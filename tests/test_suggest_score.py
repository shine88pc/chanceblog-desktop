"""콘텐츠 작성 우선도·키워드 기회도 계산 틀(`content/suggest_score.py`) 시험.

지키는 것:
  1) 가중치는 합이 100 이고 값이 문서(`docs/DECISIONS.md` D-29)와 같다 — 값을 여기서 못박는다. 구간 경계(70·40)는 정확히 그 점수에서 갈린다.
  2) **'데이터 없음' 은 0점이 아니다** — 키워드 기회도가 없으면 그 요인을 빼고 나머지 가중치를 다시 나눈다. 기대값은 시험이 분수로 따로 계산한다(코드의 식을 복사하지 않는다).
  3) 키워드 기회도는 수요가 클수록 높고, 관련 블로그 검색 결과 수(경쟁)가 클수록 낮고, 관심도 변화가 상승일수록 높다(단조) — 값이 없는 하위 점수는 빼고 다시 나눈다.
  4) 조회일 경과일 경계: 정확히 30일은 아직 아니고 31일부터 '오래된 데이터', 조회일이 하루 뒤여도 0일.
"""
import sys
import unittest
from datetime import date
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.content import suggest_score as sc  # noqa: E402

TODAY = date(2026, 11, 3)


def exact(values, weights):
    """시험이 따로 구하는 가중 평균(분수) — 있는 요인만으로 다시 나눈다."""
    present = {name: Fraction(value).limit_denominator(10 ** 9) for name, value in values.items() if value is not None}
    total = sum(weights[name] for name in present)
    return sum(weights[name] * value for name, value in present.items()) / total


class ConstantsTest(unittest.TestCase):
    def test_the_published_weights_levels_and_thresholds(self):
        self.assertEqual(sc.WEIGHTS, {"fit": 30, "season": 20, "freshness": 20, "balance": 15, "opportunity": 15})
        self.assertEqual(sum(sc.WEIGHTS.values()), 100)
        self.assertEqual(set(sc.WEIGHTS), set(sc.FACTORS))
        self.assertEqual(set(sc.FACTOR_NAMES), set(sc.FACTORS))
        self.assertEqual(sc.FACTOR_NAMES["fit"], "블로그 프로필 적합도")
        self.assertEqual(sc.FACTOR_NAMES["opportunity"], "키워드 기회도")
        self.assertEqual((sc.HIGH_FROM, sc.MID_FROM, sc.HIGH, sc.MID, sc.LOW), (70, 40, "높음", "보통", "낮음"))
        self.assertEqual(sc.SEED_STRENGTH, {"주제": 90, "카테고리": 75, "태그": 60})
        self.assertEqual((sc.TYPE_BONUS, sc.SEASON_MATCH, sc.SEASON_RELATED, sc.SEASON_NEUTRAL, sc.SEASON_OFF), (10, 100, 70, 50, 30))
        self.assertEqual((sc.SIMILAR_FROM, sc.BALANCE_STEP, sc.STALE_DATA_DAYS), (0.6, 20, 30))
        self.assertEqual(sc.OPPORTUNITY_WEIGHTS, {"demand": 50, "competition": 30, "trend": 20})
        self.assertEqual((sc.DEMAND_FULL, sc.RESULTS_FULL), (100_000, 10_000_000))
        self.assertEqual(sc.TREND_POINTS, {"상승": 100, "보합": 50, "하락": 0})

    def test_the_levels_change_exactly_at_the_boundaries(self):
        for score, level in ((100, "높음"), (70.1, "높음"), (70, "높음"), (69.9, "보통"), (40.1, "보통"), (40, "보통"), (39.9, "낮음"), (0, "낮음")):
            self.assertEqual(sc.level_of(score), level, score)


