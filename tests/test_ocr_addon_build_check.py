"""글자 읽기 추가 도구 빌드(`ocr_addon/build_ocr_addon.py`)의 **점검 관문**(검증 S 지적 SP-1·SP-11, 결정 D-512·D-526)을 빌드 없이 시험한다 — PyInstaller·진짜 pefile·진짜 모델이 없어도 CI 에서 돈다.

지키는 것:
  1) 단계 `all` 은 점검이 실패하면 거기서 멈춘다 — 정보 파일·zip 을 만들지 않고 종료 코드 1(예전에는 점검 실패를 버리고 zip 을 만든 뒤 0 으로 끝났다). 단계 순서와 각 단계 실패의 전파.
  2) 가져오기 표(가짜 pefile 로 흉내) — 정적·지연·묶음 가져오기의 네트워크 DLL 을 모두 잡는다. 네트워크 DLL 목록·허용 예외(`_internal` 바로 아래의 `_socket.pyd`·`select.pyd`·`python312.dll` 셋뿐)·금지 파일 이름·모델 기대값은 글자 그대로 못박는다
     (모델 기대값은 앱에 박은 값과 같아야 한다). 같은 이름 파일이 묶음 다른 곳에 있으면 예외가 아니다.
  3) `check()` 가 허용 예외 밖의 네트워크 DLL·금지 파일·모델 크기/해시 불일치·읽지 못한 PE·동결본 자가 점검 실패를 모두 실패(종료 값 1)로 친다.
"""
import contextlib
import hashlib
import importlib.util
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
sys.path.insert(0, str(ROOT / "src"))
BUILD = ROOT / "ocr_addon" / "build_ocr_addon.py"


