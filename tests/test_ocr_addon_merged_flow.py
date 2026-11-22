"""D 를 B1 최종 위로 얹은 빌드 스크립트(`ocr_addon/build_ocr_addon.py`)의 **전체 연결** 시험 — 충돌 풀이가 지키려는 양쪽 뜻을 한 줄기로 못박는다.

  B1 의 뜻: ① 라이선스 전문(licenses/)·고지문(THIRD_PARTY_NOTICES.txt)·GEOS 칸을 정보 파일에 싣는다(운영자 확인 030 ②). GEOS 전문·판·별도 GEOS 파일을 못 찾으면 조용히 건너뛰지 않고 멈춘다.
           ② 점검이 실패하면 정보 파일·zip 을 만들지 않고 종료 코드 1(독립 검증 S 의 SP-1) — 점검에 실패하고도 zip 을 만드는 옛 모양으로 돌아가지 않는다.
  D 의 뜻:  ③ 규칙(R1–R4)·키 모양 훑기·결정적 zip·점검 없이는 정보 파일·zip 없음, 올리기 직전 점검(verify_release.py)이 압축 파일 쪽에서 다시 판정한다.
  풀이가 새로 만든 연결: ④ 고지 파일 만들기(`notices` 단계)가 **점검 앞**이라서 점검(R2 금지 이름·키 모양 훑기)이 고지 파일도 본다 ⑤ notices 단계가 남긴 GEOS 기록(`geos.json`, 묶음 밖)을 info 단계가 읽는다(단계를 하나씩 따로 불러도
           이어진다) ⑥ 합친 빌드의 산출물을 올리기 직전 점검과 앱의 추가 도구 확인이 모두 ok 로 읽는다.

freeze·assemble·remove 와 묶음을 읽는 함수(가져오기 표·자가 점검·DLL 출처·모듈 목록·설치된 판)만 가짜이고, 고지 만들기·점검·정보 파일·zip·`main` 은 진짜다 — PyInstaller·pefile·진짜 모델 없이 CI 에서 돈다.
"""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_build_support as support  # noqa: E402

build = support.load("build_ocr_addon")
verify = support.load("verify_release")
rules = build.rules
STATE = {"commit": "0123456789abcdef0123456789abcdef01234567", "epoch": 1794873600, "epoch_from": "git commit", "committed_utc": "2026-11-17T00:00:00Z", "clean": True, "dirty_count": 0}
MODELS = {"models/det/inference.onnx": b"det-model", "models/rec/inference.onnx": b"rec-model-bytes", "data/ppocrv5_korean_dict.txt": b"dict\nbytes\n"}
BUNDLED = {"shapely", "numpy", "onnxruntime", "tqdm"}
SITE = {
    "numpy": ["numpy-2.5.4.dist-info/METADATA", "numpy-2.5.4.dist-info/licenses/LICENSE.txt", "numpy/__init__.py"],
    "onnxruntime": ["onnxruntime-1.31.1.dist-info/METADATA", "onnxruntime/LICENSE", "onnxruntime/ThirdPartyNotices.txt", "onnxruntime/capi/onnxruntime_pybind11_state.pyd"],
    "shapely": ["shapely-2.2.0.dist-info/licenses/LICENSE.txt", "shapely-2.2.0.dist-info/licenses/LICENSE_GEOS", "shapely/__init__.py", "shapely.libs/geos-aaaa.dll"],
    "tqdm": ["tqdm-4.70.1.dist-info/licenses/LICENCE", "tqdm/__init__.py"],
}
LICENSES = {"shapely": "BSD-3-Clause", "numpy": "BSD-3-Clause", "onnxruntime": "MIT License", "tqdm": "MPL-2.0 AND MIT"}
PE_ROWS = [{"path": "ocr_worker.exe", "imports": ["kernel32.dll"], "delay": [], "bound": []}, {"path": "_internal/python312.dll", "imports": ["kernel32.dll", "ws2_32.dll"], "delay": [], "bound": []}]
REPORT = {"frozen": True, "guard_active": True, "negative_control": [{"blocked_and_counted": True}] * 5, "negative_control_attempts": 5, "negative_control_recent_targets_only_test_addresses": True,
          "loopback_not_counted": True, "files_ok": True, "imports": {"requests": "0+offline-stub"}, "imports_failed": [], "selfcheck_ok": True, "guard_attempts_during_normal_read": 0, "ok": True,
          "imports_optional": {name: "없음(묶이지 않음) x" for name in ("ssl", "urllib3", "certifi", "asyncio", "multiprocessing")}}


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
VERSIONS = {pin["name"]: pin["version"] for pin in rules.parse_lock(support.read("ocr_addon/requirements-ocr.lock"))}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


