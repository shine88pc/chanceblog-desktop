"""복원을 시작하지 않은 쉬운 안내 시험 — 지금 보관함에 앱이 만들지 않는 구조가 있어 복원 직전 사본으로 되돌릴 수 없을 때 화면이 하는 말(L8b, 결정 D-570). 어댑터(`ui/backups_adapter.py`)와 컨트롤러(`ui/core/backup_view.py`)의 새 이유 `live_structure`.

지키는 것:
  1) 서비스의 `RESTORE_FAILED`(이유 `live_structure`)만 화면 실패에 그 이유 이름이 실린다 — 다른 오류 코드에는 실리지 않고 다른 복원 이유(저장 공간·쓰기·점검·다른 곳이 쓰는 중·예상 밖)는 예전 그대로다.
  2) 컨트롤러는 첫 문장에 '복원을 시작하지 않았어요 · 지금 데이터는 그대로예요' 라고 말하고 이유 한 줄(왜 멈췄는지·어떻게 하면 되는지)을 붙인다 — 문장은 정해진 말이라 지금 보관함의 개체 이름·경로·오류 코드가 없다.
     '원래대로 돌려 두었어요' 는 말하지 않는다(바꾼 것이 없었다).
  3) 실제 서비스를 진짜 임시 폴더에서 돌려도 같다 — 지금 보관함에 뷰가 있으면 복원 단추가 쉬운 안내로 끝나고 지금 데이터·안전 사본 폴더는 그대로이며, 그 뷰를 지우면 복원이 되고 그 복원 직전 사본으로 되돌리기도 된다.
네트워크·실제 자격 증명 관리자 없이 돈다(Qt 를 쓰지 않는 순수 시험).
"""
import contextlib
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import test_service_backup_live_structure as tls  # noqa: E402
import test_service_backup_restore as tr  # noqa: E402

from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.ui import backups_adapter  # noqa: E402
from chanceblog_desktop.ui.core import backup_view, backups, jobs  # noqa: E402
from chanceblog_desktop.ui.core.backup_text import BACKUP_T  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

LIVE = "live_structure"


def quiet(*_):
    return None


def flow_error(reason, code="RESTORE_FAILED", notes=()):
    return bf.FlowError(code, {"이유": bf.LIVE_STRUCTURE_TEXT}, detail="x", reason=reason, notes=notes)


class FailureMappingTest(unittest.TestCase):
    def test_the_live_structure_reason_travels_with_a_restore_failure(self):
        found = backups_adapter.failure_of(flow_error(bf.LIVE_STRUCTURE))
        self.assertEqual((found.kind, found.code, found.reason), ("restore", "RESTORE_FAILED", LIVE))
        self.assertEqual(backups_adapter.LIVE_STRUCTURE_REASON, bf.LIVE_STRUCTURE, "서비스와 어댑터가 같은 이름을 쓴다")

    def test_the_reason_means_nothing_for_other_error_codes(self):
        for code in ("FULL_BACKUP_INVALID", "BACKUP_FAILED", "FULL_BACKUP_BLOCKED", "DISK_FULL", "STORE_LOCKED", "UNEXPECTED_ERROR"):
            with self.subTest(code=code):
                found = backups_adapter.failure_of(flow_error(LIVE, code))
                self.assertNotEqual(found.reason, LIVE)

    def test_the_other_restore_reasons_are_unchanged(self):
        for reason in backups_adapter.RESTORE_REASONS:
            with self.subTest(reason=reason):
                self.assertEqual(backups_adapter.failure_of(flow_error(reason)).reason, reason)
        for reason in ("safety", "", "structure", "nonsense"):
            with self.subTest(reason=reason):
                self.assertEqual(backups_adapter.failure_of(flow_error(reason)).reason, "", "알 수 없는 이유 이름은 실리지 않는다")

    def test_the_structure_reason_of_an_invalid_backup_is_still_its_own_thing(self):
        found = backups_adapter.failure_of(flow_error("structure", "FULL_BACKUP_INVALID"))
        self.assertEqual((found.kind, found.reason), ("invalid", "structure"))

    def test_the_reason_list_the_adapter_names_did_not_grow(self):
        self.assertEqual(backups_adapter.RESTORE_REASONS, ("disk", "io", "corrupt", "busy", "other"))


