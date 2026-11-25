"""새 가지 올리기 — 객체로만 만든 글 커밋과 가지 올리기·병합 확인을 **진짜 git·로컬 bare 저장소**로 확인한다(PUBPR 설계서 PT-10–19·PT-22–24, 네트워크·시크릿 없음).

지키는 것(하나씩 일부러 어겨 보는 변이 점검으로도 확인한다):
  1) `build_branch_commit`: 받은 원격 main 위에 **글 파일 하나만 더한 커밋 한 개**를 객체로만 만든다 — 내용은 승인한 글과 한 글자도 다르지 않고(줄바꿈 변환(autocrlf)·`.gitattributes`·한글 분야 폴더 포함),
     트리는 `git add`+`git commit` 이 만들 트리와 같으며(오라클), **작업 폴더·색인·HEAD·로컬 가지는 한 바이트도 바뀌지 않는다**. 같은 주소·같은 내용이 원격 main 에 있으면 만들지 않는다.
  2) `push_branch`: 새 가지 **하나**만 올린다 — 원격의 다른 참조(특히 main)는 한 바이트도 안 변하고, 인자는 정해진 한 모양이며(강제 없음), 같은 일을 두 번 해도 같은 결과다(끝이 같으면 보내지 않고 이어 가며, 다르면 덮어쓰지 않는다).
  3) 서버가 main 갱신을 거절하는 저장소에서도 클라이언트는 main 을 시도하지 않는다(대조: 앱 밖에서 직접 올리면 main 이 실제로 움직인다 — '0' 이 빈 실험이 아니다).
  4) `post_on_main`(병합 확인): 일반 병합·squash·rebase 가 어느 쪽이든 **내용**으로 알아보고, 같은 경로에 다른 글이면 `different`, 아직이면 `not_yet`(같은 내용이 다른 경로면 그 경로만 알린다) — 아무것도 쓰지 않는다.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import gitrepo, pages  # noqa: E402
from chanceblog_desktop.publish.gitrepo import GitResult  # noqa: E402

ROOT = ss.ROOT
Post = namedtuple("Post", "path text")
KO_TEXT = (ROOT / "tests" / "fixtures" / "chance_post_ko.md").read_text(encoding="utf-8")
EN_TEXT = (ROOT / "tests" / "fixtures" / "chance_post_en.md").read_text(encoding="utf-8")
KO_PATH = "_posts/경제·일/2026-10-29-KR-101652.md"
KO_PATH_2 = "_posts/경제·일/2026-10-29-KR-101700.md"
EN_PATH = "_posts/Society & Policy/2026-10-28-EN-184844.md"
OTHER_TEXT = "---\nlayout: post\n---\n다른 글\n"
NETWORK = ("fetch", "push", "ls-remote", "pull", "clone")
git = ss.git
BOX = None


def setUpModule():
    global BOX
    ss.external_write_on()                                    # 이 시험은 올리기 흐름을 쓴다 — 외부 Write 관문·좁은 스위치·`file` 전송을 임시로만 연다(소스 상수는 모두 False)
    if ss.HAVE_GIT:
        BOX = ss.GitSandbox()


def tearDownModule():
    if BOX is not None:
        BOX.cleanup()
    ss.external_write_off()


def raw(repo, *args):
    """git 출력을 바이트 그대로(줄바꿈 변환 없이)."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    return done.stdout if done.returncode == 0 else None


