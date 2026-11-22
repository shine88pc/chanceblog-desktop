"""글자 읽기 추가 도구 빌드 점검 규칙(`ocr_addon/build_rules.py` — a 단계 보고 ⑥ 의 R1–R4, 설계서 5-6·6-2 T-E, 결정 D-528)의 시험 — **빌드 없이** 돈다.

진짜 묶음(PyInstaller 산출물)·pefile 은 CI 에 없으므로, 합성 가져오기 표·가짜 파일 목록·가짜 자가 점검 결과로 규칙 함수를 시험한다. 지키는 것:
  R1 가져오기 표: 네트워크 DLL 을 가져오는 파일은 python312.dll·_socket.pyd·select.pyd 셋뿐(예외 밖 하나만 있어도 실패, 위치·대소문자·가져오기 종류(정적·지연·묶음)·예외 파일의 다른 네트워크 DLL 까지)
  R2 묶음 파일: FFmpeg DLL·pem 류·기본 모델이 없고 모델 2개·사전의 크기와 SHA-256 이 박힌 값과 같다
  R3 부품: ssl·_ssl·libcrypto·_overlapped·_multiprocessing·urllib3·certifi 가 없고 requests 는 가짜 껍데기이며 동결본이 ssl 등을 실제로 못 가져온다
  R4 자가 점검: 모든 칸이 통과(소켓 가드 음성 대조 5/5·정상 읽기 시도 0)
그리고 잠금 파일 규칙(해시·중복·PyPI 업로드 14일)·모델 잠금(`models.lock.json`)이 앱에 박은 값·작업자의 값과 같음·산출물 이름·키 모양 훑기.
pefile 이 있을 때만 도는 시험(진짜 PE 파일 읽기)은 없으면 건너뛰기로 표시한다(`ocr_addon/build_ocr_addon.py` 의 `pe_rows` — 합성 PE 를 만들어 읽는다).
"""
import ast
import copy
import datetime
import fnmatch
import hashlib
import json
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_build_support as support  # noqa: E402

rules = support.load("build_rules")
ROOT = support.ROOT

try:
    import pefile  # noqa: F401
    HAVE_PEFILE = True
except ImportError:                      # 앱 CI 에는 pefile 이 없다(빌드 환경에만 있다)
    HAVE_PEFILE = False

GOOD_ROWS = [
    {"path": "ocr_worker.exe", "imports": ["kernel32.dll", "user32.dll"], "delay": [], "bound": []},
    {"path": "_internal/python312.dll", "imports": ["kernel32.dll", "ws2_32.dll", "advapi32.dll"], "delay": [], "bound": []},
    {"path": "_internal/_socket.pyd", "imports": ["ws2_32.dll", "iphlpapi.dll", "kernel32.dll"], "delay": [], "bound": []},
    {"path": "_internal/select.pyd", "imports": ["ws2_32.dll", "kernel32.dll"], "delay": [], "bound": []},
    {"path": "_internal/cv2/cv2.pyd", "imports": ["kernel32.dll", "ole32.dll", "python3.dll"], "delay": [], "bound": []},
    {"path": "_internal/onnxruntime/capi/onnxruntime.dll", "imports": ["advapi32.dll", "dbghelp.dll", "kernel32.dll"], "delay": [], "bound": []},
]
MODELS = {"models/det/inference.onnx": b"det-bytes", "models/rec/inference.onnx": b"rec-bytes-longer", "data/ppocrv5_korean_dict.txt": b"dict-bytes"}
EXPECTED = {key: (len(data), hashlib.sha256(data).hexdigest()) for key, data in MODELS.items()}
GOOD_SIZES = {"ocr_worker.exe": 5505592, "_internal/python312.dll": 6972184, "_internal/cv2/cv2.pyd": 85848064, "_internal/rapidocr/config.yaml": 900, **{key: len(data) for key, data in MODELS.items()}}
GOOD_SELFTEST = {
    "python": "3.12.0", "frozen": True, "guard_active": True,
    "negative_control": [{"probe": name, "blocked_and_counted": True, "outcome": "x"} for name in ("getaddrinfo", "create_connection", "connect", "connect_ex", "gethostbyname")],
    "negative_control_attempts": 5, "negative_control_recent_targets_only_test_addresses": True, "loopback_not_counted": True, "files_ok": True,
    "imports": {"numpy": "2.5.4", "cv2": "5.0.0", "requests": "0+offline-stub"},
    "imports_optional": {"google.protobuf": "없음(묶이지 않음) ModuleNotFoundError", "ssl": "없음(묶이지 않음) ModuleNotFoundError: No module named 'ssl'", "urllib3": "없음(묶이지 않음) x",
                         "certifi": "없음(묶이지 않음) x", "asyncio": "없음(묶이지 않음) x", "multiprocessing": "없음(묶이지 않음) x", "colorama": "0.4.6"},
    "imports_failed": [], "selfcheck_ok": True, "guard_attempts_during_normal_read": 0, "ok": True,
}
# R1 의 네트워크 DLL 목록과 예외 파일이 가져와도 되는 DLL — 규칙 모듈의 목록을 돌며 확인하면 목록이 같이 틀려도 통과하므로 글자 그대로 못박는다(독립 검증 S 의 SP-3).
PINNED_NET_DLLS = ("ws2_32.dll", "wsock32.dll", "mswsock.dll", "wininet.dll", "winhttp.dll", "iphlpapi.dll", "dnsapi.dll", "urlmon.dll", "wldap32.dll",
                   "httpapi.dll", "netapi32.dll", "rasapi32.dll", "mpr.dll", "webservices.dll", "wlanapi.dll", "fwpuclnt.dll", "winnsi.dll", "nsi.dll", "dhcpcsvc.dll")
