"""최소 권한 — 앱은 Git 로그인 자체를 읽지도 저장하지도 출력하지도 않고, 대화창을 띄우지 않으며, 연결 해제는 설정 한 칸만 비운다(PUBPR 설계서 3.11, PT-40–44). 외부 접속 0.

지키는 것:
  1) `git credential` 계열 명령을 부르는 코드가 없고(`network_shape` 가 거절), 출력·오류·기록에 origin 에 심은 카나리 토큰이 한 번도 나오지 않는다(PT-40).
  2) 인증 오류는 한 번만 알리고 자동으로 다시 올리지 않는다(PT-41).
  3) 모든 git 호출의 환경에서 대화창이 꺼져 있고(`GIT_TERMINAL_PROMPT=0`·`GCM_INTERACTIVE=false`) 질문 도우미 변수는 지워지며 ssh 는 질문 대신 실패한다(PT-42).
  4) `disconnect` 는 설정의 `repo_path` 하나만 비운다 — 저장소 폴더·가지·글·발행 기록·다른 설정·비밀 보관소는 그대로다(PT-43).
  5) 재인증 안내에 main 으로 가는 push 를 권하는 말이 없다(PT-44).
"""
import ast
import json
import os
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.publish import gitrepo, pages  # noqa: E402
from chanceblog_desktop.publish.gitrepo import GitResult  # noqa: E402
from chanceblog_desktop.service import pages_flow  # noqa: E402
from chanceblog_desktop.service.journal import Journal  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
CANARY = "CANARY_" + "PUBPR" + "_" + "TOKEN" + "0123456789abcdef"            # 조립한 가짜 비밀 — 저장소에는 키 모양 글이 없다
URL_WITH_TOKEN = f"https://someone:{CANARY}@github.com/{gitrepo.EXPECTED_OWNER}/{gitrepo.EXPECTED_REPO}.git"


Post = namedtuple("Post", "path text")
KO_POST = Post("_posts/경제·일/2026-10-29-KR-101652.md", (ss.ROOT / "tests" / "fixtures" / "chance_post_ko.md").read_text(encoding="utf-8"))
BOX = None


def setUpModule():
    global BOX
    ss.external_write_on()
    if ss.HAVE_GIT:
        BOX = ss.GitSandbox()


def tearDownModule():
    if BOX is not None:
        BOX.cleanup()
    ss.external_write_off()


class Spy:
    """진짜 git 을 부르되 호출을 기록하고 지정한 명령은 가짜 결과로 바꾼다."""

    def __init__(self, fake=None):
        self.calls, self.fake = [], dict(fake or {})

    def __call__(self, cwd, args, timeout=gitrepo.DEFAULT_TIMEOUT, input_bytes=None):
        self.calls.append(list(args))
        return self.fake[args[0]] if args[0] in self.fake else gitrepo.run_git(cwd, args, timeout, input_bytes)

    def pushes(self):
        return [call for call in self.calls if call[0] == "push"]


def canned_git(origin_url, branch="main"):
    """`inspect_repo` 가 부르는 읽기 명령에 정해진 답만 하는 가짜 git — 원격 주소를 마음대로 바꿔 끼울 수 있다."""
    def git(cwd, args, timeout=0, input_bytes=None):
        if args[:2] == ["rev-parse", "--show-toplevel"]:
            return GitResult(0, str(cwd) + "\n", "")
        if args[0] == "remote":
            return GitResult(0, origin_url + "\n", "")
        if args[0] == "symbolic-ref":
            return GitResult(0, f"refs/heads/{branch}\n", "")
        if args[0] == "status":
            return GitResult(0, "", "")
        if args[:2] == ["rev-parse", "HEAD"]:
            return GitResult(0, "a" * 40 + "\n", "")
        return GitResult(1, "", "unexpected")
    return git


