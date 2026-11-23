"""복원이 보관함을 덮어쓴 **뒤에** '판 올리기(`_prepare`)' 가 실패해도 지금 보관함이 원래대로 남는 것을 지키는 시험 — AS-S1 필수-4(결정 D-606).

위협(감사 탐침 p5): SQLite 백업 호출이 지금 보관함을 한 번에 덮은 직후 판 올리기가 실패하면(마이그레이션 사본 이름 20개가 모두 쓰이는 중·디스크 가득·경로 259자 초과·읽기 전용 폴더 …)
예전에는 예외가 `_restore_database` 밖으로 나가 `db_done` 에 들어가지 못했고 `_roll_back` 이 그 보관함을 건너뛰었다. 지금 보관함은 '복사된 백업 내용' 으로 남고, notes 는 비고, 표지는 지워지고,
사용자에게는 '원래대로 돌려 두었어요' 가 나갔다.

지키는 것(겹이 셋 — 안쪽부터):
  1) 낮은 층(`Store.restore_from`·`EngineFile.restore_from`): 덮기 **전에** 지금 내용을 메모리에 담고(담지 못하면 덮지 않는다), 덮은 뒤 무슨 일이 나도 그 사본으로 되돌린다. 되돌리지 못하면 오류에 `left_overwritten` 표시를 남긴다.
     옛 `restore` 명령(`projects.restore_store`)과 주제 엔진 복원(`topicdb.backup`)도 이 낮은 층을 거치므로 같은 틈이 막힌다.
  2) 전체 복원 흐름(`backup_flow._apply`·`_roll_back`): `left_overwritten` 표시가 있는 보관함은 '바꾼 것' 으로 세어 안전 사본에서 되돌리고, 되돌린 뒤 지금 보관함이 안전 사본과 같은지 확인해 다르면 notes 에 넣고 표지를 남긴다.
     덮이지 않은 채 실패한 보관함은 건드리지 않는다(다른 창이 그 사이 쓴 내용을 안전 사본으로 덮어 잃지 않게).
  3) 주제 엔진 복원(`topicdb.backup.restore_backup`): 덮인 채 남았으면 직전 상태 백업에서 되돌리고, 못 하면 이름을 알린다.
네트워크·실제 시계·실제 자격 증명 관리자 없이 돈다. 결함 주입은 `Store._prepare` 를 덮은 뒤에만 실패하게 하는 것과 감사 탐침 p5 처럼 실제로 사본 이름 스무 개를 채우는 것 둘이다.
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import test_service_backup_restore as tr  # noqa: E402
import test_topicdb_backup as tb  # noqa: E402

from chanceblog_desktop.content import store as cstore  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topicdb import backup as tbackup  # noqa: E402
from chanceblog_desktop.topicdb import file as tfile  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402


def _marked(error):
    """그 예외에 '덮인 채 남았다' 표시를 단다(낮은 층이 되돌리지 못했을 때의 모양)."""
    error.left_overwritten = True
    return error


class BrokenUndo:
    """메모리 사본인 척하지만 되돌리기(`backup`)가 늘 실패하는 가짜 — 되돌리기 자체가 실패하는 길을 시험한다."""

    def backup(self, target):
        raise sqlite3.OperationalError("disk I/O error")

    def close(self):
        pass


def make_store_file(path, text):
    """글 보관함 파일 하나 — 저장한 초안 한 줄(`text`)이 든다."""
    with cstore.Store.open(path):
        pass
    with contextlib.closing(sqlite3.connect(str(path))) as connection:
        connection.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES ('p1', ?, '2026-11-23T00:00:00Z')", (text,))
        connection.commit()
    return path


def drafts_of(path):
    with contextlib.closing(sqlite3.connect(cstore._read_only_uri(Path(path)), uri=True)) as connection:
        return [row[0] for row in connection.execute("SELECT text FROM drafts ORDER BY project_id")]


def make_engine_file(path, kind):
    """주제 엔진 보관함 파일 하나 — 점검 기록 한 줄(`kind`)이 든다."""
    with TopicStore.open(path):
        pass
    with contextlib.closing(sqlite3.connect(str(path))) as connection:
        connection.execute("INSERT INTO review_log (kind, last_run_on) VALUES (?, '2026-11-23')", (kind,))
        connection.commit()
    return path


def reviews_of(path):
    with contextlib.closing(sqlite3.connect(cstore._read_only_uri(Path(path)), uri=True)) as connection:
        return [row[0] for row in connection.execute("SELECT kind FROM review_log ORDER BY kind")]


def user_version(path):
    with contextlib.closing(sqlite3.connect(cstore._read_only_uri(Path(path)), uri=True)) as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0]


def make_v1_store_file(path, text):
    """판 1 모양의 글 보관함(초안 한 줄) — 열면 판 2 로 올려야 하는 옛 백업."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(str(path))) as connection:
        for statement in cstore._SCHEMA[:4]:
            connection.execute(statement)
        connection.execute(f"PRAGMA application_id = {cstore.APPLICATION_ID}")
        connection.execute("PRAGMA user_version = 1")
        connection.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES ('p1', ?, '2026-11-23T00:00:00Z')", (text,))
        connection.commit()
    return path


