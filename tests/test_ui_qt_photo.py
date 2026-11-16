"""'사진 정리'(사진 연동 2단계, 결정 D-499)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 초안 화면의 '사진' 카드·'사진 넣기(선택)' 줄과 사진 정리 창(사진 추가·줄·입력 칸·글자 수·확인·모두 확인했어요·순서·지우기와 되돌리기·
미리보기·다시 찾기·종류 목록 고치기·닫기·Esc)을 실제로 눌러 본다. **PySide6 가 없으면 Qt 시험은 통째로 건너뛴다**(저장소 CI 에는 PySide6 가 없다 — 이 파일의 `SourceRulesTest` 는 PySide6 없이도 돈다).
사진 파일은 이 시험이 임시 폴더에 만든 아주 작은 그림뿐이고(그 밖의 사진 위치는 가짜 공급자가 판정하며 파일을 읽지 않는다), 사용자의 사진·클립보드·브라우저·데이터 폴더·설정 파일은 건드리지 않는다. 사진·이름·글은 모두 지어낸 것이다.

지키는 것:
  1) 진입 — 초안 화면에 '사진' 카드와 '만드는 방법' 칸의 '사진 넣기(선택)' 줄이 있고(접근 이름·36px 이상·Tab 정거장) 둘 다 같은 창을 연다. 사진을 넣지 않아도 초안 화면은 그대로다.
  2) 입력 칸 — '이 사진은 무엇인가요?'·'한마디 메모' 는 접지 않고 늘 보이고 예시가 종류에 따라 바뀐다. 글자 수(12/60·0/300)가 치는 동안 바뀌고 한도를 넘으면 글로도 알린다. 한도를 넘긴 글은 반영하지 않고 이유만 보이며 닫을 때 한 번 알린다.
  3) 흐름 — 사진 추가(못 넣은 파일은 이름과 이유만)·확인했어요(고치면 풀림)·모두 확인했어요(확인 줄을 먼저 보이고 처음 포커스는 그만두기)·↑↓·지우기와 한 번 되돌리기·다시 찾기·종류 목록 고치기·30장 한도.
  4) 미리보기 — 메모리에서만 한 장씩 만들고, 큰 PNG(1억 화소 초과)·없는 파일은 만들지 않고 글로 알린다. 닫으면 줄·그림·대기열이 비워진다.
  5) 경로·글이 새지 않는다 — 어느 위젯의 글·접근 이름·툴팁에도 폴더 이름이 없고, 파일 이름은 줄·못 넣은 파일 목록에만 보이며, 한도를 넘겨 반영하지 못한 글은 입력 칸에만 있다.
  6) 키보드·크기 — Tab 은 이름 있는 곳만 보이는 순서로 지나고 대화상자 밖으로 새지 않으며, 모든 필수 크기와 최소 창에서 가로 스크롤·글자 잘림·삐져나옴이 없고 단추 줄이 늘 보인다.
  7) 읽기 전용 — 진짜 사진 파일을 넣고 미리보기까지 만들어도 파일 바이트·폴더 목록이 그대로이고 네트워크를 부르지 않는다.
"""
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import key_leak_support as leak  # noqa: E402
import test_ui_qt_drafts as qd  # noqa: E402     (초안 화면 시험의 도구 — 이 모듈의 시험은 가져오지 않고 도구만 이어 쓴다)
from test_ui_drafts_core import APPLIANCE, GENERIC, OTHER_CHANNEL, SOFTWARE, STOPPED  # noqa: E402
from test_ui_drafts_service import NoNetwork  # noqa: E402

from chanceblog_desktop.ui.core import imagerules as R  # noqa: E402
from chanceblog_desktop.ui.core import photo_rules as rules  # noqa: E402
from chanceblog_desktop.ui.core import photo_text, services, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402
from chanceblog_desktop.ui.core.clock import FixedClock  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPixmap
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QWidget
    from chanceblog_desktop.ui import photo_adapter
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import photo_screen
    from chanceblog_desktop.ui.qt import shell as shell_module

T = text.T
UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
QT_DIR, CORE_DIR = UI_DIR / "qt", UI_DIR / "core"
NEW_QT = ("photo_parts.py", "photo_screen.py")
SIZES = ((1920, 1080), (1600, 960), (1366, 768), (1280, 720), (1093, 614), (910, 512), (900, 560))
DIR_MARK, FILE_MARK, NOTE_MARK = "UNIQ-PHOTODIR-z5r1", "UNIQ-PHOTOFILE-v8t3", "UNIQ-NOTE-본문-y2k7"


def fake_path(number, ext="jpg", stem=FILE_MARK):
    return f"C:/Users/{DIR_MARK}/Pictures/{stem}-{number:02d}.{ext}"


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


