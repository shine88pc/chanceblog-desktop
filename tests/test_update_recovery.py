"""`update/recovery.py` 시험(UPDATE 설계서 3-6 복구 모드, v1update U-2) — 연속 시작 실패 판정·안내 데이터·복구 순서.

지키는 것:
  1) 복구 안내는 `pending.to` 가 지금 버전이고 정상 표식 없이 기준(2)번 이상 시작했을 때만이다(기준 − 1 번이거나 다른 버전이거나 `pending` 이 없으면 아니다).
  2) 안내 데이터: 제목·본문(오류 표의 `UPDATE_RECOVERY_NEEDED` 문구)·단추 이름 둘 — 명령·경로·진단용 글이 없고, **데이터는 사용자의 선택 없이 시작하지 않는다**(이 모듈에는 상자를 띄우거나 복구를 시작하는 코드가 없다).
  3) 낮은 판 허용은 `pending.from` 하나뿐이다(같은 순서의 판만, 그 밖의 낮은 판·높은 판·기록 없음은 거절).
  4) 복구 순서: 잠금 → 데이터(이관됐거나 모를 때만 복원) → 이전 판 구하기 → 적용 → 기록. 어느 단계가 실패해도 거기서 멈추고(뒤 단계는 부르지 않는다) `UPDATE_ROLLBACK_FAILED` + 단계 이름이고,
     결과 기록은 `rollback_failed` 이며 잠금은 항상 푼다. 잠금을 못 잡으면 `UPDATE_IN_PROGRESS` 가 그대로 나가고 아무것도 시작하지 않는다.
네트워크·파일 없이 돈다(부품은 모두 가짜).
"""
import dataclasses
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.update import recovery, state  # noqa: E402

PENDING = state.Pending("1.0.0", "1.0.1", 20261201030000, "full-20261201-040000", "2026-12-01T04:00:00Z", 2, "velopack")


class NeedsRecoveryTest(unittest.TestCase):
    def test_only_after_the_threshold_of_unhealthy_starts_with_the_same_new_version(self):
        for attempts, expected in ((0, False), (1, False), (2, True), (3, True), (50, True)):
            pending = dataclasses.replace(PENDING, boot_attempts=attempts)
            self.assertEqual(recovery.needs_recovery(state.State(pending=pending), "1.0.1"), expected, attempts)
        self.assertEqual(state.RECOVERY_AFTER_FAILED_BOOTS, 2)

    def test_not_for_other_versions_missing_records_or_unreadable_versions(self):
        s = state.State(pending=PENDING)
        for version in ("1.0.0", "1.0.2", "", "x", None):
            self.assertFalse(recovery.needs_recovery(s, version), repr(version))
        self.assertTrue(recovery.needs_recovery(s, "1.0.1+5"))
        self.assertFalse(recovery.needs_recovery(state.State(), "1.0.1"))
        self.assertFalse(recovery.needs_recovery(None, "1.0.1"))


class PromptTest(unittest.TestCase):
    def test_the_prompt_text_comes_from_the_error_table_and_names_two_buttons(self):
        from chanceblog_desktop.errors import render
        prompt = recovery.prompt_for(PENDING)
        shown = render("UPDATE_RECOVERY_NEEDED")
        self.assertIn(shown.message, prompt.text)
        self.assertIn(shown.card_action, prompt.text)
        self.assertEqual((prompt.title, prompt.recover_label, prompt.later_label), ("ChanceBlog Desktop 업데이트 복구", "복구", "나중에"))
        self.assertEqual(recovery.prompt_for(None).text, prompt.text)

    def test_the_prompt_has_no_commands_paths_options_or_diagnostic_words(self):
        text = recovery.prompt_for(PENDING).text
        for word in ("python", "--", ".json", ".exe", "C:\\", "/", "터미널", "명령", "HKEY", "http", "~", "{", "}"):
            self.assertNotIn(word, text, word)
        self.assertIn("두 번 연속", text)
        self.assertIn("'복구'", text)

    def test_the_module_has_no_way_to_show_a_box_or_start_anything_by_itself(self):
        text = (ROOT / "src" / "chanceblog_desktop" / "update" / "recovery.py").read_text(encoding="utf-8")
        for word in ("ctypes", "MessageBox", "subprocess", "os.system", "Popen", "threading", "open(", "write_text", "unlink", "rmtree"):
            self.assertNotIn(word, text, word)


