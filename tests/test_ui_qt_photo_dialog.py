"""확인창의 본문 스크롤(PySide6, 사진 연동 3단계 검증 Q 의 PQ-16) 시험 — 복사 확인창이 확인 권장과 올릴 사진 줄을 함께 보일 때(사진이 많을수록 길다) 낮은 창에서 끝줄이 잘리고 스크롤도 없었다.
창을 화면에 띄우지 않고(offscreen) 가짜 공급자(메모리)로 한다 — 사용자의 파일·데이터 폴더·클립보드는 건드리지 않고, 사진 파일은 만들지도 읽지도 않는다(경로는 글자일 뿐이다).
**PySide6 가 없으면 Qt 시험은 건너뛴다**(CI 에는 PySide6 가 없다 — 줄을 만드는 순수 부분은 `test_ui_photo_copy_core`). 소스 규칙(`SourceRulesTest` — 본문 칸을 쓰는지·사진 정보 실패 경고창·포커스 이동)은 PySide6 없이도 돈다.

지키는 것:
  1) 본문이 창에 다 들어가면 지금까지와 똑같다 — 본문 칸의 높이는 글이 필요한 만큼이고 스크롤 막대·Tab 정거장·접근 이름이 따로 생기지 않는다(일곱 크기 모두).
  2) 창이 낮아 안 들어갈 때만 본문이 세로로 스크롤된다 — 제목과 단추는 스크롤 밖에 그대로 있어 단추가 늘 창 안에 있고, 맨 아래까지 내리면 끝줄이 보이며, 가로 스크롤은 없다.
  3) 스크롤이 있을 때는 키보드로도 읽는다 — 그때만 Tab 정거장이 되고(접근 이름은 본문 글) 방향키·PageUp·PageDown·Home·End 로 움직이며 Tab 은 창 안에서만 돈다. 마우스로 본문을 눌러도(휠도) 포커스가 단추에서 옮겨 오지 않는다(검증 Q PQ-22 — Enter 가 단추를 그대로 누른다).
  4) 확정한 사진 10장의 복사 확인창이 일곱 크기에서 잘림 없이 보이고 단추가 창 안에 있다(사진 3장도 같다).
`show_dialog`·`show_choice_dialog` 둘 다 같은 본문 칸을 쓴다.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_qt_drafts import HAVE, QT_DIR, SIZES, methods_of  # noqa: E402
from test_ui_qt_drafts import Base as DraftsBase  # noqa: E402
from test_ui_qt_drafts_save import provider  # noqa: E402
from test_ui_qt_photo import FILE_MARK, fake_path  # noqa: E402
from test_ui_qt_photo_save import Base as PhotoSaveBase  # noqa: E402

if HAVE:
    from test_ui_qt_drafts import QAbstractButton, QTest, Qt, ui_offscreen
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    from chanceblog_desktop.ui.qt import components as UI

from chanceblog_desktop.ui.core import text  # noqa: E402

T = text.T
SHORT = "저장하지 않은 내용이 있어요. 저장하고 이동할까요?"


def long_body(lines=70):
    return "\n".join(f"{number}. 올릴 사진 순서를 알려 드려요 — 이 줄은 일부러 길게 적어 낮은 창에서 스크롤이 생기게 해요" for number in range(1, lines + 1))


class BodyHelpers:
    def body_of(self, window):
        found = window.dialog.findChildren(UI.DialogBody)
        self.assertEqual(len(found), 1, "확인창 본문 칸은 하나")
        return found[0]

    def inside_window(self, window, widget):
        rect = window.rect()
        return rect.contains(widget.mapTo(window, widget.rect().topLeft())) and rect.contains(widget.mapTo(window, widget.rect().bottomRight()))

    def check_buttons_inside(self, window, where):
        buttons = [button for button in window.dialog.findChildren(QAbstractButton) if button.isVisibleTo(window.dialog)]
        self.assertGreaterEqual(len(buttons), 1, where)
        for button in buttons:
            self.assertTrue(self.inside_window(window, button), f"단추 `{button.text()}` 가 창 밖으로 나갔다 {where}")
        self.assertTrue(window.rect().contains(window.dialog.geometry()), f"확인창이 창 밖으로 나갔다 {where}")

    def reachable_end(self, body):
        """맨 아래까지 내리면 본문의 끝줄이 보이는 영역 안에 있고, 맨 위로 올리면 첫 줄이 있다."""
        bar = body.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.settle(2)
        label = body.label
        self.assertLessEqual(label.mapTo(body.viewport(), label.rect().bottomLeft()).y(), body.viewport().height() + 1, "맨 아래까지 내려도 끝줄이 안 보인다")
        bar.setValue(0)
        self.settle(2)
        self.assertGreaterEqual(label.mapTo(body.viewport(), label.rect().topLeft()).y(), 0, "맨 위로 올리면 첫 줄이 보여야 한다")


def code_of(function):
    """함수의 몸(독스트링은 뺀다) — 소스 규칙이 설명 글이 아니라 코드를 보게."""
    body = function.body[1:] if function.body and isinstance(function.body[0], ast.Expr) and isinstance(getattr(function.body[0], "value", None), ast.Constant) else function.body
    return "\n".join(ast.unparse(statement) for statement in body)


class SourceRulesTest(unittest.TestCase):
    """PySide6 없이도 도는 소스 규칙(CI 와 같은 조건 — CI 에는 PySide6 가 없어 위 Qt 시험은 건너뛴다) — 확인창 본문이 스크롤 칸을 쓰고, `저장하고 나가기` 의 사진 정보 실패가 경고창으로 이어지고, 되돌릴 사본 단추가 꺼지기 전에 포커스를 넘긴다."""

    def test_both_dialog_functions_put_the_body_in_the_scrolling_body_widget(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        for name in ("show_dialog", "show_choice_dialog"):
            code = code_of(methods[name])
            self.assertIn("UI.DialogBody(body)", code, name)
            self.assertNotIn("UI.label(body", code, f"{name}: 본문을 그냥 글로 두면 낮은 창에서 끝줄이 잘린다(검증 Q PQ-16)")

    def test_the_body_widget_is_a_scroll_area_that_reports_its_height_shrinks_and_has_no_sideways_bar(self):
        tree = ast.parse((QT_DIR / "components.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DialogBody")
        self.assertEqual([ast.unparse(base) for base in cls.bases], ["QScrollArea"])
        self.assertTrue({"heightForWidth", "sizeHint", "minimumSizeHint", "keyPressEvent", "_range_changed"} <= {node.name for node in cls.body if isinstance(node, ast.FunctionDef)})
        source = ast.unparse(cls)
        for needed in ("setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)", "setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)", "setWidgetResizable(True)", "QSize(0, 0)", "Qt.TabFocus if scrolling else Qt.NoFocus"):
            self.assertIn(needed, source, needed)
        for forbidden in ("StrongFocus", "ClickFocus", "WheelFocus"):
            self.assertNotIn(forbidden, source, f"{forbidden}: 본문을 마우스로 눌렀을 때 포커스가 단추에서 옮겨 오면 Enter 가 단추를 못 누른다(검증 Q PQ-22) — 본문 칸은 Tab 으로만 닿는다")
        places = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "place" and "self.layout_" in ast.unparse(node)]
        self.assertEqual(len(places), 1, "확인창의 `place` 는 하나")
        self.assertIn("max(120, parent.height() - 32)", places[0], "확인창 높이는 창 높이로 자른다 — 넘치는 글은 본문 칸이 스크롤로 받는다")

    def test_saving_to_leave_goes_to_the_warning_when_only_the_photo_info_failed(self):
        code = code_of(methods_of(QT_DIR / "shell.py", "AppShell")["_after_save"])
        self.assertIn("status == 'photos_failed'", code)
        branch = code[code.index("status == 'photos_failed'"):code.index("_continue_after")]
        self.assertIn("_after_save_failed", branch, "사진 정보만 실패하면 이어서 나가지 않고 경고창을 잇는다")
        self.assertIn("return", branch)

    def test_the_trash_buttons_hand_the_focus_to_the_card_button_before_they_go_off_or_hide(self):
        source = (QT_DIR / "draft_screen.py").read_text(encoding="utf-8")
        function = source[source.index("def _apply_trash"):source.index("def _checks_card")]
        self.assertIn("ui.photos_button.setFocus", function, "포커스를 카드 단추로 옮기는 코드가 있다")
        move = function.index("ui.photos_button.setFocus")
        self.assertLess(move, function.index("box.setVisible"), "숨기기 전에 옮긴다")
        self.assertLess(move, function.index("setEnabled"), "끄기 전에 옮긴다 — 꺼진 뒤에는 Qt 가 포커스를 엉뚱한 곳으로 던진다(검증 Q PQ-2)")
        self.assertIn("ui.photos_restore.hasFocus()", function, "되돌리기 단추의 포커스를 본다")
        self.assertIn("ui.photos_clear.hasFocus()", function, "사본 비우기 단추의 포커스도 본다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ScrollBehaviorTest(BodyHelpers, DraftsBase):
    """본문 칸 자체의 동작 — 직접 만든 짧은 글·긴 글로 일곱 크기에서 본다(두 확인창 함수 모두)."""

    def test_a_short_body_looks_as_it_did_with_no_bar_no_stop_and_no_extra_height_at_every_size(self):
        window = self.make()
        for size in SIZES:
            with self.subTest(size=size):
                window.resize(*size)
                self.settle(6)
                window.show_dialog("제목", SHORT, ok="확인", cancel="취소")
                self.settle(4)
                body = self.body_of(window)
                bar = body.verticalScrollBar()
                self.assertEqual((bar.maximum(), bar.isVisibleTo(body), body.horizontalScrollBar().isVisibleTo(body)), (0, False, False), "다 들어가면 스크롤 막대가 없다")
                self.assertEqual((body.focusPolicy(), body.accessibleName()), (Qt.NoFocus, ""), "다 들어가면 Tab 정거장도 접근 이름도 따로 없다")
                label = body.label
                self.assertLessEqual(abs(label.height() - label.heightForWidth(label.width())), 1, "본문 글은 필요한 높이 그대로다")
                self.assertLessEqual(abs(body.height() - label.height()), 1, "본문 칸은 글 높이 그대로다(남는 칸이 없다)")
                self.assertEqual(ui_offscreen.find_clipping(window.dialog), [], size)
                self.check_buttons_inside(window, size)
                window.close_dialog()

    def test_a_long_body_scrolls_at_every_size_and_the_buttons_stay_inside_the_window(self):
        window = self.make()
        for size in SIZES:
            with self.subTest(size=size):
                window.resize(*size)
                self.settle(6)
                window.show_dialog("제목", long_body(), ok="확인", cancel="취소")
                self.settle(4)
                body = self.body_of(window)
                bar = body.verticalScrollBar()
                self.assertGreater(bar.maximum(), 0, "글이 창보다 길면 스크롤된다")
                self.assertTrue(bar.isVisibleTo(body), "스크롤 막대가 보인다")
                self.assertFalse(body.horizontalScrollBar().isVisibleTo(body), "가로 스크롤은 없다")
                self.assertEqual(body.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
                self.check_buttons_inside(window, size)
                self.assertLessEqual(window.dialog.height(), max(120, window.height() - 32), "확인창은 창보다 크지 않다")
                self.assertEqual(ui_offscreen.find_clipping(window.dialog), [], size)
                self.reachable_end(body)
                window.close_dialog()

    def test_the_choice_dialog_uses_the_same_scrolling_body(self):
        window = self.make(size=(900, 560))
        window.show_choice_dialog("제목", long_body(), [("save", "저장", "primary", None), ("discard", "저장 안 하고 나가기", "danger", None), ("stay", "계속 고치기", "secondary", None)], first="save")
        self.settle(4)
        body = self.body_of(window)
        self.assertGreater(body.verticalScrollBar().maximum(), 0)
        self.assertEqual(sorted(self.dialog_buttons(window)), ["계속 고치기", "저장", "저장 안 하고 나가기"])
        self.check_buttons_inside(window, (900, 560))
        self.assertEqual(ui_offscreen.find_clipping(window.dialog), [])
        self.reachable_end(body)

    def test_when_it_scrolls_the_body_is_a_named_tab_stop_that_the_keys_move_and_tab_stays_in_the_dialog(self):
        window = self.make(size=(900, 560))
        window.show_dialog("제목", long_body(), ok="확인", cancel="취소", safe_focus=True)
        self.settle(4)
        body = self.body_of(window)
        bar = body.verticalScrollBar()
        self.assertEqual((body.focusPolicy(), body.accessibleName()), (Qt.TabFocus, body.label.plain_text()), "스크롤이 있으면 키보드로 읽을 수 있게 Tab 정거장이고 이름은 본문 글이다 — Tab 으로만 닿는다")
        body.setFocus(Qt.TabFocusReason)
        self.settle(1)
        self.assertTrue(body.hasFocus())
        QTest.keyClick(body, Qt.Key_PageDown)
        self.assertGreater(bar.value(), 0, "PageDown 으로 내려간다")
        QTest.keyClick(body, Qt.Key_End)
        self.assertEqual(bar.value(), bar.maximum(), "End 로 맨 아래까지 간다")
        QTest.keyClick(body, Qt.Key_Home)
        self.assertEqual(bar.value(), 0, "Home 으로 맨 위로 간다")
        QTest.keyClick(body, Qt.Key_Down)
        self.assertGreater(bar.value(), 0, "방향키로도 움직인다")
        seen = []
        for _ in range(6):
            QTest.keyClick(self.app.focusWidget(), Qt.Key_Tab)
            self.settle(1)
            focus = self.app.focusWidget()
            self.assertTrue(focus is not None and window.dialog.isAncestorOf(focus), "Tab 은 확인창 안에서만 돈다")
            seen.append("body" if focus is body else focus.text())
        self.assertIn("body", seen, "Tab 으로 본문 칸에 닿는다")
        self.assertTrue({"확인", "취소"} <= set(seen), "두 단추에도 닿는다")

    def test_the_stop_goes_away_again_when_the_window_grows_and_the_whole_body_fits(self):
        window = self.make(size=(900, 560))
        body_text = "\n".join(f"줄 {number}" for number in range(1, 26))
        window.show_dialog("제목", body_text, ok="확인", cancel="취소")
        self.settle(4)
        body = self.body_of(window)
        self.assertGreater(body.verticalScrollBar().maximum(), 0, "낮은 창에서는 스크롤된다")
        self.assertEqual(body.focusPolicy(), Qt.TabFocus)
        window.resize(1920, 1080)
        self.settle(8)
        self.assertEqual((body.verticalScrollBar().maximum(), body.focusPolicy(), body.accessibleName()), (0, Qt.NoFocus, ""), "다 들어가면 막대·정거장·이름이 다시 사라진다")
        window.close_dialog()


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class BodyFocusTest(BodyHelpers, DraftsBase):
    """검증 Q PQ-22 — 스크롤이 있는 확인창의 본문 칸은 Tab 으로만 닿는다(`Qt.TabFocus`). 마우스로 본문을 눌러도·휠을 돌려도 포커스가 단추에서 옮겨 오지 않아 Enter 가 그 단추를 그대로 누른다
    (예전엔 `StrongFocus` 라 한 번 누르면 포커스가 본문으로 가서 Enter 가 아무것도 안 눌렀다). 작게 넘칠 때(사진 3장·1093×614 에서 10px — PQ-18)도 키보드로 읽는 정거장이 있다."""

    def open_long(self, window, **kwargs):
        window.show_dialog("제목", long_body(), ok="확인", cancel="취소", safe_focus=True, **kwargs)
        self.settle(4)
        body = self.body_of(window)
        self.assertGreater(body.verticalScrollBar().maximum(), 0, "이 시험은 스크롤이 있는 확인창에서 한다")
        first = self.dialog_buttons(window)["취소"]
        self.assertIs(self.app.focusWidget(), first, "처음 포커스는 취소다(safe_focus)")
        return body, first

    def wheel_down(self, body, notches=2):
        pos = QPointF(60, 60)
        event = QWheelEvent(pos, body.viewport().mapToGlobal(pos), QPoint(0, 0), QPoint(0, -120 * notches), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(body.viewport(), event)
        self.settle(2)

    def test_pressing_the_body_with_the_mouse_keeps_the_focus_on_the_button_and_enter_still_presses_it(self):
        window = self.make(size=(900, 560))
        confirmed = []
        body, first = self.open_long(window, on_ok=lambda: confirmed.append("ok"))
        QTest.mouseClick(body.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
        self.settle(2)
        self.assertIs(self.app.focusWidget(), first, "본문을 눌러도 포커스는 단추에 그대로다")
        self.assertFalse(body.hasFocus())
        QTest.keyClick(self.app.focusWidget(), Qt.Key_Return)
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "Enter 가 취소 단추를 눌러 확인창을 닫는다")
        self.assertEqual(confirmed, [], "확인(on_ok)은 눌리지 않았다")

    def test_the_mouse_wheel_scrolls_the_body_without_taking_the_focus(self):
        """휠은 본문을 스크롤하고 포커스를 안 옮긴다. (직접 만든 휠 이벤트는 Qt 가 '정책에 따른 포커스 주기' 를 거치지 않는 비자발 이벤트라 휠 포커스 자체는 위 클릭 시험과 정책 단언(`TabFocus` 뿐)이 지킨다.)"""
        window = self.make(size=(900, 560))
        body, first = self.open_long(window)
        bar = body.verticalScrollBar()
        before = bar.value()
        self.wheel_down(body)
        self.assertGreater(bar.value(), before, "휠로 본문이 스크롤된다")
        self.assertIs(self.app.focusWidget(), first, "휠은 포커스를 안 뺏는다")
        self.assertFalse(body.hasFocus())
        window.close_dialog()

    def test_tab_still_reaches_the_body_and_shift_tab_gives_the_focus_back_to_a_button(self):
        window = self.make(size=(900, 560))
        body, first = self.open_long(window)
        self.assertEqual(body.focusPolicy(), Qt.TabFocus, "Tab 으로만 닿는다(클릭·휠로는 안 닿는다)")
        reached = False
        for _ in range(4):
            QTest.keyClick(self.app.focusWidget(), Qt.Key_Tab)
            self.settle(1)
            if self.app.focusWidget() is body:
                reached = True
                break
        self.assertTrue(reached, "Tab 으로 본문 칸에 닿는다")
        QTest.keyClick(body, Qt.Key_PageDown)
        self.assertGreater(body.verticalScrollBar().value(), 0, "닿은 뒤에는 키로 읽는다")
        QTest.keyClick(self.app.focusWidget(), Qt.Key_Backtab)
        self.settle(1)
        focus = self.app.focusWidget()
        self.assertTrue(focus is not None and focus is not body and window.dialog.isAncestorOf(focus) and isinstance(focus, QAbstractButton), "Shift+Tab 으로 본문에서 단추로 돌아간다")
        window.close_dialog()

    def test_even_a_tiny_overflow_makes_the_body_a_named_tab_stop(self):
        """작게 넘쳐도(여기서는 6px 쯤) 키보드 사용자가 잘린 줄을 읽을 수 있게 정거장·이름이 생긴다 — 문턱은 없다(스크롤 범위가 0 보다 크면 생긴다)."""
        window = self.make(size=(900, 1400))
        window.show_dialog("제목", "\n".join(f"{number}. 확인창 본문 줄" for number in range(1, 31)), ok="확인", cancel="취소")
        self.settle(4)
        body = self.body_of(window)
        bar = body.verticalScrollBar()
        self.assertEqual((bar.maximum(), body.focusPolicy(), body.accessibleName()), (0, Qt.NoFocus, ""), "큰 창에서는 다 들어가 막대·정거장·이름이 없다")
        needed = window.dialog.layout_.totalHeightForWidth(window.dialog.width())
        window.resize(900, needed + 32 - 6)
        self.settle(8)
        self.assertTrue(0 < bar.maximum() <= 14, f"6px 쯤 넘쳐야 한다(실제 {bar.maximum()}px)")
        self.assertEqual((body.focusPolicy(), body.accessibleName()), (Qt.TabFocus, body.label.plain_text()), "조금 넘쳐도 키보드로 읽을 정거장이고 이름은 본문 글이다")
        window.close_dialog()


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class CopyDialogFitTest(BodyHelpers, PhotoSaveBase):
    """검증 Q 의 재현(`exp_q14`) — 사진을 확정해 다시 만든 글의 `본문 복사` 확인창(확인 권장 + 올릴 사진 줄)이 일곱 크기에서 잘림 없이 보인다."""

    def prepared(self, count):
        """사진 `count` 장을 모두 확인하고 다시 만든 초안 → 창."""
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        window, form = self.sheet(window)
        self.add_photos(form, *[fake_path(number) for number in range(1, count + 1)])
        for number in range(1, count + 1):
            form.rows[f"p{number:03d}"].confirm_box.click()
            self.settle(1)
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        window.drf_remake()
        self.assertTrue(self.wait_draft(window))
        self.settle(4)
        return window

    def open_copy_dialog(self, window, size):
        window.resize(*size)
        self.settle(8)
        self.button(window, "act:body").click()
        self.settle(4)
        self.assertTrue(window.dialog.is_open, f"복사 확인창이 떠야 한다 {size}")
        return self.body_of(window)

    def test_ten_confirmed_photos_and_three_fit_the_copy_dialog_at_every_size(self):
        for count in (10, 3):
            window = self.prepared(count)
            for size in SIZES:
                with self.subTest(photos=count, size=size):
                    body = self.open_copy_dialog(window, size)
                    shown = body.label.plain_text()
                    self.assertIn(T["pho_gate_uploads"].format(n=count), shown)
                    self.assertIn(T["pho_gate_upload_line"].format(n=1, name=f"{FILE_MARK}-01.jpg"), shown)
                    self.assertIn(T["drf_gate_tail"], shown, "끝 안내까지 본문에 있다")
                    self.assertEqual(ui_offscreen.find_clipping(window.dialog), [], (count, size))
                    self.check_buttons_inside(window, (count, size))
                    self.assertFalse(body.horizontalScrollBar().isVisibleTo(body), "가로 스크롤은 없다")
                    bar = body.verticalScrollBar()
                    needed = window.dialog.layout_.totalHeightForWidth(window.dialog.width())
                    if needed > max(120, window.height() - 32):
                        self.assertTrue(bar.maximum() > 0 and bar.isVisibleTo(body), f"창보다 길면 스크롤된다(필요 {needed}px)")
                        self.reachable_end(body)
                    else:
                        self.assertEqual((bar.maximum(), body.focusPolicy()), (0, Qt.NoFocus), f"다 들어가면 스크롤이 없다(필요 {needed}px)")
                    self.dialog_buttons(window)[T["drf_cancel"]].click()                   # 다음 크기에서 새로 열기 전에 닫는다(열린 확인창을 다른 것으로 바꾸는 길이 아니라)
                    self.settle(2)
                    self.assertFalse(window.dialog.is_open)
            window.state.drafts.leave()
            window.close()

    def test_the_lowest_window_with_ten_photos_really_needs_the_scroll_and_its_last_line_is_reachable(self):
        """시험이 헛돌지 않게 — 가장 낮은 창(900×560)에서 사진 10장의 확인창은 실제로 창보다 길어 스크롤이 필요하다(검증 Q 가 잰 값: 필요 682px > 한도 528px)."""
        window = self.prepared(10)
        body = self.open_copy_dialog(window, (900, 560))
        needed = window.dialog.layout_.totalHeightForWidth(window.dialog.width())
        self.assertGreater(needed, window.height() - 32, "이 사진 수에서는 본문이 창보다 길다")
        self.assertGreater(body.verticalScrollBar().maximum(), 0)
        self.reachable_end(body)
        shown = body.label.plain_text()
        self.assertIn(T["pho_gate_upload_line"].format(n=8, name=f"{FILE_MARK}-08.jpg"), shown, "여덟째 사진 줄까지 보이고")
        self.assertIn(T["drf_gate_more"].format(n=2), shown, "나머지는 개수로 알린다")
        self.assertIn(T["drf_gate_tail"], shown, "끝 안내(그래도 복사 안내)가 맨 아래에 있다")

    def test_pressing_the_scrolling_copy_dialog_body_does_not_move_the_focus_and_enter_closes_it_without_copying(self):
        """검증 Q 의 재현(`exp_q24`) — 사진 10장·900×560 복사 확인창(처음 포커스 `취소`)에서 본문을 눌러도 포커스는 `취소` 에 그대로이고 Enter 가 확인창을 닫는다(복사 0건)."""
        window = self.prepared(10)
        window.resize(900, 560)
        self.settle(8)
        self.activate(window)                                                           # 화면 없는 환경에서는 창이 저절로 활성이 되지 않아 포커스가 안 간다 — 크기를 바꾼 뒤 활성으로 만든다
        self.button(window, "act:body").click()
        self.settle(4)
        self.assertTrue(window.dialog.is_open, "복사 확인창이 떠야 한다")
        body = self.body_of(window)
        self.assertGreater(body.verticalScrollBar().maximum(), 0)
        cancel = self.dialog_buttons(window)[T["drf_cancel"]]
        self.assertIs(self.app.focusWidget(), cancel, "처음 포커스는 취소다")
        QTest.mouseClick(body.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
        self.settle(2)
        self.assertIs(self.app.focusWidget(), cancel, "본문을 눌러도 포커스는 취소에 그대로다")
        QTest.keyClick(self.app.focusWidget(), Qt.Key_Return)
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "Enter 가 취소를 눌러 확인창을 닫는다")
        self.assertEqual(self.copied, [], "아무것도 복사되지 않았다")
        window.state.drafts.leave()
        window.close()


if __name__ == "__main__":
    unittest.main()
