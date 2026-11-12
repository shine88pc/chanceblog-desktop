"""끊긴 백업·복원 시험 — 앱이 도중에 강제로 끝나거나(전원·강제 종료) 창을 닫거나 이름 바꾸기가 막혀도 키·토큰 모양이 디스크에 남지 않고, 남은 흔적은 다음에 치워진다(BACKUPUI 2차 수정, 결정 D-461–D-465).

지키는 것:
  1) **훑기 전에는 디스크에 쓰지 않는다**(D1): 키·토큰 모양이 든 보관함·JSON·설정이 있는 데이터로 백업을 하다가 곳곳에서 프로세스를 죽여도(`os._exit` — 정리 코드가 돌지 않는다) 지금 파일을 뺀
     데이터 폴더의 모든 바이트에 그 글이 없다(utf-8·utf-16·16진수·base64·퍼센트 인코딩). 찾는 도구가 정말 찾는지는 양성 대조(지금 파일에는 있다)로 확인한다.
  2) 진행 단계마다·파일을 쓰고 메모리 사본을 만드는 모든 길목 앞뒤로 같은 검사를 한다 — '한순간도' 없다. 이름 바꾸기가 막히거나 정리조차 못 해도 남는 임시 폴더에는 키 모양이 없다.
  3) 죽은 백업이 남긴 임시 폴더(`full-….tmp`·`before-….tmp`, SQLite 짝 파일 포함)와 낡은 잠금은 다음 백업·복원에서, 그리고 목록을 보여 줄 때 치워진다. 살아 있는 백업·복원의 것·낯선 파일이 든 폴더는 건드리지 않는다.
네트워크 없이 돈다. 죽이는 쪽은 자식 프로세스(`backup_kill_child.py`)다.
"""
import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import backup_support as bs  # noqa: E402
import service_support as ss  # noqa: E402
from test_service_backup_restore import change_everything, state_of  # noqa: E402
from test_service_backup_secrets import inject  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

SRC = HERE.parent / "src"
CHILD = HERE / "backup_kill_child.py"
DIED = 9
KIND = bs.KINDS[0]


def stray_bytes(world):
    """데이터 폴더의 모든 파일 바이트 — 지금 파일(보관함·JSON·설정 여섯 개)은 뺀다(거기에는 원래 있다). 백업·임시·잠금·안전 사본 폴더가 모두 여기에 든다."""
    live = {world.path(component.name) for component in bf.COMPONENTS}
    return b"".join(path.read_bytes() for path in sorted(world.root.rglob("*")) if path.is_file() and path not in live)


def assert_clean(test, world, token, where=""):
    """지금 파일 밖의 어디에도 키·토큰 모양 글(여러 인코딩)이 없다."""
    blob = stray_bytes(world)
    for label, needle in bs.encodings(token).items():
        test.assertNotIn(needle, blob, f"{where} — {label} 모양의 키 글이 디스크에 있다")


