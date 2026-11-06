"""계절 후보의 시기 점수 — 관심도(Trend)가 없을 때의 **최소 순서**(발행 기간 ≥ 준비 중 > 시즌 밖)와 '관심도 데이터 부족' 표시(P3b-1 fix1-G, 운영자 2026-11-06 지시 3 + 같은 날 22시대 개정, 결정 D-122).

운영자 결정: 관심도 값이 없을 때 준비 중이 발행 기간보다 높은 순서는 알려진 한계로 받지 않고 고친다. 승인된 점수표(`TIMING_*`·가중치·구간 값)는 **그대로** 두고 **계산 지점에서만** 보정한다 —
관심도가 없는(`Timing.trend_used` 가 거짓인) 계절 씨앗 경로 후보에서 발행 기간 점수가 준비 중 점수보다 낮으면 **최종 점수를 덮어쓰지 않고** 발행 기간의 시기 항목 값을 `max(표의 값, 같은 후보의 준비 중 점수)` 로 올려
최종 점수가 준비 중 점수와 같아지게 하고, 후보의 선정 이유에 '관심도 데이터 부족으로 최소 순서 보정' 을 적는다. 시즌 밖이 준비 중 이상이면(극단) 시즌 밖의 시기 항목 값을 낮춰 준비 중보다 낮게 한다.
보정이 필요 없는 후보와 관심도가 있을 때·계절 일정이 없는 씨앗(옛 규칙)·계절이 아닌 후보는 한 글자도 안 바뀐다.
이 시험이 하는 일: 1) 승인 점수표·달력 상태 옮김이 그대로임을 못박는다 2) 보정 규칙(`generate.minimum_order`)을 순수 함수로 — 반올림·구간 경계·상한 100·점수 묶음 일관성·표 전체 격자 3) 생성 결과가 모든 후보에서 발행 ≥ 준비 > 시즌 밖이고
보정이 필요한 후보에만 사유 줄이 붙는지 4) 관심도가 없으면 캘린더 점수를 유지하고 '데이터 부족' 을 표시하는지(점수는 캘린더만으로, 상태 insufficient, 사유 한 줄, 자세히 보기·`--json`).
입력은 모두 시험용으로 지어낸 **예시** 씨앗이다(실제 제안 파일의 계절 씨앗 × 네이버 A·B 도 같은 규칙으로 도구가 확인했다 — 그 파일은 저장소에 두지 않는다).
"""
import dataclasses
import json
import math
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402
from test_service_topics import World, put  # noqa: E402

from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import notice, schedule, score, seeds  # noqa: E402

PROFILES = ts.PROFILES
DAYS = {"publishing": "2026-11-10", "preparing": "2026-10-25", "off_season": "2026-08-10"}                # 예시 씨앗(아래)의 세 상태에 드는 날
SHORTAGE = "관심도 데이터가 부족해 시기는 캘린더만으로 봤습니다"
OUTAGE = "관심도를 조회할 수 없어 시기는 캘린더만으로 봤습니다"
FIX = "관심도 데이터 부족으로 최소 순서 보정"
DUE_VALUE, OFF_VALUE = 60, 20                                                                    # 승인 점수표의 캘린더만 값(독립 기준 — 코드의 표를 불러다 쓰지 않는다)
FACTOR_NAMES = ("channel_fit", "feasibility", "differentiation", "timing", "evidence", "monetization")


def season_seed(scope="common", **changes):
    values = dict(seed_id="ex-season-1", keyword="예시 계절 정리", seed_type="seasonal", scope=scope, target_type="life_habit", prepare_from="10-20", publish_from="11-01", publish_until="11-30",
                  peak_period=("11-15", "11-20"), recurrence="yearly", major="생활", minor="정리")
    values.update(changes)
    return ts.example_seed(**values)


def made(code, state, pool=None, **options):
    pool = [season_seed(scope=code)] if pool is None else pool
    return gn.generate(PROFILES[code], pool, (), (), DAYS[state], target=200, **options).candidates


