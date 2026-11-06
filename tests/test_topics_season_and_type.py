"""계절·월별 씨앗의 동작과 후보 종류 기록(P3b-1 S3) 시험.

① 그날의 계절 상태 계산(`schedule.season_state`·`seasonal_state` — 순수: 해를 넘기는 기간·2월 29일 없음·윤년·매년(`yearly`)과 매월(`monthly`)·경계 날짜)
② 후보 조립에서의 동작: 시즌 밖이어도 씨앗을 쉬게 하거나 후보 생성에서 빼지 않고 우선순위(시기 점수)만 낮추며, 일정이 없는 판 1 계절 씨앗은 옛 규칙(캘린더 항목이 발행 기간 안일 때만)이다
③ 후보 종류(`candidate_type`) 값 집합·월별 반복 후보의 `monthly_recurring`·옛 JSON 에서 경로로 유도·비율에 맞추려고 후보를 늘리거나 줄이지 않음.
입력은 모두 시험용 예시이고 시계를 읽지 않는다(날짜는 인자로 준다).
"""
import calendar
import dataclasses
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402
from chanceblog_desktop.topics import schedule as sc  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.topics import wording as wd  # noqa: E402

A, B = ts.PROFILES["naver_a"], ts.PROFILES["naver_b"]
PUBLISHING, PREPARING, OFF = sc.SEASON_PUBLISHING, sc.SEASON_PREPARING, sc.SEASON_OFF
YEARLY = ("12-05", "12-20", "01-20")                  # 준비 시작·발행 시작·발행 종료 — 해를 넘기는 기간
MONTHLY = ("20", "25", "05")                          # 매월: 준비 시작 20일·발행 25일~다음 달 5일


def state(recurrence, dates, today):
    return sc.season_state(recurrence, *dates, today)


def scheduled(**changes):
    values = dict(seed_type="seasonal", scope="naver_a", keyword="예시 계절 나들이", prepare_from=YEARLY[0], publish_from=YEARLY[1], publish_until=YEARLY[2], recurrence="yearly")
    values.update(changes)
    return ts.example_seed(**values)


