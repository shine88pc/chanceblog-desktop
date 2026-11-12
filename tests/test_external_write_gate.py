"""외부 Write 완전 비활성(PCSEC1 H3, 운영자 결정 2026-11-11)의 관문 시험 — 네 겹 중 앞의 셋(서비스 거절·어댑터 미등록·소스 상수 관문)을 소스와 실제 호출로 확인한다.

지키는 것:
  1) 소스 상수 `capabilities.EXTERNAL_WRITE` 는 False 이고 글자 그대로 True 일 때만 열린다. 켜는 길이 없다 — 설정 파일·환경 변수·명령줄·화면 어디에도 이 상수를 바꾸는 코드가 없고
     (`src/` 어디서도 이름을 쓰지 않는다 — 부르는 것은 관문 함수뿐), 시험만 `mock.patch.object` 로 임시로 켠다. 어댑터를 꽂는 `register` 를 부르는 코드도 `src/` 에 없다.
  2) 외부 Write 가 닿는 모든 진입점(게시 흐름·commit·push·되돌리기·원격 받기·올리기 점검·공개 확인·하위 프로세스를 띄우는 곳)은 첫 줄에서 관문을 지난다.
  3) 꺼진 채 그 진입점을 불러 보면 **하위 프로세스·소켓·HTTP 호출이 한 번도 일어나기 전에** `EXTERNAL_WRITE_DISABLED` 로 거절하고(`Tripwire` 가 센다), 가짜 backend·가짜 git 은 한 번도 불리지 않는다.
  4) `Context` 의 기본 backend 는 파일만 읽는 `LocalOnlyBackend`, 기본 git 실행기는 무엇이든 거절하는 `refusing_git` 이다(이 PC 에 Git 로그인이 있어도 앱은 쓰지 못한다).
  5) 연결한 폴더 확인(`connect`)은 파일만 읽는다(`.git/config` 의 origin·`HEAD` 의 브랜치) — git 을 부르지 않는다. `doctor` 는 '외부 게시: 꺼져 있어요' 를 보이고 `doctor --online` 은 거절한다.
네트워크·실제 git 없이 돈다(진짜 git 로 원격 main 이 안 움직이는 것은 `test_external_write_bare_repo.py`, 모든 부명령·화면 어댑터의 연결·하위 프로세스 0 은 `test_external_write_zero.py`).
"""
import ast
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import outgoing_support as og  # noqa: E402
import secret_support as sec  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.publish import deploy, gitrepo, pages  # noqa: E402
from chanceblog_desktop.render.pages import PagesPost  # noqa: E402
from chanceblog_desktop.service import cli, connections, doctor, external, pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.context import Context, Settings, make_context  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
GATE_NAMES = ("capabilities.require_external_write", "require_external_write")
# 외부 Write 가 닿는 진입점 — (파일, 함수 또는 클래스.메서드). 모두 첫 줄(설명 글 다음 첫 문장)이 관문 호출이다.
ENTRY_POINTS = (
    ("service/pages_flow.py", "plan_pages_publish"), ("service/pages_flow.py", "preview_publish"), ("service/pages_flow.py", "run_pages_publish"),
    ("service/pages_flow.py", "check_pages_deploy"), ("service/pages_flow.py", "cancel_pages_publish"),
    ("publish/pages.py", "commit_post"), ("publish/pages.py", "push_commit"), ("publish/pages.py", "discard_commit"), ("publish/pages.py", "publish_post"),
    ("publish/gitrepo.py", "run_command"), ("publish/gitrepo.py", "run_git"), ("publish/gitrepo.py", "sync_latest"), ("publish/gitrepo.py", "check_push_access"),
    ("publish/deploy.py", "check_deployed"),
    ("service/backend.py", "GitPagesBackend.check_push_access"), ("service/backend.py", "GitPagesBackend.commit"), ("service/backend.py", "GitPagesBackend.push"),
    ("service/backend.py", "GitPagesBackend.discard"), ("service/backend.py", "GitPagesBackend.check_deployed"),
    ("service/cli.py", "cmd_publish_pages"), ("service/cli.py", "cmd_check_deploy"),
)
# 첫 문장이 `if 온라인:` 이고 그 안 첫 문장이 관문인 곳
CONDITIONAL_ENTRY_POINTS = (("service/cli.py", "cmd_doctor"), ("service/doctor.py", "_check_push_access"))


