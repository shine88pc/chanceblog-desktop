"""검증(BACKUPUIV)에서 드러난 시험 공백을 메우는 시험 — 이름 바꾸기 다시 하기(D8)·WAL 저장 방식 보관함(D2)·정리 못 한 저장(D5)·목록 모양의 느슨한 곳(D9)·살아남은 변이 여섯(D11) (BACKUPUI 2차 수정, 결정 D-462·D-464·D-466).

지키는 것:
  1) **이름 바꾸기·바꿔 넣기가 다른 프로그램에 잠깐 붙잡혀 막히면 짧게 다시 해 본다**(`RETRY_TRIES` 번·`RETRY_WAIT` 초): 잠깐이면 백업·복원이 끝나고, 계속이면 깨끗이 실패하며(임시 폴더·잠금 0, 지금 데이터 그대로),
     다시 해도 소용없는 오류(저장 공간 부족·이미 있음)는 한 번만 한다. 기다림은 시계를 바꿔 끼워 실제로 자지 않는다.
  2) **앱 밖의 도구가 WAL 저장 방식으로 바꿔 둔 보관함도 백업된다** — 사본은 일반 방식(짝 파일 없음)이고 지금 파일은 바뀌지 않으며 복원까지 된다. **정리 못 한 저장(`-journal`)이 남은 보관함은 백업이 건드리지 않고**
     부분 백업으로 정직하게 알린다(이유가 목록에 남는다). 복원은 어차피 쓰는 일이라 그 보관함을 한 번 열어 정리한 뒤 진행한다.
  3) 목록 모양: `schema: true`·훑기 기록이 '찾은 것 있음'·담지 않은 것 항목 모양이 다름·글 칸이 너무 김은 거절한다. 앱이 자기 버전을 못 읽어도 보관함 자체의 판(`user_version`)으로 더 새로운 데이터를 거절한다.
  4) 변이 여섯(백업 마무리 전 다시 읽기·안전 사본 완전성·깨진 지금 파일 판정·복원 뒤 JSON 해시·링크 거절·복원 전 정리 못 한 저장 열기)을 없애면 이 시험이 빨개진다.
네트워크 없이 돈다.
"""
import contextlib
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import backup_support as bs  # noqa: E402
from test_service_backup_restore import change_everything, state_of  # noqa: E402

from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

DBS = ("chanceblog.db", layout.ENGINE_DB_FILE)
HOT_JOURNAL = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("pragma journal_mode = delete")
db.execute("pragma cache_size = 1")
db.execute("begin")
db.execute("create table zz_scratch(a blob)")
for _ in range(400):
    db.execute("insert into zz_scratch values (zeroblob(4000))")
