"""WAL 머리표시(18·19번째 바이트가 2)를 가진 들어오는 보관함을 거절하는 시험 — AS-S1 권고-2(결정 D-609).

위협(감사 탐침 p1·p1b): 앱은 롤백 저널 방식(`delete`)의 보관함만 만든다. WAL 머리의 파일이 복원으로 들어오면
  · 새 경로(전체 복원)는 '읽기만 한다' 면서 **읽기 전용으로 열기만 해도** SQLite 가 백업 폴더에 `-wal`·`-shm` 을 만들고, 두 번째 확인이 그 짝 파일 때문에 `FULL_BACKUP_INVALID files` 로 우연히 거절해
    그 폴더가 영구히 깨진 것으로 보이며(정리도 못 한다),
  · 옛 경로(`Store.restore_from`·`topics restore`)는 받아서 복원 뒤 지금 보관함 머리가 (2, 2) 로 남고 원본 백업 폴더에도 짝 파일이 생긴다.
지키는 것: 들어오는 파일은 SQLite 로 **열기 전에** 머리 바이트로 보고 거절한다(전체 복원은 `FULL_BACKUP_INVALID` 이유 `structure`, 옛 복원은 각자의 '온전한 백업이 아님' 오류) — 백업 폴더에는 아무것도 생기지 않고 지금 데이터도
바뀌지 않는다. 롤백 저널 방식 파일은 그대로 받는다. 네트워크·실제 시계 없이 돈다.
"""
import contextlib
import datetime
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import test_service_backup_restore as tr  # noqa: E402
import test_topicdb_backup as tb  # noqa: E402

from chanceblog_desktop.content import store as cstore  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402
from chanceblog_desktop.topicdb import backup as tbackup  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

MAGIC = b"SQLite format 3" + bytes([0])


def header18_19(path):
    with open(path, "rb") as handle:
        head = handle.read(20)
    return head[18], head[19]


