"""씨앗 → 확장 키워드(`topics/expand.py`) 시험 — 방향 낱말 표(초기값), 씨앗 유형별 허용 조합표, 막은 이유, 제외 키워드, 상한, 주제 묶음 식별자, 안정된 해시.

지키는 것:
  1) **표는 초기값이다 — 전략 원문 확인 전.** 방향 낱말 32개(계열·검색 의도·글 종류·관점)·공통 확장어 6개·씨앗 유형별 허용 계열·주제 묶음 이름표를 이 시험이 손으로 쓴 값과 같은지 못박는다 —
     원문에 맞춰 표를 고칠 때는 `expand.py` 한 곳과 이 시험의 같은 표를 의식적으로 함께 고친다.
  2) 확장은 채널 프로필의 방향 낱말 → 공통 확장어 순서로 같은 입력에 늘 같은 순서이고, 뜻이 안 맞는 조합·제외 키워드·너무 긴 키워드·영문 채널의 한글 씨앗은 후보가 되지 않고 **사유를 값으로** 돌려준다.
  3) 씨앗 하나에서 만드는 확장 수의 상한은 `channels.PER_SEED` 의 '처음 만들 후보 수' 이고 넘는 것은 세기만 한다. 씨앗·프로필은 바뀌지 않는다.
네트워크·파일·실제 시계·난수 없이 돈다. 시험 씨앗은 모두 '예시' 로 시작하는 지어낸 낱말이다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.content.candidates import keyword_key  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import expand as ex  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402

A, B = ts.PROFILES["naver_a"], ts.PROFILES["naver_b"]
# 손으로 쓴 기댓값(초기값 표) — (방향 낱말, 계열, 검색 의도, 글 종류, 관점)
EXPECTED_ROWS = (
    ("구매 기준", "choose", "selection_guide", "buying_guide", "buying-criteria"), ("제품 비교", "choose", "comparison", "comparison", "product-comparison"),
    ("성능", "choose", "comparison", "comparison", "performance"), ("호환성", "choose", "selection_guide", "checklist", "compatibility"),
    ("설치", "howto", "how_to", "how_to_guide", "installation"), ("설정", "howto", "how_to", "how_to_guide", "settings"), ("API 연동", "howto", "how_to", "how_to_guide", "api-integration"),
    ("관리 방법", "howto", "how_to", "how_to_guide", "care-method"), ("정보 관리", "howto", "how_to", "how_to_guide", "info-management"),
    ("오류 해결", "fix", "problem_solving", "troubleshooting", "troubleshooting"), ("변화", "context", "context_explainer", "news_analysis", "what-changed"),
    ("영향", "context", "context_explainer", "news_analysis", "impact"), ("배경", "context", "context_explainer", "explainer", "background"),
    ("산업·경제·사회적 맥락", "context", "context_explainer", "news_analysis", "wider-context"), ("분야 연결", "context", "context_explainer", "explainer", "cross-field"),
    ("방문 전 확인", "place", "local_info", "place_guide", "before-visit"), ("지역·계절 체험", "place", "local_info", "place_guide", "local-season"),
    ("정리", "habit", "routine_building", "routine_plan", "organizing"), ("습관", "habit", "routine_building", "routine_plan", "habit-building"),
    ("반복 관리", "habit", "routine_building", "checklist", "recurring-care"), ("생활 부담 줄이기", "habit", "routine_building", "routine_plan", "lighten-load"),
    ("simple routine", "habit", "routine_building", "routine_plan", "simple-routine"), ("gentle reset", "habit", "routine_building", "routine_plan", "gentle-reset"),
    ("low-pressure habit", "habit", "routine_building", "routine_plan", "low-pressure-habit"), ("everyday checklist", "habit", "routine_building", "checklist", "everyday-checklist"),
    ("자동화 사례", "case", "information", "dev_log", "automation-case"), ("방법", "howto", "how_to", "how_to_guide", "method"), ("체크리스트", "howto", "how_to", "checklist", "checklist"),
    ("비교", "choose", "comparison", "comparison", "comparison"), ("비용", "choose", "selection_guide", "buying_guide", "cost"), ("주의할 점", "info", "information", "explainer", "cautions"),
    ("자주 묻는 질문", "info", "information", "explainer", "faq"),
)
EXPECTED_ALLOWED = {
    "general": ("choose", "howto", "fix", "context", "place", "habit", "case", "info"), "priority": ("choose", "howto", "fix", "context", "place", "habit", "case", "info"),
    "seasonal": ("choose", "howto", "place", "habit", "info"), "realtime": ("choose", "fix", "context", "info"), "sponsorable": ("choose", "howto", "place", "case", "info"),
}


def seed(**changes):
    return ts.example_seed(**changes)


def words(result):
    return [item.direction for item in result.items]


def fnv(text):
    """손으로 쓴 FNV-1a 64비트(시험용 참조 구현)."""
    value = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        value = ((value ^ byte) * 0x100000001B3) % (1 << 64)
    return f"{value:016x}"


class InitialTablesTest(unittest.TestCase):
    def test_the_module_says_which_tables_come_from_the_strategy_original_and_which_are_implementer_initial_values(self):
        # P3b-1 의도적 갱신: 전략 원문 대조가 끝났다(2026-11-06) — 새 규칙의 표는 원문 §10.1·§10.3 에서 옮긴 것이고, 옛 규칙의 표(`DIRECTIONS`·`LEGACY_*`)와 `CLUSTER_LABELS` 는 구현자 초기값이다. 머리말이 그것을 사실대로 말한다.
        text = Path(ex.__file__).read_text(encoding="utf-8")
        doc = text.split('"""', 2)[1]
        self.assertIn("구현자 초기값", doc)
        self.assertNotIn("전략 원문 확인 전", doc, "더 이상 '원문 확인 전' 이 아니다")
        for name in ("STRATEGY_COMMON_DIRECTIONS", "TARGET_EXPANSION_WORDS", "TARGET_ALLOWED_FAMILIES", "TARGET_WORD_FAMILY", "LEGACY_COMMON_DIRECTIONS", "LEGACY_ALLOWED_FAMILIES", "원문 §10.1", "원문 §10.3"):
            self.assertIn(name, doc, name)
        self.assertIn("옛 규칙", doc)

    def test_the_families_and_their_plain_korean_names(self):
        self.assertEqual(ex.FAMILIES, ("choose", "howto", "fix", "context", "place", "habit", "case", "info"))
        self.assertEqual(dict(ex.FAMILY_KO), {"choose": "고르기·비교", "howto": "하는 법", "fix": "문제 해결", "context": "배경·영향", "place": "장소·방문", "habit": "습관·정리", "case": "사례", "info": "알아 두기"})
        self.assertEqual(dict(ex.SEED_TYPE_KO), {"general": "일반", "priority": "우선", "seasonal": "계절", "realtime": "실시간", "sponsorable": "협찬 가능"})

    def test_the_direction_table_is_exactly_these_rows(self):
        self.assertEqual(len(ex.DIRECTIONS), len(EXPECTED_ROWS))
        for row in EXPECTED_ROWS:
            with self.subTest(word=row[0]):
                found = ex.DIRECTIONS[keyword_key(row[0])]
                self.assertEqual(tuple(found[:5]), row)
                self.assertTrue(found.known)

    def test_every_row_uses_the_closed_lists_of_the_candidate_model_and_valid_identifiers(self):
        angles = set()
        for word, family, intent, content_type, angle in EXPECTED_ROWS:
            with self.subTest(word=word):
                self.assertIn(family, ex.FAMILIES)
                self.assertIn(intent, md.SEARCH_INTENTS)
                self.assertIn(content_type, md.CONTENT_TYPES)
                self.assertTrue(ch.is_slug(angle))
                angles.add(angle)
        self.assertEqual(len(angles), len(EXPECTED_ROWS), "관점 식별자는 방향 낱말마다 다르다")

    def test_the_common_directions_and_the_allowed_families_per_seed_type_are_exactly_these(self):
        self.assertEqual(ex.COMMON_DIRECTIONS, ("방법", "체크리스트", "비교", "주의할 점", "자주 묻는 질문", "비용"))
        self.assertEqual({name: tuple(value) for name, value in ex.ALLOWED_FAMILIES.items()}, EXPECTED_ALLOWED)
        self.assertEqual(tuple(ex.ALLOWED_FAMILIES), ch.PER_SEED and tuple(ch.PER_SEED), "씨앗 유형 다섯이 `channels.PER_SEED` 와 같은 이름·순서다")
        for word in ex.COMMON_DIRECTIONS:
            self.assertIn(keyword_key(word), ex.DIRECTIONS)

    def test_every_default_profile_direction_word_is_in_the_table(self):
        for profile in ch.default_profiles():
            for word in profile.expansion_directions:
                with self.subTest(channel=profile.key, word=word):
                    self.assertTrue(ex.direction_of(word).known)

    def test_the_cluster_label_table_is_exactly_these_names_and_covers_every_default_cluster(self):
        self.assertEqual(len(ex.CLUSTER_LABELS), 33, "기본 프로필 다섯의 주제 묶음(겹치는 `personal-productivity` 하나 포함 33가지)")
        self.assertEqual(ex.CLUSTER_LABELS["small-appliances"], ("소형가전", "가전"))
        self.assertEqual(ex.CLUSTER_LABELS["local-ai"], ("로컬 AI",))
        self.assertEqual(ex.CLUSTER_LABELS["household-budget"], ("가계부", "생활비"))
        self.assertEqual(ex.CLUSTER_LABELS["meal-planning"], ("meal planning",))
        for profile in ch.default_profiles():
            for slug in profile.topic_clusters:
                with self.subTest(channel=profile.key, cluster=slug):
                    self.assertIn(slug, ex.CLUSTER_LABELS)
        self.assertTrue(all(ch.is_slug(slug) for slug in ex.CLUSTER_LABELS))
        self.assertEqual(ex.PLACE_CLUSTERS, ("lodging-and-travel", "local-places"))


