"""주제 후보 화면의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 메뉴·머리 줄·거르기·카드 격자·상세(고정 창·서랍)·후보 만들기(미리 보기 → 확인창 → 쓰기)·읽기 전용 증명·키보드·접근 이름·배치(필수 크기와 최소 창)를 확인한다.
**PySide6 가 없으면 Qt 시험은 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_candidates_core`·`test_ui_candidates_service`, 이 파일의 `SourceRulesTest` 는 PySide6 없이도 돈다).
사용자의 클립보드·보관소·데이터 폴더·설정 파일은 건드리지 않는다(가짜 공급자·임시 폴더의 실제 서비스). 후보·이름은 모두 지어낸 낱말이다.

지키는 것:
  1) 메뉴에 `주제 후보` 가 핵심 작업 묶음(홈 다음)으로 올라 있고 '다음 단계' 목록에는 초안 작성·발행 기록만 남는다. 화면에는 주요 행동이 머리 줄의 `후보 만들기` 하나뿐이고 초안 단추·미완성 화면으로 가는 길은 없다.
  2) 화면을 열고 거르고 찾고 고르고 상세를 열고 창 크기를 바꾸고 `후보 만들기` 를 눌러 미리 보는 것만으로는 **파일이 하나도 안 바뀌고 보관함이 만들어지지 않는다**(임시 폴더 전체 바이트). 쓰는 때는 확인창에서 `만들기` 를 눌렀을 때 하나뿐이다.
  3) 확인창은 처음 포커스가 취소에 있고 취소·Esc·Enter(취소 위)로 닫으면 아무것도 쓰지 않는다. 만들기는 작업 스레드에서 한 번만 돌고 도는 중의 두 번째 요청은 무시된다. 실패해도 목록은 그대로이고 문장은 종류별로 정해진 쉬운 말뿐이다.
  4) 카드는 규격(배지 둘 이하·키워드 칩 셋 이하·제목 둘째 줄·요약 셋째 줄)을 지키고 '제목, 채널, 점수 N점 구간 이름' 한 줄로 읽힌다. 점수가 없으면 링 없이 `점수 계산 전` 이다. 사진 썸네일·즐겨찾기 별·월 검색량·상위노출 같은 말은 없다.
  5) 창 논리 폭 1366 이상이면 고정 상세 창(400~500), 그보다 좁으면 서랍이고 같은 내용을 보인다. 창 크기를 바꿔도 고른 후보가 유지되고 좁아진다고 서랍이 저절로 열리지 않는다. Esc·닫기로 닫으면 포커스가 그 카드로 돌아온다.
  6) 가로 스크롤·글자 잘림이 없고(필수 크기 여섯과 최소 창) 키보드 Tab 은 한 바퀴를 돌며 이름 없는 곳에 닿지 않고 카드 하나가 읽기 정거장 하나다. 키·토큰 모양 글은 화면 어디에도 나오지 않는다.
"""
import ast
import datetime
import importlib.util
import math
import os
import re
import socket
import stat
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from test_ui_candidates_service import World, approved_seeds, candidate  # noqa: E402

from chanceblog_desktop.service import topics as topic_service  # noqa: E402
from chanceblog_desktop.ui import candidates_adapter  # noqa: E402
from chanceblog_desktop.ui.core import candidates as cd  # noqa: E402
from chanceblog_desktop.ui.core import gauges as G  # noqa: E402
from chanceblog_desktop.ui.core import part_rules, services, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core.clock import FixedClock  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import blog_parts, candidate_parts
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module

T = text.T
UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
QT_DIR = UI_DIR / "qt"
NEW_QT = ("candidate_parts.py", "candidate_screen.py")
SIZES = ((1366, 768), (1093, 614), (1536, 864), (1280, 720), (1920, 1080), (900, 560))
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
NOW = datetime.datetime(2026, 11, 6, 20, 10)


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
    def test_the_new_screen_files_cannot_write_open_files_or_reach_the_network_or_the_service(self):
        for name in NEW_QT:
            tree = ast.parse((QT_DIR / name).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported |= {(node.module or "").split(".")[0] or ("." * node.level + (node.module or ""))}
                    imported |= {alias.name for alias in node.names if node.level >= 2 and not node.module}
            self.assertFalse(imported & {"sqlite3", "subprocess", "socket", "urllib", "http", "shutil", "os", "pathlib", "json", "tempfile", "requests", "keyring"}, name)
            names = called_names(tree)
            self.assertFalse(names & {"open", "write_text", "write_bytes", "generate_candidates", "plan_candidates", "list_candidates", "show_candidate", "start_make", "start_preview", "make_candidates", "load_candidates", "unlink", "mkdir", "rename"}, (name, names))
            source = (QT_DIR / name).read_text(encoding="utf-8")
            for forbidden in ("chanceblog_desktop.service", "..service", "..topics", "..topicdb", "..security", "..publish", "..content", "candidates_adapter", "adapters"):
                self.assertNotIn(forbidden, source, f"{name}: 화면 부품은 서비스·엔진·보관소를 직접 부르지 않는다 — {forbidden}")

    def test_only_the_confirmed_dialog_path_starts_the_write(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        self.assertEqual([name for name, function in methods.items() if "start_make" in called_names(function)], ["cand_make_confirmed"], "쓰기를 시작하는 함수는 하나뿐")
        self.assertIn("start_preview", called_names(methods["cand_make"]))
        self.assertNotIn("start_make", called_names(methods["cand_make"]), "머리의 `후보 만들기` 단추는 미리 보기만 시작한다")
        references = [name for name, function in methods.items() for node in ast.walk(function) if isinstance(node, ast.Attribute) and node.attr == "cand_make_confirmed"]
        self.assertEqual(references, ["_show_make_dialog"], "`cand_make_confirmed` 는 확인창을 만드는 곳에서만 쓰인다")
        calls = [node for node in ast.walk(methods["_show_make_dialog"]) if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "show_dialog"]
        self.assertEqual(len(calls), 1)
        keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        self.assertEqual(ast.unparse(keywords["on_ok"]), "self.cand_make_confirmed", "확인창의 `만들기` 만 쓰기를 시작한다")
        self.assertEqual(ast.unparse(keywords["on_cancel"]), "candidates.discard_make", "취소·Esc 는 '확인창을 보였다' 표시를 거둔다")
        self.assertIs(keywords["safe_focus"].value, True, "처음 포커스는 취소")
        self.assertEqual([name for name, function in methods.items() if "_show_make_dialog" in called_names(function)], ["_show_cand_written"], "확인창은 미리 보기가 끝났을 때만 뜬다")

    def test_the_candidate_handlers_of_the_shell_never_touch_providers_files_or_the_network(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        for name, function in methods.items():
            if not (name.startswith(("cand_", "_on_cand", "_show_cand", "_recover_cand", "_render_cand", "reload_cand")) or name == "_show_make_dialog"):
                continue
            source = ast.unparse(function)
            for forbidden in ("provider", "service.", "sqlite3", "subprocess", "socket", "urllib"):
                self.assertNotIn(forbidden, source, f"{name}: {forbidden}")
            self.assertFalse(called_names(function) & {"open", "write", "write_text", "write_bytes", "mkdir", "unlink", "rename", "replace", "connect"}, name)

    def test_show_dialog_calls_the_old_cancel_hook_before_it_builds_the_new_dialog(self):
        """독립 검증(P4d 수정 F1) — 열린 확인창을 다른 대화상자로 바꿀 때 옛 `on_cancel` 을 부르는 줄이 `show_dialog` 안에 있고, 새 대화상자를 만들기(`self.dialog.clear()`) 전에 온다."""
        function = methods_of(QT_DIR / "shell.py", "AppShell")["show_dialog"]
        held = set()                                                                                 # `self._dialog_on_cancel` 을 읽어 담아 둔 지역 이름(= 옛 갈고리)
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and any(isinstance(sub, ast.Attribute) and sub.attr == "_dialog_on_cancel" and isinstance(sub.ctx, ast.Load) for sub in ast.walk(node.value)):
                held |= {sub.id for target in node.targets for sub in ast.walk(target) if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store)}
        self.assertTrue(held, "옛 갈고리를 지역 이름에 담아 둔다")
        old_calls = [node.lineno for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in held]
        builds = [node.lineno for node in ast.walk(function) if isinstance(node, ast.Call) and ast.unparse(node.func) == "self.dialog.clear"]
        self.assertEqual((len(old_calls), len(builds)), (1, 1))
        self.assertLess(old_calls[0], builds[0], "옛 갈고리는 새 대화상자를 만들기 전에 부른다")

    def test_typing_in_the_search_box_does_not_redraw_the_whole_screen(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        self.assertNotIn("render", called_names(methods["cand_query"]), "글 검색은 카드 격자만 새로 놓는다(입력 칸·커서가 안 튄다)")
        self.assertIn("refilter_candidates_live", called_names(methods["cand_query"]))

    def test_the_new_qt_files_use_tokens_only_no_inline_styles_hex_colors_or_font_names(self):
        for name in NEW_QT:
            source = (QT_DIR / name).read_text(encoding="utf-8")
            self.assertNotIn("setStyleSheet", source, name)
            self.assertIsNone(re.search(r"#[0-9a-fA-F]{6}\b", source), f"{name}: 직접 적은 색")
            self.assertNotIn("QFont(", source, name)
            self.assertNotIn("datetime.now", source, name)

    def test_no_forbidden_word_is_in_a_string_literal_of_the_candidate_qt_code(self):
        """독립 검증(P4d 수정 F2-2) — 화면 코드가 문구 표를 거치지 않고 직접 적는 글(부품·셸의 후보 함수·화면 만드는 함수)에도 금지어가 없다. 독스트링은 설명이라 뺀다."""
        words = ("상위노출 보장", "상위노출", "상위 노출", "노출 확률", "검색 1위", "수익 보장", "월 검색량", "검색량", "월간 검색", "보장")
        shell_methods = {name: function for name, function in methods_of(QT_DIR / "shell.py", "AppShell").items()
                         if name.startswith(("cand_", "_on_cand", "_show_cand", "_recover_cand", "_render_cand", "reload_cand")) or name in ("_show_make_dialog", "show_sample_info", "show_dialog")}
        trees = [(name, ast.parse((QT_DIR / name).read_text(encoding="utf-8"))) for name in (*NEW_QT, "screens.py")] + [(name, function) for name, function in shell_methods.items()]
        scanned = 0
        for name, tree in trees:
            docs = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
                    and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                    scanned += 1
                    for word in words:
                        self.assertNotIn(word, node.value, f"{name}: {node.value[:60]}")
        self.assertGreater(scanned, 400, "글 리터럴을 실제로 훑는다")
        self.assertGreaterEqual(len(shell_methods), 25)
        self.assertEqual([word for word in words if word in "월 검색량 기준"], ["월 검색량", "검색량"], "대조: 식이 금지어를 실제로 알아본다")

    def test_the_screen_builder_takes_the_window_and_the_view_model_only_and_the_menu_table_has_the_topic_line(self):
        screens = (QT_DIR / "screens.py").read_text(encoding="utf-8")
        self.assertIn('"topics": _topics_builder', screens)
        self.assertIn("candidates_screen(shell, shell.state.candidates_view())", screens)


# ---- 시험 도구 -----------------------------------------------------------------------------------------------------------------------
class Gated(cd.FakeCandidatesProvider):
    """읽기·미리 보기·만들기가 **시험이 문을 열어 줄 때까지** 기다리는 가짜 공급자 — 시간에 기대지 않고 '도는 중' 을 확실히 본다. 어느 스레드에서 들어왔는지도 기록한다."""

    def __init__(self, *args, hold=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.gates = {name: threading.Event() for name in ("load", "preview", "make")}
        for name, gate in self.gates.items():
            if name not in hold:
                gate.set()
        self.entered = []
        self.threads = {}

    def _enter(self, name, cancelled):
        self.entered.append(name)
        self.threads.setdefault(name, []).append(threading.current_thread())
        if not self.gates[name].wait(30):
            raise AssertionError("시험이 문을 열어 주지 않았다")
        super()._enter(name, cancelled)


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

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def activate(self, window):
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)

    def focus(self, widget):
        self.activate(widget.window())
        widget.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), widget)

    def loaded(self, window):
        return ui_offscreen.wait_until(self.app, lambda: window.state.candidates.state != "loading" and not window.state.candidates.loading, 10)

    def make(self, provider=None, size=(1600, 960), page="topics", wait=True, clipboard=None):
        provider = provider or cd.FakeCandidatesProvider()
        window = shell_module.AppShell(services.FakeHomeProvider(), candidates=provider, autoload=False, clock=FixedClock(NOW), clipboard=clipboard or (lambda value: True))     # 시험은 실제 클립보드를 건드리지 않는다
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        if page == "topics":
            window.go("topics")
            if wait:
                self.assertTrue(self.loaded(window))
            self.settle()
        return window

    def ui(self, window):
        return window.screen_widget.cand_ui

    def ids(self, window):
        return [card["id"] for card in window.state.candidates_view()["grid"]["cards"]]

    def id_of(self, window, part):
        found = [card["id"] for card in window.state.candidates_view()["grid"]["cards"] if part in card["title"]]
        self.assertEqual(len(found), 1, part)
        return found[0]

    def card(self, window, candidate_id):
        return self.ui(window).grid.cards[candidate_id]

    def open_card(self, window, candidate_id):
        QTest.mouseClick(self.card(window, candidate_id), Qt.LeftButton)
        self.settle(8)

    def button(self, root, key):
        found = [button for button in root.findChildren(QAbstractButton) if button.property("focus_key") == key]
        self.assertEqual(len(found), 1, f"{key}: {len(found)}개")
        return found[0]

    def has_button(self, root, key):
        return any(button.property("focus_key") == key for button in root.findChildren(QAbstractButton))

    def texts(self, root):
        found = set()
        for label in root.findChildren(QLabel):
            found.add(label.plain_text() if isinstance(label, (UI.Label, candidate_parts.ClampedLabel)) else label.text())
        return found

    def everything(self, window):
        """창 안의 모든 보이는 글·툴팁·접근 이름·접근 설명."""
        found = []
        for widget in [window, *window.findChildren(QWidget)]:
            found += [widget.toolTip(), widget.accessibleName(), widget.accessibleDescription()]
            if isinstance(widget, (UI.Label, candidate_parts.ClampedLabel)):
                found.append(widget.plain_text())
            elif isinstance(widget, (QLabel, QAbstractButton, QLineEdit)):
                found.append(widget.text())
        return [value for value in found if value]

    def primary_buttons(self, root):
        return [button for button in root.findChildren(QAbstractButton) if button.property("kind") == "primary"]

    def type_query(self, window, value):
        edit = self.button_edit(window)
        edit.setFocus(Qt.OtherFocusReason)
        edit.selectAll()
        QTest.keyClick(edit, Qt.Key_Delete)
        if value:
            event = QInputMethodEvent()                                                            # 한글은 입력기(IME)가 글을 확정하는 것과 같은 이벤트로 넣는다
            event.setCommitString(value)
            QApplication.sendEvent(edit, event)
        self.settle(3)
        return edit

    def button_edit_present(self, window):
        return any(edit.property("focus_key") == "cand-query" for edit in window.screen_widget.findChildren(QLineEdit))

    def button_edit(self, window):
        found = [edit for edit in window.screen_widget.findChildren(QLineEdit) if edit.property("focus_key") == "cand-query"]
        self.assertEqual(len(found), 1)
        return found[0]

    def dialog_buttons(self, window):
        return {button.text(): button for button in window.dialog.findChildren(QAbstractButton)}

    def press_make(self, window):
        self.button(window.screen_widget, "cand-make").click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open or window.state.candidates.preview is not None and not window.state.candidates.busy, 10))
        self.settle()

    def wait_idle(self, window):
        ui_offscreen.wait_until(self.app, lambda: not window.state.candidates.busy and not window.state.candidates.loading and window.state.candidates.pending is None, 10)
        self.settle()

    def notice_texts(self, window):
        return [bar.text.plain_text() for bar in window.screen_widget.findChildren(blog_parts.NoticeBar)]


