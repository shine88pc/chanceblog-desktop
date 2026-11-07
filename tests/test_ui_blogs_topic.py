"""블로그 관리 화면의 **주제 설정 세 칸**(우선 키워드·제외 키워드·선호 글 유형 — P4c)의 순수 부분 시험(PySide6 없이 돈다 — CI 와 같은 조건): 칸 표·구역·문구·검사·뷰모델·가짜 공급자·실제 어댑터(임시 폴더).
옛 시험(`test_ui_blogs_core`)이 폼 전체의 규칙을 이미 확인하므로 여기서는 **새 칸이 같은 규칙 위에서 똑같이 안전한가**를 본다.

지키는 것:
  1) 칸 표: 새 구역 `topic` 이 자세한 정보와 모양 사이에 있고 칸은 우선 키워드·제외 키워드(`words`, 20개×30자 — 서비스 상수)·선호 글 유형(`multi` 칩 다섯)이다. 글 유형의 이름은 서비스의 `POST_TYPES` 값 그대로(이름표를 베끼지 않는다).
  2) **판정은 서비스 생성자와 같다**: 수백 가지 입력(낱말 목록·두 칸의 쌍·한 칸만 바꿔 저장된 다른 칸과 견주기·글 유형 모든 조합)에서 **화면이 통과시키는데 서비스가 거절하는 입력이 0** 이다.
  3) 우선·제외에 같은 낱말이 있으면 두 칸 옆에 쉬운 문장(어느 칸이 문제인지, 입력한 낱말은 되풀이하지 않는다)이 보이고 서비스를 부르지 않는다.
  4) 초안은 고친 칸만 들고 있다(F1): 다른 창이 바꾼 '안 고친' 새 칸은 다시 읽은 뒤 최신 값이고 저장해도 낡은 값으로 되돌아가지 않는다. 다른 창이 바꾼 값 때문에 겹침이 생기면 조용히 덮지 않고 막는다.
  5) 가짜 공급자는 같은 일을 서비스에 해 본 결과와 같다(저장·겹침·바꿔치기·복제·삭제). 실제 어댑터로 저장→다시 읽기·손으로 고친 판 2 파일·판 1 파일·읽기 전용 증명(열고 고르고 고쳐도 파일이 안 바뀐다).
  6) 화면 문구는 사실만 쓴다 — 엔진은 이 세 칸을 아직 읽지 않는다(그것을 지키는 시험이 있다: 엔진이 읽기 시작하면 그 시험이 걸려 문구를 고치게 한다).
"""
import ast
import dataclasses
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.ui import blogs_adapter  # noqa: E402
from chanceblog_desktop.ui.core import blog_form as bf  # noqa: E402
from chanceblog_desktop.ui.core import blogs, blogs_view, jobs, text  # noqa: E402
from test_ui_blogs_core import NEVER, SAFE, drive, load, new_controller  # noqa: E402,I001

SRC = ROOT / "src" / "chanceblog_desktop"
T = text.T
THREE = ("priority_keywords", "exclude_keywords", "preferred_post_types")
POST_TYPES = ("정보형", "비교형", "문제 해결형", "제품·서비스 소개형", "장소·업체 정보형")      # 서비스의 `POST_TYPES` 와 같은 다섯 — 시험이 직접 적어 서비스 상수를 돌려 쓰지 않는다


def form_of(controller):
    return {field["name"]: field for section in controller.view()["form"]["sections"] for field in section["fields"]}


def errors_of(controller):
    return {name: field["error"] for name, field in form_of(controller).items() if field["error"]}


def service_accepts(profile, fields):
    try:
        bp.apply_fields(profile, fields)
    except bp.ProfileProblems:
        return False
    return True


