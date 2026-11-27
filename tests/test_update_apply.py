"""`update/apply.py`·`update/install_kind.py` 시험(UPDATE 설계서 3-8, v1update U-2 + v1update4 U-4) — 적용 어댑터의 틀·어댑터 고르기·설치 종류 가르기. Inno 어댑터 자체의 시험은 `test_update_inno.py` 다.

지키는 것:
  1) 어댑터의 `apply` 첫 문장이 스위치 관문(`capabilities.require_update_apply`)이다 — 꺼져 있으면 `UPDATE_DISABLED` 로 `_apply`(설치 도구를 띄울 자리)를 한 번도 부르기 전에 끝난다. 하위 클래스가 `_apply` 만 채워도 이 관문은 빠지지 않는다.
  2) 휴대용·소스 실행·모르는 종류는 `UPDATE_NOT_INSTALLED_KIND`, `inno` 는 진짜 어댑터(`InnoAdapter`), 매니페스트는 읽지만 적용 어댑터가 없는 `velopack`(설치 도구 결정 D-811)은 `UPDATE_APPLY_FAILED`(이유 `kind_not_supported`)로 거절한다 — 거절은 아무것도 실행하지 않는다.
  3) **`update/` 패키지에서 설치 도구를 띄우는 곳은 `apply.py` 의 `launch_setup` 한 곳뿐이다** — 나머지 파일에는 `subprocess`·`os.system`·`Popen`·`socket`·`http`·`ssl`·`urllib` 의 접속·`webbrowser`·`ctypes` 가져오기가 0 이고(`source.py` 가 `net/` 틀을 늦게 가져오는 것 말고는),
     `apply.py` 에는 아래 `SetupLauncherSourceTest` 의 더 좁은 규칙(하위 프로세스 이름은 `Popen`·`DEVNULL` 둘, 부르는 곳 하나, 셸 없음, 그 밖의 바깥 길 0)이 걸린다.
     그 규칙은 **가져오기 별칭을 풀어서도** 본다(독립 검증 S R2 — `from subprocess import Popen as _P`·`import subprocess as sp` 가 예전에는 다섯 시험 모듈을 모두 통과했다): 가져오기는 별칭 없는 `import subprocess` 한 줄뿐이고,
     모든 호출 글을 별칭표로 풀었을 때 프로그램을 띄우는 호출은 `launch_setup` 안의 `subprocess.Popen` 하나뿐이다.
  4) 설치 종류는 파일이 있는지만 본다(묶음이 아니면 소스, 묶음이면 `unins000.exe` → inno, 그 밖 휴대용 — Velopack 감지는 지웠다). 어떤 입력에도 예외 없이 닫는 쪽(휴대용)이다.
네트워크·진짜 설치 도구 없이 돈다.
"""
import ast
import subprocess
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
STARTERS = {"Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput", "system", "popen", "startfile", "exec", "eval", "Process", "create_subprocess_exec", "create_subprocess_shell",
            "ShellExecute", "ShellExecuteA", "ShellExecuteW", "ShellExecuteEx", "CreateProcess", "CreateProcessA", "CreateProcessW",
            "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "posix_spawn", "posix_spawnp"}


def import_aliases(tree):
    """가져오기 별칭표 — `import os as o` → `o: os`, `from subprocess import Popen as P` → `P: subprocess.Popen`(별칭이 없으면 이름 그대로)."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                aliases[alias.asname or alias.name] = "." * node.level + (node.module or "") + "." + alias.name
    return aliases


def dotted(node):
    """이름·점 사슬(`a.b.c`)이면 그 글, 맨 왼쪽이 이름이 아니면(호출 결과 등) None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def resolved_calls(tree):
    """[(그 호출이 든 함수 이름, 가져오기 별칭표로 푼 호출 글 | None)] — 맨 왼쪽이 호출 결과인 점 호출(`Path(x).with_name(…)`)은 마지막 낱말만, 이름으로 부르지 않는 호출(`vars(m)['P'](…)`·`f()()`)은 None."""
    aliases = import_aliases(tree)
    found = []

    def visit(node, current):
        for child in ast.iter_child_nodes(node):
            inside = child.name if isinstance(child, ast.FunctionDef) else current
            if isinstance(child, ast.Call):
                text = dotted(child.func)
                if text is None:
                    text = child.func.attr if isinstance(child.func, ast.Attribute) else None
                else:
                    head, _, rest = text.partition(".")
                    if head in aliases:
                        text = aliases[head] + ("." + rest if rest else "")
                found.append((inside, text))
            visit(child, inside)
    visit(tree, "")
    return found


def starts_a_program(text):
    parts = text.split(".")
    return parts[-1] in STARTERS or "ctypes" in parts


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
        """(옛 이름 그대로 — 시험 id 를 지키려고) U-4 이전에는 설치형 둘 다 어댑터가 없었다. 지금은 `inno` 만 진짜 어댑터(`InnoAdapter`)를 갖고, `velopack`(매니페스트는 읽지만 설치 도구 결정 D-811 로 적용 어댑터를 만들지 않는다)은
        아무것도 실행하지 않고 `UPDATE_APPLY_FAILED`(이유 `kind_not_supported`)로 거절한다. 어느 쪽이든 받은 파일이 없는 호출(`None`)은 예외 대신 `UPDATE_APPLY_FAILED` 로 닫힌다 — 하위 프로세스는 한 번도 불리지 않는다."""
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("이 시험은 하위 프로세스를 띄우지 않는다")) as popen:
            adapter = apply.adapter_for("velopack")
            self.assertIsInstance(adapter, apply.NotSupportedAdapter)
            self.assertNotIsInstance(adapter, apply.InnoAdapter)
            with self.assertRaises(AppError) as caught:
                adapter.apply(None, **CALL)
            self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_APPLY_FAILED", "kind_not_supported"))
            adapter = apply.adapter_for("inno")
            self.assertIsInstance(adapter, apply.InnoAdapter)
            with self.assertRaises(AppError) as caught:
                adapter.apply(None, **CALL)
            self.assertEqual(caught.exception.code, "UPDATE_APPLY_FAILED")
            popen.assert_not_called()

    def test_the_kinds_the_manifest_may_name_match_the_adapters_installed_kinds(self):
        """매니페스트가 이름으로 부를 수 있는 설치 도구 = 적용 어댑터가 있는 것(`inno`) + 읽기만 하는 것(`velopack`). 앱이 스스로 가질 수 있는 설치 종류는 `inno`·`portable`·`source` 셋이다(손으로 적은 값으로 못박는다)."""
        from chanceblog_desktop.update import manifest
        self.assertEqual(apply.INSTALLED_KINDS, ("inno",))
        self.assertEqual(apply.READ_ONLY_INSTALLER_KINDS, ("velopack",))
        self.assertEqual(sorted(manifest.INSTALLER_KINDS), sorted(apply.INSTALLED_KINDS + apply.READ_ONLY_INSTALLER_KINDS))
        self.assertEqual(tuple(manifest.INSTALL_KINDS), ("inno", "portable", "source"))
        self.assertEqual(sorted(manifest.INSTALL_KINDS), sorted(apply.INSTALLED_KINDS + ("portable", "source")))
        self.assertEqual(apply.REQUIRED_ROLES, {"inno": ("setup",)}, "받아야 하는 파일의 역할은 Inno 의 Setup 하나뿐이다")
        for kind in apply.INSTALLED_KINDS:
            self.assertEqual(apply.adapter_for(kind).kind, kind)

    def test_a_kind_without_an_adapter_is_refused_by_name_and_an_unknown_one_is_not_confused_with_it(self):
        """`velopack` 은 '적용 어댑터가 없다'(`UPDATE_APPLY_FAILED`) 이고 휴대용·소스·모르는 값은 '설치형이 아니다'(`UPDATE_NOT_INSTALLED_KIND`) 다 — 둘이 섞이지 않는다."""
        for kind, code in (("velopack", "UPDATE_APPLY_FAILED"), ("portable", "UPDATE_NOT_INSTALLED_KIND"), ("source", "UPDATE_NOT_INSTALLED_KIND"), ("msi", "UPDATE_NOT_INSTALLED_KIND"), ("INNO", "UPDATE_NOT_INSTALLED_KIND"),
                           (["inno"], "UPDATE_NOT_INSTALLED_KIND"), ({"kind": "inno"}, "UPDATE_NOT_INSTALLED_KIND")):
            with self.subTest(kind=repr(kind)):
                with self.assertRaises(AppError) as caught:
                    apply.adapter_for(kind).apply(None, **CALL)
                self.assertEqual(caught.exception.code, code)
        self.assertIsInstance(apply.adapter_for("inno"), apply.InnoAdapter)
        self.assertNotIsInstance(apply.adapter_for("Inno"), apply.InnoAdapter, "대소문자만 다른 값은 설치형이 아니다")