PINNED_EXCEPTION_NET_OK = ("ws2_32.dll", "iphlpapi.dll")
GOOD_NAMES = {"cv2", "numpy", "numpy.libs", "onnxruntime", "PIL", "rapidocr", "select.pyd", "_socket.pyd", "python312.dll", "base_library.zip", "ocr_worker.exe", "models", "data", "requests"}


def digest_of(key):
    return hashlib.sha256(MODELS[key]).hexdigest()


def rows_with(extra=(), drop=()):
    rows = [copy.deepcopy(row) for row in GOOD_ROWS if row["path"] not in drop]
    return rows + [copy.deepcopy(item) for item in extra]


class PeRuleTest(unittest.TestCase):
    def test_the_good_table_has_no_problem_and_python_parts_alone_may_import_the_network_libraries(self):
        self.assertEqual(rules.pe_problems(rows_with()), [])
        self.assertEqual(rules.PE_EXCEPTIONS, ("_internal/python312.dll", "_internal/_socket.pyd", "_internal/select.pyd"), "예외는 셋뿐이다")

    def test_one_file_outside_the_exceptions_is_enough_to_fail(self):
        for path in ("_internal/_ssl.pyd", "_internal/libcrypto-3.dll", "_internal/_overlapped.pyd", "_internal/_multiprocessing.pyd", "_internal/cv2/cv2.pyd", "ocr_worker.exe",
                     "_internal/cv2/opencv_videoio_ffmpeg500_64.dll", "_internal/numpy/_core/_multiarray_umath.pyd", "_internal/PIL/_avif.pyd"):
            with self.subTest(path=path):
                rows = rows_with(extra=[{"path": path, "imports": ["kernel32.dll", "ws2_32.dll"], "delay": [], "bound": []}], drop=(path,))
                problems = rules.pe_problems(rows)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(path, problems[0])
                self.assertIn("ws2_32.dll", problems[0])

    def test_every_listed_network_library_is_caught_in_any_kind_of_import(self):
        self.assertEqual(rules.NET_DLLS, PINNED_NET_DLLS, "네트워크 DLL 목록은 열아홉 이름 그대로다 — 이름 하나를 닮은 이름으로 바꿔도, 줄여도, 늘려도 알아챈다")
        self.assertEqual(len(set(PINNED_NET_DLLS)), 19)
        for dll in PINNED_NET_DLLS:
            for kind in ("imports", "delay", "bound"):
                with self.subTest(dll=dll, kind=kind):
                    row = {"path": "_internal/other.pyd", "imports": [], "delay": [], "bound": []}
                    row[kind] = [dll.upper()]                                    # 가져오기 표의 이름은 대소문자가 섞여 있다
                    self.assertEqual(len(rules.pe_problems(rows_with(extra=[row]))), 1)

    def test_the_exceptions_hold_only_at_the_exact_place_and_ignore_case_and_slash_style(self):
        for path in ("_internal/sub/select.pyd", "select.pyd", "_internal/other/python312.dll", "python312.dll", "ocr/_internal/_socket.pyd"):
            with self.subTest(path=path):
                rows = rows_with(extra=[{"path": path, "imports": ["ws2_32.dll"], "delay": [], "bound": []}])
                self.assertEqual(len(rules.pe_problems(rows)), 1)
        windows_style = rows_with(drop=("_internal/select.pyd",), extra=[{"path": chr(92).join(("_INTERNAL", "SELECT.PYD")), "imports": ["WS2_32.dll"], "delay": [], "bound": []}])
        self.assertEqual(rules.pe_problems(windows_style), [])

    def test_an_exception_file_may_not_import_any_other_network_library(self):
        self.assertEqual(rules.PE_EXCEPTION_NET_OK, PINNED_EXCEPTION_NET_OK, "예외 파일이 가져와도 되는 네트워크 DLL 은 둘뿐이다 — 하나를 더해도 알아챈다")
        for path in rules.PE_EXCEPTIONS:                                                # 예외 셋 모두에 대해
            for dll in (name for name in PINNED_NET_DLLS if name not in PINNED_EXCEPTION_NET_OK):      # 목록의 나머지 열일곱 개 전부
                with self.subTest(path=path, dll=dll):
                    rows = rows_with(drop=(path,), extra=[{"path": path, "imports": ["ws2_32.dll", "iphlpapi.dll", dll], "delay": [], "bound": []}])
                    problems = rules.pe_problems(rows)
                    self.assertEqual(len(problems), 1)
                    self.assertIn("허용 밖", problems[0])
        for path in rules.PE_EXCEPTIONS:                                                # 허용된 둘만 가져오면 통과
            rows = rows_with(drop=(path,), extra=[{"path": path, "imports": list(PINNED_EXCEPTION_NET_OK), "delay": [], "bound": []}])
            self.assertEqual(rules.pe_problems(rows), [], path)

    def test_a_table_that_misses_the_core_files_or_has_unreadable_files_fails(self):
        self.assertTrue(rules.pe_problems([]), "빈 표는 아무것도 못 본 채 통과하면 안 된다")
        self.assertTrue(rules.pe_problems(rows_with(drop=("ocr_worker.exe",))))
        self.assertTrue(rules.pe_problems(rows_with(drop=("_internal/python312.dll",))))
        problems = rules.pe_problems(rows_with(), errors=["_internal/broken.pyd (PEFormatError)"])
        self.assertEqual(len(problems), 1)
        self.assertIn("broken.pyd", problems[0])

    def test_the_messages_name_the_rule_and_the_file(self):
        rows = rows_with(extra=[{"path": "_internal/x.dll", "imports": ["winhttp.dll"], "delay": [], "bound": []}])
        self.assertTrue(rules.pe_problems(rows)[0].startswith("R1 "))
        self.assertIn("_internal/x.dll", rules.pe_problems(rows)[0])