# ---- 1) 칸 표·구역·문구 ------------------------------------------------------------------------------------------------------------------
class SpecTest(unittest.TestCase):
    def test_a_new_topic_section_sits_between_the_detail_and_look_sections_with_the_three_fields_in_order(self):
        self.assertEqual(bf.SECTIONS, ("basic", "more", "topic", "look"))
        by_section = {section: [spec.name for spec in bf.FIELDS if spec.section == section] for section in bf.SECTIONS}
        self.assertEqual(by_section["topic"], ["priority_keywords", "exclude_keywords", "preferred_post_types"])
        self.assertEqual(by_section["look"], ["color_preset", "profile_image", "cover_image"])
        self.assertEqual([spec.section for spec in bf.FIELDS], sorted((spec.section for spec in bf.FIELDS), key=bf.SECTIONS.index), "구역 순서대로 놓여 있다")
        for key in bp.SLOTS:
            names = [spec.name for spec in bf.fields_for(key)]
            self.assertEqual(sorted(names), sorted(bp.form_fields(key)), key)
            self.assertEqual(len(names), 18 if key in ("naver_a", "naver_b") else 17, key)
            self.assertEqual(len(bf.fields_for(key)), len(bp.form_fields(key)))

    def test_the_limits_and_the_choices_are_the_services(self):
        self.assertEqual((ch.MAX_KEYWORDS, ch.MAX_KEYWORD_WORD), (20, 30), "계획 표의 값")
        for name in bf.KEYWORD_FIELDS:
            spec = bf.SPEC[name]
            self.assertEqual((spec.kind, spec.count, spec.limit, spec.required), ("words", ch.MAX_KEYWORDS, ch.MAX_KEYWORD_WORD, False), name)
        spec = bf.SPEC["preferred_post_types"]
        self.assertEqual((spec.kind, spec.options, spec.count, spec.keep_extra, spec.required), ("multi", POST_TYPES, 5, False, False))
        self.assertEqual(ch.POST_TYPES, POST_TYPES)
        tags = bf.SPEC["monetization_focus"]
        self.assertEqual((tags.kind, tags.options, tags.count, tags.keep_extra), ("multi", bf.TAG_ORDER, ch.MAX_FOCUS, True), "협찬 분야는 그대로 — 목록 밖 값을 보존하는 칸")
        self.assertEqual(bf.KEYWORD_FIELDS, bp.KEYWORD_FIELDS)
        self.assertEqual(set(bf.KEYWORD_FIELDS) | {"preferred_post_types"}, set(THREE))

    def test_the_chip_names_are_the_service_values_and_no_name_table_was_copied(self):
        self.assertEqual(bf.options_of(bf.SPEC["preferred_post_types"]), [{"value": name, "label": name} for name in POST_TYPES])
        self.assertEqual([item["label"] for item in bf.options_of(bf.SPEC["monetization_focus"])], [T["bf_tag_" + tag] for tag in bf.TAG_ORDER])
        self.assertEqual([key for key in T if key.startswith(("bf_post", "bf_type"))], [], "글 유형 이름표를 화면이 따로 만들지 않는다 — 서비스의 값이 곧 이름이다")

    def test_the_labels_are_the_services_korean_field_names(self):
        for name in THREE:
            self.assertEqual(T["bf_label_" + name], ch.PROFILE_FIELD_KO[name], name)
        self.assertEqual((T["bf_label_priority_keywords"], T["bf_label_exclude_keywords"], T["bf_label_preferred_post_types"]), ("우선 키워드", "제외 키워드", "선호 글 유형"))

    def test_the_section_text_says_only_what_is_true_the_engine_does_not_use_these_three_fields_yet(self):
        desc = T["blogs_sec_topic_desc"]
        self.assertEqual(T["blogs_sec_topic"], "주제 설정(선택)")
        for part in ("저장만", "아직 연결되어 있지 않아요"):
            self.assertIn(part, desc)
        for claim in ("점수", "가산", "거르", "걸러", "제외돼", "반영돼요", "추천해"):
            self.assertNotIn(claim, desc, f"엔진이 읽지 않는 칸에 효과를 약속하면 안 된다: {claim}")
        for key in ("bf_hint_priority_keywords", "bf_hint_exclude_keywords", "bf_hint_preferred_post_types", "bf_err_overlap_priority_keywords", "bf_err_overlap_exclude_keywords"):
            for claim in ("점수", "가산", "거르", "걸러", "반영돼요"):
                self.assertNotIn(claim, T[key], f"{key}: {claim}")
            for word in text.FORBIDDEN:
                self.assertNotIn(word, T[key], key)

    def test_the_hints_carry_the_limits_and_easy_words(self):
        self.assertIn("20개", bf.SPEC["priority_keywords"].hint())
        self.assertIn("30자", bf.SPEC["priority_keywords"].hint())
        self.assertIn("20개", bf.SPEC["exclude_keywords"].hint())
        self.assertIn("우선 키워드와 같은 낱말은 쓸 수 없어요", bf.SPEC["exclude_keywords"].hint())
        self.assertEqual(bf.SPEC["preferred_post_types"].hint(), T["bf_hint_preferred_post_types"])
        for name in THREE:
            self.assertNotRegex(bf.SPEC[name].hint(), r"\{|\}")

    def test_each_of_the_three_hints_says_it_is_saved_only_so_a_screen_reader_hears_it_too(self):
        """독립 검증 M1 — 힌트는 접근 설명이기도 해서 구역 설명(`지금은 저장만 해요`)을 못 듣는 화면 읽기 프로그램 사용자도 칸마다 그 사실을 듣는다."""
        for name in THREE:
            self.assertIn("지금은 저장만 해요", bf.SPEC[name].hint(), name)
            for claim in ("점수", "가산", "거르", "걸러", "반영돼요"):
                self.assertNotIn(claim, bf.SPEC[name].hint(), f"{name}: {claim}")

    def test_the_delete_dialog_names_the_three_topic_fields_that_now_get_cleared(self):
        """독립 검증 M2 — 슬롯 비우기는 이제 세 칸도 비운다(P4b 에서는 보존됐다). 확인창이 '같은 내용' 에 맡기지 않고 이름으로 말하고, 되돌릴 수 없다는 것·후보·초안·발행 기록은 그대로라는 것도 여전히 말한다."""
        controller = new_controller()
        controller.select("naver_a")
        body = controller.delete_dialog()["body"]
        for part in ("우선 키워드", "제외 키워드", "선호 글 유형", "이름·블로그 ID·주제", "모두 비워져요", "되돌릴 수 없어요", "후보·초안·발행 기록은 지워지지 않아요"):
            self.assertIn(part, body, part)


class TruthTest(unittest.TestCase):
    ALLOWED = {"topics/channels.py", "topics/seeds.py", "service/seed_manage.py", "topicdb/backup.py", "service/blog_profiles.py"}      # 칸을 정의·검사하는 곳, 씨앗의 같은 이름 칸(씨앗 모양 `topics/seeds.py` 와 Seed 관리의 저장 서비스 `service/seed_manage.py` — 후보를 만들지 않는다), 키 모양 검사 목록, 이 화면의 저장 서비스

    def test_no_engine_module_reads_the_three_profile_fields_so_the_screen_says_they_are_saved_only(self):
        """**꼬리표 시험** — 이 화면의 문구('이 세 칸은 지금 저장만 해요 … 아직 연결되어 있지 않아요')는 엔진이 프로필의 이 세 칸을 읽지 않는다는 코드 사실에 기댄다. 후보를 만드는 코드가 이 칸을 읽기 시작하면
        이 시험이 걸린다 — 그때는 화면 문구(`blogs_sec_topic_desc`)·UI 문서·결정 D-241 을 함께 고치고 이 목록을 갱신한다(`topics/seeds.py` 의 같은 이름은 **씨앗**의 칸이라 다른 객체다)."""
        found = []
        for path in sorted(SRC.rglob("*.py")):
            rel = path.relative_to(SRC).as_posix()
            if rel in self.ALLOWED or rel.startswith("ui/"):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr in THREE:
                    found.append(f"{rel}:{node.lineno} .{node.attr}")
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in THREE:
                    found.append(f"{rel}:{node.lineno} '{node.value}'")
        self.assertEqual(found, [], "엔진이 이 세 칸을 읽기 시작했다면 화면 문구와 문서를 사실에 맞게 고쳐야 한다")


