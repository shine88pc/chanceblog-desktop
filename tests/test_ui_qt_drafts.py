"""초안 작성 화면의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 메뉴·후보 상세의 `이 주제로 만들기`·편집기·제목 후보·오른쪽 칸·확인 권장·복사 단추와 복사 피드백·복사 전 확인창들·떠날 때/닫을 때 확인·폭 규칙과 최소 창·Tab 순서·접근 이름·
읽기 전용 증명을 확인한다. **PySide6 가 없으면 Qt 시험은 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_drafts_core`·`test_ui_drafts_service`·`test_service_draft_engine`, 이 파일의 `SourceRulesTest` 는 PySide6 없이도 돈다).
사용자의 클립보드·브라우저·보관소·데이터 폴더·설정 파일은 건드리지 않는다(가짜 클립보드·가짜 열기 함수·가짜 공급자·임시 폴더의 실제 서비스). 후보·이름은 모두 지어낸 낱말이다.

지키는 것:
  1) 메뉴에 `초안 작성` 이 핵심 작업 묶음(주제 후보 다음)으로 올라 있고 '다음 단계' 에는 발행 기록만 남는다. 후보 없이 열면 안내 한 줄과 `주제 후보로 가기` 단추만 있다. 후보 상세 아래 고정 줄의 주요 단추 `이 주제로 만들기` 는 안전 판정 중지 후보·네이버가 아닌 채널의 후보에서 꺼져 있고 까닭이 글로 보인다.
  2) **복사는 사용자가 단추를 눌렀을 때만**(초안 만들기·창 열기·검사·고치기로 클립보드를 바꾸지 않는다). 복사 전 관문: 키 모양은 막고(안내창 하나) 이 글에만 해당하는 확인 권장·분야 못 읽음·점검 걸림·거의 안 고침은 확인창(처음 포커스는 취소 — 취소하면 복사 0)이 먼저다.
     복사한 글은 편집기의 글 그대로이고 단추가 1.8초 `✓ … 복사됨`(성공색 + 글자)으로 보였다 돌아온다. 옛 확인창의 단추가 새 확인창에 남지 않는다(F-H1).
  3) 고친 내용은 확인 없이 사라지지 않는다: 다른 화면으로 가기·`다시 만들기`·다른 제목 후보 고르기·앱 닫기 앞에 확인창(처음 포커스는 취소). 글을 칠 때는 화면 전체를 다시 그리지 않는다(입력기 조합이 사라지지 않는다).
  4) 열기·만들기·고치기·검사·복사·다시 만들기 어느 것도 파일을 하나도 안 바꾼다(임시 폴더 전체 바이트). 네트워크·키 보관소를 부르지 않고 `네이버 글쓰기 열기` 는 `https://blog.naver.com/` 주소 하나만 연다.
  5) 가로 스크롤·글자 잘림이 없고(필수 크기와 최소 창) 오른쪽 칸은 창 논리 폭 1280 이상에서 옆에, 미만에서 아래에 있다. Tab 은 이름 있는 곳만 지나고 편집기에서 빠져나온다. 사이드바가 최소 창에 들어간다.
"""
import ast
import dataclasses
import datetime
import importlib.util
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from test_ui_drafts_core import CATALOG, KEY_SHAPED, SOFTWARE, GENERIC, APPLIANCE, STOPPED, OTHER_CHANNEL  # noqa: E402
from test_ui_drafts_service import Bomb, NoNetwork, Setup  # noqa: E402

from chanceblog_desktop.ui.core import candidates as cd  # noqa: E402
from chanceblog_desktop.ui.core import drafts, services, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core.clock import FixedClock  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QGuiApplication, QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QWidget
    from chanceblog_desktop.ui import candidates_adapter
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import blog_parts
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module

T = text.T
UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
QT_DIR = UI_DIR / "qt"
NEW_QT = ("draft_parts.py", "draft_screen.py")
NOW = datetime.datetime(2026, 11, 6, 20, 10)
FORBIDDEN_WORDS = ("월 검색량", "검색량", "상위노출", "노출 확률", "검색 1위", "수익 보장", "보장", "월간 검색")
SIZES = ((1920, 1080), (1600, 960), (1366, 768), (1280, 720), (1093, 614), (910, 512), (900, 560))


def methods_of(path, class_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}