def exact_final(profile, values):
    """독립 계산 — 여섯 항목(이름 → 점수 또는 None)의 가중 평균을 분수로 계산해 0.5 를 올려 정수로(코드의 `round_half_up` 을 쓰지 않는다)."""
    present = {name: value for name, value in values.items() if value is not None}
    total = sum(profile.weights[name] for name in present)
    if not total:
        return None
    return math.floor(sum(Fraction(value * profile.weights[name]) for name, value in present.items()) / total + Fraction(1, 2))


def season_line(item):
    return [text for text in item.selection_reasons if text.startswith("계절 일정:")][0]


class ApprovedTablesUnchangedTest(unittest.TestCase):
    def test_the_approved_calendar_only_table_and_bands_are_what_they_were(self):
        self.assertEqual(dict(score.TIMING_CALENDAR_ONLY), {"due": 60, "out_of_range": 20, "unknown": None}, "승인된 점수표 — 값은 한 글자도 안 바뀌었다(순서 보정은 계산 지점에서만 한다)")
        self.assertEqual(ch.GRADE_CUTOFFS, (80, 65, 50))
        self.assertEqual(dict(score.TIMING_WITH_TREND), {("due", "rising"): 90, ("due", "flat"): 70, ("due", "falling"): 40, ("out_of_range", "rising"): 70, ("out_of_range", "flat"): 20,
                                                          ("out_of_range", "falling"): 10, ("unknown", "rising"): 70, ("unknown", "flat"): 50, ("unknown", "falling"): 30})
        self.assertEqual(score.CALENDAR_STATES, ("due", "out_of_range", "unknown"), "달력 상태는 셋뿐이다(준비 중·피크를 따로 두지 않았다)")

    def test_the_season_to_calendar_mapping_is_what_it_was(self):
        self.assertEqual(dict(gn.SEASON_CALENDAR), {schedule.SEASON_PUBLISHING: "due", schedule.SEASON_PREPARING: "unknown", schedule.SEASON_OFF: "out_of_range"},
                         "발행 기간 → due(60)·준비 중 → unknown(시기 항목을 빼고 나머지로 다시 나눔)·시즌 밖 → out_of_range(20)")

    def test_the_channel_weights_of_the_timing_item_are_what_they_were(self):
        self.assertEqual({code: PROFILES[code].weights["timing"] for code in ("naver_a", "naver_b")}, {"naver_a": 15, "naver_b": 20})

    def test_the_timing_function_itself_is_unchanged_it_still_gives_the_table_value(self):
        for calendar, points in (("due", 60), ("out_of_range", 20), ("unknown", None)):
            self.assertEqual(score.timing_score(calendar, "insufficient", trend_use=ch.USE_PRIMARY).score, points)


