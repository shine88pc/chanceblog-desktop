"""보류함 만료일 시험 — 평가한 시각 + 90일, 보류 구간이 아니면 만료일 없음, 정각 경계, 달력 끝, 입력 검사.

지키는 것:
  1) 만료일은 평가한 시각에 `HOLD_DAYS`(90)일을 더한 UTC 시각 글이다 — 후보의 `review_expires_at` 칸이 그대로 받아들이는 모양이다.
  2) 보류 구간(HOLD)만 만료일이 있고 나머지 구간(우선 추천·일반·제외·점수 없음)은 None 이다. 구간 이름이 틀리면 거절한다.
  3) 지났는가는 '지금 >= 만료일' 이다 — 만료 1초 전은 아직이고 정각은 지난 것이다. 만료일이 없는 후보는 지나지 않는다.
  4) 이 모듈은 시계를 읽지 않고 아무것도 바꾸지 않는다(날짜는 늘 인자).
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import hold  # noqa: E402
from chanceblog_desktop.topics import score as sc  # noqa: E402


class ExpiryDateTest(unittest.TestCase):
    def test_ninety_days_after_the_evaluation_is_the_default(self):
        self.assertEqual(ch.HOLD_DAYS, 90)
        self.assertEqual(hold.review_expires_at("2026-11-05T09:00:00Z"), "2027-02-03T09:00:00Z")
        self.assertEqual(hold.review_expires_at("2026-11-05T09:00:00Z", 90), "2027-02-03T09:00:00Z")

    def test_the_time_of_day_is_kept_and_the_month_ends_roll_over_correctly(self):
        self.assertEqual(hold.review_expires_at("2026-01-01T00:00:00Z"), "2026-04-01T00:00:00Z")
        self.assertEqual(hold.review_expires_at("2026-12-31T23:59:59Z"), "2027-03-31T23:59:59Z")
        self.assertEqual(hold.review_expires_at("2027-12-01T12:34:56Z", 1), "2027-12-02T12:34:56Z")

    def test_a_leap_day_is_counted(self):
        self.assertEqual(hold.review_expires_at("2027-12-01T00:00:00Z"), "2028-02-29T00:00:00Z")
        self.assertEqual(hold.review_expires_at("2028-01-01T00:00:00Z"), "2028-03-31T00:00:00Z")

    def test_another_number_of_days_can_be_given_within_the_limit(self):
        self.assertEqual(hold.review_expires_at("2026-11-05T00:00:00Z", 30), "2026-12-05T00:00:00Z")
        self.assertEqual(hold.review_expires_at("2026-11-05T00:00:00Z", hold.MAX_DAYS), "2036-11-02T00:00:00Z")
        for bad in (0, -1, hold.MAX_DAYS + 1, 90.0, True, "90", None):
            with self.subTest(days=bad):
                with self.assertRaises(AppError):
                    hold.review_expires_at("2026-11-05T00:00:00Z", bad)

    def test_the_result_is_accepted_by_the_candidate_as_its_review_deadline(self):
        for day in ("2026-11-05T09:00:00Z", "2026-12-31T23:59:59Z", "2028-02-29T00:00:00Z"):
            with self.subTest(evaluated_at=day):
                expires = hold.review_expires_at(day)
                made = ts.make(created_at=day, scores=ts.flat_card(60), review_expires_at=expires)
                self.assertEqual((made.review_expires_at, made.recommendation_band), (expires, sc.BAND_HOLD))

    def test_a_wrong_time_is_refused_with_the_candidate_error_in_plain_korean(self):
        for bad in ("2026-11-05", "2026-11-05T09:00:00", "2026-11-05T09:00:00+09:00", "2026-13-05T09:00:00Z", "1999-12-31T00:00:00Z", "", None, 3, "내일"):
            with self.subTest(evaluated_at=bad):
                with self.assertRaises(AppError) as caught:
                    hold.review_expires_at(bad)
                self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")
                self.assertIn("평가한 시각", caught.exception.rendered().message)

    def test_the_end_of_the_calendar_is_an_app_error_and_not_an_overflow(self):
        self.assertEqual(hold.review_expires_at("9999-09-01T00:00:00Z"), "9999-11-30T00:00:00Z")
        for stamp in ("9999-10-03T00:00:00Z", "9999-12-31T23:59:59Z"):
            with self.subTest(evaluated_at=stamp):
                with self.assertRaises(AppError) as caught:
                    hold.review_expires_at(stamp)
                self.assertIn("너무 먼 미래", caught.exception.rendered().message)


class BandRuleTest(unittest.TestCase):
    def test_only_the_hold_band_has_an_expiry(self):
        for band in sc.BANDS:
            with self.subTest(band=band):
                expected = "2027-02-03T09:00:00Z" if band == sc.BAND_HOLD else None
                self.assertEqual(hold.expiry_for(band, "2026-11-05T09:00:00Z"), expected)

    def test_it_follows_the_band_of_the_final_score_at_the_edges(self):
        for final, has_expiry in ((80, False), (65, False), (64, True), (50, True), (49, False), (None, False)):
            with self.subTest(final=final):
                expiry = hold.expiry_for(sc.band_of(final), "2026-11-05T09:00:00Z")
                self.assertEqual(expiry is not None, has_expiry)

    def test_a_candidate_made_from_the_band_gets_a_valid_deadline(self):
        held = ts.rated(60)
        expiry = hold.expiry_for(held.recommendation_band, held.created_at)
        again = dataclasses.replace(held, review_expires_at=expiry)
        self.assertEqual(again.review_expires_at, "2027-02-02T09:56:00Z")
        self.assertIsNone(hold.expiry_for(ts.rated(70).recommendation_band, ts.STAMP))

    def test_the_day_count_can_be_changed_here_too_and_unknown_bands_are_refused(self):
        self.assertEqual(hold.expiry_for(sc.BAND_HOLD, "2026-11-05T00:00:00Z", 10), "2026-11-15T00:00:00Z")
        for bad in ("hold", "", None, 3, "REJECTED", "NEW"):
            with self.subTest(band=bad):
                with self.assertRaises(ValueError):
                    hold.expiry_for(bad, "2026-11-05T00:00:00Z")
        with self.assertRaises(AppError):
            hold.expiry_for(sc.BAND_RECOMMENDED, "엉터리")


class ExpiredTest(unittest.TestCase):
    EXPIRES = "2027-02-03T09:00:00Z"

    def test_one_second_before_is_not_yet_and_the_exact_moment_is_over(self):
        self.assertFalse(hold.is_expired(self.EXPIRES, "2027-02-03T08:59:59Z"))
        self.assertTrue(hold.is_expired(self.EXPIRES, "2027-02-03T09:00:00Z"))
        self.assertTrue(hold.is_expired(self.EXPIRES, "2027-02-03T09:00:01Z"))

    def test_the_evaluation_day_and_the_89th_day_are_not_expired_the_90th_is(self):
        start = "2026-11-05T09:00:00Z"
        expires = hold.review_expires_at(start)
        self.assertFalse(hold.is_expired(expires, start))
        self.assertFalse(hold.is_expired(expires, hold.review_expires_at(start, 89)))
        self.assertTrue(hold.is_expired(expires, hold.review_expires_at(start, 90)))
        self.assertTrue(hold.is_expired(expires, hold.review_expires_at(start, 91)))

    def test_no_deadline_never_expires_but_the_clock_value_is_still_checked(self):
        self.assertFalse(hold.is_expired(None, "2999-01-01T00:00:00Z"))
        with self.assertRaises(AppError):
            hold.is_expired(None, "어제")

    def test_wrong_times_are_refused(self):
        for expires, now in (("엉터리", "2027-02-03T09:00:00Z"), (self.EXPIRES, "엉터리"), (self.EXPIRES, None), (3, "2027-02-03T09:00:00Z"), (self.EXPIRES, "2027-02-03")):
            with self.subTest(expires=expires, now=now):
                with self.assertRaises(AppError):
                    hold.is_expired(expires, now)

    def test_expiry_does_not_depend_on_any_clock_and_changes_nothing(self):
        held = ts.rated(60, review_expires_at=self.EXPIRES)
        snapshot = held.to_dict()
        for _ in range(3):
            self.assertTrue(hold.is_expired(held.review_expires_at, "2030-01-01T00:00:00Z"))
        self.assertEqual(held.to_dict(), snapshot)


class NamesTest(unittest.TestCase):
    def test_the_public_names_are_these(self):
        self.assertEqual(sorted(hold.__all__), ["MAX_DAYS", "expiry_for", "is_expired", "review_expires_at"])
        self.assertEqual(hold.MAX_DAYS, 3650)
        self.assertEqual(hold.BAND_HOLD, "HOLD")


if __name__ == "__main__":
    unittest.main()
