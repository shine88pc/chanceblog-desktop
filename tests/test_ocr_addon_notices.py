"""글자 읽기 추가 도구 빌드(`ocr_addon/build_ocr_addon.py`)의 라이선스 전문 모으기·고지문 생성(운영자 확인 030 ② — GEOS(LGPL-2.1)·MPL-2.0 의무는 라이선스 전문·고지문·소스 안내문을 추가 도구 폴더에 넣는 방식으로 지킨다.
원본 소스 압축 파일은 넣지 않는다 — 새 내려받기 없음). **빌드 없이 도는 순수 함수·가짜 설치 폴더 시험**이라 PyInstaller·PySide6·진짜 패키지가 없어도 CI 에서 돈다.

지키는 것:
  1) 고지문 — GEOS 칸(LGPL-2.1·별도 파일 geos*.dll 이라 바꿔 끼울 수 있음·같은 버전 소스를 공식 배포처에서 받으라는 안내·판은 OCR_INFO.json 의 geos 칸), MPL-2.0 칸(tqdm·onnxruntime 안 Eigen), 묶음에 든 부품만 담은 표,
     인터넷 주소의 스킴·물결표가 없다(받는 곳은 host 글자만).
  2) 라이선스 전문 모으기 — 묶음에 든 부품마다 설치된 분포에서 라이선스·고지문 파일을 licenses/<이름>/ 로 복사하고, GEOS 의 LICENSE_GEOS 를 못 찾으면 **조용히 건너뛰지 않고 빌드를 멈춘다**(판을 못 읽거나 별도 GEOS 파일이 없을 때도).
  3) 산출 목록 — OCR_INFO.json 의 files 에 licenses/ 와 THIRD_PARTY_NOTICES.txt(와 GEOS 라이선스 전문)가 있고, info 단계가 그 파일들을 목록에 넣은 뒤 정보 파일을 쓴다. license_notes 는 '방식 미정' 이 아니라 확인 030 ② 에 따른다는 문구다.
  4) 새 코드는 네트워크·인터넷 주소를 쓰지 않는다(소스 규칙).

[합친 뒤 이식 — D 를 B1 최종 위로 얹을 때] 순수 함수·가짜 설치 폴더 시험(NoticeText·LicenseNotes·FileRules·Collect·WriteOutputs·SourceRule)은 그대로다(불러오는 곳만 D 의 시험 도우미로 — 합친 스크립트가 형제 규칙 모듈을 가져오려고
불러오는 동안 import 경로에 ocr_addon 폴더를 두기 때문에 도우미가 그 경로를 곧 빼 준다). 바뀐 것은 `InfoStageTest` 하나다: B1 의 a 단계 스크립트는 고지 파일을 **info 단계 안에서** 만들었지만, 합친 흐름은 고지 파일 만들기를
**점검 앞의 독립 단계(`notices`)** 로 옮겼다(점검의 금지 이름·키 모양 훑기가 고지 파일도 보고 정보 파일의 목록에 들어가도록 — 확인 030 ② 의 검증 요청). 그래서 같은 네 가지 확인을 새 구조(`write_notices` → `geos.json` 기록 → 점검 →
`make_info`)로 다시 걸었다. 합친 흐름의 전체 연결(점검·산출물 점검과 함께)은 test_ocr_addon_merged_flow.py 가 본다.
"""
import contextlib
import hashlib
import inspect
import io
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
sys.path.insert(0, str(HERE))
import ocr_build_support as support  # noqa: E402

BUILD = ROOT / "ocr_addon" / "build_ocr_addon.py"
B = support.load("build_ocr_addon")
STATE = {"commit": "0123456789abcdef0123456789abcdef01234567", "epoch": 1794873600, "epoch_from": "git commit", "committed_utc": "2026-11-17T00:00:00Z", "clean": True, "dirty_count": 0}

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
# 고지문 [5] 절(N1 의 R5)의 재료 — 저장소의 진짜 잠금 파일과 사전 출처 기록(순수 함수 시험이라 파일을 직접 읽어 넘긴다)
REAL_LOCK = json.loads(support.read("ocr_addon/models.lock.json"))
REAL_PROVENANCE = json.loads(support.read("ocr_addon/data/ppocrv5_korean_dict.provenance.json"))