class FakeDist:
    """설치된 분포 흉내 — `files`(기록 경로들)와 `locate_file` 만 안다."""

    def __init__(self, root, files):
        self.root, self.files = root, list(files)

    def locate_file(self, path):
        return os.path.join(self.root, *str(path).split("/"))


def make_site(root, spec, texts):
    dists = {}
    for name, records in spec.items():
        folder = Path(root) / ("site-" + name)
        for record in records:
            write(folder / Path(*record.split("/")), texts.get(record, "TEXT OF %s %s" % (name, record)))
        dists[name] = FakeDist(str(folder), records)

    def lookup(name):
        if name not in dists:
            raise LookupError(name)
        return dists[name]
    return lookup


class MergedFlowCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.models = self.root / "models"                        # 이름만 넘긴다(가짜 assemble 이 읽지 않는다)
        self.stages = []
        self.removed = []                                         # 가짜 remove 가 removed.json 에 적을 기록

    def fake_stages(self, out_dir_holder):
        """freeze·assemble·remove 를 작은 가짜 묶음을 만드는 함수로 — 부른 순서를 기록한다."""
        def freeze(out_dir, epoch):
            self.stages.append("freeze")
            dst = Path(build.dist_dir(out_dir))
            write(dst / "ocr_worker.exe", b"worker-bytes")
            write(dst / "_internal" / "python312.dll", b"python-dll")
            write(dst / "_internal" / "Shapely.libs" / "geos-aaaa.dll", b"geos-dll-bytes")
            write(dst / "_internal" / "rapidocr" / "config.yaml", "Global:\n  use_cls: false\n")

        def assemble(out_dir, models_dir):
            self.stages.append("assemble")
            dst = Path(build.dist_dir(out_dir))
            for key, data in MODELS.items():
                write(dst / Path(*key.split("/")), data)

        def remove(out_dir):
            self.stages.append("remove")
            write(Path(out_dir) / "removed.json", json.dumps(self.removed))
        return freeze, assemble, remove

    @contextlib.contextmanager
    def environment(self, *, site=None, texts=None, rows=None, report=None):
        """가짜 단계·묶음 읽기 함수를 끼운 환경 — `with` 안에서 `call_main(...)` 으로 main 을 부른다."""
        lookup = make_site(self.root, site or SITE, texts or {})
        freeze, assemble, remove = self.fake_stages(None)
        real = build.import_packaging()

        class FakeBp:
            """본체 packaging 을 그대로 쓰되(출력 폴더 점검·금지 이름 목록) DLL 출처 점검만 '문제 없음' 으로 — 진짜는 PyInstaller 의 묶음 목록 파일이 있어야 돈다."""
            check_binary_origins = staticmethod(lambda toc: [])

            def __getattr__(self, name):
                return getattr(real, name)
        fake_bp = FakeBp()
        with contextlib.ExitStack() as stack:
            for name, value in (("freeze", freeze), ("assemble", assemble), ("remove_unused", remove)):
                stack.enter_context(mock.patch.object(build, name, side_effect=value))
            stack.enter_context(mock.patch.object(build.im, "distribution", lookup))
            stack.enter_context(mock.patch.object(build, "log"))
            stack.enter_context(mock.patch.object(build, "source_state", return_value=dict(STATE)))
            stack.enter_context(mock.patch.object(build, "bundled_modules", return_value=set(BUNDLED)))
            stack.enter_context(mock.patch.object(build, "installed_version", side_effect=lambda name: VERSIONS.get(name)))
            stack.enter_context(mock.patch.object(build, "pypi_license", side_effect=lambda name: LICENSES.get(name)))
            stack.enter_context(mock.patch.object(build, "read_geos_version", lambda: "3.99.9"))
            stack.enter_context(mock.patch.object(build, "load_lock", return_value=(LOCK, EXPECTED)))
            stack.enter_context(mock.patch.object(build, "import_packaging", return_value=fake_bp))
            stack.enter_context(mock.patch.object(build, "pe_rows", return_value=(rows if rows is not None else [dict(item) for item in PE_ROWS], [])))
            stack.enter_context(mock.patch.object(build, "run_selftest", return_value=(0, report if report is not None else dict(REPORT), [], 1.0, "")))
            yield

    def call_main(self, stage, out, *, require_clean=True):
        argv = [stage, "--out-dir", str(out)]
        if stage in ("all", "assemble"):
            argv += ["--models-dir", str(self.models)]
        if require_clean:
            argv.append("--require-clean")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = build.main(argv)
        return code, errors.getvalue()

    def zip_of(self, out):
        return Path(out) / "release" / ("ChanceBlogDesktop-OCR-%s-win64.zip" % build.read_version())


