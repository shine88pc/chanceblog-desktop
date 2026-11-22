"""글자 읽기 추가 도구 빌드(`ocr_addon/build_ocr_addon.py`)의 **점검 관문**(검증 S 지적 SP-1·SP-11, 결정 D-512·D-526)을 빌드 없이 시험한다 — PyInstaller·진짜 pefile·진짜 모델이 없어도 CI 에서 돈다.

지키는 것:
  1) 단계 `all` 은 점검이 실패하면 거기서 멈춘다 — 정보 파일·zip 을 만들지 않고 종료 코드 1(예전에는 점검 실패를 버리고 zip 을 만든 뒤 0 으로 끝났다). 단계 순서와 각 단계 실패의 전파.
  2) 가져오기 표(가짜 pefile 로 흉내) — 정적·지연·묶음 가져오기의 네트워크 DLL 을 모두 잡는다. 네트워크 DLL 목록·허용 예외(`_internal` 바로 아래의 `_socket.pyd`·`select.pyd`·`python312.dll` 셋뿐)·금지 파일 이름·모델 기대값은 글자 그대로 못박는다
     (모델 기대값은 앱에 박은 값과 같아야 한다). 같은 이름 파일이 묶음 다른 곳에 있으면 예외가 아니다.
  3) `check()` 가 허용 예외 밖의 네트워크 DLL·금지 파일·모델 크기/해시 불일치·읽지 못한 PE·동결본 자가 점검 실패를 모두 실패(종료 값 1)로 친다.

[합친 뒤 이식 — D 를 B1 최종 위로 얹을 때] 이 파일은 B1 이 a 단계 스크립트의 안쪽 이름(`NET_DLLS`·`net_offenders`·`pe_table`·`check(out, run_selftest)` 의 정수 반환·`--no-remove`·`--no-selftest`)에 걸어 두었다. 합친 스크립트는 D 의 구조(규칙은
`build_rules.py` 순수 함수, `check(out)` 은 (통과 여부, 결과), 단계가 멈추면 BuildError 와 종료 코드 2, 점검을 끄는 옵션 없음 — 결정 D-530 ④)라서 같은 **뜻**을 합친 이름으로 다시 걸었다. 시험 이름과 확인 내용은 그대로 두고 바뀐 것은 아래다.
  - 상수 시험은 값을 글자 그대로 못박는 방식을 지키되 합친 쪽 이름(`B.rules.…`)과 표기(예외는 `_internal/` 를 붙인 경로 셋)로 — 금지 이름 표기는 `re.fullmatch` 라 `$` 가 없다.
  - 허용 예외 시험(NetOffenders)은 B1 의 `net_offenders` 대신 규칙 함수 `rules.pe_problems` 의 문제 글에서 걸린 경로를 읽는 어댑터(`offenders`)로 — 점검 대상에 꼭 있어야 하는 두 파일(작업자 exe·python312.dll)은 어댑터가 채운다.
  - 가져오기 표 읽기 시험(PeTable)은 `pe_table` 대신 `pe_rows` 로 — 줄 모양이 `imports·delay·bound`(소문자·중복 없음)이고 못 읽은 파일은 '경로 (오류 이름)' 글이다.
  - `check()` 시험(CheckGate)은 D 쪽 읽기 함수들(가져오기 표·자가 점검·모듈 목록·DLL 출처)을 가짜로 끼우고 `(통과 여부, 결과)` 를 본다. 통과 기준의 자가 점검 결과는 D 의 R4(칸 하나하나 다시 봄)가 더 엄격해서 '{"ok": true}' 한 칸짜리가 아니라 온전한 결과를 쓴다.
  - 흐름 시험(MainFlow)은 단계가 멈추면 BuildError(종료 코드 2)이고 점검 실패만 종료 코드 1 이다(B1 은 둘 다 1) — 둘 다 0 이 아니고 뒤 단계가 돌지 않는 것은 같다. 새 단계 `notices` 가 `remove` 와 `check` 사이에 낀다(확인 030 ②).
  - **뒤집힌 것 하나**: `test_no_remove_skips_the_removal_and_no_selftest_is_passed_on_to_the_check` — B1 은 두 옵션이 있고 동작하는 것을 못박았으나 D 가 결정 D-530 ④ 로 점검을 끄는 길을 없앴다(옵션 없음). 그래서 옵션이 거절되고 `all` 이 언제나 제거·점검을 거치는 것을 못박는 시험으로 바꿨다.
"""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
import ocr_build_support as support  # noqa: E402