class YearlyStateTest(unittest.TestCase):
    def test_the_window_that_crosses_the_new_year_is_continuous(self):
        expected = {"2026-12-04": OFF, "2026-12-05": PREPARING, "2026-12-19": PREPARING, "2026-12-20": PUBLISHING, "2026-12-31": PUBLISHING, "2027-01-01": PUBLISHING, "2027-01-20": PUBLISHING,
                    "2027-01-21": OFF, "2027-06-01": OFF, "2027-12-04": OFF, "2027-12-05": PREPARING}
        for day, want in expected.items():
            with self.subTest(day=day):
                self.assertEqual(state("yearly", YEARLY, day), want)

    def test_a_window_inside_one_year_and_a_preparation_that_starts_the_year_before(self):
        spring = ("02-25", "03-10", "04-30")
        self.assertEqual([state("yearly", spring, day) for day in ("2027-02-24", "2027-02-25", "2027-03-09", "2027-03-10", "2027-04-30", "2027-05-01")], [OFF, PREPARING, PREPARING, PUBLISHING, PUBLISHING, OFF])
        early = ("12-25", "01-10", "02-10")                                   # 준비 시작이 지난해 12월
        self.assertEqual([state("yearly", early, day) for day in ("2026-12-24", "2026-12-25", "2027-01-09", "2027-01-10", "2027-02-10", "2027-02-11")], [OFF, PREPARING, PREPARING, PUBLISHING, PUBLISHING, OFF])

    def test_leap_years_have_no_surprise_because_dates_are_calendar_dates_without_feb_29(self):
        window = ("02-10", "02-28", "03-05")
        self.assertEqual([state("yearly", window, day) for day in ("2028-02-27", "2028-02-28", "2028-02-29", "2028-03-01", "2028-03-05", "2028-03-06")], [PREPARING, PUBLISHING, PUBLISHING, PUBLISHING, PUBLISHING, OFF],
                         "윤년 2월 29일은 발행 기간 안이다(날짜 두 개 사이의 하루)")
        self.assertEqual([state("yearly", window, day) for day in ("2027-02-28", "2027-03-01", "2027-03-05", "2027-03-06")], [PUBLISHING, PUBLISHING, PUBLISHING, OFF])
        self.assertIsNotNone(sc.season_problem("yearly", "02-29", "03-10", "04-10"), "2월 29일은 날짜로 쓸 수 없다")
        self.assertIsNotNone(sc.season_problem("yearly", "01-10", "02-29", "04-10"))
        self.assertIsNotNone(sc.season_problem("yearly", "01-10", "03-10", "02-29"))

    def test_the_number_of_publishing_days_in_a_year_is_the_window_length(self):
        for year in (2027, 2028):
            days = [date(year, 1, 1) + timedelta(days=offset) for offset in range(366 if calendar.isleap(year) else 365)]
            counts = {name: sum(state("yearly", YEARLY, day.isoformat()) == name for day in days) for name in (PUBLISHING, PREPARING, OFF)}
            self.assertEqual(counts[PUBLISHING], 20 + 12, f"{year}: 1월 1~20일 + 12월 20~31일")
            self.assertEqual(counts[PREPARING], 15, f"{year}: 12월 5~19일 15일")
            self.assertEqual(sum(counts.values()), len(days))

    def test_the_state_does_not_read_the_clock_and_is_pure(self):
        before = (YEARLY, "yearly")
        self.assertEqual(state("yearly", YEARLY, "2026-12-25"), state("yearly", YEARLY, "2026-12-25"))
        self.assertEqual((YEARLY, "yearly"), before)
        with self.assertRaises(AppError):
            state("yearly", YEARLY, "내일")
        with self.assertRaises(AppError):
            state("yearly", YEARLY, "1999-01-01")
        with self.assertRaises(ValueError):
            sc.season_state("yearly", "13-01", "12-20", "01-20", "2026-12-25")


class MonthlyStateTest(unittest.TestCase):
    def test_the_window_that_crosses_the_month_end_repeats_every_month(self):
        expected = {"2026-11-19": OFF, "2026-11-20": PREPARING, "2026-11-24": PREPARING, "2026-11-25": PUBLISHING, "2026-11-30": PUBLISHING, "2026-12-01": PUBLISHING, "2026-12-05": PUBLISHING,
                    "2026-12-06": OFF, "2026-12-19": OFF, "2026-12-20": PREPARING, "2027-01-04": PUBLISHING, "2027-01-06": OFF}
        for day, want in expected.items():
            with self.subTest(day=day):
                self.assertEqual(state("monthly", MONTHLY, day), want)

    def test_february_and_the_leap_day_need_no_special_case(self):
        for day, want in (("2027-02-27", PUBLISHING), ("2027-02-28", PUBLISHING), ("2027-03-01", PUBLISHING), ("2027-03-05", PUBLISHING), ("2027-03-06", OFF), ("2028-02-29", PUBLISHING), ("2028-03-05", PUBLISHING)):
            with self.subTest(day=day):
                self.assertEqual(state("monthly", MONTHLY, day), want)

    def test_a_window_inside_one_month_and_a_preparation_in_the_month_before(self):
        mid = ("05", "10", "20")
        self.assertEqual([state("monthly", mid, day) for day in ("2026-11-04", "2026-11-05", "2026-11-09", "2026-11-10", "2026-11-20", "2026-11-21")], [OFF, PREPARING, PREPARING, PUBLISHING, PUBLISHING, OFF])
        early = ("25", "03", "10")                                            # 준비 시작이 앞선 달 25일
        self.assertEqual([state("monthly", early, day) for day in ("2026-10-24", "2026-10-25", "2026-11-02", "2026-11-03", "2026-11-10", "2026-11-11")], [OFF, PREPARING, PREPARING, PUBLISHING, PUBLISHING, OFF])

    def test_a_year_boundary_is_not_special_for_monthly(self):
        self.assertEqual([state("monthly", MONTHLY, day) for day in ("2026-12-31", "2027-01-01", "2027-01-05", "2027-01-06")], [PUBLISHING, PUBLISHING, PUBLISHING, OFF])

    def test_the_dates_are_two_digit_days_1_to_28_only(self):
        for bad in ("00", "29", "30", "31", "5", "100", "ab", "-1"):
            self.assertIsNone(sc.parse_day_of_month(bad), bad)
        self.assertEqual((sc.parse_day_of_month("01"), sc.parse_day_of_month("28")), (1, 28))
        self.assertIsNone(sc.season_problem("monthly", "20", "25", "05"))
        self.assertIsNotNone(sc.season_problem("monthly", "29", "25", "05"))
        self.assertIsNotNone(sc.season_problem("weekly", "20", "25", "05"))