# ---- 2) 값 다듬기·검사 — 서비스 생성자와 같은 판정 -------------------------------------------------------------------------------------------
class VerdictTest(unittest.TestCase):
    RAW_WORDS = ["", "가", "가, 나", "가,,나", " , ", "가 나, 다", "A, a", "가, 가", "가, 가 ", "가나다라마바사아자차" * 3, "가나다라마바사아자차" * 3 + "가", "<b>x</b>, 나", "javascript: 가, 나", "{{x}}", "{% x %}", "onclick=x()",
                 "a<b 비교", "숙박·여행, 업무 자동화", "a;b\nc", "가，나、다", "  앞뒤  공백  , 둘째", "Abc, aBC", "ß, SS", "가\t나", ",".join(f"낱말{index}" for index in range(20)), ",".join(f"낱말{index}" for index in range(21)),
                 ", ".join(f"{'가' * 30}{index}" for index in range(3)), "가" * 30, "가" * 31]
    checked = 0

    def screen_rejects(self, name, raw):
        spec = bf.SPEC[name]
        return bool(bf.problem_of(spec, bf.normalize(spec, raw)))

    def test_each_keyword_field_is_judged_like_the_service_for_many_typed_inputs(self):
        base = bp.default_profile("naver_a")
        for name in bf.KEYWORD_FIELDS:
            for raw in self.RAW_WORDS:
                typed = bf.normalize(bf.SPEC[name], raw)
                with self.subTest(field=name, raw=raw[:24]):
                    self.assertEqual(self.screen_rejects(name, raw), not service_accepts(base, {name: typed}))
                    type(self).checked += 1

    def test_every_pair_of_typed_keyword_inputs_passes_the_screen_only_when_the_service_accepts_it(self):
        base = bp.default_profile("naver_a")
        pool = ["", "가", "가, 나", "A", "a", "A, b", "b, A", "가, 가", "<b>x</b>", "x" * 31, "다, 라, 마", "Abc, aBC", "ß", "SS", "나; 가", "가，다", "ǆ", "ǅ", "나, 다"]
        pairs = 0
        for first, second in itertools.product(pool, pool):
            raws = {"priority_keywords": first, "exclude_keywords": second}
            typed = bf.typed_values("naver_a", {**bf.default_values("naver_a"), **raws})
            keywords = {name: typed[name] for name in bf.KEYWORD_FIELDS}
            screen_ok = not {name: problem for name, problem in bf.check_typed("naver_a", typed).items() if name in bf.KEYWORD_FIELDS}      # 블로그 ID 가 필수인 것은 화면만의 규칙이라 두 키워드 칸의 문제만 본다
            service_ok = service_accepts(base, keywords)
            pairs += 1
            if screen_ok != service_ok:
                self.fail(f"화면과 서비스가 다르다: {first!r} / {second!r} → 화면 {screen_ok}, 서비스 {service_ok}")
        self.assertGreater(pairs, 300)

    def test_a_change_to_one_keyword_field_is_judged_against_the_stored_other_field_like_the_service(self):
        """한 칸만 고쳐 저장하는 길 — 저장된 다른 칸과 견준다. 화면(저장된 값 + 초안)과 서비스(`apply_fields` 에 바뀐 칸만 보냄)의 판정이 같다."""
        count = 0
        for stored_priority, stored_exclude in itertools.product((("가",), ("가", "나"), (), ("Abc",)), (("다",), ("라", "마"), ())):
            stored = dataclasses.replace(bp.default_profile("naver_a"), blog_ref="example-blog-a", priority_keywords=stored_priority, exclude_keywords=stored_exclude)
            base_raw = bf.raw_from_profile(stored)
            for name in bf.KEYWORD_FIELDS:
                for raw in ("", "가", "나", "다", "마, 가", "aBC", "ABC, x", "새 낱말", "다, 가", "라", "가, 나", "나, 다", "마", "가, 가"):
                    values = {**base_raw, name: raw}
                    typed = bf.typed_values("naver_a", values)
                    screen_ok = not bf.check_all("naver_a", values)
                    service_ok = service_accepts(stored, {name: typed[name]})
                    count += 1
                    if screen_ok != service_ok:
                        self.fail(f"화면과 서비스가 다르다: 저장 {stored_priority}/{stored_exclude}, {name} ← {raw!r} → 화면 {screen_ok}, 서비스 {service_ok}")
        self.assertGreater(count, 300)

    def test_every_combination_of_the_five_post_types_passes_and_anything_else_fails_like_the_service(self):
        base = bp.default_profile("naver_a")
        spec = bf.SPEC["preferred_post_types"]
        total = 0
        for size in range(len(POST_TYPES) + 1):
            for combo in itertools.combinations(POST_TYPES, size):
                typed = bf.normalize(spec, combo)
                self.assertEqual(typed, tuple(name for name in POST_TYPES if name in combo), "정해진 순서로 정리한다")
                self.assertEqual(bf.problem_of(spec, typed), "")
                self.assertTrue(service_accepts(base, {"preferred_post_types": typed}))
                total += 1
        self.assertEqual(total, 32)
        for raw in (("후기형",), ("정보형", "후기형"), ("",), ("정보 형",), "정보형 ", ("정보형", "정보형"), POST_TYPES + ("정보형",), ("정보형", "x")):
            typed = bf.normalize(spec, raw)
            self.assertEqual(bool(bf.problem_of(spec, typed)), not service_accepts(base, {"preferred_post_types": typed}), repr(raw))
        self.assertEqual(bf.problem_of(spec, ("후기형",)), "bad_choice")
        self.assertEqual(bf.normalize(spec, "정보형"), ("정보형",), "글 한 줄은 값 하나로 본다(글자로 쪼개지 않는다)")

    def test_the_reasons_are_the_specific_ones_and_the_overlap_names_both_fields(self):
        spec = bf.SPEC
        self.assertEqual(bf.problem_of(spec["priority_keywords"], ("가",) * 2), "duplicate")
        self.assertEqual(bf.problem_of(spec["priority_keywords"], tuple(str(i) for i in range(21))), "too_many")
        self.assertEqual(bf.problem_of(spec["exclude_keywords"], ("가" * 31,)), "item_too_long")
        self.assertEqual(bf.problem_of(spec["exclude_keywords"], ("<b>x</b>",)), "markup")
        self.assertEqual(bf.overlap_names({"priority_keywords": ("가", "Abc"), "exclude_keywords": ("ABC",)}), ("priority_keywords", "exclude_keywords"))
        self.assertEqual(bf.overlap_names({"priority_keywords": ("가",), "exclude_keywords": ("나",)}), ())
        self.assertEqual(bf.overlap_names({"priority_keywords": ("가",)}), (), "칸 하나만으로는 알 수 없다")
        self.assertEqual(bf.overlap_names({"priority_keywords": "가", "exclude_keywords": ("가",)}), (), "목록이 아닌 값은 칸 검사가 먼저 거른다")
        found = bf.check_typed("naver_a", {"priority_keywords": ("가",), "exclude_keywords": ("가",)})
        self.assertEqual(found, {"priority_keywords": "overlap", "exclude_keywords": "overlap"})
        found = bf.check_typed("naver_a", {"priority_keywords": ("가", "가"), "exclude_keywords": ("가",)})
        self.assertEqual(found, {"priority_keywords": "duplicate", "exclude_keywords": "overlap"}, "칸에 이미 다른 문제가 있으면 그 문제가 먼저다")
        self.assertEqual(bf.check_fields("naver_a", {"priority_keywords": ("가",), "exclude_keywords": ("가",)}), {}, "칸마다만 보는 검사는 칸 사이 규칙을 보지 않는다")


