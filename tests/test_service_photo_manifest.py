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
    def good_text(self):
        """멀쩡한 파일의 글 — 이 초안 번호의 것이라서 아래 사례는 각자의 결함 **하나**만 가진다(초안 번호가 빈 표본에서 출발하면 모든 사례가 '이름과 초안 번호가 다름' 으로 이미 깨져 있어 그 결함을 시험하지 못한다 — 검증 Q-3)."""
        return dataclasses.replace(sample(1), draft_id=DRAFT_A).to_text()

    def broken_cases(self):
        good = self.good_text()
        return {"JSON 아님": "{abc", "빈 파일": "", "BOM": chr(0xFEFF) + good, "UTF-16": good.encode("utf-16"), "NUL": good.encode("utf-8") + bytes(1),
                "다른 초안 번호": good.replace(f'"draft_id": "{DRAFT_A}"', f'"draft_id": "{DRAFT_B}"'), "초안 번호 없음": good.replace(f'"draft_id": "{DRAFT_A}"', '"draft_id": ""'),
                "모르는 칸": good.replace('"draft_id"', '"exif": 1, "draft_id"', 1), "깊은 겹침": "[" * 50000, "너무 큼": "x" * (svc.MAX_FILE_BYTES + 1), "배열": "[]", "newer": good.replace("photo-manifest/1", "photo-manifest/2")}

    def test_the_good_sample_itself_loads_so_each_broken_case_has_exactly_its_own_defect(self):
        self.write_raw(self.good_text())
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "ok")
        for name, content in self.broken_cases().items():
            self.assertNotEqual(content, self.good_text(), name)

    def test_a_read_that_fails_is_broken_never_none_and_the_file_is_left_alone(self):
        """검증 Q-3 — 열기 오류가 아닌 읽기 실패(검사와 열기 사이에 파일이 바뀜)는 '없음' 이 아니라 '깨짐' 이다(없음으로 알리면 저장이 그 위에 덮어쓴다). 읽기를 실패하게 바꿔 본다."""
        path = self.write_raw(self.good_text())
        before = path.read_bytes()
        with mock.patch.object(svc, "_pause") as pause, mock.patch.object(own_posts, "_read_prefix", return_value=(None, own_posts._R_CHANGED)):
            loaded = svc.load_manifest(self.ctx, DRAFT_A)
            self.assertEqual((loaded.state, loaded.manifest.photos), ("broken", ()))
            self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, sample(1))
            self.assertEqual(svc.list_manifests(self.ctx), svc.Listing((), 1))
        self.assertEqual(path.read_bytes(), before)
        pause.assert_not_called()                                                         # 열기 오류가 아니면 다시 해 보지 않는다
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [path.name], "읽기 실패가 새 파일·옮긴 파일을 만들지 않는다")
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "ok")

    def test_an_open_error_is_retried_and_a_lasting_one_is_unreadable_never_broken(self):
        """검증 S-2 — '지금 못 엶(윈도의 공유 위반)' 과 '내용이 깨짐' 을 갈라 알린다. 앞의 것은 짧게 두 번 더 해 보고, 계속되면 `unreadable` 이고 `replace_broken` 으로도 그 위에 쓰지 않는다."""
        saved = svc.save_manifest(self.ctx, DRAFT_A, sample(1))
        path = self.file()
        before = path.read_bytes()
        real = own_posts._read_prefix
        calls = {"count": 0}

        def flaky(*args, **kwargs):
            calls["count"] += 1
            return (None, own_posts._R_MISSING) if calls["count"] == 1 else real(*args, **kwargs)

        with mock.patch.object(svc, "_pause") as pause, mock.patch.object(own_posts, "_read_prefix", flaky):
            self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A), svc.Loaded(saved, "ok"), "한 번 못 열고 다시 해 보니 열렸다")
        self.assertEqual([call.args for call in pause.call_args_list], [(0.03,)])
        self.assertEqual(svc.READ_RETRY_WAITS, (0.03, 0.06))
        with mock.patch.object(svc, "_pause") as pause, mock.patch.object(own_posts, "_read_prefix", return_value=(None, own_posts._R_MISSING)):
            loaded = svc.load_manifest(self.ctx, DRAFT_A)
            self.assertEqual((loaded.state, loaded.manifest.photos, loaded.manifest.draft_id), ("unreadable", (), DRAFT_A))
            self.assertEqual([call.args for call in pause.call_args_list], [(0.03,), (0.06,)])
            error = self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, sample(2))
            self.assertNoLeak(error, [self.tmp.name, DRAFT_A])
            self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, sample(2), replace_broken=True)
            self.assertEqual(svc.list_manifests(self.ctx), svc.Listing((), 1))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [path.name], ".bak 도 임시 파일도 만들지 않았다")
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A), svc.Loaded(saved, "ok"))
        self.assertIn("unreadable", svc.STATES)

    def test_a_file_that_vanishes_between_the_check_and_the_open_is_none_not_unreadable(self):
        svc.save_manifest(self.ctx, DRAFT_A, sample(1))
        path = self.file()

        def vanish(*args, **kwargs):
            path.unlink(missing_ok=True)
            return None, own_posts._R_MISSING

        with mock.patch.object(svc, "_pause"), mock.patch.object(own_posts, "_read_prefix", vanish):
            self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "none")

    def test_a_list_too_big_to_read_back_is_refused_before_anything_is_written(self):
        """검증 Q-5 — 읽을 때 512KB 를 넘으면 거절하므로, 쓴 파일을 못 읽는 상태가 되지 않게 쓰기 전에 막는다(분석 결과를 쓰는 최악의 경우만 넘는다)."""
        def words(seed):
            return "".join(chr(0xAC00 + (seed * 7 + step * 13) % 1500) for step in range(200))

        manifest = pm.empty_manifest()
        for number in range(1, 31):
            manifest, photo_id = pm.add_photo(manifest, win(f"{number:02d}.jpg"))
            manifest, _dropped = pm.set_analysis(manifest, photo_id, method="local:x", objects=[words(number * 100 + index) for index in range(20)], texts=[words(number * 100 + 50 + index) for index in range(20)])
        self.assertGreater(len(manifest.to_text(True).encode("utf-8")), svc.MAX_FILE_BYTES, "시험의 전제: 분석 결과까지 쓰면 읽을 수 있는 크기를 넘는다")
        self.assertLess(len(manifest.to_text(False).encode("utf-8")), svc.MAX_FILE_BYTES // 4, "기본(분석 결과를 쓰지 않는) 길은 훨씬 작다")
        error = self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, manifest, persist_analysis=True)
        self.assertNoLeak(error, [self.tmp.name, DRAFT_A])
        self.assertFalse(self.folder.exists(), "아무것도 쓰지 않았고 폴더도 만들지 않았다")
        svc.save_manifest(self.ctx, DRAFT_A, manifest)
        loaded = svc.load_manifest(self.ctx, DRAFT_A)
        self.assertEqual((loaded.state, len(loaded.manifest.photos)), ("ok", 30), "분석 결과를 쓰지 않는 기본 길은 그대로 저장되고 읽힌다")
        self.assertTrue(all(photo.observed_objects == () and photo.visible_text == () for photo in loaded.manifest.photos))

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

    def test_the_list_comes_back_sorted_whatever_order_the_folder_is_read_in(self):
        """검증 Q-11 ③ — 윈도 NTFS 는 이름 순으로 읽어 주지만 리눅스는 아니다. 폴더를 거꾸로 읽어도 목록·고아는 번호순이다."""
        for draft_id in (DRAFT_C, DRAFT_A, DRAFT_B):
            svc.save_manifest(self.ctx, draft_id, sample(1))
        real = os.scandir

        class Reversed:
            def __init__(self, path):
                self.entries = list(real(path))[::-1]

            def __enter__(self):
                return iter(self.entries)

            def __exit__(self, *exc):
                return False

        with mock.patch.object(svc.os, "scandir", Reversed):
            self.assertEqual(svc.list_manifests(self.ctx).draft_ids, tuple(sorted((DRAFT_A, DRAFT_B, DRAFT_C))))
            self.assertEqual(svc.orphans(self.ctx, []), tuple(sorted((DRAFT_A, DRAFT_B, DRAFT_C))))

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
        for ok in ([], (), set(), frozenset(), [DRAFT_A], (DRAFT_A, DRAFT_B), {DRAFT_A}):
            svc.orphans(self.ctx, ok)                                                   # 빈 목록과 올바른 번호의 목록·튜플·집합은 받는다
        for bad in (["bad", None, 5], [DRAFT_A.upper()], [" " + DRAFT_A], [DRAFT_A, "dd-"], DRAFT_A, None, 5, {DRAFT_A: 1}, (number for number in [DRAFT_A]), b"dd-aaaaaaaaaaaaaaaaaaaa"):
            with self.subTest(bad=repr(bad)[:40]):
                error = self.refuses("CONTENT_INVALID", svc.orphans, self.ctx, bad)        # 검증 S-3 — fail closed: 잘못된 목록이 모든 파일을 고아로 보이게 하지 않는다
                self.assertNoLeak(error, [self.tmp.name])
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
        root_before = snapshot(self.root)
        for probe in (None, self.probe(), self.probe(can_read=False)):
            svc.check_files(manifest, probe=probe)
        after = {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns, path.stat().st_size) for path in paths}
        self.assertEqual(after, before)
        self.assertEqual(sorted(os.listdir(self.pictures)), listing)
        self.assertEqual(snapshot(self.root), root_before, "데이터 폴더도 그대로다(검증 Q-11 — 앞뒤를 견준다)")

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