# ---- 1) 메뉴 ---------------------------------------------------------------------------------------------------------------------------
class MenuTest(Base):
    def test_the_topic_menu_is_in_the_core_group_after_home_and_opens_the_new_screen(self):
        window = self.make(page=None)
        self.assertEqual(list(window.nav_buttons), ["home", "topics", "seed", "blogs", "settings"])
        self.assertEqual(window.nav_buttons["topics"].accessibleName(), "주제 후보 메뉴로 이동")
        self.assertEqual(list(window.sidebar.group_titles), ["core", "data", "system"])
        self.assertEqual(list(S.SCREEN_BUILDERS), ["home", "topics", "seed", "blogs", "settings"])
        window.nav_buttons["topics"].click()
        self.assertTrue(self.loaded(window))
        self.settle()
        self.assertEqual((window.state.page, window.nav_buttons["topics"].isChecked(), window.nav_buttons["home"].isChecked()), ("topics", True, False))
        self.assertEqual(len(self.ui(window).grid.cards), 14)
        self.assertEqual([item.name.text() for item in window.sidebar.soon_list.items], ["초안 작성", "발행 기록"])

    def test_the_screen_has_no_draft_button_and_no_route_to_an_unfinished_screen(self):
        window = self.make()
        requested = []
        real_nav = window.state.nav
        window.state.nav = lambda key: (requested.append(key), real_nav(key))[1]
        self.assertEqual([button.text() for button in window.findChildren(QAbstractButton) if "초안" in button.text() or "발행" in button.text()], [], "초안·발행으로 가는 단추는 이번에 만들지 않는다")
        first = self.ids(window)[0]
        self.open_card(window, first)
        def present():
            return [button for button in [*window.screen_widget.findChildren(QAbstractButton), *window.detail_pane.findChildren(QAbstractButton)] if button.isVisible() and button.isEnabled() and button.property("focus_key")]

        pressed = 0
        for key in sorted({str(button.property("focus_key")) for button in present()} - {"cand-make", "refresh-candidates"}, reverse=True):      # 누를 때마다 화면을 다시 그리므로 열쇠로 다시 찾는다
            found = [button for button in present() if button.property("focus_key") == key]
            if found:
                found[0].click()
                pressed += 1
                self.settle(3)
                if window.state.page != "topics":
                    window.go("topics")
                    self.assertTrue(self.loaded(window))
        self.assertGreater(pressed, 10)
        self.assertEqual(requested, [], "카드·거르기·상세의 어느 단추도 화면 이동을 요청하지 않는다")


