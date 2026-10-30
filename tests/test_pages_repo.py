"""연결한 chanceblog 로컬 저장소 확인 시험 — 폴더·origin·main·변경 여부 확인, 최신 받기, 올리기 점검, 실패의 오류 코드 분류.

실제 git 으로 임시 저장소(원격 역할의 bare 저장소 + 작업 사본 + 다른 사람 사본)를 만들어 돌린다. 네트워크·시크릿이 필요 없다.
인증·네트워크 실패는 실제로 만들 수 없어서 git 의 실제 오류 문구를 모은 표로 분류를 확인한다.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import UNEXPECTED, AppError  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
from chanceblog_desktop.publish.gitrepo import GitResult  # noqa: E402

LOCAL_ORIGIN = re.compile(r".*origin\.git/?$")      # 시험용 원격(bare 저장소) 주소
HAVE_GIT = bool(shutil.which("git"))


def git(cwd, *args):
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr.decode('utf-8', 'replace')}")
    return done.stdout.decode("utf-8").strip()


def commit_file(repo, name, text, message="x"):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)


def code_of(callable_, *args, **kwargs):
    with unittest.TestCase().assertRaises(AppError) as caught:
        callable_(*args, **kwargs)
    return caught.exception


@unittest.skipUnless(HAVE_GIT, "git 이 필요하다(GIT_NOT_INSTALLED 상황)")
class RealRepositoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shared = tempfile.TemporaryDirectory()
        cls.addClassCleanup(shared.cleanup)
        cls.base = Path(shared.name) / "base"
        cls.base.mkdir()
        origin = cls.base / "origin.git"
        git(cls.base, "init", "-q", "--bare", str(origin))
        git(origin, "symbolic-ref", "HEAD", "refs/heads/main")        # 다른 사본이 clone 하면 main 을 받게
        git(cls.base, "clone", "-q", str(origin), "work")
        work = cls.base / "work"
        git(work, "config", "core.autocrlf", "false")
        git(work, "checkout", "-q", "-B", "main")
        commit_file(work, "README.md", "처음\n")
        git(work, "push", "-q", "-u", "origin", "main")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        shutil.copytree(self.base, self.tmp / "t")
        self.origin = self.tmp / "t" / "origin.git"
        self.work = self.tmp / "t" / "work"
        git(self.work, "remote", "set-url", "origin", str(self.origin))

    def other_pushes(self, name="from_bot.md"):
        """다른 사본(자동 발행 봇처럼)이 원격 main 에 커밋을 올린다."""
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.origin), "other")
        git(other, "config", "core.autocrlf", "false")
        commit_file(other, name, "봇 글\n", "bot")
        git(other, "push", "-q", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def inspect(self, path=None):
        return gitrepo.inspect_repo(path or self.work, expected_origin=LOCAL_ORIGIN)

    # --- 연결 확인 -----------------------------------------------------------------------------------------------------
    def test_a_clean_clone_on_main_is_accepted(self):
        info = self.inspect()
        self.assertEqual((info.branch, info.head), ("main", git(self.work, "rev-parse", "HEAD")))
        self.assertTrue(info.origin.endswith("origin.git"))

    def test_a_missing_folder_a_plain_folder_and_a_subfolder_are_not_repositories(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        sub = self.work / "sub"
        sub.mkdir()
        for path in (self.tmp / "no-such-folder", plain, sub):
            with self.subTest(path=path.name):
                self.assertEqual(code_of(self.inspect, path).code, "PAGES_LOCAL_REPO_INVALID")

    def test_a_repository_whose_origin_is_not_chanceblog_is_refused(self):
        error = code_of(gitrepo.inspect_repo, self.work)            # 기본 규칙은 github.com/shine88pc/chanceblog 만 받는다
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_INVALID")
        git(self.work, "remote", "remove", "origin")
        self.assertEqual(code_of(self.inspect).code, "PAGES_LOCAL_REPO_INVALID")

    def test_another_branch_or_a_detached_head_is_not_main(self):
        git(self.work, "checkout", "-q", "-b", "feature")
        error = code_of(self.inspect)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_NOT_MAIN")
        self.assertIn("「feature」", error.rendered().message)
        git(self.work, "checkout", "-q", "--detach")
        self.assertEqual(code_of(self.inspect).code, "PAGES_LOCAL_REPO_NOT_MAIN")

    def test_tracked_changes_and_staged_files_are_dirty_but_new_untracked_files_are_not(self):
        (self.work / "newfile.txt").write_text("새 파일\n", encoding="utf-8")
        self.inspect()                                             # 새 파일(추적 안 함)은 변경으로 보지 않는다
        (self.work / "README.md").write_text("바뀜\n", encoding="utf-8")
        self.assertEqual(code_of(self.inspect).code, "PAGES_LOCAL_REPO_DIRTY")
        git(self.work, "checkout", "--", "README.md")
        self.inspect()
        git(self.work, "add", "newfile.txt")
        self.assertEqual(code_of(self.inspect).code, "PAGES_LOCAL_REPO_DIRTY")

    # --- 최신 받기 -----------------------------------------------------------------------------------------------------
    def test_sync_latest_brings_in_what_the_bot_published_and_nothing_else_changes(self):
        new_head = self.other_pushes()
        (self.work / "untracked.txt").write_text("내 새 파일\n", encoding="utf-8")
        info = gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(info.head, new_head)
        self.assertTrue((self.work / "from_bot.md").is_file())
        self.assertEqual((self.work / "untracked.txt").read_text(encoding="utf-8"), "내 새 파일\n")

    def test_sync_latest_when_already_up_to_date_changes_nothing(self):
        before = git(self.work, "rev-parse", "HEAD")
        self.assertEqual(gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN).head, before)

    def test_sync_latest_refuses_unpushed_or_diverged_commits_and_leaves_them_alone(self):
        commit_file(self.work, "mine.md", "내 커밋\n", "mine")
        mine = git(self.work, "rev-parse", "HEAD")
        self.assertEqual(code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.other_pushes()
        self.assertEqual(code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(git(self.work, "rev-parse", "HEAD"), mine, "앱은 남의 커밋을 되돌리거나 지우지 않는다")
        self.assertTrue((self.work / "mine.md").is_file())

    def test_sync_latest_reports_an_unreachable_remote_with_a_code(self):
        git(self.work, "remote", "set-url", "origin", "file:///no/such/place/origin.git")
        error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "GIT_PUSH_AUTH")      # 없는 저장소와 권한 없는 저장소는 git 이 같은 문구로 알린다
        self.assertTrue(error.detail)

    # --- 올리기 점검 ---------------------------------------------------------------------------------------------------
    def test_the_push_check_does_not_change_the_remote(self):
        before = git(self.origin, "rev-parse", "main")
        gitrepo.check_push_access(self.work, expected_origin=LOCAL_ORIGIN)
        commit_file(self.work, "later.md", "나중\n", "later")                # 올릴 것이 있어도 점검은 올리지 않는다
        gitrepo.check_push_access(self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(git(self.origin, "rev-parse", "main"), before)

    def test_the_push_check_reports_a_remote_that_moved_on_as_rejected(self):
        self.other_pushes()
        error = code_of(gitrepo.check_push_access, self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "GIT_PUSH_REJECTED")


class FakeGit:
    """git 인자의 앞부분으로 미리 정한 답을 돌려주는 가짜 실행기."""

    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def __call__(self, cwd, args):
        self.calls.append(list(args))
        text = " ".join(args)
        for prefix, reply in self.replies.items():
            if text.startswith(prefix):
                return reply
        raise AssertionError(f"예상하지 못한 git 호출: {text}")


def ok(stdout=""):
    return GitResult(0, stdout, "")


def fail(stderr, stdout="", code=128):
    return GitResult(code, stdout, stderr)


class FailureClassificationTest(unittest.TestCase):
    CASES = {
        "GIT_PUSH_AUTH": (
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
            "remote: Invalid username or password.\nfatal: Authentication failed for 'https://github.com/shine88pc/chanceblog.git/'",
            "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': The requested URL returned error: 403",
            "remote: Permission to shine88pc/chanceblog.git denied to someone.\nfatal: unable to access 'https://github.com/x/y.git/': The requested URL returned error: 403",
            "remote: Repository not found.\nfatal: repository 'https://github.com/x/y.git/' not found",
            "git@github.com: Permission denied (publickey).\nfatal: Could not read from remote repository.",
            "fatal: unable to access 'https://github.com/x/y.git/': The requested URL returned error: 401",
        ),
        "GIT_PUSH_NETWORK": (
            "fatal: unable to access 'https://github.com/x/y.git/': Could not resolve host: github.com",
            "fatal: unable to access 'https://github.com/x/y.git/': Failed to connect to github.com port 443 after 21060 ms: Couldn't connect to server",
            "fatal: unable to access 'https://github.com/x/y.git/': Connection timed out after 300000 milliseconds",
            "fatal: unable to access 'https://github.com/x/y.git/': schannel: next InitializeSecurityContext failed: Unknown error",
            "fatal: unable to access 'https://github.com/x/y.git/': SSL certificate problem: unable to get local issuer certificate",
            "fatal: unable to access 'https://github.com/x/y.git/': Recv failure: Connection was reset",
            "fatal: the remote end hung up unexpectedly",
        ),
        "GIT_PUSH_REJECTED": (
            "To https://github.com/x/y.git\n ! [rejected]        HEAD -> main (fetch first)\nerror: failed to push some refs to 'https://github.com/x/y.git'",
            " ! [rejected]        main -> main (non-fast-forward)",
            "error: failed to push some refs to 'https://github.com/x/y.git'",
        ),
        UNEXPECTED: ("fatal: not a git repository (or any of the parent directories): .git", "", "무슨 말인지 모를 출력"),
    }

    def test_real_git_messages_map_to_the_right_codes(self):
        for code, messages in self.CASES.items():
            for message in messages:
                with self.subTest(code=code, message=message[:60]):
                    self.assertEqual(gitrepo.classify_git_failure(message), code)
                    self.assertEqual(gitrepo.classify_git_failure(message.upper()), code, "대소문자와 무관")

    def test_credentials_inside_urls_are_hidden(self):
        self.assertEqual(gitrepo.hide_credentials("https://user:ghp_secretvalue@github.com/a/b.git"), "https://***@github.com/a/b.git")
        self.assertEqual(gitrepo.hide_credentials("git@github.com:a/b.git"), "git@github.com:a/b.git")
        self.assertEqual(gitrepo.hide_credentials("see https://github.com/a/b"), "see https://github.com/a/b")


class RunnerTest(unittest.TestCase):
    def test_git_runs_without_prompts_and_with_english_messages(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b"ok\n", stderr=b"")) as run:
            result = gitrepo.run_git("C:/somewhere", ["status"])
        self.assertEqual((result.returncode, result.stdout), (0, "ok\n"))
        args, kwargs = run.call_args
        self.assertEqual(args[0][:3], ["git", "-C", "C:/somewhere"])
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(kwargs["env"]["GCM_INTERACTIVE"], "false")
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        self.assertGreater(kwargs["timeout"], 0)

    def test_a_missing_git_is_git_not_installed(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(code_of(gitrepo.run_git, ".", ["status"]).code, "GIT_NOT_INSTALLED")

    def test_a_timeout_is_a_network_timeout(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 90)):
            self.assertEqual(code_of(gitrepo.run_git, ".", ["fetch"]).code, "NETWORK_TIMEOUT")

    def test_output_is_decoded_leniently(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout=b"\xff\xfe", stderr="한글".encode("utf-8"))):
            result = gitrepo.run_git(".", ["x"])
        self.assertEqual(result.stderr, "한글")


class FailureDetailTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def replies(self, **overrides):
        replies = {
            "rev-parse --show-toplevel": ok(str(self.root)),
            "remote get-url": ok("https://github.com/shine88pc/chanceblog.git"),
            "rev-parse --abbrev-ref": ok("main"),
            "status --porcelain": ok(""),
            "rev-parse HEAD": ok("a" * 40),
        }
        replies.update(overrides)
        return replies

    def test_the_default_origin_rule_accepts_the_usual_chanceblog_addresses_and_nothing_else(self):
        for url in ("https://github.com/shine88pc/chanceblog.git", "https://github.com/shine88pc/chanceblog", "git@github.com:shine88pc/chanceblog.git",
                    "https://someone@github.com/shine88pc/chanceblog.git", "ssh://git@github.com/shine88pc/chanceblog.git", "HTTPS://GITHUB.COM/shine88pc/chanceblog.git"):
            with self.subTest(url=url):
                self.assertTrue(gitrepo.EXPECTED_ORIGIN.match(url))
        for url in ("https://github.com/shine88pc/chanceblog-desktop.git", "https://github.com/other/chanceblog.git", "https://evil.example/github.com/shine88pc/chanceblog.git",
                    "https://github.com.evil.example/shine88pc/chanceblog.git", "https://github.com/shine88pc/chanceblog.git.evil", ""):
            with self.subTest(url=url):
                self.assertFalse(gitrepo.EXPECTED_ORIGIN.match(url))

    def test_a_credential_in_the_origin_address_never_reaches_the_info_or_the_error_detail(self):
        secret = "ghp_" + "x" * 36
        fake = FakeGit(self.replies(**{"remote get-url": ok(f"https://user:{secret}@github.com/shine88pc/chanceblog.git")}))
        info = gitrepo.inspect_repo(self.root, git=fake)
        self.assertNotIn(secret, repr(info))
        fake = FakeGit(self.replies(**{"remote get-url": ok(f"https://user:{secret}@github.com/other/repo.git")}))
        error = code_of(gitrepo.inspect_repo, self.root, git=fake)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_INVALID")
        self.assertNotIn(secret, error.detail)

    def test_a_failed_push_check_names_the_cause_and_hides_credentials_in_the_detail(self):
        secret = "ghp_" + "y" * 36
        stderr = f"fatal: unable to access 'https://user:{secret}@github.com/shine88pc/chanceblog.git/': The requested URL returned error: 403"
        fake = FakeGit(self.replies(**{"push --dry-run": fail(stderr)}))
        error = code_of(gitrepo.check_push_access, self.root, git=fake)
        self.assertEqual(error.code, "GIT_PUSH_AUTH")
        self.assertNotIn(secret, error.detail)
        self.assertIn("***@", error.detail)
        self.assertLessEqual(len(error.detail), 440)
        self.assertNotIn(secret, str(error))

    def test_a_very_long_git_output_is_cut_to_its_tail_in_the_detail(self):
        stderr = "x" * 5000 + "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': Could not resolve host: github.com"
        fake = FakeGit(self.replies(**{"push --dry-run": fail(stderr)}))
        error = code_of(gitrepo.check_push_access, self.root, git=fake)
        self.assertEqual(error.code, "GIT_PUSH_NETWORK")
        self.assertLessEqual(len(error.detail), 440, "세부는 끝부분 400자만 남긴다")
        self.assertTrue(error.detail.endswith("Could not resolve host: github.com"), "원인이 있는 끝부분이 남아야 한다")

    def test_an_unknown_failure_is_the_catch_all_with_a_detail_for_developers(self):
        fake = FakeGit(self.replies(**{"rev-parse --abbrev-ref": fail("fatal: ambiguous argument 'HEAD': unknown revision")}))
        error = code_of(gitrepo.inspect_repo, self.root, git=fake)
        self.assertEqual(error.code, UNEXPECTED)
        self.assertIn("ambiguous", error.detail)

    def test_the_check_order_is_repository_then_branch_then_changes(self):
        fake = FakeGit(self.replies(**{"rev-parse --abbrev-ref": ok("feature"), "status --porcelain": ok(" M README.md")}))
        self.assertEqual(code_of(gitrepo.inspect_repo, self.root, git=fake).code, "PAGES_LOCAL_REPO_NOT_MAIN")
        fake = FakeGit(self.replies(**{"status --porcelain": ok(" M README.md")}))
        self.assertEqual(code_of(gitrepo.inspect_repo, self.root, git=fake).code, "PAGES_LOCAL_REPO_DIRTY")


if __name__ == "__main__":
    unittest.main()
