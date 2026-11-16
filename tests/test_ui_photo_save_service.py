"""사진 정보를 초안과 함께 저장·열기·지우기(되돌릴 사본) — 실제 공급자(`ui/drafts_adapter.py` → `service/photo_manifest.py`·`draft_store.py`)를 진짜 임시 폴더와 진짜 서비스 함수로 확인한다(사진 연동 3단계, 운영자 확인 024).
PySide6·네트워크·실제 시크릿 없이 돈다. 사진 파일은 만들지도 읽지도 않는다(사진 경로는 글자일 뿐이고 이 시험은 목록만 본다).

지키는 것:
  1) 저장 — 초안을 먼저, 사진 정보를 나중에 쓰고, 사진 정보가 없거나 안 고쳤으면 `photo-manifests/` 폴더를 만들지도 않는다. 새로 연 컨트롤러(재시작처럼)가 사진 목록을 그대로 읽는다.
  2) 열기는 읽기뿐이다 — 깨진 사진 정보 파일은 건드리지 않고 알리며, 그 위에 저장하려 하면 거절하고(초안은 저장됐다) 파일이 그대로다.
  3) 지우기 — 초안을 지우면 사진 정보 파일은 되돌릴 사본(`.json.trash`)으로 옮겨지고(초안당 한 벌), 같은 번호로 되살린 초안에서 `사진 정보 되돌리기`·`사본 비우기` 가 말한 대로 움직인다.
  4) 사진 파일·초안 보관함의 다른 것은 건드리지 않는다. 화면에 나가는 문장에 경로·글이 없다.
"""
import dataclasses
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
from test_ui_drafts_save_service import fresh, make, store as base_store  # noqa: E402
from test_ui_drafts_service import Setup  # noqa: E402

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import draft_store  # noqa: E402
from chanceblog_desktop.service import photo_manifest as svc  # noqa: E402
from chanceblog_desktop.ui.core import drafts, text  # noqa: E402

T = text.T
MARKER = "UNIQ-S3SVC-q4"
OPS = {"restore": ("start_restore_photos", "apply_photos_restored", "apply_restore_photos_failed"), "clear": ("start_clear_trash", "apply_trash_cleared", "apply_clear_trash_failed")}


def store(controller, op, *args, **kwargs):
    if op not in OPS:
        return base_store(controller, op, *args, **kwargs)
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


class Base(unittest.TestCase):
    def setUp(self):
        self.setup = Setup(self, count=2)
        self.engine = self.setup.engines[0]
        self.root = self.setup.ctx.workspace.root
        self.folder = svc.folder_path(self.setup.ctx)
        self.pictures = Path(self.setup.world.tmp) / "pics"
        self.pictures.mkdir()
        self.paths = []
        for number in (1, 2):
            path = self.pictures / f"{MARKER}-{number}.jpg"
            path.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0]) + bytes(number * 40))
            self.paths.append(str(path))

    def made(self):
        return make(self.setup.controller(), self.engine)

    def with_photos(self):
        controller = self.made()
        controller.photos.add_paths(self.paths)
        return controller

    def saved_with_photos(self):
        controller = self.with_photos()
        store(controller, "save")
        return controller, controller.saved_id

    def picture_state(self):
        return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(self.pictures.iterdir())}