def kill_child(world, name, nth, when, *, restore=None):
    """백업(`restore` 에 백업 이름을 주면 그 백업을 되돌리는 중)을 자식 프로세스에서 돌리다 지정한 지점에서 죽인다 → 끝난 프로세스(종료 코드 9 이어야 한다)."""
    extra = ["restore", restore] if restore else []
    return subprocess.run([sys.executable, "-X", "utf8", str(CHILD), str(SRC), str(HERE), str(world.tmp), name, str(nth), when, *extra], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = bs.World.cached(self.tmp.name)
        self.ctx = self.world.ctx
        self.backups = self.ctx.workspace.backups_dir

    def tmp_folders(self):
        return sorted(path for root in (self.backups, self.backups / bf.SAFETY_FOLDER) if root.is_dir() for path in root.iterdir() if path.name.endswith(".tmp"))

    def lock_files(self):
        return sorted(path.name for path in self.ctx.workspace.locks_dir.iterdir()) if self.ctx.workspace.locks_dir.is_dir() else []

    def full_names(self):
        return sorted(path.name for path in self.backups.iterdir() if bf.FULL_NAME.fullmatch(path.name)) if self.backups.is_dir() else []


# 키 모양이 든 곳 → 그 곳이 처음 나오는 순서(보관함 둘이 먼저, JSON·설정이 뒤) — 죽이는 지점은 (바꿀 함수, 몇 번째 부름, 앞/뒤)
SECRET_PLACES = {
    "원고 본문": [("_stage_sqlite", 1, "after"), ("_scan_connection", 1, "before"), ("_scan_connection", 1, "after")],
    "주제 보관함 후보": [("_write_sqlite", 1, "after"), ("_stage_sqlite", 2, "after"), ("_scan_connection", 2, "after")],
    "설정": [("_write_sqlite", 2, "after"), ("_write_durably", 3, "after"), ("_stage_sqlite", 1, "before")],
}


class KillWithSecretsTest(Base):
    def test_a_backup_killed_anywhere_never_leaves_a_key_shaped_text_on_disk(self):
        """키 모양이 든 곳 × 죽이는 지점 아홉 곳 — 죽은 뒤 지금 파일을 뺀 데이터 폴더의 모든 바이트에 그 글이 없다."""
        token, count = bs.secret_token(KIND), 0
        for where, points in SECRET_PLACES.items():
            for name, nth, when in points:
                with self.subTest(where=where, point=f"{name}#{nth} {when}"):
                    with tempfile.TemporaryDirectory() as tmp:
                        world = bs.World.cached(tmp)
                        inject(world, where, KIND, bs.three_lines(KIND))
                        self.assertIn(token.encode("utf-8"), bs.all_bytes(world.root), "양성 대조 — 지금 파일에는 키 글이 있다(찾는 도구가 찾는다)")
                        done = kill_child(world, name, nth, when)
                        self.assertEqual(done.returncode, DIED, f"그 지점에서 죽지 않았다: {done.stderr[-300:]}")
                        assert_clean(self, world, token, f"{where} {name}#{nth} {when}")
                        count += 1
        self.assertEqual(count, sum(len(points) for points in SECRET_PLACES.values()))

    def test_after_a_kill_the_next_backup_still_refuses_and_clears_what_the_dead_one_left(self):
        for where, points in SECRET_PLACES.items():
            name, nth, when = points[0]
            with self.subTest(where=where):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World.cached(tmp)
                    inject(world, where, KIND, bs.three_lines(KIND))
                    self.assertEqual(kill_child(world, name, nth, when).returncode, DIED)
                    error = bs.code_of(world.backup)
                    self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
                    backups = world.ctx.workspace.backups_dir
                    self.assertEqual(list(backups.iterdir()) if backups.is_dir() else [], [], "죽은 백업이 남긴 임시 폴더도 치워진다")
                    self.assertEqual(list(world.ctx.workspace.locks_dir.iterdir()), [], "낡은 잠금도 풀린다")
                    assert_clean(self, world, bs.secret_token(KIND), where)


CLEAN_POINTS = [("_write_sqlite", 1, "after"), ("_write_sqlite", 2, "after"), ("_write_durably", 1, "after"), ("_write_durably", 5, "after"), ("_verify_folder", 1, "before"), ("_finish_folder", 1, "before")]


class KillCleanDataTest(Base):
    def test_a_killed_backup_leaves_a_stale_temp_folder_and_lock_that_the_next_backup_clears(self):
        """죽은 백업의 임시 폴더(쓰다 만 사본)·잠금은 다음 백업이 치우고, 그 백업은 정상으로 끝난다 — 임시 폴더가 쌓이지 않는다."""
        for name, nth, when in CLEAN_POINTS:
            with self.subTest(point=f"{name}#{nth} {when}"):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World.cached(tmp)
                    backups = world.ctx.workspace.backups_dir
                    self.assertEqual(kill_child(world, name, nth, when).returncode, DIED)
                    leftovers = [path for path in backups.iterdir() if path.name.endswith(".tmp")]
                    self.assertEqual(len(leftovers), 1, "죽은 백업의 임시 폴더가 남는다(이 시험의 전제)")
                    self.assertTrue(any(leftovers[0].iterdir()), "쓰다 만 사본이 들어 있다")
                    self.assertEqual([path.name for path in world.ctx.workspace.locks_dir.iterdir()], ["full-backup.lock"], "죽은 백업의 잠금이 남는다(이 시험의 전제)")
                    world.ctx.clock.advance(seconds=30)
                    outcome = world.backup()
                    self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
                    self.assertEqual(sorted(path.name for path in backups.iterdir()), [outcome.row.name], "임시 폴더가 모두 치워졌다")
                    self.assertEqual(list(world.ctx.workspace.locks_dir.iterdir()), [])


class StaleCleanupTest(Base):
    def make_temp(self, root, name, files=("chanceblog.db", "chanceblog.db-journal", "MANIFEST.json")):
        folder = Path(root) / name
        folder.mkdir(parents=True)
        for item in files:
            (folder / item).write_bytes(b"half written")
        return folder

    def dead_lock(self):
        """죽은 프로세스가 남긴 잠금 파일 — 프로세스 생존 확인이 '이미 끝났다' 를 돌려주게 한다."""
        lock = bf._FlowLock(self.ctx.workspace.locks_dir, bf.LOCK_NAME, now=self.ctx.now, host="")
        lock._prepare_folder()
        lock._create()
        return lock

    def test_the_next_backup_clears_stale_temp_folders_of_any_name_including_sqlite_side_files(self):
        stale = [self.make_temp(self.backups, "full-20250101-000000.tmp"), self.make_temp(self.backups, "full-20250102-030405-2.tmp", files=("topic_engine.db", "topic_engine.db-wal", "topic_engine.db-shm")),
                 self.make_temp(self.backups / bf.SAFETY_FOLDER, "before-20250103-000000.tmp")]
        keep = self.make_temp(self.backups, "full-20250104-000000.tmp", files=("내 메모.txt",))
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=False):
            self.dead_lock()
            outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        for folder in stale:
            self.assertFalse(folder.exists(), f"{folder.name} 이 남았다")
        self.assertTrue((keep / "내 메모.txt").is_file(), "낯선 파일이 든 임시 폴더는 건드리지 않는다")
        self.assertEqual(self.lock_files(), [])

    def test_the_next_restore_clears_them_too(self):
        outcome = self.world.backup()
        stale = [self.make_temp(self.backups, "full-20250101-000000.tmp"), self.make_temp(self.backups / bf.SAFETY_FOLDER, "before-20250103-000000.tmp")]
        self.ctx.clock.advance(seconds=30)
        bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        for folder in stale:
            self.assertFalse(folder.exists(), f"{folder.name} 이 남았다")

    def test_listing_clears_what_a_dead_run_left_and_a_normal_listing_writes_nothing(self):
        outcome = self.world.backup()
        quiet = self.world.data_digests()
        before = sorted(str(path.relative_to(self.ctx.workspace.root)) for path in self.ctx.workspace.root.rglob("*"))
        rows = bf.list_full_backups(self.ctx).rows
        self.assertEqual([row.name for row in rows], [outcome.row.name])
        self.assertEqual(sorted(str(path.relative_to(self.ctx.workspace.root)) for path in self.ctx.workspace.root.rglob("*")), before, "치울 흔적이 없으면 목록은 한 글자도 쓰지 않는다")
        self.assertEqual(self.world.data_digests(), quiet)
        stale = self.make_temp(self.backups, "full-20250101-000000.tmp")
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=False):
            self.dead_lock()
            rows = bf.list_full_backups(self.ctx).rows
        self.assertEqual([row.name for row in rows], [outcome.row.name])
        self.assertFalse(stale.exists())
        self.assertEqual(self.lock_files(), [], "낡은 잠금도 치워졌다")

    def test_listing_clears_a_stale_lock_even_when_there_is_no_temp_folder(self):
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=False):
            self.dead_lock()
            self.assertEqual(self.lock_files(), ["full-backup.lock"], "시험의 전제")
            bf.list_full_backups(self.ctx)
        self.assertEqual(self.lock_files(), [], "임시 폴더가 없어도 낡은 잠금은 치워진다")

    def test_listing_a_data_folder_without_locks_folder_does_not_create_one(self):
        fresh = Path(tempfile.mkdtemp(dir=self.tmp.name)) / "nothing-here"
        ctx = ss.make_ctx(fresh, repo=None)
        self.assertEqual(bf.list_full_backups(ctx).rows, ())
        self.assertFalse(ctx.workspace.root.exists())

    def test_a_live_backup_or_restore_is_never_touched(self):
        """살아 있는 백업·복원이 잠금을 쥔 동안에는 목록도 다음 백업도 임시 폴더를 건드리지 않는다."""
        working = self.make_temp(self.backups, "full-20250101-000000.tmp")
        with bf._flow_lock(self.ctx):
            self.assertEqual(bf.list_full_backups(self.ctx).rows, ())
            self.assertTrue(working.exists(), "목록이 만드는 중인 임시 폴더를 지웠다")
            error = bs.code_of(self.world.backup)
            self.assertEqual(error.code, "BACKUP_IN_PROGRESS")
            self.assertTrue(working.exists(), "다른 백업이 도는 중에 임시 폴더를 지웠다")
        self.assertEqual(self.lock_files(), [])

    def test_a_lock_whose_process_is_alive_is_not_taken_over(self):
        """프로세스가 살아 있다고 나오는 잠금은 낡아 보이지 않는 한 넘겨받지 않는다 — 목록은 건드리지 않고 백업은 BACKUP_IN_PROGRESS."""
        working = self.make_temp(self.backups, "full-20250101-000000.tmp")
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=True):
            lock = self.dead_lock()
            self.assertEqual(bf.list_full_backups(self.ctx).rows, ())
            self.assertTrue(working.exists())
            self.assertEqual(bs.code_of(self.world.backup).code, "BACKUP_IN_PROGRESS")
            self.assertTrue(working.exists())
            self.assertEqual(self.lock_files(), ["full-backup.lock"], "다른 프로세스의 잠금은 그대로다")
        lock.release()

    def test_a_link_named_like_a_temp_folder_is_not_followed_or_removed(self):
        target = Path(self.tmp.name) / "somewhere-else"
        target.mkdir()
        (target / "chanceblog.db").write_bytes(b"not yours")
        link = self.backups / "full-20250101-000000.tmp"
        self.backups.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("이 PC 에서는 폴더 링크를 만들 수 없다")
        self.world.backup()
        self.assertTrue((target / "chanceblog.db").is_file(), "링크가 가리키는 곳의 파일을 지웠다")

    def test_a_folder_that_is_a_link_is_not_swept_even_where_this_pc_cannot_make_links(self):
        """링크로 보이는 이름의 폴더는 모의(`is_symlink`)로도 치우지 않는다 — 진짜 링크를 못 만드는 PC 에서도 링크 보호가 시험된다."""
        folder = self.make_temp(self.backups, "full-20250101-000000.tmp")
        real = Path.is_symlink

        def pretend(path):
            return True if path == folder else real(path)
        with mock.patch.object(Path, "is_symlink", pretend):
            self.world.backup()
        self.assertTrue((folder / "chanceblog.db").is_file(), "링크로 보이는 폴더 안의 파일을 지웠다")

    def test_the_names_that_count_as_temp_folders_are_only_the_ones_the_app_makes(self):
        for name, expected in (("full-20250101-000000.tmp", True), ("before-20250101-000000-12.tmp", True), ("full-20250101-000000", False), ("other-20250101-000000.tmp", False),
                               ("full-2025.tmp", False), ("full-20250101-000000.tmp.bak", False), ("full-20250101-000000-123.tmp", False)):
            self.assertEqual(bf.STALE_TEMP.fullmatch(name) is not None, expected, name)