# ---- 2) 머리·카드 ----------------------------------------------------------------------------------------------------------------------
class ScreenTest(Base):
    def test_the_header_has_the_only_primary_action_the_sample_mark_and_the_refresh_button(self):
        window = self.make()
        page = window.screen_widget
        primary = self.primary_buttons(page)
        self.assertEqual([button.text() for button in primary], ["후보 만들기"], "주요 행동은 머리의 `후보 만들기` 하나")
        self.assertEqual(primary[0].toolTip(), T["cand_make_tip"])
        self.assertEqual(primary[0].accessibleDescription(), T["cand_make_tip"])
        refresh = self.button(page, "refresh-candidates")
        self.assertEqual((refresh.accessibleName(), refresh.toolTip()), ("후보 다시 불러오기", "후보 다시 불러오기"))
        self.assertEqual(len([b for b in window.findChildren(QAbstractButton) if b.accessibleName() == "예시 데이터"]), 1)
        self.assertIn("주제 후보", self.texts(page))
        self.assertIn(T["cand_sub"], self.texts(page))

    def test_every_sample_card_follows_the_card_spec_and_is_one_reading_stop(self):
        window = self.make()
        view = window.state.candidates_view()["grid"]["cards"]
        grid = self.ui(window).grid
        self.assertEqual((len(grid.cards), set(grid.cards)), (14, {card["id"] for card in view}))
        for card_vm in view:
            card = grid.cards[card_vm["id"]]
            self.assertTrue(card.isVisible())
            self.assertTrue(1 <= len(card.badges) <= 2, card_vm["title"])                         # 작업 상태는 늘 있고 의미 배지는 둘까지
            self.assertLessEqual(len(card.chips), 3)
            self.assertEqual(card.more_chip is not None, card_vm["more"] > 0)
            if card.more_chip is not None:
                self.assertEqual(card.more_chip.text(), f"+{card_vm['more']}")
            self.assertEqual((card.accessibleName(), card.accessibleDescription()), (card_vm["a11y"], card_vm["desc"]))
            self.assertEqual(card.focusPolicy(), Qt.StrongFocus)
            self.assertEqual([w for w in card.findChildren(QWidget) if w.focusPolicy() != Qt.NoFocus], [], "카드 안의 글·배지·링은 따로 정거장이 아니다")
            self.assertGreaterEqual(card.height(), tokens.SIZE["hit"])
            self.assertEqual(card.sample_label.text(), "예시")
            self.assertLessEqual(card.title_label.height(), math.ceil(2 * card.title_label._pitch()) + 1, "제목은 둘째 줄까지")
            self.assertLessEqual(card.summary_label.height(), math.ceil(3 * card.summary_label._pitch()) + 1, "요약은 셋째 줄까지")
            self.assertEqual(card.channel_label.text(), card_vm["channel"]["name"])
            self.assertRegex(card_vm["a11y"], r"^.+, .+, (점수 \d+점 .+|점수 계산 전)(, 예시)?$")
            if card_vm["ring"]:
                self.assertIsNotNone(card.score.ring)
                self.assertEqual((card.score.ring.view.text, card.score.band_label.plain_text()), (card_vm["score_text"], G.score_band(card_vm["score"]).name), "홈과 같은 점수·같은 구간 이름")
            else:
                self.assertIsNone(card.score.ring, "점수가 없으면 링을 그리지 않는다")
                self.assertEqual(card.score.missing_label.plain_text(), "점수 계산 전")

    def test_the_card_uses_a_topic_icon_with_a_gradient_and_never_a_photo_or_a_favorite_star(self):
        window = self.make()
        for card in self.ui(window).grid.cards.values():
            self.assertIsInstance(card.image, candidate_parts.CardImage)
            self.assertEqual(card.image.toolTip(), T["cand_image_state"])
            self.assertEqual(card.image.height(), tokens.CARD["image_h"])
            self.assertEqual([button for button in card.findChildren(QAbstractButton)], [], "카드 안에는 즐겨찾기 별 같은 눌리는 부품이 없다")
        for word in ("썸네일", "즐겨찾기", "★", "☆", "월 검색량", "상위노출", "상위 노출", "노출 확률"):
            self.assertFalse([value for value in self.everything(window) if word in value], word)

    def test_a_long_title_and_long_keywords_are_cut_and_nothing_overflows_the_card(self):
        provider = cd.FakeCandidatesProvider()
        provider.candidates.append(cd.build_candidate(90, "예시 아주 긴 제목 " * 18, "naver_a", "high", seed_id="EX001", keywords=tuple("예시 아주 긴 키워드 " * 3 + str(number) for number in range(6)),
                                                      reasons=("예시 아주 긴 이유 " * 18,)))
        window = self.make(provider)
        long_id = self.id_of(window, "예시 아주 긴 제목")
        card = self.card(window, long_id)
        self.assertLessEqual(len(card.chips), 3)
        self.assertTrue(all(len(chip.text()) <= tokens_chip_limit() + 1 for chip in card.chips), [chip.text() for chip in card.chips])
        self.assertLessEqual(card.title_label.height(), math.ceil(2 * card.title_label._pitch()) + 1, "긴 제목도 둘째 줄까지(넘치면 줄임표로 그려진다)")
        self.assertEqual(card.title_label.toolTip(), card.title_label.plain_text(), "전체 제목은 툴팁에 있다")
        self.assertLessEqual(len(card.summary_label.plain_text()), 121)
        self.assertLessEqual(card.summary_label.height(), math.ceil(3 * card.summary_label._pitch()) + 1)
        self.assertEqual(ui_offscreen.find_clipping(window), [])
        self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)

    def test_a_key_shaped_text_is_masked_on_the_card_and_in_the_detail_everywhere_on_the_screen(self):
        provider = cd.FakeCandidatesProvider()
        provider.candidates.append(cd.build_candidate(91, f"예시 키 모양 제목 {KEY_SHAPED}", "naver_a", "high", seed_id="EX001", keywords=(f"예시 낱말 {KEY_SHAPED}", "예시 보조 가"), reasons=(f"예시 이유 {KEY_SHAPED} 가 들어 있어요",)))
        window = self.make(provider)
        key_id = self.id_of(window, "예시 키 모양 제목")
        self.open_card(window, key_id)
        self.assertFalse([value for value in self.everything(window) if KEY_SHAPED in value], "키 모양 글이 화면(글·툴팁·접근 이름)에 나왔다")
        window.resize(1280, 720)
        self.settle(8)
        self.open_card(window, key_id)
        self.assertFalse([value for value in self.everything(window) if KEY_SHAPED in value], "서랍에서도 마찬가지")


def tokens_chip_limit():
    from chanceblog_desktop.ui.core import candidate_rules
    return candidate_rules.CHIP_LIMIT


# ---- 3) 거르기·찾기 --------------------------------------------------------------------------------------------------------------------
class FilterTest(Base):
    def test_the_chips_narrow_the_cards_the_result_line_follows_and_the_reset_brings_them_back(self):
        window = self.make()
        self.assertFalse(self.ui(window).reset.isVisibleTo(window), "거르지 않았으면 `거르기 풀기` 는 숨어 있다")
        self.button(window.screen_widget, "cand:channel:naver_a").click()
        self.settle(4)
        self.assertEqual(len(self.ui(window).grid.cards), 7)
        self.assertEqual(self.ui(window).result.plain_text(), "7장을 보여 줘요(조건에 맞는 후보 7개 · 전체 14개)")
        self.assertTrue(self.ui(window).reset.isVisibleTo(window))
        self.assertTrue(self.button(window.screen_widget, "cand:channel:naver_a").isChecked())
        self.assertFalse(self.has_button(window.screen_widget, "cand:band:high"), "점수 구간 칩은 `더 거르기` 뒤에 있다")
        self.button(window.screen_widget, "cand-filter-more").click()
        self.settle(4)
        self.button(window.screen_widget, "cand:band:high").click()
        self.settle(4)
        self.assertEqual(set(self.ui(window).grid.cards), set(self.ids(window)))
        self.assertTrue(0 < len(self.ui(window).grid.cards) < 7)
        self.button(window.screen_widget, "cand-filter-reset").click()
        self.settle(4)
        self.assertEqual((len(self.ui(window).grid.cards), self.ui(window).reset.isVisibleTo(window)), (14, False))

    def test_the_status_band_and_cluster_chips_each_narrow_by_their_own_rule_and_the_band_and_cluster_rows_hide_behind_more(self):
        window = self.make()
        for hidden in ("cand:cluster:pc-parts", "cand:band:none"):
            self.assertFalse(self.has_button(window.screen_widget, hidden), f"{hidden}: 점수 구간·주제 묶음 칩은 `더 거르기` 뒤에 있다")
        self.button(window.screen_widget, "cand:status:NEW").click()
        self.settle(4)
        self.assertEqual(len(self.ui(window).grid.cards), 10)
        self.button(window.screen_widget, "cand:status:all").click()
        self.settle(4)
        self.button(window.screen_widget, "cand-filter-more").click()
        self.settle(4)
        self.assertEqual(self.button(window.screen_widget, "cand-filter-more").text(), "더 거르기 닫기")
        self.button(window.screen_widget, "cand:band:none").click()
        self.settle(4)
        self.assertEqual(len(self.ui(window).grid.cards), 1)
        self.assertIsNone(next(iter(self.ui(window).grid.cards.values())).score.ring, "점수 계산 전 구간에는 링이 없다")
        self.button(window.screen_widget, "cand:band:all").click()
        self.settle(4)
        self.button(window.screen_widget, "cand:cluster:pc-parts").click()
        self.settle(4)
        self.assertEqual(len(self.ui(window).grid.cards), 2)
        self.button(window.screen_widget, "cand-filter-reset").click()
        self.settle(4)
        self.assertTrue(self.has_button(window.screen_widget, "cand:band:high"), "`더 거르기` 를 열어 둔 채로 풀어도 열려 있다")
        self.button(window.screen_widget, "cand-filter-more").click()
        self.settle(4)
        self.assertFalse(self.has_button(window.screen_widget, "cand:band:high"), "닫으면 다시 숨는다")
        self.button(window.screen_widget, "cand-filter-more").click()
        self.settle(4)
        for chip in window.screen_widget.findChildren(QAbstractButton):
            if chip.property("chip"):
                self.assertTrue(chip.accessibleName().strip())
                self.assertGreaterEqual(chip.height(), tokens.SIZE["hit"])

    def test_searching_keeps_the_screen_and_the_typing_place_and_narrows_the_cards_by_title_or_keyword(self):
        window = self.make()
        page, grid = window.screen_widget, self.ui(window).grid
        edit = self.type_query(window, "영양제")
        self.assertIs(window.screen_widget, page, "글을 치는 동안 화면을 다시 그리지 않는다")
        self.assertIs(self.ui(window).grid, grid)
        self.assertIs(QApplication.focusWidget(), edit, "입력하던 자리가 사라지지 않는다")
        self.assertEqual(edit.text(), "영양제")
        self.assertEqual(len(grid.cards), 2)
        self.assertEqual(self.ui(window).result.plain_text(), "2장을 보여 줘요(조건에 맞는 후보 2개 · 전체 14개)")
        self.assertTrue(self.ui(window).reset.isVisibleTo(window))
        self.type_query(window, "예시 낱말 마")                                                       # 키워드로도 찾는다(제목에는 없는 낱말)
        self.assertEqual(len(grid.cards), 1)
        self.type_query(window, "")
        self.assertEqual((len(grid.cards), self.ui(window).reset.isVisibleTo(window)), (14, False))
        self.assertIs(window.screen_widget, page)

    def test_a_search_with_no_match_shows_the_filtered_empty_card_and_the_reset_clears_the_box(self):
        window = self.make()
        self.type_query(window, "없는낱말")
        grid = self.ui(window).grid
        self.assertEqual(len(grid.cards), 0)
        self.assertIn(T["cand_none_found"], self.texts(window.screen_widget))
        reset = [b for b in window.screen_widget.findChildren(QAbstractButton) if b.property("focus_key") == "cand-empty-reset"]
        self.assertEqual(len(reset), 1)
        self.assertEqual([b.text() for b in self.primary_buttons(window.screen_widget)], ["후보 만들기"], "빈 안내에 주요 단추를 더하지 않는다")
        reset[0].click()
        self.settle(6)
        self.assertEqual(self.button_edit(window).text(), "")
        self.assertEqual(len(self.ui(window).grid.cards), 14)

    def test_the_three_empty_states_each_say_their_own_thing_and_never_add_a_primary_button(self):
        cases = {"no_store": T["cand_empty_nostore_title"], "empty": T["cand_empty_none_title"], "old_structure": T["cand_empty_old_title"]}
        seen = set()
        for scenario, title in cases.items():
            window = self.make(cd.FakeCandidatesProvider(scenario), size=(1366, 768))
            self.assertIn(title, self.texts(window.screen_widget), scenario)
            self.assertEqual([b.text() for b in self.primary_buttons(window.screen_widget)], ["후보 만들기"], scenario)
            self.assertEqual(len(self.ui(window).grid.cards), 0)
            self.assertFalse(window.detail_pane.isVisible(), f"{scenario}: 고를 후보가 하나도 없으면 상세 창을 두지 않는다")
            self.assertFalse(self.has_button(window.screen_widget, "cand:channel:all") or self.button_edit_present(window), f"{scenario}: 거를 후보가 없으면 거르기 카드도 없다")
            seen.add(title)
            window.close()
        self.assertEqual(len(seen), 3, "서로 다른 안내")

    def test_many_candidates_draw_one_page_of_cards_and_the_more_button_adds_the_next_page(self):
        window = self.make(cd.FakeCandidatesProvider("many"))
        self.assertEqual(len(self.ui(window).grid.cards), 24, "수백 개여도 카드는 한 번에 24장")
        more = self.button(window.screen_widget, "cand-more")
        self.assertEqual(more.text(), "24개 더 보기")
        more.click()
        self.settle(6)
        self.assertEqual(len(self.ui(window).grid.cards), 48)
        self.assertTrue(self.has_button(window.screen_widget, "cand-more"))


