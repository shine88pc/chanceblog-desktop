"""설정 화면의 백업·복원 카드(BACKUPUI)의 PySide6 시험 — 카드가 그려지는 모양(목록·배지·위치 글·'Credential 제외됨')·지금 백업(작업 스레드·제자리 진행·쓰는 동안 단추 꺼짐)·복원(확인창이 먼저·안전 사본 안내)·실패 안내·창 크기·접근성, 그리고 실제 서비스를 임시 폴더에서 끝까지 돌려 본다.

**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_backup_core`·`test_ui_backup_adapter`). 사용자의 데이터 폴더·클립보드는 건드리지 않는다(데이터 폴더는 모두 임시 폴더, 실제 자격 증명 관리자는 부르지 않는다).

지키는 것:
  1) 짝 공급자가 없으면 카드가 없다(기존 설정 화면은 그대로 — D-391). 예시 화면(`--sample`)은 '예시' 배지와 안내가 있고 아무것도 저장하지 않는다.
  2) 카드는 제목·`지금 백업`·백업 위치(글자로만, 폴더 열기 단추 없음)·USB 복사 안내·'Credential 제외됨' 글 안내를 늘 보이고, 줄마다 종류·상태·`Credential 제외됨` 배지(글자)와 크기·담긴 것을 보인다. **'무시하고 백업' 같은 선택지가 없다.**
  3) 백업은 작업 스레드에서 돈다 — 진행 줄(글+막대)은 제자리에서 바뀌고(위젯이 그대로) 쓰는 동안 단추는 꺼지며(까닭이 툴팁·진행 줄에) 두 번째 누름은 아무 일도 하지 않는다. 끝나면 결과 띠·새 줄·`지금 백업` 으로 포커스.
  4) 복원은 확인창이 먼저다 — 무엇이 바뀌는지·안전 사본(복원 직전 사본)이 남는다는 것·되돌리는 법이 있고 처음 포커스는 취소다. 취소·Esc 는 아무것도 복원하지 않는다. 확인하면 복원하고 홈을 다시 읽는다.
  5) 실패는 종류별로 정해진 문장뿐이다(경로·예외 문구 없음). 키 모양이 발견되면 위치·유형 줄만 나오고 키 글자는 위젯 트리의 어떤 글·툴팁·접근 이름에도 없다.
  6) 모든 눌리는 부품은 접근 이름과 36px 이상의 누르는 칸을 가지고, 어느 창 크기(최소 900×560 포함)에서도 가로 스크롤·글자 잘림이 없다. 창을 닫을 때 돌고 있는 백업은 끝나기를 기다린다.
"""
import datetime
import importlib.util
import json
import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import backup_support as bs  # noqa: E402
import key_leak_support as leak  # noqa: E402

from chanceblog_desktop.security.backup_note import CREDENTIAL_NOTE, EXCLUDED, RESTORE_NOTE, SHORT_NOTE  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402
from chanceblog_desktop.ui import backups_adapter  # noqa: E402
from chanceblog_desktop.ui.core import backups, clock as clock_rules, jobs, services  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import backup_parts
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import shell as shell_module

FIXED_NOW = datetime.datetime(2026, 11, 11, 12, 10)                       # 이 모듈의 모든 창은 고정 시계를 쓴다 — 컴퓨터 시계의 분·초에 따라 글 검사가 우연히 실패하지 않게
SIZES = ((1366, 768), (1093, 614), (910, 512), (1536, 864), (1280, 720), (1920, 1080), (900, 560))             # 910×512 = 1366×768 노트북의 150%(논리 크기), 900×560 = 최소 창
FIRST, SAFETY, PARTIAL, BROKEN = "full-20261110-210500", "before-20261110-100300", "full-20261108-083000", "full-20261101-120000"
IGNORE_WORDS = ("무시", "그냥", "그래도", "강제", "건너", "계속 진행")
FOLDER_WORDS = ("열기", "탐색기", "폴더 열")