def make_wal(path):
    """그 보관함 파일을 WAL 방식으로 바꾼다(머리 바이트 18·19 가 2·2) — 짝 파일은 지워 '깨끗한' WAL 머리 파일만 남긴다."""
    path = Path(path)
    with contextlib.closing(sqlite3.connect(str(path))) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    for suffix in ("-wal", "-shm", "-journal"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    assert header18_19(path) == (2, 2)
    return path


def listing(folder):
    return sorted(entry.name for entry in Path(folder).iterdir())


def head_bytes(write, read):
    return MAGIC + bytes([0, 0, write, read]) + bytes([0] * 8)


class HeaderFunctionTest(unittest.TestCase):
    def test_only_the_wal_numbers_in_the_two_version_bytes_of_a_sqlite_header_count(self):
        cases = {(1, 1): False, (2, 2): True, (1, 2): True, (2, 1): True, (0, 0): False, (3, 3): False, (255, 1): False}
        for (write, read), expected in cases.items():
            with self.subTest(write=write, read=read):
                self.assertEqual(cstore.wal_in_head(head_bytes(write, read)), expected)

    def test_text_that_is_not_a_sqlite_header_or_is_too_short_is_not_wal(self):
        for head in (b"", b"SQLite format 3", b"x" * 100, b"\x00" * 20, b"SQLite format 4" + bytes([0]) + bytes([0, 0, 2, 2]) + bytes(8), head_bytes(2, 2)[:19]):
            with self.subTest(head=head[:20]):
                self.assertFalse(cstore.wal_in_head(head))

    def test_a_real_wal_file_a_real_rollback_file_a_missing_path_and_a_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            wal = make_wal(Path(tmp) / "wal.db")
            plain = Path(tmp) / "plain.db"
            with contextlib.closing(sqlite3.connect(str(plain))) as connection:
                connection.execute("CREATE TABLE t (x)")
                connection.commit()
            self.assertTrue(cstore.wal_header(wal))
            self.assertFalse(cstore.wal_header(plain))
            self.assertFalse(cstore.wal_header(Path(tmp) / "missing.db"))
            self.assertFalse(cstore.wal_header(Path(tmp)), "폴더는 읽을 수 없으니 거짓 — 그 뒤의 열기가 자기 오류를 낸다")
            self.assertEqual(listing(tmp), ["plain.db", "wal.db"], "머리를 읽어도 곁에 아무 파일도 만들지 않는다")

    def test_the_function_reads_bytes_only_it_never_opens_the_file_with_sqlite(self):
        import inspect
        source = inspect.getsource(cstore.wal_header) + inspect.getsource(cstore.wal_in_head)
        self.assertNotIn("sqlite3.connect", source)
        self.assertIn('"rb"', source)


class FullRestoreWalTest(tr.Base):
    """전체 복원 — 감사 탐침 p1."""

    BACKUP_NAME = "full-20200101-000000"

    def setUp(self):
        super().setUp()
        self.outcome = self.world.backup()
        tr.change_everything(self.world)
        self.before = tr.state_of(self.world)

    def wal_backup(self, databases):
        source = self.ctx.workspace.backups_dir / self.outcome.row.name
        target = self.ctx.workspace.backups_dir / self.BACKUP_NAME
        shutil.copytree(source, target)
        manifest = json.loads((target / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        for name in databases:
            make_wal(target / name)
            data = (target / name).read_bytes()
            manifest["files"][name].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        bs.write_manifest(target, manifest)
        return target

    def test_a_backup_whose_databases_carry_the_wal_header_is_refused_as_a_structure_problem_and_the_folder_stays_untouched(self):
        for databases in (("chanceblog.db", layout.ENGINE_DB_FILE), ("chanceblog.db",), (layout.ENGINE_DB_FILE,)):
            with self.subTest(databases=databases):
                target = self.wal_backup(databases)
                try:
                    entries = listing(target)
                    error = bs.code_of(bf.restore_full_backup, self.ctx, self.BACKUP_NAME, confirmed=True)
                    self.assertIsNotNone(error)
                    self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "structure"), error.detail)
                    self.assertIn("WAL", error.detail)
                    self.assertEqual(listing(target), entries, "거절한 뒤 백업 폴더에 `-wal`·`-shm` 이 생겼다 — 읽기만 해야 한다")
                    self.assertEqual(tr.state_of(self.world), self.before)
                    self.assertFalse(self.safety_root().exists() and list(self.safety_root().iterdir()), "안전 사본을 만들기 전에 멈춘다")
                    self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()) if self.ctx.workspace.locks_dir.is_dir() else [], [], "잠금도 잡기 전에 멈춘다")
                finally:
                    shutil.rmtree(target)

    def test_the_refused_folder_is_not_turned_into_a_broken_folder_by_the_refusal_and_a_normal_backup_still_restores(self):
        target = self.wal_backup(("chanceblog.db",))
        bs.code_of(bf.restore_full_backup, self.ctx, self.BACKUP_NAME, confirmed=True)
        row = next(row for row in bf.list_full_backups(self.ctx).rows if row.name == self.BACKUP_NAME)
        self.assertNotEqual(row.status, bf.STATUS_BROKEN, "거절이 폴더를 영구히 깨진 것으로 만들었다(옛 동작: 짝 파일 때문에 files 불일치)")
        self.assertEqual(listing(target), sorted([bf.MANIFEST_NAME, *self.world.manifest(self.outcome)["files"]]))
        result = bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)