class SeedStateTest(unittest.TestCase):
    def test_a_seed_without_its_own_schedule_has_no_state(self):
        self.assertIsNone(sc.seasonal_state(ts.example_seed(seed_type="seasonal"), "2026-11-10"), "판 1 의 계절 씨앗 — 옛 규칙")
        self.assertIsNone(sc.seasonal_state(ts.example_seed(), "2026-11-10"))

    def test_a_seed_with_a_schedule_follows_the_calendar_of_that_day(self):
        made = scheduled()
        self.assertEqual([sc.seasonal_state(made, day) for day in ("2026-11-10", "2026-12-10", "2026-12-25", "2027-02-01")], [OFF, PREPARING, PUBLISHING, OFF])
        self.assertEqual(sc.seasonal_state(scheduled(recurrence="monthly", prepare_from="20", publish_from="25", publish_until="05", peak_period=None), "2026-11-27"), PUBLISHING)

    def test_off_season_never_makes_a_seed_unusable_or_a_resting_proposal(self):
        made = dataclasses.replace(scheduled(), registered_on="2020-01-01")
        self.assertEqual(sd.usable_seeds((made,), "naver_a"), (made,), "시즌 밖이어도 사용 중 씨앗은 후보 생성에 쓸 수 있다")
        self.assertEqual(sd.idle_proposals((made,), "2026-11-10"), (), "비수기라는 이유로 쉬게 하자고 제안하지 않는다(그대로)")
        resting = sd.change_state(made, "inactive")
        self.assertEqual(sd.usable_seeds((resting,), "naver_a"), (), "사용자가 직접 쉬게 한 씨앗만 빠진다")

    def test_the_stored_state_can_hold_the_last_computed_value(self):
        made = scheduled()
        marked = dataclasses.replace(made, seasonal_priority_state=sc.seasonal_state(made, "2026-12-25"))
        self.assertEqual(marked.seasonal_priority_state, PUBLISHING)
        self.assertEqual(sd.seeds_from_dict(sd.seeds_to_dict((marked,))), (marked,))
        self.assertEqual(set(wd.SEASONAL_STATE_KO), set(sc.SEASON_STATES))


