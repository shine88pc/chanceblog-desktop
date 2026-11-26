"""'진단 정보 복사' 단추(L3 의 F035, 결정 D-539 에서 D-541)와 연결 오류에서도 보이는 정보 카드(F022·F040)의 PySide6 시험 — 창을 화면에 띄우지 않는다(offscreen).
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 사용자의 클립보드·보관소·데이터 폴더는 건드리지 않는다(가짜 클립보드·가짜 공급자·임시 폴더의 가짜 보관소).

지키는 것:
  1) 설정 > 정보 카드에 `진단 정보 복사` 단추가 하나 있고(접근 이름·36px 이상·아이콘·담기는 것 안내 한 줄), 누르면(마우스·Space·Enter) **기존 복사 길**로 정해진 글 하나가 복사되고 안내가 뜬다.
  2) 복사되는 글은 머리 한 줄 + 다섯 칸이고 윈도 빌드·배율은 앱 틀이 읽거나 주입받은 값이다 — 못 읽으면 그 칸만 `unknown`, 클립보드가 실패하거나 예외를 내도 앱은 계속된다.
  3) 설정 화면이 오류 상태여도 버전·커밋·시험 안내와 복사 단추가 오류 카드 바로 아래에 보인다(접이식 없이, 진단 정보 보기는 하나뿐) — 나아지면 정보 묶음 안으로 옮겨 가 단추는 늘 하나다.
  4) 읽는 중·빈 상태와 다른 화면(홈·주제 후보·초안·Seed·블로그)은 건드리지 않았고 버전 글은 어느 화면·어느 상태에서나 사이드바에 보인다(사실표). 앱 틀 없이 만든 정보 카드에는 복사 단추·안내가 없다.
     홈 새 구역 하나만 못 읽은 경우도 그 구역의 코드가 복사된다(홈 전체는 읽었는데도 — 검증 S 의 SP-3).
  5) 실제 어댑터로 열고 눌러도 파일·보관소가 바뀌지 않고 복사된 글에 이름·폴더·키가 없다. 가장 좁은 창에서도 글자 잘림·가로 스크롤이 없다.
"""
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from chanceblog_desktop.ui import adapters  # noqa: E402  (PySide6 를 모르는 부분 — PySide6 가 없어도 불러온다)
from chanceblog_desktop.ui.core import jobs, services, settings_view as sv, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core.version import VersionInfo  # noqa: E402

import test_ui_diagnostics_core as pure  # noqa: E402  (순수 시험의 모양 전수 규칙·가짜 금지 값을 그대로 쓴다)

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()                       # 창을 띄우지 않는다(offscreen) + 윈도 글꼴 폴더
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QLabel, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module

import service_support as support  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402

VERSION = VersionInfo("v0.1.0-preview.1", "file", "abcdef0", "개인 PC 제한 시험용, 미서명 Package")
PLAIN = VersionInfo("v0.1.0-preview.1", "file")
ENV = {"windows_build": 22631, "scale_percent": 150}
EXPECTED = "ChanceBlog Desktop 진단 정보\nversion: v0.1.0-preview.1\ncommit: abcdef0\nwindows_build: 22631\ndisplay_scale: 150%\nlast_error_code: none"
SIZES = ((1440, 900), (1366, 768), (1280, 720), (900, 560))
GOOGLE_KEY = "AI" + "za" + "SyD4e7Kq9ZmW2xV8bN5tR1cY6uH3jL0pGfA1B"[:35]            # 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)
GITHUB_KEY = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


class Clip:
    """가짜 클립보드 — 받은 글을 모두 적어 두고 정해 둔 결과(성공·실패)를 돌려준다."""

    def __init__(self, result=True):
        self.texts, self.result = [], result

    def __call__(self, value):
        self.texts.append(value)
        return self.result