B = support.load("build_ocr_addon")                      # 합친 스크립트(D 의 시험들과 같은 모듈 — 불러오는 동안만 ocr_addon 폴더를 import 경로에 둔다)
rules = B.rules

from chanceblog_desktop.service import ocr_addon as service  # noqa: E402

ALLOWED_ROWS = [("_internal/_socket.pyd", ("iphlpapi.dll", "ws2_32.dll")), ("_internal/python312.dll", ("ws2_32.dll",)), ("_internal/select.pyd", ("ws2_32.dll",))]
REQUIRED_PLAIN = [("ocr_worker.exe", ())]                # 점검 대상에 꼭 있어야 하는 파일 중 네트워크를 가져오지 않는 것(규칙 PE_REQUIRED) — python312.dll 은 허용 예외 줄에 있다
GOOD_REPORT = {"frozen": True, "guard_active": True, "negative_control": [{"blocked_and_counted": True}] * 5, "negative_control_attempts": 5, "negative_control_recent_targets_only_test_addresses": True,
               "loopback_not_counted": True, "files_ok": True, "imports": {"requests": "0+offline-stub"}, "imports_failed": [], "selfcheck_ok": True, "guard_attempts_during_normal_read": 0, "ok": True,
               "imports_optional": {name: "없음(묶음에 들어 있지 않다) x" for name in ("ssl", "urllib3", "certifi", "asyncio", "multiprocessing")}}


def row(path, net=()):
    return {"path": path, "bytes": 10, "n_imports": 3, "n_delay": 0, "net_dlls": list(net), "net_static": list(net), "net_delay": [], "imports": ["kernel32.dll"] + list(net)}


def sha(data):
    return hashlib.sha256(data).hexdigest()


class LiteralsTest(unittest.TestCase):
    def test_the_network_dll_list_is_pinned_literally(self):
        self.assertEqual(list(rules.NET_DLLS), ["ws2_32.dll", "wsock32.dll", "mswsock.dll", "wininet.dll", "winhttp.dll", "iphlpapi.dll", "dnsapi.dll", "urlmon.dll", "wldap32.dll",
                                                "httpapi.dll", "netapi32.dll", "rasapi32.dll", "mpr.dll", "webservices.dll", "wlanapi.dll", "fwpuclnt.dll", "winnsi.dll", "nsi.dll", "dhcpcsvc.dll"])
        self.assertTrue(all(name == name.lower() for name in rules.NET_DLLS), "비교는 소문자로 한다")

    def test_the_allowed_exceptions_are_exactly_three_python_files_directly_under_internal(self):
        self.assertEqual({os.path.basename(path) for path in rules.PE_EXCEPTIONS}, {"_socket.pyd", "select.pyd", "python312.dll"})
        self.assertEqual({os.path.dirname(path) for path in rules.PE_EXCEPTIONS}, {"_internal"})
        self.assertEqual(len(rules.PE_EXCEPTIONS), 3)

    def test_the_forbidden_names_are_pinned(self):
        self.assertEqual(list(rules.FORBIDDEN_FILES), [r"opencv_videoio_ffmpeg.*\.dll", r".*\.pem", r".*\.crt", r".*\.key"], "합친 쪽은 re.fullmatch 로 이름 전체를 맞춘다 — B1 의 끝 표시($)가 없는 대신")

    def test_the_models_the_build_expects_are_the_ones_built_into_the_app(self):
        _lock, expected = B.load_lock()
        self.assertEqual(expected, service.EMBEDDED_FILES, "빌드가 기대하는 모델·사전 크기·해시는 앱에 박은 값(신뢰의 뿌리)과 같아야 한다")