# ---- 4) 읽는 중·오류 -------------------------------------------------------------------------------------------------------------------
class StateTest(Base):
    def test_while_reading_a_skeleton_shows_and_the_make_and_refresh_buttons_are_off_then_the_cards_come(self):
        provider = Gated(hold=("load",))
        window = self.make(provider, wait=False)
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: "load" in provider.entered, 5))
        self.settle(4)
        page = window.screen_widget
        self.assertEqual(window.state.candidates.state, "loading")
        self.assertEqual(len([w for w in page.findChildren(QWidget) if w.accessibleName() == T["cand_loading_a11y"]]), 1, "읽는 중 자리 표시 하나")
        self.assertIn(T["cand_loading"], self.texts(page))
        make, refresh = self.button(page, "cand-make"), self.button(page, "refresh-candidates")
        self.assertFalse(make.isEnabled() or refresh.isEnabled())
        self.assertEqual(make.toolTip(), T["cand_make_why_loading"])
        self.assertNotIn(threading.current_thread(), provider.threads["load"], "읽기는 작업 스레드에서 돈다")
        self.assertFalse(window.detail_pane.isVisible(), "읽는 동안에는 상세 창이 없다 — 본문이 넓게 안내한다")
        provider.gates["load"].set()
        self.assertTrue(self.loaded(window))
        self.settle()
        self.assertEqual(len(self.ui(window).grid.cards), 14)
        self.assertTrue(window.detail_pane.isVisible())
        self.assertTrue(self.button(window.screen_widget, "cand-make").isEnabled())

    def test_an_unreadable_store_shows_one_state_card_with_the_easy_sentence_and_no_raw_error_text(self):
        window = self.make(cd.FakeCandidatesProvider("error"))
        page = window.screen_widget
        visible = [label.plain_text() if isinstance(label, UI.Label) else label.text() for label in page.findChildren(QLabel) if label.isVisible()]
        self.assertIn(T["cand_error_title"], visible)
        self.assertIn(T["cand_error_desc"], visible)
        self.assertFalse([value for value in visible if "SAMPLE_CANDIDATES_UNREADABLE" in value or "Traceback" in value or "Error" in value], "코드·예외 글은 접힌 진단 정보 안에만 있다")
        self.assertEqual([b.text() for b in page.findChildren(QAbstractButton) if b.isVisible() and b.text() == T["cand_error_btn"]], [T["cand_error_btn"]])
        make = self.button(page, "cand-make")
        self.assertFalse(make.isEnabled())
        self.assertEqual(make.toolTip(), T["cand_make_why_error"])
        self.assertFalse(window.detail_pane.isVisible(), "읽지 못했으면 상세 창도 없다")
        self.assertIsNone(self.ui(window).grid, "읽지 못했으면 카드 격자도 거르기 카드도 없다")
        self.assertFalse(self.has_button(page, "cand:channel:all"))

    def test_the_refresh_button_reads_again_without_writing_and_a_second_press_while_reading_is_refused(self):
        provider = Gated()
        window = self.make(provider)
        provider.gates["load"].clear()
        before = list(provider.entered)
        self.button(window.screen_widget, "refresh-candidates").click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: len(provider.entered) == len(before) + 1, 5))
        self.assertFalse(window.reload_candidates(), "읽는 중에는 두 번째 읽기를 시작하지 않는다")
        provider.gates["load"].set()
        self.assertTrue(self.loaded(window))
        self.assertEqual(provider.entered[len(before):], ["load"])
        self.assertNotIn("make", provider.entered)


