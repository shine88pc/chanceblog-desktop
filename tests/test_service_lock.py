"""서비스 층 — 같은 글을 두 곳에서 동시에 올리지 못하게 하는 잠금(`service/lock.py`)과, 실패한 쪽이 성공한 쪽의 발행 기록을 지우지 못하게 하는 규칙 시험.

지키는 것:
  1) 잠금은 글마다 `publish/<글번호>.lock` 을 `O_EXCL` 로 만들고(프로세스 번호·시작 시각·실행 번호), 못 잡으면 PUBLISH_IN_PROGRESS 로 멈추며 아무것도 바꾸지 않는다.
  2) 정상 종료·실패·Ctrl+C 어느 쪽이든 푼다. 풀 때는 자기 실행 번호인 잠금만 지운다.
  3) 시작한 지 30분(기다리는 시간이 길면 그 시간 + 15분)이 넘은 잠금은 낡은 것으로 보고 넘겨받으며 그 사실을 알린다. 미리 보기(dry run)는 잠그지도 않고 아무것도 쓰지 않는다.
  4) 올리기·되돌리기·공개 확인은 점검 전에 잠금을 잡는다. 같은 글을 올리는 중에 다른 작업이 끼어들어도 첫 작업의 발행 기록은 그대로다.
  5) 실패 경로의 발행 기록 지우기는 이 실행이 쓴 기록과 똑같을 때만 한다(`Journal.remove(only=…)`).
  6) **진짜 프로세스 둘**이 같은 글을 동시에 올려도 하나만 올리고 다른 하나는 아무것도 바꾸지 않고 멈춘다(진짜 git, 로컬 bare 저장소).
"""
import errno
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import lock as lockmod  # noqa: E402
from chanceblog_desktop.service import pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_COMMITTED, STAGE_PUSHED, Journal, PublishRecord  # noqa: E402

PID = "proj-1"


class LockBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.folder = self.tmp / "publish"
        self.clock = ss.Clock()

    def make(self, project_id=PID, **kwargs):
        return lockmod.PublishLock(self.folder, project_id, now=self.clock, **kwargs)

    def file(self, project_id=PID):
        return self.folder / f"{project_id}.lock"


class LockFileTest(LockBase):
    def test_the_lock_file_is_made_with_the_process_the_start_time_and_a_run_number_and_released(self):
        held = self.make().acquire()
        data = json.loads(self.file().read_text(encoding="utf-8"))
        self.assertEqual(sorted(data), ["host", "max_seconds", "pid", "project_id", "run", "schema", "started"])
        self.assertEqual(data["host"], held.host)
        self.assertEqual((data["pid"], data["started"], data["max_seconds"], data["project_id"]), (os.getpid(), "2026-11-02T01:30:12Z", 1800, PID))
        self.assertRegex(data["run"], r"^[0-9a-f]{32}$")
        held.release()
        self.assertFalse(self.file().exists())
        self.assertEqual(held.release_note, "")

    def test_a_second_lock_on_the_same_post_is_refused_and_changes_nothing(self):
        first = self.make().acquire()
        before = self.file().read_bytes()
        second = self.make()
        error = ss.code_of(second.acquire)
        self.assertEqual(error.code, "PUBLISH_IN_PROGRESS")
        self.assertIn("2026-11-02 10:30:12 한국 시각", error.slots["시작"])
        self.assertIn(str(os.getpid()), error.slots["시작"])
        self.assertEqual(self.file().read_bytes(), before, "첫 작업의 잠금은 그대로다")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"{PID}.lock"], "다른 파일을 만들지 않았다")
        second.release()                                            # 잡지 못한 쪽이 풀어도 첫 작업의 잠금은 그대로다
        self.assertEqual(self.file().read_bytes(), before)
        first.release()
        self.assertTrue(self.make().acquire().held, "풀린 뒤에는 잡을 수 있다")

    def test_two_different_posts_do_not_block_each_other(self):
        first, second = self.make("post-a").acquire(), self.make("post-b").acquire()
        self.assertTrue(first.held and second.held)
        first.release()
        second.release()

    def test_release_removes_only_its_own_lock(self):
        held = self.make().acquire()
        other = {"schema": 1, "project_id": PID, "pid": 4321, "started": "2026-11-02T01:30:12Z", "max_seconds": 1800, "run": "0" * 32}
        self.file().write_text(json.dumps(other), encoding="utf-8")               # 낡은 것으로 보고 다른 작업이 넘겨받은 잠금
        held.release()
        self.assertTrue(self.file().exists(), "남의 잠금은 지우지 않는다")
        self.assertEqual(json.loads(self.file().read_text(encoding="utf-8"))["run"], "0" * 32)
        self.assertIn("내 잠금이 아니어서", held.release_note)

    def test_releasing_twice_or_without_holding_is_harmless(self):
        held = self.make().acquire()
        held.release()
        held.release()
        self.make().release()
        self.assertFalse(self.file().exists())

    def test_the_lock_is_released_after_an_error_and_after_a_keyboard_interrupt(self):
        ctx = ss.make_ctx(self.tmp)
        for problem in (AppError("GIT_PUSH_NETWORK"), KeyboardInterrupt()):
            with self.subTest(problem=type(problem).__name__):
                with self.assertRaises(type(problem)):
                    with lockmod.publish_lock(ctx, PID):
                        self.assertTrue((ctx.workspace.journal_dir / f"{PID}.lock").exists(), "블록 안에서는 잠겨 있다")
                        raise problem
                self.assertFalse((ctx.workspace.journal_dir / f"{PID}.lock").exists())

    def test_a_half_written_lock_is_removed_when_the_write_fails(self):
        with mock.patch.object(lockmod.os, "write", side_effect=OSError(errno.ENOSPC, "No space left")):
            error = ss.code_of(self.make().acquire)
        self.assertEqual(error.code, "DISK_FULL")
        self.assertFalse(self.file().exists(), "만들다 만 잠금이 남아 다음 실행을 막지 않는다")

    def test_a_post_number_that_could_leave_the_folder_is_refused(self):
        for bad in ("../x", "a/b", "", "x" * 65, None, 7):
            with self.subTest(project_id=bad):
                self.assertEqual(ss.code_of(lockmod.PublishLock, self.folder, bad, now=self.clock).code, "CONTENT_INVALID")