os._exit(9)
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = bs.World(self.tmp.name)
        self.ctx = self.world.ctx
        self.backups = self.ctx.workspace.backups_dir
        self.sleeps = []
        patcher = mock.patch.object(bf, "_sleep", self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def leftovers(self):
        names = [path.name for path in self.world.root.rglob("*") if path.name.endswith((".tmp", ".restoring"))]
        locks = list(self.ctx.workspace.locks_dir.iterdir()) if self.ctx.workspace.locks_dir.is_dir() else []
        return names, [path.name for path in locks]


class RetryTest(Base):
    """D8 — 폴더 이름 바꾸기(`_finish_folder`)·제자리로 바꿔 넣기(`_swap_in`)가 잠깐 막히면 다시 해 본다."""

    def flaky_rename(self, fail_times, error):
        real, calls = os.rename, []

        def fake(source, target):
            calls.append(str(source))
            if len(calls) <= fail_times:
                raise error
            return real(source, target)
        return fake, calls

    def test_the_constants_are_five_tries_and_a_fifth_of_a_second_in_one_place(self):
        self.assertEqual((bf.RETRY_TRIES, bf.RETRY_WAIT), (5, 0.2))

    def test_a_folder_rename_held_for_a_moment_is_tried_again_and_the_backup_finishes(self):
        for error in (PermissionError(errno.EACCES, "Access is denied"), PermissionError(errno.EPERM, "Operation not permitted"), OSError(errno.EBUSY, "busy")):
            with self.subTest(error=type(error).__name__):
                self.sleeps.clear()
                fake, calls = self.flaky_rename(2, error)
                with mock.patch.object(bf.os, "rename", fake):
                    outcome = self.world.backup()
                self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
                self.assertEqual((len(calls), self.sleeps), (3, [bf.RETRY_WAIT, bf.RETRY_WAIT]), "두 번 막히고 세 번째에 됐다")
                self.assertEqual(self.leftovers(), ([], []))
                self.ctx.clock.advance(seconds=5)

    def test_a_sharing_violation_reported_only_by_its_windows_error_number_is_tried_again_too(self):
        error = OSError(errno.EIO, "I/O")
        error.winerror = 32
        fake, calls = self.flaky_rename(1, error)
        with mock.patch.object(bf.os, "rename", fake):
            self.assertEqual(self.world.backup().row.status, bf.STATUS_COMPLETE)
        self.assertEqual(len(calls), 2)

    def test_when_it_never_lets_go_the_backup_fails_cleanly_after_exactly_the_tries(self):
        before = self.world.data_digests()
        fake, calls = self.flaky_rename(99, PermissionError(errno.EACCES, "Access is denied"))
        with mock.patch.object(bf.os, "rename", fake):
            error = bs.code_of(self.world.backup)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertEqual((len(calls), self.sleeps), (bf.RETRY_TRIES, [bf.RETRY_WAIT] * (bf.RETRY_TRIES - 1)))
        self.assertEqual(self.leftovers(), ([], []))
        self.assertEqual(sorted(path.name for path in self.backups.iterdir()) if self.backups.is_dir() else [], [])
        self.assertEqual(self.world.data_digests(), before)

    def test_errors_that_a_retry_cannot_fix_are_tried_once(self):
        for error in (OSError(errno.ENOSPC, "No space left on device"), FileExistsError(errno.EEXIST, "exists"), FileNotFoundError(errno.ENOENT, "gone"), OSError(errno.ENAMETOOLONG, "too long")):
            with self.subTest(error=type(error).__name__):
                self.sleeps.clear()
                fake, calls = self.flaky_rename(99, error)
                with mock.patch.object(bf.os, "rename", fake):
                    failure = bs.code_of(self.world.backup)
                self.assertIsNotNone(failure)
                self.assertEqual((len(calls), self.sleeps), (1, []), "다시 해도 같은 오류는 한 번만 한다")

    def flaky_replace(self, fail_times, error):
        real, calls = os.replace, []

        def fake(source, target):
            if str(source).endswith(".restoring"):
                calls.append(str(source))
                if len(calls) <= fail_times:
                    raise error
            return real(source, target)
        return fake, calls

    def prepare_restore(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        change_everything(self.world)
        self.ctx.clock.advance(seconds=30)
        return outcome, saved

    def test_a_replace_held_for_a_moment_during_a_restore_is_tried_again_and_the_restore_finishes(self):
        outcome, saved = self.prepare_restore()
        fake, calls = self.flaky_replace(2, PermissionError(errno.EACCES, "Access is denied"))
        with mock.patch.object(bf.os, "replace", fake):
            result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(self.sleeps, [bf.RETRY_WAIT] * 2)
        self.assertEqual(state_of(self.world), saved)
        self.assertEqual(self.leftovers(), ([], []))

    def test_a_replace_that_never_gets_through_fails_the_restore_and_leaves_the_data_as_it_was(self):
        outcome, _saved = self.prepare_restore()
        before = state_of(self.world)
        fake, calls = self.flaky_replace(999, PermissionError(errno.EACCES, "Access is denied"))
        with mock.patch.object(bf.os, "replace", fake):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("RESTORE_FAILED", "io"))
        self.assertEqual(len(calls), bf.RETRY_TRIES, "첫 파일이 모두 막혔고 거기서 멈췄다")
        self.assertEqual(state_of(self.world), before)
        self.assertEqual(self.leftovers(), ([], []))
        self.assertIsNone(bf.list_full_backups(self.ctx).interrupted, "원래대로 돌렸으니 멈춘 복원의 흔적은 없다")


class RestorePruneTest(Base):
    """D3 의 짝 — 복원 뒤 안전 사본 정리도 지금보다 미래 날짜인 폴더를 가장 낡은 것으로 센다(시계가 거꾸로 가도 지난 안전 사본이 먼저 지워지지 않는다)."""

    def test_future_dated_safety_copies_are_pruned_before_real_past_ones(self):
        outcome = self.world.backup()
        self.ctx.clock.advance(seconds=30)
        first = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True).safety
        root = self.backups / bf.SAFETY_FOLDER
        template = root / first
        past = [f"before-20260101-0000{number:02d}" for number in (1, 2, 3)]
        future = [f"before-20271101-0000{number:02d}" for number in range(1, 10)]
        for name in (*past, *future):
            shutil.copytree(template, root / name)
        self.ctx.clock.advance(seconds=30)
        latest = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True).safety
        kept = sorted(path.name for path in root.iterdir())
        self.assertEqual(len(kept), bf.KEEP_BACKUPS)
        for name in (latest, first, *past):
            self.assertIn(name, kept, f"{name} 이 정리됐다 — 지난 안전 사본이 미래 날짜보다 먼저 지워졌다")
        self.assertEqual([name for name in future if name not in kept], future[:4], "미래 날짜 가운데 가장 낡은 것부터 정리된다")