class StableIdTest(unittest.TestCase):
    def test_it_is_the_standard_fnv_1a_64_bit_hash_so_the_ids_never_depend_on_the_python_run(self):
        self.assertEqual(ex.stable_id(""), "cbf29ce484222325")
        self.assertEqual(ex.stable_id("a"), "af63dc4c8601ec8c")
        self.assertEqual(ex.stable_id("foobar"), "85944171f73967e8")
        for parts in (("가", "나"), ("naver_a", "seed", "s1", "buying-criteria", "구매 기준"), ("x",) * 5, ("", "a"), ("a", "")):
            with self.subTest(parts=parts):
                self.assertEqual(ex.stable_id(*parts), fnv(chr(0x1F).join(parts)))

    def test_the_parts_are_separated_and_their_order_counts(self):
        self.assertNotEqual(ex.stable_id("ab", "c"), ex.stable_id("a", "bc"))
        self.assertNotEqual(ex.stable_id("a", "b"), ex.stable_id("b", "a"))
        self.assertNotEqual(ex.stable_id("a", "b"), ex.stable_id("ab"))
        self.assertEqual(ex.stable_id("a", 1), ex.stable_id("a", "1"), "숫자는 글로 바꿔 쓴다")

    def test_the_number_of_digits_can_be_chosen_and_the_result_is_lowercase_hex(self):
        full = ex.stable_id("a", "b")
        self.assertEqual((len(full), ex.stable_id("a", "b", digits=8), len(ex.stable_id("a", digits=1))), (16, full[:8], 1))
        self.assertRegex(full, "^[0-9a-f]{16}$")