class BundleFileRuleTest(unittest.TestCase):
    def check(self, sizes=None, expected=None, digest=None):
        return rules.bundle_file_problems(GOOD_SIZES if sizes is None else sizes, EXPECTED if expected is None else expected, digest or digest_of)

    def test_the_good_listing_passes(self):
        self.assertEqual(self.check(), [])

    def test_ffmpeg_dll_pem_files_and_default_models_are_refused(self):
        for extra in ("_internal/cv2/opencv_videoio_ffmpeg500_64.dll", "_internal/cv2/OPENCV_VIDEOIO_FFMPEG600_64.DLL", "_internal/certifi/cacert.pem", "_internal/x/CA.PEM", "_internal/a/b.crt",
                      "_internal/a/private.key", "_internal/rapidocr/models/PP-OCRv6_det_small.onnx", "_internal/rapidocr/models/ch_ppocr_mobile_v2.0_cls_mobile.onnx", "models/extra/other.onnx"):
            with self.subTest(extra=extra):
                problems = self.check(sizes={**GOOD_SIZES, extra: 10})
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(extra, problems[0])
                self.assertTrue(problems[0].startswith("R2 "))

    def test_the_two_models_and_the_dictionary_must_be_there_with_the_exact_size_and_hash(self):
        for key in EXPECTED:
            with self.subTest(key=key, what="missing"):
                sizes = {path: size for path, size in GOOD_SIZES.items() if path != key}
                self.assertEqual(len(self.check(sizes=sizes)), 1)
            with self.subTest(key=key, what="size"):
                self.assertEqual(len(self.check(sizes={**GOOD_SIZES, key: GOOD_SIZES[key] + 1})), 1)
            with self.subTest(key=key, what="hash"):
                self.assertEqual(len(self.check(digest=lambda path, bad=key: "0" * 64 if path == bad else digest_of(path))), 1)

    def test_the_hash_is_only_asked_for_the_pinned_files_and_with_their_bundle_path(self):
        asked = []
        self.check(digest=lambda path: asked.append(path) or digest_of(path))
        self.assertEqual(sorted(asked), sorted(EXPECTED))

    def test_the_worker_exe_must_be_in_the_bundle(self):
        sizes = {path: size for path, size in GOOD_SIZES.items() if path != "ocr_worker.exe"}
        self.assertEqual(len(self.check(sizes=sizes)), 1)

    def test_a_wrong_size_never_reaches_the_hash(self):
        calls = []
        problems = self.check(sizes={**GOOD_SIZES, "models/det/inference.onnx": 1}, digest=lambda path: calls.append(path) or digest_of(path))
        self.assertEqual(len(problems), 1)
        self.assertNotIn("models/det/inference.onnx", calls)


class ModuleRuleTest(unittest.TestCase):
    def check(self, names=None, imports=None, optional=None):
        return rules.module_problems(GOOD_NAMES if names is None else names, GOOD_SELFTEST["imports"] if imports is None else imports,
                                     GOOD_SELFTEST["imports_optional"] if optional is None else optional)

    def test_the_good_bundle_passes(self):
        self.assertEqual(self.check(), [])

    def test_every_forbidden_part_is_caught_in_every_spelling_it_comes_in(self):
        spellings = {"ssl": ("ssl", "ssl.pyc"), "_ssl": ("_ssl.cp312-win_amd64.pyd", "_ssl.pyd", "_ssl"), "libcrypto": ("libcrypto-3.dll", "libcrypto-3-x64.dll", "LIBCRYPTO-3.DLL"),
                     "libssl": ("libssl-3.dll", "libssl-3-x64.dll"), "_overlapped": ("_overlapped.pyd",), "_multiprocessing": ("_multiprocessing.pyd",),
                     "urllib3": ("urllib3", "urllib3.util.retry", "urllib3-2.8.0.dist-info"), "certifi": ("certifi", "certifi.core"), "_hashlib": ("_hashlib.pyd",)}
        self.assertEqual(sorted(spellings), sorted(rules.FORBIDDEN_MODULES), "이 시험이 규칙의 목록 전부를 다룬다")
        for part, forms in spellings.items():
            for form in forms:
                with self.subTest(part=part, form=form):
                    problems = self.check(names=GOOD_NAMES | {form})
                    self.assertEqual(len(problems), 1, problems)
                    self.assertIn(part, problems[0])

    def test_innocent_look_alike_names_are_not_flagged(self):
        self.assertEqual(self.check(names=GOOD_NAMES | {"sslx.pyd", "libsslx", "my_ssl_helper", "urllib", "_socket.pyd", "select.pyd", "certifi_extra_data"}), [])

    def test_requests_must_be_the_empty_stand_in(self):
        self.assertEqual(rules.STUB_VERSION, "0+offline-stub")
        for value in ("2.34.2", "ok", "", None, "0+offline-stub-2", "offline-stub"):
            with self.subTest(value=value):
                self.assertEqual(len(self.check(imports={"requests": value})), 1)
        self.assertEqual(len(self.check(imports={})), 1, "requests 칸이 없으면 확인하지 못한 것이다")

    def test_the_frozen_runtime_must_say_it_cannot_import_the_forbidden_parts(self):
        for name in rules.RUNTIME_ABSENT:
            with self.subTest(name=name):
                for seen in ("3.12.0", "ok", None, ""):
                    self.assertEqual(len(self.check(optional={**GOOD_SELFTEST["imports_optional"], name: seen})), 1)
                gone = {key: value for key, value in GOOD_SELFTEST["imports_optional"].items() if key != name}
                self.assertEqual(len(self.check(optional=gone)), 1)
        self.assertEqual(sorted(rules.RUNTIME_ABSENT), ["asyncio", "certifi", "multiprocessing", "ssl", "urllib3"])

    def test_an_empty_name_list_is_a_failure_not_a_pass(self):
        self.assertTrue(self.check(names=set()))

    def test_the_worker_selftest_really_tries_these_imports_and_writes_the_absent_marker(self):
        """규칙이 기대는 사실을 작업자 소스에 묶는다 — 작업자가 imports_optional 에 이 이름들을 시도하고 '없음' 글을 적는다."""
        source = support.read("ocr_addon/worker_main.py")
        tree = ast.parse(source)
        optional = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "optional")
        names = [item.value for item in optional.elts]
        for name in rules.RUNTIME_ABSENT:
            self.assertIn(name, names)
        self.assertIn('"' + rules.ABSENT_PREFIX + "(묶이지 않음) ", source)