class WalTest(Base):
    """D2 — 앱 밖의 도구가 보관함을 WAL 저장 방식으로 바꿔 두어도 백업이 되고, 사본은 일반 방식이다."""

    def to_wal(self, path):
        with contextlib.closing(sqlite3.connect(str(path))) as db:
            self.assertEqual(db.execute("pragma journal_mode = wal").fetchone()[0], "wal")
        self.assertEqual(Path(path).read_bytes()[18:20], b"\x02\x02", "시험의 전제 — 파일 머리가 WAL 표시다")

    def test_a_wal_store_is_backed_up_as_an_ordinary_file_without_touching_the_live_file(self):
        for name in DBS:
            self.to_wal(self.world.path(name))
        live = {name: sha(self.world.path(name)) for name in DBS}
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        folder = self.world.folder(outcome)
        self.assertEqual(sorted(path.name for path in folder.iterdir()), sorted([*self.world.manifest(outcome)["files"], bf.MANIFEST_NAME]), "-wal·-shm 같은 짝 파일이 백업에 없다")
        for name in DBS:
            self.assertEqual((folder / name).read_bytes()[18:20], b"\x01\x01", "사본은 일반(롤백 저널) 방식이다")
            self.assertEqual(sha(self.world.path(name)), live[name], "지금 파일은 한 바이트도 바뀌지 않았다")
        self.assertEqual(self.leftovers(), ([], []))

    def test_that_backup_is_verified_listed_and_restored_like_any_other(self):
        for name in DBS:
            self.to_wal(self.world.path(name))
        outcome = self.world.backup()
        saved = state_of(self.world)
        self.assertEqual([row.status for row in bf.list_full_backups(self.ctx).rows], [bf.STATUS_COMPLETE])
        change_everything(self.world)
        self.ctx.clock.advance(seconds=30)
        self.assertEqual(bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True).status, bf.STATUS_COMPLETE)
        self.assertEqual(state_of(self.world), saved)


