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
    from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

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

    def test_a_name_that_ends_with_a_digit_is_split_from_the_count_by_a_dot_in_the_chip_text_and_a_comma_in_the_accessible_name(self):
        window = self.make()
        window.state.seeds.more_filters = True
        window.render()
        self.settle(8)
        scope = chips_of(window.screen_widget, "seeds:scope:")
        self.assertEqual(scope["naver_a"].text(), "네이버 블로그 1 · 6")
        self.assertEqual(scope["naver_a"].accessibleName(), "네이버 블로그 1, 6")
        self.assertEqual(scope["github_pages"].text(), "GitHub Pages  1", "숫자로 끝나지 않는 이름은 그대로")
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


if __name__ == "__main__":
    unittest.main()
