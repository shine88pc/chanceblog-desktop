"""보류 90일 규칙 맞춤과 상세 정리(P3b-1 S5) 시험 — 운영자 결정: 90일은 **최초로 보류에 든 시각**이 기준이고 일반 재평가로 초기화하지 않으며 다른 구간으로 잠시 이동했다가 자동으로 돌아와도 최초 시각을 유지하고
**사용자가 직접 다시 활성화할 때만** 새 주기다(D-62 정정). 90일 뒤 변화가 없으면 상세 데이터를 정리하되(자동 삭제 금지 — 미리 보기가 기본, `--yes` 가 있어야 정리) 이력 11칸은 남기고, 정리 뒤에도 같은 후보를 알아본다.

입력은 시험용 예시이고 시계를 읽지 않는다(시각은 인자로 준다).
"""
import dataclasses
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402
from test_service_topics import World, tree  # noqa: E402
from test_topicdb_store import CREATED, DAY90, NOW, cand, code_of, connect, digest, hold_cand, raw, v1_class  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import topic_format as tfmt  # noqa: E402
from chanceblog_desktop.service import topics as tp  # noqa: E402
from chanceblog_desktop.topicdb.store import HOLD_HISTORY_FIELDS, CleanupTokenMismatch, HoldCleanup, Lineage, TopicStore, open_for_write, open_read_only  # noqa: E402
from chanceblog_desktop.topics import hold, slots  # noqa: E402
from chanceblog_desktop.topics.link import CandidateLink  # noqa: E402

# D-120 의도적 갱신(판 2 는 배포 전이라 같은 판 2 안에서 고쳤다): 이력이 11칸 → 13칸 — `first_created_on`(날짜)이 `first_created_at`(후보의 만든 시각 그대로)이 되고 `cleaned_at`·`cleanup_reason` 이 더해졌다
FIELDS_13 = ("normalized_keyword", "topic_summary", "first_created_at", "last_evaluated_on", "hold_reason", "exclusion_reason", "normalized_topic_hash", "seed_id", "channel", "search_intent", "topic_angle",
             "cleaned_at", "cleanup_reason")
OPERATOR_MINIMUM = ("normalized_topic_hash", "seed_id", "channel", "search_intent", "topic_angle", "first_created_at", "cleaned_at", "cleanup_reason")       # 운영자가 '최소한' 으로 적은 8칸 — 이름 그대로 있어야 한다


class Abort(BaseException):
    """`except Exception` 이 잡지 않는 '큰 실패'(행 단위 처리 밖으로 번지는 멈춤)를 흉내 낸다."""


def cleaned(rows):
    return tuple(row.candidate_id for row in rows if row.status == "cleaned")


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"
        self.store = TopicStore.open(self.path)
        self.addCleanup(self.store.close)

    def stays(self, open_only=False):
        return [tuple(stay) for stay in self.store.hold_stays(open_only=open_only)]

    def token(self, now):
        """미리 보기가 보이는 확인 번호 — 지금(`now`)의 정리 대상으로 만든다(D-120)."""
        return hold.cleanup_token(self.store.hold_cleanup_targets(now))


class FirstHoldTimeTest(StoreCase):
    def test_the_ninety_days_start_at_the_first_time_and_every_ordinary_re_evaluation_keeps_them(self):
        self.store.add_candidates(lambda existing: [hold_cand(1)], now=NOW)
        for when in ("2026-12-01T00:00:00Z", "2027-01-15T00:00:00Z", "2027-02-07T00:00:00Z"):
            kept = self.store.re_evaluate(dataclasses.replace(hold_cand(1), scores=ts.flat_card(58)), evaluated_at=when)
            self.assertEqual(kept.review_expires_at, DAY90)
        self.assertEqual(self.stays(), [("cid-001", CREATED, DAY90, None)])

    def test_leaving_for_another_band_and_coming_back_by_itself_keeps_the_first_time_even_several_times(self):
        self.store.add_candidates(lambda existing: [hold_cand(1)], now=NOW)
        cycle = (("2026-12-01T00:00:00Z", 72), ("2026-12-20T00:00:00Z", 55), ("2027-01-10T00:00:00Z", 40), ("2027-01-25T00:00:00Z", 61))
        for when, final in cycle:
            moved = self.store.re_evaluate(dataclasses.replace(hold_cand(1), scores=ts.flat_card(final), review_expires_at=DAY90 if 50 <= final < 65 else None), evaluated_at=when)
            self.assertEqual(moved.review_expires_at, DAY90 if 50 <= final < 65 else None)
        self.assertEqual(self.stays(), [("cid-001", CREATED, DAY90, None)], "최초 시각과 기한은 처음 그대로다")
        self.assertEqual(self.store.check(), [])

    def test_a_candidate_that_first_falls_into_the_band_later_starts_its_ninety_days_then(self):
        self.store.add_candidates(lambda existing: [cand(2, final=70)], now=NOW)
        fell = self.store.re_evaluate(dataclasses.replace(cand(2, final=70), scores=ts.flat_card(60)), evaluated_at="2026-12-01T00:00:00Z")
        self.assertEqual(fell.review_expires_at, "2027-03-01T00:00:00Z")
        self.assertEqual(self.stays(), [("cid-002", "2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z", None)])


class DirectReactivationTest(StoreCase):
    LATER = "2027-01-20T00:00:00Z"

    def test_reactivating_a_held_candidate_by_hand_starts_a_new_ninety_days(self):
        self.store.add_candidates(lambda existing: [hold_cand(1)], now=NOW)
        self.store.set_work_status("cid-001", "HOLD")
        moved = self.store.set_work_status("cid-001", "REVIEW", now=self.LATER)
        self.assertEqual(moved.review_expires_at, "2027-04-20T00:00:00Z", "직접 다시 활성화한 때부터 90일")
        self.assertEqual(self.stays(), [("cid-001", self.LATER, "2027-04-20T00:00:00Z", None)])
        self.assertEqual(raw(self.path, "SELECT review_expires_at FROM candidates")[0][0], "2027-04-20T00:00:00Z")
        self.assertEqual(self.store.load_candidate("cid-001"), moved)
        self.assertEqual(self.store.check(), [])

    def test_all_three_reactivation_moves_count_and_no_other_move_does(self):
        for number, (before, after) in enumerate((("HOLD", "REVIEW"), ("HOLD", "SELECTED"), ("REJECTED", "REVIEW")), start=1):
            self.store.add_candidates(lambda existing, n=number: [hold_cand(n)], now=NOW)
            if before != "NEW":
                self.store.set_work_status(f"cid-{number:03d}", before)
            moved = self.store.set_work_status(f"cid-{number:03d}", after, now=self.LATER)
            self.assertEqual(moved.review_expires_at, "2027-04-20T00:00:00Z", (before, after))
        plain = [(number, before, after) for number, (before, after) in enumerate((("NEW", "REVIEW"), ("NEW", "SELECTED"), ("NEW", "HOLD"), ("NEW", "REJECTED")), start=10)]
        for number, before, after in plain:
            self.store.add_candidates(lambda existing, n=number: [hold_cand(n)], now=NOW)
            moved = self.store.set_work_status(f"cid-{number:03d}", after)
            self.assertEqual(moved.review_expires_at, DAY90, f"{before} → {after} 는 다시 활성화가 아니다")
        self.store.set_work_status("cid-010", "SELECTED")
        self.assertEqual(self.store.set_work_status("cid-010", "REVIEW").review_expires_at, DAY90, "선택됨 → 검토 중도 다시 활성화가 아니다")

    def test_a_closed_stay_also_starts_fresh_so_a_later_automatic_return_keeps_the_new_first_time(self):
        self.store.add_candidates(lambda existing: [hold_cand(1)], now=NOW)
        self.store.re_evaluate(dataclasses.replace(hold_cand(1), scores=ts.flat_card(72), review_expires_at=None), evaluated_at="2026-12-01T00:00:00Z")
        self.store.set_work_status("cid-001", "REJECTED")
        self.store.set_work_status("cid-001", "REVIEW", now=self.LATER)
        self.assertEqual(self.stays(), [("cid-001", self.LATER, "2027-04-20T00:00:00Z", "2026-12-01T00:00:00Z")], "닫힌 기록도 새 주기의 시작과 기한이 된다")
        back = self.store.re_evaluate(dataclasses.replace(hold_cand(1), scores=ts.flat_card(57)), evaluated_at="2027-02-10T00:00:00Z")
        self.assertEqual(back.review_expires_at, "2027-04-20T00:00:00Z")
        self.assertEqual(self.stays(), [("cid-001", self.LATER, "2027-04-20T00:00:00Z", None)])

    def test_a_candidate_that_never_held_needs_no_clock_but_a_held_one_does(self):
        self.store.add_candidates(lambda existing: [cand(1), hold_cand(2)], now=NOW)
        self.store.set_work_status("cid-001", "REJECTED")
        self.assertEqual(self.store.set_work_status("cid-001", "REVIEW").work_status, "REVIEW", "보류함에 든 적이 없으면 시각이 필요 없다")
        self.store.set_work_status("cid-002", "REJECTED")
        before = digest(self.path)
        self.assertEqual(code_of(self.store.set_work_status, "cid-002", "REVIEW"), "UNEXPECTED_ERROR")
        self.assertEqual(code_of(self.store.set_work_status, "cid-002", "REVIEW", now="어제"), "CANDIDATE_INVALID")
        self.assertEqual(digest(self.path), before, "실패하면 아무것도 바뀌지 않는다")
        self.assertEqual(self.store.load_candidate("cid-002").work_status, "REJECTED")