def occupy_copy_names(live_path, version=1):
    """감사 탐침 p5 처럼 마이그레이션 사본 이름 스무 개(`.v1.bak` … `.v1.20.bak`)를 서로 다른 내용으로 모두 채운다 — 판 올리기가 사본을 만들 자리가 없다."""
    for number in range(1, cstore.MAX_COPY_NAMES + 1):
        name = f"{live_path.name}.v{version}.bak" if number == 1 else f"{live_path.name}.v{version}.{number}.bak"
        (live_path.parent / name).write_bytes(b"not the same content " + str(number).encode())


class StoreRestoreFromTest(unittest.TestCase):
    """글 보관함 낮은 층 — `Store.restore_from` 은 덮은 뒤 실패해도 지금 내용으로 되돌리고, 못 되돌리면 표시를 남긴다."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.live = make_store_file(self.root / "live" / "chanceblog.db", "LIVE")
        self.backup = make_store_file(self.root / "backup" / "chanceblog.db", "BACKUP")

    def arm_prepare_failure(self, seen, exception=None):
        real = cstore.Store._prepare

        def failing(this, fresh):
            if seen.get("armed"):
                seen["armed"] = False
                seen["during"] = [row[0] for row in this._db.execute("SELECT text FROM drafts")]
                if exception is not None:
                    raise exception()
                raise AppError("MIGRATION_BLOCKED", {"이유": "일부러 낸 실패"}, detail="덮은 뒤의 판 올리기 실패")
            return real(this, fresh)
        return mock.patch.object(cstore.Store, "_prepare", failing)

    def test_a_keyboard_interrupt_or_a_system_exit_after_the_copy_also_puts_the_current_content_back_and_is_raised_again(self):
        """AS2 시험 렌즈 Q 필수-4(D-619) — `except BaseException` 을 `except Exception` 으로 바꿔도 초록이던 변이(Q19)를 죽인다: 덮은 뒤 `Exception` 이 아닌 `BaseException`(`KeyboardInterrupt`·`SystemExit`)이 나도
        지금 내용으로 되돌리고, 되돌린 뒤 그 예외를 삼키지 않고 그대로 다시 던진다."""
        for factory in (lambda: KeyboardInterrupt("일부러 낸 중단"), lambda: SystemExit(3)):
            kind = type(factory())
            with self.subTest(kind=kind.__name__):
                seen = {}
                with self.arm_prepare_failure(seen, factory):
                    with cstore.Store.open(self.live) as store:
                        store.undo_failed_restore = True
                        seen["armed"] = True
                        with self.assertRaises(kind) as caught:
                            store.restore_from(self.backup)
                        self.assertEqual(drafts_of(self.live), ["LIVE"], "열려 있는 저장소도 원래 내용이다")
                self.assertEqual(seen["during"], ["BACKUP"], "시험의 전제 — 중단이 난 순간 지금 보관함은 이미 백업 내용으로 덮여 있었다")
                self.assertFalse(getattr(caught.exception, "left_overwritten", False), "되돌렸으면 '덮인 채 남았다' 표시가 없다")
                with cstore.Store.open(self.live) as again:
                    self.assertEqual(again.check(), [])

    def test_a_keyboard_interrupt_when_the_undo_is_impossible_carries_the_overwritten_mark_and_is_still_raised(self):
        seen = {}
        with self.arm_prepare_failure(seen, lambda: KeyboardInterrupt("일부러 낸 중단")), mock.patch.object(cstore, "hold_in_memory", lambda connection: BrokenUndo()):
            with cstore.Store.open(self.live) as store:
                store.undo_failed_restore = True
                seen["armed"] = True
                with self.assertRaises(KeyboardInterrupt) as caught:
                    store.restore_from(self.backup)
        self.assertTrue(getattr(caught.exception, "left_overwritten", False), "되돌리지 못했으면 중단에도 표시가 달려야 복원 흐름이 안전 사본에서 되돌린다")
        self.assertEqual(drafts_of(self.live), ["BACKUP"], "시험의 전제 — 되돌리기가 실패해 백업 내용으로 남았다")

    def test_a_prepare_failure_after_the_copy_puts_the_current_content_back(self):
        seen = {}
        with self.arm_prepare_failure(seen):
            with cstore.Store.open(self.live) as store:
                store.undo_failed_restore = True
                seen["armed"] = True
                with self.assertRaises(AppError) as caught:
                    store.restore_from(self.backup)
                self.assertEqual(drafts_of(self.live), ["LIVE"], "열려 있는 저장소도 원래 내용이다")
        self.assertEqual(seen["during"], ["BACKUP"], "시험의 전제 — 실패하는 순간 지금 보관함은 이미 백업 내용으로 덮여 있었다")
        self.assertEqual(caught.exception.code, "MIGRATION_BLOCKED")
        self.assertEqual(drafts_of(self.live), ["LIVE"], "덮은 뒤 실패했는데 지금 보관함이 백업 내용으로 남았다")
        self.assertFalse(getattr(caught.exception, "left_overwritten", False), "되돌렸으면 '덮인 채 남았다' 표시가 없다")
        with cstore.Store.open(self.live) as again:                       # 다시 열어도 멀쩡하다
            self.assertEqual(again.check(), [])

    def test_by_default_the_old_behaviour_stays_the_restored_content_remains_and_the_error_carries_the_overwritten_mark(self):
        """되돌리기는 켠 쪽(전체 복원·옛 `restore` 명령)만 쓴다 — 기본은 기존 시험(`test_content_migration`)이 못박은 옛 동작이다: 판 올리기가 실패해도 복구한 내용이 남고 저장소는 계속 쓸 수 있다. 다만 '덮인 채 남았다' 는 표시는 단다."""
        seen = {}
        with self.arm_prepare_failure(seen), mock.patch.object(cstore, "hold_in_memory", side_effect=AssertionError("기본에서는 지금 내용을 담지 않는다")):
            with cstore.Store.open(self.live) as store:
                self.assertFalse(store.undo_failed_restore)
                seen["armed"] = True
                with self.assertRaises(AppError) as caught:
                    store.restore_from(self.backup)
                self.assertFalse(store._db.in_transaction)
                self.assertEqual([row[0] for row in store._db.execute("SELECT text FROM drafts")], ["BACKUP"])
        self.assertTrue(caught.exception.left_overwritten)
        self.assertEqual(drafts_of(self.live), ["BACKUP"])

    def test_the_real_p5_trigger_a_version_one_backup_with_every_copy_name_taken_leaves_the_current_store_untouched(self):
        v1 = make_v1_store_file(self.root / "v1" / "chanceblog.db", "OLD-BACKUP")
        occupy_copy_names(self.live)
        with cstore.Store.open(self.live) as store:
            store.undo_failed_restore = True
            with self.assertRaises(AppError) as caught:
                store.restore_from(v1)
        self.assertEqual(caught.exception.code, "MIGRATION_BLOCKED")
        self.assertEqual(drafts_of(self.live), ["LIVE"])
        self.assertEqual(user_version(self.live), cstore.SCHEMA_VERSION, "판도 원래대로(2)다 — 백업의 판 1 이 남지 않았다")

    def test_a_failed_undo_leaves_the_mark_and_a_snapshot_that_cannot_be_taken_means_no_overwrite_at_all(self):
        seen = {}
        with self.arm_prepare_failure(seen), mock.patch.object(cstore, "hold_in_memory", lambda connection: BrokenUndo()):
            with cstore.Store.open(self.live) as store:
                store.undo_failed_restore = True
                seen["armed"] = True
                with self.assertRaises(AppError) as caught:
                    store.restore_from(self.backup)
        self.assertTrue(getattr(caught.exception, "left_overwritten", False), "되돌리지 못했으면 표시가 있어야 복원 흐름이 안전 사본에서 되돌린다")
        self.assertEqual(drafts_of(self.live), ["BACKUP"], "시험의 전제 — 되돌리기가 실패해 백업 내용으로 남았다")
        make_store_file(self.root / "live2" / "chanceblog.db", "LIVE2")
        with mock.patch.object(cstore, "hold_in_memory", side_effect=sqlite3.OperationalError("database is locked")):
            with cstore.Store.open(self.root / "live2" / "chanceblog.db") as store:
                store.undo_failed_restore = True
                with self.assertRaises(AppError) as locked:
                    store.restore_from(self.backup)
        self.assertEqual(locked.exception.code, "STORE_LOCKED")
        self.assertEqual(drafts_of(self.root / "live2" / "chanceblog.db"), ["LIVE2"], "지금 내용을 담지 못하면 덮지 않는다")
        self.assertFalse(getattr(locked.exception, "left_overwritten", False))

    def test_a_restore_that_works_is_unchanged_and_a_refused_backup_still_changes_nothing(self):
        with cstore.Store.open(self.live) as store:
            store.restore_from(self.backup)
        self.assertEqual(drafts_of(self.live), ["BACKUP"])
        broken = self.root / "broken.db"
        broken.write_bytes(b"this is not a database " * 40)
        with cstore.Store.open(self.live) as store:
            with self.assertRaises(AppError):
                store.restore_from(broken)
        self.assertEqual(drafts_of(self.live), ["BACKUP"])

    def test_the_snapshot_and_the_undo_never_leave_a_file_or_a_connection_behind(self):
        before = sorted(path.name for path in self.live.parent.iterdir())
        seen = {}
        with self.arm_prepare_failure(seen):
            with cstore.Store.open(self.live) as store:
                store.undo_failed_restore = True
                seen["armed"] = True
                with self.assertRaises(AppError):
                    store.restore_from(self.backup)
        self.assertEqual(sorted(path.name for path in self.live.parent.iterdir()), before, "메모리 사본이라 폴더에 새 파일이 없다")

    def test_the_shared_comparison_helper_tells_equal_from_different_and_tolerates_a_newer_version(self):
        same = make_store_file(self.root / "same" / "chanceblog.db", "LIVE")
        self.assertTrue(cstore.same_database(self.live, same))
        self.assertFalse(cstore.same_database(self.live, self.backup))
        older = make_v1_store_file(self.root / "older" / "chanceblog.db", "LIVE")
        self.assertTrue(cstore.same_database(older, self.live), "판이 다르면 판이 낮은 쪽의 표마다 행 수가 같을 때 같다")
        different_rows = make_v1_store_file(self.root / "older2" / "chanceblog.db", "LIVE")
        with contextlib.closing(sqlite3.connect(str(different_rows))) as connection:
            connection.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES ('p2', 'extra', '2026-11-23T00:00:00Z')")
            connection.commit()
        self.assertFalse(cstore.same_database(different_rows, self.live))
        with self.assertRaises((sqlite3.Error, OSError)):
            cstore.same_database(self.live, self.root / "none" / "missing.db")


class EngineRestoreFromTest(unittest.TestCase):
    """주제 엔진 낮은 층 — `EngineFile.restore_from` 도 같다."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.live = make_engine_file(self.root / "live" / layout.ENGINE_DB_FILE, "LIVE")
        self.backup = make_engine_file(self.root / "backup" / layout.ENGINE_DB_FILE, "BACKUP")

    def arm_prepare_failure(self, seen, exception=None):
        real = tfile.EngineFile._prepare

        def failing(this, fresh):
            if seen.get("armed"):
                seen["armed"] = False
                seen["during"] = [row[0] for row in this._db.execute("SELECT kind FROM review_log")]
                if exception is not None:
                    raise exception()
                raise AppError("MIGRATION_BLOCKED", {"이유": "일부러 낸 실패"}, detail="덮은 뒤의 판 올리기 실패")
            return real(this, fresh)
        return mock.patch.object(tfile.EngineFile, "_prepare", failing)

    def test_a_keyboard_interrupt_or_a_system_exit_after_the_copy_also_puts_the_current_content_back_and_is_raised_again(self):
        """주제 엔진 쪽 같은 시험(AS2 시험 렌즈 Q 필수-4, D-619) — `EngineFile.restore_from` 의 `except BaseException` 을 지킨다."""
        for factory in (lambda: KeyboardInterrupt("일부러 낸 중단"), lambda: SystemExit(3)):
            kind = type(factory())
            with self.subTest(kind=kind.__name__):
                seen = {}
                with self.arm_prepare_failure(seen, factory):
                    with TopicStore.open(self.live) as store:
                        store.undo_failed_restore = True
                        seen["armed"] = True
                        with self.assertRaises(kind) as caught:
                            store.restore_from(self.backup)
                self.assertEqual(seen["during"], ["BACKUP"], "시험의 전제 — 중단이 난 순간 이미 덮여 있었다")
                self.assertEqual(reviews_of(self.live), ["LIVE"], "덮은 뒤 중단됐는데 주제 보관함이 백업 내용으로 남았다")
                self.assertFalse(getattr(caught.exception, "left_overwritten", False))
                with TopicStore.open(self.live) as again:
                    self.assertEqual(again.check(), [])

    def test_a_keyboard_interrupt_when_the_undo_is_impossible_carries_the_overwritten_mark_and_is_still_raised(self):
        seen = {}
        with self.arm_prepare_failure(seen, lambda: KeyboardInterrupt("일부러 낸 중단")), mock.patch.object(tfile, "hold_in_memory", lambda connection: BrokenUndo()):
            with TopicStore.open(self.live) as store:
                store.undo_failed_restore = True
                seen["armed"] = True
                with self.assertRaises(KeyboardInterrupt) as caught:
                    store.restore_from(self.backup)
        self.assertTrue(getattr(caught.exception, "left_overwritten", False))
        self.assertEqual(reviews_of(self.live), ["BACKUP"], "시험의 전제 — 되돌리기가 실패해 덮인 채 남았다")

    def test_a_prepare_failure_after_the_copy_puts_the_current_content_back(self):
        seen = {}
        with self.arm_prepare_failure(seen):
            with TopicStore.open(self.live) as store:
                store.undo_failed_restore = True
                seen["armed"] = True
                with self.assertRaises(AppError) as caught:
                    store.restore_from(self.backup)
        self.assertEqual(seen["during"], ["BACKUP"], "시험의 전제 — 실패하는 순간 이미 덮여 있었다")
        self.assertEqual(reviews_of(self.live), ["LIVE"], "덮은 뒤 실패했는데 주제 보관함이 백업 내용으로 남았다")
        self.assertFalse(getattr(caught.exception, "left_overwritten", False))
        with TopicStore.open(self.live) as again:
            self.assertEqual(again.check(), [])

    def test_a_failed_undo_leaves_the_mark_and_an_untakeable_snapshot_means_no_overwrite(self):
        seen = {}
        with self.arm_prepare_failure(seen), mock.patch.object(tfile, "hold_in_memory", lambda connection: BrokenUndo()):
            with TopicStore.open(self.live) as store:
                store.undo_failed_restore = True
                seen["armed"] = True
                with self.assertRaises(AppError) as caught:
                    store.restore_from(self.backup)
        self.assertTrue(getattr(caught.exception, "left_overwritten", False))
        self.assertEqual(reviews_of(self.live), ["BACKUP"], "시험의 전제 — 되돌리기가 실패해 덮인 채 남았다")
        other = make_engine_file(self.root / "other" / layout.ENGINE_DB_FILE, "OTHER")
        with mock.patch.object(tfile, "hold_in_memory", side_effect=sqlite3.OperationalError("database is locked")):
            with TopicStore.open(other) as store:
                store.undo_failed_restore = True
                with self.assertRaises(AppError) as locked:
                    store.restore_from(self.backup)
        self.assertEqual(locked.exception.code, "TOPIC_STORE_LOCKED")
        self.assertEqual(reviews_of(other), ["OTHER"], "지금 내용을 담지 못하면 덮지 않는다")

    def test_a_restore_that_works_is_unchanged(self):
        with TopicStore.open(self.live) as store:
            store.restore_from(self.backup)
        self.assertEqual(reviews_of(self.live), ["BACKUP"])

    def test_by_default_the_restored_content_remains_and_the_error_carries_the_overwritten_mark(self):
        seen = {}
        with self.arm_prepare_failure(seen), mock.patch.object(tfile, "hold_in_memory", side_effect=AssertionError("기본에서는 지금 내용을 담지 않는다")):
            with TopicStore.open(self.live) as store:
                self.assertFalse(store.undo_failed_restore)
                seen["armed"] = True
                with self.assertRaises(AppError) as caught:
                    store.restore_from(self.backup)
        self.assertTrue(caught.exception.left_overwritten)
        self.assertEqual(reviews_of(self.live), ["BACKUP"])


