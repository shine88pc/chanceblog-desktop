"""서비스 층 — 검토 요청·승인·승인 취소와 네이버 복사 패키지 시험(네트워크·git 없음, 임시 폴더).

지키는 것:
  1) 검토 요청은 글을 그 플랫폼용으로 만들어 현재 판으로 기록하고 '검토 중' 으로 보낸다(검사에 걸려도 보여 줄 뿐 막지 않는다). 이미 승인된 글을 다시 만들면 먼저 승인이 풀린다.
  2) 승인은 사람이 직접 하고, GitHub Pages 는 승인하는 순간 검사를 **다시** 통과해야 한다(걸리면 CHECK_FAILED·키 모양 문자열이면 SECRET_IN_TEXT_BLOCKED — 승인되지 않고 상태도 그대로).
  3) 순서를 건너뛰면(승인 전에 승인·올라간 글을 다시 만들기 …) 모델의 오류 코드(STATUS_TRANSITION_INVALID)로 거절한다.
  4) 네이버: 두 블로그 글이 기준 이상 비슷하면 NAVER_SIMILARITY_HIGH — **직접 승인(`similarity_approved is True`)** 이 있어야 복사 준비(READY_TO_COPY)가 되고, 아니면 아무것도 바뀌지 않는다.
     복사용 글은 사람이 검토한 저장된 패키지 그대로 나가고, 발행 주소는 blog.naver.com 의 https 주소만 받는다. 네이버에 로그인하거나 글을 대신 올리지 않는다.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.service import naver_flow, pages_flow, previews, projects, review  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.service.naver_flow import NaverOptions  # noqa: E402

class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp)

    def new(self, text=None, title="에너지 절약 습관"):
        return projects.new_project(self.ctx, title, text or ss.ko_text()).project_id

    def status(self, project_id, platform="github_pages"):
        return ss.status_of(self.ctx, project_id, platform)

    def variant(self, project_id, platform="github_pages"):
        return projects.show_project(self.ctx, project_id).variant(platform)

    def review_pages(self, project_id, params=ss.KO_PARAMS):
        return review.request_review(self.ctx, project_id, "github_pages", pages=params)


class PagesReviewTest(Base):
    def test_a_review_stores_the_rendering_for_the_current_revision_and_moves_to_review_required(self):
        project_id = self.new()
        result = self.review_pages(project_id)
        self.assertEqual((result.status, result.platform, result.project_id), (st.REVIEW_REQUIRED, "github_pages", project_id))
        variant = self.variant(project_id)
        self.assertEqual((variant.status, variant.rendered_revision, variant.has_rendering), (st.REVIEW_REQUIRED, 1, True))
        self.assertTrue(result.pages.gates.ok)
        self.assertEqual(result.pages.path, ss.KO_PATH, "미리 보는 경로는 지금 시각(한국 시각)으로 만든다")

    def test_what_was_previewed_is_exactly_what_was_stored(self):
        project_id = self.new()
        shown = previews.preview_pages(self.ctx, project_id, ss.KO_PARAMS)
        self.review_pages(project_id)
        with self.ctx.store() as store:
            stored = store.load(project_id).variant("github_pages").rendered
        self.assertEqual(stored, shown.text)

    def test_the_review_result_converts_to_plain_data(self):
        project_id = self.new()
        data = self.review_pages(project_id).to_dict()
        self.assertEqual((data["status"], data["pages"]["lang"], data["naver"]), (st.REVIEW_REQUIRED, "ko", None))
        json.dumps(data)

    def test_a_review_without_the_settings_or_with_bad_ones_changes_nothing(self):
        project_id = self.new()
        self.assertEqual(ss.code_of(review.request_review, self.ctx, project_id, "github_pages").code, "CONTENT_INVALID")
        for params in (previews.PagesParams("", "ko", "https://x.example/a.jpg"), previews.PagesParams("경제", "ko", "http://x.example/a.jpg"), previews.PagesParams("경제", "fr", "https://x.example/a.jpg"),
                       previews.PagesParams("경제", "ko", "https://x.example/a.jpg", ("a",) * 99)):
            with self.subTest(params=params):
                self.assertEqual(ss.code_of(self.review_pages, project_id, params).code, "CONTENT_INVALID")
        self.assertEqual(self.status(project_id), st.NOT_STARTED)

    def test_a_review_shows_the_gate_problems_but_does_not_block_it(self):
        project_id = self.new("짧은 글입니다. " * 10)
        result = self.review_pages(project_id)
        self.assertEqual(result.status, st.REVIEW_REQUIRED)
        self.assertFalse(result.pages.gates.ok)
        self.assertIn("LEN_SHORT", result.pages.gates.codes())

    def test_only_the_platforms_this_bundle_handles_can_be_reviewed(self):
        project_id = self.new()
        for platform in ("blogger_en", "blogger_ko", "twitter", None):
            with self.subTest(platform=platform):
                self.assertEqual(ss.code_of(review.request_review, self.ctx, project_id, platform, pages=ss.KO_PARAMS).code, "CONTENT_INVALID")
                self.assertEqual(ss.code_of(review.grant_approval, self.ctx, project_id, platform).code, "CONTENT_INVALID")
                self.assertEqual(ss.code_of(review.revoke_approval, self.ctx, project_id, platform).code, "CONTENT_INVALID")

    def test_reviewing_again_replaces_the_rendering_and_stays_in_review(self):
        project_id = self.new()
        self.review_pages(project_id)
        second = self.review_pages(project_id, ss.PagesParams("사회", "ko", "https://images.example.invalid/c.jpg"))
        self.assertEqual(second.status, st.REVIEW_REQUIRED)
        with self.ctx.store() as store:
            self.assertIn('category: "사회"', store.load(project_id).variant("github_pages").rendered)

    def test_reviewing_an_approved_post_again_first_withdraws_the_approval(self):
        project_id = ss.make_approved(self.ctx)
        self.assertEqual(self.status(project_id), st.APPROVED)
        result = self.review_pages(project_id, ss.PagesParams("사회", "ko", "https://images.example.invalid/c.jpg"))
        self.assertEqual(result.status, st.REVIEW_REQUIRED, "승인은 새로 만든 글에 따라가지 않는다")
        self.assertEqual(ss.code_of(pages_flow.plan_pages_publish, self.ctx, project_id).code, "STATUS_TRANSITION_INVALID")

    def test_a_post_that_is_already_committed_or_online_cannot_be_made_again(self):
        project_id = ss.make_approved(self.ctx)
        pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True, wait=False)
        self.assertEqual(self.status(project_id), st.PUSHED)
        error = ss.code_of(self.review_pages, project_id)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.PUSHED))


class PagesApprovalTest(Base):
    def test_approval_needs_the_review_step_first(self):
        project_id = self.new()
        for _ in range(2):
            error = ss.code_of(review.grant_approval, self.ctx, project_id, "github_pages")
            self.assertEqual((error.code, error.slots["현재 상태"], error.slots["요청 상태"]), ("STATUS_TRANSITION_INVALID", st.NOT_STARTED, st.APPROVED))
        self.assertEqual(self.status(project_id), st.NOT_STARTED)

    def test_the_human_approval_moves_a_reviewed_post_to_approved_and_reports_the_gates(self):
        project_id = self.new()
        self.review_pages(project_id)
        result = review.grant_approval(self.ctx, project_id, "github_pages")
        self.assertEqual((result.status, result.gates.ok), (st.APPROVED, True))
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertTrue(result.to_dict()["gates"]["ok"])

    def test_the_gates_are_run_again_at_approval_and_failing_ones_block_it(self):
        project_id = self.new("짧은 글입니다. " * 10)
        self.review_pages(project_id)
        error = ss.code_of(review.grant_approval, self.ctx, project_id, "github_pages")
        self.assertEqual(error.code, "CHECK_FAILED")
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED, "승인되지 않았다")

    def test_a_key_shaped_string_blocks_the_approval_with_its_own_code(self):
        project_id = self.new()
        ss.inject_text(self.ctx, project_id, text=ss.ko_text(extra=f"실수로 {ss.KEY} 를 붙였습니다."))        # 옛 버전이 저장한 글 — 쓰기 길은 이제 거절한다(PCSEC1 M3). 승인 관문이 두 번째 방어선으로 남는다
        self.review_pages(project_id)
        error = ss.code_of(review.grant_approval, self.ctx, project_id, "github_pages")
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
        self.assertNotIn(ss.KEY, error.detail + error.log_line())
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)

    def test_a_path_of_this_pc_in_the_post_blocks_the_approval(self):
        project_id = self.new(ss.ko_text(extra=f"원본은 {self.ctx.workspace.root} 에 있습니다."))
        self.review_pages(project_id)
        self.assertEqual(ss.code_of(review.grant_approval, self.ctx, project_id, "github_pages").code, "CHECK_FAILED")

    def test_revoking_returns_to_review_and_only_an_approval_can_be_revoked(self):
        project_id = ss.make_approved(self.ctx)
        result = review.revoke_approval(self.ctx, project_id, "github_pages")
        self.assertEqual((result.status, self.status(project_id)), (st.REVIEW_REQUIRED, st.REVIEW_REQUIRED))
        self.assertEqual(ss.code_of(review.revoke_approval, self.ctx, project_id, "github_pages").code, "STATUS_TRANSITION_INVALID")
        review.grant_approval(self.ctx, project_id, "github_pages")
        self.assertEqual(self.status(project_id), st.APPROVED, "다시 읽어 보고 승인할 수 있다")

    def test_a_revoked_post_cannot_be_published(self):
        project_id = ss.make_approved(self.ctx)
        review.revoke_approval(self.ctx, project_id, "github_pages")
        self.assertEqual(ss.code_of(pages_flow.plan_pages_publish, self.ctx, project_id).code, "STATUS_TRANSITION_INVALID")

    def test_approving_an_unknown_post_is_not_found(self):
        self.assertEqual(ss.code_of(review.grant_approval, self.ctx, "ffffffff", "github_pages").code, "CONTENT_NOT_FOUND")


class NaverReviewTest(Base):
    def setUp(self):
        super().setUp()
        ss.naver_profiles(self.ctx)

    def test_a_review_needs_the_blogs_profile(self):
        ctx = ss.make_ctx(self.tmp / "other")
        project_id = projects.new_project(ctx, "글", ss.ko_text()).project_id
        error = ss.code_of(review.request_review, ctx, project_id, "naver_a")
        self.assertEqual((error.code, error.slots["블로그"]), ("NAVER_PROFILE_MISSING", "naver_a"))
        self.assertEqual(ss.status_of(ctx, project_id, "naver_a"), st.NOT_STARTED)

    def test_the_package_is_stored_as_json_and_read_back_equal_to_the_preview(self):
        project_id = self.new()
        result = review.request_review(self.ctx, project_id, "naver_a")
        self.assertEqual(result.status, st.REVIEW_REQUIRED)
        with self.ctx.store() as store:
            stored = store.load(project_id).variant("naver_a").rendered
        self.assertEqual(naver_flow.package_from_json(stored), result.naver.package)
        self.assertIn("#생활", result.naver.package.tags_text)

    def test_per_blog_changes_are_used(self):
        project_id = self.new()
        options = NaverOptions(title="블로그 에이용 제목", body=ss.DIFFERENT, tags=("추가",), ai_assisted=False)
        package = review.request_review(self.ctx, project_id, "naver_a", naver_options=options).naver.package
        self.assertEqual(package.title, "블로그 에이용 제목")
        self.assertIn("추가", package.tags)
        self.assertNotIn("AI 도구의 도움", package.body_text)

    def test_the_package_json_is_read_strictly(self):
        project_id = self.new()
        stored = naver_flow.package_to_json(review.request_review(self.ctx, project_id, "naver_a").naver.package)
        data = json.loads(stored)
        for bad in ("", "[]", "{", json.dumps({**data, "schema": 9}), json.dumps({**data, "extra": 1}), json.dumps({**data, "title": 5}), json.dumps({**data, "tags": "a"}),
                    json.dumps({**data, "images": [{"number": 1}]}), json.dumps({**data, "chars": "많이"})):
            with self.subTest(text=bad[:30]):
                self.assertEqual(ss.code_of(naver_flow.package_from_json, bad).code, "CONTENT_INVALID")

    def test_approving_a_naver_package_needs_the_review_first(self):
        project_id = self.new()
        self.assertEqual(ss.code_of(review.grant_approval, self.ctx, project_id, "naver_a").code, "STATUS_TRANSITION_INVALID")

    def test_the_other_blog_not_being_ready_yet_means_there_is_nothing_to_compare(self):
        project_id = self.new()
        review.request_review(self.ctx, project_id, "naver_a")
        result = review.grant_approval(self.ctx, project_id, "naver_a")
        self.assertEqual((result.status, result.similarity), (st.READY_TO_COPY, None))

    def test_two_nearly_identical_packages_need_the_humans_direct_approval(self):
        project_id = self.new()
        review.request_review(self.ctx, project_id, "naver_a")
        second = review.request_review(self.ctx, project_id, "naver_b")
        self.assertEqual(second.similarity.level, "high", "검토 요청은 비슷함을 알리기만 한다")
        for flag in (False, None, 0, 1, "yes", "True"):
            with self.subTest(flag=flag):
                error = ss.code_of(review.grant_approval, self.ctx, project_id, "naver_a", similarity_approved=flag)
                self.assertEqual(error.code, "NAVER_SIMILARITY_HIGH")
                self.assertEqual(self.status(project_id, "naver_a"), st.REVIEW_REQUIRED, "승인되지 않았다")
        result = review.grant_approval(self.ctx, project_id, "naver_a", similarity_approved=True)
        self.assertEqual((result.status, result.similarity.level), (st.READY_TO_COPY, "high"))

    def test_clearly_different_packages_pass_without_any_special_approval(self):
        project_id = self.new()
        review.request_review(self.ctx, project_id, "naver_a")
        review.request_review(self.ctx, project_id, "naver_b", naver_options=NaverOptions(title="전혀 다른 제목의 이야기", body=ss.DIFFERENT, tags=("산책",)))
        result = review.grant_approval(self.ctx, project_id, "naver_a")
        self.assertEqual(result.status, st.READY_TO_COPY)
        self.assertNotEqual(result.similarity.level, "high")

    def test_the_comparison_uses_the_stored_other_package_even_if_it_is_not_approved_yet(self):
        project_id = self.new()
        review.request_review(self.ctx, project_id, "naver_b")
        review.request_review(self.ctx, project_id, "naver_a")
        self.assertEqual(self.status(project_id, "naver_b"), st.REVIEW_REQUIRED)
        self.assertEqual(ss.code_of(review.grant_approval, self.ctx, project_id, "naver_a").code, "NAVER_SIMILARITY_HIGH")

    def test_revoking_ready_to_copy_goes_back_to_review_and_a_new_review_withdraws_it_first(self):
        project_id = self.new()
        review.request_review(self.ctx, project_id, "naver_a")
        review.grant_approval(self.ctx, project_id, "naver_a")
        review.revoke_approval(self.ctx, project_id, "naver_a")
        self.assertEqual(self.status(project_id, "naver_a"), st.REVIEW_REQUIRED)
        review.grant_approval(self.ctx, project_id, "naver_a")
        again = review.request_review(self.ctx, project_id, "naver_a", naver_options=NaverOptions(title="새 제목"))
        self.assertEqual((again.status, again.naver.package.title), (st.REVIEW_REQUIRED, "새 제목"))

    def test_editing_the_manuscript_withdraws_the_copy_approval(self):
        project_id = self.new()
        review.request_review(self.ctx, project_id, "naver_a")
        review.grant_approval(self.ctx, project_id, "naver_a")
        projects.edit_project(self.ctx, project_id, markdown=ss.ko_text(1700))
        self.assertEqual(self.status(project_id, "naver_a"), st.DRAFT_GENERATED)


class NaverIssueTest(Base):
    def setUp(self):
        super().setUp()
        ss.naver_profiles(self.ctx)
        self.project_id = self.new()

    def test_issuing_a_reviewed_package_is_the_approval_and_returns_the_stored_package(self):
        reviewed = review.request_review(self.ctx, self.project_id, "naver_a").naver.package
        issue = review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        self.assertEqual((issue.status, issue.package, issue.similarity), (st.READY_TO_COPY, reviewed, None))
        self.assertEqual(self.status(self.project_id, "naver_a"), st.READY_TO_COPY)

    def test_the_copy_text_has_title_body_tags_image_places_and_the_checklist(self):
        projects.edit_project(self.ctx, self.project_id, assets=(projects.parse_asset("사진1.png|첫 사진|1"),))
        review.request_review(self.ctx, self.project_id, "naver_a")
        text = naver_flow.copy_text(review.issue_naver_package(self.ctx, self.project_id, "naver_a").package)
        for needle in ("[제목]", "에너지 절약 습관", "[본문]", "[태그]", "#생활", "[이미지 자리]", "[이미지 1] 파일 사진1.png — 첫 사진", "[발행 전 체크리스트]", "AI 활용 고지문"):
            self.assertIn(needle, text, needle)

    def test_issuing_again_shows_the_same_package_without_changing_anything(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        first = review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        second = review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        self.assertEqual((second.package, second.status), (first.package, st.READY_TO_COPY))

    def test_a_package_whose_copy_was_marked_done_can_still_be_shown_again(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        first = review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        with self.ctx.store() as store:
            project = store.load(self.project_id)
            project.transition("naver_a", st.COPY_COMPLETED, now="2026-11-02T02:00:00Z")
            store.save(project)
        again = review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        self.assertEqual((again.status, again.package), (st.COPY_COMPLETED, first.package))

    def test_issuing_without_a_review_is_refused(self):
        for platform in ("naver_a", "naver_b"):
            error = ss.code_of(review.issue_naver_package, self.ctx, self.project_id, platform)
            self.assertEqual((error.code, error.slots["요청 상태"]), ("STATUS_TRANSITION_INVALID", st.READY_TO_COPY))

    def test_a_package_too_similar_to_the_other_blogs_is_not_issued_without_the_direct_approval(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        review.request_review(self.ctx, self.project_id, "naver_b")
        before = self.status(self.project_id, "naver_a")
        error = ss.code_of(review.issue_naver_package, self.ctx, self.project_id, "naver_a")
        self.assertEqual(error.code, "NAVER_SIMILARITY_HIGH")
        self.assertIn("유사도", error.detail)
        for flag in (None, 0, 1, "yes", "True"):
            with self.subTest(flag=flag):
                self.assertEqual(ss.code_of(review.issue_naver_package, self.ctx, self.project_id, "naver_a", similarity_approved=flag).code, "NAVER_SIMILARITY_HIGH")
        self.assertEqual(self.status(self.project_id, "naver_a"), before, "복사용 글도 나가지 않고 상태도 그대로다")
        issue = review.issue_naver_package(self.ctx, self.project_id, "naver_a", similarity_approved=True)
        self.assertEqual((issue.status, issue.similarity.level), (st.READY_TO_COPY, "high"))

    def test_an_unknown_blog_is_refused(self):
        self.assertEqual(ss.code_of(review.issue_naver_package, self.ctx, self.project_id, "naver_c").code, "CONTENT_INVALID")
        self.assertEqual(ss.code_of(review.record_naver_published, self.ctx, self.project_id, "github_pages", "https://blog.naver.com/x/1").code, "CONTENT_INVALID")

    def test_the_published_address_is_recorded_after_the_copy_and_only_a_naver_address_is_accepted(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        for bad in ("", "http://blog.naver.com/x/1", "https://example.com/x/1", "https://user:pw@blog.naver.com/x/1", "blog.naver.com/x/1"):
            with self.subTest(url=bad):
                self.assertIn(ss.code_of(review.record_naver_published, self.ctx, self.project_id, "naver_a", bad).code, ("NAVER_PUBLISH_URL_INVALID", "PUBLISHED_URL_REQUIRED"))
                self.assertEqual(self.status(self.project_id, "naver_a"), st.READY_TO_COPY, "주소가 틀리면 아무것도 바뀌지 않는다")
        result = review.record_naver_published(self.ctx, self.project_id, "naver_a", "https://blog.naver.com/exampleaaa/223000000001")
        self.assertEqual(result.status, st.PUBLISHED_MANUAL)
        variant = self.variant(self.project_id, "naver_a")
        self.assertEqual(variant.published_url, "https://blog.naver.com/exampleaaa/223000000001")
        self.assertEqual(variant.published_at, "2026-11-02T01:30:12Z")

    def test_recording_an_address_before_the_copy_step_is_refused(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        self.assertEqual(ss.code_of(review.record_naver_published, self.ctx, self.project_id, "naver_a", "https://blog.naver.com/a/1").code, "STATUS_TRANSITION_INVALID")

    def test_a_published_naver_post_cannot_be_issued_again_or_made_again(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        review.record_naver_published(self.ctx, self.project_id, "naver_a", "https://blog.naver.com/a/1")
        self.assertEqual(ss.code_of(review.issue_naver_package, self.ctx, self.project_id, "naver_a").code, "STATUS_TRANSITION_INVALID")
        self.assertEqual(ss.code_of(review.request_review, self.ctx, self.project_id, "naver_a").code, "STATUS_TRANSITION_INVALID")

    def test_a_corrupted_stored_package_stops_the_issue(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        with self.ctx.store() as store:
            project = store.load(self.project_id)
            project.variants["naver_a"].rendered = "이건 패키지가 아니다"
            store.save(project)
        self.assertEqual(ss.code_of(review.issue_naver_package, self.ctx, self.project_id, "naver_a").code, "CONTENT_INVALID")
        self.assertEqual(self.status(self.project_id, "naver_a"), st.REVIEW_REQUIRED)

    def test_the_copy_text_names_the_blog_category_and_the_warnings(self):
        self.ctx.settings.save_naver_profile(NaverProfile("naver_a", "블로그 에이", "https://blog.naver.com/exampleaaa", default_tags=("생활",), categories={"경제": "경제 이야기"}, min_chars=10, max_chars=20,
                                                          forbidden_phrases=("에너지",)))
        review.request_review(self.ctx, self.project_id, "naver_a", naver_options=NaverOptions(category="경제"))
        text = naver_flow.copy_text(review.issue_naver_package(self.ctx, self.project_id, "naver_a").package)
        for needle in ("[카테고리]", "경제 이야기", "[주의]", "금지 표현 「에너지」", "기준(10~20자)보다 깁니다"):
            self.assertIn(needle, text, needle)

    def test_a_post_whose_copy_was_made_can_be_made_again_after_withdrawing_the_approval(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        with self.ctx.store() as store:                                   # 복사를 마친 상태(다른 흐름이 남길 수 있다)
            project = store.load(self.project_id)
            project.transition("naver_a", st.COPY_COMPLETED, now="2026-11-02T02:00:00Z")
            store.save(project)
        again = review.request_review(self.ctx, self.project_id, "naver_a", naver_options=NaverOptions(title="다시 만든 제목"))
        self.assertEqual((again.status, again.naver.package.title), (st.REVIEW_REQUIRED, "다시 만든 제목"))

    def test_issue_result_converts_to_plain_data_with_the_copy_text(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        data = review.issue_naver_package(self.ctx, self.project_id, "naver_a").to_dict()
        self.assertIn("copy_text", data)
        self.assertEqual(data["package"]["blog"], "naver_a")
        json.dumps(data)


class NaverSettingsErrorsTest(Base):
    def test_a_damaged_profile_is_not_taken_for_a_missing_one(self):
        self.ctx.settings.path.parent.mkdir(parents=True, exist_ok=True)
        bad = {"schema": 1, "repo_path": "", "naver_profiles": {"naver_a": {"key": "naver_a", "display_name": "x", "blog_url": "http://not-naver.example/x"}}}
        self.ctx.settings.path.write_text(json.dumps(bad), encoding="utf-8")
        project_id = self.new()
        for call in (lambda: previews.preview_naver(self.ctx, project_id), lambda: naver_flow.set_profile(self.ctx.settings, "naver_a", {"tone": "x"})):
            self.assertEqual(ss.code_of(call).code, "SETTINGS_INVALID")


class NaverProfileSetTest(Base):
    def test_a_new_profile_needs_a_name_and_an_address_and_is_validated(self):
        settings = self.ctx.settings
        self.assertEqual(ss.code_of(naver_flow.set_profile, settings, "naver_a", {"topic": "경제"}).code, "NAVER_PROFILE_MISSING")
        self.assertEqual(ss.code_of(naver_flow.set_profile, settings, "naver_a", {"display_name": "이름", "blog_url": "https://example.com/x"}).code, "CONTENT_INVALID")
        self.assertEqual(ss.code_of(naver_flow.set_profile, settings, "naver_c", {"display_name": "이름", "blog_url": "https://blog.naver.com/x"}).code, "CONTENT_INVALID")
        saved = naver_flow.set_profile(settings, "naver_a", {"display_name": "블로그 에이", "blog_url": "https://blog.naver.com/exampleaaa", "default_tags": ["생활"]})
        self.assertEqual((saved.key, saved.default_tags), ("naver_a", ("생활",)))

    def test_later_changes_keep_the_other_values(self):
        settings = self.ctx.settings
        naver_flow.set_profile(settings, "naver_a", {"display_name": "블로그 에이", "blog_url": "https://blog.naver.com/exampleaaa", "topic": "경제"})
        changed = naver_flow.set_profile(settings, "naver_a", {"tone": "차분하게"})
        self.assertEqual((changed.topic, changed.tone, changed.display_name), ("경제", "차분하게", "블로그 에이"))
        renamed = naver_flow.set_profile(settings, "naver_a", {"display_name": "새 이름"})
        self.assertEqual((renamed.display_name, renamed.tone), ("새 이름", "차분하게"), "준 값은 반영된다")
        self.assertEqual(ss.code_of(naver_flow.set_profile, settings, "naver_a", {"min_chars": 10 ** 7}).code, "CONTENT_INVALID")
        self.assertEqual(settings.naver_profile("naver_a").tone, "차분하게", "잘못된 값은 저장하지 않는다")


def setUpModule():
    ss.external_write_on()                                   # 이 시험은 게시 흐름을 쓴다 — 외부 Write 관문을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    ss.external_write_off()


if __name__ == "__main__":
    unittest.main()
