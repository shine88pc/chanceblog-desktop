"""UI-C1a(틀 Shell)의 Qt 시험 — 창을 띄우지 않고(offscreen) 상단 앱 바(시계·좁은 폭)·사이드바·'다음 단계' 목록·위험 단추/배지 상태 색·Windows 125% 를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 순수 규칙(시계 글·분 경계·좁은 폭 순서·상세 창·버전)은 `test_ui_c1a_core.py` 가 PySide6 없이 지킨다 — 여기서는 **그려진 모습**·배치·키보드·접근 이름을 본다.

지키는 것:
  · 상단 앱 바: 높이 60·잎+ChanceBlog+소개+날짜·시간뿐(단추 0 — 설정 아이콘·검색·알림·사용자·날씨·창 조절 없음)·가짜 시계의 글·분 경계에서만 글자 갱신(한 번 기다리는 타이머)·좁은 폭에서 소개 먼저 숨김→날짜 줄임·겹침 없음.
  · 사이드바: 폭 208·묶음 이름은 실제 메뉴가 있는 묶음에만·실제 Navigation 은 홈·설정뿐·현재 메뉴 색·'다음 단계' 목록(클릭 불가·Tab 제외·55% 섞은 토큰 색·'준비 중' 배지·가리켜도 변화 없음·기본 커서)·
    미완성 화면으로 가는 길 0(소스·실행 모두)·하단은 브랜드와 버전뿐('개발 버전' 표시)·최소 창(900×560)에서 안 넘침.
  · 굳은 배치: 다시 그린 직후·창 크기를 바꾼 뒤 추천 행이 '누르는 칸 최소 높이' 로 눌려 제목이 잘리지 않는다(논리 1280×720 의 서랍 닫기·폭 1040~1100 끌기).
  · 접근성 색 상태: 위험 단추·의미 배지 세 종(추천·가격변화·주의)의 Default·Hover·Pressed·Disabled 색과 대비, Windows 125% 흉내(`QT_SCALE_FACTOR=1.25` 자식 프로세스)에서 글자 잘림 0·누르는 칸 36px 이상.
"""
import ast
import datetime
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from chanceblog_desktop.ui.core import app_state, clock as clock_rules, services, text, tokens, version as version_rules  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.qt import theme
    from chanceblog_desktop.ui.qt.sidebar import SoonItem
    from chanceblog_desktop.ui.qt.topbar import TopBar

COLORS = tokens.palette()
FRIDAY = datetime.datetime(2026, 11, 6, 20, 10, 0)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class QtBase(unittest.TestCase):
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

    def make(self, provider=None, size=(1440, 900), clock=None, **kwargs):
        fake = clock or clock_rules.FixedClock(FRIDAY)
        window = shell_module.AppShell(provider or services.FakeHomeProvider(), autoload=False, clipboard=lambda _t: True, clock=fake, **kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        window.reload()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10))
        self.settle()
        return window

    def bar(self, clock=None, width=1200):
        bar = TopBar(clock or clock_rules.FixedClock(FRIDAY))
        bar.resize(width, tokens.FRAME["app_bar"])
        bar.show()
        self.addCleanup(bar.close)
        self.settle()
        return bar

    def width_for(self, bar, available):
        """바의 남은 폭(`measures()[0]`)이 `available` 이 되는 바 폭."""
        return bar.width() - bar.measures()[0] + available