class SelftestRuleTest(unittest.TestCase):
    def test_the_real_shaped_good_report_passes(self):
        self.assertEqual(rules.selftest_problems(GOOD_SELFTEST, 0), [])

    def test_each_field_that_turns_bad_is_caught_on_its_own(self):
        flips = {"ok": False, "frozen": False, "guard_active": False, "negative_control_attempts": 4, "negative_control_recent_targets_only_test_addresses": False, "loopback_not_counted": False,
                 "files_ok": False, "imports_failed": ["cv2"], "selfcheck_ok": False, "guard_attempts_during_normal_read": 1}
        for name, value in flips.items():
            with self.subTest(field=name):
                report = {**GOOD_SELFTEST, name: value}
                problems = rules.selftest_problems(report, 0)
                self.assertEqual(len(problems), 1, problems)
                self.assertTrue(problems[0].startswith("R4 "))

    def test_the_negative_control_must_block_all_five_probes(self):
        for bad in ([], GOOD_SELFTEST["negative_control"][:4], GOOD_SELFTEST["negative_control"] + [GOOD_SELFTEST["negative_control"][0]], "all",
                    [{**GOOD_SELFTEST["negative_control"][0], "blocked_and_counted": False}] + GOOD_SELFTEST["negative_control"][1:]):
            with self.subTest(bad=str(bad)[:40]):
                self.assertEqual(len(rules.selftest_problems({**GOOD_SELFTEST, "negative_control": bad}, 0)), 1)

    def test_a_missing_field_is_a_failure_and_the_worker_ok_alone_is_not_trusted(self):
        for name in list(GOOD_SELFTEST):
            if name in ("python", "imports", "imports_optional"):
                continue
            with self.subTest(missing=name):
                report = {key: value for key, value in GOOD_SELFTEST.items() if key != name}
                self.assertTrue(rules.selftest_problems(report, 0))
        lying = {**GOOD_SELFTEST, "ok": True, "guard_attempts_during_normal_read": 3}
        self.assertTrue(rules.selftest_problems(lying, 0), "ok 가 참이어도 세부 칸이 나쁘면 실패")

    def test_a_nonzero_exit_code_and_an_unreadable_report_fail(self):
        self.assertEqual(len(rules.selftest_problems(GOOD_SELFTEST, 6)), 1)
        for report in (None, [], "ok", 5):
            self.assertEqual(len(rules.selftest_problems(report, 0)), 1)


class KeyShapeRuleTest(unittest.TestCase):
    def shapes(self):
        marker = "CANARY_"
        return {"구글 키": marker + "AI" + "za" + "A" * 35, "깃허브 토큰": marker + "ghp" + "_" + "B" * 36, "개인 키": "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
                "서비스 키": marker + "sk" + "-" + "C" * 40, "텔레그램 봇": marker + "123456789" + ":AA" + "D" * 34}

    def test_each_key_shape_is_caught_and_the_answer_never_repeats_the_text(self):
        for name, text in self.shapes().items():
            with self.subTest(name=name):
                problems = rules.key_shape_problems([("_internal/x/notes.txt", "앞 글 " + text + " 뒤 글")])
                self.assertEqual(problems, ["키 모양 글이 든 파일: _internal/x/notes.txt"])
                self.assertNotIn(text, problems[0])

    def test_ordinary_text_passes(self):
        self.assertEqual(rules.key_shape_problems([("a.txt", "한 글자씩 적은 사전\n가\n나\n" + "x" * 5000), ("b.md", "Apache License 2.0 — see the file for terms"), ("c.json", "{}")]), [])

    def test_the_shapes_are_the_same_list_as_the_main_package_check(self):
        sys.path.insert(0, str(ROOT / "packaging"))
        try:
            import pkgcommon
        finally:
            sys.path.remove(str(ROOT / "packaging"))
        self.assertEqual(tuple(rules.KEY_SHAPES), tuple(pkgcommon.KEY_SHAPES))