def load_build():
    spec = importlib.util.spec_from_file_location("build_ocr_addon_check_under_test", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = load_build()

from chanceblog_desktop.service import ocr_addon as service  # noqa: E402

ALLOWED_ROWS = [("_internal/_socket.pyd", ("iphlpapi.dll", "ws2_32.dll")), ("_internal/python312.dll", ("ws2_32.dll",)), ("_internal/select.pyd", ("ws2_32.dll",))]


def row(path, net=()):
    return {"path": path, "bytes": 10, "n_imports": 3, "n_delay": 0, "net_dlls": list(net), "net_static": list(net), "net_delay": [], "imports": ["kernel32.dll"] + list(net)}


def sha(data):
    return hashlib.sha256(data).hexdigest()


class LiteralsTest(unittest.TestCase):
    def test_the_network_dll_list_is_pinned_literally(self):
        self.assertEqual(B.NET_DLLS, ["ws2_32.dll", "wsock32.dll", "mswsock.dll", "wininet.dll", "winhttp.dll", "iphlpapi.dll", "dnsapi.dll", "urlmon.dll", "wldap32.dll",
                                      "httpapi.dll", "netapi32.dll", "rasapi32.dll", "mpr.dll", "webservices.dll", "wlanapi.dll", "fwpuclnt.dll", "winnsi.dll", "nsi.dll", "dhcpcsvc.dll"])
        self.assertTrue(all(name == name.lower() for name in B.NET_DLLS), "비교는 소문자로 한다")

    def test_the_allowed_exceptions_are_exactly_three_python_files_directly_under_internal(self):
        self.assertEqual(B.PE_EXCEPTIONS, {"_socket.pyd", "select.pyd", "python312.dll"})
        self.assertEqual(B.PE_EXCEPTION_DIR, "_internal")

    def test_the_forbidden_names_are_pinned(self):
        self.assertEqual(B.FORBIDDEN_NAMES, [r"opencv_videoio_ffmpeg.*\.dll", r".*\.pem$", r".*\.crt$", r".*\.key$"])

    def test_the_models_the_build_expects_are_the_ones_built_into_the_app(self):
        self.assertEqual(B.MODEL_EXPECT, service.EMBEDDED_FILES, "빌드가 기대하는 모델·사전 크기·해시는 앱에 박은 값(신뢰의 뿌리)과 같아야 한다")


class NetOffendersTest(unittest.TestCase):
    def test_only_the_three_python_files_directly_under_internal_are_excused(self):
        rows = [row(path, net) for path, net in ALLOWED_ROWS]
        self.assertEqual(B.net_offenders(rows), [])

    def test_everything_else_with_a_network_import_is_an_offender(self):
        cases = ["_internal/_ssl.pyd", "_internal/libcrypto-3.dll", "_internal/_overlapped.pyd", "_internal/_multiprocessing.pyd", "ocr_worker.exe", "_internal/cv2/cv2.pyd", "_internal/onnxruntime/capi/onnxruntime.dll"]
        for path in cases:
            with self.subTest(path=path):
                self.assertEqual([r["path"] for r in B.net_offenders([row(path, ("ws2_32.dll",))])], [path])

    def test_a_file_of_the_excused_name_in_another_folder_is_not_excused(self):
        for path in ("_internal/sub/_socket.pyd", "select.pyd", "other/python312.dll", "_internal_x/_socket.pyd", "x/_internal/select.pyd", "_internal/lib/select.pyd"):
            with self.subTest(path=path):
                self.assertEqual([r["path"] for r in B.net_offenders([row(path, ("ws2_32.dll",))])], [path])

    def test_the_name_comparison_ignores_case_and_windows_separators(self):
        self.assertEqual(B.net_offenders([row("_internal/Python312.DLL", ("ws2_32.dll",)), row("_internal" + chr(92) + "_SOCKET.pyd", ("ws2_32.dll",))]), [])

    def test_rows_without_a_network_import_are_never_offenders(self):
        self.assertEqual(B.net_offenders([row("_internal/_ssl.pyd"), row("ocr_worker.exe"), {"path": "x.dll", "net_dlls": []}]), [])

    def test_the_result_keeps_the_original_rows_in_order(self):
        rows = [row("_internal/b.pyd", ("ws2_32.dll",)), row("_internal/select.pyd", ("ws2_32.dll",)), row("a.dll", ("wininet.dll",))]
        self.assertEqual([r["path"] for r in B.net_offenders(rows)], ["_internal/b.pyd", "a.dll"])


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
                rows, errors = B.pe_table(dst)
        by_path = {r["path"]: r for r in rows}
        self.assertEqual(sorted(by_path), ["_internal/clean.dll", "_internal/ext.pyd", "_internal/lib.dll", "ocr_worker.exe"], "exe·dll·pyd 만 본다")
        self.assertEqual((by_path["ocr_worker.exe"]["net_dlls"], by_path["ocr_worker.exe"]["net_static"], by_path["ocr_worker.exe"]["net_delay"]), (["ws2_32.dll"], ["ws2_32.dll"], []))
        self.assertEqual((by_path["_internal/lib.dll"]["net_dlls"], by_path["_internal/lib.dll"]["net_static"], by_path["_internal/lib.dll"]["net_delay"]), (["winhttp.dll"], [], ["winhttp.dll"]))
        self.assertEqual((by_path["_internal/ext.pyd"]["net_dlls"], by_path["_internal/ext.pyd"]["net_static"]), (["mswsock.dll"], []), "묶음 가져오기 표도 본다")
        self.assertEqual(by_path["_internal/clean.dll"]["net_dlls"], [])
        self.assertEqual([entry["path"] for entry in errors], ["_internal/bad.pyd"], "구문 분석에 실패한 파일은 오류 목록에 따로 간다")
        self.assertTrue(errors[0]["error"].startswith("ValueError"))

    def test_every_network_dll_name_in_the_list_is_noticed_as_a_static_import(self):
        names = list(B.NET_DLLS)
        spec = {"a.dll": {"static": names}}
        with tempfile.TemporaryDirectory() as dst:
            touch(dst, "a.dll")
            with mock.patch.dict(sys.modules, {"pefile": fake_pefile(spec)}):
                rows, errors = B.pe_table(dst)
        self.assertEqual((rows[0]["net_dlls"], errors), (sorted(names), []))


class CheckGateTest(unittest.TestCase):
    """`check()` — 가짜 가져오기 표·작은 가짜 모델로(모델 기대값은 시험 동안만 바꿔 끼운다)."""
    MODELS = {"models/det/inference.onnx": b"det-bytes", "models/rec/inference.onnx": b"rec-bytes-longer", "data/ppocrv5_korean_dict.txt": b"dict"}

    def run_check(self, rows=None, errors=(), extra=(), models=None, selftest=None):
        with tempfile.TemporaryDirectory() as out, contextlib.ExitStack() as stack:
            dst = os.path.join(out, "dist", "ocr_addon")
            for relative, data in (self.MODELS if models is None else models).items():
                touch(dst, relative, data)
            for relative in extra:
                touch(dst, relative)
            expect = {name: (len(data), sha(data)) for name, data in self.MODELS.items()}
            table = [row(path, net) for path, net in ALLOWED_ROWS] if rows is None else rows
            stack.enter_context(mock.patch.object(B, "MODEL_EXPECT", expect))
            stack.enter_context(mock.patch.object(B, "pe_table", return_value=(table, list(errors))))
            stack.enter_context(mock.patch.object(B, "log"))
            if selftest is not None:
                stack.enter_context(mock.patch.object(B.subprocess, "run", return_value=selftest))
            code = B.check(out, run_selftest=selftest is not None)
            result = json.loads(Path(out, "check_result.json").read_text(encoding="utf-8"))
            self.assertTrue(Path(out, "pe_imports_all.json").is_file())
        return code, result

    def test_a_clean_bundle_passes_and_the_result_file_says_so(self):
        code, result = self.run_check()
        self.assertEqual((code, result["ok"], result["problems"], result["pe"]["offenders"]), (0, True, [], []))
        self.assertEqual(result["pe"]["exceptions_allowed"], ["_socket.pyd", "python312.dll", "select.pyd"])
        self.assertTrue(result["model_dict_ok"])

    def test_a_network_import_outside_the_exceptions_fails_the_check(self):
        for path in ("ocr_worker.exe", "_internal/_ssl.pyd", "_internal/libcrypto-3.dll", "_internal/sub/_socket.pyd", "select.pyd"):
            with self.subTest(path=path):
                code, result = self.run_check(rows=[row(p, n) for p, n in ALLOWED_ROWS] + [row(path, ("ws2_32.dll",))])
                self.assertEqual(code, 1)
                self.assertFalse(result["ok"])
                self.assertIn(path, result["pe"]["offenders"])
                self.assertTrue(any("허용 예외 밖" in problem for problem in result["problems"]))

    def test_a_forbidden_file_fails_the_check(self):
        for relative in ("_internal/cv2/opencv_videoio_ffmpeg5000_64.dll", "_internal/certifi/cacert.pem", "x/server.key", "x/ca.crt", "_internal/rapidocr/models/default_det.onnx"):
            with self.subTest(relative=relative):
                code, result = self.run_check(extra=[relative])
                self.assertEqual(code, 1)
                self.assertTrue(any("금지 파일" in problem for problem in result["problems"]))
                self.assertTrue(any(relative.endswith(path.split("/")[-1]) for path in result["forbidden_files"]))

    def test_a_missing_or_changed_model_or_dictionary_fails_the_check(self):
        broken = {
            "missing": {name: data for name, data in self.MODELS.items() if name != "models/det/inference.onnx"},
            "other size": dict(self.MODELS, **{"models/rec/inference.onnx": b"rec"}),
            "same size other bytes": dict(self.MODELS, **{"data/ppocrv5_korean_dict.txt": b"DICT"}),
        }
        for label, models in broken.items():
            with self.subTest(label=label):
                code, result = self.run_check(models=models)
                self.assertEqual(code, 1)
                self.assertFalse(result["model_dict_ok"])
                self.assertTrue(any("모델·사전" in problem for problem in result["problems"]))

    def test_a_file_whose_imports_could_not_be_read_fails_the_check(self):
        code, result = self.run_check(errors=[{"path": "_internal/x.pyd", "error": "PEFormatError: x"}])
        self.assertEqual(code, 1)
        self.assertTrue(any("읽지 못한 파일" in problem for problem in result["problems"]))

    def test_the_frozen_worker_self_check_must_pass_when_it_is_run(self):
        good = types.SimpleNamespace(returncode=0, stdout=b'{"ok": true}' + chr(10).encode("ascii"), stderr=b"")
        self.assertEqual(self.run_check(selftest=good)[0], 0)
        for label, done in (("exit 1", types.SimpleNamespace(returncode=1, stdout=b'{"ok": true}', stderr=b"boom")), ("ok false", types.SimpleNamespace(returncode=0, stdout=b'{"ok": false}', stderr=b"")),
                            ("no json", types.SimpleNamespace(returncode=0, stdout=b"hello", stderr=b"")), ("silent", types.SimpleNamespace(returncode=0, stdout=b"", stderr=b""))):
            with self.subTest(label=label):
                code, result = self.run_check(selftest=done)
                self.assertEqual(code, 1)
                self.assertTrue(any("--selftest 실패" in problem for problem in result["problems"]))


class MainFlowTest(unittest.TestCase):
    """단계 함수를 기록용 가짜로 바꿔 흐름만 본다 — 아무것도 만들지 않는다."""

    def run_main(self, *args, check_code=0, freeze_code=0, assemble_code=0, info_code=0):
        calls = []

        def recorder(name, value):
            def function(*a, **k):
                calls.append((name, a[1:] if name == "check" else ()))
                return value
            return function
        with tempfile.TemporaryDirectory() as out, contextlib.ExitStack() as stack:
            for name, value in (("freeze", freeze_code), ("assemble", assemble_code), ("check", check_code), ("make_info", info_code), ("make_zip", 0)):
                stack.enter_context(mock.patch.object(B, name, recorder({"make_info": "info", "make_zip": "zip"}.get(name, name), value)))
            stack.enter_context(mock.patch.object(B, "remove_unused", recorder("remove", None)))
            stack.enter_context(mock.patch.object(B, "log"))
            stack.enter_context(mock.patch.object(sys, "argv", ["build_ocr_addon.py", *args, "--out-dir", out]))
            code = B.main()
        return code, [name for name, _extra in calls], calls

    def test_all_runs_every_stage_in_order_and_ends_with_zero_when_everything_passes(self):
        code, names, _calls = self.run_main("all")
        self.assertEqual((code, names), (0, ["freeze", "assemble", "remove", "check", "info", "zip"]))

    def test_all_stops_at_a_failed_check_and_makes_neither_the_info_file_nor_the_zip(self):
        code, names, _calls = self.run_main("all", check_code=1)
        self.assertEqual(code, 1)
        self.assertEqual(names, ["freeze", "assemble", "remove", "check"])
        self.assertNotIn("zip", names)
        self.assertNotIn("info", names)

    def test_a_failed_freeze_or_assemble_stops_everything_after_it(self):
        self.assertEqual(self.run_main("all", freeze_code=1)[:2], (1, ["freeze"]))
        self.assertEqual(self.run_main("all", assemble_code=1)[:2], (1, ["freeze", "assemble"]))

    def test_a_failed_info_stage_stops_before_the_zip(self):
        code, names, _calls = self.run_main("all", info_code=1)
        self.assertEqual((code, names), (1, ["freeze", "assemble", "remove", "check", "info"]))

    def test_the_check_stage_alone_returns_its_own_code(self):
        self.assertEqual(self.run_main("check", check_code=1)[:2], (1, ["check"]))
        self.assertEqual(self.run_main("check", check_code=0)[:2], (0, ["check"]))

    def test_single_stages_run_only_themselves(self):
        self.assertEqual(self.run_main("info")[:2], (0, ["info"]))
        self.assertEqual(self.run_main("zip")[:2], (0, ["zip"]))
        self.assertEqual(self.run_main("remove")[:2], (0, ["remove"]))

    def test_no_remove_skips_the_removal_and_no_selftest_is_passed_on_to_the_check(self):
        _code, names, calls = self.run_main("all", "--no-remove", "--no-selftest")
        self.assertEqual(names, ["freeze", "assemble", "check", "info", "zip"])
        self.assertEqual([extra for name, extra in calls if name == "check"], [(False,)])
        _code, _names, calls = self.run_main("all")
        self.assertEqual([extra for name, extra in calls if name == "check"], [(True,)])


if __name__ == "__main__":
    unittest.main()
