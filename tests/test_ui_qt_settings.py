"""설정 화면(연결 관리, P4a)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 접이식 네 묶음·용도 카드·여섯 상태·키보드·접근 이름·'메뉴 → 화면' 표·읽기 전용·키 값 비노출을 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 사용자의 클립보드·보관소·데이터 폴더는 건드리지 않는다(가짜 공급자·임시 폴더의 가짜 보관소).

지키는 것:
  · 메뉴 설정과 위 막대 설정 아이콘이 같은 새 화면을 열고, 나머지 네 화면은 그대로 같은 자리표시다. 홈은 한 글자도 안 바뀐다(지문은 `test_topic_protect_ui`).
  · 접이식: 머리는 이름 있는 단추(36px 이상)이고 누르기·Enter·Space·칩 누르기로 펴고 접는다 — 접근 이름이 상태를 말하고 다시 그려도 포커스·펼침이 남는다. Tab 한 바퀴에 새 부품이 정거장으로 들어 있다.
  · 가로 스크롤·글자 잘림 없음(모든 필수 크기와 최소 창), 넓으면 두 열·좁으면 한 열, 준비 중 카드는 회색 톤.
  · 읽는 중·빈·오류(다시 시도로 회복)·일부만·오프라인 상태, 예시 표시는 예시 데이터에만, 읽기는 작업 스레드에서 하고 화면 스레드에서 받는다, 슬롯이 깨져도 '읽는 중' 에 멈추지 않는다.
  · 실제 어댑터로 열어도 파일·보관소를 바꾸지 않고, 키 모양 가짜 값이 어떤 글자·툴팁·접근 이름에도 남지 않는다.
"""
import contextlib
import importlib.util
import io
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from chanceblog_desktop.ui import adapters  # noqa: E402  (PySide6 를 모르는 부분 — PySide6 가 없어도 불러온다)
from chanceblog_desktop.ui.core import app_state, jobs, services, text, tokens  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()                       # 창을 띄우지 않는다(offscreen) + 윈도 글꼴 폴더
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QLabel, QLineEdit, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.qt import theme

import service_support as support  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402

GOOGLE_KEY = "AI" + "za" + "SyD4e7Kq9ZmW2xV8bN5tR1cY6uH3jL0pGfA1B"[:35]            # 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)
GITHUB_KEY = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
SIZES = ((1366, 768), (1536, 864), (1280, 720), (1920, 1080), (900, 560))


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
        self.data, self.calls, self.thread = data, 0, None

    def load_connections(self, progress, cancelled):
        self.calls += 1
        self.thread = threading.current_thread()
        return self.data


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

    def make(self, connections=None, size=(1440, 900), settings=True, wait=True):
        """홈 공급자는 가짜(불러오지 않는다) — 설정 공급자만 시험이 고른다. 기본은 예시(`normal`)."""
        window = shell_module.AppShell(services.FakeHomeProvider(), connections=connections or services.FakeConnectionsProvider(), autoload=False)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        if settings:
            window.go("settings")
            if wait:
                self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10))
            self.settle()
        return window

    def open_all(self, window):
        for accordion in window.screen_widget.findChildren(UI.Accordion):
            if not accordion.is_open:
                accordion.flip()
        self.settle()

    def accordions(self, window):
        return {accordion.key: accordion for accordion in window.screen_widget.findChildren(UI.Accordion)}

    def interactive(self, window):
        return [w for w in window.findChildren(QWidget) if w.isVisible() and (isinstance(w, (QAbstractButton, QLineEdit)) or isinstance(w, UI.Pressable) and w.focusPolicy() != Qt.NoFocus)]

    @staticmethod
    def everything(window):
        """창 안의 모든 글자·툴팁·접근 이름(숨겨진 진단 글 포함)."""
        parts = [w.text() for w in window.findChildren(QLabel)] + [w.text() for w in window.findChildren(QAbstractButton)]
        parts += [w.accessibleName() + " " + w.accessibleDescription() + " " + w.toolTip() for w in window.findChildren(QWidget)]
        return " ".join(parts)

    @staticmethod
    def labels(window):
        return [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]


