"""'참고 글 보관함'(결정 D-490)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) '내 글 문체 참고값 보기' 대화상자 안의 진입 단추와 보관함 대화상자(목록·붙여 넣어 올리기·파일에서 올리기·열어서 고쳐 저장·
저장 안 한 변경 확인·지우기 두 단계·오류 문장·닫기)를 **진짜 서비스 + 임시 데이터 폴더**로 실제로 눌러 본다. **PySide6 가 없으면 통째로 건너뛴다**(저장소 CI 에는 PySide6 가 없다 — 그쪽은 계속 초록이다).
모든 글·파일은 임시 폴더이고 이 PC 의 실제 데이터 폴더는 읽지도 쓰지도 않는다(가짜 파일 선택기·임시 데이터 폴더). 처음 띄워 본 날(2026-11-16) 찾아 고친 것: 거절 문장·확인 줄이 스크롤 안쪽 아래에 있어 안 보였고, Esc 가 확인 없이 닫았다.

지키는 것:
  · 진입 — 문체 보기 대화상자에 단추가 하나 늘었고(접근 이름·36px 이상·Tab 정거장), 누르면 보관함이 열리며 문체 보기의 나머지 동작은 그대로다.
  · 흐름 — 빈 상태 문구·붙여 넣어 올리기(정상·빈 제목·너무 긴 제목·비밀 모양·너무 긴 본문)·파일에서 올리기·목록 순서·열기→고치기→저장·깨진 파일 건너뜀 알림.
  · 저장 안 한 변경 — 다른 글 열기·새 글·닫기 단추·Esc·창 닫기(X·Alt+F4)가 모두 같은 확인을 거치고, 확인이 열려 있으면 다른 단추가 꺼지며, 어느 쪽을 골라도 글이 조용히 사라지지 않는다.
  · 지우기 — 두 단계 확인, 어느 단계에서든 그만두면 아무것도 안 지워지고, 지우면 그 글 파일 하나만 사라진다.
  · 거절·오류 문장 — 스크롤 밖 상태 줄에 늘 보이고, 글·제목·경로·파일 이름이 문장·위젯 어디에도 되풀이되지 않는다(글은 편집 칸에만 있다).
  · 낡은 결과 — 닫은 뒤 늦게 온 결과는 새 대화상자에 섞이지 않는다. 닫으면 편집 칸·목록이 비워진다.
  · 크기 — 모든 필수 크기와 최소 창(900×560)에서 가로 스크롤·글자 잘림·삐져나옴이 없고 단추 줄이 늘 보인다.
"""
import errno
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import key_leak_support as leak  # noqa: E402
import service_support as ss  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import context as context_module  # noqa: E402
from chanceblog_desktop.service import references as ref_service  # noqa: E402
from chanceblog_desktop.ui.core import references_view as rv  # noqa: E402
from chanceblog_desktop.ui.core import services, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core.references_view import FakeReferencesProvider  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QPlainTextEdit, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import references_dialog
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.references_adapter import ServiceReferencesProvider

T = text.T
SIZES = ((1366, 768), (1536, 864), (1280, 720), (1920, 1080), (900, 560))
BODY_MARK, TITLE_MARK, NAME_MARK = "UNIQ-BODY-qt5k-본문", "UNIQ-TITLE-qt8m-제목", "uniq-name-qt2w"
KEY = ss.KEY
LONG_BODY = "가나다라마바사아자차카타파하 " * 6 + "입니다.\n"


class Picker:
    """가짜 파일 선택기 — 정해 둔 위치를 차례로 돌려주고(없으면 취소 = 빈 글) 부른 횟수를 센다."""

    def __init__(self):
        self.paths, self.calls = [], 0

    def __call__(self, parent, title, filter_text):
        self.calls += 1
        self.last = (title, filter_text)
        return self.paths.pop(0) if self.paths else ""


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
        holder = tempfile.TemporaryDirectory(prefix="refs-qt-")
        self.addCleanup(holder.cleanup)
        self.root = Path(os.path.realpath(holder.name))
        self.clock = ss.Clock()
        self.ctx = ss.make_ctx(self.root, clock=self.clock, repo="")
        self.vault = self.ctx.workspace.root / "references"
        self.picker = Picker()

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    # ---- 도우미 ----
    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def real(self):
        return ServiceReferencesProvider(None, context_factory=lambda data_dir=None: self.ctx)

    def make(self, *, size=(1440, 900), provider=None, **kwargs):
        window = shell_module.AppShell(services.FakeHomeProvider(), connections=services.FakeConnectionsProvider(), autoload=False, file_picker=self.picker, references=provider or self.real(), **kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)
        return window

    def open_vault(self, window):
        """문체 보기 대화상자를 열고 그 안의 `참고 글 보관함 열기` 단추를 누른다(진짜 길)."""
        window.style_open()
        self.settle()
        self.assertIsNotNone(window.style_form)
        window.style_form.refs_button.click()
        self.settle(10)
        self.assertIsNotNone(window.references_form)
        return window.references_form

    def vault_window(self, **kwargs):
        window = self.make(**kwargs)
        return window, self.open_vault(window)

    def add_post(self, title, body, minutes=1):
        """서비스로 곧바로 글을 하나 보관한다(화면을 거치지 않는다) — 시계는 `minutes` 분 흐른다."""
        self.clock.advance(minutes=minutes)
        return ref_service.add_reference(self.ctx, title=title, body=body)

    def click(self, button):
        QTest.mouseClick(button, Qt.LeftButton)
        self.settle()

    def type_post(self, form, title, body):
        form.title_input.setText(title)
        form.body.setPlainText(body)
        self.settle(2)

    def save(self, window):
        window.references.edited(window.references_form.title_text(), window.references_form.body_text())
        self.click(window.references_form.save_button)

    def texts(self, root):
        return [label.text() if not isinstance(label, UI.Label) else label.plain_text() for label in root.findChildren(QLabel) if label.isVisibleTo(root)]

    def buttons(self, root):
        return [widget for widget in root.findChildren(QAbstractButton) if widget.isVisibleTo(root)]

    def named(self, form, name):
        found = [button for button in form.findChildren(QAbstractButton) if button.accessibleName() == name and button.isVisibleTo(form)]
        self.assertEqual(len(found), 1, (name, [button.accessibleName() for button in self.buttons(form)]))
        return found[0]

    def vault_files(self):
        return sorted(path.name for path in self.vault.iterdir()) if self.vault.exists() else []

    def outside_editors(self, window, probes):
        """편집 칸(제목·본문 입력)을 뺀 모든 위젯의 글·접근 이름·툴팁에서 조각을 찾는다 — 글은 편집 칸에만 있어야 한다."""
        editors = set()
        for form in (window.references_form, window.style_form):
            if form is not None:
                editors.update(id(widget) for widget in form.findChildren(QLineEdit) + form.findChildren(QPlainTextEdit))
        hits = []
        for widget in [window, *window.findChildren(QWidget)]:
            if id(widget) in editors:
                continue
            for label, value in leak.own_texts(widget):
                hits += [f"{label}: {probe}" for probe in leak.text_hits(value, probes)[:1]]
        return hits

    def lt(self, label):
        """라벨의 보이는 글(`UI.Label` 은 `plain_text`)."""
        return label.plain_text() if isinstance(label, UI.Label) else label.text()

    def message(self, form):
        return self.lt(form.message) if form.message.isVisibleTo(form) else ""


# ---- 1) 진입 ----------------------------------------------------------------------------------------------------------------------
class EntryTest(Base):
    def test_the_style_dialog_has_exactly_one_more_button_and_the_rest_is_unchanged(self):
        window = self.make()
        window.style_open()
        self.settle()
        names = {button.accessibleName() for button in self.buttons(window.style_form)}
        self.assertEqual(names, {T["style_pick_a11y"], T["style_compute_a11y"], T["style_close_a11y"], T["ref_entry_open_a11y"]}, "고르기·계산하기·닫기(+ 결과 모습의 다시 하기)에 단추 하나만 더해졌다")
        button = window.style_form.refs_button
        self.assertEqual((button.text(), button.accessibleName()), (T["ref_entry_open"], T["ref_entry_open_a11y"]))
        self.assertGreaterEqual(button.height(), tokens.SIZE["hit"])
        self.assertNotEqual(button.focusPolicy(), Qt.NoFocus)

    def test_pressing_the_button_replaces_the_style_dialog_with_the_vault_and_the_style_state_is_dropped(self):
        window = self.make()
        window.style_open()
        self.settle()
        self.assertTrue(window.style.is_open)
        form = self.open_vault(window)
        self.assertTrue(window.dialog.is_open)
        self.assertIs(window.references_form, form)
        self.assertIsNone(window.style_form, "문체 보기는 정리 훅이 불려 닫혔다")
        self.assertFalse(window.style.is_open)
        self.assertEqual(window.dialog.accessibleName(), T["ref_title"])

    def test_the_button_works_with_the_keyboard_too(self):
        for key in (Qt.Key_Return, Qt.Key_Space):
            with self.subTest(key=key):
                window = self.make()
                window.style_open()
                self.settle()
                window.style_form.refs_button.setFocus(Qt.TabFocusReason)
                self.settle(2)
                QTest.keyClick(window.style_form.refs_button, key)
                self.settle(8)
                self.assertIsNotNone(window.references_form)
                window.close()

    def test_the_vault_does_not_open_over_another_dialog(self):
        window = self.make()
        window.show_sample_info()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertIsNone(window.references_open())
        self.assertIsNone(window.references_form)

    def test_the_style_dialog_still_works_without_the_vault(self):
        """진입 단추를 더해도 문체 보기의 고르기·닫기는 그대로다 — 닫으면 보관함은 열리지 않고 보관함 폴더도 만들어지지 않는다."""
        window = self.make()
        window.style_open()
        self.settle()
        window.escape()
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertIsNone(window.references_form)
        self.assertFalse(self.vault.exists())

    def test_the_default_shell_with_the_sample_provider_uses_an_in_memory_vault(self):
        window = shell_module.AppShell(services.FakeHomeProvider(), connections=services.FakeConnectionsProvider(), autoload=False)
        self.addCleanup(window.close)
        window.resize(1440, 900)
        window.show()
        self.settle()
        self.assertTrue(window.references.provider.sample)
        form = self.open_vault(window)
        self.type_post(form, "예시 글", "예시 본문입니다")
        self.save(window)
        self.assertEqual(len(window.references.rows), 1)
        self.assertFalse(self.vault.exists(), "예시 공급자는 파일을 만들지 않는다")