class MessageTest(unittest.TestCase):
    def test_every_problem_including_overlap_has_an_easy_sentence_that_never_repeats_the_input(self):
        secret = "비밀처럼 보이는 입력 글 12345"
        import re
        for name in THREE:
            spec = bf.SPEC[name]
            for problem in ("required", "too_long", "too_many", "item_too_long", "duplicate", "markup", "bad_ref", "bad_choice", "bad_path", "key_shape", "invalid", "overlap"):
                sentence = bf.problem_text(spec, problem, secret)
                self.assertTrue(sentence, (name, problem))
                self.assertNotIn(secret, sentence)
                self.assertIsNone(re.search(r"[\[\]{}]|Traceback|Exception|CONTENT_|AppError|None\b", sentence), (name, problem, sentence))

    def test_the_overlap_sentence_names_the_other_field_and_a_non_keyword_field_gets_the_general_sentence(self):
        self.assertIn("제외 키워드", bf.problem_text(bf.SPEC["priority_keywords"], "overlap", "x"))
        self.assertIn("우선 키워드", bf.problem_text(bf.SPEC["exclude_keywords"], "overlap", "x"))
        self.assertEqual(bf.problem_text(bf.SPEC["alias"], "overlap"), T["bf_err_invalid"], "다른 칸에는 겹침 문장이 없다")
        self.assertEqual(bf.problem_text(bf.SPEC["priority_keywords"], "overlap", "x"), T["bf_err_overlap_priority_keywords"])
        self.assertEqual(bf.problem_text(bf.SPEC["exclude_keywords"], "overlap", "x"), T["bf_err_overlap_exclude_keywords"])

    def test_the_keyword_sentences_carry_the_numbers(self):
        self.assertIn("20", bf.problem_text(bf.SPEC["priority_keywords"], "too_many", ", ".join("가" + str(i) for i in range(22))))
        self.assertIn("30", bf.problem_text(bf.SPEC["exclude_keywords"], "item_too_long", "x"))
        self.assertEqual(bf.problem_text(bf.SPEC["preferred_post_types"], "bad_choice", ("x",)), T["bf_err_choice"])


