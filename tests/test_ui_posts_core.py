"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)의 순수 부분 시험(PySide6 없이 돈다 — CI 와 같은 조건) — 미리보기·검토 규칙·승인 조건·상태·가져오기·검토·승인 흐름·실패·동시성·문구·소스 규칙.

지키는 것:
  1) 미리보기는 글자만 그리고(글 속 HTML·스크립트는 글자 그대로) 키·토큰 모양은 가린 뒤에 나가며 긴 글은 앞부분만 담는다(M07).
  2) 검토 결과는 발행 전 검사·건강 효과 단정·비밀 모양 세 층이고, **승인은 이 앱을 연 뒤 이 글·이 플랫폼·이 판의 검토 결과를 받았고 막힘이 없고 확인창을 거쳤을 때만** 시작한다(M09·M10·M11·M12). 승인 취소는 검토 중으로 되돌린다(M13).
  3) 가져오기는 실패해도 입력이 남고(칸의 글은 위젯에만 있다), 쓰기는 한 번에 하나이고 복원이 도는 동안 시작하지 않는다.
  4) 상태 글·플랫폼 이름·검사 코드 문장은 서비스와 같고, 문구에 영문 코드·결과 약속 표현이 없다. 화면 층 소스에는 파일 쓰기·네트워크·하위 프로세스가 없다.
가짜 비밀은 조립한 문자열(`CANARY_` 또는 키 모양을 쪼개 이어 붙임)이고 실제 글·블로그 이름은 어디에도 없다.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.service import format as service_format  # noqa: E402
from chanceblog_desktop.service import previews, review  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs, post_fake, post_rules as rules, post_text, posts, posts_view, text  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
KEY = ss.KEY                                                                 # 구글 API 키 모양의 가짜 값(조립한 문자열)
RAW = {"category": "생활", "lang": "ko", "image_url": "https://img.example.invalid/a.jpg", "tags": "에너지, 습관", "description": ""}


def make(scenario="normal", **kwargs):
    provider = post_fake.FakePostsProvider(scenario, **kwargs)
    controller = posts_view.PostsController(provider, jobs.JobRunner())
    controller.apply_loaded(provider.load_posts(SAFE, NEVER))
    return controller


def drive(controller, starter):
    """일을 시작하고 끝까지 기다려 결과를 받는다(셸이 하는 일과 같다) → (시작 상태, 끝난 일: 'ok'·'failed'·None, 셸이 할 일)."""
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
    if "ok" in results:
        controller.apply_detail(results["ok"])
        return "ok"
    return controller.apply_detail_failed(results["failed"])


def review_pages(controller, raw=None):
    return drive(controller, lambda **cb: controller.start_review(posts.PAGES, dict(raw or RAW), **cb))


def approve(controller):
    controller.approve_dialog()
    return drive(controller, lambda **cb: controller.start_approve(**cb))


def long_post(provider, title="긴 글"):
    return provider.add_post(title, post_fake.sample_text())


def row_ids(controller):
    return [row.project_id for row in controller.data.rows]


