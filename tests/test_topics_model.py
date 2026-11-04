"""엔진 후보(`TopicCandidate`) 시험 — 닫힌 목록, 필수·기본값, 한 줄 규칙·결과 약속 표현 거절, 관심도(상대값)와 실제 검색 횟수의 분리, 두 상태 축, 엄격한 JSON 왕복, 이름 규칙.

지키는 것:
  1) 열거형 값은 닫힌 목록이다(작업 상태는 기존 후보의 다섯 값을 그대로 쓴다). 글 종류는 기존 글 유형 다섯에 빠짐없이 대응한다.
  2) 모든 글칸(주제·키워드·보조 키워드·대상 독자·선정 이유·처리 중 문제·관심도 기간·비교 그룹·횟수 출처)은 기존 후보와 같은 한 줄·위험한 표기·결과 약속 표현 규칙으로 거절한다.
  3) 관심도(상대값)와 실제 검색 횟수는 다른 칸이다 — 상대값에는 기준(기간·비교 그룹·조회일)이 있어야 하고 횟수에는 출처가 있어야 하며, 상대값은 횟수 칸으로 흘러가지 않는다.
     칸 이름·저장 키·화면 이름 어디에도 '검색량'·'조회수'·volume 이 없고 demand 는 실제 횟수 칸 둘에만 있다.
  4) 작업 상태(work_status)와 추천 구간(recommendation_band)은 다른 축이다 — 구간은 점수에서 계산하고 저장하지 않으며 하나의 status 로 합치지 않는다.
  5) 저장 모양(JSON)은 엄격하다 — 모르는 칸·빠진 필수 칸·어긋난 값은 거절하고 왕복하면 같은 후보다.
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import dataclasses
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.content import candidates as cand  # noqa: E402
from chanceblog_desktop.content.profiles import POST_TYPES  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402
from chanceblog_desktop.topics import score as sc  # noqa: E402

REQUIRED = ("candidate_id", "source_type", "candidate_type", "channel", "language", "topic", "primary_keyword", "search_intent", "content_type", "topic_cluster", "topic_angle",
            "target_reader", "created_at")
OPTIONAL = ("source_topic_id", "seed_id", "secondary_keywords", "scores", "trend_status", "trend_ratio", "trend_period", "trend_compared_group", "trend_queried_on",
            "search_demand_count", "search_demand_source", "data_status", "duplicate_status", "similar_post_ids", "monetization_tags", "selection_reasons", "processing_errors",
            "work_status", "review_expires_at")
PROMISES = ("상위노출 보장", "검색 1위 가능성", "수익 보장", "노출 확률 높이는 법", "guaranteed income")
TREND_BASIS = {"trend_ratio": 60, "trend_period": "최근 12개월", "trend_compared_group": ("로컬 AI",), "trend_queried_on": "2026-11-04"}


def rejected(test, **changes):
    """바꾼 값으로 후보를 만들면 CANDIDATE_INVALID 로 거절하고 사용자 문구가 만들어지는지 본다."""
    with test.assertRaises(AppError) as caught:
        ts.make(**changes)
    test.assertEqual(caught.exception.code, "CANDIDATE_INVALID")
    test.assertTrue(caught.exception.rendered().message)
    return caught.exception


class ClosedListsTest(unittest.TestCase):
    def test_the_enumerations_are_exactly_the_documented_values(self):
        self.assertEqual(md.SOURCE_TYPES, ("seed", "follow_up", "seasonal", "realtime", "sponsor"))
        self.assertEqual(md.CANDIDATE_TYPES, ("evergreen", "seasonal", "realtime", "follow_up", "sponsor_prep"))
        self.assertEqual(md.DUPLICATE_STATUSES, ("different_topic", "similar_elements", "different_angle_needed", "duplicate_or_update"))

    def test_search_intents_and_content_types_are_closed_lists_that_hold_the_strategy_examples(self):
        for values in (md.SEARCH_INTENTS, md.CONTENT_TYPES):
            self.assertEqual(len(set(values)), len(values))
            self.assertTrue(all(ch.is_tag(value) for value in values))
        self.assertIn("selection_guide", md.SEARCH_INTENTS)
        self.assertIn("buying_guide", md.CONTENT_TYPES)

    def test_every_enumerated_value_is_accepted_and_others_are_not(self):
        cases = (("source_type", md.SOURCE_TYPES), ("candidate_type", md.CANDIDATE_TYPES), ("search_intent", md.SEARCH_INTENTS), ("content_type", md.CONTENT_TYPES),
                 ("duplicate_status", md.DUPLICATE_STATUSES), ("trend_status", ("insufficient",)), ("data_status", sc.DATA_STATUSES))
        for name, values in cases:
            for value in values:
                with self.subTest(field=name, value=value):
                    self.assertEqual(getattr(ts.make(**{name: value}), name), value)
            for bad in ("", "other", values[0].upper(), f" {values[0]}", None if name != "duplicate_status" else "different_angle", 3, ["x"]):
                with self.subTest(field=name, bad=bad):
                    rejected(self, **{name: bad})

    def test_a_missing_duplicate_check_is_none_and_not_a_value_of_the_list(self):
        self.assertIsNone(ts.make().duplicate_status)
        self.assertIsNone(ts.make(duplicate_status=None).duplicate_status)

    def test_the_work_status_values_are_the_ones_the_existing_candidate_uses(self):
        self.assertEqual(cand.STATUSES, ("NEW", "REVIEW", "SELECTED", "HOLD", "REJECTED"))
        for status in cand.STATUSES:
            self.assertEqual(ts.make(work_status=status).work_status, status)
        for bad in ("DRAFTING", "DRAFT_READY", "COPIED", "PUBLISHED", "RECOMMENDED", "recommended", "new", "", None, 1):
            with self.subTest(status=bad):
                rejected(self, work_status=bad)

    def test_every_content_type_maps_to_one_of_the_five_existing_post_types(self):
        self.assertEqual(set(md.CONTENT_TO_POST_TYPE), set(md.CONTENT_TYPES))
        self.assertTrue(set(md.CONTENT_TO_POST_TYPE.values()) <= set(POST_TYPES))
        self.assertEqual(set(md.CONTENT_TO_POST_TYPE.values()), set(POST_TYPES), "다섯 유형이 모두 어떤 글 종류의 대응이다")
        for content_type in md.CONTENT_TYPES:
            self.assertIn(md.to_post_type(content_type), POST_TYPES)

    def test_the_documented_mapping_examples(self):
        self.assertEqual(md.to_post_type("buying_guide"), "비교형")
        self.assertEqual(md.to_post_type("comparison"), "비교형")
        self.assertEqual(md.to_post_type("troubleshooting"), "문제 해결형")
        self.assertEqual(md.to_post_type("service_intro"), "제품·서비스 소개형")
        self.assertEqual(md.to_post_type("place_guide"), "장소·업체 정보형")
        self.assertEqual(md.to_post_type("explainer"), "정보형")

    def test_an_unknown_content_type_has_no_post_type(self):
        for bad in ("blog", "", None, 3, "Buying_Guide"):
            with self.assertRaises(AppError):
                md.to_post_type(bad)
        with self.assertRaises(TypeError):
            md.CONTENT_TO_POST_TYPE["explainer"] = "비교형"


class ShapeTest(unittest.TestCase):
    def test_a_minimal_candidate_has_safe_defaults(self):
        c = ts.make()
        self.assertEqual((c.trend_status, c.data_status, c.work_status), ("insufficient", "insufficient", "NEW"))
        self.assertEqual(c.scores, sc.ScoreCard())
        self.assertEqual(c.recommendation_band, "UNRATED")
        for name in ("source_topic_id", "seed_id", "trend_ratio", "trend_period", "trend_queried_on", "search_demand_count", "search_demand_source", "duplicate_status", "review_expires_at"):
            self.assertIsNone(getattr(c, name), name)
        for name in ("secondary_keywords", "trend_compared_group", "similar_post_ids", "monetization_tags", "selection_reasons", "processing_errors"):
            self.assertEqual(getattr(c, name), (), name)

    def test_the_fields_are_exactly_the_documented_ones(self):
        self.assertEqual({f.name for f in dataclasses.fields(md.TopicCandidate)}, set(REQUIRED) | set(OPTIONAL))
        self.assertEqual(md._KEYS[0], "schema")
        self.assertEqual(set(md._KEYS[1:]), set(REQUIRED) | set(OPTIONAL))
        self.assertEqual(md._REQUIRED, set(REQUIRED) | {"schema"})

    def test_every_required_field_must_be_given(self):
        base = {"candidate_id": "c1", "source_type": "seed", "candidate_type": "evergreen", "channel": "naver_b", "language": "ko", "topic": "주제", "primary_keyword": "키워드",
                "search_intent": "how_to", "content_type": "explainer", "topic_cluster": "a", "topic_angle": "b", "target_reader": "독자", "created_at": ts.STAMP}
        self.assertEqual(set(base), set(REQUIRED))
        md.TopicCandidate(**base)
        for name in REQUIRED:
            with self.subTest(missing=name):
                with self.assertRaises(TypeError):
                    md.TopicCandidate(**{key: value for key, value in base.items() if key != name})

    def test_the_fields_can_only_be_given_by_name(self):
        with self.assertRaises(TypeError):
            md.TopicCandidate("c1", "seed", "evergreen", "naver_b", "ko", "주제", "키워드", "how_to", "explainer", "a", "b", "독자", ts.STAMP)

    def test_the_candidate_is_a_frozen_value_and_replace_checks_again(self):
        c = ts.make()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            c.topic = "다른 주제"
        self.assertEqual(dataclasses.replace(c, work_status="REVIEW").work_status, "REVIEW")
        with self.assertRaises(AppError):
            dataclasses.replace(c, topic="")
        self.assertEqual(hash(ts.make()), hash(ts.make()))
        self.assertEqual(ts.make(), ts.make())
        self.assertNotEqual(ts.make(), ts.make(candidate_id="cand0002"))

    def test_the_candidate_makes_no_numbers_of_its_own(self):
        self.assertFalse(hasattr(md.TopicCandidate, "new"), "번호는 난수라서 만드는 쪽이 정한다")


class IdentityTest(unittest.TestCase):
    def test_the_candidate_id_shape(self):
        for good in ("a", "c" * 64, "A-b_9", "0123456789abcdef0123456789abcdef"):
            self.assertEqual(ts.make(candidate_id=good).candidate_id, good)
        for bad in ("", "c" * 65, "a b", "a.b", "a/b", "한글", None, 3, "a\n"):
            with self.subTest(candidate_id=bad):
                rejected(self, candidate_id=bad)

    def test_the_optional_ids_are_none_or_the_same_shape(self):
        for name in ("source_topic_id", "seed_id"):
            self.assertEqual(getattr(ts.make(**{name: "src-1"}), name), "src-1")
            for bad in ("", "a b", "c" * 65, 3, "한글"):
                with self.subTest(field=name, value=bad):
                    rejected(self, **{name: bad})

    def test_each_of_the_five_channels_is_accepted(self):
        for key in ch.CHANNELS:
            self.assertEqual(ts.make(channel=key).channel, key)

    def test_the_strategy_aliases_are_not_stored_and_the_message_says_which_key_to_use(self):
        for alias, key in ch.CHANNEL_ALIAS.items():
            error = rejected(self, channel=alias)
            self.assertIn(key, error.detail + error.rendered().message + str(error.slots))
        for bad in ("tistory", "", "NAVER_A", None, 3, ["naver_a"]):
            with self.subTest(channel=bad):
                rejected(self, channel=bad)

    def test_the_language_is_ko_or_en(self):
        for language in ch.LANGUAGES:
            self.assertEqual(ts.make(language=language).language, language)
        for bad in ("jp", "KO", "", None):
            rejected(self, language=bad)

    def test_the_cluster_and_angle_are_lowercase_hyphen_identifiers(self):
        for name in ("topic_cluster", "topic_angle"):
            self.assertEqual(getattr(ts.make(**{name: "gpu-memory-requirements"}), name), "gpu-memory-requirements")
            for bad in ("", "Local-AI", "local_ai", "local ai", "로컬", "-a", "a-", "a--b", "a" * 61, None, 3):
                with self.subTest(field=name, value=bad):
                    rejected(self, **{name: bad})

    def test_similar_posts_and_tags(self):
        c = ts.make(similar_post_ids=("2026-10-01-KR-120000", "my-post_1", "a:b"), monetization_tags=("pc_parts", "sponsored_product", "affiliate"))
        self.assertEqual(c.similar_post_ids, ("2026-10-01-KR-120000", "my-post_1", "a:b"))
        for bad in (("a b",), ("",), ("-x",), ("a/b",), ("a", "a"), "a", None, ("a",) * 2, tuple(f"p{i}" for i in range(md.MAX_SIMILAR + 1)), (3,)):
            with self.subTest(similar=bad):
                rejected(self, similar_post_ids=bad)
        for bad in (("PC",), ("pc-parts",), ("pc_parts", "pc_parts"), "pc_parts", None, tuple(f"t{i}" for i in range(md.MAX_TAGS + 1)), (3,)):
            with self.subTest(tags=bad):
                rejected(self, monetization_tags=bad)

    def test_lists_may_be_given_as_lists_and_are_stored_as_tuples(self):
        c = ts.make(secondary_keywords=["하나", "둘"], similar_post_ids=["p1"], monetization_tags=["a_b"], selection_reasons=["이유"], processing_errors=["문제"])
        for name in ("secondary_keywords", "similar_post_ids", "monetization_tags", "selection_reasons", "processing_errors"):
            self.assertIsInstance(getattr(c, name), tuple, name)


class TextRulesTest(unittest.TestCase):
    def test_every_text_field_rejects_a_promise_of_results(self):
        fields = (("topic", lambda text: text), ("primary_keyword", lambda text: text), ("secondary_keywords", lambda text: (text,)), ("target_reader", lambda text: text),
                  ("selection_reasons", lambda text: (text,)), ("processing_errors", lambda text: (text,)))
        for name, wrap in fields:
            for text in PROMISES:
                with self.subTest(field=name, text=text):
                    rejected(self, **{name: wrap(text)})

    def test_the_promise_check_is_the_same_one_the_existing_candidate_uses(self):
        for text in PROMISES:
            self.assertIsNotNone(cand.forbidden_claim(text), text)
        for text in ("상위노출 보장 업체 피하는 법", "수익을 보장하지 않습니다", "로컬 AI 고르는 기준"):
            self.assertIsNone(cand.forbidden_claim(text), text)
            self.assertEqual(ts.make(topic=text).topic, text)
            self.assertEqual(ts.make(selection_reasons=(text,)).selection_reasons, (text,))

    def test_the_trend_texts_and_the_count_source_reject_a_promise_too(self):
        rejected(self, **{**TREND_BASIS, "trend_status": "flat", "trend_period": "상위노출 보장"})
        rejected(self, **{**TREND_BASIS, "trend_status": "flat", "trend_compared_group": ("수익 보장",)})
        rejected(self, search_demand_count=10, search_demand_source="수익 보장")

    def test_one_line_rules_apply_to_every_text_field(self):
        bad_texts = ("두\n줄", "탭\t문자", "겹친  공백", "보이지" + chr(0x200B) + "않는 글자", "<b>굵게</b>", "{{ 템플릿 }}", "javascript:alert(1)", "")
        fields = (("topic", lambda text: text), ("primary_keyword", lambda text: text), ("secondary_keywords", lambda text: (text,)), ("target_reader", lambda text: text),
                  ("selection_reasons", lambda text: (text,)), ("processing_errors", lambda text: (text,)))
        for name, wrap in fields:
            for text in bad_texts:
                with self.subTest(field=name, text=text):
                    rejected(self, **{name: wrap(text)})

    def test_lengths(self):
        self.assertEqual(len(ts.make(topic="가" * md.MAX_TOPIC).topic), md.MAX_TOPIC)
        rejected(self, topic="가" * (md.MAX_TOPIC + 1))
        self.assertEqual(len(ts.make(primary_keyword="가" * 60).primary_keyword), 60)
        rejected(self, primary_keyword="가" * 61)
        self.assertEqual(len(ts.make(target_reader="가" * md.MAX_TARGET_READER).target_reader), md.MAX_TARGET_READER)
        rejected(self, target_reader="가" * (md.MAX_TARGET_READER + 1))
        self.assertEqual(len(ts.make(selection_reasons=("가" * md.MAX_REASON,)).selection_reasons[0]), md.MAX_REASON)
        rejected(self, selection_reasons=("가" * (md.MAX_REASON + 1),))
        rejected(self, target_reader="")

    def test_keywords_must_have_a_letter_or_digit_and_not_repeat(self):
        rejected(self, primary_keyword="!!!")
        rejected(self, secondary_keywords=("!!!",))
        rejected(self, secondary_keywords=("로컬 AI 사양",))               # 핵심 키워드와 같다(띄어쓰기·기호 무시)
        rejected(self, secondary_keywords=("로컬-AI-사양",))
        rejected(self, secondary_keywords=("하나", "하나"))
        rejected(self, secondary_keywords=("하나", "하 나"))
        self.assertEqual(ts.make(secondary_keywords=("C++", "C#", "C")).secondary_keywords, ("C++", "C#", "C"))
        rejected(self, secondary_keywords=tuple(f"단어{i}" for i in range(md.MAX_SUB_KEYWORDS + 1)))
        for bad in ("하나", {"하나"}, {"a": 1}, None, 3):
            with self.subTest(secondary=bad):
                rejected(self, secondary_keywords=bad)

    def test_reasons_and_errors_are_lists_of_lines_with_a_limit_and_are_kept_apart(self):
        for name, limit in (("selection_reasons", md.MAX_REASONS), ("processing_errors", md.MAX_ERRORS)):
            self.assertEqual(len(getattr(ts.make(**{name: tuple(f"이유 {i}" for i in range(limit))}), name)), limit)
            for bad in (tuple(f"이유 {i}" for i in range(limit + 1)), ("",), "이유", None, (3,)):
                with self.subTest(field=name, value=bad):
                    rejected(self, **{name: bad})
        c = ts.make(selection_reasons=("골랐다",), processing_errors=("조회가 한 번 실패했다",))
        self.assertEqual((c.selection_reasons, c.processing_errors), (("골랐다",), ("조회가 한 번 실패했다",)))
        self.assertNotIn("조회가 한 번 실패했다", c.selection_reasons)

    def test_the_error_message_names_the_field_in_plain_korean(self):
        error = rejected(self, topic="상위노출 보장")
        self.assertIn(md.LABELS["topic"], error.rendered().message)
        self.assertIn("결과를 약속하는 표현", error.rendered().message)


class ScoresAndAxesTest(unittest.TestCase):
    def test_scores_must_be_a_score_card(self):
        for bad in ({"final": 80}, None, 80, sc.Factors()):
            with self.subTest(scores=bad):
                rejected(self, scores=bad)

    def test_the_band_comes_from_the_final_score_and_is_not_stored(self):
        for final in range(101):
            c = ts.make(scores=ts.flat_card(final))
            self.assertEqual(c.recommendation_band, sc.band_of(final))
        self.assertEqual(ts.make().recommendation_band, "UNRATED")
        self.assertNotIn("recommendation_band", ts.make().to_dict())
        self.assertNotIn("recommendation_band", {f.name for f in dataclasses.fields(md.TopicCandidate)})

    def test_there_are_two_status_axes_and_no_single_status_field(self):
        names = {f.name for f in dataclasses.fields(md.TopicCandidate)}
        self.assertIn("work_status", names)
        self.assertTrue({"status", "grade"}.isdisjoint(names))
        self.assertTrue({"status", "grade", "recommendation_band"}.isdisjoint(ts.make().to_dict()))
        self.assertEqual(md.LABELS["work_status"], "작업 상태")
        self.assertEqual(md.LABELS["recommendation_band"], "추천 구간")

    def test_the_axes_move_independently(self):
        for band_final, expected in ((90, "RECOMMENDED"), (70, "GENERAL"), (55, "HOLD"), (10, "EXCLUDED")):
            for work in cand.STATUSES:
                with self.subTest(final=band_final, work=work):
                    c = ts.make(scores=ts.flat_card(band_final), work_status=work)
                    self.assertEqual((c.recommendation_band, c.work_status), (expected, work))

    def test_both_axes_have_a_hold_and_they_are_not_the_same_thing(self):
        c = ts.make(scores=ts.flat_card(90), work_status="HOLD")
        self.assertEqual((c.work_status, c.recommendation_band), ("HOLD", "RECOMMENDED"))
        c = ts.make(scores=ts.flat_card(55), work_status="NEW")
        self.assertEqual((c.work_status, c.recommendation_band), ("NEW", "HOLD"))


class TrendFieldsTest(unittest.TestCase):
    def test_a_candidate_may_know_nothing_about_the_trend(self):
        c = ts.make()
        self.assertEqual((c.trend_status, c.trend_ratio, c.trend_period, c.trend_compared_group, c.trend_queried_on), ("insufficient", None, None, (), None))

    def test_a_relative_value_comes_with_its_basis(self):
        c = ts.make(trend_status="rising", **TREND_BASIS)
        self.assertEqual((c.trend_ratio, c.trend_period, c.trend_compared_group, c.trend_queried_on), (60, "최근 12개월", ("로컬 AI",), "2026-11-04"))

    def test_the_relative_value_is_an_integer_from_zero_to_one_hundred(self):
        for good in (0, 1, 100):
            self.assertEqual(ts.make(**{**TREND_BASIS, "trend_status": "flat", "trend_ratio": good}).trend_ratio, good)
        for bad in (-1, 101, 50.5, 50.0, True, "50", [50]):
            with self.subTest(ratio=bad):
                rejected(self, **{**TREND_BASIS, "trend_status": "flat", "trend_ratio": bad})

    def test_a_relative_value_without_period_group_or_date_is_refused(self):
        for missing in ("trend_period", "trend_compared_group", "trend_queried_on"):
            basis = {key: value for key, value in TREND_BASIS.items() if key != missing}
            with self.subTest(missing=missing):
                rejected(self, trend_status="flat", **basis)

    def test_a_determinate_trend_status_needs_a_relative_value(self):
        for status in ("rising", "flat", "falling"):
            with self.subTest(status=status):
                rejected(self, trend_status=status)
                rejected(self, trend_status=status, trend_period="최근 12개월", trend_compared_group=("로컬 AI",), trend_queried_on="2026-11-04")
                self.assertEqual(ts.make(trend_status=status, **TREND_BASIS).trend_status, status)

    def test_not_enough_data_may_still_carry_a_value_and_its_basis_or_only_the_basis(self):
        self.assertEqual(ts.make(trend_status="insufficient", **TREND_BASIS).trend_ratio, 60)
        c = ts.make(trend_status="insufficient", trend_period="최근 12개월", trend_compared_group=("로컬 AI",), trend_queried_on="2026-11-04")
        self.assertIsNone(c.trend_ratio)

    def test_any_trend_value_needs_the_query_date(self):
        rejected(self, trend_period="최근 12개월")
        rejected(self, trend_compared_group=("로컬 AI",))
        rejected(self, trend_status="flat", **{**TREND_BASIS, "trend_queried_on": None})

    def test_the_query_date_shape(self):
        for good in ("2026-11-04", "2000-01-01"):
            self.assertEqual(ts.make(trend_period="기간", trend_queried_on=good).trend_queried_on, good)
        for bad in ("2026-13-01", "2026-02-30", "26-11-04", "2026/11/04", "2026-11-04T00:00:00Z", "1999-12-31", "", 20261104, True):
            with self.subTest(date=bad):
                rejected(self, trend_period="기간", trend_queried_on=bad)

    def test_the_period_and_the_compared_group_rules(self):
        rejected(self, trend_period="가" * (md.MAX_PERIOD + 1), trend_queried_on="2026-11-04")
        rejected(self, trend_period="", trend_queried_on="2026-11-04")
        rejected(self, trend_period="두\n줄", trend_queried_on="2026-11-04")
        rejected(self, trend_compared_group=("로컬 AI", "로컬 ai"), trend_queried_on="2026-11-04")
        rejected(self, trend_compared_group=tuple(f"그룹{i}" for i in range(md.MAX_COMPARED + 1)), trend_queried_on="2026-11-04")
        rejected(self, trend_compared_group="로컬 AI", trend_queried_on="2026-11-04")
        rejected(self, trend_compared_group=("",), trend_queried_on="2026-11-04")

    def test_the_trend_status_is_never_a_word_for_an_outage(self):
        rejected(self, trend_status="unavailable")
        rejected(self, trend_status="up")
        self.assertEqual(sc.TREND_STATUSES, ("rising", "flat", "falling", "insufficient"))


class SearchDemandTest(unittest.TestCase):
    def test_a_real_count_comes_with_its_source(self):
        c = ts.make(search_demand_count=4200, search_demand_source="검색광고 키워드 도구")
        self.assertEqual((c.search_demand_count, c.search_demand_source), (4200, "검색광고 키워드 도구"))
        self.assertEqual(ts.make(search_demand_count=0, search_demand_source="수동 입력").search_demand_count, 0)

    def test_a_count_without_a_source_and_a_source_without_a_count_are_both_refused(self):
        rejected(self, search_demand_count=4200)
        rejected(self, search_demand_source="검색광고 키워드 도구")
        rejected(self, search_demand_count=4200, search_demand_source="")

    def test_the_count_is_an_integer_in_range(self):
        self.assertEqual(ts.make(search_demand_count=md.MAX_SEARCH_COUNT, search_demand_source="출처").search_demand_count, md.MAX_SEARCH_COUNT)
        for bad in (-1, md.MAX_SEARCH_COUNT + 1, 12.5, 100.0, True, "4200", [1]):
            with self.subTest(count=bad):
                rejected(self, search_demand_count=bad, search_demand_source="출처")

    def test_a_trend_service_cannot_be_the_source_of_a_real_count(self):
        for source in ("NAVER Search Trend", "naver_search_trend", "네이버 데이터랩", "Datalab", "Google Trends", "트렌드 지수", "관심도 지수", "상대지수", "Search-Trend API"):
            with self.subTest(source=source):
                error = rejected(self, search_demand_count=100, search_demand_source=source)
                self.assertIn("실제 검색 횟수의 출처", error.rendered().message)
        for source in ("검색광고 키워드 도구", "naver_searchad", "수동 입력", "운영자가 확인한 값"):
            with self.subTest(source=source):
                self.assertEqual(ts.make(search_demand_count=100, search_demand_source=source).search_demand_source, source)

    def test_a_relative_value_never_becomes_a_count(self):
        c = ts.make(trend_status="rising", **TREND_BASIS)
        self.assertIsNone(c.search_demand_count)
        self.assertIsNone(c.search_demand_source)
        self.assertIsNone(c.to_dict()["search_demand_count"])
        self.assertEqual(c.to_dict()["trend_ratio"], 60)
        self.assertIsNone(dataclasses.replace(c, trend_ratio=70).search_demand_count)

    def test_the_two_values_stay_separate_when_both_exist(self):
        c = ts.full()
        data = c.to_dict()
        self.assertEqual((data["trend_ratio"], data["search_demand_count"]), (73, 4200))
        again = md.TopicCandidate.from_dict(data)
        self.assertEqual((again.trend_ratio, again.search_demand_count), (73, 4200))
        swapped = dict(data, trend_ratio=59, search_demand_count=73)
        self.assertNotEqual(md.TopicCandidate.from_dict(swapped), c)

    def test_a_count_does_not_change_the_score_or_the_band(self):
        plain = ts.make(scores=ts.flat_card(70))
        counted = ts.make(scores=ts.flat_card(70), search_demand_count=10**8, search_demand_source="출처")
        self.assertEqual((plain.scores, plain.recommendation_band), (counted.scores, counted.recommendation_band))


class NamesTest(unittest.TestCase):
    FORBIDDEN = ("volume", "검색량", "조회수", "예상 조회", "월 검색", "월간 검색", "demand")
    EXACT_COUNT_FIELDS = {"search_demand_count", "search_demand_source"}

    def names(self):
        fields = {f.name for f in dataclasses.fields(md.TopicCandidate)}
        return fields | set(md._KEYS) | set(ts.full().to_dict()) | set(md.LABELS)

    def test_no_field_key_or_label_name_uses_a_search_volume_word_except_the_two_real_count_fields(self):
        for name in self.names():
            for word in self.FORBIDDEN:
                if word in name.casefold():
                    with self.subTest(name=name, word=word):
                        self.assertEqual((word, name in self.EXACT_COUNT_FIELDS), ("demand", True))

    def test_the_demand_word_appears_only_in_the_two_real_count_fields(self):
        self.assertEqual({name for name in self.names() if "demand" in name}, self.EXACT_COUNT_FIELDS)

    def test_no_label_text_uses_a_search_volume_word(self):
        for key, text in md.LABELS.items():
            for word in ("검색량", "조회수", "volume", "예상 조회", "월 검색", "월간 검색", "상위노출", "노출 확률"):
                with self.subTest(label=key, word=word):
                    self.assertNotIn(word, text.casefold())

    def test_the_trend_labels_call_the_value_a_relative_interest_without_a_unit(self):
        self.assertEqual(md.LABELS["trend_ratio"], "최근 관심도(상대값)")
        self.assertEqual(md.LABELS["trend_status"], "최근 관심도 변화")
        self.assertEqual(md.LABELS["search_demand_count"], "실제 검색 횟수")
        self.assertNotEqual(md.LABELS["trend_ratio"], md.LABELS["search_demand_count"])
        for name in ("trend_ratio", "trend_status", "trend_period", "trend_compared_group", "trend_queried_on"):
            self.assertNotRegex(md.LABELS[name], r"[0-9]\s*회|월\s*검색")

    def test_the_labels_cover_every_field_and_the_derived_band(self):
        self.assertEqual(set(md.LABELS), {f.name for f in dataclasses.fields(md.TopicCandidate)} | {"recommendation_band"})
        self.assertEqual(len(set(md.LABELS.values())), len(md.LABELS), "라벨이 겹치지 않는다")

    def test_the_old_candidate_label_table_is_not_touched(self):
        self.assertEqual(cand.LABELS["search_demand"], "월간 검색 수요")
        self.assertEqual(cand.LABELS["trend"], "최근 관심도 변화")


class TimeAndDisplayTest(unittest.TestCase):
    def test_the_created_time_is_a_utc_stamp(self):
        for bad in ("2026-11-04", "2026-11-04T09:56:00", "2026-11-04T09:56:00+09:00", "2026-13-04T09:56:00Z", "1999-01-01T00:00:00Z", "", None, 3):
            with self.subTest(created_at=bad):
                rejected(self, created_at=bad)

    def test_the_review_deadline_cannot_be_before_the_creation(self):
        self.assertEqual(ts.make(review_expires_at=ts.STAMP).review_expires_at, ts.STAMP)
        self.assertEqual(ts.make(review_expires_at="2027-02-02T09:56:00Z").review_expires_at, "2027-02-02T09:56:00Z")
        rejected(self, review_expires_at="2026-11-04T09:55:59Z")
        rejected(self, review_expires_at="내일")
        self.assertIsNone(ts.make(review_expires_at=None).review_expires_at)

    def test_the_display_id_uses_the_korean_date_and_a_three_digit_number(self):
        self.assertEqual(md.display_id("2026-11-04T09:56:00Z", 1), "candidate-20261104-001")
        self.assertEqual(md.display_id("2026-11-04T09:56:00Z", 42), "candidate-20261104-042")
        self.assertEqual(md.display_id("2026-11-04T09:56:00Z", 999), "candidate-20261104-999")
        self.assertEqual(md.display_id("2026-11-04T09:56:00Z", 1000), "candidate-20261104-1000")

    def test_the_display_date_rolls_over_at_korean_midnight(self):
        self.assertEqual(md.display_id("2026-11-04T14:59:59Z", 7), "candidate-20261104-007")
        self.assertEqual(md.display_id("2026-11-04T15:00:00Z", 7), "candidate-20261105-007")
        self.assertEqual(md.display_id("2026-12-31T15:00:00Z", 1), "candidate-20270101-001")

    def test_the_display_id_arguments_are_checked(self):
        for sequence in (0, -1, md.MAX_SEQUENCE + 1, True, "1", 1.0, None):
            with self.subTest(sequence=sequence):
                with self.assertRaises(AppError):
                    md.display_id(ts.STAMP, sequence)
        for stamp in ("2026-11-04", "", None, "2026-11-04T09:56:00+09:00"):
            with self.assertRaises(AppError):
                md.display_id(stamp, 1)

    def test_a_display_id_is_a_poor_stored_id_because_the_prefix_is_the_same_for_everyone(self):
        first, second = md.display_id(ts.STAMP, 1), md.display_id(ts.STAMP, 2)
        self.assertEqual(first[:cand.SHORT_ID], second[:cand.SHORT_ID])
        self.assertEqual(cand.short_id(first), cand.short_id(second))


class JsonShapeTest(unittest.TestCase):
    def test_a_minimal_and_a_full_candidate_round_trip_through_json_text(self):
        for c in (ts.make(), ts.full(), ts.rated(88, source_topic_id="s1", seed_id="seed-1")):
            with self.subTest(candidate=c.candidate_id):
                text = json.dumps(c.to_dict(), ensure_ascii=False, sort_keys=True)
                self.assertEqual(md.TopicCandidate.from_dict(json.loads(text)), c)

    def test_the_stored_keys_are_exactly_these_in_this_order(self):
        data = ts.full().to_dict()
        self.assertEqual(tuple(data), md._KEYS)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(type(data["scores"]), dict)
        self.assertEqual(list(data["scores"]), [*ch.FACTOR_NAMES, "final"])
        for name in ("secondary_keywords", "trend_compared_group", "similar_post_ids", "monetization_tags", "selection_reasons", "processing_errors"):
            self.assertIs(type(data[name]), list, name)

    def test_the_schema_must_be_the_integer_one(self):
        good = ts.make().to_dict()
        for schema in (0, 2, "1", 1.0, True, None):
            with self.subTest(schema=schema):
                with self.assertRaises(AppError):
                    md.TopicCandidate.from_dict({**good, "schema": schema})
        missing = dict(good)
        del missing["schema"]
        for bad in (missing, None, [], "x", 1):
            with self.assertRaises(AppError):
                md.TopicCandidate.from_dict(bad)

    def test_an_unknown_key_is_refused(self):
        good = ts.make().to_dict()
        for extra in ("search_volume", "monthly_volume", "status", "grade", "recommendation_band", "relative_interest", "anything"):
            with self.subTest(key=extra):
                with self.assertRaises(AppError) as caught:
                    md.TopicCandidate.from_dict({**good, extra: 1})
                self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")

    def test_a_missing_required_key_is_refused_but_a_missing_optional_key_takes_its_default(self):
        good = ts.make().to_dict()
        for name in REQUIRED:
            with self.subTest(missing=name):
                data = dict(good)
                del data[name]
                with self.assertRaises(AppError):
                    md.TopicCandidate.from_dict(data)
        slim = {key: value for key, value in good.items() if key in set(REQUIRED) | {"schema"}}
        self.assertEqual(md.TopicCandidate.from_dict(slim), ts.make())

    def test_a_wrong_value_is_refused_when_read(self):
        good = ts.full().to_dict()
        for name, bad in (("channel", "blogger_a"), ("source_type", "manual"), ("work_status", "DRAFTING"), ("trend_ratio", True), ("trend_status", "unavailable"),
                          ("search_demand_source", None), ("scores", None), ("scores", {"final": 80}), ("secondary_keywords", "하나"), ("created_at", "어제"), ("topic", "상위노출 보장")):
            with self.subTest(field=name):
                with self.assertRaises(AppError):
                    md.TopicCandidate.from_dict({**good, name: bad})
        broken = ts.full().to_dict()
        broken["scores"]["final"] = 100
        with self.assertRaises(AppError):
            md.TopicCandidate.from_dict(broken)

    def test_the_scores_object_is_read_strictly(self):
        data = ts.full().to_dict()
        data["scores"]["luck"] = 1
        with self.assertRaises(AppError):
            md.TopicCandidate.from_dict(data)
        data = ts.full().to_dict()
        del data["scores"]["timing"]
        with self.assertRaises(AppError):
            md.TopicCandidate.from_dict(data)

    def test_to_dict_hands_out_copies_that_cannot_change_the_candidate(self):
        c = ts.full()
        data = c.to_dict()
        data["secondary_keywords"].append("끼어들기")
        data["scores"]["final"] = 1
        self.assertEqual(c, ts.full())

    def test_errors_use_the_candidate_error_code_and_it_exists_in_the_catalog(self):
        from chanceblog_desktop.errors import CATALOG
        self.assertIn("CANDIDATE_INVALID", CATALOG)
        with self.assertRaises(AppError) as caught:
            md.TopicCandidate.from_dict({"schema": 1})
        self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")


# 전략 문서의 최소 후보 모델 25칸의 이름(이름만 — 값·문장은 옮기지 않는다). 상태 칸 하나(status)는 두 축으로 나뉘어 work_status 와 recommendation_band 가 되었다.
STRATEGY_FIELDS = ("candidate_id", "source_topic_id", "seed_id", "source_type", "candidate_type", "channel", "language", "topic", "primary_keyword", "secondary_keywords", "search_intent",
                   "content_type", "topic_cluster", "topic_angle", "target_reader", "scores", "trend_status", "data_status", "duplicate_status", "similar_post_ids", "monetization_tags",
                   "selection_reasons", "status", "created_at", "review_expires_at")
ADDED_FIELDS = ("processing_errors", "trend_ratio", "trend_period", "trend_compared_group", "trend_queried_on", "search_demand_count", "search_demand_source")


class StrategyFieldsTest(unittest.TestCase):
    def test_the_twenty_five_strategy_fields_are_all_here_with_the_status_split_in_two(self):
        self.assertEqual(len(STRATEGY_FIELDS), 25)
        names = {f.name for f in dataclasses.fields(md.TopicCandidate)}
        self.assertEqual([name for name in STRATEGY_FIELDS if name not in names], ["status"])
        self.assertTrue({"work_status"} <= names and "recommendation_band" in md.LABELS)

    def test_the_added_fields_are_exactly_the_ones_the_operator_asked_for(self):
        names = {f.name for f in dataclasses.fields(md.TopicCandidate)}
        self.assertEqual(names - (set(STRATEGY_FIELDS) - {"status"}) - {"work_status"}, set(ADDED_FIELDS))

    def test_the_engine_candidate_and_the_existing_candidate_do_not_mix(self):
        engine = ts.full().to_dict()
        with self.assertRaises(AppError):
            cand.Candidate.from_dict(engine)
        legacy = cand.Candidate.new("주제", "키워드", ["naver_a"], now="2026-11-04T09:56:00Z").to_dict()
        with self.assertRaises(AppError):
            md.TopicCandidate.from_dict(legacy)
        self.assertEqual(cand.Candidate.new("주제", "키워드", ["naver_a"], search_demand=87, data_date="2026-11-04").search_demand, 87)


if __name__ == "__main__":
    unittest.main()
