"""연결한 chanceblog 로컬 저장소 확인 시험 — 폴더·origin·main·변경 여부 확인, 최신 받기, 올리기 점검, 실패의 오류 코드 분류.

실제 git 으로 임시 저장소(원격 역할의 bare 저장소 + 작업 사본 + 다른 사람 사본)를 만들어 돌린다. 네트워크·시크릿이 필요 없다.
인증·네트워크 실패는 실제로 만들 수 없어서 git 의 실제 오류 문구를 모은 표로 분류를 확인한다.
"""
import errno
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
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


# 긴 경로(임시 폴더 이름이 길 때)를 받아들이게 한다 — 환경 변수라서 git push 가 띄우는 자식(git-receive-pack)까지 이어진다
LONGPATH_ENV = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.longpaths", GIT_CONFIG_VALUE_0="true")


def git(cwd, *args):
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, env=LONGPATH_ENV)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr.decode('utf-8', 'replace')}")
    return done.stdout.decode("utf-8").strip()


def commit_file(repo, name, text, message="x"):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)


def process_alive(pid):
    """그 번호의 프로세스가 아직 돌고 있는지(Windows·POSIX 모두)."""
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259                                               # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_pid(pid):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


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
        git(origin, "config", "core.longpaths", "true")                 # 임시 폴더 이름이 길어도(환경 변수는 로컬 push 의 git-receive-pack 에 전해지지 않는다) 저장소 자체에 둔다
        git(origin, "symbolic-ref", "HEAD", "refs/heads/main")        # 다른 사본이 clone 하면 main 을 받게
        git(cls.base, "clone", "-q", str(origin), "work")
        work = cls.base / "work"
        git(work, "config", "core.autocrlf", "false")
        git(work, "config", "core.longpaths", "true")
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
        return self.other_pushes_file(name, "봇 글\n")

    def other_pushes_file(self, name, text):
        other = self.tmp / "other"
        if not other.exists():
            git(self.tmp, "clone", "-q", str(self.origin), "other")
            git(other, "config", "core.autocrlf", "false")
            git(other, "config", "core.longpaths", "true")
        git(other, "pull", "-q", "--ff-only", "origin", "main")
        commit_file(other, name, text, "bot")
        git(other, "push", "-q", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def bot_edits(self, files):
        """봇이 여러 파일(이미 추적 중인 것 포함)을 한 커밋으로 고쳐 올린다."""
        other = self.tmp / "other"
        if not other.exists():
            git(self.tmp, "clone", "-q", str(self.origin), "other")
            git(other, "config", "core.autocrlf", "false")
            git(other, "config", "core.longpaths", "true")
        git(other, "pull", "-q", "--ff-only", "origin", "main")
        for name, text in files.items():
            path = other / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            git(other, "add", "--", name)
        git(other, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "bot")
        git(other, "push", "-q", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def bot_changes(self, writes=None, deletes=(), renames=()):
        """봇이 한 커밋으로 파일을 쓰고(writes), 지우고(deletes), 이름을 바꿔(renames: (옛 이름, 새 이름)) 올린다."""
        other = self.tmp / "other"
        if not other.exists():
            git(self.tmp, "clone", "-q", str(self.origin), "other")
            git(other, "config", "core.autocrlf", "false")
            git(other, "config", "core.longpaths", "true")
        git(other, "pull", "-q", "--ff-only", "origin", "main")
        for old, new in renames:
            (other / new).parent.mkdir(parents=True, exist_ok=True)
            git(other, "mv", "--", old, new)
        for name in deletes:
            git(other, "rm", "-q", "--", name)
        for name, text in (writes or {}).items():
            path = other / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            git(other, "add", "--", name)
        git(other, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "bot")
        git(other, "push", "-q", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def lock(self, path):
        """git 이 그 파일을 바꾸지 못하게 한다. 풀어 주는 함수를 돌려준다. Windows: 다른 프로그램이 파일을 쓰는 중인 것처럼 읽기·쓰기만 공유하고 삭제는 공유하지 않게 연다 / POSIX: 폴더를 쓰기 금지로."""
        if os.name == "nt":
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.CreateFileW.restype = ctypes.c_void_p
            kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0, None)            # GENERIC_READ, 읽기·쓰기 공유(삭제 공유 없음 — 편집기가 파일을 연 모양: 읽을 수는 있어도 바꿔 치울 수 없다), OPEN_EXISTING
            if handle in (None, ctypes.c_void_p(-1).value):
                self.skipTest("이 환경에서는 파일을 잠글 수 없다")
            return lambda: kernel.CloseHandle(handle)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("관리자(root)는 쓰기 금지 폴더에도 쓸 수 있다")
        folder = Path(path).parent
        folder.chmod(0o555)
        return lambda: folder.chmod(0o755)

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

    # --- 독립 검토에서 나온 경우들: 실제 git 으로 확인 ---------------------------------------------------------------------
    def test_a_push_only_address_or_a_second_address_is_checked_like_the_first(self):
        git(self.work, "remote", "set-url", "--push", "origin", "https://evil.example/elsewhere.git")
        self.assertEqual(code_of(self.inspect).code, "PAGES_LOCAL_REPO_INVALID")
        git(self.work, "config", "--unset-all", "remote.origin.pushurl")
        self.inspect()
        git(self.work, "remote", "set-url", "--add", "origin", "https://evil.example/second.git")
        self.assertEqual(code_of(self.inspect).code, "PAGES_LOCAL_REPO_INVALID")

    def test_sync_latest_updates_tracked_files_the_bot_changed_including_ones_with_non_ascii_names(self):
        """봇이 이미 추적 중인 파일(기록 파일·한글 이름 파일)을 고쳐도 받아진다 — 내 파일로 오해해 막지 않는다."""
        commit_file(self.work, "기록/이력 파일.json", "{}\n", "tracked")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        new_head = self.bot_edits({"README.md": "봇이 고침\n", "기록/이력 파일.json": '{"a": 1}\n'})
        info = gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(info.head, new_head)
        self.assertEqual((self.work / "README.md").read_text(encoding="utf-8"), "봇이 고침\n")
        self.assertEqual((self.work / "기록" / "이력 파일.json").read_text(encoding="utf-8"), '{"a": 1}\n')

    def test_my_untracked_file_that_the_bots_file_would_overwrite_is_named_and_stays_untouched_and_moving_it_lets_the_sync_go_on(self):
        new_head = self.other_pushes("from_bot.md")
        mine = self.work / "from_bot.md"
        mine.write_text("내가 쓰던 메모\n", encoding="utf-8")
        before = git(self.work, "rev-parse", "HEAD")
        error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "PAGES_LOCAL_FILE_IN_THE_WAY")
        self.assertEqual(error.slots["파일"], "from_bot.md")
        self.assertIn("「from_bot.md」", error.rendered().message)
        self.assertEqual(mine.read_text(encoding="utf-8"), "내가 쓰던 메모\n")
        self.assertEqual(git(self.work, "rev-parse", "HEAD"), before)
        mine.rename(self.tmp / "내 메모 보관.md")                    # 안내대로 폴더 밖으로 옮기면
        self.assertEqual(gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN).head, new_head)
        self.assertEqual((self.work / "from_bot.md").read_text(encoding="utf-8"), "봇 글\n")

    def test_my_git_ignored_file_in_the_way_is_protected_too(self):
        """git 은 무시(.gitignore)한 파일을 병합 때 조용히 덮어쓰지만, 사용자의 파일이니 이 앱은 건드리지 않는다."""
        self.other_pushes("from_bot.md")
        with open(self.work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("\nfrom_bot.md\n")
        mine = self.work / "from_bot.md"
        mine.write_text("무시한 내 파일\n", encoding="utf-8")
        self.assertIn("!! from_bot.md", git(self.work, "status", "--porcelain", "--ignored"), "전제: 정말 무시 상태")
        error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual((error.code, error.slots["파일"]), ("PAGES_LOCAL_FILE_IN_THE_WAY", "from_bot.md"))
        self.assertEqual(mine.read_text(encoding="utf-8"), "무시한 내 파일\n")

    def test_a_file_of_mine_where_the_bot_adds_a_folder_and_a_folder_of_mine_where_the_bot_adds_a_file_are_both_kept(self):
        self.other_pushes("posts/x.md")                              # 봇은 posts/ 안에 파일을 올렸는데 내 폴더에는 posts 라는 '파일'이 있다
        (self.work / "posts").write_text("내 파일\n", encoding="utf-8")
        error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "PAGES_LOCAL_FILE_IN_THE_WAY")
        self.assertEqual((self.work / "posts").read_text(encoding="utf-8"), "내 파일\n")
        (self.work / "posts").unlink()
        self.assertEqual(git(self.work, "status", "--porcelain"), "")
        gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN)   # 치우면 받아진다
        self.other_pushes_file("docs", "봇의 docs 파일\n")           # 이번에는 봇이 'docs' 라는 파일을 올렸는데 내 폴더에는 docs/ 폴더가 있다
        (self.work / "docs").mkdir()
        (self.work / "docs" / "a.txt").write_text("내 폴더 안 파일\n", encoding="utf-8")
        error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "PAGES_LOCAL_FILE_IN_THE_WAY")
        self.assertEqual((self.work / "docs" / "a.txt").read_text(encoding="utf-8"), "내 폴더 안 파일\n")

    def test_a_merge_that_stops_in_the_middle_leaves_nothing_half_applied_and_works_once_the_lock_is_gone(self):
        commit_file(self.work, "a_first.md", "처음 내용\n", "a")
        commit_file(self.work, "sub/z.md", "z 처음\n", "z")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        new_head = self.bot_edits({"a_first.md": "봇이 고침\n", "sub/z.md": "z 봇이 고침\n"})
        release = self.lock(self.work / "sub" / "z.md")             # 다른 프로그램이 파일을 쓰는 중이거나 폴더가 쓰기 금지인 것처럼
        try:
            error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
            self.assertEqual(error.code, "FILE_IN_USE")
            self.assertEqual((self.work / "a_first.md").read_text(encoding="utf-8"), "처음 내용\n", "중간까지 바뀐 파일이 병합 전으로 되돌려져 있다")
            self.assertEqual(git(self.work, "status", "--porcelain"), "")
            self.assertEqual(git(self.work, "rev-parse", "HEAD"), git(self.work, "rev-parse", "origin/main~1"))
        finally:
            release()
        self.assertEqual(gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN).head, new_head)
        self.assertEqual((self.work / "a_first.md").read_text(encoding="utf-8"), "봇이 고침\n")

    def test_an_edit_made_just_before_the_merge_is_never_erased_when_git_refuses(self):
        """검사를 통과한 뒤 병합 직전에 내가 파일을 저장해도(편집기 자동 저장), git 이 병합을 거절하고 앱은 내 내용을 지우지 않는다(3차 검토 H1)."""
        commit_file(self.work, "a.md", "처음\n", "a")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.bot_edits({"a.md": "봇이 고침\n"})
        before = git(self.work, "rev-parse", "HEAD")
        for staged in (False, True):
            with self.subTest(staged=staged):
                def edit_then_merge(cwd, args, **kwargs):
                    if args[0] == "merge":
                        (self.work / "a.md").write_text("내가 방금 고침\n", encoding="utf-8", newline="\n")
                        if staged:
                            git(self.work, "add", "a.md")
                    return gitrepo.run_git(cwd, args, **kwargs)

                error = code_of(gitrepo.sync_latest, self.work, git=edit_then_merge, expected_origin=LOCAL_ORIGIN)
                self.assertEqual(error.code, "PAGES_LOCAL_REPO_DIRTY")
                self.assertEqual((self.work / "a.md").read_text(encoding="utf-8"), "내가 방금 고침\n", "되돌리기가 내가 고친 내용을 지웠다")
                self.assertEqual(git(self.work, "rev-parse", "HEAD"), before)
                git(self.work, "checkout", "-q", "--", "a.md")                  # 다음 경우를 위해 내 편집을 걷어 낸다(시험 정리)
                git(self.work, "reset", "-q", "HEAD", "--", "a.md")

    def test_files_hidden_with_assume_unchanged_are_never_reset_to_the_old_content(self):
        commit_file(self.work, "cfg.yml", "기본 설정\n", "cfg")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        git(self.work, "update-index", "--assume-unchanged", "cfg.yml")
        (self.work / "cfg.yml").write_text("내 설정\n", encoding="utf-8", newline="\n")
        self.bot_edits({"cfg.yml": "봇의 설정\n"})
        try:
            gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN)
        except AppError:
            pass
        self.assertNotEqual((self.work / "cfg.yml").read_text(encoding="utf-8"), "기본 설정\n", "되돌리기가 숨겨 둔 변경을 옛 내용으로 지웠다")

    def test_a_stopped_merge_gives_back_deleted_and_renamed_files_too(self):
        for name, text in (("d.md", "지워질 글\n"), ("old.md", "이름이 바뀔 글\n"), ("sub/z.md", "z 처음\n")):
            commit_file(self.work, name, text, name)
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.bot_changes(writes={"sub/z.md": "z 봇이 고침\n"}, deletes=["d.md"], renames=[("old.md", "new.md")])
        release = self.lock(self.work / "sub" / "z.md")
        try:
            error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
            self.assertEqual(error.code, "FILE_IN_USE")
            self.assertEqual((self.work / "d.md").read_text(encoding="utf-8"), "지워질 글\n", "병합이 지운 파일이 되살아나 있다")
            self.assertEqual((self.work / "old.md").read_text(encoding="utf-8"), "이름이 바뀔 글\n")
            self.assertFalse((self.work / "new.md").exists(), "병합이 만든 새 이름은 치운다")
            self.assertEqual(git(self.work, "status", "--porcelain"), "")
        finally:
            release()
        gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN)
        self.assertFalse((self.work / "d.md").exists())
        self.assertEqual((self.work / "new.md").read_text(encoding="utf-8"), "이름이 바뀔 글\n")

    def test_a_case_only_rename_together_with_a_stopped_merge_never_costs_me_the_tracked_file(self):
        commit_file(self.work, "sub/z.md", "z 처음\n", "z")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.bot_changes(writes={"sub/z.md": "z 봇이 고침\n"}, renames=[("README.md", "Readme.md")])
        release = self.lock(self.work / "sub" / "z.md")
        try:
            error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
            self.assertEqual(error.code, "FILE_IN_USE")
            self.assertEqual(git(self.work, "ls-files", "--", "README.md", "Readme.md"), "README.md", "추적 이름은 그대로")
            self.assertEqual((self.work / "README.md").read_text(encoding="utf-8"), "처음\n", "추적 파일이 지워졌다")
            self.assertEqual(git(self.work, "status", "--porcelain"), "")
        finally:
            release()
        gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(git(self.work, "ls-files", "--", "README.md", "Readme.md"), "Readme.md")

    def undo_with_autocrlf_true(self, eol):
        """줄바꿈 변환(core.autocrlf=true)이 켜진 저장소에서, 작업 폴더 파일의 줄바꿈이 `eol` 일 때 멈춘 병합을 되돌린 결과를 확인한다."""
        git(self.work, "config", "core.autocrlf", "true")
        for name, text in (("a.md", "첫 줄\n둘째 줄\n"), ("sub/z.md", "z 처음\n")):
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline=eol)
            git(self.work, "add", name)
        git(self.work, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "a")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.bot_changes(writes={"a.md": "봇이 고침\n둘째 줄\n", "sub/z.md": "z 봇이 고침\n"})
        release = self.lock(self.work / "sub" / "z.md")
        try:
            error = code_of(gitrepo.sync_latest, self.work, expected_origin=LOCAL_ORIGIN)
            self.assertEqual(error.code, "FILE_IN_USE")
            self.assertEqual((self.work / "a.md").read_bytes().replace(b"\r\n", b"\n"), "첫 줄\n둘째 줄\n".encode("utf-8"), "병합이 쓴 a.md 가 병합 전 내용으로 돌아가지 않았다")
            self.assertEqual(git(self.work, "status", "--porcelain"), "", "되돌린 파일을 git 이 '바뀜' 으로 보면 안 된다")
            self.assertNotIn("a.md", error.detail, "되돌렸으니 남은 파일로 알리지 않는다")
        finally:
            release()

    def test_the_undo_reads_file_contents_the_way_git_stores_them_even_with_autocrlf_true(self):
        self.undo_with_autocrlf_true("\r\n")

    def test_the_undo_leaves_no_phantom_change_when_git_rewrites_lf_files_as_crlf(self):
        self.undo_with_autocrlf_true("\n")                  # LF 로 둔 파일을 git 이 CRLF 로 되돌려 쓰면 크기가 색인에 적힌 것과 달라진다 — 색인 항목도 함께 되돌리지 않으면 내용이 같아도 '바뀜' 으로 남는다(어느 OS 에서나)

    def test_file_names_that_look_like_glob_patterns_are_taken_literally_by_the_undo(self):
        commit_file(self.work, "[x].md", "대괄호 글\n", "b")
        commit_file(self.work, "x.md", "x 처음\n", "x")
        commit_file(self.work, "sub/z.md", "z 처음\n", "z")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.bot_changes(writes={"[x].md": "봇이 고침\n", "sub/z.md": "z 봇이 고침\n"})
        release = self.lock(self.work / "sub" / "z.md")

        def edit_x_then_merge(cwd, args, **kwargs):
            if args[0] == "merge":
                (self.work / "x.md").write_text("내가 방금 고친 x\n", encoding="utf-8", newline="\n")
            return gitrepo.run_git(cwd, args, **kwargs)

        try:
            error = code_of(gitrepo.sync_latest, self.work, git=edit_x_then_merge, expected_origin=LOCAL_ORIGIN)
            self.assertEqual(error.code, "FILE_IN_USE")
            self.assertEqual((self.work / "[x].md").read_text(encoding="utf-8"), "대괄호 글\n", "병합이 쓴 [x].md 는 되돌린다")
            self.assertEqual((self.work / "x.md").read_text(encoding="utf-8"), "내가 방금 고친 x\n", "이름이 비슷한 내 x.md 는 글롭으로 읽혀 되돌려지지 않는다")
        finally:
            release()

    def test_a_merge_cut_off_by_the_time_limit_leaves_a_clean_folder_and_no_lock(self):
        commit_file(self.work, "a_first.md", "처음 내용\n", "a")
        commit_file(self.work, "sub/z.md", "z 처음\n", "z")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.bot_edits({"a_first.md": "봇이 고침\n", "sub/z.md": "z 봇이 고침\n"})

        def cut_off(cwd, args, **kwargs):
            if args[0] == "merge":
                git(self.work, "read-tree", "-m", "-u", "HEAD", "refs/remotes/origin/main")       # 파일은 다 써졌지만 HEAD 는 못 옮긴 채 끊긴 병합처럼
                (self.work / ".git" / "index.lock").write_text("", encoding="utf-8")               # 끈 git 이 남긴 잠금
                raise AppError("NETWORK_TIMEOUT", detail="git merge 가 90초 안에 끝나지 않았다")
            return gitrepo.run_git(cwd, args, **kwargs)

        error = code_of(gitrepo.sync_latest, self.work, git=cut_off, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "NETWORK_TIMEOUT")
        self.assertFalse((self.work / ".git" / "index.lock").exists(), "끊긴 병합이 남긴 잠금이 남아 다음 시도를 막는다")
        self.assertEqual((self.work / "a_first.md").read_text(encoding="utf-8"), "처음 내용\n")
        self.assertEqual((self.work / "sub" / "z.md").read_text(encoding="utf-8"), "z 처음\n")
        self.assertEqual(git(self.work, "status", "--porcelain"), "")
        self.assertEqual(gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN).head, git(self.work, "rev-parse", "origin/main"), "다음 시도는 그대로 받아진다")

    def test_the_users_own_ssh_command_setting_is_used_and_not_overridden(self):
        marker = self.tmp / "ssh-args.txt"
        script = self.tmp / "fake-ssh.sh"
        script.write_text(f'#!/bin/sh\necho "$@" > "{marker.as_posix()}"\nexit 255\n', encoding="utf-8", newline="\n")
        git(self.work, "config", "core.sshCommand", f'sh "{script.as_posix()}"')
        git(self.work, "remote", "set-url", "origin", "ssh://git@github.com/shine88pc/chanceblog.git")
        with mock.patch.dict(os.environ):
            os.environ.pop("GIT_SSH_COMMAND", None)
            os.environ.pop("GIT_SSH", None)
            code_of(gitrepo.check_push_access, self.work)           # 가짜 ssh 가 실패(255)하므로 오류가 난다 — 중요한 것은 어떤 ssh 가 불렸는가
        self.assertTrue(marker.is_file(), "사용자가 정한 ssh 명령(core.sshCommand)이 쓰이지 않았다")
        arguments = marker.read_text(encoding="utf-8")
        self.assertIn("git@github.com", arguments)
        self.assertNotIn("BatchMode", arguments, "앱이 ssh 옵션을 끼워 넣지 않는다")

    def test_tags_named_like_the_branches_do_not_confuse_the_check(self):
        git(self.work, "tag", "main")                  # 태그 main: `rev-parse --abbrev-ref HEAD` 는 'heads/main' 으로 읽어 main 이 아니라고 했던 경우
        git(self.work, "tag", "origin/main")           # 태그 origin/main: 원격 main 을 가리키는 이름을 가로채던 경우
        self.assertEqual(self.inspect().branch, "main")
        new_head = self.other_pushes()
        self.assertEqual(gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN).head, new_head)

    def test_the_fetch_uses_an_explicit_refspec_whatever_the_remote_config_says(self):
        git(self.work, "config", "remote.origin.fetch", "+refs/heads/nothing:refs/remotes/origin/nothing")
        new_head = self.other_pushes()
        self.assertEqual(gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN).head, new_head)

    def test_git_environment_variables_of_the_user_do_not_redirect_the_check(self):
        with mock.patch.dict(os.environ, {"GIT_DIR": str(self.origin), "GIT_WORK_TREE": str(self.tmp)}):
            info = self.inspect()
        self.assertEqual((info.path, info.head), (self.work, git(self.work, "rev-parse", "HEAD")))

    def test_the_push_check_does_not_run_the_users_pre_push_hook(self):
        hook = self.work / ".git" / "hooks" / "pre-push"
        marker = self.work / "hook-ran.txt"
        hook.write_text(f'#!/bin/sh\necho ran > "{marker.as_posix()}"\nexit 0\n', encoding="utf-8", newline="\n")
        hook.chmod(0o755)
        subprocess.run(["git", "-C", str(self.work), "push", "--dry-run", "origin", "HEAD:refs/heads/main"], capture_output=True)
        if not marker.exists():
            self.skipTest("이 git 은 dry-run 에서 pre-push 훅을 돌리지 않는다(시험이 의미 없다)")
        marker.unlink()                                 # 통제 실험: 평범한 git 은 훅을 돌렸다 → 이제 이 앱의 점검이 돌리지 않는지 본다
        gitrepo.check_push_access(self.work, expected_origin=LOCAL_ORIGIN)
        self.assertFalse(marker.exists(), "올리기 점검이 사용자의 훅을 돌렸다")

    def test_none_of_the_users_hooks_run_while_the_app_updates_the_folder(self):
        marker = self.tmp / "hooks-ran.txt"
        for name in ("post-merge", "reference-transaction", "post-checkout"):
            hook = self.work / ".git" / "hooks" / name
            hook.write_text(f'#!/bin/sh\necho {name} >> "{marker.as_posix()}"\nexit 0\n', encoding="utf-8", newline="\n")
            hook.chmod(0o755)
        new_head = self.other_pushes()
        control = self.tmp / "control"                                        # 통제 실험: 같은 훅을 가진 사본에서 평범한 git 은 훅을 돌린다
        shutil.copytree(self.work, control)
        subprocess.run(["git", "-C", str(control), "fetch", "-q", "origin"], capture_output=True)
        subprocess.run(["git", "-C", str(control), "merge", "-q", "--ff-only", "origin/main"], capture_output=True)
        if not marker.exists():
            self.skipTest("이 git 은 훅을 돌리지 않는다(시험이 의미 없다)")
        marker.unlink()
        self.assertEqual(gitrepo.sync_latest(self.work, expected_origin=LOCAL_ORIGIN).head, new_head)
        self.assertFalse(marker.exists(), "최신으로 맞추는 동안 사용자의 훅이 돌았다: " + (marker.read_text(encoding="utf-8").split()[0] if marker.exists() else ""))

    def test_a_junction_or_symlink_to_the_repository_is_accepted(self):
        link = self.tmp / "link-to-work"
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.work)], capture_output=True)
            if made.returncode != 0:
                self.skipTest("이 환경에서는 연결 폴더(junction)를 만들 수 없다")
        else:
            try:
                os.symlink(self.work, link, target_is_directory=True)
            except OSError:
                self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link) if os.name == "nt" else os.path.lexists(link) and os.unlink(link))
        self.assertEqual(self.inspect(link).head, git(self.work, "rev-parse", "HEAD"))

    @unittest.skipUnless(os.name == "nt", "Windows 의 8.3 짧은 경로 이야기다")
    def test_a_windows_short_8_3_path_is_accepted(self):
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(self.work), buffer, 1024)
        short = buffer.value if 0 < length < 1024 else str(self.work)
        if short.lower() == str(self.work).lower():
            self.skipTest("이 폴더는 8.3 짧은 이름이 없다")
        self.assertEqual(self.inspect(Path(short)).head, git(self.work, "rev-parse", "HEAD"))

    def test_a_branch_whose_name_only_starts_with_main_is_not_main(self):
        git(self.work, "checkout", "-q", "-b", "main-old")
        error = code_of(self.inspect)
        self.assertEqual((error.code, error.slots["브랜치"]), ("PAGES_LOCAL_REPO_NOT_MAIN", "main-old"))


