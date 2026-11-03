"""서비스 층 — 안전 규칙을 소스에서 직접 확인하는 시험(AST 검사 + 몇 가지 통합 확인). 규칙을 어기는 코드가 몰래 들어오면 여기서 걸린다.

지키는 것(AGENTS.md 절대 규칙 1·2·4·6·7):
  1) 조용한 실패 금지: 서비스 코드에 맨 `except:` 나 본문이 `pass` 뿐인 `except` 가 없다(오류를 숨기지 않는다). 오류를 일부러 삼키는 곳(`contextlib.suppress`)은 아래 목록의 둘뿐이다.
  2) 로그인·네트워크·셸 자동화 없음: 서비스 코드는 `subprocess`·`socket`·`urllib`·`http`·`ssl`·`webbrowser`·`ctypes` 를 쓰지 않는다(git 은 backend 를 거쳐 `publish/` 모듈이 하고, 네트워크는 주입한 배포 확인뿐이다).
  3) git 을 직접 쓰는 명령은 읽기 전용(`rev-parse`·`rev-list`·`ls-tree`·`cat-file`·`diff-tree`·`log`·`--version`)뿐이다 — commit·push·되돌리기는 모두 `publish/pages.py` 가 한다. 강제 push·`reset --hard` 같은 말은 어디에도 없다.
  4) 서비스 코드가 파일을 쓰는 곳은 설정·발행 기록·잠금 파일(`context.write_json`·`journal`·`lock` — 글 잠금은 데이터 폴더에, 저장소 잠금은 연결한 저장소의 `.git` 안에 둔다)뿐이다 — 연결한 저장소에 글 파일은 쓰지 않는다(그건 `publish/pages.py`).
  5) 키·토큰을 읽지 않는다: 읽는 환경 변수는 데이터 폴더·저장소 폴더 위치뿐이고, 영어 비밀 낱말(`api key`·`secret`·`token`·`password`)이 서비스 코드의 문자열에 없다.
  6) 이 PC 의 절대경로는 commit 되는 글·commit 제목에 들어가지 않는다.
"""
import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import CATALOG  # noqa: E402
from chanceblog_desktop.service import pages_flow  # noqa: E402