def parse(rel):
    return ast.parse((SRC / rel).read_text(encoding="utf-8"), filename=rel)


def function_node(tree, qualified):
    scope = tree
    for part in qualified.split("."):
        scope = next(node for node in ast.iter_child_nodes(scope) if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == part)
    return scope


def statements(function):
    return [node for node in function.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]            # 설명 글(docstring) 제외


def is_gate_call(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) in GATE_NAMES


def src_files():
    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)


class ConstantTest(unittest.TestCase):
    def test_the_shipped_constants_are_off(self):
        self.assertIs(capabilities.EXTERNAL_WRITE, False)
        self.assertIs(capabilities.BLOGGER_OAUTH_INPUT, False)
        self.assertFalse(capabilities.external_write_enabled())
        self.assertFalse(capabilities.blogger_oauth_input_enabled())

    def test_the_gate_refuses_with_the_catalog_code_and_names_the_operation(self):
        with self.assertRaises(AppError) as caught:
            capabilities.require_external_write("시험 작업")
        error = caught.exception
        self.assertEqual(error.code, "EXTERNAL_WRITE_DISABLED")
        self.assertEqual(error.slots, {"작업": "시험 작업"})
        shown = error.rendered()
        self.assertIn("시험 작업", shown.message)
        self.assertIn("꺼져", shown.message)
        self.assertEqual(shown.retry_kind, "no")

    def test_only_the_literal_true_opens_the_gate(self):
        for value in (1, "yes", "True", [1], object(), 2, "1"):
            with self.subTest(value=repr(value)[:20]), mock.patch.object(capabilities, "EXTERNAL_WRITE", value):
                self.assertFalse(capabilities.external_write_enabled())
                with self.assertRaises(AppError):
                    capabilities.require_external_write("x")
        with mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
            self.assertTrue(capabilities.external_write_enabled())
            capabilities.require_external_write("x")                             # 예외 없음
        self.assertIs(capabilities.EXTERNAL_WRITE, False, "시험의 임시 켜기는 끝나면 원래대로다")

    def test_the_catalog_row_exists_with_every_column(self):
        info = CATALOG["EXTERNAL_WRITE_DISABLED"]
        self.assertTrue(info.when and info.message and info.action)
        self.assertEqual(info.slots, ("작업",))
        self.assertEqual(info.retry_kind, "no")