class BoundaryTest(StoreCase):
    def targets(self, now):
        return [item.candidate_id for item in self.store.hold_cleanup_targets(now)]

    def test_eighty_nine_days_no_ninety_days_yes_ninety_one_days_yes(self):
        self.store.add_candidates(lambda existing: [hold_cand(1)], now=NOW)
        for now, expected in (("2027-02-06T00:00:00Z", []), ("2027-02-07T23:59:59Z", []), ("2027-02-08T00:00:00Z", ["cid-001"]), ("2027-02-09T00:00:00Z", ["cid-001"])):
            with self.subTest(now=now):
                self.assertEqual(self.targets(now), expected, f"기한 {DAY90}")

    def test_the_leap_day_counts_as_a_day(self):
        created = "2027-12-01T00:00:00Z"
        self.store.add_candidates(lambda existing: [cand(1, final=60, expires="2028-02-29T00:00:00Z", created_at=created)], now=NOW)
        self.assertEqual(self.stays(), [("cid-001", created, "2028-02-29T00:00:00Z", None)])
        self.assertEqual(self.targets("2028-02-28T23:59:59Z"), [])
        self.assertEqual(self.targets("2028-02-29T00:00:00Z"), ["cid-001"])

    def test_the_expiry_is_exactly_ninety_days_after_the_first_time(self):
        self.assertEqual(hold.review_expires_at("2026-11-10T00:00:00Z"), DAY90)
        self.assertEqual(hold.review_expires_at("2027-12-01T00:00:00Z"), "2028-02-29T00:00:00Z")
        self.assertEqual(hold.review_expires_at("2028-01-01T00:00:00Z"), "2028-03-31T00:00:00Z")

    def test_only_untouched_unlinked_candidates_still_on_hold_are_eligible(self):
        self.store.add_candidates(lambda existing: [hold_cand(number) for number in range(1, 8)] + [cand(8, final=70)], now=NOW)
        self.store.set_work_status("cid-002", "REVIEW")                                           # 사람이 검토 중으로
        self.store.set_work_status("cid-003", "SELECTED")
        self.store.set_work_status("cid-004", "HOLD")                                             # 사람이 보류
        self.store.set_work_status("cid-005", "REJECTED")
        self.store.save_link(CandidateLink(engine_candidate_id="cid-006", channel="naver_a", seed_id="seed-6", source_topic_id="src-6", legacy_candidate_id="legacy-1", draft_plan_id=None), now=NOW)
        self.store.re_evaluate(dataclasses.replace(hold_cand(7), scores=ts.flat_card(72), review_expires_at=None), evaluated_at="2026-12-01T00:00:00Z")      # 구간을 나갔다
        self.assertEqual(self.targets("2027-03-01T00:00:00Z"), ["cid-001"], "변화가 있는 후보는 정리하지 않는다")


class CleanupStoreTest(StoreCase):
    NOW90 = "2027-02-10T00:00:00Z"

    def prepare(self):
        self.store.add_candidates(lambda existing: [hold_cand(1), hold_cand(2), cand(3, final=70)], now=NOW)
        self.store.re_evaluate(dataclasses.replace(hold_cand(1), scores=ts.flat_card(58)), evaluated_at="2026-12-25T00:00:00Z")
        return {"cid-001": self.store.load_candidate("cid-001"), "cid-003": self.store.load_candidate("cid-003")}

    def test_the_cleanup_keeps_exactly_the_thirteen_history_fields_and_removes_the_details(self):
        kept = self.prepare()
        keys_before = slots.sameness_keys(kept["cid-001"])
        rows = self.store.cleanup_hold(now=self.NOW90, token=self.token(self.NOW90))
        self.assertEqual([(row.candidate_id, row.status) for row in rows], [("cid-001", "cleaned"), ("cid-002", "cleaned")])
        self.assertEqual([item.candidate_id for item in self.store.list_candidates()], ["cid-003"], "다른 후보는 그대로다")
        for table in ("hold_box", "score_snapshots", "provenance", "candidate_links"):
            ids = raw(self.path, f"SELECT COUNT(*) FROM {table} WHERE {'engine_candidate_id' if table in ('provenance', 'candidate_links') else 'candidate_id'} IN ('cid-001', 'cid-002')")
            self.assertEqual(ids[0][0], 0, f"{table} 의 정리한 후보 행도 함께 지워진다")
        history = self.store.hold_history()
        self.assertEqual([row.candidate_id for row in history], ["cid-001", "cid-002"])
        self.assertEqual(HOLD_HISTORY_FIELDS, FIELDS_13)
        self.assertEqual(hold.HISTORY_FIELDS, FIELDS_13)
        self.assertTrue(set(OPERATOR_MINIMUM) <= set(HOLD_HISTORY_FIELDS), "운영자가 최소한으로 적은 8칸이 그 이름 그대로 있다")
        self.assertEqual(history[0]._fields, ("candidate_id", *FIELDS_13), "이력 13칸 + 행 열쇠")
        first = history[0]
        self.assertEqual((first.normalized_keyword, first.topic_summary, first.first_created_at, first.last_evaluated_on), ("로컬ai사양", "예시 주제 1번 모음", CREATED, "2026-12-25"), "처음 생성 시각은 후보의 만든 시각 그대로(날짜로 자르지 않는다)")
        self.assertEqual((first.cleaned_at, first.cleanup_reason), (self.NOW90, "hold_90d_unchanged"), "정리한 시각은 정리를 실행한 시각, 사유는 고정 코드 글")
        self.assertEqual((first.seed_id, first.channel, first.search_intent, first.topic_angle), ("seed-1", "naver_a", "selection_guide", "memory-requirements"))
        self.assertTrue(first.normalized_topic_hash)
        self.assertIn("보류 구간(50~64점)", first.hold_reason)
        self.assertEqual(first.exclusion_reason, "")
        self.assertFalse(any("{" in str(value) or "selection_reasons" in str(value) for value in first), "이력은 후보 상세(점수·선정 이유·출처 JSON)를 담지 않는다 — 날짜·고정 문장·해시·식별자뿐이다")
        self.assertIn(("id", "cid-001"), self.store.hold_history_keys())
        self.assertTrue(set(keys_before) <= self.store.hold_history_keys(), "정리 전 후보가 가진 같은 후보 열쇠를 정리 뒤에도 이력이 모두 가진다")
        self.assertEqual(self.store.check(), [])
        self.assertEqual(raw(self.path, "PRAGMA foreign_key_check"), [])

    def test_a_second_cleanup_finds_nothing_and_a_cleaned_candidate_cannot_be_moved_any_more(self):
        self.prepare()
        self.store.cleanup_hold(now=self.NOW90, token=self.token(self.NOW90))
        self.assertEqual(self.store.cleanup_hold(now=self.NOW90, token=None), (), "대상이 없고 번호도 없으면 할 일이 없다")
        self.assertEqual(len(self.store.hold_history()), 2)
        self.assertEqual(code_of(self.store.set_work_status, "cid-001", "REVIEW", now=self.NOW90), "TOPIC_CANDIDATE_NOT_FOUND", "상세가 지워진 후보는 되살릴 수 없다 — 이력만 남는다(D-118)")

    def test_the_check_reports_a_history_row_whose_candidate_still_exists(self):
        self.prepare()
        with connect(self.path) as connection:
            connection.execute("INSERT INTO hold_history (candidate_id, normalized_keyword, topic_summary, first_created_at, last_evaluated_on, hold_reason, exclusion_reason, normalized_topic_hash,"
                               " seed_id, channel, search_intent, topic_angle, cleaned_at, cleanup_reason)"
                               " VALUES ('cid-003', 'k', 't', '2026-11-10T00:00:00Z', '2026-11-10', '', '', 'h', 's', 'naver_a', 'information', 'a', '2027-02-10T00:00:00Z', 'hold_90d_unchanged')")
        self.assertTrue(any("보류 이력 cid-003" in problem for problem in self.store.check()))

    def test_the_reasons_come_from_the_band_and_the_work_status(self):
        held = hold_cand(1)
        cleaned_at = "2027-02-10T03:04:05Z"
        row = hold.history_row(held, "2026-12-25T01:02:03Z", "abc", cleaned_at)
        self.assertEqual(list(row), list(FIELDS_13))
        self.assertEqual((row["last_evaluated_on"], row["normalized_topic_hash"], row["exclusion_reason"]), ("2026-12-25", "abc", ""))
        self.assertEqual((row["first_created_at"], row["cleaned_at"], row["cleanup_reason"]), (CREATED, cleaned_at, "hold_90d_unchanged"))
        rejected = hold.history_row(dataclasses.replace(held, work_status="REJECTED"), CREATED, None, cleaned_at)
        self.assertEqual((rejected["exclusion_reason"], rejected["normalized_topic_hash"]), ("사람이 제외했습니다", ""))
        excluded = hold.history_row(cand(5, final=30), CREATED, "h", cleaned_at)
        self.assertIn("제외 구간", excluded["exclusion_reason"])
        self.assertEqual(excluded["hold_reason"], "")
        no_seed = hold.history_row(dataclasses.replace(held, seed_id=None), CREATED, "h", cleaned_at)
        self.assertEqual(no_seed["seed_id"], "", "없는 값은 빈 값이다")
        with self.assertRaises(AppError):
            hold.history_row(held, CREATED, "h", "어제")                                                # 정리한 시각은 UTC 시각 글이어야 한다
        self.assertEqual(set(hold.HISTORY_FIELD_KO), set(FIELDS_13))
        self.assertTrue(all(name for name in hold.HISTORY_FIELD_KO.values()))
        self.assertEqual([table for table, _column, _what in hold.CLEANUP_ERASES], ["candidates", "score_snapshots", "provenance", "hold_box", "candidate_links"])


