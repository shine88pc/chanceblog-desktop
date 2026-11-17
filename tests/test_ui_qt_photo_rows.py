"""'사진 정리' 사진 한 줄의 배치·접힘·첫 포커스·Enter·예시 글 대비(검증 Q 의 N-3·N-4(Enter 부분)·N-10 — 수정 지시 2).

지키는 것:
  1) 줄 배치(N-3 a) — 입력 칸 둘(`이 사진은 무엇인가요?`·`한마디 메모`)은 미리보기 바로 아래에 있고 그 아래에 종류·장소 분위기 칩이 온다. 화면 위에서 아래 순서와 Tab 순서가 같다.
     접힌 줄은 1366×768 의 대화상자 몸 높이 안에 들어오고 미리보기와 입력 칸 둘이 한 화면에 함께 보인다.
  2) 접힘(N-3 b) — `자리 정하기` 는 **사용자가 직접 고른 값**(기본값이 아닌 들어갈 곳·자리·설명 글)이 있을 때만 저절로 펼쳐지고(종류가 정한 기본 들어갈 곳은 접힌 단추의 한 줄 요약 `들어갈 곳: 도입 ▸` 뿐 — POLISH-1 M-2), 사용자가 접은 줄은 그 줄이 지워질 때까지 다른 동작이 되살리지 않는다.
  3) 첫 포커스(N-3 c) — 창을 (다시) 열면 첫 사진의 대상 칸이 몸 영역 안에 보인다(최소 창 900×560·125% 배율의 논리 크기 1093×614 포함).
  4) Enter(N-4) — 규칙이 받지 않은 글(한도를 넘김·검사에 걸림)은 Enter 로 다음 칸에 가지 않고 그 칸에 머문다.
  5) 예시 글(N-10) — 칸 안 예시 글은 보조 글 색(글자 대비 5.4:1)으로 보인다(기본 흐린 글은 3.2:1).
`test_ui_qt_photo` 의 도구(`PhotoBase`)만 이어 쓰고 그 모듈의 시험은 가져오지 않는다. **PySide6 가 없으면 통째로 건너뛴다.**
"""
import unittest

import test_ui_qt_photo as tq

if tq.HAVE:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from chanceblog_desktop.ui.core import tokens as K
    from chanceblog_desktop.ui.qt import theme

T = tq.T
fake_path = tq.fake_path