# ---- 2) 모습 ----------------------------------------------------------------------------------------------------------------------
class ShapeTest(Base):
    def test_it_opens_empty_with_the_title_field_focused_and_every_fixed_sentence(self):
        window, form = self.vault_window()
        shown = self.texts(form)
        for key in ("ref_title", "ref_intro", "ref_list_title", "ref_list_empty", "ref_editor_new", "ref_title_label", "ref_title_hint", "ref_body_label", "ref_body_hint", "ref_folder_label", "ref_folder_note"):
            self.assertIn(T[key], shown, key)
        self.assertTrue(any("50개" in line and "80자" in line and "100,000자" in line for line in shown), shown)
        self.assertIn("0개 보관 중", shown)
        self.assertIs(QApplication.focusWidget(), form.title_input)
        self.assertFalse(form.delete_button.isEnabled())
        self.assertTrue(all(button.isEnabled() for button in (form.save_button, form.new_button, form.pick_button, form.close_button)))
        self.assertEqual(self.lt(form.folder_text), str(self.vault))
        self.assertFalse(self.vault.exists(), "열기만 해서는 보관함 폴더도 만들어지지 않는다")
        self.assertEqual(window.dialog.accessibleName(), T["ref_title"])

    def test_opened_directly_without_the_style_dialog_tab_still_stays_inside(self):
        """변이 Q19 — 문체 보기 대화상자를 거치면 바깥 위젯의 포커스는 이미 잠겨 있다. 보관함을 곧바로 열어도(`references_open`) Tab·Shift+Tab 이 대화상자 밖으로 새지 않는다."""
        self.add_post("글", "본문")
        window = self.make()
        form = window.references_open()
        self.settle(10)
        self.assertIsNotNone(form)
        form.save_button.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), form.save_button)
        QTest.keyClick(form.save_button, Qt.Key_Tab)
        self.settle(2)
        self.assertTrue(form.isAncestorOf(QApplication.focusWidget()), "마지막에서 Tab 을 눌렀더니 대화상자 밖으로 나갔다")
        form.scroll.setFocus(Qt.TabFocusReason)
        self.settle(2)
        QTest.keyClick(form.scroll, Qt.Key_Backtab)
        self.settle(2)
        self.assertTrue(form.isAncestorOf(QApplication.focusWidget()), "처음에서 Shift+Tab 을 눌렀더니 대화상자 밖으로 나갔다")

    def test_every_button_has_a_name_a_hit_size_and_a_focus_policy(self):
        window, form = self.vault_window()
        self.add_post("글", "본문")
        window.references.refresh()
        form.refresh()
        self.settle()
        buttons = self.buttons(form)
        self.assertGreaterEqual(len(buttons), 6)
        for button in buttons:
            with self.subTest(button=button.accessibleName()):
                self.assertTrue(button.accessibleName())
                self.assertGreaterEqual(button.height(), tokens.SIZE["hit"] - 8 if button.property("size") == "sm" else tokens.SIZE["hit"])
                self.assertNotEqual(button.focusPolicy(), Qt.NoFocus)
        names = [button.accessibleName() for button in buttons]
        self.assertEqual(len(names), len(set(names)), "접근 이름이 겹치지 않는다")

    def tab_walk(self, key, steps):
        seen = [QApplication.focusWidget()]
        for _ in range(steps):
            QTest.keyClick(QApplication.focusWidget(), key)
            self.settle(1)
            seen.append(QApplication.focusWidget())
        return seen

    def test_tab_and_shift_tab_walk_the_parts_in_the_visible_order_and_stay_inside_the_dialog(self):
        """검증자 Q-07 — 옛 시험은 이름과 달리 Tab 을 한 번도 누르지 않았다. 실제로 Tab·Shift+Tab 을 눌러: 몸(스크롤) → 목록의 `열기`들 → 제목 → 본문 → 지우기 → 파일에서 올리기 → 새 글 → 닫기 → 저장 → 다시 몸. 대화상자 밖으로 새지 않고 거꾸로도 같다."""
        self.add_post("첫째 글", "첫째 본문")
        self.add_post("둘째 글", "둘째 본문")
        window, form = self.vault_window()
        self.click(form.open_buttons[0])
        expected = [form.scroll, form.open_buttons[0], form.open_buttons[1], form.title_input, form.body, form.delete_button, form.pick_button, form.new_button, form.close_button, form.save_button]
        form.scroll.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), expected[0])
        names = lambda widgets: [getattr(widget, "accessibleName", lambda: "?")() for widget in widgets]
        forward = self.tab_walk(Qt.Key_Tab, len(expected))
        self.assertEqual(forward[:-1], expected, names(forward))
        self.assertIs(forward[-1], expected[0], "마지막에서 Tab 을 누르면 대화상자 안의 처음으로 돌아온다 — 바깥으로 새지 않는다")
        backward = self.tab_walk(Qt.Key_Backtab, len(expected))
        self.assertEqual(backward[:-1], [expected[0]] + expected[:0:-1], names(backward))
        self.assertIs(backward[-1], expected[0], "Shift+Tab 도 한 바퀴 돌면 제자리다")
        for widget in forward + backward:
            self.assertTrue(form.isAncestorOf(widget), "포커스가 대화상자 밖으로 나갔다")

    def test_the_dialog_is_760_wide_and_never_wider_than_ninety_four_percent_of_the_window(self):
        self.assertEqual(references_dialog.DIALOG_WIDTH, 760)
        self.assertEqual(shell_module.REFERENCES_DIALOG_WIDTH, 760)
        for size in SIZES:
            with self.subTest(size=size):
                window, form = self.vault_window(size=size)
                self.assertEqual(window.dialog.width(), min(760, int(window.width() * 0.94)))
                self.assertTrue(window.rect().contains(window.dialog.geometry()), (size, window.dialog.geometry()))
                window.close()

    def test_the_status_line_and_the_buttons_sit_outside_the_scrolling_body(self):
        """처음 띄워 보고 찾은 틈 — 거절 문장·확인 줄이 스크롤 안쪽 아래에 있어 길어진 몸에서는 화면 밖이었다. 지금은 스크롤 밖에 있다."""
        window, form = self.vault_window(size=(900, 560))
        for name in ("editor_state", "confirm_host", "message", "notice", "save_button", "close_button", "delete_button", "pick_button", "new_button"):
            self.assertFalse(form.scroll.isAncestorOf(getattr(form, name)), name)
        for name in ("title_input", "body", "rows_host", "folder_text"):
            self.assertTrue(form.scroll.isAncestorOf(getattr(form, name)), name)


# ---- 3) 붙여 넣어 올리기 ------------------------------------------------------------------------------------------------------------
class PasteTest(Base):
    def test_a_pasted_post_is_saved_listed_and_shown_as_saved(self):
        window, form = self.vault_window()
        self.type_post(form, "내 첫 글", "안녕하세요.\n두 번째 줄입니다.")
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])
        self.assertTrue(form.editor_state.isVisibleTo(form))
        self.save(window)
        self.assertEqual(self.message(form), "")
        self.assertEqual(self.lt(form.notice), T["ref_done_saved"])
        self.assertTrue(form.notice.isVisibleTo(form))
        self.assertEqual(len(self.vault_files()), 1)
        rows = [line for line in self.texts(form) if "내 첫 글" in line]
        self.assertEqual(len(rows), 1)
        self.assertIn("17자", rows[0])
        self.assertEqual(self.lt(form.editor_state), T["ref_clean"])
        self.assertEqual((form.title_input.text(), form.body.toPlainText()), ("내 첫 글", "안녕하세요.\n두 번째 줄입니다."), "저장해도 편집 칸의 글은 그대로다")
        self.assertEqual(self.lt(form.heading), T["ref_editor_edit"])
        self.assertTrue(form.delete_button.isEnabled())

    def test_an_empty_or_blank_title_is_refused_in_the_always_visible_status_line_and_the_text_stays(self):
        window, form = self.vault_window()
        for title in ("", "   "):
            self.type_post(form, title, "제목이 없는 본문")
            self.save(window)
            self.assertIn("제목을 적어 주세요", self.message(form))
            self.assertTrue(form.message.isVisibleTo(form))
            self.assertFalse(form.scroll.isAncestorOf(form.message))
            self.assertEqual(form.body.toPlainText(), "제목이 없는 본문")
            self.assertEqual(self.vault_files(), [])
        self.assertTrue(self.lt(form.editor_state) == T["ref_dirty"])

    def test_a_refusal_removes_the_earlier_saved_notice(self):
        window, form = self.vault_window()
        self.type_post(form, "첫 글", "본문")
        self.save(window)
        self.assertEqual(self.lt(form.notice), T["ref_done_saved"])
        self.type_post(form, "", "본문")
        self.save(window)
        self.assertTrue(self.message(form))
        self.assertFalse(form.notice.isVisibleTo(form), "앞 일의 '저장했어요' 가 새 거절 문장 옆에 남지 않는다")

    def test_a_title_of_eighty_one_characters_is_refused_and_eighty_is_accepted(self):
        window, form = self.vault_window()
        self.type_post(form, "가" * 81, "본문")
        self.save(window)
        self.assertIn("80자까지만", self.message(form))
        self.assertEqual(self.vault_files(), [])
        self.type_post(form, "가" * 80, "본문")
        self.save(window)
        self.assertEqual(self.message(form), "", "다음 저장이 되면 앞의 거절 문장은 사라진다")
        self.assertEqual(len(self.vault_files()), 1)

    def test_the_body_limit_is_one_hundred_thousand_characters(self):
        window, form = self.vault_window()
        self.type_post(form, "긴 글", "가" * 100_001)
        self.assertEqual(self.lt(form.body_count), "100001자")
        self.save(window)
        self.assertIn("100,000자 이하만", self.message(form))
        self.assertEqual(self.vault_files(), [])
        self.type_post(form, "긴 글", "가" * 100_000)
        self.save(window)
        self.assertEqual(self.message(form), "")
        self.assertEqual(len(self.vault_files()), 1)

    def test_a_blank_body_is_refused(self):
        window, form = self.vault_window()
        self.type_post(form, "빈 본문", "  \n \t ")
        self.save(window)
        self.assertIn("읽을 글이 없어요", self.message(form))
        self.assertEqual(self.vault_files(), [])

    def test_a_secret_shape_is_refused_with_only_the_place_and_nothing_is_stored_or_shown(self):
        window, form = self.vault_window()
        probes = leak.needles(KEY, size=8)
        for where, title, body in (("본문", "멀쩡한 제목", "앞 글입니다.\n둘째 줄 " + KEY + "\n끝"), ("제목", "제목 " + KEY, "멀쩡한 본문")):
            self.type_post(form, title, body)
            self.save(window)
            shown = self.message(form)
            self.assertIn(f"{where} ", shown)
            self.assertIn("줄에", shown)
            self.assertIn("그 부분을 지운 뒤 다시 올려 주세요", shown)
            self.assertEqual(self.vault_files(), [])
            self.assertEqual(self.outside_editors(window, probes), [], "찾은 글은 문장·위젯 어디에도 없다(글은 편집 칸에만 있다)")
        self.assertEqual(leak.graph_hits(window.references, probes, skip=(window.references.provider,)), [], "화면 규칙의 상태에도 없다")

    def test_the_counter_follows_the_typing_and_a_marker_shows_unsaved_changes(self):
        window, form = self.vault_window()
        self.assertEqual(self.lt(form.body_count), "0자")
        form.body.setPlainText("가나다")
        self.settle(2)
        self.assertEqual(self.lt(form.body_count), "3자")
        self.assertIn("3", form.body_count.accessibleName())
        QTest.keyClicks(form.title_input, "abc")
        self.assertEqual(form.title_input.text(), "abc")
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])

    def test_the_first_save_of_an_untitled_empty_dialog_creates_nothing_and_a_save_button_press_with_nothing_typed_is_a_refusal(self):
        window, form = self.vault_window()
        self.click(form.save_button)
        self.assertIn("제목을 적어 주세요", self.message(form))
        self.assertFalse(self.vault.exists())


