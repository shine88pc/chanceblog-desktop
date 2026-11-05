"""쉬운 말 도우미와 값 이름 표(`topics/wording.py`) 시험 — P2b 보완 W1~W5(D-57).

지키는 것:
  W1) 도우미 단위: `clean_word`·`quote`·`quoted`·`one_of`(이름 표 없이 부르면 `TypeError`)·`unknown_and_missing`·`object_particle`·`tag_name`.
  W2) 값 이름 표 완전성: 닫힌 목록마다 이름 표가 값을 빠짐없이·남김없이 덮고, 한 표 안에서 이름이 겹치지 않고, 이름이 식별자 꼴이 아니다. 칸 이름 표의 키가 각 모듈의 `_KEYS` 와 같고 값이 모두 한글을 품는다.
     같은 값이어야 하는 표 쌍(`SOURCE_TYPE_KO`=`generate.ROUTE_KO`·`CHANNEL_KO`=기본 프로필 표시 이름·`DUPLICATE_STATUS_KO`=`dedupe.STATUS_KO`·`SAFETY_FLAG_KO`=`safety.FLAG_KO`)이 어긋나지 않는다.
  W3) `wording` 은 `topics` 의 다른 모듈을 가져오지 않는다. W4) `invalid_in(…, dev=…)` — 개발자 메모는 `AppError.detail` 에만. W5) 어느 번째 항목 오류도 메모를 화면 글로 새게 하지 않는다.
표의 이름은 초기값 — 전략 원문 확인 전이다. 네트워크·파일·실제 시계·난수 없이 돈다.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import dedupe as dd  # noqa: E402
from chanceblog_desktop.topics import expand as ex  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import link as lk  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402
from chanceblog_desktop.topics import schedule as sc  # noqa: E402
from chanceblog_desktop.topics import score as se  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.topics import wording as wd  # noqa: E402

SEED = dict(seed_id="s1", major="가", minor="나", keyword="노트북", seed_type="general", scope="common", priority=False, excluded_keywords=[], sponsor_tag=None, state="active", registered_on="2026-01-01",
            last_selected_on=None, active_since=None)
HANGUL = re.compile("[가-힣]")
IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]*")


class HelpersTest(unittest.TestCase):                                                                          # W1
    def test_clean_word_removes_control_characters_curly_quotes_and_folds_spaces(self):
        self.assertEqual(wd.clean_word("  a\tb\nc  "), "a b c")
        self.assertEqual(wd.clean_word("a" + chr(0x200B) + "b" + chr(7) + "c"), "abc")
        self.assertEqual(wd.clean_word("‘안녕’"), "안녕", "바깥 따옴표와 섞이지 않게 입력 안의 곡선 따옴표는 지운다")
        self.assertEqual(wd.clean_word("x" * 30), "x" * 19 + "…")
        self.assertEqual(len(wd.clean_word("x" * 30)), 20)
        self.assertEqual(wd.clean_word("x" * 20), "x" * 20)
        self.assertEqual(wd.clean_word("x" * 30, limit=5), "xxxx…")
        self.assertEqual(wd.clean_word(None), "None")

    def test_quote_wraps_in_curly_quotes_and_shortens(self):
        self.assertEqual(wd.quote("zzz"), "‘zzz’")
        self.assertEqual(wd.quote("x" * 30), "‘" + "x" * 19 + "…’")
        self.assertEqual(wd.quote(3), "‘3’")
        self.assertEqual(wd.quote("['a', 'b']"), "‘['a', 'b']’", "입력은 따옴표 안에만 나온다")

    def test_quoted_turns_values_into_names_and_keeps_unknown_values_quoted(self):
        self.assertEqual(wd.quoted(("ko", "en"), names=wd.LANGUAGE_KO), "‘한국어’, ‘영어’")
        self.assertEqual(wd.quoted(("ko", "zzz"), names=wd.LANGUAGE_KO), "‘한국어’, ‘zzz’")
        self.assertEqual(wd.quoted(("가", "나", "다", "라")), "‘가’, ‘나’, ‘다’, ‘라’")
        self.assertEqual(wd.quoted(("가", "나", "다", "라"), limit=2), "‘가’, ‘나’ 외 2개")
        self.assertEqual(wd.quoted(("가", "나"), limit=2), "‘가’, ‘나’")
        self.assertEqual(wd.quoted(()), "")
        self.assertEqual(wd.quoted([3, None]), "‘3’, ‘None’")

    def test_one_of_needs_the_names_table_so_raw_values_cannot_be_listed(self):
        self.assertEqual(wd.one_of(("general", "priority"), wd.SEED_TYPE_KO), "다음 중 하나여야 합니다: ‘일반’, ‘우선’")
        with self.assertRaises(TypeError):
            wd.one_of(("general", "priority"))                                              # type: ignore[call-arg]

    def test_unknown_and_missing_lists_the_two_kinds_in_one_plain_sentence(self):
        labels = ch.PROFILE_FIELD_KO
        self.assertEqual(wd.unknown_and_missing(["zzz"], ["top_n"], labels), "모르는 칸이 있습니다: ‘zzz’ · 빠진 칸이 있습니다: ‘채널당 후보 수’")
        self.assertEqual(wd.unknown_and_missing([], ["top_n"], labels), "빠진 칸이 있습니다: ‘채널당 후보 수’")
        self.assertEqual(wd.unknown_and_missing(["zzz"], [], labels), "모르는 칸이 있습니다: ‘zzz’")
        self.assertEqual(wd.unknown_and_missing([], [], labels), "")
        many = wd.unknown_and_missing([], sorted(labels)[:9], labels)
        self.assertTrue(many.endswith("외 3개"), many)
        self.assertEqual(wd.unknown_and_missing([], ["nope"], labels), "빠진 칸이 있습니다: ‘nope’", "표에 없는 칸 이름은 따옴표로 되돌린다")
        self.assertEqual(wd.unknown_and_missing(["a", "b", "c"], [], labels, limit=2), "모르는 칸이 있습니다: ‘a’, ‘b’ 외 1개")

    def test_the_object_particle_follows_the_last_hangul_syllable(self):
        for word, particle in (("제미나이", "를"), ("코파일럿", "을"), ("삼성", "을"), ("엘지", "를"), ("네이버", "를"), ("마이크로소프트", "를"), ("에이수스", "를"), ("LG", "를"), ("", "를"), ("API", "를")):
            with self.subTest(word=word):
                self.assertEqual(wd.object_particle(word), particle)

    def test_tag_name_gives_the_korean_name_in_quotes_and_quotes_an_unknown_tag(self):
        self.assertEqual(wd.tag_name("lodging_travel"), "‘숙박·여행’")
        self.assertEqual(wd.tag_name("zzz_tag"), "‘zzz_tag’")
        self.assertEqual(wd.tag_name(None), "‘None’")

    def test_the_helpers_do_not_change_their_inputs(self):
        values = ["ko", "en"]
        wd.quoted(values, names=wd.LANGUAGE_KO, limit=1)
        self.assertEqual(values, ["ko", "en"])


class NameTablesTest(unittest.TestCase):                                                                       # W2
    PAIRS = (
        ("SEED_TYPE_KO", sd.SEED_TYPES), ("SOURCE_TYPE_KO", md.SOURCE_TYPES), ("CHANNEL_KO", ch.CHANNELS), ("SCOPE_KO", sd.SCOPES), ("LANGUAGE_KO", ch.LANGUAGES), ("TREND_USE_KO", ch.TREND_USES),
        ("CANDIDATE_TYPE_KO", md.CANDIDATE_TYPES), ("SEARCH_INTENT_KO", md.SEARCH_INTENTS), ("CONTENT_TYPE_KO", md.CONTENT_TYPES), ("DATA_STATUS_KO", se.DATA_STATUSES),
        ("DUPLICATE_STATUS_KO", md.DUPLICATE_STATUSES), ("SAFETY_FLAG_KO", md.SAFETY_FLAGS), ("CHANNEL_ALIAS_KO", tuple(ch.CHANNEL_ALIAS)),
    )

    def test_each_name_table_covers_the_closed_list_with_no_missing_and_no_extra_value(self):
        for table, values in self.PAIRS:
            with self.subTest(table=table):
                self.assertEqual(tuple(getattr(wd, table)), tuple(values))

    def test_names_inside_one_table_are_distinct_and_never_identifier_shaped(self):
        for table in ("SEED_TYPE_KO", "SOURCE_TYPE_KO", "CHANNEL_KO", "SCOPE_KO", "CHANNEL_ALIAS_KO", "LANGUAGE_KO", "TREND_USE_KO", "CANDIDATE_TYPE_KO", "SEARCH_INTENT_KO", "CONTENT_TYPE_KO",
                      "DATA_STATUS_KO", "DUPLICATE_STATUS_KO", "SAFETY_FLAG_KO", "TAG_KO", "CLUSTER_KO", "FILE_KEY_KO"):
            names = list(getattr(wd, table).values())
            with self.subTest(table=table):
                self.assertEqual(len(names), len(set(names)))
                for name in names:
                    self.assertIsNone(IDENTIFIER.fullmatch(name), name)
                    self.assertTrue(HANGUL.search(name) or name == "GitHub Pages", name)

    def test_the_pairs_that_must_say_the_same_thing_do(self):
        self.assertEqual(dict(wd.SOURCE_TYPE_KO), dict(gn.ROUTE_KO))
        self.assertEqual([wd.CHANNEL_KO[profile.key] for profile in ch.default_profiles()], [profile.display_name for profile in ch.default_profiles()])
        self.assertEqual(dict(wd.DUPLICATE_STATUS_KO), dict(dd.STATUS_KO))
        self.assertEqual(dict(wd.SAFETY_FLAG_KO), dict(sf.FLAG_KO))
        self.assertEqual(dict(wd.SCOPE_KO), {"common": "공통", **wd.CHANNEL_KO})
        self.assertIs(ex.SEED_TYPE_KO, wd.SEED_TYPE_KO, "표의 주인은 wording 이고 expand 의 이름은 그대로다")
        self.assertIn("SEED_TYPE_KO", ex.__all__)

    def test_the_tag_and_cluster_tables_cover_what_the_generator_and_the_expansion_know(self):
        self.assertEqual(set(wd.TAG_KO), set(gn.CLUSTER_MONETIZATION.values()))
        for slug, labels in ex.CLUSTER_LABELS.items():
            korean = next((label for label in labels if HANGUL.search(label)), None)
            with self.subTest(cluster=slug):
                if slug in ("api-and-limits", "github-and-deploy"):
                    self.assertEqual(wd.CLUSTER_KO[slug], {"api-and-limits": "API 한도", "github-and-deploy": "배포"}[slug])
                elif korean is None:
                    self.assertNotIn(slug, wd.CLUSTER_KO, "한글 이름이 없는 묶음은 이름 표에 없다")
                else:
                    self.assertEqual(wd.CLUSTER_KO[slug], korean)
        self.assertEqual(len(wd.CLUSTER_KO), 26)

    def test_the_field_name_tables_have_the_same_keys_as_the_json_keys_and_korean_values(self):
        pairs = ((ch.PROFILE_FIELD_KO, ch._KEYS), (sd.SEED_FIELD_KO, sd._KEYS), (sc.ENTRY_FIELD_KO, sc._KEYS), (sf.CAMPAIGN_FIELD_KO, sf.CAMPAIGN_KEYS))
        for table, keys in pairs:
            with self.subTest(keys=keys[0]):
                self.assertEqual(tuple(table), tuple(keys))
                self.assertTrue(all(HANGUL.search(value) for value in table.values()))
        link_keys = {"engine_candidate_id", "legacy_candidate_id", "draft_plan_id", *lk.Provenance.__dataclass_fields__, *lk.CandidateLink.__dataclass_fields__}
        self.assertTrue(link_keys <= set(lk.LINK_FIELD_KO), link_keys - set(lk.LINK_FIELD_KO))
        self.assertTrue(all(HANGUL.search(value) for value in lk.LINK_FIELD_KO.values()))
        self.assertTrue(set(md._KEYS) - {"schema"} <= set(md.LABELS))
        for name in ("seed_id", "scores", "selection_reasons", "channel"):
            self.assertEqual(lk.LINK_FIELD_KO[name], md.LABELS[name], "후보 칸 이름과 같은 글이다")

    def test_the_module_says_the_names_are_initial_values_and_every_table_value_is_pinned(self):
        doc = Path(wd.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        self.assertIn("초기값 — 전략 원문 확인 전", doc)
        pinned = {
            "SEED_TYPE_KO": {"general": "일반", "priority": "우선", "seasonal": "계절", "realtime": "실시간", "sponsorable": "협찬 가능"},
            "SOURCE_TYPE_KO": {"seed": "씨앗", "follow_up": "후속", "seasonal": "계절", "realtime": "실시간", "sponsor": "협찬"},
            "CHANNEL_KO": {"github_pages": "GitHub Pages", "blogger_en": "Blogger 영문", "blogger_ko": "Blogger 한글", "naver_a": "네이버 A", "naver_b": "네이버 B"},
            "CHANNEL_ALIAS_KO": {"blogger_a": "Blogger A(한글)", "blogger_b": "Blogger B(영문)"},
            "LANGUAGE_KO": {"ko": "한국어", "en": "영어"},
            "TREND_USE_KO": {"primary": "주된 근거로 씀", "supporting": "보조로 씀", "reference": "참고만 함", "none": "쓰지 않음"},
            "CANDIDATE_TYPE_KO": {"evergreen": "지속형", "seasonal": "계절형", "realtime": "실시간", "follow_up": "후속", "sponsor_prep": "협찬 준비형"},
            "SEARCH_INTENT_KO": {"information": "정보 찾기", "how_to": "하는 법 찾기", "problem_solving": "문제 해결", "selection_guide": "고르기", "comparison": "비교", "local_info": "지역 정보",
                                 "context_explainer": "배경 이해", "routine_building": "습관 만들기"},
            "CONTENT_TYPE_KO": {"explainer": "설명글", "how_to_guide": "따라 하기 안내", "checklist": "점검표", "troubleshooting": "문제 해결", "buying_guide": "구매 안내", "comparison": "비교",
                                "place_guide": "장소 안내", "news_analysis": "소식 분석", "routine_plan": "습관 계획", "dev_log": "개발 기록", "service_intro": "서비스 소개"},
            "DATA_STATUS_KO": {"sufficient": "충분", "partial": "일부만 있음", "insufficient": "모자람", "unavailable": "조회 불가"},
            "DUPLICATE_STATUS_KO": {"different_topic": "다른 주제", "similar_elements": "비슷한 요소 있음", "different_angle_needed": "다른 관점이 필요", "duplicate_or_update": "중복 또는 기존 글 업데이트 후보"},
            "SAFETY_FLAG_KO": {"health_check": "건강 표현", "product_brand": "제품·브랜드", "experience_claim": "경험 단정", "sponsor_disclosure": "협찬 고지", "result_promise": "결과 약속 표현"},
            "TAG_KO": {"small_appliance": "소형가전", "pc_peripheral": "PC 주변기기", "lodging_travel": "숙박·여행", "ai_service": "AI 서비스", "pc_parts": "PC 부품", "work_automation": "업무 자동화"},
            "FILE_KEY_KO": {"schema": "저장 형식 번호", "profiles": "채널 프로필 목록", "seeds": "씨앗 목록", "entries": "캘린더 항목 목록"},
        }
        for name, expected in pinned.items():
            with self.subTest(table=name):
                self.assertEqual(dict(getattr(wd, name)), expected)

    def test_the_file_key_table_names_the_four_stored_file_keys(self):
        self.assertEqual(tuple(wd.FILE_KEY_KO), ("schema", "profiles", "seeds", "entries"))


class DependencyTest(unittest.TestCase):                                                                       # W3
    def test_wording_imports_nothing_from_the_other_topic_modules(self):
        tree = ast.parse(Path(wd.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "topics 의 다른 모듈을 가져오지 않는다")
                self.assertIn(node.module, ("__future__", "types"))
            elif isinstance(node, ast.Import):
                self.assertEqual([alias.name for alias in node.names], ["unicodedata"])


class InvalidInDevTest(unittest.TestCase):                                                                     # W4
    def test_without_dev_the_error_is_exactly_what_it_was(self):
        error = ch.invalid_in("씨앗", "상태", "1~30자 한 줄이어야 한다")
        self.assertEqual(error.detail, "1~30자 한 줄이어야 한다")
        self.assertEqual(error.slots["항목"], "씨앗의 상태 — 1~30자 한 줄이어야 한다")
        self.assertEqual((error.reason, error.dev, error.code, error.explained), ("1~30자 한 줄이어야 한다", "", "CONTENT_INVALID", True))
        self.assertEqual(ch.invalid_in("씨앗", "상태").detail, "")

    def test_a_dev_note_goes_to_the_developer_detail_and_never_into_the_screen_text(self):
        error = ch.invalid_in("씨앗", "상태", "다음 중 하나여야 합니다", dev="값: proposed, active")
        self.assertEqual(error.detail, "다음 중 하나여야 합니다 | 값: proposed, active")
        self.assertNotIn("proposed", error.slots["항목"])
        self.assertNotIn("proposed", error.rendered().message)
        self.assertEqual((error.reason, error.dev), ("다음 중 하나여야 합니다", "값: proposed, active"))
        only = ch.invalid_in("씨앗", "상태", dev="메모")
        self.assertEqual((only.detail, only.slots["항목"]), ("메모", "씨앗의 상태"))


class AtEntryTest(unittest.TestCase):                                                                          # W5
    def test_an_error_in_the_nth_seed_keeps_the_dev_note_out_of_the_screen_text(self):
        data = {"schema": 1, "seeds": [dict(SEED), dict(SEED, seed_id="s2", keyword="마우스", seed_type="zzz")]}
        with self.assertRaises(AppError) as caught:
            sd.seeds_from_dict(data)
        error = caught.exception
        self.assertIn("2번째 씨앗", error.slots["항목"])
        self.assertNotIn("general", error.slots["항목"])
        self.assertNotIn("값:", error.slots["항목"])
        self.assertIn("값: general", error.detail, "개발자 메모는 그대로 남는다")
        self.assertIn("다음 중 하나여야 합니다", error.slots["항목"])

    def test_the_nth_calendar_entry_does_the_same_and_an_unexplained_error_is_returned_unchanged(self):
        entry = ts.example_entry().to_dict()
        with self.assertRaises(AppError) as caught:
            sc.entries_from_dict({"schema": 1, "entries": [entry, {**entry, "entry_id": "x2", "repeat": "weekly"}]})
        self.assertIn("2번째 캘린더", caught.exception.slots["항목"])
        self.assertNotIn("yearly", caught.exception.slots["항목"])
        plain = AppError("CONTENT_INVALID", {"항목": "x"})
        self.assertIs(ch.at_entry("씨앗", 1, plain), plain)


if __name__ == "__main__":
    unittest.main()