class RowResultTest(StoreCase):
    """운영자 결정(D-120): 정리 결과를 행 단위로 — 정리함·건너뜀·충돌·실패. 한 후보의 충돌·실패가 나머지 정리를 막지 않는다. 원자성은 '행 안'에서 지킨다(한 행의 이력 삽입과 후보 삭제는 함께 되거나 함께 안 된다)."""
    NOW90 = "2027-02-10T00:00:00Z"

    def three(self):
        self.store.add_candidates(lambda existing: [hold_cand(1), hold_cand(2), hold_cand(3)], now=NOW)

    @staticmethod
    def statuses(rows):
        return [(row.candidate_id, row.status) for row in rows]

    def rows_of(self, candidate_id):
        """그 번호의 후보가 가진 모든 표의 행(앞뒤 비교용)."""
        return [raw(self.path, f"SELECT * FROM {table} WHERE {column} = ?", (candidate_id,)) for table, column in
                (("candidates", "candidate_id"), ("hold_box", "candidate_id"), ("score_snapshots", "candidate_id"), ("hold_history", "candidate_id"))]

    def test_a_number_already_in_the_history_is_a_conflict_row_and_the_others_are_still_cleaned(self):
        self.three()
        with connect(self.path) as connection:                                                    # 같은 번호의 이력이 이미 있다(옛 데이터·손질 — 저장소 API 는 이런 상태를 만들지 않는다)
            connection.execute("INSERT INTO hold_history (candidate_id, normalized_keyword, topic_summary, first_created_at, last_evaluated_on, hold_reason, exclusion_reason, normalized_topic_hash,"
                               " seed_id, channel, search_intent, topic_angle, cleaned_at, cleanup_reason)"
                               " VALUES ('cid-002', 'k', 't', '2026-11-10T00:00:00Z', '2026-11-10', '', '', 'h', 's', 'naver_a', 'information', 'a', '2027-01-01T00:00:00Z', 'hold_90d_unchanged')")
        old_history = {row.candidate_id: row for row in self.store.hold_history()}
        rows = self.store.cleanup_hold(now=self.NOW90, token=self.token(self.NOW90))
        self.assertEqual(self.statuses(rows), [("cid-001", "cleaned"), ("cid-002", "conflict"), ("cid-003", "cleaned")], "충돌 하나가 나머지 정리를 막지 않는다")
        self.assertIn("같은 번호의 정리 이력이 이미 있어", rows[1].detail)
        self.assertEqual([item.candidate_id for item in self.store.list_candidates()], ["cid-002"], "충돌한 후보는 그대로 남는다")
        now_history = {row.candidate_id: row for row in self.store.hold_history()}
        self.assertEqual(now_history["cid-002"], old_history["cid-002"], "충돌한 번호의 이력은 건드리지 않는다")
        self.assertEqual(sorted(now_history), ["cid-001", "cid-002", "cid-003"])

    def test_an_unexpected_failure_in_one_row_puts_back_only_that_row_and_never_repeats_the_error_text(self):
        self.three()
        before = self.rows_of("cid-002")
        real = hold.history_row

        def broken(candidate, last, topic_hash, cleaned_at):
            if candidate.candidate_id == "cid-002":
                raise RuntimeError("비밀 주제 글이 든 오류 문구")
            return real(candidate, last, topic_hash, cleaned_at)

        with mock.patch.object(hold, "history_row", broken):
            rows = self.store.cleanup_hold(now=self.NOW90, token=self.token(self.NOW90))
        self.assertEqual(self.statuses(rows), [("cid-001", "cleaned"), ("cid-002", "failed"), ("cid-003", "cleaned")])
        self.assertNotIn("비밀", rows[1].detail, "오류 글(후보 글이 들어 있을 수 있다)은 되풀이하지 않는다")
        self.assertEqual(self.rows_of("cid-002"), before, "실패한 행은 후보·보류함·점수 기록이 그대로이고 이력도 없다")
        self.assertEqual(self.store.check(), [])
        self.assertEqual([row.candidate_id for row in self.store.hold_history()], ["cid-001", "cid-003"])

    def test_inside_one_row_the_history_insert_and_the_candidate_removal_stand_or_fall_together(self):
        self.three()
        with connect(self.path) as connection:                                                    # cid-002 의 후보를 지우려 하면 실패하게 한다 — 이력을 이미 넣은 뒤다
            connection.execute("CREATE TRIGGER block_one BEFORE DELETE ON candidates WHEN old.candidate_id = 'cid-002' BEGIN SELECT RAISE(ABORT, 'x'); END")
        rows = self.store.cleanup_hold(now=self.NOW90, token=self.token(self.NOW90))
        self.assertEqual(self.statuses(rows), [("cid-001", "cleaned"), ("cid-002", "failed"), ("cid-003", "cleaned")])
        self.assertEqual(raw(self.path, "SELECT COUNT(*) FROM hold_history WHERE candidate_id = 'cid-002'")[0][0], 0, "후보 삭제가 안 됐으니 같은 행의 이력 삽입도 되돌려졌다")
        self.assertEqual([item.candidate_id for item in self.store.list_candidates()], ["cid-002"])

    def test_a_target_that_is_not_eligible_any_more_inside_the_lock_is_a_skipped_row(self):
        self.three()
        self.store.add_candidates(lambda existing: [hold_cand(4)], now=NOW)
        self.store.set_work_status("cid-004", "REVIEW")                                           # 사람이 손댄 후보 — 정리 대상이 아니다
        real = TopicStore._targets

        def with_stale(this, run, now):
            return (*real(this, run, now), HoldCleanup("cid-004", "naver_a", "손댄 후보", DAY90), HoldCleanup("cid-777", "naver_a", "없는 후보", DAY90))

        with mock.patch.object(TopicStore, "_targets", with_stale):
            rows = self.store.cleanup_hold(now=self.NOW90, token=self.token(self.NOW90))
        self.assertEqual(self.statuses(rows), [("cid-001", "cleaned"), ("cid-002", "cleaned"), ("cid-003", "cleaned"), ("cid-004", "skipped"), ("cid-777", "skipped")])
        self.assertEqual(self.store.load_candidate("cid-004").work_status, "REVIEW", "건너뛴 후보는 그대로다")
        self.assertIn("이미 정리 대상이 아니라", rows[3].detail)

    def test_a_big_failure_outside_the_row_handling_still_rolls_back_the_whole_cleanup(self):
        self.three()
        before = digest(self.path)
        real = hold.history_row
        calls = []

        def broken(candidate, last, topic_hash, cleaned_at):
            calls.append(candidate.candidate_id)
            if len(calls) == 2:
                raise Abort()
            return real(candidate, last, topic_hash, cleaned_at)

        with mock.patch.object(hold, "history_row", broken):
            with self.assertRaises(Abort):
                self.store.cleanup_hold(now=self.NOW90, token=self.token(self.NOW90))
        self.assertEqual(calls, ["cid-001", "cid-002"])
        self.assertEqual(digest(self.path), before, "행 처리 밖으로 번지는 큰 실패는 바깥 트랜잭션이 전부 되돌린다(첫 행도 정리되지 않는다)")
        self.assertEqual((self.store.hold_history(), self.store.count()), ([], 3))


class OrderTest(StoreCase):
    """독립 검증 1라운드 A-L1 ①②: 정리 대상 목록과 이력 목록의 순서가 시험으로 못박혀 있지 않았다(순서 구절을 지워도 시험이 통과했다). 저장한 순서·번호 순서·기한 순서가 서로 다르게 만들어 본다."""
    EARLY, MIDDLE, LATE = "2027-02-08T00:00:00Z", "2027-02-12T00:00:00Z", "2027-02-20T00:00:00Z"
    CLEAN_AT = "2027-03-01T00:00:00Z"

    def save_in_a_mixed_order(self):
        saved = [cand(5, final=60, expires=self.MIDDLE), cand(4, final=60, expires=self.MIDDLE), cand(1, final=60, expires=self.LATE), cand(2, final=60, expires=self.EARLY)]
        self.store.add_candidates(lambda existing: saved, now=NOW)

    def test_the_targets_come_earliest_expiry_first_and_the_same_expiry_in_number_order_not_in_saving_order(self):
        self.save_in_a_mixed_order()
        found = [(item.candidate_id, item.expires_at) for item in self.store.hold_cleanup_targets(self.CLEAN_AT)]
        self.assertEqual(found, [("cid-002", self.EARLY), ("cid-004", self.MIDDLE), ("cid-005", self.MIDDLE), ("cid-001", self.LATE)], "기한이 이른 순, 같은 기한이면 번호 순(저장한 순서는 5·4·1·2)")
        self.assertEqual(cleaned(self.store.cleanup_hold(now=self.CLEAN_AT, token=self.token(self.CLEAN_AT))), ("cid-002", "cid-004", "cid-005", "cid-001"), "실제 정리도 같은 순서로 한다")

    def test_the_history_list_comes_back_in_number_order_not_in_the_order_it_was_cleaned(self):
        self.save_in_a_mixed_order()
        self.store.cleanup_hold(now=self.CLEAN_AT, token=self.token(self.CLEAN_AT))
        self.assertEqual(raw(self.path, "SELECT candidate_id FROM hold_history ORDER BY rowid"), [("cid-002",), ("cid-004",), ("cid-005",), ("cid-001",)], "정리한 순서(이 시험의 전제)")
        self.assertEqual([row.candidate_id for row in self.store.hold_history()], ["cid-001", "cid-002", "cid-004", "cid-005"])


