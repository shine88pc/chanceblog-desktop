"""받은 주제 엔진 백업을 읽을 때의 순서와 SQLite 한도 시험 — AS-S2 권고-5(결정 D-691)와 권고-8 의 M12 틈.

위협(감사 탐침 03): `topics restore` 는 되돌릴 백업의 보관함에 '내용 질의'(`TopicStore.check()` — 후보 행을 모두 읽어 풀어 본다)를 **구조 검사**(뷰·트리거·모르는 표·색인 거절)보다 먼저 돌렸다.
표 `candidates` 를 같은 열 이름의 **뷰**로 바꾼 보관함은 20만 행을 모두 만든 뒤에야(2.4초) 거절됐고, 끝없는 재귀 뷰라면 끝나지 않았을 것이다. 앱 전체에 SQLite 한도 설정(`setlimit`·`set_progress_handler`)도 0건이었다.

지키는 것:
  1) 순서 — 받은 백업(`read_backup`·`restore_backup`)은 구조 검사가 내용 질의보다 먼저다. 뷰·트리거·모르는 표·색인이 든 보관함은 내용 질의(`check`)를 **한 번도 부르지 않고** TOPIC_BACKUP_INVALID 다
     (감사 변이 M12 — 구조 검사를 건너뛰어도 시험이 통과하던 틈 — 이 이 시험으로 닫힌다). 더 새로운 판의 파일은 구조가 아니라 판 번호로 거절된다.
  2) 한도 — 받은 파일을 여는 읽기 연결에만 시간 상한(진행 처리 콜백)·길이 한도(`setlimit`, 파이썬 3.11 부터)를 건다. 지금 데이터를 점검하는 길(`make_backup`·`_live_state`)에는 걸지 않아 정상 데이터는 영향이 없다.
     질의가 끝나지 않으면 끊고 쉬운 이유(`TIME_REASON`)로 거절한다. 터무니없이 큰 파일은 메모리에 읽기 전에 크기로 거절한다.
  3) 끝없는 재귀 질의는 **이 PC 를 지키려고** 한도를 먼저 건 연결에서만, 그리고 모든 연결을 몇 초 뒤 강제로 끊는 안전망(`SafetyNet`) 아래에서만 돌린다.
네트워크·실제 시계 없이 돈다(시간 상한 시험은 가짜 시계).
"""
import ast
import contextlib
import datetime
import hashlib
import importlib
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_topicdb_backup as base  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topicdb import backup as bk  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

HAS_SETLIMIT = hasattr(sqlite3.Connection, "setlimit")             # 파이썬 3.11 부터
ENDLESS = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r"
LATER = base.NOW + datetime.timedelta(minutes=5)


def lim():
    """`topicdb/limits.py` — 모듈이 없는 옛 코드에서도 이 시험 파일이 불러와지게 늦게 가져온다(순서 시험은 모듈 없이도 빨갛게 나온다)."""
    return importlib.import_module("chanceblog_desktop.topicdb.limits")


class SafetyNet:
    """이 PC 보호 — 시험 안에서 열리는 모든 SQLite 연결을 `seconds` 뒤에 강제로 끊는다(한도가 고장 나도 끝없는 질의가 PC 를 붙잡지 않는다). `fired` 는 안전망이 실제로 끊은 횟수다 — 한도가 제대로면 0 이다."""

    def __init__(self, seconds=8.0):
        self.seconds = seconds
        self.fired = 0
        self.timers = []

    def _cut(self, connection):
        try:
            connection.interrupt()
            self.fired += 1
        except sqlite3.Error:
            pass                                                          # 이미 닫힌 연결

    def __enter__(self):
        real = sqlite3.connect

        def connect(*args, **kwargs):
            connection = real(*args, **kwargs)
            timer = threading.Timer(self.seconds, self._cut, (connection,))
            timer.daemon = True
            timer.start()
            self.timers.append(timer)
            return connection

        self.patch = mock.patch.object(sqlite3, "connect", connect)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        for timer in self.timers:
            timer.cancel()


