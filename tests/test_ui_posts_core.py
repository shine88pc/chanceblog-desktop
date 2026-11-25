"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)의 순수 부분 시험(PySide6 없이 돈다 — CI 와 같은 조건) — 미리보기·검토 규칙·승인 조건·상태·가져오기·검토·승인 흐름·실패·동시성·문구·소스 규칙.

지키는 것:
  1) 미리보기는 글자만 그리고(글 속 HTML·스크립트는 글자 그대로) 키·토큰 모양은 가린 뒤에 나가며 긴 글은 앞부분만 담는다(M07).
  2) 검토 결과는 발행 전 검사·건강 효과 단정·비밀 모양 세 층이고, **승인은 이 앱을 연 뒤 이 글·이 플랫폼·이 판의 검토 결과를 받았고 막힘이 없고 확인창을 거쳤을 때만** 시작한다(M09·M10·M11·M12). 승인 취소는 검토 중으로 되돌린다(M13).
  3) 가져오기는 실패해도 입력이 남고(칸의 글은 위젯에만 있다), 쓰기는 한 번에 하나이고 복원이 도는 동안 시작하지 않는다.
  4) 상태 글·플랫폼 이름·검사 코드 문장은 서비스와 같고, 문구에 영문 코드·결과 약속 표현이 없다. 화면 층 소스에는 파일 쓰기·네트워크·하위 프로세스가 없다.