class ControllerTest(unittest.TestCase):
    def controller(self):
        return backup_view.BackupController(backups.FakeBackupsProvider(), jobs.JobRunner())

    def test_a_live_structure_refusal_says_it_did_not_start_adds_the_two_easy_lines_and_asks_for_a_reload(self):
        controller = self.controller()
        controller.pending = {"kind": "restore", "name": "full-20261110-210500"}
        self.assertIsNotNone(controller.progress_vm(), "시험의 전제 — 쓰는 중이면 진행 표시가 있다")
        failure = backups.make_failure("restore", "RESTORE_FAILED", reason=LIVE)
        self.assertEqual(controller.apply_write_failed(failure), "restore")
        self.assertEqual(controller.notice, ("error", T["backup_fail_restore_unstarted"], (T["backup_restore_live_structure"], T["backup_restore_live_structure_help"])))
        self.assertTrue(controller.reload_wanted)
        self.assertIsNone(controller.pending, "실패하면 '쓰고 있다' 는 표시를 지운다")
        self.assertIsNone(controller.progress_vm(), "낡은 진행 표시가 남지 않는다 — 독립 검증 Q 의 QL-2: 예전 `busy` 단언은 이 시험에서 늘 거짓이라 아무것도 세지 않았다")

    def test_the_other_restore_failures_keep_their_sentences_and_lines(self):
        controller = self.controller()
        controller.apply_write_failed(backups.make_failure("restore", "RESTORE_FAILED", reason="disk"))
        self.assertEqual(controller.notice, ("error", T["backup_fail_restore"], (T["backup_restore_reason_disk"],)))
        controller.apply_write_failed(backups.make_failure("restore", "RESTORE_FAILED", notes=("글 보관함",), reason="io"))
        self.assertEqual(controller.notice, ("error", T["backup_fail_restore_left"], (T["backup_restore_reason_io"], "글 보관함")))
        controller.apply_write_failed(backups.make_failure("restore", "RESTORE_FAILED", reason="safety"))
        self.assertEqual(controller.notice, ("error", T["backup_fail_restore"], ()), "다른 이름은 줄이 되지 않는다")

    def test_the_live_structure_line_belongs_to_restore_failures_only(self):
        controller = self.controller()
        for kind in ("blocked", "nothing", "busy", "invalid", "newer", "disk", "io", "other"):
            with self.subTest(kind=kind):
                controller.apply_write_failed(backups.make_failure(kind, "X", reason=LIVE))
                self.assertNotIn(T["backup_restore_live_structure"], controller.notice[2])
                self.assertNotIn(T["backup_restore_live_structure_help"], controller.notice[2])
                self.assertNotEqual(controller.notice[1], T["backup_fail_restore_unstarted"])

    def test_the_three_sentences_are_in_the_text_table_with_the_other_backup_sentences(self):
        for key in ("backup_fail_restore_unstarted", "backup_restore_live_structure", "backup_restore_live_structure_help"):
            self.assertIs(T[key], BACKUP_T[key])


class TextTest(unittest.TestCase):
    def test_the_first_sentence_says_nothing_was_started_and_nothing_changed(self):
        text = T["backup_fail_restore_unstarted"]
        self.assertIn("시작하지 않았어요", text)
        self.assertIn("지금 데이터는 그대로예요", text)
        self.assertNotIn("원래대로", text, "바꾼 것이 없으니 '원래대로 돌려 두었어요' 라고 하지 않는다")

    def test_the_line_says_why_and_what_to_do_in_easy_words_without_a_name_or_a_code(self):
        text = T["backup_restore_live_structure"]
        self.assertTrue(text.startswith("이유: "))
        for word in ("앱이 만들지 않는 구조", "트리거", "뷰", "복원 직전 사본", "되돌릴 수 없어서", "지운 뒤 다시 복원"):
            self.assertIn(word, text)
        for forbidden in ("FULL_BACKUP", "RESTORE_FAILED", "STORE_", "Traceback", "SELECT", "CREATE", "sqlite", chr(126), "http"):
            self.assertNotIn(forbidden, text)
        for sentence in re.split(r"(?<=[.])\s+", text):
            self.assertTrue(sentence.endswith(("요.", "요")), f"해요체로 끝난다: {sentence}")

    def test_the_help_line_names_the_diagnostics_copy_button_by_its_real_label_in_easy_words(self):
        """독립 검증 S 의 SP-1 — 막힌 사용자에게 다음에 할 일을 말한다: 이미 설정의 정보 카드에 있는 `진단 정보 복사` 단추(L3, D-539). 단추 이름은 그 단추의 글(`T["diag_copy"]`)과 같아야 한다 — 단추 글이 바뀌면 이 시험이 알린다."""
        text = T["backup_restore_live_structure_help"]
        self.assertIn("‘" + T["diag_copy"] + "’", text)
        for word in ("설정", "정보 카드", "단추", "알려 주세요", "모르겠다면"):
            self.assertIn(word, text)
        for forbidden in ("FULL_BACKUP", "RESTORE_FAILED", "STORE_", "live_structure", "Traceback", "SELECT", "CREATE", "sqlite", chr(126), "http"):
            self.assertNotIn(forbidden, text)
        for sentence in re.split(r"(?<=[.])\s+", text):
            self.assertTrue(sentence.endswith(("요.", "요")), f"해요체로 끝난다: {sentence}")
        self.assertLessEqual(len(text), 240, "화면이 한 줄을 자르는 길이(240자) 안이다")
        self.assertNotEqual(text, T["backup_restore_live_structure"])

    def test_the_dialog_still_promises_the_undo_which_now_holds_for_every_restore_that_starts(self):
        """확인창의 약속 문장은 그대로다 — 이제 복원이 시작하는 경우마다 지켜지고(`test_service_backup_live_structure`) 시작하지 않는 경우는 위 안내가 말한다."""
        body = T["backup_restore_body"]
        self.assertIn("잘못 복원했다면 목록에서 그 사본을 골라 다시 복원하면 돼요", body)
        self.assertIn("복원 직전 사본", T["backup_ok_restored"])


