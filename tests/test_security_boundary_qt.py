"""UI 메시지 위치의 화면 쪽 시험(Qt, offscreen) — 처리 실패·안내(토스트)·설정 화면 오류·처리하지 못한 예외 훅·Qt 메시지 핸들러로 이름 11개의 카나리를 흘려 위젯 글 전수에 새는 것 0 을 확인한다(PCSEC1 H1).

**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — D-32). 창을 화면에 띄우지 않는다(`QT_QPA_PLATFORM=offscreen`). 사용자의 클립보드·보관소·데이터 폴더를 건드리지 않는다(가짜 클립보드·가짜 공급자).
UI 글이 위젯에 닿는 길이 백 곳이 넘어(`setText` 161곳) 위젯 글을 한 점에서 가릴 수는 없다 — 그래서 화면에 동적 글을 만드는 쪽(뷰모델: `ui/core/text.py` 의 `display_text` 한 곳)에서 가리고, 이 시험이 **위젯 트리 전체의 글**
(글·툴팁·접근 이름·플레이스홀더·창 제목·동적 속성 — 숨겨진 위젯 포함)을 훑어 그것이 실제로 지켜지는지 확인한다.
가짜 비밀은 `CANARY_` 로 시작하는 문자열을 런타임에 만든다. 이 시험은 실행 환경의 `sys.excepthook` 을 건드리지 않고 되돌린다.
"""
import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import key_leak_support as leak  # noqa: E402
import secret_support as sec  # noqa: E402
from test_security_boundary_matrix import NAMES, canary_of, carrier  # noqa: E402

from chanceblog_desktop.security import boundary  # noqa: E402
from chanceblog_desktop.ui.core import services  # noqa: E402
from chanceblog_desktop.ui.core.jobs import JobFailure  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6 import QtCore
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import shell as shell_module


class FailingHome(services.HomeProvider):
    message = ""

    def load_home(self, progress, cancelled):
        raise JobFailure(self.message, code=self.message)


class FailingConnections(services.ConnectionsProvider):
    message = ""

    def load_connections(self, progress, cancelled):
        raise JobFailure(self.message, code=self.message)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class UiMessageScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def setUp(self):
        self.assertIsNone(boundary.active(), "다른 시험이 경계를 깔아 둔 채 끝났다")
        self.errors = []
        hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: self.errors.append(kind.__name__)                 # 슬롯 안의 예외도 시험이 잡는다
        self.addCleanup(setattr, sys, "excepthook", hook)
        self.addCleanup(self._uninstall)

    @staticmethod
    def _uninstall():
        installed = boundary.active()
        if installed is not None:
            installed.uninstall()

    def tearDown(self):
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def window(self, provider=None, connections=None):
        window = shell_module.AppShell(provider or services.FakeHomeProvider(), connections=connections, autoload=False, clipboard=lambda text: True)
        window.resize(1366, 768)
        window.show()
        self.addCleanup(window.close)
        ui_offscreen.settle(self.app, 4)
        return window

    def widget_text(self, window):
        return "\n".join(text for _label, text in leak.widget_texts(window))

    def check_all_names(self, label, produce):
        """이름마다 카나리를 흘려(`produce(window 글)`) 위젯 글 전수에 카나리가 없는지 본다 — 샌 이름이 있으면 이름만 알려 실패한다."""
        for name in NAMES:
            canary = canary_of(name)
            text = carrier(name, canary, "assign")
            output = produce(text)
            with self.subTest(place=label, name=name):
                sec.assert_no_secret(self, canary, output, f"{label}의 위젯 글 — {name}")

    def test_a_failed_home_load_shows_no_name_anywhere_in_the_widget_tree(self):
        provider = FailingHome()
        window = self.window(provider)

        def produce(text):
            provider.message = text
            window.reload()
            self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10))
            ui_offscreen.settle(self.app, 4)
            self.assertEqual(window.state.list_state, "error")
            return self.widget_text(window)

        self.check_all_names("홈 오류 화면", produce)

    def test_a_failed_connections_load_shows_no_name_anywhere_in_the_widget_tree(self):
        provider = FailingConnections()
        window = self.window(connections=provider)
        window.go("settings")

        def produce(text):
            provider.message = text
            window.reload_connections()
            self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.conn_state not in ("loading",) and not window.state.conn_loading, 10))
            ui_offscreen.settle(self.app, 4)
            self.assertEqual(window.state.conn_state, "error")
            return self.widget_text(window)

        self.check_all_names("설정 화면 오류", produce)

    def test_a_toast_message_with_a_name_is_masked_before_it_is_drawn(self):
        window = self.window()

        def produce(text):
            window.toast.policy.expire()
            window.notify(text)
            ui_offscreen.settle(self.app, 2)
            return window.toast.text() + "\n" + self.widget_text(window)

        self.check_all_names("토스트", produce)

    def test_the_global_exception_hook_masks_its_line_and_the_notice(self):
        window = self.window()
        for name in NAMES:
            canary = canary_of(name)
            stream = io.StringIO()
            hook = qapp.make_excepthook(window, stream)
            hook(RuntimeError, RuntimeError("슬롯 안의 오류 " + carrier(name, canary, "assign")), None)
            with self.subTest(name=name):
                sec.assert_no_secret(self, canary, stream.getvalue() + "\n" + window.toast.text(), f"화면 예외 훅의 한 줄과 안내 — {name}")
                self.assertIn("RuntimeError", stream.getvalue())

    def test_the_qt_message_handler_masks_messages_qt_prints_itself(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            handle = boundary.install_qt_message_handler()
            try:
                for name in NAMES:
                    QtCore.qWarning("qt.test 경고 " + carrier(name, canary_of(name), "assign"))
            finally:
                handle.uninstall()
        out = err.getvalue()
        self.assertIn("qt.test", out, "핸들러가 메시지를 표준 오류로 보냈다")
        for name in NAMES:
            sec.assert_no_secret(self, canary_of(name), out, f"Qt 메시지 핸들러 — {name}")
        self.assertFalse(handle.active)


if __name__ == "__main__":
    unittest.main()