# ---- 3) 상태·동작 ---------------------------------------------------------------------------------------------------------------------------
class ControllerTest(unittest.TestCase):
    def test_the_view_has_four_sections_and_the_topic_section_shows_the_saved_values_with_the_limits(self):
        controller = new_controller()
        sections = {section["key"]: section for section in controller.view()["form"]["sections"]}
        self.assertEqual(list(sections), ["basic", "more", "topic", "look"])
        topic = sections["topic"]
        self.assertEqual((topic["title"], topic["desc"]), (T["blogs_sec_topic"], T["blogs_sec_topic_desc"]))
        fields = {field["name"]: field for field in topic["fields"]}
        self.assertEqual(list(fields), ["priority_keywords", "exclude_keywords", "preferred_post_types"])
        self.assertEqual((fields["priority_keywords"]["kind"], fields["exclude_keywords"]["kind"], fields["preferred_post_types"]["kind"]), ("words", "words", "multi"))
        self.assertEqual(fields["priority_keywords"]["value"], "예시 키워드 하나, 예시 키워드 둘")
        self.assertEqual(fields["exclude_keywords"]["value"], "예시 제외어")
        self.assertEqual(fields["preferred_post_types"]["value"], ("정보형", "비교형"))
        self.assertEqual([option["value"] for option in fields["preferred_post_types"]["options"]], list(POST_TYPES))
        self.assertEqual([option["label"] for option in fields["preferred_post_types"]["options"]], list(POST_TYPES))
        self.assertEqual(fields["preferred_post_types"]["extra"], "", "목록 밖 값 보존 안내는 협찬 분야만")
        self.assertEqual(fields["priority_keywords"]["placeholder"], T["bf_placeholder_words"])
        for name, field in fields.items():
            self.assertEqual((field["required"], field["error"], field["changed"], field["disabled"]), (False, "", False, False), name)
            self.assertTrue(field["hint"], name)
        self.assertIn("20개", fields["priority_keywords"]["hint"])
        empty = {field["name"]: field for section in new_controller("empty").view()["form"]["sections"] for field in section["fields"]}
        self.assertEqual((empty["priority_keywords"]["value"], empty["exclude_keywords"]["value"], empty["preferred_post_types"]["value"]), ("", "", ()))

    def test_every_slot_shows_the_topic_section_with_the_three_fields(self):
        controller = new_controller()
        for key in bf.SLOTS:
            controller.select(key)
            names = [field["name"] for section in controller.view()["form"]["sections"] for field in section["fields"]]
            self.assertEqual(len(names), 18, key)         # 네이버: 폼 칸 18 / 나머지: 폼 칸 17 + 꺼진 '후보 만들기' 한 칸(이유와 함께 보인다 — P4b 그대로)
            self.assertEqual([name for name in names if name in THREE], list(THREE), key)

    def test_editing_the_three_fields_marks_only_those_dirty_and_putting_the_value_back_drops_the_draft(self):
        controller = new_controller()
        calls = list(controller.provider.calls)
        controller.edit("priority_keywords", "예시 키워드 하나, 예시 키워드 둘")
        self.assertFalse(controller.is_dirty("naver_a"), "저장된 값과 같다")
        controller.edit("priority_keywords", "예시 키워드 하나 ,  예시 키워드 둘 ")
        self.assertFalse(controller.is_dirty("naver_a"), "공백만 다르면 바뀐 것이 아니다")
        controller.edit("priority_keywords", "예시 새 키워드")
        controller.edit("exclude_keywords", "")
        self.assertTrue(controller.toggle_choice("preferred_post_types", "문제 해결형"))
        self.assertEqual(controller.dirty_names("naver_a"), ("priority_keywords", "exclude_keywords", "preferred_post_types"))
        self.assertEqual(set(controller.drafts["naver_a"]), set(THREE), "초안에는 고친 칸만 있다")
        controller.revert()
        self.assertFalse(controller.is_dirty("naver_a"))
        self.assertEqual(controller.provider.calls, calls, "고치기·되돌리기는 공급자를 부르지 않는다")

    def test_the_post_type_chips_toggle_in_the_services_order_and_only_the_five_known_values_are_accepted(self):
        controller = new_controller("empty")
        self.assertTrue(controller.toggle_choice("preferred_post_types", "장소·업체 정보형"))
        self.assertTrue(controller.toggle_choice("preferred_post_types", "정보형"))
        self.assertEqual(bf.typed_values("naver_a", controller.values("naver_a"))["preferred_post_types"], ("정보형", "장소·업체 정보형"), "저장하는 값은 서비스의 글 유형 순서로 정리된다")
        self.assertTrue(controller.toggle_choice("preferred_post_types", "정보형"))
        self.assertEqual(bf.typed_values("naver_a", controller.values("naver_a"))["preferred_post_types"], ("장소·업체 정보형",), "다시 누르면 꺼진다")
        for bad in (("preferred_post_types", "후기형"), ("preferred_post_types", ""), ("alias", "정보형"), ("no_such_field", "x"), ("priority_keywords", "가"), ("generation_enabled", "x")):
            self.assertFalse(controller.toggle_choice(*bad), bad)
        self.assertEqual(controller.values("naver_a")["monetization_focus"], controller.base_raw("naver_a")["monetization_focus"])
        self.assertTrue(controller.toggle_tag("ai_service"), "기존 협찬 분야 껍질은 그대로 일한다")
        self.assertIn("ai_service", controller.values("naver_a")["monetization_focus"])
        self.assertFalse(controller.toggle_tag("정보형"), "글 유형 이름은 협찬 분야가 아니다")
        controller.data = None
        self.assertFalse(controller.toggle_choice("preferred_post_types", "정보형"), "읽기 전의 상태에서는 아무 일도 없다")

    def test_a_clean_save_writes_the_three_values_and_empties_only_that_slots_draft(self):
        controller = new_controller()
        controller.edit("priority_keywords", "예시 새 키워드 하나, 예시 새 키워드 둘")
        controller.edit("exclude_keywords", "예시 새 제외어")
        controller.toggle_choice("preferred_post_types", "문제 해결형")
        controller.select("naver_b")
        controller.edit("alias", "저장 안 할 별명")
        controller.select("naver_a")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        slot = controller.provider.slots["naver_a"]
        self.assertEqual((slot.priority_keywords, slot.exclude_keywords, slot.preferred_post_types), (("예시 새 키워드 하나", "예시 새 키워드 둘"), ("예시 새 제외어",), ("정보형", "비교형", "문제 해결형")))
        self.assertFalse(controller.is_dirty("naver_a"))
        self.assertTrue(controller.is_dirty("naver_b"), "다른 슬롯의 초안은 그대로")
        self.assertEqual(form_of(controller)["priority_keywords"]["value"], "예시 새 키워드 하나, 예시 새 키워드 둘")

    def test_a_word_in_both_keyword_fields_shows_a_sentence_beside_the_touched_field_then_both_after_a_save_try_and_never_calls_the_provider(self):
        controller = new_controller()
        calls = list(controller.provider.calls)
        controller.edit("exclude_keywords", "예시 제외어, 예시 키워드 둘")
        self.assertEqual(errors_of(controller), {"exclude_keywords": T["bf_err_overlap_exclude_keywords"]}, "고친 칸 옆에 먼저 보인다")
        status, problems = controller.start_save()
        self.assertEqual((status, problems), ("invalid", {"priority_keywords": "overlap", "exclude_keywords": "overlap"}))
        self.assertEqual(errors_of(controller), {"priority_keywords": T["bf_err_overlap_priority_keywords"], "exclude_keywords": T["bf_err_overlap_exclude_keywords"]}, "저장을 시도하면 두 칸 모두")
        self.assertEqual(controller.notice, ("error", T["blogs_save_invalid"]))
        self.assertEqual(controller.provider.calls, calls, "서비스를 부르지 않는다")
        for sentence in errors_of(controller).values():
            self.assertNotIn("예시 키워드 둘", sentence, "입력한 낱말을 되풀이하지 않는다")
        controller.edit("exclude_keywords", "예시 제외어")
        self.assertEqual(errors_of(controller), {}, "한쪽에서 빼면 둘 다 풀린다")
        self.assertEqual(controller.start_save(), ("nothing", None), "저장된 값과 같아졌으니 바꿀 것이 없다")

    def test_swapping_a_word_between_the_two_fields_passes_the_screen_and_is_saved(self):
        controller = new_controller()
        controller.edit("priority_keywords", "예시 키워드 둘, 예시 제외어")
        controller.edit("exclude_keywords", "예시 키워드 하나")
        self.assertEqual(errors_of(controller), {}, "두 칸을 함께 바꾼 최종 값이 겹치지 않으면 통과한다")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        slot = controller.provider.slots["naver_a"]
        self.assertEqual((slot.priority_keywords, slot.exclude_keywords), (("예시 키워드 둘", "예시 제외어"), ("예시 키워드 하나",)))

    def test_a_service_overlap_rejection_marks_both_fields_and_keeps_the_values(self):
        controller = new_controller()
        controller.edit("alias", "고친 별명")
        controller.provider.save_blog = lambda *a: (_ for _ in ()).throw(blogs.BlogFailure("x", code="CONTENT_INVALID", kind="invalid", problems={"priority_keywords": "overlap", "exclude_keywords": "overlap"}))
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", False))
        self.assertEqual(errors_of(controller), {"priority_keywords": T["bf_err_overlap_priority_keywords"], "exclude_keywords": T["bf_err_overlap_exclude_keywords"]})
        self.assertEqual(controller.values("naver_a")["alias"], "고친 별명")
        controller.edit("exclude_keywords", "예시 다른 제외어")
        self.assertNotIn("exclude_keywords", errors_of(controller), "그 칸을 다시 고치면 서비스가 알려 준 문제는 사라진다")

    def test_unedited_topic_fields_follow_the_latest_saved_value_so_a_reload_never_reverts_another_windows_change(self):
        """F1 — 새 칸에도: 다른 창이 바꾼 '고치지 않은' 우선·제외 키워드·글 유형은 다시 읽은 뒤 최신 값이고, 저장해도 낡은 값으로 되돌아가지 않는다."""
        changes = {"priority_keywords": ("다른 창의 우선",), "exclude_keywords": ("다른 창의 제외",), "preferred_post_types": ("장소·업체 정보형",)}
        for name, value in changes.items():
            with self.subTest(field=name):
                controller = new_controller()
                controller.edit("alias", "고친 별명")
                self.assertEqual(set(controller.drafts["naver_a"]), {"alias"}, "초안에는 고친 칸만 있다")
                provider = controller.provider
                provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], **{name: value})
                provider.revision += 1
                load(controller)
                shown = form_of(controller)[name]
                self.assertEqual(controller.dirty_names("naver_a"), ("alias",), "'저장 전 변경' 에 안 고친 칸이 끼지 않는다")
                self.assertEqual(shown["value"], ", ".join(value) if name != "preferred_post_types" else value, "화면 칸도 최신 값이다")
                self.assertFalse(shown["changed"])
                self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
                self.assertEqual(getattr(provider.slots["naver_a"], name), value, "저장해도 다른 창의 변경이 낡은 값으로 되돌아가지 않는다")
                self.assertEqual(provider.slots["naver_a"].alias, "고친 별명")

    def test_the_stale_version_path_keeps_the_other_windows_value_on_the_unedited_topic_field_and_the_typed_value_on_the_edited_one(self):
        controller = new_controller()
        controller.edit("exclude_keywords", "내가 친 제외어")
        provider = controller.provider
        provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], priority_keywords=("다른 창의 우선",), preferred_post_types=("정보형",))
        provider.revision += 1
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", True))
        load(controller)
        self.assertEqual(controller.notice, ("warning", T["blogs_stale_reloaded"]))
        values = controller.values("naver_a")
        self.assertEqual((values["priority_keywords"], values["exclude_keywords"], values["preferred_post_types"]), ("다른 창의 우선", "내가 친 제외어", ("정보형",)))
        self.assertEqual(controller.dirty_names("naver_a"), ("exclude_keywords",))
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        saved = provider.slots["naver_a"]
        self.assertEqual((saved.priority_keywords, saved.exclude_keywords, saved.preferred_post_types), (("다른 창의 우선",), ("내가 친 제외어",), ("정보형",)))

    def test_when_another_window_makes_the_typed_word_overlap_the_save_is_blocked_instead_of_silently_overriding(self):
        controller = new_controller()
        controller.edit("exclude_keywords", "겹치게 될 낱말")
        provider = controller.provider
        provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], priority_keywords=("겹치게 될 낱말",))
        provider.revision += 1
        load(controller)
        calls = list(provider.calls)
        status, problems = controller.start_save()
        self.assertEqual((status, problems), ("invalid", {"priority_keywords": "overlap", "exclude_keywords": "overlap"}))
        self.assertEqual(provider.calls, calls, "다른 창이 바꾼 우선 키워드를 조용히 덮지도, 겹친 채 쓰지도 않는다")
        self.assertEqual(provider.slots["naver_a"].priority_keywords, ("겹치게 될 낱말",))

    def test_clone_copies_the_three_fields_and_clear_empties_them_in_the_fake_provider(self):
        controller = new_controller()
        controller.select("blogger_ko")
        controller.edit("priority_keywords", "예시 우선")
        controller.edit("exclude_keywords", "예시 제외")
        controller.toggle_choice("preferred_post_types", "비교형")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual(drive(controller, controller.start_clone), ("started", "ok", False))
        self.assertEqual(controller.selected, "blogger_en")
        copied = controller.provider.slots["blogger_en"]
        self.assertEqual((copied.priority_keywords, copied.exclude_keywords, copied.preferred_post_types), (("예시 우선",), ("예시 제외",), ("비교형",)))
        self.assertEqual(drive(controller, controller.start_clear), ("started", "ok", False))
        cleared = controller.provider.slots["blogger_en"]
        self.assertEqual((cleared.priority_keywords, cleared.exclude_keywords, cleared.preferred_post_types), ((), (), ()))
        self.assertEqual(controller.provider.slots["blogger_ko"].priority_keywords, ("예시 우선",), "원본은 그대로")

    def test_a_slot_with_only_a_topic_field_set_is_not_empty_so_it_cannot_be_overwritten_by_a_clone_and_can_be_cleared(self):
        for name, value in (("priority_keywords", "예시 우선"), ("exclude_keywords", "예시 제외"), ("preferred_post_types", ("정보형",))):
            with self.subTest(field=name):
                values = {**bf.default_values("naver_b"), name: value}
                self.assertFalse(bf.is_empty_values("naver_b", values))
        controller = new_controller("empty")
        controller.edit("blog_ref", "example-blog-a")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual(controller.clone_info()[0], True, "네이버 B 가 비어 있어 복제할 자리가 있다")
        provider = controller.provider
        provider.slots["naver_b"] = dataclasses.replace(provider.slots["naver_b"], priority_keywords=("예시 우선",))                 # 손으로 고친 파일처럼 — 화면으로는 블로그 ID 없이 저장할 수 없다
        provider.revision += 1
        load(controller)
        self.assertEqual(controller.clone_info()[0], False, "네이버 B 에 우선 키워드가 있어 복제할 빈 자리가 없다")
        controller.select("naver_b")
        self.assertTrue(controller.can_clear(), "세 칸 중 하나만 있어도 비어 있지 않아 지울 수 있다(확인창 뒤)")
        self.assertEqual(drive(controller, controller.start_clear), ("started", "ok", False))
        self.assertEqual(controller.provider.slots["naver_b"].priority_keywords, (), "지우면 우선 키워드도 비워진다")
        self.assertFalse(controller.can_clear(), "이미 비었다")

    def test_nothing_in_the_view_model_is_a_code_a_python_list_or_a_field_name_after_an_overlap_failure(self):
        import re
        controller = new_controller()
        controller.edit("exclude_keywords", "예시 키워드 하나")
        controller.start_save()
        strings = []

        def walk(value):
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key not in ("key", "name", "kind", "preset", "tone", "value", "level", "state", "selected", "dirty_names"):      # `dirty_names` 는 화면에 그리지 않는 내부 칸 이름 목록이다
                        walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(controller.view())
        self.assertGreater(len(strings), 40)
        for item in strings:
            self.assertIsNone(re.search(r"\[['\"]|Traceback|Exception|\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b|[A-Za-z]:[\\/]|AppError|None\b|True\b|False\b|priority_keywords|exclude_keywords|preferred_post_types", item), item)
            for word in text.FORBIDDEN:
                self.assertNotIn(word, item)