def real_models():
    return B.model_notice_records(REAL_LOCK, REAL_PROVENANCE)

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
        self.assert_drive_and_absolute_record_paths_are_refused_before_anything_is_written()

    def assert_drive_and_absolute_record_paths_are_refused_before_anything_is_written(self):
        """독립 검증 S 의 SP-8 — 윈도의 os.path.join 은 'C:' 꼴 조각이나 '\\' 로 시작하는 조각을 만나면 앞의 폴더를 버리고 그 드라이브·루트로 가므로(묶음 밖 경로), 드라이브·절대 경로·파일 이름 안의 ':'(NTFS 대체 스트림)를
        가진 기록 경로는 **복사하기 전에** 안전 규칙이 거절해야 한다. 폴더 만들기·복사를 가짜로 바꿔 '거절' 이 그 앞의 규칙에서 났음을 본다 — 규칙이 빠지면 뒤의 복사 실패가 대신 BuildError 를 내서
        겉으로는 같아 보이고, 바꾸지 않으면 규칙이 빠진 코드가 시험 도중 진짜 드라이브에 폴더를 만든다. 가짜 경로에는 실제 사용자 이름이 없다."""
        tqdm_only = [package for package in PACKAGES if package["name"] == "tqdm"]
        backslash = chr(92)
        bad_records = {
            "드라이브와 슬래시": "C:/evil/LICENCE",
            "드라이브만 있는 상대 꼴": "C:evil/LICENCE",
            "다른 드라이브와 역슬래시": "D:" + backslash + "evil" + backslash + "LICENCE",
            "꼬리표 폴더 아래의 드라이브": "tqdm-4.70.1.dist-info/licenses/C:/evil/LICENCE",
            "꼬리표 폴더 아래의 드라이브만": "tqdm-4.70.1.dist-info/licenses/C:evil/LICENCE",
            "파일 이름 안의 콜론(대체 스트림)": "tqdm-4.70.1.dist-info/licenses/LICENCE:stream",
            "슬래시로 시작하는 절대 경로": "/evil/LICENCE",
            "역슬래시로 시작하는 절대 경로": backslash + "evil" + backslash + "LICENCE",
            "겹슬래시(UNC 꼴)": "//server/share/LICENCE",
        }
        for label, record in bad_records.items():
            with self.subTest(case=label, record=record):
                with tempfile.TemporaryDirectory() as root:
                    dist = FakeDist(os.path.join(root, "site-tqdm"), [record])            # 원본 파일은 만들지 않는다 — 규칙이 막으면 파일 시스템에 닿지 않는다
                    dst = make_bundle(root)
                    with mock.patch.object(B.os, "makedirs") as makedirs, mock.patch.object(B.shutil, "copyfile") as copyfile:
                        with self.assertRaises(B.BuildError) as caught:
                            B.collect_licenses(dst, tqdm_only, lookup_of({"tqdm": dist}))
                    self.assertIn("안전하지 않다", str(caught.exception), "복사 실패가 아니라 안전 규칙이 거절했다")
                    makedirs.assert_not_called()
                    copyfile.assert_not_called()
        for label, record in {"평범한 꼬리표 아래 파일": "tqdm-4.70.1.dist-info/licenses/LICENCE", "폴더 안 파일": "tqdm/vendored/NOTICE.txt"}.items():       # 거절이 지나치지 않다 — 안전한 경로는 그대로 복사한다
            with self.subTest(case=label, record=record):
                with tempfile.TemporaryDirectory() as root:
                    dists = make_site(root, {"tqdm": [record]})
                    dst = make_bundle(root)
                    collected = B.collect_licenses(dst, tqdm_only, lookup_of(dists))
                    self.assertEqual(len(collected["tqdm"]), 1)
                    self.assertTrue(os.path.isfile(os.path.join(dst, "licenses", "tqdm", *collected["tqdm"][0].split("/"))))

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
        geos = B.write_license_outputs(dst, packages, (), lookup_of(dists), lambda: version, real_models())
        return dst, geos

    def test_the_licenses_folder_the_notice_and_the_geos_record_are_made(self):
        with tempfile.TemporaryDirectory() as root:
            dst, geos = self.run_outputs(root)
            self.assertEqual(geos, GEOS)
            with open(os.path.join(dst, "THIRD_PARTY_NOTICES.txt"), "rb") as handle:
                raw = handle.read()
            self.assertEqual(raw.decode("utf-8"), B.render_notices(PACKAGES, geos, {"flatbuffers": [], "numpy": ["LICENSE.txt", "numpy/_core/src/highway/LICENSE"],
                                                                                  "onnxruntime": ["onnxruntime/LICENSE", "onnxruntime/ThirdPartyNotices.txt"], "shapely": ["LICENSE.txt", "LICENSE_GEOS", "LICENSE_win32"],
                                                                                  "tqdm": ["LICENCE"]}, (), real_models()))
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
    """`write_notices`(점검 앞의 notices 단계)와 `make_info`·`main` 이 새 단계를 실제로 부른다 — 가짜 설치 폴더와 가짜 부품 표만으로(빌드 없이). 예전 이름은 B1 의 info 단계 안 고지 만들기였다."""

    BUNDLED = {"shapely", "numpy", "onnxruntime", "tqdm"}

    def prepare(self, root, site=None):
        out_dir = os.path.join(root, "out")
        dst = os.path.join(out_dir, "dist", "ocr")
        libs = os.path.join(dst, "_internal", "Shapely.libs")
        os.makedirs(libs)
        for name in ("geos-aaaa.dll", "geos_c-bbbb.dll"):
            with open(os.path.join(libs, name), "wb") as handle:
                handle.write(b"DLL")
        with open(os.path.join(dst, "ocr_worker.exe"), "wb") as handle:
            handle.write(b"EXE")
        with open(os.path.join(out_dir, "check_result.json"), "w", encoding="utf-8") as handle:        # 점검을 통과했다고 치는 기록(점검 자체는 test_ocr_addon_build_check.py·test_ocr_addon_build_flow.py 가 본다)
            json.dump({"ok": True, "problems": [], "pe_files_checked": 3, "selftest": {"ok": True}, "selftest_exit": 0}, handle)
        return out_dir, dst, lookup_of(make_site(root, site or SITE))

    def patches(self, stack, lookup, version="3.99.9"):
        stack.enter_context(mock.patch.object(B.im, "distribution", lookup))
        stack.enter_context(mock.patch.object(B, "bundled_modules", return_value=set(self.BUNDLED)))
        stack.enter_context(mock.patch.object(B, "installed_version", side_effect=lambda name: SITE_VERSIONS.get(name)))
        stack.enter_context(mock.patch.object(B, "pypi_license", side_effect=lambda name: SITE_LICENSES.get(name)))
        stack.enter_context(mock.patch.object(B, "read_geos_version", lambda: version))
        stack.enter_context(mock.patch.object(B, "load_lock", return_value=(REAL_LOCK, B.rules.expected_files(REAL_LOCK))))
        stack.enter_context(mock.patch.object(B, "log"))

    def run_flow(self, root, site=None, version="3.99.9"):
        """notices 단계 -> info 단계(점검은 통과했다고 친다)."""
        out_dir, dst, lookup = self.prepare(root, site)
        with contextlib.ExitStack() as stack:
            self.patches(stack, lookup, version)
            geos = B.write_notices(out_dir, STATE)
            info = B.make_info(out_dir, STATE, "t")
        return out_dir, dst, geos, info

    def test_the_notices_stage_writes_the_notice_and_licenses_first_and_the_info_stage_lists_them_with_their_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            out_dir, dst, geos, result = self.run_flow(root)
            info = json.loads(Path(dst, "OCR_INFO.json").read_text(encoding="utf-8"))
            self.assertEqual(result, info, "make_info 가 돌려준 값과 디스크의 정보 파일이 같다")
            paths = [entry["path"] for entry in info["files"]]
            self.assertEqual(B.missing_outputs(paths), [])
            self.assertNotIn("OCR_INFO.json", paths)
            self.assertNotIn("geos.json", paths, "GEOS 기록은 묶음 밖(out 폴더) 파일이다")
            self.assertEqual(info["file_count"], len(paths))
            by_path = {entry["path"]: entry for entry in info["files"]}
            notice = Path(dst, "THIRD_PARTY_NOTICES.txt").read_bytes()
            self.assertEqual(by_path["THIRD_PARTY_NOTICES.txt"]["sha256"], hashlib.sha256(notice).hexdigest(), "고지문은 목록을 만들기 전에 이미 있어야 해시가 맞는다")
            self.assertEqual(by_path["THIRD_PARTY_NOTICES.txt"]["bytes"], len(notice))
            self.assertEqual(info["geos"]["version"], "3.99.9")
            self.assertEqual(info["geos"]["license_file"], "licenses/shapely/LICENSE_GEOS")
            self.assertEqual(info["geos"]["dll_files"], ["_internal/Shapely.libs/geos-aaaa.dll", "_internal/Shapely.libs/geos_c-bbbb.dll"])
            self.assertIs(info["geos"]["source_included"], False)
            self.assertEqual(info["geos"], geos)
            self.assertEqual(json.loads(Path(out_dir, "geos.json").read_text(encoding="utf-8")), geos, "info 단계가 읽는 기록은 notices 단계가 남긴 것이다")
            self.assertEqual(info["license_notes"], B.license_notes(info["geos"]))
            self.assertNotIn("방식 미정", json.dumps(info["license_notes"], ensure_ascii=False))

    def test_a_missing_geos_license_makes_the_notices_stage_fail_and_no_info_file_is_written(self):
        with tempfile.TemporaryDirectory() as root:
            site = dict(SITE, shapely=[r for r in SITE["shapely"] if "LICENSE_GEOS" not in r])
            out_dir, dst, lookup = self.prepare(root, site)
            with contextlib.ExitStack() as stack, warnings.catch_warnings():
                self.patches(stack, lookup)
                warnings.simplefilter("ignore", ResourceWarning)
                with self.assertRaises(B.BuildError):
                    B.write_notices(out_dir, STATE)
                self.assertFalse(os.path.exists(os.path.join(out_dir, "geos.json")), "멈춘 단계는 GEOS 기록을 남기지 않는다")
                self.assertFalse(os.path.exists(os.path.join(dst, "THIRD_PARTY_NOTICES.txt")))
                with self.assertRaises(B.BuildError):                      # notices 를 건너뛰고 info 로 가는 길도 없다
                    B.make_info(out_dir, STATE, "t")
            self.assertFalse(os.path.exists(os.path.join(dst, "OCR_INFO.json")))

    def test_the_info_stage_refuses_to_write_when_the_listing_lacks_the_required_outputs(self):
        """고지문·라이선스 전문을 만드는 단계가 (어떤 이유로) 파일을 안 만들었다면 정보 파일을 쓰지 않고 멈춘다 — 산출 목록의 마지막 확인."""
        with tempfile.TemporaryDirectory() as root:
            out_dir, dst, lookup = self.prepare(root)
            with contextlib.ExitStack() as stack:
                self.patches(stack, lookup)
                stack.enter_context(mock.patch.object(B, "write_license_outputs", return_value=dict(GEOS)))        # 단계는 끝난 척하지만 파일은 하나도 만들지 않았다
                B.write_notices(out_dir, STATE)
                with self.assertRaises(B.BuildError) as caught:
                    B.make_info(out_dir, STATE, "t")
            self.assertIn("THIRD_PARTY_NOTICES.txt", str(caught.exception))
            self.assertFalse(os.path.exists(os.path.join(dst, "OCR_INFO.json")))

    def test_main_turns_a_build_error_into_a_failure_exit_code_and_a_nonzero_info_into_failure_too(self):
        """B1: 정보 단계의 BuildError 는 0 이 아닌 종료 코드. 합친 흐름: BuildError(notices·info)는 종료 코드 2 와 표준 오류 글 — 점검 실패의 1 과 구분한다. 정보 단계가 정보를 돌려주면 0 이다(B1 의 '0 이 아닌 값을 돌려준 정보 단계' 는 합친 쪽에 없다 — 실패는 예외로만 알린다)."""
        with tempfile.TemporaryDirectory() as root:
            for stage, patched in (("info", "make_info"), ("notices", "write_notices")):
                argv = ["build_ocr_addon.py", stage, "--out-dir", os.path.join(root, "out")]
                os.makedirs(os.path.join(root, "out"), exist_ok=True)
                with open(os.path.join(root, "out", "check_result.json"), "w", encoding="utf-8") as handle:
                    json.dump({"ok": True}, handle)
                with self.subTest(stage=stage):
                    errors = io.StringIO()
                    with mock.patch.object(sys, "argv", argv), mock.patch.object(B, "source_state", return_value=dict(STATE)), mock.patch.object(B, patched, side_effect=B.BuildError("GEOS 없음")), \
                            mock.patch.object(B, "log"), contextlib.redirect_stderr(errors):
                        self.assertEqual(B.main(), 2)
                    self.assertIn("GEOS 없음", errors.getvalue())
                    with mock.patch.object(sys, "argv", argv), mock.patch.object(B, "source_state", return_value=dict(STATE)), mock.patch.object(B, patched, return_value={"name": "x"}), mock.patch.object(B, "log"):
                        self.assertEqual(B.main(), 0)