SERVICE = ss.ROOT / "src" / "chanceblog_desktop" / "service"
FILES = sorted(SERVICE.glob("*.py")) + [ss.ROOT / "src" / "chanceblog_desktop" / "__main__.py"]
FORBIDDEN_IMPORTS = {"subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "requests", "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio"}
READ_ONLY_GIT = {"rev-parse", "rev-list", "ls-tree", "cat-file", "diff-tree", "log", "--version"}        # diff-tree·log: commit 직후에 멈춘 이 글의 commit 인지 읽기만 해서 확인한다
FILE_WRITERS = {"context.py": {"write_text", "replace", "unlink", "mkdir"}, "journal.py": {"unlink"}, "lock.py": {"unlink", "mkdir"}}
WRITE_CALLS = {"write_text", "write_bytes", "write", "unlink", "mkdir", "rmdir", "replace", "rename", "remove", "rmtree", "copy", "copy2", "copyfile", "copytree", "move", "touch", "open", "makedirs", "chmod"}
ENV_NAMES = {"CHANCEBLOG_DESKTOP_DATA", "CHANCEBLOG_LOCAL_REPO", "LOCALAPPDATA", "XDG_DATA_HOME"}
OTHER_NAMES = {"VERSION", "O_BINARY"}           # 파일 이름(프로그램 버전을 적은 파일) · 잠금 파일을 만들 때 Windows 에서 쓰는 열기 표시(os.O_BINARY)


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def strings(tree):
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


class SourceRulesTest(unittest.TestCase):
    def test_the_service_package_is_found(self):
        self.assertGreaterEqual(len(FILES), 14)
        self.assertIn("pages_flow.py", [path.name for path in FILES])

    def test_no_error_is_swallowed_silently(self):
        for path in FILES:
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.ExceptHandler):
                    with self.subTest(file=path.name, line=node.lineno):
                        self.assertIsNotNone(node.type, "맨 except: 금지")
                        self.assertFalse(all(isinstance(item, ast.Pass) for item in node.body), "본문이 pass 뿐인 except 금지")

    def test_the_only_places_that_deliberately_suppress_an_error_are_the_known_two(self):
        found = []
        for path in FILES:
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "suppress":
                    found.append((path.name, ", ".join(ast.unparse(arg) for arg in node.args)))
        self.assertEqual(sorted(found), [("cli.py", "OSError, ValueError")], "오류를 일부러 삼키는 곳은 출력 방식을 바꾸는 것 하나뿐이다")

    def test_no_forbidden_modules_are_imported(self):
        for path in FILES:
            for node in ast.walk(parse(path)):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
                for name in names:
                    with self.subTest(file=path.name, module=name):
                        if path.name == "liveness.py" and name.split(".")[0] == "ctypes":
                            continue                    # 프로세스가 살아 있는지 읽기만 하는 한 곳 — 아래 test_the_liveness_check_only_reads... 가 호출을 못 박는다
                        self.assertNotIn(name.split(".")[0], FORBIDDEN_IMPORTS)

    def test_the_liveness_check_only_reads_the_state_of_a_process_and_never_ends_or_signals_one(self):
        tree = parse(SERVICE / "liveness.py")
        kills, calls = [], set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                calls.add(name)
                if name == "os.kill":
                    kills.append(node)
        self.assertEqual(len(kills), 1, "os.kill 은 한 곳(신호 0 — 있는지만 본다)뿐이다")
        self.assertEqual([ast.unparse(arg) for arg in kills[0].args], ["pid", "0"])
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_posix")
        self.assertTrue(any(node is kills[0] for node in ast.walk(function)), "os.kill 은 Windows 가 아닐 때만 부르는 함수 안에 있다(Windows 에서는 프로세스를 끝내 버린다)")
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "process_alive")
        self.assertIn("os.name == 'nt'", ast.unparse(main))
        words = {name.rsplit(".", 1)[-1] for name in calls}
        self.assertFalse(words & {"TerminateProcess", "TerminateJobObject", "DebugActiveProcess", "WriteProcessMemory", "CreateRemoteThread", "SetPriorityClass", "system", "popen", "Popen", "run"})
        self.assertLessEqual({name for name in words if name[:1].isupper()} - {"WinDLL", "DWORD", "BOOL", "HANDLE", "POINTER", "FILETIME", "OpenProcess", "GetExitCodeProcess", "GetProcessTimes", "CloseHandle"}, set(),
                             "읽기 전용 Windows 호출만 쓴다")
        text = (SERVICE / "liveness.py").read_text(encoding="utf-8")
        self.assertIn("_QUERY_LIMITED = 0x1000", text, "상태를 읽는 권한(PROCESS_QUERY_LIMITED_INFORMATION)만 연다")

    def test_the_only_git_commands_the_service_runs_itself_are_read_only(self):
        used = set()
        for path in FILES:
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "git" and len(node.args) >= 2 and isinstance(node.args[1], ast.List):
                    first = node.args[1].elts[0] if node.args[1].elts else None
                    self.assertIsInstance(first, ast.Constant, f"{path.name}:{node.lineno} git 명령은 글자 상수여야 한다")
                    used.add(first.value)
        self.assertTrue(used)
        self.assertLessEqual(used, READ_ONLY_GIT, f"읽기 전용이 아닌 git 명령: {used - READ_ONLY_GIT}")

    def test_the_only_doors_to_commit_push_and_undo_are_the_publish_functions_behind_the_confirmation(self):
        """backend 의 commit·push·discard 를 부르는 곳을 못 박는다 — 미리 보기·점검·명령줄 같은 곳이 몰래 부르면 여기서 걸린다."""
        callers = {}
        for path in FILES:
            tree = parse(path)
            for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
                for node in ast.walk(function):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("commit", "push", "discard") and ast.unparse(node.func.value).endswith("backend"):
                        callers.setdefault(node.func.attr, set()).add((path.name, function.name))
        self.assertEqual(callers, {"commit": {("pages_flow.py", "run_pages_publish")}, "push": {("pages_flow.py", "_push")}, "discard": {("pages_flow.py", "_undo_commit"), ("pages_flow.py", "_record_committed")}})
        tree = parse(SERVICE / "pages_flow.py")
        users = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_push", "_undo_commit", "_record_committed", "_give_up"):
                    users.setdefault(node.func.id, set()).add(function.name)
        self.assertEqual(users, {"_push": {"run_pages_publish"}, "_undo_commit": {"_give_up", "cancel_pages_publish", "_cancel_unrecorded"}, "_record_committed": {"run_pages_publish"}, "_give_up": {"_push"}})

    def test_every_write_to_the_repository_happens_inside_the_repo_lock_taken_after_the_post_lock_and_the_public_check_is_outside_it(self):
        tree = parse(SERVICE / "pages_flow.py")

        def named(function, name, kind):
            return [node for node in ast.walk(function) if isinstance(node, kind) and (
                (kind is ast.With and any(isinstance(item.context_expr, ast.Call) and ast.unparse(item.context_expr.func) == name for item in node.items))
                or (kind is ast.Call and ast.unparse(node.func).rsplit(".", 1)[-1] == name))]

        for function_name, writers in (("run_pages_publish", ("commit", "_push", "_record_committed", "_record_pushed")), ("cancel_pages_publish", ("_undo_commit", "_cancel_unrecorded", "_mark_failed"))):
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
            outer = named(function, "publish_lock", ast.With)
            self.assertEqual(len(outer), 1, function_name)
            inner = named(outer[0], "_repo_section", ast.With)
            self.assertEqual(len(inner), 1, f"{function_name}: 글 잠금 안에서 저장소 잠금을 잡는다(순서 고정)")
            inside = {id(node) for node in ast.walk(inner[0])}
            for writer in writers:
                calls = named(function, writer, ast.Call)
                with self.subTest(function=function_name, writer=writer):
                    self.assertTrue(calls, f"{writer} 를 부르는 곳이 있어야 한다")
                    self.assertTrue(all(id(call) in inside for call in calls), f"{writer} 는 저장소 잠금 안에서만 부른다")
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_pages_publish")
        inside = {id(node) for node in ast.walk(named(run, "_repo_section", ast.With)[0])}
        for waiting in ("_finish",):
            calls = named(run, waiting, ast.Call)
            self.assertTrue(calls)
            self.assertTrue(all(id(call) not in inside for call in calls), "공개 확인을 기다리는 동안에는 저장소 잠금을 쥐지 않는다")
        check = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "check_pages_deploy")
        self.assertEqual(named(check, "_repo_section", ast.With), [], "공개 확인은 저장소 잠금이 필요 없다")

    def test_the_confirmation_is_the_first_thing_the_publish_and_cancel_functions_do(self):
        tree = parse(SERVICE / "pages_flow.py")
        for name in ("run_pages_publish", "cancel_pages_publish"):
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            body = [node for node in function.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]      # 설명 글(docstring) 제외
            first = body[0]
            with self.subTest(function=name):
                self.assertTrue(isinstance(first, ast.Expr) and isinstance(first.value, ast.Call) and ast.unparse(first.value.func) == "require_confirmation", ast.unparse(first)[:80])
                names = [arg.arg for arg in function.args.kwonlyargs]
                self.assertIn("confirmed", names, "확인은 이름 붙은 인자다")
                self.assertIsNone(function.args.kw_defaults[names.index("confirmed")], "확인에는 기본값이 없다(빠뜨리면 TypeError)")

    def test_no_dangerous_git_wording_anywhere(self):
        pattern = re.compile(r"--force|force-with-lease|reset --hard|push -f|clean -f|rm -rf|--no-verify|filter-branch|--mirror", re.IGNORECASE)
        for path in FILES:
            with self.subTest(file=path.name):
                self.assertEqual([text for text in strings(parse(path)) if pattern.search(text)], [])

    def test_only_settings_and_the_publish_record_are_written_by_the_service_itself(self):
        for path in FILES:
            allowed = FILE_WRITERS.get(path.name, set())
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else (node.func.id if isinstance(node.func, ast.Name) else "")
                    if name in WRITE_CALLS and name not in ("write", "open", "copy", "move", "replace", "remove"):
                        with self.subTest(file=path.name, call=name, line=node.lineno):
                            self.assertIn(name, allowed, "서비스가 직접 파일을 쓰거나 지우는 곳은 설정(context)과 발행 기록(journal)뿐이다")
                    allowed_open = ("Store.open", "os.open") if path.name == "lock.py" else ("Store.open",)         # os.open: 잠금 파일을 `O_EXCL` 로 새로 만드는 한 곳
                    opens_a_file = name in ("makedirs", "rmtree", "copytree", "copyfile", "copy2") or (name == "open" and ast.unparse(node.func) not in allowed_open)
                    if opens_a_file:
                        self.fail(f"{path.name}:{node.lineno} 서비스가 직접 파일을 열거나 복사한다: {name}")

    def test_only_the_known_environment_variables_are_named_and_no_secret_words_appear(self):
        secret_words = re.compile(r"(?i)\b(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?\b")
        constants_allowed = set(CATALOG) | ENV_NAMES | OTHER_NAMES
        for path in FILES:
            tree = parse(path)
            for text in strings(tree):
                with self.subTest(file=path.name, text=text[:30]):
                    self.assertIsNone(secret_words.search(text), "서비스 코드는 키·토큰을 다루지 않는다")
                    if re.fullmatch(r"[A-Z][A-Z0-9_]{5,}", text):
                        self.assertIn(text, constants_allowed, "읽는 환경 변수는 위치를 정하는 것뿐이다 — 새 대문자 이름은 오류 코드이거나 허용 목록에 있어야 한다")
        env_reads = []
        for path in FILES:
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                    env_reads.append(path.name)
        self.assertEqual(sorted(set(env_reads)), ["context.py"], "환경 변수는 context.py 한 곳에서만 읽는다")

    def test_every_error_code_the_service_raises_is_in_the_catalog_and_renders(self):
        pattern = re.compile(r'AppError\(\s*"([A-Z][A-Z0-9_]+)"')
        codes = {code for path in FILES for code in pattern.findall(path.read_text(encoding="utf-8"))}
        self.assertTrue({"CONFIRMATION_REQUIRED", "SETTINGS_INVALID", "DATA_DIR_UNSAFE", "NAVER_PROFILE_MISSING"} <= codes)
        for code in sorted(codes):
            with self.subTest(code=code):
                self.assertIn(code, CATALOG)
        self.assertIn("CORE_CODE_MISMATCH", CATALOG)
        self.assertIn("PUBLISH_CANCELLED", CATALOG)
        for code in ("CONFIRMATION_REQUIRED", "SETTINGS_INVALID", "DATA_DIR_UNSAFE", "NAVER_PROFILE_MISSING", "CORE_CODE_MISMATCH", "PUBLISH_CANCELLED"):
            info = CATALOG[code]
            self.assertTrue(info.message and info.action, code)


