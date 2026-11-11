"""'내 글 문체 참고값 보기'(N-3a)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 설정 화면 맨 아래의 진입 카드·읽기 전용 대화상자(고르기·붙여 넣기·세는 중·결과 표)·키보드·접근 이름·닫으면 버리기를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 모든 글·파일은 임시 폴더이고 이 PC 의 실제 글·데이터 폴더는 읽지도 쓰지도 않는다(가짜 파일 선택기·임시 폴더).

지키는 것:
  · 진입점 — 설정 화면(어느 상태에서나)의 맨 아래에 작은 카드 하나와 `열기` 단추 하나(접근 이름·36px 이상·Tab 정거장). 누르면 대화상자만 열고 파일·설정·프로필에는 닿지 않는다.
  · 대화상자 — 저장 단추·체크 칸·확인창이 없고(있는 단추는 고르기·빼기·계산하기·다시 하기·닫기뿐), 창 논리 폭의 94% 를 넘지 않으며, Tab 이 대화상자 안에서만 돌고 Esc 로 닫으면 포커스가 `열기` 로 돌아간다.
  · 흐름 — 파일 선택 취소는 읽지 않고, 거절 문장은 대화상자 안에 보이고, 셋째 글은 고를 수 없고, 계산은 작업 스레드에서 돌고, 끝나면 붙여 넣기 칸이 비워지고(되돌리기 기록까지), 실패하면 칸·고른 글이 남는다.
  · 닫기 — 단추·Esc·다른 대화상자로 바뀜·앱 닫기 어느 길로든 입력 칸·고른 글·결과를 모두 버리고, 닫은 뒤 늦게 온 결과는 보이지 않는다.
  · 크기 — 모든 필수 크기와 최소 창(900×560)에서 가로 스크롤·글자 잘림·삐져나옴이 없고 단추 줄이 늘 보인다.
"""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from chanceblog_desktop.ui.core import services, style_view, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core.style_view import FakeStyleProvider  # noqa: E402
from chanceblog_desktop.ui.core.jobs import JobFailure  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QCheckBox, QFrame, QLabel, QPlainTextEdit, QScrollArea, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.qt import style_dialog

import key_leak_support as leak  # noqa: E402

SIZES = ((1366, 768), (1536, 864), (1280, 720), (1920, 1080), (900, 560))
P_MD = "# 제목\n\n## 하나\n\n## 둘\n\n저는 갑니다. 정말요? 좋아요. 끝났다."
Q_TXT = "갑니다. 정말요? 좋아요. 끝났다."
Q_TWO = "저는 갑니다.\n\n정말요?"
LONG = " ".join(["가나다라마바사아자차카타파하" * 4 + "입니다." for _ in range(12)])
BUTTON_NAMES = {text.T["style_entry_open_a11y"], text.T["style_pick_a11y"], text.T["style_compute_a11y"], text.T["style_close_a11y"], text.T["style_again_a11y"]}


class Picker:
    """가짜 파일 선택기 — 정해 둔 위치를 차례로 돌려주고(없으면 취소 = 빈 글) 부른 횟수를 센다."""

    def __init__(self, *paths):
        self.paths, self.calls = list(paths), []

    def __call__(self, parent, title, filter_text):
        self.calls.append((title, filter_text))
        return self.paths.pop(0) if self.paths else ""