class TopBarTest(QtBase):
    def test_the_bar_is_60_high_and_holds_only_leaf_name_tagline_and_date_and_no_buttons(self):
        window = self.make()
        bar = window.topbar
        self.assertEqual(bar.height(), tokens.FRAME["app_bar"])
        self.assertEqual(bar.height(), 60)
        self.assertEqual([label.plain_text() for label in (bar.name, bar.tagline)], ["ChanceBlog", "고르고 · 만들고 · 복사하기"])
        self.assertEqual(bar.date_label.plain_text(), "2026년 11월 6일 (금) 20:10")
        self.assertEqual(bar.findChildren(QAbstractButton), [], "상단 앱 바에는 단추가 하나도 없다 — 설정 아이콘·검색·알림·사용자·날씨·창 조절 없음")
        texts = [label.text() for label in bar.findChildren(QLabel)]
        self.assertEqual(sorted(texts), sorted(["ChanceBlog", "고르고 · 만들고 · 복사하기", "2026년 11월 6일 (금) 20:10"]))        # 글은 이 셋뿐(잎 아이콘은 글이 없는 그림 칸)
        self.assertEqual(len(bar.findChildren(theme.IconWidget)), 1)

    def test_the_settings_icon_is_gone_from_the_whole_window_and_the_sidebar_is_the_only_way_to_settings(self):
        window = self.make()
        keys = {widget.property("focus_key") for widget in window.findChildren(QWidget)}
        self.assertNotIn("top-settings", keys)
        self.assertTrue(window.nav_buttons["settings"].isVisible())
        window.nav_buttons["settings"].click()
        self.settle()
        self.assertEqual(window.state.page, "settings")

    def test_name_and_tagline_sizes_are_20_and_13(self):
        bar = self.bar()
        self.assertEqual((bar.name.font().pixelSize(), bar.tagline.font().pixelSize()), (20, 13))
        self.assertEqual(bar.name.property("role"), "h2")

    def test_the_leaf_starts_at_the_left_margin_and_the_date_hugs_its_text_at_the_right_end(self):
        bar = self.bar(width=1200)
        margin = tokens.SPACE["6"]
        self.assertEqual(bar.icon.geometry().left(), margin)                                          # 잎은 왼쪽 여백에서 시작
        self.assertEqual(bar.date_label.geometry().right() + 1, bar.width() - margin)                  # 날짜는 오른쪽 여백 바로 안쪽에서 끝난다
        for label in (bar.name, bar.tagline, bar.date_label):
            self.assertEqual(label.width(), label.sizeHint().width(), label.plain_text())              # 남는 폭은 날짜 앞의 늘어나는 빈 칸이 가져간다 — 글자 칸이 늘어 날짜 글이 가운데로 오지 않는다
        self.assertGreater(bar.date_label.geometry().left() - bar.tagline.geometry().right(), 300)     # 소개와 날짜 사이가 비어 있다

    def test_the_date_is_the_injected_clock_not_the_system_time(self):
        fake = clock_rules.FixedClock(datetime.datetime(2031, 3, 9, 7, 5))                # 2031-03-09 는 일요일 — 실제 오늘과 다른 날
        bar = self.bar(fake)
        self.assertEqual(bar.date_label.plain_text(), "2031년 3월 9일 (일) 07:05")
        self.assertNotEqual(bar.date_label.plain_text(), clock_rules.date_levels(datetime.datetime.now())[0])        # 컴퓨터의 실제 시각이 아니라 넣어 준 시계의 시각

    def test_the_text_changes_only_on_the_minute_boundary_and_only_that_label_is_set(self):
        fake = clock_rules.FixedClock(datetime.datetime(2026, 11, 6, 20, 10, 30, 500000))
        bar = self.bar(fake)
        spy = mock.Mock(wraps=bar.date_label.set_text)
        bar.date_label.set_text = spy
        apply_spy = mock.Mock(wraps=bar._apply)                                            # 같은 분 안에서는 폭을 다시 재지도 않는다(앱을 느리게 하지 않는다)
        bar._apply = apply_spy
        for second, micro in ((31, 0), (45, 250000), (59, 999000)):                        # 같은 분 안에서는 몇 번 깨어나도 글을 다시 쓰지 않는다
            fake.set(datetime.datetime(2026, 11, 6, 20, 10, second, micro))
            bar.tick()
            self.assertEqual(bar.date_label.plain_text(), "2026년 11월 6일 (금) 20:10", (second, micro))
        self.assertEqual((spy.call_count, apply_spy.call_count), (0, 0))
        fake.set(datetime.datetime(2026, 11, 6, 20, 11, 0, 20000))                         # 분이 바뀐 직후
        bar.tick()
        self.assertEqual(bar.date_label.plain_text(), "2026년 11월 6일 (금) 20:11")
        self.assertEqual((spy.call_count, apply_spy.call_count), (1, 1))
        fake.set(datetime.datetime(2026, 11, 6, 23, 59, 59, 900000))                       # 자정을 넘기면 날짜도 바뀐다
        bar.tick()
        fake.set(datetime.datetime(2026, 11, 7, 0, 0, 0, 30000))
        bar.tick()
        self.assertEqual(bar.date_label.plain_text(), "2026년 11월 7일 (토) 00:00")

    def test_the_timer_is_a_single_shot_for_the_next_minute_not_a_seconds_tick(self):
        for second, micro in ((0, 0), (30, 500000), (45, 0), (59, 999000)):
            fake = clock_rules.FixedClock(datetime.datetime(2026, 11, 6, 20, 10, second, micro))
            bar = self.bar(fake)
            self.assertTrue(bar.timer.isSingleShot())
            self.assertTrue(bar.timer.isActive())
            expected = clock_rules.ms_until_next_minute(fake.now()) + clock_rules.TICK_MARGIN_MS
            self.assertEqual(bar.timer.interval(), expected, (second, micro))
            if second <= 45:
                self.assertGreaterEqual(bar.timer.interval(), 14000, "분이 바뀌기 전에는 깨어나지 않는다(초 단위 갱신이 아니다)")

    def test_the_real_timer_fires_at_the_boundary_and_redraws(self):
        fake = clock_rules.FixedClock(datetime.datetime(2026, 11, 6, 20, 10, 59, 980000))      # 다음 분까지 20ms
        bar = self.bar(fake)
        self.assertEqual(bar.date_label.plain_text(), "2026년 11월 6일 (금) 20:10")
        self.assertLess(bar.timer.interval(), 200)
        fake.set(datetime.datetime(2026, 11, 6, 20, 11, 0, 5000))                             # 시계를 분 경계 뒤로 보낸다(스스로 흐르지 않는 가짜 시계)
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: bar.date_label.plain_text().endswith("20:11"), 3), "타이머가 분 경계에서 글자를 바꿨어야 한다")
        self.assertGreater(bar.timer.interval(), 50000, "다시 건 타이머는 다음 분 경계까지 한 번 기다린다")

    def test_the_bar_stays_the_same_widget_across_screens_and_keeps_the_clock_text(self):
        window = self.make()
        bar, text_before = window.topbar, window.topbar.date_label.plain_text()
        window.nav_buttons["settings"].click()
        self.settle()
        self.assertIs(window.topbar, bar)
        self.assertEqual(window.topbar.date_label.plain_text(), text_before)
        self.assertTrue(bar.isVisible())

    def test_screen_readers_always_get_the_full_date_and_the_bar_has_a_name(self):
        bar = self.bar()
        self.assertEqual(bar.date_label.accessibleName(), "현재 날짜와 시간 2026년 11월 6일 (금) 20:10")
        self.assertEqual(bar.accessibleName(), text.T["topbar_a11y"])

    def test_the_shell_gets_the_clock_and_uses_it_for_the_diagnostic_time_too(self):
        fake = clock_rules.FixedClock(datetime.datetime(2031, 3, 9, 7, 5, 9))
        window = self.make(clock=fake)
        self.assertIs(window.clock, fake)
        window.state.apply_failure(services.ServiceFailure("연결이 끊겼어요.", code="X_Y"), window.clock.now())
        self.assertEqual(window.state.failed_at, datetime.datetime(2031, 3, 9, 7, 5, 9))

    def test_without_a_clock_the_shell_uses_the_system_clock(self):
        window = shell_module.AppShell(services.FakeHomeProvider(), autoload=False, clipboard=lambda _t: True)
        self.addCleanup(window.close)
        self.assertIsInstance(window.clock, clock_rules.SystemClock)


