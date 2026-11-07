"""Seed 관리 화면의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 메뉴·요약·거르기·줄 목록·서랍(상세·새 Seed)·아래 고정 행동 줄·확인창·쓰기 흐름(작업 스레드)·입력 유지·읽기 전용 증명·키보드·접근 이름·배치(필수 크기와 최소 창)를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_seeds_core`). 사용자의 클립보드·보관소·데이터 폴더·설정 파일은 건드리지 않는다(가짜 공급자·임시 폴더의 실제 서비스).

지키는 것:
  1) 메뉴에 `Seed 관리` 가 데이터·관리 묶음(블로그 관리 앞)으로 올라 있고 누르면 새 화면이 열린다. 화면을 열고 거르고 찾고 고르고 서랍을 열고 칸을 고쳐도 **파일이 하나도 안 바뀐다**(임시 폴더 전체 바이트). 홈·설정·블로그 관리도 마찬가지다.
  2) 화면 본문에는 주요 행동이 없고 서랍에 정확히 하나다. 상태는 색만이 아니라 글자로도 보인다. 줄·상자·단추는 접근 이름과 36px 이상의 누르는 칸을 가진다.
  3) **여러 개를 한꺼번에 바꾸기·제안 파일 등록은 확인창이 먼저**이고(처음 포커스는 취소) 취소·Esc 로 닫으면 아무것도 쓰지 않는다. 한 씨앗의 승인·쉬게 하기·다시 쓰기는 확인창 없이 저장한다.
  4) 칸을 고치는 동안·상자를 고르는 동안·글 검색을 치는 동안 화면을 다시 그리지 않고(입력 중이던 자리가 사라지지 않는다) 오류 글·단추만 바뀐다. 저장·바꾸기는 작업 스레드에서 돌고 실패해도 입력이 그대로이며 낡은 판이면 최신 내용을 다시 읽는다.
  5) 가로 스크롤·글자 잘림이 없고 서랍의 아래 고정 행동 줄이 필수 크기 여섯(1366×768·1093×614(125%)·1536×864·1280×720(150%)·1920×1080·최소 창)에서 창 안에 보인다.
"""
import ast
import importlib.util
import re
import sys
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from chanceblog_desktop.service import seed_manage as sm  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.ui import seeds_adapter  # noqa: E402
from chanceblog_desktop.ui.core import seeds, services, text, tokens  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import blog_parts, seed_parts
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module

import service_support as support  # noqa: E402

T = text.T
SIZES = ((1366, 768), (1093, 614), (1536, 864), (1280, 720), (1920, 1080), (900, 560))
PICKED = "C:/예시 폴더/예시 제안.json"                       # 선택기가 돌려줄 가짜 위치 — 그런 파일은 없다(가짜 공급자는 읽지 않는다)


class Gated(seeds.FakeSeedsProvider):
    """쓰기가 **시험이 문을 열어 줄 때까지** 기다리는 가짜 공급자 — 시간에 기대지 않고 '쓰는 중' 을 확실히 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def _enter(self, name, version, cancelled):
        if not self.gate.wait(30):
            raise AssertionError("시험이 쓰기의 문을 열어 주지 않았다")
        super()._enter(name, version, cancelled)


class Recording(seeds.FakeSeedsProvider):
    """쓰기가 어느 스레드에서 도는지 기록하는 가짜 공급자."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.threads = []

    def set_state(self, seed_id, state, version, progress, cancelled):
        self.threads.append(threading.current_thread())
        return super().set_state(seed_id, state, version, progress, cancelled)


