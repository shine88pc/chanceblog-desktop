"""사진 정보를 초안과 함께 저장하고, 지운 초안의 사진 정보를 되돌릴 사본에서 되돌리거나 비우는 **Qt 화면** 시험(PySide6, 사진 연동 3단계 — 운영자 확인 024).
창을 화면에 띄우지 않고(offscreen) 가짜 공급자(메모리)로 한다 — 사용자의 파일·데이터 폴더·클립보드는 건드리지 않고, 사진 파일은 만들지도 읽지도 않는다(경로는 글자일 뿐이고 미리보기는 가짜 그림이다).
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_photo_save_core`·`test_ui_photo_save_service`).

지키는 것:
  1) 사진 정보를 고치면 저장 상태 줄이 '저장한 뒤 고쳤어요' 로 바뀌고(글은 안 바뀌어도) 카드에 안내가 보이며, `저장` 한 번이 글과 사진 정보를 함께 저장하면 안내가 사라진다. 사진 정보만 고친 채 떠나려 하면 세 갈래 확인창이 먼저다.
  2) 지운 초안이 되살아나 열리면 카드에 되돌릴 사본의 안내와 두 단추가 보인다. `사진 정보 되돌리기` 는 사진 목록을 되살리고(지금 사진이 있으면 꺼지고 까닭을 글로 말한다), `사진 정보 사본 비우기` 는 확인창(처음 포커스는 `그만두기`)을 거친 뒤에만 사본을 지운다.
  3) 두 단추의 이름·크기·Tab 순서·포커스(작업이 도는 동안 두 단추가 꺼질 때와 끝난 뒤 같은 카드의 `사진 정리 열기` 로 — 마우스·Space·Enter 모두, `TrashFocusTest`)·모든 크기에서 잘림 없음. 실패하면 고정 문장으로 알리고 단추는 그대로다.
  4) 저장한 초안을 지우면 '사진 정보는 되돌릴 사본으로 남겨 뒀어요' 가 목록 알림에 함께 보인다.
  5) 새 셸 함수는 공급자·파일·네트워크를 직접 부르지 않고 컨트롤러만 부른다.
  6) `저장` 을 골라 나가려는데 사진 정보만 저장하지 못하면(다른 메뉴·`저장한 초안`·앱 닫기의 진짜 `window.close()`) 나가지도 닫히지도 않고 경고창이 먼저다(`LeaveWithFailedPhotoSaveTest`).
"""
import ast
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_drafts_core import CATALOG  # noqa: E402
from test_ui_qt_drafts import HAVE, QT_DIR, SIZES  # noqa: E402
from test_ui_qt_drafts_save import SaveBase, provider  # noqa: E402
from test_ui_qt_photo import DIR_MARK, FILE_MARK, PhotoBase, called_names, fake_path, methods_of  # noqa: E402

if HAVE:
    from test_ui_qt_drafts import QAbstractButton, QTest, Qt, ui_offscreen  # noqa: E402

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.ui.core import drafts, text, tokens  # noqa: E402

T = text.T