class FakeGit:
    """git 인자의 앞부분으로 미리 정한 답을 돌려주는 가짜 실행기(답이 함수면 인자를 넘겨 부른다)."""

    def __init__(self, replies):
        self.replies = replies
        self.calls = []
        self.inputs = []

    def __call__(self, cwd, args, input_bytes=None):
        self.calls.append(list(args))
        self.inputs.append(input_bytes)
        text = " ".join(args)
        for prefix, reply in self.replies.items():
            if text.startswith(prefix):
                return reply(list(args)) if callable(reply) else reply
        raise AssertionError(f"예상하지 못한 git 호출: {text}")


def ok(stdout=""):
    return GitResult(0, stdout, "")


def fail(stderr, stdout="", code=128):
    return GitResult(code, stdout, stderr)


def raw(*items):
    """`git diff --raw -z --no-abbrev` 모양의 출력. 항목은 (상태, 이름) 또는 (상태, 이름, 옛 번호, 새 번호) — 상태는 A 새 파일·D 지워짐·M 바뀜·T 종류가 바뀜."""
    out = []
    for item in items:
        status, path = item[0], item[1]
        old, new = (item[2], item[3]) if len(item) > 2 else ("0" * 40 if status == "A" else "1" * 40, "0" * 40 if status == "D" else "2" * 40)
        old_mode, new_mode = ("000000" if status == "A" else "100644"), ("000000" if status == "D" else "100644")
        out.append(f":{old_mode} {new_mode} {old} {new} {status}\0{path}\0")
    return "".join(out)


