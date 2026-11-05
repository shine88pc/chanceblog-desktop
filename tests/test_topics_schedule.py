"""캘린더 시험(`topics/schedule.py`) — 항목의 모양과 검증, 발행 기간의 시작·끝날 경계(포함), 해를 넘기는 기간, 매년·한 번만, 윤년, 후보의 시기 상태(due·out_of_range·unknown)와 P1 시기 점수와의 연결, 마지막 평가일, `calendar.json` 모양.

지키는 것:
  1) 발행 기간은 시작날과 끝날을 **포함**한다(하루 전·하루 뒤는 밖). 해를 넘기는 기간(12-20 → 01-10)도 같다. 준비 시작일부터 발행 시작 전날까지는 '준비 중'이다. `once` 는 자기 해의 주기만 돈다.
  2) 후보의 시기 상태는 낱말 통째 일치로 정한다 — 해당 항목의 발행 기간 안이면 due, 해당 항목은 있지만 밖이면 out_of_range, 해당 항목이 없으면 unknown(0 이 아니라 '모름'). '카드' 는 '그래픽카드'·'카드뮴' 에 걸리지 않는다.
  3) 그 상태는 P1 `score.timing_score` 의 첫 입력에 그대로 들어간다(`score.CALENDAR_STATES`).
  4) 마지막 평가일이 없으면 '모름'(None)이고 재평가가 필요한 것으로 본다. 모양은 엄격하다(schema 1·정확한 칸·모르는 칸·같은 번호·어느 번째 항목인지 안내).
  5) 실제 캘린더는 이 저장소에 없다 — 시험 자료는 모두 '예시' 로 시작하는 지어낸 낱말이다. 날짜는 늘 인자이고 시계를 읽지 않는다.
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import copy
import dataclasses
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import schedule as sc  # noqa: E402
from chanceblog_desktop.topics import score  # noqa: E402


def entry(**changes):
    return ts.example_entry(**changes)


def rejected(test, **changes):
    with test.assertRaises(AppError) as caught:
        entry(**changes)
    test.assertEqual(caught.exception.code, "CONTENT_INVALID")
    test.assertTrue(caught.exception.rendered().message)
    return caught.exception


class ConstantsTest(unittest.TestCase):
    def test_the_rules_the_calendar_documents(self):
        self.assertEqual((sc.MAX_LEAD_DAYS, sc.MAX_WINDOW_DAYS, sc.EVALUATION_DAYS, sc.MAX_ENTRIES), (180, 183, 30, 500))
        self.assertEqual(sc.REPEATS, ("yearly", "once"))
        self.assertEqual(sc.PHASES, ("preparing", "publishing", "outside"))
        self.assertEqual(set(sc.REPEAT_KO), set(sc.REPEATS))

    def test_the_three_calendar_states_are_the_ones_the_timing_score_reads(self):
        self.assertEqual(score.CALENDAR_STATES, ("due", "out_of_range", "unknown"))
        found = {sc.calendar_state([entry()], ["예시시기 글"], "2026-11-10").state, sc.calendar_state([entry()], ["예시시기 글"], "2026-12-10").state, sc.calendar_state([], ["글"], "2026-11-10").state}
        self.assertEqual(found, set(score.CALENDAR_STATES))


class MonthDayTest(unittest.TestCase):
    def test_valid_month_days_are_read_and_the_leap_day_is_not_allowed(self):
        self.assertEqual(sc.parse_month_day("01-01"), (1, 1))
        self.assertEqual(sc.parse_month_day("12-31"), (12, 31))
        self.assertEqual(sc.parse_month_day("02-28"), (2, 28))
        self.assertEqual(sc.parse_month_day("11-15"), sc.MonthDay(11, 15))
        self.assertIsNone(sc.parse_month_day("02-29"))

    def test_anything_else_is_none(self):
        for bad in ("13-01", "00-10", "01-00", "04-31", "1-1", "11/15", "11-5", "ab-cd", "11-155", "", None, 1115, "２-１", "１１-１５", "11 15", " 11-15"):
            with self.subTest(text=bad):
                self.assertIsNone(sc.parse_month_day(bad))


class EntryShapeTest(unittest.TestCase):
    def test_an_example_has_the_documented_defaults_and_keys(self):
        made = entry()
        self.assertEqual((made.peak, made.year, made.last_evaluated_on, made.channels), ("11-20", None, None, ()))
        self.assertEqual(tuple(made.to_dict()), ("entry_id", "name", "keywords", "prep_start", "publish_from", "publish_to", "peak", "repeat", "year", "last_evaluated_on", "channels"))

    def test_a_full_entry_round_trips_through_its_dictionary(self):
        made = entry(repeat="once", year=2026, last_evaluated_on="2026-10-01", channels=("naver_a", "naver_b"), keywords=("예시시기", "예시 구문"))
        self.assertEqual(sc.CalendarEntry.from_dict(made.to_dict()), made)
        self.assertEqual(made.to_dict()["channels"], ["naver_a", "naver_b"])

    def test_an_entry_is_frozen_and_hashable(self):
        made = entry()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            made.name = "바뀜"
        self.assertEqual(len({made, entry()}), 1)

    def test_every_wrong_value_is_refused_with_the_field_named(self):
        bad = (("entry_id", "", "항목 번호"), ("entry_id", "한글", "항목 번호"), ("entry_id", None, "항목 번호"), ("name", "", "이름"), ("name", "가" * 31, "이름"), ("name", "<b>굵게</b>", "이름"),
               ("name", 3, "이름"), ("keywords", (), "시기 낱말"), ("keywords", "문자열", "시기 낱말"), ("keywords", ("!!!",), "시기 낱말"), ("keywords", ("가", "가"), "시기 낱말"),
               ("keywords", ("",), "시기 낱말"), ("keywords", ("가" * 31,), "시기 낱말"), ("keywords", tuple(f"낱말{n}" for n in range(11)), "시기 낱말"), ("keywords", {"가": 1}, "시기 낱말"),
               ("prep_start", "10-32", "준비 시작"), ("prep_start", None, "준비 시작"), ("prep_start", "02-29", "준비 시작"), ("publish_from", "2026-11-01", "발행 기간 시작"),
               ("publish_to", "13-01", "발행 기간 끝"), ("publish_to", 1130, "발행 기간 끝"), ("peak", "11-31", "피크"), ("peak", "", "피크"), ("repeat", "monthly", "반복"), ("repeat", None, "반복"),
               ("year", 2026, "해"), ("last_evaluated_on", "어제", "마지막 평가일"), ("last_evaluated_on", "2026-13-01", "마지막 평가일"), ("last_evaluated_on", 3, "마지막 평가일"),
               ("channels", "naver_a", "적용 채널"), ("channels", ("naver",), "적용 채널"), ("channels", ("blogger_a",), "적용 채널"), ("channels", ("naver_a", "naver_a"), "적용 채널"),
               ("channels", (3,), "적용 채널"), ("channels", None, "적용 채널"))
        for name, value, label in bad:
            with self.subTest(**{name: value}):
                self.assertIn(label, rejected(self, **{name: value}).rendered().message)

    def test_the_message_says_what_is_wrong_in_plain_korean(self):
        message = rejected(self, publish_from="2026-11-01").rendered().message
        self.assertIn("캘린더의 발행 기간 시작", message)
        self.assertIn("월-일 모양", message)

    def test_the_limits_are_accepted_exactly(self):
        made = entry(entry_id="a" * 64, name="가" * 30, keywords=tuple(f"낱말{n}" for n in range(10)))
        self.assertEqual((len(made.entry_id), len(made.name), len(made.keywords)), (64, 30, 10))
        self.assertEqual(entry(keywords=("가" * 30,)).keywords, ("가" * 30,))
        self.assertEqual(entry(channels=("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b")).channels[0], "github_pages")


class RuleLimitsTest(unittest.TestCase):
    def test_the_preparation_may_start_up_to_180_days_before_and_the_same_day_is_fine(self):
        self.assertEqual(entry(prep_start="05-05", publish_from="11-01", publish_to="11-30", peak=None).prep_start, "05-05")
        rejected(self, prep_start="05-04", publish_from="11-01", publish_to="11-30", peak=None)
        self.assertEqual(entry(prep_start="11-01", publish_from="11-01").prep_start, "11-01")

    def test_the_preparation_must_come_before_the_window_even_across_the_new_year(self):
        self.assertEqual(entry(prep_start="12-20", publish_from="01-05", publish_to="01-31", peak="01-10").prep_start, "12-20")
        error = rejected(self, prep_start="11-05", publish_from="11-01", publish_to="11-30")
        self.assertIn("준비 시작", error.rendered().message)

    def test_the_window_may_be_up_to_183_days_long_with_both_ends_counted(self):
        self.assertEqual(entry(prep_start="01-01", publish_from="01-01", publish_to="07-02", peak=None).publish_to, "07-02")
        error = rejected(self, prep_start="01-01", publish_from="01-01", publish_to="07-03", peak=None)
        self.assertIn("발행 기간", error.rendered().message)
        self.assertEqual(entry(prep_start="11-01", publish_from="11-01", publish_to="11-01", peak="11-01").publish_to, "11-01")

    def test_a_window_that_wraps_the_year_is_allowed_and_counted_across_the_new_year(self):
        made = entry(prep_start="12-10", publish_from="12-20", publish_to="01-10", peak="01-02")
        self.assertEqual(made.publish_to, "01-10")
        self.assertEqual(entry(prep_start="12-20", publish_from="12-20", publish_to="06-19", peak=None).publish_to, "06-19")
        rejected(self, prep_start="12-20", publish_from="12-20", publish_to="06-22", peak=None)

    def test_the_peak_must_be_inside_the_window_and_the_edges_count(self):
        for peak in ("11-01", "11-15", "11-30", None):
            with self.subTest(peak=peak):
                self.assertEqual(entry(peak=peak).peak, peak)
        for peak in ("10-31", "12-01", "05-05"):
            with self.subTest(peak=peak):
                self.assertIn("피크", rejected(self, peak=peak).rendered().message)

    def test_the_peak_of_a_wrapped_window_may_be_on_either_side_of_the_new_year(self):
        for peak in ("12-20", "12-31", "01-01", "01-10"):
            with self.subTest(peak=peak):
                self.assertEqual(entry(prep_start="12-10", publish_from="12-20", publish_to="01-10", peak=peak).peak, peak)
        for peak in ("12-19", "01-11", "06-01"):
            with self.subTest(peak=peak):
                rejected(self, prep_start="12-10", publish_from="12-20", publish_to="01-10", peak=peak)

    def test_once_needs_a_year_in_range_and_yearly_must_not_have_one(self):
        self.assertEqual(entry(repeat="once", year=2026).year, 2026)
        self.assertEqual(entry(repeat="once", year=2000).year, 2000)
        self.assertEqual(entry(repeat="once", year=2200).year, 2200)
        for bad in (None, 1999, 2201, True, 2026.0, "2026"):
            with self.subTest(year=bad):
                self.assertIn("해", rejected(self, repeat="once", year=bad).rendered().message)
        self.assertIn("해", rejected(self, repeat="yearly", year=2026).rendered().message)


class PhaseTest(unittest.TestCase):
    def phases(self, made, days):
        return [(day, sc.phase_of(made, day)) for day in days]

    def test_the_window_includes_its_first_and_last_day_and_the_preparation_runs_until_the_day_before(self):
        made = entry()                                   # 준비 10-15 · 발행 11-01 ~ 11-30
        self.assertEqual(self.phases(made, ("2026-10-14", "2026-10-15", "2026-10-31", "2026-11-01", "2026-11-15", "2026-11-30", "2026-12-01")),
                         [("2026-10-14", "outside"), ("2026-10-15", "preparing"), ("2026-10-31", "preparing"), ("2026-11-01", "publishing"), ("2026-11-15", "publishing"),
                          ("2026-11-30", "publishing"), ("2026-12-01", "outside")])

    def test_a_yearly_entry_comes_back_every_year_and_the_far_months_are_outside(self):
        made = entry()
        for year in (2025, 2027, 2030, 2099):
            self.assertEqual(sc.phase_of(made, f"{year}-11-10"), "publishing")
            self.assertEqual(sc.phase_of(made, f"{year}-10-20"), "preparing")
            self.assertEqual(sc.phase_of(made, f"{year}-06-01"), "outside")
            self.assertEqual(sc.phase_of(made, f"{year}-12-31"), "outside")
            self.assertEqual(sc.phase_of(made, f"{year}-01-01"), "outside")

    def test_a_window_across_the_new_year_is_publishing_on_both_sides(self):
        made = entry(prep_start="12-10", publish_from="12-20", publish_to="01-10", peak="01-02")
        expected = (("2026-12-09", "outside"), ("2026-12-10", "preparing"), ("2026-12-19", "preparing"), ("2026-12-20", "publishing"), ("2026-12-31", "publishing"), ("2027-01-01", "publishing"),
                    ("2027-01-10", "publishing"), ("2027-01-11", "outside"), ("2027-12-25", "publishing"), ("2026-01-05", "publishing"), ("2026-01-11", "outside"))
        for day, phase in expected:
            with self.subTest(day=day):
                self.assertEqual(sc.phase_of(made, day), phase)

    def test_a_preparation_that_starts_in_the_year_before_the_window_is_found(self):
        made = entry(prep_start="12-20", publish_from="01-05", publish_to="01-31", peak="01-10")
        for day, phase in (("2026-12-19", "outside"), ("2026-12-20", "preparing"), ("2027-01-04", "preparing"), ("2027-01-05", "publishing"), ("2027-01-31", "publishing"), ("2027-02-01", "outside")):
            with self.subTest(day=day):
                self.assertEqual(sc.phase_of(made, day), phase)

    def test_a_once_entry_runs_only_in_its_own_year(self):
        made = entry(repeat="once", year=2026)
        self.assertEqual(sc.phase_of(made, "2026-11-10"), "publishing")
        self.assertEqual(sc.phase_of(made, "2026-10-20"), "preparing")
        for day in ("2025-11-10", "2027-11-10", "2027-10-20", "2030-11-10"):
            with self.subTest(day=day):
                self.assertEqual(sc.phase_of(made, day), "outside")

    def test_a_once_entry_that_wraps_the_new_year_also_runs_into_the_next_year(self):
        made = entry(repeat="once", year=2026, prep_start="12-10", publish_from="12-20", publish_to="01-10", peak="01-02")
        self.assertEqual(sc.phase_of(made, "2027-01-05"), "publishing")
        self.assertEqual(sc.phase_of(made, "2027-01-11"), "outside")
        self.assertEqual(sc.phase_of(made, "2028-01-05"), "outside")
        self.assertEqual(sc.phase_of(made, "2026-01-05"), "outside", "해 앞쪽 1월은 이 항목의 주기가 아니다")

    def test_a_one_day_window_is_that_day_only_and_does_not_run_to_the_next_year(self):
        one = entry(prep_start="10-25", publish_from="11-01", publish_to="11-01", peak="11-01")
        for day, phase in (("2026-10-31", "preparing"), ("2026-11-01", "publishing"), ("2026-11-02", "outside"), ("2027-03-01", "outside"), ("2027-10-31", "preparing"), ("2027-11-01", "publishing")):
            with self.subTest(day=day):
                self.assertEqual(sc.phase_of(one, day), phase)
        self.assertEqual(sc.cycle_of(one, 2026), sc.Cycle("2026-10-25", "2026-11-01", "2026-11-01", "2026-11-01"))

    def test_a_peak_on_the_first_day_of_the_window_is_in_the_same_year_as_the_start(self):
        made = entry(prep_start="10-25", publish_from="11-01", publish_to="11-30", peak="11-01")
        self.assertEqual(sc.cycle_of(made, 2026).peak, "2026-11-01")
        wrapped = entry(prep_start="12-10", publish_from="12-20", publish_to="01-10", peak="12-20")
        self.assertEqual(sc.cycle_of(wrapped, 2026), sc.Cycle("2026-12-10", "2026-12-20", "2027-01-10", "2026-12-20"))
        after_new_year = entry(prep_start="12-10", publish_from="12-20", publish_to="01-10", peak="01-10")
        self.assertEqual(sc.cycle_of(after_new_year, 2026).peak, "2027-01-10")

    def test_a_leap_year_has_its_extra_day_inside_the_window(self):
        made = entry(prep_start="02-10", publish_from="02-20", publish_to="03-05", peak=None)
        self.assertEqual(sc.phase_of(made, "2028-02-29"), "publishing")
        self.assertEqual(sc.phase_of(made, "2028-03-05"), "publishing")
        self.assertEqual(sc.phase_of(made, "2028-03-06"), "outside")
        self.assertEqual(sc.phase_of(made, "2027-03-05"), "publishing")
        self.assertEqual(sc.phase_of(made, "2027-03-06"), "outside")

    def test_the_cycle_dates_follow_the_year_and_the_preparation_is_counted_in_days(self):
        made = entry(prep_start="02-19", publish_from="03-01", publish_to="03-31", peak="03-15")
        self.assertEqual(sc.cycle_of(made, 2027), sc.Cycle("2027-02-19", "2027-03-01", "2027-03-31", "2027-03-15"))
        self.assertEqual(sc.cycle_of(made, 2028), sc.Cycle("2028-02-20", "2028-03-01", "2028-03-31", "2028-03-15"), "윤년에는 2월 29일이 끼어 같은 10일 앞이 하루 늦은 날짜(2월 20일)다")
        wrapped = entry(prep_start="12-10", publish_from="12-20", publish_to="01-10", peak="01-02")
        self.assertEqual(sc.cycle_of(wrapped, 2026), sc.Cycle("2026-12-10", "2026-12-20", "2027-01-10", "2027-01-02"))
        self.assertIsNone(sc.cycle_of(entry(peak=None), 2026).peak)

    def test_a_once_entry_has_a_cycle_only_in_its_year(self):
        made = entry(repeat="once", year=2026)
        self.assertEqual(sc.cycle_of(made, 2026).start, "2026-11-01")
        self.assertIsNone(sc.cycle_of(made, 2027))
        self.assertIsNone(sc.cycle_of(made, 2025))
        for bad in (1999, 2201, True, "2026", None):
            with self.assertRaises(AppError):
                sc.cycle_of(made, bad)

    def test_the_day_argument_is_checked_and_nothing_reads_the_clock(self):
        for bad in ("어제", None, "2026-13-01", 20261110, "2026-11-1", "2201-01-01", "1999-12-31"):
            with self.subTest(on=bad):
                with self.assertRaises(AppError):
                    sc.phase_of(entry(), bad)
        with self.assertRaises(TypeError):
            sc.phase_of({"name": "x"}, "2026-11-10")
        with self.assertRaises(TypeError):
            sc.cycle_of("x", 2026)

    def test_the_same_day_gives_the_same_answer_every_time(self):
        made = entry()
        self.assertEqual({sc.phase_of(made, "2026-11-10") for _ in range(5)}, {"publishing"})

    def test_the_last_allowed_year_does_not_overflow(self):
        self.assertEqual(sc.phase_of(entry(), "2200-12-31"), "outside")
        self.assertEqual(sc.phase_of(entry(), "2200-11-10"), "publishing")
        self.assertEqual(sc.phase_of(entry(prep_start="12-10", publish_from="12-20", publish_to="01-10", peak=None), "2200-12-25"), "publishing")


class CalendarStateTest(unittest.TestCase):
    def test_a_topic_inside_a_window_is_due_and_the_entry_is_listed(self):
        found = sc.calendar_state([entry()], ["예시시기 준비 방법"], "2026-11-10")
        self.assertEqual(found.state, "due")
        self.assertEqual(found.matched, (sc.EntryPhase("ex-cal-001", "예시 시기 하나", "publishing"),))

    def test_the_edges_of_the_window_are_due_and_the_days_around_it_are_not(self):
        for day, state in (("2026-10-31", "out_of_range"), ("2026-11-01", "due"), ("2026-11-30", "due"), ("2026-12-01", "out_of_range")):
            with self.subTest(day=day):
                self.assertEqual(sc.calendar_state([entry()], ["예시시기"], day).state, state)

    def test_a_topic_of_an_entry_in_preparation_or_far_away_is_out_of_range_and_not_unknown(self):
        for day in ("2026-10-20", "2026-06-01", "2027-02-01"):
            with self.subTest(day=day):
                found = sc.calendar_state([entry()], ["예시시기"], day)
                self.assertEqual(found.state, "out_of_range")
                self.assertEqual(len(found.matched), 1)

    def test_a_topic_without_any_matching_entry_is_unknown_and_not_out_of_range(self):
        for entries in ([], [entry()]):
            found = sc.calendar_state(entries, ["전혀 다른 글"], "2026-11-10")
            self.assertEqual((found.state, found.matched), ("unknown", ()))

    def test_a_whole_word_is_needed_a_letter_piece_of_a_word_does_not_count(self):
        card = entry(keywords=("카드",), name="예시 카드 시기")
        for text, expected in (("카드 혜택 비교", "due"), ("카드를 정리하는 법", "due"), ("신용 카드 고르기", "due"), ("그래픽카드 고르는 법", "unknown"), ("카드뮴 중독", "unknown"), ("사운드카드", "unknown"),
                               ("카드값", "unknown"), ("CARD 정리", "unknown")):
            with self.subTest(text=text):
                self.assertEqual(sc.calendar_state([card], [text], "2026-11-10").state, expected)

    def test_a_phrase_needs_its_words_side_by_side_in_the_same_order(self):
        phrase = entry(keywords=("새해 계획",), name="예시 새해")
        for text, expected in (("새해 계획 세우기", "due"), ("올해의 새해 계획을 점검", "due"), ("새해 그리고 계획", "unknown"), ("계획 새해", "unknown"), ("새해", "unknown")):
            with self.subTest(text=text):
                self.assertEqual(sc.calendar_state([phrase], [text], "2026-11-10").state, expected)

    def test_a_particle_after_the_word_is_ignored_and_case_width_and_spacing_do_not_matter(self):
        made = entry(keywords=("예시시기",))
        for text in ("예시시기에 맞는 글", "예시시기를 위한", "예시시기는", "ＹＥ".replace("ＹＥ", "예시시기"), "   예시시기   ", "다른 말 예시시기"):
            with self.subTest(text=text):
                self.assertEqual(sc.calendar_state([made], [text], "2026-11-10").state, "due")
        english = entry(keywords=("Black Friday",), name="예시 영문")
        for text in ("black friday deals", "BLACK  FRIDAY tips".replace("  ", " "), "ＢＬＡＣＫ ＦＲＩＤＡＹ"):
            with self.subTest(text=text):
                self.assertEqual(sc.calendar_state([english], [text], "2026-11-10").state, "due")

    def test_any_of_the_given_texts_may_hold_the_word_but_a_phrase_must_sit_inside_one_text(self):
        phrase = entry(keywords=("새해 계획",))
        self.assertEqual(sc.calendar_state([phrase], ["새해", "계획"], "2026-11-10").state, "unknown")
        self.assertEqual(sc.calendar_state([phrase], ["아무 말", "새해 계획 세우기"], "2026-11-10").state, "due")
        word = entry(keywords=("예시시기",))
        self.assertEqual(sc.calendar_state([word], ["아무 말", "또 아무 말", "예시시기"], "2026-11-10").state, "due")

    def test_one_due_entry_among_several_matching_ones_makes_the_topic_due(self):
        due = entry(entry_id="b-due", keywords=("겹침",), name="예시 둘째")
        far = entry(entry_id="a-far", keywords=("겹침",), name="예시 첫째", prep_start="05-01", publish_from="05-10", publish_to="05-31", peak=None)
        found = sc.calendar_state([due, far], ["겹침 글"], "2026-11-10")
        self.assertEqual(found.state, "due")
        self.assertEqual([item.entry_id for item in found.matched], ["a-far", "b-due"])
        self.assertEqual([item.phase for item in found.matched], ["outside", "publishing"])

    def test_the_result_does_not_depend_on_the_order_of_the_entries(self):
        pool = [entry(entry_id=f"e{n}", keywords=("겹침",), name=f"예시 {n}") for n in range(4)]
        expected = sc.calendar_state(pool, ["겹침"], "2026-11-10")
        for order in itertools.permutations(pool):
            self.assertEqual(sc.calendar_state(list(order), ["겹침"], "2026-11-10"), expected)

    def test_an_entry_limited_to_other_channels_does_not_apply(self):
        only_a = entry(channels=("naver_a",))
        self.assertEqual(sc.calendar_state([only_a], ["예시시기"], "2026-11-10", "naver_a").state, "due")
        self.assertEqual(sc.calendar_state([only_a], ["예시시기"], "2026-11-10", "naver_b").state, "unknown")
        self.assertEqual(sc.calendar_state([only_a], ["예시시기"], "2026-11-10").state, "due", "채널을 안 주면 거르지 않는다")
        self.assertTrue(entry().applies_to("blogger_en"))
        self.assertFalse(only_a.applies_to("naver_b"))

    def test_a_candidate_is_judged_by_its_topic_keywords_and_channel(self):
        made = ts.make(topic="올해 예시시기를 준비하는 방법", primary_keyword="핵심어", channel="naver_a")
        self.assertEqual(sc.state_of(made, [entry()], "2026-11-10").state, "due")
        by_keyword = ts.make(topic="아무 주제", primary_keyword="예시시기", channel="naver_a")
        self.assertEqual(sc.state_of(by_keyword, [entry()], "2026-11-10").state, "due")
        by_second = ts.make(topic="아무 주제", primary_keyword="핵심어", secondary_keywords=("예시시기 정리",), channel="naver_a")
        self.assertEqual(sc.state_of(by_second, [entry()], "2026-11-10").state, "due")
        self.assertEqual(sc.state_of(made, [entry(channels=("naver_b",))], "2026-11-10").state, "unknown")
        self.assertEqual(sc.state_of(ts.make(), [entry()], "2026-11-10").state, "unknown")

    def test_the_state_goes_straight_into_the_timing_score_of_the_first_phase(self):
        rising = score.timing_score(sc.calendar_state([entry()], ["예시시기"], "2026-11-10").state, "rising")
        self.assertEqual((rising.score, rising.realtime), (90, False))
        out = score.timing_score(sc.calendar_state([entry()], ["예시시기"], "2026-12-10").state, "rising")
        self.assertEqual((out.score, out.realtime), (70, True), "범위 밖인데 관심도가 오르면 실시간 후보 표시")
        unknown = score.timing_score(sc.calendar_state([], ["글"], "2026-11-10").state, "insufficient")
        self.assertIsNone(unknown.score, "캘린더에도 없고 관심도도 모르면 평가 불가 — 0 점이 아니다")
        with_trend = score.timing_score(sc.calendar_state([], ["글"], "2026-11-10").state, "flat")
        self.assertEqual(with_trend.score, 50)

    def test_wrong_kinds_are_programming_errors(self):
        for args in (([None], ["글"], "2026-11-10"), ([entry()], "글", "2026-11-10"), ([entry()], [3], "2026-11-10"), ([entry()], None, "2026-11-10"), ([{"name": "x"}], ["글"], "2026-11-10")):
            with self.subTest(args=repr(args)[:30]):
                with self.assertRaises(TypeError):
                    sc.calendar_state(*args)
        for bad in ("어제", None, "2026-11-1"):
            with self.assertRaises(AppError):
                sc.calendar_state([entry()], ["글"], bad)
        for bad in ("naver", "", 3):
            with self.assertRaises(ValueError):
                sc.calendar_state([entry()], ["글"], "2026-11-10", bad)
        with self.assertRaises(TypeError):
            sc.state_of({"topic": "x"}, [entry()], "2026-11-10")

    def test_the_inputs_are_not_changed(self):
        pool = [entry(), entry(entry_id="e2", keywords=("다른말",), name="예시 둘")]
        before = [item.to_dict() for item in pool]
        sc.calendar_state(iter(pool), iter(["예시시기"]), "2026-11-10")
        self.assertEqual([item.to_dict() for item in pool], before)


class EvaluationTest(unittest.TestCase):
    def test_a_never_evaluated_entry_has_an_unknown_age_and_needs_evaluating(self):
        made = entry()
        self.assertIsNone(sc.evaluation_age(made, "2026-11-05"))
        self.assertTrue(sc.needs_evaluation(made, "2026-11-05"))

    def test_the_age_counts_the_days_and_the_thirtieth_day_is_the_first_that_needs_a_new_evaluation(self):
        made = entry(last_evaluated_on="2026-10-06")
        self.assertEqual(sc.evaluation_age(made, "2026-10-06"), 0)
        self.assertEqual(sc.evaluation_age(made, "2026-11-04"), 29)
        self.assertEqual(sc.evaluation_age(made, "2026-11-05"), 30)
        self.assertFalse(sc.needs_evaluation(made, "2026-11-04"))
        self.assertTrue(sc.needs_evaluation(made, "2026-11-05"))
        self.assertTrue(sc.needs_evaluation(made, "2027-01-01"))
        self.assertFalse(sc.needs_evaluation(made, "2026-10-06"))

    def test_an_evaluation_day_after_today_is_age_zero_and_the_interval_can_change(self):
        made = entry(last_evaluated_on="2026-11-10")
        self.assertEqual(sc.evaluation_age(made, "2026-11-05"), 0)
        self.assertFalse(sc.needs_evaluation(made, "2026-11-05"))
        week = entry(last_evaluated_on="2026-10-29")
        self.assertTrue(sc.needs_evaluation(week, "2026-11-05", max_age_days=7))
        self.assertFalse(sc.needs_evaluation(week, "2026-11-05", max_age_days=8))

    def test_wrong_inputs_are_refused(self):
        for bad in (0, -1, 3651, True, 30.0, None, "30"):
            with self.subTest(max_age_days=bad):
                with self.assertRaises(AppError):
                    sc.needs_evaluation(entry(), "2026-11-05", max_age_days=bad)
        for bad in ("어제", None, "2026-11-1"):
            with self.assertRaises(AppError):
                sc.evaluation_age(entry(), bad)
        with self.assertRaises(TypeError):
            sc.evaluation_age({"last_evaluated_on": None}, "2026-11-05")


class JsonShapeTest(unittest.TestCase):
    def several(self):
        return [entry(entry_id="e1"), entry(entry_id="e2", name="예시 둘째", keywords=("둘째말",), prep_start="12-10", publish_from="12-20", publish_to="01-10", peak="01-02"),
                entry(entry_id="e3", name="예시 셋째", keywords=("셋째말", "셋째 구문"), repeat="once", year=2027, last_evaluated_on="2026-10-01", channels=("naver_a",), peak=None)]

    def test_the_empty_template_has_the_schema_and_an_empty_list(self):
        self.assertEqual(sc.entries_to_dict(()), {"schema": 1, "entries": []})
        self.assertEqual(sc.entries_from_dict({"schema": 1, "entries": []}), ())

    def test_the_entries_round_trip_in_the_same_order(self):
        data = sc.entries_to_dict(self.several())
        self.assertEqual(tuple(data), ("schema", "entries"))
        self.assertEqual(sc.entries_from_dict(data), tuple(self.several()))
        self.assertEqual(sc.entries_to_dict(sc.entries_from_dict(data)), data)

    def test_a_wrong_schema_or_top_level_shape_is_refused(self):
        good = sc.entries_to_dict(self.several())
        for bad in (None, [], "x", 3, {}, dict(good, schema=0), dict(good, schema=2), dict(good, schema=True), dict(good, schema="1"), dict(good, extra=1), {"schema": 1}, {"entries": []},
                    dict(good, entries={}), dict(good, entries="x"), dict(good, entries=None)):
            with self.subTest(bad=repr(bad)[:40]):
                with self.assertRaises(AppError) as caught:
                    sc.entries_from_dict(bad)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_an_entry_with_an_unknown_or_missing_field_is_refused_and_its_number_is_in_the_message(self):
        good = sc.entries_to_dict(self.several())
        for index in range(len(good["entries"])):
            for name in good["entries"][index]:
                broken = copy.deepcopy(good)
                del broken["entries"][index][name]
                with self.subTest(index=index, missing=name):
                    with self.assertRaises(AppError) as caught:
                        sc.entries_from_dict(broken)
                    self.assertIn(f"{index + 1}번째 캘린더", caught.exception.rendered().message)
        extra = copy.deepcopy(good)
        extra["entries"][0]["unknown"] = 1
        with self.assertRaises(AppError) as caught:
            sc.entries_from_dict(extra)
        self.assertIn("모르는 칸", caught.exception.rendered().message)
        for bad_entry in (None, [], "x", 3):
            broken = copy.deepcopy(good)
            broken["entries"][1] = bad_entry
            with self.subTest(entry=repr(bad_entry)):
                with self.assertRaises(AppError) as caught:
                    sc.entries_from_dict(broken)
                self.assertIn("2번째 캘린더", caught.exception.rendered().message)

    def test_every_field_with_a_wrong_type_is_refused_when_reading(self):
        good = sc.entries_to_dict(self.several())
        wrong = {"entry_id": 3, "name": None, "keywords": "x", "prep_start": 1015, "publish_from": None, "publish_to": [], "peak": 1120, "repeat": 1, "year": "2026", "last_evaluated_on": 3, "channels": "naver_a"}
        for name, value in wrong.items():
            broken = copy.deepcopy(good)
            broken["entries"][0][name] = value
            with self.subTest(field=name):
                with self.assertRaises(AppError):
                    sc.entries_from_dict(broken)

    def test_a_value_that_breaks_a_rule_is_refused_when_reading_too(self):
        good = sc.entries_to_dict(self.several())
        for name, value in (("publish_to", "08-31"), ("peak", "12-25"), ("prep_start", "03-01"), ("year", 2026)):
            broken = copy.deepcopy(good)
            broken["entries"][0][name] = value
            with self.subTest(**{name: value}):
                with self.assertRaises(AppError):
                    sc.entries_from_dict(broken)

    def test_the_same_number_twice_is_refused(self):
        with self.assertRaises(AppError) as caught:
            sc.entries_to_dict([entry(entry_id="same"), entry(entry_id="same", name="예시 둘")])
        self.assertIn("같은 항목 번호", caught.exception.rendered().message)
        data = sc.entries_to_dict(self.several())
        data["entries"][2]["entry_id"] = "e1"
        with self.assertRaises(AppError):
            sc.entries_from_dict(data)

    def test_the_size_limit_is_enforced_both_ways(self):
        many = [entry(entry_id=f"e{n}") for n in range(sc.MAX_ENTRIES)]
        data = sc.entries_to_dict(many)
        self.assertEqual(len(sc.entries_from_dict(data)), sc.MAX_ENTRIES)
        with self.assertRaises(AppError):
            sc.entries_to_dict(many + [entry(entry_id="one-more")])
        data["entries"].append(dict(data["entries"][0], entry_id="one-more"))
        with self.assertRaises(AppError):
            sc.entries_from_dict(data)

    def test_only_entries_can_be_written_and_the_dictionary_is_plain_json_data(self):
        import json
        for bad in ([{"entry_id": "x"}], [None]):
            with self.assertRaises(AppError):
                sc.entries_to_dict(bad)
        data = sc.entries_to_dict(self.several())
        self.assertEqual(sc.entries_from_dict(json.loads(json.dumps(data, ensure_ascii=False))), tuple(self.several()))

    def test_reading_does_not_change_the_input(self):
        data = sc.entries_to_dict(self.several())
        before = copy.deepcopy(data)
        sc.entries_from_dict(data)
        self.assertEqual(data, before)


class NoRealCalendarTest(unittest.TestCase):
    def test_the_module_holds_no_calendar_entries_only_the_rules_and_the_empty_template(self):
        lists = [name for name, value in vars(sc).items() if isinstance(value, (tuple, list)) and value and all(isinstance(item, sc.CalendarEntry) for item in value)]
        self.assertEqual(lists, [])

    def test_the_existing_month_table_is_left_alone_and_not_read(self):
        import inspect
        source = inspect.getsource(sc)
        self.assertNotIn("suggest_data", source.split('"""', 2)[2], "월별 시기 표를 가져오지 않는다")
        self.assertNotIn("SEASONS", source.split('"""', 2)[2])


if __name__ == "__main__":
    unittest.main()
