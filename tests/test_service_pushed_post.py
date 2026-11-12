"""서비스 층 — 올렸지만 공개 확인이 끝나지 않은 글(PUSHED)을 지우는 일과 발행 기록이 없는 '올림' 글의 막다른 길(독립 검증 3차 낮음 2).

배경: 올린 글(`--no-wait`)을 `delete --yes` 로 지우면 발행 기록 파일도 함께 지워지고, 지우기 직전 백업으로 `restore --yes` 해도 기록은 되살아나지 않는다(기록은 백업에 들어 있지 않다).
그러면 글은 '올림(PUSHED)' 인데 기록이 없어서 `check-deploy`·`publish-pages` 는 SETTINGS_INVALID, `--cancel --yes` 는 PUBLISH_ALREADY_PUSHED("check-deploy 로 마친다")로 서로를 가리키며 막혔다.

해법(가장 단순하고 데이터를 만들어 내지 않는 쪽): ① 발행 기록이 있는 PUSHED 글은 지우지 않고 '먼저 `check-deploy` 로 마친 뒤 지운다' 고 알린다(막다른 길을 만들지 않는다).
② 그래도 이미 기록 없는 PUSHED 글이 있으면(오래된 백업으로 되돌렸을 때 생긴다) 어느 명령도 서로를 가리키지 않고 '지운다' 는 한 가지 출구만 알리며, 그 글은 지울 수 있다(잃는 것이 없다 — 올라간 글은 저장소에 그대로 있다).

지키는 것:
  1) 기록이 있는 PUSHED 글은 지우지 않는다(STATUS_TRANSITION_INVALID — 안내에 `check-deploy 글번호`), 아무것도 바꾸지 않고 백업도 만들지 않는다. 안내대로 마치면(PUBLISHED) 지울 수 있고, 지우기 직전 백업으로 되살려도 막히지 않는다.
  2) 기록이 없는 PUSHED 글: `check-deploy`·`publish-pages`(미리 보기·`--yes`)·`--cancel --yes`·`doctor` 가 모두 같은 출구(`delete 글번호 --yes`)를 말하고 서로를 가리키지 않으며, 그대로 하면 풀린다(원격은 그대로).
  3) 읽을 수 없는 기록은 지우지 않고 SETTINGS_INVALID 로 알린다(있는데 못 읽는 것과 없는 것을 가린다).
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.service import pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.journal import Journal  # noqa: E402


class FakeFlowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)
        self.journal = Journal(self.ctx.workspace.journal_dir)

    def pushed(self):
        project_id = ss.make_approved(self.ctx)
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True, wait=False)
        self.assertEqual((report.status, ss.status_of(self.ctx, project_id)), (st.PUSHED, st.PUSHED))
        self.assertIsNotNone(self.journal.read(project_id))
        return project_id

    def listed(self):
        return [row.project_id for row in projects.list_projects(self.ctx)]

    def test_a_pushed_post_with_its_record_is_not_deleted_and_nothing_changes(self):
        project_id = self.pushed()
        before = (self.journal.read(project_id), self.listed())
        error = ss.code_of(projects.delete_project, self.ctx, project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"], error.slots["요청 상태"]), ("STATUS_TRANSITION_INVALID", st.PUSHED, "삭제"))
        self.assertIn(f"`check-deploy {project_id[:8]}`", error.detail, "안내에 마치는 명령이 그대로 들어 있다")
        self.assertEqual((self.journal.read(project_id), self.listed()), before, "글도 발행 기록도 그대로다")
        self.assertFalse((self.ctx.workspace.backups_dir / "before-delete").exists(), "지우지 않았으니 지우기 직전 백업도 만들지 않았다")

    def test_after_the_public_check_the_post_can_be_deleted_and_the_note_says_the_published_post_stays(self):
        project_id = self.pushed()
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)
        deleted, note = projects.delete_project(self.ctx, project_id, confirmed=True)
        self.assertEqual(deleted, project_id)
        self.assertEqual(self.listed(), [])
        self.assertIn("이미 올라간 글은 연결한 저장소에 그대로 있습니다", note)
        self.assertIn("`restore 그파일 --yes`", note, "되살리는 명령도 확인 표시가 있어야 한다")

    def test_a_post_that_was_never_pushed_gets_no_such_note(self):
        view = projects.new_project(self.ctx, "올리지 않은 글", ss.ko_text())
        deleted, note = projects.delete_project(self.ctx, view.project_id, confirmed=True)
        self.assertNotIn("이미 올라간 글", note)
        self.assertIn("`restore 그파일 --yes`", note)

    def test_a_pushed_post_that_already_lost_its_record_can_be_deleted(self):
        project_id = self.pushed()
        self.journal.remove(project_id)                      # 막다른 길에 이미 들어선 글 — 지워도 잃는 것이 없다
        self.assertIsNone(self.journal.read(project_id))
        deleted, note = projects.delete_project(self.ctx, project_id, confirmed=True)
        self.assertEqual((deleted, self.listed()), (project_id, []))
        self.assertIn("이미 올라간 글은 연결한 저장소에 그대로 있습니다", note)

    def test_a_pushed_post_whose_record_cannot_be_read_is_left_alone(self):
        project_id = self.pushed()
        record = self.ctx.workspace.journal_dir / f"{project_id}.json"
        record.write_text("{깨짐", encoding="utf-8")
        error = ss.code_of(projects.delete_project, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "SETTINGS_INVALID", "있는데 읽을 수 없는 기록을 '없다' 로 보고 지우지 않는다")
        self.assertEqual((self.listed(), record.read_text(encoding="utf-8")), ([project_id], "{깨짐"))

    def test_the_other_unfinished_state_is_still_refused_as_before(self):
        project_id = ss.make_approved(self.ctx)
        self.backend.push_errors = [ss.AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(ss.AppError):
            pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        error = ss.code_of(projects.delete_project, self.ctx, project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.COMMITTED))

    def exit_door(self, text, project_id):
        """안내에 적힌 출구 — `delete 번호 --yes` 한 가지이고, 어느 말도 `check-deploy` 로 마치라고 하지 않는다(순환이 아니다)."""
        self.assertIn(f"`delete {project_id[:8]} --yes`", text)
        self.assertNotRegex(text, r"check-deploy [0-9a-f]{8}` 로 공개 확인을 마친다", "막힌 명령을 다시 가리키지 않는다")

    def test_without_its_record_every_command_names_the_same_way_out_and_none_points_at_another(self):
        project_id = self.pushed()
        self.journal.remove(project_id)
        for label, call in (("check-deploy", lambda: pages_flow.check_pages_deploy(self.ctx, project_id)),
                            ("미리 보기", lambda: pages_flow.preview_publish(self.ctx, project_id)),
                            ("올리기 --yes", lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True))):
            with self.subTest(command=label):
                error = ss.code_of(call)
                self.assertEqual(error.code, "SETTINGS_INVALID")
                self.exit_door(error.detail, project_id)
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "PUBLISH_ALREADY_PUSHED")
        self.exit_door(error.detail, project_id)
        code, out, err = ss.run_cli(self.ctx, "doctor")
        self.assertIn("발행 기록 파일이 없어 공개 확인을 이어갈 수 없습니다", out)
        self.exit_door(out, project_id)
        line = next(item for item in out.splitlines() if "이어서 처리할 글" in item)
        self.assertNotIn("로 확인합니다", line, "doctor 도 check-deploy 로 마치라고 하지 않는다")

    def test_with_its_record_cancel_and_doctor_still_say_to_finish_with_check_deploy(self):
        project_id = self.pushed()
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "PUBLISH_ALREADY_PUSHED")
        self.assertIn(f"`check-deploy {project_id[:8]}` 로 공개 확인을 마친다", error.detail)
        code, out, err = ss.run_cli(self.ctx, "doctor")
        self.assertIn(f"`check-deploy {project_id[:8]}` 로 확인합니다", out)

    def test_a_record_that_cannot_be_read_is_not_taken_for_a_missing_one(self):
        """있는데 못 읽는 기록은 '없는 기록' 이 아니다 — 취소·점검은 지우라고 하지 않고(기록을 읽을 수 있게 되는 쪽이 먼저다) 읽는 명령이 SETTINGS_INVALID 로 알린다."""
        project_id = self.pushed()
        self.assertFalse(self.journal.missing(project_id))
        (self.ctx.workspace.journal_dir / f"{project_id}.json").write_text("{깨짐", encoding="utf-8")
        self.assertFalse(self.journal.missing(project_id), "읽을 수 없어도 파일은 있다")
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "PUBLISH_ALREADY_PUSHED")
        self.assertNotIn("delete", error.detail)
        self.assertEqual(ss.code_of(pages_flow.check_pages_deploy, self.ctx, project_id).code, "SETTINGS_INVALID")
        code, out, err = ss.run_cli(self.ctx, "doctor")
        self.assertNotIn(f"delete {project_id[:8]}", out)
        self.journal.remove(project_id)
        self.assertTrue(self.journal.missing(project_id), "파일이 없으면 없다")
        self.assertTrue(self.journal.missing("no-such-post"))

    def test_a_committed_post_without_its_record_keeps_its_own_old_message(self):
        """이 묶음은 PUSHED 만 다룬다 — COMMITTED 인데 기록이 없는 글의 안내는 그대로다(기록이 없다는 사실만)."""
        project_id = ss.make_approved(self.ctx)
        self.backend.push_errors = [ss.AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(ss.AppError):
            pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.journal.remove(project_id)
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual((error.code, error.detail), ("SETTINGS_INVALID", "이어서 올릴 발행 기록 파일이 없다"))


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class RealFlowTest(unittest.TestCase):
    """진짜 git(로컬 bare 저장소)으로 — 올림 → 지우기 시도·복구 → 안내대로 하면 풀린다."""

    @classmethod
    def setUpClass(cls):
        cls.box = ss.GitSandbox()
        cls.addClassCleanup(cls.box.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin, self.work = self.box.copy_into(self.tmp)
        self.world = ss.FakeWorld()
        backend = GitPagesBackend(git=ss.Spy(), expected_origin=ss.LOCAL_ORIGIN, fetcher=self.world.fetcher, sleep=self.world.sleep, monotonic=self.world.clock)
        self.ctx = ss.make_ctx(self.tmp, backend=backend, repo=None, git=ss.Spy())
        self.ctx.expected_origin = ss.LOCAL_ORIGIN
        self.ctx.settings.save_repo_path(str(self.work))
        self.journal = Journal(self.ctx.workspace.journal_dir)

    def cli(self, *argv):
        code, out, err = ss.run_cli(self.ctx, *argv)
        return code, out + err

    def remote(self):
        return ss.git(self.origin, "rev-parse", "main"), ss.git(self.origin, "ls-tree", "-r", "--name-only", "main", "--", "_posts").splitlines()

    def pushed(self):
        project_id = ss.make_approved(self.ctx)
        self.assertEqual(pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True, wait=False).status, st.PUSHED)
        return project_id

    def command_in(self, text, verb):
        found = re.search(r"`(" + verb + r" [0-9a-f]{8}(?: --yes)?)`", text)
        self.assertIsNotNone(found, f"안내에 `{verb} …` 명령이 있어야 한다: {text[-400:]}")
        return found.group(1).split()

    def test_deleting_a_pushed_post_is_refused_and_following_the_advice_leads_to_a_post_that_can_be_deleted_and_restored(self):
        project_id = self.pushed()
        remote = self.remote()
        self.assertIsNotNone(self.journal.read(project_id))
        code, text = self.cli("delete", project_id, "--yes")
        self.assertEqual(code, 1, text)
        self.assertIn("STATUS_TRANSITION_INVALID", text)
        self.assertEqual((ss.status_of(self.ctx, project_id), self.remote()), (st.PUSHED, remote))
        self.assertIsNotNone(self.journal.read(project_id), "지우지 않았으니 발행 기록도 그대로다")
        code, text2 = self.cli(*self.command_in(text, "check-deploy"))                      # 안내대로
        self.assertEqual(code, 0, text2)
        self.assertEqual(ss.status_of(self.ctx, project_id), st.PUBLISHED)
        code, text3 = self.cli("delete", project_id, "--yes")
        self.assertEqual(code, 0, text3)
        self.assertEqual(projects.list_projects(self.ctx), [])
        saved = sorted((self.ctx.workspace.backups_dir / "before-delete").glob("*.db"))
        self.assertEqual(len(saved), 1)
        code, text4 = self.cli("restore", str(saved[0]), "--yes")                               # 되살려도 막히지 않는다(공개된 글이라 기록이 필요 없다)
        self.assertEqual(code, 0, text4)
        self.assertEqual(ss.status_of(self.ctx, project_id), st.PUBLISHED)
        code, text5 = self.cli("check-deploy", project_id)
        self.assertEqual(code, 0, text5)
        self.assertIn("이미 공개된 글입니다", text5)
        self.assertEqual(self.remote(), remote, "이 모든 것에서 원격은 한 번도 바뀌지 않았다")

    def test_a_post_sent_back_to_pushed_by_an_old_backup_has_one_way_out_and_it_works(self):
        project_id = self.pushed()
        code, out = self.cli("backup")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.cli("check-deploy", project_id)[0], 0)
        self.assertEqual(ss.status_of(self.ctx, project_id), st.PUBLISHED)
        self.assertIsNone(self.journal.read(project_id), "공개가 확인되어 발행 기록을 지웠다")
        old = projects.list_backups(self.ctx)[0]                                           # 올림 상태일 때의 백업
        code, text = self.cli("restore", str(old), "--yes")
        self.assertEqual(code, 0, text)
        self.assertEqual(ss.status_of(self.ctx, project_id), st.PUSHED, "되돌렸더니 '올림' 인데 기록은 없다")
        self.assertIsNone(self.journal.read(project_id))
        remote = self.remote()
        door = None
        for argv in (("check-deploy", project_id), ("publish-pages", project_id), ("publish-pages", project_id, "--yes"), ("publish-pages", project_id, "--cancel", "--yes")):
            code, text = self.cli(*argv)
            self.assertEqual(code, 1, (argv, text))
            self.assertRegex(text, r"SETTINGS_INVALID|PUBLISH_ALREADY_PUSHED")
            self.assertNotRegex(text, r"check-deploy [0-9a-f]{8}` 로 공개 확인을 마친다", f"{argv[0]}: 막힌 명령을 다시 가리킨다")
            found = self.command_in(text, "delete")
            door = door or found
            self.assertEqual(found, door, "모든 명령이 같은 출구를 말한다")
        code, text = self.cli("doctor")
        self.assertIn(" ".join(door), text)
        code, text = self.cli(*door)                                                        # 안내대로
        self.assertEqual(code, 0, text)
        self.assertEqual(projects.list_projects(self.ctx), [])
        self.assertEqual(self.remote(), remote, "올라간 글은 그대로다 — 이 앱은 올라간 글을 지우지 않는다")
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "")


def setUpModule():
    ss.external_write_on()                                   # 이 시험은 게시 흐름을 쓴다 — 외부 Write 관문을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    ss.external_write_off()


if __name__ == "__main__":
    unittest.main()