# ---- 5) 상세(고정 창·서랍) --------------------------------------------------------------------------------------------------------------
class DetailTest(Base):
    SECTIONS = ("점수 구성", "추천 이유", "최근 관심도(상대값)", "Seed 출처", "안전 표시", "기본 정보")

    def test_choosing_a_card_shows_the_fixed_pane_at_1600_and_1366_with_every_section_and_no_action_but_copy(self):
        for size, width in (((1600, 960), 420), ((1366, 768), 400)):
            window = self.make(size=size)
            pane = window.detail_pane
            self.assertTrue(pane.isVisible())
            self.assertEqual(pane.width(), width, size)
            self.assertIn(T["cand_detail_empty_title"], self.texts(pane), "아무것도 안 골랐을 때의 안내")
            self.assertEqual([button for button in pane.findChildren(QAbstractButton)], [], "안내에는 단추가 없다")
            first = self.id_of(window, "예시 후보 가 —")
            self.open_card(window, first)
            for key, card in self.ui(window).grid.cards.items():
                self.assertEqual(bool(card.property("selected")), key == first, "선택된 카드는 하나")
            labels = self.texts(pane)
            for title in self.SECTIONS:
                self.assertIn(title, labels, (size, title))
            self.assertIn("예시 후보 가 — 순서대로 따라 하는 안내", labels)
            self.assertEqual(self.primary_buttons(pane), [], "상세에는 주요 단추가 없다(후보 상태·초안 행동은 이번에 만들지 않는다)")
            self.assertEqual(sorted(button.property("focus_key") for button in pane.findChildren(QAbstractButton)), ["detail-close", "detail-copy"])
            for word in ("월 검색량", "상위노출", "상위 노출", "노출 확률"):
                self.assertFalse([value for value in self.everything(window) if word in value], word)
            self.assertIn("최근 관심도(상대값)", labels)
            self.assertEqual(pane.scroll.horizontalScrollBar().maximum(), 0)
            window.close()

    def test_the_detail_ring_is_the_detail_size_and_the_final_score_matches_the_card(self):
        window = self.make()
        first = self.id_of(window, "예시 후보 가 —")
        card_ring = self.card(window, first).score.ring
        self.open_card(window, first)
        rings = [ring for ring in window.detail_pane.findChildren(candidate_parts.ScoreWithLabel)]
        self.assertEqual(len(rings), 1)
        self.assertEqual((rings[0].ring.view.text, rings[0].ring.width()), (card_ring.view.text, G.ring_pixels("detail")))
        self.assertTrue(68 <= rings[0].ring.width() <= 80)
        self.assertIn(f"최종 점수 {card_ring.view.text}점", self.texts(window.detail_pane))

    def test_the_score_parts_show_the_engine_values_and_unrated_parts_say_before_evaluation_without_a_bar(self):
        window = self.make()
        self.open_card(window, self.id_of(window, "예시 영양제 고르는 기준"))                          # 시기·차별성을 평가하지 못한 예
        rows = window.detail_pane.findChildren(candidate_parts.FactorRow)
        self.assertEqual(len(rows), 6)
        missing = [row for row in rows if row.track is None]
        self.assertEqual((len(missing), {row.value_label.plain_text() for row in missing}), (2, {"평가 전"}), "평가하지 못한 항목은 0점 막대가 아니라 `평가 전`")
        for row in rows:
            if row.track is not None:
                self.assertRegex(row.value_label.plain_text(), r"^\d+점$")
                self.assertTrue(row.weight_label.plain_text().startswith("가중치"))
        self.assertIn(T["cand_factor_note"], self.texts(window.detail_pane))

    def test_a_card_without_a_score_shows_no_ring_and_the_words_before_calculation_in_the_detail_too(self):
        window = self.make()
        none_id = self.id_of(window, "예시 후보 아 —")
        self.assertIsNone(self.card(window, none_id).score.ring)
        self.open_card(window, none_id)
        top = window.detail_pane.findChildren(candidate_parts.ScoreWithLabel)
        self.assertEqual(len(top), 1)
        self.assertIsNone(top[0].ring, "0점 링을 그리지 않는다")
        self.assertEqual(top[0].missing_label.plain_text(), "점수 계산 전")
        self.assertIn(T["cand_factor_none"], self.texts(window.detail_pane))
        self.assertIn(T["cand_reason_none"], self.texts(window.detail_pane))

    def test_closing_by_the_button_or_escape_clears_the_choice_and_gives_the_focus_back_to_the_card(self):
        window = self.make()
        first = self.id_of(window, "예시 후보 가 —")
        for how in ("button", "escape"):
            card = self.card(window, first)
            self.focus(card)
            QTest.keyClick(card, Qt.Key_Return)
            self.settle(8)
            self.assertEqual(window.state.candidates.selected, first)
            self.assertIsNotNone(window.detail_close)
            if how == "button":
                window.detail_close.click()
            else:
                window.escape()
            self.settle(8)
            self.assertIsNone(window.state.candidates.selected, how)
            self.assertIn(T["cand_detail_empty_title"], self.texts(window.detail_pane))
            self.assertFalse([c for c in self.ui(window).grid.cards.values() if c.property("selected")])
            self.assertIs(QApplication.focusWidget(), self.card(window, first), f"{how}: 포커스가 열었던 카드로 돌아온다")

    def test_below_1366_the_same_detail_is_a_drawer_and_escape_gives_the_focus_back_to_the_card(self):
        window = self.make(size=(1280, 720))
        self.assertFalse(window.detail_pane.isVisible())
        first = self.id_of(window, "예시 후보 가 —")
        card = self.card(window, first)
        self.focus(card)
        QTest.keyClick(card, Qt.Key_Space)
        self.settle(10)
        self.assertTrue(window.drawer.is_open)
        labels = self.texts(window.drawer)
        for title in self.SECTIONS:
            self.assertIn(title, labels, title)
        self.assertEqual(window.drawer.accessibleName(), window.state.candidates.detail_view()["a11y"])
        self.assertIs(QApplication.focusWidget(), window.drawer_close, "서랍이 열리면 닫기 단추에 포커스가 간다")
        for _ in range(12):                                                                          # Tab 은 서랍 안에서만 돈다(가둠)
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab)
            self.settle(1)
            self.assertTrue(window.drawer.isAncestorOf(QApplication.focusWidget()) or QApplication.focusWidget() is window.drawer_close)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Escape)
        self.settle(10)
        self.assertFalse(window.drawer.is_open)
        self.assertIsNone(window.state.candidates.selected)
        self.assertIs(QApplication.focusWidget(), self.card(window, first))

    def test_the_choice_survives_every_size_change_and_shrinking_never_opens_the_drawer(self):
        window = self.make(size=(1920, 1080))
        first = self.id_of(window, "예시 후보 가 —")
        self.open_card(window, first)
        heading = "예시 후보 가 — 순서대로 따라 하는 안내"
        for width in (1600, 1500, 1366, 1365, 1200, 900, 1093, 1366, 1600, 1920):
            window.resize(width, 800)
            self.settle(10)
            layout = part_rules.detail_layout(window.width())
            self.assertEqual(window.state.candidates.selected, first, width)
            self.assertEqual(self.ui(window).columns, layout.columns, width)
            self.assertTrue(self.card(window, first).property("selected"), width)
            if layout.mode == "fixed":
                self.assertTrue(window.detail_pane.isVisible(), width)
                self.assertEqual(window.detail_pane.width(), layout.detail_width, width)
                self.assertIn(heading, self.texts(window.detail_pane), width)
                self.assertFalse(window.drawer.is_open, width)
            else:
                self.assertFalse(window.detail_pane.isVisible(), width)
                self.assertFalse(window.drawer.is_open, f"{width}: 좁아졌다고 서랍이 저절로 열리지 않는다")
        window.resize(1100, 800)
        self.settle(8)
        self.open_card(window, first)                                                                # 서랍은 카드를 다시 눌러야 열린다
        self.assertTrue(window.drawer.is_open)
        self.assertIn(heading, self.texts(window.drawer))
        window.resize(1500, 800)
        self.settle(10)
        self.assertFalse(window.drawer.is_open, "넓어지면 서랍은 닫히고 고정 창에 같은 후보가 보인다")
        self.assertIn(heading, self.texts(window.detail_pane))
        self.assertEqual(window.state.candidates.selected, first)

    def test_leaving_the_screen_hides_the_pane_and_the_drawer_and_coming_back_keeps_the_choice(self):
        window = self.make(size=(1366, 768))
        first = self.id_of(window, "예시 후보 가 —")
        self.open_card(window, first)
        self.assertTrue(window.detail_pane.isVisible())
        window.go("settings")
        self.settle(6)
        self.assertFalse(window.detail_pane.isVisible())
        window.go("topics")
        self.assertTrue(self.loaded(window))
        self.settle(8)
        self.assertEqual(window.state.candidates.selected, first)
        self.assertTrue(window.detail_pane.isVisible())
        window.resize(1100, 700)
        self.settle(8)
        self.assertFalse(window.detail_pane.isVisible())
        self.open_card(window, first)                                                                # 서랍 방식 — 카드를 눌러야 열린다
        self.assertTrue(window.drawer.is_open)
        window.go("seed")
        self.settle(6)
        self.assertFalse(window.drawer.is_open, "다른 화면으로 가면 후보 상세 서랍은 닫힌다")
        self.assertFalse(window.state.candidates.opened)
        self.assertEqual(window.state.candidates.selected, first, "고른 후보는 그대로")
        window.go("topics")
        self.assertTrue(self.loaded(window))
        self.settle(8)
        self.assertFalse(window.drawer.is_open, "돌아와도 서랍이 저절로 열려 있지 않다(카드를 다시 눌러야 한다)")
        self.assertEqual(window.state.candidates.selected, first)
        self.assertTrue(self.card(window, first).property("selected"))

    def test_copying_the_number_puts_only_the_short_number_on_the_clipboard(self):
        copied = []
        window = self.make(clipboard=lambda value: copied.append(value) or True)
        self.open_card(window, self.id_of(window, "예시 후보 가 —"))
        self.button(window.detail_pane, "detail-copy").click()
        self.settle(4)
        self.assertEqual(len(copied), 1)
        self.assertRegex(copied[0], r"^[0-9a-f]{8}$", "복사되는 것은 짧은 번호뿐 — 내부 번호·채널 이름이 아니다")
        self.assertTrue(window.toast.isVisible())
        self.assertEqual(window.toast.text(), T["cand_copied"])
        failing = self.make(clipboard=lambda value: False)
        self.open_card(failing, self.id_of(failing, "예시 후보 가 —"))
        self.button(failing.detail_pane, "detail-copy").click()
        self.settle(4)
        self.assertEqual(failing.toast.text(), T["cand_copy_failed"])

    def test_the_safety_section_shows_the_engine_sentences_and_the_stop_sentence_for_an_auto_draft_stop(self):
        window = self.make()
        stop_id = self.id_of(window, "예시 영양제 먹으면 바로 낫는 방법")
        card = self.card(window, stop_id)
        self.assertIn(T["cand_badge_stop"], [badge.text() for badge in card.badges] + [b.text() for b in card.findChildren(QLabel)])
        self.open_card(window, stop_id)
        labels = self.texts(window.detail_pane)
        self.assertIn(T["cand_safety_stop"], labels)
        self.assertIn(T["cand_level_error"], labels)
        self.assertNotIn(T["cand_safety_none"], labels)
        plain_id = self.id_of(window, "예시 후보 다 —")                                                  # 협업 표시·건강 표시가 없는 후보
        self.open_card(window, plain_id)
        self.assertIn(T["cand_safety_none"], self.texts(window.detail_pane))
        self.assertNotIn(T["cand_safety_stop"], self.texts(window.detail_pane))


# ---- 6) 배치 ---------------------------------------------------------------------------------------------------------------------------
class LayoutTest(Base):
    def columns_seen(self, window):
        grid = self.ui(window).grid
        return len({round(card.mapTo(grid, card.rect().topLeft()).x() / 10) for card in grid.cards.values()})

    def test_columns_and_the_pane_follow_the_width_rule_and_nothing_overflows_at_every_required_size(self):
        window = self.make(size=SIZES[0])
        first = self.ids(window)[0]
        for size in SIZES:
            for chosen in (False, True):
                window.resize(*size)
                self.settle(8)
                if chosen:
                    self.open_card(window, first)
                else:
                    window.state.candidates.close_detail()
                    window.render()
                    self.settle(6)
                ui_offscreen.wait_until(self.app, lambda: window.scroll.horizontalScrollBar().maximum() == 0, 2)
                where = (size, chosen)
                layout = part_rules.detail_layout(window.width())
                self.assertEqual(self.ui(window).columns, layout.columns, where)
                self.assertEqual(self.columns_seen(window), layout.columns, where)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, where)
                self.assertLessEqual(window.screen_widget.width(), window.scroll.viewport().width(), where)
                self.assertEqual(window.detail_pane.isVisible(), layout.mode == "fixed", where)
                if layout.mode == "fixed":
                    self.assertEqual(window.detail_pane.width(), layout.detail_width, where)
                    self.assertEqual(window.detail_pane.scroll.horizontalScrollBar().maximum(), 0, where)
                    self.assertLessEqual(window.detail_pane.geometry().right(), window.width(), where)
                self.assertEqual(ui_offscreen.find_clipping(window), [], where)
                for card in self.ui(window).grid.cards.values():
                    self.assertGreaterEqual(card.width(), tokens.CARD["min_w"], where)
                    if layout.columns == 3:
                        self.assertLessEqual(card.width(), tokens.CARD["w_range"][1] + 1, where)

    def test_three_column_cards_are_at_most_300_wide_and_the_grid_is_centered(self):
        window = self.make(size=(1920, 1080))
        grid = self.ui(window).grid
        cards = list(grid.cards.values())
        widths = {card.width() for card in cards}
        self.assertLessEqual(max(widths), 301)
        holder = grid.holder
        left = holder.mapTo(grid, holder.rect().topLeft()).x()
        right = grid.width() - (left + holder.width())
        self.assertLessEqual(abs(left - right), 2, "격자는 가운데에 놓인다")

    def test_the_card_height_stays_within_a_readable_range_at_the_two_column_and_three_column_layouts(self):
        for size in ((1920, 1080), (1366, 768)):
            window = self.make(size=size)
            heights = [card.height() for card in self.ui(window).grid.cards.values()]
            self.assertTrue(min(heights) >= 250 and max(heights) <= 460, (size, min(heights), max(heights)))
            window.close()

    def test_the_first_row_of_cards_is_visible_without_scrolling_at_1366_by_768(self):
        window = self.make(size=(1366, 768))
        cards = self.ids(window)
        top = self.card(window, cards[0])
        viewport = window.scroll.viewport()
        origin = top.mapTo(viewport, top.rect().topLeft()).y()
        self.assertLess(origin, viewport.height(), "카드 격자의 시작이 첫 화면 안에 있다")


