"""git 인자 표와 가지 이름 시험(PUBPR P2, 설계서 PT-01–08 — 정책 시험은 git 을 띄우지 않는다, D-741).

지키는 것 — 'main 에 직접 올리지 못한다' 의 네 겹 가운데 앞의 셋과 환경 정리:
  1) git 이 네트워크로 나가는 명령(`fetch`·`push`·`ls-remote`·`pull`·`clone`)은 `run_git` 한 곳에서 **정확히 네 모양**(받기·가지 확인·가지 올리기·올리기 점검)만 지나고, 그 밖은 하위 프로세스를 띄우기 전에 `PAGES_PUSH_REFUSED`(PT-01·02·08).
  2) 가지 이름은 상수 접두사와 숫자·16진수로만 만들어지고 사용자 글(제목·분야·태그)에서 온 글자가 한 글자도 없으며 블로그 저장소의 자동화(`ai/claude/**`)를 깨우지 않는다(PT-03·04).
  3) 항상 붙는 `-c` 설정이 사용자 설정이 push 를 넓히지 못하게 덮어쓴다(PT-05).
  4) 소스에 `refs/heads/main` 으로 가는 refspec 을 만드는 코드가 없다 — 받는 쪽 상수 한 곳뿐이다(PT-06, AST).
  5) 네트워크 명령 직전마다 origin 을 다시 읽어 견준다(PT-07 — 진짜 git·로컬 bare 저장소는 `test_pages_branch_build.py`).
  6) 올리기 길의 환경에서 인증서 검증을 끄거나 설정을 덮어쓰거나 통신 내용을 기록하게 하는 변수가 지워진다(NET '켜기 전 필수 조건' 마무리).
  7) 표는 **허용 목록**이다(재작업 1, 독립 검증 S G-1·G-2): 앱이 쓰는 로컬 하위 명령(`gitrepo._LOCAL_COMMANDS`) 밖의 이름(낯선 이름·대소문자만 바꾼 이름)과 글(`str`)이 아닌 인자(`Path`·`bytes`·숫자·`str` 하위 클래스)·빈 인자도
     하위 프로세스 전에 거절하고, `run_git` 은 검사와 실행이 같은 인자를 보게 한 번만 읽으며, 목록은 소스가 실제로 쓰는 하위 명령과 같다.
  8) `run_command`(하위 프로세스를 띄우는 유일한 곳)는 `publish/gitrepo.py` 의 `run_git`·`_with_ssh_default` 두 곳에서만 가리킨다 — 이름·속성·`import … as`·글자·이어 붙인 글 모두(AST, G-3). 시험 접합부 `_EXTRA_TRANSPORTS` 도 같은 방식으로 지킨다.
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


class Sneaky(str):
    """글(`str`)처럼 보이지만 검사 메서드를 속이는 하위 클래스 — `startswith` 가 늘 거짓이라 '옵션처럼 시작한다' 를 숨긴다."""

    def startswith(self, *args, **kwargs):
        return False


class Shifty(list):
    """처음 읽을 때는 안전한 인자를, 그다음부터는 위험한 인자를 내놓는 가변 목록 — 검사와 실행이 따로 읽으면 표를 피할 수 있다(`reads` 가 읽힌 횟수)."""

    def __init__(self, safe, danger):
        super().__init__(safe)
        self.safe, self.danger, self.reads = tuple(safe), tuple(danger), 0

    def __iter__(self):
        self.reads += 1
        return iter(self.safe if self.reads == 1 else self.danger)


# 재작업 1(G-1·G-2): 글이 아닌 인자·빈 인자·낯선 하위 명령·대소문자만 바꾼 이름 — 모두 하위 프로세스 전에 거절한다
REFUSED_OTHERS.update({
    "Path 인자(S 탐침 A7)": ["push", "--force", "origin", Path("main")], "Path 하위 명령": [Path("status")], "bytes 인자(A8)": ["push", b"--force", "origin", b"main"], "bytes 하위 명령": [b"push", "origin", "main"],
    "숫자 인자(A9)": ["status", 1], "None 인자": ["status", None], "중첩 목록": ["status", ["--force"]], "튜플 인자": ["status", ("--force",)], "str 하위 클래스": ["push", Sneaky("--force"), "origin", "main"],
    "str 하위 클래스 하위 명령": [Sneaky("status")], "빈 인자": [], "빈 글 하위 명령": [""], "공백 하위 명령": [" status"], "글 하나(목록 아님)": "status", "바이트 글(목록 아님)": b"status",
    "알 수 없는 하위 명령 x": ["x"], "lfs push(A10)": ["lfs", "push", "--all", "origin"], "maintenance run(A10)": ["maintenance", "run", "--task=prefetch"], "credential-wincred": ["credential-wincred", "get"],
    "credential-manager-core": ["credential-manager-core", "get"], "bundle": ["bundle", "create", "x", "HEAD"], "update-ref 삭제": ["update-ref", "-d", "refs/remotes/origin/main"], "gc": ["gc"], "notes merge": ["notes", "merge", "x"],
    "rebase": ["rebase", "origin/main"], "foo": ["foo"], "checkout": ["checkout", "-b", "x"], "branch 삭제": ["branch", "-D", "x"], "tag 삭제": ["tag", "-d", "x"], "stash": ["stash"], "clean": ["clean", "-fdx"], "init": ["init"],
    "worktree": ["worktree", "add", "x"], "filter-branch": ["filter-branch"], "대소문자 PUSH(A5)": ["PUSH", "--force", "origin", "main"], "대소문자 Push": ["Push", "--force", "origin", "main"], "대소문자 pUsH": ["pUsH", "origin", "main"],
    "대소문자 FETCH(A6)": ["FETCH", "origin"], "대소문자 LS-REMOTE": ["LS-REMOTE", "origin"], "대소문자 Pull": ["Pull", "origin"], "대소문자 CLONE": ["CLONE", "origin"], "대소문자 Remote update(A10)": ["Remote", "update"],
    "대소문자 Config --global": ["Config", "--global", "x", "y"], "대소문자 STATUS": ["STATUS"], "대소문자 Rev-Parse": ["Rev-Parse", "HEAD"],
})
LOCAL_COMMANDS = (["status"], ["rev-parse", "HEAD"], ["rev-list", "--count", "a..b"], ["ls-tree", "-z", "abc"], ["cat-file", "-e", "HEAD:x"], ["diff-tree", "-z", "abc"], ["hash-object", "--no-filters", "--stdin"],
                  ["mktree", "-z", "--missing"], ["commit-tree", "abc", "-p", "def", "-F", "-"], ["log", "-1"], ["merge", "--ff-only", "x"], ["reset", "--soft", "x"], ["restore", "--staged", "--", "a"],
                  ["remote", "get-url", "--all", "origin"], ["remote", "get-url", "--push", "--all", "origin"], ["config", "--get", "core.sshCommand"], ["symbolic-ref", "-q", "HEAD"], ["merge-base", "--is-ancestor", "a", "b"],
                  ["--version"], ["add", "--", "a.md"], ["commit", "--only", "--no-verify", "--quiet", "-F", "m.txt", "--", "a.md"], ["diff", "--raw", "-z", "HEAD", "refs/remotes/origin/main"], ["ls-files", "-z", "--others"],
                  ["rm", "--cached", "--quiet", "--", "a.md"])          # 재작업 1: 옛 `["x"]`(없는 하위 명령)는 표가 이제 허용 목록이라 거절 쪽(`REFUSED_OTHERS` 의 '알 수 없는 하위 명령 x')으로 옮겼다


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


class StrictArgumentTest(unittest.TestCase):
    """재작업 1(독립 검증 S G-1) — 검사와 실행이 **같은** 인자를 본다: `run_git` 은 인자를 한 번만 읽어 두고 그 값으로 검사하고 그 값으로 실행한다. 글이 아닌 인자·낯선 하위 명령을 거절하는 것은 위 `REFUSED_OTHERS` 가
    `network_shape` 와 `run_git`(하위 프로세스 0) 양쪽으로 본다."""

    def setUp(self):
        ss.external_write_on()
        self.addCleanup(ss.external_write_off)

    def run_recorded(self, args):
        """`run_command` 를 가짜로 바꿔 실제로 실행하려던 명령을 돌려준다(하위 프로세스 0)."""
        seen = []

        def recorder(command, *, env=None, timeout=0, label="", input_bytes=None):
            seen.append(list(command))
            return gitrepo.GitResult(0, "", "")

        with mock.patch.object(gitrepo, "run_command", recorder), mock.patch.object(gitrepo, "_with_ssh_default", lambda cwd, env: env):
            gitrepo.run_git("C:/repo", args)
        return seen

    def test_the_table_and_the_runner_read_the_arguments_exactly_once(self):
        """검사 뒤에 내용이 바뀌는 가변 목록: 처음 읽으면 `status`, 두 번째부터는 `push --force origin main`. 실행이 따로 다시 읽으면 표를 피한다 — 실제로 실행된 명령은 검사한 것(`status`)이어야 한다."""
        shifty = Shifty(["status"], ["push", "--force", "origin", "main"])
        seen = self.run_recorded(shifty)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][-1:], ["status"], seen[0])
        self.assertFalse({"push", "--force", "origin", "main"} & set(seen[0]), seen[0])
        self.assertEqual(shifty.reads, 1, "목록은 한 번만 읽혔다")

    def test_an_iterator_is_read_once_and_the_command_is_what_was_checked(self):
        seen = self.run_recorded(iter(["status", "--porcelain"]))
        self.assertEqual(seen[0][-2:], ["status", "--porcelain"], "한 번만 읽히는 반복자도 검사한 값 그대로 실행된다(비어 버리지 않는다)")

    def test_an_iterator_that_hides_a_forbidden_shape_is_still_refused_before_any_process(self):
        with og.Tripwire() as wire:
            with self.assertRaises(AppError) as caught:
                gitrepo.run_git(Path("."), iter(["push", "--force", "origin", "main"]))
        self.assertEqual((caught.exception.code, wire.calls), ("PAGES_PUSH_REFUSED", []))

    def test_every_allowed_shape_runs_unchanged_through_the_snapshot(self):
        for name, args in ALLOWED.items():
            with self.subTest(shape=name):
                seen = self.run_recorded(args)
                self.assertEqual((len(seen), seen[0][-len(args):], seen[0][:3]), (1, args, ["git", "-C", "C:/repo"]))


GIT_CALLERS = ("git", "run_git", "_must", "_git_in_chunks")


def src_git_subcommands():
    """`src` 가 git 으로 부르는 하위 명령(목록 인자의 첫 항목이 글자 상수인 것) 집합 — `git(root, [...])`·`run_git`·`_must(git, root, [...])`·`_git_in_chunks(git, root, [접두 목록], 이름들)` 호출을 AST 로 훑는다."""
    used = set()
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] in GIT_CALLERS:
                for arg in node.args:
                    if isinstance(arg, ast.List) and arg.elts and isinstance(arg.elts[0], ast.Constant) and isinstance(arg.elts[0].value, str):
                        used.add(arg.elts[0].value)
    return used


class LocalCommandListTest(unittest.TestCase):
    """재작업 1(독립 검증 S G-2) — 표는 거부 목록이 아니라 **허용 목록**이다: 앱이 쓰는 로컬 하위 명령 스무 개(`gitrepo._LOCAL_COMMANDS`)와 네트워크 네 모양·`remote get-url`·`config --get`·`--version` 만 하위 프로세스에 간다."""

    def test_the_closed_list_is_exactly_the_local_commands_the_source_runs(self):
        used = src_git_subcommands()
        self.assertTrue({"push", "ls-remote", "remote", "--version", "rev-parse"} <= used, "빈 훑기가 아니다")
        self.assertEqual(used - {"fetch", "push", "ls-remote", "remote", "config", "--version"}, set(gitrepo._LOCAL_COMMANDS),
                         "소스가 git 으로 부르는 로컬 하위 명령과 `_LOCAL_COMMANDS` 가 같아야 한다 — 새 하위 명령을 쓰려면 목록에 더하고(검토 지점) 안 쓰게 되면 목록에서 뺀다")

    def test_every_name_on_the_list_passes_untouched(self):
        for name in sorted(gitrepo._LOCAL_COMMANDS):
            with self.subTest(name=name):
                self.assertIsNone(gitrepo.network_shape([name, "--", "x"]))

    def test_the_list_holds_plain_lower_case_local_names_only(self):
        self.assertIsInstance(gitrepo._LOCAL_COMMANDS, frozenset)
        for name in gitrepo._LOCAL_COMMANDS:
            self.assertRegex(name, r"\A[a-z]+(?:-[a-z]+)*\Z", name)
        self.assertEqual(gitrepo._LOCAL_COMMANDS & (gitrepo._NETWORK_COMMANDS | gitrepo._OTHER_NETWORK_COMMANDS), set(), "네트워크로 나갈 수 있는 명령은 허용 목록에 없다")

    def test_look_alikes_of_allowed_names_are_refused(self):
        """대소문자만 바꾼 이름·공백·줄바꿈·눈에 안 보이는 글자·경로 꼴·접두 옵션·이름을 줄이거나 늘린 것 — 가장 비슷한 명령으로 고쳐 돌릴 길(`help.autocorrect`)도 없다."""
        names = sorted(gitrepo._LOCAL_COMMANDS) + ["fetch", "push", "ls-remote", "remote", "config"]
        for name in names:
            variants = {name.upper(), name.title(), name.swapcase(), " " + name, name + " ", name + chr(10), name[:1] + chr(0x200B) + name[1:], "./" + name, "--" + name, name + "/", name.replace("-", "_"), name + "s", name[:-1]} - {name}
            for variant in sorted(variants):
                with self.subTest(name=name, variant=repr(variant)):
                    with self.assertRaises(AppError) as caught:
                        gitrepo.network_shape([variant, "x"])
                    self.assertEqual(caught.exception.code, "PAGES_PUSH_REFUSED")


def _fold(node):
    """글자 상수(이어 붙인 것·글자 부분뿐인 f-문자열 포함)로 접히면 그 글, 아니면 None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left), _fold(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr) and all(isinstance(part, ast.Constant) for part in node.values):
        return "".join(part.value for part in node.values)
    return None


