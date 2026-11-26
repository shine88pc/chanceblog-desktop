"""전 과정 — 승인 → 새 가지 → (시험이 main 에 병합을 흉내) → 병합 확인 → 가짜 공개 확인 → `PUBLISHED` 를 로컬 bare 저장소와 진짜 git 으로 한 번에 돌린다(PUBPR 설계서 PT-60, 외부 접속 0).

지키는 것(설계서 불변 — '원격 `main` 은 한 번도 앱 때문에 움직이지 않는다'):
  · 원격 main 의 커밋 번호를 단계마다 `git rev-parse` 로 기록해, **시험 자신이 병합을 흉내 내는 한 곳에서만** 바뀌고 앱의 어떤 단계(올리기·병합 확인·공개 확인·정리)에서도 안 바뀜을 보인다.
  · 앱이 부른 네트워크 git 명령은 전부 정해진 모양(받기·가지 확인·가지 올리기)이고, 올리기의 목적지는 모두 `desktop/post-…` 가지다.
  · 병합 방식(병합 커밋·squash·rebase)이 무엇이든 내용으로 알아본다. 발행 기록 파일이 없어져도(백업 복원) 가지 이름·승인한 글의 머리말로 이어 간다. '병합하지 않기로 했어요' 는 원격에서 아무것도 지우지 않는다.
"""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402
from test_service_pages_git import GitBase  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
from chanceblog_desktop.service import pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.journal import Journal  # noqa: E402


def setUpModule():
    ss.external_write_on()


def tearDownModule():
    ss.external_write_off()


