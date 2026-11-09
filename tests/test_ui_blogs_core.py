"""블로그 관리 화면(P4b)의 순수 부분 시험(PySide6 없이 돈다 — CI 와 같은 조건) — 폼 규칙·값 다듬기·칸 옆 문장·변경 감지·복제 가능 여부·상태/동작(`BlogsController`)·뷰모델·가짜 공급자·실제 어댑터(임시 폴더).

지키는 것:
  1) 칸 표의 한도는 서비스(`topics/channels.py`)의 상수 그대로이고 폼 칸 이름은 서비스의 폼 칸과 같다. 슬롯·종류·후보 만들기 슬롯·색 프리셋·협찬 분야 이름은 서비스 표와 같다.
  2) 검사 판정은 서비스 생성자(`ChannelProfile`)와 **같다** — 경계·공백·위험한 표기·중복·형식을 수백 가지 입력으로 견준다(칸이 필수인 것은 화면만의 규칙).
  3) 칸 옆 문장은 쉬운 말이고 입력한 글을 되풀이하지 않으며 한도 숫자를 알려 준다.
  4) 입력은 지워지지 않는다: 저장이 실패해도(칸 오류·낡은 판·쓰기 실패) 초안이 그대로이고, 슬롯을 옮겨도 남으며, 성공하면 그 슬롯만 비운다.
  5) 쓰기는 사용자가 눌렀을 때만: 읽기·슬롯 고르기·칸 고치기는 파일에 닿지 않고(임시 폴더의 폴더 전체 바이트가 그대로) 칸에 문제가 있으면 서비스를 부르지 않으며 같은 일을 두 번 시작하지 않는다.
  6) 가짜 공급자(`--sample`·시험·사진)는 메모리에서만 일하고 같은 일을 서비스에 해 본 결과와 같다.
  7) 화면 코드(`ui/core`·`ui/qt`)에는 파일을 쓰는 호출이 없고, 쓰는 길은 어댑터가 부르는 서비스 함수 셋뿐이며 삭제는 확인(`confirmed=True`)이 있을 때만 불린다.
  8) 실제 블로그 이름·아이디는 어디에도 없다 — 예시는 가짜 이름뿐이다.
"""
import ast
import dataclasses
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import wording  # noqa: E402
from chanceblog_desktop.ui import adapters, blogs_adapter  # noqa: E402
from chanceblog_desktop.ui.core import app_state, blog_form as bf, blog_text, blogs, blogs_view, jobs, services, text, tokens  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731


def fake_slot_values(**changes):
    values = {"display_name": "예시 블로그 가", "blog_ref": "example-blog-a", "alias": "예시 별명", "channel_role": "예시 역할", "main_topics": "예시 주제 하나, 예시 주제 둘", "audience": "예시 독자",
              "tone": "예시 문체", "categories": "예시 분류 1, 예시 분류 2", "intro": "예시 소개글 한 줄", "color_preset": "warm_lifestyle", "profile_image": "", "cover_image": "",
              "monetization_focus": ("small_appliance",), "language": "ko", "generation_enabled": True}
    values.update(changes)
    return values


def load(controller, provider=None):
    data = (provider or controller.provider).load_blogs(SAFE, NEVER)
    controller.apply_loaded(data)
    return data


def new_controller(scenario="normal", **kwargs):
    provider = blogs.FakeBlogsProvider(scenario, **kwargs)
    controller = blogs_view.BlogsController(provider, jobs.JobRunner())
    load(controller)
    return controller