class PostsRulesTest(unittest.TestCase):
    def test_the_preview_splits_blocks_by_kind_and_keeps_script_text_literal(self):
        found = rules.build_preview("## 소제목\n\n보통 문단이에요.\n\n- 항목 하나\n- 항목 둘\n\n> 인용 글\n\n<script>alert(1)</script>")
        self.assertEqual([block.kind for block in found.blocks], ["heading", "paragraph", "list", "quote", "paragraph"])
        self.assertEqual(found.blocks[2].text, "- 항목 하나\n- 항목 둘")
        self.assertEqual(found.blocks[3].text, "인용 글", "인용의 `> ` 기호는 떼고 글만 둔다")
        self.assertEqual(found.blocks[4].text, "<script>alert(1)</script>", "글 속 스크립트는 해석하지 않고 글자 그대로다")
        self.assertEqual((found.total, found.cut, found.images), (5, False, 0))

    def test_the_preview_masks_key_shapes_in_paragraphs_and_in_code_blocks(self):
        pem = "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END " + "PRIVATE KEY-----"
        found = rules.build_preview(f"앞 문단 {KEY} 뒤 문단\n\n```\n{pem}\n```\n\n- 목록에 {KEY} 도")
        joined = "\n".join(block.text for block in found.blocks)
        self.assertNotIn(KEY, joined)
        self.assertNotIn("MIIEvQ", joined, "여러 줄에 걸친 개인 키 블록도 가려서 나간다")
        for piece in (KEY[:12], KEY[-12:]):
            self.assertNotIn(piece, joined, "키의 조각도 남지 않는다")
        self.assertIn("가림", joined)

    def test_the_preview_caps_the_blocks_and_the_block_length_and_says_it_is_cut(self):
        found = rules.build_preview("\n\n".join(f"문단 {number} 입니다." for number in range(200)))
        self.assertEqual((len(found.blocks), found.total, found.cut), (rules.PREVIEW_BLOCKS, 200, True))
        self.assertEqual(found.shown, rules.PREVIEW_BLOCKS)
        long_block = rules.build_preview("가" * 5000)
        self.assertLessEqual(len(long_block.blocks[0].text), rules.BLOCK_LIMIT)
        self.assertTrue(long_block.blocks[0].text.endswith("…"))
        many = rules.build_preview("\n\n".join("나" * 2500 for _ in range(30)))
        self.assertLessEqual(sum(len(block.text) for block in many.blocks), rules.PREVIEW_CHARS + 2500, "합쳐 글자 상한 근처에서 멈춘다")
        self.assertTrue(many.cut)

    def test_the_preview_never_raises_on_odd_input(self):
        for value in (None, "", "   \n  ", 12345, b"bytes", "\x00\x01 널 글자", "<<<>>>", "```\n닫지 않은 코드", "\u202e뒤집힌 글\u202c", "가\u200b나\u200d다", "😀" * 500, "#" * 400, "[a](" * 2000, "&" * 3000):
            with self.subTest(value=repr(value)[:30]):
                found = rules.build_preview(value)
                self.assertIsInstance(found, posts.PostPreview)
                for block in found.blocks:
                    self.assertIn(block.kind, ("heading", "paragraph", "list", "quote"))
        self.assertEqual(rules.build_preview("").blocks, ())
        self.assertEqual(rules.build_preview(None).total, 0)

    def test_the_preview_draws_neither_images_nor_links_and_counts_the_image_spots(self):
        found = rules.build_preview("앞 글 ![설명](https://img.example.invalid/a.png) 뒤 글\n\n[링크 글자](https://example.invalid/page) 입니다.", assets=2, refs=3)
        joined = "\n".join(block.text for block in found.blocks)
        self.assertNotIn("img.example.invalid", joined)
        self.assertNotIn("example.invalid/page", joined)
        self.assertIn("링크 글자", joined)
        self.assertEqual((found.images, found.refs), (1 + 2, 3))

    def test_the_preview_counts_text_without_markup_or_spaces(self):
        self.assertEqual(rules.build_preview("## 가나다\n\n라 마 바").chars, len("가나다") + len("라마바"))

    def test_the_title_is_masked_then_cut(self):
        shown = rules.shown(KEY + "가" * 500, 40)
        self.assertNotIn(KEY[:10], shown)
        self.assertLessEqual(len(shown), 40)

    def test_secret_spots_say_where_and_what_but_never_the_text(self):
        found = rules.secret_spots("제목", f"첫 줄\n둘째 {KEY} 줄", ("https://example.invalid/a",))
        self.assertEqual(found, ((T["drf_where_body"], 2, "Google API 키"),))
        self.assertNotIn(KEY, repr(found))
        self.assertEqual(rules.secret_spots("제목", "깨끗한 글"), ())
        self.assertEqual(rules.secret_spots(KEY, "")[0][0], T["drf_where_title"])
        self.assertEqual(rules.secret_spots(None, None), ())

    def test_health_review_uses_the_draft_screen_judge_sentence_by_sentence(self):
        stop = rules.health_of("제목", "이 영양제를 먹으면 통증이 완전히 사라집니다.")
        self.assertEqual(stop.stage, "stop")
        self.assertTrue(stop.places and stop.places[0].startswith(T["drf_where_body"]), "걸린 문장의 앞부분과 칸 이름만 있다")
        self.assertEqual(rules.health_of("오늘의 산책", "오늘은 산책을 했어요.").stage, "general")
        far = rules.health_of("제목", "피로가 쌓였어요. " + "가나다라 " * 400 + "영양제를 샀어요.")
        self.assertNotEqual(far.stage, "stop", "서로 먼 문장의 낱말이 섞여 정상 글이 막히지 않는다")
        self.assertEqual(rules.health_of(None, None).stage, "general")

    def test_every_gate_code_the_service_can_say_has_an_easy_sentence(self):
        source = (ROOT / "src" / "chanceblog_desktop" / "service" / "gate.py").read_text(encoding="utf-8")
        codes = set(re.findall(r"\[([A-Z][A-Z_]{2,})\]", source)) - {"CODE"}
        self.assertTrue({"RAW_HTML", "LIQUID", "KRAMDOWN", "UNSAFE_URL", "AD_SCRIPT", "INVISIBLE", "HEADER_VALUE", "HEADER", "BODY", "LEN_BODY", "LOCAL_PATH"} <= codes)
        for code in sorted(codes | {"LEN_SHORT", "LEN_LONG", "LANG", "LABELS", "LEAK", "SECRET_SHAPE_FOUND"}):
            with self.subTest(code=code):
                self.assertNotEqual(rules.gate_sentence(code), T["post_gate_other"], code)
        self.assertEqual(rules.gate_sentence("NEW_UNKNOWN"), T["post_gate_other"])
        for odd in ("", "lower", "A B", "A;B", None, 7, "../x", "X" * 100):
            self.assertEqual(rules.gate_sentence(odd), T["post_gate_other"], repr(odd))

    def test_codes_are_read_from_the_service_reason_lines_in_first_seen_order(self):
        self.assertEqual(rules.unique_codes(["[LEN_BODY] a", "[RAW_HTML] b", "[LEN_BODY] c", "코드 없는 줄", "[소문자] d", 5]), ("LEN_BODY", "RAW_HTML"))
        self.assertEqual(rules.code_of("[LEN_BODY] 본문"), "LEN_BODY")
        self.assertEqual(rules.code_of("LEN_BODY"), "")

    def test_the_fake_gate_says_the_same_codes_as_the_real_gate_for_the_cases_it_knows(self):
        import tempfile
        from chanceblog_desktop.service import projects
        NL, BS = chr(10), chr(92)
        cases = ((ss.ko_text(), "ko"), ("## 짧음" + NL * 2 + "짧아요.", "ko"), (ss.ko_text() + NL * 2 + "<div>태그</div>", "ko"), (ss.ko_text() + NL * 2 + "C:" + BS + "Users" + BS + "someone" + BS + "a.txt", "ko"))
        for markdown, lang in cases:
            with tempfile.TemporaryDirectory() as tmp:
                ctx = ss.make_ctx(tmp, repo="")
                view = projects.new_project(ctx, "시험 글", markdown)
                result = review.request_review(ctx, view.project_id, "github_pages", pages=previews.PagesParams("생활", lang, "https://img.example.invalid/a.jpg", ()))
                real = set(result.pages.gates.codes())
            fake = set(rules.unique_codes(post_fake.fake_gates(markdown, lang)[0]))
            with self.subTest(markdown=markdown[:12], fake=sorted(fake), real=sorted(real)):
                self.assertLessEqual(fake, real, "가짜 관문이 말하는 코드는 실제 관문도 말한다")
                self.assertEqual(bool(fake), bool(real), "통과·막힘이 같다")

    def test_the_approval_conditions_are_all_in_one_place(self):
        provider = post_fake.FakePostsProvider()
        project_id = long_post(provider)
        detail = provider.load_post(project_id, SAFE, NEVER)
        out = provider.review_post(posts.ReviewRequest(project_id, posts.PAGES, rules.pages_values_of(RAW)), SAFE, NEVER)
        reviewed = out.detail
        fresh = out.review
        self.assertEqual(rules.approval_state(fresh, reviewed, posts.PAGES), (True, ""))
        self.assertEqual(rules.approval_state(fresh, reviewed, posts.PAGES, restoring=True), (False, "post_approve_why_restoring"))
        self.assertEqual(rules.approval_state(fresh, reviewed, posts.PAGES, busy=True), (False, "post_approve_why_busy"))
        self.assertEqual(rules.approval_state(None, reviewed, posts.PAGES), (False, "post_res_lost"), "이 앱을 연 뒤 받은 결과가 없으면 승인하지 않는다")
        self.assertEqual(rules.approval_state(fresh, detail, posts.PAGES), (False, "post_approve_why_none"), "검토 전(글 만듦·시작 전)에는 먼저 검토하라고 말한다")
        other = posts.ReviewReport("다른글", posts.PAGES, reviewed.revision, st.REVIEW_REQUIRED, True, health=fresh.health)
        self.assertEqual(rules.approval_state(other, reviewed, posts.PAGES), (False, "post_res_lost"), "다른 글의 결과로는 승인하지 않는다")
        wrong_platform = posts.ReviewReport(project_id, posts.NAVER_A, reviewed.revision, st.REVIEW_REQUIRED, True, health=fresh.health)
        self.assertEqual(rules.approval_state(wrong_platform, reviewed, posts.PAGES), (False, "post_res_lost"), "다른 플랫폼의 결과로는 승인하지 않는다")
        old = posts.ReviewReport(project_id, posts.PAGES, reviewed.revision - 1 or 99, st.REVIEW_REQUIRED, True, health=fresh.health)
        self.assertEqual(rules.approval_state(old, reviewed, posts.PAGES), (False, "post_approve_why_stale"), "옛 판의 결과로는 승인하지 않는다")
        self.assertEqual(rules.approval_state(fresh, None, posts.PAGES), (False, "post_approve_why_none"))

    def test_an_approved_or_published_state_is_not_approvable_again(self):
        provider = post_fake.FakePostsProvider()
        project_id = long_post(provider)
        provider.review_post(posts.ReviewRequest(project_id, posts.PAGES, rules.pages_values_of(RAW)), SAFE, NEVER)
        out = provider.approve_post(posts.ApproveRequest(project_id, posts.PAGES, 1), SAFE, NEVER)
        report = posts.ReviewReport(project_id, posts.PAGES, out.detail.revision, st.APPROVED, True, health=rules.health_of("a", "b"))
        self.assertEqual(rules.approval_state(report, out.detail, posts.PAGES), (False, "post_approve_why_state"))

    def test_the_blocks_of_a_review_each_have_one_reason_and_an_incomplete_review_is_not_trusted(self):
        general, stop = rules.health_of("a", "오늘은 산책을 했어요."), rules.health_of("a", "이 영양제를 먹으면 통증이 완전히 사라집니다.")
        base = dict(project_id="x", platform=posts.PAGES, revision=1, status=st.REVIEW_REQUIRED)
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=general)), ())
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, gate_ok=False, health=general)), ("gate",))
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=stop)), ("health",))
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=general, secrets=(("본문", 1, "Google API 키"),))), ("secret",))
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=general, similarity=posts.SimilarityInfo("high", 0.9))), ("similarity",))
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=general, similarity=posts.SimilarityInfo("warn", 0.5))), (), "경고만이면 막지 않는다")
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=None)), ("incomplete",), "건강 판정이 빠진 결과는 믿지 않는다")
        self.assertEqual(rules.review_blocks(None), ("incomplete",))
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, gate_ok=False, health=stop, secrets=(("본문", 1, "x"),), similarity=posts.SimilarityInfo("high", 1.0))), ("gate", "health", "secret", "similarity"))

    def test_the_pages_values_are_checked_at_the_renderer_limits(self):
        from chanceblog_desktop.render import pages as renderer
        self.assertEqual(rules.pages_problems(RAW), {})
        self.assertEqual(rules.pages_problems({}), {"category": "post_pv_p_category", "lang": "post_pv_p_lang", "image_url": "post_pv_p_image"})
        edit = lambda **change: rules.pages_problems({**RAW, **change})  # noqa: E731
        self.assertEqual(edit(category="가" * renderer.MAX_CATEGORY), {})
        self.assertEqual(edit(category="가" * (renderer.MAX_CATEGORY + 1)), {"category": "post_pv_p_category"})
        self.assertEqual(edit(category="  "), {"category": "post_pv_p_category"})
        self.assertEqual(edit(category="가\n나"), {"category": "post_pv_p_category"})
        self.assertEqual(edit(lang="fr"), {"lang": "post_pv_p_lang"})
        self.assertEqual(edit(tags=", ".join(f"태그{number}" for number in range(renderer.MAX_TAGS))), {})
        self.assertEqual(edit(tags=", ".join(f"태그{number}" for number in range(renderer.MAX_TAGS + 1))), {"tags": "post_pv_p_tags"})
        self.assertEqual(edit(tags="가" * renderer.MAX_TAG), {})
        self.assertEqual(edit(tags="가" * (renderer.MAX_TAG + 1)), {"tags": "post_pv_p_tags"})
        self.assertEqual(edit(description="가" * renderer.MAX_DESCRIPTION), {})
        self.assertEqual(edit(description="가" * (renderer.MAX_DESCRIPTION + 1)), {"description": "post_pv_p_desc"})
        for bad in ("", "http://img.example.invalid/a.jpg", "https://", "https:///a", "ftp://x/a", "https://img.example.invalid/a b.jpg", "img.example.invalid/a.jpg", "javascript:alert(1)", "https://" + "a" * 1500):
            with self.subTest(url=bad[:30]):
                self.assertEqual(edit(image_url=bad), {"image_url": "post_pv_p_image"})
        values = rules.pages_values_of({**RAW, "tags": " 하나 , 둘，셋、 ,, ", "category": " 생활 "})
        self.assertEqual((values.category, values.tags, values.lang), ("생활", ("하나", "둘", "셋"), "ko"))
        self.assertEqual(rules.pages_raw_of(values)["tags"], "하나, 둘, 셋")
        self.assertEqual(rules.pages_raw_of(None)["lang"], "ko")

    def test_times_are_shown_in_korean_time_and_odd_values_are_hidden(self):
        self.assertEqual(rules.when_text("2026-11-24T05:30:12Z"), "2026-11-24 14:30")
        self.assertEqual(rules.when_text("2026-12-31T20:00:00Z"), "2027-01-01 05:00")
        for odd in ("", None, "어제", "2026-13-40T99:99:99Z", "2026-11-24 05:30:12", 5):
            self.assertEqual(rules.when_text(odd), "", repr(odd))

    def test_the_title_suggestion_is_the_file_name_without_the_extension(self):
        self.assertEqual(rules.title_of("C:/예시 폴더/글 하나.md"), "글 하나")
        self.assertEqual(rules.title_of("a\\b\\c.tar.md"), "c.tar")
        self.assertEqual(rules.title_of(""), "")
        self.assertEqual(len(rules.title_of("가" * 500)), 200)

    def test_the_names_and_limits_are_the_services(self):
        self.assertEqual(posts.PLATFORMS, review.SUPPORTED)
        self.assertEqual(posts.PAGES, previews.PLATFORM_PAGES)
        for status in service_format.STATUS_KO:
            self.assertEqual(rules.status_text(status), service_format.STATUS_KO[status], status)
        for platform in posts.PLATFORMS:
            self.assertEqual(rules.platform_text(platform), service_format.PLATFORM_KO[platform], platform)
        self.assertEqual(rules.status_text("없는상태"), T["post_status_unknown"])
        self.assertEqual(rules.status_text(None), T["post_status_unknown"])
        self.assertEqual(rules.platform_text("blogger_ko"), "", "Blogger 는 이 흐름에 없다")
        self.assertEqual(post_fake.LENGTH_MIN, __import__("chanceblog_desktop.service.gate", fromlist=["x"]).LENGTH_MIN)
        self.assertEqual(rules.REVIEWABLE | rules.APPROVED_NOW, rules.REVIEWABLE, "승인 취소를 켜는 상태에서는 다시 검토도 켠다")
        for status in (st.COMMITTED, st.PUSHED, st.PUBLISHED, st.DRAFT_SAVED, st.COPY_COMPLETED, st.PUBLISHED_MANUAL):
            self.assertNotIn(status, rules.REVIEWABLE, f"{status} 는 1a 화면이 바꾸지 않는다")