class Stepped(backups.FakeBackupsProvider):
    """쓰기가 **시험이 풀어 줄 때까지** 기다리는 가짜 공급자 — 시간에 기대지 않고 '쓰는 중' 을 확실히 본다. `steps` 는 일이 알릴 (비율, 글) 들이고 하나를 알릴 때마다 `release.put(1)` 을 기다린다.
    `started` 는 시작한 쓰기 이름, `threads` 는 일한 스레드(작업 스레드에서 도는지 본다), `hold_load` 를 비우면 목록 읽기가 멈춘다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.release = queue.Queue()
        self.steps = ()
        self.hold_load = threading.Event()
        self.hold_load.set()
        self.started, self.threads = [], []
        self.finished = threading.Event()
        self.create_error = self.restore_error = None

    def _wait(self, cancelled, limit=30):
        end = time.monotonic() + limit
        while True:
            try:
                return self.release.get(timeout=0.02)
            except queue.Empty:
                if cancelled():
                    raise jobs.JobCancelled()
                if time.monotonic() > end:
                    raise AssertionError("시험이 쓰기를 풀어 주지 않았다")

    def _steps(self, progress, cancelled):
        for fraction, text in self.steps:
            progress(fraction, text)
            self._wait(cancelled)

    def load_backups(self, progress, cancelled):
        self.threads.append(threading.current_thread())
        while not self.hold_load.wait(0.02):
            if cancelled():
                raise jobs.JobCancelled()
        return super().load_backups(progress, cancelled)

    def create_backup(self, progress, cancelled):
        self.started.append("create")
        self.threads.append(threading.current_thread())
        try:
            self._steps(progress, cancelled)
            if self.create_error is not None:
                raise self.create_error
            return super().create_backup(progress, cancelled)
        finally:
            self.finished.set()

    def restore_backup(self, name, progress, cancelled):
        self.started.append("restore:" + name)
        self.threads.append(threading.current_thread())
        try:
            self._steps(progress, cancelled)
            if self.restore_error is not None:
                raise self.restore_error
            return super().restore_backup(name, progress, cancelled)
        finally:
            self.finished.set()

    def revert_interrupted(self, progress, cancelled):
        self.started.append("revert")
        self.threads.append(threading.current_thread())
        try:
            self._steps(progress, cancelled)
            return super().revert_interrupted(progress, cancelled)
        finally:
            self.finished.set()


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def setUp(self):
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: self.errors.append(f"{kind.__name__}: {value}")
        self.clipboard = QGuiApplication.clipboard()
        self._saved_clipboard = self.clipboard.text()
        self.addCleanup(self.clipboard.setText, self._saved_clipboard)

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def flush(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.settle(2)

    def activate(self, window):
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)

    def make(self, provider=None, size=(1366, 768), page="settings", home=None, **kwargs):
        provider = Stepped() if provider is None else provider
        kwargs.setdefault("clock", clock_rules.FixedClock(FIXED_NOW))
        window = shell_module.AppShell(home or services.FakeHomeProvider(), backups=provider, autoload=False, **kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        if page == "settings":
            window.go("settings")
            self.wait_loaded(window)
        return window

    def wait_loaded(self, window, seconds=10):
        controller = window.state.backups
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading" and controller.state != "loading" and not controller.loading, seconds)
        self.settle()

    def wait_write(self, window, seconds=20):
        controller = window.state.backups
        ui_offscreen.wait_until(self.app, lambda: controller.pending is None and not controller.busy and not controller.loading and not controller.reload_wanted, seconds)
        self.settle()

    def card(self, window):
        found = window.screen_widget.findChildren(backup_parts.BackupSection)
        self.assertEqual(len(found), 1, "백업·복원 카드는 설정 화면에 하나다")
        return found[0]

    def click(self, button):
        self.assertTrue(button.isVisible() and button.isEnabled(), button.accessibleName())
        QTest.mouseClick(button, Qt.LeftButton)
        self.settle(3)

    def press(self, widget, key):
        widget.setFocus(Qt.OtherFocusReason)
        QTest.keyClick(widget, key)
        self.settle(3)

    def texts(self, root):
        found = []
        for widget in root.findChildren(QLabel):
            found.append(getattr(widget, "_full", None) or (widget.plain_text() if hasattr(widget, "plain_text") else widget.text()))
        found += [button.text() for button in root.findChildren(QAbstractButton)]
        return found

    def badges(self, root):
        return [label.text() for label in root.findChildren(QLabel) if label.property("badge")]

    def notice_level(self, card):
        return None if card.notice is None else card.notice.level

    def notice_text(self, card):
        return "" if card.notice is None else card.notice.text.plain_text()

    def dialog_buttons(self, window):
        return [button for button in window.dialog.findChildren(QAbstractButton) if button.isVisible()]

    def dialog_texts(self, window):
        return [label.plain_text() for label in window.dialog.findChildren(UI.Label)]

    def focus_key(self):
        widget = QApplication.focusWidget()
        return None if widget is None else widget.property("focus_key")

    def restore_through_dialog(self, window, name):
        card = self.card(window)
        self.click(card.row(name).restore)
        self.assertTrue(window.dialog.is_open)
        ok = next(button for button in self.dialog_buttons(window) if button.property("focus_key") == "dialog-ok")
        self.click(ok)


class AbsentTest(Base):
    def test_without_a_paired_provider_the_settings_screen_has_no_backup_card_and_the_handlers_are_safe(self):
        window = shell_module.AppShell(services.FakeHomeProvider(), autoload=False, clock=clock_rules.FixedClock(FIXED_NOW))
        window.resize(1366, 768)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        window.go("settings")
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10)
        self.settle()
        self.assertIsNone(window.state.backups)
        self.assertEqual(window.screen_widget.findChildren(backup_parts.BackupSection), [])
        self.assertNotIn(T["backup_title"], self.texts(window.screen_widget))
        self.assertEqual(window.backup_now(), "unavailable")
        self.assertIsNone(window.backup_restore(FIRST))
        self.assertEqual(window.backup_restore_confirmed(FIRST), "unavailable")
        self.assertFalse(window.reload_backups())
        self.assertFalse(window.dialog.is_open)

    def test_the_sample_home_provider_pairs_an_example_card_that_says_so_and_saves_nothing(self):
        window = shell_module.AppShell(services.FakeHomeProvider(backups=True), autoload=False, clock=clock_rules.FixedClock(FIXED_NOW))
        window.resize(1366, 768)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        window.go("settings")
        self.wait_loaded(window)
        card = self.card(window)
        self.assertIn(T["backup_sample_tag"], self.badges(card))
        self.assertIn(T["backup_sample_note"], self.texts(card))
        self.assertTrue(card.create_button.isEnabled())
        before = [row.name for row in card.rows]
        self.click(card.create_button)
        self.wait_write(window)
        after = [row.name for row in self.card(window).rows]
        self.assertEqual((len(after), after[1:]), (len(before) + 1, before), "새 줄이 맨 위에 생겼다")
        self.assertIsInstance(window.state.backups_provider, backups.FakeBackupsProvider)


class CardTest(Base):
    def test_the_card_shows_title_create_button_location_copy_hint_and_the_credential_line(self):
        window = self.make()
        card = self.card(window)
        texts = self.texts(card)
        self.assertIn(T["backup_title"], texts)
        self.assertEqual(card.create_button.text(), T["backup_now"])
        self.assertEqual(card.create_button.accessibleName(), T["backup_now_a11y"])
        self.assertTrue(card.create_button.isEnabled())
        location = card.notes[0]
        self.assertTrue(location.plain_text().startswith("백업 위치: "), location.plain_text())
        self.assertTrue(bool(location.textInteractionFlags() & Qt.TextSelectableByMouse), "위치는 글자로 보이고 복사할 수 있다")
        self.assertIn(T["backup_copy_tip"], texts)
        self.assertTrue(any(text.startswith(CREDENTIAL_NOTE) for text in texts), "키·토큰·쿠키·세션이 백업에 들어 있지 않다는 안내")
        self.assertTrue(any("복원한 뒤 키는 다시 등록하세요" in text for text in texts), "복원한 뒤 키를 다시 등록하라는 안내(위 문장 안에 들어 있다)")
        self.assertIn(T["backup_keep"].format(n=10), texts)
        self.assertIn(T["backup_list_title"], texts)

    def test_every_backup_row_says_kind_status_and_credential_excluded_in_words_with_size_and_contents(self):
        window = self.make()
        card = self.card(window)
        self.assertEqual([row.name for row in card.rows], [FIRST, SAFETY, PARTIAL])
        first = card.row(FIRST)
        self.assertEqual(first.title._full, "2026-11-10 21:05 백업", "시각은 한국 시간이다")
        self.assertEqual(self.badges(first), [T["backup_kind_backup"], T["backup_status_complete"], SHORT_NOTE])
        lines = [line.plain_text() for line in first.lines]
        self.assertTrue(any(line.startswith("크기 ") and "MB" in line for line in lines), lines)
        contents = next(line for line in lines if line.startswith("담긴 것: "))
        for part in ("글 12개", "저장한 초안 3개", "주제 후보 5개", "추천 후보 40개", "채널 프로필 5개", "Seed 130개", "캘린더 항목 6개", "설정"):
            self.assertIn(part, contents)
        safety = card.row(SAFETY)
        self.assertEqual(self.badges(safety)[0], T["backup_kind_safety"])
        self.assertEqual(safety.title._full, "2026-11-10 10:03 복원 직전 사본")
        partial = card.row(PARTIAL)
        self.assertEqual(self.badges(partial)[1], T["backup_status_partial"])
        self.assertTrue(any(line.plain_text().startswith("담지 못한 것: Seed(") for line in partial.lines), "담지 못한 것이 이유와 함께 쓰여 있다")
        for row in card.rows:
            self.assertIn(SHORT_NOTE, self.badges(row), "모든 줄에 Credential 제외됨 글자 배지가 있다")
            self.assertTrue(row.accessibleName().endswith(T["backup_credential_a11y"]), row.accessibleName())

    def test_there_is_no_folder_button_and_no_ignore_and_continue_choice_anywhere_in_the_card(self):
        window = self.make(backups.FakeBackupsProvider("broken"))
        card = self.card(window)
        keys = sorted(str(button.property("focus_key") or "") for button in card.findChildren(QAbstractButton))
        self.assertEqual(keys, sorted(["backup-create", "backup-excluded", *[f"backup-restore:{row.name}" for row in card.rows]]))
        for button in card.findChildren(QAbstractButton):
            for word in FOLDER_WORDS + IGNORE_WORDS:
                self.assertNotIn(word, button.text(), button.accessibleName())
        self.assertEqual([row.name for row in card.rows][-1], BROKEN)

    def test_the_list_of_things_not_in_the_backup_opens_and_closes_and_names_every_excluded_thing_with_its_reason(self):
        window = self.make()
        card = self.card(window)
        self.assertEqual(card.excluded.toggle.text(), T["backup_excluded_show"])
        self.assertFalse(card.excluded.body.isVisible(), "처음에는 접혀 있다")
        self.click(card.excluded.toggle)
        self.assertTrue(card.excluded.body.isVisible())
        body = card.excluded.body.plain_text()
        self.assertEqual(card.excluded.toggle.text(), T["backup_excluded_hide"])
        self.assertTrue(body.startswith(T["backup_excluded_intro"]))
        for name, reason in EXCLUDED:
            self.assertIn(f"{name} — {reason}", body)
        self.assertEqual(len(EXCLUDED), 9)
        self.click(card.excluded.toggle)
        self.assertFalse(card.excluded.body.isVisible())
        self.assertEqual(card.excluded.toggle.text(), T["backup_excluded_show"])

    def test_a_broken_backup_cannot_be_restored_and_says_why_in_words_and_by_tooltip(self):
        window = self.make(backups.FakeBackupsProvider("broken"))
        card = self.card(window)
        broken = card.row(BROKEN)
        self.assertFalse(broken.restore.isEnabled())
        self.assertEqual((broken.restore.toolTip(), broken.restore.accessibleDescription()), (T["backup_restore_broken"], T["backup_restore_broken"]))
        self.assertEqual(self.badges(broken)[1], T["backup_status_broken"])
        self.assertNotIn(SHORT_NOTE, self.badges(broken), "복원할 수 없는 줄은 담긴 것이 없으니 Credential 안내 배지도 없다")
        self.assertTrue(any("목록 파일을 읽을 수 없어요" in line.plain_text() and line.plain_text().endswith(T["backup_broken_tail"]) for line in broken.lines))
        self.assertTrue(card.row(FIRST).restore.isEnabled())
        QTest.mouseClick(broken.restore, Qt.LeftButton)
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "꺼진 단추는 확인창도 열지 않는다")

    def test_the_empty_the_loading_and_the_error_states_each_have_their_own_plain_screen(self):
        window = self.make(backups.FakeBackupsProvider("empty"))
        card = self.card(window)
        self.assertEqual((card.rows, card.state_card is not None), ([], True))
        self.assertIn(T["backup_empty_title"], self.texts(card))
        self.assertTrue(card.create_button.isEnabled(), "목록이 비어 있어도 만들 수 있다")
        provider = Stepped()
        provider.hold_load.clear()
        window = self.make(provider)
        card = self.card(window)
        self.assertEqual(window.state.backups.state, "loading")
        self.assertTrue([widget for widget in card.findChildren(QWidget) if widget.accessibleName() == T["backup_loading_a11y"]], "읽는 동안 자리 표시 줄이 있다")
        self.assertIn(T["backup_loading"], self.texts(card))
        self.assertTrue(card.create_button.isEnabled(), "읽는 동안에도 만들 수 있다(읽기는 쓰기를 막지 않는다)")
        provider.hold_load.set()
        self.wait_loaded(window)
        self.assertEqual(len(self.card(window).rows), 3)
        window = self.make(backups.FakeBackupsProvider("error"))
        card = self.card(window)
        self.assertEqual(window.state.backups.state, "error")
        texts = self.texts(card)
        self.assertIn(T["backup_error_title"], texts)
        self.assertIn(T["backup_reload"], texts)
        self.assertTrue(card.create_button.isEnabled(), "목록을 못 읽어도 백업은 만들 수 있다")

    def test_the_error_state_reads_again_with_its_button_and_a_backup_made_meanwhile_still_shows_its_notice(self):
        provider = Stepped("error")
        window = self.make(provider)
        reload_button = next(button for button in self.card(window).findChildren(QAbstractButton) if button.text() == T["backup_reload"])
        count = window.state.backups.load_count
        self.click(reload_button)
        self.wait_loaded(window)
        self.assertEqual(window.state.backups.load_count, count + 1)
        self.click(self.card(window).create_button)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual(self.notice_level(card), "ok")
        self.assertEqual(window.state.backups.state, "error", "다시 읽어도 같은 오류면 오류 화면 그대로다(결과 띠는 남는다)")

    def test_a_card_whose_provider_is_read_only_shows_the_reason_and_has_no_working_buttons(self):
        class ReadOnly(backups.BackupsProvider):
            sample = True

            def load_backups(self, progress, cancelled):
                return backups.BackupsData(backups.sample_rows(), backups.SAMPLE_LOCATION, 10, True)

        window = self.make(ReadOnly())
        card = self.card(window)
        self.assertFalse(card.create_button.isEnabled())
        self.assertEqual(card.create_button.toolTip(), T["backup_no_write"])
        self.assertIn(T["backup_no_write"], self.texts(card), "까닭이 툴팁만이 아니라 화면 글로도 있다")
        for row in card.rows:
            self.assertFalse(row.restore.isEnabled())
        self.assertEqual(window.backup_now(), "unavailable")


class WriteTest(Base):
    def test_a_backup_runs_on_a_worker_thread_with_progress_updated_in_place_then_a_notice_a_new_row_and_the_focus_back(self):
        provider = Stepped()
        provider.steps = ((0.4, T["backup_step_save"]), (0.8, T["backup_step_check"]))
        window = self.make(provider)
        self.click(self.card(window).create_button)
        self.assertTrue(window.state.backups.busy)
        ui_offscreen.wait_until(self.app, lambda: window.state.backups.progress[0] == 0.4, 5)
        self.settle(2)
        card = self.card(window)
        self.assertIsNotNone(card.progress)
        self.assertIn("40%", card.progress.text.plain_text())
        self.assertIn(T["backup_step_save"], card.progress.text.plain_text())
        self.assertEqual(card.progress.track._segments, ((0.4, "primary"),))
        self.assertTrue(provider.threads[-1] is not threading.main_thread(), "백업은 작업 스레드에서 돈다(화면은 멈추지 않는다)")
        first_progress = card.progress
        provider.release.put(1)
        ui_offscreen.wait_until(self.app, lambda: window.state.backups.progress[0] == 0.8, 5)
        self.settle(2)
        self.assertIs(self.card(window).progress, first_progress, "진행 줄은 제자리에서 바뀐다(다시 그리지 않는다)")
        self.assertIn("80%", first_progress.text.plain_text())
        self.assertEqual(first_progress.track._segments, ((0.8, "primary"),))
        provider.release.put(1)
        self.wait_write(window)
        card = self.card(window)
        self.assertIsNone(card.progress)
        self.assertEqual(self.notice_level(card), "ok")
        self.assertTrue(self.notice_text(card).startswith("백업을 만들었어요 — 2026-11-11 12:00"), self.notice_text(card))
        self.assertEqual(card.rows[0].name, "full-20261111-120001", "새 백업이 목록 맨 위에 있다")
        self.assertEqual(self.focus_key(), "backup-create", "끝나면 포커스가 지금 백업으로 돌아온다")
        self.assertTrue(card.create_button.isEnabled())

    def test_while_writing_the_buttons_are_off_with_the_reason_and_a_second_press_does_nothing(self):
        provider = Stepped()
        provider.steps = ((0.3, T["backup_step_save"]),)
        window = self.make(provider)
        self.click(self.card(window).create_button)
        ui_offscreen.wait_until(self.app, lambda: window.state.backups.progress[0] == 0.3, 5)
        card = self.card(window)
        self.assertFalse(card.create_button.isEnabled())
        self.assertEqual((card.create_button.toolTip(), card.create_button.accessibleDescription()), (T["backup_busy_create"], T["backup_busy_create"]))
        for row in card.rows:
            self.assertFalse(row.restore.isEnabled())
            self.assertEqual(row.restore.toolTip(), T["backup_busy"])
        QTest.mouseClick(card.create_button, Qt.LeftButton)
        self.settle(3)
        self.assertEqual(window.backup_now(), "busy")
        self.assertEqual(window.backup_restore(FIRST), None)
        self.assertFalse(window.dialog.is_open, "쓰는 중에는 복원 확인창도 열지 않는다")
        self.assertFalse(window.reload_backups(), "쓰는 중에는 목록을 읽지도 않는다")
        self.assertEqual(provider.started, ["create"], "두 번째 누름은 아무 일도 시작하지 않았다")
        provider.release.put(1)
        self.wait_write(window)
        self.assertEqual(provider.started, ["create"])

    def test_the_restore_dialog_comes_first_with_cancel_focused_and_says_what_changes_the_safety_copy_and_how_to_undo(self):
        provider = Stepped()
        window = self.make(provider)
        card = self.card(window)
        self.click(card.row(FIRST).restore)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(provider.started, [], "확인하기 전에는 아무것도 시작하지 않는다")
        texts = self.dialog_texts(window)
        self.assertEqual(texts[0], T["backup_restore_title"])
        body = texts[1]
        for needle in ("2026-11-10 21:05", "글 보관함·주제 보관함·채널 프로필·Seed·캘린더·설정", "복원 직전 사본", backups.SAMPLE_LOCATION, "다시 복원", "키는 백업에 없어서"):
            self.assertIn(needle, body)
        self.assertEqual([button.text() for button in self.dialog_buttons(window)], [T["backup_restore_cancel"], T["backup_restore_ok"]])
        self.assertEqual(self.focus_key(), "dialog-cancel", "처음 포커스는 취소다 — Enter 를 잘못 눌러도 복원하지 않는다")
        self.click(next(button for button in self.dialog_buttons(window) if button.property("focus_key") == "dialog-cancel"))
        self.assertFalse(window.dialog.is_open)
        self.click(self.card(window).row(PARTIAL).restore)
        self.assertIn(T["backup_restore_partial"].strip(), self.dialog_texts(window)[1], "일부만 담긴 백업은 그 사실을 확인창에도 쓴다")
        self.press(QApplication.focusWidget(), Qt.Key_Escape)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(provider.started, [], "취소·Esc 는 아무것도 복원하지 않는다")

    def test_confirming_restores_in_the_worker_shows_the_result_and_the_safety_copy_row_and_reads_the_home_again(self):
        provider = Stepped()
        provider.steps = ((0.5, T["backup_step_change"]),)
        window = self.make(provider)
        home_reads = window.state.load_count
        self.restore_through_dialog(window, FIRST)
        ui_offscreen.wait_until(self.app, lambda: window.state.backups.progress[0] == 0.5, 5)
        card = self.card(window)
        self.assertIn(T["backup_progress_restore"].format(percent=50), card.progress.text.plain_text())
        self.assertEqual(card.create_button.toolTip(), T["backup_busy_restore"])
        self.assertEqual(provider.started, ["restore:" + FIRST])
        provider.release.put(1)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("ok", T["backup_ok_restored"]))
        self.assertIn(T["backup_note_keys"], self.texts(card), "키는 백업에 없으니 다시 등록하라는 안내가 결과에 붙는다")
        self.assertEqual(card.rows[0].name, "before-20261111-130001")
        self.assertEqual(card.rows[0].title._full, "2026-11-11 13:00 복원 직전 사본")
        self.assertGreater(window.state.load_count, home_reads, "복원이 데이터를 바꿨으니 홈이 읽어 둔 값을 새로 읽는다")
        self.assertEqual(self.focus_key(), "backup-create")

    def test_a_partial_backup_and_a_partial_restore_say_so_with_a_warning_notice(self):
        provider = Stepped(create_status="partial")
        window = self.make(provider)
        self.click(self.card(window).create_button)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual(self.notice_level(card), "warning")
        self.assertTrue(self.notice_text(card).startswith("일부만 백업했어요. 담지 못한 것: Seed("), self.notice_text(card))
        self.restore_through_dialog(window, PARTIAL)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("warning", T["backup_ok_restored_partial"]))

    def test_failures_show_only_the_fixed_sentence_for_their_kind_and_never_a_path_or_an_exception_text(self):
        for kind in ("nothing", "busy", "newer", "disk", "io", "other"):
            with self.subTest(kind=kind):
                provider = Stepped()
                provider.create_error = backups.BackupFailure("C:\\누군가\\폴더 안의 예외 문구", "SOME_CODE", kind=kind)
                window = self.make(provider)
                self.click(self.card(window).create_button)
                self.wait_write(window)
                card = self.card(window)
                self.assertEqual((self.notice_level(card), self.notice_text(card)), ("error", T["backup_fail_" + kind]))
                shown = " ".join(text for _label, text in leak.widget_texts(window))
                self.assertNotIn("누군가", shown)
                self.assertNotIn("SOME_CODE", shown)
                self.assertEqual(self.focus_key(), "backup-create")
                self.assertEqual(len(card.rows), 3, "실패해도 목록은 그대로다")

    def test_a_blocked_backup_lists_places_and_kinds_only_and_offers_no_way_to_ignore_it(self):
        provider = Stepped()
        places = ("저장한 초안 — 예시 글 1 — 3번째 줄 — 키 모양(Google API 키)", "채널 프로필 — 첫 번째 프로필 — 키 모양(GitHub 토큰)")
        provider.create_error = backups.make_failure("blocked", "FULL_BACKUP_BLOCKED", summary=places)
        window = self.make(provider)
        self.click(self.card(window).create_button)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("error", T["backup_fail_blocked"]))
        self.assertEqual([line.plain_text() for line in card.notice_lines], list(places))
        self.assertEqual([button.text() for button in card.findChildren(QAbstractButton) if button.text() not in (T["backup_restore"], T["backup_now"], T["backup_excluded_show"])], [],
                         "막힌 뒤에도 단추는 처음과 같다 — '무시하고 백업' 같은 선택지가 없다")
        for button in window.findChildren(QAbstractButton):
            for word in IGNORE_WORDS:
                self.assertNotIn(word, button.text())
        self.assertEqual(len(card.rows), 3)

    def test_a_restore_that_fails_says_what_was_put_back_and_what_was_not_and_where_the_safety_copy_is(self):
        provider = Stepped()
        provider.restore_error = backups.make_failure("restore", "RESTORE_FAILED", notes=("글 보관함", "설정"), reason="io")
        window = self.make(provider)
        self.restore_through_dialog(window, FIRST)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("error", T["backup_fail_restore_left"]))
        lines = [line.plain_text() for line in card.notice_lines]
        self.assertEqual(lines, [T["backup_restore_reason_io"], "글 보관함", "설정"])
        self.assertIn("복원 직전 사본", self.notice_text(card))

    def test_an_unexpected_exception_in_the_worker_becomes_the_plain_sentence_and_the_screen_stays_usable(self):
        provider = Stepped()
        provider.create_error = RuntimeError("C:\\비밀 경로\\예외")
        window = self.make(provider)
        self.click(self.card(window).create_button)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("error", T["backup_fail_other"]))
        self.assertNotIn("비밀 경로", " ".join(text for _label, text in leak.widget_texts(window)))
        self.assertTrue(card.create_button.isEnabled())

    def test_the_list_is_not_read_while_a_write_runs_and_is_read_again_after_it(self):
        provider = Stepped()
        provider.steps = ((0.3, T["backup_step_save"]),)
        window = self.make(provider)
        self.click(self.card(window).create_button)
        ui_offscreen.wait_until(self.app, lambda: window.state.backups.progress[0] == 0.3, 5)
        reads = window.state.backups.load_count
        self.assertFalse(window.reload_backups())
        window.go("home")
        window.go("settings")
        self.settle(4)
        self.assertEqual(window.state.backups.load_count, reads, "쓰는 도중의 폴더를 읽지 않는다")
        provider.release.put(1)
        self.wait_write(window)
        self.assertGreater(window.state.backups.load_count, reads, "끝난 뒤에는 다시 읽는다")
        self.assertEqual(len(self.card(window).rows), 4)

    def test_closing_the_window_waits_for_a_running_backup_to_finish(self):
        provider = Stepped()
        provider.steps = ((0.5, T["backup_step_save"]),)
        window = self.make(provider)
        self.click(self.card(window).create_button)
        ui_offscreen.wait_until(self.app, lambda: window.state.backups.progress[0] == 0.5, 5)
        timer = threading.Timer(0.3, lambda: provider.release.put(1))
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        window.close()
        self.assertTrue(provider.finished.is_set(), "닫을 때 돌고 있던 백업은 끝난 뒤에 닫혔다")
        self.assertGreaterEqual(time.monotonic() - started, 0.25, "끝나기를 기다렸다")
        self.assertEqual(provider.started, ["create"])

    def test_the_keyboard_alone_can_make_a_backup_and_open_the_restore_dialog(self):
        provider = Stepped()
        window = self.make(provider)
        card = self.card(window)
        card.create_button.setFocus(Qt.TabFocusReason)
        QTest.keyClick(card.create_button, Qt.Key_Space)
        self.wait_write(window)
        self.assertEqual(provider.started, ["create"])
        card = self.card(window)
        self.assertIn(card.create_button.focusPolicy(), (Qt.StrongFocus, Qt.TabFocus), "Tab 정거장이다")
        row = card.rows[1]
        row.restore.setFocus(Qt.TabFocusReason)
        QTest.keyClick(row.restore, Qt.Key_Return)
        self.settle(3)
        self.assertTrue(window.dialog.is_open, "Enter 로도 복원 확인창이 열린다")
        self.assertEqual(provider.started, ["create"], "열기만 했을 뿐 복원은 시작하지 않았다")


class InterruptedCardTest(Base):
    """복원이 중간에 멈춘 흔적(D-463) — 카드 위쪽의 쉬운 안내와 `안전 사본으로 되돌리기`(확인창이 먼저, 처음 포커스는 취소)."""

    def test_the_normal_card_has_no_notice_of_a_stopped_restore(self):
        card = self.card(self.make(Stepped()))
        self.assertEqual((card.interrupted, card.revert_button, card.interrupted_lines), (None, None, []))

    def test_a_stopped_restore_shows_the_plain_notice_the_time_and_a_revert_button_that_can_be_pressed_by_keyboard(self):
        window = self.make(Stepped("interrupted"))
        card = self.card(window)
        self.assertEqual((card.interrupted.level, card.interrupted.text.plain_text()), ("warning", T["backup_interrupted_can"]))
        self.assertEqual([line.plain_text() for line in card.interrupted_lines], [T["backup_interrupted_when"].format(when="2026-11-10 21:20")])
        button = card.revert_button
        self.assertEqual((button.text(), button.accessibleName(), button.isEnabled()), (T["backup_revert"], T["backup_revert_a11y"], True))
        self.assertGreaterEqual(button.height(), 36, "누르는 칸은 36px 이상이다")
        self.assertEqual(button.property("focus_key"), "backup-revert")

    def test_the_revert_asks_first_with_cancel_focused_and_cancel_or_escape_starts_nothing(self):
        provider = Stepped("interrupted")
        window = self.make(provider)
        self.click(self.card(window).revert_button)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(provider.started, [], "확인하기 전에는 아무것도 시작하지 않는다")
        texts = self.dialog_texts(window)
        self.assertEqual(texts[0], T["backup_revert_title"])
        for needle in ("2026-11-10 10:03", "복원 직전 사본", backups.SAMPLE_LOCATION, "키는 백업에 없어서"):
            self.assertIn(needle, texts[1])
        self.assertEqual([button.text() for button in self.dialog_buttons(window)], [T["backup_restore_cancel"], T["backup_revert_ok"]])
        self.assertEqual(self.focus_key(), "dialog-cancel", "처음 포커스는 취소다 — Enter 를 잘못 눌러도 되돌리지 않는다")
        self.click(next(button for button in self.dialog_buttons(window) if button.property("focus_key") == "dialog-cancel"))
        self.assertFalse(window.dialog.is_open)
        self.click(self.card(window).revert_button)
        self.press(QApplication.focusWidget(), Qt.Key_Escape)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(provider.started, [], "취소·Esc 는 아무것도 되돌리지 않는다")
        self.assertIsNotNone(self.card(window).interrupted, "취소하면 안내는 그대로다")

    def test_confirming_reverts_in_the_worker_shows_the_result_and_the_notice_goes_away(self):
        provider = Stepped("interrupted")
        provider.steps = ((0.5, T["backup_step_change"]),)
        window = self.make(provider)
        self.click(self.card(window).revert_button)
        self.click(next(button for button in self.dialog_buttons(window) if button.property("focus_key") == "dialog-ok"))
        ui_offscreen.wait_until(self.app, lambda: window.state.backups.progress[0] == 0.5, 5)
        card = self.card(window)
        self.assertIn(T["backup_progress_restore"].format(percent=50), card.progress.text.plain_text())
        self.assertFalse(card.revert_button.isEnabled(), "쓰는 중에는 꺼진다")
        self.assertEqual(card.revert_button.toolTip(), T["backup_busy"])
        self.assertEqual(provider.started, ["revert"])
        self.assertTrue(provider.threads[-1] is not threading.main_thread(), "되돌리기는 작업 스레드에서 돈다")
        provider.release.put(1)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("ok", T["backup_ok_restored"]))
        self.assertIsNone(card.interrupted, "되돌린 뒤에는 멈춘 복원 안내가 사라진다")
        self.assertEqual(card.rows[0].name, "before-20261111-130001", "되돌리기 직전 상태가 새 복원 직전 사본으로 남았다")
        self.assertEqual(self.focus_key(), "backup-create")

    def test_without_a_safety_copy_the_notice_says_so_and_there_is_no_revert_button(self):
        class NoSafety(Stepped):
            def load_backups(self, progress, cancelled):
                data = super().load_backups(progress, cancelled)
                return backups.BackupsData(data.rows, data.location, data.keep, data.sample, backups.InterruptedData("", "", "", False))
        window = self.make(NoSafety())
        card = self.card(window)
        self.assertEqual(card.interrupted.text.plain_text(), T["backup_interrupted_cannot"])
        self.assertIsNone(card.revert_button)
        self.assertEqual(card.interrupted_lines, [])
        self.assertIsNone(window.backup_revert(), "되돌릴 것이 없으면 확인창도 열지 않는다")
        self.assertFalse(window.dialog.is_open)

    def test_the_handlers_are_safe_without_a_paired_provider(self):
        window = shell_module.AppShell(services.FakeHomeProvider(), autoload=False, clock=clock_rules.FixedClock(FIXED_NOW))
        self.addCleanup(window.close)
        self.assertIsNone(window.backup_revert())
        self.assertEqual(window.backup_revert_confirmed(), "unavailable")

    def test_the_notice_and_button_stay_inside_the_window_at_every_size_and_leak_no_internal_word(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(Stepped("interrupted"), size=size)
                ui_offscreen.wait_until(self.app, lambda w=window: w.scroll.horizontalScrollBar().maximum() == 0, 2)
                card = self.card(window)
                self.assertTrue(card.revert_button.isVisibleTo(card))
                self.assertGreaterEqual(card.revert_button.height(), 36)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)
                self.assertEqual(ui_offscreen.find_clipping(window), [])
                self.assertEqual(ui_offscreen.find_squeezed(window.screen_widget), [])
                shown = " ".join(text for _label, text in leak.widget_texts(window))
                for word in ("InterruptedData", "can_revert", "restore-in-progress", "interrupted"):
                    self.assertNotIn(word, shown)
                window.close()


class FitTest(Base):
    def test_every_pressable_part_has_a_name_and_a_big_enough_hit_target_and_nothing_is_clipped(self):
        window = self.make()
        card = self.card(window)
        buttons = card.findChildren(QAbstractButton)
        self.assertEqual(len(buttons), 5, "지금 백업 · 접기 단추 · 복원 셋")
        for button in buttons:
            self.assertTrue(button.accessibleName().strip(), button.text())
            self.assertGreaterEqual(button.height(), 36, button.accessibleName())
            self.assertTrue(button.text().strip())
        self.assertEqual(ui_offscreen.find_clipping(window), [])
        self.assertEqual(ui_offscreen.find_squeezed(window.screen_widget), [])

    def test_the_card_fits_every_required_window_size_without_horizontal_scroll_or_clipped_text(self):
        for size in SIZES:
            for scenario in ("normal", "broken", "empty"):
                with self.subTest(size=size, scenario=scenario):
                    window = self.make(Stepped(scenario), size=size)
                    ui_offscreen.wait_until(self.app, lambda w=window: w.scroll.horizontalScrollBar().maximum() == 0, 2)
                    self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)
                    self.assertEqual(ui_offscreen.find_clipping(window), [])
                    self.assertEqual(ui_offscreen.find_squeezed(window.screen_widget), [])
                    for row in self.card(window).rows:
                        self.assertLessEqual(row.title.fontMetrics().horizontalAdvance(row.title._full), row.title.width(), f"제목이 줄임표로 잘리지 않는다 — {row.title._full}")
                    window.close()

    def test_the_card_still_fits_while_writing_and_with_every_kind_of_notice(self):
        for size in ((900, 560), (1366, 768)):
            with self.subTest(size=size):
                provider = Stepped()
                provider.steps = ((0.6, T["backup_step_save"]),)
                window = self.make(provider, size=size)
                self.click(self.card(window).create_button)
                ui_offscreen.wait_until(self.app, lambda: window.state.backups.progress[0] == 0.6, 5)
                self.settle(2)
                self.assertEqual(ui_offscreen.find_clipping(window), [])
                self.assertEqual(ui_offscreen.find_squeezed(window.screen_widget), [])
                provider.release.put(1)
                self.wait_write(window)
                for notice in (("ok", T["backup_ok_restored"], ("키는 백업에 없어요",)), ("warning", T["backup_ok_partial"].format(text="Seed(읽을 수 없어요)"), ()),
                               ("error", T["backup_fail_blocked"], ("저장한 초안 — 예시 글 1 — 3번째 줄 — 키 모양(Google API 키)",) * 3), ("error", T["backup_fail_restore_left"], ("글 보관함", "설정"))):
                    window.state.backups.notice = notice
                    window.render()
                    self.settle(3)
                    self.assertEqual(ui_offscreen.find_clipping(window), [], notice[0])
                    self.assertEqual(ui_offscreen.find_squeezed(window.screen_widget), [], notice[0])
                    self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)
                window.close()


class RealServiceTest(Base):
    """실제 서비스(`service/backup_flow.py`)를 임시 폴더에서 카드 단추로 끝까지 돌린다 — 어댑터가 서비스 결과를 화면이 아는 모양으로 옮기는 길 전체."""

    def manifest_of(self, world, name):
        return json.loads((world.ctx.workspace.backups_dir / name / bf.MANIFEST_NAME).read_text(encoding="utf-8"))

    def make_real(self, **world_kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world = bs.World.cached(tmp.name, **world_kwargs)
        provider = backups_adapter.ServiceBackupsProvider(str(world.root), context_factory=lambda data_dir=None: world.ctx)
        return world, provider, self.make(provider)

    def test_the_real_service_makes_lists_and_restores_through_the_card(self):
        world, provider, window = self.make_real()
        card = self.card(window)
        self.assertEqual(window.state.backups.state, "empty")
        self.assertIn(str(world.ctx.workspace.backups_dir), card.notes[0].plain_text(), "백업 위치가 글자로 보인다")
        self.assertFalse(world.ctx.workspace.backups_dir.exists(), "목록을 읽는 것은 폴더도 만들지 않는다")
        before_dump = world.dumps()
        before_files = world.data_digests()
        self.click(card.create_button)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual(self.notice_level(card), "ok")
        self.assertEqual(len(card.rows), 1)
        row = card.rows[0]
        self.assertEqual(self.badges(row), [T["backup_kind_backup"], T["backup_status_complete"], SHORT_NOTE])
        self.assertTrue(any("글 2개" in line.plain_text() for line in row.lines), [line.plain_text() for line in row.lines])
        self.assertEqual(world.data_digests(), before_files, "백업은 지금 데이터를 한 바이트도 바꾸지 않는다")
        manifest = self.manifest_of(world, row.name)
        self.assertIs(manifest["credential_excluded"], True)
        self.assertEqual(manifest["credential_excluded_note"], CREDENTIAL_NOTE)
        world.ctx.clock.advance(seconds=30)                                               # 복원 직전 사본은 백업보다 나중에 만들어진다(고정 시계를 앞으로)
        with world.ctx.store() as store:                                                  # 백업 뒤에 글이 늘었다 — 복원하면 이 글은 사라진다
            store.save_draft(world.ids[0], "백업 뒤에 쓴 초안")
        projects.new_project(world.ctx, "백업 뒤의 새 글", "본문")
        changed_dump = world.dumps()
        self.assertNotEqual(changed_dump, before_dump)
        self.restore_through_dialog(window, row.name)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("ok", T["backup_ok_restored"]))
        self.assertIn(RESTORE_NOTE, self.texts(card), "복원한 뒤 키를 다시 등록하라는 안내")
        self.assertEqual(world.dumps(), before_dump, "복원하면 백업 때의 내용으로 돌아온다")
        self.assertEqual([item.name.startswith("before-") for item in card.rows], [True, False], "복원 직전 사본이 목록에 생겼다")
        safety = card.rows[0]
        self.assertEqual(self.badges(safety)[0], T["backup_kind_safety"])
        self.restore_through_dialog(window, safety.name)                                  # 잘못 복원했다면 그 사본으로 다시 복원할 수 있다
        self.wait_write(window)
        self.assertEqual(self.notice_level(self.card(window)), "ok")
        self.assertEqual(world.dumps(), changed_dump, "복원 직전 사본으로 되돌리면 복원하기 직전의 내용이다")

    def test_a_secret_shaped_text_stops_the_backup_and_the_screen_shows_the_place_and_the_kind_but_never_the_text(self):
        for kind in ("google_api_key", "github_token", "pem_private_key"):
            with self.subTest(kind=kind):
                world, provider, window = self.make_real()
                token = bs.secret_token(kind)
                bs.plant_draft(world, bs.three_lines(kind))
                before = world.data_digests()
                card = self.card(window)
                self.click(card.create_button)
                self.wait_write(window)
                card = self.card(window)
                self.assertEqual((self.notice_level(card), self.notice_text(card)), ("error", T["backup_fail_blocked"]))
                lines = [line.plain_text() for line in card.notice_lines]
                self.assertTrue(lines and all(lines), "발견한 위치가 줄로 나온다")
                self.assertTrue(any("저장한 초안" in line for line in lines) or any("초안" in line for line in lines), lines)
                shown = "\n".join(text for _label, text in leak.widget_texts(window))
                self.assertFalse(bs.S.leaked(shown, token), "키 모양 글이 화면 어디에도 없다")
                self.assertNotIn("Traceback", shown)
                backups_dir = world.ctx.workspace.backups_dir
                self.assertEqual(list(backups_dir.iterdir()) if backups_dir.exists() else [], [], "부분 폴더도 남기지 않는다")
                self.assertEqual(world.data_digests(), before, "아무것도 지우거나 바꾸지 않는다")
                for button in card.findChildren(QAbstractButton):
                    for word in IGNORE_WORDS:
                        self.assertNotIn(word, button.text())
                window.close()

    def test_a_restore_of_a_backup_made_by_a_newer_program_is_refused_with_the_fixed_sentence(self):
        world, provider, window = self.make_real()
        self.click(self.card(window).create_button)
        self.wait_write(window)
        row = self.card(window).rows[0]
        manifest = self.manifest_of(world, row.name)
        manifest["app_version"] = "99.0.0"
        bs.write_manifest(world.ctx.workspace.backups_dir / row.name, manifest)
        window.reload_backups()
        self.wait_loaded(window)
        before = world.data_digests()
        self.restore_through_dialog(window, row.name)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("error", T["backup_fail_newer"]), "새 프로그램이 만든 백업은 쓰지 않는다")
        self.assertEqual(world.data_digests(), before, "아무것도 바뀌지 않았다")
        self.assertFalse((world.ctx.workspace.backups_dir / "before-restore").exists(), "거절했으니 안전 사본도 만들지 않았다")


if __name__ == "__main__":
    unittest.main()