class NoLaunchCodeTest(unittest.TestCase):
    BANNED_IMPORTS = {"subprocess", "socket", "ssl", "http", "ftplib", "smtplib", "webbrowser", "ctypes", "winreg", "msvcrt", "multiprocessing", "asyncio", "socketserver", "xmlrpc", "requests"}
    BANNED_NAMES = {"system", "popen", "startfile", "Popen", "spawnl", "spawnv", "execv", "execl", "posix_spawn", "urlopen", "QDesktopServices", "QProcess"}

    def test_no_file_in_the_package_launches_a_program_or_connects_to_anything_by_itself(self):
        """`apply.py` 는 설치 도구를 띄우는 유일한 파일이라 이 일반 금지에서 빠지고(U-4), 대신 아래 `SetupLauncherSourceTest` 가 그 파일에 **더 좁은** 규칙을 건다 — 나머지 열한 파일은 예전 그대로 `subprocess`·`Popen` 가져오기·부르기가 0 이다."""
        for path in sorted(UPDATE.glob("*.py")):
            if path.name == "apply.py":
                continue
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


class SetupLauncherSourceTest(unittest.TestCase):
    """`apply.py` 는 앱이 설치 도구를 띄우는 **유일한 파일**이다(U-4, 설계서 3-8) — 그래서 `NoLaunchCodeTest` 의 일반 금지에서 빠진 대신 이 파일에만 더 좁은 규칙을 건다: 가져오는 모듈은 다섯뿐,
    `subprocess` 이름은 `Popen`(한 번, `launch_setup` 안)과 `DEVNULL` 뿐, 셸 없음, 명령은 목록 하나(`inno_command` 가 목록을 돌려준다), 그 밖의 바깥 길(`os.system`·`startfile`·`ctypes`·접속·`eval`)은 0."""
    ALLOWED_IMPORTS = {"__future__", "os", "re", "subprocess", "pathlib"}
    EXTRA_BANNED_IMPORTS = {"shlex", "urllib", "importlib", "runpy", "pty", "nt", "posix", "_winapi", "_socket", "_ssl", "telnetlib", "imaplib", "poplib"}

    def tree(self):
        return ast.parse((UPDATE / "apply.py").read_text(encoding="utf-8"))

    def function(self, name):
        found = [node for node in ast.walk(self.tree()) if isinstance(node, ast.FunctionDef) and node.name == name]
        self.assertEqual(len(found), 1, f"{name} 함수가 하나여야 한다")
        return found[0]

    def test_apply_py_imports_only_the_five_allowed_modules_and_does_import_subprocess(self):
        imported = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, self.ALLOWED_IMPORTS)
        self.assertEqual(imported & (NoLaunchCodeTest.BANNED_IMPORTS - {"subprocess"}), set(), "접속·네이티브 모듈은 이 파일에도 없다")
        self.assertEqual(imported & self.EXTRA_BANNED_IMPORTS, set())

    def test_the_only_subprocess_names_are_popen_once_inside_launch_setup_and_devnull(self):
        used = {}
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "subprocess":
                used[node.attr] = used.get(node.attr, 0) + 1
        self.assertEqual(sorted(used), ["DEVNULL", "Popen"], "하위 프로세스 이름은 Popen 과 DEVNULL 뿐이다")
        self.assertEqual(used["Popen"], 1, "Popen 은 한 번만 나온다")
        launcher = self.function("launch_setup")
        inside = [node for node in ast.walk(launcher) if isinstance(node, ast.Attribute) and node.attr == "Popen"]
        self.assertEqual(len(inside), 1, "그 한 번이 launch_setup 안에 있다")
        calls = [node for node in ast.walk(self.tree()) if isinstance(node, ast.Call) and ast.unparse(node.func) == "subprocess.Popen"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([ast.unparse(arg) for arg in calls[0].args], ["command"], "명령은 목록 하나(변수 command)로 넘긴다")
        self.assertEqual([keyword.arg for keyword in calls[0].keywords], [None], "나머지 옵션은 spawn_options() 의 사전 하나(**)로만 넘긴다")
        self.assertEqual(ast.unparse(calls[0].keywords[0].value), "spawn_options()")
        self.assertEqual(sorted(name for name, count in ((n, sum(1 for x in ast.walk(self.tree()) if isinstance(x, ast.Attribute) and x.attr == n)) for n in ("Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput")) if count), ["Popen"])

    def test_the_first_statement_of_launch_setup_is_the_switch_gate(self):
        body = [node for node in self.function("launch_setup").body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        self.assertEqual(ast.unparse(body[0]), "capabilities.require_update_apply('업데이트 설치 도구 띄우기')")

    def test_no_shell_and_the_command_is_a_list_built_by_one_function(self):
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                self.assertEqual(ast.unparse(node.value), "False")
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "shell":
                        self.assertEqual(ast.unparse(value), "False", "셸은 거짓")
        options = ast.unparse(self.function("spawn_options"))
        self.assertIn("'shell': False", options, "셸 거짓이 글자 그대로 적혀 있다")
        self.assertIn("'close_fds': True", options)
        self.assertEqual(options.count("subprocess.DEVNULL"), 3, "표준 입력·출력·오류가 모두 NUL 이다(출력은 읽지 않는다)")
        returns = [node for node in ast.walk(self.function("inno_command")) if isinstance(node, ast.Return)]
        self.assertEqual(len(returns), 1)
        self.assertIsInstance(returns[0].value, ast.List, "명령은 목록(문자열 한 줄이 아니다)")
        starred = [item for item in returns[0].value.elts if isinstance(item, ast.Starred)]
        self.assertEqual([ast.unparse(item.value) for item in starred], ["INNO_SILENT_ARGS"], "고정 인자 목록을 그대로 펼친다")
        launcher = ast.unparse(self.function("launch_setup"))
        self.assertIn("command = inno_command(", launcher)
        self.assertNotIn("join(", ast.unparse(self.tree()), "문자열을 이어 붙여 명령 줄을 만들지 않는다")

    def test_no_other_way_to_start_a_program_or_reach_the_outside_exists_in_the_file(self):
        banned = (NoLaunchCodeTest.BANNED_NAMES - {"Popen"}) | {"spawn", "spawnle", "spawnlp", "spawnve", "execve", "execvp", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput", "Process", "ProcessPoolExecutor", "create_subprocess_exec"}
        for node in ast.walk(self.tree()):
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
            if name is not None:
                self.assertNotIn(name, banned, name)
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, ("eval", "exec", "__import__", "compile", "open"), node.id)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
                self.fail("getattr 로 이름을 돌려 부르지 않는다")
        text = (UPDATE / "apply.py").read_text(encoding="utf-8")
        for word in ("ShellExecute", "CreateProcess", "cmd.exe", "powershell", "shell=True", "os.startfile", "taskkill"):
            self.assertNotIn(word, text, word)

    def test_nobody_but_the_inno_adapter_calls_launch_setup_anywhere_in_the_app(self):
        callers = []
        src = ROOT / "src" / "chanceblog_desktop"
        for path in sorted(src.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef):
                    continue
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "launch_setup":
                        callers.append((path.relative_to(src).as_posix(), fn.name))
        self.assertEqual(sorted(callers), [("update/apply.py", "_apply")], "설치 도구를 띄우는 함수의 부르는 곳은 어댑터의 `_apply` 하나다")
        mentions = [path.relative_to(src).as_posix() for path in sorted(src.rglob("*.py")) if "launch_setup" in path.read_text(encoding="utf-8")]
        self.assertEqual(mentions, ["update/apply.py"], "다른 파일은 이 이름을 언급하지도 않는다")

    def test_subprocess_is_imported_by_one_plain_import_line_with_no_alias_and_no_from_import(self):
        """독립 검증 S R2(변이 X10·X11·X15) — `from subprocess import Popen as _P`·`import subprocess as sp` 같은 별칭 가져오기가 예전의 '하위 프로세스는 한 곳' 규칙을 비껴 갔다(그 규칙은 `subprocess.<이름>` 글만 셌다).
        이 파일의 가져오기는 별칭 없는 `import subprocess` 정확히 한 줄이고 `from subprocess import …` 는 하나도 없다."""
        tree = self.tree()
        plain = [node for node in ast.walk(tree) if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "subprocess" for alias in node.names)]
        self.assertEqual(len(plain), 1, "`import subprocess` 는 정확히 한 줄")
        self.assertEqual([(alias.name, alias.asname) for alias in plain[0].names], [("subprocess", None)], "그 줄은 별칭이 없고 이 이름 하나뿐이다")
        froms = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "subprocess"]
        self.assertEqual(froms, [], "`from subprocess import …` 는 0")

    def test_every_call_resolved_through_the_import_aliases_starts_no_program_except_the_one_popen_inside_launch_setup(self):
        """독립 검증 S R2 — 모든 호출 글을 가져오기 별칭표로 풀어 `Popen`·`run`·`call`·`check_output`·`os.exec*`·`os.spawn*`·`os.system`·`startfile`·`ctypes` 로 끝나는(든) 호출을 센다 — `launch_setup` 안의 `subprocess.Popen` 하나뿐이다.
        이름으로 부르지 않는 호출(`vars(subprocess)['Popen'](…)` 처럼 식의 결과를 바로 부르기)도 이 파일에는 없다."""
        flagged = [(inside, text) for inside, text in resolved_calls(self.tree()) if text is None or starts_a_program(text)]
        self.assertEqual(flagged, [("launch_setup", "subprocess.Popen")])

    def test_the_scanner_itself_sees_the_alias_forms_it_exists_to_catch(self):
        """위 두 시험이 눈먼 것이 아님을 보인다 — 별칭 가져오기·모듈 별칭·`from … import run`·`os` 별칭·`ctypes`·식 결과 부르기를 합성 소스에 넣으면 모두 걸린다(그리고 평범한 소스는 안 걸린다)."""
        header = "def f(c):\n    return "
        cases = (
            ("from subprocess import Popen as _P\n" + header + "_P(c)\n", "subprocess.Popen"),
            ("import subprocess as sp\n" + header + "sp.Popen(c)\n", "subprocess.Popen"),
            ("from subprocess import run\n" + header + "run(c)\n", "subprocess.run"),
            ("import os as o\n" + header + "o.system(c)\n", "os.system"),
            ("from os import startfile as go\n" + header + "go(c)\n", "os.startfile"),
            ("import ctypes as k\n" + header + "k.windll.shell32.ShellExecuteW(c)\n", "k.windll.shell32.ShellExecuteW"),
            ("import subprocess\n" + header + "vars(subprocess)['Popen'](c)\n", None),
        )
        for text, expected in cases:
            with self.subTest(source=text.splitlines()[0]):
                flagged = [item for item in resolved_calls(ast.parse(text)) if item[1] is None or starts_a_program(item[1])]
                self.assertEqual(len(flagged), 1, flagged)
                inside, got = flagged[0]
                self.assertEqual(inside, "f")
                if expected is None:
                    self.assertIsNone(got)
                else:
                    self.assertTrue(got.endswith(expected.split(".")[-1]) or "ctypes" in got.split("."), got)
        calm = ast.parse("import os\nfrom pathlib import Path\ndef f(p):\n    return Path(p).with_name('x'), os.path.isabs(p), spawn_options()\n")
        self.assertEqual([item for item in resolved_calls(calm) if item[1] is None or starts_a_program(item[1])], [], "평범한 호출은 걸리지 않는다(`spawn_options` 처럼 이름만 비슷한 것도)")