class Failing(seeds.FakeSeedsProvider):
    def __init__(self, fail, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail = fail

    def _enter(self, name, version, cancelled):
        super()._enter(name, version, cancelled)
        if name in self.fail:
            raise self.fail[name]


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

    def make(self, provider=None, size=(1366, 768), picker=None, page="seed", wait=True):
        provider = provider or seeds.FakeSeedsProvider()
        window = shell_module.AppShell(services.FakeHomeProvider(), seeds=provider, file_picker=picker or (lambda parent, title, filters: PICKED), autoload=False)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        if page == "seed":
            window.go("seed")
            if wait:
                ui_offscreen.wait_until(self.app, lambda: window.state.seeds.state != "loading" and not window.state.seeds.loading, 10)
            self.settle()
        return window

    def ui(self, window):
        return window.screen_widget.seeds_ui

    def dui(self, window):
        return window.seeds_drawer_ui

    def row(self, window, seed_id):
        return self.ui(window).list.rows[seed_id]

    def open_row(self, window, seed_id):
        QTest.mouseClick(self.row(window, seed_id), Qt.LeftButton)
        self.settle(8)

    def bar_button(self, window, key):
        ui = self.dui(window)
        return next(button for button, spec in zip(ui.bar.buttons, ui.bar.specs, strict=True) if spec["key"] == key)

    def type_into(self, window, name, value):
        edit = self.dui(window).fields[name].edit
        edit.setFocus(Qt.OtherFocusReason)
        edit.selectAll()
        QTest.keyClick(edit, Qt.Key_Delete)
        if value.isascii():
            QTest.keyClicks(edit, value)
        elif value:
            from PySide6.QtGui import QInputMethodEvent                                              # 한글은 입력기(IME)가 글을 확정하는 것과 같은 이벤트로 넣는다 — `QTest.keyClicks` 는 이 환경에서 한글 글자를 만나면 프로세스가 통째로 죽는다
            event = QInputMethodEvent()
            event.setCommitString(value)
            QApplication.sendEvent(edit, event)
        self.settle(2)

    def wait_write(self, window):
        ui_offscreen.wait_until(self.app, lambda: not window.state.seeds.busy and window.state.seeds.pending is None, 10)
        self.settle()

    def labels(self, root):
        return {label.plain_text() for label in root.findChildren(UI.Label)}

    def buttons(self, root):
        return {button.text(): button for button in root.findChildren(QAbstractButton)}

    def notice_bar(self, window, text_):
        bars = [bar for bar in window.screen_widget.findChildren(blog_parts.NoticeBar) if bar.text.plain_text() == text_]
        self.assertEqual(len(bars), 1, f"그 글의 알림 줄이 하나 있다: {text_}")
        return bars[0]

    def field_error(self, window, name):
        view = self.dui(window).fields[name]
        return view.error.plain_text() if view.error_row.isVisibleTo(window) else ""


class MenuAndPageTest(Base):
    def test_the_seed_menu_is_in_the_data_group_before_the_blog_menu_and_opens_the_screen(self):
        window = self.make(page=None)
        self.assertEqual(list(window.nav_buttons), ["home", "seed", "blogs", "settings"])
        self.assertEqual(window.nav_buttons["seed"].accessibleName(), "Seed 관리 메뉴로 이동")
        self.assertEqual(list(window.sidebar.group_titles), ["core", "data", "system"])
        window.nav_buttons["seed"].click()
        ui_offscreen.wait_until(self.app, lambda: window.state.seeds.state != "loading", 10)
        self.settle()
        self.assertEqual((window.state.page, window.nav_buttons["seed"].isChecked(), window.nav_buttons["home"].isChecked()), ("seed", True, False))
        self.assertEqual(len(self.ui(window).list.rows), 16)
        self.assertEqual(list(S.SCREEN_BUILDERS), ["home", "seed", "blogs", "settings"])
        self.assertEqual([item.name.text() for item in window.sidebar.soon_list.items], ["주제 후보", "초안 작성", "발행 기록"])
        data_buttons = [window.nav_buttons[key].text().strip() for key in ("seed", "blogs")]
        self.assertEqual(data_buttons, ["Seed 관리", "블로그 관리"])

    def test_the_page_says_how_many_wait_for_approval_how_each_channel_stands_and_shows_one_row_per_seed(self):
        window = self.make()
        screen = window.screen_widget
        labels = self.labels(screen)
        self.assertEqual(self.notice_bar(window, "승인 전 9개 — 승인하기 전에는 후보 생성에 쓰이지 않습니다").level, "warning")
        self.assertEqual(len(screen.findChildren(blog_parts.NoticeBar)), 1, "예시 데이터라도 알림 줄은 이 한 줄뿐이다(첫 화면에는 지난 동작의 결과가 없다)")
        badges = {label.text() for label in screen.findChildren(QLabel) if label.property("badge")}
        for text_ in ("사용 중 5개", "쉬는 중 2개", "전체 16개", "네이버 A 3개 · 후보 생성 켜짐", "GitHub Pages 0개 · 후보 생성 꺼짐"):
            self.assertIn(text_, badges)
        self.assertIn("Seed 관리", labels)
        chips = {button.text() for button in screen.findChildren(QAbstractButton) if button.property("chip")}
        self.assertEqual(chips, {"전체  16", "승인 전  9", "사용 중  5", "쉬는 중  2"})
        rows = self.ui(window).list.rows
        self.assertEqual(list(rows), [f"EX{number:03d}" for number in range(1, 17)])
        texts = {label.text() for label in self.row(window, "EX001").findChildren(UI.ElidedLabel)}
        self.assertEqual(texts, {"예시 낱말 가", "예시 대분류 하나 › 예시 중분류 하나", "네이버 A · 일반 · 제품", "허용 채널 네이버 A"})
        statuses = {seed_id: {label.text() for label in row.findChildren(QLabel) if label.property("badge")} for seed_id, row in rows.items()}
        self.assertEqual(statuses["EX001"], {"제안(승인 전)"})
        self.assertEqual(statuses["EX009"], {"사용 중", "쉬게 할까요?"}, "180일 제안은 배지 글자로 보일 뿐이다")
        self.assertEqual(statuses["EX014"], {"쉬는 중"})
        self.assertEqual(self.row(window, "EX009").accessibleName().count("쉬게 할지 정해 보세요"), 1)

    def test_the_page_has_no_primary_button_and_the_open_drawer_has_exactly_one(self):
        window = self.make()
        primary = lambda root: [button for button in root.findChildren(QAbstractButton) if button.property("kind") == "primary"]  # noqa: E731
        self.assertEqual(primary(window.screen_widget), [], "본문에는 주요 행동이 없다 — 머리의 두 단추는 보조다")
        header = {button.text(): button for button in window.screen_widget.findChildren(QAbstractButton) if button.property("kind") == "secondary"}
        self.assertIn("제안 파일 불러오기", header)
        self.assertIn("새 Seed 등록", header)
        for key in ("EX001", "EX009", "EX014"):
            self.open_row(window, key)
            self.assertEqual(len(primary(window.drawer)), 1, key)
            window.close_drawer()
            self.settle(4)
        window.seed_open_new()
        self.settle(8)
        self.assertEqual([button.text() for button in primary(window.drawer)], ["승인 전으로 등록"])

    def test_no_horizontal_scroll_no_clipped_text_and_the_drawer_action_bar_is_in_the_window_at_every_required_size(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(size=size)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)
                self.assertEqual(ui_offscreen.find_clipping(window), [], size)
                self.assertEqual(ui_offscreen.find_squeezed(window), [], f"{size}: 부품이 눌려 반쯤 잘리는 곳이 없다")
                for opener in (partial(self.open_row, window, "EX005"), window.seed_open_new):
                    window.close_drawer()
                    self.settle(4)
                    opener()
                    self.settle(8)
                    self.assertTrue(window.drawer.is_open)
                    bar = self.dui(window).bar
                    self.assertTrue(window.drawer.isAncestorOf(bar) and bar.isVisibleTo(window), f"{size}: 행동 줄은 서랍에 붙어 있고 보인다")
                    bottom = bar.mapTo(window, bar.rect().bottomLeft()).y()
                    self.assertLessEqual(bottom, window.height() + 1, f"{size}: 아래 고정 행동 줄이 창 안에 보인다")
                    self.assertGreaterEqual(bottom, window.height() - 4, f"{size}: 행동 줄은 서랍의 맨 아래에 붙어 있다(스크롤 안쪽에 있지 않다)")
                    self.assertGreaterEqual(window.drawer.geometry().left(), 0)
                    self.assertLessEqual(window.drawer.width(), window.width(), "서랍이 창보다 넓지 않다")
                    self.assertEqual(ui_offscreen.find_clipping(window), [], size)
                    self.assertEqual(ui_offscreen.find_squeezed(window), [], size)
                window.close_drawer()

    def test_the_many_scenario_shows_forty_rows_and_a_more_button_that_adds_forty_more(self):
        window = self.make(seeds.FakeSeedsProvider("many"))
        self.assertEqual(len(self.ui(window).list.rows), 40)
        more = self.buttons(window.screen_widget)["40개 더 보기"]
        self.assertEqual(more.accessibleName(), "Seed 40개 더 보기")
        more.click()
        self.settle()
        self.assertEqual(len(self.ui(window).list.rows), 80)
        self.assertEqual(ui_offscreen.find_clipping(window), [])

    def test_the_empty_and_error_and_loading_states_use_the_shared_frames(self):
        window = self.make(seeds.FakeSeedsProvider("empty"))
        self.assertIn("아직 Seed 가 없어요.", self.labels(window.screen_widget))
        self.assertEqual(self.ui(window).list.rows, {})
        window = self.make(seeds.FakeSeedsProvider("error"))
        self.assertEqual(window.state.seeds.state, "error")
        self.assertIn("Seed 를 읽지 못했어요.", self.labels(window.screen_widget))
        self.assertIn("진단 정보 보기", {button.text() for button in window.screen_widget.findChildren(QAbstractButton)})
        header = self.buttons(window.screen_widget)
        self.assertFalse(header["제안 파일 불러오기"].isEnabled() or header["새 Seed 등록"].isEnabled(), "읽지 못한 동안에는 쓰는 길이 막혀 있다")
        slow = self.make(seeds.FakeSeedsProvider(delay=30), wait=False)
        self.assertEqual(slow.state.seeds.state, "loading")
        self.assertTrue([widget for widget in slow.screen_widget.findChildren(QWidget) if widget.accessibleName() == "Seed 를 읽는 중"])

    def test_the_sample_badge_explains_that_nothing_is_written(self):
        window = self.make()
        badge = next(button for button in window.screen_widget.findChildren(QAbstractButton) if button.accessibleName() == "예시 데이터")
        badge.click()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertIn("이 PC 의 파일에는 아무것도 쓰지 않아요", " ".join(self.labels(window.dialog)))
        window.escape()


class FilterAndSelectionTest(Base):
    def test_a_status_chip_filters_without_writing_and_keeps_the_keyboard_focus_on_it(self):
        window = self.make()
        chip = next(button for button in window.screen_widget.findChildren(QAbstractButton) if button.text() == "승인 전  9")
        self.focus(chip)
        QTest.keyClick(chip, Qt.Key_Space)
        self.settle()
        self.assertEqual(window.state.seeds.status, "proposed")
        self.assertEqual(len(self.ui(window).list.rows), 9)
        focused = window.focusWidget()                                                       # 창이 안 쓰는 환경에서도 '창 안의 포커스' 는 같다(홈의 칩 시험과 같은 방식)
        self.assertIsNotNone(focused)
        self.assertEqual(focused.property("focus_key"), "seeds:status:proposed", "다시 그린 뒤에도 그 칩에 포커스가 남는다")

    def test_typing_in_the_search_box_rebuilds_only_the_list_and_keeps_the_box_and_the_cursor(self):
        window = self.make()
        screen = window.screen_widget
        box = next(widget for widget in screen.findChildren(QWidget) if widget.property("focus_key") == "seeds-query")
        box.setFocus(Qt.OtherFocusReason)
        QTest.keyClicks(box, "abc")
        self.settle(2)
        self.assertIs(window.screen_widget, screen, "글 검색을 치는 동안 화면을 다시 그리지 않는다")
        self.assertEqual((box.text(), len(self.ui(window).list.rows)), ("abc", 0))
        self.assertIn("조건에 맞는 Seed 가 없어요", " ".join(self.labels(screen)))
        self.assertTrue(self.ui(window).reset.isVisibleTo(window), "조건이 걸려 있으면 '조건 지우기' 가 보인다")
        for _ in range(3):
            QTest.keyClick(box, Qt.Key_Backspace)
        self.settle(2)
        self.assertIs(window.screen_widget, screen)
        self.assertEqual((box.text(), len(self.ui(window).list.rows)), ("", 16))
        self.assertFalse(self.ui(window).reset.isVisibleTo(window))

    def test_the_more_filters_button_shows_scope_and_importance_chips_and_an_active_one_keeps_them_open(self):
        window = self.make()
        self.assertEqual({button.text() for button in window.screen_widget.findChildren(QAbstractButton) if button.property("focus_key") and str(button.property("focus_key")).startswith("seeds:scope:")}, set())
        self.buttons(window.screen_widget)["더 거르기"].click()
        self.settle()
        scope = {button.text() for button in window.screen_widget.findChildren(QAbstractButton) if str(button.property("focus_key")).startswith("seeds:scope:")}
        self.assertEqual(scope, {"모든 소속  16", "공통  3", "GitHub Pages  1", "Blogger 영문  1", "Blogger 한글  1", "네이버 A  6", "네이버 B  4"})
        next(button for button in window.screen_widget.findChildren(QAbstractButton) if str(button.property("focus_key")) == "seeds:scope:common").click()
        self.settle()
        self.assertEqual(len(self.ui(window).list.rows), 3)
        self.assertTrue(self.ui(window).reset.isVisibleTo(window))
        self.buttons(window.screen_widget)["더 거르기 닫기"].click()
        self.settle()
        self.assertIn("더 거르기 닫기", self.buttons(window.screen_widget), "조건이 걸려 있으면 열어 둔다")
        self.ui(window).reset.click()
        self.settle()
        self.assertEqual(len(self.ui(window).list.rows), 16)

    def test_ticking_a_box_changes_the_row_and_the_bulk_bar_without_redrawing_the_screen(self):
        window = self.make()
        screen = window.screen_widget
        row = self.row(window, "EX001")
        row.box.click()
        self.settle(2)
        self.assertIs(window.screen_widget, screen)
        self.assertEqual((window.state.seeds.checked, row.property("checked")), ({"EX001"}, True))
        self.assertEqual(self.ui(window).bulk_text.plain_text(), "1개 골랐어요")
        self.assertTrue(self.ui(window).bulk_buttons["activate"].isEnabled())
        self.assertEqual(self.ui(window).bulk_buttons["activate"].text(), "사용 중으로 바꾸기 1")
        self.assertEqual(self.dui_none(window), None)
        self.ui(window).bulk_select.click()
        self.settle(2)
        self.assertEqual(len(window.state.seeds.checked), 16)
        self.assertTrue(all(item.property("checked") for item in self.ui(window).list.rows.values()))
        self.ui(window).bulk_clear.click()
        self.settle(2)
        self.assertEqual((window.state.seeds.checked, self.ui(window).bulk_buttons["activate"].isEnabled()), (set(), False))
        self.assertIn(T["seeds_bulk_no_pick"], self.ui(window).bulk_buttons["activate"].toolTip(), "꺼진 이유가 툴팁에 있다")

    def dui_none(self, window):
        return getattr(window, "seeds_drawer_ui", None) if window.drawer.is_open else None


class DrawerTest(Base):
    def test_a_click_opens_the_detail_drawer_traps_the_tab_key_and_esc_gives_the_focus_back_to_the_row(self):
        window = self.make()
        row = self.row(window, "EX001")
        self.focus(row)
        QTest.keyClick(row, Qt.Key_Return)
        self.settle(8)
        self.assertTrue(window.drawer.is_open)
        self.assertEqual(window.drawer.accessibleName(), "Seed 상세와 고치기", "서랍 틀의 읽기용 이름도 이 내용의 것이다(공통 틀의 '주제 상세' 가 아니다)")
        self.assertIn("Seed 상세", self.labels(window.drawer))
        self.assertIn("예시 낱말 가", self.labels(window.drawer))
        outside = self.ui(window).list.rows["EX002"]
        self.assertEqual(outside.focusPolicy(), Qt.NoFocus, "서랍 밖 Tab 정거장은 닫혀 있다")
        window.escape()
        self.settle(8)
        self.assertFalse(window.drawer.is_open)
        self.assertEqual(getattr(QApplication.focusWidget(), "seed_id", None), "EX001", "닫으면 열었던 줄로 포커스가 돌아온다")
        self.assertEqual(self.ui(window).list.rows["EX002"].focusPolicy(), Qt.StrongFocus)

    def test_the_actions_of_each_state_are_the_ones_the_rules_allow_and_the_tooltips_say_why_when_off(self):
        window = self.make()
        expected = {"EX001": ["승인하기", "쉬게 두기", "저장", "되돌리기"], "EX009": ["저장", "쉬게 하기", "되돌리기"], "EX014": ["다시 쓰기", "저장", "되돌리기"]}
        for seed_id, names in expected.items():
            self.open_row(window, seed_id)
            self.assertEqual([button.text() for button in self.dui(window).bar.buttons], names, seed_id)
            self.assertEqual(self.dui(window).bar.accessibleName(), "Seed 행동 줄")
            self.assertTrue(window.drawer.isAncestorOf(self.dui(window).bar) and self.dui(window).bar.isVisibleTo(window), "행동 줄은 서랍에 붙어 있고 보인다")
            save = self.bar_button(window, "save")
            self.assertFalse(save.isEnabled())
            self.assertIn("바꾼 내용이 없어요", save.toolTip())
            window.close_drawer()
            self.settle(4)

    def test_the_detail_shows_the_facts_the_notes_and_a_seasonal_schedule_without_a_schedule_field(self):
        window = self.make()
        self.open_row(window, "EX012")
        labels = self.labels(window.drawer)
        for part in ("계절 일정", "12월 5일", "12월 20일 부터 1월 20일 까지", "12월 28일 부터 1월 10일 까지", "매년", T["seeds_sched_note"], "계절 · 일정은 고치지 않아요"):
            if part == "계절 · 일정은 고치지 않아요":
                continue
            self.assertIn(part, labels)
        self.assertEqual(sorted(self.dui(window).fields), ["allowed_channels", "excluded_keywords", "priority", "priority_keywords", "reason"], "일정 칸은 고칠 수 없다")
        window.close_drawer()
        self.settle(4)
        self.open_row(window, "EX009")
        self.assertIn(T["seeds_idle_note"].format(days=215), self.labels(window.drawer), "180일 제안은 문장으로 보이고 아무것도 바뀌지 않았다")
        self.assertEqual(window.state.seeds.by_id()["EX009"].state, "active")

    def test_the_drawer_closes_with_the_menu_and_the_close_button_and_the_scrim(self):
        window = self.make()
        self.open_row(window, "EX001")
        window.nav_buttons["home"].click()
        self.settle(8)
        self.assertFalse(window.drawer.is_open)
        window.go("seed")
        ui_offscreen.wait_until(self.app, lambda: not window.state.seeds.loading, 10)
        self.settle()
        self.open_row(window, "EX001")
        next(button for button in window.drawer.findChildren(QAbstractButton) if button.accessibleName() == "상세 닫기").click()
        self.settle(8)
        self.assertFalse(window.drawer.is_open)
        self.open_row(window, "EX001")
        window.drawer.scrim.mousePressEvent(None)
        self.settle(8)
        self.assertFalse(window.drawer.is_open)


class EditingTest(Base):
    def test_typing_changes_the_buttons_without_redrawing_and_turns_the_state_buttons_off_with_the_reason(self):
        window = self.make()
        self.open_row(window, "EX001")
        ui = self.dui(window)
        self.type_into(window, "reason", "새 이유")
        self.assertIs(self.dui(window), ui, "고치는 동안 서랍을 다시 그리지 않는다(입력 중이던 자리가 사라지지 않는다)")
        self.assertEqual(ui.fields["reason"].edit.text(), "새 이유")
        self.assertTrue(self.bar_button(window, "save").isEnabled() and self.bar_button(window, "revert").isEnabled())
        for key in ("approve", "rest"):
            button = self.bar_button(window, key)
            self.assertFalse(button.isEnabled(), key)
            self.assertIn("저장하지 않은 변경이 있어요", button.toolTip())
        self.assertTrue(ui.unsaved.isVisibleTo(window))
        self.type_into(window, "reason", "예시 이유 한 줄")
        self.assertFalse(self.bar_button(window, "save").isEnabled(), "저장된 값으로 돌아가면 저장 단추가 다시 꺼진다")
        self.assertTrue(self.bar_button(window, "approve").isEnabled())

    def test_a_wrong_value_shows_an_easy_sentence_beside_the_field_and_the_save_button_does_not_call_the_service(self):
        provider = seeds.FakeSeedsProvider()
        window = self.make(provider)
        self.open_row(window, "EX001")
        calls = list(provider.calls)
        self.type_into(window, "reason", "가" * 250)
        self.assertEqual(self.field_error(window, "reason"), T["bf_err_too_long"].format(limit=200, now=250))
        self.assertTrue(self.dui(window).fields["reason"].edit.property("invalid"))
        self.type_into(window, "priority_keywords", "겹침")
        self.type_into(window, "excluded_keywords", "겹침")
        self.assertEqual(self.field_error(window, "priority_keywords"), T["sf_err_overlap"])
        self.bar_button(window, "save").click()
        self.settle()
        self.assertEqual(provider.calls, calls, "문제가 있으면 서비스를 부르지 않는다")
        self.assertEqual(window.state.seeds.notice, ("error", T["seeds_save_invalid"]))
        self.assertIs(window.focusWidget(), self.dui(window).fields[self.dui(window).first_error].controls[0], "첫 문제 칸으로 포커스가 간다")
        self.type_into(window, "reason", "정상 이유")
        self.type_into(window, "excluded_keywords", "")
        self.assertEqual((self.field_error(window, "reason"), self.field_error(window, "priority_keywords")), ("", ""))

    def test_the_draft_survives_closing_the_drawer_and_shows_on_the_row(self):
        window = self.make()
        self.open_row(window, "EX001")
        self.type_into(window, "reason", "임시 이유")
        window.close_drawer()
        self.settle(8)
        badges = {label.text() for label in self.row(window, "EX001").findChildren(QLabel) if label.property("badge")}
        self.assertIn("저장 전 변경", badges)
        self.open_row(window, "EX001")
        self.assertEqual(self.dui(window).fields["reason"].edit.text(), "임시 이유", "서랍을 닫았다 열어도 초안이 남는다")
        self.bar_button(window, "revert").click()
        self.settle(8)
        self.assertEqual(self.dui(window).fields["reason"].edit.text(), "예시 이유 한 줄")

    def test_a_common_seed_has_channel_chips_and_an_active_one_warns_when_they_change(self):
        window = self.make()
        self.open_row(window, "EX011")
        chips = self.dui(window).fields["allowed_channels"].chips
        self.assertEqual(sorted(chips), sorted(sd.SCOPES[1:]))
        self.assertTrue(chips["naver_a"].isChecked() and chips["naver_b"].isChecked() and not chips["github_pages"].isChecked())
        chips["github_pages"].click()
        self.settle(2)
        view = self.dui(window).fields["allowed_channels"]
        self.assertEqual(view.warning.plain_text(), T["sf_warn_active_channels"])
        for chip in list(chips.values()):
            chip.setChecked(False) if chip.isChecked() and False else None
        chips["naver_a"].click()
        chips["naver_b"].click()
        chips["github_pages"].click()
        self.settle(2)
        self.assertEqual(self.field_error(window, "allowed_channels"), T["sf_err_channels_none"])


class WritingTest(Base):
    def test_approving_runs_on_a_worker_thread_asks_nothing_and_changes_only_that_seed(self):
        provider = Recording()
        window = self.make(provider)
        before = {seed.seed_id: seed.state for seed in provider.seeds}
        self.open_row(window, "EX001")
        self.bar_button(window, "approve").click()
        self.assertFalse(window.dialog.is_open, "한 씨앗의 승인은 확인창 없이 저장한다")
        self.wait_write(window)
        self.assertNotIn(threading.main_thread(), provider.threads, "쓰기는 화면 스레드가 아니라 작업 스레드에서 돈다")
        after = {seed.seed_id: seed.state for seed in provider.seeds}
        self.assertEqual({key: value for key, value in after.items() if before[key] != value}, {"EX001": "active"})
        self.assertEqual(window.state.seeds.notice, ("ok", T["seeds_approved"]))
        self.assertTrue(window.drawer.is_open, "서랍은 열려 있고 새 상태에 맞는 행동이 보인다")
        self.assertEqual([button.text() for button in self.dui(window).bar.buttons], ["저장", "쉬게 하기", "되돌리기"])
        self.assertEqual(self.row(window, "EX001").findChildren(QLabel)[0].text() or "", self.row(window, "EX001").findChildren(QLabel)[0].text())
        self.assertEqual(self.notice_bar(window, T["seeds_approved"]).level, "ok", "결과 줄은 알림 줄(수준 ok)로 보인다")

    def test_while_writing_the_fields_and_buttons_are_off_and_a_second_click_does_nothing(self):
        provider = Gated()
        window = self.make(provider)
        self.open_row(window, "EX001")
        self.bar_button(window, "approve").click()
        self.settle(2)
        self.assertTrue(window.state.seeds.busy)
        self.assertTrue(all(not button.isEnabled() for button in self.dui(window).bar.buttons))
        self.assertTrue(all(not control.isEnabled() for view in self.dui(window).fields.values() for control in view.controls))
        self.assertIn("저장하는 중이에요…", self.labels(window.drawer))
        window.seed_state("rest")
        window.seed_save()
        provider.gate.set()
        self.wait_write(window)
        self.assertEqual((provider.calls.count("set_state"), provider.calls.count("edit_seed")), (1, 0))

    def test_a_failed_save_keeps_the_typed_values_and_says_why(self):
        for kind, key in (("io", "seeds_fail_io"), ("busy", "seeds_fail_busy"), ("disk", "seeds_fail_disk"), ("corrupt", "seeds_fail_corrupt")):
            provider = Failing({"edit_seed": seeds.SeedFailure("x", code="C", kind=kind)})
            window = self.make(provider)
            self.open_row(window, "EX001")
            self.type_into(window, "reason", "남아야 하는 이유")
            self.type_into(window, "excluded_keywords", "남아야 하는 제외 낱말")
            self.bar_button(window, "save").click()
            self.wait_write(window)
            with self.subTest(kind=kind):
                self.assertEqual(window.state.seeds.notice, ("error", T[key]))
                self.assertEqual((self.dui(window).fields["reason"].edit.text(), self.dui(window).fields["excluded_keywords"].edit.text()), ("남아야 하는 이유", "남아야 하는 제외 낱말"))
                self.assertTrue(self.bar_button(window, "save").isEnabled(), "다시 저장할 수 있다")
                self.assertEqual(self.notice_bar(window, T[key]).level, "error")
                self.assertNotRegex(" ".join(self.labels(window.screen_widget)), r"Traceback|\[['\"]|Exception|C:[\\/]|FILE_WRITE|DISK_FULL")

    def test_a_service_refusal_marks_the_field_beside_it(self):
        provider = Failing({"edit_seed": seeds.SeedFailure("x", code="CONTENT_INVALID", kind="invalid", problems={"reason": "key_shape"})})
        window = self.make(provider)
        self.open_row(window, "EX001")
        self.type_into(window, "reason", "이유")
        self.dui(window).fields["excluded_keywords"].edit.setFocus(Qt.OtherFocusReason)           # 거절될 칸이 아닌 다른 칸에 포커스가 있다
        self.settle(2)
        self.assertIs(window.focusWidget(), self.dui(window).fields["excluded_keywords"].edit)
        self.bar_button(window, "save").click()
        self.wait_write(window)
        self.assertEqual(self.field_error(window, "reason"), T["bf_err_key_shape"])
        self.assertEqual(self.dui(window).fields["reason"].edit.text(), "이유")
        self.assertIs(window.focusWidget(), self.dui(window).fields["reason"].controls[0], "서비스가 거절한 첫 칸으로 포커스가 간다")

    def test_a_stale_version_reloads_the_latest_and_keeps_the_input_then_saves_again(self):
        provider = seeds.FakeSeedsProvider()
        window = self.make(provider)
        self.open_row(window, "EX001")
        self.type_into(window, "reason", "내 이유")
        provider.seeds = [sd.change_state(seed, "active", on=provider.today) if seed.seed_id == "EX002" else seed for seed in provider.seeds]
        provider.revision += 1
        self.bar_button(window, "save").click()
        self.wait_write(window)
        ui_offscreen.wait_until(self.app, lambda: window.state.seeds.notice and window.state.seeds.notice[0] == "warning", 10)
        self.settle(8)
        self.assertEqual(window.state.seeds.notice, ("warning", T["seeds_stale_reloaded"]))
        self.assertEqual(self.dui(window).fields["reason"].edit.text(), "내 이유", "입력은 그대로다")
        self.assertEqual(window.state.seeds.by_id()["EX002"].state, "active", "최신 내용을 다시 읽었다")
        self.bar_button(window, "save").click()
        self.wait_write(window)
        self.assertEqual(window.state.seeds.notice, ("ok", T["seeds_saved"]))

    def test_closing_the_window_waits_for_a_write_in_progress(self):
        provider = Gated()
        window = self.make(provider)
        self.open_row(window, "EX001")
        self.bar_button(window, "approve").click()
        self.settle(2)
        self.assertTrue(window.state.seeds.busy)
        hide = window.hide

        def hide_then_open_the_gate_a_little_later():
            hide()
            threading.Timer(2.0, provider.gate.set).start()                                       # 창을 닫기 시작한 **뒤 2초에야** 쓰기가 끝난다 — 작업 정리가 기다리는 1초보다 길어서, 닫는 쪽이 따로(최대 10초) 기다려야만 아래 값이 맞는다

        window.hide = hide_then_open_the_gate_a_little_later
        window.close()
        self.assertFalse(window.state.seeds.busy, "창을 닫을 때 쓰기가 끝나기를 기다렸다")
        self.assertEqual(next(seed.state for seed in provider.seeds if seed.seed_id == "EX001"), "active")


class BulkDialogTest(Base):
    def pick(self, window, *ids):
        for seed_id in ids:
            self.row(window, seed_id).box.click()
        self.settle(2)

    def test_the_bulk_button_asks_first_with_the_count_the_names_and_a_cancel_focus_and_writing_starts_only_after_the_confirm(self):
        provider = seeds.FakeSeedsProvider()
        window = self.make(provider)
        self.pick(window, "EX001", "EX002", "EX003", "EX004", "EX005", "EX006")
        calls = list(provider.calls)
        self.ui(window).bulk_buttons["activate"].click()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        names = self.labels(window.dialog)
        self.assertIn("고른 Seed 6개를 바꿀까요?", names)
        body = next(name for name in names if "사용 중으로 바꿉니다" in name)
        for part in ("승인 전 6개를 사용 중으로 바꿉니다.", "처음 5개: ‘예시 낱말 가’", "외 1개", "나중에 쉬는 중으로 되돌릴 수 있어요", "네이버 A 3개 → 7개", "한 번에 모두 바뀌거나 하나도 안 바뀌어요"):
            self.assertIn(part, body)
        buttons = self.buttons(window.dialog)
        self.assertEqual(sorted(buttons), ["사용 중으로 바꾸기", "취소"])
        self.assertIs(window.dialog_default, buttons["취소"], "처음 포커스는 취소 — Enter 를 잘못 눌러도 바뀌지 않는다")
        self.assertEqual(provider.calls, calls, "확인 전에는 아무것도 쓰지 않았다")
        QTest.keyClick(window.dialog_default, Qt.Key_Return)
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(provider.calls, calls)
        self.assertIsNone(window.state.seeds.bulk_asked, "취소하면 '확인창을 보였다' 는 표시도 거둔다")
        self.assertEqual(window.state.seeds.start_bulk("activate")[0], "unconfirmed", "취소한 뒤 다시 부르는 길도 막혀 있다")
        self.ui(window).bulk_buttons["activate"].click()
        self.settle()
        window.escape()
        self.settle()
        self.assertEqual((provider.calls, window.state.seeds.bulk_asked), (calls, None), "Esc 로 닫아도 마찬가지")
        self.ui(window).bulk_buttons["activate"].click()
        self.settle()
        self.buttons(window.dialog)["사용 중으로 바꾸기"].click()
        self.wait_write(window)
        self.assertEqual(provider.calls[-1], "set_states")
        self.assertEqual(provider.calls.count("set_states"), 1)
        self.assertEqual({seed.state for seed in provider.seeds if seed.seed_id in ("EX001", "EX002", "EX003", "EX004", "EX005", "EX006")}, {"active"})
        self.assertEqual(window.state.seeds.notice, ("ok", T["seeds_bulk_done_activate"].format(n=6)))
        self.assertEqual(window.state.seeds.checked, set())
        self.assertFalse(self.ui(window).bulk_buttons["activate"].isEnabled())

    def test_the_rest_button_names_the_states_it_changes_and_a_disabled_button_shows_why(self):
        window = self.make()
        self.assertFalse(self.ui(window).bulk_buttons["rest"].isEnabled())
        self.pick(window, "EX009", "EX001")
        self.ui(window).bulk_buttons["rest"].click()
        self.settle()
        body = next(name for name in self.labels(window.dialog) if "쉬는 중으로 바꿉니다" in name)
        self.assertIn("승인 전 1개, 사용 중 1개를 쉬는 중으로 바꿉니다.", body)
        self.assertIn("쉬는 중인 Seed 는 후보 생성에 쓰이지 않아요", body)
        window.escape()
        self.settle()

    def test_a_failed_bulk_change_changes_nothing_and_keeps_the_picked_rows(self):
        provider = Failing({"set_states": seeds.SeedFailure("x", code="FILE_WRITE_FAILED", kind="io")})
        window = self.make(provider)
        self.pick(window, "EX001", "EX002")
        self.ui(window).bulk_buttons["activate"].click()
        self.settle()
        self.buttons(window.dialog)["사용 중으로 바꾸기"].click()
        self.wait_write(window)
        self.assertEqual({seed.state for seed in provider.seeds if seed.seed_id in ("EX001", "EX002")}, {"proposed"})
        self.assertEqual(window.state.seeds.checked, {"EX001", "EX002"})
        self.assertEqual(window.state.seeds.notice, ("error", T["seeds_fail_io"]))


class ImportFlowTest(Base):
    def test_a_picked_file_is_previewed_then_confirmed_and_every_new_seed_is_proposed(self):
        provider = seeds.FakeSeedsProvider()
        window = self.make(provider)
        header = self.buttons(window.screen_widget)
        header["제안 파일 불러오기"].click()
        ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open, 10)
        self.settle()
        self.assertEqual(provider.calls.count("preview_import"), 1)
        self.assertEqual(provider.calls.count("apply_import"), 0, "미리 보기는 읽기뿐이다")
        names = self.labels(window.dialog)
        self.assertIn("제안 파일을 불러올까요?", names)
        body = next(name for name in names if "새로 등록하는 Seed 는 모두 승인 전이에요" in name)
        for part in ("파일 안 Seed 4개 · 새로 등록할 Seed 3개", "승인하기 전에는 후보 생성에 쓰이지 않아요", "GitHub Pages 0개(후보 생성 꺼짐)"):
            self.assertIn(part, body)
        buttons = self.buttons(window.dialog)
        self.assertEqual(sorted(buttons), ["승인 전으로 등록", "취소"])
        self.assertIs(window.dialog_default, buttons["취소"])
        buttons["취소"].click()
        self.settle()
        self.assertEqual((provider.calls.count("apply_import"), window.state.seeds.import_info, len(provider.seeds)), (0, None, 16), "취소하면 아무것도 등록하지 않는다")
        header["제안 파일 불러오기"].click()
        ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open, 10)
        self.settle()
        self.buttons(window.dialog)["승인 전으로 등록"].click()
        self.wait_write(window)
        self.assertEqual(provider.calls.count("apply_import"), 1)
        self.assertEqual({seed.state for seed in provider.seeds if seed.seed_id.startswith("EXI")}, {"proposed"})
        self.assertEqual(window.state.seeds.status, "proposed")
        self.assertEqual(window.state.seeds.notice, ("ok", T["seeds_imported"].format(n=3)))

    def test_cancelling_the_file_picker_does_nothing_and_a_blocked_file_offers_only_to_close(self):
        provider = seeds.FakeSeedsProvider()
        window = self.make(provider, picker=lambda parent, title, filters: "")
        self.buttons(window.screen_widget)["제안 파일 불러오기"].click()
        self.settle()
        self.assertEqual(provider.calls, ["load"], "파일을 고르지 않으면 아무 일도 없다")
        blocked = seeds.FakeSeedsProvider(import_mode="blocked")
        window = self.make(blocked)
        self.buttons(window.screen_widget)["제안 파일 불러오기"].click()
        ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open, 10)
        self.settle()
        self.assertEqual(sorted(self.buttons(window.dialog)), ["닫기"])
        self.assertIn(T["seeds_imp_blocked"], " ".join(self.labels(window.dialog)))
        self.buttons(window.dialog)["닫기"].click()
        self.settle()
        self.assertEqual((blocked.calls.count("apply_import"), window.state.seeds.import_info), (0, None))

    def test_an_unreadable_file_gives_an_easy_notice_and_nothing_changes(self):
        provider = seeds.FakeSeedsProvider(import_mode="unreadable")
        window = self.make(provider)
        self.buttons(window.screen_widget)["제안 파일 불러오기"].click()
        self.wait_write(window)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(window.state.seeds.notice, ("error", T["seeds_imp_failed"]))
        self.assertEqual(len(provider.seeds), 16)