class NumberReuseTest(StoreCase):
    """운영자 결정(D-120): 후보 번호는 정리 뒤에도 영구히 다시 쓰지 않는다 — 정리 이력(과 재생성 관계)에 있는 번호를 `candidates` 에 다시 넣으려는 저장은 거절한다. 전에는 같은 번호가 다시 들어오면 그 뒤 모든 정리가
    `UNIQUE` 오류로 영구히 막혔다(독립 검증 1라운드 A-M2)."""
    FIRST, BACK_AT = "2027-02-10T00:00:00Z", "2027-03-01T00:00:00Z"

    def cleaned_store(self):
        self.store.add_candidates(lambda existing: [hold_cand(1), hold_cand(2), cand(3, final=70)], now=NOW)
        self.assertEqual(cleaned(self.store.cleanup_hold(now=self.FIRST, token=self.token(self.FIRST))), ("cid-001", "cid-002"))

    def test_saving_a_cleaned_number_again_is_refused_and_nothing_else_in_that_call_is_saved(self):
        self.cleaned_store()
        before = digest(self.path)
        for number in (1, 2):
            with self.subTest(number=number):
                with self.assertRaises(AppError) as caught:
                    self.store.add_candidates(lambda existing, n=number: [cand(7), hold_cand(n)], now=self.BACK_AT)             # 정리한 번호가 다시 들어온다
                self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")
                self.assertIn("영구히 다시 쓰지 않습니다", str(caught.exception.slots) + str(caught.exception.detail))
        self.assertEqual(digest(self.path), before, "한 번호라도 거절되면 하나도 저장되지 않는다")
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.add_candidates(lambda existing: [cand(7)], now=self.BACK_AT)[0].candidate_id, "cid-007", "다른 새 번호는 그대로 저장된다")

    def test_the_numbers_that_cannot_be_used_are_the_union_of_candidates_history_and_lineage(self):
        self.cleaned_store()
        self.assertEqual(self.store.used_candidate_ids(), frozenset({"cid-001", "cid-002", "cid-003"}))
        self.assertIsInstance(self.store.used_candidate_ids(), frozenset)
        new_id = hold.next_recreated_id("cid-001", 1, self.store.used_candidate_ids())
        self.store.recreate_candidate("cid-001", dataclasses.replace(hold_cand(1), candidate_id=new_id), now=self.BACK_AT)
        self.assertEqual(self.store.used_candidate_ids(), frozenset({"cid-001", "cid-002", "cid-003", new_id}))

    def test_a_stale_plan_that_proposes_a_cleaned_number_cannot_bring_back_the_old_permanent_failure(self):
        """동시 실행·낡은 읽기로 정리한 번호가 다시 만들어지는 길(A-M2 의 서비스 경로)이 저장 때 막힌다 — 그래서 정리가 `UNIQUE` 오류로 영구히 막히는 일이 없다."""
        self.cleaned_store()
        stale = [hold_cand(1)]
        with self.assertRaises(AppError):
            self.store.add_candidates(lambda existing: stale, now=self.BACK_AT)
        self.assertEqual(self.store.check(), [])
        self.assertEqual(self.store.cleanup_hold(now=self.FIRST, token=None), (), "정리는 막히지 않는다(이번에는 대상이 없을 뿐이다)")


class RecreationHelpersTest(unittest.TestCase):
    """순수 도우미(`topics/hold.py`): 정리 이력 한 줄 → 재생성에 필요한 최소 정보, 옛 번호와 세대에서 결정적으로 만드는 새 번호."""

    def test_the_recreation_input_is_the_minimum_the_history_keeps(self):
        row = hold.history_row(hold_cand(1), "2026-12-25T00:00:00Z", "해시", "2027-02-10T00:00:00Z")
        found = hold.recreation_input(row)
        self.assertEqual(found._fields, ("seed_id", "channel", "search_intent", "topic_angle", "normalized_keyword", "normalized_topic_hash", "first_created_at"))
        self.assertEqual(found, ("seed-1", "naver_a", "selection_guide", "memory-requirements", "로컬ai사양", "해시", CREATED))
        history = type("Row", (), row)()                                                         # 이름 있는 값(`HoldHistory` 같은)도 같은 결과
        self.assertEqual(hold.recreation_input(history), found)
        with self.assertRaises(KeyError):
            hold.recreation_input({"seed_id": "x"})

    def test_the_new_number_is_deterministic_never_the_old_number_and_skips_numbers_already_used(self):
        first = hold.next_recreated_id("cid-001")
        self.assertRegex(first, r"^rc-1-[0-9a-f]{16}$")
        self.assertEqual((hold.RECREATED_PREFIX, first), ("rc-", hold.next_recreated_id("cid-001", 1)), "같은 입력이면 같은 번호(시계·난수 없음)")
        self.assertNotEqual(first, hold.next_recreated_id("cid-002"))
        self.assertNotEqual(first, "cid-001")
        again = hold.next_recreated_id("cid-001", 1, used={first})
        self.assertRegex(again, r"^rc-2-[0-9a-f]{16}$")
        self.assertEqual(hold.next_recreated_id("cid-001", 1, used={first, again}).split("-")[1], "3", "이미 쓰인 번호면 세대를 올려 다음 번호")
        self.assertEqual(hold.next_recreated_id("cid-001", 2), again, "세대 2 를 바로 줘도 같은 번호")
        self.assertEqual(hold.next_recreated_id(first, 1).split("-")[1], "1", "다시 만든 번호에서 또 만들어도 새 번호이고 옛 번호와 다르다")
        self.assertNotEqual(hold.next_recreated_id(first, 1), first)
        self.assertTrue(all(len(item) <= 64 for item in (first, again)))
        for old, generation in (("", 1), ("나쁜 번호", 1), ("a" * 65, 1), (None, 1), ("cid-001", 0), ("cid-001", True), ("cid-001", "1"), ("cid-001", hold.MAX_GENERATION + 1)):
            with self.subTest(old=repr(old)[:12], generation=generation), self.assertRaises(ValueError):
                hold.next_recreated_id(old, generation)
        class Zeros:                                                                              # 어떤 입력에도 같은 해시를 내는 가짜 — 옛 번호가 우연히 새 번호와 같은 경우를 만든다
            def __init__(self, data):
                self.data = data

            def hexdigest(self):
                return "0" * 64

        same_as_new = "rc-1-" + "0" * 16
        with mock.patch.object(hold.hashlib, "sha256", Zeros):
            self.assertEqual(hold.next_recreated_id(same_as_new, 1), "rc-2-" + "0" * 16, "새 번호가 옛 번호와 같아지면 세대를 올려 다른 번호를 쓴다(옛 번호를 되살리지 않는다)")
        with self.assertRaises(ValueError):                                                      # 세대를 올리다 한도를 넘으면 거절한다
            hold.next_recreated_id("cid-001", hold.MAX_GENERATION, used={hold.next_recreated_id("cid-001", hold.MAX_GENERATION)})


