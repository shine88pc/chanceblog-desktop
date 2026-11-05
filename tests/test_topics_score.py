"""6항목 점수·추천 구간·시기 항목 점수표 시험.

지키는 것:
  1) '모름'은 0점이 아니다 — 평가 불가(None) 항목은 빼고 남은 가중치를 100 으로 다시 나눈다(항목 하나·둘·전부 없음). 전부 없으면 최종은 None, 구간은 UNRATED 다.
  2) 반올림은 한 곳(`round_half_up`)이고 0.5 는 올린다(79.5 → 80, 78.5 → 79). 구간 경계는 반올림한 정수에 적용한다(49/50·64/65·79/80).
  3) 점수는 단조롭다(한 항목을 올리면 최종이 내려가지 않는다)·가중 평균이라 가장 낮은 항목과 가장 높은 항목 사이에 있다·기존 `suggest_score.combine` 과 같은 규칙이다.
  4) 시기 항목 점수표는 손으로 쓴 값으로 모든 칸을 못박고, 관심도를 쓰지 않는 채널(none)은 관심도를 아예 보지 않는다.
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import dataclasses
import itertools
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.content import suggest_score as old  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import score as sc  # noqa: E402

NAMES = ch.FACTOR_NAMES


def factors(*values):
    return sc.Factors(**dict(zip(NAMES, values, strict=True)))


def reference_final(profile, values):
    """독립 계산 — 분수로 정확히 구한 가중 평균을 0.5 올림해 정수로."""
    used = sum(profile.weights[name] for name, value in zip(NAMES, values, strict=True) if value is not None)
    if not used:
        return None
    total = sum(profile.weights[name] * value for name, value in zip(NAMES, values, strict=True) if value is not None)
    return int(Fraction(total, used) + Fraction(1, 2))


def two_factor_profile(first=50, second=50):
    """채널 적합도와 작성 가능성만 가중치를 가진 프로필 — 반올림 경계를 정확히 만들기 위한 시험용이다."""
    weights = {name: 0 for name in NAMES}
    weights["channel_fit"], weights["feasibility"] = first, second
    return dataclasses.replace(ts.PROFILES["naver_b"], weights=weights)


class RoundingTest(unittest.TestCase):
    def test_half_goes_up_and_below_half_goes_down(self):
        for numerator, denominator, expected in ((159, 2, 80), (7949, 100, 79), (7951, 100, 80), (157, 2, 79), (129, 2, 65), (99, 2, 50), (1, 2, 1), (0, 5, 0), (7, 1, 7), (199, 2, 100),
                                                 (1, 3, 0), (2, 3, 1), (5, 4, 1), (7, 4, 2)):
            with self.subTest(fraction=f"{numerator}/{denominator}"):
                self.assertEqual(sc.round_half_up(numerator, denominator), expected)

    def test_it_is_not_python_round_which_rounds_halves_to_even(self):
        self.assertEqual(round(78.5), 78)
        self.assertEqual(sc.round_half_up(157, 2), 79)
        self.assertEqual(round(0.5), 0)
        self.assertEqual(sc.round_half_up(1, 2), 1)

    def test_an_exact_half_in_a_real_score_rounds_up_and_just_below_rounds_down(self):
        profile = two_factor_profile()
        for pair, expected in (((80, 79), 80), ((79, 79), 79), ((65, 64), 65), ((64, 64), 64), ((50, 49), 50), ((49, 49), 49), ((78, 79), 79), ((0, 1), 1), ((99, 100), 100), ((0, 0), 0)):
            with self.subTest(pair=pair):
                result = sc.score(profile, sc.Factors(channel_fit=pair[0], feasibility=pair[1]))
                self.assertEqual(result.final, expected)

    def test_the_boundary_scores_land_in_the_right_band_through_score(self):
        profile = two_factor_profile()
        for pair, band in (((80, 79), sc.BAND_RECOMMENDED), ((79, 79), sc.BAND_GENERAL), ((65, 64), sc.BAND_GENERAL), ((64, 64), sc.BAND_HOLD), ((50, 49), sc.BAND_HOLD),
                           ((49, 49), sc.BAND_EXCLUDED)):
            with self.subTest(pair=pair):
                self.assertEqual(sc.score(profile, sc.Factors(channel_fit=pair[0], feasibility=pair[1])).band, band)


class BandTest(unittest.TestCase):
    def test_the_four_bands_and_their_edges(self):
        for final, band in ((100, "RECOMMENDED"), (80, "RECOMMENDED"), (79, "GENERAL"), (65, "GENERAL"), (64, "HOLD"), (50, "HOLD"), (49, "EXCLUDED"), (0, "EXCLUDED")):
            with self.subTest(final=final):
                self.assertEqual(sc.band_of(final), band)

    def test_no_score_is_unrated_and_not_excluded(self):
        self.assertEqual(sc.band_of(None), "UNRATED")
        self.assertNotEqual(sc.band_of(None), sc.band_of(0))

    def test_the_band_names_and_korean_labels(self):
        self.assertEqual(sc.BANDS, ("RECOMMENDED", "GENERAL", "HOLD", "EXCLUDED", "UNRATED"))
        self.assertEqual(dict(sc.BAND_KO), {"RECOMMENDED": "우선 추천", "GENERAL": "일반 후보", "HOLD": "보류함(점수 구간)", "EXCLUDED": "제외", "UNRATED": "점수 없음"})

    def test_a_final_score_outside_zero_to_one_hundred_or_not_an_integer_is_refused(self):
        for bad in (-1, 101, 79.5, 80.0, True, "80"):
            with self.subTest(final=bad):
                with self.assertRaises(ValueError):
                    sc.band_of(bad)

    def test_the_cutoffs_come_from_the_shared_constant(self):
        recommended, general, hold = ch.GRADE_CUTOFFS
        self.assertEqual((sc.band_of(recommended), sc.band_of(recommended - 1)), ("RECOMMENDED", "GENERAL"))
        self.assertEqual((sc.band_of(general), sc.band_of(general - 1)), ("GENERAL", "HOLD"))
        self.assertEqual((sc.band_of(hold), sc.band_of(hold - 1)), ("HOLD", "EXCLUDED"))


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.profile = ts.PROFILES["naver_b"]          # 25/15/10/20/10/20

    def test_all_six_present_is_the_plain_weighted_average(self):
        result = sc.score(self.profile, factors(92, 85, 78, 80, 82, 88))
        self.assertEqual(result.final, 85)             # 85.35 → 85
        self.assertEqual((result.used_weight, result.missing), (100, ()))
        self.assertEqual([(part.name, part.value, part.weight) for part in result.parts],
                         [("channel_fit", 92, 25), ("feasibility", 85, 15), ("differentiation", 78, 10), ("timing", 80, 20), ("evidence", 82, 10), ("monetization", 88, 20)])

    def test_one_missing_factor_is_left_out_and_the_rest_is_divided_again(self):
        result = sc.score(self.profile, factors(92, 85, 78, None, 82, 88))
        self.assertEqual(result.final, 87)             # (2300+1275+780+820+1760)/80 = 86.69 → 87
        self.assertEqual((result.used_weight, result.missing), (80, ("timing",)))
        self.assertEqual([part.name for part in result.parts], ["channel_fit", "feasibility", "differentiation", "evidence", "monetization"])

    def test_two_missing_factors(self):
        result = sc.score(self.profile, factors(60, None, None, 40, 50, 70))
        self.assertEqual(result.final, reference_final(self.profile, (60, None, None, 40, 50, 70)))
        self.assertEqual(result.final, 56)             # (25*60 + 20*40 + 10*50 + 20*70) / 75 = 4200 / 75
        self.assertEqual((result.used_weight, result.missing), (75, ("feasibility", "differentiation")))

    def test_missing_is_not_zero(self):
        with_zero = sc.score(self.profile, factors(90, 90, 90, 0, 90, 90)).final
        left_out = sc.score(self.profile, factors(90, 90, 90, None, 90, 90)).final
        self.assertEqual(left_out, 90)
        self.assertLess(with_zero, left_out)

    def test_a_single_present_factor_is_the_whole_score(self):
        for index, name in enumerate(NAMES):
            with self.subTest(factor=name):
                values = [None] * 6
                values[index] = 73
                self.assertEqual(sc.score(self.profile, factors(*values)).final, 73)

    def test_no_factor_at_all_means_no_score_not_zero(self):
        result = sc.score(self.profile, factors(*[None] * 6))
        self.assertIsNone(result.final)
        self.assertEqual((result.used_weight, result.parts, result.missing), (0, (), NAMES))
        self.assertEqual(result.band, "UNRATED")
        self.assertEqual(sc.score(self.profile, sc.Factors()).final, None)

    def test_only_a_zero_weight_factor_present_means_nothing_to_weigh(self):
        weights = {name: 0 for name in NAMES}
        weights["channel_fit"] = 100
        profile = dataclasses.replace(self.profile, weights=weights)
        result = sc.score(profile, sc.Factors(timing=90))
        self.assertIsNone(result.final)
        self.assertEqual(result.used_weight, 0)
        self.assertEqual(sc.score(profile, sc.Factors(timing=90, channel_fit=40)).final, 40)

    def test_every_default_channel_matches_an_independent_calculation(self):
        patterns = ((92, 85, 78, 80, 82, 88), (0, 0, 0, 0, 0, 0), (100,) * 6, (10, 20, 30, 40, 50, 60), (None, 100, None, 0, None, 55), (33, None, 66, None, 99, None), (1, 2, 3, None, None, None))
        for key, profile in ts.PROFILES.items():
            for values in patterns:
                with self.subTest(channel=key, values=values):
                    self.assertEqual(sc.score(profile, factors(*values)).final, reference_final(profile, values))

    def test_the_final_score_lies_between_the_lowest_and_highest_present_factor(self):
        grid = (0, 17, 50, 83, 100)
        for key, profile in ts.PROFILES.items():
            for values in itertools.product(grid, repeat=3):
                factor_values = (values[0], values[1], None, values[2], values[0], None)
                present = [value for value in factor_values if value is not None]
                with self.subTest(channel=key, values=factor_values):
                    self.assertTrue(min(present) <= sc.score(profile, factors(*factor_values)).final <= max(present))

    def test_raising_one_factor_never_lowers_the_final_score(self):
        bases = ((50,) * 6, (0,) * 6, (30, None, 60, 90, None, 10), (None, None, 20, None, None, 80), (100, 0, 100, 0, 100, 0))
        for key, profile in ts.PROFILES.items():
            for base in bases:
                for index, name in enumerate(NAMES):
                    if base[index] is None:
                        continue
                    previous = -1
                    for value in range(0, 101, 5):
                        values = list(base)
                        values[index] = value
                        final = sc.score(profile, factors(*values)).final
                        with self.subTest(channel=key, base=base, raised=name, value=value):
                            self.assertGreaterEqual(final, previous)
                        previous = final

    def test_score_wants_a_profile_and_factors(self):
        for profile, values in ((None, sc.Factors()), (self.profile, None), (self.profile, {"channel_fit": 50}), ({"key": "naver_b"}, sc.Factors()), (self.profile, factors(1, 2, 3, 4, 5, 6).to_dict())):
            with self.subTest(profile=type(profile).__name__, values=type(values).__name__):
                with self.assertRaises(TypeError):
                    sc.score(profile, values)

    def test_the_result_can_be_stored_as_a_score_card(self):
        result = sc.score(self.profile, factors(92, 85, 78, 80, 82, 88))
        self.assertEqual(result.card, sc.ScoreCard(result.factors, 85))
        self.assertEqual(result.card.band, result.band)
        self.assertEqual(sc.score(self.profile, sc.Factors()).card, sc.ScoreCard())

    def test_the_same_input_gives_the_same_result_every_time(self):
        first = sc.score(self.profile, factors(92, 85, 78, None, 82, 88))
        for _ in range(5):
            self.assertEqual(sc.score(self.profile, factors(92, 85, 78, None, 82, 88)), first)


class SameRuleAsTheOldScoreTest(unittest.TestCase):
    """기존 5요인 우선도(`content.suggest_score.combine`)와 '없는 요인은 빼고 다시 나눈다' 규칙이 같은지 — 같은 가중치를 가진 프로필로 같은 입력을 넣어 본다."""
    MAPPING = {"fit": "channel_fit", "season": "timing", "freshness": "differentiation", "balance": "feasibility", "opportunity": "evidence"}

    def profile(self):
        weights = {name: 0 for name in NAMES}
        for old_name, new_name in self.MAPPING.items():
            weights[new_name] = old.WEIGHTS[old_name]
        return dataclasses.replace(ts.PROFILES["naver_b"], weights=weights)

    def test_the_results_agree_for_every_pattern_of_missing_factors(self):
        profile = self.profile()
        levels = (None, 0, 37, 100)
        for combo in itertools.product(levels, repeat=5):
            old_values = dict(zip(self.MAPPING, combo, strict=True))
            new_values = {self.MAPPING[name]: value for name, value in old_values.items()}
            with self.subTest(values=combo):
                priority, parts = old.combine(old_values)
                result = sc.score(profile, sc.Factors(**new_values))
                if priority is None:
                    self.assertIsNone(result.final)
                    self.assertEqual(parts, ())
                    continue
                self.assertLessEqual(abs(priority.score - result.final), 0.55)
                self.assertEqual(result.final, reference_final(profile, [new_values.get(name) for name in NAMES]))
                self.assertEqual({part.name for part in result.parts}, {self.MAPPING[part.name] for part in parts})
                self.assertEqual(result.used_weight, sum(part.weight for part in parts))

    def test_the_new_score_does_not_change_the_old_one(self):
        self.assertEqual(old.WEIGHTS, {"fit": 30, "season": 20, "freshness": 20, "balance": 15, "opportunity": 15})
        self.assertEqual((old.HIGH_FROM, old.MID_FROM), (70, 40))


class FactorsAndCardTest(unittest.TestCase):
    def test_a_factor_is_none_or_an_integer_from_zero_to_one_hundred(self):
        for bad in (-1, 101, 50.5, 50.0, True, "50", [50]):
            for name in NAMES:
                with self.subTest(factor=name, value=bad):
                    with self.assertRaises(AppError) as caught:
                        sc.Factors(**{name: bad})
                    self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")
        self.assertEqual(sc.Factors(channel_fit=0, feasibility=100).present(), (("channel_fit", 0), ("feasibility", 100)))

    def test_present_lists_only_the_evaluated_factors_in_order(self):
        self.assertEqual(factors(None, 5, None, 7, None, 9).present(), (("feasibility", 5), ("timing", 7), ("monetization", 9)))
        self.assertEqual(sc.Factors().present(), ())

    def test_factors_round_trip_and_are_strict(self):
        value = factors(1, None, 3, None, 5, 6)
        self.assertEqual(sc.Factors.from_dict(value.to_dict()), value)
        self.assertEqual(list(value.to_dict()), list(NAMES))
        broken = value.to_dict()
        del broken["timing"]
        for bad in (broken, {**value.to_dict(), "extra": 1}, None, [], "x"):
            with self.assertRaises(AppError):
                sc.Factors.from_dict(bad)

    def test_a_card_with_a_final_score_needs_evaluated_factors_and_the_final_inside_their_range(self):
        with self.assertRaises(AppError):
            sc.ScoreCard(sc.Factors(), 50)
        with self.assertRaises(AppError):
            sc.ScoreCard(factors(40, 60, None, None, None, None), 61)
        with self.assertRaises(AppError):
            sc.ScoreCard(factors(40, 60, None, None, None, None), 39)
        self.assertEqual(sc.ScoreCard(factors(40, 60, None, None, None, None), 40).final, 40)
        self.assertEqual(sc.ScoreCard(factors(40, 60, None, None, None, None), 60).final, 60)
        self.assertEqual(sc.ScoreCard(factors(40, 60, None, None, None, None)).final, None)

    def test_a_card_rejects_a_bad_final_and_a_bad_factors_object(self):
        for bad in (-1, 101, 50.5, True, "50"):
            with self.assertRaises(AppError):
                sc.ScoreCard(factors(*[50] * 6), bad)
        with self.assertRaises(AppError):
            sc.ScoreCard({"channel_fit": 50}, None)

    def test_the_empty_card_means_no_score(self):
        self.assertEqual(sc.ScoreCard().to_dict(), {**{name: None for name in NAMES}, "final": None})
        self.assertEqual(sc.ScoreCard().band, "UNRATED")

    def test_the_card_round_trips_with_the_final_score_next_to_the_six_factors(self):
        card = ts.card(85, channel_fit=92, feasibility=85, differentiation=78, timing=80, evidence=82, monetization=88)
        self.assertEqual(list(card.to_dict()), [*NAMES, "final"])
        self.assertEqual(sc.ScoreCard.from_dict(card.to_dict()), card)

    def test_the_card_is_read_strictly(self):
        good = ts.card(85, channel_fit=92, feasibility=85, differentiation=78, timing=80, evidence=82, monetization=88).to_dict()
        missing = dict(good)
        del missing["final"]
        for bad in (missing, {**good, "extra": 1}, {**good, "final": 100}, None, [], "x"):
            with self.assertRaises(AppError):
                sc.ScoreCard.from_dict(bad)


TREND_CELLS = {                                     # 손으로 쓴 점수표
    ("due", "rising"): 90, ("due", "flat"): 70, ("due", "falling"): 40,
    ("out_of_range", "rising"): 70, ("out_of_range", "flat"): 20, ("out_of_range", "falling"): 10,
    ("unknown", "rising"): 70, ("unknown", "flat"): 50, ("unknown", "falling"): 30,
}
CALENDAR_ONLY = {"due": 60, "out_of_range": 20, "unknown": None}


class CardCheckTest(unittest.TestCase):
    # P2a(독립 검증 M2): `ScoreCard` 는 '최소~최대 사이' 까지만 보므로, 저장된 점수가 채널 가중치로 다시 계산한 값과 같은지는 `check_card` 가 따로 확인한다.
    B = ts.PROFILES["naver_b"]

    def test_the_card_alone_cannot_tell_a_lying_final_score_from_an_honest_one(self):
        liar = sc.ScoreCard(factors(10, None, None, 90, None, None), 80)             # 항목 10·90 에 최종 80 — 받아들여진다(최소 10 ~ 최대 90 사이)
        self.assertEqual(liar.band, sc.BAND_RECOMMENDED)

    def test_the_recomputed_card_passes_for_every_channel_and_every_pattern_of_missing_factors(self):
        values = (92, 55, 70, 100, 0, 38)
        for key, profile in ts.PROFILES.items():
            for mask in itertools.product((True, False), repeat=6):
                shown = [value if keep else None for value, keep in zip(values, mask, strict=True)]
                with self.subTest(channel=key, factors=shown):
                    card = sc.score(profile, factors(*shown)).card
                    self.assertIs(sc.check_card(profile, card), card)

    def test_the_lie_is_refused_with_the_stored_and_the_recomputed_number(self):
        liar = sc.ScoreCard(factors(10, None, None, 90, None, None), 80)
        with self.assertRaises(AppError) as caught:
            sc.check_card(self.B, liar)
        self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")
        shown = caught.exception.rendered().message
        for needle in ("최종 점수", "80", "46", "네이버 B", "다시 계산한 값"):
            self.assertIn(needle, shown)
        self.assertEqual(sc.score(self.B, liar.factors).final, 46)

    def test_the_stored_number_is_the_first_one_and_the_recomputed_number_the_second_in_the_sentence(self):
        # P2b(독립 검증 M6 ③): 두 숫자가 문장에 있기만 하면 통과해서 '저장된 값' 과 '다시 계산한 값' 자리를 바꿔도 몰랐다.
        for stored, recomputed, card in ((80, 46, sc.ScoreCard(factors(10, None, None, 90, None, None), 80)), (45, 46, sc.ScoreCard(factors(10, None, None, 90, None, None), 45)),
                                         ("없음", 60, sc.ScoreCard(factors(60, None, None, None, None, None), None))):
            with self.subTest(stored=stored, recomputed=recomputed):
                with self.assertRaises(AppError) as caught:
                    sc.check_card(self.B, card)
                shown = caught.exception.rendered().message
                self.assertIn(f"저장된 값 {stored} 이(가)", shown)
                self.assertIn(f"다시 계산한 값 {recomputed} 과", shown)
                self.assertLess(shown.index("저장된 값"), shown.index("다시 계산한 값"))

    def test_one_point_off_in_either_direction_is_refused_and_the_exact_value_is_accepted(self):
        for final in (45, 47):
            with self.subTest(final=final):
                with self.assertRaises(AppError):
                    sc.check_card(self.B, sc.ScoreCard(factors(10, None, None, 90, None, None), final))
        exact = sc.ScoreCard(factors(10, None, None, 90, None, None), 46)
        self.assertIs(sc.check_card(self.B, exact), exact)

    def test_a_final_score_that_the_weights_cannot_produce_is_refused(self):
        zero_weight = dataclasses.replace(self.B, weights={**self.B.weights, "channel_fit": 25, "timing": 0, "evidence": 10 + 20, "monetization": 20})
        card = sc.ScoreCard(factors(None, None, None, 90, None, None), 90)             # 평가한 항목(시기)의 가중치가 0 이라 다시 계산하면 '점수 없음'
        self.assertIsNone(sc.score(zero_weight, card.factors).final)
        with self.assertRaises(AppError):
            sc.check_card(zero_weight, card)

    def test_a_missing_final_with_evaluated_factors_is_refused_and_no_score_at_all_is_fine(self):
        with self.assertRaises(AppError):
            sc.check_card(self.B, sc.ScoreCard(factors(60, None, None, None, None, None), None))
        empty = sc.ScoreCard()
        self.assertIs(sc.check_card(self.B, empty), empty)

    def test_the_same_card_is_judged_with_the_weights_of_the_channel_it_is_given(self):
        card = sc.score(self.B, factors(90, None, None, 10, None, None)).card
        sc.check_card(self.B, card)
        with self.assertRaises(AppError):
            sc.check_card(ts.PROFILES["naver_a"], card)

    def test_wrong_kinds_of_input_are_programming_errors(self):
        card = sc.ScoreCard()
        for args in ((None, card), (self.B, None), ({"key": "naver_b"}, card), (self.B, {"final": 1}), (self.B, factors(1, None, None, None, None, None))):
            with self.subTest(args=repr(args)[:30]):
                with self.assertRaises(TypeError):
                    sc.check_card(*args)

    def test_it_does_not_change_the_card_and_gives_the_same_answer_every_time(self):
        card = sc.score(self.B, factors(70, 70, None, 70, None, None)).card
        again = dataclasses.replace(card)
        self.assertEqual((sc.check_card(self.B, card), sc.check_card(self.B, card)), (again, again))


class TimingTest(unittest.TestCase):
    def test_the_state_names(self):
        self.assertEqual(sc.CALENDAR_STATES, ("due", "out_of_range", "unknown"))
        self.assertEqual(sc.TREND_STATUSES, ("rising", "flat", "falling", "insufficient"))
        self.assertEqual(sc.DATA_STATUSES, ("sufficient", "partial", "insufficient", "unavailable"))
        self.assertEqual(sc.DETERMINATE_TRENDS, ("rising", "flat", "falling"))
        self.assertEqual(dict(sc.TREND_STATUS_KO), {"rising": "상승", "flat": "보통", "falling": "하락", "insufficient": "데이터 부족"})

    def test_every_cell_of_the_table_with_a_known_trend(self):
        for (calendar, trend), expected in TREND_CELLS.items():
            with self.subTest(calendar=calendar, trend=trend):
                result = sc.timing_score(calendar, trend)
                self.assertEqual(result.score, expected)
                self.assertEqual((result.data_status, result.trend_used), ("sufficient", True))
        self.assertEqual({key: value for key, value in sc.TIMING_WITH_TREND.items()}, TREND_CELLS)

    def test_without_a_usable_trend_the_calendar_alone_decides(self):
        self.assertEqual(dict(sc.TIMING_CALENDAR_ONLY), CALENDAR_ONLY)
        for calendar, expected in CALENDAR_ONLY.items():
            with self.subTest(calendar=calendar, reason="insufficient"):
                result = sc.timing_score(calendar, "insufficient")
                self.assertEqual((result.score, result.data_status, result.trend_used, result.realtime), (expected, "insufficient", False, False))
            with self.subTest(calendar=calendar, reason="outage"):
                result = sc.timing_score(calendar, "insufficient", outage=True)
                self.assertEqual((result.score, result.data_status, result.trend_used, result.realtime), (expected, "unavailable", False, False))

    def test_a_due_topic_without_trend_data_gets_a_middle_score_that_is_not_zero(self):
        result = sc.timing_score("due", "insufficient")
        self.assertEqual((result.score, result.data_status), (60, "insufficient"))
        self.assertTrue(0 < result.score < sc.timing_score("due", "rising").score)

    def test_an_outage_ignores_even_a_known_trend_status(self):
        for trend in ("rising", "flat", "falling"):
            with self.subTest(trend=trend):
                result = sc.timing_score("due", trend, outage=True)
                self.assertEqual((result.score, result.data_status, result.trend_used), (60, "unavailable", False))

    def test_nothing_known_at_all_is_not_evaluable_instead_of_zero(self):
        for outage, status in ((False, "insufficient"), (True, "unavailable")):
            with self.subTest(outage=outage):
                result = sc.timing_score("unknown", "insufficient", outage=outage)
                self.assertEqual((result.score, result.data_status), (None, status))

    def test_a_topic_out_of_the_calendar_whose_interest_is_rising_is_marked_realtime(self):
        self.assertTrue(sc.timing_score("out_of_range", "rising").realtime)
        for calendar, trend in itertools.product(sc.CALENDAR_STATES, sc.TREND_STATUSES):
            if (calendar, trend) != ("out_of_range", "rising"):
                with self.subTest(calendar=calendar, trend=trend):
                    self.assertFalse(sc.timing_score(calendar, trend).realtime)

    def test_realtime_needs_the_trend_to_be_used(self):
        self.assertFalse(sc.timing_score("out_of_range", "rising", outage=True).realtime)
        self.assertFalse(sc.timing_score("out_of_range", "rising", trend_use="none").realtime)

    def test_a_channel_that_does_not_use_the_trend_never_looks_at_it(self):
        for calendar in sc.CALENDAR_STATES:
            results = {sc.timing_score(calendar, trend, trend_use="none") for trend in sc.TREND_STATUSES}
            results |= {sc.timing_score(calendar, trend, trend_use="none", outage=True) for trend in sc.TREND_STATUSES}
            with self.subTest(calendar=calendar):
                self.assertEqual(len(results), 1, "관심도 상태가 무엇이든 결과가 같다")
                result = results.pop()
                self.assertEqual((result.score, result.trend_used, result.realtime), (CALENDAR_ONLY[calendar], False, False))
                self.assertEqual(result.data_status, "insufficient" if calendar == "unknown" else "sufficient")

    def test_the_three_uses_that_read_the_trend_score_the_same(self):
        for calendar, trend in itertools.product(sc.CALENDAR_STATES, sc.TREND_STATUSES):
            for outage in (False, True):
                with self.subTest(calendar=calendar, trend=trend, outage=outage):
                    results = {sc.timing_score(calendar, trend, trend_use=use, outage=outage) for use in ("primary", "supporting", "reference")}
                    self.assertEqual(len(results), 1)

    def test_a_better_trend_never_scores_lower_inside_one_calendar_state(self):
        for calendar in sc.CALENDAR_STATES:
            scores = [sc.timing_score(calendar, trend).score for trend in ("rising", "flat", "falling")]
            with self.subTest(calendar=calendar):
                self.assertTrue(scores[0] >= scores[1] >= scores[2])

    def test_no_data_sits_between_a_flat_and_a_falling_trend_when_the_calendar_is_known(self):
        for calendar in ("due", "out_of_range"):
            with self.subTest(calendar=calendar):
                self.assertTrue(sc.timing_score(calendar, "falling").score <= sc.timing_score(calendar, "insufficient").score <= sc.timing_score(calendar, "flat").score)

    def test_no_cell_of_the_table_is_zero_so_unknown_never_means_zero(self):
        self.assertTrue(all(value > 0 for value in sc.TIMING_WITH_TREND.values()))
        self.assertTrue(all(value is None or value > 0 for value in sc.TIMING_CALENDAR_ONLY.values()))

    def test_every_score_is_a_valid_factor_value(self):
        for calendar, trend, use, outage in itertools.product(sc.CALENDAR_STATES, sc.TREND_STATUSES, ch.TREND_USES, (False, True)):
            with self.subTest(calendar=calendar, trend=trend, use=use, outage=outage):
                sc.Factors(timing=sc.timing_score(calendar, trend, trend_use=use, outage=outage).score)

    def test_a_timing_score_feeds_the_score_like_any_other_factor(self):
        profile = ts.PROFILES["naver_b"]
        due_rising = sc.timing_score("due", "rising").score
        values = (80, 80, 80, due_rising, 80, 80)
        self.assertEqual(sc.score(profile, factors(*values)).final, reference_final(profile, values))
        unknown = sc.timing_score("unknown", "insufficient").score
        self.assertEqual(sc.score(profile, sc.Factors(channel_fit=80, timing=unknown)).final, 80)

    def test_unknown_inputs_are_refused(self):
        for call in (lambda: sc.timing_score("soon", "rising"), lambda: sc.timing_score("due", "unavailable"), lambda: sc.timing_score("due", "up"), lambda: sc.timing_score(None, "rising"),
                     lambda: sc.timing_score("due", "rising", trend_use="x"), lambda: sc.timing_score("due", "rising", outage=1), lambda: sc.timing_score("due", "rising", outage=None),
                     lambda: sc.timing_score("due", "rising", trend_use="none", outage="no"), lambda: sc.timing_score("due", "bad", trend_use="none")):
            with self.assertRaises(ValueError):
                call()

    def test_the_table_cannot_be_changed(self):
        with self.assertRaises(TypeError):
            sc.TIMING_WITH_TREND[("due", "rising")] = 1
        with self.assertRaises(TypeError):
            sc.TIMING_CALENDAR_ONLY["due"] = 1


if __name__ == "__main__":
    unittest.main()