class CredentialTest(unittest.TestCase):
    def test_app_never_reads_or_stores_git_credentials(self):
        """PT-40 — 원격 주소에 심은 카나리 토큰이 읽은 결과·오류 글·로그 줄·발행 기록 어디에도 나오지 않고, `credential` 계열 명령은 앱 길에서 거절된다."""
        with tempfile.TemporaryDirectory() as tmp:
            info = gitrepo.inspect_repo(tmp, canned_git(URL_WITH_TOKEN), gitrepo.EXPECTED_ORIGIN)
            self.assertNotIn(CANARY, repr(info))
            wrong = f"https://someone:{CANARY}@github.com/someoneelse/other.git"
            error = ss.code_of(gitrepo.inspect_repo, tmp, canned_git(wrong), gitrepo.EXPECTED_ORIGIN)
            self.assertEqual(error.code, "PAGES_LOCAL_REPO_INVALID")
            for text in (error.detail, str(error), error.log_line(), repr(error), json.dumps(error.rendered().__dict__, default=str, ensure_ascii=False)):
                self.assertNotIn(CANARY, text)
        failure = gitrepo._failure(GitResult(128, "", f"fatal: unable to access '{URL_WITH_TOKEN}/': Could not resolve host: github.com"), "새 가지에 올리기")
        for text in (failure.detail, str(failure), failure.log_line()):
            self.assertNotIn(CANARY, text)
        self.assertNotIn(CANARY, gitrepo.hide_credentials(f"remote: {URL_WITH_TOKEN} failed"))
        for args in (["credential", "fill"], ["credential-store", "get"], ["credential-manager", "get"], ["config", "--get", "credential.helper", "x"], ["config", "--global", "credential.helper", "store"],
                     ["remote", "set-url", "origin", URL_WITH_TOKEN], ["push", "--porcelain", "--no-verify", URL_WITH_TOKEN, f"{'a' * 40}:refs/heads/desktop/post-20261102-103012-3bf91f62"]):
            with self.subTest(args=args[0] + " " + args[1]):
                self.assertEqual(ss.code_of(gitrepo.network_shape, args).code, "PAGES_PUSH_REFUSED")

    def test_no_source_runs_a_credential_command_or_reads_a_credential_store(self):
        """git 을 돌리는 곳(`publish/`·`service/`)에 `credential` 계열 명령 이름이 나오는 곳은 인자 표의 '거절 목록'(`publish/gitrepo.py`) 한 곳뿐이다."""
        names = ("credential", "credential-store", "credential-manager", "credential-cache")
        found = []
        for path in sorted(SRC.rglob("*.py")):
            rel = path.relative_to(SRC).as_posix()
            if "__pycache__" in path.parts or not rel.startswith(("publish/", "service/")):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docs = {node.body[0].value for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docs and node.value in names:
                    found.append((rel, node.value))
        self.assertTrue(found, "빈 시험이 아니다 — 거절 목록에는 이 이름들이 있다")
        self.assertEqual(sorted({rel for rel, _name in found}), ["publish/gitrepo.py"])
        self.assertFalse([name for rel, name in found if name not in ("credential", "credential-store", "credential-manager", "credential-cache")])


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class AuthFailureTest(unittest.TestCase):
    def test_auth_failure_is_reported_once_with_no_automatic_retry(self):
        """PT-41 — 인증 오류는 코드 하나로 한 번만 알린다: push 는 한 번이고 같은 명령을 다시 시도하거나 다른 길을 찾지 않는다. 오류 글에 원격 주소의 토큰이 나오지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            _origin, work = BOX.copy_into(Path(tmp))
            built = pages.build_branch_commit(work, KO_POST, expected_origin=ss.LOCAL_ORIGIN)
            denied = GitResult(128, "", "remote: Invalid username or password.\n" + f"fatal: Authentication failed for '{URL_WITH_TOKEN}/'")
            spy = Spy({"push": denied})
            error = ss.code_of(pages.push_branch, work, built, KO_POST, git=spy, expected_origin=ss.LOCAL_ORIGIN)
            self.assertEqual(error.code, "GIT_PUSH_AUTH")
            self.assertEqual(len(spy.pushes()), 1, "자동 재시도 0")
            self.assertNotIn(CANARY, error.detail + str(error) + error.log_line())
            for call in spy.calls:
                if call[0] in ("fetch", "push", "ls-remote"):
                    self.assertIn(gitrepo.network_shape(call), ("ls_remote", "push_branch", "fetch_main"))


class PromptTest(unittest.TestCase):
    def run_all(self, env_extra=None):
        seen = []

        def recorder(command, *, env=None, timeout=0, label="", input_bytes=None):
            seen.append((list(command), dict(env or {})))
            return GitResult(0, "", "")

        head = "a" * 40
        branch = "desktop/post-20261102-103012-3bf91f62"
        calls = [["status"], list(gitrepo.FETCH_MAIN_ARGS), ["ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"], ["push", "--porcelain", "--no-verify", "origin", f"{head}:refs/heads/{branch}"],
                 ["push", "--dry-run", "--porcelain", "--no-verify", "origin", f"{head}:refs/heads/desktop/check-aaaaaaaa"], ["rev-parse", "HEAD"]]
        with mock.patch.dict(os.environ), mock.patch.object(gitrepo, "run_command", recorder):
            for key in ("GIT_SSH", "GIT_SSH_COMMAND"):
                os.environ.pop(key, None)
            os.environ.update(env_extra or {})
            for args in calls:
                gitrepo.run_git("C:/repo", args)
        return seen

    def test_prompts_are_disabled_in_every_git_call(self):
        """PT-42 — 모든 git 호출(로컬·받기·확인·올리기·점검)의 환경: 대화창 끔 · 질문 도우미 변수 없음 · 영어 고정 · 편집기 창 없음. 받기·올리기는 ssh 도 질문 대신 실패한다."""
        poison = {"GIT_ASKPASS": "evil", "SSH_ASKPASS": "evil", "GIT_TERMINAL_PROMPT": "1", "GCM_INTERACTIVE": "always", "GIT_EDITOR": "vim", "LC_ALL": "ko_KR.UTF-8"}
        seen = self.run_all(poison)
        self.assertGreaterEqual(len(seen), 6)
        for command, env in seen:
            label = " ".join(command[3:8])
            self.assertEqual((env.get("GIT_TERMINAL_PROMPT"), env.get("GCM_INTERACTIVE")), ("0", "false"), label)
            self.assertNotIn("GIT_ASKPASS", env, label)
            self.assertNotIn("SSH_ASKPASS", env, label)
            self.assertEqual((env.get("LC_ALL"), env.get("GIT_EDITOR")), ("C", "true"), label)
        network = [env for command, env in seen if "fetch" in command or "push" in command or "ls-remote" in command]
        self.assertEqual(len(network), 4, "받기·가지 확인·올리기·올리기 점검")
        for env in network:
            self.assertEqual(env.get("GIT_SSH_COMMAND"), "ssh -o BatchMode=yes", "사용자가 ssh 를 정하지 않았으면 질문 대신 실패하는 ssh")

    def test_the_users_own_ssh_command_is_left_alone(self):
        seen = self.run_all({"GIT_SSH_COMMAND": "ssh -i C:/keys/mine"})
        for command, env in seen:
            if any(word in command for word in ("fetch", "push", "ls-remote")):
                self.assertEqual(env.get("GIT_SSH_COMMAND"), "ssh -i C:/keys/mine")


class DisconnectTest(unittest.TestCase):
    def test_disconnect_clears_only_the_repo_setting(self):
        """PT-43 — 설정의 `repo_path` 한 칸만 비운다: 다른 설정·저장소 폴더·병합 대기 글·발행 기록·비밀 보관소는 그대로이고 git 은 한 번도 부르지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp)
            ss.naver_profiles(ctx)
            git_calls = []
            ctx.git = lambda cwd, args, timeout=0, input_bytes=None: git_calls.append(list(args)) or GitResult(0, "", "")
            project_id = ss.make_approved(ctx)
            report = pages_flow.run_pages_publish(ctx, project_id, confirmed=True)
            self.assertEqual(report.status, st.MERGE_PENDING)
            settings_file = ctx.settings.path
            before = json.loads(settings_file.read_text(encoding="utf-8"))
            self.assertTrue(before["repo_path"])
            repo_dir = Path(before["repo_path"])
            journal_before = Journal(ctx.workspace.journal_dir).read(project_id)
            keys_before = ss.tree_snapshot(ctx.workspace.root)
            code, out, err = ss.run_cli(ctx, "disconnect")
            self.assertEqual((code, err), (0, ""), err)
            self.assertIn("저장소 폴더 위치만", out)
            after = json.loads(settings_file.read_text(encoding="utf-8"))
            self.assertEqual(after["repo_path"], "")
            self.assertEqual({key: value for key, value in after.items() if key != "repo_path"}, {key: value for key, value in before.items() if key != "repo_path"}, "다른 설정은 한 칸도 안 바뀐다")
            self.assertTrue((repo_dir / ".git").is_dir(), "저장소 폴더는 그대로다")
            self.assertEqual(ss.status_of(ctx, project_id), st.MERGE_PENDING, "병합 대기 글은 목록에 남는다")
            self.assertEqual(Journal(ctx.workspace.journal_dir).read(project_id), journal_before)
            changed = {key for key in keys_before if ss.tree_snapshot(ctx.workspace.root).get(key) != keys_before[key]}
            self.assertEqual({Path(key).name for key in changed}, {settings_file.name}, "데이터 폴더에서 바뀐 파일은 설정 파일 하나뿐이다")
            self.assertEqual(git_calls, [], "연결 해제는 git 을 부르지 않는다")
            again_code, again_out, _err = ss.run_cli(ctx, "disconnect")
            self.assertEqual(again_code, 0)
            self.assertIn("바꾼 것이 없습니다", again_out)
            code, out, err = ss.run_cli(ctx, "merge-check", project_id)
            self.assertNotEqual(code, 0, "연결이 없으면 병합 확인은 멈춘다")
            self.assertEqual(ss.status_of(ctx, project_id), st.MERGE_PENDING)

    def test_disconnect_deletes_nothing_remote_and_names_how_to_remove_the_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp)
            code, out, _err = ss.run_cli(ctx, "disconnect")
            self.assertEqual(code, 0)
            self.assertIn("자격 증명 관리자", out)
            self.assertIn("올려 둔 가지", out)
            source = (SRC / "service" / "cli.py").read_text(encoding="utf-8")
            body = source[source.index("def cmd_disconnect"):source.index("def cmd_naver_package")]
            for word in ("run_git", "backend.", "push", "delete", "unlink", "rmtree"):
                self.assertNotIn(word, body.split('"""', 2)[2], word)


class ReauthGuidanceTest(unittest.TestCase):
    def test_reauth_guidance_has_no_main_push_advice(self):
        """PT-44 — 인증 오류의 안내(사용자 문구·하실 일)에 터미널에서 `git push` 를 해 보라는 말이 없다(그것은 main 으로 가는 push 를 권하는 문장이 된다). 새 안내는 로그인만 말한다."""
        for code, info in CATALOG.items():
            for text in (info.message, info.action):
                self.assertNotRegex(text, r"(?i)git push\b(?!\s*--dry)", f"{code}: main 으로 가는 push 를 권하는 말")
        auth = CATALOG["GIT_PUSH_AUTH"]
        self.assertIn("Git 을 쓰는 프로그램", auth.action)
        self.assertIn("앱은 비밀번호나 토큰을 읽거나 저장하지 않아요", auth.action)
        text = (ss.ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if "GIT_PUSH_AUTH" in line and line.lstrip().startswith("|"))
        self.assertNotIn("git push", row)


if __name__ == "__main__":
    unittest.main()