class Ticking:
    """호출할 때마다 1 씩 늘어나는 가짜 시계 — 시간 상한 시험이 실제 시간을 기다리지 않게."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


class CheckSpy:
    """보관함의 내용 질의(`TopicStore.check`)가 몇 번 불렸는가."""

    def __enter__(self):
        self.calls = 0
        original = TopicStore.check
        spy = self

        def counting(store):
            spy.calls += 1
            return original(store)

        self.patch = mock.patch.object(TopicStore, "check", counting)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = base.World(self.tmp.name)
        self.backup = self.world.backup().path
        self.count = 0

    def variant(self, mutate, *, rewrite=True):
        """진짜 백업을 복사해 보관함에 `mutate(연결)` 를 적용한 폴더 — 조작한 사람은 목록의 크기·해시를 다시 계산하므로 해시 확인은 통과한다."""
        self.count += 1
        folder = Path(self.tmp.name) / "variants" / f"topic-20260101-{self.count:06d}"
        folder.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.backup, folder)
        with contextlib.closing(sqlite3.connect(str(folder / layout.ENGINE_DB_FILE))) as connection:
            mutate(connection)
            connection.commit()
        if rewrite:
            self.rewrite_manifest(folder)
        return folder

    @staticmethod
    def rewrite_manifest(folder):
        manifest = json.loads((folder / bk.MANIFEST_NAME).read_text(encoding="utf-8"))
        for name in manifest["files"]:
            data = (folder / name).read_bytes()
            manifest["files"][name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        (folder / bk.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    @staticmethod
    def as_view(rows_sql):
        """표 `candidates` 를 같은 열 이름의 뷰로 바꾼다(열 이름이 같아 표 모양 확인을 통과한다 — 감사 탐침 03)."""
        def mutate(connection):
            columns = [row[0] for row in connection.execute("SELECT name FROM pragma_table_info('candidates') ORDER BY cid")]
            connection.execute("DROP TABLE candidates")
            constants = ", ".join(["'c' || n"] + ["'x'"] * (len(columns) - 1))
            connection.execute(f"CREATE VIEW candidates ({', '.join(columns)}) AS {rows_sql.format(constants=constants)}")
        return mutate

    def reason_and_detail(self, call, *args, **kwargs):
        with self.assertRaises(AppError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_INVALID")
        return str((caught.exception.slots or {}).get("이유", "")), str(caught.exception.detail or "")

    def restore(self, source):
        return bk.restore_backup(source, self.world.data, self.world.backups, now=LATER)


FOREIGN = {
    "20만 행을 만드는 뷰": Base.as_view("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 200000) SELECT {constants} FROM r"),
    "끝없는 재귀 뷰(질의를 돌리면 끝나지 않는다)": Base.as_view("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT {constants} FROM r"),
    "트리거": lambda connection: connection.execute("CREATE TRIGGER sneaky AFTER INSERT ON hold_box BEGIN SELECT 1; END"),
    "모르는 표": lambda connection: connection.execute("CREATE TABLE extra_notes (x TEXT)"),
    "모르는 색인": lambda connection: connection.execute("CREATE INDEX sneaky_index ON candidates (work_status, band)"),
}


class OrderTest(Base):
    def test_a_backup_with_foreign_structure_is_refused_before_any_content_query_runs(self):
        """감사 변이 M12 와 탐침 03 — 구조(뷰·트리거·모르는 표·색인)를 내용 질의(`check`)보다 먼저 본다."""
        with SafetyNet() as net:
            for label, mutate in FOREIGN.items():
                with self.subTest(case=label):
                    folder = self.variant(mutate)
                    for call in (bk.read_backup, self.restore):
                        with CheckSpy() as spy:
                            reason, detail = self.reason_and_detail(call, folder)
                        self.assertEqual(spy.calls, 0, "내용 질의가 구조 검사보다 먼저 돌았다")
                        self.assertIn("앱이 만들지 않는 구조", reason)
                        self.assertIn("앱이 만들지 않는 구조", detail)
        self.assertEqual(net.fired, 0, "안전망이 질의를 끊었다 — 질의가 끝나지 않고 돌았다")

    def test_a_refused_restore_changes_nothing_and_makes_no_safety_backup(self):
        folder = self.variant(FOREIGN["끝없는 재귀 뷰(질의를 돌리면 끝나지 않는다)"])
        before = base.digests(self.world.data)
        with SafetyNet():
            self.reason_and_detail(self.restore, folder)
        self.assertEqual(base.digests(self.world.data), before)
        self.assertFalse((self.world.backups / bk.SAFETY_FOLDER).exists())

    def test_the_audit_probe_a_two_hundred_thousand_row_view_never_builds_its_rows(self):
        folder = self.variant(FOREIGN["20만 행을 만드는 뷰"])
        with SafetyNet(), CheckSpy() as spy:
            started = time.perf_counter()
            self.reason_and_detail(bk.read_backup, folder)
            elapsed = time.perf_counter() - started
        self.assertEqual(spy.calls, 0)
        self.assertLess(elapsed, 5.0, f"뷰의 20만 행을 만들었다면 감사 때 2.4초(여기서는 부하에 따라 더) — 지금은 만들지 않는다: {elapsed:.2f}초")

    def test_a_newer_version_backup_is_refused_by_its_version_and_not_called_a_foreign_structure(self):
        """새 판이 더한 표를 '앱이 만들지 않는 구조' 라고 잘못 말하지 않는다 — 판 번호가 먼저 거절한다(구조 검사는 새 판의 파일을 건너뛴다)."""
        def newer(connection):
            connection.execute("CREATE TABLE added_by_a_newer_version (x TEXT)")
            connection.execute(f"PRAGMA user_version = {TopicStore.SCHEMA_VERSION + 1}")
        folder = self.variant(newer)
        reason, detail = self.reason_and_detail(bk.read_backup, folder)
        self.assertNotIn("앱이 만들지 않는 구조", reason + detail)
        self.assertIn("파일 버전", detail)
        self.assertEqual(bk._structure_problem(folder / layout.ENGINE_DB_FILE), None)

    def test_a_backup_that_is_not_a_database_at_all_is_still_a_plain_refusal(self):
        folder = Path(self.tmp.name) / "variants" / "topic-20260101-000099"
        shutil.copytree(self.backup, folder)
        (folder / layout.ENGINE_DB_FILE).write_bytes(b"this is not a sqlite file " * 200)
        self.rewrite_manifest(folder)
        reason, detail = self.reason_and_detail(bk.read_backup, folder)
        self.assertTrue(reason)
        self.assertNotIn("this is not", reason + detail)                   # 조작한 파일의 글을 되풀이하지 않는다

    def test_a_normal_backup_is_still_read_and_restored(self):
        manifest, contents = bk.read_backup(self.backup)
        self.assertEqual(set(contents), set(layout.USER_DATA_FILES))
        with CheckSpy() as spy:
            result = self.restore(self.backup)
        self.assertGreaterEqual(spy.calls, 1, "정상 백업은 구조 검사 뒤에 내용 질의도 돈다(두 검사 모두 한다)")
        self.assertEqual(result.restored, layout.USER_DATA_FILES)

    def test_the_structure_check_comes_after_the_wal_header_check_and_before_the_content_check(self):
        """호출 순서 — WAL 머리표시(열면 SQLite 가 짝 파일을 만든다)가 구조 검사보다, 구조 검사가 내용 점검보다 먼저다."""
        order = []
        with mock.patch.object(bk, "wal_in_head", lambda head: order.append("wal") or False), \
                mock.patch.object(bk, "_structure_problem", lambda path: order.append("structure")), \
                mock.patch.object(bk, "_database_problem", lambda path, guard=None: order.append("content")):
            bk._verify_folder(self.backup, None, lambda name: bk._structure_problem(self.backup / name))
        self.assertEqual(order, ["wal", "structure", "content"])


class GuardTest(unittest.TestCase):
    def test_an_endless_recursive_query_is_cut_by_the_time_limit_on_a_guarded_connection(self):
        """끝없는 재귀 질의는 한도를 **먼저 건** 연결에서만 돌린다(이 PC 보호) — 가짜 시계로 몇 번째 확인에서 끊을지 정해 둔다."""
        guard = lim().Guard(10, clock=Ticking())
        with SafetyNet() as net, contextlib.closing(sqlite3.connect(":memory:")) as connection:
            guard.attach(connection)
            started = time.perf_counter()
            with self.assertRaises(sqlite3.OperationalError) as caught:
                connection.execute(ENDLESS).fetchall()
            elapsed = time.perf_counter() - started
        self.assertIn("interrupted", str(caught.exception))
        self.assertTrue(guard.tripped)
        self.assertEqual(net.fired, 0, "안전망이 먼저 끊었다 — 한도가 일하지 않았다")
        self.assertLess(elapsed, 5.0)

    def test_a_normal_query_runs_on_a_guarded_connection_and_never_trips(self):
        guard = lim().Guard(10, clock=lambda: 0.0)                           # 시계가 멈춰 있으면 아무리 긴 정상 질의도 끊기지 않는다(진짜 시계에서는 60초 안의 질의가 정상이다)
        with contextlib.closing(sqlite3.connect(":memory:")) as connection:
            guard.attach(connection)
            connection.execute("CREATE TABLE t (x INTEGER)")
            connection.executemany("INSERT INTO t VALUES (?)", [(n,) for n in range(2000)])
            self.assertEqual(connection.execute("SELECT COUNT(*), SUM(x) FROM t").fetchone(), (2000, sum(range(2000))))
        self.assertFalse(guard.tripped)

    def test_the_clock_starts_at_the_first_connection_and_is_shared_by_the_next_ones(self):
        clock = Ticking()
        guard = lim().Guard(3, clock=clock)
        self.assertEqual(clock.now, 0.0, "만들기만 해서는 시계가 시작하지 않는다")
        with contextlib.closing(sqlite3.connect(":memory:")) as first, contextlib.closing(sqlite3.connect(":memory:")) as second:
            guard.attach(first)
            started_at = clock.now
            guard.attach(second)
            self.assertEqual(clock.now, started_at, "두 번째 연결은 시계를 다시 시작하지 않는다 — 한 번의 읽기가 한 시간 상한을 나눠 쓴다")

    def test_attach_sets_the_length_limits_where_python_has_them(self):
        lm = lim()
        guard = lm.Guard(10, clock=Ticking())
        with contextlib.closing(sqlite3.connect(":memory:")) as connection:
            guard.attach(connection)
            expected = tuple(name for name, _value in lm.LIMITS if hasattr(sqlite3, name)) if HAS_SETLIMIT else ()
            self.assertEqual(guard.limits_applied, expected)
            if HAS_SETLIMIT:
                for name, value in lm.LIMITS:
                    self.assertEqual(connection.getlimit(getattr(sqlite3, name)), value, name)

    def test_attach_installs_the_progress_handler_so_even_a_short_query_is_cut_once_the_clock_has_run_out(self):
        lm = lim()
        guard = lm.Guard(-1.0, clock=Ticking())                              # 시계가 처음부터 지난 것으로 — 첫 확인에서 끊는다
        with mock.patch.object(lm, "CHECK_EVERY", 1), contextlib.closing(sqlite3.connect(":memory:")) as connection:
            guard.attach(connection)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 50) SELECT SUM(n) FROM r").fetchall()
        self.assertTrue(guard.tripped)

    def test_the_real_limit_values_are_roomy_for_the_apps_own_data_and_tight_against_attacks(self):
        lm = lim()
        with contextlib.closing(sqlite3.connect(":memory:")) as schema:
            for statement in TopicStore.SCHEMA:
                schema.execute(statement)
            widest = max(schema.execute("SELECT COUNT(*) FROM pragma_table_info(?)", (name,)).fetchone()[0] for (name,) in schema.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall())
        values = dict(lm.LIMITS)
        self.assertGreater(values["SQLITE_LIMIT_COLUMN"], widest * 2, "앱의 가장 넓은 표가 열 한도에 걸리면 안 된다")
        self.assertGreaterEqual(values["SQLITE_LIMIT_EXPR_DEPTH"], 2 * values["SQLITE_LIMIT_COLUMN"] + 3, "열 한도만큼 넓은 표를 훑는 질의(`iterdump`)의 식 깊이가 한도 안이다")
        self.assertLessEqual(values["SQLITE_LIMIT_EXPR_DEPTH"], 1000)
        self.assertGreaterEqual(values["SQLITE_LIMIT_LENGTH"], 1024 * 1024)
        self.assertLessEqual(values["SQLITE_LIMIT_LENGTH"], 64 * 1024 * 1024)
        self.assertGreaterEqual(values["SQLITE_LIMIT_SQL_LENGTH"], 100_000)
        self.assertLessEqual(values["SQLITE_LIMIT_SQL_LENGTH"], 10_000_000)
        self.assertGreaterEqual(values["SQLITE_LIMIT_COMPOUND_SELECT"], 2)
        self.assertLessEqual(values["SQLITE_LIMIT_COMPOUND_SELECT"], 32)
        self.assertEqual((values["SQLITE_LIMIT_ATTACHED"], values["SQLITE_LIMIT_TRIGGER_DEPTH"]), (0, 0))
        self.assertEqual(set(values), {"SQLITE_LIMIT_LENGTH", "SQLITE_LIMIT_SQL_LENGTH", "SQLITE_LIMIT_COLUMN", "SQLITE_LIMIT_EXPR_DEPTH", "SQLITE_LIMIT_COMPOUND_SELECT", "SQLITE_LIMIT_ATTACHED", "SQLITE_LIMIT_TRIGGER_DEPTH"})
        self.assertTrue(5 <= lm.SECONDS <= 300)
        self.assertTrue(500 <= lm.CHECK_EVERY <= 100_000)
        self.assertTrue(64 * 1024 * 1024 <= lm.MAX_DB_BYTES <= 2 * 1024 * 1024 * 1024)
        self.assertTrue(4 * 1024 <= lm.MAX_MANIFEST_BYTES <= 16 * 1024 * 1024)

    def test_the_apps_own_normal_database_passes_every_query_the_restore_path_runs_under_the_real_limits(self):
        """정상 데이터는 영향이 없다 — 앱이 만든 보관함을 진짜 한도 아래에서 점검·훑기까지 모두 돌려 본다."""
        with tempfile.TemporaryDirectory() as tmp:
            world = base.World(tmp)
            guard = lim().Guard()
            with TopicStore.open(world.data / layout.ENGINE_DB_FILE, migrate=False, guard=guard) as store:
                self.assertEqual(store.check(), [])
            with contextlib.closing(sqlite3.connect(str(world.data / layout.ENGINE_DB_FILE))) as connection:
                lim().Guard().attach(connection)
                self.assertTrue(list(connection.iterdump()))
            self.assertFalse(guard.tripped)

    def test_a_guard_cannot_be_given_to_a_writing_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                TopicStore.open(Path(tmp) / layout.ENGINE_DB_FILE, guard=lim().Guard())
            self.assertFalse((Path(tmp) / layout.ENGINE_DB_FILE).exists(), "거절은 파일을 만들기 전이다")


class ReadLimitsTest(Base):
    def attached(self):
        """보관함 연결에 한도가 붙는 횟수를 센다."""
        lm = lim()
        original = lm.Guard.attach
        calls = []

        def counting(guard, connection):
            calls.append(guard)
            return original(guard, connection)

        return mock.patch.object(lm.Guard, "attach", counting), calls

    def test_incoming_connections_get_the_limits_and_the_live_data_checks_do_not(self):
        patch, calls = self.attached()
        with patch:
            self.world.backup(now=LATER + datetime.timedelta(seconds=1))                  # 지금 데이터에서 만드는 백업 — 한도 없음
            self.assertEqual(calls, [])
            bk.read_backup(self.backup)                                                    # 받은 백업을 읽는다 — 보관함 점검 연결에 한도
            self.assertGreaterEqual(len(calls), 1)
            self.assertEqual(len({id(guard) for guard in calls}), 1, "한 번의 읽기가 한 한도(시계)를 나눠 쓴다")
            calls.clear()
            self.restore(self.backup)                                                      # 복원: 읽기 + 덮어쓰기 직전의 백업 읽기 연결
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])

    def test_a_check_that_runs_past_the_time_limit_is_cut_and_refused_with_the_time_reason(self):
        """구조가 정상인 척하는 파일(진짜 표 — 구조 검사는 통과)의 점검이 시간 상한을 넘으면 끊고 쉬운 이유로 거절한다 — 가짜 시계로 첫 확인에서 넘긴다."""
        lm = lim()
        folder = self.variant(lambda connection: None)
        real_guard = lm.Guard
        with mock.patch.object(lm, "CHECK_EVERY", 1), mock.patch.object(lm, "Guard", lambda *a, **k: real_guard(1, clock=Ticking())):
            reason, detail = self.reason_and_detail(bk.read_backup, folder)
        self.assertEqual(reason, lm.TIME_REASON)
        self.assertEqual(detail, lm.TIME_REASON)

    def test_when_the_structure_check_is_bypassed_the_limits_still_stop_an_endless_view(self):
        """두 번째 방어선 — 구조 검사가 어떤 이유로 놓쳐도(여기서는 건너뛰게 바꿔 둔다) 끝없는 재귀 뷰가 한도 안에서 거절된다. 한도를 먼저 건 상태에서만 돌리고 안전망이 몇 초 뒤 모든 연결을 끊는다."""
        lm = lim()
        folder = self.variant(FOREIGN["끝없는 재귀 뷰(질의를 돌리면 끝나지 않는다)"])
        with SafetyNet(4.0) as net, mock.patch.object(bk, "_structure_problem", lambda path: None), mock.patch.object(lm, "SECONDS", 0.3):
            started = time.perf_counter()
            reason, detail = self.reason_and_detail(bk.read_backup, folder)
            elapsed = time.perf_counter() - started
        self.assertEqual(reason, lm.TIME_REASON)
        self.assertEqual(detail, lm.TIME_REASON, "점검 질의가 끊겨 `점검 중 오류` 로 삼켜져도 개발자용 세부는 '시간 상한' 이라고 말한다")
        self.assertEqual(net.fired, 0, "안전망이 끊었다 — 한도가 일하지 않았다")
        self.assertLess(elapsed, 3.9, "한도(0.3초)가 일했다면 몇 초 안에 끝난다 — 느린 러너의 여유를 두되 안전망(4초)보다 먼저여야 한다")

    def test_restore_from_cuts_a_slow_backup_with_the_time_reason_and_changes_nothing(self):
        lm = lim()
        real_guard = lm.Guard
        before = base.digests(self.world.data)
        live_db = self.world.data / layout.ENGINE_DB_FILE
        with TopicStore.open(live_db) as store, mock.patch.object(lm, "CHECK_EVERY", 1), mock.patch.object(lm, "Guard", lambda *a, **k: real_guard(1, clock=Ticking())):
            with self.assertRaises(AppError) as caught:
                store.restore_from(self.backup / layout.ENGINE_DB_FILE)
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_INVALID")
        self.assertEqual(caught.exception.slots["이유"], lm.TIME_REASON)
        self.assertEqual(base.digests(self.world.data), before, "지금 보관함은 그대로다")

    def test_a_file_over_the_size_limit_is_refused_before_it_is_read(self):
        lm = lim()
        cases = (("보관함", (lm, "MAX_DB_BYTES", 10_000), {layout.ENGINE_DB_FILE}), ("설정 JSON", (bk, "MAX_JSON_BYTES", 100), set(layout.JSON_FILES)), ("목록 파일", (lm, "MAX_MANIFEST_BYTES", 10), {bk.MANIFEST_NAME}))
        real_bytes, real_text = Path.read_bytes, Path.read_text
        for label, patched, never_read in cases:
            with self.subTest(file=label):
                reads = []

                def recording_bytes(path, *args, **kwargs):
                    reads.append(path.name)
                    return real_bytes(path, *args, **kwargs)

                def recording_text(path, *args, **kwargs):
                    reads.append(path.name)
                    return real_text(path, *args, **kwargs)

                with mock.patch.object(*patched), mock.patch.object(Path, "read_bytes", recording_bytes), mock.patch.object(Path, "read_text", recording_text),                         mock.patch.object(bk, "_database_problem", side_effect=AssertionError("점검까지 갔다")):
                    reason, detail = self.reason_and_detail(bk.read_backup, self.backup)
                self.assertEqual(reason, lm.BIG_REASON)
                self.assertIn("너무 크다", detail)
                self.assertEqual(never_read & set(reads), set(), "크기 상한보다 먼저 파일을 읽었다")
        self.assertEqual(set(bk.read_backup(self.backup)[1]), set(layout.USER_DATA_FILES), "대조 — 진짜 상한에서는 같은 백업이 읽힌다")

    def test_the_size_limit_is_for_received_backups_only_and_the_backup_maker_is_not_limited(self):
        lm = lim()
        with mock.patch.object(lm, "MAX_DB_BYTES", 10_000), mock.patch.object(lm, "MAX_MANIFEST_BYTES", 10):            # JSON 상한(`MAX_JSON_BYTES`)은 백업을 만들 때의 읽기 검사도 쓰는 값이라 여기서 줄이지 않는다
            made = self.world.backup(now=LATER + datetime.timedelta(seconds=2))
        self.assertEqual(made.files, layout.USER_DATA_FILES, "지금 데이터에서 막 만든 사본의 확인은 크기 상한을 받지 않는다 — 정상 동작이 그대로다")

    @unittest.skipUnless(HAS_SETLIMIT, "Connection.setlimit 는 파이썬 3.11 부터 있다 — 3.10 에서는 시간·크기 상한이 지킨다")
    def test_a_huge_value_in_a_real_table_is_refused_by_the_length_limit(self):
        lm = lim()
        size = dict(lm.LIMITS)["SQLITE_LIMIT_LENGTH"] + 1024
        folder = self.variant(lambda connection: connection.execute("UPDATE candidates SET data = ? WHERE candidate_id = 'cid-001'", ("x" * size,)))
        self.assertGreater((folder / layout.ENGINE_DB_FILE).stat().st_size, size)
        with SafetyNet() as net:
            reason, detail = self.reason_and_detail(bk.read_backup, folder)
        self.assertEqual(net.fired, 0)
        self.assertIn("too big", detail, "길이 한도가 그 칸을 읽지 못하게 했다(한도가 없으면 읽은 뒤 JSON 오류로 거절돼 이 문구가 없다)")


class LeafModuleTest(unittest.TestCase):
    def test_the_limit_module_imports_only_sqlite3_and_time_and_never_another_inner_module(self):
        # 머리말의 약속('다른 안쪽 모듈을 가져오지 않는다 · 외부 접속도 파일 쓰기도 하지 않는다')을 글자 그대로 못박는다 — `test_topicdb_rules` 는 `errors` 같은 허용된 안쪽 모듈의 가져오기를 막지 못한다.
        found = set()
        for node in ast.walk(ast.parse(Path(lim().__file__).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "상대 가져오기가 있다: " + ast.unparse(node))
                found.add((node.module or "").split(".")[0])
        self.assertEqual(found, {"__future__", "sqlite3", "time"})


if __name__ == "__main__":
    unittest.main()