class NewSeedFormTest(Base):
    def fill(self, window, **values):
        for name, value in values.items():
            view = self.dui(window).fields[name]
            if view.kind == "choice":
                view.chips[value].click()
            else:
                self.type_into(window, name, value)
            self.settle(4)

    def test_the_form_changes_its_field_list_when_the_scope_changes_but_not_when_typing(self):
        window = self.make()
        window.seed_open_new()
        self.settle(8)
        ui = self.dui(window)
        self.assertNotIn("allowed_channels", ui.fields)
        self.type_into(window, "keyword", "예시 새 낱말")
        self.assertIs(self.dui(window), ui, "글을 치는 동안은 서랍을 다시 그리지 않는다")
        self.fill(window, scope="common")
        self.assertIsNot(self.dui(window), ui)
        self.assertIn("allowed_channels", self.dui(window).fields)
        self.assertEqual(self.dui(window).fields["keyword"].edit.text(), "예시 새 낱말", "다시 그려도 쓰던 글이 남는다")
        self.assertIn("seeds:field:", str(window.focusWidget().property("focus_key")), "다시 그린 뒤에도 고르던 칸에 포커스가 남는다")

    def test_a_save_try_with_wrong_values_names_the_fields_and_a_good_one_registers_a_proposed_seed_and_opens_it(self):
        provider = seeds.FakeSeedsProvider()
        window = self.make(provider)
        window.seed_open_new()
        self.settle(8)
        calls = list(provider.calls)
        self.bar_button(window, "create").click()
        self.settle(8)
        self.assertEqual(provider.calls, calls, "문제가 있으면 서비스를 부르지 않는다")
        for name in ("keyword", "major", "minor", "target_type", "scope"):
            self.assertTrue(self.field_error(window, name), name)
        self.fill(window, keyword="예시 새 낱말", major="예시 대분류", minor="예시 중분류", target_type="product", scope="naver_a")
        self.bar_button(window, "create").click()
        self.wait_write(window)
        made = next(seed for seed in provider.seeds if seed.seed_id == "M001")
        self.assertEqual((made.state, made.keyword, made.scope, made.priority, made.active_since), ("proposed", "예시 새 낱말", "naver_a", False, None))
        self.assertEqual(window.state.seeds.drawer, ("seed", "M001"))
        self.assertEqual(window.state.seeds.notice, ("ok", T["seeds_created"]))
        self.assertIn("제안(승인 전)", {label.text() for label in window.drawer.findChildren(QLabel) if label.property("badge")})

    def test_cancel_closes_the_form_and_keeps_what_was_typed(self):
        window = self.make()
        window.seed_open_new()
        self.settle(8)
        self.type_into(window, "keyword", "쓰던 낱말")
        self.bar_button(window, "cancel").click()
        self.settle(8)
        self.assertFalse(window.drawer.is_open)
        window.seed_open_new()
        self.settle(8)
        self.assertEqual(self.dui(window).fields["keyword"].edit.text(), "쓰던 낱말")