# ---- 4) 파일에서 올리기 -------------------------------------------------------------------------------------------------------------
class FileTest(Base):
    def put(self, name, data):
        folder = self.root / "내 글 모음"
        folder.mkdir(exist_ok=True)
        path = folder / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)

    def test_a_text_file_is_added_with_a_title_from_its_name_and_the_editor_is_left_alone(self):
        window, form = self.vault_window()
        path = self.put("여름 휴가 후기.txt", "여름 휴가를 다녀왔어요.\n정말 좋았어요.")
        self.type_post(form, "쓰던 글", "쓰던 본문")
        self.picker.paths = [path]
        window.references.edited(form.title_text(), form.body_text())
        self.click(form.save_button)
        self.clock.advance(minutes=1)
        self.picker.paths = [path]
        self.click(form.pick_button)
        self.assertEqual(self.picker.calls, 1)
        self.assertEqual(self.picker.last, (T["ref_pick_title"], f"{T['ref_pick_filter']} (*.txt *.md)"))
        self.assertEqual(self.lt(form.notice), T["ref_done_file"])
        self.assertEqual(len(self.vault_files()), 2)
        shown = self.texts(form)
        self.assertTrue(any("여름 휴가 후기" in line for line in shown), shown)
        self.assertEqual((form.title_input.text(), form.body.toPlainText()), ("쓰던 글", "쓰던 본문"), "올린 글이 편집 칸을 덮지 않는다")
        self.assertEqual(Path(path).read_text(encoding="utf-8"), "여름 휴가를 다녀왔어요.\n정말 좋았어요.", "원본 파일은 그대로다")

    def test_a_cp949_file_adds_the_reading_note(self):
        window, form = self.vault_window()
        self.picker.paths = [self.put("옛 메모장.txt", "옛 메모장 글자 모양으로 저장한 글입니다.".encode("cp949"))]
        self.click(form.pick_button)
        self.assertIn(T["ref_note_cp949"], self.lt(form.notice))
        self.assertEqual(len(self.vault_files()), 1)

    def test_cancelling_the_picker_reads_nothing_and_says_nothing(self):
        window, form = self.vault_window()
        self.click(form.pick_button)
        self.assertEqual(self.picker.calls, 1)
        self.assertEqual((self.message(form), form.notice.isVisibleTo(form)), ("", False))
        self.assertFalse(self.vault.exists())

    def test_refused_files_show_a_fixed_sentence_and_never_the_path_the_name_or_the_text(self):
        window, form = self.vault_window()
        probes = [NAME_MARK, BODY_MARK, str(self.root / "내 글 모음"), "내 글 모음"]                    # 보관함 폴더 위치(안내 글)는 데이터 폴더 경로라 파일을 고른 폴더와 다르다
        cases = {"형식": self.put(NAME_MARK + ".docx", BODY_MARK), "없음": str(self.root / "내 글 모음" / (NAME_MARK + "-없음.txt")), "큰 파일": self.put(NAME_MARK + "-big.txt", b"a" * (2 * 1024 * 1024 + 1)),
                 "이진": self.put(NAME_MARK + "-bin.txt", BODY_MARK.encode("utf-8") + b"\x00"), "빈 파일": self.put(NAME_MARK + "-empty.txt", ""), "비밀": self.put(NAME_MARK + "-key.txt", BODY_MARK + " " + KEY)}
        for label, path in cases.items():
            with self.subTest(label=label):
                self.picker.paths = [path]
                self.click(form.pick_button)
                self.assertTrue(self.message(form), label)
                self.assertTrue(form.message.isVisibleTo(form))
                self.assertEqual(self.outside_editors(window, probes + leak.needles(KEY, size=8)), [], label)
        self.assertEqual(self.vault_files(), [])
        self.assertFalse(self.vault.exists())

    def test_a_file_when_the_vault_is_full_is_refused(self):
        for number in range(50):
            self.add_post(f"글 {number}", "본문", minutes=0)
        window, form = self.vault_window()
        self.picker.paths = [self.put("쉰한째.txt", "본문")]
        self.click(form.pick_button)
        self.assertIn("50개까지만 보관할 수 있어요", self.message(form))
        self.assertEqual(len(self.vault_files()), 50)