class RecreationTest(StoreCase):
    """운영자 결정(D-120): 정리 이력에서 '다시 후보로 만들기'가 가능하도록 저장소 층 API 와 관계 표 — 새 후보 번호를 받아 후보를 저장하고 `candidate_lineage` 에 `RECREATED_FROM` 한 줄을 같은 트랜잭션으로 적는다.
    옛 번호는 되살리지 않는다. CLI·화면 명령은 후속(P4b·P6)이다."""
    FIRST, BACK_AT, SECOND = "2027-02-10T00:00:00Z", "2027-03-01T00:00:00Z", "2027-06-10T00:00:00Z"

    def setUp(self):
        super().setUp()
        self.store.add_candidates(lambda existing: [hold_cand(1), hold_cand(2), cand(3, final=70)], now=NOW)
        self.store.cleanup_hold(now=self.FIRST, token=self.token(self.FIRST))

    def fresh(self, old_id="cid-001", number=None, **more):
        """정리 이력과 맞는(채널·씨앗·의도·관점·주제 해시가 같은) 새 번호의 후보 — 번호만 새것이다(`number` 는 그 이력이 만들어진 예시 후보의 순서 번호)."""
        new_id = hold.next_recreated_id(old_id, 1, self.store.used_candidate_ids())
        base = cand(number or int(old_id[-3:]), final=60, expires="2027-06-01T00:00:00Z", created_at=self.BACK_AT)
        return dataclasses.replace(base, candidate_id=new_id, **more)

    def test_recreating_saves_the_new_candidate_and_one_lineage_line_and_never_revives_the_old_number(self):
        history = {row.candidate_id: row for row in self.store.hold_history()}
        new = self.fresh()
        saved = self.store.recreate_candidate("cid-001", new, now=self.BACK_AT)
        self.assertEqual(saved, new)
        self.assertEqual(self.store.load_candidate(new.candidate_id), new)
        self.assertEqual(self.store.lineage_of(new.candidate_id), Lineage(new.candidate_id, "cid-001", "RECREATED_FROM", self.BACK_AT))
        self.assertIsNone(self.store.lineage_of("cid-003"), "다시 만든 후보가 아니면 관계가 없다")
        self.assertEqual(code_of(self.store.load_candidate, "cid-001"), "TOPIC_CANDIDATE_NOT_FOUND", "옛 번호는 되살아나지 않는다")
        self.assertEqual({row.candidate_id: row for row in self.store.hold_history()}, history, "정리 이력은 그대로다")
        self.assertEqual(raw(self.path, "SELECT COUNT(*) FROM candidate_lineage")[0][0], 1)
        self.assertEqual(self.store.check(), [])
        self.assertEqual(raw(self.path, "PRAGMA foreign_key_check"), [])
        self.assertEqual(code_of(self.store.add_candidates, lambda existing: [hold_cand(1)], now=self.BACK_AT), "CANDIDATE_INVALID", "옛 번호로 저장하는 길은 여전히 막혀 있다")

    def test_it_is_one_transaction_the_candidate_is_not_saved_when_the_lineage_line_cannot_be_written(self):
        with connect(self.path) as connection:
            connection.execute("CREATE TRIGGER block_lineage BEFORE INSERT ON candidate_lineage BEGIN SELECT RAISE(ABORT, 'x'); END")
        before = digest(self.path)
        with self.assertRaises(AppError):
            self.store.recreate_candidate("cid-001", self.fresh(), now=self.BACK_AT)
        self.assertEqual(digest(self.path), before, "관계 한 줄이 안 써지면 후보도 저장되지 않는다")
        self.assertEqual(self.store.count(), 1)

    def test_it_refuses_a_wrong_history_a_taken_number_or_a_candidate_that_does_not_match_the_history_and_changes_nothing(self):
        used = self.fresh()
        self.store.recreate_candidate("cid-001", used, now=self.BACK_AT)
        before = digest(self.path)
        cases = [
            ("정리 이력에 없는 번호", "cid-999", self.fresh("cid-002"), "TOPIC_CANDIDATE_NOT_FOUND"),
            ("새 번호가 옛 번호와 같음", "cid-001", dataclasses.replace(self.fresh(), candidate_id="cid-001"), "CANDIDATE_INVALID"),
            ("새 번호가 지금 후보의 번호", "cid-001", dataclasses.replace(self.fresh(), candidate_id="cid-003"), "CANDIDATE_INVALID"),
            ("새 번호가 다른 정리 이력의 번호", "cid-001", dataclasses.replace(self.fresh(), candidate_id="cid-002"), "CANDIDATE_INVALID"),
            ("새 번호가 이미 다시 만든 번호", "cid-002", dataclasses.replace(self.fresh("cid-002"), candidate_id=used.candidate_id), "CANDIDATE_INVALID"),
            ("채널이 다름", "cid-002", self.fresh("cid-002", channel="naver_b"), "CANDIDATE_INVALID"),
            ("씨앗이 다름", "cid-002", self.fresh("cid-002", seed_id="seed-other"), "CANDIDATE_INVALID"),
            ("검색 의도가 다름", "cid-002", self.fresh("cid-002", search_intent="information"), "CANDIDATE_INVALID"),
            ("관점이 다름", "cid-002", self.fresh("cid-002", topic_angle="other-angle"), "CANDIDATE_INVALID"),
            ("주제 비교 번호가 다름", "cid-002", self.fresh("cid-002", topic="전혀 다른 주제의 후보"), "CANDIDATE_INVALID"),
            ("후보가 아닌 값", "cid-002", {"candidate_id": "x"}, "CANDIDATE_INVALID"),
        ]
        for name, old_id, candidate, code in cases:
            with self.subTest(case=name):
                self.assertEqual(code_of(self.store.recreate_candidate, old_id, candidate, now=self.BACK_AT), code)
                self.assertEqual(digest(self.path), before, "거절하면 아무것도 바뀌지 않는다")
        self.assertEqual(code_of(self.store.recreate_candidate, "cid-002", self.fresh("cid-002"), now="어제"), "CANDIDATE_INVALID")

    def test_the_lineage_survives_when_the_recreated_candidate_is_cleaned_again_and_it_can_be_recreated_once_more(self):
        first = self.fresh()
        self.store.recreate_candidate("cid-001", first, now=self.BACK_AT)
        done = cleaned(self.store.cleanup_hold(now=self.SECOND, token=self.token(self.SECOND)))
        self.assertEqual(done, (first.candidate_id,), "다시 만든 후보도 90일 뒤 같은 길로 정리된다")
        self.assertEqual(self.store.lineage_of(first.candidate_id).recreated_from, "cid-001", "후보 행이 지워져도 관계는 남는다")
        self.assertIn(first.candidate_id, self.store.used_candidate_ids())
        self.assertEqual(self.store.check(), [])
        second = self.fresh(first.candidate_id, number=1)
        self.assertNotIn(second.candidate_id, (first.candidate_id, "cid-001"))
        self.store.recreate_candidate(first.candidate_id, second, now=self.SECOND)
        self.assertEqual(self.store.lineage_of(second.candidate_id).recreated_from, first.candidate_id)
        self.assertEqual(raw(self.path, "SELECT COUNT(*) FROM candidate_lineage")[0][0], 2)
        self.assertEqual(self.store.check(), [])

    def test_a_number_that_only_the_lineage_knows_is_still_unusable(self):
        """관계 표에만 남은 번호(후보도 이력도 없는 어긋난 상태 — `check()` 가 알린다)도 쓸 수 없는 번호다 — 사라진 후보의 번호를 새 후보가 이어받지 않는다(변이 점검에서 살아남던 곳)."""
        with connect(self.path) as connection:
            connection.execute("INSERT INTO candidate_lineage (candidate_id, recreated_from, relation, created_at) VALUES ('cid-050', 'cid-001', 'RECREATED_FROM', ?)", (self.BACK_AT,))
        self.assertIn("cid-050", self.store.used_candidate_ids())
        before = digest(self.path)
        self.assertEqual(code_of(self.store.add_candidates, lambda existing: [hold_cand(50)], now=self.BACK_AT), "CANDIDATE_INVALID")
        self.assertEqual(code_of(self.store.recreate_candidate, "cid-002", dataclasses.replace(self.fresh("cid-002"), candidate_id="cid-050"), now=self.BACK_AT), "CANDIDATE_INVALID")
        self.assertEqual(digest(self.path), before)
        self.assertTrue(any("재생성 관계 cid-050" in problem for problem in self.store.check()))

    def test_the_check_reports_a_lineage_line_that_points_nowhere(self):
        new = self.fresh()
        self.store.recreate_candidate("cid-001", new, now=self.BACK_AT)
        with connect(self.path) as connection:
            connection.execute("INSERT INTO candidate_lineage (candidate_id, recreated_from, relation, created_at) VALUES ('cid-050', 'cid-404', 'RECREATED_FROM', ?)", (self.BACK_AT,))
            connection.execute("INSERT INTO candidate_lineage (candidate_id, recreated_from, relation, created_at) VALUES ('cid-002', 'cid-002', 'RECREATED_FROM', ?)", (self.BACK_AT,))
        problems = "\n".join(self.store.check())
        self.assertIn("재생성 관계 cid-050: 이어진 정리 이력 cid-404 이 없다", problems)
        self.assertIn("재생성 관계 cid-050: 같은 번호의 후보도 정리 이력도 없다", problems)
        self.assertIn("재생성 관계 cid-002: 새 번호가 옛 번호와 같다", problems)
        self.assertNotIn(f"재생성 관계 {new.candidate_id}", problems, "정상인 관계는 문제로 적지 않는다")


class StoreTokenTest(StoreCase):
    """확인 번호(D-120) — 저장소는 번호가 없거나 틀리면 아무것도 바꾸지 않고 거절하고, 번호가 맞을 때만 정리한다. 서비스·명령줄의 확인과 별개로 저장소 자신이 지킨다."""
    NOW90 = "2027-02-10T00:00:00Z"

    def test_the_store_refuses_without_the_right_token_and_changes_nothing_then_cleans_with_it(self):
        self.store.add_candidates(lambda existing: [hold_cand(1), hold_cand(2)], now=NOW)
        right = self.token(self.NOW90)
        before = digest(self.path)
        for bad in (None, "", "0" * 12, right.upper(), right + "0", 123):
            with self.subTest(token=repr(bad)[:16]):
                with self.assertRaises(CleanupTokenMismatch) as caught:
                    self.store.cleanup_hold(now=self.NOW90, token=bad)
                self.assertEqual(caught.exception.code, "CONFIRMATION_REQUIRED", "새 오류 코드를 만들지 않고 기존 코드를 쓴다")
        self.assertEqual(digest(self.path), before, "번호가 없거나 틀리면 아무것도 바뀌지 않는다")
        self.assertEqual(cleaned(self.store.cleanup_hold(now=self.NOW90, token=right)), ("cid-001", "cid-002"))
        with self.assertRaises(CleanupTokenMismatch):
            self.store.cleanup_hold(now=self.NOW90, token=right)                    # 미리 본 대상이 이미 없다 — 같은 번호로 다시 해도 지울 것도 통할 것도 없다

    def test_the_token_is_a_twelve_hex_fingerprint_of_the_targets_and_changes_when_anything_about_them_changes(self):
        first = HoldCleanup("cid-001", "naver_a", "예시 주제", "2027-02-08T00:00:00Z")
        second = HoldCleanup("cid-002", "naver_b", "다른 예시", "2027-02-09T00:00:00Z")
        token = hold.cleanup_token([first, second])
        self.assertRegex(token, "^[0-9a-f]{12}$")
        expected = hashlib.sha256("\n".join([hold.TOKEN_VERSION, "cid-001|naver_a|2027-02-08T00:00:00Z", "cid-002|naver_b|2027-02-09T00:00:00Z"]).encode("utf-8")).hexdigest()[:12]
        self.assertEqual((hold.TOKEN_VERSION, token), ("cleanup-v1", expected), "버전 머리 + 번호·채널·기한을 번호 순으로 이은 글의 SHA-256 앞 12자리")
        self.assertEqual(hold.cleanup_token([second, first]), token, "넘기는 순서가 달라도 같다(번호 순으로 정리한다)")
        self.assertEqual(hold.cleanup_token([first._replace(topic="주제 글만 다름"), second]), token, "주제 글은 번호에 들어가지 않는다")
        for name, changed in (("대상 하나 빠짐", [first]), ("채널이 다름", [first, second._replace(channel="naver_a")]), ("기한이 다름", [first, second._replace(expires_at="2027-02-10T00:00:00Z")]),
                              ("번호가 다름", [first, second._replace(candidate_id="cid-003")]), ("대상이 늘어남", [first, second, HoldCleanup("cid-004", "naver_a", "x", "2027-02-01T00:00:00Z")])):
            with self.subTest(case=name):
                self.assertNotEqual(hold.cleanup_token(changed), token)
        self.assertIsNone(hold.cleanup_token([]), "대상이 없으면 번호도 없다")


