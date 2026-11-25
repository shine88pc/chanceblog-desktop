"""글 흐름 1b(결정 D-642 이후)의 순수 부분 시험(PySide6 없이 돈다 — CI 와 같은 조건) — 네이버 복사 패키지·복사 표시·발행 주소 기록·유사도를 알고도 승인하기·발행 기록·작업 로그 규칙.

지키는 것:
  1) 복사용 패키지는 복사 준비됨·복사함에서만 보이고 **고른 블로그의 것만** 복사하며(A 와 B 가 섞이지 않는다) 키·토큰 모양이 든 글은 복사하지 않는다. **복사 단추는 상태를 바꾸지 않는다** — 사람이 `복사했어요` 를 눌러야 복사함이 된다.
  2) 발행 주소는 복사함에서만 기록하고, 주소 모양(https·네이버 블로그·글 주소·계정 정보 없음)과 비밀 모양을 화면이 먼저 거르며 걸리면 서비스를 부르지 않는다. 화면의 검사는 서비스의 검사보다 느슨하지 않다.
  3) `그래도 승인하기` 는 막힘이 유사도 하나뿐일 때만, 센 확인창을 거친 요청만 서비스의 `similarity_approved` 가 되고 일반 승인은 늘 거짓이다.
  4) 발행 기록은 오래된 순서가 기본이고 모르는 상태도 죽지 않으며 작업 로그는 읽기뿐이고 줄을 다시 가린다(D-93).
  5) 건강 효과 단정 판정은 Pages 한 줄 설명·태그에도 걸리고 검토가 쓴 값이 승인 요청에 함께 간다.
가짜 비밀은 조립한 문자열이고 실제 글·블로그 이름은 어디에도 없다.
"""
import dataclasses
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import model as content_model  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.service import history as service_history  # noqa: E402
from chanceblog_desktop.service import worklog as service_worklog  # noqa: E402
from chanceblog_desktop.ui.core import jobs, post_fake, post_history, post_history_text, post_history_view, post_rules as rules, posts, posts_view, text  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
KEY = ss.KEY
A, B = posts.NAVER_A, posts.NAVER_B
GOOD_URL = "https://blog.naver.com/exampleaaa/223000000001"
STOP_SENTENCE = "이 영양제를 먹으면 통증이 완전히 사라집니다."
RAW = {"category": "생활", "lang": "ko", "image_url": "https://img.example.invalid/a.jpg", "tags": "에너지, 습관", "description": ""}