def drive(controller, starter):
    """저장·복제·삭제를 시작하고 끝까지 기다려 결과를 받는다(셸이 하는 일과 같다). → (시작 상태, 끝난 일: 'ok'·'failed'·None, 충돌이라 다시 읽어야 하나)."""
    results = {}
    status, detail = starter(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if status != "started":
        return status, detail, False
    detail.join(10)
    if "ok" in results:
        controller.apply_write_ok(results["ok"])
        return status, "ok", False
    return status, "failed", controller.apply_write_failed(results["failed"])


# ---- 1) 칸 표 ----------------------------------------------------------------------------------------------------------------------
class SpecTest(unittest.TestCase):
    def test_the_limits_are_the_service_constants(self):
        spec = bf.SPEC
        self.assertEqual((spec["display_name"].limit, spec["blog_ref"].limit, spec["alias"].limit, spec["channel_role"].limit, spec["audience"].limit, spec["tone"].limit, spec["intro"].limit),
                         (ch.MAX_NAME, ch.MAX_BLOG_REF, ch.MAX_ALIAS, ch.MAX_ROLE, ch.MAX_AUDIENCE, ch.MAX_TONE, ch.MAX_INTRO))
        self.assertEqual((spec["main_topics"].count, spec["main_topics"].limit, spec["categories"].count, spec["categories"].limit), (ch.MAX_MAIN_TOPICS, ch.MAX_TOPIC_WORD, ch.MAX_CATEGORIES, ch.MAX_CATEGORY_WORD))
        self.assertEqual((spec["profile_image"].limit, spec["cover_image"].limit), (ch.MAX_IMAGE_PATH, ch.MAX_IMAGE_PATH))
        self.assertEqual((ch.MAX_NAME, ch.MAX_BLOG_REF, ch.MAX_ALIAS, ch.MAX_ROLE, ch.MAX_AUDIENCE, ch.MAX_TONE, ch.MAX_INTRO, ch.MAX_IMAGE_PATH), (30, 200, 30, 60, 120, 120, 300, 260), "계획 표의 값")

    def test_the_field_names_match_the_service_form_fields_for_every_slot(self):
        for key in bp.SLOTS:
            names = [item.name for item in bf.fields_for(key)]
            self.assertEqual(sorted(names), sorted(bp.form_fields(key)), key)
            self.assertEqual(names[:3], ["display_name", "blog_ref", "language"], "필수 칸이 맨 위")
        self.assertEqual([spec.section for spec in bf.FIELDS], sorted((spec.section for spec in bf.FIELDS), key=bf.SECTIONS.index), "구역 순서대로 놓여 있다")
        required = [spec.name for spec in bf.FIELDS if spec.required]
        self.assertEqual(required, ["display_name", "blog_ref", "language", "generation_enabled"], "필수 넷(운영자 전달서) — 사용 여부(후보 만들기)는 스위치라 늘 값이 있어 '비었다' 는 문제 없이 필수 표시만 붙는다")
        for value in (True, False):
            self.assertEqual(bf.problem_of(bf.SPEC["generation_enabled"], value), "", "스위치는 꺼져 있어도 문제가 아니다")

    def test_slots_kinds_and_names_are_the_services(self):
        self.assertEqual((bf.SLOTS, bf.GENERATION_SLOTS, bf.SLOT_KINDS), (bp.SLOTS, bp.GENERATION_SLOTS, bp.SLOT_KINDS))
        for key in bp.SLOTS:
            self.assertEqual(bf.kind_of(key), bp.kind_of(key))
            self.assertEqual(T["blogs_slot_" + key], wording.CHANNEL_KO[key])
        self.assertEqual(bf.TAG_ORDER, tuple(wording.TAG_KO))
        for tag, name in wording.TAG_KO.items():
            self.assertEqual(T["bf_tag_" + tag], name)
        self.assertEqual(bf.PRESET_ORDER, ("", "warm_lifestyle", "cool_technology"))
        for preset, name in wording.COLOR_PRESET_KO.items():
            self.assertEqual(T["bf_preset_" + preset], name)
        for code, name in wording.LANGUAGE_KO.items():
            self.assertEqual(T["blogs_lang_" + code], name)

    def test_default_values_are_the_default_profile_and_the_default_slots_are_empty(self):
        for profile in ch.default_profiles():
            self.assertEqual(bf.default_values(profile.key), bf.raw_from_profile(profile))
            self.assertTrue(bf.is_empty_values(profile.key, bf.default_values(profile.key)))
            self.assertFalse(bf.default_values(profile.key)["blog_ref"])
        values = bf.default_values("naver_a")
        for change in ({"display_name": "다른 이름"}, {"blog_ref": "example-blog-a"}, {"alias": "예시"}, {"generation_enabled": False}, {"color_preset": "cool_technology"}, {"monetization_focus": ()}):
            self.assertFalse(bf.is_empty_values("naver_a", {**values, **change}), change)
        self.assertTrue(bf.is_empty_values("naver_a", {**values, "alias": "   "}), "공백만 있는 것은 비어 있다")


# ---- 2) 값 다듬기 ------------------------------------------------------------------------------------------------------------------
class NormalizeTest(unittest.TestCase):
    def test_clean_line_is_the_services_and_words_are_split_on_commas_semicolons_and_newlines(self):
        from chanceblog_desktop.content.profiles import clean_line
        zero = chr(0x200B)
        for raw in ("  앞뒤   공백  ", "탭\t글", "줄\n바꿈", f"보이지{zero}않는", "", "   ", "정상 문장"):
            self.assertEqual(bf.clean_line(raw), clean_line(raw))
        self.assertEqual(bf.clean_line(None), "")
        self.assertEqual(bf.split_words("가, 나;다\n라，마、바"), ("가", "나", "다", "라", "마", "바"))
        self.assertEqual(bf.split_words(" 가 ,, 나  나 ,"), ("가", "나 나"))
        self.assertEqual(bf.split_words("숙박·여행, 업무 자동화"), ("숙박·여행", "업무 자동화"), "가운뎃점은 낱말 안에 쓰이므로 나누지 않는다")
        self.assertEqual(bf.split_words(None), ())

    def test_each_kind_of_field_is_normalized_for_the_service(self):
        spec = bf.SPEC
        self.assertEqual(bf.normalize(spec["display_name"], "  내   블로그 "), "내 블로그")
        self.assertEqual(bf.normalize(spec["blog_ref"], "  example-blog-a \n"), "example-blog-a")
        self.assertEqual(bf.normalize(spec["main_topics"], "가, 나"), ("가", "나"))
        self.assertEqual(bf.normalize(spec["color_preset"], ""), None)
        self.assertEqual(bf.normalize(spec["color_preset"], "warm_lifestyle"), "warm_lifestyle")
        self.assertEqual(bf.normalize(spec["generation_enabled"], 1), True)
        self.assertEqual(bf.normalize(spec["monetization_focus"], ("work_automation", "small_appliance", "x_custom")), ("small_appliance", "work_automation", "x_custom"), "이름표가 있는 분야는 정해진 순서로, 없는 값은 뒤에 그대로")
        self.assertEqual(bf.normalize(spec["language"], "en"), "en")

    def test_a_change_of_only_spaces_or_tag_order_is_not_a_change(self):
        base = fake_slot_values()
        self.assertEqual(bf.dirty_names("naver_a", base, {**base, "display_name": "  예시 블로그 가  ", "main_topics": "예시 주제 하나 ,  예시 주제 둘"}), ())
        self.assertEqual(bf.dirty_names("naver_a", {**base, "monetization_focus": ("small_appliance", "pc_parts")}, {**base, "monetization_focus": ("pc_parts", "small_appliance")}), ())
        self.assertEqual(bf.dirty_names("naver_a", base, {**base, "alias": "다른 별명", "language": "en"}), ("language", "alias"))
        self.assertEqual(bf.dirty_names("blogger_ko", bf.default_values("blogger_ko"), {**bf.default_values("blogger_ko"), "generation_enabled": True}), (), "후보 만들기 칸은 네이버 슬롯만 가진다")


# ---- 3) 검사 — 서비스 생성자와 같은 판정 ----------------------------------------------------------------------------------------------------
def service_rejects(name, typed):
    try:
        dataclasses.replace(bp.default_profile("naver_a"), **{name: typed})
    except AppError as error:
        if error.requested_code != "CONTENT_INVALID":
            raise
        return True
    return False


class VerdictTest(unittest.TestCase):
    def corpus_lines(self, limit):
        zero, back = chr(0x200B), chr(92)
        return ["", "a", "가" * limit, "가" * (limit + 1), "  앞뒤  공백  ", "탭\t글", "줄\n바꿈", "<b>태그</b>", "<script", "javascript: x", "JavaScript:alert(1)", "{{템플릿}}", "{% x %}", "onclick=run()", "a<b 비교", "Map<String, List<Integer>>",
                f"보이지{zero}않는", "정상 문장입니다", "a" * (limit - 1) + "<", f"경로{back}섞임"]

    def test_line_fields_are_judged_like_the_service(self):
        for name in ("display_name", "alias", "channel_role", "audience", "tone", "intro"):
            spec = bf.SPEC[name]
            for raw in self.corpus_lines(spec.limit):
                typed = bf.normalize(spec, raw)
                mine = bool(bf.problem_of(spec, typed))
                with self.subTest(field=name, raw=raw[:20]):
                    if spec.required and not typed:
                        self.assertTrue(mine)
                    self.assertEqual(mine, service_rejects(name, typed))

    def test_word_fields_are_judged_like_the_service(self):
        words = lambda count, size=3: ", ".join(f"{'가' * size}{index}" for index in range(count))  # noqa: E731
        for name in ("main_topics", "categories"):
            spec = bf.SPEC[name]
            cases = ["", "가", "가, 나", "가, 가", "A, a", words(spec.count), words(spec.count + 1), "가" * spec.limit, "가" * (spec.limit + 1), "<b>x</b>, 나", "가,,나", " , ", "가 나, 다", "javascript: 가, 나", "{{x}}"]
            for raw in cases:
                typed = bf.normalize(spec, raw)
                with self.subTest(field=name, raw=raw[:20]):
                    self.assertEqual(bool(bf.problem_of(spec, typed)), service_rejects(name, typed))

    def test_the_blog_id_or_address_is_judged_like_the_service_except_that_the_form_requires_it(self):
        spec = bf.SPEC["blog_ref"]
        cases = ["example-blog-a", "a", "a" * 64, "a" * 65, "-start", ".", "a_b.c-d", "a b", "한글아이디", "https://blog.example.com/x", "https://" + "a" * 190, "https://" + "a" * 200, "http://insecure.example.com", "https://user@example.com/x",
                 "https://example.com/x#frag", "https://example.com/ x", "<b>", "javascript:alert(1)", "HTTPS://Example.com/x", "https://", "ftp://x"]
        for raw in cases:
            typed = bf.normalize(spec, raw)
            with self.subTest(raw=raw[:30]):
                self.assertEqual(bool(bf.problem_of(spec, typed)), service_rejects("blog_ref", typed))
        self.assertEqual(bf.problem_of(spec, ""), "required", "서비스는 빈 ID 를 받지만(빈 슬롯) 폼은 저장할 때 꼭 있어야 한다")
        self.assertFalse(service_rejects("blog_ref", ""))

    def test_paths_choices_and_tags_are_judged_like_the_service(self):
        back = chr(92)
        for name in ("profile_image", "cover_image"):
            spec = bf.SPEC[name]
            for raw in ("", "C:" + back + "그림" + back + "a.png", "/home/a.png", "a" * ch.MAX_IMAGE_PATH, "a" * (ch.MAX_IMAGE_PATH + 1), "data:image/png;base64,xx", "DATA:x", "javascript:x", "vbscript:x", "<x>", "그림 폴더/내 사진.png"):
                typed = bf.normalize(spec, raw)
                with self.subTest(field=name, raw=raw[:20]):
                    self.assertEqual(bool(bf.problem_of(spec, typed)), service_rejects(name, typed))
        for raw in ("ko", "en", "fr", "", "KO"):
            self.assertEqual(bool(bf.problem_of(bf.SPEC["language"], raw)), service_rejects("language", raw), raw)
        for raw in ("", "warm_lifestyle", "cool_technology", "neon", "WARM_LIFESTYLE"):
            typed = bf.normalize(bf.SPEC["color_preset"], raw)
            self.assertEqual(bool(bf.problem_of(bf.SPEC["color_preset"], typed)), service_rejects("color_preset", typed), raw)
        spec = bf.SPEC["monetization_focus"]
        for tags in ((), ("small_appliance",), tuple(bf.TAG_ORDER), ("custom_tag",), ("Not A Tag",)):
            typed = bf.normalize(spec, tags)
            extra = tuple(tag for tag in typed if tag not in bf.TAG_ORDER)
            allowed = not bf.problem_of(spec, typed, extra) or tags == ("Not A Tag",)
            self.assertEqual(not allowed or bool(tags == ("Not A Tag",)), service_rejects("monetization_focus", typed), tags)
        self.assertEqual(bf.problem_of(spec, ("custom_tag",)), "bad_choice", "목록에 없는 분야는 화면에서 새로 만들 수 없다(이미 있는 것은 보존)")
        self.assertEqual(bf.problem_of(spec, ("custom_tag",), ("custom_tag",)), "")

    def test_the_reasons_are_the_specific_ones(self):
        spec = bf.SPEC
        self.assertEqual(bf.problem_of(spec["display_name"], ""), "required")
        self.assertEqual(bf.problem_of(spec["alias"], "가" * 31), "too_long")
        self.assertEqual(bf.problem_of(spec["alias"], "<b>x</b>"), "markup")
        self.assertEqual(bf.problem_of(spec["main_topics"], ("가",) * 2), "duplicate")
        self.assertEqual(bf.problem_of(spec["main_topics"], tuple(str(i) for i in range(11))), "too_many")
        self.assertEqual(bf.problem_of(spec["main_topics"], ("가" * 31,)), "item_too_long")
        self.assertEqual(bf.problem_of(spec["blog_ref"], "a b"), "bad_ref")
        self.assertEqual(bf.problem_of(spec["blog_ref"], "a" * 201), "too_long")
        self.assertEqual(bf.problem_of(spec["profile_image"], "data:x"), "bad_path")
        self.assertEqual(bf.problem_of(spec["language"], "fr"), "bad_choice")


class MessageTest(unittest.TestCase):
    def test_every_problem_has_an_easy_sentence_that_never_repeats_the_input(self):
        secret = "비밀처럼 보이는 입력 글 12345"
        for spec in bf.FIELDS:
            for problem in ("required", "too_long", "too_many", "item_too_long", "duplicate", "markup", "bad_ref", "bad_choice", "bad_path", "key_shape", "invalid"):
                sentence = bf.problem_text(spec, problem, secret)
                self.assertTrue(sentence, (spec.name, problem))
                self.assertNotIn(secret, sentence)
                self.assertNotRegex(sentence, r"[\[\]{}]|Traceback|Exception|CONTENT_|AppError|None\b")
        self.assertEqual(bf.problem_text(bf.SPEC["alias"], ""), "")
        self.assertIn("30", bf.problem_text(bf.SPEC["alias"], "too_long", "가" * 35))
        self.assertIn("35", bf.problem_text(bf.SPEC["alias"], "too_long", "가" * 35), "지금 몇 자인지 알려 준다")
        self.assertIn("10", bf.problem_text(bf.SPEC["main_topics"], "too_many", ", ".join("가" + str(i) for i in range(12))))
        self.assertEqual(bf.problem_text(bf.SPEC["alias"], "알 수 없는 문제"), T["bf_err_invalid"], "모르는 문제 이름은 일반 문장")

    def test_hints_carry_the_limits(self):
        self.assertIn("30", bf.SPEC["display_name"].hint())
        self.assertIn("10", bf.SPEC["main_topics"].hint())
        self.assertEqual(bf.SPEC["language"].hint(), T["bf_hint_language"])
        for spec in bf.FIELDS:
            self.assertTrue(spec.label)
            self.assertNotRegex(spec.hint(), r"\{|\}")


# ---- 복제 가능 여부 -----------------------------------------------------------------------------------------------------------------
class CloneStateTest(unittest.TestCase):
    def slots(self, **registered):
        out = {key: bf.default_values(key) for key in bf.SLOTS}
        for key, change in registered.items():
            out[key] = {**out[key], "blog_ref": "example-blog", **change}
        return out

    def test_clone_follows_the_service_rules_on_many_arrangements(self):
        for registered in ({}, {"naver_a": {}}, {"naver_a": {}, "naver_b": {}}, {"naver_a": {}, "naver_b": {"alias": "예시"}}, {"blogger_ko": {}}, {"blogger_ko": {}, "blogger_en": {}}, {"github_pages": {}},
                           {"naver_b": {"display_name": "다른 이름"}}):
            slots = self.slots(**registered)
            profiles = tuple(dataclasses.replace(profile, **{name: (tuple(split) if isinstance(split := bf.typed_values(profile.key, slots[profile.key])[name], tuple) else split) for name in bp.form_fields(profile.key)})
                             for profile in ch.default_profiles())
            for key in bf.SLOTS:
                allowed, reason, target = bf.clone_state(slots, key)
                expected = bp.clone_target(profiles, key) if profiles and bp.is_registered(next(p for p in profiles if p.key == key)) else None
                with self.subTest(registered=sorted(registered), key=key):
                    self.assertEqual(target if allowed else None, expected)
                    self.assertEqual(allowed, expected is not None)
                    self.assertEqual(bool(reason), not allowed)

    def test_the_reasons_are_easy_sentences(self):
        none = bf.clone_state(self.slots(), "naver_a")
        self.assertEqual(none, (False, T["blogs_clone_no_source"], None))
        full = bf.clone_state(self.slots(naver_a={}, naver_b={}), "naver_a")
        self.assertEqual(full, (False, T["blogs_clone_no_target"], None))
        self.assertEqual(bf.clone_state(self.slots(github_pages={}), "github_pages"), (False, T["blogs_clone_no_target"], None), "같은 종류의 슬롯이 없다")
        self.assertEqual(bf.clone_state(self.slots(naver_a={}), "naver_a"), (True, "", "naver_b"))
        self.assertEqual(bf.clone_state(self.slots(blogger_en={}), "blogger_en"), (True, "", "blogger_ko"))


# ---- 4) 상태·동작: 입력 유지 · 쓰기는 누를 때만 --------------------------------------------------------------------------------------------
class ControllerTest(unittest.TestCase):
    def test_loading_selects_the_default_slot_and_shows_the_five_cards(self):
        controller = new_controller()
        view = controller.view()
        self.assertEqual((view["state"], view["selected"], len(view["list"]["cards"])), ("normal", "naver_a", 5))
        self.assertEqual([card["key"] for card in view["list"]["cards"]], list(bf.SLOTS))
        self.assertTrue(view["sample"])
        self.assertEqual(view["form"]["key"], "naver_a")
        blank = blogs_view.BlogsController(blogs.FakeBlogsProvider(), jobs.JobRunner())
        self.assertEqual((blank.state, blank.view()["form"], blank.view()["list"]["cards"]), ("loading", None, []))

    def test_selecting_and_editing_never_touch_the_provider_and_keep_drafts_per_slot(self):
        controller = new_controller()
        calls = list(controller.provider.calls)
        self.assertTrue(controller.select("naver_b"))
        self.assertTrue(controller.edit("alias", "새 별명"))
        self.assertTrue(controller.is_dirty("naver_b"))
        self.assertTrue(controller.select("naver_a"))
        self.assertTrue(controller.edit("tone", "새 문체"))
        self.assertTrue(controller.select("naver_b"))
        self.assertEqual(controller.values("naver_b")["alias"], "새 별명", "슬롯을 옮겼다 돌아와도 초안이 남는다")
        self.assertEqual({card["key"]: card["unsaved"] for card in controller.view()["list"]["cards"]}, {"github_pages": False, "blogger_en": False, "blogger_ko": False, "naver_a": True, "naver_b": True})
        self.assertEqual(controller.provider.calls, calls, "고르기·고치기는 공급자(파일)를 부르지 않는다")
        self.assertFalse(controller.select("no_slot"))
        self.assertFalse(controller.edit("no_field", "x"))
        self.assertFalse(controller.edit("generation_enabled", False) if controller.selected == "blogger_ko" else False)

    def test_putting_a_value_back_or_changing_only_spaces_drops_the_draft(self):
        controller = new_controller()
        controller.edit("alias", "새 별명")
        self.assertTrue(controller.is_dirty("naver_a"))
        controller.edit("alias", controller.base_raw("naver_a")["alias"] + "  ")
        self.assertFalse(controller.is_dirty("naver_a"))
        self.assertNotIn("naver_a", controller.drafts)

    def test_revert_drops_the_draft_and_its_messages_of_that_slot_only(self):
        controller = new_controller()
        controller.edit("alias", "새 별명")
        controller.select("naver_b")
        controller.edit("alias", "다른 별명")
        controller.select("naver_a")
        self.assertTrue(controller.revert())
        self.assertFalse(controller.is_dirty("naver_a"))
        self.assertTrue(controller.is_dirty("naver_b"))

    def test_saving_without_a_change_or_with_a_wrong_value_never_calls_the_provider(self):
        controller = new_controller()
        calls = list(controller.provider.calls)
        self.assertEqual(controller.start_save(), ("nothing", None))
        controller.edit("display_name", "")
        controller.edit("alias", "가" * 40)
        status, problems = controller.start_save()
        self.assertEqual(status, "invalid")
        self.assertEqual(problems, {"display_name": "required", "alias": "too_long"})
        self.assertEqual(controller.provider.calls, calls, "칸에 문제가 있으면 서비스를 부르지 않는다")
        self.assertEqual(controller.notice, ("error", T["blogs_save_invalid"]))
        errors = {field["name"]: field["error"] for section in controller.view()["form"]["sections"] for field in section["fields"] if field["error"]}
        self.assertEqual(set(errors), {"display_name", "alias"}, "저장을 시도하면 문제 칸의 오류가 보인다")
        self.assertIn("30", errors["alias"])

    def test_errors_show_only_for_touched_fields_until_a_save_is_tried(self):
        controller = new_controller("empty")
        errors = lambda: {field["name"]: field["error"] for section in controller.view()["form"]["sections"] for field in section["fields"] if field["error"]}  # noqa: E731
        self.assertEqual(errors(), {}, "처음 보는 빈 등록 칸은 오류로 시작하지 않는다")
        controller.edit("alias", "가" * 40)
        self.assertEqual(list(errors()), ["alias"], "고친 칸만 보인다")
        controller.edit("display_name", "")
        self.assertEqual(set(errors()), {"alias", "display_name"})
        controller.revert()
        self.assertEqual(errors(), {})

    def test_a_successful_save_replaces_the_data_and_empties_only_that_slots_draft(self):
        controller = new_controller()
        controller.edit("alias", "저장할 별명")
        controller.select("naver_b")
        controller.edit("alias", "저장 안 할 별명")
        controller.select("naver_a")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual(controller.base_raw("naver_a")["alias"], "저장할 별명")
        self.assertFalse(controller.is_dirty("naver_a"))
        self.assertTrue(controller.is_dirty("naver_b"), "다른 슬롯의 초안은 그대로")
        self.assertEqual(controller.notice, ("ok", T["blogs_saved"]))
        self.assertEqual(controller.provider.calls[-1], "save")

    def test_a_failed_save_keeps_every_typed_value_and_says_why_in_an_easy_sentence(self):
        controller = new_controller()
        controller.edit("alias", "고친 별명")
        controller.edit("intro", "고친 소개글")
        before = dict(controller.values("naver_a"))
        controller.provider.save_blog = lambda *a: (_ for _ in ()).throw(blogs.BlogFailure("x", code="FILE_WRITE_FAILED", kind="io"))
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", False))
        self.assertEqual(controller.values("naver_a"), before, "실패해도 입력은 그대로다")
        self.assertTrue(controller.is_dirty("naver_a"))
        self.assertEqual(controller.notice, ("error", T["blogs_fail_io"]))
        self.assertIsNone(controller.pending)
        for kind, key in blogs_view.FAILURE_TEXT.items():
            controller.pending = {"kind": "save", "key": "naver_a", "target": None}
            controller.apply_write_failed(blogs.BlogFailure("무엇이든", code="X", kind=kind))
            self.assertEqual(controller.notice, ("error", T[key]), kind)
            self.assertEqual(controller.values("naver_a"), before)

    def test_a_service_rejection_marks_the_field_and_keeps_the_values(self):
        controller = new_controller()
        controller.edit("alias", "고친 별명")
        controller.provider.save_blog = lambda *a: (_ for _ in ()).throw(blogs.BlogFailure("x", code="CONTENT_INVALID", kind="invalid", problems={"alias": "key_shape"}))
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", False))
        field = next(item for section in controller.view()["form"]["sections"] for item in section["fields"] if item["name"] == "alias")
        self.assertEqual(field["error"], T["bf_err_key_shape"])
        self.assertEqual(controller.values("naver_a")["alias"], "고친 별명")
        controller.edit("alias", "다시 고친 별명")
        field = next(item for section in controller.view()["form"]["sections"] for item in section["fields"] if item["name"] == "alias")
        self.assertEqual(field["error"], "", "그 칸을 다시 고치면 서비스가 알려 준 문제는 사라진다")

    def test_a_stale_version_asks_for_a_reload_and_keeps_the_draft_then_says_what_happened(self):
        controller = new_controller()
        controller.edit("alias", "고친 별명")
        controller.provider.revision += 1                                          # 다른 창이 먼저 저장했다
        status, outcome, reload = drive(controller, controller.start_save)
        self.assertEqual((status, outcome, reload), ("started", "failed", True))
        self.assertEqual(controller.values("naver_a")["alias"], "고친 별명")
        self.assertEqual(controller.notice, ("error", T["blogs_fail_conflict"]))
        load(controller)
        self.assertEqual(controller.notice, ("warning", T["blogs_stale_reloaded"]))
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False), "다시 불러온 뒤에는 저장된다")
        self.assertEqual(controller.base_raw("naver_a")["alias"], "고친 별명")

    def test_unedited_fields_follow_the_latest_saved_value_so_a_reload_never_reverts_another_windows_change(self):
        """F1(독립 검증) — 초안은 고친 칸만 들고 있다: 다른 창이 바꾼 '고치지 않은 칸'은 다시 읽은 뒤에도 최신 값이 보이고, 저장해도 되돌아가지 않는다."""
        controller = new_controller()
        controller.edit("display_name", "고친 표시 이름")
        controller.edit("alias", "고친 별명")
        self.assertEqual(set(controller.drafts["naver_a"]), {"display_name", "alias"}, "초안에는 고친 칸만 있다(저장된 값 전체를 복사해 두지 않는다)")
        provider = controller.provider
        provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], tone="다른 창이 바꾼 문체")           # 다른 창이 '고치지 않은 칸'을 먼저 저장했다
        provider.revision += 1
        load(controller)                                                           # 화면이 최신 내용을 다시 읽는다
        values = controller.values("naver_a")
        self.assertEqual((values["tone"], values["display_name"], values["alias"]), ("다른 창이 바꾼 문체", "고친 표시 이름", "고친 별명"))
        self.assertEqual(set(controller.dirty_names("naver_a")), {"display_name", "alias"}, "'저장 전 변경' 에 안 고친 문체가 끼지 않는다")
        form = {field["name"]: field for section in controller.view()["form"]["sections"] for field in section["fields"]}
        self.assertEqual((form["tone"]["value"], form["tone"]["changed"], form["alias"]["changed"]), ("다른 창이 바꾼 문체", False, True), "화면 칸도 최신 값이고 고친 칸만 '바뀜' 표시다")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        saved = provider.slots["naver_a"]
        self.assertEqual((saved.tone, saved.display_name, saved.alias), ("다른 창이 바꾼 문체", "고친 표시 이름", "고친 별명"), "저장해도 다른 창의 변경이 낡은 값으로 되돌아가지 않는다")

    def test_the_stale_version_path_keeps_the_other_windows_change_on_unedited_fields_and_the_typed_value_on_edited_ones(self):
        """F1 의 낡은 판 길 — 저장 거절 → 다시 읽기 → 확인 뒤 저장: 안 고친 칸은 최신 값, 고친 칸은 사용자가 친 값(둘 다 바꾼 칸도 사용자가 정한다)."""
        controller = new_controller()
        controller.edit("alias", "고친 별명")
        provider = controller.provider
        provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], tone="다른 창이 바꾼 문체", intro="다른 창이 바꾼 소개", alias="다른 창이 바꾼 별명")
        provider.revision += 1
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", True))
        load(controller)
        self.assertEqual(controller.notice, ("warning", T["blogs_stale_reloaded"]))
        values = controller.values("naver_a")
        self.assertEqual((values["tone"], values["intro"], values["alias"]), ("다른 창이 바꾼 문체", "다른 창이 바꾼 소개", "고친 별명"))
        self.assertEqual(list(controller.dirty_names("naver_a")), ["alias"], "고친 칸만 바뀐 것이다")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False), "확인한 뒤 다시 저장하면 저장된다")
        saved = provider.slots["naver_a"]
        self.assertEqual((saved.alias, saved.tone, saved.intro), ("고친 별명", "다른 창이 바꾼 문체", "다른 창이 바꾼 소개"))

    def test_a_field_another_window_saved_with_the_same_value_stops_being_a_change_after_a_reload(self):
        controller = new_controller()
        controller.edit("alias", "같은 별명")
        provider = controller.provider
        provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], alias="같은 별명")
        provider.revision += 1
        load(controller)
        self.assertFalse(controller.is_dirty("naver_a"), "다른 창이 같은 값으로 저장했으니 더 바뀐 것이 없다")
        self.assertEqual(controller.start_save(), ("nothing", None))
        self.assertEqual(controller.values("naver_a")["alias"], "같은 별명")

    def test_a_write_in_progress_blocks_a_second_start_and_everything_else_that_changes_state(self):
        controller = new_controller(delay=0.4)
        controller.edit("alias", "고친 별명")
        status, job = controller.start_save()
        self.assertEqual(status, "started")
        self.assertTrue(controller.busy)
        self.assertEqual(controller.start_save(), ("busy", None))
        self.assertEqual(controller.start_clone()[0], "busy")
        self.assertEqual(controller.start_clear()[0], "busy")
        self.assertFalse(controller.select("naver_b"))
        self.assertFalse(controller.edit("alias", "또 고침"))
        self.assertFalse(controller.revert())
        self.assertIsNone(controller.start_load())
        form = controller.view()["form"]
        self.assertTrue(all(not action["enabled"] for action in form["actions"]))
        self.assertTrue(all(field["disabled"] for section in form["sections"] for field in section["fields"]))
        job.join(10)
        self.assertEqual(controller.provider.calls.count("save"), 1)

    def test_clone_fills_the_empty_slot_selects_it_and_never_overwrites(self):
        controller = new_controller()
        self.assertEqual(controller.clone_info("naver_a")[0], False, "네이버 B 가 등록되어 있어 복제할 자리가 없다")
        controller.select("blogger_ko")
        allowed, reason, target = controller.clone_info()
        self.assertEqual((allowed, reason, target), (True, "", "blogger_en"))
        self.assertEqual(drive(controller, controller.start_clone), ("started", "ok", False))
        self.assertEqual(controller.selected, "blogger_en")
        self.assertEqual(controller.base_raw("blogger_en")["blog_ref"], "example-blog-c")
        self.assertEqual(controller.notice, ("ok", T["blogs_cloned"]))
        self.assertEqual(controller.start_clone()[0], "unavailable", "이제 빈 자리가 없다")
        fresh = new_controller()
        fresh.select("blogger_ko")
        fresh.edit("alias", "저장 전 변경")
        self.assertEqual(fresh.clone_info(), (False, T["blogs_clone_unsaved"], "blogger_en"), "저장하지 않은 변경이 있으면 먼저 저장하게 한다")

    def test_clear_needs_a_registered_slot_and_empties_it_but_the_slot_stays(self):
        controller = new_controller()
        controller.select("github_pages")
        self.assertFalse(controller.can_clear())
        self.assertEqual(controller.start_clear()[0], "nothing")
        controller.select("naver_a")
        self.assertTrue(controller.can_clear())
        dialog = controller.delete_dialog()
        self.assertIn("예시 블로그 가", dialog["body"])
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), (T["blogs_del_title"], T["blogs_del_ok"], T["blogs_del_cancel"]))
        self.assertEqual(drive(controller, controller.start_clear), ("started", "ok", False))
        self.assertEqual(controller.notice, ("ok", T["blogs_cleared"]))
        self.assertEqual(len(controller.view()["list"]["cards"]), 5, "슬롯은 사라지지 않는다")
        self.assertFalse(controller.slot_map()["naver_a"].registered)
        self.assertFalse(controller.can_clear())

    def test_the_delete_dialog_says_what_is_erased_that_it_cannot_be_undone_and_what_stays(self):
        controller = new_controller()
        body = controller.delete_dialog()["body"]
        for part in ("비워져요", "되돌릴 수 없어요", "후보·초안·발행 기록은 지워지지 않아요", "사라지지 않고"):
            self.assertIn(part, body)

    def test_a_read_error_keeps_what_was_shown_and_an_unexpected_exception_becomes_an_easy_error(self):
        controller = new_controller()
        controller.apply_load_failed(jobs.JobFailure("읽기 실패", code="TOPIC_FILE_INVALID"), None)
        self.assertEqual(controller.state, "error")
        self.assertIsNotNone(controller.data, "이전에 보이던 내용은 지우지 않는다")
        view = controller.view("code: X")
        self.assertEqual((view["state"], view["error"]["diag"]), ("error", "code: X"))
        self.assertIsNone(view["form"])
        controller.apply_unexpected(ValueError("값 비밀 12345"), None)
        self.assertIsNone(controller.data)
        self.assertNotIn("12345", repr(controller.failure.__dict__))
        self.assertEqual(controller.failure.code, "ValueError")