class LockRuleTest(unittest.TestCase):
    def real(self):
        return rules.parse_lock(support.read("ocr_addon/requirements-ocr.lock")), json.loads(support.read("ocr_addon/requirements-ocr.meta.json"))

    def test_the_real_lock_has_twenty_one_hashed_pins_and_numpy_is_the_old_enough_one(self):
        pins, _meta = self.real()
        self.assertEqual(len(pins), 21)
        self.assertEqual(len({pin["name"] for pin in pins}), 21)
        self.assertTrue(all(len(pin["hashes"]) == 1 for pin in pins))
        versions = {pin["name"]: pin["version"] for pin in pins}
        self.assertEqual(versions["numpy"], "2.5.4")
        self.assertEqual(versions["rapidocr"], "3.10.0")
        self.assertEqual(versions["onnxruntime"], "1.31.1")
        self.assertEqual(versions["requests"], "2.34.2")

    def test_every_pin_is_at_least_fourteen_days_old_on_the_day_it_was_pinned_and_the_metadata_matches_the_lock(self):
        pins, meta = self.real()
        self.assertEqual(meta["min_age_days"], 14)
        self.assertEqual(rules.pin_age_problems(pins, meta), [])
        self.assertEqual(sorted(meta["packages"]), sorted(pin["name"] for pin in pins))
        pinned = datetime.date.fromisoformat(meta["pinned_on"])
        ages = {name: (pinned - datetime.date.fromisoformat(entry["uploaded"])).days for name, entry in meta["packages"].items()}
        self.assertEqual(min(ages.values()), 22, "가장 새 핀은 onnxruntime(22일)")
        self.assertGreaterEqual(ages["numpy"], 14)

    def test_the_build_tools_lock_is_hashed_too_and_shares_the_one_overlapping_pin(self):
        build = rules.parse_lock(support.read("ocr_addon/requirements-build.txt"))
        self.assertEqual(len(build), 7)
        self.assertTrue(all(len(pin["hashes"]) == 1 for pin in build))
        ocr = {pin["name"]: pin for pin in self.real()[0]}
        for pin in build:
            if pin["name"] in ocr:
                self.assertEqual(pin, ocr[pin["name"]], "두 잠금 파일에 같이 든 핀은 판도 해시도 같다")

    def test_a_pin_younger_than_the_floor_is_caught_and_the_floor_itself_passes(self):
        pins = [{"name": "alpha", "version": "1.0", "hashes": ["a" * 64]}]
        meta = {"pinned_on": "2026-11-17", "min_age_days": 14, "packages": {"alpha": {"version": "1.0", "uploaded": "2026-11-03"}}}
        self.assertEqual(rules.pin_age_problems(pins, meta), [], "정확히 14일은 통과")
        meta["packages"]["alpha"]["uploaded"] = "2026-11-04"
        self.assertEqual(len(rules.pin_age_problems(pins, meta)), 1, "13일은 실패")
        meta["packages"]["alpha"]["uploaded"] = "2026-11-17"
        self.assertEqual(len(rules.pin_age_problems(pins, meta)), 1, "같은 날도 실패")

    def test_missing_or_mismatched_metadata_and_a_broken_metadata_file_fail(self):
        pins = [{"name": "alpha", "version": "1.0", "hashes": ["a" * 64]}]
        good = {"pinned_on": "2026-11-17", "min_age_days": 14, "packages": {"alpha": {"version": "1.0", "uploaded": "2026-01-01"}}}
        self.assertEqual(rules.pin_age_problems(pins, good), [])
        self.assertEqual(len(rules.pin_age_problems(pins, {**good, "packages": {}})), 1)
        self.assertEqual(len(rules.pin_age_problems(pins, {**good, "packages": {"alpha": {"version": "2.0", "uploaded": "2026-01-01"}}})), 1)
        self.assertEqual(len(rules.pin_age_problems(pins, {**good, "packages": {"alpha": {"version": "1.0", "uploaded": "어제"}}})), 1)
        for broken in ({}, {"pinned_on": "2026-11-17"}, {**good, "min_age_days": "x"}, None):
            self.assertEqual(len(rules.pin_age_problems(pins, broken)), 1)

    def test_lock_lines_must_be_exact_pins_with_a_hash_and_no_repeats(self):
        h = "--hash=sha256:" + "a" * 64
        self.assertEqual(rules.parse_lock("# 주석\n\nAlpha_One==1.0 " + h + "\n")[0]["name"], "alpha-one")
        for bad in ("alpha>=1.0 " + h, "alpha==1.0", "alpha==1.0 --hash=sha256:xyz", "alpha==1.0 " + h + "\nalpha==1.1 " + h, "alpha==1.0 " + h + "\nALPHA==1.0 " + h,
                    "git+https://example.invalid/x#egg=alpha", "", "# 핀 없음\n"):
            with self.subTest(bad=bad[:30]):
                with self.assertRaises(ValueError):
                    rules.parse_lock(bad)

    def test_installed_versions_must_equal_the_locked_ones(self):
        pins = [{"name": "alpha", "version": "1.0", "hashes": []}, {"name": "beta", "version": "2.0", "hashes": []}]
        self.assertEqual(rules.installed_problems(pins, {"alpha": "1.0", "beta": "2.0"}), [])
        self.assertEqual(len(rules.installed_problems(pins, {"alpha": "1.0", "beta": "2.1"})), 1)
        self.assertEqual(len(rules.installed_problems(pins, {"alpha": "1.0"})), 1)
        self.assertEqual(len(rules.installed_problems(pins, {"alpha": None, "beta": None})), 2)