def builtin_calls(function):
    """`open(…)`·`print(…)` 처럼 이름만으로 부르는 함수(`board.open()` 같은 메서드는 뺀다)."""
    return {node.func.id for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def mentions(path, name):
    """소스가 `name` 을 가져오거나 이름으로 쓰는가(주석·설명 글은 세지 않는다)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name == name for alias in node.names):
            return True
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
    return False


# ---- 소스 규칙(PySide6 없이 돈다 — CI 와 같은 조건) -----------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    def test_the_new_screen_files_cannot_write_open_files_reach_the_network_the_service_or_print(self):
        for name in NEW_QT:
            source = (QT_DIR / name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported |= {(node.module or "").split(".")[0] or ("." * node.level + (node.module or ""))}
            self.assertFalse(imported & {"sqlite3", "subprocess", "socket", "urllib", "http", "shutil", "os", "pathlib", "json", "tempfile", "requests", "keyring", "logging", "traceback", "webbrowser", "ctypes"}, (name, imported))
            names = called_names(tree)
            self.assertFalse(names & {"open", "print", "write", "write_text", "write_bytes", "unlink", "mkdir", "rename", "replace", "remove", "copy", "copyfile", "move", "save", "exec", "eval", "openUrl", "clipboard"}, (name, names))
            for forbidden in ("chanceblog_desktop.service", "..service", "..topics", "..topicdb", "..security", "..publish", "..content", "..check", "adapters", "QClipboard", "QGuiApplication", "QDesktopServices", "QFileDialog", "QSettings", "QStandardPaths"):
                self.assertNotIn(forbidden, source, f"{name}: 화면 부품은 서비스·엔진·보관소·클립보드·브라우저·파일 대화상자를 직접 부르지 않는다 — {forbidden}")
        self.assertTrue(mentions(QT_DIR / "photo_screen.py", "imagecheck"))
        self.assertFalse(mentions(QT_DIR / "photo_parts.py", "imagecheck"), "줄 부품은 파일을 읽지 않는다 — 그림은 창이 만들어 넘긴다")

    def test_colors_fonts_and_sizes_come_from_the_tokens_only(self):
        for name in NEW_QT:
            source = (QT_DIR / name).read_text(encoding="utf-8")
            for forbidden in ("setStyleSheet", "QColor(", "QFont(", "QPalette", "setFont(", "rgb(", "rgba("):
                self.assertNotIn(forbidden, source, f"{name}: {forbidden}")
            self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", source), [], f"{name}: 색 글자가 있다")
            self.assertEqual(re.findall(r"setFixedSize\(\s*\d|setMinimumWidth\(\s*\d|setFixedHeight\(\s*\d|setFixedWidth\(\s*\d", source), [], f"{name}: 크기를 숫자로 정했다")

    def test_the_shell_functions_of_the_photo_sheet_never_touch_providers_files_or_the_network(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        found = [name for name in methods if name.startswith(("photos_", "_photos_"))]
        self.assertEqual(sorted(found), ["_photos_after_store", "_photos_discard", "_photos_live", "_photos_trash_clear_confirmed", "photos_card_refresh", "photos_close", "photos_escape", "photos_open", "photos_pick", "photos_relink", "photos_restore", "photos_trash_clear"])
        for name in found:
            source = "\n".join(ast.unparse(statement) for statement in methods[name].body)
            for forbidden in ("provider.", "service.", "sqlite3", "subprocess", "socket", "urllib", "shutil", "os.", "pathlib"):
                self.assertIsNone(re.search(r"\b" + re.escape(forbidden), source), f"{name}: {forbidden}")
            self.assertFalse(called_names(methods[name]) & {"write", "write_text", "write_bytes", "mkdir", "unlink", "rename", "replace"}, name)
            self.assertFalse(builtin_calls(methods[name]) & {"open", "print", "exec", "eval"}, name)
        self.assertEqual(ast.unparse(methods["photos_pick"]).count("add_paths"), 1)
        self.assertIn("paths = None", ast.unparse(methods["photos_pick"]), "고른 위치 목록은 쓰고 나서 바로 놓는다")
        self.assertIn("path = None", ast.unparse(methods["photos_relink"]))

    def test_the_sheet_is_always_cleaned_up_whichever_way_the_dialog_closes(self):
        methods = methods_of(QT_DIR / "shell.py", "AppShell")
        opener = ast.unparse(methods["photos_open"])
        self.assertIn("cleanups.append(self._photos_discard)", opener)
        self.assertIn("shutdown", ast.unparse(methods["_photos_discard"]))
        closer = ast.unparse(methods["photos_close"])
        self.assertLess(closer.index("flush"), closer.index("close()"), "닫기 전에 칸의 글을 먼저 규칙에 넘긴다")
        escape = ast.unparse(methods["escape"])
        self.assertIn("photos_escape", escape, "Esc 가 사진 정리 길로 간다")
        self.assertLess(escape.index("photos_escape"), escape.index("close_dialog"), "Esc 는 닫기 단추와 같은 길을 먼저 거친다")

    def test_every_photo_text_is_used_and_every_used_text_is_defined(self):
        files = [CORE_DIR / "photo_view.py", CORE_DIR / "photo_rules.py", QT_DIR / "photo_parts.py", QT_DIR / "photo_screen.py", QT_DIR / "shell.py", QT_DIR / "draft_screen.py", CORE_DIR / "drafts_view.py", CORE_DIR / "drafts.py",
                 UI_DIR / "drafts_adapter.py"]
        used = set()
        for path in files:
            used |= set(re.findall(r"""["'](pho_[a-z0-9_]+)["']""", path.read_text(encoding="utf-8")))
        unused = sorted(key for key in photo_text.PHOTO_T if key not in used)
        self.assertEqual(unused, [], "쓰이지 않는 문구가 있다")
        self.assertEqual(sorted(key for key in used if key not in photo_text.PHOTO_T), [], "정의하지 않은 문구를 쓴다")


# ---- 시험 도구 -----------------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class PhotoBase(qd.Base):
    """초안 화면까지 가서 사진 정리를 여는 도구 — 초안 화면 시험(`test_ui_qt_drafts`)의 `Base`(가짜 후보·가짜 클립보드·오류 잡이)를 이어 쓴다."""

    def setUp(self):
        super().setUp()
        self.picks, self.pick_calls = [], []                                          # 사진 여러 장 선택기(가짜) — 차례로 돌려줄 목록과 부른 기록
        self.relinks, self.relink_calls = [], []                                      # 사진 하나 선택기(가짜 — 다시 찾기)
        self.maker_calls = []                                                         # 미리보기 만들기(가짜)를 부른 위치
        holder = tempfile.TemporaryDirectory(prefix="photo-qt-")
        self.addCleanup(holder.cleanup)
        self.tmp = Path(os.path.realpath(holder.name))

    # 가짜 선택기·미리보기 만들기
    def pick_files(self, _parent, title, filter_text):
        self.pick_calls.append((title, filter_text))
        return self.picks.pop(0) if self.picks else []

    def pick_one(self, _parent, title, filter_text):
        self.relink_calls.append((title, filter_text))
        return self.relinks.pop(0) if self.relinks else ""

    def make_preview(self, path):
        self.maker_calls.append(path)
        pixmap = QPixmap(24, 18)
        pixmap.fill(QColor("#336699"))
        return pixmap

    def make(self, candidates=None, drafts_provider=None, size=(1600, 960), clipboard=None, opener=None, home=None, photos=None, maker=True, real_files=False):
        provider = candidates or qd.candidates_with(GENERIC, SOFTWARE, APPLIANCE, STOPPED, OTHER_CHANNEL)
        window = shell_module.AppShell(home or services.FakeHomeProvider(), candidates=provider, drafts=drafts_provider, autoload=False, clock=FixedClock(qd.NOW), clipboard=clipboard or self.clipboard,
                                       url_opener=opener or (lambda url: self.opened.append(url) or True), files_picker=self.pick_files, file_picker=self.pick_one,
                                       photos=photos if photos is not None else (photo_adapter.ServicePhotoProvider() if real_files else pv.FakePhotoProvider()),
                                       photo_preview_maker=(self.make_preview if maker is True else maker) if not real_files else None)
        window.resize(*size)
        window.show()
        self.addCleanup(lambda: (window.state.drafts.leave(), window.close()))
        self.settle()
        self.activate(window)
        window.go("topics")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.candidates.state != "loading" and not window.state.candidates.loading, 10))
        self.settle()
        return window

    def sheet(self, window=None, **kwargs):
        """초안이 보이는 창에서 오른쪽 '사진' 카드의 단추로 사진 정리 창을 연다(진짜 길) → (창, 사진 정리 창 안쪽)."""
        window = window or self.drafted(**kwargs)
        self.button(window, "drf-photos").click()
        self.settle(8)
        form = window.photo_form
        self.assertIsNotNone(form)
        return window, form

    def add_photos(self, form, *paths):
        self.picks.append(list(paths))
        form.add_button.click()
        self.settle(10)

    def lt(self, label):
        return label.plain_text() if isinstance(label, UI.Label) else label.text()

    def buttons_of(self, root):
        return [widget for widget in root.findChildren(QAbstractButton) if widget.isVisibleTo(root)]

    def chip(self, form, kind, photo_id, value):
        key = f"pho:{kind}:{photo_id}:{value}"
        found = [button for button in form.findChildren(QAbstractButton) if button.property("focus_key") == key]
        self.assertEqual(len(found), 1, (key, len(found)))
        return found[0]

    def named(self, form, name):
        found = [button for button in form.findChildren(QAbstractButton) if button.accessibleName() == name and button.isVisibleTo(form)]
        self.assertEqual(len(found), 1, (name, [button.accessibleName() for button in self.buttons_of(form)]))
        return found[0]

    def commit(self, edit, value):
        """칸에 글을 치고 Enter(규칙에 넘긴다)."""
        edit.setFocus(Qt.OtherFocusReason)
        edit.setText(value)
        self.settle(1)
        QTest.keyClick(edit, Qt.Key_Return)
        self.settle(3)

    def widget_hits(self, window, probes, skip_editors=True):
        editors = [widget for widget in window.findChildren(QLineEdit)] if skip_editors else []
        return leak.widget_hits(window, probes, typing_into=editors)

    def shown_texts(self, root):
        found = []
        for widget in [root, *root.findChildren(QWidget)]:
            if isinstance(widget, (QLabel, QAbstractButton)) and widget.isVisibleTo(root):
                found.append(self.lt(widget) if isinstance(widget, UI.Label) else widget.text())
        return found