class SourceRuleTest(unittest.TestCase):
    """새 코드(라이선스·고지문 단계)는 네트워크도 인터넷 주소도 쓰지 않고 dst 밖에는 쓰지 않는다."""
    NEW_FUNCTIONS = ("is_license_file", "license_target", "geos_license_path", "read_geos_version", "geos_dll_files", "collect_licenses", "render_notices", "license_notes", "missing_outputs", "write_license_outputs",
                     "shaped", "read_dict_provenance", "dict_source_facts", "model_notice_records", "notice_field_ok", "check_model_records")

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


class ModelFactsTest(unittest.TestCase):
    """고지문 [5] 절의 재료 — models.lock.json 과 사전 출처 기록에서 모델 2개·글자 사전의 사실만 뽑는다(순수 함수). 빠졌거나 모양이 다르면 조용히 건너뛰지 않고 BuildError(N1 의 R5)."""

    GIVEN = object()                                                              # 넘기지 않았다는 표시(None 도 넘길 수 있는 값이라 따로 둔다)

    def records(self, lock=GIVEN, provenance=GIVEN):
        return B.model_notice_records(REAL_LOCK if lock is self.GIVEN else lock, REAL_PROVENANCE if provenance is self.GIVEN else provenance)

    def test_the_three_records_carry_the_values_of_the_lock_and_the_dictionary_record_in_a_fixed_order(self):
        records = self.records()
        self.assertEqual([item["role"] for item in records], ["det", "rec", "dict"])
        by_key = {entry["key"]: entry for entry in REAL_LOCK["files"]}
        for item in records[:2]:
            entry = by_key[item["file"]]
            self.assertEqual((item["bytes"], item["sha256"], item["repo"], item["commit"], item["source_file"], item["license_tag"]),
                             (entry["bytes"], entry["sha256"], entry["source"]["repo"], entry["source"]["commit"], entry["source"]["path"], entry["license_tag"]))
        dictionary, entry, derived = records[2], by_key["data/ppocrv5_korean_dict.txt"], REAL_PROVENANCE["derived_from"]
        self.assertEqual((dictionary["file"], dictionary["bytes"], dictionary["sha256"]), (entry["key"], entry["bytes"], entry["sha256"]), "크기·SHA-256 은 빌드가 확인하는 잠금 파일의 값이다")
        self.assertEqual((dictionary["repo"], dictionary["commit"], dictionary["source_file"], dictionary["git_blob"], dictionary["entries"], dictionary["license_tag"]),
                         (derived["repo"], derived["commit"], derived["file"], derived["git_blob"], REAL_PROVENANCE["lines"], REAL_PROVENANCE["license_tag"]))
        self.assertEqual([item["repo"] for item in records], ["PaddlePaddle/PP-OCRv5_mobile_det_onnx", "PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx", "PaddlePaddle/korean_PP-OCRv5_mobile_rec"])
        self.assertEqual({item["license_tag"] for item in records}, {"apache-2.0"})
        self.assertTrue(all(item["label"].strip() for item in records))

    def test_the_order_does_not_depend_on_the_order_of_the_lock_lines(self):
        self.assertEqual(self.records(dict(REAL_LOCK, files=list(reversed(REAL_LOCK["files"])))), self.records())

    def test_a_lock_without_a_model_or_with_an_odd_source_or_license_stops_with_a_build_error(self):
        def lock_with(change):
            files = json.loads(json.dumps(REAL_LOCK["files"]))
            change({entry["role"]: entry for entry in files}, files)
            return dict(REAL_LOCK, files=files)
        cases = {
            "검출 칸이 없다": lock_with(lambda by, files: files.remove(by["det"])),
            "출처 종류가 huggingface 가 아니다": lock_with(lambda by, files: by["det"]["source"].update(kind="repo")),
            "커밋이 40자리가 아니다": lock_with(lambda by, files: by["rec"]["source"].update(commit="abc")),
            "저장소 이름 모양이 다르다": lock_with(lambda by, files: by["det"]["source"].update(repo="no slash")),
            "라이선스 표기가 없다": lock_with(lambda by, files: by["det"].pop("license_tag")),
            "라이선스 표기가 빈 글이다": lock_with(lambda by, files: by["rec"].update(license_tag="")),
            "라이선스 표기에 줄바꿈이 있다": lock_with(lambda by, files: by["rec"].update(license_tag="apache-2.0" + chr(10) + "x")),
            "라이선스 표기가 글이 아니다": lock_with(lambda by, files: by["det"].update(license_tag=7)),
            "schema 가 다르다": dict(REAL_LOCK, schema=2),
            "객체가 아니다": ["x"],
        }
        for label, lock in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(B.BuildError):
                    self.records(lock)

    def test_a_dictionary_record_that_is_missing_odd_or_about_another_file_stops_the_build(self):
        def record_with(change):
            record = json.loads(json.dumps(REAL_PROVENANCE))
            change(record)
            return record
        flipped = ("0" if REAL_PROVENANCE["sha256"][0] != "0" else "1") + REAL_PROVENANCE["sha256"][1:]
        cases = {
            "기록이 없다": None,
            "객체가 아니다": ["x"],
            "빈 객체": {},
            "출처 칸이 없다": record_with(lambda r: r.pop("derived_from")),
            "출처 칸이 객체가 아니다": record_with(lambda r: r.update(derived_from="x")),
            "출처 종류가 huggingface 가 아니다": record_with(lambda r: r["derived_from"].update(kind="repo")),
            "저장소 이름이 없다": record_with(lambda r: r["derived_from"].pop("repo")),
            "커밋 모양이 다르다": record_with(lambda r: r["derived_from"].update(commit="abc")),
            "파일 이름이 없다": record_with(lambda r: r["derived_from"].pop("file")),
            "git blob 모양이 다르다": record_with(lambda r: r["derived_from"].update(git_blob="zz")),
            "줄 수가 없다": record_with(lambda r: r.pop("lines")),
            "줄 수가 0 이다": record_with(lambda r: r.update(lines=0)),
            "줄 수가 참거짓이다": record_with(lambda r: r.update(lines=True)),
            "라이선스 표기가 없다": record_with(lambda r: r.pop("license_tag")),
            "라이선스 표기에 줄바꿈이 있다": record_with(lambda r: r.update(license_tag="apache-2.0" + chr(10) + "x")),
            "SHA-256 이 잠금 파일의 사전과 다르다(다른 파일의 기록)": record_with(lambda r: r.update(sha256=flipped)),
            "크기가 잠금 파일의 사전과 다르다(다른 파일의 기록)": record_with(lambda r: r.update(bytes=r["bytes"] + 1)),
        }
        for label, provenance in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(B.BuildError) as caught:
                    self.records(provenance=provenance)
                self.assertIn("사전", str(caught.exception))