class EndToEndTest(unittest.TestCase):
    """진짜 서비스·진짜 임시 폴더 — 어댑터로 복원해 본다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = bs.World(self.tmp.name)
        self.ctx = self.world.ctx
        self.provider = backups_adapter.ServiceBackupsProvider(str(self.world.root), context_factory=lambda data_dir=None: self.ctx)
        self.made = self.provider.create_backup(quiet, lambda: False)
        tr.change_everything(self.world)

    def add_view(self):
        with contextlib.closing(sqlite3.connect(str(self.world.path("chanceblog.db")))) as database:
            database.execute(f"CREATE VIEW {tls.CANARY}_mine AS SELECT project_id, title FROM projects")
            database.commit()

    def test_a_live_view_ends_the_restore_in_the_easy_refusal_and_changes_nothing(self):
        self.add_view()
        before, files = tr.state_of(self.world), self.world.data_digests()
        with self.assertRaises(backups.BackupFailure) as caught:
            self.provider.restore_backup(self.made.name, quiet, lambda: False)
        failure = caught.exception
        self.assertEqual((failure.kind, failure.code, failure.reason), ("restore", "RESTORE_FAILED", LIVE))
        blob = " ".join([failure.user_message, failure.code, failure.reason, repr(failure), str(failure), *failure.notes])
        self.assertNotIn(tls.CANARY, blob)
        self.assertNotIn(str(self.world.root), blob)
        self.assertEqual(failure.notes, ())
        self.assertEqual(tr.state_of(self.world), before)
        self.assertEqual(self.world.data_digests(), files)
        self.assertFalse((self.ctx.workspace.backups_dir / bf.SAFETY_FOLDER).exists(), "안전 사본을 만들지 않았다")
        controller = backup_view.BackupController(self.provider, jobs.JobRunner())
        controller.apply_write_failed(failure)
        self.assertEqual(controller.notice, ("error", T["backup_fail_restore_unstarted"], (T["backup_restore_live_structure"], T["backup_restore_live_structure_help"])))
        shown = " ".join([controller.notice[1], *controller.notice[2]])
        self.assertNotIn(tls.CANARY, shown)
        self.assertNotIn("RESTORE_FAILED", shown)

    def test_after_the_view_is_dropped_the_restore_works_and_so_does_the_undo_it_promised(self):
        self.add_view()
        with self.assertRaises(backups.BackupFailure):
            self.provider.restore_backup(self.made.name, quiet, lambda: False)
        with contextlib.closing(sqlite3.connect(str(self.world.path("chanceblog.db")))) as database:
            database.execute(f"DROP VIEW {tls.CANARY}_mine")
            database.commit()
        before = tr.state_of(self.world)
        done = self.provider.restore_backup(self.made.name, quiet, lambda: False)
        self.assertEqual((done.action, done.status), ("restored", "complete"))
        self.assertTrue(done.safety)
        again = self.provider.restore_backup(done.safety, quiet, lambda: False)
        self.assertEqual((again.action, again.status), ("restored", "complete"), "복원 직전 사본으로 되돌리기가 된다")
        self.assertEqual(tr.state_of(self.world), before)

    def test_a_clean_restore_through_the_adapter_is_as_before(self):
        result = self.provider.restore_backup(self.made.name, quiet, lambda: False)
        self.assertEqual((result.action, result.status), ("restored", "complete"))


if __name__ == "__main__":
    unittest.main()