# ---- 5) 목록·열기·고치기·저장 -------------------------------------------------------------------------------------------------------
class ListEditTest(Base):
    def three(self):
        return [self.add_post("첫째 글", "첫째 본문", 1), self.add_post("둘째 글", "둘째 본문 입니다", 1), self.add_post("셋째 글", "셋째 본문 입니다 정말로", 1)]

    def test_the_list_is_newest_first_with_title_length_and_korean_time(self):
        first, second, third = self.three()
        window, form = self.vault_window()
        rows = [line for line in self.texts(form) if " · " in line and "자 · " in line]
        self.assertEqual([line.split(" · ")[0] for line in rows], ["셋째 글", "둘째 글", "첫째 글"])
        self.assertEqual(rows[0], "셋째 글 · 13자 · 2026-11-02 10:33", "시계는 UTC 01:30 에서 1분씩 흘렀고 화면에는 한국 시각이 나온다")
        self.assertIn("3개 보관 중", self.texts(form))
        self.assertEqual(len(form.open_buttons), 3)
        names = [button.accessibleName() for button in form.open_buttons]
        self.assertTrue(all(title in name for title, name in zip(("셋째 글", "둘째 글", "첫째 글"), names)), names)

    def test_opening_a_post_fills_the_editor_and_switches_to_the_edit_mode(self):
        first, second, third = self.three()
        window, form = self.vault_window()
        self.click(form.open_buttons[1])
        self.assertEqual((form.title_input.text(), form.body.toPlainText()), ("둘째 글", "둘째 본문 입니다"))
        self.assertEqual(self.lt(form.heading), T["ref_editor_edit"])
        self.assertEqual(self.lt(form.editor_state), T["ref_clean"])
        self.assertTrue(form.delete_button.isEnabled())
        self.assertEqual(window.references.current, second.ref_id)

    def test_edit_then_save_overwrites_the_one_file_keeps_the_creation_time_and_moves_it_to_the_top(self):
        first, second, third = self.three()
        window, form = self.vault_window()
        self.click(form.open_buttons[2])
        self.assertEqual(form.title_input.text(), "첫째 글")
        path = self.vault / f"ref-{first.ref_id}.json"
        before = path.read_bytes()
        form.body.setPlainText("고쳐 쓴 첫째 본문")
        form.title_input.setText("고친 첫째 글")
        self.settle(2)
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])
        self.clock.advance(hours=2)
        self.save(window)
        self.assertEqual(self.lt(form.notice), T["ref_done_saved"])
        saved = ref_service.open_reference(self.ctx, first.ref_id)
        self.assertEqual((saved.title, saved.body, saved.created_at), ("고친 첫째 글", "고쳐 쓴 첫째 본문", first.created_at))
        self.assertGreater(saved.updated_at, first.updated_at)
        self.assertNotEqual(path.read_bytes(), before)
        self.assertEqual(len(self.vault_files()), 3, "고쳐도 파일은 늘지 않는다")
        self.assertEqual([line.split(" · ")[0] for line in self.texts(form) if "자 · " in line][0], "고친 첫째 글", "고친 글이 맨 위로 온다")

    def test_putting_the_text_back_clears_the_unsaved_marker(self):
        self.three()
        window, form = self.vault_window()
        self.click(form.open_buttons[0])
        original = form.body.toPlainText()
        form.body.setPlainText(original + "!")
        self.settle(2)
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])
        form.body.setPlainText(original)
        self.settle(2)
        self.assertEqual(self.lt(form.editor_state), T["ref_clean"])

    def test_broken_files_are_skipped_with_a_count_and_never_touched(self):
        self.three()
        self.vault.mkdir(exist_ok=True)
        (self.vault / "ref-brokenaa.json").write_text("깨진 파일 " + BODY_MARK, encoding="utf-8")
        (self.vault / "ref-brokenbb.json").write_bytes(b"\xff\xfe\x00")
        before = {path.name: path.read_bytes() for path in self.vault.iterdir()}
        window, form = self.vault_window()
        self.assertIn(T["ref_skipped"].format(n=2), self.texts(form))
        self.assertEqual(len(form.open_buttons), 3)
        self.assertEqual({path.name: path.read_bytes() for path in self.vault.iterdir()}, before)
        self.assertEqual(self.outside_editors(window, [BODY_MARK]), [])

    def test_a_post_that_broke_after_listing_shows_a_fixed_sentence_when_opened(self):
        first, = [self.add_post("곧 깨질 글", "본문")]
        window, form = self.vault_window()
        (self.vault / f"ref-{first.ref_id}.json").write_text("깨졌다 " + BODY_MARK, encoding="utf-8")
        self.type_post(form, "쓰던 글", "쓰던 본문")
        window.references.edited(form.title_text(), form.body_text())
        window.references_select(first.ref_id, discard=True)
        self.settle()
        self.assertIn("보관된 글 파일이 올바르지 않아 열지 않았어요", self.message(form))
        self.assertEqual((form.title_input.text(), form.body.toPlainText()), ("쓰던 글", "쓰던 본문"), "열지 못해도 편집 칸은 그대로다")
        self.assertEqual(self.outside_editors(window, [BODY_MARK]), [])

    def test_a_full_vault_refuses_the_fifty_first_post_but_allows_editing(self):
        for number in range(50):
            self.add_post(f"글 {number}", "본문", minutes=0)
        window, form = self.vault_window()
        self.type_post(form, "쉰한째", "본문")
        self.save(window)
        self.assertIn("50개까지만 보관할 수 있어요", self.message(form))
        self.assertEqual(len(self.vault_files()), 50)
        self.click(form.open_buttons[0])
        form.body.setPlainText("고친 본문")
        self.save(window)
        self.assertEqual(self.message(form), "")

    def in_view(self, form, widget):
        """위젯이 스크롤 몸의 보이는 영역 안에 통째로 들어 있는가(보이는 영역의 위·아래 끝 기준)."""
        viewport = form.scroll.viewport()
        top = widget.mapTo(viewport, QPoint(0, 0)).y()
        return top >= 0 and top + widget.height() <= viewport.height()

    def test_opening_a_post_far_down_a_long_list_scrolls_the_title_field_into_view_in_the_smallest_window(self):
        """독립 검증 Q-05 — 글이 12편이고 창이 가장 작을 때(900×560) 8번째 `열기` 를 눌러도 편집 칸이 화면 밖에 있고 포커스는 안 보이는 칸에 있었다."""
        for number in range(12):
            self.add_post(f"글 {number}", f"본문 {number}")
        window, form = self.vault_window(size=(900, 560))
        self.assertEqual(len(form.open_buttons), 12)
        self.assertFalse(self.in_view(form, form.title_input), "처음에는 편집 칸이 목록 아래에 있다(스크롤 전)")
        self.assertEqual(form.scroll.verticalScrollBar().value(), 0)
        self.assertIs(QApplication.focusWidget(), form.title_input, "처음 포커스는 이미 제목 칸에 있다 — 포커스가 옮겨 가며 저절로 스크롤되는 일이 없다(검증자 Q 의 재현과 같은 길)")
        window.references_select(window.references.rows[7].ref_id)
        self.settle(4)
        self.assertGreater(form.scroll.verticalScrollBar().value(), 0, "편집 칸이 보이도록 몸이 스크롤됐다")
        self.assertTrue(self.in_view(form, form.title_input), "제목 칸이 몸의 보이는 영역 안에 있다")
        self.assertIs(QApplication.focusWidget(), form.title_input)
        self.assertEqual(form.title_input.text(), "글 4", "목록은 새 것 먼저 — 8번째가 5번째로 만든 글이다")

    def test_clicking_the_open_button_of_a_far_down_post_also_shows_the_editor(self):
        """마우스로 `열기` 를 누르는 길(눌린 단추가 지워지며 포커스가 옮겨 간다)도 같다."""
        for number in range(12):
            self.add_post(f"글 {number}", f"본문 {number}")
        window, form = self.vault_window(size=(900, 560))
        self.click(form.open_buttons[7])
        self.settle(4)
        self.assertTrue(self.in_view(form, form.title_input))
        self.assertEqual(form.title_input.text(), "글 4")

    def test_the_open_row_is_marked_in_the_visible_text_and_in_the_spoken_name_and_only_that_row(self):
        """검증자 Q-10·변이 Q13 — 열린 글 줄은 파랑뿐 아니라 보이는 글자와 접근 이름 둘 다에 '지금 편집 중' 이 있다."""
        self.add_post("첫째 글", "첫째 본문")
        self.add_post("둘째 글", "둘째 본문")
        window, form = self.vault_window()
        labels = lambda: [label for label in form.rows_host.findChildren(QLabel) if label.isVisibleTo(form)]
        self.assertFalse(any("지금 편집 중" in self.lt(label) + label.accessibleName() for label in labels()))
        self.click(form.open_buttons[0])
        marked = [label for label in labels() if "지금 편집 중" in self.lt(label)]
        self.assertEqual(len(marked), 1)
        self.assertTrue(self.lt(marked[0]).startswith("둘째 글 · "))
        spoken = marked[0].accessibleName()
        self.assertIn(", 지금 편집 중", spoken, "읽어 주는 이름은 쉼표로 이어지는 말이다")
        self.assertNotIn(" · ", spoken, "보이는 글(가운뎃점으로 이어진다)과 같은 글이 아니다")
        self.assertTrue(spoken.startswith("둘째 글, "), spoken)
        others = [label for label in labels() if label is not marked[0]]
        self.assertEqual(len(others), 1)
        self.assertNotIn("지금 편집 중", self.lt(others[0]) + others[0].accessibleName())

    def test_a_post_that_was_deleted_outside_while_open_leaves_its_text_as_an_unsaved_new_post_and_says_so(self):
        """독립 검증 Q-04 — 열어 둔 글이 바깥에서 지워진 뒤 목록을 다시 읽으면(`파일에서 올리기` 가 그 길이다) 편집 칸의 글이 변경 표시 없이 남아 닫기·새 글이 묻지 않고 버렸다."""
        first = self.add_post("첫째 글", "첫째 본문")
        window, form = self.vault_window()
        self.click(form.open_buttons[0])
        form.body.setPlainText("고치던 본문 " + BODY_MARK)
        self.settle(2)
        ref_service.delete_reference(self.ctx, first.ref_id, confirmed=True)                    # 바깥에서 지웠다
        folder = self.root / "내 글 모음"
        folder.mkdir(exist_ok=True)
        (folder / "다른 글.txt").write_text("새로 올린 본문", encoding="utf-8")
        self.picker.paths = [str(folder / "다른 글.txt")]
        self.click(form.pick_button)
        self.assertEqual(self.lt(form.heading), T["ref_editor_new"], "새 글 모습으로 바뀐다")
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"], "칸의 글은 저장 안 한 새 글이다")
        self.assertEqual(self.lt(form.notice), T["ref_done_file"] + " " + T["ref_vanished"])
        self.assertEqual(form.body.toPlainText(), "고치던 본문 " + BODY_MARK, "칸의 글은 그대로다")
        self.assertFalse(form.delete_button.isEnabled())
        self.click(form.close_button)
        self.assertEqual(window.references.pending, ("close",), "확인 없이 닫히지 않는다")
        self.assertIn(T["ref_discard_q_close"], self.texts(form))
        self.click(form.confirm_buttons[-1])
        self.assertEqual(len(self.vault_files()), 1, "올린 파일 하나뿐")
        self.save(window)                                                                         # 저장하면 새 글로 보관된다
        self.assertEqual(len(self.vault_files()), 2)
        self.assertEqual(self.lt(form.notice), T["ref_done_saved"])
        self.assertEqual(self.lt(form.editor_state), T["ref_clean"])

    def test_typing_after_saving_takes_back_the_saved_notice_on_the_screen(self):
        """검증자 Q-09 — 저장한 뒤 다시 고치면 '저장하지 않은 변경이 있어요.' 와 '저장했어요.' 가 한 화면에 같이 남았다."""
        window, form = self.vault_window()
        self.type_post(form, "제목", "본문")
        self.save(window)
        self.assertEqual(self.lt(form.notice), T["ref_done_saved"])
        form.body.insertPlainText("더")
        self.settle(2)
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])
        self.assertFalse(form.notice.isVisibleTo(form), "저장했다는 안내는 거둔다")

    def test_opening_a_post_in_the_default_window_with_a_long_list_also_shows_the_editor(self):
        for number in range(30):
            self.add_post(f"글 {number}", f"본문 {number}")
        window, form = self.vault_window()
        self.assertFalse(self.in_view(form, form.title_input))
        window.references_select(window.references.rows[20].ref_id)
        self.settle(4)
        self.assertTrue(self.in_view(form, form.title_input))
        self.assertEqual(form.title_input.text(), "글 9")


