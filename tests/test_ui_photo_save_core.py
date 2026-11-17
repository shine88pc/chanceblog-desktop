"""사진 정보를 초안과 함께 저장하고 열고 지우는 화면 규칙(사진 연동 3단계 — 순수 층: `ui/core/drafts_view.py`·`drafts.py` 의 가짜 공급자, 운영자 확인 024) — PySide6 없이 돈다(CI 와 같은 조건).
실제 서비스와의 연결은 `test_ui_photo_save_service` 가 본다.

지키는 것:
  1) 사진 정보는 **저장한 판과 다를 때만** 저장 요청에 실리고(사진을 한 번도 안 만졌으면 `None` — 사진 정보를 건드리지 않는다), 저장하면 그 목록이 저장한 판이 된다. 저장하지 못했으면 '고쳤어요' 가 남는다.
  2) 사진 정보만 고쳐도 저장 상태가 '저장한 뒤 고쳤어요(changed)' 이고 떠나기·닫기 앞에서 묻는다. 다시 만들기 확인은 글만 본다(사진 목록은 다시 만들어도 남는다).
  3) 저장한 초안을 열면 사진 목록이 채워지고(깨졌거나 지금 못 열면 안내만 — 덮어쓰지 않는다) 되돌릴 사본이 있으면 알린다.
  4) 저장한 초안을 지우면 사진 정보는 되돌릴 사본으로 남고 그렇게 말한다(옮기지 못했으면 그것도 말한다).
  5) 되살린 초안에서 `사진 정보 되돌리기`(지금 사진이 있으면 안 한다)·`사진 정보 사본 비우기`(확인창을 먼저 — 비우면 되돌릴 수 없다)가 말한 대로 움직인다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_drafts_save_core import drive, made_saving, saved_id  # noqa: E402

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.ui.core import drafts, text  # noqa: E402

T = text.T
OPS = {"save": ("start_save", "apply_saved", "apply_save_failed"), "list": ("start_list", "apply_listing", "apply_list_failed"), "open": ("start_open_saved", "apply_opened", "apply_open_failed"), "delete": ("start_delete", "apply_deleted", "apply_delete_failed"),
       "restore": ("start_restore_photos", "apply_photos_restored", "apply_restore_photos_failed"), "clear": ("start_clear_trash", "apply_trash_cleared", "apply_clear_trash_failed")}


def store(controller, op, *args, **kwargs):
    starter, ok, failed = (getattr(controller, name) for name in OPS[op])
    results = {}
    status, job = starter(*args, on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure), **kwargs)
    if job is not None:
        job.join(30)
    if "ok" in results:
        return status, ok(results["ok"])
    if "failed" in results:
        return status, failed(results["failed"])
    return status, None


def path_of(number):
    return f"C:/Users/UNIQ-USERDIR-s3x1/Pictures/UNIQ-FILE-s3x1-{number:02d}.jpg"


def confirm(controller, number, **fields):
    """사진 하나의 글을 고치고(있으면) 확정한다(`test_ui_photo_make_core.confirm` 과 같다 — 그 모듈이 이 모듈을 가져오므로 여기에 따로 둔다)."""
    photo_id = pm.photo_id_of(number)
    for name, value in fields.items():
        controller.photos.set_text(photo_id, name, value)
    controller.photos.confirm(photo_id, True)


def with_photos(count=2):
    controller, provider = made_saving()
    controller.photos.add_paths([path_of(number) for number in range(1, count + 1)])
    return controller, provider


def delete(controller, draft_id):
    """목록을 읽고 확인창을 거쳐 지운다 → `(시작 상태, 적용 결과)`."""
    store(controller, "list")
    controller.delete_dialog(draft_id)
    return store(controller, "delete")


def deleted_and_back(controller, provider):
    """저장한 초안을 지웠다가(사진 정보는 되돌릴 사본으로) 같은 번호로 되살린 초안을 연 상태 — 되살림은 백업에서 같은 번호로 다시 생기는 것이다."""
    draft_id = saved_id(provider)
    draft = provider.saved[draft_id]
    delete(controller, draft_id)
    provider.saved[draft_id] = draft
    controller.leave()
    store(controller, "open", draft_id)
    return draft_id


class SaveTest(unittest.TestCase):
    def test_photos_ride_along_only_when_they_differ_from_the_saved_ones(self):
        controller, provider = made_saving()
        self.assertFalse(controller.photos_unsaved())
        self.assertIsNone(controller._save_request().photos, "사진을 안 만졌으면 사진 정보는 건드리지 않는다")
        controller.photos.add_paths([path_of(1), path_of(2)])
        self.assertTrue(controller.photos_unsaved() and controller.has_unsaved())
        self.assertEqual(controller.save_state(), "unsaved")
        status, applied = store(controller, "save")
        self.assertEqual((status, applied[0]), ("started", "saved"))
        self.assertEqual(provider.save_calls[-1].photos, controller.photos.manifest)
        self.assertIn(saved_id(provider), provider.photo_files)
        self.assertEqual((controller.photos_unsaved(), controller.save_state()), (False, "saved"))
        store(controller, "save")
        self.assertIsNone(provider.save_calls[-1].photos, "그 사이 안 고쳤으면 다시 싣지 않는다")

    def test_changing_only_the_photos_after_a_save_is_a_change_and_saves_only_them_again(self):
        controller, provider = made_saving()
        store(controller, "save")
        self.assertIsNone(provider.save_calls[-1].photos)
        self.assertNotIn(saved_id(provider), provider.photo_files)
        controller.photos.add_paths([path_of(1)])
        self.assertEqual((controller.text_unsaved(), controller.photos_unsaved(), controller.save_state()), (False, True, "changed"))
        self.assertIsNotNone(controller.leave_dialog(), "사진 정보만 고쳐도 떠나기 앞에서 묻는다")
        controller.discard_leave() if hasattr(controller, "discard_leave") else None
        store(controller, "save")
        self.assertEqual(provider.photo_files[saved_id(provider)].photos[0].photo_id, "p001")
        self.assertEqual(controller.save_state(), "saved")
        controller.photos.remove("p001")
        self.assertEqual(controller.save_state(), "changed")
        store(controller, "save")
        self.assertEqual(provider.photo_files[saved_id(provider)].photos, (), "다 지운 것도 저장한다")

    def test_a_failed_photo_save_keeps_the_photos_marked_as_unsaved_and_says_so(self):
        controller, provider = with_photos()
        provider.photo_fail = T["pho_save_fail"]
        status, applied = store(controller, "save")
        self.assertEqual(applied[0], "saved", "글은 저장됐다")
        self.assertEqual(controller.notice, ("error", T["pho_save_fail"]))
        self.assertTrue(controller.photos_unsaved())
        self.assertEqual(controller.save_state(), "changed")
        provider.photo_fail = None
        store(controller, "save")
        self.assertEqual((controller.photos_unsaved(), controller.save_state()), (False, "saved"))

    def test_remaking_the_draft_makes_it_a_new_draft_so_the_photos_are_unsaved_again(self):
        controller, provider = with_photos()
        store(controller, "save")
        self.assertFalse(controller.photos_unsaved())
        self.assertIsNone(controller.regen_dialog(), "다시 만들기 확인은 글만 본다")
        drive(controller)
        self.assertIsNone(controller.saved_id)
        self.assertTrue(controller.photos_unsaved(), "새 초안이라 사진 정보도 아직 저장하지 않았다")
        self.assertEqual(controller.photos.count, 2, "사진 목록은 다시 만들어도 남는다")

    def test_photos_do_not_make_a_text_edit_and_text_edits_do_not_touch_the_photos(self):
        controller, provider = with_photos()
        store(controller, "save")
        controller.set_body(controller.body + " 고침")
        self.assertEqual((controller.text_unsaved(), controller.photos_unsaved()), (True, False))
        store(controller, "save")
        self.assertIsNone(provider.save_calls[-1].photos)
        self.assertEqual(len(provider.photo_files[saved_id(provider)].photos), 2)


class DifferenceTest(unittest.TestCase):
    def test_adding_and_removing_every_photo_in_a_draft_with_no_saved_photo_info_is_not_a_change(self):
        """저장한 사진 정보가 없는 글에서 사진을 넣었다 모두 지우면 저장할 것이 없다 — 안내·확인창·저장 요청이 모두 없다(서비스도 빈 목록은 파일을 만들지 않는다)."""
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1), path_of(2)])
        self.assertTrue(controller.photos_unsaved())
        controller.photos.remove("p001")
        controller.photos.remove("p002")
        self.assertEqual(controller.photos.manifest.next_number, 3, "번호 예약은 메모리에 남는다")
        self.assertEqual((controller.photos_unsaved(), controller.has_unsaved(), controller.photos_card()["unsaved"]), (False, False, ""))
        self.assertIsNone(controller._save_request().photos)

    def test_with_a_saved_photo_info_the_number_reservation_still_counts_as_a_change(self):
        """저장한 판이 있으면 번호 예약까지 견준다 — 사진을 넣었다 지워도 저장해야 지운 번호를 새 사진이 물려받지 않는다."""
        controller, provider = with_photos(2)
        store(controller, "save")
        self.assertFalse(controller.photos_unsaved())
        controller.photos.add_paths([path_of(3)])
        controller.photos.remove("p003")
        self.assertEqual([photo.photo_id for photo in controller.photos.manifest.photos], ["p001", "p002"])
        self.assertTrue(controller.photos_unsaved(), "사진 목록은 같지만 다음 번호(4)가 달라졌다")
        store(controller, "save")
        self.assertEqual(provider.photo_files[saved_id(provider)].next_number, 4)
        self.assertFalse(controller.photos_unsaved())


class OpenTest(unittest.TestCase):
    def test_opening_a_saved_draft_fills_the_photo_list_and_it_is_not_unsaved(self):
        controller, provider = with_photos(3)
        store(controller, "save")
        draft_id = saved_id(provider)
        controller.leave()
        self.assertEqual(controller.photos.count, 0)
        status, applied = store(controller, "open", draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(controller.photos.count, 3)
        self.assertEqual((controller.photos_unsaved(), controller.has_unsaved(), controller.photos_state, controller.photos_trash), (False, False, "ok", False))
        self.assertEqual(controller.photos_card()["count"], "사진 3장 · 확인 0/3")

    def test_a_draft_without_photo_info_opens_with_an_empty_list(self):
        controller, provider = made_saving()
        store(controller, "save")
        controller.leave()
        store(controller, "open", saved_id(provider))
        self.assertEqual((controller.photos.count, controller.photos_state, controller.photos_unsaved()), (0, "none", False))
        self.assertIsNone(controller.photos_card()["trash"])

    def test_a_broken_or_unreadable_photo_file_is_noted_and_the_list_stays_empty(self):
        for state, sentence in (("broken", T["pho_open_broken"]), ("unreadable", T["pho_open_unreadable"])):
            with self.subTest(state=state):
                controller, provider = made_saving()
                store(controller, "save")
                draft_id = saved_id(provider)
                controller.leave()
                original = provider.open_saved
                provider.open_saved = lambda *args, original=original, state=state: dataclasses.replace(original(*args), photos=None, photos_state=state)
                store(controller, "open", draft_id)
                self.assertIn(sentence, controller.notice[1])
                self.assertEqual((controller.photos.count, controller.photos_state), (0, state))
                self.assertFalse(controller.photos_unsaved())


class LyingProviderTest(unittest.TestCase):
    def test_a_manifest_that_comes_with_a_state_other_than_ok_is_never_loaded(self):
        """공급자가 사진 정보를 실어 보내면서 상태를 `ok` 가 아니라고 해도 컨트롤러는 목록을 채우지 않는다(상태가 먼저다 — 깨진 파일 위에 저장하지 않게)."""
        for state in ("broken", "unreadable", "none"):
            with self.subTest(state=state):
                controller, provider = with_photos(2)
                store(controller, "save")
                draft_id = saved_id(provider)
                controller.leave()
                original = provider.open_saved
                provider.open_saved = lambda *args, original=original, state=state: dataclasses.replace(original(*args), photos_state=state)
                store(controller, "open", draft_id)
                self.assertEqual((controller.photos.count, controller.photos_state, controller.photos_baseline), (0, state, None))


class DeleteAndRestoreTest(unittest.TestCase):
    def test_deleting_a_saved_draft_keeps_the_photo_info_as_a_restorable_copy_and_says_so(self):
        controller, provider = with_photos()
        store(controller, "save")
        draft_id = saved_id(provider)
        controller.leave()
        status, applied = delete(controller, draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertNotIn(draft_id, provider.photo_files)
        self.assertEqual(len(provider.photo_trash[draft_id].photos), 2)
        self.assertEqual(controller.list_notice, ("ok", T["drf_deleted_notice"] + " " + T["pho_deleted_trash"]))

    def test_a_draft_with_no_photo_info_says_nothing_about_a_copy(self):
        controller, provider = made_saving()
        store(controller, "save")
        draft_id = saved_id(provider)
        controller.leave()
        delete(controller, draft_id)
        self.assertEqual((controller.list_notice, provider.photo_trash), (("ok", T["drf_deleted_notice"]), {}))

    def test_a_copy_that_could_not_be_made_is_reported_as_an_error(self):
        controller, provider = with_photos()
        store(controller, "save")
        draft_id = saved_id(provider)
        controller.leave()
        provider.delete_saved = lambda draft, progress, cancelled: (provider.saved.pop(draft), drafts.DeletedOutcome(draft, "failed"))[1]
        delete(controller, draft_id)
        self.assertEqual(controller.list_notice, ("error", T["drf_deleted_notice"] + " " + T["pho_deleted_trash_fail"]))

    def test_a_draft_that_comes_back_shows_the_copy_and_restoring_fills_the_photos(self):
        controller, provider = with_photos()
        store(controller, "save")
        draft_id = deleted_and_back(controller, provider)
        self.assertEqual((controller.photos_trash, controller.photos.count), (True, 0))
        card = controller.photos_card()
        self.assertEqual(card["trash"]["restore"], "사진 정보 되돌리기")
        self.assertTrue(card["trash"]["restore_enabled"])
        status, applied = store(controller, "restore")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((controller.photos.count, controller.photos_trash, controller.photos_unsaved(), controller.photos_state), (2, False, False, "ok"))
        self.assertEqual(controller.notice, ("ok", T["pho_restored_notice"]))
        self.assertIn(draft_id, provider.photo_files)
        self.assertNotIn(draft_id, provider.photo_trash)
        self.assertIsNone(controller.photos_card()["trash"])

    def test_restoring_never_overwrites_the_photos_that_are_there_now(self):
        controller, provider = with_photos()
        store(controller, "save")
        deleted_and_back(controller, provider)
        controller.photos.add_paths([path_of(9)])
        self.assertFalse(controller.photos_card()["trash"]["restore_enabled"], "지금 사진이 있으면 되돌리기는 꺼진다")
        self.assertEqual(controller.start_restore_photos(), ("occupied", None))
        self.assertEqual(controller.photos.count, 1)
        controller.photos.remove("p001")
        self.assertEqual(controller.start_restore_photos()[0], "started")

    def test_a_missing_copy_hides_the_button_and_says_so(self):
        controller, provider = with_photos()
        store(controller, "save")
        deleted_and_back(controller, provider)
        provider.photo_trash.clear()                                                   # 그 사이 사본이 사라졌다
        status, applied = store(controller, "restore")
        self.assertEqual(applied, "notfound")
        self.assertEqual((controller.photos_trash, controller.notice), (False, ("error", T["pho_restore_missing"])))

    def test_restoring_is_not_offered_without_a_copy_or_for_a_draft_that_is_not_saved(self):
        controller, provider = with_photos()
        self.assertEqual(controller.start_restore_photos(), ("unavailable", None))
        store(controller, "save")
        self.assertEqual(controller.start_restore_photos(), ("unavailable", None))
        self.assertIsNone(controller.trash_clear_dialog())

    def test_clearing_the_copy_asks_first_and_removes_only_the_copy(self):
        controller, provider = with_photos()
        store(controller, "save")
        draft_id = deleted_and_back(controller, provider)
        self.assertEqual(controller.start_clear_trash(), ("unconfirmed", None), "확인창을 안 보였다")
        dialog = controller.trash_clear_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), ("사진 정보 사본 비우기", "사본 비우기", "그만두기"))
        self.assertIn("비우면 사진 정보를 되돌릴 수 없어요", dialog["body"])
        controller.discard_trash_clear()
        self.assertEqual(controller.start_clear_trash(), ("unconfirmed", None), "그만뒀으면 다시 물어야 한다")
        controller.trash_clear_dialog()
        status, applied = store(controller, "clear")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((controller.photos_trash, controller.notice), (False, ("ok", T["pho_trash_cleared_notice"])))
        self.assertEqual(provider.photo_trash, {})
        self.assertIn(draft_id, provider.saved, "초안은 그대로다")

    def test_a_failed_clear_says_so_and_keeps_the_button_unless_the_copy_is_gone(self):
        controller, provider = with_photos()
        store(controller, "save")
        deleted_and_back(controller, provider)
        controller.trash_clear_dialog()
        provider.photo_trash.clear()
        status, applied = store(controller, "clear")
        self.assertEqual((applied, controller.photos_trash, controller.notice), ("notfound", False, ("error", T["pho_trash_clear_fail"])))


def opened_with_state(state, photos=2):
    """저장한 초안을 사진 정보 파일이 깨졌거나(`broken`) 지금 못 열린(`unreadable`) 상태로 연다 — 사진 목록은 비어 있고 저장해 둔 파일(가짜 공급자의 `photo_files`)은 그대로다."""
    controller, provider = with_photos(photos)
    store(controller, "save")
    draft_id = saved_id(provider)
    controller.leave()
    original = provider.open_saved
    provider.open_saved = lambda *args, original=original, state=state: dataclasses.replace(original(*args), photos=None, photos_state=state)
    store(controller, "open", draft_id)
    return controller, provider, draft_id


class UnsavablePhotoStateTest(unittest.TestCase):
    """열 때 저장해 둔 사진 정보 파일이 깨졌거나 지금 못 열었으면 이 화면은 그 초안의 사진 정보를 **저장하지 않는다**(검증 S PS-2 — 잠금이 풀린 뒤 멀쩡한 파일을 소리 없이 덮던 길, D-501 ② '그 위에 저장하지 않는다').
    저장을 시도조차 안 하므로 '다시 저장해 보세요' 가 아무리 해도 안 풀리는 일(PS-11·PQ-11)도 없고, 카드·떠나기 질문이 사실대로 '저장되지 않아요' 라고 말한다."""
    STATES = (("broken", "pho_card_lost_broken"), ("unreadable", "pho_card_lost_unreadable"))

    def test_photos_put_in_that_state_are_not_in_the_save_request_and_nothing_is_saved_for_them(self):
        for state, card_key in self.STATES:
            with self.subTest(state=state):
                controller, provider, draft_id = opened_with_state(state)
                kept = provider.photo_files[draft_id]
                self.assertEqual((controller.photos_savable(), controller.photos_lost(), controller.has_unsaved()), (False, False, False), "사진을 안 넣었으면 잃을 것도 없다")
                self.assertEqual(controller.photos_card()["unsaved"], "")
                controller.photos.add_paths([path_of(7)])
                self.assertEqual((controller.photos_unsaved(), controller.photos_lost(), controller.has_unsaved()), (False, True, True))
                self.assertIsNone(controller._save_request().photos, "저장 요청에 사진 정보를 싣지 않는다")
                self.assertEqual(controller.save_state(), "saved", "글은 저장한 판 그대로다")
                self.assertEqual(controller.photos_card()["unsaved"], T[card_key])
                status, applied = store(controller, "save")
                self.assertEqual((status, applied), ("started", ("saved", None)))
                self.assertIsNone(provider.save_calls[-1].photos, "저장한 요청에도 사진 정보가 없다")
                self.assertEqual(controller.notice[0], "ok", "저장을 시도하지 않았으니 '다시 저장해 보세요' 실패 알림도 없다")
                self.assertIs(provider.photo_files[draft_id], kept, "저장해 둔 사진 정보 파일은 건드리지 않았다")
                self.assertTrue(controller.photos_lost() and controller.has_unsaved(), "저장한 뒤에도 사진 정보는 저장되지 않았다는 안내가 남는다")

    def test_the_card_says_what_is_true_for_each_state(self):
        broken, unreadable = T["pho_card_lost_broken"], T["pho_card_lost_unreadable"]
        self.assertIn("읽을 수 없어서", broken)
        self.assertIn("지금은 열 수 없어서", unreadable)
        for sentence in (broken, unreadable):
            self.assertIn("저장", sentence)
            self.assertIn("이 화면을 떠나면 사라져요", sentence)
            self.assertNotIn("다시 저장해 보세요", sentence)
        self.assertIn("초안을 다시 열면", unreadable)
        self.assertNotIn("초안을 다시 열면", broken, "깨진 파일은 다시 열어도 같다")

    def test_leaving_asks_a_two_way_question_and_with_edited_text_a_three_way_one_that_says_the_photo_info_is_not_saved(self):
        for state, _key in self.STATES:
            with self.subTest(state=state):
                controller, provider, draft_id = opened_with_state(state)
                controller.photos.add_paths([path_of(7), path_of(8)])
                dialog = controller.leave_dialog("leave")
                self.assertEqual((dialog["title"], "choices" in dialog), (T["pho_leave_title"], False), "글은 그대로이고 사진 정보는 저장할 길이 없다 — 사라진다는 두 갈래")
                self.assertEqual(dialog["body"], T["pho_leave_body"].format(n=2))
                self.assertEqual(controller.leave_dialog("close")["body"], T["pho_close_body"].format(n=2))
                controller.discard_leave()
                controller.set_body(controller.body + " 고침")
                three = controller.leave_dialog("leave")
                self.assertEqual([choice["key"] for choice in three["choices"]], ["save", "discard", "stay"])
                self.assertEqual(three["body"], T["drf_leave3_body"] + " " + T["pho_leave3_lost"], "`저장` 은 글만 저장한다 — 사진 정보는 저장되지 않는다고 사실대로")
                self.assertEqual(controller.leave_dialog("close")["body"], T["drf_close3_body"] + " " + T["pho_leave3_lost"])

    def test_removing_every_photo_again_leaves_nothing_to_lose(self):
        controller, provider, draft_id = opened_with_state("broken")
        controller.photos.add_paths([path_of(7)])
        self.assertTrue(controller.photos_lost())
        controller.photos.remove("p001")
        self.assertEqual((controller.photos_lost(), controller.has_unsaved(), controller.photos_card()["unsaved"]), (False, False, ""))
        self.assertIsNone(controller.leave_dialog("leave"))

    def test_restoring_the_copy_makes_the_photo_info_savable_again(self):
        controller, provider = with_photos()
        store(controller, "save")
        draft_id = deleted_and_back(controller, provider)
        controller.photos_state = "broken"                                              # 열 때 깨졌던 것으로 본다(사본을 되돌리면 새로 시작한다)
        self.assertFalse(controller.photos_savable())
        status, applied = store(controller, "restore")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((controller.photos_state, controller.photos_savable()), ("ok", True))
        controller.photos.add_paths([path_of(9)])
        self.assertEqual((controller.photos_unsaved(), controller.photos_lost()), (True, False))
        store(controller, "save")
        self.assertEqual(len(provider.photo_files[draft_id].photos), 3)

    def test_a_draft_whose_photo_info_is_fine_behaves_as_before(self):
        for state in ("none", "ok"):
            with self.subTest(state=state):
                controller, provider = with_photos(2) if state == "ok" else made_saving()
                store(controller, "save")
                draft_id = saved_id(provider)
                controller.leave()
                store(controller, "open", draft_id)
                self.assertEqual(controller.photos_state, state)
                controller.photos.add_paths([path_of(7)])
                self.assertEqual((controller.photos_savable(), controller.photos_unsaved(), controller.photos_lost()), (True, True, False))
                self.assertIsNotNone(controller._save_request().photos)
                self.assertEqual(controller.photos_card()["unsaved"], T["pho_card_unsaved"])
                controller.discard_leave()
                self.assertEqual(controller.leave_dialog("leave")["body"], T["drf_leave3_body"], "글을 안 고쳤으면 세 갈래 본문 그대로")
                controller.discard_leave()
                controller.set_body(controller.body + " 고침")
                self.assertEqual(controller.leave_dialog("leave")["body"], T["drf_leave3_body"], "멀쩡한 상태에서는 '저장되지 않아요' 문장이 안 붙는다")


class ZeroPhotoAndRemakeTest(unittest.TestCase):
    """사진이 0장인 사진 정보(검증 S PS-5·Q PQ-5)와 되돌린 직후의 '다시 만들기' 안내(Q PQ-3) — 가짜 공급자는 서비스와 같은 규칙이다(사진 0장 파일은 지울 때 사본으로 안 옮기고, 되돌리기는 0장 파일 위에 쓴다)."""

    def emptied(self):
        """사진 정보를 저장했다 지운 상태 — 되살린 초안(사본 있음)에서 사진 1장을 넣어 저장하고 다시 지워 저장해 저장해 둔 사진 정보가 사진 0장이다."""
        controller, provider = with_photos()
        store(controller, "save")
        draft_id = deleted_and_back(controller, provider)
        controller.photos.add_paths([path_of(9)])
        store(controller, "save")
        controller.photos.remove("p001")
        store(controller, "save")
        self.assertEqual(provider.photo_files[draft_id].photos, (), "저장해 둔 사진 정보는 사진 0장")
        return controller, provider, draft_id

    def test_a_photo_info_with_no_photos_is_not_made_a_copy_and_the_earlier_copy_stays(self):
        controller, provider, draft_id = self.emptied()
        earlier = provider.photo_trash[draft_id]
        self.assertEqual(len(earlier.photos), 2)
        controller.leave()
        status, applied = delete(controller, draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertIs(provider.photo_trash[draft_id], earlier, "앞선 사본은 그대로다 — 빈 사진 정보가 덮지 못한다")
        self.assertNotIn(draft_id, provider.photo_files)
        self.assertEqual(controller.list_notice, ("ok", T["drf_deleted_notice"]), "사본을 만들지 않았으니 사본 문장이 없다")

    def test_a_zero_photo_info_with_no_earlier_copy_leaves_no_copy_at_all(self):
        controller, provider = with_photos()
        store(controller, "save")
        draft_id = saved_id(provider)
        controller.photos.remove("p001")
        controller.photos.remove("p002")
        store(controller, "save")
        self.assertEqual(provider.photo_files[draft_id].photos, ())
        controller.leave()
        delete(controller, draft_id)
        self.assertEqual((provider.photo_trash, provider.photo_files, controller.list_notice), ({}, {}, ("ok", T["drf_deleted_notice"])))

    def test_restoring_writes_over_a_saved_photo_info_with_no_photos_so_the_button_is_never_a_dead_end(self):
        controller, provider, draft_id = self.emptied()
        self.assertTrue(controller.photos_card()["trash"]["restore_enabled"], "화면에 사진이 없으니 단추가 켜져 있다")
        status, applied = store(controller, "restore")
        self.assertEqual((status, applied), ("started", True), "켜진 단추가 영구 거절이 되지 않는다")
        self.assertEqual((controller.photos.count, controller.photos_trash, controller.notice), (2, False, ("ok", T["pho_restored_notice"])))
        self.assertEqual(len(provider.photo_files[draft_id].photos), 2)
        self.assertNotIn(draft_id, provider.photo_trash)

    def test_restoring_never_writes_over_a_saved_photo_info_that_has_photos(self):
        controller, provider = with_photos()
        store(controller, "save")
        draft_id = deleted_and_back(controller, provider)
        controller.photos.add_paths([path_of(9)])
        store(controller, "save")
        saved = provider.photo_files[draft_id]
        controller.photos.remove("p001")                                                # 저장 전 목록은 비어 단추는 켜지지만 저장해 둔 사진 정보에는 사진이 있다
        self.assertTrue(controller.photos_card()["trash"]["restore_enabled"])
        status, applied = store(controller, "restore")
        self.assertEqual(applied, "invalid")
        self.assertEqual(controller.notice, ("error", drafts.PHOTO_EXISTS_REASON))
        self.assertIs(provider.photo_files[draft_id], saved)
        self.assertIn(draft_id, provider.photo_trash, "사본도 그대로다")

    def test_the_blocked_reason_also_says_a_saved_photo_info_with_photos_blocks_it(self):
        controller, provider = with_photos()
        store(controller, "save")
        deleted_and_back(controller, provider)
        self.assertEqual(controller.photos_card()["trash"]["restore_note"], "")
        controller.photos.add_paths([path_of(9)])
        note = controller.photos_card()["trash"]["restore_note"]
        self.assertEqual(note, T["pho_restore_blocked"])
        self.assertIn("사진을 모두 지운 뒤에 되돌려 주세요", note)
        self.assertIn("저장해 둔 사진 정보에 사진이 있으면 그때도 되돌릴 수 없어요", note)

    def restored_with(self, slots):
        """사진 둘을 확정해 만들고(slots=True 면 본문에 자리가 들어가게 다시 만든다) 저장·지움·되살림·열기 뒤 `사진 정보 되돌리기` 까지 한 컨트롤러."""
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1), path_of(2)])
        confirm(controller, 1, user_subject="매장 입구 간판")
        confirm(controller, 2)
        if slots:
            drive(controller)
        store(controller, "save")
        deleted_and_back(controller, provider)
        status, applied = store(controller, "restore")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(controller.photos.count, 2)
        return controller

    def test_after_restoring_the_card_does_not_ask_for_a_remake_when_the_body_already_has_the_slots(self):
        controller = self.restored_with(slots=True)
        self.assertEqual(controller.photo_gate_lines("body")[0], (), "본문의 자리와 되돌린 사진은 어긋남이 없다")
        self.assertEqual(controller.photos_card()["remake"], "", "어긋남이 없으면 '다시 만들기' 안내도 없다")

    def test_after_restoring_the_card_still_asks_for_a_remake_when_the_body_has_no_slots_for_the_photos(self):
        controller = self.restored_with(slots=False)
        self.assertNotEqual(controller.photo_gate_lines("body")[0], (), "본문에 자리가 없으니 어긋남이 있다")
        self.assertEqual(controller.photos_card()["remake"], T["pho_card_remake"], "본문에 반영하려면 다시 만들어야 한다")


class LeaveWithFailedPhotosTest(unittest.TestCase):
    """`저장` 을 골라 나가려는데 **사진 정보만** 저장하지 못했으면 나가지 않고 글 저장 실패와 같은 경고창이 먼저다(검증 S PS-1·Q PQ-1 — 그냥 나가면 고친 사진 정보가 조용히 사라졌다)."""
    AFTERS = (("leave", lambda: None), ("list", None), ("close", None))

    def failing(self):
        controller, provider = with_photos()
        provider.photo_fail = T["pho_save_fail"]
        return controller, provider

    def test_saving_to_leave_stops_with_a_warning_when_only_the_photo_info_failed(self):
        for after in self.AFTERS:
            with self.subTest(after=after[0]):
                controller, provider = self.failing()
                status, applied = store(controller, "save", after=after)
                self.assertEqual((status, applied), ("started", ("photos_failed", after)), "이어서 나가라고 돌려주면 안 된다")
                self.assertIn(saved_id(provider), provider.saved, "글은 저장됐다")
                self.assertTrue(controller.photos_unsaved(), "사진 정보는 아직 저장되지 않았다")
                self.assertEqual(controller.photos.count, 2, "사진 목록은 그대로 남아 있다")
                problem = controller.take_save_problem()
                self.assertEqual((problem.kind, problem.code, problem.user_message), ("other", "PHOTO_SAVE_FAILED", T["pho_save_fail"]))
                closing = after[0] == "close"
                self.assertEqual(controller.save_failure_dialog(problem, after), {"title": T["pho_savefail_leave_title"], "body": T["pho_save_fail"] + "\n\n" + T["pho_savefail_leave_tail"],
                                                                                 "ok": T["pho_choice_discard_close" if closing else "pho_choice_discard_leave"], "cancel": T["drf_choice_stay"], "after": after})

    def test_the_warning_says_the_photo_info_goes_away_and_the_draft_text_was_saved_and_the_buttons_say_so_too(self):
        controller, provider = self.failing()
        store(controller, "save", after=("leave", lambda: None))
        dialog = controller.save_failure_dialog(controller.take_save_problem(), ("leave", lambda: None))
        self.assertIn("초안은 저장했지만 사진 정보는 저장하지 못했어요", dialog["body"])
        self.assertIn("그래도 나가면 고친 사진 정보가 사라져요", dialog["body"])
        self.assertEqual((dialog["ok"], dialog["cancel"]), ("사진 정보 없이 나가기", "계속 고치기"))
        self.assertNotIn("저장 안 하고", dialog["ok"], "글은 저장됐으므로 '저장 안 하고' 라고 하지 않는다")

    def test_it_is_a_quiet_notice_when_nothing_is_waiting_to_leave(self):
        controller, provider = self.failing()
        status, applied = store(controller, "save")
        self.assertEqual((status, applied), ("started", ("saved", None)))
        self.assertIsNone(controller.take_save_problem())
        self.assertEqual(controller.notice, ("error", T["pho_save_fail"]))
        self.assertTrue(controller.photos_unsaved())

    def test_after_the_warning_a_second_save_that_works_goes_on_to_leave(self):
        controller, provider = self.failing()
        after = ("close", None)
        store(controller, "save", after=after)
        controller.take_save_problem()
        provider.photo_fail = None
        status, applied = store(controller, "save", after=after)
        self.assertEqual(applied, ("saved", after))
        self.assertEqual((controller.photos_unsaved(), controller.save_state()), (False, "saved"))
        self.assertIsNone(controller.take_save_problem())

    def test_the_reason_the_service_gave_stays_in_the_warning(self):
        controller, provider = with_photos()
        reason = "사진 1 메모 줄 3 — 키나 토큰처럼 보이는 글이 있어요"
        provider.photo_fail = T["pho_save_fail"] + " " + reason
        after = ("leave", lambda: None)
        store(controller, "save", after=after)
        dialog = controller.save_failure_dialog(controller.take_save_problem(), after)
        self.assertIn(reason, dialog["body"])

    def test_a_text_failure_still_uses_the_text_warning(self):
        controller, provider = self.failing()
        failure = drafts.DraftFailure(T["drf_savefail_io"], code="FILE_WRITE_FAILED", kind="io")
        after = ("close", None)
        dialog = controller.save_failure_dialog(failure, after)
        self.assertEqual((dialog["title"], dialog["ok"]), (T["drf_savefail_leave_title"], T["drf_choice_discard_close"]))
        self.assertIn(T["drf_savefail_leave_tail"], dialog["body"])


class FailureSentenceTest(unittest.TestCase):
    def test_photo_failures_use_the_fixed_sentences_and_never_the_details(self):
        from chanceblog_desktop.errors import AppError
        missing = drafts.photo_failure(AppError("CONTENT_NOT_FOUND", {"항목": "사진 정보"}))
        self.assertEqual((missing.user_message, missing.kind), (T["pho_restore_missing"], "notfound"))
        exists = drafts.photo_failure(AppError("CONTENT_INVALID", {"항목": "사진 정보 — " + drafts.PHOTO_EXISTS_REASON}))
        self.assertEqual((exists.user_message, exists.kind), (drafts.PHOTO_EXISTS_REASON, "invalid"))
        for code in ("FILE_WRITE_FAILED", "DISK_FULL", "SOMETHING_ELSE"):
            failure = drafts.photo_failure(AppError(code, {"경로": "UNIQ-PATH-s3x1"}, detail="UNIQ-DETAIL-s3x1"))
            self.assertEqual(failure.user_message, T["pho_restore_fail"])
            self.assertNotIn("UNIQ", failure.user_message + repr(failure))
        self.assertEqual(drafts.photo_failure(AppError("FILE_WRITE_FAILED"), "pho_trash_clear_fail").user_message, T["pho_trash_clear_fail"])


if __name__ == "__main__":
    unittest.main()
