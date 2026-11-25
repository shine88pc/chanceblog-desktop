"""서비스 층 — commit 직후에 멈춘 올리기를 이어받는 판단(`backend.orphan_commit`)과 그 흐름(plan·run·cancel)을 **가짜 git·가짜 backend** 로 빠르게 확인한다(진짜 git·진짜 프로세스 종료 시험은 test_service_recovery).

지키는 것:
  1) 올리지 않은 commit 이 **정확히 하나**이고, 그것이 이 앱이 만든 것(제목)이며, 글 파일 **하나만 더하고**(경로가 이 글의 분야·언어로 앱이 만드는 모양), 그 파일의 내용이 승인한 글과 **한 글자도 다르지 않을 때만** 이 글의 commit 으로 본다.
     조금이라도 다르면 None(확신이 없으면 이어받지도 되돌리지도 않는다).
  2) 이어받은 흐름은 다시 commit 하지 않고, 기록을 만든 뒤 push 하며, 기록을 못 남겨도 이어받으려던 commit 을 되돌리지 않는다. 취소는 이 글의 commit 이 있을 때만 `discard_commit` 의 조건 안에서 되돌린다.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish.gitrepo import GitResult  # noqa: E402
from chanceblog_desktop.publish.pages import CommitInfo  # noqa: E402
from chanceblog_desktop.service import pages_flow  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_BUILT, Journal, PublishRecord  # noqa: E402

TEXT = "---\nlayout: post\n---\n본문\n"
SUBJECT = "글 올리기(데스크톱 앱): 제목"


class FakeGit:
    """읽기 전용 git 명령(rev-list·rev-parse·diff-tree·log·cat-file)에 정해진 답을 한다."""

    def __init__(self, **kwargs):
        self.ahead, self.head, self.parent = "1", "c" * 40, "b" * 40
        self.changes = f"A\0{ss.KO_PATH}\0"
        self.subject, self.content = SUBJECT, TEXT
        self.fail = set()
        self.calls = []
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __call__(self, cwd, args, timeout=0, input_bytes=None):
        self.calls.append(list(args))
        command = args[0]
        if command in self.fail:
            return GitResult(128, "", "fatal")
        if command == "rev-list":
            return GitResult(0, f"{self.ahead}\n", "")
        if command == "rev-parse":
            if args[-1] == "HEAD^" and "HEAD^" in self.fail:
                return GitResult(128, "", "fatal")
            return GitResult(0, (self.head if args[-1] == "HEAD" else self.parent) + "\n", "")
        if command == "diff-tree":
            return GitResult(0, self.changes, "")
        if command == "log":
            return GitResult(0, self.subject + "\n", "")
        if command == "cat-file":
            return GitResult(0, self.content, "")
        raise AssertionError(f"읽기 전용이 아닌 git 명령: {args}")


class OrphanCommitTest(unittest.TestCase):
    def found(self, **kwargs):
        fake = FakeGit(**kwargs)
        backend = GitPagesBackend(git=fake, expected_origin=ss.LOCAL_ORIGIN)
        return backend.orphan_commit(Path("repo"), TEXT, "경제·일", "ko"), fake

    def test_an_app_commit_that_adds_exactly_the_approved_post_is_recognised(self):
        info, fake = self.found()
        self.assertEqual((info.path, info.commit, info.base), (ss.KO_PATH, "c" * 40, "b" * 40))
        self.assertTrue({call[0] for call in fake.calls} <= {"rev-list", "rev-parse", "diff-tree", "log", "cat-file"}, "읽기 전용 명령만 쓴다")

    def test_anything_that_is_not_exactly_that_is_left_alone(self):
        cases = {
            "올리지 않은 commit 이 없다": {"ahead": "0"}, "올리지 않은 commit 이 둘": {"ahead": "2"}, "세어 보지 못함": {"ahead": "x"},
            "HEAD 를 못 읽음": {"fail": {"rev-parse"}}, "부모가 없다": {"fail": {"HEAD^"}},
            "글 파일을 고친 commit": {"changes": f"M\0{ss.KO_PATH}\0"}, "글 파일을 지운 commit": {"changes": f"D\0{ss.KO_PATH}\0"},
            "파일을 둘 더한 commit": {"changes": f"A\0{ss.KO_PATH}\0A\0README2.md\0"}, "변경이 없는 commit": {"changes": ""}, "diff-tree 실패": {"fail": {"diff-tree"}},
            "글이 아닌 파일": {"changes": "A\0README2.md\0"}, "다른 분야 폴더": {"changes": "A\0_posts/다른 분야/2026-11-02-KR-103012.md\0"},
            "언어 표시가 다르다": {"changes": "A\0_posts/경제·일/2026-11-02-EN-103012.md\0"}, "불가능한 날짜": {"changes": "A\0_posts/경제·일/2026-02-30-KR-103012.md\0"},
            "앱의 commit 이 아니다": {"subject": "내가 만든 commit"}, "제목을 못 읽음": {"fail": {"log"}},
            "내용이 다르다": {"content": TEXT + "한 줄 더\n"}, "내용을 못 읽음": {"fail": {"cat-file"}},
        }
        for name, kwargs in cases.items():
            with self.subTest(case=name):
                self.assertIsNone(self.found(**kwargs)[0], name)

    def test_the_category_and_language_come_from_the_approved_post_not_from_the_commit(self):
        fake = FakeGit()
        backend = GitPagesBackend(git=fake, expected_origin=ss.LOCAL_ORIGIN)
        self.assertIsNotNone(backend.orphan_commit(Path("repo"), TEXT, "경제·일", "ko"))
        self.assertIsNone(backend.orphan_commit(Path("repo"), TEXT, "다른 분야", "ko"))
        self.assertIsNone(backend.orphan_commit(Path("repo"), TEXT, "경제·일", "en"))
        self.assertIsNone(backend.orphan_commit(Path("repo"), TEXT + "x", "경제·일", "ko"))


class AdoptFlowTest(unittest.TestCase):
    """이어받기 — 새 흐름(PUBPR)에서는 올리기 전에 적어 둔 발행 기록 `built`(가지·커밋)를 이어받는다(옛 방식의 '이 PC 에 남은 commit' 이어받기는 없어졌고, 그 commit 은 `--cancel` 로 되돌리기만 한다)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(tmp.name, backend=self.backend)
        self.journal = Journal(self.ctx.workspace.journal_dir)
        self.project_id = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        self.backend.orphan = CommitInfo(ss.KO_PATH, "c" * 40, "b" * 40)             # 옛 방식으로 남은 commit(취소 시험용)

    def leave_a_built_record(self):
        """올리기 전에 멈춘 앞선 실행이 남긴 기록 — 가지 이름은 이 글의 승인한 내용에서 나온다."""
        from chanceblog_desktop.publish import pages
        from chanceblog_desktop.render.pages import PagesPost
        with self.ctx.store() as store:
            text = store.load(self.project_id).variant("github_pages").rendered
        post = PagesPost(ss.KO_PATH, text, "경제·일", "ko")
        record = PublishRecord(self.project_id, ss.KO_PATH, "c" * 40, "b" * 40, STAGE_BUILT, pages.branch_name(post))
        self.journal.write(record)
        return record

    def test_the_plan_is_an_adoption_with_the_commit_found(self):
        record = self.leave_a_built_record()
        plan = pages_flow.plan_pages_publish(self.ctx, self.project_id)
        self.assertEqual((plan.stage, plan.path, plan.branch), (pages_flow.STAGE_BRANCH, ss.KO_PATH, record.branch))
        self.assertEqual(plan.resumed, record)
        self.assertEqual(self.backend.count("build_branch_commit"), 0)

    def test_the_run_adopts_records_pushes_and_verifies_without_committing_again(self):
        record = self.leave_a_built_record()
        seen = {}
        self.backend.hooks["push_branch"] = lambda: seen.update(status=ss.status_of(self.ctx, self.project_id), record=self.journal.read(self.project_id))
        self.ctx.clock.advance(hours=2)                                                    # 시각이 달라도 이어받은 파일 이름 그대로다
        report = pages_flow.run_pages_publish(self.ctx, self.project_id, confirmed=True)
        self.assertEqual((report.status, report.plan.stage, report.plan.path), (st.MERGE_PENDING, pages_flow.STAGE_BRANCH, ss.KO_PATH))
        self.assertEqual(self.backend.count("build_branch_commit"), 0, "다시 만들지 않았다")
        self.assertEqual(self.backend.count("push_branch"), 1)
        self.assertEqual(seen["status"], st.APPROVED, "올리기 전에는 상태가 그대로다")
        self.assertEqual(seen["record"], record, "이어받은 기록 그대로다")
        self.assertTrue(any("이어받았습니다" in step for step in report.steps))
        self.assertEqual(self.journal.read(self.project_id).stage, "branch_pushed")
        self.assertEqual(st.split_remote_id(projects_remote_id(self.ctx, self.project_id)), (record.branch, record.commit))

    def test_a_failure_while_recording_leaves_the_found_commit_alone(self):
        """이어받은 가지를 올린 **뒤** 기록을 못 남기면(`branch_pushed` 쓰기 실패) 올라간 것은 그대로 두고 같은 명령을 다시 하라고 알린다 — 같은 일을 두 번 해도 같은 결과라서 다시 하면 기록만 마친다."""
        from unittest import mock
        record = self.leave_a_built_record()
        with mock.patch.object(pages_flow.Journal, "write", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})):
            error = ss.code_of(pages_flow.run_pages_publish, self.ctx, self.project_id, confirmed=True)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertIn("이미 새 가지에 올라갔다", error.detail)
        self.assertEqual(self.backend.count("discard"), 0, "아무것도 되돌리지 않는다")
        self.assertEqual(self.backend.count("push_branch"), 1)
        self.assertEqual(ss.status_of(self.ctx, self.project_id), st.APPROVED)
        self.backend.push_already = True                                                    # 다시 하면 원격에 같은 끝이 이미 있어 보내지 않고 이어 간다
        report = pages_flow.run_pages_publish(self.ctx, self.project_id, confirmed=True)
        self.assertEqual((report.status, self.journal.read(self.project_id).branch), (st.MERGE_PENDING, record.branch))

    def test_a_new_commit_would_have_been_undone_in_the_same_situation(self):
        """새 흐름에서 처음부터 하는 실행은 올리기 전에 `built` 를 적는다 — 그 기록을 못 남기면 올리지 않고 멈춘다. 만든 커밋은 객체일 뿐이라 되돌릴 것이 없다(`discard` 0)."""
        from unittest import mock
        self.backend.orphan = None
        with mock.patch.object(pages_flow.Journal, "write", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})):
            error = ss.code_of(pages_flow.run_pages_publish, self.ctx, self.project_id, confirmed=True)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertEqual((self.backend.count("build_branch_commit"), self.backend.count("push_branch"), self.backend.count("discard")), (1, 0, 0))
        self.assertEqual(ss.status_of(self.ctx, self.project_id), st.APPROVED)

    def test_a_different_file_with_the_same_address_is_still_a_duplicate_even_when_adopting(self):
        """처음 하는 실행은 같은 주소의 다른 파일을 중복으로 막는다. 이어받는 실행은 이미 만든 커밋을 올릴 뿐이라 다시 점검하지 않는다 — 그 사이 생긴 같은 주소는 병합 확인(`PAGES_MERGE_DIFFERENT`)이 잡는다."""
        self.backend.names_found = [ss.KO_PATH, "_posts/다른 분야/2026-11-02-KR-103012.md"]
        error = ss.code_of(pages_flow.plan_pages_publish, self.ctx, self.project_id)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertIn("다른 분야", error.detail)
        self.leave_a_built_record()
        self.assertIsNotNone(pages_flow.plan_pages_publish(self.ctx, self.project_id).resumed)

    def test_the_orphans_own_file_is_not_a_duplicate_of_itself(self):
        """이어받는 실행에서 자기 파일 이름이 목록에 있어도(원격 main 에 같은 이름이 생긴 것이 아니다) 계획이 막히지 않는다."""
        self.backend.names_found = [ss.KO_PATH]
        self.backend.same_content_found = [ss.KO_PATH]
        self.leave_a_built_record()
        plan = pages_flow.plan_pages_publish(self.ctx, self.project_id)
        self.assertEqual((plan.stage, plan.resumed is not None), (pages_flow.STAGE_BRANCH, True))

    def test_cancel_undoes_an_adoptable_commit_only(self):
        report = pages_flow.cancel_pages_publish(self.ctx, self.project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISH_FAILED)
        self.assertEqual([call for call in self.backend.calls if call[0] == "discard"], [("discard", ss.KO_PATH, "c" * 40)])
        self.assertEqual(self.backend.count("push_branch"), 0)

    def test_cancel_without_such_a_commit_is_refused_and_touches_nothing(self):
        self.backend.orphan = None
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, self.project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.assertEqual((self.backend.count("discard"), self.backend.count("build_branch_commit")), (0, 0))
        self.assertEqual(ss.status_of(self.ctx, self.project_id), st.APPROVED)

    def test_an_edit_after_the_crash_resets_the_approval_so_nothing_is_adopted(self):
        from chanceblog_desktop.service import projects
        self.leave_a_built_record()
        projects.edit_project(self.ctx, self.project_id, markdown=ss.ko_text(1800))
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, self.project_id, confirmed=True)
        self.assertEqual(error.code, "STATUS_TRANSITION_INVALID")
        self.assertEqual((self.backend.count("push_branch"), self.backend.count("discard"), self.backend.count("build_branch_commit")), (0, 0, 0))

    def test_a_built_record_for_an_older_text_is_not_adopted_after_a_new_approval(self):
        """새 흐름의 새 시험 — 가지 이름은 승인한 글의 내용 해시를 담고 있어서, 고쳐 다시 승인한 글은 옛 `built` 기록을 이어받지 않는다(낡은 커밋을 올리지 않는다)."""
        from chanceblog_desktop.service import projects, review
        self.leave_a_built_record()
        projects.edit_project(self.ctx, self.project_id, markdown=ss.ko_text(1800))
        review.request_review(self.ctx, self.project_id, "github_pages", pages=ss.KO_PARAMS)
        review.grant_approval(self.ctx, self.project_id, "github_pages")
        plan = pages_flow.plan_pages_publish(self.ctx, self.project_id)
        self.assertIsNone(plan.resumed)
        report = pages_flow.run_pages_publish(self.ctx, self.project_id, confirmed=True)
        self.assertEqual(report.status, st.MERGE_PENDING)
        self.assertEqual(self.backend.count("build_branch_commit"), 1, "새 글은 새로 만든다")


def projects_remote_id(ctx, project_id):
    with ctx.store() as store:
        return store.load(project_id).variant("github_pages").remote_id


def setUpModule():
    ss.external_write_on()                                   # 이 시험은 게시 흐름을 쓴다 — 외부 Write 관문을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    ss.external_write_off()


if __name__ == "__main__":
    unittest.main()