def with_required(rows):
    """규칙 R1 은 점검 대상에 작업자 exe·python312.dll 이 꼭 있어야 한다('못 훑음' 방지). B1 의 net_offenders 는 그런 요구가 없어서, 시험이 준 줄에 없으면 네트워크를 가져오지 않는 줄(python312.dll 은 허용 예외라 ws2_32 하나)로 채운다."""
    have = {rules.norm_path(item["path"]) for item in rows}
    extra = [row(path, ("ws2_32.dll",) if path == "_internal/python312.dll" else ()) for path in rules.PE_REQUIRED if path not in have]
    return list(rows) + extra


def offenders(rows):
    """B1 의 net_offenders 자리 — 규칙 함수 rules.pe_problems 가 '허용 예외 밖' 으로 친 파일 경로들(줄 순서대로)."""
    return [item.split(": ", 1)[1].rsplit(" (", 1)[0] for item in rules.pe_problems(with_required(rows), ()) if "허용 예외 밖" in item]


class NetOffendersTest(unittest.TestCase):
    def test_only_the_three_python_files_directly_under_internal_are_excused(self):
        rows = [row(path, net) for path, net in ALLOWED_ROWS]
        self.assertEqual(offenders(rows), [])
        self.assertEqual(rules.pe_problems(with_required(rows), ()), [], "허용된 셋과 꼭 있어야 하는 파일만 있으면 문제가 하나도 없다")

    def test_everything_else_with_a_network_import_is_an_offender(self):
        cases = ["_internal/_ssl.pyd", "_internal/libcrypto-3.dll", "_internal/_overlapped.pyd", "_internal/_multiprocessing.pyd", "ocr_worker.exe", "_internal/cv2/cv2.pyd", "_internal/onnxruntime/capi/onnxruntime.dll"]
        for path in cases:
            with self.subTest(path=path):
                self.assertEqual(offenders([row(path, ("ws2_32.dll",))]), [path])

    def test_a_file_of_the_excused_name_in_another_folder_is_not_excused(self):
        for path in ("_internal/sub/_socket.pyd", "select.pyd", "other/python312.dll", "_internal_x/_socket.pyd", "x/_internal/select.pyd", "_internal/lib/select.pyd"):
            with self.subTest(path=path):
                self.assertEqual(offenders([row(path, ("ws2_32.dll",))]), [path])

    def test_the_name_comparison_ignores_case_and_windows_separators(self):
        rows = [row("_internal/Python312.DLL", ("ws2_32.dll",)), row("_internal" + chr(92) + "_SOCKET.pyd", ("ws2_32.dll",))]
        self.assertEqual(offenders(rows), [])
        self.assertEqual(rules.pe_problems(with_required(rows), ()), [])

    def test_rows_without_a_network_import_are_never_offenders(self):
        rows = [row("_internal/_ssl.pyd"), row("ocr_worker.exe"), {"path": "x.dll", "net_dlls": []}]
        self.assertEqual(offenders(rows), [])
        self.assertEqual(rules.pe_problems(with_required(rows), ()), [])

    def test_the_result_keeps_the_original_rows_in_order(self):
        rows = [row("_internal/b.pyd", ("ws2_32.dll",)), row("_internal/select.pyd", ("ws2_32.dll",)), row("a.dll", ("wininet.dll",))]
        self.assertEqual(offenders(rows), ["_internal/b.pyd", "a.dll"])


class FakeImport:
    def __init__(self, dll):
        self.dll = dll


class FakeBound:
    def __init__(self, name):
        self.name = name