class Flaky(services.ConnectionsProvider):
    """처음 몇 번은 실패하고 그 뒤에는 정상으로 돌아오는 공급자(다시 시도 시험)."""

    def __init__(self, failures=1, code="SAMPLE_DOWN"):
        self.failures, self.code, self.calls = failures, code, 0

    def load_connections(self, progress, cancelled):
        self.calls += 1
        if self.calls <= self.failures:
            raise jobs.JobFailure("연결 설정을 읽는 중 끊겼어요.", code=self.code)
        return services.FakeConnectionsProvider().load_connections(progress, cancelled)


class Static(services.ConnectionsProvider):
    def __init__(self, data):
        self.data, self.calls = data, 0

    def load_connections(self, progress, cancelled):
        self.calls += 1
        return self.data


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def setUp(self):
        self.errors, self.clip = [], Clip()
        self._hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: self.errors.append(f"{kind.__name__}: {value}")        # 화면 슬롯 안의 예외도 시험이 잡는다

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def make(self, connections=None, size=(1440, 900), settings=True, wait=True, home=None, **shell_kwargs):
        shell_kwargs.setdefault("clipboard", self.clip)
        shell_kwargs.setdefault("environment", lambda: dict(ENV))
        shell_kwargs.setdefault("version_info", VERSION)
        window = shell_module.AppShell(home or services.FakeHomeProvider(), connections=connections or services.FakeConnectionsProvider(), autoload=False, **shell_kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)
        if settings:
            window.go("settings")
            if wait:
                self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10))
            self.settle()
        return window

    def focus(self, widget):
        widget.window().activateWindow()
        ui_offscreen.wait_until(self.app, widget.window().isActiveWindow, 2)
        widget.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), widget)

    @staticmethod
    def copy_buttons(window):
        return [b for b in window.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["diag_copy"]]

    @staticmethod
    def accordions(window):
        return {accordion.key: accordion for accordion in window.screen_widget.findChildren(UI.Accordion)}

    @staticmethod
    def labels(window):
        return [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]

    def open_info(self, window):
        info = self.accordions(window)["info"]
        if not info.is_open:
            info.flip()
        self.settle()
        return info


