"""git 인자 표와 가지 이름 시험(PUBPR P2, 설계서 PT-01–08 — 정책 시험은 git 을 띄우지 않는다, D-741).

지키는 것 — 'main 에 직접 올리지 못한다' 의 네 겹 가운데 앞의 셋과 환경 정리:
  1) git 이 네트워크로 나가는 명령(`fetch`·`push`·`ls-remote`·`pull`·`clone`)은 `run_git` 한 곳에서 **정확히 네 모양**(받기·가지 확인·가지 올리기·올리기 점검)만 지나고, 그 밖은 하위 프로세스를 띄우기 전에 `PAGES_PUSH_REFUSED`(PT-01·02·08).
  2) 가지 이름은 상수 접두사와 숫자·16진수로만 만들어지고 사용자 글(제목·분야·태그)에서 온 글자가 한 글자도 없으며 블로그 저장소의 자동화(`ai/claude/**`)를 깨우지 않는다(PT-03·04).
  3) 항상 붙는 `-c` 설정이 사용자 설정이 push 를 넓히지 못하게 덮어쓴다(PT-05).
  4) 소스에 `refs/heads/main` 으로 가는 refspec 을 만드는 코드가 없다 — 받는 쪽 상수 한 곳뿐이다(PT-06, AST).
  5) 네트워크 명령 직전마다 origin 을 다시 읽어 견준다(PT-07 — 진짜 git·로컬 bare 저장소는 `test_pages_branch_build.py`).
  6) 올리기 길의 환경에서 인증서 검증을 끄거나 설정을 덮어쓰거나 통신 내용을 기록하게 하는 변수가 지워진다(NET '켜기 전 필수 조건' 마무리).
"""
import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import outgoing_support as og  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import gitrepo, pages  # noqa: E402
from chanceblog_desktop.render.pages import PagesPost  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
SHA = "0123456789abcdef0123456789abcdef01234567"
BRANCH = "desktop/post-20261102-103012-3bf91f62"
CHECK = "desktop/check-01234567"
FETCH = list(gitrepo.FETCH_MAIN_ARGS)
LS_REMOTE = ["ls-remote", "--exit-code", "origin", f"refs/heads/{BRANCH}"]
PUSH = ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{BRANCH}"]
DRY_RUN = ["push", "--dry-run", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{CHECK}"]
ALLOWED = {"fetch_main": FETCH, "ls_remote": LS_REMOTE, "push_branch": PUSH, "push_check": DRY_RUN}

REFUSED_PUSHES = {
    "main 이름만": ["push", "origin", "main"], "main 전체 이름": ["push", "origin", "refs/heads/main"], "HEAD:main": ["push", "--porcelain", "--no-verify", "origin", "HEAD:main"],
    "커밋:main": ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/main"], "커밋:main(짧게)": ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:main"],
    "강제 접두사": ["push", "--porcelain", "--no-verify", "origin", f"+{SHA}:refs/heads/{BRANCH}"], "강제 접두사 main": ["push", "--porcelain", "--no-verify", "origin", f"+{SHA}:refs/heads/main"],
    "삭제": ["push", "--porcelain", "--no-verify", "origin", f":refs/heads/{BRANCH}"], "삭제(--delete)": ["push", "--porcelain", "--no-verify", "--delete", "origin", BRANCH],
    "--force": ["push", "--force", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{BRANCH}"], "-f": ["push", "-f", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{BRANCH}"],
    "--force-with-lease": ["push", "--force-with-lease", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{BRANCH}"],
    "--mirror": ["push", "--mirror", "origin"], "--all": ["push", "--all", "origin"], "--tags": ["push", "--tags", "origin"], "--prune": ["push", "--prune", "origin", f"{SHA}:refs/heads/{BRANCH}"],
    "refspec 둘": ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{BRANCH}", f"{SHA}:refs/heads/main"],
    "origin 대신 주소": ["push", "--porcelain", "--no-verify", "https://github.com/someone/else.git", f"{SHA}:refs/heads/{BRANCH}"],
    "origin 대신 폴더": ["push", "--porcelain", "--no-verify", "C:/other/place.git", f"{SHA}:refs/heads/{BRANCH}"],
    "옵션 순서 바뀜": ["push", "--no-verify", "--porcelain", "origin", f"{SHA}:refs/heads/{BRANCH}"], "옵션 하나 빠짐": ["push", "--porcelain", "origin", f"{SHA}:refs/heads/{BRANCH}"],
    "여분 옵션": ["push", "--porcelain", "--no-verify", "--atomic", "origin", f"{SHA}:refs/heads/{BRANCH}"], "푸시 옵션": ["push", "--porcelain", "--no-verify", "-o", "x", "origin", f"{SHA}:refs/heads/{BRANCH}"],
    "수신 명령 지정": ["push", "--receive-pack=evil", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{BRANCH}"], "커밋이 짧다": ["push", "--porcelain", "--no-verify", "origin", f"{SHA[:12]}:refs/heads/{BRANCH}"],
    "커밋이 대문자": ["push", "--porcelain", "--no-verify", "origin", f"{SHA.upper()}:refs/heads/{BRANCH}"], "가지 모양 틀림": ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/desktop/post-x"],
    "다른 접두사": ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/ai/claude/post-20261102-103012-3bf91f62"], "가지 이름 뒤 줄바꿈": ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{BRANCH}\n"],
    "refs/tags": ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/tags/{BRANCH}"], "점검 가지에 진짜 올리기": ["push", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{CHECK}"],
    "점검 모양에 post 가지": ["push", "--dry-run", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/{BRANCH}"], "점검 모양에 main": ["push", "--dry-run", "--porcelain", "--no-verify", "origin", f"{SHA}:refs/heads/main"],
    "점검 모양에 강제": ["push", "--dry-run", "--porcelain", "--no-verify", "origin", f"+{SHA}:refs/heads/{CHECK}"], "인자 없는 push": ["push"],
}
REFUSED_OTHERS = {
    "받기에 다른 refspec": ["fetch", "--quiet", "origin", "+refs/heads/*:refs/remotes/origin/*"], "받기에 main 아닌 가지": ["fetch", "--quiet", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/x"],
    "받기에 --all": ["fetch", "--all"], "받기에 인자 없음": ["fetch"], "받기에 origin 만": ["fetch", "origin"], "받기에 주소": ["fetch", "--quiet", "https://github.com/x/y.git", "+refs/heads/main:refs/remotes/origin/main"],
    "받기에 태그": ["fetch", "--quiet", "--tags", "origin", "+refs/heads/main:refs/remotes/origin/main"], "받기에 --prune": ["fetch", "--quiet", "--prune", "origin", "+refs/heads/main:refs/remotes/origin/main"],
    "받기의 refspec 앞 +없음": ["fetch", "--quiet", "origin", "refs/heads/main:refs/remotes/origin/main"],
    "ls-remote 에 모든 가지": ["ls-remote", "origin"], "ls-remote 에 --heads": ["ls-remote", "--heads", "origin"], "ls-remote 에 주소": ["ls-remote", "--exit-code", "https://github.com/x/y.git", f"refs/heads/{BRANCH}"],
    "ls-remote 에 main": ["ls-remote", "--exit-code", "origin", "refs/heads/main"], "ls-remote 에 무늬": ["ls-remote", "--exit-code", "origin", "refs/heads/desktop/*"], "ls-remote 에 --exit-code 없음": ["ls-remote", "origin", f"refs/heads/{BRANCH}"],
    "pull": ["pull"], "pull origin main": ["pull", "origin", "main"], "pull --ff-only": ["pull", "--ff-only", "origin", "main"], "clone": ["clone", "https://github.com/x/y.git", "z"], "clone 인자 없음": ["clone"],
    "알 수 없는 받기": ["fetch-pack", "origin"], "send-pack": ["send-pack", "origin", "main"], "upload-pack": ["upload-pack", "."], "receive-pack": ["receive-pack", "."], "submodule": ["submodule", "update"],
    "remote update(원격에 닿는다)": ["remote", "update"], "remote show": ["remote", "show", "origin"], "remote prune": ["remote", "prune", "origin"], "remote set-url": ["remote", "set-url", "origin", "https://x/y.git"], "remote add": ["remote", "add", "x", "y"],
    "config 쓰기": ["config", "remote.origin.pushurl", "https://x/y.git"], "config 읽기 둘": ["config", "--get", "a", "b"], "config --global": ["config", "--global", "user.name", "x"],
    "credential": ["credential", "fill"], "credential-store": ["credential-store", "get"], "원격 도우미": ["remote-https", "origin", "https://x/y.git"], "archive": ["archive", "--remote=origin", "HEAD"],
    "전역 옵션 -c": ["-c", "alias.f=push", "f", "origin", "main"], "전역 옵션 -C": ["-C", "/other", "status"], "전역 옵션 --exec-path": ["--exec-path=/tmp/evil", "status"], "--git-dir": ["--git-dir=/other/.git", "fetch"],
    "옵션이 먼저": ["--no-pager", "log"], "--help": ["--help"],
}
LOCAL_COMMANDS = (["status"], ["rev-parse", "HEAD"], ["rev-list", "--count", "a..b"], ["ls-tree", "-z", "abc"], ["cat-file", "-e", "HEAD:x"], ["diff-tree", "-z", "abc"], ["hash-object", "--no-filters", "--stdin"],
                  ["mktree", "-z", "--missing"], ["commit-tree", "abc", "-p", "def", "-F", "-"], ["log", "-1"], ["merge", "--ff-only", "x"], ["reset", "--soft", "x"], ["restore", "--staged", "--", "a"],
                  ["remote", "get-url", "--all", "origin"], ["remote", "get-url", "--push", "--all", "origin"], ["config", "--get", "core.sshCommand"], ["symbolic-ref", "-q", "HEAD"], ["merge-base", "--is-ancestor", "a", "b"],
                  ["--version"], ["x"])


class ShapeTableTest(unittest.TestCase):
    def test_the_only_network_shapes_git_may_run_are_fetch_main_ls_remote_branch_and_push_new_branch(self):
        """PT-01 — 허용되는 네트워크 모양은 정확히 넷이고 이름이 서로 다르다."""
        for name, args in ALLOWED.items():
            with self.subTest(shape=name):
                self.assertEqual(gitrepo.network_shape(args), name)
        self.assertEqual(sorted(ALLOWED), ["fetch_main", "ls_remote", "push_branch", "push_check"])
        self.assertEqual(FETCH, ["fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main"], "받기는 지금까지와 한 글자도 다르지 않다")
        for args in (tuple(PUSH), PUSH + []):
            self.assertEqual(gitrepo.network_shape(args), "push_branch", "목록·튜플 모두")

    def test_every_refused_shape_raises_the_catalog_code_before_any_process(self):
        for label, args in {**REFUSED_PUSHES, **REFUSED_OTHERS}.items():
            with self.subTest(label=label):
                with self.assertRaises(AppError) as caught:
                    gitrepo.network_shape(args)
                self.assertEqual(caught.exception.code, "PAGES_PUSH_REFUSED", args)

    def test_local_commands_pass_the_table_untouched(self):
        for args in LOCAL_COMMANDS:
            with self.subTest(args=args):
                self.assertIsNone(gitrepo.network_shape(args))

    def test_the_branch_name_pattern_and_the_check_pattern_are_exact(self):
        self.assertTrue(gitrepo.BRANCH_NAME.fullmatch(BRANCH))
        for bad in (BRANCH + "x", "x" + BRANCH, BRANCH + "\n", BRANCH.upper(), "desktop/post-2026110-103012-3bf91f62", "desktop/post-20261102-103012-3bf91f6", "desktop/post-20261102-103012-3BF91F62",
                    "desktop/post-20261102-103012-3bf91f62/x", "desktop/post-２０２６１１０２-103012-3bf91f62", "desktop/post-20261102-103012-3bf91f6２", "desktop/check-01234567", "main", ""):
            with self.subTest(bad=repr(bad)):
                self.assertIsNone(gitrepo.BRANCH_NAME.fullmatch(bad))
        self.assertTrue(gitrepo.CHECK_BRANCH.fullmatch(CHECK))
        self.assertIsNone(gitrepo.CHECK_BRANCH.fullmatch(BRANCH))


class NoProcessBeforeRefusalTest(unittest.TestCase):
    """PT-02·08 — 거절은 하위 프로세스를 띄우기 전이다(`Tripwire` 가 하위 프로세스를 하나라도 띄우면 막고 센다)."""

    def setUp(self):
        ss.external_write_on()
        self.addCleanup(ss.external_write_off)

    def test_push_to_main_in_any_spelling_is_refused_before_a_process_starts(self):
        for label, args in REFUSED_PUSHES.items():
            with self.subTest(label=label), og.Tripwire() as wire:
                with self.assertRaises(AppError) as caught:
                    gitrepo.run_git(Path("."), args)
                self.assertEqual(caught.exception.code, "PAGES_PUSH_REFUSED")
                self.assertEqual(wire.calls, [], "하위 프로세스를 띄우기 전에 거절한다")

    def test_pull_clone_and_unknown_network_subcommands_are_refused(self):
        for label, args in REFUSED_OTHERS.items():
            with self.subTest(label=label), og.Tripwire() as wire:
                with self.assertRaises(AppError) as caught:
                    gitrepo.run_git(Path("."), args)
                self.assertEqual(caught.exception.code, "PAGES_PUSH_REFUSED")
                self.assertEqual(wire.calls, [])

    def test_the_gate_comes_first_so_a_closed_build_says_disabled_even_for_a_refused_shape(self):
        ss.external_write_off()
        self.addCleanup(ss.external_write_on)
        with og.Tripwire() as wire:
            with self.assertRaises(AppError) as caught:
                gitrepo.run_git(Path("."), ["push", "origin", "main"])
        self.assertEqual((caught.exception.code, wire.calls), ("EXTERNAL_WRITE_DISABLED", []))

    def test_without_the_narrow_switch_even_an_allowed_shape_is_not_run(self):
        with mock.patch.object(capabilities, "PAGES_BRANCH_PUSH", False), og.Tripwire() as wire:
            for args in ALLOWED.values():
                with self.subTest(args=args[0]):
                    with self.assertRaises(AppError) as caught:
                        gitrepo.run_git(Path("."), args)
                    self.assertEqual(caught.exception.code, "NETWORK_DISABLED")
            self.assertEqual(wire.calls, [], "좁은 스위치가 꺼져 있으면 하위 프로세스를 띄우지 않는다")


class BranchNameTest(unittest.TestCase):
    def post(self, path=ss.KO_PATH, text="---\nlayout: post\n---\n본문\n", category="경제·일", lang="ko"):
        return PagesPost(path, text, category, lang)

    def test_branch_name_is_built_only_from_constants_digits_and_hex(self):
        """PT-03 — 제목·분야·태그 같은 사용자 글에서 온 글자는 한 글자도 들어가지 않는다."""
        hostile = ["../main", "a b", "x^y", "x:y", "x*y", "x?y", "x[y]", "x\\y", "x\x01y", "x~y", "desktop/post-", "ai/claude/x", "@{", "x.lock", ".hidden", "한글 제목", "﻿bom", "\u202e위장", "main"]
        names = set()
        for number, word in enumerate(hostile):
            with self.subTest(word=repr(word)):
                post = self.post(text=f"---\ntitle: {word}\ncategory: {word}\n---\n{word} {number}\n", category=word)
                name = pages.branch_name(post)
                self.assertRegex(name, r"\Adesktop/post-[0-9]{8}-[0-9]{6}-[0-9a-f]{8}\Z")
                self.assertTrue(gitrepo.BRANCH_NAME.fullmatch(name))
                names.add(name)
        self.assertEqual(len(names), len(hostile), "글이 다르면 이름도 다르다(해시가 글 내용을 담는다)")
        self.assertEqual(pages.branch_name(self.post()), pages.branch_name(self.post()), "같은 글·같은 경로면 같은 이름이다(멱등)")
        self.assertNotEqual(pages.branch_name(self.post()), pages.branch_name(self.post(path="_posts/경제·일/2026-11-02-KR-103013.md")))
        self.assertEqual(pages.branch_name(self.post()).split("-")[1:3], ["20261102", "103012"], "시각은 글 파일 이름과 같은 한국 시각이다")

    def test_the_name_is_made_only_from_the_path_time_and_a_hash_not_from_any_other_field(self):
        tree = ast.parse((SRC / "publish" / "pages.py").read_text(encoding="utf-8"))
        func = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "branch_name")
        used = {node.attr for node in ast.walk(func) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "post"}
        self.assertEqual(used, {"path", "text"}, "가지 이름은 글 경로의 시각과 (경로+글)의 해시에서만 나온다 — 분야·언어·제목 필드를 읽지 않는다")

    def test_branch_name_never_matches_the_blog_automation_patterns(self):
        """PT-04 — 블로그 저장소의 요청·텔레그램·자동 병합 부탁 흐름은 `ai/claude/**`·`ai/claude/M###-*`(M 뒤 세·네 자리) 가지 이름에만 반응한다 — 이 앱의 이름은 어느 것에도 맞지 않는다."""
        patterns = (r"ai/claude/.*", r"ai/claude/M\d{3}-.*", r"ai/claude/M\d{4}-.*")
        names = [pages.branch_name(self.post(text=f"---\n---\n글 {number}\n")) for number in range(50)] + [gitrepo.BRANCH_PREFIX + "x", gitrepo.CHECK_PREFIX + "x"]
        for name in names:
            for pattern in patterns:
                self.assertIsNone(re.fullmatch(pattern, name), (name, pattern))
            self.assertFalse(name.startswith(("ai/", "main", "pipeline/")))
        self.assertTrue(gitrepo.BRANCH_PREFIX.startswith("desktop/") and gitrepo.CHECK_PREFIX.startswith("desktop/"))

    def test_the_remote_identifier_shape_and_the_branch_shape_are_one_rule(self):
        self.assertEqual(pages.branch_name(self.post()), gitrepo.BRANCH_PREFIX + "20261102-103012-" + pages.branch_name(self.post()).rsplit("-", 1)[1])
        self.assertEqual(pages.post_path_for_branch(pages.branch_name(self.post()), "경제·일", "ko"), ss.KO_PATH)
        self.assertEqual(pages.post_path_for_branch(pages.branch_name(self.post()), "Society & Policy", "en"), "_posts/Society & Policy/2026-11-02-EN-103012.md")
        for bad in ("main", "desktop/post-1", None, 5, ""):
            self.assertIsNone(pages.post_path_for_branch(bad, "경제·일", "ko"))


class ConfigOverridesTest(unittest.TestCase):
    def fake_popen(self):
        made = []

        def popen(command, **kwargs):
            made.append((command, kwargs))
            kwargs["stdout"].write(b"")
            process = mock.Mock()
            process.returncode = 0
            process.pid = 4242
            process.wait.side_effect = [0]
            return process

        popen.made = made
        return popen

    def run_with_spy(self, args, **patches):
        popen = self.fake_popen()
        with mock.patch.dict(os.environ), mock.patch("subprocess.Popen", popen), mock.patch.object(gitrepo, "run_command", wraps=gitrepo.run_command):
            for name in ("GIT_SSH", "GIT_SSH_COMMAND"):
                os.environ.pop(name, None)
            with mock.patch.object(gitrepo, "_with_ssh_default", lambda cwd, env: env):
                gitrepo.run_git("C:/repo", args)
        return popen.made[-1][0]

    def setUp(self):
        ss.external_write_on()
        self.addCleanup(ss.external_write_off)

    def test_fixed_config_overrides_are_always_passed(self):
        """PT-05 — 설계서 3.5 의 `-c` 목록 전부(네트워크 명령만이 아니라 모든 git 호출에 늘 붙는다)."""
        wanted = ("http.lowSpeedLimit=1000", "http.lowSpeedTime=30", "gc.auto=0", "maintenance.auto=false", f"core.hooksPath={os.devnull}", "commit.gpgsign=false", "push.gpgSign=false", "user.useConfigOnly=true",
                  "i18n.commitEncoding=UTF-8", "i18n.logOutputEncoding=UTF-8", "http.sslVerify=true", "push.followTags=false", "push.recurseSubmodules=no", "push.autoSetupRemote=false", "push.default=nothing",
                  "protocol.allow=never", "protocol.https.allow=always", "protocol.ssh.allow=always")
        with mock.patch.object(gitrepo, "_EXTRA_TRANSPORTS", ()):
            for args in (["status"], FETCH, LS_REMOTE, PUSH, DRY_RUN):
                with self.subTest(args=args[0]):
                    command = self.run_with_spy(args)
                    pairs = [command[index + 1] for index, item in enumerate(command) if item == "-c"]
                    for option in wanted:
                        self.assertIn(option, pairs, option)
                    self.assertEqual(command[:3], ["git", "-C", "C:/repo"])
                    self.assertEqual(command[-len(args):], args, "인자는 한 글자도 바뀌지 않는다")
                    self.assertFalse([pair for pair in pairs if pair.startswith("protocol.") and pair not in wanted], "허용 전송은 https·ssh 둘뿐이다")

    def test_the_file_transport_is_added_only_through_the_test_seam_and_never_by_production_code(self):
        with mock.patch.object(gitrepo, "_EXTRA_TRANSPORTS", ("file",)):
            command = self.run_with_spy(["status"])
        self.assertIn("protocol.file.allow=always", command)
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else []
                for target in targets:
                    if isinstance(target, ast.Name) and target.id == "_EXTRA_TRANSPORTS" or isinstance(target, ast.Attribute) and target.attr == "_EXTRA_TRANSPORTS":
                        self.assertEqual(path.relative_to(SRC).as_posix(), "publish/gitrepo.py", "시험이 아닌 코드가 이 접합부를 바꾸지 않는다")
                        self.assertEqual(ast.unparse(node.value), "()", "기본값은 비어 있다")

    def test_the_config_list_has_no_main_or_force_related_option(self):
        text = (SRC / "publish" / "gitrepo.py").read_text(encoding="utf-8")
        section = text[text.index("def _config_overrides"):text.index("def run_git")]
        for word in ("--force", "+refs", "refs/heads/main", "push.default=current", "push.default=matching", "followTags=true", "sslVerify=false"):
            self.assertNotIn(word, section, word)


def ref_strings():
    """소스(`src`)에서 `refs/heads`·`refs/remotes` 가 든 글(f-문자열은 통째로, 설명 글(docstring)은 뺀다) → [(상대 경로, 줄, 따옴표·f 를 걷어낸 글)]."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    docs.add(first.value)
        for node in ast.walk(tree):
            text = None
            if isinstance(node, ast.JoinedStr):
                shown = ast.unparse(node)
                text = shown[2:-1] if shown.startswith(("f'", 'f"')) else shown
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and not isinstance(parents.get(node), ast.JoinedStr) and node not in docs:
                text = node.value
            if text is not None and ("refs/heads" in text or "refs/remotes" in text):
                found.append((path.relative_to(SRC).as_posix(), node.lineno, text))
    return found


class SourceHasNoMainRefspecTest(unittest.TestCase):
    def test_no_code_in_src_builds_a_refspec_to_main(self):
        """PT-06 — 소스 훑기(AST, 설명 글은 뺀다): ① `refs/heads/main` 을 만드는 곳은 **받는 쪽 상수 하나**(`+refs/heads/{MAIN}:{_REMOTE_MAIN}` — 원격 main → 이 저장소의 원격 추적 참조) ② 올리는 쪽(`<커밋>:refs/heads/<가지>`)을
        만드는 곳은 둘뿐 — 새 가지(`{built.branch}`)와 점검 가지(`{CHECK_PREFIX}…`) — 이고 그 뒤에 `main`·`MAIN` 이 붙는 글은 없다."""
        found = ref_strings()
        mains = [(rel, text) for rel, _, text in found if "refs/heads/{MAIN}" in text or "refs/heads/main" in text]
        self.assertEqual(mains, [("publish/gitrepo.py", "+refs/heads/{MAIN}:{_REMOTE_MAIN}")], "`refs/heads/main` 을 만드는 곳은 받는 쪽 상수 하나뿐이다")
        pushes = sorted(text for _, _, text in found if ":refs/heads/" in text and not text.startswith("+"))
        self.assertEqual(pushes, sorted(["{built.commit}:refs/heads/{built.branch}", "{head}:refs/heads/{CHECK_PREFIX}{head[:8]}"]), "올리는 쪽 모양은 새 가지와 점검 가지 둘뿐이다")
        for text in pushes:
            self.assertNotRegex(text, r"refs/heads/\{?(MAIN|main)\b", text)
        self.assertEqual(sorted(text for _, _, text in found if text.startswith("+")), ["+refs/heads/{MAIN}:{_REMOTE_MAIN}"], "강제 접두사(+)가 붙은 글도 받는 쪽 하나뿐이다")

    def test_the_old_main_pushing_functions_are_gone_and_nothing_names_them(self):
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for old in ("def push_commit", "def publish_post", "def _rebase", "MAX_PUSH_ATTEMPTS", "pages.push_commit", "pages.publish_post"):
                self.assertNotIn(old, text, f"{path.name}: {old}")

    def test_the_dry_run_check_pushes_to_a_check_branch_never_to_main(self):
        text = (SRC / "publish" / "gitrepo.py").read_text(encoding="utf-8")
        body = text[text.index("def check_push_access"):]
        body = body[:body.index("\n\n\n") if "\n\n\n" in body else len(body)]
        self.assertIn("{CHECK_PREFIX}{head[:8]}", body)
        self.assertNotIn(":refs/heads/{MAIN}", body)
        self.assertNotIn("HEAD:refs/heads", body)


class EnvironmentTest(unittest.TestCase):
    NAMES = ("GIT_SSL_NO_VERIFY", "GIT_SSL_CAINFO", "GIT_SSL_CAPATH", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
             "GIT_CONFIG_PARAMETERS", "GIT_TRACE", "GIT_TRACE_CURL", "GIT_TRACE_PACKET", "GIT_TRACE2", "GIT_TRACE2_EVENT", "GIT_CURL_VERBOSE", "SSLKEYLOGFILE", "GIT_ALLOW_PROTOCOL")

    def test_every_variable_that_could_weaken_the_push_path_is_dropped(self):
        with mock.patch.dict(os.environ, {name: "x" for name in self.NAMES}):
            env = gitrepo._git_env()
        for name in self.NAMES:
            self.assertNotIn(name, env, name)
        self.assertEqual(sorted(name for name in self.NAMES if name in gitrepo._ENV_DROP), [], "옛 목록(_ENV_DROP)은 그대로다 — 새 이름은 별도 표다")
        for name in ("GIT_TERMINAL_PROMPT", "GCM_INTERACTIVE", "GIT_EDITOR"):
            self.assertIn(name, env)

    def test_lower_case_spellings_are_dropped_too_and_unrelated_variables_are_kept(self):
        with mock.patch.dict(os.environ, {"git_trace": "1", "Git_Config_Count": "1", "sslkeylogfile": "x", "MY_OTHER_VARIABLE": "keep", "HTTPS_PROXY": "http://proxy.invalid:8080"}):
            env = gitrepo._git_env()
        for name in ("git_trace", "Git_Config_Count", "sslkeylogfile"):
            self.assertNotIn(name, {key for key in env}, name)
        self.assertEqual(env.get("MY_OTHER_VARIABLE"), "keep", "관계없는 변수는 건드리지 않는다")
        self.assertEqual(env.get("HTTPS_PROXY"), "http://proxy.invalid:8080", "회사 프록시 환경은 그대로 둔다(앱은 접속 설정을 바꾸지 않는다)")

    def test_the_users_own_ssh_settings_are_still_left_alone(self):
        with mock.patch.dict(os.environ, {"GIT_SSH_COMMAND": "ssh -i C:/keys/mine", "GIT_SSH": "C:/tools/plink.exe"}):
            env = gitrepo._git_env()
        self.assertEqual((env["GIT_SSH_COMMAND"], env["GIT_SSH"]), ("ssh -i C:/keys/mine", "C:/tools/plink.exe"))


if __name__ == "__main__":
    unittest.main()