class ModelNoticeTextTest(unittest.TestCase):
    """고지문의 [5] 절 — 모델 2개와 글자 사전마다 파일·크기·SHA-256·출처(저장소·커밋·파일)·라이선스 표기를 적고, 확인하지 못한 것은 확인하지 못했다고 적는다. 같은 입력은 같은 바이트다(N1 의 R5)."""

    def setUp(self):
        self.models = real_models()
        self.text = B.render_notices(PACKAGES, GEOS, COLLECTED, (), self.models)
        self.part = self.text.split("[5]")[1]

    def test_section_5_names_each_model_and_the_dictionary_with_file_size_hash_source_commit_and_license_tag(self):
        self.assertEqual(self.text.count("[5]"), 1)
        for item in self.models:
            for needle in (item["label"], item["file"], "%d바이트" % item["bytes"], item["sha256"], item["repo"], item["commit"], "파일 " + item["source_file"], item["license_tag"]):
                self.assertIn(needle, self.part, (item["role"], needle))
        dictionary = self.models[2]
        for needle in (dictionary["git_blob"], "character_dict", "%d개" % dictionary["entries"], "한 줄에 한 글자씩"):
            self.assertIn(needle, self.part, needle)
        self.assertEqual(self.part.count("character_dict"), 1, "사전을 만든 방법 문장은 사전에만 있다")
        self.assertEqual(self.part.count("라이선스 표기: apache-2.0 (그 저장소 카드의 license 태그)"), 3)
        positions = [self.part.index(item["label"]) for item in self.models]
        self.assertEqual(positions, sorted(positions), "글의 차례는 검출 모델 · 인식 모델 · 글자 사전이다")

    def test_it_says_the_license_label_is_only_the_card_tag_and_that_the_original_paddleocr_text_was_not_checked(self):
        for needle in ("license 태그뿐", "확인하지 못했다", "원본 PaddleOCR 의 라이선스 본문", "전용 라이선스 전문 파일은 licenses 폴더에 없다"):
            self.assertIn(needle, self.part, needle)
        self.assertNotIn("확인했다", self.part, "확인하지 못한 것을 확인한 것처럼 쓰지 않는다")

    def test_without_models_there_is_no_section_5_and_every_old_line_is_kept_in_order(self):
        old = B.render_notices(PACKAGES, GEOS, COLLECTED, ())
        self.assertNotIn("[5]", old)
        old_lines, position = old.splitlines(), 0
        for line in self.text.splitlines():
            if position < len(old_lines) and line == old_lines[position]:
                position += 1
        self.assertEqual(position, len(old_lines), "옛 줄이 새 글 안에 같은 차례로 모두 있다")

    def test_the_sections_come_in_order_and_the_closing_line_stays_last(self):
        removed = [{"what": "x", "path": "_internal/cv2/opencv_videoio_ffmpeg500_64.dll", "bytes": 1}]
        text = B.render_notices(PACKAGES, GEOS, COLLECTED, removed, self.models)
        marks = [text.index(mark) for mark in ("[1]", "[2]", "[3]", "[4]", "[5]")]
        self.assertEqual(marks, sorted(marks))
        closing = "그 밖의 부품(MIT·BSD·Apache-2.0 등)의 고지 조건은 licenses 폴더의 라이선스 전문 파일로 지킨다."
        self.assertTrue(text.rstrip().endswith(closing))
        self.assertLess(text.index("[5]"), text.index(closing))

    def test_the_same_input_gives_the_same_bytes_whatever_the_order_of_the_records(self):
        again = B.render_notices(PACKAGES, GEOS, COLLECTED, (), list(reversed(self.models)))
        self.assertEqual(again.encode("utf-8"), self.text.encode("utf-8"))
        self.assertEqual(B.render_notices(PACKAGES, GEOS, COLLECTED, (), self.models).encode("utf-8"), self.text.encode("utf-8"))
        self.assertNotIn(chr(13), self.text)
        self.assertTrue(self.text.endswith(chr(10)))

    def test_the_whole_text_has_no_scheme_no_tilde_and_passes_the_key_shape_scan_and_the_name_rules(self):
        self.assertNotIn("http", self.text.lower())
        self.assertNotIn("://", self.text)
        self.assertNotIn(chr(0x7E), self.text)
        self.assertEqual(B.rules.key_shape_problems([("THIRD_PARTY_NOTICES.txt", self.text)]), [], "R2 키 모양 훑기가 새 글(해시·커밋 포함)도 통과한다")
        self.assertFalse(B.import_packaging().pc.forbidden_name("THIRD_PARTY_NOTICES.txt"))

    def test_a_record_with_an_unknown_role_stops_instead_of_being_written_quietly(self):
        for odd in ([dict(self.models[0], role="other")], ["not a record"]):
            with self.subTest(odd=odd):
                with self.assertRaises(B.BuildError):
                    B.render_notices(PACKAGES, GEOS, COLLECTED, (), odd)