class StaleLockTest(LockBase):
    def test_a_lock_older_than_thirty_minutes_is_taken_over_and_the_takeover_is_reported(self):
        dead = self.make().acquire()                                  # 이 실행이 죽었다고 치고 풀지 않는다
        self.clock.advance(minutes=31)
        newcomer = self.make()
        newcomer.acquire()
        self.assertTrue(newcomer.held)
        self.assertIn("넘겨받았습니다", newcomer.taken_over)
        self.assertIn("2026-11-02 10:30:12 한국 시각", newcomer.taken_over)
        self.assertIn(f"프로세스 {os.getpid()}", newcomer.taken_over)
        self.assertEqual(json.loads(self.file().read_text(encoding="utf-8"))["run"], newcomer.run, "이제 새 작업의 잠금이다")
        self.assertEqual([path.name for path in self.folder.iterdir()], [f"{PID}.lock"], "옮겨 둔 낡은 파일은 치웠다")
        dead.release()                                                 # 되살아난 옛 작업이 끝나도 새 작업의 잠금을 지우지 않는다
        self.assertTrue(self.file().exists())
        newcomer.release()
        self.assertFalse(self.file().exists())

    def test_a_lock_younger_than_the_limit_is_never_taken_over(self):
        self.make().acquire()
        self.clock.advance(minutes=29, seconds=59)
        self.assertEqual(ss.code_of(self.make().acquire).code, "PUBLISH_IN_PROGRESS")
        self.clock.advance(seconds=1)                                  # 정확히 30분 — 아직 '넘은' 것이 아니다
        self.assertEqual(ss.code_of(self.make().acquire).code, "PUBLISH_IN_PROGRESS")
        self.clock.advance(seconds=1)
        self.assertTrue(self.make().acquire().held)

    def test_the_limit_grows_with_the_time_the_run_said_it_would_wait(self):
        self.assertEqual(lockmod.lock_seconds(0), 1800)
        self.assertEqual(lockmod.lock_seconds(720), 1800)
        self.assertEqual(lockmod.lock_seconds(7200), 7200 + 900)
        self.make(deadline=7200).acquire()
        self.clock.advance(minutes=60)
        self.assertEqual(ss.code_of(self.make().acquire).code, "PUBLISH_IN_PROGRESS", "오래 기다리겠다고 한 작업의 잠금은 30분이 지나도 낡지 않았다")
        self.clock.advance(hours=1, minutes=16)                        # 합쳐서 2시간 16분 — 7200 + 900 초(2시간 15분)를 넘었다
        self.assertTrue(self.make().acquire().held)

    def test_a_lock_dated_far_in_the_future_is_not_trusted_forever(self):
        self.make().acquire()
        self.clock.advance(hours=-3)                                   # 시계가 크게 뒤로 갔다
        self.assertTrue(self.make().acquire().held)

    def test_a_lock_that_cannot_be_read_is_judged_by_its_file_time(self):
        self.folder.mkdir()
        self.file().write_text("{깨짐", encoding="utf-8")
        error = ss.code_of(self.make().acquire)
        self.assertEqual(error.code, "PUBLISH_IN_PROGRESS", "방금 만들어진 읽을 수 없는 잠금은 만드는 중일 수 있다")
        self.assertIn("시작 시각을 알 수 없음", error.slots["시작"])
        old = time.time() - 3 * 3600
        os.utime(self.file(), (old, old))
        newcomer = self.make()
        newcomer.acquire()
        self.assertIn("넘겨받았습니다", newcomer.taken_over)

    def test_a_lock_with_wrong_fields_is_not_believed(self):
        self.folder.mkdir()
        good = {"schema": 1, "project_id": PID, "pid": 1, "started": "2026-11-02T01:30:12Z", "max_seconds": 1800, "run": "a" * 32}
        for name, change in (("schema", {"schema": 2}), ("pid", {"pid": "1"}), ("pid 불리언", {"pid": True}), ("start", {"started": "어제"}), ("시간", {"max_seconds": 0}), ("run", {"run": "xyz"}),
                             ("칸 추가", {"extra": 1})):
            with self.subTest(case=name):
                self.assertIsNone(lockmod.PublishLock._parse(json.dumps({**good, **change})))
        self.assertIsNotNone(lockmod.PublishLock._parse(json.dumps(good)))
        self.assertIsNone(lockmod.PublishLock._parse("[]"))

    def test_two_newcomers_never_both_take_over_the_same_stale_lock(self):
        self.make().acquire()
        self.clock.advance(minutes=45)
        first, second = self.make(), self.make()
        first.acquire()
        self.assertEqual(ss.code_of(second.acquire).code, "PUBLISH_IN_PROGRESS", "먼저 넘겨받은 쪽이 있으면 다른 쪽은 새 잠금을 건드리지 않는다")
        self.assertEqual(json.loads(self.file().read_text(encoding="utf-8"))["run"], first.run)

    def test_taking_over_puts_back_a_lock_that_turned_out_to_be_fresh(self):
        """낡았다고 읽었는데 옮기는 순간 이미 다른 작업이 새로 잡은 잠금이었다 — 그것을 되돌려 놓고 넘겨받지 않는다."""
        self.make().acquire()
        self.clock.advance(minutes=45)
        stale_seen = lockmod.PublishLock._parse(self.file().read_text(encoding="utf-8"))
        fresh_owner = self.make()
        self.file().unlink()
        fresh_owner.acquire()                                          # 읽은 뒤 옮기기 전에 다른 작업이 새로 잡았다
        newcomer = self.make()
        self.assertFalse(newcomer._take_over(stale_seen))
        self.assertEqual(json.loads(self.file().read_text(encoding="utf-8"))["run"], fresh_owner.run, "새 잠금은 제자리에 있다")
        self.assertEqual([path.name for path in self.folder.iterdir()], [f"{PID}.lock"])