# ---- 뷰모델 -------------------------------------------------------------------------------------------------------------------------
class ViewModelTest(unittest.TestCase):
    def test_cards_show_registered_and_empty_slots_with_chips_and_accessible_names(self):
        view = new_controller().view()
        cards = {card["key"]: card for card in view["list"]["cards"]}
        self.assertTrue(cards["naver_a"]["registered"])
        self.assertEqual((cards["naver_a"]["headline"], cards["naver_a"]["status"]["text"], cards["naver_a"]["preset"], cards["naver_b"]["preset"]), ("예시 블로그 가", "등록됨", "warm_lifestyle", "cool_technology"))
        self.assertEqual(cards["naver_a"]["title"], "네이버 A")
        self.assertEqual([chip["text"] for chip in cards["naver_a"]["chips"]], ["한국어", "후보 만들기 켜짐"])
        self.assertEqual([chip["text"] for chip in cards["blogger_ko"]["chips"]], ["한국어", "후보 만들기 지원 전"])
        empty = cards["github_pages"]
        self.assertEqual((empty["registered"], empty["headline"], empty["status"]["text"], empty["preset"]), (False, T["blogs_card_empty_title"], "비어 있음", ""))
        self.assertIn("비어 있음", empty["a11y"])
        self.assertIn("선택됨", cards["naver_a"]["a11y"])
        self.assertNotIn("선택됨", cards["naver_b"]["a11y"])
        self.assertEqual([card["selected"] for card in view["list"]["cards"]].count(True), 1)

    def test_the_form_has_the_required_four_first_then_the_optional_fields_and_the_color_and_images_last(self):
        form = new_controller().view()["form"]
        names = [[field["name"] for field in section["fields"]] for section in form["sections"]]
        self.assertEqual(names[0], ["display_name", "blog_ref", "language", "generation_enabled"])
        self.assertEqual(names[1], ["alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "monetization_focus"])
        # 의도적 갱신(P4c, D-240): 구역이 셋에서 넷이 되었다 — 새 '주제 설정' 구역이 자세한 정보와 모양 사이에 들어갔다(모양이 맨 끝이라는 것은 그대로다)
        self.assertEqual([section["key"] for section in form["sections"]], ["basic", "more", "topic", "look"])
        self.assertEqual(names[2], ["priority_keywords", "exclude_keywords", "preferred_post_types"])
        self.assertEqual(names[3], ["color_preset", "profile_image", "cover_image"])
        required = [field["name"] for section in form["sections"] for field in section["fields"] if field["required"]]
        self.assertEqual(required, ["display_name", "blog_ref", "language", "generation_enabled"], "필수 넷 — 네이버 슬롯에서는 사용 여부까지")
        controller = new_controller()
        controller.select("blogger_ko")
        other = [field["name"] for section in controller.view()["form"]["sections"] for field in section["fields"] if field["required"]]
        self.assertEqual(other, ["display_name", "blog_ref", "language"], "나머지 슬롯의 사용 여부는 꺼진 채 잠겨 있어 필수 표시가 없다")
        self.assertEqual([action["key"] for action in form["actions"]], ["save", "revert", "clone", "delete"])
        self.assertEqual([action["kind"] for action in form["actions"]], ["primary", "secondary", "secondary", "danger"], "화면당 주요 행동은 하나, 위험 행동은 하나")
        self.assertEqual(form["title"], "네이버 A 정보")
        self.assertEqual(new_controller("empty").view()["form"]["title"], "네이버 A 등록")

    def test_the_candidate_switch_is_a_real_choice_for_naver_and_a_disabled_one_with_a_reason_for_the_others(self):
        controller = new_controller()
        field = lambda: next(item for item in controller.view()["form"]["sections"][0]["fields"] if item["name"] == "generation_enabled")  # noqa: E731
        self.assertFalse(field()["disabled"])
        for key in ("blogger_ko", "blogger_en", "github_pages"):
            controller.select(key)
            self.assertTrue(field()["disabled"], key)
            self.assertEqual(field()["disabled_reason"], T["bf_hint_generation_off"])
            self.assertFalse(controller.edit("generation_enabled", True))

    def test_the_actions_are_enabled_by_the_state_and_say_why_when_they_are_not(self):
        controller = new_controller()
        actions = lambda: {action["key"]: action for action in controller.view()["form"]["actions"]}  # noqa: E731
        self.assertEqual((actions()["save"]["enabled"], actions()["save"]["reason"]), (False, T["blogs_save_nothing"]))
        self.assertEqual((actions()["revert"]["enabled"], actions()["revert"]["reason"]), (False, T["blogs_revert_nothing"]))
        self.assertEqual((actions()["clone"]["enabled"], actions()["clone"]["reason"]), (False, T["blogs_clone_no_target"]))
        self.assertTrue(actions()["delete"]["enabled"])
        controller.edit("alias", "고침")
        self.assertTrue(actions()["save"]["enabled"] and actions()["revert"]["enabled"])
        controller.select("github_pages")
        self.assertEqual((actions()["delete"]["enabled"], actions()["delete"]["reason"]), (False, T["blogs_delete_empty"]))
        self.assertEqual(actions()["clone"]["reason"], T["blogs_clone_no_source"])

    def test_a_second_slot_with_the_same_blog_id_gets_a_warning_not_an_error(self):
        controller = new_controller()
        controller.select("naver_b")
        controller.edit("blog_ref", "EXAMPLE-blog-a")
        field = next(item for item in controller.view()["form"]["sections"][0]["fields"] if item["name"] == "blog_ref")
        self.assertEqual((field["error"], field["warning"]), ("", T["bf_warn_same_ref"]))
        self.assertEqual(controller.start_save()[0], "started", "경고는 저장을 막지 않는다")

    def test_unknown_sponsor_tags_are_kept_and_said_so(self):
        controller = new_controller()
        slot = controller.slot_map()["naver_a"]
        controller.data = dataclasses.replace(controller.data, slots=tuple(dataclasses.replace(s, monetization_focus=("small_appliance", "custom_tag")) if s.key == "naver_a" else s for s in controller.data.slots))
        field = next(item for section in controller.view()["form"]["sections"] for item in section["fields"] if item["name"] == "monetization_focus")
        self.assertEqual(field["extra"], T["bf_extra_tags"].format(n=1))
        self.assertTrue(controller.toggle_tag("ai_service"))
        self.assertEqual(sorted(controller.values("naver_a")["monetization_focus"]), ["ai_service", "custom_tag", "small_appliance"], "이름표가 없는 값은 그대로 남는다")
        self.assertEqual(bf.typed_values("naver_a", controller.values("naver_a"))["monetization_focus"], ("small_appliance", "ai_service", "custom_tag"))
        self.assertFalse(controller.toggle_tag("no_such_tag"))
        self.assertIsNotNone(slot)

    def test_nothing_in_the_view_model_is_a_code_a_python_list_or_a_path(self):
        controller = new_controller()
        controller.edit("alias", "가" * 40)
        controller.start_save()
        strings = []

        def walk(value):
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key not in ("key", "name", "kind", "preset", "tone", "value", "level", "state", "selected"):
                        walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(controller.view())
        self.assertGreater(len(strings), 40)
        for item in strings:
            self.assertNotRegex(item, r"\[['\"]|Traceback|Exception|\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b|[A-Za-z]:[\\/]|AppError|None\b|True\b|False\b", item)
            for word in text.FORBIDDEN:
                self.assertNotIn(word, item)

    def test_the_sample_tag_and_the_missing_file_note_follow_the_data(self):
        self.assertTrue(new_controller().view()["sample"])
        self.assertEqual(new_controller().view()["banners"], [], "예시 데이터에는 파일 안내가 없다")
        real = new_controller()
        real.data = dataclasses.replace(real.data, sample=False, state="missing")
        self.assertEqual(real.view()["banners"], [("info", T["blogs_missing_note"])])
        self.assertFalse(real.view()["sample"])

    def test_key_shaped_text_in_a_saved_profile_is_masked_on_the_cards_and_in_the_delete_dialog(self):
        """L1(독립 검증) — 손으로 고친 파일에 키 모양이 들어 있어도 카드·삭제 확인창에는 가려서 보인다(`bf.shown` — 가리기가 먼저, 자르기가 나중)."""
        controller = new_controller()
        secret = "AK" + "IA" + "ABCDEFGHIJKLMNOP"                                    # 키 모양의 가짜 값 — 조각으로 나눠 적어 저장소에 키 문자열이 없다
        provider = controller.provider
        provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], display_name="블로그 " + secret, blog_ref=secret, channel_role="역할 " + secret)
        load(controller)
        controller.select("naver_a")
        card = next(card for card in controller.view()["list"]["cards"] if card["key"] == "naver_a")
        for name in ("headline", "sub", "role", "a11y"):
            self.assertNotIn(secret, card[name], name)
        self.assertTrue(card["headline"].startswith("블로그"), "가린 뒤에도 앞의 글은 남는다")
        self.assertNotIn(secret, " ".join(str(item) for item in controller.delete_dialog().values()))

    def test_the_channel_color_presets_are_exactly_the_operators_values(self):
        """L2(독립 검증) — 색 프리셋 값은 운영자 문서 그대로이고 임의 색 입력은 없다: 값이 슬며시 바뀌면 여기서 걸린다."""
        self.assertEqual(tokens.CHANNEL_PRESETS, {"warm_lifestyle": {"primary": "#A85A44", "secondary": "#4F8B78", "accent": "#F2B38D", "surface": "#FFF7EE"},
                                                  "cool_technology": {"primary": "#2F6FED", "secondary": "#19B8C9", "accent": "#55DDE0", "surface": "#EEF5FF"}})
        self.assertEqual(set(tokens.CHANNEL_PRESETS), set(ch.COLOR_PRESETS), "프리셋 이름은 서비스가 받는 값과 같다")
        for preset in ch.COLOR_PRESETS:
            self.assertEqual(tokens.preset_colors(preset), tokens.CHANNEL_PRESETS[preset])
        for nothing in (None, "", "no_such_preset"):
            self.assertIsNone(tokens.preset_colors(nothing), repr(nothing))


