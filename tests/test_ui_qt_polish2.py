"""후속 정리 둘째 묶음(POLISH-2)의 PySide6 시험(창을 화면에 띄우지 않고 offscreen). **PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_polish2_core`·`test_render_naver_polish2`).

지키는 것:
  1) 툴팁에 사용자가 친 글(별명·제목)이 들어갈 때 `<b>굵게</b>`·`&lt;` 같은 서식 모양이어도 툴팁이 칩 글처럼 **쓴 그대로** 보인다(SP-7·QP-5) — `plain_tooltip` 한 곳이 이스케이프하고, 줄인 칩·요약 배지(`with_tooltip`)와 옛 서랍 툴팁(홈 서랍·Seed 서랍)이 모두 거친다. 서식 모양이 아닌 글은 한 글자도 안 바뀐다.
  2) 열린 확인창을 바꿔 연 직후 같은 이벤트 차례에 확인창 부품이 지워져도(앱을 닫을 때) 다음 차례의 틀 다시 놓기가 예외를 슬롯 밖으로 내지 않는다(SP-6).
  3) 개수가 붙는 칩의 보이는 글이 주 화면(Seed 관리·주제 후보)에서 늘 `이름 · 개수` 다(QP-4 ①).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ui_qt_candidates import Base as CandidatesBase  # noqa: E402,I001
from test_ui_qt_drafts import Base as DraftsBase  # noqa: E402,I001
from test_ui_qt_seeds import HAVE, Base as SeedsBase  # noqa: E402,I001

from chanceblog_desktop.ui.core import channel_names as cn  # noqa: E402

if HAVE:
    import ui_offscreen
    from PySide6 import QtGui
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QPushButton, QToolTip, QWidget
    from chanceblog_desktop.ui.core import tokens as K
    from chanceblog_desktop.ui.qt import candidate_parts, components as UI

LONG30 = ("가나다라마바사아자차카타파하" * 3)[:30]
RICH30 = ("<b>굵게</b> " + LONG30)[:30]                                    # 서른 자 별명 — `<b>` 가 든 서식 모양
ENTITY30 = ("&lt;b&gt; " + LONG30)[:30]                                   # 서른 자 별명 — `&lt;` 가 든 서식 모양
MARKUP_LIKE = ("<b>굵게</b> 가나다", "&lt;b&gt; 원문", "a &lt; b", "앞 <i>기울임</i> 뒤", "<p>문단</p>", "<a href='x'>링크</a>", "x<br>y", "두  칸  공백 <b>굵게</b>", "<b>굵게</b>\n둘째 줄", RICH30, ENTITY30)
PLAIN_LOOKING = ("R&D 2 가나다", "그냥 글 가나다", "<unknown>태그</unknown>", "1 < 2 > 0", "<", "<<b>>", "&amp;lt; 원문", "가\n<b>x</b>", "예시 가게", LONG30)


def rendered(tip):
    """Qt 가 툴팁 글을 그리는 방식 그대로 — `Qt.mightBeRichText` 가 참이면 서식 글로 읽어(`QTextDocument.setHtml`) 보이는 글만 남고, 아니면 일반 글 그대로다(툴팁 라벨의 글자 형식이 AutoText 다)."""
    if QtGui.Qt.mightBeRichText(tip):
        document = QTextDocument()
        document.setHtml(tip)
        return document.toPlainText()
    return tip


def listed(first, second):
    return {"naver_a": (first, True), "naver_b": (second, True), "blogger_ko": ("", True), "blogger_en": ("", True), "github_pages": ("", True)}


def chips_of(root, prefix):
    return {str(button.property("focus_key")).split(":")[-1]: button for button in root.findChildren(QAbstractButton) if str(button.property("focus_key")).startswith(prefix)}


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class PlainTooltipTest(SeedsBase):
    def test_a_text_that_looks_like_markup_is_drawn_exactly_as_typed_and_would_not_be_without_the_helper(self):
        for text in MARKUP_LIKE:
            with self.subTest(text):
                self.assertTrue(QtGui.Qt.mightBeRichText(text), "이 글은 Qt 가 서식 글로 읽는 모양이다")
                self.assertNotEqual(rendered(text), text, "도우미 없이 그대로 달면 태그가 사라지거나 바뀌어 보인다(이 시험의 전제)")
                self.assertEqual(rendered(UI.plain_tooltip(text)), text, "도우미를 거치면 쓴 그대로 보인다(공백·줄바꿈도)")

    def test_a_text_that_does_not_look_like_markup_is_left_alone_and_is_drawn_as_typed_anyway(self):
        for text in PLAIN_LOOKING:
            with self.subTest(text):
                self.assertFalse(QtGui.Qt.mightBeRichText(text))
                self.assertEqual(UI.plain_tooltip(text), text, "한 글자도 안 바뀐다")
                self.assertEqual(rendered(UI.plain_tooltip(text)), text)
        self.assertEqual(UI.plain_tooltip(""), "")
        self.assertIsNone(UI.plain_tooltip(None), "문자열이 아니면 건드리지 않는다")

    def test_with_tooltip_and_the_chip_factory_put_the_typed_name_in_the_tooltip_and_the_raw_name_in_the_accessible_name(self):
        button = UI.with_tooltip(QPushButton("단추"), RICH30)
        self.assertEqual(rendered(button.toolTip()), RICH30)
        chip = UI.FilterChip("짧은 이름", 3, False, full=RICH30)
        self.assertEqual(rendered(chip.toolTip()), RICH30)
        self.assertIn(RICH30, chip.accessibleName(), "접근 이름은 별명 그대로(서식 글이 아니다)")
        plain = UI.FilterChip("예시 가게", 3, False, full="예시 가게 전체")
        self.assertEqual(plain.toolTip(), "예시 가게 전체", "서식 모양이 아닌 이름은 툴팁 글이 그대로다")
        self.assertEqual(UI.FilterChip("예시 가게", 3, False).toolTip(), "", "줄이지 않은 칩은 툴팁이 없다")

    def test_the_elided_label_the_semantic_badge_and_the_clamped_card_text_draw_a_name_that_looks_like_markup_as_typed(self):
        label = UI.ElidedLabel(RICH30, "small")
        self.assertEqual(rendered(label.toolTip()), RICH30)
        long_text = "<b>굵게</b> " + "가나다라마바사아자차카타" * 2
        badge = UI.SemanticBadge(K.BADGE_KINDS[0], long_text)
        self.assertNotEqual(badge.text(), badge.full_text, "배지 글이 줄었다(툴팁이 있는 경우)")
        self.assertEqual(rendered(badge.toolTip()), badge.full_text)
        clamped = candidate_parts.ClampedLabel(long_text, "small", 2)
        self.assertEqual(rendered(clamped.toolTip()), long_text)
        # 강화(D-595, 감사 AS-S1 권고-4): 제목은 '이름을 쓴 그대로 그린다' 인데 옛 단언은 툴팁만 봤다 — 글 자체의 형식(서식 글이 아니라 일반 글)과 보이는 글도 못박는다
        self.assertEqual((label.textFormat(), label.text()), (Qt.PlainText, RICH30))
        self.assertEqual(badge.textFormat(), Qt.PlainText)
        self.assertTrue(badge.text().endswith("…") and badge.full_text.startswith(badge.text()[:-1]), "보이는 글은 쓴 이름의 앞부분 + …(태그를 벗기지 않는다)")
        self.assertEqual((clamped.textFormat(), clamped.plain_text()), (Qt.PlainText, long_text))

    def test_a_tooltip_shown_for_the_keyboard_focus_is_the_same_text(self):
        window = self.make()
        self.activate(window)
        chip = UI.FilterChip("짧은 이름", 3, False, full=RICH30)
        host = QWidget(window)
        host.setGeometry(40, 40, 300, 60)
        chip.setParent(host)
        host.show()
        self.settle(4)
        QToolTip.hideText()
        chip.setFocus(Qt.TabFocusReason)
        self.settle(6)
        self.assertTrue(chip.hasFocus())
        self.assertTrue(QToolTip.isVisible(), "키보드 포커스로 툴팁이 뜬다")
        self.assertEqual(rendered(QToolTip.text()), RICH30)
        QToolTip.hideText()


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ScreenTooltipsTest(SeedsBase):
    """서식 모양의 별명(`<b>…</b>`·`&lt;`)이 주 화면 칩·요약 배지의 툴팁에서 쓴 그대로 보인다 — 칩 글(일반 글)과 같게."""

    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def test_the_seed_screen_scope_chip_and_summary_badge_tooltips_show_the_alias_as_typed(self):
        window = self.make()
        cn.use(cn.labels(listed(RICH30, ENTITY30)))
        window.state.seeds.more_filters = True
        window.render()
        self.settle(8)
        scope = chips_of(window.screen_widget, "seeds:scope:")
        self.assertEqual(rendered(scope["naver_a"].toolTip()), RICH30)
        self.assertEqual(rendered(scope["naver_b"].toolTip()), ENTITY30)
        self.assertIn(RICH30, scope["naver_a"].accessibleName(), "접근 이름은 별명 그대로")
        badges = [label for label in window.screen_widget.findChildren(QLabel) if label.property("badge") and "후보 생성" in label.text()]
        long_badge = next(label for label in badges if RICH30 in label.accessibleName())
        self.assertIn(RICH30, rendered(long_badge.toolTip()), "요약 칩의 툴팁도 별명이 쓴 그대로 든 칩 글이다")
        self.assertIn("<b>", rendered(long_badge.toolTip()))

    def test_a_cut_chip_tooltip_shown_for_the_keyboard_focus_of_the_seed_screen_is_the_alias_as_typed(self):
        window = self.make()
        cn.use(cn.labels(listed(RICH30, "예시 가게")))
        window.state.seeds.more_filters = True
        window.render()
        self.settle(8)
        self.activate(window)
        chip = chips_of(window.screen_widget, "seeds:scope:")["naver_a"]
        QToolTip.hideText()
        chip.setFocus(Qt.TabFocusReason)
        self.settle(6)
        self.assertTrue(QToolTip.isVisible())
        self.assertEqual(rendered(QToolTip.text()), RICH30)
        QToolTip.hideText()

    def home_window(self, size=(1366, 768)):
        window = self.make(size=size, page="home")
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        self.settle()
        return window

    def test_the_old_home_drawer_tooltips_show_the_alias_as_typed(self):
        """옛 서랍 툴팁(`blog_tip` 배지·`{이름} 초안` 단추)도 같은 도우미를 거친다 — 서랍은 이름을 열두 자로 줄여 전체 이름이 툴팁에 있다."""
        window = self.home_window()
        cn.use(cn.labels(listed(RICH30, ENTITY30)))
        window.render()
        self.settle()
        window.open_drawer("rA1")
        self.settle(8)
        body = window.drawer.scroll.widget()
        badge = next(widget for widget in body.findChildren(QWidget) if widget.property("badge") == "info")
        self.assertEqual(rendered(badge.toolTip()), RICH30)
        self.assertEqual(badge.accessibleName(), RICH30, "접근 이름은 별명 그대로")
        draft = next(button for button in body.findChildren(QAbstractButton) if button.text().endswith(" 초안"))
        self.assertEqual(rendered(draft.toolTip()), f"{RICH30} 초안")
        self.assertEqual(draft.accessibleName(), f"{RICH30} 초안")
        window.close_drawer()

    def test_the_old_seed_drawer_chip_tooltips_show_the_alias_as_typed(self):
        window = self.make()
        cn.use(cn.labels(listed(RICH30, ENTITY30)))
        window.render()
        self.settle()
        window.seed_open_new()
        self.settle(8)
        self.dui(window).fields["scope"].chips["common"].click()
        self.settle(8)
        fields = self.dui(window).fields
        for name in ("scope", "allowed_channels"):
            for code, alias in (("naver_a", RICH30), ("naver_b", ENTITY30)):
                chip = fields[name].chips[code]
                self.assertEqual(rendered(chip.toolTip()), alias, (name, code))
                self.assertIn(alias, chip.accessibleName(), (name, code))


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class CandidateAndDraftTooltipsTest(CandidatesBase):
    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def test_the_candidate_channel_chip_tooltip_shows_the_alias_as_typed(self):
        window = self.make()
        cn.use(cn.labels(listed(RICH30, "예시 가게")))
        window.render()
        self.settle(8)
        chips = chips_of(window.screen_widget, "cand:channel:")
        self.assertEqual(rendered(chips["naver_a"].toolTip()), RICH30)
        self.assertEqual(chips["naver_b"].toolTip(), "")
        self.activate(window)
        QToolTip.hideText()
        chips["naver_a"].setFocus(Qt.TabFocusReason)
        self.settle(6)
        self.assertTrue(QToolTip.isVisible())
        self.assertEqual(rendered(QToolTip.text()), RICH30)
        QToolTip.hideText()


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class DraftTooltipsTest(DraftsBase):
    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def test_the_draft_blog_chip_tooltip_shows_the_alias_as_typed(self):
        window = self.drafted()
        window.drf_toggle_options()
        cn.use(cn.labels(listed(RICH30, "예시 가게")))
        window.render()
        self.settle(8)
        chips = self.ui(window).blog_chips
        self.assertEqual(rendered(chips["naver_a"].toolTip()), RICH30)
        self.assertEqual(chips["naver_b"].toolTip(), "")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ReplaceSettledTest(SeedsBase):
    """검증 S SP-6: 열린 확인창을 바꿔 연 직후(다음 차례에 틀을 다시 놓으려고 예약한 뒤) 같은 이벤트 차례에 확인창 부품이 지워지면 예약한 일이 이미 지워진 부품에 `place()` 를 불러 `RuntimeError`(Internal C++ object already deleted)를 슬롯 밖으로 냈다(앱을 닫을 때만 닿는다)."""

    def test_a_dialog_destroyed_in_the_same_turn_it_was_replaced_raises_nothing_when_the_postponed_frame_fix_comes_due(self):
        window = self.make(page=None)
        window.show_dialog("첫째 확인창", "첫째 본문이에요.", ok="확인", cancel="취소")
        self.settle(3)
        window.show_dialog("둘째 확인창", "둘째 본문이에요.", ok="확인", cancel="취소")          # 바꿔 연다 → 다음 차례에 틀을 다시 놓으려고 예약
        dialog = window.dialog
        dialog.setParent(None)
        dialog.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QApplication.processEvents()
        QApplication.processEvents()
        self.assertEqual(self.errors, [], "지워진 확인창에 예약했던 일이 슬롯 밖으로 예외를 내면 안 된다")
        window.dialog = type("Stub", (), {"is_open": False, "place": lambda self: None, "dismiss": lambda self: None})()                  # 지운 확인창 대신(창을 닫을 때 쓰인다)

    def test_replacing_and_then_closing_in_the_same_turn_leaves_the_dialog_closed_and_a_new_one_takes_its_frame(self):
        window = self.make()
        window.show_dialog("A", "a", ok="확인", cancel="취소")
        self.settle(3)
        window.show_dialog("B", "b", ok="확인", cancel="취소")                                  # 바꿔 연다 → 예약
        window.close_dialog()                                                                   # 예약한 일이 돌기 전에 닫는다
        QApplication.processEvents()
        self.settle(4)
        self.assertFalse(window.dialog.is_open)
        self.assertFalse(window.dialog.isVisible(), "닫은 확인창이 예약한 일 때문에 다시 보이면 안 된다")
        self.assertFalse(window.dialog.scrim.isVisible())
        window.show_dialog("C", "c", ok="확인", cancel="취소")                                  # 곧바로 새로 연다
        self.settle(6)
        self.assertTrue(window.dialog.isVisible())
        self.assertGreater(window.dialog.height(), 120)

    def test_the_replaced_dialog_still_gets_its_frame_a_turn_later_when_nothing_is_destroyed(self):
        """고침(받는 객체를 함께 준 예약)이 평소 길을 막지 않는다 — 바꿔 연 확인창은 한 차례 뒤에 새로 연 것과 같은 높이가 된다(POLISH-1 PQ-19)."""
        window = self.make(size=(1366, 768))
        window.show_dialog("첫째", "첫째 본문이에요.", ok="확인", cancel="취소")
        self.settle(6)
        window.show_dialog("둘째", "둘째 본문이에요. " * 8, ok="확인", cancel="취소")
        self.settle(6)
        replaced = window.dialog.height()
        window.close_dialog()
        self.settle(3)
        window.show_dialog("둘째", "둘째 본문이에요. " * 8, ok="확인", cancel="취소")
        self.settle(6)
        self.assertEqual(replaced, window.dialog.height())
        self.assertGreater(replaced, 120)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class DialogHeightBandTest(SeedsBase):
    """검증 Q PQ-18(확인창이 창보다 10px 길어 막대가 생김 — 사진 3장·1093×614): 확인창은 창 위아래로 16px 씩 띄우는 것이 기본이고(`roomy` = 창 높이 - 32), 필요한 높이가 그보다 조금(16px 까지) 길면 여백을 8px 씩까지 줄여 막대 없이 보인다(`tight` = 창 높이 - 16).
    그보다 길면 예전처럼 본문 칸이 스크롤로 받는다(위아래 16px 씩)."""

    BODY = "\n".join(f"{number}. 확인창 본문 줄이에요 — 높이를 재려고 여러 줄을 두었어요." for number in range(1, 25))

    def open_with_overflow(self, overflow, width=1093):
        """긴 본문의 확인창을 큰 창에서 열어 필요 높이를 읽고, 위아래 16px 씩 띄운 높이(창 - 32)가 필요 높이보다 `overflow` 만큼 모자라는 창으로 줄인다(음수면 그만큼 남는 창)."""
        window = self.make(size=(width, 1400), page=None)
        window.show_dialog("제목", self.BODY, ok="확인", cancel="취소")
        self.settle(4)
        needed = window.dialog.layout_.totalHeightForWidth(window.dialog.width())
        window.resize(width, needed + 32 - overflow)
        self.settle(8)
        body = window.dialog.findChildren(UI.DialogBody)[0]
        return window, window.dialog, body, needed

    def test_a_dialog_up_to_sixteen_pixels_taller_than_the_usual_margin_allows_fits_with_smaller_margins_and_no_bar(self):
        for overflow in (1, 10, 16):
            with self.subTest(overflow=overflow):
                window, dialog, body, needed = self.open_with_overflow(overflow)
                bar = body.verticalScrollBar()
                top, bottom = dialog.y(), window.height() - dialog.y() - dialog.height()
                self.assertEqual(dialog.height(), needed, "필요한 높이만큼 열린다")
                self.assertEqual((bar.maximum(), body.focusPolicy(), body.accessibleName()), (0, Qt.NoFocus, ""), "스크롤 막대·Tab 정거장·이름이 없다")
                self.assertGreaterEqual(min(top, bottom), 8, f"위아래 여백은 8px 이상({top}·{bottom})")
                self.assertLessEqual(abs(top - bottom), 1, f"위아래 여백이 같다({top}·{bottom})")
                self.assertTrue(window.rect().contains(dialog.geometry()))
                self.assertEqual(ui_offscreen.find_clipping(dialog), [])
                window.close_dialog()

    def test_a_dialog_more_than_sixteen_pixels_taller_keeps_the_usual_sixteen_pixel_margins_and_scrolls(self):
        for overflow in (17, 40, 200):
            with self.subTest(overflow=overflow):
                window, dialog, body, needed = self.open_with_overflow(overflow)
                bar = body.verticalScrollBar()
                self.assertEqual((dialog.height(), dialog.y()), (window.height() - 32, 16), "예전처럼 위아래 16px 씩 띄우고 본문 칸이 스크롤로 받는다")
                self.assertEqual(bar.maximum(), needed - (window.height() - 32), "넘친 만큼 스크롤된다")
                self.assertEqual((body.focusPolicy(), body.accessibleName()), (Qt.TabFocus, body.label.plain_text()), "스크롤이 있으면 키보드로 읽는 정거장이다")
                self.assertTrue(window.rect().contains(dialog.geometry()))
                window.close_dialog()

    def test_a_dialog_that_fits_the_usual_margin_is_centered_exactly_as_before(self):
        for overflow in (0, -1, -100):
            with self.subTest(overflow=overflow):
                window, dialog, body, needed = self.open_with_overflow(overflow)
                self.assertEqual(dialog.height(), needed)
                self.assertEqual(dialog.y(), max(16, (window.height() - needed) // 2), "위아래 16px 이상 띄워 가운데 — 예전 규칙 그대로")
                self.assertEqual(body.verticalScrollBar().maximum(), 0)
                window.close_dialog()


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class CountedChipCaptionTest(SeedsBase):
    """개수가 붙는 칩의 보이는 글은 주 화면에서 늘 `이름 · 개수` — 숫자로 끝나는 이름도 아닌 이름도 같은 구분 글이다(QP-4 ①)."""

    def test_every_counted_chip_of_the_seed_screen_uses_the_middle_dot_and_none_keeps_two_spaces(self):
        window = self.make()
        window.state.seeds.more_filters = True
        window.render()
        self.settle(8)
        counted = [button for button in window.screen_widget.findChildren(QAbstractButton) if str(button.property("focus_key")).startswith(("seeds:scope:", "seeds:status:"))]
        self.assertGreaterEqual(len(counted), 9)
        for button in counted:
            self.assertRegex(button.text(), r"^.+ · \d+$", button.text())
            self.assertNotIn("  ", button.text())
        texts = {str(button.property("focus_key")).split(":")[-1]: button.text() for button in counted if str(button.property("focus_key")).startswith("seeds:scope:")}
        self.assertEqual((texts["github_pages"], texts["naver_a"]), ("GitHub Pages · 1", "네이버 블로그 1 · 6"), "숫자로 끝나는 칩과 아닌 칩의 구분 글이 같다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class CandidateCountedChipCaptionTest(CandidatesBase):
    def test_every_counted_chip_of_the_candidate_screen_uses_the_middle_dot_and_none_keeps_two_spaces(self):
        window = self.make()
        window.state.candidates.more_filters = True
        window.render()
        self.settle(8)
        counted = [button for button in window.screen_widget.findChildren(QAbstractButton) if str(button.property("focus_key")).startswith(("cand:channel:", "cand:status:"))]
        self.assertGreaterEqual(len(counted), 6)
        for button in counted:
            self.assertRegex(button.text(), r"^.+ · \d+$", button.text())
            self.assertNotIn("  ", button.text())
            self.assertRegex(button.accessibleName(), r"\d+(개)?$", "접근 이름은 개수로 끝난다(그대로)")


if __name__ == "__main__":
    unittest.main()
