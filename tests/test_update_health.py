"""`update/health.py` 시험(UPDATE 설계서 3-5 정상 점검, v1update U-2) — 새 판 첫 시작의 점검·정상 표식·정리.

지키는 것:
  1) 점검: 지금 버전이 `pending.to` 와 같고 데이터 폴더·보관함 점검이 모두 참일 때만 정상이다 — 점검이 빠졌거나 거짓이거나 예외를 내면 실패(정상 표식을 쓰지 않는다).
  2) `HealthMonitor`: 창이 뜬 뒤 15초(경계 포함) 처리 못 한 예외가 없을 때만 정상, 예외가 하나라도 먼저 오면 비정상, 한 번 정해지면 안 바뀐다, 창이 안 뜨면 끝까지 기다림.
  3) 정상 표식은 `pending` 을 지우고 정상 판을 기록하고 안내를 비운다(없으면 그대로). 정리: 임시 폴더를 비우고 복구용 보관은 보호한 판 + 가장 높은 판 순으로 둘까지, 링크는 따라가지도 지우지도 않는다.
네트워크 없이 돈다(파일은 임시 폴더, 시계는 가짜).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.update import health, state  # noqa: E402

PENDING = state.Pending("1.0.0", "1.0.1", 20261201030000, "full-20261201-040000", "2026-12-01T04:00:00Z", 1, "velopack")


def good_probes():
    return {"data_folder": lambda: True, "store": lambda: True}


class StartupChecksTest(unittest.TestCase):
    def test_everything_good_is_healthy(self):
        result = health.startup_checks(PENDING, current_version="1.0.1", probes=good_probes())
        self.assertEqual((result.ok, result.failed), (True, ()))
        self.assertEqual(health.startup_checks(PENDING, current_version="1.0.1+9", probes=good_probes()).ok, True)

    def test_a_wrong_version_fails_and_never_raises(self):
        for version in ("1.0.0", "1.0.2", "", "x", None):
            result = health.startup_checks(PENDING, current_version=version, probes=good_probes())
            self.assertEqual((result.ok, result.failed), (False, ("version",)), repr(version))
        self.assertEqual(health.startup_checks(None, current_version="1.0.1", probes=good_probes()).failed, ("version",))

    def test_a_probe_that_is_false_missing_raising_or_not_exactly_true_fails(self):
        for name in health.PROBE_NAMES:
            for bad in (lambda: False, lambda: None, lambda: 1, lambda: "yes", None):
                probes = good_probes()
                if bad is None:
                    del probes[name]
                else:
                    probes[name] = bad
                result = health.startup_checks(PENDING, current_version="1.0.1", probes=probes)
                self.assertEqual((result.ok, result.failed), (False, (name,)), name)
            probes = good_probes()
            probes[name] = lambda: 1 / 0
            self.assertEqual(health.startup_checks(PENDING, current_version="1.0.1", probes=probes).failed, (name,))
        self.assertEqual(health.startup_checks(PENDING, current_version="1.0.1", probes=None).failed, ("data_folder", "store"))
        self.assertEqual(health.startup_checks(PENDING, current_version="2.0.0", probes={}).failed, ("version", "data_folder", "store"))


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class MonitorTest(unittest.TestCase):
    def test_healthy_only_after_fifteen_quiet_seconds_with_the_window_visible(self):
        clock = FakeClock()
        monitor = health.HealthMonitor(clock)
        self.assertEqual(health.HEALTHY_AFTER_SECONDS if hasattr(health, "HEALTHY_AFTER_SECONDS") else state.HEALTHY_AFTER_SECONDS, 15)
        self.assertEqual(monitor.poll(), "waiting")
        clock.now += 100
        self.assertEqual(monitor.poll(), "waiting", "창이 안 떴으면 얼마가 지나도 정상이 아니다")
        monitor.report_window_visible()
        clock.now += 14.99
        self.assertEqual(monitor.poll(), "waiting")
        clock.now += 0.01
        self.assertEqual(monitor.poll(), "healthy", "정확히 15초는 정상")

    def test_an_exception_before_the_deadline_is_unhealthy_and_the_verdict_is_final(self):
        clock = FakeClock()
        monitor = health.HealthMonitor(clock)
        monitor.report_window_visible()
        clock.now += 5
        monitor.report_exception()
        self.assertEqual(monitor.poll(), "unhealthy")
        clock.now += 100
        self.assertEqual(monitor.poll(), "unhealthy")
        monitor.report_window_visible()
        self.assertEqual(monitor.poll(), "unhealthy")

    def test_an_exception_after_healthy_does_not_change_it_and_the_window_time_is_the_first_one(self):
        clock = FakeClock()
        monitor = health.HealthMonitor(clock)
        monitor.report_window_visible()
        clock.now += 10
        monitor.report_window_visible()                      # 두 번째 알림이 시작 시각을 늦추지 않는다
        clock.now += 5
        self.assertEqual(monitor.poll(), "healthy")
        monitor.report_exception()
        self.assertEqual(monitor.poll(), "healthy")

    def test_an_exception_before_the_window_even_appears_is_unhealthy(self):
        monitor = health.HealthMonitor(FakeClock())
        monitor.report_exception()
        monitor.report_window_visible()
        self.assertEqual(monitor.poll(), "unhealthy")

    def test_the_default_wait_is_the_state_constant_and_a_custom_wait_is_honoured(self):
        clock = FakeClock()
        monitor = health.HealthMonitor(clock, seconds=3)
        monitor.report_window_visible()
        clock.now += 3
        self.assertEqual(monitor.poll(), "healthy")


class MarkHealthyTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name) / "update"

    def test_the_mark_clears_the_pending_record_and_remembers_the_good_version(self):
        state.write_state(self.folder, state.State(last_seq=7, pending=PENDING, last_good="1.0.0", notice="not_applied"))
        done = health.mark_healthy(self.folder)
        self.assertEqual((done.pending, done.last_good, done.notice, done.last_seq), (None, "1.0.1", "", 7))
        self.assertEqual(state.read_state(self.folder), done)

    def test_without_a_pending_record_nothing_is_written(self):
        self.assertEqual(health.mark_healthy(self.folder), state.State())
        self.assertFalse(self.folder.exists())
        state.write_state(self.folder, state.State(last_seq=3, last_good="1.0.1"))
        before = (self.folder / "state.json").read_bytes()
        health.mark_healthy(self.folder)
        self.assertEqual((self.folder / "state.json").read_bytes(), before)

    def test_a_passed_state_is_used_instead_of_reading_again(self):
        state.write_state(self.folder, state.State(pending=PENDING))
        done = health.mark_healthy(self.folder, state.State(pending=PENDING, last_seq=11))
        self.assertEqual(done.last_seq, 11)


class FolderHelpersTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name) / "update"

    def make_keep(self, *names):
        for name in names:
            path = health.keep_dir(self.folder, name)
            path.mkdir(parents=True)
            (path / "installer.bin").write_bytes(b"x")

    def test_keep_names_are_safe_versions_only(self):
        self.assertEqual(health.keep_dir(self.folder, "1.0.1"), self.folder / "keep" / "1.0.1")
        for bad in ("../x", "1.0.0/../../x", "x", "1.0", "", None, "1.0.0\\..", "C:/x", "1.0.0 "):
            with self.assertRaises(ValueError, msg=repr(bad)):
                health.keep_dir(self.folder, bad)

    def test_promote_moves_the_folder_replaces_an_older_copy_and_ignores_missing_sources(self):
        staged = self.folder / "staging" / "run1"
        staged.mkdir(parents=True)
        (staged / "installer.bin").write_bytes(b"new")
        target = health.promote_to_keep(staged, self.folder, "1.0.1")
        self.assertEqual((target, (target / "installer.bin").read_bytes(), staged.exists()), (self.folder / "keep" / "1.0.1", b"new", False))
        again = self.folder / "staging" / "run2"
        again.mkdir()
        (again / "installer.bin").write_bytes(b"newer")
        health.promote_to_keep(again, self.folder, "1.0.1")
        self.assertEqual((self.folder / "keep" / "1.0.1" / "installer.bin").read_bytes(), b"newer")
        self.assertIsNone(health.promote_to_keep(self.folder / "nothing", self.folder, "1.0.1"))

    def test_prune_keeps_the_protected_versions_and_the_highest_up_to_the_limit(self):
        self.make_keep("1.0.0", "1.0.1", "1.0.2", "0.9.0", "1.0.10")
        (self.folder / "keep" / "note.txt").write_text("x", encoding="utf-8")
        (self.folder / "keep" / "notaversion").mkdir()
        removed = health.prune_keep(self.folder, keep_versions=("1.0.1",))
        self.assertEqual(removed, ("0.9.0", "1.0.0", "1.0.2"), "보호한 1.0.1 과 가장 높은 1.0.10 둘만 남는다")
        self.assertEqual(sorted(path.name for path in (self.folder / "keep").iterdir()), ["1.0.1", "1.0.10", "notaversion", "note.txt"])
        self.assertEqual(health.prune_keep(self.folder, keep_versions=("1.0.1",)), ())
        self.assertEqual(health.MAX_KEEP, 2)

    def test_prune_with_two_protected_versions_keeps_exactly_those(self):
        self.make_keep("1.0.0", "1.0.1", "1.0.2")
        self.assertEqual(health.prune_keep(self.folder, keep_versions=("1.0.0", "1.0.1")), ("1.0.2",))

    def test_prune_without_a_keep_folder_does_nothing(self):
        self.assertEqual(health.prune_keep(self.folder, keep_versions=()), ())

    def test_clear_staging_removes_run_folders_and_loose_files_and_counts_them(self):
        root = health.staging_root(self.folder)
        (root / "a").mkdir(parents=True)
        (root / "a" / "x.part").write_bytes(b"1")
        (root / "b").mkdir()
        (root / "loose.tmp").write_bytes(b"2")
        self.assertEqual(health.clear_staging(self.folder), 3)
        self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(health.clear_staging(self.folder), 0)
        self.assertEqual(health.clear_staging(self.folder / "elsewhere"), 0)

    def test_links_are_neither_followed_nor_removed(self):
        outside = self.folder.parent / "outside"
        outside.mkdir(parents=True)
        (outside / "precious.txt").write_text("keep me", encoding="utf-8")
        root = health.staging_root(self.folder)
        root.mkdir(parents=True)
        link = root / "link"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("건너뜀: 이 환경에서는 심볼릭 링크를 만들 수 없다")
        self.assertEqual(health.clear_staging(self.folder), 0)
        self.assertTrue((outside / "precious.txt").exists())
        self.assertTrue(link.exists() or link.is_symlink())
        self.make_keep("1.0.1")
        keep_link = health.keep_root(self.folder) / "9.9.9"
        os.symlink(outside, keep_link, target_is_directory=True)
        health.prune_keep(self.folder, keep_versions=("1.0.1",))
        self.assertTrue((outside / "precious.txt").exists(), "보관 폴더의 링크 너머를 지우지 않는다")
        staged_link = self.folder / "staging" / "src"
        os.symlink(outside, staged_link, target_is_directory=True)
        self.assertIsNone(health.promote_to_keep(staged_link, self.folder, "1.0.2"))
        self.assertTrue((outside / "precious.txt").exists())


if __name__ == "__main__":
    unittest.main()