class PostsStatesCoreTest(unittest.TestCase):
    def test_the_six_list_states(self):
        provider = post_fake.FakePostsProvider()
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        self.assertEqual(controller.view()["state"], "loading")
        self.assertIn(controller.view()["state"], posts_view.LIST_STATES)
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        self.assertEqual(controller.view()["state"], "normal")
        self.assertIsNone(controller.view()["banner"])
        empty = make("empty")
        self.assertEqual(empty.view()["state"], "empty")
        self.assertEqual(empty.view()["list"]["empty"]["button"], T["post_import"])
        partial = make("partial")
        self.assertEqual(partial.view()["state"], "partial")
        self.assertEqual(partial.view()["banner"], ("alert", T["post_partial"].format(n=1)))
        offline = make("offline")
        self.assertEqual(offline.view()["state"], "offline")
        self.assertEqual(offline.view()["banner"], ("cloud_off", T["post_offline"]))
        failing = posts_view.PostsController(post_fake.FakePostsProvider("error"), jobs.JobRunner())
        results = {}
        job = failing.start_load(on_error=lambda failure, _p: results.setdefault("failed", failure))
        job.join(10)
        self.assertEqual(failing.view()["state"], "loading")
        failing.apply_load_failed(results["failed"], None)
        error = failing.view("code: X")
        self.assertEqual((error["state"], error["error"]["title"], error["error"]["diag"]), ("error", T["post_error_title"], "code: X"))
        self.assertEqual(error["error"]["button"], T["post_retry"])

    def test_a_missing_store_is_an_empty_list_and_an_unreadable_row_is_a_card_without_open(self):
        controller = make("partial")
        broken = [row for row in controller.view()["list"]["rows"] if row["unreadable"]]
        self.assertEqual(len(broken), 1)
        self.assertEqual((broken[0]["open"], broken[0]["title"]), (None, T["post_row_unreadable"]))
        self.assertEqual(controller.start_open("exmbroken"), ("unknown", None), "읽을 수 없는 글은 열지 않는다")

    def test_the_list_is_newest_first_and_each_card_says_status_in_words(self):
        controller = make()
        view = controller.view()["list"]
        stamps = [row.updated_at for row in controller.data.rows]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        first = next(row for row in view["rows"] if "GitHub Pages" in " ".join(row["status_lines"]))
        self.assertIn(T["post_platform_line"].format(name="GitHub Pages", status="검토 중"), first["status_lines"])
        quiet = [row for row in view["rows"] if row["status_lines"] == [T["post_row_none"]]]
        self.assertTrue(quiet, "아직 어디에도 내보내지 않은 글은 그렇게 말한다")
        for row in view["rows"]:
            self.assertTrue(row["a11y"] and row["open"]["a11y"] and row["title"] in row["a11y"])

    def test_a_long_list_is_drawn_fifty_at_a_time(self):
        controller = make("many")
        view = controller.view()["list"]
        self.assertEqual((len(view["rows"]), view["count"]), (rules.PAGE, T["post_count"].format(n=130)))
        self.assertEqual(view["more"], {"text": T["post_more"], "a11y": T["post_more_a11y"]})
        controller.show_more()
        self.assertEqual(len(controller.view()["list"]["rows"]), 2 * rules.PAGE)
        controller.show_more()
        controller.show_more()
        done = controller.view()["list"]
        self.assertEqual((len(done["rows"]), done["more"]), (130, None))

    def test_the_list_never_shows_a_key_shaped_title(self):
        provider = post_fake.FakePostsProvider("empty")
        provider.add_post("제목 " + KEY, post_fake.sample_text())
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        row = controller.view()["list"]["rows"][0]
        self.assertNotIn(KEY[:12], repr(row))
        self.assertTrue(row["title"])

    def test_opening_a_post_reads_it_and_picks_the_platform_that_has_progress(self):
        controller = make()
        review_id = next(row.project_id for row in controller.data.rows if dict(row.statuses)[posts.PAGES] == st.REVIEW_REQUIRED)
        self.assertEqual(open_post(controller, review_id), "ok")
        view = controller.view()
        self.assertEqual((view["mode"], controller.platform), ("detail", posts.PAGES))
        self.assertEqual(view["detail"]["state"], "normal")
        self.assertEqual(view["detail"]["title"], controller.detail.title)
        other = next(row.project_id for row in controller.data.rows if row.project_id != review_id)
        controller.close_post()
        self.assertEqual(controller.view()["mode"], "list")
        self.assertEqual(open_post(controller, other), "ok")
        self.assertEqual(controller.platform, posts.PAGES, "어디에도 내보내지 않은 글은 Pages 가 처음 고른 칩이다")

    def test_opening_an_unknown_post_does_nothing_and_a_post_that_vanishes_goes_back_to_the_list(self):
        controller = make()
        self.assertEqual(controller.start_open("없는번호"), ("unknown", None))
        self.assertIsNone(controller.open_id)
        project_id = row_ids(controller)[0]
        open_post(controller, project_id)
        controller.provider.projects.pop(project_id)
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        view = controller.view()
        self.assertEqual((view["mode"], view["notice"]), ("list", {"level": "warning", "text": T["post_detail_gone"]}))
        self.assertEqual(open_post(make(), "exm99999"), "unknown")

    def test_a_detail_that_cannot_be_read_shows_an_error_with_back_and_retry(self):
        provider = post_fake.FakePostsProvider(fail={"load_post": posts.PostFailure(T["post_fail_read"], code="STORE_CORRUPT", kind="corrupt")})
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        self.assertEqual(open_post(controller, row_ids(controller)[0]), "error")
        view = controller.view("code: STORE_CORRUPT")["detail"]
        self.assertEqual((view["state"], view["error"]["title"], view["error"]["button"]), ("error", T["post_detail_error_title"], T["post_retry"]))
        self.assertEqual(view["back"], {"text": T["post_back"], "a11y": T["post_back_a11y"]})
        self.assertNotIn("STORE_CORRUPT", view["error"]["desc"], "오류 코드는 접힌 진단 정보에만 있다")

    def test_a_late_detail_for_another_post_is_dropped(self):
        controller = make()
        ids = row_ids(controller)
        open_post(controller, ids[0])
        late = controller.provider.load_post(ids[1], SAFE, NEVER)
        self.assertFalse(controller.apply_detail(late))
        self.assertEqual(controller.detail.project_id, ids[0])

    def test_the_view_has_one_primary_action_in_each_mode(self):
        controller = make()
        self.assertTrue(controller.view()["import"]["enabled"], "목록의 주요 단추는 글 가져오기 하나다")
        open_post(controller, row_ids(controller)[0])
        panel = controller.view()["detail"]["review"]["panel"]
        primary = [name for name in ("review", "approve") if panel[name]["primary"]]
        self.assertLessEqual(len(primary), 1)


