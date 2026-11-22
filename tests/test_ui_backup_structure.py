"""조작했을 수 있는 백업(보관함에 트리거·뷰 같은 앱이 만들지 않는 구조)을 화면이 거절할 때의 쉬운 한 줄 시험 — 어댑터(`ui/backups_adapter.py`)와 컨트롤러(`ui/core/backup_view.py`)의 새 이유 `structure` (L8, 결정 D-554).

지키는 것:
  1) 서비스의 `FULL_BACKUP_INVALID`(이유 `structure`)만 화면 실패에 이유 이름이 실린다 — 다른 이유(목록·파일·해시·내용·찾을 수 없음)는 예전처럼 이유 없이 '바뀌었거나 깨져서' 한 문장이다.
  2) 컨트롤러는 그 이유를 쉬운 한 줄로 더한다(`backup_invalid_structure`) — 문장은 정해진 말이라 조작한 파일의 개체 이름·글·경로·오류 코드가 없고, 복원을 하지 않았다는 말과 지금 데이터는 그대로라는 말이 첫 문장에 이미 있다.
  3) 실제 서비스를 진짜 임시 폴더에서 돌려도 같다 — 조작한 백업(목록의 해시를 다시 계산한 것)의 복원 단추가 쉬운 안내로 끝나고 지금 데이터는 그대로이며 목록 줄은 다시 읽는다.
네트워크·실제 자격 증명 관리자 없이 돈다(Qt 를 쓰지 않는 순수 시험).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import test_service_backup_structure as tsb  # noqa: E402

from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.ui import backups_adapter  # noqa: E402
from chanceblog_desktop.ui.core import backup_view, backups, jobs  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402


def quiet(*_):
    return None


def flow_error(reason, code="FULL_BACKUP_INVALID"):
    return bf.FlowError(code, {"파일": "full-20261111-050000", "이유": bf.INVALID_REASONS.get(reason, "x")}, detail="x", reason=reason)


class FailureMappingTest(unittest.TestCase):
    def test_only_the_structure_reason_travels_with_an_invalid_failure(self):
        found = backups_adapter.failure_of(flow_error("structure"))
        self.assertEqual((found.kind, found.code, found.reason), ("invalid", "FULL_BACKUP_INVALID", "structure"))
        for reason in ("manifest", "files", "hash", "content", "missing", "newer", ""):
            with self.subTest(reason=reason):
                other = backups_adapter.failure_of(flow_error(reason))
                self.assertEqual((other.kind, other.reason), ("invalid", ""))

    def test_the_structure_reason_means_nothing_for_other_failure_kinds(self):
        for code in ("RESTORE_FAILED", "BACKUP_FAILED", "FULL_BACKUP_BLOCKED", "DISK_FULL"):
            with self.subTest(code=code):
                found = backups_adapter.failure_of(flow_error("structure", code))
                self.assertNotEqual(found.reason, "structure")

    def test_the_fixed_sentence_is_easy_and_carries_nothing_from_a_file(self):
        text = T["backup_invalid_structure"]
        self.assertTrue(text.startswith("이유: "))
        for word in ("트리거", "뷰", "복원하지 않았어요"):
            self.assertIn(word, text)
        for forbidden in ("FULL_BACKUP", "STORE_", "Traceback", "SELECT", "CREATE", chr(126), "http"):
            self.assertNotIn(forbidden, text)
        self.assertIn("지금 데이터는 그대로", T["backup_fail_invalid"], "첫 문장이 이미 지금 데이터는 그대로라고 말한다")


class ControllerTest(unittest.TestCase):
    def controller(self):
        return backup_view.BackupController(backups.FakeBackupsProvider(), jobs.JobRunner())

    def test_a_structure_refusal_adds_the_one_easy_line_and_asks_for_a_reload(self):
        controller = self.controller()
        failure = backups.make_failure("invalid", "FULL_BACKUP_INVALID", reason="structure")
        self.assertEqual(controller.apply_write_failed(failure), "invalid")
        self.assertEqual(controller.notice, ("error", T["backup_fail_invalid"], (T["backup_invalid_structure"],)))
        self.assertTrue(controller.reload_wanted)

    def test_an_invalid_backup_for_any_other_reason_has_no_extra_line(self):
        controller = self.controller()
        controller.apply_write_failed(backups.make_failure("invalid", "FULL_BACKUP_INVALID"))
        self.assertEqual(controller.notice, ("error", T["backup_fail_invalid"], ()))
        controller.apply_write_failed(backups.make_failure("invalid", "FULL_BACKUP_INVALID", reason="hash"))
        self.assertEqual(controller.notice[2], (), "알 수 없는 이유 이름은 줄이 되지 않는다")

    def test_the_line_is_for_invalid_failures_only(self):
        controller = self.controller()
        for kind in ("blocked", "nothing", "busy", "newer", "disk", "io", "restore", "other"):
            with self.subTest(kind=kind):
                controller.apply_write_failed(backups.make_failure(kind, "X", reason="structure"))
                self.assertNotIn(T["backup_invalid_structure"], controller.notice[2])


class EndToEndTest(unittest.TestCase):
    """진짜 서비스·진짜 임시 폴더 — 조작한 백업을 어댑터로 복원해 본다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = bs.World(self.tmp.name)
        self.ctx = self.world.ctx
        self.provider = backups_adapter.ServiceBackupsProvider(str(self.world.root), context_factory=lambda data_dir=None: self.ctx)

    def test_restoring_a_tampered_backup_ends_in_the_easy_invalid_refusal_and_changes_nothing(self):
        made = self.provider.create_backup(quiet, lambda: False)
        folder = self.ctx.workspace.backups_dir / made.name
        tsb.forge(folder, "chanceblog.db", *tsb.tampering("chanceblog.db")["trigger"])
        before = self.world.data_digests()
        with self.assertRaises(backups.BackupFailure) as caught:
            self.provider.restore_backup(made.name, quiet, lambda: False)
        failure = caught.exception
        self.assertEqual((failure.kind, failure.code, failure.reason), ("invalid", "FULL_BACKUP_INVALID", "structure"))
        blob = " ".join([failure.user_message, failure.code, failure.reason, repr(failure), str(failure)])
        self.assertNotIn(tsb.CANARY, blob)
        self.assertNotIn(str(self.world.root), blob)
        self.assertEqual(self.world.data_digests(), before)
        controller = backup_view.BackupController(self.provider, jobs.JobRunner())
        controller.apply_write_failed(failure)
        self.assertEqual(controller.notice, ("error", T["backup_fail_invalid"], (T["backup_invalid_structure"],)))

    def test_a_clean_backup_restores_through_the_adapter_as_before(self):
        made = self.provider.create_backup(quiet, lambda: False)
        result = self.provider.restore_backup(made.name, quiet, lambda: False)
        self.assertEqual((result.action, result.status), ("restored", "complete"))


if __name__ == "__main__":
    unittest.main()