# ---- 5-2) 본문 통일(독립 검증 S-2) — 저장한 글이 곧 편집 칸의 글이다 -------------------------------------------------------------------------
class NormalizeTest(Base):
    """실제 Qt 편집 칸은 줄 끝(CRLF·CR·U+2028·U+2029)·NBSP·맨 앞 BOM 을 바꾼다. 서비스가 저장할 때 같은 것을 통일하므로 열자마자 '저장하지 않은 변경' 이 켜지지 않고, 저장해도 본문이 달라지지 않으며, 목록의 글자 수가 편집 칸의 글자 수와 같다."""
    CR, LF, LS, PS, NBSP, BOM = chr(13), chr(10), chr(0x2028), chr(0x2029), chr(0xA0), chr(0xFEFF)

    def originals(self):
        cr, lf, ls, ps, nbsp, bom = self.CR, self.LF, self.LS, self.PS, self.NBSP, self.BOM
        return ("가" + cr + lf + "나", "가" + cr + "나", "가" + lf + cr + "나", "가" + cr + cr + lf + "나", "가" + ls + "나", "가" + ps + "나", "가" + ls + cr + lf + "나", "가나" + cr + lf, bom + "가", bom + bom + "가", "가" + bom,
                lf + bom + "가", "가" + nbsp + "나", bom + nbsp + "가", "가  " + chr(9) + "나 " + lf, "가" + chr(0x200B) + "나", "가" + chr(0x0B) + chr(0x0C) + chr(0x85) + "나", "가" + chr(0x1F600) + "나",
                "끝 공백  ", lf * 3 + "가" + lf * 3, "가" + chr(7) + "나", "가" + chr(0x3000) + "나", "가" + chr(0x202E) + "나")

    def test_every_kind_of_body_opens_clean_with_the_same_text_and_the_same_count_as_the_list(self):
        originals = self.originals()
        posts = []
        for number, original in enumerate(originals):
            posts.append((self.add_post(f"글 {number}", original, minutes=0), ref_service.normalize_body(original)))
        window, form = self.vault_window()
        for number, (added, expected) in enumerate(posts):
            with self.subTest(body=ascii(expected)):
                window.references_select(added.ref_id, discard=True)
                self.settle(2)
                self.assertEqual(form.body.toPlainText(), expected, "편집 칸의 글 == 저장한 글")
                self.assertFalse(window.references.dirty, "열자마자 '저장하지 않은 변경' 이 켜지면 안 된다")
                self.assertEqual(self.lt(form.editor_state), T["ref_clean"])
                self.assertEqual(self.lt(form.body_count), f"{len(expected)}자")
                row = next(line for line in self.texts(form) if line.startswith(f"글 {number} · "))
                self.assertIn(f" · {len(expected):,}자 · ", row, "목록의 글자 수 == 편집 칸의 글자 수")

    def test_what_the_service_stores_is_a_fixed_point_of_the_edit_box_on_random_strings(self):
        import random
        window, form = self.vault_window()
        alphabet = ["가", "나", " ", chr(9), self.CR, self.LF, self.LS, self.PS, self.NBSP, self.BOM, chr(0x200B), "a"]
        rng = random.Random(20261116)
        for _ in range(400):
            text_ = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 14)))
            stored = ref_service.normalize_body(text_)
            form.body.setPlainText(stored)
            self.assertEqual(form.body.toPlainText(), stored, ascii(text_))

    def test_a_windows_notepad_crlf_file_goes_from_the_file_to_the_list_to_the_editor_and_back_unchanged(self):
        window, form = self.vault_window()
        lines = ["첫 줄입니다.", "둘째 줄입니다.", "", "셋째 줄입니다."]
        source = self.root / "메모장 글.txt"
        source.write_bytes((self.CR + self.LF).join(lines).encode("utf-8") + (self.CR + self.LF).encode("utf-8"))
        expected = self.LF.join(lines) + self.LF
        self.picker.paths = [str(source)]
        self.click(form.pick_button)
        self.assertEqual(self.message(form), "")
        self.assertEqual(len(self.vault_files()), 1)
        row = next(line for line in self.texts(form) if line.startswith("메모장 글 · "))
        self.assertIn(f" · {len(expected)}자 · ", row, "목록은 저장한 글(LF)의 글자 수를 센다 — 예전에는 CRLF 를 두 글자로 세어 편집 칸과 어긋났다")
        self.click(form.open_buttons[0])
        self.assertEqual(form.body.toPlainText(), expected)
        self.assertEqual(self.lt(form.body_count), f"{len(expected)}자")
        self.assertEqual(self.lt(form.editor_state), T["ref_clean"], "윈도 메모장 글을 열자마자 '저장하지 않은 변경이 있어요' 가 켜지던 것이 고쳐졌다")
        self.assertFalse(window.references.dirty)
        self.click(form.close_button)
        self.assertFalse(window.dialog.is_open, "저장 안 한 변경이 없으니 묻지 않고 닫힌다")

    def test_saving_after_only_a_title_change_keeps_the_body_exactly_and_reopening_is_still_clean(self):
        added = self.add_post("옛 제목", "가" + self.CR + self.LF + "나" + self.NBSP + "다")
        window, form = self.vault_window()
        self.click(form.open_buttons[0])
        expected = "가" + self.LF + "나 다"
        self.assertEqual(form.body.toPlainText(), expected)
        form.title_input.setText("새 제목")
        self.settle(2)
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])
        self.clock.advance(hours=1)
        self.save(window)
        self.assertEqual(ref_service.open_reference(self.ctx, added.ref_id).body, expected, "제목만 고쳐 저장해도 본문은 그대로다")
        self.assertEqual(self.lt(form.editor_state), T["ref_clean"])
        self.click(form.new_button)
        self.click(form.open_buttons[0])
        self.assertEqual((form.title_input.text(), form.body.toPlainText()), ("새 제목", expected))
        self.assertFalse(window.references.dirty)

    def test_pasted_text_with_windows_line_ends_is_stored_as_the_editor_shows_it(self):
        window, form = self.vault_window()
        form.title_input.setText("붙여 넣은 글")
        form.body.setPlainText("가" + self.CR + self.LF + "나" + self.CR + self.LF + "다")                 # 칸이 이미 LF 로 바꿨다
        self.settle(2)
        self.save(window)
        stored = ref_service.open_reference(self.ctx, window.references.current)
        self.assertEqual(stored.body, "가" + self.LF + "나" + self.LF + "다")
        self.assertEqual(self.lt(form.body_count), f"{len(stored.body)}자")
        self.assertEqual(self.lt(form.editor_state), T["ref_clean"])

    def test_even_a_provider_that_hands_over_raw_line_ends_opens_clean_because_the_baseline_is_the_text_read_back_from_the_box(self):
        """독립 검증 Q-01 의 화면 쪽 방어 — 서비스의 통일을 거치지 않은 글(가짜 공급자가 날것을 그대로 준다)도 열자마자 '저장하지 않은 변경' 이 켜지지 않는다. 기준이 칸에서 되읽은 글이기 때문이다."""
        cr, lf, ls, ps, nbsp, bom = self.CR, self.LF, self.LS, self.PS, self.NBSP, self.BOM
        raws = ("가" + cr + lf + "나", "가" + cr + "나", "가" + ls + "나", "가" + ps + "나", "가" + nbsp + "나", bom + "가나", bom + bom + "가" + cr + lf, "가" + chr(0x0B) + chr(0x85) + "나", "가나다")
        items = {f"fake{number:04d}": [f"글 {number}", raw, f"2026-11-15T01:0{number}:00Z"] for number, raw in enumerate(raws)}
        provider = FakeReferencesProvider(items)
        window, form = self.vault_window(provider=provider)
        for number, raw in enumerate(raws):
            with self.subTest(raw=ascii(raw)):
                window.references_select(f"fake{number:04d}", discard=True)
                self.settle(2)
                self.assertEqual(window.references.current, f"fake{number:04d}")
                self.assertFalse(window.references.dirty, "열자마자 변경 표시가 켜지면 안 된다")
                self.assertEqual(self.lt(form.editor_state), T["ref_clean"])
                self.assertFalse(form.confirm_buttons)
                self.assertEqual(window.references.leave("close"), "go", "안 고쳤는데 닫기가 묻는다")
                window.references.keep_editing()
                form.body.insertPlainText("x")                                                  # 정말 고치면 표시가 켜진다
                self.settle(2)
                self.assertTrue(window.references.dirty)
                self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])


