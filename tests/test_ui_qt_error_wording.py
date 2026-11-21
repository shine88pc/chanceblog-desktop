"""홈이 못 읽혀 오류 카드가 뜰 때 사용자가 실제로 보는 글(L4 — F028 명령줄 말투, 결정 D-544) — 창을 띄우지 않고(offscreen) 카드의 글자를 읽는다.

**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 순수 규칙(카드 글에 명령·옵션·파일 이름이 없다·꼬리가 나뉘어 있다)은 `test_errors_wording.py` 가 PySide6 없이 모든 코드에 대어 본다.

지키는 것:
  · 서비스 오류(`AppError`)가 홈 카드로 올라올 때 카드에는 쉬운 말의 사용자 문구와 하실 일의 앞부분만 보이고, 명령줄 꼬리(`명령줄·개발자 안내:` 와 그 뒤의 명령)는 보이지 않는다.
  · 카드에는 실제 화면 이름(`설정 → 백업·복원`)이 보인다.
  · 같은 카드의 다시 시도 단추와 접어 둔 진단 정보는 그대로 있다(글만 바뀌었다).
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from chanceblog_desktop.errors import CLI_TAIL_LABEL, AppError  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import text  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtWidgets import QAbstractButton, QLabel
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import shell as shell_module


def failing_factory(code, slots):
    def factory(data_dir=None):
        raise AppError(code, slots)

    return factory


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ErrorCardWordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def setUp(self):
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: self.errors.append(f"{kind.__name__}: {value}")

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def card(self, code, slots):
        """그 오류로 홈을 못 읽은 창을 만들고 카드의 글자(모든 라벨)를 읽는다."""
        provider = adapters.ServiceHomeProvider(context_factory=failing_factory(code, slots))
        window = shell_module.AppShell(provider, autoload=False, clipboard=lambda _text: True)
        window.resize(1440, 900)
        window.show()
        self.addCleanup(window.close)
        window.reload()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10))
        ui_offscreen.settle(self.app, 6)
        self.assertEqual(window.state.list_state, "error")
        labels = [(label.plain_text() if hasattr(label, "plain_text") else label.text()) for label in window.screen_widget.findChildren(QLabel)]
        return window, " ".join(labels)

    def test_a_short_error_shows_its_plain_words_and_no_command(self):
        window, shown = self.card("KEY_ENTRY_LIMIT", {"용도": "이미지", "개수": "3"})
        self.assertIn("키 항목을 「3」개까지만 둘 수 있어요.", shown)
        self.assertIn("쓰지 않는 항목을 지운 뒤 다시 더해 주세요.", shown)
        for hidden in (CLI_TAIL_LABEL, "keys remove", "--yes", "명령줄"):
            self.assertNotIn(hidden, shown)
        self.assertIn(text.T["retry"], [button.text() for button in window.screen_widget.findChildren(QAbstractButton)], "다시 시도 단추는 그대로")
        self.assertEqual(window.state.failure.code, "KEY_ENTRY_LIMIT")

    def test_a_long_error_shows_the_real_backup_card_name_and_no_command(self):
        window, shown = self.card("CANDIDATE_CORRUPT", {"번호": "bad00000"})
        self.assertIn("후보 번호 「bad00000」", shown)
        self.assertIn("설정 → 백업·복원", shown)
        for hidden in (CLI_TAIL_LABEL, "candidates", "--yes", "명령줄"):
            self.assertNotIn(hidden, shown)
        self.assertEqual(window.state.failure.code, "CANDIDATE_CORRUPT", "오류 코드는 진단 정보용으로 그대로 남는다")

    def test_the_text_on_the_card_is_the_text_the_adapter_made(self):
        _window, shown = self.card("STORE_RECOVERY_PENDING", {"파일": "chanceblog.db"})
        expected = adapters.failure_from(AppError("STORE_RECOVERY_PENDING", {"파일": "chanceblog.db"})).user_message
        self.assertIn(expected[:60], shown)
        self.assertIn("앱을 한 번 열면 끝내지 못한 저장을 자동으로 되돌려 정리해요.", expected)


if __name__ == "__main__":
    unittest.main()
