"""키 연결 화면(P4f)의 PySide6 시험 — 설정 화면의 연결 카드에 더한 키 행동(등록 대화상자·확인 단계·삭제 확인창·별칭 바꾸기·상태·순서·연결 시험)과 **키가 새지 않는 구조**를 확인한다. 창을 화면에 띄우지 않는다(offscreen).
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_keys_core`·`test_ui_keys_adapter`). 사용자의 클립보드·보관소·데이터 폴더는 건드리지 않는다(가짜 공급자·임시 폴더의 가짜 보관소 — 진짜 자격 증명 관리자는 부르지 않는다).
클립보드는 시험이 정한 글로 바꿔 쓰고 끝나면 원래 글로 되돌린다.

지키는 것:
  1) 읽기 전용 공급자의 카드는 이전과 같다(키 구역 없음). 쓰는 공급자의 카드는 행(별칭·배지·마지막 성공·마지막 오류·우선순위)·단추(이름 있는 36px 이상)·'키 등록' 을 가지고, 꺼진 단추는 까닭을 툴팁·접근 설명으로(중요한 까닭은 글로도) 알린다.
  2) 키 입력 칸은 마스킹이다 — 복사·잘라내기가 글을 클립보드에 내보내지 않고 Qt 가 예측 입력·민감 정보 표시를 켠다. 제출·취소·Esc·다른 대화상자로 바뀜·창 닫힘 어느 길로든 칸이 비고 되돌리기 기록도 없다.
  3) 등록은 두 단계(입력 → 확인)이고 확인 단계의 처음 포커스는 취소다(요약에는 서비스·제공자·별칭만, 키는 안 보인다). 삭제는 확인창이 먼저고(위험 단추·처음 포커스 취소) 연달아 눌러도 한 번만 지운다. 옛 확인창의 단추가 새 대화상자에 남지 않는다(F-H1).
  4) 쓰는 동안 모든 단추가 꺼지고 두 번째 클릭은 아무 일도 하지 않는다. 실패해도 별칭 같은 입력은 남고 키만 다시 입력한다.
  5) **가짜 키와 그 조각이 위젯 트리의 어떤 글·툴팁·접근 이름에도, 상태 구조에도, 클립보드에도, 표준 출력·오류에도, 데이터 폴더의 어떤 파일에도 없다**(입력 중인 칸 자신의 글만 예외 — 저장·취소 뒤에는 그것도 0건).
  6) 모든 눌리는 부품은 접근 이름과 36px 이상의 누르는 칸을 가지고, 가로 스크롤·글자 잘림이 없으며 대화상자는 어느 필요한 크기에서도 창 안에 있고 단추가 보인다.
  7) 이 모듈의 창은 고정 시계로 만든다(`FIXED_NOW`) — 컴퓨터 시계의 분·초에 따라 글 검사가 우연히 실패하지 않는다(독립 검증 M3). 삭제 도중 저장이 실패해도 화면이 목록을 다시 읽어 그 행을 '키를 찾지 못했어요' 로 보인다(M1).
"""
import ast
import contextlib
import datetime
import errno
import importlib.util
import io
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import key_leak_support as leak  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import context as cx  # noqa: E402
from chanceblog_desktop.ui import keys_adapter  # noqa: E402
from chanceblog_desktop.ui.core import clock as clock_rules, keys, services  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QAccessible, QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QLabel, QLineEdit, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import key_parts
    from chanceblog_desktop.ui.qt import shell as shell_module

KEY = leak.make_key("a")
OTHER = leak.make_key("b")
NEEDLES = leak.needles(KEY, OTHER)
FIXED_NOW = datetime.datetime(2026, 11, 6, 20, 10)                       # 이 모듈의 모든 창은 이 시각으로 고정한 시계를 쓴다 — 컴퓨터 시계를 쓰면 상단 앱 바 시계 글(`HH:MM`)과 진단 정보의 `time: … HH:MM:SS` 가 때마다 달라져 길이 숫자 같은 글 검사가 특정 분·초(37)에만 우연히 실패한다(독립 검증 M3)
SIZES = ((1366, 768), (1093, 614), (910, 512), (1536, 864), (1280, 720), (1920, 1080), (900, 560))             # 910×512 = 1366×768 노트북의 150%(논리 크기), 1093×614 = 125%