# ---- 6) 가짜 공급자 = 서비스 ------------------------------------------------------------------------------------------------------------
class FakeProviderTest(unittest.TestCase):
    def test_the_fake_provider_works_in_memory_and_never_touches_the_disk(self):
        provider = blogs.FakeBlogsProvider()
        with tempfile.TemporaryDirectory() as tmp:
            before = sorted(str(path) for path in Path(tmp).rglob("*"))
            data = provider.load_blogs(SAFE, NEVER)
            provider.save_blog("naver_a", {"alias": "메모리에서만"}, data.version, SAFE, NEVER)
            self.assertEqual(sorted(str(path) for path in Path(tmp).rglob("*")), before)
        self.assertTrue(data.sample)
        self.assertEqual(provider.load_blogs(SAFE, NEVER).by_key()["naver_a"].alias, "메모리에서만")
        self.assertTrue(all(slot.sample for slot in data.slots))
        with self.assertRaises(ValueError):
            blogs.FakeBlogsProvider("no_such_scenario")
        failing = blogs.FakeBlogsProvider("error")
        with self.assertRaises(blogs.BlogFailure):
            failing.load_blogs(SAFE, NEVER)

    def test_every_sample_name_is_made_up(self):
        for scenario in blogs.SCENARIOS:
            if scenario == "error":
                continue
            data = blogs.FakeBlogsProvider(scenario).load_blogs(SAFE, NEVER)
            for slot in data.slots:
                self.assertTrue(not slot.blog_ref or slot.blog_ref.startswith("example-"), slot.blog_ref)
                self.assertTrue(not slot.registered or slot.display_name.startswith("예시"), slot.display_name)

    def test_the_fake_and_the_real_service_give_the_same_result_for_the_same_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp)
            real = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            fake = blogs.FakeBlogsProvider("empty")
            steps = (("save_blog", ("naver_a", {"display_name": "예시 블로그 가", "blog_ref": "example-blog-a", "main_topics": ("예시 주제",), "color_preset": "warm_lifestyle"})),
                     ("save_blog", ("naver_a", {"alias": "예시 별명"})), ("save_blog", ("naver_a", {"alias": "예시 별명"})), ("clone_blog", ("naver_a", "naver_b")), ("clone_blog", ("naver_a", "naver_b")),
                     ("save_blog", ("naver_b", {"display_name": "예시 블로그 나", "blog_ref": "example-blog-b"})), ("clear_blog", ("naver_a",)), ("clear_blog", ("naver_a",)),
                     ("save_blog", ("blogger_ko", {"display_name": "예시 블로그 다", "blog_ref": "example-blog-c", "language": "ko"})), ("clone_blog", ("blogger_ko", "blogger_en")),
                     ("save_blog", ("naver_b", {"generation_enabled": False})), ("save_blog", ("github_pages", {"alias": "가" * 40})), ("save_blog", ("naver_b", {"blog_ref": "a b"})))
            for name, args in steps:
                versions = []
                results = []
                for provider in (real, fake):
                    version = provider.load_blogs(SAFE, NEVER).version
                    try:
                        outcome = getattr(provider, name)(*args, version, SAFE, NEVER)
                        results.append((outcome.kind, outcome.changed, tuple(slot.raw() for slot in outcome.data.slots)))
                    except blogs.BlogFailure as failure:
                        results.append((failure.kind, tuple(sorted(failure.problems)), None))
                    versions.append(version)
                with self.subTest(step=name, args=args):
                    self.assertEqual(results[0], results[1])