class TopBarNarrowTest(QtBase):
    def test_everything_shows_when_there_is_room(self):
        bar = self.bar(width=1200)
        self.assertTrue(bar.tagline.isVisible())
        self.assertEqual(bar.plan, clock_rules.TopbarPlan(True, 0))
        self.assertEqual(bar.date_label.toolTip(), "")

    def test_the_tagline_hides_first_and_only_then_the_date_gets_shorter(self):
        bar = self.bar(width=1200)
        _available, tagline, dates, gap = bar.measures()
        steps = ((tagline + gap + dates[0], True, 0), (tagline + gap + dates[0] - 1, False, 0), (dates[0], False, 0), (dates[0] - 1, False, 1), (dates[1], False, 1), (dates[1] - 1, False, 2))
        for available, shown, level in steps:
            bar.resize(self.width_for(bar, available), tokens.FRAME["app_bar"])
            self.settle(3)
            self.assertEqual((bar.tagline.isVisible(), bar.plan.level), (shown, level), available)
            self.assertEqual(bar.date_label.plain_text(), bar.levels[level], available)
            self.assertEqual(bar.date_label.toolTip(), bar.levels[0] if level else "", "줄여 보일 때는 전체 날짜가 말풍선으로 나온다")
            self.assertEqual(bar.date_label.accessibleName(), text.T["clock_a11y"].format(text=bar.levels[0]), "화면 읽기 프로그램에는 늘 전체 날짜")

    def test_the_measured_room_matches_the_real_room_between_the_tagline_and_the_date(self):
        bar = self.bar(width=1200)
        available, tagline, dates, gap = bar.measures()
        real_free = bar.date_label.geometry().left() - (bar.tagline.geometry().right() + 1) - 2 * gap      # 소개와 날짜 사이 '늘어나는 빈 칸' 의 실제 폭(양쪽 간격을 뺀 것)
        planned_free = available - tagline - gap - dates[0]                                                  # 판단에 쓴 남은 폭에서 소개·간격·날짜를 뺀 값
        self.assertLessEqual(abs(real_free - planned_free), 6, (real_free, planned_free))                  # 간격 개수(3개)를 잘못 세면 간격(12px)만큼 벗어난다 — 그 어긋남이 경계 판단을 12px 밀어 낸다

    def test_the_three_date_levels_are_the_documented_ones_and_nothing_overlaps_at_any_step(self):
        bar = self.bar(width=1200)
        self.assertEqual(bar.levels, ("2026년 11월 6일 (금) 20:10", "11월 6일 (금) 20:10", "11/6 20:10"))
        _available, tagline, dates, gap = bar.measures()
        for available in range(tagline + gap + dates[0] + 20, dates[2] - 1, -7):
            bar.resize(self.width_for(bar, available), tokens.FRAME["app_bar"])
            self.settle(2)
            date_box = bar.date_label.geometry()
            self.assertLessEqual(date_box.right(), bar.width() - tokens.SPACE["6"] + 1, available)         # 오른쪽 여백 안에
            self.assertGreaterEqual(date_box.width(), bar.date_label.fontMetrics().horizontalAdvance(bar.date_label.plain_text()), "날짜 글자가 칸보다 길지 않다(잘림 없음)")
            if bar.tagline.isVisible():
                self.assertLess(bar.tagline.geometry().right(), date_box.left(), available)                  # 소개 문구와 날짜가 겹치지 않는다
            self.assertLess(bar.name.geometry().right(), date_box.left(), available)

    def test_the_shortest_level_is_kept_even_when_nothing_fits(self):
        bar = self.bar(width=1200)
        bar.setMinimumWidth(0)                                                            # 레이아웃의 최소 폭보다 좁게 줄여 본다(실제 창은 최소 900 이라 여기까지 오지 않는다)
        bar.resize(120, tokens.FRAME["app_bar"])
        self.settle(3)
        self.assertEqual((bar.tagline.isVisible(), bar.plan.level), (False, 2))
        self.assertEqual(bar.date_label.plain_text(), "11/6 20:10")

    def test_the_minimum_window_shows_everything_and_a_roomy_one_too(self):
        for size in ((900, 560), (1180, 720), (1366, 768), (1536, 864), (1920, 1080)):
            window = self.make(size=size)
            self.assertTrue(window.topbar.tagline.isVisible(), size)
            self.assertEqual(window.topbar.plan.level, 0, size)
            self.assertLess(window.topbar.name.geometry().right(), window.topbar.tagline.geometry().left(), size)
            self.assertLess(window.topbar.tagline.geometry().right(), window.topbar.date_label.geometry().left(), size)


QT_DIR = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
REAL = {"home", "settings"}


def hexed(image, x, y):
    return image.pixelColor(int(x), int(y)).name().upper()


def count_color(image, color, tolerance=0):
    target = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    found = 0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() > 200 and all(abs(a - b) <= tolerance for a, b in zip((pixel.red(), pixel.green(), pixel.blue()), target, strict=True)):
                found += 1
    return found