def called_names(function):
    names = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            names.add(node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", ""))
    return names


# ---- 소스 규칙(PySide6 없이 돈다 — CI 와 같은 조건) -----------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    def test_the_new_screen_files_cannot_write_open_files_copy_or_reach_the_network_or_the_service(self):
        for name in NEW_QT:
            tree = ast.parse((QT_DIR / name).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported |= {(node.module or "").split(".")[0] or ("." * node.level + (node.module or ""))}
            self.assertFalse(imported & {"sqlite3", "subprocess", "socket", "urllib", "http", "shutil", "os", "pathlib", "json", "tempfile", "requests", "keyring"}, name)
            names = called_names(tree)
            self.assertFalse(names & {"open", "write_text", "write_bytes", "make_body_for_engine", "make_draft", "start_make", "start_regenerate", "copy_decision", "confirm_copy", "setText_clipboard", "clipboard", "unlink", "mkdir", "rename", "openUrl"}, (name, names))
            source = (QT_DIR / name).read_text(encoding="utf-8")
            for forbidden in ("chanceblog_desktop.service", "..service", "..topics", "..topicdb", "..security", "..publish", "..content", "..check", "drafts_adapter", "adapters", "QClipboard", "QGuiApplication", "QDesktopServices"):
                self.assertFalse(forbidden in source, f"{name}: 화면 부품은 서비스·엔진·보관소·클립보드·브라우저를 직접 부르지 않는다 — {forbidden}")

    def test_only_one_shell_function_writes_the_clipboard_and_it_is_reached_only_through_the_gate(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        writers = [name for name, function in methods.items() if "copy" in called_names(function) and name.startswith(("drf_", "_drf", "cand_make"))]
        self.assertEqual(writers, ["_drf_do_copy"], "초안 글을 클립보드에 쓰는 함수는 하나뿐")
        callers = [name for name, function in methods.items() if "_drf_do_copy" in called_names(function)]
        self.assertEqual(sorted(callers), ["drf_copy", "drf_copy_confirmed"], "그 함수는 관문이 '복사해도 된다' 고 한 글이나 확인창 뒤의 글만 받는다")
        references = [name for name, function in methods.items() for node in ast.walk(function) if isinstance(node, ast.Attribute) and node.attr == "drf_copy_confirmed"]
        self.assertEqual(references, ["drf_copy"], "`drf_copy_confirmed` 는 확인창을 만드는 곳에서만 쓰인다")
        calls = [node for node in ast.walk(methods["drf_copy"]) if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "show_dialog"]
        confirm = [call for call in calls if any(keyword.arg == "on_ok" for keyword in call.keywords)]
        self.assertEqual(len(confirm), 1)
        keywords = {keyword.arg: keyword.value for keyword in confirm[0].keywords}
        self.assertEqual(ast.unparse(keywords["on_cancel"]), "controller.discard_copy", "취소·Esc 는 '확인창을 보였다' 표시를 거둔다")
        self.assertIs(keywords["safe_focus"].value, True, "처음 포커스는 취소")
        self.assertIn("copy_decision", called_names(methods["drf_copy"]))
        self.assertIn("confirm_copy", called_names(methods["drf_copy_confirmed"]))
        self.assertNotIn("copy", called_names(methods["drf_copy"]), "복사 결정 함수가 직접 클립보드를 쓰지 않는다")

    def test_the_address_is_opened_in_one_place_and_only_for_a_naver_blog_address(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        openers = [name for name, function in methods.items() for node in ast.walk(function) if isinstance(node, ast.Attribute) and node.attr == "_url_opener" and name != "__init__"]
        self.assertEqual(openers, ["drf_open"])
        self.assertIn("https://blog.naver.com/", ast.unparse(methods["drf_open"]), "열기 전에 주소 머리를 한 번 더 본다")
        self.assertIn("open_info", called_names(methods["drf_open"]))

    def test_the_draft_handlers_of_the_shell_never_touch_providers_files_or_the_network(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        found = [name for name in methods if name.startswith(("drf_", "_drf", "_on_drafts", "_show_drafts", "_recover_drafts", "_render_drafts", "_live_drafts", "_start_draft", "cand_make_draft", "_close_after", "_sync_nav"))]
        self.assertGreaterEqual(len(found), 25)
        for name in found:
            source = "\n".join(ast.unparse(statement) for statement in methods[name].body)           # 함수 이름(`cand_make_draft` 의 `make_draft`)은 빼고 몸만 본다
            for forbidden in ("provider", "service.", "sqlite3", "subprocess", "socket", "urllib", "make_draft", "make_body"):
                self.assertNotIn(forbidden, source, f"{name}: {forbidden}")
            self.assertFalse(called_names(methods[name]) & {"open", "write", "write_text", "write_bytes", "mkdir", "unlink", "rename", "replace"}, name)       # `connect` 는 Qt 신호 연결(`timeout.connect`)에도 쓰여 이름으로 막지 않는다 — 데이터베이스·소켓 연결은 위의 글자 검사(`sqlite3`·`socket`·`urllib`)가 막는다

    def test_typing_never_redraws_the_whole_screen(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        for name in ("drf_title_edited", "drf_body_edited", "drf_option_edited", "drf_inspect", "drf_toggle_options", "drf_blog", "drf_post_type", "drf_toggle_image", "drf_checks_toggled"):
            self.assertNotIn("render", called_names(methods[name]), f"{name}: 글을 치거나 고르는 동안 화면 전체를 다시 그리지 않는다(입력기 조합·커서가 사라지지 않게)")
        self.assertIn("_live_drafts", called_names(methods["drf_body_edited"]))

    def test_leaving_and_closing_are_guarded_before_anything_moves(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        go = ast.unparse(methods["go"])
        self.assertLess(go.index("leave_guard"), go.index(".nav("), "화면을 옮기기 전에 고친 내용을 먼저 본다")
        self.assertIn("safe_focus=True", go)
        close = ast.unparse(methods["closeEvent"])
        self.assertIn("close_guard", close)
        self.assertIn("isSavingSession", close, "윈도가 종료·로그오프 중일 때는 확인창이 시스템 종료를 붙잡지 않는다(이 PC 는 매일 밤 강제로 재부팅한다)")
        self.assertLess(close.index("isSavingSession"), close.index("close_guard"), "세션 종료 확인이 닫기 확인보다 먼저다")
        self.assertIn("event.ignore()", close)
        self.assertIn("safe_focus=True", close)
        self.assertLess(close.index("close_guard"), close.index("self.hide()"), "닫기를 막으면 창을 숨기기 전이다")
        self.assertIn("render", called_names(methods["resizeEvent"]))

    def test_the_new_qt_files_use_tokens_only_no_inline_styles_hex_colors_or_font_names(self):
        for name in NEW_QT:
            source = (QT_DIR / name).read_text(encoding="utf-8")
            self.assertNotIn("setStyleSheet", source, name)
            self.assertIsNone(re.search(r"#[0-9a-fA-F]{6}\b", source), f"{name}: 직접 적은 색")
            self.assertNotIn("QFont(", source, name)
            self.assertNotIn("datetime.now", source, name)

    def test_the_screen_table_and_the_builder_take_the_window_and_the_view_model_only(self):
        screens = (QT_DIR / "screens.py").read_text(encoding="utf-8")
        self.assertIn('"drafts": _drafts_builder', screens)
        self.assertIn("drafts_screen(shell, shell.state.drafts_view())", screens)

    def test_every_draft_text_is_used_somewhere(self):
        from chanceblog_desktop.ui.core import draft_text
        used, prefixes = set(), set()
        paths = [*(UI_DIR / "core").glob("draft*.py"), *(QT_DIR).glob("draft*.py"), QT_DIR / "shell.py", UI_DIR / "core" / "app_state.py", UI_DIR / "drafts_adapter.py", UI_DIR / "core" / "candidates_view.py", QT_DIR / "candidate_screen.py"]
        for path in paths:
            if path.name == "draft_text.py":
                continue
            source = path.read_text(encoding="utf-8")
            used |= set(re.findall(r"""["'](drf_[a-z0-9_]+)["']""", source)) - {"drf_ui"}      # `drf_ui` 는 한 번 그린 화면의 부품 묶음을 달아 두는 속성 이름이다(문구 열쇠가 아니다)
            prefixes |= set(re.findall(r"""["'](drf_[a-z0-9_]*_)["']\s*\+""", source))
        unused = sorted(key for key in draft_text.DRAFT_T if key not in used and not any(key.startswith(prefix) for prefix in prefixes))
        self.assertEqual(unused, [], "쓰이지 않는 문구가 있다")
        self.assertEqual(sorted(key for key in used if key not in draft_text.DRAFT_T and key not in prefixes), [], "정의하지 않은 문구를 쓴다")


# ---- 시험 도구 -----------------------------------------------------------------------------------------------------------------------------
class Gated(drafts.FakeDraftsProvider):
    """초안 만들기가 시험이 문을 열어 줄 때까지 기다리는 가짜 공급자 — 시간에 기대지 않고 '도는 중' 을 확실히 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()
        self.entered = []

    def make_draft(self, request, progress, cancelled):
        self.entered.append(threading.current_thread())
        if not self.gate.wait(30):
            raise AssertionError("시험이 문을 열어 주지 않았다")
        return super().make_draft(request, progress, cancelled)


def candidates_with(*extra):
    provider = cd.FakeCandidatesProvider()
    provider.candidates = [*provider.candidates, *extra]
    return provider


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
        self.copied, self.opened = [], []

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def activate(self, window):
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)

    def clipboard(self, value):
        self.copied.append(value)
        return True

    def make(self, candidates=None, drafts_provider=None, size=(1600, 960), clipboard=None, opener=None, home=None):
        provider = candidates or candidates_with(GENERIC, SOFTWARE, APPLIANCE, STOPPED, OTHER_CHANNEL)
        window = shell_module.AppShell(home or services.FakeHomeProvider(), candidates=provider, drafts=drafts_provider, autoload=False, clock=FixedClock(NOW), clipboard=clipboard or self.clipboard,
                                       url_opener=opener or (lambda url: self.opened.append(url) or True))
        window.resize(*size)
        window.show()
        self.addCleanup(lambda: (window.state.drafts.leave(), window.close()))                    # 고친 내용이 있으면 닫기가 막히므로 먼저 지운다
        self.settle()
        self.activate(window)
        window.go("topics")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.candidates.state != "loading" and not window.state.candidates.loading, 10))
        self.settle()
        return window

    def topic_id(self, window, part):
        found = [row.candidate.candidate_id for row in window.state.candidates.rows() if part in row.candidate.topic]
        self.assertEqual(len(found), 1, part)
        return found[0]

    def open_candidate(self, window, part):
        window.cand_open(self.topic_id(window, part))
        self.settle(6)

    def drafted(self, part="분야를 알 수 없는", **kwargs):
        """후보를 골라 `이 주제로 만들기` 를 눌러 초안이 보이는 창."""
        window = self.make(**kwargs)
        self.open_candidate(window, part)
        self.make_button(window).click()
        self.assertTrue(self.wait_draft(window))
        return window

    def make_button(self, window):
        found = [button for button in window.detail_pane.findChildren(QAbstractButton) if button.property("focus_key") == "act:make"]
        if not found:
            found = [button for button in window.drawer.findChildren(QAbstractButton) if button.property("focus_key") == "act:make"]
        self.assertEqual(len(found), 1)
        return found[0]

    def wait_draft(self, window, state="normal"):
        ok = ui_offscreen.wait_until(self.app, lambda: window.state.drafts.state == state and not window.state.drafts.busy, 15)
        self.settle()
        return ok

    def ui(self, window):
        return window.screen_widget.drf_ui

    def buttons(self, root):
        return {button.property("focus_key"): button for button in root.findChildren(QAbstractButton) if button.property("focus_key")}

    def button(self, window, key):
        found = [button for button in window.screen_widget.findChildren(QAbstractButton) if button.property("focus_key") == key]
        self.assertEqual(len(found), 1, f"{key}: {len(found)}개")
        return found[0]

    def dialog_buttons(self, window):
        return {button.text(): button for button in window.dialog.findChildren(QAbstractButton) if button.isVisibleTo(window.dialog)}

    def texts(self, root):
        found = set()
        for label in root.findChildren(QLabel):
            found.add(label.plain_text() if isinstance(label, UI.Label) else label.text())
        return found

    def everything(self, window):
        found = []
        for widget in [window, *window.findChildren(QWidget)]:
            found += [widget.toolTip(), widget.accessibleName(), widget.accessibleDescription()]
            if isinstance(widget, UI.Label):
                found.append(widget.plain_text())
            elif isinstance(widget, (QLabel, QAbstractButton, QLineEdit)):
                found.append(widget.text())
        return [value for value in found if value]

    def edit_body(self, window, extra="\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8):
        editor = self.ui(window).editor
        editor.setPlainText(editor.toPlainText() + extra)
        self.settle(2)
        return editor

    def type_ime(self, edit, value):
        event = QInputMethodEvent()
        event.setCommitString(value)
        QApplication.sendEvent(edit, event)
        self.settle(2)


# ---- 1) 메뉴와 들어가는 길 -----------------------------------------------------------------------------------------------------------------
class MenuTest(Base):
    def test_the_draft_menu_is_in_the_core_group_after_the_topics_and_the_next_steps_keep_only_the_history(self):
        window = self.make()
        self.assertEqual(list(window.nav_buttons), ["home", "topics", "drafts", "seed", "blogs", "settings"])
        self.assertEqual(window.nav_buttons["drafts"].accessibleName(), "초안 작성 메뉴로 이동")
        self.assertEqual(list(S.SCREEN_BUILDERS), ["home", "topics", "drafts", "seed", "blogs", "settings"])
        self.assertEqual([item.name.text() for item in window.sidebar.soon_list.items], ["발행 기록"])
        self.assertEqual(list(window.sidebar.group_titles), ["core", "data", "system"])

    def test_the_menu_without_a_candidate_shows_one_line_and_one_button_and_nothing_else(self):
        window = self.make()
        window.nav_buttons["drafts"].click()
        self.settle()
        self.assertEqual((window.state.page, window.state.drafts.state), ("drafts", "empty"))
        page = window.screen_widget
        self.assertIn("주제 후보에서 후보를 골라 '이 주제로 만들기' 를 눌러 주세요", self.texts(page))
        self.assertEqual([button.text() for button in page.findChildren(QAbstractButton)], ["주제 후보로 가기"])
        self.assertEqual([button.property("kind") for button in page.findChildren(QAbstractButton)], ["primary"])
        self.assertEqual(self.copied, [])
        page.findChildren(QAbstractButton)[0].click()
        self.settle()
        self.assertEqual(window.state.page, "topics")

    def test_the_make_button_is_the_fixed_footer_action_of_the_detail_and_opens_the_draft_screen(self):
        window = self.make()
        self.open_candidate(window, "분야를 알 수 없는")
        button = self.make_button(window)
        self.assertEqual((button.text(), button.property("kind"), button.isEnabled()), ("이 주제로 만들기", "primary", True))
        self.assertEqual(self.copied, [])
        button.click()
        self.assertTrue(self.wait_draft(window))
        self.assertEqual((window.state.page, window.state.drafts.state), ("drafts", "normal"))
        self.assertEqual(window.nav_buttons["drafts"].isChecked(), True)
        self.assertFalse(window.detail_pane.isVisible(), "초안 화면에는 후보의 고정 상세 창이 없다")
        self.assertEqual(self.copied, [], "초안을 만드는 것만으로 클립보드를 바꾸지 않는다")

    def test_a_stopped_candidate_and_a_foreign_channel_keep_the_button_off_with_the_reason_as_visible_text(self):
        window = self.make()
        for candidate, why in ((STOPPED, T["drf_make_why_stop"]), (OTHER_CHANNEL, T["drf_make_why_channel"])):               # 기본 예시 후보에도 같은 제목이 있어 제목 조각이 아니라 번호로 연다
            with self.subTest(topic=candidate.topic):
                window.cand_open(candidate.candidate_id)
                self.settle(6)
                button = self.make_button(window)
                self.assertFalse(button.isEnabled())
                self.assertIn(why, self.texts(window.detail_pane), "꺼진 단추는 Tab 이 가지 않아 까닭을 글로도 보인다")
                self.assertEqual(button.toolTip(), why)
                button.click()
                self.settle()
                self.assertEqual(window.state.page, "topics")
                window.cand_make_draft()                                       # 코드로 직접 불러도 이 길에서 열지 않는다 — 까닭만 안내한다
                self.settle()
                self.assertEqual((window.state.page, window.state.drafts.state, window.toast.text()), ("topics", "empty", why))

    def test_the_footer_is_in_the_drawer_too_when_the_window_is_narrow(self):
        window = self.make(size=(1200, 800))
        self.open_candidate(window, "분야를 알 수 없는")
        self.assertTrue(window.drawer.is_open)
        button = self.make_button(window)
        self.assertEqual((button.text(), button.isEnabled()), ("이 주제로 만들기", True))
        button.click()
        self.assertTrue(self.wait_draft(window))
        self.assertEqual((window.state.page, window.drawer.is_open), ("drafts", False))

    def test_only_the_make_footer_adds_a_primary_button_to_the_detail_and_the_screen_keeps_one_primary_action(self):
        window = self.make()
        self.open_candidate(window, "분야를 알 수 없는")
        self.assertEqual([button.text() for button in window.detail_pane.findChildren(QAbstractButton) if button.property("kind") == "primary"], ["이 주제로 만들기"])
        window = self.drafted()
        primary = [button.text() for button in window.screen_widget.findChildren(QAbstractButton) if button.property("kind") == "primary"]
        self.assertEqual(primary, ["전체 복사"], "화면의 주요 단추는 하나")


# ---- 2) 화면 ---------------------------------------------------------------------------------------------------------------------------------
class ScreenTest(Base):
    def test_the_screen_has_the_editor_the_title_the_side_cards_and_the_fixed_action_row(self):
        window = self.drafted()
        ui, controller = self.ui(window), window.state.drafts
        body = controller.draft_body()
        self.assertEqual(ui.editor.toPlainText(), body.body_text)
        self.assertEqual(ui.title.text(), body.selected_title)
        self.assertGreaterEqual(ui.editor.minimumHeight(), 420)
        self.assertLessEqual(ui.editor.minimumHeight(), 480)
        self.assertEqual([pick.index for pick in ui.picks], [0, 1, 2])
        self.assertEqual([button.text() for button in ui.action_bar.buttons], ["제목 복사", "본문 복사", "전체 복사", "네이버 글쓰기 열기"])
        self.assertEqual(sorted(ui.copy), ["all", "body", "keywords", "summary", "tags", "title"])
        shown = self.texts(window.screen_widget)
        for wanted in ("제목", "본문", "검사 결과", "키워드", "태그", "추천 카테고리", "한 줄 요약", "대표 이미지", "확인 권장", "이미지 검색 전"):
            self.assertIn(wanted, shown)
        self.assertEqual([ui.accordions[key].toggle.text().strip() for key in ("specific", "common")], ["이 글에만 해당", "모든 글 공통"], "확인 권장의 두 묶음 이름(접이식 머리 단추의 글)")
        self.assertEqual(ui.editor.property("focus_key"), "drf-body")

    def test_a_chosen_category_is_shown_in_its_card_and_the_check_card_names_what_it_checked(self):
        """독립 검증 V4(변이 N32)·V3: 서비스가 카테고리를 정한 초안은 카드에 그 글이 보이고, 검사 카드의 초록 문구는 본 범위와 못 보는 것을 밝힌다."""
        window = self.drafted()
        controller = window.state.drafts
        self.assertIn(T["drf_category_none"], self.texts(window.screen_widget))
        controller.result = dataclasses.replace(controller.result, body=dataclasses.replace(controller.result.body, category="예시 생활 정보"))
        window.render()
        self.settle(3)
        shown = self.texts(window.screen_widget)
        self.assertIn("예시 생활 정보", shown)
        self.assertNotIn(T["drf_category_none"], shown)
        self.edit_body(window)
        self.button(window, "drf-inspect").click()
        self.settle(2)
        status = self.ui(window).inspect.status.plain_text()
        self.assertEqual(status, T["drf_inspect_ok"])
        self.assertIn("직접 확인", status)

    def test_the_action_row_stays_at_the_bottom_while_the_content_scrolls(self):
        window = self.drafted()
        bar = self.ui(window).action_bar
        inner = window.screen_widget.findChild(QScrollArea)
        self.assertIsNotNone(inner)
        before = bar.mapTo(window, bar.rect().topLeft()).y()
        inner.verticalScrollBar().setValue(inner.verticalScrollBar().maximum())
        self.settle(2)
        self.assertEqual(bar.mapTo(window, bar.rect().topLeft()).y(), before, "행동 줄은 스크롤과 함께 움직이지 않는다")
        self.assertTrue(bar.isVisible())
        self.assertGreater(inner.verticalScrollBar().maximum(), 0)

    def test_typing_does_not_redraw_the_screen_and_the_status_line_follows(self):
        window = self.drafted()
        ui, controller = self.ui(window), window.state.drafts
        page, editor = window.screen_widget, ui.editor
        self.assertEqual(ui.edit.plain_text(), T["drf_edit_none"])
        editor.setFocus(Qt.OtherFocusReason)
        QTest.keyClicks(editor, "abc")
        self.settle(2)
        self.assertIs(window.screen_widget, page, "글을 쳐도 화면을 다시 그리지 않는다")
        self.assertIs(self.ui(window).editor, editor)
        self.assertEqual(controller.body, editor.toPlainText())
        self.assertTrue(controller.has_unsaved())
        self.assertIn("고친 부분이 있어요", ui.edit.plain_text())
        self.assertIn("공백 제외", ui.count.plain_text())
        self.type_ime(editor, "한글 입력")                                       # 한글은 입력기(IME)가 글을 확정하는 것과 같은 이벤트로 넣는다
        self.assertIs(window.screen_widget, page)
        self.assertIn("한글 입력", controller.body)

    def test_tab_leaves_the_editor_without_inserting_a_tab_and_every_stop_has_a_name(self):
        window = self.drafted()
        ui = self.ui(window)
        ui.editor.setFocus(Qt.OtherFocusReason)
        self.settle(2)
        QTest.keyClick(ui.editor, Qt.Key_Tab)
        self.settle(2)
        self.assertNotIn(chr(9), ui.editor.toPlainText())
        self.assertIsNot(QApplication.focusWidget(), ui.editor)
        for stop in ui.stops:
            self.assertTrue(stop.accessibleName().strip(), type(stop).__name__)
        self.assertEqual(ui.stops[0].accessibleName(), "주제 후보로 돌아가기")
        names = [stop.accessibleName() for stop in ui.stops]
        self.assertLess(names.index(T["drf_title_input_a11y"]), names.index(T["drf_body_a11y"]))
        self.assertEqual(ui.stops[-1], ui.actions["open"], "Tab 순서의 끝은 아래 행동 줄")

    def test_the_title_picks_follow_the_title_field_and_a_pick_over_an_edited_title_asks_first(self):
        window = self.drafted()
        ui, controller = self.ui(window), window.state.drafts
        titles = controller.generated_titles()
        self.assertEqual([pick.property("selected") for pick in ui.picks], [False, True, False])
        ui.title.setFocus(Qt.OtherFocusReason)
        QTest.keyClicks(ui.title, "!")
        self.settle(2)
        self.assertEqual([pick.property("selected") for pick in ui.picks], [False, False, False], "고친 제목은 어느 후보도 아니다")
        QTest.mouseClick(ui.picks[0], Qt.LeftButton)
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(QApplication.focusWidget().text(), "취소")
        self.assertEqual(controller.title, titles[1] + "!", "확인하기 전에는 제목이 그대로다")
        self.dialog_buttons(window)["취소"].click()
        self.settle(2)
        self.assertEqual((window.dialog.is_open, controller.title), (False, titles[1] + "!"))
        QTest.mouseClick(ui.picks[0], Qt.LeftButton)
        self.settle(3)
        self.dialog_buttons(window)["제목 바꾸기"].click()
        self.settle(3)
        self.assertEqual((controller.title, ui.title.text(), [pick.property("selected") for pick in ui.picks]), (titles[0], titles[0], [True, False, False]))
        QTest.mouseClick(ui.picks[2], Qt.LeftButton)                          # 고치지 않은 제목이면 묻지 않고 바꾼다
        self.settle(3)
        self.assertEqual((window.dialog.is_open, ui.title.text()), (False, titles[2]))

    def test_the_checks_open_the_specific_group_and_fold_the_common_one_and_remember_a_change(self):
        window = self.drafted("청소기")
        ui = self.ui(window)
        self.assertEqual((ui.accordions["specific"].is_open, ui.accordions["common"].is_open), (True, False))
        shown = self.texts(window.screen_widget)
        self.assertTrue([line for line in shown if "협찬·광고·제휴로" in line], "협찬 알림은 펼친 쪽")
        card = window.state.drafts.view()["normal"]["side"]["checks"]                                # 출처와 확인 필요 상태 한 줄(완료 조건 ⑭)이 확인 권장 카드 맨 위에 보인다
        self.assertEqual(ui.checks_status.plain_text(), card["status"])
        self.assertTrue(card["status"].startswith("출처: ") and "확인 필요" in card["status"] and "직접 확인" in card["status"])
        self.assertIn(card["status"], shown)
        ui.accordions["common"].toggle.click()
        self.settle(2)
        self.assertTrue(window.state.drafts.common_open)
        window.render()
        self.settle(4)
        self.assertTrue(self.ui(window).accordions["common"].is_open, "다시 그려도 펼친 채다")

    def test_the_image_slot_has_two_states_and_no_search_button_and_no_thumbnail(self):
        window = self.drafted()
        ui = self.ui(window)
        self.assertEqual(ui.image_state.plain_text(), "이미지 검색 전")
        self.assertEqual(ui.image_button.text(), "이미지 없이 진행")
        ui.image_button.click()
        self.settle(2)
        self.assertEqual((ui.image_state.plain_text(), ui.image_button.text()), ("이미지 없이 진행", "되돌리기"))
        ui.image_button.click()
        self.assertEqual(ui.image_state.plain_text(), "이미지 검색 전")
        self.assertFalse([button for button in window.screen_widget.findChildren(QAbstractButton) if "검색" in button.text()], "동작하지 않는 이미지 검색 단추는 없다")
        self.assertFalse([label for label in window.screen_widget.findChildren(QLabel) if label.pixmap() is not None and not label.pixmap().isNull()], "사진 썸네일은 없다")

    def test_the_inspect_button_fills_the_card_in_place_and_marks_it_stale_after_an_edit(self):
        window = self.drafted()
        ui = self.ui(window)
        self.assertEqual(ui.inspect.status.plain_text(), T["drf_inspect_before"])
        self.button(window, "drf-inspect").click()
        self.settle(2)
        self.assertIn("거의 고치지 않은 초안", ui.inspect.status.plain_text())
        self.edit_body(window, "\n\n직접 써 보니 정말 좋았습니다.")
        self.assertEqual(ui.inspect.status.plain_text(), T["drf_inspect_stale"])
        self.button(window, "drf-inspect").click()
        self.settle(2)
        self.assertIn("확인이 필요한 곳", ui.inspect.status.plain_text())
        self.assertTrue([line for line in self.texts(ui.inspect.lines) if "직접 써 보니" in line])
        self.assertEqual(self.copied, [], "검사는 클립보드를 바꾸지 않는다")

    def test_the_options_panel_opens_and_the_blog_type_and_fields_make_a_new_draft_after_a_question(self):
        window = self.drafted()
        ui, controller = self.ui(window), window.state.drafts
        self.assertFalse(ui.options_panel.isVisibleTo(window.screen_widget))
        ui.options_toggle.click()
        self.settle(2)
        self.assertTrue(ui.options_panel.isVisibleTo(window.screen_widget))
        self.assertEqual(ui.options_toggle.text(), T["drf_options_close"])
        ui.blog_chips["naver_b"].click()
        ui.type_chips["문제 해결형"].click()
        self.settle(2)
        self.assertEqual((controller.blog, controller.post_type, ui.blog_chips["naver_a"].isChecked(), ui.blog_chips["naver_b"].isChecked()), ("naver_b", "문제 해결형", False, True))
        self.assertEqual(sum(chip.isChecked() for chip in ui.type_chips.values()), 1, "글 유형은 하나만")
        ui.fields["message"].setFocus(Qt.OtherFocusReason)
        QTest.keyClicks(ui.fields["message"], "x")
        self.type_ime(ui.fields["message"], " 예시 전하고 싶은 말")
        ui.fields["must_include"].setPlainText("예시 반드시 넣을 문장이에요.")
        self.settle(2)
        self.assertTrue(ui.pending_note.isVisibleTo(window.screen_widget))
        self.assertTrue(controller.has_unsaved(), "적고 반영하지 않은 선택 입력은 고친 내용이다")
        ui.apply.click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(QApplication.focusWidget().text(), "취소")
        self.dialog_buttons(window)["취소"].click()
        self.settle(2)
        self.assertEqual(len(window.state.drafts.provider.calls), 1, "취소하면 새로 만들지 않는다")
        ui.apply.click()
        self.settle(3)
        self.dialog_buttons(window)["다시 만들기"].click()
        self.assertTrue(self.wait_draft(window))
        self.assertEqual(len(window.state.drafts.provider.calls), 2)
        ui = self.ui(window)
        self.assertIn("예시 반드시 넣을 문장이에요.", ui.editor.toPlainText())
        self.assertEqual((controller.result.blog, controller.result.post_type, controller.has_unsaved()), ("naver_b", "문제 해결형", False))
        self.assertTrue([text for text in self.texts(window.screen_widget) if T["drf_made_again"] in text])

    def test_a_wrong_option_keeps_the_edited_draft_and_names_the_field_in_a_notice(self):
        window = self.drafted()
        ui = self.ui(window)
        self.edit_body(window, "\n\n내가 고친 문단이에요.")
        ui.options_toggle.click()
        self.type_ime(ui.fields["experience"], "예시 " + KEY_SHAPED)                              # 한글은 `QTest.keyClicks` 로 치면 이 환경에서 프로세스가 죽는다(입력기 이벤트로 넣는다)
        self.settle(2)
        ui.apply.click()
        self.settle(3)
        self.dialog_buttons(window)["다시 만들기"].click()
        self.assertTrue(self.wait_draft(window))
        self.assertIn("내가 고친 문단이에요.", self.ui(window).editor.toPlainText(), "실패해도 고친 내용은 그대로")
        notices = [bar.text.plain_text() for bar in window.screen_widget.findChildren(blog_parts.NoticeBar)]
        self.assertTrue([notice for notice in notices if "‘실제 사용 경험’" in notice])
        self.assertNotIn(KEY_SHAPED, " ".join(notices))

    def test_a_loading_screen_shows_while_the_draft_is_made_and_leaving_drops_the_late_answer(self):
        provider = Gated(lambda: CATALOG)
        window = self.make(drafts_provider=provider)
        self.open_candidate(window, "분야를 알 수 없는")
        self.make_button(window).click()
        self.settle(4)
        self.assertEqual((window.state.page, window.state.drafts.state), ("drafts", "loading"))
        self.assertIn(T["drf_loading"], self.texts(window.screen_widget))
        window.go("home")
        self.settle(3)
        self.assertEqual((window.state.page, window.state.drafts.state), ("home", "empty"))
        provider.gate.set()
        ui_offscreen.wait_until(self.app, lambda: not window.state.runner.running("drafts-make"), 10)
        self.settle(6)
        self.assertEqual((window.state.page, window.state.drafts.state, window.state.drafts.result), ("home", "empty", None), "늦게 온 답은 어디에도 보이지 않는다")
        window.go("drafts")
        self.settle(3)
        self.assertEqual(window.state.drafts.state, "empty")

    def test_a_stopped_candidate_refused_by_the_provider_shows_the_refusal_and_no_body(self):
        window = self.make()
        window.state.drafts.open_target(drafts.DraftTarget(STOPPED.candidate_id, STOPPED.topic, "naver_b", "예시", False, True))      # 화면의 값이 거짓말을 해도 공급자가 거절한다
        window.go("drafts")
        window._start_draft()
        self.assertTrue(self.wait_draft(window, "refused"))
        page = window.screen_widget
        self.assertIn(T["drf_refused_title"], self.texts(page))
        self.assertEqual(sorted(button.text() for button in page.findChildren(QAbstractButton) if button.isVisibleTo(page)), ["예시 데이터", "주제 후보로 가기"])
        self.assertFalse(page.findChildren(QPlainTextEdit), "본문 편집기가 없다")
        self.assertFalse(window.state.drafts.body or window.state.drafts.title, "본문·제목이 상태에도 없다")
        self.assertEqual(self.copied, [])


# ---- 3) 복사 ---------------------------------------------------------------------------------------------------------------------------------
class CopyTest(Base):
    def dialog_open(self, window):
        return window.dialog.is_open

    def test_nothing_is_copied_until_a_button_is_pressed(self):
        window = self.drafted("AI 서비스")
        ui = self.ui(window)
        self.button(window, "drf-inspect").click()
        ui.options_toggle.click()
        ui.image_button.click()
        self.edit_body(window)
        self.button(window, "drf-inspect").click()
        window.state.drafts.set_body(window.state.drafts.draft_body().body_text)
        window.state.drafts.set_title(window.state.drafts.generated_titles()[1])
        window.go("topics")
        self.settle(3)
        window.go("drafts")
        self.settle(3)
        self.assertEqual(self.copied, [], "초안 만들기·열기·검사·고치기·옮기기로는 클립보드를 바꾸지 않는다")

    def test_the_title_of_a_clean_draft_goes_straight_to_the_clipboard_and_the_button_shows_copied_then_reverts(self):
        window = self.drafted("AI 서비스")
        ui, controller = self.ui(window), window.state.drafts
        button = ui.copy["title"]
        self.assertEqual(button.text(), "제목 복사")
        button.click()
        self.settle(3)
        self.assertEqual(self.copied, [controller.title])
        self.assertEqual((button.text(), button.property("copied"), button.accessibleName()), ("✓ 제목 복사됨", True, "✓ 제목 복사됨"), "성공색(`copied`)과 글자가 함께 바뀐다")
        self.assertIn("title", controller.copied, "독립 검증 D3(변이 N18): 복사했다는 표시가 컨트롤러에도 남는다 — 화면을 다시 그려도 복사됨 모양이 이어진다")
        self.assertTrue(1500 <= tokens.COPY_FEEDBACK_MS <= 2000)
        timer = window._copy_timers["title"]
        self.assertEqual((timer.interval(), timer.isActive(), timer.isSingleShot()), (tokens.COPY_FEEDBACK_MS, True, True))
        self.assertEqual(self.ui(window).copy["body"].text(), "본문 복사", "다른 단추는 그대로")
        timer.stop()
        timer.timeout.emit()                                                   # 1.8초가 지났다고 해 보자
        self.settle(2)
        self.assertEqual((button.text(), button.property("copied"), button.accessibleName(), "title" in controller.copied), ("제목 복사", False, "제목 복사", False))

    def test_the_body_of_an_unedited_draft_asks_softly_and_cancel_copies_nothing_while_ok_copies_the_text_as_it_is(self):
        window = self.drafted("AI 서비스")
        ui, controller = self.ui(window), window.state.drafts
        ui.copy["body"].click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(QApplication.focusWidget().text(), "취소", "처음 포커스는 취소")
        self.assertEqual(sorted(self.dialog_buttons(window)), ["그래도 복사", "취소"])
        self.assertIn(T["drf_soft_title"], self.texts(window.dialog))
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Return)              # 취소 위의 Enter
        self.settle(3)
        self.assertEqual((window.dialog.is_open, self.copied), (False, []))
        ui.copy["body"].click()
        self.settle(3)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Escape)
        self.settle(3)
        self.assertEqual((window.dialog.is_open, self.copied), (False, []), "Esc 도 복사하지 않는다")
        ui.copy["body"].click()
        self.settle(3)
        self.dialog_buttons(window)["그래도 복사"].click()
        self.settle(3)
        self.assertEqual(self.copied, [controller.draft_body().body_text])
        self.assertEqual(ui.copy["body"].text(), "✓ 본문 복사됨")
        ui.copy["all"].click()
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "이미 확인한 안내는 다시 묻지 않는다")
        self.assertEqual(self.copied[-1], controller.draft_body().plain_text)

    def test_the_edited_body_and_title_are_copied_exactly_as_they_are(self):
        window = self.drafted("AI 서비스")
        ui = self.ui(window)
        mine = "내가 고친 본문이에요.\n\n둘째 문단입니다.  끝에 공백  " + "가" * 130
        ui.editor.setPlainText(mine)
        ui.title.setFocus(Qt.OtherFocusReason)
        ui.title.selectAll()
        self.type_ime(ui.title, "내가 고친 제목")
        self.settle(2)
        ui.copy["body"].click()
        self.settle(3)
        ui.copy["title"].click()
        self.settle(3)
        ui.copy["all"].click()
        self.settle(3)
        self.assertEqual(self.copied, [mine, "내가 고친 제목", "내가 고친 제목\n\n" + mine])

    def test_an_unreadable_domain_a_sponsor_line_and_a_new_claim_ask_with_the_listed_lines_and_then_not_again(self):
        window = self.drafted("분야를 알 수 없는")
        ui = self.ui(window)
        ui.copy["title"].click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.assertIn(T["drf_chk_domain"], " ".join(self.texts(window.dialog)))
        self.dialog_buttons(window)["그래도 복사"].click()
        self.settle(3)
        self.assertEqual(len(self.copied), 1)
        ui.copy["title"].click()
        self.settle(3)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(len(self.copied), 2, "이미 확인한 것은 다시 묻지 않는다")
        self.edit_body(window, "\n\n직접 써 보니 정말 좋았습니다. 가격은 12,000원이었어요.")
        ui.copy["body"].click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        shown = " ".join(self.texts(window.dialog))
        self.assertIn("직접 써 보니 정말 좋았습니다.", shown)
        self.assertIn("확인하지 않은 가격", shown)
        self.dialog_buttons(window)["취소"].click()
        self.settle(3)
        self.assertEqual(len(self.copied), 2)

    def test_a_sponsor_line_asks_at_the_first_copy_and_lists_the_line(self):
        window = self.drafted("청소기")
        self.ui(window).copy["title"].click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.assertIn("협찬·광고·제휴로", " ".join(self.texts(window.dialog)))
        self.assertEqual(self.copied, [])

    def test_a_key_shape_blocks_every_copy_with_one_ok_dialog_and_nothing_reaches_the_clipboard(self):
        window = self.drafted("AI 서비스")
        ui = self.ui(window)
        self.edit_body(window, " " + KEY_SHAPED)
        for key in ("title", "body", "all", "keywords", "tags", "summary"):
            with self.subTest(key=key):
                ui.copy[key].click()
                self.settle(3)
                self.assertTrue(window.dialog.is_open)
                self.assertEqual(sorted(self.dialog_buttons(window)), ["확인"])
                self.assertIn(T["drf_secret_title"], self.texts(window.dialog))
                self.assertNotIn(KEY_SHAPED, " ".join(self.everything(window)).replace(ui.editor.toPlainText(), ""), "안내창은 입력한 글을 되풀이하지 않는다")
                self.dialog_buttons(window)["확인"].click()
                self.settle(2)
        self.assertEqual(self.copied, [])
        self.button(window, "drf-inspect").click()
        self.settle(2)
        self.assertEqual(ui.inspect.status.plain_text(), T["drf_inspect_secret"])

    def test_a_health_claim_blocks_the_gated_copies_with_one_ok_dialog_that_points_to_the_sentence(self):
        """독립 검증 V1②·V3: 편집기에 쓴 건강 효과 단정은 본문·전체 복사를 막고(안내창 하나 — 우회 없음) 어느 문장인지 짚으며, 작은 복사는 자기 글만 본다. 고치면 다시 복사할 수 있다."""
        window = self.drafted("AI 서비스")
        ui, controller = self.ui(window), window.state.drafts
        self.edit_body(window, "\n\n이 영양제는 피로를 즉시 없애줍니다.")
        for key in ("body", "all"):
            with self.subTest(key=key):
                ui.copy[key].click()
                self.settle(3)
                self.assertTrue(window.dialog.is_open)
                self.assertEqual(sorted(self.dialog_buttons(window)), ["확인"])
                shown = " ".join(self.texts(window.dialog))
                self.assertIn(T["drf_health_body"], shown)
                self.assertIn(T["drf_where_head"], shown)
                self.assertIn("본문 — 이 영양제는 피로를 즉시 없애줍니다.", shown, "걸린 문장의 앞부분을 짚는다")
                self.dialog_buttons(window)["확인"].click()
                self.settle(2)
        self.assertEqual(self.copied, [])
        self.button(window, "drf-inspect").click()
        self.settle(2)
        self.assertEqual(ui.inspect.status.plain_text(), T["drf_inspect_health_stop"])
        self.assertTrue([line for line in self.texts(ui.inspect.lines) if "이 영양제는 피로를 즉시 없애줍니다." in line])
        for key in ("keywords", "tags", "summary"):
            ui.copy[key].click()
            self.settle(3)
            self.assertFalse(window.dialog.is_open, key)
        self.assertEqual(len(self.copied), 3, "작은 복사는 자기 글만 본다")
        controller.set_body(controller.draft_body().body_text)
        ui.copy["body"].click()
        self.settle(3)
        self.assertNotEqual(sorted(self.dialog_buttons(window)), ["확인"], "고치면 막지 않는다")

    def test_normal_addresses_in_the_editor_never_lock_the_copy_buttons_and_a_key_in_an_address_shows_its_place(self):
        """독립 검증 V2: 정상 주소(글번호·상품번호)가 든 글은 복사할 수 있고, 주소 안의 키 모양은 막되 어느 부분인지 앞부분만 짚는다(키는 되풀이하지 않는다)."""
        window = self.drafted("AI 서비스")
        ui = self.ui(window)
        self.edit_body(window, "\n\n참고: https://blog.naver.com/exampleaaa/223012345678 와 https://www.coupang.com/vp/products/1234567890 입니다. " + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8)
        for key in ("title", "body", "all", "keywords", "tags", "summary"):
            with self.subTest(key=key):
                ui.copy[key].click()
                self.settle(3)
                if window.dialog.is_open:
                    self.assertNotEqual(sorted(self.dialog_buttons(window)), ["확인"], "정상 주소 때문에 막지 않는다")
                    self.dialog_buttons(window)["취소"].click()
                    self.settle(2)
        self.edit_body(window, "\n\n참고: https://example.com/page?x=" + KEY_SHAPED + " 입니다.")
        ui.copy["body"].click()
        self.settle(3)
        self.assertEqual(sorted(self.dialog_buttons(window)), ["확인"])
        shown = " ".join(self.texts(window.dialog))
        self.assertIn(T["drf_where_head"], shown)
        self.assertIn("com/page?x=", shown, "걸린 곳 앞의 글이 보인다")
        self.assertNotIn(KEY_SHAPED, shown)
        self.dialog_buttons(window)["확인"].click()
        self.settle(2)

    def test_the_buttons_of_an_old_dialog_never_survive_into_the_next_one(self):
        window = self.drafted("AI 서비스")
        ui = self.ui(window)
        ui.copy["body"].click()
        self.settle(3)
        self.assertEqual(sorted(self.dialog_buttons(window)), ["그래도 복사", "취소"])
        ui.title.setFocus(Qt.OtherFocusReason)
        QTest.keyClicks(ui.title, "!")
        QTest.mouseClick(ui.picks[0], Qt.LeftButton)                          # 확인창이 떠 있는 채 다른 확인창(제목 바꾸기)을 연다
        self.settle(3)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.settle(3)
        now = self.dialog_buttons(window)
        self.assertEqual(sorted(now), ["제목 바꾸기", "취소"], "새 확인창에는 자기 단추만 있다")
        for _ in range(3):
            QTest.keyClick(QApplication.focusWidget() or window, Qt.Key_Return)
        self.settle(3)
        self.assertEqual(self.copied, [], "옛 확인창의 `그래도 복사` 가 눌리지 않는다")

    def test_a_clipboard_that_fails_shows_a_notice_and_no_copied_look(self):
        window = self.drafted("AI 서비스", clipboard=lambda value: False)
        ui = self.ui(window)
        ui.copy["title"].click()
        self.settle(3)
        self.assertEqual(ui.copy["title"].text(), "제목 복사")
        self.assertIn(T["drf_copy_failed"], [window.toast.text()])

    def test_the_side_copies_keep_their_own_look_and_copy_the_service_values(self):
        window = self.drafted("AI 서비스")
        ui, controller = self.ui(window), window.state.drafts
        body = controller.draft_body()
        for key, expected, shown in (("keywords", ", ".join((*body.core_keywords, *body.sub_keywords)), "✓ 키워드 복사됨"), ("tags", body.tags_text, "✓ 태그 복사됨"), ("summary", body.summary, "✓ 요약 복사됨")):
            with self.subTest(key=key):
                ui.copy[key].click()
                self.settle(3)
                self.assertEqual((self.copied[-1], ui.copy[key].text(), ui.copy[key].property("copied")), (expected, shown, True))
                self.assertFalse(window.dialog.is_open)


# ---- 4) 떠나기·닫기 ------------------------------------------------------------------------------------------------------------------------
class LeaveTest(Base):
    def test_leaving_with_edits_asks_with_cancel_first_and_cancel_keeps_everything_then_ok_leaves_and_clears(self):
        window = self.drafted("AI 서비스")
        self.edit_body(window, "\n\n고친 문단이에요.")
        window.nav_buttons["home"].click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual((window.state.page, QApplication.focusWidget().text()), ("drafts", "취소"))
        self.assertEqual((window.nav_buttons["drafts"].isChecked(), window.nav_buttons["home"].isChecked()), (True, False), "막힌 단추가 눌린 채로 남지 않는다")
        self.assertIn("고친 내용이 사라져요", self.texts(window.dialog))
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Return)
        self.settle(3)
        self.assertEqual((window.state.page, window.state.drafts.has_unsaved(), window.dialog.is_open), ("drafts", True, False))
        window.nav_buttons["home"].click()
        self.settle(3)
        self.dialog_buttons(window)["그래도 이동"].click()
        self.settle(4)
        self.assertEqual((window.state.page, window.state.drafts.state, window.state.drafts.result), ("home", "empty", None))

    def test_the_back_button_has_the_same_guard_and_no_question_without_edits(self):
        window = self.drafted("AI 서비스")
        self.edit_body(window, "\n\n고친 문단이에요.")
        self.button(window, "drf-back").click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.dialog_buttons(window)["취소"].click()
        self.settle(2)
        self.assertEqual(window.state.page, "drafts")
        window.state.drafts.set_body(window.state.drafts.draft_body().body_text)
        window.render()
        self.settle(3)
        self.button(window, "drf-back").click()
        self.settle(3)
        self.assertEqual((window.dialog.is_open, window.state.page, window.state.drafts.state), (False, "topics", "empty"))

    def test_closing_with_edits_asks_and_cancel_keeps_the_window_open_while_ok_closes_it(self):
        window = self.drafted("AI 서비스")
        self.edit_body(window, "\n\n고친 문단이에요.")
        self.assertFalse(window.close(), "고친 내용이 있으면 닫기를 막는다")
        self.settle(3)
        self.assertTrue(window.isVisible() and window.dialog.is_open)
        self.assertEqual(QApplication.focusWidget().text(), "취소")
        self.assertEqual(sorted(self.dialog_buttons(window)), ["그래도 닫기", "취소"])
        self.dialog_buttons(window)["취소"].click()
        self.settle(3)
        self.assertTrue(window.isVisible())
        self.assertTrue(window.state.drafts.has_unsaved())
        self.assertFalse(window.close())
        self.settle(3)
        self.dialog_buttons(window)["그래도 닫기"].click()
        self.settle(3)
        self.assertFalse(window.isVisible())

    def test_closing_while_windows_ends_the_session_does_not_ask_and_so_cannot_hold_the_shutdown(self):
        """윈도가 종료·로그오프하는 중(`QGuiApplication.isSavingSession`)이면 고친 내용이 있어도 확인창으로 붙잡지 않는다(이 PC 는 매일 밤 강제로 재부팅한다 — D-281). 이 길을 처음 만들 때 호출 방식이 틀려(`isSavingSession` 은 인스턴스 함수다)
        모든 창 닫기가 예외를 냈고 이 시험이 그것을 잡는다."""
        window = self.drafted("AI 서비스")
        self.edit_body(window, "\n\n고친 문단이에요.")
        with mock.patch.object(QGuiApplication, "isSavingSession", lambda self: True):
            self.assertTrue(window.close(), "세션이 끝나는 중이면 닫기를 막지 않는다")
            self.settle(3)
        self.assertFalse(window.dialog.is_open)
        self.assertFalse(window.isVisible())

    def test_closing_without_edits_closes_at_once_and_other_screens_close_as_before(self):
        window = self.drafted("AI 서비스")
        self.assertTrue(window.close())
        self.assertFalse(window.isVisible())
        other = self.make()
        self.assertTrue(other.close())

    def test_resizing_across_the_two_column_limit_keeps_the_edits(self):
        window = self.drafted("AI 서비스", size=(1366, 768))
        self.assertTrue(window._drafts_side)
        editor = self.edit_body(window, "\n\n고친 문단이에요.")
        mine = editor.toPlainText()
        window.resize(1100, 700)
        self.settle(8)
        self.assertFalse(window._drafts_side)
        self.assertEqual(self.ui(window).editor.toPlainText(), mine, "배치가 바뀌어 다시 그려도 고친 글은 그대로다")
        window.resize(1400, 800)
        self.settle(8)
        self.assertTrue(window._drafts_side)
        self.assertEqual(self.ui(window).editor.toPlainText(), mine)
        self.assertTrue(window.state.drafts.has_unsaved())


# ---- 5) 배치 ---------------------------------------------------------------------------------------------------------------------------------
class LockTest(Base):
    def test_the_editors_are_read_only_while_a_new_draft_is_made_and_editable_again_after(self):
        """독립 검증 V5: 다시 만들기가 도는 동안 친 글이 새 초안에 덮여 확인 없이 사라지던 틈 — 도는 동안 제목·본문은 읽기 전용이고 제목 후보는 눌리지 않으며 끝나면 다시 고칠 수 있다."""
        provider = Gated(lambda: CATALOG)
        provider.gate.set()
        window = self.drafted("AI 서비스", drafts_provider=provider)
        ui, controller = self.ui(window), window.state.drafts
        self.assertEqual((ui.editor.isReadOnly(), ui.title.isReadOnly(), [pick.isEnabled() for pick in ui.picks]), (False, False, [True] * 3))
        self.edit_body(window, "\n\n내가 고친 문단이에요.")
        provider.gate.clear()
        window.drf_remake()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.dialog_buttons(window)["다시 만들기"].click()
        self.settle(4)
        self.assertTrue(controller.busy and controller.locked)
        ui = self.ui(window)
        self.assertEqual((ui.editor.isReadOnly(), ui.title.isReadOnly(), [pick.isEnabled() for pick in ui.picks]), (True, True, [False] * 3), "도는 동안은 읽기 전용")
        self.assertEqual((ui.editor.accessibleDescription(), ui.title.accessibleDescription()), (T["drf_edit_locked"], T["drf_edit_locked"]), "화면 읽기 프로그램에도 까닭이 읽힌다")
        before = (controller.body, controller.title)
        shown = (ui.editor.toPlainText(), ui.title.text())
        ui.editor.setFocus(Qt.OtherFocusReason)
        self.type_ime(ui.editor, "도는 동안 친 글")                                         # 입력기 확정 이벤트가 곧바로 와도 읽기 전용 칸은 받지 않는다(진짜 입력기는 읽기 전용 칸을 꺼 둔다)
        QTest.keyClicks(ui.editor, "abc")
        ui.title.setFocus(Qt.OtherFocusReason)
        self.type_ime(ui.title, "도는 동안 새 제목")
        QTest.keyClicks(ui.title, "abc")
        self.assertEqual((controller.body, controller.title), before, "도는 동안 친 글자는 상태에 들어가지 않는다")
        self.assertEqual((ui.editor.toPlainText(), ui.title.text()), shown, "화면의 글도 그대로다(친 글이 보였다가 새 초안에 덮여 사라지지 않는다)")
        provider.gate.set()
        self.assertTrue(self.wait_draft(window))
        ui = self.ui(window)
        self.assertEqual((ui.editor.isReadOnly(), ui.title.isReadOnly(), [pick.isEnabled() for pick in ui.picks]), (False, False, [True] * 3), "새 초안이 오면 다시 고칠 수 있다")


class ClipboardTest(Base):
    class Lost:
        """다른 프로그램이 클립보드를 잡고 있어 쓰기가 먹지 않은 모습 — 쓴 뒤 읽으면 예전 글이 그대로다."""

        def __init__(self, old):
            self.old = old

        def setText(self, value):
            pass

        def text(self):
            return self.old

    class Kept:
        def __init__(self, newline=chr(10)):
            self.value, self.newline = "", newline

        def setText(self, value):
            self.value = value.replace(chr(10), self.newline)

        def text(self):
            return self.value

    def test_the_real_clipboard_function_reads_back_and_reports_a_write_that_did_not_land(self):
        """독립 검증 V7: 예전에는 쓰지 못해도 늘 성공으로 알려 '복사됨' 이 보였다 — 쓴 뒤 다시 읽어 같은지 보고(줄바꿈·공백 차이는 같은 글), 다르면 실패로 알린다."""
        with mock.patch.object(QGuiApplication, "clipboard", return_value=self.Lost("예전 글")):
            self.assertFalse(shell_module.qt_clipboard_set("복사할 글"))
        for newline in (chr(10), chr(13) + chr(10)):
            with self.subTest(newline=repr(newline)), mock.patch.object(QGuiApplication, "clipboard", return_value=self.Kept(newline)):
                self.assertTrue(shell_module.qt_clipboard_set("복사할 글\n둘째 줄  "))
        with mock.patch.object(QGuiApplication, "clipboard", return_value=self.Kept()):
            self.assertFalse(shell_module._same_clipboard_text(None, "글"))
            self.assertFalse(shell_module._same_clipboard_text("다른 글", "글"))
        if QGuiApplication.platformName() == "offscreen":                                   # 화면 없는 시험용 플랫폼은 이 프로세스 안의 클립보드라 사용자의 클립보드를 건드리지 않는다
            self.assertTrue(shell_module.qt_clipboard_set("진짜 클립보드 함수가 쓴 글\n둘째 줄"))
            self.assertEqual(QGuiApplication.clipboard().text(), "진짜 클립보드 함수가 쓴 글\n둘째 줄")

    def test_a_write_that_did_not_land_shows_the_failure_notice_and_never_the_copied_look(self):
        window = self.drafted("AI 서비스", clipboard=shell_module.qt_clipboard_set)
        ui, controller = self.ui(window), window.state.drafts
        with mock.patch.object(QGuiApplication, "clipboard", return_value=self.Lost("예전 글")):
            ui.copy["title"].click()
            self.settle(3)
        self.assertEqual((ui.copy["title"].text(), bool(ui.copy["title"].property("copied")), "title" in controller.copied), ("제목 복사", False, False), "쓰지 못했으면 '복사됨' 으로 보이지 않는다")
        self.assertIn(T["drf_copy_failed"], [window.toast.text()])
        with mock.patch.object(QGuiApplication, "clipboard", return_value=self.Kept()):
            ui.copy["title"].click()
            self.settle(3)
        self.assertEqual((ui.copy["title"].text(), ui.copy["title"].property("copied")), ("✓ 제목 복사됨", True), "쓴 뒤 읽어 같으면 복사됨")


class LayoutTest(Base):
    def test_two_columns_from_1280_stacked_below_no_horizontal_scroll_and_nothing_outside_the_window(self):
        window = self.drafted("AI 서비스", size=(1920, 1080))
        for width, height in SIZES:
            with self.subTest(size=(width, height)):
                window.resize(width, height)
                self.settle(8)
                ui = self.ui(window)
                self.assertEqual((window._drafts_side, ui.side), (width >= 1280, width >= 1280))
                inner = window.screen_widget.findChild(QScrollArea)
                self.assertEqual((inner.horizontalScrollBar().maximum(), window.scroll.horizontalScrollBar().maximum()), (0, 0), "가로 스크롤이 없다")
                bar_top = ui.action_bar.mapTo(window, ui.action_bar.rect().topLeft())
                self.assertLessEqual(bar_top.y() + ui.action_bar.height(), window.height())
                self.assertGreaterEqual(ui.editor.height(), 420)
                right = ui.inspect.status.mapTo(window, ui.inspect.status.rect().topLeft()).x()
                left = ui.editor.mapTo(window, ui.editor.rect().topLeft()).x()
                self.assertEqual(right > left + ui.editor.width() // 2, width >= 1280, "넓으면 오른쪽 칸이 편집기 옆에, 좁으면 아래에")
                for button in ui.action_bar.buttons:
                    if button.isVisible():
                        self.assertLessEqual(button.mapTo(window, button.rect().topRight()).x(), window.width())

    def test_the_sidebar_with_six_menus_fits_the_minimum_window(self):
        window = self.make(size=tuple(tokens.LAYOUT["window_min"]))
        height = window.sidebar.minimumSizeHint().height()
        self.assertLessEqual(height, tokens.LAYOUT["window_min"][1] - tokens.FRAME["app_bar"], "사이드바가 최소 창(900×560)의 높이 안에 들어간다")
        self.assertLessEqual(height, 492, "의도적 갱신(P4e, D-282): 메뉴 하나가 늘어 516 이 되는 것을 여백 24px 로 줄여 492 — 늘어나면 이 시험이 알린다")
        self.assertEqual(len(window.nav_buttons), 6)
        self.assertEqual(len(window.sidebar.soon_list.items), 1)
        self.assertLessEqual(window.sidebar.height(), window.height() - tokens.FRAME["app_bar"])

    def test_every_visible_stop_is_reached_by_tab_in_reading_order_and_the_focus_never_lands_on_an_unnamed_widget(self):
        window = self.drafted("AI 서비스", size=(1366, 768))
        ui = self.ui(window)
        self.activate(window)
        ui.back.setFocus(Qt.TabFocusReason)
        self.settle(2)
        seen = []
        for _ in range(60):
            widget = QApplication.focusWidget()
            self.assertIsNotNone(widget)
            seen.append(widget)
            QTest.keyClick(widget, Qt.Key_Tab)
            self.settle(1)
            if QApplication.focusWidget() is seen[0]:
                break
        names = [widget.accessibleName() for widget in seen]
        self.assertTrue(all(name.strip() for name in names), names)
        for wanted in (ui.title, ui.editor, ui.inspect_button, ui.copy["keywords"], ui.copy["tags"], ui.copy["summary"], ui.image_button, ui.actions["title"], ui.actions["body"], ui.actions["all"], ui.actions["open"]):
            self.assertIn(wanted, seen)
        order = [seen.index(widget) for widget in (ui.title, ui.editor, ui.inspect_button, ui.actions["title"], ui.actions["all"])]
        self.assertEqual(order, sorted(order), "읽는 순서")

    def test_the_screen_texts_have_no_forbidden_word_and_the_sample_badge_is_shown_for_sample_data(self):
        window = self.drafted("AI 서비스")
        shown = self.everything(window)
        for value in shown:
            for word in FORBIDDEN_WORDS + text.FORBIDDEN:
                self.assertFalse(word in value, f"{word} / {value[:40]}")
        self.assertEqual(len([button for button in window.screen_widget.findChildren(QAbstractButton) if button.text() == "예시 데이터"]), 1, "예시 데이터 표시는 머리의 단추 하나(누르면 설명)")


# ---- 6) 네이버 글쓰기 열기 -------------------------------------------------------------------------------------------------------------------
class OpenTest(Base):
    def test_the_button_opens_only_the_write_address_of_a_plain_naver_blog_address_and_copies_nothing(self):
        window = self.drafted("AI 서비스")
        ui = self.ui(window)
        self.assertTrue(ui.actions["open"].isEnabled())
        ui.actions["open"].click()
        self.settle(2)
        self.assertEqual(self.opened, ["https://blog.naver.com/example-blog-a?Redirect=Write"])
        self.assertEqual(self.copied, [])
        window.state.drafts.result = drafts.DraftResult(window.state.drafts.result.candidate_id, window.state.drafts.result.body, "naver_a", "정보형", {}, (), "http://blog.naver.com/a", False, False, False, True)
        window.drf_open()
        window.state.drafts.result = drafts.DraftResult(window.state.drafts.result.candidate_id, window.state.drafts.result.body, "naver_a", "정보형", {}, (), "https://evil.example/a", False, False, False, True)
        window.drf_open()
        self.assertEqual(len(self.opened), 1, "다른 주소는 열지 않는다")

    def test_a_browser_that_cannot_open_shows_a_notice(self):
        window = self.drafted("AI 서비스", opener=lambda url: False)
        self.ui(window).actions["open"].click()
        self.settle(3)
        self.assertIn(T["drf_open_failed"], [window.toast.text()])

    def test_without_a_profile_the_button_is_off_with_the_reason_and_opens_nothing(self):
        setup = Setup(self, count=3)
        candidates_provider = candidates_adapter.ServiceCandidatesProvider(context_factory=lambda data_dir=None: setup.ctx)
        window = self.make(candidates=candidates_provider, drafts_provider=setup.provider)
        window.cand_open(setup.engines[0].candidate_id)
        self.settle(6)
        self.make_button(window).click()
        self.assertTrue(self.wait_draft(window))
        button = self.ui(window).actions["open"]
        self.assertFalse(button.isEnabled())
        self.assertEqual(button.toolTip(), T["drf_open_why_profile"])
        window.drf_open()
        self.assertEqual(self.opened, [])


# ---- 7) 진짜 서비스 — 읽기 전용 증명 ---------------------------------------------------------------------------------------------------------
class RealServiceTest(Base):
    def test_the_whole_flow_with_the_real_service_changes_no_file_and_calls_neither_the_network_nor_the_key_store(self):
        setup = Setup(self, profiles=True, count=6)
        candidates_provider = candidates_adapter.ServiceCandidatesProvider(context_factory=lambda data_dir=None: setup.ctx)
        window = self.make(candidates=candidates_provider, drafts_provider=setup.provider)
        before, listing = setup.world.tree(), setup.world.listing()
        with NoNetwork():
            wanted = setup.engines[2]
            window.cand_open(wanted.candidate_id)
            self.settle(6)
            self.make_button(window).click()
            self.assertTrue(self.wait_draft(window))
            ui = self.ui(window)
            self.assertEqual(window.state.drafts.result.candidate_id, wanted.candidate_id)
            self.assertIn(wanted.topic.split(" — ")[0], ui.title.text() + " ".join(window.state.drafts.generated_titles()) + window.state.drafts.draft_body().body_text)
            self.edit_body(window, "\n\n직접 써 보니 정말 좋았습니다.")
            self.button(window, "drf-inspect").click()
            ui.options_toggle.click()
            ui.blog_chips["naver_b"].click()
            self.type_ime(ui.fields["audience"], "예시 독자")                                      # 한글은 입력기 이벤트로(`QTest.keyClicks` 는 한글에서 프로세스가 죽는다)
            self.settle(2)
            ui.copy["body"].click()
            self.settle(3)
            if window.dialog.is_open:
                self.dialog_buttons(window)["그래도 복사"].click()
                self.settle(3)
            ui.actions["open"].click()
            self.settle(2)
            ui.apply.click()
            self.settle(3)
            self.dialog_buttons(window)["다시 만들기"].click()
            self.assertTrue(self.wait_draft(window))
            window.go("topics")
            self.settle(3)
        self.assertEqual((setup.world.tree(), setup.world.listing()), (before, listing), "열기·만들기·고치기·검사·복사·다시 만들기·떠나기가 파일을 하나도 안 바꿨다")
        self.assertEqual(self.opened, ["https://blog.naver.com/exampleaaa?Redirect=Write"])
        self.assertEqual(len(self.copied), 1)
        self.assertIn("직접 써 보니 정말 좋았습니다.", self.copied[0])
        self.assertIsInstance(setup.ctx.keystore, Bomb)


if __name__ == "__main__":
    unittest.main()