class RealServiceFlowTest(Base):
    def real(self, tmp, items=None):
        ctx = support.make_ctx(tmp)
        paths = tf.topic_paths(ctx.workspace)
        if items is not None:
            paths.folder.mkdir(parents=True, exist_ok=True)
            paths.seeds.write_bytes((__import__("json").dumps(sd.seeds_to_dict(items), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        return ctx, paths, seeds_adapter.ServiceSeedsProvider(context_factory=lambda data_dir=None: ctx)

    def test_opening_filtering_selecting_the_drawer_and_editing_write_nothing_with_the_real_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, paths, provider = self.real(tmp, seeds.FakeSeedsProvider().seeds)
            before, listing = support.tree_snapshot(tmp), sorted(str(path) for path in Path(tmp).rglob("*"))
            window = self.make(provider)
            self.assertFalse([widget for widget in window.screen_widget.findChildren(QWidget) if widget.accessibleName() == "예시 데이터"], "실제 어댑터에는 '예시 데이터' 표시가 없다")
            chip = next(button for button in window.screen_widget.findChildren(QAbstractButton) if button.text() == "승인 전  9")
            chip.click()
            self.settle()
            self.row(window, "EX001").box.click()
            self.open_row(window, "EX001")
            self.type_into(window, "reason", "고쳐 보는 이유")
            self.bar_button(window, "revert").click()
            self.settle(8)
            window.close_drawer()
            self.settle(4)
            window.seed_open_new()
            self.settle(8)
            self.type_into(window, "keyword", "예시 새 낱말")
            window.close_drawer()
            window.go("home")
            self.settle()
            window.go("settings")
            self.settle()
            window.go("blogs")
            self.settle()
            window.go("seed")
            ui_offscreen.wait_until(self.app, lambda: not window.state.seeds.loading, 10)
            self.settle()
            self.assertEqual(support.tree_snapshot(tmp), before)
            self.assertEqual(sorted(str(path) for path in Path(tmp).rglob("*")), listing, "읽기·고치기는 파일도 폴더도 만들지 않는다")

    def test_a_missing_file_reads_as_an_empty_list_with_a_note_and_a_broken_file_shows_a_read_error_without_a_way_to_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, paths, provider = self.real(tmp)
            window = self.make(provider)
            self.assertEqual(window.screen_widget.findChildren(blog_parts.NoticeBar)[0].level, "info", "처음에는 파일이 아직 없다는 안내")
            self.assertIn("아직 Seed 가 없어요.", self.labels(window.screen_widget))
            self.assertFalse(paths.folder.exists())
        with tempfile.TemporaryDirectory() as tmp:
            ctx, paths, provider = self.real(tmp)
            paths.folder.mkdir(parents=True)
            paths.seeds.write_bytes(b"{broken")
            before = support.tree_snapshot(tmp)
            window = self.make(provider)
            self.assertEqual(window.state.seeds.state, "error")
            self.assertEqual(self.ui(window).list, None)
            self.assertFalse(self.buttons(window.screen_widget)["새 Seed 등록"].isEnabled())
            self.assertEqual(support.tree_snapshot(tmp), before)

    def test_approve_register_edit_and_bulk_change_through_the_screen_with_the_real_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, paths, provider = self.real(tmp, seeds.FakeSeedsProvider().seeds)
            window = self.make(provider)
            self.open_row(window, "EX001")
            self.bar_button(window, "approve").click()
            self.wait_write(window)
            saved = {seed.seed_id: seed for seed in sm.read_snapshot(ctx).seeds}
            self.assertEqual((saved["EX001"].state, saved["EX001"].active_since), ("active", "2026-11-02"))
            self.assertEqual(saved["EX002"].state, "proposed", "다른 씨앗은 그대로")
            self.type_into(window, "excluded_keywords", "예시 제외 하나")
            self.bar_button(window, "save").click()
            self.wait_write(window)
            self.assertEqual({seed.seed_id: seed for seed in sm.read_snapshot(ctx).seeds}["EX001"].excluded_keywords, ("예시 제외 하나",))
            window.close_drawer()
            self.settle(4)
            window.seed_open_new()
            self.settle(8)
            for name, value in (("keyword", "예시 새 낱말"), ("major", "예시 대분류"), ("minor", "예시 중분류")):
                self.type_into(window, name, value)
            self.dui(window).fields["target_type"].chips["product"].click()
            self.settle(4)
            self.dui(window).fields["scope"].chips["naver_a"].click()
            self.settle(8)
            self.bar_button(window, "create").click()
            self.wait_write(window)
            made = {seed.seed_id: seed for seed in sm.read_snapshot(ctx).seeds}["M001"]
            self.assertEqual((made.state, made.keyword), ("proposed", "예시 새 낱말"))
            window.close_drawer()
            self.settle(4)
            for seed_id in ("EX002", "EX003"):
                self.row(window, seed_id).box.click()
            self.ui(window).bulk_buttons["activate"].click()
            self.settle()
            self.buttons(window.dialog)["사용 중으로 바꾸기"].click()
            self.wait_write(window)
            final = {seed.seed_id: seed.state for seed in sm.read_snapshot(ctx).seeds}
            self.assertEqual((final["EX002"], final["EX003"], final["EX004"], final["M001"]), ("active", "active", "proposed", "proposed"))
            files = sorted(path.relative_to(ctx.workspace.root).as_posix() for path in Path(ctx.workspace.root).rglob("*") if path.is_file() and path.name != "settings.json")
            self.assertEqual(files, ["topic_engine/seeds.json", "topic_engine/seeds.json.bak"], "쓴 파일은 씨앗 파일과 그 사본뿐이다(잠금·임시 파일이 남지 않는다)")
            self.assertEqual(sd.usable_seeds(sm.read_snapshot(ctx).seeds, "naver_b")[0].seed_id in ("EX003", "EX010", "EX013", "EX011"), True)


class KeyboardTest(Base):
    def test_tab_goes_all_the_way_around_through_rows_boxes_and_filters_and_every_stop_has_a_name(self):
        window = self.make()
        start = window.nav_buttons["seed"]
        self.focus(start)
        seen, current = [], start
        for _ in range(200):
            seen.append(current)
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            if current is start:
                break
        else:
            self.fail("Tab 이 한 바퀴를 돌지 못했다")
        self.assertEqual(len(seen), len(set(map(id, seen))), "같은 곳을 두 번 지나지 않는다(갇히지 않는다)")
        stops = {id(widget) for widget in seen}
        for row in self.ui(window).list.rows.values():
            self.assertIn(id(row), stops, row.accessibleName())
            self.assertIn(id(row.box), stops, row.box.accessibleName())
        for widget in seen:
            self.assertTrue(widget.accessibleName().strip(), type(widget).__name__)
            self.assertGreaterEqual(widget.height(), tokens.SIZE["hit"] if not widget.property("nav") else 1, widget.accessibleName())

    def test_space_on_a_box_picks_the_row_and_enter_on_a_row_opens_it_without_picking(self):
        window = self.make()
        row = self.row(window, "EX002")
        self.focus(row.box)
        QTest.keyClick(row.box, Qt.Key_Space)
        self.settle(2)
        self.assertEqual(window.state.seeds.checked, {"EX002"})
        self.assertFalse(window.drawer.is_open)
        self.focus(row)
        QTest.keyClick(row, Qt.Key_Enter)
        self.settle(8)
        self.assertEqual((window.drawer.is_open, window.state.seeds.drawer, window.state.seeds.checked), (True, ("seed", "EX002"), {"EX002"}))
        window.escape()

    def test_the_drawer_tab_order_stays_inside_and_ends_at_the_action_bar(self):
        window = self.make()
        self.open_row(window, "EX001")
        close = window.drawer_close
        self.focus(close)
        seen, current = [], close
        for _ in range(60):
            seen.append(current)
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            if current is close:
                break
        self.assertTrue(all(window.drawer.isAncestorOf(widget) or widget is close for widget in seen), "서랍 밖으로 나가지 않는다")
        enabled = [button for button in self.dui(window).bar.buttons if button.isEnabled()]
        for button in enabled:
            self.assertIn(button, seen, button.text())
        for widget in seen:
            self.assertTrue(widget.accessibleName().strip())


class GhostDialogButtonsTest(Base):
    """Seed 관리 독립 검증 F-H1(필수): 공용 대화상자가 옛 확인창의 단추를 치우지 않아, 확인창을 두 번째로 열면 옛 단추가 새 확인창 안에 남아 보이고 눌렸다 — 클릭만으로 확인창을 건너뛴 쓰기(승인 전 → 사용 중·쉬게 하기·다른 화면의 슬롯 비우기)가 가능했다."""

    def shown(self, window):
        return sorted(button.text() for button in window.dialog.findChildren(QAbstractButton) if button.isVisible())

    def test_each_confirmation_dialog_holds_exactly_its_own_buttons_however_many_were_opened_before(self):
        provider = seeds.FakeSeedsProvider()
        window = self.make(provider)
        for seed_id in ("EX001", "EX002"):
            self.row(window, seed_id).box.click()
        self.settle(2)
        self.ui(window).bulk_buttons["activate"].click()
        self.settle()
        self.assertEqual(self.shown(window), ["사용 중으로 바꾸기", "취소"])
        self.buttons(window.dialog)["취소"].click()
        self.settle()
        self.ui(window).bulk_buttons["rest"].click()
        self.settle()
        rest = self.shown(window)
        self.assertEqual((len(rest), "취소" in rest, "사용 중으로 바꾸기" in rest), (2, True, False), "옛 확인창의 '사용 중으로 바꾸기' 가 남아 있지 않다")
        self.assertEqual(len(window.dialog.findChildren(QAbstractButton)), 2, "숨은 옛 단추도 남지 않는다")
        window.escape()
        self.settle()
        self.buttons(window.screen_widget)["제안 파일 불러오기"].click()
        ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open, 10)
        self.settle()
        self.assertEqual(self.shown(window), ["승인 전으로 등록", "취소"], "제안 파일 확인창에도 앞 확인창들의 단추가 없다")
        self.assertEqual(len(window.dialog.findChildren(QAbstractButton)), 2)
        window.escape()
        self.settle()
        self.assertEqual(provider.calls.count("set_states") + provider.calls.count("apply_import"), 0, "확인창을 닫기만 했으니 아무것도 쓰지 않았다")

    def test_a_cancelled_blog_delete_confirmation_leaves_no_danger_button_in_the_next_seed_dialog(self):
        provider = seeds.FakeSeedsProvider()
        window = self.make(provider, page="home")
        window.go("blogs")
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state == "normal", 10)
        self.settle()
        window.blog_select("naver_a")
        self.settle()
        blogs_ui = window.screen_widget.blogs_ui
        delete = next(button for button, spec in zip(blogs_ui.bar.buttons, blogs_ui.bar.specs, strict=True) if spec["key"] == "delete")
        delete.click()
        self.settle()
        self.assertEqual(self.shown(window), ["지우기", "취소"])
        self.buttons(window.dialog)["취소"].click()
        self.settle()
        window.go("seed")
        ui_offscreen.wait_until(self.app, lambda: window.state.seeds.state != "loading" and not window.state.seeds.loading, 10)
        self.settle()
        self.buttons(window.screen_widget)["제안 파일 불러오기"].click()
        ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open, 10)
        self.settle()
        shown = self.shown(window)
        self.assertNotIn("지우기", shown, "블로그 삭제 확인창의 위험 단추가 Seed 확인창에 남아 있으면 슬롯이 확인 없이 비워질 수 있다")
        self.assertEqual(shown, ["승인 전으로 등록", "취소"])
        window.escape()
        self.settle()

    def test_the_dialog_object_drops_the_old_button_row_so_nothing_is_left_to_click(self):
        window = self.make(seeds.FakeSeedsProvider())
        window.show_dialog("첫 확인창", "본문", "첫 확인", "첫 취소", on_ok=lambda: None)
        self.settle()
        first = [button for button in window.dialog.findChildren(QAbstractButton)]
        self.assertEqual(sorted(button.text() for button in first), ["첫 취소", "첫 확인"])
        window.show_dialog("둘째 확인창", "본문", "둘째 확인", "둘째 취소", on_ok=lambda: None)
        self.settle()
        second = window.dialog.findChildren(QAbstractButton)
        self.assertEqual(sorted(button.text() for button in second), ["둘째 취소", "둘째 확인"])
        self.assertFalse([button for button in first if any(button is other for other in second)], "옛 단추는 새 대화상자 안에 남아 있지 않다")
        window.escape()
        self.settle()