def references_in(tree, word):
    """한 소스(AST)에서 `word` 를 가리키는 모든 곳 → [(둘러싼 함수 이름('<module>' 이면 함수 밖), 종류)] — 이름·속성(`x.word`)·`import … word [as …]`·`def word`·글자 `word`(이어 붙인 글(`'run_' + 'command'`)도 접어서 본다)."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found = []
    for node in ast.walk(tree):
        kind = None
        if isinstance(node, ast.Name) and node.id == word:
            kind = "name"
        elif isinstance(node, ast.Attribute) and node.attr == word:
            kind = "attribute"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == word:
            kind = "def"
        elif isinstance(node, ast.alias) and word in (node.name.rsplit(".", 1)[-1], node.asname):
            kind = "import"
        elif isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr)) and _fold(node) == word and not (isinstance(node, ast.Constant) and isinstance(parents.get(node), (ast.BinOp, ast.JoinedStr))):
            kind = "string"
        if kind is None:
            continue
        owner, scope = node, "<module>"
        while owner in parents:
            owner = parents[owner]
            if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = owner.name
                break
        found.append((scope, kind))
    return found


def src_references(word):
    """`src` 모든 파일에서 `word` 를 가리키는 곳 → 정렬된 [(상대 경로, 둘러싼 함수 이름, 종류)]."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" not in path.parts:
            found += [(path.relative_to(SRC).as_posix(), scope, kind) for scope, kind in references_in(ast.parse(path.read_text(encoding="utf-8")), word)]
    return sorted(found)


