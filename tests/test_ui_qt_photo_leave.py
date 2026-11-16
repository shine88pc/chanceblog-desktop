"""'사진 정리'(사진 연동 2단계, 결정 D-499)의 떠나기·닫기 확인과 못 넣은 파일 안내의 PySide6 시험(검증 Q 의 N-2·N-5 — 수정 지시 2).

지키는 것:
  1) 떠나기·앱 닫기(N-2) — 사진 정보는 저장하지 못해서(저장은 3단계) 사진이 하나라도 있으면 다른 화면으로 가거나 창을 닫기 전에 확인창이 먼저 뜬다. 처음 포커스는 취소이고, 취소하면 그대로(사진 그대로)이며,
     '그래도 이동/닫기' 를 눌러야 떠나고 사진 정보가 비워진다. 사진이 없으면 지금처럼 묻지 않는다.
  2) 넣지 못한 파일(N-5) — 하나라도 못 넣으면 상태 줄이 몇 개를 못 넣었는지와 어디서 이유를 보는지('아래 ‘넣지 못한 파일’')를 알리고, 그 목록이 보이는 자리로 스크롤한다. 같은 목록을 다시 그릴 때는 다시 스크롤하지 않는다.
`test_ui_qt_photo` 의 도구(`PhotoBase`)만 이어 쓰고 그 모듈의 시험은 가져오지 않는다. **PySide6 가 없으면 통째로 건너뛴다.**
"""
import unittest

import test_ui_qt_photo as tq

if tq.HAVE:
    from PySide6.QtWidgets import QApplication
    from chanceblog_desktop.ui.core import drafts

T = tq.T
fake_path = tq.fake_path