# ---- 7) 후보 만들기 -------------------------------------------------------------------------------------------------------------------
class MakeFlowTest(Base):
    def test_pressing_make_only_previews_and_the_dialog_asks_first_with_cancel_focused(self):
        provider = Gated()
        window = self.make(provider)
        self.assertEqual(provider.entered, ["load"])
        self.press_make(window)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(provider.entered, ["load", "preview"], "단추를 누른 것만으로는 미리 보기뿐 — 쓰기는 부르지 않았다")
        labels = self.texts(window.dialog)
        self.assertIn("후보를 최대 4개 만들까요?", labels)                                                # 의도적 갱신(P4d, D-277): 미리 본 개수라 `최대`
        body = next(label for label in labels if "새 후보를 최대 4개 만들어요" in label)
        for part in ("예시 블로그 가 2개", "예시 블로그 나 2개", "승인한 Seed 3개에서 만들어요. 승인 전 Seed 1개는 쓰이지 않아요.", "지워지거나 바뀌지 않아요", "키나 네트워크는 쓰지 않아요", "아직 연결 전"):
            self.assertIn(part, body)
        buttons = self.dialog_buttons(window)
        self.assertEqual(sorted(buttons), ["만들기", "취소"])
        self.assertIs(window.dialog_default, buttons["취소"], "처음 포커스는 취소 — Enter 를 잘못 눌러도 만들지 않는다")
        self.assertIs(QApplication.focusWidget(), buttons["취소"])
        self.assertEqual(self.primary_buttons(window.dialog), [buttons["만들기"]])
        self.assertEqual(len(self.ui(window).grid.cards), 14, "미리 보기는 목록을 바꾸지 않는다")
        self.assertEqual(provider.made_batches, 0)

    def test_cancel_enter_on_cancel_and_escape_each_leave_everything_as_it_was(self):
        for how in ("cancel", "enter", "escape"):
            provider = Gated()
            window = self.make(provider, size=(1366, 768))
            self.press_make(window)
            self.assertTrue(window.dialog.is_open, how)
            if how == "cancel":
                self.dialog_buttons(window)["취소"].click()
            elif how == "enter":
                QTest.keyClick(window.dialog_default, Qt.Key_Return)
            else:
                window.escape()
            self.settle(6)
            self.assertFalse(window.dialog.is_open, how)
            self.assertEqual(provider.entered, ["load", "preview"], f"{how}: 쓰지 않았다")
            self.assertEqual((provider.made_batches, len(self.ui(window).grid.cards), window.state.candidates.make_asked), (0, 14, False), how)
            self.assertEqual(window.state.candidates.start_make()[0], "unconfirmed", f"{how}: 취소한 뒤 다시 부르는 길도 막혀 있다")
            self.assertEqual(provider.entered, ["load", "preview"], how)
            window.close()

    def test_ok_makes_once_on_a_worker_thread_then_shows_the_result_and_reads_the_longer_list(self):
        provider = Gated()
        window = self.make(provider)
        self.press_make(window)
        self.dialog_buttons(window)["만들기"].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: provider.made_batches == 1 and len(self.ui(window).grid.cards) == 18, 10))
        self.wait_idle(window)
        self.assertEqual(provider.entered, ["load", "preview", "make", "load"], "읽기 → 미리 보기 → 만들기 하나 → 다시 읽기")
        self.assertNotIn(threading.current_thread(), provider.threads["make"], "만들기는 작업 스레드에서 돈다")
        self.assertEqual(len(self.ui(window).grid.cards), 18, "후보는 지워지지 않고 더해진다")
        self.assertIn("후보 4개를 만들었어요.", self.notice_texts(window))
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(len(window.screen_widget.findChildren(blog_parts.NoticeBar)), 1)

    def test_while_writing_the_buttons_are_off_a_second_request_is_ignored_and_closing_waits_for_the_write(self):
        provider = Gated(hold=("make",))
        window = self.make(provider)
        self.press_make(window)
        self.dialog_buttons(window)["만들기"].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: "make" in provider.entered, 5))
        self.settle(4)
        page = window.screen_widget
        self.assertTrue(window.state.candidates.busy)
        self.assertIn(T["cand_make_working"], self.notice_texts(window))
        self.assertFalse(self.button(page, "cand-make").isEnabled() or self.button(page, "refresh-candidates").isEnabled())
        self.assertEqual(self.button(page, "cand-make").toolTip(), T["cand_make_why_busy"])
        window.cand_make_confirmed()                                                                 # 끼어든 두 번째 요청
        window.cand_make()
        window.reload_candidates()
        self.settle(4)
        self.assertEqual(provider.entered.count("make"), 1, "도는 중의 두 번째 요청은 무시된다")
        self.assertEqual(provider.entered.count("preview"), 1)
        threading.Timer(1.6, provider.gates["make"].set).start()                                     # 닫기가 일반 작업 정리의 한 번 기다림(1초)보다 오래 걸리는 쓰기 — 쓰기를 따로 기다리지 않으면 못 끝낸다
        window.close()                                                                               # 끝나기를 기다린다 — 쓰기를 중간에 끊지 않는다
        self.assertEqual(provider.made_batches, 1, "닫아도 쓰던 것은 끝까지 간다")

    def test_the_prep_card_explains_what_is_missing_and_only_goes_to_existing_screens(self):
        provider = cd.FakeCandidatesProvider("lacking")
        window = self.make(provider)
        requested = []
        real_nav = window.state.nav
        window.state.nav = lambda key: (requested.append(key), real_nav(key))[1]
        self.press_make(window)
        self.assertFalse(window.dialog.is_open, "만들 것이 없으면 확인창을 띄우지 않는다")
        card = window.screen_widget.prep_card
        labels = self.texts(card)
        for part in (T["cand_prep_title"], T["cand_prep_lead"], "· " + T["cand_prep_no_seed"], "· " + T["cand_prep_proposed"].format(n=2)):
            self.assertIn(part, labels)
        self.assertEqual([button.text() for button in card.buttons], ["Seed 관리 열기", "블로그 관리 열기", "닫기"])
        self.assertEqual(self.primary_buttons(card), [], "준비 안내에는 쓰기·주요 단추가 없다")
        self.assertEqual(provider.calls, ["load", "preview"])
        card.buttons[2].click()
        self.settle(4)
        self.assertFalse(hasattr(window.screen_widget, "prep_card"), "닫기를 누르면 카드가 사라진다")
        self.assertEqual((window.state.page, requested), ("topics", []))
        for index, target in ((0, "seed"), (1, "blogs")):
            self.press_make(window)
            window.screen_widget.prep_card.buttons[index].click()
            self.settle(6)
            self.assertEqual(window.state.page, target)
            self.assertTrue(window.nav_buttons[target].isChecked())
            window.go("topics")
            self.assertTrue(self.loaded(window))
        self.assertEqual([key for key in requested if key not in ("seed", "blogs", "topics")], [], "준비 안내가 가는 곳은 이미 있는 두 화면뿐")
        self.assertEqual(provider.calls.count("make"), 0)

    def test_a_failure_shows_the_fixed_sentence_for_its_kind_and_the_list_is_not_touched(self):
        for kind in cd.KINDS_OF_FAILURE:
            provider = cd.FakeCandidatesProvider(fail={"make": cd.CandidateFailure("원본 글 C:/예시 경로/예시.db", code="SAMPLE_CODE", kind=kind)})
            window = self.make(provider, size=(1366, 768))
            ids = self.ids(window)
            self.press_make(window)
            self.dialog_buttons(window)["만들기"].click()
            self.assertTrue(ui_offscreen.wait_until(self.app, lambda: bool(self.notice_texts(window)) and not window.state.candidates.busy, 10), kind)
            self.settle(6)
            sentence = T["cand_fail_" + kind]
            self.assertEqual(self.notice_texts(window), [sentence], kind)
            self.assertEqual(self.ids(window), ids, f"{kind}: 목록이 안 바뀐다")
            self.assertEqual(provider.made_batches, 0)
            self.assertFalse([value for value in self.everything(window) if "C:/예시 경로" in value or "SAMPLE_CODE" in value], f"{kind}: 오류 원문이 화면에 나왔다")
            window.close()

    def test_a_failed_make_leaves_every_other_feature_working_and_the_same_screen_can_make_again(self):
        """운영자 P4d 완료 조건 ⑧ — 저장(만들기)이 실패해도 앱의 나머지 기능이 막히지 않는다: 화면이 '만드는 중' 모양에 갇히지 않고 거르기·상세·다른 화면 이동이 되며, 원인이 사라지면 같은 화면에서 다시 만든다."""
        provider = cd.FakeCandidatesProvider(fail={"make": cd.CandidateFailure("원본 글", code="SAMPLE_CODE", kind="io")})
        window = self.make(provider)
        self.press_make(window)
        self.dialog_buttons(window)["만들기"].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: bool(self.notice_texts(window)) and not window.state.candidates.busy, 10))
        self.settle(4)
        self.assertEqual(self.notice_texts(window), [T["cand_fail_io"]])
        page = window.screen_widget
        self.assertTrue(self.button(page, "cand-make").isEnabled() and self.button(page, "refresh-candidates").isEnabled(), "화면이 '만드는 중' 모양에 갇히지 않는다")
        self.assertFalse(window.dialog.is_open)
        self.button(page, "cand:channel:naver_a").click()                                              # 같은 화면의 기존 기능 — 거르기·상세
        self.settle(4)
        self.assertEqual(len(self.ui(window).grid.cards), 7)
        self.button(window.screen_widget, "cand-filter-reset").click()
        self.settle(4)
        self.assertEqual(len(self.ui(window).grid.cards), 14)
        self.open_card(window, self.ids(window)[0])
        self.assertTrue(window.detail_pane.isVisible())
        for key, ready in (("home", lambda: True), ("seed", lambda: window.state.seeds.state == "normal"), ("blogs", lambda: window.state.blogs.state == "normal"), ("settings", lambda: not window.state.conn_loading)):
            window.go(key)                                                                             # 다른 화면 — 저장 실패와 상관없이 열리고 읽는다
            self.assertTrue(ui_offscreen.wait_until(self.app, ready, 10), key)
            self.settle(4)
            self.assertEqual((window.state.page, window.nav_buttons[key].isChecked()), (key, True), key)
        window.go("topics")
        self.assertTrue(self.loaded(window))
        self.settle(4)
        self.assertEqual(len(self.ui(window).grid.cards), 14, "돌아와도 후보 목록은 그대로다")
        provider.fail.pop("make")                                                                      # 원인이 사라졌다 — 같은 화면에서 다시 만든다
        self.press_make(window)
        self.dialog_buttons(window)["만들기"].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: provider.made_batches == 1 and len(self.ui(window).grid.cards) == 18, 10))
        self.wait_idle(window)
        self.assertIn("후보 4개를 만들었어요.", self.notice_texts(window))

    def test_an_unexpected_exception_in_the_write_shows_the_other_sentence_and_never_its_text(self):
        provider = cd.FakeCandidatesProvider(fail={"make": RuntimeError("예시 비밀 경로 C:/예시/예시.db")})
        window = self.make(provider)
        ids = self.ids(window)
        self.press_make(window)
        self.dialog_buttons(window)["만들기"].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: bool(self.notice_texts(window)) and not window.state.candidates.busy, 10))
        self.settle(4)
        self.assertEqual(self.notice_texts(window), [T["cand_fail_other"]])
        self.assertEqual(self.ids(window), ids)
        self.assertFalse([value for value in self.everything(window) if "예시 비밀 경로" in value])

    def test_a_failed_preview_shows_a_sentence_opens_no_dialog_and_changes_nothing(self):
        provider = cd.FakeCandidatesProvider(fail={"preview": cd.CandidateFailure("x", code="SAMPLE_CODE", kind="io")})
        window = self.make(provider)
        self.button(window.screen_widget, "cand-make").click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: bool(self.notice_texts(window)), 10))
        self.settle(4)
        self.assertEqual(self.notice_texts(window), [T["cand_fail_io"]])
        self.assertFalse(window.dialog.is_open)
        self.assertEqual((provider.calls, provider.made_batches, len(self.ui(window).grid.cards)), (["load", "preview"], 0, 14))

    def test_the_sample_screen_says_that_making_candidates_writes_nothing_to_this_pc(self):
        window = self.make()
        self.button(window.screen_widget, "cand-make")
        sample = next(b for b in window.findChildren(QAbstractButton) if b.accessibleName() == "예시 데이터")
        self.assertEqual(sample.toolTip(), T["cand_sample_tip"])
        sample.click()
        self.settle(4)
        self.assertTrue(window.dialog.is_open)
        self.assertIn(T["cand_sample_dialog_body"], self.texts(window.dialog))

    def test_swapping_the_open_dialog_for_another_one_calls_the_old_cancel_hook_once_and_a_confirmed_close_calls_none(self):
        """독립 검증(P4d 수정 F1) — 열린 확인창을 닫지 않고 다른 대화상자로 바꾸면 옛 확인창은 확인 없이 닫힌 셈이다: 옛 `on_cancel` 이 바꾸는 순간 한 번 불리고 새것은 새 대화상자를 취소할 때 불린다. 확인(`on_ok`)으로 닫으면 어느 쪽도 불리지 않는다."""
        calls = []
        window = self.make(Gated())
        window.show_dialog("첫 대화상자", "본문", ok="첫 확인", cancel="첫 취소", on_cancel=lambda: calls.append("첫"))
        self.settle(2)
        window.show_dialog("둘째 대화상자", "본문", ok="둘째 확인", cancel="둘째 취소", on_cancel=lambda: calls.append("둘째"))
        self.settle(2)
        self.assertEqual(calls, ["첫"], "바꾼 순간 옛 확인창의 취소 갈고리가 한 번 불렸고 새것은 아직이다")
        self.assertEqual(sorted(self.dialog_buttons(window)), ["둘째 취소", "둘째 확인"])
        window.escape()
        self.settle(2)
        self.assertEqual(calls, ["첫", "둘째"], "새 대화상자를 취소하면 새 갈고리가 불린다 — 옛것은 다시 불리지 않는다")
        window.show_dialog("셋째 대화상자", "본문", ok="셋째 확인", cancel="셋째 취소", on_ok=lambda: calls.append("셋째 확인"), on_cancel=lambda: calls.append("셋째"))
        self.settle(2)
        self.dialog_buttons(window)["셋째 확인"].click()
        self.settle(2)
        self.assertEqual(calls, ["첫", "둘째", "셋째 확인"], "확인으로 닫으면 취소 갈고리는 불리지 않는다")
        window.show_dialog("넷째 대화상자", "본문", ok="넷째 확인")
        self.settle(2)
        window.show_dialog("다섯째 대화상자", "본문", ok="다섯째 확인")
        self.settle(2)
        self.assertEqual(calls, ["첫", "둘째", "셋째 확인"], "갈고리가 없는 대화상자를 바꿔도 아무것도 불리지 않는다")
        window.escape()
        self.settle(2)

    def test_replacing_the_make_dialog_with_the_same_kind_keeps_the_new_confirmation_and_the_write_still_starts(self):
        """같은 종류로 바꿀 때(예: 미리 보기가 다시 끝나 확인창이 한 번 더 뜸) 새 확인창이 방금 켠 '확인창을 보였다' 표시를 옛 갈고리가 거두면 안 된다 — 거두면 새 확인창의 `만들기` 가 아무것도 못 한다."""
        provider = Gated()
        window = self.make(provider)
        self.press_make(window)
        self.assertTrue(window.dialog.is_open and window.state.candidates.make_asked)
        window._show_make_dialog()                                                                   # 같은 미리 보기로 확인창을 한 번 더 띄운다(열린 확인창을 같은 종류로 바꾼다)
        self.settle(4)
        self.assertTrue(window.dialog.is_open)
        self.assertTrue(window.state.candidates.make_asked, "새 확인창의 표시가 거둬지지 않았다")
        self.assertEqual(sorted(self.dialog_buttons(window)), ["만들기", "취소"])
        self.assertEqual(provider.made_batches, 0)
        self.dialog_buttons(window)["만들기"].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: provider.made_batches == 1, 10), "바뀐 확인창에서도 `만들기` 는 쓰기를 시작한다")
        self.wait_idle(window)
        self.assertEqual(provider.made_batches, 1)