class NoWayToTurnItOnTest(unittest.TestCase):
    """켜는 길이 없다 — 소스에서 직접 확인한다(설정 파일·환경 변수·명령줄·화면·등록)."""

    def test_nothing_in_src_stores_to_the_constant_except_the_one_false_in_capabilities(self):
        stores = []
        for path in src_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for target in targets:
                    for item in ast.walk(target):
                        if (isinstance(item, ast.Name) and item.id == "EXTERNAL_WRITE") or (isinstance(item, ast.Attribute) and item.attr == "EXTERNAL_WRITE"):
                            stores.append((path.relative_to(SRC).as_posix(), node.lineno, ast.unparse(node.value) if getattr(node, "value", None) is not None else ""))
        self.assertEqual(len(stores), 1, "소스 상수에 값을 넣는 곳은 capabilities.py 의 `EXTERNAL_WRITE = False` 하나뿐이다")
        self.assertEqual((stores[0][0], stores[0][2]), ("capabilities.py", "False"))

    def test_no_other_module_even_names_the_constant_and_no_code_sets_it_by_string(self):
        found = []
        for path in src_files():
            if path.name == "capabilities.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Name) and node.id == "EXTERNAL_WRITE") or (isinstance(node, ast.Attribute) and node.attr == "EXTERNAL_WRITE")                         or (isinstance(node, ast.Constant) and node.value == "EXTERNAL_WRITE"):          # 이름을 글자로 쓰는 길(setattr·환경 변수 이름)도 없다
                    found.append((path.relative_to(SRC).as_posix(), getattr(node, "lineno", 0)))
        self.assertEqual(found, [], "capabilities.py 밖에서는 상수 이름을 쓰지 않는다 — 부르는 것은 관문 함수뿐이다")

    def test_the_capabilities_module_reads_nothing_from_outside(self):
        text = (SRC / "capabilities.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        tree = ast.parse(text)
        body = "\n".join(ast.unparse(node) for node in tree.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)))
        for word in ("environ", "getenv", "argv", "settings", "json", "open(", "read_text", "import os", "import sys", "argparse"):
            self.assertNotIn(word, body, f"capabilities.py 는 바깥에서 값을 읽지 않는다: {word}")
        self.assertIn("EXTERNAL_WRITE = False", code)

    def test_the_settings_file_has_no_field_for_it_and_still_refuses_unknown_fields(self):
        text = (SRC / "service" / "context.py").read_text(encoding="utf-8")
        for word in ("external_publish", "allow_publish", "external_write", "EXTERNAL_WRITE"):
            self.assertNotIn(word, text, word)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"schema": 1, "repo_path": "", "naver_profiles": {}, "external_publish": true}', encoding="utf-8")
            with self.assertRaises(AppError) as caught:
                Settings(path).repo_path()
            self.assertEqual(caught.exception.code, "SETTINGS_INVALID", "설정 파일에 그런 칸을 넣어도 읽지 않는다 — 켜지지 않는다")

    def test_the_command_line_has_no_switch_or_settings_command(self):
        parser = cli.build_parser()
        options, commands = set(), set()
        stack = [parser]
        while stack:
            current = stack.pop()
            for action in current._actions:
                options.update(action.option_strings)
                choices = getattr(action, "choices", None)
                if isinstance(choices, dict):
                    for name, child in choices.items():
                        commands.add(name)
                        stack.append(child)
        for word in options | commands:
            self.assertIsNone(re.search(r"(?i)external|allow|enable|switch|unlock", word), f"켜는 길처럼 보이는 명령·옵션: {word}")
        self.assertNotIn("settings", commands)

    def test_the_environment_variables_the_service_reads_are_only_the_two_locations(self):
        text = (SRC / "service" / "context.py").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(re.findall(r'ENV_[A-Z_]+ = "([A-Z_]+)"', text))), ["CHANCEBLOG_DESKTOP_DATA", "CHANCEBLOG_LOCAL_REPO"])

    def test_no_code_in_src_registers_an_adapter(self):
        calls = []
        for path in src_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    if name in ("external.register", "register", "external.registered", "registered") and path.name != "external.py":
                        calls.append((path.relative_to(SRC).as_posix(), node.lineno, name))
        self.assertEqual(calls, [], "어댑터를 꽂는 코드가 src 에 없다(시험만 꽂는다)")
        self.assertEqual(external.registered_kinds(), (), "이 빌드는 어떤 어댑터도 꽂지 않는다")

    def test_the_registry_only_knows_three_kinds_and_a_test_can_plug_one_temporarily(self):
        self.assertEqual(external.KINDS, ("pages_git", "blogger", "naver_publish"))
        with self.assertRaises(ValueError):
            external.register("unknown_kind", lambda **parts: None)
        with self.assertRaises(ValueError):
            external.register("pages_git", "not callable")
        marker = object()
        with external.registered(external.KIND_PAGES_GIT, lambda **parts: marker):
            self.assertEqual(external.registered_kinds(), ("pages_git",))
            self.assertIs(external.pages_backend(), marker)
        self.assertEqual(external.registered_kinds(), ())
        self.assertIsInstance(external.pages_backend(), external.LocalOnlyBackend)