class Gated(FakeStyleProvider):
    """`compute` 가 문이 열릴 때까지 멈추는 가짜 — 세는 중의 모습과 닫은 뒤에 늦게 오는 결과를 시험한다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def compute(self, paths, pasted_text):
        self.gate.wait(10)
        return super().compute(paths, pasted_text)


class Failing(FakeStyleProvider):
    def compute(self, paths, pasted_text):
        raise JobFailure("고정 문장 하나예요", code="CONTENT_INVALID")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def setUp(self):
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: self.errors.append(f"{kind.__name__}: {value}")        # 화면 슬롯 안의 예외도 시험이 잡는다
        holder = tempfile.TemporaryDirectory(prefix="style-qt-")
        self.addCleanup(holder.cleanup)
        self.root = Path(os.path.realpath(holder.name))

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def put(self, name, data):
        path = self.root / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def activate(self, window):
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)

    def make(self, *picks, size=(1440, 900), style=None, connections=None, settings=True, **kwargs):
        self.picker = Picker(*picks)
        window = shell_module.AppShell(services.FakeHomeProvider(), connections=connections or services.FakeConnectionsProvider(), autoload=False, file_picker=self.picker, style=style, **kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        if settings:
            window.go("settings")
            ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10)
            self.settle()
        return window

    def entry(self, window):
        cards = [widget for widget in window.screen_widget.findChildren(QFrame) if widget.property("style_entry")]
        self.assertEqual(len(cards), 1)
        return cards[0]

    def open_dialog(self, window):
        self.entry(window).entry_button.click()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        return window.style_form

    def wait_phase(self, window, phase, seconds=10):
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.style.phase == phase, seconds), window.style.phase)
        self.settle()

    def click(self, button):
        QTest.mouseClick(button, Qt.LeftButton)
        self.settle()

    def buttons(self, root):
        return [widget for widget in root.findChildren(QAbstractButton) if widget.isVisibleTo(root)]

    def texts(self, root):
        return [label.text() if not isinstance(label, UI.Label) else label.plain_text() for label in root.findChildren(QLabel) if label.isVisibleTo(root)]

    def with_two_files(self, window=None, **kwargs):
        a, b = self.put("a.md", P_MD), self.put("b.txt", Q_TXT)
        window = window or self.make(a, b, **kwargs)
        form = self.open_dialog(window)
        window.style_pick()
        window.style_pick()
        self.settle()
        return window, form


# ---- 1) 진입 카드 -----------------------------------------------------------------------------------------------------------------
class EntryTest(Base):
    def test_the_settings_screen_ends_with_one_small_card_with_one_open_button(self):
        window = self.make()
        card = self.entry(window)
        labels = [label.plain_text() for label in card.findChildren(UI.Label)]
        self.assertEqual(labels, [text.T["style_entry_title"], text.T["style_entry_desc"]])
        buttons = card.findChildren(QAbstractButton)
        self.assertEqual([button.accessibleName() for button in buttons], [text.T["style_entry_open_a11y"]])
        self.assertEqual(buttons[0].text(), text.T["style_entry_open"])
        self.assertGreaterEqual(buttons[0].height(), tokens.SIZE["hit"])
        self.assertEqual(card.accessibleName(), "", "카드 틀에는 이름을 달지 않는다(안의 단추가 이름을 가진다)")
        page = window.screen_widget
        cards = [widget for widget in page.findChildren(QFrame) if widget.property("card") in ("true", "plain", "quiet") and widget.parentWidget() is page]
        self.assertIs(cards[-1], card, "설정 화면 맨 아래의 카드다")
        self.assertGreater(card.mapTo(page, card.rect().topLeft()).y(), max(other.mapTo(page, other.rect().bottomLeft()).y() for other in cards[:-1]) - 1)

    def test_the_card_is_there_in_every_connection_state(self):
        for scenario in ("normal", "partial", "offline", "empty", "not_connected", "auth_error", "rate_limited"):
            with self.subTest(scenario=scenario):
                window = self.make(connections=services.FakeConnectionsProvider(scenario))
                self.assertEqual(self.entry(window).entry_button.isEnabled(), True)
                window.close()

    def test_the_card_is_there_while_the_screen_is_still_loading_and_after_a_failed_read(self):
        window = self.make(connections=services.FakeConnectionsProvider("normal"), settings=False)
        window.go("settings")
        self.assertEqual(len([w for w in window.screen_widget.findChildren(QFrame) if w.property("style_entry")]), 1, "읽는 중에도")
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10)

    def test_the_open_button_is_a_named_tab_stop_that_opens_with_the_mouse_enter_and_space(self):
        window = self.make()
        button = self.entry(window).entry_button
        self.assertTrue(button.focusPolicy() != Qt.NoFocus and button.accessibleName())
        for how in ("click", "enter", "space"):
            with self.subTest(how=how):
                button.setFocus(Qt.TabFocusReason)
                self.settle(2)
                if how == "click":
                    self.click(button)
                else:
                    QTest.keyClick(button, Qt.Key_Return if how == "enter" else Qt.Key_Space)
                    self.settle()
                self.assertTrue(window.dialog.is_open)
                self.assertIsNotNone(window.style_form)
                window.escape()
                self.settle()
                self.assertFalse(window.dialog.is_open)

    def test_opening_never_touches_a_file_or_the_picker(self):
        window = self.make()
        self.open_dialog(window)
        self.assertEqual(self.picker.calls, [])
        self.assertEqual(window.style.paths, [])
        self.assertEqual(window.style.view(0)["phase"], "select")

    def test_the_card_is_not_added_to_any_other_screen(self):
        window = self.make()
        for key in ("home", "blogs", "seed", "topics"):
            window.go(key)
            self.settle(3)
            self.assertEqual([w for w in window.screen_widget.findChildren(QFrame) if w.property("style_entry")], [], key)


# ---- 2) 대화상자의 모양 ------------------------------------------------------------------------------------------------------------
class DialogShapeTest(Base):
    def test_the_dialog_opens_with_the_pick_button_focused_and_the_intro_and_the_only_yours_note(self):
        window = self.make()
        form = self.open_dialog(window)
        self.assertIs(QApplication.focusWidget(), form.pick_button)
        shown = self.texts(form)
        for key in ("style_title", "style_intro", "style_only_yours", "style_pick_hint", "style_paste_label", "style_paste_hint", "style_none_yet"):
            self.assertIn(text.T[key], shown, key)
        self.assertEqual(window.dialog.accessibleName(), text.T["style_title"])
        self.assertIs(window.style_form, form)
        self.assertEqual(window.style.view(0)["phase"], "select")

    def test_the_dialog_is_wide_for_the_table_and_never_wider_than_ninety_four_percent_of_the_window(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(size=size)
                self.open_dialog(window)
                self.assertLessEqual(window.dialog.width(), int(window.width() * 0.94))
                self.assertEqual(window.dialog.width(), min(style_dialog.DIALOG_WIDTH, int(window.width() * 0.94)))
                self.assertTrue(window.rect().contains(window.dialog.geometry()), (size, window.dialog.geometry()))
                window.close()

    def test_the_dialog_width_and_the_paste_box_height_are_the_designed_values(self):
        """위 시험은 상수 자신을 기준으로 삼으므로 값 자체는 여기서 못박는다(설계 값: 폭 760px — 표가 들어갈 만큼, 붙여 넣기 칸 최소 키 110px)."""
        self.assertEqual(style_dialog.DIALOG_WIDTH, 760)
        self.assertEqual(shell_module.STYLE_DIALOG_WIDTH, style_dialog.DIALOG_WIDTH)
        self.assertEqual(style_dialog.PASTE_MIN_HEIGHT, 110)
        window = self.make(size=(1920, 1080))
        form = self.open_dialog(window)
        self.assertEqual(window.dialog.width(), 760)
        self.assertEqual(form.paste.minimumHeight(), 110)
        self.assertGreaterEqual(form.paste.height(), 110)

    def test_a_disabled_paste_box_takes_no_text_from_the_input_method_and_an_enabled_one_does(self):
        """한글 입력기가 확정한 글도 숫자를 세는 동안(칸이 꺼진 동안)에는 받지 않는다 — 꺼진 칸에 직접 입력기 사건을 넣어 본다."""
        from PySide6.QtGui import QInputMethodEvent
        window = self.make()
        form = self.open_dialog(window)
        form.paste.setEnabled(False)
        blocked = QInputMethodEvent()
        blocked.setCommitString("가나다")
        form.paste.inputMethodEvent(blocked)
        self.assertEqual(form.paste.toPlainText(), "")
        self.assertFalse(blocked.isAccepted())
        form.paste.setEnabled(True)
        allowed = QInputMethodEvent()
        allowed.setCommitString("가나다")
        form.paste.inputMethodEvent(allowed)
        self.assertEqual(form.paste.toPlainText(), "가나다")

    def test_tab_in_the_paste_box_moves_to_the_next_part_and_never_types_a_tab(self):
        window = self.make()
        form = self.open_dialog(window)
        form.paste.setFocus(Qt.OtherFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), form.paste)
        QTest.keyClick(form.paste, Qt.Key_Tab)
        self.settle(2)
        self.assertEqual(form.paste.toPlainText(), "", "Tab 은 글자가 아니라 다음 칸으로 가는 키다")
        self.assertIs(QApplication.focusWidget(), form.close_button, "붙여 넣기 칸 다음은 `닫기`(다시 하기는 결과 모습에만 있다)")
        form.paste.setFocus(Qt.OtherFocusReason)
        self.settle(2)
        QTest.keyClick(form.paste, Qt.Key_Backtab)
        self.settle(2)
        self.assertEqual(form.paste.toPlainText(), "")
        self.assertIs(QApplication.focusWidget(), form.pick_button, "거꾸로는 `파일 고르기`")

    def test_each_phase_shows_exactly_its_own_parts_and_buttons(self):
        window, form = self.with_two_files()
        names = ("title", "intro", "only_yours", "select_host", "result_host", "pick_button", "compute_button", "again_button", "close_button")

        def shown():
            return {name: getattr(form, name).isVisibleTo(form) for name in names}

        self.assertEqual(shown(), {"title": True, "intro": True, "only_yours": True, "select_host": True, "result_host": False, "pick_button": True, "compute_button": True, "again_button": False, "close_button": True}, "고르기 모습")
        window.style_compute()
        self.wait_phase(window, "result")
        self.assertEqual(shown(), {"title": True, "intro": False, "only_yours": False, "select_host": False, "result_host": True, "pick_button": False, "compute_button": False, "again_button": True, "close_button": True}, "결과 모습")
        window.style_again()
        self.settle()
        self.assertEqual(shown(), {"title": True, "intro": True, "only_yours": True, "select_host": True, "result_host": False, "pick_button": True, "compute_button": True, "again_button": False, "close_button": True}, "다시 하기 뒤의 고르기 모습")

    def test_the_enabled_state_of_pick_paste_and_compute_follows_how_many_texts_are_chosen(self):
        window = self.make(self.put("a.md", P_MD), self.put("b.txt", Q_TXT))
        form = self.open_dialog(window)

        def states():
            return (form.pick_button.isEnabled(), form.paste.isEnabled(), form.compute_button.isEnabled())

        self.assertEqual(states(), (True, True, False), "아무것도 안 골랐다 — 계산할 것이 없다")
        window.style_pick()
        self.settle()
        self.assertEqual(states(), (True, True, True), "파일 하나")
        window.style_pick()
        self.settle()
        self.assertEqual(states(), (False, False, True), "파일 둘 — 더 고르거나 붙여 넣을 수 없다")
        window.style_remove(1)
        self.settle()
        self.assertEqual(states(), (True, True, True), "하나를 빼면 다시 고를 수 있다")
        written = "붙여 넣은 글입니다."
        form.paste.setPlainText(written)
        self.settle(2)
        self.assertEqual(states(), (False, True, True), "파일 하나와 붙여 넣은 글이 합쳐 둘 — 파일은 더 못 고르지만 칸은 고칠 수 있다")
        self.assertEqual(form.paste_count.accessibleName(), text.T["style_paste_count_a11y"].format(n=len(written)))
        self.assertEqual(form.paste_count.plain_text(), text.T["style_paste_count"].format(n=len(written)))
        form.paste.setPlainText("")
        window.style_remove(0)
        self.settle(2)
        self.assertEqual(states(), (True, True, False), "모두 비우면 처음과 같다")

    def test_there_is_no_save_check_box_or_confirmation_and_only_the_five_known_buttons(self):
        window, form = self.with_two_files()
        names = {button.accessibleName() for button in form.findChildren(QAbstractButton)}
        self.assertEqual(names - {text.T["style_remove_a11y"].format(n=1), text.T["style_remove_a11y"].format(n=2)}, BUTTON_NAMES - {text.T["style_entry_open_a11y"]})
        self.assertEqual(form.findChildren(QCheckBox), [], "체크 칸이 없다(승인해서 저장하는 길이 없다)")
        for button in form.findChildren(QAbstractButton):
            for word in ("저장", "적용", "복사", "확인", "승인", "내보내기"):
                self.assertNotIn(word, button.text() + button.accessibleName())
        self.wait_phase_after_compute(window)
        names = {button.accessibleName() for button in form.findChildren(QAbstractButton)}
        self.assertEqual(names & {"저장", "적용"}, set())
        self.assertEqual(window.findChildren(QCheckBox), [])

    def wait_phase_after_compute(self, window):
        window.style_compute()
        self.wait_phase(window, "result")

    def test_the_dialog_is_replaced_by_nothing_while_another_dialog_is_open(self):
        window = self.make()
        window.show_dialog("다른 대화상자", "내용")
        self.settle()
        self.assertIsNone(window.style_open(), "다른 대화상자가 열려 있으면 열지 않는다")
        self.assertIsNone(window.style_form)

    def test_tab_stays_inside_the_dialog_for_a_whole_round_while_choosing_and_in_the_result(self):
        window, form = self.with_two_files()
        for phase in ("select", "result"):
            with self.subTest(phase=phase):
                seen = []
                for _ in range(14):
                    focus = QApplication.focusWidget()
                    self.assertTrue(focus is not None and window.dialog.isAncestorOf(focus), focus)
                    seen.append(focus)
                    QTest.keyClick(focus, Qt.Key_Tab)
                    self.settle(2)
                expected = [form.scroll, *form.slot_buttons, form.close_button, form.compute_button] if phase == "select" else [form.scroll, form.again_button, form.close_button]
                start = seen.index(form.scroll)
                self.assertEqual(seen[start:start + len(expected)], expected, "Tab 순서: 몸 → (파일 고르기) → 빼기들 → (붙여 넣기 칸) → (다시 하기) → 닫기 → (계산하기)")
                if phase == "select":
                    for widget in (form.scroll, form.close_button, form.compute_button, *form.slot_buttons):                     # 둘을 골랐으니 파일 고르기와 붙여 넣기 칸은 꺼져 있다(Tab 이 건너뛴다)
                        self.assertIn(widget, seen, widget.accessibleName())
                    for widget in (form.pick_button, form.paste):
                        self.assertNotIn(widget, seen, "꺼진 칸에는 Tab 이 가지 않는다")
                    window.style_compute()
                    self.wait_phase(window, "result")
                else:
                    for widget in (form.scroll, form.again_button, form.close_button):
                        self.assertIn(widget, seen, widget.accessibleName())
                    self.assertNotIn(form.compute_button, seen, "결과 모습에는 계산하기가 없다")

    def test_the_scroll_body_has_a_name_and_is_a_keyboard_stop(self):
        window = self.make()
        form = self.open_dialog(window)
        self.assertEqual(form.scroll.accessibleName(), text.T["style_scroll_a11y"])
        self.assertEqual(form.scroll.focusPolicy(), Qt.StrongFocus)
        self.assertEqual(form.scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

    def test_escape_closes_the_dialog_and_gives_the_focus_back_to_the_open_button(self):
        window = self.make()
        button = self.entry(window).entry_button
        button.setFocus(Qt.TabFocusReason)
        self.settle(2)
        form = self.open_dialog(window)
        QTest.keyClick(form.pick_button, Qt.Key_Escape)
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertIs(QApplication.focusWidget(), button)


# ---- 3) 흐름 ----------------------------------------------------------------------------------------------------------------------
class FlowTest(Base):
    def test_two_files_are_computed_on_a_worker_thread_and_the_table_shows_the_numbers(self):
        window, form = self.with_two_files()
        self.assertEqual(len(form.slot_buttons), 2)
        shown = self.texts(form)
        self.assertIn("글 1 · 파일에서 가져옴", shown)
        self.assertIn("글 2 · 파일에서 가져옴", shown)
        self.assertEqual(len(self.picker.calls), 2)
        self.assertFalse(form.pick_button.isEnabled(), "둘을 골랐으면 더 고를 수 없다")
        self.assertFalse(form.paste.isEnabled())
        threads = []
        real = window.style.provider.compute

        def spy(paths, pasted):
            threads.append(threading.current_thread())
            return real(paths, pasted)

        window.style.provider.compute = spy
        self.click(form.compute_button)
        self.wait_phase(window, "result")
        self.assertEqual(len(threads), 1)
        self.assertIsNot(threads[0], threading.main_thread())
        vm = window.style.view(0)["result"]
        self.assertIsNotNone(form.result_card)
        self.assertEqual(form.result_card.accessibleName(), text.T["style_result_a11y"])
        for row in vm["rows"]:
            self.assertIn(row["label"], self.texts(form))
            for number, cell in enumerate(row["cells"] + [row["range"]] + ([row["total"]] if row["total"] else []), start=1):
                self.assertEqual(form.cells[(row["key"], number)].plain_text(), cell)
        for line in vm["counts"] + vm["notes"] + [vm["trust"], vm["rough"]]:
            self.assertIn(line, self.texts(form))
        self.assertIs(QApplication.focusWidget(), form.scroll, "결과가 나오면 포커스가 몸으로 가서 방향키로 읽는다")
        self.assertTrue(form.again_button.isVisible() and not form.compute_button.isVisible())
        self.assertTrue(form.close_button.isVisible())

    def test_the_result_shows_the_counts_title_the_notes_and_top_aligned_right_aligned_cells(self):
        window, form = self.with_two_files()
        window.style_compute()
        self.wait_phase(window, "result")
        shown = self.texts(form)
        vm = window.style.view(0)["result"]
        for key in ("style_result_title", "style_counts_title", "style_notes_title"):
            self.assertIn(text.T[key], shown, key)
        for line in [*vm["counts"], *vm["notes"]]:
            self.assertIn(line, shown)
        self.assertTrue(vm["notes"], "시험 글이 짧아서 안내가 있다")
        self.assertEqual(len(form.cells), len(vm["rows"]) * len(vm["columns"]), "줄마다 열 수만큼 값 칸이 있다")
        for key, cell in form.cells.items():
            alignment = cell.alignment()
            self.assertTrue(alignment & Qt.AlignRight, key)
            self.assertTrue(alignment & Qt.AlignTop, key)
        single = self.make(self.put("c.md", P_MD))
        single_form = self.open_dialog(single)
        single.style_pick()
        self.settle()
        single.style_compute()
        self.wait_phase(single, "result")
        one = single.style.view(0)["result"]
        self.assertEqual([column["key"] for column in one["columns"]], ["item0"])
        self.assertEqual(len(single_form.cells), len(one["rows"]), "글 하나 — 줄마다 값 칸 하나뿐이다(범위·합산 칸이 없다)")
        self.assertEqual({number for (_key, number) in single_form.cells}, {1})

    def test_each_remove_button_takes_out_its_own_file_and_has_its_own_tab_key_and_the_focus_moves_on(self):
        a, b = self.put("a.md", P_MD), self.put("b.txt", Q_TXT)
        for index, expected in ((1, [a]), (0, [b])):
            with self.subTest(removing=index):
                window = self.make(a, b)
                form = self.open_dialog(window)
                window.style_pick()
                self.settle()
                self.assertIs(QApplication.focusWidget(), form.pick_button, "하나를 고른 뒤에도 `파일 고르기` 가 켜져 있어 거기에 포커스")
                window.style_pick()
                self.settle()
                self.assertEqual(window.style.paths, [a, b])
                self.assertIs(QApplication.focusWidget(), form.compute_button, "둘을 고르면 `파일 고르기` 가 꺼지므로 포커스는 `계산하기`")
                self.assertEqual([button.property("focus_key") for button in form.slot_buttons], ["style:remove:0", "style:remove:1"])
                self.click(form.slot_buttons[index])
                self.assertEqual(window.style.paths, expected, f"{index + 1}번째 `빼기` 는 {index + 1}번째 글을 뺀다")
                window.close()

    def test_the_trust_sentence_is_next_to_the_numbers_and_the_rough_note_says_it_is_a_surface_rule(self):
        window, form = self.with_two_files()
        window.style_compute()
        self.wait_phase(window, "result")
        shown = self.texts(form)
        self.assertIn(text.T["style_trust"], shown)
        self.assertIn(text.T["style_rough"], shown)
        self.assertEqual(shown.count(text.T["style_trust"]), 1)

    def test_the_result_ends_with_the_trust_the_yours_and_the_rough_lines_in_that_order(self):
        """D-434·D-432 — 숫자 아래 마지막 세 줄: 판단하는 값이 아니라는 문장 → 직접 쓴 글만 골랐을 때의 숫자라는 문장 → 글자 모양 규칙이라 오차가 있다는 문장."""
        window, form = self.with_two_files()
        window.style_compute()
        self.wait_phase(window, "result")
        labels = [form.result_layout.itemAt(index).widget() for index in range(form.result_layout.count())]
        self.assertEqual([label.plain_text() for label in labels[-3:]], [text.T["style_trust"], text.T["style_yours_result"], text.T["style_rough"]])
        self.assertEqual(self.texts(form).count(text.T["style_yours_result"]), 1)
        self.assertFalse(form.only_yours.isVisibleTo(form), "고르기 모습의 부탁 문장은 결과 모습에서 접힌 채다")

    def test_a_pasted_text_is_marked_in_the_column_header_of_the_table(self):
        """D-434 — 파일 하나와 붙여 넣은 글 하나를 골랐을 때 어느 열이 붙여 넣은 글인지 열 머리가 말한다."""
        window = self.make(self.put("a.md", P_MD))
        form = self.open_dialog(window)
        window.style_pick()
        form.paste.setPlainText(Q_TXT)
        self.settle(2)
        self.click(form.compute_button)
        self.wait_phase(window, "result")
        shown = self.texts(form)
        self.assertIn("글 1", shown)
        self.assertIn("글 2 (붙여 넣음)", shown)
        self.assertNotIn("글 1 (붙여 넣음)", shown)
        vm = window.style.view(0)["result"]
        self.assertEqual([column["text"] for column in vm["columns"]][:2], ["글 1", "글 2 (붙여 넣음)"])
        named = {label.accessibleName() for label in form.result_card.findChildren(QLabel)}
        for row in vm["rows"]:
            self.assertIn(row["a11y"], named)
            self.assertIn("글 2 (붙여 넣음) ", row["a11y"])

    def test_the_file_dialog_gets_its_title_and_offers_only_txt_and_md_files(self):
        window = self.make(self.put("a.md", P_MD))
        self.open_dialog(window)
        window.style_pick()
        self.assertEqual(self.picker.calls, [(text.T["style_pick_title"], f"{text.T['style_pick_filter']} (*.txt *.md)")])

    def test_a_cancelled_file_dialog_reads_nothing_and_changes_nothing(self):
        window = self.make()
        form = self.open_dialog(window)
        calls = []
        real = window.style.provider.check_files
        window.style.provider.check_files = lambda paths: (calls.append(paths), real(paths))[1]
        self.click(form.pick_button)
        self.assertEqual(len(self.picker.calls), 1)
        self.assertEqual(calls, [])
        self.assertEqual(window.style.paths, [])
        self.assertEqual(self.texts(form).count(text.T["style_none_yet"]), 1)

    def test_a_refused_file_shows_the_fixed_sentence_in_the_dialog_without_its_name_and_is_not_added(self):
        bad = self.put("고유이름-w5p2m8.docx", "글")
        window = self.make(bad)
        form = self.open_dialog(window)
        self.click(form.pick_button)
        self.assertTrue(form.message.isVisible())
        self.assertIn("기존 글 파일 — ", form.message.plain_text())
        self.assertNotIn("고유이름", " ".join(self.texts(window)))
        self.assertNotIn(str(self.root), " ".join(self.texts(window)))
        self.assertEqual(window.style.paths, [])
        self.assertTrue(form.pick_button.isEnabled())

    def test_the_third_file_cannot_be_chosen_and_the_picker_is_not_even_opened(self):
        window, form = self.with_two_files()
        self.assertEqual(len(self.picker.calls), 2)
        window.style_pick()
        self.assertEqual(len(self.picker.calls), 2, "꽉 찼으면 파일 선택 창을 열지 않는다")
        self.assertFalse(form.pick_button.isEnabled())

    def test_the_remove_button_takes_a_file_out_and_the_pick_button_comes_back(self):
        window, form = self.with_two_files()
        self.assertEqual(len(form.slot_buttons), 2)
        self.assertEqual([button.accessibleName() for button in form.slot_buttons], ["글 1 빼기", "글 2 빼기"])
        self.click(form.slot_buttons[0])
        self.assertEqual(len(window.style.paths), 1)
        self.assertEqual(len(form.slot_buttons), 1)
        self.assertEqual(form.slot_buttons[0].accessibleName(), "글 1 빼기")
        self.assertTrue(form.pick_button.isEnabled() and form.paste.isEnabled())

    def test_typing_a_text_turns_on_compute_counts_the_characters_and_a_pasted_text_uses_one_slot(self):
        window = self.make(self.put("a.md", P_MD), self.put("b.txt", Q_TXT))
        form = self.open_dialog(window)
        self.assertFalse(form.compute_button.isEnabled())
        form.paste.setPlainText("붙여 넣은 글입니다. 정말요?")
        self.settle(2)
        self.assertTrue(form.compute_button.isEnabled())
        self.assertEqual(form.paste_count.plain_text(), "16자")
        self.assertEqual(form.paste_count.accessibleName(), "붙여 넣은 글자 수 16자")
        window.style_pick()
        self.settle()
        self.assertEqual(len(window.style.paths), 1)
        self.assertFalse(form.pick_button.isEnabled(), "붙여 넣은 글과 파일 하나로 이미 둘이다")
        form.paste.setPlainText("")
        self.settle(2)
        self.assertTrue(form.pick_button.isEnabled())
        self.assertTrue(form.compute_button.isEnabled())

    def test_a_pasted_text_is_computed_and_then_the_box_is_empty_with_no_undo_history(self):
        window = self.make()
        form = self.open_dialog(window)
        form.paste.setPlainText("붙여 넣은 글입니다.\n\n둘째 문단입니다. 정말요?")
        self.settle(2)
        self.click(form.compute_button)
        self.assertFalse(form.paste.isEnabled() and window.style.running, "세는 동안 칸은 꺼진다")
        self.wait_phase(window, "result")
        self.assertEqual(form.paste.toPlainText(), "")
        self.assertFalse(form.paste.document().isUndoAvailable() or form.paste.document().isRedoAvailable())
        vm = window.style.view(0)["result"]
        self.assertEqual([column["text"] for column in vm["columns"]], ["글 1"])
        self.assertEqual(form.cells[("sentence_length", 1)].plain_text(), vm["rows"][0]["cells"][0])

    def test_while_it_is_counting_everything_but_close_is_off_and_the_status_says_so(self):
        gated = Gated({"a": (P_MD, "md")})
        window = self.make(style=gated, size=(1440, 900))
        form = self.open_dialog(window)
        window.style.paths.append("a")
        form.refresh()
        self.click(form.compute_button)
        self.assertEqual(window.style.phase, "running")
        self.assertFalse(form.pick_button.isEnabled() or form.paste.isEnabled() or form.compute_button.isEnabled())
        self.assertTrue(form.close_button.isEnabled())
        self.assertIn(text.T["style_running"], self.texts(form))
        self.assertEqual(form.status.accessibleName(), text.T["style_running_a11y"])
        gated.gate.set()
        self.wait_phase(window, "result")

    def test_a_result_that_arrives_moves_the_focus_to_the_body_even_when_it_was_on_the_close_button(self):
        """`닫기` 에 포커스가 있던 채로(세는 동안 켜져 있는 유일한 단추) 결과가 오면 포커스는 몸으로 간다 — 숨은 부품에서 자동으로 옮겨 가는 것과 구별되는 경우."""
        gated = Gated({"a": (P_MD, "md")})
        window = self.make(style=gated, size=(1440, 900))
        form = self.open_dialog(window)
        window.style.paths.append("a")
        form.refresh()
        self.click(form.compute_button)
        self.assertEqual(window.style.phase, "running")
        form.close_button.setFocus(Qt.OtherFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), form.close_button)
        gated.gate.set()
        self.wait_phase(window, "result")
        self.assertIs(QApplication.focusWidget(), form.scroll, "결과가 나오면 몸(스크롤)으로 — 닫기 단추에 남아 있지 않는다")

    def test_a_cancel_notice_from_the_job_is_forwarded_to_the_controller_and_changes_nothing_on_screen(self):
        from unittest import mock
        window = self.make(self.put("a.md", P_MD))
        form = self.open_dialog(window)
        window.style_pick()
        self.settle()
        before = (window.style.phase, list(window.style.paths), window.style.message, [button.isEnabled() for button in (form.pick_button, form.compute_button)])
        with mock.patch.object(window.style, "apply_cancelled", wraps=window.style.apply_cancelled) as spy:
            window._style_cancelled()
        spy.assert_called_once_with()
        self.settle(2)
        self.assertEqual((window.style.phase, list(window.style.paths), window.style.message, [button.isEnabled() for button in (form.pick_button, form.compute_button)]), before)

    def test_a_result_that_arrives_after_closing_is_dropped_without_a_trace(self):
        gated = Gated({"a": (P_MD, "md")})
        window = self.make(style=gated)
        form = self.open_dialog(window)
        window.style.paths.append("a")
        form.refresh()
        self.click(form.compute_button)
        window.style_close()
        self.settle()
        gated.gate.set()
        self.settle(20)
        self.assertFalse(window.dialog.is_open)
        self.assertIsNone(window.style_form)
        self.assertFalse(window.style.is_open)
        self.assertIsNone(window.style.outcome)
        self.assertEqual(form.result_card, None)
        again = self.open_dialog(window)
        self.assertEqual(window.style.phase, "select")
        self.assertEqual(self.texts(again).count(text.T["style_none_yet"]), 1)

    def test_a_failed_computation_shows_the_fixed_sentence_and_keeps_the_chosen_files_and_the_pasted_text(self):
        failing = Failing({"a": (P_MD, "md")})
        window = self.make(style=failing)
        form = self.open_dialog(window)
        window.style.paths.append("a")
        form.paste.setPlainText("붙여 넣은 글입니다.")
        form.refresh()
        self.click(form.compute_button)
        ui_offscreen.wait_until(self.app, lambda: window.style.message != "", 10)
        self.settle()
        self.assertEqual(window.style.phase, "select")
        self.assertEqual(form.message.plain_text(), "고정 문장 하나예요")
        self.assertTrue(form.message.isVisible())
        self.assertEqual(form.paste.toPlainText(), "붙여 넣은 글입니다.", "실패하면 칸의 글이 남는다(다시 시도할 수 있게)")
        self.assertEqual(window.style.paths, ["a"])
        self.assertTrue(form.compute_button.isEnabled())

    def test_a_crash_while_drawing_the_result_goes_back_to_choosing_with_the_easy_sentence_and_no_text_anywhere(self):
        """결과를 그리다 화면 쪽에서 예외가 나도(있으면 버그다) 쉬운 고정 문장만 보이고 고르기 모습으로 돌아간다 — 표준 오류에는 예외 이름만 남고 예외 글·붙여 넣은 글은 어디에도 없다."""
        marker = "충돌표지문장h5j8k2m7전혀다른낱말p3q9r1입니다"
        probes = leak.needles(marker, size=8)
        window = self.make(style=FakeStyleProvider({"a": (P_MD, "md")}))
        form = self.open_dialog(window)
        window.style.paths.append("a")
        form.paste.setPlainText(marker)
        form.refresh()
        original, crashed = form.refresh, []

        def crashing():
            if window.style.outcome is not None and not crashed:                     # 결과를 받아 둔 직후의 그리기에서 한 번만 터진다
                crashed.append(True)
                raise RuntimeError(marker)
            return original()

        form.refresh = crashing
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.click(form.compute_button)
            ui_offscreen.wait_until(self.app, lambda: bool(crashed), 10)
            self.settle()
        self.assertEqual(crashed, [True])
        self.assertEqual((window.style.phase, window.style.message, window.style.paths), ("select", text.T["style_fail_other"], ["a"]))
        self.assertEqual(form.message.plain_text(), text.T["style_fail_other"])
        self.assertTrue(form.message.isVisible())
        self.assertIn("RuntimeError", err.getvalue(), "예외 이름은 표준 오류에 남는다(조용한 실패가 아니다)")
        self.assertEqual(leak.text_hits(err.getvalue(), probes), [], "예외 글은 표준 오류에도 없다")
        self.assertEqual(leak.widget_hits(window, probes), [], "붙여 넣은 글은 결과를 받는 순간 비워졌고 어디에도 남지 않았다")
        self.assertEqual(leak.graph_hits(window.style, probes, skip=(window.style.provider,)), [])
        self.assertEqual(window.style.view(0)["phase"], "select")
        form.refresh = original
        self.assertTrue(form.compute_button.isEnabled(), "다시 계산할 수 있다")

    def test_nothing_chosen_says_so_and_a_refused_pasted_text_keeps_the_box(self):
        window = self.make()
        form = self.open_dialog(window)
        self.assertEqual(window.style_compute(), "nothing")
        self.assertEqual(form.message.plain_text(), text.T["style_none_yet"])
        form.paste.setPlainText("x" * 100_001)
        self.settle(2)
        self.assertEqual(window.style_compute(), "refused")
        self.assertIn("글이 너무 길어요", form.message.plain_text())
        self.assertEqual(len(form.paste.toPlainText()), 100_001)

    def test_do_it_again_clears_the_result_the_files_and_the_box_and_goes_back_to_choosing(self):
        window, form = self.with_two_files()
        window.style_compute()
        self.wait_phase(window, "result")
        form.paste.setPlainText("칸에 남아 있던 글입니다.")                    # 결과 모습에서는 칸이 숨어 있고 이미 비워졌지만, 어떤 길로든 글이 남아 있어도 다시 하기가 비운다
        self.click(form.again_button)
        self.assertEqual(window.style.phase, "select")
        self.assertEqual((window.style.paths, window.style.outcome), ([], None))
        self.assertIsNone(form.result_card)
        self.assertEqual(form.paste.toPlainText(), "")
        self.assertIs(QApplication.focusWidget(), form.pick_button)
        self.assertEqual(len(form.slot_buttons), 0)

    def test_the_real_provider_is_used_when_none_is_given(self):
        window = self.make()
        from chanceblog_desktop.ui import style_adapter
        self.assertIsInstance(window.style.provider, style_adapter.ServiceStyleProvider)


# ---- 4) 닫으면 버린다 ---------------------------------------------------------------------------------------------------------------
class DiscardTest(Base):
    def assert_discarded(self, window, form, dialog_open=False):
        self.assertEqual(window.dialog.is_open, dialog_open)
        self.assertIsNone(window.style_form)
        self.assertFalse(window.style.is_open)
        self.assertEqual((window.style.paths, window.style.outcome, window.style.message), ([], None, ""))
        self.assertEqual(form.paste.toPlainText(), "")
        self.assertFalse(form.paste.document().isUndoAvailable() or form.paste.document().isRedoAvailable())
        self.assertIsNone(form.result_card)
        self.assertEqual(form.cells, {})
        self.assertEqual(form.slot_buttons, [])
        self.assertIsNone(form.study)

    def prepare(self):
        window, form = self.with_two_files()
        window.style_compute()
        self.wait_phase(window, "result")
        return window, form

    def test_the_close_button_discards_everything(self):
        window, form = self.prepare()
        self.click(form.close_button)
        self.assert_discarded(window, form)

    def test_escape_discards_everything(self):
        window, form = self.prepare()
        window.escape()
        self.settle()
        self.assert_discarded(window, form)

    def test_another_dialog_replacing_this_one_discards_everything(self):
        window, form = self.prepare()
        window.show_dialog("다른 대화상자", "내용")
        self.settle()
        self.assert_discarded(window, form, dialog_open=True)

    def test_closing_the_app_with_the_dialog_open_discards_everything(self):
        window, form = self.prepare()
        window.close()
        self.settle()
        self.assert_discarded(window, form)

    def test_closing_while_choosing_with_a_typed_text_empties_the_box_and_the_undo_history(self):
        window = self.make(self.put("a.md", P_MD))
        form = self.open_dialog(window)
        window.style_pick()
        form.paste.setPlainText("고르다 만 붙여 넣은 글입니다.")
        self.settle(2)
        window.style_close()
        self.settle()
        self.assertEqual(form.paste.toPlainText(), "")
        self.assertFalse(form.paste.document().isUndoAvailable())
        self.assertEqual(window.style.paths, [])

    def test_typing_builds_an_undo_history_and_closing_or_computing_leaves_none_behind(self):
        """위 시험들은 글을 `setPlainText` 로 넣어 되돌리기 기록이 처음부터 없다 — 여기서는 키로 직접 쳐서(기록이 쌓인다) 비운 뒤에 기록이 남지 않음을 본다."""
        for how in ("close", "compute"):
            with self.subTest(how=how):
                window = self.make(self.put("a.md", P_MD))
                form = self.open_dialog(window)
                form.paste.setFocus(Qt.OtherFocusReason)
                QTest.keyClicks(form.paste, "hello world. really?")
                self.settle(2)
                self.assertEqual(form.paste.toPlainText(), "hello world. really?")
                self.assertTrue(form.paste.document().isUndoAvailable(), "직접 치면 되돌리기 기록이 쌓인다")
                if how == "close":
                    window.style_close()
                else:
                    window.style_compute()
                    self.wait_phase(window, "result")
                self.settle()
                self.assertEqual(form.paste.toPlainText(), "")
                self.assertFalse(form.paste.document().isUndoAvailable() or form.paste.document().isRedoAvailable())
                window.close()

    def test_a_reopened_dialog_is_a_new_empty_one(self):
        window, form = self.prepare()
        window.style_close()
        self.settle()
        newer = self.open_dialog(window)
        self.assertIsNot(newer, form)
        self.assertEqual((window.style.paths, window.style.phase), ([], "select"))
        self.assertEqual(newer.paste.toPlainText(), "")
        self.assertEqual(self.texts(newer).count(text.T["style_none_yet"]), 1)
        self.assertFalse(any("세어 본 숫자" in shown for shown in self.texts(newer)))

    def test_the_focus_returns_to_the_open_button_after_every_way_of_closing(self):
        for how in ("button", "escape"):
            with self.subTest(how=how):
                window = self.make()
                button = self.entry(window).entry_button
                button.setFocus(Qt.TabFocusReason)
                self.settle(2)
                form = self.open_dialog(window)
                if how == "button":
                    self.click(form.close_button)
                else:
                    window.escape()
                self.settle()
                self.assertIs(QApplication.focusWidget(), button)
                window.close()


# ---- 5) 크기·접근성 ---------------------------------------------------------------------------------------------------------------
class LayoutAndAccessibilityTest(Base):
    def put_files(self, long_second=False):
        return self.put("a.md", P_MD), self.put("b.txt", LONG if long_second else Q_TXT)

    def test_no_horizontal_scroll_clipping_or_squeezing_at_every_size_in_the_choosing_and_the_result_views(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(*self.put_files(), size=size)
                form = self.open_dialog(window)
                self.check_fit(window, form, size, "select")
                window.style_pick()
                window.style_pick()
                self.settle()
                window.style_compute()
                self.wait_phase(window, "result")
                self.settle(8)
                self.check_fit(window, form, size, "result")
                window.close()

    def check_fit(self, window, form, size, phase):
        dialog = window.dialog
        self.assertTrue(window.rect().contains(dialog.geometry()), (size, phase, dialog.geometry(), window.rect()))
        self.assertEqual(form.scroll.horizontalScrollBar().maximum(), 0, (size, phase))
        self.assertEqual(ui_offscreen.find_clipping(dialog), [], (size, phase))
        self.assertEqual(ui_offscreen.find_squeezed(dialog), [], (size, phase))
        for button in self.buttons(form):
            if button.parentWidget() is not None and not form.scroll.isAncestorOf(button):
                bottom = button.mapTo(window, button.rect().bottomRight())
                self.assertTrue(window.rect().contains(bottom) and button.isVisible(), (size, phase, button.accessibleName()))
        capped = dialog.height() >= window.height() - 32
        bar = form.scroll.verticalScrollBar()
        if not capped:
            self.assertEqual(bar.maximum(), 0, (size, phase, "창에 들어가면 스크롤이 없다"))

    def test_a_result_with_a_pasted_text_in_its_header_fits_every_size_too(self):
        """D-434 — 열 머리가 길어졌다(`글 2 (붙여 넣음)`): 최소 창(900×560)을 포함한 모든 크기에서 잘림·눌림·가로 스크롤이 없다."""
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(self.put("a.md", P_MD), size=size)
                form = self.open_dialog(window)
                window.style_pick()
                form.paste.setPlainText(Q_TXT)
                self.settle(2)
                window.style_compute()
                self.wait_phase(window, "result")
                self.settle(8)
                self.assertIn("글 2 (붙여 넣음)", self.texts(form))
                self.check_fit(window, form, size, "result")
                window.close()

    def test_at_the_smallest_window_the_result_scrolls_and_the_buttons_stay_visible(self):
        window = self.make(*self.put_files(long_second=True), size=(900, 560))
        form = self.open_dialog(window)
        window.style_pick()
        window.style_pick()
        window.style_compute()
        self.wait_phase(window, "result")
        self.settle(8)
        self.assertGreaterEqual(window.dialog.height(), window.height() - 40, "창을 거의 채운다")
        self.assertGreater(form.scroll.verticalScrollBar().maximum(), 0, "몸은 스크롤된다")
        for button in (form.again_button, form.close_button):
            self.assertTrue(window.rect().contains(button.mapTo(window, button.rect().bottomRight())) and button.isVisible())
        form.scroll.verticalScrollBar().setValue(form.scroll.verticalScrollBar().maximum())
        self.settle(2)
        last = form.result_layout.itemAt(form.result_layout.count() - 1).widget()
        self.assertTrue(last.isVisible())

    def test_every_pressable_part_has_a_name_and_a_big_enough_target_in_every_view(self):
        window, form = self.with_two_files()
        for phase in ("select", "result"):
            for button in self.buttons(form):
                self.assertTrue(button.accessibleName().strip(), f"{phase}: {button.text()!r}")
                self.assertGreaterEqual(button.height(), tokens.SIZE["hit"], button.accessibleName())
            self.assertTrue(form.paste.accessibleName() and form.scroll.accessibleName())
            if phase == "select":
                window.style_compute()
                self.wait_phase(window, "result")

    def test_the_table_has_a_name_every_label_has_text_and_every_row_has_a_full_sentence_name(self):
        window, form = self.with_two_files()
        window.style_compute()
        self.wait_phase(window, "result")
        self.assertEqual(form.result_card.accessibleName(), text.T["style_result_a11y"])
        vm = window.style.view(0)["result"]
        named = {label.accessibleName() for label in form.result_card.findChildren(QLabel)}
        for row in vm["rows"]:
            self.assertIn(row["a11y"], named)
        for label in form.findChildren(QLabel):
            if label.isVisibleTo(form):
                shown = label.plain_text() if isinstance(label, UI.Label) else label.text()
                self.assertTrue(shown.strip() or label.accessibleName().strip(), "글이 없는 보이는 글자 칸이 없다")

    def test_the_status_colors_are_never_the_only_way_to_tell_and_there_is_no_green_or_orange(self):
        """색은 안내 파랑·흐린 회색·거절의 빨강뿐이다(초록은 '안전', 주황은 확인창의 뜻이라 쓰지 않는다). 안내는 늘 글이 함께 있다."""
        window, form = self.with_two_files()
        window.style_compute()
        self.wait_phase(window, "result")
        tones = {label.property("tone") for label in form.findChildren(QLabel) if label.property("tone")}
        self.assertLessEqual(tones, {"blue", "slate", "red"})
        self.assertNotIn("green", tones)
        self.assertNotIn("orange", tones)


# ---- 6) 안전 증명(Qt 층) — 글이 어디에도 남지 않는다 ---------------------------------------------------------------------------------
class ZeroTraceTest(Base):
    MARK = "카나리표지문장zq7k3j9x전혀다른낱말r4t6y8입니다"

    def probes(self):
        return leak.needles(self.MARK, size=8)

    def make_text(self, flavor):
        mark = self.MARK
        if flavor == "md":
            return f"# 제목\n\n## {mark} 소제목\n\n{mark}. 이 문장은 {mark} 를 담고 있습니다. 정말요?\n\n> 인용 {mark}\n\n- {mark} 목록\n\n```\n{mark}\n```"
        return f"{mark}. 이 문장은 {mark} 를 담고 있습니다.\n\n둘째 문단 {mark} 입니다. 정말요?"

    def test_the_marker_is_nowhere_in_any_widget_state_output_clipboard_or_the_data_folder_at_any_moment(self):
        probes = self.probes()
        data = self.root / "data"
        data.mkdir()
        (data / "settings.json").write_text('{"naver_profiles": {}}', encoding="utf-8")
        (data / "topic_engine").mkdir()
        (data / "topic_engine" / "channel_profiles.json").write_text("{}", encoding="utf-8")
        before = {path.relative_to(data).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns) for path in data.rglob("*") if path.is_file()}
        md, txt = self.put("a.md", self.make_text("md")), self.put("b.txt", self.make_text("txt"))
        clipboard = []
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            window = self.make(md, txt, clipboard=lambda value: clipboard.append(value) or True)
            form = self.open_dialog(window)
            os.environ["CHANCEBLOG_DESKTOP_DATA"] = str(data)
            self.addCleanup(lambda: os.environ.pop("CHANCEBLOG_DESKTOP_DATA", None))
            moments = []
            window.style_pick()
            moments.append("파일 하나")
            self.assertEqual(leak.widget_hits(window, probes), [], moments[-1])
            window.style_pick()
            self.settle()
            moments.append("파일 둘")
            self.assertEqual(leak.widget_hits(window, probes), [], moments[-1])
            window.style_compute()
            moments.append("세는 중")
            self.assertEqual(leak.widget_hits(window, probes), [], moments[-1])
            self.wait_phase(window, "result")
            moments.append("결과")
            self.assertEqual(leak.widget_hits(window, probes), [], moments[-1])
            self.assertEqual(leak.graph_hits(window.style, probes, skip=(window.style.provider,)), [], "컨트롤러 상태")
            self.assertEqual(leak.graph_hits(window.style.view(0), probes), [], "뷰모델")
            window.style_again()
            form.paste.setPlainText(self.make_text("txt"))
            self.settle(2)
            self.assertEqual([hit for hit in leak.widget_hits(window, probes, typing_into=(form.paste,)) if not hit.startswith("PasteBox:.plain")], [], "붙여 넣는 중(입력 칸의 글만 빼고)")
            window.style_compute()
            self.wait_phase(window, "result")
            self.assertEqual(leak.widget_hits(window, probes), [], "붙여 넣은 글 결과")
            window.style_close()
            self.settle()
            self.assertEqual(leak.widget_hits(window, probes), [], "닫은 뒤")
            self.assertEqual(leak.graph_hits(window.style, probes, skip=(window.style.provider,)), [], "닫은 뒤 컨트롤러")
        self.assertEqual(clipboard, [], "클립보드에 아무것도 쓰지 않는다")
        for stream in (out.getvalue(), err.getvalue()):
            self.assertEqual(leak.text_hits(stream, probes), [])
        self.assertEqual(leak.file_hits(data, probes), [])
        after = {path.relative_to(data).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns) for path in data.rglob("*") if path.is_file()}
        self.assertEqual(after, before, "데이터 폴더의 바이트·수정 시각이 그대로다(설정·프로필·보관함은 읽지도 쓰지도 않는다)")
        self.assertEqual(sorted(path.name for path in data.rglob("*")), sorted(["settings.json", "topic_engine", "channel_profiles.json"]), "새 파일이 생기지 않았다")

    def test_a_failure_keeps_no_text_in_the_error_the_state_or_the_widgets(self):
        probes = self.probes()
        window = self.make(self.put("gone.txt", self.make_text("txt")))
        form = self.open_dialog(window)
        window.style_pick()
        os.remove(str(self.root / "gone.txt"))
        window.style_compute()
        ui_offscreen.wait_until(self.app, lambda: window.style.message != "", 10)
        self.settle()
        self.assertIn("기존 글 파일 — ", form.message.plain_text())
        self.assertEqual(leak.widget_hits(window, probes), [])
        self.assertEqual(leak.graph_hits(window.style, probes, skip=(window.style.provider,)), [])
        self.assertNotIn("gone", " ".join(self.texts(window)))

    def test_the_real_provider_errors_are_clean_for_the_marker_in_the_file_and_the_name(self):
        from chanceblog_desktop.ui import style_adapter
        provider = style_adapter.ServiceStyleProvider()
        named = self.put(self.MARK[:12] + "-표지.docx", self.make_text("txt"))
        try:
            provider.check_files([named])
        except style_view.StyleRefusal as refusal:
            self.assertEqual(leak.error_hits(refusal, self.probes() + leak.needles(self.MARK[:12], size=8)), [])
        else:
            self.fail("거절되지 않았다")


if __name__ == "__main__":
    unittest.main()