class FailureClassificationTest(unittest.TestCase):
    def test_real_messages_found_by_the_fourth_review(self):
        for message, code in (
            ("Connection to github.com closed by remote host.\nfatal: Could not read from remote repository.\n\nPlease make sure you have the correct access rights\nand the repository exists.", "GIT_PUSH_NETWORK"),
            ("error: unable to unlink old 'a/very/long/path.md': Filename too long", "FILE_PATH_TOO_LONG"),
            ("warning: unable to access '/home/u/.config/git/attributes': Permission denied\nfatal: something nobody has seen before", UNEXPECTED),
            ("remote: Support for password authentication was removed on August 13, 2021.\nremote: Please see https://docs.github.com/ for information on currently recommended modes of authentication.\n"
             "fatal: Authentication failed for 'https://github.com/x/y.git/'", "GIT_PUSH_AUTH"),
            ("error: RPC failed; curl 18 transfer closed with outstanding read data remaining\nerror: 1234 bytes of body are still expected\nfetch-pack: unexpected disconnect while reading sideband packet\n"
             "fatal: early EOF\nfatal: fetch-pack: invalid index-pack output", "GIT_PUSH_NETWORK"),
        ):
            with self.subTest(message=message[:50]):
                self.assertEqual(gitrepo.classify_git_failure(message), code)

    CASES = {
        "GIT_PUSH_AUTH": (
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
            "remote: Invalid username or password.\nfatal: Authentication failed for 'https://github.com/shine88pc/chanceblog.git/'",
            "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': The requested URL returned error: 403",
            "remote: Permission to shine88pc/chanceblog.git denied to someone.\nfatal: unable to access 'https://github.com/x/y.git/': The requested URL returned error: 403",
            "remote: Repository not found.\nfatal: repository 'https://github.com/x/y.git/' not found",
            "git@github.com: Permission denied (publickey).\nfatal: Could not read from remote repository.",
            "fatal: unable to access 'https://github.com/x/y.git/': The requested URL returned error: 401",
            "git@github.com: Permission denied (publickey,keyboard-interactive).\nfatal: Could not read from remote repository.",
            "remote: Permission to shine88pc/chanceblog.git denied to someone.",
            # 서버가 규칙으로 막음(보호된 브랜치·규칙 위반·서버 훅): 'failed to push some refs' 가 같이 나와도 거절(봇이 먼저 올림)이 아니라 권한 문제다
            "remote: error: GH006: Protected branch update failed for refs/heads/main.\nTo https://github.com/x/y.git\n ! [remote rejected] HEAD -> main (protected branch hook declined)\nerror: failed to push some refs to 'https://github.com/x/y.git'",
            "remote: error: GH013: Repository rule violations found for refs/heads/main.\nremote: - Changes must be made through a pull request.",
            " ! [remote rejected] HEAD -> main (pre-receive hook declined)",
            "remote: error: GH007: Your push would publish a private email address.\nremote: You can make your email public or disable this protection by visiting:\nremote: https://github.com/settings/emails\nTo https://github.com/x/y.git\n ! [remote rejected] HEAD -> main (push declined due to email privacy restrictions)\nerror: failed to push some refs to 'https://github.com/x/y.git'",
        ),
        "GIT_IDENTITY_MISSING": (
            "Author identity unknown\n\n*** Please tell me who you are.\n\nRun\n\n  git config --global user.email \"you@example.com\"\n  git config --global user.name \"Your Name\"\n\nto set your account's default identity.\nfatal: unable to auto-detect email address (got 'user@host.(none)')",
            "fatal: unable to auto-detect email address (got 'user@PC.(none)')",
            "fatal: empty ident name (for <>) not allowed",
        ),
        "GIT_PUSH_NETWORK": (
            "fatal: unable to access 'https://github.com/x/y.git/': Could not resolve host: github.com",
            "fatal: unable to access 'https://github.com/x/y.git/': Failed to connect to github.com port 443 after 21060 ms: Couldn't connect to server",
            "fatal: unable to access 'https://github.com/x/y.git/': Connection timed out after 300000 milliseconds",
            "fatal: unable to access 'https://github.com/x/y.git/': schannel: next InitializeSecurityContext failed: Unknown error",
            "fatal: unable to access 'https://github.com/x/y.git/': SSL certificate problem: unable to get local issuer certificate",
            "fatal: unable to access 'https://github.com/x/y.git/': Recv failure: Connection was reset",
            "fatal: the remote end hung up unexpectedly",
            # SSH 주소의 연결 실패·연결 뒤 끊김: 뒤에 'Could not read from remote repository' 가 같이 나와도 로그인 문제가 아니라 네트워크다
            "ssh: connect to host github.com port 22: Connection refused\nfatal: Could not read from remote repository.\n\nPlease make sure you have the correct access rights\nand the repository exists.",
            "ssh: Could not resolve hostname github.com: Name or service not known\nfatal: Could not read from remote repository.",
            "kex_exchange_identification: read: Connection reset by peer\nfatal: Could not read from remote repository.",
            "ssh_dispatch_run_fatal: Connection to 127.0.0.1 port 22: message authentication code incorrect\nfatal: Could not read from remote repository.",
            "Read from remote host github.com: Software caused connection abort\nfatal: Could not read from remote repository.",
            "Connection closed by 140.82.112.3 port 22\nfatal: Could not read from remote repository.",
            "client_loop: send disconnect: Connection reset\nfatal: Could not read from remote repository.",
            "Connection reset by 140.82.112.3 port 22\nfatal: Could not read from remote repository.",
            "packet_write_wait: Connection to 140.82.112.3 port 22: Broken pipe\nfatal: Could not read from remote repository.",
        ),
        "GIT_PUSH_REJECTED": (
            "To https://github.com/x/y.git\n ! [rejected]        HEAD -> main (fetch first)\nerror: failed to push some refs to 'https://github.com/x/y.git'",
            " ! [rejected]        main -> main (non-fast-forward)",
            "error: failed to push some refs to 'https://github.com/x/y.git'",
            # 같은 출력에 파일 잠금 경쟁 문구가 같이 있어도 '거절(봇이 먼저 올림)' 이 먼저다
            "error: cannot lock ref 'refs/remotes/origin/main': is at A but expected B\n ! [rejected]        main -> main (fetch first)\nerror: failed to push some refs to 'x'",
        ),
        "FILE_IN_USE": (
            "error: unable to unlink old 'z.md': Permission denied",
            "error: unable to unlink old 'sub/z.md': Invalid argument\nfatal: Could not reset index file to revision 'refs/remotes/origin/main'.",
            "fatal: Unable to create 'C:/work/chanceblog/.git/index.lock': The process cannot access the file because it is being used by another process.",
            "error: cannot be removed: Text file busy",
            "error: unable to write file x: Device or resource busy",
        ),
        "FILE_WRITE_FAILED": (
            "error: unable to create file posts/x.md: Permission denied",
            "fatal: Unable to create 'C:/work/chanceblog/.git/index.lock': Permission denied",
            "error: cannot lock ref 'refs/remotes/origin/main': Unable to create '.git/refs/remotes/origin/main.lock'",
            "error: unable to write file a.md",
            "error: cannot open '.git/FETCH_HEAD': Permission denied",
        ),
        "DISK_FULL": ("error: unable to write file x\nfatal: write error: No space left on device",),
        "FILE_PATH_TOO_LONG": (
            "error: unable to create file 한글/아주/긴/경로/글.md: Filename too long",
            "fatal: Unable to create 'C:/work/.git/index.lock': Filename too long",
            "fatal: cannot open '.git/FETCH_HEAD': Filename too long",
        ),
        UNEXPECTED: (
            "fatal: not a git repository (or any of the parent directories): .git", "", "무슨 말인지 모를 출력",
            "error: Permission denied", "permission denied while reading a local file",
        ),
    }

    def test_real_git_messages_map_to_the_right_codes(self):
        for code, messages in self.CASES.items():
            for message in messages:
                with self.subTest(code=code, message=message[:60]):
                    self.assertEqual(gitrepo.classify_git_failure(message), code)
                    self.assertEqual(gitrepo.classify_git_failure(message.upper()), code, "대소문자와 무관")

    def test_a_local_file_failure_names_the_folder_in_the_user_message(self):
        for text, code in (("error: unable to unlink old 'z.md': Permission denied", "FILE_IN_USE"), ("error: unable to create file x.md: Permission denied", "FILE_WRITE_FAILED")):
            with self.subTest(code=code):
                error = gitrepo._failure(fail(text), "원격 main 따라잡기", Path("C:/work/chanceblog"))
                self.assertEqual(error.code, code)
                self.assertIn("「C:/work/chanceblog」", error.rendered().message.replace("\\", "/"))
        self.assertIsNone(gitrepo._failure(fail("fatal: not a repo"), "x", Path("C:/w")).slots or None)

    def test_a_huge_failure_output_is_masked_only_in_its_tail(self):
        seen = []
        real = gitrepo.mask

        def spy(value):
            seen.append(len(value))
            return real(value)

        with mock.patch.object(gitrepo, "mask", spy):
            error = gitrepo._failure(fail("x" * 3000000 + "fatal: Could not resolve host: github.com"), "받기")
        self.assertEqual(error.code, "GIT_PUSH_NETWORK")
        self.assertLessEqual(max(seen), 8100, "통째로 가리면 아주 큰 출력에서 오래 걸린다")
        self.assertTrue(error.detail.endswith("Could not resolve host: github.com"))

    def test_credentials_inside_urls_are_hidden(self):
        self.assertEqual(gitrepo.hide_credentials("https://user:ghp_secretvalue@github.com/a/b.git"), "https://***@github.com/a/b.git")
        self.assertEqual(gitrepo.hide_credentials("git@github.com:a/b.git"), "git@github.com:a/b.git")
        self.assertEqual(gitrepo.hide_credentials("see https://github.com/a/b"), "see https://github.com/a/b")
        self.assertEqual(gitrepo.hide_credentials("https://u:p@ss@github.com/a/b.git"), "https://***@github.com/a/b.git", "비밀번호에 @ 가 있어도")