class FlowPostCopyTest(tr.Base):
    """전체 복원 흐름 — 감사 탐침 p5 모양과 결함 주입."""

    BACKUP_NAME = "full-20200101-000000"

    def setUp(self):
        super().setUp()
        self.outcome = self.world.backup()
        tr.change_everything(self.world)
        with contextlib.closing(sqlite3.connect(str(self.world.path("chanceblog.db")))) as connection:
            connection.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES ('liveproj', 'LIVE-MARKER', '2026-11-23T00:00:00Z')")
            connection.commit()
        self.before = tr.state_of(self.world)

    def v1_backup(self):
        """판 1 모양의 글 보관함이 든 백업 폴더 — 목록의 크기·해시를 다시 맞췄다(조작한 사람이 하는 일)."""
        source = self.ctx.workspace.backups_dir / self.outcome.row.name
        target = self.ctx.workspace.backups_dir / self.BACKUP_NAME
        shutil.copytree(source, target)
        (target / "chanceblog.db").unlink()
        make_v1_store_file(target / "chanceblog.db", "OLD-BACKUP")
        manifest = json.loads((target / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        data = (target / "chanceblog.db").read_bytes()
        manifest["files"]["chanceblog.db"].update(size=len(data), sha256=hashlib.sha256(data).hexdigest(), items={"drafts": 1, "projects": 0, "revisions": 0})
        bs.write_manifest(target, manifest)
        return self.BACKUP_NAME

    def failing_restore(self, error_text="덮은 뒤 실패", mark=True, exception=None):
        """`Store.restore_from` 을 '지금 보관함을 덮은 뒤 실패하고 되돌리지도 못하는' 것으로 바꾼다(첫 호출만 — 되돌리기의 호출은 진짜다). `exception` 은 `AppError` 대신 낼 예외를 만드는 함수다."""
        real = cstore.Store.restore_from
        calls = []

        def broken(this, backup, **kwargs):
            calls.append(Path(backup).parent.name)
            if len(calls) > 1:
                return real(this, backup, **kwargs)
            with contextlib.closing(sqlite3.connect(cstore._read_only_uri(Path(backup)), uri=True)) as source:
                source.backup(this._db)
            error = exception() if exception is not None else AppError("MIGRATION_BLOCKED", {"이유": "일부러 낸 실패"}, detail=error_text)
            if mark:
                error.left_overwritten = True
            raise error
        return mock.patch.object(cstore.Store, "restore_from", broken), calls

    def assert_original_and_clean(self, error):
        self.assertEqual(error.code, "RESTORE_FAILED")
        self.assertEqual(error.notes, ())
        self.assertEqual(tr.state_of(self.world), self.before, "복원이 실패했는데 지금 데이터가 원래대로가 아니다")
        self.assertFalse(bf._marker_path(self.ctx).exists(), "원래대로 돌렸는데 표지가 남았다")
        self.assertIsNone(bf.list_full_backups(self.ctx).interrupted)
        self.assertEqual(user_version(self.world.path("chanceblog.db")), cstore.SCHEMA_VERSION)

    def test_the_audit_probe_p5_a_version_one_backup_with_every_copy_name_taken_ends_with_the_current_data_intact(self):
        name = self.v1_backup()
        occupy_copy_names(self.world.path("chanceblog.db"))
        error = bs.code_of(bf.restore_full_backup, self.ctx, name, confirmed=True)
        self.assertIsNotNone(error)
        self.assertEqual((error.code, error.reason), ("RESTORE_FAILED", "other"))
        self.assertIn("MIGRATION_BLOCKED", error.detail)
        self.assertIn("LIVE-MARKER", "\n".join(bs.dump(self.world.path("chanceblog.db"))), "지금 보관함의 초안이 사라졌다")
        self.assertEqual(self.world.path("chanceblog.db").read_bytes()[:16], b"SQLite format 3\x00")
        self.assert_original_and_clean(error)
        safety = [row for row in bf.list_full_backups(self.ctx).rows if row.kind == "safety"]
        self.assertEqual(len(safety), 1, "안전 사본은 그대로 남아 있다")

    def test_a_prepare_failure_injected_after_the_copy_ends_with_the_current_data_intact(self):
        seen = {"armed": False, "restores": 0}
        real_prepare, real_restore = cstore.Store._prepare, cstore.Store.restore_from

        def restore(this, backup, **kwargs):
            seen["restores"] += 1
            seen["armed"] = seen["restores"] == 1                       # 첫 복원(앞으로 가는 길)만 실패하게 한다 — 되돌리는 호출은 진짜다
            return real_restore(this, backup, **kwargs)

        def prepare(this, fresh):
            if seen["armed"]:
                seen["armed"] = False
                seen["during"] = [row[0] for row in this._db.execute("SELECT text FROM drafts")]
                raise AppError("MIGRATION_FAILED", detail="덮은 뒤의 판 올리기 실패")
            return real_prepare(this, fresh)

        with mock.patch.object(cstore.Store, "restore_from", restore), mock.patch.object(cstore.Store, "_prepare", prepare):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertNotIn("LIVE-MARKER", seen["during"], "시험의 전제 — 실패하는 순간 보관함은 이미 백업 내용이었다")
        self.assert_original_and_clean(error)

    def test_when_the_low_layer_cannot_undo_the_flow_rolls_the_store_back_from_the_safety_copy(self):
        patch, calls = self.failing_restore()
        with patch:
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(len(calls), 2, "덮인 채 남은 보관함을 안전 사본에서 되돌렸다")
        self.assertEqual(calls[0], self.outcome.row.name)
        self.assertRegex(calls[1], bf.SAFETY_NAME.pattern)
        self.assert_original_and_clean(error)

    def test_a_keyboard_interrupt_after_the_overwrite_is_rolled_back_from_the_safety_copy_and_then_raised_again(self):
        """AS2 시험 렌즈 Q 필수-4(D-619) — 복원 흐름의 `except BaseException` 도 같다: 덮은 뒤 `KeyboardInterrupt`·`SystemExit` 이 나도(표시가 달려 있으면) 안전 사본에서 되돌리고 표지를 지운 뒤 그 예외를 다시 던진다."""
        for factory in (lambda: KeyboardInterrupt("일부러 낸 중단"), lambda: SystemExit(3)):
            kind = type(factory())
            with self.subTest(kind=kind.__name__):
                patch, calls = self.failing_restore(exception=lambda: _marked(factory()))
                with patch:
                    with self.assertRaises(kind):
                        bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True)
                self.assertEqual(len(calls), 2, "되돌리기가 안전 사본으로 한 번 더 불렀다")
                self.assertEqual(tr.state_of(self.world), self.before, "중단됐는데 지금 데이터가 원래대로가 아니다")
                self.assertFalse(bf._marker_path(self.ctx).exists(), "원래대로 돌렸는데 표지가 남았다")
                self.assertIsNone(bf.list_full_backups(self.ctx).interrupted)

    def test_an_error_without_the_overwritten_mark_is_not_rolled_back_so_another_windows_new_writes_survive(self):
        """덮이지 않은 채 실패한 보관함(예: 다른 곳이 쓰는 중)을 안전 사본으로 덮으면 그 사이 다른 창이 쓴 내용을 잃는다 — 표시가 없으면 건드리지 않는다."""
        real, calls = bf._restore_database, []

        def busy(component, path, source):
            calls.append(component.name)
            if component.name == "chanceblog.db":
                with contextlib.closing(sqlite3.connect(str(path))) as connection:
                    connection.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES ('other-window', 'OTHER-WINDOW-WRITE', '2026-11-23T00:00:00Z')")
                    connection.commit()
                raise AppError("STORE_LOCKED", detail="다른 곳에서 쓰는 중")
            return real(component, path, source)
        with mock.patch.object(bf, "_restore_database", busy):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "RESTORE_FAILED")
        self.assertEqual(error.notes, ())
        self.assertEqual(calls, ["chanceblog.db"], "되돌리기가 그 보관함을 다시 덮으려 하지 않았다")
        self.assertIn("OTHER-WINDOW-WRITE", "\n".join(bs.dump(self.world.path("chanceblog.db"))), "다른 창이 쓴 내용이 사라졌다")

    def test_when_even_the_rollback_of_an_overwritten_store_fails_the_name_is_told_and_the_marker_stays(self):
        patch, _calls = self.failing_restore()
        real, seen = bf._restore_database, []

        def flaky(component, path, source):
            seen.append(component.name)
            if len(seen) == 1:
                return real(component, path, source)                    # 앞으로 가는 길(진짜 — 덮은 뒤 표시가 달린 오류로 끝난다)
            raise sqlite3.OperationalError("disk I/O error")            # 되돌리기도 실패한다
        with patch, mock.patch.object(bf, "_restore_database", flaky):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "RESTORE_FAILED")
        self.assertTrue(any("글 보관함" in note and "원래대로 돌리지 못했어요" in note for note in error.notes), error.notes)
        self.assertTrue(bf._marker_path(self.ctx).exists(), "못 돌린 것이 있으면 표지가 남아 안내가 뜬다")
        pending = bf.list_full_backups(self.ctx).interrupted
        self.assertIsNotNone(pending)
        self.assertTrue(pending.can_revert)
        self.ctx.clock.advance(seconds=30)
        bf.revert_interrupted_restore(self.ctx, confirmed=True)
        self.assertEqual(tr.state_of(self.world), self.before, "그 안전 사본으로 되돌리면 복원 직전 데이터다")

    def test_a_rollback_that_reports_success_but_leaves_a_different_store_is_told_and_keeps_the_marker(self):
        """(3) 되돌린 뒤 지금 보관함이 안전 사본과 같은지 확인한다 — 다르면 '원래대로 돌렸다' 고 말하지 않는다."""
        patch, _calls = self.failing_restore()
        real, seen = bf._restore_database, []

        def pretend(component, path, source):
            seen.append(component.name)
            if len(seen) == 1:
                return real(component, path, source)
            return None                                                  # 되돌렸다고 하지만 아무것도 하지 않는다
        with patch, mock.patch.object(bf, "_restore_database", pretend):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "RESTORE_FAILED")
        self.assertTrue(any("글 보관함" in note and "안전 사본" in note and "내용이 달라요" in note for note in error.notes), error.notes)
        self.assertTrue(bf._marker_path(self.ctx).exists())

    def test_a_successful_restore_does_not_call_the_rollback_and_still_ends_complete(self):
        calls = []
        real = bf._roll_back
        with mock.patch.object(bf, "_roll_back", side_effect=lambda *args, **kwargs: calls.append(1) or real(*args, **kwargs)):
            result = bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual((result.status, calls), (bf.STATUS_COMPLETE, []))