class DirectionOfTest(unittest.TestCase):
    def test_a_known_word_keeps_the_spelling_that_was_given_and_the_table_values(self):
        found = ex.direction_of("구매  기준".replace("  ", " "))
        self.assertEqual(tuple(found), ("구매 기준", "choose", "selection_guide", "buying_guide", "buying-criteria", True))
        spaced = ex.direction_of("구매기준")
        self.assertEqual((spaced.word, spaced.family, spaced.known), ("구매기준", "choose", True), "띄어쓰기가 달라도 같은 낱말이다(키워드 열쇠로 찾는다)")
        self.assertEqual(ex.direction_of("EVERYDAY Checklist").angle, "everyday-checklist", "대소문자도 가리지 않는다")

    def test_an_unknown_word_is_a_general_explanation_with_a_stable_custom_angle(self):
        found = ex.direction_of("새로 적은 방향")
        self.assertEqual((found.word, found.family, found.search_intent, found.content_type, found.known), ("새로 적은 방향", "info", "information", "explainer", False))
        self.assertTrue(found.angle.startswith("custom-") and ch.is_slug(found.angle))
        self.assertEqual(found.angle, ex.direction_of("새로 적은 방향").angle)
        self.assertNotEqual(found.angle, ex.direction_of("또 다른 방향").angle)
        self.assertEqual(found.angle, "custom-" + ex.stable_id("direction", keyword_key("새로 적은 방향"), digits=8))


