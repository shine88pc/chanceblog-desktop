"""사진 연동 3단계(저장)·2단계 수정 묶음(WIP 11 — 치는 중인 글 넘기기)·블로그 후속(M080 — 별명·`&&`)이 만나는 곳의 PySide6 시험(offscreen). **PySide6 가 없으면 통째로 건너뛴다.**

지키는 것:
  1) **넘기는 순서** — 사진 정리 창에서 글을 치는 중(Enter·Tab 전)에 앱 닫기·떠나기 질문이 뜨면 질문이 창을 치우기 **전에** 그 글이 규칙에 넘어가고, 세 갈래 질문에서 `저장` 을 고르면 그 글이 사진 정보와 함께 저장된다(넘긴 뒤 묻고 저장한다).
  2) **블로그 이름이 바뀔 때 다시 그리기**(`shell._typing_would_be_lost` → `drafts.has_unsaved`) — 저장하지 않은 사진 정보가 있으면 다시 그리기를 미루고(입력을 안 잃는 쪽), 저장한 뒤에는 다시 그린다.
  3) **`&`** — 사용자가 더한 종류 이름에 `&` 가 있어도 칩에 글자 그대로 보인다(단축키 표시로 읽히지 않는다).
"""
import unittest
from unittest import mock

import test_ui_qt_photo_save as tqs
from test_ui_qt_photo import fake_path

if tqs.HAVE:
    from test_ui_qt_drafts import QAbstractButton, QTest, Qt, ui_offscreen

T = tqs.T


class InterplayTest(tqs.Base):
    TYPED = "typing now"

    def typing(self):
        fake = tqs.provider()
        window = self.drafted(drafts_provider=fake)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1))
        edit = form.rows["p001"].note.edit
        edit.setFocus(Qt.TabFocusReason)
        self.settle(1)
        QTest.keyClicks(edit, self.TYPED)
        controller = window.state.drafts
        self.assertEqual((edit.text(), controller.photos.photo("p001").user_note), (self.TYPED, ""), "시험의 전제: 글은 칸에만 있고 규칙에는 아직 안 넘어갔다")
        return window, fake, controller

    def saved_note(self, fake):
        self.assertEqual(len(fake.saved), 1, "초안이 하나 저장됐다")
        return fake.photo_files[next(iter(fake.saved))].photo("p001").user_note

    def test_the_app_close_question_hands_the_typed_text_over_first_and_save_stores_it_with_the_photo_info(self):
        window, fake, controller = self.typing()
        self.assertFalse(window.close(), "사진 정보가 저장되지 않았으니 닫기를 막고 먼저 묻는다")
        self.settle(3)
        buttons = self.dialog_buttons(window)
        self.assertEqual(list(buttons), [T["drf_choice_save"], T["drf_choice_discard_close"], T["drf_choice_stay"]], "저장 기능이 있으면 세 갈래")
        self.assertEqual(controller.photos.photo("p001").user_note, self.TYPED, "질문이 창을 치운 뒤가 아니라 질문이 뜨기 전에 넘어갔다")
        buttons[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: not window.isVisible(), 15), "저장을 마치면 이어서 닫힌다")
        self.assertEqual(self.saved_note(fake), self.TYPED, "치던 글이 사진 정보와 함께 저장됐다")

    def test_the_leave_question_hands_the_typed_text_over_first_and_save_stores_it_with_the_photo_info(self):
        window, fake, controller = self.typing()
        window.go("topics")
        self.settle(3)
        buttons = self.dialog_buttons(window)
        self.assertEqual(list(buttons), [T["drf_choice_save"], T["drf_choice_discard_leave"], T["drf_choice_stay"]])
        self.assertEqual(controller.photos.photo("p001").user_note, self.TYPED)
        buttons[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.page == "topics", 15))
        self.settle()
        self.assertEqual(self.saved_note(fake), self.TYPED)

    def test_staying_keeps_the_typed_text_and_discarding_leaves_without_saving_it(self):
        window, fake, controller = self.typing()
        window.go("topics")
        self.settle(3)
        self.dialog_buttons(window)[T["drf_choice_stay"]].click()
        self.settle(3)
        self.assertEqual((window.state.page, controller.photos.photo("p001").user_note, fake.saved), ("drafts", self.TYPED, {}), "계속 고치기 — 글은 보드에 남고 아무것도 저장하지 않았다")
        window.go("topics")
        self.settle(3)
        self.dialog_buttons(window)[T["drf_choice_discard_leave"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.page == "topics", 10))
        self.assertEqual(fake.saved, {}, "저장 안 하고 나가기 — 아무것도 저장하지 않았다")

    def test_the_blog_name_redraw_waits_while_photo_info_is_unsaved_and_runs_after_the_save(self):
        fake = tqs.provider()
        window = self.drafted(drafts_provider=fake)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1))
        self.assertEqual(window.photos_close(), "closed")
        self.settle(3)
        controller = window.state.drafts
        calls = []
        with mock.patch.object(window.state, "refresh_names", return_value=True), mock.patch.object(window, "render", side_effect=lambda *a, **k: calls.append("render")):
            self.assertEqual((controller.text_unsaved(), controller.photos_unsaved(), window._typing_would_be_lost()), (False, True, True))
            window._names_changed()
            self.assertEqual(calls, [], "사진 정보만 저장 전이어도 다시 그리기는 미뤄진다(입력을 안 잃는 쪽)")
        self.press_save(window)
        with mock.patch.object(window.state, "refresh_names", return_value=True), mock.patch.object(window, "render", side_effect=lambda *a, **k: calls.append("render")):
            self.assertEqual((controller.has_unsaved(), window._typing_would_be_lost()), (False, False))
            window._names_changed()
            self.assertEqual(calls, ["render"], "저장한 뒤에는 새 이름으로 다시 그린다")

    def test_a_custom_type_name_with_an_ampersand_shows_as_written_and_can_be_chosen(self):
        window = self.drafted()
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1))
        board = window.state.drafts.photos
        board.add_type("한식&분식")
        self.assertIn("한식&분식", board.types)
        form.refresh()
        self.settle(3)
        chips = [button for button in form.findChildren(QAbstractButton) if button.property("focus_key") == "pho:type:p001:한식&분식"]
        self.assertEqual(len(chips), 1)
        self.assertEqual(chips[0].text(), "한식&&분식", "&& 로 써야 Qt 가 한 글자 &로 그린다 — 단축키 표시로 읽히지 않는다")
        chips[0].click()
        self.settle(2)
        self.assertEqual(board.photo("p001").photo_type, "한식&분식")


if __name__ == "__main__":
    unittest.main()