class SaveAndOpenTest(Base):
    def test_a_saved_draft_comes_back_with_its_photo_list_after_a_restart(self):
        controller, draft_id = self.saved_with_photos()
        self.assertEqual(controller.notice[0], "ok")
        self.assertEqual((controller.photos_unsaved(), controller.save_state()), (False, "saved"))
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{draft_id}.json"])
        again = fresh(self.setup)
        store(again, "list")
        status, applied = store(again, "open", draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(again.photos.manifest.photos, controller.photos.manifest.photos)
        self.assertEqual((again.photos_unsaved(), again.has_unsaved(), again.photos_state, again.photos_trash), (False, False, "ok", False))

    def test_a_draft_without_photos_never_makes_the_photo_folder(self):
        controller = self.made()
        store(controller, "save")
        controller.set_body(controller.body + " 고침")
        store(controller, "save")
        self.assertFalse(self.folder.exists(), "사진을 안 만졌으면 사진 정보 폴더도 만들지 않는다")
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", again.listing.rows[0].draft_id)
        self.assertEqual((again.photos.count, again.photos_state, again.photos_trash), (0, "none", False))
        self.assertFalse(self.folder.exists(), "열기도 아무것도 만들지 않는다")

    def test_a_text_edit_alone_does_not_rewrite_the_photo_file(self):
        controller, draft_id = self.saved_with_photos()
        file = self.folder / f"{draft_id}.json"
        before = (file.read_bytes(), file.stat().st_mtime_ns)
        controller.set_body(controller.body + " 고침")
        store(controller, "save")
        self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), before)

    def test_changing_the_photos_and_saving_again_rewrites_the_file_and_removing_all_is_saved_too(self):
        controller, draft_id = self.saved_with_photos()
        controller.photos.set_text("p001", "user_note", MARKER)
        controller.photos.confirm("p001", True)
        store(controller, "save")
        loaded = svc.load_manifest(self.setup.ctx, draft_id)
        self.assertEqual((loaded.state, loaded.manifest.photo("p001").user_note, loaded.manifest.photo("p001").confirmed_by_user), ("ok", MARKER, True))
        for photo_id in ("p001", "p002"):
            controller.photos.remove(photo_id)
        store(controller, "save")
        self.assertEqual(svc.load_manifest(self.setup.ctx, draft_id).manifest.photos, ())

    def test_the_photo_save_is_refused_over_a_broken_file_and_the_draft_is_still_saved(self):
        controller, draft_id = self.saved_with_photos()
        file = self.folder / f"{draft_id}.json"
        file.write_text("{ 깨진 글 }", encoding="utf-8")
        before = file.read_bytes()
        controller.photos.set_text("p001", "user_note", "새 메모")
        controller.set_body(controller.body + " 글도 고침")
        status, applied = store(controller, "save")
        self.assertEqual(applied[0], "saved")
        self.assertEqual(controller.notice[0], "error")
        self.assertTrue(controller.notice[1].startswith(T["pho_save_fail"]))
        self.assertNotIn(str(self.folder), controller.notice[1])
        self.assertEqual(file.read_bytes(), before, "깨진 파일은 덮어쓰지 않았다")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [file.name], ".bak 도 안 만들었다")
        self.assertTrue(controller.photos_unsaved(), "저장하지 못했으니 '고쳤어요' 가 남는다")
        self.assertEqual(controller.save_state(), "changed")
        self.assertEqual(draft_store.load_draft(self.setup.ctx, draft_id).body, controller.body, "글은 저장됐다")

    def test_opening_a_draft_with_a_broken_or_unreadable_photo_file_notes_it_and_changes_nothing(self):
        controller, draft_id = self.saved_with_photos()
        file = self.folder / f"{draft_id}.json"
        file.write_text("{ 깨진 글 }", encoding="utf-8")
        before = ss.tree_snapshot(self.setup.world.tmp)
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", draft_id)
        self.assertEqual((again.photos_state, again.photos.count), ("broken", 0))
        self.assertIn(T["pho_open_broken"], again.notice[1])
        self.assertEqual(ss.tree_snapshot(self.setup.world.tmp), before, "열기는 읽기뿐이다")
        file.unlink()
        svc.save_manifest(self.setup.ctx, draft_id, controller.photos.manifest)          # 멀쩡한 파일로 되돌려 두고 '지금 못 읽는' 경우를 만든다
        again = fresh(self.setup)
        store(again, "list")
        with mock.patch.object(svc, "_pause"), mock.patch.object(svc.own_posts, "_read_prefix", return_value=(None, svc.own_posts._R_MISSING)):
            store(again, "open", draft_id)
        self.assertEqual((again.photos_state, again.photos.count), ("unreadable", 0))
        self.assertIn(T["pho_open_unreadable"], again.notice[1])

    def test_the_picture_files_are_never_touched(self):
        before = self.picture_state()
        controller, draft_id = self.saved_with_photos()
        controller.leave()
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", draft_id)
        again.delete_dialog(draft_id)
        store(again, "delete")
        self.assertEqual(self.picture_state(), before)
        self.assertEqual(sorted(os.listdir(self.pictures)), sorted(Path(path).name for path in self.paths))