class PostsPreviewCoreTest(unittest.TestCase):
    def test_the_detail_view_carries_the_safe_preview_and_its_information_line(self):
        provider = post_fake.FakePostsProvider("empty")
        project_id = provider.add_post("미리보기 글", "## 소제목\n\n문단이에요 " + KEY + " 끝.\n\n<script>alert(1)</script>")
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        view = controller.view()["detail"]["preview"]
        self.assertEqual([block["kind"] for block in view["blocks"]], ["heading", "paragraph", "paragraph"])
        self.assertEqual(view["blocks"][0]["label"], T["post_block_heading"])
        self.assertIn("<script>alert(1)</script>", [block["text"] for block in view["blocks"]], "스크립트는 글자 그대로 보인다")
        self.assertNotIn(KEY[:12], repr(view), "키 모양은 가려서 나간다")
        self.assertEqual(view["note"], T["post_preview_note"])
        self.assertIn("본문", view["info"])
        self.assertEqual((view["cut"], view["empty"]), ("", ""))

    def test_a_long_post_says_it_shows_only_the_front(self):
        provider = post_fake.FakePostsProvider("empty")
        project_id = provider.add_post("긴 글", "\n\n".join(f"문단 {number}" for number in range(300)))
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        view = controller.view()["detail"]["preview"]
        self.assertEqual(len(view["blocks"]), rules.PREVIEW_BLOCKS)
        self.assertEqual(view["cut"], T["post_preview_cut"].format(total=300, shown=rules.PREVIEW_BLOCKS))

    def test_an_empty_preview_says_there_is_nothing_to_show(self):
        provider = post_fake.FakePostsProvider("empty")
        project_id = provider.add_post("빈 글", "![이미지만](https://img.example.invalid/a.png)")
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        self.assertEqual(controller.view()["detail"]["preview"]["empty"], T["post_preview_empty"])

    def test_the_preview_belongs_to_the_revision_that_was_read(self):
        controller = make()
        project_id = row_ids(controller)[0]
        open_post(controller, project_id)
        before = controller.detail.revision
        controller.provider.edit(project_id, source_content="## 바뀐 글\n\n새 문단")
        self.assertEqual(controller.detail.revision, before, "다시 읽기 전에는 읽은 판 그대로다")
        open_post(controller, project_id)
        self.assertEqual(controller.detail.revision, before + 1)
        self.assertEqual(controller.view()["detail"]["preview"]["blocks"][0]["text"], "바뀐 글")


class PostsImportCoreTest(unittest.TestCase):
    def test_import_opens_a_dialog_with_nothing_started_and_nothing_written(self):
        controller = make("empty")
        self.assertTrue(controller.open_import())
        self.assertFalse(controller.open_import(), "이미 열려 있다")
        view = controller.import_view(0, 0)
        self.assertEqual((view["kind"], view["start"]["enabled"], view["cancel"]["enabled"], view["pick"]["visible"]), ("markdown", False, True, True))
        self.assertEqual(controller.provider.calls, ["load_posts"], "대화를 여는 것만으로는 서비스를 부르지 않는다")
        self.assertEqual(controller.import_view(3, 0)["start"]["enabled"], False)
        self.assertEqual(controller.import_view(3, 5)["start"]["enabled"], True)

    def test_importing_a_markdown_post_saves_it_closes_the_dialog_and_opens_the_post(self):
        controller = make("empty")
        controller.open_import()
        controller.import_edited(True)
        status, end, todo = drive(controller, lambda **cb: controller.start_import("새 글 제목", post_fake.sample_text(), **cb))
        self.assertEqual((status, end, todo), ("started", "ok", {"reload_list": True}))
        view = controller.view()
        self.assertFalse(controller.import_open)
        self.assertEqual((view["mode"], view["detail"]["title"]), ("detail", "새 글 제목"))
        self.assertEqual(view["notice"], {"level": "ok", "text": T["post_im_done"].format(title="새 글 제목")})
        self.assertEqual(controller.platform, posts.PAGES)
        self.assertEqual(len(controller.provider.projects), 1)

    def test_importing_html_keeps_allowed_tags_only(self):
        controller = make("empty")
        controller.open_import()
        controller.set_import_kind("html")
        self.assertEqual(controller.import_view(1, 1)["pick"]["visible"], False, "HTML 은 붙여 넣기만 읽는다")
        self.assertEqual(controller.import_view(1, 1)["kind_note"], T["post_im_html_note"])
        status, end, _ = drive(controller, lambda **cb: controller.start_import("옛 글", "<h2>소제목</h2><p>문단 <strong>굵게</strong></p><script>alert(1)</script>", **cb))
        self.assertEqual((status, end), ("started", "ok"))
        project = next(iter(controller.provider.projects.values()))
        self.assertNotIn("script", project.source_content.lower())
        self.assertIn("소제목", project.source_content)

    def test_an_empty_title_or_body_is_not_sent(self):
        controller = make("empty")
        controller.open_import()
        for title, body in (("", "본문"), ("  ", "본문"), ("제목", ""), ("제목", "  \n "), (None, "본문"), ("제목", None)):
            with self.subTest(title=title, body=body):
                self.assertEqual(controller.start_import(title, body)[0], "invalid")
                self.assertEqual(controller.import_message, T["post_fail_input_plain"])
        self.assertEqual(controller.provider.calls, ["load_posts"])
        self.assertEqual(posts_view.PostsController(post_fake.FakePostsProvider("empty"), jobs.JobRunner()).start_import("제목", "본문")[0], "busy", "대화가 열려 있지 않으면 시작하지 않는다")

    def test_a_failed_import_keeps_the_dialog_and_says_why_without_repeating_the_text(self):
        controller = make("empty")
        controller.open_import()
        controller.import_edited(True)
        status, end, todo = drive(controller, lambda **cb: controller.start_import("키 글", "본문 " + KEY, **cb))
        self.assertEqual((status, end, todo), ("started", "failed", {}))
        self.assertTrue(controller.import_open)
        self.assertIn("본문 1번째 줄", controller.import_message)
        self.assertIn("Google API 키", controller.import_message)
        self.assertNotIn(KEY[:10], controller.import_message)
        self.assertNotIn(KEY[:10], repr(controller.view()) + repr(controller.import_view(3, 8)))
        self.assertEqual(controller.import_view(3, 8)["message"], controller.import_message)
        self.assertEqual(len(controller.provider.projects), 0, "저장하지 않았다")
        self.assertTrue(controller.import_dirty, "입력은 그대로 남아 있다")

    def test_editing_the_fields_clears_the_old_message_and_the_discard_question(self):
        controller = make("empty")
        controller.open_import()
        controller.import_message = "이전 거절"
        controller.import_edited(True)
        self.assertEqual(controller.import_message, "")
        self.assertEqual(controller.request_close_import(), "ask")
        controller.import_edited(True)
        self.assertFalse(controller.import_ask)

    def test_closing_the_dialog_with_typed_text_asks_first_and_empty_closes_at_once(self):
        controller = make("empty")
        controller.open_import()
        self.assertEqual(controller.request_close_import(), "closed")
        self.assertFalse(controller.import_open)
        controller.open_import()
        controller.import_edited(True)
        self.assertEqual(controller.request_close_import(), "ask")
        self.assertTrue(controller.import_open and controller.import_ask)
        view = controller.import_view(3, 8)["discard"]
        self.assertEqual((view["open"], view["question"], view["no"]["text"]), (True, T["post_im_discard_q"], T["post_im_discard_no"]))
        controller.keep_import()
        self.assertTrue(controller.import_open and not controller.import_ask)
        self.assertEqual(controller.request_close_import(), "ask")
        self.assertEqual(controller.request_close_import(), "closed", "확인 줄이 떠 있을 때 한 번 더 닫으면 닫힌다")
        self.assertFalse(controller.import_open or controller.import_dirty)

    def test_the_app_close_question_exists_only_while_typed_text_would_be_lost(self):
        controller = make("empty")
        self.assertIsNone(controller.close_dialog())
        controller.open_import()
        self.assertIsNone(controller.close_dialog(), "입력이 없으면 묻지 않는다")
        controller.import_edited(True)
        dialog = controller.close_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"], dialog["posts"]), (T["post_close_title"], T["post_close_ok"], T["post_close_cancel"], True))
        self.assertTrue(controller.has_unsaved())
        controller.close_import()
        self.assertIsNone(controller.close_dialog())

    def test_reading_a_file_hands_the_text_to_the_screen_and_keeps_none_of_it(self):
        controller = make("empty")
        controller.open_import()
        results = {}
        status, job = controller.start_read_file("C:/예시 폴더/내 글.md", on_done=lambda result, _p: results.setdefault("ok", result))
        self.assertEqual(status, "started")
        job.join(10)
        file = controller.apply_file(results["ok"])
        self.assertEqual((file.name, file.encoding), ("내 글", "utf-8"))
        self.assertEqual(controller.import_note, T["post_im_read_ok"])
        self.assertNotIn(file.text[:20], repr(controller.view()) + repr(controller.import_view(1, 1)) + repr(vars(controller)), "컨트롤러는 읽은 글을 쥐지 않는다")
        again = {}
        controller.open_import() if not controller.import_open else None
        _s, job = controller.start_read_file("C:/폴더/cp949 글.md", on_done=lambda result, _p: again.setdefault("ok", result))
        job.join(10)
        controller.apply_file(again["ok"])
        self.assertEqual(controller.import_note, T["post_im_cp949"])

    def test_a_file_that_cannot_be_read_shows_the_reason_and_leaves_the_fields_alone(self):
        controller = make("empty")
        controller.open_import()
        results = {}
        _s, job = controller.start_read_file("C:/폴더/나쁜.bad", on_error=lambda failure, _p: results.setdefault("failed", failure))
        job.join(10)
        controller.apply_file_failed(results["failed"])
        self.assertIn("글 파일이 아닌 것 같아요", controller.import_message)

    def test_reading_a_file_needs_the_markdown_kind_and_an_open_dialog_and_no_other_write(self):
        controller = make("empty")
        self.assertEqual(controller.start_read_file("C:/a.md")[0], "busy", "대화가 열려 있지 않다")
        controller.open_import()
        controller.set_import_kind("html")
        self.assertEqual(controller.start_read_file("C:/a.md")[0], "busy", "HTML 은 파일을 읽지 않는다")
        self.assertFalse(controller.set_import_kind("rtf"))

    def test_import_is_a_write_that_runs_one_at_a_time(self):
        import threading
        gate = threading.Event()

        class Gated(post_fake.FakePostsProvider):
            def import_post(self, request, progress, cancelled):
                gate.wait(10)
                return super().import_post(request, progress, cancelled)

        provider = Gated("empty")
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        controller.open_import()
        status, job = controller.start_import("제목", post_fake.sample_text())
        self.assertEqual(status, "started")
        self.assertTrue(controller.busy)
        self.assertEqual(controller.start_import("둘째", post_fake.sample_text()), ("busy", None))
        self.assertEqual(controller.request_close_import(), "busy", "가져오는 중에는 대화를 닫지 않는다")
        self.assertFalse(controller.import_view(1, 1)["cancel"]["enabled"])
        self.assertEqual(controller.import_view(1, 1)["working"], T["post_im_importing"])
        self.assertIsNone(controller.start_load(), "쓰는 동안 목록을 다시 읽지 않는다")
        gate.set()
        job.join(10)


