"""사진을 본문에 넣는 길의 화면 규칙(컨트롤러·가짜 공급자 — 사진 연동 3단계, 순수 층) 시험. 본문 생성기 쪽은 `test_content_photo_make`·`test_content_photo_flow` 가 본다.

지키는 것:
  1) 만들 때(`이 주제로 만들기`·`다시 만들기`) **확정한 사진만** 요청에 실린다. 요청에는 경로·파일 이름이 없고(`DraftPhoto`), 사진이 없거나 확정한 것이 없으면 요청·초안이 지금과 같다.
  2) 사진 정보 검사(`draft_inputs`)가 막으면 사진을 빼고 몰래 만들지 않고 고정 문장으로 멈춘다(공급자를 부르지 않는다).
  3) 만든 뒤 확정한 사진·자리·글이 달라지면 카드가 '다시 만들기' 를 안내하고(본문은 몰래 고치지 않는다), 다시 만들면 안내가 사라진다. 저장한 초안을 열면 연 순간의 사진을 기준으로 삼는다. 초안이 없으면 안내도 없다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_drafts_save_core import drive, made_saving, saved_id  # noqa: E402
from test_ui_photo_save_core import path_of  # noqa: E402
from test_ui_photo_save_core import store as store3  # noqa: E402

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.ui.core import drafts, text  # noqa: E402

T = text.T


def confirm(controller, number, **fields):
    """사진 하나의 글을 고치고(있으면) 확정한다."""
    photo_id = pm.photo_id_of(number)
    for name, value in fields.items():
        controller.photos.set_text(photo_id, name, value)
    controller.photos.confirm(photo_id, True)


class RequestTest(unittest.TestCase):
    def test_the_request_has_a_photos_field_that_defaults_to_nothing(self):
        self.assertEqual([item.name for item in dataclasses.fields(drafts.DraftRequest)], ["candidate_id", "blog", "post_type", "options", "photos"])
        self.assertEqual(drafts.DraftRequest("후보").photos, ())

    def test_the_draft_photo_value_has_no_path_or_photo_id_field(self):
        names = {item.name for item in dataclasses.fields(pm.DraftPhoto)}
        self.assertFalse(names & {"local_path", "photo_id", "analysis_method", "confirmed_by_user"}, names)


class MakeTest(unittest.TestCase):
    def test_only_confirmed_photos_ride_along_and_the_request_carries_no_path(self):
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1), path_of(2), path_of(3)])
        confirm(controller, 1, user_subject="매장 입구 간판", user_note="주차는 뒤쪽이에요")
        confirm(controller, 3)
        self.assertEqual(drive(controller), "started")
        request = provider.calls[-1]
        self.assertEqual([item.number for item in request.photos], [1, 3], "확정하지 않은 2번은 싣지 않는다")
        self.assertTrue(all(isinstance(item, pm.DraftPhoto) for item in request.photos))
        self.assertNotIn("UNIQ-", str(dataclasses.asdict(request)) + repr(request), "경로·파일 이름은 요청에 없다")
        self.assertEqual(sorted(number for number, _start, _end in pm.find_placeholders(controller.body)), [1, 3])
        self.assertIn("매장 입구 간판 사진이에요.", controller.body)
        self.assertIn("주차는 뒤쪽이에요", controller.body)
        self.assertNotIn("{{사진 2}}", controller.body)

    def test_without_confirmed_photos_the_request_and_the_draft_are_what_they_were(self):
        controller, provider = made_saving()
        first = (controller.title, controller.body, provider.calls[-1])
        self.assertEqual(first[2].photos, ())
        drive(controller)
        self.assertEqual((controller.title, controller.body), first[:2])
        controller.photos.add_paths([path_of(1), path_of(2)])
        drive(controller)
        self.assertEqual(provider.calls[-1].photos, (), "확정하지 않은 사진은 본문에 안 들어간다")
        self.assertEqual((controller.title, controller.body), first[:2])

    def test_the_text_unsaved_flag_and_the_regenerate_confirmation_ignore_the_photos(self):
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1)])
        confirm(controller, 1)
        self.assertFalse(controller.text_unsaved())
        self.assertEqual(controller.start_regenerate()[0], "started", "사진만 고쳤으면 다시 만들기에 확인창이 없다")

    def test_a_blocked_photo_check_stops_the_make_with_a_fixed_sentence_and_never_calls_the_provider(self):
        controller, provider = made_saving()
        calls, body = len(provider.calls), controller.body
        error = AppError("CONTENT_INVALID", {"항목": "사진"}, detail="UNIQ-DETAIL-비밀")
        with mock.patch("chanceblog_desktop.content.photo_manifest.draft_inputs", side_effect=error):
            self.assertEqual(drive(controller), "photos")
        self.assertEqual(controller.notice, ("error", T["pho_make_blocked"]))
        self.assertEqual((len(provider.calls), controller.body, controller.state), (calls, body, "normal"))
        self.assertNotIn("UNIQ-DETAIL", repr(controller.notice))


class RemakeNoteTest(unittest.TestCase):
    def note(self, controller):
        return controller.photos_card()["remake"]

    def test_the_card_asks_for_a_remake_only_after_the_confirmed_photos_changed_since_the_draft_was_made(self):
        controller, provider = made_saving()
        self.assertEqual(self.note(controller), "")
        controller.photos.add_paths([path_of(1), path_of(2)])
        self.assertEqual(self.note(controller), "", "확정하지 않은 사진은 본문에 안 들어가니 안내도 없다")
        confirm(controller, 1)
        self.assertEqual(self.note(controller), T["pho_card_remake"])
        drive(controller)
        self.assertEqual(self.note(controller), "", "다시 만들었다")
        controller.photos.set_text("p001", "user_note", "새 메모")
        self.assertEqual(self.note(controller), T["pho_card_remake"], "고치면 확정이 풀려 본문과 달라진다")
        drive(controller)
        self.assertEqual(self.note(controller), "")
        self.assertEqual(controller.photos_card()["unsaved"], T["pho_card_unsaved"], "저장 안내는 별개다(사진 정보를 고쳤는데 저장하지 않았다)")

    def test_reordering_or_removing_a_confirmed_photo_also_asks_for_a_remake(self):
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1), path_of(2)])
        confirm(controller, 1)
        confirm(controller, 2)
        drive(controller)
        self.assertEqual(self.note(controller), "")
        controller.photos.move("p002", -1)
        self.assertEqual(self.note(controller), T["pho_card_remake"])
        drive(controller)
        controller.photos.remove("p001")
        self.assertEqual(self.note(controller), T["pho_card_remake"])

    def test_no_note_without_a_draft_and_the_old_draft_text_is_never_touched(self):
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1)])
        confirm(controller, 1)
        body = controller.body
        self.assertEqual(self.note(controller), T["pho_card_remake"])
        self.assertEqual(controller.body, body, "본문은 몰래 고치지 않는다")
        controller.leave()
        self.assertEqual(self.note(controller), "")

    def test_an_opened_saved_draft_is_taken_as_made_with_its_own_photos_and_a_later_change_is_noted(self):
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1)])
        confirm(controller, 1)
        drive(controller)
        store3(controller, "save")
        draft_id = saved_id(provider)
        controller.leave()
        store3(controller, "open", draft_id)
        self.assertEqual(controller.photos.count, 1)
        self.assertEqual(self.note(controller), "", "연 순간의 사진을 기준으로 삼는다 — 열자마자 안내하지 않는다")
        controller.photos.set_text("p001", "user_note", "열고 나서 고침")
        self.assertEqual(self.note(controller), T["pho_card_remake"])


if __name__ == "__main__":
    unittest.main()
