"""Seed 관리 화면의 순수 부분 시험(PySide6 없이 돈다 — CI 와 같은 조건) — 폼 규칙·값 다듬기·칸 옆 문장·거르기·개수 요약·일괄 변경 미리 보기·상태/동작(`SeedsController`)·뷰모델·가짜 공급자와 실제 어댑터.

지키는 것:
  1) 칸 표의 한도는 서비스(`topics/seeds.py`)의 상수 그대로이고 고치는 칸은 서비스 `EDITABLE` 과 같다. 상태·소속·중요도·대상 유형·채널·협찬 분야 이름은 서비스 표와 같은 글이다.
  2) 검사 판정은 서비스 `Seed` 생성자와 **같다** — 경계·공백·위험한 표기·중복·결과 약속 표현·겹침을 수백 가지 입력으로 견준다(칸이 필수인 것은 화면만의 규칙).
  3) 거르기·찾기·고르기·서랍 열기·칸 고치기는 파일에 닿지 않는다(임시 폴더 전체 바이트가 그대로). 쓰기는 승인·바꾸기·저장·등록·불러오기를 눌렀을 때만이고 **일괄 변경·제안 파일 등록은 확인창을 보이기 전에는 하지 않는다**.
  4) 입력은 지워지지 않는다: 저장이 실패해도 초안이 그대로이고 서랍을 닫았다 열어도 남으며 성공하면 그 씨앗만 비운다. 칸에 문제가 있으면 서비스를 부르지 않는다.
  5) 180일 '쉬게 할까요' 는 보이기만 하고 자동으로 바뀌지 않는다. 승인 전 씨앗의 승인은 사용자가 그 씨앗(또는 고른 씨앗들)에 눌렀을 때만 일어난다.
  6) 가짜 공급자(`--sample`·시험·사진)는 메모리에서만 일하고 같은 일을 서비스에 해 본 결과와 같다.
  7) 화면 코드(`ui/core`·`ui/qt`)에는 파일을 쓰는 호출이 없고, 쓰는 길은 어댑터가 부르는 서비스 함수 다섯뿐이다. 실제 Seed 낱말·블로그 이름은 어디에도 없다 — 예시는 가짜 낱말뿐이다.
"""
import ast
import dataclasses
import itertools
import re
import sys
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import seed_manage as sm  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.topics import wording  # noqa: E402
from chanceblog_desktop.ui import adapters, seeds_adapter  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs, seed_form as sf, seed_rules as rules, seed_text, seeds, seeds_view, services, text  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
T = text.T
DAY = seeds.SAMPLE_DAY
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"


def load(controller, provider=None):
    data = (provider or controller.provider).load_seeds(SAFE, NEVER)
    controller.apply_loaded(data)
    return data


def new_controller(scenario="normal", **kwargs):
    provider = seeds.FakeSeedsProvider(scenario, **kwargs)
    controller = seeds_view.SeedsController(provider, jobs.JobRunner())
    load(controller)
    return controller


