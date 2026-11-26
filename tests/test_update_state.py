"""`update/state.py` 시험(UPDATE 설계서 3-5·3-6, v1update U-2) — 상태 파일의 엄격한 읽기·원자적 쓰기·시작 후크(`note_boot`).

지키는 것:
  1) 읽기·쓰기가 왕복하고, 파일이 없으면 처음 상태이며, 모르는 칸·틀린 형(불리언 정수 포함)·틀린 시각·틀린 백업 이름·큰 파일·깨진 글은 `StateError("corrupt")` 다. 깨진 파일은 `.bak` 으로 옮기고 처음부터 시작한다.
  2) 쓰기는 같은 폴더의 임시 파일에 다 쓰고 디스크까지 내린(`fsync`) 뒤 이름을 바꾼다 — 바꾸기가 막혀도(공유 위반 재시도·끝내 실패) 옛 파일이 그대로이고 임시 파일이 남지 않는다.
  3) 시작 후크: 스위치가 꺼져 있으면 **파일을 읽지도 쓰지도 않는다**. 켜면 시작 **전** 횟수가 기준(2) 미만일 때 하나 올려 저장하고(첫·둘째 시작), 기준 이상이면 저장하지 않고 복구를 알리며(셋째 시작),
     `pending.from` 이면 적용 안 됨·그 밖이면 낡은 표식 정리다. 어떤 실패도 None 이고 예외가 아니다. 이 모듈은 앱의 무거운 모듈·접속 코드를 가져오지 않는다.
  4) 데이터 폴더 위치 규칙이 `service/context.py` 와 같다. 상태 파일에는 카나리 글(경로·키 모양)이 들어가지 않는다.
네트워크·실제 시크릿 없이 돈다.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import capability_support as cap  # noqa: E402

from chanceblog_desktop.service import context  # noqa: E402
from chanceblog_desktop.update import state  # noqa: E402

PENDING = state.Pending("1.0.0", "1.0.1", 20261201030000, "full-20261201-040000", "2026-12-01T04:00:00Z", 0, "velopack")


def good_state(**changes):
    values = dict(last_seq=20261201030000, last_seen_utc="2026-12-01T04:00:00Z", last_check=state.LastCheck("2026-12-01T04:00:00Z", "AVAILABLE", "1.0.1", ""), pending=PENDING, last_good="1.0.0", notice="")
    values.update(changes)
    return state.State(**values)


def raw_of(**changes):
    data = state.state_to_dict(good_state())
    data.update(changes)
    return json.dumps(data).encode("utf-8")


class TempCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name) / "update"
        self.addCleanup(cap.switch_off, "UPDATE_APPLY")


class RoundTripTest(TempCase):
    def test_write_then_read_gives_the_same_state_and_the_default_is_the_first_state(self):
        self.assertEqual(state.read_state(self.folder), state.State())
        self.assertEqual((state.State().last_seq, state.State().pending, state.State().last_check, state.State().notice), (0, None, None, ""))
        state.write_state(self.folder, good_state())
        self.assertEqual(state.read_state(self.folder), good_state())
        state.write_state(self.folder, state.State())
        self.assertEqual(state.read_state(self.folder), state.State())

    def test_the_file_is_one_small_json_with_exactly_the_documented_keys_and_no_leftovers(self):
        state.write_state(self.folder, good_state())
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["state.json"], "임시 파일이 남지 않는다")
        data = json.loads((self.folder / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data), set(state.STATE_KEYS))
        self.assertEqual(set(data["pending"]), set(state.PENDING_KEYS))
        self.assertLess((self.folder / "state.json").stat().st_size, 2000)
        text = (self.folder / "state.json").read_text(encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))

    def test_the_state_never_holds_paths_or_text_from_outside(self):
        canary = "CANARY_" + "PATH_" + "C:/Users/someone"
        state.write_state(self.folder, good_state())
        self.assertNotIn(canary, (self.folder / "state.json").read_text(encoding="utf-8"))
        self.assertNotIn(str(self.folder), (self.folder / "state.json").read_text(encoding="utf-8"))


class StrictReadTest(TempCase):
    def write_raw(self, raw):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "state.json").write_bytes(raw)

    def test_each_wrong_shape_is_corrupt(self):
        cases = {
            "모르는 칸": raw_of(extra=1), "빠진 칸": json.dumps({k: v for k, v in state.state_to_dict(good_state()).items() if k != "notice"}).encode(),
            "스키마 2": raw_of(schema=2), "스키마 불리언": raw_of(schema=True), "seq 불리언": raw_of(last_seq=True), "seq 음수": raw_of(last_seq=-1), "seq 글": raw_of(last_seq="1"), "seq 너무 큼": raw_of(last_seq=2 ** 54),
            "시각 모양": raw_of(last_seen_utc="2026-12-01 04:00:00"), "시각 날짜": raw_of(last_seen_utc="2026-02-30T04:00:00Z"), "안내 모르는 값": raw_of(notice="other"),
            "정상 판 글자": raw_of(last_good="x"), "확인 결과 모름": raw_of(last_check={"at": "2026-12-01T04:00:00Z", "result": "OK", "version": "", "code": ""}),
            "확인 칸 모자람": raw_of(last_check={"at": "2026-12-01T04:00:00Z", "result": "AVAILABLE"}), "코드 소문자": raw_of(last_check={"at": "2026-12-01T04:00:00Z", "result": "CHECK_FAILED", "version": "", "code": "net"}),
            "pending 글": raw_of(pending="x"), "pending 칸 모자람": raw_of(pending={"from_version": "1.0.0"}),
            "pending 백업 이름": raw_of(pending={**state.state_to_dict(good_state())["pending"], "backup_name": "../x"}),
            "pending 종류": raw_of(pending={**state.state_to_dict(good_state())["pending"], "kind": "msi"}),
            "pending 횟수 음수": raw_of(pending={**state.state_to_dict(good_state())["pending"], "boot_attempts": -1}),
            "pending 횟수 불리언": raw_of(pending={**state.state_to_dict(good_state())["pending"], "boot_attempts": True}),
            "pending 버전": raw_of(pending={**state.state_to_dict(good_state())["pending"], "to_version": "1.0"}),
            "깨진 JSON": b"{not json", "같은 키": b'{"schema": 1, "schema": 1}', "배열": b"[]", "빈 파일": b"", "BOM": b"\xef\xbb\xbf" + raw_of(),
        }
        for label, raw in cases.items():
            with self.subTest(label=label):
                self.write_raw(raw)
                with self.assertRaises(state.StateError) as caught:
                    state.read_state(self.folder)
                self.assertEqual(caught.exception.reason, "corrupt")

    def test_a_file_over_the_size_limit_is_corrupt_without_being_read_into_memory_as_json(self):
        self.write_raw(b" " * (state.MAX_STATE_BYTES + 1) + raw_of())
        with self.assertRaises(state.StateError) as caught:
            state.read_state(self.folder)
        self.assertEqual(caught.exception.reason, "corrupt")

    def test_the_boundary_values_are_accepted(self):
        for changes in (dict(last_seq=0), dict(last_seq=2 ** 53), dict(last_seen_utc=""), dict(last_good=""), dict(pending=None), dict(last_check=None), dict(notice="rolled_back"),
                        dict(pending=state.Pending("1.0.0", "1.0.1", 1, "full-20261201-040000-12", "2026-12-01T04:00:00Z", 1000, "inno"))):
            with self.subTest(changes=repr(changes)[:60]):
                state.write_state(self.folder, good_state(**changes))
                self.assertEqual(state.read_state(self.folder), good_state(**changes))

    def test_an_unreadable_file_is_unreadable_not_corrupt(self):
        state.write_state(self.folder, good_state())
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("x")):
            with self.assertRaises(state.StateError) as caught:
                state.read_state(self.folder)
        self.assertEqual(caught.exception.reason, "unreadable")

    def test_a_corrupt_file_is_kept_as_bak_and_loading_starts_fresh(self):
        self.write_raw(b"{broken")
        self.assertEqual(state.load_state(self.folder), state.State())
        self.assertEqual((self.folder / "state.json.bak").read_bytes(), b"{broken")
        self.assertFalse((self.folder / "state.json").exists())
        state.write_state(self.folder, good_state())
        self.assertEqual(state.load_state(self.folder), good_state())

    def test_loading_an_unreadable_file_does_not_move_it(self):
        state.write_state(self.folder, good_state())
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("x")):
            with self.assertRaises(state.StateError):
                state.load_state(self.folder)
        self.assertTrue((self.folder / "state.json").exists())
        self.assertFalse((self.folder / "state.json.bak").exists())


class AtomicWriteTest(TempCase):
    def test_the_write_goes_to_a_temp_file_in_the_same_folder_is_flushed_and_then_renamed(self):
        calls = []
        real_replace, real_fsync = os.replace, os.fsync
        with mock.patch.object(os, "replace", side_effect=lambda a, b: (calls.append(("replace", Path(a).parent, Path(b).name)), real_replace(a, b))[1]), \
                mock.patch.object(os, "fsync", side_effect=lambda fd: (calls.append(("fsync",)), real_fsync(fd))[1]):
            state.write_state(self.folder, good_state())
        self.assertEqual(calls, [("fsync",), ("replace", self.folder, "state.json")])

    def test_a_failed_rename_keeps_the_old_file_and_leaves_no_temp_file(self):
        state.write_state(self.folder, good_state(last_seq=5))
        with mock.patch.object(os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(state.StateError) as caught:
                state.write_state(self.folder, good_state(last_seq=9))
        self.assertEqual(caught.exception.reason, "write")
        self.assertEqual(state.read_state(self.folder).last_seq, 5)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["state.json"])

    def test_a_sharing_violation_is_retried_a_few_times_and_then_succeeds(self):
        state.write_state(self.folder, good_state(last_seq=5))
        real = os.replace
        attempts = []

        def flaky(source, target):
            attempts.append(1)
            if len(attempts) < 3:
                error = PermissionError("busy")
                error.winerror = 32
                raise error
            return real(source, target)
        with mock.patch.object(os, "replace", flaky), mock.patch.object(state.time, "sleep") as slept:
            state.write_state(self.folder, good_state(last_seq=9))
        self.assertEqual((len(attempts), slept.call_count), (3, 2))
        self.assertEqual(state.read_state(self.folder).last_seq, 9)

    def test_other_permission_errors_are_not_retried(self):
        attempts = []

        def deny(source, target):
            attempts.append(1)
            raise PermissionError("denied")
        with mock.patch.object(os, "replace", deny), mock.patch.object(state.time, "sleep") as slept:
            with self.assertRaises(state.StateError):
                state.write_state(self.folder, good_state())
        self.assertEqual((len(attempts), slept.call_count), (1, 0))
        self.assertEqual(list(self.folder.iterdir()) if self.folder.exists() else [], [])

    def test_a_killed_write_before_the_rename_leaves_the_old_file_intact(self):
        state.write_state(self.folder, good_state(last_seq=5))

        class Killed(BaseException):
            pass
        with mock.patch.object(os, "replace", side_effect=Killed()):
            with self.assertRaises(Killed):
                state.write_state(self.folder, good_state(last_seq=9))
        self.assertEqual(state.read_state(self.folder).last_seq, 5, "중간에 죽어도 옛 파일 그대로")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["state.json"], "끊겨도 임시 파일을 치운다")


class BootHookTest(TempCase):
    def setUp(self):
        super().setUp()
        cap.switch_on("UPDATE_APPLY")

    def seed(self, **changes):
        state.write_state(self.folder, good_state(**changes))

    def test_a_first_start_of_the_new_version_counts_up_and_saves_before_returning(self):
        self.seed()
        note = state.note_boot(version="1.0.1", folder=self.folder)
        self.assertEqual((note.action, note.attempts_before, note.pending.boot_attempts), ("first_boot", 0, 1))
        self.assertEqual(state.read_state(self.folder).pending.boot_attempts, 1, "돌려주기 전에 저장했다")

    def test_the_third_start_offers_recovery_and_changes_nothing(self):
        self.seed()
        seen = [state.note_boot(version="1.0.1", folder=self.folder).action for _ in range(3)]
        self.assertEqual(seen, ["first_boot", "first_boot", "recovery_offered"])
        again = state.note_boot(version="1.0.1", folder=self.folder)
        self.assertEqual((again.action, again.attempts_before, state.read_state(self.folder).pending.boot_attempts), ("recovery_offered", 2, 2))
        self.assertEqual(state.RECOVERY_AFTER_FAILED_BOOTS, 2)

    def test_a_healthy_mark_between_starts_resets_the_count(self):
        self.seed()
        self.assertEqual(state.note_boot(version="1.0.1", folder=self.folder).action, "first_boot")
        from chanceblog_desktop.update import health
        health.mark_healthy(self.folder)
        self.assertEqual(state.read_state(self.folder).pending, None)
        self.assertEqual(state.note_boot(version="1.0.1", folder=self.folder).action, "none")

    def test_the_old_version_still_running_means_the_update_was_not_applied(self):
        self.seed()
        note = state.note_boot(version="1.0.0", folder=self.folder)
        self.assertEqual((note.action, note.pending), ("not_applied", None))
        after = state.read_state(self.folder)
        self.assertEqual((after.pending, after.notice, after.last_seq), (None, "not_applied", PENDING.seq), "표식은 지우고 seq 는 그대로")

    def test_an_unrelated_version_clears_the_stale_marker(self):
        self.seed()
        note = state.note_boot(version="2.0.0", folder=self.folder)
        self.assertEqual((note.action, state.read_state(self.folder).notice), ("stale_cleared", "pending_stale"))

    def test_build_metadata_does_not_change_which_version_it_is(self):
        self.seed()
        self.assertEqual(state.note_boot(version="1.0.1+7", folder=self.folder).action, "first_boot")

    def test_no_pending_means_nothing_to_do_and_nothing_is_written(self):
        self.seed(pending=None)
        before = (self.folder / "state.json").read_bytes()
        self.assertEqual(state.note_boot(version="1.0.1", folder=self.folder).action, "none")
        self.assertEqual((self.folder / "state.json").read_bytes(), before)
        empty = self.folder.parent / "nothing"
        self.assertEqual(state.note_boot(version="1.0.1", folder=empty).action, "none")
        self.assertFalse(empty.exists(), "상태 파일이 없으면 폴더도 만들지 않는다")

    def test_every_failure_is_none_and_never_an_exception(self):
        self.seed()
        (self.folder / "state.json").write_bytes(b"{broken")
        self.assertIsNone(state.note_boot(version="1.0.1", folder=self.folder))
        self.assertEqual((self.folder / "state.json").read_bytes(), b"{broken", "깨진 파일은 후크가 건드리지 않는다")
        self.seed()
        for version in ("", "x", None):
            self.assertIsNone(state.note_boot(version=version if version is not None else "", folder=self.folder), repr(version))
        with mock.patch.object(state, "write_state", side_effect=state.StateError("write")):
            self.assertIsNone(state.note_boot(version="1.0.1", folder=self.folder))
        with mock.patch.object(state, "read_state", side_effect=RuntimeError("x")):
            self.assertIsNone(state.note_boot(version="1.0.1", folder=self.folder))

    def test_the_folder_comes_from_the_data_dir_and_the_environment_like_the_service_does(self):
        data = self.folder.parent
        state.write_state(data / "update", good_state())
        self.assertEqual(state.note_boot(version="1.0.1", data_dir=data).action, "first_boot")
        env = {"CHANCEBLOG_DESKTOP_DATA": str(data)}
        self.assertEqual(state.note_boot(version="1.0.1", environ=env).action, "first_boot")


class SwitchOffTest(TempCase):
    def test_while_the_switch_is_off_the_hook_neither_reads_nor_writes_anything(self):
        state.write_state(self.folder, good_state())
        before = (self.folder / "state.json").read_bytes()
        names_before = sorted(path.name for path in self.folder.iterdir())
        with mock.patch.object(state, "read_state", side_effect=AssertionError("읽으면 안 된다")), mock.patch.object(state, "write_state", side_effect=AssertionError("쓰면 안 된다")), \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("읽으면 안 된다")), mock.patch.object(os, "replace", side_effect=AssertionError("바꾸면 안 된다")):
            for _ in range(3):
                self.assertIsNone(state.note_boot(version="1.0.1", folder=self.folder))
        self.assertEqual((self.folder / "state.json").read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), names_before)

    def test_look_alike_true_values_do_not_wake_the_hook(self):
        state.write_state(self.folder, good_state())
        for value in (1, "yes", "True", [1], object()):
            with mock.patch("chanceblog_desktop.capabilities.UPDATE_APPLY", value):
                self.assertIsNone(state.note_boot(version="1.0.1", folder=self.folder), repr(value))
        self.assertEqual(state.read_state(self.folder).pending.boot_attempts, 0)


class PlacementTest(unittest.TestCase):
    def test_the_data_folder_rules_equal_the_services(self):
        self.assertEqual(state.APP_DIR_NAME, context.APP_DIR_NAME)
        self.assertEqual(state.ENV_DATA_DIR, context.ENV_DATA_DIR)
        for env in ({"LOCALAPPDATA": "C:/Users/x/AppData/Local"}, {"XDG_DATA_HOME": "/tmp/xdg"}, {"LOCALAPPDATA": "C:/L", "XDG_DATA_HOME": "/tmp/xdg"}, {}):
            with self.subTest(env=env):
                self.assertEqual(state.default_data_dir(env), context.default_data_dir(env))
        self.assertEqual(state.default_data_dir({"CHANCEBLOG_DESKTOP_DATA": "D:/data"}), Path("D:/data"))
        self.assertEqual(state.update_folder(data_dir="D:/data"), Path("D:/data") / "update")

    def test_the_current_version_is_read_from_the_version_file_and_a_bad_one_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_bytes(b"\xef\xbb\xbf1.0.1\r\n")
            self.assertEqual(state.read_current_version(root), "1.0.1")
            (root / "VERSION").write_text("not a version", encoding="utf-8")
            self.assertEqual(state.read_current_version(root), "")
            (root / "VERSION").unlink()
            self.assertEqual(state.read_current_version(root), "")
        self.assertRegex(state.read_current_version(), r"^[0-9]+\.[0-9]+\.[0-9]+")


class LightImportTest(unittest.TestCase):
    def test_importing_the_state_module_loads_no_heavy_app_module_and_no_connection_code(self):
        code = ("import sys\nsys.path.insert(0, %r)\nimport chanceblog_desktop.update.state\n"
                "bad = [name for name in sys.modules if name.startswith(('chanceblog_desktop.service', 'chanceblog_desktop.ui', 'chanceblog_desktop.content', 'chanceblog_desktop.publish', "
                "'chanceblog_desktop.net', 'chanceblog_desktop.security')) or name in ('ssl', 'http.client', 'socket', 'subprocess', 'PySide6')]\nprint(sorted(bad))\n" % str(ROOT / "src"))
        done = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code], capture_output=True, text=True, timeout=120, env=dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(done.returncode, 0, done.stderr[-400:])
        self.assertEqual(done.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