class FlowTest(GitBase):
    def helper(self, name):
        target = self.tmp / name
        ss.git(self.tmp, "clone", "-q", str(self.origin), name)
        for key, value in (("core.autocrlf", "false"), ("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            ss.git(target, "config", key, value)
        return target

    def merge_the_way(self, method, branch):
        """GitHub 의 세 병합 단추를 흉내 낸다(시험 준비 — 사람이 하는 일): 일반 병합·squash·rebase. 결과를 원격 main 에 올린다."""
        other = self.helper(f"merger_{method}")
        ss.git(other, "fetch", "-q", "origin", f"refs/heads/{branch}:refs/remotes/origin/pr")
        if method == "merge":
            ss.git(other, "merge", "-q", "--no-ff", "-m", "병합", "origin/pr")
        elif method == "squash":
            ss.git(other, "merge", "-q", "--squash", "origin/pr")
            ss.git(other, "commit", "-q", "-m", "squash")
        else:
            ss.git(other, "cherry-pick", "origin/pr")
        ss.git(other, "push", "-q", "origin", "HEAD:refs/heads/main")

    def network_calls(self):
        return [call for call in self.spy.calls if call[0] in ("fetch", "push", "ls-remote", "pull", "clone")]

    def full_flow(self, method):
        """승인 → 가지 → 병합 확인(아직) → (사람이 병합 — 시험이 흉내) → 병합 확인(됨) → 가짜 공개 확인 → PUBLISHED. 원격 main 은 시험의 병합 한 곳에서만 움직인다."""
        project_id = self.approved()
        trace = [("시작", self.remote_main())]
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.MERGE_PENDING)
        branch, commit = self.branch_of(project_id)
        trace.append(("올림", self.remote_main()))
        before_merge = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual((before_merge.status, self.status(project_id)), (st.MERGE_PENDING, st.MERGE_PENDING))
        self.assertIn("아직 병합되지 않았", " ".join(before_merge.notes + before_merge.steps))
        trace.append(("병합 확인(아직)", self.remote_main()))
        self.bot_pushes(name="_posts/Bot/2026-11-03-KR-090000.md", text="봇 글\n")            # 병합 전에 main 이 앞서간다 — 병합 방식이 실제로 갈린다
        self.merge_the_way(method, branch)
        merged = self.remote_main()
        trace.append(("사람이 병합(시험)", merged))
        self.assertEqual(ss.blob(self.origin, f"main:{ss.KO_PATH}"), self.stored_rendering(project_id), "병합 방식과 상관없이 같은 내용이 main 에 있다")
        after = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual((after.status, self.status(project_id)), (st.PUSHED, st.PUSHED))
        trace.append(("병합 확인(됨)", self.remote_main()))
        record = Journal(self.ctx.workspace.journal_dir).read(project_id)
        self.assertEqual(record.stage, "pushed")
        self.assertEqual(ss.blob(self.origin, f"{record.commit}:{ss.KO_PATH}"), self.stored_rendering(project_id), "기록한 커밋은 글을 처음 담은 main 커밋이다")
        done = pages_flow.check_pages_deploy(self.ctx, project_id)
        self.assertEqual((done.status, done.url), (st.PUBLISHED, ss.KO_URL))
        trace.append(("공개 확인", self.remote_main()))
        values = [value for _name, value in trace]
        self.assertEqual(values[:3], [self.main0] * 3, f"앱의 어느 단계도 main 을 움직이지 않았다: {trace[:3]}")
        self.assertTrue(all(value == merged for value in values[3:]), f"병합 뒤 앱의 단계는 main 을 안 움직인다: {trace}")
        self.assertEqual(len(set(values)), 2, trace)
        calls = self.network_calls()
        self.assertTrue(calls)
        for call in calls:
            self.assertIsNotNone(gitrepo.network_shape(call), f"정해진 모양이 아닌 네트워크 명령: {call}")
            if call[0] == "push":
                self.assertTrue(call[-1].split(":", 1)[1].startswith("refs/heads/desktop/post-"), call)
        self.assertIsNone(Journal(self.ctx.workspace.journal_dir).read(project_id))

    def test_full_flow_on_local_bare_repo_from_approval_to_merge_check_with_a_simulated_merge(self):
        """PT-60 — 일반 병합(병합 커밋)으로 흉내 낸 전 과정. squash·rebase 가 병합 확인에서 같은 `merged` 로 읽히는지는 어댑터 시험(`test_pages_branch_build.MergeCheckTest`)이 세 방식으로 본다 —
        병합 확인은 방식이 아니라 **내용**을 보므로 흐름 시험은 한 방식으로 충분하다(이 PC 에서 진짜 git 시험이 느려서 같은 흐름을 세 번 돌리지 않는다)."""
        self.full_flow("merge")

    def test_remote_id_alone_rebuilds_the_path_after_a_restore_without_the_journal(self):
        """PT-27 — 백업을 되돌려 발행 기록 파일이 없어도 보관함의 식별자(`가지@커밋`)와 승인한 글의 머리말로 글 경로를 다시 만들어 병합 확인이 이어진다."""
        project_id = self.approved()
        pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        branch, commit = self.branch_of(project_id)
        journal = Journal(self.ctx.workspace.journal_dir)
        self.assertIsNotNone(journal.read(project_id))
        (self.ctx.workspace.journal_dir / f"{project_id}.json").unlink()
        self.assertIsNone(journal.read(project_id))
        self.merge_into_main(project_id)
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual((report.status, self.status(project_id)), (st.PUSHED, st.PUSHED))
        self.assertEqual(journal.read(project_id).path, ss.KO_PATH, "기록을 식별자에서 다시 만들어 이어 갔다")
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)

    def test_abandon_marks_failed_and_deletes_nothing_remote(self):
        """PT-25 — '병합하지 않기로 했어요' 는 상태만 바꾼다: 원격의 가지·글·main 은 한 바이트도 안 변하고 작업 폴더도 그대로다."""
        project_id = self.approved()
        pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        branch, commit = self.branch_of(project_id)
        refs_before = ss.git(self.origin, "for-each-ref", "--format=%(refname) %(objectname)")
        work_before = (ss.tree_snapshot(self.work), self.head(), ss.git(self.work, "status", "--porcelain", "--untracked-files=all"))
        self.spy.calls.clear()
        report = pages_flow.abandon_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, self.status(project_id)), (st.PUBLISH_FAILED, st.PUBLISH_FAILED))
        self.assertEqual(projects.show_project(self.ctx, project_id).variant("github_pages").error_code, "PAGES_MERGE_ABANDONED")
        self.assertEqual(ss.git(self.origin, "for-each-ref", "--format=%(refname) %(objectname)"), refs_before, "원격의 어떤 참조도 지우거나 바꾸지 않았다")
        self.assertEqual(ss.git(self.origin, "rev-parse", branch), commit)
        self.assertEqual((ss.tree_snapshot(self.work), self.head(), ss.git(self.work, "status", "--porcelain", "--untracked-files=all")), work_before)
        self.assertEqual(self.spy.calls, [], "정리는 git 을 한 번도 부르지 않는다")
        self.assertIsNone(Journal(self.ctx.workspace.journal_dir).read(project_id))
        self.assertIn("GitHub 에 그대로 남아 있습니다", " ".join(report.steps))
        self.assertEqual(ss.code_of(pages_flow.abandon_pages_publish, self.ctx, project_id, confirmed=True).code, "STATUS_TRANSITION_INVALID", "두 번째 정리는 할 일이 없다")

    def test_a_merge_that_changed_the_text_is_reported_and_the_public_check_is_never_made(self):
        """PT-24 의 흐름 쪽 — 병합 전에 PR 에서 글이 고쳐졌으면 `PAGES_MERGE_DIFFERENT` 로 멈추고 공개 주소는 요청하지 않는다. 상태는 그대로다."""
        project_id = self.approved()
        pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.bot_pushes(name=ss.KO_PATH, text="---\nlayout: post\n---\n병합 전에 고쳐진 글\n")
        main_now = self.remote_main()
        error = ss.code_of(pages_flow.merge_check_pages, self.ctx, project_id)
        self.assertEqual(error.code, "PAGES_MERGE_DIFFERENT")
        self.assertEqual(self.status(project_id), st.MERGE_PENDING)
        self.assertEqual(self.world.requests, [])
        self.assertEqual(self.remote_main(), main_now)
        self.assertEqual(ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id).code, "STATUS_TRANSITION_INVALID", "병합을 확인하기 전에는 공개 확인을 하지 않는다")
        self.assertEqual(self.world.requests, [])

    def test_editing_the_text_after_the_push_does_not_change_what_the_merge_check_compares(self):
        """PT-21 의 흐름 쪽 — 올라간 것은 승인한 옛 글이다: 원고를 고쳐도 병합 확인은 승인한 글과 견주고(그래서 병합된 글이 맞으면 통과) 고쳤다는 안내가 붙는다."""
        project_id = self.approved()
        pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        ss.inject_text(self.ctx, project_id, text=ss.ko_text(extra="나중에 고친 문단입니다. "))
        self.merge_into_main(project_id)
        report = pages_flow.merge_check_pages(self.ctx, project_id)
        self.assertEqual(report.status, st.PUSHED)
        self.assertIn("원고를 고쳤어요", " ".join(report.notes))

    def history_rewrite(self):
        """운영자가 원격 main 의 이력을 다시 쓴다(비밀을 지우려고 옛 커밋을 없애는 경우 등 — 시험 준비, 앱 코드를 거치지 않는다) — 같은 트리를 부모 없는 새 뿌리 커밋으로 바꾼다 → 새 main."""
        tree = ss.git(self.origin, "rev-parse", "main^{tree}")
        new = ss.git(self.origin, "-c", "user.name=op", "-c", "user.email=op@example.com", "-c", "commit.gpgsign=false", "commit-tree", tree, "-m", "이력을 다시 씀")
        ss.git(self.origin, "update-ref", "refs/heads/main", new)
        self.assertNotEqual(new, self.main0)
        return new

    def stopped_at_the_push(self, project_id):
        """올리기가 연결 문제로 막혀 `built` 기록(만들어 둔 커밋 — 부모는 그때의 main)이 남은 상태 → 그 기록."""
        self.use(ss.Spy(fail={"push"}))
        self.assertEqual(ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True).code, "GIT_PUSH_NETWORK")
        record = Journal(self.ctx.workspace.journal_dir).read(project_id)
        self.assertEqual((record.stage, record.base, self.remote_branches()), ("built", self.main0, ["main"]))
        return record

    def assert_rebuilt_on_the_new_main(self, project_id, record, new_main, report):
        branch, commit = self.branch_of(project_id)
        self.assertEqual((report.status, self.status(project_id)), (st.MERGE_PENDING, st.MERGE_PENDING))
        self.assertEqual((branch, report.plan.path), (record.branch, record.path), "파일 이름·가지 이름은 앞선 실행의 것 그대로다")
        self.assertNotEqual(commit, record.commit, "옛 커밋을 이어받지 않고 다시 만들었다")
        self.assertEqual(ss.git(self.origin, "rev-parse", f"{branch}^"), new_main, "가지는 새 main 한 커밋 위에 있다")
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{new_main}..{branch}"), "1")
        reaches_old = subprocess.run(["git", "-C", str(self.origin), "merge-base", "--is-ancestor", record.base, branch], capture_output=True).returncode == 0
        self.assertFalse(reaches_old, "옛 main(지운 이력)은 올라간 가지에서 닿지 않는다 — 지운 옛 이력이 새 공개 가지로 되살아나지 않았다")
        self.assertTrue(ss.git(self.origin, "log", "-1", "--format=%s", branch).startswith("글 올리기(데스크톱 앱):"), "가지 끝은 앱이 만든 글 커밋이다")
        self.assertEqual(self.remote_main(), new_main, "원격 main 은 운영자가 다시 쓴 그대로다 — 앱은 한 번도 움직이지 않았다")
        self.assertEqual(sorted(self.remote_branches()), sorted(["main", branch]), "새 가지는 하나뿐이다")
        self.assertEqual(Journal(self.ctx.workspace.journal_dir).read(project_id).commit, commit)

    def test_after_a_history_rewrite_the_retry_builds_again_on_the_new_main_and_the_removed_history_never_comes_back(self):
        """M-1 의 흐름 쪽(독립 검증 S 의 탐침과 같은 일) — 올리다 막혀 `built` 기록이 남았고 그 사이 운영자가 main 의 이력을 다시 썼다. 같은 명령을 다시 하면 옛 커밋을 올리지 않고 새 main 위에서 다시 만들어 올린다 —
        올라간 가지에 옛 main 이 없다. 이 PC 가 아직 새 main 을 받아 두지 않았어도(받아 둔 기록은 낡았다) 올리기 직전의 받기가 알아본다."""
        project_id = self.approved()
        record = self.stopped_at_the_push(project_id)
        new_main = self.history_rewrite()
        self.use(ss.Spy())
        self.ctx.clock.advance(hours=1)
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.resumed, plan.stale_base), (record, False), "받아 둔 기록은 낡아 아직 알 수 없다 — 올리기 직전의 받기가 마지막 문이다")
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assert_rebuilt_on_the_new_main(project_id, record, new_main, report)
        steps = " ".join(report.steps)
        self.assertIn("올리지 않았습니다", steps)
        self.assertNotIn("이어받았습니다", steps, "다시 만든 것을 이어받았다고 알리지 않는다")
        self.assertEqual([call[0] for call in self.spy.calls if call[0] == "push"], ["push"], "푸시는 다시 만든 커밋 하나뿐이다")
        self.assertNotIn(record.commit, " ".join(" ".join(call) for call in self.spy.calls if call[0] == "push"), "옛 커밋은 보내지 않았다")

    def test_when_the_received_main_already_shows_the_rewrite_the_old_commit_is_not_even_tried(self):
        """M-1 의 점검·이어받기 쪽 — 이 PC 가 새 main 을 이미 받아 두었으면(사용자가 자기 git 으로 받았다) 점검이 '이어받지 않고 다시 만든다' 고 알리고, 올리기는 옛 커밋을 올리기 단계에 넘기지도 않는다."""
        project_id = self.approved()
        record = self.stopped_at_the_push(project_id)
        new_main = self.history_rewrite()
        ss.git(self.work, "fetch", "-q", "origin")                         # 사용자의 git 이 새 main 을 받아 두었다
        self.assertEqual(ss.git(self.work, "rev-parse", "refs/remotes/origin/main"), new_main)
        self.use(ss.Spy())
        self.ctx.clock.advance(hours=1)
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.resumed, plan.stale_base, plan.path, plan.branch), (record, True, record.path, record.branch))
        self.assertTrue(any("이어받지 않고" in line for line in plan.actions), plan.actions)
        code, out, err = ss.run_cli(self.ctx, "publish-pages", project_id)
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("이어받지 않고", out)
        self.assertIn("아직 아무것도 하지 않았습니다", out)
        self.assertEqual((self.status(project_id), self.remote_branches(), self.remote_main()), (st.APPROVED, ["main"], new_main), "미리 보기는 아무것도 바꾸지 않는다")
        self.spy.calls.clear()
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assert_rebuilt_on_the_new_main(project_id, record, new_main, report)
        steps = " ".join(report.steps)
        self.assertIn("이어받지 않았습니다", steps)
        self.assertNotIn("이어받았습니다", steps)
        pushes = [call for call in self.spy.calls if call[0] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertNotIn(record.commit, pushes[0][-1], "옛 커밋은 올리기 단계에 넘기지도 않았다")


if __name__ == "__main__":
    unittest.main()