class NoLocalPathLeakTest(unittest.TestCase):
    def test_the_commit_title_and_the_post_text_never_contain_a_path_of_this_pc(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = ss.FakeBackend()
            ctx = ss.make_ctx(tmp, backend=backend)
            project_id = ss.make_approved(ctx)
            pages_flow.run_pages_publish(ctx, project_id, confirmed=True)
            commit = next(call for call in backend.calls if call[0] == "commit")
            for text in (commit[1], commit[2], commit[3]):
                self.assertNotIn(str(tmp), text)
                self.assertNotIn(str(tmp).replace("\\", "/"), text)
                self.assertNotIn(str(ctx.workspace.root), text)
            self.assertNotRegex(commit[3], r"(?i)[a-z]:[\\/]+users[\\/]")

    def test_a_post_that_would_carry_such_a_path_is_stopped_before_the_commit(self):
        """데이터 폴더·연결한 저장소 폴더(이 PC 마다 다른 정확한 경로)와 Windows 사용자 폴더 모양 — 어느 운영체제에서 돌려도 같은 결과여야 한다."""
        with tempfile.TemporaryDirectory() as tmp:
            backend = ss.FakeBackend()
            ctx = ss.make_ctx(tmp, backend=backend)
            leaks = {"데이터 폴더": str(ctx.workspace.root), "연결한 저장소 폴더": str(ctx.repo_path()), "Windows 사용자 폴더": r"C:\Users\운영자\Desktop\원고.md"}
            for name, leak in leaks.items():
                with self.subTest(leak=name):
                    view = ss.projects.new_project(ctx, f"경로가 든 글 {name}", ss.ko_text(extra=f"위치는 {leak} 입니다."))
                    ss.review.request_review(ctx, view.project_id, "github_pages", pages=ss.KO_PARAMS)
                    self.assertEqual(ss.code_of(ss.review.grant_approval, ctx, view.project_id, "github_pages").code, "CHECK_FAILED")
                    self.assertEqual(ss.status_of(ctx, view.project_id), "REVIEW_REQUIRED")
            self.assertEqual(backend.count("commit"), 0)


if __name__ == "__main__":
    unittest.main()
