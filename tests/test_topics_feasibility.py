"""작성 가능성(`topics/feasibility.py`) 시험 — 소제목 뼈대 표(초기값), 검색 의도가 더하는 소제목, 자동 보완 순서, 점수 표, '못 채우면 낮음(0점 아님)', '모르면 None'.

지키는 것:
  1) **표는 구현자 초기값이다 — 전략 원문과 2026-11-06 에 대조했고 원문이 정한 값이 아니다(D-104).** 소제목 이름(37개)·글 종류별 기본 뼈대 11개·검색 의도별 추가 소제목 8개·자동 보완 순서(자주 묻는 질문 → 체크리스트 → 비교표 → 주의할 점)·그 글 종류에 안 맞는 보완·점수(90·80·70·60·50·낮음 30)를
     이 시험이 손으로 쓴 값과 같은지 못박는다 — 원문에 맞춰 고칠 때는 `feasibility.py` 한 곳과 이 시험의 같은 표를 의식적으로 함께 고친다.
  2) 글 종류 11개 × 검색 의도 8개 × 소제목 최소 수 1~12 의 모든 조합을 이 시험의 **독립 참조 구현**과 견준다(뼈대·보완·단계·점수 모두).
  3) 소제목 최소 수에 못 미쳐도 보완 순서대로 하나씩만 더하고(이미 있는 것·안 맞는 글 종류는 건너뜀) 그래도 못 채우면 점수를 낮춘다(`LOW_SCORE` — 0점이 아니다). 글 종류나 검색 의도를 모르면 점수도 None 이다(0점으로 치지 않는다).
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import feasibility as fe  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402

LABELS = {
    "overview": "한눈에 보기", "details": "자세히 보기", "example": "예시로 보기", "wrap_up": "정리", "prepare": "준비물과 준비", "steps": "단계별 방법", "stuck_points": "자주 막히는 부분",
    "before_start": "시작 전 점검", "checklist": "체크리스트", "easy_to_miss": "빠뜨리기 쉬운 것", "next_check": "다음 점검 시기", "symptoms": "증상 확인", "causes": "원인 후보", "fix_order": "해결 순서",
    "still_failing": "그래도 안 될 때", "criteria": "고르는 기준", "by_situation": "상황별 선택", "cautions": "주의할 점", "differences": "항목별 차이", "comparison_table": "비교표",
    "before_visit": "가기 전에 확인할 것", "how_to_get": "가는 방법", "highlights": "둘러볼 곳", "what_happened": "무슨 일이 있었나", "why_it_matters": "왜 중요한가", "impact": "영향", "goal": "목표 정하기",
    "daily_flow": "하루 흐름", "keep_going": "꾸준히 하는 요령", "situation": "상황", "tried": "시도한 것", "result": "결과", "what_it_is": "무엇인가", "how_to_use": "쓰는 방법", "pros_cons": "장단점",
    "who_for": "누구에게 맞나", "faq": "자주 묻는 질문",
}
BASE = {
    "explainer": ("overview", "details", "example", "wrap_up"), "how_to_guide": ("prepare", "steps", "stuck_points", "wrap_up"), "checklist": ("before_start", "checklist", "easy_to_miss", "next_check"),
    "troubleshooting": ("symptoms", "causes", "fix_order", "still_failing"), "buying_guide": ("criteria", "by_situation", "cautions"), "comparison": ("criteria", "differences", "by_situation"),
    "place_guide": ("before_visit", "how_to_get", "highlights"), "news_analysis": ("what_happened", "why_it_matters", "impact"), "routine_plan": ("goal", "daily_flow", "keep_going"),
    "dev_log": ("situation", "tried", "result"), "service_intro": ("what_it_is", "how_to_use", "pros_cons", "who_for"),
}
EXTRAS = {"information": ("overview",), "how_to": ("steps",), "problem_solving": ("fix_order",), "selection_guide": ("by_situation",), "comparison": ("comparison_table",), "local_info": ("before_visit",),
          "context_explainer": ("impact",), "routine_building": ("keep_going",)}
ORDER = ("faq", "checklist", "comparison_table", "cautions")
NOT_FOR = {"comparison_table": ("news_analysis", "routine_plan", "dev_log")}
SCORES = {0: 90, 1: 80, 2: 70, 3: 60, 4: 50}


def reference(content_type, intent, minimum):
    """독립 참조 구현 — 표만 읽고 같은 규칙을 다시 쓴다. (뼈대, 처음 뼈대, 더한 것, 단계, 점수)."""
    base = list(BASE[content_type])
    for name in EXTRAS[intent]:
        if name not in base:
            base.append(name)
    sections, added = list(base), []
    for name in ORDER:
        if len(sections) >= minimum:
            break
        if name in sections or content_type in NOT_FOR.get(name, ()):
            continue
        sections.append(name)
        added.append(name)
    if len(sections) < minimum:
        return tuple(sections), tuple(base), tuple(added), "low", 30
    return tuple(sections), tuple(base), tuple(added), ("ready" if not added else "supplemented"), SCORES[len(added)]


class InitialTablesTest(unittest.TestCase):
    def test_the_module_says_the_tables_are_implementer_initial_values_compared_with_the_strategy_original(self):
        # 의도적 갱신(전략 맞춤 1차 ③, D-104): 머리말이 '전략 원문 확인 전' 에서 '원문과 대조했다 — 이 표는 계획 문서 예에서 온 구현자 초기값, 원문 §16 은 성격이 다른 7단계' 로 바뀌었다. 표 값·소제목 보충 검사는 그대로다.
        doc = Path(fe.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        self.assertIn("구현자 초기값", doc)
        self.assertIn("2026-11-06 에 대조했고", doc)
        for stale in ("원문 확인 전", "이 PC 에 없어서"):
            self.assertNotIn(stale, doc)
        for step in ("넓은 키워드 세분화", "대상 독자·목적 적용", "글 유형 기본 구조 적용", "보조 키워드 추가", "기존 글에서 다루지 않은 관점 적용", "안전한 정보형으로 전환", "작성 가능한 하위 주제 최대 3개 생성"):
            self.assertIn(step, doc)
        for needle in ("7단계", "규칙 기반 초안 본문 생성기", "작성 기반 부족", "88조합 중 0", "그대로 둔다"):
            self.assertIn(needle, doc)
        for name in ("SECTIONS", "BASE_OUTLINES", "INTENT_EXTRAS", "SUPPLEMENT_ORDER", "SUPPLEMENT_NOT_FOR", "SCORES_BY_ADDED", "LOW_SCORE"):
            self.assertIn(name, doc)

    def test_the_header_claim_that_no_ordinary_combination_reaches_low_is_true_for_the_default_minimum(self):
        # 머리말의 '88조합 중 0' 을 직접 센다 — 소제목 최소 4(기본)에서 글 종류 11 × 검색 의도 8 어느 조합도 '낮음' 이 아니다(그래서 '작성 기반 부족' 보류에 닿지 못한다).
        combos = [(content_type, intent) for content_type in md.CONTENT_TYPES for intent in md.SEARCH_INTENTS]
        self.assertEqual(len(combos), 88)
        self.assertEqual([pair for pair in combos if fe.assess(*pair).level == "low"], [])

    def test_the_section_names_are_exactly_these(self):
        self.assertEqual(dict(fe.SECTIONS), LABELS)
        self.assertEqual(len(fe.SECTIONS), 37)

    def test_the_base_outlines_the_intent_extras_and_the_supplement_rules_are_exactly_these(self):
        self.assertEqual({name: tuple(value) for name, value in fe.BASE_OUTLINES.items()}, BASE)
        self.assertEqual({name: tuple(value) for name, value in fe.INTENT_EXTRAS.items()}, EXTRAS)
        self.assertEqual(fe.SUPPLEMENT_ORDER, ORDER)
        self.assertEqual({name: tuple(value) for name, value in fe.SUPPLEMENT_NOT_FOR.items()}, NOT_FOR)
        self.assertEqual(dict(fe.SCORES_BY_ADDED), SCORES)
        self.assertEqual(fe.LOW_SCORE, 30)
        self.assertEqual(fe.MAX_SUBHEADING_MIN, 20)
        self.assertEqual(fe.LEVELS, ("ready", "supplemented", "low", "unknown"))

    def test_the_tables_cover_every_closed_list_of_the_candidate_model_and_only_use_known_section_names(self):
        self.assertEqual(set(fe.BASE_OUTLINES), set(md.CONTENT_TYPES))
        self.assertEqual(set(fe.INTENT_EXTRAS), set(md.SEARCH_INTENTS))
        for names in (*fe.BASE_OUTLINES.values(), *fe.INTENT_EXTRAS.values(), fe.SUPPLEMENT_ORDER):
            self.assertTrue(set(names) <= set(fe.SECTIONS))
        for name, types in fe.SUPPLEMENT_NOT_FOR.items():
            self.assertIn(name, fe.SUPPLEMENT_ORDER)
            self.assertTrue(set(types) <= set(md.CONTENT_TYPES))
        for name, labels in ((name, fe.SECTIONS[name]) for name in fe.SECTIONS):
            self.assertTrue(labels and labels == labels.strip() and "  " not in labels, name)

    def test_every_default_channel_asks_for_four_subheadings_and_the_scores_fall_by_ten_per_added_one(self):
        for profile in ts.PROFILES.values():
            self.assertEqual(profile.subheading_min, 4)
        self.assertEqual([fe.SCORES_BY_ADDED[count] for count in range(5)], [90, 80, 70, 60, 50])
        self.assertLess(fe.LOW_SCORE, min(fe.SCORES_BY_ADDED.values()))
        self.assertGreater(fe.LOW_SCORE, 0, "낮추되 0점은 아니다")


class AssessTest(unittest.TestCase):
    def test_every_content_type_intent_and_minimum_matches_the_independent_reference(self):
        count = 0
        for content_type, intent, minimum in itertools.product(md.CONTENT_TYPES, md.SEARCH_INTENTS, range(1, 13)):
            sections, base, added, level, points = reference(content_type, intent, minimum)
            found = fe.assess(content_type, intent, subheading_min=minimum)
            count += 1
            with self.subTest(content_type=content_type, intent=intent, minimum=minimum):
                self.assertEqual((found.level, found.score), (level, points))
                self.assertEqual((found.outline.sections, found.outline.base, found.outline.added, found.outline.minimum), (sections, base, added, minimum))
                self.assertEqual(found.outline.labels, tuple(LABELS[name] for name in sections))
                self.assertEqual(len(found.reasons), 1)
        self.assertEqual(count, 11 * 8 * 12)

    def test_the_default_minimum_is_four_and_a_three_piece_outline_gets_one_added_question_section(self):
        found = fe.assess("buying_guide", "selection_guide")
        self.assertEqual((found.level, found.score), ("supplemented", 80))
        self.assertEqual(found.outline.sections, ("criteria", "by_situation", "cautions", "faq"))
        self.assertEqual((found.outline.base, found.outline.added, found.outline.minimum), (("criteria", "by_situation", "cautions"), ("faq",), 4))
        self.assertEqual(found.reasons, ("소제목 뼈대 3개에 자동 보완 1개(자주 묻는 질문)를 더해 최소 4개를 채웠습니다",))

    def test_a_type_that_already_has_four_gets_no_supplement_and_the_full_score(self):
        found = fe.assess("explainer", "information")
        self.assertEqual((found.level, found.score, found.outline.added), ("ready", 90, ()))
        self.assertEqual(found.reasons, ("글 종류와 검색 의도만으로 소제목 뼈대 4개가 나와 최소 4개를 채웁니다",))

    def test_the_intent_adds_its_own_section_before_any_supplement_and_only_when_it_is_missing(self):
        found = fe.assess("comparison", "comparison")
        self.assertEqual((found.outline.base, found.outline.added, found.level, found.score), (("criteria", "differences", "by_situation", "comparison_table"), (), "ready", 90))
        self.assertEqual(fe.assess("buying_guide", "selection_guide").outline.base, ("criteria", "by_situation", "cautions"), "이미 있는 소제목은 다시 더하지 않는다")

    def test_the_supplements_come_in_the_documented_order_and_skip_what_is_there_or_does_not_fit(self):
        found = fe.assess("news_analysis", "context_explainer", subheading_min=6)
        self.assertEqual(found.outline.added, ("faq", "checklist", "cautions"), "비교표는 뉴스 분석에 안 맞아 건너뛴다")
        self.assertEqual((found.level, found.score), ("supplemented", 60))
        self.assertEqual(fe.assess("buying_guide", "information", subheading_min=7).outline.added, ("faq", "checklist", "comparison_table"))
        self.assertEqual(fe.assess("checklist", "information", subheading_min=7).outline.added, ("faq", "comparison_table"), "이미 있는 체크리스트는 건너뛴다")
        self.assertEqual(fe.assess("buying_guide", "information", subheading_min=6).outline.sections, ("criteria", "by_situation", "cautions", "overview", "faq", "checklist"))

    def test_when_even_every_supplement_is_not_enough_the_level_is_low_and_the_score_is_lowered_not_zero(self):
        found = fe.assess("news_analysis", "context_explainer", subheading_min=7)
        self.assertEqual((found.level, found.score), ("low", 30))
        self.assertEqual(found.outline.added, ("faq", "checklist", "cautions"))
        self.assertEqual(len(found.outline.sections), 6)
        self.assertEqual(found.reasons, ("소제목 뼈대가 6개뿐이라 최소 7개를 채우지 못했습니다(자동 보완 3개를 더해도 모자랍니다) — 작성 가능성을 낮게 봅니다",))
        self.assertIsNotNone(found.score)
        self.assertGreater(found.score, 0)

    def test_a_larger_minimum_never_raises_the_score(self):
        for content_type, intent in itertools.product(md.CONTENT_TYPES, md.SEARCH_INTENTS):
            scores = [fe.assess(content_type, intent, subheading_min=minimum).score for minimum in range(1, 13)]
            with self.subTest(content_type=content_type, intent=intent):
                self.assertEqual(scores, sorted(scores, reverse=True))

    def test_not_knowing_the_type_or_the_intent_gives_no_score_and_no_outline_and_is_not_zero(self):
        for content_type, intent in ((None, "how_to"), ("explainer", None), (None, None)):
            with self.subTest(content_type=content_type, intent=intent):
                found = fe.assess(content_type, intent)
                self.assertEqual((found.level, found.score, found.outline), ("unknown", None, None))
                self.assertIn("0점으로 치지 않고", found.reasons[0])

    def test_wrong_values_are_programming_errors(self):
        for content_type, intent in (("Explainer", "how_to"), ("explainer", "HOW_TO"), ("nope", "how_to"), (3, "how_to"), ("explainer", "nope"), ("explainer", 3), ("", "how_to")):
            with self.subTest(content_type=content_type, intent=intent):
                with self.assertRaises(ValueError):
                    fe.assess(content_type, intent)
        for bad in (0, -1, 21, True, 4.0, "4", None):
            with self.subTest(minimum=bad):
                with self.assertRaises(ValueError):
                    fe.assess("explainer", "information", subheading_min=bad)
        self.assertEqual(fe.assess("explainer", "information", subheading_min=1).level, "ready")
        self.assertEqual(fe.assess("explainer", "information", subheading_min=20).level, "low")

    def test_the_result_is_a_value_that_does_not_change_and_is_the_same_every_time(self):
        first = fe.assess("service_intro", "information")
        self.assertEqual(first, fe.assess("service_intro", "information"))
        self.assertIsInstance(first.outline.sections, tuple)
        with self.assertRaises(AttributeError):
            first.score = 1


class AssessCandidateTest(unittest.TestCase):
    def test_it_reads_the_type_the_intent_and_the_channels_minimum(self):
        made = ts.make(content_type="buying_guide", search_intent="selection_guide")
        found = fe.assess_candidate(made, ts.PROFILES["naver_b"])
        self.assertEqual(found, fe.assess("buying_guide", "selection_guide", subheading_min=4))
        import dataclasses
        strict = dataclasses.replace(ts.PROFILES["naver_b"], subheading_min=6)
        self.assertEqual(fe.assess_candidate(made, strict).outline.added, ("faq", "checklist", "comparison_table"))
        lax = dataclasses.replace(ts.PROFILES["naver_b"], subheading_min=2)
        self.assertEqual(fe.assess_candidate(made, lax).level, "ready")

    def test_the_candidate_and_the_profile_must_be_of_the_same_channel(self):
        with self.assertRaises(ValueError):
            fe.assess_candidate(ts.make(), ts.PROFILES["naver_a"])
        for args in ((None, ts.PROFILES["naver_b"]), (ts.make(), None), (ts.make().to_dict(), ts.PROFILES["naver_b"]), (ts.make(), "naver_b")):
            with self.assertRaises(TypeError):
                fe.assess_candidate(*args)

    def test_the_score_fits_the_feasibility_slot_of_the_six_factors_without_a_conversion(self):
        from chanceblog_desktop.topics import score as sc
        for content_type in md.CONTENT_TYPES:
            found = fe.assess(content_type, "information")
            self.assertEqual(sc.Factors(feasibility=found.score).feasibility, found.score)
        self.assertIsNone(sc.Factors(feasibility=fe.assess(None, None).score).feasibility)


class PublicNamesTest(unittest.TestCase):
    def test_the_module_lists_exactly_the_names_it_exports(self):
        for name in fe.__all__:
            self.assertTrue(hasattr(fe, name), name)
        self.assertEqual(len(set(fe.__all__)), len(fe.__all__))


if __name__ == "__main__":
    unittest.main()