class Gated(keys.FakeKeysProvider):
    """쓰기가 **시험이 문을 열어 줄 때까지** 기다리는 가짜 공급자 — 시간에 기대지 않고 '쓰는 중' 을 확실히 본다. `taken` 은 등록으로 받은 통의 글(시험이 키가 닿았는지 보려고 따로 적는 사본 — 앱 구조가 아니다)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()
        self.gate.set()
        self.taken = []
        self.threads = []

    def _enter(self, name, cancelled):
        self.threads.append(threading.current_thread())
        if not self.gate.wait(30):
            raise AssertionError("시험이 쓰기의 문을 열어 주지 않았다")
        super()._enter(name, cancelled)

    def add_key(self, purpose, provider, name, secret, terms_ack, progress, cancelled):
        self.taken.append(dict(secret._fields))
        return super().add_key(purpose, provider, name, secret, terms_ack, progress, cancelled)


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
        """`deleteLater` 로 미룬 삭제를 지금 처리한다(`processEvents` 는 미룬 삭제를 처리하지 않는다 — 치운 부품이 정말 사라졌는지 보려면 필요하다)."""
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.settle(2)

    def activate(self, window):
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)

    def make(self, provider=None, size=(1366, 768), page="settings", **kwargs):
        provider = provider or keys.FakeKeysProvider()
        kwargs.setdefault("clock", clock_rules.FixedClock(FIXED_NOW))                  # 독립 검증 M3: 화면 시계를 고정한다(시험이 따로 시계를 주면 그것을 쓴다)
        window = shell_module.AppShell(services.FakeHomeProvider(), connections=provider, autoload=False, **kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        if page == "settings":
            window.go("settings")
            ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10)
            self.settle()
            self.open_all(window)
        return window

    def open_all(self, window):
        for accordion in window.screen_widget.findChildren(UI.Accordion):
            if not accordion.is_open:
                accordion.flip()
        self.settle()

    def rows(self, window, purpose=None):
        return [row for row in window.screen_widget.findChildren(key_parts.KeyRow) if purpose in (None, row.purpose)]

    def register_button(self, window, purpose):
        return next(widget for widget in window.screen_widget.findChildren(QAbstractButton) if widget.property("focus_key") == f"key-register:{purpose}")

    def click(self, button):
        self.assertTrue(button.isVisible() and button.isEnabled(), button.accessibleName())
        QTest.mouseClick(button, Qt.LeftButton)
        self.settle(3)

    def wait_write(self, window, seconds=10):
        ui_offscreen.wait_until(self.app, lambda: not window.state.keys.busy and window.state.keys.pending is None, seconds)
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading" and not window.state.conn_loading, seconds)
        self.settle()

    def press(self, widget, key):
        widget.setFocus(Qt.OtherFocusReason)
        QTest.keyClick(widget, key)
        self.settle(3)

    def open_register(self, window, purpose="ai_assist"):
        self.click(self.register_button(window, purpose))
        self.assertTrue(window.dialog.is_open)
        return window.key_form

    def type_key(self, form, key=KEY, name=None):
        for edit_name, edit in form.secret_edits.items():
            if name in (None, edit_name):
                edit.setFocus(Qt.OtherFocusReason)
                QTest.keyClicks(edit, key)
        self.settle(2)

    def dialog_buttons(self, window):
        return [button for button in window.dialog.findChildren(QAbstractButton) if button.isVisible()]

    def button_with(self, window, text):
        return next(button for button in self.dialog_buttons(window) if button.text() == text)

    def everything(self, window):
        return [text for _label, text in leak.widget_texts(window)]


class ScreenTest(Base):
    def test_a_read_only_provider_keeps_the_old_cards_with_no_key_buttons(self):
        window = self.make(services.FakeConnectionsProvider())
        self.assertEqual(self.rows(window), [])
        self.assertEqual([widget for widget in window.screen_widget.findChildren(QAbstractButton) if str(widget.property("focus_key") or "").startswith("key")], [])
        texts = [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]
        self.assertIn(T["conn_keys_note"], texts)
        self.assertNotIn(T["conn_keys_note_write"], texts)

    def test_a_writable_card_shows_rows_with_badges_lines_actions_and_a_register_button(self):
        window = self.make()
        rows = self.rows(window)
        self.assertGreaterEqual(len(rows), 4)
        image = self.rows(window, "image_provider")[0]
        self.assertEqual(image.name.text(), "예시 키 1")
        badges = [label.text() for label in image.findChildren(QLabel) if label.property("badge")]
        self.assertEqual(badges, ["사용"])
        self.assertIn("마지막 성공: 아직 없어요", [label.plain_text() for label in image.lines])
        self.assertEqual(list(image.buttons), ["test", "state:off", "rename", "delete"])
        self.assertEqual([button.text() for button in image.buttons.values()], ["연결 시험", "끄기", "별칭 바꾸기", "삭제"])
        self.assertIn("연결 시험 — 예시 키 1", [button.accessibleName() for button in image.buttons.values()])
        self.assertIn(T["conn_keys_note_write"], [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)])
        for purpose in ("naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger"):
            self.assertIsNotNone(self.register_button(window, purpose), purpose)

    def test_every_new_part_has_an_accessible_name_and_a_big_enough_hit_target(self):
        window = self.make()
        new = [widget for widget in window.screen_widget.findChildren(QAbstractButton) if str(widget.property("focus_key") or "").startswith("key")]
        self.assertGreaterEqual(len(new), 12)
        for widget in new:
            self.assertTrue(widget.accessibleName().strip(), widget.text())
            self.assertGreaterEqual(widget.height(), 36, widget.accessibleName())
            self.assertTrue(widget.text().strip())
        self.assertEqual(ui_offscreen.find_clipping(window), [])

    def test_disabled_buttons_say_why_by_tooltip_and_description_and_the_main_reasons_are_also_plain_text(self):
        window = self.make()
        apihub = self.rows(window, "naver_apihub")[0]
        test = apihub.buttons["test"]
        self.assertFalse(test.isEnabled())
        self.assertEqual((test.toolTip(), test.accessibleDescription()), (T["keys_why_terms"], T["keys_why_terms"]))
        self.assertIn(T["keys_why_terms"], [label.plain_text() for label in apihub.reasons])
        searchad = self.rows(window, "naver_searchad")[0]
        self.assertEqual(searchad.buttons["test"].toolTip(), T["keys_why_prep"])
        self.assertIn(T["keys_why_prep"], [label.plain_text() for label in searchad.reasons])
        self.assertEqual(searchad.buttons["up"].toolTip(), T["keys_why_first"])
        self.assertTrue(self.rows(window, "image_provider")[0].buttons["test"].isEnabled(), "호출 코드가 있는 예시 용도는 시험할 수 있다")
        register = self.register_button(window, "naver_apihub")
        self.assertFalse(register.isEnabled())
        self.assertIn("1개까지만", register.toolTip())

    def test_without_a_key_store_the_key_actions_are_off_with_a_visible_reason_and_the_page_still_works(self):
        window = self.make(keys.FakeKeysProvider(store_ready=False))
        texts = [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]
        self.assertIn(T["keys_store_missing"], texts)
        self.assertIn(T["keys_store_missing_why"], texts)
        for purpose in ("naver_apihub", "image_provider"):
            row = self.rows(window, purpose)[0]
            for name in ("test", "rename", "delete"):
                self.assertFalse(row.buttons[name].isEnabled(), (purpose, name))
                self.assertEqual(row.buttons[name].toolTip(), T["keys_store_missing"])
            self.assertTrue(row.buttons["state:off"].isEnabled())
            self.assertFalse(self.register_button(window, purpose).isEnabled())
        self.assertEqual(ui_offscreen.find_clipping(window), [])

    def test_a_card_without_keys_says_not_connected_and_offers_the_registration_and_github_has_no_key_controls(self):
        window = self.make(keys.FakeKeysProvider("not_connected"))
        texts = [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]
        self.assertEqual(texts.count(T["keys_none"]), 4)                                 # 키를 받는 카드 넷(NAVER API HUB·이미지 공급자·AI 보조·Blogger) — 키 없는 GitHub 카드는 이 문장이 없다
        self.assertTrue(self.register_button(window, "ai_assist").isEnabled())
        self.assertFalse([widget for widget in window.screen_widget.findChildren(QAbstractButton) if widget.property("focus_key") == "key-register:github_repo"])
        self.assertIn(T["nokey_note_off"], texts)                                        # 의도적 갱신(PCSEC1 H3): 이 빌드는 외부 게시가 꺼져 있어 'Git 로그인을 써요' 라고 말하지 않는다
        self.assertNotIn(T["nokey_note"], texts)
        from chanceblog_desktop import capabilities
        with mock.patch.object(capabilities, "EXTERNAL_WRITE", True):                    # 켜진 모양(시험에서만)은 옛 문장 그대로
            opened = self.make(keys.FakeKeysProvider("not_connected"))
            self.assertIn(T["nokey_note"], [label.plain_text() for label in opened.screen_widget.findChildren(UI.Label)])

    def test_the_busy_state_is_a_notice_and_the_whole_screen_has_the_same_notice_line_as_the_last_result(self):
        provider = Gated()
        window = self.make(provider)
        provider.gate.clear()
        row = self.rows(window, "image_provider")[0]
        self.click(row.buttons["state:off"])
        self.assertTrue(window.state.keys.busy)
        notices = [widget for widget in window.screen_widget.findChildren(QFrame) if widget.property("notice")]
        self.assertTrue(notices and T["keys_busy_status"] in notices[0].accessibleName())
        provider.gate.set()
        self.wait_write(window)
        notices = [widget for widget in window.screen_widget.findChildren(QFrame) if widget.property("notice")]
        self.assertEqual([notice.property("notice") for notice in notices], ["ok"])
        self.assertIn(T["keys_ok_state"], notices[0].accessibleName())


class RegisterTest(Base):
    def test_the_dialog_opens_with_masked_boxes_the_default_alias_and_the_focus_on_the_first_key_box(self):
        window = self.make(keys.FakeKeysProvider("not_connected"))
        form = self.open_register(window, "image_provider")
        self.assertEqual(form.draft.vm()["title"], "키 등록 — 이미지 공급자")
        self.assertEqual(form.alias_edit.text(), "기본")
        self.assertEqual(list(form.secret_edits), ["access_key"])
        edit = form.secret_edits["access_key"]
        self.assertEqual(edit.echoMode(), QLineEdit.Password)
        self.assertIs(QApplication.focusWidget(), edit)
        self.assertEqual(edit.placeholderText(), "")
        self.assertEqual(edit.toolTip(), "")
        self.assertEqual(sorted(form.chips), ["pexels", "pixabay", "unsplash"])
        self.assertEqual([chip.isChecked() for chip in form.chips.values()], [True, False, False])
        self.assertEqual(window.dialog.accessibleName(), "이미지 공급자 키 등록 1단계 입력")

    def test_a_masked_box_is_hidden_from_copying_and_asks_the_input_method_not_to_learn(self):
        window = self.make(keys.FakeKeysProvider("not_connected"))
        edit = self.open_register(window, "ai_assist").secret_edits["key"]
        self.clipboard.setText("먼저 복사해 둔 글")
        QTest.keyClicks(edit, KEY)
        edit.selectAll()
        edit.copy()
        edit.cut()
        self.assertEqual(self.clipboard.text(), "먼저 복사해 둔 글", "마스킹 칸은 복사·잘라내기가 글을 클립보드에 내보내지 않는다")
        self.assertEqual(edit.text(), "", "잘라내기는 글을 지우되 내보내지 않는다")
        hints = edit.inputMethodHints()
        for hint in (Qt.ImhHiddenText, Qt.ImhNoPredictiveText, Qt.ImhSensitiveData, Qt.ImhNoAutoUppercase):
            self.assertTrue(hints & hint, hint)
        self.assertIsNone(edit.completer())
        QTest.keyClicks(edit, KEY)
        self.assertNotIn(KEY[:6], edit.displayText())
        interface = QAccessible.queryAccessibleInterface(edit)
        self.assertEqual(leak.text_hits(interface.text(QAccessible.Text.Value), NEEDLES), [])

    def test_an_empty_next_shows_the_problem_beside_the_box_and_moves_the_focus_there(self):
        window = self.make(keys.FakeKeysProvider("not_connected"))
        form = self.open_register(window, "ai_assist")
        self.click(form.next_button)
        self.assertEqual(form.draft.step, "input")
        self.assertTrue(form.errors["key"].isVisible())
        self.assertEqual(form.errors["key"].plain_text(), "API 키 칸이 비어 있어요.")
        self.assertIs(QApplication.focusWidget(), form.secret_edits["key"])
        form.alias_edit.setText("")
        self.click(form.next_button)
        self.assertTrue(form.errors["name"].isVisible())
        self.assertEqual(form.errors["name"].plain_text(), T["keys_alias_empty"])

    def test_next_cleans_line_breaks_and_shows_a_summary_with_no_key_and_the_focus_on_cancel(self):
        window = self.make(keys.FakeKeysProvider("not_connected"))
        form = self.open_register(window, "image_provider")
        edit = form.secret_edits["access_key"]
        edit.setText(chr(10) + "  " + KEY + chr(13) + chr(10))
        form.alias_edit.setText("  내   별칭 ")
        self.click(form.next_button)
        self.assertEqual(form.draft.step, "confirm")
        self.assertTrue(form.confirm_page.isVisible() and not form.input_page.isVisible())
        self.assertEqual([label.plain_text() for label in form.summary], ["서비스: 이미지 공급자", "제공자: Unsplash", "별칭: 내 별칭"])
        self.assertEqual(edit.text(), KEY, "다듬은 글(줄바꿈·앞뒤 공백 없음)")
        self.assertIs(QApplication.focusWidget(), form.confirm_cancel)
        self.assertEqual(window.dialog.accessibleName(), "이미지 공급자 키 등록 2단계 확인")
        self.assertEqual(leak.widget_hits(window, NEEDLES, typing_into=[edit]), [], "입력 칸 자신을 뺀 모든 글·툴팁·접근 이름")
        self.assertEqual(leak.graph_hits(window.state, NEEDLES, skip=(self,)), [])

    def test_the_confirm_step_default_is_cancel_so_enter_never_saves_and_back_returns_to_the_input(self):
        provider = Gated("not_connected")
        window = self.make(provider)
        form = self.open_register(window, "image_provider")
        self.type_key(form)
        self.click(form.next_button)
        self.press(form.confirm_cancel, Qt.Key_Return)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(provider.writes, [])
        self.assertIsNone(window.state.keys.draft)
        form = self.open_register(window, "image_provider")
        self.type_key(form)
        self.click(form.next_button)
        self.click(form.back_button)
        self.assertEqual((form.draft.step, form.secret_edits["access_key"].text()), ("input", KEY))
        self.assertTrue(form.input_page.isVisible())

    def test_a_confirm_step_shown_directly_still_starts_on_cancel(self):
        """대화상자를 확인 단계로 곧바로 보이는 길(지금은 초안이 확인 단계로 다시 열리지 않지만 `focus_start` 가 두 단계를 다 안다)도 처음 포커스는 취소다 — Enter 를 잘못 눌러도 저장되지 않는다."""
        window = self.make(keys.FakeKeysProvider("not_connected"))
        form = self.open_register(window, "image_provider")
        self.type_key(form)
        form.draft.step = "confirm"
        form.refresh()
        form.focus_start()
        self.assertIs(QApplication.focusWidget(), form.confirm_cancel)

    def test_save_hands_the_key_to_the_worker_once_wipes_every_box_and_shows_the_result(self):
        provider = Gated("not_connected")
        window = self.make(provider)
        form = self.open_register(window, "image_provider")
        edit = form.secret_edits["access_key"]
        self.type_key(form)
        form.alias_edit.setText("내 별칭")
        self.click(form.next_button)
        provider.gate.clear()
        self.click(form.save_button)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(edit.text(), "")
        self.assertFalse(edit.isUndoAvailable() or edit.isRedoAvailable())
        self.assertTrue(window.state.keys.busy)
        self.assertFalse(any(row_button.isEnabled() for row in self.rows(window) for row_button in row.buttons.values()), "쓰는 동안 모든 행동 단추가 꺼진다")
        provider.gate.set()
        self.wait_write(window)
        self.assertEqual(provider.taken, [{"access_key": KEY}], "키는 통에 담겨 공급자에게만 갔다")
        self.assertEqual(provider.writes, ["add"])
        self.assertNotEqual(provider.threads[0], threading.main_thread())
        self.assertEqual([row.name.text() for row in self.rows(window, "image_provider")], ["내 별칭"])
        self.assertEqual(window.state.keys.notice, ("ok", T["keys_ok_added"]))
        self.assertEqual(leak.widget_hits(window, NEEDLES), [])
        self.assertEqual(leak.graph_hits(window.state, NEEDLES, skip=(self, provider)), [])
        self.assertEqual(leak.graph_hits(window.state.runner, NEEDLES, skip=(self, provider)), [])

    def test_every_way_of_closing_empties_the_boxes_and_clears_the_undo_history(self):
        for way in ("cancel", "escape", "x-close-window", "another-dialog", "back-then-cancel"):
            with self.subTest(way=way):
                window = self.make(keys.FakeKeysProvider("not_connected"))
                form = self.open_register(window, "ai_assist")
                edit = form.secret_edits["key"]
                self.type_key(form)
                self.assertEqual(edit.text(), KEY)
                if way == "cancel":
                    self.click(form.cancel_button)
                elif way == "escape":
                    QTest.keyClick(window, Qt.Key_Escape)
                elif way == "x-close-window":
                    window.close()
                elif way == "another-dialog":
                    window.show_dialog("다른 안내", "내용", ok="확인")
                else:
                    self.click(form.next_button)
                    self.click(form.back_button)
                    self.click(form.cancel_button)
                self.settle()
                self.assertEqual(edit.text(), "", way)
                self.assertFalse(edit.isUndoAvailable() or edit.isRedoAvailable(), way)
                self.assertIsNone(window.state.keys.draft if way != "another-dialog" else None)
                self.assertEqual(leak.widget_hits(window, NEEDLES), [], way)

    def test_clear_alone_would_leave_the_text_in_the_undo_history_and_the_wipe_does_not(self):
        plain = QLineEdit()
        plain.setText(KEY)
        plain.clear()
        self.assertTrue(plain.isUndoAvailable(), "대조군: clear() 는 지운 글을 되돌리기 기록에 남긴다")
        masked = UI.SecretInput("키")
        QTest.keyClicks(masked, KEY)
        masked.clear()
        masked.undo()
        masked.setText(KEY)
        self.assertTrue(UI.wipe_input(masked))
        self.assertEqual(masked.text(), "")
        masked.undo()
        masked.redo()
        self.assertEqual(masked.text(), "")

    def test_a_pasted_key_is_taken_off_the_clipboard_when_the_dialog_closes_but_other_text_is_left_alone(self):
        window = self.make(keys.FakeKeysProvider("not_connected"))
        for clip, expected in ((KEY, ""), ("  " + KEY + chr(10), ""), ("내가 따로 복사한 글", "내가 따로 복사한 글"), ("", "")):
            with self.subTest(clip=clip[:6]):
                form = self.open_register(window, "ai_assist")
                self.clipboard.setText(clip)
                edit = form.secret_edits["key"]
                edit.setFocus(Qt.OtherFocusReason)
                QTest.keyClicks(edit, KEY)
                self.click(form.cancel_button)
                self.assertEqual(self.clipboard.text(), expected)

    def test_the_clipboard_is_cleared_on_save_too_and_the_injected_wiper_gets_only_cleaned_texts(self):
        calls = []
        window = self.make(keys.FakeKeysProvider("not_connected"), clipboard_wipe=lambda texts: calls.append(list(texts)) or True)
        form = self.open_register(window, "ai_assist")
        edit = form.secret_edits["key"]
        edit.setText(" " + KEY + " ")
        self.click(form.next_button)
        self.click(form.save_button)
        self.wait_write(window)
        self.assertEqual(calls, [[KEY]], "저장하는 순간 한 번(저장 뒤 닫을 때는 이미 빈 칸이라 부르지 않는다)")

    def test_a_pasted_key_with_the_real_clipboard_is_wiped_through_the_real_function(self):
        self.clipboard.setText(KEY + chr(10))
        self.assertFalse(shell_module.qt_clipboard_wipe(["다른 글"]))
        self.assertEqual(self.clipboard.text(), KEY + chr(10))
        self.assertTrue(shell_module.qt_clipboard_wipe([KEY]))
        self.assertEqual(self.clipboard.text(), "")
        self.assertFalse(shell_module.qt_clipboard_wipe([KEY]))

    def test_a_key_pasted_into_the_alias_box_is_cleared_at_once_with_a_message(self):
        window = self.make(keys.FakeKeysProvider("not_connected"))
        form = self.open_register(window, "ai_assist")
        form.alias_edit.setFocus(Qt.OtherFocusReason)
        form.alias_edit.selectAll()
        self.clipboard.setText(KEY)
        form.alias_edit.paste()                                                         # 키를 별칭 칸에 잘못 붙여 넣는다(한 번에 들어온다)
        self.clipboard.clear()
        self.settle(2)
        self.assertEqual(form.alias_edit.text(), "")
        self.assertEqual(form.draft.alias, "")
        self.assertTrue(form.errors["name"].isVisible())
        self.assertEqual(form.errors["name"].plain_text(), T["keys_alias_keyish"])
        self.assertEqual(leak.widget_hits(window, NEEDLES), [])
        self.assertEqual(leak.graph_hits(window.state, NEEDLES, skip=(self,)), [])

    def test_the_second_key_of_a_service_needs_the_terms_box_and_space_switches_it(self):
        provider = Gated("not_connected")
        window = self.make(provider)
        first = self.open_register(window, "ai_assist")
        self.type_key(first)
        self.click(first.next_button)
        self.assertFalse(first.terms_toggle.isVisible(), "첫 키에는 약관 확인이 없다")
        self.click(first.save_button)
        self.wait_write(window)
        second = self.open_register(window, "ai_assist")
        second.alias_edit.setText("둘째")
        self.type_key(second, OTHER)
        self.click(second.next_button)
        self.assertTrue(second.terms_toggle.isVisible() and second.terms_text.isVisible())
        self.assertFalse(second.save_button.isEnabled())
        self.assertEqual(second.save_button.toolTip(), T["keys_fail_terms"])
        self.press(second.terms_toggle, Qt.Key_Space)
        self.assertTrue(second.terms_toggle.isChecked() and second.save_button.isEnabled())
        self.click(second.save_button)
        self.wait_write(window)
        self.assertEqual([row.name.text() for row in self.rows(window, "ai_assist")], ["기본", "둘째"])

    def test_the_provider_chips_show_the_full_one_disabled_and_the_choice_goes_to_the_summary(self):
        window = self.make()
        form = self.open_register(window, "image_provider")
        self.assertFalse(form.chips["unsplash"].isEnabled())
        self.assertIn(T["keys_reg_provider_full"], form.chips["unsplash"].accessibleName())
        self.assertTrue(form.chips["pexels"].isChecked())
        self.click(form.chips["pixabay"])
        self.assertEqual(form.draft.provider, "pixabay")
        self.type_key(form)
        self.click(form.next_button)
        self.assertEqual(form.summary[1].plain_text(), "제공자: Pixabay")

    def test_a_failed_save_reopens_the_dialog_with_the_alias_and_the_problem_and_empty_key_boxes(self):
        provider = Gated("not_connected")
        window = self.make(provider)
        form = self.open_register(window, "image_provider")
        form.alias_edit.setText("남는 별칭")
        edit = form.secret_edits["access_key"]
        edit.setFocus(Qt.OtherFocusReason)
        QTest.keyClicks(edit, KEY[:9])                                                  # 가짜 서비스의 최소 길이(16)보다 짧다
        self.click(form.next_button)
        self.click(form.save_button)
        self.wait_write(window)
        self.assertTrue(window.dialog.is_open)
        again = window.key_form
        self.assertEqual((again.alias_edit.text(), again.secret_edits["access_key"].text()), ("남는 별칭", ""))
        self.assertTrue(again.errors["access_key"].isVisible())
        self.assertEqual(again.errors["access_key"].plain_text(), "Access Key 칸이 너무 짧아요(최소 16자). 끝까지 복사됐는지 확인해 주세요.")
        self.assertIs(QApplication.focusWidget(), again.secret_edits["access_key"])
        self.assertEqual(window.state.keys.notice[0], "error")
        self.assertEqual(leak.widget_hits(window, leak.needles(KEY[:9], size=4)), [])

    def test_tab_stays_inside_the_dialog_for_a_whole_round(self):
        window = self.make(keys.FakeKeysProvider("not_connected"))
        form = self.open_register(window, "image_provider")
        seen = []
        for _ in range(16):
            focus = QApplication.focusWidget()
            self.assertTrue(focus is not None and window.dialog.isAncestorOf(focus), focus)
            seen.append(focus)
            QTest.keyClick(focus, Qt.Key_Tab)
            self.settle(2)
        self.assertIn(form.alias_edit, seen)
        self.assertIn(form.next_button, seen)
        self.assertIn(form.secret_edits["access_key"], seen)

    def test_the_dialog_fits_every_size_with_its_buttons_visible_even_for_three_boxes(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(keys.FakeKeysProvider("not_connected"), size=size)
                form = self.open_register(window, "blogger")
                self.assertEqual(len(form.secret_edits), 3)
                self.settle(6)
                dialog = window.dialog
                self.assertTrue(window.rect().contains(dialog.geometry()), (size, dialog.geometry(), window.rect()))
                for button in (form.cancel_button, form.next_button):
                    top_left = button.mapTo(window, button.rect().topLeft())
                    self.assertTrue(window.rect().contains(top_left) and button.isVisible(), (size, button.text()))
                self.assertEqual(ui_offscreen.find_clipping(dialog), [], size)
                self.type_key(form)
                self.click(form.next_button)
                self.assertTrue(form.confirm_cancel.isVisible() and window.rect().contains(form.confirm_cancel.mapTo(window, form.confirm_cancel.rect().topLeft())), size)
                self.assertEqual(ui_offscreen.find_squeezed(dialog), [], size)

    def test_the_dialog_is_as_tall_as_its_content_and_scrolls_only_when_the_window_is_too_short(self):
        """등록 대화상자가 몸의 키만큼 열린다 — 창에 들어가는 한 스크롤 없이 모든 칸·글이 보인다(처음엔 스크롤 영역이 최소 크기로 쪼그라들어 칸이 가려졌다). 창이 낮아 못 들어갈 때만 스크롤되고 단추 줄은 늘 보인다."""
        for size in SIZES:
            for purpose, step in (("image_provider", "input"), ("blogger", "input"), ("ai_assist", "confirm")):
                with self.subTest(size=size, purpose=purpose, step=step):
                    window = self.make(keys.FakeKeysProvider("not_connected"), size=size)
                    form = self.open_register(window, purpose)
                    self.type_key(form)
                    if step == "confirm":
                        self.click(form.next_button)
                    self.settle(6)
                    capped = window.dialog.height() >= window.height() - 32
                    bar, view = form.scroll.verticalScrollBar(), form.scroll.viewport()
                    if capped:
                        self.assertGreater(bar.maximum(), 0, "창이 낮아 몸이 스크롤된다")
                    else:
                        self.assertEqual(bar.maximum(), 0, "창에 들어가면 스크롤이 없다")
                        needed = form.scroll.heightForWidth(form.scroll.width())
                        self.assertLessEqual(abs(view.height() - needed), 3, ("몸의 키만큼만 열린다(단계가 바뀌어도 옛 키로 남지 않는다)", view.height(), needed))
                        shown = list(form.secret_edits.values()) if step == "input" else form.summary
                        for widget in shown:
                            top, bottom = widget.mapTo(view, widget.rect().topLeft()), widget.mapTo(view, widget.rect().bottomRight())
                            self.assertTrue(view.rect().contains(top) and view.rect().contains(bottom), (widget.accessibleName() or widget.objectName(), top, bottom, view.rect()))
                    buttons = (form.cancel_button, form.next_button) if step == "input" else (form.confirm_cancel, form.back_button, form.save_button)
                    for button in buttons:
                        self.assertTrue(window.rect().contains(button.mapTo(window, button.rect().bottomRight())), (button.text(), size))


class DeleteAndRenameTest(Base):
    def test_delete_asks_first_with_the_focus_on_cancel_and_one_click_on_the_danger_button_deletes_once(self):
        provider = Gated()
        window = self.make(provider)
        row = self.rows(window, "image_provider")[0]
        self.click(row.buttons["delete"])
        dialog = window.state.keys.delete_dialog(window.state.keys.info("image_provider"), window.state.keys.entry("image_provider", row.ref))
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(window.dialog.accessibleName(), "키를 지울까요?")
        cancel, ok = self.button_with(window, "취소"), self.button_with(window, "지우기")
        self.assertEqual(ok.property("kind"), "danger")
        self.assertIs(QApplication.focusWidget(), cancel)
        for phrase in ("되돌릴 수 없어요", "Windows 자격 증명 관리자", "예시 키 1"):
            self.assertIn(phrase, " ".join(label.plain_text() for label in window.dialog.findChildren(UI.Label)))
        self.assertEqual(provider.writes, [])
        self.press(cancel, Qt.Key_Return)
        self.assertEqual((window.dialog.is_open, provider.writes), (False, []))
        self.click(row.buttons["delete"])
        self.click(self.button_with(window, "지우기"))
        self.wait_write(window)
        self.assertEqual(provider.writes, ["remove"])
        self.assertEqual(self.rows(window, "image_provider"), [])
        self.assertEqual(window.state.keys.notice, ("ok", T["keys_ok_removed"]))
        self.assertEqual(dialog["ok"], "지우기")

    def test_pressing_the_danger_button_again_and_again_deletes_only_once(self):
        provider = Gated()
        window = self.make(provider)
        row = self.rows(window, "image_provider")[0]
        self.click(row.buttons["delete"])
        ok = self.button_with(window, "지우기")
        provider.gate.clear()
        for _ in range(6):
            QTest.keyClick(ok, Qt.Key_Return)
            QTest.keyClick(ok, Qt.Key_Space)
            QTest.mouseClick(ok, Qt.LeftButton)
        self.settle(3)
        provider.gate.set()
        self.wait_write(window)
        self.assertEqual(provider.writes, ["remove"])

    def test_the_buttons_of_an_old_dialog_do_not_survive_into_the_next_one(self):
        """F-H1 — 옛 확인창의 단추가 안 치워져 새 대화상자 위에 남으면 확인창을 건너뛰고 지우는 쓰기가 가능했다."""
        provider = Gated()
        window = self.make(provider)
        row = self.rows(window, "image_provider")[0]
        self.click(row.buttons["delete"])
        self.assertEqual([button.text() for button in self.dialog_buttons(window)].count("지우기"), 1)
        self.click(self.button_with(window, "취소"))
        form = self.open_register(window, "ai_assist")
        self.settle(4)
        every = [button for button in window.dialog.findChildren(QAbstractButton)]
        self.assertEqual([button.text() for button in every if button.text() == "지우기" and button.isVisibleTo(window.dialog)], [], "옛 확인창의 위험 단추는 눌릴 수 없다(숨겨졌다)")
        self.flush()
        every = [button for button in window.dialog.findChildren(QAbstractButton)]
        self.assertEqual([button.text() for button in every if button.text() == "지우기"], [], "옛 확인창의 위험 단추가 남아 있지 않다(안쪽 배치의 단추까지 치워졌다)")
        self.assertEqual(provider.writes, [])
        window.show_dialog("다른 확인", "내용", ok="확인", cancel="취소")
        self.settle(4)
        self.flush()
        self.assertEqual([button.text() for button in window.dialog.findChildren(QAbstractButton)].count("취소"), 1)
        self.assertNotIn(form.next_button, window.dialog.findChildren(QAbstractButton))
        window.close_dialog()
        self.assertEqual(provider.writes, [])

    def test_rename_asks_for_the_new_name_keeps_the_input_on_a_problem_and_changes_it_on_success(self):
        provider = Gated()
        window = self.make(provider)
        row = self.rows(window, "image_provider")[0]
        self.click(row.buttons["rename"])
        form = window.key_rename_form
        self.assertEqual(form.edit.text(), "예시 키 1")
        self.assertIs(QApplication.focusWidget(), form.edit)
        form.edit.setText("")
        self.click(form.ok_button)
        self.assertTrue(form.error.isVisible() and window.dialog.is_open)
        self.assertEqual(form.error.plain_text(), T["keys_alias_empty"])
        self.assertEqual(provider.writes, [])
        form.edit.setFocus(Qt.OtherFocusReason)
        form.edit.selectAll()
        self.clipboard.setText(KEY)
        form.edit.paste()                                                               # 키를 별칭 칸에 잘못 붙여 넣는다(한 번에 들어온다)
        self.clipboard.clear()
        self.settle(2)
        self.assertEqual(form.edit.text(), "")
        self.assertEqual(form.error.plain_text(), T["keys_alias_keyish"])
        form.edit.setText("새 별칭")
        self.click(form.ok_button)
        self.wait_write(window)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual([item.name.text() for item in self.rows(window, "image_provider")], ["새 별칭"])
        self.assertEqual(provider.writes, ["rename"])
        self.assertEqual(leak.widget_hits(window, NEEDLES), [])

    def test_the_same_name_changes_nothing_and_a_duplicate_is_refused_in_the_dialog(self):
        provider = Gated()
        window = self.make(provider)
        rows = self.rows(window, "naver_searchad")
        self.click(rows[0].buttons["rename"])
        form = window.key_rename_form
        form.edit.setText("예시 키 B")
        self.click(form.ok_button)
        self.assertEqual(form.error.plain_text(), T["keys_alias_duplicate"])
        form.edit.setText("예시 키 A")
        self.click(form.ok_button)
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(provider.writes, [])


class ActionsTest(Base):
    def test_state_order_and_test_buttons_write_through_the_provider_and_the_focus_comes_back(self):
        provider = Gated()
        window = self.make(provider)
        row = self.rows(window, "naver_searchad")[0]
        ref = row.ref
        self.click(row.buttons["down"])
        self.wait_write(window)
        self.assertEqual(provider.writes, ["move"])
        names = [item.name.text() for item in self.rows(window, "naver_searchad")]
        self.assertEqual(names, ["예시 키 B", "예시 키 A"])
        focus = QApplication.focusWidget()
        self.assertEqual(focus.property("focus_key"), f"key:{ref}:up", "행이 움직여도 포커스가 그 행의 단추에 남는다")
        moved = next(item for item in self.rows(window, "naver_searchad") if item.ref == ref)
        self.click(moved.buttons["state:standby"])
        self.wait_write(window)
        self.assertEqual(provider.writes, ["move", "state"])
        badges = [label.text() for label in next(item for item in self.rows(window, "naver_searchad") if item.ref == ref).findChildren(QLabel) if label.property("badge")]
        self.assertIn("예비", badges)
        image = self.rows(window, "image_provider")[0]
        self.click(image.buttons["test"])
        self.wait_write(window)
        self.assertEqual(provider.writes[-1], "test")
        shown = [label.plain_text() for label in self.rows(window, "image_provider")[0].findChildren(UI.Label)]
        self.assertIn(T["keys_test_ok"], shown)
        self.assertIn("마지막 성공: 2026-11-07 14:20", shown)

    def test_each_test_answer_has_its_own_plain_sentence_and_a_failed_test_does_not_switch_to_another_key(self):
        for answer, sentence in (("auth_failed", T["keys_test_auth"]), ("rate_limited", T["keys_test_limit"]), ("error", T["keys_test_error"])):
            with self.subTest(answer=answer):
                provider = Gated(test_result=answer)
                window = self.make(provider)
                self.click(self.rows(window, "image_provider")[0].buttons["test"])
                self.wait_write(window)
                self.assertIn(sentence, [label.plain_text() for label in self.rows(window, "image_provider")[0].findChildren(UI.Label)])
                self.assertEqual(provider.writes, ["test"])

    def test_while_a_write_runs_every_button_is_off_and_more_clicks_do_nothing(self):
        provider = Gated()
        window = self.make(provider)
        provider.gate.clear()
        row = self.rows(window, "image_provider")[0]
        self.click(row.buttons["state:off"])
        self.assertTrue(window.state.keys.busy)
        buttons = [button for each in self.rows(window) for button in each.buttons.values()] + [self.register_button(window, key) for key in ("ai_assist", "image_provider")]
        self.assertTrue(buttons)
        for button in buttons:
            self.assertFalse(button.isEnabled(), button.accessibleName())
            QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(window.key_register("ai_assist"), None)
        self.assertEqual(window.key_action("image_provider", row.ref, "delete"), None)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(window.state.keys.start_state("image_provider", row.ref, "off")[0], "busy")
        provider.gate.set()
        self.wait_write(window)
        self.assertEqual(provider.writes, ["state"])

    def test_the_row_buttons_stay_off_after_a_write_until_the_new_value_has_been_read(self):
        """쓰기가 끝나도 새 값을 받기 전에는 낡은 목록이 보인다 — 그 사이 단추가 꺼져 있다(이미 지워진 항목의 행을 또 눌러 다시 건드리지 않게). 새 값을 받으면 켜진다."""
        provider = Gated()
        window = self.make(provider)
        gate = threading.Event()
        self.addCleanup(gate.set)
        original = provider.load_connections

        def slow(progress, cancelled):
            gate.wait(20)
            return original(progress, cancelled)
        provider.load_connections = slow
        row = self.rows(window, "image_provider")[0]
        self.click(row.buttons["state:off"])
        ui_offscreen.wait_until(self.app, lambda: window.state.keys.pending is None and window.state.keys.reloading, 10)
        self.settle(2)
        self.assertTrue(window.state.keys.reloading)
        buttons = [button for each in self.rows(window) for button in each.buttons.values()] + [self.register_button(window, key) for key in ("ai_assist", "image_provider")]
        self.assertTrue(buttons)
        for button in buttons:
            self.assertFalse(button.isEnabled(), button.accessibleName())
        gate.set()
        self.wait_write(window)
        self.assertFalse(window.state.keys.reloading)
        self.assertTrue(self.rows(window, "image_provider")[0].buttons["delete"].isEnabled())

    def refresh_button(self, window):
        return next(widget for widget in window.screen_widget.findChildren(QWidget) if widget.property("focus_key") == "refresh-conn")

    def test_the_refresh_button_is_off_and_refuses_while_a_key_write_runs(self):
        """쓰는 도중에 새로 읽으면 파일이 반쯤 바뀐 때를 읽어 낡은 목록이 남을 수 있다 — 쓰는 동안(그리고 쓴 뒤 새 값을 읽는 동안) 다시 읽기는 꺼져 있고 불러도 읽지 않는다."""
        provider = Gated()
        window = self.make(provider)
        row = self.rows(window, "image_provider")[0]
        provider.gate.clear()
        self.click(row.buttons["state:off"])
        self.assertTrue(window.state.keys.busy)
        self.assertFalse(self.refresh_button(window).isEnabled())
        calls = provider.calls
        self.assertFalse(window.reload_connections())
        self.assertEqual(provider.calls, calls, "쓰는 중에는 읽기를 시작하지 않는다")
        provider.gate.set()
        self.wait_write(window)
        self.assertTrue(self.refresh_button(window).isEnabled())
        self.assertTrue(window.reload_connections(), "끝나면 다시 읽을 수 있다")
        self.wait_write(window)

    def test_a_read_already_running_when_the_write_ends_is_followed_by_one_more_read(self):
        """쓰기가 끝났을 때 이미 돌고 있던 읽기는 쓰기 전 값일 수 있다 — 그 읽기가 끝난 뒤 한 번 더 읽고, 그때까지 단추는 꺼져 있다(낡은 목록이 남지 않는다)."""
        provider = Gated()
        window = self.make(provider)
        gate = threading.Event()
        self.addCleanup(gate.set)
        original = provider.load_connections

        def slow(progress, cancelled):
            gate.wait(20)
            return original(progress, cancelled)
        provider.load_connections = slow
        calls = provider.calls
        self.assertTrue(window.reload_connections())                                    # 쓰기 전에 시작한 읽기 하나가 돌고 있다
        row = self.rows(window, "image_provider")[0]
        self.click(row.buttons["state:off"])
        ui_offscreen.wait_until(self.app, lambda: window.state.keys.pending is None, 10)    # 쓰기는 끝났고 읽기는 아직이다
        self.assertTrue(window.state.keys.reload_wanted and window.state.keys.reloading)
        gate.set()
        self.wait_write(window)
        self.assertEqual(provider.calls, calls + 2, "돌고 있던 읽기 + 그 뒤 한 번 더")
        self.assertFalse(window.state.keys.reloading or window.state.keys.reload_wanted)
        self.assertTrue(self.rows(window, "image_provider")[0].buttons["delete"].isEnabled())

    def test_a_failure_is_shown_as_an_easy_sentence_with_an_icon_and_the_page_stays_usable(self):
        provider = Gated()
        window = self.make(provider)
        row = self.rows(window, "image_provider")[0]
        with mock.patch.object(provider, "set_key_state", side_effect=keys.make_failure("io", "FILE_WRITE_FAILED")):
            self.click(row.buttons["state:off"])
            self.wait_write(window)
        notices = [widget for widget in window.screen_widget.findChildren(QFrame) if widget.property("notice")]
        self.assertEqual([notice.property("notice") for notice in notices], ["error"])
        self.assertIn(T["keys_fail_io_edit"], notices[0].accessibleName())                 # 상태 바꾸기의 저장 실패 — 다시 입력할 키가 없다
        self.assertFalse(window.state.keys.busy)
        self.assertTrue(self.rows(window, "image_provider")[0].buttons["state:off"].isEnabled())

    def test_an_unexpected_exception_in_the_slot_is_an_easy_sentence_and_not_a_crash(self):
        window = self.make()
        window.state.keys.pending = {"kind": "state", "purpose": "image_provider", "ref": "x"}
        with mock.patch.object(window.state.keys, "apply_write_ok", side_effect=ValueError("내용 " + KEY)), contextlib.redirect_stderr(io.StringIO()) as err:
            window._on_keys_written(keys.KeyOutcome("state"))
        self.settle()
        self.assertEqual(window.state.keys.notice, ("error", T["keys_fail_other"]))
        self.assertEqual(leak.text_hits(err.getvalue(), NEEDLES), [])
        self.errors.clear()


class RealAdapterTest(Base):
    """실제 어댑터·서비스·임시 데이터 폴더·가짜 보관소로 화면을 끝까지 — 키는 보관소에만 있다."""

    def make_real(self, **kwargs):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.ctx = ss.make_ctx(tmp.name, clock=ss.Clock())
        self.store = self.ctx.keystore
        provider = keys_adapter.ServiceKeysProvider(None, context_factory=lambda data_dir=None: self.ctx, **kwargs)
        return provider, self.make(provider)

    def folder(self):
        root = self.ctx.workspace.root
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()} if root.exists() else {}

    def test_opening_and_looking_around_changes_nothing_on_disk_or_in_the_store(self):
        provider, window = self.make_real()
        before, refs = self.folder(), self.store.list_refs()
        for key in ("home", "blogs", "settings", "home", "settings"):
            window.go(key)
            ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading and not window.state.blogs.loading, 10)
            self.settle(3)
        window.reload_connections()
        self.wait_write(window)
        self.assertEqual((self.folder(), self.store.list_refs()), (before, refs))

    def test_a_whole_session_through_the_screen_leaves_the_key_only_in_the_store(self):
        provider, window = self.make_real()
        form = self.open_register(window, "ai_assist")
        form.alias_edit.setText("내 별칭")
        edit = form.secret_edits["key"]
        self.type_key(form)
        self.assertEqual(leak.widget_hits(window, NEEDLES, typing_into=[edit]), [])
        self.click(form.next_button)
        self.click(form.save_button)
        self.wait_write(window)
        self.assertEqual([row.name.text() for row in self.rows(window, "ai_assist")], ["내 별칭"])
        ref = self.rows(window, "ai_assist")[0].ref
        self.assertEqual(self.store.get("ai_assist:" + ref).reveal("key"), KEY)
        row = self.rows(window, "ai_assist")[0]
        self.click(row.buttons["rename"])
        window.key_rename_form.edit.setText("새 별칭")
        self.click(window.key_rename_form.ok_button)
        self.wait_write(window)
        self.click(self.rows(window, "ai_assist")[0].buttons["state:standby"])
        self.wait_write(window)
        self.assertEqual(leak.file_hits(self.ctx.workspace.root, NEEDLES), [], "데이터 폴더의 모든 파일")
        self.assertEqual(leak.widget_hits(window, NEEDLES), [])
        self.assertEqual(leak.graph_hits(window.state, NEEDLES, skip=(self, provider, self.store, self.ctx)), [])
        self.assertEqual(self.clipboard.text(), self._saved_clipboard)
        self.click(self.rows(window, "ai_assist")[0].buttons["delete"])
        self.click(self.button_with(window, "지우기"))
        self.wait_write(window)
        self.assertEqual((self.store.list_refs(), self.rows(window, "ai_assist")), ([], []))

    def test_a_failed_file_write_removes_the_key_tells_the_user_and_keeps_the_alias_for_a_new_try(self):
        provider, window = self.make_real()
        form = self.open_register(window, "ai_assist")
        form.alias_edit.setText("남는 별칭")
        self.type_key(form)
        self.click(form.next_button)
        with mock.patch.object(cn, "write_json", side_effect=AppError("DISK_FULL", {})):
            self.click(form.save_button)
            self.wait_write(window)
        self.assertEqual(self.store.list_refs(), [], "방금 넣은 키는 보관소에서 지워졌다")
        self.assertEqual(window.state.keys.notice, ("error", T["keys_fail_disk"]))
        self.assertEqual(leak.widget_hits(window, NEEDLES), [])
        self.assertEqual(leak.file_hits(self.ctx.workspace.root, NEEDLES), [])

    def test_when_even_the_cleanup_fails_the_screen_says_so_in_plain_words(self):
        provider, window = self.make_real()
        form = self.open_register(window, "ai_assist")
        self.type_key(form)
        self.click(form.next_button)

        def broken_delete(ref):
            raise AppError("KEY_STORE_UNAVAILABLE", detail="시험용 실패")
        with mock.patch.object(cn, "write_json", side_effect=AppError("FILE_WRITE_FAILED", {})), mock.patch.object(self.store, "delete", side_effect=broken_delete):
            self.click(form.save_button)
            self.wait_write(window)
        self.assertEqual(window.state.keys.notice, ("error", T["keys_fail_leftover"]))
        self.assertEqual(leak.widget_hits(window, NEEDLES), [])
        self.assertEqual(len(self.store.list_refs()), 1, "보관소에 남은 키를 숨기지 않는다")

    def test_an_entry_whose_key_is_gone_is_shown_and_can_be_deleted_again(self):
        provider, window = self.make_real()
        provider.add_key("ai_assist", "gemini", "가", self._box(KEY), False, lambda *_: None, lambda: False)
        window.reload_connections()
        self.wait_write(window)
        ref = self.rows(window, "ai_assist")[0].ref
        self.store.delete("ai_assist:" + ref)
        window.reload_connections()
        self.wait_write(window)
        row = self.rows(window, "ai_assist")[0]
        self.assertIn(T["keys_row_missing"], [label.plain_text() for label in row.lines])
        self.click(row.buttons["delete"])
        self.click(self.button_with(window, "지우기"))
        self.wait_write(window)
        self.assertEqual(self.rows(window, "ai_assist"), [])

    def test_a_delete_whose_save_fails_after_the_key_is_gone_reads_again_shows_the_row_without_a_key_and_a_second_delete_cleans_up(self):
        """독립 검증 M1 — 삭제 도중 디스크가 가득 차 파일 쓰기가 실패해도(키 저장소의 키는 이미 지워졌다) 화면은 '바뀐 것은 없어요' 라고 하지 않고 목록을 바로 다시 읽어 그 행을 '키를 찾지 못했어요' 로 보이며, 한 번 더 지우면 정리된다."""
        provider, window = self.make_real()
        provider.add_key("ai_assist", "gemini", "가", self._box(KEY), False, lambda *_: None, lambda: False)
        window.reload_connections()
        self.wait_write(window)
        row = self.rows(window, "ai_assist")[0]
        self.click(row.buttons["delete"])
        with mock.patch.object(cx, "_write_durably", side_effect=OSError(errno.ENOSPC, "디스크 가득(시험)")):
            self.click(self.button_with(window, "지우기"))
            self.wait_write(window)
        sentence = ("키를 지우다가 디스크 공간이 모자라 저장하지 못했어요. 키가 이미 지워졌을 수도 있어서 목록을 다시 읽어 드릴게요. 그 줄에 '보관소에서 이 키를 찾지 못했어요' 가 보이면 삭제를 한 번 더 눌러 정리해 주세요. "
                    "키가 그대로면 공간을 만든 뒤 다시 지워 주세요.")
        self.assertEqual(self.store.list_refs(), [], "키 저장소의 키는 이미 지워졌다")
        self.assertEqual(window.state.keys.notice, ("error", sentence))
        notices = [widget for widget in window.screen_widget.findChildren(QFrame) if widget.property("notice")]
        self.assertEqual([notice.property("notice") for notice in notices], ["error"])
        self.assertIn(sentence, notices[0].accessibleName())
        self.assertNotIn("바뀐 것은 없어요", notices[0].accessibleName())
        row = self.rows(window, "ai_assist")[0]
        self.assertIn("보관소에서 이 키를 찾지 못했어요. 지우고 다시 등록해 주세요.", [label.plain_text() for label in row.lines], "화면이 목록을 다시 읽었다")
        self.assertTrue(row.buttons["delete"].isEnabled())
        self.click(row.buttons["delete"])
        self.click(self.button_with(window, "지우기"))
        self.wait_write(window)
        self.assertEqual(self.rows(window, "ai_assist"), [])
        self.assertEqual(window.state.keys.notice, ("ok", "키를 지웠어요."))
        self.assertEqual(leak.widget_hits(window, NEEDLES), [])

    @staticmethod
    def _box(key):
        box = keys.SecretBox()
        box.put("key", key)
        return box

    def test_the_store_that_cannot_be_opened_is_a_state_and_nothing_can_be_registered(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        ctx = ss.make_ctx(tmp.name, clock=ss.Clock())
        ctx.keystore = None
        provider = keys_adapter.ServiceKeysProvider(None, context_factory=lambda data_dir=None: ctx)
        with mock.patch.object(type(ctx), "get_keystore", mock.Mock(side_effect=AppError("KEY_STORE_UNAVAILABLE", detail="시험용 실패"))):
            window = self.make(provider)
            texts = [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]
            self.assertIn(T["keys_store_missing"], texts)
            self.assertFalse(self.register_button(window, "ai_assist").isEnabled())
            self.assertIsNone(window.key_register("ai_assist"))
            self.assertFalse(window.dialog.is_open)


class NoLeakTest(Base):
    def test_every_surface_has_no_piece_of_the_key_at_every_step_of_a_registration(self):
        stderr, stdout = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            provider = Gated("not_connected")
            window = self.make(provider)
            form = self.open_register(window, "image_provider")
            edit = form.secret_edits["access_key"]
            steps = []
            self.type_key(form)
            steps.append(("입력 중", leak.widget_hits(window, NEEDLES, typing_into=[edit])))
            self.click(form.next_button)
            steps.append(("확인 단계", leak.widget_hits(window, NEEDLES, typing_into=[edit])))
            self.click(form.save_button)
            steps.append(("저장 직후", leak.widget_hits(window, NEEDLES)))
            self.wait_write(window)
            steps.append(("결과 뒤", leak.widget_hits(window, NEEDLES)))
            steps.append(("상태 구조", leak.graph_hits(window.state, NEEDLES, skip=(self, provider))))
            steps.append(("클립보드", leak.text_hits(self.clipboard.text(), NEEDLES)))
            steps.append(("표준 출력·오류", leak.text_hits(stdout.getvalue() + stderr.getvalue(), NEEDLES)))
            steps.append(("입력 칸(저장 뒤)", leak.text_hits(edit.text() + edit.displayText(), NEEDLES)))
        for name, hits in steps:
            self.assertEqual(hits, [], name)

    def test_no_screen_text_shows_the_length_of_the_key_at_any_step(self):
        """키의 **길이**도 화면에 남지 않는다(첫째 요구 — 원문·일부·길이·모양). 길이 37(화면의 다른 숫자와 겹치지 않는 길이)의 가짜 키를 넣고 단계마다 모든 위젯의 글·툴팁·접근 이름에 `37` 이 없는지 센다.
        입력 중인 칸 자신은 뺀다 — 마스킹 칸에 글자 수만큼 점이 보이는 것은 입력하는 동안 칸 안에서만이고(이 칸의 글자는 비워진다) 저장·취소 뒤에는 없다.
        화면의 시계는 `Base.make` 가 고정한다(`FIXED_NOW` — 컴퓨터 시계를 쓰면 분이 37 일 때 상단 앱 바 시계 글 `HH:37` 에, 그리고 초가 37 일 때 진단 정보의 `time: … HH:MM:37` 에 이 시험이 걸려 우연히 실패했다, 독립 검증 M3)."""
        key = leak.make_key("c", 37)
        self.assertEqual(len(key), 37)
        number = re.compile(r"(?<![0-9])37(?![0-9])")
        window = self.make(Gated("not_connected"))
        self.assertIsInstance(window.clock, clock_rules.FixedClock, "시계를 고정하지 않으면 분이 37 일 때 앱 바 시계 글(HH:37)에, 초가 37 일 때 진단 정보의 시각 줄에 이 시험이 걸린다")
        form = self.open_register(window, "ai_assist")
        edit = form.secret_edits["key"]

        def shown(typing=None):
            found = []
            for widget in [window, *window.findChildren(QWidget)]:
                for label, value in leak.own_texts(widget):
                    if widget is typing and (label.endswith(".text") or label.endswith(".displayText")):
                        continue
                    if number.search(value):
                        found.append(f"{label}: {value[:30]}")
            return found
        self.type_key(form, key)
        self.assertEqual(shown(edit), [], "입력 중")
        self.click(form.next_button)
        self.assertEqual(shown(edit), [], "확인 단계")
        self.click(form.save_button)
        self.wait_write(window)
        self.assertEqual(shown(), [], "저장 뒤")
        self.assertEqual(leak.widget_hits(window, leak.needles(key)), [], "저장 뒤 키 조각")

    def test_own_texts_leaves_the_memory_address_of_a_property_object_out_so_a_37_in_it_never_trips_the_length_scan(self):
        """독립 검증 H2 의 원인 수정 — 위젯 동적 속성(`_q_styleSheetWidgetFont` 의 QFont)을 `repr` 로 모을 때 끝의 `at 0x…` 메모리 주소가 우연히 `37` 을 품으면(예 `…37C0`) 길이 검사에 걸려
        `test_no_screen_text_shows_the_length_of_the_key_at_any_step` 이 간헐적으로 실패했다(주소는 실행마다 다르다). 주소를 뺀 글로 모은다 — 흉내 위젯으로 결정적으로 확인한다."""
        number = re.compile(r"(?<![0-9])37(?![0-9])")

        class Pointer:
            def __repr__(self):
                return "<PySide6.QtGui.QFont(맑은 고딕,-1,14,5,400,0,0,0,0,0,0,0,0,0,0,1,,0,0) at 0x000001EB70DA37C0>"

        class Pretend:                                                                       # `own_texts` 가 읽는 칸만 가진 흉내 위젯
            def toolTip(self):
                return ""

            accessibleName = accessibleDescription = statusTip = whatsThis = windowTitle = objectName = toolTip

            def dynamicPropertyNames(self):
                return [b"_q_styleSheetWidgetFont"]

            def property(self, key):
                return Pointer()

        found = [(label, value) for label, value in leak.own_texts(Pretend()) if ".property:" in label]
        self.assertEqual(len(found), 1)
        label, value = found[0]
        self.assertTrue(label.endswith("property:_q_styleSheetWidgetFont"))
        self.assertIn("QFont(맑은 고딕", value, "글 부분은 그대로 모은다")
        self.assertNotIn(" at 0x", value)
        self.assertNotIn("37C0", value)
        self.assertIsNone(number.search(value), "주소 속의 37 이 길이 검사에 걸리지 않는다")
        self.assertIsNotNone(number.search(repr(Pointer())), "대조: 주소를 빼지 않은 글은 같은 식에 걸린다(이 시험이 잡으려는 모양)")

    def test_the_length_scan_does_see_the_clock_text_which_is_why_the_windows_here_get_a_fixed_clock(self):
        """독립 검증 M3 의 대조군 — 시계가 18:37 이면 같은 검사(모든 위젯의 글·접근 이름)가 시계에서 온 글에서 37 을 **찾아낸다**: 상단 앱 바 시계 글과 진단 정보의 `time: … 18:37:00`(초 단위라 초가 37 일 때도 걸린다).
        검사가 시계 글까지 훑는다는 증거이고, 고정 시계(`FIXED_NOW`)의 창에서는 0건이다."""
        number = re.compile(r"(?<![0-9])37(?![0-9])")

        def hits(window):
            return [(label, value) for widget in [window, *window.findChildren(QWidget)] for label, value in leak.own_texts(widget) if number.search(value)]
        fixed = self.make(Gated("not_connected"))
        self.assertEqual(hits(fixed), [])
        late = self.make(Gated("not_connected"), clock=clock_rules.FixedClock(datetime.datetime(2026, 11, 6, 18, 37)))
        found = hits(late)
        self.assertIn("Label:clock.text", [label for label, _value in found], "앱 바 시계 글")
        self.assertTrue(all("18:37" in value for _label, value in found), [label for label, _value in found])               # 걸린 글은 모두 시계 시각에서 온 것이다(앱 바 시계·진단 정보의 시각 줄)

    def test_the_log_of_a_failed_save_and_a_crashing_slot_never_has_the_key(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            provider = Gated("not_connected")
            window = self.make(provider)
            form = self.open_register(window, "image_provider")
            self.type_key(form)
            self.click(form.next_button)
            with mock.patch.object(provider, "add_key", side_effect=ValueError("내용 " + KEY)):
                self.click(form.save_button)
                self.wait_write(window)
            self.assertEqual(window.state.keys.notice, ("error", T["keys_fail_other"]))
        self.assertEqual(leak.text_hits(stderr.getvalue(), NEEDLES), [])
        self.assertEqual(leak.widget_hits(window, NEEDLES), [])
        self.assertEqual(leak.graph_hits(window.state, NEEDLES, skip=(self, provider)), [])


class SourceRulesTest(unittest.TestCase):
    PARTS = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt" / "key_parts.py"

    def test_the_key_boxes_have_no_text_signals_and_the_text_is_only_read_when_a_button_is_pressed(self):
        tree = ast.parse(self.PARTS.read_text(encoding="utf-8"))
        text = self.PARTS.read_text(encoding="utf-8")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("textChanged", "textEdited", "editingFinished", "returnPressed"):
                owner = ast.unparse(node.value)
                self.assertNotIn("secret", owner.lower(), f"{owner}.{node.attr}")
                self.assertIn(owner, ("self.alias_edit", "self.edit"), f"키 칸이 아닌 칸만(별칭) — {owner}.{node.attr}")
        self.assertNotIn("self.secret_edits[", text.split("def go_next")[0].split("class KeyDialog")[1].split("def _build_input")[0])
        for name in ("go_next", "save", "wipe"):
            self.assertIn(f"def {name}", text)

    def test_the_dialog_class_clears_nested_layouts_and_runs_its_cleanups(self):
        source = (ROOT / "src" / "chanceblog_desktop" / "ui" / "qt" / "components.py").read_text(encoding="utf-8")
        dialog = source.split("class Dialog(QFrame):")[1]
        for needle in ("def _discard", "item.layout()", "run_cleanups", "self.cleanups"):
            self.assertIn(needle, dialog)


def setUpModule():
    import capability_support
    capability_support.blogger_input_on()                    # 이 모듈의 시험은 blogger 카드를 '입력 칸 셋이 있는 대화상자' 의 예로 쓴다 — Blogger 입력을 임시로만 연다(소스 상수는 False — PCSEC1). 닫힌 모양은 아래 BloggerOffTest 가 따로 본다


def tearDownModule():
    import capability_support
    capability_support.blogger_input_off()


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class BloggerOffTest(Base):
    """PCSEC1(운영자 결정 2026-11-11 §4) — 이 빌드의 기본 모양: Blogger 카드에는 입력 칸·등록 단추·항목 줄이 없고 '받지 않아요' 안내만 있다. 다른 네 용도는 그대로다."""

    def setUp(self):
        super().setUp()
        from chanceblog_desktop import capabilities
        patcher = mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_blogger_card_has_no_register_button_no_key_rows_and_only_says_it_is_not_accepted(self):
        window = self.make()
        keyed = {str(widget.property("focus_key") or "") for widget in window.screen_widget.findChildren(QAbstractButton)}
        self.assertNotIn("key-register:blogger", keyed)
        self.assertEqual(self.rows(window, "blogger"), [])
        texts = [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]
        self.assertIn(T["blogger_off_note"], texts)
        for purpose in ("naver_apihub", "naver_searchad", "image_provider", "ai_assist"):
            self.assertIn(f"key-register:{purpose}", keyed, purpose)                        # 다른 용도의 등록 단추는 그대로

    def test_nothing_on_the_screen_asks_for_a_blogger_login_value(self):
        window = self.make()
        shown = " ".join(self.everything(window))
        for word in ("갱신용 인증 값", "클라이언트 시크릿", "refresh_token", "client_secret"):
            self.assertNotIn(word, shown, word)
        self.assertEqual([edit for edit in window.screen_widget.findChildren(QLineEdit) if "blogger" in str(edit.property("focus_key") or "")], [])

if __name__ == "__main__":
    unittest.main()