class InstallKindTest(unittest.TestCase):
    def test_not_frozen_is_the_source_run_whatever_files_exist(self):
        self.assertEqual(install_kind.detect("C:/x", frozen=False, exists=lambda path: True), "source")

    def test_velopack_needs_both_markers_inno_needs_its_uninstaller_and_the_rest_is_portable(self):
        """(옛 이름 그대로 — 시험 id 를 지키려고) 설치 도구가 Inno 로 정해져(D-811) Velopack 감지는 지워졌다: Velopack 표식(`Update.exe`·`sq.version`)은 둘이 다 있어도 더는 설치형이 아니다 — 휴대용으로 닫힌다.
        Inno 는 실행 파일 폴더의 `unins000.exe` 하나이고, 둘이 다 있으면 Inno 다(Velopack 표식이 이기던 옛 규칙의 거울)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "pkg" / "current"
            app.mkdir(parents=True)
            self.assertEqual(install_kind.detect(app, frozen=True), "portable")
            (root / "pkg" / "Update.exe").write_bytes(b"x")
            self.assertEqual(install_kind.detect(app, frozen=True), "portable", "표식 하나만으로는 설치형이 아니다")
            (app / "sq.version").write_bytes(b"x")
            self.assertEqual(install_kind.detect(app, frozen=True), "portable", "Velopack 표식 둘이 다 있어도 이제는 휴대용이다(감지를 지웠다)")
            (root / "pkg" / "Update.exe").unlink()
            (app / "sq.version").unlink()
            (app / "unins000.exe").write_bytes(b"x")
            self.assertEqual(install_kind.detect(app, frozen=True), "inno")
            (root / "pkg" / "Update.exe").write_bytes(b"x")
            (app / "sq.version").write_bytes(b"x")
            self.assertEqual(install_kind.detect(app, frozen=True), "inno", "둘이 다 있으면 Inno 표식이 이긴다")

    def test_the_only_file_looked_at_is_the_inno_uninstaller_and_nothing_can_be_detected_as_velopack(self):
        """감지는 파일이 있는지만 본다: 묶음이면 폴더의 `unins000.exe` 하나만 묻고(부모 폴더의 `Update.exe`·`sq.version` 은 묻지 않는다), 어떤 표식 조합에서도 `velopack` 은 나오지 않는다."""
        asked = []

        def spy(path):
            asked.append(Path(path).as_posix())
            return False
        self.assertEqual(install_kind.detect("C:/app/current", frozen=True, exists=spy), "portable")
        self.assertEqual(asked, ["C:/app/current/unins000.exe"], "묻는 파일은 Inno 제거 도구 하나뿐이다")
        self.assertFalse(hasattr(install_kind, "VELOPACK_MARKERS"), "Velopack 표식 상수를 지웠다")
        self.assertEqual(install_kind.INNO_MARKERS, ((".", "unins000.exe"),))
        names = ("Update.exe", "sq.version", "unins000.exe")
        for mask in range(8):
            present = {names[bit] for bit in range(3) if mask >> bit & 1}
            result = install_kind.detect("C:/app/current", frozen=True, exists=lambda path: Path(path).name in present)
            self.assertEqual(result, "inno" if "unins000.exe" in present else "portable", sorted(present))
            self.assertIn(result, ("inno", "portable"))
        self.assertEqual(install_kind.detect("C:/app/current", frozen=False, exists=lambda path: True), "source")

    def test_the_detector_imports_nothing_that_could_read_the_registry_or_start_anything(self):
        """`install_kind.py` 는 `pathlib` 말고 아무것도 가져오지 않고(레지스트리·하위 프로세스·접속 0) 부르는 이름도 파일 확인뿐이다."""
        tree = ast.parse((UPDATE / "install_kind.py").read_text(encoding="utf-8"))
        imported = sorted((node.module or "") if isinstance(node, ast.ImportFrom) else alias.name for node in ast.walk(tree) for alias in (getattr(node, "names", []) if isinstance(node, (ast.Import, ast.ImportFrom)) else []))
        self.assertEqual(sorted({name.split(".")[0] for name in imported if name != "__future__"}), ["pathlib"])
        self.assertEqual(sorted({node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}), ["is_file"])

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
