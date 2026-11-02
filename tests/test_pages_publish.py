"""Pages 발행 시험 — 연결한 chanceblog 저장소에 글을 쓰고 commit 하고 push 한다(진짜 git, 로컬 bare 저장소, 네트워크·시크릿 없음).

지키는 것(이 모듈은 실제 main 에 올라가므로 하나씩 일부러 어겨 보는 변이 점검으로도 확인한다):
  1) 글 검사: 경로 모양(경로 이탈·`..`·절대 경로·역슬래시)·머리말·키 모양 문자열이 있으면 아무것도 쓰지 않는다.
  2) commit_post: 글 파일 하나만 commit 하고(내 다른 파일은 그대로), 같은 주소(분야가 달라도 같은 날짜-언어-시각)의 글이 있으면 DUPLICATE_SLUG,
     실패하면 쓴 파일·스테이징·만든 폴더를 치운다. 내 훅·서명 설정에 걸리지 않는다. 한글·공백 분야 폴더, LF 줄바꿈(autocrlf=true 여도).
  3) push_commit: 올리지 않은 것이 '이 글 하나'일 때만 올리고(강제 push 없음), 봇이 먼저 올려 막히면 최신 위로 옮겨 다시(최대 3번),
     충돌(같은 이름)이면 되돌리고 DUPLICATE_SLUG, 이미 올라가 있으면 할 일 없이 성공(연결이 끊겼지만 실제로는 성공했던 경우 포함).
"""
import errno
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import gitrepo, pages  # noqa: E402
from chanceblog_desktop.publish.gitrepo import GitResult  # noqa: E402

LOCAL_ORIGIN = re.compile(r".*origin\.git/?$")
HAVE_GIT = bool(shutil.which("git"))
Post = namedtuple("Post", "path text")
KO_TEXT = (ROOT / "tests" / "fixtures" / "chance_post_ko.md").read_text(encoding="utf-8")
EN_TEXT = (ROOT / "tests" / "fixtures" / "chance_post_en.md").read_text(encoding="utf-8")
KO_PATH = "_posts/경제·일/2026-10-29-KR-101652.md"
EN_PATH = "_posts/Society & Policy/2026-10-28-EN-184844.md"


def git(cwd, *args):
    done = subprocess.run(["git", "-c", "core.longpaths=true", "-c", "core.quotePath=false", "-C", str(cwd), *args], capture_output=True)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr.decode('utf-8', 'replace')}")
    return done.stdout.decode("utf-8").strip()


def commit_file(repo, name, text, message="x"):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    git(repo, "add", "--", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)


def code_of(callable_, *args, **kwargs):
    with unittest.TestCase().assertRaises(AppError) as caught:
        callable_(*args, **kwargs)
    return caught.exception


def blob(repo, spec):
    done = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", spec], capture_output=True)
    return done.stdout.decode("utf-8") if done.returncode == 0 else None


class Spy:
    """진짜 git 을 부르되 호출을 기록하고, push 직전·직후에 끼어들 수 있다(봇이 먼저 올리는 경우·연결이 끊기는 경우)."""

    def __init__(self, before_push=(), lose_answer_after_push=0):
        self.calls = []
        self.before_push = list(before_push)
        self.lose_answer = lose_answer_after_push

    def __call__(self, cwd, args):
        self.calls.append(list(args))
        if args[0] == "push" and self.before_push:
            self.before_push.pop(0)()
        result = gitrepo.run_git(cwd, args)
        if args[0] == "push" and result.returncode == 0 and self.lose_answer:
            self.lose_answer -= 1
            return GitResult(128, "", "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': Connection reset by peer")
        return result

    def pushes(self):
        return [call for call in self.calls if call[0] == "push"]


class Flaky:
    """진짜 git 을 부르되 지정한 명령은 가짜로 실패시키거나(fail) 진짜로 한 뒤 시간 초과 예외를 던진다(then_raise) — 중간에 끊기는 경우를 만든다."""

    def __init__(self, fail=(), then_raise=()):
        self.fail, self.then_raise, self.calls = set(fail), set(then_raise), []

    def __call__(self, cwd, args):
        self.calls.append(list(args))
        if args[0] in self.fail:
            return GitResult(1, "", f"fatal: simulated failure of {args[0]}")
        result = gitrepo.run_git(cwd, args)
        if args[0] in self.then_raise:
            raise AppError("NETWORK_TIMEOUT", detail=f"git {args[0]} 가 끝나지 않았다")
        return result


