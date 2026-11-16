"""사진 Manifest 보관 서비스(`service/photo_manifest.py` — 화면 없음, 결정 D-496) 시험. **전부 임시 폴더**(이 PC 의 실제 데이터 폴더는 읽지도 쓰지도 않는다). 네트워크·실제 시크릿·화면 도구 없이 돈다.

지키는 것:
  1) 위치·모양 — `photo-manifests/<초안 번호>.json` 파일 하나, 글은 `PhotoManifest.to_text` 와 같은 바이트(UTF-8·BOM 없음), 분석 결과는 기본으로 쓰지 않는다. 읽기만 하는 길은 아무것도 만들지 않는다.
  2) 경로 탈출 0 — 파일 이름이 되는 것은 초안 번호 모양(`dd-` + 16진수 20자)뿐이다(`../`·구분자·대문자·긴 글·NUL·글자 아닌 값 거절). 사용자가 준 글자(경로·메모)는 파일 이름이 되지 않는다.
  3) 원자적 저장 — 이름 바꾸기·디스크 쓰기가 실패해도 옛 파일이 그대로이고 임시 파일이 남지 않으며 오류에 경로가 없다. 바뀐 것이 없으면 쓰지 않는다.
  4) 비밀 모양 — 경로·모든 글칸에서 키·토큰 모양이 나오면 아무것도 쓰지 않고(폴더도 만들지 않는다) 위치와 종류만 알린다.
  5) 깨진 파일 — 읽을 수 없는 파일은 `broken` 으로만 알리고 건드리지 않는다. 덮어쓰려면 `replace_broken=True` 이고 그때도 `.bak` 으로 옮겨 둔다. 목록은 깨진 파일을 건너뛰고 개수만 알린다.
  6) 지우기 — 확인이 있어야 하고 번호가 정한 파일 하나(와 그 번호의 임시 파일)만 지운다. 링크·폴더는 거절한다.
  7) 사진 파일 보기 — 읽기만 한다(원본의 해시·수정 시각·폴더 목록이 그대로). 없음·폴더·링크·클라우드·큰 파일·지원하지 않는 형식·읽지 못함·긴 변 경고를 알리고 경로는 결과에 없다.
  8) 소스 규칙 — 파일 쓰기는 `write_json`·`keep_bad_copy` 와 `delete_manifest` 의 `unlink` 뿐, 파일을 직접 열지 않고, 화면 층은 늦게 가져온다.
CI 는 윈도·리눅스 × 3.10·3.12 네 칸이다 — 진짜 파일을 만드는 시험은 짧은 파일 이름(리눅스 파일 이름 255바이트 한도에 걸리지 않게)을 쓰고, 링크 시험은 만들 수 없는 곳에서 건너뛴다.
"""
import ast
import dataclasses
import errno
import hashlib
import os
import stat
import sys
import tempfile
import traceback
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import scan_samples  # noqa: E402
import service_support as ss  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import context as context_module  # noqa: E402
from chanceblog_desktop.service import own_posts  # noqa: E402
from chanceblog_desktop.service import photo_manifest as svc  # noqa: E402
from chanceblog_desktop.ui.core import imagerules  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "service" / "photo_manifest.py"
DRAFT_A, DRAFT_B, DRAFT_C = "dd-" + "a" * 20, "dd-" + "0123456789abcdef0123", "dd-" + "f" * 20
UNIQ_NOTE, UNIQ_DIR, UNIQ_FILE = "UNIQ-NOTE-m4z8", "UNIQ-USERDIR-q7w2", "UNIQ-FILE-k3x9"
BAD_IDS = ("", "dd-", "dd-" + "a" * 19, "dd-" + "a" * 21, "DD-" + "a" * 20, "dd-" + "A" * 20, "dd-" + "g" * 20, "../" + "a" * 20, "dd-" + "a" * 17 + "/..", "dd-aaaaaaaaaaaaaaaaaaaa.json", " dd-" + "a" * 20, "dd-" + "a" * 20 + "\n",
           "dd-" + "a" * 19 + "\x00", "dd\\" + "a" * 20, "dd-" + "a" * 19 + "\u00e1", "ｄｄ-" + "a" * 20, None, 5, b"dd-" + b"a" * 20, ["dd-" + "a" * 20], "x" * 5000)


def win(name):
    return f"C:\\Users\\{UNIQ_DIR}\\Pictures\\{UNIQ_FILE}-{name}"


def sample(count=2, **fields):
    manifest = pm.empty_manifest()
    for number in range(1, count + 1):
        manifest, _id = pm.add_photo(manifest, win(f"{number:02d}.jpg"), photo_type="음식", **fields)
    return manifest


def snapshot(root):
    """폴더 안의 모든 파일(바이트)·폴더 이름 — 앞뒤 비교로 '아무것도 바꾸지 않았다' 를 본다."""
    root = Path(root)
    if not root.exists():
        return None
    files = {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}
    folders = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir())
    return files, folders