class MinimumOrderRuleTest(unittest.TestCase):
    """`generate.minimum_order` — 순수 함수(시계·난수·파일 없음). 보정은 발행 기간(`due`)의 시기 항목 값을 올려 최종 점수가 준비 중 점수와 정확히 같아지게 하는 것이다."""

    def factors(self, timing, **values):
        base = dict(channel_fit=80, feasibility=80, differentiation=80, evidence=80, monetization=80)
        base.update(values)
        return score.Factors(timing=timing, **base)

    def test_a_due_candidate_below_its_preparation_score_is_raised_to_exactly_that_score(self):
        for code, before in (("naver_a", 77), ("naver_b", 76)):
            profile = PROFILES[code]
            factors = self.factors(60)
            self.assertEqual(score.score(profile, factors).final, before, "보정 전: 시기 60 이 다른 항목 평균(80)보다 낮아 끌어내린다")
            fix = gn.minimum_order(profile, factors, "due", False)
            self.assertEqual(fix.factors.timing, 80, "시기 항목 값을 준비 중 점수(다른 항목의 평균 80)로 올린다")
            self.assertEqual({name: getattr(fix.factors, name) for name in FACTOR_NAMES if name != "timing"}, {name: getattr(factors, name) for name in FACTOR_NAMES if name != "timing"}, "다른 항목은 그대로")
            self.assertEqual(score.score(profile, fix.factors).final, 80, "최종 점수가 준비 중 점수와 정확히 같다")
            self.assertEqual(score.score(profile, dataclasses.replace(factors, timing=None)).final, 80)
            self.assertIn(FIX, fix.note)
            self.assertIn("60점에서 80점으로", fix.note)
            self.assertIn("(80점)", fix.note)
            self.assertTrue(notice.is_clean(fix.note))
            self.assertEqual(score.check_card(profile, score.score(profile, fix.factors).card).final, 80, "점수 묶음 일관성(`check_card`)을 통과한다")

    def test_the_correction_can_cross_a_band_boundary_and_the_band_follows_the_final_score(self):
        profile = PROFILES["naver_a"]
        factors = self.factors(60)
        before = score.score(profile, factors)
        after = score.score(profile, gn.minimum_order(profile, factors, "due", False).factors)
        self.assertEqual((before.final, before.band), (77, score.BAND_GENERAL))
        self.assertEqual((after.final, after.band), (80, score.BAND_RECOMMENDED), "구간 경계(80)를 넘어 우선 추천이 된다 — 구간은 보정한 최종 점수에서 계산한다")

    def test_nothing_changes_when_the_order_already_holds_or_the_rule_does_not_apply(self):
        profile = PROFILES["naver_b"]
        low = self.factors(60, channel_fit=50, feasibility=50, differentiation=50, evidence=50, monetization=50)
        equal = self.factors(60, channel_fit=60, feasibility=60, differentiation=60, evidence=60, monetization=60)
        for factors, why in ((low, "다른 항목 평균이 60 보다 낮아 이미 발행 ≥ 준비"), (equal, "같으면 그대로")):
            fix = gn.minimum_order(profile, factors, "due", False)
            self.assertIs(fix.factors, factors, why)
            self.assertIsNone(fix.note)
        high = self.factors(60)
        for calendar, timing, trend_used in (("due", 60, True), ("unknown", None, False), ("unknown", None, True), ("out_of_range", 20, True)):
            fix = gn.minimum_order(profile, self.factors(timing), calendar, trend_used)
            self.assertEqual(fix.factors.timing, timing)
            self.assertIsNone(fix.note, f"{calendar} trend_used={trend_used}")
        self.assertIsNone(gn.minimum_order(profile, score.Factors(timing=60), "due", False).note, "다른 항목이 하나도 없으면 준비 중 점수가 없어 보정하지 않는다")
        self.assertIsNone(gn.minimum_order(profile, dataclasses.replace(high, timing=None), "due", False).note, "시기 항목이 없으면 보정하지 않는다")

    def test_the_upper_bound_100_holds(self):
        profile = PROFILES["naver_a"]
        top = self.factors(60, channel_fit=100, feasibility=100, differentiation=100, evidence=100, monetization=100)
        fix = gn.minimum_order(profile, top, "due", False)
        self.assertEqual(fix.factors.timing, 100)
        self.assertEqual(score.score(profile, fix.factors).final, 100)
        score.check_card(profile, score.score(profile, fix.factors).card)

    def test_every_cell_of_a_grid_keeps_the_order_and_the_score_card_consistent_for_due(self):
        values, checked, corrected = (0, 40, 60, 61, 75, 90, 100), 0, 0
        for code in ("naver_a", "naver_b"):
            profile = PROFILES[code]
            for channel_fit in values:
                for feasibility in values:
                    for evidence in values:
                        for differentiation in (None, 30, 80):
                            for monetization in (None, 20, 100):
                                factors = score.Factors(channel_fit=channel_fit, feasibility=feasibility, differentiation=differentiation, timing=60, evidence=evidence, monetization=monetization)
                                others = {name: getattr(factors, name) for name in FACTOR_NAMES if name != "timing"}
                                prepared, plain = exact_final(profile, others), exact_final(profile, {**others, "timing": 60})
                                fix = gn.minimum_order(profile, factors, "due", False)
                                final = score.score(profile, fix.factors).final
                                checked += 1
                                if plain >= prepared:
                                    self.assertIs(fix.factors, factors, (code, factors))
                                    self.assertIsNone(fix.note)
                                    continue
                                corrected += 1
                                self.assertEqual((fix.factors.timing, final), (prepared, prepared), (code, factors))
                                self.assertGreater(fix.factors.timing, 60)
                                self.assertIn(FIX, fix.note)
                                score.check_card(profile, score.score(profile, fix.factors).card)
        self.assertEqual(checked, 2 * 7 ** 3 * 9)
        self.assertGreater(corrected, 1000, "격자의 상당수가 실제로 뒤집힌 칸이라 보정 경로를 충분히 지난다")

    def test_a_season_off_candidate_that_is_not_below_its_preparation_score_is_lowered_below_it(self):
        profile = PROFILES["naver_a"]
        low = score.Factors(channel_fit=5, feasibility=5, differentiation=5, timing=20, evidence=5, monetization=5)
        self.assertEqual((score.score(profile, low).final, score.score(profile, dataclasses.replace(low, timing=None)).final), (7, 5), "보정 전: 시즌 밖(7)이 준비 중(5)보다 높다")
        fix = gn.minimum_order(profile, low, "out_of_range", False)
        self.assertEqual(fix.factors.timing, 1)
        self.assertEqual(score.score(profile, fix.factors).final, 4, "준비 중 점수(5)보다 낮다")
        self.assertIn(FIX, fix.note)
        self.assertIn("20점에서 1점으로", fix.note)
        zero = score.Factors(channel_fit=0, feasibility=0, differentiation=0, timing=20, evidence=0, monetization=0)
        again = gn.minimum_order(profile, zero, "out_of_range", False)
        self.assertIs(again.factors, zero, "어떤 값으로도 준비 중보다 낮출 수 없으면(다른 항목이 모두 0) 그대로 둔다")
        self.assertIsNone(again.note)

    def test_every_cell_of_a_grid_keeps_off_season_below_preparation_when_it_can(self):
        values, checked, corrected = (0, 3, 5, 8, 12, 20, 21, 40, 90), 0, 0
        for code in ("naver_a", "naver_b"):
            profile = PROFILES[code]
            for channel_fit in values:
                for feasibility in values:
                    for evidence in values:
                        for monetization in (None, 0, 20, 100):
                            factors = score.Factors(channel_fit=channel_fit, feasibility=feasibility, differentiation=None, timing=20, evidence=evidence, monetization=monetization)
                            others = {name: getattr(factors, name) for name in FACTOR_NAMES if name != "timing"}
                            prepared, plain = exact_final(profile, others), exact_final(profile, {**others, "timing": 20})
                            fix = gn.minimum_order(profile, factors, "out_of_range", False)
                            final = score.score(profile, fix.factors).final
                            checked += 1
                            if plain < prepared:
                                self.assertIs(fix.factors, factors)
                                self.assertIsNone(fix.note)
                                continue
                            possible = [value for value in range(19, -1, -1) if exact_final(profile, {**others, "timing": value}) < prepared]
                            if not possible:
                                self.assertIs(fix.factors, factors, (code, factors))
                                continue
                            corrected += 1
                            self.assertEqual(fix.factors.timing, possible[0], "가장 큰 값으로만 낮춘다")
                            self.assertLess(final, prepared)
                            self.assertIn(FIX, fix.note)
                            score.check_card(profile, score.score(profile, fix.factors).card)
        self.assertEqual(checked, 2 * 9 ** 3 * 4)
        self.assertGreater(corrected, 50)

    def test_the_rule_is_deterministic(self):
        profile = PROFILES["naver_b"]
        factors = self.factors(60)
        self.assertEqual(gn.minimum_order(profile, factors, "due", False), gn.minimum_order(profile, factors, "due", False))