# ---- 5) 쓰기는 누를 때만 · 실제 어댑터 -------------------------------------------------------------------------------------------------------
class AdapterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.ctx = ss.make_ctx(tmp.name)
        self.root = Path(self.ctx.workspace.root)
        self.provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: self.ctx)

    def tree(self):
        return ss.tree_snapshot(self.root)

    def test_opening_selecting_and_editing_write_nothing_in_a_missing_blank_and_good_data_folder(self):
        folder = self.root / "topic_engine"
        for prepare in (lambda: None, lambda: (folder.mkdir(parents=True), (folder / "channel_profiles.json").write_bytes(b"")),
                        lambda: bp.save_slot(self.ctx, "naver_a", {"display_name": "예시 블로그 가", "blog_ref": "example-blog-a"}, expected_version=bp.read_snapshot(self.ctx).version)):
            prepare()
            before, listing = self.tree(), sorted(str(path) for path in self.root.parent.rglob("*"))
            controller = blogs_view.BlogsController(self.provider, jobs.JobRunner())
            load(controller)
            controller.select("naver_b")
            controller.edit("alias", "고치는 중")
            controller.select("naver_a")
            controller.revert()
            controller.view()
            self.assertEqual(self.tree(), before)
            self.assertEqual(sorted(str(path) for path in self.root.parent.rglob("*")), listing, "읽기는 파일도 폴더도 만들지 않는다")

    def test_a_save_writes_exactly_the_profile_file_and_the_failure_kinds_map_to_easy_kinds(self):
        controller = blogs_view.BlogsController(self.provider, jobs.JobRunner())
        load(controller)
        controller.edit("display_name", "예시 블로그 가")
        controller.edit("blog_ref", "example-blog-a")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual(sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file() and path.name != "settings.json"), ["topic_engine/channel_profiles.json"])
        self.assertEqual(controller.base_raw("naver_a")["blog_ref"], "example-blog-a")
        # 다른 창이 먼저 바꿨다
        other = bp.save_slot(self.ctx, "naver_b", {"display_name": "예시 블로그 나", "blog_ref": "example-blog-b"}, expected_version=bp.read_snapshot(self.ctx).version)
        self.assertEqual(other.kind, "saved")
        controller.edit("alias", "고친 별명")
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", True))
        self.assertEqual(controller.notice, ("error", T["blogs_fail_conflict"]))
        self.assertEqual(controller.values("naver_a")["alias"], "고친 별명")
        load(controller)
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))

    def test_service_failures_become_kinds_without_paths_codes_or_values_in_the_sentences(self):
        cases = (("STORE_CONFLICT", "conflict"), ("TOPIC_STORE_LOCKED", "busy"), ("DISK_FULL", "disk"), ("FILE_WRITE_FAILED", "io"), ("FILE_IN_USE", "io"), ("TOPIC_FILE_INVALID", "corrupt"), ("CONFIRMATION_REQUIRED", "other"),
                 ("UNEXPECTED_ERROR", "other"))
        for code, kind in cases:
            failure = blogs_adapter.failure_of(AppError(code, {"경로": "C:/비밀/폴더/파일.json"}, detail="세부 메모"))
            self.assertEqual((failure.kind, failure.code), (kind, AppError(code).code), code)
            self.assertNotRegex(failure.user_message, r"[A-Za-z]:[\\/]|비밀|세부")
        self.assertEqual(blogs_adapter.failure_of(AppError("CONTENT_INVALID"), reading=True).kind, "corrupt")
        self.assertEqual(blogs_adapter.failure_of(AppError("CONTENT_INVALID")).kind, "invalid", "쓰는 중의 CONTENT_INVALID 는 복제·삭제 규칙을 어긴 것 — 칸 값이 틀린 쪽과 같은 종류")

    def test_a_broken_profile_file_stops_the_read_and_every_write_with_an_easy_error_and_is_never_touched(self):
        folder = self.root / "topic_engine"
        folder.mkdir(parents=True)
        (folder / "channel_profiles.json").write_bytes(b"{broken")
        before = self.tree()
        with self.assertRaises(blogs.BlogFailure) as caught:
            self.provider.load_blogs(SAFE, NEVER)
        self.assertEqual(caught.exception.kind, "corrupt")
        for call in (lambda: self.provider.save_blog("naver_a", {"alias": "x"}, "v", SAFE, NEVER), lambda: self.provider.clone_blog("naver_a", "naver_b", "v", SAFE, NEVER),
                     lambda: self.provider.clear_blog("naver_a", "v", SAFE, NEVER)):
            with self.assertRaises(blogs.BlogFailure) as caught:
                call()
            self.assertEqual(caught.exception.kind, "corrupt")
        self.assertEqual(self.tree(), before)

    def test_a_missing_data_folder_is_an_easy_error_and_the_pairing_follows_the_home_provider(self):
        provider = blogs_adapter.ServiceBlogsProvider(str(self.root / "no_such_folder"), context_factory=lambda data_dir=None: self.ctx)
        with self.assertRaises(blogs.BlogFailure) as caught:
            provider.load_blogs(SAFE, NEVER)
        self.assertEqual(caught.exception.code, "DATA_DIR_NOT_FOUND")
        self.assertIsInstance(adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: self.ctx).blogs_provider(), blogs_adapter.ServiceBlogsProvider)
        self.assertIsInstance(services.FakeHomeProvider().blogs_provider(), blogs.FakeBlogsProvider)
        self.assertIsInstance(app_state.AppState(services.FakeHomeProvider()).blogs_provider, blogs.FakeBlogsProvider)
        state = app_state.AppState(adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: self.ctx))
        self.assertIsInstance(state.blogs_provider, blogs_adapter.ServiceBlogsProvider)
        self.assertIs(state.blogs.provider, state.blogs_provider)
        self.assertIs(state.blogs.runner, state.runner)
        self.assertEqual(state.blogs_view()["state"], "loading")