class ShellTest(Base):
    def test_the_menu_opens_the_new_settings_screen_and_the_top_bar_has_no_settings_icon_any_more(self):
        """의도적 갱신(UI-C1a, D-171): 상단 앱 바의 설정 아이콘은 사이드바 '설정' 과 겹쳐 지웠다(운영자 2026-11-06 확인 요청 004) — 옛 시험은 그 아이콘 눌림도 확인했다. 이제는 아이콘이 없다는 것과 사이드바로 여는 것을 본다."""
        window = self.make(settings=False)
        self.assertEqual(window.state.page, "home")
        window.nav_buttons["settings"].click()
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10)
        self.settle()
        self.assertEqual(window.state.page, "settings")
        self.assertTrue(window.nav_buttons["settings"].isChecked())
        self.assertEqual(len(window.screen_widget.findChildren(UI.Accordion)), 4)
        self.assertNotIn(text.T["home_title"], self.labels(window))                                  # (자리표시 화면은 없어졌다 — UI-C1a) 지금은 설정 화면이다
        window.go("home")
        self.assertEqual([b for b in window.findChildren(QAbstractButton) if b.property("focus_key") == "top-settings"], [], "상단 앱 바에는 설정 아이콘이 없다")
        self.assertEqual(window.topbar.findChildren(QAbstractButton), [])
        window.nav_buttons["settings"].click()                                                  # 설정으로 가는 길은 사이드바 하나
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10)
        self.settle()
        self.assertEqual((window.state.page, len(window.screen_widget.findChildren(UI.Accordion))), ("settings", 4))

    def test_the_screen_table_has_one_builder_per_real_menu_and_the_old_placeholder_screens_cannot_be_opened(self):
        """의도적 갱신(UI-C1a, D-172): 옛 시험은 '나머지 넷이 같은 자리표시를 그린다' 를 보았다. 이제 표는 완성된 화면(홈·설정)뿐이고 옛 자리표시 화면 이름을 불러도 열리지 않는다."""
        self.assertEqual(list(S.SCREEN_BUILDERS), [key for key, _label, _icon in app_state.NAV])
        self.assertEqual(list(S.SCREEN_BUILDERS), ["home", "settings"])
        self.assertIsNot(S.SCREEN_BUILDERS["settings"], S.SCREEN_BUILDERS["home"])
        window = self.make(settings=False)
        for key in ("topics", "draft", "history", "blogs"):
            window.go(key)
            self.settle()
            self.assertEqual(window.state.page, "home", key)
            self.assertEqual(window.screen_widget.findChildren(UI.Accordion), [], key)                   # 설정도 아니고 자리표시도 아니다 — 지금 화면은 그대로 홈이다
            self.assertTrue(window.nav_buttons["home"].isChecked(), key)

    def test_the_home_screen_still_builds_the_same_parts(self):
        window = self.make(settings=False)
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        self.settle()
        self.assertEqual((len(window.screen_widget.findChildren(UI.SummaryCard)), len(window.screen_widget.findChildren(UI.TopicRow))), (4, 5))
        sample = next(b for b in window.findChildren(QAbstractButton) if b.accessibleName() == "예시 데이터")
        self.assertEqual(sample.toolTip(), text.T["sample_tip"])                                         # 홈의 예시 설명 그대로(설정만 자기 설명을 쓴다)

    def test_visiting_settings_reads_each_time_and_remembers_which_groups_were_open(self):
        provider = services.FakeConnectionsProvider()
        window = self.make(provider)
        self.assertEqual(provider.calls, 1)
        self.accordions(window)["image"].flip()
        self.assertEqual(window.state.conn_open, {"data", "image"})
        window.go("home")
        window.go("settings")
        ui_offscreen.wait_until(self.app, lambda: provider.calls == 2 and not window.state.conn_loading, 10)
        self.settle()
        self.assertEqual(provider.calls, 2)
        self.assertEqual({key: accordion.is_open for key, accordion in self.accordions(window).items()}, {"data": True, "image": True, "ai": False, "publish": False})
        self.assertEqual(window.state.conn_state, "normal")                                              # 다시 읽는 동안에도 보이던 내용은 그대로였다

    def test_reading_runs_on_a_worker_thread_and_the_result_is_received_on_the_screen_thread(self):
        provider = Static(services.ConnectionsData(purposes=services.sample_connections("normal"), sample=True))
        window = self.make(provider, settings=False)
        seen = []
        original = window._on_conn_loaded
        window.conn_bridge.loaded.disconnect(window._on_conn_loaded)
        window.conn_bridge.loaded.connect(lambda data: (seen.append(threading.current_thread() is threading.main_thread()), original(data)))
        window.go("settings")
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 5)
        self.assertEqual(seen, [True])
        self.assertIsNot(provider.thread, threading.main_thread())
        self.assertEqual(provider.thread.name, "job-" + app_state.CONN_KEY)

    def test_a_crash_in_each_settings_slot_is_caught_and_the_screen_is_never_left_loading(self):
        window = self.make()
        err = io.StringIO()
        for slot, args in ((window._on_conn_loaded, ("이상한 값",)), (window._on_conn_failed, (None,)), (window._on_conn_cancelled, ())):
            with mock.patch.object(window.state, "apply_connections", side_effect=RuntimeError("속 사정")), mock.patch.object(window.state, "apply_conn_failure", side_effect=RuntimeError("속 사정")), \
                    mock.patch.object(window.state, "apply_conn_cancelled", side_effect=RuntimeError("속 사정")), contextlib.redirect_stderr(err):
                slot(*args)
            self.settle()
            self.assertEqual(window.state.conn_state, "error", slot.__name__)
            self.assertEqual(window.state.conn_failure.code, "RuntimeError")
            self.assertNotIn("속 사정", repr(window.state.settings_view()))
            self.assertIn(text.T["conn_error_title"], self.labels(window))                                # 오류 화면이 그려졌다
            window.state.apply_connections(services.FakeConnectionsProvider().load_connections(lambda *a: None, lambda: False))
            window.render()
        self.assertEqual(err.getvalue().count("(RuntimeError)"), 3)                                      # 슬롯마다 원인 한 줄이 표준 오류에 남는다
        self.assertEqual(len(err.getvalue().strip().splitlines()), 3)

    def test_a_result_that_arrives_while_another_page_is_shown_is_kept_without_redrawing_that_page(self):
        provider = Static(services.ConnectionsData(purposes=services.sample_connections("normal"), sample=True))
        window = self.make(provider, settings=False)
        window.go("settings")
        window.go("home")                                                                                 # 읽는 중에 다른 화면(홈)으로 갔다 — 의도적 갱신(UI-C1a): 옛 시험은 자리표시 화면으로 갔다
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 5)
        self.settle()
        self.assertEqual(window.state.page, "home")
        self.assertIn(text.T["home_title"], self.labels(window))
        self.assertEqual(window.state.conn_state, "normal")
        window.go("settings")
        ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 5)
        self.settle()
        self.assertEqual(len(window.screen_widget.findChildren(UI.Accordion)), 4)

    def test_a_second_read_request_while_one_is_running_only_says_so_and_closing_cancels_it(self):
        window = self.make(services.FakeConnectionsProvider(delay=5), settings=False)
        window.go("settings")
        self.assertTrue(window.state.conn_loading)
        self.assertFalse(window.reload_connections())
        self.assertEqual(window.toast.text(), text.T["load_busy"])
        window.close()
        self.assertFalse(window.state.runner.running())