@unittest.skipUnless(HAVE_GIT, "git 이 필요하다")
class PublishBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shared = tempfile.TemporaryDirectory()
        cls.addClassCleanup(shared.cleanup)
        cls.base = Path(shared.name) / "base"
        cls.base.mkdir()
        origin = cls.base / "origin.git"
        git(cls.base, "init", "-q", "--bare", str(origin))
        git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
        git(cls.base, "clone", "-q", str(origin), "work")
        work = cls.base / "work"
        git(work, "config", "core.autocrlf", "false")
        git(work, "checkout", "-q", "-B", "main")
        commit_file(work, "README.md", "블로그\n")
        commit_file(work, "_posts/2026-10-18-KR-225949.md", "---\nlayout: post\n---\n옛 글\n")
        commit_file(work, "_config.yml", 'url: "https://example.invalid"\nbaseurl: "/chanceblog"\npermalink: /posts/:year/:month/:day/:title/\n')
        git(work, "push", "-q", "-u", "origin", "main")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        shutil.copytree(self.base, self.tmp / "t")
        self.origin = self.tmp / "t" / "origin.git"
        self.work = self.tmp / "t" / "work"
        git(self.work, "remote", "set-url", "origin", str(self.origin))
        git(self.work, "config", "user.name", "운영자")
        git(self.work, "config", "user.email", "operator@example.com")
        git(self.work, "config", "commit.gpgsign", "false")
        self.ko = Post(KO_PATH, KO_TEXT)
        self.en = Post(EN_PATH, EN_TEXT)

    def bot_pushes(self, name="_posts/Bot/2026-10-30-KR-090000.md", text="봇 글\n"):
        other = self.tmp / "bot"
        if not other.exists():
            git(self.tmp, "clone", "-q", str(self.origin), "bot")
            git(other, "config", "core.autocrlf", "false")
        git(other, "pull", "-q", "--ff-only", "origin", "main")
        commit_file(other, name, text, "bot")
        git(other, "push", "-q", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def commit(self, post=None, **kwargs):
        return pages.commit_post(self.work, post or self.ko, expected_origin=LOCAL_ORIGIN, **kwargs)

    def push(self, post=None, **kwargs):
        return pages.push_commit(self.work, post or self.ko, expected_origin=LOCAL_ORIGIN, **kwargs)

    def head(self, repo=None):
        return git(repo or self.work, "rev-parse", "HEAD")

    def remote_main(self):
        return git(self.origin, "rev-parse", "main")

    def assert_untouched(self, head_before):
        """실패한 뒤 저장소가 처음과 같다: HEAD 그대로, 스테이징·수정 없음, 글 폴더·파일 없음."""
        self.assertEqual(self.head(), head_before)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertFalse((self.work / KO_PATH).exists())
        self.assertFalse((self.work / "_posts" / "경제·일").exists(), "우리가 만든 폴더는 치운다")


class CheckPostTest(unittest.TestCase):
    """글 검사는 저장소 없이 돈다."""

    def test_a_good_post_passes(self):
        pages.check_post(Post(KO_PATH, KO_TEXT))
        pages.check_post(Post(EN_PATH, EN_TEXT))

    def test_paths_that_could_leave_the_posts_folder_or_are_not_post_files_are_refused(self):
        bad = (
            "_posts/../README.md", "_posts/../2026-10-29-KR-101652.md", "_posts/./2026-10-29-KR-101652.md", "_posts/.../2026-10-29-KR-101652.md",
            "_posts/a/b/2026-10-29-KR-101652.md", "/_posts/a/2026-10-29-KR-101652.md", "C:/x/_posts/a/2026-10-29-KR-101652.md",
            "_posts\\a\\2026-10-29-KR-101652.md", "_posts/a\\b/2026-10-29-KR-101652.md", "posts/a/2026-10-29-KR-101652.md", "_drafts/a/2026-10-29-KR-101652.md",
            "_posts/a/2026-10-29-KR-101652.markdown", "_posts/a/2026-10-29-XX-101652.md", "_posts/a/2026-10-29-KR-1016.md", "_posts/a/26-10-29-KR-101652.md",
            "_posts/a/2026-10-29-KR-101652.md\n", "_posts/a:b/2026-10-29-KR-101652.md", "_posts/a /2026-10-29-KR-101652.md", "_posts/a./2026-10-29-KR-101652.md",
            "_posts//2026-10-29-KR-101652.md", "_posts/a/2026-10-29-KR-101652.md/", "", None, 5,
            "_posts/a\tb/2026-10-29-KR-101652.md", "_posts/a\x00b/2026-10-29-KR-101652.md", "_posts/a\x1fb/2026-10-29-KR-101652.md",
        )
        for path in bad:
            with self.subTest(path=path):
                self.assertEqual(code_of(pages.check_post, Post(path, KO_TEXT)).code, "CONTENT_INVALID")

    def test_empty_oversized_or_headerless_text_is_refused(self):
        for text in (None, "", "   \n", "머리말 없는 글\n", "x" * (pages.MAX_POST_BYTES + 1), KO_TEXT.replace("layout:", "layouts:"), 5):
            with self.subTest(text=str(text)[:20]):
                self.assertEqual(code_of(pages.check_post, Post(KO_PATH, text)).code, "CONTENT_INVALID")

    def test_a_post_with_a_good_header_but_too_big_a_body_is_refused_for_its_size(self):
        small = KO_TEXT + "x" * (pages.MAX_POST_BYTES - len(KO_TEXT.encode("utf-8")) - 10)
        pages.check_post(Post(KO_PATH, small))                                      # 상한 바로 아래는 통과
        error = code_of(pages.check_post, Post(KO_PATH, small + "x" * 20))        # 머리말은 멀쩡한데 커서 거절
        self.assertEqual((error.code, error.detail), ("CONTENT_INVALID", "너무 크다"))

    def test_the_size_limit_is_exactly_the_constant_counted_in_bytes_not_characters(self):
        exact = KO_TEXT + "x" * (pages.MAX_POST_BYTES - len(KO_TEXT.encode("utf-8")))
        self.assertEqual(len(exact.encode("utf-8")), pages.MAX_POST_BYTES)
        pages.check_post(Post(KO_PATH, exact))                                      # 딱 상한은 통과
        self.assertEqual(code_of(pages.check_post, Post(KO_PATH, exact + "x")).detail, "너무 크다", "1바이트만 넘어도 거절")
        wide = KO_TEXT + "가" * (pages.MAX_POST_BYTES // 3 + 1)                      # 글자 수로는 상한 아래지만 바이트로는 위
        self.assertLess(len(wide), pages.MAX_POST_BYTES)
        self.assertEqual(code_of(pages.check_post, Post(KO_PATH, wide)).detail, "너무 크다")

    def test_a_key_shaped_string_in_the_post_blocks_it_and_the_error_never_repeats_the_key(self):
        key = "AI" + "za" + "A" * 35
        error = code_of(pages.check_post, Post(KO_PATH, KO_TEXT + f"\n실수로 {key} 가 들어갔다\n"))
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
        self.assertNotIn(key, error.detail + error.log_line() + str(error))
        self.assertIn("Google API 키", error.detail)


class StricterCheckPostTest(unittest.TestCase):
    """독립 검증이 짚은 약한 곳 — 전각 숫자·불가능한 날짜·Windows 예약 이름·보이지 않는 글자·제어 문자·쪼갠 키."""

    def test_non_ascii_digits_impossible_dates_and_odd_folder_names_are_refused(self):
        odd_folders = ("con", "CON", "nul.txt", "Com1", "LPT9", "aux", "a" + chr(0xA0) + "b", "a" + chr(0x200B) + "b", "a" + chr(0x202E) + "b", "a" + chr(0x7F) + "b", "a" + chr(0x3000) + "b")
        paths = [f"_posts/{folder}/2026-10-29-KR-101652.md" for folder in odd_folders]
        paths += [
            "_posts/a/" + "".join(chr(0xFF10 + int(digit)) for digit in "2026") + "-10-29-KR-101652.md",          # 전각 숫자
            "_posts/a/2026-13-45-KR-101652.md", "_posts/a/0000-00-00-KR-101652.md", "_posts/a/2026-02-30-KR-101652.md",
            "_posts/a/2026-10-29-KR-240000.md", "_posts/a/2026-10-29-KR-106000.md", "_posts/a/2026-10-29-KR-101660.md",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(code_of(pages.check_post, Post(path, KO_TEXT)).code, "CONTENT_INVALID")
        pages.check_post(Post("_posts/컨/2026-10-29-KR-235959.md", KO_TEXT))                          # 정상 경계: 한글 폴더·23:59:59
        pages.check_post(Post("_posts/a b/2026-02-28-EN-000000.md", EN_TEXT))

    def test_control_characters_lone_surrogates_and_a_key_split_by_invisible_characters_are_refused(self):
        for bad in ("\r", "\x00", "\x1b", "\x7f", "\x0b"):
            with self.subTest(char=repr(bad)):
                self.assertEqual(code_of(pages.check_post, Post(KO_PATH, KO_TEXT + f"끝{bad}\n")).code, "CONTENT_INVALID")
        self.assertEqual(code_of(pages.check_post, Post(KO_PATH, KO_TEXT + chr(0xD800))).code, "CONTENT_INVALID")
        key = "AI" + "za" + "A" * 35
        for hider in (0x200B, 0x00AD, 0x2060):
            with self.subTest(hider=hex(hider)):
                text = KO_TEXT + "\n실수 " + key[:10] + chr(hider) + key[10:] + " 로\n"
                self.assertEqual(code_of(pages.check_post, Post(KO_PATH, text)).code, "SECRET_IN_TEXT_BLOCKED")

    def test_leading_dots_or_spaces_and_invisible_filler_characters_in_the_folder_are_refused(self):
        folders = (" a", ".a", "a ", "a.", chr(0x3164), "a" + chr(0x115F) + "b", "a" + chr(0x2800) + "b", "a" + chr(0xFE0F) + "b", "a" + chr(0x034F) + "b", "a" + chr(0x17B4) + "b")
        for folder in folders:
            with self.subTest(folder=repr(folder)):
                self.assertEqual(code_of(pages.check_post, Post(f"_posts/{folder}/2026-10-29-KR-101652.md", KO_TEXT)).code, "CONTENT_INVALID")

    def test_line_separators_c1_controls_and_noncharacters_in_the_text_are_refused(self):
        for bad in (0x0085, 0x009F, 0x2028, 0x2029, 0xFFFE, 0xFFFF):
            with self.subTest(char=hex(bad)):
                self.assertEqual(code_of(pages.check_post, Post(KO_PATH, KO_TEXT + f"끝{chr(bad)}\n")).code, "CONTENT_INVALID")


class CommitPostTest(PublishBase):
    def test_the_post_is_written_and_only_it_is_committed_with_the_base_and_message_recorded(self):
        before = self.head()
        (self.work / "내메모.txt").write_text("내 파일\n", encoding="utf-8")
        info = self.commit(title="오늘의 경제 글")
        self.assertEqual((info.path, info.base), (KO_PATH, before))
        self.assertEqual(info.commit, self.head())
        self.assertEqual(git(self.work, "rev-parse", "HEAD~1"), before)
        self.assertEqual((self.work / KO_PATH).read_bytes(), KO_TEXT.encode("utf-8"))
        self.assertEqual(git(self.work, "diff-tree", "-z", "--no-commit-id", "--name-status", "-r", "HEAD").split("\0")[:2], ["A", KO_PATH])
        self.assertIn("오늘의 경제 글", git(self.work, "log", "-1", "--format=%B"))
        self.assertEqual((self.work / "내메모.txt").read_text(encoding="utf-8"), "내 파일\n", "내 새 파일은 그대로, 커밋에도 안 들어간다")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all").splitlines(), ["?? 내메모.txt"])
        self.assertEqual(self.remote_main(), before, "commit 은 올리지 않는다")

    def test_a_folder_with_spaces_and_symbols_and_an_english_post_work_too(self):
        self.commit(self.en)
        self.assertEqual(blob(self.work, f"HEAD:{EN_PATH}"), EN_TEXT)

    def test_the_text_is_committed_with_lf_even_when_git_converts_line_endings(self):
        git(self.work, "config", "core.autocrlf", "true")
        self.commit()
        self.assertEqual(blob(self.work, f"HEAD:{KO_PATH}"), KO_TEXT)
        self.assertNotIn("\r", blob(self.work, f"HEAD:{KO_PATH}"))

    def test_the_message_defaults_to_the_file_name_and_cleans_a_messy_title(self):
        self.commit()
        self.assertIn("2026-10-29-KR-101652.md", git(self.work, "log", "-1", "--format=%s"))
        self.push()
        self.commit(self.en, title="  첫 줄\n\n둘째 줄  " + "길" * 200)
        subject = git(self.work, "log", "-1", "--format=%s")
        self.assertTrue(subject.startswith("글 올리기(데스크톱 앱): 첫 줄 둘째 줄 "))
        self.assertLessEqual(len(subject), 120)

    def test_a_same_named_post_in_any_category_is_a_duplicate_and_nothing_changes(self):
        commit_file(self.work, "_posts/다른 분야/2026-10-29-KR-101652.md", "---\nlayout: post\n---\n같은 시각의 다른 글\n")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        before = self.head()
        error = code_of(self.commit)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertEqual(self.head(), before)
        self.assertFalse((self.work / KO_PATH).exists())
        self.assertFalse((self.work / "_posts" / "경제·일").exists())

    def test_a_different_extension_with_the_same_name_also_counts_as_a_duplicate(self):
        commit_file(self.work, "_posts/2026-10-29-KR-101652.markdown", "---\nlayout: post\n---\n옛 글\n")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.assertEqual(code_of(self.commit).code, "DUPLICATE_SLUG")

    def test_the_same_post_written_twice_is_refused_with_a_code(self):
        self.commit()
        error = code_of(self.commit)
        # 올리지 않은 커밋이 이미 있어 최신 받기가 먼저 막을 수도 있다 — 어느 쪽이든 같은 글을 두 번 쓰지 않고 코드로 알린다
        self.assertIn(error.code, ("DUPLICATE_SLUG", "PAGES_LOCAL_REPO_DIVERGED"))
        self.assertEqual(git(self.work, "rev-list", "--count", "origin/main..HEAD"), "1")

    def test_a_post_that_is_already_published_with_the_same_content_is_a_duplicate_not_a_leftover_to_reuse(self):
        self.commit()
        self.push()
        head = self.head()
        error = code_of(self.commit)                          # 같은 경로·같은 내용이어도 git 이 이미 추적하는 글은 '지난번에 못 지운 내 파일' 이 아니다
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertEqual(self.head(), head)
        self.assertEqual(blob(self.work, f"HEAD:{KO_PATH}"), KO_TEXT)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")

    def test_a_bad_post_or_a_bad_repository_writes_nothing(self):
        head = self.head()
        for post in (Post("_posts/../x.md", KO_TEXT), Post(KO_PATH, "머리말 없음\n"), Post(KO_PATH, KO_TEXT + "AI" + "za" + "A" * 35)):
            with self.subTest(path=post.path):
                self.assertEqual(code_of(self.commit, post).code in ("CONTENT_INVALID", "SECRET_IN_TEXT_BLOCKED"), True)
        self.assert_untouched(head)
        (self.work / "README.md").write_text("고침\n", encoding="utf-8")
        self.assertEqual(code_of(self.commit).code, "PAGES_LOCAL_REPO_DIRTY")
        self.assertFalse((self.work / KO_PATH).exists(), "내가 고친 파일이 있으면 아무것도 쓰지 않는다")

    def test_a_new_bot_post_is_brought_in_first_and_the_commit_goes_on_top_of_it(self):
        bot = self.bot_pushes()
        info = self.commit()
        self.assertEqual(info.base, bot)
        self.assertTrue((self.work / "_posts" / "Bot" / "2026-10-30-KR-090000.md").is_file())

    def test_a_symlink_or_junction_inside_posts_that_points_outside_is_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        link = self.work / "_posts" / "경제·일"
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
            if made.returncode != 0:
                self.skipTest("이 환경에서는 연결 폴더(junction)를 만들 수 없다")
        else:
            try:
                os.symlink(outside, link, target_is_directory=True)
            except OSError:
                self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link) if os.name == "nt" else os.path.lexists(link) and os.unlink(link))
        error = code_of(self.commit)
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertEqual(list(outside.iterdir()), [], "밖에는 아무것도 쓰지 않는다")

    def test_a_missing_commit_author_is_reported_with_its_own_code_and_the_write_is_undone(self):
        git(self.work, "config", "--unset", "user.name")
        git(self.work, "config", "--unset", "user.email")
        git(self.work, "config", "user.useConfigOnly", "true")
        empty = self.tmp / "empty.gitconfig"
        empty.write_text("", encoding="utf-8")
        head = self.head()
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1"}):
            for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
                os.environ.pop(name, None)
            error = code_of(self.commit)
        self.assertEqual(error.code, "GIT_IDENTITY_MISSING")
        self.assert_untouched(head)

    def test_a_commit_that_somehow_contains_more_than_the_post_is_reported_and_left_alone(self):
        def lying_git(cwd, args):
            if args[0] == "diff-tree":
                return GitResult(0, "M\0README.md\0", "")
            return gitrepo.run_git(cwd, args)

        error = code_of(pages.commit_post, self.work, self.ko, git=lying_git, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        self.assertTrue((self.work / KO_PATH).is_file(), "이미 만든 커밋과 파일은 지우지 않고 사람이 보게 둔다")
        self.assertEqual(git(self.work, "rev-list", "--count", "origin/main..HEAD"), "1")

    def test_a_failing_step_after_the_file_was_written_undoes_everything(self):
        head = self.head()

        def failing_git(cwd, args):
            if args[0] == "add":
                return GitResult(128, "", "fatal: something broke")
            return gitrepo.run_git(cwd, args)

        error = code_of(pages.commit_post, self.work, self.ko, git=failing_git, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        self.assert_untouched(head)

    def test_an_interrupt_between_writing_and_committing_also_undoes_the_write(self):
        head = self.head()

        def interrupted_git(cwd, args):
            if "commit" in args:
                raise KeyboardInterrupt
            return gitrepo.run_git(cwd, args)

        with self.assertRaises(KeyboardInterrupt):
            pages.commit_post(self.work, self.ko, git=interrupted_git, expected_origin=LOCAL_ORIGIN)
        self.assert_untouched(head)

    def test_an_unwritable_place_is_a_file_error_with_the_path(self):
        head = self.head()
        with mock.patch("builtins.open", side_effect=PermissionError(13, "Permission denied")):
            error = code_of(self.commit)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertIn("2026-10-29-KR-101652.md", error.slots["경로"])
        self.assert_untouched(head)
        for number, winerror, expected in ((errno.ENOSPC, None, "DISK_FULL"), (errno.ENAMETOOLONG, None, "FILE_PATH_TOO_LONG"), (2, 206, "FILE_PATH_TOO_LONG")):
            problem = OSError(number, "x")
            problem.winerror = winerror
            with mock.patch("builtins.open", side_effect=problem):
                self.assertEqual(code_of(self.commit).code, expected)
            self.assert_untouched(head)

    def test_the_users_hooks_and_signing_settings_do_not_get_in_the_way(self):
        scratch = self.tmp / "scratch"
        git(self.tmp, "clone", "-q", str(self.origin), "scratch")
        markers = {name: self.tmp / f"ran-{name}" for name in ("pre-commit", "commit-msg", "pre-push")}
        for repo in (self.work, scratch):
            for name, marker in markers.items():
                hook = repo / ".git" / "hooks" / name
                hook.write_text(f'#!/bin/sh\ntouch "{marker.as_posix()}"\nexit 1\n', encoding="utf-8", newline="\n")      # 훅이 돌면 커밋·push 를 거부한다
                hook.chmod(0o755)
        for repo in (self.work, scratch):
            git(repo, "config", "commit.gpgsign", "true")
            git(repo, "config", "gpg.program", "no-such-gpg-program")
        git(scratch, "config", "user.name", "t")
        git(scratch, "config", "user.email", "t@example.com")
        control = subprocess.run(["git", "-C", str(scratch), "commit", "--allow-empty", "-q", "-m", "통제"], capture_output=True)
        if not markers["pre-commit"].exists() or control.returncode == 0:
            self.skipTest("이 git 은 훅·서명 설정을 이 모양으로 쓰지 않는다(시험이 의미 없다)")
        for marker in markers.values():
            if marker.exists():
                marker.unlink()
        self.commit()
        self.push()
        self.assertEqual([name for name, marker in markers.items() if marker.exists()], [], "앱이 사용자의 훅을 돌렸다")
        self.assertEqual(self.remote_main(), self.head())


class FailureHandlingTest(PublishBase):
    """독립 검증이 짚은 실패 처리 — 정리가 안 되거나 중간에 끊겨도 저장소가 막다른 길에 빠지지 않는다."""

    def test_a_category_folder_that_differs_only_in_letter_case_from_an_existing_one_is_refused_before_anything_is_written(self):
        self.bot_pushes(name="_posts/Society & Policy/2026-10-27-EN-000001.md", text="---\nlayout: post\n---\n앞선 글\n")
        error = code_of(self.commit, Post("_posts/society & policy/2026-10-28-EN-184844.md", EN_TEXT))
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertIn("Society & Policy", error.detail)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual([path.name for path in (self.work / "_posts").rglob("2026-10-28-EN-184844.md")], [], "글 파일이 만들어졌다")

    def test_a_key_shaped_commit_title_is_refused_before_anything_is_written(self):
        key = "AI" + "za" + "A" * 35
        error = code_of(self.commit, title=f"제목 {key}")
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
        self.assertNotIn(key, error.detail + str(error) + error.log_line())
        self.assertFalse((self.work / "_posts" / "경제·일").exists())

    def test_a_cleanup_that_cannot_unstage_still_leaves_no_staged_file(self):
        flaky = Flaky(fail=("commit", "reset"))
        head = self.head()
        code_of(self.commit, git=flaky)
        self.assertEqual(self.head(), head)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertFalse((self.work / KO_PATH).exists())
        self.assertIn(["rm", "--cached", "--quiet", "--ignore-unmatch", "--", KO_PATH], flaky.calls, "reset 이 안 먹으면 색인에서 직접 뺀다")

    def test_the_users_empty_category_folder_survives_a_failed_commit(self):
        folder = self.work / "_posts" / "경제·일"
        folder.mkdir(parents=True)                                                 # 사용자가 미리 만들어 둔 빈 폴더(git 은 빈 폴더를 추적하지 않는다)
        code_of(self.commit, git=Flaky(fail=("commit",)))
        self.assertTrue(folder.is_dir(), "원래 있던 폴더는 치우지 않는다")
        self.assertFalse((self.work / KO_PATH).exists())

    def test_a_file_the_user_stages_just_before_the_commit_is_not_swept_into_it(self):
        def stage_then_commit(cwd, args):
            if args[0] == "commit":
                (self.work / "내메모.txt").write_text("내 메모\n", encoding="utf-8", newline="\n")
                git(self.work, "add", "내메모.txt")                                  # 점검을 마친 뒤 사용자가 다른 파일을 스테이징했다
            return gitrepo.run_git(cwd, args)

        info = self.commit(git=stage_then_commit)
        self.assertEqual(git(self.work, "diff-tree", "-z", "--no-commit-id", "--name-status", "-r", "HEAD").split("\0")[:2], ["A", KO_PATH])
        self.assertEqual(info.commit, self.head())
        self.assertEqual(git(self.work, "diff", "--cached", "--name-only"), "내메모.txt", "사용자가 스테이징한 파일은 커밋에 들어가지 않고 그대로 남는다")

    def test_a_failure_after_the_commit_was_made_keeps_the_commit_and_the_file(self):
        state = {"committed": False}

        def fail_checks_after_commit(cwd, args):
            if state["committed"] and args[0] == "rev-parse":
                return GitResult(1, "", "fatal: simulated failure")
            result = gitrepo.run_git(cwd, args)
            if args[0] == "commit" and result.returncode == 0:
                state["committed"] = True
            return result

        base = self.head()
        code_of(self.commit, git=fail_checks_after_commit)
        self.assertTrue(state["committed"])
        self.assertTrue((self.work / KO_PATH).exists(), "만들어진 커밋의 글 파일을 지우면 안 된다")
        self.assertNotEqual(self.head(), base, "커밋은 만들어졌다")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")

    def test_the_commit_command_itself_skips_the_users_hooks_and_commits_only_the_post(self):
        flaky = Flaky()
        self.commit(git=flaky)
        commits = [call for call in flaky.calls if call[0] == "commit"]
        self.assertEqual(len(commits), 1)
        self.assertIn("--no-verify", commits[0], "러너 설정에만 기대지 않고 명령 자체도 훅을 건너뛴다")
        self.assertEqual(commits[0][-2:], ["--", KO_PATH], "그 파일만 commit 한다")
        self.assertIn("--only", commits[0])

    def test_a_file_that_appears_between_the_check_and_the_write_is_a_duplicate_and_is_not_overwritten(self):
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        other = self.work / KO_PATH
        other.write_text("---\nlayout: post\n---\n그사이 생긴 글\n", encoding="utf-8", newline="\n")
        with mock.patch.object(Path, "rglob", lambda self_, pattern: iter(())):                  # 같은 이름 검사가 못 보고 지나갔다
            error = code_of(self.commit)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertEqual(other.read_text(encoding="utf-8"), "---\nlayout: post\n---\n그사이 생긴 글\n", "남의 파일을 덮어쓰지 않는다")

    def test_a_hard_linked_file_with_the_same_content_is_not_taken_for_my_leftover(self):
        outside = self.tmp / "밖의 파일.md"
        outside.write_bytes(KO_TEXT.encode("utf-8"))
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        try:
            os.link(outside, self.work / KO_PATH)
        except (OSError, NotImplementedError):
            self.skipTest("이 환경에서는 하드 링크를 만들 수 없다")
        self.assertEqual(code_of(self.commit).code, "DUPLICATE_SLUG")
        self.assertEqual(outside.read_bytes(), KO_TEXT.encode("utf-8"))
        self.assertTrue((self.work / KO_PATH).exists(), "남의 파일은 건드리지 않는다")

    def test_a_symbolic_link_with_the_same_content_is_not_taken_for_my_leftover(self):
        outside = self.tmp / "밖의 파일.md"
        outside.write_bytes(KO_TEXT.encode("utf-8"))
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        try:
            os.symlink(outside, self.work / KO_PATH)
        except (OSError, NotImplementedError):
            self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        before = self.head()
        self.assertEqual(code_of(self.commit).code, "DUPLICATE_SLUG")
        self.assertEqual(self.head(), before)
        self.assertEqual(outside.read_bytes(), KO_TEXT.encode("utf-8"))

    def test_a_leftover_whose_name_differs_only_in_case_is_not_taken_for_mine(self):
        folder = self.work / "_posts" / "경제·일"
        folder.mkdir(parents=True)
        probe = folder / "Probe.tmp"
        probe.write_text("x", encoding="utf-8")
        case_insensitive = (folder / "probe.tmp").exists()
        probe.unlink()
        if not case_insensitive:
            self.skipTest("대소문자를 구분하는 파일 시스템에서는 이름이 다른 별개의 파일이다")
        lower = folder / "2026-10-29-kr-101652.md"
        lower.write_bytes(KO_TEXT.encode("utf-8"))
        self.assertEqual(code_of(self.commit).code, "DUPLICATE_SLUG")
        self.assertTrue(lower.exists(), "남의 파일은 지우지 않는다")

    def test_a_reused_leftover_file_is_not_deleted_when_this_try_fails_too(self):
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        (self.work / KO_PATH).write_bytes(KO_TEXT.encode("utf-8"))                              # 지난번에 못 지운 내 파일
        code_of(self.commit, git=Flaky(fail=("commit",)))
        self.assertTrue((self.work / KO_PATH).exists(), "이어 쓰던 내 파일을 이번 실패 때 지우지 않는다")
        self.assertEqual(git(self.work, "diff", "--cached", "--name-only"), "", "스테이징은 취소한다")

    def test_when_the_head_cannot_be_read_after_a_failure_nothing_is_cleaned_and_the_file_is_named(self):
        state = {"committed": False}

        def commit_times_out_and_head_is_unreadable(cwd, args):
            if state["committed"] and args[0] == "rev-parse":
                raise AppError("NETWORK_TIMEOUT", detail="git rev-parse 가 끝나지 않았다")
            result = gitrepo.run_git(cwd, args)
            if args[0] == "commit":
                state["committed"] = True
                raise AppError("NETWORK_TIMEOUT", detail="git commit 이 끝나지 않았다")
            return result

        error = code_of(self.commit, git=commit_times_out_and_head_is_unreadable)
        self.assertTrue((self.work / KO_PATH).exists(), "만들어진 커밋의 글 파일을 지우면 안 된다")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "", "삭제가 스테이징돼 남으면 안 된다")
        self.assertIn(Path(KO_PATH).name, error.detail, "그대로 둔 파일을 이름으로 알린다")

    def test_a_timeout_in_add_leaves_no_stale_index_lock_so_the_next_try_works(self):
        lock = self.work / ".git" / "index.lock"

        def add_times_out(cwd, args):
            if args[0] == "add":
                lock.write_bytes(b"")                                                            # 끊긴 git 이 남긴 잠금
                raise AppError("NETWORK_TIMEOUT", detail="git add 가 끝나지 않았다")
            return gitrepo.run_git(cwd, args)

        self.assertEqual(code_of(self.commit, git=add_times_out).code, "NETWORK_TIMEOUT")
        self.assertFalse(lock.exists(), "남은 잠금을 치운다")
        self.assertFalse((self.work / KO_PATH).exists())
        info = self.commit()                                                                     # 다음 시도가 막히지 않는다
        self.assertEqual(info.commit, self.head())

    def test_the_branch_is_checked_again_right_before_the_file_is_added(self):
        spy = Spy()
        self.commit(git=spy)
        add_at = spy.calls.index(["add", "--", KO_PATH])
        self.assertEqual(spy.calls[add_at - 1], ["symbolic-ref", "-q", "HEAD"], "add 바로 앞에서 main 인지 다시 본다")

    def test_unstage_never_removes_a_path_that_is_already_in_head_even_when_reset_fails(self):
        self.commit()
        flaky = Flaky(fail=("reset",))                                                    # reset 이 안 먹는 상황
        self.assertEqual(pages._unstage(flaky, self.work, KO_PATH), [])
        self.assertFalse(any(call[0] == "rm" for call in flaky.calls), "HEAD 에 있는 글은 색인에서 빼지 않는다")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "", "삭제가 스테이징되지 않았다")

    def test_a_leftover_file_with_the_same_size_but_other_content_is_still_a_duplicate(self):
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        same_size_other = KO_TEXT.replace("layout: post", "layout: pose", 1)
        self.assertEqual(len(same_size_other.encode("utf-8")), len(KO_TEXT.encode("utf-8")))
        self.assertNotEqual(same_size_other, KO_TEXT)
        (self.work / KO_PATH).write_bytes(same_size_other.encode("utf-8"))
        self.assertEqual(code_of(self.commit).code, "DUPLICATE_SLUG")
        self.assertEqual((self.work / KO_PATH).read_bytes(), same_size_other.encode("utf-8"), "남의 파일을 건드리지 않는다")

    def test_an_identical_untracked_copy_in_another_category_folder_is_a_duplicate_not_my_leftover(self):
        other = self.work / "_posts" / "다른 분야"
        other.mkdir(parents=True)
        (other / Path(KO_PATH).name).write_bytes(KO_TEXT.encode("utf-8"))
        self.assertEqual(code_of(self.commit).code, "DUPLICATE_SLUG")
        self.assertTrue((other / Path(KO_PATH).name).exists(), "남의 파일은 건드리지 않는다")
        self.assertFalse((self.work / KO_PATH).exists())

    def test_a_staged_leftover_of_my_own_that_could_not_be_cleaned_does_not_block_the_next_try(self):
        state = {"add_done": False}

        def commit_never_runs_and_head_is_unreadable(cwd, args):
            if state["add_done"] and args[0] == "rev-parse":
                raise AppError("NETWORK_TIMEOUT", detail="git rev-parse 가 끝나지 않았다")
            if args[0] == "commit":
                raise AppError("NETWORK_TIMEOUT", detail="git commit 이 끝나지 않았다")                  # 시작도 못 하고 끊겼다
            result = gitrepo.run_git(cwd, args)
            if args[0] == "add":
                state["add_done"] = True
            return result

        code_of(self.commit, git=commit_never_runs_and_head_is_unreadable)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=no"), "A  " + KO_PATH, "HEAD 를 못 읽어 치우지 못했다")
        info = self.commit()                                                                              # 다음 시도가 내 스테이징 잔여물을 알아보고 이어 간다
        self.assertEqual(info.commit, self.head())
        self.assertEqual(blob(self.work, f"HEAD:{KO_PATH}"), KO_TEXT)

    def test_a_staged_file_that_is_not_exactly_my_post_still_blocks_with_dirty(self):
        (self.work / "내 파일.md").write_text("내 글\n", encoding="utf-8", newline="\n")
        git(self.work, "add", "--", "내 파일.md")                                                          # 사용자가 스테이징한 다른 파일
        self.assertEqual(code_of(self.commit).code, "PAGES_LOCAL_REPO_DIRTY")
        self.assertEqual(git(self.work, "diff", "--cached", "--name-only"), "내 파일.md", "사용자의 스테이징은 건드리지 않는다")

    def test_a_head_that_is_read_on_the_second_try_counts_as_read(self):
        state = {"after_commit": False, "failed": 0}

        def commit_times_out_and_head_fails_once(cwd, args):
            if state["after_commit"] and args == ["rev-parse", "HEAD"] and state["failed"] == 0:
                state["failed"] = 1
                return GitResult(1, "", "fatal: simulated transient failure")                 # 시간 초과가 아닌 일반 실패 — 다시 읽는다
            result = gitrepo.run_git(cwd, args)
            if args[0] == "commit":
                state["after_commit"] = True
                raise AppError("NETWORK_TIMEOUT", detail="git commit 이 끝나지 않았다")
            return result

        with mock.patch("time.sleep"):
            error = code_of(self.commit, git=commit_times_out_and_head_fails_once)
        self.assertEqual(state["failed"], 1)
        self.assertNotIn("HEAD 를 읽지 못해", error.detail, "다시 읽어서 읽었다")
        self.assertTrue((self.work / KO_PATH).exists(), "만들어진 커밋의 글 파일을 지우면 안 된다")

    def test_a_head_read_that_hangs_until_the_time_limit_is_not_read_again(self):
        calls = []

        def hangs(cwd, args):
            calls.append(list(args))
            raise AppError("NETWORK_TIMEOUT", detail="git rev-parse 가 끝나지 않았다")

        with mock.patch("time.sleep") as sleep:
            self.assertEqual(pages._head(hangs, self.work), "")
        self.assertEqual(len(calls), 1, "멈춘 읽기를 두 번 더 기다리지 않는다")
        sleep.assert_not_called()

    def test_a_staged_hard_link_with_the_same_content_is_not_taken_for_my_staged_leftover(self):
        outside = self.tmp / "밖의 파일.md"
        outside.write_bytes(KO_TEXT.encode("utf-8"))
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        try:
            os.link(outside, self.work / KO_PATH)
        except (OSError, NotImplementedError):
            self.skipTest("이 환경에서는 하드 링크를 만들 수 없다")
        git(self.work, "add", "--", KO_PATH)                                                       # 사용자가 스테이징했다
        self.assertEqual(code_of(self.commit).code, "PAGES_LOCAL_REPO_DIRTY")
        self.assertEqual(git(self.work, "diff", "--cached", "--name-only"), KO_PATH, "사용자의 스테이징은 건드리지 않는다")

    def test_a_staged_symbolic_link_is_not_taken_for_my_staged_leftover(self):
        outside = self.tmp / "밖의 파일.md"
        outside.write_bytes(KO_TEXT.encode("utf-8"))
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        try:
            os.symlink(outside, self.work / KO_PATH)
        except (OSError, NotImplementedError):
            self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        git(self.work, "add", "--", KO_PATH)
        self.assertEqual(code_of(self.commit).code, "PAGES_LOCAL_REPO_DIRTY")
        self.assertEqual(git(self.work, "diff", "--cached", "--name-only"), KO_PATH, "사용자의 스테이징은 건드리지 않는다")
        self.assertEqual(outside.read_bytes(), KO_TEXT.encode("utf-8"))

    def test_a_branch_switch_after_add_does_not_delete_the_file_that_the_other_branch_already_tracks(self):
        git(self.work, "checkout", "-q", "-b", "other")                                              # 다른 브랜치가 같은 경로를 같은 내용으로 추적한다
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        (self.work / KO_PATH).write_bytes(KO_TEXT.encode("utf-8"))
        git(self.work, "add", "--", KO_PATH)
        git(self.work, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "다른 브랜치의 같은 글")
        git(self.work, "checkout", "-q", "main")                                                     # main 에는 그 파일이 없다
        self.assertFalse((self.work / KO_PATH).exists())
        calls = {"checks": 0}

        def switch_after_add(cwd, args):
            if args[:2] == ["symbolic-ref", "-q"]:
                calls["checks"] += 1
                if calls["checks"] == 3:                                                              # 연결 확인·쓰기 앞·commit 앞
                    git(self.work, "checkout", "-q", "other")
            return gitrepo.run_git(cwd, args)

        self.assertEqual(code_of(self.commit, git=switch_after_add).code, "PAGES_LOCAL_REPO_NOT_MAIN")
        self.assertTrue((self.work / KO_PATH).exists(), "지금 브랜치가 추적하는 파일은 지우지 않는다")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")

    def test_the_branch_is_checked_again_between_add_and_commit_and_a_switch_there_cleans_up_what_was_staged(self):
        spy = Spy()
        self.commit(git=spy)
        commit_at = spy.calls.index(next(call for call in spy.calls if call[0] == "commit"))
        self.assertEqual(spy.calls[commit_at - 1], ["symbolic-ref", "-q", "HEAD"], "commit 바로 앞에서 main 인지 다시 본다")

        git(self.work, "reset", "--hard", "-q", "HEAD~1")                                                  # 처음 상태로 돌아가 이번엔 add 가 끝난 뒤 사용자가 브랜치를 바꾸는 경우
        git(self.work, "checkout", "-q", "-b", "other")
        commit_file(self.work, "다른 브랜치 글.md", "다른 글\n", "other")                                         # 그 브랜치의 HEAD 는 우리가 알던 HEAD 와 다르다
        git(self.work, "checkout", "-q", "main")
        calls = {"checks": 0}

        def switch_after_add(cwd, args):
            if args[:2] == ["symbolic-ref", "-q"]:
                calls["checks"] += 1
                if calls["checks"] == 3:                                                                    # 연결 확인·쓰기 앞·commit 앞
                    git(self.work, "checkout", "-q", "other")
            return gitrepo.run_git(cwd, args)

        error = code_of(self.commit, git=switch_after_add)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_NOT_MAIN")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "", "스테이징된 것과 쓴 파일을 치운다")
        self.assertFalse((self.work / KO_PATH).exists())

    def test_a_failed_commit_unstages_the_file_with_reset_and_needs_no_fallback(self):
        flaky = Flaky(fail=("commit",))
        code_of(self.commit, git=flaky)
        self.assertIn(["reset", "--quiet", "--", KO_PATH], flaky.calls, "스테이징 취소는 reset 으로 한다")
        self.assertFalse(any(call[0] == "rm" for call in flaky.calls), "reset 이 먹으면 색인에서 직접 빼는 보조 수단은 쓰지 않는다")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")

    def test_a_file_that_could_not_be_removed_is_named_in_the_error_and_reused_by_the_next_try(self):
        real = Path.unlink

        def unlink(self_, missing_ok=False):
            if self_.name == Path(KO_PATH).name:
                raise PermissionError(13, "Permission denied")                       # 백신·색인기가 잠깐 쥔 파일
            return real(self_, missing_ok=missing_ok)

        with mock.patch.object(Path, "unlink", unlink), mock.patch("time.sleep"):
            error = code_of(self.commit, git=Flaky(fail=("commit",)))
        self.assertIn(Path(KO_PATH).name, error.detail, "치우지 못한 파일의 이름을 알린다")
        self.assertTrue((self.work / KO_PATH).exists())
        info = self.commit()                                                          # 내 파일이 그대로 남아 있어도 '같은 이름의 글이 있다' 로 막히지 않고 이어 간다
        self.assertEqual(info.commit, self.head())
        self.assertEqual(blob(self.work, f"HEAD:{KO_PATH}"), KO_TEXT)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")

    def test_a_leftover_file_with_other_content_is_still_a_duplicate(self):
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        (self.work / KO_PATH).write_text("---\nlayout: post\n---\n다른 내용\n", encoding="utf-8", newline="\n")
        self.assertEqual(code_of(self.commit).code, "DUPLICATE_SLUG")
        self.assertEqual((self.work / KO_PATH).read_text(encoding="utf-8"), "---\nlayout: post\n---\n다른 내용\n", "남의 파일을 건드리지 않는다")

    def test_a_commit_that_was_made_but_whose_call_timed_out_stays_and_can_be_pushed(self):
        base = self.head()
        error = code_of(self.commit, git=Flaky(then_raise=("commit",)))
        self.assertEqual(error.code, "NETWORK_TIMEOUT")
        self.assertNotEqual(self.head(), base, "커밋은 만들어졌다")
        self.assertTrue((self.work / KO_PATH).exists(), "만들어진 커밋의 글 파일을 지우면 안 된다")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        info = self.push()
        self.assertEqual(self.remote_main(), info.commit)

    def test_the_rebase_is_aborted_and_the_lock_cleared_when_it_is_cut_off(self):
        calls = []

        def fake(cwd, args):
            calls.append(list(args))
            if args[0] == "rebase" and "--abort" not in args:
                raise AppError("NETWORK_TIMEOUT", detail="git rebase 가 끝나지 않았다")
            if args[0] == "symbolic-ref":
                return GitResult(0, "refs/heads/main\n", "")                      # rebase 직전의 main 확인
            if args[0] == "rev-parse":
                return GitResult(0, str(self.work / ".git"), "")
            return GitResult(0, "", "")

        with self.assertRaises(AppError) as caught:
            pages._rebase(fake, self.work)
        self.assertEqual(caught.exception.code, "NETWORK_TIMEOUT")
        self.assertIn(["rebase", "--abort"], calls)
        self.assertIn(["rev-parse", "--absolute-git-dir"], calls, "끈 git 이 남긴 잠금을 치우려고 git 폴더를 찾는다")

    def test_the_branch_must_still_be_main_when_the_loop_starts(self):
        git(self.work, "checkout", "-q", "-b", "other")
        error = code_of(pages._require_main, gitrepo.run_git, self.work)
        self.assertEqual((error.code, error.slots["브랜치"]), ("PAGES_LOCAL_REPO_NOT_MAIN", "other"))
        git(self.work, "checkout", "-q", "main")
        pages._require_main(gitrepo.run_git, self.work)


class PushCommitTest(PublishBase):
    def test_a_plain_push_puts_exactly_the_post_commit_on_the_remote_main_without_force(self):
        before = self.remote_main()
        self.commit(title="글")
        spy = Spy()
        info = self.push(git=spy)
        self.assertEqual((info.attempts, info.already), (1, False))
        self.assertEqual(info.commit, self.head())
        self.assertEqual(self.remote_main(), self.head())
        self.assertEqual(git(self.origin, "rev-parse", "main~1"), before)
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}"), KO_TEXT)
        (push,) = spy.pushes()
        self.assertEqual(push, ["push", "--porcelain", "--no-verify", "origin", f"{info.commit}:refs/heads/main"], "브랜치 이름이 아니라 검사한 커밋 번호로 올린다")
        self.assertFalse(any(arg in ("--force", "-f", "--force-with-lease", "--mirror", "--delete") or arg.startswith("+") for call in spy.calls for arg in call if call[0] == "push"))

    def test_when_the_bot_already_posted_the_commit_is_moved_on_top_before_pushing(self):
        self.commit()
        bot = self.bot_pushes()
        info = self.push()
        self.assertEqual(info.attempts, 1)
        self.assertEqual(git(self.origin, "rev-parse", "main~1"), bot)
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}"), KO_TEXT)
        self.assertEqual(blob(self.origin, "main:_posts/Bot/2026-10-30-KR-090000.md"), "봇 글\n")

    def test_when_the_bot_posts_right_before_the_push_the_push_is_retried_on_top_of_the_new_main(self):
        self.commit()
        spy = Spy(before_push=[self.bot_pushes])
        info = self.push(git=spy)
        self.assertEqual(info.attempts, 2)
        self.assertEqual(len(spy.pushes()), 2)
        self.assertEqual(self.remote_main(), self.head())
        self.assertEqual(blob(self.origin, "main:_posts/Bot/2026-10-30-KR-090000.md"), "봇 글\n")
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}"), KO_TEXT)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")

    def test_if_the_bot_wins_every_time_it_gives_up_after_three_pushes_and_the_commit_stays_for_later(self):
        self.commit()
        names = [f"_posts/Bot/2026-10-30-KR-09000{i}.md" for i in range(3)]
        spy = Spy(before_push=[lambda name=name: self.bot_pushes(name) for name in names])
        error = code_of(self.push, git=spy)
        self.assertEqual(error.code, "GIT_PUSH_REJECTED")
        self.assertEqual(len(spy.pushes()), 3)
        self.assertEqual(blob(self.work, f"HEAD:{KO_PATH}"), KO_TEXT, "올리지 못한 커밋은 그대로 남는다")
        info = self.push()                                   # 방해가 없어지면 이어서 올라간다
        self.assertEqual(self.remote_main(), self.head())
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}"), KO_TEXT)
        for name in names:
            self.assertIsNotNone(blob(self.origin, f"main:{name}"), "봇의 글은 하나도 잃지 않는다")
        self.assertFalse(info.already)

    def test_the_bot_posting_the_same_name_is_a_duplicate_and_the_rebase_is_undone(self):
        self.commit()
        mine = self.head()
        self.bot_pushes(name=KO_PATH, text="---\nlayout: post\n---\n봇이 같은 이름으로 먼저 올린 글\n")
        spy = Spy()
        error = code_of(self.push, git=spy)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertFalse(any(call[0] in ("push", "rebase") for call in spy.calls), "받아 보고 같은 이름이 있으면 올리거나 옮겨 보지 않고 곧 멈춘다")
        self.assertEqual(self.head(), mine, "내 커밋은 그대로다")
        self.assertFalse((self.work / ".git" / "rebase-merge").exists() or (self.work / ".git" / "rebase-apply").exists())
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}").count("봇이 같은 이름으로"), 1, "남의 글을 덮어쓰지 않았다")

    def push_after_commit(self):
        info = self.commit()
        self.push()
        return info

    def test_pushing_again_after_it_already_went_through_is_a_success_that_does_nothing(self):
        self.commit()
        first = self.push()
        spy = Spy()
        again = self.push(git=spy)
        self.assertEqual((again.attempts, again.already, again.commit), (0, True, first.commit))
        self.assertEqual(spy.pushes(), [], "이미 올라간 글은 다시 올리지 않는다")

    def test_a_push_that_reached_the_server_but_lost_its_answer_is_not_repeated(self):
        """올리다가 연결이 끊겨 실패로 보였지만 서버에는 들어간 경우 — 다시 부르면 중복 없이 성공으로 마무리된다."""
        self.commit()
        spy = Spy(lose_answer_after_push=1)
        error = code_of(self.push, git=spy)
        self.assertEqual(error.code, "GIT_PUSH_NETWORK")
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}"), KO_TEXT, "서버에는 들어가 있다")
        spy2 = Spy()
        info = self.push(git=spy2)
        self.assertTrue(info.already)
        self.assertEqual(spy2.pushes(), [])
        self.assertEqual(git(self.origin, "log", "--format=%s", "--", KO_PATH).count("글 올리기"), 1)

    def test_anything_other_than_exactly_this_post_waiting_is_refused_and_nothing_is_pushed(self):
        before = self.remote_main()
        spy = Spy()
        # 내 커밋이 먼저, 그 위에 이 글 커밋 — 올리지 않은 커밋이 둘이다(맨 위는 이 글이라 내용 검사만으로는 거를 수 없다)
        commit_file(self.work, "mine.md", "내 커밋\n", "내 커밋")
        commit_file(self.work, KO_PATH, KO_TEXT, "글")
        self.assertEqual(code_of(self.push, git=spy).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual((spy.pushes(), self.remote_main()), ([], before))
        self.assertTrue((self.work / "mine.md").is_file(), "내 커밋은 건드리지 않는다")
        # 이 글 커밋이 다른 파일도 함께 바꾸는 경우(글 내용은 같다)
        git(self.work, "reset", "-q", "--hard", before)
        (self.work / "README.md").write_text("같이 고침\n", encoding="utf-8", newline="\n")
        (self.work / KO_PATH).parent.mkdir(parents=True, exist_ok=True)
        (self.work / KO_PATH).write_text(KO_TEXT, encoding="utf-8", newline="\n")
        git(self.work, "add", "--", "README.md", KO_PATH)
        git(self.work, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "글과 다른 파일")
        self.assertEqual(code_of(self.push, git=spy).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual((spy.pushes(), self.remote_main()), ([], before))
        # 올릴 커밋이 이 글이 아닌 경우
        git(self.work, "reset", "-q", "--hard", before)
        commit_file(self.work, KO_PATH, "---\nlayout: post\n---\n다른 내용\n", "다른 내용의 같은 이름")
        self.assertEqual(code_of(self.push, git=spy).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual((spy.pushes(), self.remote_main()), ([], before))
        # 올릴 커밋이 아예 없고 원격에도 없는 경우
        git(self.work, "reset", "-q", "--hard", before)
        self.assertEqual(code_of(self.push, git=spy).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(spy.pushes(), [])

    def test_the_same_name_with_different_content_on_the_remote_is_a_duplicate_not_a_success(self):
        self.bot_pushes(name=KO_PATH, text="---\nlayout: post\n---\n다른 글\n")
        git(self.work, "pull", "-q", "--ff-only", "origin", "main")
        self.assertEqual(code_of(self.push).code, "DUPLICATE_SLUG")

    def test_a_server_that_declines_the_push_for_its_rules_is_a_permission_problem_and_is_not_retried(self):
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text('#!/bin/sh\necho "remote: error: GH006: Protected branch update failed for refs/heads/main." >&2\nexit 1\n', encoding="utf-8", newline="\n")
        hook.chmod(0o755)
        self.commit()
        spy = Spy()
        error = code_of(self.push, git=spy)
        if not spy.pushes() or error.code == "UNEXPECTED_ERROR":
            self.skipTest("이 환경의 git 이 서버 훅을 쓰지 않는다")
        self.assertEqual(error.code, "GIT_PUSH_AUTH")
        self.assertEqual(len(spy.pushes()), 1, "권한 문제는 다시 해도 같으니 반복하지 않는다")

    def test_a_bad_post_is_refused_before_any_git_call(self):
        spy = Spy()
        error = code_of(pages.push_commit, self.work, Post("_posts/../x.md", KO_TEXT), git=spy, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertEqual(spy.calls, [])

    def test_a_push_that_claims_success_but_left_the_commit_off_the_remote_is_reported(self):
        self.commit()

        def pretend_git(cwd, args):
            if args[0] == "push":
                return GitResult(0, "", "")
            return gitrepo.run_git(cwd, args)

        self.assertEqual(code_of(self.push, git=pretend_git).code, "UNEXPECTED_ERROR")

    def test_the_bot_posting_the_same_name_right_before_the_push_is_caught_while_moving_the_commit(self):
        self.commit()
        mine = self.head()
        spy = Spy(before_push=[lambda: self.bot_pushes(name=KO_PATH, text="---\nlayout: post\n---\n봇의 같은 이름 글\n")])
        error = code_of(self.push, git=spy)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertEqual(len(spy.pushes()), 1)
        self.assertEqual(self.head(), mine, "되돌려서 내 커밋이 그대로다")
        self.assertFalse((self.work / ".git" / "rebase-merge").exists() or (self.work / ".git" / "rebase-apply").exists())
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertIn("봇의 같은 이름 글", blob(self.origin, f"main:{KO_PATH}"), "남의 글을 덮어쓰지 않았다")

    def test_the_users_signing_setting_and_blocking_hooks_do_not_get_in_the_way_of_moving_the_commit(self):
        git(self.work, "config", "commit.gpgsign", "true")
        git(self.work, "config", "gpg.program", str(self.tmp / "no-such-gpg"))                  # 서명을 켜 둔 PC: 서명 도구가 없으면 rebase 가 실패한다
        self.commit()
        for name in ("pre-rebase", "post-rewrite", "post-checkout", "reference-transaction", "post-merge"):
            hook = self.work / ".git" / "hooks" / name
            hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")             # 막는 훅: 돌았다면 받기·옮기기가 막힌다
            hook.chmod(0o755)
        bot = self.bot_pushes()
        info = self.push()
        self.assertEqual(info.attempts, 1)
        self.assertEqual(git(self.origin, "rev-parse", "main~1"), bot)
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}"), KO_TEXT)

    def test_pushing_checks_the_connection_first_like_committing_does(self):
        self.commit()
        spy = Spy()
        git(self.work, "checkout", "-q", "-b", "other")
        self.assertEqual(code_of(self.push, git=spy).code, "PAGES_LOCAL_REPO_NOT_MAIN")
        git(self.work, "checkout", "-q", "main")
        git(self.work, "remote", "set-url", "origin", "https://github.com/someone/else.git")
        self.assertEqual(code_of(self.push, git=spy).code, "PAGES_LOCAL_REPO_INVALID")
        git(self.work, "remote", "set-url", "origin", str(self.origin))
        (self.work / "README.md").write_text("내가 고치는 중\n", encoding="utf-8", newline="\n")
        self.assertEqual(code_of(self.push, git=spy).code, "PAGES_LOCAL_REPO_DIRTY")
        self.assertEqual(spy.pushes(), [], "어느 경우에도 올리지 않았다")

    def test_a_post_with_the_same_address_in_another_category_arriving_before_the_push_is_a_duplicate(self):
        self.commit()
        self.bot_pushes(name="_posts/Other/2026-10-29-KR-101652.md", text="---\nlayout: post\n---\n같은 주소의 다른 글\n")
        spy = Spy()
        self.assertEqual(code_of(self.push, git=spy).code, "DUPLICATE_SLUG")
        self.assertEqual(spy.pushes(), [], "같은 주소가 원격에 있으면 올리지 않는다")
        self.assertIsNone(blob(self.origin, f"main:{KO_PATH}"))

    def test_the_same_address_with_another_extension_on_the_remote_is_a_duplicate_too(self):
        self.commit()
        self.bot_pushes(name="_posts/Other/2026-10-29-KR-101652.markdown", text="---\nlayout: post\n---\n확장자만 다른 글\n")
        self.assertEqual(code_of(self.push).code, "DUPLICATE_SLUG")

    def test_a_branch_switch_after_a_rejected_push_stops_before_the_rebase_touches_the_other_branch(self):
        info = self.commit()
        state = {"pushes": 0, "bot": None}

        def bot_first_then_switch_after_the_rejection(cwd, args):
            if args[0] == "push" and state["pushes"] == 0:
                state["bot"] = self.bot_pushes()                                      # 봇이 먼저 올려 이 push 는 거절된다
            result = gitrepo.run_git(cwd, args)
            if args[0] == "push":
                state["pushes"] += 1
                if result.returncode != 0:
                    git(self.work, "checkout", "-q", "-b", "other")                  # 거절된 뒤 사용자가 같은 커밋에서 다른 브랜치로 바꿨다
            return result

        error = code_of(self.push, git=bot_first_then_switch_after_the_rejection)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_NOT_MAIN")
        self.assertEqual(state["pushes"], 1, "다시 올리지 않는다")
        self.assertEqual(git(self.work, "rev-parse", "other"), info.commit, "다른 브랜치를 최신 위로 옮기지 않는다")
        self.assertEqual(self.remote_main(), state["bot"], "원격 main 은 봇이 올린 그대로")

    def test_a_branch_switch_right_after_the_connection_check_stops_the_push_before_anything_is_pushed(self):
        self.commit()
        base = self.remote_main()
        state = {"checks": 0}

        def switch_before_the_loop_check(cwd, args):
            if args[:2] == ["symbolic-ref", "-q"]:
                state["checks"] += 1
                if state["checks"] == 2:                                                       # 첫째는 연결 확인, 둘째가 올리기 반복문 앞의 확인
                    git(self.work, "checkout", "-q", "-b", "other")
            return gitrepo.run_git(cwd, args)

        self.assertEqual(code_of(self.push, git=switch_before_the_loop_check).code, "PAGES_LOCAL_REPO_NOT_MAIN")
        self.assertEqual(self.remote_main(), base, "아무것도 올리지 않는다")

    def test_a_post_that_is_already_published_is_not_moved_even_when_the_bot_posted_after_it(self):
        info = self.push_after_commit()
        self.bot_pushes(name="_posts/Bot/2026-10-31-KR-090000.md", text="봇의 새 글\n")            # 우리 글이 올라간 뒤 봇이 또 올려 로컬 main 이 뒤처졌다
        spy = Spy()
        again = self.push(git=spy)
        self.assertEqual((again.already, again.attempts), (True, 0))
        self.assertFalse(any(call[0] in ("rebase", "push") for call in spy.calls), "이미 올라간 글은 옮기지도 올리지도 않는다")
        self.assertEqual(self.head(), info.commit)

    def test_a_same_address_post_in_another_category_that_arrives_with_the_rejection_is_caught_before_the_commit_is_moved(self):
        info = self.commit()

        def bot_posts_twice():
            self.bot_pushes()
            self.bot_pushes(name="_posts/Other/2026-10-29-KR-101652.md", text="---\nlayout: post\n---\n같은 주소의 다른 글\n")

        self.assertEqual(code_of(self.push, git=Spy(before_push=[bot_posts_twice])).code, "DUPLICATE_SLUG")
        self.assertEqual(self.head(), info.commit, "옮기기 전에 알아봐서 커밋이 그대로다(되돌릴 수 있다)")
        pages.discard_commit(self.work, info, expected_origin=LOCAL_ORIGIN)

    def test_a_rebase_conflict_that_is_not_the_same_file_is_reported_as_a_duplicate_and_the_rebase_is_undone(self):
        info = self.commit()
        self.bot_pushes(name="_posts/경제·일", text="폴더가 아니라 파일\n")                           # 봇이 우리 분야 폴더 자리에 같은 이름의 '파일' 을 올렸다 — 옮기면 충돌한다
        error = code_of(self.push)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertFalse((self.work / ".git" / "rebase-merge").exists() or (self.work / ".git" / "rebase-apply").exists(), "진행 중인 rebase 를 남기지 않는다")
        self.assertEqual(self.head(), info.commit)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")

    def test_a_commit_the_user_adds_to_main_right_after_the_check_is_not_pushed_along(self):
        info = self.commit()

        def user_commits():
            commit_file(self.work, "mine.md", "내 글\n", "mine")                                   # 검사를 마친 뒤 사용자가 main 에 커밋을 더했다

        result = self.push(git=Spy(before_push=[user_commits]))
        self.assertEqual(self.remote_main(), info.commit, "검사한 바로 그 커밋까지만 올라간다")
        self.assertIsNone(blob(self.origin, "main:mine.md"))
        self.assertEqual(result.commit, info.commit)
        self.assertEqual(git(self.work, "rev-parse", "main~1"), info.commit, "내 커밋은 내 저장소에 그대로 있다")

    def test_a_commit_the_user_adds_to_main_before_the_final_check_stops_the_push(self):
        self.commit()
        base = self.remote_main()
        state = {"done": False}

        def user_commits_when_the_tip_is_read(cwd, args):
            if args == ["rev-parse", "refs/heads/main"] and not state["done"]:
                state["done"] = True
                commit_file(self.work, "mine.md", "내 글\n", "mine")
            return gitrepo.run_git(cwd, args)

        self.assertEqual(code_of(self.push, git=user_commits_when_the_tip_is_read).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.remote_main(), base, "아무것도 올리지 않는다")

    def test_the_rebase_itself_checks_that_the_branch_is_main_first(self):
        git(self.work, "checkout", "-q", "-b", "other")
        spy = Spy()
        self.assertEqual(code_of(pages._rebase, spy, self.work).code, "PAGES_LOCAL_REPO_NOT_MAIN")
        self.assertFalse(any(call[0] == "rebase" for call in spy.calls), "다른 브랜치를 옮기지 않는다")

    def test_a_rebase_failure_that_is_not_a_conflict_is_not_reported_as_a_duplicate(self):
        self.commit()
        self.bot_pushes()                                                                        # 봇이 먼저 올려서 rebase 가 필요하다
        calls = []

        def rebase_breaks(cwd, args):
            calls.append(list(args))
            if args[0] == "rebase" and args[1] != "--abort":
                return GitResult(1, "", "fatal: could not read orig-head")
            return gitrepo.run_git(cwd, args)

        error = code_of(self.push, git=rebase_breaks)
        self.assertNotEqual(error.code, "DUPLICATE_SLUG")
        self.assertIn(["rebase", "--abort"], calls, "진행 중인 rebase 를 남기지 않는다")

    def test_a_key_in_the_rebase_conflict_text_or_in_a_file_error_is_masked(self):
        key = "AI" + "za" + "A" * 35
        self.commit()
        self.bot_pushes()

        def rebase_conflicts_with_a_key(cwd, args):
            if args[0] == "rebase" and args[1] != "--abort":
                return GitResult(1, f"CONFLICT (add/add): Merge conflict in {key}.md", "error: could not apply abc123")
            return gitrepo.run_git(cwd, args)

        error = code_of(self.push, git=rebase_conflicts_with_a_key)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertNotIn(key, error.detail + str(error) + error.log_line())
        failure = pages._file_error(OSError(errno.EACCES, f"Permission denied {key}"), Path("x.md"))
        self.assertNotIn(key, failure.detail + failure.log_line())

    def test_switching_branches_right_before_the_push_does_not_publish_the_other_branch(self):
        info = self.commit()

        def switch():
            git(self.work, "checkout", "-q", "-b", "other")
            commit_file(self.work, "다른 브랜치 글.md", "공개하면 안 되는 글\n", "other")

        result = self.push(git=Spy(before_push=[switch]))
        self.assertEqual(self.remote_main(), info.commit, "main 브랜치의 그 글 커밋만 올라간다")
        self.assertIsNone(blob(self.origin, "main:다른 브랜치 글.md"))
        self.assertEqual(result.commit, info.commit)

    def test_a_server_ref_lock_race_is_retried_not_reported_as_a_permission_problem(self):
        self.commit()

        class Racy(Spy):
            raced = False

            def __call__(self, cwd, args):
                if args[0] == "push" and not self.raced:
                    self.raced = True
                    self.calls.append(list(args))
                    return GitResult(1, "", "remote: error: cannot lock ref 'refs/heads/main': is at 1 but expected 2\nTo https://github.com/x/y.git\n"
                                            " ! [remote rejected] HEAD -> main (failed to update ref)\nerror: failed to push some refs to 'https://github.com/x/y.git'")
                return super().__call__(cwd, args)

        info = self.push(git=Racy())
        self.assertEqual((info.attempts, info.already), (2, False))
        self.assertEqual(self.remote_main(), self.head())

    def test_discard_commit_puts_the_repository_back_so_the_next_post_can_be_committed(self):
        info = self.commit()
        self.bot_pushes(name="_posts/Other/2026-10-29-KR-101652.md", text="---\nlayout: post\n---\n같은 주소의 다른 글\n")
        self.assertEqual(code_of(self.push).code, "DUPLICATE_SLUG")
        pages.discard_commit(self.work, info, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(self.head(), info.base)
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertFalse((self.work / KO_PATH).exists())
        self.commit(self.en)                                                         # 다른 글은 이제 commit 할 수 있다
        self.assertEqual(blob(self.work, f"HEAD:{EN_PATH}"), EN_TEXT)

    def test_discard_commit_refuses_a_commit_that_is_already_on_the_remote(self):
        info = self.commit()
        self.push()
        error = code_of(pages.discard_commit, self.work, info, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}"), KO_TEXT)
        self.assertEqual(self.head(), info.commit)

    def test_discard_commit_refuses_when_my_own_commit_sits_on_top_and_leaves_everything(self):
        info = self.commit()
        commit_file(self.work, "내메모.txt", "내 글\n", "내 커밋")
        head = self.head()
        self.assertEqual(code_of(pages.discard_commit, self.work, info, expected_origin=LOCAL_ORIGIN).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.head(), head)
        self.assertTrue((self.work / KO_PATH).exists())

    def test_discard_commit_fetches_first_so_a_commit_that_reached_the_remote_is_refused_even_when_the_local_record_is_old(self):
        info = self.commit()

        def push_lands_but_the_answer_is_lost(cwd, args):
            result = gitrepo.run_git(cwd, args)
            if args[0] == "push" and result.returncode == 0:
                git(self.work, "update-ref", "refs/remotes/origin/main", info.base)           # 응답이 끊겨 이 컴퓨터는 올라간 것을 모른다(원격 기록이 옛것)
                return GitResult(128, "", "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': Connection reset by peer")
            return result

        code_of(self.push, git=push_lands_but_the_answer_is_lost)
        self.assertEqual(self.remote_main(), info.commit)
        self.assertEqual(git(self.work, "rev-parse", "origin/main"), info.base)
        error = code_of(pages.discard_commit, self.work, info, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        self.assertEqual(self.head(), info.commit)
        self.assertTrue((self.work / KO_PATH).exists())

    def test_discard_commit_does_not_trust_a_path_or_a_commit_that_is_not_the_apps_post_commit(self):
        base = self.head()
        commit_file(self.work, "docs/내노트.md", "내 노트\n", "글 올리기(데스크톱 앱): 내 노트")           # 제목은 앱 것처럼 생겼지만 글 경로가 아닌 파일 하나만 더한 커밋 — 경로 확인만 가를 수 있다
        error = code_of(pages.discard_commit, self.work, pages.CommitInfo("docs/내노트.md", self.head(), base), expected_origin=LOCAL_ORIGIN)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertTrue((self.work / "docs" / "내노트.md").exists())
        base = self.head()
        commit_file(self.work, KO_PATH, KO_TEXT, "내가 직접 만든 글")                                     # 글 경로 모양이지만 앱이 만든 커밋이 아니다
        info = pages.CommitInfo(KO_PATH, self.head(), base)
        self.assertEqual(code_of(pages.discard_commit, self.work, info, expected_origin=LOCAL_ORIGIN).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.head(), info.commit)
        self.assertTrue((self.work / KO_PATH).exists())

    def test_discard_commit_clears_the_stale_index_lock_when_the_reset_times_out(self):
        info = self.commit()
        lock = self.work / ".git" / "index.lock"

        def reset_times_out(cwd, args):
            if args[0] == "reset":
                lock.write_bytes(b"")
                raise AppError("NETWORK_TIMEOUT", detail="git reset 이 끝나지 않았다")
            return gitrepo.run_git(cwd, args)

        self.assertEqual(code_of(pages.discard_commit, self.work, info, git=reset_times_out, expected_origin=LOCAL_ORIGIN).code, "NETWORK_TIMEOUT")
        self.assertFalse(lock.exists())
        pages.discard_commit(self.work, info, expected_origin=LOCAL_ORIGIN)                 # 다음에 다시 하면 된다
        self.assertEqual(self.head(), info.base)

    def test_discard_commit_refuses_a_commit_that_was_amended_after_it_was_made(self):
        info = self.commit()
        git(self.work, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "--amend", "-m", "글 올리기(데스크톱 앱): 고침")
        self.assertNotEqual(self.head(), info.commit)
        head = self.head()
        self.assertEqual(code_of(pages.discard_commit, self.work, info, expected_origin=LOCAL_ORIGIN).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.head(), head)
        self.assertTrue((self.work / KO_PATH).exists())

    def test_discard_commit_refuses_when_the_recorded_parent_is_not_the_commits_parent(self):
        info = self.commit()
        wrong = pages.CommitInfo(info.path, info.commit, "1" * 40)
        self.assertEqual(code_of(pages.discard_commit, self.work, wrong, expected_origin=LOCAL_ORIGIN).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.head(), info.commit)
        self.assertTrue((self.work / KO_PATH).exists())

    def test_discard_commit_refuses_a_commit_with_more_than_the_post_even_if_it_looks_like_the_apps(self):
        base = self.head()
        (self.work / "_posts" / "경제·일").mkdir(parents=True)
        (self.work / KO_PATH).write_bytes(KO_TEXT.encode("utf-8"))
        (self.work / "다른 파일.md").write_text("다른 파일\n", encoding="utf-8", newline="\n")
        git(self.work, "add", "--", KO_PATH, "다른 파일.md")
        git(self.work, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "글 올리기(데스크톱 앱): 두 파일")
        info = pages.CommitInfo(KO_PATH, self.head(), base)
        self.assertEqual(code_of(pages.discard_commit, self.work, info, expected_origin=LOCAL_ORIGIN).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(self.head(), info.commit)
        self.assertTrue((self.work / "다른 파일.md").exists())

    def test_a_legacy_commit_encoding_setting_does_not_break_the_commit_or_the_discard_check(self):
        git(self.work, "config", "i18n.commitEncoding", "cp949")
        git(self.work, "config", "i18n.logOutputEncoding", "cp949")
        info = self.commit()
        header = git(self.work, "cat-file", "-p", "HEAD").split("\n\n")[0]
        self.assertNotIn("encoding", header, "commit 에 인코딩 머리가 붙지 않는다")
        pages.discard_commit(self.work, info, expected_origin=LOCAL_ORIGIN)
        self.assertEqual(self.head(), info.base)

    def test_publish_post_does_both_steps(self):
        info = pages.publish_post(self.work, self.ko, title="한 번에", expected_origin=LOCAL_ORIGIN)
        self.assertEqual(self.remote_main(), info.commit)
        self.assertEqual(blob(self.origin, f"main:{KO_PATH}"), KO_TEXT)


if __name__ == "__main__":
    unittest.main()
