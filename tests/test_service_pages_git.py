"""서비스 층 — GitHub Pages 올리기를 **진짜 git** 으로 확인한다(로컬 bare 저장소를 origin 으로 쓰고, 네트워크·시크릿 없음). 한 번에 몇 초씩 걸리므로 꼭 필요한 것만 둔다.

지키는 것(가짜 backend 시험이 못 보는 것):
  1) 확인된 올리기는 글 파일 하나만 commit 하고(다른 파일·다른 변경은 그대로) 강제 push 없이 origin 의 main 에 올리며, 올린 내용은 승인한 렌더링과 바이트까지 같고, 이 PC 의 경로는 어디에도 남지 않는다.
  2) 미리 보기(dry run)는 읽기 전용 git 명령(rev-parse·remote·symbolic-ref·status·ls-tree)만 부르고, 작업 폴더·색인·HEAD·원격 기록을 한 바이트도 바꾸지 않는다. 확인이 없으면 git 은 한 번도 불리지 않는다.
  3) push 가 막히면 commit 이 남아 다음 실행이 push 만 하고(다시 commit 하지 않고), 올리기 취소는 진짜 `discard_commit` 으로 저장소를 처음 상태로 되돌린다.
  4) 봇이 같은 주소의 글을 먼저 올렸으면 진짜로 글 기록을 되돌리고 PUBLISH_FAILED 로 남긴다. 같은 주소 찾기는 작업 폴더와 받아 둔 원격 main 을 모두 본다.
  5) 공개 주소 확인은 진짜 `_config.yml` 로 주소를 계산하고, 안 열리면 PUSHED 로 남는다.
"""
import hashlib
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.service import pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.journal import Journal  # noqa: E402

Post = namedtuple("Post", "path text")
READ_ONLY = {"rev-parse", "remote", "symbolic-ref", "status", "ls-tree", "rev-list", "diff-tree", "log", "cat-file"}        # 뒤의 넷: commit 직후에 멈춘 이 글의 commit 이 있는지 읽기만 해서 본다(이어받기)