class CombineTest(unittest.TestCase):
    def test_all_five_present_is_the_weighted_average_of_the_published_weights(self):
        values = {"fit": 90, "season": 70, "freshness": 100, "balance": 60, "opportunity": 40}
        priority, parts = sc.combine(values)
        self.assertEqual(priority.score, round(float(exact(values, sc.WEIGHTS)), 1))
        self.assertEqual(priority.score, 76.0)                      # (30·90 + 20·70 + 20·100 + 15·60 + 15·40) / 100 = 76.0
        self.assertEqual(priority.level, "높음")
        self.assertEqual([part.name for part in parts], list(sc.FACTORS))
        self.assertAlmostEqual(sum(part.share for part in parts), 1.0)
        self.assertAlmostEqual(sum(part.points for part in parts), 76.0)
        self.assertEqual([part.weight for part in parts], [30, 20, 20, 15, 15])

    def test_a_missing_factor_is_dropped_and_the_rest_are_renormalised_not_counted_as_zero(self):
        values = {"fit": 80, "season": 50, "freshness": 100, "balance": 100, "opportunity": None}
        priority, parts = sc.combine(values)
        self.assertEqual(priority.score, 81.2)                      # (30·80 + 20·50 + 20·100 + 15·100) / 85 = 81.176…
        self.assertEqual(priority.score, round(float(exact(values, sc.WEIGHTS)), 1))
        self.assertEqual([part.name for part in parts], ["fit", "season", "freshness", "balance"])
        self.assertAlmostEqual(sum(part.share for part in parts), 1.0)
        self.assertAlmostEqual(parts[0].share, 30 / 85)
        zero, _ = sc.combine({**values, "opportunity": 0})
        self.assertEqual(zero.score, 69.0)                          # 같은 값에서 기회도가 0점이면 (…+ 0) / 100 = 69.0 — 없는 것과 0점은 다르다
        self.assertNotEqual(zero.score, priority.score)

    def test_a_missing_factor_never_lowers_a_perfect_score(self):
        for dropped in sc.FACTORS:
            with self.subTest(dropped=dropped):
                priority, parts = sc.combine({name: (None if name == dropped else 100) for name in sc.FACTORS})
                self.assertEqual(priority.score, 100.0)
                self.assertNotIn(dropped, [part.name for part in parts])

    def test_one_factor_alone_is_its_own_value_and_nothing_at_all_is_none(self):
        priority, parts = sc.combine({"fit": None, "season": 33, "freshness": None, "balance": None})
        self.assertEqual((priority.score, priority.level, [part.share for part in parts]), (33.0, "낮음", [1.0]))
        self.assertEqual(sc.combine({}), (None, ()))
        self.assertEqual(sc.combine({name: None for name in sc.FACTORS}), (None, ()))

    def test_values_outside_zero_to_one_hundred_are_clamped_and_unknown_factors_refused(self):
        priority, parts = sc.combine({"fit": 250, "season": -40})
        self.assertEqual([part.value for part in parts], [100.0, 0.0])
        self.assertEqual(priority.score, exact({"fit": 100, "season": 0}, sc.WEIGHTS) and round(float(exact({"fit": 100, "season": 0}, sc.WEIGHTS)), 1))
        with self.assertRaises(ValueError):
            sc.combine({"fit": 50, "luck": 90})

    def test_each_weight_moves_the_score_by_exactly_its_share(self):
        base = {name: 50 for name in sc.FACTORS}
        for name, weight in sc.WEIGHTS.items():
            raised = sc.combine({**base, name: 100})[0].score
            self.assertEqual(raised, round(50 + weight * 50 / 100, 1), name)

    def test_the_score_is_rounded_to_one_decimal_and_the_level_follows_the_rounded_score(self):
        priority, _ = sc.combine({"fit": 100, "season": 100, "freshness": 100, "balance": 100, "opportunity": 0})
        self.assertEqual((priority.score, priority.level), (85.0, "높음"))
        priority, _ = sc.combine({"fit": 50, "season": 100, "freshness": 0, "balance": 0, "opportunity": None})
        self.assertEqual(priority.score, round(float(Fraction(30 * 50 + 20 * 100, 85)), 1))
        self.assertEqual(priority.score, 41.2)
        self.assertEqual(priority.level, "보통")