class PostsReviewCoreTest(unittest.TestCase):
    def opened(self, scenario="normal", **kwargs):
        controller = make(scenario, **kwargs)
        project_id = long_post(controller.provider, "검토할 글")
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        return controller

    def test_a_pages_review_needs_valid_values_and_does_not_call_the_service_otherwise(self):
        controller = self.opened()
        calls = list(controller.provider.calls)
        status, problems = controller.start_review(posts.PAGES, {})[0:2]
        self.assertEqual(status, "invalid")
        self.assertEqual(set(problems), {"category", "lang", "image_url"})
        self.assertEqual(controller.provider.calls, calls)
        self.assertEqual(controller.pages_view()["problems"]["category"], T["post_pv_p_category"])
        self.assertFalse(controller.busy)

    def test_a_pages_review_shows_three_layers_and_remembers_the_values_for_this_session(self):
        controller = self.opened()
        status, end, todo = review_pages(controller)
        self.assertEqual((status, end, todo), ("started", "ok", {"reload_list": True}))
        self.assertEqual(controller.detail.platform(posts.PAGES).status, st.REVIEW_REQUIRED)
        result = controller.view()["detail"]["review"]["panel"]["result"]
        self.assertEqual(result["state"], "ready")
        self.assertEqual([section["key"] for section in result["sections"]], ["gates", "health", "secret", "summary"])
        badges = {section["key"]: section["badge"]["text"] for section in result["sections"]}
        self.assertEqual((badges["gates"], badges["health"], badges["secret"]), (T["post_badge_pass"], T["post_badge_pass"], T["post_badge_pass"]))
        self.assertEqual(controller.view()["notice"], {"level": "ok", "text": T["post_done_review"]})
        self.assertEqual(controller.pages_raw[controller.open_id]["category"], "생활")
        self.assertEqual(controller.open_pages()["category"], "생활", "다시 열면 지난번 값이 채워진다")

    def test_a_blocked_gate_is_shown_with_an_easy_sentence_per_code_and_the_raw_reasons_folded(self):
        controller = make("empty")
        project_id = controller.provider.add_post("짧은 글", "## 짧음\n\n<div>태그</div>")
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        review_pages(controller)
        section = next(item for item in controller.view()["detail"]["review"]["panel"]["result"]["sections"] if item["key"] == "gates")
        self.assertEqual(section["badge"], {"tone": "danger", "text": T["post_badge_block"]})
        self.assertIn(T["post_gate_len_body"], section["lines"])
        self.assertIn(T["post_gate_raw_html"], section["lines"])
        self.assertEqual(section["lines"][0], T["post_gate_blocked"].format(n=2))
        self.assertTrue(any("LEN_BODY" in line for line in section["details"]), "원래 사유는 접힌 자세히에만 있다")
        self.assertFalse(any("LEN_BODY" in line for line in section["lines"]), "보이는 줄에는 코드가 없다")
        self.assertFalse(controller.approval()[0])

    def test_a_health_claim_blocks_and_a_light_health_topic_does_not(self):
        controller = make("empty")
        stop_id = controller.provider.add_post("건강 글", post_fake.sample_text() + "\n\n이 영양제를 먹으면 통증이 완전히 사라집니다.")
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, stop_id)
        review_pages(controller)
        health = next(item for item in controller.view()["detail"]["review"]["panel"]["result"]["sections"] if item["key"] == "health")
        self.assertEqual(health["badge"]["text"], T["post_badge_block"])
        self.assertEqual(health["lines"][0], T["post_health_stop"])
        self.assertTrue(health["lines"][1].startswith(T["post_health_places"]), "걸린 문장의 앞부분을 보인다")
        self.assertEqual(controller.approval(), (False, "post_approve_why_blocked"))
        self.assertIsNone(controller.approve_dialog(), "막힌 글은 확인창도 뜨지 않는다")

    def test_a_key_shape_in_the_post_blocks_with_place_and_kind_only(self):
        controller = make("empty")
        project_id = controller.provider.add_post("키 글", post_fake.sample_text() + f"\n\n마지막 줄 {KEY}")
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        review_pages(controller)
        view = controller.view()["detail"]["review"]["panel"]["result"]
        secret = next(item for item in view["sections"] if item["key"] == "secret")
        self.assertEqual(secret["badge"]["text"], T["post_badge_block"])
        self.assertIn("Google API 키", secret["lines"][0])
        self.assertNotIn(KEY[:10], repr(view) + repr(controller.view()["detail"]["preview"]))
        self.assertEqual(controller.approval(), (False, "post_approve_why_blocked"))

    def test_naver_needs_a_profile_and_otherwise_shows_similarity_and_summary(self):
        controller = self.opened(profiles=())
        self.assertEqual(controller.start_review(posts.NAVER_A)[0], "profile")
        controller.select_platform(posts.NAVER_A)
        panel = controller.view()["detail"]["review"]["panel"]
        self.assertEqual(panel["profile_missing"], T["post_naver_profile_missing"])
        self.assertFalse(panel["review"]["enabled"])
        both = self.opened()
        status, end, _ = drive(both, lambda **cb: both.start_review(posts.NAVER_A, **cb))
        self.assertEqual((status, end), ("started", "ok"))
        self.assertEqual(both.platform, posts.NAVER_A)
        sections = {item["key"]: item for item in both.view()["detail"]["review"]["panel"]["result"]["sections"]}
        self.assertEqual(sections["naver"]["lines"], [T["post_naver_similarity_none"]], "다른 블로그에 검토한 글이 없으면 비교하지 않는다")
        self.assertNotIn("gates", sections, "네이버에는 Pages 관문이 없다")
        drive(both, lambda **cb: both.start_review(posts.NAVER_B, **cb))
        high = {item["key"]: item for item in both.view()["detail"]["review"]["panel"]["result"]["sections"]}["naver"]
        self.assertEqual(high["badge"]["text"], T["post_badge_block"])
        self.assertTrue(high["lines"][0].startswith("두 네이버 블로그 글이 많이 비슷해요"))

    def test_review_is_only_for_states_this_screen_may_change(self):
        controller = self.opened()
        for status in (st.COMMITTED, st.PUSHED, st.PUBLISHED, st.COPY_COMPLETED, st.PUBLISHED_MANUAL, st.DRAFT_SAVED):
            with self.subTest(status=status):
                controller.provider.projects[controller.open_id].variants[posts.PAGES].status = status
                open_post(controller, controller.open_id)
                self.assertEqual(controller.start_review(posts.PAGES, dict(RAW))[0], "state")
                panel = controller.view()["detail"]["review"]["panel"]
                self.assertEqual((panel["review"]["visible"], panel["approve"]["visible"], panel["revoke"]["visible"]), (False, False, False))
                self.assertEqual(panel["after"], T["post_review_after_note"])

    def test_the_platform_chips_say_name_and_state_in_words(self):
        controller = self.opened()
        chips = controller.view()["detail"]["review"]["chips"]
        self.assertEqual([chip["key"] for chip in chips], list(posts.PLATFORMS))
        self.assertEqual(chips[0]["text"], T["post_chip"].format(name="GitHub Pages", status="시작 전"))
        self.assertTrue(all(chip["a11y"] for chip in chips))
        self.assertEqual([chip["selected"] for chip in chips], [True, False, False])
        self.assertTrue(controller.select_platform(posts.NAVER_B))
        self.assertEqual([chip["selected"] for chip in controller.view()["detail"]["review"]["chips"]], [False, False, True])
        self.assertFalse(controller.select_platform("blogger_ko"))

    def test_the_pages_dialog_stays_open_with_a_reason_when_the_service_refuses_the_values(self):
        controller = self.opened(fail={"review_post": posts.PostFailure(T["post_gate_header_value"], code="CHECK_FAILED", kind="check")})
        self.assertIsNotNone(controller.open_pages())
        status, end, todo = review_pages(controller)
        self.assertEqual((status, end, todo), ("started", "failed", {}))
        self.assertTrue(controller.pages_open)
        self.assertEqual(controller.pages_view()["message"], T["post_gate_header_value"])
        self.assertEqual(controller.pages_raw[controller.open_id]["category"], "생활", "값은 남아 있다")

    def test_a_review_of_the_approved_state_revokes_the_approval_and_says_so(self):
        controller = self.opened()
        review_pages(controller)
        approve(controller)
        panel = controller.view()["detail"]["review"]["panel"]
        self.assertEqual((panel["review"]["text"], panel["review"]["note"]), (T["post_review_again"], T["post_review_again_note"]))
        review_pages(controller)
        self.assertEqual(controller.detail.platform(posts.PAGES).status, st.REVIEW_REQUIRED)