class OldRestoreWalTest(unittest.TestCase):
    """옛 복원 길 — 감사 탐침 p1b."""

    def test_the_single_file_store_restore_refuses_a_wal_backup_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with cstore.Store.open(root / "live" / "chanceblog.db"):
                pass
            with cstore.Store.open(root / "other" / "chanceblog.db"):
                pass
            wal = make_wal(root / "other" / "chanceblog.db")
            live = root / "live" / "chanceblog.db"
            before_header, before_dir, before_source_dir = header18_19(live), listing(live.parent), listing(wal.parent)
            with cstore.Store.open(live) as store:
                with self.assertRaises(AppError) as caught:
                    store.restore_from(wal)
            self.assertEqual(caught.exception.code, "STORE_CORRUPT")
            self.assertIn("WAL", caught.exception.detail)
            self.assertEqual(header18_19(live), before_header, "지금 보관함이 조용히 WAL 이 됐다")
            self.assertEqual(listing(live.parent), before_dir)
            self.assertEqual(listing(wal.parent), before_source_dir, "원본 백업 곁에 짝 파일이 생겼다")

    def test_the_old_restore_command_refuses_a_wal_backup_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = bs.World(tmp)
            backup = projects.backup_store(world.ctx)
            make_wal(backup)
            before = tr.state_of(world)
            directory = listing(backup.parent)
            error = bs.code_of(projects.restore_store, world.ctx, backup, confirmed=True)
            self.assertIsNotNone(error)
            self.assertEqual(error.code, "STORE_CORRUPT")
            self.assertEqual(tr.state_of(world), before)
            self.assertEqual(header18_19(world.path("chanceblog.db")), (1, 1))
            self.assertEqual([name for name in listing(backup.parent) if name.endswith(("-wal", "-shm"))], [])
            self.assertEqual([name for name in listing(backup.parent) if name not in directory and not name.startswith("before-")], [], "백업 폴더에 새 파일이 생겼다")

    def test_the_topic_engine_file_restore_refuses_a_wal_backup_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with TopicStore.open(root / "live" / layout.ENGINE_DB_FILE):
                pass
            with TopicStore.open(root / "other" / layout.ENGINE_DB_FILE):
                pass
            wal = make_wal(root / "other" / layout.ENGINE_DB_FILE)
            live = root / "live" / layout.ENGINE_DB_FILE
            before_header, before_dir, before_source_dir = header18_19(live), listing(live.parent), listing(wal.parent)
            with TopicStore.open(live) as store:
                with self.assertRaises(AppError) as caught:
                    store.restore_from(wal)
            self.assertEqual(caught.exception.code, "TOPIC_BACKUP_INVALID")
            self.assertEqual(header18_19(live), before_header)
            self.assertEqual(listing(live.parent), before_dir)
            self.assertEqual(listing(wal.parent), before_source_dir)

    def test_topics_restore_refuses_a_wal_backup_before_opening_it_and_leaves_the_backup_folder_and_the_live_store_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = tb.World(tmp)
            made = world.backup().path
            crafted = made.parent / "topic-20200101-000000"
            shutil.copytree(made, crafted)
            database = crafted / layout.ENGINE_DB_FILE
            make_wal(database)
            manifest = json.loads((crafted / tbackup.MANIFEST_NAME).read_text(encoding="utf-8"))
            data = database.read_bytes()
            manifest["files"][layout.ENGINE_DB_FILE] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            (crafted / tbackup.MANIFEST_NAME).write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            live = world.data / layout.ENGINE_DB_FILE
            before = (listing(crafted), header18_19(live), tb.digests(world.data))
            with self.assertRaises(AppError) as caught:
                tbackup.restore_backup(crafted, world.data, world.backups, now=tb.NOW + datetime.timedelta(minutes=5))
            self.assertEqual(caught.exception.code, "TOPIC_BACKUP_INVALID")
            self.assertEqual((listing(crafted), header18_19(live), tb.digests(world.data)), before, "거절했는데 백업 폴더·지금 데이터가 바뀌었다")
            with self.assertRaises(AppError):
                tbackup.read_backup(crafted)
            self.assertEqual(listing(crafted), before[0], "읽어 보기만 해도 짝 파일이 생기면 안 된다")


class NormalBackupsStayAcceptedTest(tr.Base):
    def test_rollback_journal_backups_restore_exactly_as_before(self):
        outcome = self.world.backup()
        saved = tr.state_of(self.world)
        tr.change_everything(self.world)
        for name in ("chanceblog.db", layout.ENGINE_DB_FILE):
            self.assertEqual(header18_19(self.ctx.workspace.backups_dir / outcome.row.name / name), (1, 1))
        result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(tr.state_of(self.world), saved)
        for name in ("chanceblog.db", layout.ENGINE_DB_FILE):
            self.assertEqual(header18_19(self.world.path(name)), (1, 1))


if __name__ == "__main__":
    unittest.main()