class GeosSwapNoteTest(unittest.TestCase):
    """[2] 절의 '바꿔 끼운 뒤' 한 줄(N1 의 R6) — GEOS 파일을 바꾸면 정보 파일의 그 항목도 고쳐야 앱이 받아들인다. 말이 사실인지 앱 쪽 진짜 확인으로도 본다."""

    def test_section_2_tells_that_the_info_entry_must_be_fixed_when_the_geos_file_is_swapped(self):
        renders = (("모델 칸 없이", lambda: B.render_notices(PACKAGES, GEOS, COLLECTED, ())),                                  # 옛 호출 모양 — 새 함수가 없는 옛 코드에서도 이 칸은 글 비교로 빨개진다
                   ("모델 칸과 함께", lambda: B.render_notices(PACKAGES, GEOS, COLLECTED, (), real_models())))
        for label, render in renders:
            with self.subTest(case=label):
                part = render().split("[2]")[1].split("[3]")[0]
                for needle in ("GEOS 파일을 바꾸면", "OCR_INFO.json 의 files 목록", "path 가 그 파일인 항목", "bytes(크기)", "sha256(SHA-256)", "새 파일에 맞게 고쳐야", "받아들인다",
                               "크기·SHA-256 이 다른 파일이 하나라도 있으면", "쓰지 않는다"):
                    self.assertIn(needle, part, needle)

    def test_the_claim_is_true_for_the_apps_own_check(self):
        sys.path.insert(0, str(ROOT / "src"))
        try:
            from chanceblog_desktop.service import ocr_addon as app_side
        finally:
            sys.path.remove(str(ROOT / "src"))
        models = {"models/det/inference.onnx": b"det-bytes", "models/rec/inference.onnx": b"rec-bytes", "data/ppocrv5_korean_dict.txt": b"dict-bytes"}
        dll = "_internal/Shapely.libs/geos-aaaa.dll"
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "ocr"
            files = dict(models, **{"ocr_worker.exe": b"EXE", dll: b"GEOS-OLD"})
            for name, data in files.items():
                path = folder / Path(*name.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

            def write_info():
                listed = [{"path": name, "bytes": len((folder / Path(*name.split("/"))).read_bytes()), "sha256": hashlib.sha256((folder / Path(*name.split("/"))).read_bytes()).hexdigest()} for name in sorted(files)]
                info = {"name": "ocr_addon", "proto": app_side.PROTO, "packages": [], "files": listed,
                        "models_dict": {key: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for key, data in models.items()}}
                (folder / "OCR_INFO.json").write_text(json.dumps(info), encoding="utf-8")
                return info

            embedded = {key: (len(data), hashlib.sha256(data).hexdigest()) for key, data in models.items()}
            write_info()
            with mock.patch.object(app_side, "EMBEDDED_FILES", embedded):
                self.assertEqual(app_side.verify(str(folder)).state, "ok", "처음 묶음은 앱이 받아들인다")
                (folder / Path(*dll.split("/"))).write_bytes(b"GEOS-A-NEWER-BUILD")
                swapped = app_side.verify(str(folder))
                self.assertEqual((swapped.state, swapped.problems), ("invalid", ("size",)), "파일만 바꾸면(정보 파일은 그대로) 앱이 거절한다")
                write_info()                                                              # 정보 파일의 그 항목(크기·SHA-256)을 새 파일에 맞게 고쳤다
                self.assertEqual(app_side.verify(str(folder)).state, "ok", "그 항목을 고치면 앱이 받아들인다")
                (folder / Path(*dll.split("/"))).write_bytes(b"GEOS-B-NEWER-BUILD")      # 크기는 같고 내용만 다른 파일
                same_size = app_side.verify(str(folder))
                self.assertEqual((same_size.state, same_size.problems), ("invalid", ("hash",)))


class ModelNoticeStageTest(unittest.TestCase):
    """notices 단계(`write_notices`)가 고지문 [5] 절을 쓰고, 재료(잠금 파일·사전 출처 기록)를 못 만들면 아무것도 쓰기 전에 멈춘다 — 빌드 없이 가짜 설치 폴더로(N1 의 R5)."""

    BUNDLED = {"shapely", "numpy", "onnxruntime", "tqdm"}

    def prepare(self, root):
        out_dir = os.path.join(root, "out")
        dst = os.path.join(out_dir, "dist", "ocr")
        libs = os.path.join(dst, "_internal", "Shapely.libs")
        os.makedirs(libs)
        for name in ("geos-aaaa.dll", "geos_c-bbbb.dll"):
            with open(os.path.join(libs, name), "wb") as handle:
                handle.write(b"DLL")
        return out_dir, dst, lookup_of(make_site(root, SITE))

    @contextlib.contextmanager
    def environment(self, lookup, lock=None, **replaced):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(B.im, "distribution", lookup))
            stack.enter_context(mock.patch.object(B, "bundled_modules", return_value=set(self.BUNDLED)))
            stack.enter_context(mock.patch.object(B, "installed_version", side_effect=lambda name: SITE_VERSIONS.get(name)))
            stack.enter_context(mock.patch.object(B, "pypi_license", side_effect=lambda name: SITE_LICENSES.get(name)))
            stack.enter_context(mock.patch.object(B, "read_geos_version", lambda: "3.99.9"))
            stack.enter_context(mock.patch.object(B, "load_lock", return_value=(REAL_LOCK if lock is None else lock, {})))
            stack.enter_context(mock.patch.object(B, "log"))
            for name, value in replaced.items():
                stack.enter_context(mock.patch.object(B, name, value))
            yield

    def test_the_stage_writes_section_5_with_the_facts_of_the_lock_and_the_dictionary_record(self):
        with tempfile.TemporaryDirectory() as root:
            out_dir, dst, lookup = self.prepare(root)
            with self.environment(lookup):
                B.write_notices(out_dir, STATE)
            text = Path(dst, "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
            self.assertFalse([path for path in listing(dst) if "provenance" in path], "사전 출처 기록은 읽기만 하고 묶음에 복사하지 않는다")
        part = text.split("[5]")[1]
        for item in real_models():
            for needle in (item["file"], item["sha256"], item["repo"], item["commit"], item["license_tag"]):
                self.assertIn(needle, part, needle)
        self.assertIn("확인하지 못했다", part)

    def test_the_section_in_the_notice_the_stage_writes_has_the_exact_shape_of_the_facts(self):
        """SR1 — 단계가 파일로 쓴 고지문의 [5] 절도 줄 단위 모양·허용 문장 목록·1차 최종 빌드의 글과 같다."""
        with tempfile.TemporaryDirectory() as root:
            out_dir, dst, lookup = self.prepare(root)
            with self.environment(lookup):
                B.write_notices(out_dir, STATE)
            text = Path(dst, "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
        lines = section_lines(text)
        self.assertEqual(section_problems(lines, expected_section_facts()), [])
        self.assertEqual(tuple(lines), GOLDEN_SECTION)

    def test_two_runs_of_the_stage_write_the_same_notice_bytes(self):
        written = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as root:
                out_dir, dst, lookup = self.prepare(root)
                with self.environment(lookup):
                    B.write_notices(out_dir, STATE)
                written.append(Path(dst, "THIRD_PARTY_NOTICES.txt").read_bytes())
        self.assertEqual(written[0], written[1])
        self.assertIn("[5]".encode("ascii"), written[0])

    def test_when_the_facts_cannot_be_made_the_stage_stops_and_writes_nothing(self):
        without_rec = dict(REAL_LOCK, files=[entry for entry in REAL_LOCK["files"] if entry["role"] != "rec"])
        other_file = dict(REAL_PROVENANCE, sha256="0" * 64)
        with tempfile.TemporaryDirectory() as empty_folder:
            cases = {"잠금 파일에 인식 모델 칸이 없다": dict(lock=without_rec),
                     "사전 출처 기록 파일이 없다": dict(DATA_DIR=empty_folder),
                     "사전 출처 기록이 다른 파일의 것이다": dict(read_dict_provenance=lambda: other_file)}
            for label, replaced in cases.items():
                with self.subTest(case=label), tempfile.TemporaryDirectory() as root:
                    out_dir, dst, lookup = self.prepare(root)
                    with self.environment(lookup, **replaced):
                        with self.assertRaises(B.BuildError):
                            B.write_notices(out_dir, STATE)
                    self.assertEqual(listing(dst), ["_internal/Shapely.libs/geos-aaaa.dll", "_internal/Shapely.libs/geos_c-bbbb.dll"], "아무것도 쓰기 전에 멈췄다")
                    self.assertFalse(os.path.exists(os.path.join(out_dir, "geos.json")))

    def test_the_writer_refuses_a_missing_or_partial_model_record_and_writes_nothing(self):
        models = real_models()
        for label, given in (("없음", None), ("빈 목록", []), ("검출만", models[:1]), ("인식을 뺀 둘", [models[0], models[2]]), ("같은 칸 둘", [models[0], models[0], models[2]]), ("글이 아닌 칸", ["x", "y", "z"]), ("글", "abc")):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as root:
                dists = make_site(root, SITE)
                dst = make_bundle(root)
                with self.assertRaises(B.BuildError):
                    B.write_license_outputs(dst, PACKAGES, (), lookup_of(dists), lambda: "3.99.9", given)
                self.assertFalse(os.path.exists(os.path.join(dst, "THIRD_PARTY_NOTICES.txt")))
                self.assertFalse(os.path.exists(os.path.join(dst, "licenses")))

    def test_the_provenance_reader_reads_the_repository_record_and_stops_on_a_missing_or_odd_file(self):
        self.assertEqual(B.read_dict_provenance(), REAL_PROVENANCE)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(B, "DATA_DIR", folder):
            with self.assertRaises(B.BuildError):
                B.read_dict_provenance()                                                 # 파일이 없다
            for broken in (b"{not json", bytes([0xFF, 0xFE, 0x00])):                     # JSON 이 아니다 · UTF-8 이 아니다
                Path(folder, B.DICT_PROVENANCE).write_bytes(broken)
                with self.assertRaises(B.BuildError):
                    B.read_dict_provenance()
            Path(folder, B.DICT_PROVENANCE).write_bytes(b"[]")                           # 읽히지만 객체가 아니다 — 사실 뽑기가 거절한다
            with self.assertRaises(B.BuildError):
                B.model_notice_records(REAL_LOCK, B.read_dict_provenance())


# ---- N1 2차 라운드(독립 검증 S 의 SR1·SR2) — [5] 절을 줄 단위 모양과 허용 문장 목록으로 견주고, 값의 모양을 한 곳에서 정해 마지막으로 다시 보며, 정상 값은 한 글자도 안 바뀐다는 것을 못박는다 ----
SECTION_HEADER = "[5] 모델과 글자 사전 — 이름·출처·라이선스 표기 (빌드가 소스의 models.lock.json 과 사전 출처 기록에서 그대로 옮긴 값)"
SECTION_CLOSING = ("- 라이선스 표기의 근거는 위 저장소 카드의 license 태그뿐이다(카드 본문은 사실상 비어 있다). 원본 PaddleOCR 의 라이선스 본문은 확인하지 못했다.",
                   "- 이 모델·사전 전용 라이선스 전문 파일은 licenses 폴더에 없다(licenses 폴더의 파일은 파이썬 부품이 자기 패키지에 넣어 둔 것을 모은 것이다).")
ITEM_RE = re.compile(r"^- ([^:]+): 파일 ([^ ]+) [(]([0-9]+)바이트, SHA-256 ([0-9a-f]{64})[)]$")
ORIGIN_RE = re.compile(r"^  출처: Hugging Face 저장소 ([A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*) · 커밋 ([0-9a-f]{40}) · 파일 ([A-Za-z0-9._/-]+?)(?:[(]git blob ([0-9a-f]{40})[)])?$")
METHOD_RE = re.compile(r"^  만든 방법: 그 파일의 character_dict 목록 ([0-9]+)개를 순서·내용 그대로 한 줄에 한 글자씩 옮겨 적었다[.]$")
LICENSE_LINE_RE = re.compile(r"^  라이선스 표기: ([A-Za-z0-9][A-Za-z0-9.+-]*) [(]그 저장소 카드의 license 태그[)]$")
HEX40 = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
HEX64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
BIG_DIGITS = re.compile(r"(?<![0-9A-Za-z])[0-9]{4,}(?![0-9A-Za-z])")
# 값 모양 점검을 넣기 전(1차 최종 빌드 8c9f0b9)에 진짜 묶음의 고지문에 실제로 들어간 [5] 절 — 정상 값에서는 출력이 한 글자도 안 바뀐다는 기준(바이트 동일 시험)
GOLDEN_SECTION = (
    "[5] 모델과 글자 사전 — 이름·출처·라이선스 표기 (빌드가 소스의 models.lock.json 과 사전 출처 기록에서 그대로 옮긴 값)",
    "- 글자 위치를 찾는 모델(PP-OCRv5 검출): 파일 models/det/inference.onnx (4826518바이트, SHA-256 a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d)",
    "  출처: Hugging Face 저장소 PaddlePaddle/PP-OCRv5_mobile_det_onnx · 커밋 e6f4fa85f00e168c862bc462aebca69eef9b3d3d · 파일 inference.onnx",
    "  라이선스 표기: apache-2.0 (그 저장소 카드의 license 태그)",
    "- 글자를 읽는 모델(PP-OCRv5 한국어 인식): 파일 models/rec/inference.onnx (13418787바이트, SHA-256 92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08)",
    "  출처: Hugging Face 저장소 PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx · 커밋 5c6f574b8e2230adf4287b33e736d71b9fabd28e · 파일 inference.onnx",
    "  라이선스 표기: apache-2.0 (그 저장소 카드의 license 태그)",
    "- 글자 사전(한국어 인식 모델이 쓰는 글자 목록): 파일 data/ppocrv5_korean_dict.txt (47451바이트, SHA-256 a88071c68c01707489baa79ebe0405b7beb5cca229f4fc94cc3ef992328802d7)",
    "  출처: Hugging Face 저장소 PaddlePaddle/korean_PP-OCRv5_mobile_rec · 커밋 c02ecaf1f22bfd1c618cce154fd19185b47e663a · 파일 inference.yml(git blob ba8f60f36464f8444b71301062ec6bf4f7b2d1e0)",
    "  만든 방법: 그 파일의 character_dict 목록 11945개를 순서·내용 그대로 한 줄에 한 글자씩 옮겨 적었다.",
    "  라이선스 표기: apache-2.0 (그 저장소 카드의 license 태그)",
    "- 라이선스 표기의 근거는 위 저장소 카드의 license 태그뿐이다(카드 본문은 사실상 비어 있다). 원본 PaddleOCR 의 라이선스 본문은 확인하지 못했다.",
    "- 이 모델·사전 전용 라이선스 전문 파일은 licenses 폴더에 없다(licenses 폴더의 파일은 파이썬 부품이 자기 패키지에 넣어 둔 것을 모은 것이다).",
)


def section_lines(text):
    """고지문 글에서 [5] 절의 줄들(머리 줄부터 첫 빈 줄 앞까지)."""
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("[5] "))
    end = next((index for index in range(start + 1, len(lines)) if not lines[index].strip()), len(lines))
    return lines[start:end]


def expected_section_facts():
    """진짜 잠금 파일·사전 출처 기록을 시험이 따로 읽어 만든 기대값 — 고지문을 만드는 코드(model_notice_records)를 거치지 않는다."""
    lock = json.loads(support.read("ocr_addon/models.lock.json"))
    provenance = json.loads(support.read("ocr_addon/data/ppocrv5_korean_dict.provenance.json"))
    by_key = {entry["key"]: entry for entry in lock["files"]}
    derived = provenance["derived_from"]
    facts = []
    for label, key in (("글자 위치를 찾는 모델(PP-OCRv5 검출)", "models/det/inference.onnx"), ("글자를 읽는 모델(PP-OCRv5 한국어 인식)", "models/rec/inference.onnx")):
        entry = by_key[key]
        facts.append({"label": label, "file": key, "bytes": str(entry["bytes"]), "sha": entry["sha256"], "repo": entry["source"]["repo"], "commit": entry["source"]["commit"],
                      "origin_file": entry["source"]["path"], "blob": None, "tag": entry["license_tag"], "entries": None})
    dictionary = by_key["data/ppocrv5_korean_dict.txt"]
    facts.append({"label": "글자 사전(한국어 인식 모델이 쓰는 글자 목록)", "file": dictionary["key"], "bytes": str(dictionary["bytes"]), "sha": dictionary["sha256"], "repo": derived["repo"], "commit": derived["commit"],
                  "origin_file": derived["file"], "blob": derived["git_blob"], "tag": provenance["license_tag"], "entries": str(provenance["lines"])})
    return facts


def section_problems(lines, facts):
    """[5] 절의 줄 목록을 줄 단위 정규식과 허용 문장 목록으로 견준다 -> 문제 글 목록(없으면 빈 목록). 칸마다 값이 기대값과 같아야 하고, 허용 목록 밖의 줄·40자리·64자리 16진수·네 자리 이상 숫자가 끼어 있으면 문제다."""
    problems = []
    if not lines or lines[0] != SECTION_HEADER:
        problems.append("머리 줄이 다르다")
    cursor = 1
    for want in facts:
        block = 4 if want["entries"] else 3
        chunk = lines[cursor:cursor + block]
        cursor += block
        if len(chunk) != block:
            problems.append("줄이 모자란다: " + want["label"])
            break
        found = ITEM_RE.match(chunk[0])
        if not found or (found[1], found[2], found[3], found[4]) != (want["label"], want["file"], want["bytes"], want["sha"]):
            problems.append("항목 줄이 다르다: " + chunk[0][:70])
        found = ORIGIN_RE.match(chunk[1])
        if not found or (found[1], found[2], found[3], found[4]) != (want["repo"], want["commit"], want["origin_file"], want["blob"]):
            problems.append("출처 줄이 다르다: " + chunk[1][:70])
        if want["entries"]:
            found = METHOD_RE.match(chunk[2])
            if not found or found[1] != want["entries"]:
                problems.append("만든 방법 줄이 다르다")
        found = LICENSE_LINE_RE.match(chunk[-1])
        if not found or found[1] != want["tag"]:
            problems.append("라이선스 표기 줄이 다르다")
    if tuple(lines[cursor:]) != SECTION_CLOSING:
        problems.append("끝 문장이 허용 목록과 다르다(%d줄)" % len(lines[cursor:]))
    text = chr(10).join(lines)
    if sorted(HEX40.findall(text)) != sorted([item["commit"] for item in facts] + [item["blob"] for item in facts if item["blob"]]):
        problems.append("40자리 16진수가 기대한 커밋·git blob 과 다르다")
    if sorted(HEX64.findall(text)) != sorted(item["sha"] for item in facts):
        problems.append("64자리 16진수가 기대한 SHA-256 과 다르다")
    if sorted(BIG_DIGITS.findall(HEX64.sub(" ", HEX40.sub(" ", text)))) != sorted([item["bytes"] for item in facts] + [item["entries"] for item in facts if item["entries"]]):
        problems.append("네 자리 이상 숫자가 기대한 크기·줄 수와 다르다")
    return problems


def lock_changed(role, field, value):
    """진짜 잠금 파일의 사본에서 role('det'·'rec') 칸의 값 하나만 바꾼다 — field 가 repo·commit·path 면 source 안의 값, 아니면 칸 자체의 값(sha256·license_tag)."""
    files = json.loads(json.dumps(REAL_LOCK["files"]))
    entry = next(item for item in files if item["role"] == role)
    if field in ("repo", "commit", "path"):
        entry["source"][field] = value
    else:
        entry[field] = value
    return dict(REAL_LOCK, files=files)


def provenance_changed(field, value):
    """진짜 사전 출처 기록의 사본에서 값 하나만 바꾼다 — field 가 repo·commit·file·git_blob 이면 derived_from 안의 값, 아니면 기록 자체의 값(license_tag·lines)."""
    record = json.loads(json.dumps(REAL_PROVENANCE))
    if field in ("repo", "commit", "file", "git_blob"):
        record["derived_from"][field] = value
    else:
        record[field] = value
    return record


class ModelSectionShapeTest(unittest.TestCase):
    """SR1 — [5] 절을 줄 단위 정규식과 허용 문장 목록으로 견준다: 예상 밖의 줄이나 값이 끼거나 저장소·커밋 같은 값이 서로 바뀌면 빨강. '사실만 적는다' 를 낱말 찾기(assertIn)가 아니라 모양 전체로 못박는다."""

    def rendered(self):
        return B.render_notices(PACKAGES, GEOS, COLLECTED, (), real_models())

    def test_the_section_made_from_the_real_lock_and_provenance_has_exactly_the_expected_lines_and_values(self):
        lines = section_lines(self.rendered())
        self.assertEqual(len(lines), 1 + 3 + 3 + 4 + 2, "머리 한 줄 + 검출 3 + 인식 3 + 사전 4 + 끝 문장 둘")
        self.assertEqual(section_problems(lines, expected_section_facts()), [])

    def test_the_checker_catches_an_extra_line_a_changed_sentence_swapped_or_altered_values_and_a_missing_line(self):
        facts, lines = expected_section_facts(), section_lines(self.rendered())
        self.assertEqual(section_problems(lines, facts), [])
        flipped = ("0" if facts[0]["sha"][0] != "0" else "1") + facts[0]["sha"][1:]
        cases = {
            "머리 바로 뒤에 확인 안 된 줄 하나": lambda new: new.insert(1, "- 라이선스: Apache-2.0 (확인됨)"),
            "끝 문장의 낱말 하나를 바꿈": lambda new: new.__setitem__(11, new[11].replace("(카드 본문은 사실상 비어 있다)", "(카드 본문에 Apache-2.0 전문이 있다)")),
            "검출 모델의 저장소와 커밋 값을 서로 맞바꿈": lambda new: new.__setitem__(2, "  출처: Hugging Face 저장소 %s · 커밋 %s · 파일 %s" % (facts[0]["commit"], facts[0]["repo"], facts[0]["origin_file"])),
            "항목 줄의 SHA-256 한 글자": lambda new: new.__setitem__(1, new[1].replace(facts[0]["sha"], flipped)),
            "항목 줄의 크기": lambda new: new.__setitem__(4, new[4].replace(facts[1]["bytes"] + "바이트", str(int(facts[1]["bytes"]) + 1) + "바이트")),
            "라이선스 표기를 다른 값으로": lambda new: new.__setitem__(3, new[3].replace(facts[0]["tag"], "MIT")),
            "사전 줄 수를 바꿈": lambda new: new.__setitem__(9, new[9].replace(facts[2]["entries"], "11946")),
            "끝에 줄 하나 더": lambda new: new.append("- 이 모델은 법적으로 문제가 없다."),
            "줄 하나 빠짐": lambda new: new.pop(5),
            "허용 밖의 40자리 값이 한 줄에 더 끼어듦": lambda new: new.__setitem__(1, new[1] + " " + "a" * 40),
            "다른 모델의 해시가 항목 줄에": lambda new: new.__setitem__(1, new[1].replace(facts[0]["sha"], facts[1]["sha"])),
            "인식 모델의 저장소 이름만 바꿈": lambda new: new.__setitem__(5, new[5].replace(facts[1]["repo"], "PaddlePaddle/other_repo")),
            "머리 줄 문구": lambda new: new.__setitem__(0, new[0].replace("그대로 옮긴 값", "확인한 값")),
        }
        for label, change in cases.items():
            with self.subTest(case=label):
                new = list(lines)
                change(new)
                self.assertNotEqual(section_problems(new, facts), [], label)


class ModelValueShapeTest(unittest.TestCase):
    """SR2 — 고지문 [5] 절에 들어가는 값은 한 줄·공백 없음·길이 상한이 있는 정해진 모양이어야 하고(잠금 쪽·사전 출처 기록 쪽이 같은 문), 글이 되기 전 마지막으로 한 번 더 본다. 정상 값은 한 글자도 안 바뀐다."""

    def hostile(self):
        return {"줄바꿈": "x" + chr(10) + "[6] injected section", "캐리지 리턴": "x" + chr(13) + "y", "공백": "x y", "끝 공백": "x ", "탭": "x" + chr(9) + "y", "마크다운 링크": "[x](y)",
                "HTML": "<script>alert(1)</script>", "백틱": "`x`", "전각 글자": chr(0xFF21) + "BC", "제로폭 글자": "a" + chr(0x200B) + "b", "NUL": "a" + chr(0) + "b", "빈 글": ""}

    REPO_200 = "a" * 99 + "/" + "b" * 100
    REPO_201 = "a" * 100 + "/" + "b" * 100
    BAD_REPOS = {"201글자": REPO_201, "10만 글자": "a" * 100000 + "/b", "슬래시 없음": "nodivider"}
    BAD_COMMITS = {"39자리": "a" * 39, "41자리": "a" * 41, "대문자": "A" * 40, "16진수 아님": "g" * 40}
    BAD_FILES = {"점 점 마디": "../../x", "중간의 점 점 마디": "a/../b", "끝의 점 점 마디": "a/..", "점 마디": "./x", "중간의 점 마디": "a/./b", "절대 경로": "/etc/x", "역슬래시": "a" + chr(92) + "b", "끝 슬래시": "a/b/", "201글자": "a" * 201}
    BAD_TAGS = {"41글자": "a" * 41, "앞 하이픈": "-apache", "안의 공백": "apache 2"}

    def test_a_dangerous_value_in_the_lock_stops_the_build(self):
        extras = {"repo": self.BAD_REPOS, "commit": self.BAD_COMMITS, "path": self.BAD_FILES, "sha256": {"63자리": "a" * 63, "65자리": "a" * 65, "대문자": "A" * 64}, "license_tag": self.BAD_TAGS}
        for role in ("det", "rec"):
            for field, more in extras.items():
                for name, value in list(self.hostile().items()) + list(more.items()):
                    with self.subTest(role=role, field=field, value=name):
                        with self.assertRaises(B.BuildError):
                            B.model_notice_records(lock_changed(role, field, value), REAL_PROVENANCE)

    def test_a_dangerous_value_in_the_dictionary_provenance_stops_the_build_and_names_the_dictionary(self):
        extras = {"repo": self.BAD_REPOS, "commit": self.BAD_COMMITS, "git_blob": self.BAD_COMMITS, "file": self.BAD_FILES, "license_tag": self.BAD_TAGS,
                  "lines": {"참": True, "0": 0, "음수": -1, "너무 큼": 10 ** 12, "글": "5", "소수": 5.0, "없음": None}}
        for field, more in extras.items():
            for name, value in list(self.hostile().items()) + list(more.items()):
                with self.subTest(field=field, value=name):
                    with self.assertRaises(B.BuildError) as caught:
                        B.model_notice_records(REAL_LOCK, provenance_changed(field, value))
                    self.assertIn("사전", str(caught.exception))

    def test_a_lock_license_tag_problem_names_the_lock_file_so_the_cause_stays_clear(self):
        """잠금 파일 쪽 라이선스 표기 문제는 어느 파일의 문제인지 말하는 글로 멈춘다 — 마지막 점검(check_model_records)의 일반 글에만 기대지 않는다."""
        bad = dict(self.hostile(), **self.BAD_TAGS)
        for role in ("det", "rec"):
            for name, value in bad.items():
                with self.subTest(role=role, value=name):
                    with self.assertRaises(B.BuildError) as caught:
                        B.model_notice_records(lock_changed(role, "license_tag", value), REAL_PROVENANCE)
                    self.assertIn("models.lock.json", str(caught.exception))
        files = json.loads(json.dumps(REAL_LOCK["files"]))
        next(item for item in files if item["role"] == "det").pop("license_tag")
        with self.assertRaises(B.BuildError) as caught:
            B.model_notice_records(dict(REAL_LOCK, files=files), REAL_PROVENANCE)
        self.assertIn("models.lock.json", str(caught.exception), "표기 칸이 아예 없을 때도")

    def test_the_dictionary_file_shape_is_as_strict_as_the_locks_path_about_dot_segments(self):
        for name in ("점 점 마디", "중간의 점 점 마디", "끝의 점 점 마디", "점 마디", "중간의 점 마디"):
            value = self.BAD_FILES[name]
            with self.subTest(value=name):
                with self.assertRaises(B.BuildError):
                    B.model_notice_records(lock_changed("det", "path", value), REAL_PROVENANCE)
                with self.assertRaises(B.BuildError):
                    B.model_notice_records(REAL_LOCK, provenance_changed("file", value))

    def test_the_limit_is_exactly_two_hundred_for_a_repo_and_a_file_path(self):
        self.assertEqual(len(self.REPO_200), 200)
        self.assertEqual(B.model_notice_records(lock_changed("det", "repo", self.REPO_200), REAL_PROVENANCE)[0]["repo"], self.REPO_200)
        self.assertEqual(B.model_notice_records(REAL_LOCK, provenance_changed("repo", self.REPO_200))[2]["repo"], self.REPO_200)
        self.assertEqual(B.model_notice_records(REAL_LOCK, provenance_changed("file", "a" * 200))[2]["source_file"], "a" * 200)
        self.assertEqual(B.model_notice_records(lock_changed("rec", "path", "a" * 200), REAL_PROVENANCE)[1]["source_file"], "a" * 200)

    def test_render_notices_rechecks_every_value_when_it_is_called_directly(self):
        base = real_models()
        for index, record in enumerate(base):
            role = record["role"]
            extras = {"sha256": {"63자리": "a" * 63, "65자리": "a" * 65, "대문자": "A" * 64}, "repo": self.BAD_REPOS, "commit": self.BAD_COMMITS, "git_blob": self.BAD_COMMITS, "source_file": self.BAD_FILES, "license_tag": self.BAD_TAGS}
            for field in ["sha256", "repo", "commit", "source_file", "license_tag"] + (["git_blob"] if role == "dict" else []):
                for name, value in list(self.hostile().items()) + list(extras[field].items()):
                    with self.subTest(role=role, field=field, value=name):
                        changed = [dict(item) for item in base]
                        changed[index][field] = value
                        with self.assertRaises(B.BuildError):
                            B.render_notices(PACKAGES, GEOS, COLLECTED, (), changed)
            for field in ("bytes", "entries") if role == "dict" else ("bytes",):
                for name, value in (("참", True), ("거짓", False), ("0", 0), ("음수", -1), ("너무 큼", 10 ** 12), ("글", "5"), ("소수", 5.0), ("없음", None)):
                    with self.subTest(role=role, field=field, value=name):
                        changed = [dict(item) for item in base]
                        changed[index][field] = value
                        with self.assertRaises(B.BuildError):
                            B.render_notices(PACKAGES, GEOS, COLLECTED, (), changed)
            for what, change in (("모르는 칸이 더 있다", {"note": "x"}), ("label 이 다르다", {"label": "다른 이름"}), ("file 이 다르다", {"file": "models/other/inference.onnx"})):
                with self.subTest(role=role, what=what):
                    changed = [dict(item) for item in base]
                    changed[index].update(change)
                    with self.assertRaises(B.BuildError):
                        B.render_notices(PACKAGES, GEOS, COLLECTED, (), changed)
            with self.subTest(role=role, what="필요한 칸이 없다"):
                changed = [dict(item) for item in base]
                changed[index].pop("sha256")
                with self.assertRaises(B.BuildError):
                    B.render_notices(PACKAGES, GEOS, COLLECTED, (), changed)

    def test_write_license_outputs_rejects_a_dangerous_record_before_it_writes_anything(self):
        base = real_models()
        for name, value in (("줄바꿈", "x" + chr(10) + "[6] injected section"), ("HTML", "<script>alert(1)</script>"), ("아주 긴 저장소", "a" * 100000 + "/b")):
            with self.subTest(value=name), tempfile.TemporaryDirectory() as root:
                changed = [dict(item) for item in base]
                changed[0]["repo"] = value
                dists = make_site(root, SITE)
                dst = make_bundle(root)
                with self.assertRaises(B.BuildError):
                    B.write_license_outputs(dst, PACKAGES, (), lookup_of(dists), lambda: "3.99.9", changed)
                self.assertFalse(os.path.exists(os.path.join(dst, "licenses")))
                self.assertFalse(os.path.exists(os.path.join(dst, "THIRD_PARTY_NOTICES.txt")))

    def test_normal_values_give_exactly_the_section_text_of_before_the_value_checks_were_added(self):
        text = B.render_notices(PACKAGES, GEOS, COLLECTED, (), real_models())
        self.assertEqual(tuple(section_lines(text)), GOLDEN_SECTION, "정상 값에서는 출력이 한 글자도 안 바뀐다")
        self.assertEqual(text, B.render_notices(PACKAGES, GEOS, COLLECTED, (), list(reversed(real_models()))))

    def test_the_one_shape_function_answers_the_boundary_cases(self):
        table = (("repo", "PaddlePaddle/x", True), ("repo", self.REPO_200, True), ("repo", self.REPO_201, False), ("repo", "no_slash", False), ("repo", None, False), ("repo", 5, False),
                 ("file", "models/det/inference.onnx", True), ("file", "a/../b", False), ("file", "./a", False), ("file", "a/b/", False), ("file", "", False),
                 ("source_file", "a" * 200, True), ("source_file", "a" * 201, False), ("source_file", "x y", False),
                 ("commit", "0" * 40, True), ("commit", "0" * 39, False), ("commit", "0" * 41, False), ("commit", "A" * 40, False), ("git_blob", "f" * 40, True), ("git_blob", "f" * 39, False),
                 ("sha256", "f" * 64, True), ("sha256", "f" * 63, False), ("sha256", "F" * 64, False),
                 ("license_tag", "apache-2.0", True), ("license_tag", "a" * 40, True), ("license_tag", "a" * 41, False), ("license_tag", "-x", False), ("license_tag", "a b", False),
                 ("license_tag", b"apache-2.0", False))
        for field, value, want in table:
            with self.subTest(field=field, value=repr(value)[:30]):
                self.assertIs(B.notice_field_ok(field, value), want)


if __name__ == "__main__":
    unittest.main()