class AbortPathTest(Base):
    def watched(self, calls, token):
        """길목 함수를 감싸 부르기 앞뒤로 데이터 폴더(지금 파일 제외)에 키 글이 없는지 본다."""
        def wrap(name):
            real = getattr(bf, name)

            def inner(*args, **kwargs):
                assert_clean(self, self.world, token, f"{name} 앞")
                result = real(*args, **kwargs)
                assert_clean(self, self.world, token, f"{name} 뒤")
                calls.append(name)
                return result
            return mock.patch.object(bf, name, inner)
        return [wrap(name) for name in ("_stage_sqlite", "_write_sqlite", "_scan_connection", "_write_durably", "_scan_json_bytes")]

    def test_at_every_step_and_every_write_no_key_shaped_text_is_on_disk(self):
        """키 모양이 든 데이터로 백업해도(거절된다) 진행 단계마다·길목 앞뒤마다 지금 파일 밖에 그 글이 없다 — '한순간도' 없다."""
        token = bs.secret_token(KIND)
        inject(self.world, "설정", KIND, bs.three_lines(KIND))
        seen, calls = [], []
        with contextlib.ExitStack() as stack:
            for patch in self.watched(calls, token):
                stack.enter_context(patch)

            def step(fraction, text=""):
                assert_clean(self, self.world, token, f"진행 {fraction}")
                seen.append(fraction)
            error = bs.code_of(self.world.backup, step=step)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
        self.assertGreaterEqual(len(seen), 5)
        self.assertTrue({"_stage_sqlite", "_write_sqlite", "_scan_connection", "_write_durably", "_scan_json_bytes"} <= set(calls), "길목이 모두 불렸다(시험이 빈 껍데기가 아니다)")
        assert_clean(self, self.world, token, "끝난 뒤")

    def test_cancelling_at_any_step_with_a_key_in_the_data_leaves_nothing_and_no_key_text(self):
        token = bs.secret_token(KIND)
        inject(self.world, "주제 보관함 후보", KIND, bs.three_lines(KIND))
        fractions = []
        bs.code_of(self.world.backup, step=lambda fraction, text="": fractions.append(fraction))
        for stop in sorted(set(fractions)):
            with self.subTest(stop=stop):
                class Stop(Exception):
                    pass

                def step(fraction, text="", stop=stop):
                    assert_clean(self, self.world, token, f"진행 {fraction}")
                    if fraction >= stop:
                        raise Stop()
                with self.assertRaises(Stop):
                    self.world.backup(step=step)
                self.assertEqual(self.tmp_folders(), [])
                self.assertEqual(self.lock_files(), [])
                assert_clean(self, self.world, token, f"취소 {stop}")

    def test_a_rename_that_is_blocked_leaves_no_key_text_and_no_temp_folder(self):
        token = bs.secret_token(KIND)
        with mock.patch.object(bf, "_finish_folder", side_effect=PermissionError(13, "denied")):
            error = bs.code_of(self.world.backup)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertEqual(self.tmp_folders(), [])
        self.assertEqual(self.lock_files(), [])
        assert_clean(self, self.world, token, "이름 바꾸기가 막힌 뒤")

    def test_even_when_the_cleanup_itself_fails_the_leftover_temp_folder_holds_no_key_text_and_is_swept_next_time(self):
        """이름 바꾸기가 막히고 치우기까지 실패해 임시 폴더가 남아도 그 안에는 키 모양이 없고(훑기 전에는 쓰지 않았다) 다음 백업이 치운다."""
        token = bs.secret_token(KIND)
        inject(self.world, "주제 보관함 후보", KIND, bs.three_lines(KIND))
        with mock.patch.object(bf, "_finish_folder", side_effect=PermissionError(13, "denied")), mock.patch.object(bf, "_remove_known_folder", return_value=False):
            error = bs.code_of(self.world.backup)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
        left = self.tmp_folders()
        self.assertEqual(len(left), 1, "치우기가 실패해 임시 폴더가 남았다(이 시험의 전제)")
        assert_clean(self, self.world, token, "치우기가 실패한 뒤")
        error = bs.code_of(self.world.backup)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
        self.assertEqual(self.tmp_folders(), [], "다음 백업이 치웠다")

    def test_the_second_look_at_the_written_files_catches_what_the_first_look_missed(self):
        """메모리에서 훑은 결과와 쓴 파일을 훑은 결과가 다르면(이중 확인) 여전히 백업을 만들지 않는다 — 첫 훑기를 끈 모의로 확인한다."""
        inject(self.world, "원고 본문", KIND, bs.three_lines(KIND))
        real = bf._scan_connection

        def blind_in_memory(sink, db, name):
            if db.execute("pragma database_list").fetchall()[0][2] == "":                 # 메모리 사본을 훑을 때만 눈을 감는다(쓴 파일을 훑을 때는 그대로)
                return None
            return real(sink, db, name)
        with mock.patch.object(bf, "_scan_connection", blind_in_memory):
            error = bs.code_of(self.world.backup)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
        self.assertEqual(self.full_names(), [])
        self.assertEqual(self.tmp_folders(), [])


