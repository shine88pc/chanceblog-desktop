"""Pages 발행 시험 — 연결한 chanceblog 저장소에 글을 쓰고 commit 하고 push 한다(진짜 git, 로컬 bare 저장소, 네트워크·시크릿 없음).

지키는 것(이 모듈은 실제 main 에 올라가므로 하나씩 일부러 어겨 보는 변이 점검으로도 확인한다):
  1) 글 검사: 경로 모양(경로 이탈·`..`·절대 경로·역슬래시)·머리말·키 모양 문자열이 있으면 아무것도 쓰지 않는다.
  2) commit_post: 글 파일 하나만 commit 하고(내 다른 파일은 그대로), 같은 주소(분야가 달라도 같은 날짜-언어-시각)의 글이 있으면 DUPLICATE_SLUG,
     실패하면 쓴 파일·스테이징·만든 폴더를 치운다. 내 훅·서명 설정에 걸리지 않는다. 한글·공백 분야 폴더, LF 줄바꿈(autocrlf=true 여도).
  3) discard_commit: 옛 방식으로 이 PC 에 기록해 둔 글 커밋만 되돌린다(이 PC 안의 일 — 네트워크 없음). 원격 main 으로 올리던 `push_commit`·`publish_post` 는 없어졌고(새 가지에 올리는 시험은 `test_pages_branch_build.py`),
     `commit_post` 는 옛 `COMMITTED` 글을 이해하려는 시험 준비·되돌리기 용도로만 남아 있다. 시험 준비의 '원격 main 에 올림'은 앱 밖에서 직접 부른 git 이다(앱에는 그런 길이 없다).
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
Landed = namedtuple("Landed", "commit")
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
        """(시험 준비 전용) 이 PC 에 기록한 글 커밋이 원격 main 에 올라간 상태를 만든다 — **앱의 길이 아니다**: 앱에는 main 으로 올리는 코드가 없어서 앱 밖의 git 을 직접 부른다."""
        git(self.work, "push", "-q", "origin", "HEAD:main")
        return Landed(self.head())

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
        self.assertEqual([name for name, marker in markers.items() if marker.exists()], [], "앱이 사용자의 훅을 돌렸다")      # 올리기 쪽 훅은 `test_pages_branch_build` 의 같은 이름 시험이 본다(가지 올리기)


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

    def test_the_branch_must_still_be_main_when_the_loop_starts(self):
        git(self.work, "checkout", "-q", "-b", "other")
        error = code_of(pages._require_main, gitrepo.run_git, self.work)
        self.assertEqual((error.code, error.slots["브랜치"]), ("PAGES_LOCAL_REPO_NOT_MAIN", "other"))
        git(self.work, "checkout", "-q", "main")
        pages._require_main(gitrepo.run_git, self.work)


class DiscardCommitTest(PublishBase):
    """옛 방식(main 에 곧바로 commit)으로 이 PC 에 기록해 둔 글 커밋을 되돌리는 길(`discard_commit`) — 새 흐름(가지 올리기)은 이 상태를 만들지 않지만 옛 `COMMITTED` 글을 되돌릴 수 있어야 한다.
    이 PC 안의 일뿐이다(네트워크 명령 없음). 옛 `PushCommitTest` 의 되돌리기 시험이 여기로 옮겨 왔다(올리는 시험은 `test_pages_branch_build.py` 로 옮겼다)."""

    def test_discard_commit_puts_the_repository_back_so_the_next_post_can_be_committed(self):
        info = self.commit()
        self.bot_pushes(name="_posts/Other/2026-10-29-KR-101652.md", text="---\nlayout: post\n---\n같은 주소의 다른 글\n")
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

    def test_discard_commit_never_touches_the_network(self):
        """옛 `discard_commit_fetches_first…` 시험이 새 흐름으로 — 되돌리기는 이 PC 안의 일이다: 받기·가지 확인·올리기 같은 네트워크 명령을 한 번도 부르지 않는다(원격에 올라갔는지는 마지막으로 받아 둔 기록으로만 본다)."""
        info = self.commit()
        spy = Spy()
        pages.discard_commit(self.work, info, git=spy, expected_origin=LOCAL_ORIGIN)
        self.assertEqual([call for call in spy.calls if call[0] in ("fetch", "push", "ls-remote", "pull", "clone")], [])
        self.assertEqual(self.head(), info.base)
        self.assertFalse((self.work / KO_PATH).exists())

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


class OldMainPathIsGoneTest(unittest.TestCase):
    """옛 `push_commit`·`publish_post`·`_rebase`(원격 main 으로 올리던 길)는 없어졌다 — 앱 소스에 main 으로 가는 올리기 인자를 만드는 코드가 없다(`test_pages_branch_policy` 가 소스를 훑는다)."""

    def test_the_functions_that_pushed_to_remote_main_no_longer_exist(self):
        for name in ("push_commit", "publish_post", "_rebase", "_pending_state", "_counts", "_fetch_main", "_stem_clash", "PushInfo", "MAX_PUSH_ATTEMPTS"):
            self.assertFalse(hasattr(pages, name), f"pages.{name} 이 아직 있다")
        for name in ("push_commit", "publish_post"):
            self.assertFalse(hasattr(gitrepo, name), f"gitrepo.{name} 이 아직 있다")

    def test_the_new_path_has_the_replacement_functions(self):
        for name in ("build_branch_commit", "push_branch", "branch_on_remote", "post_on_main", "compare_link", "branch_name"):
            self.assertTrue(callable(getattr(pages, name)), name)


def setUpModule():
    import capability_support
    capability_support.external_write_on()          # 이 시험은 게시 모듈을 직접 부른다 — 외부 Write 관문·좁은 스위치·`file` 전송(로컬 bare 저장소)을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    import capability_support
    capability_support.external_write_off()


if __name__ == "__main__":
    unittest.main()