# ---- 8) 읽기 전용 증명과 쓰기 안전(실제 서비스·임시 폴더) ----------------------------------------------------------------------------------
class RealServiceTest(Base):
    def use_everything(self, window):
        """화면이 할 수 있는 읽기 동작을 모두 한다 — 거르기·찾기·고르기·창 크기 바꾸기·미리 보기."""
        page = window.screen_widget
        for key in ("cand:channel:naver_a", "cand:status:NEW", "cand:band:all"):
            if self.has_button(window.screen_widget, key):
                self.button(window.screen_widget, key).click()
                self.settle(3)
        if self.has_button(window.screen_widget, "cand-filter-more"):
            self.button(window.screen_widget, "cand-filter-more").click()
            self.settle(3)
        if self.button_edit_present(window):                                                         # 후보가 하나도 없으면 거르기 카드(검색 칸)가 없다
            self.type_query(window, "예시")
            self.type_query(window, "")
        if self.has_button(window.screen_widget, "cand-filter-reset"):
            self.button(window.screen_widget, "cand-filter-reset").click()
            self.settle(3)
        for card in list(self.ui(window).grid.cards)[:3]:
            self.open_card(window, card)
        for width in (1920, 1600, 1366, 1100, 900, 1366):
            window.resize(width, 800)
            self.settle(6)
        window.escape()
        self.settle(4)
        self.assertIsNotNone(page)

    def real_window(self, world, size=(1600, 960)):
        window = shell_module.AppShell(services.FakeHomeProvider(), candidates=world.provider, autoload=False, clock=FixedClock(NOW), clipboard=lambda value: True)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        window.go("topics")
        self.assertTrue(self.loaded(window))
        self.settle()
        return window

    def test_opening_and_using_the_screen_without_a_store_changes_nothing_and_never_creates_the_store(self):
        world = World(self)
        before, listing = world.tree(), world.listing()
        window = self.real_window(world)
        self.assertEqual(window.state.candidates.data.store, "missing")
        self.assertIn(T["cand_empty_nostore_title"], self.texts(window.screen_widget))
        self.assertEqual([button for button in window.findChildren(QAbstractButton) if button.accessibleName() == "예시 데이터"], [], "실제 데이터에는 예시 표시가 없다")
        self.use_everything(window)
        self.press_make(window)                                                                      # 미리 보기까지는 읽기뿐(씨앗이 없으면 준비 안내 카드)
        self.assertTrue(hasattr(window.screen_widget, "prep_card"))
        window.screen_widget.prep_card.buttons[2].click()
        self.settle(4)
        self.assertEqual(world.tree(), before)
        self.assertEqual(world.listing(), listing)
        self.assertFalse(world.paths.folder.exists(), "읽기·미리 보기는 보관함 폴더를 만들지 않는다")

    def test_using_the_screen_on_a_ready_store_and_cancelling_the_dialog_changes_not_a_byte(self):
        world = World(self, seeds=approved_seeds())
        world.add(*(candidate(number, 40 + number, ("naver_a", "naver_b")[number % 2]) for number in range(1, 31)))
        before, listing = world.tree(), world.listing()
        window = self.real_window(world)
        self.assertEqual(len(self.ids(window)), 24, "서른 개 중 한 번에 24장")
        self.use_everything(window)
        self.press_make(window)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(world.tree(), before, "확인창이 떠 있는 동안도 0쓰기")
        self.dialog_buttons(window)["취소"].click()
        self.settle(6)
        self.assertEqual(world.tree(), before, "취소하면 0쓰기")
        self.assertEqual(world.listing(), listing)
        self.assertEqual(len(world.stored()), 30)

    def test_swapping_the_open_confirmation_for_another_dialog_takes_the_confirmation_back_so_no_write_can_start(self):
        """독립 검증(P4d 수정 F1)의 재현 그대로 — 실제 서비스·임시 폴더에서 `후보 만들기` 로 확인창을 띄운 뒤 `show_sample_info("topics")` 로 대화상자를 바꾸고 `start_make` 를 부르면 예전에는
        `make_asked=True` 가 남아 쓰기가 시작됐다(서비스 1번 호출). 이제는 `unconfirmed` 이고 서비스 호출 0·폴더는 한 바이트도 안 바뀐다."""
        world = World(self, seeds=approved_seeds())
        before, listing = world.tree(), world.listing()
        window = self.real_window(world)
        self.press_make(window)
        self.assertTrue(window.dialog.is_open)
        self.assertTrue(window.state.candidates.make_asked)
        real = topic_service.generate_candidates
        with mock.patch.object(candidates_adapter.service, "generate_candidates", wraps=real) as spy:
            window.show_sample_info("topics")                                                        # 열린 확인창을 닫지 않고 다른 대화상자로 바꾼다
            self.settle(4)
            self.assertTrue(window.dialog.is_open)
            self.assertEqual(sorted(self.dialog_buttons(window)), [T["ok"]], "이제 보이는 것은 예시 설명 대화상자다")
            self.assertFalse(window.state.candidates.make_asked, "확인창이 바뀌었으니 '확인창을 보였다' 표시도 거둬졌다")
            self.assertEqual(window.state.candidates.start_make(**window.cand_write_bridge.callbacks()), ("unconfirmed", None))
            window.cand_make_confirmed()                                                             # 확인창의 `만들기` 가 부르는 함수를 직접 불러도 마찬가지다
            self.settle(6)
            self.assertFalse(window.state.candidates.busy)
            self.assertEqual(spy.call_count, 0, "서비스의 쓰기 함수는 한 번도 불리지 않았다")
        self.assertEqual(world.tree(), before, "임시 폴더 전체 바이트 그대로")
        self.assertEqual(world.listing(), listing)
        self.assertFalse(world.paths.database.exists(), "보관함 파일도 만들어지지 않았다")

    def test_the_confirmed_make_is_the_only_write_it_creates_only_the_store_file_and_the_cards_appear(self):
        world = World(self, seeds=approved_seeds())
        before, listing = world.tree(), world.listing()
        window = self.real_window(world)
        self.use_everything(window)
        self.press_make(window)
        self.assertEqual(world.tree(), before, "만들기를 누르기 전까지는 0쓰기")
        planned = window.state.candidates.preview.total_new
        self.assertGreater(planned, 0)
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("네트워크")), mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("네트워크")):
            self.dialog_buttons(window)["만들기"].click()
            self.assertTrue(ui_offscreen.wait_until(self.app, lambda: world.paths.database.exists() and len(self.ids(window)) > 0 and not window.state.candidates.busy, 30))
        self.wait_idle(window)
        created = sorted(set(world.listing()) - set(listing))
        self.assertEqual(created, ["data\\topic_engine\\topic_engine.db"] if os.name == "nt" else ["data/topic_engine/topic_engine.db"], "보관함 파일 하나만 생긴다(설정 파일·사본·잠금은 없다)")
        self.assertEqual(len(world.stored()), planned)
        self.assertIn(f"후보 {planned}개를 만들었어요.", self.notice_texts(window))
        self.assertEqual(len(window.state.candidates.rows()), planned)
        self.assertFalse(world.paths.profiles.exists() or world.paths.calendar.exists(), "설정 파일은 만들지 않는다")

    def test_a_read_only_store_fails_with_the_easy_sentence_and_the_bytes_and_the_cards_stay(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("관리자(root)는 읽기 전용 파일도 쓸 수 있다")
        world = World(self, seeds=approved_seeds())
        world.add(candidate(1, 85))
        window = self.real_window(world, size=(1366, 768))
        ids = self.ids(window)
        self.press_make(window)
        os.chmod(world.paths.database, stat.S_IREAD)
        self.addCleanup(os.chmod, world.paths.database, stat.S_IWRITE | stat.S_IREAD)
        before, listing = world.tree(), world.listing()
        self.dialog_buttons(window)["만들기"].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: bool(self.notice_texts(window)) and not window.state.candidates.busy, 30))
        self.settle(6)
        self.assertEqual(self.notice_texts(window), [T["cand_fail_io"]])
        self.assertEqual(world.tree(), before, "쓰기 전 상태 그대로(바이트 같음)")
        self.assertEqual(world.listing(), listing, "임시·잠금 파일이 남지 않는다")
        self.assertEqual(self.ids(window), ids, "목록이 안 바뀐다")

    def test_the_screen_and_the_make_never_ask_the_keystore(self):
        world = World(self, seeds=approved_seeds())

        def boom(*args, **kwargs):
            raise AssertionError("화면·후보 만들기는 키 보관소를 부르지 않는다")

        world.ctx.get_keystore = boom
        window = self.real_window(world)
        self.press_make(window)
        self.dialog_buttons(window)["만들기"].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: world.paths.database.exists() and not window.state.candidates.busy, 30))
        self.wait_idle(window)
        self.assertGreater(len(self.ids(window)), 0)