class PostsApproveCoreTest(unittest.TestCase):
    def reviewed(self, provider=None, title="승인할 글", markdown=None):
        controller = make("empty") if provider is None else provider
        project_id = controller.provider.add_post(title, markdown or post_fake.sample_text())
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        return controller

    def test_approve_is_off_before_a_review_and_needs_the_dialog_first(self):
        controller = self.reviewed()
        self.assertEqual(controller.approval(), (False, "post_approve_why_none"))
        self.assertFalse(controller.view()["detail"]["review"]["panel"]["approve"]["visible"], "검토 전에는 승인 단추 자리가 없다")
        review_pages(controller)
        self.assertEqual(controller.approval(), (True, ""))
        self.assertEqual(controller.start_approve(), ("unconfirmed", None), "확인창을 보이지 않고는 시작하지 않는다")
        self.assertEqual(controller.provider.calls.count("approve_post"), 0)
        self.assertEqual(controller.detail.platform(posts.PAGES).status, st.REVIEW_REQUIRED)

    def test_the_confirm_text_says_approval_is_not_publishing(self):
        controller = self.reviewed()
        review_pages(controller)
        dialog = controller.approve_dialog()
        self.assertEqual(dialog["title"], T["post_confirm_title"])
        self.assertIn("어디에도 올리지 않아요", dialog["body"])
        self.assertIn("취소할 수 있어요", dialog["body"])
        self.assertIn("GitHub Pages", dialog["body"])
        self.assertIn(f"판 {controller.detail.revision}", dialog["body"])
        self.assertEqual((dialog["ok"], dialog["cancel"]), (T["post_confirm_ok"], T["post_confirm_cancel"]))

    def test_approve_after_the_dialog_moves_the_post_to_approved_and_a_second_press_does_nothing(self):
        controller = self.reviewed()
        review_pages(controller)
        status, end, todo = approve(controller)
        self.assertEqual((status, end, todo), ("started", "ok", {"reload_list": True}))
        self.assertEqual(controller.detail.platform(posts.PAGES).status, st.APPROVED)
        self.assertEqual(controller.view()["notice"], {"level": "ok", "text": T["post_done_approved"]})
        self.assertIn("어디에도 올리지 않아요", T["post_done_approved"])
        self.assertEqual(controller.start_approve(), ("refused", "post_approve_why_state"))
        panel = controller.view()["detail"]["review"]["panel"]
        self.assertEqual((panel["approve"]["visible"], panel["revoke"]["visible"], panel["revoke"]["enabled"]), (False, True, True))
        self.assertEqual(panel["primary"] if "primary" in panel else "", "")

    def test_cancelling_the_confirm_removes_the_mark_so_the_press_is_not_accepted_later(self):
        controller = self.reviewed()
        review_pages(controller)
        controller.approve_dialog()
        controller.discard_approve()
        self.assertEqual(controller.start_approve(), ("unconfirmed", None))

    def test_a_confirm_is_for_that_post_platform_and_revision_only(self):
        controller = self.reviewed()
        review_pages(controller)
        controller.approve_dialog()
        controller.select_platform(posts.NAVER_A)                       # 다른 플랫폼을 고르면 확인 표시는 사라진다
        controller.select_platform(posts.PAGES)
        self.assertEqual(controller.start_approve(), ("unconfirmed", None))
        controller.approve_dialog()
        controller.provider.edit(controller.open_id, source_content="## 바뀜\n\n" + post_fake.sample_text())
        open_post(controller, controller.open_id)
        self.assertEqual(controller.start_approve()[0], "refused", "글이 바뀐 뒤에는 옛 확인으로 승인하지 않는다")

    def test_a_post_edited_after_the_review_cannot_be_approved_until_reviewed_again(self):
        controller = self.reviewed()
        review_pages(controller)
        controller.provider.edit(controller.open_id, source_content="## 고친 글\n\n" + post_fake.sample_text())
        open_post(controller, controller.open_id)
        self.assertEqual(controller.detail.platform(posts.PAGES).status, st.DRAFT_GENERATED, "고치면 검토가 풀린다")
        self.assertFalse(controller.approval()[0])
        self.assertEqual(controller.view()["detail"]["review"]["panel"]["result"]["state"], "stale")
        self.assertEqual(controller.view()["detail"]["review"]["panel"]["result"]["sections"], [], "낡은 결과는 펼쳐 보이지 않는다")
        review_pages(controller)
        self.assertTrue(controller.approval()[0])

    def test_the_provider_refuses_a_stale_approval_even_if_the_screen_asked(self):
        controller = self.reviewed()
        review_pages(controller)
        controller.approve_dialog()
        controller.provider.edit(controller.open_id, source_content="## 그 사이 고침\n\n" + post_fake.sample_text())
        status, end, todo = drive(controller, lambda **cb: controller.start_approve(**cb))
        self.assertEqual((status, end), ("started", "failed"))
        self.assertEqual(todo, {"reload": True})
        self.assertEqual(controller.view()["notice"]["level"], "error")
        self.assertNotEqual(controller.detail.platform(posts.PAGES).status, st.APPROVED)

    def test_a_blocked_review_cannot_be_approved_by_any_path(self):
        controller = self.reviewed(markdown="## 짧은 글\n\n짧아요.")
        review_pages(controller)
        self.assertEqual(controller.approval(), (False, "post_approve_why_blocked"))
        self.assertIsNone(controller.approve_dialog())
        self.assertEqual(controller.start_approve(), ("refused", "post_approve_why_blocked"))
        self.assertEqual(controller.provider.calls.count("approve_post"), 0)

    def test_an_incomplete_review_result_cannot_approve(self):
        controller = self.reviewed()
        review_pages(controller)
        controller.review = posts.ReviewReport(controller.open_id, posts.PAGES, controller.detail.revision, st.REVIEW_REQUIRED, True, health=None)
        self.assertEqual(controller.approval(), (False, "post_approve_why_blocked"))

    def test_a_result_for_another_post_or_platform_cannot_approve(self):
        controller = self.reviewed()
        review_pages(controller)
        saved = controller.review
        controller.review = posts.ReviewReport("다른글", saved.platform, saved.revision, saved.status, True, health=saved.health)
        self.assertEqual(controller.approval(), (False, "post_res_lost"))
        controller.review = saved
        controller.select_platform(posts.NAVER_A)
        self.assertFalse(controller.approval()[0])

    def test_revoke_returns_to_review_without_a_dialog_and_only_from_an_approved_state(self):
        controller = self.reviewed()
        self.assertEqual(controller.start_revoke(), ("state", None))
        review_pages(controller)
        self.assertEqual(controller.start_revoke(), ("state", None), "검토 중에는 취소할 승인이 없다")
        approve(controller)
        status, end, todo = drive(controller, lambda **cb: controller.start_revoke(**cb))
        self.assertEqual((status, end, todo), ("started", "ok", {"reload_list": True}))
        self.assertEqual(controller.detail.platform(posts.PAGES).status, st.REVIEW_REQUIRED)
        self.assertEqual(controller.view()["notice"], {"level": "ok", "text": T["post_done_revoked"]})

    def test_a_published_state_has_no_revoke_and_no_approve(self):
        controller = self.reviewed()
        review_pages(controller)
        approve(controller)
        controller.provider.projects[controller.open_id].variants[posts.PAGES].status = st.PUBLISHED
        open_post(controller, controller.open_id)
        self.assertEqual(controller.start_revoke(), ("state", None))
        self.assertEqual(controller.start_approve()[0], "refused")

    def test_naver_approval_means_ready_to_copy_and_a_high_similarity_blocks_it(self):
        controller = self.reviewed()
        drive(controller, lambda **cb: controller.start_review(posts.NAVER_A, **cb))
        self.assertEqual(controller.approval(), (True, ""))
        approve(controller)
        self.assertEqual(controller.detail.platform(posts.NAVER_A).status, st.READY_TO_COPY)
        controller.select_platform(posts.NAVER_B)
        drive(controller, lambda **cb: controller.start_review(posts.NAVER_B, **cb))
        self.assertEqual(controller.approval(), (False, "post_approve_why_blocked"), "같은 글을 두 블로그에 그대로 올리지 않는다")
        self.assertEqual(controller.start_approve(), ("refused", "post_approve_why_blocked"))

    def test_the_panel_has_at_most_one_primary_button_and_it_is_the_next_step(self):
        controller = self.reviewed()
        for step in range(3):
            panel = controller.view()["detail"]["review"]["panel"]
            buttons = [name for name in ("review", "approve") if panel[name]["primary"]]
            if step == 0:
                self.assertEqual(buttons, ["review"])
                review_pages(controller)
            elif step == 1:
                self.assertEqual(buttons, ["approve"], "검토 결과를 받으면 다음 일은 승인이다")
                approve(controller)
            else:
                self.assertEqual(buttons, [], "승인한 뒤에는 주요 단추가 없다")
        self.assertEqual(sum(1 for name in ("review", "approve") if controller.view()["detail"]["review"]["panel"][name]["primary"]), 0)