class GoodBuildTest(MergedFlowCase):
    def test_a_good_build_makes_a_release_that_the_verifier_and_the_apps_check_both_accept(self):
        out = self.root / "out"
        with self.environment():
            code, err = self.call_main("all", out)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.stages, ["freeze", "assemble", "remove"])
        release = out / "release"
        problems, facts = verify.release_problems(str(release), LOCK)
        self.assertEqual(problems, [], "올리기 직전 점검이 합친 빌드의 산출물을 문제 없이 읽는다")
        with zipfile.ZipFile(self.zip_of(out)) as archive:
            names = set(archive.namelist())
            self.assertEqual(facts["license_files"], len([name for name in names if name.startswith("ocr/licenses/")]))
            self.assertEqual(facts["license_files"], 6, "numpy 1 + onnxruntime 2 + shapely 2 + tqdm 1")
            notice = archive.read("ocr/THIRD_PARTY_NOTICES.txt").decode("utf-8")
            info = json.loads(archive.read("ocr/OCR_INFO.json").decode("utf-8"))
        self.assertTrue({"ocr/THIRD_PARTY_NOTICES.txt", "ocr/licenses/shapely/LICENSE_GEOS", "ocr/licenses/shapely/LICENSE.txt", "ocr/licenses/numpy/LICENSE.txt", "ocr/licenses/tqdm/LICENCE",
                         "ocr/licenses/onnxruntime/onnxruntime/ThirdPartyNotices.txt", "ocr/_internal/Shapely.libs/geos-aaaa.dll"} <= names, sorted(names))
        self.assertFalse([name for name in names if name.endswith("geos.json")], "geos.json 은 묶음 밖 기록이다")
        self.assertIn("LGPL-2.1", notice)
        self.assertIn("3.99.9", notice)
        self.assertEqual(info["geos"], {"name": "GEOS", "version": "3.99.9", "license": "LGPL-2.1", "dll_files": ["_internal/Shapely.libs/geos-aaaa.dll"], "license_file": "licenses/shapely/LICENSE_GEOS",
                                        "replaceable": True, "source_host": "libgeos.org", "source_included": False})
        self.assertEqual(info["license_notes"], build.license_notes(info["geos"]))
        self.assertEqual(sorted(path for path in names if path != "ocr/OCR_INFO.json"), sorted("ocr/" + item["path"] for item in info["files"]), "정보 파일의 목록이 압축 파일 항목과 한 줄씩 같다")
        self.assertEqual(info["checks"]["ok"], True)
        sys.path.insert(0, str(support.ROOT / "src"))
        try:
            from chanceblog_desktop.service import ocr_addon as app_side
        finally:
            sys.path.remove(str(support.ROOT / "src"))
        extracted = self.root / "extracted"
        with zipfile.ZipFile(self.zip_of(out)) as archive:
            archive.extractall(extracted)
        with mock.patch.object(app_side, "EMBEDDED_FILES", EXPECTED):
            status = app_side.verify(str(extracted / "ocr"))
        self.assertEqual((status.state, status.problems), ("ok", ()), "앱의 추가 도구 확인이 합친 빌드의 폴더를 ok 로 읽는다")

    def test_what_the_remove_stage_recorded_reaches_the_notice_and_nothing_is_claimed_when_nothing_was_removed(self):
        """remove 단계가 남긴 기록(removed.json)을 notices 단계가 읽어 고지문의 '뺀 것' 칸에 싣는다 — 연결이 끊기면 빠진 FFmpeg 안내가 사라진다."""
        plain = self.root / "plain"
        with self.environment():
            self.assertEqual(self.call_main("all", plain)[0], 0)
        with zipfile.ZipFile(self.zip_of(plain)) as archive:
            self.assertNotIn("[4]", archive.read("ocr/THIRD_PARTY_NOTICES.txt").decode("utf-8"))
        self.removed = [{"what": "opencv FFmpeg DLL(영상 입출력, 쓰지 않음)", "path": "_internal/cv2/opencv_videoio_ffmpeg500_64.dll", "bytes": 1}]
        recorded = self.root / "recorded"
        with self.environment():
            self.assertEqual(self.call_main("all", recorded)[0], 0)
        with zipfile.ZipFile(self.zip_of(recorded)) as archive:
            notice = archive.read("ocr/THIRD_PARTY_NOTICES.txt").decode("utf-8")
            info = json.loads(archive.read("ocr/OCR_INFO.json").decode("utf-8"))
        self.assertIn("[4]", notice)
        self.assertIn("opencv_videoio_ffmpeg", notice)
        self.assertEqual(info["removed_from_bundle"], self.removed, "정보 파일의 '뺀 것' 도 같은 기록이다")

    def test_the_stages_run_one_by_one_through_files_alone_give_the_same_zip_as_all(self):
        """단계를 따로 불러도(notices 가 남긴 geos.json·check_result.json·OCR_INFO.json 만 건네받아) 이어지고, 같은 입력이면 같은 압축 파일 바이트다."""
        whole = self.root / "whole"
        with self.environment():
            self.assertEqual(self.call_main("all", whole)[0], 0)
        staged = self.root / "staged"
        with self.environment():
            for stage in ("freeze", "assemble", "remove", "notices", "check", "info", "zip"):
                code, err = self.call_main(stage, staged)
                self.assertEqual((stage, code, err), (stage, 0, ""))
        self.assertEqual(self.zip_of(staged).read_bytes(), self.zip_of(whole).read_bytes())
        self.assertTrue((staged / build.GEOS_RECORD).is_file())
        again = self.root / "again"
        with self.environment():
            self.assertEqual(self.call_main("all", again)[0], 0)
        self.assertEqual(self.zip_of(again).read_bytes(), self.zip_of(whole).read_bytes(), "같은 입력이면 같은 바이트(고지 파일에도 시각이 없다)")