class RunCommandCallersTest(unittest.TestCase):
    """재작업 1(독립 검증 S G-3) — `run_command` 는 인자 표도 환경 정리도 없는 하위 프로세스 실행기다. 그것을 직접 부르는 곳이 생기면 표를 건너뛴다(`getattr(gitrepo, 'run_command')(['git', 'push', …])` 도 마찬가지).
    그래서 소스가 `run_command` 를 가리키는 곳을 **허용 목록**(`gitrepo.py` 안 정해진 두 곳)으로 못박는다. 정직한 한계: 소스 훑기는 정직한 코드의 회귀 그물이다 — 일부러 숨기는 코드를 막는 방어가 아니라서 마지막 방어는 `run_git` 의 인자 표와 환경 정리다."""

    ALLOWED = [("publish/gitrepo.py", "<module>", "def"), ("publish/gitrepo.py", "_with_ssh_default", "name"), ("publish/gitrepo.py", "run_git", "name")]

    def test_only_the_runner_and_the_ssh_default_point_at_run_command(self):
        self.assertEqual(src_references("run_command"), self.ALLOWED,
                         "`run_command` 를 가리키는 곳은 정의 하나와 `run_git`·`_with_ssh_default` 의 호출뿐이다 — 이름·속성·`import … as`·글자(`getattr`·이어 붙인 글)로 가리키는 곳도 모두 센다")

    def test_the_scanner_sees_every_way_of_pointing_at_a_name(self):
        """훑개가 빈 훑개가 아님을 합성 코드로 보인다(소스 파일을 만들지 않고 AST 만): 이름·속성·import 별칭·글자·이어 붙인 글·f-문자열·정의 — 한 번씩만 센다."""
        cases = {"run_command([])": ["name"], "gitrepo.run_command([])": ["attribute"], "from x import run_command as rc": ["import"], "from x import rc as run_command": ["import"], "getattr(m, 'run_command')": ["string"],
                 "getattr(m, 'run_' + 'command')": ["string"], "getattr(m, 'r' + 'un' + '_' + 'command')": ["string"], "getattr(m, f'run_command')": ["string"], "def run_command(): pass": ["def"],
                 "other_name([])": [], "x = 'run_commands'": [], "def f():\n    return gitrepo.run_command([])": ["attribute"]}
        for code, kinds in cases.items():
            with self.subTest(code=code):
                self.assertEqual([kind for _scope, kind in references_in(ast.parse(code), "run_command")], kinds)
        self.assertEqual(references_in(ast.parse("def f():\n    return gitrepo.run_command([])"), "run_command"), [("f", "attribute")], "둘러싼 함수 이름을 함께 센다")

    def test_the_two_allowed_callers_build_their_command_the_way_the_table_expects(self):
        tree = ast.parse((SRC / "publish" / "gitrepo.py").read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        calls = [node for node in ast.walk(functions["_with_ssh_default"]) if isinstance(node, ast.Call) and ast.unparse(node.func) == "run_command"]
        self.assertEqual([ast.unparse(call.args[0]) for call in calls], ["['git', '-C', str(cwd), 'config', '--get', 'core.sshCommand']"], "ssh 기본값 확인은 읽기 하나뿐이다")
        commands = [node.value for node in ast.walk(functions["run_git"]) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "command" for target in node.targets)]
        self.assertEqual([ast.unparse(value) for value in commands], ["['git', '-C', str(cwd), *_config_overrides(), *args]"], "실행 명령은 늘 붙는 -c 설정과 검사한 인자로만 짠다")
        calls = [node for node in ast.walk(functions["run_git"]) if isinstance(node, ast.Call) and ast.unparse(node.func) == "run_command"]
        self.assertEqual([ast.unparse(call.args[0]) for call in calls], ["command"])

    def test_the_transport_seam_is_named_only_where_it_is_defined_and_read(self):
        """`_EXTRA_TRANSPORTS`(시험이 `file` 전송을 임시로 여는 접합부)를 이름·속성·글자(`__dict__[…]`·`setattr`·이어 붙인 글)로 가리키는 곳은 `gitrepo.py` 의 정의와 `_config_overrides` 의 읽기뿐이다."""
        self.assertEqual(src_references("_EXTRA_TRANSPORTS"), [("publish/gitrepo.py", "<module>", "name"), ("publish/gitrepo.py", "_config_overrides", "name")])


if __name__ == "__main__":
    unittest.main()