def fake_pefile(spec):
    """진짜 pefile 대신 — spec: {파일 기본 이름: {"static": […], "delay": […], "bound": […]} 또는 예외 클래스}."""
    module = types.ModuleType("pefile")
    module.DIRECTORY_ENTRY = {"IMAGE_DIRECTORY_ENTRY_IMPORT": 1, "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT": 13, "IMAGE_DIRECTORY_ENTRY_BOUND_IMPORT": 11}

    class PE:
        def __init__(self, path, fast_load=False):
            entry = spec[os.path.basename(path)]
            if isinstance(entry, type) and issubclass(entry, Exception):
                raise entry("가짜 구문 분석 실패")
            self.DIRECTORY_ENTRY_IMPORT = [FakeImport(name.encode("ascii")) for name in entry.get("static", ())]
            self.DIRECTORY_ENTRY_DELAY_IMPORT = [FakeImport(name.encode("ascii")) for name in entry.get("delay", ())]
            self.DIRECTORY_ENTRY_BOUND_IMPORT = [FakeBound(name.encode("ascii")) for name in entry.get("bound", ())]

        def parse_data_directories(self, directories=None):
            pass

        def close(self):
            pass
    module.PE = PE
    return module


def touch(folder, relative, data=b"x"):
    path = os.path.join(folder, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


class PeTableTest(unittest.TestCase):
    def test_static_delay_and_bound_network_imports_are_all_found_and_nothing_else_is_listed(self):
        spec = {"ocr_worker.exe": {"static": ["KERNEL32.dll", "WS2_32.dll"]}, "lib.dll": {"static": ["kernel32.dll"], "delay": ["WinHTTP.dll"]}, "ext.pyd": {"bound": ["MSWSOCK.dll"], "static": ["kernel32.dll"]},
                "clean.dll": {"static": ["kernel32.dll", "user32.dll"]}, "bad.pyd": ValueError}
        with tempfile.TemporaryDirectory() as dst:
            for name in spec:
                touch(dst, "_internal/" + name if name != "ocr_worker.exe" else name)
            touch(dst, "readme.txt")
            touch(dst, "data/model.onnx")
            with mock.patch.dict(sys.modules, {"pefile": fake_pefile(spec)}):
                rows, errors = B.pe_rows(dst)
        by_path = {r["path"]: r for r in rows}
        self.assertEqual(sorted(by_path), ["_internal/clean.dll", "_internal/ext.pyd", "_internal/lib.dll", "ocr_worker.exe"], "exe·dll·pyd 만 본다")
        self.assertEqual((rules.net_imports(by_path["ocr_worker.exe"]), by_path["ocr_worker.exe"]["imports"], by_path["ocr_worker.exe"]["delay"]), (["ws2_32.dll"], ["kernel32.dll", "ws2_32.dll"], []))
        self.assertEqual((rules.net_imports(by_path["_internal/lib.dll"]), by_path["_internal/lib.dll"]["imports"], by_path["_internal/lib.dll"]["delay"]), (["winhttp.dll"], ["kernel32.dll"], ["winhttp.dll"]))
        self.assertEqual((rules.net_imports(by_path["_internal/ext.pyd"]), by_path["_internal/ext.pyd"]["imports"], by_path["_internal/ext.pyd"]["bound"]), (["mswsock.dll"], ["kernel32.dll"], ["mswsock.dll"]), "묶음 가져오기 표도 본다")
        self.assertEqual(rules.net_imports(by_path["_internal/clean.dll"]), [])
        self.assertEqual(errors, ["_internal/bad.pyd (ValueError)"], "구문 분석에 실패한 파일은 오류 목록에 따로 간다(경로와 오류 이름)")
        self.assertTrue(any("읽지 못한 파일" in item for item in rules.pe_problems(rows, errors)), "읽지 못한 파일은 R1 이 문제로 센다")

    def test_every_network_dll_name_in_the_list_is_noticed_as_a_static_import(self):
        names = list(rules.NET_DLLS)
        spec = {"a.dll": {"static": names}}
        with tempfile.TemporaryDirectory() as dst:
            touch(dst, "a.dll")
            with mock.patch.dict(sys.modules, {"pefile": fake_pefile(spec)}):
                rows, errors = B.pe_rows(dst)
        self.assertEqual((rules.net_imports(rows[0]), errors), (sorted(names), []))


class CheckGateTest(unittest.TestCase):
    """`check()` — 가짜 가져오기 표·작은 가짜 모델·고지 산출물로(모델 기대값과 묶음을 읽는 함수들은 시험 동안만 바꿔 끼운다). 결과는 (통과 여부, 결과 파일 내용)."""
    MODELS = {"models/det/inference.onnx": b"det-bytes", "models/rec/inference.onnx": b"rec-bytes-longer", "data/ppocrv5_korean_dict.txt": b"dict"}
    NOTICES = {"THIRD_PARTY_NOTICES.txt": b"GEOS LGPL-2.1", "licenses/shapely/LICENSE_GEOS": b"LGPL text", "licenses/numpy/LICENSE.txt": b"BSD"}      # notices 단계가 점검 앞에서 만든 것

    def run_check(self, rows=None, errors=(), extra=(), models=None, selftest=None):
        with tempfile.TemporaryDirectory() as out, contextlib.ExitStack() as stack:
            dst = os.path.join(out, "dist", "ocr")
            for relative, data in (self.MODELS if models is None else models).items():
                touch(dst, relative, data)
            touch(dst, "ocr_worker.exe", b"worker")                      # 규칙 R2 는 작업자 exe 가 묶음에 꼭 있어야 한다고 본다
            for relative, data in self.NOTICES.items():
                touch(dst, relative, data)
            for relative in extra:
                touch(dst, relative)
            expect = {name: (len(data), sha(data)) for name, data in self.MODELS.items()}
            table = [row(path, net) for path, net in ALLOWED_ROWS + REQUIRED_PLAIN] if rows is None else rows
            real = B.import_packaging()
            fake_bp = types.SimpleNamespace(pc=real.pc, check_binary_origins=lambda toc: [])
            versions = {pin["name"]: pin["version"] for pin in rules.parse_lock(support.read("ocr_addon/requirements-ocr.lock"))}
            stack.enter_context(mock.patch.object(B, "load_lock", return_value=({"schema": 1, "files": []}, expect)))
            stack.enter_context(mock.patch.object(B, "import_packaging", return_value=fake_bp))
            stack.enter_context(mock.patch.object(B, "pe_rows", return_value=(table, list(errors))))
            stack.enter_context(mock.patch.object(B, "bundled_modules", return_value={"cv2", "numpy", "requests"}))
            stack.enter_context(mock.patch.object(B, "installed_version", side_effect=lambda name: versions.get(name)))
            stack.enter_context(mock.patch.object(B, "log"))
            if selftest is None:
                stack.enter_context(mock.patch.object(B, "run_selftest", return_value=(0, GOOD_REPORT, [], 1.5, "")))
            else:
                stack.enter_context(mock.patch.object(B.subprocess, "run", return_value=selftest))
            ok, returned = B.check(out)
            saved = json.loads(Path(out, "check_result.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["ok"], ok, "결과 파일이 돌려준 통과 여부와 같은 말을 한다")
            self.assertEqual(saved["problems"], returned["problems"])
            self.assertTrue(Path(out, "pe_imports_all.json").is_file())
        return ok, saved

    def test_a_clean_bundle_passes_and_the_result_file_says_so(self):
        ok, result = self.run_check()
        self.assertEqual((ok, result["ok"], result["problems"]), (True, True, []))
        self.assertEqual((result["pe_files_checked"], result["selftest_exit"]), (len(ALLOWED_ROWS) + len(REQUIRED_PLAIN), 0))
        self.assertTrue(result["selftest"]["ok"])

    def test_a_network_import_outside_the_exceptions_fails_the_check(self):
        for path in ("ocr_worker.exe", "_internal/_ssl.pyd", "_internal/libcrypto-3.dll", "_internal/sub/_socket.pyd", "select.pyd"):
            with self.subTest(path=path):
                ok, result = self.run_check(rows=[row(p, n) for p, n in ALLOWED_ROWS + REQUIRED_PLAIN] + [row(path, ("ws2_32.dll",))])
                self.assertFalse(ok)
                self.assertFalse(result["ok"])
                self.assertTrue(any("허용 예외 밖" in problem and path in problem for problem in result["problems"]), result["problems"])

    def test_a_forbidden_file_fails_the_check(self):
        for relative, word in (("_internal/cv2/opencv_videoio_ffmpeg5000_64.dll", "묶음에 있으면 안 되는 파일"), ("_internal/certifi/cacert.pem", "묶음에 있으면 안 되는 파일"), ("x/server.key", "묶음에 있으면 안 되는 파일"),
                               ("x/ca.crt", "묶음에 있으면 안 되는 파일"), ("_internal/rapidocr/models/default_det.onnx", "기본 모델")):
            with self.subTest(relative=relative):
                ok, result = self.run_check(extra=[relative])
                self.assertFalse(ok)
                self.assertTrue(any(word in problem and relative in problem for problem in result["problems"]), result["problems"])

    def test_a_missing_or_changed_model_or_dictionary_fails_the_check(self):
        broken = {
            "missing": {name: data for name, data in self.MODELS.items() if name != "models/det/inference.onnx"},
            "other size": dict(self.MODELS, **{"models/rec/inference.onnx": b"rec"}),
            "same size other bytes": dict(self.MODELS, **{"data/ppocrv5_korean_dict.txt": b"DICT"}),
        }
        for label, models in broken.items():
            with self.subTest(label=label):
                ok, result = self.run_check(models=models)
                self.assertFalse(ok)
                self.assertTrue(any("R2 모델·사전" in problem for problem in result["problems"]), result["problems"])

    def test_a_file_whose_imports_could_not_be_read_fails_the_check(self):
        ok, result = self.run_check(errors=["_internal/x.pyd (PEFormatError)"])
        self.assertFalse(ok)
        self.assertTrue(any("읽지 못한 파일" in problem and "_internal/x.pyd" in problem for problem in result["problems"]), result["problems"])

    def test_the_frozen_worker_self_check_must_pass_when_it_is_run(self):
        good = types.SimpleNamespace(returncode=0, stdout=json.dumps(GOOD_REPORT).encode("utf-8") + chr(10).encode("ascii"), stderr=b"")
        self.assertEqual(self.run_check(selftest=good)[0], True)
        for label, done in (("exit 1", types.SimpleNamespace(returncode=1, stdout=json.dumps(GOOD_REPORT).encode("utf-8"), stderr=b"boom")),
                            ("ok false", types.SimpleNamespace(returncode=0, stdout=json.dumps(dict(GOOD_REPORT, ok=False)).encode("utf-8"), stderr=b"")),
                            ("one box only", types.SimpleNamespace(returncode=0, stdout=b'{"ok": true}', stderr=b"")),
                            ("no json", types.SimpleNamespace(returncode=0, stdout=b"hello", stderr=b"")), ("silent", types.SimpleNamespace(returncode=0, stdout=b"", stderr=b""))):
            with self.subTest(label=label):
                ok, result = self.run_check(selftest=done)
                self.assertFalse(ok)
                self.assertTrue(any("R4 --selftest" in problem for problem in result["problems"]), result["problems"])


class MainFlowTest(unittest.TestCase):
    """단계 함수를 기록용 가짜로 바꿔 흐름만 본다 — 아무것도 만들지 않는다. 합친 흐름: freeze · assemble · remove · notices · check · info · zip (점검에 걸리면 info·zip 은 돌지 않는다)."""
    ORDER = ["freeze", "assemble", "remove", "notices", "check", "info", "zip"]
    STATE = {"commit": "0123456789abcdef0123456789abcdef01234567", "epoch": 1794873600, "epoch_from": "git commit", "committed_utc": "2026-11-17T00:00:00Z", "clean": True, "dirty_count": 0}

    def run_main(self, *args, check_ok=True, fail_at=None):
        calls = []

        def recorder(name, value=None):
            def function(*a, **k):
                calls.append((name, a[1:] if name == "check" else ()))
                if name == fail_at:
                    raise B.BuildError("단계 %s 가 멈췄다" % name)
                return value
            return function
        with tempfile.TemporaryDirectory() as out, contextlib.ExitStack() as stack:
            if args[0] in ("info", "zip"):                               # 이 둘만 따로 부를 때는 통과한 점검 결과 파일이 있어야 하고, zip 은 앞서 만든 정보 파일을 읽는다
                Path(out, "check_result.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            if args[0] == "zip":
                touch(os.path.join(out, "dist", "ocr"), "OCR_INFO.json", b"{}")
            extra = ["--models-dir", out] if args[0] in ("all", "assemble") else []
            for name, value in (("freeze", None), ("assemble", None), ("remove_unused", None), ("write_notices", None), ("check", (check_ok, {})), ("make_info", {"name": "x"}), ("make_zip", None)):
                stack.enter_context(mock.patch.object(B, name, recorder({"remove_unused": "remove", "write_notices": "notices", "make_info": "info", "make_zip": "zip"}.get(name, name), value)))
            stack.enter_context(mock.patch.object(B, "source_state", return_value=dict(self.STATE)))
            stack.enter_context(mock.patch.object(B, "log"))
            stack.enter_context(mock.patch.object(sys, "argv", ["build_ocr_addon.py", *args, "--out-dir", out, *extra]))
            with contextlib.redirect_stderr(io.StringIO()):
                code = B.main()
        return code, [name for name, _extra in calls], calls

    def test_all_runs_every_stage_in_order_and_ends_with_zero_when_everything_passes(self):
        code, names, _calls = self.run_main("all")
        self.assertEqual((code, names), (0, self.ORDER))

    def test_all_stops_at_a_failed_check_and_makes_neither_the_info_file_nor_the_zip(self):
        code, names, _calls = self.run_main("all", check_ok=False)
        self.assertEqual(code, 1)
        self.assertEqual(names, ["freeze", "assemble", "remove", "notices", "check"])
        self.assertNotIn("zip", names)
        self.assertNotIn("info", names)

    def test_a_failed_freeze_or_assemble_stops_everything_after_it(self):
        self.assertEqual(self.run_main("all", fail_at="freeze")[:2], (2, ["freeze"]))
        self.assertEqual(self.run_main("all", fail_at="assemble")[:2], (2, ["freeze", "assemble"]))

    def test_a_failed_info_stage_stops_before_the_zip(self):
        code, names, _calls = self.run_main("all", fail_at="info")
        self.assertEqual((code, names), (2, ["freeze", "assemble", "remove", "notices", "check", "info"]))

    def test_the_check_stage_alone_returns_its_own_code(self):
        self.assertEqual(self.run_main("check", check_ok=False)[:2], (1, ["check"]))
        self.assertEqual(self.run_main("check", check_ok=True)[:2], (0, ["check"]))

    def test_single_stages_run_only_themselves(self):
        self.assertEqual(self.run_main("info")[:2], (0, ["info"]))
        self.assertEqual(self.run_main("zip")[:2], (0, ["zip"]))
        self.assertEqual(self.run_main("remove")[:2], (0, ["remove"]))
        self.assertEqual(self.run_main("notices")[:2], (0, ["notices"]))

    def test_no_remove_skips_the_removal_and_no_selftest_is_passed_on_to_the_check(self):
        """뒤집힌 시험(결정 D-530 ④) — B1 은 두 옵션이 동작하는 것을 못박았으나 합친 스크립트에는 점검·제거를 끄는 길이 없다: 두 옵션은 거절되고 `all` 은 언제나 제거·점검을 거친다."""
        for flag in ("--no-remove", "--no-selftest"):
            with self.subTest(flag=flag):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                    self.run_main("all", flag)
                self.assertEqual(stop.exception.code, 2, "알 수 없는 옵션은 인자 해석이 거절한다")
        _code, names, calls = self.run_main("all")
        self.assertEqual(names, self.ORDER, "제거도 점검도 건너뛰지 않는다")
        self.assertEqual([extra for name, extra in calls if name == "check"], [()], "점검은 끄는 칸 없이 묶음 폴더 하나만 받는다")


if __name__ == "__main__":
    unittest.main()