class RunnerTest(unittest.TestCase):
    def fake_popen(self, out=b"ok\n", err=b"", code=0, waits=None):
        """Popen 대신: 넘겨받은 임시 파일에 출력을 쓰고, 프로세스는 곧 끝난 것처럼 구는 가짜(waits 로 wait 의 동작을 바꾼다)."""
        made = []

        def popen(command, **kwargs):
            kwargs["stdout"].write(out)
            kwargs["stderr"].write(err)
            process = mock.Mock()
            process.returncode = code
            process.pid = 4242
            process.wait.side_effect = list(waits) if isinstance(waits, (list, tuple)) else (waits if waits is not None else [code])
            made.append((command, kwargs, process))
            return process

        popen.made = made
        return popen

    def test_git_runs_without_prompts_in_english_with_a_clean_environment(self):
        dropped = {name: "x" for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_INDEX_FILE")}
        with mock.patch.dict(os.environ, dropped):
            os.environ.pop("GIT_SSH_COMMAND", None)
            popen = self.fake_popen()
            with mock.patch("subprocess.Popen", popen):
                result = gitrepo.run_git("C:/somewhere", ["status"])
        self.assertEqual((result.returncode, result.stdout), (0, "ok\n"))
        (command, kwargs, _process), = popen.made
        self.assertEqual(command[:3], ["git", "-C", "C:/somewhere"])
        self.assertEqual(command[-1], "status")
        for option in ("http.lowSpeedLimit=1000", "http.lowSpeedTime=30", "gc.auto=0", "maintenance.auto=false", f"core.hooksPath={os.devnull}", "commit.gpgsign=false", "push.gpgSign=false", "user.useConfigOnly=true", "i18n.commitEncoding=UTF-8", "i18n.logOutputEncoding=UTF-8"):
            self.assertIn(option, command)
        env = kwargs["env"]
        self.assertEqual((env["GIT_TERMINAL_PROMPT"], env["GCM_INTERACTIVE"], env["LC_ALL"], env["LANGUAGE"], env["GIT_OPTIONAL_LOCKS"]), ("0", "false", "C", "C", "0"))
        self.assertEqual((env["GIT_EDITOR"], env["GIT_MERGE_AUTOEDIT"]), ("true", "no"), "편집기 창이 뜨지 않게")
        for name in dropped:
            self.assertNotIn(name, env, name)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL, "입력 장치를 막아 대화창 입력을 기다리며 멈추지 않게")
        self.assertNotEqual(kwargs["stdout"], subprocess.PIPE, "출력은 파이프가 아니라 임시 파일로 받는다")
        self.assertNotEqual(kwargs["stderr"], subprocess.PIPE)
        if os.name == "nt":
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)      # 화면 앞에 검은 창이 깜빡이지 않게
        else:
            self.assertTrue(kwargs["start_new_session"])                                # 시간 초과 때 프로세스 묶음을 한 번에 끄려고

    def test_every_environment_variable_that_could_redirect_git_or_open_a_dialog_is_dropped(self):
        names = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_ASKPASS", "SSH_ASKPASS")
        with mock.patch.dict(os.environ, {name: "x" for name in names}):
            env = gitrepo._git_env()
        for name in names:
            self.assertNotIn(name, env, name)
        self.assertEqual(set(gitrepo._ENV_DROP), set(names), "지우는 목록이 달라졌다 — 의도한 것인지 확인한다")

    def test_the_users_own_ssh_settings_are_left_alone(self):
        with mock.patch.dict(os.environ, {"GIT_SSH_COMMAND": "ssh -i C:/keys/mine", "GIT_SSH": "C:/tools/plink.exe"}):
            env = gitrepo._git_env()
        self.assertEqual((env["GIT_SSH_COMMAND"], env["GIT_SSH"]), ("ssh -i C:/keys/mine", "C:/tools/plink.exe"))
        with mock.patch.dict(os.environ):
            os.environ.pop("GIT_SSH_COMMAND", None)
            os.environ.pop("GIT_SSH", None)
            env = gitrepo._git_env()
        self.assertNotIn("GIT_SSH_COMMAND", env, "사용자의 core.sshCommand·에이전트·PuTTY 설정을 덮어쓰지 않는다")
        self.assertNotIn("GIT_SSH", env)

    def run_through_a_spy(self, args, config=None, env=None):
        """run_command 를 가짜로 바꿔 git 호출들을 모은다. 첫 호출이 `git config --get core.sshCommand` 면 config 로 답한다."""
        calls = []

        def spy(command, **kwargs):
            calls.append((command, kwargs))
            if command[3:5] == ["config", "--get"]:
                return config if config is not None else GitResult(1, "", "")
            return GitResult(0, "", "")

        with mock.patch.dict(os.environ, env or {}), mock.patch.object(gitrepo, "run_command", spy):
            for name in ("GIT_SSH", "GIT_SSH_COMMAND"):
                if name not in (env or {}):
                    os.environ.pop(name, None)
            gitrepo.run_git("C:/repo", args)
        return calls

    def test_a_network_command_gets_batch_mode_ssh_only_when_the_user_chose_no_ssh_command(self):
        for command in ("fetch", "push", "ls-remote", "pull", "clone"):
            with self.subTest(command=command):
                calls = self.run_through_a_spy([command, "origin"])
                self.assertEqual(calls[0][0], ["git", "-C", "C:/repo", "config", "--get", "core.sshCommand"])
                self.assertEqual(calls[-1][1]["env"]["GIT_SSH_COMMAND"], "ssh -o BatchMode=yes", "질문을 입력 없이 기다리며 멈추지 않게")
        calls = self.run_through_a_spy(["fetch"], config=GitResult(128, "", "fatal: bad config"))
        self.assertEqual(calls[-1][1]["env"]["GIT_SSH_COMMAND"], "ssh -o BatchMode=yes", "설정을 읽지 못하면 정한 것이 없는 것으로")

    def test_the_users_own_ssh_command_is_never_overridden_by_that_default(self):
        calls = self.run_through_a_spy(["push"], config=GitResult(0, "plink.exe -ssh -batch\n", ""))
        self.assertNotIn("GIT_SSH_COMMAND", calls[-1][1]["env"], "core.sshCommand 가 있으면 그대로 쓴다")
        for env in ({"GIT_SSH_COMMAND": "ssh -i C:/keys/mine"}, {"GIT_SSH": "C:/tools/plink.exe"}):
            with self.subTest(env=env):
                calls = self.run_through_a_spy(["fetch"], env=env)
                self.assertEqual(len(calls), 1, "환경 변수로 정했으면 설정을 읽어 보지도 않는다")
                for name, value in env.items():
                    self.assertEqual(calls[0][1]["env"][name], value)
        self.assertNotIn("GIT_SSH_COMMAND", self.run_through_a_spy(["fetch"], env={"GIT_SSH": "C:/tools/plink.exe"})[0][1]["env"])

    def test_commands_that_do_not_talk_to_the_remote_get_no_ssh_setting_and_no_extra_call(self):
        for command in ("status", "merge", "rev-parse", "diff", "restore"):
            with self.subTest(command=command):
                calls = self.run_through_a_spy([command])
                self.assertEqual(len(calls), 1)
                self.assertNotIn("GIT_SSH_COMMAND", calls[0][1]["env"])

    def test_every_git_command_reads_path_arguments_literally(self):
        calls = self.run_through_a_spy(["restore", "--", "[x].md"])
        self.assertEqual(calls[0][1]["env"]["GIT_LITERAL_PATHSPECS"], "1", "`[x].md` 가 x.md 까지 가리키는 글롭으로 읽히지 않게")

    def test_input_for_a_command_is_handed_over_through_a_temporary_file(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = gitrepo.run_command([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"], env=env, timeout=30, input_bytes="안녕 hello\n".encode("utf-8"))
        self.assertEqual(result.stdout.strip(), "안녕 HELLO")
        nothing = gitrepo.run_command([sys.executable, "-c", "import sys; sys.stdout.write(repr(sys.stdin.read()))"], env=env, timeout=30)
        self.assertEqual(nothing.stdout, "''", "입력을 주지 않으면 입력 장치는 막혀 있다")

    def test_a_temporary_file_problem_is_a_file_error_naming_the_folder_not_a_crash(self):
        for problem in (FileNotFoundError(errno.ENOENT, "No such file or directory"), PermissionError(errno.EACCES, "Permission denied"), OSError(errno.ENOSPC, "No space left on device")):
            with self.subTest(problem=type(problem).__name__):
                with mock.patch("tempfile.TemporaryFile", side_effect=problem):
                    error = code_of(gitrepo.run_command, ["git", "status"])
                self.assertEqual(error.code, "FILE_WRITE_FAILED")
                self.assertEqual(error.slots["경로"], tempfile.gettempdir())
        made = []
        real = tempfile.TemporaryFile

        def second_one_fails(*args, **kwargs):
            if made:
                raise OSError(errno.ENOSPC, "No space left on device")
            made.append(real())
            return made[0]

        with mock.patch("tempfile.TemporaryFile", side_effect=second_one_fails):
            self.assertEqual(code_of(gitrepo.run_command, ["git", "status"]).code, "FILE_WRITE_FAILED")
        self.assertTrue(made[0].closed, "먼저 만든 임시 파일을 닫는다")

    def test_a_command_line_that_is_too_long_is_not_reported_as_git_missing(self):
        problems = [OSError(errno.E2BIG, "Argument list too long")]
        if os.name == "nt":
            problems.append(OSError(0, "The filename or extension is too long", None, 206))
        for problem in problems:
            with self.subTest(problem=str(problem)):
                with mock.patch("subprocess.Popen", side_effect=problem):
                    error = code_of(gitrepo.run_command, ["git", "status"])
                self.assertEqual(error.code, UNEXPECTED)
                self.assertIn("명령줄이 너무 길다", error.detail)

    def test_a_missing_or_unusable_git_is_git_not_installed(self):
        for problem in (FileNotFoundError(2, "No such file"), PermissionError(13, "Permission denied"), OSError(8, "%1 is not a valid Win32 application")):
            with self.subTest(problem=type(problem).__name__):
                with mock.patch("subprocess.Popen", side_effect=problem):
                    error = code_of(gitrepo.run_git, ".", ["status"])
                self.assertEqual(error.code, "GIT_NOT_INSTALLED")
                self.assertIn(type(problem).__name__, error.detail)

    def test_a_timeout_kills_the_whole_tree_and_is_a_network_timeout(self):
        popen = self.fake_popen(waits=[subprocess.TimeoutExpired("git", 90), 0])
        with mock.patch("subprocess.Popen", popen), mock.patch.object(gitrepo, "_kill_tree") as kill:
            error = code_of(gitrepo.run_git, ".", ["status"])
        self.assertEqual(error.code, "NETWORK_TIMEOUT")
        process = popen.made[0][2]
        kill.assert_called_once_with(process)
        self.assertEqual(process.wait.call_args_list, [mock.call(timeout=90), mock.call(timeout=5)], "끈 뒤 확인하는 대기에도 시간 제한이 있어야 한다")

    def test_a_process_that_cannot_be_ended_does_not_make_the_timeout_wait_forever(self):
        popen = self.fake_popen(waits=[subprocess.TimeoutExpired("git", 90), subprocess.TimeoutExpired("git", 5)])
        with mock.patch("subprocess.Popen", popen), mock.patch.object(gitrepo, "_kill_tree"):
            self.assertEqual(code_of(gitrepo.run_git, ".", ["status"]).code, "NETWORK_TIMEOUT")

    def test_an_interrupt_also_kills_the_process_and_is_not_swallowed(self):
        popen = self.fake_popen(waits=KeyboardInterrupt)
        with mock.patch("subprocess.Popen", popen), mock.patch.object(gitrepo, "_kill_tree") as kill:
            with self.assertRaises(KeyboardInterrupt):
                gitrepo.run_git(".", ["status"])
        kill.assert_called_once_with(popen.made[0][2])

    def test_output_is_decoded_leniently(self):
        with mock.patch("subprocess.Popen", self.fake_popen(out=b"\xff\xfe", err="한글".encode("utf-8"), code=1, waits=[1])):
            result = gitrepo.run_git(".", ["x"])
        self.assertEqual((result.returncode, result.stderr), (1, "한글"))

    def test_a_huge_stdout_is_an_error_not_a_silent_cut_and_stderr_keeps_its_tail(self):
        with mock.patch.object(gitrepo, "_MAX_STDOUT", 10), mock.patch("subprocess.Popen", self.fake_popen(out=b"x" * 20)):
            self.assertEqual(code_of(gitrepo.run_git, ".", ["ls-files"]).code, UNEXPECTED)
        with mock.patch.object(gitrepo, "_STDERR_TAIL", 5), mock.patch("subprocess.Popen", self.fake_popen(err=b"0123456789")):
            self.assertEqual(gitrepo.run_git(".", ["x"]).stderr, "56789")

    def test_a_real_process_tree_is_ended_at_the_time_limit(self):
        """git 이 손자 프로세스(git-remote-https·ssh)를 띄운 채 멈춰도, 시간이 되면 손자까지 모두 끄고 곧 돌아온다."""
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "grandchild.pid"
            code = ("import pathlib, subprocess, sys, time\n"
                    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                    f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                    "time.sleep(60)\n")
            started = time.time()
            error = code_of(gitrepo.run_command, [sys.executable, "-c", code], timeout=10, label="시험 명령")
            elapsed = time.time() - started
            self.assertTrue(pid_file.is_file(), "시험 준비(손자 프로세스 시작)가 제한 시간 안에 끝나지 못했다")
            grandchild = int(pid_file.read_text())
            try:
                self.assertEqual(error.code, "NETWORK_TIMEOUT")
                self.assertLess(elapsed, 35, "손자가 있어도 오래 기다리지 않는다")
                self.assertIn("10초", error.detail)
                deadline = time.time() + 10
                while process_alive(grandchild) and time.time() < deadline:
                    time.sleep(0.2)
                self.assertFalse(process_alive(grandchild), "시간 초과 뒤에도 손자 프로세스가 살아 있다 — 프로세스 트리를 끄지 못했다")
            finally:
                if process_alive(grandchild):
                    kill_pid(grandchild)

    def test_a_command_that_finished_while_a_grandchild_still_holds_its_output_returns_at_once(self):
        """명령은 정상으로 끝났는데 그 손자(ssh 연결 유지 등)가 출력 장치를 쥔 채 남아 있어도 끝을 기다리지 않고 결과를 돌려준다."""
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "grandchild.pid"
            code = ("import pathlib, subprocess, sys\n"
                    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(40)'])\n"
                    f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                    "print('done')\n")
            started = time.time()
            try:
                result = gitrepo.run_command([sys.executable, "-c", code], timeout=30, label="시험 명령")
                elapsed = time.time() - started
            finally:
                if pid_file.is_file():
                    kill_pid(int(pid_file.read_text()))
            self.assertEqual((result.returncode, result.stdout.strip()), (0, "done"))
            self.assertLess(elapsed, 25, "끝난 명령의 손자가 쥐고 있는 출력 때문에 매달렸다")

    def test_a_real_command_returns_its_output(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")           # 시험용 자식 파이썬이 UTF-8 로 쓰게(한국어 Windows 의 기본은 cp949)
        result = gitrepo.run_command([sys.executable, "-c", "import sys; print('안녕'); sys.stderr.write('경고'); sys.exit(3)"], env=env, timeout=30)
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (3, "안녕", "경고"))

    def test_a_big_real_output_is_read_completely(self):
        result = gitrepo.run_command([sys.executable, "-c", "import sys; sys.stdout.write('가' * 3000000)"], env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=60)
        self.assertEqual(len(result.stdout), 3000000)


class FailureDetailTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def replies(self, **overrides):
        replies = {
            "rev-parse --show-toplevel": ok(str(self.root)),
            "remote get-url": ok("https://github.com/shine88pc/chanceblog.git"),
            "symbolic-ref": ok("refs/heads/main"),
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
                    "https://github.com.evil.example/shine88pc/chanceblog.git", "https://github.com/shine88pc/chanceblog.git.evil", "",
                    "https://githubXcom/shine88pc/chanceblog.git", "https://g\u0131thub.com/shine88pc/chanceblog.git", "https://github.com/ſhine88pc/chanceblog.git",
                    "https://github.com/shine88pc/chanceblog.git\nhttps://evil.example/x"):
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
        self.assertNotIn(secret, error.log_line())

    def test_both_the_fetch_and_the_push_addresses_are_checked(self):
        def answer(args):
            return ok("https://github.com/shine88pc/chanceblog.git" if "--push" not in args else "https://evil.example/elsewhere.git")

        fake = FakeGit(self.replies(**{"remote get-url": answer}))
        error = code_of(gitrepo.inspect_repo, self.root, git=fake)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_INVALID")
        self.assertIn(["remote", "get-url", "--all", "origin"], fake.calls)
        self.assertIn(["remote", "get-url", "--push", "--all", "origin"], fake.calls)
        two_urls = FakeGit(self.replies(**{"remote get-url": ok("https://github.com/shine88pc/chanceblog.git\nhttps://evil.example/x.git")}))
        self.assertEqual(code_of(gitrepo.inspect_repo, self.root, git=two_urls).code, "PAGES_LOCAL_REPO_INVALID")
        no_origin = FakeGit(self.replies(**{"remote get-url": fail("error: No such remote 'origin'")}))
        self.assertEqual(code_of(gitrepo.inspect_repo, self.root, git=no_origin).code, "PAGES_LOCAL_REPO_INVALID")

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

    def test_the_push_check_never_runs_the_users_hooks_and_never_really_pushes(self):
        fake = FakeGit(self.replies(**{"push --dry-run": ok("")}))
        gitrepo.check_push_access(self.root, git=fake)
        push = next(call for call in fake.calls if call[0] == "push")
        self.assertEqual(push, ["push", "--dry-run", "--porcelain", "--no-verify", "origin", "HEAD:refs/heads/main"])

    def test_a_very_long_git_output_is_cut_to_its_tail_in_the_detail(self):
        stderr = "x" * 5000 + "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': Could not resolve host: github.com"
        fake = FakeGit(self.replies(**{"push --dry-run": fail(stderr)}))
        error = code_of(gitrepo.check_push_access, self.root, git=fake)
        self.assertEqual(error.code, "GIT_PUSH_NETWORK")
        self.assertLessEqual(len(error.detail), 440, "세부는 끝부분 400자만 남긴다")
        self.assertTrue(error.detail.endswith("Could not resolve host: github.com"), "원인이 있는 끝부분이 남아야 한다")

    def test_a_token_that_straddles_the_cut_is_masked_before_cutting(self):
        """끝 400자만 남기기 전에 가린다 — 순서가 거꾸로면 잘린 토큰 조각(접두어가 잘려 나가 패턴에 안 맞는 부분)이 그대로 남는다."""
        token = "gh" + "p_" + "z" * 40
        stderr = "x" * 10 + " " + token + " " + "y" * 380          # 끝 400자의 시작선이 토큰 한가운데를 지난다
        self.assertLess(len(stderr) - gitrepo._DETAIL_CHARS, stderr.index(token) + len(token))
        self.assertGreater(len(stderr) - gitrepo._DETAIL_CHARS, stderr.index(token))
        fake = FakeGit(self.replies(**{"push --dry-run": fail(stderr)}))
        error = code_of(gitrepo.check_push_access, self.root, git=fake)
        self.assertNotIn("z" * 5, error.detail)
        self.assertNotIn("ghp_", error.detail)

    def test_an_unknown_failure_is_the_catch_all_with_a_detail_for_developers(self):
        fake = FakeGit(self.replies(**{"symbolic-ref": fail("fatal: ambiguous argument 'HEAD': unknown revision")}))
        error = code_of(gitrepo.inspect_repo, self.root, git=fake)
        self.assertEqual(error.code, UNEXPECTED)
        self.assertIn("ambiguous", error.detail)

    def test_the_check_order_is_repository_then_branch_then_changes(self):
        fake = FakeGit(self.replies(**{"symbolic-ref": ok("refs/heads/feature"), "status --porcelain": ok(" M README.md")}))
        self.assertEqual(code_of(gitrepo.inspect_repo, self.root, git=fake).code, "PAGES_LOCAL_REPO_NOT_MAIN")
        fake = FakeGit(self.replies(**{"status --porcelain": ok(" M README.md")}))
        self.assertEqual(code_of(gitrepo.inspect_repo, self.root, git=fake).code, "PAGES_LOCAL_REPO_DIRTY")

    def test_only_a_branch_named_exactly_main_passes(self):
        for ref, shown in (("refs/heads/main-old", "main-old"), ("refs/heads/mainline", "mainline"), ("refs/heads/Main", "Main"), ("refs/heads/feature/main", "feature/main")):
            with self.subTest(ref=ref):
                error = code_of(gitrepo.inspect_repo, self.root, git=FakeGit(self.replies(**{"symbolic-ref": ok(ref)})))
                self.assertEqual((error.code, error.slots["브랜치"]), ("PAGES_LOCAL_REPO_NOT_MAIN", shown))

    def test_a_detached_head_is_not_main_and_says_so(self):
        error = code_of(gitrepo.inspect_repo, self.root, git=FakeGit(self.replies(**{"symbolic-ref": fail("", code=1)})))
        self.assertEqual((error.code, error.slots["브랜치"]), ("PAGES_LOCAL_REPO_NOT_MAIN", "(분리된 HEAD)"))

    def test_a_path_that_git_reports_in_a_form_python_cannot_open_is_refused_as_an_error_code_not_a_crash(self):
        fake = FakeGit(self.replies(**{"rev-parse --show-toplevel": ok("/c/definitely/not/a/real/path/here")}))
        self.assertEqual(code_of(gitrepo.inspect_repo, self.root, git=fake).code, "PAGES_LOCAL_REPO_INVALID")

    def test_the_reason_git_gives_for_not_treating_the_folder_as_a_repository_is_kept_in_the_detail(self):
        fake = FakeGit(self.replies(**{"rev-parse --show-toplevel": fail("fatal: detected dubious ownership in repository at 'C:/work/chanceblog'")}))
        error = code_of(gitrepo.inspect_repo, self.root, git=fake)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_INVALID")
        self.assertIn("dubious ownership", error.detail)

    def test_an_empty_folder_setting_is_refused_instead_of_meaning_the_current_folder(self):
        for bad in ("", "   ", None):
            with self.subTest(bad=bad):
                self.assertEqual(code_of(gitrepo.inspect_repo, bad, git=FakeGit({})).code, "PAGES_LOCAL_REPO_INVALID")


class SyncFailureTest(unittest.TestCase):
    """최신 받기가 실패하거나 어긋나는 여러 경우 — 실제 git 으로 만들기 어려운 것은 가짜 실행기로."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()

    def replies(self, **overrides):
        """기본 답 + 덮어쓸 답. 덮어쓰는 쪽(보통 더 구체적인 앞부분)을 먼저 둬서 먼저 맞게 한다."""
        defaults = {
            "rev-parse --show-toplevel": ok(str(self.root)),
            "remote get-url": ok("https://github.com/shine88pc/chanceblog.git"),
            "symbolic-ref": ok("refs/heads/main"),
            "status --porcelain": ok(""),
            "fetch": ok(""),
            "rev-list --left-right --count": ok("0\t1\n"),
            "diff --raw": ok(""),
            "diff --cached": ok(""),
            "ls-files": ok(""),
            "merge --ff-only": ok(""),
            "ls-tree": ok(""),
            "restore": ok(""),
            "hash-object": ok(""),
            "rev-parse --absolute-git-dir": ok(str(self.root / ".git")),
            "rev-parse HEAD": ok("a" * 40),
            "rev-parse refs/remotes/origin/main": ok("a" * 40),
        }
        ordered = dict(overrides)
        ordered.update((key, value) for key, value in defaults.items() if key not in ordered)
        return ordered

    def assert_no_undo(self, fake):
        """되돌리기에 쓰는 git 호출이 하나도 없었다."""
        for call in fake.calls:
            self.assertNotIn(call[0], ("restore", "hash-object", "ls-tree"), call)
            self.assertNotEqual(call[:2], ["diff", "--cached"], call)

    def test_the_fetch_uses_an_explicit_refspec_and_the_comparison_uses_full_ref_names(self):
        fake = FakeGit(self.replies())
        gitrepo.sync_latest(self.root, git=fake)
        fetch = next(call for call in fake.calls if call[0] == "fetch")
        self.assertEqual(fetch, ["fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main"])
        self.assertIn(["rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/main"], fake.calls)
        self.assertIn(["merge", "--ff-only", "--quiet", "refs/remotes/origin/main"], fake.calls)

    def test_the_check_for_my_files_asks_git_for_its_own_list_of_files_it_does_not_track(self):
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("M", "a.md")))}))
        gitrepo.sync_latest(self.root, git=fake)
        self.assertIn(["ls-files", "-z", "--others"], fake.calls, "새 파일과 무시한 파일을 모두 보려면 --exclude-standard 를 주지 않는다")
        self.assertIn(["diff", "--raw", "-z", "--no-abbrev", "--no-renames", "HEAD", "refs/remotes/origin/main"], fake.calls, "이름 바꾸기는 지움 + 새 파일로 본다")

    def test_a_merge_that_git_refused_is_never_undone_because_nothing_was_changed(self):
        """git 이 내 파일·변경을 지키려고 거절한 병합은 아무것도 바꾸지 않았다 — 되돌리기를 하면 오히려 내가 고친 것을 지운다(3차 검토 H1)."""
        for message, code in (
            ("error: The following untracked working tree files would be overwritten by merge:\n\tnotes.md\nPlease move or remove them before you merge.\nAborting", "PAGES_LOCAL_FILE_IN_THE_WAY"),
            ("error: Updating the following directories would lose untracked files in them:\n\tdocs\n\nAborting", "PAGES_LOCAL_FILE_IN_THE_WAY"),
            ("error: Your local changes to the following files would be overwritten by merge:\n\tREADME.md\nPlease commit your changes or stash them before you merge.", "PAGES_LOCAL_REPO_DIRTY"),
            ("error: Entry 'a.md' would be overwritten by merge. Cannot merge.", "PAGES_LOCAL_REPO_DIRTY"),
            ("error: Entry 'a.md' not uptodate. Cannot merge.", "PAGES_LOCAL_REPO_DIRTY"),
            ("fatal: Not possible to fast-forward, aborting.", "PAGES_LOCAL_REPO_DIVERGED"),
            ("hint: Diverging branches can't be fast-forwarded, you need to either:", "PAGES_LOCAL_REPO_DIVERGED"),
        ):
            with self.subTest(code=code, message=message[:50]):
                fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("M", "a.md"), ("A", "notes.md"))), "merge --ff-only": fail(message)}))
                self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, code)
                self.assert_no_undo(fake)

    def test_a_merge_refused_for_my_untracked_files_names_them_and_is_not_the_dirty_error(self):
        message = "error: The following untracked working tree files would be overwritten by merge:\n\tnotes.md\n\tposts/a.md\nPlease move or remove them before you merge.\nAborting"
        error = code_of(gitrepo.sync_latest, self.root, git=FakeGit(self.replies(**{"merge --ff-only": fail(message)})))
        self.assertEqual(error.code, "PAGES_LOCAL_FILE_IN_THE_WAY")
        self.assertEqual(error.slots["파일"], "notes.md, posts/a.md")
        self.assertIn("「notes.md, posts/a.md」", error.rendered().message)

    def test_a_merge_refused_because_a_folder_of_mine_would_lose_files_is_the_same_error(self):
        message = "error: Updating the following directories would lose untracked files in them:\n\tdocs\n\nAborting"
        error = code_of(gitrepo.sync_latest, self.root, git=FakeGit(self.replies(**{"merge --ff-only": fail(message)})))
        self.assertEqual((error.code, error.slots["파일"]), ("PAGES_LOCAL_FILE_IN_THE_WAY", "docs"))

    def test_a_merge_that_stops_in_the_middle_is_a_file_in_use_error_and_only_what_the_merge_wrote_is_undone(self):
        (self.root / "a.md").write_text("병합이 쓴 내용", encoding="utf-8")              # 추적 중인 파일 — 내용이 원격과 같으면(병합이 쓴 것) HEAD 내용으로 되돌린다(지우지는 않는다)
        (self.root / "new.md").write_text("병합이 만든 파일", encoding="utf-8")         # 병합이 이미 써 둔 새 파일(원격 내용과 같다) — 치운다
        (self.root / "kept.md").write_text("내 파일", encoding="utf-8")                  # 내용이 원격과 다른 같은 이름의 파일 — 내 것이니 그대로
        (self.root / "mine.md").write_text("내가 고친 추적 파일", encoding="utf-8")       # 내용이 HEAD 와도 원격과도 다른 추적 파일 — 내가 고친 것이니 그대로
        changes = raw(("M", "a.md", "1" * 40, "N1"), ("M", "sub/z.md", "1" * 40, "N2"), ("A", "new.md", "0" * 40, "N3"), ("A", "kept.md", "0" * 40, "N4"),
                      ("D", "gone.md", "O5", "0" * 40), ("M", "mine.md", "1" * 40, "N6"))
        fake = FakeGit(self.replies(**{
            "diff --raw": ok(changes),
            "merge --ff-only": fail("error: unable to unlink old 'sub/z.md': Permission denied\nfatal: Could not reset index file to revision"),
            "diff --cached": ok(raw(("M", "a.md"), ("D", "gone.md"))),                        # 병합이 색인을 바꿔 둔 곳
            "hash-object": ok("N1\nN3\nMINE\nMINE2\n"),                                        # a.md·new.md·kept.md·mine.md 순서
        }))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.code, "FILE_IN_USE")
        self.assertIn(str(self.root), error.slots["경로"])
        self.assertEqual(fake.inputs[[call[0] for call in fake.calls].index("hash-object")], b"a.md\nnew.md\nkept.md\nmine.md\n")
        self.assertIn(["diff", "--raw", "-z", "--no-abbrev", "--no-renames", "HEAD", "refs/remotes/origin/main"], fake.calls, "받을 파일은 이름 바꾸기를 따로 보지 않고 전체 번호로 읽는다")
        self.assertIn(["diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames", "HEAD"], fake.calls, "색인 차이도 같은 방식으로")
        self.assertIn(["restore", "--source=HEAD", "--staged", "--", "a.md", "gone.md"], fake.calls)
        self.assertIn(["restore", "--source=HEAD", "--staged", "--worktree", "--", "a.md", "gone.md"], fake.calls, "병합이 쓴 a.md 와 지워진 gone.md 만 되돌린다(색인 항목도 함께)")
        self.assertFalse((self.root / "new.md").exists(), "병합이 만든(원격과 똑같은) 파일은 치운다")
        self.assertTrue((self.root / "a.md").exists(), "추적 중인 파일은 지우지 않는다")
        self.assertEqual((self.root / "kept.md").read_text(encoding="utf-8"), "내 파일", "내용이 다른 같은 이름의 파일은 지우지 않는다")
        self.assertEqual((self.root / "mine.md").read_text(encoding="utf-8"), "내가 고친 추적 파일")
        for call in fake.calls:
            if call[0] == "restore":
                self.assertNotIn("mine.md", call, "내가 고친 파일은 되돌리지 않는다")
                self.assertNotIn("kept.md", call)

    def test_a_failing_undo_does_not_hide_the_original_error(self):
        fake = FakeGit(self.replies(**{
            "diff --raw": ok(raw(("M", "a.md"))),
            "merge --ff-only": fail("error: unable to unlink old 'a.md': Permission denied"),
            "diff --cached": lambda args: (_ for _ in ()).throw(RuntimeError("복구 도중 문제")),
        }))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")

    def test_a_merge_cut_off_by_the_time_limit_is_undone_and_the_lock_it_left_is_removed(self):
        gitdir = self.root / ".git"
        gitdir.mkdir()
        lock = gitdir / "index.lock"
        lock.write_text("", encoding="utf-8")

        def timed_out(args):
            raise AppError("NETWORK_TIMEOUT", detail="git merge 가 90초 안에 끝나지 않았다")

        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("M", "a.md"))), "diff --cached": ok(raw(("M", "a.md"))), "merge --ff-only": timed_out}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "NETWORK_TIMEOUT")
        self.assertFalse(lock.exists(), "끈 git 이 남긴 잠금이 남아 있다 — 다음 시도가 막힌다")
        self.assertIn(["restore", "--source=HEAD", "--staged", "--", "a.md"], fake.calls)

    def test_an_old_lock_is_left_alone_because_it_may_belong_to_another_program(self):
        gitdir = self.root / ".git"
        gitdir.mkdir()
        lock = gitdir / "index.lock"
        lock.write_text("", encoding="utf-8")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("M", "a.md"))), "merge --ff-only": lambda args: (_ for _ in ()).throw(AppError("NETWORK_TIMEOUT"))}))
        code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertTrue(lock.exists())

    def test_any_other_merge_failure_is_the_catch_all_with_the_cause(self):
        fake = FakeGit(self.replies(**{"merge --ff-only": fail("fatal: something nobody expected happened")}))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.code, UNEXPECTED)
        self.assertIn("nobody expected", error.detail)

    def test_a_head_that_is_not_origin_main_after_the_merge_is_an_error_not_a_success(self):
        fake = FakeGit(self.replies(**{"rev-parse refs/remotes/origin/main": ok("b" * 40)}))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.code, UNEXPECTED)
        self.assertIn("원격 main", error.detail)

    def test_my_untracked_or_ignored_file_in_the_way_stops_the_merge_before_it_starts(self):
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "notes.md"), ("M", "posts/known.md"), ("A", "posts/new.md"))), "ls-files": ok("notes.md\0other.txt\0")}))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.code, "PAGES_LOCAL_FILE_IN_THE_WAY")
        self.assertEqual(error.slots["파일"], "notes.md")
        self.assertNotIn("known.md", error.detail)
        self.assertFalse(any(call[0] == "merge" for call in fake.calls), "겹치면 병합을 시도하지 않는다")

    def test_a_file_the_remote_deletes_is_not_a_file_of_mine_in_the_way(self):
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("D", "gone.md"))), "ls-files": ok("gone.md\0")}))
        self.assertEqual(gitrepo.sync_latest(self.root, git=fake).head, "a" * 40)

    def test_more_than_five_names_are_shortened(self):
        names = [f"f{i}.md" for i in range(7)]
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(*[("A", name) for name in names])), "ls-files": ok("\0".join(names) + "\0")}))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.slots["파일"], "f0.md, f1.md, f2.md, f3.md, f4.md 외 2개")

    def test_tracked_files_the_bot_changed_are_never_mistaken_for_my_files(self):
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("M", "README.md"), ("M", "기록/이력 파일.json"))), "ls-files": ok("other.txt\0")}))
        self.assertEqual(gitrepo.sync_latest(self.root, git=fake).head, "a" * 40)

    def test_files_the_merge_will_create_that_do_not_exist_locally_are_fine(self):
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "posts/new.md"))), "ls-files": ok("README.md\0")}))
        self.assertEqual(gitrepo.sync_latest(self.root, git=fake).head, "a" * 40)

    def test_a_failing_file_list_is_reported_not_ignored(self):
        fake = FakeGit(self.replies(**{"diff --raw": fail("fatal: bad revision")}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, UNEXPECTED)
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("M", "a.md"))), "ls-files": fail("fatal: broken index")}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, UNEXPECTED)

    def test_unsaved_changes_are_refused_with_the_names_of_the_files(self):
        listing = " M a.md\0A  b.md\0R  new.md\0ab cd.md\0 D gone.md\0"
        error = code_of(gitrepo.inspect_repo, self.root, git=FakeGit(self.replies(**{"status --porcelain": ok(listing)})))
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_DIRTY")
        self.assertIn("바뀐 파일 4개", error.detail)
        for name in ("a.md", "b.md", "new.md", "gone.md"):
            self.assertIn(name, error.detail)
        self.assertNotIn("cd.md", error.detail, "이름을 바꾼 항목의 옛 이름(공백이 든 이름도)은 따로 세지 않는다")
        many = " M " + "x.md\0 M ".join(f"f{index}" for index in range(7)) + "x.md\0"
        shown = code_of(gitrepo.inspect_repo, self.root, git=FakeGit(self.replies(**{"status --porcelain": ok(many)}))).detail
        self.assertIn("외 2개", shown)
        self.assertIn("f4x.md", shown)
        self.assertNotIn("f5x.md", shown, "이름은 다섯 개까지만 보인다")
        odd = code_of(gitrepo.inspect_repo, self.root, git=FakeGit(self.replies(**{"status --porcelain": ok("weird-output")})))
        self.assertEqual(odd.code, "PAGES_LOCAL_REPO_DIRTY", "이름으로 읽히지 않아도 비어 있지 않으면 변경이 있는 것이다")

    def test_a_failing_status_is_an_error_not_a_clean_folder(self):
        error = code_of(gitrepo.inspect_repo, self.root, git=FakeGit(self.replies(**{"status --porcelain": fail("fatal: not a git repository")})))
        self.assertNotEqual(error.code, "PAGES_LOCAL_REPO_DIRTY")

    def test_up_to_date_does_no_merge_and_still_checks_the_head(self):
        fake = FakeGit(self.replies(**{"rev-list --left-right --count": ok("0\t0\n")}))
        gitrepo.sync_latest(self.root, git=fake)
        self.assertFalse(any(call[0] in ("merge", "diff", "ls-files", "ls-tree", "restore") for call in fake.calls))
        bad = FakeGit(self.replies(**{"rev-list --left-right --count": ok("0\t0\n"), "rev-parse refs/remotes/origin/main": ok("c" * 40)}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=bad).code, UNEXPECTED)

    # ---- 되돌릴 때 쓰는 이름은 원격이 정한 것 — 저장소 밖을 건드리지 못한다(3차 검토 M1) ------------------------------------------
    def test_names_that_could_leave_the_repository_are_never_trusted(self):
        for name, ok_ in (
            ("README.md", True), ("posts/a.md", True), ("기록/이력 파일.json", True), ("[x].md", True), (".github/workflows/ci.yml", True), ("a b/c.md", True), ("a.b.c", True),
            ("", False), ("..\\victim.txt", False), ("../victim.txt", False), ("a/../../victim.txt", False), ("a/./b.md", False), ("/etc/passwd", False), ("C:/Windows/x.txt", False),
            ("C:x.txt", False), ("a\\b.md", False), (".git/config", False), ("sub/.git/hooks/pre-commit", False), (".GIT/config", False), ("a//b.md", False), ("a/", False),
            ("a\nb.md", False), ("a\rb.md", False), ("a\0b.md", False), ("깨진\ufffd이름.md", False),
        ):
            with self.subTest(name=name):
                self.assertEqual(gitrepo._safe_name(name), ok_)

    def test_a_folder_that_is_a_link_to_somewhere_else_is_not_inside_the_repository(self):
        outside = self.base / "outside"
        outside.mkdir()
        try:
            os.symlink(outside, self.root / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        (self.root / "real").mkdir()
        self.assertFalse(gitrepo._inside(self.root, "link/x.md"))
        self.assertTrue(gitrepo._inside(self.root, "real/x.md"))
        self.assertTrue(gitrepo._inside(self.root, "x.md"))

    def test_a_link_to_a_sibling_folder_whose_name_starts_like_the_repository_is_not_inside(self):
        sibling = self.base / "repo-extra"
        sibling.mkdir()
        link = self.root / "link"
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(sibling)], capture_output=True)
            if made.returncode != 0:
                self.skipTest("이 환경에서는 연결 폴더(junction)를 만들 수 없다")
        else:
            try:
                os.symlink(sibling, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        self.addCleanup(lambda: os.rmdir(link) if os.name == "nt" else os.unlink(link))
        self.assertFalse(gitrepo._inside(self.root, "link/x.md"), "이름이 저장소 이름으로 시작하는 형제 폴더는 저장소 안이 아니다")

    def test_the_undo_never_touches_a_file_outside_the_repository_even_if_the_remote_asks(self):
        victim = self.base / "victim.txt"
        victim.write_text("남의 파일", encoding="utf-8")
        (self.root / "link").mkdir()
        (self.root / ".git" / "hooks").mkdir(parents=True)
        hook = self.root / ".git" / "hooks" / "post-merge"
        hook.write_text("#!/bin/sh\n", encoding="utf-8")
        changes = raw(("A", "../victim.txt", "0" * 40, "N1"), ("A", "..\\victim.txt", "0" * 40, "N1"), ("M", "link/../../victim.txt", "1" * 40, "N1"), ("A", ".git/hooks/post-merge", "0" * 40, "N1"))
        holder = []

        def same_hash_for_every_file(args):
            return ok("N1\n" * len(holder[0].inputs[-1].decode("utf-8").split()))      # 읽을 수 있는 파일마다 '원격과 같다' 고 답한다 — 이름 검사가 막지 않으면 지워진다

        fake = FakeGit(self.replies(**{"diff --raw": ok(changes), "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied"), "hash-object": same_hash_for_every_file}))
        holder.append(fake)
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        self.assertEqual(victim.read_text(encoding="utf-8"), "남의 파일")
        self.assertTrue(hook.exists(), ".git 안의 파일은 건드리지 않는다")
        self.assertFalse(any(call[0] == "restore" and any("victim" in part or ".git" in part for part in call) for call in fake.calls))

    def test_a_folder_inside_the_repository_that_is_a_link_to_the_outside_is_never_followed_by_the_undo(self):
        outside = self.base / "outside"
        outside.mkdir()
        victim = outside / "victim.txt"
        victim.write_text("남의 파일", encoding="utf-8")
        try:
            os.symlink(outside, self.root / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        holder = []

        def same_hash(args):
            return ok("N1\n" * len(holder[0].inputs[-1].decode("utf-8").split()))

        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "link/victim.txt", "0" * 40, "N1"))), "hash-object": same_hash,
                                       "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        holder.append(fake)
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        self.assertEqual(victim.read_text(encoding="utf-8"), "남의 파일", "링크 너머의 파일이 지워졌다")

    def test_staged_files_that_are_not_part_of_the_merge_are_left_alone_by_the_undo(self):
        fake = FakeGit(self.replies(**{
            "diff --raw": ok(raw(("M", "a.md"))),
            "diff --cached": ok(raw(("M", "a.md"), ("M", "my_staged.md"))),                # 내가 미리 올려 둔(스테이징한) 다른 파일
            "merge --ff-only": fail("error: unable to unlink old 'a.md': Permission denied"),
        }))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        staged_calls = [call for call in fake.calls if call[:4] == ["restore", "--source=HEAD", "--staged", "--"]]
        self.assertEqual(staged_calls, [["restore", "--source=HEAD", "--staged", "--", "a.md"]], "받을 파일의 색인 항목만 되돌린다")

    def test_raw_diff_output_is_read_into_changes(self):
        text = raw(("A", "new.md"), ("M", "a b.md", "1" * 40, "2" * 40), ("D", "gone.md"), ("T", "link.md")) + ":160000 160000 " + "3" * 40 + " " + "4" * 40 + " M\0sub\0"
        changes = gitrepo._parse_raw(text)
        self.assertEqual([(c.status, c.path) for c in changes], [("A", "new.md"), ("M", "a b.md"), ("D", "gone.md"), ("T", "link.md"), ("M", "sub")])
        self.assertEqual((changes[1].old_mode, changes[1].new_mode, changes[1].old, changes[1].new), ("100644", "100644", "1" * 40, "2" * 40))
        self.assertEqual((changes[0].old_mode, changes[0].new_mode), ("000000", "100644"))
        self.assertEqual(gitrepo._parse_raw(""), [])
        self.assertEqual(gitrepo._parse_raw("무슨 말인지 모를 출력\0"), [])
        self.assertEqual(gitrepo._parse_raw(":100644 100644 a b M\0"), [], "경로가 없는 줄은 건너뛴다")
        colon = gitrepo._parse_raw(raw(("M", ":weird.md"), ("A", ":100644 100644 a b M"), ("D", ":also.md"), ("A", "next.md")))
        self.assertEqual([(c.status, c.path) for c in colon], [("M", ":weird.md"), ("A", ":100644 100644 a b M"), ("D", ":also.md"), ("A", "next.md")],
                         "`:` 로 시작하는(머리글처럼 생긴) 파일 이름도 이름으로 읽고 다음 항목을 삼키지 않는다")

    def test_many_files_are_hashed_and_restored_in_chunks(self):
        names = [f"f{index:03d}.md" for index in range(650)]
        for name in names:
            (self.root / name).write_text("병합이 쓴 내용", encoding="utf-8")
        changes = raw(*[("M", name, "1" * 40, "N") for name in names])
        holder = []

        def hashes(args):
            return ok("N\n" * len(holder[0].inputs[-1].decode("utf-8").split()))

        fake = FakeGit(self.replies(**{"diff --raw": ok(changes), "diff --cached": ok(changes), "hash-object": hashes,
                                       "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        holder.append(fake)
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        hash_inputs = [data for call, data in zip(fake.calls, fake.inputs) if call[0] == "hash-object"]
        self.assertEqual([len(data.decode("utf-8").split()) for data in hash_inputs], [500, 150], "해시는 500개씩 나눠서")
        for prefix in (["restore", "--source=HEAD", "--staged", "--worktree", "--"], ["restore", "--source=HEAD", "--staged", "--"]):
            calls = [call for call in fake.calls if call[:len(prefix)] == prefix]
            self.assertEqual([len(call) - len(prefix) for call in calls], [100] * 6 + [50], "명령줄이 너무 길어지지 않게 100개씩")
            self.assertEqual(sorted(name for call in calls for name in call[len(prefix):]), names)

    def test_a_hash_list_that_does_not_line_up_is_not_trusted_but_each_name_is_asked_again_alone(self):
        (self.root / "a.md").write_text("x", encoding="utf-8")
        (self.root / "new.md").write_text("y", encoding="utf-8")
        changes = raw(("M", "a.md", "1" * 40, "N1"), ("A", "new.md", "0" * 40, "N3"))
        holder = []

        def hashes(args):
            names = holder[0].inputs[-1].decode("utf-8").split()
            if len(names) == 2:
                return ok("N3\n")                                                      # 파일은 둘인데 줄이 하나 모자란다(그 한 줄은 둘째 파일의 것) — 위치대로 첫 파일에 붙이면 안 된다
            return ok("N1\n") if names == ["a.md"] else fail("error: cannot open 'new.md'")      # 하나씩 다시: a.md 는 읽히고 new.md 는 (다른 프로그램이 독점으로 열어) 못 읽는다

        fake = FakeGit(self.replies(**{"diff --raw": ok(changes), "hash-object": hashes, "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        holder.append(fake)
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.code, "FILE_IN_USE")
        self.assertTrue((self.root / "new.md").exists(), "읽지 못한 파일은 지우지 않는다")
        self.assertIn(["restore", "--source=HEAD", "--staged", "--worktree", "--", "a.md"], fake.calls, "하나씩 읽은 a.md 는 병합이 쓴 것으로 확인돼 되돌린다")
        self.assertIn("new.md", error.detail, "되돌리지 못하고 남긴 새 파일은 이름으로 알린다")

    def test_files_whose_content_cannot_be_read_at_all_are_left_alone_and_named(self):
        (self.root / "a.md").write_text("x", encoding="utf-8")
        (self.root / "new.md").write_text("y", encoding="utf-8")
        changes = raw(("M", "a.md", "1" * 40, "N1"), ("A", "new.md", "0" * 40, "N3"))
        fake = FakeGit(self.replies(**{"diff --raw": ok(changes), "hash-object": fail("error: cannot open"), "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertTrue((self.root / "new.md").exists())
        self.assertFalse(any(call[:5] == ["restore", "--source=HEAD", "--staged", "--worktree", "--"] for call in fake.calls))
        self.assertIn("new.md", error.detail)

    def test_a_merge_that_had_already_finished_when_the_time_ran_out_is_a_success_and_nothing_is_undone(self):
        (self.root / "new.md").write_text("받은 새 글", encoding="utf-8")
        state = {"merged": False}

        def merge(args):
            state["merged"] = True
            raise AppError("NETWORK_TIMEOUT", detail="git merge 가 90초 안에 끝나지 않았다")              # 병합은 끝났는데 훅이 늦어 시간 초과

        def head(args):
            return ok(("b" if state["merged"] else "a") * 40 + "\n")

        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "new.md", "0" * 40, "N3"))), "merge --ff-only": merge, "rev-parse HEAD": head,
                                       "rev-parse refs/remotes/origin/main": ok("b" * 40), "hash-object": ok("N3\n")}))
        gitrepo.sync_latest(self.root, git=fake)
        self.assertTrue((self.root / "new.md").exists(), "이미 받아 끝난 새 파일을 지웠다")
        self.assertFalse(any(call[0] in ("restore", "hash-object") for call in fake.calls))

    def test_a_merge_that_timed_out_before_moving_the_head_is_undone_as_before(self):
        (self.root / "new.md").write_text("병합이 만든 파일", encoding="utf-8")
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "new.md", "0" * 40, "N3"))), "hash-object": ok("N3\n"),
                                       "merge --ff-only": lambda args: (_ for _ in ()).throw(AppError("NETWORK_TIMEOUT", detail="git merge 가 90초 안에 끝나지 않았다"))}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "NETWORK_TIMEOUT")
        self.assertFalse((self.root / "new.md").exists(), "HEAD 가 그대로면 병합이 쓰다 만 것이니 병합이 만든 파일을 치운다")

    def test_a_failed_merge_whose_head_has_moved_is_not_undone(self):
        (self.root / "new.md").write_text("받은 새 글", encoding="utf-8")
        state = {"merged": False}

        def merge(args):
            state["merged"] = True
            return fail("error: unable to unlink old 'x': Permission denied")

        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "new.md", "0" * 40, "N3"))), "merge --ff-only": merge, "hash-object": ok("N3\n"),
                                       "rev-parse HEAD": lambda args: ok(("b" if state["merged"] else "a") * 40 + "\n")}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        self.assertTrue((self.root / "new.md").exists())
        self.assertFalse(any(call[0] in ("restore", "hash-object") for call in fake.calls))

    def test_files_that_are_still_different_after_the_undo_are_named_in_the_error(self):
        state = {"merge": False}

        def merge(args):
            state["merge"] = True
            return fail("error: unable to unlink old 'x': Permission denied")

        status = lambda args: ok(" M half.bin\0 M other.md\0" if state["merge"] else "")           # 쓰다 만 파일은 HEAD 와도 원격과도 달라 되돌리지 못한다
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("M", "half.bin", "1" * 40, "N1"))), "merge --ff-only": merge, "status --porcelain": status, "hash-object": ok("HALF\n")}))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.code, "FILE_IN_USE")
        self.assertIn("받다가 멈춘 뒤에도 병합 전과 다른 파일 2개", error.detail)
        self.assertIn("half.bin", error.detail)
        self.assertIn("other.md", error.detail)

    def test_the_names_left_behind_are_listed_once_each_and_in_order(self):
        (self.root / "dup.md").write_text("받은 새 글", encoding="utf-8")
        state = {"merge": False}

        def merge(args):
            state["merge"] = True
            return fail("error: unable to unlink old 'x': Permission denied")

        real = Path.unlink

        def unlink(self_, missing_ok=False):
            if self_.name == "dup.md":
                raise PermissionError(13, "Permission denied")                      # 못 지운 새 파일이 아래 상태 목록에도 나온다
            return real(self_, missing_ok=missing_ok)

        status = lambda args: ok(" M b.md\0 M dup.md\0 M a.md\0" if state["merge"] else "")
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "dup.md", "0" * 40, "N3"))), "hash-object": ok("N3\n"), "merge --ff-only": merge, "status --porcelain": status}))
        with mock.patch.object(Path, "unlink", unlink):
            error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertIn("병합 전과 다른 파일 3개: a.md, b.md, dup.md", error.detail)

    def test_a_timeout_error_also_names_the_files_left_behind(self):
        state = {"merge": False}

        def merge(args):
            state["merge"] = True
            raise AppError("NETWORK_TIMEOUT", detail="git merge 가 90초 안에 끝나지 않았다")

        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("M", "half.bin", "1" * 40, "N1"))), "merge --ff-only": merge, "hash-object": ok("HALF\n"),
                                       "status --porcelain": lambda args: ok(" M half.bin\0" if state["merge"] else "")}))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.code, "NETWORK_TIMEOUT")
        self.assertIn("half.bin", error.detail)
        self.assertIn("90초", error.detail, "원래 세부는 그대로 두고 덧붙인다")

    def test_one_file_that_cannot_be_deleted_does_not_stop_the_rest_of_the_undo(self):
        for name in ("new1.md", "new2.md", "a.md"):
            (self.root / name).write_text("병합이 쓴 내용", encoding="utf-8")
        changes = raw(("A", "new1.md", "0" * 40, "N1"), ("A", "new2.md", "0" * 40, "N2"), ("M", "a.md", "1" * 40, "N3"))
        fake = FakeGit(self.replies(**{"diff --raw": ok(changes), "hash-object": ok("N1\nN2\nN3\n"), "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        real = Path.unlink

        def unlink(self_, missing_ok=False):
            if self_.name == "new1.md":
                raise PermissionError(13, "Permission denied")                      # 백신·색인기가 잠깐 쥐고 있는 파일
            return real(self_, missing_ok=missing_ok)

        with mock.patch.object(Path, "unlink", unlink):
            error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertTrue((self.root / "new1.md").exists())
        self.assertFalse((self.root / "new2.md").exists(), "앞의 파일 하나가 안 지워져도 나머지는 계속 치운다")
        self.assertIn(["restore", "--source=HEAD", "--staged", "--worktree", "--", "a.md"], fake.calls, "복원도 계속한다")
        self.assertIn("new1.md", error.detail)

    def test_a_restore_that_fails_for_a_group_is_retried_one_file_at_a_time(self):
        for name in ("a.md", "b.md"):
            (self.root / name).write_text("병합이 쓴 내용", encoding="utf-8")
        changes = raw(("M", "a.md", "1" * 40, "N1"), ("M", "b.md", "1" * 40, "N2"))

        def restore(args):
            return ok("") if len(args) == 6 else fail("error: unable to restore")      # 둘을 한꺼번에 하면 실패, 하나씩은 성공

        fake = FakeGit(self.replies(**{"diff --raw": ok(changes), "hash-object": ok("N1\nN2\n"), "restore --source=HEAD --staged --worktree": restore,
                                       "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        restores = [call for call in fake.calls if call[:5] == ["restore", "--source=HEAD", "--staged", "--worktree", "--"]]
        self.assertEqual(restores, [["restore", "--source=HEAD", "--staged", "--worktree", "--", "a.md", "b.md"], ["restore", "--source=HEAD", "--staged", "--worktree", "--", "a.md"],
                                    ["restore", "--source=HEAD", "--staged", "--worktree", "--", "b.md"]])

    def test_a_timeout_after_the_head_moved_to_something_other_than_the_remote_main_is_still_an_error(self):
        state = {"merged": False}

        def merge(args):
            state["merged"] = True
            raise AppError("NETWORK_TIMEOUT", detail="git merge 가 90초 안에 끝나지 않았다")

        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "new.md", "0" * 40, "N3"))), "merge --ff-only": merge,
                                       "rev-parse HEAD": lambda args: ok(("c" if state["merged"] else "a") * 40 + "\n"), "rev-parse refs/remotes/origin/main": ok("b" * 40)}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "NETWORK_TIMEOUT")

    def test_the_names_in_the_unsaved_changes_error_hide_secrets_and_stay_short(self):
        key = "AI" + "za" + "A" * 35
        listing = f" M {key}.md\0 M " + "x" * 200 + ".md\0"
        error = code_of(gitrepo.inspect_repo, self.root, git=FakeGit(self.replies(**{"status --porcelain": ok(listing)})))
        self.assertNotIn(key, error.detail)
        self.assertIn("[가림:", error.detail)
        self.assertNotIn("x" * 81, error.detail)

    def test_a_new_file_that_has_already_disappeared_is_not_reported_as_left_behind(self):
        (self.root / "n.md").write_text("받은 새 글", encoding="utf-8")

        def hashes(args):
            (self.root / "n.md").unlink()                                 # 읽은 직후 이미 사라졌다(다른 이름으로 같은 파일을 가리키는 경우 등)
            return ok("N3\n")

        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("A", "n.md", "0" * 40, "N3"))), "hash-object": hashes,
                                       "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        error = code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertEqual(error.code, "FILE_IN_USE")
        self.assertNotIn("n.md", error.detail)

    def test_a_file_the_remote_deleted_that_is_still_here_is_not_restored_over_my_edit(self):
        (self.root / "gone.md").write_text("내가 고친 내용", encoding="utf-8")
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("D", "gone.md", "O5", "0" * 40))), "merge --ff-only": fail("error: unable to unlink old 'gone.md': Permission denied")}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        self.assertFalse(any(call[:5] == ["restore", "--source=HEAD", "--staged", "--worktree", "--"] for call in fake.calls), "아직 있는 파일은 HEAD 내용으로 덮어쓰지 않는다")
        self.assertEqual((self.root / "gone.md").read_text(encoding="utf-8"), "내가 고친 내용")

    def test_a_file_whose_kind_changed_is_restored_when_the_merge_wrote_it(self):
        (self.root / "link.md").write_text("병합이 쓴 내용", encoding="utf-8")
        fake = FakeGit(self.replies(**{"diff --raw": ok(raw(("T", "link.md", "1" * 40, "N7"))), "hash-object": ok("N7\n"),
                                       "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        self.assertIn(["restore", "--source=HEAD", "--staged", "--worktree", "--", "link.md"], fake.calls)

    def test_a_failed_git_dir_lookup_never_makes_the_app_delete_an_index_lock_in_its_own_folder(self):
        old = os.getcwd()
        os.chdir(self.base)
        self.addCleanup(os.chdir, old)
        lock = self.base / "index.lock"
        lock.write_text("", encoding="utf-8")
        fake = FakeGit(self.replies(**{"rev-parse --absolute-git-dir": fail("fatal: not a git repository")}))
        gitrepo._clear_stale_index_lock(fake, self.root)
        self.assertTrue(lock.exists(), "앱이 도는 폴더의 파일을 지웠다")

    def test_a_path_that_is_or_was_a_submodule_is_never_restored_by_the_undo(self):
        changes = (":160000 100644 " + "1" * 40 + " N1 T\0was_sub\0" + ":100644 160000 " + "1" * 40 + " N2 T\0became_sub\0")
        for name in ("was_sub", "became_sub"):
            (self.root / name).write_text("x", encoding="utf-8")
        fake = FakeGit(self.replies(**{"diff --raw": ok(changes), "hash-object": ok("N1\nN2\n"), "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied")}))
        self.assertEqual(code_of(gitrepo.sync_latest, self.root, git=fake).code, "FILE_IN_USE")
        self.assertFalse(any(call[0] in ("restore", "hash-object") for call in fake.calls), "하위 모듈이었거나 하위 모듈이 된 경로는 건드리지 않는다")

    def test_a_submodule_entry_is_never_restored_by_the_undo(self):
        fake = FakeGit(self.replies(**{
            "diff --raw": ok(":160000 160000 " + "3" * 40 + " " + "4" * 40 + " M\0sub\0"),
            "merge --ff-only": fail("error: unable to unlink old 'x': Permission denied"),
            "diff --cached": ok(":160000 160000 " + "3" * 40 + " " + "4" * 40 + " M\0sub\0"),
        }))
        code_of(gitrepo.sync_latest, self.root, git=fake)
        self.assertFalse(any(call[0] == "restore" for call in fake.calls))


if __name__ == "__main__":
    unittest.main()