class TopicsRestoreAfterCopyTest(unittest.TestCase):
    """주제 엔진 복원(`topicdb.backup.restore_backup`, `topics restore`) — 덮은 뒤 실패해도 주제 보관함이 원래대로다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = tb.World(self.tmp.name)
        self.backup = self.world.backup().path
        self.later = tb.NOW + datetime.timedelta(minutes=5)
        with TopicStore.open(self.world.data / layout.ENGINE_DB_FILE) as store:
            store.add_candidates(lambda existing: [tb.candidate(3)], now=tb.STAMP)
        self.database = self.world.data / layout.ENGINE_DB_FILE
        self.before = bs.dump(self.database)

    def restore(self):
        return tbackup.restore_backup(self.backup, self.world.data, self.world.backups, now=self.later)

    def arm(self):
        real, seen = tfile.EngineFile._prepare, {"armed": False, "restores": 0}
        real_restore = tfile.EngineFile.restore_from

        def restore_from(this, backup):
            seen["restores"] += 1
            seen["armed"] = seen["restores"] == 1
            return real_restore(this, backup)

        def prepare(this, fresh):
            if seen["armed"]:
                seen["armed"] = False
                raise AppError("MIGRATION_BLOCKED", {"이유": "일부러 낸 실패"}, detail="덮은 뒤의 판 올리기 실패")
            return real(this, fresh)
        return mock.patch.object(tfile.EngineFile, "restore_from", restore_from), mock.patch.object(tfile.EngineFile, "_prepare", prepare), seen

    def test_a_prepare_failure_after_the_copy_leaves_the_engine_store_as_it_was(self):
        first, second, _seen = self.arm()
        with first, second:
            with self.assertRaises(AppError) as caught:
                self.restore()
        self.assertEqual(caught.exception.code, "MIGRATION_BLOCKED")
        self.assertEqual(getattr(caught.exception, "notes", ()), ())
        self.assertEqual(bs.dump(self.database), self.before, "덮은 뒤 실패했는데 주제 보관함이 백업 내용으로 남았다")
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002", "cid-003"])

    def test_when_the_low_layer_cannot_undo_the_restore_rolls_the_store_back_from_the_before_restore_backup(self):
        first, second, seen = self.arm()
        with first, second, mock.patch.object(tfile, "hold_in_memory", lambda connection: BrokenUndo()):
            with self.assertRaises(AppError) as caught:
                self.restore()
        self.assertEqual(caught.exception.code, "MIGRATION_BLOCKED")
        self.assertEqual(getattr(caught.exception, "notes", ()), (), "되돌렸으면 알릴 것이 없다")
        self.assertGreaterEqual(seen["restores"], 2, "직전 상태 백업에서 되돌리는 복원이 한 번 더 있었다")
        self.assertEqual(bs.dump(self.database), self.before)

    def test_when_even_that_fails_the_name_and_the_place_of_the_original_are_told(self):
        calls = []

        def restore_from(this, backup):
            calls.append(Path(backup).parent.name)
            if len(calls) == 1:
                with contextlib.closing(sqlite3.connect(cstore._read_only_uri(Path(backup)), uri=True)) as source:
                    source.backup(this._db)
                error = AppError("MIGRATION_BLOCKED", {"이유": "일부러 낸 실패"}, detail="덮은 뒤 실패")
                error.left_overwritten = True
                raise error
            raise AppError("TOPIC_STORE_LOCKED", detail="되돌리기도 실패")
        with mock.patch.object(tfile.EngineFile, "restore_from", restore_from):
            with self.assertRaises(AppError) as caught:
                self.restore()
        notes = " ".join(caught.exception.notes)
        self.assertIn(layout.ENGINE_DB_FILE, notes)
        self.assertIn(tbackup.SAFETY_FOLDER, notes, "원래 내용이 어디 있는지")
        safety = tbackup.list_backups(self.world.backups / tbackup.SAFETY_FOLDER)[0]
        with TopicStore.open(safety / layout.ENGINE_DB_FILE, migrate=False) as saved:
            self.assertEqual(saved.count(), 3, "원래 내용은 직전 상태 백업에 그대로 있다")

    def test_without_the_mark_nothing_extra_is_attempted_and_a_normal_failure_stays_as_before(self):
        calls = []

        def restore_from(this, backup):
            calls.append(1)
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 실패(덮기 전)")
        with mock.patch.object(tfile.EngineFile, "restore_from", restore_from):
            with self.assertRaises(AppError) as caught:
                self.restore()
        self.assertEqual((caught.exception.code, len(calls)), ("TOPIC_STORE_LOCKED", 1))
        self.assertEqual(getattr(caught.exception, "notes", ()), ())
        self.assertEqual(bs.dump(self.database), self.before)


class OldRestoreCommandTest(unittest.TestCase):
    """옛 `restore` 명령(`service/projects.py::restore_store`)도 낮은 층을 거치므로 같은 틈이 막힌다."""

    def test_the_old_restore_command_leaves_the_store_intact_when_the_prepare_step_fails_after_the_copy(self):
        from chanceblog_desktop.service import projects
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world = bs.World(tmp.name)
        backup = projects.backup_store(world.ctx)
        tr.change_everything(world)
        before = tr.state_of(world)
        seen = {"armed": False, "restores": 0}
        real_prepare, real_restore = cstore.Store._prepare, cstore.Store.restore_from

        def restore(this, source, **kwargs):
            seen["restores"] += 1
            seen["armed"] = seen["restores"] == 1
            return real_restore(this, source, **kwargs)

        def prepare(this, fresh):
            if seen["armed"]:
                seen["armed"] = False
                raise AppError("MIGRATION_FAILED", detail="덮은 뒤의 판 올리기 실패")
            return real_prepare(this, fresh)
        with mock.patch.object(cstore.Store, "restore_from", restore), mock.patch.object(cstore.Store, "_prepare", prepare):
            error = bs.code_of(projects.restore_store, world.ctx, backup, confirmed=True)
        self.assertEqual(error.code, "MIGRATION_FAILED")
        self.assertEqual(tr.state_of(world), before, "옛 restore 명령이 실패했는데 글 보관함이 백업 내용으로 남았다")


if __name__ == "__main__":
    unittest.main()