# ---- 6) 저장 안 한 변경 확인 ---------------------------------------------------------------------------------------------------------
class UnsavedTest(Base):
    def dirty(self):
        first = self.add_post("첫째 글", "첫째 본문")
        second = self.add_post("둘째 글", "둘째 본문")
        window, form = self.vault_window()
        self.click(form.open_buttons[0])                                            # 목록은 새 것 먼저 — 0번이 둘째 글(second)이다
        form.body.setPlainText("고치는 중인 글 " + BODY_MARK)
        self.settle(2)
        return window, form, first, second

    def confirm_names(self, form):
        return [button.accessibleName() for button in form.confirm_buttons]

    def assert_asking(self, window, form, kind):
        self.assertEqual(window.references.pending[0], kind)
        self.assertIn(T["ref_discard_q_" + kind], self.texts(form))
        self.assertEqual(self.confirm_names(form), [T["ref_discard_yes_a11y_" + kind], T["ref_discard_no_a11y"]])
        self.assertFalse(form.scroll.isAncestorOf(form.confirm_host), "확인 줄은 스크롤 밖이라 늘 보인다")
        self.assertTrue(all(button.isVisibleTo(form) for button in form.confirm_buttons))
        for button in (form.save_button, form.new_button, form.pick_button, form.delete_button):
            self.assertFalse(button.isEnabled(), button.accessibleName())
        self.assertTrue(form.close_button.isEnabled())
        self.assertIs(QApplication.focusWidget(), form.confirm_buttons[-1], "처음 포커스는 안전한 쪽(계속 고치기)")

    def test_opening_another_post_asks_first_and_keep_editing_loses_nothing(self):
        window, form, first, second = self.dirty()
        self.click(form.open_buttons[1])
        self.assert_asking(window, form, "select")
        self.assertEqual(window.references.current, second.ref_id, "물은 동안 아무것도 바뀌지 않았다")
        self.assertEqual(form.body.toPlainText(), "고치는 중인 글 " + BODY_MARK)
        self.click(form.confirm_buttons[-1])
        self.assertIsNone(window.references.pending)
        self.assertEqual(form.confirm_buttons, [])
        self.assertEqual(form.body.toPlainText(), "고치는 중인 글 " + BODY_MARK)
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])
        self.assertIs(QApplication.focusWidget(), form.title_input)
        self.assertTrue(all(button.isEnabled() for button in (form.save_button, form.new_button, form.pick_button, form.delete_button)))

    def test_opening_another_post_after_choosing_to_discard_replaces_the_editor(self):
        window, form, first, second = self.dirty()
        self.click(form.open_buttons[1])
        self.click(form.confirm_buttons[0])
        self.assertEqual((form.title_input.text(), form.body.toPlainText()), ("첫째 글", "첫째 본문"))
        self.assertEqual(window.references.current, first.ref_id)
        self.assertIsNone(window.references.pending)
        self.assertEqual(self.lt(form.editor_state), T["ref_clean"])
        self.assertEqual(ref_service.open_reference(self.ctx, second.ref_id).body, "둘째 본문", "버린 변경은 저장되지 않았다")

    def test_new_post_asks_first_then_empties_the_editor_on_yes(self):
        window, form, first, second = self.dirty()
        self.click(form.new_button)
        self.assert_asking(window, form, "new")
        self.click(form.confirm_buttons[0])
        self.assertEqual((form.title_input.text(), form.body.toPlainText(), window.references.current, window.references.mode), ("", "", None, "new"))
        self.assertEqual(self.lt(form.heading), T["ref_editor_new"])

    def test_the_close_button_asks_first(self):
        window, form, first, second = self.dirty()
        self.click(form.close_button)
        self.assert_asking(window, form, "close")
        self.assertTrue(window.dialog.is_open)
        self.click(form.confirm_buttons[-1])
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(form.body.toPlainText(), "고치는 중인 글 " + BODY_MARK)
        self.click(form.close_button)
        self.click(form.confirm_buttons[0])
        self.assertFalse(window.dialog.is_open)
        self.assertIsNone(window.references_form)

    def test_escape_asks_first_and_a_second_escape_keeps_editing(self):
        window, form, first, second = self.dirty()
        QTest.keyClick(form.body, Qt.Key_Escape)
        self.settle()
        self.assertTrue(window.dialog.is_open, "저장 안 한 변경이 있는데 Esc 가 확인 없이 닫았다")
        self.assert_asking(window, form, "close")
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertIsNone(window.references.pending, "묻는 중의 Esc 는 닫지 않고 계속 고치는 쪽이다")
        self.assertEqual(form.body.toPlainText(), "고치는 중인 글 " + BODY_MARK)
        QTest.keyClick(form.title_input, Qt.Key_Escape)
        self.settle()
        self.assert_asking(window, form, "close")
        self.click(form.confirm_buttons[0])
        self.assertFalse(window.dialog.is_open)

    def test_escape_closes_at_once_when_nothing_is_unsaved_and_gives_the_focus_back(self):
        self.add_post("글", "본문")
        window = self.make()
        window.style_open()
        self.settle()
        window.style_form.refs_button.setFocus(Qt.TabFocusReason)
        self.settle(2)
        window.style_form.refs_button.click()
        self.settle(8)
        form = window.references_form
        self.click(form.open_buttons[0])
        QTest.keyClick(form.body, Qt.Key_Escape)
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertIsNone(window.references_form)

    def test_the_window_close_x_and_alt_f4_ask_first_and_the_window_stays(self):
        window, form, first, second = self.dirty()
        window.close()
        self.settle()
        self.assertTrue(window.isVisible(), "창 닫기가 저장 안 한 변경을 확인 없이 버렸다")
        self.assert_asking(window, form, "quit")
        self.assertEqual(form.body.toPlainText(), "고치는 중인 글 " + BODY_MARK)
        self.click(form.confirm_buttons[-1])
        self.assertTrue(window.isVisible())
        self.assertIsNone(window.references.pending)
        window.close()
        self.settle()
        self.assertTrue(window.isVisible())
        self.click(form.confirm_buttons[0])
        self.assertFalse(window.isVisible(), "버리고 닫기를 누르면 창이 닫힌다")
        self.assertIsNone(window.references_form)

    def test_the_window_close_is_not_held_when_nothing_is_unsaved(self):
        self.add_post("글", "본문")
        window, form = self.vault_window()
        self.click(form.open_buttons[0])
        window.close()
        self.settle()
        self.assertFalse(window.isVisible())

    def test_saving_first_then_leaving_asks_nothing(self):
        window, form, first, second = self.dirty()
        self.save(window)
        self.assertEqual(window.references.pending, None)
        self.click(form.close_button)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(ref_service.open_reference(self.ctx, second.ref_id).body, "고치는 중인 글 " + BODY_MARK)

    def test_the_question_replaces_an_old_message_and_notice(self):
        window, form, first, second = self.dirty()
        self.type_post(form, "", "본문")
        self.save(window)
        self.assertTrue(self.message(form))
        self.click(form.close_button)
        self.assertEqual(self.message(form), "")
        self.assertFalse(form.notice.isVisibleTo(form))

    def delete_gives_way(self, label):
        window, form, first, second = self.dirty()
        self.click(form.delete_button)
        self.assertIn(T["ref_delete_q1"], self.texts(form))
        self.assertEqual(window.references.delete_step, 1)
        kind = {"열기": "select", "닫기": "close", "창 닫기": "quit"}[label]
        if label == "열기":
            self.click(form.open_buttons[1])
        elif label == "닫기":
            self.click(form.close_button)
        else:
            window.close()
            self.settle()
            self.assertTrue(window.isVisible(), "창이 확인 없이 닫혔다")
        self.assert_asking(window, form, kind)
        self.assertNotIn(T["ref_delete_q1"], self.texts(form), "지우기 확인은 그만두었다 — 질문은 하나")
        self.assertEqual(window.references.delete_step, 0)
        self.assertFalse(any(button.accessibleName() == T["ref_delete_no_a11y"] for button in self.buttons(form)))
        self.assertEqual(form.body.toPlainText(), "고치는 중인 글 " + BODY_MARK)
        self.assertEqual(self.vault_files(), sorted([f"ref-{first.ref_id}.json", f"ref-{second.ref_id}.json"]), "아무것도 지워지지 않았다")
        self.click(form.confirm_buttons[-1])                                                  # 계속 고치기 — 다시 평소 모습이고 글은 그대로
        self.assertIsNone(window.references.pending)
        self.assertEqual(form.body.toPlainText(), "고치는 중인 글 " + BODY_MARK)
        self.assertTrue(form.delete_button.isEnabled())

    def test_a_delete_question_that_is_open_gives_way_to_opening_another_post_and_only_that_question_is_shown(self):
        """독립 검증 Q-03 — 지우기 확인이 열린 채 `열기`를 누르면 질문이 둘 쌓여 화면에는 지우기 확인 하나만 보였다."""
        self.delete_gives_way("열기")

    def test_a_delete_question_that_is_open_gives_way_to_the_close_button(self):
        """독립 검증 Q-03 — 지우기 확인이 열린 채 `닫기` 를 눌러도 아무 변화가 없어 보였다(`그만두기` 를 눌러야 두 번째 질문이 나타났다)."""
        self.delete_gives_way("닫기")

    def test_a_delete_question_that_is_open_gives_way_to_the_window_close_x(self):
        """독립 검증 Q-03 — 지우기 확인이 열린 채 창 X·Alt+F4 를 눌러도 창이 안 닫히는 이유가 안 보였다."""
        self.delete_gives_way("창 닫기")