class HotJournalTest(Base):
    """D5·V22 — 앱이 쓰다 갑자기 꺼져 정리 못 한 저장(`-journal`)이 남은 보관함."""

    def make_hot(self, name="chanceblog.db"):
        path = self.world.path(name)
        done = subprocess.run([sys.executable, "-X", "utf8", "-c", HOT_JOURNAL, str(path)], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 9, done.stderr[-300:])
        journal = Path(str(path) + "-journal")
        self.assertTrue(journal.is_file() and journal.stat().st_size > 0, "시험의 전제 — 정리 못 한 저장이 남았다")
        error = bs.code_of(Store.open, path, migrate=False)
        self.assertEqual(error.code, "STORE_RECOVERY_PENDING", "시험의 전제 — 읽기 전용으로는 읽을 수 없다")
        return path, journal

    def test_a_backup_leaves_such_a_store_alone_and_says_truthfully_that_it_is_partial_and_why(self):
        path, journal = self.make_hot()
        before = (sha(path), sha(journal))
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_PARTIAL)
        skipped = {line.name: line.reason for line in outcome.row.files if line.state == bf.LINE_SKIPPED}
        self.assertEqual(skipped, {"chanceblog.db": "STORE_RECOVERY_PENDING"})
        saved = [line.name for line in outcome.row.files if line.state == bf.LINE_SAVED]
        self.assertEqual(saved, [name for name in bf.BY_NAME if name != "chanceblog.db"], "나머지는 모두 담았다")
        self.assertEqual(self.world.manifest(outcome)["skipped"], {"chanceblog.db": "STORE_RECOVERY_PENDING"}, "이유가 목록에도 남는다")
        self.assertEqual((sha(path), sha(journal)), before, "백업은 그 보관함도 저널도 한 바이트 바꾸지 않았다")

    def test_a_restore_opens_such_a_current_store_once_to_finish_its_save_and_then_goes_on(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        change_everything(self.world)
        path, journal = self.make_hot()
        self.ctx.clock.advance(seconds=30)
        opened = []
        real = Store.open

        def spy(target, *args, **kwargs):
            opened.append((Path(target), kwargs.get("migrate", True)))
            return real(target, *args, **kwargs)
        with mock.patch.object(bf.Store, "open", spy):
            result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertIn((path, True), opened, "정리하려고 쓰기로 한 번 열었다")
        self.assertEqual(state_of(self.world), saved)
        self.assertFalse(journal.exists(), "정리 못 한 저장이 정리됐다")
        self.assertEqual(result.safety.startswith("before-"), True)
        safety = next(row for row in bf.list_full_backups(self.ctx).rows if row.name == result.safety)
        self.assertIn("chanceblog.db", [line.name for line in safety.files if line.state == bf.LINE_SAVED], "정리한 보관함이 안전 사본에 담겼다")


class MutantGapsTest(Base):
    """D11 — 검증이 살려 낸 변이 여섯을 잡는 시험(각각 그 줄을 없애면 빨개진다)."""

    def test_v06_the_finished_folder_is_read_back_before_it_is_published(self):
        real = bf._write_durably

        def spoil(path, data):
            real(path, data)
            if Path(path).name == bf.MANIFEST_NAME:
                (Path(path).parent / "chanceblog.db-wal").write_bytes(b"stray")                  # 목록에 없는 짝 파일이 폴더에 끼어들었다
        with mock.patch.object(bf, "_write_durably", spoil):
            error = bs.code_of(self.world.backup)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "files"))
        self.assertEqual(sorted(path.name for path in self.backups.iterdir()) if self.backups.is_dir() else [], [], "모르는 파일이 든 폴더가 백업으로 공개되지 않았다")

    def test_a_disk_error_after_sqlite_left_a_side_file_still_cleans_the_whole_temp_folder(self):
        """입출력 오류로 멈출 때도 SQLite 가 쓰다 남긴 짝 파일(`-journal`)까지 치워 임시 폴더가 남지 않는다."""
        def fail(path, data):
            (Path(path).parent / "chanceblog.db-journal").write_bytes(b"left by sqlite")
            raise OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(bf, "_write_durably", fail):
            error = bs.code_of(self.world.backup)
        self.assertEqual(error.code, "DISK_FULL")
        self.assertEqual(sorted(path.name for path in self.backups.iterdir()) if self.backups.is_dir() else [], [])
        self.assertEqual(self.leftovers(), ([], []))

    def test_v06_a_file_that_changes_after_its_hash_was_taken_is_caught_before_the_rename(self):
        real = bf._write_durably

        def spoil(path, data):
            real(path, data)
            if Path(path).name == bf.MANIFEST_NAME:
                seeds = Path(path).parent / layout.SEEDS_FILE
                seeds.write_bytes(seeds.read_bytes() + b" ")
        with mock.patch.object(bf, "_write_durably", spoil):
            error = bs.code_of(self.world.backup)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "hash"))
        self.assertEqual(sorted(path.name for path in self.backups.iterdir()) if self.backups.is_dir() else [], [])

    def test_v07_a_safety_copy_that_lacks_a_file_that_will_change_stops_the_restore_before_anything_changes(self):
        outcome = self.world.backup()
        change_everything(self.world)
        before = state_of(self.world)
        real = bf._build

        def incomplete(*args, **kwargs):
            built = real(*args, **kwargs)
            if kwargs.get("prefix") == "before":
                files = tuple(replace(line, state=bf.LINE_SKIPPED) if line.name == "settings.json" else line for line in built.row.files)
                return replace(built, row=replace(built.row, files=files))
            return built
        self.ctx.clock.advance(seconds=30)
        with mock.patch.object(bf, "_build", incomplete):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("RESTORE_FAILED", "safety"))
        self.assertEqual(state_of(self.world), before, "안전 사본이 불완전하면 아무것도 바꾸지 않는다")
        self.assertFalse(bf._marker_path(self.ctx).exists(), "아직 바꾸기 시작하지 않았으니 표지도 없다")

    def test_v08_a_current_store_that_opens_but_fails_its_check_is_moved_aside_and_the_backup_is_restored(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        live = self.world.path("chanceblog.db")
        with contextlib.closing(sqlite3.connect(str(live))) as db:
            db.execute("UPDATE projects SET title = '목록 열만 바뀐 제목'")                        # 열고 읽을 수는 있지만 앱의 자료 점검이 '목록 열과 자료가 다르다' 고 한다
            db.commit()
        with Store.open(live, migrate=False) as opened:
            self.assertTrue(opened.check(), "시험의 전제 — 점검이 문제를 찾는다")
        damaged = live.read_bytes()
        self.ctx.clock.advance(seconds=30)
        result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(state_of(self.world), saved)
        aside = sorted(live.parent.glob("chanceblog.db.bad-*"))
        self.assertEqual(len(aside), 1, "깨진 지금 파일은 지우지 않고 옆으로 옮겨 뒀다")
        self.assertEqual(aside[0].read_bytes(), damaged)
        safety = next(row for row in bf.list_full_backups(self.ctx).rows if row.name == result.safety)
        self.assertNotIn("chanceblog.db", [line.name for line in safety.files if line.state == bf.LINE_SAVED], "깨진 파일은 안전 사본에 담지 않는다")

    def test_v10_a_plain_file_that_differs_from_the_list_after_it_was_written_fails_the_restore_and_is_rolled_back(self):
        outcome = self.world.backup()
        change_everything(self.world)
        before = state_of(self.world)
        real = bf._write_durably
        folder = self.world.folder(outcome)
        backup_bytes = {name: (folder / name).read_bytes() for name in (layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE, layout.CALENDAR_FILE, "settings.json")}

        def spoil(path, data):
            name = Path(path).name[:-len(".restoring")] if Path(path).name.endswith(".restoring") else ""
            real(path, data + b" " if name in backup_bytes and data == backup_bytes[name] else data)      # 백업의 내용을 쓰는 임시 파일에만 한 글자를 더 쓴다(원래대로 돌릴 때 쓰는 옛 내용은 그대로)
        self.ctx.clock.advance(seconds=30)
        with mock.patch.object(bf, "_write_durably", spoil):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "RESTORE_FAILED")
        self.assertEqual(state_of(self.world), before, "목록과 해시가 다른 파일이 복원됐다면 원래대로 돌아와야 한다")
        self.assertIsNone(bf.list_full_backups(self.ctx).interrupted)

    def test_v16_a_link_inside_a_backup_folder_is_refused_even_when_its_bytes_match(self):
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        seeds = folder / layout.SEEDS_FILE
        original = seeds.read_bytes()
        real_is_symlink = Path.is_symlink

        def pretend(self_path):
            return True if self_path.name == layout.SEEDS_FILE and self_path.parent == folder else real_is_symlink(self_path)
        change_everything(self.world)
        before = state_of(self.world)
        with mock.patch.object(Path, "is_symlink", pretend):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "files"))
        self.assertEqual(state_of(self.world), before)
        self.assertEqual(seeds.read_bytes(), original)

    def test_v16_a_real_link_is_refused_too_where_this_pc_can_make_one(self):
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        seeds = folder / layout.SEEDS_FILE
        copy = Path(self.tmp.name) / "seeds-copy.json"
        copy.write_bytes(seeds.read_bytes())
        seeds.unlink()
        try:
            os.symlink(copy, seeds)
        except (OSError, NotImplementedError):
            self.skipTest("이 PC 에서는 링크를 만들 수 없다")
        before = state_of(self.world)
        error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "files"))
        self.assertEqual(state_of(self.world), before)

    def test_v22_without_the_heal_step_a_pending_save_would_stop_the_restore(self):
        """V22 의 모의 짝 — 읽기 전용 열기가 한 번 '정리 못 한 저장' 이라 하면 복원은 쓰기로 한 번 열어 정리한 뒤 진행한다(진짜 저널 시험은 HotJournalTest)."""
        outcome = self.world.backup()
        saved = state_of(self.world)
        change_everything(self.world)
        live = self.world.path("chanceblog.db")
        real, state, opened = Store.open, {"first": True}, []

        def fake(path, *args, **kwargs):
            opened.append((Path(path), kwargs.get("migrate", True)))
            if kwargs.get("migrate") is False and Path(path) == live and state["first"]:
                state["first"] = False
                raise AppError("STORE_RECOVERY_PENDING", {"파일": "chanceblog.db"})
            return real(path, *args, **kwargs)
        self.ctx.clock.advance(seconds=30)
        with mock.patch.object(bf.Store, "open", fake):
            result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(state_of(self.world), saved)
        self.assertIn((live, True), opened)