class CopyButtonTest(Base):
    def test_the_info_card_has_one_named_big_enough_copy_button_with_an_icon_and_a_wrapped_note(self):
        window = self.make()
        info = self.open_info(window)
        buttons = self.copy_buttons(window)
        self.assertEqual(len(buttons), 1)
        button = buttons[0]
        self.assertTrue(button.isVisible())
        self.assertEqual((button.text(), button.accessibleName(), button.property("focus_key")), ("진단 정보 복사", "진단 정보 복사", "diag-copy"))
        self.assertFalse(button.icon().isNull())
        self.assertGreaterEqual(button.height(), tokens.SIZE["hit"])
        self.assertGreaterEqual(button.width(), tokens.SIZE["hit"])
        self.assertTrue(info.body.isAncestorOf(button))
        notes = [label for label in info.body.findChildren(UI.Label) if label.plain_text() == text.T["diag_copy_note"]]
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].wordWrap())
        self.assertTrue(notes[0].isVisible())
        self.assertEqual(ui_offscreen.find_clipping(window), [])

    def test_pressing_it_copies_exactly_the_report_once_through_the_existing_clipboard_and_says_so(self):
        window = self.make()
        self.open_info(window)
        button = self.copy_buttons(window)[0]
        QTest.mouseClick(button, Qt.LeftButton)
        self.settle(2)
        self.assertEqual(self.clip.texts, [EXPECTED])
        self.assertTrue(window.toast.isVisible())
        self.assertEqual((window.toast.text(), window.toast.accessibleName()), (text.T["diag_copy_done"], text.T["diag_copy_done"]))
        self.assertEqual(window.toast.property("level"), "")
        self.assertTrue(button.isEnabled())
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.clip.texts, [EXPECTED, EXPECTED])                                       # 누를 때마다 같은 글 — 누적하거나 바뀌지 않는다
        self.assertFalse(window.dialog.is_open)
        self.assertFalse(window.drawer.is_open)

    def test_space_and_enter_press_it_from_the_keyboard_and_tab_comes_to_it_right_after_the_diagnostic_toggle(self):
        window = self.make()
        self.open_info(window)
        toggle = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["diag_show"] and b.isVisible())
        self.focus(toggle)
        toggle.focusNextChild()
        self.settle(2)
        button = self.copy_buttons(window)[0]
        self.assertIs(QApplication.focusWidget(), button)                                             # 진단 정보 보기 다음 정거장이 복사 단추다
        QTest.keyClick(button, Qt.Key_Space)
        self.assertEqual(len(self.clip.texts), 1)
        QTest.keyClick(button, Qt.Key_Return)
        self.assertEqual(self.clip.texts, [EXPECTED, EXPECTED])

    def test_a_package_build_and_a_plain_run_differ_only_in_the_commit_line(self):
        plain = self.make(version_info=PLAIN)
        self.open_info(plain)
        QTest.mouseClick(self.copy_buttons(plain)[0], Qt.LeftButton)
        self.assertEqual(self.clip.texts[-1].split("\n")[1:3], ["version: v0.1.0-preview.1", "commit: unknown"])
        dev = self.make(version_info=VersionInfo("개발 버전", "dev"))
        self.open_info(dev)
        QTest.mouseClick(self.copy_buttons(dev)[0], Qt.LeftButton)
        self.assertEqual(self.clip.texts[-1].split("\n")[1:3], ["version: dev", "commit: unknown"])

    def test_a_clipboard_that_fails_or_raises_gives_the_failure_notice_with_the_error_line_and_the_app_goes_on(self):
        for label, clipboard in (("실패", Clip(False)), ("예외", mock.Mock(side_effect=RuntimeError("클립보드가 막혔다")))):
            window = self.make(clipboard=clipboard)
            self.open_info(window)
            button = self.copy_buttons(window)[0]
            QTest.mouseClick(button, Qt.LeftButton)
            self.settle(2)
            self.assertEqual((window.toast.text(), window.toast.property("level")), (text.T["diag_copy_failed"], "error"), label)
            self.assertTrue(button.isEnabled(), label)
            self.assertEqual(window.state.page, "settings", label)
            window.close()

    def test_an_environment_that_cannot_be_read_only_blanks_its_own_lines(self):
        def broken():
            raise OSError("읽을 수 없다")

        for label, environment in (("예외", broken), ("None", lambda: None), ("빈 값", lambda: {}), ("이상한 값", lambda: {"windows_build": pure.WINDOWS_PATH, "scale_percent": pure.MESSAGE}),
                                   ("범위 밖", lambda: {"windows_build": 7, "scale_percent": 9999})):
            clip = Clip()
            window = self.make(clipboard=clip, environment=environment)
            self.open_info(window)
            QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
            self.assertEqual(clip.texts[-1].split("\n")[1:], ["version: v0.1.0-preview.1", "commit: abcdef0", "windows_build: unknown", "display_scale: unknown", "last_error_code: none"], label)
            window.close()

    def test_the_real_environment_reading_makes_a_well_shaped_report_and_takes_the_scale_from_the_window_screen(self):
        clip = Clip()
        window = self.make(clipboard=clip, environment=None)
        self.open_info(window)
        QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
        pure.assert_shape(self, clip.texts[-1])
        self.assertRegex(clip.texts[-1], r"windows_build: (?:unknown|[0-9]{3,6})\n")
        self.assertRegex(clip.texts[-1], r"display_scale: (?:unknown|[0-9]{2,3}%)\n")
        if sys.platform == "win32":
            self.assertRegex(clip.texts[-1], r"windows_build: [0-9]{4,6}\n")                              # 윈도에서는 실제 빌드 번호가 읽혀야 한다(리눅스는 `unknown`)

        class Screen:
            def __init__(self, ratio):
                self.ratio = ratio

            def devicePixelRatio(self):
                if isinstance(self.ratio, Exception):
                    raise self.ratio
                return self.ratio

        for ratio, shown in ((1.5, "150%"), (1.25, "125%"), (2.0, "200%"), (RuntimeError("화면 없음"), "unknown"), (float("nan"), "unknown"), (None, "unknown")):
            with mock.patch.object(shell_module.AppShell, "screen", lambda self, r=ratio: Screen(r)):
                self.assertEqual(window._read_environment()["scale_percent"], {"150%": 150, "125%": 125, "200%": 200}.get(shown), ratio)
                window.copy_diagnostics()
            self.assertIn(f"display_scale: {shown}\n", clip.texts[-1], ratio)

    def test_the_last_error_code_of_a_failed_read_is_copied_and_its_message_and_the_time_are_not(self):
        window = self.make(Flaky(failures=1, code="SAMPLE_DOWN"))
        self.assertEqual(window.state.conn_state, "error")
        button = self.copy_buttons(window)[0]
        QTest.mouseClick(button, Qt.LeftButton)
        sent = self.clip.texts[-1]
        pure.assert_shape(self, sent)
        self.assertEqual(sent.split("\n")[-1], "last_error_code: SAMPLE_DOWN")
        self.assertNotIn("끊겼어요", sent)
        self.assertNotRegex(sent, r"\d{4}-\d\d-\d\d|\d\d:\d\d")