class CheckSeesTheNoticesTest(MergedFlowCase):
    """④ — notices 가 점검 앞이라서 점검이 고지 파일도 본다. 순서가 뒤집히면(점검 뒤 고지) 아래 시험들이 알린다."""

    def test_a_secret_shaped_text_inside_a_license_file_fails_the_check_and_nothing_is_made_after_it(self):
        secret = "memo CANARY_" + "AI" + "za" + "A" * 35 + " end"
        out = self.root / "out"
        with self.environment(texts={"numpy-2.5.4.dist-info/licenses/LICENSE.txt": secret}):
            code, _err = self.call_main("all", out)
        self.assertEqual(code, 1)
        result = json.loads((out / "check_result.json").read_text(encoding="utf-8"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("키 모양" in problem and "licenses/numpy/LICENSE.txt" in problem for problem in result["problems"]), result["problems"])
        self.assertFalse((Path(build.dist_dir(str(out))) / "OCR_INFO.json").exists())
        self.assertFalse(list((out / "release").glob("*")), "점검에 걸리면 압축 파일도 SHA256SUMS 도 만들지 않는다")

    def test_a_secret_shaped_text_inside_a_license_file_without_an_extension_fails_the_check_too(self):
        """LICENSE·LICENCE·COPYING·LICENSE_GEOS 처럼 확장자 없는 라이선스 파일이 대부분이다 — licenses/ 아래는 확장자와 상관없이 훑는다."""
        secret = "memo CANARY_" + "AI" + "za" + "A" * 35 + " end"
        for record, shown in (("onnxruntime/LICENSE", "licenses/onnxruntime/onnxruntime/LICENSE"), ("shapely-2.2.0.dist-info/licenses/LICENSE_GEOS", "licenses/shapely/LICENSE_GEOS"), ("tqdm-4.70.1.dist-info/licenses/LICENCE", "licenses/tqdm/LICENCE")):
            with self.subTest(record=record):
                out = self.root / ("out_" + record.replace("/", "_"))
                with self.environment(texts={record: secret}):
                    code, _err = self.call_main("all", out)
                self.assertEqual(code, 1)
                result = json.loads((out / "check_result.json").read_text(encoding="utf-8"))
                self.assertTrue(any("키 모양" in problem and shown in problem for problem in result["problems"]), result["problems"])
                self.assertFalse((Path(build.dist_dir(str(out))) / "OCR_INFO.json").exists())

    def test_a_forbidden_name_inside_the_licenses_folder_fails_the_check(self):
        site = dict(SITE, tqdm=SITE["tqdm"] + ["tqdm-4.70.1.dist-info/licenses/third_party_license.pem"])
        out = self.root / "out"
        with self.environment(site=site):
            code, _err = self.call_main("all", out)
        self.assertEqual(code, 1)
        result = json.loads((out / "check_result.json").read_text(encoding="utf-8"))
        self.assertTrue(any("묶음에 있으면 안 되는 파일" in problem and "licenses/tqdm/third_party_license.pem" in problem for problem in result["problems"]), result["problems"])
        self.assertFalse(list((out / "release").glob("*")))

    def test_the_notice_files_are_in_the_list_the_check_hands_to_the_rules(self):
        out = self.root / "out"
        seen = {}
        real = rules.bundle_file_problems

        def spy(sizes, expected, digest_of):
            seen["paths"] = sorted(sizes)
            return real(sizes, expected, digest_of)
        with self.environment(), mock.patch.object(rules, "bundle_file_problems", side_effect=spy):
            self.assertEqual(self.call_main("all", out)[0], 0)
        self.assertIn("THIRD_PARTY_NOTICES.txt", seen["paths"])
        self.assertIn("licenses/shapely/LICENSE_GEOS", seen["paths"])


class FailureShapesTest(MergedFlowCase):
    def test_a_failed_check_leaves_no_info_file_and_no_zip_even_though_the_notices_were_made(self):
        """B1 의 SP-1 — 점검에 실패하고도 zip 을 만드는 옛 모양으로 돌아가지 않는다(고지 파일은 이미 만들어져 있어도)."""
        out = self.root / "out"
        rows = [dict(item) for item in PE_ROWS] + [{"path": "_internal/_ssl.pyd", "imports": ["ws2_32.dll"], "delay": [], "bound": []}]
        with self.environment(rows=rows):
            code, _err = self.call_main("all", out)
        self.assertEqual(code, 1)
        self.assertTrue((Path(build.dist_dir(str(out))) / "THIRD_PARTY_NOTICES.txt").is_file(), "고지 단계는 점검 앞에서 이미 끝나 있었다")
        self.assertFalse((Path(build.dist_dir(str(out))) / "OCR_INFO.json").exists())
        self.assertFalse(list((out / "release").glob("*")))
        self.assertEqual(json.loads((out / "check_result.json").read_text(encoding="utf-8"))["ok"], False)
        for stage in ("info", "zip"):                                  # 따로 불러도 통과한 점검 결과 없이는 만들지 않는다
            with self.environment():
                code, err = self.call_main(stage, out)
            self.assertEqual(code, 2, stage)
            self.assertIn("점검", err)
        self.assertFalse(list((out / "release").glob("*")))

    def test_a_missing_geos_license_stops_before_the_check_with_two_and_leaves_no_check_result_info_or_zip(self):
        site = dict(SITE, shapely=[record for record in SITE["shapely"] if "LICENSE_GEOS" not in record])
        out = self.root / "out"
        with self.environment(site=site):
            code, err = self.call_main("all", out)
        self.assertEqual(code, 2)
        self.assertIn("LICENSE_GEOS", err)
        self.assertFalse((out / "check_result.json").exists(), "점검까지 가지 못했다")
        self.assertFalse((out / build.GEOS_RECORD).exists())
        self.assertFalse((Path(build.dist_dir(str(out))) / "THIRD_PARTY_NOTICES.txt").exists())
        self.assertFalse((Path(build.dist_dir(str(out))) / "OCR_INFO.json").exists())
        self.assertFalse(list((out / "release").glob("*")))

    def test_the_geos_version_or_a_separate_geos_file_that_cannot_be_found_also_stops_the_build(self):
        out = self.root / "no_version"
        with self.environment():
            with mock.patch.object(build, "read_geos_version", lambda: None):
                code, err = self.call_main("all", out)
        self.assertEqual(code, 2)
        self.assertIn("GEOS 판", err)
        self.assertFalse((out / "check_result.json").exists())
        out = self.root / "no_dll"
        with self.environment():
            with mock.patch.object(build, "geos_dll_files", return_value=[]):
                code, err = self.call_main("all", out)
        self.assertEqual(code, 2)
        self.assertIn("geos*.dll", err)
        self.assertFalse((out / "check_result.json").exists())

    def test_a_build_that_skipped_the_notices_stage_is_stopped_by_the_check_and_then_by_the_info_stage(self):
        """notices 를 건너뛴 묶음은 점검이 '고지 산출물이 없다' 로 막고, 점검 없이 info 로 가도 geos.json 이 없어 막는다."""
        out = self.root / "out"
        with self.environment():
            for stage in ("freeze", "assemble", "remove"):
                self.assertEqual(self.call_main(stage, out)[0], 0)
            code, _err = self.call_main("check", out)
        self.assertEqual(code, 1)
        result = json.loads((out / "check_result.json").read_text(encoding="utf-8"))
        self.assertTrue(any("라이선스 고지 산출물이 없다" in problem for problem in result["problems"]), result["problems"])
        with self.environment():
            check_path = out / "check_result.json"
            check_path.write_text(json.dumps(dict(result, ok=True, problems=[])), encoding="utf-8")        # 점검을 통과했다고 거짓으로 적어도
            code, err = self.call_main("info", out)
        self.assertEqual(code, 2)
        self.assertIn(build.GEOS_RECORD, err)
        self.assertFalse((Path(build.dist_dir(str(out))) / "OCR_INFO.json").exists())


if __name__ == "__main__":
    unittest.main()