class PostsFailureCoreTest(unittest.TestCase):
    def test_every_failure_kind_has_one_easy_sentence_without_codes_or_input(self):
        from chanceblog_desktop.ui import posts_adapter
        self.assertEqual(set(posts_adapter.SENTENCE_OF_KIND) | {"input", "secret", "check", "file"}, set(posts.KINDS_OF_FAILURE))
        for kind, key in posts_adapter.SENTENCE_OF_KIND.items():
            sentence = T[key]
            with self.subTest(kind=kind):
                self.assertFalse(re.search(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", sentence), sentence)
                self.assertNotRegex(sentence, r"Traceback|Exception|Error\b")
                self.assertTrue(sentence.endswith((".", "요")), sentence)

    def test_a_failed_write_keeps_the_screen_and_the_input_and_says_why(self):
        controller = make("empty")
        project_id = controller.provider.add_post("글", post_fake.sample_text())
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        controller.provider.fail["review_post"] = posts.PostFailure(T["post_fail_locked"], code="STORE_LOCKED", kind="locked")
        status, end, todo = review_pages(controller)
        self.assertEqual((status, end, todo), ("started", "failed", {}))
        view = controller.view()
        self.assertEqual((view["mode"], view["notice"]), ("detail", {"level": "error", "text": T["post_fail_locked"]}))
        self.assertFalse(controller.busy)

    def test_a_stale_or_missing_or_changed_state_asks_the_screen_to_read_again(self):
        for kind in ("stale", "notfound", "state"):
            with self.subTest(kind=kind):
                controller = make("empty")
                project_id = controller.provider.add_post("글", post_fake.sample_text())
                controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
                open_post(controller, project_id)
                controller.provider.fail["review_post"] = posts.PostFailure(T["post_fail_" + kind], code="X", kind=kind)
                self.assertEqual(review_pages(controller)[2], {"reload": True})

    def test_a_failure_text_is_masked_and_cut_before_it_is_shown(self):
        controller = make("empty")
        controller.open_import()
        controller.provider.fail["import_post"] = posts.PostFailure("문제 " + KEY + "가" * 500, code="X", kind="other")
        drive(controller, lambda **cb: controller.start_import("제목", "본문", **cb))
        self.assertNotIn(KEY[:10], controller.import_message)
        self.assertLessEqual(len(controller.import_message), 200)

    def test_an_unexpected_error_in_a_slot_becomes_an_error_state_with_the_exception_name_only(self):
        controller = make()
        controller.apply_unexpected(ValueError("비밀 " + KEY), None)
        view = controller.view("code: ValueError")
        self.assertEqual(view["state"], "error")
        self.assertNotIn(KEY[:10], repr(view))
        self.assertEqual(view["error"]["diag"], "code: ValueError")
        controller.apply_write_unexpected(RuntimeError("x"))
        self.assertEqual(controller.view()["notice"], {"level": "error", "text": T["post_fail_other"]})

    def test_the_diagnostic_text_goes_through_the_app_state_and_carries_the_code_only(self):
        state = app_state.AppState(posts=post_fake.FakePostsProvider("error"))
        results = {}
        job = state.posts.start_load(on_error=lambda failure, _p: results.setdefault("failed", failure))
        job.join(10)
        state.posts.apply_load_failed(results["failed"], None)
        view = state.posts_view()
        self.assertIn("SAMPLE_POSTS_UNREADABLE", view["error"]["diag"])
        self.assertNotIn("SAMPLE_POSTS_UNREADABLE", view["error"]["desc"] + view["error"]["user"])
        self.assertEqual(state.last_error_code(), "SAMPLE_POSTS_UNREADABLE")

    def test_the_last_error_code_also_sees_a_post_that_could_not_be_read(self):
        provider = post_fake.FakePostsProvider(fail={"load_post": posts.PostFailure(T["post_fail_read"], code="STORE_CORRUPT", kind="corrupt")})
        state = app_state.AppState(posts=provider)
        state.posts.apply_loaded(provider.load_posts(SAFE, NEVER))
        results = {}
        _s, job = state.posts.start_open(row_ids(state.posts)[0], on_error=lambda failure, _p: results.setdefault("failed", failure))
        job.join(10)
        state.posts.apply_detail_failed(results["failed"], None)
        self.assertEqual(state.last_error_code(), "STORE_CORRUPT")
        self.assertIn("STORE_CORRUPT", state.posts_view()["detail"]["error"]["diag"])


class PostsConcurrencyCoreTest(unittest.TestCase):
    def test_a_restore_blocks_every_write_start_and_a_write_blocks_the_restore(self):
        state = app_state.AppState(backups=None, posts=post_fake.FakePostsProvider())
        controller = state.posts
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, row_ids(controller)[0])
        self.assertEqual(controller.save_gate, state.save_blocked, "앱 상태가 복원 중 막기를 이어 준다")
        controller.save_gate = lambda: True
        self.assertEqual(controller.start_import("a", "b"), ("restoring", None))
        self.assertEqual(controller.start_review(posts.PAGES, dict(RAW)), ("restoring", None))
        self.assertEqual(controller.start_approve(), ("restoring", None))
        self.assertEqual(controller.start_revoke(), ("restoring", None))
        self.assertIsNone(controller.open_pages(), "복원 중에는 검토 값 창도 열지 않는다")
        self.assertEqual(controller.approval(), (False, "post_approve_why_restoring"))
        self.assertEqual(controller.provider.calls.count("review_post"), 0)

    def test_the_app_state_counts_a_posts_write_as_busy_for_the_restore(self):
        import threading
        gate = threading.Event()

        class Gated(post_fake.FakePostsProvider):
            def review_post(self, request, progress, cancelled):
                gate.wait(10)
                return super().review_post(request, progress, cancelled)

        provider = Gated()
        state = app_state.AppState(posts=provider)
        state.posts.apply_loaded(provider.load_posts(SAFE, NEVER))
        open_post(state.posts, row_ids(state.posts)[0])
        self.assertFalse(state.writers_busy())
        status, job = state.posts.start_review(posts.PAGES, dict(RAW))
        self.assertEqual(status, "started")
        self.assertTrue(state.writers_busy(), "글 쓰기가 도는 동안 복원은 시작하지 않는다")
        self.assertEqual(state.posts.start_review(posts.NAVER_A), ("busy", None), "쓰기는 한 번에 하나다")
        self.assertEqual(state.posts.approval(), (False, "post_approve_why_busy"))
        gate.set()
        job.join(10)
        self.assertFalse(state.writers_busy())

    def test_reading_and_writing_have_their_own_job_names(self):
        self.assertEqual(len({posts_view.LOAD_KEY, posts_view.DETAIL_KEY, posts_view.FILE_KEY, posts_view.WRITE_KEY}), 4)
        from chanceblog_desktop.ui.core import blogs_view, candidates_view, drafts_view, keys_view, seeds_view
        others = {blogs_view.LOAD_KEY, blogs_view.WRITE_KEY, seeds_view.LOAD_KEY, seeds_view.WRITE_KEY, candidates_view.WRITE_KEY, keys_view.WRITE_KEY, drafts_view.STORE_KEY, app_state.LOAD_KEY, app_state.CONN_KEY}
        self.assertFalse(others & {posts_view.LOAD_KEY, posts_view.DETAIL_KEY, posts_view.FILE_KEY, posts_view.WRITE_KEY}, "다른 화면의 일과 이름이 겹치지 않는다")

    def test_the_menu_has_the_posts_entry_in_the_core_group_after_drafts(self):
        keys = [key for key, _label, _icon in app_state.NAV]
        self.assertEqual(keys, ["home", "topics", "drafts", "posts", "seed", "blogs", "settings"])
        self.assertEqual(app_state.NAV_GROUPS[0][2], ("home", "topics", "drafts", "posts"))
        self.assertEqual(T["nav_posts"], "글 검토")
        self.assertEqual(dict((key, icon) for key, _label, icon in app_state.NAV)["posts"], "check_circle")
        self.assertNotIn("posts", [key for key, _label, _icon in app_state.NEXT_STEPS])


class PostsTextTest(unittest.TestCase):
    KEYS = sorted(key for key in post_text.POST_T)

    def test_every_post_text_is_merged_into_the_screen_table(self):
        for key in self.KEYS:
            self.assertIs(text.T[key], post_text.POST_T[key], key)

    def test_no_promise_words_no_english_codes_no_tilde_and_no_address_in_the_texts(self):
        for key, value in post_text.POST_T.items():
            with self.subTest(key=key):
                for word in text.FORBIDDEN:
                    self.assertNotIn(word, value)
                self.assertNotRegex(value, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
                self.assertNotRegex(value, r"Traceback|Exception|Error\b|테마|다크|Dark|어두운")
                self.assertNotIn(chr(0x7E), value)
                self.assertNotIn("://", value)
                self.assertNotIn("{{", value)

    @unittest.skipUnless((UI_DIR / "qt" / "post_screen.py").exists(), "글 검토 화면 파일(Qt)이 아직 없다 — 화면이 쓰는 글은 화면이 생긴 뒤에 센다")
    def test_every_post_text_is_used_somewhere(self):
        used = "\n".join(path.read_text(encoding="utf-8") for path in UI_DIR.rglob("*.py") if path.name != "post_text.py")            # 소스에서만 센다 — 시험이 이름을 불러 주는 것은 '쓰는 것' 이 아니다
        for key in self.KEYS:
            if key.startswith(("post_status_", "post_platform_", "post_gate_", "post_health_", "post_block_", "post_lang_", "post_naver_similarity_", "post_im_kind_")):
                continue                                                   # 낱말을 이어 붙여 찾는 열쇠들 — 아래 시험이 따로 본다
            self.assertRegex(used, rf'["\']{key}["\']', f"죽은 글: {key}")

    def test_the_keys_that_are_built_from_a_word_are_all_reachable(self):
        for status in service_format.STATUS_KO:
            self.assertIn(f"post_status_{status}", post_text.POST_T)
        for platform in posts.PLATFORMS:
            self.assertIn(f"post_platform_{platform}", post_text.POST_T)
        for stage in ("general", "mark", "evidence", "stop"):
            self.assertIn(posts_view.HEALTH_TEXT[stage], post_text.POST_T)
        for level in ("ok", "warn", "high"):
            self.assertIn(posts_view.SIMILARITY_TEXT[level], post_text.POST_T)
        for kind in rules.KIND_LABEL.values():
            self.assertIn(kind, post_text.POST_T)
        for kind in posts.KINDS:
            self.assertIn(f"post_im_kind_{kind}", post_text.POST_T)
        for lang in posts.LANGS:
            self.assertIn(f"post_lang_{lang}", post_text.POST_T)

    def test_every_kind_of_failure_and_reason_key_the_controller_can_return_has_a_text(self):
        for key in ("post_approve_why_none", "post_approve_why_stale", "post_approve_why_state", "post_approve_why_blocked", "post_approve_why_busy", "post_approve_why_restoring", "post_res_lost"):
            self.assertIn(key, text.T)

    def test_the_nav_label_and_the_screen_title_are_the_same_words(self):
        self.assertEqual(T["nav_posts"], T["post_title"])


class PostsSourceRulesTest(unittest.TestCase):
    WRITES = {"write_text", "write_bytes", "unlink", "mkdir", "rmdir", "rmtree", "copy2", "copyfile", "copytree", "touch", "makedirs", "chmod"}
    CORE = sorted((UI_DIR / "core").glob("post*.py"))
    QT = sorted((UI_DIR / "qt").glob("post*.py"))
    BANNED_IMPORTS = re.compile(r"(^|\.)(socket|subprocess|urllib|http|ssl|requests|ftplib|smtplib|webbrowser|ctypes|multiprocessing|asyncio)(\.|$)")
    BANNED_WORDS = ("PIPELINE_PAUSE", "pages_flow", "naver_flow", "issue_naver_package", "record_naver_published", "check_pages_deploy", "gitrepo", "capabilities", "workflow_dispatch", "keystore")

    def parse(self, path):
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def code_only(self, path):
        """주석과 머리글(docstring)을 뺀 소스 — 설명 글이 금지 낱말을 '쓰지 않는다' 고 말해도 걸리지 않게, 코드(이름·글자열)만 본다."""
        tree = self.parse(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body and isinstance(node.body[0], ast.Expr)                     and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
        return ast.unparse(tree)

    def test_the_files_exist(self):
        self.assertGreaterEqual(len(self.CORE), 5, [path.name for path in self.CORE])

    def test_screen_files_never_import_the_service_or_the_network_or_processes(self):
        for path in self.CORE + self.QT:
            for node in ast.walk(self.parse(path)):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [("." * node.level) + (node.module or "")] + [alias.name for alias in node.names]
                    for name in names:
                        with self.subTest(file=path.name, name=name):
                            self.assertNotRegex(name, r"(^|\.)(service|keystore)(\.|$)")
                            self.assertNotRegex(name, self.BANNED_IMPORTS)
        for path in self.CORE:
            self.assertNotIn("PySide6", self.code_only(path), f"{path.name}: 순수 층은 화면 도구를 모른다")

    def test_screen_files_never_write_files_open_files_or_print(self):
        for path in self.CORE + self.QT:
            for node in ast.walk(self.parse(path)):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else (node.func.id if isinstance(node.func, ast.Name) else "")
                    owner = ast.unparse(node.func.value) if isinstance(node.func, ast.Attribute) else ""
                    with self.subTest(file=path.name, line=node.lineno):
                        self.assertNotIn(name, self.WRITES)
                        self.assertFalse(isinstance(node.func, ast.Name) and node.func.id in ("open", "print", "exec", "eval", "compile", "__import__"))
                        self.assertFalse(name in ("replace", "rename", "remove", "copy", "move", "system", "popen") and owner in ("os", "shutil"))

    def test_screen_files_do_not_mention_the_things_that_leave_this_pc(self):
        for path in self.CORE + self.QT + [UI_DIR / "posts_adapter.py"]:
            body = self.code_only(path)
            for word in self.BANNED_WORDS:
                with self.subTest(file=path.name, word=word):
                    self.assertNotIn(word, body)

    def test_no_screen_file_mentions_an_ai_provider(self):
        for path in self.CORE + self.QT + [UI_DIR / "posts_adapter.py"]:
            body = self.code_only(path).lower()
            for word in ("openai", "anthropic", "gemini", "ai_assist", "llm", "chatgpt"):
                with self.subTest(file=path.name, word=word):
                    self.assertIsNone(re.search(rf"{word}", body), word)

    def test_the_adapter_calls_exactly_these_service_functions_and_nothing_else(self):
        tree = self.parse(UI_DIR / "posts_adapter.py")
        service_aliases = {"own_posts", "project_service", "review_service"}
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in service_aliases:
                calls.add(f"{node.func.value.id}.{node.func.attr}")
        self.assertEqual(calls, {"own_posts.read_own_files", "own_posts.check_pasted_text", "project_service.list_projects", "project_service.show_project", "project_service.new_project",
                                 "project_service.import_html", "review_service.request_review", "review_service.grant_approval", "review_service.revoke_approval"})
        imported = {alias.name if isinstance(node, ast.Import) else f"{node.module}.{alias.name}" for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
        for banned in ("pages_flow", "naver_flow", "external", "capabilities", "gitrepo", "gate", "backup_flow", "doctor"):
            self.assertFalse([name for name in imported if name.endswith(banned) or f".{banned}." in name], banned)


if __name__ == "__main__":
    unittest.main()
