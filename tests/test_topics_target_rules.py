"""확장어를 원문 기준으로, 대상 유형으로 허용 확장 정하기(P3b-1 S2) 시험 — 원문 §10.1 공통 확장어 10개(낱말·순서·표시)·§10.2 채널별 확장 방향·§10.3 대상 유형별 허용 확장을 **표 그대로** 못박고,
대상 유형이 있는 씨앗은 새 규칙·없는 씨앗은 옛 규칙으로 확장하는지, 뜻이 안 맞는 조합(숙박 × API 연동 · API × 방문 후기 · PC 부품 × 맛집 비교)이 이유와 함께 막히는지, 호출 순서와 상관없이 같은 결과인지 본다.

입력은 모두 시험용으로 지어낸 **예시** 씨앗이다. 옛 규칙의 결과가 안 바뀐 것은 `test_topics_legacy_rules` 가 지문으로 못박는다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import expand as ex  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import notice, seeds as sd  # noqa: E402

PROFILES = ts.PROFILES
A, B, GH, BK, BE = PROFILES["naver_a"], PROFILES["naver_b"], PROFILES["github_pages"], PROFILES["blogger_ko"], PROFILES["blogger_en"]

# 원문 §10.1 — 낱말·순서 그대로
STRATEGY_COMMON = ("방법", "순서", "기준", "비교", "원인", "해결", "주의사항", "체크리스트", "관리", "예방")
# 원문 §10.2 — 채널별 확장 방향(표 그대로 — 기본 채널 프로필의 `expansion_directions` 가 같은 값이어야 한다)
STRATEGY_CHANNEL = {
    "github_pages": ("변화", "영향", "배경", "산업·경제·사회적 맥락", "분야 연결"),
    "blogger_ko": ("정리", "습관", "반복 관리", "정보 관리", "생활 부담 줄이기"),
    "blogger_en": ("simple routine", "gentle reset", "low-pressure habit", "everyday checklist"),
    "naver_a": ("구매 기준", "제품 비교", "방문 전 확인", "지역·계절 체험", "관리 방법"),
    "naver_b": ("설치", "설정", "API 연동", "성능", "호환성", "오류 해결", "자동화 사례"),
}
# 원문 §10.3 — 대상 유형별 허용 확장(여덟 행, 낱말 그대로)
STRATEGY_TARGETS = {
    "product": ("선택 기준", "비교", "호환성", "관리", "구매 전 확인"),
    "place_lodging": ("이동", "예약", "방문 전 확인", "계절", "숙박 조건", "주변 이용 정보"),
    "service_saas": ("요금", "기능", "무료·유료 비교", "설정", "연동", "해지·이관"),
    "pc_part": ("성능", "호환성", "소비전력", "가격", "설치", "업그레이드"),
    "problem": ("원인", "점검", "해결", "예방", "지원이 필요한 조건"),
    "life_habit": ("단순화", "반복 루틴", "체크리스트", "유지 방법"),
    "realtime_issue": ("변화", "영향", "대응", "대안", "종료·이관"),
    "policy_api": ("적용 일정", "변경사항", "무료 한도", "인증", "마이그레이션"),
}


def seed(**changes):
    changes.setdefault("keyword", "예시 물건")
    return ts.example_seed(**changes)


def words(result):
    return [item.direction for item in result.items]


def blocked(result):
    return {item.direction: item for item in result.blocked}


class OriginalTablesTest(unittest.TestCase):
    def test_the_ten_common_words_are_exactly_the_original_in_the_original_order(self):
        self.assertEqual(ex.STRATEGY_COMMON_DIRECTIONS, STRATEGY_COMMON)
        self.assertEqual(len(ex.STRATEGY_COMMON_DIRECTIONS), 10)
        self.assertEqual(" ".join(ex.STRATEGY_COMMON_DIRECTIONS), "방법 순서 기준 비교 원인 해결 주의사항 체크리스트 관리 예방", "표시(낱말 모양)도 원문과 같다")

    def test_the_channel_directions_are_exactly_the_original_table(self):
        for code, expected in STRATEGY_CHANNEL.items():
            with self.subTest(channel=code):
                self.assertEqual(PROFILES[code].expansion_directions, expected)

    def test_the_target_rows_are_exactly_the_original_table(self):
        self.assertEqual({key: tuple(value) for key, value in ex.TARGET_EXPANSION_WORDS.items()}, STRATEGY_TARGETS)
        self.assertEqual(len(ex.TARGET_EXPANSION_WORDS), 8, "원문 §10.3 의 행은 여덟 개다")

    def test_eleven_target_types_and_three_bundles_each_use_one_row_and_have_at_least_one_family(self):
        self.assertEqual(set(ex.TARGET_ROW), set(sd.ALL_TARGET_TYPES))
        self.assertEqual(set(ex.TARGET_ROW.values()), set(STRATEGY_TARGETS))
        for key in sd.ALL_TARGET_TYPES:
            with self.subTest(target=key):
                self.assertTrue(ex.TARGET_ALLOWED_FAMILIES[key], "허용 확장이 한 개 이상")
                self.assertIn(ex.FAMILY_INFO, ex.TARGET_ALLOWED_FAMILIES[key], "알아 두기는 모든 대상 유형이 받는다(구현자 초기값)")
                self.assertTrue(set(ex.TARGET_ALLOWED_FAMILIES[key]) <= set(ex.FAMILIES))
        for lone, bundle in (("place", "place_lodging"), ("lodging", "place_lodging"), ("service", "service_saas"), ("saas", "service_saas"), ("policy", "policy_api"), ("api", "policy_api")):
            self.assertEqual(ex.TARGET_ALLOWED_FAMILIES[lone], ex.TARGET_ALLOWED_FAMILIES[bundle], "원문이 한 행으로 적은 것은 낱개와 묶음이 같은 허용 확장을 가진다")

    def test_every_original_word_has_a_family_and_nothing_extra(self):
        used = {word for row in STRATEGY_TARGETS.values() for word in row}
        self.assertEqual(set(ex.TARGET_WORD_FAMILY), used)
        self.assertTrue(all(family in ex.FAMILIES for family in ex.TARGET_WORD_FAMILY.values()))
        self.assertEqual(ex.TARGET_WORD_FAMILY["체크리스트"], ex.DIRECTIONS["체크리스트"].family, "같은 낱말은 어느 표에서든 같은 계열이다")
        self.assertEqual(ex.TARGET_WORD_FAMILY["비교"], ex.DIRECTIONS["비교"].family)

    def test_the_new_direction_rows_have_known_codes_and_unique_angles(self):
        for key, row in ex.STRATEGY_DIRECTIONS.items():
            self.assertIn(row.family, ex.FAMILIES)
            self.assertNotIn(key, ex.DIRECTIONS, "새 규칙에서만 아는 낱말이다 — 옛 표에 이미 있는 낱말을 다시 정의하지 않는다")
        angles = [row.angle for row in (*ex.DIRECTIONS.values(), *ex.STRATEGY_DIRECTIONS.values())]
        self.assertEqual(len(angles), len(set(angles)), "관점 식별자는 표 전체에서 겹치지 않는다(같은 씨앗의 후보 번호가 겹치지 않게)")
        for word in STRATEGY_COMMON:
            self.assertIn(ex.keyword_key(word), {*ex.DIRECTIONS, *ex.STRATEGY_DIRECTIONS}, "열 가지 공통 확장어 모두 계열이 정해져 있다")

    def test_the_legacy_tables_keep_their_old_names_and_values(self):
        self.assertEqual(ex.COMMON_DIRECTIONS, ("방법", "체크리스트", "비교", "주의할 점", "자주 묻는 질문", "비용"))
        self.assertIs(ex.COMMON_DIRECTIONS, ex.LEGACY_COMMON_DIRECTIONS)
        self.assertIs(ex.ALLOWED_FAMILIES, ex.LEGACY_ALLOWED_FAMILIES)
        self.assertEqual(tuple(ex.ALLOWED_FAMILIES), tuple(ch.PER_SEED))


class RuleSelectionTest(unittest.TestCase):
    def test_a_seed_without_a_target_type_uses_the_legacy_rule(self):
        plain = seed()
        self.assertEqual(ex.rule_of(plain), ex.RULE_LEGACY)
        self.assertEqual(words(ex.expand(plain, A, limit=20))[-3:], ["주의할 점", "자주 묻는 질문", "비용"], "옛 공통 확장어가 붙는다")
        self.assertIn("옛 규칙", ex.RULE_KO[ex.RULE_LEGACY])

    def test_a_seed_with_a_target_type_uses_the_original_common_words(self):
        made = seed(target_type="problem", scope="naver_b")
        self.assertEqual(ex.rule_of(made), ex.RULE_TARGET)
        result = ex.expand(made, B, limit=20)
        common = [item.direction for item in result.items if item.source == "common"]
        self.assertEqual(common, ["원인", "해결", "주의사항", "예방"], "문제 대상: 원문 공통 확장어 중 문제 해결 계열과 알아 두기만 — 원문 순서대로(원인·해결·주의사항·예방)")
        self.assertEqual([item.direction for item in result.items if item.source == "channel"], ["오류 해결"], "채널 방향 중 문제 해결 계열만 붙는다")

    def test_the_common_words_follow_the_channel_directions_in_the_original_order_without_repeats(self):
        made = seed(target_type="product", scope="naver_a")
        result = ex.expand(made, A, limit=20)
        found = words(result)
        self.assertEqual(found[:3], ["구매 기준", "제품 비교", "관리 방법"], "채널 방향이 먼저 붙는다")
        common = [item.direction for item in result.items if item.source == "common"]
        self.assertEqual(common, [word for word in STRATEGY_COMMON if word in common], "원문 순서를 지킨다")
        custom = dataclasses.replace(A, expansion_directions=("비교", "예시 새 낱말"))
        again = words(ex.expand(made, custom, limit=20))
        self.assertEqual(again.count("비교"), 1, "채널 방향에 있는 낱말은 공통 확장어로 다시 붙지 않는다")
        self.assertIn("예시 새 낱말", again, "표에 없는 새 낱말은 알아 두기 계열이라 모든 대상 유형이 받는다")

    def test_each_target_type_gets_at_least_one_expansion_on_every_default_channel(self):
        for key in sd.ALL_TARGET_TYPES:
            for code, profile in PROFILES.items():
                with self.subTest(target=key, channel=code):
                    korean = "example weekly note" if profile.language == "en" else "예시 물건"
                    found = ex.expand(seed(target_type=key, keyword=korean, scope="common"), profile, limit=20)
                    self.assertGreaterEqual(len(found.items), 1)

    def test_importance_still_decides_how_many_while_the_target_type_decides_which(self):
        for importance, count in (("general", 3), ("priority", 5)):
            made = seed(target_type="problem", seed_type=importance, scope="naver_b")
            self.assertEqual(len(ex.expand(made, B).items), min(count, len(ex.expand(made, B, limit=20).items)))
        general = ex.expand(seed(target_type="product", scope="naver_a"), A)
        self.assertEqual(len(general.items), 3)
        self.assertEqual(general.capped, len(ex.expand(seed(target_type="product", scope="naver_a"), A, limit=20).items) - 3)
        realtime = ex.expand(seed(target_type="product", seed_type="realtime", scope="naver_a"), A, limit=20)
        self.assertIn("구매 기준", words(realtime), "옛 규칙은 실시간 씨앗에 고르기 계열도 허용하지만, 새 규칙은 중요도가 아니라 대상 유형을 본다")
        self.assertIn("관리 방법", words(realtime), "옛 규칙이었다면 실시간 씨앗의 ‘관리 방법’ 은 막혔다 — 새 규칙은 대상 유형(제품)이 허용한다")

    def test_the_result_does_not_depend_on_the_order_of_calls(self):
        pool = [seed(seed_id=f"ex-{index}", keyword=f"예시 물건 {index}", target_type=key, scope="common") for index, key in enumerate(sd.ALL_TARGET_TYPES)]
        forward = [(item.seed_id, profile.key, ex.expand(item, profile, limit=20)) for item in pool for profile in PROFILES.values()]
        backward = [(item.seed_id, profile.key, ex.expand(item, profile, limit=20)) for item in reversed(pool) for profile in reversed(list(PROFILES.values()))]
        self.assertEqual(sorted(forward, key=lambda row: row[:2]), sorted(backward, key=lambda row: row[:2]))
        first = ex.expand(pool[0], A, limit=20)
        ex.expand(pool[3], B, limit=20)
        self.assertEqual(ex.expand(pool[0], A, limit=20), first)


class MismatchBlockTest(unittest.TestCase):
    def test_a_lodging_seed_is_not_combined_with_api_integration(self):
        lodging = seed(target_type="lodging", keyword="예시 숙소", scope="naver_b")
        result = ex.expand(lodging, B, limit=20)
        found = blocked(result)["API 연동"]
        self.assertEqual(found.reason, "combination")
        self.assertIn("숙박", found.detail)
        self.assertIn("API 연동", found.detail)
        self.assertIn("뜻이 맞지 않는 조합", found.detail)
        self.assertIn("예약", found.detail, "이 대상에 어울리는 방향(원문 낱말)을 쉬운 말로 보여 준다")
        self.assertNotIn("API 연동", words(result))
        self.assertIn("방문 전 확인", words(ex.expand(lodging, A, limit=20)), "맞는 조합은 그대로 나온다")

    def test_an_api_seed_is_not_combined_with_a_visit_review(self):
        hub = dataclasses.replace(B, expansion_directions=("방문 후기", "API 연동", "설정"))
        for key in ("api", "policy", "policy_api", "service", "saas"):
            with self.subTest(target=key):
                result = ex.expand(seed(target_type=key, keyword="예시 API 허브", scope="naver_b"), hub, limit=20)
                self.assertEqual(blocked(result)["방문 후기"].reason, "combination")
                self.assertNotIn("방문 후기", words(result))
                self.assertIn("방문 후기", blocked(result)["방문 후기"].detail)

    def test_a_pc_part_seed_is_not_combined_with_a_restaurant_comparison(self):
        gpu = dataclasses.replace(B, expansion_directions=("맛집 비교", "성능", "설치"))
        for key in ("pc_part",):
            result = ex.expand(seed(target_type=key, keyword="예시 GPU 카드", scope="naver_b"), gpu, limit=20)
            self.assertEqual(blocked(result)["맛집 비교"].reason, "combination")
            self.assertIn("PC 부품", blocked(result)["맛집 비교"].detail)
            self.assertEqual([item.direction for item in result.items if item.source == "channel"], ["성능", "설치"])

    def test_the_block_never_changes_the_seed_and_the_block_message_is_clean_korean(self):
        lodging = seed(target_type="lodging", keyword="예시 숙소", scope="naver_b")
        before = lodging.to_dict()
        result = ex.expand(lodging, B, limit=20)
        self.assertEqual(lodging.to_dict(), before, "씨앗을 지우거나 바꾸지 않는다")
        for item in result.blocked:
            self.assertTrue(notice.is_clean(item.detail), item.detail)
            self.assertFalse(notice.leaks(item.detail), item.detail)
        self.assertIn("‘숙박’", result.blocked[0].detail)
        self.assertNotIn("lodging", " ".join(item.detail for item in result.blocked))

    def test_place_directions_are_allowed_for_place_types_even_in_a_non_place_cluster(self):
        made = seed(target_type="place_lodging", keyword="예시 나들이", major="전자", minor="가전", scope="naver_a")
        self.assertIn("방문 전 확인", words(ex.expand(made, A, limit=20)), "새 규칙은 묶음 이름이 아니라 대상 유형이 장소 방향을 허용한다")
        legacy = seed(keyword="예시 나들이", major="전자", minor="가전", scope="naver_a")
        self.assertNotIn("방문 전 확인", words(ex.expand(legacy, A, limit=20)), "옛 규칙은 장소 묶음이 아니면 장소 방향을 막는다(그대로)")

    def test_other_blocks_still_apply_under_the_new_rule(self):
        self.assertEqual(blocked(ex.expand(seed(target_type="product", excluded_keywords=("비교",), scope="naver_a"), A, limit=20))["제품 비교"].reason, "excluded_keyword")
        korean_on_english = ex.expand(seed(target_type="life_habit", scope="common"), BE, limit=20)
        self.assertEqual(korean_on_english.items, ())
        self.assertTrue(all(item.reason in ("language", "combination") for item in korean_on_english.blocked))
        long_seed = ex.expand(seed(target_type="product", keyword="가" * 58, scope="naver_a"), A, limit=20)
        self.assertTrue(any(item.reason == "too_long" for item in long_seed.blocked))


class GenerateWithTargetTypesTest(unittest.TestCase):
    TODAY = "2026-11-10"

    def test_target_type_seeds_become_candidates_through_the_new_rule(self):
        pool = (seed(seed_id="ex-t1", keyword="예시 숙소", target_type="lodging", scope="naver_b"), seed(seed_id="ex-t2", keyword="예시 GPU 카드", target_type="pc_part", scope="naver_b"),
                seed(seed_id="ex-t3", keyword="예시 설정 문제", target_type="problem", scope="naver_b"))
        for item in pool:
            self.assertEqual(ex.rule_of(item), ex.RULE_TARGET)
        found = gn.generate(B, pool, (), (), self.TODAY, target=20)
        topics = {candidate.seed_id: [] for candidate in found.candidates}
        for candidate in found.candidates:
            topics[candidate.seed_id].append(candidate.primary_keyword)
        self.assertEqual(set(topics), {"ex-t1", "ex-t2", "ex-t3"})
        self.assertFalse([word for word in topics["ex-t1"] if "API 연동" in word], "숙박 씨앗은 API 연동 후보를 만들지 않는다")
        self.assertTrue([word for word in topics["ex-t2"] if "설치" in word or "성능" in word])
        reasons = [row.reason for row in found.dropped]
        self.assertIn("combination", reasons, "차단은 후보를 만들지 않고 이유를 센다")
        ids = [candidate.candidate_id for candidate in found.candidates]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(gn.generate(B, tuple(reversed(pool)), (), (), self.TODAY, target=20).candidates, found.candidates, "씨앗 순서와 상관없이 같은 후보")


if __name__ == "__main__":
    unittest.main()
