"""열 때 저장해 둔 사진 정보 파일이 깨졌거나(`broken`) 지금 못 열렸으면(`unreadable`) 그 초안의 사진 정보는 이 화면에서 저장하지 않는다 — **Qt 화면** 시험(PySide6, 검증 S PS-2·PS-11, 검증 Q PQ-11).
창을 화면에 띄우지 않고(offscreen) 가짜 공급자(메모리)로 한다 — 사용자의 파일·데이터 폴더·클립보드는 건드리지 않고, 사진 파일은 만들지도 읽지도 않는다(경로는 글자일 뿐).
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 규칙은 `test_ui_photo_save_core`·`test_ui_photo_save_service` 의 `UnsavablePhotoStateTest`·진짜 서비스 시험이 본다).

지키는 것:
  1) 그 상태에서 사진을 넣으면 카드에 '저장해 둔 사진 정보 파일을 … 저장되지 않아요' 안내가 보이고(상태별 문장) 일곱 크기에서 잘리거나 눌리지 않는다.
  2) `저장` 은 글만 저장하고(저장 요청에 사진 정보가 없다) 저장해 둔 사진 정보는 그대로이며 사진 정보 실패 알림이 아니다 — 저장한 뒤에도 '저장되지 않아요' 안내는 남는다.
  3) 떠나려 하면 사진 정보가 사라진다는 두 갈래 질문이 뜨고 `취소` 로 화면·사진 목록이 그대로다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_drafts_core import CATALOG  # noqa: E402
from test_ui_qt_drafts import HAVE, SIZES  # noqa: E402
from test_ui_qt_photo import fake_path  # noqa: E402
from test_ui_photo_save_core import before_the_question  # noqa: E402
from test_ui_qt_photo_save import Base  # noqa: E402

if HAVE:
    from test_ui_qt_drafts import ui_offscreen  # noqa: E402

from chanceblog_desktop.ui.core import drafts, text  # noqa: E402

T = text.T


class UnsavableOpen(drafts.FakeDraftsProvider):
    """저장한 초안을 열 때 사진 정보 파일이 깨졌거나(`broken`) 지금 못 열렸다(`unreadable`)고 알리는 가짜 공급자 — `opened_state` 가 `none` 이면 평소와 같다."""
    opened_state = "none"

    def open_saved(self, draft_id, progress, cancelled):
        opened = super().open_saved(draft_id, progress, cancelled)
        return opened if self.opened_state == "none" else dataclasses.replace(opened, photos=None, photos_state=self.opened_state)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class UnsavableStateTest(Base):
    STATES = ("broken", "unreadable")

    def reopened_as(self, state):
        """사진을 넣어 저장한 초안을 그 상태로 다시 연다 → `(창, 가짜 공급자, 초안 번호)`."""
        window, fake, draft_id = self.saved_with_photos(2, fake=UnsavableOpen(lambda: CATALOG, saving=True))
        window.state.drafts.leave()
        window.go("home")
        self.settle()
        self.open_list(window)
        fake.opened_state = state
        self.ui(window).saved_rows[0].open_button.click()
        self.assertTrue(self.wait_store(window))
        self.settle(4)
        self.assertEqual((window.state.drafts.saved_id, window.state.drafts.photos_state, window.state.drafts.photos.count), (draft_id, state, 0))
        return window, fake, draft_id

    def put_photo_in(self, window):
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(7))
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        return window

    def test_the_card_says_the_photo_info_is_not_saved_and_fits_every_size(self):
        for state in self.STATES:
            for size in SIZES:
                with self.subTest(state=state, size=size):
                    window, fake, draft_id = self.reopened_as(state)
                    window = self.put_photo_in(window)
                    window.resize(*size)
                    self.settle(8)
                    ui = self.ui(window)
                    self.assertTrue(ui.photos_unsaved.isVisibleTo(window.screen_widget), "저장되지 않는다는 지속 안내가 카드에 보인다")
                    self.assertEqual(ui.photos_unsaved.plain_text(), T["pho_card_lost_" + state])
                    self.assertEqual(ui_offscreen.find_clipping(window.screen_widget), [], size)
                    self.assertEqual(ui_offscreen.find_squeezed(window.screen_widget), [], size)
                    window.close()

    def test_saving_in_that_state_saves_only_the_text_and_never_the_photo_info(self):
        for state in self.STATES:
            with self.subTest(state=state):
                window, fake, draft_id = self.reopened_as(state)
                kept = fake.photo_files[draft_id]
                window = self.put_photo_in(window)
                self.press_save(window)
                controller = window.state.drafts
                self.assertEqual(controller.notice[0], "info", "사진 정보 실패(error)가 아니라 안내(info)다 — 저장을 시도하지도 않았고 글만 저장했다고 말한다(검증 S PS-15)")
                self.assertTrue(controller.notice[1].endswith(" · " + T["pho_saved_without_photos"]), "시각과 둘째 문장이 가운뎃점으로 갈린다(POLISH-1 PQ-26)")
                self.assertEqual(window.toast.property("level"), "info", "토스트에도 안내색 줄이 보인다(POLISH-1 PQ-25)")
                self.assertIsNone(fake.save_calls[-1].photos)
                self.assertIs(fake.photo_files[draft_id], kept, "저장해 둔 사진 정보는 그대로다")
                self.assertEqual(self.ui(window).photos_unsaved.plain_text(), T["pho_card_lost_" + state], "저장한 뒤에도 '저장되지 않아요' 안내가 남는다")
                window.close()

    def test_leaving_asks_that_the_photo_info_will_be_lost_and_staying_keeps_it(self):
        window, fake, draft_id = self.reopened_as("broken")
        window = self.put_photo_in(window)
        window.nav_buttons["home"].click()
        self.settle(3)
        self.assertEqual(sorted(self.dialog_buttons(window)), sorted([T["drf_leave_ok"], T["drf_cancel"]]), "글은 그대로이고 사진 정보는 저장할 길이 없다 — 두 갈래")
        expected = before_the_question(T["pho_leave_body"].format(n=1), T["pho_leave3_lost"])             # 초안은 있는데 저장할 길이 막혔다 — 이유 문장이 맨 끝 물음 앞에 있다(POLISH-1 PQ-24, 옛 시험은 `본문` 이 통째로 들어 있는지만 봤다)
        self.assertTrue(any(expected in line for line in self.texts(window.dialog)), self.texts(window.dialog))
        self.dialog_buttons(window)[T["drf_cancel"]].click()
        self.settle(3)
        self.assertEqual((window.state.page, window.state.drafts.photos.count), ("drafts", 1))
        window.close()


if __name__ == "__main__":
    unittest.main()
