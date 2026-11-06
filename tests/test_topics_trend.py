"""Trend 연결 틀(`topics/trend.py`) 시험 — 규약·'없음'·'가짜' 네 시나리오·느린 응답·공급자 오류에도 멈추지 않음·생성기로 이어지는 값(P3, D-60). 네트워크·파일·실제 시계·난수 없이 돈다.

지키는 것:
  1) '없음' 은 늘 '조회 안 함' 이고 값이 없다 — 엔진은 관심도 항목을 빼고 캘린더만으로 시기를 정한다(조회 불가·자료 부족과 다르다).
  2) 가짜의 네 시나리오(값 있음·자료 부족·조회 불가·느린 응답)는 정해진 값을 내고 같은 입력은 늘 같은 값이다.
  3) 장애(unavailable)와 자료 부족(insufficient)은 구분하고, 모든 키워드가 조회 불가일 때만 생성기에 '관심도 조회 불가' 로 알린다.
  4) 느린 응답은 기한을 넘을 때만(정각은 통과) 값을 버리고, 공급자가 오류·이상한 값을 줘도 멈추지 않고 안내에 남긴다.
  5) 상대값은 실제 검색 횟수 칸으로 흘러가지 않는다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import notice, trend  # noqa: E402

TODAY = "2026-11-10"
A = ts.PROFILES["naver_a"]


class Raises:
    name = "오류를 내는 공급자"

    def read(self, keyword, today):
        raise RuntimeError("연결할 수 없습니다 " + keyword)


class Garbage:
    name = "이상한 값을 주는 공급자"

    def read(self, keyword, today):
        return {"ratio": 5}


class Counting:
    name = "세는 공급자"

    def __init__(self):
        self.asked = []

    def read(self, keyword, today):
        self.asked.append(keyword)
        return trend.NOT_QUERIED


class NoneProviderTest(unittest.TestCase):
    def test_it_always_says_not_queried_and_has_no_value(self):
        provider = trend.NoTrend()
        for word in ("예시 키워드", "another keyword", ""):
            reading = provider.read(word, TODAY)
            self.assertIs(reading, trend.NOT_QUERIED)
            self.assertEqual((reading.queried, reading.trend_status, reading.trend_ratio, reading.trend_period, reading.trend_compared_group, reading.trend_queried_on, reading.data_status),
                             (False, "insufficient", None, None, (), None, "insufficient"))
        self.assertEqual(trend.check_reading(trend.NOT_QUERIED), trend.NOT_QUERIED)

    def test_collect_with_it_gives_nothing_to_the_engine_and_says_so_in_plain_words(self):
        result = trend.collect(trend.NoTrend(), ["예시 하나", "예시 둘"], TODAY)
        self.assertEqual((result.interest, result.outage), ({}, False))
        self.assertEqual(len(result.readings), 2)
        self.assertEqual(result.notes, ("관심도를 조회하지 않았습니다(캘린더만으로 시기 항목을 정합니다)",))

    def test_not_queried_is_different_from_unavailable_and_from_insufficient(self):
        self.assertNotEqual(trend.NOT_QUERIED, trend.UNAVAILABLE)
        self.assertFalse(trend.NOT_QUERIED.queried)
        self.assertTrue(trend.UNAVAILABLE.queried)
        self.assertEqual(trend.UNAVAILABLE.data_status, "unavailable")
        self.assertEqual(trend.NOT_QUERIED.data_status, "insufficient")


class FakeProviderTest(unittest.TestCase):
    def test_the_four_scenarios_with_hand_checked_values(self):
        value = trend.FakeTrend("value").read("예시 키워드", TODAY)
        self.assertEqual(value, trend.TrendReading(True, "rising", 73, "최근 1년", ("기준 키워드", "예시 키워드"), TODAY, "sufficient", 0.0))
        insufficient = trend.FakeTrend("insufficient").read("예시 키워드", TODAY)
        self.assertEqual((insufficient.queried, insufficient.trend_status, insufficient.trend_ratio, insufficient.data_status), (True, "insufficient", None, "insufficient"))
        self.assertEqual(trend.FakeTrend("unavailable").read("예시 키워드", TODAY), trend.UNAVAILABLE)
        slow = trend.FakeTrend("slow").read("예시 키워드", TODAY)
        self.assertEqual((slow.trend_ratio, slow.data_status, slow.elapsed_seconds), (73, "sufficient", trend.SLOW_SECONDS))
        self.assertGreater(slow.elapsed_seconds, trend.DEADLINE_SECONDS)

    def test_every_reading_it_makes_passes_the_check_and_values_follow_the_arguments(self):
        for scenario in trend.SCENARIOS:
            with self.subTest(scenario=scenario):
                trend.check_reading(trend.FakeTrend(scenario).read("예시 키워드", TODAY))
        fake = trend.FakeTrend("value", ratio=12, status="falling")
        reading = fake.read("예시 키워드", TODAY)
        self.assertEqual((reading.trend_ratio, reading.trend_status), (12, "falling"))
        self.assertEqual(trend.FakeTrend("value").read("예시 키워드", TODAY), trend.FakeTrend("value").read("예시 키워드", TODAY))

    def test_overrides_vary_the_scenario_by_keyword_and_the_calls_are_recorded(self):
        fake = trend.FakeTrend("value", overrides={"예시 둘": "unavailable", "Third Word": "insufficient"})
        self.assertEqual(fake.read("예시 하나", TODAY).data_status, "sufficient")
        self.assertEqual(fake.read("예시둘", TODAY).data_status, "unavailable", "키워드는 띄어쓰기를 가리지 않고 비교한다")
        self.assertEqual(fake.read("third word", TODAY).data_status, "insufficient")
        self.assertEqual(fake.calls, ["예시 하나", "예시둘", "third word"])

    def test_wrong_arguments_are_refused(self):
        for kwargs in ({"scenario": "fast"}, {"ratio": 101}, {"ratio": -1}, {"ratio": True}, {"ratio": 3.5}, {"status": "insufficient"}, {"status": "up"}, {"overrides": {"가": "fast"}}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    trend.FakeTrend(**kwargs)

    def test_the_compared_group_never_repeats_the_keyword(self):
        reading = trend.FakeTrend("value").read(trend.COMPARED_BASE, TODAY)
        self.assertEqual(reading.trend_compared_group, (trend.COMPARED_BASE,))
        trend.check_reading(reading)


class CheckAndInterpretTest(unittest.TestCase):
    def good(self, **changes):
        values = dict(queried=True, trend_status="rising", trend_ratio=70, trend_period="최근 1년", trend_compared_group=("기준", "예시"), trend_queried_on=TODAY, data_status="sufficient", elapsed_seconds=1.0)
        values.update(changes)
        return trend.TrendReading(**values)

    def test_a_good_reading_passes_and_each_broken_rule_is_refused(self):
        self.assertEqual(trend.check_reading(self.good()), self.good())
        bad = (
            {"trend_ratio": None},                                                   # 충분한데 값이 없다
            {"trend_status": "insufficient"},                                       # 충분한데 상태가 모른다
            {"data_status": "insufficient"},                                        # 부족한데 값이 있다
            {"data_status": "unavailable"},                                         # 불가인데 값이 있다
            {"queried": False},                                                     # 조회 안 했는데 값이 있다
            {"trend_ratio": 101}, {"trend_ratio": -1}, {"trend_ratio": True},       # 상대값 범위·종류
            {"trend_period": None}, {"trend_compared_group": ()}, {"trend_queried_on": None},   # 상대값에는 기간·그룹·조회일이 함께
            {"trend_queried_on": "어제"}, {"data_status": "great"}, {"trend_status": "up"},
            {"trend_compared_group": ["기준", "예시"]},                              # 목록이 아니라 튜플
            {"elapsed_seconds": -1}, {"elapsed_seconds": "3"}, {"elapsed_seconds": True}, {"elapsed_seconds": 100000},
            {"queried": "yes"},
        )
        for changes in bad:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    trend.check_reading(self.good(**changes))
        with self.assertRaises(ValueError):
            trend.check_reading({"trend_ratio": 5})

    def test_a_reading_without_values_must_have_none_not_zero(self):
        for changes in ({"trend_ratio": 0}, {"trend_period": "최근 1년"}, {"trend_compared_group": ("가",)}, {"trend_queried_on": TODAY}, {"trend_status": "flat"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    trend.check_reading(trend.UNAVAILABLE._replace(**changes))
        with self.assertRaises(ValueError):
            trend.check_reading(trend.UNAVAILABLE._replace(queried=False))

    def test_partial_data_is_allowed_and_keeps_its_value(self):
        partial = self.good(data_status="partial", trend_status="flat", trend_ratio=50)
        self.assertEqual(trend.interpret(partial), partial)

    def test_a_response_slower_than_the_deadline_is_dropped_and_exactly_the_deadline_is_kept(self):
        kept = trend.interpret(self.good(elapsed_seconds=trend.DEADLINE_SECONDS))
        self.assertEqual(kept.data_status, "sufficient")
        dropped = trend.interpret(self.good(elapsed_seconds=trend.DEADLINE_SECONDS + 0.001))
        self.assertEqual((dropped.queried, dropped.data_status, dropped.trend_ratio, dropped.trend_status), (True, "unavailable", None, "insufficient"))
        self.assertEqual(trend.interpret(self.good(elapsed_seconds=None)).data_status, "sufficient", "시간을 모르면 버리지 않는다")
        self.assertEqual(trend.interpret(self.good(elapsed_seconds=3), deadline=2).data_status, "unavailable")
        self.assertEqual(trend.interpret(self.good(elapsed_seconds=3), deadline=3).data_status, "sufficient")
        self.assertIs(trend.interpret(trend.NOT_QUERIED, deadline=0.001), trend.NOT_QUERIED, "조회 안 함은 느릴 수 없다")

    def test_a_wrong_deadline_is_refused(self):
        for deadline in (0, -1, True, "10", None):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ValueError):
                    trend.interpret(self.good(), deadline)


class CollectTest(unittest.TestCase):
    def test_values_go_to_the_interest_dictionary_by_keyword_key_and_nothing_else_does(self):
        fake = trend.FakeTrend("value", overrides={"예시 둘": "insufficient", "예시 셋": "unavailable"})
        result = trend.collect(fake, ["예시 하나", "예시 둘", "예시 셋"], TODAY)
        self.assertEqual(list(result.interest), ["예시하나"])
        self.assertEqual(result.interest["예시하나"], gn.InterestReading("rising", 73, "최근 1년", ("기준 키워드", "예시 하나"), TODAY))
        self.assertFalse(result.outage, "일부만 조회 불가이면 조회 불가가 아니다")
        self.assertEqual([reading.data_status for _word, reading in result.readings], ["sufficient", "insufficient", "unavailable"])

    def test_the_outage_flag_is_true_only_when_every_asked_keyword_is_unavailable(self):
        result = trend.collect(trend.FakeTrend("unavailable"), ["예시 하나", "예시 둘"], TODAY)
        self.assertEqual((result.interest, result.outage), ({}, True))
        self.assertIn("관심도를 조회할 수 없어 시기 항목은 캘린더만으로 정했습니다", result.notes)
        self.assertFalse(trend.collect(trend.FakeTrend("insufficient"), ["예시"], TODAY).outage, "자료 부족은 장애가 아니다")
        self.assertFalse(trend.collect(trend.FakeTrend("value", overrides={"예시 둘": "unavailable"}), ["예시 하나", "예시 둘"], TODAY).outage)
        self.assertFalse(trend.collect(trend.FakeTrend("value"), [], TODAY).outage, "조회한 것이 없으면 장애가 아니다")

    def test_a_slow_answer_is_treated_as_unavailable_with_a_note(self):
        result = trend.collect(trend.FakeTrend("slow"), ["예시 하나"], TODAY)
        self.assertEqual((result.interest, result.outage), ({}, True))
        self.assertTrue(any("10초를 넘긴" in note for note in result.notes))
        quick = trend.collect(trend.FakeTrend("slow", slow_seconds=2.0), ["예시 하나"], TODAY)
        self.assertEqual((list(quick.interest), quick.outage), (["예시하나"], False))
        longer = trend.collect(trend.FakeTrend("slow", slow_seconds=2.0), ["예시 하나"], TODAY, deadline=1)
        self.assertTrue(longer.outage)

    def test_partial_data_goes_to_the_engine_like_sufficient_data(self):
        class Partial:
            name = "일부만 주는 공급자"

            def read(self, keyword, today):
                return trend.TrendReading(True, "flat", 50, "최근 1년", ("기준", keyword), today, "partial", 1.0)

        result = trend.collect(Partial(), ["예시 하나"], TODAY)
        self.assertEqual(list(result.interest), ["예시하나"])
        self.assertEqual((result.interest["예시하나"].status, result.interest["예시하나"].ratio, result.outage), ("flat", 50, False))

    def test_a_provider_that_raises_or_gives_garbage_does_not_stop_the_engine(self):
        for provider in (Raises(), Garbage()):
            with self.subTest(provider=provider.name):
                result = trend.collect(provider, ["예시 하나", "예시 둘"], TODAY)
                self.assertEqual((result.interest, result.outage), ({}, True))
                self.assertEqual(len([note for note in result.notes if note.startswith("‘예시")]), 2, "키워드마다 안내가 남는다 — 조용히 삼키지 않는다")
        self.assertNotIn("RuntimeError", " ".join(trend.collect(Raises(), ["예시 하나"], TODAY).notes), "화면 글에 예외 이름을 쓰지 않는다")

    def test_a_failing_keyword_does_not_hide_the_good_ones(self):
        class Half:
            name = "절반만 되는 공급자"

            def read(self, keyword, today):
                if "나쁜" in keyword:
                    raise RuntimeError("x")
                return trend.FakeTrend("value").read(keyword, today)

        result = trend.collect(Half(), ["예시 좋은", "예시 나쁜", "예시 또 좋은"], TODAY)
        self.assertEqual(sorted(result.interest), ["예시또좋은", "예시좋은"])
        self.assertFalse(result.outage)

    def test_duplicates_are_asked_once_and_the_limit_is_applied_with_a_note(self):
        counting = Counting()
        trend.collect(counting, ["로컬 AI", "로컬ai", "LOCAL AI", "다른 말", "  ", "!!!"], TODAY)
        self.assertEqual(counting.asked, ["로컬 AI", "LOCAL AI", "다른 말"], "열쇠가 같은 것·글자가 없는 것은 묻지 않는다")
        many = [f"예시 키워드 {number}" for number in range(8)]
        counting = Counting()
        result = trend.collect(counting, many, TODAY, limit=3)
        self.assertEqual(counting.asked, many[:3])
        self.assertEqual(result.notes[0], "키워드가 8개라 앞의 3개만 조회했습니다")
        self.assertEqual(trend.collect(Counting(), many, TODAY, limit=8).notes[0], "관심도를 조회하지 않았습니다(캘린더만으로 시기 항목을 정합니다)")

    def test_wrong_inputs_are_refused(self):
        for call in (lambda: trend.collect(object(), ["가"], TODAY), lambda: trend.collect(trend.NoTrend(), "가나다", TODAY), lambda: trend.collect(trend.NoTrend(), [1], TODAY),
                     lambda: trend.collect(trend.NoTrend(), ["가"], TODAY, limit=0), lambda: trend.collect(trend.NoTrend(), ["가"], TODAY, limit=True)):
            with self.assertRaises((TypeError, ValueError)):
                call()

    def test_the_same_input_gives_the_same_result_whatever_the_order_of_equal_keywords(self):
        first = trend.collect(trend.FakeTrend("value"), ["가나 다", "라마"], TODAY)
        again = trend.collect(trend.FakeTrend("value"), ["가나 다", "라마"], TODAY)
        self.assertEqual(first, again)


class EngineIntegrationTest(unittest.TestCase):
    """생성기에 이어 보면 — 값 있음은 관심도 칸이 채워지고, 없음·부족은 캘린더만으로, 조회 불가는 자료 상태 unavailable 이다. 상대값은 실제 검색 횟수 칸으로 새지 않는다."""

    def world(self):
        pool = [ts.example_seed(seed_id="g1", keyword="예시 로봇청소기", major="가전", minor="소형가전"), ts.example_seed(seed_id="g2", keyword="예시 공기청정기", major="가전", minor="소형가전")]
        return pool, [ts.example_entry(keywords=("예시 로봇청소기",), name="예시 청소 시기", prep_start="10-15", publish_from="11-01", publish_to="11-30", peak="11-20")]

    def made(self, provider):
        pool, calendar = self.world()
        first = gn.generate(A, pool, calendar, (), TODAY, target=6)
        words = [candidate.primary_keyword for candidate in first.candidates]
        result = trend.collect(provider, words, TODAY)
        return gn.generate(A, pool, calendar, (), TODAY, target=6, interest=result.interest, interest_outage=result.outage), first, result

    def test_a_value_fills_the_interest_columns_and_never_the_search_count_column(self):
        again, first, result = self.made(trend.FakeTrend("value"))
        self.assertTrue(result.interest)
        filled = [candidate for candidate in again.candidates if candidate.trend_ratio is not None]
        self.assertTrue(filled)
        for candidate in filled:
            self.assertEqual((candidate.trend_status, candidate.trend_ratio, candidate.trend_period, candidate.trend_queried_on), ("rising", 73, "최근 1년", TODAY))
            self.assertIsNone(candidate.search_demand_count)
            self.assertIsNone(candidate.search_count_source)
        self.assertTrue(all(candidate.search_demand_count is None for candidate in again.candidates))

    def test_no_provider_gives_the_same_candidates_as_never_asking(self):
        again, first, result = self.made(trend.NoTrend())
        self.assertEqual([c.to_dict() for c in again.candidates], [c.to_dict() for c in first.candidates])
        self.assertTrue(all(candidate.trend_status == "insufficient" and candidate.trend_ratio is None for candidate in again.candidates))

    def test_an_outage_is_recorded_as_unavailable_and_still_produces_candidates(self):
        again, first, result = self.made(trend.FakeTrend("unavailable"))
        self.assertTrue(result.outage)
        self.assertEqual(len(again.candidates), len(first.candidates))
        self.assertTrue(all(candidate.data_status == "unavailable" for candidate in again.candidates))
        self.assertTrue(all(candidate.trend_ratio is None for candidate in again.candidates))

    def test_insufficient_data_is_recorded_as_insufficient_not_unavailable(self):
        again, first, result = self.made(trend.FakeTrend("insufficient"))
        self.assertFalse(result.outage)
        self.assertTrue(all(candidate.data_status == "insufficient" for candidate in again.candidates))

    def test_the_timing_score_changes_with_a_rising_value_but_every_candidate_still_scores(self):
        again, first, result = self.made(trend.FakeTrend("value"))
        self.assertNotEqual([c.scores.final for c in again.candidates], [c.scores.final for c in first.candidates])
        self.assertTrue(all(candidate.scores.final is not None for candidate in again.candidates))

    def test_the_notes_are_plain_korean_without_developer_marks(self):
        for provider in (trend.NoTrend(), trend.FakeTrend("unavailable"), trend.FakeTrend("slow"), Raises(), Garbage()):
            for note in trend.collect(provider, ["예시 하나"], TODAY).notes:
                with self.subTest(provider=provider.name, note=note):
                    self.assertTrue(notice.is_clean(note), note)


class PublicNamesTest(unittest.TestCase):
    def test_all_lists_exactly_the_public_names_and_the_dataclass_is_not_mutable_by_accident(self):
        for name in trend.__all__:
            self.assertTrue(hasattr(trend, name), name)
        self.assertEqual(len(set(trend.__all__)), len(trend.__all__))
        self.assertEqual(set(trend.SCENARIOS), {"value", "insufficient", "unavailable", "slow"})
        with self.assertRaises(AttributeError):
            trend.NOT_QUERIED.queried = True
        self.assertTrue(dataclasses.is_dataclass(gn.RealtimeItem))


class SlowNoteTest(unittest.TestCase):
    """'응답이 N초를 넘긴 키워드' 안내는 기한을 넘겨 값을 버린 것만 센다 — 값이 있거나 모자라거나 조회 불가인 응답은 세지 않는다."""

    WORDS = ["예시 하나", "예시 둘"]

    def slow_notes(self, provider):
        return [note for note in trend.collect(provider, self.WORDS, "2026-11-10").notes if "응답이" in note]

    def test_only_responses_that_overran_the_deadline_are_counted(self):
        for scenario in ("value", "insufficient", "unavailable"):
            with self.subTest(scenario=scenario):
                self.assertEqual(self.slow_notes(trend.FakeTrend(scenario)), [], "느린 응답이 아니면 안내하지 않는다")
        self.assertEqual(self.slow_notes(trend.FakeTrend("slow")), ["응답이 10초를 넘긴 키워드 2개는 값을 쓰지 않았습니다"])
        self.assertEqual(self.slow_notes(trend.FakeTrend("value", overrides={"예시 둘": "slow"})), ["응답이 10초를 넘긴 키워드 1개는 값을 쓰지 않았습니다"])

    def test_a_response_exactly_at_the_deadline_is_not_slow(self):
        self.assertEqual(self.slow_notes(trend.FakeTrend("slow", slow_seconds=10.0)), [])


if __name__ == "__main__":
    unittest.main()