# ---- 1) 진입 ----------------------------------------------------------------------------------------------------------------------
class EntryTest(PhotoBase):
    def test_the_draft_screen_has_the_card_and_the_optional_row_and_both_open_the_same_sheet(self):
        window = self.drafted()
        ui = self.ui(window)
        self.assertEqual(self.lt(ui.photos_count), "넣은 사진이 없어요")
        self.assertEqual(ui.photos_count.accessibleName(), "넣은 사진이 없어요")
        for button in (ui.photos_button, ui.photos_row_button):
            self.assertEqual(button.text(), "사진 넣기")
            self.assertEqual(button.accessibleName(), "사진 넣기 — 글에 넣을 사진을 고르는 창")
            self.assertGreaterEqual(button.height(), tokens.SIZE["hit"] - 8)
            self.assertNotEqual(button.focusPolicy(), Qt.NoFocus)
        self.assertIn("사진 넣기(선택)", self.texts(window.screen_widget))
        self.assertFalse(ui.photos_unsaved.isVisibleTo(window.screen_widget), "사진이 없으면 저장 안내를 보이지 않는다")
        self.assertIn(ui.photos_button, ui.stops)
        self.assertIn(ui.photos_row_button, ui.stops)
        self.assertLess(ui.stops.index(ui.photos_row_button), ui.stops.index(ui.apply))
        self.assertGreater(ui.stops.index(ui.photos_button), ui.stops.index(ui.image_button))
        self.assertIsNone(window.photo_form)
        window.drf_toggle_options()
        self.settle(3)
        QTest.mouseClick(ui.photos_row_button, Qt.LeftButton)
        self.settle(8)
        self.assertIsNotNone(window.photo_form, "만드는 방법 칸의 줄에서도 같은 창이 열린다")
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(window.dialog.accessibleName(), T["pho_title"])

    def test_opening_the_sheet_changes_nothing_in_the_draft(self):
        window = self.drafted()
        controller, ui = window.state.drafts, self.ui(window)
        body, title = ui.editor.toPlainText(), ui.title.text()
        window, form = self.sheet(window)
        self.assertEqual((ui.editor.toPlainText(), ui.title.text()), (body, title))
        self.assertFalse(controller.has_unsaved())
        self.add_photos(form, fake_path(1), fake_path(2))
        self.assertEqual((ui.editor.toPlainText(), ui.title.text()), (body, title), "사진을 넣어도 글은 그대로다(본문에 사진 넣기는 아직 없다)")
        self.assertFalse(controller.text_unsaved(), "글은 안 바뀌었다")
        self.assertTrue(controller.photos_unsaved() and controller.has_unsaved(), "사진 정보를 고쳤으니 초안을 저장해야 함께 저장된다(3단계)")
        self.assertEqual(controller.body, body)

    def test_a_second_open_while_the_sheet_is_open_does_nothing(self):
        window, form = self.sheet()
        self.assertIsNone(window.photos_open())
        self.assertIs(window.photo_form, form)

    def test_the_card_follows_the_photos_and_the_unsaved_note_shows_only_with_photos(self):
        window, form = self.sheet()
        ui = self.ui(window)
        self.add_photos(form, fake_path(1), fake_path(2))
        self.assertEqual(self.lt(ui.photos_count), "사진 2장 · 확인 0/2")
        self.assertEqual(ui.photos_count.accessibleName(), "넣은 사진 2장 중 0장을 확인했어요")
        self.assertEqual((ui.photos_button.text(), ui.photos_row_button.text()), ("사진 정리 열기", "사진 정리 열기"))
        self.assertTrue(ui.photos_unsaved.isVisibleTo(window.screen_widget))
        self.assertIn("사진 정보를 고쳤어요. 초안을 저장해야 사진 정보도 함께 저장돼요.", self.lt(ui.photos_unsaved))
        form.rows["p001"].confirm_box.click()
        self.settle(3)
        self.assertEqual(self.lt(ui.photos_count), "사진 2장 · 확인 1/2")
        form.rows["p001"].remove.click()
        self.settle(3)
        form.rows["p002"].remove.click()
        self.settle(3)
        self.assertEqual(self.lt(ui.photos_count), "넣은 사진이 없어요")
        self.assertEqual(ui.photos_button.text(), "사진 넣기")
        self.assertFalse(ui.photos_unsaved.isVisibleTo(window.screen_widget))

    def test_leaving_the_draft_clears_the_photos(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        window.photos_close()
        self.settle(4)
        self.assertEqual(window.state.drafts.photos.count, 1)
        window.go("topics", force=True)                                           # 사진 정보를 고쳤으면 확인창이 먼저다(세 갈래) — 여기서는 `저장 안 하고 나가기` 와 같다
        self.settle(6)
        self.assertEqual(window.state.drafts.photos.count, 0)


# ---- 2) 창과 입력 칸 --------------------------------------------------------------------------------------------------------------
class SheetTest(PhotoBase):
    def test_the_empty_sheet(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.assertTrue(board.is_open)
        self.assertEqual(self.lt(form.title), "사진 정리")
        self.assertEqual(self.lt(form.count), "사진 0장 · 확인 0/0")
        self.assertTrue(form.empty.isVisibleTo(form))
        self.assertEqual(self.lt(form.empty), T["pho_empty"])
        self.assertEqual(form.rows, {})
        self.assertTrue(form.add_button.isEnabled())
        self.assertFalse(form.all_button.isEnabled())
        self.assertFalse(form.undo_button.isVisibleTo(form))
        self.assertIs(QApplication.focusWidget(), form.add_button)
        for part in ("30장", "60자", "300자", "100자"):
            self.assertIn(part, self.lt(form.limits))
        self.assertIn("밖으로 보내지 않아요", self.lt(form.intro))
        self.assertEqual(window.dialog.width(), min(photo_screen.DIALOG_WIDTH, int(window.width() * 0.94)))

    def test_picking_adds_rows_and_lists_what_was_not_added_by_name_and_reason_only(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2, "png"), fake_path(3, "gif"), "relative.jpg")
        self.assertEqual(self.pick_calls, [(T["pho_pick_title"], f"{T['pho_pick_filter']} {shell_module.IMAGE_FILTER}")])
        self.assertEqual(list(form.rows), ["p001", "p002"])
        self.assertEqual(self.lt(form.count), "사진 2장 · 확인 0/2")
        self.assertFalse(form.empty.isVisibleTo(form))
        self.assertTrue(form.rejected_host.isVisibleTo(form))
        shown = self.shown_texts(form.rejected_host)
        self.assertIn(f"{FILE_MARK}-03.gif — 지원하지 않는 형식이에요. JPG·PNG·WebP 사진만 쓸 수 있어요", shown)
        self.assertIn("relative.jpg — 사진 파일 위치가 올바르지 않아요. 파일 선택 창에서 직접 골라 주세요", shown)
        self.assertEqual(self.lt(form.notice), "사진 2장을 넣었어요.")
        self.assertEqual(self.widget_hits(window, [DIR_MARK]), [], "폴더 이름은 어느 위젯의 글·접근 이름·툴팁에도 없다")
        form.rejected_clear.click()
        self.settle(3)
        self.assertFalse(form.rejected_host.isVisibleTo(form))
        self.add_photos(form)                                                          # 선택을 취소하면(빈 목록) 아무것도 바뀌지 않는다
        self.assertEqual(list(form.rows), ["p001", "p002"])

    def test_the_two_input_fields_are_always_visible_and_the_example_follows_the_type(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        card = form.rows["p001"]
        self.assertFalse(card.place_body.isVisibleTo(form), "자리 정하기는 접혀 있다")
        for edit in (card.subject.edit, card.note.edit):
            self.assertTrue(edit.isVisibleTo(form))
            self.assertGreaterEqual(edit.height(), tokens.SIZE["control"] - 4)
        self.assertEqual(self.lt(card.subject.title), "이 사진은 무엇인가요?")
        self.assertEqual(self.lt(card.note.title), "한마디 메모(선택)")
        self.assertEqual(card.subject.edit.placeholderText(), "예: " + rules.example_for("기타"))
        self.assertTrue(card.note.edit.placeholderText().startswith("예: "))
        for kind, example in (("반찬", "예: 반찬 5개"), ("대표 메뉴", "예: 메인 메뉴 한우 불고기 전골"), ("간판", "예: 매장 입구 간판과 주차장 전경")):
            self.chip(form, "type", "p001", kind).click()
            self.settle(3)
            self.assertEqual(card.subject.edit.placeholderText(), example, kind)
            self.assertTrue(card.subject.edit.isVisibleTo(form) and card.note.edit.isVisibleTo(form))
        self.assertEqual(form.rows["p002"].subject.edit.placeholderText(), "예: " + rules.example_for("기타"), "다른 줄의 예시는 그대로")
        self.assertTrue(card.place_body.isVisibleTo(form), "간판은 기본 들어갈 곳(도입)이 생겨 자리 정하기가 펼쳐진다")
        self.assertTrue(self.chip(form, "section", "p001", "도입").isChecked())

    def test_the_default_place_follows_the_type_unless_the_user_chose_one(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        for kind, section in (("간판", "도입"), ("메뉴판", "내용 소제목"), ("인테리어", "분위기 소제목"), ("지도 캡처", "")):
            self.chip(form, "type", "p001", kind).click()
            self.settle(3)
            self.assertEqual(board.photo("p001").preferred_section, section, kind)
            self.assertTrue(self.chip(form, "section", "p001", section).isChecked(), kind)
        self.chip(form, "section", "p001", "마무리").click()
        self.settle(3)
        self.chip(form, "type", "p001", "음식").click()
        self.settle(3)
        self.assertEqual(board.photo("p001").preferred_section, "마무리", "사용자가 고른 곳은 종류를 바꿔도 그대로")

    def test_the_counters_change_while_typing_and_the_over_limit_text_appears_without_color_alone(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        self.assertEqual((self.lt(card.subject.count), self.lt(card.note.count)), ("0/60", "0/300"))
        card.subject.edit.setFocus(Qt.OtherFocusReason)
        card.subject.edit.setText("한우 불고기 전골")
        self.settle(2)
        self.assertEqual(self.lt(card.subject.count), "9/60")
        card.subject.edit.setText("가" * 60)
        self.settle(2)
        self.assertEqual(self.lt(card.subject.count), "60/60")
        self.assertFalse(card.subject.error.isVisibleTo(form))
        card.subject.edit.setText("가" * 61)
        self.settle(2)
        self.assertEqual(self.lt(card.subject.count), "61/60")
        self.assertTrue(card.subject.error.isVisibleTo(form))
        self.assertEqual(self.lt(card.subject.error), "60자까지만 적을 수 있어요. 지금 61자예요.")
        card.note.edit.setText("나" * 300)
        self.settle(2)
        self.assertEqual(self.lt(card.note.count), "300/300")
        self.assertFalse(card.note.error.isVisibleTo(form))

    def test_an_over_limit_text_is_not_applied_keeps_only_in_the_field_and_closing_warns_once(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        self.commit(card.subject.edit, "냉면")
        self.assertEqual(board.photo("p001").user_subject, "냉면")
        long_text = NOTE_MARK + "가" * 70
        self.commit(card.subject.edit, long_text)
        self.assertEqual(board.photo("p001").user_subject, "냉면", "한도를 넘긴 글은 반영하지 않는다")
        self.assertEqual(card.subject.edit.text(), long_text, "입력 칸의 글은 지우지 않는다")
        self.assertIn("60자까지만", self.lt(card.subject.error))
        probes = leak.needles(NOTE_MARK, size=8)
        self.assertEqual(leak.graph_hits(board, probes, skip=(board.provider,)), [], "규칙 쪽(사진 목록·오류·안내)에는 그 글이 없다")
        self.assertEqual(self.widget_hits(window, probes), [], "입력 칸 밖의 어느 위젯에도 그 글이 없다")
        self.assertEqual(window.photos_close(), "warned")
        self.assertIs(window.photo_form, form)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(self.lt(form.notice), T["pho_over_close"])
        self.assertEqual(window.photos_close(), "closed")
        self.assertIsNone(window.photo_form)
        self.assertFalse(window.dialog.is_open)
        self.assertFalse(board.is_open)
        self.assertEqual(board.photo("p001").user_subject, "냉면")
        self.assertEqual(self.widget_hits(window, probes, skip_editors=False), [], "닫으면 그 글은 어디에도 없다")

    def test_a_text_typed_but_not_entered_is_handed_over_when_closing(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        card.note.edit.setFocus(Qt.OtherFocusReason)
        card.note.edit.setText("비 오는 날 갔어요")
        self.assertEqual(board.photo("p001").user_note, "")
        form.close_button.click()
        self.settle(4)
        self.assertEqual(board.photo("p001").user_note, "비 오는 날 갔어요")
        self.assertIsNone(window.photo_form)

    def test_typing_in_another_field_or_clicking_a_chip_does_not_lose_the_typed_text_or_the_row(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2))
        card, other = form.rows["p001"], form.rows["p002"]
        subject_edit = card.subject.edit
        subject_edit.setFocus(Qt.OtherFocusReason)
        subject_edit.setText("한우 불고기 전골")
        self.chip(form, "type", "p001", "대표 메뉴").click()
        self.settle(4)
        self.assertIs(form.rows["p001"], card, "줄은 사진이 지워질 때까지 같은 부품이다")
        self.assertIs(card.subject.edit, subject_edit)
        self.assertEqual(subject_edit.text(), "한우 불고기 전골")
        self.assertEqual(board.photo("p001").user_subject, "한우 불고기 전골", "다른 곳을 누르면 그 글이 규칙에 넘어간다")
        self.assertEqual(board.photo("p001").photo_type, "대표 메뉴")
        self.assertIs(form.rows["p002"], other)
        self.assertEqual(other.subject.edit.text(), "")

    def test_the_setting_chips_are_the_six_and_none_and_can_be_cleared(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        names = [chip.text() for chip in form.rows["p001"]._chips_setting.values()]
        self.assertEqual(names, ["정하지 않음", "실내", "실외", "테라스", "주차장", "객실", "야경"])
        self.chip(form, "setting", "p001", "야경").click()
        self.settle(3)
        self.assertEqual(board.photo("p001").setting, "야경")
        self.assertTrue(self.chip(form, "setting", "p001", "야경").isChecked())
        self.chip(form, "setting", "p001", "").click()
        self.settle(3)
        self.assertEqual(board.photo("p001").setting, "")

    def test_the_place_block_sets_section_kind_nth_and_caption(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        card.place_toggle.click()
        self.settle(3)
        self.assertTrue(card.place_body.isVisibleTo(form))
        self.assertFalse(card.nth_box.isVisibleTo(form))
        self.chip(form, "kind", "p001", "after_paragraph").click()
        self.settle(3)
        self.assertTrue(card.nth_box.isVisibleTo(form))
        self.assertEqual(self.lt(card.nth_value), "1번째")
        card.nth_more.click()
        self.settle(3)
        self.assertEqual((board.photo("p001").placement.kind, board.photo("p001").placement.nth), ("after_paragraph", 2))
        self.assertEqual(self.lt(card.nth_value), "2번째")
        card.nth_less.click()
        card.nth_less.click()
        self.settle(3)
        self.assertEqual(board.photo("p001").placement.nth, 1)
        self.chip(form, "kind", "p001", "auto").click()
        self.settle(3)
        self.assertFalse(card.nth_box.isVisibleTo(form))
        self.commit(card.caption.edit, "기본 반찬")
        self.assertEqual(board.photo("p001").caption, "기본 반찬")
        self.assertEqual(self.lt(card.caption.count), "5/100")
        self.chip(form, "section", "p001", "마무리").click()
        self.settle(3)
        self.assertEqual(board.photo("p001").preferred_section, "마무리")


# ---- 3) 확인·순서·지우기 --------------------------------------------------------------------------------------------------------
class FlowTest(PhotoBase):
    def test_confirming_and_the_unconfirm_note_when_the_content_changes(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2))
        card = form.rows["p001"]
        self.assertFalse(card.confirm_box.isChecked())
        self.assertEqual(self.lt(card.confirm_status), "아직 확인하지 않았어요")
        card.confirm_box.click()
        self.settle(3)
        self.assertTrue(board.photo("p001").confirmed_by_user)
        self.assertTrue(card.confirm_box.isChecked())
        self.assertEqual(self.lt(card.confirm_status), "확인했어요")
        self.assertEqual(self.lt(form.count), "사진 2장 · 확인 1/2")
        self.assertEqual(card.confirm_box.accessibleName(), "사진 1 확인했어요")
        self.commit(card.note.edit, "비 오는 날")
        self.assertFalse(board.photo("p001").confirmed_by_user, "내용을 고치면 확인이 풀린다")
        self.assertFalse(card.confirm_box.isChecked())
        self.assertTrue(card.changed_note.isVisibleTo(form))
        self.assertEqual(self.lt(card.changed_note), "내용을 고쳐서 확인 표시를 풀었어요. 다시 확인해 주세요.")
        card.confirm_box.click()
        self.settle(3)
        self.assertFalse(card.changed_note.isVisibleTo(form))
        self.assertTrue(board.photo("p001").confirmed_by_user)

    def test_confirm_all_shows_the_line_first_puts_focus_on_the_safe_button_and_esc_cancels_it(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        form.rows["p002"].confirm_box.click()
        self.settle(3)
        self.assertTrue(form.all_button.isEnabled())
        form.all_button.click()
        self.settle(6)
        self.assertEqual(board.confirmed_count, 1, "묻는 것만으로는 아무것도 바뀌지 않는다")
        self.assertEqual(len(form.confirm_buttons), 2)
        yes, no = form.confirm_buttons
        self.assertEqual((yes.text(), no.text()), ("2장 모두 확인", "그만두기"))
        self.assertTrue(all(button.isVisibleTo(form) for button in form.confirm_buttons))
        self.assertIs(QApplication.focusWidget(), no, "처음 포커스는 안전한 쪽(그만두기)")
        self.assertFalse(form.all_button.isEnabled())
        self.assertIn("사진 2장을 모두 ‘확인했어요’ 로 표시할까요?", self.shown_texts(form.confirm_host)[0])
        QTest.keyClick(no, Qt.Key_Escape)
        self.settle(4)
        self.assertEqual(form.confirm_buttons, [])
        self.assertTrue(window.dialog.is_open, "Esc 는 확인 줄만 그만두고 창은 그대로")
        self.assertEqual(board.confirmed_count, 1)
        form.all_button.click()
        self.settle(4)
        form.confirm_buttons[0].click()
        self.settle(4)
        self.assertEqual(board.confirmed_count, 3)
        self.assertEqual(self.lt(form.notice), "사진 2장을 확인했다고 표시했어요.")
        self.assertTrue(all(card.confirm_box.isChecked() for card in form.rows.values()))
        self.assertFalse(form.all_button.isEnabled())

    def test_moving_up_and_down_keeps_the_numbers_and_the_edge_buttons_are_off(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        self.assertFalse(form.rows["p001"].up.isEnabled())
        self.assertFalse(form.rows["p003"].down.isEnabled())
        form.rows["p003"].up.click()
        self.settle(4)
        self.assertEqual([photo.photo_id for photo in board.manifest.photos], ["p001", "p003", "p002"])
        self.assertEqual([self.lt(card.number) for card in form.ordered_cards()], ["사진 1", "사진 3", "사진 2"])
        self.assertEqual([card.photo_id for card in form.ordered_cards()], ["p001", "p003", "p002"])
        self.assertFalse(form.rows["p002"].down.isEnabled())
        form.rows["p001"].down.click()
        self.settle(4)
        self.assertEqual([card.photo_id for card in form.ordered_cards()], ["p003", "p001", "p002"])
        self.assertEqual(form.rows["p001"].up.accessibleName(), "사진 1 위로 옮기기")

    def test_removing_drops_the_row_not_the_file_and_the_last_one_can_be_undone_once(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2))
        self.commit(form.rows["p002"].note.edit, "비 오는 날")
        form.rows["p002"].confirm_box.click()
        self.settle(3)
        removed_card = form.rows["p002"]
        removed_card.remove.click()
        self.settle(5)
        self.assertEqual(list(form.rows), ["p001"])
        self.assertEqual(self.lt(form.notice), "사진 2번을 목록에서 지웠어요. 파일은 그대로 있어요.")
        self.assertTrue(form.undo_button.isVisibleTo(form))
        form.undo_button.click()
        self.settle(5)
        self.assertEqual(list(form.rows), ["p001", "p002"])
        self.assertEqual([card.photo_id for card in form.ordered_cards()], ["p001", "p002"])
        self.assertEqual(board.photo("p002").user_note, "비 오는 날")
        self.assertTrue(board.photo("p002").confirmed_by_user)
        self.assertFalse(form.undo_button.isVisibleTo(form))
        form.rows["p001"].remove.click()
        self.settle(4)
        form.rows["p002"].confirm_box.click()
        self.settle(3)
        self.assertFalse(form.undo_button.isVisibleTo(form), "다른 일을 하면 되돌리기는 사라진다")

    def test_thirty_photos_fill_the_list_and_the_add_button_goes_off(self):
        window, form = self.sheet()
        self.add_photos(form, *[fake_path(number) for number in range(1, 31)])
        self.assertEqual(len(form.rows), 30)
        self.assertFalse(form.add_button.isEnabled())
        self.assertTrue(form.full.isVisibleTo(form))
        self.assertEqual(self.lt(form.full), T["pho_full"].format(n=30))
        self.add_photos(form, fake_path(31))
        self.assertEqual(len(self.pick_calls), 1, "꺼진 단추는 선택 창을 열지 않는다")
        form.rows["p030"].remove.click()
        self.settle(5)
        self.assertTrue(form.add_button.isEnabled())
        self.assertFalse(form.full.isVisibleTo(form))

    def test_the_type_and_setting_lists_can_be_edited_here_and_a_used_name_cannot_be_removed(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        self.assertFalse(form.lists_body.isVisibleTo(form))
        form.lists_toggle.click()
        self.settle(3)
        self.assertTrue(form.lists_body.isVisibleTo(form))
        edit = form.lists_parts["types"]["input"]
        edit.setText("테이블 위")
        form.lists_parts["types"]["add"].click()
        self.settle(4)
        self.assertIn("테이블 위", board.types)
        self.assertEqual(edit.text(), "")
        self.assertEqual(self.lt(form.lists_message), "목록에 더했어요.")
        self.assertIn("테이블 위", form.rows["p001"]._chips_type)
        self.chip(form, "type", "p001", "테이블 위").click()
        self.settle(3)
        remove = [button for button in form.lists_parts["types"]["items"].parentWidget().findChildren(QAbstractButton) if button.property("focus_key") == "pho:list-remove:types:테이블 위"][0]
        self.assertFalse(remove.isEnabled(), "사진이 쓰는 이름은 지울 수 없다")
        keep = [button for button in form.lists_parts["types"]["items"].parentWidget().findChildren(QAbstractButton) if button.property("focus_key") == "pho:list-remove:types:기타"][0]
        self.assertFalse(keep.isEnabled(), "‘기타’ 는 지울 수 없다")
        edit.setText("기타")
        form.lists_parts["types"]["add"].click()
        self.settle(3)
        self.assertEqual(self.lt(form.lists_message), "이미 있는 이름이에요.")
        self.assertEqual(edit.text(), "기타", "거절되면 쓴 글은 그대로")
        self.chip(form, "type", "p001", "간판").click()
        self.settle(3)
        remove = [button for button in form.lists_body.findChildren(QAbstractButton) if button.property("focus_key") == "pho:list-remove:types:테이블 위"][0]
        self.assertTrue(remove.isEnabled())
        remove.click()
        self.settle(3)
        self.assertNotIn("테이블 위", board.types)


# ---- 4) 미리보기·파일 상태·다시 찾기 ---------------------------------------------------------------------------------------------
class PreviewTest(PhotoBase):
    def test_previews_are_made_one_by_one_in_memory_and_shown(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        ui_offscreen.wait_until(self.app, lambda: len(self.maker_calls) >= 3, 5)
        self.settle(4)
        self.assertEqual(sorted(self.maker_calls), sorted(fake_path(number) for number in (1, 2, 3)))
        for card in form.rows.values():
            self.assertFalse(card.preview.pixmap().isNull())
            self.assertEqual(card.preview.text(), "")
        self.assertEqual(self.widget_hits(window, [DIR_MARK]), [])
        calls = len(self.maker_calls)
        form.refresh()
        self.settle(6)
        self.assertEqual(len(self.maker_calls), calls, "같은 사진의 미리보기는 다시 만들지 않는다")

    def test_a_big_png_and_a_missing_file_get_no_preview_and_a_sentence_instead(self):
        provider = pv.FakePhotoProvider(verdicts={fake_path(1, "png"): R.Verdict(R.OK, "", "", 12_000, 12_000, "png"), fake_path(2): R.Verdict(R.OK, "", "", 12_000, 12_000, "jpeg")}, states={fake_path(3): "missing"})
        window = self.drafted(photos=provider)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1, "png"), fake_path(2), fake_path(3))
        ui_offscreen.wait_until(self.app, lambda: len(self.maker_calls) >= 2, 5)
        self.settle(4)
        self.assertEqual(sorted(self.maker_calls), sorted([fake_path(2), fake_path(3)]), "넣을 때는 큰 PNG 만 건너뛴다")
        self.assertEqual(window.photos_close(), "closed")
        provider.states[fake_path(3)] = "missing"                                       # 사진 파일이 그 사이 사라졌다 — 창을 다시 열면 파일 상태를 다시 읽는다
        self.maker_calls.clear()
        window, form = self.sheet(window)
        ui_offscreen.wait_until(self.app, lambda: len(self.maker_calls) >= 1, 5)
        self.settle(6)
        self.assertEqual(self.maker_calls, [fake_path(2)], "큰 PNG(1억 화소 초과)와 없는 파일은 만들지 않는다 — 큰 JPEG 는 만든다")
        big, jpeg, missing = form.rows["p001"], form.rows["p002"], form.rows["p003"]
        self.assertEqual(big.preview.text(), T["pho_preview_blocked"])
        self.assertTrue(big.preview_note.isVisibleTo(form))
        self.assertEqual(self.lt(big.badge), "파일 있음 · 12000×12000", "사진은 그대로 쓸 수 있다")
        self.assertFalse(jpeg.preview.pixmap().isNull())
        self.assertEqual(missing.preview.text(), T["pho_preview_none"])
        self.assertEqual(self.lt(missing.badge), "파일 없음")
        self.assertTrue(missing.relink.isVisibleTo(form))
        self.assertFalse(big.relink.isVisibleTo(form))

    def test_a_maker_that_fails_marks_only_that_row(self):
        calls = []

        def maker(path):
            calls.append(path)
            if path.endswith("-01.jpg"):
                raise RuntimeError(DIR_MARK)
            return None if path.endswith("-02.jpg") else self.make_preview(path)
        window = self.drafted(maker=maker)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        ui_offscreen.wait_until(self.app, lambda: len(calls) >= 3, 5)
        self.settle(6)
        self.assertEqual(form.rows["p001"].preview.text(), T["pho_preview_failed"])
        self.assertEqual(form.rows["p002"].preview.text(), T["pho_preview_failed"])
        self.assertFalse(form.rows["p003"].preview.pixmap().isNull())
        self.assertEqual(self.widget_hits(window, [DIR_MARK]), [], "읽기 도구가 낸 오류의 글이 화면에 나오지 않는다")

    def test_relinking_picks_a_new_file_for_the_same_photo(self):
        provider = pv.FakePhotoProvider()
        window = self.drafted(photos=provider)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1), fake_path(2))
        self.assertEqual(window.photos_close(), "closed")
        provider.states[fake_path(1)] = "missing"                                       # 사진 파일이 그 사이 사라졌다 — 창을 다시 열면 파일 상태를 다시 읽는다
        window, form = self.sheet(window)
        card = form.rows["p001"]
        self.assertEqual(self.lt(card.badge), "파일 없음")
        self.assertTrue(card.relink.isVisibleTo(form))
        self.assertEqual(card.relink.text(), "다시 찾기")
        self.assertEqual(card.relink.accessibleName(), "사진 1 파일 다시 찾기")
        card.confirm_box.click()
        self.relinks.append(fake_path(7, "png"))
        card.relink.click()
        self.settle(6)
        self.assertEqual(self.relink_calls, [(T["pho_relink_title"], f"{T['pho_pick_filter']} {shell_module.IMAGE_FILTER}")])
        board = window.state.drafts.photos
        self.assertEqual(board.photo("p001").local_path, fake_path(7, "png"))
        self.assertFalse(board.photo("p001").confirmed_by_user)
        self.assertEqual(self.lt(card.badge), "파일 있음 · 640×480")
        self.assertFalse(card.relink.isVisibleTo(form))
        self.assertEqual(self.lt(form.notice), "사진 파일을 다시 연결했어요.")
        self.relinks.append("")
        window.photos_relink("p001")                                                   # 선택을 취소하면 그대로
        self.settle(3)
        self.assertEqual(board.photo("p001").local_path, fake_path(7, "png"))

    def test_closing_clears_the_rows_the_previews_and_the_queue_and_reopening_makes_them_again(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        ui_offscreen.wait_until(self.app, lambda: len(self.maker_calls) >= 2, 5)
        self.settle(4)
        board = window.state.drafts.photos
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle(6)
        self.assertIsNone(window.photo_form)
        self.assertFalse(window.dialog.is_open)
        self.assertFalse(board.is_open)
        self.assertEqual((form.rows, form._previews, form._queue, form.board), ({}, {}, [], None))
        self.assertEqual(board.count, 2, "사진 목록은 남는다")
        before = len(self.maker_calls)
        window, again = self.sheet(window)
        ui_offscreen.wait_until(self.app, lambda: len(self.maker_calls) >= before + 2, 5)
        self.settle(4)
        self.assertEqual(list(again.rows), ["p001", "p002"])
        self.assertIsNot(again, form)
        self.assertEqual(len(self.maker_calls), before + 2, "다시 열면 미리보기를 새로 만든다(그림은 닫을 때 버렸다)")


# ---- 5) 접근성·키보드 ------------------------------------------------------------------------------------------------------------
class KeyboardTest(PhotoBase):
    def tab_walk(self, key, steps):
        seen = [QApplication.focusWidget()]
        for _ in range(steps):
            QTest.keyClick(QApplication.focusWidget(), key)
            self.settle(1)
            seen.append(QApplication.focusWidget())
        return seen

    def test_every_button_and_field_has_a_name_a_hit_size_and_a_focus_policy(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2, "png", stem="x" * 80))
        form.rows["p001"].place_toggle.click()
        form.lists_toggle.click()
        self.settle(4)
        buttons = self.buttons_of(form)
        self.assertGreaterEqual(len(buttons), 30)
        for button in buttons:
            with self.subTest(button=button.accessibleName()):
                self.assertTrue(button.accessibleName().strip())
                self.assertGreaterEqual(button.height(), tokens.SIZE["hit"] - 8 if button.property("size") == "sm" else tokens.SIZE["hit"] - 4)
                self.assertNotEqual(button.focusPolicy(), Qt.NoFocus)
        for edit in form.findChildren(QLineEdit):
            if edit.isVisibleTo(form):
                self.assertTrue(edit.accessibleName().strip(), edit.placeholderText())
        row_names = [button.accessibleName() for card in form.ordered_cards() for button in card.findChildren(QAbstractButton) if button.isVisibleTo(form)]
        self.assertEqual(len(row_names), len(set(row_names)), "접근 이름이 겹치지 않는다(줄마다 '사진 N' 이 붙는다)")
        for card in form.ordered_cards():
            self.assertTrue(card.accessibleName().startswith(f"사진 {card.photo_id[1:].lstrip('0')}"))
        self.assertEqual(form.confirm_buttons, [])

    def test_tab_and_shift_tab_walk_the_parts_in_the_visible_order_and_stay_inside_the_dialog(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        form.rows["p001"].remove.setFocus(Qt.TabFocusReason)
        self.settle(2)
        expected = []
        for card in form.ordered_cards():
            expected += [widget for widget in card.stops() if widget.isVisibleTo(form) and widget.isEnabled() and widget.focusPolicy() != Qt.NoFocus]
        expected += [form.lists_toggle, form.add_button, form.all_button, form.close_button]
        form.scroll.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), form.scroll)
        forward = self.tab_walk(Qt.Key_Tab, len(expected) + 1)
        names = lambda widgets: [getattr(widget, "accessibleName", lambda: "?")() for widget in widgets]
        self.assertEqual(forward[1:-1], expected, names(forward))
        self.assertIs(forward[-1], form.scroll, "마지막에서 Tab 을 누르면 대화상자 안의 처음으로 돌아온다 — 바깥으로 새지 않는다")
        backward = self.tab_walk(Qt.Key_Backtab, len(expected) + 1)
        self.assertEqual(backward[1:-1], expected[::-1], names(backward))
        for widget in forward + backward:
            self.assertTrue(form.isAncestorOf(widget) or widget is form, "포커스가 대화상자 밖으로 나갔다")

    def test_the_keyboard_alone_can_add_edit_confirm_and_close(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.assertIs(QApplication.focusWidget(), form.add_button)
        self.picks.append([fake_path(1)])
        form.add_button.setFocus(Qt.TabFocusReason)
        QTest.keyClick(form.add_button, Qt.Key_Space)
        self.settle(8)
        self.assertEqual(board.count, 1)
        card = form.rows["p001"]
        card.subject.edit.setFocus(Qt.TabFocusReason)
        QTest.keyClicks(card.subject.edit, "mainmenu")
        QTest.keyClick(card.subject.edit, Qt.Key_Return)
        self.settle(3)
        self.assertEqual(board.photo("p001").user_subject, "mainmenu")
        card.confirm_box.setFocus(Qt.TabFocusReason)
        QTest.keyClick(card.confirm_box, Qt.Key_Space)
        self.settle(3)
        self.assertTrue(board.photo("p001").confirmed_by_user)
        self.chip(form, "type", "p001", "음식").setFocus(Qt.TabFocusReason)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Space)
        self.settle(3)
        self.assertEqual(board.photo("p001").photo_type, "음식")
        form.close_button.setFocus(Qt.TabFocusReason)
        QTest.keyClick(form.close_button, Qt.Key_Space)
        self.settle(4)
        self.assertIsNone(window.photo_form)

    def test_enter_moves_from_the_subject_to_the_memo_and_from_the_memo_to_the_next_photos_subject(self):
        """설계 5-3 — Enter 는 글을 넘기고 다음 칸으로 간다: 대상 칸 → 같은 사진의 메모 칸 → 다음 사진의 대상 칸(마지막 사진의 메모 칸에서는 그대로)."""
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2))
        first, second = form.rows["p001"], form.rows["p002"]
        first.subject.edit.setFocus(Qt.TabFocusReason)
        QTest.keyClicks(first.subject.edit, "abc")
        QTest.keyClick(first.subject.edit, Qt.Key_Return)
        self.settle(3)
        self.assertEqual(board.photo("p001").user_subject, "abc")
        self.assertIs(QApplication.focusWidget(), first.note.edit)
        QTest.keyClicks(first.note.edit, "memo")
        QTest.keyClick(first.note.edit, Qt.Key_Return)
        self.settle(3)
        self.assertEqual(board.photo("p001").user_note, "memo")
        self.assertIs(QApplication.focusWidget(), second.subject.edit)
        QTest.keyClick(second.subject.edit, Qt.Key_Return)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), second.note.edit)
        QTest.keyClick(second.note.edit, Qt.Key_Return)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), second.note.edit, "다음 사진이 없으면 그대로")
        first.caption.edit.setFocus(Qt.TabFocusReason)
        QTest.keyClick(first.caption.edit, Qt.Key_Return)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), first.caption.edit, "설명 글 칸의 Enter 는 칸을 옮기지 않는다")

    def test_enter_scrolls_a_photo_that_was_off_screen_into_view(self):
        """프로그램으로 옮긴 포커스는 스크롤이 따라가지 않는다(Tab 은 Qt 가 따라간다) — 최소 창에서 사진이 화면 밖일 때 Enter 가 그 사진의 대상 칸을 보이는 곳으로 가져온다."""
        window, form = self.sheet(size=(900, 560))
        self.add_photos(form, *[fake_path(number) for number in range(1, 7)])
        viewport = form.scroll.viewport()
        form.rows["p001"].note.edit.setFocus(Qt.TabFocusReason)
        QTest.keyClick(form.rows["p001"].note.edit, Qt.Key_Return)
        self.settle(3)
        for number in range(2, 7):
            photo_id = f"p{number:03d}"
            box = form.rows[photo_id].subject
            subject = box.edit
            self.assertIs(QApplication.focusWidget(), subject, photo_id)
            top = box.mapTo(viewport, box.rect().topLeft()).y()
            bottom = box.mapTo(viewport, box.rect().bottomLeft()).y()
            self.assertTrue(0 <= top and bottom <= viewport.height(), (photo_id, top, bottom, viewport.height()))     # 이름표·입력 칸·글자 수 칸 전체가 보인다(입력 칸만 맞추면 Qt 는 글자 커서 줄만 맞춘다)
            QTest.keyClick(subject, Qt.Key_Return)                                       # 대상 → 같은 사진의 메모
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Return)                    # 메모 → 다음 사진의 대상
            self.settle(3)
        self.assertGreater(form.scroll.verticalScrollBar().value(), 0, "몸이 스크롤됐다")

    def test_focus_returns_to_the_card_button_that_opened_the_sheet(self):
        window = self.drafted()
        ui = self.ui(window)
        ui.photos_button.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.button(window, "drf-photos").click()
        self.settle(8)
        self.assertIsNotNone(window.photo_form)
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle(8)
        self.assertIsNone(window.photo_form)
        self.assertIs(QApplication.focusWidget(), ui.photos_button)