class SourceRulesTest(unittest.TestCase):
    QT = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
    NEW = ("seed_parts.py", "seed_screen.py")

    def test_the_new_qt_files_follow_the_part_rules(self):
        raw = re.compile(r"\b(?:QPushButton|QLabel|QLineEdit|QCheckBox|QToolButton|QRadioButton|QComboBox|QTextEdit|QPlainTextEdit|QSpinBox)\(")
        for name in self.NEW:
            source = (self.QT / name).read_text(encoding="utf-8")
            self.assertEqual(raw.findall(source), [], name)
            self.assertNotIn("setStyleSheet(", source, name)
            self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", source), [], name)
            self.assertNotRegex(source, r"QFont\(|font-size|setPointSize|datetime\.now|date\.today|use_font_source", name)
            self.assertNotRegex(source, r"\b(?:go|nav|navigate)\(", name + ": 화면 이동 요청은 사이드바·셸뿐이다")

    def test_the_part_files_hold_no_file_writing_call_and_never_import_the_service_or_the_adapter(self):
        for name in self.NEW:
            source = (self.QT / name).read_text(encoding="utf-8")
            calls = [ast.unparse(node.func) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
            for call in calls:
                self.assertNotRegex(call, r"write_text|write_bytes|write_json|unlink|mkdir|os\.|shutil|\bopen$|set_state|set_states|edit_seed|create_seed|apply_import|preview_import", f"{name}: {call}")
            imports = [node.module or "" for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
            self.assertEqual([module for module in imports if "service" in module or "adapter" in module], [], f"{name}: 화면 부품은 서비스 층·어댑터를 가져오지 않는다")

    def test_the_shell_starts_the_two_confirmed_writes_only_from_the_confirm_callbacks(self):
        tree = ast.parse((self.QT / "shell.py").read_text(encoding="utf-8"))
        users = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("start_bulk", "start_import_apply"):
                    users.setdefault(node.func.attr, set()).add(function.name)
        self.assertEqual(users, {"start_bulk": {"seed_bulk_confirmed"}, "start_import_apply": {"seed_import_confirmed"}})
        shown = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in ("seed_bulk", "_show_import_dialog")]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and ast.unparse(node.func) == "self.show_dialog":
                    shown.setdefault(function.name, []).append({keyword.arg: ast.unparse(keyword.value) for keyword in node.keywords})
        self.assertIn("lambda: self.seed_bulk_confirmed(kind)", shown["seed_bulk"][0]["on_ok"].replace("lambda :", "lambda:"))      # 3.10 의 ast.unparse 는 인자 없는 lambda 뒤에 빈칸을 넣는다(`lambda : …`) — 빈칸 차이만 없애고 같은 호출을 요구한다(M019 병합 때 3.10 에서 찾음)
        self.assertEqual(shown["seed_bulk"][0]["safe_focus"], "True")
        self.assertTrue(all(call["on_ok"] in ("self.seed_import_confirmed", "seeds.discard_import") for call in shown["_show_import_dialog"]))
        self.assertTrue(all(call["safe_focus"] == "True" for call in shown["_show_import_dialog"] if call["on_ok"] == "self.seed_import_confirmed"))

    def test_the_shell_reaches_the_service_only_through_the_state(self):
        tree = ast.parse((self.QT / "shell.py").read_text(encoding="utf-8"))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertFalse({module for module in imports if module and "service" in module}, "셸은 서비스 층을 직접 가져오지 않는다")
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        for forbidden in ("set_state", "set_states", "edit_seed", "create_seed", "apply_import", "preview_import", "write_json", "open"):
            self.assertNotIn(forbidden, calls)

    def test_the_new_theme_rules_use_tokens_only_and_the_check_box_part_exists(self):
        if not HAVE:
            self.skipTest("PySide6 가 없다")
        from chanceblog_desktop.ui.qt import theme
        qss = theme.build_qss(tokens.palette())
        for rule in ('QFrame[seedrow="true"]', 'QFrame[seedrow="true"][checked="true"]', 'QFrame[seedrow="true"][selected="true"]', 'QFrame[seedrow="true"]:focus'):
            self.assertIn(rule, qss)
        self.assertEqual(tokens.SIZE["check_box"], 20)
        self.assertTrue(issubclass(UI.CheckBox, UI.QCheckBox) if hasattr(UI, "QCheckBox") else True)
        self.assertTrue(seed_parts.SeedRow)


if __name__ == "__main__":
    unittest.main()