class ErrorStateTest(Base):
    def test_the_error_screen_shows_the_version_the_commit_the_notice_and_the_copy_button_without_an_accordion(self):
        window = self.make(Flaky(failures=1, code="SAMPLE_DOWN"))
        self.assertEqual(window.state.conn_state, "error")
        labels = self.labels(window)
        self.assertIn("버전", labels)
        self.assertIn("v0.1.0-preview.1 · 커밋 abcdef0", labels)
        self.assertIn("개인 PC 제한 시험용, 미서명 Package", labels)
        self.assertEqual(self.accordions(window), {})                                                  # 접이식 묶음이 아니라 바로 보이는 카드
        button = self.copy_buttons(window)[0]
        self.assertTrue(button.isVisible())
        retry = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.text() == text.T["retry"])
        self.assertGreater(button.mapTo(window.screen_widget, button.rect().topLeft()).y(), retry.mapTo(window.screen_widget, retry.rect().bottomLeft()).y())       # 오류 카드 바로 아래
        version_label = next(w for w in window.screen_widget.findChildren(UI.Label) if w.plain_text() == "v0.1.0-preview.1 · 커밋 abcdef0")
        self.assertTrue(version_label.isVisible())
        card = button.parentWidget()
        self.assertTrue(card.isAncestorOf(version_label) and card.isAncestorOf(button))                # 버전 줄과 단추가 같은 카드 안에 있다
        self.assertEqual(card.property("card"), "true")

    def test_the_error_screen_still_has_one_diagnostic_toggle_one_note_and_one_copy_note_and_the_code_stays_folded(self):
        window = self.make(Flaky(failures=1, code="SAMPLE_DOWN"))
        self.assertEqual(len(window.screen_widget.findChildren(UI.Disclosure)), 1)
        self.assertEqual(self.labels(window).count(text.T["diag_note"]), 1)
        self.assertEqual(self.labels(window).count(text.T["diag_copy_note"]), 1)
        self.assertEqual(len([b for b in window.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["diag_show"]]), 1)
        visible = " ".join(label.text() for label in window.screen_widget.findChildren(QLabel) if label.isVisible())
        self.assertNotIn("SAMPLE_DOWN", visible)                                                      # 오류 코드는 접어 둔 진단 정보에만(복사하면 글에 들어간다)
        self.assertIn("버전", visible)

    def test_retrying_moves_the_card_into_the_folded_info_group_and_there_is_always_exactly_one_copy_button(self):
        provider = Flaky(failures=1, code="SAMPLE_DOWN")
        window = self.make(provider)
        self.assertEqual(len(self.copy_buttons(window)), 1)
        retry = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.text() == text.T["retry"])
        QTest.mouseClick(retry, Qt.LeftButton)
        ui_offscreen.wait_until(self.app, lambda: provider.calls == 2 and not window.state.conn_loading, 10)
        self.settle()
        self.assertEqual((window.state.conn_state, len(self.accordions(window))), ("normal", 5))
        button = self.copy_buttons(window)[0]
        self.assertEqual(len(self.copy_buttons(window)), 1)
        self.assertFalse(button.isVisible())                                                           # 접힌 정보 묶음 안 — 펴야 보인다
        info = self.open_info(window)
        self.assertTrue(button.isVisible())
        self.assertTrue(info.body.isAncestorOf(button))
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.clip.texts[-1].split("\n")[-1], "last_error_code: none")                 # 나아진 오류는 담기지 않는다

    def test_a_failure_after_a_good_read_shows_the_card_again_and_the_report_carries_the_new_code(self):
        window = self.make()
        self.assertEqual(window.state.conn_state, "normal")
        window.state.apply_conn_failure(jobs.JobFailure("다시 끊겼어요.", code="LATER_DOWN"), window.clock.now())
        window.render()
        self.settle()
        self.assertEqual(window.state.conn_state, "error")
        QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
        self.assertEqual(self.clip.texts[-1].split("\n")[-1], "last_error_code: LATER_DOWN")

    def test_the_loading_and_empty_screens_are_not_touched_and_have_no_copy_button_or_info_card(self):
        loading = self.make(services.FakeConnectionsProvider(delay=30), wait=False)                  # 창을 닫으면 읽기도 취소된다 — 바쁜 PC 에서도 읽는 중 모습을 볼 시간이 있게 넉넉히
        self.assertEqual(loading.state.conn_state, "loading")
        self.assertEqual((self.copy_buttons(loading), self.accordions(loading)), ([], {}))
        self.assertNotIn("버전", self.labels(loading))
        empty = self.make(Static(services.ConnectionsData(purposes=(), sample=True)))
        self.assertEqual(empty.state.conn_state, "empty")
        self.assertEqual((self.copy_buttons(empty), self.accordions(empty)), ([], {}))
        self.assertNotIn("버전", self.labels(empty))

    def test_partial_and_offline_screens_keep_their_info_group_with_one_copy_button(self):
        for scenario in ("partial", "offline"):
            window = self.make(services.FakeConnectionsProvider(scenario))
            self.assertEqual(len(self.accordions(window)), 5, scenario)
            self.assertEqual(len(self.copy_buttons(window)), 1, scenario)
            self.open_info(window)
            QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
            self.assertEqual(self.clip.texts[-1], EXPECTED, scenario)
            window.close()