# ---- 6) 크기 ------------------------------------------------------------------------------------------------------------------------
class FitTest(PhotoBase):
    def check_fit(self, window, form, label):
        dialog = window.dialog
        self.assertTrue(window.rect().contains(dialog.geometry()), (label, dialog.geometry(), window.rect()))
        self.assertEqual(form.scroll.horizontalScrollBar().maximum(), 0, label)
        self.assertEqual(ui_offscreen.find_clipping(dialog), [], label)
        self.assertEqual(ui_offscreen.find_squeezed(dialog), [], label)
        for button in (form.add_button, form.all_button, form.close_button):
            bottom = button.mapTo(window, button.rect().bottomRight())
            self.assertTrue(window.rect().contains(bottom) and button.isVisible(), (label, button.accessibleName()))
        for widget in (form.notice, *form.confirm_buttons):
            if widget.isVisibleTo(form):
                self.assertTrue(window.rect().contains(widget.mapTo(window, widget.rect().bottomRight())), (label, "상태 줄이 창 밖이다"))

    def test_every_state_fits_every_size_without_clipping_scrolling_sideways_or_hiding_the_buttons(self):
        for size in SIZES:
            with self.subTest(size=size):
                window, form = self.sheet(size=size)
                self.check_fit(window, form, (size, "빈 창"))
                self.add_photos(form, fake_path(1), fake_path(2, "png", stem="가" * 70), fake_path(3), fake_path(4, "gif"))
                self.check_fit(window, form, (size, "사진 세 장과 못 넣은 파일"))
                card = form.rows["p001"]
                self.chip(form, "type", "p001", "간판").click()
                self.settle(3)
                self.commit(card.subject.edit, "가" * 60)
                card.note.edit.setText("나" * 301)
                self.settle(3)
                self.check_fit(window, form, (size, "한도를 넘긴 글"))
                card.note.edit.setText("메모")
                form.all_button.click()
                self.settle(6)
                self.check_fit(window, form, (size, "모두 확인 줄"))
                form.confirm_buttons[-1].click()
                self.settle(4)
                form.rows["p003"].remove.click()
                self.settle(5)
                self.check_fit(window, form, (size, "지운 뒤 되돌리기"))
                form.lists_toggle.click()
                self.settle(4)
                self.check_fit(window, form, (size, "목록 고치기"))
                self.assertEqual(window.photos_close(), "closed", "칸에 남은 글(메모)은 닫을 때 넘어가고 한도를 넘긴 글은 없다")
                window.close()

    def test_thirty_long_rows_fit_in_the_minimum_window(self):
        window, form = self.sheet(size=(900, 560))
        self.add_photos(form, *[fake_path(number, stem="길" * 60) for number in range(1, 31)])
        self.check_fit(window, form, "30장")
        self.assertGreater(form.scroll.verticalScrollBar().maximum(), 0, "몸이 길면 스크롤된다")
        for button in (form.add_button, form.all_button, form.close_button):
            self.assertFalse(form.scroll.isAncestorOf(button), "단추 줄은 스크롤 밖에 늘 보인다")