class SidebarTest(QtBase):
    def test_the_sidebar_is_208_wide_inside_184_to_208_with_the_document_background_and_right_line(self):
        window = self.make()
        side = window.sidebar
        self.assertEqual(side.width(), tokens.FRAME["sidebar"])
        self.assertEqual(side.width(), 208)                                                        # 범위의 끝 — 1366×768/100% 의 홈 모양을 그대로 두려는 값(D-172)
        self.assertTrue(184 <= side.width() <= 208)
        image = window.grab().toImage()
        top = window.topbar.height()
        self.assertEqual(hexed(image, 4, top + 300), COLORS["bg_sidebar"].upper())                  # 사이드바 바탕 #F7F9FC
        self.assertEqual(hexed(image, side.width() - 1, top + 300), COLORS["sidebar_border"].upper())          # 오른쪽 선 #E3E9F2
        self.assertEqual(hexed(image, side.width() + 6, top + 300), COLORS["bg_app"].upper())

    def test_group_names_show_only_for_groups_that_have_a_real_menu(self):
        side = self.make().sidebar
        self.assertEqual(list(side.group_titles), ["core", "system"])
        self.assertEqual([label.plain_text() for label in side.group_titles.values()], ["핵심 작업", "시스템"])
        every_text = {label.plain_text() for label in side.findChildren(UI.Label)}
        self.assertNotIn("데이터·관리", every_text, "실제 메뉴가 없는 묶음은 이름도 보이지 않는다")
        self.assertEqual({label.property("role") for label in side.group_titles.values()}, {"micro"})

    def test_the_real_menu_is_home_and_settings_and_the_current_one_gets_the_new_colors(self):
        window = self.make()
        self.assertEqual(list(window.nav_buttons), ["home", "settings"])
        self.assertEqual([button.accessibleName() for button in window.nav_buttons.values()], ["홈 메뉴로 이동", "설정 메뉴로 이동"])
        for button in window.nav_buttons.values():
            self.assertTrue(42 <= button.height() <= 46, button.height())                          # 문서의 메뉴 높이 42~46
            self.assertEqual(button.cursor().shape(), Qt.PointingHandCursor)
        home = window.nav_buttons["home"]
        self.assertTrue(home.isChecked())
        image = window.grab().toImage()
        spot = home.mapTo(window, QPoint(home.width() - 14, home.height() // 2))
        self.assertEqual(hexed(image, spot.x(), spot.y()), COLORS["nav_current_bg"].upper())      # 현재 메뉴 면 #DCEAFF
        self.assertGreater(count_color(home.grab().toImage(), COLORS["nav_current_text"], 40), 20)    # 글자·아이콘 #1F61BC
        other = window.nav_buttons["settings"]
        spot = other.mapTo(window, QPoint(other.width() - 14, other.height() // 2))
        self.assertEqual(hexed(image, spot.x(), spot.y()), COLORS["bg_sidebar"].upper())          # 현재가 아닌 메뉴는 면이 없다
        window.nav_buttons["settings"].click()
        self.settle()
        self.assertTrue(window.nav_buttons["settings"].isChecked() and not window.nav_buttons["home"].isChecked())

    def test_the_next_steps_list_has_the_five_unfinished_names_with_a_soon_badge_each(self):
        window = self.make()
        box = window.sidebar.soon_list
        self.assertEqual(box.accessibleName(), "준비 중 — 아직 열 수 없는 화면")
        self.assertEqual(box.title.plain_text(), "다음 단계")
        items = box.items
        self.assertEqual([item.name.text() for item in items], ["주제 후보", "초안 작성", "발행 기록", "Seed 관리", "블로그 관리"])
        for item in items:
            self.assertIsInstance(item, SoonItem)
            self.assertEqual(item.badge.text(), "준비 중")                                          # 색만이 아니라 글자
            self.assertEqual(item.badge.property("badge"), "muted")                               # 의미 배지 중 중립 종류
            self.assertEqual(item.accessibleName(), f"{item.name.text()}, 준비 중")
            self.assertTrue(item.badge.isVisible() and item.name.isVisible() and item.icon.isVisible())
            self.assertEqual(item.minimumHeight(), tokens.SIZE["hit_min"])                          # 줄 높이는 32 아래로 줄지 않는다(누르는 칸이 아니라 읽기 편한 줄 높이 — 최소 창 안에 사이드바가 들어가는 값)
            self.assertGreaterEqual(item.height(), tokens.SIZE["hit_min"], item.name.text())
        self.assertGreater(box.geometry().top(), window.nav_buttons["settings"].geometry().bottom() - 1)  # 실제 메뉴 아래에 따로

    def test_the_next_steps_list_cannot_be_clicked_focused_or_tabbed_to_and_nothing_happens(self):
        window = self.make()
        box = window.sidebar.soon_list
        for widget in [box, *box.findChildren(QWidget)]:
            self.assertEqual(widget.focusPolicy(), Qt.NoFocus, widget)                            # Tab 정거장이 아니다
            self.assertNotIsInstance(widget, QAbstractButton)                                     # 단추가 하나도 없다
        calls = []
        real_nav = window.state.nav
        window.state.nav = lambda key: (calls.append(key), real_nav(key))[1]
        before_screen = window.screen_widget
        for item in box.items:
            for target in (item, item.name, item.badge, item.icon):
                QTest.mouseClick(target, Qt.LeftButton)
                QTest.mouseDClick(target, Qt.LeftButton)
            QTest.keyClick(item, Qt.Key_Return)
            QTest.keyClick(item, Qt.Key_Space)
        self.settle()
        self.assertEqual(calls, [], "눌러도 화면 이동 요청이 한 번도 없다")
        self.assertEqual((window.state.page, window.toast.isVisible(), window.screen_widget is before_screen), ("home", False, True))
        window.activateWindow()                                                                   # Tab 으로 한 바퀴 — 어느 정거장도 '다음 단계' 목록 안에 없다
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)
        window.nav_buttons["home"].setFocus(Qt.TabFocusReason)
        self.settle(2)
        seen = []
        for _ in range(60):
            QTest.keyClick(QApplication.focusWidget() or window, Qt.Key_Tab)
            self.settle(1)
            focus = QApplication.focusWidget()
            seen.append(focus)
            self.assertFalse(focus is box or (focus is not None and box.isAncestorOf(focus)), "Tab 이 '다음 단계' 항목에 닿았다")
            if focus is window.nav_buttons["home"]:
                break
        self.assertIn(window.nav_buttons["settings"], seen, "실제 메뉴(설정)에는 Tab 이 간다")

    def test_hovering_the_next_steps_changes_nothing_and_the_cursor_stays_an_arrow(self):
        window = self.make()
        item = window.sidebar.soon_list.items[0]
        before = item.grab().toImage()
        QTest.mouseMove(item, QPoint(item.width() // 2, item.height() // 2))
        self.settle(3)
        self.assertTrue(before == item.grab().toImage(), "가리켜도 모양이 바뀌지 않는다")
        for widget in (item, item.name, item.badge, item.icon):
            self.assertEqual(widget.cursor().shape(), Qt.ArrowCursor)
        self.assertEqual(item.name.toolTip(), "")
        qss = theme.build_qss(COLORS)
        self.assertNotRegex(qss, r"soonitem[^{]*:hover|navsoon[^{]*:hover|QLabel\[soon[^{]*:hover")        # 가리킬 때 모양을 바꾸는 규칙이 없다

    def test_the_faded_color_is_a_token_mix_of_55_percent_and_no_opacity_effect_is_used(self):
        mixed = tokens.mix(COLORS["bg_sidebar"], COLORS["text_secondary"], 0.55)
        self.assertEqual(COLORS["soon_text"], mixed)                                              # 토큰 값이 55% 섞은 값과 같다(입력 색이나 비율이 바뀌면 이 시험이 알린다)
        self.assertTrue(0.50 <= tokens.SOON_OPACITY <= 0.60)
        window = self.make()
        for item in window.sidebar.soon_list.items:
            self.assertEqual(item.name.palette().color(item.name.foregroundRole()).name().upper(), mixed.upper(), "이름 글자 색 = 55% 섞은 토큰 색")
            for widget in (item, item.name, item.icon):
                self.assertIsNone(widget.graphicsEffect(), "투명 효과(QGraphicsOpacityEffect)를 쓰지 않는다")
        code = "\n".join(line for line in (QT_DIR / "sidebar.py").read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith(("#", '"""')))
        self.assertNotRegex(code, r"QGraphicsOpacityEffect\(|setGraphicsEffect|setWindowOpacity|setOpacity")
        icon_image = window.sidebar.soon_list.items[0].icon.grab().toImage()
        self.assertGreater(count_color(icon_image, mixed, 30), 5, "아이콘도 같은 색으로 그려진다")

    def test_the_bottom_shows_only_the_brand_and_the_version_and_no_channel_shortcuts(self):
        window = self.make()
        side = window.sidebar
        texts = [label.plain_text() for label in side.findChildren(UI.Label)]
        self.assertIn("ChanceBlog Desktop", texts)
        self.assertIn(window.version_info.text, texts)
        self.assertNotIn(text.T["brand_line"], texts, "한 줄 소개는 상단 앱 바로 갔다")
        self.assertEqual(side.findChild(QLabel, "brandversion").text(), window.version_info.text)
        joined = " ".join(texts)
        for word in ("채널", "Naver", "Blogger", "GitHub", "네이버"):
            self.assertNotIn(word, joined, "채널 바로가기는 표시하지 않는다")

    def test_the_version_label_shows_v_number_or_the_dev_label(self):
        window = self.make()
        raw = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(window.sidebar.findChild(QLabel, "brandversion").text(), "v" + raw)
        dev = self.make(version_info=version_rules.VersionInfo("개발 버전", "dev"))
        self.assertEqual(dev.sidebar.findChild(QLabel, "brandversion").text(), "개발 버전")

    def test_everything_fits_inside_the_sidebar_at_the_minimum_window_and_the_window_minimum_is_unchanged(self):
        window = self.make(size=(900, 560))
        self.assertEqual((window.minimumSize().width(), window.minimumSize().height()), (900, 560))
        side = window.sidebar
        self.assertLessEqual(side.minimumSizeHint().height(), 560 - tokens.FRAME["app_bar"])
        box, brand = side.soon_list, side.findChild(QWidget, "brandcard")
        self.assertLess(window.nav_buttons["settings"].geometry().bottom(), box.geometry().top())
        previous = -1
        for item in box.items:
            geometry = item.geometry()
            self.assertGreater(geometry.top(), previous)                                           # 항목끼리 겹치지 않는다
            previous = geometry.bottom()
            self.assertLessEqual(box.geometry().top() + geometry.bottom(), brand.geometry().top(), "항목이 아래 브랜드 카드와 겹치지 않는다")
            self.assertGreaterEqual(item.name.width(), item.name.fontMetrics().horizontalAdvance(item.name.text()), "이름이 잘리지 않는다")
        self.assertLessEqual(brand.geometry().bottom(), side.height())


class NoRouteToUnfinishedScreensTest(QtBase):
    def test_in_the_source_the_only_place_that_asks_for_a_screen_is_the_sidebar_and_only_real_ones(self):
        """화면 이동을 요청하는 호출(`go`·`nav`·`navigate`)을 소스(`ast`)에서 훑는다 — 화면·부품에는 하나도 없고, 사이드바는 실제 메뉴 열쇠(변수)로만 요청한다."""
        found = {}
        for path in sorted(QT_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                    if name in ("go", "nav", "navigate"):
                        found.setdefault(path.name, []).append(ast.unparse(node))
        self.assertEqual(sorted(found), ["shell.py", "sidebar.py"], found)
        self.assertEqual(found["sidebar.py"], ["navigate(k)"], "사이드바는 실제 메뉴의 열쇠로만 화면을 요청한다")
        self.assertEqual(found["shell.py"], ["self.state.nav(key)"], "셸의 `go` 가 상태의 `nav` 를 부르는 한 곳뿐")

    def test_every_button_and_card_on_both_real_screens_never_asks_for_an_unfinished_screen(self):
        window = self.make()
        requested = []
        real_nav = window.state.nav
        window.state.nav = lambda key: (requested.append(key), real_nav(key))[1]

        def pressables():
            return [w for w in window.findChildren(QWidget) if w.isVisible() and (isinstance(w, QAbstractButton) or isinstance(w, UI.Pressable)) and not window.sidebar.isAncestorOf(w)]

        pressed = 0
        for screen in ("home", "settings"):
            if window.state.page != screen:
                window.go(screen)
                ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 10)
                self.settle()
            names = [widget.accessibleName() or widget.text() for widget in pressables()]
            self.assertGreater(len(names), 4, screen)
            for name in names:
                current = next((w for w in pressables() if (w.accessibleName() or w.text()) == name), None)
                if current is None:
                    continue
                if isinstance(current, QAbstractButton):
                    if not current.isEnabled():
                        continue
                    current.click()
                elif current.focusPolicy() != Qt.NoFocus:
                    current.activated.emit()
                else:
                    continue
                pressed += 1
                self.settle(2)
                window.escape()
                window.escape()
                window.state.runner.cancel_all()
                self.settle(2)
                if window.state.page != screen:
                    window.go(screen)
                    self.settle(2)
        self.assertGreater(pressed, 10)
        self.assertEqual([key for key in requested if key not in REAL], [], "어느 단추·카드를 눌러도 미완성 화면을 요청하지 않는다")

    def test_asking_for_any_unfinished_screen_by_name_is_refused_by_the_shell_and_the_state(self):
        window = self.make()
        before = window.screen_widget
        for key, _label, _icon in app_state.NEXT_STEPS:
            self.assertFalse(window.state.nav(key), key)
            window.go(key)
        self.assertEqual((window.state.page, window.screen_widget is before), ("home", True))
        self.assertEqual({menu for _key, _label, menus in app_state.NAV_GROUPS for menu in menus}, REAL)


class ColorStatesTest(QtBase):
    """위험 단추와 의미 배지 세 종(추천·가격변화·주의)의 **Default·Hover·Pressed·Disabled** 상태 — 실제로 그려진 픽셀의 배경색·글자색과 대비. 값은 손으로 적은 운영자 결정 값이다.
    꺼짐은 대비(4.5) 제외 항목이라 색 값과 '글자가 바탕과 구별됨'(1.5 이상)만 본다."""
    DANGER = {"default": ("#CE4646", "#FFFFFF"), "hover": ("#BA4247", "#FFFFFF"), "pressed": ("#BA4247", "#FFFFFF"), "disabled": ("#C5D0E0", "#FFFFFF")}
    BADGES = {"recommend": ("#FFF0CA", "#9D5F07", "추천"), "price_change": ("#E8F7DF", "#437B28", "가격변화"), "caution": ("#FFF2D6", "#9F6003", "주의")}

    def host(self, widget, width=None):
        box = QWidget()
        from PySide6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(widget)
        if width:
            box.setFixedWidth(width)
        box.show()
        self.addCleanup(box.close)
        self.settle()
        return box

    def hover(self, widget):
        QTest.mouseMove(widget, QPoint(widget.width() // 2, widget.height() // 2))
        self.settle(3)
        if not widget.underMouse():                                                      # 화면 없는 환경에서 진짜 가리킴이 안 만들어지면 가리킴 상태만 직접 만든다(스타일은 이 속성으로 판단한다)
            widget.setAttribute(Qt.WA_UnderMouse, True)
            widget.update()
            self.settle(3)

    def unhover(self, widget):
        widget.setAttribute(Qt.WA_UnderMouse, False)
        QTest.mouseMove(widget.window(), QPoint(2, 2))
        self.settle(3)

    def test_the_danger_button_in_all_four_states_has_the_decided_colors_and_readable_text(self):
        button = UI.Button("danger", "위험 단추")
        self.host(button)
        button.clearFocus()
        self.settle(2)
        seen = {}

        def sample(state):
            image = button.grab().toImage()
            seen[state] = (hexed(image, 8, image.height() // 2), image)

        sample("default")
        self.hover(button)
        sample("hover")
        self.unhover(button)
        button.setDown(True)
        self.settle(2)
        sample("pressed")
        button.setDown(False)
        button.setEnabled(False)
        self.settle(2)
        sample("disabled")
        for state, (bg, fg) in self.DANGER.items():
            found_bg, image = seen[state]
            self.assertEqual(found_bg, bg, state)                                            # 배경
            self.assertGreater(count_color(image, fg, 12), 8, f"{state}: 글자가 흰색이어야 한다")      # 글자
            ratio = tokens.contrast(fg, found_bg)
            if state == "disabled":
                self.assertGreaterEqual(ratio, 1.5, "꺼진 단추도 글자가 바탕과 구별된다(대비 제외 항목)")
                self.assertLess(ratio, 4.5)
            else:
                self.assertGreaterEqual(ratio, 4.5, state)
        self.assertEqual(round(tokens.contrast("#FFFFFF", "#CE4646"), 2), 4.58)
        self.assertEqual(button.minimumHeight(), tokens.SIZE["control"])

    def test_the_danger_stylesheet_rules_carry_exactly_those_colors(self):
        qss = theme.build_qss(COLORS)
        self.assertRegex(qss, r'QPushButton\[kind="danger"\] \{ background: #CE4646; color: #FFFFFF; border: 1px solid #CE4646;')
        self.assertRegex(qss, r'QPushButton\[kind="danger"\]:hover, QPushButton\[kind="danger"\]:pressed \{ background: #BA4247; border-color: #BA4247; \}')
        self.assertRegex(qss, r'QPushButton\[kind="primary"\]:disabled, QPushButton\[kind="danger"\]:disabled \{ background: #C5D0E0; border-color: #C5D0E0; color: #FFFFFF; \}')
        self.assertNotIn("#D94A4A", qss.replace('QPushButton[kind="danger_ghost"]', "").split('QPushButton[kind="danger"] {')[1].split("\n")[0], "위험 단추 규칙에 옛 채움 색이 없다")

    def test_the_three_changed_badges_keep_their_pair_in_all_four_states(self):
        for kind, (bg, fg, name) in self.BADGES.items():
            badge = UI.SemanticBadge(kind)
            self.host(badge)
            self.assertEqual(badge.text(), name)
            results = {}

            def sample(state, badge=badge, results=results, fg=fg):
                image = badge.grab().toImage()
                results[state] = (hexed(image, 10, image.height() // 2), count_color(image, fg, 60), image)

            sample("default")
            self.hover(badge)
            sample("hover")
            self.unhover(badge)
            QTest.mousePress(badge, Qt.LeftButton)
            self.settle(2)
            sample("pressed")
            QTest.mouseRelease(badge, Qt.LeftButton)
            badge.setEnabled(False)
            self.settle(2)
            sample("disabled")
            for state, (found_bg, dots, _image) in results.items():
                self.assertEqual(found_bg, bg, f"{kind} {state} 배경")
                self.assertGreater(dots, 8, f"{kind} {state}: 글자 색 점이 있어야 한다")
                self.assertGreaterEqual(tokens.contrast(fg, found_bg), 4.5, f"{kind} {state}")       # 꺼진 모습도 같은 쌍 — 4.5 이상 그대로
            self.assertEqual(badge.accessibleName(), name)
            self.assertEqual(badge.height(), tokens.SIZE["badge_h"])

    def test_the_badge_stylesheet_rules_carry_the_decided_pairs(self):
        qss = theme.build_qss(COLORS)
        for kind, (bg, fg, _name) in self.BADGES.items():
            self.assertIn(f'QLabel[semantic="{kind}"] {{ background: {bg}; color: {fg}; }}', qss)

    def test_the_old_document_values_are_nowhere_in_the_stylesheet(self):
        qss = theme.build_qss(COLORS).upper()
        for old in ("#B36A00", "#478327", "#A86500"):
            self.assertNotIn(old, qss)


class ScaleStatesTest(unittest.TestCase):
    """Windows 125% 흉내(`QT_SCALE_FACTOR=1.25`, 자식 프로세스 — 앱 코드에는 없다) — 위험 단추·배지 세 종·사이드바·상단 앱 바가 배율에서도 글자 잘림 0이고 누르는 칸이 36px 이상이다.
    실제 윈도 125% 의 글꼴 힌팅·DPI 반올림은 이 흉내와 다르다(운영자 PC 확인으로 남음)."""
    PROBE = r"""
import json, sys, datetime
sys.path.insert(0, sys.argv[1] + "/src"); sys.path.insert(0, sys.argv[1] + "/scripts")
import ui_offscreen
ui_offscreen.prepare_environment()
from PySide6.QtWidgets import QAbstractButton, QApplication, QVBoxLayout, QWidget
from chanceblog_desktop.ui.core import clock, services
from chanceblog_desktop.ui.qt import app as qapp, components as UI, shell as shell_module
ui_offscreen.install_system_fonts()
app = qapp.make_app()
out = {"scale": float(__import__("os").environ.get("QT_SCALE_FACTOR", "1"))}
box = QWidget(); lay = QVBoxLayout(box)
parts = [UI.Button("danger", "위험 단추"), UI.Button("danger_ghost", "제외하기"), UI.SemanticBadge("recommend"), UI.SemanticBadge("price_change"), UI.SemanticBadge("caution")]
for p in parts: lay.addWidget(p)
box.show(); ui_offscreen.settle(app, 6)
def clipped(widget, text=None):
    text = text if text is not None else widget.text()
    return widget.width() < widget.fontMetrics().horizontalAdvance(text) - 1
out["parts"] = {"clipped": [p.text() for p in parts if clipped(p)], "button_height": parts[0].height(), "ghost_height": parts[1].height(), "badge_heights": [p.height() for p in parts[2:]]}
window = shell_module.AppShell(services.FakeHomeProvider(), autoload=False, clipboard=lambda t: True, clock=clock.FixedClock(datetime.datetime(2026, 11, 6, 20, 10)))
window.resize(1536, 864); window.show(); window.reload()
ui_offscreen.wait_until(app, lambda: window.state.list_state != "loading", 10); ui_offscreen.settle(app, 6)
bar, side = window.topbar, window.sidebar
bad = []
for label in (bar.name, bar.tagline, bar.date_label):
    if label.isVisible() and label.width() < label.fontMetrics().horizontalAdvance(label.text()) - 1: bad.append(label.text())
for item in side.soon_list.items:
    if item.name.width() < item.name.fontMetrics().horizontalAdvance(item.name.text()) - 1: bad.append(item.name.text())
    if item.badge.width() < item.badge.fontMetrics().horizontalAdvance(item.badge.text()) - 1: bad.append(item.badge.text())
for button in window.nav_buttons.values():
    if button.height() < 36: bad.append("nav " + button.text())
out["shell"] = {"clipped": bad, "nav_heights": [b.height() for b in window.nav_buttons.values()], "bar_height": bar.height(), "sidebar_width": side.width(), "tagline_visible": bar.tagline.isVisible()}
print(json.dumps(out))
"""

    @unittest.skipUnless(HAVE and __import__("os").name == "nt", "PySide6 와 윈도 글꼴이 있어야 한다")
    def test_at_125_percent_nothing_is_clipped_and_every_target_is_36px_or_more(self):
        import json
        import os
        import subprocess
        done = subprocess.run([sys.executable, "-X", "utf8", "-c", self.PROBE, str(ROOT)], capture_output=True, text=True, encoding="utf-8",
                              env=dict(os.environ, PYTHONUTF8="1", QT_SCALE_FACTOR="1.25", QT_FONT_DPI="120"), timeout=240, creationflags=0x08000000)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        report = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(report["scale"], 1.25)
        self.assertEqual(report["parts"]["clipped"], [])
        self.assertGreaterEqual(report["parts"]["button_height"], 36)
        self.assertGreaterEqual(report["parts"]["ghost_height"], 36)
        self.assertEqual(report["parts"]["badge_heights"], [24, 24, 24])
        self.assertEqual(report["shell"]["clipped"], [])
        self.assertTrue(all(height >= 36 for height in report["shell"]["nav_heights"]), report["shell"])
        self.assertEqual((report["shell"]["bar_height"], report["shell"]["sidebar_width"]), (60, 208))
        self.assertTrue(report["shell"]["tagline_visible"])


class RelayoutTest(QtBase):
    """굳어 버린 배치 — UI-C1a 의 사진 점검(논리 1280×720)에서 서랍을 열었다 닫아 다시 그린 뒤 홈 추천 행이 '누르는 칸 최소 높이'(96)로 눌려 제목이 잘리는 것이 드러났다. 행의 높이는 위쪽 배치에 반영되지 않은 채 굳었고(`row.heightForWidth` 는 110 인데 실제는 96),
    몇 번을 더 기다려도 그대로였다. 같은 일이 옛 코드(UI-C0)에서도 창 폭 1060·1080 으로 끌어 바꿀 때 있었다. 다시 그린 직후와 창 크기를 바꾼 뒤 한 번 배치를 처음부터 다시 계산하게 해 풀었다(`screens.relayout_screen`, D-172 ⑦)."""

    @staticmethod
    def squeezed(window):
        """행 높이가 그 행이 필요로 하는 높이보다 낮은 행들의 높이, 제목 라벨이 필요한 높이보다 낮은 개수."""
        rows = window.screen_widget.findChildren(UI.TopicRow)
        short = [row.height() for row in rows if row.height() < row.layout().totalHeightForWidth(row.width())]
        titles = [label for row in rows for label in row.findChildren(UI.Label) if label.property("role") == "h3" and label.heightForWidth(label.width()) > label.height() + 1]
        return short, len(titles)

    def test_rows_stay_whole_after_the_drawer_closes_and_the_screen_is_drawn_again_at_1280x720(self):
        window = self.make(size=(1280, 720))
        self.assertEqual(self.squeezed(window), ([], 0))
        self.assertGreaterEqual(len(window.screen_widget.findChildren(UI.TopicRow)), 5)
        window.open_drawer(window.state.home_rows()[1].id)
        ui_offscreen.wait_until(self.app, lambda: window.drawer.x() <= window.width() - window.drawer.width() + 2, 3)
        self.settle()
        window.close_drawer()                                                              # 다시 그린다
        self.settle(12)
        self.assertEqual(self.squeezed(window), ([], 0))
        self.assertEqual(ui_offscreen.find_clipping(window), [])
        window.show_sample_info()
        self.settle(6)
        self.assertEqual(self.squeezed(window), ([], 0))

    def test_rows_stay_whole_at_every_size_while_the_window_is_dragged_down_and_up_again(self):
        """창 폭을 1920 에서 900 까지 20 씩 줄였다가 다시 1920 까지 늘린다(높이 720 — 고치기 전에는 옛 코드도 새 코드도 이 끌기에서 폭 1060 에서 행이 눌렸다). 끌기를 하나하나 따라가야 굳은 상태가 생긴다."""
        window = self.make(size=(1920, 720))
        widths = list(range(1920, 899, -20)) + list(range(900, 1921, 20))
        squeezed = []
        for width in widths:
            window.resize(width, 720)
            self.settle(4)
            if self.squeezed(window) != ([], 0):
                squeezed.append(width)
        self.assertEqual(squeezed, [], "창 폭을 끌어 바꾸다가 추천 행이 눌린 폭")
        window.resize(1060, 768)
        self.settle(6)
        self.assertEqual(self.squeezed(window), ([], 0))
        self.assertEqual(ui_offscreen.find_clipping(window), [])

    def test_every_state_change_that_draws_the_screen_again_keeps_the_rows_whole_at_1280x720(self):
        window = self.make(size=(1280, 720))
        for filter_key in ("b", "hot", "new", "all", "a"):
            window.chip_home(filter_key)
            self.settle(10)
            self.assertEqual(self.squeezed(window), ([], 0), filter_key)
        window.select_topic(window.state.home_rows()[-1].id)
        self.settle(10)
        self.assertEqual(self.squeezed(window), ([], 0))
        window.nav_buttons["settings"].click()
        self.settle(10)
        window.nav_buttons["home"].click()
        self.settle(10)
        self.assertEqual(self.squeezed(window), ([], 0))

    def test_drawing_and_resizing_schedule_one_relayout_and_the_helper_is_cheap_and_repeatable(self):
        import time
        from chanceblog_desktop.ui.qt import screens as screens_module
        window = self.make(size=(1280, 720))
        calls = []
        real = screens_module.relayout_screen
        screens_module.relayout_screen = lambda root: (calls.append(root), real(root))[1]
        self.addCleanup(setattr, screens_module, "relayout_screen", real)
        window.render()
        self.settle(4)
        self.assertGreaterEqual(len(calls), 1, "다시 그린 뒤 배치를 다시 계산한다")
        before = len(calls)
        window.resize(1300, 730)
        window.resize(1310, 740)                                                           # 끌어 바꾸는 동안은 미룬다
        self.settle(8)
        self.assertEqual(len(calls) - before, 1, "크기를 연달아 바꿔도 멈춘 뒤 한 번만")
        holder = window.scroll.widget()
        geometry = [w.geometry() for w in holder.findChildren(QWidget)]
        started = time.perf_counter()
        screens_module.relayout_screen(holder)
        screens_module.relayout_screen(holder)
        elapsed = time.perf_counter() - started
        self.settle(4)
        self.assertEqual(geometry, [w.geometry() for w in holder.findChildren(QWidget)], "여러 번 불러도 결과가 같다")
        self.assertLess(elapsed, 1.0)
        screens_module.relayout_screen(None)                                               # 화면이 아직 없어도 안전하다

    def test_a_window_that_closes_right_after_drawing_does_not_fail_in_the_timer(self):
        window = self.make(size=(1280, 720))
        window.render()
        window.close()
        self.settle(6)                                                                    # 타이머가 닫힌 창의 배치를 건드리다 오류를 내면 `tearDown` 의 예외 수집이 알린다


if __name__ == "__main__":
    unittest.main()