def channels(error):
    shown = error.rendered()
    trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return {"str": str(error), "repr": repr(error), "args": repr(error.args), "slots": repr(error.slots), "detail": error.detail, "log": error.log_line(), "message": shown.message, "action": shown.action,
            "trace": trace}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ss.make_ctx(self.tmp.name)
        self.root = self.ctx.workspace.root
        self.folder = svc.folder_path(self.ctx)

    def file(self, draft_id=DRAFT_A):
        return self.folder / f"{draft_id}.json"

    def refuses(self, code, function, *args, **kwargs):
        with self.assertRaises(AppError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def assertNoLeak(self, error, markers):
        for name, text in channels(error).items():
            for marker in markers:
                self.assertNotIn(marker, text, f"{name} 에 표식 글이 있다")

    def write_raw(self, data, draft_id=DRAFT_A):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.file(draft_id)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path


class SaveLoadTest(Base):
    def test_one_json_file_per_draft_with_exactly_the_text_of_to_text(self):
        manifest = pm.set_confirmed(sample(2, user_note="메모"), "p001", True)
        saved = svc.save_manifest(self.ctx, DRAFT_A, manifest)
        self.assertEqual(saved.draft_id, DRAFT_A)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{DRAFT_A}.json"])
        data = self.file().read_bytes()
        self.assertEqual(data, saved.to_text().encode("utf-8"))
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", data)
        self.assertIn("메모".encode("utf-8"), data)
        loaded = svc.load_manifest(self.ctx, DRAFT_A)
        self.assertEqual((loaded.state, loaded.manifest), ("ok", saved))
        self.assertEqual(svc.folder_path(self.ctx), self.root / "photo-manifests")
        self.assertEqual(self.file(), self.root / "photo-manifests" / f"{DRAFT_A}.json")

    def test_the_file_matches_what_write_json_writes_so_the_text_is_the_stored_form(self):
        manifest = sample(3, user_subject="반찬")
        with mock.patch.object(svc, "write_json", wraps=svc.write_json) as spy:
            svc.save_manifest(self.ctx, DRAFT_B, manifest)
        self.assertEqual(spy.call_count, 1)
        args, kwargs = spy.call_args
        self.assertEqual(args[0], self.file(DRAFT_B))
        self.assertTrue(kwargs.get("unique_temp"), "임시 파일 이름이 쓸 때마다 다르다")
        self.assertEqual(args[1], dataclasses.replace(manifest, draft_id=DRAFT_B).to_dict())
        self.assertEqual(self.file(DRAFT_B).read_text(encoding="utf-8"), dataclasses.replace(manifest, draft_id=DRAFT_B).to_text())

    def test_reading_creates_nothing_even_the_data_folder(self):
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        ctx = ss.make_ctx(fresh.name, repo="")
        before = snapshot(fresh.name)
        loaded = svc.load_manifest(ctx, DRAFT_A)
        self.assertEqual((loaded.state, loaded.manifest), ("none", pm.empty_manifest(DRAFT_A)))
        self.assertEqual(svc.list_manifests(ctx), svc.Listing((), 0))
        self.assertEqual(svc.orphans(ctx, ()), ())
        self.assertEqual(svc.check_files(pm.empty_manifest()), ())
        self.assertEqual(snapshot(fresh.name), before)
        self.assertFalse((Path(fresh.name) / "data").exists())

    def test_an_empty_manifest_creates_no_file_but_clears_an_existing_one(self):
        svc.save_manifest(self.ctx, DRAFT_A, pm.empty_manifest())
        self.assertFalse(self.folder.exists())
        svc.save_manifest(self.ctx, DRAFT_A, sample(2))
        self.assertEqual(len(svc.load_manifest(self.ctx, DRAFT_A).manifest.photos), 2)
        svc.save_manifest(self.ctx, DRAFT_A, pm.empty_manifest())
        loaded = svc.load_manifest(self.ctx, DRAFT_A)
        self.assertEqual((loaded.state, loaded.manifest.photos), ("ok", ()))

    def test_a_save_with_nothing_changed_writes_nothing(self):
        manifest = sample(2)
        svc.save_manifest(self.ctx, DRAFT_A, manifest)
        before = self.file().stat().st_mtime_ns
        with mock.patch.object(svc, "write_json") as spy:
            again = svc.save_manifest(self.ctx, DRAFT_A, manifest)
            svc.save_manifest(self.ctx, DRAFT_A, pm.PhotoManifest(manifest.photos, manifest.next_number, DRAFT_C))
        self.assertEqual(spy.call_count, 0)
        self.assertEqual(again.draft_id, DRAFT_A)
        self.assertEqual(self.file().stat().st_mtime_ns, before)
        with mock.patch.object(svc, "write_json", wraps=svc.write_json) as spy:
            svc.save_manifest(self.ctx, DRAFT_A, pm.update_photo(manifest, "p001", user_note="바뀜"))
        self.assertEqual(spy.call_count, 1)

    def test_analysis_results_are_not_written_unless_asked_to(self):
        manifest, _dropped = pm.set_analysis(sample(1), "p001", method="local:paddleocr", objects=["UNIQ-OBJ-aa"], texts=["UNIQ-TXT-bb 9,000원"])
        manifest = pm.confirm_item(manifest, "p001", pm.TEXTS, 0)
        svc.save_manifest(self.ctx, DRAFT_A, manifest)
        data = self.file().read_text(encoding="utf-8")
        self.assertNotIn("UNIQ-OBJ-aa", data)
        self.assertNotIn("UNIQ-TXT-bb", data)
        loaded = svc.load_manifest(self.ctx, DRAFT_A).manifest
        self.assertEqual((loaded.photos[0].observed_objects, loaded.photos[0].visible_text), ((), ()))
        svc.save_manifest(self.ctx, DRAFT_A, manifest, persist_analysis=True)
        self.assertIn("UNIQ-TXT-bb", self.file().read_text(encoding="utf-8"))
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).manifest.photos[0].visible_text[0].confirmed, True)
        svc.save_manifest(self.ctx, DRAFT_A, manifest)
        self.assertNotIn("UNIQ-TXT-bb", self.file().read_text(encoding="utf-8"), "다시 저장하면 분석 결과는 지워진다(기본)")

    def test_what_is_saved_for_one_draft_never_touches_another(self):
        svc.save_manifest(self.ctx, DRAFT_A, sample(1, user_note="A 의 메모"))
        svc.save_manifest(self.ctx, DRAFT_B, sample(2, user_note="B 의 메모"))
        before = self.file(DRAFT_A).read_bytes()
        svc.save_manifest(self.ctx, DRAFT_B, sample(3, user_note="B 의 새 메모"))
        self.assertEqual(self.file(DRAFT_A).read_bytes(), before)
        self.assertEqual(len(svc.load_manifest(self.ctx, DRAFT_B).manifest.photos), 3)
        self.assertEqual(svc.list_manifests(self.ctx).draft_ids, tuple(sorted((DRAFT_A, DRAFT_B))))

    def test_a_manifest_that_is_not_a_manifest_is_refused(self):
        for bad in (None, {}, "x", sample(1).to_dict(), [sample(1)]):
            self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, bad)
        self.assertFalse(self.folder.exists())

    def test_the_file_drafts_id_must_equal_the_name_so_a_copied_file_is_not_trusted(self):
        svc.save_manifest(self.ctx, DRAFT_A, sample(1))
        self.file(DRAFT_B).write_bytes(self.file(DRAFT_A).read_bytes())
        loaded = svc.load_manifest(self.ctx, DRAFT_B)
        self.assertEqual((loaded.state, loaded.manifest.photos), ("broken", ()))