class GenerateSeasonTest(unittest.TestCase):
    ON, PREP, OFF_DAY = "2026-12-25", "2026-12-10", "2026-11-10"

    def candidates(self, today, *pool, profile=A, entries=(), target=20):
        return gn.generate(profile, pool, entries, (), today, target=target)

    def test_a_scheduled_seed_makes_candidates_even_in_the_off_season_and_with_no_calendar_entry(self):
        made = scheduled()
        counts = {day: len(self.candidates(day, made).candidates) for day in (self.ON, self.PREP, self.OFF_DAY)}
        self.assertGreater(counts[self.OFF_DAY], 0, "시즌 밖이라고 후보 생성에서 빼지 않는다")
        self.assertEqual(len(set(counts.values())), 1, f"세 날의 후보 수가 같다(우선순위만 다르다): {counts}")
        legacy = ts.example_seed(seed_type="seasonal", scope="naver_a", keyword="예시 계절 나들이")
        found = self.candidates(self.OFF_DAY, legacy)
        self.assertEqual(found.candidates, (), "일정이 없는 판 1 계절 씨앗은 옛 규칙 그대로 캘린더 항목이 없으면 후보가 없다")
        self.assertIn("not_due", [row.reason for row in found.dropped])

    def test_the_off_season_lowers_the_priority_and_the_preparation_start_restores_the_normal_one(self):
        made = scheduled()
        finals = {}
        for name, day in (("publishing", self.ON), ("preparing", self.PREP), ("off", self.OFF_DAY)):
            found = self.candidates(day, made)
            self.assertTrue(all(item.source_type == "seasonal" for item in found.candidates))
            finals[name] = {item.candidate_id: item.scores.final for item in found.candidates}
        ids = set(finals["off"])
        self.assertEqual(ids, set(finals["publishing"]), "같은 씨앗·같은 방향이면 날짜가 달라도 같은 후보 번호다")
        for candidate_id in ids:
            self.assertLess(finals["off"][candidate_id], finals["preparing"][candidate_id], "시즌 밖은 준비 중(일반 우선순위)보다 낮다")
            self.assertLess(finals["off"][candidate_id], finals["publishing"][candidate_id], "시즌 밖은 발행 기간보다 낮다")

    def test_the_candidate_explains_which_season_state_was_used(self):
        for day, word in ((self.ON, "우선 추천"), (self.PREP, "일반 우선순위"), (self.OFF_DAY, "우선순위를 낮췄")):
            with self.subTest(day=day):
                first = self.candidates(day, scheduled()).candidates[0]
                self.assertTrue(any(line.startswith("계절 일정:") and word in line for line in first.selection_reasons), first.selection_reasons)

    def test_a_calendar_entry_that_says_due_still_wins_over_an_off_season_seed(self):
        entry = ts.example_entry(keywords=("예시 계절 나들이",), prep_start="10-15", publish_from="11-01", publish_to="11-30", peak="11-20")
        with_entry = self.candidates(self.OFF_DAY, scheduled(), entries=(entry,))
        without = self.candidates(self.OFF_DAY, scheduled())
        self.assertGreater(with_entry.candidates[0].scores.final, without.candidates[0].scores.final)

    def test_only_a_user_deactivated_seed_drops_out_of_generation(self):
        resting = sd.change_state(scheduled(), "inactive")
        found = self.candidates(self.ON, resting)
        self.assertEqual(found.candidates, ())
        self.assertIn("no_seed", [row.reason for row in found.dropped])


