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
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
from test_ui_drafts_save_service import fresh, make, store as base_store  # noqa: E402
from test_ui_drafts_service import Setup, drive_regenerate  # noqa: E402

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
        self.assertEqual((controller.notice[0], controller.save_state()), ("ok", "saved"), "글만 저장한 것은 사진 정보 실패가 아니다")
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
        self.assertIn(svc._R_BROKEN, controller.notice[1], "서비스가 정한 고정 이유 문장이 함께 보인다")
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

    def test_a_photo_folder_that_is_not_a_folder_is_noted_as_broken_when_opening_and_nothing_is_changed(self):
        controller, draft_id = self.saved_with_photos()
        controller.leave()
        shutil.rmtree(self.folder)
        self.folder.write_text("폴더가 아니라 파일이다", encoding="utf-8")                      # 사진 정보 보관 폴더 자리에 파일이 있다 — 읽지도 덮어쓰지도 않는다
        before = ss.tree_snapshot(self.setup.world.tmp)
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", draft_id)
        self.assertEqual((again.photos_state, again.photos.count, again.photos_trash), ("broken", 0, False))
        self.assertIn(T["pho_open_broken"], again.notice[1])
        self.assertEqual(ss.tree_snapshot(self.setup.world.tmp), before, "열기는 읽기뿐이다")
        again.photos.add_paths(self.paths)
        self.assertEqual((again.photos_lost(), again.photos_unsaved(), again.photos_card()["unsaved"]), (True, False, T["pho_card_lost_broken"]))
        store(again, "save")
        self.assertEqual(again.notice[0], "info", "그 위에는 저장을 시도하지도 않는다 — 사진 정보는 저장하지 않고 알림과 카드가 그렇게 말한다(검증 S PS-2·PS-15)")
        self.assertTrue(again.notice[1].endswith(T["pho_saved_without_photos"]))
        self.assertEqual(self.folder.read_text(encoding="utf-8"), "폴더가 아니라 파일이다")

    def test_a_photo_file_that_was_unreadable_or_broken_when_opened_is_not_overwritten_by_a_later_save(self):
        """검증 S PS-2(S 재현 s2_flow.py UnreadableThenOverwrite): 열 때 못 열었거나 깨졌던 파일 위에, 잠금이 풀린 뒤 사진을 넣고 저장해도 멀쩡한 기존 파일을 덮지 않는다."""
        for state in ("unreadable", "broken"):
            with self.subTest(state=state):
                controller, draft_id = self.saved_with_photos()
                file = self.folder / f"{draft_id}.json"
                if state == "broken":
                    file.write_text("{ 깨진 글 }", encoding="utf-8")
                before = (file.read_bytes(), file.stat().st_mtime_ns)
                controller.leave()
                again = fresh(self.setup)
                store(again, "list")
                if state == "unreadable":
                    with mock.patch.object(svc, "_pause"), mock.patch.object(svc.own_posts, "_read_prefix", return_value=(None, svc.own_posts._R_MISSING)):
                        store(again, "open", draft_id)
                else:
                    store(again, "open", draft_id)
                self.assertEqual((again.photos_state, again.photos.count), (state, 0))
                again.photos.add_paths(self.paths)                                       # 잠금이 풀린 뒤(막던 것이 없다) 사진을 넣고 글도 고쳐 저장한다
                again.set_body(again.body + " 글도 고침")
                self.assertIsNone(again._save_request().photos, "저장 요청에 사진 정보를 싣지 않는다")
                store(again, "save")
                self.assertEqual(again.notice[0], "info", "사진 정보 실패 알림이 아니다 — 저장을 시도하지도 않았고 글만 저장했다고 말한다(검증 S PS-15)")
                self.assertTrue(again.notice[1].endswith(T["pho_saved_without_photos"]))
                self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), before, "저장해 둔 사진 정보 파일은 바이트도 수정 시각도 그대로다")
                self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [file.name], ".bak 도 안 만들었다")
                self.assertEqual(draft_store.load_draft(self.setup.ctx, draft_id).body, again.body, "글은 저장됐다")
                self.assertEqual((again.photos_lost(), again.photos_unsaved(), again.photos_card()["unsaved"]), (True, False, T["pho_card_lost_" + state]))

    def test_remaking_a_draft_that_was_opened_with_an_unreadable_or_broken_photo_file_saves_the_new_drafts_photo_info(self):
        """검증 S PS-12(S 재현 s2c_remake_stale.py)·Q PQ-17(pure_q30.py): 열 때 못 읽었던 사진 정보 파일의 상태가 다시 만들기로 만든 새 초안(새 번호)에 이어지면 새 초안의 사진 정보가 영영 저장되지 않았다 — 새 번호는 새 파일이다."""
        for state in ("unreadable", "broken"):
            with self.subTest(state=state):
                controller, draft_id = self.saved_with_photos()
                file = self.folder / f"{draft_id}.json"
                if state == "broken":
                    file.write_text("{ 깨진 글 }", encoding="utf-8")
                before = (file.read_bytes(), file.stat().st_mtime_ns)
                controller.leave()
                again = fresh(self.setup)
                store(again, "list")
                if state == "unreadable":
                    with mock.patch.object(svc, "_pause"), mock.patch.object(svc.own_posts, "_read_prefix", return_value=(None, svc.own_posts._R_MISSING)):
                        store(again, "open", draft_id)
                else:
                    store(again, "open", draft_id)
                self.assertEqual((again.photos_state, again.photos.count), (state, 0))
                again.photos.add_paths(self.paths)
                self.assertTrue(again.photos_lost())
                self.assertEqual(drive_regenerate(again), "started")
                self.assertEqual((again.photos_state, again.photos_savable(), again.photos_lost(), again.saved_id), ("none", True, False, None), "새 초안은 새 번호라 저장해 둔 파일이 없다")
                self.assertEqual(again.photos_card()["unsaved"], T["pho_card_unsaved"], "카드 안내가 새 초안에 거짓말을 하지 않는다")
                again.set_body(again.body + " 다시 만든 글")                                  # 번호는 저장 시각·글의 지문이라(시험의 시계는 고정) 글이 같으면 번호도 같다 — 실제로는 시각이 달라 늘 새 번호다
                status, applied = store(again, "save")
                self.assertEqual((status, applied), ("started", ("saved", None)))
                new_id = again.saved_id
                self.assertNotEqual(new_id, draft_id)
                self.assertEqual((again.notice[0], again.photos_unsaved()), ("ok", False))
                self.assertNotIn(T["pho_saved_without_photos"], again.notice[1])
                loaded = svc.load_manifest(self.setup.ctx, new_id)
                self.assertEqual((loaded.state, len(loaded.manifest.photos)), ("ok", 2), "새 번호의 사진 정보 파일이 생겼다")
                self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), before, "옛 사진 정보 파일은 바이트도 수정 시각도 그대로다")
                self.assertTrue({file.name, f"{new_id}.json"} <= {path.name for path in self.folder.iterdir()})

    def test_the_adapter_never_asks_the_service_to_keep_analysis_results(self):
        """검증 S PS-3 ④(변이 AD6 = PS-6): 분석 결과 저장 기본 끔은 운영자의 절대 조건이다 — 메모리에 확인 전 분석 항목이 있어도 어댑터는 `persist_analysis` 를 켜지 않고 파일에도 그 글이 없다."""
        controller = self.with_photos()
        manifest, dropped = pm.set_analysis(controller.photos.manifest, "p001", method="local:test-plugin", objects=[MARKER + "-obj"], texts=[MARKER + "-txt"])
        self.assertEqual(dropped, 0)
        controller.photos.manifest = manifest
        self.assertEqual(controller.photos.manifest.photo("p001").observed_objects[0].text, MARKER + "-obj", "분석 항목이 메모리에 있다")
        calls, real = [], svc.save_manifest

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return real(*args, **kwargs)

        with mock.patch.object(svc, "save_manifest", side_effect=spy):
            store(controller, "save")
        self.assertEqual(len(calls), 1, "사진 정보 저장은 서비스를 한 번 불렀다")
        self.assertFalse([call for call in calls if call.get("persist_analysis")], "어댑터는 분석 결과를 남기라고 하지 않는다")
        text = (self.folder / f"{controller.saved_id}.json").read_text(encoding="utf-8")
        for leaked in (MARKER + "-obj", MARKER + "-txt", "local:test-plugin"):
            self.assertNotIn(leaked, text)

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

    def emptied(self):
        """되살린 초안에서 사진 1장을 넣어 저장하고 다시 지워 저장해, 디스크에 사진 0장짜리 사진 정보 파일이 남은 상태(검증 S 재현 s11_misc.py) — 앞선 2장짜리 사본이 있다."""
        again, draft_id, original = self.deleted_and_back()
        again.photos.add_paths(self.paths[:1])
        store(again, "save")
        again.photos.remove("p001")
        store(again, "save")
        self.assertEqual(svc.load_manifest(self.setup.ctx, draft_id).manifest.photos, (), "디스크에 사진 0장짜리 파일이 남는다")
        self.assertTrue((self.folder / f"{draft_id}.json").exists())
        return again, draft_id, original

    def test_a_draft_that_cannot_be_deleted_keeps_its_photo_file_in_place_and_makes_no_copy(self):
        """검증 S PS-3 ③(변이 AD3·AD7): 초안을 못 지웠는데 사진 정보를 사본으로 옮기면 안 된다."""
        controller, draft_id = self.saved_with_photos()
        file = self.folder / f"{draft_id}.json"
        before = (file.read_bytes(), file.stat().st_mtime_ns)
        controller.leave()
        with mock.patch.object(draft_store, "delete_draft", side_effect=AppError("FILE_WRITE_FAILED", {"경로": MARKER}, detail=MARKER)):
            status, applied = self.delete(controller, draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(controller.list_notice, ("error", T["drf_deletefail"]))
        self.assertNotIn(MARKER, repr(controller.list_notice))
        self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), before, "초안을 못 지웠으면 사진 정보는 그대로 둔다")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [file.name], "되돌릴 사본이 안 생겼다")
        self.assertEqual([entry.draft_id for entry in draft_store.list_drafts(self.setup.ctx).entries], [draft_id], "초안은 그대로 있다")

    def test_restoring_over_a_saved_photo_file_with_no_photos_works_so_the_button_is_never_a_dead_end(self):
        again, draft_id, original = self.emptied()
        self.assertTrue(again.photos_card()["trash"]["restore_enabled"], "화면에 사진이 없으니 단추가 켜져 있다")
        status, applied = store(again, "restore")
        self.assertEqual((status, applied), ("started", True), "켜진 단추가 영구 거절이 되지 않는다")
        self.assertEqual((again.photos.count, again.photos_trash, again.notice), (2, False, ("ok", T["pho_restored_notice"])))
        self.assertEqual((self.folder / f"{draft_id}.json").read_bytes(), original, "사본의 바이트 그대로")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{draft_id}.json"])

    def test_deleting_a_draft_whose_photo_file_has_no_photos_keeps_the_earlier_copy_and_does_not_mention_a_copy(self):
        again, draft_id, original = self.emptied()
        trash = self.folder / f"{draft_id}.json.trash"
        before = (trash.read_bytes(), trash.stat().st_mtime_ns)
        again.leave()
        status, applied = self.delete(again, draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(again.list_notice, ("ok", T["drf_deleted_notice"]), "사본을 만들지 않았으니 사본 문장이 없다")
        self.assertEqual((trash.read_bytes(), trash.stat().st_mtime_ns), before, "앞선 사본은 바이트도 수정 시각도 그대로다")
        self.assertEqual(trash.read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [trash.name], "0장짜리 사진 정보 파일은 지웠다")

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


class MakeTest(Base):
    """진짜 공급자로 초안을 만들 때 확정한 사진이 본문에 들어간다(사진 연동 3단계 — 본문 연결)."""

    def regen(self, controller):
        results = {}
        status, job = controller.start_make(on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
        self.assertEqual(status, "started")
        job.join(30)
        self.assertIn("ok", results, results)
        controller.apply_made(results["ok"])

    def made_with_photos(self):
        controller = self.made()
        controller.photos.add_paths(self.paths)
        controller.photos.set_text("p001", "user_subject", "매장 입구 간판")
        controller.photos.set_text("p001", "user_note", "주차는 뒤쪽이에요")
        controller.photos.confirm("p001", True)
        controller.photos.confirm("p002", True)
        self.regen(controller)
        return controller

    def test_a_real_make_places_the_confirmed_photos_and_never_reads_the_picture_files(self):
        pictures, before = self.picture_state(), ss.tree_snapshot(self.setup.world.tmp)
        controller = self.made()
        controller.photos.add_paths(self.paths)
        controller.photos.confirm("p001", True)
        self.regen(controller)
        found = [number for number, _start, _end in pm.find_placeholders(controller.body)]
        self.assertEqual(found, [1], "확정한 사진 하나만 본문에 들어간다")
        controller.photos.confirm("p002", True)
        controller.photos.set_text("p001", "user_subject", "매장 입구 간판")
        controller.photos.confirm("p001", True)
        self.assertEqual(controller.photos_card()["remake"], T["pho_card_remake"])
        self.regen(controller)
        self.assertEqual(sorted(number for number, _start, _end in pm.find_placeholders(controller.body)), [1, 2])
        self.assertIn("매장 입구 간판 사진이에요.", controller.body)
        self.assertEqual(controller.photos_card()["remake"], "")
        self.assertEqual(self.picture_state(), pictures, "사진 파일은 열지도 바꾸지도 않았다")
        self.assertEqual(ss.tree_snapshot(self.setup.world.tmp), before, "만들기는 읽기뿐이다 — 폴더 안이 그대로다")
        shown = controller.body + repr(controller.view()) + repr(self.setup.provider.__dict__)
        self.assertNotIn(MARKER, shown.replace(MARKER + "-1.jpg", "").replace(MARKER + "-2.jpg", ""))
        self.assertNotIn(str(self.pictures), controller.body)

    def test_without_confirmed_photos_a_real_make_gives_the_same_body_as_before(self):
        controller = self.made()
        first = (controller.title, controller.body)
        controller.photos.add_paths(self.paths)
        self.regen(controller)
        self.assertEqual((controller.title, controller.body), first, "확정하지 않았으면 본문이 같다")
        self.assertEqual(pm.find_placeholders(controller.body), ())

    def test_after_restoring_the_copy_the_card_does_not_ask_for_a_remake_when_the_body_already_has_the_slots(self):
        """검증 Q PQ-3(Q 재현 pure_q10.py): 지운 초안을 되살려 사진 정보를 되돌리면 본문에 이미 그 사진들의 자리가 있고 어긋남도 없다 — 다시 만들라고 하지 않는다."""
        controller = self.made_with_photos()
        store(controller, "save")
        draft_id = controller.saved_id
        draft = draft_store.load_draft(self.setup.ctx, draft_id)
        controller.leave()
        store(controller, "list")
        controller.delete_dialog(draft_id)
        store(controller, "delete")
        draft_store.save_draft(self.setup.ctx, title=draft.title, body=draft.body, blog=draft.blog, post_type=draft.post_type, draft_id=draft_id)          # 백업에서 되살린 것처럼 같은 번호로 다시 생긴다
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", draft_id)
        self.assertEqual((again.photos.count, again.photos_trash, again.photos_card()["remake"]), (0, True, ""))
        status, applied = store(again, "restore")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(again.photos.count, 2)
        self.assertTrue(pm.placeholder_report(again.photos.manifest, again.body).ok)
        self.assertEqual(again.photos_card()["remake"], "", "본문에 이미 그 사진들의 자리가 있고 어긋남이 없다 — 다시 만들라고 하지 않는다")

    def test_the_placed_body_is_saved_and_comes_back_with_its_photos_and_no_remake_note(self):
        controller = self.made_with_photos()
        store(controller, "save")
        draft_id = controller.saved_id
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", draft_id)
        self.assertEqual(sorted(number for number, _start, _end in pm.find_placeholders(again.body)), [1, 2])
        self.assertEqual((again.photos.count, again.photos_card()["remake"]), (2, ""))
        report = pm.placeholder_report(again.photos.manifest, again.body)
        self.assertTrue(report.ok, report)


if __name__ == "__main__":
    unittest.main()