class ModelLockTest(unittest.TestCase):
    def lock(self):
        return json.loads(support.read("ocr_addon/models.lock.json"))

    def test_the_real_lock_is_well_formed_and_pins_commits(self):
        lock = self.lock()
        self.assertEqual(rules.lock_problems(lock), [])
        by_key = {entry["key"]: entry for entry in lock["files"]}
        self.assertEqual(by_key["models/det/inference.onnx"]["source"]["repo"], "PaddlePaddle/PP-OCRv5_mobile_det_onnx")
        self.assertEqual(by_key["models/det/inference.onnx"]["source"]["commit"], "e6f4fa85f00e168c862bc462aebca69eef9b3d3d")
        self.assertEqual(by_key["models/rec/inference.onnx"]["source"]["repo"], "PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx")
        self.assertEqual(by_key["models/rec/inference.onnx"]["source"]["commit"], "5c6f574b8e2230adf4287b33e736d71b9fabd28e")

    def test_the_lock_the_app_the_worker_and_the_dictionary_file_all_say_the_same_numbers(self):
        expected = rules.expected_files(self.lock())
        self.assertEqual(expected, {"models/det/inference.onnx": (4826518, "a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d"),
                                    "models/rec/inference.onnx": (13418787, "92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08"),
                                    "data/ppocrv5_korean_dict.txt": (47451, "a88071c68c01707489baa79ebe0405b7beb5cca229f4fc94cc3ef992328802d7")})
        sys.path.insert(0, str(ROOT / "src"))
        try:
            from chanceblog_desktop.service import ocr_addon as app_side
        finally:
            sys.path.remove(str(ROOT / "src"))
        self.assertEqual(app_side.EMBEDDED_FILES, expected, "앱에 박은 값과 빌드 잠금이 같다")
        tree = ast.parse(support.read("ocr_addon/worker_main.py"))
        worker = next(ast.literal_eval(node.value) for node in ast.walk(tree) if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "EXPECT")
        self.assertEqual({"models/det/inference.onnx": worker["det"], "models/rec/inference.onnx": worker["rec"], "data/ppocrv5_korean_dict.txt": worker["dict"]}, expected, "작업자의 값과도 같다")
        dictionary = (ROOT / "ocr_addon" / "data" / "ppocrv5_korean_dict.txt").read_bytes()
        self.assertEqual((len(dictionary), hashlib.sha256(dictionary).hexdigest()), expected["data/ppocrv5_korean_dict.txt"], "저장소의 사전 파일 바이트가 잠금 값과 같다(줄 끝 변환이 없다)")

    def test_the_dictionary_bytes_are_protected_from_line_ending_conversion(self):
        text = support.read(".gitattributes")
        self.assertIn("ocr_addon/data/** -text", text)

    def test_bad_locks_are_refused(self):
        def changed(mutator):
            lock = copy.deepcopy(self.lock())
            mutator(lock)
            return lock

        def entry(lock, key):
            return next(item for item in lock["files"] if item["key"] == key)

        det = "models/det/inference.onnx"
        cases = {
            "schema": lambda lock: lock.update(schema=2),
            "files not list": lambda lock: lock.update(files={}),
            "unknown extra file": lambda lock: lock["files"].append(copy.deepcopy(entry(lock, det)) | {"key": "models/other/inference.onnx"}),
            "missing file": lambda lock: lock["files"].remove(entry(lock, det)),
            "sha not hex": lambda lock: entry(lock, det).update(sha256="Z" * 64),
            "sha short": lambda lock: entry(lock, det).update(sha256="a" * 63),
            "bytes zero": lambda lock: entry(lock, det).update(bytes=0),
            "bytes text": lambda lock: entry(lock, det).update(bytes="4826518"),
            "commit short": lambda lock: entry(lock, det)["source"].update(commit="e6f4fa85"),
            "commit branch name": lambda lock: entry(lock, det)["source"].update(commit="main"),
            "repo with dots": lambda lock: entry(lock, det)["source"].update(repo="../evil"),
            "repo no owner": lambda lock: entry(lock, det)["source"].update(repo="PP-OCRv5_mobile_det_onnx"),
            "path parent": lambda lock: entry(lock, det)["source"].update(path="../inference.onnx"),
            "path question": lambda lock: entry(lock, det)["source"].update(path="inference.onnx?download=true"),
            "path space": lambda lock: entry(lock, det)["source"].update(path="a b.onnx"),
            "kind other": lambda lock: entry(lock, det)["source"].update(kind="url"),
        }
        for name, mutator in cases.items():
            with self.subTest(case=name):
                self.assertTrue(rules.lock_problems(changed(mutator)), name)
        for bad in (None, [], "x", {"schema": 1}):
            self.assertTrue(rules.lock_problems(bad))