class Spy:
    """진짜 git 을 부르되 호출을 기록하고, 명령 앞에서 끼어들거나(`before`) 명령의 결과를 가짜로 바꾸거나(`fake`) 올리기 뒤 응답만 잃게(`lose_answer_after_push`) 한다."""

    def __init__(self, before=None, fake=None, lose_answer_after_push=0):
        self.calls = []
        self.before = dict(before or {})
        self.fake = dict(fake or {})
        self.lose = lose_answer_after_push

    def __call__(self, cwd, args, timeout=gitrepo.DEFAULT_TIMEOUT, input_bytes=None):
        self.calls.append(list(args))
        if args[0] in self.before:
            self.before.pop(args[0])()
        if args[0] in self.fake:
            return self.fake[args[0]]
        result = gitrepo.run_git(cwd, args, timeout, input_bytes)
        if args[0] == "push" and result.returncode == 0 and self.lose:
            self.lose -= 1
            return GitResult(128, "", "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': Connection reset by peer")
        return result

    def commands(self):
        return [call[0] for call in self.calls]

    def pushes(self):
        return [call for call in self.calls if call[0] == "push"]

    def network(self):
        return [call for call in self.calls if call[0] in NETWORK]


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class BranchBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin, self.work = BOX.copy_into(self.tmp)
        self.ko, self.en = Post(KO_PATH, KO_TEXT), Post(EN_PATH, EN_TEXT)
        self.main0 = self.remote_main()                           # 시험을 시작할 때의 원격 main — 시험이 원격을 이리저리 옮겨도 처음 모양으로 돌릴 수 있다

    def build(self, post=None, **kwargs):
        return pages.build_branch_commit(self.work, post or self.ko, expected_origin=ss.LOCAL_ORIGIN, **kwargs)

    def push(self, built, post=None, **kwargs):
        return pages.push_branch(self.work, built, post or self.ko, expected_origin=ss.LOCAL_ORIGIN, **kwargs)

    def remote_main(self):
        return git(self.origin, "rev-parse", "main")

    def remote_refs(self):
        text = git(self.origin, "for-each-ref", "--format=%(refname) %(objectname)")
        return dict(line.split(" ") for line in text.splitlines() if line)

    def helper_clone(self, name="helper"):
        """앱이 아닌 시험 도우미(사람·봇)가 쓰는 별도 복제본 — 시험 준비에만 쓴다."""
        target = self.tmp / name
        if not target.exists():
            git(self.tmp, "clone", "-q", str(self.origin), name)
            git(target, "config", "core.autocrlf", "false")
        git(target, "pull", "-q", "--ff-only", "origin", "main")
        return target

    def bot_pushes(self, name="_posts/Bot/2026-10-30-KR-090000.md", text="봇 글\n", clone="bot"):
        """다른 쪽(봇·사람)이 원격 main 에 글을 올린다 → 새 main 커밋(시험 준비 — 앱 코드를 거치지 않는다)."""
        other = self.helper_clone(clone)
        ss.commit_file(other, name, text, "bot")
        git(other, "push", "-q", "origin", "HEAD:main")
        return git(other, "rev-parse", "HEAD")

    def merge_into_main(self, built):
        """병합을 흉내 낸다 — 올라간 가지의 끝으로 원격 main 을 앞으로 옮긴다(빨리감기, 시험 준비)."""
        git(self.origin, "update-ref", "refs/heads/main", built.commit)

    def fresh_repo(self, files, name="fresh"):
        """파일 몇 개만 든 새 저장소(origin 폴더, 작업 폴더) — 분야 폴더가 없거나 `_posts` 가 없는 모양을 만들 때 쓴다."""
        base = self.tmp / name
        base.mkdir()
        origin = base / "origin.git"
        git(base, "init", "-q", "--bare", str(origin))
        git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
        git(base, "clone", "-q", str(origin), "work")
        work = base / "work"
        for key, value in (("core.autocrlf", "false"), ("user.name", "운영자"), ("user.email", "operator@example.com"), ("commit.gpgsign", "false")):
            git(work, "config", key, value)
        git(work, "checkout", "-q", "-B", "main")
        for name, text in files.items():
            ss.commit_file(work, name, text)
        git(work, "push", "-q", "-u", "origin", "main")
        return origin, work

    def work_state(self):
        """작업 폴더가 '그대로' 인지 견주는 값 — 파일 내용·색인 내용·HEAD·로컬 가지와 태그·설정·HEAD 기록. (원격 추적 참조는 받기가 바꾸는 것이라 뺀다)"""
        return {"files": ss.tree_snapshot(self.work), "index": git(self.work, "ls-files", "-s"), "head": git(self.work, "rev-parse", "HEAD"), "head_ref": git(self.work, "symbolic-ref", "HEAD"),
                "heads": git(self.work, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags"), "status": git(self.work, "status", "--porcelain", "--untracked-files=all"),
                "config": (self.work / ".git" / "config").read_bytes(), "reflog": git(self.work, "reflog", "-n", "20")}


class BuildTest(BranchBase):
    def test_built_commit_has_exactly_one_added_file_on_top_of_origin_main(self):
        """PT-10 — 부모 = 받은 원격 main, 변경 = 글 파일 하나 `A`, 내용 = 승인한 글, 그리고 아직 아무 참조에도 묶이지 않았다(올리지도 않았다)."""
        bot = self.bot_pushes()                                       # 원격 main 이 작업 폴더의 받아 둔 기록보다 앞서 있다 — 만들 때 먼저 받아 그 위에 얹는다
        built = self.build(title="오늘의 경제 글")
        self.assertEqual((built.path, built.base), (KO_PATH, bot))
        self.assertRegex(built.branch, r"\Adesktop/post-20261029-101652-[0-9a-f]{8}\Z")
        self.assertEqual(built.branch, pages.branch_name(self.ko))
        self.assertEqual(git(self.work, "rev-parse", f"{built.commit}^"), bot)
        self.assertEqual(git(self.work, "rev-list", "--count", f"{bot}..{built.commit}"), "1")
        self.assertEqual(git(self.work, "diff-tree", "-z", "--no-commit-id", "--name-status", "-r", built.commit).split("\0")[:2], ["A", KO_PATH])
        self.assertEqual(ss.blob(self.work, f"{built.commit}:{KO_PATH}"), KO_TEXT)
        self.assertIn("오늘의 경제 글", git(self.work, "log", "-1", "--format=%B", built.commit))
        self.assertEqual(git(self.work, "rev-parse", "refs/remotes/origin/main"), bot, "받은 원격 main 이 부모다")
        self.assertEqual(self.remote_main(), bot, "만들기만 했고 올리지 않았다")
        self.assertEqual(git(self.work, "for-each-ref", "--contains", built.commit), "", "어떤 참조에도 묶이지 않았다(객체로만 있다)")
        self.assertEqual(self.remote_refs(), {"refs/heads/main": bot})

    def test_the_commit_subject_defaults_to_the_file_name_and_cleans_a_messy_title(self):
        first = self.build()
        self.assertEqual(git(self.work, "log", "-1", "--format=%s", first.commit), "글 올리기(데스크톱 앱): 2026-10-29-KR-101652.md")
        second = self.build(self.en, title="  첫 줄\n\n둘째 줄  " + "길" * 200)
        subject = git(self.work, "log", "-1", "--format=%s", second.commit)
        self.assertTrue(subject.startswith("글 올리기(데스크톱 앱): 첫 줄 둘째 줄 "), subject)
        self.assertLessEqual(len(subject), 120)

    def test_a_key_shaped_commit_title_is_refused_before_anything_is_made(self):
        spy = Spy()
        error = ss.code_of(pages.build_branch_commit, self.work, self.ko, title=f"제목 {ss.KEY}", git=spy, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
        self.assertNotIn(ss.KEY, error.detail + str(error) + error.log_line())
        self.assertEqual(spy.calls, [], "git 을 한 번도 부르지 않았다")

    def test_tree_equals_the_tree_porcelain_would_make(self):
        """PT-11 — 오라클: 같은 글·같은 기준(받은 main)을 `git add`+`git commit` 으로 만든 트리와 해시가 같다(새 분야 폴더·공백·기호·이미 있는 분야 폴더 모두)."""
        def oracle_tree(post, name):
            clone = self.tmp / name
            git(self.tmp, "clone", "-q", str(self.origin), name)
            for key, value in (("core.autocrlf", "false"), ("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
                git(clone, "config", key, value)
            ss.commit_file(clone, post.path, post.text, "oracle")
            return git(clone, "rev-parse", "HEAD^{tree}")

        for number, post in enumerate((self.ko, self.en)):
            with self.subTest(path=post.path):
                built = self.build(post)
                self.assertEqual(git(self.work, "rev-parse", f"{built.commit}^{{tree}}"), oracle_tree(post, f"oracle{number}"))
        built = self.build()                                           # 이미 있는 분야 폴더에 두 번째 글 — 첫 글을 병합했다고 치고(빨리감기) 같은 분야에 더한다
        self.push(built)
        self.merge_into_main(built)
        second = Post(KO_PATH_2, KO_TEXT + "\n덧붙인 문단입니다.\n")
        again = self.build(second)
        self.assertEqual(git(self.work, "rev-parse", f"{again.commit}^{{tree}}"), oracle_tree(second, "oracle_existing"))
        self.assertEqual(ss.blob(self.work, f"{again.commit}:{KO_PATH}"), KO_TEXT, "먼저 병합된 글은 그대로다")

    def test_working_tree_index_head_and_local_branches_are_untouched_byte_for_byte(self):
        """PT-12 — 만들기와 올리기가 끝나도 작업 폴더의 파일·색인·HEAD·로컬 가지·설정이 그대로다(내 추적하지 않는 파일도). 원격 추적 참조(받은 main)만 앞으로 간다."""
        (self.work / "내메모.txt").write_text("내 파일\n", encoding="utf-8")
        git(self.work, "status")
        before = self.work_state()
        index_before = (self.work / ".git" / "index").read_bytes()
        bot = self.bot_pushes()
        built = self.build()
        self.push(built)
        self.assertEqual((self.work / ".git" / "index").read_bytes(), index_before, "색인 파일이 한 바이트도 바뀌지 않았다")
        self.assertEqual(self.work_state(), before)
        self.assertFalse((self.work / KO_PATH).exists(), "글 파일은 작업 폴더에 쓰지 않았다")
        self.assertFalse((self.work / "_posts" / "경제·일").exists(), "분야 폴더도 만들지 않았다")
        self.assertEqual(git(self.work, "rev-parse", "refs/remotes/origin/main"), bot, "원격 추적 참조는 받은 만큼 앞으로 갔다")
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "?? 내메모.txt")
        self.assertEqual(git(self.work, "branch", "--list", "desktop/*"), "", "로컬 가지를 만들지 않았다")

    def test_bytes_are_exact_even_with_autocrlf_attributes_and_unicode_names(self):
        """PT-13 — `core.autocrlf=true`·`core.safecrlf=true`·`.gitattributes` 의 `eol=crlf` 가 있어도 올라간 글의 바이트가 승인한 글과 같다(줄바꿈 변환이 없다). 한글·공백·기호 분야 폴더."""
        git(self.work, "config", "core.autocrlf", "true")
        git(self.work, "config", "core.safecrlf", "true")
        git(self.work, "config", "core.quotePath", "true")
        other = self.helper_clone("attr")
        ss.commit_file(other, ".gitattributes", "*.md text eol=crlf\n", "attr")
        git(other, "push", "-q", "origin", "HEAD:main")
        for post in (self.ko, self.en):
            with self.subTest(path=post.path):
                built = self.build(post)
                self.push(built, post)
                data = raw(self.origin, "cat-file", "blob", f"{built.branch}:{post.path}")
                self.assertEqual(data, post.text.encode("utf-8"))
                self.assertNotIn(b"\r", data)
        listing = raw(self.origin, "ls-tree", "-r", "--name-only", "-z", self.remote_branch_of(self.ko)).split(b"\0")
        self.assertIn(KO_PATH.encode("utf-8"), listing, "한글 분야 폴더 이름이 그대로 들어갔다")

    def remote_branch_of(self, post):
        return pages.branch_name(post)

    def test_new_category_folder_and_existing_folder_both_work(self):
        """PT-14 — 분야 폴더가 없을 때와 있을 때, 그리고 `_posts` 자체가 없을 때. 기존 항목은 하나도 바뀌지 않고 글 한 줄만 더해진다."""
        base_listing = git(self.work, "ls-tree", "-r", "origin/main")
        built = self.build()
        after = git(self.work, "ls-tree", "-r", built.commit).splitlines()
        added = [line for line in after if line not in base_listing.splitlines()]
        self.assertEqual(len(added), 1, added)
        self.assertTrue(added[0].endswith("\t" + KO_PATH) or added[0].endswith(KO_PATH), added[0])
        self.assertEqual(len(after), len(base_listing.splitlines()) + 1, "기존 항목은 하나도 사라지거나 바뀌지 않았다(`_posts` 바로 아래의 옛 글 포함)")
        self.push(built)
        self.merge_into_main(built)
        second = Post(KO_PATH_2, KO_TEXT + "\n두 번째 글입니다.\n")
        again = self.build(second)
        names = git(self.work, "ls-tree", "-r", "--name-only", "-z", again.commit).split("\0")
        self.assertIn(KO_PATH, names)
        self.assertIn(KO_PATH_2, names)
        self.assertEqual(git(self.work, "rev-list", "--count", f"{built.commit}..{again.commit}"), "1")
        _origin, fresh = self.fresh_repo({"README.md": "블로그\n", "_config.yml": ss.CONFIG})                 # `_posts` 가 없는 저장소
        made = pages.build_branch_commit(fresh, self.ko, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(sorted(name for name in git(fresh, "ls-tree", "-r", "--name-only", "-z", made.commit).split("\0") if name), sorted(["README.md", "_config.yml", KO_PATH]))

    def test_a_folder_that_differs_only_in_letter_case_or_is_a_file_is_refused_and_nothing_is_made(self):
        """옛 `…differs_only_in_letter_case…` 시험이 새 흐름으로 — 대소문자만 다른 분야 폴더가 원격에 이미 있으면 만들지 않는다(대소문자를 구분하지 않는 PC 에서 git 이 기존 이름으로 기록해 경로가 어긋난다)."""
        self.bot_pushes(name="_posts/Society & Policy/2026-10-27-EN-000001.md", text="---\nlayout: post\n---\n앞선 글\n")
        spy = Spy()
        error = ss.code_of(pages.build_branch_commit, self.work, Post("_posts/society & policy/2026-10-28-EN-184844.md", EN_TEXT), git=spy, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertIn("Society & Policy", error.detail)
        self.assertEqual(spy.pushes(), [])
        self.assertEqual(git(self.work, "for-each-ref", "--format=%(refname)", "refs/heads"), "refs/heads/main")
        _origin, odd = self.fresh_repo({"README.md": "블로그\n", "_posts": "폴더가 아닌 파일\n"}, "odd1")
        self.assertEqual(ss.code_of(pages.build_branch_commit, odd, self.ko, expected_origin=ss.LOCAL_ORIGIN).code, "CONTENT_INVALID")
        _origin2, odd2 = self.fresh_repo({"README.md": "블로그\n", "_posts/경제·일": "분야 이름이 파일\n"}, "odd2")
        self.assertEqual(ss.code_of(pages.build_branch_commit, odd2, self.ko, expected_origin=ss.LOCAL_ORIGIN).code, "CONTENT_INVALID")

    def test_same_stem_or_same_content_on_origin_main_is_refused(self):
        """PT-15 — 같은 주소(분야가 달라도 날짜-언어-시각이 같음·확장자만 다름)이거나 내용이 똑같은 글이 원격 main 에 있으면 `DUPLICATE_SLUG`·`DUPLICATE_CONTENT`. 만들지도 올리지도 않는다."""
        cases = (("_posts/다른 분야/2026-10-29-KR-101652.md", OTHER_TEXT, "DUPLICATE_SLUG"), ("_posts/2026-10-29-KR-101652.markdown", OTHER_TEXT, "DUPLICATE_SLUG"),
                 (KO_PATH, OTHER_TEXT, "DUPLICATE_SLUG"), ("_posts/다른 분야/2026-09-01-KR-000001.md", KO_TEXT, "DUPLICATE_CONTENT"))
        for number, (name, text, code) in enumerate(cases):
            with self.subTest(name=name):
                git(self.origin, "update-ref", "refs/heads/main", self.main0)                     # 처음 모양으로 되돌린다(시험 준비)
                self.bot_pushes(name=name, text=text, clone=f"bot{number}")
                spy = Spy()
                error = ss.code_of(pages.build_branch_commit, self.work, self.ko, git=spy, expected_origin=ss.LOCAL_ORIGIN)
                self.assertEqual(error.code, code)
                self.assertEqual(spy.pushes(), [], "올리지 않았다")
                self.assertEqual(set(self.remote_refs()), {"refs/heads/main"})
                self.assertEqual(git(self.work, "for-each-ref", "--format=%(refname)", "refs/heads"), "refs/heads/main")


class BadInputTest(BranchBase):
    def test_a_bad_post_is_refused_before_any_git_call(self):
        spy = Spy()
        for post in (Post("_posts/../x.md", KO_TEXT), Post(KO_PATH, "머리말 없음\n"), Post(KO_PATH, KO_TEXT + ss.KEY)):
            with self.subTest(path=post.path):
                self.assertIn(ss.code_of(pages.build_branch_commit, self.work, post, git=spy, expected_origin=ss.LOCAL_ORIGIN).code, ("CONTENT_INVALID", "SECRET_IN_TEXT_BLOCKED"))
                built = pages.BranchCommit(KO_PATH, pages.branch_name(self.ko), "a" * 40, "b" * 40)
                self.assertIn(ss.code_of(pages.push_branch, self.work, built, post, git=spy, expected_origin=ss.LOCAL_ORIGIN).code, ("CONTENT_INVALID", "SECRET_IN_TEXT_BLOCKED"))
        self.assertEqual(spy.calls, [], "git 을 한 번도 부르지 않았다")

    def test_building_and_pushing_check_the_connection_first(self):
        built = self.build()
        for call in (lambda spy: pages.build_branch_commit(self.work, self.ko, git=spy, expected_origin=ss.LOCAL_ORIGIN), lambda spy: pages.push_branch(self.work, built, self.ko, git=spy, expected_origin=ss.LOCAL_ORIGIN)):
            spy = Spy()
            git(self.work, "checkout", "-q", "-b", "other")
            self.assertEqual(ss.code_of(call, spy).code, "PAGES_LOCAL_REPO_NOT_MAIN")
            git(self.work, "checkout", "-q", "main")
            git(self.work, "remote", "set-url", "origin", "https://github.com/someone/else.git")
            self.assertEqual(ss.code_of(call, spy).code, "PAGES_LOCAL_REPO_INVALID")
            git(self.work, "remote", "set-url", "origin", str(self.origin))
            (self.work / "README.md").write_text("내가 고치는 중\n", encoding="utf-8", newline="\n")
            self.assertEqual(ss.code_of(call, spy).code, "PAGES_LOCAL_REPO_DIRTY")
            git(self.work, "checkout", "-q", "--", "README.md")
            self.assertEqual(spy.pushes(), [], "어느 경우에도 올리지 않았다")
            self.assertEqual(self.remote_main(), git(self.work, "rev-parse", "origin/main"))
            git(self.work, "branch", "-q", "-D", "other")

    def test_a_missing_commit_author_is_reported_with_its_own_code_and_nothing_is_left(self):
        git(self.work, "config", "--unset", "user.name")
        git(self.work, "config", "--unset", "user.email")
        git(self.work, "config", "user.useConfigOnly", "true")
        empty = self.tmp / "empty.gitconfig"
        empty.write_text("", encoding="utf-8")
        old = {key: os.environ.get(key) for key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL", "HOME", "USERPROFILE")}
        self.addCleanup(lambda: [os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value) for key, value in old.items()])
        os.environ.update(GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM="1", HOME=str(self.tmp), USERPROFILE=str(self.tmp))
        for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
            os.environ.pop(name, None)
        error = ss.code_of(pages.build_branch_commit, self.work, self.ko, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(error.code, "GIT_IDENTITY_MISSING")
        self.assertEqual(self.remote_refs(), {"refs/heads/main": self.remote_main()})

    def test_a_commit_that_somehow_contains_more_than_the_post_is_reported_and_never_pushed(self):
        lying = Spy(fake={"diff-tree": GitResult(0, "M\0README.md\0", "")})
        error = ss.code_of(pages.build_branch_commit, self.work, self.ko, git=lying, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        built = self.build()
        error = ss.code_of(pages.push_branch, self.work, built, self.ko, git=lying, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        self.assertEqual(lying.pushes(), [], "올리기 직전에도 '글 하나만 더한 커밋' 을 다시 보고, 아니면 올리지 않는다")
        self.assertEqual(set(self.remote_refs()), {"refs/heads/main"})

    def test_a_failing_step_leaves_no_ref_and_no_file_behind(self):
        for command in ("hash-object", "mktree", "commit-tree"):
            with self.subTest(command=command):
                spy = Spy(fake={command: GitResult(128, "", "fatal: something broke")})
                error = ss.code_of(pages.build_branch_commit, self.work, self.ko, git=spy, expected_origin=ss.LOCAL_ORIGIN)
                self.assertEqual(error.code, "UNEXPECTED_ERROR")
                self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
                self.assertEqual(git(self.work, "for-each-ref", "--format=%(refname)", "refs/heads"), "refs/heads/main")
                self.assertEqual(set(self.remote_refs()), {"refs/heads/main"})

    def test_the_users_hooks_and_signing_settings_do_not_get_in_the_way(self):
        scratch = self.tmp / "scratch"
        git(self.tmp, "clone", "-q", str(self.origin), "scratch")
        markers = {name: self.tmp / f"ran-{name}" for name in ("pre-commit", "commit-msg", "pre-push", "reference-transaction", "post-commit")}
        for repo in (self.work, scratch):
            for name, marker in markers.items():
                hook = repo / ".git" / "hooks" / name
                hook.write_text(f'#!/bin/sh\ntouch "{marker.as_posix()}"\nexit 1\n', encoding="utf-8", newline="\n")      # 훅이 돌면 거부한다
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
        built = self.build()
        self.push(built)
        self.assertEqual([name for name, marker in markers.items() if marker.exists()], [], "앱이 사용자의 훅을 돌렸다")
        self.assertEqual(git(self.origin, "rev-parse", built.branch), built.commit)


class PushTest(BranchBase):
    def test_pushing_the_branch_moves_only_that_ref_and_origin_main_is_unchanged(self):
        """PT-16 — 원격에는 가지 하나만 새로 생기고 main 을 포함한 다른 참조는 한 바이트도 안 변한다. 인자는 정해진 한 모양이다."""
        built = self.build(title="글")
        main_before, refs_before = self.remote_main(), self.remote_refs()
        spy = Spy()
        info = self.push(built, git=spy)
        after = self.remote_refs()
        self.assertEqual((info.branch, info.commit, info.already), (built.branch, built.commit, False))
        self.assertEqual(set(after) - set(refs_before), {f"refs/heads/{built.branch}"})
        self.assertEqual(after[f"refs/heads/{built.branch}"], built.commit)
        for name, value in refs_before.items():
            self.assertEqual(after[name], value, name)
        self.assertEqual(self.remote_main(), main_before)
        self.assertEqual(git(self.origin, "rev-parse", f"{built.branch}^"), main_before, "가지는 받은 main 한 커밋 위다")
        self.assertEqual(ss.blob(self.origin, f"{built.branch}:{KO_PATH}"), KO_TEXT)
        (push,) = spy.pushes()
        self.assertEqual(push, ["push", "--porcelain", "--no-verify", "origin", f"{built.commit}:refs/heads/{built.branch}"], "커밋 번호로, 새 가지 하나만")
        shapes = [gitrepo.network_shape(call) for call in spy.network()]
        self.assertEqual(sorted(set(shapes)), ["ls_remote", "push_branch"])
        self.assertEqual(git(self.work, "for-each-ref", "--format=%(refname)", "refs/heads"), "refs/heads/main", "이 PC 에는 새 로컬 가지가 없다")
        self.assertIsNone(pages.branch_on_remote(self.work, "desktop/post-20990101-000000-00000000", expected_origin=ss.LOCAL_ORIGIN))
        self.assertEqual(pages.branch_on_remote(self.work, built.branch, expected_origin=ss.LOCAL_ORIGIN), built.commit)

    def test_a_server_that_forbids_updating_main_is_never_asked_to(self):
        """PT-17 — 서버가 main 갱신을 거절하는 저장소(`receive.hideRefs`)에서도 앱의 올리기는 main 을 시도하지 않고 성공한다. 대조로 앱 밖에서 main 에 올리면 이 서버가 거절한다."""
        git(self.origin, "config", "receive.hideRefs", "refs/heads/main")
        control = self.helper_clone("control")
        ss.commit_file(control, "_posts/Bot/2026-10-30-KR-090000.md", "봇 글\n", "bot")
        denied = subprocess.run(["git", "-C", str(control), "push", "origin", "HEAD:refs/heads/main"], capture_output=True)
        if denied.returncode == 0:
            self.skipTest("이 git 은 receive.hideRefs 로 main 갱신을 거절하지 않는다(시험이 의미 없다)")
        main_before = self.remote_main()
        spy = Spy()
        built = self.build(git=spy)
        self.push(built, git=spy)
        self.assertEqual(len(spy.pushes()), 1)
        for call in spy.pushes():
            self.assertTrue(call[-1].split(":", 1)[1].startswith("refs/heads/desktop/post-"), f"main 을 가리키는 올리기 인자가 없다: {call}")
        self.assertEqual(self.remote_main(), main_before)
        self.assertEqual(git(self.origin, "rev-parse", built.branch), built.commit)

    def test_control_experiment_a_direct_push_to_main_would_move_it_without_the_policy(self):
        """PT-18 — '앱은 main 을 움직이지 못한다' 가 빈 실험이 아님을 보인다: 같은 저장소에서 앱 밖(`subprocess` 로 직접 git)에서 올리면 main 이 **실제로 움직이고**, 앱의 git 실행기는 같은 일을 하위 프로세스 전에 거절한다."""
        before = self.remote_main()
        refused = Spy()
        with self.assertRaises(AppError) as caught:
            refused(self.work, ["push", "--porcelain", "--no-verify", "origin", "HEAD:refs/heads/main"])
        self.assertEqual(caught.exception.code, "PAGES_PUSH_REFUSED")
        self.assertEqual(self.remote_main(), before, "앱의 길로는 main 이 안 움직인다")
        other = self.helper_clone("direct")
        ss.commit_file(other, "_posts/Bot/2026-10-30-KR-090000.md", "봇 글\n", "direct")
        done = subprocess.run(["git", "-C", str(other), "push", "origin", "HEAD:refs/heads/main"], capture_output=True)
        self.assertEqual(done.returncode, 0, "앱 밖에서는 이 저장소가 main 을 받아 준다 — 막는 것은 앱의 인자 표다")
        self.assertNotEqual(self.remote_main(), before, "main 이 실제로 움직였다")

    def test_pushing_again_after_it_already_went_through_is_a_success_that_sends_nothing(self):
        """PT-19 (끝이 같음) — 같은 일을 두 번 해도 같은 결과: 이미 올라가 있고 끝이 같으면 보내지 않고 이어 간다."""
        built = self.build()
        first = self.push(built)
        spy = Spy()
        again = self.push(built, git=spy)
        self.assertEqual((again.already, again.commit, again.branch), (True, built.commit, built.branch))
        self.assertEqual(first.already, False)
        self.assertEqual(spy.pushes(), [], "두 번째 push 는 하지 않았다")

    def test_a_push_that_reached_the_server_but_lost_its_answer_is_adopted_without_a_second_push(self):
        """PT-19 (응답 끊김) — 서버에는 들어갔는데 연결이 끊겨 실패로 보인 경우: 가지를 한 번 더 읽어 올라간 것을 알아보고 두 번째 push 를 하지 않는다."""
        built = self.build()
        spy = Spy(lose_answer_after_push=1)
        info = self.push(built, git=spy)
        self.assertEqual((info.already, info.commit), (False, built.commit))
        self.assertEqual(len(spy.pushes()), 1)
        self.assertEqual(git(self.origin, "rev-parse", built.branch), built.commit)
        self.assertEqual(spy.commands().count("ls-remote"), 2, "처음 한 번(없음) + 끊긴 뒤 한 번(있음)")

    def test_a_retry_with_the_branch_missing_pushes_and_with_a_different_tip_refuses_without_overwriting(self):
        """PT-19 (가지 없음·끝이 다름) — 가지가 없으면 올리고, 같은 이름에 다른 끝이 이미 있으면 덮어쓰지 않고 `PAGES_PUSH_REFUSED`(이름 충돌)."""
        built = self.build()
        stranger = self.helper_clone("stranger")
        ss.commit_file(stranger, "_posts/Bot/2026-10-30-KR-090000.md", "다른 사람의 글\n", "other")
        git(stranger, "push", "-q", "origin", f"HEAD:refs/heads/{built.branch}")
        other_tip = git(self.origin, "rev-parse", built.branch)
        spy = Spy()
        error = ss.code_of(pages.push_branch, self.work, built, self.ko, git=spy, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(error.code, "PAGES_PUSH_REFUSED")
        self.assertEqual(spy.pushes(), [], "덮어쓰려고 시도하지도 않았다")
        self.assertEqual(git(self.origin, "rev-parse", built.branch), other_tip)
        self.assertEqual(git(self.origin, "rev-parse", "main"), built.base)

    def test_the_bot_posting_after_the_build_does_not_make_the_branch_push_fail(self):
        """옛 '봇이 먼저 올려 rebase' 시험이 새 흐름으로 — 새 가지 push 는 비빨리감기로 거절되지 않는다: main 이 앞서가도 push 는 그대로 성공하고 main 은 봇이 둔 그대로다."""
        built = self.build()
        bot = self.bot_pushes()
        info = self.push(built)
        self.assertEqual(info.already, False)
        self.assertEqual(self.remote_main(), bot, "main 은 봇의 것 그대로다 — 앱은 건드리지 않았다")
        self.assertEqual(git(self.origin, "rev-parse", f"{built.branch}^"), built.base, "가지는 만들 때 기준(옛 main) 위에 그대로 있다")

    def test_a_server_that_declines_the_push_for_its_rules_is_a_permission_problem_and_is_not_retried(self):
        """PT-41 의 짝 — 서버가 규칙으로 거절하면(GH006 문구) 권한 문제로 알리고 되풀이하지 않는다. 같은 가지를 한 번 더 읽어 보고(올라갔는지) 없으면 처음 오류를 그대로 낸다."""
        built = self.build()
        declined = GitResult(1, "", " ! [remote rejected] x -> y (protected branch hook declined)\nremote: error: GH006: Protected branch update failed.")
        spy = Spy(fake={"push": declined})
        error = ss.code_of(pages.push_branch, self.work, built, self.ko, git=spy, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(error.code, "GIT_PUSH_AUTH")
        self.assertEqual(len(spy.pushes()), 1, "권한 문제는 다시 해도 같으니 반복하지 않는다")

    def test_a_push_that_claims_success_but_left_the_branch_off_the_remote_is_reported(self):
        built = self.build()
        spy = Spy(fake={"push": GitResult(0, "", "")})
        self.assertEqual(ss.code_of(pages.push_branch, self.work, built, self.ko, git=spy, expected_origin=ss.LOCAL_ORIGIN).code, "UNEXPECTED_ERROR")
        self.assertEqual(set(self.remote_refs()), {"refs/heads/main"})

    def test_a_commit_object_that_is_gone_is_reported_so_the_flow_can_rebuild_it_once(self):
        built = self.build()
        gone = pages.BranchCommit(built.path, built.branch, "c" * 40, built.base)
        spy = Spy()
        error = ss.code_of(pages.push_branch, self.work, gone, self.ko, git=spy, expected_origin=ss.LOCAL_ORIGIN)
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        self.assertIn("다시 만든다", error.detail)
        self.assertEqual(spy.pushes(), [])
        wrong = pages.BranchCommit(built.path, "desktop/post-20990101-000000-00000000", built.commit, built.base)
        self.assertEqual(ss.code_of(pages.push_branch, self.work, wrong, self.ko, expected_origin=ss.LOCAL_ORIGIN).code, "PAGES_PUSH_REFUSED", "가지 이름이 이 글의 것이 아니면 올리지 않는다")


class MergeCheckTest(BranchBase):
    """`post_on_main` — 병합을 **내용**으로 알아본다(PT-22·23·24). 세 병합 방식은 시험이 원격 main 에 직접 반영해 흉내 낸다."""

    def pushed(self, post=None):
        post = post or self.ko
        built = self.build(post)
        self.push(built, post)
        return built, post

    def check(self, post=None, **kwargs):
        return pages.post_on_main(self.work, post or self.ko, expected_origin=ss.LOCAL_ORIGIN, **kwargs)

    def test_merge_check_detects_merge_commit_squash_and_rebase_by_content(self):
        """PT-22 — 일반 병합(병합 커밋)·squash·rebase 어느 쪽이든 원격 main 의 그 경로 내용이 같으면 `merged`, 글을 처음 담은 main 커밋을 함께 돌려준다."""
        for number, method in enumerate(("merge", "squash", "rebase")):
            with self.subTest(method=method):
                if subprocess.run(["git", "-C", str(self.origin), "show-ref", "--verify", "--quiet", f"refs/heads/{pages.branch_name(self.ko)}"]).returncode == 0:
                    git(self.origin, "update-ref", "-d", f"refs/heads/{pages.branch_name(self.ko)}")                       # 앞 반복이 올린 가지를 치운다(시험 준비 — 앱은 지우지 않는다)
                git(self.origin, "update-ref", "refs/heads/main", self.main0)
                built, post = self.pushed()
                self.bot_pushes(name=f"_posts/Bot/2026-10-30-KR-09000{number}.md", text=f"{method} 봇\n", clone=f"bot_{method}")        # main 이 앞서가 있다(병합 방식이 실제로 갈린다)
                merger = self.helper_clone(f"merger_{method}")
                for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
                    git(merger, "config", key, value)
                git(merger, "fetch", "-q", "origin", f"refs/heads/{built.branch}:refs/remotes/origin/pr")
                if method == "merge":
                    git(merger, "merge", "-q", "--no-ff", "-m", "병합", "origin/pr")
                elif method == "squash":
                    git(merger, "merge", "-q", "--squash", "origin/pr")
                    git(merger, "commit", "-q", "-m", "squash")
                else:
                    git(merger, "cherry-pick", "origin/pr")
                git(merger, "push", "-q", "origin", "HEAD:refs/heads/main")
                result = self.check(post)
                self.assertEqual(result.state, "merged")
                self.assertEqual(git(self.origin, "show", "-s", "--format=%H", result.commit), result.commit)
                self.assertEqual(ss.blob(self.origin, f"{result.commit}:{post.path}"), post.text, "그 커밋이 글을 처음 담았다")
                self.assertNotEqual(result.commit, "", method)

    def test_merge_check_reports_not_yet_merged_without_changing_anything(self):
        """PT-23 — 병합 전이면 `not_yet`. 읽기만 한다(작업 폴더 그대로, 원격 그대로)."""
        built, post = self.pushed()
        before_work, before_refs = self.work_state(), self.remote_refs()
        spy = Spy()
        result = self.check(post, git=spy)
        self.assertEqual((result.state, result.commit, result.moved_to), ("not_yet", "", ""))
        self.assertEqual(self.remote_refs(), before_refs)
        self.assertEqual(self.work_state(), before_work)
        self.assertEqual(spy.pushes(), [])
        self.assertEqual([call for call in spy.network()], [list(gitrepo.FETCH_MAIN_ARGS)], "네트워크 명령은 원격 main 받기 하나뿐이다")

    def test_merge_check_refuses_different_content_at_the_same_path_and_names_a_moved_copy_only(self):
        """PT-24 — 같은 경로에 다른 글이 있으면 `different`(공개 확인으로 이어 가지 않는다). 같은 내용이 다른 경로에 있으면 `not_yet` 에 그 경로만 알린다 — 자동으로 이어받지 않는다."""
        built, post = self.pushed()
        self.bot_pushes(name=KO_PATH, text=OTHER_TEXT)
        self.assertEqual(self.check(post).state, "different")
        git(self.origin, "update-ref", "refs/heads/main", self.main0)
        self.bot_pushes(name="_posts/경제·일/2026-10-29-KR-101653.md", text=KO_TEXT, clone="bot2")
        moved = self.check(post)
        self.assertEqual((moved.state, moved.moved_to), ("not_yet", "_posts/경제·일/2026-10-29-KR-101653.md"))


if __name__ == "__main__":
    unittest.main()