class ExpandTest(unittest.TestCase):
    def test_a_general_naver_a_product_seed_gets_the_first_three_allowed_directions_and_the_rest_are_counted(self):
        result = ex.expand(seed(keyword="예시 로봇청소기", major="가전", minor="소형가전"), A)
        self.assertEqual(words(result), ["구매 기준", "제품 비교", "관리 방법"])
        self.assertEqual([(item.family, item.source) for item in result.items], [("choose", "channel"), ("choose", "channel"), ("howto", "channel")])
        self.assertEqual([(blocked.direction, blocked.reason) for blocked in result.blocked], [("방문 전 확인", "combination"), ("지역·계절 체험", "combination")])
        self.assertEqual(result.capped, 6, "남은 확장(방법·체크리스트·비교·주의할 점·자주 묻는 질문·비용)은 상한 3 을 넘어 세기만 한다")
        self.assertEqual(result.items[0], ex.Expansion("ex-seed-001", "구매 기준", "channel", "choose", "예시 로봇청소기 구매 기준", "selection_guide", "buying_guide", "buying-criteria"))

    def test_without_a_limit_the_channel_words_come_first_then_the_common_words_each_once(self):
        result = ex.expand(seed(keyword="예시 호텔", major="여행", minor="숙박"), A, limit=20)
        self.assertEqual(words(result), ["구매 기준", "제품 비교", "방문 전 확인", "지역·계절 체험", "관리 방법", "방법", "체크리스트", "비교", "주의할 점", "자주 묻는 질문", "비용"])
        self.assertEqual([item.source for item in result.items], ["channel"] * 5 + ["common"] * 6)
        self.assertEqual((result.blocked, result.capped), ((), 0))
        self.assertEqual(len({keyword_key(item.keyword) for item in result.items}), len(result.items))

    def test_a_word_that_is_both_a_channel_word_and_a_common_word_is_used_once_as_the_channel_word(self):
        profile = ts.PROFILES["naver_b"]
        import dataclasses
        mixed = dataclasses.replace(profile, expansion_directions=("방법", "설치", "비교"))
        result = ex.expand(seed(), mixed, limit=20)
        self.assertEqual(words(result), ["방법", "설치", "비교", "체크리스트", "주의할 점", "자주 묻는 질문", "비용"])
        self.assertEqual([item.source for item in result.items][:3], ["channel", "channel", "channel"])

    def test_the_default_limit_follows_the_per_seed_table_of_the_seed_type(self):
        for seed_type, quota in ch.PER_SEED.items():
            extra = {"sponsor_tag": "pc_parts"} if seed_type == "sponsorable" else {}
            with self.subTest(seed_type=seed_type):
                result = ex.expand(seed(seed_type=seed_type, **extra), B)
                self.assertLessEqual(len(result.items), quota.first)
                if seed_type != "realtime":
                    self.assertEqual(len(result.items), quota.first)
        self.assertEqual(len(ex.expand(seed(seed_type="general"), B).items), 3)
        self.assertEqual(len(ex.expand(seed(seed_type="priority"), B).items), 5)

    def test_the_cap_counts_only_the_expansions_that_would_otherwise_have_been_used(self):
        capped = ex.expand(seed(), B, limit=2)
        self.assertEqual((len(capped.items), capped.capped), (2, 11))
        full = ex.expand(seed(), B, limit=20)
        self.assertEqual((len(full.items), full.capped), (13, 0))
        self.assertEqual(words(capped), words(full)[:2], "상한은 앞에서부터 자른다")

    def test_the_allowed_families_of_each_seed_type_decide_what_is_blocked_and_the_reason_is_plain_korean(self):
        for seed_type, allowed in EXPECTED_ALLOWED.items():
            extra = {"sponsor_tag": "pc_parts"} if seed_type == "sponsorable" else {}
            for profile in ch.default_profiles():
                result = ex.expand(seed(seed_type=seed_type, major="PC", minor="PC 부품", **extra), profile, limit=20)
                with self.subTest(seed_type=seed_type, channel=profile.key):
                    self.assertTrue(all(item.family in allowed for item in result.items))
                    for blocked in result.blocked:
                        if blocked.reason == "combination" and blocked.direction not in ("방문 전 확인", "지역·계절 체험"):
                            self.assertNotIn(ex.direction_of(blocked.direction).family, allowed)
                            self.assertIn(f"‘{ex.SEED_TYPE_KO[seed_type]}’ 씨앗에는 ‘{blocked.direction}’", blocked.detail)
                            self.assertIn("뜻이 맞지 않는 조합", blocked.detail)

    def test_a_realtime_seed_does_not_get_how_to_or_visit_directions_and_a_sponsorable_one_does_not_get_fix_or_context(self):
        realtime = ex.expand(seed(seed_type="realtime"), B, limit=20)
        self.assertEqual(words(realtime), ["성능", "호환성", "오류 해결", "비교", "주의할 점", "자주 묻는 질문", "비용"])
        self.assertEqual([item.direction for item in ex.expand(seed(seed_type="realtime"), B, limit=20).blocked], ["설치", "설정", "API 연동", "자동화 사례", "방법", "체크리스트"])
        sponsor = ex.expand(seed(seed_type="sponsorable", sponsor_tag="pc_parts"), B, limit=20)
        self.assertNotIn("오류 해결", words(sponsor))
        self.assertIn("자동화 사례", words(sponsor))
        github = ex.expand(seed(seed_type="seasonal"), ts.PROFILES["github_pages"], limit=20)
        self.assertEqual(words(github), ["방법", "체크리스트", "비교", "주의할 점", "자주 묻는 질문", "비용"], "배경·영향 계열은 계절 씨앗에 붙이지 않는다")

    def test_as_type_treats_the_seed_as_another_type_for_the_allowed_families_and_the_limit(self):
        plain = seed(seed_type="general", sponsor_tag="pc_parts")
        as_sponsor = ex.expand(plain, B, as_type="sponsorable")
        self.assertEqual(len(as_sponsor.items), 5)
        self.assertNotIn("오류 해결", words(ex.expand(plain, B, limit=20, as_type="sponsorable")))
        self.assertIn("오류 해결", words(ex.expand(plain, B, limit=20)))
        self.assertIn("‘협찬 가능’", [blocked.detail for blocked in ex.expand(plain, B, limit=20, as_type="sponsorable").blocked][0])
        for bad in ("Sponsorable", "other", 3, ""):
            with self.subTest(as_type=bad):
                with self.assertRaises(ValueError):
                    ex.expand(plain, B, as_type=bad)

    def test_the_place_directions_go_only_to_place_clusters_or_to_seeds_whose_cluster_is_unknown(self):
        product = ex.expand(seed(keyword="예시 청소기", major="가전", minor="소형가전"), A, limit=20)
        self.assertNotIn("방문 전 확인", words(product))
        self.assertIn("관리 방법", words(product))
        blocked = {item.direction: item for item in product.blocked}
        self.assertEqual(set(blocked), {"방문 전 확인", "지역·계절 체험"})
        self.assertIn("소형가전", blocked["방문 전 확인"].detail)           # P2b 보완: 묶음 식별자 대신 쉬운 한국어 이름
        self.assertIn("장소를 다루는 묶음", blocked["방문 전 확인"].detail)
        for minor, expected in (("숙박", True), ("지역 정보", True), ("맛집", True), ("모르는 분류", True), ("소형가전", False), ("PC 주변기기", False)):
            with self.subTest(minor=minor):
                got = "방문 전 확인" in words(ex.expand(seed(major="분류", minor=minor), A, limit=20))
                self.assertEqual(got, expected)

    def test_an_excluded_keyword_blocks_the_expansions_that_contain_it_and_says_which_word(self):
        result = ex.expand(seed(excluded_keywords=("비용",)), B, limit=20)
        self.assertNotIn("비용", words(result))
        self.assertEqual([(item.direction, item.reason) for item in result.blocked], [("비용", "excluded_keyword")])
        self.assertEqual(result.blocked[0].detail, "씨앗의 제외 키워드 ‘비용’ 이(가) 들어 있어 쓰지 않습니다")
        inside = ex.expand(seed(keyword="예시 중고 청소기", excluded_keywords=("중고",)), B, limit=20)
        self.assertEqual((inside.items, {item.reason for item in inside.blocked}), ((), {"excluded_keyword"}), "씨앗 낱말 자체에 제외 키워드가 있으면 모든 확장이 막힌다")
        spaced = ex.expand(seed(keyword="예시 청소기", excluded_keywords=("체크 리스트",)), B, limit=20)
        self.assertNotIn("체크리스트", words(spaced), "띄어쓰기·대소문자 차이는 같은 낱말이다")
        self.assertEqual(words(ex.expand(seed(excluded_keywords=("없는말",)), B, limit=20)), words(ex.expand(seed(), B, limit=20)))

    def test_a_keyword_longer_than_sixty_characters_is_blocked_and_sixty_exactly_is_fine(self):
        exact = "가" * 56 + " 설치"                      # 56 + 공백 1 + 설치 2 = 59 → 방향 '설치' 는 되고 '구매 기준'(5자) 은 62 자라 막힌다
        result = ex.expand(seed(keyword="가" * 56), B, limit=20)
        self.assertIn("설치", words(result))
        self.assertEqual(len(exact), 59)
        long_blocked = [item for item in result.blocked if item.reason == "too_long"]
        self.assertTrue(long_blocked)
        self.assertEqual(long_blocked[0].detail, "확장한 키워드가 60자를 넘어 쓰지 않습니다")
        edge = ex.expand(seed(keyword="가" * 57), B, limit=20)             # 57 + 1 + 2('설치') = 60 → 되고, 3자 방향 '설정'(2자)도 된다 · '방법'(2자) 도 된다
        self.assertIn("설치", words(edge))
        self.assertTrue(all(len(item.keyword) <= 60 for item in edge.items))
        over = ex.expand(seed(keyword="가" * 58), B, limit=20)             # 58 + 1 + 2 = 61 → 모두 막힌다
        self.assertEqual(over.items, ())

    def test_an_english_channel_refuses_a_korean_seed_word_and_accepts_an_english_one(self):
        import dataclasses
        english = dataclasses.replace(ts.PROFILES["blogger_en"], generation_enabled=True)
        korean = ex.expand(seed(keyword="예시 정리"), english, limit=20)
        self.assertEqual(korean.items, ())
        self.assertEqual({item.reason for item in korean.blocked}, {"language"})
        self.assertIn("영문 채널(Blogger 영문)", korean.blocked[0].detail)
        good = ex.expand(seed(keyword="sample morning routine"), english, limit=20)
        self.assertEqual(words(good)[:4], ["simple routine", "gentle reset", "low-pressure habit", "everyday checklist"])
        self.assertNotIn("language", {item.reason for item in good.blocked})
        self.assertEqual(ex.expand(seed(keyword="예시 정리"), B, limit=1).items[0].direction, "설치", "한국어 채널은 한글 씨앗을 받는다")

    def test_the_order_of_the_checks_is_combination_then_place_then_language_then_excluded_then_length(self):
        import dataclasses
        english = dataclasses.replace(ts.PROFILES["blogger_en"], generation_enabled=True)
        result = ex.expand(seed(keyword="예시 정리", seed_type="realtime", excluded_keywords=("정리",)), english, limit=20)
        self.assertEqual({item.reason for item in result.blocked if item.direction == "simple routine"}, {"combination"})
        self.assertEqual({item.reason for item in result.blocked if item.direction == "방법"}, {"combination"})
        self.assertEqual({item.reason for item in result.blocked if item.direction == "비교"}, {"language"})

    def test_it_does_not_look_at_the_state_and_changes_nothing_and_gives_the_same_answer_every_time(self):
        for state in ("active", "inactive", "proposed"):
            with self.subTest(state=state):
                self.assertEqual(ex.expand(seed(state=state), B), ex.expand(seed(), B))
        made = seed(excluded_keywords=("비용",))
        before = made.to_dict()
        first = ex.expand(made, A, limit=7)
        self.assertEqual(made.to_dict(), before)
        self.assertEqual(first, ex.expand(made, A, limit=7))

    def test_wrong_inputs_are_programming_errors(self):
        for args in ((None, B), (seed(), None), (seed().to_dict(), B), (seed(), "naver_b")):
            with self.subTest(args=repr(args)[:24]):
                with self.assertRaises(TypeError):
                    ex.expand(*args)
        for bad in (0, -1, 21, True, 2.0, "3"):
            with self.subTest(limit=bad):
                with self.assertRaises(ValueError):
                    ex.expand(seed(), B, limit=bad)
        self.assertEqual(len(ex.expand(seed(), B, limit=1).items), 1)
        self.assertEqual(len(ex.expand(seed(), B, limit=20).items), 13)