class RowLayoutTest(tq.PhotoBase):
    @staticmethod
    def top(widget, card):
        return widget.mapTo(card, widget.rect().topLeft()).y()

    @staticmethod
    def bottom(widget, card):
        return widget.mapTo(card, widget.rect().bottomLeft()).y()

    def test_the_two_input_fields_sit_right_under_the_preview_and_the_chips_follow_them(self):
        window, form = self.sheet(size=(1366, 768))
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        card = form.rows["p001"]
        order = [card.preview, card.subject, card.note, card.types_host, card.settings_host, card.place_toggle, card.confirm_box]
        tops = [self.top(widget, card) for widget in order]
        self.assertEqual(tops, sorted(tops), "위에서 아래: 미리보기 → 대상 → 메모 → 종류 칩 → 장소 분위기 칩 → 자리 정하기 → 확인했어요")
        self.assertEqual(len(set(tops)), len(tops))
        self.assertLessEqual(self.top(card.subject, card) - self.bottom(card.preview, card), 40, "대상 칸은 미리보기 그림 바로 아래다")
        self.assertLessEqual(self.bottom(card.note, card), 300, "미리보기와 입력 칸 둘이 한 줄의 첫 300px 안에 함께 있다")
        self.assertTrue(card.subject.isVisibleTo(form) and card.note.isVisibleTo(form), "입력 칸 둘은 접지 않는다")

    def test_a_folded_row_fits_the_body_of_the_1366_by_768_dialog_and_the_preview_and_both_fields_show_together(self):
        window, form = self.sheet(size=(1366, 768))
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        card = form.rows["p001"]
        viewport = form.scroll.viewport().height()
        self.assertLessEqual(card.height(), viewport - 40, f"접힌 줄 {card.height()}px 은 몸 높이 {viewport}px 안에(위아래 여유 40px 두고) 들어온다")
        bar = form.scroll.verticalScrollBar()
        bar.setValue(card.mapTo(form.scroll.widget(), card.rect().topLeft()).y())                    # 줄 맨 위에 맞춘다
        self.settle(3)
        for widget in (card.preview, card.subject, card.note):
            top = widget.mapTo(form.scroll.viewport(), widget.rect().topLeft()).y()
            bottom = widget.mapTo(form.scroll.viewport(), widget.rect().bottomLeft()).y()
            self.assertTrue(0 <= top and bottom <= viewport, (top, bottom, viewport, "줄 맨 위에 맞추면 미리보기와 입력 칸 둘이 한꺼번에 보인다"))

    def test_the_tab_order_inside_a_row_is_the_order_it_looks(self):
        """줄의 Tab 정거장(`stops`)을 화면 위치(위→아래, 같은 높이면 왼쪽→오른쪽)로 줄 세운 것과 같다 — 보이는 순서와 Tab 순서가 갈라지지 않는다."""
        window, form = self.sheet(size=(1366, 768))
        self.add_photos(form, fake_path(1), fake_path(2))
        card = form.rows["p001"]
        card.place_toggle.click()
        self.settle(4)
        stops = [widget for widget in card.stops() if widget.isVisibleTo(card) and widget.isEnabled()]
        self.assertGreaterEqual(len(stops), 8)
        place = lambda widget: (widget.mapTo(card, widget.rect().topLeft()).y(), widget.mapTo(card, widget.rect().topLeft()).x())
        self.assertEqual(stops, sorted(stops, key=place), [widget.accessibleName() for widget in stops])
        names = [widget.accessibleName() for widget in stops]
        self.assertLess(names.index(card.subject.edit.accessibleName()), names.index(card.note.edit.accessibleName()))
        first_chip = next(widget for widget in stops if widget.property("focus_key") and str(widget.property("focus_key")).startswith("pho:type:"))
        self.assertLess(stops.index(card.note.edit), stops.index(first_chip), "대상·메모 칸은 종류 칩보다 먼저다")