class DeleteAndRestoreTest(Base):
    def delete(self, controller, draft_id):
        store(controller, "list")
        controller.delete_dialog(draft_id)
        return store(controller, "delete")

    def deleted_and_back(self):
        controller, draft_id = self.saved_with_photos()
        draft = draft_store.load_draft(self.setup.ctx, draft_id)
        original = (self.folder / f"{draft_id}.json").read_bytes()
        controller.leave()
        status, applied = self.delete(controller, draft_id)
        self.assertEqual((status, applied), ("started", True))
        draft_store.save_draft(self.setup.ctx, title=draft.title, body=draft.body, blog=draft.blog, post_type=draft.post_type, draft_id=draft_id)          # 백업에서 되살린 것처럼 같은 번호로 다시 생긴다
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", draft_id)
        return again, draft_id, original

    def test_deleting_a_saved_draft_moves_the_photo_file_to_one_restorable_copy_and_says_so(self):
        controller, draft_id = self.saved_with_photos()
        original = (self.folder / f"{draft_id}.json").read_bytes()
        controller.leave()
        status, applied = self.delete(controller, draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(controller.list_notice, ("ok", T["drf_deleted_notice"] + " " + T["pho_deleted_trash"]))
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{draft_id}.json.trash"])
        self.assertEqual((self.folder / f"{draft_id}.json.trash").read_bytes(), original, "바이트 그대로")
        self.assertEqual(svc.list_manifests(self.setup.ctx), svc.Listing((), 0))
        self.assertEqual(svc.orphans(self.setup.ctx, []), ())

    def test_a_draft_without_photo_info_deletes_as_before_and_makes_no_copy(self):
        controller = self.made()
        store(controller, "save")
        draft_id = controller.saved_id
        controller.leave()
        self.delete(controller, draft_id)
        self.assertEqual(controller.list_notice, ("ok", T["drf_deleted_notice"]))
        self.assertFalse(self.folder.exists())

    def test_the_draft_is_deleted_even_when_the_copy_cannot_be_made_and_the_screen_says_so(self):
        controller, draft_id = self.saved_with_photos()
        controller.leave()
        with mock.patch.object(svc, "trash_manifest", side_effect=AppError("FILE_WRITE_FAILED", {"경로": MARKER}, detail=MARKER)):
            status, applied = self.delete(controller, draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(controller.list_notice, ("error", T["drf_deleted_notice"] + " " + T["pho_deleted_trash_fail"]))
        self.assertNotIn(MARKER, repr(controller.list_notice))
        self.assertTrue((self.folder / f"{draft_id}.json").exists(), "사진 정보 파일은 그대로 남아 있다")
        self.assertEqual(draft_store.list_drafts(self.setup.ctx).entries, (), "초안은 지워졌다 — 사본을 못 만들어도 초안 지우기를 되돌리지 않는다")

    def test_a_draft_that_comes_back_shows_the_copy_and_restoring_gives_back_the_exact_file(self):
        again, draft_id, original = self.deleted_and_back()
        self.assertEqual((again.photos_trash, again.photos.count, again.photos_state), (True, 0, "none"))
        self.assertTrue(again.photos_card()["trash"]["restore_enabled"])
        status, applied = store(again, "restore")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((again.photos.count, again.photos_trash, again.photos_unsaved(), again.notice), (2, False, False, ("ok", T["pho_restored_notice"])))
        self.assertEqual((self.folder / f"{draft_id}.json").read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{draft_id}.json"])

    def test_restoring_over_an_existing_photo_file_is_refused_with_the_fixed_sentence_and_both_files_stay(self):
        again, draft_id, original = self.deleted_and_back()
        manifest, _id = pm.add_photo(pm.empty_manifest(), self.paths[0])
        svc.save_manifest(self.setup.ctx, draft_id, manifest)
        live = (self.folder / f"{draft_id}.json").read_bytes()
        trash = (self.folder / f"{draft_id}.json.trash").read_bytes()
        status, applied = store(again, "restore")
        self.assertEqual(applied, "invalid")
        self.assertEqual(again.notice, ("error", drafts.PHOTO_EXISTS_REASON))
        self.assertEqual(((self.folder / f"{draft_id}.json").read_bytes(), (self.folder / f"{draft_id}.json.trash").read_bytes()), (live, trash))

    def test_the_fake_and_the_real_sentences_agree_for_an_existing_file(self):
        self.assertEqual(svc._R_EXISTS, drafts.PHOTO_EXISTS_REASON)

    def test_clearing_the_copy_deletes_only_the_copy_after_the_dialog(self):
        again, draft_id, original = self.deleted_and_back()
        self.assertEqual(again.start_clear_trash(), ("unconfirmed", None))
        again.trash_clear_dialog()
        status, applied = store(again, "clear")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((again.photos_trash, again.notice), (False, ("ok", T["pho_trash_cleared_notice"])))
        self.assertFalse(self.folder.exists() and any(self.folder.iterdir()))
        self.assertEqual(draft_store.load_draft(self.setup.ctx, draft_id).draft_id, draft_id, "초안은 그대로다")
        self.assertEqual(sorted(os.listdir(self.pictures)), sorted(Path(path).name for path in self.paths), "사진 파일은 그대로다")

    def test_a_second_delete_keeps_only_the_latest_copy(self):
        again, draft_id, original = self.deleted_and_back()
        store(again, "restore")
        again.photos.set_text("p001", "user_note", MARKER)
        store(again, "save")
        later = (self.folder / f"{draft_id}.json").read_bytes()
        again.leave()
        self.delete(again, draft_id)
        self.assertEqual((self.folder / f"{draft_id}.json.trash").read_bytes(), later)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{draft_id}.json.trash"])

    def test_nothing_the_screen_shows_carries_a_path_or_the_marker_of_the_service_error(self):
        again, draft_id, original = self.deleted_and_back()
        with mock.patch.object(svc, "restore_manifest", side_effect=AppError("FILE_WRITE_FAILED", {"경로": str(self.folder)}, detail=MARKER)):
            status, applied = store(again, "restore")
        self.assertEqual((applied, again.notice), ("io", ("error", T["pho_restore_fail"])))
        shown = repr(again.notice) + repr(again.photos_card()) + repr(again.view())
        for marker in (str(self.folder), str(self.setup.world.tmp), MARKER, "UNIQ-USERDIR"):
            self.assertNotIn(marker, shown.replace(MARKER + "-1.jpg", "").replace(MARKER + "-2.jpg", ""), marker)


if __name__ == "__main__":
    unittest.main()