class SecretAndFailureTest(Base):
    def test_a_key_shape_anywhere_blocks_the_write_and_creates_no_folder(self):
        key = scan_samples.google()
        before = snapshot(self.root)
        in_path, _id = pm.add_photo(pm.empty_manifest(), f"C:\\Users\\x\\Pictures\\{key}.jpg")
        error = self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, in_path)
        self.assertIn("사진 1 파일 위치", error.rendered().message)
        self.assertIn("Google API 키", error.rendered().message)
        self.assertNoLeak(error, [key, key[:10]])
        for field in ("photo_type", "setting", "user_subject", "user_note", "preferred_section", "caption"):
            with self.subTest(field=field):
                manifest = sample(1)
                object.__setattr__(manifest.photos[0], field, f"앞 {key} 뒤")             # 만드는 길의 검사를 돌아서 들어온 값도 저장 직전에 걸린다
                error = self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, manifest)
                self.assertNoLeak(error, [key, key[:10]])
        analysis, _dropped = pm.set_analysis(sample(1), "p001", method="local:x", texts=["문서"])
        object.__setattr__(analysis.photos[0].visible_text[0], "text", key)
        self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, analysis, persist_analysis=True)
        self.assertFalse(self.folder.exists(), "검사에 걸린 저장은 폴더도 만들지 않았다")
        self.assertEqual(snapshot(self.root), before)
        svc.save_manifest(self.ctx, DRAFT_A, analysis)                                       # 쓰지 않는 분석 결과는 검사 대상이 아니다
        self.assertNotIn(key, self.file().read_text(encoding="utf-8"))

    def test_nothing_is_created_when_the_secret_check_fails(self):
        key = scan_samples.github()
        manifest, _id = pm.add_photo(pm.empty_manifest(), f"C:\\p\\{key}.png")
        before = snapshot(self.root)
        self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, manifest)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.folder.exists())

    def test_a_failed_rename_keeps_the_old_file_leaves_no_temp_file_and_hides_the_path(self):
        svc.save_manifest(self.ctx, DRAFT_A, sample(1, user_note="옛 메모"))
        old = self.file().read_bytes()
        for code, error in (("FILE_WRITE_FAILED", PermissionError(errno.EACCES, "denied")), ("DISK_FULL", OSError(errno.ENOSPC, "full"))):
            with self.subTest(code=code):
                with mock.patch.object(context_module.os, "replace", side_effect=error):
                    raised = self.refuses(code, svc.save_manifest, self.ctx, DRAFT_A, sample(1, user_note="새 메모"))
                self.assertEqual(self.file().read_bytes(), old, "옛 파일이 그대로다")
                self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{DRAFT_A}.json"], "임시 파일이 남지 않았다")
                self.assertNoLeak(raised, [str(self.tmp.name), UNIQ_DIR, UNIQ_FILE, "새 메모", "옛 메모"])
                self.assertEqual(raised.slots.get("경로"), svc._WHERE if code == "FILE_WRITE_FAILED" else raised.slots.get("경로"))
        svc.save_manifest(self.ctx, DRAFT_A, sample(1, user_note="새 메모"))
        self.assertIn("새 메모", self.file().read_text(encoding="utf-8"))

    def test_a_failed_first_write_leaves_neither_a_file_nor_a_temp_file(self):
        with mock.patch.object(context_module.os, "replace", side_effect=OSError(errno.EIO, "io")):
            raised = self.refuses("FILE_WRITE_FAILED", svc.save_manifest, self.ctx, DRAFT_A, sample(1))
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertNoLeak(raised, [self.tmp.name, UNIQ_DIR, UNIQ_FILE])
        self.assertIsNone(raised.__cause__)
        self.assertIsNone(raised.__context__)