class AccordionTest(Base):
    def test_there_are_four_headers_named_after_the_groups_with_the_summary_and_the_state(self):
        window = self.make()
        names = {key: accordion.toggle.accessibleName() for key, accordion in self.accordions(window).items()}
        self.assertEqual(names, {"data": "데이터, 준비 중 2 · 요청 한도 도달 1 · 연결 확인 필요 1, 펼쳐져 있어요", "image": "이미지, 연결됨 1, 접혀 있어요", "ai": "AI, 준비 중 1, 접혀 있어요",
                                 "publish": "발행·연결, 준비 중 1 · 인증 정보 오류 1, 접혀 있어요"})
        self.assertEqual(list(self.accordions(window)), ["data", "image", "ai", "publish"])
        self.assertEqual([accordion.is_open for accordion in self.accordions(window).values()], [True, False, False, False])         # 문제(한도)가 있는 묶음만 처음부터 펼쳐진다
        for accordion in self.accordions(window).values():
            self.assertEqual(accordion.body.isVisibleTo(window), accordion.is_open)

    def test_a_problem_in_another_group_opens_that_group_first(self):
        data = services.ConnectionsData(purposes=tuple(item for item in services.sample_connections("normal") if item.key != "naver_searchad"), sample=True)
        window = self.make(Static(data))
        self.assertEqual([key for key, accordion in self.accordions(window).items() if accordion.is_open], ["publish"])          # 한도 대신 인증 오류가 남은 발행 묶음

    def test_clicking_the_header_the_chips_enter_and_space_all_open_and_close_it_and_the_screen_is_not_redrawn(self):
        window = self.make()
        page = window.screen_widget
        accordion = self.accordions(window)["image"]
        header = accordion.toggle
        self.assertFalse(accordion.is_open)
        QTest.mouseClick(header, Qt.LeftButton)
        self.assertTrue(accordion.is_open)
        self.assertTrue(accordion.body.isVisibleTo(window))
        self.assertTrue(header.accessibleName().endswith("펼쳐져 있어요"))
        chip = header.findChildren(QLabel)[0]
        spot = chip.mapTo(header, chip.rect().center())
        self.assertIsNone(header.childAt(spot), "칩이 마우스를 받으면 칩을 눌러도 머리가 안 눌린다")
        QTest.mouseClick(header, Qt.LeftButton, Qt.NoModifier, spot)
        self.assertFalse(accordion.is_open)
        self.focus(header)
        QTest.keyClick(header, Qt.Key_Return)
        self.assertTrue(accordion.is_open)
        QTest.keyClick(header, Qt.Key_Space)
        self.assertFalse(accordion.is_open)
        self.assertTrue(header.accessibleName().endswith("접혀 있어요"))
        self.assertIs(window.screen_widget, page)                                                         # 펴고 접기는 다시 그리지 않는다
        self.assertEqual(window.state.conn_open, {"data"})                                                # 기억만 한다(위 네 번 눌러 처음으로 돌아왔다)

    def test_the_open_groups_are_remembered_in_the_state_and_survive_a_redraw(self):
        window = self.make()
        self.accordions(window)["publish"].flip()
        self.accordions(window)["data"].flip()
        self.assertEqual(window.state.conn_open, {"publish"})
        window.render()
        self.settle()
        self.assertEqual({key: accordion.is_open for key, accordion in self.accordions(window).items()}, {"data": False, "image": False, "ai": False, "publish": True})

    def test_the_keyboard_focus_stays_on_the_same_header_after_a_redraw(self):
        window = self.make()
        header = self.accordions(window)["image"].toggle
        self.focus(header)
        window.render()
        self.settle()
        focus = QApplication.focusWidget()
        self.assertIsNotNone(focus)
        self.assertEqual(focus.property("focus_key"), "acc:image")
        self.assertIsNot(focus, header)                                                                   # 새로 만든 같은 머리

    def test_the_header_draws_a_focus_ring_in_the_agreed_color(self):
        window = self.make()
        header = self.accordions(window)["ai"].toggle
        colors = tokens.palette()
        window.setFocus()
        self.settle(2)
        before = header.grab().toImage()
        self.focus(header)
        after = header.grab().toImage()
        self.assertNotEqual(before, after, "포커스가 와도 접이식 머리의 모양이 같다(링 없음)")
        top = lambda image: [image.pixelColor(image.width() // 3, y).name().upper() for y in range(4)]      # noqa: E731
        self.assertIn(colors["border_focus"].upper(), top(after))
        self.assertNotIn(colors["border_focus"].upper(), top(before))

    def test_a_folded_body_hides_its_cards_and_the_header_is_a_normal_button(self):
        window = self.make()
        accordion = self.accordions(window)["ai"]
        self.assertFalse(accordion.body.isVisibleTo(window))
        card = accordion.body.findChildren(QFrame)[0]
        self.assertFalse(card.isVisible())
        self.assertIsInstance(accordion.toggle, QAbstractButton)
        self.assertEqual((accordion.toggle.property("acc"), accordion.toggle.property("expanded")), (True, False))
        self.assertGreaterEqual(accordion.toggle.height(), tokens.SIZE["acc_h"])


class AccessibilityTest(Base):
    def test_every_interactive_part_of_the_settings_screen_has_an_accessible_name_and_a_big_enough_target(self):
        window = self.make()
        self.open_all(window)
        found = self.interactive(window)
        self.assertGreaterEqual(len(found), 9)                                                            # 메뉴 6 + 위 막대 + 예시 표시·새로 읽기·머리 넷·진단 정보
        for widget in found:
            self.assertTrue(widget.accessibleName().strip(), f"접근 이름이 없다: {type(widget).__name__} {getattr(widget, 'text', lambda: '')()!r}")
            if isinstance(widget, QAbstractButton):
                self.assertGreaterEqual(widget.height(), tokens.SIZE["hit"], widget.accessibleName())
                self.assertGreaterEqual(widget.width(), tokens.SIZE["hit"], widget.accessibleName())
                if not widget.text().strip():                                                             # 아이콘만 있는 단추는 툴팁도 같은 말
                    self.assertEqual(widget.toolTip(), widget.accessibleName())
        names = [w.accessibleName() for w in found]
        self.assertIn(text.T["conn_refresh"], names)
        self.assertEqual(len([w for w in found if w.property("acc")]), 4)
        self.assertEqual(ui_offscreen.find_clipping(window), [])

    def test_tab_goes_all_the_way_around_and_the_new_parts_are_stops(self):
        window = self.make()
        start = window.nav_buttons["settings"]
        self.focus(start)
        seen, current = [], start
        for _ in range(60):
            seen.append(current)
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            if current is start:
                break
        else:
            self.fail("Tab 이 한 바퀴를 돌지 못했다")
        names = [w.accessibleName() for w in seen]
        self.assertTrue(all(name.strip() for name in names), names)
        self.assertEqual(len(seen), len(set(map(id, seen))))                                              # 같은 곳을 두 번 지나지 않는다(갇히지 않는다)
        self.assertEqual(sum(1 for w in seen if w.property("acc")), 4)                                    # 접이식 머리 넷이 모두 정거장
        self.assertIn(text.T["conn_refresh"], names)
        self.assertIn(text.T["diag_show"], names)
        self.assertIn("예시 데이터", names)
        self.assertEqual(sum(1 for w in seen if w.property("nav")), 2)                                    # 의도적 갱신(UI-C1a, D-172): 실제 메뉴는 홈·설정 둘뿐(옛 값 6) — '다음 단계' 항목은 정거장이 아니다

    def test_open_groups_add_no_tab_stops_because_the_cards_have_nothing_to_press(self):
        window = self.make()
        before = len(self.interactive(window))
        self.open_all(window)
        self.assertEqual(len(self.interactive(window)), before)                                           # 펼쳐도 눌리는 곳이 늘지 않는다(읽기만 하는 카드)
        card_buttons = [w for w in window.screen_widget.findChildren(QAbstractButton) if not w.property("acc") and w.isVisible()]
        self.assertTrue(all(w.accessibleName() in (text.T["conn_refresh"], text.T["diag_show"], "예시 데이터") for w in card_buttons), [w.accessibleName() for w in card_buttons])

    def test_the_card_groups_have_a_name_a_screen_reader_can_read(self):
        window = self.make()
        self.open_all(window)
        frames = [w for w in window.screen_widget.findChildren(QFrame) if w.property("card") in ("true", "plain", "quiet") and w.accessibleName()]
        self.assertEqual(len(frames), 6)
        self.assertIn("NAVER API HUB 검색어 트렌드, 준비 중, 연결 확인 필요, 예시 데이터", [w.accessibleName() for w in frames])
        self.assertIn("GitHub 저장소, 키 없음, 예시 데이터", [w.accessibleName() for w in frames])


class LayoutTest(Base):
    def test_no_horizontal_scroll_and_no_clipped_text_at_every_required_size_and_the_minimum_window_with_every_group_open(self):
        for scenario in ("normal", "partial"):
            window = self.make(services.FakeConnectionsProvider(scenario), size=SIZES[0])
            self.open_all(window)
            for size in SIZES:
                window.resize(*size)
                self.settle()
                ui_offscreen.wait_until(self.app, lambda w=window: w.scroll.horizontalScrollBar().maximum() == 0, 2)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, (scenario, size))
                self.assertLessEqual(window.screen_widget.width(), window.scroll.viewport().width(), (scenario, size))
                self.assertEqual(ui_offscreen.find_clipping(window), [], (scenario, size))

    def test_every_other_state_and_scenario_fits_the_smallest_and_a_usual_window_too(self):
        for scenario in ("offline", "empty", "not_connected", "auth_error", "rate_limited"):
            for size in (SIZES[0], SIZES[-1]):
                window = self.make(services.FakeConnectionsProvider(scenario), size=size)
                self.open_all(window)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, (scenario, size))
                self.assertEqual(ui_offscreen.find_clipping(window), [], (scenario, size))
                window.close()

    def test_cards_sit_in_two_columns_when_the_window_is_wide_and_in_one_when_it_is_narrow(self):
        window = self.make(size=(1440, 900))
        grid = self.accordions(window)["data"].body
        first, second = grid._widgets[:2]
        self.assertEqual(first.y(), second.y())
        self.assertLess(first.x(), second.x())
        window.resize(*SIZES[-1])
        self.settle()
        ui_offscreen.wait_until(self.app, lambda: first.x() == second.x(), 2)
        self.assertEqual(first.x(), second.x())
        self.assertLess(first.y(), second.y())

    def test_getting_ready_cards_are_gray_and_the_others_are_white_and_the_two_badges_are_two_lines(self):
        window = self.make()
        self.open_all(window)
        frames = {w.accessibleName().split(",")[0]: w for w in window.screen_widget.findChildren(QFrame) if w.property("card") in ("true", "plain", "quiet") and w.accessibleName()}
        self.assertEqual(frames["NAVER API HUB 검색어 트렌드"].property("card"), "quiet")
        self.assertEqual(frames["이미지 공급자"].property("card"), "true")                                  # 예시에서만 호출 코드가 있는 용도
        self.assertEqual(frames["GitHub 저장소"].property("card"), "true")
        card = frames["NAVER API HUB 검색어 트렌드"]
        badges = [w for w in card.findChildren(QLabel) if w.property("badge")]
        self.assertEqual([b.text() for b in badges[:2]], ["준비 중", "연결 확인 필요"])
        self.assertLess(badges[0].mapTo(card, badges[0].rect().topLeft()).y(), badges[1].mapTo(card, badges[1].rect().topLeft()).y())      # 준비 줄이 연결 줄 위에 따로
        self.assertEqual([b.property("badge") for b in badges[:2]], ["muted", "warning"])

    def test_the_widest_header_the_real_table_can_make_does_not_let_the_chips_run_over_the_title_even_in_the_smallest_window(self):
        """실제 서비스 표로 생길 수 있는 가장 긴 머리는 '데이터' 묶음의 칩 셋(준비 중·요청 한도 도달·연결 확인 필요) — 최소 창(900×560)에서도 제목 글자의 끝이 첫 칩보다 왼쪽이다."""
        window = self.make(size=SIZES[-1])
        header = self.accordions(window)["data"].toggle
        chips = header.findChildren(QLabel)
        self.assertEqual(len(chips), 3)
        title_right = 14 + header.iconSize().width() + 8 + header.fontMetrics().horizontalAdvance(header.text())        # 안쪽 여백 + 아이콘 + 간격 + 글자
        first = min(chip.mapTo(header, chip.rect().topLeft()).x() for chip in chips)
        self.assertGreater(first, title_right + 16, (first, title_right))
        self.assertLessEqual(max(chip.mapTo(header, chip.rect().topRight()).x() for chip in chips), header.width())            # 머리 밖으로도 나가지 않는다

    def test_the_header_chips_keep_their_own_tones_and_text(self):
        window = self.make()
        chips = [(b.text(), b.property("badge")) for b in self.accordions(window)["data"].toggle.findChildren(QLabel)]
        self.assertEqual(chips, [("준비 중 2", "muted"), ("요청 한도 도달 1", "warning"), ("연결 확인 필요 1", "warning")])
        publish = [(b.text(), b.property("badge")) for b in self.accordions(window)["publish"].toggle.findChildren(QLabel)]
        self.assertEqual(publish, [("준비 중 1", "muted"), ("인증 정보 오류 1", "danger")])