class FactTableTest(Base):
    """사실표 — 버전 글은 어느 화면·어느 상태에서나 사이드바에 보이고, 복사 단추는 설정 화면(정보 카드·오류 카드)에만 있다."""

    @staticmethod
    def sidebar_version(window):
        return window.sidebar.findChild(QFrame, "brandcard").version_label

    def test_the_sidebar_shows_the_version_on_every_screen_and_the_other_screens_have_no_copy_button(self):
        window = self.make(settings=False)
        for page in ("home", "topics", "drafts", "posts", "history", "seed", "blogs", "settings"):    # 의도적 갱신(글 흐름 1a, D-633): 글 검토 메뉴가 초안 작성 다음에 올랐다 / 의도적 갱신(글 흐름 1b, D-651): 발행 기록이 다음 단계 목록에서 실제 메뉴로 올라 글 검토 다음에 놓였다(메뉴 여덟)
            window.go(page)
            ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 10)
            self.settle()
            self.assertEqual(window.state.page, page)
            shown = self.sidebar_version(window)
            self.assertTrue(shown.isVisible(), page)
            self.assertEqual(shown.text(), VERSION.text, page)
            if page != "settings":
                self.assertEqual([b for b in window.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["diag_copy"]], [], page)

    def test_the_sidebar_shows_the_version_in_the_error_states_of_home_and_settings_too_and_the_home_error_has_no_copy_button(self):
        home = self.make(settings=False, home=services.FakeHomeProvider("error"))
        home.reload()
        ui_offscreen.wait_until(self.app, lambda: home.state.list_state != "loading", 10)
        self.settle()
        self.assertEqual(home.state.list_state, "error")
        self.assertEqual((self.sidebar_version(home).isVisible(), self.sidebar_version(home).text()), (True, VERSION.text))
        self.assertEqual([b for b in home.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["diag_copy"]], [])
        settings = self.make(Flaky(failures=1))
        self.assertEqual(settings.state.conn_state, "error")
        self.assertEqual((self.sidebar_version(settings).isVisible(), self.sidebar_version(settings).text()), (True, VERSION.text))

    def test_the_sidebar_version_stays_inside_the_window_even_at_the_smallest_size(self):
        """'늘 보인다' 가 보이는 상태만이 아니라 창 안에 그려진다는 뜻이다 — 가장 작은 창(900×560)에서도 사이드바 아래의 버전 글이 창 밖으로 잘려 나가지 않는다."""
        for size in (SIZES[0], SIZES[-1]):
            window = self.make(size=size)
            window.go("home")
            self.settle()
            label = self.sidebar_version(window)
            top_left, bottom_right = label.mapTo(window, label.rect().topLeft()), label.mapTo(window, label.rect().bottomRight())
            self.assertTrue(label.isVisible(), size)
            self.assertGreaterEqual(top_left.y(), 0, size)
            self.assertLessEqual(bottom_right.y(), window.height(), size)
            self.assertLessEqual(bottom_right.x(), window.width(), size)
            window.close()

    def test_the_home_error_is_a_failure_that_the_copied_report_names_by_its_code(self):
        window = self.make(home=services.FakeHomeProvider("error"))
        window.go("home")
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        self.settle()
        self.assertEqual(window.state.list_state, "error")
        window.go("settings")
        ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 10)
        self.settle()
        self.open_info(window)
        QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
        self.assertEqual(self.clip.texts[-1].split("\n")[-1], "last_error_code: SAMPLE_NETWORK_DOWN")        # 다른 화면의 오류도 설정 > 정보에서 복사하면 담긴다

    def test_a_home_board_section_that_could_not_be_read_is_named_by_its_code_in_the_copied_report_though_the_whole_home_loaded(self):
        """홈 전체는 읽었지만 새 구역 하나(추천 채널)를 못 읽은 경우 — 구역마다 따로 성공·실패해서 홈의 `failure` 는 비어 있다. 설정 > 정보에서 복사하면 그 구역의 코드가 담기고 안내 문장·채널 이름은 담기지 않는다(검증 S 의 SP-3)."""
        channels = (services.ChannelRead("A", name="채널 가", enabled=True, state="failed", failure=services.ServiceFailure("추천을 읽지 못했어요.", code="SAMPLE_BOARD_DOWN")),
                    services.ChannelRead("B", name="채널 나", enabled=True))
        window = self.make(home=services.FakeHomeProvider(board=services.BoardData(channels=channels, sample=True)))
        window.go("home")
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        self.settle()
        self.assertNotEqual(window.state.list_state, "error")                                          # 홈 전체는 읽었다 — 구역 하나만 못 읽었다
        self.assertIsNone(window.state.failure)
        window.go("settings")
        ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 10)
        self.settle()
        self.open_info(window)
        QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
        sent = self.clip.texts[-1]
        pure.assert_shape(self, sent)
        self.assertEqual(sent.split("\n")[-1], "last_error_code: SAMPLE_BOARD_DOWN")
        for piece in ("추천을 읽지 못했어요", "채널 가", "채널 나"):
            self.assertNotIn(piece, sent, piece)

    def test_an_info_card_built_without_the_app_shell_has_no_copy_button_and_no_copy_note_while_the_same_card_with_a_shell_has_one_of_each(self):
        """문서(UI_STATES·UI_COMPONENTS)의 '앱 틀이 없으면 단추와 안내가 없다 — 눌러도 할 일이 없는 단추는 만들지 않는다' 를 못박는다(검증 S 의 SP-11 — `if shell is not None:` 를 `if True:` 로 바꾼 변이를 잡는다)."""
        info = sv.info_vm(None, True, None, VERSION)
        window = self.make(settings=False)
        for with_diag in (True, False):
            for shell, expected in ((None, 0), (window, 1)):
                frame = S.info_card(info, shell, with_diag=with_diag)
                self.addCleanup(frame.deleteLater)
                buttons = [b for b in frame.findChildren(QAbstractButton) if text.T["diag_copy"] in (b.text(), b.accessibleName())]
                notes = [label for label in frame.findChildren(UI.Label) if label.plain_text() == text.T["diag_copy_note"]]
                self.assertEqual((len(buttons), len(notes)), (expected, expected), (with_diag, shell is None))