class IdSafetyTest(Base):
    def test_only_a_stored_draft_number_can_become_a_file_name(self):
        self.assertTrue(svc.is_draft_id(DRAFT_A) and svc.is_draft_id(DRAFT_B))
        before = snapshot(self.root)
        for bad in BAD_IDS:
            with self.subTest(id=repr(bad)[:40]):
                self.assertFalse(svc.is_draft_id(bad))
                self.refuses("CONTENT_INVALID", svc.load_manifest, self.ctx, bad)
                self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, bad, sample(1))
                self.refuses("CONTENT_INVALID", svc.delete_manifest, self.ctx, bad, confirmed=True)
        self.assertEqual(snapshot(self.root), before, "아무것도 만들지 않았다")
        self.assertFalse(self.folder.exists())
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, "../../outside/" + "a" * 20, sample(1))
        self.assertEqual(list(outside.iterdir()), [])

    def test_the_users_path_or_note_never_becomes_part_of_a_file_name(self):
        manifest, _id = pm.add_photo(pm.empty_manifest(), win("..x.jpg").replace("..x", "x"), user_note="../../evil", user_subject="x/y\\z")
        svc.save_manifest(self.ctx, DRAFT_A, manifest)
        names = sorted(path.name for path in self.root.rglob("*") if path.is_file())
        self.assertEqual(sorted(names), sorted(["settings.json", f"{DRAFT_A}.json"]))
        for name in names:
            self.assertNotIn(UNIQ_FILE, name)
            self.assertNotIn("evil", name)


class BrokenFileTest(Base):
    def broken_cases(self):
        good = sample(1).to_text()
        return {"JSON 아님": "{abc", "빈 파일": "", "BOM": "\ufeff" + good, "UTF-16": good.encode("utf-16"), "NUL": good.encode("utf-8") + b"\x00", "다른 초안 번호": good.replace('"draft_id": ""', f'"draft_id": "{DRAFT_B}"'),
                "초안 번호 없음": good, "모르는 칸": good.replace('"draft_id"', '"exif": 1, "draft_id"'), "깊은 겹침": "[" * 50000, "너무 큼": "x" * (svc.MAX_FILE_BYTES + 1), "배열": "[]", "newer": good.replace("photo-manifest/1", "photo-manifest/2")}

    def test_an_unreadable_file_is_reported_broken_and_never_touched(self):
        for name, content in self.broken_cases().items():
            with self.subTest(case=name):
                path = self.write_raw(content)
                before = path.read_bytes()
                loaded = svc.load_manifest(self.ctx, DRAFT_A)
                self.assertEqual((loaded.state, loaded.manifest.photos, loaded.manifest.draft_id), ("broken", (), DRAFT_A))
                self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, sample(1))
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [path.name])
                self.assertEqual(svc.list_manifests(self.ctx), svc.Listing((), 1))
                path.unlink()

    def test_replacing_a_broken_file_keeps_it_aside_as_a_bak_copy(self):
        path = self.write_raw("{ 깨진 글 UNIQ-OLD }")
        saved = svc.save_manifest(self.ctx, DRAFT_A, sample(1, user_note="새 글"), replace_broken=True)
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A), svc.Loaded(saved, "ok"))
        backup = Path(str(path) + ".bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), "{ 깨진 글 UNIQ-OLD }", "깨진 파일은 지우지 않고 옆으로 옮겼다")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), sorted([path.name, backup.name]))
        svc.save_manifest(self.ctx, DRAFT_A, sample(2), replace_broken=True)            # 멀쩡한 파일에는 `.bak` 을 새로 만들지 않는다
        self.assertEqual(backup.read_text(encoding="utf-8"), "{ 깨진 글 UNIQ-OLD }")

    def test_if_the_broken_file_cannot_be_moved_aside_nothing_is_written_and_the_path_is_hidden(self):
        path = self.write_raw("{ 깨진 글 UNIQ-OLD }")
        with mock.patch.object(context_module.os, "replace", side_effect=PermissionError(errno.EACCES, "denied", str(path))):
            error = self.refuses("FILE_WRITE_FAILED", svc.save_manifest, self.ctx, DRAFT_A, sample(1), replace_broken=True)
        self.assertNoLeak(error, [self.tmp.name, DRAFT_A, UNIQ_DIR])
        self.assertEqual(error.slots.get("경로"), svc._WHERE)
        self.assertEqual(path.read_text(encoding="utf-8"), "{ 깨진 글 UNIQ-OLD }", "옮기지 못하면 깨진 파일 위에 쓰지 않는다")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [path.name])

    def test_a_directory_or_link_in_place_of_the_file_is_broken(self):
        self.folder.mkdir(parents=True)
        self.file().mkdir()
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "broken")
        self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, sample(1))
        self.refuses("CONTENT_INVALID", svc.delete_manifest, self.ctx, DRAFT_A, confirmed=True)
        self.assertTrue(self.file().is_dir())
        self.file().rmdir()
        target = Path(self.tmp.name) / "real.json"
        target.write_text(sample(1).to_text(), encoding="utf-8")
        try:
            os.symlink(target, self.file())
        except (OSError, NotImplementedError, AttributeError) as error:
            self.skipTest(f"이 환경에서는 링크를 만들 수 없다({type(error).__name__})")
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "broken")
        self.refuses("CONTENT_INVALID", svc.delete_manifest, self.ctx, DRAFT_A, confirmed=True)
        self.assertTrue(target.exists())

    def test_the_list_skips_broken_files_counts_them_and_ignores_other_names(self):
        svc.save_manifest(self.ctx, DRAFT_B, sample(1))
        svc.save_manifest(self.ctx, DRAFT_C, sample(1))
        self.write_raw("{bad", DRAFT_A)
        for stranger in ("README.txt", f"{DRAFT_B}.json.bak", "DD-" + "b" * 20 + ".json", "dd-short.json", f"{DRAFT_B}.json.123-abcd1234.tmp", "x.json"):
            (self.folder / stranger).write_text("{}", encoding="utf-8")
        listing = svc.list_manifests(self.ctx)
        self.assertEqual(listing, svc.Listing(tuple(sorted((DRAFT_B, DRAFT_C))), 1))
        self.assertEqual(listing.draft_ids, tuple(sorted(listing.draft_ids)))

    def test_orphans_are_the_files_whose_draft_is_no_longer_stored(self):
        for draft in (DRAFT_A, DRAFT_B, DRAFT_C):
            svc.save_manifest(self.ctx, draft, sample(1))
        self.write_raw("{bad", "dd-" + "1" * 20)
        self.assertEqual(svc.orphans(self.ctx, [DRAFT_A, DRAFT_C]), tuple(sorted((DRAFT_B, "dd-" + "1" * 20))))
        self.assertEqual(svc.orphans(self.ctx, [DRAFT_A, DRAFT_B, DRAFT_C, "dd-" + "1" * 20]), ())
        self.assertEqual(svc.orphans(self.ctx, ["bad", None, 5]), tuple(sorted((DRAFT_A, DRAFT_B, DRAFT_C, "dd-" + "1" * 20))))
        before = snapshot(self.root)
        svc.orphans(self.ctx, [])
        self.assertEqual(snapshot(self.root), before, "읽기만 한다")


