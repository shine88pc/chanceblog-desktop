"""서비스 층 — GitHub Pages 올리기 흐름 시험(가짜 backend: git·네트워크 없음). 연결한 chanceblog 의 **새 가지**에 올라가는 흐름이라 안전 규칙을 하나씩 어겨 보는 변이 점검으로도 확인한다(PUBPR, T3).
옛 시험(main 에 곧바로 commit·push 하던 흐름)을 새 흐름으로 옮겼다 — 옮긴 목록은 보고서의 '시험 이동표' 와 `docs/DECISIONS.md` D-747 에 있다.

지키는 것:
  1) **확인 없이는 올리지 않는다**: `confirmed is True` 가 아니면 글 커밋 만들기도 가지 올리기도 점검도 하지 않는다. 미리 보기(dry run)는 읽기만 한다(저장소·데이터 파일·상태 그대로).
  2) **승인된 글만, 승인한 그대로**: 승인 전·승인이 풀린·실패한 글은 STATUS_TRANSITION_INVALID. 올라가는 내용은 승인한 렌더링 그대로다.
  3) **검사를 통과해야 한다(fail closed)**: 게이트·연결한 저장소 확인·같은 주소(slug) 확인·병합 기다리는 글 수(최대 3)·공개 주소 계산 중 하나라도 걸리면 글 커밋을 만들지 않는다.
  4) **상태는 사실을 따라간다**: APPROVED → MERGE_PENDING(`built` 를 가지 올리기 전에 적고 올린 뒤 `branch_pushed`) → PUSHED(병합 확인) → PUBLISHED(공개 확인). 공개 주소가 아직 안 열리면 PUSHED 로 두고 check-deploy 로 마친다.
  5) **실패해도 일관되고 같은 일을 두 번 해도 같다**: 가지 올리기가 막히면 APPROVED 에 `built` 기록이 남아 같은 명령이 만든 커밋을 이어받아 올리고(다시 만들지 않는다), 앱의 안전 규칙이 막으면(`PAGES_PUSH_REFUSED`) 실패로 남기며,
     병합을 확인하기 전에는 공개 확인을 하지 않는다. 병합 확인은 사용자가 누를 때만 한다. 옛 방식의 COMMITTED 글은 읽기만 하고 되돌리기는 확인이 있어야 하며 `discard_commit` 이 허락할 때만 된다.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import pages as publish_pages  # noqa: E402
from chanceblog_desktop.publish.gitrepo import BRANCH_NAME  # noqa: E402
from chanceblog_desktop.publish.pages import MainCheck  # noqa: E402
from chanceblog_desktop.render.pages import PagesPost  # noqa: E402
from chanceblog_desktop.service import gate, pages_flow, projects, review  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_BRANCH_PUSHED, STAGE_BUILT, STAGE_COMMITTED, STAGE_PUSHED, Journal, PublishRecord  # noqa: E402

EN_PATH = "_posts/Society & Policy/2026-11-02-EN-103012.md"
MERGED = MainCheck("merged", commit="d" * 40)


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

    def remote_id(self, project_id):
        with self.ctx.store() as store:
            return store.load(project_id).variant("github_pages").remote_id

    def fail_the_store_after(self, call_name):
        """backend 가 `call_name` 을 부른 뒤로는 상태 저장소를 열 수 없다고 한다(잠김). 되돌리는 함수를 돌려준다."""
        real = self.ctx.store

        def failing():
            if self.backend.count(call_name):
                raise AppError("STORE_LOCKED")
            return real()

        self.ctx.store = failing
        return lambda: setattr(self.ctx, "store", real)

    def pending(self, project_id=None, **kwargs):
        """승인한 글을 새 가지에 올려 병합을 기다리는 상태(MERGE_PENDING)로 만든다 → 글 번호."""
        project_id = project_id or self.approved(**kwargs)
        self.run_publish(project_id)
        self.assertEqual(self.status(project_id), st.MERGE_PENDING)
        self.backend.calls.clear()
        return project_id

    def merged(self, project_id=None, **kwargs):
        """병합을 확인한 상태(PUSHED)까지 간다 → 글 번호."""
        project_id = self.pending(project_id, **kwargs)
        self.backend.merge_results = [MERGED]
        pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual(self.status(project_id), st.PUSHED)
        self.backend.calls.clear()
        return project_id

    def legacy_committed(self, **kwargs):
        """옛 버전(main 에 곧바로 올리던 시절)이 남긴 '이 PC 에 기록함' 상태를 직접 만든다 — 새 흐름은 이 상태를 만들지 않는다."""
        project_id = self.approved(**kwargs)
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.transition("github_pages", st.COMMITTED, now=self.ctx.stamp())
            store.save(project)
        self.journal.write(PublishRecord(project_id, ss.KO_PATH, "c" * 40, "b" * 40, STAGE_COMMITTED))
        self.backend.calls.clear()
        return project_id


class PlanTest(Base):
    def test_the_plan_of_an_approved_post_names_the_file_the_branch_and_the_address_and_changes_nothing(self):
        project_id = self.approved()
        before = ss.tree_snapshot(self.ctx.workspace.root)
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.stage, plan.status, plan.path, plan.expected_url, plan.lang, plan.category), (pages_flow.STAGE_BRANCH, st.APPROVED, ss.KO_PATH, ss.KO_URL, "ko", "경제·일"))
        self.assertEqual(plan.text, self.stored_rendering(project_id))
        self.assertTrue(plan.gates.ok)
        self.assertEqual(plan.size_bytes, len(plan.text.encode("utf-8")))
        self.assertTrue(any(ss.KO_PATH in action for action in plan.actions))
        self.assertTrue(BRANCH_NAME.fullmatch(plan.branch), plan.branch)
        self.assertEqual(plan.branch, publish_pages.branch_name(plan.post))
        self.assertIn(f"compare/main...{plan.branch}?quick_pull=1&title=", plan.link)
        self.assertTrue(any(plan.branch in action and "main 에는 올리지 않습니다" in action for action in plan.actions))
        self.assertEqual(self.backend.names(), ["inspect", "duplicates", "same_content", "expected_url"], "읽기만 한다 — 글 커밋 만들기·가지 올리기·병합 확인은 부르지 않는다")
        self.assertEqual(ss.tree_snapshot(self.ctx.workspace.root), before, "데이터 폴더에 아무것도 쓰지 않았다(발행 기록도 없다)")
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.status(project_id), st.APPROVED)

    def test_the_preview_report_says_nothing_was_done_and_how_to_go_on(self):
        project_id = self.approved()
        report = pages_flow.preview_publish(self.ctx, project_id)
        self.assertEqual((report.dry_run, report.steps, report.status, report.verified, report.pending_verification), (True, (), st.APPROVED, False, False))
        self.assertTrue(any("--yes" in step for step in report.next_steps))
        self.assertTrue(any("아무것도 하지 않았" in note for note in report.notes))
        self.assertEqual(self.backend.count("build_branch_commit") + self.backend.count("push_branch"), 0)

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
        self.backend.push_errors = [AppError("PAGES_PUSH_REFUSED")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        self.assertEqual(self.status(project_id), st.PUBLISH_FAILED)
        self.backend.calls.clear()
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "STATUS_TRANSITION_INVALID")
        self.assertIn("승인(APPROVED)한 글만", error.detail)
        self.assertEqual(self.backend.calls, [], "실패한 글은 저장소를 들여다보지도, 글 커밋을 만들지도 않는다")

    def test_the_gates_run_again_when_publishing_so_a_tightened_rule_stops_an_old_approval(self):
        project_id = self.approved()
        with mock.patch.dict(gate.LENGTH_MIN, {"ko": 10 ** 6}):
            for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: self.run_publish(project_id)):
                error = ss.code_of(call)
                self.assertEqual(error.code, "CHECK_FAILED")
                self.assertIn("LEN_SHORT", error.slots["걸린 항목 목록"])
        self.assertEqual(self.backend.count("build_branch_commit"), 0)
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
        self.assertEqual(self.backend.count("build_branch_commit"), 0)

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
        self.assertEqual((self.backend.count("build_branch_commit"), self.backend.count("push_branch")), (0, 0))
        self.assertEqual(self.status(project_id), st.APPROVED)

    def test_a_post_with_the_same_address_already_in_the_repository_is_a_duplicate(self):
        project_id = self.approved()
        self.backend.names_found = ["_posts/다른 분야/2026-11-02-KR-103012.md"]
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: self.run_publish(project_id)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "DUPLICATE_SLUG")
            self.assertIn("다른 분야", error.detail)
        self.assertEqual(self.backend.count("build_branch_commit"), 0)

    def test_a_post_with_the_same_content_already_in_the_repository_is_a_duplicate(self):
        project_id = self.approved()
        self.backend.same_content_found = ["_posts/예전/2026-10-01-KR-090000.md"]
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual((error.code, error.slots["파일"]), ("DUPLICATE_CONTENT", "_posts/예전/2026-10-01-KR-090000.md"))
        self.assertEqual(self.backend.count("build_branch_commit"), 0)

    def test_another_post_already_online_at_the_same_address_gets_the_next_second_instead(self):
        first = self.merged(title="첫 글")
        pages_flow.check_pages_deploy(self.ctx, first)
        self.assertEqual(self.status(first), st.PUBLISHED)
        second = self.approved(title="둘째 글")                       # 같은 시계 — 같은 파일 이름·같은 공개 주소가 될 뻔했다 → 앱이 다음 초의 이름을 쓴다
        report = self.run_publish(second)
        self.assertEqual(report.plan.path, "_posts/경제·일/2026-11-02-KR-103013.md")
        self.assertNotEqual(report.plan.expected_url, self.variant(first).published_url, "다른 공개 주소다")
        self.assertEqual(self.backend.count("build_branch_commit"), 1, "둘째 글은 한 번 글 커밋을 만들었다")
        self.assertEqual(self.status(second), st.MERGE_PENDING)

    def test_another_post_in_the_middle_of_publishing_blocks_the_same_file_name(self):
        first = self.approved(title="첫 글")
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.run_publish(first)
        self.assertEqual(self.status(first), st.APPROVED)
        second = self.approved(title="둘째 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).path, "_posts/경제·일/2026-11-02-KR-103013.md", "가지를 올리다 멈춘 글(`built` 기록)이 쥔 이름을 피해 다음 초로")

    def test_a_post_waiting_for_a_merge_also_holds_its_file_name(self):
        first = self.approved(title="첫 글")
        self.run_publish(first)
        self.assertEqual(self.status(first), st.MERGE_PENDING)
        second = self.approved(title="둘째 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).path, "_posts/경제·일/2026-11-02-KR-103013.md", "병합을 기다리는 글의 이름도 피한다")

    def test_a_post_that_was_merged_but_not_yet_verified_also_holds_its_file_name(self):
        first = self.merged(title="첫 글")
        second = self.approved(title="둘째 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).path, "_posts/경제·일/2026-11-02-KR-103013.md", "병합을 확인한 글의 이름도 피한다")
        self.assertEqual(self.status(first), st.PUSHED)

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
        self.assertEqual(self.backend.count("build_branch_commit"), 0)

    def test_the_file_name_is_made_from_the_clock_in_korean_time_and_the_category_and_language(self):
        project_id = self.approved(title="English post", text=ss.en_text(), params=ss.EN_PARAMS)
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.path, plan.lang), (EN_PATH, "en"))
        self.ctx.clock.advance(hours=15)                              # UTC 16:30 → 한국 시각 다음 날 01:30
        later = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual(later.path, "_posts/Society & Policy/2026-11-03-EN-013012.md")
        self.assertTrue(later.branch.startswith("desktop/post-20261103-013012-"), "가지 이름의 시각은 글 파일 이름과 같은 한국 시각이다")

    def test_the_text_that_goes_in_is_exactly_the_approved_rendering(self):
        project_id = self.approved()
        approved_text = self.stored_rendering(project_id)
        self.run_publish(project_id)
        build_call = next(call for call in self.backend.calls if call[0] == "build_branch_commit")
        self.assertEqual(build_call[3], approved_text)
        self.assertEqual(build_call[2], "에너지 절약 습관", "commit 제목은 글 제목이다")

    def test_the_branch_name_has_no_user_text_even_when_the_title_is_hostile(self):
        project_id = self.approved(title="../main ^ ~ : * ? [x] 제목 \\ desktop")
        report = self.run_publish(project_id)
        self.assertTrue(BRANCH_NAME.fullmatch(report.branch), report.branch)
        self.assertNotIn("main", report.branch.split("/", 1)[1])


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

    def test_cancelling_and_abandoning_also_need_the_confirmation(self):
        legacy = self.legacy_committed()
        waiting = self.pending(title="병합 기다리는 글")
        calls = len(self.backend.calls)
        for confirmed in (False, None, 1, "yes"):
            with self.subTest(confirmed=confirmed):
                self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, legacy, confirmed=confirmed).code, "CONFIRMATION_REQUIRED")
                self.assertEqual(ss.code_of(pages_flow.abandon_pages_publish, self.ctx, waiting, confirmed=confirmed).code, "CONFIRMATION_REQUIRED")
        self.assertEqual(len(self.backend.calls), calls)
        self.assertEqual((self.status(legacy), self.status(waiting)), (st.COMMITTED, st.MERGE_PENDING))


class HappyPathTest(Base):
    def test_a_confirmed_publish_builds_pushes_the_branch_and_saves_each_step_before_the_next(self):
        project_id = self.approved()
        seen = {}
        for name in ("build_branch_commit", "push_branch"):
            self.backend.hooks[name] = lambda name=name: seen.setdefault(name, (self.status(project_id), self.journal.read(project_id)))
        report = self.run_publish(project_id)
        self.assertEqual(seen["build_branch_commit"], (st.APPROVED, None))
        self.assertEqual(seen["push_branch"][0], st.APPROVED, "가지를 올리기 전에는 아직 승인됨이다")
        built = seen["push_branch"][1]
        self.assertEqual((built.stage, built.path, built.commit, built.base), (STAGE_BUILT, ss.KO_PATH, "c" * 40, "b" * 40), "가지를 올리기 **전에** `built` 를 적었다(멱등)")
        self.assertTrue(BRANCH_NAME.fullmatch(built.branch))
        self.assertEqual([name for name in self.backend.names() if name in ("build_branch_commit", "push_branch", "check_deployed", "post_on_main")], ["build_branch_commit", "push_branch"])
        self.assertEqual((report.status, report.verified, report.pending_verification, report.dry_run), (st.MERGE_PENDING, False, True, False))
        self.assertEqual(report.branch, built.branch)
        self.assertEqual(report.link, publish_pages.compare_link(built.branch, "에너지 절약 습관"))
        variant = self.variant(project_id)
        self.assertEqual((variant.status, variant.published_url, variant.published_at, variant.error_code), (st.MERGE_PENDING, None, None, None))
        self.assertEqual(self.remote_id(project_id), f"{built.branch}@{'c' * 40}", "병합 확인을 이어 갈 가지와 커밋이 보관함에 있다")
        record = self.journal.read(project_id)
        self.assertEqual((record.stage, record.branch, record.commit, record.path), (STAGE_BRANCH_PUSHED, built.branch, "c" * 40, ss.KO_PATH))

    def test_the_whole_way_publish_then_merge_check_then_check_deploy(self):
        project_id = self.approved()
        self.run_publish(project_id)
        self.backend.merge_results = [MERGED]
        seen = {}
        self.backend.hooks["check_deployed"] = lambda: seen.setdefault("record", (self.status(project_id), self.journal.read(project_id)))
        merge = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual((merge.status, merge.pending_verification, merge.verified), (st.PUSHED, True, False))
        self.assertTrue(any("check-deploy" in step for step in merge.next_steps))
        record = self.journal.read(project_id)
        self.assertEqual((record.stage, record.commit, record.path), (STAGE_PUSHED, "d" * 40, ss.KO_PATH), "글을 처음 담은 main 커밋을 기록한다")
        report = pages_flow.check_pages_deploy(self.ctx, project_id)
        self.assertEqual(seen["record"][0], st.PUSHED, "공개 확인 전에 '병합 확인' 을 저장했다")
        self.assertEqual((report.status, report.verified, report.pending_verification, report.url), (st.PUBLISHED, True, False, ss.KO_URL))
        variant = self.variant(project_id)
        self.assertEqual((variant.status, variant.published_url, variant.published_at, variant.error_code), (st.PUBLISHED, ss.KO_URL, "2026-11-02T01:30:12Z", None))
        self.assertIsNone(self.journal.read(project_id), "끝난 글의 발행 기록은 지운다")
        self.assertEqual(self.backend.count("push_branch"), 1, "병합 확인과 공개 확인은 다시 올리지 않는다")

    def test_the_report_tells_what_was_done_in_plain_words_and_converts_to_plain_data(self):
        project_id = self.approved()
        report = self.run_publish(project_id)
        self.assertEqual(len(report.steps), 2)
        self.assertTrue(any("기록(commit)" in step and "작업 폴더는 바꾸지 않았습니다" in step for step in report.steps))
        self.assertTrue(any("새 가지" in step and "main 에는 올리지 않았습니다" in step for step in report.steps))
        data = report.to_dict()
        self.assertEqual((data["status"], data["plan"]["path"], "text" in data["plan"], data["branch"], bool(data["link"])), (st.MERGE_PENDING, ss.KO_PATH, False, report.branch, True))
        self.assertIn("text", report.to_dict(with_text=True)["plan"])
        json.dumps(data)

    def test_the_time_in_the_file_name_is_the_moment_of_the_run_not_of_the_approval(self):
        project_id = self.approved()
        self.ctx.clock.advance(hours=2, minutes=5, seconds=7)
        report = self.run_publish(project_id)
        self.assertEqual(report.plan.path, "_posts/경제·일/2026-11-02-KR-123519.md")
        self.assertTrue(report.branch.startswith("desktop/post-20261102-123519-"))

    def test_the_deadline_and_interval_reach_the_deploy_check(self):
        project_id = self.merged()
        pages_flow.check_pages_deploy(self.ctx, project_id, deadline=90, interval=3)
        self.assertIn(("check_deployed", ss.KO_PATH, 90, 3), self.backend.calls)

    def test_a_published_post_is_left_alone_when_asked_again(self):
        project_id = self.merged()
        pages_flow.check_pages_deploy(self.ctx, project_id)
        calls = len(self.backend.calls)
        for call in (lambda: self.run_publish(project_id), lambda: pages_flow.preview_publish(self.ctx, project_id), lambda: pages_flow.check_pages_deploy(self.ctx, project_id)):
            report = call()
            self.assertEqual((report.status, report.url, report.plan.stage), (st.PUBLISHED, ss.KO_URL, pages_flow.STAGE_DONE))
        self.assertEqual(len(self.backend.calls), calls, "이미 공개된 글은 저장소·네트워크를 부르지 않는다")

    def test_publishing_again_while_waiting_for_the_merge_only_says_so_and_does_nothing(self):
        project_id = self.pending()
        report = self.run_publish(project_id)
        self.assertEqual((report.status, report.plan.stage, report.pending_verification), (st.MERGE_PENDING, pages_flow.STAGE_MERGE, True))
        self.assertTrue(any("병합을 기다리는" in step for step in report.steps))
        self.assertTrue(any("merge-check" in step for step in report.next_steps))
        self.assertEqual(self.backend.count("build_branch_commit") + self.backend.count("push_branch") + self.backend.count("post_on_main"), 0, "병합 확인은 사용자가 누를 때만 — 올리기 명령이 대신하지 않는다")

    def test_publishing_a_merged_post_only_checks_the_public_address(self):
        project_id = self.merged()
        report = self.run_publish(project_id)
        self.assertEqual((report.status, report.verified), (st.PUBLISHED, True))
        self.assertEqual((self.backend.count("build_branch_commit"), self.backend.count("push_branch"), self.backend.count("post_on_main")), (0, 0, 0))


class FailureTest(Base):
    def test_a_build_that_fails_leaves_the_post_approved_with_nothing_recorded(self):
        project_id = self.approved()
        for code in ("PAGES_LOCAL_REPO_DIRTY", "GIT_IDENTITY_MISSING", "DUPLICATE_SLUG", "FILE_WRITE_FAILED", "GIT_PUSH_NETWORK"):
            with self.subTest(code=code):
                self.backend.commit_error = AppError(code)
                self.assertEqual(ss.code_of(self.run_publish, project_id).code, code)
                self.assertEqual(self.status(project_id), st.APPROVED)
                self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.backend.count("push_branch"), 0)
        self.assertEqual(self.backend.count("discard"), 0, "저장소를 바꾸지 않았으니 되돌릴 것도 없다")

    def test_a_push_that_fails_for_a_temporary_reason_keeps_the_built_record_and_the_next_run_only_pushes(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK", detail="Could not resolve host")]
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "GIT_PUSH_NETWORK")
        self.assertIn("같은 명령을 다시 실행", error.detail)
        self.assertIn("원격 main 은 건드리지 않았다", error.detail)
        self.assertEqual(self.status(project_id), st.APPROVED)
        record = self.journal.read(project_id)
        self.assertEqual((record.path, record.stage), (ss.KO_PATH, STAGE_BUILT))
        self.assertEqual(self.backend.count("discard"), 0)
        self.ctx.clock.advance(hours=3)                                   # 다음 실행은 새 시각이 아니라 앞서 만든 같은 글 커밋·같은 가지를 올린다
        report = self.run_publish(project_id)
        self.assertEqual((self.backend.count("build_branch_commit"), self.backend.count("push_branch")), (1, 2), "다시 만들지 않고 가지 올리기만 했다")
        self.assertEqual((report.status, report.plan.stage, report.plan.path), (st.MERGE_PENDING, pages_flow.STAGE_BRANCH, ss.KO_PATH))
        self.assertEqual(report.branch, record.branch, "같은 가지다")
        self.assertTrue(any("이어받았습니다" in step for step in report.steps))
        self.assertEqual(self.status(project_id), st.MERGE_PENDING)

    def test_every_temporary_kind_of_push_failure_keeps_the_built_record_for_a_retry(self):
        for code in ("GIT_PUSH_AUTH", "GIT_PUSH_NETWORK", "GIT_PUSH_REJECTED", "NETWORK_TIMEOUT", "PAGES_LOCAL_REPO_DIVERGED", "PAGES_LOCAL_REPO_NOT_MAIN", "UNEXPECTED_ERROR", "SECRET_IN_TEXT_BLOCKED"):
            with self.subTest(code=code):
                project_id = self.approved(title=f"글 {code}")
                self.ctx.clock.advance(seconds=1)
                self.backend.push_errors = [AppError(code)]
                self.assertEqual(ss.code_of(self.run_publish, project_id).code, code)
                self.assertEqual(self.status(project_id), st.APPROVED)
                self.assertEqual(self.journal.read(project_id).stage, STAGE_BUILT)
                self.backend.push_errors = [None]
                self.run_publish(project_id)
                self.assertEqual(self.status(project_id), st.MERGE_PENDING)
                pages_flow.abandon_pages_publish(self.ctx, project_id, confirmed=True)             # 병합 기다리는 글이 셋을 넘지 않게 정리한다
        self.assertEqual(self.backend.count("discard"), 0)

    def test_a_refusal_by_the_apps_own_safety_rule_marks_the_post_failed_and_removes_the_record(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("PAGES_PUSH_REFUSED", detail="같은 이름의 가지가 다른 내용으로 이미 원격에 있어 덮어쓰지 않고 멈췄다")]
        error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "PAGES_PUSH_REFUSED")
        self.assertIn("다시 만들어(review)", error.detail)
        variant = self.variant(project_id)
        self.assertEqual((variant.status, variant.error_code), (st.PUBLISH_FAILED, "PAGES_PUSH_REFUSED"))
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.backend.count("discard"), 0)
        review.request_review(self.ctx, project_id, "github_pages", pages=ss.KO_PARAMS)       # 글을 다시 만들어 검토·승인하면 새로 올릴 수 있다
        review.grant_approval(self.ctx, project_id, "github_pages")
        self.ctx.clock.advance(seconds=5)
        self.assertEqual(self.run_publish(project_id).status, st.MERGE_PENDING)

    def test_a_record_that_cannot_be_saved_after_the_build_stops_before_the_push(self):
        project_id = self.approved()
        with mock.patch.object(pages_flow.Journal, "write", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})):
            error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertEqual(self.backend.count("push_branch"), 0, "기록을 못 남겼으면 올리지 않는다(올린 뒤 잊는 일이 없게)")
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertIsNone(self.journal.read(project_id))

    def test_the_same_when_the_state_cannot_be_saved_after_the_push_and_a_rerun_completes_it_without_pushing_twice(self):
        project_id = self.approved()
        restore = self.fail_the_store_after("push_branch")
        error = ss.code_of(self.run_publish, project_id)
        restore()
        self.assertEqual(error.code, "STORE_LOCKED")
        self.assertIn("이미 새 가지에 올라갔다", error.detail)
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertEqual(self.journal.read(project_id).stage, STAGE_BRANCH_PUSHED)
        self.backend.push_already = True                                  # 다시 올리면 '이미 올라가 있다' 로 끝난다(멱등)
        report = self.run_publish(project_id)
        self.assertEqual(report.status, st.MERGE_PENDING)
        self.assertTrue(any("이미 원격에 같은 끝으로 올라가 있어 다시 올리지 않았습니다" in step for step in report.steps))
        self.assertEqual(self.backend.count("build_branch_commit"), 1)

    def test_an_interruption_between_the_record_and_the_push_leaves_a_record_a_rerun_picks_up(self):
        project_id = self.approved()
        self.backend.hooks["push_branch"] = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_publish(project_id)
        self.backend.hooks.clear()
        self.assertEqual((self.status(project_id), self.journal.read(project_id).stage), (st.APPROVED, STAGE_BUILT))
        self.run_publish(project_id)
        self.assertEqual((self.status(project_id), self.backend.count("build_branch_commit")), (st.MERGE_PENDING, 1))

    def test_a_failure_to_record_the_branch_push_says_the_post_is_online_and_the_next_run_finishes_the_record(self):
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
        self.assertEqual((error.code, writes), ("FILE_WRITE_FAILED", [STAGE_BUILT, STAGE_BRANCH_PUSHED]))
        self.assertIn("이미 새 가지에 올라갔다", error.detail)
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.backend.push_already = True
        report = self.run_publish(project_id)
        self.assertEqual(report.status, st.MERGE_PENDING)
        self.assertEqual(self.backend.count("build_branch_commit"), 1)

    def test_a_missing_local_commit_is_rebuilt_once(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        self.backend.push_errors = [AppError("UNEXPECTED_ERROR", detail="만들어 둔 글 커밋이 이 저장소에 없다 — 다시 만든다"), None]
        report = self.run_publish(project_id)
        self.assertEqual((report.status, self.backend.count("build_branch_commit"), self.backend.count("push_branch")), (st.MERGE_PENDING, 2, 3))

    def test_at_most_three_posts_wait_for_a_merge_and_the_fourth_is_stopped_before_anything_is_built(self):
        waiting = []
        for number in range(3):
            self.ctx.clock.advance(seconds=1)
            waiting.append(self.pending(title=f"기다리는 글 {number}"))
        self.ctx.clock.advance(seconds=1)
        fourth = self.approved(title="넷째 글")
        for call in (lambda: self.run_publish(fourth), lambda: pages_flow.plan_pages_publish(self.ctx, fourth), lambda: pages_flow.preview_publish(self.ctx, fourth)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "PAGES_MERGE_LIMIT")
        self.assertEqual((self.backend.count("build_branch_commit"), self.backend.count("push_branch")), (0, 0), "아무것도 올라가지 않았다")
        self.assertEqual(self.status(fourth), st.APPROVED)
        pages_flow.abandon_pages_publish(self.ctx, waiting[0], confirmed=True)
        self.assertEqual(self.run_publish(fourth).status, st.MERGE_PENDING, "하나를 정리하면 다시 올릴 수 있다")


class MergeCheckTest(Base):
    def test_a_merged_post_becomes_pushed_and_keeps_the_branch_identifier(self):
        project_id = self.pending()
        before = self.remote_id(project_id)
        self.backend.merge_results = [MERGED]
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual((report.status, self.status(project_id)), (st.PUSHED, st.PUSHED))
        self.assertTrue(any("한 글자도 다르지 않습니다" in step for step in report.steps))
        self.assertEqual(self.remote_id(project_id), before, "식별자(가지@커밋)는 그대로 — 발행 기록이 없어져도 경로를 다시 만들 수 있다")
        self.assertEqual(self.backend.count("post_on_main"), 1)
        self.assertEqual(self.backend.count("check_deployed"), 0, "병합 확인이 공개 확인을 대신하지 않는다")

    def test_not_yet_merged_changes_nothing_and_says_where_to_look(self):
        project_id = self.pending()
        self.backend.merge_results = [MainCheck("not_yet")]
        self.backend.branch_tip = "c" * 40
        record = self.journal.read(project_id)
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual((report.status, self.status(project_id), report.pending_verification), (st.MERGE_PENDING, st.MERGE_PENDING, True))
        self.assertTrue(any("아직 병합되지 않았어요" in note for note in report.notes))
        self.assertTrue(report.link.startswith("https://github.com/"), "비교 링크를 다시 보인다(글자로만)")
        self.assertEqual(self.journal.read(project_id), record, "기록도 그대로다")
        self.assertFalse(any("가지가 원격에 없어요" in note for note in report.notes))

    def test_when_the_branch_is_gone_it_says_so_and_points_to_abandon_but_does_not_change_the_state_by_itself(self):
        project_id = self.pending()
        self.backend.merge_results = [MainCheck("not_yet")]
        self.backend.branch_tip = None
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertTrue(any("가지가 원격에 없어요" in note and "abandon" in note for note in report.notes))
        self.assertEqual(self.status(project_id), st.MERGE_PENDING, "자동으로 바꾸지 않는다")

    def test_the_same_content_under_another_name_is_reported_but_not_adopted(self):
        project_id = self.pending()
        self.backend.merge_results = [MainCheck("not_yet", moved_to="_posts/경제·일/2026-11-02-KR-999999.md")]
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual(self.status(project_id), st.MERGE_PENDING)
        self.assertTrue(any("2026-11-02-KR-999999.md" in note and "이어받지 않아요" in note for note in report.notes))

    def test_different_content_at_the_same_path_stops_with_its_own_code_and_never_checks_the_address(self):
        project_id = self.pending()
        self.backend.merge_results = [MainCheck("different")]
        error = ss.code_of(pages_flow.merge_check_pages, self.ctx, project_id)
        self.assertEqual((error.code, error.slots["파일"]), ("PAGES_MERGE_DIFFERENT", ss.KO_PATH))
        self.assertEqual(self.status(project_id), st.MERGE_PENDING)
        self.assertEqual(self.backend.count("check_deployed"), 0)
        self.assertEqual(ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id).code, "STATUS_TRANSITION_INVALID", "병합을 확인하지 못한 글은 공개 확인도 못 한다")

    def test_only_a_post_waiting_for_a_merge_can_be_checked(self):
        approved = self.approved(title="승인만 한 글")
        error = ss.code_of(pages_flow.merge_check_pages, self.ctx, approved)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.assertEqual(self.backend.count("post_on_main"), 0)
        merged = self.merged(title="이미 병합한 글")
        again = pages_flow.merge_check_pages(self.ctx, merged)
        self.assertTrue(any("이미 병합을 확인한" in step for step in again.steps))
        self.assertEqual(self.backend.count("post_on_main"), 0)

    def test_the_merge_check_is_only_done_when_asked_never_by_planning_previewing_or_publishing(self):
        project_id = self.pending()
        pages_flow.plan_pages_publish(self.ctx, project_id)
        pages_flow.preview_publish(self.ctx, project_id)
        self.run_publish(project_id)
        self.assertEqual(self.backend.count("post_on_main"), 0, "시작할 때·주기·화면을 열 때·올리기 명령으로는 병합을 확인하지 않는다")

    def test_after_a_restore_without_the_journal_the_identifier_alone_rebuilds_the_path(self):
        project_id = self.pending()
        (self.ctx.workspace.journal_dir / f"{project_id}.json").unlink()                 # 발행 기록은 백업에 들어 있지 않다 — 복원 뒤에는 없다
        self.backend.merge_results = [MERGED]
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual(report.status, st.PUSHED)
        self.assertEqual(report.plan.path, ss.KO_PATH, "가지 이름의 시각과 머리말의 분야·언어로 글 파일 경로를 다시 만들었다")
        self.assertIn(("post_on_main", ss.KO_PATH), self.backend.calls)
        record = self.journal.read(project_id)
        self.assertEqual((record.stage, record.path, record.commit), (STAGE_PUSHED, ss.KO_PATH, "d" * 40))
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)

    def test_a_pushed_post_without_its_record_can_also_finish_when_it_came_from_a_branch(self):
        project_id = self.merged()
        (self.ctx.workspace.journal_dir / f"{project_id}.json").unlink()
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED, "새 방식으로 올린 글은 기록이 없어도 식별자로 이어 간다")

    def test_the_text_that_is_compared_is_the_approved_rendering_even_after_an_edit(self):
        project_id = self.pending()
        rendering = self.stored_rendering(project_id)
        projects.edit_project(self.ctx, project_id, markdown=ss.ko_text(1800))
        self.assertEqual(self.status(project_id), st.MERGE_PENDING, "이미 올라간 것은 과거의 사실이라 상태가 그대로다")
        self.backend.merge_results = [MERGED]
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual(report.status, st.PUSHED)
        compared = next(call for call in self.backend.calls if call[0] == "post_on_main")
        self.assertEqual(compared, ("post_on_main", ss.KO_PATH))
        self.assertEqual(self.stored_rendering(project_id), rendering)
        self.assertTrue(any("원고를 고쳤어요" in note and "승인했던 옛 내용" in note for note in report.notes), "병합되는 글은 승인했던 옛 내용이라는 것을 알린다")

    def test_a_listed_call_error_is_passed_on_and_the_state_is_kept(self):
        project_id = self.pending()
        for code in ("GIT_PUSH_NETWORK", "GIT_PUSH_AUTH", "NETWORK_TIMEOUT"):
            with self.subTest(code=code):
                self.backend.merge_results = [AppError(code)]
                self.assertEqual(ss.code_of(pages_flow.merge_check_pages, self.ctx, project_id).code, code)
                self.assertEqual(self.status(project_id), st.MERGE_PENDING)


class AbandonTest(Base):
    def test_abandoning_marks_failed_with_its_own_code_deletes_nothing_and_removes_the_record(self):
        project_id = self.pending()
        calls = list(self.backend.calls)
        report = pages_flow.abandon_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, self.status(project_id)), (st.PUBLISH_FAILED, st.PUBLISH_FAILED))
        self.assertEqual(self.variant(project_id).error_code, "PAGES_MERGE_ABANDONED")
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.backend.calls, calls, "원격 가지도 글도 건드리지 않았다 — backend 를 한 번도 부르지 않았다")
        self.assertTrue(any("GitHub 에 그대로 남아 있습니다" in step for step in report.steps))
        json.dumps(report.to_dict())

    def test_an_abandoned_post_can_be_reviewed_approved_and_published_again(self):
        project_id = self.pending()
        pages_flow.abandon_pages_publish(self.ctx, project_id, confirmed=True)
        review.request_review(self.ctx, project_id, "github_pages", pages=ss.KO_PARAMS)
        review.grant_approval(self.ctx, project_id, "github_pages")
        self.ctx.clock.advance(seconds=9)
        self.assertEqual(self.run_publish(project_id).status, st.MERGE_PENDING)

    def test_only_a_post_waiting_for_a_merge_can_be_abandoned(self):
        approved = self.approved(title="승인만 한 글")
        error = ss.code_of(pages_flow.abandon_pages_publish, self.ctx, approved, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        merged = self.merged(title="병합한 글")
        self.assertEqual(ss.code_of(pages_flow.abandon_pages_publish, self.ctx, merged, confirmed=True).slots["현재 상태"], st.PUSHED)

    def test_cancel_does_not_take_a_waiting_post_and_points_to_abandon(self):
        project_id = self.pending()
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.MERGE_PENDING))
        self.assertIn(f"abandon {project_id[:8]}", error.detail)
        self.assertEqual(self.status(project_id), st.MERGE_PENDING)

    def test_a_waiting_post_cannot_be_deleted_until_it_is_merged_or_abandoned(self):
        project_id = self.pending()
        error = ss.code_of(projects.delete_project, self.ctx, project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.MERGE_PENDING))
        self.assertIn("merge-check", error.detail)
        pages_flow.abandon_pages_publish(self.ctx, project_id, confirmed=True)
        projects.delete_project(self.ctx, project_id, confirmed=True)


class VerificationTest(Base):
    def test_a_post_that_is_not_open_yet_is_merged_and_unverified_not_failed_and_check_deploy_finishes_it(self):
        project_id = self.merged()
        self.backend.deploy_errors = [AppError("PAGES_DEPLOY_NOT_VISIBLE", detail="404")]
        report = pages_flow.check_pages_deploy(self.ctx, project_id)
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
        self.assertEqual(self.backend.count("push_branch"), 0, "확인을 다시 할 뿐 다시 올리지 않는다")

    def test_a_post_that_stays_closed_keeps_a_consistent_state_for_as_long_as_it_takes(self):
        project_id = self.merged()
        self.backend.deploy_errors = [AppError("PAGES_DEPLOY_NOT_VISIBLE")] * 2
        for _ in range(2):
            report = pages_flow.check_pages_deploy(self.ctx, project_id)
            self.assertEqual((report.status, report.pending_verification), (st.PUSHED, True))
            self.assertEqual(self.status(project_id), st.PUSHED)
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)

    def test_no_wait_does_not_wait_for_the_address(self):
        project_id = self.merged()
        report = self.run_publish(project_id, wait=False)
        self.assertEqual((report.status, report.pending_verification, self.backend.count("check_deployed")), (st.PUSHED, True, 0))
        self.assertTrue(any("check-deploy" in step for step in report.next_steps))
        self.assertEqual(self.status(project_id), st.PUSHED)

    def test_a_published_post_with_a_leftover_record_is_tidied_by_the_next_check_and_the_next_publish_and_nothing_else_is_touched(self):
        """옛 `test_a_crash_before_the_record_is_removed_leaves_a_harmless_record_that_the_next_check_cleans`(진짜 프로세스 충돌 시험)의 서비스 층 짝 — 공개된 뒤 기록을 지우기 직전에 멈춘 흔적을 다음 확인·다음 올리기 명령이 그 글의 것만 치운다."""
        project_id = self.merged()
        record = self.journal.read(project_id)
        pages_flow.check_pages_deploy(self.ctx, project_id)
        self.assertEqual(self.status(project_id), st.PUBLISHED)
        self.assertIsNone(self.journal.read(project_id))
        other = PublishRecord("x" * 32, record.path, record.commit, record.base, STAGE_PUSHED, record.branch)
        self.journal.write(record)                                                       # 공개 직후 기록을 지우기 전에 멈춘 흔적을 흉내 낸다
        report = pages_flow.check_pages_deploy(self.ctx, project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertTrue(any("정리했습니다" in note for note in report.notes), report.notes)
        self.assertIsNone(self.journal.read(project_id), "그 글의 기록만 지웠다")
        self.journal.write(record)
        self.journal.write(other)                                                        # 다른 글의 기록은 건드리지 않는다
        again = self.run_publish(project_id)
        self.assertTrue(any("정리했습니다" in note for note in again.notes), again.notes)
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.journal.read("x" * 32), other)
        self.assertEqual((self.backend.count("build_branch_commit"), self.backend.count("push_branch")), (0, 0), "이미 공개된 글을 다시 올리지 않는다")

    def test_another_problem_with_the_check_is_raised_with_a_note_and_leaves_the_post_pushed(self):
        project_id = self.merged()
        self.backend.deploy_errors = [AppError("CONTENT_INVALID", {"항목": "배포 확인 설정"})]
        error = ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id)
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertIn("check-deploy", error.detail)
        self.assertEqual(self.status(project_id), st.PUSHED)

    def test_a_failure_to_record_the_published_state_says_so_and_check_deploy_completes_it(self):
        project_id = self.merged()
        restore = self.fail_the_store_after("check_deployed")
        error = ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id)
        restore()
        self.assertEqual(error.code, "STORE_LOCKED")
        self.assertIn("check-deploy 를 다시 실행", error.detail)
        self.assertEqual(self.status(project_id), st.PUSHED)
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)

    def test_check_deploy_only_works_for_a_post_whose_merge_was_confirmed(self):
        project_id = self.approved()
        error = ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.run_publish(project_id)
        error = ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.MERGE_PENDING))
        self.assertIn(f"merge-check {project_id[:8]}", error.detail, "병합을 기다리는 글은 먼저 병합 확인을 하라고 알린다")
        self.assertEqual(self.backend.count("check_deployed"), 0)

    def test_check_deploy_passes_its_deadline_and_a_zero_deadline_means_one_look(self):
        project_id = self.merged()
        pages_flow.check_pages_deploy(self.ctx, project_id, deadline=0)
        self.assertIn(("check_deployed", ss.KO_PATH, 0, pages_flow.DEFAULT_INTERVAL), self.backend.calls)

    def test_check_deploy_does_not_check_the_gates_or_the_repository_state(self):
        project_id = self.merged()
        self.backend.inspect_error = AppError("PAGES_LOCAL_REPO_DIRTY")        # 내 저장소가 지저분해도 이미 병합한 글의 공개 확인은 할 수 있다
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)
        self.assertEqual(self.backend.names(), ["expected_url", "check_deployed"])


class ResumeAndRecordTest(Base):
    def built(self):
        """가지를 올리다 멈춘 글 — APPROVED 이고 `built` 기록이 남았다."""
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.run_publish(project_id)
        self.backend.calls.clear()
        return project_id

    def test_resuming_checks_the_gates_and_the_repository_again_but_not_the_duplicates(self):
        project_id = self.built()
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.stage, plan.status, plan.path), (pages_flow.STAGE_BRANCH, st.APPROVED, ss.KO_PATH))
        self.assertIsNotNone(plan.resumed)
        self.assertEqual(self.backend.names(), ["inspect", "expected_url"], "같은 주소·같은 내용 점검은 처음 한 번뿐이다(이어받는 글은 자기 이름을 쥐고 있다)")
        self.assertTrue(plan.gates.ok)
        with mock.patch.dict(gate.LENGTH_MIN, {"ko": 10 ** 6}):
            self.assertEqual(ss.code_of(pages_flow.plan_pages_publish, self.ctx, project_id).code, "CHECK_FAILED")

    def test_an_edit_made_while_waiting_resets_the_approval_and_the_stale_built_record_is_not_taken_over_after_a_new_approval(self):
        project_id = self.built()
        old = self.journal.read(project_id)
        projects.edit_project(self.ctx, project_id, markdown=ss.ko_text(1800))
        self.assertEqual(self.status(project_id), st.DRAFT_GENERATED, "아직 올라가지 않은 글은 고치면 승인이 풀린다")
        self.assertEqual(ss.code_of(self.run_publish, project_id).code, "STATUS_TRANSITION_INVALID")
        review.request_review(self.ctx, project_id, "github_pages", pages=ss.KO_PARAMS)
        review.grant_approval(self.ctx, project_id, "github_pages")
        self.ctx.clock.advance(seconds=2)
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertIsNone(plan.resumed, "가지 이름에 글 내용의 해시가 있어 낡은 기록(옛 글)은 알아보고 이어받지 않는다")
        self.assertNotEqual(plan.branch, old.branch)
        report = self.run_publish(project_id)
        self.assertEqual((report.status, report.branch == old.branch), (st.MERGE_PENDING, False))

    def test_an_edit_between_the_build_and_the_push_of_the_same_run_also_stops_before_the_push(self):
        project_id = self.approved()
        real = pages_flow._record_built

        def record_then_edit(*args, **kwargs):
            record = real(*args, **kwargs)
            projects.edit_project(self.ctx, project_id, markdown=ss.ko_text(1800))        # 기록한 직후 다른 창에서 원고를 고쳤다
            return record

        with mock.patch.object(pages_flow, "_record_built", record_then_edit):
            error = ss.code_of(self.run_publish, project_id)
        self.assertEqual(error.code, "PUBLISH_CONTENT_CHANGED")
        self.assertEqual(self.backend.count("push_branch"), 0, "고친 원고가 아니라 승인했던 옛 글이 몰래 올라가는 일은 없다")
        self.assertEqual(self.status(project_id), st.DRAFT_GENERATED)

    def test_a_legacy_committed_post_cannot_be_published_or_resumed_only_cancelled(self):
        project_id = self.legacy_committed()
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.preview_publish(self.ctx, project_id), lambda: self.run_publish(project_id)):
            error = ss.code_of(call)
            self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.COMMITTED))
            self.assertIn(f"publish-pages {project_id[:8]} --cancel --yes", error.detail)
        self.assertEqual(self.backend.names(), [], "옛 글은 읽기만 한다 — backend 를 부르지 않는다")

    def test_a_damaged_record_stops_the_resume_and_is_left_untouched(self):
        project_id = self.built()
        path = self.ctx.workspace.journal_dir / f"{project_id}.json"
        for text in ("{깨짐", "[]", json.dumps({"schema": 1}), json.dumps({"schema": 1, "project_id": project_id, "path": "../etc/passwd", "commit": "c" * 40, "base": "b" * 40, "stage": "committed"}),
                     json.dumps({"schema": 1, "project_id": "다른글", "path": ss.KO_PATH, "commit": "c" * 40, "base": "b" * 40, "stage": "committed"}),
                     json.dumps({"schema": 1, "project_id": project_id, "path": ss.KO_PATH, "commit": "not-a-hash", "base": "b" * 40, "stage": "committed"}),
                     json.dumps({"schema": 2, "project_id": project_id, "path": ss.KO_PATH, "commit": "c" * 40, "base": "b" * 40, "stage": "built", "branch": "desktop/post-x"}),
                     json.dumps({"schema": 1, "project_id": project_id, "path": ss.KO_PATH, "commit": "c" * 40, "base": "b" * 40, "stage": "done"})):
            with self.subTest(text=text[:30]):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(ss.code_of(pages_flow.plan_pages_publish, self.ctx, project_id).code, "SETTINGS_INVALID")
                self.assertEqual(path.read_text(encoding="utf-8"), text)
                self.assertEqual(self.backend.count("push_branch"), 0)

    def test_the_publish_record_holds_only_a_repository_relative_path_and_hashes_and_the_branch(self):
        project_id = self.built()
        raw = (self.ctx.workspace.journal_dir / f"{project_id}.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertEqual(sorted(data), ["base", "branch", "commit", "path", "project_id", "schema", "stage"])      # 판 2(PUBPR): 칸 branch 가 더해졌다
        self.assertNotIn(str(self.tmp), raw, "이 PC 의 절대경로를 적지 않는다")
        self.assertFalse(Path(data["path"]).is_absolute())
        self.assertTrue(BRANCH_NAME.fullmatch(data["branch"]))

    def test_the_journal_only_accepts_known_stages_and_project_ids(self):
        with self.assertRaises(AppError):
            self.journal.read("../x")
        self.assertEqual(ss.code_of(self.journal.write, PublishRecord("p1", ss.KO_PATH, "c" * 40, "b" * 40, "weird")).code, "CONTENT_INVALID")
        self.assertEqual(ss.code_of(self.journal.write, "not a record").code, "CONTENT_INVALID")
        self.assertEqual(self.journal.remove("p1"), "", "없는 기록을 지우는 것은 오류가 아니다")

    def test_a_record_that_cannot_be_removed_is_reported_not_hidden(self):
        project_id = self.built()
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
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, project_id).stage, pages_flow.STAGE_BRANCH)

    def test_an_approval_for_another_revision_is_refused_even_if_the_store_somehow_held_it(self):
        """모델은 그런 상태를 저장하지 못하게 막지만, 올리기 직전에도 한 번 더 본다(방어)."""
        from chanceblog_desktop.content.store import Store
        project_id = self.approved()
        real_load = Store.load

        for broken in (0, None):
            with self.subTest(rendered_revision=broken):
                with mock.patch.object(Store, "load", lambda store, text_id: self._with_revision(real_load(store, text_id), broken)):
                    error = ss.code_of(self.run_publish, project_id)
                self.assertEqual(error.code, "STATUS_TRANSITION_INVALID")
                self.assertIn("다르다", error.detail)
        self.assertEqual(self.backend.count("build_branch_commit"), 0)

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
        self.assertEqual(self.backend.count("build_branch_commit"), 0)

    def test_if_the_state_cannot_be_saved_after_a_refusal_the_error_says_so(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("PAGES_PUSH_REFUSED")]
        real = self.ctx.store
        self.backend.hooks["push_branch"] = lambda: setattr(self.ctx, "store", self._locked)
        self._locked = lambda: (_ for _ in ()).throw(AppError("STORE_LOCKED"))
        error = ss.code_of(self.run_publish, project_id)
        self.ctx.store = real
        self.backend.hooks.clear()
        self.assertEqual(error.code, "PAGES_PUSH_REFUSED")
        self.assertIn("상태를 갱신하지 못했다(STORE_LOCKED)", error.detail)
        self.assertEqual(self.status(project_id), st.APPROVED)


class LegacyCancelTest(Base):
    """옛 방식(main 에 곧바로 올리던 시절)이 남긴 'COMMITTED' 글을 되돌리는 길만 남아 있다 — 이 PC 안의 일뿐이다."""

    def test_cancelling_undoes_the_commit_marks_the_post_failed_with_its_own_code_and_removes_the_record(self):
        project_id = self.legacy_committed()
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, self.status(project_id)), (st.PUBLISH_FAILED, st.PUBLISH_FAILED))
        self.assertEqual(self.variant(project_id).error_code, "PUBLISH_CANCELLED")
        self.assertEqual([call for call in self.backend.calls if call[0] == "discard"], [("discard", ss.KO_PATH, "c" * 40)])
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.backend.count("push_branch"), 0)
        json.dumps(report.to_dict())

    def test_a_cancelled_post_can_be_made_reviewed_approved_and_published_again(self):
        project_id = self.legacy_committed()
        pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        review.request_review(self.ctx, project_id, "github_pages", pages=ss.KO_PARAMS)
        review.grant_approval(self.ctx, project_id, "github_pages")
        self.ctx.clock.advance(seconds=9)
        self.assertEqual(self.run_publish(project_id).status, st.MERGE_PENDING)

    def test_cancelling_is_refused_when_the_commit_cannot_be_undone_and_nothing_changes(self):
        project_id = self.legacy_committed()
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED", detail="지금 HEAD 가 되돌릴 글 커밋이 아니다")
        self.backend.head_has_post = True
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.assertIsNotNone(self.journal.read(project_id))

    def test_other_refusals_of_the_undo_are_passed_on_as_they_are(self):
        project_id = self.legacy_committed()
        self.backend.discard_error = AppError("UNEXPECTED_ERROR", detail="이미 원격 main 에 올라간 커밋이라 되돌리지 않는다")
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "UNEXPECTED_ERROR")
        self.assertEqual(self.status(project_id), st.COMMITTED)

    def test_a_commit_that_is_already_gone_does_not_block_the_cancel(self):
        """되돌린 뒤 상태를 못 남겼던 경우: 기록도 파일도 없으면 할 일이 끝난 것으로 보고 상태만 정리한다."""
        project_id = self.legacy_committed()
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED")
        self.backend.head_has_post = False
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISH_FAILED)

    def test_a_file_that_is_still_there_is_not_taken_for_an_undone_commit(self):
        project_id = self.legacy_committed()
        leftover = self.tmp / "chanceblog" / ss.KO_PATH
        leftover.parent.mkdir(parents=True)
        leftover.write_text("남은 파일", encoding="utf-8")
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.status(project_id), st.COMMITTED)

    def test_only_an_old_style_commit_can_be_cancelled_and_a_pushed_post_is_never_undone(self):
        approved = self.approved(title="승인만 한 글")
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, approved, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.ctx.clock.advance(seconds=3)
        pushed = self.merged(title="올라간 글")
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, pushed, confirmed=True)
        self.assertEqual(error.code, "PUBLISH_ALREADY_PUSHED", "이미 올라간 글은 전용 오류로 거절한다")
        self.assertIn(f"check-deploy {pushed[:8]}", error.detail)
        self.assertEqual(self.backend.count("discard"), 0, "이미 올라간 글은 되돌리지 않는다")

    def test_cancelling_without_a_record_is_a_settings_error_and_changes_nothing(self):
        project_id = self.legacy_committed()
        (self.ctx.workspace.journal_dir / f"{project_id}.json").unlink()
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "SETTINGS_INVALID")
        self.assertEqual(self.status(project_id), st.COMMITTED)


class PlanDataTest(Base):
    def test_a_plan_for_each_stage_describes_its_own_actions(self):
        project_id = self.approved()
        branch_plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertTrue(any("새 가지" in action and "main 에는 올리지 않습니다" in action for action in branch_plan.actions))
        self.assertTrue(any("바꾸지 않습니다" in action for action in branch_plan.actions))
        self.assertTrue(any("앱이 열지 않으니" in action for action in branch_plan.actions))
        self.run_publish(project_id)
        merge_plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((merge_plan.stage, merge_plan.gates), (pages_flow.STAGE_MERGE, None))
        self.assertTrue(any("병합은 GitHub 에서 사람이 합니다" in action for action in merge_plan.actions))
        self.assertTrue(any("merge-check" in action for action in merge_plan.actions))
        self.backend.merge_results = [MERGED]
        pages_flow.merge_check_pages(self.ctx, project_id)
        verify_plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((verify_plan.stage, verify_plan.gates), (pages_flow.STAGE_VERIFY, None))
        self.assertTrue(any("공개 주소가 열리는지만" in action for action in verify_plan.actions))
        self.assertTrue(json.dumps(verify_plan.to_dict()))
        self.assertTrue(json.dumps(branch_plan.to_dict()))

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
