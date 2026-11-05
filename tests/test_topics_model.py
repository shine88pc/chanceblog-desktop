"""엔진 후보(`TopicCandidate`) 시험 — 닫힌 목록, 필수·기본값, 한 줄 규칙·결과 약속 표현 거절, 관심도(상대값)와 실제 검색 횟수의 분리, 두 상태 축, 엄격한 JSON 왕복, 이름 규칙.

지키는 것:
  1) 열거형 값은 닫힌 목록이다(작업 상태는 기존 후보의 다섯 값을 그대로 쓴다). 글 종류는 기존 글 유형 다섯에 빠짐없이 대응한다.
  2) 모든 글칸(주제·키워드·보조 키워드·대상 독자·선정 이유·처리 중 문제·관심도 기간·비교 그룹·횟수 출처)은 기존 후보와 같은 한 줄·위험한 표기·결과 약속 표현 규칙으로 거절한다.
  3) 관심도(상대값)와 실제 검색 횟수는 다른 칸이다 — 상대값에는 기준(기간·비교 그룹·조회일)이 있어야 하고 횟수에는 출처가 있어야 하며, 상대값은 횟수 칸으로 흘러가지 않는다.
     칸 이름·저장 키·화면 이름 어디에도 '검색량'·'조회수'·volume 이 없고 demand 는 실제 횟수 칸(`search_demand_count`) 하나에만 있다(출처 칸은 `search_count_source` — P2a 에서 개명, D-43).
  6) 출처 이름에 상대값·관심도를 뜻하는 말이 들어 있으면 전각·악센트·키릴 닮은꼴·숫자 글자로 바꿔 써도 거절하고(P2a, L1), 저장 번호는 화면 표시 번호 모양(`candidate-…`)이 될 수 없다(L9).
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
            "search_demand_count", "search_count_source", "data_status", "duplicate_status", "similar_post_ids", "monetization_tags", "safety_flags", "selection_reasons", "processing_errors",
            "work_status", "review_expires_at")       # P2b 의도적 갱신: `safety_flags`(안전 표시)를 이 구현이 더했다 — 규칙 기반 안전 표시를 담을 자리(결정 D-47)
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

    def test_the_two_closed_lists_are_exactly_these_values_so_adding_a_word_is_a_conscious_change(self):
        # 낱말을 더하거나 빼면 여기가 걸린다 — 값이 늘면 이 시험과 글 종류 대응표(`CONTENT_TO_POST_TYPE`)를 함께 고친다(P2a, 독립 검증 L10).
        self.assertEqual(md.SEARCH_INTENTS, ("information", "how_to", "problem_solving", "selection_guide", "comparison", "local_info", "context_explainer", "routine_building"))
        self.assertEqual(md.CONTENT_TYPES, ("explainer", "how_to_guide", "checklist", "troubleshooting", "buying_guide", "comparison", "place_guide", "news_analysis", "routine_plan",
                                            "dev_log", "service_intro"))

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
        for name in ("source_topic_id", "seed_id", "trend_ratio", "trend_period", "trend_queried_on", "search_demand_count", "search_count_source", "duplicate_status", "review_expires_at"):
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
        rejected(self, search_demand_count=10, search_count_source="수익 보장")

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
        c = ts.make(search_demand_count=4200, search_count_source="검색광고 키워드 도구")
        self.assertEqual((c.search_demand_count, c.search_count_source), (4200, "검색광고 키워드 도구"))
        self.assertEqual(ts.make(search_demand_count=0, search_count_source="수동 입력").search_demand_count, 0)

    def test_a_count_without_a_source_and_a_source_without_a_count_are_both_refused(self):
        rejected(self, search_demand_count=4200)
        rejected(self, search_count_source="검색광고 키워드 도구")
        rejected(self, search_demand_count=4200, search_count_source="")

    def test_the_count_is_an_integer_in_range(self):
        self.assertEqual(ts.make(search_demand_count=md.MAX_SEARCH_COUNT, search_count_source="출처").search_demand_count, md.MAX_SEARCH_COUNT)
        for bad in (-1, md.MAX_SEARCH_COUNT + 1, 12.5, 100.0, True, "4200", [1]):
            with self.subTest(count=bad):
                rejected(self, search_demand_count=bad, search_count_source="출처")

    def test_a_trend_service_cannot_be_the_source_of_a_real_count(self):
        for source in ("NAVER Search Trend", "naver_search_trend", "네이버 데이터랩", "Datalab", "Google Trends", "트렌드 지수", "관심도 지수", "상대지수", "Search-Trend API"):
            with self.subTest(source=source):
                error = rejected(self, search_demand_count=100, search_count_source=source)
                self.assertIn("실제 검색 횟수의 출처", error.rendered().message)
        for source in ("검색광고 키워드 도구", "naver_searchad", "수동 입력", "운영자가 확인한 값"):
            with self.subTest(source=source):
                self.assertEqual(ts.make(search_demand_count=100, search_count_source=source).search_count_source, source)

    def test_a_relative_value_never_becomes_a_count(self):
        c = ts.make(trend_status="rising", **TREND_BASIS)
        self.assertIsNone(c.search_demand_count)
        self.assertIsNone(c.search_count_source)
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
        counted = ts.make(scores=ts.flat_card(70), search_demand_count=10**8, search_count_source="출처")
        self.assertEqual((plain.scores, plain.recommendation_band), (counted.scores, counted.recommendation_band))


class NamesTest(unittest.TestCase):
    FORBIDDEN = ("volume", "검색량", "조회수", "예상 조회", "월 검색", "월간 검색", "demand")
    EXACT_COUNT_FIELDS = {"search_demand_count"}                  # 운영자가 정한 이름 하나뿐 — 출처 칸은 search_count_source(P2a 개명, D-43)

    def names(self):
        fields = {f.name for f in dataclasses.fields(md.TopicCandidate)}
        return fields | set(md._KEYS) | set(ts.full().to_dict()) | set(md.LABELS)

    def test_no_field_key_or_label_name_uses_a_search_volume_word_except_the_one_real_count_field(self):
        for name in self.names():
            for word in self.FORBIDDEN:
                if word in name.casefold():
                    with self.subTest(name=name, word=word):
                        self.assertEqual((word, name in self.EXACT_COUNT_FIELDS), ("demand", True))

    def test_the_demand_word_appears_only_in_the_one_real_count_field(self):
        self.assertEqual({name for name in self.names() if "demand" in name}, self.EXACT_COUNT_FIELDS)

    def test_the_source_field_is_called_search_count_source_and_the_old_name_is_gone(self):
        names = self.names()
        self.assertIn("search_count_source", names)
        self.assertNotIn("search_demand_source", names)
        self.assertEqual(md.LABELS["search_count_source"], "검색 횟수 출처")
        self.assertNotIn("search_demand_source", ts.full().to_dict())
        with self.assertRaises(AppError):
            md.TopicCandidate.from_dict(dict(ts.make().to_dict(), search_demand_source=None))

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
                          ("search_count_source", None), ("scores", None), ("scores", {"final": 80}), ("secondary_keywords", "하나"), ("created_at", "어제"), ("topic", "상위노출 보장")):
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
ADDED_FIELDS = ("processing_errors", "trend_ratio", "trend_period", "trend_compared_group", "trend_queried_on", "search_demand_count", "search_count_source")
P2B_ADDED_FIELDS = ("safety_flags",)          # P2b 가 더한 칸 — 운영자가 칸 이름까지 정한 것이 아니라 '건강·제품·협찬은 표시만 한다' 는 전략 요구를 담으려고 이 구현이 정했다(결정 D-47)


class StrategyFieldsTest(unittest.TestCase):
    def test_the_twenty_five_strategy_fields_are_all_here_with_the_status_split_in_two(self):
        self.assertEqual(len(STRATEGY_FIELDS), 25)
        names = {f.name for f in dataclasses.fields(md.TopicCandidate)}
        self.assertEqual([name for name in STRATEGY_FIELDS if name not in names], ["status"])
        self.assertTrue({"work_status"} <= names and "recommendation_band" in md.LABELS)

    def test_the_added_fields_are_exactly_the_ones_the_operator_asked_for_and_the_one_p2b_added(self):
        names = {f.name for f in dataclasses.fields(md.TopicCandidate)}
        self.assertEqual(names - (set(STRATEGY_FIELDS) - {"status"}) - {"work_status"}, set(ADDED_FIELDS) | set(P2B_ADDED_FIELDS))

    def test_the_engine_candidate_and_the_existing_candidate_do_not_mix(self):
        engine = ts.full().to_dict()
        with self.assertRaises(AppError):
            cand.Candidate.from_dict(engine)
        legacy = cand.Candidate.new("주제", "키워드", ["naver_a"], now="2026-11-04T09:56:00Z").to_dict()
        with self.assertRaises(AppError):
            md.TopicCandidate.from_dict(legacy)
        self.assertEqual(cand.Candidate.new("주제", "키워드", ["naver_a"], search_demand=87, data_date="2026-11-04").search_demand, 87)


def fullwidth(text):
    """영문을 전각으로(ＴＲＥＮＤ) — 글자 이스케이프를 소스에 쓰지 않고 코드 위치로 만든다."""
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in text)


CYRILLIC_E, ACUTE_E = chr(0x0435), chr(0x00E9)
# 상대값·관심도를 뜻하는 말을 바꿔 쓴 출처 이름 — 전부 실제 검색 횟수의 출처가 될 수 없다(독립 검증 L1 이 찾은 우회 14가지 + 같은 계열)
DISGUISED_SOURCES = (
    fullwidth("TREND"), fullwidth("NAVER Search Trend"), fullwidth("DataLab"), "tr" + CYRILLIC_E + "nd", "NAVER Search Tr" + CYRILLIC_E + "nd", "tr" + ACUTE_E + "nd", "Tr" + ACUTE_E + "nds",
    "relative index", "relative interest", "Relative-Interest", "ratio", "Ratio", "the ratio", "interest index", "Interest Index", "관심지수", "검색 지수", "검색지수", "지수", "트랜드", "트렌드",
    "Tr3nd", "d4t4lab", "re1ative", "interest1ndex", "T R E N D", "T-R-E-N-D", "t.r.e.n.d", "데이터 랩", "상대 값", "상대 비율", "비율", "ＮＡＶＥＲ ＳｅａｒｃｈＴｒｅｎｄ",
)
HONEST_SOURCES = ("검색광고 키워드 도구", "NAVER SearchAd", "naver_searchad", "manual csv", "사람이 적음", "my notes", "수동 입력", "운영자가 확인한 값", "operation log", "migration notes",
                  "API integration report", "registration sheet", "calibration table", "generation log")


class SourceNameWordsTest(unittest.TestCase):
    # P2a(독립 검증 L1): 출처 이름 막기가 낱말 그대로만 보지 않는다 — 전각·악센트·키릴 닮은꼴·숫자 글자·띄어쓰기·기호로 바꿔 써도 상대값을 뜻하는 말이면 거절한다.
    def test_a_disguised_relative_value_word_is_refused_as_the_source_of_a_real_count(self):
        for source in DISGUISED_SOURCES:
            with self.subTest(source=source):
                self.assertTrue(md.trend_word_in(source), source)
                error = rejected(self, search_demand_count=50, search_count_source=source)
                self.assertIn("실제 검색 횟수의 출처", error.rendered().message)

    def test_an_honest_source_name_is_accepted_even_when_it_contains_the_letters_of_a_banned_word(self):
        for source in HONEST_SOURCES:
            with self.subTest(source=source):
                self.assertIsNone(md.trend_word_in(source), source)
                self.assertEqual(ts.make(search_demand_count=50, search_count_source=source).search_count_source, source)

    def test_ratio_and_index_count_only_as_whole_words_because_operation_and_integration_contain_them(self):
        for source in ("ratio", "Ratios", "index", "the index", "Indexes"):
            with self.subTest(source=source):
                self.assertIn(md.trend_word_in(source), ("ratio", "ratios", "index", "indexes"))
        for source in ("operation", "integration", "migration", "indexing tool"):
            with self.subTest(source=source):
                self.assertIsNone(md.trend_word_in(source))

    def test_the_word_that_was_found_is_reported(self):
        self.assertEqual(md.trend_word_in("Google Trends"), "trend")
        self.assertEqual(md.trend_word_in("NAVER DataLab"), "datalab")
        self.assertEqual(md.trend_word_in("관심도 조사"), "관심도")
        self.assertIsNone(md.trend_word_in("my notes"))

    def test_the_folding_keeps_hangul_whole_and_turns_look_alikes_into_latin_letters(self):
        self.assertEqual(md._fold("트렌드 데이터랩"), "트렌드 데이터랩")
        self.assertEqual(md._fold(fullwidth("TREND")), "trend")
        self.assertEqual(md._fold("tr" + CYRILLIC_E + "nd"), "trend")
        self.assertEqual(md._fold("tr" + ACUTE_E + "nd"), "trend")
        self.assertEqual(md._fold("Ａｂｃ１２３"), "abc123")

    def test_a_trend_service_is_still_refused_in_every_old_spelling(self):
        for source in ("NAVER Search Trend", "naver_search_trend", "네이버 데이터랩", "Datalab", "Google Trends", "트렌드 지수", "관심도 지수", "상대지수", "Search-Trend API", "상대값"):
            with self.subTest(source=source):
                rejected(self, search_demand_count=1, search_count_source=source)

    def test_the_check_applies_to_the_source_only_when_a_count_exists(self):
        self.assertIsNone(ts.make().search_count_source)
        rejected(self, search_count_source="relative index")

    def test_capital_look_alikes_from_cyrillic_and_greek_are_read_as_latin_letters_before_folding_to_lower_case(self):
        # P2b(독립 검증 L1): `ТRЕND`(키릴 대문자 Т·Е)·`ΤRΕΝD`(그리스 대문자 Τ·Ε·Ν)가 통과했다 — 소문자로 접으면 Τ→τ(표에 있음)이지만 Ν→ν 는 v 로 읽히고 Т→т 는 표에 없었다.
        cyrillic = chr(0x0422) + "R" + chr(0x0415) + "ND"
        greek = chr(0x03A4) + "R" + chr(0x0395) + chr(0x039D) + "D"
        for source in (cyrillic, greek, "NAVER " + cyrillic, greek + " API", chr(0x0422) + "r" + chr(0x0435) + "nd"):
            with self.subTest(source=source):
                self.assertEqual(md.trend_word_in(source), "trend")
                rejected(self, search_demand_count=5, search_count_source=source)
        self.assertEqual(md._fold(cyrillic), "trend")
        self.assertEqual(md._fold(greek), "trend")
        self.assertEqual(md._fold(chr(0x039D)), "n", "그리스 대문자 Ν 은 n 이다(소문자 ν 는 v)")
        self.assertEqual(md._fold(chr(0x03BD)), "v")

    def test_digits_and_symbols_that_stand_for_letters_are_read_also_inside_the_whole_words_ratio_and_index(self):
        # 독립 검증 L1: `r4tio`·`rati0`·`1ndex`·`tr€nd` 가 통과했다 — 숫자 글자는 낱말 조각만 보고 통째 낱말(ratio·index)에는 적용되지 않았다.
        for source in ("r4tio", "rati0", "R4TI0", "1ndex", "ind3x", "1nd3x", "the r4tio", "tr€nd", "TR€ND", "d4t4lab"):
            with self.subTest(source=source):
                self.assertTrue(md.trend_word_in(source), source)
                rejected(self, search_demand_count=5, search_count_source=source)

    def test_letters_spaced_out_one_by_one_are_joined_into_a_word_before_the_whole_word_check(self):
        for source in ("r a t i o", "r-a-t-i-o", "r.a.t.i.o", "i n d e x", "i-n-d-e-x", "NAVER r a t i o", "r a t i o and notes", "R A T I O"):
            with self.subTest(source=source):
                self.assertTrue(md.trend_word_in(source), source)
        for source in ("o p e r a t i o n", "a b c", "i o", "m i g r a t i o n", "r a t e", "x y index card".replace("index card", "z")):
            with self.subTest(honest=source):
                self.assertIsNone(md.trend_word_in(source), source)
                self.assertEqual(ts.make(search_demand_count=5, search_count_source=source).search_count_source, source)

    def test_the_message_names_the_word_that_was_found_and_never_echoes_the_whole_name(self):
        # 독립 검증 L1: 거절 문구가 어떤 낱말 때문인지 알려 주지 않았다 — 걸린 말은 이 모듈의 고정 목록에서 나오므로(입력 글이 아니다) 문구에 넣어도 안전하다.
        for source, word in (("Google Trends", "trend"), ("NAVER DataLab", "datalab"), ("상대 지수", "상대지수"), ("r a t i o", "ratio"), ("the index", "index")):
            with self.subTest(source=source):
                shown = rejected(self, search_demand_count=1, search_count_source=source).rendered().message
                self.assertIn(f"‘{word}’", shown)
                self.assertNotIn(source, shown.replace(f"‘{word}’", ""), "입력한 출처 이름을 그대로 되풀이하지 않는다")


class SafetyFlagsFieldTest(unittest.TestCase):
    # P2b: 규칙 기반 안전 표시(`safety.py`)를 담는 칸 — 닫힌 목록이고 표시일 뿐이다(후보를 지우거나 점수·구간을 바꾸지 않는다).
    def test_the_closed_list_is_exactly_these_names_so_adding_one_is_a_conscious_change(self):
        self.assertEqual(md.SAFETY_FLAGS, ("health_check", "product_brand", "experience_claim", "sponsor_disclosure", "result_promise"))
        self.assertTrue(all(ch.is_tag(name) for name in md.SAFETY_FLAGS))
        self.assertEqual(md.LABELS["safety_flags"], "안전 표시")

    def test_it_is_empty_by_default_and_every_listed_flag_is_accepted_in_any_order_once(self):
        self.assertEqual(ts.make().safety_flags, ())
        self.assertEqual(ts.make(safety_flags=list(md.SAFETY_FLAGS)).safety_flags, md.SAFETY_FLAGS)
        self.assertEqual(ts.make(safety_flags=("sponsor_disclosure", "health_check")).safety_flags, ("sponsor_disclosure", "health_check"))

    def test_an_unknown_repeated_or_wrongly_shaped_flag_list_is_refused(self):
        for bad in (("health",), ("HEALTH_CHECK",), ("health_check", "health_check"), "health_check", {"health_check"}, (None,), (3,), tuple(md.SAFETY_FLAGS) + ("health_check",), ("",)):
            with self.subTest(bad=repr(bad)[:30]):
                self.assertIn("안전 표시", rejected(self, safety_flags=bad).rendered().message)

    def test_the_flags_survive_the_json_round_trip_and_an_old_stored_candidate_without_them_still_loads(self):
        made = ts.make(safety_flags=("product_brand",))
        self.assertEqual(made.to_dict()["safety_flags"], ["product_brand"])
        self.assertEqual(md.TopicCandidate.from_dict(made.to_dict()), made)
        old = ts.make().to_dict()
        del old["safety_flags"]
        self.assertEqual(md.TopicCandidate.from_dict(old).safety_flags, ())

    def test_a_flag_changes_nothing_else_about_the_candidate(self):
        plain = ts.rated(70)
        flagged = dataclasses.replace(plain, safety_flags=("health_check",))
        self.assertEqual((flagged.recommendation_band, flagged.scores, flagged.work_status), (plain.recommendation_band, plain.scores, plain.work_status))


class DisplayIdLimitsTest(unittest.TestCase):
    # P2a(독립 검증 L4): 먼 미래 날짜에서 파이썬의 OverflowError 가 새지 않고 앱의 오류(AppError)로 나온다.
    def test_the_last_moment_that_still_fits_in_the_korean_calendar_works(self):
        self.assertEqual(md.display_id("9999-12-31T14:59:59Z", 1), "candidate-99991231-001")

    def test_one_second_later_would_be_the_year_10000_in_korea_and_gives_an_app_error(self):
        for stamp in ("9999-12-31T15:00:00Z", "9999-12-31T20:00:00Z", "9999-12-31T23:59:59Z"):
            with self.subTest(created_at=stamp):
                with self.assertRaises(AppError) as caught:
                    md.display_id(stamp, 1)
                self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")
                self.assertIn("한국 시간", caught.exception.rendered().message)

    def test_a_candidate_created_that_late_can_still_be_made_only_the_display_id_refuses(self):
        late = ts.make(created_at="9999-12-31T20:00:00Z")
        self.assertEqual(late.created_at, "9999-12-31T20:00:00Z")
        with self.assertRaises(AppError):
            md.display_id(late.created_at, 1)


class StoredIdTest(unittest.TestCase):
    # P2a(독립 검증 L9): 화면 표시 번호(`candidate-날짜-순번`)는 앞 8자가 모두 같아 명령줄의 '번호 앞 8자 선택' 으로 고를 수 없다 — 저장 번호로 쓰지 못하게 막는다.
    def test_a_display_id_cannot_be_a_stored_id(self):
        shown = md.display_id(ts.STAMP, 1)
        error = rejected(self, candidate_id=shown)
        self.assertIn("앞 8자", error.rendered().message)
        for bad in ("candidate-1", "Candidate-1", "CANDIDATE-X", "candidate_1", "candidates1", "candidat"):
            with self.subTest(candidate_id=bad):
                rejected(self, candidate_id=bad)

    def test_ordinary_ids_are_still_fine_and_are_told_apart_by_their_first_eight_characters(self):
        for good in ("cand0001", "c90-local-ai", "9f3a7c1e2b4d4a0e9c1d5b6a7f8e9d0c", "cand", "candy-1", "can-didate"):
            with self.subTest(candidate_id=good):
                self.assertEqual(ts.make(candidate_id=good).candidate_id, good)

    def test_the_rule_is_the_shared_short_id_length_not_a_number_of_its_own(self):
        self.assertEqual(cand.SHORT_ID, 8)
        self.assertTrue(md._DISPLAY_PREFIX.startswith("candidat"))
        self.assertEqual(md.stored_id("cand0001", "x"), "cand0001")
        for bad in (None, 3, "", "a b", "x" * 65, "가나다"):
            with self.subTest(value=bad):
                with self.assertRaises(AppError):
                    md.stored_id(bad, "x")

    def test_the_same_rule_holds_for_the_id_inside_a_link_and_when_reading_json(self):
        from chanceblog_desktop.topics import link
        for bad in ("candidate-20261104-001", "Candidate-9"):
            with self.subTest(engine_candidate_id=bad):
                with self.assertRaises(AppError):
                    link.CandidateLink(engine_candidate_id=bad, legacy_candidate_id=None, draft_plan_id=None, source_topic_id=None, seed_id=None, channel="naver_b")
                with self.assertRaises(AppError):
                    md.TopicCandidate.from_dict(dict(ts.make().to_dict(), candidate_id=bad))
        self.assertEqual(link.CandidateLink.of(ts.make()).engine_candidate_id, "cand0001")


class ScoreRecheckTest(unittest.TestCase):
    # P2a(독립 검증 M2): 저장된 점수가 항목 점수와 채널 가중치로 다시 계산한 값과 같은지 확인한다 — 거짓 묶음(항목 10·90 에 최종 80)을 거절한다.
    def test_an_honest_candidate_passes_for_every_channel(self):
        factors = sc.Factors(channel_fit=92, feasibility=85, differentiation=78, timing=80, evidence=82, monetization=88)
        partial = sc.Factors(channel_fit=60, timing=75)
        for key, profile in ts.PROFILES.items():
            for what in (factors, partial, sc.Factors()):
                with self.subTest(channel=key, factors=what.present()):
                    made = ts.make(channel=key, language="en" if key == "blogger_en" else "ko", scores=sc.score(profile, what).card)
                    self.assertIs(md.check_candidate_score(made, profile), made)

    def test_a_lying_final_score_is_refused_with_the_recomputed_number_in_plain_korean(self):
        liar = ts.make(scores=ts.card(80, channel_fit=10, timing=90))
        self.assertEqual(liar.recommendation_band, "RECOMMENDED", "거짓 카드는 모델만으로는 만들어지고 우수 후보 구간이다")
        with self.assertRaises(AppError) as caught:
            md.check_candidate_score(liar, ts.PROFILES["naver_b"])
        error = caught.exception
        self.assertEqual(error.code, "CANDIDATE_INVALID")
        shown = error.rendered().message
        for needle in ("최종 점수", "80", "46", "다시 계산한 값"):
            self.assertIn(needle, shown)

    def test_every_off_by_one_and_a_missing_final_are_refused(self):
        profile = ts.PROFILES["naver_b"]
        true_final = sc.score(profile, sc.Factors(channel_fit=10, timing=90)).final
        self.assertEqual(true_final, 46)
        for final in (45, 47, 10, 90, None):
            with self.subTest(final=final):
                with self.assertRaises(AppError):
                    md.check_candidate_score(ts.make(scores=ts.card(final, channel_fit=10, timing=90)), profile)
        md.check_candidate_score(ts.make(scores=ts.card(46, channel_fit=10, timing=90)), profile)

    def test_the_same_card_can_be_right_for_one_channel_and_wrong_for_another(self):
        factors = sc.Factors(channel_fit=90, timing=10)
        right = sc.score(ts.PROFILES["naver_b"], factors).final
        wrong_for_a = sc.score(ts.PROFILES["naver_a"], factors).final
        self.assertNotEqual(right, wrong_for_a)
        made = ts.make(scores=sc.ScoreCard(factors, right))
        md.check_candidate_score(made, ts.PROFILES["naver_b"])
        with self.assertRaises(AppError):
            md.check_candidate_score(dataclasses.replace(made, channel="naver_a"), ts.PROFILES["naver_a"])

    def test_the_profile_must_be_the_channel_of_the_candidate(self):
        made = ts.make(scores=sc.score(ts.PROFILES["naver_a"], sc.Factors(channel_fit=70)).card)
        with self.assertRaises(AppError) as caught:
            md.check_candidate_score(made, ts.PROFILES["naver_a"])
        self.assertIn("채널", caught.exception.rendered().message)

    def test_wrong_kinds_of_input_are_programming_errors(self):
        for args in ((None, ts.PROFILES["naver_b"]), (ts.make(), None), (ts.make().scores, ts.PROFILES["naver_b"]), (ts.make(), {"key": "naver_b"})):
            with self.subTest(args=type(args[0]).__name__):
                with self.assertRaises(TypeError):
                    md.check_candidate_score(*args)

    def test_no_score_at_all_is_consistent_with_itself(self):
        plain = ts.make()
        self.assertIs(md.check_candidate_score(plain, ts.PROFILES["naver_b"]), plain)


if __name__ == "__main__":
    unittest.main()
