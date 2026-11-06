"""점검 주기 상수 넷과 '다음 점검일'(P3b-1 S4) 시험 — 상수 값·호환 이름·다음 점검일 계산(윤년·월말·기록 없음·기록이 미래·오늘 점검)·보관함 판 2 의 점검 기록(`review_log`)과 판 1 → 2 올리기·
자동 실행이 없다는 것(점검을 안 해도 아무것도 바뀌지 않는다)·`status` 의 다음 점검일 네 개. 입력은 시험용 예시이고 시계를 읽지 않는다(날짜는 인자로 준다).
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402
from test_service_topics import World, digest as file_digest, tree  # noqa: E402
from test_topicdb_store import NOW, cand, code_of, connect, hold_cand, raw, v1_class  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import topic_format as tfmt  # noqa: E402
from chanceblog_desktop.service import topics as tp  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore, open_read_only  # noqa: E402
from chanceblog_desktop.topics import schedule as sc  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.topics import wording as wd  # noqa: E402

KINDS = ("seasonal_calendar", "long_term_seed", "hold_candidate", "seed_inactive")


class ConstantsTest(unittest.TestCase):
    def test_the_four_periods_are_separate_constants_with_the_operator_values(self):
        self.assertEqual((sc.SEASONAL_CALENDAR_REVIEW_DAYS, sc.LONG_TERM_SEED_REVIEW_DAYS, sc.HOLD_CANDIDATE_REVIEW_DAYS, sc.SEED_INACTIVE_REVIEW_DAYS), (7, 30, 30, 180))
        self.assertEqual(sc.REVIEW_KINDS, KINDS)
        self.assertEqual(dict(sc.REVIEW_DAYS), {"seasonal_calendar": 7, "long_term_seed": 30, "hold_candidate": 30, "seed_inactive": 180})
        self.assertEqual(tuple(wd.REVIEW_KIND_KO), KINDS)
        self.assertEqual(list(wd.REVIEW_KIND_KO.values()), ["계절 캘린더 점검", "장기 씨앗 재평가", "보류 후보 재평가", "씨앗 비활성 검토"])

    def test_the_old_names_still_exist_with_their_old_values(self):
        self.assertEqual(sc.EVALUATION_DAYS, 30, "호환 이름 — 옛 '월 재평가' 30일")
        self.assertIs(sc.EVALUATION_DAYS, sc.LONG_TERM_SEED_REVIEW_DAYS)
        self.assertEqual(sd.IDLE_DAYS, 180)
        self.assertIs(sd.IDLE_DAYS, sc.SEED_INACTIVE_REVIEW_DAYS, "숫자가 두 곳에 흩어지지 않는다")

    def test_the_calendar_review_uses_the_weekly_period_not_the_old_monthly_default(self):
        entry = ts.example_entry(last_evaluated_on="2026-11-01")
        self.assertTrue(sc.needs_evaluation(entry, "2026-11-08", sc.SEASONAL_CALENDAR_REVIEW_DAYS))
        self.assertFalse(sc.needs_evaluation(entry, "2026-11-07", sc.SEASONAL_CALENDAR_REVIEW_DAYS))
        self.assertFalse(sc.needs_evaluation(entry, "2026-11-08"), "함수의 기본값(호환 이름 30일)은 그대로다")


class NextReviewDateTest(unittest.TestCase):
    def test_never_reviewed_means_it_can_be_reviewed_now(self):
        found = sc.review_due("seasonal_calendar", None, "2026-11-06")
        self.assertEqual((found.state, found.last_run_on, found.next_due_on, found.days_left, found.period_days), ("never", None, None, None, 7))
        self.assertIn("지금 점검할 수 있음", sc.REVIEW_STATE_KO["never"])

    def test_the_next_date_is_the_last_date_plus_the_period_and_the_boundaries(self):
        cases = {"2026-11-06": ("scheduled", 7), "2026-11-12": ("scheduled", 1), "2026-11-13": ("due", 0), "2026-11-14": ("overdue", -1), "2026-12-31": ("overdue", -48)}
        for today, (state, left) in cases.items():
            with self.subTest(today=today):
                found = sc.review_due("seasonal_calendar", "2026-11-06", today)
                self.assertEqual((found.state, found.days_left, found.next_due_on), (state, left, "2026-11-13"))

    def test_leap_years_and_month_ends(self):
        self.assertEqual(sc.review_due("seasonal_calendar", "2028-02-26", "2028-02-26").next_due_on, "2028-03-04", "윤년 2월 29일을 지난다")
        self.assertEqual(sc.review_due("seasonal_calendar", "2027-02-26", "2027-02-26").next_due_on, "2027-03-05")
        self.assertEqual(sc.review_due("long_term_seed", "2026-01-31", "2026-01-31").next_due_on, "2026-03-02", "월말 + 30일")
        self.assertEqual(sc.review_due("long_term_seed", "2028-01-31", "2028-01-31").next_due_on, "2028-03-01")
        self.assertEqual(sc.review_due("seed_inactive", "2028-02-29", "2028-03-01").next_due_on, "2028-08-27")
        self.assertEqual(sc.review_due("hold_candidate", "2026-12-15", "2026-12-15").next_due_on, "2027-01-14", "해를 넘긴다")

    def test_a_record_dated_in_the_future_is_just_added_to_and_checked_the_same_day_is_scheduled(self):
        future = sc.review_due("hold_candidate", "2027-01-01", "2026-11-06")
        self.assertEqual((future.state, future.next_due_on, future.days_left), ("scheduled", "2027-01-31", 86))
        today = sc.review_due("hold_candidate", "2026-11-06", "2026-11-06")
        self.assertEqual((today.state, today.days_left), ("scheduled", 30), "오늘 점검했으면 다음은 주기만큼 뒤다")

    def test_the_four_come_back_in_the_fixed_order_and_a_missing_kind_is_never(self):
        found = sc.review_dues({"long_term_seed": "2026-11-01"}, "2026-11-06")
        self.assertEqual([item.kind for item in found], list(KINDS))
        self.assertEqual([item.state for item in found], ["never", "scheduled", "never", "never"])
        self.assertEqual(len(sc.review_dues({}, "2026-11-06")), 4)
        for bad in ({"weekly": "2026-11-01"}, [], "x", None):
            with self.subTest(bad=repr(bad)), self.assertRaises(ValueError):
                sc.review_dues(bad, "2026-11-06")

    def test_wrong_inputs_are_refused_and_nothing_reads_the_clock(self):
        for kind, last, today in (("weekly", None, "2026-11-06"), (5, None, "2026-11-06")):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                sc.review_due(kind, last, today)
        for last, today in (("어제", "2026-11-06"), ("2026-11-06", "내일"), ("2026-13-01", "2026-11-06"), ("1999-01-01", "2026-11-06"), (20261106, "2026-11-06"), ("2026-11-06", None)):
            with self.subTest(last=last, today=today), self.assertRaises(AppError):
                sc.review_due("seasonal_calendar", last, today)
        with self.assertRaises(AppError):
            sc.review_due("seasonal_calendar", "2201-01-01", "2026-11-06")            # 2200년을 넘는 날짜는 받지 않는다


def seed_v1_store(path, *, with_hold=True):
    """판 1 모양의 보관함 파일(P3 병합 시점)을 만든다 — 후보 둘(하나는 보류 구간)이 들어 있다."""
    with v1_class().open(path) as store:
        store.add_candidates(lambda existing: [cand(1), hold_cand(2)] if with_hold else [cand(1)], now=NOW)


class StoreVersionTwoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"

    def dump(self, path=None):
        with connect(path or self.path) as connection:
            return list(connection.iterdump())

    def test_a_version_1_file_is_upgraded_keeping_a_copy_and_every_old_row(self):
        seed_v1_store(self.path)
        before = self.dump()
        with TopicStore.open(self.path) as store:
            self.assertEqual((store.schema_version, store.needs_migration, store.check()), (2, False, []))
            self.assertEqual(store.review_log(), {})
            self.assertEqual([item.candidate_id for item in store.list_candidates()], ["cid-001", "cid-002"])
        after = self.dump()
        old_rows = [line for line in before if line.startswith("INSERT")]
        self.assertEqual([line for line in after if line.startswith("INSERT")], old_rows, "옛 행은 한 글자도 바뀌지 않았다")
        self.assertEqual(raw(self.path, "PRAGMA user_version")[0][0], 2)
        self.assertEqual({row[0] for row in raw(self.path, "SELECT name FROM sqlite_master WHERE type = 'table'")} - {"sqlite_sequence"},
                         {"candidates", "hold_box", "score_snapshots", "trend_cache", "candidate_links", "provenance", "history_ledger", "review_log", "hold_history", "candidate_lineage"})
        copy = self.path.with_name("topic_engine.db.v1.bak")
        self.assertTrue(copy.is_file(), "올리기 전 사본(.v1.bak)이 남는다")
        self.assertEqual(self.dump(copy), before, "사본은 올리기 전 파일과 똑같다")
        self.assertEqual(raw(copy, "PRAGMA user_version")[0][0], 1)

    def test_two_windows_opening_a_version_1_file_at_once_upgrade_it_once_and_both_succeed(self):
        """올림 장치 자체는 흉내 클래스 시험(`test_topicdb_store`)이 보고, 이 시험은 실제 보관함으로 판 1 → 2 를 두 곳에서 동시에 열어 사본이 하나뿐이고 둘 다 잘 열리는지 본다."""
        seed_v1_store(self.path)
        before = self.dump()
        versions, errors, barrier = [], [], threading.Barrier(2)

        def open_it():
            try:
                barrier.wait(timeout=10)
                with TopicStore.open(self.path) as store:
                    versions.append((store.schema_version, store.count()))
            except BaseException as error:                                         # 시험 스레드의 실패를 모아 본 스레드에서 알린다
                errors.append(repr(error))

        threads = [threading.Thread(target=open_it) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(versions, [(2, 2), (2, 2)])
        self.assertEqual(sorted(name for name in os.listdir(self.path.parent) if ".bak" in name), ["topic_engine.db.v1.bak"], "사본은 하나뿐이다")
        self.assertEqual(self.dump(self.path.with_name("topic_engine.db.v1.bak")), before, "사본은 올리기 전 파일과 똑같다")
        self.assertEqual(raw(self.path, "PRAGMA user_version")[0][0], 2)

    def test_a_read_only_open_of_a_version_1_file_changes_nothing_and_says_it_needs_upgrading(self):
        seed_v1_store(self.path)
        before = (file_digest(self.path), self.path.stat().st_mtime_ns, sorted(os.listdir(self.path.parent)))
        with open_read_only(self.path) as store:
            self.assertEqual((store.schema_version, store.needs_migration), (1, True))
        self.assertEqual((file_digest(self.path), self.path.stat().st_mtime_ns, sorted(os.listdir(self.path.parent))), before)

    def test_an_older_program_refuses_a_version_2_file_without_changing_a_byte(self):
        with TopicStore.open(self.path):
            pass
        before = (file_digest(self.path), sorted(os.listdir(self.path.parent)))
        for migrate in (True, False):
            with self.subTest(migrate=migrate):
                self.assertEqual(code_of(v1_class().open, self.path, migrate=migrate), "TOPIC_STORE_VERSION_UNSUPPORTED", "낡은 프로그램(판 1)은 판 2 를 거절한다")
        self.assertEqual((file_digest(self.path), sorted(os.listdir(self.path.parent))), before)

    def test_a_version_1_backup_is_upgraded_when_restored(self):
        old = Path(self.tmp.name) / "old.db"
        seed_v1_store(old)
        with TopicStore.open(self.path) as store:
            store.restore_from(old)
            self.assertEqual((store.schema_version, store.count(), store.review_log()), (2, 2, {}))

    def test_a_new_file_starts_at_version_2_with_the_new_tables_empty(self):
        with TopicStore.open(self.path) as store:
            self.assertEqual((store.schema_version, store.review_log()), (2, {}))
            self.assertEqual(raw(self.path, "SELECT COUNT(*) FROM hold_history")[0][0], 0)


class ReviewLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"

    def test_recording_writes_all_four_kinds_and_the_last_value_wins(self):
        with TopicStore.open(self.path) as store:
            store.record_reviews("2026-11-06")
            self.assertEqual(store.review_log(), {kind: "2026-11-06" for kind in KINDS})
            store.record_reviews("2026-10-01")
            self.assertEqual(set(store.review_log().values()), {"2026-10-01"}, "마지막 값이 이긴다(기록이 앞서 가도 고칠 수 있다)")

    def test_a_wrong_day_is_refused_and_a_corrupt_log_is_reported(self):
        with TopicStore.open(self.path) as store:
            for bad in ("어제", "2026-13-01", None, 20261106):
                self.assertEqual(code_of(store.record_reviews, bad), "CANDIDATE_INVALID", bad)
            self.assertEqual(store.review_log(), {})
        with connect(self.path) as connection:
            connection.execute("INSERT INTO review_log (kind, last_run_on) VALUES ('weekly', '2026-11-06')")
        with TopicStore.open(self.path) as store:
            self.assertEqual(code_of(store.review_log), "TOPIC_STORE_CORRUPT")

    def test_the_review_date_is_saved_in_the_same_transaction_as_the_candidates(self):
        with TopicStore.open(self.path) as store:
            saved = store.add_candidates(lambda existing: [cand(1)], now=NOW, reviewed_on="2026-11-10")
            self.assertEqual((len(saved), set(store.review_log().values())), (1, {"2026-11-10"}))

            def broken(existing):
                yield cand(2)
                raise RuntimeError("일부러 낸 실패")

            with self.assertRaises(RuntimeError):
                store.add_candidates(broken, now=NOW, reviewed_on="2026-12-31")
            self.assertEqual((store.count(), set(store.review_log().values())), (1, {"2026-11-10"}), "저장이 실패하면 점검일도 바뀌지 않는다")
            store.add_candidates(lambda existing: [cand(3)], now=NOW)
            self.assertEqual(set(store.review_log().values()), {"2026-11-10"}, "점검일을 안 주면 점검 기록은 그대로다")

    def test_a_bad_review_day_stops_the_whole_save(self):
        with TopicStore.open(self.path) as store:
            self.assertEqual(code_of(store.add_candidates, lambda existing: [cand(1)], now=NOW, reviewed_on="어제"), "CANDIDATE_INVALID")
            self.assertEqual(store.count(), 0)


class StatusReviewTest(unittest.TestCase):
    def test_status_lists_exactly_the_four_next_review_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            result = tp.status(world.ctx)
            self.assertEqual([item.kind for item in result.reviews], list(KINDS))
            lines = tfmt.status_lines(result)
            reviews = [line for line in lines if any(name in line for name in wd.REVIEW_KIND_KO.values())]
            self.assertEqual(len(reviews), 4)
            self.assertTrue(all("아직 점검한 적이 없어 지금 점검할 수 있습니다" in line for line in reviews), "한 번도 점검한 적이 없다")
            code, out, err = ss.run_cli(world.ctx, "topics", "status", "--json")
            data = json.loads(out)["data"]
            self.assertEqual((code, err, len(data["next_reviews"])), (0, "", 4))
            self.assertEqual([item["kind"] for item in data["next_reviews"]], list(KINDS))
            self.assertEqual({item["state"] for item in data["next_reviews"]}, {"never"})
            self.assertEqual(set(data["next_reviews"][0]), {"kind", "name", "period_days", "last_run_on", "next_due_on", "state", "days_left"})

    def test_a_preview_never_records_but_saving_an_analysis_records_the_day_for_all_four(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.plan(channel="naver_a")
            self.assertEqual({item.state for item in tp.status(world.ctx).reviews}, {"never"}, "미리 보기는 점검일을 적지 않는다")
            world.generate(today="2026-11-02", target=4)
            found = tp.status(world.ctx).reviews
            self.assertEqual([item.last_run_on for item in found], ["2026-11-02"] * 4)
            self.assertEqual([item.next_due_on for item in found], ["2026-11-09", "2026-12-02", "2026-12-02", "2027-05-01"])
            self.assertEqual({item.state for item in found}, {"scheduled"})
            self.assertTrue(any("다음 점검일 2026-11-09(7일 뒤" in line for line in tfmt.status_lines(tp.status(world.ctx))))

    def test_an_overdue_review_is_only_shown_and_nothing_changes_by_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.generate(today="2026-10-01", target=4)
            before_files = tree(tmp)
            found = tp.status(world.ctx)                                               # 가짜 시계의 오늘은 2026-11-02
            self.assertEqual([(item.state, item.days_left) for item in found.reviews], [("overdue", -25), ("overdue", -2), ("overdue", -2), ("scheduled", 148)])
            lines = [line for line in tfmt.status_lines(found) if "기한이" in line]
            self.assertEqual(len(lines), 3)
            self.assertTrue(all("표시만 하고 아무것도 바꾸지 않았습니다" in line for line in lines))
            for command in (("topics", "status"), ("topics", "check"), ("topics", "review"), ("topics", "plan"), ("topics", "list"), ("topics", "top")):
                ss.run_cli(world.ctx, *command)
            self.assertEqual(tree(tmp), before_files, "점검 기한이 지나도 읽기 명령은 아무것도 만들거나 바꾸지 않는다(자동 실행 없음)")
            with open_read_only(world.paths.database) as store:
                self.assertEqual(set(store.review_log().values()), {"2026-10-01"})

    def test_status_on_a_missing_or_old_structure_store_shows_never_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            self.assertEqual({item.state for item in tp.status(world.ctx).reviews}, {"never"})
            self.assertFalse(world.paths.database.exists())
            world.paths.folder.mkdir(parents=True, exist_ok=True)
            seed_v1_store(world.paths.database)
            before = (file_digest(world.paths.database), sorted(os.listdir(world.paths.folder)))
            found = tp.status(world.ctx)
            self.assertEqual((found.store_state, found.store_version), ("old_structure", 1))
            self.assertEqual({item.state for item in found.reviews}, {"never"})
            self.assertEqual((file_digest(world.paths.database), sorted(os.listdir(world.paths.folder))), before)

    def test_the_calendar_check_flags_entries_not_evaluated_for_a_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            from chanceblog_desktop.topics import schedule
            from test_service_topics import put
            entries = [ts.example_entry(entry_id="ex-a", name="예시 일주일 전", last_evaluated_on="2026-11-03"), ts.example_entry(entry_id="ex-b", name="예시 엿새 전", last_evaluated_on="2026-11-04"),
                       ts.example_entry(entry_id="ex-c", name="예시 평가 안 함")]
            put(world.paths.calendar, schedule.entries_to_dict(entries))
            found = tp.check_files(world.ctx, today="2026-11-10")
            flagged = " ".join(found.evaluations)
            self.assertIn("예시 일주일 전", flagged)
            self.assertIn("예시 평가 안 함", flagged)
            self.assertNotIn("예시 엿새 전", flagged, "7일(주 1회)이 안 지났으면 다시 평가할 때가 아니다")


if __name__ == "__main__":
    unittest.main()