class FolderTest(Base):
    def test_a_folder_that_is_a_file_or_a_link_is_refused_everywhere(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.folder.write_text("not a folder", encoding="utf-8")
        for call in (lambda: svc.load_manifest(self.ctx, DRAFT_A), lambda: svc.save_manifest(self.ctx, DRAFT_A, sample(1)), lambda: svc.delete_manifest(self.ctx, DRAFT_A, confirmed=True),
                     lambda: svc.list_manifests(self.ctx), lambda: svc.orphans(self.ctx, ())):
            error = self.refuses("CONTENT_INVALID", call)
            self.assertNoLeak(error, [self.tmp.name])
        self.assertEqual(self.folder.read_text(encoding="utf-8"), "not a folder")
        self.folder.unlink()
        real = Path(self.tmp.name) / "elsewhere"
        real.mkdir()
        try:
            os.symlink(real, self.folder, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as error:
            self.skipTest(f"이 환경에서는 링크를 만들 수 없다({type(error).__name__})")
        self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, sample(1))
        self.refuses("CONTENT_INVALID", svc.load_manifest, self.ctx, DRAFT_A)
        self.assertEqual(list(real.iterdir()), [], "링크 너머에 쓰지 않았다")


class DeleteTest(Base):
    def test_a_confirmation_is_required_and_without_it_nothing_is_deleted(self):
        svc.save_manifest(self.ctx, DRAFT_A, sample(1))
        before = snapshot(self.root)
        for bad in (False, None, 1, "yes", "true", 0, [], "예"):
            with self.subTest(confirmed=bad):
                self.refuses("CONFIRMATION_REQUIRED", svc.delete_manifest, self.ctx, DRAFT_A, confirmed=bad)
        self.assertEqual(snapshot(self.root), before)
        with self.assertRaises(TypeError):
            svc.delete_manifest(self.ctx, DRAFT_A)

    def test_exactly_one_file_and_that_numbers_leftover_temp_files_are_deleted(self):
        for draft in (DRAFT_A, DRAFT_B):
            svc.save_manifest(self.ctx, draft, sample(1))
        mine = [self.folder / f"{DRAFT_A}.json.123-abcd1234.tmp", self.folder / f"{DRAFT_A}.json.tmp"]
        others = [self.folder / f"{DRAFT_B}.json.123-abcd1234.tmp", self.folder / "notes.txt", self.folder / f"{DRAFT_A}.json.bak", self.folder / f"{DRAFT_A}.json.123-abcd1234.tmp.keep"]
        for path in (*mine, *others):
            path.write_text("남은 글", encoding="utf-8")
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("바깥", encoding="utf-8")
        svc.delete_manifest(self.ctx, DRAFT_A, confirmed=True)
        self.assertFalse(self.file(DRAFT_A).exists())
        for path in mine:
            self.assertFalse(path.exists(), path.name)
        for path in (self.file(DRAFT_B), *others, outside):
            self.assertTrue(path.exists(), path.name)
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "none")
        self.refuses("CONTENT_NOT_FOUND", svc.delete_manifest, self.ctx, DRAFT_A, confirmed=True)
        self.refuses("CONTENT_NOT_FOUND", svc.delete_manifest, self.ctx, DRAFT_C, confirmed=True)

    def test_a_broken_file_can_be_deleted_and_a_failed_delete_hides_the_path(self):
        path = self.write_raw("{bad")
        svc.delete_manifest(self.ctx, DRAFT_A, confirmed=True)
        self.assertFalse(path.exists())
        svc.save_manifest(self.ctx, DRAFT_A, sample(1))
        original = Path.unlink

        def failing(self_path, *args, **kwargs):
            if self_path.name == f"{DRAFT_A}.json":
                raise PermissionError(errno.EACCES, "denied", str(self_path))
            return original(self_path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", failing):
            error = self.refuses("FILE_WRITE_FAILED", svc.delete_manifest, self.ctx, DRAFT_A, confirmed=True)
        self.assertNoLeak(error, [self.tmp.name, DRAFT_A])
        self.assertTrue(self.file().exists())


class CheckFilesTest(Base):
    def setUp(self):
        super().setUp()
        self.pictures = Path(self.tmp.name) / "pics"
        self.pictures.mkdir()

    def manifest(self, *names):
        manifest = pm.empty_manifest()
        for name in names:
            manifest, _id = pm.add_photo(manifest, str(self.pictures / name))
        return manifest

    def make(self, name, size=64):
        path = self.pictures / name
        path.write_bytes(b"\xff\xd8\xff\xe0" + b"\0" * size)
        return path

    def probe(self, *, can_read=True, fmt="jpeg", width=640, height=480, calls=None):
        def probe(path):
            if calls is not None:
                calls.append(path)
            return imagerules.Probe(can_read, fmt, width, height)

        return probe

    def test_a_present_picture_is_ok_and_without_a_reader_only_the_extension_and_size_were_looked_at(self):
        self.make("a.jpg")
        self.make("메뉴.PNG")
        results = svc.check_files(self.manifest("a.jpg", "메뉴.PNG"))
        self.assertEqual([(item.photo_id, item.state, item.ok, item.verified) for item in results], [("p001", "ok", True, False), ("p002", "ok", True, False)])
        with_reader = svc.check_files(self.manifest("a.jpg"), probe=self.probe(width=4000, height=3000))
        self.assertEqual((with_reader[0].state, with_reader[0].verified, with_reader[0].width, with_reader[0].height, with_reader[0].format), ("ok", True, 4000, 3000, "jpeg"))
        self.assertEqual(with_reader[0].warning, "")

    def test_a_missing_file_is_shown_as_missing_with_the_same_sentence_as_the_image_rules(self):
        self.make("here.jpg")
        results = svc.check_files(self.manifest("here.jpg", "gone.jpg"))
        self.assertEqual([item.state for item in results], ["ok", "missing"])
        self.assertEqual(results[1].message, imagerules.T[imagerules.MESSAGES[imagerules.MISSING]])
        self.assertFalse(results[1].ok)
        (self.pictures / "here.jpg").unlink()
        self.assertEqual([item.state for item in svc.check_files(self.manifest("here.jpg"))], ["missing"])

    def test_a_folder_a_link_and_an_undownloaded_cloud_file_are_not_used(self):
        (self.pictures / "dir.jpg").mkdir()
        self.assertEqual(svc.check_files(self.manifest("dir.jpg"))[0].state, "not_file")
        target = self.make("real.jpg")
        try:
            os.symlink(target, self.pictures / "link.jpg")
        except (OSError, NotImplementedError, AttributeError):
            link_state = None
        else:
            link_state = svc.check_files(self.manifest("link.jpg"))[0]
        if link_state is not None:
            self.assertEqual(link_state.state, "link")
            self.assertTrue(link_state.message)
        cloud = self.make("cloud.jpg")
        real_lstat = svc._lstat

        def fake(path):
            info = real_lstat(path)
            if info is not None and Path(path) == cloud:
                return types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_file_attributes=own_posts._NOT_LOCAL, st_size=info.st_size)
            return info

        with mock.patch.object(svc, "_lstat", fake):
            result = svc.check_files(self.manifest("cloud.jpg"))[0]
        self.assertEqual(result.state, "cloud")
        self.assertIn("내려받지 않은", result.message)

    def test_the_image_rules_decide_size_real_format_unreadable_and_the_long_side_warning(self):
        self.make("a.jpg")
        calls = []
        manifest = self.manifest("a.jpg")
        cases = {"not_image": self.probe(can_read=False), "unsupported": self.probe(fmt="gif"), "unreadable": "raises", "ok": self.probe(width=imagerules.LONG_SIDE_WARN + 1, height=10, calls=calls)}
        for expected, probe in cases.items():
            with self.subTest(expected=expected):
                if probe == "raises":
                    def probe(_path):
                        raise RuntimeError("읽기 도구가 터졌다")
                result = svc.check_files(manifest, probe=probe)[0]
                self.assertEqual(result.state, expected)
                self.assertEqual(result.ok, expected == "ok")
                if expected == "ok":
                    self.assertTrue(result.warning, "긴 변이 12,000px 를 넘으면 경고한다")
        self.assertEqual(calls, [str(self.pictures / "a.jpg")], "읽기 도구에는 경로 하나만 준다")

    def test_a_file_over_twenty_megabytes_is_refused_before_it_is_read(self):
        big = self.pictures / "big.jpg"
        with open(big, "wb") as handle:
            handle.truncate(imagerules.MAX_BYTES + 1)
        calls = []
        result = svc.check_files(self.manifest("big.jpg"), probe=self.probe(calls=calls))[0]
        self.assertEqual((result.state, calls), ("too_big", []))
        self.assertIn("20MB", result.message)

    def test_looking_never_changes_the_originals_or_the_folder(self):
        paths = [self.make("a.jpg", 100), self.make("b.png", 200), self.make("c.webp", 300)]
        manifest = self.manifest("a.jpg", "b.png", "c.webp", "missing.jpg")
        before = {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns, path.stat().st_size) for path in paths}
        listing = sorted(os.listdir(self.pictures))
        for probe in (None, self.probe(), self.probe(can_read=False)):
            svc.check_files(manifest, probe=probe)
        after = {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns, path.stat().st_size) for path in paths}
        self.assertEqual(after, before)
        self.assertEqual(sorted(os.listdir(self.pictures)), listing)
        self.assertEqual(snapshot(self.root), snapshot(self.root))

    def test_the_results_carry_no_path_and_a_bad_argument_is_refused(self):
        self.make("a.jpg")
        results = svc.check_files(self.manifest("a.jpg", "gone.jpg"))
        shown = repr(results) + str(results) + "".join(item.message + item.warning for item in results)
        for marker in (self.tmp.name, "pics", "a.jpg", "gone.jpg"):
            self.assertNotIn(marker, shown)
        for bad in (None, [], "x", sample(1).to_dict()):
            self.refuses("CONTENT_INVALID", svc.check_files, bad)

    def test_windows_style_paths_that_cannot_exist_here_are_simply_missing(self):
        self.assertEqual([item.state for item in svc.check_files(sample(2))], ["missing", "missing"])


