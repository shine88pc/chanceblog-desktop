"""`update/apply.py`·`update/install_kind.py` 시험(UPDATE 설계서 3-8, v1update U-2) — 적용 어댑터의 **빈 틀**과 설치 종류 가르기.

지키는 것:
  1) 어댑터의 `apply` 첫 문장이 스위치 관문(`capabilities.require_update_apply`)이다 — 꺼져 있으면 `UPDATE_DISABLED` 로 `_apply`(설치 도구를 띄울 자리)를 한 번도 부르기 전에 끝난다. 하위 클래스가 `_apply` 만 채워도 이 관문은 빠지지 않는다.
  2) 휴대용·소스 실행·모르는 종류는 `UPDATE_NOT_INSTALLED_KIND`, 설치형(velopack·inno)은 어댑터가 아직 없어 `UPDATE_APPLY_FAILED`(이유: 어댑터 없음)로 거절한다 — 아무것도 실행하지 않는다.
  3) **`update/` 패키지 어디에도 설치 도구를 띄우거나 바깥과 닿는 코드가 없다**(`subprocess`·`os.system`·`Popen`·`socket`·`http`·`ssl`·`urllib` 의 접속·`webbrowser`·`ctypes` 가져오기 0 — `source.py` 가 `net/` 틀을 늦게 가져오는 것 말고는).
  4) 설치 종류는 파일이 있는지만 본다(묶음이 아니면 소스, 묶음이면 `Update.exe`+`sq.version` → velopack, `unins000.exe` → inno, 그 밖 휴대용). 어떤 입력에도 예외 없이 닫는 쪽(휴대용)이다.
네트워크·하위 프로세스 없이 돈다.
"""
import ast
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import capability_support as cap  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.update import apply, install_kind  # noqa: E402

UPDATE = ROOT / "src" / "chanceblog_desktop" / "update"
CALL = dict(from_version="1.0.0", to_version="1.0.1")


class RecordingAdapter(apply.ApplyAdapter):
    """시험용 가짜 어댑터 — `_apply` 가 불렸는지만 기록한다(설치 도구를 띄우지 않는다)."""
    kind = "velopack"

    def __init__(self):
        self.applied = []

    def _apply(self, staged, *, from_version, to_version, recovery):
        self.applied.append((staged, from_version, to_version, recovery))
        return "handed-off"


