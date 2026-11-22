"""글자 읽기 추가 도구 빌드(`ocr_addon/build_ocr_addon.py`)의 라이선스 전문 모으기·고지문 생성(운영자 확인 030 ② — GEOS(LGPL-2.1)·MPL-2.0 의무는 라이선스 전문·고지문·소스 안내문을 추가 도구 폴더에 넣는 방식으로 지킨다.
원본 소스 압축 파일은 넣지 않는다 — 새 내려받기 없음). **빌드 없이 도는 순수 함수·가짜 설치 폴더 시험**이라 PyInstaller·PySide6·진짜 패키지가 없어도 CI 에서 돈다.

지키는 것:
  1) 고지문 — GEOS 칸(LGPL-2.1·별도 파일 geos*.dll 이라 바꿔 끼울 수 있음·같은 버전 소스를 공식 배포처에서 받으라는 안내·판은 OCR_INFO.json 의 geos 칸), MPL-2.0 칸(tqdm·onnxruntime 안 Eigen), 묶음에 든 부품만 담은 표,
     인터넷 주소의 스킴·물결표가 없다(받는 곳은 host 글자만).
  2) 라이선스 전문 모으기 — 묶음에 든 부품마다 설치된 분포에서 라이선스·고지문 파일을 licenses/<이름>/ 로 복사하고, GEOS 의 LICENSE_GEOS 를 못 찾으면 **조용히 건너뛰지 않고 빌드를 멈춘다**(판을 못 읽거나 별도 GEOS 파일이 없을 때도).
  3) 산출 목록 — OCR_INFO.json 의 files 에 licenses/ 와 THIRD_PARTY_NOTICES.txt(와 GEOS 라이선스 전문)가 있고, info 단계가 그 파일들을 목록에 넣은 뒤 정보 파일을 쓴다. license_notes 는 '방식 미정' 이 아니라 확인 030 ② 에 따른다는 문구다.
  4) 새 코드는 네트워크·인터넷 주소를 쓰지 않는다(소스 규칙).
"""
import hashlib
import importlib.util
import inspect
import json
import os
import re
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = ROOT / "ocr_addon" / "build_ocr_addon.py"