class DeadProcessLockTest(LockBase):
    """잠금을 남긴 프로세스가 이미 없으면 30분을 기다리지 않고 바로 넘겨받는다 — 단, 확실히 없을 때만."""

    def test_a_lock_left_by_a_process_that_is_gone_is_taken_over_at_once_and_the_reason_is_told(self):
        self.make().acquire()                                                            # 이 실행이 죽었다고 치고 풀지 않는다
        newcomer = self.make(alive=lambda holder: False)
        newcomer.acquire()
        self.assertTrue(newcomer.held)
        self.assertIn("그 프로세스는 이미 끝나 있음", newcomer.taken_over)
        self.assertIn("넘겨받았습니다", newcomer.taken_over)
        self.assertEqual(newcomer.why_stale, "gone")
        self.assertEqual(json.loads(self.file().read_text(encoding="utf-8"))["run"], newcomer.run)

    def test_an_old_lock_says_it_was_old_not_dead(self):
        self.make().acquire()
        self.clock.advance(minutes=45)
        newcomer = self.make(alive=lambda holder: True)
        newcomer.acquire()
        self.assertIn("오래된 잠금", newcomer.taken_over)
        self.assertEqual(newcomer.why_stale, "old")

    def test_a_process_that_is_alive_or_unknown_keeps_its_lock(self):
        self.make().acquire()
        for answer in (True, None):
            with self.subTest(answer=answer):
                self.assertEqual(ss.code_of(self.make(alive=lambda holder, answer=answer: answer).acquire).code, "PUBLISH_IN_PROGRESS")

    def test_the_liveness_check_gets_the_holder_and_is_not_asked_about_a_lock_from_another_pc(self):
        self.make().acquire()
        seen = []
        asked = self.make(alive=lambda holder: seen.append((holder.pid, holder.host)) or True)
        self.assertEqual(ss.code_of(asked.acquire).code, "PUBLISH_IN_PROGRESS")
        self.assertEqual(seen, [(os.getpid(), asked.host)])
        data = json.loads(self.file().read_text(encoding="utf-8"))
        data["host"] = asked.host + "-다른PC"
        self.file().write_text(json.dumps(data), encoding="utf-8")
        elsewhere = self.make(alive=lambda holder: False)
        self.assertEqual(ss.code_of(elsewhere.acquire).code, "PUBLISH_IN_PROGRESS", "다른 PC 에서 잡은 잠금은 그 PC 의 프로세스 번호를 여기서 볼 수 없으니 시간으로만 판단한다")
        data.pop("host")
        self.file().write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(self.make(alive=lambda holder: False).acquire().held, "host 칸이 없는 잠금은 같은 PC 로 본다")

    def test_a_lock_file_may_have_the_host_field_or_not_but_no_other_extra_field(self):
        good = {"schema": 1, "project_id": PID, "pid": 1, "started": "2026-11-02T01:30:12Z", "max_seconds": 1800, "run": "a" * 32}
        self.assertEqual(lockmod.PublishLock._parse(json.dumps(good)).host, "")
        self.assertEqual(lockmod.PublishLock._parse(json.dumps({**good, "host": "내PC"})).host, "내PC")
        self.assertIsNone(lockmod.PublishLock._parse(json.dumps({**good, "host": 7})))
        self.assertIsNone(lockmod.PublishLock._parse(json.dumps({**good, "other": 1})))

    def test_the_real_process_check_sees_this_process_a_running_child_and_a_finished_child(self):
        from datetime import datetime, timezone
        from chanceblog_desktop.service import liveness
        self.assertTrue(liveness.process_alive(os.getpid(), ss.NOW))
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            started = datetime.now(timezone.utc)
            self.assertTrue(liveness.process_alive(child.pid, started))
            self.assertIsNone(child.poll(), "살아 있는지 보다가 그 프로세스를 끝내 버리지 않았다(Windows 에서 os.kill(pid, 0) 이 하는 일)")
        finally:
            child.kill()
            child.wait()
        self.assertFalse(liveness.process_alive(child.pid, datetime.now(timezone.utc)), "끝난 프로세스는 없다고 본다")

    def test_a_process_number_taken_over_by_a_later_process_is_not_the_lock_holder(self):
        from datetime import datetime, timedelta, timezone
        from chanceblog_desktop.service import liveness
        if os.name != "nt":
            self.skipTest("프로세스 시작 시각을 읽는 것은 Windows 에서만 한다")
        long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        self.assertFalse(liveness.process_alive(self._other_live_pid(), long_ago), "잠금을 잡은 뒤에 시작한 프로세스는 그 번호를 이어받은 다른 프로세스다")

    def _other_live_pid(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: (child.kill(), child.wait()))
        return child.pid

    def test_impossible_process_numbers_are_unknown_not_killed(self):
        from chanceblog_desktop.service import liveness
        for pid in (0, -1, -999, True, None, "12", 1.5):
            with self.subTest(pid=pid):
                self.assertIsNone(liveness.process_alive(pid, ss.NOW))


class RecordOwnershipTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.journal = Journal(Path(tmp.name) / "publish")
        self.mine = PublishRecord(PID, ss.KO_PATH, "c" * 40, "b" * 40, STAGE_COMMITTED)
        self.other = PublishRecord(PID, ss.KO_PATH, "e" * 40, "b" * 40, STAGE_PUSHED)

    def test_only_a_record_identical_to_the_one_this_run_wrote_is_removed(self):
        self.journal.write(self.mine)
        self.assertIn("지우지 않았다", self.journal.remove(PID, only=self.other))
        self.assertEqual(self.journal.read(PID), self.mine, "다른 실행의 기록은 지우지 않는다")
        self.assertEqual(self.journal.remove(PID, only=self.mine), "")
        self.assertIsNone(self.journal.read(PID))

    def test_a_missing_record_is_nothing_to_remove_and_a_damaged_one_is_left_alone(self):
        self.assertEqual(self.journal.remove(PID, only=self.mine), "")
        self.journal.folder.mkdir(parents=True)
        path = self.journal.folder / f"{PID}.json"
        path.write_text("{깨짐", encoding="utf-8")
        self.assertIn("읽을 수 없어", self.journal.remove(PID, only=self.mine))
        self.assertEqual(path.read_text(encoding="utf-8"), "{깨짐")

    def test_without_an_expected_record_the_old_unconditional_removal_still_works(self):
        self.journal.write(self.other)
        self.assertEqual(self.journal.remove(PID), "")
        self.assertIsNone(self.journal.read(PID))


class FlowBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)
        self.journal = Journal(self.ctx.workspace.journal_dir)

    def approved(self, **kwargs):
        project_id = ss.make_approved(self.ctx, **kwargs)
        self.backend.calls.clear()
        return project_id

    def lock_file(self, project_id):
        return self.ctx.workspace.journal_dir / f"{project_id}.lock"

    def status(self, project_id):
        return ss.status_of(self.ctx, project_id)

    def publish(self, project_id, **kwargs):
        kwargs.setdefault("confirmed", True)
        return pages_flow.run_pages_publish(self.ctx, project_id, **kwargs)


class PublishLockedFlowTest(FlowBase):
    def test_a_second_publish_started_while_the_first_is_pushing_stops_and_the_first_ones_record_survives(self):
        project_id = self.approved()
        seen = {}

        def second_run_arrives():
            seen["record_before"] = self.journal.read(project_id)
            for name, call in (("publish", lambda: self.publish(project_id)), ("preview-yes", lambda: pages_flow.run_pages_publish(self.ctx, project_id[:8], confirmed=True)),
                               ("check-deploy", lambda: pages_flow.check_pages_deploy(self.ctx, project_id)), ("cancel", lambda: pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True))):
                seen[name] = ss.code_of(call).code
            seen["record_after"] = self.journal.read(project_id)
            seen["status"] = self.status(project_id)
            seen["backend"] = list(self.backend.calls)

        self.backend.hooks["push"] = second_run_arrives
        report = self.publish(project_id)
        self.assertEqual({key: seen[key] for key in ("publish", "preview-yes", "check-deploy", "cancel")}, {"publish": "PUBLISH_IN_PROGRESS", "preview-yes": "PUBLISH_IN_PROGRESS",
                                                                                                         "check-deploy": "PUBLISH_IN_PROGRESS", "cancel": "PUBLISH_IN_PROGRESS"})
        self.assertEqual(seen["record_after"], seen["record_before"], "첫 작업의 발행 기록은 그대로다")
        self.assertEqual(seen["record_after"].stage, STAGE_COMMITTED)
        self.assertEqual(seen["status"], st.COMMITTED)
        self.assertEqual([call[0] for call in seen["backend"]].count("commit"), 1, "두 번째 작업은 commit 도 되돌리기도 하지 않았다")
        self.assertEqual([call[0] for call in seen["backend"]].count("discard"), 0)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertEqual(self.backend.count("commit"), 1)
        self.assertEqual(self.backend.count("push"), 1)

    def test_the_lock_is_taken_before_any_check_so_the_refused_run_does_not_even_look_at_the_repository(self):
        project_id = self.approved()
        held = lockmod.PublishLock(self.ctx.workspace.journal_dir, project_id, now=self.ctx.now).acquire()
        before = ss.tree_snapshot(self.ctx.workspace.root)
        error = ss.code_of(self.publish, project_id)
        self.assertEqual(error.code, "PUBLISH_IN_PROGRESS")
        self.assertEqual(self.backend.calls, [], "저장소를 들여다보지도 않았다")
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertEqual(ss.tree_snapshot(self.ctx.workspace.root), before)
        shown = error.rendered()
        self.assertIn("진행 중", shown.message)
        self.assertIn("30분", shown.action)
        held.release()
        self.assertEqual(self.publish(project_id).status, st.PUBLISHED)

    def test_the_lock_is_released_after_success_failure_and_cancel(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        self.assertEqual(ss.code_of(self.publish, project_id).code, "GIT_PUSH_NETWORK")
        self.assertFalse(self.lock_file(project_id).exists(), "실패해도 푼다")
        pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertFalse(self.lock_file(project_id).exists(), "취소해도 푼다")
        second = self.approved(title="둘째")
        self.ctx.clock.advance(seconds=5)
        self.publish(second)
        self.assertFalse(self.lock_file(second).exists(), "성공해도 푼다")
        self.ctx.clock.advance(seconds=5)
        third = self.approved(title="셋째")
        self.publish(third, wait=False)
        pages_flow.check_pages_deploy(self.ctx, third)
        self.assertFalse(self.lock_file(third).exists(), "공개 확인을 마쳐도 푼다")

    def test_a_missing_confirmation_never_even_touches_the_lock_folder(self):
        project_id = self.approved()
        before = ss.tree_snapshot(self.ctx.workspace.root)
        self.assertEqual(ss.code_of(self.publish, project_id, confirmed=False).code, "CONFIRMATION_REQUIRED")
        self.assertEqual(ss.tree_snapshot(self.ctx.workspace.root), before)
        self.assertFalse(self.ctx.workspace.journal_dir.exists() and any(self.ctx.workspace.journal_dir.iterdir()))

    def test_the_dry_run_neither_locks_nor_writes_and_works_while_another_run_holds_the_lock(self):
        project_id = self.approved()
        before = ss.tree_snapshot(self.ctx.workspace.root)
        pages_flow.preview_publish(self.ctx, project_id)
        self.assertFalse(self.ctx.workspace.journal_dir.exists(), "미리 보기는 잠금 폴더도 만들지 않는다")
        self.assertEqual(ss.tree_snapshot(self.ctx.workspace.root), before)
        held = lockmod.PublishLock(self.ctx.workspace.journal_dir, project_id, now=self.ctx.now).acquire()
        self.assertTrue(pages_flow.preview_publish(self.ctx, project_id).dry_run, "다른 작업이 올리는 중에도 미리 보기는 읽기만 하므로 된다")
        held.release()

    def test_a_stale_lock_left_by_a_dead_run_is_taken_over_and_the_report_says_so(self):
        project_id = self.approved()
        lockmod.PublishLock(self.ctx.workspace.journal_dir, project_id, now=self.ctx.now).acquire()          # 죽은 작업이 남긴 잠금
        self.ctx.clock.advance(minutes=31)
        report = self.publish(project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertTrue(any("넘겨받았습니다" in note for note in report.notes), report.notes)
        self.assertFalse(self.lock_file(project_id).exists())

    def test_the_wait_time_the_user_asked_for_keeps_the_lock_alive_longer(self):
        project_id = self.approved()
        seen = {}
        self.backend.hooks["check_deployed"] = lambda: seen.setdefault("lock", json.loads(self.lock_file(project_id).read_text(encoding="utf-8")))
        self.publish(project_id, deadline=7200)
        self.assertEqual(seen["lock"]["max_seconds"], 7200 + 900)

    def test_cancel_and_check_deploy_also_report_a_taken_over_lock(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.publish(project_id)
        lockmod.PublishLock(self.ctx.workspace.journal_dir, project_id, now=self.ctx.now).acquire()
        self.ctx.clock.advance(minutes=40)
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertTrue(any("넘겨받았습니다" in step for step in report.steps))
        project = self.approved(title="다른 글")
        self.ctx.clock.advance(seconds=3)
        self.publish(project, wait=False)
        lockmod.PublishLock(self.ctx.workspace.journal_dir, project, now=self.ctx.now).acquire()
        self.ctx.clock.advance(minutes=40)
        self.assertTrue(any("넘겨받았습니다" in note for note in pages_flow.check_pages_deploy(self.ctx, project).notes))


class OwnRecordOnlyTest(FlowBase):
    """실패한 쪽이 다른 실행이 쓴 발행 기록을 지우는 일이 없다 — 올라간 글을 잊지 않는다."""

    OTHER = PublishRecord("x", ss.KO_PATH, "e" * 40, "b" * 40, STAGE_PUSHED)

    def other_run_writes_its_record(self, project_id):
        record = PublishRecord(project_id, self.OTHER.path, self.OTHER.commit, self.OTHER.base, self.OTHER.stage)
        return record, lambda: self.journal.write(record)

    def test_the_undo_after_a_failed_state_save_leaves_a_record_another_run_wrote(self):
        project_id = self.approved()
        record, write = self.other_run_writes_its_record(project_id)
        self.backend.hooks["discard"] = write                                      # 되돌리는 사이 다른 실행이 올림 기록을 썼다
        real_store = self.ctx.store

        def failing():
            if self.backend.count("commit"):
                raise AppError("STORE_LOCKED")
            return real_store()

        self.ctx.store = failing
        error = ss.code_of(self.publish, project_id)
        self.ctx.store = real_store
        self.assertEqual(error.code, "STORE_LOCKED")
        self.assertEqual(self.journal.read(project_id), record, "다른 실행이 쓴 기록은 지우지 않았다")
        self.assertIn("지우지 않았다", error.detail)

    def test_giving_up_after_a_duplicate_leaves_a_record_another_run_wrote(self):
        project_id = self.approved()
        record, write = self.other_run_writes_its_record(project_id)
        self.backend.hooks["discard"] = write
        self.backend.push_errors = [AppError("DUPLICATE_SLUG")]
        error = ss.code_of(self.publish, project_id)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertEqual(self.journal.read(project_id), record)
        self.assertIn("지우지 않았다", error.detail)
        self.assertEqual(self.status(project_id), st.PUBLISH_FAILED)

    def test_finishing_the_verification_leaves_a_record_another_run_wrote(self):
        project_id = self.approved()
        record, write = self.other_run_writes_its_record(project_id)
        self.backend.hooks["check_deployed"] = write
        report = self.publish(project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertEqual(self.journal.read(project_id), record)
        self.assertTrue(any("지우지 않았다" in note for note in report.notes), report.notes)

    def test_cancelling_leaves_a_record_another_run_wrote(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.publish(project_id)
        record, write = self.other_run_writes_its_record(project_id)
        self.backend.hooks["discard"] = write
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(self.journal.read(project_id), record)
        self.assertTrue(any("지우지 않았다" in step for step in report.steps))

    def test_the_normal_paths_still_remove_the_record_they_wrote(self):
        project_id = self.approved()
        self.publish(project_id)
        self.assertIsNone(self.journal.read(project_id))
        second = self.approved(title="둘째")
        self.ctx.clock.advance(seconds=3)
        self.backend.push_errors = [AppError("DUPLICATE_SLUG")]
        with self.assertRaises(AppError):
            self.publish(second)
        self.assertIsNone(self.journal.read(second))


# ---- 진짜 프로세스 둘 -------------------------------------------------------------------------------------------------------------
CHILD = textwrap.dedent('''
    import os, sys, time
    sys.path.insert(0, sys.argv[1])
    sys.path.insert(0, sys.argv[2])
    import service_support as ss
    from chanceblog_desktop.service import cli
    from chanceblog_desktop.service.backend import GitPagesBackend
    from chanceblog_desktop.service.context import make_context

    data, repo, project_id, reached, go = sys.argv[3:8]


    class Slow(GitPagesBackend):
        def push(self, repo_path, post):
            if reached != "-":
                open(reached, "w").close()                                  # 잠금을 쥔 채 올리는 중이다
                end = time.time() + 120
                while not os.path.exists(go) and time.time() < end:
                    time.sleep(0.05)
            return super().push(repo_path, post)


    ctx = make_context(data_dir=data, repo=repo, backend=Slow(expected_origin=ss.LOCAL_ORIGIN), expected_origin=ss.LOCAL_ORIGIN)
    sys.exit(cli.main(["publish-pages", project_id, "--yes", "--no-wait"], ctx=ctx))
''')


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class TwoRealProcessesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = ss.GitSandbox()
        cls.addClassCleanup(cls.box.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin, self.work = self.box.copy_into(self.tmp)
        backend = GitPagesBackend(git=ss.Spy(), expected_origin=ss.LOCAL_ORIGIN, fetcher=ss.FakeWorld().fetcher)
        self.ctx = ss.make_ctx(self.tmp, backend=backend, repo=None, git=ss.Spy())
        self.ctx.settings.save_repo_path(str(self.work))
        self.script = self.tmp / "child.py"
        self.script.write_text(CHILD, encoding="utf-8")
        self.reached, self.go = self.tmp / "reached", self.tmp / "go"

    def spawn(self, project_id, *, slow):
        args = [sys.executable, "-X", "utf8", str(self.script), str(ss.ROOT / "src"), str(ss.ROOT / "tests"), str(self.ctx.workspace.root), str(self.work), project_id,
                str(self.reached) if slow else "-", str(self.go)]
        env = {key: value for key, value in os.environ.items() if key not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA")}
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    def wait_for(self, path, process, seconds=120):
        end = time.time() + seconds
        while not path.exists():
            if process.poll() is not None:
                self.fail(f"자식 프로세스가 기다리는 지점에 닿기 전에 끝났다: {process.communicate()}")
            if time.time() > end:
                process.kill()
                self.fail("자식 프로세스가 기다리는 지점에 닿지 못했다")
            time.sleep(0.05)

    def test_two_real_processes_publishing_the_same_post_publish_it_once_and_the_loser_changes_nothing(self):
        project_id = ss.make_approved(self.ctx)
        origin_before = ss.git(self.origin, "rev-parse", "main")
        first = self.spawn(project_id, slow=True)
        try:
            self.wait_for(self.reached, first)
            lock_path = self.ctx.workspace.journal_dir / f"{project_id}.lock"
            self.assertTrue(lock_path.exists(), "첫 작업이 올리는 동안 잠금 파일이 있다")
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["pid"], first.pid)
            journal = Journal(self.ctx.workspace.journal_dir)
            record_while_locked = journal.read(project_id)
            self.assertEqual(record_while_locked.stage, STAGE_COMMITTED)
            head_while_locked = ss.git(self.work, "rev-parse", "HEAD")
            second = self.spawn(project_id, slow=False)
            out, err = second.communicate(timeout=240)
            err_text = err.decode("utf-8", "replace")
            self.assertEqual(second.returncode, 1, err_text)
            self.assertIn("PUBLISH_IN_PROGRESS", err_text)
            self.assertIn("진행 중", err_text)
            self.assertEqual(journal.read(project_id), record_while_locked, "두 번째 작업이 첫 작업의 발행 기록을 건드리지 않았다")
            self.assertEqual(ss.git(self.work, "rev-parse", "HEAD"), head_while_locked, "두 번째 작업이 commit 을 더하지 않았다")
            self.assertEqual(ss.git(self.origin, "rev-parse", "main"), origin_before, "아직 아무것도 올라가지 않았다")
            self.assertEqual(ss.status_of(self.ctx, project_id), st.COMMITTED)
        finally:
            self.go.write_text("go", encoding="utf-8")
        out, err = first.communicate(timeout=240)
        self.assertEqual(first.returncode, 0, err.decode("utf-8", "replace"))
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{origin_before}..main"), "1", "원격에는 글 하나만 올라갔다")
        self.assertEqual(ss.git(self.origin, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").count("_posts/"), 1)
        record = Journal(self.ctx.workspace.journal_dir).read(project_id)
        self.assertEqual((record.stage, record.commit), (STAGE_PUSHED, ss.git(self.origin, "rev-parse", "main")), "올라간 글의 '올림' 기록이 남아 있어 공개 확인을 이어갈 수 있다")
        self.assertEqual(ss.status_of(self.ctx, project_id), st.PUSHED)
        self.assertEqual([path.name for path in self.ctx.workspace.journal_dir.iterdir()], [f"{project_id}.json"], "잠금 파일이 남지 않았다")


if __name__ == "__main__":
    unittest.main()