class DictionaryProvenanceTest(unittest.TestCase):
    """글자 사전의 출처·라이선스 근거 기록(`ocr_addon/data/ppocrv5_korean_dict.provenance.json`, 독립 검증 S·Q 의 SP-5·QP-5) — 모양과, 잠금·사전 파일과의 일치, 문서에 옮겨 적었는지를 지킨다."""

    def record(self):
        return json.loads(support.read("ocr_addon/data/ppocrv5_korean_dict.provenance.json"))

    def test_the_record_matches_the_lock_and_the_real_dictionary_file(self):
        record, lock = self.record(), json.loads(support.read("ocr_addon/models.lock.json"))
        entry = next(item for item in lock["files"] if item["key"] == "data/ppocrv5_korean_dict.txt")
        raw = (ROOT / "ocr_addon" / "data" / "ppocrv5_korean_dict.txt").read_bytes()
        self.assertEqual((record["bytes"], record["sha256"]), (entry["bytes"], entry["sha256"]))
        self.assertEqual((record["bytes"], record["sha256"], record["lines"]), (len(raw), hashlib.sha256(raw).hexdigest(), raw.count(b"\n")))
        self.assertEqual(record["file"], "ppocrv5_korean_dict.txt")

    def test_the_upstream_source_is_written_down_with_exact_identifiers_and_the_license_basis(self):
        record = self.record()
        source = record["derived_from"]
        self.assertEqual(source["kind"], "huggingface")
        self.assertRegex(source["repo"], r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
        self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(source["git_blob"], r"^[0-9a-f]{40}$")
        # 받기 기록(photolab 0단계 stage0_download.py)과 같은 값 — 한 글자만 틀려도 알아챈다
        self.assertEqual((source["repo"], source["commit"], source["file"], source["file_bytes"], source["git_blob"]),
                         ("PaddlePaddle/korean_PP-OCRv5_mobile_rec", "c02ecaf1f22bfd1c618cce154fd19185b47e663a", "inference.yml", 96039, "ba8f60f36464f8444b71301062ec6bf4f7b2d1e0"))
        self.assertEqual(record["license_tag"], "apache-2.0")
        for key in ("method", "license_basis", "verified_on", "verified_how"):
            self.assertTrue(record[key].strip(), key)
        self.assertNotIn(chr(0x7E), json.dumps(record, ensure_ascii=False))
        self.assertIsNone(re.search(r"(?i)https?://", json.dumps(record, ensure_ascii=False)))

    def test_the_docs_tell_where_the_dictionary_comes_from(self):
        record = self.record()
        source = record["derived_from"]
        for path in ("docs/PACKAGE_OCR.md", "docs/DECISIONS.md"):
            text = support.read(path)
            for word in (source["repo"], source["commit"][:8], source["git_blob"][:8], "provenance.json"):
                self.assertIn(word, text, (path, word))
        self.assertIn("apache-2.0", support.read("docs/PACKAGE_OCR.md"))


class DocHashTest(unittest.TestCase):
    """문서(PACKAGE_OCR·결정 D-527에서 D-533)에 적힌 해시·커밋 앞자리가 실제 값의 앞자리인가 — 결정 기록은 나중에 무결성을 대조할 때 보는 글이다(독립 검증 Q 의 QP-4: 사전 SHA-256 앞자리 한 글자가 틀려 있었다).
    새 해시 앞자리를 문서에 적으면 아래 알려진 전체 값 목록에도 전체 값을 함께 적는다."""

    KNOWN = ("197deea17024e9ca7d4750232a98d2e9986e47d1a94162308e205cae7fcfb884",       # a 단계 시제품 압축 파일(지시서가 알려 준 값)
             "f01f93ba2d720f2ed357c9dbfcd19a75abd06883d676d9755782165303de2eea",       # 이 PC 증거 빌드 1(커밋 시각)
             "eed3750c8c1ef09c01cb5d34517d383b93040e0b26a517f020788b64691b03ff")       # 이 PC 증거 빌드 2·3(같은 SOURCE_DATE_EPOCH — 바이트까지 같음)

    def full_values(self):
        lock = json.loads(support.read("ocr_addon/models.lock.json"))
        values = list(self.KNOWN)
        for item in lock["files"]:
            values.append(item["sha256"])
            if item["source"].get("commit"):
                values.append(item["source"]["commit"])
        source = json.loads(support.read("ocr_addon/data/ppocrv5_korean_dict.provenance.json"))["derived_from"]
        values += [source["commit"], source["git_blob"]]
        return values

    def my_doc_text(self):
        rows = [line for line in support.read("docs/DECISIONS.md").splitlines() if re.match(r"\| D-5(2[7-9]|3[0-3]) \|", line)]
        self.assertEqual(len(rows), 7, "결정 D-527에서 D-533 일곱 행")
        return "\n".join(rows) + "\n" + support.read("docs/PACKAGE_OCR.md")

    @staticmethod
    def wrong_short_hashes(text, values):
        """글 안의 `<16진수 7에서 64자>…` 중 알려진 전체 값의 앞자리가 아닌 것들."""
        return [token for token in re.findall(r"(?<![0-9a-f])([0-9a-f]{7,64})…", text) if not any(value.startswith(token) for value in values)]

    def test_every_short_hash_in_my_docs_is_the_start_of_a_known_full_value(self):
        text, values = self.my_doc_text(), self.full_values()
        self.assertGreaterEqual(len(re.findall(r"(?<![0-9a-f])([0-9a-f]{7,64})…", text)), 8, "문서에 해시 앞자리가 있어야 이 시험이 의미가 있다")
        self.assertEqual(self.wrong_short_hashes(text, values), [], "문서의 해시 앞자리가 알려진 전체 값 어느 것의 앞자리도 아니다")

    def test_the_check_function_notices_a_one_letter_typo_and_an_unknown_hash(self):
        """검사 함수 자체의 시험 — 사전 SHA-256 앞자리를 한 글자 틀리게 적은 글과 모르는 해시는 걸리고 맞는 앞자리는 통과한다(독립 검증 Q 의 ΔQ-2)."""
        values = self.full_values()
        self.assertEqual(self.wrong_short_hashes("사전 `a88071c7…` 와 `a88071c6…` 와 `deadbeef…`", values), ["a88071c7", "deadbeef"])
        self.assertEqual(self.wrong_short_hashes("`a88071c6…` `e6f4fa85…` `197deea1…`", values), [])
        self.assertEqual(self.wrong_short_hashes("짧은 값 abc123… 은 일곱 글자 미만이라 보지 않는다", values), [])


class OutputNameTest(unittest.TestCase):
    def test_the_zip_name_fits_the_allowed_upload_shape_and_rejects_odd_versions(self):
        name = rules.zip_name("0.1.0-preview.1")
        self.assertEqual(name, "ChanceBlogDesktop-OCR-0.1.0-preview.1-win64.zip")
        self.assertTrue(fnmatch.fnmatchcase(name, "ChanceBlogDesktop-*-win64.zip"))
        self.assertEqual(rules.zip_name("1.2.3"), "ChanceBlogDesktop-OCR-1.2.3-win64.zip")
        for bad in ("", "1.0", "../1.2.3", "1.2.3 ", "1.2.3/x", "v1.2.3", "1.2.3-", None, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    rules.zip_name(bad)
        self.assertEqual(rules.zip_name(support.read("VERSION").strip()).endswith("-win64.zip"), True)

    def test_the_sums_file_has_the_sha256sum_shape_sorted_by_name(self):
        text = rules.render_sums([("b.zip", "2" * 64), ("a.zip", "1" * 64)])
        self.assertEqual(text, "1" * 64 + "  a.zip\n" + "2" * 64 + "  b.zip\n")
        self.assertEqual(re.findall(r"^[0-9a-f]{64}  \S+$", text, re.M).__len__(), 2)

    def test_the_commit_time_text_is_utc(self):
        self.assertEqual(rules.utc_text(0), "1970-01-01T00:00:00Z")
        self.assertEqual(rules.utc_text(1794873600), "2026-11-17T00:00:00Z")


def synthetic_pe(import_dll, *, function="Connect"):
    """pefile 이 읽을 수 있는 가장 작은 PE32+ 파일 — 정적 가져오기 한 칸이 `import_dll` 의 함수 하나. 시험용으로 손으로 쌓았다."""
    file_align, section_rva, raw_ptr = 0x200, 0x1000, 0x200
    name = import_dll.encode("ascii") + b"\0"
    entry = b"\0\0" + function.encode("ascii") + b"\0"
    idt_size, ilt_off = 40, 40
    ilt = struct.pack("<QQ", section_rva + ilt_off + 32, 0)
    iat = struct.pack("<QQ", section_rva + ilt_off + 32, 0)
    hint_off, name_off = ilt_off + 32, ilt_off + 32 + len(entry)
    descriptor = struct.pack("<IIIII", section_rva + ilt_off, 0, 0, section_rva + name_off, section_rva + ilt_off + 16) + b"\0" * 20
    body = descriptor + ilt + iat + entry + name
    assert len(descriptor) == idt_size and body.index(entry) == hint_off
    raw = body + b"\0" * (file_align - len(body))
    dos = b"MZ" + b"\0" * 58 + struct.pack("<I", 0x80)
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x2022)
    optional = struct.pack("<HBBIIIIIQIIHHHHHHIIIIHHQQQQII", 0x20B, 14, 0, 0x200, 0x200, 0, 0x1000, 0x1000, 0x140000000, 0x1000, file_align, 6, 0, 0, 0, 6, 0,
                           0, 0x2000, 0x200, 0, 3, 0x8160, 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    directories = struct.pack("<II", 0, 0) + struct.pack("<II", section_rva, idt_size) + struct.pack("<II", 0, 0) * 14
    section = struct.pack("<8sIIIIIIHHI", b".idata", len(raw), section_rva, len(raw), raw_ptr, 0, 0, 0, 0, 0x40000040)
    header = dos + b"\0" * (0x80 - len(dos)) + b"PE\0\0" + coff + optional + directories + section
    return header + b"\0" * (raw_ptr - len(header)) + raw


@unittest.skipUnless(HAVE_PEFILE, "pefile 이 없다(앱 CI 에는 없고 빌드 환경에만 있다) — 합성 PE 읽기 시험은 건너뛴다")
class PeReaderTest(unittest.TestCase):
    """빌드 스크립트의 `pe_rows` 가 진짜 PE 파일의 가져오기 표를 규칙이 읽는 모양(`imports`·`delay`·`bound` 소문자 목록)으로 읽는가."""

    def test_the_reader_lists_the_imported_dll_and_the_rules_flag_it(self):
        build = support.load("build_ocr_addon")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "_internal").mkdir()
            (root / "_internal" / "net.pyd").write_bytes(synthetic_pe("WS2_32.dll"))
            (root / "_internal" / "plain.dll").write_bytes(synthetic_pe("KERNEL32.dll", function="ExitProcess"))
            (root / "notes.txt").write_text("PE 가 아니다", encoding="utf-8")
            rows, errors = build.pe_rows(str(root))
        self.assertEqual(errors, [])
        by_path = {row["path"]: row for row in rows}
        self.assertEqual(sorted(by_path), ["_internal/net.pyd", "_internal/plain.dll"], "확장자가 exe·dll·pyd 인 파일만 훑는다")
        self.assertEqual(by_path["_internal/net.pyd"]["imports"], ["ws2_32.dll"])
        self.assertEqual(by_path["_internal/plain.dll"]["imports"], ["kernel32.dll"])
        problems = rules.pe_problems(rows)
        self.assertTrue(any("_internal/net.pyd" in item and "ws2_32.dll" in item for item in problems), problems)
        self.assertFalse(any("_internal/plain.dll" in item for item in problems))

    def test_a_file_that_is_not_a_pe_is_reported_as_unreadable_not_skipped(self):
        build = support.load("build_ocr_addon")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "broken.pyd").write_bytes(b"MZ not really")
            rows, errors = build.pe_rows(folder)
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("broken.pyd", errors[0])


if __name__ == "__main__":
    unittest.main()