class StagedCopyTest(Base):
    def test_the_database_copy_is_made_in_memory_and_written_only_after_the_scan_is_clean(self):
        order = []
        real_stage, real_scan, real_write = bf._stage_sqlite, bf._scan_connection, bf._write_sqlite

        def stage(*args, **kwargs):
            order.append("stage")
            return real_stage(*args, **kwargs)

        def scan(sink, db, name):
            in_memory = db.execute("pragma database_list").fetchall()[0][2] == ""
            order.append(("scan-memory:" if in_memory else "scan-file:") + name)
            return real_scan(sink, db, name)

        def write(memory, target):
            order.append("write:" + Path(target).name)
            return real_write(memory, target)
        with mock.patch.object(bf, "_stage_sqlite", stage), mock.patch.object(bf, "_scan_connection", scan), mock.patch.object(bf, "_write_sqlite", write):
            self.world.backup()
        store, engine = "chanceblog.db", layout.ENGINE_DB_FILE
        self.assertEqual(order, ["stage", "scan-memory:" + store, "write:" + store, "stage", "scan-memory:" + engine, "write:" + engine, "scan-file:" + store, "scan-file:" + engine],
                         "메모리에서 훑은 뒤에야 쓰고, 쓴 파일은 마지막에 한 번 더 훑는다")

    def test_a_key_in_the_first_database_stops_every_later_write(self):
        """앞의 보관함에 키 모양이 있으면 뒤의 보관함·JSON 도 훑기만 하고 디스크에 쓰지 않는다 — 위치는 모두 모아 알린다."""
        inject(self.world, "원고 본문", KIND, bs.three_lines(KIND))
        inject(self.world, "설정", KIND, bs.three_lines(KIND))
        writes = []
        with mock.patch.object(bf, "_write_sqlite", side_effect=lambda *a: writes.append("sqlite")), mock.patch.object(bf, "_write_durably", side_effect=lambda *a: writes.append("json")):
            error = bs.code_of(self.world.backup)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
        self.assertEqual(writes, [], "키 모양이 있는데 무엇인가를 디스크에 썼다")
        places = {item.where.split(" · ")[0] for item in error.findings}
        self.assertEqual(places, {"글 보관함", "설정"}, "두 곳의 위치를 모두 알린다")

    def test_an_unreadable_settings_file_with_a_key_inside_is_reported_as_a_key_not_silently_dropped(self):
        path = self.world.path("settings.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["extra_unknown"] = bs.secret_text(KIND)                                  # 모르는 칸 — 엄격한 읽기는 이 파일을 '틀린 모양' 으로 거절한다
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        error = bs.code_of(self.world.backup)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
        self.assertEqual(self.full_names(), [])
        self.assertEqual(self.tmp_folders(), [])


RESTORE_POINTS = [("_write_marker", 1, "after"), ("_swap_in", 4, "after"), ("_restore_database", 1, "after"), ("_after_check", 1, "before")]        # 표지를 쓴 직후 · 설정·JSON 을 모두 바꾼 직후(보관함은 옛것) · 첫 보관함을 바꾼 직후 · 마지막 확인 직전


class RestoreKillTest(Base):
    def prepare(self, tmp):
        world = bs.World.cached(tmp)
        outcome = world.backup()
        saved = state_of(world)
        change_everything(world)
        return world, outcome, saved, state_of(world)

    def test_a_restore_killed_at_each_of_four_points_leaves_a_marker_and_the_revert_brings_the_data_back_as_it_was(self):
        """복원이 곳곳에서 죽으면 '복원 진행 중' 표지가 남고(안전 사본 이름 포함), 목록이 쉬운 안내를 줄 수 있고, 안전 사본으로 되돌리면 복원 직전 데이터와 같아진다."""
        for name, nth, when in RESTORE_POINTS:
            with self.subTest(point=f"{name}#{nth} {when}"):
                with tempfile.TemporaryDirectory() as tmp:
                    world, outcome, saved, changed = self.prepare(tmp)
                    done = kill_child(world, name, nth, when, restore=outcome.row.name)
                    self.assertEqual(done.returncode, DIED, f"그 지점에서 죽지 않았다: {done.stderr[-300:]}")
                    pending = bf.list_full_backups(world.ctx).interrupted
                    self.assertIsNotNone(pending, "복원이 멈춘 흔적이 목록에 없다")
                    self.assertEqual((pending.backup, pending.can_revert), (outcome.row.name, True))
                    self.assertRegex(pending.safety, bf.SAFETY_NAME.pattern)
                    self.assertRegex(pending.started_at, r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z$")
                    world.ctx.clock.advance(seconds=30)
                    result = bf.revert_interrupted_restore(world.ctx, confirmed=True)
                    self.assertEqual(result.source, pending.safety)
                    self.assertEqual(state_of(world), changed, "안전 사본으로 되돌리면 복원 직전의 데이터와 같아야 한다")
                    self.assertIsNone(bf.list_full_backups(world.ctx).interrupted, "되돌린 뒤에는 안내가 사라진다")
                    self.assertFalse(bf._marker_path(world.ctx).exists())

    def test_running_the_same_restore_again_after_the_kill_finishes_it_and_clears_the_marker(self):
        for name, nth, when in RESTORE_POINTS:
            with self.subTest(point=f"{name}#{nth} {when}"):
                with tempfile.TemporaryDirectory() as tmp:
                    world, outcome, saved, changed = self.prepare(tmp)
                    self.assertEqual(kill_child(world, name, nth, when, restore=outcome.row.name).returncode, DIED)
                    world.ctx.clock.advance(seconds=30)
                    bf.restore_full_backup(world.ctx, outcome.row.name, confirmed=True)
                    self.assertEqual(state_of(world), saved)
                    self.assertIsNone(bf.list_full_backups(world.ctx).interrupted)

    def test_the_marker_names_only_the_backup_the_safety_copy_and_the_files_and_no_path_or_text(self):
        outcome = self.world.backup()
        change_everything(self.world)
        seen = []
        real = bf._write_marker

        def spy(ctx, folder, safety_name, names, moment):
            real(ctx, folder, safety_name, names, moment)
            seen.append(bf._marker_path(ctx).read_bytes())
        with mock.patch.object(bf, "_write_marker", spy):
            bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        data = json.loads(seen[0].decode("utf-8"))
        self.assertEqual(set(data), bf.MARKER_KEYS)
        self.assertEqual((data["schema"], data["backup"]), (1, outcome.row.name))
        self.assertRegex(data["safety"], bf.SAFETY_NAME.pattern)
        self.assertEqual(data["files"], [component.name for component in bf.COMPONENTS if component.name in self.world.manifest(outcome)["files"]])
        self.assertNotIn(self.tmp.name.encode("utf-8"), seen[0], "이 PC 의 경로가 표지에 있다")
        self.assertNotIn("예시 본문".encode("utf-8"), seen[0], "글 내용이 표지에 있다")
        self.assertFalse(bf._marker_path(self.ctx).exists(), "복원이 끝나면 표지가 없다")

    def test_a_restore_that_ends_normally_or_is_rolled_back_completely_leaves_no_marker(self):
        outcome = self.world.backup()
        change_everything(self.world)
        with mock.patch.object(bf, "_restore_database", side_effect=sqlite3.OperationalError("disk I/O error")):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "RESTORE_FAILED")
        self.assertFalse(bf._marker_path(self.ctx).exists(), "원래대로 돌렸는데 표지가 남았다")
        self.assertIsNone(bf.list_full_backups(self.ctx).interrupted)
        bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertFalse(bf._marker_path(self.ctx).exists())

    def test_a_restore_that_could_not_be_rolled_back_completely_keeps_the_marker_so_the_notice_stays(self):
        outcome = self.world.backup()
        change_everything(self.world)
        with mock.patch.object(bf, "_apply", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})), mock.patch.object(bf, "_roll_back", return_value=("설정은 원래 내용으로 돌리지 못했어요",)):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "RESTORE_FAILED")
        pending = bf.list_full_backups(self.ctx).interrupted
        self.assertIsNotNone(pending)
        self.assertTrue(pending.can_revert)

    def test_the_revert_needs_the_confirmation_and_a_trace_and_a_safety_copy(self):
        self.assertEqual(bs.code_of(bf.revert_interrupted_restore, self.ctx, confirmed=True).code, "CONTENT_NOT_FOUND")
        outcome = self.world.backup()
        change_everything(self.world)
        with mock.patch.object(bf, "_apply", side_effect=KeyboardInterrupt()), mock.patch.object(bf, "_roll_back", return_value=("x",)):
            with self.assertRaises(KeyboardInterrupt):
                bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        before = state_of(self.world)
        self.assertEqual(bs.code_of(bf.revert_interrupted_restore, self.ctx, confirmed=False).code, "CONFIRMATION_REQUIRED")
        self.assertEqual(state_of(self.world), before, "확인 없이 아무것도 바뀌지 않는다")
        pending = bf.list_full_backups(self.ctx).interrupted
        shutil.rmtree(self.backups / bf.SAFETY_FOLDER / pending.safety)
        pending = bf.list_full_backups(self.ctx).interrupted
        self.assertFalse(pending.can_revert, "안전 사본이 없으면 되돌릴 수 없다고 알린다")
        error = bs.code_of(bf.revert_interrupted_restore, self.ctx, confirmed=True)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "missing"))
        self.assertEqual(state_of(self.world), before)

    def test_a_marker_that_cannot_be_read_still_tells_that_a_restore_stopped_but_cannot_be_reverted(self):
        self.backups.mkdir(parents=True, exist_ok=True)
        for raw in (b"not json", b'{"schema": 1}', b'{"schema": 2, "started": "2026-11-11T05:00:00Z", "backup": "x", "safety": "", "files": []}', b"\xff\xfe"):
            (self.backups / bf.RESTORE_MARKER).write_bytes(raw)
            pending = bf.list_full_backups(self.ctx).interrupted
            self.assertEqual((pending.started_at, pending.backup, pending.safety, pending.can_revert), ("", "", "", False), raw)
            self.assertEqual(bs.code_of(bf.revert_interrupted_restore, self.ctx, confirmed=True).code, "FULL_BACKUP_INVALID")

    def test_a_marker_with_an_extra_field_or_a_wrong_kind_of_value_is_not_trusted(self):
        self.backups.mkdir(parents=True, exist_ok=True)
        good = {"schema": 1, "started": "2026-11-11T05:00:00Z", "backup": "full-20261111-050000", "safety": "before-20261111-050000", "files": ["chanceblog.db"]}
        for label, change in (("칸이 하나 더", lambda data: data.update(extra=1)), ("칸이 하나 없음", lambda data: data.pop("files")), ("files 가 목록이 아님", lambda data: data.update(files="chanceblog.db")),
                              ("files 에 모르는 이름", lambda data: data.update(files=["../x"])), ("started 모양이 틀림", lambda data: data.update(started="어제")), ("backup 이 글이 아님", lambda data: data.update(backup=5)),
                              ("safety 가 글이 아님", lambda data: data.update(safety=None)), ("schema 가 2", lambda data: data.update(schema=2))):
            with self.subTest(label=label):
                data = dict(good)
                change(data)
                (self.backups / bf.RESTORE_MARKER).write_text(json.dumps(data), encoding="utf-8")
                pending = bf.interrupted_restore(self.ctx)
                self.assertEqual((pending.started_at, pending.backup, pending.safety, pending.can_revert), ("", "", "", False))
        (self.backups / bf.RESTORE_MARKER).write_text(json.dumps(good), encoding="utf-8")
        pending = bf.interrupted_restore(self.ctx)
        self.assertEqual((pending.started_at, pending.backup, pending.safety, pending.can_revert), ("2026-11-11T05:00:00Z", good["backup"], good["safety"], False), "안전 사본 폴더가 없으면 되돌릴 수 없다")

    def test_names_in_the_marker_that_do_not_look_like_the_apps_own_are_not_repeated(self):
        self.backups.mkdir(parents=True, exist_ok=True)
        data = {"schema": 1, "started": "2026-11-11T05:00:00Z", "backup": "C:/somewhere/else", "safety": "../../etc", "files": ["chanceblog.db"]}
        (self.backups / bf.RESTORE_MARKER).write_text(json.dumps(data), encoding="utf-8")
        pending = bf.list_full_backups(self.ctx).interrupted
        self.assertEqual((pending.backup, pending.safety, pending.can_revert), ("", "", False))

    def test_a_restore_that_cannot_write_the_marker_stops_before_changing_anything(self):
        outcome = self.world.backup()
        change_everything(self.world)
        before = state_of(self.world)
        with mock.patch.object(bf, "_write_marker", side_effect=OSError(28, "No space left on device")):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("RESTORE_FAILED", "disk"))
        self.assertEqual(state_of(self.world), before)

    def test_a_restore_that_is_running_right_now_is_not_reported_as_stopped(self):
        """복원이 도는 동안에도 표지는 있다 — 다른 창이 그때 목록을 읽어도 '멈췄다' 고 알리지 않는다(살아 있는 복원이 잠금을 쥐고 있다)."""
        outcome = self.world.backup()
        with mock.patch.object(bf, "_apply", side_effect=KeyboardInterrupt()), mock.patch.object(bf, "_roll_back", return_value=("x",)):
            with self.assertRaises(KeyboardInterrupt):
                bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertIsNotNone(bf.list_full_backups(self.ctx).interrupted, "시험의 전제 — 멈춘 복원의 표지가 있다")
        with bf._flow_lock(self.ctx):
            self.assertIsNone(bf.list_full_backups(self.ctx).interrupted, "도는 복원을 멈춘 것으로 알렸다")
            self.assertTrue(bf._marker_path(self.ctx).is_file(), "목록은 표지를 건드리지 않는다")
        self.assertIsNotNone(bf.list_full_backups(self.ctx).interrupted)
        self.assertEqual(sorted(path.name for path in self.ctx.workspace.locks_dir.iterdir()), [], "잠금을 잡아 본 뒤 풀었다")

    def test_a_dead_restores_stale_lock_does_not_hide_the_stopped_restore(self):
        outcome = self.world.backup()
        with mock.patch.object(bf, "_apply", side_effect=KeyboardInterrupt()), mock.patch.object(bf, "_roll_back", return_value=("x",)):
            with self.assertRaises(KeyboardInterrupt):
                bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        lock = bf._FlowLock(self.ctx.workspace.locks_dir, bf.LOCK_NAME, now=self.ctx.now, host="")
        lock._prepare_folder()
        lock._create()
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=False):
            self.assertIsNotNone(bf.list_full_backups(self.ctx).interrupted)
        self.assertEqual(sorted(path.name for path in self.ctx.workspace.locks_dir.iterdir()), [])

    def test_a_normal_listing_has_no_interrupted_restore(self):
        self.world.backup()
        self.assertIsNone(bf.list_full_backups(self.ctx).interrupted)
        self.assertIsNone(bf.interrupted_restore(self.ctx))


if __name__ == "__main__":
    unittest.main()