class LinkAndCloudTest(Base):
    """정션(윈도의 폴더 링크)·이름을 대신하는 재해석 지점·클라우드 '내려받지 않음' 비트를 시험이 직접 못박는다(독립 검증 S-1·Q-2). 심볼릭 링크는 `S_IFLNK` 로도 걸러져서 링크 시험만으로는
    정션을 잡는 줄(`own_posts._link_like`)이나 '경로 위의 폴더' 순회가 빠져도 모른다. 진짜 정션 시험은 윈도에서만(`_winapi.CreateJunction` — 권한 불필요, 다른 곳에서는 건너뜀)이고, 가짜 상태 정보
    시험은 리눅스에서도 돈다. 클라우드 세 비트의 값은 `own_posts` 의 상수를 읽지 않고 이 시험에 글자로 못박는다(상수가 바뀌면 여기서 걸린다)."""
    REPARSE = 0x400                                                  # FILE_ATTRIBUTE_REPARSE_POINT
    NAME_TAGS = {"symlink": 0xA000000C, "mount_point": 0xA0000003}   # 이름 대리 비트(0x20000000)가 켜진 재해석 표 — 링크 종류(심볼릭 링크·정션)
    CLOUD_TAG = 0x9000601A                                           # OneDrive 같은 클라우드 표 — 이름 대리 비트가 꺼져 있다(링크가 아니다)
    CLOUD_BITS = {"OFFLINE": 0x1000, "RECALL_ON_OPEN": 0x40000, "RECALL_ON_DATA_ACCESS": 0x400000}

    def setUp(self):
        super().setUp()
        self.pictures = Path(self.tmp.name) / "pics"
        self.pictures.mkdir()

    def make(self, folder, name, size=64):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0]) + bytes(size))
        return path

    @staticmethod
    def manifest_of(*paths):
        manifest = pm.empty_manifest()
        for path in paths:
            manifest, _id = pm.add_photo(manifest, str(path))
        return manifest

    @staticmethod
    def info(kind, attributes=0, tag=0, size=64):
        mode = (stat.S_IFDIR | 0o755) if kind == "dir" else (stat.S_IFREG | 0o644)
        return types.SimpleNamespace(st_mode=mode, st_file_attributes=attributes, st_reparse_tag=tag, st_size=size)

    @staticmethod
    def fake_lstat(replacements):
        """`svc._lstat` 를 바꾼다 — `{경로: 가짜 상태 정보}` 에 있는 경로만 가짜이고 나머지는 진짜다."""
        real = svc._lstat
        table = {Path(path): info for path, info in replacements.items()}

        def fake(path):
            return table[Path(path)] if Path(path) in table else real(path)
        return mock.patch.object(svc, "_lstat", fake)

    def store_calls(self):
        return (lambda: svc.load_manifest(self.ctx, DRAFT_A), lambda: svc.save_manifest(self.ctx, DRAFT_A, sample(1)), lambda: svc.delete_manifest(self.ctx, DRAFT_A, confirmed=True),
                lambda: svc.list_manifests(self.ctx), lambda: svc.orphans(self.ctx, ()))

    def test_the_constants_are_the_ones_written_here(self):
        self.assertEqual(own_posts._NAME_SURROGATE, 0x20000000)
        self.assertEqual(own_posts._NOT_LOCAL, 0x1000 | 0x40000 | 0x400000)
        self.assertEqual(sorted(self.CLOUD_BITS.values()), [0x1000, 0x40000, 0x400000])
        self.assertEqual(stat.FILE_ATTRIBUTE_REPARSE_POINT, self.REPARSE)
        for tag in self.NAME_TAGS.values():
            self.assertTrue(tag & 0x20000000)
        self.assertFalse(self.CLOUD_TAG & 0x20000000)

    def test_a_name_surrogate_reparse_point_is_refused_as_the_store_folder_everywhere_and_nothing_is_made(self):
        for label, tag in self.NAME_TAGS.items():
            with self.subTest(tag=label):
                with self.fake_lstat({self.folder: self.info("dir", self.REPARSE | 0x10, tag)}):
                    for call in self.store_calls():
                        error = self.refuses("CONTENT_INVALID", call)
                        self.assertNoLeak(error, [self.tmp.name])
                self.assertFalse(self.folder.exists(), "링크라고 본 폴더에 아무것도 만들지 않았다")

    def test_a_reparse_point_without_the_name_surrogate_bit_is_not_taken_for_a_link(self):
        self.folder.mkdir(parents=True)
        with self.fake_lstat({self.folder: self.info("dir", self.REPARSE | 0x10, self.CLOUD_TAG)}):
            self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "none")
            self.assertEqual(svc.list_manifests(self.ctx), svc.Listing((), 0))
            saved = svc.save_manifest(self.ctx, DRAFT_A, sample(1))
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A), svc.Loaded(saved, "ok"))

    def test_a_name_surrogate_reparse_point_in_place_of_the_stored_file_is_broken_and_cannot_be_deleted(self):
        saved = svc.save_manifest(self.ctx, DRAFT_A, sample(1))
        before = self.file().read_bytes()
        for label, tag in self.NAME_TAGS.items():
            with self.subTest(tag=label):
                with self.fake_lstat({self.file(): self.info("file", self.REPARSE, tag, size=len(before))}):
                    self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "broken")
                    self.refuses("CONTENT_INVALID", svc.save_manifest, self.ctx, DRAFT_A, sample(2))
                    self.refuses("CONTENT_INVALID", svc.delete_manifest, self.ctx, DRAFT_A, confirmed=True)
                self.assertEqual(self.file().read_bytes(), before)
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A), svc.Loaded(saved, "ok"))

    def test_a_name_surrogate_reparse_point_on_the_picture_path_is_a_link_whether_a_folder_or_the_file(self):
        subfolder = self.pictures / "sub"
        photo = self.make(subfolder, "a.jpg")
        manifest = self.manifest_of(photo)
        self.assertEqual(svc.check_files(manifest)[0].state, "ok")
        for label, tag in self.NAME_TAGS.items():
            with self.subTest(tag=label):
                with self.fake_lstat({subfolder: self.info("dir", self.REPARSE | 0x10, tag)}):
                    result = svc.check_files(manifest)[0]
                self.assertEqual(result.state, "link", "경로 위의 폴더가 링크이면 그 아래 사진은 쓰지 않는다")
                self.assertTrue(result.message)
                with self.fake_lstat({photo: self.info("file", self.REPARSE, tag)}):
                    self.assertEqual(svc.check_files(manifest)[0].state, "link")
        with self.fake_lstat({subfolder: self.info("dir", self.REPARSE | 0x10, self.CLOUD_TAG)}):
            self.assertEqual(svc.check_files(manifest)[0].state, "ok", "이름 대리 비트가 꺼진 재해석 지점은 링크가 아니다")

    def test_each_cloud_bit_alone_means_the_file_is_not_downloaded_and_other_attributes_do_not(self):
        photo = self.make(self.pictures, "c.jpg")
        manifest = self.manifest_of(photo)
        for name, bit in self.CLOUD_BITS.items():
            with self.subTest(bit=name):
                with self.fake_lstat({photo: self.info("file", bit)}):
                    result = svc.check_files(manifest)[0]
                self.assertEqual(result.state, "cloud")
                self.assertIn("내려받지 않은", result.message)
        with self.fake_lstat({photo: self.info("file", self.REPARSE | 0x1000, self.CLOUD_TAG)}):
            self.assertEqual(svc.check_files(manifest)[0].state, "cloud", "실제 클라우드 파일의 모습(재해석 지점 + 오프라인)")
        for harmless in (0x1, 0x2, 0x4, 0x20, 0x80, 0x2000, 0x8000):                           # 읽기 전용·숨김·시스템·보관·보통·색인 제외·무결성
            with self.subTest(attributes=hex(harmless)):
                with self.fake_lstat({photo: self.info("file", harmless)}):
                    self.assertEqual(svc.check_files(manifest)[0].state, "ok")

    def junction(self, link, target):
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        except (ImportError, AttributeError, OSError) as error:
            self.skipTest(f"이 환경에서는 정션을 만들 수 없다({type(error).__name__})")

    def test_a_real_junction_as_the_store_folder_is_refused_everywhere_and_nothing_is_written_beyond_it(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.junction(self.folder, outside)
        for call in self.store_calls():
            self.refuses("CONTENT_INVALID", call)
        self.assertEqual(list(outside.iterdir()), [], "정션 너머에 쓰지 않았다")

    def test_a_real_junction_in_the_middle_of_the_picture_path_is_a_link_and_a_real_one_beside_it_is_ok(self):
        real = Path(self.tmp.name) / "real_pics"
        self.make(real, "a.jpg")
        self.make(self.pictures / "plain", "b.jpg")
        self.junction(self.pictures / "via", real)
        results = svc.check_files(self.manifest_of(self.pictures / "via" / "a.jpg", self.pictures / "plain" / "b.jpg"))
        self.assertEqual([item.state for item in results], ["link", "ok"])
        self.assertTrue(results[0].message)


class TrashTest(Base):
    """초안을 지울 때의 '되돌릴 사본'(운영자 확인 024, 이슈 #221 선택 ② '남김') — 옮기기·되돌리기·비우기·읽기. 사진 **파일**은 어떤 길로도 건드리지 않는다(이 함수들은 사진 경로를 받지도 읽지도 않는다)."""

    def trash(self, draft_id=DRAFT_A):
        return self.folder / f"{draft_id}.json.trash"

    def saved(self, draft_id=DRAFT_A, count=2, **fields):
        return svc.save_manifest(self.ctx, draft_id, sample(count, **fields))

    def test_trashing_moves_the_file_byte_for_byte_into_one_copy_and_the_listings_forget_it(self):
        self.saved(user_note=UNIQ_NOTE)
        original = self.file().read_bytes()
        self.assertEqual(svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True), "moved")
        self.assertFalse(self.file().exists())
        self.assertEqual(self.trash().read_bytes(), original, "바이트 그대로 옮겼다")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{DRAFT_A}.json.trash"])
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A).state, "none")
        self.assertEqual(svc.list_manifests(self.ctx), svc.Listing((), 0))
        self.assertEqual(svc.orphans(self.ctx, []), (), "사본은 고아가 아니다")
        self.assertEqual((svc.has_trash(self.ctx, DRAFT_A), svc.has_trash(self.ctx, DRAFT_B)), (True, False))
        self.assertEqual(svc.list_trash(self.ctx), (DRAFT_A,))
        self.assertEqual(svc.TRASH_SUFFIX, ".json.trash")

    def test_trashing_the_same_draft_again_keeps_only_the_latest_copy(self):
        self.saved(count=1, user_note="처음")
        svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True)
        self.saved(count=2, user_note="나중")
        later = self.file().read_bytes()
        svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True)
        self.assertEqual(self.trash().read_bytes(), later)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [self.trash().name])

    def test_nothing_to_trash_is_none_and_makes_nothing(self):
        self.assertEqual(svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True), "none")
        self.assertFalse(self.folder.exists())
        self.saved(DRAFT_B)
        self.assertEqual(svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True), "none", "다른 초안의 파일은 옮기지 않는다")
        self.assertTrue(self.file(DRAFT_B).exists())

    def test_trashing_clearing_and_restoring_need_what_they_need_and_refuse_bad_numbers_without_touching_anything(self):
        self.saved()
        svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True)
        self.saved(DRAFT_B)
        before = snapshot(self.root)
        for bad in (False, None, 1, "yes", "true", 0, [], "예"):
            with self.subTest(confirmed=bad):
                self.refuses("CONFIRMATION_REQUIRED", svc.trash_manifest, self.ctx, DRAFT_B, confirmed=bad)
                self.refuses("CONFIRMATION_REQUIRED", svc.clear_trash, self.ctx, DRAFT_A, confirmed=bad)
        for bad in BAD_IDS:
            with self.subTest(draft_id=repr(bad)[:30]):
                self.refuses("CONTENT_INVALID", svc.trash_manifest, self.ctx, bad, confirmed=True)
                self.refuses("CONTENT_INVALID", svc.restore_manifest, self.ctx, bad)
                self.refuses("CONTENT_INVALID", svc.clear_trash, self.ctx, bad, confirmed=True)
                self.assertFalse(svc.has_trash(self.ctx, bad))
        self.assertEqual(snapshot(self.root), before)
        with self.assertRaises(TypeError):
            svc.trash_manifest(self.ctx, DRAFT_B)
        with self.assertRaises(TypeError):
            svc.clear_trash(self.ctx, DRAFT_A)

    def test_a_folder_a_link_or_a_file_that_is_not_plain_is_refused_and_left_alone(self):
        self.saved()
        before = snapshot(self.root)
        for label, tag in LinkAndCloudTest.NAME_TAGS.items():
            with self.subTest(tag=label):
                with LinkAndCloudTest.fake_lstat({self.file(): LinkAndCloudTest.info("file", LinkAndCloudTest.REPARSE, tag)}):
                    self.refuses("CONTENT_INVALID", svc.trash_manifest, self.ctx, DRAFT_A, confirmed=True)
                with LinkAndCloudTest.fake_lstat({self.folder: LinkAndCloudTest.info("dir", LinkAndCloudTest.REPARSE | 0x10, tag)}):
                    for call in (lambda: svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True), lambda: svc.restore_manifest(self.ctx, DRAFT_A), lambda: svc.clear_trash(self.ctx, DRAFT_A, confirmed=True),
                                 lambda: svc.list_trash(self.ctx)):
                        self.refuses("CONTENT_INVALID", call)
                    self.assertFalse(svc.has_trash(self.ctx, DRAFT_A))
        self.assertEqual(snapshot(self.root), before)
        self.trash().mkdir()                                                           # 사본 자리가 폴더면 덮어쓰지 않는다
        self.refuses("CONTENT_INVALID", svc.trash_manifest, self.ctx, DRAFT_A, confirmed=True)
        self.refuses("CONTENT_INVALID", svc.clear_trash, self.ctx, DRAFT_A, confirmed=True)
        self.assertTrue(self.trash().is_dir() and self.file().exists())
        self.assertEqual(svc.list_trash(self.ctx), (), "폴더는 사본이 아니다")
        self.assertFalse(svc.has_trash(self.ctx, DRAFT_A))
        self.trash().rmdir()
        self.file().unlink()
        self.file().mkdir()                                                            # 사진 정보 자리가 폴더면 옮기지 않는다
        self.refuses("CONTENT_INVALID", svc.trash_manifest, self.ctx, DRAFT_A, confirmed=True)
        self.assertTrue(self.file().is_dir())

    def test_a_failed_move_leaves_the_file_where_it_was_and_hides_the_path(self):
        self.saved(user_note=UNIQ_NOTE)
        original = self.file().read_bytes()
        with mock.patch.object(svc.os, "replace", side_effect=PermissionError(errno.EACCES, "denied", str(self.file()))):
            error = self.refuses("FILE_WRITE_FAILED", svc.trash_manifest, self.ctx, DRAFT_A, confirmed=True)
        self.assertNoLeak(error, [self.tmp.name, DRAFT_A, UNIQ_DIR, UNIQ_NOTE])
        self.assertEqual(error.slots.get("경로"), svc._WHERE)
        self.assertEqual(self.file().read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [self.file().name])

    def test_restoring_moves_the_checked_copy_back_so_the_file_is_exactly_as_it_was(self):
        saved = self.saved(user_note=UNIQ_NOTE)
        original = self.file().read_bytes()
        svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True)
        loaded = svc.restore_manifest(self.ctx, DRAFT_A)
        self.assertEqual(loaded, svc.Loaded(saved, "ok"))
        self.assertEqual(self.file().read_bytes(), original)
        self.assertFalse(self.trash().exists())
        self.assertEqual(svc.load_manifest(self.ctx, DRAFT_A), svc.Loaded(saved, "ok"))
        self.assertEqual((svc.has_trash(self.ctx, DRAFT_A), svc.list_trash(self.ctx)), (False, ()))

    def test_restoring_refuses_without_a_copy_with_an_unusable_copy_or_over_an_existing_file(self):
        self.refuses("CONTENT_NOT_FOUND", svc.restore_manifest, self.ctx, DRAFT_A)
        self.assertFalse(self.folder.exists())
        good = dataclasses.replace(sample(1), draft_id=DRAFT_A).to_text()
        cases = {"JSON 아님": "{abc", "빈 파일": "", "BOM": chr(0xFEFF) + good, "다른 초안 번호": good.replace(DRAFT_A, DRAFT_B), "모르는 칸": good.replace('"draft_id"', '"exif": 1, "draft_id"', 1),
                 "새 판": good.replace("photo-manifest/1", "photo-manifest/2"), "너무 큼": "x" * (svc.MAX_FILE_BYTES + 1)}
        for name, content in cases.items():
            with self.subTest(case=name):
                self.folder.mkdir(parents=True, exist_ok=True)
                self.trash().write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
                before = snapshot(self.root)
                error = self.refuses("CONTENT_INVALID", svc.restore_manifest, self.ctx, DRAFT_A)
                self.assertNoLeak(error, [self.tmp.name, DRAFT_A])
                self.assertEqual(snapshot(self.root), before, "깨진 사본은 그대로 두고 사진 정보 파일도 만들지 않는다")
                self.trash().unlink()
        self.trash().write_text(good, encoding="utf-8")
        with mock.patch.object(svc, "_pause"), mock.patch.object(own_posts, "_read_prefix", return_value=(None, own_posts._R_MISSING)):
            self.refuses("CONTENT_INVALID", svc.restore_manifest, self.ctx, DRAFT_A)
        self.assertEqual(self.trash().read_text(encoding="utf-8"), good, "지금 못 연 사본도 그대로")
        self.saved()                                                                   # 이미 사진 정보가 있다
        live, kept = self.file().read_bytes(), self.trash().read_bytes()
        self.refuses("CONTENT_INVALID", svc.restore_manifest, self.ctx, DRAFT_A)
        self.assertEqual((self.file().read_bytes(), self.trash().read_bytes()), (live, kept), "두 파일이 다 남는다")

    def test_clearing_removes_only_that_copy_after_a_confirmation(self):
        for draft_id in (DRAFT_A, DRAFT_B):
            self.saved(draft_id)
            svc.trash_manifest(self.ctx, draft_id, confirmed=True)
        self.saved(DRAFT_C)
        svc.clear_trash(self.ctx, DRAFT_A, confirmed=True)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), sorted([f"{DRAFT_B}.json.trash", f"{DRAFT_C}.json"]))
        self.assertEqual(svc.list_trash(self.ctx), (DRAFT_B,))
        self.refuses("CONTENT_NOT_FOUND", svc.clear_trash, self.ctx, DRAFT_A, confirmed=True)
        original = Path.unlink

        def failing(self_path, *args, **kwargs):
            if self_path.name.endswith(".json.trash"):
                raise PermissionError(errno.EACCES, "denied", str(self_path))
            return original(self_path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", failing):
            error = self.refuses("FILE_WRITE_FAILED", svc.clear_trash, self.ctx, DRAFT_B, confirmed=True)
        self.assertNoLeak(error, [self.tmp.name, DRAFT_B])
        self.assertTrue(self.trash(DRAFT_B).exists())

    def test_looking_at_the_copies_reads_names_only_and_makes_nothing(self):
        before = snapshot(self.root)
        self.assertEqual((svc.list_trash(self.ctx), svc.has_trash(self.ctx, DRAFT_A)), ((), False))
        self.assertEqual(snapshot(self.root), before)
        self.saved()
        svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True)
        self.folder.joinpath("dd-" + "b" * 20 + ".json.trash.bak").write_text("x", encoding="utf-8")
        self.folder.joinpath("DD-" + "b" * 20 + ".json.trash").write_text("x", encoding="utf-8")
        self.folder.joinpath("note.json.trash").write_text("x", encoding="utf-8")
        before = snapshot(self.root)
        self.assertEqual(svc.list_trash(self.ctx), (DRAFT_A,), "정확한 이름 모양의 사본만")
        self.assertEqual(snapshot(self.root), before)

    def test_no_picture_file_is_ever_touched(self):
        pictures = Path(self.tmp.name) / "pics"
        pictures.mkdir()
        paths = []
        for number in range(1, 3):
            path = pictures / f"{number}.jpg"
            path.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0]) + bytes(number * 50))
            paths.append(path)
        manifest = pm.empty_manifest()
        for path in paths:
            manifest, _id = pm.add_photo(manifest, str(path))
        svc.save_manifest(self.ctx, DRAFT_A, manifest)
        before = {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}
        listing = sorted(os.listdir(pictures))
        svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True)
        svc.restore_manifest(self.ctx, DRAFT_A)
        svc.trash_manifest(self.ctx, DRAFT_A, confirmed=True)
        svc.clear_trash(self.ctx, DRAFT_A, confirmed=True)
        self.assertEqual({path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}, before)
        self.assertEqual(sorted(os.listdir(pictures)), listing)


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