class DowngradeTargetTest(unittest.TestCase):
    def test_only_the_version_before_the_update_may_be_installed_by_the_recovery(self):
        self.assertEqual(recovery.downgrade_target(PENDING), "1.0.0")
        self.assertEqual(recovery.downgrade_target(None), "")
        self.assertTrue(recovery.may_downgrade_to(PENDING, "1.0.0"))
        self.assertTrue(recovery.may_downgrade_to(PENDING, "1.0.0+9"))
        for version in ("0.9.9", "0.9.0", "1.0.0-rc.1", "1.0.1", "1.0.2", "2.0.0", "", "x", None, 1):
            self.assertFalse(recovery.may_downgrade_to(PENDING, version), repr(version))
        self.assertFalse(recovery.may_downgrade_to(None, "1.0.0"))

    def test_restoring_data_happens_when_migrated_or_unknown_but_not_when_clearly_not_migrated(self):
        self.assertTrue(recovery.should_restore_data(True))
        self.assertTrue(recovery.should_restore_data(None))
        self.assertFalse(recovery.should_restore_data(False))


class Recorder:
    """주입 부품 묶음 — 불린 순서를 기록하고 단계마다 실패를 흉내 낸다."""

    def __init__(self, migrated=True, fail_at=None, fail_with=None, busy=False):
        self.calls = []
        self.migrated = migrated
        self.fail_at = fail_at
        self.fail_with = fail_with or AppError("DISK_FULL")
        self.busy = busy
        self.released = 0

    def _step(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise self.fail_with

    def acquire_lock(self):
        self.calls.append("lock")
        if self.busy:
            raise AppError("UPDATE_IN_PROGRESS", {"시작": "방금"})
        recorder = self

        class Lock:
            def release(self):
                recorder.released += 1
        return Lock()

    def data_migrated(self):
        self.calls.append("migrated?")
        if self.fail_at == "migrated?":
            raise RuntimeError("secret detail C:/Users/someone")
        return self.migrated

    def restore_backup(self, name):
        self._step(f"restore:{name}")

    def obtain_previous(self, version):
        self._step(f"obtain:{version}")
        return {"version": version}

    def apply_previous(self, package, version):
        self._step(f"apply:{version}")

    def record(self, result, restored):
        self.calls.append(f"record:{result}:{restored}")
        if self.fail_at == "record":
            raise RuntimeError("record failed")

    def run(self, pending=PENDING):
        return recovery.run_recovery(pending, acquire_lock=self.acquire_lock, data_migrated=self.data_migrated, restore_backup=self.restore_backup, obtain_previous=self.obtain_previous,
                                     apply_previous=self.apply_previous, record=self.record)


class RunRecoveryTest(unittest.TestCase):
    def test_the_whole_order_when_the_data_was_migrated(self):
        recorder = Recorder(migrated=True)
        outcome = recorder.run()
        self.assertEqual(recorder.calls, ["lock", "migrated?", "restore:full-20261201-040000", "obtain:1.0.0", "apply:1.0.0", "record:rolled_back:True"])
        self.assertEqual((outcome.restored_data, outcome.steps), (True, ("lock", "data", "installer", "apply", "record")))
        self.assertEqual(recorder.released, 1)

    def test_when_the_data_clearly_was_not_migrated_it_is_left_alone(self):
        recorder = Recorder(migrated=False)
        outcome = recorder.run()
        self.assertNotIn("restore:full-20261201-040000", recorder.calls)
        self.assertEqual((outcome.restored_data, recorder.calls[-1]), (False, "record:rolled_back:False"))

    def test_when_it_is_unknown_the_data_is_restored(self):
        recorder = Recorder(migrated=None)
        self.assertTrue(recorder.run().restored_data)

    def test_a_failure_in_any_step_stops_there_records_the_failure_and_names_the_step(self):
        cases = (("migrated?", "data"), ("restore:full-20261201-040000", "data"), ("obtain:1.0.0", "installer"), ("apply:1.0.0", "apply"), ("record", "record"))
        for fail_at, step in cases:
            with self.subTest(fail_at=fail_at):
                recorder = Recorder(fail_at=fail_at)
                with self.assertRaises(recovery.RollbackFailure) as caught:
                    recorder.run()
                self.assertEqual(caught.exception.step, step)
                self.assertEqual(caught.exception.code, "UPDATE_ROLLBACK_FAILED")
                index = next(position for position, call in enumerate(recorder.calls) if call.startswith(fail_at))
                after = [call for call in recorder.calls[index + 1:] if not call.startswith("record:")]
                self.assertEqual(after, [], "실패한 단계 뒤의 단계는 부르지 않는다")
                restored = fail_at in ("obtain:1.0.0", "apply:1.0.0", "record")                     # 복원이 이미 끝난 뒤의 실패인가
                self.assertEqual(recorder.calls[-1], f"record:rollback_failed:{restored}")
                self.assertEqual(recorder.released, 1, "잠금은 항상 푼다")

    def test_the_failure_keeps_the_cause_code_but_never_the_text_of_the_cause(self):
        recorder = Recorder(fail_at="restore:full-20261201-040000", fail_with=AppError("DISK_FULL", {"경로": "C:/Users/someone/secret"}, detail="C:/Users/someone/secret"))
        with self.assertRaises(recovery.RollbackFailure) as caught:
            recorder.run()
        error = caught.exception
        self.assertEqual((error.step, error.cause_code), ("data", "DISK_FULL"))
        for shown in (str(error), error.detail, error.log_line(), error.rendered().message, error.rendered().action):
            self.assertNotIn("someone", shown)
            self.assertNotIn("secret", shown)
        recorder = Recorder(fail_at="migrated?")
        with self.assertRaises(recovery.RollbackFailure) as caught:
            recorder.run()
        self.assertEqual(caught.exception.cause_code, "RuntimeError")
        self.assertNotIn("someone", caught.exception.detail)

    def test_the_manual_way_is_in_the_user_text_of_the_failure(self):
        recorder = Recorder(fail_at="apply:1.0.0")
        with self.assertRaises(recovery.RollbackFailure) as caught:
            recorder.run()
        action = caught.exception.rendered().action
        self.assertIn("릴리스 페이지", action)
        self.assertIn("백업·복원", action)

    def test_a_busy_lock_stops_everything_with_its_own_code_and_starts_nothing(self):
        recorder = Recorder(busy=True)
        with self.assertRaises(AppError) as caught:
            recorder.run()
        self.assertEqual(caught.exception.code, "UPDATE_IN_PROGRESS")
        self.assertNotIsInstance(caught.exception, recovery.RollbackFailure)
        self.assertEqual(recorder.calls, ["lock"])
        self.assertEqual(recorder.released, 0)

    def test_without_a_pending_record_nothing_runs(self):
        recorder = Recorder()
        with self.assertRaises(recovery.RollbackFailure):
            recorder.run(pending=None)
        self.assertEqual(recorder.calls, [])

    def test_a_failing_record_after_a_failure_does_not_hide_the_original_failure(self):
        recorder = Recorder(fail_at="apply:1.0.0")
        original = recorder.record

        def broken(result, restored):
            original(result, restored)
            raise RuntimeError("cannot record")
        recorder.record = broken
        with self.assertRaises(recovery.RollbackFailure) as caught:
            recorder.run()
        self.assertEqual(caught.exception.step, "apply")


class ErrorCodesTest(unittest.TestCase):
    def test_the_codes_exist_in_the_catalog_with_the_documented_retry_values(self):
        from chanceblog_desktop.errors import CATALOG
        expected = {"UPDATE_RECOVERY_NEEDED": "no", "UPDATE_ROLLBACK_FAILED": "no", "UPDATE_ROLLED_BACK": "no", "UPDATE_IN_PROGRESS": "after_user"}
        for code, kind in expected.items():
            self.assertEqual(CATALOG[code].retry_kind, kind, code)


if __name__ == "__main__":
    unittest.main()