class SmallScoresTest(unittest.TestCase):
    def test_fit_adds_the_bonus_only_for_the_profile_post_type_and_caps_at_one_hundred(self):
        self.assertEqual(sc.fit_score(90, True), 100)
        self.assertEqual(sc.fit_score(90, False), 90)
        self.assertEqual(sc.fit_score(75, True), 85)
        self.assertEqual(sc.fit_score(60, True), 70)
        self.assertEqual(sc.fit_score(60, False), 60)
        self.assertEqual(sc.fit_score(95, True), 100)

    def test_freshness_falls_in_a_straight_line_to_zero_at_the_similarity_threshold(self):
        self.assertEqual(sc.freshness_score(0), 100)
        self.assertAlmostEqual(sc.freshness_score(0.3), 50.0)
        self.assertAlmostEqual(sc.freshness_score(0.15), 75.0)
        self.assertEqual(sc.freshness_score(0.6), 0.0)
        self.assertEqual(sc.freshness_score(0.9), 0.0)
        self.assertEqual(sc.freshness_score(-0.5), 100.0)

    def test_balance_loses_twenty_per_existing_post_and_stops_at_zero(self):
        self.assertEqual([sc.balance_score(count) for count in range(8)], [100, 80, 60, 40, 20, 0, 0, 0])


class OpportunityTest(unittest.TestCase):
    def test_nothing_known_is_none_not_zero(self):
        self.assertIsNone(sc.opportunity())
        self.assertIsNone(sc.opportunity(None, None, None))
        self.assertEqual(sc.opportunity(0), 0.0, "수요 0회는 '없음' 이 아니라 0점이다")

    def test_one_part_alone_is_that_part(self):
        self.assertAlmostEqual(sc.opportunity(search_demand=100_000), 100.0)
        self.assertAlmostEqual(sc.opportunity(search_demand=10_000_000), 100.0, msg="가득 찬 뒤에는 더 오르지 않는다")
        self.assertAlmostEqual(sc.opportunity(search_demand=0), 0.0)
        self.assertAlmostEqual(sc.opportunity(related_blog_results=10_000_000), 0.0)
        self.assertAlmostEqual(sc.opportunity(related_blog_results=0), 100.0)
        self.assertEqual([sc.opportunity(trend=item) for item in ("상승", "보합", "하락")], [100.0, 50.0, 0.0])

    def test_two_and_three_parts_use_the_published_weights_and_renormalise(self):
        self.assertAlmostEqual(sc.opportunity(search_demand=100_000, trend="하락"), (50 * 100 + 20 * 0) / 70)
        self.assertAlmostEqual(sc.opportunity(related_blog_results=0, trend="상승"), (30 * 100 + 20 * 100) / 50)
        self.assertAlmostEqual(sc.opportunity(search_demand=100_000, related_blog_results=10_000_000, trend="보합"), (50 * 100 + 30 * 0 + 20 * 50) / 100)

    def test_a_bigger_demand_never_lowers_the_opportunity_and_below_the_cap_raises_it(self):
        demands = [0, 1, 10, 100, 1000, 10_000, 100_000, 1_000_000]
        values = [sc.opportunity(search_demand=item, related_blog_results=50_000, trend="보합") for item in demands]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(left < right for left, right in zip(values[:6], values[1:7], strict=True)), values)
        self.assertEqual(values[-1], values[-2], "수요가 가득 찬 뒤에는 같다")

    def test_more_blog_results_means_more_competition_and_a_lower_opportunity(self):
        results = [0, 1, 10, 1000, 100_000, 1_000_000, 10_000_000, 99_000_000]
        values = [sc.opportunity(search_demand=5000, related_blog_results=item, trend="보합") for item in results]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertTrue(all(left > right for left, right in zip(values[:7], values[1:8], strict=True)) or values[-1] == values[-2], values)

    def test_a_rising_interest_beats_flat_beats_falling(self):
        up, flat, down = (sc.opportunity(search_demand=5000, related_blog_results=50_000, trend=item) for item in ("상승", "보합", "하락"))
        self.assertTrue(up > flat > down, (up, flat, down))

    def test_an_unknown_trend_is_refused_not_scored(self):
        with self.assertRaises(ValueError):
            sc.opportunity(search_demand=10, trend="폭등")

    def test_negative_numbers_do_not_break_the_scale(self):
        self.assertAlmostEqual(sc.opportunity(search_demand=-5), 0.0)


