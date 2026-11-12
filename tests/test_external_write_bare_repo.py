"""'이 PC 에 git 이 설치돼 있고 Git 로그인이 있어도 앱이 push 하지 못한다'의 실험 시험(PCSEC1 H3 — 보안 조사 `exp/e6_direct_publish.py` 방식: 진짜 git·로컬 bare 저장소·임시 폴더만, 네트워크 0).

같은 준비(연결 `connect` → 글 만들기·검토·`approve` → `publish-pages --yes`)를 두 번 한다:
  · **꺼진 채**(이 빌드의 기본): 앱이 쓰는 진짜 기본 부품(`make_context` — 파일만 읽는 backend·무엇이든 거절하는 git 실행기)으로 한 줄도 빠짐없이 갖춰도 **git 하위 프로세스 호출 0**,
    **원격 main 불변**, 작업 폴더 불변, 글 상태 APPROVED 그대로, 거절 코드 EXTERNAL_WRITE_DISABLED. 호출 수는 `Tripwire`(하위 프로세스 전부 차단·집계)로 센다.
  · **대조**(시험이 관문을 임시로 열고 진짜 git 어댑터를 꽂은 채): 같은 준비로 `publish-pages --yes --no-wait` 가 원격 main 을 실제로 옮긴다 — 위 '0' 이 실험이 헛돌아서가 아님을 보인다.
"""
import io
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import outgoing_support as og  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
from chanceblog_desktop.service import cli, external, projects, review  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.context import make_context  # noqa: E402


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class BareRepoExperiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = ss.GitSandbox()
        cls.addClassCleanup(cls.box.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.origin, self.work = self.box.copy_into(self.base)

    def snapshot(self):
        return {"origin_main": ss.git(self.origin, "rev-parse", "main"), "work_head": ss.git(self.work, "rev-parse", "HEAD"), "work_files": ss.tree_snapshot(self.work),
                "origin_branches": ss.git(self.origin, "branch", "-a").split(), "work_status": ss.git(self.work, "status", "--porcelain")}

    def run_cli(self, ctx, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), out=out, err=err, ctx=ctx, env={}, stdin=io.StringIO(""))
        return code, out.getvalue(), err.getvalue()

    def prepare(self, ctx):
        """연결 → 글 만들기 → 검토 → 승인(모두 이 PC 안의 일) → 승인된 글의 번호."""
        code, out, err = self.run_cli(ctx, "connect", str(self.work))
        self.assertEqual(code, 0, err)
        view = projects.new_project(ctx, "원격 실험 글", ss.ko_text())
        review.request_review(ctx, view.project_id, "github_pages", pages=ss.KO_PARAMS)
        review.grant_approval(ctx, view.project_id, "github_pages")
        self.assertEqual(ss.status_of(ctx, view.project_id), "APPROVED")
        return view.project_id

    def test_with_the_gate_off_every_step_is_done_and_git_is_never_called_and_the_remote_does_not_move(self):
        self.assertIs(capabilities.EXTERNAL_WRITE, False)
        ctx = make_context(data_dir=str(self.base / "data"), env={}, expected_origin=ss.LOCAL_ORIGIN, clock=ss.Clock())          # 앱이 실제로 쓰는 기본 부품(backend·git 실행기)
        self.assertIsInstance(ctx.backend, external.LocalOnlyBackend)
        self.assertIs(ctx.git, external.refusing_git)
        before = self.snapshot()
        with og.Tripwire() as wire:                                                                                             # 하위 프로세스를 하나라도 띄우면 막고 센다
            project_id = self.prepare(ctx)
            results = [self.run_cli(ctx, "publish-pages", project_id), self.run_cli(ctx, "publish-pages", project_id, "--yes"), self.run_cli(ctx, "publish-pages", project_id, "--yes", "--no-wait"),
                       self.run_cli(ctx, "publish-pages", project_id, "--cancel", "--yes"), self.run_cli(ctx, "check-deploy", project_id), self.run_cli(ctx, "doctor", "--online")]
        for (code, out, err), label in zip(results, ("미리 보기", "--yes", "--yes --no-wait", "--cancel --yes", "check-deploy", "doctor --online")):
            self.assertEqual(code, 1, label)
            self.assertIn("EXTERNAL_WRITE_DISABLED", err, label)
        self.assertEqual(wire.calls, [], "git 하위 프로세스(그 밖의 하위 프로세스·소켓·HTTP 도) 호출이 0 이어야 한다")
        self.assertEqual(self.snapshot(), before, "원격 main·작업 폴더 HEAD·작업 폴더 파일이 하나도 바뀌지 않았다")
        self.assertEqual(ss.status_of(ctx, project_id), "APPROVED", "승인된 글의 상태도 그대로다")

    def test_with_the_gate_opened_by_a_test_the_same_steps_do_push_so_the_zero_above_is_not_an_empty_experiment(self):
        spy = ss.Spy()
        world = ss.FakeWorld()

        def adapter(**parts):
            return GitPagesBackend(git=spy, expected_origin=parts["expected_origin"], fetcher=world.fetcher, sleep=world.sleep, monotonic=world.clock)

        ss.external_write_on()
        self.addCleanup(ss.external_write_off)
        with external.registered(external.KIND_PAGES_GIT, adapter):
            ctx = make_context(data_dir=str(self.base / "data"), env={}, expected_origin=ss.LOCAL_ORIGIN, git=gitrepo.run_git, clock=ss.Clock())
            self.assertIsInstance(ctx.backend, GitPagesBackend)
            before = self.snapshot()
            project_id = self.prepare(ctx)
            spy.calls.clear()
            code, out, err = self.run_cli(ctx, "publish-pages", project_id, "--yes", "--no-wait")
        self.assertEqual(code, 0, err)
        self.assertIn("push", spy.commands(), "관문을 열고 어댑터를 꽂으면 같은 명령이 진짜로 올린다")
        after = self.snapshot()
        self.assertNotEqual(after["origin_main"], before["origin_main"], "원격 main 이 옮겨졌다")
        self.assertGreater(len(spy.calls), 0)
        self.assertEqual(ss.status_of(ctx, project_id), "PUSHED")


if __name__ == "__main__":
    unittest.main()