# ---- 6-2) 화면 배율 125%·150% ---------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAVE and os.name == "nt", "PySide6 와 윈도 글꼴이 있어야 한다(글자 잘림은 글꼴에 달렸다)")
class ScaleTest(unittest.TestCase):
    """배율은 프로세스가 시작될 때 `QT_SCALE_FACTOR` 환경 변수로 정해야 해서 자식 프로세스(`tests/photo_scale_probe.py`)를 배율마다 돌린다 — **실제 윈도 배율 설정이 아니라 Qt 자체의 High DPI 경로로 흉내 낸 것이다**
    (실제 윈도 125·150% 렌더·한글 입력기·화면 읽기 프로그램은 운영자 PC 에서 본다). 창의 논리 크기는 화면 크기를 배율로 나눈 값이다."""
    ENVIRONMENTS = ((1366, 768, 1.0), (1920, 1080, 1.0), (1536, 864, 1.25), (1280, 720, 1.5), (900, 560, 1.0))

    def probe(self, width, height, scale):
        environment = dict(os.environ, PYTHONUTF8="1")
        environment.pop("QT_SCALE_FACTOR", None)
        if scale != 1.0:
            environment["QT_SCALE_FACTOR"] = str(scale)
        done = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tests" / "photo_scale_probe.py"), str(width), str(height)], capture_output=True, text=True, encoding="utf-8", env=environment, timeout=240,
                              creationflags=0x08000000)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_the_sheet_fits_every_environment_without_clipping_scrolling_sideways_or_hiding_the_buttons(self):
        for width, height, scale in self.ENVIRONMENTS:
            with self.subTest(size=(width, height), scale=scale):
                report = self.probe(width, height, scale)
                self.assertEqual(report["scale"], scale)
                self.assertEqual(report["logical"], [width, height])
                self.assertEqual([item["label"] for item in report["reports"]], ["빈 창", "사진 세 장과 못 넣은 파일", "한도를 넘긴 글", "모두 확인 줄", "지운 뒤 되돌리기", "목록 고치기"])
                for item in report["reports"]:
                    label = (width, height, scale, item["label"])
                    self.assertTrue(item["inside"], label)
                    self.assertEqual(item["hscroll"], 0, label)
                    self.assertEqual(item["clipping"], [], label)
                    self.assertEqual(item["squeezed"], [], label)
                    self.assertTrue(item["buttons"], label)