def stored_world(tmp, count=2):
    """보류 후보 `count`개가 든 보관함이 있는 데이터 폴더."""
    world = World(tmp, with_world=False)
    world.paths.folder.mkdir(parents=True, exist_ok=True)
    with open_for_write(world.paths.database) as store:
        store.add_candidates(lambda existing: [hold_cand(number) for number in range(1, count + 1)] + [cand(9, final=70)], now=NOW)
    return world


def token_of(world, today):
    """미리 보기가 보이는 확인 번호(정리 대상이 있을 때)."""
    return tp.cleanup_hold(world.ctx, confirmed=False, today=today).token


def old_structure_world(tmp, count=2):
    """판 1(옛 구조) 보관함이 있는 데이터 폴더 — 최초 보류 90일이 지난 새 후보 `count`개와 일반 후보 하나(P3 병합 시점의 파일을 판 1 흉내 클래스로 만든다)."""
    world = World(tmp, with_world=False)
    world.paths.folder.mkdir(parents=True, exist_ok=True)
    with v1_class().open(world.paths.database) as store:
        store.add_candidates(lambda existing: [hold_cand(number) for number in range(1, count + 1)] + [cand(9, final=70)], now=NOW)
    return world


class ServiceCleanupTest(unittest.TestCase):
    TODAY = "2027-02-10"

    def test_the_preview_changes_nothing_and_shows_what_stays_and_what_goes(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            before = tree(tmp)
            result = tp.cleanup_hold(world.ctx, confirmed=False, today=self.TODAY)
            self.assertEqual((result.applied, len(result.items), result.store_state), (False, 2, "ready"))
            self.assertRegex(result.token, "^[0-9a-f]{12}$")
            self.assertEqual(tree(tmp), before, "미리 보기는 파일 하나도 바꾸거나 만들지 않는다(사본도 없다)")
            text = "\n".join(tfmt.cleanup_lines(result))
            for word in ("미리 보기", "정규화 키워드", "주제 요약", "처음 생성 시각", "마지막 평가일", "보류 사유", "제외 사유", "주제 비교 번호", "씨앗 번호", "채널", "검색 의도", "관점", "정리한 시각", "정리 사유", "지워지는 것", "--yes", "--confirm", "확인 번호", "되돌릴 수 없습니다"):
                self.assertIn(word, text)
            self.assertIn(result.token, text, "미리 보기가 확인 번호를 보여 준다")
            self.assertNotIn("normalized_keyword", text, "영문 칸 이름은 화면에 없다")

    def test_confirming_cleans_up_after_taking_a_copy_and_the_candidate_list_loses_those_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            before = tp.list_candidates(world.ctx).total
            result = tp.cleanup_hold(world.ctx, confirmed=True, token=token_of(world, self.TODAY), today=self.TODAY)
            self.assertEqual((result.applied, len(result.items), result.history_total), (True, 2, 2))
            self.assertEqual(result.copy, "topic_engine.db.before-cleanup-20270210.bak")
            copy = world.paths.database.with_name(result.copy)
            with connect(copy) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 3, "사본에는 정리 전 후보가 그대로 있다")
            self.assertEqual((before, tp.list_candidates(world.ctx).total), (3, 1))
            again = tp.cleanup_hold(world.ctx, confirmed=True, today=self.TODAY)
            self.assertEqual((again.applied, again.items, again.copy), (False, (), None), "정리할 후보가 없으면 사본도 만들지 않는다")
            self.assertEqual(sorted(name for name in os.listdir(world.paths.folder) if ".bak" in name), ["topic_engine.db.before-cleanup-20270210.bak"])
            self.assertIn("정리했습니다", "\n".join(tfmt.cleanup_lines(result)))

    def test_an_existing_copy_with_the_same_name_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            taken = world.paths.folder / "topic_engine.db.before-cleanup-20270210.bak"
            taken.write_bytes(b"not a database")
            result = tp.cleanup_hold(world.ctx, confirmed=True, token=token_of(world, self.TODAY), today=self.TODAY)
            self.assertEqual(result.copy, "topic_engine.db.before-cleanup-20270210-2.bak")
            self.assertEqual(taken.read_bytes(), b"not a database")

    def test_nothing_is_cleaned_before_the_ninety_days_or_without_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            early = tp.cleanup_hold(world.ctx, confirmed=True, today="2027-02-07")
            self.assertEqual((early.applied, len(early.items)), (False, 0))
            self.assertEqual(tp.list_candidates(world.ctx).total, 3)
            self.assertIn("지금 정리할 후보가 없습니다", "\n".join(tfmt.cleanup_lines(early)))
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            for confirmed in (False, True):
                result = tp.cleanup_hold(world.ctx, confirmed=confirmed, today=self.TODAY)
                self.assertEqual((result.applied, result.items, result.store_state), (False, (), "missing"))
            self.assertFalse(world.paths.database.exists(), "보관함이 없으면 만들지도 않는다")

    def test_no_other_command_cleans_even_when_the_ninety_days_have_long_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            for command in (("topics", "status"), ("topics", "check"), ("topics", "review", "--today", "2030-01-01"), ("topics", "plan", "--today", "2030-01-01"), ("topics", "list"), ("topics", "top")):
                ss.run_cli(world.ctx, *command)
            ss.run_cli(world.ctx, "topics", "generate", "--yes", "--today", "2030-01-01", "--target", "3")
            with open_read_only(world.paths.database) as store:
                self.assertEqual(store.hold_history(), [], "자동으로는 절대 정리하지 않는다")
                self.assertGreaterEqual(store.count(), 3)

    def test_a_cleaned_candidate_is_still_recognised_as_the_same_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.generate(target=4, today="2026-11-10")
            chosen = world.stored("naver_a")[0]
        keys = slots.sameness_keys(chosen)
        held = dataclasses.replace(chosen, scores=ts.flat_card(57), review_expires_at=DAY90, created_at=CREATED)
        outcome = {}
        for stage in ("before", "after"):
            with tempfile.TemporaryDirectory() as other:
                twin = World(other)
                twin.paths.folder.mkdir(parents=True, exist_ok=True)
                with open_for_write(twin.paths.database) as store:
                    store.add_candidates(lambda existing: [held], now=NOW)
                if stage == "after":
                    tp.cleanup_hold(twin.ctx, confirmed=True, token=token_of(twin, "2027-02-10"), today="2027-02-10")
                    with open_read_only(twin.paths.database) as store:
                        self.assertTrue(set(keys) <= store.hold_history_keys())
                        self.assertEqual(store.count(), 0)
                plan = twin.plan(channel=chosen.channel, target=4, today="2027-02-10")
                channel_plan = next(item for item in plan.plans if item.channel == chosen.channel)
                outcome[stage] = [item.candidate_id for item in channel_plan.candidates]
                self.assertNotIn(chosen.candidate_id, outcome[stage], f"{stage}: 같은 후보를 다시 만들지 않는다")
                if stage == "after":
                    self.assertGreaterEqual(channel_plan.duplicates, 1, "정리한 뒤에는 이력 열쇠로 같은 후보를 알아보고 뺐다")


class RowResultServiceTest(unittest.TestCase):
    """행 단위 결과가 서비스 결과·화면 글·`--json` 에 개수와 정리하지 않은 후보의 사유로 나온다(D-120) — 충돌 하나가 나머지 정리를 막지 않는다."""
    TODAY = "2027-02-10"

    @staticmethod
    def make_conflict(world):
        with connect(world.paths.database) as connection:                                        # cid-002 의 이력이 이미 있다(옛 데이터·손질)
            connection.execute("INSERT INTO hold_history (candidate_id, normalized_keyword, topic_summary, first_created_at, last_evaluated_on, hold_reason, exclusion_reason, normalized_topic_hash,"
                               " seed_id, channel, search_intent, topic_angle, cleaned_at, cleanup_reason)"
                               " VALUES ('cid-002', 'k', 't', '2026-11-10T00:00:00Z', '2026-11-10', '', '', 'h', 's', 'naver_a', 'information', 'a', '2027-01-01T00:00:00Z', 'hold_90d_unchanged')")

    def test_a_conflict_row_is_shown_with_its_reason_and_the_other_candidates_are_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp, count=3)
            self.make_conflict(world)
            result = tp.cleanup_hold(world.ctx, confirmed=True, token=token_of(world, self.TODAY), today=self.TODAY)
            self.assertEqual((result.applied, len(result.items), result.counts), (True, 2, {"cleaned": 2, "skipped": 0, "conflict": 1, "failed": 0}))
            text = "\n".join(tfmt.cleanup_lines(result))
            for word in ("정리했습니다", "정리하지 않은 후보 1개", "건너뜀 0", "충돌 1", "실패 0", "같은 번호의 정리 이력이 이미 있어"):
                self.assertIn(word, text)
            data = result.to_dict()
            self.assertEqual(data["results"], {"cleaned": 2, "skipped": 0, "conflict": 1, "failed": 0})
            self.assertEqual([(item["status"], item["ref"]) for item in data["not_cleaned"]], [("conflict", tp.short_ref("cid-002"))])
            self.assertEqual(tp.list_candidates(world.ctx).total, 2, "충돌한 후보와 일반 후보가 남는다")

    def test_when_every_row_is_a_conflict_nothing_is_reported_as_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp, count=1)
            with connect(world.paths.database) as connection:
                connection.execute("INSERT INTO hold_history (candidate_id, normalized_keyword, topic_summary, first_created_at, last_evaluated_on, hold_reason, exclusion_reason, normalized_topic_hash,"
                                   " seed_id, channel, search_intent, topic_angle, cleaned_at, cleanup_reason)"
                                   " VALUES ('cid-001', 'k', 't', '2026-11-10T00:00:00Z', '2026-11-10', '', '', 'h', 's', 'naver_a', 'information', 'a', '2027-01-01T00:00:00Z', 'hold_90d_unchanged')")
            result = tp.cleanup_hold(world.ctx, confirmed=True, token=token_of(world, self.TODAY), today=self.TODAY)
            self.assertEqual((result.applied, result.items, result.counts["conflict"]), (False, (), 1))
            text = "\n".join(tfmt.cleanup_lines(result))
            self.assertIn("정리된 후보가 없습니다", text)
            self.assertNotIn("정리했습니다", text)

    def test_the_command_line_json_has_the_counts_and_the_not_cleaned_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp, count=3)
            self.make_conflict(world)
            token = json.loads(ss.run_cli(world.ctx, "topics", "hold", "cleanup", "--today", self.TODAY, "--json")[1])["data"]["confirm_number"]
            code, out, err = ss.run_cli(world.ctx, "topics", "hold", "cleanup", "--today", self.TODAY, "--yes", "--confirm", token, "--json")
            data = json.loads(out)["data"]
            self.assertEqual((code, err, data["applied"], data["results"]["cleaned"], data["results"]["conflict"], [item["status"] for item in data["not_cleaned"]]), (0, "", True, 2, 1, ["conflict"]))