class TrashBackupTest(unittest.TestCase):
    """확인 024 — 되돌릴 사본도 전체 백업에는 담지 않는다(결정 2 그대로)."""

    def test_the_copies_are_not_in_a_real_full_backup_and_a_real_restore_leaves_them_alone(self):
        import backup_support as bs
        from chanceblog_desktop.service import backup_flow as bf
        with tempfile.TemporaryDirectory(prefix="pm-trash-backup-") as tmp:
            world = bs.World(Path(os.path.realpath(tmp)), posts=1, drafts=0, candidates_count=0)
            ctx = world.ctx
            ctx.clock.advance(minutes=1)
            svc.save_manifest(ctx, DRAFT_A, sample(2, user_note=UNIQ_NOTE))
            svc.trash_manifest(ctx, DRAFT_A, confirmed=True)
            svc.save_manifest(ctx, DRAFT_B, sample(1, user_note="살아 있는 초안"))
            folder = world.root / "photo-manifests"

            def snap():
                return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(folder.iterdir())}

            before = snap()
            self.assertEqual(sorted(before), sorted([f"{DRAFT_A}.json.trash", f"{DRAFT_B}.json"]))
            outcome = world.backup()
            backup_folder = world.folder(outcome)
            names = [path.relative_to(backup_folder).as_posix() for path in backup_folder.rglob("*")]
            self.assertFalse([name for name in names if "photo" in name or "trash" in name or DRAFT_A in name], names)
            for path in backup_folder.rglob("*"):
                if path.is_file():
                    self.assertNotIn(UNIQ_NOTE.encode("utf-8"), path.read_bytes(), path.name)
            self.assertEqual(snap(), before, "백업이 사본을 건드리지 않았다")
            result = bf.restore_full_backup(ctx, outcome.row.name, confirmed=True)
            self.assertEqual(result.status, bf.STATUS_COMPLETE)
            self.assertEqual(snap(), before, "복원도 사본을 건드리지 않았다(내용·수정 시각 그대로)")


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
        self.assertEqual(unlinks, {"delete_manifest", "clear_trash"})
        self.assertEqual(calls.get("os.replace"), {"trash_manifest", "restore_manifest"}, "이름 바꾸기(되돌릴 사본으로 옮기기·되돌리기)는 이 둘뿐이다")
        for banned in ("open", "io.open", "os.open", "os.write", "os.rename", "os.remove", "os.makedirs", "shutil.copy", "shutil.rmtree", "shutil.move", "print", "os.fsync", "os.chmod"):
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
        self.assertFalse(names & {"subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "requests", "asyncio", "logging", "traceback", "PySide6", "random"})
        clock = {ast.unparse(node.func): function.name for function in ast.walk(tree) if isinstance(function, ast.FunctionDef) for node in ast.walk(function)
                 if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[0] == "time"}
        self.assertEqual(clock, {"time.sleep": "_pause"}, "시간은 읽기를 다시 해 보기 전에 쉬는 `_pause` 한 곳에서만 쓴다(시계를 읽지 않는다)")
        screen = {(node.module, tuple(alias.name for alias in node.names)) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and "ui" in (node.module or "").split(".")}
        self.assertEqual(screen, {("ui.core", ("imagerules",))}, "검증 Q-4 — 화면 층에서 가져오는 것은 imagerules 하나뿐이다")
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

    # 이 모듈을 부르는 소스 파일의 허용 목록(파일 → 이유). 1단계는 기존 코드를 바꾸지 않았으므로 비어 있었다 — 2단계(사진 정리 화면, 결정 D-499)가 아래 넷을 더했다. 3단계(초안 연결)가 부를 때도 이유와 함께 여기에 더한다(몰래 늘면 걸린다).
    MODULE_USERS = {
        "ui/core/photo_rules.py": "사진 정리 화면의 규칙표 — 종류·장소 분위기·글자 수 한도·자리 종류를 1단계 규칙에서 그대로 가져온다(새 한도를 만들지 않는다)",
        "ui/core/photo_text.py": "화면 문구 파일의 머리 설명이 1단계 파일 이름을 말할 뿐 코드로 가져오지는 않는다",
        "ui/core/photo_view.py": "사진 정리 화면의 컨트롤러(PhotoBoard) — 사진 목록을 1단계 규칙(추가·고치기·글칸 검사·순서·지우기·확정)으로만 고치고 저장하지 않는다",
        "ui/photo_adapter.py": "사진 파일을 읽기만 하는 어댑터 — 서비스의 `check_files`(읽기 전용)를 부른다",
        "ui/core/drafts.py": "저장한 초안 공급자의 값(사진 정보 저장·열기·지우기 결과)·가짜 공급자 — 서비스의 고정 문장 하나를 글로만 가리킨다(`PHOTO_EXISTS_REASON` — 시험이 견준다)",
        "ui/drafts_adapter.py": "저장한 초안 공급자가 사진 정보를 함께 저장·열기·되돌릴 사본으로 옮기기·되돌리기·사본 비우기(3단계, 운영자 확인 024) — 서비스 한 곳(photo_manifest)만 부른다",
        "content/draft_body.py": "본문 생성기의 머리 설명이 `DraftPhoto`(확정한 사진만 담은 값)를 말하고 `photo_flow.place_photos` 를 부른다 — 사진 파일·경로를 모른다(3단계 본문 연결)",
        "content/photo_flow.py": "사진 줄을 본문 블록에 끼우는 순수 함수(3단계 본문 연결) — `DraftPhoto`·자리표시자 만들기만 가져온다",
        "ui/core/drafts_view.py": "초안 컨트롤러가 만들 때 확정한 사진만 `draft_inputs` 로 뽑아 요청에 싣고 만든 뒤 바뀌었는지 견준다(3단계 본문 연결) — 경로·파일 이름은 뽑히지 않는다",
    }

    def test_only_the_listed_source_files_use_the_photo_manifest_modules(self):
        src = ROOT / "src" / "chanceblog_desktop"
        users = sorted(path.relative_to(src).as_posix() for path in src.rglob("*.py") if "photo_manifest" in path.read_text(encoding="utf-8") and path.name != "photo_manifest.py")
        self.assertEqual(users, sorted(self.MODULE_USERS), "이 모듈을 새로 부르는 파일은 이유와 함께 MODULE_USERS 에 더한다")
        self.assertTrue(all(reason.strip() for reason in self.MODULE_USERS.values()))


if __name__ == "__main__":
    unittest.main()