class GenerationOrderTest(unittest.TestCase):
    """생성 결과 — 같은 후보 번호를 세 상태(발행 기간·준비 중·시즌 밖)로 만들어 모든 후보에서 발행 ≥ 준비 > 시즌 밖이다. 보정이 필요한 후보에만 사유 줄이 붙고 나머지는 그대로다."""

    def pool(self, code):
        return [season_seed(scope=code), season_seed(seed_id="ex-season-2", keyword="예시 계절 점검", scope="common", target_type="product", major="가전", minor="소형가전"),
                season_seed(seed_id="ex-season-3", keyword="예시 계절 여행", scope=code, target_type="place", major="숙박", minor="여행", priority=True),
                season_seed(seed_id="ex-season-4", keyword="예시 계절 장비", scope="common", target_type="pc_part", major="PC 부품", minor="부품"),
                season_seed(seed_id="ex-season-5", keyword="예시 계절 메모", scope=code, target_type=None, major="생활", minor="정리", excluded_keywords=("비교",))]

    def by_state(self, code):
        return {state: {item.candidate_id: item for item in made(code, state, self.pool(code))} for state in DAYS}

    def test_every_candidate_keeps_publishing_at_least_preparing_and_preparing_above_off_season(self):
        total = 0
        for code in ("naver_a", "naver_b"):
            states = self.by_state(code)
            self.assertEqual(set(states["publishing"]), set(states["preparing"]))
            self.assertEqual(set(states["publishing"]), set(states["off_season"]))
            self.assertGreater(len(states["publishing"]), 5)
            for cid, item in states["publishing"].items():
                total += 1
                prepared, off = states["preparing"][cid].scores.final, states["off_season"][cid].scores.final
                with self.subTest(channel=code, candidate=cid[-6:]):
                    self.assertGreaterEqual(item.scores.final, prepared, "발행 기간 ≥ 준비 중")
                    self.assertGreater(prepared, off, "준비 중 > 시즌 밖")
        self.assertGreater(total, 12)

    def test_only_the_candidates_that_needed_it_are_corrected_and_the_rest_are_untouched(self):
        raised = untouched = 0
        for code in ("naver_a", "naver_b"):
            profile = PROFILES[code]
            states = self.by_state(code)
            for cid, item in states["publishing"].items():
                factors = item.scores.factors
                others = {name: getattr(factors, name) for name in FACTOR_NAMES if name != "timing"}
                prepared, plain = exact_final(profile, others), exact_final(profile, {**others, "timing": DUE_VALUE})
                notes = [text for text in item.selection_reasons if FIX in text]
                with self.subTest(channel=code, candidate=cid[-6:]):
                    self.assertEqual(states["preparing"][cid].scores.final, prepared, "다른 항목은 상태와 상관없어 준비 중 점수는 나머지 항목의 평균이다")
                    if plain < prepared:
                        raised += 1
                        self.assertEqual((factors.timing, item.scores.final), (prepared, prepared), "시기 항목 값을 올려 준비 중 점수와 정확히 같다")
                        self.assertEqual(len(notes), 1, "보정한 후보에는 사유 줄이 하나 붙는다")
                        self.assertIn(f"{DUE_VALUE}점에서 {prepared}점으로", notes[0])
                        self.assertTrue(notice.is_clean(notes[0]))
                    else:
                        untouched += 1
                        self.assertEqual((factors.timing, item.scores.final), (DUE_VALUE, plain), "보정이 필요 없으면 한 글자도 안 바뀐다")
                        self.assertEqual(notes, [])
                    self.assertEqual(item.scores, score.score(profile, factors).card, "점수 묶음은 여섯 항목의 가중 평균 그대로")
                    self.assertEqual(item.recommendation_band, score.band_of(item.scores.final), "구간은 보정한 최종 점수에서 계산한다")
            for state in ("preparing", "off_season"):
                for item in states[state].values():
                    self.assertFalse([text for text in item.selection_reasons if FIX in text], "준비 중·시즌 밖은 보정하지 않는다(극단이 아니면)")
        self.assertGreater(raised, 5)

    def test_a_trend_reading_a_non_seasonal_seed_and_a_legacy_seasonal_seed_are_never_corrected(self):
        code, profile = "naver_b", PROFILES["naver_b"]
        key = gn.keyword_key("예시 계절 정리")
        for status, points in (("rising", 90), ("flat", 70), ("falling", 40)):
            reading = {key: gn.InterestReading(status, 60, "최근 12개월", ("예시 계절 정리",), "2026-11-10")}
            found = made(code, "publishing", interest=reading)
            self.assertTrue(found)
            for item in found:
                with self.subTest(status=status):
                    self.assertEqual((item.scores.factors.timing, item.trend_status, item.data_status), (points, status, "sufficient"), "관심도가 있으면 승인된 표의 값 그대로")
                    self.assertFalse([text for text in item.selection_reasons if FIX in text])
        plain = ts.example_seed(seed_id="ex-plain", keyword="예시 물건", seed_type="general", scope="naver_b", target_type="product")
        legacy = ts.example_seed(seed_id="ex-legacy", keyword="예시 난방", seed_type="seasonal", scope="naver_b", major="가전", minor="소형가전")
        entry = ts.example_entry(keywords=("예시 난방",), name="예시 난방 시기")
        found = gn.generate(profile, [plain, legacy], [entry], (), "2026-11-10", target=200).candidates
        self.assertTrue([item for item in found if item.seed_id == "ex-legacy"] and [item for item in found if item.seed_id == "ex-plain"])
        for item in found:
            self.assertFalse([text for text in item.selection_reasons if FIX in text], "계절 일정이 없는 씨앗(옛 규칙)과 계절이 아닌 씨앗은 보정하지 않는다")
        for item in (item for item in found if item.seed_id == "ex-legacy"):
            self.assertEqual(item.scores.factors.timing, 60, "옛 규칙의 캘린더 항목이 발행 기간 안이면 표의 값 60 그대로")

    def test_the_same_input_gives_the_same_candidates(self):
        first = made("naver_a", "publishing", self.pool("naver_a"))
        self.assertEqual(made("naver_a", "publishing", self.pool("naver_a")), first)
        self.assertEqual(made("naver_a", "publishing", list(reversed(self.pool("naver_a")))), first, "씨앗 순서와 상관없이 같은 후보")