class HoldingRestore(drafts.FakeDraftsProvider):
    """사진 정보 되돌리기·사본 비우기가 시험이 문을 열어 줄 때까지 기다리는 가짜 공급자 — 시간에 기대지 않고 '도는 중' 을 확실히 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate, self.entered, self.holding, self.restore_calls, self.clear_calls = threading.Event(), threading.Event(), False, 0, 0

    def clear_photos_trash(self, draft_id, progress, cancelled):
        self.clear_calls += 1
        if self.holding:
            self.entered.set()
            if not self.gate.wait(30):
                raise AssertionError("시험이 문을 열어 주지 않았다")
        return super().clear_photos_trash(draft_id, progress, cancelled)

    def restore_photos(self, draft_id, progress, cancelled):
        self.restore_calls += 1
        if self.holding:
            self.entered.set()
            if not self.gate.wait(30):
                raise AssertionError("시험이 문을 열어 주지 않았다")
        return super().restore_photos(draft_id, progress, cancelled)


class HoldingFailingRestore(HoldingRestore):
    """되돌리기가 문 앞에서 기다렸다가 실패하는 가짜 공급자 — 실패해도 도는 동안 두 단추가 꺼졌던 것을 시간에 기대지 않고 본다."""

    def restore_photos(self, draft_id, progress, cancelled):
        self.restore_calls += 1
        self.entered.set()
        if not self.gate.wait(30):
            raise AssertionError("시험이 문을 열어 주지 않았다")
        raise drafts.DraftFailure(T["pho_restore_fail"], code="FILE_WRITE_FAILED", kind="io")


class FailingTrash(drafts.FakeDraftsProvider):
    """되돌리기·사본 비우기가 실패하는 가짜 공급자(고정 문장으로 알리는 길을 본다)."""

    def restore_photos(self, draft_id, progress, cancelled):
        raise drafts.DraftFailure(T["pho_restore_fail"], code="FILE_WRITE_FAILED", kind="io")

    def clear_photos_trash(self, draft_id, progress, cancelled):
        raise drafts.DraftFailure(T["pho_trash_clear_fail"], code="FILE_WRITE_FAILED", kind="io")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class Base(PhotoBase, SaveBase):
    def open_list(self, window):
        window.go("drafts")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.list_state == "ok", 10))
        self.settle()
        self.activate(window)

    def saved_with_photos(self, count=2, fake=None):
        """사진을 넣고 저장한 초안 → `(창, 가짜 공급자, 초안 번호)`."""
        fake = fake or provider()
        window = self.drafted(drafts_provider=fake)
        window, form = self.sheet(window)
        self.add_photos(form, *[fake_path(number) for number in range(1, count + 1)])
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        self.press_save(window)
        return window, fake, window.state.drafts.saved_id

    def deleted_and_back(self, count=2, fake=None):
        """사진을 넣어 저장한 초안을 목록에서 지우고(사진 정보는 되돌릴 사본으로) 같은 번호로 되살아난 초안을 연다 → `(창, 가짜 공급자, 초안 번호)`."""
        window, fake, draft_id = self.saved_with_photos(count, fake)
        draft = fake.saved[draft_id]
        window.state.drafts.leave()
        window.go("home")
        self.settle()
        self.open_list(window)
        self.ui(window).saved_rows[0].delete_button.click()
        self.settle(3)
        self.dialog_buttons(window)[T["drf_delete_ok"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.list_state == "ok" and not window.state.drafts.store_busy and not fake.saved, 10))
        self.settle()
        self.deleted_notice = window.state.drafts.list_notice
        fake.saved[draft_id] = draft                                                  # 백업에서 같은 번호로 되살아난 것처럼
        window.go("home")
        self.settle()
        self.open_list(window)
        self.ui(window).saved_rows[0].open_button.click()
        self.assertTrue(self.wait_store(window))
        self.settle(4)
        self.assertEqual(window.state.drafts.saved_id, draft_id)
        return window, fake, draft_id

    def trash_ui(self, window):
        ui = self.ui(window)
        return ui, ui.photos_trash_box, ui.photos_restore, ui.photos_clear


class SaveTest(Base):
    def test_a_photo_only_change_turns_the_status_to_changed_and_one_save_stores_both(self):
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        ui, controller = self.ui(window), window.state.drafts
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1), fake_path(2))
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        self.assertTrue(ui.photos_unsaved.isVisibleTo(window.screen_widget), "사진 정보를 고쳤는데 저장하지 않았다는 안내")
        self.assertIn("초안을 저장해야 사진 정보도 함께 저장돼요", ui.photos_unsaved.plain_text())
        self.assertFalse(controller.text_unsaved())
        self.press_save(window)
        self.assertEqual(len(fake.save_calls), 1)
        self.assertEqual([photo.photo_id for photo in fake.save_calls[0].photos.photos], ["p001", "p002"], "저장 요청에 사진 정보가 실렸다")
        self.assertEqual([photo.photo_id for photo in fake.photo_files[controller.saved_id].photos], ["p001", "p002"])
        self.assertFalse(ui.photos_unsaved.isVisibleTo(window.screen_widget), "함께 저장했으니 안내가 사라진다")
        self.assertEqual((controller.save_state(), self.saved_status(window)), ("saved", controller.save_vm()["text"]))
        window, form = self.sheet(window)
        form.rows["p001"].confirm_box.click()
        self.settle(3)
        window.photos_close()
        self.settle(3)
        self.assertEqual((controller.save_state(), self.saved_status(window)), ("changed", T["drf_state_changed"]), "글은 그대로인데 사진 정보만 고쳤다")
        self.assertTrue(ui.photos_unsaved.isVisibleTo(window.screen_widget))
        self.press_save(window)
        self.assertTrue(fake.photo_files[controller.saved_id].photo("p001").confirmed_by_user)
        self.assertEqual(controller.save_state(), "saved")

    def test_leaving_with_only_the_photo_info_changed_asks_with_three_choices(self):
        window, fake, draft_id = self.saved_with_photos()
        window, form = self.sheet(window)
        form.rows["p001"].confirm_box.click()
        self.settle(3)
        window.photos_close()
        self.settle(3)
        window.go("topics")
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(list(self.dialog_buttons(window)), [T["drf_choice_save"], T["drf_choice_discard_leave"], T["drf_choice_stay"]])
        self.assertEqual(window.state.page, "drafts")
        self.dialog_buttons(window)[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.page == "topics", 10))
        self.settle()
        self.assertTrue(fake.photo_files[draft_id].photo("p001").confirmed_by_user, "저장하고 나갔다 — 사진 정보도 함께")

    def test_a_failed_photo_save_keeps_the_note_and_says_so_while_the_text_is_saved(self):
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        ui, controller = self.ui(window), window.state.drafts
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1))
        window.photos_close()
        self.settle(3)
        fake.photo_fail = T["pho_save_fail"]                                          # 가짜 공급자는 사진 정보 저장 실패를 고정 문장으로 돌려준다
        self.press_save(window)
        self.assertEqual(len(fake.saved), 1, "글은 저장됐다")
        self.assertEqual(controller.notice[0], "error")
        self.assertTrue(controller.notice[1].startswith(T["pho_save_fail"]))
        self.assertTrue(ui.photos_unsaved.isVisibleTo(window.screen_widget), "저장하지 못했으니 안내가 남는다")
        self.assertEqual(controller.save_state(), "changed")
        fake.photo_fail = None
        self.press_save(window)
        self.assertEqual(controller.save_state(), "saved")
        self.assertEqual(len(fake.photo_files), 1)


class TrashTest(Base):
    def test_a_draft_without_a_trash_copy_has_no_trash_block(self):
        window, fake, draft_id = self.saved_with_photos()
        ui, box, restore, clear = self.trash_ui(window)
        self.assertFalse(box.isVisibleTo(window.screen_widget))
        self.assertNotIn(T["pho_card_trash"], self.texts(window.screen_widget))

    def test_deleting_a_saved_draft_with_photos_says_the_photo_info_was_kept_as_a_copy(self):
        window, fake, draft_id = self.deleted_and_back()
        self.assertEqual(self.deleted_notice, ("ok", T["drf_deleted_notice"] + " " + T["pho_deleted_trash"]))
        self.assertIn(draft_id, fake.photo_trash)
        self.assertNotIn(draft_id, fake.photo_files)

    def test_a_draft_that_comes_back_shows_the_copy_and_the_two_buttons_with_names_and_sizes(self):
        window, fake, draft_id = self.deleted_and_back()
        ui, box, restore, clear = self.trash_ui(window)
        self.assertTrue(box.isVisibleTo(window.screen_widget))
        self.assertIn(T["pho_card_trash"], self.texts(window.screen_widget))
        self.assertEqual((restore.text(), clear.text()), (T["pho_restore_btn"], T["pho_trash_clear_btn"]))
        self.assertEqual((restore.accessibleName(), clear.accessibleName()), (T["pho_restore_btn_a11y"], T["pho_trash_clear_btn_a11y"]))
        for button in (restore, clear):
            self.assertTrue(button.isEnabled() and button.isVisibleTo(window.screen_widget))
            self.assertGreaterEqual(button.height(), tokens.SIZE["hit"] - 8)
            self.assertNotEqual(button.focusPolicy(), Qt.NoFocus)
        self.assertFalse(ui.photos_restore_note.isVisibleTo(window.screen_widget), "사진이 없으니 되돌릴 수 있다 — 막는 안내가 없다")
        self.assertEqual(ui.stops[ui.stops.index(ui.photos_button) + 1:ui.stops.index(ui.photos_button) + 3], [restore, clear], "Tab 순서: 사진 정리 열기 다음에 두 단추")
        self.assertEqual(window.state.drafts.photos.count, 0)

    def test_restoring_brings_the_photo_list_back_moves_focus_to_the_card_button_and_tells_it(self):
        window, fake, draft_id = self.deleted_and_back()
        ui, box, restore, clear = self.trash_ui(window)
        self.activate(window)
        restore.setFocus(Qt.MouseFocusReason)                                          # 진짜 누름은 단추에 포커스를 준다(`click()` 은 안 준다)
        restore.click()
        self.assertTrue(self.wait_store(window))
        self.settle(3)
        controller = window.state.drafts
        self.assertEqual((controller.photos.count, controller.photos_trash, controller.photos_unsaved()), (2, False, False))
        self.assertEqual(controller.notice, ("ok", T["pho_restored_notice"]))
        self.assertTrue(window.toast.isVisible())
        self.assertEqual(window.toast.text(), T["pho_restored_notice"], "결과 알림이 토스트로 뜬다 — 앞의 안내가 남은 것이 아니다")
        self.assertFalse(box.isVisibleTo(window.screen_widget), "사본을 쓰고 났으니 줄이 사라진다")
        self.assertEqual(self.lt(ui.photos_count), "사진 2장 · 확인 0/2")
        self.assertEqual(ui.photos_button.text(), "사진 정리 열기")
        self.assertTrue(ui.photos_button.hasFocus(), "눌렀던 단추가 사라져도 포커스를 잃지 않는다")
        self.assertNotIn(draft_id, fake.photo_trash)
        self.assertEqual([photo.photo_id for photo in fake.photo_files[draft_id].photos], ["p001", "p002"])
        self.assertFalse(ui.photos_unsaved.isVisibleTo(window.screen_widget), "되돌린 것은 저장된 사진 정보 그대로다")

    def test_restore_is_off_with_a_reason_while_photos_are_in_the_draft_and_back_on_when_they_are_gone(self):
        window, fake, draft_id = self.deleted_and_back()
        ui, box, restore, clear = self.trash_ui(window)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(7))
        window.photos_close()
        self.settle(4)
        self.assertTrue(box.isVisibleTo(window.screen_widget))
        self.assertFalse(restore.isEnabled())
        self.assertTrue(ui.photos_restore_note.isVisibleTo(window.screen_widget))
        self.assertEqual(ui.photos_restore_note.plain_text(), T["pho_restore_blocked"], "꺼진 단추만 두지 않고 까닭을 글로 말한다")
        self.assertTrue(clear.isEnabled(), "사본 비우기는 사진이 있어도 된다")
        window, form = self.sheet(window)
        form.rows["p001"].remove.click()
        self.settle(3)
        window.photos_close()
        self.settle(3)
        self.assertTrue(restore.isEnabled())
        self.assertFalse(ui.photos_restore_note.isVisibleTo(window.screen_widget))

    def test_clearing_the_copy_asks_first_with_focus_on_cancel_and_clears_only_after_yes(self):
        window, fake, draft_id = self.deleted_and_back()
        ui, box, restore, clear = self.trash_ui(window)
        controller = window.state.drafts
        self.activate(window)
        clear.setFocus(Qt.MouseFocusReason)
        clear.click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        buttons = self.dialog_buttons(window)
        self.assertEqual(list(buttons), [T["pho_trash_clear_no"], T["pho_trash_clear_yes"]])
        self.assertTrue(buttons[T["pho_trash_clear_no"]].hasFocus(), "처음 포커스는 안전한 쪽(그만두기)")
        self.assertIn(T["pho_trash_clear_ask"], " ".join(self.texts(window.dialog)))
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle(3)
        self.assertEqual((window.dialog.is_open, controller.photos_trash, controller.trash_asked, draft_id in fake.photo_trash), (False, True, False, True), "Esc 는 그만두기와 같다")
        self.assertEqual(controller.start_clear_trash(), ("unconfirmed", None), "확인창을 거치지 않으면 지우지 않는다")
        clear.setFocus(Qt.MouseFocusReason)
        clear.click()
        self.settle(3)
        self.dialog_buttons(window)[T["pho_trash_clear_yes"]].click()
        self.assertTrue(self.wait_store(window))
        self.settle(3)
        self.assertEqual((controller.photos_trash, controller.notice), (False, ("ok", T["pho_trash_cleared_notice"])))
        self.assertNotIn(draft_id, fake.photo_trash)
        self.assertIn(draft_id, fake.saved, "초안은 그대로다")
        self.assertFalse(box.isVisibleTo(window.screen_widget))
        self.assertTrue(ui.photos_button.hasFocus())
        self.assertTrue(window.toast.isVisible())
        self.assertEqual(window.toast.text(), T["pho_trash_cleared_notice"], "사본을 비운 결과도 토스트로 알린다")

    def test_a_failed_restore_or_clear_says_it_in_a_fixed_sentence_and_keeps_the_buttons(self):
        fake = FailingTrash(lambda: CATALOG, saving=True)
        window, fake, draft_id = self.deleted_and_back(fake=fake)
        ui, box, restore, clear = self.trash_ui(window)
        controller = window.state.drafts
        restore.click()
        self.assertTrue(self.wait_store(window))
        self.settle(3)
        self.assertEqual(controller.notice, ("error", T["pho_restore_fail"]))
        self.assertEqual(window.toast.text(), T["pho_restore_fail"], "실패도 고정 문장으로 토스트에 알린다")
        self.assertTrue(box.isVisibleTo(window.screen_widget) and restore.isEnabled(), "다시 눌러 볼 수 있다")
        self.assertEqual(controller.photos.count, 0)
        clear.click()
        self.settle(3)
        self.dialog_buttons(window)[T["pho_trash_clear_yes"]].click()
        self.assertTrue(self.wait_store(window))
        self.settle(3)
        self.assertEqual(controller.notice, ("error", T["pho_trash_clear_fail"]))
        self.assertEqual(window.toast.text(), T["pho_trash_clear_fail"])
        self.assertTrue(box.isVisibleTo(window.screen_widget))
        self.assertIn(draft_id, fake.photo_trash)

    def test_while_a_job_runs_both_buttons_are_off_and_a_second_press_does_nothing(self):
        window, fake, draft_id = self.deleted_and_back(fake=HoldingRestore(lambda: CATALOG, saving=True))
        ui, box, restore, clear = self.trash_ui(window)
        controller = window.state.drafts
        fake.holding = True
        restore.click()
        self.assertTrue(fake.entered.wait(10), "되돌리기 작업이 시작됐다")
        self.settle(3)
        self.assertEqual((restore.isEnabled(), clear.isEnabled()), (False, False), "작업이 도는 동안 두 단추가 꺼진다")
        self.assertEqual(window.photos_restore(), "busy", "작업이 도는 동안의 두 번째 누름")
        fake.gate.set()
        self.assertTrue(self.wait_store(window))
        self.settle(3)
        self.assertEqual(fake.restore_calls, 1)
        self.assertEqual(controller.photos.count, 2)

    def test_the_trash_block_fits_every_size_without_clipping_or_sideways_scroll(self):
        for size in SIZES:
            with self.subTest(size=size):
                window, fake, draft_id = self.deleted_and_back(count=1)
                window.resize(*size)
                self.settle(8)
                ui, box, restore, clear = self.trash_ui(window)
                self.assertTrue(box.isVisibleTo(window.screen_widget))
                self.assertEqual(ui_offscreen.find_clipping(window.screen_widget), [], size)
                self.assertEqual(ui_offscreen.find_squeezed(window.screen_widget), [], size)
                for button in (restore, clear):
                    self.assertTrue(button.width() >= button.sizeHint().width() - 2, (size, button.text()))
                window.close()


class TrashFocusTest(Base):
    """되돌리기·사본 비우기를 누르면 작업이 도는 동안 두 단추가 꺼진다 — 그때 포커스는 오른쪽 칸의 엉뚱한 단추가 아니라 같은 카드의 `사진 정리 열기` 에 있고 끝난 뒤에도 거기 있다(검증 Q PQ-2).
    옛 시험은 작업이 단추를 끄기 전에 끝나 버리는 가짜 공급자의 우연에 기대어 통과했다 — 여기서는 작업이 문 앞에서 기다리게 해 '도는 동안' 을 본다. 마우스·Space·Enter 모두."""
    HOWS = ("mouse", "space", "enter")

    def held(self):
        return self.deleted_and_back(fake=HoldingRestore(lambda: CATALOG, saving=True))

    def focus_key(self):
        widget = self.app.focusWidget()
        return widget.property("focus_key") if widget is not None else None

    def press(self, window, button, how):
        self.activate(window)
        button.setFocus(Qt.TabFocusReason)
        self.settle(1)
        self.assertTrue(button.hasFocus(), "시험의 전제: 누르기 전에 그 단추에 포커스가 있다")
        if how == "mouse":
            button.setFocus(Qt.MouseFocusReason)
            button.click()
        else:
            QTest.keyClick(button, Qt.Key_Space if how == "space" else Qt.Key_Return)

    def test_restoring_keeps_the_focus_on_the_card_button_while_the_job_runs_and_after_it(self):
        for how in self.HOWS:
            with self.subTest(how=how):
                window, fake, draft_id = self.held()
                ui, box, restore, clear = self.trash_ui(window)
                fake.holding = True
                self.press(window, restore, how)
                self.assertTrue(fake.entered.wait(10), "되돌리기 작업이 시작됐다")
                self.settle(3)
                self.assertEqual((restore.isEnabled(), clear.isEnabled()), (False, False), "도는 동안 두 단추가 꺼진다")
                self.assertEqual(self.focus_key(), "drf-photos", "도는 동안 포커스가 같은 카드의 '사진 정리 열기' 에 있다(오른쪽 칸의 엉뚱한 단추가 아니다)")
                self.assertTrue(ui.photos_button.hasFocus())
                fake.gate.set()
                self.assertTrue(self.wait_store(window))
                self.settle(3)
                self.assertEqual((window.state.drafts.photos.count, box.isVisibleTo(window.screen_widget)), (2, False), "되돌렸고 사본 줄은 사라졌다")
                self.assertEqual(self.focus_key(), "drf-photos", "끝난 뒤에도 거기 있다")
                self.assertTrue(ui.photos_button.hasFocus())
                window.state.drafts.leave()
                window.close()

    def test_clearing_the_copy_keeps_the_focus_on_the_card_button_while_the_job_runs_and_after_it(self):
        for how in self.HOWS:
            with self.subTest(how=how):
                window, fake, draft_id = self.held()
                ui, box, restore, clear = self.trash_ui(window)
                self.press(window, clear, how)
                self.settle(3)
                self.assertTrue(window.dialog.is_open, "사본 비우기는 확인창이 먼저다")
                fake.holding = True
                if how == "mouse":
                    self.dialog_buttons(window)[T["pho_trash_clear_yes"]].click()
                else:
                    QTest.keyClick(self.app.focusWidget(), Qt.Key_Tab)                          # 처음 포커스 `그만두기` 에서 `사본 비우기` 로
                    self.settle(1)
                    self.assertEqual(self.app.focusWidget().text(), T["pho_trash_clear_yes"])
                    QTest.keyClick(self.app.focusWidget(), Qt.Key_Space if how == "space" else Qt.Key_Return)
                self.assertTrue(fake.entered.wait(10), "사본 비우기 작업이 시작됐다")
                self.settle(3)
                self.assertEqual((restore.isEnabled(), clear.isEnabled()), (False, False), "도는 동안 두 단추가 꺼진다")
                self.assertEqual(self.focus_key(), "drf-photos", "도는 동안 포커스가 같은 카드의 '사진 정리 열기' 에 있다")
                fake.gate.set()
                self.assertTrue(self.wait_store(window))
                self.settle(3)
                self.assertEqual((window.state.drafts.photos_trash, box.isVisibleTo(window.screen_widget), fake.clear_calls), (False, False, 1), "사본을 비웠고 줄은 사라졌다")
                self.assertEqual(self.focus_key(), "drf-photos", "끝난 뒤에도 거기 있다")
                window.state.drafts.leave()
                window.close()

    def test_a_refresh_moves_the_focus_only_when_the_button_that_has_it_goes_off(self):
        """사진이 생기면 되돌리기만 꺼진다(지금 사진을 덮어쓰지 않는다) — 포커스가 켜져 있는 `사본 비우기` 에 있으면 제자리이고, 꺼지는 `되돌리기` 에 있었다면 카드 단추로 간다."""
        window, fake, draft_id = self.deleted_and_back()
        ui, box, restore, clear = self.trash_ui(window)
        controller = window.state.drafts
        self.activate(window)
        clear.setFocus(Qt.TabFocusReason)
        self.settle(1)
        self.assertTrue(clear.hasFocus())
        controller.photos.add_paths([fake_path(7)])
        window.photos_card_refresh()
        self.settle(2)
        self.assertEqual((restore.isEnabled(), clear.isEnabled()), (False, True), "사진이 있으니 되돌리기만 꺼진다")
        self.assertTrue(clear.hasFocus(), "켜져 있는 단추의 포커스는 제자리다")
        controller.photos.remove("p001")
        window.photos_card_refresh()
        self.settle(2)
        self.assertEqual((restore.isEnabled(), clear.isEnabled()), (True, True))
        restore.setFocus(Qt.TabFocusReason)
        self.settle(1)
        self.assertTrue(restore.hasFocus())
        controller.photos.add_paths([fake_path(8)])
        window.photos_card_refresh()
        self.settle(2)
        self.assertEqual((restore.isEnabled(), ui.photos_button.hasFocus()), (False, True), "꺼지는 단추에 포커스가 있었다면 카드 단추로 간다")

    def test_after_a_failed_restore_the_buttons_are_back_and_the_focus_is_still_on_the_card_button(self):
        window, fake, draft_id = self.deleted_and_back(fake=HoldingFailingRestore(lambda: CATALOG, saving=True))
        ui, box, restore, clear = self.trash_ui(window)
        fake.holding = True
        self.press(window, restore, "space")
        self.assertTrue(fake.entered.wait(10))
        self.settle(3)
        self.assertEqual((restore.isEnabled(), clear.isEnabled(), self.focus_key()), (False, False, "drf-photos"), "도는 동안 두 단추가 꺼지고 포커스는 카드 단추에 있다")
        fake.gate.set()
        self.assertTrue(self.wait_store(window))
        self.settle(3)
        self.assertEqual(window.state.drafts.notice, ("error", T["pho_restore_fail"]))
        self.assertTrue(box.isVisibleTo(window.screen_widget) and restore.isEnabled() and clear.isEnabled(), "실패해도 단추는 다시 켜진다")
        self.assertEqual(self.focus_key(), "drf-photos", "포커스를 잃지 않는다 — 다시 누르려면 Tab 한 번")


class LeaveWithFailedPhotoSaveTest(Base):
    """`저장` 을 골라 나가려는데 **사진 정보만** 저장하지 못하면(검증 S PS-1·Q PQ-1) 나가지도 닫히지도 않고 경고창이 먼저다 — 그냥 나가면 고친 사진 정보가 조용히 사라진다(앱 닫기에서는 알림을 볼 수조차 없다).
    다른 메뉴·`저장한 초안`·앱 닫기(진짜 `window.close()`) 셋 모두 — 컨트롤러의 `photos_failed` 를 셸 `_after_save` 가 글 저장 실패와 같은 경고창으로 잇는다."""
    HOWS = ("topics", "saved_list", "close")

    def prepared(self):
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1), fake_path(2))
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        fake.photo_fail = T["pho_save_fail"]                                          # 사진 정보 저장만 실패한다(글 저장은 된다)
        return window, fake

    def ask(self, window, how):
        """나가기·닫기를 눌러 세 갈래 확인창을 연다 → 그 단추들."""
        if how == "topics":
            window.go("topics")
        elif how == "saved_list":
            self.button(window, "drf-saved-list").click()
        else:
            self.assertFalse(window.close(), "사진 정보가 저장되지 않았으니 닫기를 막고 먼저 묻는다")
        self.settle(3)
        buttons = self.dialog_buttons(window)
        self.assertEqual(list(buttons), [T["drf_choice_save"], T["drf_choice_discard_close" if how == "close" else "drf_choice_discard_leave"], T["drf_choice_stay"]])
        return buttons

    def warned(self, window, how):
        """세 갈래 창에서 `저장` 을 눌러 사진 정보 경고창이 뜰 때까지 → 경고창의 단추들."""
        self.ask(window, how)[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open and T["pho_savefail_leave_title"] in self.texts(window.dialog), 10), "경고창이 떠야 한다")
        self.settle()
        return self.dialog_buttons(window)

    def here(self, window, how):
        """아직 나가지도 닫히지도 않았다."""
        if how == "close":
            return window.isVisible()
        return window.state.page == "drafts" and window.state.drafts.state == "normal"

    def gone(self, window, how):
        if how == "close":
            return ui_offscreen.wait_until(self.app, lambda: not window.isVisible(), 10)
        if how == "topics":
            return ui_offscreen.wait_until(self.app, lambda: window.state.page == "topics", 10)
        return ui_offscreen.wait_until(self.app, lambda: window.state.drafts.state == "empty" and window.state.drafts.listing is not None, 10)

    def test_saving_to_leave_stops_with_a_warning_and_keep_editing_keeps_everything(self):
        for how in self.HOWS:
            with self.subTest(how=how):
                window, fake = self.prepared()
                controller, ui = window.state.drafts, self.ui(window)
                buttons = self.warned(window, how)
                closing = how == "close"
                self.assertEqual(list(buttons), [T["drf_choice_stay"], T["pho_choice_discard_close" if closing else "pho_choice_discard_leave"]])
                self.assertTrue(buttons[T["drf_choice_stay"]].hasFocus(), "처음 포커스는 계속 고치기")
                shown = " ".join(self.texts(window.dialog))
                self.assertIn(T["pho_save_fail"], shown)
                self.assertIn(T["pho_savefail_leave_tail"], shown)
                self.assertNotIn(T["drf_savefail_leave_tail"], shown, "글이 아니라 사진 정보의 경고다")
                self.assertTrue(self.here(window, how), "나가지도 닫히지도 않았다")
                self.assertEqual((len(fake.saved), len(fake.photo_files), controller.photos.count), (1, 0, 2), "글은 저장됐고 사진 정보는 못 저장했고 사진 목록은 그대로다")
                buttons[T["drf_choice_stay"]].click()
                self.settle(3)
                self.assertFalse(window.dialog.is_open)
                self.assertTrue(self.here(window, how))
                self.assertEqual((controller.photos.count, controller.photos_unsaved(), controller.leave_asked), (2, True, None), "사진 정보는 아직 저장되지 않았고 질문은 잊었다")
                self.assertTrue(ui.photos_unsaved.isVisibleTo(window.screen_widget), "카드의 '고쳤어요' 안내가 남아 있다")
                fake.photo_fail = None                                                       # 이제 사진 정보도 저장된다 — 같은 길로 다시 나가면 이번에는 나간다
                self.ask(window, how)[T["drf_choice_save"]].click()
                self.assertTrue(self.gone(window, how), "사진 정보도 저장돼 이번에는 나갔다")
                self.assertEqual(len(fake.photo_files), 1)
                window.state.drafts.leave()
                window.close()

    def test_leaving_anyway_after_the_warning_leaves_or_closes_and_the_photo_info_is_gone(self):
        for how in self.HOWS:
            with self.subTest(how=how):
                window, fake = self.prepared()
                buttons = self.warned(window, how)
                buttons[T["pho_choice_discard_close" if how == "close" else "pho_choice_discard_leave"]].click()
                self.assertTrue(self.gone(window, how), "경고를 읽고 그래도 나가겠다고 해서야 나갔다")
                self.assertEqual((len(fake.saved), len(fake.photo_files)), (1, 0), "글은 저장돼 있고 사진 정보는 저장되지 않았다(경고가 그렇게 말했다)")
                window.state.drafts.leave()
                window.close()

    def test_escape_on_the_warning_is_keep_editing(self):
        window, fake = self.prepared()
        self.warned(window, "topics")
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle(3)
        self.assertEqual((window.dialog.is_open, window.state.page, window.state.drafts.photos.count, window.state.drafts.leave_asked), (False, "drafts", 2, None))

    def test_the_photo_card_note_and_the_save_status_still_say_it_is_not_saved_behind_the_warning(self):
        window, fake = self.prepared()
        controller = window.state.drafts
        self.warned(window, "topics")
        self.assertEqual(controller.save_state(), "changed", "글은 저장됐지만 사진 정보 때문에 '저장한 뒤 고쳤어요'")
        self.assertEqual(self.saved_status(window), T["drf_state_changed"])
        self.assertTrue(self.ui(window).photos_unsaved.isVisibleTo(window.screen_widget))


class MakeAndCopyTest(Base):
    """본문 연결(다시 만들기에 사진 자리가 들어가고, 복사하면 `[이미지 N]` 이 되며, 확인창이 올릴 사진 순서를 알려 준다)."""

    def placed(self):
        """사진 둘을 넣고 확정한 창(아직 다시 만들지 않았다) → `(창, 가짜 공급자)`."""
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1), fake_path(2))
        self.commit(form.rows["p001"].subject.edit, "매장 입구 간판")
        for number in (1, 2):
            form.rows[f"p{number:03d}"].confirm_box.click()
            self.settle(3)
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        return window, fake

    def remake(self, window):
        window.drf_remake()
        self.assertTrue(self.wait_draft(window))
        self.settle(4)

    def test_the_card_asks_for_a_remake_and_the_remake_puts_the_slots_in_the_body_then_the_note_goes_away(self):
        window, _fake = self.placed()
        ui, controller = self.ui(window), window.state.drafts
        self.assertTrue(ui.photos_remake.isVisibleTo(window.screen_widget))
        self.assertEqual(ui.photos_remake.plain_text(), T["pho_card_remake"])
        self.assertNotIn("{{사진", ui.editor.toPlainText(), "본문은 몰래 고치지 않는다")
        self.remake(window)
        ui = self.ui(window)
        written = ui.editor.toPlainText()
        self.assertEqual(sorted(number for number, _start, _end in pm.find_placeholders(written)), [1, 2])
        self.assertIn("매장 입구 간판 사진이에요.", written)
        self.assertFalse(ui.photos_remake.isVisibleTo(window.screen_widget))
        self.assertEqual(controller.photos_card()["remake"], "")

    def test_copy_changes_the_slots_to_image_marks_and_the_dialog_lists_the_upload_order_without_a_path(self):
        window, _fake = self.placed()
        self.remake(window)
        self.button(window, "act:body").click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        shown = " ".join(self.texts(window.dialog))
        for number in (1, 2):
            self.assertIn(T["pho_gate_upload_line"].format(n=number, name=f"{FILE_MARK}-{number:02d}.jpg"), shown)
        self.assertIn(T["pho_gate_uploads"].format(n=2), shown)
        self.assertNotIn(DIR_MARK, shown, "경로는 확인창에도 없다")
        buttons = self.dialog_buttons(window)
        ok = buttons.get(T["drf_gate_ok"]) or buttons[T["pho_upload_ok"]]
        ok.click()
        self.settle(3)
        self.assertEqual(len(self.copied), 1)
        self.assertNotIn("{{", self.copied[0])
        self.assertIn("[이미지 1]", self.copied[0])
        self.assertIn("[이미지 2]", self.copied[0])
        self.assertEqual(self.copied[0], self.ui(window).editor.toPlainText().replace("{{사진 1}}", "[이미지 1]").replace("{{사진 2}}", "[이미지 2]"))
        self.button(window, "act:body").click()
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "한 번 확인했으면 같은 줄은 다시 묻지 않는다")
        self.assertEqual(len(self.copied), 2)
        self.button(window, "act:title").click()
        self.settle(3)
        self.assertFalse({T["pho_gate_uploads"].format(n=2)} & set(self.texts(window.dialog)) if window.dialog.is_open else set(), "제목 복사에는 사진 줄이 없다")

    def test_a_copy_with_a_mismatch_lists_numbers_only(self):
        window, _fake = self.placed()
        self.remake(window)
        window, form = self.sheet(window)
        form.rows["p002"].remove.click()
        self.settle(3)
        window.photos_close()
        self.settle(3)
        self.button(window, "act:body").click()
        self.settle(3)
        shown = " ".join(self.texts(window.dialog))
        self.assertIn(T["pho_gate_dangling"].format(numbers="2"), shown)
        self.assertNotIn(FILE_MARK, shown, "어긋남은 번호로만 알린다")
        self.assertEqual(self.copied, [], "확인하기 전에는 복사하지 않는다")

    def test_a_remake_that_the_photo_check_blocks_shows_the_notice_and_keeps_the_body(self):
        window, _fake = self.placed()
        controller = window.state.drafts
        body = controller.body
        error = AppError("CONTENT_INVALID", {"항목": "사진"}, detail="비밀-내용")
        with mock.patch("chanceblog_desktop.content.photo_manifest.draft_inputs", side_effect=error):
            window.drf_remake()
            self.settle(4)
        self.assertEqual(controller.notice, ("error", T["pho_make_blocked"]))
        self.assertEqual(controller.body, body)
        self.assertIn(T["pho_make_blocked"], self.texts(window.screen_widget))
        self.assertNotIn("비밀-내용", " ".join(self.texts(window.screen_widget)))


class SourceRulesTest(unittest.TestCase):
    NEW = ("photos_restore", "photos_trash_clear", "_photos_trash_clear_confirmed", "_photos_after_store", "photos_card_refresh")

    def test_the_new_shell_functions_only_call_the_controller(self):
        shell = QT_DIR / "shell.py"
        forbidden = {"restore_photos", "clear_photos_trash", "trash_manifest", "restore_manifest", "clear_trash", "open", "write", "write_text", "unlink", "rename", "replace", "urlopen", "run", "system"}
        for name in self.NEW:
            functions = methods_of(shell, "AppShell")
            self.assertIn(name, functions, name)
            calls = called_names(functions[name])
            self.assertEqual(sorted(calls & forbidden), [], f"{name} 가 직접 파일·공급자를 부른다")
        allowed_controller = {"start_restore_photos", "trash_clear_dialog", "start_clear_trash", "photos_card", "notify", "photos_card_refresh", "_live_drafts", "callbacks", "show_dialog"}
        for name in ("photos_restore", "photos_trash_clear", "_photos_trash_clear_confirmed"):
            calls = called_names(methods_of(shell, "AppShell")[name])
            self.assertTrue(calls & {"start_restore_photos", "trash_clear_dialog", "start_clear_trash"}, name)
            self.assertLessEqual({call for call in calls if call.startswith(("start_", "apply_", "trash_"))}, allowed_controller, name)

    def test_the_draft_screen_part_has_no_file_network_or_provider_calls(self):
        source = (QT_DIR / "draft_screen.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        for forbidden in ("restore_photos", "clear_photos_trash", "trash_manifest", "urlopen", "subprocess", "socket"):
            self.assertNotIn(forbidden, names, forbidden)


if __name__ == "__main__":
    unittest.main()
