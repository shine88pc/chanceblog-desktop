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
from chanceblog_desktop.service.journal import STAGE_COMMITTED, Journal  # noqa: E402

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
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(tmp.name, backend=self.backend)
        self.journal = Journal(self.ctx.workspace.journal_dir)
        self.project_id = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        self.backend.orphan = CommitInfo(ss.KO_PATH, "c" * 40, "b" * 40)

    def test_the_plan_is_an_adoption_with_the_commit_found(self):
        plan = pages_flow.plan_pages_publish(self.ctx, self.project_id)
        self.assertEqual((plan.stage, plan.path, plan.adopted), (pages_flow.STAGE_ADOPT, ss.KO_PATH, self.backend.orphan))
        self.assertTrue(any("이어받" in action for action in plan.actions))
        self.assertEqual(self.backend.count("commit"), 0)

    def test_the_run_adopts_records_pushes_and_verifies_without_committing_again(self):
        seen = {}
        self.backend.hooks["push"] = lambda: seen.update(status=ss.status_of(self.ctx, self.project_id), record=self.journal.read(self.project_id))
        self.ctx.clock.advance(hours=2)                                                    # 시각이 달라도 이어받은 파일 이름 그대로다
        report = pages_flow.run_pages_publish(self.ctx, self.project_id, confirmed=True)
        self.assertEqual((report.status, report.plan.stage, report.plan.path), (st.PUBLISHED, pages_flow.STAGE_ADOPT, ss.KO_PATH))
        self.assertEqual(self.backend.count("commit"), 0)
        self.assertEqual(self.backend.count("push"), 1)
        self.assertEqual(seen["status"], st.COMMITTED, "push 하기 전에 '기록함' 을 저장했다")
        self.assertEqual((seen["record"].stage, seen["record"].path, seen["record"].commit, seen["record"].base), (STAGE_COMMITTED, ss.KO_PATH, "c" * 40, "b" * 40))
        self.assertTrue(any("이어받았습니다" in step for step in report.steps))
        self.assertIsNone(self.journal.read(self.project_id))

    def test_a_failure_while_recording_leaves_the_found_commit_alone(self):
        from unittest import mock
        with mock.patch.object(pages_flow.Journal, "write", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})):
            error = ss.code_of(pages_flow.run_pages_publish, self.ctx, self.project_id, confirmed=True)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertIn("그대로 두었다", error.detail)
        self.assertEqual(self.backend.count("discard"), 0, "내가 만든 commit 이 아니므로 되돌리지 않는다")
        self.assertEqual(self.backend.count("push"), 0)
        self.assertEqual(ss.status_of(self.ctx, self.project_id), st.APPROVED)

    def test_a_new_commit_would_have_been_undone_in_the_same_situation(self):
        from unittest import mock
        self.backend.orphan = None
        with mock.patch.object(pages_flow.Journal, "write", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})):
            error = ss.code_of(pages_flow.run_pages_publish, self.ctx, self.project_id, confirmed=True)
        self.assertIn("되돌렸다", error.detail)
        self.assertEqual((self.backend.count("commit"), self.backend.count("discard")), (1, 1))

    def test_a_different_file_with_the_same_address_is_still_a_duplicate_even_when_adopting(self):
        self.backend.names_found = [ss.KO_PATH, "_posts/다른 분야/2026-11-02-KR-103012.md"]
        error = ss.code_of(pages_flow.plan_pages_publish, self.ctx, self.project_id)
        self.assertEqual(error.code, "DUPLICATE_SLUG", "이어받는 commit 의 파일 자신은 뺐지만 다른 이름은 그대로 중복이다")
        self.assertIn("다른 분야", error.detail)
        self.assertNotIn(ss.KO_PATH, error.detail)

    def test_the_orphans_own_file_is_not_a_duplicate_of_itself(self):
        self.backend.names_found = [ss.KO_PATH]
        self.backend.same_content_found = [ss.KO_PATH]
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, self.project_id).stage, pages_flow.STAGE_ADOPT)

    def test_cancel_undoes_an_adoptable_commit_only(self):
        report = pages_flow.cancel_pages_publish(self.ctx, self.project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISH_FAILED)
        self.assertEqual([call for call in self.backend.calls if call[0] == "discard"], [("discard", ss.KO_PATH, "c" * 40)])
        self.assertEqual(self.backend.count("push"), 0)

    def test_cancel_without_such_a_commit_is_refused_and_touches_nothing(self):
        self.backend.orphan = None
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, self.project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.assertEqual((self.backend.count("discard"), self.backend.count("commit")), (0, 0))
        self.assertEqual(ss.status_of(self.ctx, self.project_id), st.APPROVED)

    def test_an_edit_after_the_crash_resets_the_approval_so_nothing_is_adopted(self):
        from chanceblog_desktop.service import projects
        projects.edit_project(self.ctx, self.project_id, markdown=ss.ko_text(1800))
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, self.project_id, confirmed=True)
        self.assertEqual(error.code, "STATUS_TRANSITION_INVALID")
        self.assertEqual((self.backend.count("push"), self.backend.count("discard")), (0, 0))


if __name__ == "__main__":
    unittest.main()
