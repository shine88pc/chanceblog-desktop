"""사진 정보 되돌리기가 0장 사진 정보 파일을 덮어쓸 때 **사진 번호 예약(`next_number`)은 큰 쪽**을 쓴다(검증 S PS-14 — 사본의 작은 값으로 돌아가면 지운 사진 번호를 새 사진이 물려받아
본문에 남은 옛 `{{사진 N}}` 자리와 겹친다). 서비스 함수 자체의 시험은 `test_service_photo_manifest.py`(`TrashTest`)에 있고, 여기서는

  1) **진짜 서비스·진짜 임시 폴더**로 컨트롤러를 거쳐 — 사진 6장까지 넣었다 모두 지우고 저장(0장 파일, 다음 번호 7) → 되돌리기 → 되돌린 직후 목록·디스크의 파일이 다음 번호 7 이고 새로 넣은 사진이 `p007` 을 받는다.
  2) **가짜 공급자**(순수)도 서비스와 같다 — 큰 쪽이면 큰 쪽, 같거나 작으면 사본의 값.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_drafts_save_service import fresh  # noqa: E402
from test_ui_photo_save_core import deleted_and_back, path_of, saved_id, with_photos  # noqa: E402
from test_ui_photo_save_core import store as core_store  # noqa: E402
from test_ui_photo_save_service import MARKER, Base, store  # noqa: E402

from chanceblog_desktop.service import draft_store  # noqa: E402
from chanceblog_desktop.service import photo_manifest as svc  # noqa: E402


class RealServiceReserveTest(Base):
    def delete(self, controller, draft_id):
        store(controller, "list")
        controller.delete_dialog(draft_id)
        return store(controller, "delete")

    def deleted_and_back(self):
        """사진 2장을 저장했다 초안을 지우고(사본 한 벌: 사진 2장·다음 번호 3) 같은 번호로 되살려 연 컨트롤러."""
        controller, draft_id = self.saved_with_photos()
        draft = draft_store.load_draft(self.setup.ctx, draft_id)
        controller.leave()
        status, applied = self.delete(controller, draft_id)
        self.assertEqual((status, applied), ("started", True))
        draft_store.save_draft(self.setup.ctx, title=draft.title, body=draft.body, blog=draft.blog, post_type=draft.post_type, draft_id=draft_id)          # 백업에서 되살린 것처럼 같은 번호로 다시 생긴다
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", draft_id)
        return again, draft_id

    def extra_paths(self, count, tag="b"):
        return [str(self.pictures / f"{MARKER}-{tag}{number}.jpg") for number in range(1, count + 1)]

    def test_restoring_over_an_emptied_list_keeps_the_bigger_number_reservation_so_the_next_photo_is_p007(self):
        again, draft_id = self.deleted_and_back()
        self.assertEqual((again.photos_trash, again.photos.count), (True, 0))
        again.photos.add_paths(self.extra_paths(6))
        store(again, "save")
        for number in range(1, 7):
            again.photos.remove(f"p{number:03d}")
        store(again, "save")
        emptied = svc.load_manifest(self.setup.ctx, draft_id)
        self.assertEqual((emptied.state, len(emptied.manifest.photos), emptied.manifest.next_number), ("ok", 0, 7), "디스크에 사진 0장·번호 예약 7 인 파일이 있다")
        status, applied = store(again, "restore")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((again.photos.count, again.photos.manifest.next_number, again.photos_unsaved(), again.photos_trash), (2, 7, False, False), "되돌린 목록은 사본의 사진 2장에 큰 쪽 예약이고 저장한 그대로다")
        on_disk = svc.load_manifest(self.setup.ctx, draft_id)
        self.assertEqual((on_disk.state, len(on_disk.manifest.photos), on_disk.manifest.next_number), ("ok", 2, 7))
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{draft_id}.json"], "사본도 임시 파일도 남지 않았다")
        again.photos.add_paths(self.extra_paths(1, tag="c"))
        self.assertEqual(again.photos.manifest.photos[-1].photo_id, "p007", "새 사진은 지운 번호(3~6)를 물려받지 않는다")

    def test_restoring_over_an_emptied_list_with_a_smaller_reservation_is_the_copy_as_it_was(self):
        again, draft_id = self.deleted_and_back()
        copy = (self.folder / f"{draft_id}.json.trash").read_bytes()
        again.photos.add_paths(self.extra_paths(1))
        store(again, "save")
        again.photos.remove("p001")
        store(again, "save")
        emptied = svc.load_manifest(self.setup.ctx, draft_id)
        self.assertEqual((emptied.state, len(emptied.manifest.photos), emptied.manifest.next_number), ("ok", 0, 2), "0장이고 번호 예약은 사본의 3 보다 작다")
        status, applied = store(again, "restore")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((again.photos.count, again.photos.manifest.next_number), (2, 3))
        self.assertEqual((self.folder / f"{draft_id}.json").read_bytes(), copy, "사본 바이트 그대로 — 다시 쓰지 않았다")


class FakeProviderReserveTest(unittest.TestCase):
    def emptied(self, added):
        """사본 한 벌(사진 2장·다음 번호 3)이 있는 되살린 초안에서 사진을 `added` 장 넣었다 모두 지우고 저장했다."""
        controller, provider = with_photos(2)
        core_store(controller, "save")
        draft_id = deleted_and_back(controller, provider)
        self.assertEqual((provider.photo_trash[draft_id].next_number, controller.photos.count), (3, 0))
        controller.photos.add_paths([path_of(number) for number in range(1, added + 1)])
        core_store(controller, "save")
        for number in range(1, added + 1):
            controller.photos.remove(f"p{number:03d}")
        core_store(controller, "save")
        self.assertEqual((len(provider.photo_files[draft_id].photos), provider.photo_files[draft_id].next_number), (0, added + 1))
        return controller, provider, draft_id

    def test_the_fake_also_keeps_the_bigger_number_reservation(self):
        controller, provider, draft_id = self.emptied(6)
        status, applied = core_store(controller, "restore")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((controller.photos.count, controller.photos.manifest.next_number, controller.photos_unsaved()), (2, 7, False))
        self.assertEqual((len(provider.photo_files[draft_id].photos), provider.photo_files[draft_id].next_number), (2, 7))
        self.assertNotIn(draft_id, provider.photo_trash)

    def test_the_fake_with_a_smaller_or_equal_reservation_gives_the_copy_back_as_it_was(self):
        for added, name in ((1, "작은 예약"), (2, "같은 예약")):
            with self.subTest(live=name):
                controller, provider, draft_id = self.emptied(added)
                status, applied = core_store(controller, "restore")
                self.assertEqual((status, applied), ("started", True))
                self.assertEqual((controller.photos.count, controller.photos.manifest.next_number), (2, 3))
                self.assertEqual(provider.photo_files[draft_id].next_number, 3)


if __name__ == "__main__":
    unittest.main()