# ---- 7) 지우기 --------------------------------------------------------------------------------------------------------------------
class DeleteTest(Base):
    def open_one(self):
        first = self.add_post("첫째 글", "첫째 본문")
        second = self.add_post("둘째 글", "둘째 본문")
        window, form = self.vault_window()
        self.click(form.open_buttons[0])                                            # 목록은 새 것 먼저 — 0번이 둘째 글(second)이다
        return window, form, first, second

    def test_the_delete_button_is_off_until_a_post_is_open(self):
        self.add_post("글", "본문")
        window, form = self.vault_window()
        self.assertFalse(form.delete_button.isEnabled())
        self.click(form.open_buttons[0])
        self.assertTrue(form.delete_button.isEnabled())

    def test_two_steps_and_nothing_is_deleted_before_the_second_confirmation(self):
        window, form, first, second = self.open_one()
        self.click(form.delete_button)
        self.assertEqual(self.vault_files(), sorted([f"ref-{first.ref_id}.json", f"ref-{second.ref_id}.json"]))
        self.assertIn(T["ref_delete_q1"], self.texts(form))
        self.assertEqual([button.text() for button in form.confirm_buttons], [T["ref_delete_next"], T["ref_delete_no"]])
        self.assertFalse(form.scroll.isAncestorOf(form.confirm_host))
        self.assertIs(QApplication.focusWidget(), form.confirm_buttons[-1], "처음 포커스는 그만두기")
        for button in (form.save_button, form.new_button, form.pick_button, form.delete_button):
            self.assertFalse(button.isEnabled())
        self.click(form.confirm_buttons[0])
        self.assertIn(T["ref_delete_q2"], self.texts(form))
        self.assertEqual([button.text() for button in form.confirm_buttons], [T["ref_delete_yes"], T["ref_delete_no"]])
        self.assertEqual(len(self.vault_files()), 2, "두 번째 확인 전에는 지우지 않는다")
        self.assertIs(QApplication.focusWidget(), form.confirm_buttons[-1])
        self.click(form.confirm_buttons[0])
        self.assertEqual(self.vault_files(), [f"ref-{first.ref_id}.json"], "열려 있던 둘째 글 파일 하나만 사라졌다")
        self.assertEqual(self.lt(form.notice), T["ref_done_deleted"])
        self.assertEqual((form.title_input.text(), form.body.toPlainText(), window.references.current), ("", "", None))
        self.assertFalse(form.delete_button.isEnabled())
        self.assertEqual(len(form.open_buttons), 1)
        self.assertIs(QApplication.focusWidget(), form.title_input)

    def cancel_after(self, steps):
        window, form, first, second = self.open_one()
        self.click(form.delete_button)
        for _ in range(steps):
            self.click(form.confirm_buttons[0])
        self.click(form.confirm_buttons[-1])
        self.assertEqual(len(self.vault_files()), 2, "그만두면 아무것도 안 지워진다")
        self.assertEqual(form.confirm_buttons, [])
        self.assertIs(QApplication.focusWidget(), form.delete_button)
        self.assertTrue(all(button.isEnabled() for button in (form.save_button, form.new_button, form.pick_button, form.delete_button)))
        self.assertEqual((window.references.current, window.references.delete_step), (second.ref_id, 0))
        self.assertEqual((form.title_input.text(), form.body.toPlainText()), ("둘째 글", "둘째 본문"))

    def test_cancelling_at_the_first_step_deletes_nothing_and_gives_the_focus_back(self):
        self.cancel_after(0)

    def test_cancelling_at_the_second_step_deletes_nothing_and_gives_the_focus_back(self):
        self.cancel_after(1)

    def test_escape_cancels_only_the_delete_question_not_the_dialog(self):
        window, form, first, second = self.open_one()
        self.click(form.delete_button)
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertEqual((window.references.delete_step, len(self.vault_files())), (0, 2))
        self.click(form.delete_button)
        self.click(form.confirm_buttons[0])
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertEqual((window.references.delete_step, len(self.vault_files())), (0, 2))

    def test_enter_on_the_focused_safe_button_cancels(self):
        window, form, first, second = self.open_one()
        self.click(form.delete_button)
        self.assertIs(QApplication.focusWidget(), form.confirm_buttons[-1])
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Return)
        self.settle()
        self.assertEqual((window.references.delete_step, len(self.vault_files())), (0, 2))

    def test_a_delete_that_fails_shows_a_fixed_sentence_without_the_path(self):
        window, form, first, second = self.open_one()
        self.click(form.delete_button)
        self.click(form.confirm_buttons[0])
        with mock.patch.object(Path, "unlink", side_effect=PermissionError(errno.EACCES, "접근 거부 " + NAME_MARK, str(self.root / NAME_MARK))):
            self.click(form.confirm_buttons[0])
        self.assertEqual(self.message(form), T["ref_fail_delete"], "지우기가 실패했는데 '저장하지 못했습니다' 라고 말하지 않는다")
        self.assertEqual(len(self.vault_files()), 2)
        self.assertEqual(self.outside_editors(window, [NAME_MARK, "접근 거부", str(self.root / NAME_MARK)]), [])
        self.assertEqual(window.references.delete_step, 0)

    def test_only_the_second_confirmation_button_looks_dangerous(self):
        """변이 Q11 — 1단계의 `계속` 은 보통 모양이고 2단계의 `지우기` 만 위험한(빨강) 모양이다."""
        window, form, first, second = self.open_one()
        self.click(form.delete_button)
        self.assertEqual(form.confirm_buttons[0].property("kind"), "secondary")
        self.click(form.confirm_buttons[0])
        self.assertEqual(form.confirm_buttons[0].property("kind"), "danger")
        self.assertEqual(form.confirm_buttons[0].text(), T["ref_delete_yes"])
        self.assertEqual(form.confirm_buttons[1].property("kind"), "ghost", "그만두기는 조용한 모양")

    def test_after_a_failed_delete_the_focus_goes_back_to_the_title_field(self):
        """변이 Q16 — 지우기가 거절되면 포커스가 사라진 확인 줄에 남지 않고 제목 칸으로 돌아온다."""
        window, form, first, second = self.open_one()
        self.click(form.delete_button)
        self.click(form.confirm_buttons[0])
        with mock.patch.object(Path, "unlink", side_effect=PermissionError(errno.EACCES, "접근 거부", str(self.root / NAME_MARK))):
            self.click(form.confirm_buttons[0])
        self.assertTrue(self.message(form))
        self.assertIs(QApplication.focusWidget(), form.title_input)

    def test_the_delete_button_is_not_reachable_by_a_stale_answer_after_the_dialog_was_closed(self):
        window, form, first, second = self.open_one()
        self.click(form.delete_button)
        self.click(form.confirm_buttons[0])
        window.close_dialog()
        self.settle()
        self.assertIsNone(window.references_delete_next())
        self.assertEqual(len(self.vault_files()), 2)


# ---- 8) 오류 문장에 글이 없다 --------------------------------------------------------------------------------------------------------
class ErrorTextTest(Base):
    def test_a_failed_write_shows_the_fixed_sentence_keeps_the_text_and_repeats_nothing(self):
        window, form = self.vault_window()
        self.type_post(form, TITLE_MARK, "본문 " + BODY_MARK)
        probes = [BODY_MARK, str(self.root / NAME_MARK), "I/O 오류", NAME_MARK]                      # 제목은 편집 칸에만 있어야 하고 목록 줄에는 저장된 뒤에야 나온다 — 저장이 안 됐으니 목록에도 없다
        with mock.patch.object(context_module.os, "replace", side_effect=OSError(errno.EIO, "I/O 오류 " + NAME_MARK, str(self.root / NAME_MARK))):
            self.save(window)
        self.assertEqual(self.message(form), "파일을 저장하지 못했어요: 「참고 글 보관함 폴더」.")
        self.assertEqual((form.title_input.text(), form.body.toPlainText()), (TITLE_MARK, "본문 " + BODY_MARK), "저장하지 못해도 글은 편집 칸에 남아 다시 해 볼 수 있다")
        self.assertEqual(self.outside_editors(window, probes + [TITLE_MARK]), [], "저장이 안 됐으니 제목도 목록에 없다 — 편집 칸에만 있다")
        self.assertEqual(self.vault_files(), [], "임시 파일도 남지 않았다")
        self.save(window)
        self.assertEqual(self.message(form), "")
        self.assertEqual(len(self.vault_files()), 1)

    def test_a_full_disk_has_its_own_fixed_sentence(self):
        window, form = self.vault_window()
        self.type_post(form, "제목", "본문 " + BODY_MARK)
        with mock.patch.object(context_module.os, "write", side_effect=OSError(errno.ENOSPC, "꽉 참 " + NAME_MARK, str(self.root / NAME_MARK))):
            self.save(window)
        self.assertEqual(self.message(form), "저장 공간이 부족합니다.")
        self.assertEqual(self.outside_editors(window, [BODY_MARK, NAME_MARK, "꽉 참"]), [])

    def test_a_list_that_cannot_be_read_stops_saying_loading_and_the_read_again_button_brings_it_back(self):
        """독립 검증 Q-06 — 목록을 못 읽으면 '읽는 중이에요…' 가 계속 남고 다시 읽을 길이 없었다. 진짜 서비스로: 보관함 자리에 폴더가 아닌 파일이 있으면 서비스가 목록을 거절한다."""
        self.vault.parent.mkdir(parents=True, exist_ok=True)
        self.vault.write_text("not a folder", encoding="utf-8")
        window, form = self.vault_window()
        shown = self.texts(form)
        self.assertNotIn(T["ref_list_loading"], shown, "읽는 중에 멈춰 있으면 안 된다")
        self.assertIn(T["ref_fail_load"], shown)
        self.assertNotIn(T["ref_list_empty"], shown, "읽지 못한 것을 '비어 있다' 고 말하지 않는다")
        self.assertTrue(self.message(form), "서비스의 고정 거절 문장도 상태 줄에 보인다")
        self.assertTrue(form.reload_button.isVisibleTo(form))
        self.assertTrue(form.reload_button.isEnabled())
        self.assertEqual((form.reload_button.text(), form.reload_button.accessibleName()), (T["ref_reload"], T["ref_reload_a11y"]))
        self.assertGreaterEqual(form.reload_button.height(), tokens.SIZE["hit"])
        self.assertNotEqual(form.reload_button.focusPolicy(), Qt.NoFocus)
        self.assertNotIn(str(self.root), self.message(form), "거절 문장에는 경로가 되풀이되지 않는다(폴더 위치 안내는 따로 있다)")
        self.vault.unlink()                                                                    # 문제를 풀고 다시 읽는다
        self.click(form.reload_button)
        self.assertIn(T["ref_list_empty"], self.texts(form))
        self.assertNotIn(T["ref_fail_load"], self.texts(form))
        self.assertEqual(self.message(form), "", "앞의 거절 문장이 남지 않는다")
        self.assertFalse(form.reload_button.isVisibleTo(form))
        self.assertIs(QApplication.focusWidget(), form.title_input)

    def test_reading_again_that_fails_again_keeps_the_button_and_the_focus_on_it(self):
        self.vault.parent.mkdir(parents=True, exist_ok=True)
        self.vault.write_text("not a folder", encoding="utf-8")
        window, form = self.vault_window()
        form.reload_button.setFocus(Qt.TabFocusReason)
        self.click(form.reload_button)
        self.assertTrue(form.reload_button.isVisibleTo(form))
        self.assertIn(T["ref_fail_load"], self.texts(form))
        self.assertTrue(self.message(form))
        self.assertTrue(form.reload_button.hasFocus() or QApplication.focusWidget() is form.reload_button)
        self.assertEqual(self.vault.read_text(encoding="utf-8"), "not a folder", "읽기는 아무것도 바꾸지 않는다")

    def test_no_text_stays_in_the_screen_rules_state_or_the_adapter_after_a_whole_session(self):
        window, form = self.vault_window()
        probes = leak.needles(BODY_MARK, TITLE_MARK, size=8)
        self.type_post(form, TITLE_MARK, BODY_MARK + " 하나")
        self.save(window)
        self.type_post(form, TITLE_MARK + "-2", BODY_MARK + " 둘")
        self.save(window)
        window.references_new()
        self.settle()
        body_probes = leak.needles(BODY_MARK, size=8)
        self.assertEqual(leak.graph_hits(window.references, body_probes, skip=(window.references.provider,)), [], "화면 규칙의 상태에는 글(본문)이 없다 — 지문과 목록 줄의 제목·글자 수뿐이다")
        self.assertEqual([row.title for row in window.references.rows], [TITLE_MARK + "-2"], "목록 줄의 제목은 있다(목록에 보여야 하므로)")
        window.close_dialog()
        self.settle()
        self.assertEqual(leak.widget_hits(window, probes), [], "닫으면 편집 칸도 목록도 비워진다")