# ---- 메뉴 ---------------------------------------------------------------------------------------------------------------------------
class MenuTest(unittest.TestCase):
    def test_the_blog_screen_is_a_real_menu_in_the_data_group_and_not_in_the_coming_soon_list(self):
        # 의도적 갱신(Seed 관리, D-230): Seed 관리 화면이 완성돼 데이터·관리 묶음의 블로그 관리 앞에 올랐고 '다음 단계' 목록에서 빠졌다. 블로그 관리가 실제 메뉴이고 '다음 단계' 에 없다는 이 시험의 뜻은 그대로다.
        # 의도적 갱신(P4d, D-270): 주제 후보 화면이 완성돼 핵심 작업 묶음의 홈 다음에 올랐고 '다음 단계' 목록에서 빠졌다 — 블로그 관리가 실제 메뉴이고 '다음 단계' 에 없다는 이 시험의 뜻은 그대로다.
        # 의도적 갱신(P4e, D-282): 초안 작성 화면이 완성돼 핵심 작업 묶음의 주제 후보 다음에 올랐고 '다음 단계' 목록에는 발행 기록만 남았다 — 블로그 관리가 실제 메뉴이고 '다음 단계' 에 없다는 이 시험의 뜻은 그대로다.
        self.assertEqual([key for key, _label, _icon in app_state.NAV], ["home", "topics", "drafts", "seed", "blogs", "settings"])
        self.assertEqual([text.T[label] for _key, label, _icon in app_state.NAV], ["홈", "주제 후보", "초안 작성", "Seed 관리", "블로그 관리", "설정"])
        self.assertEqual([(key, label, [item[0] for item in items]) for key, label, items in app_state.nav_groups()],
                         [("core", "nav_group_core", ["home", "topics", "drafts"]), ("data", "nav_group_data", ["seed", "blogs"]), ("system", "nav_group_system", ["settings"])])
        self.assertEqual([key for key, _label, _icon in app_state.NEXT_STEPS], ["history"])
        state = app_state.AppState(services.FakeHomeProvider())
        self.assertTrue(state.nav("blogs"))
        self.assertEqual(state.page, "blogs")
        for unfinished in ("draft", "history", "nope"):
            self.assertFalse(state.nav(unfinished), unfinished)