class TokenFlowTest(unittest.TestCase):
    """확인 번호(D-120, 운영자 결정): 미리 보기가 번호를 보이고 `--yes` 는 같은 번호를 받아야 정리한다 — 번호가 없거나 틀리거나 미리 본 뒤 대상이 바뀌면 아무것도 지우지 않는다(사본도 만들지 않는다)."""
    TODAY = "2027-02-10"

    @staticmethod
    def count(world, table):
        return raw(world.paths.database, f"SELECT COUNT(*) FROM {table}")[0][0]

    def test_a_confirmed_run_without_the_token_or_with_a_wrong_one_cleans_nothing_and_says_so_without_revealing_the_right_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            shown = token_of(world, self.TODAY)
            for typed, why in ((None, "token_missing"), ("", "token_missing"), ("   ", "token_missing"), (123, "token_missing"), ("0" * 12, "token_mismatch"), (shown + "0", "token_mismatch")):
                with self.subTest(token=repr(typed)):
                    result = tp.cleanup_hold(world.ctx, confirmed=True, token=typed, today=self.TODAY)
                    self.assertEqual((result.applied, result.items, result.refused, result.copy, result.token), (False, (), why, None, None))
                    text = "\n".join(tfmt.cleanup_lines(result))
                    self.assertIn("아무것도 정리하지 않았습니다", text)
                    self.assertNotIn(shown, text, "맞는 번호를 되풀이하지 않는다 — 다시 미리 보기를 해야 본다")
                    self.assertEqual(result.to_dict()["refused"], why)
            self.assertEqual((self.count(world, "candidates"), self.count(world, "hold_history")), (3, 0))
            self.assertEqual([name for name in os.listdir(world.paths.folder) if "before-cleanup" in name], [], "거절했으니 정리 직전 사본도 만들지 않는다")
            done = tp.cleanup_hold(world.ctx, confirmed=True, token="  " + shown.upper() + " ", today=self.TODAY)
            self.assertEqual((done.applied, len(done.items), done.refused), (True, 2, None), "앞뒤 공백과 대문자는 받는다")

    def test_the_token_goes_stale_when_the_targets_change_after_the_preview_and_nothing_is_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            shown = token_of(world, self.TODAY)
            with open_for_write(world.paths.database) as store:                                     # 미리 본 뒤에 정리 대상이 하나 늘었다
                store.add_candidates(lambda existing: [hold_cand(3)], now=NOW)
            stale = tp.cleanup_hold(world.ctx, confirmed=True, token=shown, today=self.TODAY)
            self.assertEqual((stale.applied, stale.refused, stale.items), (False, "token_mismatch", ()))
            self.assertEqual((self.count(world, "candidates"), self.count(world, "hold_history")), (4, 0))
            self.assertIn("다시 미리 보기", "\n".join(tfmt.cleanup_lines(stale)))
            fresh = tp.cleanup_hold(world.ctx, confirmed=False, today=self.TODAY)
            self.assertEqual(len(fresh.items), 3)
            self.assertNotEqual(fresh.token, shown, "대상이 바뀌면 번호가 달라진다")
            self.assertEqual(len(tp.cleanup_hold(world.ctx, confirmed=True, token=fresh.token, today=self.TODAY).items), 3)

    def test_a_wrong_date_changes_the_targets_so_the_token_of_the_intended_preview_no_longer_fits(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            world.paths.folder.mkdir(parents=True, exist_ok=True)
            with open_for_write(world.paths.database) as store:
                store.add_candidates(lambda existing: [hold_cand(1), cand(5, final=60, expires="2027-06-01T00:00:00Z")], now=NOW)
            intended = token_of(world, "2027-02-10")                                                # 뜻한 날짜: 대상 하나(cid-001)
            typo = tp.cleanup_hold(world.ctx, confirmed=False, today="2027-11-06")                  # 연도 오타: 대상이 둘로 넓어진다
            self.assertEqual((len(typo.items), typo.token != intended), (2, True))
            refused = tp.cleanup_hold(world.ctx, confirmed=True, token=intended, today="2027-11-06")
            self.assertEqual((refused.applied, refused.refused), (False, "token_mismatch"))
            self.assertEqual((self.count(world, "candidates"), self.count(world, "hold_history")), (2, 0), "날짜를 잘못 쳐도 미리 본 대상만 정리된다 — 넓어진 대상은 지워지지 않는다")


class OldStructureTest(unittest.TestCase):
    """독립 검증 1라운드 A-M1 + 운영자 결정(D-120): 옛 구조(판 1)의 보관함에서는 미리 보기가 '정리할 것이 없습니다(옛 구조라 아직 읽지 않았습니다)' 인데 `--yes` 는 구조를 올리자마자 미리 본 적 없는 후보를 지우던
    어긋남 — 이제 `--yes` 는 구조만 올리고 정리는 멈춘다(후보 수 그대로·이력 0줄·정리 직전 사본도 없음). 올린 뒤 다시 미리 보아 확인 번호를 받고 `--yes --confirm` 을 줘야 정리된다. 구조 올림과 정리는 한 실행에서 같이 하지 않는다."""
    TODAY = "2027-02-10"

    @staticmethod
    def count(world, table):
        return raw(world.paths.database, f"SELECT COUNT(*) FROM {table}")[0][0]

    def test_a_confirmed_run_on_a_version_1_store_only_raises_the_structure_and_the_clean_up_needs_a_new_preview_and_its_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = old_structure_world(tmp)
            preview = tp.cleanup_hold(world.ctx, confirmed=False, today=self.TODAY)
            self.assertEqual((preview.applied, preview.items, preview.store_state, preview.upgraded, preview.token), (False, (), "old_structure", False, None), "미리 보기는 옛 구조라 읽지 않았다 — 지울 것이 없다고 한다")
            self.assertEqual(raw(world.paths.database, "PRAGMA user_version")[0][0], 1, "미리 보기는 구조도 올리지 않는다")
            hint = "\n".join(tfmt.cleanup_lines(preview))
            self.assertIn("옛 구조라 아직 읽지 않았습니다", hint)
            self.assertIn("구조만 올리고 정리는 하지 않으니", hint, "미리 보기가 구조를 올리는 방법과 그 뒤 순서를 알려 준다")
            first = tp.cleanup_hold(world.ctx, confirmed=True, token="0" * 12, today=self.TODAY)               # 번호를 줘도 구조를 올리는 실행은 정리하지 않는다
            self.assertEqual((first.applied, first.items, first.copy, first.upgraded, first.history_total, first.refused), (False, (), None, True, 0, None), "구조만 올리고 정리는 하지 않는다")
            self.assertEqual(raw(world.paths.database, "PRAGMA user_version")[0][0], 2, "구조는 올렸다")
            self.assertEqual((self.count(world, "candidates"), self.count(world, "hold_box"), self.count(world, "hold_history")), (3, 2, 0), "후보 수 그대로 — 미리 본 적 없는 후보를 지우지 않았다")
            names = sorted(os.listdir(world.paths.folder))
            self.assertIn("topic_engine.db.v1.bak", names, "올리기 전 사본은 남는다")
            self.assertEqual([name for name in names if "before-cleanup" in name], [], "정리하지 않았으니 정리 직전 사본도 만들지 않는다")
            text = "\n".join(tfmt.cleanup_lines(first))
            for word in ("정리하지 않았습니다", "옛 구조", "구조를 올렸습니다", "다시 미리 보기", "--yes", "--confirm"):
                self.assertIn(word, text)
            self.assertNotIn("정리했습니다", text)
            self.assertTrue(first.to_dict()["upgraded"] is True and first.to_dict()["applied"] is False and first.to_dict()["candidates"] == [])
            shown = tp.cleanup_hold(world.ctx, confirmed=False, today=self.TODAY)
            self.assertEqual((shown.store_state, len(shown.items), shown.upgraded), ("ready", 2, False), "올린 뒤의 미리 보기는 대상과 확인 번호를 보여 준다")
            self.assertRegex(shown.token, "^[0-9a-f]{12}$")
            for typed, why in ((None, "token_missing"), ("0" * 12, "token_mismatch")):
                refused = tp.cleanup_hold(world.ctx, confirmed=True, token=typed, today=self.TODAY)
                self.assertEqual((refused.applied, refused.refused), (False, why))
            self.assertEqual((self.count(world, "candidates"), self.count(world, "hold_history")), (3, 0), "번호가 없거나 틀리면 지우지 않는다")
            second = tp.cleanup_hold(world.ctx, confirmed=True, token=shown.token, today=self.TODAY)
            self.assertEqual((second.applied, len(second.items), second.upgraded, second.history_total), (True, 2, False, 2), "다시 미리 보고 그 번호로 --yes 를 줘야 정리된다")
            self.assertEqual((self.count(world, "candidates"), self.count(world, "hold_history")), (1, 2))

    def test_a_run_whose_open_raises_the_structure_never_cleans_even_if_the_earlier_look_did_not_say_old(self):
        """열기 전 상태를 잘못 읽었더라도(다른 창이 막 올렸거나 읽기 전용으로는 못 읽은 경우 등) 이 실행의 열기가 구조를 올렸다면 같은 실행에서 정리하지 않는다 — 올림 여부를 열기 결과(`migrated_from`)로도 확인한다."""
        wrong_looks = {"현재 구조라고 잘못 읽음": mock.patch.object(tp, "_read_store", return_value=(None, tp.STORE_READY)),
                       "읽기 전용으로 못 읽음": mock.patch.object(tp, "_read_store", side_effect=AppError("TOPIC_STORE_RECOVERY_PENDING", {"파일": "예시"}))}
        for name, looked in wrong_looks.items():
            with self.subTest(look=name), tempfile.TemporaryDirectory() as tmp:
                world = old_structure_world(tmp)
                with looked:
                    result = tp.cleanup_hold(world.ctx, confirmed=True, token="0" * 12, today=self.TODAY)
                self.assertEqual((result.applied, result.items, result.upgraded), (False, (), True))
                self.assertEqual((self.count(world, "candidates"), self.count(world, "hold_history"), raw(world.paths.database, "PRAGMA user_version")[0][0]), (3, 0, 2))

    def test_a_run_that_saw_the_old_structure_before_opening_never_cleans_even_if_another_window_raised_it_meanwhile(self):
        """미리 보기가 '옛 구조라 읽지 않았다' 고 한 상태에서 `--yes` 를 줬는데 그 사이 다른 창이 구조를 올렸다 — 이 실행의 열기는 올리지 않았지만(`migrated_from` 은 None) 열기 전에 옛 구조로 봤으니 정리하지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            shown = token_of(world, self.TODAY)
            with mock.patch.object(tp, "_read_store", return_value=(None, tp.STORE_OLD)):
                result = tp.cleanup_hold(world.ctx, confirmed=True, token=shown, today=self.TODAY)
            self.assertEqual((result.applied, result.items, result.upgraded), (False, (), True))
            self.assertEqual((self.count(world, "candidates"), self.count(world, "hold_history")), (3, 0), "맞는 확인 번호가 있어도 이 실행에서는 지우지 않는다")

    def test_a_confirmed_run_on_a_store_already_at_the_current_version_cleans_with_the_token_in_one_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            done = tp.cleanup_hold(world.ctx, confirmed=True, token=token_of(world, self.TODAY), today=self.TODAY)
            self.assertEqual((done.applied, len(done.items), done.upgraded), (True, 2, False), "이미 현재 구조면 미리 보기를 거친 번호로 한 번에 정리한다")


class CommandLineTest(unittest.TestCase):
    TODAY = "2027-02-10"

    def clean(self, world, *extra):
        return ss.run_cli(world.ctx, "topics", "hold", "cleanup", "--today", self.TODAY, *extra)

    def test_the_preview_shows_the_token_and_yes_alone_or_a_wrong_token_clean_nothing_while_yes_with_the_token_cleans(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            code, text, err = self.clean(world)
            self.assertEqual((code, err), (0, ""))
            code, out, _err = self.clean(world, "--json")
            token = json.loads(out)["data"]["confirm_number"]
            self.assertRegex(token, "^[0-9a-f]{12}$")
            self.assertIn(f"확인 번호: {token}", text)
            self.assertIn(f"--yes --confirm {token}", text)
            for extra, words in ((["--yes"], ("확인 번호가 없어", "아무것도 정리하지 않았습니다")), (["--yes", "--confirm", "0" * 12], ("맞지 않아", "다시 미리 보기"))):
                code, out, err = self.clean(world, *extra)
                self.assertEqual((code, err), (0, ""))
                for word in words:
                    self.assertIn(word, out)
                self.assertNotIn(token, out, "맞는 번호를 되풀이하지 않는다")
                self.assertEqual(tp.list_candidates(world.ctx).total, 3, "아무것도 지워지지 않았다")
            self.assertEqual(self.clean(world, "--confirm", token)[0], 2, "--confirm 은 --yes 없이 쓰면 사용법 오류")
            for bad in ("나쁜값", "12345", "g" * 12, "0" * 13):
                self.assertEqual(self.clean(world, "--yes", "--confirm", bad)[0], 2, bad)
            code, out, err = self.clean(world, "--yes", "--confirm", token)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("정리했습니다", out)
            self.assertEqual(tp.list_candidates(world.ctx).total, 1)

    def test_a_confirmed_run_on_a_version_1_store_stops_after_raising_the_structure_with_exit_code_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = old_structure_world(tmp)
            code, out, err = self.clean(world)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("옛 구조라 아직 읽지 않았습니다", out)
            code, out, err = self.clean(world, "--yes")
            self.assertEqual((code, err), (0, ""))
            for word in ("정리하지 않았습니다", "구조를 올렸습니다", "다시 미리 보기", "--yes"):
                self.assertIn(word, out)
            self.assertNotIn("정리했습니다", out)
            self.assertEqual(tp.list_candidates(world.ctx).total, 3, "후보는 하나도 지워지지 않았다")
            code, out, err = self.clean(world)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("정리할 수 있는 후보 2개", out)
            token = json.loads(self.clean(world, "--json")[1])["data"]["confirm_number"]
            code, out, err = self.clean(world, "--yes", "--confirm", token)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("정리했습니다", out)
            self.assertEqual(tp.list_candidates(world.ctx).total, 1)
        with tempfile.TemporaryDirectory() as tmp:
            world = old_structure_world(tmp)
            code, out, err = self.clean(world, "--yes", "--json")
            data = json.loads(out)["data"]
            self.assertEqual((code, err, data["applied"], data["upgraded"], data["candidates"], data["store"], data["confirm_number"]), (0, "", False, True, [], "ready", None))
            self.assertEqual(tp.list_candidates(world.ctx).total, 3)

    def test_preview_yes_json_today_and_usage_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = stored_world(tmp)
            code, out, err = ss.run_cli(world.ctx, "topics", "hold", "cleanup", "--today", "2027-02-10")
            self.assertEqual((code, err), (0, ""))
            self.assertIn("미리 보기", out)
            self.assertEqual(tp.list_candidates(world.ctx).total, 3)
            code, out, _err = ss.run_cli(world.ctx, "topics", "hold", "cleanup", "--today", "2027-02-10", "--json")
            envelope = json.loads(out)
            self.assertEqual((code, envelope["command"], envelope["data"]["applied"], len(envelope["data"]["candidates"])), (0, "topics hold cleanup", False, 2))
            self.assertEqual(envelope["data"]["keeps"], list(FIELDS_13))
            self.assertEqual([item["table"] for item in envelope["data"]["erases"]], ["candidates", "score_snapshots", "provenance", "hold_box", "candidate_links"])
            code, out, err = ss.run_cli(world.ctx, "topics", "hold", "cleanup", "--today", "2027-02-10", "--yes", "--confirm", envelope["data"]["confirm_number"])
            self.assertEqual((code, err), (0, ""))
            self.assertIn("정리했습니다", out)
            self.assertEqual(tp.list_candidates(world.ctx).total, 1)
            self.assertEqual(ss.run_cli(world.ctx, "topics", "hold")[0], 2)
            self.assertEqual(ss.run_cli(world.ctx, "topics", "hold", "cleanup", "--y")[0], 2, "줄임 옵션은 받지 않는다")
            self.assertEqual(ss.run_cli(world.ctx, "topics", "hold", "cleanup", "--today", "내일")[0], 2)

    def test_a_typed_value_never_comes_back_in_an_error_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            secret = "AI" + "za" + "E" * 35
            for argv in (("topics", "hold", "cleanup", "--today", secret), ("topics", "hold", secret), ("topics", "hold", "cleanup", secret), ("topics", "hold", "cleanup", "--yes", "--confirm", secret)):
                code, out, err = ss.run_cli(world.ctx, *argv, "--verbose")
                self.assertEqual(code, 2)
                self.assertNotIn(secret, out + err)


class SourceRuleTest(unittest.TestCase):
    def test_the_cleanup_is_never_called_by_anything_but_the_confirmed_service_path(self):
        root = Path(__file__).resolve().parent.parent / "src" / "chanceblog_desktop"
        callers = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py") if "store.cleanup_hold(" in path.read_text(encoding="utf-8"))
        self.assertEqual(callers, ["service/topics.py"], "저장소의 상세 정리는 서비스의 확인된 길 하나에서만 부른다")
        cli_text = (root / "service" / "cli.py").read_text(encoding="utf-8")
        self.assertEqual(cli_text.count("topics.cleanup_hold("), 1, "명령줄은 서비스 함수(확인 여부를 가리는 곳)만 부른다")
        service = (root / "service" / "topics.py").read_text(encoding="utf-8")
        self.assertEqual(service.count("store.cleanup_hold("), 1)
        self.assertIn("if confirmed is not True:", service[service.index("def cleanup_hold(ctx"):service.index("# ---- 씨앗 제안 파일 불러오기")])


if __name__ == "__main__":
    unittest.main()