class EntryPointGateTest(unittest.TestCase):
    def test_every_entry_point_passes_the_gate_as_its_first_statement(self):
        for rel, name in ENTRY_POINTS:
            with self.subTest(entry=f"{rel}:{name}"):
                body = statements(function_node(parse(rel), name))
                self.assertTrue(body and is_gate_call(body[0]), f"{rel}:{name} 의 첫 문장이 관문이 아니다 — {ast.unparse(body[0])[:70] if body else '(비었다)'}")

    def test_the_two_online_entry_points_pass_the_gate_first_inside_their_online_branch(self):
        for rel, name in CONDITIONAL_ENTRY_POINTS:
            with self.subTest(entry=f"{rel}:{name}"):
                body = statements(function_node(parse(rel), name))
                first = body[0]
                self.assertIsInstance(first, ast.If)
                self.assertIn("online", ast.unparse(first.test))
                self.assertTrue(is_gate_call(first.body[0]), ast.unparse(first.body[0])[:70])

    def test_the_publish_flow_gate_comes_before_the_confirmation_and_before_any_store_or_git_use(self):
        for name in ("run_pages_publish", "cancel_pages_publish"):
            body = statements(function_node(parse("service/pages_flow.py"), name))
            self.assertTrue(is_gate_call(body[0]))
            self.assertEqual(ast.unparse(body[1].value.func), "require_confirmation", name)

    def test_the_only_subprocess_launcher_is_the_gated_run_command(self):
        launches = []
        for path in src_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and ast.unparse(node.func) in ("subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "os.system", "os.popen"):
                    launches.append((path.relative_to(SRC).as_posix(), ast.unparse(node.func)))
        self.assertEqual(sorted(launches), [("publish/gitrepo.py", "subprocess.Popen"), ("publish/gitrepo.py", "subprocess.run")],
                         "하위 프로세스를 띄우는 곳은 gitrepo.py 의 run_command(관문 안)와 시간 초과 때 그 자식을 끄는 taskkill 뿐이다")
        tree = parse("publish/gitrepo.py")
        for node in ast.walk(function_node(tree, "run_command")):
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "subprocess.Popen":
                break
        else:
            self.fail("run_command 안에 Popen 이 있어야 한다")
        kill_tree = ast.unparse(function_node(tree, "_kill_tree"))
        self.assertIn("taskkill", kill_tree)


class RefusalWithoutOutgoingCallsTest(unittest.TestCase):
    """꺼진 채 불러 보면 하위 프로세스·소켓·HTTP 를 한 번도 부르기 전에 거절한다 — 가짜 backend·가짜 git 도 한 번도 불리지 않는다."""

    def setUp(self):
        self.assertIs(capabilities.EXTERNAL_WRITE, False, "이 시험은 관문을 켜지 않은 그대로 돈다")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)
        self.project_id = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        self.post = PagesPost(ss.KO_PATH, ss.ko_text(), "경제·일", "ko")
        self.spy_calls = []

        def spy_git(cwd, args, timeout=0, input_bytes=None):
            self.spy_calls.append(list(args))
            return gitrepo.GitResult(0, "", "")

        self.spy_git = spy_git

    def refused(self, label, call):
        with og.Tripwire() as wire:
            with self.assertRaises(AppError, msg=label) as caught:
                call()
        self.assertEqual(caught.exception.code, "EXTERNAL_WRITE_DISABLED", label)
        self.assertEqual(wire.calls, [], f"{label}: 하위 프로세스·소켓·HTTP 호출이 일어났다")

    def test_the_low_level_git_and_publish_modules_refuse_before_any_outgoing_call(self):
        repo = self.tmp / "chanceblog"
        info = pages.CommitInfo(ss.KO_PATH, "c" * 40, "b" * 40)
        cases = {
            "run_command": lambda: gitrepo.run_command(["git", "--version"]),
            "run_git": lambda: gitrepo.run_git(self.tmp, ["--version"]),
            "run_git(fetch)": lambda: gitrepo.run_git(self.tmp, ["fetch", "origin"]),
            "run_git(push)": lambda: gitrepo.run_git(self.tmp, ["push", "origin", "main"]),
            "sync_latest": lambda: gitrepo.sync_latest(repo, self.spy_git),
            "check_push_access": lambda: gitrepo.check_push_access(repo, self.spy_git),
            "commit_post": lambda: pages.commit_post(repo, self.post, git=self.spy_git),
            "push_commit": lambda: pages.push_commit(repo, self.post, git=self.spy_git),
            "discard_commit": lambda: pages.discard_commit(repo, info, git=self.spy_git),
            "publish_post": lambda: pages.publish_post(repo, self.post, git=self.spy_git),
            "check_deployed": lambda: deploy.check_deployed(repo, self.post.path, self.post.text),
        }
        for label, call in cases.items():
            with self.subTest(label=label):
                self.refused(label, call)
        self.assertEqual(self.spy_calls, [], "가짜 git 도 한 번도 불리지 않았다")

    def test_the_publish_flow_refuses_before_it_touches_the_store_or_the_backend(self):
        cases = {
            "plan_pages_publish": lambda: pages_flow.plan_pages_publish(self.ctx, self.project_id),
            "preview_publish": lambda: pages_flow.preview_publish(self.ctx, self.project_id),
            "run_pages_publish": lambda: pages_flow.run_pages_publish(self.ctx, self.project_id, confirmed=True),
            "run_pages_publish(no wait)": lambda: pages_flow.run_pages_publish(self.ctx, self.project_id, confirmed=True, wait=False),
            "check_pages_deploy": lambda: pages_flow.check_pages_deploy(self.ctx, self.project_id),
            "cancel_pages_publish": lambda: pages_flow.cancel_pages_publish(self.ctx, self.project_id, confirmed=True),
        }
        for label, call in cases.items():
            with self.subTest(label=label):
                self.refused(label, call)
        self.assertEqual(self.backend.calls, [], "가짜 backend 는 한 번도 불리지 않았다(승인·확인이 모두 있어도)")
        self.assertEqual(ss.status_of(self.ctx, self.project_id), "APPROVED", "글의 상태도 그대로다")

    def test_a_git_backend_refuses_its_write_and_network_methods_before_calling_git(self):
        backend = GitPagesBackend(git=self.spy_git, expected_origin=ss.LOCAL_ORIGIN)
        info = pages.CommitInfo(ss.KO_PATH, "c" * 40, "b" * 40)
        repo = self.tmp / "chanceblog"
        cases = {"check_push_access": lambda: backend.check_push_access(repo), "commit": lambda: backend.commit(repo, self.post, "제목"), "push": lambda: backend.push(repo, self.post),
                 "discard": lambda: backend.discard(repo, info), "check_deployed": lambda: backend.check_deployed(repo, self.post, ss.NOW, 1, 1)}
        for label, call in cases.items():
            with self.subTest(label=label):
                self.refused(label, call)
        self.assertEqual(self.spy_calls, [])

    def test_the_command_line_commands_refuse_whatever_the_flags_say(self):
        argvs = (["publish-pages", self.project_id], ["publish-pages", self.project_id, "--yes"], ["publish-pages", self.project_id, "--yes", "--no-wait"],
                 ["publish-pages", self.project_id, "--cancel", "--yes"], ["check-deploy", self.project_id], ["doctor", "--online"])
        for argv in argvs:
            with self.subTest(argv=" ".join(argv[:1] + argv[2:])), og.Tripwire() as wire:
                out, err = io.StringIO(), io.StringIO()
                code = cli.main(argv, out=out, err=err, ctx=self.ctx, env={})
                self.assertEqual(code, 1)
                self.assertIn("EXTERNAL_WRITE_DISABLED", err.getvalue())
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(wire.calls, [])
        self.assertEqual(self.backend.calls, [])


