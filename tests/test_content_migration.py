"""보관함 구조 올리기(마이그레이션) 시험 — 처음으로 운영자의 진짜 파일을 올리는 코드라서 데이터 안전을 가장 세게 지킨다.

지키는 것:
  1) 같은 옛 파일을 여러 창·프로세스가 동시에 열어도 모두 성공하고, 한 번만 올라가며, 사본(`.v1.bak`)은 올리기 전 내용 그대로다(둘째가 첫째의 사본을 덮어쓰지 못한다).
  2) 이미 있는 사본은 덮어쓰지 않는다 — 똑같은 것이면 그것을 쓰고, 다르거나 못 읽는 것이면 건드리지 않고 다른 이름으로 새로 만든다. 사본은 쓰기 잠금을 쥔 채 만든다.
  3) 올리다 난 오류는 쉬운 안내로 나뉜다 — 잠김은 STORE_LOCKED, 디스크 가득·읽기 전용·경로가 긴 것은 MIGRATION_BLOCKED(원래 그대로라고 알린다), 그 밖은 MIGRATION_FAILED. 어느 쪽이든 파일은 바뀌지 않는다.
  4) 이름표만 맞고 표가 없거나 열이 다른 깨진 파일·판 번호 0 또는 음수는 올리기 전에 거절하고 파일도 사본도 만들지 않는다.
  5) 어느 순간에 프로세스가 죽어도(진짜 `os._exit`) 파일은 '옛 판 그대로' 아니면 '새 판 전체' 이고, 다시 열면 이어서 끝낸다(판 번호는 같은 트랜잭션 안·COMMIT 앞에서 올라간다).
  6) 올리기에 쓰는 DDL 은 판 2 의 것으로 고정돼 있다. 읽기 전용 열기(`migrate=False`)는 옛 판 파일을 한 바이트도(수정 시각까지) 바꾸지 않고 쓰기를 거절한다.
네트워크 없이 임시 폴더에서 돈다.
"""
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))                                          # tests/store_v1.py

from chanceblog_desktop.content import Candidate, ContentProject  # noqa: E402
from chanceblog_desktop.content import store as store_module  # noqa: E402
from chanceblog_desktop.content.store import APPLICATION_ID, SCHEMA_VERSION, Store  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.errors.render import UNKNOWN_SLOT  # noqa: E402
from store_v1 import make_v1_file  # noqa: E402

NOW = "2026-11-02T03:00:00Z"
OLD_TABLES = ("projects", "revisions", "drafts")


def project(project_id="p1"):
    return ContentProject.new("주제가 분명한 제목", "본문 첫 문단입니다.\n\n둘째 문단입니다.", project_id=project_id, now=NOW)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path):
    with closing(sqlite3.connect(str(path))) as db:
        return list(db.iterdump())


