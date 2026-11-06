"""확장 차단의 예외 규칙 회귀 시험(P3b-1 fix1-G) — 차단은 **계열 단위**가 기본이고, (대상 유형 × 채널 × Recipe × 확장어) 네 가지를 함께 보고 평가하며, 예외 표(`FAMILY_EXCEPTIONS`)에 적힌 조합만 더해서 허용한다.

첫 예외 하나: 장소·숙박 대상 × 확장어 ‘API 연동’ × 채널 네이버 B × Recipe `tourapi_integration` → 허용. 네이버 A 의 여행 글·Recipe 가 없는 호출·다른 Recipe·다른 채널·다른 대상 유형은 지금까지처럼 막힌다.
이 시험의 **기준 표는 모두 시험 안에 손으로 적은 독립 표**다(변경 전 동작 — 코드의 표를 불러다 기대값을 만들지 않는다): 대상 유형 → 허용 계열, 확장어 41개의 계열. 코드의 표가 그것과 한 칸이라도 다르면 빨개진다.
예외를 더하는 방법: 코드의 `FAMILY_EXCEPTIONS` 에 한 줄 + 이 파일의 `EXPECTED_EXCEPTIONS` 에 한 줄 + (그 조합이 더 열어 주는 칸) `EXCEPTION_CELLS` — 셋이 서로 맞아야 한다.
Recipe(조합 방식) 값의 씨앗 쪽 출처는 공공데이터 프로젝트(PD0)의 몫이다(`DEFERRED`) — 지금은 `expand(…, recipe=…)` 인자로만 받고, 부르는 쪽(`generate.py`·`brand.py`)은 넘기지 않는다.

입력은 모두 시험용으로 지어낸 **예시** 씨앗·낱말이다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import expand as ex  # noqa: E402
from chanceblog_desktop.topics import notice, seeds as sd  # noqa: E402

PROFILES = ts.PROFILES
CHANNEL_CODES = ("github_pages", "blogger_ko", "blogger_en", "naver_a", "naver_b")
RECIPE = "tourapi_integration"
PLACE_TYPES = ("place", "lodging", "place_lodging")

# ---- 독립 기준 표 1 — 변경 전의 대상 유형 → 허용 계열(원문 §10.3 낱말의 계열 + 알아 두기). 시험 안에 손으로 적었다 ----------------------------------------------------------------
BASELINE_ALLOWED = {
    "product": {"choose", "howto", "info"},
    "place": {"place", "info"}, "lodging": {"place", "info"}, "place_lodging": {"place", "info"},
    "service": {"choose", "howto", "info"}, "saas": {"choose", "howto", "info"}, "service_saas": {"choose", "howto", "info"},
    "pc_part": {"choose", "howto", "info"},
    "problem": {"fix", "info"},
    "life_habit": {"habit", "howto", "info"},
    "realtime_issue": {"context", "fix", "choose", "info"},
    "policy": {"context", "info", "howto"}, "api": {"context", "info", "howto"}, "policy_api": {"context", "info", "howto"},
}
FAMILIES = ("choose", "howto", "fix", "context", "place", "habit", "case", "info")

# ---- 독립 기준 표 2 — 원문 §10.3 낱말 41개의 계열(변경 전, `TARGET_WORD_FAMILY` 와 한 칸씩 같아야 한다) --------------------------------------------------------------------------
TARGET_WORD_FAMILY = {
    "선택 기준": "choose", "비교": "choose", "호환성": "choose", "관리": "howto", "구매 전 확인": "choose",
    "이동": "place", "예약": "place", "방문 전 확인": "place", "계절": "place", "숙박 조건": "place", "주변 이용 정보": "place",
    "요금": "choose", "기능": "choose", "무료·유료 비교": "choose", "설정": "howto", "연동": "howto", "해지·이관": "howto",
    "성능": "choose", "소비전력": "choose", "가격": "choose", "설치": "howto", "업그레이드": "howto",
    "원인": "fix", "점검": "fix", "해결": "fix", "예방": "fix", "지원이 필요한 조건": "fix",
    "단순화": "habit", "반복 루틴": "habit", "체크리스트": "howto", "유지 방법": "habit",
    "변화": "context", "영향": "context", "대응": "fix", "대안": "choose", "종료·이관": "context",
    "적용 일정": "context", "변경사항": "context", "무료 한도": "info", "인증": "howto", "마이그레이션": "howto",
}

# ---- 독립 기준 표 3 — 방향 낱말 41개(옛 방향 표 32 + 새 규칙 낱말 9)의 계열: 허용 행렬(대상 유형 × 확장어)의 세로축 ------------------------------------------------------------------
KNOWN_WORD_FAMILY = {
    "구매 기준": "choose", "제품 비교": "choose", "성능": "choose", "호환성": "choose", "설치": "howto", "설정": "howto", "API 연동": "howto", "관리 방법": "howto", "정보 관리": "howto",
    "오류 해결": "fix", "변화": "context", "영향": "context", "배경": "context", "산업·경제·사회적 맥락": "context", "분야 연결": "context", "방문 전 확인": "place", "지역·계절 체험": "place",
    "정리": "habit", "습관": "habit", "반복 관리": "habit", "생활 부담 줄이기": "habit", "simple routine": "habit", "gentle reset": "habit", "low-pressure habit": "habit",
    "everyday checklist": "habit", "자동화 사례": "case", "방법": "howto", "체크리스트": "howto", "비교": "choose", "비용": "choose", "주의할 점": "info", "자주 묻는 질문": "info",
    "순서": "howto", "기준": "choose", "원인": "fix", "해결": "fix", "주의사항": "info", "관리": "howto", "예방": "fix", "방문 후기": "place", "맛집 비교": "place",
}
COMMON_TEN = ("방법", "순서", "기준", "비교", "원인", "해결", "주의사항", "체크리스트", "관리", "예방")

# ---- 예외 표의 기대값(코드의 `FAMILY_EXCEPTIONS` 와 한 줄씩 같아야 한다)과 그 예외가 더 열어 주는 칸 ---------------------------------------------------------------------------------
EXPECTED_EXCEPTIONS = (
    ("place_lodging_tourapi_integration", ("place", "lodging", "place_lodging"), ("naver_b",), (RECIPE,), ("howto",), ("API 연동",)),
)
EXCEPTION_CELLS = {(target, "naver_b", RECIPE, "API 연동") for target in PLACE_TYPES}          # (대상 유형, 채널, Recipe, 확장어) — 기본 허용표가 막는데 예외가 여는 칸 전부


def baseline_allowed(target, word):
    """변경 전 동작 — 이 낱말의 계열이 대상 유형의 허용 계열에 드는가(채널·Recipe 는 보지 않았다)."""
    return KNOWN_WORD_FAMILY[word] in BASELINE_ALLOWED[target]


def expected_allowed(target, channel, recipe, word):
    """변경 후 기대 — 변경 전 동작 + 예외 칸(위 `EXCEPTION_CELLS`)."""
    return baseline_allowed(target, word) or (target, channel, recipe, word) in EXCEPTION_CELLS


def direction_of(word, family=None):
    """독립 표의 계열로 만든 방향(코드의 낱말 표를 거치지 않는다)."""
    return ex.Direction(word, family or KNOWN_WORD_FAMILY[word], "information", "explainer", "example-angle", True)


def seed(**changes):
    changes.setdefault("keyword", "예시 숙소")
    changes.setdefault("scope", "common")
    return ts.example_seed(**changes)


def keyword_for(profile):
    return "example hotel" if profile.language == "en" else "예시 숙소"


def with_api(profile):
    words = profile.expansion_directions
    return profile if "API 연동" in words else dataclasses.replace(profile, expansion_directions=(*words, "API 연동"))


def words(result):
    return [item.direction for item in result.items]


def blocked(result):
    return {item.direction: item for item in result.blocked}


def matrix_counts():
    """허용 행렬의 요약 — 대상 유형마다 확장어 41개 중 허용되는 낱말 수 (예외 없이, 예외 칸이 열린 채널·Recipe 에서)."""
    plain = {target: sum(baseline_allowed(target, word) for word in KNOWN_WORD_FAMILY) for target in BASELINE_ALLOWED}
    opened = {target: sum(expected_allowed(target, "naver_b", RECIPE, word) for word in KNOWN_WORD_FAMILY) for target in BASELINE_ALLOWED}
    return plain, opened


class IndependentTablesTest(unittest.TestCase):
    """코드의 표가 변경 전과 한 칸씩 같다 — 예외 규칙은 이 표를 건드리지 않는다(L1/m63: `TARGET_WORD_FAMILY` 의 낱말 하나만 바꿔도 빨개진다)."""

    def test_the_allowed_families_of_every_target_type_match_the_independent_table_cell_by_cell(self):
        self.assertEqual(set(ex.TARGET_ALLOWED_FAMILIES), set(BASELINE_ALLOWED), "대상 유형 열네 개가 그대로")
        self.assertEqual(set(ex.TARGET_ALLOWED_FAMILIES), set(sd.ALL_TARGET_TYPES))
        for target in BASELINE_ALLOWED:
            for family in FAMILIES:
                with self.subTest(target=target, family=family):
                    self.assertEqual(family in ex.TARGET_ALLOWED_FAMILIES[target], family in BASELINE_ALLOWED[target])
            self.assertEqual(len(ex.TARGET_ALLOWED_FAMILIES[target]), len(set(ex.TARGET_ALLOWED_FAMILIES[target])), "계열이 되풀이되지 않는다")

    def test_the_family_of_every_original_word_matches_the_independent_table(self):
        self.assertEqual(set(ex.TARGET_WORD_FAMILY), set(TARGET_WORD_FAMILY))
        self.assertEqual(len(TARGET_WORD_FAMILY), 41)
        for word, family in TARGET_WORD_FAMILY.items():
            with self.subTest(word=word):
                self.assertEqual(ex.TARGET_WORD_FAMILY[word], family)

    def test_the_family_of_every_direction_word_matches_the_independent_table(self):
        found = {**{key: row for key, row in ex.DIRECTIONS.items()}, **{key: row for key, row in ex.STRATEGY_DIRECTIONS.items()}}
        self.assertEqual({row.word for row in found.values()}, set(KNOWN_WORD_FAMILY))
        self.assertEqual(len(KNOWN_WORD_FAMILY), 41)
        for word, family in KNOWN_WORD_FAMILY.items():
            with self.subTest(word=word):
                self.assertEqual(ex.strategy_direction_of(word).family, family)
        self.assertTrue(set(COMMON_TEN) <= set(KNOWN_WORD_FAMILY) and tuple(ex.STRATEGY_COMMON_DIRECTIONS) == COMMON_TEN)

    def test_the_exception_table_is_exactly_the_expected_rows(self):
        found = tuple((rule.name, rule.target_types, rule.channels, rule.recipes, rule.families, rule.words) for rule in ex.FAMILY_EXCEPTIONS)
        self.assertEqual(found, EXPECTED_EXCEPTIONS, "예외를 더하거나 고치면 이 시험의 기대 표도 함께 고친다(의식적인 결정)")
        self.assertEqual(ex.RECIPE_TOURAPI_INTEGRATION, RECIPE)

    def test_every_exception_row_is_consistent_and_its_reason_is_plain_korean(self):
        names = [rule.name for rule in ex.FAMILY_EXCEPTIONS]
        self.assertEqual(len(names), len(set(names)), "예외 이름은 겹치지 않는다")
        for rule in ex.FAMILY_EXCEPTIONS:
            with self.subTest(rule=rule.name):
                self.assertTrue(rule.target_types and rule.channels and rule.recipes and rule.families, "대상 유형·채널·Recipe·계열은 비어 있지 않다(비면 아무 데도 안 맞는다)")
                self.assertTrue(set(rule.target_types) <= set(sd.ALL_TARGET_TYPES))
                self.assertTrue(set(rule.channels) <= set(CHANNEL_CODES))
                self.assertTrue(set(rule.families) <= set(ex.FAMILIES))
                self.assertTrue(all(isinstance(item, str) and item.strip() == item and item for item in (*rule.recipes, *rule.words)))
                for word in rule.words:
                    self.assertIn(word, KNOWN_WORD_FAMILY, "예외가 여는 낱말은 방향 표에 있는 낱말이다")
                    self.assertIn(KNOWN_WORD_FAMILY[word], rule.families, "여는 낱말의 계열이 예외의 계열 안에 있다")
                for target in rule.target_types:
                    for word in rule.words:
                        self.assertFalse(baseline_allowed(target, word), "기본 허용표가 이미 허용하는 낱말은 예외가 아니다(예외는 막힌 것을 여는 것뿐)")
                self.assertTrue(rule.reason and notice.is_clean(rule.reason), rule.reason)
        self.assertEqual(EXCEPTION_CELLS, {(t, c, r, w) for rule in ex.FAMILY_EXCEPTIONS for t in rule.target_types for c in rule.channels for r in rule.recipes for w in rule.words},
                         "예외가 여는 칸 목록(시험의 독립 목록)과 같다")


class DecisionGridTest(unittest.TestCase):
    """(대상 유형 14 × 채널 5 × Recipe 5 × 확장어 41) 전체 칸을 독립 표로 판정한 것과 `family_decision` 이 한 칸도 다르지 않다 — 예외 표 밖의 칸은 변경 전과 같다."""
    RECIPES = (None, "", "   ", RECIPE, "other_recipe")

    def test_every_cell_matches_the_independent_expectation(self):
        wrong, opened = [], set()
        for target in BASELINE_ALLOWED:
            for channel in CHANNEL_CODES:
                for recipe in self.RECIPES:
                    for word in KNOWN_WORD_FAMILY:
                        decision = ex.family_decision(target, channel, recipe, direction_of(word))
                        want = expected_allowed(target, channel, recipe if recipe and recipe.strip() else None, word)
                        if decision.allowed != want:
                            wrong.append((target, channel, recipe, word, decision.allowed, want))
                        if decision.basis == ex.BASIS_EXCEPTION:
                            opened.add((target, channel, recipe, word))
                        self.assertEqual(decision.basis, ex.BASIS_FAMILY if baseline_allowed(target, word) else (ex.BASIS_EXCEPTION if want else ex.BASIS_BLOCKED))
        self.assertEqual(wrong, [], "독립 표와 다른 칸")
        self.assertEqual(opened, EXCEPTION_CELLS, "예외 표가 여는 칸은 정확히 이것뿐")

    def test_the_exception_only_opens_the_listed_word_not_the_rest_of_its_family(self):
        for word, family in KNOWN_WORD_FAMILY.items():
            if family != "howto" or word == "API 연동":
                continue
            for target in PLACE_TYPES:
                with self.subTest(target=target, word=word):
                    self.assertFalse(ex.family_decision(target, "naver_b", RECIPE, direction_of(word)).allowed, "같은 하는 법 계열의 다른 낱말은 계속 막는다")
        for target in PLACE_TYPES:
            self.assertFalse(ex.family_decision(target, "naver_b", RECIPE, direction_of("예시 하는 법 낱말", "howto")).allowed, "표에 없는 낱말은 계열이 같아도 예외가 아니다")
            self.assertTrue(ex.family_decision(target, "naver_b", RECIPE, direction_of("API 연동")).allowed)
            self.assertTrue(ex.family_decision(target, "naver_b", RECIPE, direction_of(" api 연동 ", "howto")).allowed, "낱말 비교는 `keyword_key` 로(공백·대소문자를 같게 본다)")

    def test_every_target_family_and_channel_cell_with_a_synthetic_word_equals_the_old_table(self):
        for target in BASELINE_ALLOWED:
            for channel in CHANNEL_CODES:
                for recipe in (None, RECIPE):
                    for family in FAMILIES:
                        with self.subTest(target=target, channel=channel, recipe=recipe, family=family):
                            self.assertEqual(ex.family_decision(target, channel, recipe, direction_of("예시 방향", family)).allowed, family in BASELINE_ALLOWED[target])

    def test_the_decision_records_which_rule_allowed_it(self):
        self.assertEqual(ex.family_decision("lodging", "naver_b", RECIPE, direction_of("API 연동")), ex.FamilyDecision(True, "exception", "place_lodging_tourapi_integration"))
        self.assertEqual(ex.family_decision("product", "naver_a", None, direction_of("API 연동")), ex.FamilyDecision(True, "family", None))
        self.assertEqual(ex.family_decision("lodging", "naver_a", RECIPE, direction_of("API 연동")), ex.FamilyDecision(False, "blocked", None))
        self.assertEqual(ex.family_decision("lodging", "naver_b", None, direction_of("API 연동")), ex.FamilyDecision(False, "blocked", None))

    def test_the_decision_function_is_pure_and_checks_its_inputs(self):
        first = [ex.family_decision(t, c, RECIPE, direction_of("API 연동")) for t in BASELINE_ALLOWED for c in CHANNEL_CODES]
        self.assertEqual(first, [ex.family_decision(t, c, RECIPE, direction_of("API 연동")) for t in BASELINE_ALLOWED for c in CHANNEL_CODES], "같은 입력은 늘 같은 결과")
        with self.assertRaises(ValueError):
            ex.family_decision("not_a_target", "naver_b", None, direction_of("API 연동"))
        with self.assertRaises(ValueError):
            ex.family_decision(None, "naver_b", None, direction_of("API 연동"))
        with self.assertRaises(TypeError):
            ex.family_decision("lodging", None, None, direction_of("API 연동"))
        with self.assertRaises(TypeError):
            ex.family_decision("lodging", "naver_b", None, "API 연동")
        with self.assertRaises(TypeError):
            ex.family_decision("lodging", "naver_b", 7, direction_of("API 연동"))


class PlaceApiIntegrationTest(unittest.TestCase):
    """장소·숙박 × API 연동 — 네이버 A 여행 글은 차단, 네이버 B 의 TourAPI 연동 글은 허용(운영자 지시 4)."""

    def expand(self, target, code, recipe=None, **more):
        profile = with_api(PROFILES[code])
        return ex.expand(seed(target_type=target, keyword=keyword_for(profile), **more), profile, limit=20, recipe=recipe)

    def test_naver_a_blocks_api_integration_for_place_and_lodging_with_or_without_a_recipe(self):
        for target in PLACE_TYPES:
            for recipe in (None, RECIPE):
                with self.subTest(target=target, recipe=recipe):
                    result = self.expand(target, "naver_a", recipe)
                    self.assertNotIn("API 연동", words(result))
                    found = blocked(result)["API 연동"]
                    self.assertEqual(found.reason, "combination")
                    self.assertIn("API 연동", found.detail)
                    self.assertIn("뜻이 맞지 않는 조합", found.detail)

    def test_naver_b_blocks_it_without_a_recipe_and_allows_it_for_the_tourapi_integration_recipe(self):
        for target in PLACE_TYPES:
            with self.subTest(target=target):
                plain = self.expand(target, "naver_b")
                self.assertNotIn("API 연동", words(plain))
                self.assertEqual(blocked(plain)["API 연동"].reason, "combination")
                allowed = self.expand(target, "naver_b", RECIPE)
                self.assertIn("API 연동", words(allowed))
                self.assertNotIn("API 연동", blocked(allowed))
                item = next(row for row in allowed.items if row.direction == "API 연동")
                self.assertEqual((item.source, item.family, item.keyword), ("channel", "howto", f"{keyword_for(PROFILES['naver_b'])} API 연동"))
                self.assertEqual(words(allowed), ["API 연동", "주의사항"], "그 밖의 허용(알아 두기)은 그대로고, 같은 하는 법 계열의 설치·설정·방법·순서·체크리스트·관리는 계속 막힌다")
                for word in ("설치", "설정", "방법", "순서", "체크리스트", "관리", "성능", "호환성", "오류 해결", "자동화 사례", "기준", "비교", "원인", "해결", "예방"):
                    self.assertEqual(blocked(allowed)[word].reason, "combination", word)

    def test_other_recipe_values_do_not_open_it(self):
        for value in ("tourapi", "TOURAPI_INTEGRATION", "TourAPI_integration", "tourapi-integration", " tourapi_integration", "tourapi_integration ", "other_recipe", "x", "0"):
            with self.subTest(recipe=value):
                result = self.expand("lodging", "naver_b", value)
                self.assertNotIn("API 연동", words(result))
                self.assertEqual(blocked(result)["API 연동"].reason, "combination")
                self.assertEqual(result, self.expand("lodging", "naver_b"), "모르는 Recipe 는 예외 없이 Recipe 를 안 준 것과 같은 결과다")

    def test_every_other_channel_blocks_it_even_with_the_recipe(self):
        for code in ("github_pages", "blogger_ko", "blogger_en", "naver_a"):
            for target in PLACE_TYPES:
                with self.subTest(channel=code, target=target):
                    result = self.expand(target, code, RECIPE)
                    self.assertNotIn("API 연동", words(result))
                    self.assertEqual(blocked(result)["API 연동"].reason, "combination")
                    self.assertEqual(result, self.expand(target, code), "예외에 없는 채널은 Recipe 를 줘도 같은 결과")

    def test_other_target_types_keep_their_old_result_for_api_integration_in_the_exception_channel(self):
        for target in BASELINE_ALLOWED:
            if target in PLACE_TYPES:
                continue
            for recipe in (None, RECIPE):
                with self.subTest(target=target, recipe=recipe):
                    result = self.expand(target, "naver_b", recipe)
                    self.assertEqual("API 연동" in words(result), "howto" in BASELINE_ALLOWED[target], "다른 대상 유형은 예외 없이 기본 허용표 그대로")
                    self.assertEqual(result, self.expand(target, "naver_b"), "Recipe 가 결과를 바꾸지 않는다")

    def test_the_block_message_is_unchanged_by_the_exception_rule(self):
        want = "‘숙박’ 대상에는 ‘API 연동’(하는 법 계열)을 붙이지 않습니다 — 뜻이 맞지 않는 조합입니다(이 대상에 어울리는 방향: 이동, 예약, 방문 전 확인, 계절, 숙박 조건, 주변 이용 정보)"
        for recipe in (None, "other_recipe"):
            found = blocked(self.expand("lodging", "naver_b", recipe))["API 연동"].detail
            self.assertEqual(found, want, "차단 이유 글은 예외 규칙이 생기기 전과 한 글자도 같다(Recipe 를 안 준 호출의 결과가 달라지지 않게)")
        self.assertTrue(notice.is_clean(want))

    def test_a_custom_profile_keeps_its_own_direction_order_with_the_exception_word(self):
        base = PROFILES["naver_b"]
        for order in (("API 연동", "방문 전 확인", "예약"), ("방문 전 확인", "API 연동", "예약"), ("예약", "방문 전 확인", "API 연동")):
            with self.subTest(order=order):
                custom = dataclasses.replace(base, expansion_directions=order)
                result = ex.expand(seed(target_type="lodging"), custom, limit=20, recipe=RECIPE)
                self.assertEqual(words(result), [*order, "주의사항"], "채널 방향이 먼저(프로필 순서 그대로), 공통 확장어가 그 뒤")
                self.assertEqual(words(ex.expand(seed(target_type="lodging"), custom, limit=20)), [word for word in order if word != "API 연동"] + ["주의사항"])


class EndToEndGridTest(unittest.TestCase):
    """`expand` 전체 — (대상 유형 14 × 채널 5 × Recipe 3) × 낱말 41개(프로필 한도 20 때문에 세 묶음으로 나눠 넣는다)의 결과가 독립 표의 기대와 같다(순서·상한·넘친 수까지)."""

    def chunks(self):
        order = list(KNOWN_WORD_FAMILY)
        return (order[:14], order[14:28], order[28:])

    def test_the_whole_expansion_equals_the_independent_expectation_cell_by_cell(self):
        checked = 0
        for target in BASELINE_ALLOWED:
            for code in CHANNEL_CODES:
                for recipe in (None, RECIPE, "other_recipe"):
                    for chunk in self.chunks():
                        profile = dataclasses.replace(PROFILES[code], expansion_directions=tuple(chunk))
                        made = seed(target_type=target, keyword=keyword_for(profile))
                        universe = list(chunk) + [word for word in COMMON_TEN if word not in chunk]
                        want = [word for word in universe if expected_allowed(target, code, recipe, word)]
                        got = ex.expand(made, profile, limit=20, recipe=recipe)
                        with self.subTest(target=target, channel=code, recipe=recipe, first=chunk[0]):
                            self.assertEqual(words(got), want[:20])
                            self.assertEqual(got.capped, max(0, len(want) - 20))
                            self.assertEqual({row.direction for row in got.blocked if row.reason == "combination"}, {word for word in universe if not expected_allowed(target, code, recipe, word)}
                                             - {row.direction for row in got.blocked if row.reason != "combination"})
                        checked += 1
        self.assertEqual(checked, 14 * 5 * 3 * 3)


class RecipeArgumentTest(unittest.TestCase):
    def test_a_recipe_that_is_not_text_is_a_type_error(self):
        made = seed(target_type="lodging")
        legacy = seed()
        for bad in (5, 0, 1.5, True, False, b"tourapi_integration", ["tourapi_integration"], ("tourapi_integration",), {"tourapi_integration"}, object()):
            for item in (made, legacy):
                with self.subTest(recipe=repr(bad), rule=ex.rule_of(item)):
                    with self.assertRaises(TypeError):
                        ex.expand(item, PROFILES["naver_b"], limit=20, recipe=bad)
            with self.assertRaises(TypeError):
                ex.clean_recipe(bad)

    def test_a_blank_recipe_is_the_same_as_none(self):
        for target in ("lodging", "product", "problem"):
            made = seed(target_type=target)
            plain = ex.expand(made, PROFILES["naver_b"], limit=20)
            for blank in (None, "", " ", "   ", "\t", "\n", "　"):
                with self.subTest(target=target, recipe=repr(blank)):
                    self.assertEqual(ex.expand(made, PROFILES["naver_b"], limit=20, recipe=blank), plain)
        self.assertIsNone(ex.clean_recipe(""))
        self.assertIsNone(ex.clean_recipe("  \t "))
        self.assertIsNone(ex.clean_recipe(None))

    def test_an_unknown_recipe_is_not_an_error_and_is_kept_as_it_is(self):
        for value in ("unknown_recipe", "한글 레시피", "a" * 500, "tourapi_integration2"):
            with self.subTest(recipe=value[:20]):
                self.assertEqual(ex.clean_recipe(value), value)
                self.assertEqual(ex.expand(seed(target_type="lodging"), PROFILES["naver_b"], limit=20, recipe=value), ex.expand(seed(target_type="lodging"), PROFILES["naver_b"], limit=20))
        self.assertEqual(ex.clean_recipe(" tourapi_integration"), " tourapi_integration", "다듬지 않는다 — 앞뒤 공백이 있으면 예외 표의 값과 다르다")

    def test_the_recipe_is_keyword_only(self):
        with self.assertRaises(TypeError):
            ex.expand(seed(target_type="lodging"), PROFILES["naver_b"], 20, None, RECIPE)

    def test_the_recipe_is_checked_before_anything_else_is_decided(self):
        with self.assertRaises(TypeError):
            ex.expand("not a seed", PROFILES["naver_b"], recipe=RECIPE)
        with self.assertRaises(ValueError):
            ex.expand(seed(target_type="lodging"), PROFILES["naver_b"], as_type="nope", recipe=RECIPE)
        with self.assertRaises(ValueError):
            ex.expand(seed(target_type="lodging"), PROFILES["naver_b"], limit=0, recipe=RECIPE)


class LegacySeedIgnoresTheRecipeTest(unittest.TestCase):
    """대상 유형이 없는 옛 씨앗은 recipe 를 줘도 결과가 같다 — 옛 규칙은 한 글자도 안 바뀐다(P3 지문은 `test_topics_legacy_rules`)."""

    def test_a_seed_without_a_target_type_gets_the_same_result_with_any_recipe(self):
        for minor in ("숙박", "지역", "소형가전"):
            for seed_type in ("general", "priority", "seasonal", "realtime"):
                made = seed(minor=minor, seed_type=seed_type, keyword="예시 호텔")
                self.assertEqual(ex.rule_of(made), ex.RULE_LEGACY)
                for code in CHANNEL_CODES:
                    profile = with_api(PROFILES[code])
                    plain = ex.expand(made, profile, limit=20)
                    for recipe in (RECIPE, "other_recipe", "", None):
                        with self.subTest(minor=minor, seed_type=seed_type, channel=code, recipe=recipe):
                            self.assertEqual(ex.expand(made, profile, limit=20, recipe=recipe), plain)
                            self.assertEqual(ex.expand(made, profile, recipe=recipe, as_type="sponsorable"), ex.expand(made, profile, as_type="sponsorable"))

    def test_the_legacy_rule_still_blocks_what_it_blocked_even_in_the_exception_channel(self):
        realtime = seed(seed_type="realtime", minor="숙박", keyword="예시 호텔")
        result = ex.expand(realtime, with_api(PROFILES["naver_b"]), limit=20, recipe=RECIPE)
        self.assertNotIn("API 연동", words(result), "옛 규칙의 실시간 씨앗은 하는 법 계열을 받지 않는다 — Recipe 가 있어도 같다")
        self.assertEqual(blocked(result)["API 연동"].reason, "combination")


class DeterminismTest(unittest.TestCase):
    def test_the_same_input_gives_the_same_output_in_any_call_order(self):
        pool = [seed(seed_id=f"ex-{index}", keyword=f"예시 숙소 {index}", target_type=target) for index, target in enumerate(sd.ALL_TARGET_TYPES)]
        profiles = [with_api(PROFILES[code]) for code in CHANNEL_CODES]
        forward = {(item.seed_id, profile.key, recipe): ex.expand(item, profile, limit=20, recipe=recipe) for item in pool for profile in profiles for recipe in (None, RECIPE)}
        backward = {(item.seed_id, profile.key, recipe): ex.expand(item, profile, limit=20, recipe=recipe) for item in reversed(pool) for profile in reversed(profiles) for recipe in (RECIPE, None)}
        self.assertEqual(forward, backward)
        first = ex.expand(pool[1], profiles[4], limit=20, recipe=RECIPE)
        ex.expand(pool[2], profiles[3], limit=20, recipe=RECIPE)
        self.assertEqual(ex.expand(pool[1], profiles[4], limit=20, recipe=RECIPE), first)
        self.assertEqual(words(first), ["API 연동", "주의사항"], "채널 방향 순서(설치·설정·API 연동 중 열린 것) → 공통 확장어 순서")

    def test_expansions_of_a_seed_never_repeat_an_intent_and_angle_pair_with_the_exception_open(self):
        for target in PLACE_TYPES:
            result = ex.expand(seed(target_type=target), PROFILES["naver_b"], limit=20, recipe=RECIPE)
            pairs = [(item.search_intent, item.angle) for item in result.items]
            self.assertEqual(len(pairs), len(set(pairs)))
            self.assertEqual(len({item.keyword for item in result.items}), len(result.items))

    def test_the_callers_do_not_pass_a_recipe_so_real_generation_is_unchanged(self):
        root = ts.TOPICS
        for name in ("generate.py", "brand.py", "channels.py", "seeds.py"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("recipe", text.lower(), f"{name} 이 Recipe 를 쓰기 시작했다 — Recipe 값의 출처는 공공데이터 프로젝트(PD0)가 정한다(DEFERRED). 의식적인 변경이면 이 시험과 결정 기록(D-121)을 함께 고친다")
        self.assertNotIn("recipe", " ".join(sd.Seed.__dataclass_fields__), "씨앗에는 Recipe 칸이 없다(씨앗 판 2 의 칸은 바뀌지 않았다)")


class MatrixFingerprintTest(unittest.TestCase):
    """(대상 유형 × 확장어) 전체 허용 행렬의 요약 지문 — 대상 유형마다 확장어 41개 중 몇 개가 허용되는가. 예외 표나 허용표가 바뀌면 이 표가 달라진다(빨개지면 '허용 행렬이 바뀌었다' 는 뜻 — 의도한 변경이면 이유를 적고 함께 고친다)."""
    PLAIN = {"product": 19, "place": 7, "lodging": 7, "place_lodging": 7, "service": 19, "saas": 19, "service_saas": 19, "pc_part": 19, "problem": 7, "life_habit": 20, "realtime_issue": 19,
             "policy": 17, "api": 17, "policy_api": 17}                                                       # 예외 없이(Recipe 없음 또는 예외 밖 채널)
    OPENED = {**PLAIN, "place": 8, "lodging": 8, "place_lodging": 8}                                          # 네이버 B + `tourapi_integration` — 장소·숙박 셋만 ‘API 연동’ 하나가 더 열린다
    TOTALS = {"plain_sum": 213, "opened_sum": 216, "grid_allowed_cells": 3198}                                # 합계, 그리고 14 × 5 × Recipe 3(없음·tourapi_integration·다른 값) × 41 칸 중 허용 칸 수

    def test_the_summary_counts_from_the_independent_tables_are_the_pinned_ones(self):
        plain, opened = matrix_counts()
        self.assertEqual(plain, self.PLAIN)
        self.assertEqual(opened, self.OPENED)
        self.assertEqual((sum(plain.values()), sum(opened.values())), (self.TOTALS["plain_sum"], self.TOTALS["opened_sum"]))
        grid = sum(expected_allowed(target, channel, recipe, word) for target in BASELINE_ALLOWED for channel in CHANNEL_CODES for recipe in (None, RECIPE, "other_recipe") for word in KNOWN_WORD_FAMILY)
        self.assertEqual(grid, self.TOTALS["grid_allowed_cells"])

    def test_the_code_produces_the_same_counts(self):
        for target in BASELINE_ALLOWED:
            plain = sum(ex.family_decision(target, "naver_a", None, direction_of(word)).allowed for word in KNOWN_WORD_FAMILY)
            opened = sum(ex.family_decision(target, "naver_b", RECIPE, direction_of(word)).allowed for word in KNOWN_WORD_FAMILY)
            with self.subTest(target=target):
                self.assertEqual((plain, opened), (self.PLAIN[target], self.OPENED[target]))
        without_recipe = {target: {sum(ex.family_decision(target, channel, None, direction_of(word)).allowed for word in KNOWN_WORD_FAMILY) for channel in CHANNEL_CODES} for target in BASELINE_ALLOWED}
        self.assertEqual(without_recipe, {target: {count} for target, count in self.PLAIN.items()}, "Recipe 가 없으면 어느 채널에서나 예외 없이 같은 개수")
        grid = sum(ex.family_decision(target, channel, recipe, direction_of(word)).allowed for target in BASELINE_ALLOWED for channel in CHANNEL_CODES for recipe in (None, RECIPE, "other_recipe")
                   for word in KNOWN_WORD_FAMILY)
        self.assertEqual(grid, self.TOTALS["grid_allowed_cells"])
        self.assertEqual(grid - 5 * 3 * self.TOTALS["plain_sum"], len(EXCEPTION_CELLS), "예외가 더 여는 칸은 정확히 예외 칸 목록뿐")


if __name__ == "__main__":
    unittest.main()