# ---- 4) 가짜 공급자 = 서비스 ---------------------------------------------------------------------------------------------------------------
class FakeProviderTest(unittest.TestCase):
    def test_the_sample_values_are_made_up_and_the_fake_never_touches_the_disk(self):
        provider = blogs.FakeBlogsProvider()
        with tempfile.TemporaryDirectory() as tmp:
            before = sorted(str(path) for path in Path(tmp).rglob("*"))
            data = provider.load_blogs(SAFE, NEVER)
            provider.save_blog("naver_a", {"priority_keywords": ("메모리에서만",)}, data.version, SAFE, NEVER)
            self.assertEqual(sorted(str(path) for path in Path(tmp).rglob("*")), before)
        by_key = provider.load_blogs(SAFE, NEVER).by_key()
        self.assertEqual(by_key["naver_a"].priority_keywords, ("메모리에서만",))
        for slot in blogs.FakeBlogsProvider().load_blogs(SAFE, NEVER).slots:
            for word in slot.priority_keywords + slot.exclude_keywords:
                self.assertTrue(word.startswith("예시"), word)
            self.assertTrue(set(slot.preferred_post_types) <= set(POST_TYPES))
        self.assertTrue(blogs.FakeBlogsProvider("empty").load_blogs(SAFE, NEVER).slots[0].priority_keywords == ())

    def test_the_fake_and_the_real_service_give_the_same_result_for_the_same_topic_steps(self):
        steps = (("save_blog", ("naver_a", {"display_name": "예시 블로그 가", "blog_ref": "example-blog-a"})),
                 ("save_blog", ("naver_a", {"priority_keywords": ("예시 우선 하나", "예시 우선 둘"), "preferred_post_types": ("정보형", "비교형")})),
                 ("save_blog", ("naver_a", {"priority_keywords": ("예시 우선 하나", "예시 우선 둘"), "preferred_post_types": ("정보형", "비교형")})),
                 ("save_blog", ("naver_a", {"exclude_keywords": ("예시 우선 하나",)})),                                          # 저장된 우선과 겹침 → 거절
                 ("save_blog", ("naver_a", {"exclude_keywords": ("예시 제외 하나",)})),
                 ("save_blog", ("naver_a", {"priority_keywords": ("예시 제외 하나",)})),                                         # 저장된 제외와 겹침 → 거절
                 ("save_blog", ("naver_a", {"priority_keywords": ("예시 제외 하나",), "exclude_keywords": ("예시 제외 하나",)})),   # 두 칸 모두 같은 낱말 → 거절
                 ("save_blog", ("naver_a", {"priority_keywords": ("예시 제외 하나",), "exclude_keywords": ("예시 우선 하나", "예시 우선 둘")})),      # 바꿔치기 → 저장됨
                 ("save_blog", ("naver_a", {"priority_keywords": ("가" * 31,)})), ("save_blog", ("naver_a", {"exclude_keywords": ("가", "가")})),
                 ("save_blog", ("naver_a", {"priority_keywords": tuple(f"낱말{index}" for index in range(21))})),
                 ("save_blog", ("naver_a", {"preferred_post_types": ("후기형",)})), ("save_blog", ("naver_a", {"preferred_post_types": ("정보형", "정보형")})),
                 ("save_blog", ("naver_a", {"priority_keywords": ("가" * 31,), "exclude_keywords": ("x",)})),
                 ("save_blog", ("naver_a", {"preferred_post_types": ()})), ("save_blog", ("naver_a", {"exclude_keywords": ()})),
                 ("clone_blog", ("naver_a", "naver_b")), ("clone_blog", ("naver_a", "naver_b")),
                 ("save_blog", ("naver_b", {"preferred_post_types": ("문제 해결형", "제품·서비스 소개형")})),
                 ("clear_blog", ("naver_a",)), ("clear_blog", ("naver_a",)), ("clear_blog", ("naver_b",)))
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp)
            real = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            fake = blogs.FakeBlogsProvider("empty")
            for name, args in steps:
                results = []
                for provider in (real, fake):
                    version = provider.load_blogs(SAFE, NEVER).version
                    try:
                        outcome = getattr(provider, name)(*args, version, SAFE, NEVER)
                        results.append((outcome.kind, outcome.changed, tuple(slot.raw() for slot in outcome.data.slots)))
                    except blogs.BlogFailure as failure:
                        results.append((failure.kind, tuple(sorted(failure.problems)), tuple(sorted({"overlap" if reason == "overlap" else "other" for reason in failure.problems.values()}))))      # 칸마다의 이유 이름은 화면 쪽이 더 잘게 가른다 — 겹침인지 아닌지만 견준다
                with self.subTest(step=name, args=args):
                    self.assertEqual(results[0], results[1])