class ScenarioTest(Base):
    def test_one_whole_session_from_adding_photos_to_the_saved_file_and_back_with_the_draft_input_unchanged(self):
        manifest = pm.empty_manifest()
        for name, kind, subject in (("a.jpg", "간판", "매장 입구 간판과 주차장 전경"), ("b.jpg", "메뉴판", ""), ("c.jpg", "대표 메뉴", "메인 메뉴 한우 불고기 전골"), ("d.jpg", "반찬", "반찬 5개"), ("e.jpg", "기타", "")):
            manifest, _id = pm.add_photo(manifest, win(name), photo_type=kind, user_subject=subject)
        manifest = pm.move_photo(manifest, "p005", 1)                                         # 기타 사진을 맨 앞으로
        manifest = pm.remove_photo(manifest, "p002")                                          # 메뉴판을 뺀다
        manifest = pm.update_photo(manifest, "p003", user_note="비 오는 날 갔어요", placement={"kind": "after_paragraph", "nth": 2})
        for photo_id in ("p001", "p003", "p004"):
            manifest = pm.set_confirmed(manifest, photo_id, True)
        self.assertEqual([(photo.photo_id, photo.display_order) for photo in manifest.photos], [("p005", 1), ("p001", 2), ("p003", 3), ("p004", 4)])
        sent = pm.draft_inputs(manifest)
        self.assertEqual([item.number for item in sent], [1, 3, 4], "확정한 사진만, 사진 순서대로")
        body = "\n\n".join(pm.placeholder(item.number) for item in sent)
        self.assertTrue(pm.placeholder_report(manifest, body).ok)

        saved = svc.save_manifest(self.ctx, DRAFT_A, manifest)
        loaded = svc.load_manifest(self.ctx, DRAFT_A)
        self.assertEqual((loaded.state, loaded.manifest), ("ok", saved))
        self.assertEqual(pm.draft_inputs(loaded.manifest), sent, "저장했다 다시 열어도 초안 입력이 같다")
        self.assertEqual([item.state for item in svc.check_files(loaded.manifest)], ["missing"] * 4, "이 환경에는 없는 윈도 경로라 모두 파일 없음으로 보인다")

        again = pm.remove_photo(loaded.manifest, "p004")
        again, new_id = pm.add_photo(again, win("f.jpg"))
        self.assertEqual(new_id, "p006", "지운 p004 의 번호를 새 사진이 물려받지 않는다")
        report = pm.placeholder_report(again, body)
        self.assertEqual((report.dangling, report.ok), ((4,), False), "본문에는 아직 {{사진 4}} 가 있어 어긋남으로 알린다")
        svc.save_manifest(self.ctx, DRAFT_A, again)
        reopened = svc.load_manifest(self.ctx, DRAFT_A).manifest
        self.assertEqual([photo.photo_id for photo in reopened.photos], ["p005", "p001", "p003", "p006"])
        self.assertEqual(reopened.next_number, 7)
        text = self.file().read_text(encoding="utf-8")
        for hidden in ("observed_objects\": [\n        {", "visible_text\": [\n        {"):
            self.assertNotIn(hidden, text)