class ManifestShapeTest(Base):
    """D9 — 목록 모양의 느슨한 곳을 좁힌다."""

    def rewrite(self, outcome, change):
        manifest = self.world.manifest(outcome)
        change(manifest)
        bs.write_manifest(self.world.folder(outcome), manifest)

    def assert_refused(self, outcome):
        row = next(row for row in bf.list_full_backups(self.ctx).rows if row.name == outcome.row.name)
        self.assertEqual((row.status, row.problem), (bf.STATUS_BROKEN, "manifest"))
        before = state_of(self.world)
        error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "manifest"))
        self.assertEqual(state_of(self.world), before)

    def test_a_normal_manifest_is_accepted_by_the_tighter_checks(self):
        outcome = self.world.backup()
        self.assertEqual([row.status for row in bf.list_full_backups(self.ctx).rows], [bf.STATUS_COMPLETE])
        self.assertEqual(bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True).status, bf.STATUS_COMPLETE)

    def test_a_boolean_true_is_not_accepted_as_the_schema_number_one(self):
        outcome = self.world.backup()
        self.rewrite(outcome, lambda manifest: manifest.update(schema=True))
        self.assert_refused(outcome)

    def test_the_scan_record_must_say_checked_and_nothing_found_and_have_only_its_three_fields(self):
        for label, change in (("찾은 것 있음", lambda scan_note: scan_note.update(found=1)), ("찾은 것이 불리언", lambda scan_note: scan_note.update(found=False)), ("훑지 않음", lambda scan_note: scan_note.update(checked=False)),
                              ("칸 하나 더", lambda scan_note: scan_note.update(extra="x")), ("유형이 목록 아님", lambda scan_note: scan_note.update(kinds="google_api_key")),
                              ("유형 글이 너무 김", lambda scan_note: scan_note.update(kinds=["가" * 100]))):
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World.cached(tmp)
                    outcome = world.backup()
                    manifest = world.manifest(outcome)
                    change(manifest["secret_scan"])
                    bs.write_manifest(world.folder(outcome), manifest)
                    row = next(row for row in bf.list_full_backups(world.ctx).rows if row.name == outcome.row.name)
                    self.assertEqual((row.status, row.problem), (bf.STATUS_BROKEN, "manifest"))

    def test_the_excluded_list_must_be_name_and_reason_texts_of_a_sensible_size(self):
        for label, change in (("목록이 아님", lambda manifest: manifest.update(excluded={"name": "x"})), ("항목에 칸이 하나 더", lambda manifest: manifest["excluded"][0].update(extra="x")),
                              ("이유가 글이 아님", lambda manifest: manifest["excluded"][0].update(reason=5)), ("이유가 너무 김", lambda manifest: manifest["excluded"][0].update(reason="가" * 2001)),
                              ("항목이 너무 많음", lambda manifest: manifest.update(excluded=manifest["excluded"] * 6)), ("안내 글이 너무 김", lambda manifest: manifest.update(credential_excluded_note="가" * 2001)),
                              ("안내 글이 글이 아님", lambda manifest: manifest.update(credential_excluded_note=["x"]))):
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World.cached(tmp)
                    outcome = world.backup()
                    manifest = world.manifest(outcome)
                    change(manifest)
                    bs.write_manifest(world.folder(outcome), manifest)
                    row = next(row for row in bf.list_full_backups(world.ctx).rows if row.name == outcome.row.name)
                    self.assertEqual((row.status, row.problem), (bf.STATUS_BROKEN, "manifest"))

    def test_the_marker_of_a_stopped_restore_does_not_accept_a_boolean_schema_either(self):
        self.backups.mkdir(parents=True, exist_ok=True)
        data = {"schema": True, "started": "2026-11-11T05:00:00Z", "backup": "full-20261111-050000", "safety": "before-20261111-050000", "files": ["chanceblog.db"]}
        (self.backups / bf.RESTORE_MARKER).write_text(json.dumps(data), encoding="utf-8")
        pending = bf.interrupted_restore(self.ctx)
        self.assertEqual((pending.started_at, pending.backup, pending.safety, pending.can_revert), ("", "", "", False))

    def test_a_newer_store_is_still_refused_when_the_app_cannot_read_its_own_version(self):
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        with contextlib.closing(sqlite3.connect(str(folder / "chanceblog.db"))) as db:
            db.execute("PRAGMA user_version = 99")
            db.commit()
        manifest = self.world.manifest(outcome)
        manifest["files"]["chanceblog.db"].update(size=(folder / "chanceblog.db").stat().st_size, sha256=sha(folder / "chanceblog.db"))
        manifest["app_version"] = "99.0.0"
        bs.write_manifest(folder, manifest)
        before = state_of(self.world)
        with mock.patch.object(bf, "read_app_version", return_value=""):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("STORE_VERSION_UNSUPPORTED", "newer"), "앱 버전 비교가 꺼져도 보관함 자체의 판으로 거절한다")
        self.assertEqual(state_of(self.world), before)


if __name__ == "__main__":
    unittest.main()