class BotSpy(ss.Spy):
    """진짜 git 을 부르되, 글을 commit 한 뒤 처음 받기(fetch) 직전에 봇이 같은 주소의 글을 먼저 올린다."""

    def __init__(self, bot_push):
        super().__init__()
        self.bot_push = bot_push
        self.done = False

    def __call__(self, cwd, args, timeout=90, input_bytes=None):
        if args[0] == "fetch" and "commit" in self.commands() and not self.done:
            self.done = True
            self.bot_push()
        return super().__call__(cwd, args, timeout, input_bytes)


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class GitBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = ss.GitSandbox()
        cls.addClassCleanup(cls.box.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin, self.work = self.box.copy_into(self.tmp)
        self.use(ss.Spy())
        self.ctx.settings.save_repo_path(str(self.work))

    def use(self, spy, world=None):
        """진짜 git(spy 로 감싼 것)과 가짜 요청기·시계로 Context 를 만든다."""
        self.spy = spy
        self.world = world or ss.FakeWorld()
        self.backend = GitPagesBackend(git=spy, expected_origin=ss.LOCAL_ORIGIN, fetcher=self.world.fetcher, sleep=self.world.sleep, monotonic=self.world.clock)
        if hasattr(self, "ctx"):
            self.ctx.backend, self.ctx.git = self.backend, spy
        else:
            self.ctx = ss.make_ctx(self.tmp, backend=self.backend, repo=None, git=spy)
            self.ctx.expected_origin = ss.LOCAL_ORIGIN

    def approved(self, **kwargs):
        project_id = ss.make_approved(self.ctx, **kwargs)
        self.spy.calls.clear()
        return project_id

    def head(self, repo=None):
        return ss.git(repo or self.work, "rev-parse", "HEAD")

    def remote_main(self):
        return ss.git(self.origin, "rev-parse", "main")

    def stored_rendering(self, project_id):
        with self.ctx.store() as store:
            return store.load(project_id).variant("github_pages").rendered

    def status(self, project_id):
        return ss.status_of(self.ctx, project_id)

    def bot_pushes(self, name="_posts/Bot/2026-11-02-KR-103012.md", text="봇 글\n"):
        bot = self.tmp / "bot"
        if not bot.exists():
            ss.git(self.tmp, "clone", "-q", str(self.origin), "bot")
            ss.git(bot, "config", "core.autocrlf", "false")
        ss.git(bot, "pull", "-q", "--ff-only", "origin", "main")
        ss.commit_file(bot, name, text, "bot")
        ss.git(bot, "push", "-q", "origin", "HEAD:main")


class PublishTest(GitBase):
    def test_a_confirmed_publish_commits_only_the_post_pushes_it_without_force_and_records_the_address(self):
        (self.work / "내메모.txt").write_text("내 파일\n", encoding="utf-8")                 # 추적하지 않는 내 파일 — commit 에 들어가면 안 된다
        project_id = self.approved()
        approved_text = self.stored_rendering(project_id)
        before_remote = self.remote_main()
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, report.verified, report.url), (st.PUBLISHED, True, ss.KO_URL))
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{before_remote}..main"), "1", "새 commit 은 정확히 하나")
        self.assertEqual(ss.git(self.origin, "diff-tree", "--no-commit-id", "--name-status", "-r", "main"), f"A\t{ss.KO_PATH}")
        self.assertEqual(ss.blob(self.origin, f"main:{ss.KO_PATH}"), approved_text, "올라간 글은 승인한 렌더링과 한 글자도 다르지 않다")
        self.assertTrue(ss.git(self.origin, "log", "-1", "--format=%s", "main").startswith("글 올리기(데스크톱 앱):"))
        self.assertEqual(self.head(), self.remote_main())
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "?? 내메모.txt", "내 파일은 그대로 있고 올라가지 않았다")
        pushes = [call for call in self.spy.calls if call[0] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertFalse({"--force", "-f", "--force-with-lease", "--mirror", "--delete"} & set(pushes[0]), pushes[0])
        self.assertTrue(pushes[0][-1].endswith(":refs/heads/main"))
        self.assertEqual(self.status(project_id), st.PUBLISHED)
        self.assertEqual(projects.show_project(self.ctx, project_id).variant("github_pages").published_url, ss.KO_URL)
        self.assertIsNone(Journal(self.ctx.workspace.journal_dir).read(project_id))
        for text in (ss.git(self.work, "log", "-1", "--format=%B"), ss.blob(self.origin, f"main:{ss.KO_PATH}")):
            self.assertNotIn(str(self.tmp), text, "이 PC 의 경로가 저장소에 남지 않았다")
            self.assertNotIn(str(self.tmp).replace("\\", "/"), text)
        self.assertEqual(self.world.requests[0].split("?")[0], ss.KO_URL, "공개 주소를 진짜 _config.yml 로 계산해 확인했다")

    def test_a_post_that_never_opens_is_left_pushed_and_check_deploy_finishes_it_later(self):
        self.use(ss.Spy(), ss.FakeWorld(open_after=10 ** 6))
        project_id = self.approved()
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True, deadline=20, interval=10)
        self.assertEqual((report.status, report.pending_verification), (st.PUSHED, True))
        self.assertEqual(ss.blob(self.origin, f"main:{ss.KO_PATH}"), self.stored_rendering(project_id), "글은 올라가 있다")
        self.assertGreaterEqual(len(self.world.sleeps), 1)
        self.use(ss.Spy(), ss.FakeWorld(open_after=1))
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", "main"), "4", "다시 확인했을 뿐 다시 올리지 않았다(처음 3개 + 글 1개)")