class CandidateTypeTest(unittest.TestCase):
    TODAY = "2026-12-25"

    def test_the_value_set_matches_the_operator_list_plus_the_one_still_in_use(self):
        self.assertEqual(set(md.CANDIDATE_TYPES), {"evergreen", "realtime", "seasonal", "monthly_recurring", "follow_up", "sponsor_prep"})
        self.assertEqual(wd.CANDIDATE_TYPE_KO["monthly_recurring"], "월별 반복형")
        self.assertEqual(tuple(wd.CANDIDATE_TYPE_KO), md.CANDIDATE_TYPES)
        self.assertEqual(md.CANDIDATE_TYPE_OF_SOURCE, {"seed": "evergreen", "follow_up": "follow_up", "seasonal": "seasonal", "realtime": "realtime", "sponsor": "sponsor_prep"})

    def test_the_rule_table_per_route_is_the_same_as_the_p3_merge_point_except_the_monthly_seasonal_seed(self):
        self.assertEqual({route: gn.candidate_type_of(route) for route in gn.ROUTES}, {"seed": "evergreen", "follow_up": "follow_up", "seasonal": "seasonal", "realtime": "realtime", "sponsor": "sponsor_prep"})
        self.assertEqual(gn.candidate_type_of("seasonal", scheduled()), "seasonal")
        monthly = scheduled(recurrence="monthly", prepare_from="20", publish_from="25", publish_until="05", peak_period=None)
        self.assertEqual(gn.candidate_type_of("seasonal", monthly), "monthly_recurring")
        self.assertEqual(gn.candidate_type_of("seed", monthly), "evergreen", "계절 경로가 아니면 그대로다")
        self.assertEqual(gn.candidate_type_of("sponsor", monthly), "sponsor_prep")

    def test_candidates_carry_the_recorded_type_for_every_route(self):
        monthly = scheduled(seed_id="ex-m", keyword="예시 월말 정리", recurrence="monthly", prepare_from="20", publish_from="25", publish_until="05", peak_period=None)
        yearly = scheduled(seed_id="ex-y", keyword="예시 연말 정리")
        plain = ts.example_seed(seed_id="ex-g", keyword="예시 일반 씨앗", scope="naver_a")
        tagged = ts.example_seed(seed_id="ex-s", keyword="예시 협찬 씨앗", scope="naver_a", seed_type="sponsorable", sponsor_tag="pc_peripheral")
        found = gn.generate(A, (monthly, yearly, plain, tagged), (), (), self.TODAY, target=60)
        by_seed = {}
        for item in found.candidates:
            by_seed.setdefault((item.seed_id, item.source_type), set()).add(item.candidate_type)
        self.assertEqual(by_seed[("ex-m", "seasonal")], {"monthly_recurring"})
        self.assertEqual(by_seed[("ex-y", "seasonal")], {"seasonal"})
        self.assertEqual(by_seed[("ex-g", "seed")], {"evergreen"})
        self.assertEqual(by_seed[("ex-s", "sponsor")], {"sponsor_prep"})

    def test_the_type_is_only_recorded_and_never_changes_how_many_candidates_there_are(self):
        pool = tuple(ts.example_seed(seed_id=f"ex-{n}", keyword=f"예시 씨앗 {n}", scope="naver_a") for n in range(1, 7))
        found = gn.generate(A, pool, (), (), self.TODAY, target=20)
        self.assertEqual({item.candidate_type for item in found.candidates}, {"evergreen"})
        by_route = {row.route: row for row in found.routes}
        self.assertEqual(by_route["seed"].made, by_route["seed"].target, "씨앗 경로의 목표만큼 만들고")
        self.assertTrue(all(by_route[name].made == 0 for name in ("follow_up", "seasonal", "realtime", "sponsor")), "다른 종류를 비율에 맞추려고 억지로 채우지 않는다")
        self.assertTrue(all(by_route[name].shortage == by_route[name].target for name in ("follow_up", "seasonal", "realtime", "sponsor")))

    def test_an_old_json_without_the_type_derives_it_from_the_route(self):
        for source, expected in md.CANDIDATE_TYPE_OF_SOURCE.items():
            with self.subTest(source=source):
                data = ts.make(source_type=source, candidate_type=expected).to_dict()
                del data["candidate_type"]
                self.assertEqual(md.TopicCandidate.from_dict(data).candidate_type, expected)
        old = ts.make().to_dict()
        del old["candidate_type"]
        self.assertEqual(md.TopicCandidate.from_dict(old), ts.make(), "칸이 없는 옛 JSON 은 같은 후보로 읽힌다")
        for bad in ("manual", None, 5):
            broken = dict(old, source_type=bad)
            with self.subTest(bad=bad), self.assertRaises(AppError):
                md.TopicCandidate.from_dict(broken)

    def test_every_recorded_value_survives_a_round_trip_and_an_unknown_value_is_refused(self):
        for kind in md.CANDIDATE_TYPES:
            made = ts.make(candidate_type=kind)
            self.assertEqual(md.TopicCandidate.from_dict(made.to_dict()), made)
        with self.assertRaises(AppError):
            ts.make(candidate_type="weekly")
        data = ts.make().to_dict()
        data["candidate_type"] = "weekly"
        with self.assertRaises(AppError):
            md.TopicCandidate.from_dict(data)

    def test_the_type_is_a_field_of_the_candidate_json_not_a_new_column(self):
        self.assertIn("candidate_type", md.TopicCandidate.__dataclass_fields__)
        self.assertIn("candidate_type", ts.make().to_dict())


if __name__ == "__main__":
    unittest.main()