class StatesTest(Base):
    def test_the_first_read_shows_a_skeleton_with_its_own_name_and_a_disabled_refresh_button_then_the_groups(self):
        window = self.make(services.FakeConnectionsProvider(delay=3), wait=False)                  # 느린 PC·다른 일이 겹쳐도 읽는 중 모습을 볼 시간이 있게 넉넉히
        self.assertEqual(window.state.conn_state, "loading")
        names = [w.accessibleName() for w in window.screen_widget.findChildren(QWidget)]
        self.assertIn(text.T["conn_loading_a11y"], names)
        self.assertNotIn(text.T["loading_a11y"], names)                                                   # 홈의 '후보를 불러오는 중' 이 아니다
        self.assertIn(text.T["conn_loading"], self.labels(window))
        refresh = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["conn_refresh"])
        self.assertFalse(refresh.isEnabled())
        self.assertEqual(window.screen_widget.findChildren(UI.Accordion), [])
        self.assertFalse(any(b.accessibleName() == "예시 데이터" for b in window.findChildren(QAbstractButton)))       # 아직 무엇을 읽는지 모른다
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10))
        self.settle()
        self.assertEqual(len(window.screen_widget.findChildren(UI.Accordion)), 4)
        refresh = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["conn_refresh"])
        self.assertTrue(refresh.isEnabled())

    def test_the_refresh_button_reads_again(self):
        provider = services.FakeConnectionsProvider()
        window = self.make(provider)
        refresh = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["conn_refresh"])
        QTest.mouseClick(refresh, Qt.LeftButton)
        ui_offscreen.wait_until(self.app, lambda: provider.calls == 2 and not window.state.conn_loading, 10)
        self.settle()
        self.assertEqual((provider.calls, window.state.conn_state), (2, "normal"))

    def test_an_error_shows_an_easy_sentence_hides_the_code_in_a_folded_diagnostic_and_retry_recovers(self):
        provider = Flaky(failures=1, code="SAMPLE_DOWN")
        window = self.make(provider)
        self.assertEqual(window.state.conn_state, "error")
        self.assertIn(text.T["conn_error_title"], self.labels(window))
        self.assertIn("연결 설정을 읽는 중 끊겼어요.", self.labels(window))
        diag = window.screen_widget.findChild(UI.Disclosure)
        self.assertFalse(diag.is_open)
        visible = " ".join(label.text() for label in window.screen_widget.findChildren(QLabel) if label.isVisible())
        self.assertNotIn("SAMPLE_DOWN", visible)                                                          # 오류 코드는 접어 둔 진단 정보에만
        diag.flip()
        self.settle()
        self.assertTrue(diag.body.isVisible())
        self.assertIn("code: SAMPLE_DOWN", diag.body.plain_text())
        self.assertRegex(diag.body.plain_text(), r"time: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
        retry = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.text() == text.T["retry"])
        QTest.mouseClick(retry, Qt.LeftButton)
        ui_offscreen.wait_until(self.app, lambda: provider.calls == 2 and not window.state.conn_loading, 10)
        self.settle()
        self.assertEqual((window.state.conn_state, len(window.screen_widget.findChildren(UI.Accordion))), ("normal", 4))
        self.assertIsNone(window.state.conn_failure)

    def test_the_diagnostics_always_come_with_the_line_saying_no_key_and_no_typed_text_is_in_them(self):
        """점검 Q13 — 진단 정보를 펼치기 전에도 그 아래 '키와 입력한 글은 담기지 않아요' 줄이 보인다(오류 상태·고급 영역 둘 다)."""
        self.assertIn("키와 입력한 글은 담기지 않아요", text.T["diag_note"])
        for provider in (Flaky(failures=1, code="SAMPLE_DOWN"), None):
            window = self.make(provider) if provider else self.make()
            notes = [label for label in window.screen_widget.findChildren(UI.Label) if label.plain_text() == text.T["diag_note"]]
            self.assertEqual(len(notes), 1, provider)
            self.assertTrue(notes[0].isVisible())
            window.close()

    def test_an_empty_answer_has_a_next_step_button_that_reads_again(self):
        provider = Static(services.ConnectionsData(purposes=(), sample=True))
        window = self.make(provider)
        self.assertEqual(window.state.conn_state, "empty")
        self.assertIn(text.T["conn_empty_title"], self.labels(window))
        again = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.text() == text.T["conn_empty_btn"])
        QTest.mouseClick(again, Qt.LeftButton)
        ui_offscreen.wait_until(self.app, lambda: provider.calls == 2 and not window.state.conn_loading, 10)
        self.assertEqual(provider.calls, 2)

    def test_partial_and_offline_notes_appear_above_the_groups_and_a_normal_screen_has_none(self):
        banners = {}
        for scenario in ("normal", "partial", "offline"):
            window = self.make(services.FakeConnectionsProvider(scenario))
            banners[scenario] = [frame.accessibleName() for frame in window.screen_widget.findChildren(QFrame) if frame.objectName() == "banner"]
            window.close()
        self.assertEqual(banners, {"normal": [], "partial": [text.T["conn_partial_keystore"], text.T["conn_partial_usage"]], "offline": [text.T["conn_offline"]]})

    def test_the_example_badge_only_appears_for_example_data_and_opens_its_own_explanation(self):
        window = self.make()
        badge = next(b for b in window.findChildren(QAbstractButton) if b.accessibleName() == "예시 데이터")
        self.assertEqual(badge.toolTip(), text.T["conn_sample_tip"])
        QTest.mouseClick(badge, Qt.LeftButton)
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertIn(text.T["conn_sample_dialog_body"], [label.plain_text() for label in window.dialog.findChildren(UI.Label)])
        window.close_dialog()
        self.open_all(window)
        tags = [b for b in window.screen_widget.findChildren(QLabel) if b.property("badge") == "muted" and b.text() == text.T["usage_sample"]]
        self.assertEqual(len(tags), 4)                                                                    # 예시의 사용량 줄마다 꼬리표 — 허브 둘(숫자 줄·작은 글)·검색광고(다시 열리는 때)·이미지
        real = self.make(Static(services.ConnectionsData(purposes=services.sample_connections("normal"), sample=False)))
        self.open_all(real)
        self.assertFalse(any(b.accessibleName() == "예시 데이터" for b in real.findChildren(QAbstractButton)))
        self.assertEqual([b for b in real.screen_widget.findChildren(QLabel) if b.text() == text.T["usage_sample"]], [])
        real.close()

    def test_the_diagnostic_of_a_normal_screen_is_folded_and_holds_no_names_or_values(self):
        window = self.make()
        diag = window.screen_widget.findChild(UI.Disclosure)
        self.assertFalse(diag.is_open)
        self.assertEqual(diag.body.plain_text().splitlines()[1:], ["purposes: 6", "entries: 5", "keystore: ok", "usage: ok"])
        self.assertTrue(diag.body.plain_text().startswith("time: "))
        self.assertNotIn("예시 키", diag.body.plain_text())