# ---- 9) 낡은 결과·닫기 --------------------------------------------------------------------------------------------------------------
class StaleAndCloseTest(Base):
    def test_a_result_from_before_the_dialog_was_closed_is_not_shown_in_the_next_one(self):
        self.add_post("지금 있는 글", "본문")
        window, form = self.vault_window()
        old = window.references.begin()
        listing = rv.RefListing((rv.RefRow("zzzzzzzz", "낡은 결과의 글", 3, "2026-11-15T01:00:00Z"),))
        window.close_dialog()
        self.settle()
        form2 = self.open_vault(window)
        self.assertFalse(window.references.apply_list(old, listing), "닫기 전 번호의 결과는 받지 않는다")
        self.assertFalse(window.references.apply_opened(old, rv.OpenedRef("zzzzzzzz", "낡은", "낡은 본문")))
        self.assertFalse(window.references.apply_failed(old, "낡은 실패"))
        form2.refresh()
        self.assertFalse(any("낡은" in line for line in self.texts(form2)))
        self.assertEqual(len(form2.open_buttons), 1)

    def test_calls_after_the_dialog_is_gone_do_nothing(self):
        window, form = self.vault_window()
        window.close_dialog()
        self.settle()
        for call in (window.references_save, window.references_new, window.references_pick, window.references_delete, window.references_delete_next, window.references_close, window.references_escape,
                     window.references_discard_yes, window.references_discard_no, lambda: window.references_select("aaaaaaaa")):
            self.assertIsNone(call())
        self.assertFalse(window.references_guard_quit())
        self.assertFalse(self.vault.exists())

    def test_closing_by_any_way_wipes_the_editor_and_the_list(self):
        for how in ("button", "escape", "other_dialog", "window"):
            with self.subTest(how=how):
                self.add_post("글 " + how, "본문")
                window, form = self.vault_window()
                self.type_post(form, TITLE_MARK, BODY_MARK)
                window.references.edited("", "")                                   # 저장 안 한 변경 확인은 다른 시험이 본다 — 여기서는 곧바로 닫는다
                window.references.dirty = False
                if how == "button":
                    self.click(form.close_button)
                elif how == "escape":
                    QTest.keyClick(form.body, Qt.Key_Escape)
                elif how == "other_dialog":
                    window.show_sample_info()
                else:
                    window.close()
                self.settle()
                self.assertIsNone(window.references_form)
                self.assertFalse(window.references.is_open)
                self.assertEqual((form.library, form.open_buttons), (None, []))
                self.assertEqual((form.title_input.text(), form.body.toPlainText()), ("", ""))
                self.assertFalse(form.body.document().isUndoAvailable(), "되돌리기 기록까지 지웠다")
                self.assertEqual(leak.widget_hits(window, leak.needles(BODY_MARK, TITLE_MARK, size=8)), [])
                window.close()

    def test_reopening_starts_clean(self):
        self.add_post("글", "본문")
        window, form = self.vault_window()
        self.type_post(form, "", "본문")
        self.save(window)
        self.assertTrue(self.message(form))
        window.references.dirty = False
        window.close_dialog()
        self.settle()
        form2 = self.open_vault(window)
        self.assertEqual((self.message(form2), form2.notice.isVisibleTo(form2), form2.title_input.text(), form2.body.toPlainText()), ("", False, "", ""))
        self.assertEqual((window.references.mode, window.references.current, window.references.dirty, window.references.pending), ("new", None, False, None))

    def test_the_generation_grows_with_every_open_and_close(self):
        window = self.make()
        numbers = []
        for _ in range(3):
            self.open_vault(window)
            numbers.append(window.references.generation)
            window.close_dialog()
            self.settle()
            numbers.append(window.references.generation)
        self.assertEqual(numbers, sorted(set(numbers)))


# ---- 10) 크기 ---------------------------------------------------------------------------------------------------------------------
class FitTest(Base):
    def check_fit(self, window, form, label):
        dialog = window.dialog
        self.assertTrue(window.rect().contains(dialog.geometry()), (label, dialog.geometry(), window.rect()))
        self.assertEqual(form.scroll.horizontalScrollBar().maximum(), 0, label)
        self.assertEqual(ui_offscreen.find_clipping(dialog), [], label)
        self.assertEqual(ui_offscreen.find_squeezed(dialog), [], label)
        for button in self.buttons(form):
            if not form.scroll.isAncestorOf(button):
                bottom = button.mapTo(window, button.rect().bottomRight())
                self.assertTrue(window.rect().contains(bottom) and button.isVisible(), (label, button.accessibleName()))
        for name in ("editor_state", "message", "notice"):
            widget = getattr(form, name)
            if widget.isVisibleTo(form):
                self.assertTrue(window.rect().contains(widget.mapTo(window, widget.rect().bottomRight())), (label, name, "상태 줄이 창 밖이다"))
        for button in form.confirm_buttons:
            self.assertTrue(window.rect().contains(button.mapTo(window, button.rect().bottomRight())), (label, "확인 단추가 창 밖이다"))

    def test_every_state_fits_every_size_without_clipping_scrolling_sideways_or_hiding_the_buttons(self):
        for number in range(12):
            self.add_post("가" * 80 if number == 0 else f"참고 글 {number}", LONG_BODY * 40 if number % 3 == 0 else "짧은 본문")
        for size in SIZES:
            with self.subTest(size=size):
                window, form = self.vault_window(size=size)
                self.check_fit(window, form, (size, "열자마자"))
                self.click(form.open_buttons[-1])
                self.check_fit(window, form, (size, "긴 제목 열기"))
                form.body.setPlainText(form.body.toPlainText() + " 고침")
                self.settle(2)
                self.click(form.open_buttons[0])
                self.check_fit(window, form, (size, "버릴지 묻기"))
                self.click(form.confirm_buttons[-1])
                self.type_post(form, "", "본문")
                self.save(window)
                self.check_fit(window, form, (size, "거절 문장"))
                self.type_post(form, "제목", "본문")
                self.save(window)
                self.click(form.delete_button)
                self.check_fit(window, form, (size, "지우기 1단계"))
                self.click(form.confirm_buttons[0])
                self.check_fit(window, form, (size, "지우기 2단계"))
                self.click(form.confirm_buttons[-1])
                form.body.setPlainText("저장 안 한 글 " + "가" * 60)
                self.settle(2)
                window.references_guard_quit()
                self.settle(8)
                self.check_fit(window, form, (size, "창 닫기 확인"))
                window.close()

    def test_an_eighty_character_title_and_a_long_message_fit_in_the_minimum_window(self):
        window, form = self.vault_window(size=(900, 560))
        self.type_post(form, "가" * 80, "나" * 100_001)
        self.save(window)
        self.assertTrue(self.message(form))
        self.check_fit(window, form, "긴 거절 문장")


# ---- 11) 시간 ---------------------------------------------------------------------------------------------------------------------
class SpeedTest(Base):
    def test_a_one_hundred_thousand_character_post_opens_and_saves_without_a_noticeable_freeze(self):
        """동기 호출이 느린지 재 둔 숫자의 안전망 — 10만 자 글 한 편을 열고 고쳐 저장하는 데 몇 초씩 걸리면 여기서 걸린다(이 PC 에서 열기 0.3초·저장 0.4초 안팎이었다)."""
        added = self.add_post("큰 글", LONG_BODY * 1000)
        self.assertGreater(len(ref_service.open_reference(self.ctx, added.ref_id).body), 50_000)
        window, form = self.vault_window()
        started = time.perf_counter()
        self.click(form.open_buttons[0])
        opened = time.perf_counter() - started
        form.body.insertPlainText("고침")
        started = time.perf_counter()
        self.save(window)
        saved = time.perf_counter() - started
        self.assertEqual(self.message(form), "")
        self.assertLess(opened, 5.0, f"열기 {opened:.2f}초")
        self.assertLess(saved, 5.0, f"저장 {saved:.2f}초")

    def test_typing_in_a_big_post_updates_the_marker_quickly(self):
        added = self.add_post("큰 글", LONG_BODY * 1000)
        window, form = self.vault_window()
        self.click(form.open_buttons[0])
        started = time.perf_counter()
        for _ in range(10):
            form.body.insertPlainText("가")
        per_key = (time.perf_counter() - started) / 10
        self.assertLess(per_key, 0.5, f"글자 하나 입력에 {per_key * 1000:.0f}ms")
        self.assertEqual(self.lt(form.editor_state), T["ref_dirty"])


# ---- 12) 소스 규칙 ----------------------------------------------------------------------------------------------------------------
class SourceTest(unittest.TestCase):
    def test_the_dialog_module_has_no_file_network_process_or_output_calls(self):
        import ast
        source = (ROOT / "src" / "chanceblog_desktop" / "ui" / "qt" / "references_dialog.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        banned = {"os", "pathlib", "socket", "subprocess", "urllib", "http", "logging", "tempfile", "shutil", "json", "sqlite3", "threading"}
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)
        called = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(called & {"print", "open", "eval", "exec"})
        self.assertFalse({name for name in called if name.split(".")[-1] in ("unlink", "write_text", "write_bytes", "mkdir", "rmdir", "replace", "rename", "setStyleSheet")})
        self.assertNotIn(chr(0x7E), source)
        self.assertNotIn("http", source)

    def test_the_shell_methods_use_only_the_screen_rules_and_the_dialog(self):
        import ast
        source = (ROOT / "src" / "chanceblog_desktop" / "ui" / "qt" / "shell.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith(("references_", "_references_"))]
        self.assertGreaterEqual(len(methods), 14)
        for method in methods:
            for node in ast.walk(method):
                if isinstance(node, ast.Call):
                    self.assertNotIn(ast.unparse(node.func), {"open", "print", "os.remove", "os.replace", "subprocess.run"}, method.name)
        self.assertNotIn("from ..service import references", source)
        self.assertNotIn("from ...service import references", source)


if __name__ == "__main__":
    unittest.main()