class DryRunTest(GitBase):
    def snapshot(self):
        return {"files": ss.tree_snapshot(self.work), "index": hashlib.sha256((self.work / ".git" / "index").read_bytes()).hexdigest(), "head": self.head(),
                "remote_tracking": ss.git(self.work, "rev-parse", "refs/remotes/origin/main"), "origin": self.remote_main(), "data": ss.tree_snapshot(self.ctx.workspace.root)}

    def test_the_dry_run_runs_only_read_only_git_commands_and_changes_nothing_at_all(self):
        project_id = self.approved()
        before = self.snapshot()
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        code, out, err = ss.run_cli(self.ctx, "publish-pages", project_id)
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("아직 아무것도 하지 않았습니다", out)
        self.assertEqual(plan.stage, pages_flow.STAGE_COMMIT)
        commands = set(self.spy.commands())
        self.assertTrue(commands, "git 을 실제로 불렀다")
        self.assertLessEqual(commands, READ_ONLY, f"읽기 전용이 아닌 git 명령: {commands - READ_ONLY}")
        self.assertEqual(self.snapshot(), before, "작업 폴더·색인·HEAD·받아 둔 원격 기록·원격·데이터 폴더가 모두 그대로다")
        self.assertEqual(self.status(project_id), st.APPROVED)

    def test_without_the_confirmation_not_one_git_command_runs(self):
        project_id = self.approved()
        before = self.snapshot()
        for confirmed in (False, None, "yes", 1):
            with self.subTest(confirmed=confirmed):
                self.assertEqual(ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=confirmed).code, "CONFIRMATION_REQUIRED")
        self.assertEqual(self.spy.calls, [])
        self.assertEqual(self.snapshot(), before)

    def test_a_connected_folder_with_unsaved_changes_stops_the_dry_run_and_the_real_run_the_same_way(self):
        project_id = self.approved()
        (self.work / "README.md").write_text("내가 고치는 중\n", encoding="utf-8")
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "PAGES_LOCAL_REPO_DIRTY")
            self.assertIn("README.md", error.detail)
        self.assertEqual(self.remote_main(), ss.git(self.work, "rev-parse", "origin/main"))
        self.assertEqual((self.work / "README.md").read_text(encoding="utf-8"), "내가 고치는 중\n", "내 변경은 그대로다")


class FailureAndRecoveryTest(GitBase):
    def failing_push(self):
        self.use(ss.Spy(fail={"push"}))

    def test_a_failed_push_leaves_the_commit_and_the_retry_only_pushes_it(self):
        project_id = self.approved()
        base, remote_before = self.head(), self.remote_main()
        self.failing_push()
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "GIT_PUSH_NETWORK")
        self.assertEqual(self.status(project_id), st.COMMITTED)
        self.assertNotEqual(self.head(), base, "글 기록은 이 PC 에 남아 있다")
        self.assertEqual(self.remote_main(), remote_before, "원격은 그대로다")
        record = Journal(self.ctx.workspace.journal_dir).read(project_id)
        self.assertEqual((record.path, record.base, record.commit), (ss.KO_PATH, base, self.head()))
        self.use(ss.Spy())                                                       # 연결이 돌아왔다
        self.ctx.clock.advance(hours=1)
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, report.plan.stage), (st.PUBLISHED, pages_flow.STAGE_PUSH))
        self.assertNotIn("commit", self.spy.commands(), "다시 commit 하지 않았다")
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{remote_before}..main"), "1", "원격에는 글 하나만 올라갔다")
        self.assertEqual(self.head(), self.remote_main())

    def test_cancelling_after_a_failed_push_puts_the_repository_back_exactly(self):
        project_id = self.approved()
        base = self.head()
        self.failing_push()
        with self.assertRaises(Exception):
            pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.use(ss.Spy())
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISH_FAILED)
        self.assertEqual(self.head(), base)
        self.assertFalse((self.work / ss.KO_PATH).exists())
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(projects.show_project(self.ctx, project_id).variant("github_pages").error_code, "PUBLISH_CANCELLED")
        self.assertIsNone(Journal(self.ctx.workspace.journal_dir).read(project_id))

    def test_a_bot_that_posted_the_same_address_first_gets_the_commit_undone_and_the_post_marked_failed(self):
        self.use(BotSpy(lambda: self.bot_pushes()))
        project_id = self.approved()
        base = self.head()
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertIn("되돌렸다", error.detail)
        self.assertEqual(self.status(project_id), st.PUBLISH_FAILED)
        self.assertEqual(projects.show_project(self.ctx, project_id).variant("github_pages").error_code, "DUPLICATE_SLUG")
        self.assertEqual(ss.git(self.work, "rev-list", "--count", "origin/main..HEAD"), "0", "올리지 않은 글 기록이 남지 않았다")
        self.assertFalse((self.work / ss.KO_PATH).exists())
        self.assertEqual(self.head(), base, "글 기록을 되돌려 처음 상태로 돌아왔다(봇의 글은 받아만 두었고 아직 합치지 않았다)")
        self.assertEqual(ss.git(self.work, "rev-list", "--count", "HEAD..origin/main"), "1")
        self.assertEqual(ss.blob(self.origin, f"main:{ss.KO_PATH}"), None, "원격에는 우리 글이 올라가지 않았다")
        self.assertIsNone(Journal(self.ctx.workspace.journal_dir).read(project_id))