가짜 비밀은 조립한 문자열(`CANARY_` 또는 키 모양을 쪼개 이어 붙임)이고 실제 글·블로그 이름은 어디에도 없다.
"""
import ast
import dataclasses
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
from chanceblog_desktop.service.context import Context  # noqa: E402
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

    def test_secret_spots_also_look_at_the_image_names_and_descriptions(self):
        from chanceblog_desktop.content.model import Asset
        keyed = (Asset("a.png", alt=f"설명 {KEY}"),)
        found = rules.secret_spots("제목", "본문", (), keyed)
        self.assertEqual(found, ((T["post_where_assets"], 1, "Google API 키"),), "저장 때 훑는 이미지 칸을 검토에서도 훑는다")
        self.assertNotIn(KEY, repr(found))
        self.assertEqual(rules.text_blocks("제목", "본문", (), keyed), ("secret",), "승인 직전의 재검사도 이미지 칸을 본다")
        self.assertEqual(rules.secret_spots("제목", "본문", (), (Asset("b.png", alt="평범한 설명"),)), ())
        self.assertEqual(rules.secret_spots("제목", "본문", (), None), ())

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
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=general, spots=(("본문", 1, "Google API 키"),))), ("secret",))
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=general, similarity=posts.SimilarityInfo("high", 0.9))), ("similarity",))
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=general, similarity=posts.SimilarityInfo("warn", 0.5))), (), "경고만이면 막지 않는다")
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=None)), ("incomplete",), "건강 판정이 빠진 결과는 믿지 않는다")
        self.assertEqual(rules.review_blocks(None), ("incomplete",))
        self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, gate_ok=False, health=stop, spots=(("본문", 1, "x"),), similarity=posts.SimilarityInfo("high", 1.0))), ("gate", "health", "secret", "similarity"))

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
        for bad in ("", "ht" + "tp://img.example.invalid/a.jpg", "https://", "https:///a", "ftp://x/a", "https://img.example.invalid/a b.jpg", "img.example.invalid/a.jpg", "javascript:alert(1)", "https://" + "a" * 1500):
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

    def test_a_saved_rendering_of_another_revision_is_not_approvable_even_when_the_review_is_of_the_current_revision(self):
        """승인 조건 ⑤ 의 두 번째 절(독립 검증 Q 권고-1): 검토 결과의 판이 지금 판이어도 **저장된 렌더링의 판**이 지금 판이 아니면 승인하지 않는다 — 앞의 시험은 검토 결과의 판만 바꿔 이 절을 지우고도 통과했다."""
        provider = post_fake.FakePostsProvider()
        project_id = long_post(provider)
        out = provider.review_post(posts.ReviewRequest(project_id, posts.PAGES, rules.pages_values_of(RAW)), SAFE, NEVER)
        detail, fresh = out.detail, out.review
        self.assertEqual((fresh.revision, detail.revision), (detail.revision, detail.revision), "검토 결과의 판은 지금 판이다")
        self.assertEqual(rules.approval_state(fresh, detail, posts.PAGES), (True, ""))
        for other in (None, detail.revision + 1, 0):
            changed = dataclasses.replace(detail, platforms=tuple(dataclasses.replace(item, rendered_revision=other) if item.platform == posts.PAGES else item for item in detail.platforms))
            with self.subTest(rendered_revision=other):
                self.assertEqual(rules.approval_state(fresh, changed, posts.PAGES), (False, "post_approve_why_stale"))

    def test_secret_spots_also_look_at_the_references_and_say_only_place_and_kind(self):
        """출처(references)의 키 모양(독립 검증 Q 권고-3): 검토 카드와 승인 직전 재검사가 출처 칸도 훑는다 — 앞의 시험은 키 없는 출처만 넘겨 이 칸을 지우고도 통과했다."""
        keyed = (f"https://example.invalid/page?k={KEY}",)
        found = rules.secret_spots("제목", "본문", keyed)
        self.assertEqual(found, ((T["post_where_refs"], 1, "Google API 키"),))
        self.assertNotIn(KEY, repr(found))
        self.assertEqual(rules.text_blocks("제목", "본문", keyed), ("secret",), "승인 직전의 재검사도 출처 칸을 본다")
        self.assertEqual(rules.secret_spots("제목", "본문", ("https://example.invalid/a", f"https://example.invalid/b?k={KEY}"))[0][1], 2, "줄 번호는 출처 줄 기준이다")
        self.assertEqual(rules.secret_spots("제목", "본문", ("https://example.invalid/a",)), ())
        self.assertEqual(rules.secret_spots("제목", "본문", None), ())

    def test_only_the_stop_stage_blocks_and_the_lower_health_stages_never_do(self):
        """건강 판정의 아래쪽 경계(독립 검증 Q 권고-5): `근거 필요`(evidence)·`표시 권장`(mark) 단계는 승인을 막지 않는다 — 막는 것은 중지(stop)뿐이다. 앞의 시험은 근거 필요 단계까지 막아도 통과했다."""
        base = dict(project_id="x", platform=posts.PAGES, revision=1, status=st.REVIEW_REQUIRED)
        for stage, blocked in (("general", False), ("mark", False), ("evidence", False), ("stop", True)):
            with self.subTest(stage=stage):
                self.assertEqual(rules.review_blocks(posts.ReviewReport(**base, health=rules.HealthReview(stage))), ("health",) if blocked else ())
        for stage, sentence in (("general", "오늘은 산책을 했어요."), ("mark", "피로 회복에 도움이 될 수 있어요."), ("evidence", "당뇨 환자에게 좋은 식단을 소개해요."), ("stop", "이 영양제를 먹으면 통증이 완전히 사라집니다.")):
            with self.subTest(sentence=sentence):
                self.assertEqual(rules.health_of("제목", sentence).stage, stage, "시험 문장이 정말 그 단계다")
                self.assertEqual(rules.text_blocks("제목", sentence), ("health",) if stage == "stop" else ())


class PostsKeyBlockPreviewTest(unittest.TestCase):
    """개인 키 블록(PEM·PGP)은 머리부터 꼬리까지 **한 덩어리로** 가려서 미리보기에 나간다(독립 검증 S 권고-3). 실제 PGP 개인 키는 머리 줄 뒤에 빈 줄이 있고 Markdown 은 빈 줄마다 블록을 나누므로,
    블록마다 따로 가리면 머리 줄만 가려지고 본문 줄이 미리보기에 그대로 나갔다. 가짜 키 본문은 `CANARY_` 로 시작하는 조립 문자열이다."""
    PGP = ("-----BEGIN " + "PGP PRIVATE KEY BLOCK-----", "-----END " + "PGP PRIVATE KEY BLOCK-----")
    RSA = ("-----BEGIN " + "RSA PRIVATE KEY-----", "-----END " + "RSA PRIVATE KEY-----")
    ONE, TWO = "CANARY_" + "KEYBODY_ONE_" + "A" * 24, "CANARY_" + "KEYBODY_TWO_" + "B" * 24

    def blocks(self, markdown):
        found = rules.build_preview(markdown)
        return found, [block.text for block in found.blocks]

    def assert_hidden(self, markdown, shown):
        joined = "\n".join(shown)
        for piece in (self.ONE, self.TWO, "Version: 가짜", self.ONE[:14]):
            self.assertNotIn(piece, joined, f"키 본문이 미리보기에 그대로 나갔다: {piece[:14]}")

    def test_a_pgp_key_split_by_blank_lines_is_hidden_from_head_to_tail_as_one_piece(self):
        head, tail = self.PGP
        markdown = f"앞 글\n\n{head}\nVersion: 가짜\n\n{self.ONE}\n\n{self.TWO}\n{tail}\n\n뒤 글"
        found, shown = self.blocks(markdown)
        self.assert_hidden(markdown, shown)
        self.assertEqual([shown[0], shown[-1], len(shown)], ["앞 글", "뒤 글", 3], "앞 글·가려진 덩어리 하나·뒤 글")
        self.assertIn("가림", shown[1])
        self.assertEqual((found.total, found.chars), (3, len(re.sub(r"\s+", "", markdown))), "묶은 덩어리는 한 블록으로 세고 글자 수는 글 그대로다")
        self.assertFalse(found.cut)

    def test_every_private_key_label_is_hidden_the_same_way_with_blank_lines_inside(self):
        for label in ("", "RSA ", "EC ", "DSA ", "OPENSSH ", "ENCRYPTED ", "PGP "):
            head = "-----BEGIN " + label + "PRIVATE KEY" + (" BLOCK" if label == "PGP " else "") + "-----"
            tail = "-----END " + label + "PRIVATE KEY" + (" BLOCK" if label == "PGP " else "") + "-----"
            markdown = f"{head}\n\n{self.ONE}\n\n{self.TWO}\n\n{tail}"
            with self.subTest(label=label):
                found, shown = self.blocks(markdown)
                self.assert_hidden(markdown, shown)
                self.assertEqual((found.total, len(shown)), (1, 1))
                self.assertIn("가림", shown[0])

    def test_a_head_without_a_tail_hides_everything_after_it_but_keeps_what_comes_before(self):
        head, _tail = self.RSA
        markdown = f"앞 글\n\n{head}\n\n{self.ONE}\n\n뒤에 이어지는 글\n\n- 목록 항목\n\n> 인용 글"
        found, shown = self.blocks(markdown)
        self.assert_hidden(markdown, shown)
        self.assertEqual(shown[0], "앞 글")
        self.assertEqual((len(shown), found.total), (2, 2))
        self.assertNotIn("뒤에 이어지는 글", "\n".join(shown), "꼬리가 없으면 머리 뒤 글 전부를 가린다(엔진의 규칙과 같다 — 의심스러우면 내보내지 않는다)")
        self.assertGreater(found.chars, len(re.sub(r"\s+", "", "앞 글" + head + self.ONE)), "가려진 글자도 글자 수에는 센다(글 그대로의 크기를 알린다)")

    def test_the_head_in_a_heading_and_the_body_in_a_list_and_a_quote_are_hidden_too(self):
        head, tail = self.RSA
        markdown = f"## {head}\n\n- {self.ONE}\n- {self.TWO}\n\n> 인용 {self.ONE}\n\n{tail}\n\n뒤 글"
        found, shown = self.blocks(markdown)
        self.assert_hidden(markdown, shown)
        self.assertEqual([block.kind for block in found.blocks], ["heading", "paragraph"], "묶은 덩어리의 종류는 머리가 든 블록의 종류다")
        self.assertEqual((shown[1], found.total), ("뒤 글", 2))

    def test_one_blank_line_several_lines_with_several_blank_lines_and_a_head_without_a_tail_are_each_hidden(self):
        """지시서가 든 세 모양을 따로 못박는다(독립 검증 S 권고-3): 머리 줄 뒤에 빈 줄 하나 · 본문이 여러 줄이고 빈 줄이 여럿 · 머리만 있고 꼬리가 없다."""
        head, tail = self.PGP
        shapes = (("빈 줄 하나", f"{head}\n\n{self.ONE}\n{tail}"),
                  ("여러 줄·여러 빈 줄", f"{head}\n\n\n{self.ONE}\n{self.TWO}\n\n{self.ONE}\n\n\n{self.TWO}\n{tail}"),
                  ("머리만(꼬리 없음)", f"{head}\n\n{self.ONE}\n\n{self.TWO}"))
        for name, key in shapes:
            with self.subTest(shape=name):
                markdown = f"앞 글\n\n{key}"
                found, shown = self.blocks(markdown)
                self.assert_hidden(markdown, shown)
                self.assertEqual(shown[0], "앞 글")
                self.assertIn("가림", shown[1])
                self.assertEqual((len(shown), found.total), (2, 2))

    def test_text_between_two_keys_and_before_the_head_and_after_the_tail_stays_visible(self):
        pgp_head, pgp_tail = self.PGP
        rsa_head, rsa_tail = self.RSA
        markdown = (f"설명 앞 {pgp_head}\n\n{self.ONE}\n\n{pgp_tail} 설명 뒤\n\n가운데 글이에요.\n\n{rsa_head}\n\n{self.TWO}\n\n{rsa_tail}\n\n마지막 글이에요.")
        found, shown = self.blocks(markdown)
        self.assert_hidden(markdown, shown)
        self.assertEqual(len(shown), 4)
        self.assertTrue(shown[0].startswith("설명 앞") and shown[0].endswith("설명 뒤"), shown[0])
        self.assertIn("가림", shown[0])
        self.assertEqual((shown[1], shown[3]), ("가운데 글이에요.", "마지막 글이에요."))
        self.assertIn("가림", shown[2])

    def test_a_tail_line_alone_is_just_text_and_hides_nothing(self):
        _head, tail = self.PGP
        found, shown = self.blocks(f"앞 글\n\n{tail}\n\n뒤 글")
        self.assertEqual(shown, ["앞 글", tail, "뒤 글"])
        self.assertEqual(found.total, 3)

    def test_the_open_state_agrees_with_what_the_masking_engine_hides(self):
        """머리·꼬리를 찾는 이 규칙이 가리기 엔진과 어긋나지 않는다 — 글 뒤에 표지를 붙여 엔진에 가려 보고 표지가 사라지면(머리부터 글 끝까지 가렸다) 아직 열려 있는 것이다."""
        pgp_head, pgp_tail = self.PGP
        rsa_head, rsa_tail = self.RSA
        snippets = ("평범한 글이에요.", pgp_head, f"{pgp_head}\n{self.ONE}", f"{pgp_head}\n{self.ONE}\n{pgp_tail}", pgp_tail, f"{pgp_tail}\n{pgp_head}", f"{pgp_head} {pgp_tail} {pgp_head}",
                    f"{rsa_head} x {pgp_head} y {rsa_tail} z", f"{pgp_head}\n{pgp_tail}\n{pgp_head}\n{pgp_tail}", f"{rsa_head} {rsa_tail} 뒤 글 {pgp_head}")
        for snippet in snippets:
            with self.subTest(snippet=snippet[:48]):
                hidden_to_the_end = "ZZENDZZ" not in text.display_text(snippet + " ZZENDZZ", 10_000)
                self.assertEqual(rules._key_open_after(snippet, False), hidden_to_the_end)
        self.assertEqual(rules._key_open_after(f"{self.ONE}\n{pgp_tail}", True), False, "열린 채 들어와 꼬리를 만나면 닫힌다")
        self.assertEqual(rules._key_open_after(self.ONE, True), True, "열린 채 들어와 꼬리가 없으면 계속 열려 있다")

    # ---- 독립 검증 S 2차 필수 N1·권고 R1 — 열림 판정과 원문 가리기를 엔진에 맡긴다 ----------------------------------------------------------------------------
    INVISIBLE = (("소프트 하이픈", 0xAD), ("결합 서자 연결자", 0x34F), ("아랍 글자 표지", 0x61C), ("한글 초성 채움", 0x115F), ("크메르 내재 모음", 0x17B4), ("몽골 모음 구분", 0x180E), ("폭 없는 공백", 0x200B),
                 ("폭 없는 비연결자", 0x200C), ("폭 없는 연결자", 0x200D), ("왼쪽에서 오른쪽 표지", 0x200E), ("오른쪽에서 왼쪽 덮어쓰기", 0x202E), ("워드 조이너", 0x2060), ("보이지 않는 곱", 0x2062), ("점자 빈칸", 0x2800),
                 ("한글 채움", 0x3164), ("변형 선택자 16", 0xFE0F), ("바이트 순서 표지", 0xFEFF), ("반각 한글 채움", 0xFFA0), ("줄 구분 글자", 0x2028), ("문단 구분 글자", 0x2029), ("태그 글자", 0xE0041), ("C1 제어 글자", 0x85),
                 ("제어 글자 하나", 0x01))

    def head_shapes(self, z):
        """머리 줄(PGP) 글자 사이 일곱 곳에 눈에 안 보이는 글자 `z` 를 끼운 모양들 — 엔진은 먼저 지우고 머리로 알아본다."""
        return (("BEGIN 안", "-----BEG" + z + "IN PGP PRIVATE KEY BLOCK-----"), ("BEGIN 뒤", "-----BEGIN" + z + " PGP PRIVATE KEY BLOCK-----"), ("PRIVATE 안", "-----BEGIN PGP PRIV" + z + "ATE KEY BLOCK-----"),
                ("KEY 안", "-----BEGIN PGP PRIVATE K" + z + "EY BLOCK-----"), ("대시 안", "--" + z + "---BEGIN PGP PRIVATE KEY BLOCK-----"), ("맨 앞", z + "-----BEGIN PGP PRIVATE KEY BLOCK-----"),
                ("라벨 낱말 안", "-----BEGIN PG" + z + "P PRIVATE KEY BLOCK-----"))

    def engine_open(self, snippet, inside):
        """시험 쪽의 독립 판정 — 엔진(`display_text`)에 글과 끝 표지를 먹여 표지가 사라졌는지(머리부터 글 끝까지 가렸는지). 이미 열린 채 들어오는 조각은 앞에 가짜 머리 한 줄을 붙인다."""
        probe = (self.RSA[0] + "\n" if inside else "") + snippet + "\nZZENDZZ"
        return "ZZENDZZ" not in text.display_text(probe, 10 * len(probe))

    def assert_three_blocks(self, markdown):
        """앞 글 · 가려진 덩어리 하나 · 뒤 글 — 키 본문은 어느 것에도 없다."""
        found, shown = self.blocks(markdown)
        self.assert_hidden(markdown, shown)
        self.assertEqual((shown[0], shown[-1], len(shown), found.total), ("앞 글", "뒤 글", 3, 3))

    def test_a_head_with_an_invisible_character_inside_is_hidden_the_way_the_masking_engine_hides_it(self):
        """필수 N1: 머리 글자 사이에 눈에 안 보이는 글자가 끼면 엔진은 먼저 지우고 머리로 알아봐 본문을 가리는데, 정규식으로 머리를 찾던 미리보기는 못 알아보고 키 본문을 그대로 내보냈다(23종 × 일곱 곳)."""
        tail = self.PGP[1]
        for name, code in self.INVISIBLE:
            for where, head in self.head_shapes(chr(code)):
                markdown = f"앞 글\n\n{head}\nVersion: 가짜\n\n{self.ONE}\n\n{self.TWO}\n{tail}\n\n뒤 글"
                with self.subTest(character=name, where=where):
                    self.assertNotIn(self.ONE, text.display_text(markdown, 100_000), "시험 표본이 정말 엔진이 가리는 모양이다")
                    self.assert_three_blocks(markdown)

    def test_a_head_label_of_any_length_is_hidden_the_way_the_masking_engine_hides_it(self):
        """필수 N1: 엔진의 머리 라벨(`[A-Z ]*`)에는 길이 한도가 없다 — 라벨이 101자이거나 낱말이 쉰 개여도 엔진은 머리로 알아본다. 미리보기도 길이로 놓치지 않는다."""
        tail = "-----END " + "PRIVATE KEY-----"
        shapes = [(f"라벨 {n}자", "-----BEGIN " + "A" * n + " PRIVATE KEY-----") for n in (1, 99, 100, 101, 102, 150, 2000)]
        shapes += [("낱말 50개", "-----BEGIN " + "AB " * 50 + "PRIVATE KEY-----"), ("낱말 400개(블록)", "-----BEGIN " + "AB " * 400 + "PRIVATE KEY BLOCK-----")]
        for name, head in shapes:
            markdown = f"앞 글\n\n{head}\n\n{self.ONE}\n\n{self.TWO}\n\n{tail}\n\n뒤 글"
            with self.subTest(label=name):
                self.assertNotIn(self.ONE, text.display_text(markdown, 100_000), "시험 표본이 정말 엔진이 가리는 모양이다")
                self.assert_three_blocks(markdown)

    def test_the_open_state_follows_the_engine_for_invisible_characters_and_long_labels_in_both_directions(self):
        """`_key_open_after` 는 엔진이 가리는 대로 따라간다 — 눈에 안 보이는 글자 23종 × 일곱 곳과 라벨 길이, 닫힌 채 들어올 때와 열린 채 들어올 때 모두(표본은 엔진을 시험 쪽 표지 탐침으로 독립으로 읽는다)."""
        tail = self.PGP[1]
        shapes = [(f"{name}:{where}", head) for name, code in self.INVISIBLE for where, head in self.head_shapes(chr(code))]
        shapes += [(f"라벨 {n}자", "-----BEGIN " + "A" * n + " PRIVATE KEY-----") for n in (99, 100, 101, 150, 2000)] + [("낱말 50개", "-----BEGIN " + "AB " * 50 + "PRIVATE KEY-----")]
        for name, head in shapes:
            for label, snippet in (("머리만", head), ("머리와 본문", f"{head}\n{self.ONE}"), ("머리·본문·꼬리", f"{head}\n{self.ONE}\n{tail}"), ("꼬리 뒤 머리", f"{tail}\n{head}\n{self.TWO}"), ("본문과 꼬리", f"{self.ONE}\n{tail}")):
                for inside in (False, True):
                    with self.subTest(shape=name, snippet=label, inside=inside):
                        self.assertEqual(rules._key_open_after(snippet, inside), self.engine_open(snippet, inside))

    def test_a_head_the_converter_would_drop_or_a_tail_it_would_imitate_does_not_let_a_key_body_show_that_the_engine_hides(self):
        """권고 R1: 변환기는 이미지 설명·이미지와 링크 제목·울타리 이름 줄의 글을 버리고, 강조·링크·이미지로 꼬리를 흉내 낼 수 있으며, 줄 구분 글자(U+0085·U+2028·U+2029)로 줄을 나눈다 — 변환된 글에서 머리를 찾으면 엔진(원문)과 어긋난다.
        미리보기는 변환 전에 엔진이 원문에서 가리는 줄을 먼저 가려서 그 차이가 키 본문을 내보내지 않게 한다."""
        head, tail = self.RSA
        one, two = self.ONE, self.TWO
        shapes = {"울타리 이름 줄": f"```{head}\n{one}\n\n{two}\n```\n\n{tail}", "이미지 설명": f"![{head}](https://x.invalid/a.png)\n\n{one}\n\n{two}\n\n{tail}",
                  "이미지 제목": f'![그림](https://x.invalid/a.png "{head}")\n\n{one}\n\n{two}\n\n{tail}', "링크 제목": f'[글](https://x.invalid/a "{head}")\n\n{one}\n\n{two}\n\n{tail}',
                  "링크 글": f"[{head}](https://x.invalid/a)\n\n{one}\n\n{two}\n\n{tail}", "코드 한 줄": f"`{head}`\n\n{one}\n\n{two}\n\n{tail}"}
        for look in ("_RSA_", "*RSA*", "**RSA**", "`RSA`", "[RSA](https://x.invalid/a)", "![x](https://x.invalid/a.png)"):
            shapes[f"꼬리 흉내 {look}"] = f"{head}\n\n{one}\n\n-----END {look} PRIVATE KEY-----\n\n{two}"
        for code in (0x85, 0x2028, 0x2029):
            sep = chr(code)
            shapes[f"줄 구분 글자 U+{code:04X}"] = f"{head}{sep}{sep}{one}{sep}{two}{sep}{tail}"
            shapes[f"줄 구분 글자 U+{code:04X}(머리 안)"] = f"-----BEG{sep}IN RSA PRIVATE KEY-----\n\n{one}\n\n{two}"
        for name, body in shapes.items():
            markdown = f"앞 글\n\n{body}"
            with self.subTest(shape=name):
                engine = text.display_text(markdown, 100_000)
                hidden = [token for token in (one, two) if token not in engine]
                self.assertTrue(hidden, "시험 표본이 정말 엔진이 가리는 모양이다")
                _found, shown = self.blocks(markdown)
                for token in hidden:
                    self.assertNotIn(token, "\n".join(shown), "엔진이 원문에서 가리는 키 본문이 미리보기에 나갔다")
                self.assertEqual(shown[0], "앞 글")

    def test_a_head_the_converter_makes_is_still_grouped_after_the_hiding_of_the_source_lines(self):
        """변환기가 **만드는** 머리(역슬래시로 쓴 붙임표·강조로 쓴 라벨)는 원문에서 엔진이 못 알아봐 원문 가리기가 지나치므로, 변환된 글에서 찾는 한 덩어리 묶기가 그 뒤를 맡는다."""
        tail = self.RSA[1]
        escaped = "".join(chr(92) + char if char == "-" else char for char in self.RSA[0])
        for name, head in (("역슬래시 붙임표", escaped), ("강조 라벨", "-----BEGIN *RSA* PRIVATE KEY-----")):
            with self.subTest(shape=name):
                self.assertEqual(rules._hide_key_lines(head), head, "원문에서는 엔진이 머리로 보지 않아 그대로다")
                self.assert_three_blocks(f"앞 글\n\n{head}\n\n{self.ONE}\n\n{self.TWO}\n\n{tail}\n\n뒤 글")

    def test_the_probe_mark_is_one_the_text_does_not_contain_and_a_text_with_every_candidate_counts_as_open(self):
        """엔진에 붙여 묻는 표지가 글에 이미 있으면 머리가 글 끝까지 가려도 앞쪽의 같은 낱말이 남아 '닫혔다' 로 잘못 읽는다 — 표지는 글에 없는 후보로 고르고, 후보가 모두 글에 있으면 물을 수 없으니 열려 있다고 본다(더 많이 가리는 쪽)."""
        head, tail = self.RSA
        for mark in rules._PROBE_MARKS:
            with self.subTest(mark=mark):
                self.assertTrue(rules._key_open_after(f"{mark} 앞 글\n{head}\n{self.ONE}", False), "글 속에 표지 후보가 있어도 열린 키를 닫혔다고 읽지 않는다")
                self.assertTrue(rules._key_open_after(f"{mark} {self.ONE}\n{tail} 뒤 {head}", True), "열린 채 들어와도 마찬가지다")
        everything = " ".join(rules._PROBE_MARKS)
        self.assertTrue(rules._key_open_after(f"{everything}\n{head}\n{self.ONE}", False))
        self.assertTrue(rules._key_open_after(f"{everything} 평범한 글에 BEGIN 이라는 낱말만", False), "후보가 모두 글에 있으면 물을 수 없으니 열려 있다고 본다(더 많이 가리는 쪽)")

    def test_the_probe_relies_on_two_facts_about_the_engine_and_they_are_pinned_here(self):
        """① 사전 거름(보이는 ASCII 밖의 글자를 모두 지운다)이 엔진보다 느슨하다 — 엔진은 보이는 ASCII 를 하나도 안 지운다. ② 엔진에 붙여 묻는 세 글자 표지는 평범한 글 뒤는 물론 비밀 이름 뒤 줄에서도 가려지지 않는다
        (가려지면 닫힌 키를 열린 것으로 읽어 더 많이 가릴 뿐 새지는 않지만, 가려지지 않는다는 것이 이 판정의 바탕이다). 엔진이 바뀌어 둘 중 하나가 깨지면 이 시험이 알린다."""
        from chanceblog_desktop.security import mask as engine
        printable = "".join(chr(code) for code in range(0x20, 0x7F))
        self.assertEqual(engine._strip_invisible(printable), printable)
        self.assertEqual(rules._NON_ASCII.sub("", "".join(chr(code) for code in range(0x80))), printable)
        for lead in ("", "앞 글", "token:", "password=", "Bearer", "Authorization:", "key=", "api_key =", "Cookie:", "https://user:pw@host/path?token=", "sk-", "ghp_"):
            for mark in rules._PROBE_MARKS:
                with self.subTest(lead=lead, mark=mark):
                    self.assertIn(mark, text.display_text(f"{lead}\n{mark}", 1000))

    def test_only_a_private_key_tail_closes_the_block_and_only_a_private_key_head_opens_it(self):
        """독립 검증 Q 2차 권고-3: 엔진은 개인 키 꼬리(`END … PRIVATE KEY`)만 꼬리로, 개인 키 머리만 머리로 본다 — 공개 키·인증서·서명 같은 다른 종류의 END 줄은 열린 블록을 닫지 않고, 다른 종류의 BEGIN 줄은 열지 않는다.
        (꼬리를 아무 END 줄로 읽도록 바뀌면 미리보기는 닫혔다고 보고 뒤 블록을 내보내는데 엔진은 글 끝까지 가린다.)"""
        head = self.PGP[0]
        other_tails = ["-----END " + kind + "-----" for kind in ("CERTIFICATE", "PGP SIGNATURE", "PGP PUBLIC KEY BLOCK", "PUBLIC KEY", "RSA PUBLIC KEY", "PGP MESSAGE", "CERTIFICATE REQUEST", "X509 CRL", "PRIVATE KEYS")]
        for tail in other_tails:
            with self.subTest(tail=tail):
                self.assertTrue(self.engine_open(f"{head}\n{self.ONE}\n{tail}", False), "시험 표본이 정말 엔진은 닫지 않는 꼬리다")
                self.assertTrue(rules._key_open_after(f"{head}\n{self.ONE}\n{tail}", False))
                self.assertTrue(rules._key_open_after(f"{self.ONE}\n{tail}", True), "열린 채 들어와도 다른 종류의 꼬리는 닫지 않는다")
                found, shown = self.blocks(f"앞 글\n\n{head}\n\n{self.ONE}\n\n{tail}\n\n{self.TWO}\n\n뒤 글")
                self.assert_hidden("", shown)
                self.assertEqual((shown[0], len(shown), "뒤 글" in "\n".join(shown)), ("앞 글", 2, False), "닫히지 않았으니 글 끝까지 가린다")
        other_heads = ["-----BEGIN " + kind + "-----" for kind in ("PUBLIC KEY", "CERTIFICATE", "PGP PUBLIC KEY BLOCK", "RSA PUBLIC KEY", "PGP SIGNATURE", "PGP MESSAGE", "PRIVATE KEYS")]
        for other in other_heads:
            with self.subTest(head=other):
                self.assertFalse(self.engine_open(f"{other}\n{self.ONE}", False), "시험 표본이 정말 엔진이 열지 않는 머리다")
                self.assertFalse(rules._key_open_after(f"{other}\n{self.ONE}", False))
                found, shown = self.blocks(f"앞 글\n\n{other}\n\n{self.ONE}\n\n뒤 글")
                self.assertEqual((shown[0], shown[-1], len(shown)), ("앞 글", "뒤 글", 4), "열리지 않았으니 아무것도 가리지 않는다")
                self.assertIn(self.ONE, "\n".join(shown))

    def test_a_tail_the_converter_drops_or_breaks_does_not_close_the_key_in_the_preview(self):
        """원문 엔진은 닫힌 것으로 보지만 변환기가 꼬리를 버리거나(이미지 설명·제목·울타리 이름 줄) 줄 구분 글자로 깨면 화면에 나가는 글에서는 꼬리가 없다 — 두 눈 중 하나라도 열려 있다고 하면 열려 있는 것으로 가린다(더 많이 가리는 쪽)."""
        head, tail = self.RSA
        shapes = {"이미지 설명 속 꼬리": f"![{tail}](https://x.invalid/a.png)", "이미지 제목 속 꼬리": f'![그림](https://x.invalid/a.png "{tail}")', "링크 제목 속 꼬리": f'[글](https://x.invalid/a "{tail}")',
                  "울타리 이름 줄 속 꼬리": f"```{tail}\n```"}
        for code in (0x85, 0x2028, 0x2029):
            shapes[f"줄 구분 글자 U+{code:04X} 로 깨진 꼬리"] = "-----END RSA PRIV" + chr(code) + "ATE KEY-----"
        for name, closing in shapes.items():
            markdown = f"앞 글\n\n{head}\n\n{self.ONE}\n\n{closing}\n\n{self.TWO}\n\n뒤 글"
            with self.subTest(shape=name):
                engine = text.display_text(markdown, 100_000)
                self.assertIn(self.TWO, engine, "시험 표본이 정말 원문 엔진은 닫힌 것으로 보는 모양이다")
                found, shown = self.blocks(markdown)
                self.assert_hidden(markdown, shown)
                self.assertEqual((shown[0], len(shown)), ("앞 글", 2), "앞 글 하나와 가려진 덩어리 하나 — 화면에 나가는 글에는 꼬리가 없으니 글 끝까지 가린다")

    def test_hide_key_lines_replaces_what_the_engine_hides_line_by_line_and_leaves_everything_else(self):
        head, tail = self.RSA
        marker = text.display_text(head)
        self.assertIn(marker[:1], "[", "엔진이 개인 키 블록 자리에 쓰는 표지를 엔진에게 물어 얻는다")
        plain = "그냥 글\n\n- 목록\n> 인용\n    들여쓴 줄\nBEGIN 이라는 낱말과 END 라는 낱말\n" + tail
        self.assertEqual(rules._hide_key_lines(plain), plain, "머리가 없으면 글 그대로(꼬리만 있는 글도)")
        self.assertEqual(rules._hide_key_lines(f"앞 {head} 가운데 {tail} 뒤"), f"앞 {marker} 뒤", "한 줄 안에서 닫히면 앞뒤 글이 남는다")
        multi = f"앞\n\n{head}\nVersion: 가짜\n\n{self.ONE}\n{tail} 뒤 글\n\n끝"
        self.assertEqual(rules._hide_key_lines(multi), f"앞\n\n{marker}\n뒤 글\n\n끝", "머리 줄은 표지로, 안쪽 줄은 지우고, 꼬리 줄은 꼬리 뒤 글만")
        self.assertEqual(rules._hide_key_lines(f"앞\n{head}\n\n{self.ONE}\n끝"), f"앞\n{marker}", "꼬리가 없으면 글 끝까지")
        self.assertEqual(rules._hide_key_lines(f"{head}\n{self.ONE}\n{tail} 중간 {head}\n{self.TWO}\n끝"), f"{marker}\n중간 {marker}", "닫힌 줄에서 다시 열린다")
        self.assertEqual(rules._hide_key_lines(f"> {head}\n> {self.ONE}\n> {tail}\n\n뒤"), f"> {marker}\n\n뒤", "인용 기호는 머리 줄에 남는다")
        for sample in (multi, f"앞 {head} 가운데 {tail} 뒤", f"앞\n{head}\n\n{self.ONE}\n끝"):
            self.assertEqual(rules._hide_key_lines(rules._hide_key_lines(sample)), rules._hide_key_lines(sample), "두 번 해도 같다")
        self.assertNotIn(self.ONE, rules._hide_key_lines(f"{head}{chr(0x2028)}{self.ONE}{chr(0x2028)}{tail}\n뒤 글"), "줄 구분 글자로 이은 키도 한 줄로 읽어 가린다")

    def test_the_preview_shows_nothing_the_masking_engine_hides_in_the_source_or_in_the_converted_text_for_random_documents(self):
        """무작위 문서(독립 검증 S 의 무작위 탐침과 같은 모양)에서도 엔진이 원문에서 가리는 토큰과 엔진이 변환된 글에서 가리는 토큰은 미리보기에 나가지 않는다(두 눈 중 하나라도 가리면 가린다) — 머리·꼬리·본문·눈에 안 보이는 글자·긴 라벨·인용·목록·울타리·이미지 설명을 섞는다."""
        import random
        from chanceblog_desktop.render.markdown import markdown_blocks
        invisible = [chr(0xAD), chr(0x200B), chr(0x2060), chr(0xFEFF), chr(0x2028), chr(0xE0041)]
        heads = [self.RSA[0], self.PGP[0], "-----BEGIN " + "PRIVATE KEY-----", "-----BEGIN " + "A" * 130 + " PRIVATE KEY-----", "-----BEGIN " + "AB " * 60 + "PRIVATE KEY BLOCK-----"]
        tails = [self.RSA[1], self.PGP[1], "-----END " + "PRIVATE KEY-----", "-----END *RSA* PRIVATE KEY-----", "-----END ![x](https://x.invalid/a.png) PRIVATE KEY-----"]
        spacing = ["", "\n", "\n\n", "\n\n\n", "\n \n", "\r\n\r\n", "\n\t\n", "\n\n"]
        for seed in range(250):
            rng = random.Random(seed)
            pieces, tokens = [], []
            for index in range(rng.randint(3, 12)):
                kind = rng.choice(["head", "head", "invisible-head", "tail", "body", "body", "text", "heading", "list", "quote", "fence", "image", "rule", "mixed"])
                token = f"CANARY_FZ{seed:04d}X{index:02d}Q"
                line = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw" + token
                head, tail = rng.choice(heads), rng.choice(tails)
                if kind == "head":
                    pieces.append(rng.choice(["", "> ", "- ", "1. ", "# ", "   "]) + head)
                elif kind == "invisible-head":
                    cut = rng.randint(2, 14)
                    pieces.append(head[:cut] + rng.choice(invisible) + head[cut:])
                elif kind == "tail":
                    pieces.append(rng.choice(["", "> ", "- "]) + tail)
                elif kind == "body":
                    pieces.append(rng.choice(["", "", "> ", "- ", "   ", "1. "]) + line)
                    tokens.append(token)
                elif kind == "text":
                    pieces.append("보통 글 문단 " + str(index))
                elif kind == "heading":
                    pieces.append("## 소제목 " + str(index))
                elif kind == "list":
                    pieces.append("- 항목 " + line + "\n- 둘째 항목")
                    tokens.append(token)
                elif kind == "quote":
                    pieces.append("> 인용 " + line)
                    tokens.append(token)
                elif kind == "fence":
                    pieces.append(rng.choice(["```", "```" + head]) + "\n" + line + "\n```")
                    tokens.append(token)
                elif kind == "image":
                    pieces.append("![" + rng.choice([head, "그림", tail]) + "](https://x.invalid/a.png)")
                elif kind == "rule":
                    pieces.append("---")
                else:
                    pieces.append(head + "\n" + line + "\n" + tail)
                    tokens.append(token)
            markdown = "".join(piece + rng.choice(spacing) for piece in pieces)
            with self.subTest(seed=seed):
                engine = text.display_text(markdown, 4 * len(markdown) + 256)
                converted = "\n\n".join(plain for _kind, plain in rules._entries_of(markdown_blocks(markdown)[0]))
                engine_converted = text.display_text(converted, 4 * len(converted) + 256)
                shown = "\n".join(block.text for block in rules.build_preview(markdown).blocks)
                for token in tokens:
                    if token not in engine:
                        self.assertNotIn(token, shown, "엔진이 원문에서 가리는 토큰이 미리보기에 나갔다")
                    if token not in engine_converted:
                        self.assertNotIn(token, shown, "엔진이 변환된 글에서 가리는 토큰이 미리보기에 나갔다")

    def test_a_piece_too_big_to_ask_the_engine_is_probed_by_its_head_and_tail_lines_and_one_huge_line_counts_as_open(self):
        """엔진은 20만 자에서 글을 자르므로(끝 표지가 잘려 나가 '열려 있다' 로 잘못 읽는다) 15만 자가 넘는 조각은 머리·꼬리가 있을 수 있는 줄만 모아 묻는다. 줄 하나가 그만큼 길면 물을 수 없으니 열려 있다고 본다(더 많이 가리는 쪽)."""
        head, tail = self.RSA
        filler = "\n".join(f"채움 줄 {number}" for number in range(25_000))
        self.assertGreater(len(filler), rules._PROBE_LIMIT)
        self.assertFalse(rules._key_open_after(filler, False), "머리가 없으면 닫힌 채")
        self.assertTrue(rules._key_open_after(filler, True), "꼬리가 없으면 열린 채")
        self.assertTrue(rules._key_open_after(f"{filler}\n{head}\n{self.ONE}", False))
        self.assertFalse(rules._key_open_after(f"{filler}\n{head}\n{self.ONE}\n{tail}\n{filler}", False), "큰 조각 안에서 닫힌 키는 닫힌 것으로 읽는다")
        self.assertTrue(rules._key_open_after(f"{filler}\n{tail}\n{head}\n{filler}", True), "닫혔다가 다시 열린다")
        self.assertFalse(rules._key_open_after(f"{filler}\n{tail}\n{filler}", True))
        self.assertTrue(rules._key_open_after("가" * (rules._PROBE_LIMIT + 10) + head, False), "줄 하나가 물을 수 없을 만큼 길면 열려 있다고 본다")
        self.assertTrue(rules._key_open_after("가" * (rules._PROBE_LIMIT + 10) + tail, True), "열린 채 들어온 물을 수 없는 줄은 계속 열려 있다")
        self.assertFalse(rules._key_open_after("가" * (rules._PROBE_LIMIT + 10), False), "머리 낱말이 없으면 크기와 상관없이 묻지 않고 닫힌 채")

    def test_chars_and_images_count_the_whole_text_even_when_the_key_lines_are_hidden_first(self):
        head, tail = self.RSA
        markdown = f"![그림 하나](https://x.invalid/a.png)\n\n앞 글\n\n{head}\n![그림 둘](https://x.invalid/b.png)\n\n{self.ONE}\n{tail}\n\n뒤 글"
        found, shown = self.blocks(markdown)
        self.assert_hidden(markdown, shown)
        self.assertEqual((found.images, found.total), (2, 3), "가린 줄 속의 이미지도 이미지 수에 센다")
        self.assertEqual(found.chars, len(re.sub(r"\s+", "", "앞 글" + head + self.ONE + tail + "뒤 글")), "글자 수는 글 그대로의 크기다")


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

    def test_the_open_post_never_shows_a_key_shaped_title_in_its_header(self):
        """글 상세 머리의 제목은 컨트롤러가 가리는 유일한 곳이다(독립 검증 Q 권고-4) — 목록의 제목만 시험이 지켜 이 줄의 가리기를 지워도 통과했다."""
        controller = make("empty")
        project_id = controller.provider.add_post("제목 " + KEY, post_fake.sample_text())
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        view = controller.view()
        header = view["detail"]["title"]
        self.assertIn("가림", header, "가려졌다는 표지가 보인다")
        for piece in (KEY, KEY[:12], KEY[-12:]):
            self.assertNotIn(piece, repr(view), "상세 화면 뷰모델 어디에도 키 글이 없다")
        self.assertNotIn(KEY[:12], controller.notice[1] if controller.notice else "")

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
        self.assertEqual(open_post(controller, project_id), "gone", "그 글을 다시 읽으니 없다")
        view = controller.view()
        self.assertEqual((view["mode"], view["notice"]), ("list", {"level": "warning", "text": T["post_detail_gone"]}))
        self.assertEqual(open_post(make(), "exm99999"), "unknown")
        late = make("empty")                                                   # 늦게 온 옛 목록이 방금 가져온 글을 닫지 않는다
        stale = late.provider.load_posts(SAFE, NEVER)
        late.open_import()
        drive(late, lambda **cb: late.start_import("방금 가져온 글", post_fake.sample_text(), **cb))
        late.apply_loaded(stale)
        self.assertEqual((late.view()["mode"], late.view()["detail"]["title"]), ("detail", "방금 가져온 글"))

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
        self.assertEqual(controller.request_close_import(), "ask", "확인 줄이 떠 있을 때 취소를 또 눌러도 닫히지 않는다 — 그래도 닫기를 눌러야 닫힌다")
        self.assertTrue(controller.import_open and controller.import_dirty and controller.import_ask)
        self.assertEqual(controller.close_import(), "closed")
        self.assertFalse(controller.import_open or controller.import_dirty)

    def test_the_wait_for_the_app_close_is_a_controller_state_that_goes_down_with_the_question(self):
        controller = make("empty")
        self.assertEqual(controller.request_quit(), "none", "열린 가져오기가 없으면 그대로 닫는다")
        controller.open_import()
        self.assertEqual(controller.request_quit(), "none", "입력이 없으면 묻지 않는다")
        controller.import_edited(True)
        self.assertEqual(controller.request_quit(), "ask")
        self.assertTrue(controller.import_ask and controller.import_quit)
        controller.keep_import()
        self.assertFalse(controller.import_quit or controller.import_ask, "계속 쓰기")
        controller.request_quit()
        controller.import_edited(True)
        self.assertFalse(controller.import_quit or controller.import_ask, "확인 줄이 뜬 뒤 계속 입력하면 앱 닫기를 기다리지 않는다")
        controller.request_quit()
        self.assertEqual(controller.request_close_import(), "ask")
        self.assertTrue(controller.import_ask)
        self.assertFalse(controller.import_quit, "대화만 닫으려는 뜻이라 그래도 닫기가 앱을 닫지 않는다")
        controller.request_quit()
        controller.close_import()
        self.assertFalse(controller.import_quit)
        controller.open_import()
        self.assertFalse(controller.import_quit, "새 가져오기는 낡은 기다림 없이 시작한다")

    def test_a_write_in_progress_blocks_the_app_close_question_and_a_failed_write_leaves_no_wait(self):
        import threading
        gate = threading.Event()

        class Gated(post_fake.FakePostsProvider):
            def import_post(self, request, progress, cancelled):
                gate.wait(10)
                raise posts.PostFailure(T["post_fail_input_plain"], code="CONTENT_INVALID", kind="input")

        provider = Gated("empty")
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        controller.open_import()
        controller.import_edited(True)
        results = {}
        status, job = controller.start_import("제목", post_fake.sample_text(), on_error=lambda failure, _p: results.setdefault("failed", failure))
        self.assertEqual(status, "started")
        self.assertEqual(controller.request_quit(), "busy", "가져오는 중에는 앱 닫기 확인 줄을 띄우지 않는다")
        self.assertFalse(controller.import_quit or controller.import_ask, "그래서 낡은 기다림 표시도 남지 않는다")
        gate.set()
        job.join(10)
        controller.apply_write_failed(results["failed"])
        self.assertTrue(controller.import_open, "실패하면 대화는 열려 있다")
        self.assertFalse(controller.import_quit)
        self.assertEqual(controller.request_close_import(), "ask")
        self.assertFalse(controller.import_quit, "그 뒤 대화만 닫는 길이 앱을 닫지 않는다")

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

    def test_a_file_read_over_a_typed_body_says_how_to_undo_it(self):
        controller = make("empty")
        controller.open_import()
        results = {}
        _s, job = controller.start_read_file("C:/폴더/글.md", on_done=lambda result, _p: results.setdefault("ok", result))
        job.join(10)
        controller.apply_file(results["ok"], replaced=True)
        self.assertTrue(controller.import_note.startswith(T["post_im_read_ok"]))
        self.assertTrue(controller.import_note.endswith(T["post_im_replaced"]), "이미 쓴 본문이 바뀌었으면 되돌리는 법을 알린다")
        self.assertIn("Ctrl+Z", T["post_im_replaced"])
        controller.apply_file(results["ok"])
        self.assertEqual(controller.import_note, T["post_im_read_ok"], "빈 칸에 채울 때는 알릴 것이 없다")

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
        # 의도적 강화(독립 검증 Q 권고-5): 이름은 '가벼운 건강 주제는 막지 않는다' 인데 막지 않는 쪽 시험이 없었다 — 표시 권장(mark)·근거 필요(evidence) 단계는 승인을 막지 않는다(중지만 막는다)
        for stage, sentence in (("mark", "피로 회복에 도움이 될 수 있어요."), ("evidence", "당뇨 환자에게 좋은 식단을 소개해요.")):
            with self.subTest(stage=stage):
                light = make("empty")
                light_id = light.provider.add_post("가벼운 건강 글", post_fake.sample_text() + "\n\n" + sentence)
                light.apply_loaded(light.provider.load_posts(SAFE, NEVER))
                open_post(light, light_id)
                review_pages(light)
                self.assertEqual(light.review.health.stage, stage, "시험 글이 정말 그 단계다")
                self.assertEqual(light.approval(), (True, ""), "이 단계는 승인을 막지 않는다")
                self.assertIsNotNone(light.approve_dialog(), "확인창이 뜬다")
                section = next(item for item in light.view()["detail"]["review"]["panel"]["result"]["sections"] if item["key"] == "health")
                self.assertNotEqual(section["badge"]["text"], T["post_badge_block"])

    def test_review_card_texts_are_masked_again_where_the_card_is_made_even_if_the_source_forgot(self):
        """검토 카드의 모든 글은 카드를 만드는 곳(`_section`)에서도 한 번 더 가려진다(독립 검증 Q 권고-4) — 공급자가 가리지 않은 키 모양이 사유·경고·요약·건강 문장 어디에 있어도 화면에 나가지 않는다."""
        controller = self.opened()
        review_pages(controller)
        detail = controller.detail
        loud = f"문장 {KEY} 끝"
        pages = posts.ReviewReport(detail.project_id, posts.PAGES, detail.revision, st.REVIEW_REQUIRED, False, ("LEN_BODY",), (f"[LEN_BODY] 본문 {KEY}",), (f"경고 {KEY}",), (f"요약 {KEY}",), None,
                                   rules.HealthReview("stop", (f"본문: {loud}",)), ())
        naver = posts.ReviewReport(detail.project_id, posts.NAVER_A, detail.revision, st.REVIEW_REQUIRED, True, (), (), (f"경고 {KEY}",), (f"요약 {KEY}",), posts.SimilarityInfo("warn", 0.5, (f"이유 {KEY}",)),
                                   rules.HealthReview("general"), ())
        for report in (pages, naver):
            with self.subTest(platform=report.platform):
                controller.review, controller.platform = report, report.platform
                result = controller.view()["detail"]["review"]["panel"]["result"]
                self.assertEqual(result["state"], "ready")
                self.assertTrue(result["sections"])
                shown = repr(result)
                self.assertNotIn(KEY[:12], shown)
                self.assertNotIn(KEY[-12:], shown)
                self.assertIn("가림", shown)

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

    def test_a_key_shaped_pages_value_keeps_the_dialog_open_and_is_never_remembered(self):
        refused = posts.PostFailure(T["post_fail_secret"].format(where="한 줄 설명", kinds="Google API 키"), code="SECRET_SHAPE_FOUND", kind="secret")
        # 의도적 강화(독립 검증 Q 권고-2): 키 모양을 한 줄 설명 칸에만 넣던 것을 기억에 쓰는 네 칸(분야·대표 이미지 주소·태그·한 줄 설명) 모두로 — 어느 칸을 검사에서 빼도 빨개진다
        for field, value in (("category", f"생활 {KEY}"), ("image_url", f"https://img.example.invalid/a.jpg?k={KEY}"), ("tags", f"에너지, {KEY}"), ("description", f"설명 {KEY}")):
            with self.subTest(field=field):
                controller = self.opened(fail={"review_post": refused})
                controller.open_pages()
                keyed = dict(RAW, **{field: value})
                self.assertEqual(rules.pages_problems(keyed), {}, "키 모양을 넣은 값도 칸 검사는 통과해야 이 시험이 기억 규칙을 본다")
                status, end, todo = review_pages(controller, keyed)
                self.assertEqual((status, end, todo), ("started", "failed", {}))
                self.assertTrue(controller.pages_open, "키 모양 거절도 대화를 열어 둔 채 이유만 보인다")
                self.assertIn("Google API 키", controller.pages_view()["message"])
                self.assertNotIn(controller.open_id, controller.pages_raw, "거절된 키 모양 글이 든 값은 기억하지 않는다")
                controller.close_pages(keyed)
                self.assertNotIn(controller.open_id, controller.pages_raw, "닫을 때도 기억하지 않는다")
                self.assertEqual(controller.open_pages()[field], "", "다시 열어도 칸에 다시 채워지지 않는다")
                self.assertNotIn(KEY[:12], repr(controller.pages_raw) + repr(controller.view()) + repr(controller.pages_view()))
                self.assertFalse(controller.remember_pages(keyed), "직접 기억을 시켜도 거절한다")

    def test_a_value_with_any_shape_the_masking_engine_hides_is_not_remembered_either(self):
        """저장 검사기(`secret_spots`)가 아는 여섯 유형 밖의 모양(독립 검증 S 참고-2: Slack·OpenAI·Stripe·주소 속 사용자 정보)도 기억하지 않는다 — 가리기 엔진이 가리는 글은 칸에 다시 채우지 않는다."""
        samples = {"Slack 토큰": "xo" + "xb-" + "1234567890-" + "abcdefghijkl", "OpenAI 프로젝트 키": "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9j0K1", "주소 속 사용자 정보": "https://user:" + "pw@img.example.invalid/a.jpg",
                   "Stripe 키": "sk_" + "live_" + "A1b2C3d4E5f6G7h8I9j0K1L2"}
        for name, shape in samples.items():
            self.assertTrue(rules.would_be_masked(shape), f"시험 값이 정말 엔진이 가리는 모양이다: {name}")
            for field in ("category", "image_url", "tags", "description"):
                with self.subTest(shape=name, field=field):
                    controller = self.opened()
                    self.assertFalse(controller.remember_pages(dict(RAW, **{field: shape})))
                    self.assertNotIn(controller.open_id, controller.pages_raw)
        self.assertFalse(rules.would_be_masked("평범한 한 줄 설명이에요."))
        self.assertFalse(rules.would_be_masked(""))
        self.assertFalse(rules.would_be_masked(None))
        controller = self.opened()
        self.assertTrue(controller.remember_pages(dict(RAW)), "평범한 값은 그대로 기억한다")

    def test_a_value_with_only_invisible_characters_added_is_remembered_but_a_key_split_by_them_is_not(self):
        """독립 검증 S 2차 참고 I1: `would_be_masked` 가 '엔진이 눈에 안 보이는 글자를 지운 것' 도 가렸다고 세어 ZWJ 이모지·변형 선택자·소프트 하이픈이 든 평범한 값을 기억하지 않았다.
        이제는 가린 글을 원문에서 눈에 안 보이는 글자만 지운 글과 견준다 — 키를 그 글자로 쪼갠 값은 여전히 엔진이 가려서 기억하지 않는다."""
        family = chr(0x1F468) + chr(0x200D) + chr(0x1F469) + chr(0x200D) + chr(0x1F467)
        plain_values = {"ZWJ 이모지 가족": "가족 " + family + " 이야기", "변형 선택자 하트": "사랑 " + chr(0x2764) + chr(0xFE0F), "소프트 하이픈": "에너" + chr(0xAD) + "지 절약", "폭 없는 공백": "절" + chr(0x200B) + "약",
                        "범주로만 지워지는 서식 글자(U+0600)": "가" + chr(0x600) + "나", "제어 글자(U+0001)": "가" + chr(1) + "나", "줄 구분 글자(U+2028)": "가" + chr(0x2028) + "나", "한 줄 설명 속 방향 표지": "집" + chr(0x200F) + "안일"}
        for name, value in plain_values.items():
            with self.subTest(value=name):
                self.assertFalse(rules.would_be_masked(value), "눈에 안 보이는 글자만 든 평범한 값은 가릴 것이 없다")
                controller = self.opened()
                self.assertTrue(controller.remember_pages(dict(RAW, description=value)), "평범한 값은 그대로 기억한다")
                self.assertEqual(controller.pages_raw[controller.open_id]["description"], value)
        self.assertFalse(rules.would_be_masked(chr(0x200B) + chr(0xFEFF)), "눈에 안 보이는 글자뿐인 값에는 가릴 것이 없다")
        keys = {"Slack 토큰": "xo" + "xb-" + "1234567890-" + chr(0x200B) + "abcdefghijkl", "OpenAI 프로젝트 키": "sk-" + "proj-" + "A1b2C3d4" + chr(0x2060) + "E5f6G7h8I9j0K1", "주소 속 사용자 정보": "https://user:" + chr(0xAD) + "pw@img.example.invalid/a.jpg",
                "눈에 안 보이는 글자로 쪼갠 개인 키 머리": "-----BEG" + chr(0xAD) + "IN " + "RSA PRIVATE KEY-----"}
        for name, value in keys.items():
            with self.subTest(key=name):
                self.assertTrue(rules.would_be_masked(value), "엔진이 눈에 안 보이는 글자를 지우고 키 모양으로 알아본다")
                controller = self.opened()
                self.assertFalse(controller.remember_pages(dict(RAW, description=value)))
                self.assertNotIn(controller.open_id, controller.pages_raw)

    def test_the_invisible_character_list_is_the_masking_engines_own_list(self):
        """`would_be_masked` 가 지우는 눈에 안 보이는 글자(구간 목록과 범주)는 가리기 엔진의 것과 모든 코드 포인트에서 같다 — 엔진이 바뀌어 어긋나면 이 시험이 알린다(어긋나도 안전한 쪽이지만 평범한 값을 기억하는 정도가 달라진다)."""
        from chanceblog_desktop.security import mask as engine
        self.assertEqual(rules._HIDDEN_CATEGORIES, engine._HIDDEN)
        listed = [code for code in range(0x110000) if (rules._INVISIBLE.match(chr(code)) is None) != (engine._INVISIBLE.match(chr(code)) is None)]
        self.assertEqual(listed, [], "구간 목록이 엔진과 다른 코드 포인트")
        for start in range(0, 0x110000, 0x1000):
            chunk = "".join(chr(code) for code in range(start, start + 0x1000))
            if rules._without_invisible(chunk) != engine._strip_invisible(chunk):
                self.fail(f"엔진과 다르게 지운다: U+{start:04X} 부터 4096자")

    def test_the_pages_values_are_remembered_when_the_dialog_is_closed_without_a_review(self):
        controller = self.opened()
        controller.open_pages()
        self.assertTrue(controller.close_pages(dict(RAW)))
        self.assertFalse(controller.pages_open)
        self.assertEqual(controller.pages_raw[controller.open_id], RAW, "취소·Esc 로 닫아도 쓰던 값은 이 앱을 연 동안 남는다")
        again = controller.open_pages()
        self.assertEqual((again["category"], again["tags"]), ("생활", "에너지, 습관"))
        controller.close_pages()
        self.assertEqual(controller.pages_raw[controller.open_id], RAW, "값 없이 닫으면 기억을 지우지 않는다")
        self.assertFalse(controller.remember_pages("딕셔너리가 아니다"))
        controller.close_post()
        self.assertFalse(controller.remember_pages(dict(RAW)), "열린 글이 없으면 기억하지 않는다")

    def test_a_refused_approval_drops_the_old_review_so_a_new_one_is_needed(self):
        for kind, code in (("gate", "CHECK_FAILED"), ("similarity", "NAVER_SIMILARITY_HIGH")):
            with self.subTest(kind=kind):
                controller = make("empty", fail={"approve_post": posts.PostFailure(T["post_fail_gate"], code=code, kind=kind)})
                project_id = long_post(controller.provider, "검토할 글")
                controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
                open_post(controller, project_id)
                review_pages(controller)
                self.assertTrue(controller.approval()[0])
                status, end, todo = approve(controller)
                self.assertEqual((status, end, todo), ("started", "failed", {}))
                self.assertIsNone(controller.review, "서비스가 승인 순간에 거절했으면 '통과' 로 보이던 옛 결과를 더 믿지 않는다")
                self.assertEqual(controller.approval(), (False, "post_res_lost"))
                result = controller.view()["detail"]["review"]["panel"]["result"]
                self.assertEqual((result["state"], result["sections"]), ("lost", []))
                self.assertFalse(controller.view()["detail"]["review"]["panel"]["approve"]["enabled"])

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


class PostsStaleReadsCoreTest(unittest.TestCase):
    """읽기는 쓰기와 따로 도는 작업이라 쓰기가 끝난 뒤에 쓰기 전 모습이 늦게 도착할 수 있다 — 세대 번호가 그런 낡은 결과를 버린다."""

    def read_list(self, controller):
        results = {}
        job = controller.start_load(on_done=lambda result, _p: results.setdefault("ok", result))
        job.join(10)
        return results["ok"]

    def test_a_list_read_that_started_before_a_write_ended_is_dropped_and_a_new_one_is_taken(self):
        controller = make("empty")
        old = self.read_list(controller)                                        # 읽기는 끝났지만 셸이 아직 받지 않았다(쓰기 전 모습)
        before = controller.data
        controller.open_import()
        drive(controller, lambda **cb: controller.start_import("방금 가져온 글", post_fake.sample_text(), **cb))
        self.assertTrue(controller.is_stale(old))
        self.assertFalse(controller.apply_loaded(old), "쓰기 전 목록은 받지 않는다")
        self.assertIs(controller.data, before)
        fresh = self.read_list(controller)
        self.assertFalse(controller.is_stale(fresh))
        self.assertTrue(controller.apply_loaded(fresh))
        self.assertEqual(len(controller.data.rows), 1)
        self.assertTrue(controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER)), "세대 번호가 없는(직접 만든) 값은 낡았다고 보지 않는다")

    def test_a_detail_read_that_started_before_a_write_ended_never_puts_the_old_state_back(self):
        controller = make("empty")
        project_id = long_post(controller.provider)
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        results = {}
        _status, job = controller.start_open(project_id, on_done=lambda result, _p: results.setdefault("ok", result))
        job.join(10)
        old = results["ok"]                                                     # 쓰기 전 모습('시작 전')을 읽은 결과
        review_pages(controller)
        self.assertEqual(controller.detail.platform(posts.PAGES).status, st.REVIEW_REQUIRED)
        self.assertTrue(controller.is_stale(old))
        self.assertFalse(controller.apply_detail(old))
        self.assertEqual(controller.detail.platform(posts.PAGES).status, st.REVIEW_REQUIRED, "화면이 쓰기 전 모습으로 되돌아가지 않는다")
        again = {}
        job = controller.reload_detail(on_done=lambda result, _p: again.setdefault("ok", result))
        job.join(10)
        self.assertTrue(controller.apply_detail(again["ok"]), "쓰기가 끝난 뒤에 시작한 읽기는 받는다")

    def test_every_write_end_raises_the_generation_whether_it_worked_or_not(self):
        controller = make("empty")
        controller.open_import()
        start = controller.epoch
        drive(controller, lambda **cb: controller.start_import("가져온 글", post_fake.sample_text(), **cb))
        self.assertEqual(controller.epoch, start + 1)
        failing = make("empty", fail={"import_post": posts.PostFailure(T["post_fail_input_plain"], code="CONTENT_INVALID", kind="input")})
        failing.open_import()
        drive(failing, lambda **cb: failing.start_import("가져온 글", post_fake.sample_text(), **cb))
        self.assertEqual(failing.epoch, 1, "실패한 쓰기도 세대를 올린다")
        failing.apply_write_unexpected(RuntimeError("x"))
        self.assertEqual(failing.epoch, 2)
        failing.apply_unexpected(RuntimeError("y"))
        self.assertEqual(failing.epoch, 3, "받아 둔 값을 모두 버릴 때도")

    def test_a_late_failure_never_touches_a_closed_post_or_another_post(self):
        provider = post_fake.FakePostsProvider(fail={"load_post": posts.PostFailure(T["post_fail_notfound"], code="CONTENT_NOT_FOUND", kind="notfound")})
        controller = posts_view.PostsController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_posts(SAFE, NEVER))
        first, second = row_ids(controller)[:2]
        results = {}
        _status, job = controller.start_open(first, on_error=lambda failure, _p: results.setdefault("failed", failure))
        job.join(10)
        failure = results["failed"]
        self.assertEqual(failure.read_of, (first, 0), "어느 글을 어느 세대에 읽다 실패했는지 붙어 있다")
        controller.close_post()
        self.assertEqual(controller.apply_detail_failed(failure), "ignored", "이미 닫은 글의 늦은 실패는 오류 상태를 남기지 않는다")
        self.assertEqual((controller.open_id, controller.detail_state), (None, "none"))
        provider.fail.clear()
        open_post(controller, second)
        self.assertEqual(controller.apply_detail_failed(failure), "ignored", "다른 글을 열어 둔 동안 늦게 온 '없음' 실패가 그 글을 닫지 않는다")
        self.assertEqual((controller.open_id, controller.detail_state), (second, "normal"))
        controller.epoch += 1                                                   # 읽는 동안 쓰기가 끝났다
        late = posts.PostFailure("x", code="STORE_CORRUPT", kind="corrupt")
        late.read_of = (second, controller.epoch - 1)
        self.assertEqual(controller.apply_detail_failed(late), "stale", "같은 글의 낡은 실패는 다시 읽게 한다")
        self.assertEqual(controller.detail_state, "normal", "낡은 실패가 오류 화면을 만들지 않는다")

    def test_reloading_the_open_post_does_not_need_the_list_to_know_it_yet(self):
        controller = make("empty")
        controller.open_import()
        drive(controller, lambda **cb: controller.start_import("방금 가져온 글", post_fake.sample_text(), **cb))
        self.assertIsNone(controller.row(controller.open_id), "목록은 아직 새 글을 모른다")
        results = {}
        job = controller.reload_detail(on_done=lambda result, _p: results.setdefault("ok", result))
        self.assertIsNotNone(job, "'다시 시도' 가 조용히 아무 일도 하지 않으면 안 된다")
        job.join(10)
        self.assertTrue(controller.apply_detail(results["ok"]))
        self.assertEqual(controller.start_open("없는번호"), ("unknown", None), "처음 여는 길은 목록에 있는 글만 연다")

    def test_a_re_read_after_a_failure_keeps_the_notice_that_says_why_but_opening_a_post_clears_it(self):
        controller = make("empty")
        project_id = long_post(controller.provider)
        controller.apply_loaded(controller.provider.load_posts(SAFE, NEVER))
        open_post(controller, project_id)
        controller.notice = ("error", "글이 바뀌었어요")
        controller.reload_detail(keep_notice=True).join(10)
        self.assertEqual(controller.notice, ("error", "글이 바뀌었어요"), "왜 다시 읽는지 알리는 안내가 곧바로 사라지면 안 된다")
        controller.reload_detail().join(10)
        self.assertIsNone(controller.notice, "그냥 다시 읽을 때는 지난 알림을 거둔다")
        controller.notice = ("ok", "지난 알림")
        controller.start_open(project_id)[1].join(10)
        self.assertIsNone(controller.notice, "글을 새로 열면 지난 알림을 거둔다")


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
    ADAPTER_MAY_NAME = {"record_naver_published"}                          # 의도적 갱신(글 흐름 1b, D-647): 발행 주소 기록(`record_published`)이 이 서비스 함수 하나를 부르므로 **어댑터에서만** 이 낱말을 푼다 — 화면 층(`ui/core/post*.py`·`ui/qt/post*.py`)은 계속 금지이고 나머지 금지 낱말은 모두 그대로다

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
                if path.name == "posts_adapter.py" and word in self.ADAPTER_MAY_NAME:
                    continue                                              # 의도적 갱신(글 흐름 1b, D-647): 어댑터만 — 그 한 곳은 아래 시험이 따로 못박는다
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
        service_aliases = {"own_posts", "project_service", "review_service", "history_service", "profile_service", "worklog_service"}          # 의도적 갱신(글 흐름 1b, D-647): 서비스 모듈 별칭 셋이 늘었다
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in service_aliases:
                calls.add(f"{node.func.value.id}.{node.func.attr}")
        self.assertEqual(calls, {"own_posts.read_own_files", "own_posts.check_pasted_text", "project_service.list_projects", "project_service.show_project", "project_service.new_project",
                                 "project_service.import_html", "review_service.request_review", "review_service.grant_approval", "review_service.revoke_approval",
                                 "review_service.read_naver_package", "review_service.mark_naver_copied", "review_service.record_naver_published", "history_service.list_history",
                                 "worklog_service.read_work_log", "profile_service.profile_keys"})              # 의도적 갱신(글 흐름 1b, D-647): 아홉에서 열다섯 — 여섯을 더했고 정확히 같음을 못박는 방식은 그대로다
        imported = {alias.name if isinstance(node, ast.Import) else f"{node.module}.{alias.name}" for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
        for banned in ("pages_flow", "naver_flow", "external", "capabilities", "gitrepo", "gate", "backup_flow", "doctor"):
            self.assertFalse([name for name in imported if name.endswith(banned) or f".{banned}." in name], banned)
        self.assertEqual(self.service_problems((UI_DIR / "posts_adapter.py").read_text(encoding="utf-8")), [], "아래 강화된 검사도 통과한다(가져오기·별칭·속성·컨텍스트 호출을 모두 따라간다)")

    # ---- 강화(독립 검증 S 권고-1·2): 서비스를 부르는 길을 가져오기·별칭·속성까지 따라가고, Qt 의 파일 쓰기 도구도 막는다 ------------------------------------------------------------------
    SERVICE_IMPORTS = {"own_posts": "chanceblog_desktop.service.own_posts", "project_service": "chanceblog_desktop.service.projects", "review_service": "chanceblog_desktop.service.review",
                       "make_context": "chanceblog_desktop.service.context.make_context", "PagesParams": "chanceblog_desktop.service.previews.PagesParams",
                       "history_service": "chanceblog_desktop.service.history", "profile_service": "chanceblog_desktop.service.naver_profiles", "worklog_service": "chanceblog_desktop.service.worklog"}          # 의도적 갱신(글 흐름 1b, D-647): 서비스 모듈 셋(발행 기록·프로필 합쳐 읽기·작업 로그)이 늘었다
    SERVICE_USES = {"own_posts.read_own_files", "own_posts.check_pasted_text", "own_posts.SUBJECT", "project_service.list_projects", "project_service.show_project", "project_service.new_project",
                    "project_service.import_html", "review_service.request_review", "review_service.grant_approval", "review_service.revoke_approval",
                    "review_service.read_naver_package", "review_service.mark_naver_copied", "review_service.record_naver_published", "history_service.list_history", "worklog_service.read_work_log",
                    "profile_service.profile_keys"}      # 함수 열다섯 + 상수 하나(`SUBJECT` — 붙여 넣은 글 거절 문장의 항목 이름) — 1a 에서는 함수 아홉이었다(글 흐름 1b, D-647)
    CTX_USES = {"ctx.reading_only"}                                               # 의도적 강화(글 흐름 1b, D-648): 어댑터가 설정 파일을 직접 읽던 `ctx.settings.naver_profile_dicts` 가 없어졌다 — 프로필은 서비스 함수(`profile_keys`)가 합쳐 읽는다
    DYNAMIC_NAMES = {"getattr", "setattr", "delattr", "vars", "globals", "locals", "__import__", "importlib", "import_module", "eval", "exec", "compile", "modules", "__dict__", "__globals__", "__builtins__"}
    QT_FILE_NAMES = {"QFile", "QSaveFile", "QTemporaryFile", "QTemporaryDir", "QTextStream", "QDataStream", "QDir", "QStandardPaths", "QIODevice", "QIODeviceBase", "QLockFile", "QSettings",
                     "QFileSystemWatcher", "QFileDialog"}
    QT_WRITE_WORDS = {"WriteOnly", "ReadWrite", "Append", "Truncate", "NewOnly", "mkpath", "rmpath", "getSaveFileName", "getExistingDirectory"}

    @staticmethod
    def absolute(node, package="chanceblog_desktop.ui"):
        """`from … import` 가 가리키는 모듈의 전체 이름 — 점 하나는 이 파일이 있는 꾸러미, 둘은 그 위 꾸러미다."""
        if node.level == 0:
            return node.module or ""
        parts = package.split(".")
        parts = parts[: len(parts) - (node.level - 1)]
        return ".".join(parts + ([node.module] if node.module else []))

    def service_problems(self, source):
        """어댑터 소스가 서비스 층과 맺는 모든 연결이 허용 목록과 **정확히 같은지** 본다 → 어긋난 곳의 설명 목록(없으면 비어 있다).
        ① 서비스에서 가져오는 이름은 `SERVICE_IMPORTS` 다섯뿐(`from ..service.x import y`·`as` 별칭·`from .. import service`·`*` 도 가져온 이름으로 센다, 절대 가져오기는 금지)
        ② 서비스 모듈 별칭의 속성 접근은 `SERVICE_USES`(함수 아홉 + 상수 하나)와 같고, 별칭을 속성 접근 없이 그냥 쓰는 곳(다른 이름에 담기·인자로 넘기기)이 없다
        ③ 컨텍스트(`ctx`·`self._context(...)` 를 담은 이름)의 속성 사슬은 `CTX_USES` 와 같다 ④ `getattr` 같은 동적 접근 이름이 없다
        ⑤ 컨텍스트의 이름(진짜 `Context` 의 공개 이름 전부)은 받는 변수 이름과 상관없이 허용된 두 사슬 밖에서 쓰지 않는다 ⑥ 컨텍스트는 `ctx = self._context(...)` 한 모양으로만 만들고 이름 `ctx` 는 속성 접근·호출 인자로만 읽는다
        ⑦ `sys`·`builtins`·`inspect`·`gc`·`importlib` 를 가져오지 않는다(독립 검증 Q 2차 권고-2: 별칭·즉석 사슬·매개변수 이름·`sys.modules` 우회). **한계**: 이 검사는 이름과 모양으로 보는 시험 코드이지 실행 때의 방어가 아니다(문서 D-639)."""
        tree, problems = ast.parse(source), []
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        pairs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                problems += [f"절대 가져오기는 쓰지 않는다: {alias.name}" for alias in node.names if alias.name.split(".")[0] == "chanceblog_desktop"]
            elif isinstance(node, ast.ImportFrom):
                base = self.absolute(node)
                for alias in node.names:
                    target = f"{base}.{alias.name}"
                    if base == "chanceblog_desktop.service" or base.startswith("chanceblog_desktop.service.") or target == "chanceblog_desktop.service":
                        pairs.append((alias.asname or alias.name, target))
        if sorted(pairs) != sorted(self.SERVICE_IMPORTS.items()):
            problems.append(f"서비스에서 가져오는 이름이 허용 목록과 다르다: {sorted(set(pairs) ^ set(self.SERVICE_IMPORTS.items()))}")
        module_names = {local for local, target in pairs if target in {self.SERVICE_IMPORTS[name] for name in ("own_posts", "project_service", "review_service", "history_service", "profile_service", "worklog_service")}}
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in module_names and isinstance(node.ctx, ast.Load):
                parent = parents.get(node)
                if isinstance(parent, ast.Attribute) and parent.value is node:
                    used.add(f"{node.id}.{parent.attr}")
                else:
                    problems.append(f"서비스 모듈 별칭을 속성 접근 없이 쓴다: {node.id} (줄 {node.lineno})")
        if used != self.SERVICE_USES:
            problems.append(f"서비스 모듈의 속성 사용이 허용 목록과 다르다: {sorted(used ^ self.SERVICE_USES)}")
        roots = {"ctx"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr in ("_context", "_factory"):
                roots |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        chains = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and not isinstance(parents.get(node), ast.Attribute):
                names, current = [], node
                while isinstance(current, ast.Attribute):
                    names.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name) and current.id in roots:
                    chains.add("ctx." + ".".join(reversed(names)))
        if chains != self.CTX_USES:
            problems.append(f"컨텍스트의 속성 사슬이 허용 목록과 다르다: {sorted(chains ^ self.CTX_USES)}")
        for node in ast.walk(tree):
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
            if name in self.DYNAMIC_NAMES:
                problems.append(f"동적 접근 이름: {name} (줄 {node.lineno})")
        context_names = self.context_names()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in context_names and not self.allowed_context_attribute(node, parents):
                problems.append(f"컨텍스트의 이름이 허용된 두 사슬 밖에서 쓰였다: {node.attr} (줄 {node.lineno})")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("_context", "_factory") and not self.allowed_context_call(node, parents):
                problems.append(f"컨텍스트는 `ctx = self._context(...)` 한 모양으로만 만든다 (줄 {node.lineno})")
            elif isinstance(node, ast.Name) and node.id == "ctx" and isinstance(node.ctx, ast.Load) and not self.allowed_ctx_load(node, parents):
                problems.append(f"컨텍스트 이름 ctx 를 속성 접근이나 호출 인자 밖에서 쓴다: 다른 이름에 담거나 묶음에 넣을 수 없다 (줄 {node.lineno})")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                problems += [f"표준 도구 가져오기: {name} (줄 {node.lineno})" for name in modules if name.split(".")[0] in self.BANNED_STDLIB]
        return problems

    # ---- 강화(독립 검증 Q 2차 권고-2): 컨텍스트를 담는 이름을 `ctx` 하나로만 허용하고, 컨텍스트의 이름(git·backend·keystore·store …)은 받는 변수 이름과 상관없이 허용된 두 사슬 밖에서 쓰지 못하게 한다 ----------------
    BANNED_STDLIB = {"sys", "builtins", "inspect", "gc", "importlib"}

    @staticmethod
    def context_names():
        """진짜 `Context`(서비스의 컨텍스트)의 공개 이름 전부 — 필드와 메서드(`git`·`backend`·`keystore`·`store`·`settings` …). 컨텍스트가 늘면 자동으로 넓어진다."""
        return {field.name for field in dataclasses.fields(Context)} | {name for name in dir(Context) if not name.startswith("_")}

    @staticmethod
    def allowed_context_attribute(node, parents):
        """어댑터가 컨텍스트에서 쓰는 모양은 `ctx.reading_only()` 하나다 — 1a 에서는 `ctx.settings.naver_profile_dicts()` 의 가운데 `settings` 도 있었으나 1b(D-648)가 그 길을 서비스 함수로 바꿔 없앴다(강화)."""
        parent = parents.get(node)
        if not (isinstance(node.value, ast.Name) and node.value.id == "ctx"):
            return False
        return node.attr == "reading_only" and isinstance(parent, ast.Call) and parent.func is node

    @staticmethod
    def allowed_context_call(node, parents):
        """컨텍스트를 만드는 호출은 `ctx = self._context("…")`(대입 대상이 `ctx` 하나) 뿐이고, `self._factory(…)` 는 `_context` 함수 안에서만 부른다 — 이름에 안 담고 바로 사슬을 잇거나(`self._context('read').git`) 다른 이름에 담지 못한다."""
        parent = parents.get(node)
        if node.func.attr == "_context":
            return isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name) and parent.targets[0].id == "ctx"
        current = parent
        while current is not None and not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current = parents.get(current)
        return current is not None and current.name == "_context"

    @staticmethod
    def allowed_ctx_load(node, parents):
        """이름 `ctx` 를 읽는 곳은 속성 접근(`ctx.x`)이거나 호출의 위치 인자(`f(ctx, …)`)뿐이다 — `other = ctx`·`(ctx,)`·`[ctx]`·람다 인자 밖의 사용은 없다."""
        parent = parents.get(node)
        return (isinstance(parent, ast.Attribute) and parent.value is node) or (isinstance(parent, ast.Call) and node in parent.args)

    def qt_write_problems(self, source):
        """화면 층 소스의 Qt 파일 쓰기·경로 도구(`QFile` 열기 모드 쓰기·`QSaveFile`·`QTextStream`·`mkpath` …)를 이름으로 찾는다 → 설명 목록(없으면 비어 있다). 가져오기·이름·속성(`QtCore.QFile`)을 모두 본다."""
        problems = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                problems += [f"Qt 파일 도구 가져오기: {alias.name} (줄 {node.lineno})" for alias in node.names if alias.name.split(".")[-1] in self.QT_FILE_NAMES]
            elif isinstance(node, ast.Name) and node.id in self.QT_FILE_NAMES:
                problems.append(f"Qt 파일 도구 이름: {node.id} (줄 {node.lineno})")
            elif isinstance(node, ast.Attribute) and (node.attr in self.QT_FILE_NAMES or node.attr in self.QT_WRITE_WORDS):
                problems.append(f"Qt 파일 도구·쓰기 모드: {node.attr} (줄 {node.lineno})")
        return problems

    def test_the_adapters_whole_surface_towards_the_service_is_the_allow_list_by_imports_aliases_and_attributes(self):
        self.assertEqual(self.service_problems((UI_DIR / "posts_adapter.py").read_text(encoding="utf-8")), [])

    def test_the_surface_check_catches_every_way_around_the_nine_calls(self):
        """이 검사 자체를 합성 소스로 시험한다 — 진짜 어댑터 소스 끝에 우회 모양을 덧붙이면 빠짐없이 걸린다(독립 검증 S 권고-1: `from ..service.projects import delete_project` 같은 모양은 앞의 시험을 통과했다)."""
        source = (UI_DIR / "posts_adapter.py").read_text(encoding="utf-8")
        self.assertEqual(self.service_problems(source), [])
        bypasses = {
            "함수 이름으로 가져오기": "\nfrom ..service.projects import delete_project\n\n\ndef _extra(ctx):\n    delete_project(ctx, 'x')\n",
            "다른 별칭으로 가져오기": "\nfrom ..service import projects as other_name\n\n\ndef _extra(ctx):\n    other_name.delete_project(ctx, 'x')\n",
            "별칭을 다른 이름에 담기": "\n\ndef _extra(ctx):\n    alias = project_service\n    alias.delete_project(ctx, 'x')\n",
            "별칭을 인자로 넘기기": "\n\ndef _extra(ctx):\n    return list(map(project_service.list_projects, [ctx]))[0], dict(vars=project_service)\n",
            "허용 모듈의 다른 속성": "\n\ndef _extra(ctx):\n    project_service.delete_project(ctx, 'x')\n",
            "getattr 로 부르기": "\n\ndef _extra(ctx):\n    getattr(project_service, 'delete_project')(ctx, 'x')\n",
            "서비스 모듈 하나 더": "\nfrom ..service import backup_flow\n",
            "별표 가져오기": "\nfrom ..service.projects import *\n",
            "꾸러미째 가져오기": "\nfrom .. import service\n\n\ndef _extra(ctx):\n    service.projects.delete_project(ctx, 'x')\n",
            "절대 가져오기": "\nimport chanceblog_desktop.service.projects\n",
            "컨텍스트의 다른 속성": "\n\ndef _extra(ctx):\n    ctx.git.push()\n",
            "컨텍스트를 다른 이름에 담기": "\n\ndef _extra(self):\n    context = self._context('read')\n    context.git.push()\n",
            "컨텍스트를 다른 이름에 대입": "\n\ndef _extra(ctx):\n    ctx2 = ctx\n    ctx2.git.push()\n",
            "컨텍스트 즉석 사슬": "\n\ndef _extra(self):\n    self._context('read').git.push()\n",
            "매개변수 이름 바꾸기": "\n\ndef _helper(c):\n    c.git.push()\n\n\ndef _extra(ctx):\n    _helper(ctx)\n",
            "람다로 풀기": "\n\ndef _extra(ctx):\n    return (lambda c: c.git)(ctx)\n",
            "묶음에 넣어 꺼내기": "\n\ndef _extra(ctx):\n    return [x for x in (ctx,)][0].backend\n",
            "컨텍스트로 저장소 열기": "\n\ndef _extra(ctx):\n    ctx.store().delete_project('x')\n",
            "컨텍스트 만들기를 다른 이름에 담기": "\n\ndef _extra(self):\n    other = self._factory(data_dir='x')\n    other.keystore\n",
            "sys.modules 로 서비스 모듈 찾기": "\nimport sys\n\n\ndef _extra(ctx):\n    sys.modules['chanceblog_desktop.service.projects'].delete_project(ctx, 'x')\n",
            "표준 도구를 별칭으로 가져오기": "\nimport sys as _s\n",
            "가져오기 이름 하나 빼기": source.replace("from ..service.previews import PagesParams\n", ""),
        }
        for name, change in bypasses.items():
            with self.subTest(way=name):
                changed = change if name == "가져오기 이름 하나 빼기" else source + change
                self.assertNotEqual(changed, source)
                self.assertTrue(self.service_problems(changed), f"우회가 걸리지 않았다: {name}")

    def test_the_new_service_roads_of_1b_are_closed_the_same_way(self):
        """글 흐름 1b(D-647)가 서비스를 부르는 길을 열다섯으로 넓혔다 — 새 길 둘레의 우회(승인까지 해 버리는 옛 함수·같은 모듈의 다른 속성·옛 설정 파일 길·별칭 담기)도 같은 검사기가 빠짐없이 잡는다."""
        source = (UI_DIR / "posts_adapter.py").read_text(encoding="utf-8")
        self.assertEqual(self.service_problems(source), [])
        bypasses = {
            "승인까지 해 버리는 옛 함수 가져오기": "\nfrom ..service.review import issue_naver_package\n",
            "승인까지 해 버리는 옛 함수를 속성으로": "\n\ndef _extra(ctx):\n    review_service.issue_naver_package(ctx, 'x', 'naver_a')\n",
            "발행 기록 모듈의 다른 속성": "\n\ndef _extra(ctx):\n    history_service.delete_history(ctx)\n",
            "작업 로그를 지우는 길": "\n\ndef _extra(ctx):\n    worklog_service.clear_work_log(ctx)\n",
            "프로필을 쓰는 길": "\n\ndef _extra(ctx):\n    profile_service.save_profile(ctx, 'naver_a', {})\n",
            "설정 파일을 직접 읽던 옛 길": "\n\ndef _extra(ctx):\n    return ctx.settings.naver_profile_dicts()\n",
            "네이버 흐름 모듈 가져오기": "\nfrom ..service import naver_flow\n",
            "서비스 모듈 별칭을 다른 이름에 담기": "\n\ndef _extra(ctx):\n    other = review_service\n    other.mark_naver_copied(ctx, 'x', 'naver_a')\n",
            "발행 기록 모듈을 다른 이름으로 가져오기": "\nfrom ..service import history as other_history\n\n\ndef _extra(ctx):\n    other_history.list_history(ctx)\n",
            "프로필 모듈을 별표로 가져오기": "\nfrom ..service.naver_profiles import *\n",
        }
        for name, change in bypasses.items():
            with self.subTest(way=name):
                self.assertTrue(self.service_problems(source + change), f"우회가 걸리지 않았다: {name}")
        for word in ("issue_naver_package", "naver_flow", "pages_flow"):
            self.assertIn(word, self.BANNED_WORDS)
            self.assertNotIn(word, self.ADAPTER_MAY_NAME, "어댑터에서 풀린 낱말은 발행 주소 기록 하나뿐이다")
        self.assertEqual(self.ADAPTER_MAY_NAME, {"record_naver_published"})
        self.assertEqual(self.code_only(UI_DIR / "posts_adapter.py").count("record_naver_published"), 1, "그 낱말은 어댑터 코드에 한 번(발행 주소 기록 길)만 있다")

    def test_the_screen_files_have_no_qt_file_write_tool_and_the_check_sees_every_shape(self):
        """화면 층(`post*.py`)과 어댑터에는 `QFile`(쓰기 열기 모드)·`QSaveFile`·`QTextStream`·`QDir.mkpath` 같은 Qt 파일 도구가 없다(독립 검증 S 권고-2: 파이썬 쓰기 이름만 보던 시험이 `QFile` 쓰기를 못 잡았다)."""
        for path in self.CORE + self.QT + [UI_DIR / "posts_adapter.py"]:
            with self.subTest(file=path.name):
                self.assertEqual(self.qt_write_problems(path.read_text(encoding="utf-8")), [])
        base = (UI_DIR / "qt" / "post_parts.py").read_text(encoding="utf-8")
        shapes = {
            "QFile 쓰기 열기": "\nfrom PySide6.QtCore import QFile, QIODevice\n\n\ndef _extra():\n    QFile('a.txt').open(QIODevice.WriteOnly)\n",
            "QSaveFile": "\nfrom PySide6.QtCore import QSaveFile\n",
            "QTextStream": "\n\ndef _extra(device):\n    return QTextStream(device)\n",
            "꾸러미 속성으로": "\n\ndef _extra(QtCore):\n    return QtCore.QFile('a.txt').open(QtCore.QIODevice.OpenModeFlag.Append)\n",
            "폴더 만들기": "\n\ndef _extra(folder):\n    folder.mkpath('x')\n",
            "저장 대화": "\n\ndef _extra(dialog):\n    return dialog.getSaveFileName(None, 'x')\n",
            "설정 파일": "\nfrom PySide6.QtCore import QSettings\n",
        }
        self.assertEqual(self.qt_write_problems(base), [])
        for name, extra in shapes.items():
            with self.subTest(shape=name):
                self.assertTrue(self.qt_write_problems(base + extra), f"Qt 파일 도구가 걸리지 않았다: {name}")

    def test_every_name_in_the_deny_lists_has_its_own_shape_that_the_check_flags_for_that_name(self):
        """독립 검증 Q 2차 권고-5: 검사기의 거부 목록(`DYNAMIC_NAMES`·`QT_FILE_NAMES`·`QT_WRITE_WORDS`)에서 항목 하나가 조용히 빠져도 같은 우회가 다른 규칙에 걸려 가려졌다 — 항목마다 따로 **그 이름 때문에** 걸리는지 보고,
        목록 자체도 시험 안에 적어 둔 집합과 같다고 못박는다. 컨텍스트를 담는 호출 이름 둘(`_context`·`_factory`)도 항목마다 본다."""
        dynamic = {"getattr", "setattr", "delattr", "vars", "globals", "locals", "__import__", "importlib", "import_module", "eval", "exec", "compile", "modules", "__dict__", "__globals__", "__builtins__"}
        qt_files = {"QFile", "QSaveFile", "QTemporaryFile", "QTemporaryDir", "QTextStream", "QDataStream", "QDir", "QStandardPaths", "QIODevice", "QIODeviceBase", "QLockFile", "QSettings", "QFileSystemWatcher",
                    "QFileDialog"}
        qt_words = {"WriteOnly", "ReadWrite", "Append", "Truncate", "NewOnly", "mkpath", "rmpath", "getSaveFileName", "getExistingDirectory"}
        self.assertEqual((self.DYNAMIC_NAMES, self.QT_FILE_NAMES, self.QT_WRITE_WORDS), (dynamic, qt_files, qt_words), "거부 목록이 정해 둔 집합과 다르다 — 항목을 빼거나 더하려면 이 시험도 함께 고친다")
        adapter = (UI_DIR / "posts_adapter.py").read_text(encoding="utf-8")
        self.assertEqual(self.service_problems(adapter), [])
        for name in sorted(dynamic):
            with self.subTest(dynamic=name):
                problems = self.service_problems(adapter + f"\n\ndef _extra(project_service):\n    return {name}\n")
                self.assertTrue([item for item in problems if item.startswith(f"동적 접근 이름: {name} ")], f"{name} 이 동적 접근 이름으로 걸리지 않았다: {problems}")
        base = (UI_DIR / "qt" / "post_parts.py").read_text(encoding="utf-8")
        self.assertEqual(self.qt_write_problems(base), [])
        for name in sorted(qt_files):
            with self.subTest(qt_file=name):
                for shape, message in ((f"\n\ndef _extra():\n    return {name}\n", f"Qt 파일 도구 이름: {name} "), (f"\nfrom PySide6.QtCore import {name}\n", f"Qt 파일 도구 가져오기: {name} "),
                                       (f"\n\ndef _extra(QtCore):\n    return QtCore.{name}\n", f"Qt 파일 도구·쓰기 모드: {name} ")):
                    self.assertTrue([item for item in self.qt_write_problems(base + shape) if item.startswith(message)], f"{name}: '{message}' 로 걸리지 않았다")
        for word in sorted(qt_words):
            with self.subTest(qt_word=word):
                found = self.qt_write_problems(base + f"\n\ndef _extra(x):\n    return x.{word}\n")
                self.assertTrue([item for item in found if item.startswith(f"Qt 파일 도구·쓰기 모드: {word} ")], f"{word} 가 걸리지 않았다")
        for owner in ("_context", "_factory"):
            with self.subTest(context_source=owner):
                problems = self.service_problems(adapter + f"\n\ndef _extra(self):\n    other = self.{owner}('read')\n    other.git.push()\n")
                self.assertTrue([item for item in problems if "컨텍스트의 속성 사슬" in item], f"{owner} 로 만든 컨텍스트를 담은 이름의 사슬을 따라가지 않았다: {problems}")

    def test_the_write_wait_when_the_app_closes_is_ten_seconds_and_is_the_value_the_closing_path_waits_with(self):
        """독립 검증 Q 2차 권고-6: 앱을 닫을 때 쓰기가 끝나기를 기다리는 한도(`post_flow.WRITE_CLOSE_WAIT`)를 시험이 못박지 못했다 — 닫기 길이 더하는 `join_all(1.0)` 때문에 한도를 1–2초로 줄여도 기다림 시험이 통과했다.
        화면 도구 없이도 돌도록 소스에서 값을 읽는다."""
        tree = self.parse(UI_DIR / "qt" / "post_flow.py")
        values = [node.value.value for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and any(isinstance(target, ast.Name) and target.id == "WRITE_CLOSE_WAIT" for target in node.targets)]
        self.assertEqual(values, [10.0], "글 쓰기 기다림 한도는 10초다 — 이 값이 닫기 길이 쓰는 기다림이다")
        joins = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join" and [arg.id for arg in node.args if isinstance(arg, ast.Name)] == ["WRITE_CLOSE_WAIT"]]
        self.assertEqual(len(joins), 1, "닫기 길의 `job.join(WRITE_CLOSE_WAIT)` 한 곳")


if __name__ == "__main__":
    unittest.main()