class Recording(post_fake.FakePostsProvider):
    """부른 요청을 모두 적어 두는 가짜 공급자 — 컨트롤러가 어떤 요청을 보냈는지(유사도 승인·Pages 값 …)를 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = []

    def _note(self, name, request):
        self.requests.append((name, request))

    def approve_post(self, request, progress, cancelled):
        self._note("approve", request)
        return super().approve_post(request, progress, cancelled)

    def mark_copied(self, request, progress, cancelled):
        self._note("copied", request)
        return super().mark_copied(request, progress, cancelled)

    def record_published(self, request, progress, cancelled):
        self._note("record", request)
        return super().record_published(request, progress, cancelled)


def make(scenario="empty", provider=None, **kwargs):
    provider = provider or Recording(scenario, **kwargs)
    controller = posts_view.PostsController(provider, jobs.JobRunner())
    controller.apply_loaded(provider.load_posts(SAFE, NEVER))
    return controller


def drive(controller, starter):
    """일을 시작하고 끝까지 기다려 결과를 받는다(셸이 하는 일과 같다) → (시작 상태, 끝난 일, 셸이 할 일)."""
    results = {}
    status, detail = starter(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if status != "started":
        return status, detail, None
    detail.join(10)
    if "ok" in results:
        return status, "ok", controller.apply_write_ok(results["ok"])
    return status, "failed", controller.apply_write_failed(results["failed"])


def open_post(controller, project_id):
    results = {}
    status, job = controller.start_open(project_id, on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if status != "started":
        return status
    job.join(10)
    controller.apply_detail(results["ok"])
    return "ok"


def with_post(markdown=None, title="복사할 글", **kwargs):
    controller = make("empty", **kwargs)
    project_id = controller.provider.add_post(title, markdown if markdown is not None else post_fake.sample_text())
    controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
    open_post(controller, project_id)
    return controller, project_id


def review(controller, platform):
    controller.select_platform(platform)
    return drive(controller, lambda **cb: controller.start_review(platform, None, **cb))


def approve(controller, platform):
    controller.select_platform(platform)
    controller.approve_dialog()
    return drive(controller, lambda **cb: controller.start_approve(**cb))


def ready(controller, platform=A):
    """검토 → 승인까지 해 복사 준비됨으로 만든다."""
    review(controller, platform)
    return approve(controller, platform)


def copied(controller):
    return drive(controller, lambda **cb: controller.start_copied(True, **cb))


def panel(controller):
    return controller.view()["detail"]["review"]["panel"]


def status_of(controller, platform):
    return controller.detail.platform(platform).status


class PostsPackageCoreTest(unittest.TestCase):
    def test_the_package_card_is_only_there_after_the_approval_and_for_a_naver_blog(self):
        controller, _ = with_post()
        for platform in (posts.PAGES, A, B):
            controller.select_platform(platform)
            self.assertIsNone(panel(controller)["package"], f"{platform}: 시작 전에는 카드가 없다")
        review(controller, A)
        self.assertIsNone(panel(controller)["package"], "검토 중에도 없다")
        ready_status = approve(controller, A)
        self.assertEqual(ready_status[1], "ok")
        card = panel(controller)["package"]
        self.assertEqual((card["mode"], card["title"]), ("ready", T["post_pkg_title"]))
        self.assertEqual([item["kind"] for item in card["copies"]], ["title", "body", "tags", "all"])
        self.assertTrue(all(item["enabled"] and item["a11y"] for item in card["copies"]))
        self.assertEqual((card["copied"]["visible"], card["copied"]["enabled"], card["copied"]["primary"], card["uncopy"]["visible"], card["record"]["visible"]), (True, True, True, False, False))
        controller.select_platform(posts.PAGES)
        self.assertIsNone(panel(controller)["package"], "Pages 에는 이 카드가 없다")

    def test_the_card_lines_say_title_size_and_tags_and_hide_nothing_behind_codes(self):
        controller, _ = with_post(title="에너지 절약 습관")
        ready(controller)
        card = panel(controller)["package"]
        self.assertEqual(card["lines"][0], T["post_pkg_line_title"].format(title="에너지 절약 습관"))
        self.assertTrue(card["lines"][1].startswith("본문 ") and "문단" in card["lines"][1] and "이미지 자리" in card["lines"][1])
        self.assertEqual(card["lines"][2], T["post_pkg_line_tags"].format(tags="#예시 #에이"))

    def test_the_copy_texts_are_exactly_the_package_and_copying_never_changes_the_state(self):
        controller, project_id = with_post()
        ready(controller)
        package = controller.package()
        calls_before = list(controller.provider.calls)
        got = {kind: controller.copy_payload(kind) for kind in posts_view.COPY_KINDS}
        self.assertEqual(got, {"title": (package.title, ""), "body": (package.body, ""), "tags": (package.tags, ""), "all": (package.copy_text, "")})
        self.assertIn("[제목]", package.copy_text)
        self.assertEqual(status_of(controller, A), st.READY_TO_COPY, "복사 단추를 눌러도 복사함이 되지 않는다")
        self.assertEqual(controller.provider.calls, calls_before, "복사는 공급자를 부르지 않는다")
        self.assertEqual([item[0] for item in controller.provider.requests], ["approve"])

    def test_nothing_is_copied_when_there_is_no_package_or_the_kind_is_unknown(self):
        controller, _ = with_post()
        for kind in posts_view.COPY_KINDS + ("url", "other"):
            self.assertEqual(controller.copy_payload(kind), (None, "post_pkg_copy_none"), "아직 패키지도 발행 주소도 없다")
        review(controller, A)
        self.assertEqual(controller.copy_payload("title"), (None, "post_pkg_copy_none"), "검토 중에는 복사하지 않는다")
        approve(controller, A)
        self.assertEqual(controller.copy_payload("other"), (None, "post_pkg_copy_none"))
        self.assertEqual(controller.copy_payload("url"), (None, "post_pkg_copy_none"), "발행 주소는 직접 발행함에서만")

    def test_blog_a_and_blog_b_never_mix_the_package_that_is_copied_follows_the_chosen_blog(self):
        controller, _ = with_post()
        ready(controller, A)
        first = posts.NaverPackageInfo(A, "에이 제목", "에이 본문", "#에이", "에이 전체")
        second = posts.NaverPackageInfo(B, "비 제목", "비 본문", "#비", "비 전체")
        mixed = dataclasses.replace(controller.detail, platforms=tuple(dataclasses.replace(item, status=st.READY_TO_COPY) if item.platform in (A, B) else item for item in controller.detail.platforms), packages=(first, second))
        controller.detail = mixed
        controller.select_platform(A)
        self.assertEqual([controller.copy_payload(kind)[0] for kind in posts_view.COPY_KINDS], ["에이 제목", "에이 본문", "#에이", "에이 전체"])
        controller.select_platform(B)
        self.assertEqual([controller.copy_payload(kind)[0] for kind in posts_view.COPY_KINDS], ["비 제목", "비 본문", "#비", "비 전체"])
        self.assertEqual(controller.package().platform, B)
        controller.detail = dataclasses.replace(mixed, packages=(first,))
        self.assertIsNone(controller.package(), "고른 블로그의 패키지가 없으면 다른 블로그의 것을 대신 내지 않는다")
        self.assertEqual(controller.copy_payload("title"), (None, "post_pkg_copy_none"))

    def test_a_package_with_a_key_shaped_text_is_not_copied_for_that_part_only(self):
        controller, _ = with_post(markdown="## 소제목\n\n본문 줄 " + KEY + " 이어지는 글입니다.", title="일반 제목")
        ready(controller)                                         # 가짜 공급자는 검사 없이 글을 만든다 — 승인은 막힐 글이지만 이미 복사 준비됨인 글을 흉내 낸다
        controller.detail = dataclasses.replace(controller.detail, platforms=tuple(dataclasses.replace(item, status=st.READY_TO_COPY) if item.platform == A else item for item in controller.detail.platforms),
                                                packages=(controller.provider._package(controller.provider.projects[controller.open_id], A),))
        package = controller.package()
        self.assertEqual(sorted(package.blocked), ["all", "body"])
        self.assertEqual(controller.copy_payload("body"), (None, "post_pkg_copy_blocked"))
        self.assertEqual(controller.copy_payload("all"), (None, "post_pkg_copy_blocked"))
        self.assertEqual(controller.copy_payload("title"), ("일반 제목", ""))
        card = panel(controller)["package"]
        self.assertEqual({item["kind"]: item["enabled"] for item in card["copies"]}, {"title": True, "body": False, "tags": True, "all": False})
        self.assertEqual(card["blocked"], T["post_pkg_copy_blocked"])
        self.assertNotIn(KEY[:10], repr(card) + repr(controller.view()))

    def test_a_missing_package_shows_a_retry_and_the_copied_button_is_not_offered(self):
        controller, _ = with_post()
        ready(controller)
        controller.detail = dataclasses.replace(controller.detail, packages=())
        card = panel(controller)["package"]
        self.assertEqual((card["mode"], card["copies"], card["copied"], card["lines"]), ("missing", [], None, [T["post_pkg_missing"]]))
        self.assertEqual(card["reread"]["text"], T["post_retry"])
        self.assertEqual(controller.start_copied(True)[0], "state", "패키지를 읽지 못했으면 복사함으로 표시하지 않는다")


class PostsCopiedCoreTest(unittest.TestCase):
    def test_the_copied_button_is_the_only_way_to_the_copied_state_and_it_can_be_taken_back(self):
        controller, _ = with_post()
        ready(controller)
        status, end, todo = copied(controller)
        self.assertEqual((status, end, todo), ("started", "ok", {"reload_list": True}))
        self.assertEqual(status_of(controller, A), st.COPY_COMPLETED)
        self.assertEqual(controller.notice, ("ok", T["post_done_copied"]))
        card = panel(controller)["package"]
        self.assertEqual((card["mode"], card["copied"]["visible"], card["uncopy"]["visible"], card["record"]["visible"], card["record"]["primary"]), ("copied", False, True, True, True))
        self.assertEqual(panel(controller)["after"], "", "복사함 다음 일은 패키지 카드가 말한다")
        status, end, _todo = drive(controller, lambda **cb: controller.start_copied(False, **cb))
        self.assertEqual((status, end, status_of(controller, A)), ("started", "ok", st.READY_TO_COPY))
        self.assertEqual(controller.notice, ("ok", T["post_done_uncopied"]))
        self.assertEqual([request.copied for name, request in controller.provider.requests if name == "copied"], [True, False])

    def test_the_marks_are_refused_in_every_other_state_and_while_busy_or_restoring(self):
        controller, _ = with_post()
        for platform in (posts.PAGES, A, B):
            controller.select_platform(platform)
            for copied_flag in (True, False):
                self.assertEqual(controller.start_copied(copied_flag)[0], "state", f"{platform}: 시작 전")
        review(controller, A)
        for copied_flag in (True, False):
            self.assertEqual(controller.start_copied(copied_flag)[0], "state", "검토 중")
        approve(controller, A)
        self.assertEqual(controller.start_copied(False)[0], "state", "복사 준비됨에서 복사 표시를 취소할 수는 없다")
        controller.select_platform(posts.PAGES)
        self.assertEqual(controller.start_copied(True)[0], "state", "Pages 에는 이 길이 없다")
        controller.select_platform(A)
        controller.save_gate = lambda: True
        self.assertEqual(controller.start_copied(True)[0], "restoring")
        controller.save_gate = None
        self.assertEqual(controller.provider.requests[-1][0], "approve", "거절된 것은 공급자를 부르지 않았다")

    def test_a_failure_to_mark_is_a_sentence_and_the_state_is_read_again(self):
        provider = Recording("empty", fail={"mark_copied": posts.PostFailure(T["post_fail_state"], code="STATUS_TRANSITION_INVALID", kind="state")})
        controller, _ = with_post(provider=provider)
        ready(controller)
        status, end, todo = copied(controller)
        self.assertEqual((status, end, todo), ("started", "failed", {"reload": True}))
        self.assertEqual(controller.notice, ("error", T["post_fail_state"]))


class PostsRecordCoreTest(unittest.TestCase):
    def at_copied(self, **kwargs):
        controller, project_id = with_post(**kwargs)
        ready(controller)
        copied(controller)
        return controller, project_id

    def test_the_address_dialog_opens_only_when_copied_and_only_once(self):
        controller, _ = with_post()
        self.assertFalse(controller.open_record())
        ready(controller)
        self.assertFalse(controller.open_record(), "복사 준비됨에서는 열 수 없다 — 먼저 복사했어요")
        copied(controller)
        self.assertTrue(controller.open_record())
        self.assertFalse(controller.open_record(), "이미 열려 있다")
        self.assertTrue(controller.record_open)
        controller.close_record()
        self.assertFalse(controller.record_open)

    def test_it_does_not_open_while_busy_or_restoring(self):
        controller, _ = self.at_copied()
        controller.save_gate = lambda: True
        self.assertFalse(controller.open_record())
        controller.save_gate = None
        self.assertTrue(controller.open_record())

    def test_a_good_address_is_recorded_and_the_dialog_closes_and_the_state_is_published_manual(self):
        controller, _ = self.at_copied()
        controller.open_record()
        status, end, todo = drive(controller, lambda **cb: controller.start_record("  " + GOOD_URL + "  ", **cb))
        self.assertEqual((status, end, todo), ("started", "ok", {"reload_list": True}))
        self.assertEqual((controller.record_open, status_of(controller, A)), (False, st.PUBLISHED_MANUAL))
        self.assertEqual(controller.provider.requests[-1][1].url, GOOD_URL, "앞뒤 공백은 떼어 보낸다")
        self.assertEqual(controller.notice, ("ok", T["post_done_recorded"]))
        card = panel(controller)["package"]
        self.assertEqual((card["mode"], card["lines"][0], card["copy_url"]["visible"], card["copy_url"]["enabled"]), ("published", T["post_published_url"].format(url=GOOD_URL), True, True))
        self.assertEqual(controller.copy_payload("url"), (GOOD_URL, ""))
        self.assertEqual(panel(controller)["after"], T["post_review_after_done"])
        self.assertEqual((card["copied"], card["uncopy"], card["record"]), (None, None, None), "직접 발행함에는 더 누를 단추가 없다")

    def test_a_bad_address_never_reaches_the_provider_and_names_the_problem_without_echoing_it(self):
        controller, _ = self.at_copied()
        controller.open_record()
        cases = {"": "empty", "   ": "empty", "https://blog.naver.com/a b/1": "space", "https://blog.naver.com/a/" + "1" * 500: "long", f"https://blog.naver.com/a/{KEY}": "secret",
                 "http://blog.naver.com/a/1": "scheme", "blog.naver.com/a/1": "scheme", "https://example.com/a/1": "host", "https://blog.naver.com.evil.example/a/1": "host", "https://user:pw@blog.naver.com/a/1": "secret",
                 "https://blog.naver.com:8080/a/1": "host", "https://blog.naver.com/": "path", "https://blog.naver.com": "path", "https://blog.naver.com//x": "path", "https://blog.naver.com?x=1": "path"}
        before = len(controller.provider.requests)
        for url, problem in cases.items():
            with self.subTest(url=url[:30]):
                status, wanted = controller.start_record(url)
                self.assertEqual((status, wanted), ("invalid", problem))
                view = controller.record_view(len(url))
                self.assertEqual(view["problem"], T[posts_view.RECORD_PROBLEM_TEXT[problem]])
                self.assertNotIn(KEY[:10], repr(view))
        self.assertEqual(len(controller.provider.requests), before, "걸린 주소는 서비스를 부르지 않는다")
        self.assertTrue(controller.record_open)

    def test_the_screens_check_is_never_looser_than_the_services_and_accepts_the_real_shapes(self):
        accepted = ["https://blog.naver.com/exampleaaa/223000000001", "https://m.blog.naver.com/exampleaaa/223000000001", "HTTPS://Blog.Naver.Com/x/1", "https://blog.naver.com/PostView.naver?blogId=exampleaaa&logNo=223",
                    "https://blog.naver.com/x/1#c", "  https://blog.naver.com/x/1  "]
        for url in accepted:
            with self.subTest(accepted=url):
                self.assertEqual(rules.naver_url_problem(url), "")
                content_model._published_url("naver_a", url.strip())                              # 서비스도 받는다(받지 않으면 오류가 난다)
        rejected = ["", "https://blog.naver.com/", "http://blog.naver.com/x/1", "https://example.com/x/1", "https://user:pw@blog.naver.com/x/1", "blog.naver.com/x/1", "https://blog.naver.com/x /1",
                    "https://blog.naver.com:443/x/1", "ftp://blog.naver.com/x/1", "https://naver.com/x/1", "https://blog.naver.com.example.invalid/x/1", "javascript:alert(1)"]
        for url in rejected:
            with self.subTest(rejected=url):
                self.assertNotEqual(rules.naver_url_problem(url), "")
        for url in accepted + rejected:                                                            # 화면이 받는 주소는 서비스도 받는다(화면 ⊆ 서비스)
            if rules.naver_url_problem(url) == "":
                content_model._published_url("naver_a", url.strip())
        self.assertEqual(rules.NAVER_HOSTS, content_model.NAVER_HOSTS, "받는 호스트가 서비스와 같다")

    def test_a_service_refusal_keeps_the_dialog_open_with_the_reason_and_other_failures_close_it(self):
        for kind, kept in (("address", True), ("secret", True), ("other", True), ("state", False), ("notfound", False), ("stale", False)):
            with self.subTest(kind=kind):
                provider = Recording("empty", fail={"record_published": posts.PostFailure(T["post_fail_address"], code="NAVER_PUBLISH_URL_INVALID", kind=kind)})
                controller, _ = with_post(provider=provider)
                ready(controller)
                copied(controller)
                controller.open_record()
                status, end, todo = drive(controller, lambda **cb: controller.start_record(GOOD_URL, **cb))
                self.assertEqual((status, end, controller.record_open), ("started", "failed", kept))
                if kept:
                    self.assertEqual((todo, controller.record_view(5)["message"]), ({}, T["post_fail_address"]))
                else:
                    self.assertEqual(controller.notice[0], "error")

    def test_the_dialog_goes_away_with_the_post(self):
        controller, _ = self.at_copied()
        controller.open_record()
        controller.close_post()
        self.assertFalse(controller.record_open)

    def test_recording_is_refused_while_another_write_runs_or_the_state_changed_under_it(self):
        controller, _ = self.at_copied()
        controller.open_record()
        controller.detail = dataclasses.replace(controller.detail, platforms=tuple(dataclasses.replace(item, status=st.READY_TO_COPY) if item.platform == A else item for item in controller.detail.platforms))
        self.assertEqual(controller.start_record(GOOD_URL)[0], "state")


class PostsSimilarityAckCoreTest(unittest.TestCase):
    def two_blogs(self, **kwargs):
        controller, project_id = with_post(**kwargs)
        ready(controller, A)
        review(controller, B)
        return controller, project_id

    def test_when_only_the_similarity_blocks_the_normal_approval_is_off_and_the_strong_one_is_on(self):
        controller, _ = self.two_blogs()
        self.assertEqual(controller.approval(), (False, "post_approve_why_blocked"))
        self.assertEqual(controller.similarity_approval(), (True, ""))
        current = panel(controller)
        self.assertEqual((current["approve"]["enabled"], current["approve_similarity"]["visible"], current["approve_similarity"]["enabled"]), (False, True, True))
        self.assertEqual(current["approve_similarity"]["text"], T["post_sim_button"])
        self.assertEqual(current["approve_similarity"]["note"], T["post_sim_note"])
        self.assertEqual([button for button in ("review", "approve", "revoke") if current[button].get("primary")], ["review"], "주요 단추는 하나다")
        self.assertIsNone(controller.approve_dialog(), "일반 확인창은 뜨지 않는다")

    def test_the_strong_dialog_is_stronger_than_the_normal_one_and_starts_nothing_until_it_was_shown(self):
        controller, _ = self.two_blogs()
        self.assertEqual(controller.start_approve(similarity=True)[0], "unconfirmed", "확인창을 보이지 않고 시작하는 길은 없다")
        dialog = controller.similarity_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), (T["post_sim_title"], T["post_sim_ok"], T["post_sim_cancel"]))
        self.assertIn("100%", dialog["body"])
        self.assertIn("중복 글로 취급될 수 있어요", dialog["body"])
        self.assertEqual(controller.approve_asked, (controller.open_id, B, 1, "similarity"))
        self.assertEqual(controller.start_approve()[0], "refused", "일반 승인은 이 확인창으로 시작하지 않는다")

    def test_the_request_carries_the_acknowledgement_only_on_this_road(self):
        controller, _ = self.two_blogs()
        controller.similarity_dialog()
        status, end, _todo = drive(controller, lambda **cb: controller.start_approve(similarity=True, **cb))
        self.assertEqual((status, end, status_of(controller, B)), ("started", "ok", st.READY_TO_COPY))
        name, request = controller.provider.requests[-1]
        self.assertEqual((name, request.similarity_ack), ("approve", True))
        self.assertEqual(controller.notice, ("ok", T["post_done_approved_similarity"]))
        earlier = [request.similarity_ack for name, request in controller.provider.requests if name == "approve"]
        self.assertEqual(earlier, [False, True], "처음 일반 승인(블로그 A)은 거짓이었다")

    def test_a_normal_approval_is_always_without_the_acknowledgement(self):
        controller, _ = with_post()
        ready(controller, A)
        self.assertFalse(controller.provider.requests[-1][1].similarity_ack)
        self.assertIsNone(controller.review.pages)

    def test_it_is_not_offered_when_anything_else_blocks(self):
        controller, _ = with_post(markdown=post_fake.sample_text() + chr(10) * 2 + STOP_SENTENCE)
        review(controller, A)
        review(controller, B)
        self.assertEqual(rules.review_blocks(controller.review), ("health", "similarity"))
        self.assertEqual(controller.similarity_approval(), (False, "post_approve_why_blocked"), "다른 막힘이 있으면 유사도만 알고 승인할 수 없다")
        self.assertFalse(panel(controller)["approve_similarity"]["visible"])
        self.assertIsNone(controller.similarity_dialog())

    def test_it_is_not_offered_for_an_old_result_a_missing_result_or_a_pages_post(self):
        clean, _ = self.two_blogs()
        self.assertTrue(clean.similarity_approval()[0])
        clean.review = dataclasses.replace(clean.review, revision=clean.review.revision + 1)
        self.assertEqual(clean.similarity_approval(), (False, "post_approve_why_stale"))
        clean.review = None
        self.assertEqual(clean.similarity_approval(), (False, "post_res_lost"))
        clean.select_platform(posts.PAGES)
        self.assertEqual(clean.similarity_approval(), (False, "post_approve_why_state"))
        self.assertFalse(panel(clean)["approve_similarity"]["visible"])

    def test_busy_or_restoring_turns_the_strong_road_off(self):
        controller, _ = self.two_blogs()
        controller.save_gate = lambda: True
        self.assertEqual(controller.similarity_approval(), (False, "post_approve_why_restoring"))
        self.assertIsNone(controller.similarity_dialog())
        self.assertEqual(controller.start_approve(similarity=True)[0], "restoring")

    def test_cancelling_the_strong_dialog_takes_the_mark_back(self):
        controller, _ = self.two_blogs()
        controller.similarity_dialog()
        controller.discard_approve()
        self.assertEqual(controller.start_approve(similarity=True)[0], "unconfirmed")

    def test_the_fake_provider_itself_still_refuses_the_similar_post_without_the_acknowledgement(self):
        controller, project_id = self.two_blogs()
        with self.assertRaises(posts.PostFailure) as raised:
            controller.provider.approve_post(posts.ApproveRequest(project_id, B, 1), SAFE, NEVER)
        self.assertEqual((raised.exception.kind, status_of(controller, B)), ("similarity", st.REVIEW_REQUIRED))
        outcome = controller.provider.approve_post(posts.ApproveRequest(project_id, B, 1, True), SAFE, NEVER)
        self.assertEqual(outcome.detail.platform(B).status, st.READY_TO_COPY)


class PostsHealthExtraCoreTest(unittest.TestCase):
    def test_a_stop_sentence_in_the_description_or_a_tag_stops_the_review_like_one_in_the_body(self):
        values = posts.PagesValues("생활", "ko", "https://img.example.invalid/a.jpg", ("에너지", STOP_SENTENCE), STOP_SENTENCE)
        self.assertEqual(rules.pages_health_extra(None), ())
        found = rules.health_of("제목", "오늘은 산책을 했어요.", rules.pages_health_extra(values))
        self.assertEqual(found.stage, "stop")
        self.assertEqual(sorted(place.split(" — ")[0] for place in found.places), sorted([T["post_where_description"], T["post_where_tags"]]))
        self.assertEqual(rules.health_of("제목", "오늘은 산책을 했어요.").stage, "general")
        self.assertEqual(rules.text_blocks("제목", "오늘은 산책을 했어요.", (), (), rules.pages_health_extra(values)), ("health",))
        self.assertEqual(rules.text_blocks("제목", "오늘은 산책을 했어요."), ())

    def test_each_of_the_two_fields_alone_is_enough(self):
        for values in (posts.PagesValues("생활", "ko", "https://i.example.invalid/a.jpg", (), STOP_SENTENCE), posts.PagesValues("생활", "ko", "https://i.example.invalid/a.jpg", (STOP_SENTENCE,), "")):
            with self.subTest(values=repr(values)[:40]):
                self.assertEqual(rules.health_of("제목", "산책 글.", rules.pages_health_extra(values)).stage, "stop")

    def test_a_calm_description_and_tags_change_nothing(self):
        values = posts.PagesValues("생활", "ko", "https://i.example.invalid/a.jpg", ("에너지", "습관"), "오늘의 산책을 기록했어요.")
        self.assertEqual(rules.health_of("제목", "산책 글.", rules.pages_health_extra(values)).stage, "general")

    def test_the_review_report_keeps_the_values_the_review_used_and_the_approval_request_carries_them(self):
        controller, _ = with_post()
        raw = dict(RAW, description="오늘의 산책을 기록했어요.")
        self.assertEqual(drive(controller, lambda **cb: controller.start_review(posts.PAGES, raw, **cb))[1], "ok")
        report = controller.review
        self.assertEqual((report.pages.category, report.pages.description, report.pages.tags), ("생활", "오늘의 산책을 기록했어요.", ("에너지", "습관")))
        controller.select_platform(posts.PAGES)
        controller.approve_dialog()
        drive(controller, lambda **cb: controller.start_approve(**cb))
        request = [item for name, item in controller.provider.requests if name == "approve"][-1]
        self.assertEqual(request.pages, report.pages, "검토가 쓴 값이 승인 요청에 함께 간다")

    def test_a_stop_description_blocks_the_approval_through_the_review_result(self):
        controller, _ = with_post()
        status, end, _todo = drive(controller, lambda **cb: controller.start_review(posts.PAGES, dict(RAW, description=STOP_SENTENCE), **cb))
        self.assertEqual((status, end), ("started", "ok"))
        self.assertEqual(controller.review.health.stage, "stop")
        self.assertEqual(controller.approval(), (False, "post_approve_why_blocked"))
        sections = {item["key"]: item for item in panel(controller)["result"]["sections"]}
        self.assertEqual(sections["health"]["badge"]["text"], T["post_badge_block"])
        self.assertTrue(any(T["post_where_description"] in line for line in sections["health"]["lines"]))


class PostsHistoryCoreTest(unittest.TestCase):
    def make(self, scenario="normal", **kwargs):
        provider = Recording(scenario, **kwargs)
        controller = post_history_view.HistoryController(provider, jobs.JobRunner())
        return controller, provider

    def load(self, controller):
        results = {}
        job = controller.start_load(on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
        job.join(10)
        if "ok" in results:
            controller.apply_loaded(results["ok"])
        else:
            controller.apply_load_failed(results["failed"])
        return controller.view()

    def test_the_rows_start_oldest_first_and_the_button_switches_to_newest_first(self):
        controller, _ = self.make()
        view = self.load(controller)
        titles = [row["title"] for row in view["list"]["rows"]]
        self.assertEqual(len(titles), 3)
        self.assertEqual((view["order"]["now"], view["order"]["text"]), (T["hist_order_now_oldest"], T["hist_order_to_newest"]))
        self.assertTrue(controller.toggle_order())
        newest = [row["title"] for row in controller.view()["list"]["rows"]]
        self.assertEqual(newest, list(reversed(titles)))
        self.assertEqual((controller.view()["order"]["now"], controller.view()["order"]["text"]), (T["hist_order_now_newest"], T["hist_order_to_oldest"]))
        self.assertFalse(controller.set_order("random"))

    def test_the_sort_is_by_time_then_post_and_platform_and_empty_times_come_first(self):
        rows = [post_history.HistoryEntry("b", "", "naver_a", st.READY_TO_COPY, 1, "2026-11-02T00:00:00Z"), post_history.HistoryEntry("a", "", "naver_b", st.READY_TO_COPY, 1, "2026-11-02T00:00:00Z"),
                post_history.HistoryEntry("a", "", "naver_a", st.READY_TO_COPY, 1, "2026-11-02T00:00:00Z"), post_history.HistoryEntry("z", "", "naver_a", st.READY_TO_COPY, 1, ""),
                post_history.HistoryEntry("c", "", "naver_a", st.PUBLISHED_MANUAL, 1, "2026-11-30T00:00:00Z", "https://blog.naver.com/x/1", "2026-11-01T00:00:00Z")]
        self.assertEqual([(row.project_id, row.platform) for row in post_history.sort_rows(rows)], [("z", "naver_a"), ("c", "naver_a"), ("a", "naver_a"), ("a", "naver_b"), ("b", "naver_a")])
        self.assertEqual([(row.project_id, row.platform) for row in post_history.sort_rows(rows, "newest")], list(reversed([(row.project_id, row.platform) for row in post_history.sort_rows(rows)])))
        self.assertEqual(post_history.sort_rows(rows, "nonsense"), post_history.sort_rows(rows))

    def test_a_row_says_platform_state_time_and_a_masked_address_with_a_copy_button(self):
        controller, _ = self.make()
        rows = {row["key"]: row for row in self.load(controller)["list"]["rows"]}
        published = rows["exh00001:naver_a"]
        self.assertEqual(published["meta"], T["hist_row_meta"].format(platform="네이버 A", status="직접 발행함", when="2026-10-21 12:20"))
        self.assertEqual(published["url"], T["hist_row_url"].format(url="https://blog.naver.com/exampleid/100000000001"))
        self.assertTrue(published["copy"]["enabled"] and published["copy"]["a11y"])
        self.assertIsNone(rows["exh00002:naver_b"]["copy"], "주소가 없는 줄에는 복사 단추가 없다")
        self.assertEqual(controller.copy_payload("exh00001:naver_a"), ("https://blog.naver.com/exampleid/100000000001", ""))
        self.assertEqual(controller.copy_payload("exh00002:naver_b"), (None, "hist_copy_none"))
        self.assertEqual(controller.copy_payload("없는 열쇠"), (None, "hist_copy_none"))

    def test_a_key_shaped_address_is_hidden_in_the_row_and_never_copied(self):
        controller, _ = self.make("empty", history_examples=False)
        loud = post_history.HistoryEntry("p1", "제목", "naver_a", st.PUBLISHED_MANUAL, 1, "2026-11-02T00:00:00Z", f"https://blog.naver.com/x/1?token={KEY}", "2026-11-03T00:00:00Z")
        controller.apply_loaded(post_history.HistoryData((loud,), 0, "ok", False, False))
        view = controller.view()
        row = view["list"]["rows"][0]
        self.assertNotIn(KEY[:10], repr(view))
        self.assertFalse(row["copy"]["enabled"])
        self.assertEqual(controller.copy_payload("p1:naver_a"), (None, "hist_copy_blocked"))

    def test_the_six_states(self):
        controller, _ = self.make("normal")
        self.assertEqual(controller.view()["state"], "loading")
        self.assertEqual(self.load(controller)["state"], "normal")
        empty, _ = self.make("empty")
        self.assertEqual((self.load(empty)["state"], self.load(empty)["list"]["empty"]["title"]), ("empty", T["hist_empty_title"]))
        error, _ = self.make("error")
        view = self.load(error)
        self.assertEqual((view["state"], view["error"]["title"], view["error"]["button"]), ("error", T["hist_error_title"], T["hist_retry"]))
        partial, _ = self.make("partial")
        view = self.load(partial)
        self.assertEqual((view["state"], view["banner"]), ("partial", ("alert", T["hist_partial"].format(n=1))))
        offline, _ = self.make("offline")
        view = self.load(offline)
        self.assertEqual((view["state"], view["banner"]), ("offline", ("cloud_off", T["hist_offline"])))
        self.assertTrue(view["sample"])

    def test_a_state_the_table_does_not_know_is_shown_as_unknown_and_nothing_crashes(self):
        controller, _ = self.make("empty", history_examples=False)
        odd = post_history.HistoryEntry("p1", "새 상태 글", "github_pages", "MERGE_PENDING", 1, "2026-11-02T00:00:00Z")
        other = post_history.HistoryEntry("p2", "새 갈래 글", "somewhere_else", st.APPROVED, 1, "2026-11-03T00:00:00Z")
        controller.apply_loaded(post_history.HistoryData((odd, other), 0, "ok", False, False))
        rows = {row["key"]: row for row in controller.view()["list"]["rows"]}
        self.assertEqual(rows["p1:github_pages"]["meta"], T["hist_row_meta"].format(platform="GitHub Pages", status=T["post_status_unknown"], when="2026-11-02 09:00"))
        self.assertIn(T["hist_platform_unknown"], rows["p2:somewhere_else"]["meta"])

    def test_more_rows_than_a_page_are_cut_and_more_shows_the_rest(self):
        controller, _ = self.make("empty", history_examples=False)
        many = tuple(post_history.HistoryEntry(f"p{number:03d}", f"글 {number}", "naver_a", st.READY_TO_COPY, 1, f"2026-11-{number % 28 + 1:02d}T00:00:00Z") for number in range(120))
        controller.apply_loaded(post_history.HistoryData(many, 0, "ok", False, False))
        view = controller.view()
        self.assertEqual((len(view["list"]["rows"]), view["list"]["more"]["text"], view["list"]["count"]), (rules.PAGE, T["hist_more"], T["hist_count"].format(n=120)))
        controller.show_more()
        self.assertEqual(len(controller.view()["list"]["rows"]), 2 * rules.PAGE)
        controller.toggle_order()
        self.assertEqual(len(controller.view()["list"]["rows"]), rules.PAGE, "순서를 바꾸면 다시 첫 쪽부터")

    def test_published_entries_follow_the_posts_through_the_flow_with_the_fake(self):
        controller, project_id = with_post()
        ready(controller)
        copied(controller)
        controller.open_record()
        drive(controller, lambda **cb: controller.start_record(GOOD_URL, **cb))
        history = post_history_view.HistoryController(controller.provider, jobs.JobRunner())
        view = self.load(history)
        self.assertEqual([row["key"] for row in view["list"]["rows"]], [f"{project_id}:{A}"])
        self.assertEqual(view["list"]["rows"][0]["url"], T["hist_row_url"].format(url=GOOD_URL))
        self.assertIn("직접 발행함", view["list"]["rows"][0]["meta"])
        self.assertTrue(view["sample"])

    def test_in_review_posts_are_not_in_the_history_but_approved_ones_are(self):
        controller, project_id = with_post()
        review(controller, A)
        history = post_history_view.HistoryController(controller.provider, jobs.JobRunner())
        self.assertEqual([row for row in self.load(history)["list"]["rows"] if row["key"].startswith(project_id)], [])
        approve(controller, A)
        self.assertEqual(len([row for row in self.load(history)["list"]["rows"] if row["key"].startswith(project_id)]), 1)
        self.assertEqual(post_history.BEFORE_REVIEWED, service_history.BEFORE_REVIEWED, "서비스와 같은 '검토 전' 목록이다")


class PostsWorkLogCoreTest(unittest.TestCase):
    def make(self, **kwargs):
        provider = Recording("normal", **kwargs)
        return post_history_view.HistoryController(provider, jobs.JobRunner()), provider

    def read_log(self, controller):
        results = {}
        job = controller.start_log(on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
        job.join(10)
        if "ok" in results:
            controller.apply_log(results["ok"])
        else:
            controller.apply_log_failed(results["failed"])
        return controller.view()["log"]

    def test_the_log_card_is_closed_until_opened_and_reads_only_when_opened(self):
        controller, provider = self.make()
        self.assertEqual((controller.view()["log"]["state"], controller.view()["log"]["lines"]), ("closed", []))
        self.assertEqual(controller.view()["log"]["toggle"]["text"], T["hist_log_show"])
        self.assertNotIn("load_work_log", provider.calls)
        self.assertTrue(controller.set_log_open(True), "처음 펼치면 읽어야 한다")
        log = self.read_log(controller)
        self.assertEqual((log["state"], len(log["lines"]), log["toggle"]["text"]), ("normal", 3, T["hist_log_hide"]))
        self.assertFalse(controller.set_log_open(False))
        self.assertFalse(controller.set_log_open(True), "이미 읽은 로그는 다시 펼쳐도 다시 읽지 않는다")
        self.assertEqual(provider.calls.count("load_work_log"), 1)

    def test_a_line_says_time_source_name_and_places_newest_first(self):
        controller, _ = self.make()
        controller.set_log_open(True)
        lines = self.read_log(controller)["lines"]
        self.assertEqual(lines[0], T["hist_log_line"].format(when="2026-11-23 08:59:59", source=T["hist_log_source_qt"], name="QtCriticalMsg", places="qt.qpa.example < example.cpp:7"))
        self.assertIn("화면 반응", lines[2])
        self.assertIn("KeyError", lines[2])

    def test_the_card_has_no_button_that_changes_or_copies_the_log(self):
        controller, _ = self.make()
        controller.set_log_open(True)
        log = self.read_log(controller)
        self.assertEqual(sorted(key for key, value in log.items() if isinstance(value, dict) and "text" in value), ["retry", "toggle"])
        self.assertEqual(log["retry"]["text"], T["hist_log_retry"])
        for word in ("지우기", "내보내기", "복사", "저장"):
            self.assertNotIn(word, repr(log))

    def test_even_if_a_key_shaped_line_came_through_the_screen_hides_it_all_the_way(self):
        controller, _ = self.make()
        loud = post_history.LogEntry("2026-11-24T05:30:12Z", "slot", KEY, ("shell.py:2",))
        controller.set_log_open(True)
        controller.apply_log(post_history.WorkLogData((loud,), 1, 0, 0, False))
        view = controller.view()
        blob = repr(view)
        for start in range(0, len(KEY) - 5, 3):
            self.assertNotIn(KEY[start:start + 6], blob, "연속 6글자 조각도 화면 글에 없다")
        self.assertEqual(len(view["log"]["lines"]), 1)

    def test_the_counts_and_the_empty_and_error_states(self):
        controller, _ = self.make()
        controller.set_log_open(True)
        controller.apply_log(post_history.WorkLogData((), 0, 0, 0, False))
        self.assertEqual((controller.view()["log"]["state"], controller.view()["log"]["empty"]), ("empty", T["hist_log_empty"]))
        controller.apply_log(post_history.WorkLogData((post_history.LogEntry("2026-11-24T05:30:12Z", "main", "Error1", ()),), 1, 2, 5, False))
        log = controller.view()["log"]
        self.assertEqual(log["notes"], [T["hist_log_count"].format(n=1), T["hist_log_skipped"].format(n=2), T["hist_log_older"].format(n=5)])
        self.assertIn(T["hist_log_places_none"], log["lines"][0])
        failing, _ = self.make(fail={"load_work_log": posts.PostFailure(T["post_fail_read"], code="FILE_IN_USE", kind="io")})
        failing.set_log_open(True)
        log = self.read_log(failing)
        self.assertEqual((log["state"], log["error"]["text"], log["retry"]["enabled"]), ("error", T["hist_log_error"], True))
        self.assertTrue(failing.set_log_open(True), "읽기가 실패했으면 다시 펼칠 때 다시 읽는다")

    def test_an_unknown_source_is_named_as_unknown(self):
        controller, _ = self.make()
        controller.set_log_open(True)
        controller.apply_log(post_history.WorkLogData((post_history.LogEntry("2026-11-24T05:30:12Z", "elsewhere", "Error1", ("a.py:1",)),), 1, 0, 0, False))
        self.assertIn(T["hist_log_source_unknown"], controller.view()["log"]["lines"][0])
        self.assertEqual(set(post_history.LOG_SOURCES), set(service_worklog.SOURCES))


class PostsTextAndSourceRules1bTest(unittest.TestCase):
    NEW_KEYS = sorted(post_history_text.HIST_T)

    def test_the_history_texts_are_merged_and_follow_the_same_wording_rules_as_the_posts_texts(self):
        for key, value in post_history_text.HIST_T.items():
            with self.subTest(key=key):
                self.assertIs(text.T[key], value)
                for word in text.FORBIDDEN:
                    self.assertNotIn(word, value)
                self.assertNotRegex(value, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
                self.assertNotRegex(value, r"Traceback|Exception|Error\b|테마|다크|Dark|어두운")
                for banned in (chr(0x7E), "://", "{{"):
                    self.assertNotIn(banned, value)

    def test_every_history_text_is_used_somewhere_in_the_sources(self):
        used = "\n".join(path.read_text(encoding="utf-8") for path in UI_DIR.rglob("*.py") if path.name != "post_history_text.py")
        for key in self.NEW_KEYS:
            self.assertRegex(used, rf'["\']{key}["\']', f"죽은 글: {key}")

    def test_the_menu_label_and_the_screen_title_are_the_same_words(self):
        self.assertEqual(T["nav_history"], T["hist_title"])

    def test_the_new_files_are_covered_by_the_screen_layer_source_rules_because_their_names_start_with_post(self):
        core = {path.name for path in (UI_DIR / "core").glob("post*.py")}
        self.assertTrue({"post_history.py", "post_history_view.py", "post_history_text.py"} <= core)

    def test_the_text_keys_the_controller_can_return_all_exist(self):
        for key in ("post_pkg_copy_none", "post_pkg_copy_blocked", "hist_copy_none", "hist_copy_blocked"):
            self.assertIn(key, text.T)
        for key in posts_view.RECORD_PROBLEM_TEXT.values():
            self.assertIn(key, text.T)
        for kind in posts_view.COPY_KINDS:
            for key in posts_view.COPY_TEXT[kind]:
                self.assertIn(key, text.T)

    def test_the_sentences_do_not_contain_a_web_address_a_tilde_or_a_secret_shape(self):
        for key, value in list(text.T.items()):
            if key.startswith(("post_pkg_", "post_rec_", "post_sim_", "post_published_", "post_copied", "post_uncopy", "post_record", "hist_")):
                self.assertFalse(re.search(r"https?://", value), key)


if __name__ == "__main__":
    unittest.main()