class DuplicateFinderTest(GitBase):
    def test_the_same_address_is_found_in_the_working_folder_and_in_the_received_remote_branch(self):
        post = Post(ss.KO_PATH, "x")
        self.assertEqual(self.backend.duplicates(self.work, post), [])
        (self.work / "_posts" / "다른 분야").mkdir(parents=True)
        (self.work / "_posts" / "다른 분야" / "2026-11-02-KR-103012.markdown").write_text("내 파일", encoding="utf-8")
        self.assertEqual(self.backend.duplicates(self.work, post), ["_posts/다른 분야/2026-11-02-KR-103012.markdown"])
        (self.work / "_posts" / "다른 분야" / "2026-11-02-KR-103012.markdown").unlink()
        self.assertEqual(self.backend.duplicates(self.work, post), [])
        self.bot_pushes()                                                       # 원격에만 있고, 받아 두기 전에는 모른다
        self.assertEqual(self.backend.duplicates(self.work, post), [])
        ss.git(self.work, "fetch", "-q", "origin")
        self.assertEqual(self.backend.duplicates(self.work, post), ["_posts/Bot/2026-11-02-KR-103012.md"])
        self.assertFalse((self.work / "_posts" / "Bot").exists(), "받아 두기만 했고 작업 폴더는 그대로다")
        self.assertEqual(self.backend.duplicates(self.work, Post("_posts/경제·일/2026-11-02-KR-103013.md", "x")), [], "초가 다르면 다른 주소다")

    def test_the_dry_run_avoids_a_second_that_a_file_already_uses_and_reports_a_duplicate_only_when_every_nearby_second_is_taken(self):
        project_id = self.approved()
        folder = self.work / "_posts" / "손으로 만든"
        folder.mkdir(parents=True)
        (folder / "2026-11-02-KR-103012.md").write_text("내 글", encoding="utf-8")
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual(plan.path, "_posts/경제·일/2026-11-02-KR-103013.md", "같은 초의 이름은 피해 다음 초의 이름으로 정한다(아무것도 쓰지 않는다)")
        for second in range(13, 18):
            (folder / f"2026-11-02-KR-1030{second}.md").write_text("내 글", encoding="utf-8")
        error = ss.code_of(pages_flow.plan_pages_publish, self.ctx, project_id)                     # 처음 시각과 다섯 번 민 시각이 모두 쓰였다
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertIn("손으로 만든", error.detail)
        self.assertNotIn("commit", self.spy.commands())

    def test_the_unpushed_commit_counter_and_the_head_helpers_read_the_real_repository(self):
        self.assertEqual(self.backend.unpushed_count(self.work), 0)
        ss.commit_file(self.work, "새 파일.txt", "x", "내 커밋")
        self.assertEqual(self.backend.unpushed_count(self.work), 1)
        info = self.backend.current_commit(self.work, ss.KO_PATH)
        self.assertEqual((info.commit, info.base, info.path), (self.head(), ss.git(self.work, "rev-parse", "HEAD^"), ss.KO_PATH))
        self.assertTrue(self.backend.post_in_head(self.work, "새 파일.txt"))
        self.assertFalse(self.backend.post_in_head(self.work, ss.KO_PATH))


def setUpModule():
    ss.external_write_on()                                   # 이 시험은 게시 흐름을 쓴다 — 외부 Write 관문을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    ss.external_write_off()


if __name__ == "__main__":
    unittest.main()