class ReadOnlyAndSecretsTest(Base):
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

    def test_opening_the_screen_with_the_real_adapter_changes_no_file_and_no_stored_key(self):
        before, blobs = support.tree_snapshot(self.ctx.workspace.root), dict(self.store._blobs)
        window = self.make(self.provider)
        self.open_all(window)
        window.reload_connections()
        ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 10)
        self.settle()
        self.assertEqual(window.state.conn_state, "normal")
        self.assertEqual(support.tree_snapshot(self.ctx.workspace.root), before)
        self.assertEqual(self.store._blobs, blobs)

    def test_no_key_shaped_value_reaches_any_text_tooltip_or_accessible_name_of_the_real_screen(self):
        window = self.make(self.provider)
        self.open_all(window)
        for flip in window.screen_widget.findChildren(UI.Disclosure):
            flip.flip()
        self.settle()
        shown = self.everything(window)
        self.assertIn("내 키", shown)                                                                      # 이름은 보인다 — 값은 아니다
        for name, secret in (("허브", GOOGLE_KEY), ("이미지", GITHUB_KEY), ("보조", GOOGLE_KEY[::-1])):
            fragments = sorted({secret[i:i + 6] for i in range(len(secret) - 5) if secret[i:i + 6] in shown})
            self.assertEqual(fragments, [], f"{name} 키의 조각이 화면에 보인다")
        self.assertNotIn("****", shown)
        self.assertNotIn("hubclient001", shown)

    def test_the_real_screen_shows_real_values_only_no_example_badge_no_example_tag_and_no_made_up_connected(self):
        window = self.make(self.provider)
        self.open_all(window)
        self.assertFalse(any(b.accessibleName() == "예시 데이터" for b in window.findChildren(QAbstractButton)))
        self.assertEqual([b for b in window.screen_widget.findChildren(QLabel) if b.text() == text.T["usage_sample"]], [])
        shown = self.everything(window)
        self.assertNotIn("연결됨", shown)                                                                  # 호출 코드가 없는 동안 '연결됨' 은 어디에도 없다
        self.assertIn("준비 중", shown)
        self.assertIn("오늘 0 / 100회 · 이번 달 0 / 27,000회", self.labels(window))                                   # 실제 값(아직 한 번도 부르지 않았다) — '오늘 00 / 00회'
        self.assertIn("서비스 콘솔 월 한도 30,000회 · 실패한 호출도 세어요", self.labels(window))
        self.assertIn(text.T["limit_naver_apihub"], self.labels(window))                                    # 한도에 닿으면 어떻게 계속하는지(그림에도 나온다)
        self.assertIn(text.T["limit_desc_naver_apihub"], self.labels(window))
        self.assertNotIn("네이버 검색광고 API", [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)])      # 키 항목이 없는 검색광고는 카드가 없다(§34)
        self.assertNotIn("사용할 수 없습니다", shown)                                                       # 서비스 고정 멈춤 문구는 한도에 닿았을 때만(처음 모습에서는 고장 난 것처럼 읽힌다)
        self.assertEqual(sorted(w.text() for w in window.screen_widget.findChildren(QLabel) if w.property("badge") == "warning")[:1], ["연결 확인 필요"])

    def test_the_real_home_provider_brings_its_own_settings_provider_so_the_entry_point_needs_no_second_argument(self):
        """진입점은 `run(provider)` 하나만 넘긴다 — 홈 공급자(실제 어댑터)가 같은 데이터 폴더를 읽는 설정 공급자를 돌려주고, 설정 화면이 그것으로 연다."""
        home = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: self.ctx)
        window = shell_module.AppShell(home, autoload=False)
        window.resize(1440, 900)
        window.show()
        self.addCleanup(window.close)
        self.assertIsInstance(window.state.conn_provider, adapters.ServiceConnectionsProvider)
        window.go("settings")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10))
        self.settle()
        self.assertEqual((window.state.conn_state, [entry.name for item in window.state.conn_data.purposes for entry in item.entries]), ("normal", ["내 키", "이미지 키", "보조 키"]))
        self.assertFalse(any(b.accessibleName() == "예시 데이터" for b in window.findChildren(QAbstractButton)))

    def test_the_real_screen_reads_the_store_only_through_the_existence_question(self):
        class Spy(type(self.store)):
            def __init__(self, blobs):
                super().__init__()
                self._blobs, self.gets = dict(blobs), 0

            def get(self, ref):
                self.gets += 1
                raise AssertionError("화면이 키 값을 꺼냈다")

        spy = Spy(self.store._blobs)
        provider = adapters.ServiceConnectionsProvider(context_factory=lambda data_dir=None: self.ctx, keystore=spy)
        window = self.make(provider)
        self.open_all(window)
        self.assertEqual((spy.gets, window.state.conn_state), (0, "normal"))
        self.assertEqual(window.state.conn_data.purposes[0].entries[0].key_found, True)

    def test_a_html_looking_entry_name_is_shown_as_plain_text(self):
        data = services.ConnectionsData(purposes=(services.PurposeInfo("naver_searchad", "네이버 검색광고 API", status="needs_check",
                                                                       entries=(services.EntryInfo("<b>굵게</b>", "active", True),)),), sample=False)
        window = self.make(Static(data))
        self.open_all(window)
        names = [w.text() for w in window.screen_widget.findChildren(UI.ElidedLabel)]
        self.assertEqual(names, ["<b>굵게</b>"])