class PlaceFoldTest(tq.PhotoBase):
    """접힘 기억은 지키고(N-3 b), 무엇이 줄을 펼치는가만 바뀌었다(POLISH-1 M-2) — 옛 시험은 종류를 고르면 생기는 기본 들어갈 곳이 줄을 펼친다고 못박았다. 지금은 사용자가 직접 고른 값(기본값이 아닌 들어갈 곳)이 펼친다."""

    def open_and_choose(self, form, card, photo_id, section):
        """접힌 줄을 사용자가 펼치고 기본값이 아닌 들어갈 곳을 직접 고른다."""
        card.place_toggle.click()
        self.settle(3)
        self.assertTrue(card.place_body.isVisibleTo(card), "사용자가 펼쳤다")
        self.chip(form, "section", photo_id, section).click()
        self.settle(3)

    def test_a_place_section_the_user_closed_stays_closed_until_the_row_is_removed(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        card, other = form.rows["p001"], form.rows["p002"]
        self.assertFalse(card.place_body.isVisibleTo(card), "값이 없으면 접혀 있다")
        self.chip(form, "type", "p001", "간판").click()
        self.settle(4)
        self.assertFalse(card.place_body.isVisibleTo(card), "종류가 정한 기본 들어갈 곳(도입)은 줄을 펼치지 않는다(POLISH-1 M-2)")
        self.assertEqual(card.place_toggle.text(), "들어갈 곳: 도입 ▸", "접힌 단추가 한 줄로 요약한다")
        self.open_and_choose(form, card, "p001", "마무리")                                   # 사용자가 직접 고른 값 — 기본값(도입)이 아니다
        self.assertEqual(card.place_toggle.text(), window.state.drafts.photos.view()["rows"][0]["place"]["close_text"])
        card.place_toggle.click()
        self.settle(3)
        self.assertFalse(card.place_body.isVisibleTo(card), "사용자가 접었다")
        self.assertEqual(card.place_toggle.text(), "들어갈 곳: 마무리 ▸", "접힌 단추가 지금 값을 요약한다")
        other.confirm_box.click()                                                         # 다른 사진의 확인
        self.settle(4)
        self.assertFalse(card.place_body.isVisibleTo(card), "다른 사진의 확인이 접은 줄을 되살리지 않는다")
        card.confirm_box.click()                                                          # 같은 사진의 확인
        self.settle(4)
        self.assertFalse(card.place_body.isVisibleTo(card), "같은 사진의 확인도 마찬가지다")
        for value in ("음식", "기타", "간판"):                                               # 사용자가 고른 들어갈 곳은 종류를 바꿔도 그대로이고, 값이 있어도 접은 채다
            self.chip(form, "type", "p001", value).click()
            self.settle(3)
            self.assertFalse(card.place_body.isVisibleTo(card), value)
        self.commit(card.subject.edit, "정문 앞 간판")
        self.assertFalse(card.place_body.isVisibleTo(card), "칸에 글을 적어도 되살아나지 않는다")
        card.place_toggle.click()                                                         # 사용자가 다시 펼치면 펼쳐진다
        self.settle(3)
        self.assertTrue(card.place_body.isVisibleTo(card))
        self.assertEqual(card.place_toggle.text(), window.state.drafts.photos.view()["rows"][0]["place"]["close_text"])

    def test_a_row_opens_by_itself_only_when_a_value_the_user_chose_appears_and_never_for_a_default_or_for_a_row_that_has_none(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        first, second, third = form.rows["p001"], form.rows["p002"], form.rows["p003"]
        self.chip(form, "type", "p002", "음식").click()                                      # 기본 들어갈 곳(내용 소제목)만 생긴다 — 펼치지 않는다
        self.settle(4)
        self.assertFalse(second.place_body.isVisibleTo(second), "종류가 정한 기본값은 줄을 펼치지 않는다(POLISH-1 M-2)")
        self.assertEqual(second.place_toggle.text(), "들어갈 곳: 내용 소제목 ▸")
        self.assertEqual(board.set_section("p003", "마무리"), "ok")                          # 사용자가 고른 값이 접힌 줄에 생겼다(되돌리기·다른 길로도 생길 수 있다)
        form.refresh()
        self.settle(4)
        self.assertTrue(third.place_body.isVisibleTo(third), "사용자가 고른 값이 생긴 줄만 펼쳐진다")
        self.assertFalse(first.place_body.isVisibleTo(first), "값이 없는 줄은 접힌 채다")
        self.assertFalse(second.place_body.isVisibleTo(second), "기본값뿐인 줄도 접힌 채다")
        for card in (first, second, third):
            card.confirm_box.click()
        self.settle(4)
        self.assertFalse(first.place_body.isVisibleTo(first), "값이 없는 줄은 다른 동작에도 접힌 채다")
        self.assertFalse(second.place_body.isVisibleTo(second), "기본값뿐인 줄은 확인을 눌러도 접힌 채다")
        self.assertTrue(third.place_body.isVisibleTo(third), "펼쳐 둔 줄은 그대로다")
        self.assertEqual(board.count, 3)

    def test_a_removed_row_forgets_the_fold_and_comes_back_open_when_it_has_a_value_the_user_chose_and_folded_when_it_has_only_the_default(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        card, plain = form.rows["p001"], form.rows["p002"]
        self.chip(form, "type", "p001", "간판").click()
        self.chip(form, "type", "p002", "간판").click()
        self.settle(3)
        self.open_and_choose(form, card, "p001", "마무리")
        card.place_toggle.click()
        self.settle(3)
        self.assertFalse(card.place_body.isVisibleTo(card))
        card.remove.click()
        self.settle(4)
        form.undo_button.click()
        self.settle(5)
        again = form.rows["p001"]
        self.assertIsNot(again, card, "되돌리면 줄 부품이 새로 만들어진다")
        self.assertTrue(again.place_body.isVisibleTo(again), "사용자가 고른 값이 있는 새 줄은 펼친 채 만들어진다 — 접은 기억은 지워진 줄과 함께 사라졌다")
        plain.remove.click()
        self.settle(4)
        form.undo_button.click()
        self.settle(5)
        back = form.rows["p002"]
        self.assertFalse(back.place_body.isVisibleTo(back), "기본 들어갈 곳뿐인 줄은 되돌려도 접힌 채다")
        self.assertEqual(back.place_toggle.text(), "들어갈 곳: 도입 ▸")

    def test_a_section_text_with_an_ampersand_is_shown_as_plain_text_in_the_folded_button_and_never_becomes_an_alt_shortcut(self):
        """접힌 단추는 `들어갈 곳: <소제목> ▸` 로 요약한다 — 나중 단계가 적은 소제목 글에 `&` 가 있으면(`Q&A 코너`) Qt 가 `&A` 를 Alt 단축키로 읽어 글자가 사라지고 단추에 단축키가 붙으므로 `&&` 로 써야 한다(검증 S SP-10). 접근 이름은 앱이 만든 글 그대로다."""
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        board = window.state.drafts.photos
        board.set_type("p001", "기타")
        self.assertEqual(board._apply("p001", preferred_section="Q&A 코너"), "ok", "저장된 초안이나 나중 단계가 적은 소제목 글은 이런 값으로 들어온다")
        form.refresh()
        self.settle(6)
        card, other = form.rows["p001"], form.rows["p002"]
        self.assertTrue(card.place_body.isVisibleTo(card), "기본값이 아닌 들어갈 곳은 줄을 펼친다")
        card.place_toggle.click()                                                         # 사용자가 접는다 → 접힌 단추가 한 줄 요약
        self.settle(4)
        wanted = "들어갈 곳: Q&&A 코너 ▸"
        self.assertEqual(card.place_toggle.text(), wanted, "`&` 하나는 단축키 표시가 된다 — `&&` 로 써야 글자 `&` 가 보인다")
        self.assertTrue(card.place_toggle.shortcut().isEmpty(), "단축키가 붙으면 안 된다")
        self.assertEqual(card.place_toggle.accessibleName(), board.view()["rows"][0]["place"]["a11y"], "접근 이름은 앱이 만든 글 그대로")
        self.assertIn("Q&A 코너", card.place_toggle.accessibleName(), "접근 이름에는 `&` 하나가 그대로 있다")
        form.refresh()                                                                    # 줄을 다시 그려도 접힌 단추 글은 같다
        self.settle(4)
        self.assertEqual(card.place_toggle.text(), wanted)
        card.place_toggle.click()                                                         # 펼쳤다 다시 접어도 같다
        self.settle(3)
        card.place_toggle.click()
        self.settle(3)
        self.assertEqual(card.place_toggle.text(), wanted)
        self.assertTrue(card.place_toggle.shortcut().isEmpty())
        self.assertEqual(other.place_toggle.text(), board.view()["rows"][1]["place"]["open_text"], "소제목 글이 없는 다른 줄은 처음 글 그대로")

    def test_a_row_that_is_created_open_has_the_open_button_text_from_the_start_and_not_the_folded_summary(self):
        """줄 부품은 화면에 보이기 전에 만들어진다(그때 `isVisible()` 은 아직 거짓이다) — 접혔는지는 보이는지가 아니라 숨겼는지(`isHidden`)로 가려야 한다. 사용자가 고른 값이 있어 펼친 채 새로 만들어진 줄(지운 사진을 되돌린 줄)의 단추는 처음부터 `자리 정하기 ▾` 이고 접힌 요약(`들어갈 곳: … ▸`)이 아니다(검증 Q QP-1)."""
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        board = window.state.drafts.photos
        card = form.rows["p001"]
        self.chip(form, "type", "p001", "간판").click()
        self.settle(3)
        self.open_and_choose(form, card, "p001", "마무리")
        place = board.view()["rows"][0]["place"]
        self.assertEqual(card.place_toggle.text(), place["close_text"], "펼친 줄의 단추는 `자리 정하기 ▾`")
        card.remove.click()
        self.settle(4)
        form.undo_button.click()
        self.settle(5)
        again = form.rows["p001"]
        self.assertIsNot(again, card, "되돌리면 줄 부품이 새로 만들어진다")
        self.assertTrue(again.place_body.isVisibleTo(again), "사용자가 고른 값이 있는 새 줄은 펼친 채 만들어진다")
        self.assertEqual(again.place_toggle.text(), place["close_text"], "새로 만들어진 펼친 줄의 단추도 `자리 정하기 ▾` — 접힌 요약이면 펼친 줄이 접힌 줄처럼 읽힌다")
        self.assertNotIn("▸", again.place_toggle.text())
        again.place_toggle.click()                                                        # 사용자가 접으면 그때 요약이 된다
        self.settle(3)
        self.assertEqual(again.place_toggle.text(), "들어갈 곳: 마무리 ▸")


class FirstFocusTest(tq.PhotoBase):
    def visible_inside(self, form, box):
        viewport = form.scroll.viewport()
        top = box.mapTo(viewport, box.rect().topLeft()).y()
        bottom = box.mapTo(viewport, box.rect().bottomLeft()).y()
        return 0 <= top and bottom <= viewport.height(), (top, bottom, viewport.height())

    def test_reopening_the_sheet_puts_the_first_field_inside_the_visible_body_at_every_small_size(self):
        for size in ((900, 560), (1093, 614), (1280, 720), (1366, 768)):
            with self.subTest(size=size):
                window, form = self.sheet(size=size)
                self.add_photos(form, *[fake_path(number) for number in range(1, 5)])
                self.assertEqual(window.photos_close(), "closed")
                self.settle(4)
                window, form = self.sheet(window)
                self.settle(4)
                box = form.rows["p001"].subject
                self.assertIs(QApplication.focusWidget(), box.edit)
                inside, where = self.visible_inside(form, box)
                self.assertTrue(inside, (size, where, "첫 포커스 칸이 몸 영역 밖이다"))
                window.close()

    def test_the_first_focus_is_brought_into_view_even_when_the_body_was_scrolled_away(self):
        window, form = self.sheet(size=(900, 560))
        self.add_photos(form, *[fake_path(number) for number in range(1, 7)])
        bar = form.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        form.add_button.setFocus(Qt.TabFocusReason)
        self.settle(3)
        box = form.rows["p001"].subject
        self.assertFalse(self.visible_inside(form, box)[0], "시험의 전제: 몸을 끝까지 내려 첫 칸이 밖에 있다")
        form.focus_start()
        self.settle(4)
        self.assertIs(QApplication.focusWidget(), box.edit)
        inside, where = self.visible_inside(form, box)
        self.assertTrue(inside, (where, "칸 전체(이름표·입력 칸·글자 수)가 보여야 한다"))

    def test_a_sheet_without_photos_starts_on_the_add_button_and_does_not_scroll(self):
        window, form = self.sheet(size=(900, 560))
        self.assertIs(QApplication.focusWidget(), form.add_button)
        self.assertEqual(form.scroll.verticalScrollBar().value(), 0)


class EnterOnRejectedTextTest(tq.PhotoBase):
    def test_enter_on_a_text_over_the_limit_stays_in_the_field_with_the_reason_and_a_fixed_text_moves_on(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2))
        first, second = form.rows["p001"], form.rows["p002"]
        first.note.edit.setFocus(Qt.TabFocusReason)
        first.note.edit.setText("나" * 301)
        QTest.keyClick(first.note.edit, Qt.Key_Return)
        self.settle(4)
        self.assertIs(QApplication.focusWidget(), first.note.edit, "받지 않은 글에서는 다음 칸으로 가지 않는다")
        self.assertEqual(board.photo("p001").user_note, "", "글은 규칙에 들어가지 않았다")
        self.assertTrue(first.note.error.isVisibleTo(form))
        self.assertIn("300", self.lt(first.note.error), "이유 문장이 칸 아래에 보인다")
        self.assertEqual(first.note.edit.text(), "나" * 301, "쳐 둔 글은 그대로다")
        first.note.edit.setText("나" * 300)
        QTest.keyClick(first.note.edit, Qt.Key_Return)
        self.settle(4)
        self.assertIs(QApplication.focusWidget(), second.subject.edit, "고쳐서 받아들여지면 다음 사진의 대상 칸으로 간다")
        self.assertEqual(board.photo("p001").user_note, "나" * 300)

    def test_enter_on_a_rejected_subject_stays_and_an_empty_subject_or_an_unchanged_one_still_moves_on(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        card.subject.edit.setFocus(Qt.TabFocusReason)
        card.subject.edit.setText("가" * 61)
        QTest.keyClick(card.subject.edit, Qt.Key_Return)
        self.settle(4)
        self.assertIs(QApplication.focusWidget(), card.subject.edit)
        self.assertEqual(board.photo("p001").user_subject, "")
        card.subject.edit.setText("")
        QTest.keyClick(card.subject.edit, Qt.Key_Return)
        self.settle(3)
        self.assertIs(QApplication.focusWidget(), card.note.edit, "바뀐 것이 없는(빈) 글은 그대로 다음 칸으로 간다")
        card.note.edit.setText("<b>굵게</b>")
        QTest.keyClick(card.note.edit, Qt.Key_Return)
        self.settle(4)
        self.assertIs(QApplication.focusWidget(), card.note.edit, "검사에 걸린 글(HTML 모양)도 그 칸에 머문다")
        self.assertEqual(board.photo("p001").user_note, "")
        self.assertTrue(card.note.error.isVisibleTo(form))


class ExampleTextContrastTest(tq.PhotoBase):
    @staticmethod
    def darkest(image):
        """칸 안쪽(테두리·여백을 뺀 곳)에서 가장 진한 점의 색 — 예시 글자의 색이다."""
        best, best_color = 2.0, None
        for y in range(8, image.height() - 8):
            for x in range(12, image.width() - 12):
                color = QColor(image.pixel(x, y))
                value = K.luminance(color.name())
                if value < best:
                    best, best_color = value, color.name()
        return best_color

    def test_the_example_text_uses_the_helper_text_color_and_reads_at_least_at_4_5_to_1(self):
        colors = theme.colors()
        self.assertGreaterEqual(K.contrast(colors["text_secondary"], colors["surface"]), 4.5, "보조 글 색(5.4:1)이 기준이다")
        qss = theme.build_qss(colors)
        self.assertRegex(qss, r"(?m)^QLineEdit \{[^}\n]*placeholder-text-color: " + colors["text_secondary"] + r";[^}\n]*\}$")      # 입력 칸 선택자는 시험이 정해진 목록으로 못박아 새 규칙을 더할 수 없다 — 주 규칙의 선언 하나다
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        for box in (form.rows["p001"].subject, form.rows["p001"].note):
            edit = box.edit
            self.assertEqual(edit.text(), "")
            self.assertTrue(edit.placeholderText())
            edit.clearFocus()
            self.settle(3)
            image = edit.grab().toImage()
            shown = self.darkest(image)
            self.assertGreaterEqual(K.contrast(shown, colors["surface"]), 4.5, (box.name, shown, "예시 글자의 대비가 4.5:1 에 못 미친다"))


if __name__ == "__main__":
    unittest.main()