class LeaveWithPhotosTest(tq.PhotoBase):
    def with_photos(self, count=2):
        window, form = self.sheet()
        self.add_photos(form, *[fake_path(number) for number in range(1, count + 1)])
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        return window, window.state.drafts.photos

    def test_leaving_with_photos_asks_with_cancel_first_and_cancel_keeps_them_and_ok_leaves_and_clears_them(self):
        window, board = self.with_photos(2)
        window.nav_buttons["home"].click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual((window.state.page, QApplication.focusWidget().text(), board.count), ("drafts", "취소", 2))
        self.assertEqual(sorted(self.dialog_buttons(window)), ["그래도 이동", "취소"], "저장해도 사진 정보는 저장되지 않으므로 '저장' 갈래는 없다")
        shown = self.texts(window.dialog)
        self.assertIn("사진 정보가 사라져요", shown)
        self.assertTrue(any("넣어 둔 사진 2장의 정보는 아직 저장되지 않아서 다른 화면으로 가면 사라져요" in text for text in shown), shown)
        self.assertEqual((window.nav_buttons["drafts"].isChecked(), window.nav_buttons["home"].isChecked()), (True, False), "막힌 단추가 눌린 채로 남지 않는다")
        self.dialog_buttons(window)["취소"].click()
        self.settle(3)
        self.assertEqual((window.state.page, board.count, window.dialog.is_open), ("drafts", 2, False), "취소하면 그대로다")
        window.nav_buttons["home"].click()
        self.settle(3)
        self.dialog_buttons(window)["그래도 이동"].click()
        self.settle(4)
        self.assertEqual((window.state.page, board.count, window.state.drafts.state), ("home", 0, "empty"), "떠나면 사진 정보가 비워진다")

    def test_the_back_button_and_closing_the_window_ask_the_same_way_and_without_photos_nothing_is_asked(self):
        window, board = self.with_photos(1)
        self.button(window, "drf-back").click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.dialog_buttons(window)["취소"].click()
        self.settle(2)
        self.assertEqual((window.state.page, board.count), ("drafts", 1))
        self.assertFalse(window.close(), "사진 정보가 있으면 닫기를 막고 먼저 묻는다")
        self.settle(3)
        self.assertTrue(window.isVisible() and window.dialog.is_open)
        self.assertEqual(sorted(self.dialog_buttons(window)), ["그래도 닫기", "취소"])
        self.assertTrue(any("앱을 닫으면 사라져요" in text for text in self.texts(window.dialog)))
        self.dialog_buttons(window)["취소"].click()
        self.settle(3)
        self.assertTrue(window.isVisible())
        board.remove("p001")
        window.render()
        self.settle(3)
        self.assertIsNone(window.state.leave_guard("home"), "사진을 모두 지우면 묻지 않는다 — 사진이 없으면 지금과 같다")
        self.assertIsNone(window.state.close_guard())
        self.button(window, "drf-back").click()
        self.settle(3)
        self.assertEqual((window.dialog.is_open, window.state.page), (False, "topics"))
        self.assertFalse(window.state.drafts.photos_unsaved())

    def test_with_a_saving_provider_a_photo_only_question_has_no_save_choice_and_a_mixed_one_has_three_choices_and_the_photo_sentence(self):
        candidates = tq.qd.candidates_with(tq.GENERIC, tq.SOFTWARE, tq.APPLIANCE, tq.STOPPED, tq.OTHER_CHANNEL)
        provider = drafts.FakeDraftsProvider(lambda: tuple(candidates.candidates), saving=True)
        window = self.drafted(candidates=candidates, drafts_provider=provider)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1))
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        window.nav_buttons["home"].click()
        self.settle(3)
        self.assertEqual(sorted(self.dialog_buttons(window)), ["그래도 이동", "취소"], "저장해도 사진 정보는 저장되지 않으므로 '저장' 갈래는 없다")
        self.dialog_buttons(window)["취소"].click()
        self.settle(3)
        self.edit_body(window, chr(10) * 2 + "고친 문단이에요.")
        window.nav_buttons["home"].click()
        self.settle(3)
        self.assertEqual(sorted(self.dialog_buttons(window)), ["계속 고치기", "저장", "저장 안 하고 나가기"])
        self.assertTrue(any("넣어 둔 사진 1장의 정보도 저장되지 않고 사라져요" in text for text in self.texts(window.dialog)), self.texts(window.dialog))
        self.dialog_buttons(window)["계속 고치기"].click()
        self.settle(3)
        self.assertEqual((window.state.page, window.state.drafts.photos.count), ("drafts", 1))

    def test_the_photo_dialog_itself_closes_without_asking_and_the_card_still_warns_that_leaving_loses_them(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        self.assertFalse(window.dialog.is_open, "사진 정리 창을 닫는 것은 묻지 않는다 — 사진 목록은 남는다")
        self.assertEqual(window.state.drafts.photos.count, 1)
        self.assertIn(T["pho_card_unsaved"], self.texts(window.screen_widget))


class RejectedRevealTest(tq.PhotoBase):
    def test_files_that_could_not_be_added_are_announced_in_the_status_line_and_scrolled_into_view_once(self):
        window, form = self.sheet(size=(1366, 768))
        self.add_photos(form, *[fake_path(number) for number in range(1, 6)])
        scroll, bar = form.scroll, form.scroll.verticalScrollBar()
        bar.setValue(0)
        self.settle(2)
        self.assertFalse(form.rejected_host.isVisibleTo(form))

        def top_of_rejected():
            return form.rejected_host.mapTo(scroll.viewport(), form.rejected_host.rect().topLeft()).y()

        self.add_photos(form, fake_path(6, "gif"), fake_path(7, "bmp"))                  # 하나도 못 넣는 선택
        self.assertEqual(self.lt(form.notice), "고른 파일 2개를 넣지 못했어요 — 아래 ‘넣지 못한 파일’ 에서 이유를 확인해 주세요.")
        self.assertEqual(len(form.rows), 5)
        self.assertGreater(bar.value(), 0, "넣지 못한 파일 목록이 보이는 자리로 스크롤했다")
        self.assertTrue(0 <= top_of_rejected() < scroll.viewport().height(), f"목록의 위가 보이는 영역 안에 있다({top_of_rejected()}px)")
        bar.setValue(0)
        form.refresh()
        self.settle(4)
        self.assertEqual(bar.value(), 0, "같은 목록을 다시 그려도 다시 스크롤하지 않는다")
        bar.setValue(0)
        self.add_photos(form, fake_path(8), fake_path(9, "bmp"))                          # 일부만 넣는 선택
        self.assertEqual(self.lt(form.notice), "사진 1장을 넣었어요. 1개는 넣지 못했어요 — 아래 ‘넣지 못한 파일’ 에서 이유를 확인해 주세요.")
        self.assertGreater(bar.value(), 0, "다음 선택의 목록도 그 자리로 간다")
        self.assertTrue(0 <= top_of_rejected() < scroll.viewport().height())
        self.add_photos(form, fake_path(10))                                              # 다 넣으면 목록이 사라지고 안내는 지금과 같다
        self.assertFalse(form.rejected_host.isVisibleTo(form))
        self.assertEqual(self.lt(form.notice), "사진 1장을 넣었어요.")


if __name__ == "__main__":
    unittest.main()
