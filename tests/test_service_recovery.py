"""서비스 층 — 올리다 프로그램이 죽어도 같은 도구로 복구되는지를 **진짜 git 과 진짜 프로세스 종료(`os._exit`)** 로 확인한다(로컬 bare 저장소, 네트워크 없음).

지키는 것(PUBPR — 새 흐름은 새 가지에만 올린다):
  1) 올리는 흐름의 네 지점(after_build · after_journal_built · after_push · after_journal_branch_pushed)에서 프로세스를 갑자기 끝내도 같은 명령(`publish-pages --yes`)이 새 가지를 **한 번만** 올려
     MERGE_PENDING 까지 이어 간다(같은 가지가 두 번 올라가지 않고, 원격 main 은 한 번도 움직이지 않고, 작업 폴더는 그대로다). 올리기 전에 적어 둔 `built` 기록이 있으면 같은 커밋을 이어받는다(다시 만들지 않는다).
  2) 옛 방식으로 이 PC 에 남은 commit(승인됨 + 올리지 않은 commit 하나)은 이어받지 않는다 — `--cancel --yes` 가 **이 글의 승인한 렌더링을 그대로 더한 앱의 commit 하나뿐일 때만** 되돌려 저장소를 처음 상태로 돌린다.
  3) 조금이라도 다르면(내용·다른 파일 섞임·commit 둘·앱의 commit 이 아님·다른 분야 폴더) 되돌리지도 않고 저장소를 그대로 둔다.
  4) 백업으로 되돌린 글이 이미 올라간 글을 다시 승인됨으로 되살려도 같은 가지를 이어받을 뿐 두 번째 가지를 만들지 않고, 같은 글은 두 번 공개되지 않는다.
옛 시험의 '커밋 이어받기'(commit 직후 두 지점)는 새 흐름에 로컬 commit 이 없어 사라졌다 — 같은 목적은 위 1) 의 `built` 기록 이어받기가 한다.
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
from chanceblog_desktop.publish import pages  # noqa: E402
from chanceblog_desktop.render.pages import PagesPost  # noqa: E402
from chanceblog_desktop.service import pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.backend import GitBranchBackend  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_COMMITTED, Journal, PublishRecord  # noqa: E402

CHILD = textwrap.dedent('''
    import os, sys
    sys.path.insert(0, sys.argv[1])
    sys.path.insert(0, sys.argv[2])
    import service_support as ss
    ss.external_write_on()                         # 자식 프로세스도 시험이므로 외부 Write 관문을 임시로 연다(소스 상수는 False — PCSEC1 H3)
    from chanceblog_desktop.service import cli
    from chanceblog_desktop.service.backend import GitBranchBackend
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


    class Crashing(GitBranchBackend):
        def build_branch_commit(self, repo_path, post, title):
            built = super().build_branch_commit(repo_path, post, title)
            crash("after_build")
            return built

        def push_branch(self, repo_path, built, post):
            crash("before_push")
            result = super().push_branch(repo_path, built, post)
            crash("after_push")
            return result


    real_write = Journal.write


    def write(self, record):
        real_write(self, record)
        crash("after_journal_" + record.stage)


    Journal.write = write
    backend = Crashing(expected_origin=ss.LOCAL_ORIGIN, fetcher=world.fetcher, sleep=world.sleep, monotonic=world.clock)
    ctx = make_context(data_dir=data, repo=repo, backend=backend, expected_origin=ss.LOCAL_ORIGIN, clock=clock)
    sys.exit(cli.main(argv, ctx=ctx))
''')

POINTS = ("after_build", "after_journal_built", "after_push", "after_journal_branch_pushed")
RESUMED = ("after_journal_built", "after_push", "after_journal_branch_pushed")       # 올리기 전에 적어 둔 기록이 있어 같은 커밋을 이어받는 지점


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
        self.backend = GitBranchBackend(git=self.spy, expected_origin=ss.LOCAL_ORIGIN, fetcher=ss.FakeWorld().fetcher)
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

    def branches(self):
        return sorted(ss.git(self.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/desktop").splitlines())

    def child(self, point, minutes, *argv):
        args = [sys.executable, "-X", "utf8", str(self.script), str(ss.ROOT / "src"), str(ss.ROOT / "tests"), str(self.ctx.workspace.root), str(self.work), point, str(minutes), *argv]
        env = {key: value for key, value in os.environ.items() if key not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA")}
        env["PYTHONIOENCODING"] = "utf-8"
        done = subprocess.run(args, capture_output=True, env=env, timeout=600)
        return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")

    def leftovers(self):
        return sorted(path.name for path in self.ctx.workspace.journal_dir.iterdir() if path.name.endswith(".lock") or ".stale-" in path.name) if self.ctx.workspace.journal_dir.exists() else []

    def make_orphan(self, project_id):
        """옛 방식으로 commit 직후에 프로그램이 죽은 것과 같은 상태를 이 프로세스 안에서 만든다 — 진짜 commit 은 하고 발행 기록·상태는 남기지 않는다(새 흐름은 이런 commit 을 만들지 않는다)."""
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        info = pages.commit_post(self.work, plan.post, title=plan.title, git=self.spy, expected_origin=ss.LOCAL_ORIGIN)
        return plan, info


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class CrashPointsTest(RealGit):
    """지점마다 시험 하나(저장소·데이터 폴더를 새로 만든다) — 아래에서 만들어 붙인다."""

    def crash_and_recover(self, point):
        project_id = self.approved()
        approved_text = self.rendering(project_id)
        before_remote, head = self.remote(), self.head()
        code, out, err = self.child(point, 0, "publish-pages", project_id, "--yes")
        self.assertEqual(code, 9, f"{point}: 프로세스가 그 지점에서 끝나지 않았다 | {out} | {err}")
        self.assertEqual(self.status(project_id), st.APPROVED, "죽은 뒤에는 아직 '새 가지에 올림' 을 상태에 적지 못했다")
        snapshot = (self.head(), self.remote(), ss.tree_snapshot(self.work))
        code, out, err = self.child("-", 0, "publish-pages", project_id)                           # 복구하기 전에 미리 보기는 아무것도 바꾸지 않는다
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("아직 아무것도 하지 않았습니다", out)
        self.assertEqual((self.head(), self.remote(), ss.tree_snapshot(self.work)), snapshot)
        self.assertEqual(self.status(project_id), st.APPROVED)
        code, out, err = self.child("-", 0, "publish-pages", project_id, "--yes")                   # 곧바로 같은 명령 — 죽은 작업이 남긴 잠금은 그 프로세스가 이미 없으므로 30분을 기다리지 않고 넘겨받는다
        self.assertEqual(code, 0, f"{point}: 같은 명령으로 복구되지 않았다 | {out} | {err}")
        self.assertEqual(self.status(project_id), st.MERGE_PENDING, point)
        self.assertEqual(len(self.branches()), 1, f"{point}: 새 가지가 하나만 올라갔다: {self.branches()}")
        branch = self.branches()[0]
        self.assertEqual(self.remote(), before_remote, f"{point}: 원격 main 은 한 번도 움직이지 않았다")
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{before_remote}..{branch}"), "1")
        self.assertEqual(ss.git(self.origin, "diff-tree", "--no-commit-id", "--name-status", "-r", branch), f"A\t{ss.KO_PATH}")
        self.assertEqual(ss.blob(self.origin, f"{branch}:{ss.KO_PATH}"), approved_text, "올라간 글은 승인한 렌더링 그대로다")
        self.assertEqual(self.head(), head, "연결한 저장소의 HEAD 는 그대로다")
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertFalse((self.work / ss.KO_PATH).exists(), "작업 폴더에 글 파일을 쓰지 않았다")
        self.assertEqual(self.leftovers(), [], "잠금·옮겨 둔 낡은 파일이 남지 않았다")
        self.assertIn("넘겨받았습니다", out, "죽은 작업이 남긴 낡은 잠금을 넘겨받았다고 알린다")
        self.assertIn("그 프로세스는 이미 끝나 있음", out)
        self.assertEqual(out.count("넘겨받았습니다"), 1, "알림은 한 번만 나온다")
        record = self.journal.read(project_id)
        self.assertEqual((record.stage, record.branch), ("branch_pushed", branch))
        if point in RESUMED:
            self.assertIn("이어받았습니다", out, "올리기 전에 멈춘 것을 이어받았다고 알린다")
            self.assertNotIn("받은 원격 main 위에 글 파일 하나", out, "다시 만들지 않았다")
        else:
            self.assertIn("받은 원격 main 위에 글 파일 하나", out, "기록을 적기 전에 죽었으니 새로 만든다")

    def test_after_a_crash_at_after_push_the_branch_is_already_on_the_remote_and_the_same_command_only_records_it(self):
        """올리기는 끝났는데 `branch_pushed` 기록을 쓰기 전에 죽었다 — 다시 하면 원격에 같은 끝이 이미 있어 두 번째 push 를 하지 않는다."""
        project_id = self.approved()
        code, _out, err = self.child("after_push", 0, "publish-pages", project_id, "--yes")
        self.assertEqual(code, 9, err)
        self.assertEqual(self.status(project_id), st.APPROVED, "원격에는 올라갔지만 상태는 기록하지 못했다")
        self.assertEqual(len(self.branches()), 1)
        self.assertEqual(self.journal.read(project_id).stage, "built")
        code, out, err = self.child("-", 0, "doctor")
        self.assertEqual(code, 0, err)
        code, out, err = self.child("-", 0, "publish-pages", project_id, "--yes")
        self.assertEqual(code, 0, f"{out} | {err}")
        self.assertIn("같은 가지가 이미 원격에 같은 끝으로 올라가 있어 다시 올리지 않았습니다", out)
        self.assertEqual(self.status(project_id), st.MERGE_PENDING)
        self.assertEqual(len(self.branches()), 1, "가지는 한 번만 올라갔다")


def _add(name, point):
    def run(self):
        self.crash_and_recover(point)

    run.__name__ = name
    setattr(CrashPointsTest, name, run)


for _point in POINTS:
    _add(f"test_a_crash_at_{_point}_is_recovered_by_the_same_command_and_the_branch_goes_up_once", _point)


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class AdoptionInProcessTest(RealGit):
    """옛 방식으로 이 PC 에 남은 commit 은 이어받지 않고 되돌리기만 한다(옛 '이어받기' 시험은 새 흐름의 `built` 이어받기 — 위 CrashPointsTest — 로 옮겼다)."""

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

    def assert_left_alone(self, project_id, what, *, publishes=False):
        """조금이라도 다른 앞선 commit(앱이 이어받거나 되돌릴 수 있는 고아가 아니다)은 어떤 길로도 건드리지 않는다.
        CI 빨강 고치기: 새 흐름(PUBPR)은 이 PC 의 저장소에 commit 을 만들지 않고 받은 원격 main 위에 객체로만 만들므로 앞선 commit·파일·HEAD 는 한 바이트도 바뀌지 않는다 —
        같은 글이 이 폴더에 이미 있으면 점검·올리기가 `DUPLICATE_CONTENT`(같은 주소만 겹치면 `DUPLICATE_SLUG`)로 멈추고 상태는 APPROVED 그대로이며(옛 흐름의 `PAGES_LOCAL_REPO_DIVERGED` 는 이제 나오지 않는다),
        다른 글이면(`publishes=True`) 막지 않고 앞선 commit 을 담지 않은 새 가지로 올라간다(MERGE_PENDING, 앞선 commit 의 경로와 겹치면 다음 초의 이름으로 피한다)."""
        head, remote, files = self.head(), self.remote(), ss.tree_snapshot(self.work)
        self.assertIsNone(self.backend.orphan_commit(self.work, self.rendering(project_id), "경제·일", "ko"), what)
        plan = lambda: pages_flow.plan_pages_publish(self.ctx, project_id)
        run = lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        if publishes:
            plan()
            run()
            self.assertEqual(self.status(project_id), st.MERGE_PENDING, what)
            self.assertEqual(len(self.branches()), 1, what)
            branch = self.branches()[0]
            record = self.journal.read(project_id)
            self.assertNotEqual(record.path, ss.KO_PATH, f"{what}: 앞선 commit 의 경로와 겹치는 이름은 피했다")
            self.assertEqual(ss.git(self.origin, "diff-tree", "--no-commit-id", "--name-status", "-r", branch), f"A\t{record.path}", f"{what}: 가지에는 새 글 하나뿐이다")
            self.assertIsNone(ss.blob(self.origin, f"{branch}:{ss.KO_PATH}"), f"{what}: 앞선 commit 의 글은 가지에 담기지 않았다")
        else:
            for call in (plan, run):
                error = ss.code_of(call)
                self.assertIn(error.code, ("DUPLICATE_SLUG", "DUPLICATE_CONTENT"), f"{what}: {error.code}")
            self.assertEqual(self.status(project_id), st.APPROVED, what)
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "STATUS_TRANSITION_INVALID", what)
        self.assertEqual((self.head(), self.remote(), ss.tree_snapshot(self.work)), (head, remote, files), what)
        self.assertTrue((self.work / ss.KO_PATH).exists(), what)

    def test_a_commit_with_different_content(self):
        project_id = self.approved()
        self.orphan_like(project_id, text=self.rendering(project_id) + "\n한 줄 더\n")
        self.assert_left_alone(project_id, "내용이 다른 commit", publishes=True)

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
        """새 흐름 — 발행 기록(백업에 들어 있지 않다)이 남아 있어서 되살린 '승인됨' 글은 이미 올린 같은 가지를 이어받을 뿐 두 번째 가지를 만들지 않는다. 병합까지 끝난 뒤라면 같은 내용이 main 에 있어 `DUPLICATE_CONTENT` 로 막힌다."""
        project_id = self.approved()
        backup = projects.backup_store(self.ctx)                                 # 승인된 때의 백업
        self.assertEqual(pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True).status, st.MERGE_PENDING)
        branches, remote = self.branches(), self.remote()
        self.assertEqual(len(branches), 1)
        projects.restore_store(self.ctx, backup, confirmed=True)                                 # 되돌리면 이미 올린 글이 다시 '승인됨' 이다
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.ctx.clock.advance(hours=1)                                          # 파일 이름이 달라질 시각 — 그래도 남은 발행 기록의 이름·가지를 이어받는다
        again = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((again.status, again.plan.path), (st.MERGE_PENDING, ss.KO_PATH))
        self.assertEqual((self.branches(), self.remote()), (branches, remote), "두 번째 가지를 만들지 않았다")
        _branch, commit = st.split_remote_id(_remote_id(self.ctx, project_id))
        ss.git(self.origin, "update-ref", "refs/heads/main", commit)                                 # 병합을 흉내 낸 뒤 — 같은 내용이 main 에 있다
        ss.git(self.work, "fetch", "-q", "origin")                                                  # 사용자의 git 이 받아 둔 것처럼(점검은 받아 둔 원격 main 을 본다)
        projects.restore_store(self.ctx, backup, confirmed=True)
        self.journal.remove(project_id)                                          # 발행 기록까지 잃은 최악의 경우
        self.ctx.clock.advance(hours=1)
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "DUPLICATE_CONTENT")
            self.assertEqual(error.slots["파일"], ss.KO_PATH)
        code, out, err = ss.run_cli(self.ctx, "publish-pages", project_id)
        self.assertEqual(code, 1)
        self.assertIn("DUPLICATE_CONTENT", err)
        self.assertEqual((self.branches(), self.status(project_id)), (branches, st.APPROVED), "아무것도 더 올리지 않았다")

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


def _remote_id(ctx, project_id):
    """보관함에 적힌 올린 가지의 식별자(`가지@커밋`) — 보기 객체(`show_project`)에는 이 칸이 없으므로 보관함에서 바로 읽는다."""
    with ctx.store() as store:
        return store.load(project_id).variant("github_pages").remote_id


def setUpModule():
    ss.external_write_on()                                   # 이 시험은 게시 흐름을 쓴다 — 외부 Write 관문을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    ss.external_write_off()


if __name__ == "__main__":
    unittest.main()