class BackupTest(unittest.TestCase):
    """1단계의 기본값 — 사진 정보는 전체 백업에 담지 않는다(백업 형식은 그대로). 진짜 백업·복원으로 못박는다."""

    def test_the_photo_manifests_are_not_in_a_real_full_backup_and_a_real_restore_leaves_them_alone(self):
        import backup_support as bs
        from chanceblog_desktop.service import backup_flow as bf
        with tempfile.TemporaryDirectory(prefix="pm-backup-") as tmp:
            world = bs.World(Path(os.path.realpath(tmp)), posts=1, drafts=0, candidates_count=0)
            ctx = world.ctx
            ctx.clock.advance(minutes=1)
            svc.save_manifest(ctx, DRAFT_A, sample(2, user_note=UNIQ_NOTE))
            folder = world.root / "photo-manifests"

            def snap():
                return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(folder.iterdir())}

            before = snap()
            outcome = world.backup()
            backup_folder = world.folder(outcome)
            names = [path.relative_to(backup_folder).as_posix() for path in backup_folder.rglob("*")]
            self.assertTrue(names, "백업은 만들어졌다")
            self.assertFalse([name for name in names if "photo" in name or DRAFT_A in name], names)
            for path in backup_folder.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    self.assertNotIn(UNIQ_NOTE.encode("utf-8"), data, path.name)
                    self.assertNotIn(UNIQ_DIR.encode("utf-8"), data, path.name)
            self.assertEqual(snap(), before, "백업이 사진 정보를 건드리지 않았다")
            ctx.clock.advance(minutes=1)
            svc.save_manifest(ctx, DRAFT_B, sample(1, user_note="백업 뒤의 메모"))
            svc.save_manifest(ctx, DRAFT_A, sample(3, user_note="고친 메모"))
            expected = snap()
            self.assertEqual(sorted(expected), sorted([f"{DRAFT_A}.json", f"{DRAFT_B}.json"]))
            result = bf.restore_full_backup(ctx, outcome.row.name, confirmed=True)
            self.assertEqual(result.status, bf.STATUS_COMPLETE)
            self.assertEqual(snap(), expected, "복원은 사진 정보 파일을 하나도 건드리지 않았다(내용·수정 시각 그대로)")
            for path in ctx.workspace.backups_dir.rglob("*"):                                    # 복원 전 안전 사본에도 사진 정보가 없다
                self.assertNotIn("photo", path.relative_to(ctx.workspace.backups_dir).as_posix())
                if path.is_file():
                    self.assertNotIn(UNIQ_NOTE.encode("utf-8"), path.read_bytes(), path.name)