# ---- 7) 소스 규칙 ---------------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    NEW_CORE = ("blog_form.py", "blogs.py", "blogs_view.py", "blog_text.py")
    WRITERS = {"write_text", "write_bytes", "unlink", "mkdir", "rmdir", "rmtree", "copy2", "copyfile", "copytree", "touch", "chmod", "makedirs", "write_json", "fsync", "truncate", "symlink"}
    DOTTED = {"os.replace", "os.rename", "os.remove", "os.write", "os.open", "os.link", "shutil.move", "shutil.copy", "open"}      # `replace`·`move`·`copy` 는 글·창에도 쓰는 이름이라 파일을 다루는 모듈 이름과 함께 있을 때만 센다

    def calls(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return [(node.lineno, ast.unparse(node.func)) for node in ast.walk(tree) if isinstance(node, ast.Call)]

    def test_no_screen_code_writes_a_file(self):
        """`ui/core`·`ui/qt` 와 홈·설정 어댑터에는 파일을 쓰는 호출이 없다 — 쓰는 길은 `blogs_adapter` 가 부르는 서비스 함수 셋뿐이다."""
        for path in sorted(UI_DIR.rglob("*.py")):
            if path.name == "blogs_adapter.py":
                continue
            found = [(line, name) for line, name in self.calls(path) if name.rsplit(".", 1)[-1] in self.WRITERS or name in self.DOTTED]
            with self.subTest(file=path.relative_to(UI_DIR).as_posix()):
                self.assertEqual(found, [])

    def test_the_adapter_reaches_the_files_only_through_the_three_service_write_functions_and_delete_always_confirms(self):
        path = UI_DIR / "blogs_adapter.py"
        names = {name for _line, name in self.calls(path)}
        self.assertEqual({name for name in names if name.startswith("service.") and name.rsplit(".", 1)[-1] not in ("read_snapshot",)} - {"service.ProfileProblems"}, {"service.save_slot", "service.clone_slot", "service.clear_slot"})
        source = path.read_text(encoding="utf-8")
        self.assertEqual(source.count("confirmed=True"), 1)
        tree = ast.parse(source)
        clear = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "clear_blog")
        self.assertIn("confirmed=True", ast.unparse(clear))
        self.assertNotRegex(source, r"keystore|get_keystore|secret")

    def test_the_new_pure_modules_never_import_the_screen_toolkit_or_read_the_clock(self):
        for name in self.NEW_CORE:
            source = (UI_DIR / "core" / name).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"(?m)^\s*(?:import|from)\s+PySide6", name)
            for forbidden in ("datetime.now(", "date.today(", "time.time(", "open(", "write_text", "write_json"):
                self.assertNotIn(forbidden, source, f"{name}: {forbidden}")
            self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", source), [], name)

    def test_every_new_text_is_used_and_the_texts_are_easy_and_free_of_promises(self):
        used = "\n".join(path.read_text(encoding="utf-8") for path in UI_DIR.rglob("*.py") if path.name != "blog_text.py")
        used += "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "scripts").glob("ui_*.py"))
        families = {"bf_label_": [spec.name for spec in bf.FIELDS], "bf_hint_": [spec.name for spec in bf.FIELDS] + ["generation_off"], "bf_tag_": list(bf.TAG_ORDER), "bf_preset_": [preset or "none" for preset in bf.PRESET_ORDER],
                    "blogs_slot_": list(bf.SLOTS), "blogs_kind_": ["naver", "blogger", "github"], "blogs_lang_": ["ko", "en"], "blogs_sec_": [f"{key}{suffix}" for key in bf.SECTIONS for suffix in ("", "_desc")],
                    "bf_placeholder_": ["display_name", "blog_ref", "words", "path"]}
        for key, value in blog_text.BLOG_T.items():
            family = next((prefix for prefix in families if key.startswith(prefix)), None)
            if family is not None:
                self.assertIn(key[len(family):], families[family], key)
            else:
                self.assertRegex(used, rf'["\']{key}["\']', f"죽은 글: {key}")
            for word in text.FORBIDDEN:
                self.assertNotIn(word, value, key)
            self.assertNotRegex(value, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b|Traceback|Exception|Error\b", key)
        for prefix, names in families.items():
            for name in names:
                self.assertIn(prefix + name, blog_text.BLOG_T, prefix + name)
        self.assertEqual(set(blog_text.BLOG_T) & set(text.T), set(blog_text.BLOG_T))
        self.assertTrue(all(text.T[key] == value for key, value in blog_text.BLOG_T.items()), "합친 값이 그대로다")

    def test_the_form_never_asks_for_a_color_or_a_file_content(self):
        names = [spec.name for spec in bf.FIELDS]
        for forbidden in ("color", "hex", "primary_color", "image_data", "image_bytes", "password", "api_key", "token", "secret"):
            self.assertNotIn(forbidden, names)
        self.assertEqual(bf.SPEC["color_preset"].kind, "choice")
        self.assertEqual([option for option in bf.PRESET_ORDER], ["", "warm_lifestyle", "cool_technology"], "색은 프리셋 둘과 '정하지 않음' 뿐이다")
        self.assertEqual({spec.kind for spec in bf.FIELDS if spec.name.endswith("_image")}, {"path"})


if __name__ == "__main__":
    unittest.main()