class ThemeTest(Base):
    def test_the_new_badge_kinds_and_the_header_rule_are_made_of_tokens_and_the_old_rules_are_unchanged(self):
        colors = tokens.palette()
        qss = theme.build_qss(colors)
        for kind, ground, ink in (("warning", "warning_100", "warning_text"), ("danger", "danger_100", "danger_text")):
            self.assertRegex(qss, rf'QLabel\[badge="{kind}"\] \{{[^}}]*background: {re.escape(colors[ground])}[^}}]*color: {re.escape(colors[ink])}', kind)
        self.assertRegex(qss, rf'QPushButton\[acc="true"\] \{{[^}}]*font-size: {tokens.TYPE["h2"].size}px[^}}]*color: {re.escape(colors["text_strong"])}')
        self.assertRegex(qss, rf'QFrame\[card="quiet"\] \{{[^}}]*background: {re.escape(colors["disabled_bg"])}')                                      # 준비 중 카드의 회색 톤
        self.assertRegex(qss, rf'QFrame\[card="plain"\] \{{[^}}]*background: {re.escape(colors["surface_2"])}')                                       # 점검 Q11 — 기존 서랍 카드(plain)의 바탕은 그대로(새 카드 종류가 이것을 바꾸지 않았다)
        for old in ('QLabel[badge="ok"]', 'QLabel[badge="info"]', 'QLabel[badge="muted"]', 'QLabel[badge="a"]', 'QLabel[badge="b"]', 'QPushButton[badge="warning"]', 'QFrame[card="plain"]'):
            self.assertIn(old, qss)
        values = {value.upper() for value in colors.values()}
        for found in set(re.findall(r"#[0-9A-Fa-f]{6}\b", qss)):
            self.assertIn(found.upper(), values, found)

    def test_the_visible_texts_of_the_settings_screen_never_contain_english_codes_internal_ids_or_promises(self):
        window = self.make()
        self.open_all(window)
        for label in window.screen_widget.findChildren(QLabel):
            shown = label.text() if not isinstance(label, UI.Label) else label.plain_text()
            if label.property("mono"):                                                                    # 진단 정보 영역(고정폭)만 영문이 있다
                continue
            self.assertNotRegex(shown, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", shown)
            self.assertNotRegex(shown, r"\b(?:rotation|failover|active|standby|needs_check|not_connected|auth_error|rate_limited|naver_apihub|image_provider)\b", shown)
            for word in text.FORBIDDEN:
                self.assertNotIn(word, shown)

    def test_the_settings_page_has_no_theme_chooser_and_no_pressable_card(self):
        window = self.make()
        self.open_all(window)
        shown = [w.text() for w in window.findChildren(QLabel)] + [w.text() + w.accessibleName() for w in window.findChildren(QAbstractButton)]
        for item in shown:
            self.assertNotRegex(item, r"테마|다크|Dark|Light", item)
        self.assertEqual([w for w in window.screen_widget.findChildren(UI.Pressable)], [])                # 눌러도 아무 일 없는 카드를 만들지 않았다


if __name__ == "__main__":
    unittest.main()