class ClusterOfTest(unittest.TestCase):
    def test_the_middle_category_name_in_the_label_table_gives_that_clusters_identifier(self):
        self.assertEqual(ex.cluster_of(seed(major="가전", minor="소형가전"), A), "small-appliances")
        self.assertEqual(ex.cluster_of(seed(minor="PC 주변기기"), A), "pc-peripherals")
        self.assertEqual(ex.cluster_of(seed(minor="pc주변기기"), A), "pc-peripherals", "띄어쓰기·대소문자 차이는 같은 이름이다")
        self.assertEqual(ex.cluster_of(seed(minor="로컬 AI"), B), "local-ai")

    def test_the_big_category_is_used_when_the_middle_one_is_not_in_the_table_and_the_middle_one_wins_when_both_are(self):
        self.assertEqual(ex.cluster_of(seed(major="소형가전", minor="모르는 이름"), A), "small-appliances")
        self.assertEqual(ex.cluster_of(seed(major="소형가전", minor="PC 주변기기"), A), "pc-peripherals")

    def test_the_identifier_must_belong_to_the_channels_own_clusters(self):
        found = ex.cluster_of(seed(minor="소형가전"), B)                       # 소형가전 은 네이버 B 의 묶음이 아니다
        self.assertTrue(found.startswith("seed-"))
        self.assertEqual(ex.cluster_of(seed(minor="소형가전"), A), "small-appliances")

    def test_an_unknown_name_gets_a_temporary_identifier_that_is_the_same_for_the_same_middle_category(self):
        first, second = ex.cluster_of(seed(seed_id="s1", minor="모르는 분류"), A), ex.cluster_of(seed(seed_id="s2", keyword="예시 다른 씨앗", minor="모르는 분류"), A)
        self.assertEqual(first, second)
        self.assertEqual(first, "seed-" + ex.stable_id("cluster", keyword_key("모르는 분류"), digits=8))
        self.assertNotEqual(first, ex.cluster_of(seed(minor="또 모르는 분류"), A))
        self.assertTrue(ch.is_slug(first))
        self.assertEqual(ex.cluster_of(seed(major="큰 분류", minor="!!!"), A), "seed-" + ex.stable_id("cluster", keyword_key("큰 분류"), digits=8), "중분류에 글자가 없으면 대분류 이름으로 정한다")

    def test_wrong_inputs_are_programming_errors(self):
        for args in ((None, A), (seed(), None), (seed(), "naver_a")):
            with self.assertRaises(TypeError):
                ex.cluster_of(*args)


class PublicNamesTest(unittest.TestCase):
    def test_the_module_lists_exactly_the_names_it_exports(self):
        for name in ex.__all__:
            self.assertTrue(hasattr(ex, name), name)
        self.assertEqual(len(set(ex.__all__)), len(ex.__all__))
        self.assertEqual(ex.BLOCK_REASONS, ("combination", "excluded_keyword", "too_long", "language"))
        self.assertEqual(ex.MAX_LIMIT, 20)


if __name__ == "__main__":
    unittest.main()
