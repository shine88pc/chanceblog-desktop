"""서비스 층 — 올리다 프로그램이 죽어도 같은 도구로 복구되는지를 **진짜 git 과 진짜 프로세스 종료(`os._exit`)** 로 확인한다(로컬 bare 저장소, 네트워크 없음).

지키는 것:
  1) 올리는 흐름의 여덟 지점(before_push·after_push·after_journal_pushed·before_check·after_check·before_journal_remove·**after_commit·after_journal_committed**)에서 프로세스를 갑자기 끝내도
     같은 명령(`publish-pages --yes`)이 글을 한 번만 올려 PUBLISHED 까지 이어 간다(같은 글이 두 번 올라가지 않는다).
  2) commit 직후에 죽은 두 지점(승인됨 + 올리지 않은 commit 하나)은 그 commit 이 **이 글의 승인한 렌더링을 그대로 더한 앱의 commit 하나뿐**일 때만 이어받고,
     `--cancel --yes` 는 그 commit 을 되돌려 저장소를 처음 상태로 돌린다.
  3) 조금이라도 다르면(내용·다른 파일 섞임·commit 둘·앱의 commit 이 아님·다른 분야 폴더) 이어받지도 되돌리지도 않고 저장소를 그대로 둔다.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.render.pages import PagesPost  # noqa: E402
from chanceblog_desktop.service import pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_COMMITTED, Journal  # noqa: E402

CHILD = textwrap.dedent('''
    import os, sys
    sys.path.insert(0, sys.argv[1])
    sys.path.insert(0, sys.argv[2])
    import service_support as ss
    from chanceblog_desktop.service import cli
    from chanceblog_desktop.service.backend import GitPagesBackend
    from chanceblog_desktop.service.context import make_context
    from chanceblog_desktop.service.journal import Journal

    data, repo, point, minutes = sys.argv[3:7]
    argv = sys.argv[7:]
    clock = ss.Clock()
    clock.advance(minutes=int(minutes))
    world = ss.FakeWorld()


    def crash(name):
        if point == name:
            os._exit(9)                                                  # 정리 없이 갑자기 끝난다(finally·atexit 도 안 돈다)


    class Crashing(GitPagesBackend):
        def commit(self, repo_path, post, title):
            info = super().commit(repo_path, post, title)
            crash("after_commit")
            return info

        def push(self, repo_path, post):
            crash("before_push")
            result = super().push(repo_path, post)
            crash("after_push")
            return result

        def check_deployed(self, *args):
            crash("before_check")
            result = super().check_deployed(*args)
            crash("after_check")
            return result


    real_write, real_remove = Journal.write, Journal.remove


    def write(self, record):
        real_write(self, record)
        crash("after_journal_" + record.stage)


    def remove(self, project_id, **kwargs):
        crash("before_journal_remove")
        return real_remove(self, project_id, **kwargs)


    Journal.write, Journal.remove = write, remove
    backend = Crashing(expected_origin=ss.LOCAL_ORIGIN, fetcher=world.fetcher, sleep=world.sleep, monotonic=world.clock)
    ctx = make_context(data_dir=data, repo=repo, backend=backend, expected_origin=ss.LOCAL_ORIGIN, clock=clock)
    sys.exit(cli.main(argv, ctx=ctx))
''')

POINTS = ("before_push", "after_push", "after_journal_pushed", "before_check", "after_check", "before_journal_remove", "after_commit", "after_journal_committed")
NEWLY_RECOVERED = ("after_commit", "after_journal_committed")


class RealGit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = ss.GitSandbox()
        cls.addClassCleanup(cls.box.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin, self.work = self.box.copy_into(self.tmp)
        self.spy = ss.Spy()
        self.backend = GitPagesBackend(git=self.spy, expected_origin=ss.LOCAL_ORIGIN, fetcher=ss.FakeWorld().fetcher)
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend, repo=None, git=self.spy)
        self.ctx.expected_origin = ss.LOCAL_ORIGIN
        self.ctx.settings.save_repo_path(str(self.work))
        self.journal = Journal(self.ctx.workspace.journal_dir)
        self.script = self.tmp / "child.py"
        self.script.write_text(CHILD, encoding="utf-8")

    def approved(self, **kwargs):
        project_id = ss.make_approved(self.ctx, **kwargs)
        self.spy.calls.clear()
        return project_id

    def rendering(self, project_id):
        with self.ctx.store() as store:
            return store.load(project_id).variant("github_pages").rendered

    def status(self, project_id):
        return ss.status_of(self.ctx, project_id)

    def head(self):
        return ss.git(self.work, "rev-parse", "HEAD")

    def remote(self):
        return ss.git(self.origin, "rev-parse", "main")

    def child(self, point, minutes, *argv):
        args = [sys.executable, "-X", "utf8", str(self.script), str(ss.ROOT / "src"), str(ss.ROOT / "tests"), str(self.ctx.workspace.root), str(self.work), point, str(minutes), *argv]
        env = {key: value for key, value in os.environ.items() if key not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA")}
        env["PYTHONIOENCODING"] = "utf-8"
        done = subprocess.run(args, capture_output=True, env=env, timeout=300)
        return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")

    def leftovers(self):
        return sorted(path.name for path in self.ctx.workspace.journal_dir.iterdir() if path.name.endswith(".lock") or ".stale-" in path.name) if self.ctx.workspace.journal_dir.exists() else []

    def make_orphan(self, project_id):
        """commit 직후에 프로그램이 죽은 것과 같은 상태를 이 프로세스 안에서 만든다 — 진짜 commit 은 하고 발행 기록·상태는 남기지 않는다."""
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        info = self.backend.commit(self.work, plan.post, plan.title)
        return plan, info


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class CrashPointsTest(RealGit):
    """지점마다 시험 하나(저장소·데이터 폴더를 새로 만든다) — 아래에서 만들어 붙인다."""

    def crash_and_recover(self, point):
        project_id = self.approved()
        approved_text = self.rendering(project_id)
        before_remote = self.remote()
        code, out, err = self.child(point, 0, "publish-pages", project_id, "--yes")
        self.assertEqual(code, 9, f"{point}: 프로세스가 그 지점에서 끝나지 않았다 | {out} | {err}")
        crashed_status = self.status(project_id)
        if point in NEWLY_RECOVERED:                                                                # 복구하기 전에 미리 보기는 '이어받는다' 고 말하고 아무것도 바꾸지 않는다
            snapshot = (self.head(), self.remote(), ss.tree_snapshot(self.work))
            code, out, err = self.child("-", 0, "publish-pages", project_id)
            self.assertEqual((code, err), (0, ""), err)
            self.assertIn("이어받습니다", out)
            self.assertIn("아직 아무것도 하지 않았습니다", out)
            self.assertEqual((self.head(), self.remote(), ss.tree_snapshot(self.work)), snapshot)
            self.assertEqual(self.status(project_id), st.APPROVED)
        code, out, err = self.child("-", 0, "publish-pages", project_id, "--yes")                   # 곧바로 같은 명령 — 죽은 작업이 남긴 잠금은 그 프로세스가 이미 없으므로 30분을 기다리지 않고 넘겨받는다
        self.assertEqual(code, 0, f"{point}: 같은 명령으로 복구되지 않았다 (죽은 뒤 상태 {crashed_status}) | {out} | {err}")
        self.assertEqual(self.status(project_id), st.PUBLISHED, point)
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{before_remote}..main"), "1", f"{point}: 글이 한 번만 올라갔다")
        self.assertEqual(ss.git(self.origin, "diff-tree", "--no-commit-id", "--name-status", "-r", "main"), f"A\t{ss.KO_PATH}")
        self.assertEqual(ss.blob(self.origin, f"main:{ss.KO_PATH}"), approved_text, "올라간 글은 승인한 렌더링 그대로다")
        self.assertEqual(self.head(), self.remote(), "연결한 저장소도 올린 것과 같다")
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(self.leftovers(), [], "잠금·옮겨 둔 낡은 파일이 남지 않았다")
        self.assertIn("넘겨받았습니다", out, "죽은 작업이 남긴 낡은 잠금을 넘겨받았다고 알린다")
        self.assertIn("그 프로세스는 이미 끝나 있음", out)
        self.assertEqual(out.count("넘겨받았습니다"), 1, "알림은 한 번만 나온다")
        if point in NEWLY_RECOVERED:
            self.assertIn("이어받았습니다", out, "commit 직후에 멈춘 것을 이어받았다고 알린다")
            self.assertNotIn("글 파일을 만들고", out, "다시 commit 하지 않았다")
        if point != "before_journal_remove":
            self.assertIsNone(self.journal.read(project_id), "끝난 글의 발행 기록은 지운다")

    def cancel_puts_back(self, point):
        project_id = self.approved()
        base = self.head()
        code, _out, err = self.child(point, 0, "publish-pages", project_id, "--yes")
        self.assertEqual(code, 9, err)
        self.assertNotEqual(self.head(), base, "올리지 않은 commit 이 있다")
        code, out, err = self.child("-", 0, "publish-pages", project_id, "--cancel", "--yes")
        self.assertEqual(code, 0, f"{out} | {err}")
        self.assertEqual(out.count("넘겨받았습니다"), 1, "알림은 한 번만 나온다")
        self.assertEqual(self.head(), base, "commit 을 되돌려 처음 상태다")
        self.assertFalse((self.work / ss.KO_PATH).exists())
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(self.remote(), ss.git(self.work, "rev-parse", "origin/main"), "원격은 처음부터 건드리지 않았다")
        self.assertEqual(projects.show_project(self.ctx, project_id).variant("github_pages").error_code, "PUBLISH_CANCELLED")
        self.assertEqual(self.status(project_id), st.PUBLISH_FAILED)
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual(self.leftovers(), [])


    def test_after_a_crash_at_after_push_cancel_is_refused_with_its_own_code_and_the_same_command_finishes_the_post(self):
        """올리기는 끝났는데 올림 기록을 쓰기 전에 죽었다 — `--cancel --yes` 는 이미 올라간 글을 되돌리지 않고 전용 오류(예전에는 UNEXPECTED_ERROR)로 거절하며 어떻게 마무리하는지 알린다."""
        project_id = self.approved()
        before_remote = self.remote()
        code, _out, err = self.child("after_push", 0, "publish-pages", project_id, "--yes")
        self.assertEqual(code, 9, err)
        self.assertEqual(self.status(project_id), st.COMMITTED, "원격에는 올라갔지만 상태는 기록하지 못했다")
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{before_remote}..main"), "1")
        head = self.head()
        code, out, err = self.child("-", 0, "publish-pages", project_id, "--cancel", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("PUBLISH_ALREADY_PUSHED", err)
        self.assertNotIn("UNEXPECTED_ERROR", err)
        self.assertNotIn("로그 내보내기", err)
        self.assertIn(f"publish-pages {project_id[:8]} --yes", err, "마무리하는 명령을 알려 준다")
        self.assertEqual((self.head(), self.status(project_id), self.remote()), (head, st.COMMITTED, ss.git(self.origin, "rev-parse", "main")), "아무것도 바꾸지 않았다")
        code, out, err = self.child("-", 0, "doctor")
        self.assertIn("이미 원격 main 에 올라가 있는데 올림 기록을 마치기 전에 멈췄습니다", out)
        code, out, err = self.child("-", 0, "publish-pages", project_id, "--yes")
        self.assertEqual(code, 0, f"{out} | {err}")
        self.assertEqual(self.status(project_id), st.PUBLISHED)
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{before_remote}..main"), "1", "글은 한 번만 올라갔다")

    def test_a_crash_before_the_record_is_removed_leaves_a_harmless_record_that_the_next_check_cleans(self):
        project_id = self.approved()
        code, _out, err = self.child("before_journal_remove", 0, "publish-pages", project_id, "--yes")
        self.assertEqual(code, 9, err)
        self.assertEqual(self.status(project_id), st.PUBLISHED)
        self.assertIsNotNone(self.journal.read(project_id), "공개됐지만 발행 기록이 남았다")
        code, out, err = self.child("-", 0, "doctor")
        self.assertEqual(code, 0, err)
        self.assertIn("남은 발행 기록", out)
        self.assertIn("해롭지 않습니다", out)
        self.assertIn(f"check-deploy {project_id[:8]}", out)
        self.assertIsNotNone(self.journal.read(project_id), "doctor 는 읽기만 한다")
        code, out, err = self.child("-", 0, "check-deploy", project_id)
        self.assertEqual(code, 0, f"{out} | {err}")
        self.assertIn("정리했습니다", out)
        self.assertIsNone(self.journal.read(project_id), "그 글의 기록만 지웠다")
        self.assertEqual(self.leftovers(), [])
        code, out, err = self.child("-", 0, "doctor")
        self.assertNotIn("남은 발행 기록", out)


def _add(name, method, point):
    def run(self):
        getattr(self, method)(point)

    run.__name__ = name
    setattr(CrashPointsTest, name, run)


for _point in POINTS:
    _add(f"test_a_crash_at_{_point}_is_recovered_by_the_same_command_and_the_post_goes_up_once", "crash_and_recover", _point)
for _point in NEWLY_RECOVERED:
    _add(f"test_after_a_crash_at_{_point}_cancel_puts_the_repository_back_exactly", "cancel_puts_back", _point)


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class AdoptionInProcessTest(RealGit):
    def test_the_plan_adopts_an_orphan_commit_and_the_run_records_pushes_and_verifies_it(self):
        project_id = self.approved()
        plan, info = self.make_orphan(project_id)
        self.assertIsNone(self.journal.read(project_id))
        again = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((again.stage, again.path, again.adopted.commit, again.adopted.base), (pages_flow.STAGE_ADOPT, ss.KO_PATH, info.commit, info.base))
        self.assertTrue(any("이어받" in action for action in again.actions))
        self.ctx.clock.advance(hours=2)                                       # 시각이 달라도 만들어 둔 파일 이름 그대로다
        calls_before = len(self.spy.calls)
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, report.plan.stage, report.plan.path), (st.PUBLISHED, pages_flow.STAGE_ADOPT, ss.KO_PATH))
        self.assertTrue(any("이어받았습니다" in step for step in report.steps), report.steps)
        self.assertNotIn("commit", [call[0] for call in self.spy.calls[calls_before:]], "다시 commit 하지 않았다")
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", "main"), "4", "처음 3개 + 글 하나")
        self.assertEqual(ss.blob(self.origin, f"main:{ss.KO_PATH}"), self.rendering(project_id))
        self.assertEqual(self.head(), self.remote())

    def test_an_orphan_is_adopted_even_when_a_bot_pushed_something_else_in_the_meantime(self):
        project_id = self.approved()
        self.make_orphan(project_id)
        bot = self.tmp / "bot"
        ss.git(self.tmp, "clone", "-q", str(self.origin), "bot")
        ss.git(bot, "config", "core.autocrlf", "false")
        ss.commit_file(bot, "_posts/Bot/2026-11-01-KR-090000.md", "봇 글\n", "bot")
        ss.git(bot, "push", "-q", "origin", "HEAD:main")
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", "main"), "5", "봇의 글과 우리 글이 모두 있다")
        self.assertEqual(ss.blob(self.origin, f"main:{ss.KO_PATH}"), self.rendering(project_id))

    def test_a_failure_while_adopting_leaves_the_found_commit_exactly_as_it_was_and_the_next_run_adopts_again(self):
        project_id = self.approved()
        _plan, info = self.make_orphan(project_id)
        head = self.head()
        real = pages_flow.Journal.write
        pages_flow.Journal.write = lambda self_, record: (_ for _ in ()).throw(AppError("FILE_WRITE_FAILED", {"경로": "x"}))
        try:
            error = ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True)
        finally:
            pages_flow.Journal.write = real
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertIn("그대로 두었다", error.detail)
        self.assertEqual(self.head(), head, "이어받으려던 commit 을 되돌리지 않았다")
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertEqual(pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True).status, st.PUBLISHED)
        self.assertEqual(self.head(), self.remote())
        self.assertEqual(info.path, ss.KO_PATH)

    def test_cancel_puts_the_orphan_back_and_a_cancelled_post_must_be_reviewed_again(self):
        project_id = self.approved()
        base = self.head()
        self.make_orphan(project_id)
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, self.head()), (st.PUBLISH_FAILED, base))
        self.assertTrue(any("멈춰 남은 이 글의 commit" in step for step in report.steps))
        self.assertEqual(ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True).code, "STATUS_TRANSITION_INVALID")

    def test_cancel_also_clears_an_old_record_left_behind_by_the_crash_after_the_record_was_written(self):
        project_id = self.approved()
        plan, info = self.make_orphan(project_id)
        from chanceblog_desktop.service.journal import PublishRecord
        self.journal.write(PublishRecord(project_id, plan.path, info.commit, info.base, STAGE_COMMITTED))
        pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertIsNone(self.journal.read(project_id))

    def test_nothing_to_adopt_means_cancel_of_an_approved_post_is_still_refused(self):
        project_id = self.approved()
        head = self.head()
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.assertEqual((self.head(), self.status(project_id)), (head, st.APPROVED))


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class NotAdoptedTest(RealGit):
    """조금이라도 다르면 이어받지도 되돌리지도 않는다 — 저장소는 있는 그대로다."""

    APP_SUBJECT = "글 올리기(데스크톱 앱): 에너지 절약 습관"

    def orphan_like(self, project_id, *, text=None, path=ss.KO_PATH, subject=APP_SUBJECT, extra=None, two=False):
        text = self.rendering(project_id) if text is None else text
        target = self.work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        names = [path]
        if extra:
            (self.work / extra).write_text("딸린 파일\n", encoding="utf-8", newline="\n")
            names.append(extra)
        ss.git(self.work, "add", "--", *names)
        ss.git(self.work, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", subject)
        if two:
            ss.commit_file(self.work, "다음 파일.txt", "x", "또 하나")

    def assert_left_alone(self, project_id, what):
        head, remote = self.head(), self.remote()
        self.assertIsNone(self.backend.orphan_commit(self.work, self.rendering(project_id), "경제·일", "ko"), what)
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):
            error = ss.code_of(call)
            self.assertIn(error.code, ("DUPLICATE_SLUG", "PAGES_LOCAL_REPO_DIVERGED"), f"{what}: {error.code}")
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "STATUS_TRANSITION_INVALID", what)
        self.assertEqual((self.head(), self.remote(), self.status(project_id)), (head, remote, st.APPROVED), what)
        self.assertTrue((self.work / ss.KO_PATH).exists(), what)

    def test_a_commit_with_different_content(self):
        project_id = self.approved()
        self.orphan_like(project_id, text=self.rendering(project_id) + "\n한 줄 더\n")
        self.assert_left_alone(project_id, "내용이 다른 commit")

    def test_a_commit_that_also_adds_another_file(self):
        project_id = self.approved()
        self.orphan_like(project_id, extra="덤.txt")
        self.assert_left_alone(project_id, "다른 파일도 더한 commit")

    def test_two_unpushed_commits(self):
        project_id = self.approved()
        self.orphan_like(project_id, two=True)
        self.assert_left_alone(project_id, "올리지 않은 commit 이 둘")

    def test_a_commit_the_app_did_not_make(self):
        project_id = self.approved()
        self.orphan_like(project_id, subject="내가 직접 만든 commit")
        self.assert_left_alone(project_id, "앱이 아닌 commit")

    def test_a_commit_in_another_category_folder_or_with_the_wrong_language_mark(self):
        project_id = self.approved()
        self.orphan_like(project_id, path="_posts/다른 분야/2026-11-02-KR-103012.md")
        head = self.head()
        self.assertIsNone(self.backend.orphan_commit(self.work, self.rendering(project_id), "경제·일", "ko"), "다른 분야 폴더")
        self.assertIsNone(self.backend.orphan_commit(self.work, self.rendering(project_id), "다른 분야", "en"), "언어 표시가 다르다")
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "STATUS_TRANSITION_INVALID")
        self.assertEqual(self.head(), head)

    def test_a_commit_that_already_reached_the_remote_is_not_an_orphan(self):
        project_id = self.approved()
        self.orphan_like(project_id)
        ss.git(self.work, "push", "-q", "origin", "HEAD:main")
        ss.git(self.work, "fetch", "-q", "origin")
        self.assertIsNone(self.backend.orphan_commit(self.work, self.rendering(project_id), "경제·일", "ko"))

    def test_a_post_that_was_edited_after_the_crash_cannot_adopt_the_old_commit(self):
        project_id = self.approved()
        self.orphan_like(project_id)
        projects.edit_project(self.ctx, project_id, markdown=ss.ko_text(1800))                # 승인이 풀렸다
        head = self.head()
        self.assertEqual(ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True).code, "STATUS_TRANSITION_INVALID")
        self.assertEqual(self.head(), head)


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class RestoredPostTest(RealGit):
    """백업으로 되돌린 글이 이미 올라간 글을 다시 '승인됨' 으로 되살려도 같은 글이 두 번 공개되지 않는다."""

    def test_a_backup_restored_after_publishing_does_not_publish_the_same_post_twice(self):
        project_id = self.approved()
        backup = projects.backup_store(self.ctx)                                 # 승인된 때의 백업
        self.assertEqual(pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True).status, st.PUBLISHED)
        remote, head = self.remote(), self.head()
        projects.restore_store(self.ctx, backup, confirmed=True)                                 # 되돌리면 이미 올린 글이 다시 '승인됨' 이다
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.ctx.clock.advance(hours=1)                                          # 파일 이름이 달라지는 시각(같은 이름이면 같은 주소 검사가 먼저 막는다)
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "DUPLICATE_CONTENT")
            self.assertEqual(error.slots["파일"], ss.KO_PATH)
        code, out, err = ss.run_cli(self.ctx, "publish-pages", project_id)
        self.assertEqual(code, 1)
        self.assertIn("DUPLICATE_CONTENT", err)
        self.assertEqual((self.remote(), self.head(), self.status(project_id)), (remote, head, st.APPROVED), "아무것도 올리지 않았다")

    def test_the_same_text_is_found_in_the_working_folder_even_with_windows_line_endings_and_in_the_received_remote_branch(self):
        text = self.rendering(self.approved())
        self.assertEqual(self.backend.same_content(self.work, text), [])
        target = self.work / "_posts" / "손으로 만든" / "2026-11-01-KR-090000.md"
        target.parent.mkdir(parents=True)
        target.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(self.backend.same_content(self.work, text), ["_posts/손으로 만든/2026-11-01-KR-090000.md"])
        target.write_bytes((text + "한 글자 더").encode("utf-8"))
        self.assertEqual(self.backend.same_content(self.work, text), [], "한 글자라도 다르면 같은 글이 아니다")
        target.unlink()
        ss.commit_file(self.work, "_posts/원격에만/2026-11-01-KR-090001.md", text, "같은 글")
        ss.git(self.work, "push", "-q", "origin", "HEAD:main")
        ss.git(self.work, "reset", "-q", "--hard", "HEAD^")                       # 작업 폴더에서는 지우고 받아 둔 원격 main 에만 남긴다
        self.assertFalse((self.work / "_posts" / "원격에만").exists())
        self.assertEqual(self.backend.same_content(self.work, text), ["_posts/원격에만/2026-11-01-KR-090001.md"])


if __name__ == "__main__":
    unittest.main()