# ---- 9) 키보드·접근 이름 ---------------------------------------------------------------------------------------------------------------
class KeyboardTest(Base):
    def ring(self, window):
        start = window.nav_buttons["home"]
        self.focus(start)
        seen, current = [], start
        for _ in range(240):
            seen.append(current)
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            if current is start:
                return seen
        self.fail("Tab 이 한 바퀴를 돌지 못했다")

    def test_tab_goes_all_the_way_around_through_the_cards_in_reading_order_and_never_lands_on_something_unnamed(self):
        window = self.make(size=(1600, 960))
        seen = self.ring(window)
        self.assertTrue(all(widget.accessibleName().strip() for widget in seen), [type(w).__name__ for w in seen if not w.accessibleName().strip()])
        self.assertEqual(len(seen), len(set(map(id, seen))), "같은 곳을 두 번 지나지 않는다(갇히지 않는다)")
        self.assertTrue(all(isinstance(widget, (QAbstractButton, QLineEdit, UI.Pressable)) for widget in seen), [type(w).__name__ for w in seen])
        keys = [widget.property("focus_key") for widget in seen if widget.property("focus_key")]
        for key in ("cand-make", "refresh-candidates", "cand-query", "cand-filter-more", "cand:channel:all", "cand:status:all"):
            self.assertIn(key, keys)
        self.assertEqual([widget.candidate_id for widget in seen if isinstance(widget, candidate_parts.CandidateCard)], self.ids(window), "카드는 읽는 순서(위에서 아래로, 왼쪽에서 오른쪽)로 한 번씩")
        self.assertEqual(sum(1 for widget in seen if widget.property("nav")), 5)
        order = [widget.property("focus_key") for widget in seen]
        self.assertLess(order.index("cand-query"), order.index("cand:" + self.ids(window)[0]), "검색 칸은 카드보다 앞")
        self.assertLess(order.index("cand-make"), order.index("cand-query"), "머리의 단추가 거르기보다 앞")
        self.assertFalse([widget for widget in seen if not isinstance(widget, (QAbstractButton, QLineEdit, UI.Pressable))], "안내만 있는 상세 창은 정거장이 아니다")

    def test_the_tab_order_still_follows_the_screen_after_a_live_search_narrowed_and_widened_the_cards(self):
        window = self.make(size=(1600, 960))
        self.type_query(window, "영양제")
        self.type_query(window, "")
        seen = self.ring(window)
        self.assertEqual([widget.candidate_id for widget in seen if isinstance(widget, candidate_parts.CandidateCard)], self.ids(window), "카드를 다시 늘려도 Tab 순서가 화면의 읽는 순서다")
        order = [widget.property("focus_key") for widget in seen]
        self.assertLess(order.index("cand-query"), order.index("cand:" + self.ids(window)[0]))
        self.type_query(window, "예시 낱말")
        seen = self.ring(window)
        self.assertEqual([widget.candidate_id for widget in seen if isinstance(widget, candidate_parts.CandidateCard)], self.ids(window))

    def test_with_a_choice_the_pane_buttons_are_stops_and_every_pressable_has_a_name_and_a_big_enough_target(self):
        window = self.make(size=(1600, 960))
        self.open_card(window, self.ids(window)[0])
        seen = self.ring(window)
        self.assertIn(window.detail_close, seen)
        self.assertTrue(all(widget.accessibleName().strip() for widget in seen))
        cards = [index for index, widget in enumerate(seen) if isinstance(widget, candidate_parts.CandidateCard)]
        pane = [seen.index(widget) for widget in window.detail_pane.stops()]
        self.assertGreater(min(pane), max(cards), "상세 창은 카드 다음 정거장이다")
        self.assertEqual(pane, sorted(pane))
        self.assertEqual(seen[pane[0]].accessibleName(), "후보 상세 정보", "스크롤 영역도 이름이 있는 정거장 — 키보드로 긴 내용을 내려 본다")
        self.assertEqual([widget.property("focus_key") for widget in window.detail_pane.stops() if widget.property("focus_key")], ["detail-close", "detail-copy"])
        for widget in self.interactive(window):
            self.assertTrue(widget.accessibleName().strip(), f"접근 이름이 없다: {type(widget).__name__}")
            if isinstance(widget, QAbstractButton):
                self.assertGreaterEqual(widget.height(), tokens.SIZE["hit"], widget.accessibleName())
                self.assertGreaterEqual(widget.width(), tokens.SIZE["hit"], widget.accessibleName())
                if not widget.text().strip():
                    self.assertEqual(widget.toolTip(), widget.accessibleName(), "아이콘만 있는 단추는 툴팁도 같은 말")
            else:
                self.assertGreaterEqual(widget.height(), tokens.SIZE["hit"], widget.accessibleName())

    def interactive(self, window):
        return [w for w in window.findChildren(QWidget) if w.isVisible() and (isinstance(w, (QAbstractButton, QLineEdit)) or isinstance(w, UI.Pressable) and w.focusPolicy() != Qt.NoFocus)]

    def test_enter_and_space_open_a_card_and_a_second_card_replaces_the_choice(self):
        window = self.make(size=(1600, 960))
        first, second = self.ids(window)[:2]
        card = self.card(window, first)
        self.focus(card)
        QTest.keyClick(card, Qt.Key_Space)
        self.settle(8)
        self.assertEqual(window.state.candidates.selected, first)
        other = self.card(window, second)
        self.focus(other)
        QTest.keyClick(other, Qt.Key_Return)
        self.settle(8)
        self.assertEqual(window.state.candidates.selected, second)
        self.assertEqual([key for key, widget in self.ui(window).grid.cards.items() if widget.property("selected")], [second], "선택은 하나")
        self.assertEqual(window.drawer.is_open, False)

    def test_the_search_box_has_a_label_and_a_placeholder_and_the_filter_chips_say_what_they_filter(self):
        window = self.make()
        edit = self.button_edit(window)
        self.assertEqual((edit.accessibleName(), edit.placeholderText()), ("후보 찾기", "제목이나 키워드로 찾아요"))
        for chip in window.screen_widget.findChildren(QAbstractButton):
            if chip.property("focus_key") and str(chip.property("focus_key")).startswith("cand:"):
                self.assertRegex(chip.accessibleName(), r"(전체 \d+|(채널|작업 상태|점수 구간|주제 묶음) .+ \d+개)", chip.accessibleName())
        grid = self.ui(window).grid
        self.assertEqual(grid.accessibleName(), "후보 카드 목록")
        self.assertEqual(window.detail_pane.accessibleName(), "후보 상세 정보")


if __name__ == "__main__":
    unittest.main()