class LayoutTest(Base):
    def test_no_clipped_text_and_no_horizontal_scroll_in_the_error_state_and_the_opened_info_group_at_every_size(self):
        for size in SIZES:
            for label, provider in (("오류", Flaky(failures=1)), ("정상", None)):
                window = self.make(provider, size=size)
                if provider is None:
                    self.open_info(window)
                ui_offscreen.wait_until(self.app, lambda w=window: w.scroll.horizontalScrollBar().maximum() == 0, 2)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, (label, size))
                self.assertEqual(ui_offscreen.find_clipping(window), [], (label, size))
                self.assertTrue(self.copy_buttons(window)[0].isVisible(), (label, size))
                window.close()


class SafetyTest(Base):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = support.make_ctx(self.tmp.name, repo="")
        self.store = self.ctx.keystore
        for purpose, name, fields in (("naver_apihub", "내 키", {"client_id": "hubclient001", "client_secret": GOOGLE_KEY}), ("image_provider", "이미지 키", {"access_key": GITHUB_KEY}),
                                      ("ai_assist", "보조 키", {"key": GOOGLE_KEY[::-1]})):
            cn.add_entry(self.ctx, purpose, name=name, fields=fields, keystore=self.store)
        self.provider = adapters.ServiceConnectionsProvider(context_factory=lambda data_dir=None: self.ctx)

    def test_copying_with_the_real_adapter_changes_no_file_and_no_stored_key_and_holds_no_name_path_or_key(self):
        before, blobs = support.tree_snapshot(self.ctx.workspace.root), dict(self.store._blobs)
        window = self.make(self.provider)
        self.assertEqual(window.state.conn_state, "normal")
        for accordion in window.screen_widget.findChildren(UI.Accordion):
            if not accordion.is_open:
                accordion.flip()
        self.settle()
        QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
        QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
        self.assertEqual(support.tree_snapshot(self.ctx.workspace.root), before)                       # 새 파일도 바뀐 파일도 없다
        self.assertEqual(self.store._blobs, blobs)
        sent = self.clip.texts[-1]
        pure.assert_shape(self, sent)
        self.assertEqual(sent, EXPECTED)
        root = str(self.ctx.workspace.root)
        for piece in ("내 키", "이미지 키", "보조 키", "hubclient001", GOOGLE_KEY[:8], GITHUB_KEY[:8], root, self.tmp.name, Path(self.tmp.name).name, "AppData", "Users"):
            self.assertNotIn(piece, sent, piece)

    def test_no_widget_text_tooltip_or_accessible_name_of_the_screen_holds_the_report_or_a_key(self):
        window = self.make(self.provider)
        for accordion in window.screen_widget.findChildren(UI.Accordion):
            if not accordion.is_open:
                accordion.flip()
        self.settle()
        QTest.mouseClick(self.copy_buttons(window)[0], Qt.LeftButton)
        parts = [w.text() for w in window.findChildren(QLabel)] + [w.text() for w in window.findChildren(QAbstractButton)]
        parts += [w.accessibleName() + " " + w.accessibleDescription() + " " + w.toolTip() for w in window.findChildren(QWidget)]
        everything = " ".join(parts)
        for piece in ("last_error_code", "windows_build", "display_scale", GOOGLE_KEY[:12], GITHUB_KEY[:12]):
            self.assertNotIn(piece, everything, piece)                                                  # 복사되는 글은 화면 어디에도 그려지지 않는다


if __name__ == "__main__":
    unittest.main()
