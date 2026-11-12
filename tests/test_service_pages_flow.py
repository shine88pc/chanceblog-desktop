"""서비스 층 — GitHub Pages 올리기 흐름 시험(가짜 backend: git·네트워크 없음). 연결한 chanceblog 의 main 에 실제로 올라가는 흐름이라 안전 규칙을 하나씩 어겨 보는 변이 점검으로도 확인한다(T2).

지키는 것:
  1) **확인 없이는 올리지 않는다**: `confirmed is True` 가 아니면 commit 도 push 도 점검도 하지 않는다. 미리 보기(dry run)는 읽기만 한다(저장소·데이터 파일·상태 그대로).
  2) **승인된 글만, 승인한 그대로**: 승인 전·승인이 풀린·실패한 글은 STATUS_TRANSITION_INVALID. 올라가는 내용은 승인한 렌더링 그대로다.
  3) **검사를 통과해야 한다(fail closed)**: 게이트·연결한 저장소 확인·같은 주소(slug) 확인·공개 주소 계산 중 하나라도 걸리면 commit 하지 않는다.
  4) **상태는 사실을 따라간다**: APPROVED → COMMITTED(push 보다 먼저 저장) → PUSHED(공개 확인보다 먼저 저장) → PUBLISHED. 공개 주소가 아직 안 열리면 PUSHED 로 두고 check-deploy 로 마친다.
  5) **실패해도 일관되고 되돌릴 수 있다**: push 가 막히면 COMMITTED 로 남겨 이어서 올리고(다시 commit 하지 않는다), 같은 주소 글이 먼저 올라가 있으면 글 기록을 되돌리고 PUBLISH_FAILED 로 남기며,
     commit 뒤 기록을 못 남기면 방금 만든 commit 을 되돌린다. 올리기 취소는 확인이 있어야 하고 `discard_commit` 이 허락할 때만 된다.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import gate, pages_flow, projects, review  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_COMMITTED, STAGE_PUSHED, Journal  # noqa: E402

EN_PATH = "_posts/Society & Policy/2026-11-02-EN-103012.md"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)
        self.journal = Journal(self.ctx.workspace.journal_dir)

    def approved(self, **kwargs):
        project_id = ss.make_approved(self.ctx, **kwargs)
        self.backend.calls.clear()                               # 검토 요청의 미리 보기가 부른 것(공개 주소 계산)은 세지 않는다
        return project_id

    def status(self, project_id):
        return ss.status_of(self.ctx, project_id)

    def variant(self, project_id):
        return projects.show_project(self.ctx, project_id).variant("github_pages")

    def run_publish(self, project_id, **kwargs):
        kwargs.setdefault("confirmed", True)
        return pages_flow.run_pages_publish(self.ctx, project_id, **kwargs)

    def stored_rendering(self, project_id):
        with self.ctx.store() as store:
            return store.load(project_id).variant("github_pages").rendered

    def fail_the_store_after(self, call_name):
        """backend 가 `call_name` 을 부른 뒤로는 상태 저장소를 열 수 없다고 한다(잠김). 되돌리는 함수를 돌려준다."""
        real = self.ctx.store

        def failing():
            if self.backend.count(call_name):
                raise AppError("STORE_LOCKED")
            return real()

        self.ctx.store = failing
        return lambda: setattr(self.ctx, "store", real)


class PlanTest(Base):
    def test_the_plan_of_an_approved_post_names_the_file_and_the_address_and_changes_nothing(self):
        project_id = self.approved()
        before = ss.tree_snapshot(self.ctx.workspace.root)
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.stage, plan.status, plan.path, plan.expected_url, plan.lang, plan.category), (pages_flow.STAGE_COMMIT, st.APPROVED, ss.KO_PATH, ss.KO_URL, "ko", "경제·일"))
        self.assertEqual(plan.text, self.stored_rendering(project_id))
        self.assertTrue(plan.gates.ok)
        self.assertEqual(plan.size_bytes, len(plan.text.encode("utf-8")))
        self.assertTrue(any(ss.KO_PATH in action for action in plan.actions))
        self.assertEqual(self.backend.names(), ["inspect", "orphan_commit", "unpushed_count", "duplicates", "same_content", "expected_url"], "읽기만 한다 — commit·push·되돌리기는 부르지 않는다")
        self.assertEqual(ss.tree_snapshot(self.ctx.workspace.root), before, "데이터 폴더에 아무것도 쓰지 않았다(발행 기록도 없다)")
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.status(project_id), st.APPROVED)

    def test_the_preview_report_says_nothing_was_done_and_how_to_go_on(self):
        project_id = self.approved()
        report = pages_flow.preview_publish(self.ctx, project_id)
        self.assertEqual((report.dry_run, report.steps, report.status, report.verified, report.pending_verification), (True, (), st.APPROVED, False, False))
        self.assertTrue(any("--yes" in step for step in report.next_steps))
        self.assertTrue(any("아무것도 하지 않았" in note for note in report.notes))
        self.assertEqual(self.backend.count("commit") + self.backend.count("push"), 0)

    def test_posts_that_are_not_approved_cannot_be_planned_or_published(self):
        fresh = projects.new_project(self.ctx, "새 글", ss.ko_text()).project_id
        reviewed = projects.new_project(self.ctx, "검토 중", ss.ko_text()).project_id
        review.request_review(self.ctx, reviewed, "github_pages", pages=ss.KO_PARAMS)
        revoked = self.approved(title="승인했다 거둔 글")
        review.revoke_approval(self.ctx, revoked, "github_pages")
        edited = self.approved(title="승인 뒤 고친 글")
        projects.edit_project(self.ctx, edited, markdown=ss.ko_text(1700))
        for name, project_id, status in (("시작 전", fresh, st.NOT_STARTED), ("검토 중", reviewed, st.REVIEW_REQUIRED), ("승인을 거둠", revoked, st.REVIEW_REQUIRED), ("승인 뒤 고침", edited, st.DRAFT_GENERATED)):
            with self.subTest(case=name):
                for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.preview_publish(self.ctx, project_id), lambda: self.run_publish(project_id)):
                    error = ss.code_of(call)
                    self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", status))
                    self.assertIn("승인(APPROVED)한 글만", error.detail, "승인되지 않았다는 이유로 거절한다(다른 검사에 우연히 걸린 것이 아니다)")
        self.assertEqual(self.backend.calls, [], "승인되지 않은 글은 저장소를 들여다보지도 않는다")

    def test_a_post_whose_publish_failed_must_be_reviewed_and_approved_again(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("DUPLICATE_SLUG")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        self.assertEqual(self.status(project_id), st.PUBLISH_FAILED)
        self.backend.calls.clear()
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "STATUS_TRANSITION_INVALID")
        self.assertIn("승인(APPROVED)한 글만", error.detail)
        self.assertEqual(self.backend.calls, [], "실패한 글은 저장소를 들여다보지도, commit 하지도 않는다")

    def test_the_gates_run_again_when_publishing_so_a_tightened_rule_stops_an_old_approval(self):
        project_id = self.approved()
        with mock.patch.dict(gate.LENGTH_MIN, {"ko": 10 ** 6}):
            for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: self.run_publish(project_id)):
                error = ss.code_of(call)
                self.assertEqual(error.code, "CHECK_FAILED")
                self.assertIn("LEN_SHORT", error.slots["걸린 항목 목록"])
        self.assertEqual(self.backend.count("commit"), 0)
        self.assertEqual(self.status(project_id), st.APPROVED)

    def test_a_key_that_got_into_the_approved_text_is_blocked_at_publish_time_too(self):
        project_id = self.approved()
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.variants["github_pages"].rendered += f"\n실수로 {ss.KEY} 가 들어갔다\n"
            store.save(project)
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
        self.assertNotIn(ss.KEY, error.detail + error.log_line())
        self.assertEqual(self.backend.count("commit"), 0)

    def test_a_damaged_stored_rendering_is_refused(self):
        project_id = self.approved()
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.variants["github_pages"].rendered = "머리말이 없는 글"
            store.save(project)
        self.assertEqual(ss.code_of(self.run_publish, project_id).code, "CONTENT_INVALID")

    def test_without_a_connected_folder_nothing_happens(self):
        ctx = ss.make_ctx(self.tmp / "none", backend=self.backend, repo=None)
        project_id = ss.make_approved(ctx)
        self.assertEqual(ss.code_of(pages_flow.run_pages_publish, ctx, project_id, confirmed=True).code, "PAGES_LOCAL_REPO_INVALID")
        self.assertEqual(self.backend.names(), [])

    def test_a_connected_folder_that_is_not_in_order_stops_before_any_commit(self):
        project_id = self.approved()
        for code in ("PAGES_LOCAL_REPO_INVALID", "PAGES_LOCAL_REPO_DIRTY", "PAGES_LOCAL_REPO_NOT_MAIN", "PAGES_LOCAL_REPO_DIVERGED", "GIT_NOT_INSTALLED"):
            with self.subTest(code=code):
                self.backend.inspect_error = AppError(code)
                self.assertEqual(ss.code_of(self.run_publish, project_id).code, code)
        self.assertEqual((self.backend.count("commit"), self.backend.count("push")), (0, 0))
        self.assertEqual(self.status(project_id), st.APPROVED)

    def test_a_post_with_the_same_address_already_in_the_repository_is_a_duplicate(self):
        project_id = self.approved()
        self.backend.names_found = ["_posts/다른 분야/2026-11-02-KR-103012.md"]
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: self.run_publish(project_id)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "DUPLICATE_SLUG")
            self.assertIn("다른 분야", error.detail)
        self.assertEqual(self.backend.count("commit"), 0)

    def test_another_post_already_online_at_the_same_address_gets_the_next_second_instead(self):
        first = self.approved(title="첫 글")
        self.run_publish(first)
        self.assertEqual(self.status(first), st.PUBLISHED)
        second = self.approved(title="둘째 글")                       # 같은 시계 — 같은 파일 이름·같은 공개 주소가 될 뻔했다 → 앱이 다음 초의 이름을 쓴다
        report = self.run_publish(second)
        self.assertEqual(report.plan.path, "_posts/경제·일/2026-11-02-KR-103013.md")
        self.assertNotEqual(report.url, self.variant(first).published_url, "다른 공개 주소다")
        self.assertEqual(self.backend.count("commit"), 1, "둘째 글은 한 번 commit 했다")
        self.assertEqual(self.status(second), st.PUBLISHED)

    def test_another_post_in_the_middle_of_publishing_blocks_the_same_file_name(self):
        first = self.approved(title="첫 글")
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.run_publish(first)
        second = self.approved(title="둘째 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).path, "_posts/경제·일/2026-11-02-KR-103013.md", "올리는 중인 글의 이름을 피해 다음 초로")

    def test_a_post_that_was_pushed_but_not_yet_verified_also_holds_its_file_name(self):
        first = self.approved(title="첫 글")
        self.run_publish(first, wait=False)
        self.assertEqual(self.status(first), st.PUSHED)
        second = self.approved(title="둘째 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).path, "_posts/경제·일/2026-11-02-KR-103013.md", "올라간 글의 이름도 피한다")

    def test_a_different_second_gives_a_different_file_name_so_no_duplicate(self):
        first = self.approved(title="첫 글")
        self.run_publish(first)
        self.ctx.clock.advance(seconds=1)
        second = self.approved(title="둘째 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).path, "_posts/경제·일/2026-11-02-KR-103013.md")

    def test_a_site_that_would_not_show_the_post_stops_it_before_the_commit(self):
        project_id = self.approved()
        self.backend.url_error = AppError("CONTENT_INVALID", {"항목": "공개 설정"}, detail="이 글은 사이트에 공개되지 않는다: 미래 날짜")
        self.assertEqual(ss.code_of(self.run_publish, project_id).code, "CONTENT_INVALID")
        self.assertEqual(self.backend.count("commit"), 0)

    def test_the_file_name_is_made_from_the_clock_in_korean_time_and_the_category_and_language(self):
        project_id = self.approved(title="English post", text=ss.en_text(), params=ss.EN_PARAMS)
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.path, plan.lang), (EN_PATH, "en"))
        self.ctx.clock.advance(hours=15)                              # UTC 16:30 → 한국 시각 다음 날 01:30
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, project_id).path, "_posts/Society & Policy/2026-11-03-EN-013012.md")

    def test_the_text_that_goes_in_is_exactly_the_approved_rendering(self):
        project_id = self.approved()
        approved_text = self.stored_rendering(project_id)
        self.run_publish(project_id)
        commit_call = next(call for call in self.backend.calls if call[0] == "commit")
        self.assertEqual(commit_call[3], approved_text)
        self.assertEqual(commit_call[2], "에너지 절약 습관", "commit 제목은 글 제목이다")


class ConfirmationTest(Base):
    def test_without_the_confirmation_nothing_at_all_happens(self):
        project_id = self.approved()
        for confirmed in (False, None, 0, 1, 2, "yes", "True", "--yes", [True], {"yes": True}):
            with self.subTest(confirmed=confirmed):
                error = ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=confirmed)
                self.assertEqual(error.code, "CONFIRMATION_REQUIRED")
        self.assertEqual(self.backend.calls, [], "저장소를 들여다보지도 않는다")
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertIsNone(self.journal.read(project_id))

    def test_the_confirmation_is_a_required_argument(self):
        project_id = self.approved()
        with self.assertRaises(TypeError):
            pages_flow.run_pages_publish(self.ctx, project_id)
        self.assertEqual(self.backend.calls, [])

    def test_cancelling_also_needs_the_confirmation(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        calls = len(self.backend.calls)
        for confirmed in (False, None, 1, "yes"):
            with self.subTest(confirmed=confirmed):
                self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=confirmed).code, "CONFIRMATION_REQUIRED")
        self.assertEqual(len(self.backend.calls), calls)
        self.assertEqual(self.status(project_id), st.COMMITTED)


class HappyPathTest(Base):
    def test_a_confirmed_publish_goes_commit_push_verify_and_saves_each_step_before_the_next(self):
        project_id = self.approved()
        seen = {}
        for name in ("commit", "push", "check_deployed"):
            self.backend.hooks[name] = lambda name=name: seen.setdefault(name, (self.status(project_id), self.journal.read(project_id)))
        report = self.run_publish(project_id)
        self.assertEqual(seen["commit"][0], st.APPROVED)
        self.assertEqual(seen["push"][0], st.COMMITTED, "push 하기 전에 '기록함' 을 저장했다")
        self.assertEqual((seen["push"][1].stage, seen["push"][1].path), (STAGE_COMMITTED, ss.KO_PATH))
        self.assertEqual(seen["check_deployed"][0], st.PUSHED, "공개 확인 전에 '올림' 을 저장했다")
        self.assertEqual(seen["check_deployed"][1].stage, STAGE_PUSHED)
        self.assertEqual([name for name in self.backend.names() if name in ("commit", "push", "check_deployed")], ["commit", "push", "check_deployed"])
        self.assertEqual((report.status, report.verified, report.pending_verification, report.url, report.dry_run), (st.PUBLISHED, True, False, ss.KO_URL, False))
        variant = self.variant(project_id)
        self.assertEqual((variant.status, variant.published_url, variant.published_at, variant.error_code), (st.PUBLISHED, ss.KO_URL, "2026-11-02T01:30:12Z", None))
        self.assertIsNone(self.journal.read(project_id), "끝난 글의 발행 기록은 지운다")
        with self.ctx.store() as store:
            self.assertEqual(store.load(project_id).variant("github_pages").remote_id, "d" * 40, "올린 커밋 번호를 남긴다")

    def test_the_report_tells_what_was_done_in_plain_words_and_converts_to_plain_data(self):
        project_id = self.approved()
        report = self.run_publish(project_id)
        self.assertEqual(len(report.steps), 3)
        self.assertTrue(any("기록(commit)" in step for step in report.steps))
        self.assertTrue(any("main 에 올렸" in step for step in report.steps))
        data = report.to_dict()
        self.assertEqual((data["status"], data["plan"]["path"], "text" in data["plan"]), (st.PUBLISHED, ss.KO_PATH, False))
        self.assertIn("text", report.to_dict(with_text=True)["plan"])
        json.dumps(data)

    def test_the_time_in_the_file_name_is_the_moment_of_the_run_not_of_the_approval(self):
        project_id = self.approved()
        self.ctx.clock.advance(hours=2, minutes=5, seconds=7)
        report = self.run_publish(project_id)
        self.assertEqual(report.plan.path, "_posts/경제·일/2026-11-02-KR-123519.md")

    def test_the_deadline_and_interval_reach_the_deploy_check(self):
        project_id = self.approved()
        self.run_publish(project_id, deadline=90, interval=3)
        self.assertIn(("check_deployed", ss.KO_PATH, 90, 3), self.backend.calls)

    def test_a_published_post_is_left_alone_when_asked_again(self):
        project_id = self.approved()
        self.run_publish(project_id)
        calls = len(self.backend.calls)
        for call in (lambda: self.run_publish(project_id), lambda: pages_flow.preview_publish(self.ctx, project_id), lambda: pages_flow.check_pages_deploy(self.ctx, project_id)):
            report = call()
            self.assertEqual((report.status, report.url, report.plan.stage), (st.PUBLISHED, ss.KO_URL, pages_flow.STAGE_DONE))
        self.assertEqual(len(self.backend.calls), calls, "이미 공개된 글은 저장소·네트워크를 부르지 않는다")


class FailureTest(Base):
    def test_a_commit_that_fails_leaves_the_post_approved_with_nothing_recorded(self):
        project_id = self.approved()
        for code in ("PAGES_LOCAL_REPO_DIRTY", "GIT_IDENTITY_MISSING", "DUPLICATE_SLUG", "FILE_WRITE_FAILED"):
            with self.subTest(code=code):
                self.backend.commit_error = AppError(code)
                self.assertEqual(ss.code_of(self.run_publish, project_id).code, code)
                self.assertEqual(self.status(project_id), st.APPROVED)
                self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.backend.count("push"), 0)
        self.assertEqual(self.backend.count("discard"), 0, "commit 이 없으니 되돌릴 것도 없다")

    def test_a_push_that_fails_for_a_temporary_reason_leaves_the_post_committed_and_the_next_run_only_pushes(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK", detail="Could not resolve host")]
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "GIT_PUSH_NETWORK")
        self.assertIn("같은 명령을 다시 실행", error.detail)
        self.assertIn("--cancel --yes", error.detail)
        self.assertEqual(self.status(project_id), st.COMMITTED)
        record = self.journal.read(project_id)
        self.assertEqual((record.path, record.stage), (ss.KO_PATH, STAGE_COMMITTED))
        self.assertEqual(self.backend.count("discard"), 0, "일시적인 실패는 글 기록을 되돌리지 않는다")
        self.ctx.clock.advance(hours=3)                                   # 다음 실행은 새 시각이 아니라 기록해 둔 같은 파일을 올린다
        report = self.run_publish(project_id)
        self.assertEqual((self.backend.count("commit"), self.backend.count("push")), (1, 2), "다시 commit 하지 않고 push 만 했다")
        self.assertEqual((report.status, report.plan.stage, report.plan.path), (st.PUBLISHED, pages_flow.STAGE_PUSH, ss.KO_PATH))
        self.assertEqual(self.status(project_id), st.PUBLISHED)

    def test_every_temporary_kind_of_push_failure_keeps_the_commit_for_a_retry(self):
        for code in ("GIT_PUSH_AUTH", "GIT_PUSH_NETWORK", "GIT_PUSH_REJECTED", "NETWORK_TIMEOUT", "PAGES_LOCAL_REPO_DIVERGED", "PAGES_LOCAL_REPO_NOT_MAIN", "UNEXPECTED_ERROR", "SECRET_IN_TEXT_BLOCKED"):
            with self.subTest(code=code):
                project_id = self.approved(title=f"글 {code}")
                self.ctx.clock.advance(seconds=1)
                self.backend.push_errors = [AppError(code)]
                self.assertEqual(ss.code_of(self.run_publish, project_id).code, code)
                self.assertEqual(self.status(project_id), st.COMMITTED)
                self.assertIsNotNone(self.journal.read(project_id))
                self.backend.push_errors = [None]
                self.run_publish(project_id)
                self.assertEqual(self.status(project_id), st.PUBLISHED)
        self.assertEqual(self.backend.count("discard"), 0)

    def test_a_duplicate_found_while_pushing_undoes_the_commit_and_marks_the_post_failed(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("DUPLICATE_SLUG", detail="원격 main 에 같은 이름의 글이 이미 있다")]
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertIn("되돌렸다", error.detail)
        self.assertEqual([call for call in self.backend.calls if call[0] == "discard"], [("discard", ss.KO_PATH, "c" * 40)])
        variant = self.variant(project_id)
        self.assertEqual((variant.status, variant.error_code), (st.PUBLISH_FAILED, "DUPLICATE_SLUG"))
        self.assertIsNone(self.journal.read(project_id))
        review.request_review(self.ctx, project_id, "github_pages", pages=ss.KO_PARAMS)       # 글을 다시 만들어 검토·승인하면 새로 올릴 수 있다
        review.grant_approval(self.ctx, project_id, "github_pages")
        self.ctx.clock.advance(seconds=5)
        self.assertEqual(self.run_publish(project_id).status, st.PUBLISHED)

    def test_if_the_commit_cannot_be_undone_after_a_duplicate_the_post_stays_committed_and_says_so(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("DUPLICATE_SLUG")]
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED", detail="지금 HEAD 가 되돌릴 글 커밋이 아니다")
        self.backend.head_has_post = True                                # 글 커밋이 아직 저장소에 있다
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertIn("되돌리지 못했다", error.detail)
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.assertIsNotNone(self.journal.read(project_id))

    def test_a_record_that_cannot_be_saved_after_the_commit_undoes_the_commit(self):
        project_id = self.approved()
        with mock.patch.object(pages_flow.Journal, "write", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})):
            error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertIn("되돌렸다", error.detail)
        self.assertEqual(self.backend.count("discard"), 1)
        self.assertEqual(self.backend.count("push"), 0)
        self.assertEqual(self.status(project_id), st.APPROVED, "저장소도 상태도 처음 그대로다")
        self.assertIsNone(self.journal.read(project_id))

    def test_the_same_when_the_state_cannot_be_saved_after_the_commit(self):
        project_id = self.approved()
        restore = self.fail_the_store_after("commit")
        error = ss.code_of(self.run_publish, project_id)
        restore()
        self.assertEqual(error.code, "STORE_LOCKED")
        self.assertIn("되돌렸다", error.detail)
        self.assertEqual((self.backend.count("discard"), self.backend.count("push")), (1, 0))
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertIsNone(self.journal.read(project_id))

    def test_if_the_undo_fails_too_both_problems_are_reported(self):
        project_id = self.approved()
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED")
        with mock.patch.object(pages_flow.Journal, "write", side_effect=AppError("FILE_WRITE_FAILED")):
            error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertIn("되돌리지 못했다(PAGES_LOCAL_REPO_DIVERGED)", error.detail)

    def test_an_interruption_after_the_commit_also_undoes_it(self):
        project_id = self.approved()
        with mock.patch.object(pages_flow.Journal, "write", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_publish(project_id)
        self.assertEqual(self.backend.count("discard"), 1)
        self.assertEqual(self.status(project_id), st.APPROVED)

    def test_a_failure_to_record_the_push_says_the_post_is_online_and_the_next_run_finishes_the_record(self):
        project_id = self.approved()
        real_write = Journal.write
        writes = []

        def flaky(journal, record):
            writes.append(record.stage)
            if len(writes) == 2:
                raise AppError("FILE_WRITE_FAILED")
            return real_write(journal, record)

        with mock.patch.object(pages_flow.Journal, "write", flaky):
            error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertIn("이미 원격 main 에 올라갔다", error.detail)
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.backend.push_already = True                                  # 다시 push 하면 '이미 올라가 있다' 로 끝난다
        report = self.run_publish(project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertTrue(any("이미 원격 main 에 올라가 있어" in step for step in report.steps))
        self.assertEqual(self.backend.count("commit"), 1)

    def test_a_failure_to_record_the_state_after_the_push_leaves_it_committed_and_a_rerun_completes_it(self):
        project_id = self.approved()
        restore = self.fail_the_store_after("push")
        error = ss.code_of(self.run_publish, project_id)
        restore()
        self.assertEqual(error.code, "STORE_LOCKED")
        self.assertIn("이미 원격 main 에 올라갔다", error.detail)
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.backend.push_already = True
        self.assertEqual(self.run_publish(project_id).status, st.PUBLISHED)


class VerificationTest(Base):
    def test_a_post_that_is_not_open_yet_is_pushed_and_unverified_not_failed_and_check_deploy_finishes_it(self):
        project_id = self.approved()
        self.backend.deploy_errors = [AppError("PAGES_DEPLOY_NOT_VISIBLE", detail="404")]
        report = self.run_publish(project_id)
        self.assertEqual((report.status, report.pending_verification, report.verified), (st.PUSHED, True, False))
        self.assertTrue(any("check-deploy" in step for step in report.next_steps))
        self.assertIn("확인 기록: 404", report.notes, "확인 코드가 남긴 기록을 함께 보여 준다")
        variant = self.variant(project_id)
        self.assertEqual((variant.status, variant.published_url, variant.published_at, variant.error_code), (st.PUSHED, None, None, None), "상태를 망가뜨리지 않았다")
        self.assertEqual(self.journal.read(project_id).stage, STAGE_PUSHED)
        later = pages_flow.check_pages_deploy(self.ctx, project_id)
        self.assertEqual((later.status, later.url, later.verified), (st.PUBLISHED, ss.KO_URL, True))
        self.assertEqual(self.variant(project_id).published_url, ss.KO_URL)
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual((self.backend.count("commit"), self.backend.count("push")), (1, 1), "확인을 다시 할 뿐 다시 올리지 않는다")

    def test_a_post_that_stays_closed_keeps_a_consistent_state_for_as_long_as_it_takes(self):
        project_id = self.approved()
        self.backend.deploy_errors = [AppError("PAGES_DEPLOY_NOT_VISIBLE")] * 3
        self.run_publish(project_id)
        for _ in range(2):
            report = pages_flow.check_pages_deploy(self.ctx, project_id)
            self.assertEqual((report.status, report.pending_verification), (st.PUSHED, True))
            self.assertEqual(self.status(project_id), st.PUSHED)
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)

    def test_no_wait_pushes_but_does_not_wait_for_the_address(self):
        project_id = self.approved()
        report = self.run_publish(project_id, wait=False)
        self.assertEqual((report.status, report.pending_verification, self.backend.count("check_deployed")), (st.PUSHED, True, 0))
        self.assertTrue(any("check-deploy" in step for step in report.next_steps))
        self.assertEqual(self.status(project_id), st.PUSHED)

    def test_another_problem_with_the_check_is_raised_with_a_note_and_leaves_the_post_pushed(self):
        project_id = self.approved()
        self.backend.deploy_errors = [AppError("CONTENT_INVALID", {"항목": "배포 확인 설정"})]
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertIn("check-deploy", error.detail)
        self.assertEqual(self.status(project_id), st.PUSHED)

    def test_a_failure_to_record_the_published_state_says_so_and_check_deploy_completes_it(self):
        project_id = self.approved()
        restore = self.fail_the_store_after("check_deployed")
        error = ss.code_of(self.run_publish, project_id)
        restore()
        self.assertEqual(error.code, "STORE_LOCKED")
        self.assertIn("check-deploy 를 다시 실행", error.detail)
        self.assertEqual(self.status(project_id), st.PUSHED)
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)

    def test_check_deploy_only_works_for_a_post_that_was_pushed(self):
        project_id = self.approved()
        error = ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        self.assertEqual(ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id).slots["현재 상태"], st.COMMITTED)
        self.assertEqual(self.backend.count("check_deployed"), 0)

    def test_check_deploy_passes_its_deadline_and_a_zero_deadline_means_one_look(self):
        project_id = self.approved()
        self.run_publish(project_id, wait=False)
        pages_flow.check_pages_deploy(self.ctx, project_id, deadline=0)
        self.assertIn(("check_deployed", ss.KO_PATH, 0, pages_flow.DEFAULT_INTERVAL), self.backend.calls)

    def test_check_deploy_does_not_check_the_gates_or_the_repository_state(self):
        project_id = self.approved()
        self.run_publish(project_id, wait=False)
        self.backend.calls.clear()
        self.backend.inspect_error = AppError("PAGES_LOCAL_REPO_DIRTY")        # 내 저장소가 지저분해도 이미 올라간 글의 공개 확인은 할 수 있다
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)
        self.assertEqual(self.backend.names(), ["expected_url", "check_deployed"])


class ResumeAndRecordTest(Base):
    def committed(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        self.backend.calls.clear()
        return project_id

    def test_resuming_checks_the_gates_and_the_repository_again_but_not_the_duplicates(self):
        project_id = self.committed()
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.stage, plan.status, plan.path), (pages_flow.STAGE_PUSH, st.COMMITTED, ss.KO_PATH))
        self.assertEqual(self.backend.names(), ["inspect", "unpushed_count", "expected_url"])
        self.assertTrue(plan.gates.ok)
        with mock.patch.dict(gate.LENGTH_MIN, {"ko": 10 ** 6}):
            self.assertEqual(ss.code_of(pages_flow.plan_pages_publish, self.ctx, project_id).code, "CHECK_FAILED")

    def test_an_edit_made_while_waiting_stops_the_push_instead_of_silently_publishing_the_old_text(self):
        """commit 한 뒤 push 하기 전에 원고를 고치면 승인은 풀렸는데 승인했던 옛 글이 기록으로 남는다 — 몰래 올리지 않고 멈춘다(H)."""
        project_id = self.committed()
        rendering = self.stored_rendering(project_id)
        projects.edit_project(self.ctx, project_id, markdown=ss.ko_text(1800))
        self.assertEqual(self.status(project_id), st.COMMITTED, "이미 기록한 글은 과거의 사실이라 상태가 그대로다")
        for call in (lambda: self.run_publish(project_id), lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.preview_publish(self.ctx, project_id)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "PUBLISH_CONTENT_CHANGED")
            self.assertIn("판", error.detail)
        self.assertEqual(self.backend.count("push"), 0, "고친 뒤에는 push 를 한 번도 부르지 않았다")
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.assertIsNotNone(self.journal.read(project_id), "기록은 그대로다 — --cancel --yes 로 되돌릴 수 있다")
        self.assertEqual(self.stored_rendering(project_id), rendering)
        shown = error.rendered()
        self.assertIn("--cancel --yes", shown.action)
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)        # 안내대로 되돌릴 수 있다
        self.assertEqual(report.status, st.PUBLISH_FAILED)

    def test_an_edit_made_between_the_commit_and_the_push_of_the_same_run_also_stops_before_the_push(self):
        project_id = self.approved()
        real = pages_flow._record_committed

        def record_then_edit(*args, **kwargs):
            record = real(*args, **kwargs)
            projects.edit_project(self.ctx, project_id, markdown=ss.ko_text(1800))        # 기록한 직후 다른 창에서 원고를 고쳤다
            return record

        with mock.patch.object(pages_flow, "_record_committed", record_then_edit):
            error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "PUBLISH_CONTENT_CHANGED")
        self.assertEqual(self.backend.count("push"), 0, "고친 원고가 아니라 승인했던 옛 글이 몰래 올라가는 일은 없다")
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.assertIsNotNone(self.journal.read(project_id))
        self.assertEqual(pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True).status, st.PUBLISH_FAILED, "안내대로 되돌릴 수 있다")

    def test_a_committed_post_without_its_record_cannot_be_resumed(self):
        project_id = self.committed()
        (self.ctx.workspace.journal_dir / f"{project_id}.json").unlink()
        error = ss.code_of(pages_flow.plan_pages_publish, self.ctx, project_id)
        self.assertEqual((error.code, error.slots["파일"]), ("SETTINGS_INVALID", f"{project_id}.json"))
        self.assertEqual(self.backend.names(), [])

    def test_a_damaged_record_stops_the_resume_and_is_left_untouched(self):
        project_id = self.committed()
        path = self.ctx.workspace.journal_dir / f"{project_id}.json"
        for text in ("{깨짐", "[]", json.dumps({"schema": 1}), json.dumps({"schema": 1, "project_id": project_id, "path": "../etc/passwd", "commit": "c" * 40, "base": "b" * 40, "stage": "committed"}),
                     json.dumps({"schema": 1, "project_id": "다른글", "path": ss.KO_PATH, "commit": "c" * 40, "base": "b" * 40, "stage": "committed"}),
                     json.dumps({"schema": 1, "project_id": project_id, "path": ss.KO_PATH, "commit": "not-a-hash", "base": "b" * 40, "stage": "committed"}),
                     json.dumps({"schema": 1, "project_id": project_id, "path": ss.KO_PATH, "commit": "c" * 40, "base": "b" * 40, "stage": "done"})):
            with self.subTest(text=text[:30]):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(ss.code_of(pages_flow.plan_pages_publish, self.ctx, project_id).code, "SETTINGS_INVALID")
                self.assertEqual(path.read_text(encoding="utf-8"), text)
                self.assertEqual(self.backend.count("push"), 0)

    def test_the_publish_record_holds_only_a_repository_relative_path_and_hashes(self):
        project_id = self.committed()
        raw = (self.ctx.workspace.journal_dir / f"{project_id}.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertEqual(sorted(data), ["base", "commit", "path", "project_id", "schema", "stage"])
        self.assertNotIn(str(self.tmp), raw, "이 PC 의 절대경로를 적지 않는다")
        self.assertFalse(Path(data["path"]).is_absolute())

    def test_the_journal_only_accepts_known_stages_and_project_ids(self):
        with self.assertRaises(AppError):
            self.journal.read("../x")
        from chanceblog_desktop.service.journal import PublishRecord
        self.assertEqual(ss.code_of(self.journal.write, PublishRecord("p1", ss.KO_PATH, "c" * 40, "b" * 40, "weird")).code, "CONTENT_INVALID")
        self.assertEqual(ss.code_of(self.journal.write, "not a record").code, "CONTENT_INVALID")
        self.assertEqual(self.journal.remove("p1"), "", "없는 기록을 지우는 것은 오류가 아니다")

    def test_a_record_that_cannot_be_removed_is_reported_not_hidden(self):
        project_id = self.committed()
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("잠김")):
            note = self.journal.remove(project_id)
        self.assertIn("지우지 못했다", note)


class DefensiveChecksTest(Base):
    def test_an_unreadable_other_post_does_not_block_this_one(self):
        import sqlite3
        from contextlib import closing
        other = projects.new_project(self.ctx, "깨질 글", ss.ko_text()).project_id
        project_id = self.approved()
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as db:
            db.execute("UPDATE projects SET data = ? WHERE project_id = ?", ("{깨짐", other))
            db.commit()
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, project_id).stage, pages_flow.STAGE_COMMIT)

    def test_an_approval_for_another_revision_is_refused_even_if_the_store_somehow_held_it(self):
        """모델은 그런 상태를 저장하지 못하게 막지만, 올리기 직전에도 한 번 더 본다(방어)."""
        from chanceblog_desktop.content.store import Store
        project_id = self.approved()
        real_load = Store.load

        def tampered(store, text_id):
            project = real_load(store, text_id)
            project.variants["github_pages"].rendered_revision = 0
            return project

        for broken in (0, None):
            with self.subTest(rendered_revision=broken):
                with mock.patch.object(Store, "load", lambda store, text_id: self._with_revision(real_load(store, text_id), broken)):
                    error = ss.code_of(self.run_publish, project_id)
                self.assertEqual(error.code, "STATUS_TRANSITION_INVALID")
                self.assertIn("다르다", error.detail)
        self.assertEqual(self.backend.count("commit"), 0)

    @staticmethod
    def _with_revision(project, value):
        project.variants["github_pages"].rendered_revision = value
        return project

    def test_an_empty_rendering_is_refused_the_same_way(self):
        from chanceblog_desktop.content.store import Store
        project_id = self.approved()
        real_load = Store.load

        def blank(store, text_id):
            project = real_load(store, text_id)
            project.variants["github_pages"].rendered = ""
            return project

        with mock.patch.object(Store, "load", blank):
            self.assertEqual(ss.code_of(self.run_publish, project_id).code, "STATUS_TRANSITION_INVALID")
        self.assertEqual(self.backend.count("commit"), 0)

    def test_if_the_state_cannot_be_saved_after_undoing_a_duplicate_the_error_says_so(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("DUPLICATE_SLUG")]
        real = self.ctx.store
        self.backend.hooks["discard"] = lambda: setattr(self.ctx, "store", self._locked)
        self._locked = lambda: (_ for _ in ()).throw(AppError("STORE_LOCKED"))
        error = ss.code_of(self.run_publish, project_id)
        self.ctx.store = real
        self.backend.hooks.clear()
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertIn("상태를 갱신하지 못했다(STORE_LOCKED)", error.detail)
        self.assertIn("--cancel --yes", error.detail)
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.backend.head_has_post = False
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISH_FAILED, "--cancel --yes 로 정리할 수 있다")


class CancelTest(Base):
    def committed(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_AUTH")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        self.backend.calls.clear()
        return project_id

    def test_cancelling_undoes_the_commit_marks_the_post_failed_with_its_own_code_and_removes_the_record(self):
        project_id = self.committed()
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, self.status(project_id)), (st.PUBLISH_FAILED, st.PUBLISH_FAILED))
        self.assertEqual(self.variant(project_id).error_code, "PUBLISH_CANCELLED")
        self.assertEqual([call for call in self.backend.calls if call[0] == "discard"], [("discard", ss.KO_PATH, "c" * 40)])
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.backend.count("push"), 0)
        json.dumps(report.to_dict())

    def test_a_cancelled_post_can_be_made_reviewed_approved_and_published_again(self):
        project_id = self.committed()
        pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        review.request_review(self.ctx, project_id, "github_pages", pages=ss.KO_PARAMS)
        review.grant_approval(self.ctx, project_id, "github_pages")
        self.ctx.clock.advance(seconds=9)
        self.assertEqual(self.run_publish(project_id).status, st.PUBLISHED)

    def test_cancelling_is_refused_when_the_commit_cannot_be_undone_and_nothing_changes(self):
        project_id = self.committed()
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED", detail="지금 HEAD 가 되돌릴 글 커밋이 아니다")
        self.backend.head_has_post = True
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.assertIsNotNone(self.journal.read(project_id))

    def test_other_refusals_of_the_undo_are_passed_on_as_they_are(self):
        project_id = self.committed()
        self.backend.discard_error = AppError("UNEXPECTED_ERROR", detail="이미 원격 main 에 올라간 커밋이라 되돌리지 않는다")
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "UNEXPECTED_ERROR")
        self.assertEqual(self.status(project_id), st.COMMITTED)

    def test_a_commit_that_is_already_gone_does_not_block_the_cancel(self):
        """되돌린 뒤 상태를 못 남겼던 경우: 기록도 파일도 없으면 할 일이 끝난 것으로 보고 상태만 정리한다."""
        project_id = self.committed()
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED")
        self.backend.head_has_post = False
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISH_FAILED)

    def test_a_file_that_is_still_there_is_not_taken_for_an_undone_commit(self):
        project_id = self.committed()
        leftover = self.tmp / "chanceblog" / ss.KO_PATH
        leftover.parent.mkdir(parents=True)
        leftover.write_text("남은 파일", encoding="utf-8")
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.status(project_id), st.COMMITTED)

    def test_only_a_post_with_an_unpushed_commit_can_be_cancelled(self):
        approved = self.approved(title="승인만 한 글")
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, approved, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.ctx.clock.advance(seconds=3)
        pushed = self.approved(title="올라간 글")
        self.run_publish(pushed, wait=False)
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, pushed, confirmed=True)
        self.assertEqual(error.code, "PUBLISH_ALREADY_PUSHED", "이미 올라간 글은 전용 오류로 거절한다")
        self.assertIn(f"check-deploy {pushed[:8]}", error.detail)
        self.assertEqual(self.backend.count("discard"), 0, "이미 올라간 글은 되돌리지 않는다")

    def test_cancelling_without_a_record_is_a_settings_error_and_changes_nothing(self):
        project_id = self.committed()
        (self.ctx.workspace.journal_dir / f"{project_id}.json").unlink()
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "SETTINGS_INVALID")
        self.assertEqual(self.status(project_id), st.COMMITTED)


class PlanDataTest(Base):
    def test_a_plan_for_each_stage_describes_its_own_actions(self):
        project_id = self.approved()
        commit_plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertTrue(any("글 파일 1개를 만듭니다" in action for action in commit_plan.actions))
        self.assertTrue(any("강제로 올리지 않고" in action for action in commit_plan.actions))
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        push_plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertTrue(any("이미 기록해 둔 글" in action for action in push_plan.actions))
        self.run_publish(project_id, wait=False)
        verify_plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((verify_plan.stage, verify_plan.gates), (pages_flow.STAGE_VERIFY, None))
        self.assertTrue(any("공개 주소가 열리는지만" in action for action in verify_plan.actions))
        self.assertTrue(json.dumps(verify_plan.to_dict()))

    def test_the_wait_time_in_the_description_follows_the_deadline(self):
        project_id = self.approved()
        self.assertTrue(any("최대 12분" in action for action in pages_flow.plan_pages_publish(self.ctx, project_id).actions))
        self.assertTrue(any("최대 3분" in action for action in pages_flow.plan_pages_publish(self.ctx, project_id, deadline=180).actions))
        self.assertTrue(any("최대 1분" in action for action in pages_flow.plan_pages_publish(self.ctx, project_id, deadline=0).actions))


def setUpModule():
    ss.external_write_on()                                   # 이 시험은 게시 흐름을 쓴다 — 외부 Write 관문을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    ss.external_write_off()


if __name__ == "__main__":
    unittest.main()
