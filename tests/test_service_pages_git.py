"""서비스 층 — GitHub Pages 올리기를 **진짜 git** 으로 확인한다(로컬 bare 저장소를 origin 으로 쓰고, 네트워크·시크릿 없음). 한 번에 몇 초씩 걸리므로 꼭 필요한 것만 둔다.

지키는 것(가짜 backend 시험이 못 보는 것):
  1) 확인된 올리기는 **새 가지 하나**만 올리고(글 파일 하나만 더한 커밋을 객체로만 만든다 — 다른 파일·작업 폴더·색인·HEAD 는 그대로, 강제 push 없음) 올린 내용은 승인한 렌더링과 바이트까지 같으며, 이 PC 의 경로는 어디에도 남지 않는다.
     **원격 main 은 한 번도 움직이지 않는다.**
  2) 미리 보기(dry run)는 읽기 전용 git 명령(rev-parse·remote·symbolic-ref·status·ls-tree)만 부르고, 작업 폴더·색인·HEAD·원격 기록을 한 바이트도 바꾸지 않는다. 확인이 없으면 git 은 한 번도 불리지 않는다.
  3) 가지 올리기가 막히면 만든 커밋을 기록(`built`)해 두고 다음 실행이 같은 커밋을 이어받아 올리며(다시 만들지 않고), 같은 일을 두 번 해도 같은 결과다.
  4) 병합은 사람이 한다 — 시험이 원격 main 에 직접 반영해 흉내 내고, 병합 확인(`merge-check`)은 **내용**으로 알아본다. 봇이 같은 주소의 글을 먼저 올렸으면 만들지 않고 알린다. 같은 주소 찾기는 작업 폴더와 받아 둔 원격 main 을 모두 본다.
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
from chanceblog_desktop.publish.gitrepo import GitResult  # noqa: E402
from chanceblog_desktop.service import pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.backend import GitBranchBackend  # noqa: E402
from chanceblog_desktop.service.journal import Journal  # noqa: E402

Post = namedtuple("Post", "path text")
READ_ONLY = {"rev-parse", "remote", "symbolic-ref", "status", "ls-tree", "rev-list", "diff-tree", "log", "cat-file"}        # 올리기 전 미리 보기가 부르는 명령 — 읽기만 한다


class BotSpy(ss.Spy):
    """진짜 git 을 부르되, 받기(fetch)가 처음 불리기 직전에 봇이 같은 주소의 글을 먼저 올린다(받은 뒤 '같은 주소' 점검에 걸리게)."""

    def __init__(self, bot_push):
        super().__init__()
        self.bot_push = bot_push
        self.done = False

    def __call__(self, cwd, args, timeout=90, input_bytes=None):
        if args[0] == "fetch" and not self.done:
            self.done = True
            self.bot_push()
        return super().__call__(cwd, args, timeout, input_bytes)


class LoseAnswerSpy(ss.Spy):
    """진짜 git 을 부르되, 첫 번째 올리기(push)가 서버에 들어간 뒤 응답만 끊긴 것처럼 실패로 돌려준다."""

    def __init__(self):
        super().__init__()
        self.lost = False

    def __call__(self, cwd, args, timeout=90, input_bytes=None):
        result = super().__call__(cwd, args, timeout, input_bytes)
        if args[0] == "push" and not self.lost and result.returncode == 0:
            self.lost = True
            return GitResult(128, "", "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': Connection reset by peer")
        return result


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
        self.main0 = self.remote_main()

    def use(self, spy, world=None):
        """진짜 git(spy 로 감싼 것)과 가짜 요청기·시계로 Context 를 만든다."""
        self.spy = spy
        self.world = world or ss.FakeWorld()
        self.backend = GitBranchBackend(git=spy, expected_origin=ss.LOCAL_ORIGIN, fetcher=self.world.fetcher, sleep=self.world.sleep, monotonic=self.world.clock)
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

    def remote_branches(self):
        return ss.git(self.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()

    def stored_rendering(self, project_id):
        with self.ctx.store() as store:
            return store.load(project_id).variant("github_pages").rendered

    def status(self, project_id):
        return ss.status_of(self.ctx, project_id)

    def branch_of(self, project_id):
        with self.ctx.store() as store:
            return st.split_remote_id(store.load(project_id).variant("github_pages").remote_id)

    def bot_pushes(self, name="_posts/Bot/2026-11-02-KR-103012.md", text="봇 글\n"):
        bot = self.tmp / "bot"
        if not bot.exists():
            ss.git(self.tmp, "clone", "-q", str(self.origin), "bot")
            ss.git(bot, "config", "core.autocrlf", "false")
        ss.git(bot, "pull", "-q", "--ff-only", "origin", "main")
        ss.commit_file(bot, name, text, "bot")
        ss.git(bot, "push", "-q", "origin", "HEAD:main")

    def merge_into_main(self, project_id):
        """병합을 흉내 낸다 — 올라간 가지의 끝으로 원격 main 을 빨리감기한다(시험 준비. 앱은 이 일을 하지 않는다)."""
        branch, commit = self.branch_of(project_id)
        ss.git(self.origin, "update-ref", "refs/heads/main", commit)
        return commit


class PublishTest(GitBase):
    def test_a_confirmed_publish_builds_only_the_post_commit_pushes_a_new_branch_without_force_and_leaves_main_alone(self):
        (self.work / "내메모.txt").write_text("내 파일\n", encoding="utf-8")                 # 추적하지 않는 내 파일 — 커밋에 들어가면 안 된다
        project_id = self.approved()
        approved_text = self.stored_rendering(project_id)
        head_before = self.head()
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, report.verified, report.pending_verification), (st.MERGE_PENDING, False, True))
        branch, commit = self.branch_of(project_id)
        self.assertEqual(report.branch, branch)
        self.assertEqual(self.remote_main(), self.main0, "원격 main 은 한 바이트도 움직이지 않았다")
        self.assertEqual(sorted(self.remote_branches()), sorted(["main", branch]))
        self.assertEqual(ss.git(self.origin, "rev-parse", branch), commit)
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{self.main0}..{branch}"), "1", "새 커밋은 정확히 하나")
        self.assertEqual(ss.git(self.origin, "diff-tree", "--no-commit-id", "--name-status", "-r", branch), f"A\t{ss.KO_PATH}")
        self.assertEqual(ss.blob(self.origin, f"{branch}:{ss.KO_PATH}"), approved_text, "올라간 글은 승인한 렌더링과 한 글자도 다르지 않다")
        self.assertTrue(ss.git(self.origin, "log", "-1", "--format=%s", branch).startswith("글 올리기(데스크톱 앱):"))
        self.assertEqual(self.head(), head_before, "작업 폴더의 HEAD 는 그대로다")
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "?? 내메모.txt", "내 파일은 그대로 있고 올라가지 않았다")
        self.assertFalse((self.work / ss.KO_PATH).exists(), "글 파일을 작업 폴더에 쓰지 않았다")
        pushes = [call for call in self.spy.calls if call[0] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertFalse({"--force", "-f", "--force-with-lease", "--mirror", "--delete"} & set(pushes[0]), pushes[0])
        self.assertEqual(pushes[0][-1], f"{commit}:refs/heads/{branch}")
        self.assertEqual(self.status(project_id), st.MERGE_PENDING)
        with self.ctx.store() as store:
            variant = store.load(project_id).variant("github_pages")
        self.assertEqual((variant.published_url, variant.remote_id), (None, f"{branch}@{commit}"))
        record = Journal(self.ctx.workspace.journal_dir).read(project_id)
        self.assertEqual((record.stage, record.branch, record.commit, record.base), ("branch_pushed", branch, commit, self.main0))
        self.assertIn("compare/main...", report.link)
        self.assertIn(branch, report.link)
        for text in (ss.git(self.origin, "log", "-1", "--format=%B", branch), ss.blob(self.origin, f"{branch}:{ss.KO_PATH}")):
            self.assertNotIn(str(self.tmp), text, "이 PC 의 경로가 저장소에 남지 않았다")
            self.assertNotIn(str(self.tmp).replace("\\", "/"), text)
        self.assertEqual(self.world.requests, [], "병합 전에는 공개 주소를 확인하지 않는다")

    def test_after_the_merge_is_confirmed_the_public_address_is_checked_and_the_post_is_published(self):
        project_id = self.approved()
        pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        commit = self.merge_into_main(project_id)
        merged = self.remote_main()
        self.spy.calls.clear()
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual((report.status, self.status(project_id)), (st.PUSHED, st.PUSHED))
        self.assertEqual(self.remote_main(), merged, "병합 확인은 읽기만 한다")
        self.assertEqual(self.world.requests, [], "병합 확인은 공개 주소를 확인하지 않는다")
        self.assertEqual(Journal(self.ctx.workspace.journal_dir).read(project_id).commit, commit)
        done = pages_flow.check_pages_deploy(self.ctx, project_id)
        self.assertEqual((done.status, done.verified, done.url), (st.PUBLISHED, True, ss.KO_URL))
        self.assertEqual(self.world.requests[0].split("?")[0], ss.KO_URL, "공개 주소를 진짜 _config.yml 로 계산해 확인했다")
        self.assertEqual(projects.show_project(self.ctx, project_id).variant("github_pages").published_url, ss.KO_URL)
        self.assertIsNone(Journal(self.ctx.workspace.journal_dir).read(project_id))
        self.assertEqual(self.remote_main(), merged, "공개 확인까지 앱은 main 을 한 번도 움직이지 않았다")

    def test_a_post_that_never_opens_is_left_pushed_and_check_deploy_finishes_it_later(self):
        self.use(ss.Spy(), ss.FakeWorld(open_after=10 ** 6))
        project_id = self.approved()
        pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.merge_into_main(project_id)
        merged = self.remote_main()
        pages_flow.merge_check_pages(self.ctx, project_id)
        report = pages_flow.check_pages_deploy(self.ctx, project_id, deadline=20, interval=10)
        self.assertEqual((report.status, report.pending_verification), (st.PUSHED, True))
        self.assertEqual(ss.blob(self.origin, f"main:{ss.KO_PATH}"), self.stored_rendering(project_id), "글은 병합돼 있다")
        self.assertGreaterEqual(len(self.world.sleeps), 1)
        self.use(ss.Spy(), ss.FakeWorld(open_after=1))
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)
        self.assertEqual(self.remote_main(), merged, "다시 확인했을 뿐 앱은 아무것도 올리지 않았다")


class DryRunTest(GitBase):
    def snapshot(self):
        return {"files": ss.tree_snapshot(self.work), "index": hashlib.sha256((self.work / ".git" / "index").read_bytes()).hexdigest(), "head": self.head(),
                "remote_tracking": ss.git(self.work, "rev-parse", "refs/remotes/origin/main"), "origin": self.remote_main(), "branches": self.remote_branches(), "data": ss.tree_snapshot(self.ctx.workspace.root)}

    def test_the_dry_run_runs_only_read_only_git_commands_and_changes_nothing_at_all(self):
        project_id = self.approved()
        before = self.snapshot()
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        code, out, err = ss.run_cli(self.ctx, "publish-pages", project_id)
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("아직 아무것도 하지 않았습니다", out)
        self.assertEqual(plan.stage, pages_flow.STAGE_BRANCH)
        self.assertRegex(plan.branch, r"\Adesktop/post-20261102-103012-[0-9a-f]{8}\Z")
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
        self.assertEqual(self.remote_branches(), ["main"])


class FailureAndRecoveryTest(GitBase):
    def failing_push(self):
        self.use(ss.Spy(fail={"push"}))

    def test_a_failed_push_leaves_the_built_commit_recorded_and_the_retry_only_pushes_it(self):
        project_id = self.approved()
        base, remote_before = self.head(), self.remote_main()
        self.failing_push()
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "GIT_PUSH_NETWORK")
        self.assertIn("원격 main 은 건드리지 않았다", error.detail)
        self.assertEqual(self.status(project_id), st.APPROVED, "올라가지 않았으니 상태는 그대로다")
        self.assertEqual(self.head(), base, "이 PC 의 저장소는 그대로다")
        self.assertEqual((self.remote_main(), self.remote_branches()), (remote_before, ["main"]), "원격은 그대로다")
        record = Journal(self.ctx.workspace.journal_dir).read(project_id)
        self.assertEqual((record.stage, record.path, record.base), ("built", ss.KO_PATH, remote_before))
        self.use(ss.Spy())                                                       # 연결이 돌아왔다
        self.ctx.clock.advance(hours=1)
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, report.plan.stage), (st.MERGE_PENDING, pages_flow.STAGE_BRANCH))
        self.assertIn("앞서 올리다 멈춘", " ".join(report.steps))
        self.assertNotIn("commit-tree", self.spy.commands(), "같은 커밋을 이어받았고 다시 만들지 않았다")
        branch, commit = self.branch_of(project_id)
        self.assertEqual(commit, record.commit)
        self.assertEqual(branch, record.branch)
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{remote_before}..{branch}"), "1", "원격에는 글 하나만 올라갔다")
        self.assertEqual(self.remote_main(), remote_before)

    def test_a_push_that_reached_the_server_but_lost_its_answer_is_adopted_without_a_second_push(self):
        """올리다가 연결이 끊겨 실패로 보였지만 서버에는 들어간 경우 — 가지를 한 번 더 읽어 올라간 것을 알아보고 두 번째 push 없이 병합 기다림으로 마무리한다."""
        project_id = self.approved()
        self.use(LoseAnswerSpy())
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.MERGE_PENDING)
        self.assertEqual(len([call for call in self.spy.calls if call[0] == "push"]), 1)
        self.assertEqual(len(self.remote_branches()), 2)
        self.assertEqual(self.remote_main(), self.main0)
        self.assertEqual(ss.git(self.origin, "rev-parse", self.branch_of(project_id)[0]), self.branch_of(project_id)[1])

    def test_cancelling_an_old_style_record_puts_the_repository_back_exactly(self):
        """옛 방식으로 이 PC 에 기록해 둔 글(COMMITTED)만 되돌린다 — 새 흐름은 이 상태를 만들지 않는다(앱 밖에서 만든 옛 기록을 시험 준비로 흉내 낸다)."""
        project_id = self.approved()
        base = self.head()
        from chanceblog_desktop.publish import pages
        post_text = self.stored_rendering(project_id)
        info = pages.commit_post(self.work, Post(ss.KO_PATH, post_text), expected_origin=ss.LOCAL_ORIGIN)
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.transition("github_pages", st.COMMITTED, now=self.ctx.stamp())
            store.save(project)
        from chanceblog_desktop.service.journal import PublishRecord
        Journal(self.ctx.workspace.journal_dir).write(PublishRecord(project_id, ss.KO_PATH, info.commit, info.base, "committed"))
        self.assertNotEqual(self.head(), base)
        self.use(ss.Spy())
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISH_FAILED)
        self.assertEqual(self.head(), base)
        self.assertFalse((self.work / ss.KO_PATH).exists())
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(projects.show_project(self.ctx, project_id).variant("github_pages").error_code, "PUBLISH_CANCELLED")
        self.assertIsNone(Journal(self.ctx.workspace.journal_dir).read(project_id))
        self.assertEqual([call for call in self.spy.calls if call[0] in ("fetch", "push", "ls-remote")], [], "되돌리기는 이 PC 안의 일이다 — 네트워크 명령이 없다")
        self.assertEqual(self.remote_main(), self.main0)

    def test_a_bot_that_posted_the_same_address_first_is_a_duplicate_and_nothing_is_built_or_pushed(self):
        self.use(BotSpy(lambda: self.bot_pushes()))
        project_id = self.approved()
        base = self.head()
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertEqual(self.status(project_id), st.APPROVED, "만들거나 올린 것이 없어 상태는 그대로다")
        self.assertEqual(self.head(), base)
        self.assertFalse((self.work / ss.KO_PATH).exists())
        self.assertEqual([call for call in self.spy.calls if call[0] == "push"], [])
        self.assertIsNone(ss.blob(self.origin, f"main:{ss.KO_PATH}"), "원격에는 우리 글이 올라가지 않았다")
        self.assertEqual(self.remote_branches(), ["main"])
        self.assertIsNone(Journal(self.ctx.workspace.journal_dir).read(project_id), "만들기 전에 막혔으니 발행 기록도 없다")


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
        self.assertNotIn("commit-tree", self.spy.commands())

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