def load_build():
    spec = importlib.util.spec_from_file_location("build_ocr_addon_under_test", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = load_build()

PACKAGES = [
    {"name": "numpy", "version": "2.5.4", "license_metadata": "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", "bundled_in_dist": True},
    {"name": "onnxruntime", "version": "1.31.1", "license_metadata": "MIT License", "bundled_in_dist": True},
    {"name": "shapely", "version": "2.2.0", "license_metadata": "BSD-3-Clause", "bundled_in_dist": True},
    {"name": "tqdm", "version": "4.70.1", "license_metadata": "MPL-2.0 AND MIT", "bundled_in_dist": True},
    {"name": "certifi", "version": "2026.10.23", "license_metadata": "MPL-2.0", "bundled_in_dist": False},
    {"name": "flatbuffers", "version": "25.12.19", "license_metadata": "Apache 2.0", "bundled_in_dist": True},
]
GEOS = {"name": "GEOS", "version": "3.99.9", "license": "LGPL-2.1", "dll_files": ["_internal/Shapely.libs/geos-aaaa.dll", "_internal/Shapely.libs/geos_c-bbbb.dll"], "license_file": "licenses/shapely/LICENSE_GEOS",
        "replaceable": True, "source_host": "libgeos.org", "source_included": False}
COLLECTED = {"numpy": ["LICENSE.txt"], "onnxruntime": ["onnxruntime/LICENSE", "onnxruntime/ThirdPartyNotices.txt"], "shapely": ["LICENSE.txt", "LICENSE_GEOS", "LICENSE_win32"], "tqdm": ["LICENCE"], "flatbuffers": []}

SITE = {
    "numpy": ["numpy-2.5.4.dist-info/METADATA", "numpy-2.5.4.dist-info/licenses/LICENSE.txt", "numpy-2.5.4.dist-info/licenses/numpy/_core/src/highway/LICENSE", "numpy/__init__.py"],
    "onnxruntime": ["onnxruntime-1.31.1.dist-info/METADATA", "onnxruntime/LICENSE", "onnxruntime/ThirdPartyNotices.txt", "onnxruntime/capi/onnxruntime_pybind11_state.pyd"],
    "shapely": ["shapely-2.2.0.dist-info/licenses/LICENSE.txt", "shapely-2.2.0.dist-info/licenses/LICENSE_GEOS", "shapely-2.2.0.dist-info/licenses/LICENSE_win32", "shapely/__init__.py",
                "shapely.libs/geos-aaaa.dll"],
    "tqdm": ["tqdm-4.70.1.dist-info/licenses/LICENCE", "tqdm/__init__.py"],
    "certifi": ["certifi-2026.10.23.dist-info/licenses/LICENSE"],
    "flatbuffers": ["flatbuffers-25.12.19.dist-info/METADATA", "flatbuffers/__init__.py"],
}


class FakeDist:
    """설치된 분포 흉내 — `files`(기록 경로들)와 `locate_file` 만 안다."""

    def __init__(self, root, files):
        self.root, self.files = root, list(files)

    def locate_file(self, path):
        return os.path.join(self.root, *str(path).replace(chr(92), "/").split("/"))


def make_site(root, spec):
    """spec 의 모든 기록 경로에 글자 파일을 만들고 {이름: FakeDist} 를 돌려준다."""
    dists = {}
    for name, records in spec.items():
        folder = os.path.join(root, "site-" + name)
        for record in records:
            path = os.path.join(folder, *record.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(("TEXT OF %s %s" % (name, record)).encode("utf-8"))
        dists[name] = FakeDist(folder, records)
    return dists


def lookup_of(dists):
    def lookup(name):
        if name not in dists:
            raise LookupError(name)
        return dists[name]
    return lookup


def make_bundle(root, geos_names=("geos-aaaa.dll", "geos_c-bbbb.dll")):
    """묶음 폴더(dist/ocr_addon) 흉내 — 작업자·별도 GEOS 파일·다른 DLL 하나."""
    dst = os.path.join(root, "dist", "ocr_addon")
    libs = os.path.join(dst, "_internal", "Shapely.libs")
    os.makedirs(libs, exist_ok=True)
    for name in tuple(geos_names) + ("msvcp140-cccc.dll",):
        with open(os.path.join(libs, name), "wb") as handle:
            handle.write(b"DLL " + name.encode("ascii"))
    with open(os.path.join(dst, "ocr_worker.exe"), "wb") as handle:
        handle.write(b"EXE")
    return dst


def listing(dst):
    found = []
    for folder, _dirs, names in os.walk(dst):
        for name in names:
            found.append(os.path.relpath(os.path.join(folder, name), dst).replace(os.sep, "/"))
    return sorted(found)


class NoticeTextTest(unittest.TestCase):
    def setUp(self):
        self.text = B.render_notices(PACKAGES, GEOS, COLLECTED)

    def test_the_geos_part_says_what_the_license_is_that_it_can_be_swapped_and_where_the_same_version_source_is(self):
        part = self.text.split("[2]")[1].split("[3]")[0]                    # 다른 칸(MPL 안내에도 '같은 버전 소스' 가 있다)에 기대지 않고 GEOS 칸만 본다
        for needle in ("GEOS", "LGPL-2.1", "별도 파일 geos*.dll", "바꿔 끼울 수 있음", "같은 버전 소스", "OCR_INFO.json 의 geos 칸", "3.99.9", "libgeos.org", "licenses/shapely/LICENSE_GEOS", "geos-aaaa.dll", "geos_c-bbbb.dll"):
            self.assertIn(needle, part, needle)
        self.assertIn("원본 소스 압축 파일을 넣지 않았다", part, "소스 압축 파일은 넣지 않는다는 결정이 글에 있어야 한다")

    def test_the_mpl_part_names_tqdm_and_the_eigen_inside_onnxruntime(self):
        for needle in ("MPL-2.0", "tqdm 4.70.1", "Eigen", "onnxruntime 1.31.1", "ThirdPartyNotices.txt", "고치지 않은 채 다시 배포한다", "각 프로젝트가 공개 배포하는 같은 버전 소스"):
            self.assertIn(needle, self.text, needle)
        self.assertNotIn("MPL-2.0 조건의 부품이 없다", self.text, "MPL 부품이 있는데 없다고 적으면 안 된다")

    def test_the_table_has_only_the_parts_in_the_bundle_with_name_version_license_and_the_folder_of_the_full_text(self):
        self.assertIn("- numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | licenses/numpy/ (1개 파일)", self.text)
        self.assertIn("- shapely | 2.2.0 | BSD-3-Clause | licenses/shapely/ (3개 파일)", self.text)
        self.assertIn("- onnxruntime | 1.31.1 | MIT License | licenses/onnxruntime/ (2개 파일)", self.text)
        self.assertIn("- flatbuffers | 25.12.19 | Apache 2.0 | (휠에 라이선스 파일이 없다", self.text, "라이선스 파일이 없는 부품도 표에는 있고 없다는 사실을 적는다")
        self.assertNotIn("certifi", self.text, "묶음에 없는 부품은 표에도 MPL 칸에도 없다")

    def test_the_text_has_no_url_scheme_no_tilde_no_carriage_return_and_is_the_same_for_the_same_input(self):
        self.assertNotIn("http", self.text.lower())
        self.assertNotIn("://", self.text)
        self.assertNotIn("~", self.text)
        self.assertNotIn(chr(13), self.text)
        self.assertTrue(self.text.endswith(chr(10)))
        self.assertEqual(self.text, B.render_notices(PACKAGES, GEOS, COLLECTED))
        self.assertEqual(self.text, B.render_notices(list(reversed(PACKAGES)), GEOS, dict(reversed(list(COLLECTED.items())))), "입력 순서가 달라도 같은 글(재현 빌드)")

    def test_the_source_host_is_only_a_host_name_without_a_scheme_or_a_path(self):
        self.assertEqual(B.GEOS_SOURCE_HOST, "libgeos.org")
        self.assertRegex(B.GEOS_SOURCE_HOST, r"^[a-z0-9.-]+$")

    def test_the_ffmpeg_removal_is_noted_only_when_it_really_happened(self):
        removed = [{"what": "opencv FFmpeg DLL", "path": "_internal/cv2/opencv_videoio_ffmpeg5000_64.dll", "bytes": 1}]
        with_note = B.render_notices(PACKAGES, GEOS, COLLECTED, removed)
        self.assertIn("FFmpeg", with_note)
        self.assertNotIn("FFmpeg", self.text)

    def test_without_any_mpl_part_the_section_says_so_instead_of_staying_empty(self):
        plain = [dict(p, license_metadata="MIT") for p in PACKAGES if p["name"] in ("shapely", "numpy")]
        text = B.render_notices(plain, GEOS, COLLECTED)
        self.assertIn("MPL-2.0 조건의 부품이 없다", text)
        self.assertNotIn("Eigen", text)


class LicenseNotesTest(unittest.TestCase):
    def test_the_notes_say_the_way_is_decided_by_confirmation_030_and_not_pending(self):
        notes = B.license_notes(GEOS)
        self.assertEqual(sorted(notes), ["ffmpeg", "geos", "memo", "mpl2"])
        for key, text in notes.items():
            self.assertNotIn("방식 미정", text, key)
            self.assertNotIn("http", text.lower(), key)
            self.assertNotIn("~", text, key)
        for key in ("memo", "geos", "mpl2"):
            self.assertIn("확인 030 ②", notes[key], key)
        for needle in ("라이선스 전문", "고지문", "소스 안내문", "3.99.9", "libgeos.org", "바꿔 끼울 수 있음", "같은 버전"):
            self.assertIn(needle, notes["geos"], needle)
        self.assertIn("원본 소스 압축 파일은 넣지 않는다", notes["memo"])
        self.assertIn("THIRD_PARTY_NOTICES.txt", notes["memo"])
        self.assertIn("Eigen", notes["mpl2"])


class FileRulesTest(unittest.TestCase):
    def test_license_like_text_files_are_recognised_in_either_folder_style(self):
        for path in ("shapely-2.2.0.dist-info/licenses/LICENSE_GEOS", "onnxruntime/ThirdPartyNotices.txt", "tqdm-4.70.1.dist-info/licenses/LICENCE", "rapidocr-3.10.0.dist-info/licenses/MODEL_LICENSES.md",
                     "cv2/LICENSE-3RD-PARTY.txt", "numpy-2.5.5.dist-info/licenses/numpy/_core/src/common/pythoncapi-compat/COPYING", "omegaconf-2.4.0.dist-info/licenses/ATTRIBUTION/LICENSE-antlr4",
                     "requests-2.34.2.dist-info/licenses/NOTICE", "shapely-2.2.0.dist-info" + chr(92) + "licenses" + chr(92) + "LICENSE_GEOS"):
            self.assertTrue(B.is_license_file(path), path)

    def test_code_binaries_caches_and_unrelated_files_are_not_license_files(self):
        for path in ("_pyinstaller_hooks_contrib/stdhooks/hook-yapf_third_party.py", "pkg/__pycache__/license.cpython-312.pyc", "shapely/_geos.cp312-win_amd64.pyd", "shapely.libs/geos-aaa.dll",
                     "pkg/entry_points.txt", "pkg/top_level.txt", "pkg/license_tools.py", "pkg/METADATA", "pkg/RECORD", "pkg/licenses_index.json"):
            self.assertFalse(B.is_license_file(path), path)

    def test_the_target_drops_the_dist_info_and_licenses_prefix_but_keeps_the_rest_so_names_do_not_collide(self):
        self.assertEqual(B.license_target("shapely-2.2.0.dist-info/licenses/LICENSE_GEOS"), "LICENSE_GEOS")
        self.assertEqual(B.license_target("numpy-2.5.5.dist-info/licenses/numpy/_core/include/numpy/libdivide/LICENSE.txt"), "numpy/_core/include/numpy/libdivide/LICENSE.txt")
        self.assertEqual(B.license_target("cv2/LICENSE.txt"), "cv2/LICENSE.txt")
        self.assertEqual(B.license_target("opencv_python_headless-5.0.0.93.dist-info/LICENSE.txt"), "LICENSE.txt")
        self.assertEqual(B.license_target("onnxruntime/LICENSE"), "onnxruntime/LICENSE")
        self.assertNotEqual(B.license_target("cv2/LICENSE.txt"), B.license_target("opencv_python_headless-5.0.0.93.dist-info/LICENSE.txt"))

    def test_the_geos_license_is_found_by_its_name_or_not_found_at_all(self):
        records = ["shapely-2.2.0.dist-info/licenses/LICENSE.txt", "shapely-2.2.0.dist-info/licenses/LICENSE_GEOS", "shapely/__init__.py"]
        self.assertEqual(B.geos_license_path(records), "shapely-2.2.0.dist-info/licenses/LICENSE_GEOS")
        self.assertEqual(B.geos_license_path([r.replace("LICENSE_GEOS", "license_geos") for r in records]), "shapely-2.2.0.dist-info/licenses/license_geos")
        self.assertIsNone(B.geos_license_path(["shapely-2.2.0.dist-info/licenses/LICENSE.txt", "shapely/LICENSE_GEOS.py", "shapely.libs/geos-aaaa.dll"]))
        self.assertIsNone(B.geos_license_path([]))

    def test_the_required_outputs_are_the_notice_a_licenses_folder_and_the_geos_license(self):
        full = ["ocr_worker.exe", "THIRD_PARTY_NOTICES.txt", "licenses/numpy/LICENSE.txt", "licenses/shapely/LICENSE_GEOS"]
        self.assertEqual((B.NOTICES_NAME, B.LICENSES_DIR), ("THIRD_PARTY_NOTICES.txt", "licenses"))
        self.assertEqual(B.missing_outputs(full), [])
        self.assertEqual(B.missing_outputs(full[:1] + full[2:]), ["THIRD_PARTY_NOTICES.txt"])
        self.assertEqual(B.missing_outputs([p for p in full if not p.startswith("licenses/")]), ["licenses/", "licenses/shapely/LICENSE_GEOS"])
        self.assertEqual(B.missing_outputs([p for p in full if p != "licenses/shapely/LICENSE_GEOS"]), ["licenses/shapely/LICENSE_GEOS"], "licenses 폴더가 있어도 GEOS 전문이 없으면 빠진 것이다")
        self.assertEqual(B.missing_outputs(["licenses/other/LICENSE_GEOS", "THIRD_PARTY_NOTICES.txt"]), ["licenses/shapely/LICENSE_GEOS"], "다른 부품 폴더의 같은 이름 파일은 GEOS 전문이 아니다")
        self.assertEqual(B.missing_outputs([p.replace("/", chr(92)) for p in full]), [], "윈도 경로 글자도 같게 본다")
        self.assertEqual(B.missing_outputs([]), ["THIRD_PARTY_NOTICES.txt", "licenses/", "licenses/shapely/LICENSE_GEOS"])

    def test_the_geos_version_is_read_from_the_installed_shapely_and_never_invented(self):
        with mock.patch.dict(sys.modules, {"shapely": mock.Mock(geos_version_string=" 3.14.1 ", geos_version=(3, 14, 1))}):
            self.assertEqual(B.read_geos_version(), "3.14.1")
        with mock.patch.dict(sys.modules, {"shapely": mock.Mock(geos_version_string=None, geos_version=(3, 14, 1))}):
            self.assertEqual(B.read_geos_version(), "3.14.1")
        with mock.patch.dict(sys.modules, {"shapely": mock.Mock(geos_version_string="", geos_version="x")}):
            self.assertIsNone(B.read_geos_version())
        with mock.patch.dict(sys.modules, {"shapely": None}):                       # 가져오기 자체가 안 되면
            self.assertIsNone(B.read_geos_version())

    def test_the_separate_geos_files_are_the_geos_dlls_only(self):
        with tempfile.TemporaryDirectory() as root:
            dst = make_bundle(root, ("geos-aaaa.dll", "geos_c-bbbb.dll"))
            self.assertEqual(B.geos_dll_files(dst), ["_internal/Shapely.libs/geos-aaaa.dll", "_internal/Shapely.libs/geos_c-bbbb.dll"])


class CollectTest(unittest.TestCase):
    def test_every_bundled_part_gets_its_license_files_copied_and_nothing_else_is_copied(self):
        with tempfile.TemporaryDirectory() as root:
            dists = make_site(root, SITE)
            dst = make_bundle(root)
            collected = B.collect_licenses(dst, PACKAGES, lookup_of(dists))
            self.assertEqual(collected, {"flatbuffers": [], "numpy": ["LICENSE.txt", "numpy/_core/src/highway/LICENSE"], "onnxruntime": ["onnxruntime/LICENSE", "onnxruntime/ThirdPartyNotices.txt"],
                                         "shapely": ["LICENSE.txt", "LICENSE_GEOS", "LICENSE_win32"], "tqdm": ["LICENCE"]})
            files = [path for path in listing(dst) if path.startswith("licenses/")]
            self.assertEqual(files, ["licenses/numpy/LICENSE.txt", "licenses/numpy/numpy/_core/src/highway/LICENSE", "licenses/onnxruntime/onnxruntime/LICENSE", "licenses/onnxruntime/onnxruntime/ThirdPartyNotices.txt",
                                     "licenses/shapely/LICENSE.txt", "licenses/shapely/LICENSE_GEOS", "licenses/shapely/LICENSE_win32", "licenses/tqdm/LICENCE"])
            with open(os.path.join(dst, "licenses", "shapely", "LICENSE_GEOS"), "rb") as handle:
                self.assertEqual(handle.read(), b"TEXT OF shapely shapely-2.2.0.dist-info/licenses/LICENSE_GEOS", "설치된 패키지의 파일을 글자 그대로 복사한다")
            self.assertFalse(os.path.exists(os.path.join(dst, "licenses", "certifi")), "묶음에 없는 부품(certifi)은 모으지 않는다")

    def test_a_missing_geos_license_stops_the_build_instead_of_being_skipped_quietly(self):
        with tempfile.TemporaryDirectory() as root:
            site = dict(SITE, shapely=[r for r in SITE["shapely"] if "LICENSE_GEOS" not in r])
            dists = make_site(root, site)
            dst = make_bundle(root)
            with self.assertRaises(B.BuildError) as caught:
                B.collect_licenses(dst, PACKAGES, lookup_of(dists))
            self.assertIn("LICENSE_GEOS", str(caught.exception))

    def test_a_geos_license_that_is_listed_but_not_on_disk_also_stops_the_build(self):
        with tempfile.TemporaryDirectory() as root:
            dists = make_site(root, SITE)
            os.remove(os.path.join(root, "site-shapely", "shapely-2.2.0.dist-info", "licenses", "LICENSE_GEOS"))
            with self.assertRaises(B.BuildError):
                B.collect_licenses(make_bundle(root), PACKAGES, lookup_of(dists))

    def test_a_bundled_part_that_cannot_be_found_stops_the_build(self):
        with tempfile.TemporaryDirectory() as root:
            dists = make_site(root, {name: files for name, files in SITE.items() if name != "tqdm"})
            with self.assertRaises(B.BuildError) as caught:
                B.collect_licenses(make_bundle(root), PACKAGES, lookup_of(dists))
            self.assertIn("tqdm", str(caught.exception))

    def test_an_unsafe_record_path_is_refused_and_nothing_is_written_outside_the_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            site = dict(SITE, tqdm=["tqdm-4.70.1.dist-info/licenses/../../evil/LICENCE"])
            dists = make_site(root, {name: files for name, files in site.items() if name != "tqdm"})
            dists["tqdm"] = FakeDist(os.path.join(root, "site-tqdm"), site["tqdm"])
            dst = make_bundle(root)
            with self.assertRaises(B.BuildError):
                B.collect_licenses(dst, PACKAGES, lookup_of(dists))
            self.assertFalse(os.path.exists(os.path.join(root, "evil")))
            self.assertFalse(os.path.exists(os.path.join(dst, "evil")))

    def test_files_left_by_an_earlier_run_do_not_stay_in_the_licenses_folder(self):
        with tempfile.TemporaryDirectory() as root:
            dists = make_site(root, SITE)
            dst = make_bundle(root)
            stale = os.path.join(dst, "licenses", "gone", "OLD")
            os.makedirs(os.path.dirname(stale))
            with open(stale, "wb") as handle:
                handle.write(b"old")
            B.collect_licenses(dst, PACKAGES, lookup_of(dists))
            self.assertFalse(os.path.exists(stale))


class WriteOutputsTest(unittest.TestCase):
    def run_outputs(self, root, site=None, version="3.99.9", geos_names=("geos-aaaa.dll", "geos_c-bbbb.dll"), packages=PACKAGES):
        dists = make_site(root, site or SITE)
        dst = make_bundle(root, geos_names)
        geos = B.write_license_outputs(dst, packages, (), lookup_of(dists), lambda: version)
        return dst, geos

    def test_the_licenses_folder_the_notice_and_the_geos_record_are_made(self):
        with tempfile.TemporaryDirectory() as root:
            dst, geos = self.run_outputs(root)
            self.assertEqual(geos, GEOS)
            with open(os.path.join(dst, "THIRD_PARTY_NOTICES.txt"), "rb") as handle:
                raw = handle.read()
            self.assertEqual(raw.decode("utf-8"), B.render_notices(PACKAGES, geos, {"flatbuffers": [], "numpy": ["LICENSE.txt", "numpy/_core/src/highway/LICENSE"],
                                                                                  "onnxruntime": ["onnxruntime/LICENSE", "onnxruntime/ThirdPartyNotices.txt"], "shapely": ["LICENSE.txt", "LICENSE_GEOS", "LICENSE_win32"],
                                                                                  "tqdm": ["LICENCE"]}))
            self.assertNotIn(b"\r", raw, "줄바꿈은 LF 로 쓴다(재현 빌드)")
            self.assertTrue(os.path.isfile(os.path.join(dst, "licenses", "shapely", "LICENSE_GEOS")))

    def test_the_listing_of_the_outputs_has_the_notice_and_the_licenses_folder_and_loses_them_when_removed(self):
        with tempfile.TemporaryDirectory() as root:
            dst, _geos = self.run_outputs(root)
            files = listing(dst)
            self.assertEqual(B.missing_outputs(files), [])
            self.assertIn("THIRD_PARTY_NOTICES.txt", files)
            self.assertIn("licenses/shapely/LICENSE_GEOS", files)
            os.remove(os.path.join(dst, "THIRD_PARTY_NOTICES.txt"))
            self.assertEqual(B.missing_outputs(listing(dst)), ["THIRD_PARTY_NOTICES.txt"])

    def test_it_stops_and_writes_no_notice_when_the_geos_license_is_missing(self):
        with tempfile.TemporaryDirectory() as root:
            site = dict(SITE, shapely=[r for r in SITE["shapely"] if "LICENSE_GEOS" not in r])
            with self.assertRaises(B.BuildError):
                self.run_outputs(root, site)
            self.assertFalse(os.path.exists(os.path.join(root, "dist", "ocr_addon", "THIRD_PARTY_NOTICES.txt")))

    def test_it_stops_when_the_geos_version_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as root:
            for version in (None, "", "   "):
                with self.assertRaises(B.BuildError, msg=repr(version)):
                    self.run_outputs(root, version=version)
            self.assertFalse(os.path.exists(os.path.join(root, "dist", "ocr_addon", "THIRD_PARTY_NOTICES.txt")))

    def test_it_stops_when_there_is_no_separate_geos_file_in_the_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(B.BuildError):
                self.run_outputs(root, geos_names=())
            self.assertFalse(os.path.exists(os.path.join(root, "dist", "ocr_addon", "THIRD_PARTY_NOTICES.txt")))

    def test_it_stops_when_shapely_is_not_in_the_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            without = [dict(p, bundled_in_dist=False) if p["name"] == "shapely" else p for p in PACKAGES]
            with self.assertRaises(B.BuildError) as caught:
                self.run_outputs(root, packages=without)
            self.assertIn("전제와 다르다", str(caught.exception), "다른 방어선(복사 실패)이 아니라 '묶음에 shapely 가 없다' 는 사실로 멈춘다")


SITE_VERSIONS = {"shapely": "2.2.0", "numpy": "2.5.4", "onnxruntime": "1.31.1", "tqdm": "4.70.1"}
SITE_LICENSES = {"shapely": "BSD-3-Clause", "numpy": "BSD-3-Clause", "onnxruntime": "MIT License", "tqdm": "MPL-2.0 AND MIT"}


class InfoStageTest(unittest.TestCase):
    """`make_info` 와 `main` 이 새 단계를 실제로 부른다 — 가짜 설치 폴더와 가짜 휠 표만으로(빌드 없이)."""

    def prepare(self, root, site=None):
        out_dir = os.path.join(root, "out")
        dst = os.path.join(out_dir, "dist", "ocr_addon")
        libs = os.path.join(dst, "_internal", "Shapely.libs")
        os.makedirs(libs)
        for name in ("shapely", "numpy", "onnxruntime", "tqdm"):
            os.makedirs(os.path.join(dst, "_internal", name))
        for name in ("geos-aaaa.dll", "geos_c-bbbb.dll"):
            with open(os.path.join(libs, name), "wb") as handle:
                handle.write(b"DLL")
        with open(os.path.join(dst, "ocr_worker.exe"), "wb") as handle:
            handle.write(b"EXE")
        photolab = os.path.join(root, "photolab")
        os.makedirs(os.path.join(photolab, "stage2"))
        table = {"files": [{"canon": name, "name": name, "file": "%s-1.0-py3-none-any.whl" % name, "version": SITE_VERSIONS[name], "bytes": 10, "sha256": "0" * 64, "license": SITE_LICENSES[name]} for name in sorted(SITE_VERSIONS)]}
        with open(os.path.join(photolab, "stage2", "wheels_table.json"), "w", encoding="utf-8") as handle:
            json.dump(table, handle)
        return out_dir, dst, photolab, lookup_of(make_site(root, site or SITE))

    def run_info(self, root, site=None, version="3.99.9"):
        out_dir, dst, photolab, lookup = self.prepare(root, site)

        def fake_version(name):
            if name in SITE_VERSIONS:
                return SITE_VERSIONS[name]
            raise B.im.PackageNotFoundError(name)

        def fake_metadata(name):
            raise B.im.PackageNotFoundError(name)
        with mock.patch.object(B, "PHOTOLAB", photolab), mock.patch.object(B.im, "distribution", lookup), mock.patch.object(B.im, "version", fake_version), \
                mock.patch.object(B.im, "metadata", fake_metadata), mock.patch.object(B, "read_geos_version", lambda: version), mock.patch.object(B, "log"), warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)                # a 단계 코드가 json.load(open(...)) 로 파일을 닫지 않는 곳이 있다(이번 일과 무관)
            result = B.make_info(out_dir, "t")
        return out_dir, dst, result

    def test_the_info_stage_writes_the_notice_and_licenses_first_and_lists_them_with_their_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            _out, dst, result = self.run_info(root)
            self.assertEqual(result, 0)
            info = json.loads(Path(dst, "OCR_INFO.json").read_text(encoding="utf-8"))
            paths = [entry["path"] for entry in info["files"]]
            self.assertEqual(B.missing_outputs(paths), [])
            self.assertNotIn("OCR_INFO.json", paths)
            self.assertEqual(info["file_count"], len(paths))
            by_path = {entry["path"]: entry for entry in info["files"]}
            notice = Path(dst, "THIRD_PARTY_NOTICES.txt").read_bytes()
            self.assertEqual(by_path["THIRD_PARTY_NOTICES.txt"]["sha256"], hashlib.sha256(notice).hexdigest(), "고지문은 목록을 만들기 전에 이미 있어야 해시가 맞는다")
            self.assertEqual(by_path["THIRD_PARTY_NOTICES.txt"]["bytes"], len(notice))
            self.assertEqual(info["geos"]["version"], "3.99.9")
            self.assertEqual(info["geos"]["license_file"], "licenses/shapely/LICENSE_GEOS")
            self.assertEqual(info["geos"]["dll_files"], ["_internal/Shapely.libs/geos-aaaa.dll", "_internal/Shapely.libs/geos_c-bbbb.dll"])
            self.assertIs(info["geos"]["source_included"], False)
            self.assertEqual(info["license_notes"], B.license_notes(info["geos"]))
            self.assertNotIn("방식 미정", json.dumps(info["license_notes"], ensure_ascii=False))

    def test_a_missing_geos_license_makes_the_info_stage_fail_and_no_info_file_is_written(self):
        with tempfile.TemporaryDirectory() as root:
            site = dict(SITE, shapely=[r for r in SITE["shapely"] if "LICENSE_GEOS" not in r])
            out_dir, dst, photolab, lookup = self.prepare(root, site)
            with mock.patch.object(B, "PHOTOLAB", photolab), mock.patch.object(B.im, "distribution", lookup), mock.patch.object(B.im, "version", lambda name: SITE_VERSIONS[name]), \
                    mock.patch.object(B.im, "metadata", side_effect=B.im.PackageNotFoundError("x")), mock.patch.object(B, "read_geos_version", lambda: "3.99.9"), mock.patch.object(B, "log"), \
                    warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                with self.assertRaises(B.BuildError):
                    B.make_info(out_dir, "t")
            self.assertFalse(os.path.exists(os.path.join(dst, "OCR_INFO.json")))

    def test_the_info_stage_refuses_to_write_when_the_listing_lacks_the_required_outputs(self):
        """고지문·라이선스 전문을 만드는 단계가 (어떤 이유로) 파일을 안 만들었다면 정보 파일을 쓰지 않고 멈춘다 — 산출 목록의 마지막 확인."""
        with tempfile.TemporaryDirectory() as root:
            out_dir, dst, photolab, lookup = self.prepare(root)
            with mock.patch.object(B, "PHOTOLAB", photolab), mock.patch.object(B.im, "distribution", lookup), mock.patch.object(B.im, "version", lambda name: SITE_VERSIONS[name]), \
                    mock.patch.object(B.im, "metadata", side_effect=B.im.PackageNotFoundError("x")), mock.patch.object(B, "write_license_outputs", return_value=dict(GEOS)), mock.patch.object(B, "log"), \
                    warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                with self.assertRaises(B.BuildError) as caught:
                    B.make_info(out_dir, "t")
            self.assertIn("THIRD_PARTY_NOTICES.txt", str(caught.exception))
            self.assertFalse(os.path.exists(os.path.join(dst, "OCR_INFO.json")))

    def test_main_turns_a_build_error_into_a_failure_exit_code_and_a_nonzero_info_into_failure_too(self):
        with tempfile.TemporaryDirectory() as root:
            argv = ["build_ocr_addon.py", "info", "--out-dir", os.path.join(root, "out")]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(B, "make_info", side_effect=B.BuildError("GEOS 없음")), mock.patch.object(B, "log") as log:
                self.assertEqual(B.main(), 1)
            self.assertIn("GEOS 없음", str(log.call_args_list))
            with mock.patch.object(sys, "argv", argv), mock.patch.object(B, "make_info", return_value=1):
                self.assertEqual(B.main(), 1)
            with mock.patch.object(sys, "argv", argv), mock.patch.object(B, "make_info", return_value=0):
                self.assertEqual(B.main(), 0)


class SourceRuleTest(unittest.TestCase):
    """새 코드(라이선스·고지문 단계)는 네트워크도 인터넷 주소도 쓰지 않고 dst 밖에는 쓰지 않는다."""
    NEW_FUNCTIONS = ("is_license_file", "license_target", "geos_license_path", "read_geos_version", "geos_dll_files", "collect_licenses", "render_notices", "license_notes", "missing_outputs", "write_license_outputs")

    def test_the_new_functions_name_no_network_module_and_no_url_scheme_or_tilde(self):
        for name in self.NEW_FUNCTIONS:
            source = inspect.getsource(getattr(B, name))
            for token in ("http", "urllib", "socket", "requests", "ftp:", "~", "subprocess", "os.system"):
                self.assertNotIn(token, source, "%s: %s" % (name, token))

    def test_the_constants_of_the_new_stage_have_no_scheme_or_tilde(self):
        text = BUILD.read_text(encoding="utf-8")
        block = text[text.index("LICENSES_DIR = "):text.index("GEOS_DLL_RE = ")]
        self.assertNotRegex(block, r"https?:|ftp:|~")
        self.assertIsNone(re.search(r"https?://", text), "빌드 스크립트 어디에도 인터넷 주소 스킴이 없다")

    def test_the_only_writes_of_the_new_stage_are_under_the_bundle_folder(self):
        source = inspect.getsource(B.collect_licenses) + inspect.getsource(B.write_license_outputs)
        self.assertNotIn("PHOTOLAB", source)
        self.assertNotIn("STAGEA", source)
        for destination in re.findall(r"os\.path\.join\(([^)]*)\)", source):
            self.assertTrue(destination.split(",")[0].strip() in ("root", "dst", "os.path.dirname(destination)"), destination)


if __name__ == "__main__":
    unittest.main()