def drive(controller, starter):
    """쓰기를 시작하고 끝까지 기다려 결과를 받는다(셸이 하는 일과 같다). → (시작 상태, 끝난 일: 'ok'·'failed'·None, 충돌이라 다시 읽어야 하나)."""
    results = {}
    status, detail = starter(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if status != "started":
        return status, detail, False
    detail.join(10)
    if "ok" in results:
        controller.apply_write_ok(results["ok"])
        return status, "ok", False
    return status, "failed", controller.apply_write_failed(results["failed"])


def states(controller):
    return {seed.seed_id: seed.state for seed in controller.seeds()}


class Failing(seeds.FakeSeedsProvider):
    """정해 둔 이름의 쓰기가 정해 둔 실패로 끝나는 가짜 공급자."""

    def __init__(self, fail, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail = fail

    def _enter(self, name, version, cancelled):
        super()._enter(name, version, cancelled)
        if name in self.fail:
            raise self.fail[name]


class Gated(seeds.FakeSeedsProvider):
    """쓰기가 시험이 문을 열어 줄 때까지 기다리는 가짜 공급자 — 시간에 기대지 않고 '쓰는 중' 을 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def _enter(self, name, version, cancelled):
        if not self.gate.wait(30):
            raise AssertionError("시험이 쓰기의 문을 열어 주지 않았다")
        super()._enter(name, version, cancelled)


# ---- 1) 칸 표·이름 ----------------------------------------------------------------------------------------------------------------------
class SpecTest(unittest.TestCase):
    def test_the_limits_are_the_service_constants(self):
        edit = sf.EDIT_SPEC
        self.assertEqual((edit["excluded_keywords"].count, edit["excluded_keywords"].limit, edit["priority_keywords"].count, edit["priority_keywords"].limit, edit["reason"].limit),
                         (sd.MAX_EXCLUDED, sd.MAX_EXCLUDED_WORD, sd.MAX_PRIORITY_KEYWORDS, sd.MAX_EXCLUDED_WORD, sd.MAX_REASON))
        create = sf.CREATE_SPEC
        self.assertEqual((create["keyword"].limit, create["major"].limit, create["minor"].limit), (sd.MAX_KEYWORD, ch.MAX_NAME, ch.MAX_NAME))
        self.assertEqual((sd.MAX_EXCLUDED, sd.MAX_EXCLUDED_WORD, sd.MAX_PRIORITY_KEYWORDS, sd.MAX_KEYWORD, sd.MAX_REASON, ch.MAX_NAME), (20, 30, 10, 60, 200, 30), "계획 표의 값")

    def test_the_edit_fields_are_the_service_editable_fields_and_the_create_fields_are_the_service_create_fields(self):
        self.assertEqual({spec.name for spec in sf.EDIT_FIELDS}, set(sm.EDITABLE))
        self.assertEqual({spec.name for spec in sf.CREATE_FIELDS}, set(sm.CREATE_REQUIRED) | set(sm.CREATE_OPTIONAL))
        self.assertEqual(set(sf.IMPORTANCE_CREATE), set(sm.CREATE_SEED_TYPES))
        self.assertEqual([spec.name for spec in sf.CREATE_FIELDS if spec.required], ["keyword", "major", "minor", "seed_type", "target_type", "scope"])
        for forbidden in ("state", "seed_id", "active_since", "registered_on", "prepare_from", "publish_from", "publish_until", "peak_period", "recurrence", "password", "api_key", "token", "secret"):
            self.assertNotIn(forbidden, {spec.name for spec in sf.EDIT_FIELDS} | {spec.name for spec in sf.CREATE_FIELDS})

    def test_the_names_are_the_service_names(self):
        for code in sd.SCOPES:
            self.assertEqual(sf.scope_name(code), wording.SCOPE_KO[code])
        for kind in sd.SEED_TYPES:
            self.assertEqual(sf.importance_name(kind), wording.SEED_TYPE_KO[kind])
        for state in sd.STATES:
            self.assertEqual(sf.state_name(state), sd.STATE_KO[state])
        self.assertEqual(sf.state_name("proposed"), "제안(승인 전)")
        self.assertEqual(sf.target_name(None), T["seeds_target_none"])
        self.assertEqual(sf.target_name("pc_part"), "PC 부품")
        self.assertEqual(sf.TAG_ORDER, tuple(wording.TAG_KO))
        self.assertEqual(sf.CHANNEL_ORDER, ch.CHANNELS)
        self.assertEqual(sf.SCOPE_ORDER, sd.SCOPES)

    def test_the_create_form_shows_the_channel_field_only_for_common_and_the_tag_only_for_sponsorable(self):
        names = lambda **raw: [spec.name for spec in sf.create_fields_for({**sf.new_raw(), **raw})]  # noqa: E731
        self.assertNotIn("allowed_channels", names())
        self.assertIn("allowed_channels", names(scope="common"))
        self.assertNotIn("allowed_channels", names(scope="naver_a"))
        self.assertNotIn("sponsor_tag", names())
        self.assertIn("sponsor_tag", names(seed_type="sponsorable"))
        seed = ts.example_seed(scope="naver_a", state="proposed")
        self.assertNotIn("allowed_channels", [spec.name for spec in sf.edit_fields_for(seed)])
        self.assertIn("allowed_channels", [spec.name for spec in sf.edit_fields_for(ts.example_seed(scope="common"))])

    def test_every_problem_has_an_easy_sentence_that_never_repeats_what_was_typed(self):
        problems = ("required", "too_long", "too_many", "item_too_long", "duplicate", "markup", "overlap", "no_letters", "claim", "same_word", "channels_none", "tag_needed", "brand_reason", "bad_choice", "key_shape", "invalid")
        for name, spec in itertools.chain(sf.EDIT_SPEC.items(), sf.CREATE_SPEC.items()):
            for problem in problems:
                sentence = sf.problem_text(spec, problem, KEY_SHAPED if spec.kind in ("line", "words") else None)
                with self.subTest(field=name, problem=problem):
                    self.assertTrue(sentence)
                    self.assertNotIn(KEY_SHAPED, sentence)
                    self.assertNotRegex(sentence, r"\['|\bNone\b|Error|Traceback")
        self.assertEqual(sf.problem_text(sf.CREATE_SPEC["keyword"], ""), "")
        self.assertIn("60", sf.problem_text(sf.CREATE_SPEC["keyword"], "too_long", "가" * 70), "한도 숫자를 알려 준다")
        self.assertIn("70", sf.problem_text(sf.CREATE_SPEC["keyword"], "too_long", "가" * 70), "지금 글자 수도 알려 준다")


# ---- 2) 값 다듬기와 서비스와 같은 판정 ------------------------------------------------------------------------------------------------------
class NormalizeTest(unittest.TestCase):
    def test_lines_words_flags_channels_and_choices_are_cleaned_the_way_the_service_expects(self):
        spec = sf.EDIT_SPEC
        self.assertEqual(sf.normalize(spec["reason"], "  가   나\n다  "), "가 나 다")
        self.assertEqual(sf.normalize(spec["excluded_keywords"], " 가 , 나;다\n라, ,  "), ("가", "나", "다", "라"))
        self.assertEqual(sf.normalize(spec["priority"], 1), True)
        self.assertEqual(sf.normalize(spec["allowed_channels"], ("naver_b", "github_pages", "naver_b", "nope")), ("github_pages", "naver_b"), "코드 순서·중복 없음·모르는 이름은 버림")
        create = sf.CREATE_SPEC
        self.assertIsNone(sf.normalize(create["sponsor_tag"], ""))
        self.assertIsNone(sf.normalize(create["scope"], None))
        self.assertEqual(sf.normalize(create["scope"], "common"), "common")

    def test_changes_are_found_after_cleaning_so_a_space_only_edit_is_not_a_change(self):
        seed = ts.example_seed(scope="common", excluded_keywords=("가", "나"), reason="이유")
        fields = sf.edit_fields_for(seed)
        base = sf.raw_from_seed(seed)
        self.assertEqual(sf.dirty_names(fields, base, {**base, "reason": "  이유  ", "excluded_keywords": "가,  나"}), ())
        self.assertEqual(sf.dirty_names(fields, base, {**base, "priority": True, "allowed_channels": ("naver_a",)}), ("priority", "allowed_channels"))

    def test_the_raw_values_of_a_seed_round_trip_into_the_same_typed_values(self):
        seed = ts.example_seed(scope="common", allowed_channels=("naver_b", "naver_a"), priority_keywords=("우선",), excluded_keywords=("제외", "또"), reason="이유", priority=True)
        typed = sf.typed_values(sf.edit_fields_for(seed), sf.raw_from_seed(seed))
        self.assertEqual(typed, {"priority": True, "excluded_keywords": ("제외", "또"), "priority_keywords": ("우선",), "allowed_channels": ("naver_a", "naver_b"), "reason": "이유"})
        self.assertEqual(dataclasses.replace(seed, **typed), seed)


def verdict(call, *args):
    try:
        call(*args)
    except (AppError, sm.SeedProblems):
        return False
    return True


class JudgeTest(unittest.TestCase):
    """화면의 미리 검사와 서비스 `Seed` 생성자의 판정이 같다 — 화면이 통과시킨 값을 서비스가 거절하거나 그 반대인 사고가 없다."""

    WORD_CASES = ((), ("가",), ("가", "나"), ("같음", "같음"), ("같음", "GAME", "game"), ("<b>x</b>",), ("가" * 30,), ("가" * 31,), tuple(f"낱말{n}" for n in range(20)), tuple(f"낱말{n}" for n in range(21)),
                  ("onclick=x",), ("{{ x }}",), ("javascript:x",), ("a b",), ("보장 낱말",))
    LINE_CASES = ("", "가", "가" * 199, "가" * 200, "가" * 201, "<script>x</script>", "{% x %}", "이유 한 줄", "가 나", "a<b")

    def test_edit_values_get_the_same_verdict_as_the_service_for_hundreds_of_inputs(self):
        seeds_under_test = (ts.example_seed(scope="common", state="proposed"), ts.example_seed(scope="naver_a", state="proposed"),
                            ts.example_seed(scope="common", state="active", active_since="2026-10-01", brand_case=True, reason="브랜드 허용 이유"),
                            ts.example_seed(scope="common", state="proposed", excluded_keywords=("제외",)))
        checked = 0
        for seed in seeds_under_test:
            fields = sf.edit_fields_for(seed)
            for excluded, priority, reason in itertools.product(self.WORD_CASES, self.WORD_CASES, self.LINE_CASES):
                raw = {"priority": False, "excluded_keywords": ", ".join(excluded), "priority_keywords": ", ".join(priority), "allowed_channels": ("naver_a",), "reason": reason}
                typed = sf.typed_values(fields, raw)
                screen = not sf.edit_problems(seed, typed)
                service = verdict(sm.apply_fields, seed, dict(typed))
                self.assertEqual(screen, service, (seed.scope, seed.brand_case, excluded, priority, reason[:12], sf.edit_problems(seed, typed)))
                checked += 1
        self.assertGreater(checked, 2000)

    def test_the_channel_field_is_judged_like_the_service(self):
        common = ts.example_seed(scope="common", state="proposed")
        for channels in ((), ("naver_a",), ("naver_a", "naver_b"), CHANNELS_ALL, ("naver_a", "naver_a")):
            typed = sf.typed_values(sf.edit_fields_for(common), {**sf.raw_from_seed(common), "allowed_channels": channels})
            self.assertEqual(not sf.edit_problems(common, typed), verdict(sm.apply_fields, common, dict(typed)), channels)

    def test_create_values_get_the_same_verdict_as_the_service_for_hundreds_of_inputs(self):
        existing = (ts.example_seed(seed_id="ex-old", keyword="예시 있던 낱말", scope="naver_a", state="proposed"),)
        keywords = ("예시 새 낱말", "", "가" * 60, "가" * 61, "<b>x</b>", "!!!", "...", "보장 제습기", "예시 있던 낱말", "예시있던낱말", "예시-있던-낱말", "{기준 지역} 낱말", "a", "100% 보장")
        checked = 0
        for keyword, major, scope, kind, target, sponsor in itertools.product(keywords, ("예시 대분류", "", "가" * 30, "가" * 31, "<i>x</i>"), ("naver_a", "common", "naver_z", ""), ("general", "seasonal", "sponsorable", ""),
                                                                              ("product", "gadget", ""), ("", "pc_parts", "Not A Tag")):
            raw = {**sf.new_raw(), "keyword": keyword, "major": major, "minor": "예시 중분류", "scope": scope, "seed_type": kind, "target_type": target, "sponsor_tag": sponsor, "allowed_channels": ("naver_a", "naver_b")}
            fields = sf.create_fields_for(raw)
            typed = sf.typed_values(sf.CREATE_FIELDS, raw)
            problems = {name: problem for name, problem in sf.create_problems(typed, existing).items() if name in {spec.name for spec in fields}}
            values = sf.service_values(fields, typed)
            service = verdict(sm.new_seed, existing, values, DAY) if all(name in values for name in sm.CREATE_REQUIRED) else False
            if all(name in values for name in sm.CREATE_REQUIRED):
                self.assertEqual(not problems, service, (keyword[:14], major[:6], scope, kind, target, sponsor, problems))
            else:
                self.assertTrue(problems, "서비스에 보낼 수 없는 값은 화면이 먼저 문제로 알린다")
            checked += 1
        self.assertGreater(checked, 3000)

    def test_the_keyword_overlap_rule_is_the_services_not_a_spelling_match(self):
        seed = ts.example_seed(scope="naver_a", state="proposed")
        for excluded, priority in ((("가나",), ("가 나",)), (("A.I.",), ("ai",)), (("가",), ("나",)), (("!!",), ("??",))):
            typed = sf.typed_values(sf.edit_fields_for(seed), {**sf.raw_from_seed(seed), "excluded_keywords": ", ".join(excluded), "priority_keywords": ", ".join(priority)})
            self.assertEqual(not sf.edit_problems(seed, typed), verdict(sm.apply_fields, seed, dict(typed)), (excluded, priority))


CHANNELS_ALL = ch.CHANNELS


# ---- 3) 목록 규칙 --------------------------------------------------------------------------------------------------------------------------
class RulesTest(unittest.TestCase):
    def setUp(self):
        self.seeds = seeds.FakeSeedsProvider().load_seeds(SAFE, NEVER).seeds

    def test_the_status_counts_add_up_and_the_filters_each_keep_only_what_they_name(self):
        counts = rules.status_counts(self.seeds)
        self.assertEqual((counts["all"], counts["proposed"] + counts["active"] + counts["inactive"]), (16, 16))
        for state in sd.STATES:
            self.assertEqual({seed.state for seed in self.seeds if rules.matches(seed, status=state)}, {state})
        self.assertTrue(all(seed.scope == "common" for seed in self.seeds if rules.matches(seed, scope="common")))
        self.assertTrue(all(seed.seed_type == "seasonal" for seed in self.seeds if rules.matches(seed, importance="seasonal")))
        self.assertEqual([seed.seed_id for seed in self.seeds if rules.matches(seed)], [seed.seed_id for seed in self.seeds], "조건이 없으면 모두, 파일 순서")

    def test_the_search_needs_every_piece_in_the_word_or_the_two_category_names_and_ignores_case(self):
        words = rules.query_words("  예시   낱말  가 ")
        self.assertEqual(words, ("예시", "낱말", "가"))
        self.assertEqual([seed.seed_id for seed in self.seeds if rules.matches(seed, words=words)], ["EX001"])
        self.assertEqual({seed.seed_id for seed in self.seeds if rules.matches(seed, words=rules.query_words("대분류 둘"))}, {"EX002", "EX003", "EX004", "EX005", "EX009", "EX010", "EX013"},
                         "조각마다 낱말·대분류·중분류 어디에 있어도 되고 모든 조각이 있어야 한다(둘은 대분류 '둘' 이거나 중분류 '둘')")
        upper = ts.example_seed(keyword="GPU Guide", state="proposed")
        self.assertTrue(rules.matches(upper, words=rules.query_words("gpu guide")))
        self.assertFalse(rules.matches(upper, words=rules.query_words("gpu 없는조각")))
        self.assertEqual(rules.query_words(None), ())
        self.assertEqual(rules.query_words("   "), ())

    def test_the_usable_counts_are_the_services_usable_seeds_per_channel(self):
        counts = rules.usable_counts(self.seeds)
        for code in ch.CHANNELS:
            self.assertEqual(counts[code], len(sd.usable_seeds(self.seeds, code)), code)
        self.assertEqual(counts["naver_a"], 3, "사용 중이고 네이버 A 를 허용한 것은 셋뿐이다(승인 전·쉬는 중은 세지 않는다)")
        shifted = rules.usable_counts(self.seeds, {"EX001": "active"})
        self.assertEqual(shifted["naver_a"], counts["naver_a"] + 1, "가정한 상태로 미리 계산한다(원본은 안 바뀐다)")
        self.assertEqual(self.seeds[0].state, "proposed")

    def test_the_channel_rows_follow_the_channel_order_and_say_when_generation_is_unknown(self):
        rows = rules.channel_rows(self.seeds, seeds.DEFAULT_GENERATION)
        self.assertEqual([row["key"] for row in rows], list(ch.CHANNELS))
        self.assertEqual({row["key"]: row["generation"] for row in rows}, {"github_pages": False, "blogger_en": False, "blogger_ko": False, "naver_a": True, "naver_b": True})
        unknown = rules.channel_rows(self.seeds, tuple((code, None) for code in ch.CHANNELS))
        self.assertEqual({row["generation"] for row in unknown}, {None})
        self.assertEqual({rules.generation_text(flag) for flag in (True, False, None)}, {T["seeds_gen_on"], T["seeds_gen_off"], T["seeds_gen_unknown"]})

    def test_the_bulk_kinds_use_exactly_the_services_allowed_transitions(self):
        for kind, target in rules.BULK_TARGET.items():
            for state in sd.STATES:
                self.assertEqual(state in rules.BULK_FROM[kind], target in sd.TRANSITIONS[state], (kind, state))

    def test_the_screen_constants_are_pinned_by_hand_not_by_reading_them_back(self):
        """값을 시험이 모듈에서 읽어 되돌려 쓰지 않는다 — 슬며시 바뀌면 여기서 걸린다(독립 검증의 덧붙임)."""
        self.assertEqual((rules.PAGE, rules.NAMES_SHOWN, rules.REASONS_SHOWN), (40, 5, 5))
        self.assertEqual(rules.STATUS_KEYS, ("all", "proposed", "active", "inactive"))
        self.assertEqual(rules.BULK_KINDS, ("activate", "rest"))
        self.assertEqual(rules.BULK_TARGET, {"activate": "active", "rest": "inactive"})
        self.assertEqual(rules.BULK_FROM, {"activate": ("proposed", "inactive"), "rest": ("proposed", "active")})
        self.assertEqual(seeds_view.WRITE_KEY, "seeds-write")
        self.assertEqual(seeds_view.LOAD_KEY, "seeds-load")

    def test_the_bulk_ids_keep_the_file_order_skip_unknown_numbers_and_the_wrong_states(self):
        picked = {"EX016", "EX001", "EX009", "EX014", "nope"}
        self.assertEqual(rules.bulk_ids(self.seeds, picked, "activate"), ("EX001", "EX014", "EX016"), "승인 전·쉬는 중 → 사용 중(사용 중 EX009 와 모르는 번호는 뺀다)")
        self.assertEqual(rules.bulk_ids(self.seeds, picked, "rest"), ("EX001", "EX009", "EX016"))
        self.assertEqual(rules.bulk_ids(self.seeds, (), "rest"), ())

    def test_the_bulk_preview_counts_names_skipped_and_the_before_and_after_of_each_channel(self):
        plan = rules.bulk_preview(self.seeds, {"EX001", "EX002", "EX003", "EX009", "EX014"}, "activate")
        self.assertEqual((plan["count"], plan["parts"], plan["skipped"], plan["rest"]), (4, {"proposed": 3, "inactive": 1}, 1, 0))
        self.assertEqual(plan["names"], ["예시 낱말 가", "예시 낱말 나", "예시 낱말 다", "예시 낱말 카"])
        by_key = {row["key"]: row for row in plan["channels"]}
        self.assertEqual((by_key["naver_a"]["before"], by_key["naver_a"]["after"]), (3, 6))
        many = seeds.FakeSeedsProvider("many").load_seeds(SAFE, NEVER).seeds
        big = rules.bulk_preview(many, {seed.seed_id for seed in many}, "activate")
        self.assertEqual(len(big["names"]), rules.NAMES_SHOWN)
        self.assertEqual(big["rest"], big["count"] - rules.NAMES_SHOWN)

    def test_names_in_the_preview_are_masked_before_they_are_cut(self):
        leaky = ts.example_seed(seed_id="ex-k", keyword="예시 " + KEY_SHAPED, state="proposed")
        plan = rules.bulk_preview((leaky,), {"ex-k"}, "activate")
        self.assertNotIn(KEY_SHAPED, " ".join(plan["names"]))
        self.assertTrue(plan["names"][0].startswith("예시"), "가린 뒤에도 앞의 글은 남는다")
        self.assertNotEqual(plan["names"][0], "예시 " + KEY_SHAPED[:12], "잘린 앞 조각도 남지 않는다(가리기가 먼저, 자르기가 나중)")

    def test_key_shaped_text_in_a_saved_seed_is_masked_in_the_rows_the_drawer_the_schedule_and_the_dialogs(self):
        """손으로 고친 파일에 키 모양이 들어 있어도 목록 줄·서랍 머리·일괄 변경 확인창·일정 글에는 가려서 보인다(`sf.shown` — 가리기가 먼저, 자르기가 나중). 실제 값을 넣어 직접 확인한다."""
        controller = new_controller()
        leaky = ts.example_seed(seed_id="ex-k", keyword="예시 " + KEY_SHAPED, major="분류 " + KEY_SHAPED, minor="중분류 " + KEY_SHAPED, scope="naver_a", state="proposed", target_type="product")
        controller.provider.seeds.append(leaky)
        controller.provider.revision += 1
        load(controller)
        row = next(item for item in controller.view()["list"]["rows"] if item["id"] == "ex-k")
        for name in ("title", "path", "meta", "channels", "a11y", "check_a11y"):
            self.assertNotIn(KEY_SHAPED, str(row[name]), name)
        self.assertTrue(row["title"].startswith("예시") and row["path"].startswith("분류"), "가린 뒤에도 앞의 글은 남는다")
        controller.open_detail("ex-k")
        drawer = controller.drawer_view()
        for name in ("heading", "path", "title", "a11y"):
            self.assertNotIn(KEY_SHAPED, str(drawer[name]), name)
        self.assertNotIn(KEY_SHAPED, " ".join(str(value) for value in drawer["notes"]) + " ".join(str(item) for item in drawer["info"]))
        controller.close_drawer()
        controller.checked = {"ex-k"}
        dialog = controller.bulk_dialog("activate")
        self.assertNotIn(KEY_SHAPED, " ".join(str(value) for value in dialog.values()))
        self.assertNotIn(KEY_SHAPED, seeds_view.SeedsController._day_text("ZZ-" + KEY_SHAPED, "yearly"), "일정 글을 읽지 못해 그대로 보이는 길에도 가린다")
        self.assertTrue(seeds_view.SeedsController._day_text("ZZ-" + KEY_SHAPED, "yearly").startswith("ZZ-"))


# ---- 4) 상태·동작 ---------------------------------------------------------------------------------------------------------------------------
class ReadAndFilterTest(unittest.TestCase):
    def test_loading_states_and_a_reload_that_drops_what_is_gone(self):
        controller = seeds_view.SeedsController(seeds.FakeSeedsProvider(), jobs.JobRunner())
        self.assertEqual(controller.state, "loading")
        load(controller)
        self.assertEqual((controller.state, len(controller.seeds())), ("normal", 16))
        controller.toggle_check("EX001")
        controller.open_detail("EX002")
        controller.edit("priority", True)
        smaller = dataclasses.replace(controller.data, seeds=tuple(seed for seed in controller.seeds() if seed.seed_id not in ("EX001", "EX002")))
        controller.apply_loaded(smaller)
        self.assertEqual((controller.checked, controller.drawer, controller.drafts), (set(), None, {}), "없어진 씨앗의 고름·서랍·초안은 버린다")

    def test_the_error_state_keeps_what_was_shown_and_says_it_in_easy_words(self):
        controller = new_controller()
        controller.apply_load_failed(seeds.SeedFailure(T["seeds_error_desc"], code="X_ERR", kind="corrupt"))
        self.assertEqual((controller.state, len(controller.seeds())), ("error", 16))
        view = controller.view("code: X_ERR")
        self.assertEqual(view["state"], "error")
        self.assertEqual((view["error"]["title"], view["summary"], view["list"]["rows"]), (T["seeds_error_title"], None, []))
        controller.apply_unexpected(KeyError("secret path"))
        self.assertEqual(controller.state, "error")
        self.assertNotIn("secret path", str(controller.failure.user_message) + str(controller.failure.code))

    def test_filters_search_and_the_page_size_only_change_what_is_shown(self):
        controller = new_controller("many")
        self.assertEqual(len(controller.view()["list"]["rows"]), rules.PAGE)
        self.assertEqual(controller.view()["list"]["more"]["text"], T["seeds_more"].format(n=rules.PAGE))
        controller.show_more()
        controller.show_more()
        self.assertEqual((len(controller.view()["list"]["rows"]), controller.view()["list"]["more"]), (min(130, 3 * rules.PAGE), {"text": T["seeds_more"].format(n=10), "a11y": T["seeds_more_a11y"].format(n=10)}))
        controller.set_status("proposed")
        self.assertEqual(controller.limit, rules.PAGE, "거르기를 바꾸면 처음 쪽으로")
        self.assertTrue(all(row["status"]["text"] == "제안(승인 전)" for row in controller.view()["list"]["rows"]))
        controller.set_scope("common")
        controller.set_importance("general")
        controller.set_query("낱말 01")
        found = controller.view()["list"]
        self.assertTrue(all("낱말 01" in row["title"] for row in found["rows"]))
        self.assertEqual(found["found"], len(controller.found()))
        self.assertTrue(controller.filters_active())
        controller.reset_filters()
        self.assertEqual((controller.filters_active(), controller.view()["list"]["found"]), (False, 130))
        for bad in ("nope", "", None, 3):
            self.assertFalse(controller.set_status(bad) if bad != "all" else False)
        self.assertFalse(controller.set_scope("nope"))
        self.assertFalse(controller.set_importance("nope"))

    def test_the_summary_says_how_many_are_waiting_how_many_each_channel_can_use_and_whether_it_generates(self):
        view = new_controller().view()
        summary = view["summary"]
        self.assertEqual(summary["proposed"]["text"], "승인 전 9개 — 승인하기 전에는 후보 생성에 쓰이지 않습니다")
        self.assertEqual([chip["text"] for chip in summary["chips"]], ["사용 중 5개", "쉬는 중 2개", "전체 16개"])
        rows = {row["key"]: row for row in summary["channels"]["rows"]}
        self.assertEqual(rows["naver_a"]["chip"]["text"], "네이버 A 3개 · 후보 생성 켜짐")
        self.assertEqual(rows["github_pages"]["chip"]["text"], "GitHub Pages 0개 · 후보 생성 꺼짐")
        self.assertEqual((rows["naver_a"]["generation"]["text"], rows["github_pages"]["generation"]["text"]), ("후보 생성 켜짐", "후보 생성 꺼짐"))
        self.assertEqual((rows["naver_a"]["chip"]["tone"], rows["github_pages"]["chip"]["tone"]), ("ok", "muted"))
        self.assertIn("쓸 수 있는 Seed 3개", rows["naver_a"]["a11y"])
        self.assertEqual(summary["channels"]["unknown"], "")
        empty = new_controller("empty").view()
        self.assertEqual(empty["summary"]["proposed"]["text"], T["seeds_sum_no_proposed"])
        self.assertEqual(empty["list"]["empty"]["title"], T["seeds_empty_title"])

    def test_an_unreadable_channel_profile_file_is_told_and_nothing_is_assumed(self):
        controller = new_controller()
        controller.apply_loaded(dataclasses.replace(controller.data, generation=tuple((code, None) for code in ch.CHANNELS)))
        view = controller.view()["summary"]["channels"]
        self.assertEqual({row["generation"]["text"] for row in view["rows"]}, {T["seeds_gen_unknown"]})
        self.assertEqual({row["chip"]["tone"] for row in view["rows"]}, {"warning"})
        self.assertEqual(view["unknown"], T["seeds_profiles_unknown"])

    def test_every_row_carries_the_status_as_words_and_the_idle_suggestion_only_shows(self):
        controller = new_controller()
        rows = {row["id"]: row for row in controller.view()["list"]["rows"]}
        self.assertEqual([row["status"]["text"] for row in (rows["EX001"], rows["EX009"], rows["EX014"])], ["제안(승인 전)", "사용 중", "쉬는 중"])
        self.assertTrue(rows["EX009"]["idle"] and rows["EX009"]["idle_text"] == "쉬게 할까요?")
        self.assertIn("쉬게 할지 정해 보세요", rows["EX009"]["a11y"])
        self.assertFalse(any(rows[key]["idle"] for key in rows if key != "EX009"), "계절형·승인 전·최근 씨앗은 제안에 없다")
        self.assertEqual(states(controller)["EX009"], "active", "보이기만 하고 자동으로 바꾸지 않는다")
        self.assertEqual(rows["EX006"]["flags"], [T["seeds_flag_region"]])
        self.assertEqual(rows["EX007"]["flags"], [T["seeds_flag_brand"]])
        self.assertEqual(rows["EX002"]["flags"], [T["seeds_flag_priority"]])
        self.assertEqual(rows["EX011"]["channels"], "허용 채널 네이버 A, 네이버 B")
        for row in rows.values():
            self.assertTrue(row["status"]["text"], "색만이 아니라 늘 글자가 함께 있다")
            self.assertNotRegex(row["a11y"] + row["meta"] + row["path"], r"proposed|active|inactive|seasonal|None|\['")

    def test_selection_is_kept_across_pages_and_select_all_means_everything_that_matches(self):
        controller = new_controller("many")
        controller.set_status("proposed")
        count = len(controller.found())
        self.assertGreater(count, rules.PAGE)
        controller.select_found()
        self.assertEqual(len(controller.checked), count, "화면에 그린 줄뿐 아니라 조건에 맞는 전부")
        self.assertEqual(controller.view()["bulk"]["select_all"]["text"], T["seeds_bulk_select_all"].format(n=count))
        controller.toggle_check(controller.found()[0].seed_id)
        self.assertEqual(len(controller.checked), count - 1)
        controller.clear_checks()
        self.assertEqual(controller.checked, set())
        self.assertFalse(controller.toggle_check("nope"))


class DrawerAndEditTest(unittest.TestCase):
    def test_opening_a_detail_shows_the_facts_the_notes_and_the_fields_of_that_seed_only(self):
        controller = new_controller()
        self.assertTrue(controller.open_detail("EX005"))
        view = controller.drawer_view()
        self.assertEqual((view["kind"], view["heading"], view["status"]["text"]), ("seed", "예시 낱말 마", "제안(승인 전)"))
        self.assertEqual([field["name"] for field in view["fields"]], ["priority", "excluded_keywords", "priority_keywords", "allowed_channels", "reason"], "공통 씨앗만 허용 채널 칸이 있다")
        info = {row["label"]: row["value"] for row in view["info"]}
        self.assertEqual((info[T["seeds_info_scope"]], info[T["seeds_info_importance"]], info[T["seeds_info_channels"]]), ("공통", "일반", "네이버 A, 네이버 B"))
        self.assertIn(T["seeds_stateline_proposed"], view["notes"])
        controller.open_detail("EX001")
        self.assertEqual([field["name"] for field in controller.drawer_view()["fields"]], ["priority", "excluded_keywords", "priority_keywords", "reason"])
        info = {row["label"]: row["value"] for row in controller.drawer_view()["info"]}
        self.assertEqual(info[T["seeds_info_channels"]], "네이버 A 한 곳")

    def test_a_row_with_unsaved_changes_says_so_in_its_accessible_name_and_loses_it_when_the_value_is_put_back(self):
        """독립 검증 L5(변이 Q16 생존) — 줄 접근 이름에 '저장 전 변경이 있어요' 가 붙고 저장된 값으로 돌아가면 사라진다(뷰모델 — Qt 줄은 고치는 동안 다시 그리지 않고 다음에 그릴 때 이 이름을 받는다)."""
        controller = new_controller()
        controller.open_detail("EX001")

        def row():
            return next(item for item in controller.view()["list"]["rows"] if item["id"] == "EX001")

        clean = row()["a11y"]
        self.assertNotIn("저장 전 변경이 있어요", clean)
        controller.edit("reason", "새 이유")
        self.assertEqual(row()["a11y"], T["seeds_row_a11y_unsaved"].format(base=clean))
        self.assertTrue(row()["unsaved"])
        controller.edit("reason", "예시 이유 한 줄")
        self.assertEqual(row()["a11y"], clean, "저장된 값으로 돌아가면 표시도 사라진다")
        self.assertFalse(row()["unsaved"])

    def test_a_seasonal_seed_shows_its_schedule_but_has_no_field_to_change_it(self):
        controller = new_controller()
        controller.open_detail("EX012")
        view = controller.drawer_view()
        rows = {row["label"]: row["value"] for row in view["schedule"]["rows"]}
        self.assertEqual((rows[T["seeds_sched_prepare"]], rows[T["seeds_sched_publish"]], rows[T["seeds_sched_peak"]], rows[T["seeds_sched_repeat"]]),
                         ("12월 5일", "12월 20일 부터 1월 20일 까지", "12월 28일 부터 1월 10일 까지", "매년"))
        self.assertIn(rows[T["seeds_sched_state"]], wording.SEASONAL_STATE_KO.values())
        self.assertEqual(view["schedule"]["note"], T["seeds_sched_note"])
        names = [field["name"] for field in view["fields"]]
        for hidden in ("prepare_from", "publish_from", "publish_until", "peak_period", "recurrence", "seed_type", "state"):
            self.assertNotIn(hidden, names)
        self.assertFalse(controller.edit("prepare_from", "01-01"), "일정 칸은 고칠 수 없다")
        self.assertIsNone(new_controller().open_detail("EX001") and None)
        controller.open_detail("EX001")
        self.assertIsNone(controller.drawer_view()["schedule"])

    def test_the_idle_suggestion_is_a_sentence_in_the_detail_and_nothing_changes_until_the_user_rests_it(self):
        controller = new_controller()
        controller.open_detail("EX009")
        view = controller.drawer_view()
        self.assertTrue(view["idle"])
        self.assertIn(T["seeds_idle_note"].format(days=215), view["notes"])
        self.assertEqual(states(controller)["EX009"], "active")
        self.assertEqual(drive(controller, partial(controller.start_state, "rest"))[1], "ok")
        self.assertEqual(states(controller)["EX009"], "inactive")

    def test_editing_marks_a_change_and_going_back_to_the_saved_value_clears_it(self):
        controller = new_controller()
        controller.open_detail("EX001")
        seed = controller.open_seed()
        self.assertFalse(controller.is_dirty("EX001"))
        self.assertTrue(controller.edit("priority", True))
        self.assertTrue(controller.is_dirty("EX001"))
        self.assertEqual(controller.dirty_names(seed), ("priority",))
        self.assertTrue(controller.edit("priority", False))
        self.assertFalse(controller.is_dirty("EX001"))
        self.assertEqual(controller.drafts, {})
        self.assertTrue(controller.edit("reason", "  예시 이유 한 줄  "))
        self.assertFalse(controller.is_dirty("EX001"), "앞뒤 공백만 바꾼 것은 바뀐 것이 아니다")
        self.assertFalse(controller.edit("state", "active"))
        self.assertFalse(controller.edit("allowed_channels", ("naver_b",)), "채널 전용 씨앗에는 그 칸이 없다")

    def test_the_errors_beside_a_field_show_only_after_touching_it_or_a_save_try(self):
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("reason", "가" * 300)
        controller.edit("excluded_keywords", "같음, 같음")
        shown = {field["name"]: field["error"] for field in controller.drawer_view()["fields"]}
        self.assertIn("200", shown["reason"])
        self.assertEqual(shown["excluded_keywords"], T["bf_err_duplicate"])
        self.assertEqual(shown["priority_keywords"], "", "고치지 않은 칸은 조용하다")
        controller.revert()
        controller.open_detail("EX001")
        controller.edit("priority_keywords", "겹침")
        controller.edit("excluded_keywords", "겹침")
        self.assertEqual({field["name"]: field["error"] for field in controller.drawer_view()["fields"]}["priority_keywords"], T["sf_err_overlap"])

    def test_a_save_with_a_wrong_value_never_calls_the_provider_and_names_the_fields(self):
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("reason", "가" * 300)
        calls = list(controller.provider.calls)
        status, problems = controller.start_save()
        self.assertEqual((status, set(problems)), ("invalid", {"reason"}))
        self.assertEqual(controller.provider.calls, calls)
        self.assertEqual(controller.notice, ("error", T["seeds_save_invalid"]))
        view = controller.drawer_view()
        self.assertIn("200", {field["name"]: field["error"] for field in view["fields"]}["reason"], "저장을 시도한 뒤에는 모든 칸의 오류를 보인다")
        self.assertEqual(drive(controller, controller.start_save)[0], "invalid")

    def test_a_good_save_writes_once_clears_only_that_seeds_draft_and_says_so(self):
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("priority", True)
        controller.edit("excluded_keywords", "예시 제외, 예시 제외 둘")
        controller.open_detail("EX002")
        controller.edit("reason", "다른 씨앗의 초안")
        controller.open_detail("EX001")
        status, outcome, reload = drive(controller, controller.start_save)
        self.assertEqual((status, outcome, reload), ("started", "ok", False))
        seed = controller.by_id()["EX001"]
        self.assertEqual((seed.priority, seed.excluded_keywords, seed.state), (True, ("예시 제외", "예시 제외 둘"), "proposed"), "상태는 그대로")
        self.assertEqual(controller.notice, ("ok", T["seeds_saved"]))
        self.assertNotIn("EX001", controller.drafts)
        self.assertIn("EX002", controller.drafts, "다른 씨앗의 초안은 남는다")
        self.assertEqual(drive(controller, controller.start_save)[0], "nothing")

    def test_a_failed_save_keeps_every_typed_value_for_every_kind_of_failure(self):
        for kind, fail in (("io", seeds.SeedFailure(T["seeds_fail_io"], code="FILE_WRITE_FAILED", kind="io")), ("disk", seeds.SeedFailure(T["seeds_fail_disk"], code="DISK_FULL", kind="disk")),
                           ("busy", seeds.SeedFailure(T["seeds_fail_busy"], code="TOPIC_STORE_LOCKED", kind="busy")), ("other", seeds.SeedFailure(T["seeds_fail_other"], code="X", kind="other")),
                           ("invalid", seeds.SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid", problems={"reason": "invalid"}))):
            with self.subTest(kind=kind):
                controller = seeds_view.SeedsController(Failing({"edit_seed": fail}), jobs.JobRunner())
                load(controller)
                controller.open_detail("EX001")
                controller.edit("priority", True)
                controller.edit("reason", "고친 이유")
                status, outcome, reload = drive(controller, controller.start_save)
                self.assertEqual((status, outcome, reload), ("started", "failed", False))
                self.assertEqual(controller.values(controller.open_seed())["reason"], "고친 이유", "입력은 그대로다")
                self.assertTrue(controller.is_dirty("EX001"))
                self.assertEqual(controller.notice, ("error", T[seeds_view.FAILURE_TEXT[kind]]))
                self.assertNotRegex(controller.notice[1], r"FILE_WRITE_FAILED|DISK_FULL|TOPIC_STORE_LOCKED|Traceback")
        shown = {field["name"]: field["error"] for field in controller.drawer_view()["fields"]}
        self.assertTrue(shown["reason"], "서비스가 알려 준 칸 문제는 칸 옆에 문장으로 보인다")

    def test_a_stale_version_asks_for_a_reload_keeps_the_input_and_the_reload_says_so(self):
        controller = seeds_view.SeedsController(Failing({"edit_seed": seeds.SeedFailure(T["seeds_fail_conflict"], code="STORE_CONFLICT", kind="conflict")}), jobs.JobRunner())
        load(controller)
        controller.open_detail("EX001")
        controller.edit("priority", True)
        status, outcome, reload = drive(controller, controller.start_save)
        self.assertEqual((outcome, reload), ("failed", True))
        self.assertTrue(controller.is_dirty("EX001"))
        self.assertTrue(controller.reload_after_conflict)
        load(controller)
        self.assertEqual(controller.notice, ("warning", T["seeds_stale_reloaded"]))
        self.assertTrue(controller.is_dirty("EX001"), "다시 읽어도 입력은 그대로")

    # ---- 독립 검증 F1(P4b 와 같은 모양) — 초안은 '고친 칸' 만 들고, 안 고친 칸은 늘 저장된 최신 값을 따른다 ----
    @staticmethod
    def change_outside(controller, seed_id, **fields):
        """다른 창·손 편집이 파일을 먼저 바꾼 것을 흉내 낸다 — 가짜 공급자의 씨앗 값과 판을 바깥에서 바꾼다(화면은 아직 모른다)."""
        provider = controller.provider
        provider.seeds = [dataclasses.replace(item, **fields) if item.seed_id == seed_id else item for item in provider.seeds]
        provider.revision += 1

    def test_the_draft_holds_only_the_edited_fields_and_drops_a_field_that_went_back_to_the_saved_value(self):
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("priority", True)
        controller.edit("reason", "고친 이유")
        self.assertEqual(controller.drafts, {"EX001": {"priority": True, "reason": "고친 이유"}}, "초안에는 고친 칸만 있다(저장된 값 전체를 복사해 두지 않는다)")
        controller.edit("priority", False)
        self.assertEqual(controller.drafts, {"EX001": {"reason": "고친 이유"}}, "저장된 값과 같아진 칸은 초안에서 빠진다")
        controller.edit("reason", "  예시 이유 한 줄  ")
        self.assertEqual(controller.drafts, {}, "고친 칸이 모두 빠지면 그 씨앗의 초안이 비워진다(앞뒤 공백만 다른 것은 같은 값이다)")
        self.assertEqual(controller.values(controller.open_seed()), sf.raw_from_seed(controller.open_seed()))

    def test_unedited_fields_follow_the_latest_saved_value_so_a_reload_never_reverts_another_windows_change(self):
        """F1 — 다른 창이 바꾼 '고치지 않은 칸' 은 다시 읽은 뒤에도 최신 값이 보이고, 저장해도 낡은 값으로 되돌아가지 않는다."""
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("priority", True)
        controller.edit("reason", "고친 이유")
        self.change_outside(controller, "EX001", excluded_keywords=("다른 창 제외",))
        load(controller)                                                                   # 화면이 최신 내용을 다시 읽는다
        seed = controller.open_seed()
        values = controller.values(seed)
        self.assertEqual((values["excluded_keywords"], values["priority"], values["reason"]), ("다른 창 제외", True, "고친 이유"))
        self.assertEqual(set(controller.dirty_names(seed)), {"priority", "reason"}, "'저장 전 변경' 에 안 고친 제외 키워드가 끼지 않는다")
        fields = {field["name"]: field for field in controller.drawer_view()["fields"]}
        self.assertEqual((fields["excluded_keywords"]["value"], fields["excluded_keywords"]["changed"], fields["reason"]["changed"], fields["priority"]["changed"]), ("다른 창 제외", False, True, True),
                         "화면 칸도 최신 값이고 고친 칸만 '바뀜' 표시다")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        saved = controller.by_id()["EX001"]
        self.assertEqual((saved.excluded_keywords, saved.priority, saved.reason), (("다른 창 제외",), True, "고친 이유"), "저장해도 다른 창의 변경이 낡은 값으로 되돌아가지 않는다")
        self.assertEqual(next(item for item in controller.provider.seeds if item.seed_id == "EX001").excluded_keywords, ("다른 창 제외",), "공급자(파일) 쪽도 마찬가지")

    def test_the_stale_version_path_keeps_the_other_windows_change_on_unedited_fields_and_the_typed_value_on_edited_ones(self):
        """F1 의 낡은 판 길 — 저장 거절 → 다시 읽기 → 확인 뒤 저장: 안 고친 칸은 최신 값, 고친 칸은 사용자가 친 값(둘 다 바꾼 칸도 사용자가 정한다)."""
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("reason", "고친 이유")
        self.change_outside(controller, "EX001", excluded_keywords=("다른 창 제외",), priority_keywords=("다른 창 우선",), reason="다른 창 이유")
        status, outcome, reload = drive(controller, controller.start_save)
        self.assertEqual((status, outcome, reload), ("started", "failed", True), "낡은 판이라 저장은 거절되고 다시 읽어야 한다")
        self.assertEqual(controller.notice, ("error", T["seeds_fail_conflict"]))
        self.assertEqual(controller.values(controller.open_seed())["reason"], "고친 이유", "거절돼도 입력은 그대로")
        load(controller)
        self.assertEqual(controller.notice, ("warning", T["seeds_stale_reloaded"]))
        seed = controller.open_seed()
        values = controller.values(seed)
        self.assertEqual((values["excluded_keywords"], values["priority_keywords"], values["reason"]), ("다른 창 제외", "다른 창 우선", "고친 이유"))
        self.assertEqual(controller.dirty_names(seed), ("reason",), "고친 칸만 바뀐 것이다")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False), "확인한 뒤 다시 저장하면 저장된다")
        saved = controller.by_id()["EX001"]
        self.assertEqual((saved.reason, saved.excluded_keywords, saved.priority_keywords), ("고친 이유", ("다른 창 제외",), ("다른 창 우선",)))

    def test_a_field_another_window_saved_with_the_same_value_stops_being_a_change_after_a_reload(self):
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("reason", "같은 이유")
        self.change_outside(controller, "EX001", reason="같은 이유")
        load(controller)
        self.assertFalse(controller.is_dirty("EX001"), "다른 창이 같은 값으로 저장했으니 더 바뀐 것이 없다")
        self.assertEqual(controller.start_save(), ("nothing", None))
        self.assertEqual(controller.values(controller.open_seed())["reason"], "같은 이유")
        self.assertNotIn("EX001", controller.drafts, "같아진 칸은 초안에서도 뺀다")
        self.change_outside(controller, "EX001", reason="세 번째 이유")                    # 그 칸을 다른 창이 또 바꿨다 — 옛 입력이 최신 값을 덮으면 안 된다
        load(controller)
        self.assertEqual(controller.values(controller.open_seed())["reason"], "세 번째 이유")
        self.assertFalse(controller.is_dirty("EX001"))

    def test_the_channel_chips_follow_the_same_rule_the_edited_chips_stay_and_the_other_windows_other_field_shows(self):
        controller = new_controller()
        controller.open_detail("EX011")                                                    # 공통 Seed — 허용 채널 칸이 있다
        self.assertTrue(controller.toggle_channel("github_pages"))
        self.assertEqual(set(controller.drafts["EX011"]), {"allowed_channels"})
        self.change_outside(controller, "EX011", reason="다른 창 이유")
        load(controller)
        seed = controller.open_seed()
        values = controller.values(seed)
        self.assertEqual((set(values["allowed_channels"]), values["reason"]), ({"naver_a", "naver_b", "github_pages"}, "다른 창 이유"))
        self.assertEqual(controller.dirty_names(seed), ("allowed_channels",))
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        saved = controller.by_id()["EX011"]
        self.assertEqual((set(saved.allowed_channels), saved.reason), ({"naver_a", "naver_b", "github_pages"}, "다른 창 이유"))

    def test_a_draft_for_a_field_that_can_no_longer_be_edited_is_dropped_at_the_reload(self):
        controller = new_controller()
        controller.open_detail("EX011")
        controller.toggle_channel("github_pages")
        controller.edit("reason", "고친 이유")
        self.change_outside(controller, "EX011", scope="naver_a", allowed_channels=("naver_a",))        # 손 편집으로 공통 Seed 가 한 채널 전용이 됐다 — 허용 채널 칸이 없어진다
        load(controller)
        self.assertEqual(controller.drafts, {"EX011": {"reason": "고친 이유"}}, "더는 없는 칸의 초안은 버리고 남은 고친 칸만 둔다")
        self.assertEqual(controller.dirty_names(controller.open_seed()), ("reason",))

    def test_closing_the_drawer_and_opening_it_again_keeps_the_draft_and_revert_throws_it_away(self):
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("priority", True)
        self.assertEqual(controller.close_drawer(), ("seed", "EX001"))
        self.assertIsNone(controller.drawer_view())
        self.assertTrue(controller.view()["list"]["rows"][0]["unsaved"], "목록 줄에 '저장 전 변경' 이 보인다")
        controller.open_detail("EX001")
        self.assertTrue(controller.drawer_view()["dirty"])
        self.assertTrue(controller.revert())
        self.assertFalse(controller.is_dirty("EX001"))


class StateActionsTest(unittest.TestCase):
    def test_each_state_offers_its_own_primary_action_and_only_transitions_the_service_allows(self):
        controller = new_controller()
        expected = {"EX001": ("approve", ["approve", "rest", "save", "revert"], ["primary", "secondary", "secondary", "tertiary"]),
                    "EX009": ("save", ["save", "rest", "revert"], ["primary", "secondary", "tertiary"]),
                    "EX014": ("resume", ["resume", "save", "revert"], ["primary", "secondary", "tertiary"])}
        for seed_id, (primary, keys, kinds) in expected.items():
            controller.open_detail(seed_id)
            actions = controller.drawer_view()["actions"]
            self.assertEqual(([item["key"] for item in actions], [item["kind"] for item in actions]), (keys, kinds), seed_id)
            self.assertEqual(next(item["key"] for item in actions if item["kind"] == "primary"), primary)
        controller.open_detail("EX009")
        self.assertEqual(controller.start_state("approve")[0], "unavailable", "사용 중인 씨앗은 승인하지 않는다")
        self.assertEqual(controller.start_state("resume")[0], "unavailable")
        controller.open_detail("EX014")
        self.assertEqual((controller.start_state("approve")[0], controller.start_state("rest")[0]), ("unavailable", "unavailable"))
        self.assertEqual(controller.start_state("nope")[0], "unavailable")

    def test_approving_rested_and_resuming_change_only_that_seed_and_say_what_happened(self):
        controller = new_controller()
        before = states(controller)
        controller.open_detail("EX001")
        self.assertEqual(drive(controller, partial(controller.start_state, "approve"))[1], "ok")
        self.assertEqual(controller.notice, ("ok", T["seeds_approved"]))
        self.assertEqual(controller.by_id()["EX001"].active_since, DAY)
        self.assertEqual({key: value for key, value in states(controller).items() if before[key] != value}, {"EX001": "active"}, "그 씨앗 하나만 바뀐다")
        self.assertEqual(drive(controller, partial(controller.start_state, "rest"))[1], "ok")
        self.assertEqual((states(controller)["EX001"], controller.notice), ("inactive", ("ok", T["seeds_rested"])))
        self.assertEqual(drive(controller, partial(controller.start_state, "resume"))[1], "ok")
        self.assertEqual((states(controller)["EX001"], controller.notice), ("active", ("ok", T["seeds_resumed"])))

    def test_a_proposed_seed_can_be_left_resting_without_approving_it(self):
        controller = new_controller()
        controller.open_detail("EX003")
        drive(controller, partial(controller.start_state, "rest"))
        self.assertEqual(states(controller)["EX003"], "inactive")
        self.assertNotEqual(states(controller)["EX003"], "active")

    def test_unsaved_changes_turn_the_state_buttons_off_with_the_reason_and_the_provider_is_not_called(self):
        controller = new_controller()
        controller.open_detail("EX001")
        controller.edit("priority", True)
        actions = {item["key"]: item for item in controller.drawer_view()["actions"]}
        for key in ("approve", "rest"):
            self.assertEqual((actions[key]["enabled"], actions[key]["reason"]), (False, T["seeds_act_unsaved"]))
        self.assertEqual((actions["save"]["enabled"], actions["revert"]["enabled"]), (True, True))
        calls = list(controller.provider.calls)
        self.assertEqual(controller.start_state("approve")[0], "unsaved")
        self.assertEqual(controller.provider.calls, calls)

    def test_the_busy_writes_refuse_a_second_one_and_turn_the_buttons_off(self):
        provider = Gated()
        controller = seeds_view.SeedsController(provider, jobs.JobRunner())
        load(controller)
        controller.open_detail("EX001")
        status, job = controller.start_state("approve")
        self.assertEqual(status, "started")
        self.assertTrue(controller.busy)
        self.assertEqual((controller.start_state("rest")[0], controller.start_save()[0], controller.start_load()), ("busy", "busy", None))
        self.assertFalse(controller.toggle_check("EX002"))
        self.assertFalse(controller.edit("priority", True))
        self.assertTrue(all(not item["enabled"] for item in controller.drawer_view()["actions"]))
        self.assertTrue(all(not item["enabled"] for item in controller.view()["bulk"]["actions"]))
        provider.gate.set()
        job.join(10)
        self.assertFalse(controller.busy)


class BulkTest(unittest.TestCase):
    def picked(self, *ids):
        controller = new_controller()
        for seed_id in ids:
            controller.toggle_check(seed_id)
        return controller

    def test_the_bulk_buttons_count_what_each_can_change_and_say_why_when_they_cannot(self):
        controller = new_controller()
        self.assertEqual([(item["enabled"], item["reason"]) for item in controller.view()["bulk"]["actions"]], [(False, T["seeds_bulk_no_pick"])] * 2)
        controller.toggle_check("EX009")
        actions = {item["key"]: item for item in controller.view()["bulk"]["actions"]}
        self.assertEqual((actions["activate"]["enabled"], actions["activate"]["reason"]), (False, T["seeds_bulk_no_target"]), "이미 사용 중인 것만 골랐다")
        self.assertTrue(actions["rest"]["enabled"])
        controller.toggle_check("EX001")
        actions = {item["key"]: item for item in controller.view()["bulk"]["actions"]}
        self.assertEqual((actions["activate"]["text"], actions["rest"]["text"]), ("사용 중으로 바꾸기 1", "쉬게 하기 2"))
        self.assertEqual(controller.view()["bulk"]["text"], "2개 골랐어요")

    def test_without_the_confirmation_dialog_nothing_is_written_not_even_by_calling_start_bulk_directly(self):
        controller = self.picked("EX001", "EX002")
        calls = list(controller.provider.calls)
        self.assertEqual(controller.start_bulk("activate")[0], "unconfirmed")
        self.assertEqual(controller.provider.calls, calls)
        self.assertEqual({states(controller)[key] for key in ("EX001", "EX002")}, {"proposed"})

    def test_the_dialog_says_the_count_the_first_names_what_changes_and_that_it_can_be_undone(self):
        controller = self.picked("EX001", "EX002", "EX003", "EX004", "EX005", "EX006", "EX009")
        dialog = controller.bulk_dialog("activate")
        self.assertEqual(dialog["title"], "고른 Seed 6개를 바꿀까요?")
        body = dialog["body"]
        self.assertIn("승인 전 6개를 사용 중으로 바꿉니다.", body)
        self.assertIn("처음 5개: ‘예시 낱말 가’, ‘예시 낱말 나’, ‘예시 낱말 다’, ‘예시 낱말 라’, ‘예시 낱말 마’ 외 1개", body)
        self.assertIn(T["seeds_bulk_effect_activate"], body)
        self.assertIn("나중에 쉬는 중으로 되돌릴 수 있어요", body, "되돌릴 수 있음을 사실대로")
        self.assertIn(T["seeds_bulk_count_row"].format(name="네이버 A", before=3, after=7), body, "바꾸기 전과 뒤의 채널별 쓸 수 있는 수")
        self.assertIn("고른 것 중 1개는 이 일로 바뀌지 않아요", body)
        self.assertIn(T["seeds_bulk_all_or_nothing"], body)
        self.assertEqual((dialog["ok"], dialog["cancel"]), ("사용 중으로 바꾸기", "취소"))
        rest = self.picked("EX009", "EX001", "EX014").bulk_dialog("rest")
        self.assertIn("승인 전 1개, 사용 중 1개를 쉬는 중으로 바꿉니다.", rest["body"])
        self.assertIn(T["seeds_bulk_effect_rest"], rest["body"])
        self.assertIsNone(new_controller().bulk_dialog("activate"), "고른 것이 없으면 확인창도 없다")
        self.assertIsNone(self.picked("EX009").bulk_dialog("activate"), "바꿀 것이 없으면 확인창도 없다")

    def test_after_the_dialog_the_confirmed_change_writes_exactly_the_shown_seeds_all_at_once(self):
        controller = self.picked("EX001", "EX002", "EX014")
        controller.bulk_dialog("activate")
        status, outcome, _reload = drive(controller, partial(controller.start_bulk, "activate"))
        self.assertEqual((status, outcome), ("started", "ok"))
        self.assertEqual([states(controller)[key] for key in ("EX001", "EX002", "EX014")], ["active"] * 3)
        self.assertEqual(controller.notice, ("ok", T["seeds_bulk_done_activate"].format(n=3)))
        self.assertEqual(controller.checked, set(), "바꾼 씨앗의 고름은 풀린다")
        self.assertEqual(controller.provider.calls.count("set_states"), 1, "한 번의 쓰기")
        self.assertEqual(controller.start_bulk("activate")[0], "nothing", "확인창은 한 번 쓰이면 사라진다")

    def test_the_confirmation_is_void_when_the_selection_changed_after_the_dialog_or_the_dialog_belonged_to_another_kind(self):
        controller = self.picked("EX001", "EX002")
        controller.bulk_dialog("activate")
        controller.toggle_check("EX003")
        self.assertEqual(controller.start_bulk("activate")[0], "unconfirmed", "확인창이 보인 것과 다른 씨앗들이다")
        controller = self.picked("EX001", "EX002")
        controller.bulk_dialog("activate")
        self.assertEqual(controller.start_bulk("rest")[0], "unconfirmed")

    def test_closing_the_dialog_without_confirming_takes_the_shown_mark_back_so_the_same_change_can_no_longer_start(self):
        """취소·Esc 로 닫은 확인창은 '보였다' 는 표시도 거둔다 — 그 뒤 같은 종류·같은 씨앗으로 `start_bulk` 를 불러도 쓰지 않는다."""
        controller = self.picked("EX001", "EX002")
        calls = list(controller.provider.calls)
        controller.bulk_dialog("activate")
        self.assertEqual(controller.bulk_asked, ("activate", ("EX001", "EX002")))
        controller.discard_bulk()
        self.assertIsNone(controller.bulk_asked)
        self.assertEqual(controller.start_bulk("activate")[0], "unconfirmed")
        self.assertEqual(controller.provider.calls, calls)
        self.assertEqual({states(controller)[key] for key in ("EX001", "EX002")}, {"proposed"})
        controller.bulk_dialog("activate")                                                  # 다시 확인창을 보이면 다시 쓸 수 있다
        self.assertEqual(drive(controller, partial(controller.start_bulk, "activate"))[1], "ok")

    def test_a_failed_bulk_change_changes_nothing_and_keeps_the_selection(self):
        controller = seeds_view.SeedsController(Failing({"set_states": seeds.SeedFailure(T["seeds_fail_io"], code="FILE_WRITE_FAILED", kind="io")}), jobs.JobRunner())
        load(controller)
        for seed_id in ("EX001", "EX002"):
            controller.toggle_check(seed_id)
        controller.bulk_dialog("activate")
        self.assertEqual(drive(controller, partial(controller.start_bulk, "activate"))[1], "failed")
        self.assertEqual({states(controller)[key] for key in ("EX001", "EX002")}, {"proposed"})
        self.assertEqual(controller.checked, {"EX001", "EX002"})
        self.assertEqual(controller.notice, ("error", T["seeds_fail_io"]))

    def test_the_fake_provider_never_applies_a_bulk_change_in_part(self):
        provider = seeds.FakeSeedsProvider()
        data = provider.load_seeds(SAFE, NEVER)
        before = {seed.seed_id: seed for seed in provider.seeds}
        with self.assertRaises(seeds.SeedFailure):
            provider.set_states(("EX001", "EX009", "EX002"), "active", data.version, SAFE, NEVER)               # 가운데 EX009 는 이미 사용 중이라 바꿀 수 없다
        self.assertEqual({seed.seed_id: seed for seed in provider.seeds}, before, "앞의 EX001 도 안 바뀌었다")
        with self.assertRaises(seeds.SeedFailure):
            provider.set_states(("EX001", "nope"), "active", data.version, SAFE, NEVER)
        self.assertEqual({seed.seed_id: seed for seed in provider.seeds}, before)


class CreateTest(unittest.TestCase):
    def fill(self, controller, **values):
        controller.open_new()
        for name, value in values.items():
            controller.edit(name, value)

    def good(self, **more):
        return {"keyword": "예시 새 낱말", "major": "예시 대분류", "minor": "예시 중분류", "target_type": "product", "scope": "naver_a", **more}

    def test_the_new_form_starts_with_only_the_importance_chosen_and_asks_for_the_scope_and_the_target_type(self):
        controller = new_controller()
        controller.open_new()
        view = controller.drawer_view()
        self.assertEqual((view["kind"], view["title"], view["status"]), ("new", T["seeds_new_title"], None))
        values = {field["name"]: field["value"] for field in view["fields"]}
        self.assertEqual((values["seed_type"], values["scope"], values["target_type"]), ("general", "", ""))
        self.assertEqual([item["key"] for item in view["actions"]], ["create", "cancel"])
        self.assertEqual(next(item["text"] for item in view["actions"] if item["key"] == "create"), "승인 전으로 등록", "등록한 Seed 는 늘 승인 전이라고 단추가 말한다")
        self.assertIn(T["seeds_new_note"], view["notes"])
        options = {field["name"]: [item["label"] for item in field["options"]] for field in view["fields"] if field["options"]}
        self.assertEqual(options["seed_type"], ["일반", "우선", "실시간", "협찬 가능"], "계절형은 없다")
        self.assertEqual(options["scope"][0], "공통")
        self.assertEqual(len(options["target_type"]), 11)

    def test_changing_the_scope_or_the_importance_changes_the_field_list_and_typing_does_not(self):
        controller = new_controller()
        controller.open_new()
        self.assertEqual(controller.edit("keyword", "예시"), True)
        self.assertEqual(controller.edit("scope", "common"), "structural")
        self.assertEqual(controller.edit("scope", "common"), True, "같은 값이면 구성이 안 바뀐다")
        self.assertEqual(controller.edit("seed_type", "sponsorable"), "structural")
        self.assertIn("sponsor_tag", [field["name"] for field in controller.drawer_view()["fields"]])
        self.assertEqual(controller.edit("seed_type", "general"), "structural")
        self.assertEqual(controller.toggle_channel("naver_b"), True)
        self.assertEqual(controller.new_values["allowed_channels"], ("naver_b",))

    def test_a_save_try_with_wrong_values_names_every_field_and_never_calls_the_provider(self):
        controller = new_controller()
        controller.open_new()
        calls = list(controller.provider.calls)
        status, problems = controller.start_create()
        self.assertEqual(status, "invalid")
        self.assertEqual(set(problems), {"keyword", "major", "minor", "target_type", "scope"})
        self.assertEqual(controller.provider.calls, calls)
        shown = {field["name"]: field["error"] for field in controller.drawer_view()["fields"]}
        self.assertTrue(all(shown[name] for name in problems), "시도한 뒤에는 모든 칸의 오류가 보인다")
        controller.edit("scope", "common")
        self.assertEqual(set(controller.start_create()[1]), {"keyword", "major", "minor", "target_type", "allowed_channels"})

    def test_a_good_registration_is_always_proposed_gets_a_number_and_opens_its_detail(self):
        controller = new_controller()
        self.fill(controller, **self.good())
        status, outcome, _reload = drive(controller, controller.start_create)
        self.assertEqual((status, outcome), ("started", "ok"))
        seed = controller.by_id()["M001"]
        self.assertEqual((seed.state, seed.keyword, seed.scope, seed.active_since, seed.last_selected_on, seed.priority), ("proposed", "예시 새 낱말", "naver_a", None, None, False))
        self.assertEqual(controller.drawer, ("seed", "M001"))
        self.assertEqual(controller.notice, ("ok", T["seeds_created"]))
        self.assertIsNone(controller.new_values)
        self.assertEqual(controller.drawer_view()["status"]["text"], "제안(승인 전)")
        self.fill(controller, **self.good(keyword="예시 둘째 낱말", seed_type="priority"))
        drive(controller, controller.start_create)
        self.assertEqual((controller.by_id()["M002"].state, controller.by_id()["M002"].priority), ("proposed", True))

    def test_a_common_registration_keeps_the_chosen_channels_and_a_sponsorable_one_needs_its_tag(self):
        controller = new_controller()
        self.fill(controller, **self.good(scope="common", seed_type="sponsorable"))
        controller.toggle_channel("naver_a")
        controller.toggle_channel("naver_b")
        self.assertEqual(controller.start_create()[1], {"sponsor_tag": "tag_needed"})
        controller.edit("sponsor_tag", "pc_parts")
        self.assertEqual(drive(controller, controller.start_create)[1], "ok")
        seed = controller.by_id()["M001"]
        self.assertEqual((seed.allowed_channels, seed.sponsor_tag, seed.seed_type, seed.state), (("naver_a", "naver_b"), "pc_parts", "sponsorable", "proposed"))

    def test_the_same_word_in_the_same_scope_is_refused_before_the_provider_is_called(self):
        controller = new_controller()
        self.fill(controller, **self.good(keyword="예시 낱말 가"))
        calls = list(controller.provider.calls)
        status, problems = controller.start_create()
        self.assertEqual((status, problems), ("invalid", {"keyword": "same_word"}))
        self.assertEqual(controller.provider.calls, calls)
        self.assertEqual({field["name"]: field["error"] for field in controller.drawer_view()["fields"]}["keyword"], T["sf_err_same_word"])

    def test_a_service_refusal_names_the_field_keeps_the_input_and_the_form_stays_open(self):
        fail = seeds.SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid", problems={"keyword": "duplicate"})
        controller = seeds_view.SeedsController(Failing({"create_seed": fail}), jobs.JobRunner())
        load(controller)
        self.fill(controller, **self.good())
        status, outcome, _reload = drive(controller, controller.start_create)
        self.assertEqual((status, outcome), ("started", "failed"))
        self.assertEqual(controller.drawer, ("new", None))
        self.assertEqual(controller.new_values["keyword"], "예시 새 낱말", "입력은 그대로")
        self.assertTrue({field["name"]: field["error"] for field in controller.drawer_view()["fields"]}["keyword"])

    def test_closing_the_new_form_keeps_what_was_typed_for_next_time(self):
        controller = new_controller()
        self.fill(controller, keyword="쓰던 낱말")
        controller.close_drawer()
        controller.open_new()
        self.assertEqual(controller.new_values["keyword"], "쓰던 낱말")


class ImportTest(unittest.TestCase):
    def preview(self, mode="ok"):
        controller = seeds_view.SeedsController(seeds.FakeSeedsProvider(import_mode=mode), jobs.JobRunner())
        load(controller)
        status, outcome, _reload = drive(controller, partial(controller.start_import_preview, "가짜 파일 위치"))
        return controller, status, outcome

    def test_the_preview_reads_only_and_the_dialog_says_the_counts_the_proposed_state_and_the_channels(self):
        controller, status, outcome = self.preview()
        self.assertEqual((status, outcome), ("started", "ok"))
        self.assertEqual(controller.provider.calls.count("apply_import"), 0)
        dialog = controller.import_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"], dialog["can_apply"]), (T["seeds_imp_title"], T["seeds_imp_ok"], T["seeds_imp_cancel"], True))
        self.assertIn("파일 안 Seed 4개 · 새로 등록할 Seed 3개 · 이미 있어 건너뜀 1개 · 읽을 수 없어 뺀 Seed 0개(지금 등록된 Seed 16개)", dialog["body"], "파일 안 개수 = 새로 + 건너뜀 + 읽을 수 없어 뺌")
        self.assertIn("‘EX001’ 같은 씨앗 번호가 이미 등록되어 있어 건너뜁니다(덮어쓰지 않습니다)", dialog["body"])
        self.assertIn("새로 등록하는 Seed 는 모두 승인 전이에요. 승인하기 전에는 후보 생성에 쓰이지 않아요.", dialog["body"])
        self.assertIn("네이버 A 2개(후보 생성 켜짐)", dialog["body"])
        self.assertIn("github_pages" if False else "GitHub Pages 0개(후보 생성 꺼짐)", dialog["body"])

    def test_without_the_dialog_nothing_is_registered_and_with_it_every_new_seed_is_proposed(self):
        controller, _status, _outcome = self.preview()
        self.assertEqual(controller.start_import_apply()[0], "unconfirmed")
        self.assertEqual(len(controller.seeds()), 16)
        controller.import_dialog()
        self.assertEqual(drive(controller, controller.start_import_apply)[1], "ok")
        self.assertEqual(len(controller.seeds()), 19)
        self.assertEqual({controller.by_id()[key].state for key in ("EXI001", "EXI002", "EXI003")}, {"proposed"})
        self.assertEqual((controller.status, controller.notice), ("proposed", ("ok", T["seeds_imported"].format(n=3))))
        self.assertIsNone(controller.import_info)
        self.assertEqual(controller.start_import_apply()[0], "nothing")

    def test_closing_the_import_dialog_without_confirming_forgets_the_preview_and_registers_nothing(self):
        controller, _status, _outcome = self.preview()
        controller.import_dialog()
        self.assertTrue(controller.import_asked)
        controller.discard_import()
        self.assertEqual((controller.import_info, controller.import_asked), (None, False))
        self.assertEqual(controller.start_import_apply()[0], "nothing")
        self.assertEqual((controller.provider.calls.count("apply_import"), len(controller.seeds())), (0, 16))

    def test_rejected_seeds_block_everything_and_the_dialog_only_offers_to_close(self):
        controller, _status, _outcome = self.preview("blocked")
        dialog = controller.import_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"], dialog["can_apply"]), (T["seeds_imp_title_blocked"], T["seeds_imp_close"], None, False))
        self.assertIn(T["seeds_imp_blocked"], dialog["body"])
        self.assertIn("‘EXI900’", dialog["body"])
        self.assertEqual(controller.start_import_apply()[0], "nothing")
        self.assertEqual(len(controller.seeds()), 16)

    def test_a_file_with_nothing_new_says_so_and_offers_to_close(self):
        controller, _status, _outcome = self.preview("none")
        dialog = controller.import_dialog()
        self.assertEqual((dialog["title"], dialog["can_apply"]), (T["seeds_imp_title_none"], False))
        self.assertEqual(controller.start_import_apply()[0], "nothing")

    def test_a_file_that_cannot_be_read_gives_an_easy_sentence_and_changes_nothing(self):
        controller, status, outcome = self.preview("unreadable")
        self.assertEqual((status, outcome), ("started", "failed"))
        self.assertEqual((controller.notice, controller.import_info), (("error", T["seeds_imp_failed"]), None))
        self.assertEqual(len(controller.seeds()), 16)

    def test_the_reasons_in_the_dialog_are_masked_cut_and_counted(self):
        controller, *_ = self.preview()
        many = tuple((f"EXI{n:03d}", "이유 " + KEY_SHAPED) for n in range(900, 910))
        controller.import_info = dataclasses.replace(controller.import_info, rejected=many)
        body = controller.import_dialog()["body"]
        self.assertNotIn(KEY_SHAPED, body)
        self.assertIn(T["seeds_imp_more"].format(n=5), body)

    def test_a_stale_version_at_apply_asks_for_a_reload_and_registers_nothing(self):
        controller = seeds_view.SeedsController(Failing({"apply_import": seeds.SeedFailure(T["seeds_fail_conflict"], code="STORE_CONFLICT", kind="conflict")}), jobs.JobRunner())
        load(controller)
        drive(controller, partial(controller.start_import_preview, "가짜"))
        controller.import_dialog()
        status, outcome, reload = drive(controller, controller.start_import_apply)
        self.assertEqual((outcome, reload, len(controller.seeds())), ("failed", True, 16))


# ---- 5) 읽기 전용 증명(진짜 어댑터·임시 폴더) -------------------------------------------------------------------------------------------------
class Real:
    """임시 데이터 폴더에 가짜 씨앗을 써 두고 진짜 어댑터로 컨트롤러를 만든다."""

    def __init__(self, test, items=None):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        test.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(tmp.name)
        self.paths = tf.topic_paths(self.ctx.workspace)
        self.factory = lambda data_dir=None: self.ctx
        self.provider = seeds_adapter.ServiceSeedsProvider(context_factory=self.factory)
        if items is not None:
            self.paths.folder.mkdir(parents=True, exist_ok=True)
            self.paths.seeds.write_bytes((__import__("json").dumps(sd.seeds_to_dict(items), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        self.controller = seeds_view.SeedsController(self.provider, jobs.JobRunner())

    def tree(self):
        return ss.tree_snapshot(self.tmp)


class ReadOnlyTest(unittest.TestCase):
    def test_opening_filtering_searching_selecting_opening_the_drawer_and_editing_do_not_touch_a_single_byte(self):
        real = Real(self, seeds.FakeSeedsProvider().seeds)
        before, listing = real.tree(), sorted(str(path) for path in real.tmp.rglob("*"))
        controller = real.controller
        load(controller)
        self.assertEqual(len(controller.seeds()), 16)
        controller.set_status("proposed")
        controller.set_scope("common")
        controller.set_importance("general")
        controller.set_query("낱말")
        controller.reset_filters()
        controller.toggle_more_filters()
        controller.select_found()
        controller.toggle_check("EX001")
        controller.clear_checks()
        for seed_id in ("EX001", "EX009", "EX012"):
            controller.open_detail(seed_id)
            controller.edit("priority", True)
            controller.edit("reason", "고쳐 본 이유")
            controller.drawer_view()
            controller.revert()
        controller.open_new()
        controller.edit("keyword", "예시 새 낱말")
        controller.edit("scope", "common")
        controller.toggle_channel("naver_a")
        controller.drawer_view()
        controller.view()
        controller.close_drawer()
        self.assertEqual(real.tree(), before)
        self.assertEqual(sorted(str(path) for path in real.tmp.rglob("*")), listing)

    def test_even_a_missing_data_folder_is_read_without_creating_anything(self):
        real = Real(self)
        before = sorted(str(path) for path in real.tmp.rglob("*"))
        load(real.controller)
        self.assertEqual((real.controller.state, real.controller.view()["banners"][0][0]), ("normal", "info"))
        self.assertEqual(real.controller.view()["list"]["empty"]["title"], T["seeds_empty_title"])
        self.assertEqual(sorted(str(path) for path in real.tmp.rglob("*")), before)
        self.assertFalse(real.paths.folder.exists())

    def test_a_broken_file_is_read_as_an_easy_error_and_never_touched_or_overwritten(self):
        real = Real(self)
        real.paths.folder.mkdir(parents=True)
        real.paths.seeds.write_bytes(b"{broken")
        before = real.tree()
        with self.assertRaises(seeds.SeedFailure) as caught:
            real.provider.load_seeds(SAFE, NEVER)
        self.assertEqual((caught.exception.kind, caught.exception.user_message), ("corrupt", T["seeds_error_desc"]))
        controller = real.controller
        controller.apply_load_failed(caught.exception)
        self.assertEqual(controller.state, "error")
        with self.assertRaises(seeds.SeedFailure):
            real.provider.set_state("EX001", "active", "x", SAFE, NEVER)
        self.assertEqual(real.tree(), before)

    def test_a_data_folder_that_is_missing_is_an_easy_sentence(self):
        provider = seeds_adapter.ServiceSeedsProvider(str(ROOT / "no-such-folder-for-seeds"))
        with self.assertRaises(seeds.SeedFailure) as caught:
            provider.load_seeds(SAFE, NEVER)
        self.assertEqual(caught.exception.user_message, T["data_dir_missing"])


class FakeEqualsServiceTest(unittest.TestCase):
    """같은 일을 가짜 공급자와 진짜 서비스(어댑터)에 해 보고 결과를 견준다."""

    def both(self):
        items = seeds.FakeSeedsProvider().seeds
        real = Real(self, items)
        real_controller = real.controller
        load(real_controller)
        fake = seeds.FakeSeedsProvider()
        fake_controller = seeds_view.SeedsController(fake, jobs.JobRunner())
        load(fake_controller)
        return real, real_controller, fake_controller

    @staticmethod
    def snapshot(controller):
        return [(seed.seed_id, seed.state, seed.active_since, seed.priority, seed.excluded_keywords, seed.priority_keywords, seed.allowed_channels, seed.reason, seed.registered_on) for seed in controller.seeds()]

    def test_the_same_steps_give_the_same_seeds_the_same_numbers_and_the_same_refusals(self):
        _real, real_controller, fake_controller = self.both()
        results = []
        for controller in (real_controller, fake_controller):
            log = []
            controller.open_detail("EX001")
            log.append(drive(controller, partial(controller.start_state, "approve"))[1])
            for seed_id in ("EX002", "EX003", "EX014"):
                controller.toggle_check(seed_id)
            controller.bulk_dialog("activate")
            log.append(drive(controller, partial(controller.start_bulk, "activate"))[1])
            controller.open_detail("EX005")
            controller.edit("priority", True)
            controller.edit("excluded_keywords", "예시 제외 하나")
            controller.edit("allowed_channels", ("naver_a",))
            log.append(drive(controller, controller.start_save)[1])
            controller.open_detail("EX001")
            controller.edit("priority_keywords", "겹침")
            controller.edit("excluded_keywords", "겹침")
            log.append(controller.start_save()[0])
            controller.revert()
            controller.open_new()
            for name, value in (("keyword", "예시 새 낱말"), ("major", "예시 대분류"), ("minor", "예시 중분류"), ("target_type", "product"), ("scope", "naver_a")):
                controller.edit(name, value)
            log.append(drive(controller, controller.start_create)[1])
            controller.open_new()
            for name, value in (("keyword", "예시 새 낱말"), ("major", "예시 대분류"), ("minor", "예시 중분류"), ("target_type", "product"), ("scope", "naver_a")):
                controller.edit(name, value)
            log.append(controller.start_create()[0])
            controller.open_detail("EX009")
            log.append(controller.start_state("approve")[0])
            results.append((log, self.snapshot(controller)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], ["ok", "ok", "ok", "invalid", "ok", "invalid", "unavailable"])

    def test_a_service_refusal_and_a_fake_refusal_name_the_same_fields(self):
        _real, real_controller, fake_controller = self.both()
        for controller in (real_controller, fake_controller):
            controller.open_detail("EX005")
            outcome = []
            calls = (partial(controller.provider.edit_seed, "EX005", {"priority_keywords": ("겹침",), "excluded_keywords": ("겹침",)}, controller.data.version, SAFE, NEVER),
                     partial(controller.provider.edit_seed, "EX005", {"reason": "가" * 300}, controller.data.version, SAFE, NEVER),
                     partial(controller.provider.create_seed, {"keyword": "예시 낱말 가", "major": "가", "minor": "나", "seed_type": "general", "target_type": "product", "scope": "naver_a"}, controller.data.version, SAFE, NEVER))
            for provider_call in calls:
                with self.assertRaises(seeds.SeedFailure) as caught:
                    provider_call()
                outcome.append((caught.exception.kind, sorted(caught.exception.problems.items())))
            if controller is real_controller:
                expected = outcome
            else:
                self.assertEqual(outcome, expected)
        self.assertEqual(expected[0][1], [("excluded_keywords", "invalid"), ("priority_keywords", "invalid")])
        self.assertEqual(expected[2][1], [("keyword", "duplicate")])

    def test_the_real_adapter_changes_only_the_seed_file_and_its_copy(self):
        real, controller, _fake = self.both()
        before = real.tree()
        controller.open_detail("EX001")
        drive(controller, partial(controller.start_state, "approve"))
        after = real.tree()
        changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
        self.assertEqual(changed, {"data/topic_engine/seeds.json", "data/topic_engine/seeds.json.bak"})

    def test_the_idle_suggestions_and_the_generation_flags_come_through_the_adapter(self):
        real, controller, fake_controller = self.both()
        self.assertEqual(controller.data.idle, fake_controller.data.idle)
        self.assertEqual(controller.data.idle_days(), {"EX009": 215})
        self.assertEqual(controller.data.generation, fake_controller.data.generation)
        self.assertFalse(controller.data.sample)
        self.assertTrue(fake_controller.data.sample)

    def test_a_real_import_preview_and_apply_register_everything_as_proposed_through_the_adapter(self):
        import json
        from test_topics_seeds_v2 import proposal, proposal_file
        real = Real(self, seeds.FakeSeedsProvider().seeds)
        controller = real.controller
        load(controller)
        source = real.tmp / "proposal.json"
        source.write_text(json.dumps(proposal_file(proposal(id="EXP01", keyword="예시 불러온 하나"), proposal(id="EXP02", keyword="예시 불러온 둘"), default_status="active"), ensure_ascii=False), encoding="utf-8")
        before = real.tree()
        status, outcome, _reload = drive(controller, lambda **cb: controller.start_import_preview(str(source), **cb))
        self.assertEqual((status, outcome), ("started", "ok"))
        self.assertEqual(real.tree(), before, "미리 보기는 아무것도 쓰지 않는다")
        self.assertEqual((controller.import_info.new_count, controller.import_info.blocked), (2, False))
        controller.import_dialog()
        self.assertEqual(drive(controller, controller.start_import_apply)[1], "ok")
        self.assertEqual({controller.by_id()[key].state for key in ("EXP01", "EXP02")}, {"proposed"})
        self.assertEqual(len(controller.seeds()), 18)
        missing = drive(controller, lambda **cb: controller.start_import_preview(str(real.tmp / "none.json"), **cb))
        self.assertEqual(missing[1], "failed")
        self.assertEqual(controller.notice, ("error", T["seeds_imp_failed"]))


# ---- 6) 문구·소스·실제 값 ------------------------------------------------------------------------------------------------------------------
class TextTest(unittest.TestCase):
    def test_every_seed_text_is_used_easy_and_free_of_promises_and_codes(self):
        used = "\n".join(path.read_text(encoding="utf-8") for path in UI_DIR.rglob("*.py") if path.name != "seed_text.py")
        used += "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "scripts").glob("ui_*.py"))
        families = {"seeds_status_": ("proposed", "active", "inactive"), "seeds_stateline_": sd.STATES, "seeds_bulk_dlg_": ("activate", "rest"), "seeds_bulk_effect_": ("activate", "rest"), "seeds_bulk_ok_": ("activate", "rest"),
                    "seeds_bulk_done_": ("activate", "rest"), "sf_label_": [spec.name for spec in sf.EDIT_FIELDS] + [spec.name for spec in sf.CREATE_FIELDS], "sf_hint_": [spec.name for spec in sf.EDIT_FIELDS] + [spec.name for spec in sf.CREATE_FIELDS],
                    "seeds_bulk_part_": ("proposed", "inactive", "active"), "seeds_fail_": seeds_view.FAILURE_TEXT, "sf_placeholder_": ("words", "keyword", "name", "reason")}
        for key, value in seed_text.SEED_T.items():
            family = next((prefix for prefix in families if key.startswith(prefix)), None)
            if family is not None:
                self.assertIn(key[len(family):], families[family] if not isinstance(families[family], dict) else {name[len("seeds_fail_"):] for name in families[family].values()}, key)
            else:
                self.assertRegex(used, rf'["\']{key}["\']', f"죽은 글: {key}")
            for word in text.FORBIDDEN:
                self.assertNotIn(word, value, key)
            self.assertNotRegex(value, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b|Traceback|Exception|Error\b|테마|다크|어두운", key)
        for prefix, names in families.items():
            for name in (names if not isinstance(names, dict) else {item[len("seeds_fail_"):] for item in names.values()}):
                self.assertIn(prefix + name, seed_text.SEED_T, prefix + name)
        self.assertEqual(set(seed_text.SEED_T) & set(text.T), set(seed_text.SEED_T))
        self.assertTrue(all(text.T[key] == value for key, value in seed_text.SEED_T.items()), "합친 값이 그대로다")
        self.assertEqual(T["seeds_title"], "Seed 관리")
        self.assertEqual(T["nav_seed"], "Seed 관리")

    def test_the_view_models_never_contain_python_lists_enum_codes_or_the_words_none_and_true(self):
        controller = new_controller()
        controller.open_detail("EX012")
        views = [controller.view(), controller.drawer_view()]
        controller.open_new()
        views.append(controller.drawer_view())
        dump = repr(views)
        values = [item for item in re.findall(r"'(?:text|label|a11y|title|body|heading|desc|reason|hint|error|warning|value)': '([^']*)'", dump)]
        self.assertGreater(len(values), 100)
        for value in values:
            self.assertNotRegex(value, r"\['|\bNone\b|\bTrue\b|\bFalse\b|Traceback|\bproposed\b|\binactive\b|\bseasonal\b")


class SourceRulesTest(unittest.TestCase):
    CORE = [path for path in (UI_DIR / "core").glob("seed*.py")]
    QT = [path for path in (UI_DIR / "qt").glob("seed*.py")]
    REAL_BLOGS = ("ssae" + "ssace", "shine" + "5652", "스마트" + "프라이싱", "스마트" + "초이스", "실전" + "노트", "디지털" + "찬스")

    def calls(self, path):
        return [ast.unparse(node.func) for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Call)]

    def test_the_screen_code_has_no_file_writing_call_at_all(self):
        self.assertGreaterEqual(len(self.CORE), 5)
        exact = {"open", "os.open", "os.write", "os.fsync", "os.replace", "os.rename", "os.remove", "os.unlink", "shutil.copy", "shutil.copyfile", "shutil.copy2", "shutil.move", "shutil.rmtree", "write_json", "save_seeds", "init_files"}
        attributes = {"write_text", "write_bytes", "unlink", "mkdir", "touch", "rmtree", "write_json", "save_seeds", "init_files", "fsync", "rmdir", "chmod"}
        for path in self.CORE + self.QT + [UI_DIR / "core" / "app_state.py"]:
            for call in self.calls(path):
                with self.subTest(file=path.name, call=call):
                    self.assertNotIn(call, exact)
                    self.assertNotIn(call.rsplit(".", 1)[-1], attributes)

    def test_the_adapter_writes_only_through_the_five_service_functions_and_reads_through_two(self):
        tree = ast.parse((UI_DIR / "seeds_adapter.py").read_text(encoding="utf-8"))
        used = sorted({ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func).startswith("service.")})
        self.assertEqual(used, ["service.apply_import", "service.create_seed", "service.edit_seed", "service.preview_import", "service.read_snapshot", "service.set_state", "service.set_states"])
        text_of = (UI_DIR / "seeds_adapter.py").read_text(encoding="utf-8")
        self.assertIn("confirmed=True, expected_count=len(ids)", text_of, "여러 개 바꾸는 서비스 호출에는 확인 표시와 확인한 개수가 간다")
        self.assertNotIn("topic_files", text_of)
        self.assertNotIn("security.keystore", text_of)

    def test_the_two_confirmation_gates_are_in_the_controller_and_the_only_starters_of_those_writes(self):
        tree = ast.parse((UI_DIR / "core" / "seeds_view.py").read_text(encoding="utf-8"))
        starts = {node.name: ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in ("start_bulk", "start_import_apply")}
        self.assertIn("bulk_asked != (kind, ids)", starts["start_bulk"])
        self.assertIn("not self.import_asked", starts["start_import_apply"])
        self.assertIn("unconfirmed", starts["start_bulk"])
        self.assertIn("unconfirmed", starts["start_import_apply"])
        called = {}
        for path in UI_DIR.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("start_bulk", "start_import_apply", "start_state", "start_create", "start_save"):
                    called.setdefault(node.func.attr, set()).add(path.name)
        self.assertEqual({key: value - {"seeds_view.py"} for key, value in called.items() if key in ("start_bulk", "start_import_apply")}, {"start_bulk": {"shell.py"}, "start_import_apply": {"shell.py"}})

    def test_no_real_seed_or_blog_name_is_in_the_seed_screen_code_or_this_test(self):
        for path in self.CORE + self.QT + [UI_DIR / "seeds_adapter.py", Path(__file__)]:
            text_of = path.read_text(encoding="utf-8")
            for value in self.REAL_BLOGS:
                self.assertNotIn(value, text_of, path.name)

    def test_the_app_state_and_the_menu_know_the_new_screen_and_the_next_steps_no_longer_list_it(self):
        # 의도적 갱신(P4d, D-270): 주제 후보 화면이 완성돼 메뉴(핵심 작업 묶음, 홈 다음)에 올랐고 '다음 단계' 목록에서 빠졌다 — Seed 관리가 데이터·관리 묶음에 있고 '다음 단계' 에 없다는 뜻은 그대로다.
        # 의도적 갱신(P4e, D-282): 초안 작성 화면이 완성돼 메뉴(핵심 작업 묶음, 주제 후보 다음)에 올랐고 '다음 단계' 목록에는 발행 기록만 남았다 — 뜻은 그대로다.
        self.assertEqual([item[0] for item in app_state.NAV], ["home", "topics", "drafts", "seed", "blogs", "settings"])
        self.assertEqual([item[0] for item in app_state.nav_groups()[1][2]], ["seed", "blogs"])
        self.assertEqual([item[0] for item in app_state.NEXT_STEPS], ["history"])
        state = app_state.AppState()
        self.assertIsInstance(state.seeds_provider, seeds.FakeSeedsProvider)
        self.assertEqual(state.seeds.state, "loading")
        self.assertIsNone(state.seeds_drawer_view(), "다른 화면에서는 서랍이 없다")
        self.assertTrue(state.nav("seed"))
        self.assertTrue(isinstance(services.FakeHomeProvider().seeds_provider(), seeds.FakeSeedsProvider))
        self.assertIsInstance(adapters.ServiceHomeProvider("x").seeds_provider(), seeds_adapter.ServiceSeedsProvider)

    def test_the_drawer_closes_with_the_menu_but_the_drafts_stay(self):
        state = app_state.AppState()
        load(state.seeds)
        state.nav("seed")
        state.seeds.open_detail("EX001")
        state.seeds.edit("priority", True)
        self.assertIsNotNone(state.seeds_drawer_view())
        self.assertEqual(state.close_drawer(), "seed:EX001")
        self.assertIsNone(state.seeds.drawer)
        self.assertTrue(state.seeds.is_dirty("EX001"))
        state.seeds.open_detail("EX002")
        state.nav("home")
        self.assertIsNone(state.seeds.drawer)


if __name__ == "__main__":
    unittest.main()