class DataAgeTest(unittest.TestCase):
    def test_a_date_two_or_more_days_ahead_is_called_out_as_a_likely_typo(self):
        for ahead in (2, 30, 3650):
            day = date.fromordinal(TODAY.toordinal() + ahead).isoformat()
            with self.subTest(ahead=ahead):
                age = sc.data_age(day, TODAY)
                self.assertEqual((age.days, age.stale, age.future), (0, False, True))
                self.assertIn("오늘보다 앞선 날짜", age.text())
                self.assertIn(day, age.text())
                self.assertNotIn("오늘 조회", age.text())
                self.assertEqual(age.to_dict(), {"data_date": day, "days_ago": 0, "stale": False, "future": True})
        self.assertFalse(sc.data_age("2026-11-03", TODAY).future)
        self.assertFalse(sc.data_age("2026-11-04", TODAY).future, "하루 앞은 시간대 차이로 본다")

    def test_no_date_means_no_external_data(self):
        age = sc.data_age(None, TODAY)
        self.assertEqual((age.data_date, age.days, age.stale), (None, None, False))
        self.assertEqual(age.text(), "외부 데이터 없음")
        self.assertEqual(age.to_dict(), {"data_date": None, "days_ago": None, "stale": False, "future": False})

    def test_days_ago_and_the_stale_boundary_at_thirty_days(self):
        for days, stale in ((0, False), (1, False), (29, False), (30, False), (31, True), (90, True)):
            day = date.fromordinal(TODAY.toordinal() - days).isoformat()
            with self.subTest(days=days):
                age = sc.data_age(day, TODAY)
                self.assertEqual((age.days, age.stale), (days, stale))
                self.assertEqual("오래된 데이터" in age.text(), stale)
                self.assertIn(day, age.text())
        self.assertIn("오늘 조회", sc.data_age("2026-11-03", TODAY).text())
        self.assertIn("1일 전 조회", sc.data_age("2026-11-02", TODAY).text())
        self.assertIn("33일 전 조회", sc.data_age("2026-10-01", TODAY).text())

    def test_a_date_one_day_ahead_counts_as_today_and_a_bad_date_is_refused(self):
        age = sc.data_age("2026-11-04", TODAY)
        self.assertEqual((age.days, age.stale, age.future), (0, False, False))
        self.assertIn("오늘 조회", age.text())
        for bad in ("2026-13-01", "20261101", "어제", "2026-11-31"):
            with self.assertRaises(ValueError):
                sc.data_age(bad, TODAY)


class SeasonFitTest(unittest.TestCase):
    def test_the_season_word_itself_scores_a_match_and_a_related_word_scores_related_and_the_rest_neutral(self):
        score, item = sc.season_fit("김장 재료 정리", 11)
        self.assertEqual((score, item.word), (100, "김장"))
        score, item = sc.season_fit("보일러 점검", 11)
        self.assertEqual(score, 70)
        self.assertIn(item.word, ("난방", "난방 준비", "월동 준비"))
        self.assertEqual(sc.season_fit("자전거 타기", 11), (50, None))
        self.assertEqual(sc.season_fit("", 11), (50, None))

    def test_the_same_text_scores_differently_in_a_different_month(self):
        self.assertEqual(sc.season_fit("김장 재료", 11)[0], 100)
        self.assertEqual(sc.season_fit("김장 재료", 6)[0], 50)
        self.assertEqual(sc.season_fit("장마 대비", 7)[0], 100)

    def test_related_items_lists_the_month_entries_that_connect_in_table_order(self):
        found = sc.related_items("보일러 점검", 11)
        self.assertTrue(found)
        self.assertEqual([item.word for item in found], [item.word for item in sc.SEASONS[11] if item in found])
        self.assertEqual(sc.related_items("자전거", 11), ())
        self.assertEqual(sc.related_items("", 11), ())

    def test_a_one_letter_word_does_not_connect_to_everything(self):
        self.assertEqual(sc.season_fit("눈", 1), (50, None))
        self.assertEqual(sc.season_fit("눈", 11), (50, None), "11월에는 '눈길' 이 이어지는 낱말이라도 한 글자 '눈' 만으로는 이어지지 않는다")
        self.assertEqual(sc.season_fit("차", 11), (50, None), "'자동차' 에 '차' 가 들어 있어도")
        self.assertEqual(sc.related_items("눈", 11), ())

    def test_the_month_is_checked(self):
        self.assertEqual(sc.month_of(12), 12)
        for bad in (0, 13, -1, "5", None, True, 1.0):
            with self.assertRaises(ValueError):
                sc.month_of(bad)


if __name__ == "__main__":
    unittest.main()