# ---- 5) 실제 어댑터(임시 폴더) -------------------------------------------------------------------------------------------------------------
class SpyProvider(blogs_adapter.ServiceBlogsProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.writes = []

    def save_blog(self, key, fields, version, progress, cancelled):
        self.writes.append(("save", key, dict(fields)))
        return super().save_blog(key, fields, version, progress, cancelled)


class AdapterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.ctx = ss.make_ctx(tmp.name)
        self.root = Path(self.ctx.workspace.root)
        self.paths = tf.topic_paths(self.ctx.workspace)
        self.provider = SpyProvider(context_factory=lambda data_dir=None: self.ctx)

    def controller(self):
        controller = blogs_view.BlogsController(self.provider, jobs.JobRunner())
        load(controller)
        return controller

    def tree(self):
        return ss.tree_snapshot(self.root)

    def hand_edit(self, **changes):
        profiles = tuple(dataclasses.replace(p, **changes) if p.key == "naver_a" else p for p in ch.default_profiles())
        self.paths.folder.mkdir(parents=True, exist_ok=True)
        self.paths.profiles.write_text(json.dumps(ch.profiles_to_dict(profiles), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_typing_selecting_toggling_and_reverting_the_three_fields_write_nothing_in_a_missing_blank_and_hand_edited_folder(self):
        folder = self.root / "topic_engine"
        for prepare in (lambda: None, lambda: (folder.mkdir(parents=True), (folder / "channel_profiles.json").write_bytes(b"")),
                        lambda: self.hand_edit(priority_keywords=("예시 우선",), exclude_keywords=("예시 제외",), preferred_post_types=("정보형",), home_regions=("예시 지역",))):
            prepare()
            before, listing = self.tree(), sorted(str(path) for path in self.root.parent.rglob("*"))
            controller = self.controller()
            controller.edit("priority_keywords", "예시 새 우선, 예시 새 우선 둘")
            controller.edit("exclude_keywords", "예시 우선")
            controller.toggle_choice("preferred_post_types", "비교형")
            controller.select("naver_b")
            controller.edit("exclude_keywords", "예시 다른 제외")
            controller.select("naver_a")
            controller.view()
            controller.revert()
            self.assertEqual(self.tree(), before)
            self.assertEqual(sorted(str(path) for path in self.root.parent.rglob("*")), listing, "읽기·고치기는 파일도 폴더도 만들지 않는다")
            self.assertEqual(self.provider.writes, [], "서비스의 쓰기 함수를 부르지 않았다")

    def test_a_save_through_the_adapter_writes_exactly_the_profile_file_and_a_fresh_screen_shows_the_saved_values(self):
        controller = self.controller()
        controller.edit("display_name", "예시 블로그 가")
        controller.edit("blog_ref", "example-blog-a")
        controller.edit("priority_keywords", "예시 우선 하나, 예시 우선 둘")
        controller.edit("exclude_keywords", "예시 제외어")
        controller.toggle_choice("preferred_post_types", "문제 해결형")
        controller.toggle_choice("preferred_post_types", "정보형")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual(sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file() and path.name != "settings.json"), ["topic_engine/channel_profiles.json"])
        fresh = self.controller()
        values = fresh.values("naver_a")
        self.assertEqual((values["priority_keywords"], values["exclude_keywords"], values["preferred_post_types"]), ("예시 우선 하나, 예시 우선 둘", "예시 제외어", ("정보형", "문제 해결형")))
        stored = {profile.key: profile for profile in bp.read_snapshot(self.ctx).profiles}["naver_a"]
        self.assertEqual((stored.priority_keywords, stored.exclude_keywords, stored.preferred_post_types), (("예시 우선 하나", "예시 우선 둘"), ("예시 제외어",), ("정보형", "문제 해결형")))
        self.assertEqual(self.provider.writes[0][2].keys(), {"display_name", "blog_ref", "priority_keywords", "exclude_keywords", "preferred_post_types"}, "서비스에는 고친 칸만 간다")

    def test_a_hand_edited_version_two_file_shows_the_three_values_and_saving_another_field_keeps_them(self):
        self.hand_edit(blog_ref="example-blog-a", priority_keywords=("예시 우선",), exclude_keywords=("예시 제외",), preferred_post_types=("비교형", "정보형"), home_regions=("예시 지역",), top_n=9)
        controller = self.controller()
        values = controller.values("naver_a")
        self.assertEqual((values["priority_keywords"], values["exclude_keywords"], values["preferred_post_types"]), ("예시 우선", "예시 제외", ("비교형", "정보형")))
        shown = form_of(controller)
        self.assertEqual((shown["priority_keywords"]["value"], shown["preferred_post_types"]["value"]), ("예시 우선", ("비교형", "정보형")))
        self.assertFalse(controller.is_dirty("naver_a"), "손으로 적은 순서가 달라도 고친 것이 아니다")
        controller.edit("alias", "예시 별명")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual(set(self.provider.writes[0][2]), {"alias"}, "고친 칸만 보낸다 — 손으로 쓴 세 칸은 건드리지 않는다")
        after = {profile.key: profile for profile in bp.read_snapshot(self.ctx).profiles}["naver_a"]
        self.assertEqual((after.priority_keywords, after.exclude_keywords, after.preferred_post_types, after.home_regions, after.top_n), (("예시 우선",), ("예시 제외",), ("비교형", "정보형"), ("예시 지역",), 9))

    def test_the_real_service_refuses_an_overlap_with_the_stored_other_field_and_nothing_is_written(self):
        self.hand_edit(priority_keywords=("예시 겹침",), exclude_keywords=("예시 제외",))
        version = self.provider.load_blogs(SAFE, NEVER).version
        before = self.tree()
        with self.assertRaises(blogs.BlogFailure) as caught:
            self.provider.save_blog("naver_a", {"exclude_keywords": ("예시 제외", "예시 겹침")}, version, SAFE, NEVER)
        self.assertEqual((caught.exception.kind, caught.exception.problems), ("invalid", {"priority_keywords": "overlap", "exclude_keywords": "overlap"}))
        self.assertNotIn("예시 겹침", caught.exception.user_message + repr(caught.exception.problems))
        self.assertEqual(self.tree(), before)
        done = self.provider.save_blog("naver_a", {"priority_keywords": ("예시 제외",), "exclude_keywords": ("예시 겹침",)}, version, SAFE, NEVER)
        self.assertEqual(done.kind, "saved", "바꿔치기는 저장된다")

    def test_the_screen_blocks_an_overlap_before_the_service_is_ever_called_and_a_key_shaped_word_is_refused_with_the_field_beside_it(self):
        controller = self.controller()
        controller.edit("blog_ref", "example-blog-a")
        controller.edit("priority_keywords", "예시 우선")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        writes = len(self.provider.writes)
        controller.edit("exclude_keywords", "예시 우선")
        self.assertEqual(controller.start_save()[0], "invalid")
        self.assertEqual(len(self.provider.writes), writes, "화면이 먼저 막는다")
        controller.edit("exclude_keywords", "AK" + "IA" + "ABCDEFGHIJKLMNOP")                         # 키 모양은 화면이 모르고 서비스가 거른다 — 조각으로 나눠 적어 저장소에 키 문자열이 없다
        before = self.tree()
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", False))
        self.assertEqual(self.tree(), before)
        self.assertEqual(errors_of(controller), {"exclude_keywords": T["bf_err_key_shape"]})
        self.assertNotIn("AK" + "IA", " ".join(errors_of(controller).values()) + repr(controller.notice), "오류 문장·알림에 키 모양이 되풀이되지 않는다")
        self.assertEqual(controller.values("naver_a")["exclude_keywords"], "AK" + "IA" + "ABCDEFGHIJKLMNOP", "입력은 그대로 남는다")

    def test_a_version_one_file_shows_the_three_fields_empty_and_the_first_save_upgrades_it(self):
        data = ch.profiles_to_dict(ch.default_profiles())
        data["schema"] = 1
        data["profiles"] = [{name: value for name, value in item.items() if name in ch._KEYS_V1} for item in data["profiles"]]
        self.paths.folder.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.paths.profiles.write_bytes(raw)
        controller = self.controller()
        shown = form_of(controller)
        self.assertEqual((shown["priority_keywords"]["value"], shown["exclude_keywords"]["value"], shown["preferred_post_types"]["value"]), ("", "", ()))
        self.assertEqual(self.paths.profiles.read_bytes(), raw, "읽기는 다시 쓰지 않는다")
        controller.edit("blog_ref", "example-blog-a")                                              # 화면은 블로그 ID 가 있어야 저장한다(필수 칸)
        controller.edit("priority_keywords", "예시 우선")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual((self.paths.folder / "channel_profiles.json.v1.bak").read_bytes(), raw, "옛 모양 그대로의 사본")
        self.assertEqual(json.loads(self.paths.profiles.read_text(encoding="utf-8"))["schema"], 2)


# ---- 6) 소스 규칙 ---------------------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    def test_the_screen_layer_never_reads_the_three_fields_from_a_file_and_the_new_tests_use_made_up_words_only(self):
        for name in ("test_service_blog_profiles_topic.py", "test_ui_blogs_topic.py"):
            source = (ROOT / "tests" / name).read_text(encoding="utf-8")
            for word in ("ssae" + "ssace", "shine" + "5652", "스마트" + "프라이싱", "디지털" + "찬스"):
                self.assertNotIn(word, source, name)
        for name in ("blog_form.py", "blogs.py", "blogs_view.py", "blog_text.py"):
            source = (SRC / "ui" / "core" / name).read_text(encoding="utf-8")
            self.assertNotIn("open(", source, name)

    def test_the_form_fields_the_screen_knows_are_exactly_the_services_for_every_slot(self):
        for key in bp.SLOTS:
            self.assertEqual({spec.name for spec in bf.fields_for(key)}, set(bp.form_fields(key)), key)
        self.assertEqual({spec.name for spec in bf.FIELDS} - {"generation_enabled"}, set(bp.COMMON_FIELDS))


if __name__ == "__main__":
    unittest.main()