# ---- 7) 읽기 전용·네트워크 없음(진짜 사진 파일) -------------------------------------------------------------------------------------
class RealFilesTest(PhotoBase):
    def make_image(self, name, fmt, width=40, height=30):
        path = self.tmp / name
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor("#aa5533"))
        self.assertTrue(image.save(str(path), fmt))
        return str(path)

    def snapshot(self):
        return {item.name: item.read_bytes() for item in sorted(self.tmp.iterdir()) if item.is_file()}

    def test_real_photos_get_previews_and_nothing_is_written_read_or_sent_anywhere_else(self):
        png, jpg = self.make_image("메뉴판.png", "PNG"), self.make_image("간판.jpg", "JPG", 64, 48)
        broken = self.tmp / "가짜.jpg"
        broken.write_bytes(b"this is not an image")
        before = self.snapshot()
        with NoNetwork():
            window = self.drafted(real_files=True)
            window, form = self.sheet(window)
            self.add_photos(form, png, jpg, str(broken), str(self.tmp / "없는파일.png"))
            ui_offscreen.wait_until(self.app, lambda: all(not card.preview.pixmap().isNull() for card in form.rows.values()) and len(form.rows) == 2, 8)
            self.settle(4)
            self.assertEqual(list(form.rows), ["p001", "p002"])
            self.assertEqual([self.lt(card.badge) for card in form.ordered_cards()], ["파일 있음 · 40×30", "파일 있음 · 64×48"])
            for card in form.rows.values():
                pixmap = card.preview.pixmap()
                self.assertFalse(pixmap.isNull())
                self.assertLessEqual(max(pixmap.width(), pixmap.height()), rules.THUMB_SIDE)
            shown = self.shown_texts(form.rejected_host)
            self.assertIn(f"가짜.jpg — {T['img_local_not_image']}", shown)
            self.assertIn(f"없는파일.png — {T['img_local_missing']}", shown)
            self.commit(form.rows["p001"].subject.edit, "메뉴판 앞면")
            form.rows["p001"].confirm_box.click()
            self.settle(3)
            os.remove(png)
            window.state.drafts.photos.refresh_files()
            form.refresh()
            self.settle(4)
            self.assertEqual(self.lt(form.rows["p001"].badge), "파일 없음")
            self.assertTrue(form.rows["p001"].relink.isVisibleTo(form))
            window.photos_close()
            self.settle(4)
        after = self.snapshot()
        self.assertEqual(sorted(after), sorted(set(before) - {"메뉴판.png"}), "지운 것은 시험이 지운 사진 하나뿐 — 새 파일(썸네일·임시·메모)이 생기지 않았다")
        for name, data in after.items():
            self.assertEqual(data, before[name], f"{name}: 원본이 바뀌었다")


if __name__ == "__main__":
    unittest.main()