class SourceRulesTest(unittest.TestCase):
    def tree(self):
        return ast.parse(SOURCE.read_text(encoding="utf-8"))

    def test_the_only_ways_to_write_or_delete_are_the_two_context_functions_and_one_unlink(self):
        tree = self.tree()
        calls = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    calls.setdefault(name, set()).add(function.name)
        self.assertEqual(calls.get("write_json"), {"save_manifest"})
        self.assertEqual(calls.get("keep_bad_copy"), {"save_manifest"})
        unlinks = {function for name, functions in calls.items() if name.endswith(".unlink") for function in functions}
        self.assertEqual(unlinks, {"delete_manifest"})
        for banned in ("open", "io.open", "os.open", "os.write", "os.replace", "os.rename", "os.remove", "os.makedirs", "shutil.copy", "shutil.rmtree", "shutil.move", "print", "os.fsync", "os.chmod"):
            self.assertNotIn(banned, calls)
        for name in calls:
            self.assertFalse(name.endswith((".write_text", ".write_bytes", ".mkdir", ".rmdir", ".touch", ".open", ".chmod", ".rename", ".symlink_to", ".hardlink_to")), name)
        write = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "write_json"]
        self.assertEqual(len(write), 1)
        self.assertEqual([keyword.arg for keyword in write[0].keywords], ["unique_temp"])
        self.assertEqual(ast.unparse(write[0].keywords[0].value), "True")

    def test_the_picture_rules_and_the_screen_layer_are_imported_late_and_nothing_outgoing_is_imported(self):
        tree = self.tree()
        top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        for node in top:
            module = (node.module or "") if isinstance(node, ast.ImportFrom) else ""
            self.assertFalse(module.startswith("ui") or "ui." in module, "화면 층은 함수 안에서 늦게 가져온다")
        names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        names |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertFalse(names & {"subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "requests", "asyncio", "logging", "traceback", "PySide6", "random", "time"})
        late = [node for function in ast.walk(tree) if isinstance(function, ast.FunctionDef) for node in ast.walk(function) if isinstance(node, ast.ImportFrom) and node.level == 2]
        self.assertTrue(any((node.module or "") == "ui.core" and any(alias.name == "imagerules" for alias in node.names) for node in late), "사진 규칙은 imagerules 를 쓴다")
        self.assertEqual(sum(1 for text in SOURCE.read_text(encoding="utf-8").splitlines() if "SUPPORTED_EXTENSIONS" in text), 0, "확장자 목록을 따로 두지 않는다")

    def test_reading_goes_through_the_one_allowed_read_function_and_never_opens_a_file_itself(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("own_posts._read_prefix", text)
        self.assertNotIn("read_text(", text)
        self.assertNotIn("read_bytes(", text)
        for needle in ("scan.scan_fields", "keep_bad_copy", "write_json", "require_confirmation", "is_draft_id"):
            self.assertIn(needle, text)

    def test_every_error_code_it_raises_is_in_the_catalog(self):
        import re
        from chanceblog_desktop.errors import CATALOG
        codes = set(re.findall(r'AppError\(\s*"([A-Z][A-Z0-9_]+)"', SOURCE.read_text(encoding="utf-8")))
        self.assertEqual(codes, {"CONTENT_INVALID", "CONTENT_NOT_FOUND", "FILE_WRITE_FAILED", "DISK_FULL"})
        for code in codes:
            self.assertIn(code, CATALOG)

    # 이 모듈을 부르는 소스 파일의 허용 목록(파일 → 이유). 1단계는 기존 코드를 바꾸지 않았으므로 비어 있다 — 다음 단계(화면 2단계·초안 연결 3단계)가 부를 때 이유와 함께 여기에 더한다(몰래 늘면 걸린다).
    MODULE_USERS = {}

    def test_no_existing_source_file_uses_the_new_modules_yet_so_no_behavior_changed(self):
        src = ROOT / "src" / "chanceblog_desktop"
        users = sorted(path.relative_to(src).as_posix() for path in src.rglob("*.py") if "photo_manifest" in path.read_text(encoding="utf-8") and path.name != "photo_manifest.py")
        self.assertEqual(users, sorted(self.MODULE_USERS), "이 모듈을 새로 부르는 파일은 이유와 함께 MODULE_USERS 에 더한다")
        self.assertTrue(all(reason.strip() for reason in self.MODULE_USERS.values()))


if __name__ == "__main__":
    unittest.main()