def rows(path):
    """옛 표 셋의 모든 행(파이썬 형까지)."""
    with closing(sqlite3.connect(str(path))) as db:
        return {table: [tuple((type(value).__name__, value) for value in row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in OLD_TABLES}


def pragma(path, name):
    with closing(sqlite3.connect(str(path))) as db:
        return db.execute(f"PRAGMA {name}").fetchone()[0]


def tables(path):
    with closing(sqlite3.connect(str(path))) as db:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


class MigrationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)                    # 나중에 등록한 것(저장소 닫기)이 먼저 돈다
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "data" / "chanceblog.db"

    def old_file(self, path=None, count=3):
        """판 1 의 파일(SQL 로 직접 만든 것 — tests/store_v1.py)."""
        path = Path(self.path if path is None else path)
        path.parent.mkdir(parents=True, exist_ok=True)
        make_v1_file(path, [project(f"p{number}") for number in range(count)], [("p0", "초안 글", NOW)])
        return path

    def open(self, path=None, **kwargs):
        store = Store.open(self.path if path is None else path, **kwargs)
        self.addCleanup(store.close)
        return store

    def refuses(self, code, callable_, *args, **kwargs):
        """AppError 의 코드를 확인하고, 사용자 문구의 자리표시자가 모두 채워지는지도 본다."""
        with self.assertRaises(AppError) as caught:
            callable_(*args, **kwargs)
        error = caught.exception
        self.assertEqual(error.code, code, error.detail)
        shown = error.rendered()
        self.assertNotIn(UNKNOWN_SLOT, shown.message + shown.action, f"{code}: 자리표시자가 비었다")
        return error

    def names(self, path=None):
        return sorted(entry.name for entry in Path(self.path if path is None else path).parent.iterdir())

    def copy_of(self, *args):
        """사본 경로 — `copy_of()`·`copy_of(2)`(둘째 이름)·`copy_of(파일)`·`copy_of(파일, 2)`."""
        path, number = Path(self.path), 1
        for value in args:
            if isinstance(value, int):
                number = value
            else:
                path = Path(value)
        return path.with_name(path.name + (".v1.bak" if number == 1 else f".v1.{number}.bak"))

    def untouched(self, path, before):
        """파일이 한 바이트도 바뀌지 않았다."""
        self.assertEqual(digest(path), before)

    def assert_upgraded_once(self, path, original_dump, original_rows):
        self.assertEqual(pragma(path, "user_version"), SCHEMA_VERSION)
        self.assertEqual(pragma(path, "integrity_check"), "ok")
        self.assertEqual(rows(path), original_rows, "옛 표의 행이 하나도 달라지지 않았다")
        self.assertIn("candidates", tables(path))
        copy = self.copy_of(path)
        self.assertEqual(dump(copy), original_dump, "사본은 올리기 전 파일 그대로다")
        self.assertEqual((pragma(copy, "user_version"), pragma(copy, "application_id")), (1, APPLICATION_ID))
        self.assertEqual(self.names(path), [path.name, copy.name], "사본 하나 말고 다른 파일(임시 파일·둘째 사본)이 남지 않았다")


class ConcurrentOpenTest(MigrationCase):
    def test_several_threads_opening_the_same_old_file_at_once_all_succeed_and_it_is_upgraded_once(self):
        for trial in range(30):
            with self.subTest(trial=trial):
                path = self.old_file(self.dir / f"t{trial}" / "chanceblog.db")
                original, original_rows = dump(path), rows(path)
                gate, outcomes = threading.Barrier(3), []

                def work(path=path, gate=gate, outcomes=outcomes):
                    try:
                        gate.wait(10)
                        with Store.open(path, busy_seconds=30) as store:
                            outcomes.append(("ok", store.schema_version, store.check()))
                    except BaseException as error:           # noqa: BLE001 — 스레드 안의 어떤 실패도 모은다
                        outcomes.append(("error", repr(error)))

                threads = [threading.Thread(target=work) for _ in range(3)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(60)
                self.assertEqual(outcomes, [("ok", 2, [])] * 3)
                self.assert_upgraded_once(path, original, original_rows)

    def race(self, count, trial):
        """진짜 프로세스 `count` 개가 거의 같은 순간에 같은 옛 파일을 연다."""
        path = self.old_file(self.dir / f"p{count}-{trial}" / "chanceblog.db")
        original, original_rows = dump(path), rows(path)
        go = self.dir / f"go-{count}-{trial}"
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        children = [subprocess.Popen([sys.executable, "-X", "utf8", str(HERE / "store_race_child.py"), str(SRC), str(path), str(go)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8", env=env) for _ in range(count)]
        try:
            for child in children:
                self.assertEqual(child.stdout.readline().strip(), "READY", "자식이 시작하지 못했다")
            go.write_text("go", encoding="utf-8")
            results = []
            for child in children:
                out, err = child.communicate(timeout=120)
                self.assertEqual(child.returncode, 0, err)
                result = json.loads(out.strip().splitlines()[-1])
                result.pop("seconds")
                results.append(result)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
        self.assertEqual(results, [{"ok": True, "version": 2, "check": []}] * count)
        self.assert_upgraded_once(path, original, original_rows)

    def test_two_real_processes_opening_the_same_old_file_at_once_all_succeed(self):
        for trial in range(10):
            with self.subTest(trial=trial):
                self.race(2, trial)

    def test_three_real_processes_opening_the_same_old_file_at_once_all_succeed(self):
        for trial in range(10):
            with self.subTest(trial=trial):
                self.race(3, trial)

    def test_a_second_opener_that_read_version_1_before_the_first_one_finished_finds_it_done_and_changes_nothing(self):
        path = self.old_file()
        original, original_rows = dump(path), rows(path)
        real_begin, state = Store._begin, {"first": True}

        def interleaved(store):
            if state["first"]:                                # 둘째가 판 1 을 읽고 잠금을 잡으러 가는 바로 그 틈에
                state["first"] = False
                Store.open(path).close()                      # 첫째가 끝까지 올린다(사본·단계·판 번호)
            return real_begin(store)

        with mock.patch.object(Store, "_begin", interleaved):
            second = self.open()
        self.assertEqual(second.schema_version, SCHEMA_VERSION)
        self.assertEqual(second.check(), [])
        self.assert_upgraded_once(path, original, original_rows)
        self.assertEqual(second.list_candidates(), [])
        second.save_candidate(Candidate.new("주제", "키워드", ("naver_a",), candidate_id="c1", now=NOW))           # 올라간 파일에 바로 쓸 수 있다

    def test_while_one_opener_makes_the_copy_another_cannot_slip_in_and_upgrade_the_file_under_it(self):
        """검증자가 찾은 틈 — 예전 코드는 사본을 잠금 밖에서 만들어, 그 사이 다른 쪽이 올리면 사본이 올린 뒤 내용으로 바뀌었다. 지금은 사본을 만드는 동안 쓰기 잠금을 쥐고 있다."""
        path = self.old_file()
        original, original_rows = dump(path), rows(path)
        real_snapshot, state, outcomes = Store._snapshot, {"first": True}, []

        def slow(store, destination):
            if state["first"]:
                state["first"] = False
                try:
                    Store.open(path, busy_seconds=0.2).close()           # 사본을 만드는 한가운데에 다른 쪽이 열어 보려 한다
                    outcomes.append("opened")
                except AppError as error:
                    outcomes.append(error.code)
            return real_snapshot(store, destination)

        with mock.patch.object(Store, "_snapshot", slow):
            self.open().close()
        self.assertEqual(outcomes, ["STORE_LOCKED"], "끼어든 쪽은 올릴 수 없었다")
        self.assert_upgraded_once(path, original, original_rows)

    def test_the_copy_is_made_while_the_write_lock_is_held(self):
        path = self.old_file()
        real_snapshot, seen = Store._snapshot, []

        def watching(store, destination):
            with closing(sqlite3.connect(str(path), timeout=0.05, isolation_level=None)) as other:
                try:
                    other.execute("BEGIN IMMEDIATE")
                    seen.append("다른 연결이 쓰기 잠금을 잡았다")
                    other.execute("ROLLBACK")
                except sqlite3.OperationalError as error:
                    seen.append(str(error))
            return real_snapshot(store, destination)

        with mock.patch.object(Store, "_snapshot", watching):
            self.open().close()
        self.assertEqual(seen, ["database is locked"])

    def test_a_brand_new_file_opened_by_several_threads_at_once_is_created_once_and_everyone_gets_it(self):
        for trial in range(30):
            with self.subTest(trial=trial):
                path = self.dir / f"new{trial}" / "chanceblog.db"
                path.parent.mkdir()
                gate, outcomes = threading.Barrier(3), []

                def work(path=path, gate=gate, outcomes=outcomes):
                    try:
                        gate.wait(10)
                        with Store.open(path, busy_seconds=30) as store:
                            outcomes.append(("ok", store.schema_version, store.check()))
                    except BaseException as error:           # noqa: BLE001
                        outcomes.append(("error", repr(error)))

                threads = [threading.Thread(target=work) for _ in range(3)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(60)
                self.assertEqual(outcomes, [("ok", 2, [])] * 3)
                self.assertEqual(self.names(path), ["chanceblog.db"], "새 파일은 올릴 것이 없으니 사본도 없다")
                self.assertEqual(tables(path), {"projects", "revisions", "drafts", "candidates"})

    def test_a_new_file_that_someone_else_created_while_we_waited_for_the_lock_leaves_no_transaction_open(self):
        path = self.dir / "fresh-race" / "chanceblog.db"
        real_begin, state = Store._begin, {"first": True}

        def interleaved(store):
            if state["first"]:                                # 새 파일을 만들러 잠금을 잡으러 가는 바로 그 틈에
                state["first"] = False
                Store.open(path).close()                      # 다른 쪽이 먼저 만들어 버렸다
            return real_begin(store)

        with mock.patch.object(Store, "_begin", interleaved):
            second = self.open(path)
        self.assertEqual((second.schema_version, second.check()), (SCHEMA_VERSION, []))
        self.assertFalse(second._db.in_transaction, "먼저 만들어졌음을 알아보고 끝낸 쪽이 쓰기 잠금을 쥔 채 남지 않았다")
        other = sqlite3.connect(str(path), isolation_level=None, timeout=0.2)
        self.addCleanup(other.close)
        other.execute("BEGIN IMMEDIATE")                                # 다른 연결이 곧바로 쓰기 잠금을 잡을 수 있다
        other.execute("ROLLBACK")
        self.assertEqual(self.names(path), ["chanceblog.db"], "새 파일은 올릴 것이 없으니 사본도 없다")
        self.assertEqual(tables(path), {"projects", "revisions", "drafts", "candidates"})


class CopyTest(MigrationCase):
    def test_the_copy_is_a_whole_database_with_the_old_name_tag_version_and_content(self):
        path = self.old_file()
        original, original_rows = dump(path), rows(path)
        self.open().close()
        self.assert_upgraded_once(path, original, original_rows)
        self.assertEqual(pragma(self.copy_of(), "quick_check"), "ok")

    def test_a_copy_that_already_exists_with_other_content_is_never_overwritten_and_a_new_name_is_used(self):
        path = self.old_file()
        original = dump(path)
        make_v1_file(self.copy_of(), [project("older")])           # 예전에 올릴 때 만든 사본 — 지금 파일과 내용이 다르다
        older_digest = digest(self.copy_of())
        self.open().close()
        self.assertEqual(digest(self.copy_of()), older_digest, "예전 사본은 한 바이트도 안 바뀌었다")
        self.assertEqual(dump(self.copy_of(2)), original, "지금 파일의 사본은 다음 이름으로 만들어졌다")
        self.assertEqual(self.names(), ["chanceblog.db", "chanceblog.db.v1.2.bak", "chanceblog.db.v1.bak"])
        self.assertEqual(pragma(path, "user_version"), 2)

    def test_a_copy_that_already_exists_with_the_same_content_is_reused_not_duplicated(self):
        path = self.old_file()
        original, original_rows = dump(path), rows(path)
        with mock.patch.object(store_module, "MIGRATIONS", {1: lambda db: (_ for _ in ()).throw(RuntimeError("올리다 실패"))}):
            self.refuses("MIGRATION_FAILED", Store.open, path)         # 사본은 만들었는데 올리지 못했다
        self.assertEqual(dump(self.copy_of()), original)
        self.assertEqual(pragma(path, "user_version"), 1)
        before = digest(self.copy_of())
        self.open().close()                                           # 다시 열면 같은 사본을 쓰고 새로 만들지 않는다
        self.assertEqual(digest(self.copy_of()), before)
        self.assert_upgraded_once(path, original, original_rows)

    def test_a_copy_with_the_same_rows_but_another_version_or_name_tag_is_not_reused(self):
        for label, pragma_sql in (("판 번호 0", "PRAGMA user_version = 0"), ("판 번호 2", "PRAGMA user_version = 2"), ("이름표", "PRAGMA application_id = 7")):
            with self.subTest(label):
                path = self.old_file(self.dir / f"tag-{len(label)}-{label[-1]}" / "chanceblog.db")
                original = dump(path)
                shutil.copyfile(path, self.copy_of(path))
                with closing(sqlite3.connect(str(self.copy_of(path)))) as db:
                    db.execute(pragma_sql)
                self.assertEqual(dump(self.copy_of(path)), original, "표와 행은 똑같다")
                before = digest(self.copy_of(path))
                Store.open(path).close()
                self.assertEqual(digest(self.copy_of(path)), before, "그 사본은 그대로다")
                self.assertEqual((dump(self.copy_of(path, 2)), pragma(self.copy_of(path, 2), "user_version")), (original, 1), "새 사본이 다음 이름으로 만들어졌다")

    def test_things_that_are_not_a_good_copy_are_left_alone_and_the_migration_still_succeeds(self):
        garbage = {"글": "이건 사본이 아니라 사용자가 둔 메모입니다. ".encode("utf-8") * 5, "빈 파일": b"", "엉뚱한 자료": b"SQLite format 3\x00" + b"\xff" * 200}
        for label, content in garbage.items():
            with self.subTest(label):
                path = self.old_file(self.dir / f"g{len(content)}" / "chanceblog.db")
                original = dump(path)
                self.copy_of(path).write_bytes(content)
                Store.open(path).close()
                self.assertEqual(self.copy_of(path).read_bytes(), content, "있던 것은 그대로다")
                self.assertEqual(dump(self.copy_of(path, 2)), original)
                self.assertEqual(pragma(path, "user_version"), 2)

    def test_a_folder_or_a_locked_file_in_the_copys_place_is_left_alone_too(self):
        path = self.old_file(self.dir / "folder" / "chanceblog.db")
        self.copy_of(path).mkdir()
        original = dump(path)
        Store.open(path).close()
        self.assertTrue(self.copy_of(path).is_dir())
        self.assertEqual(dump(self.copy_of(path, 2)), original)
        locked = self.old_file(self.dir / "locked" / "chanceblog.db")
        original = dump(locked)
        make_v1_file(self.copy_of(locked), [project("x")])
        holder = sqlite3.connect(str(self.copy_of(locked)), isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN EXCLUSIVE")                             # 다른 프로그램이 그 사본을 쥐고 있다
        started = time.monotonic()
        Store.open(locked, busy_seconds=0.2).close()
        self.assertLess(time.monotonic() - started, 5, "잠긴 사본이 풀리기를 끝없이 기다리지 않는다")
        holder.execute("ROLLBACK")
        self.assertEqual(dump(self.copy_of(locked, 2)), original)

    def test_a_read_only_copy_in_the_way_is_left_alone(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("관리자(root)는 읽기 전용 파일도 쓸 수 있다")
        path = self.old_file()
        make_v1_file(self.copy_of(), [project("x")])
        self.copy_of().chmod(stat.S_IREAD)
        self.addCleanup(self.copy_of().chmod, stat.S_IWRITE | stat.S_IREAD)
        before = digest(self.copy_of())
        original = dump(path)
        self.open().close()
        self.assertEqual(digest(self.copy_of()), before)
        self.assertEqual(dump(self.copy_of(2)), original)

    def test_when_every_copy_name_is_taken_it_says_so_and_changes_nothing(self):
        path = self.old_file()
        for number in range(1, store_module.MAX_COPY_NAMES + 1):
            self.copy_of(path, number).write_text(f"메모 {number}", encoding="utf-8")
        before, files = digest(path), {name: digest(self.path.parent / name) for name in self.names() if name != "chanceblog.db"}
        error = self.refuses("MIGRATION_BLOCKED", Store.open, path)
        self.assertIn("원래 그대로", error.rendered().message)
        self.assertEqual(digest(path), before)
        self.assertEqual({name: digest(self.path.parent / name) for name in self.names() if name != "chanceblog.db"}, files, "있던 파일은 하나도 안 바뀌었고 새 파일도 없다")

    def test_a_leftover_temporary_copy_from_a_killed_attempt_is_cleaned_up(self):
        path = self.old_file()
        original = dump(path)
        leftover = self.copy_of().with_name(self.copy_of().name + ".tmp")
        leftover.write_bytes(b"\xff" * 4096)
        self.open().close()
        self.assertEqual(self.names(), ["chanceblog.db", "chanceblog.db.v1.bak"])
        self.assertEqual(dump(self.copy_of()), original)

    def test_a_copy_that_comes_out_wrong_is_not_kept_and_nothing_changes(self):
        path = self.old_file()
        before = digest(path)

        def empty_copy(store, destination):
            sqlite3.connect(str(destination)).close()               # 이름표도 표도 없는 빈 파일

        with mock.patch.object(Store, "_snapshot", empty_copy):
            error = self.refuses("MIGRATION_FAILED", Store.open, path)
        self.assertIn("사본", error.detail)
        self.assertEqual(self.names(), ["chanceblog.db"], "잘못된 사본도 임시 파일도 남지 않는다")
        self.untouched(path, before)

    def test_a_slow_copy_that_keeps_making_progress_is_not_given_up_on_even_past_the_time_limit(self):
        path = self.old_file()
        original, original_rows = dump(path), rows(path)
        real_connect, made = sqlite3.connect, []

        class Slow:
            """오래 걸리지만 계속 나아가는 읽는 쪽 — 잠깐 막혔다 풀리기를 되풀이한다."""

            def __init__(self, real):
                self._real = real

            def backup(self, target, *, progress=None, **kwargs):
                for step in range(4):
                    progress(5, 6, 6)                               # 잠깐 막혔다가
                    time.sleep(0.06)
                    progress(0, 5, 6)                               # 다시 나아간다 — 한 번의 막힘(0.06초)은 상한(0.1초)보다 짧고, 합치면 더 길다
                self._real.backup(target, progress=progress, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        def fake(*args, **kwargs):
            real = real_connect(*args, **kwargs)
            if kwargs.get("uri") and not made:
                made.append(1)
                return Slow(real)
            return real

        with mock.patch.object(store_module, "COPY_SECONDS", 0.1), mock.patch.object(store_module.sqlite3, "connect", side_effect=fake):
            Store.open(path).close()
        self.assert_upgraded_once(path, original, original_rows)

    def test_a_copy_that_is_stuck_busy_or_locked_is_given_up_after_the_time_limit_with_the_locked_message(self):
        for status, label in ((5, "BUSY"), (6, "LOCKED")):
            with self.subTest(label):
                path = self.old_file(self.dir / label / "chanceblog.db")
                before, real_connect, made = digest(path), sqlite3.connect, []

                class Stuck:
                    """읽는 쪽이 계속 BUSY·LOCKED 라고 하는 연결 — 진행 콜백을 계속 부르며 기다린다."""

                    def __init__(self, real):
                        self._real = real

                    def backup(self, target, *, progress=None, status=status, **kwargs):
                        for _ in range(500):                         # 5초 — 시간 상한(0.2초)을 못 지키는 코드가 끝없이 매달리지 않고 여기서 시험이 실패하게
                            progress(status, 10, 10)
                            time.sleep(0.01)
                        raise AssertionError("시간 상한이 지나도록 사본 만들기가 멈추지 않았다")

                    def __getattr__(self, name):
                        return getattr(self._real, name)

                def fake(*args, **kwargs):
                    real = real_connect(*args, **kwargs)
                    if kwargs.get("uri") and not made:
                        made.append(1)
                        return Stuck(real)
                    return real

                started = time.monotonic()
                with mock.patch.object(store_module, "COPY_SECONDS", 0.2), mock.patch.object(store_module.sqlite3, "connect", side_effect=fake):
                    error = self.refuses("STORE_LOCKED", Store.open, path)
                self.assertLess(time.monotonic() - started, 10, "끝없이 기다리지 않는다")
                self.assertIn("계속 잠겨", error.detail)
                self.assertEqual(self.names(path), ["chanceblog.db"], "반쯤 만든 사본이 남지 않는다")
                self.untouched(path, before)
        self.assertEqual((store_module.COPY_SECONDS, store_module._SQLITE_BUSY, store_module._SQLITE_LOCKED), (30.0, 5, 6), "상한은 30초이고 BUSY=5·LOCKED=6 이다")


class ErrorMessageTest(MigrationCase):
    def test_a_write_lock_held_by_someone_else_is_the_locked_message_and_nothing_is_made_or_changed(self):
        path = self.old_file()
        before = digest(path)
        holder = sqlite3.connect(str(path), isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        error = self.refuses("STORE_LOCKED", Store.open, path, busy_seconds=0.2)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(error.rendered().message, CATALOG["STORE_LOCKED"].message)
        self.assertIn("바뀌지 않았습니다", error.rendered().action)
        self.assertEqual(self.names(), ["chanceblog.db"], "잠겨서 못 올린 것이니 사본도 안 만든다(쓰기 잠금을 잡은 뒤에야 만든다)")
        holder.execute("ROLLBACK")
        self.untouched(path, before)
        self.open().close()
        self.assertEqual(pragma(path, "user_version"), 2)

    def test_a_reader_that_keeps_the_file_open_makes_the_upgrade_wait_then_say_locked_and_it_can_be_retried(self):
        path = self.old_file()
        original, original_rows = dump(path), rows(path)
        reader = sqlite3.connect(str(path), isolation_level=None)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM projects").fetchall()        # 읽기 잠금을 쥔다
        self.refuses("STORE_LOCKED", Store.open, path, busy_seconds=0.2)
        self.assertEqual(pragma(path, "user_version"), 1)
        self.assertEqual(tables(path), set(OLD_TABLES), "올리다 만 표가 남지 않았다")
        reader.execute("ROLLBACK")
        self.open().close()
        self.assert_upgraded_once(path, original, original_rows)          # 먼저 만든 사본을 다시 써서 둘째 사본이 없다

    def test_a_full_disk_while_making_the_copy_says_so_and_cleans_up(self):
        path = self.old_file()
        before = digest(path)

        def fills_up(store, destination):
            Path(destination).write_bytes(b"\x00" * 100)                    # 반쯤 쓰다 디스크가 찼다
            raise sqlite3.OperationalError("database or disk is full")

        with mock.patch.object(Store, "_snapshot", fills_up):
            error = self.refuses("MIGRATION_BLOCKED", Store.open, path)
        shown = error.rendered()
        self.assertIn("저장 공간이 부족합니다", shown.message)
        self.assertIn("원래 그대로", shown.message)
        self.assertEqual(error.slots["이유"], "저장 공간이 부족합니다")
        self.assertEqual(self.names(), ["chanceblog.db"], "반쯤 쓴 임시 파일이 남지 않았다")
        self.untouched(path, before)
        self.open().close()                                                  # 공간을 확보하면 같은 파일이 올라간다
        self.assertEqual(pragma(path, "user_version"), 2)

    def test_operating_system_errors_while_placing_the_copy_are_environment_problems_not_failures(self):
        for label, error_to_raise, reason in (("권한", PermissionError(errno.EACCES, "Permission denied"), "쓸 수 없습니다"),
                                              ("공간", OSError(errno.ENOSPC, "No space left on device"), "저장 공간이 부족합니다"),
                                              ("경로", OSError(errno.ENAMETOOLONG, "File name too long"), "경로가 너무 길어")):
            with self.subTest(label):
                path = self.old_file(self.dir / label / "chanceblog.db")
                before = digest(path)
                with mock.patch.object(store_module.os, "rename", side_effect=error_to_raise):
                    error = self.refuses("MIGRATION_BLOCKED", Store.open, path)
                self.assertIn(reason, error.slots["이유"])
                self.assertEqual(self.names(path), ["chanceblog.db"], "이름을 못 바꾼 임시 사본은 치워졌다")
                self.untouched(path, before)
        with mock.patch.object(store_module.os, "rename", side_effect=OSError(errno.EIO, "알 수 없는 입출력 문제")):
            self.refuses("MIGRATION_FAILED", Store.open, self.old_file())

    def test_a_file_with_the_read_only_attribute_says_so_and_nothing_is_made(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("관리자(root)는 읽기 전용 파일도 쓸 수 있다")
        path = self.old_file()
        path.chmod(stat.S_IREAD)
        self.addCleanup(path.chmod, stat.S_IWRITE | stat.S_IREAD)
        before = digest(path)
        error = self.refuses("MIGRATION_BLOCKED", Store.open, path)
        self.assertEqual(error.slots["이유"], "데이터 파일이 읽기 전용입니다")
        self.assertIn("원래 그대로", error.rendered().message)
        self.assertEqual(self.names(), ["chanceblog.db"])
        self.untouched(path, before)

    def test_a_path_too_long_for_the_copy_name_is_reported_before_anything_is_made(self):
        path = self.old_file()
        before = digest(path)
        shortest = len(os.path.abspath(path)) + len(".v1.bak.tmp")
        with mock.patch.object(store_module, "_COPY_PATH_LIMIT", shortest - 1):
            error = self.refuses("MIGRATION_BLOCKED", Store.open, path)
        self.assertIn("너무 길어", error.slots["이유"])
        self.assertEqual(self.names(), ["chanceblog.db"])
        self.untouched(path, before)
        with mock.patch.object(store_module, "_COPY_PATH_LIMIT", shortest):          # 딱 맞으면 된다
            self.open().close()
        self.assertEqual(pragma(path, "user_version"), 2)

    def test_the_windows_path_limit_is_set_only_on_windows(self):
        self.assertEqual(store_module._COPY_PATH_LIMIT, 259 if os.name == "nt" else None)

    def test_a_failing_step_is_the_failed_message_and_everything_is_put_back(self):
        path = self.old_file()
        original = dump(path)

        def broken(db):
            db.execute("CREATE TABLE half_done (id INTEGER)")
            raise RuntimeError("중간에 실패")

        with mock.patch.object(store_module, "MIGRATIONS", {1: broken}):
            error = self.refuses("MIGRATION_FAILED", Store.open, path)
        self.assertIn("중간에 실패", error.detail)
        self.assertEqual(dump(path), original)
        self.assertEqual(pragma(path, "user_version"), 1)

    def test_a_failed_upgrade_while_restoring_leaves_the_open_store_without_a_pending_transaction_whatever_failed(self):
        """열기는 실패하면 연결을 닫아 트랜잭션이 사라지지만, 복구는 이미 열린 저장소의 연결로 올리므로 어떤 실패든 쓰기 잠금을 쥔 채 남지 않아야 한다."""
        backup = self.dir / "backups" / "old-20261030-060000.db"
        backup.parent.mkdir()
        make_v1_file(backup, [project("p7")])
        for number, error in enumerate((AppError("STORE_LOCKED", detail="사본 중 잠김"), sqlite3.OperationalError("database or disk is full"), RuntimeError("그 밖의 실패"))):
            with self.subTest(type(error).__name__):
                store = self.open(self.dir / f"live{number}" / "chanceblog.db")
                store.save(project("p1"))
                with mock.patch.object(Store, "_snapshot", side_effect=error):
                    with self.assertRaises(AppError):
                        store.restore_from(backup)
                self.assertFalse(store._db.in_transaction, "실패한 복구가 쓰기 잠금을 쥔 채 남았다")
                self.assertEqual([item.project_id for item in store.list()], ["p7"], "복구한 내용(옛 구조)이 그대로 있다")
                store.save(project("p9"))                                          # 이어서 쓸 수 있다
                other = sqlite3.connect(str(store.path), isolation_level=None, timeout=0.2)
                self.addCleanup(other.close)
                other.execute("BEGIN IMMEDIATE")                                   # 다른 연결이 쓰기 잠금을 곧바로 잡을 수 있다
                other.execute("ROLLBACK")

    def test_a_missing_step_is_refused_before_any_copy_is_made(self):
        path = self.old_file()
        before = digest(path)
        with mock.patch.object(store_module, "SCHEMA_VERSION", 3), mock.patch.object(store_module, "MIGRATIONS", {1: lambda db: None}):
            error = self.refuses("MIGRATION_FAILED", Store.open, path)
        self.assertIn("버전 2", error.detail)
        self.assertEqual(self.names(), ["chanceblog.db"], "올릴 길이 없는 파일에 사본 찌꺼기를 남기지 않는다")
        self.untouched(path, before)

    def test_each_kind_of_sqlite_environment_failure_while_upgrading_gets_its_own_plain_reason(self):
        for message, reason in (("attempt to write a readonly database", "읽기 전용"), ("unable to open database file", "쓸 수 없습니다"), ("disk I/O error", "디스크 읽기·쓰기 오류"),
                                ("database or disk is full", "저장 공간이 부족합니다")):
            with self.subTest(message):
                path = self.old_file(self.dir / message.split()[0] / "chanceblog.db")
                before = digest(path)
                with mock.patch.object(Store, "_snapshot", side_effect=sqlite3.OperationalError(message)):
                    error = self.refuses("MIGRATION_BLOCKED", Store.open, path)
                self.assertIn(reason, error.slots["이유"])
                self.assertIn("원래 그대로", error.rendered().message)
                self.assertIn(reason, error.rendered().message)
                self.assertEqual(self.names(path), ["chanceblog.db"])
                self.untouched(path, before)

    def test_a_damaged_file_found_while_upgrading_is_the_damaged_message_and_a_locked_copy_is_the_locked_one(self):
        path = self.old_file()
        before = digest(path)
        with mock.patch.object(Store, "_snapshot", side_effect=sqlite3.DatabaseError("database disk image is malformed")):
            error = self.refuses("STORE_CORRUPT", Store.open, path)
        self.assertIn("chanceblog.db", error.rendered().message)
        with mock.patch.object(Store, "_snapshot", side_effect=sqlite3.OperationalError("database is locked")):
            self.refuses("STORE_LOCKED", Store.open, path)
        with mock.patch.object(Store, "_snapshot", side_effect=sqlite3.IntegrityError("UNIQUE constraint failed: x")):
            self.refuses("MIGRATION_FAILED", Store.open, path)                 # 알려진 환경 문제가 아닌 SQLite 오류는 변환 실패다
        self.untouched(path, before)

    def test_more_operating_system_errors_are_environment_problems_too(self):
        winerror = OSError(0, "경로가 너무 깁니다")
        winerror.winerror = 206
        for label, error_to_raise, reason in (("읽기 전용 파일 시스템", OSError(errno.EROFS, "Read-only file system"), "쓸 수 없습니다"), ("권한 없음", OSError(errno.EPERM, "Operation not permitted"), "쓸 수 없습니다"),
                                              ("윈도 경로 길이", winerror, "경로가 너무 길어"), ("권한 거부(오류 번호가 없는 PermissionError)", PermissionError("denied"), "쓸 수 없습니다")):
            with self.subTest(label):
                path = self.old_file(self.dir / f"os-{label}" / "chanceblog.db")
                with mock.patch.object(store_module.os, "rename", side_effect=error_to_raise):
                    error = self.refuses("MIGRATION_BLOCKED", Store.open, path)
                self.assertIn(reason, error.slots["이유"])

    def test_a_copy_that_comes_out_with_another_version_or_name_tag_is_not_kept(self):
        real_snapshot = Store._snapshot
        for label, pragma_sql in (("판 번호", "PRAGMA user_version = 5"), ("이름표", "PRAGMA application_id = 7")):
            with self.subTest(label):
                path = self.old_file(self.dir / f"wrong-{len(label)}" / "chanceblog.db")
                before = digest(path)

                def tampered(store, destination, pragma_sql=pragma_sql):
                    real_snapshot(store, destination)
                    with closing(sqlite3.connect(str(destination))) as db:
                        db.execute(pragma_sql)

                with mock.patch.object(Store, "_snapshot", tampered):
                    error = self.refuses("MIGRATION_FAILED", Store.open, path)
                self.assertIn("사본이 올바르지 않다", error.detail)
                self.assertEqual(self.names(path), ["chanceblog.db"])
                self.untouched(path, before)

    def test_a_copy_whose_own_check_does_not_come_out_ok_is_not_kept(self):
        path = self.old_file()
        before, real_connect = digest(path), sqlite3.connect

        class Damaged:
            """사본을 점검하는 연결 — 점검(quick_check)만 '깨졌다' 고 답한다(이름표·판 번호는 맞다)."""

            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args):
                if sql.strip().upper() == "PRAGMA QUICK_CHECK":
                    return mock.Mock(fetchone=lambda: ("*** in database main ***\nPage 2: btreeInitPage() returns error code 11",))
                return self._real.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self._real, name)

        def fake(*args, **kwargs):
            real = real_connect(*args, **kwargs)
            if args and str(args[0]).endswith(".bak.tmp?mode=ro"):
                return Damaged(real)
            return real

        with mock.patch.object(store_module.sqlite3, "connect", side_effect=fake):
            error = self.refuses("MIGRATION_FAILED", Store.open, path)
        self.assertIn("사본이 올바르지 않다", error.detail)
        self.assertIn("btreeInitPage", error.detail, "어떤 점검 결과였는지 남는다")
        self.assertEqual(self.names(path), ["chanceblog.db"], "깨진 사본을 이름 붙여 남기지 않는다")
        self.untouched(path, before)

    def test_the_new_and_the_changed_error_rows_say_what_they_must(self):
        blocked = CATALOG["MIGRATION_BLOCKED"]
        self.assertEqual(set(blocked.slots), {"이유"})
        self.assertIn("원래 그대로", blocked.message)
        self.assertIn("다시 열어도 안전", blocked.action)
        self.assertEqual(blocked.retry_kind, "after_user")
        self.assertIn("바뀌지 않았습니다", CATALOG["STORE_LOCKED"].action)
        self.assertIn("MIGRATION_BLOCKED", (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8"))

    def test_the_reason_texts_are_plain_korean_for_each_kind_of_environment_problem(self):
        self.assertEqual(store_module._blocked_reason("DISK_FULL", "database or disk is full"), "저장 공간이 부족합니다")
        self.assertEqual(store_module._blocked_reason("FILE_WRITE_FAILED", "attempt to write a readonly database"), "데이터 파일이 읽기 전용입니다")
        self.assertEqual(store_module._blocked_reason("FILE_WRITE_FAILED", "attempt to write a read-only database"), "데이터 파일이 읽기 전용입니다")
        self.assertIn("디스크 읽기·쓰기 오류", store_module._blocked_reason("FILE_WRITE_FAILED", "disk I/O error"))
        self.assertIn("쓸 수 없습니다", store_module._blocked_reason("FILE_WRITE_FAILED", "unable to open database file"))
        winerror = OSError(0, "disk full")
        winerror.winerror = 112
        self.assertEqual(store_module._os_blocked_reason(winerror), "저장 공간이 부족합니다")
        self.assertIsNone(store_module._os_blocked_reason(OSError(errno.EIO, "x")))


class OddFilesTest(MigrationCase):
    """이름표(application_id·user_version)만 맞춘 낯선 파일 — 올리기 전에 거절하고 파일도 사본도 만들지 않는다."""

    V1 = (
        "CREATE TABLE projects (project_id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL)",
        "CREATE TABLE revisions (project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE, revision INTEGER NOT NULL, saved_at TEXT NOT NULL, data TEXT NOT NULL,"
        " PRIMARY KEY (project_id, revision))",
        "CREATE TABLE drafts (project_id TEXT PRIMARY KEY, text TEXT NOT NULL, saved_at TEXT NOT NULL)",
    )

    def make(self, name, statements, *, application=APPLICATION_ID, version=1):
        path = self.dir / name / "chanceblog.db"
        path.parent.mkdir()
        with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
            for statement in statements:
                db.execute(statement)
            db.execute(f"PRAGMA application_id = {application}")
            db.execute(f"PRAGMA user_version = {version}")
        return path

    def assert_refused_untouched(self, path, code="STORE_CORRUPT"):
        before, names = digest(path), self.names(path)
        error = self.refuses(code, Store.open, path)
        self.assertEqual(digest(path), before)
        self.assertEqual(self.names(path), names, "사본도 임시 파일도 만들지 않았다")
        return error

    def test_the_helper_makes_a_good_version_1_file_that_opens(self):
        path = self.make("good", self.V1)
        Store.open(path).close()
        self.assertEqual(pragma(path, "user_version"), 2)

    def test_version_0_and_negative_versions_are_refused_without_leaving_a_copy_named_after_them(self):
        for version in (0, -1, -7):
            with self.subTest(version=version):
                error = self.assert_refused_untouched(self.make(f"v{version}", self.V1, version=version))
                self.assertIn(str(version), error.detail)

    def test_a_file_with_the_name_tag_but_missing_or_different_tables_is_refused_before_upgrading(self):
        cases = {
            "표 없음": [],
            "projects 만": self.V1[:1],
            "revisions 없음": (self.V1[0], self.V1[2]),
            "열이 다름": ("CREATE TABLE projects (x INTEGER)", "CREATE TABLE revisions (y INTEGER)", "CREATE TABLE drafts (z INTEGER)"),
            "열 하나 부족": (self.V1[0], self.V1[1], "CREATE TABLE drafts (project_id TEXT PRIMARY KEY, text TEXT NOT NULL)"),
            "열 순서 다름": (self.V1[0], self.V1[1], "CREATE TABLE drafts (text TEXT, project_id TEXT PRIMARY KEY, saved_at TEXT NOT NULL)"),
        }
        for number, (label, statements) in enumerate(cases.items()):
            with self.subTest(label):
                path = self.make(f"shape{number}", statements)
                error = self.assert_refused_untouched(path)
                self.assertIn("표", error.detail)

    def test_a_version_2_file_missing_its_candidates_table_is_refused_too(self):
        path = self.make("v2-missing", self.V1, version=2)
        self.assert_refused_untouched(path)
        wrong = self.make("v2-wrong", self.V1 + ("CREATE TABLE candidates (candidate_id TEXT)",), version=2)
        self.assert_refused_untouched(wrong)

    def test_another_programs_database_and_a_newer_version_are_refused_untouched(self):
        self.assert_refused_untouched(self.make("other", ["CREATE TABLE t (a)"], application=12345))
        self.assert_refused_untouched(self.make("other0", ["CREATE TABLE t (a)"], application=0, version=0))
        self.assert_refused_untouched(self.make("future", self.V1, version=SCHEMA_VERSION + 1), "STORE_VERSION_UNSUPPORTED")

    def test_a_user_table_named_candidates_with_other_columns_fails_the_upgrade_and_changes_nothing(self):
        path = self.make("preexisting", self.V1 + ("CREATE TABLE candidates (note TEXT)", "INSERT INTO candidates VALUES ('사용자 자료')"))
        before = dump(path)
        error = self.refuses("MIGRATION_FAILED", Store.open, path)
        self.assertIn("candidates", error.detail)
        self.assertEqual(dump(path), before, "있던 표와 그 안의 자료가 그대로다")
        self.assertEqual(pragma(path, "user_version"), 1)

    def test_a_foreign_index_with_a_candidates_name_fails_the_upgrade_instead_of_being_silently_accepted(self):
        cases = (
            ("다른 표의 다른 열", "candidates_keyword", ("CREATE INDEX candidates_keyword ON projects (title)",)),
            ("맞는 표의 다른 열", "candidates_status", (store_module._V2_CANDIDATES[0], "CREATE INDEX candidates_status ON candidates (candidate_id)")),
            ("다른 표의 같은 열 이름", "candidates_status", ("CREATE TABLE other_things (status TEXT, updated_at TEXT)", "CREATE INDEX candidates_status ON other_things (status, updated_at DESC)")),
            ("열 순서가 뒤집힘", "candidates_keyword", (store_module._V2_CANDIDATES[0], "CREATE INDEX candidates_keyword ON candidates (status, keyword_key)")),
        )
        for number, (label, index, statements) in enumerate(cases):
            with self.subTest(label):
                path = self.old_file(self.dir / f"index{number}" / "chanceblog.db")
                with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
                    for statement in statements:
                        db.execute(statement)
                before = dump(path)
                error = self.refuses("MIGRATION_FAILED", Store.open, path)
                self.assertIn(index, error.detail)
                self.assertEqual(dump(path), before)
                self.assertEqual(pragma(path, "user_version"), 1)

    def test_the_exact_candidates_table_left_by_an_interrupted_older_attempt_is_adopted(self):
        """IF NOT EXISTS 의 쓸모 — 표만 있고 판 번호가 옛 것인 파일(앞선 코드가 COMMIT 과 판 번호 사이에서 죽은 경우)도 이어서 끝낸다."""
        path = self.old_file()
        with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
            for statement in store_module._V2_CANDIDATES:
                db.execute(statement)
        original_rows = rows(path)
        store = self.open()
        self.assertEqual((store.schema_version, store.check()), (SCHEMA_VERSION, []))
        self.assertEqual(rows(path), original_rows)
        self.assertEqual(pragma(path, "user_version"), 2)

    def test_restoring_a_backup_with_missing_tables_is_refused_before_the_live_store_is_replaced(self):
        store = self.open()
        store.save(project("keep"))
        broken = self.make("broken-backup", self.V1[:1])
        before = [item.project_id for item in store.list()]
        self.refuses("STORE_CORRUPT", store.restore_from, broken)
        self.assertEqual([item.project_id for item in store.list()], before, "지금 저장소는 백업으로 덮어쓰이기 전에 거절됐다")
        self.assertEqual(store.check(), [])

    def test_restoring_a_backup_whose_version_this_program_never_made_is_refused_before_the_live_store_is_replaced(self):
        store = self.open()
        store.save(project("keep"))
        for number, version in enumerate((0, -1)):
            with self.subTest(version):
                weird = self.make(f"weird-backup{number}", self.V1, version=version)
                before = [item.project_id for item in store.list()]
                error = self.refuses("STORE_CORRUPT", store.restore_from, weird)
                self.assertIn(str(version), error.detail)
                self.assertEqual([item.project_id for item in store.list()], before, "지금 저장소는 그 백업으로 덮이지 않았다")
                self.assertEqual(store.check(), [])


class DdlFreezeTest(MigrationCase):
    PINNED = "2228c1f7b621678260e75af9a5ae058a3822d727bee02733b81ac0dbb406502a"

    def test_the_documented_numbers_are_these_literal_ones(self):
        self.assertEqual((SCHEMA_VERSION, store_module.MIN_SCHEMA_VERSION, store_module.MAX_COPY_NAMES, store_module.COPY_SECONDS), (2, 1, 20, 30.0))
        self.assertEqual(set(store_module.MIGRATIONS), {1})
        self.assertEqual(store_module.APPLICATION_ID, 0x43424450)

    def test_a_store_that_returned_early_from_the_upgrade_holds_no_transaction(self):
        path = self.old_file()
        real_begin = Store._begin

        def interleaved(store):
            if not hasattr(interleaved, "done"):
                interleaved.done = True
                Store.open(path).close()
            return real_begin(store)

        with mock.patch.object(Store, "_begin", interleaved):
            second = self.open()
        self.assertFalse(second._db.in_transaction, "이미 올랐음을 알아보고 끝낸 쪽이 쓰기 잠금을 쥔 채 남지 않았다")
        other = sqlite3.connect(str(path), isolation_level=None, timeout=0.2)
        self.addCleanup(other.close)
        other.execute("BEGIN IMMEDIATE")                                # 다른 연결이 곧바로 쓰기 잠금을 잡을 수 있다
        other.execute("ROLLBACK")

    def test_the_ddl_the_version_2_step_runs_is_frozen(self):
        text = "\n".join(store_module._V2_CANDIDATES)
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), self.PINNED,
                         "판 2 의 DDL 은 고치지 않는다 — 이 표를 바꿀 일이면 이 문장은 그대로 두고 판 3 의 올리기 단계를 따로 만든다(그래야 판 1 파일의 1 → 2 가 옛 모양으로 만들어진다)")

    def test_the_step_does_not_read_the_live_schema_list_so_changing_that_later_cannot_change_version_2(self):
        path = self.old_file()
        changed = tuple(statement.replace("data TEXT NOT NULL", "data TEXT NOT NULL, extra TEXT") for statement in store_module._SCHEMA)
        with mock.patch.object(store_module, "_SCHEMA", changed):
            self.open().close()
        with closing(sqlite3.connect(str(path))) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(candidates)")]
        self.assertEqual(columns, ["candidate_id", "keyword_key", "status", "project_id", "revision", "created_at", "updated_at", "data"])

    def test_the_step_is_safe_to_run_twice_and_a_new_file_has_the_same_table_as_an_upgraded_one(self):
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
            for statement in store_module._SCHEMA[:4]:
                db.execute(statement)
            store_module._add_candidates(db)
            store_module._add_candidates(db)
            upgraded = {row[0]: row[1] for row in db.execute("SELECT name, sql FROM sqlite_master WHERE name LIKE 'candidates%'")}
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
            for statement in store_module._SCHEMA:
                db.execute(statement)
            fresh = {row[0]: row[1] for row in db.execute("SELECT name, sql FROM sqlite_master WHERE name LIKE 'candidates%'")}
        self.assertEqual(upgraded, fresh)
        self.assertEqual(set(fresh), {"candidates", "candidates_status", "candidates_keyword"})

    def test_the_shape_check_names_what_is_wrong(self):
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
            for statement in store_module._SCHEMA:
                db.execute(statement)
            self.assertIsNone(store_module._shape_problem(db, 2, indexes=True))
            self.assertIsNone(store_module._shape_problem(db, 99), "모르는 판은 보지 않는다")
            db.execute("DROP INDEX candidates_status")
            self.assertIn("candidates_status", store_module._shape_problem(db, 2, indexes=True))
            self.assertIsNone(store_module._shape_problem(db, 2), "색인은 열 때 검사하지 않는다(없어도 느려질 뿐 깨진 것이 아니다)")
            db.execute("DROP TABLE candidates")
            self.assertIn("candidates", store_module._shape_problem(db, 2))
            self.assertIsNone(store_module._shape_problem(db, 1))


class CrashTest(MigrationCase):
    POINTS = ("before_begin", "after_begin", "mid_copy", "after_copy", "after_first_statement", "after_all_statements", "before_user_version", "after_user_version", "before_commit", "after_commit")

    def test_killing_the_process_at_any_moment_leaves_the_old_file_or_the_whole_new_one_and_a_reopen_finishes_it(self):
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        for point in self.POINTS:
            with self.subTest(point=point):
                path = self.old_file(self.dir / point / "chanceblog.db")
                original, original_rows = dump(path), rows(path)
                done = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "store_crash_child.py"), str(SRC), str(path), point], capture_output=True, text=True, encoding="utf-8",
                                      env=env, timeout=120)
                self.assertEqual(done.returncode, 9, f"{point}: 죽어야 하는데 {done.returncode}: {done.stdout}{done.stderr}")
                # 죽은 직후의 파일(읽으면서 남은 저널을 되돌린다) — 순수 sqlite3 로만 본다
                version, found = pragma(path, "user_version"), tables(path)
                self.assertEqual(pragma(path, "integrity_check"), "ok", point)
                self.assertIn(version, (1, 2), point)
                self.assertEqual("candidates" in found, version == 2, f"{point}: 판 번호와 표가 어긋났다(판 {version}, 표 {sorted(found)})")
                self.assertEqual(rows(path), original_rows, point)
                # 다시 열면 이어서 끝난다
                with Store.open(path) as store:
                    self.assertEqual((store.schema_version, store.check(), store.list_candidates()), (SCHEMA_VERSION, [], []), point)
                self.assertEqual(rows(path), original_rows, point)
                self.assertEqual(dump(self.copy_of(path)), original, f"{point}: 사본은 올리기 전 내용이다")
                self.assertEqual(self.names(path), ["chanceblog.db", "chanceblog.db.v1.bak"], f"{point}: 둘째 사본이나 임시 파일이 남지 않았다")
                self.assertEqual(pragma(self.copy_of(path), "user_version"), 1)

    def test_the_version_number_goes_up_inside_the_transaction_before_the_commit(self):
        path = self.old_file()
        real_connect, seen = sqlite3.connect, []

        class Spy:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args):
                seen.append(" ".join(sql.split()).upper().split(" (")[0][:40])
                return self._real.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self._real, name)

        def spy(*args, **kwargs):
            real = real_connect(*args, **kwargs)
            return Spy(real) if kwargs.get("isolation_level", 0) is None and not kwargs.get("uri") else real

        with mock.patch.object(store_module.sqlite3, "connect", side_effect=spy):
            Store.open(path).close()
        begin, version, commit = seen.index("BEGIN IMMEDIATE"), seen.index("PRAGMA USER_VERSION = 2"), seen.index("COMMIT")
        steps = [index for index, sql in enumerate(seen) if sql.startswith("CREATE ")]
        self.assertTrue(begin < min(steps) and max(steps) < version < commit, seen)
        self.assertEqual(seen.count("COMMIT"), 1)


class ReadOnlyOpenTest(MigrationCase):
    def stat_of(self, path):
        info = os.stat(path)
        return (digest(path), info.st_mtime_ns, info.st_size, self.names(path))

    def test_a_version_1_file_opened_read_only_is_not_changed_at_all_and_says_it_needs_upgrading(self):
        path = self.old_file()
        before = self.stat_of(path)
        store = Store.open(path, migrate=False)
        self.assertEqual((store.schema_version, store.needs_migration, store.read_only), (1, True, True))
        self.assertEqual([item.project_id for item in store.list()], ["p0", "p1", "p2"])
        self.assertEqual(store.load("p1").project_id, "p1")
        self.assertEqual(store.load_draft("p0").text, "초안 글")
        self.assertEqual(store.check(), [], "옛 판 파일의 점검에 후보 표가 없다는 문제가 끼지 않는다")
        self.assertEqual(store.list_candidates(), [])
        self.assertEqual(store.list_candidates(status="NEW", blog="naver_a"), [])
        self.assertEqual(store.recent_selections("키워드", "naver_a", 90, now=NOW), [])
        self.refuses("CANDIDATE_NOT_FOUND", store.load_candidate, "c1")
        store.close()
        self.assertEqual(self.stat_of(path), before, "열고 읽고 닫았는데 바이트·수정 시각·파일 목록이 달라졌다")
        self.assertFalse(self.copy_of(path).exists())
        with Store.open(path, migrate=False):                         # 몇 번을 열어도
            pass
        self.assertEqual(self.stat_of(path), before)

    def test_every_write_is_refused_and_leaves_the_file_alone(self):
        path = self.old_file()
        before = self.stat_of(path)
        store = Store.open(path, migrate=False)
        item = Candidate.new("주제", "키워드", ("naver_a",), candidate_id="c1", now=NOW)
        for label, call in (("save", lambda: store.save(project("new"))), ("delete", lambda: store.delete("p1")), ("save_draft", lambda: store.save_draft("p1", "글")),
                            ("discard_draft", lambda: store.discard_draft("p0")), ("save_candidate", lambda: store.save_candidate(item)),
                            ("set_candidate_status", lambda: store.set_candidate_status("c1", "REVIEW")), ("delete_candidate", lambda: store.delete_candidate("c1", confirm=True)),
                            ("restore_from", lambda: store.restore_from(path))):
            with self.subTest(label):
                error = self.refuses("UNEXPECTED_ERROR", call)
                self.assertIn("읽기 전용", error.detail)
        store.close()
        self.assertEqual(self.stat_of(path), before)

    def test_a_current_version_file_opened_read_only_reads_everything_and_still_refuses_writes(self):
        with Store.open(self.path) as store:
            store.save(project("p1"))
            store.save_candidate(Candidate.new("주제", "키워드", ("naver_a",), candidate_id="c1", now=NOW))
        before = self.stat_of(self.path)
        with Store.open(self.path, migrate=False) as store:
            self.assertEqual((store.schema_version, store.needs_migration, store.read_only), (SCHEMA_VERSION, False, True))
            self.assertEqual(store.load_candidate("c1").topic, "주제")
            self.assertEqual([item.candidate_id for item in store.list_candidates()], ["c1"])
            self.assertEqual(store.check(), [])
            self.refuses("UNEXPECTED_ERROR", store.save, project("p2"))
        self.assertEqual(self.stat_of(self.path), before)

    def test_a_normal_open_is_not_read_only_and_reports_the_current_version(self):
        old = self.old_file()
        store = self.open(old)
        self.assertEqual((store.schema_version, store.needs_migration, store.read_only), (SCHEMA_VERSION, False, False))

    def test_a_missing_or_empty_file_is_not_created_by_a_read_only_open(self):
        missing = self.dir / "nowhere" / "chanceblog.db"
        error = self.refuses("CONTENT_NOT_FOUND", Store.open, missing, migrate=False)
        self.assertIn("chanceblog.db", error.rendered().message)
        self.assertFalse(missing.parent.exists(), "폴더도 만들지 않는다")
        empty = self.dir / "empty.db"
        empty.write_bytes(b"")
        self.refuses("CONTENT_NOT_FOUND", Store.open, empty, migrate=False)
        self.assertEqual(empty.read_bytes(), b"")
        folder = self.dir / "folder.db"
        folder.mkdir()
        self.refuses("FILE_WRITE_FAILED", Store.open, folder, migrate=False)

    def test_foreign_damaged_and_newer_files_are_refused_the_same_way_and_untouched(self):
        foreign = self.dir / "foreign.db"
        with closing(sqlite3.connect(str(foreign))) as db:
            db.execute("CREATE TABLE notes (id INTEGER)")
            db.commit()
        text = self.dir / "text.db"
        text.write_text("그냥 메모입니다 " * 40, encoding="utf-8")
        newer = self.old_file(self.dir / "newer" / "chanceblog.db")
        with closing(sqlite3.connect(str(newer))) as db:
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        odd = self.dir / "odd.db"
        with closing(sqlite3.connect(str(odd))) as db:
            db.execute("CREATE TABLE projects (x INTEGER)")
            db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            db.execute("PRAGMA user_version = 1")
        for path, code in ((foreign, "STORE_CORRUPT"), (text, "STORE_CORRUPT"), (newer, "STORE_VERSION_UNSUPPORTED"), (odd, "STORE_CORRUPT")):
            with self.subTest(path.name):
                before = self.stat_of(path)
                self.refuses(code, Store.open, path, migrate=False)
                self.assertEqual(self.stat_of(path), before)

    def test_a_file_with_the_read_only_attribute_can_be_inspected(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("관리자(root)는 읽기 전용 파일도 쓸 수 있다")
        path = self.old_file()
        path.chmod(stat.S_IREAD)
        self.addCleanup(path.chmod, stat.S_IWRITE | stat.S_IREAD)
        before = self.stat_of(path)
        with Store.open(path, migrate=False) as store:
            self.assertEqual((store.needs_migration, store.check()), (True, []))
        self.assertEqual(self.stat_of(path), before)

    def test_a_file_that_someone_else_is_writing_is_reported_as_locked_not_waited_on_forever(self):
        path = self.old_file()
        holder = sqlite3.connect(str(path), isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        self.refuses("STORE_LOCKED", Store.open, path, migrate=False, busy_seconds=0.2)
        self.assertLess(time.monotonic() - started, 5)
        holder.execute("ROLLBACK")

    def test_the_connection_itself_is_read_only_not_just_the_methods(self):
        path = self.old_file()
        with Store.open(path, migrate=False) as store:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                store._db.execute("CREATE TABLE sneaky (a)")
            self.assertIn("readonly", str(caught.exception))
            with self.assertRaises(sqlite3.OperationalError):
                store._db.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES ('x', 'y', 'z')")

    def test_opening_an_up_to_date_file_never_needs_the_write_lock(self):
        with Store.open(self.path) as store:
            store.save(project("p1"))
        holder = sqlite3.connect(str(self.path), isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN IMMEDIATE")                             # 다른 곳이 쓰고 있어도 읽기만 하는 열기는 막히지 않는다
        started = time.monotonic()
        with Store.open(self.path, busy_seconds=0.2) as store:
            self.assertEqual([item.project_id for item in store.list()], ["p1"])
            self.assertFalse(store._db.in_transaction, "열고 나서 열린 트랜잭션(잠금)이 남지 않았다")
        self.assertLess(time.monotonic() - started, 3)
        holder.execute("ROLLBACK")

    def test_a_file_with_an_unfinished_save_left_by_a_crash_is_reported_as_such_and_left_alone_and_a_normal_open_cleans_it_up(self):
        path = self.dir / "crashed" / "chanceblog.db"
        with Store.open(path) as store:
            store.save(project("p1"))
        with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
            db.execute("BEGIN")
            db.executemany("INSERT INTO drafts (project_id, text, saved_at) VALUES (?, ?, ?)", [(f"d{number}", "y" * 500, NOW) for number in range(3000)])
            db.execute("COMMIT")
        crash = "\n".join(["import os, sqlite3, sys", "c = sqlite3.connect(sys.argv[1], isolation_level=None)", "c.execute('PRAGMA cache_size = 5')", "c.execute('BEGIN IMMEDIATE')",
                           "for n in range(3000):", "    c.execute('UPDATE drafts SET text = ? WHERE project_id = ?', ('z' * 500, 'd%d' % n))", "os._exit(9)"])
        done = subprocess.run([sys.executable, "-c", crash, str(path)], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 9, done.stderr)
        journal = Path(str(path) + "-journal")
        self.assertTrue(journal.is_file() and journal.stat().st_size > 0, "쓰다 죽어서 끝내지 못한 저장(저널)이 남았다")
        before = (digest(path), digest(journal), self.names(path))
        error = self.refuses("STORE_RECOVERY_PENDING", Store.open, path, migrate=False)
        self.assertIn("chanceblog.db", error.rendered().message)
        self.assertIn("한 번 열면", error.rendered().action)
        self.assertEqual((digest(path), digest(journal), self.names(path)), before, "읽기 전용 열기는 파일도 저널도 건드리지 않았다")
        with Store.open(path) as store:                                   # 일반 열기는 읽으면서 끝내지 못한 저장을 되돌려 정리한다
            self.assertEqual([item.project_id for item in store.list()], ["p1"])
            self.assertEqual(store.check(), [])
            self.assertEqual({draft.text[:1] for draft in store.drafts()}, {"y"}, "끝내지 못한 고침은 없던 일이 됐다")
        self.assertFalse(journal.exists())
        with Store.open(path, migrate=False) as store:                   # 정리된 뒤에는 읽기 전용으로도 열린다
            self.assertEqual(len(store.drafts()), 3000)

    def test_only_a_journal_with_something_in_it_makes_a_readonly_failure_a_pending_recovery(self):
        path = self.old_file()
        journal = Path(str(path) + "-journal")
        readonly = sqlite3.OperationalError("attempt to write a readonly database")
        with mock.patch.object(Store, "_verify", side_effect=readonly):
            self.refuses("FILE_WRITE_FAILED", Store.open, path, migrate=False)                    # 저널이 없으면 그냥 쓰기 실패다
            journal.write_bytes(b"")
            self.refuses("FILE_WRITE_FAILED", Store.open, path, migrate=False)                    # 비어 있는 저널도 남겨 둔 저장이 아니다
            journal.write_bytes(b"\x01" * 16)
            self.refuses("STORE_RECOVERY_PENDING", Store.open, path, migrate=False)
        with mock.patch.object(Store, "_verify", side_effect=sqlite3.OperationalError("database is locked")):
            self.refuses("STORE_LOCKED", Store.open, path, migrate=False)                          # 저널이 있어도 잠김은 잠김이다(쓰는 중인 다른 곳)
        self.assertEqual(journal.read_bytes(), b"\x01" * 16, "저널은 건드리지 않았다")

    def test_a_read_only_open_that_fails_for_another_reason_is_not_called_pending_recovery(self):
        path = self.old_file()
        journal = Path(str(path) + "-journal")
        journal.write_bytes(b"\x00" * 16)                               # 저널 흉내(내용 없는 것) — SQLite 가 뜨겁다고 보지 않는다
        with Store.open(path, migrate=False) as store:
            self.assertEqual(store.check(), [])
        self.assertTrue(journal.exists())
        holder = sqlite3.connect(str(path), isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN EXCLUSIVE")
        self.refuses("STORE_LOCKED", Store.open, path, migrate=False, busy_seconds=0.2)                # 쓰는 중인 파일은 '잠김' 이다
        holder.execute("ROLLBACK")

    def test_a_backup_can_still_be_taken_from_a_read_only_store(self):
        path = self.old_file()
        before = self.stat_of(path)
        with Store.open(path, migrate=False) as store:
            made = store.backup(self.dir / "backups")
        self.assertEqual(self.stat_of(path), before)
        self.assertEqual(pragma(made, "user_version"), 1)


if __name__ == "__main__":
    unittest.main()