class GateTest(unittest.TestCase):
    def tearDown(self):
        cap.switch_off("UPDATE_APPLY")

    def test_with_the_switch_off_the_apply_hook_is_never_reached(self):
        adapter = RecordingAdapter()
        with self.assertRaises(AppError) as caught:
            adapter.apply({"files": []}, **CALL)
        self.assertEqual((caught.exception.code, caught.exception.slots), ("UPDATE_DISABLED", {"작업": "업데이트 설치"}))
        self.assertEqual(adapter.applied, [])
        for kind in ("portable", "source", "", "velopack", "inno"):
            with self.assertRaises(AppError) as caught:
                apply.adapter_for(kind).apply(None, **CALL)
            self.assertEqual(caught.exception.code, "UPDATE_DISABLED", kind)

    def test_with_the_switch_on_a_filled_in_adapter_runs_once_and_returns_its_value(self):
        cap.switch_on("UPDATE_APPLY")
        adapter = RecordingAdapter()
        self.assertEqual(adapter.apply("S", **CALL, recovery=True), "handed-off")
        self.assertEqual(adapter.applied, [("S", "1.0.0", "1.0.1", True)])

    def test_the_first_statement_of_apply_is_the_gate_and_subclasses_cannot_override_it_by_accident(self):
        tree = ast.parse((UPDATE / "apply.py").read_text(encoding="utf-8"))
        klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ApplyAdapter")
        function = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == "apply")
        body = [node for node in function.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        self.assertEqual(ast.unparse(body[0]), "capabilities.require_update_apply('업데이트 설치')")
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name != "ApplyAdapter":
                self.assertNotIn("apply", [item.name for item in node.body if isinstance(item, ast.FunctionDef)], f"{node.name} 가 apply 를 덮어쓴다 — `_apply` 만 채운다")

    def test_look_alike_true_values_do_not_open_the_gate(self):
        for value in (1, "yes", "True", [1]):
            with mock.patch("chanceblog_desktop.capabilities.UPDATE_APPLY", value):
                with self.assertRaises(AppError):
                    RecordingAdapter().apply(None, **CALL)


class AdapterChoiceTest(unittest.TestCase):
    def setUp(self):
        cap.switch_on("UPDATE_APPLY")
        self.addCleanup(cap.switch_off, "UPDATE_APPLY")

    def test_portable_source_and_unknown_kinds_are_refused_as_not_installed(self):
        for kind in ("portable", "source", "", "something else", None, 5):
            with self.assertRaises(AppError) as caught:
                apply.adapter_for(kind).apply(None, **CALL)
            self.assertEqual(caught.exception.code, "UPDATE_NOT_INSTALLED_KIND", repr(kind))

    def test_installed_kinds_have_no_adapter_yet_and_refuse_without_running_anything(self):
        for kind in ("velopack", "inno"):
            adapter = apply.adapter_for(kind)
            self.assertIsInstance(adapter, apply.MissingAdapter)
            with self.assertRaises(AppError) as caught:
                adapter.apply(None, **CALL)
            self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_APPLY_FAILED", f"adapter_missing:{kind}"))

    def test_the_kinds_the_manifest_may_name_match_the_adapters_installed_kinds(self):
        from chanceblog_desktop.update import manifest
        self.assertEqual(tuple(manifest.INSTALLER_KINDS), apply.INSTALLED_KINDS)
        self.assertEqual(sorted(manifest.INSTALL_KINDS), sorted(apply.INSTALLED_KINDS + ("portable", "source")))


class NoLaunchCodeTest(unittest.TestCase):
    BANNED_IMPORTS = {"subprocess", "socket", "ssl", "http", "ftplib", "smtplib", "webbrowser", "ctypes", "winreg", "msvcrt", "multiprocessing", "asyncio", "socketserver", "xmlrpc", "requests"}
    BANNED_NAMES = {"system", "popen", "startfile", "Popen", "spawnl", "spawnv", "execv", "execl", "posix_spawn", "urlopen", "QDesktopServices", "QProcess"}

    def test_no_file_in_the_package_launches_a_program_or_connects_to_anything_by_itself(self):
        for path in sorted(UPDATE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], self.BANNED_IMPORTS, f"{path.name}: {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertNotIn((node.module or "").split(".")[0], self.BANNED_IMPORTS, f"{path.name}: {node.module}")
                    if node.module == "urllib.request":
                        self.fail(f"{path.name}: urllib.request")
                name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                if name is not None:
                    self.assertNotIn(name, self.BANNED_NAMES, f"{path.name}: {name}")
                if isinstance(node, ast.Name) and node.id in ("eval", "exec", "__import__"):
                    self.fail(f"{path.name}: {node.id}")

    def test_the_connection_frame_is_imported_only_inside_functions_never_at_module_top(self):
        for path in sorted(UPDATE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.level == 2 and (node.module or "").startswith("net"):
                    self.assertIn(node.module, ("net", "net.parse", "net.endpoints", "net.errors"), f"{path.name}: 맨 위에서 {node.module} 를 가져온다")
                    for alias in node.names:
                        self.assertNotIn(alias.name, ("client", "site"), f"{path.name}: 맨 위에서 접속 틀을 가져온다")


class InstallKindTest(unittest.TestCase):
    def test_not_frozen_is_the_source_run_whatever_files_exist(self):
        self.assertEqual(install_kind.detect("C:/x", frozen=False, exists=lambda path: True), "source")

    def test_velopack_needs_both_markers_inno_needs_its_uninstaller_and_the_rest_is_portable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "pkg" / "current"
            app.mkdir(parents=True)
            self.assertEqual(install_kind.detect(app, frozen=True), "portable")
            (root / "pkg" / "Update.exe").write_bytes(b"x")
            self.assertEqual(install_kind.detect(app, frozen=True), "portable", "표식 하나만으로는 설치형이 아니다")
            (app / "sq.version").write_bytes(b"x")
            self.assertEqual(install_kind.detect(app, frozen=True), "velopack")
            (root / "pkg" / "Update.exe").unlink()
            (app / "sq.version").unlink()
            (app / "unins000.exe").write_bytes(b"x")
            self.assertEqual(install_kind.detect(app, frozen=True), "inno")
            (root / "pkg" / "Update.exe").write_bytes(b"x")
            (app / "sq.version").write_bytes(b"x")
            self.assertEqual(install_kind.detect(app, frozen=True), "velopack", "둘이 다 있으면 Velopack 표식이 먼저다")

    def test_a_directory_with_a_marker_name_is_not_a_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "current"
            (app / "unins000.exe").mkdir(parents=True)
            self.assertEqual(install_kind.detect(app, frozen=True), "portable")

    def test_garbage_input_closes_to_portable_without_raising(self):
        for bad in (None, 5, object()):
            self.assertEqual(install_kind.detect(bad, frozen=True), "portable", repr(bad))

        def deny(path):
            raise OSError("denied")
        self.assertEqual(install_kind.detect("C:/x", frozen=True, exists=deny), "portable")


if __name__ == "__main__":
    unittest.main()
