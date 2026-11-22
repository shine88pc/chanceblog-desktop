"""빌드 흐름의 '산출물 점검' 단계(`ocr_addon/verify_release.py`, 결정 D-527·D-531, 운영자 확인 030 ② — 라이선스 고지 파일이 압축 파일 안에 있는지)의 시험 — 빌드·네트워크·진짜 모델 없이 돈다.

진짜 빌드 스크립트의 `make_info`·`make_zip` 으로 작은 가짜 묶음에서 올리는 폴더(압축 파일·SHA256SUMS·PACKAGE_INFO.json)를 만들고(두 스크립트가 같은 모양을 말하는지 보는 계약 시험),
그 폴더를 점검에 넣어 본다. 지키는 것: 올리는 폴더에 정해진 셋뿐 · 해시·크기가 SHA256SUMS·PACKAGE_INFO.json 과 같다 · 항목은 모두 `ocr/` 아래의 안전한 이름이고 정보 파일의 목록과 한 줄씩 같다 · 모델·사전이 잠금 값과 같다 ·
**`licenses/` 에 파일이 있고(그중 GEOS 라이선스 전문 `licenses/shapely/LICENSE_GEOS` 가 꼭 있고) `THIRD_PARTY_NOTICES.txt` 가 비어 있지 않으며 GEOS·LGPL 을 말하고 GEOS 가 별도 DLL 로 있다**. 어느 하나라도 어긋나면 점검이 실패하고 종료 코드가 1 이다.
"""
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_build_support as support  # noqa: E402

build = support.load("build_ocr_addon")
verify = support.load("verify_release")
rules = support.load("build_rules")
STATE = {"commit": "0123456789abcdef0123456789abcdef01234567", "epoch": 1794873600, "epoch_from": "git commit", "committed_utc": "2026-11-17T00:00:00Z", "clean": True, "dirty_count": 0}
VERSION = "0.1.0-preview.1"
MODELS = {"models/det/inference.onnx": b"det-model", "models/rec/inference.onnx": b"rec-model-bytes", "data/ppocrv5_korean_dict.txt": b"dict\nbytes\n"}
NOTICE = "제3자 고지\n\n- GEOS: LGPL-2.1, 별도 DLL 파일(Shapely.libs)이라 바꿔 끼울 수 있습니다. 소스는 파이썬 패키지 저장소의 shapely 배포 파일에서 받을 수 있습니다(원본 소스 파일은 이 폴더에 넣지 않았습니다).\n"
# 합친 빌드(notices 단계가 점검 앞에서 만든 것)와 같은 모양: licenses/<부품 이름>/<파일>, GEOS 전문은 licenses/shapely/LICENSE_GEOS, 별도 GEOS DLL 은 _internal 아래
GEOS = {"name": "GEOS", "version": "3.99.9", "license": "LGPL-2.1", "dll_files": ["_internal/Shapely.libs/geos_c-1-abcdef.dll"], "license_file": "licenses/shapely/LICENSE_GEOS", "replaceable": True,
        "source_host": "libgeos.org", "source_included": False}
BUNDLE = {"ocr_worker.exe": b"worker-bytes", "_internal/base_library.zip": b"base", "_internal/Shapely.libs/geos_c-1-abcdef.dll": b"geos-dll", "THIRD_PARTY_NOTICES.txt": NOTICE.encode("utf-8"),
          "licenses/shapely/LICENSE_GEOS": b"GNU LESSER GENERAL PUBLIC LICENSE Version 2.1", "licenses/tqdm/LICENCE": b"Mozilla Public License Version 2.0", **MODELS}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fake_lock():
    def hf(key, repo, commit):
        return {"key": key, "role": key.split("/")[1], "source": {"kind": "huggingface", "repo": repo, "commit": commit, "path": "inference.onnx"}, "bytes": len(MODELS[key]), "sha256": sha(MODELS[key])}
    return {"schema": 1, "files": [hf("models/det/inference.onnx", "Owner/det_repo", "a" * 40), hf("models/rec/inference.onnx", "Owner/rec_repo", "b" * 40),
                                   {"key": "data/ppocrv5_korean_dict.txt", "role": "dict", "source": {"kind": "repo", "path": "ocr_addon/data/ppocrv5_korean_dict.txt"},
                                    "bytes": len(MODELS["data/ppocrv5_korean_dict.txt"]), "sha256": sha(MODELS["data/ppocrv5_korean_dict.txt"])}]}


LOCK = fake_lock()
EXPECTED = rules.expected_files(LOCK)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


# 같은 가짜 묶음으로는 올리는 폴더를 한 번만 만들고(윈도에서는 파일 하나를 닫을 때마다 보안 프로그램이 훑어 느리다) 시험마다 그 사본을 쓴다 — 사본은 시험이 마음대로 망가뜨려도 된다.
_CACHE_DIR = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
unittest.addModuleCleanup(_CACHE_DIR.cleanup)
_CACHE = {}


class ReleaseCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.count = 0
        pins = rules.parse_lock(support.read("ocr_addon/requirements-ocr.lock"))
        for item in (mock.patch.object(build, "log"), mock.patch.object(build, "load_lock", return_value=(LOCK, EXPECTED)), mock.patch.object(build, "bundled_modules", return_value={"cv2", "numpy"}),
                     mock.patch.object(build, "installed_version", side_effect=lambda name: next((pin["version"] for pin in pins if pin["name"] == rules.canon(name)), "9.9")),
                     mock.patch.object(build, "pypi_license", return_value="MIT")):
            item.start()
            self.addCleanup(item.stop)

    def make_release(self, bundle=None, drop=(), check=None):
        """작은 가짜 묶음 -> 진짜 make_info·make_zip -> release 폴더 경로(같은 묶음이면 처음 만든 것의 사본). `check` 는 빌드 점검 결과(check_result.json)의 칸을 덮어쓰는 자리 —
        점검에 실패하고도 산출물을 만든 빌드(정보 파일에 checks.ok=false 가 적힌 압축 파일)를 흉내 낸다."""
        self.count += 1
        files = {name: data for name, data in (BUNDLE if bundle is None else bundle).items() if name not in drop}
        key = (tuple(sorted(files.items())), json.dumps(check, sort_keys=True))
        if key not in _CACHE:
            out = Path(_CACHE_DIR.name) / ("out%d" % len(_CACHE))
            for name, data in files.items():
                write(out / "dist" / "ocr" / Path(*name.split("/")), data)
            record = {"ok": True, "problems": [], "pe_files_checked": 3, "selftest": {"ok": True}, "selftest_exit": 0}
            record.update(check or {})
            write(out / "check_result.json", json.dumps(record))
            write(out / "removed.json", "[]")
            write(out / build.GEOS_RECORD, json.dumps(GEOS))                       # notices 단계의 기록(묶음 밖) — make_info 가 읽는다
            # 빠진 고지 산출물이 있는 묶음은 진짜 make_info 가 마지막 방어선(missing_outputs)에서 거절한다 — 이 시험들은 '그 방어선이 없었던 빌드의 산출물'을 점검이 다시 거르는지 보려고 방어선만 끈다(온전한 묶음은 방어선을 켠 채 만든다)
            guard = mock.patch.object(build, "missing_outputs", return_value=[]) if build.missing_outputs(list(files)) else contextlib.nullcontext()
            with guard:
                info = build.make_info(str(out), STATE, VERSION)
            build.make_zip(str(out), VERSION, info)
            _CACHE[key] = out / "release"
        target = self.root / ("release%d" % self.count)
        shutil.copytree(_CACHE[key], target)
        return target

    def problems(self, release):
        problems, _facts = verify.release_problems(str(release), LOCK)
        return problems

    def zip_path(self, release):
        return next(release.glob("*.zip"))

    def rewrite_zip(self, release, change):
        """압축 파일의 항목 사전을 `change` 로 바꿔 다시 쓰고 SHA256SUMS·PACKAGE_INFO.json 의 해시·크기도 맞춘다 — 노린 하나만 어긋나게."""
        path = self.zip_path(release)
        with zipfile.ZipFile(path) as archive:
            entries = [(item.filename, archive.read(item.filename)) for item in archive.infolist()]
        entries = change(entries)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                                      # 같은 이름을 두 번 쓰면 파이썬이 경고한다 — 일부러 만든 시험 자료다
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in entries:
                    archive.writestr(name, data)
        self.refresh(release)

    def refresh(self, release):
        path = self.zip_path(release)
        data = path.read_bytes()
        (release / "SHA256SUMS").write_text("%s  %s\n" % (sha(data), path.name), encoding="utf-8")
        outer = json.loads((release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        outer["package"] = {"name": path.name, "sha256": sha(data), "bytes": len(data)}
        (release / "PACKAGE_INFO.json").write_text(json.dumps(outer), encoding="utf-8")

    def expect(self, release, word, label=""):
        problems = self.problems(release)
        self.assertTrue(any(word in item for item in problems), (label, word, problems))
        return problems


class GoodReleaseTest(ReleaseCase):
    def test_a_release_made_by_the_real_build_functions_passes_with_no_problem(self):
        release = self.make_release()
        problems, facts = verify.release_problems(str(release), LOCK)
        self.assertEqual(problems, [])
        self.assertEqual((facts["zip"], facts["license_files"]), ("ChanceBlogDesktop-OCR-%s-win64.zip" % VERSION, 2))
        self.assertEqual(sorted(path.name for path in release.iterdir()), ["ChanceBlogDesktop-OCR-%s-win64.zip" % VERSION, "PACKAGE_INFO.json", "SHA256SUMS"])

    def test_the_command_line_prints_pass_and_returns_zero_or_prints_every_problem_and_returns_one(self):
        release = self.make_release()
        lock_file = self.root / "lock.json"
        lock_file.write_text(json.dumps(LOCK), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify.main(["--release", str(release), "--lock", str(lock_file)])
        self.assertEqual(code, 0)
        self.assertIn("[산출물 점검] 통과", out.getvalue())
        self.assertIn("라이선스 파일 2개", out.getvalue())
        bad = self.make_release(drop=("THIRD_PARTY_NOTICES.txt", "licenses/shapely/LICENSE_GEOS", "licenses/tqdm/LICENCE"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify.main(["--release", str(bad), "--lock", str(lock_file)])
        self.assertEqual(code, 1)
        self.assertIn("[산출물 점검] 실패", out.getvalue())
        self.assertIn("  ★ ", out.getvalue())
        self.assertEqual(verify.main(["--release", str(self.root / "none")]), 2)

    def test_the_default_lock_is_the_repository_lock_not_a_free_choice(self):
        self.assertEqual(Path(verify.DEFAULT_LOCK).resolve(), (support.ROOT / "ocr_addon" / "models.lock.json").resolve())
        problems, _facts = verify.release_problems(str(self.make_release()))
        self.assertTrue(any("잠금 값과 다르거나 없다" in item for item in problems), "진짜 잠금(진짜 모델 해시)으로는 가짜 모델이 통과하지 못한다")


class NoticeTest(ReleaseCase):
    """운영자 확인 030 ② — 고지문·소스 안내문을 폴더에 넣는 방식: 그 파일들이 압축 파일 안에 실제로 있어야 한다."""

    def test_a_missing_notice_file_or_licenses_folder_fails(self):
        self.expect(self.make_release(drop=("THIRD_PARTY_NOTICES.txt",)), "THIRD_PARTY_NOTICES.txt")
        self.expect(self.make_release(drop=("licenses/shapely/LICENSE_GEOS", "licenses/tqdm/LICENCE")), "licenses/")
        self.expect(self.make_release(drop=("THIRD_PARTY_NOTICES.txt", "licenses/shapely/LICENSE_GEOS", "licenses/tqdm/LICENCE")), "licenses/")

    def test_an_empty_notice_or_empty_license_file_fails(self):
        self.expect(self.make_release(bundle={**BUNDLE, "THIRD_PARTY_NOTICES.txt": b""}), "비어 있다")
        self.expect(self.make_release(bundle={**BUNDLE, "THIRD_PARTY_NOTICES.txt": "  \n\n".encode()}), "비어 있다")
        self.expect(self.make_release(bundle={**BUNDLE, "licenses/shapely/LICENSE_GEOS": b""}), "비어 있는 라이선스 파일")

    def test_a_notice_that_does_not_name_geos_and_lgpl_fails_and_the_spelling_case_does_not_matter(self):
        self.expect(self.make_release(bundle={**BUNDLE, "THIRD_PARTY_NOTICES.txt": "tqdm MPL-2.0 만 적었다".encode()}), "GEOS")
        self.expect(self.make_release(bundle={**BUNDLE, "THIRD_PARTY_NOTICES.txt": "GEOS 는 있는데 라이선스 이름이 없다".encode()}), "GEOS")
        self.expect(self.make_release(bundle={**BUNDLE, "THIRD_PARTY_NOTICES.txt": "라이선스는 LGPL 인데 부품 이름이 없다".encode()}), "GEOS")
        self.assertEqual(self.problems(self.make_release(bundle={**BUNDLE, "THIRD_PARTY_NOTICES.txt": "geos 는 lgpl-2.1 이다".encode()})), [])

    def test_geos_must_be_a_separate_dll_file_under_internal_not_somewhere_else(self):
        dll = "_internal/Shapely.libs/geos_c-1-abcdef.dll"
        self.expect(self.make_release(drop=(dll,)), "GEOS 가 별도 DLL")
        self.expect(self.make_release(bundle={**BUNDLE, "geos_c.dll": b"x"}, drop=(dll,)), "GEOS 가 별도 DLL")
        self.expect(self.make_release(bundle={**BUNDLE, "_internal/Shapely.libs/other.dll": b"x"}, drop=(dll,)), "GEOS 가 별도 DLL")
        self.assertEqual(self.problems(self.make_release(bundle={**BUNDLE, "_internal/shapely.libs/GEOS_C-2.DLL": b"x"}, drop=(dll,))), [], "대소문자·이름 뒤쪽은 상관없다")

    def test_the_geos_license_text_must_be_in_the_zip_even_when_other_license_files_are(self):
        """합친 빌드의 `missing_outputs` 가 꼭 요구하는 GEOS 전문(licenses/shapely/LICENSE_GEOS)을 이 점검도 압축 파일 쪽에서 다시 요구한다 — 고지문이 가리키는 파일이 압축 파일에 없는 채 올라가지 못하게."""
        problems = self.expect(self.make_release(drop=("licenses/shapely/LICENSE_GEOS",)), "GEOS 라이선스 전문")
        self.assertFalse(any("licenses/ 에 파일이 없다" in item for item in problems), "다른 라이선스 파일(licenses/tqdm/LICENCE)은 있다 — GEOS 전문만 빠졌다")
        for label, extra in (("다른 부품 폴더의 같은 이름", "licenses/other/LICENSE_GEOS"), ("이름 뒤에 글자", "licenses/shapely/LICENSE_GEOS.txt"), ("한 단계 더 깊음", "licenses/shapely/sub/LICENSE_GEOS"),
                             ("맨 위 폴더 밖", "LICENSE_GEOS")):
            with self.subTest(case=label):
                self.expect(self.make_release(bundle={**BUNDLE, extra: b"x"}, drop=("licenses/shapely/LICENSE_GEOS",)), "GEOS 라이선스 전문", label)

    def test_the_build_guard_and_the_verifier_ask_for_the_same_three_notice_outputs(self):
        """빌드(build_ocr_addon.py 의 이름 상수·missing_outputs)와 올리기 직전 점검(verify_release.py)이 같은 파일을 같은 이름으로 요구한다 — 한쪽만 이름을 바꾸면 알린다."""
        self.assertEqual((verify.NOTICE_ENTRY, verify.LICENSES_PREFIX, verify.GEOS_LICENSE_ENTRY),
                         ("ocr/" + build.NOTICES_NAME, "ocr/" + build.LICENSES_DIR + "/", "ocr/" + build.LICENSES_DIR + "/shapely/" + build.GEOS_LICENSE_NAME))
        self.assertEqual(build.missing_outputs(list(BUNDLE)), [], "온전한 묶음은 빌드 쪽 방어선도 통과한다")
        for names, build_word, verify_word in ((("THIRD_PARTY_NOTICES.txt",), "THIRD_PARTY_NOTICES.txt", "THIRD_PARTY_NOTICES.txt"), (("licenses/shapely/LICENSE_GEOS", "licenses/tqdm/LICENCE"), "licenses/", "licenses/"),
                                               (("licenses/shapely/LICENSE_GEOS",), "licenses/shapely/LICENSE_GEOS", "GEOS 라이선스 전문")):
            with self.subTest(dropped=names):
                self.assertTrue(any(build_word in item for item in build.missing_outputs([name for name in BUNDLE if name not in names])), names)
                self.expect(self.make_release(drop=names), verify_word, names)

    def test_the_notice_files_are_in_the_info_list_so_the_apps_folder_check_accepts_them(self):
        release = self.make_release()
        with zipfile.ZipFile(self.zip_path(release)) as archive:
            info = json.loads(archive.read("ocr/OCR_INFO.json").decode("utf-8"))
        listed = {item["path"] for item in info["files"]}
        self.assertIn("THIRD_PARTY_NOTICES.txt", listed)
        self.assertIn("licenses/shapely/LICENSE_GEOS", listed)
        sys.path.insert(0, str(support.ROOT / "src"))
        try:
            from chanceblog_desktop.service import ocr_addon as app_side
        finally:
            sys.path.remove(str(support.ROOT / "src"))
        folder = self.root / "extracted" / "ocr"
        with zipfile.ZipFile(self.zip_path(release)) as archive:
            archive.extractall(self.root / "extracted")
        with mock.patch.object(app_side, "EMBEDDED_FILES", EXPECTED):
            status = app_side.verify(str(folder))
        self.assertEqual((status.state, status.problems), ("ok", ()), "고지 파일이 든 압축 파일을 풀면 앱의 확인이 ok 로 읽는다")


class HashAndListTest(ReleaseCase):
    def test_the_sums_file_must_be_one_line_with_the_real_hash_and_the_real_name(self):
        release = self.make_release()
        name = self.zip_path(release).name
        real = sha(self.zip_path(release).read_bytes())
        for label, text in (("틀린 해시", "%s  %s\n" % ("0" * 64, name)), ("틀린 이름", "%s  other.zip\n" % real), ("두 줄", "%s  %s\n%s  %s\n" % (real, name, real, name)), ("빈 파일", ""),
                            ("한 칸만 띄움", "%s %s\n" % (real, name)), ("별표 모양", "%s *%s\n" % (real, name))):
            with self.subTest(case=label):
                (release / "SHA256SUMS").write_text(text, encoding="utf-8")
                self.expect(release, "SHA256SUMS", label)
        (release / "SHA256SUMS").write_text("%s  %s\n" % (real, name), encoding="utf-8")
        self.assertEqual(self.problems(release), [])

    def test_the_package_info_must_describe_the_real_zip(self):
        release = self.make_release()
        path = release / "PACKAGE_INFO.json"
        good = json.loads(path.read_text(encoding="utf-8"))
        cases = {"크기": lambda d: d["package"].update(bytes=d["package"]["bytes"] + 1), "해시": lambda d: d["package"].update(sha256="1" * 64), "이름": lambda d: d["package"].update(name="x.zip"),
                 "package 없음": lambda d: d.pop("package"), "variant": lambda d: d.update(variant="inner"), "다른 칸": lambda d: d.update(channel="other")}
        for label, mutate in cases.items():
            with self.subTest(case=label):
                data = json.loads(json.dumps(good))
                mutate(data)
                path.write_text(json.dumps(data), encoding="utf-8")
                self.assertTrue(self.problems(release), label)
        path.write_text("not json", encoding="utf-8")
        self.expect(release, "PACKAGE_INFO.json 를 읽지 못했다")
        path.write_text("[1, 2]", encoding="utf-8")
        self.expect(release, "객체가 아니다")
        path.write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(self.problems(release), [])

    def test_the_release_folder_holds_exactly_the_three_named_files(self):
        release = self.make_release()
        (release / "notes.txt").write_text("남은 파일", encoding="utf-8")
        self.expect(release, "정해진 셋")
        (release / "notes.txt").unlink()
        (release / "PACKAGE_INFO.json").rename(release / "PACKAGE_INFO.bak")
        self.expect(release, "정해진 셋")
        (release / "PACKAGE_INFO.bak").rename(release / "PACKAGE_INFO.json")
        extra = release / "ChanceBlogDesktop-OCR-9.9.9-win64.zip"
        extra.write_bytes(self.zip_path(release).read_bytes())
        self.expect(release, "정확히 하나")
        extra.unlink()
        for zipped in release.glob("*.zip"):
            zipped.unlink()
        self.expect(release, "정확히 하나")


class ZipContentTest(ReleaseCase):
    def test_every_entry_must_be_a_safe_name_under_ocr(self):
        for label, name in (("맨 위 폴더 밖", "evil.txt"), ("다른 폴더", "other/x.txt"), ("위로 올라감", "ocr/../x.txt"), ("역슬래시", "ocr/a" + chr(92) + "b.txt"), ("절대 경로", "/ocr/x.txt"),
                            ("드라이브", "ocr/C:/x.txt"), ("빈 조각", "ocr//x.txt"), ("점 조각", "ocr/./x.txt"), ("맨 위 폴더와 글자만 같음", "ocrX/x.txt"), ("맨 위 폴더 이름 그 자체", "ocr")):
            with self.subTest(case=label):
                release = self.make_release()
                self.rewrite_zip(release, lambda entries, name=name: entries + [(name, b"x")])
                # 윈도의 파이썬은 압축 파일에 쓸 때 역슬래시를 슬래시로 바꾼다 — 그 경우에도 목록에 없는 항목으로 걸린다(어느 쪽이든 걸리는 것이 요점이다)
                word = "정보 파일 목록에 없다" if label == "역슬래시" and sys.platform == "win32" else "안전하지 않은 이름"
                self.expect(release, word, label)

    def test_the_zip_name_is_as_strict_as_the_upload_glob_and_matches_the_names_the_build_makes(self):
        """올리기 글롭(ChanceBlogDesktop-OCR-*-win64.zip)보다 느슨하면 이름이 다른 압축 파일이 점검을 통과하고 업로드는 그 파일을 놓친다(독립 검증 Q 의 QP-2)."""
        for version in ("0.1.0-preview.1", "1.2.3", "10.20.30-rc.4+build.5"):
            self.assertTrue(verify.ZIP_NAME.fullmatch(rules.zip_name(version)), version)
        for bad in ("ChanceBlogDesktop-OCR-0.1.0-win32.zip", "ChanceBlogDesktop-OCR-0.1.0-win64.zip.bak", "ChanceBlogDesktop-0.1.0-win64.zip", "x-ChanceBlogDesktop-OCR-0.1.0-win64.zip",
                    "ChanceBlogDesktop-OCR-0.1-win64.zip", "ChanceBlogDesktop-OCR--win64.zip", "chanceblogdesktop-ocr-0.1.0-win64.zip", "ChanceBlogDesktop-OCR-0.1.0-win64.ZIP"):
            self.assertIsNone(verify.ZIP_NAME.fullmatch(bad), bad)

    def test_the_entry_limit_is_the_apps_own_file_limit(self):
        """이 점검이 허용하는 항목 수가 앱의 추가 도구 확인(service/ocr_addon.py)의 파일 수 상한과 다르면 점검은 통과하는데 앱이 거절하거나 그 반대가 된다(독립 검증 S 의 SP-3)."""
        sys.path.insert(0, str(support.ROOT / "src"))
        try:
            from chanceblog_desktop.service import ocr_addon as app_side
        finally:
            sys.path.remove(str(support.ROOT / "src"))
        self.assertEqual(verify.MAX_ENTRIES, app_side.MAX_FILES)

    def test_a_name_twice_or_too_many_entries_or_a_broken_zip_fail(self):
        release = self.make_release()
        self.rewrite_zip(release, lambda entries: entries + [("ocr/ocr_worker.exe", b"another")])
        self.expect(release, "두 번 있다")
        release = self.make_release()
        with mock.patch.object(verify, "MAX_ENTRIES", 3):
            self.expect(release, "너무 많다")
        release = self.make_release()
        self.zip_path(release).write_bytes(b"this is not a zip")
        self.refresh(release)
        self.expect(release, "압축 파일을 읽지 못했다")

    def test_entries_and_the_info_list_must_agree_line_by_line(self):
        def drop(name):
            return lambda entries: [item for item in entries if item[0] != name]

        def alter(name, data):
            return lambda entries: [(entry, data if entry == name else payload) for entry, payload in entries]
        cases = (("목록에 없는 항목", lambda entries: entries + [("ocr/extra.txt", b"x")], "정보 파일 목록에 없다"), ("목록의 파일이 압축 파일에 없다", drop("ocr/licenses/tqdm/LICENCE"), "압축 파일에 없다"),
                 ("내용이 바뀜(크기 같음)", alter("ocr/licenses/tqdm/LICENCE", b"X" * len(BUNDLE["licenses/tqdm/LICENCE"])), "크기·SHA-256"), ("내용이 바뀜(크기 다름)", alter("ocr/ocr_worker.exe", b"other-worker"), "크기·SHA-256"),
                 ("정보 파일이 없다", drop("ocr/OCR_INFO.json"), "OCR_INFO.json"), ("작업자가 없다", drop("ocr/ocr_worker.exe"), "ocr_worker.exe"))
        for label, change, word in cases:
            with self.subTest(case=label):
                release = self.make_release()
                self.rewrite_zip(release, change)
                self.expect(release, word, label)

    def test_a_bundle_without_the_worker_fails_even_when_the_info_file_agrees_with_the_zip(self):
        """정보 파일 목록도 작업자 없이 만들어졌으면 목록 대조는 통과한다 — 작업자가 꼭 있어야 한다는 점검이 따로 막는다."""
        problems = self.problems(self.make_release(drop=("ocr_worker.exe",)))
        self.assertTrue(any("압축 파일 안에 ocr/ocr_worker.exe 가 없다" in item for item in problems), problems)
        self.assertFalse(any("정보 파일 목록" in item for item in problems))

    def test_the_inner_info_must_have_the_names_the_app_requires_and_match_the_outer_copy(self):
        def edit_inner(mutate):
            def change(entries):
                out = []
                for name, data in entries:
                    if name == "ocr/OCR_INFO.json":
                        info = json.loads(data.decode("utf-8"))
                        mutate(info)
                        data = json.dumps(info).encode("utf-8")
                    out.append((name, data))
                return out
            return change
        for label, mutate, word in (("name", lambda i: i.update(name="ocr"), "앱이 요구하는"), ("proto", lambda i: i.update(proto=2), "앱이 요구하는"), ("목록 비움", lambda i: i.update(files=[]), "비어 있다"),
                                    ("바깥 사본과 다른 칸", lambda i: i.update(notice="바꿈"), "PACKAGE_INFO.json 이 압축 파일 안 OCR_INFO.json 과")):
            with self.subTest(case=label):
                release = self.make_release()
                self.rewrite_zip(release, edit_inner(mutate))
                self.expect(release, word, label)

    def test_an_info_file_that_is_not_an_object_fails_instead_of_skipping_every_info_check(self):
        """독립 검증 S 의 SP-7: 압축 파일 안 OCR_INFO.json 이 객체가 아니면(`[]`·`null`·`"x"`) 정보 파일 검사 전체(name·proto·checks·목록 대조)가 건너뛰어져 문제 0건으로 통과했다."""
        for label, payload in (("빈 목록", b"[]"), ("null", b"null"), ("글", b'"x"'), ("숫자", b"1"), ("참", b"true"), ("객체의 목록", b'[{"name": "ocr_addon", "proto": 1}]')):
            with self.subTest(case=label):
                release = self.make_release()
                self.rewrite_zip(release, lambda entries, payload=payload: [(name, payload if name == "ocr/OCR_INFO.json" else data) for name, data in entries])
                self.expect(release, "OCR_INFO.json 이 객체가 아니다", label)

    def test_models_and_dictionary_must_equal_the_lock_even_when_the_info_file_agrees_with_the_zip(self):
        for key in MODELS:
            with self.subTest(key=key):
                release = self.make_release(bundle={**BUNDLE, key: MODELS[key] + b"!"})
                problems = self.problems(release)
                self.assertTrue(any("잠금 값과 다르거나 없다: " + key in item for item in problems), problems)
                self.assertFalse(any("정보 파일 목록" in item for item in problems), "정보 파일과 압축 파일은 서로 맞다 — 잠금 값과만 다르다")
        self.expect(self.make_release(drop=("models/det/inference.onnx",)), "잠금 값과 다르거나 없다")
        broken = json.loads(json.dumps(LOCK))
        broken["files"][0]["source"]["commit"] = "main"
        problems, _facts = verify.release_problems(str(self.make_release()), broken)
        self.assertTrue(any(item.startswith("models.lock.json: ") for item in problems))


class GateTest(ReleaseCase):
    """산출물 점검은 올리기 직전의 마지막 문이다 — '있어야 할 것'만이 아니라 '없어야 할 것'(R2 금지 파일·R3 금지 부품)과 정보 파일에 적힌 빌드 점검 결과도 **압축 파일 쪽에서 다시** 본다
    (독립 검증 S 의 SP-1: 빌드 점검이 건너뛰어지거나 실패하고도 산출물이 만들어지는 길이 다시 열려도 금지 부품이 든 압축 파일은 여기서 걸린다 — 빌드가 먼저 막든 이 점검이 먼저 막든 우회가 없어야 한다)."""

    def test_files_the_build_forbids_are_found_again_in_the_zip_even_though_the_build_check_said_ok(self):
        banned = {"_internal/cv2/opencv_videoio_ffmpeg500_64.dll": b"ffmpeg", "_internal/Other/OPENCV_VIDEOIO_FFMPEG_X.DLL": b"ffmpeg", "_internal/certifi/cacert.pem": b"pem", "_internal/x/root.crt": b"crt", "_internal/x/private.key": b"key"}
        problems = self.expect(self.make_release(bundle={**BUNDLE, **banned}), "R2 묶음에 있으면 안 되는 파일", "FFmpeg DLL·pem·crt·key")
        text = " ".join(problems)
        for name in banned:                                                              # 메시지는 이름을 여섯 개까지 적는다 — 다섯 이름이 모두 보여야 한다
            self.assertIn(name, text, name)
        models = {"_internal/rapidocr/models/PP-OCRv6_det_small.onnx": b"default-model", "extra/other.onnx": b"x"}
        problems = self.expect(self.make_release(bundle={**BUNDLE, **models}), "R2 기본 모델", "기본 모델·알 수 없는 모델")
        for name in models:
            self.assertIn(name, " ".join(problems), name)

    def test_parts_the_build_forbids_are_found_again_in_the_zip_by_name_in_any_spelling_and_depth(self):
        nine = {"ssl", "_ssl", "_hashlib", "libcrypto", "libssl", "_overlapped", "_multiprocessing", "urllib3", "certifi"}     # 규칙 모듈의 목록이 아니라 글자 그대로(둘이 같이 틀리는 일이 없게)
        everything = {"_internal/ssl.pyd": b"x", "_internal/_ssl.cp312-win_amd64.pyd": b"x", "_internal/_hashlib.pyd": b"x", "_internal/libcrypto-3.dll": b"x", "_internal/libssl-3-x64.dll": b"x",
                      "_internal/_overlapped.pyd": b"x", "_internal/_multiprocessing.pyd": b"x", "_internal/urllib3/__init__.py": b"x", "_internal/certifi/__init__.py": b"x"}
        problems = self.expect(self.make_release(bundle={**BUNDLE, **everything}), "R3 묶음에 있으면 안 되는 부품", "금지 부품 아홉 가지가 한꺼번에")
        listed = [item for item in problems if "R3 묶음에 있으면 안 되는 부품" in item]
        self.assertEqual(len(listed), 1)
        self.assertEqual(set(listed[0].rsplit(": ", 1)[1].split(", ")), nine)
        shapes = (("폴더(직속)", {"_internal/urllib3/__init__.py": b"x"}, "urllib3"), ("깊은 곳 대문자 파일", {"_internal/sub/dir/_SSL.PYD": b"x"}, "_ssl"), ("버전 붙은 DLL", {"_internal/a/libcrypto-3-x64.dll": b"x"}, "libcrypto"),
                  ("설치 기록 폴더", {"_internal/urllib3-2.3.0.dist-info/RECORD": b"x"}, "urllib3"), ("맨 위 폴더", {"certifi/x.txt": b"x"}, "certifi"), ("맨 위 파일", {"_multiprocessing.pyd": b"x"}, "_multiprocessing"))
        for label, extra, key in shapes:
            with self.subTest(shape=label):
                problems = self.expect(self.make_release(bundle={**BUNDLE, **extra}), "R3 묶음에 있으면 안 되는 부품", label)
                listed = [item for item in problems if "R3 묶음에 있으면 안 되는 부품" in item]
                self.assertEqual([set(item.rsplit(": ", 1)[1].split(", ")) for item in listed], [{key}], label)

    def test_names_that_only_look_like_the_forbidden_ones_and_the_allowed_parts_pass(self):
        near = {"_internal/libsslx.dll": b"x", "_internal/ssl_helper.pyd": b"x", "_internal/sslkit.dll": b"x", "_internal/certifi_like/x.txt": b"x", "_internal/urllib.pyd": b"x", "_internal/_socket.pyd": b"x",
                "_internal/select.pyd": b"x", "_internal/python312.dll": b"x", "_internal/cv2/opencv_videoio_x.dll": b"x", "_internal/numpy.libs/libscipy_openblas64_-abc.dll": b"x", "_internal/rapidocr/config.yaml": b"x"}
        self.assertEqual(self.problems(self.make_release(bundle={**BUNDLE, **near})), [], "닮은 이름까지 막으면 정상 묶음이 걸린다")

    def test_a_release_whose_info_file_records_a_failed_build_check_fails_even_with_a_clean_zip(self):
        clean = {"ok": True, "problems": [], "selftest": {"ok": True}, "selftest_exit": 0}
        cases = (("점검 통과 아님", {"ok": False}, "checks.ok"), ("문제 기록이 남음", {"problems": ["R1 가져오기 표에 네트워크 DLL 이 있는 파일(허용 예외 밖): _internal/x.dll (ws2_32.dll)"]}, "checks.problems"),
                 ("자가 점검 통과 아님", {"selftest": {"ok": False}}, "checks.selftest_ok"), ("자가 점검 기록 없음", {"selftest": None}, "checks.selftest_ok"), ("자가 점검 종료 코드 1", {"selftest_exit": 1}, "checks.selftest_exit"),
                 ("종료 코드 참/거짓 글자", {"selftest_exit": False}, "checks.selftest_exit"), ("종료 코드 없음", {"selftest_exit": None}, "checks.selftest_exit"))
        for label, change, word in cases:
            with self.subTest(case=label):
                self.expect(self.make_release(check=change), "정보 파일의 빌드 점검 기록", label)
                self.expect(self.make_release(check=change), word, label)
        self.assertEqual(self.problems(self.make_release(check=clean)), [], "통과 기록이면 정상")

    def test_a_missing_or_broken_checks_field_fails(self):
        def edit_inner(mutate):
            def change(entries):
                out = []
                for name, data in entries:
                    if name == "ocr/OCR_INFO.json":
                        info = json.loads(data.decode("utf-8"))
                        mutate(info)
                        data = json.dumps(info).encode("utf-8")
                    out.append((name, data))
                return out
            return change
        for label, mutate in (("checks 없음", lambda i: i.pop("checks")), ("checks 가 목록", lambda i: i.update(checks=[1])), ("checks 가 글", lambda i: i.update(checks="ok"))):
            with self.subTest(case=label):
                release = self.make_release()
                self.rewrite_zip(release, edit_inner(mutate))
                self.expect(release, "정보 파일의 빌드 점검 기록이 없다", label)

    def test_the_two_helpers_judge_the_record_and_the_names_exactly(self):
        good = {"ok": True, "problems": [], "selftest_ok": True, "selftest_exit": 0}
        self.assertEqual(verify.checks_problems({"checks": good}), [])
        for key, bad in (("ok", False), ("ok", 1), ("ok", None), ("problems", ["x"]), ("problems", None), ("selftest_ok", False), ("selftest_ok", 1), ("selftest_exit", 1), ("selftest_exit", True), ("selftest_exit", "0")):
            with self.subTest(key=key, bad=bad):
                self.assertEqual(len(verify.checks_problems({"checks": {**good, key: bad}})), 1)
        self.assertEqual(len(verify.checks_problems({})), 1)
        self.assertEqual(verify.part_names({"ocr/ocr_worker.exe": (1, "x"), "ocr/_internal/urllib3/a/b.py": (1, "x"), "ocr/_internal/a.pyd": (1, "x"), "ocr/_internal/d/E.DLL": (1, "x"), "ocr/models/det/inference.onnx": (1, "x")}),
                         {"ocr_worker.exe", "_internal", "urllib3", "a.pyd", "d", "E.DLL", "models"})


if __name__ == "__main__":
    unittest.main()
