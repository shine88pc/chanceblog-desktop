"""후속 정리 묶음(POLISH-1)의 PySide6 시험(창을 화면에 띄우지 않고 offscreen). **PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_polish1_core`).

지키는 것:
  1) 아주 긴 별명(서른 자 둘·폭이 넓은 글자·이모지)이어도 주 화면(Seed 관리·주제 후보·초안 작성)의 채널 칩·요약·거르기가 **일곱 창 크기**에서 페이지 가로 스크롤·글자 잘림·눌림이 없다(검증 Q3-2·Q4-4).
  2) 줄인 칩은 전체 이름이 툴팁과 접근 이름에 있고 줄이지 않은 칩에는 툴팁이 따로 없다. 이름이 숫자로 끝나는 칩은 개수와 가운뎃점으로 갈린다(Q2-8).
  3) Seed·후보의 글 검색 칸에서 치는 중에 늦게 도착한 이름 읽기가 화면을 다시 그리지 않는다(검증 S3-3 — 새 칸이 만들어지면 한글 조합·커서가 끊긴다). 검색 칸에 포커스가 없으면 평소처럼 바로 다시 그린다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ui_qt_candidates import Base as CandidatesBase  # noqa: E402,I001
from test_ui_qt_drafts import Base as DraftsBase  # noqa: E402,I001
from test_ui_qt_drawer_names import assert_content_fits  # noqa: E402,I001
from test_ui_qt_seeds import HAVE, Base as SeedsBase  # noqa: E402,I001

from chanceblog_desktop.ui.core import channel_names as cn  # noqa: E402

if HAVE:
    import ui_offscreen
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QLabel, QToolTip, QWidget
    from chanceblog_desktop.ui.qt import components as UI

SEVEN = ((1920, 1080), (1600, 960), (1366, 768), (1280, 720), (1093, 614), (910, 512), (900, 560))
LONG30 = ("가나다라마바사아자차카타파하" * 3)[:30]
WIDE30 = "W" * 30
EMOJI30 = "😀🚀🌟" * 10


def listed(first, second):
    return {"naver_a": (first, True), "naver_b": (second, True), "blogger_ko": ("", True), "blogger_en": ("", True), "github_pages": ("", True)}


NAME_SETS = {"같은 한글 서른 자 둘": listed(LONG30, LONG30), "같은 W 서른 자 둘": listed(WIDE30, WIDE30), "이모지 서른 자와 그 뒤집은 것": listed(EMOJI30, EMOJI30[::-1])}


def read_names(window):
    """앱이 열린 뒤 늦게 도착한 블로그 정보 읽기를 흉내 낸다(시험 창은 시작 읽기를 하지 않는다)."""
    provider = window.state.blogs.provider
    window.state.blogs.apply_loaded(provider.load_blogs(lambda *a: None, lambda: False))
    window._names_changed()


def chips_of(root, prefix):
    return {str(button.property("focus_key")).split(":")[-1]: button for button in root.findChildren(QAbstractButton) if str(button.property("focus_key")).startswith(prefix)}


def assert_keyboard_tooltips(test, chips, wanted):
    """칩마다 Tab 포커스를 주고 키보드 포커스로 뜬 툴팁을 본다 — `wanted` 는 {열쇠: 툴팁 글 또는 None(툴팁 없음)}. 포커스를 옮기면 앞 칩의 툴팁은 사라진다."""
    for key, text in wanted.items():
        QToolTip.hideText()
        chips[key].setFocus(Qt.TabFocusReason)
        test.settle(6)
        test.assertTrue(chips[key].hasFocus(), key)
        if text is None:
            test.assertFalse(QToolTip.isVisible(), f"{key}: 이름이 다 보이는 칩은 키보드 포커스에도 툴팁이 없다")
        else:
            test.assertTrue(QToolTip.isVisible(), f"{key}: 줄인 칩은 키보드 포커스로 툴팁이 뜬다")
            test.assertEqual(QToolTip.text(), text, key)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class SeedScreenChipsTest(SeedsBase):
    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def open_filters(self, window):
        window.state.seeds.more_filters = True
        window.render()
        self.settle(8)

    def test_the_seed_screen_has_no_horizontal_scroll_clipping_or_squeezing_for_very_long_aliases_at_seven_window_sizes(self):
        for size in SEVEN:
            window = self.make(size=size)
            for label, items in NAME_SETS.items():
                cn.use(cn.labels(items))
                self.open_filters(window)
                where = f"{size} {label}"
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{where}: 페이지 가로 스크롤")
                self.assertEqual(ui_offscreen.find_clipping(window), [], where)
                self.assertEqual(ui_offscreen.find_squeezed(window), [], where)

    def test_a_cut_summary_chip_and_a_cut_scope_chip_carry_the_full_name_while_a_name_that_fits_has_no_tooltip(self):
        window = self.make()
        cn.use(cn.labels(listed(LONG30, "예시 가게")))
        self.open_filters(window)
        scope = chips_of(window.screen_widget, "seeds:scope:")
        cut, whole = scope["naver_a"], scope["naver_b"]
        self.assertEqual((cut.toolTip(), whole.toolTip()), (LONG30, ""), "줄인 칩만 툴팁이 있다")
        self.assertIn(LONG30, cut.accessibleName(), "접근 이름은 전체 이름")
        self.assertNotIn(LONG30, cut.text())
        badges = {label.accessibleName(): label for label in window.screen_widget.findChildren(QLabel) if label.property("badge") and "후보 생성" in label.text()}
        long_badge = next(label for name, label in badges.items() if LONG30 in name)
        self.assertNotIn(LONG30, long_badge.text())
        self.assertIn(LONG30, long_badge.toolTip(), "요약 칩의 툴팁은 전체 이름이 든 칩 글")
        short_badge = next(label for name, label in badges.items() if "예시 가게" in name)
        self.assertEqual(short_badge.toolTip(), "")

    def test_a_cut_scope_chip_shows_its_full_name_as_a_tooltip_when_the_keyboard_focus_comes_to_it_and_a_chip_that_fits_shows_none(self):
        """툴팁 글이 있다는 것만이 아니라 Tab 으로 포커스가 올 때 실제로 뜬다(검증 Q QP-1 — `with_tooltip` 을 일반 툴팁으로 바꿔도 글 시험은 통과했다). 요약 칩은 포커스를 받지 않는 배지라 마우스를 올릴 때만 뜬다."""
        window = self.make()
        cn.use(cn.labels(listed(LONG30, "예시 가게")))
        self.open_filters(window)
        self.activate(window)
        scope = chips_of(window.screen_widget, "seeds:scope:")
        assert_keyboard_tooltips(self, scope, {"naver_a": LONG30, "naver_b": None})
        badge = next(label for label in window.screen_widget.findChildren(QLabel) if label.property("badge") and LONG30 in label.accessibleName())
        self.assertEqual(badge.focusPolicy(), Qt.NoFocus, "요약 칩(배지)은 Tab 정거장이 아니다 — 키보드 툴팁이 없는 까닭")

    def test_a_name_that_ends_with_a_digit_is_split_from_the_count_by_a_dot_in_the_chip_text_and_a_comma_in_the_accessible_name(self):
        window = self.make()
        window.state.seeds.more_filters = True
        window.render()
        self.settle(8)
        scope = chips_of(window.screen_widget, "seeds:scope:")
        self.assertEqual(scope["naver_a"].text(), "네이버 블로그 1 · 6")
        self.assertEqual(scope["naver_a"].accessibleName(), "네이버 블로그 1, 6")
        self.assertEqual(scope["github_pages"].text(), "GitHub Pages · 1", "숫자로 끝나지 않는 이름도 같은 가운뎃점(POLISH-2 QP-4 ①)")
        self.assertEqual(scope["github_pages"].accessibleName(), "GitHub Pages 1")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class CandidateScreenChipsTest(CandidatesBase):
    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def test_the_candidate_screen_and_its_detail_have_no_horizontal_scroll_clipping_or_squeezing_for_very_long_aliases_at_seven_window_sizes(self):
        for size in SEVEN:
            window = self.make(size=size)
            for label, items in NAME_SETS.items():
                cn.use(cn.labels(items))
                window.render()
                self.settle(6)
                where = f"{size} {label}"
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{where}: 페이지 가로 스크롤")
                self.assertEqual(ui_offscreen.find_clipping(window), [], where)
                self.assertEqual(ui_offscreen.find_squeezed(window), [], where)
                self.open_card(window, self.ids(window)[0])
                holder = window.detail_pane if window.detail_pane.isVisible() else window.drawer
                self.assertTrue(holder.isVisible(), f"{where}: 상세가 열렸다")
                assert_content_fits(self, holder, f"{where} 상세")
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{where}: 상세를 연 뒤 페이지 가로 스크롤")

    def test_a_cut_channel_chip_carries_the_full_name_and_the_chips_that_fit_have_no_tooltip(self):
        window = self.make()
        cn.use(cn.labels(listed(LONG30, "예시 가게")))
        window.render()
        self.settle(8)
        chips = chips_of(window.screen_widget, "cand:channel:")
        cut, whole = chips["naver_a"], chips["naver_b"]
        self.assertEqual((cut.toolTip(), whole.toolTip()), (LONG30, ""))
        self.assertIn(LONG30, cut.accessibleName())
        self.assertNotIn(LONG30, cut.text())
        self.assertIn("예시 가게", whole.accessibleName())

    def test_a_cut_channel_chip_shows_its_full_name_as_a_tooltip_when_the_keyboard_focus_comes_to_it_and_a_chip_that_fits_shows_none(self):
        window = self.make()
        cn.use(cn.labels(listed(LONG30, "예시 가게")))
        window.render()
        self.settle(8)
        self.activate(window)
        assert_keyboard_tooltips(self, chips_of(window.screen_widget, "cand:channel:"), {"naver_a": LONG30, "naver_b": None})


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class DraftScreenChipsTest(DraftsBase):
    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def test_the_draft_screen_blog_chips_have_no_horizontal_scroll_or_clipping_for_very_long_aliases_at_seven_window_sizes(self):
        for size in SEVEN:
            window = self.drafted(size=size)
            if not window.state.drafts.options_open:
                window.drf_toggle_options()
            for label, items in NAME_SETS.items():
                cn.use(cn.labels(items))
                window.render()
                self.settle(6)
                where = f"{size} {label}"
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{where}: 페이지 가로 스크롤")
                self.assertEqual(ui_offscreen.find_clipping(window), [], where)
                self.assertEqual(ui_offscreen.find_squeezed(window), [], where)

    def test_a_cut_blog_chip_carries_the_full_name_and_a_name_that_fits_has_no_tooltip(self):
        window = self.drafted()
        window.drf_toggle_options()
        cn.use(cn.labels(listed(LONG30, "예시 가게")))
        window.render()
        self.settle(8)
        chips = self.ui(window).blog_chips
        cut, whole = chips["naver_a"], chips["naver_b"]
        self.assertEqual((cut.toolTip(), whole.toolTip()), (LONG30, ""))
        self.assertIn(LONG30, cut.accessibleName())
        self.assertNotIn(LONG30, cut.text())
        self.assertEqual(whole.text(), "예시 가게")

    def test_a_cut_blog_chip_shows_its_full_name_as_a_tooltip_when_the_keyboard_focus_comes_to_it_and_a_chip_that_fits_shows_none(self):
        window = self.drafted()
        window.drf_toggle_options()
        cn.use(cn.labels(listed(LONG30, "예시 가게")))
        window.render()
        self.settle(8)
        self.activate(window)
        assert_keyboard_tooltips(self, self.ui(window).blog_chips, {"naver_a": LONG30, "naver_b": None})


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class SearchBoxTypingTest(SeedsBase):
    """검증 S3-3: Seed·후보의 글 검색 칸에서 한글을 치는 중에 시작 읽기가 늦게 끝나면 화면이 다시 그려져 칸이 새로 만들어지고 조합 중인 글자·커서가 끊겼다."""

    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def search_box(self, window, key):
        return next(widget for widget in window.screen_widget.findChildren(QWidget) if widget.property("focus_key") == key)

    def test_a_late_name_read_does_not_rebuild_the_seed_screen_while_the_search_box_has_the_focus_and_the_names_follow_at_the_next_draw(self):
        window = self.make()
        screen = window.screen_widget
        box = self.search_box(window, "seeds-query")
        self.focus(box)
        QTest.keyClicks(box, "ab")
        read_names(window)
        self.settle(6)
        self.assertEqual(cn.label("naver_a"), "예시 별명", "이름은 바뀌었다")
        self.assertIs(window.screen_widget, screen, "검색 칸에 포커스가 있으면 화면을 다시 그리지 않는다")
        self.assertIs(self.search_box(window, "seeds-query"), box, "같은 칸이 그대로다")
        self.assertEqual(box.text(), "ab")
        self.assertTrue(window._typing_would_be_lost())
        window.nav_buttons["settings"].setFocus(Qt.OtherFocusReason)
        self.settle(2)
        self.assertFalse(window._typing_would_be_lost(), "포커스가 검색 칸을 떠나면 더는 보호하지 않는다")
        window.render()
        self.settle(6)
        texts = " ".join(label.text() for label in window.screen_widget.findChildren(QLabel))
        self.assertIn("예시 별명", texts, "다음에 그릴 때 새 이름이 보인다")
        self.assertEqual(self.search_box(window, "seeds-query").text(), "ab", "글은 컨트롤러에 남아 다시 그려도 그대로다")

    def test_a_late_name_read_redraws_the_seed_screen_at_once_when_the_search_box_does_not_have_the_focus(self):
        window = self.make()
        screen = window.screen_widget
        window.nav_buttons["settings"].setFocus(Qt.OtherFocusReason)
        self.settle(2)
        self.assertFalse(window._typing_would_be_lost())
        read_names(window)
        self.settle(6)
        self.assertIsNot(window.screen_widget, screen, "포커스가 검색 칸에 없으면 바로 다시 그려 새 이름을 보인다")
        self.assertIn("예시 별명", " ".join(label.text() for label in window.screen_widget.findChildren(QLabel)))


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class CandidateSearchBoxTest(CandidatesBase):
    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def test_a_late_name_read_does_not_rebuild_the_candidate_screen_while_its_search_box_has_the_focus_and_does_redraw_otherwise(self):
        window = self.make(size=(1366, 768))
        screen = window.screen_widget
        box = next(widget for widget in screen.findChildren(QWidget) if widget.property("focus_key") == "cand-query")
        self.focus(box)
        QTest.keyClicks(box, "ab")
        read_names(window)
        self.settle(6)
        self.assertEqual(cn.label("naver_a"), "예시 별명", "이름은 바뀌었다")
        self.assertIs(window.screen_widget, screen, "검색 칸에 포커스가 있으면 화면을 다시 그리지 않는다")
        self.assertEqual(box.text(), "ab")
        self.assertTrue(window._typing_would_be_lost())
        cn.use(None)
        window.nav_buttons["settings"].setFocus(Qt.OtherFocusReason)
        self.settle(2)
        self.assertFalse(window._typing_would_be_lost())
        read_names(window)
        self.settle(6)
        self.assertIsNot(window.screen_widget, screen, "포커스가 검색 칸에 없으면 바로 다시 그린다")


SHORT_BODY = "짧은 본문이에요."
MEDIUM_BODY = "본문 한 줄이 꽤 길어서 줄이 바뀌어요. " * 5
LONG_BODY = "긴 본문이에요. 낮은 창에서는 스크롤이 생겨요. " * 40


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ReplacedDialogTest(SeedsBase):
    """검증 Q PQ-19(옛 문제): 열린 확인창을 닫지 않고 다른 확인창으로 바꾸면 새 확인창이 44px 로 접혀 제목·본문 높이가 0 이고 단추 윗부분만 보였다. 바꿔 연 확인창은 새로 연 확인창과 틀·제목·본문·단추 자리가 같다."""

    def snapshot(self, window):
        dialog = window.dialog
        body = dialog.findChildren(UI.DialogBody)
        title = [label for label in dialog.findChildren(QLabel) if label.property("role") == "h2"]
        buttons = [(button.text(), button.geometry().x(), button.geometry().y(), button.geometry().width(), button.geometry().height()) for button in dialog.findChildren(QAbstractButton) if button.isVisibleTo(dialog)]
        return {"dialog": [dialog.x(), dialog.y(), dialog.width(), dialog.height()], "body": [item.height() for item in body], "title": [item.height() for item in title], "buttons": buttons}

    def open_second(self, window, kind, text):
        if kind == "dialog":
            window.show_dialog("둘째 확인창", text, ok="그래도 하기", cancel="취소")
        else:
            window.show_choice_dialog("둘째 선택창", text, [("a", "저장", "primary", lambda: None), ("b", "저장 안 하고 나가기", "danger", lambda: None), ("c", "계속 고치기", "secondary", None)], first="a")

    def test_a_dialog_opened_over_an_open_dialog_has_the_same_frame_as_one_opened_fresh(self):
        for size in ((1366, 768), (900, 560)):
            window = self.make(size=size)
            for kind in ("dialog", "choice"):
                for label, text in (("짧은", SHORT_BODY), ("보통", MEDIUM_BODY), ("긴", LONG_BODY)):
                    where = f"{size} {kind} {label} 본문"
                    window.close_dialog()
                    self.settle(3)
                    self.open_second(window, kind, text)
                    self.settle(6)
                    fresh = self.snapshot(window)
                    window.close_dialog()
                    self.settle(3)
                    window.show_dialog("첫째 확인창", "첫째 본문이에요.", ok="확인", cancel="취소")
                    self.settle(6)
                    self.open_second(window, kind, text)                                   # 닫지 않고 바꾼다
                    self.settle(6)
                    replaced = self.snapshot(window)
                    self.assertEqual(replaced, fresh, f"{where}: 바꿔 연 확인창의 모양이 새로 연 것과 다르다")
                    self.assertGreater(replaced["dialog"][3], 120, f"{where}: 틀이 접혔다(44px)")
                    self.assertTrue(all(height > 0 for height in replaced["title"] + replaced["body"]), f"{where}: 제목·본문 높이 0")
                    self.assertTrue(all(y + height <= replaced["dialog"][3] for _name, _x, y, _w, height in replaced["buttons"]), f"{where}: 단추가 틀 밖이다")
                    self.assertLessEqual(replaced["dialog"][3], window.height() - 16, f"{where}: 틀이 창보다 크다")
                    window.close_dialog()
                    self.settle(3)

    def test_replacing_three_times_in_a_row_and_replacing_a_choice_dialog_by_a_plain_one_keeps_the_frame(self):
        window = self.make(size=(1366, 768))
        self.open_second(window, "choice", MEDIUM_BODY)
        self.settle(6)
        self.open_second(window, "dialog", MEDIUM_BODY)
        self.settle(6)
        self.open_second(window, "choice", SHORT_BODY)
        self.settle(6)
        self.open_second(window, "dialog", LONG_BODY)
        self.settle(6)
        replaced = self.snapshot(window)
        window.close_dialog()
        self.settle(3)
        self.open_second(window, "dialog", LONG_BODY)
        self.settle(6)
        self.assertEqual(replaced, self.snapshot(window))

    def test_the_old_buttons_never_stay_behind_when_a_dialog_is_replaced_and_the_default_button_takes_the_focus(self):
        window = self.make(size=(1366, 768))
        window.show_dialog("첫째 확인창", "첫째 본문이에요.", ok="첫째 확인", cancel="첫째 취소")
        self.settle(6)
        self.open_second(window, "dialog", MEDIUM_BODY)
        self.settle(6)
        names = sorted(button.text() for button in window.dialog.findChildren(QAbstractButton) if button.isVisibleTo(window.dialog))
        self.assertEqual(names, ["그래도 하기", "취소"])
        self.assertIs(window.dialog_default, next(button for button in window.dialog.findChildren(QAbstractButton) if button.text() == "그래도 하기"))


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ToastLevelTest(SeedsBase):
    """검증 Q PQ-25: 저장 알림이 안내(info)로 바뀌었지만 토스트는 색 없는 어두운 상자뿐이라 안내색이 안 보였다 — 수준이 있으면 토스트 왼쪽에 그 상태색 줄이 보인다(새 색 없이 상태색 토큰만)."""

    def test_a_toast_with_a_level_carries_the_level_and_the_style_sheet_draws_a_line_in_the_state_color_while_others_keep_the_old_look(self):
        from PySide6.QtWidgets import QApplication

        from chanceblog_desktop.ui.qt import theme
        window = self.make()
        sheet = QApplication.instance().styleSheet()
        colors = theme.colors()
        for level, token in (("info", "info"), ("warning", "warning"), ("error", "danger")):
            self.assertIn('QLabel#toast[level="%s"] { border-left: 4px solid %s; }' % (level, colors[token]), sheet, level)
            window.toast._expire()
            window.notify(f"수준 {level}", level)
            self.assertEqual(window.toast.property("level"), level)
            self.assertTrue(window.toast.isVisible())
        window.toast._expire()
        for level in (None, "ok", "엉뚱한 수준", ""):
            window.notify(f"수준 없는 안내 {level}", level)
            self.assertEqual(window.toast.property("level"), "", repr(level))
            window.toast._expire()

    def test_the_toast_keeps_the_level_of_the_message_that_is_shown_not_the_one_before(self):
        window = self.make()
        window.notify("첫 안내", "error")
        self.assertEqual(window.toast.property("level"), "error")
        window.notify("다음 안내")
        self.assertEqual(window.toast.property("level"), "", "다른 안내가 떠 있던 자리를 바꾸면 수준도 새 안내의 것이다")
        window.notify("다음 안내", "warning")
        self.assertEqual(window.toast.property("level"), "", "같은 안내가 또 오면 시간만 늘린다 — 모양은 그대로")

    @staticmethod
    def edge_colors(window):
        """토스트를 실제로 그려서 가운데 높이의 왼쪽 가장자리 픽셀 색(`#rrggbb`)을 줄 두께 + 2 개 읽는다 → (색 목록, 줄 두께 픽셀 수). 스타일시트의 4px 는 화면 배율만큼 굵어진다."""
        from PySide6.QtGui import QColor
        window.toast.adjustSize()
        image = window.toast.grab().toImage()
        line = max(1, round(4 * image.devicePixelRatio()))
        row = image.height() // 2
        return [QColor(image.pixelColor(x, row)).name() for x in range(line + 2)], line

    def test_the_left_edge_of_a_shown_toast_is_painted_in_the_state_color_and_a_toast_without_a_level_has_no_line_even_right_after_one_with_a_level(self):
        """속성·스타일시트 글만 보는 위 두 시험은 `repolish` 를 지워도 통과한다 — 속성은 바뀌어도 스타일이 다시 계산되지 않아 줄이 안 그려지는데 그 일은 글로는 안 보인다(검증 S SP-1·Q QP-1). 여기서는 실제로 그려 본다."""
        from PySide6.QtGui import QColor

        from chanceblog_desktop.ui.qt import theme
        window = self.make()
        colors = theme.colors()
        plain = QColor(colors["inverse_bg"]).name()
        for level, token in (("info", "info"), ("warning", "warning"), ("error", "danger")):
            window.toast._expire()
            window.notify(f"수준 {level}", level)
            self.settle(4)
            edge, line = self.edge_colors(window)
            wanted = QColor(colors[token]).name()
            self.assertEqual(edge[:line], [wanted] * line, f"{level}: 왼쪽 {line}px 가 상태색 {wanted} 이어야 한다 — {edge}")
            self.assertEqual(edge[line:], [plain, plain], f"{level}: 줄 오른쪽은 토스트 바탕색이어야 한다 — {edge}")
        for level in (None, "ok"):                                                    # 수준이 있던 안내 다음에 수준 없는 안내가 오면 이전 안내의 줄이 남지 않는다
            window.toast._expire()
            window.notify(f"먼저 안내 {level}", "error")
            self.settle(3)
            edge, line = self.edge_colors(window)
            self.assertEqual(edge[:line], [QColor(colors["danger"]).name()] * line, "먼저 뜬 안내에는 줄이 있다")
            window.toast._expire()
            window.notify(f"다음 일반 안내 {level}", level)
            self.settle(4)
            edge, line = self.edge_colors(window)
            self.assertEqual(edge, [plain] * (line + 2), f"수준 없는 안내({level!r})에는 줄이 없다 — {edge}")


if __name__ == "__main__":
    unittest.main()