class DefaultsTest(unittest.TestCase):
    def test_context_defaults_refuse_git_and_make_a_local_only_backend(self):
        self.assertIs(Context.__dataclass_fields__["git"].default, external.refusing_git)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(data_dir=str(Path(tmp) / "data"), env={})
            self.assertIs(ctx.git, external.refusing_git)
            self.assertIsInstance(ctx.backend, external.LocalOnlyBackend)
            self.assertIs(ctx.backend.git, external.refusing_git)
            with og.Tripwire() as wire:
                with self.assertRaises(AppError) as caught:
                    ctx.git(tmp, ["rev-parse", "HEAD"])
            self.assertEqual((caught.exception.code, wire.calls), ("EXTERNAL_WRITE_DISABLED", []))

    def test_the_context_module_no_longer_names_the_real_git_runner(self):
        text = (SRC / "service" / "context.py").read_text(encoding="utf-8")
        self.assertNotIn("run_git", text, "Context 가 기본으로 실제 git 실행기를 참조하지 않는다")
        self.assertNotIn("GitPagesBackend", text)

    def test_the_local_only_backend_answers_what_it_can_from_files_and_refuses_the_rest(self):
        backend = external.LocalOnlyBackend()
        repo = Path("not-used")
        post = PagesPost(ss.KO_PATH, ss.ko_text(), "경제·일", "ko")
        self.assertIsNone(backend.unpushed_count(repo))
        self.assertEqual(backend.unpushed_made_by_app(repo), 0)
        self.assertFalse(backend.on_remote(repo, ss.KO_PATH))
        self.assertFalse(backend.post_in_head(repo, ss.KO_PATH))
        self.assertIsNone(backend.orphan_commit(repo, "x", "경제·일", "ko"))
        self.assertIsNone(backend.progress)
        for label, call in {"head_commit": lambda: backend.head_commit(repo), "current_commit": lambda: backend.current_commit(repo, ss.KO_PATH), "check_push_access": lambda: backend.check_push_access(repo),
                            "commit": lambda: backend.commit(repo, post, "제목"), "push": lambda: backend.push(repo, post), "discard": lambda: backend.discard(repo, None),
                            "check_deployed": lambda: backend.check_deployed(repo, post, ss.NOW, 1, 1)}.items():
            with self.subTest(label=label), self.assertRaises(AppError) as caught:
                call()
            self.assertEqual(caught.exception.code, "EXTERNAL_WRITE_DISABLED")

    def test_the_local_only_backend_scans_the_posts_folder_without_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "_posts" / "경제·일").mkdir(parents=True)
            text = ss.ko_text()
            (repo / ss.KO_PATH).write_text(text, encoding="utf-8", newline="\n")
            (repo / "_posts" / "다른분야").mkdir()
            (repo / "_posts" / "다른분야" / "2026-11-02-KR-103012.markdown").write_text("다른 글", encoding="utf-8")
            backend = external.LocalOnlyBackend()
            post = PagesPost(ss.KO_PATH, text, "경제·일", "ko")
            with og.Tripwire() as wire:
                self.assertEqual(backend.duplicates(repo, post), ["_posts/경제·일/2026-11-02-KR-103012.md", "_posts/다른분야/2026-11-02-KR-103012.markdown"])
                self.assertEqual(backend.same_content(repo, text), [ss.KO_PATH])
                self.assertEqual(backend.same_content(repo, text + "다름"), [])
            self.assertEqual(wire.calls, [])


class InspectFolderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "chanceblog"
        (self.root / ".git").mkdir(parents=True)

    def write(self, config=None, head="ref: refs/heads/main\n"):
        if config is not None:
            (self.root / ".git" / "config").write_text(config, encoding="utf-8")
        if head is not None:
            (self.root / ".git" / "HEAD").write_text(head, encoding="utf-8")

    GOOD = '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/shine88pc/chanceblog.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n[branch "main"]\n\tremote = origin\n'

    def test_a_proper_checkout_is_read_from_files_only(self):
        self.write(self.GOOD)
        with og.Tripwire() as wire:
            info = external.inspect_folder(self.root)
        self.assertEqual((info.branch, info.origin, info.head), ("main", "https://github.com/shine88pc/chanceblog.git", ""))
        self.assertEqual(wire.calls, [])

    def test_credentials_in_the_origin_address_are_hidden_in_the_result(self):
        self.write(self.GOOD.replace("https://github.com/", "https://user:pw12345@github.com/"))
        info = external.inspect_folder(self.root)
        sec.assert_no_secret(self, "pw12345", info.origin, "연결 결과의 origin")
        self.assertIn("***@", info.origin)

    def test_the_wrong_origin_the_missing_origin_and_the_second_wrong_url_are_refused(self):
        cases = {"다른 저장소": self.GOOD.replace("shine88pc/chanceblog", "someone/else"), "origin 없음": "[core]\n\tbare = false\n",
                 "올리는 주소만 다름": self.GOOD.replace("\tfetch = ", "\tpushurl = https://github.com/someone/else.git\n\tfetch = "), "다른 호스트": self.GOOD.replace("github.com", "example.test")}
        for label, config in cases.items():
            with self.subTest(label=label):
                self.write(config)
                with self.assertRaises(AppError) as caught:
                    external.inspect_folder(self.root)
                self.assertEqual(caught.exception.code, "PAGES_LOCAL_REPO_INVALID")

    def test_a_branch_other_than_main_and_a_detached_head_are_refused_with_the_branch_name(self):
        self.write(self.GOOD, head="ref: refs/heads/work\n")
        with self.assertRaises(AppError) as caught:
            external.inspect_folder(self.root)
        self.assertEqual((caught.exception.code, caught.exception.slots), ("PAGES_LOCAL_REPO_NOT_MAIN", {"브랜치": "work"}))
        self.write(self.GOOD, head="0123456789012345678901234567890123456789\n")
        with self.assertRaises(AppError) as caught:
            external.inspect_folder(self.root)
        self.assertEqual((caught.exception.code, caught.exception.slots), ("PAGES_LOCAL_REPO_NOT_MAIN", {"브랜치": "(분리된 HEAD)"}))

    def test_missing_folders_unset_paths_a_git_file_and_unreadable_config_are_refused(self):
        for label, path in (("지정 안 함", None), ("빈 글", "  "), ("없는 폴더", self.root.parent / "nope")):
            with self.subTest(label=label), self.assertRaises(AppError) as caught:
                external.inspect_folder(path)
            self.assertEqual(caught.exception.code, "PAGES_LOCAL_REPO_INVALID")
        other = self.root.parent / "worktree"
        other.mkdir()
        (other / ".git").write_text("gitdir: ../elsewhere\n", encoding="utf-8")
        with self.assertRaises(AppError) as caught:
            external.inspect_folder(other)
        self.assertEqual(caught.exception.code, "PAGES_LOCAL_REPO_INVALID")
        self.write(None)                                                                      # .git 은 있는데 config 가 없다
        with self.assertRaises(AppError) as caught:
            external.inspect_folder(self.root)
        self.assertEqual(caught.exception.code, "PAGES_LOCAL_REPO_INVALID")

    def test_the_origin_reader_handles_quotes_comments_other_sections_and_case(self):
        text = '[REMOTE "origin"]\n  URL = "https://github.com/shine88pc/chanceblog"\n[remote "upstream"]\n\turl = https://example.test/x.git\n[remote "origin"]\n\tpushurl = git@github.com:shine88pc/chanceblog.git\n'
        self.assertEqual(external._origin_urls(text), ["https://github.com/shine88pc/chanceblog", "git@github.com:shine88pc/chanceblog.git"])
        self.assertEqual(external._origin_urls("[core]\nurl = x\n"), [])


class DoctorAndConnectTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = make_context(data_dir=str(self.tmp / "data"), env={})

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with og.Tripwire() as wire:
            code = cli.main(list(argv), out=out, err=err, ctx=self.ctx, env={})
        self.assertEqual(wire.calls, [], f"{argv}: 바깥으로 나가는 호출이 일어났다")
        return code, out.getvalue(), err.getvalue()

    def test_doctor_says_the_external_write_is_off_and_skips_git(self):
        code, out, err = self.run_main("doctor")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("[정상] 외부 게시 — 이 시험 버전에서는 꺼져 있어요", out)
        self.assertIn("[건너뜀] git — 이 시험 버전은 git 을 쓰지 않아요", out)
        self.assertIn("올리기 권한 — 점검하지 않았습니다", out)
        self.assertNotIn("doctor --online", out, "이 빌드는 글을 올리지 않으므로 거절되는 `doctor --online` 을 권하지 않는다(PCSEC1V D7)")
        self.assertIn("이 시험 버전은 글을 GitHub 에 올리지 않아요", out)

    def test_the_keys_purposes_note_for_github_says_nothing_is_published_while_the_gate_is_closed(self):
        """PCSEC1V D7: `keys purposes` 의 GitHub 안내가 'Git 로그인을 쓴다·터미널에서 git push 를 한다' 였다 — 이 빌드는 글을 올리지 않으므로 사실대로 말한다."""
        code, out, err = self.run_main("keys", "purposes")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(connections.GITHUB_OFF_NOTE, out)
        for stale in ("git push", "Git 자격 증명 관리자)을 씁니다", "터미널에서"):
            self.assertNotIn(stale, out)
        code, out, err = self.run_main("--json", "keys", "purposes")                       # `--json` 도 같은 문장이다(화면이 읽는 형태)
        self.assertEqual((code, err), (0, ""), out)
        purposes = {item["purpose"]: item for item in json.loads(out)["data"]["purposes"]}
        self.assertEqual(purposes["github_repo"]["note"], connections.GITHUB_OFF_NOTE)
        self.assertNotIn("git push", out)

    def test_the_old_note_comes_back_only_when_a_test_opens_the_gate_and_the_other_purposes_keep_theirs(self):
        spec = connections.PURPOSES["github_repo"]
        self.assertEqual(connections.purpose_note(spec), connections.GITHUB_OFF_NOTE)
        with mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
            self.assertEqual(connections.purpose_note(spec), spec.note)
            self.assertIn("Git 로그인", connections.purpose_note(spec))
        self.assertLessEqual(len(connections.GITHUB_OFF_NOTE), 160, "오류 문구 칸을 넘지 않는다")
        for other in connections.PURPOSES.values():
            if other.key != "github_repo":
                self.assertEqual(connections.purpose_note(other), other.note)
        with self.assertRaises(AppError) as caught:
            connections.add_entry(self.ctx, "github_repo", name="x", fields={})
        self.assertEqual(caught.exception.slots["이유"], connections.GITHUB_OFF_NOTE)

    def test_the_doctor_check_turns_into_a_warning_when_a_test_opens_the_gate(self):
        with mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
            check = doctor._check_external_write()
        self.assertEqual(check.status, "warn")
        self.assertIn("켜져 있습니다", check.message)

    def test_connect_reads_files_only_and_says_nothing_is_published(self):
        repo = self.tmp / "chanceblog"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "config").write_text(InspectFolderTest.GOOD, encoding="utf-8")
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        code, out, err = self.run_main("connect", str(repo))
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("연결했습니다", out)
        self.assertIn("이 시험 버전은 글을 올리지 않습니다", out)
        self.assertNotIn("doctor --online", out)
        self.assertEqual(self.ctx.settings.repo_path(), str(repo))

    def test_connect_refuses_a_folder_that_is_not_the_chanceblog_checkout(self):
        folder = self.tmp / "plain"
        folder.mkdir()
        code, out, err = self.run_main("connect", str(folder))
        self.assertEqual(code, 1)
        self.assertIn("PAGES_LOCAL_REPO_INVALID", err)
        self.assertFalse(self.ctx.workspace.settings_path.exists(), "거절하면 설정을 바꾸지 않는다")

    def test_preview_of_a_pages_post_still_works_without_git(self):
        repo = self.tmp / "chanceblog"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "config").write_text(InspectFolderTest.GOOD, encoding="utf-8")
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (repo / "_config.yml").write_text(ss.CONFIG, encoding="utf-8")
        self.assertEqual(self.run_main("connect", str(repo))[0], 0)
        code, out, err = self.run_main("new", "--title", "미리 보기 글", "--text", ss.ko_text())
        self.assertEqual((code, err), (0, ""), err)
        project_id = projects.list_projects(self.ctx)[0].project_id
        code, out, err = self.run_main("preview", project_id, "--platform", "pages", "--category", "경제·일", "--lang", "ko", "--image-url", "https://images.example.invalid/a.jpg")
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("공개 주소", out)


if __name__ == "__main__":
    unittest.main()