class TrendShortageDisplayTest(unittest.TestCase):
    """관심도 값이 없으면 시기 점수는 캘린더만으로 정해지고(60·모름·20 — 순서 보정이 필요하면 그 값만 올라간다), 후보에는 '데이터 부족' 이 남고, 계절 후보의 선정 이유에 한 줄로 보인다."""

    def test_the_timing_function_keeps_the_calendar_score_and_reports_insufficient_data(self):
        for calendar, points in (("due", 60), ("out_of_range", 20), ("unknown", None)):
            for use in (ch.USE_PRIMARY, ch.USE_SUPPORTING, ch.USE_REFERENCE):
                with self.subTest(calendar=calendar, use=use):
                    timing = score.timing_score(calendar, "insufficient", trend_use=use)
                    self.assertEqual((timing.score, timing.data_status, timing.trend_used), (points, "insufficient", False))
                    outage = score.timing_score(calendar, "insufficient", trend_use=use, outage=True)
                    self.assertEqual((outage.score, outage.data_status, outage.trend_used), (points, "unavailable", False), "조회 불가는 '데이터 부족' 과 다른 상태로 구분한다")
        quiet = score.timing_score("due", "insufficient", trend_use=ch.USE_NONE)
        self.assertEqual((quiet.score, quiet.data_status), (60, "sufficient"), "관심도를 쓰지 않는 채널은 부족한 것이 아니다")

    def test_every_season_candidate_without_a_trend_shows_the_shortage_and_keeps_the_calendar_score_unless_the_order_needs_it(self):
        for code in ("naver_a", "naver_b"):
            profile = PROFILES[code]
            for state, table in (("publishing", 60), ("preparing", None), ("off_season", 20)):
                found = made(code, state)
                self.assertTrue(found)
                for item in found:
                    with self.subTest(channel=code, state=state, candidate=item.candidate_id[-6:]):
                        factors = item.scores.factors
                        others = {name: getattr(factors, name) for name in FACTOR_NAMES if name != "timing"}
                        if state == "publishing":
                            self.assertEqual(factors.timing, max(table, exact_final(profile, others)), "예시 씨앗은 보정이 필요한 쪽이라 시기 항목 값이 준비 중 점수까지 올랐다")
                        else:
                            self.assertEqual(factors.timing, table, "준비 중·시즌 밖은 캘린더 점수 그대로(모름·20)")
                        self.assertEqual((item.trend_status, item.data_status), ("insufficient", "insufficient"), "관심도·자료 상태가 데이터 부족")
                        self.assertIsNone(item.trend_ratio)
                        lines = [text for text in item.selection_reasons if text.startswith("계절 일정:")]
                        self.assertEqual(len(lines), 1)
                        self.assertTrue(lines[0].endswith(SHORTAGE), lines[0])
                        self.assertEqual(item.scores, score.score(profile, factors).card, "점수는 여섯 항목의 가중 평균 그대로")
                        self.assertTrue(notice.is_clean(lines[0]))

    def test_an_outage_says_it_could_not_be_read_and_a_real_reading_says_nothing_about_shortage(self):
        outage = made("naver_b", "publishing", interest_outage=True)
        self.assertTrue(outage)
        for item in outage:
            self.assertEqual(item.data_status, "unavailable")
            self.assertTrue(season_line(item).endswith(OUTAGE))
            self.assertTrue([text for text in item.selection_reasons if FIX in text], "조회 불가도 관심도 값이 없는 경우라 같은 최소 순서 보정을 한다")
        keyword_key = gn.keyword_key("예시 계절 정리")
        reading = {keyword_key: gn.InterestReading("rising", 80, "최근 12개월", ("예시 계절 정리",), "2026-11-10")}
        read = made("naver_b", "publishing", interest=reading)
        self.assertTrue(read)
        for item in read:
            self.assertEqual((item.trend_status, item.data_status), ("rising", "sufficient"))
            line = season_line(item)
            self.assertNotIn("관심도 데이터가", line)
            self.assertNotIn("조회할 수 없어", line)

    def test_a_channel_that_never_uses_the_trend_gets_no_shortage_note(self):
        quiet = dataclasses.replace(PROFILES["naver_b"], trend_use=ch.USE_NONE)
        for state in DAYS:
            found = gn.generate(quiet, [season_seed(scope="naver_b")], (), (), DAYS[state], target=20).candidates
            self.assertTrue(found)
            for item in found:
                with self.subTest(state=state):
                    self.assertNotIn("시기는 캘린더만으로 봤습니다", season_line(item), "관심도를 쓰지 않는 채널은 부족한 것이 아니다(준비 중은 달력 상태가 모름이라 자료 상태가 insufficient 여도 말하지 않는다)")
        again = made("naver_b", "preparing")
        self.assertTrue(again)
        for item in again:
            self.assertTrue(any("시기는 캘린더만으로 봤습니다" in text for text in item.selection_reasons), "관심도를 쓰는 채널은 준비 중에도 말한다")

    def test_seeds_without_their_own_schedule_have_no_season_line_so_nothing_changed_for_them(self):
        plain = ts.example_seed(seed_id="ex-plain", keyword="예시 물건", seed_type="general", scope="naver_b", target_type="product")
        found = gn.generate(PROFILES["naver_b"], [plain], (), (), DAYS["publishing"], target=20).candidates
        self.assertTrue(found)
        for item in found:
            self.assertFalse([line for line in item.selection_reasons if line.startswith("계절 일정:")])
            self.assertFalse([line for line in item.selection_reasons if "시기는 캘린더만으로 봤습니다" in line])

    def test_the_command_line_shows_the_shortage_and_the_correction_in_the_detail_view_and_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            put(world.paths.seeds, seeds.seeds_to_dict([season_seed(scope="naver_b")]))
            code, out, _err = ss.run_cli(world.ctx, "topics", "generate", "--today", DAYS["publishing"], "--yes")
            self.assertEqual(code, 0)
            code, out, _err = ss.run_cli(world.ctx, "topics", "show", "1")
            self.assertEqual(code, 0)
            self.assertIn("관심도: 데이터 부족 · 자료 상태: 모자람", out, "후보 자세히 보기에 관심도 데이터 부족이 보인다")
            self.assertIn(SHORTAGE, out, "선정 이유에도 한 줄로 보인다")
            self.assertIn(FIX, out, "순서 보정을 한 후보에는 그 사유 줄이 보인다")
            self.assertIn("시기 71", out, "시기 항목 값이 준비 중 점수(71)까지 올랐다")
            self.assertEqual(notice.leaks("\n".join(line for line in out.splitlines() if str(tmp) not in line)), ())
            code, out, _err = ss.run_cli(world.ctx, "topics", "show", "1", "--json")
            candidate = json.loads(out)["data"]["candidate"]
            self.assertEqual((candidate["trend_status"], candidate["data_status"]), ("insufficient", "insufficient"))
            self.assertEqual((candidate["scores"]["timing"], candidate["scores"]["final"]), (71, 71))
            self.assertTrue([line for line in candidate["selection_reasons"] if line.endswith(SHORTAGE)])
            self.assertTrue([line for line in candidate["selection_reasons"] if FIX in line])


if __name__ == "__main__":
    unittest.main()
