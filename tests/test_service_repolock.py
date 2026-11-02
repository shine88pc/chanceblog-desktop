"""서비스 층 — **서로 다른 두 글**이 같은 저장소에 동시에 올라가지 못하게 하는 저장소 잠금(`service/lock.py` 의 `RepoLock`·`repo_lock`)과 그 흐름 시험.

배경: 글 잠금은 글마다라서 서로 다른 두 글을 거의 동시에 올리면 둘 다 '최신 받기 → commit' 을 같은 저장소에서 하게 됐다(독립 검증 재현 — 1.0초 간격 3/3: 둘 다 COMMITTED·올리지 않은 commit 둘·원격 새 글 0·
같은 명령은 PAGES_LOCAL_REPO_DIVERGED). 그래서 commit·push·되돌리기 구간은 저장소마다 한 번에 하나만 돈다.

지키는 것:
  1) 저장소 잠금 파일(`publish/repo-<해시>.lock`)은 글 잠금과 같은 방식으로 만들고 풀며(자기 실행 번호만 지움·낡은 것은 넘겨받음), 같은 폴더면 어떤 경로 표기로 불러도 같은 이름이다.
  2) 올리기·되돌리기는 글 잠금을 먼저 잡은 다음 저장소 잠금을 잡는다(순서 고정 — 서로 기다리며 멈추지 않는다). 못 잡으면 정해진 시간 기다리다 PUBLISH_REPO_BUSY 로 물러나며 **아무것도 바꾸지 않는다**.
  3) commit·push 를 하는 동안만 쥐고, 공개 주소가 열리기를 기다리는 동안에는 풀어 다른 글이 올라갈 수 있다. 미리 보기(dry run)와 공개 확인은 쥐지 않는다.
  4) 진짜 스레드·진짜 프로세스 둘이 서로 다른 글을 어떤 간격으로 올려도 같은 명령만으로 두 글이 모두 올라가고(수동 git 불필요), 죽은 프로세스의 낡은 저장소 잠금은 바로 넘겨받으며 같은 글 잠금과 얽혀 멈추지 않는다.
"""
import errno
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import lock as lockmod  # noqa: E402
from chanceblog_desktop.service import pages_flow  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_COMMITTED, STAGE_PUSHED, Journal  # noqa: E402

REAL_CLOCK = lambda: datetime.now(timezone.utc)  # noqa: E731


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.folder = self.tmp / "publish"
        self.clock = ss.Clock()
        (self.tmp / "chanceblog").mkdir()

    def repo_lock(self, repo=None, **kwargs):
        return lockmod.RepoLock(self.folder, repo or (self.tmp / "chanceblog"), now=self.clock, **kwargs)

    def lock_file(self, repo=None):
        return self.folder / (lockmod.repo_lock_name(repo or (self.tmp / "chanceblog")) + ".lock")


class RepoLockNameTest(Base):
    def test_the_same_folder_has_the_same_lock_name_however_it_is_spelled(self):
        repo = self.tmp / "chanceblog"
        spellings = [repo, str(repo) + os.sep, self.tmp / "x" / ".." / "chanceblog", self.tmp / "." / "chanceblog"]
        if os.path.splitdrive(str(repo))[0] == os.path.splitdrive(os.getcwd())[0]:
            spellings.append(Path(os.path.relpath(repo)))                            # 상대 경로
        names = {lockmod.repo_lock_name(item) for item in spellings}
        self.assertEqual(len(names), 1, names)
        if os.name == "nt":
            self.assertEqual(lockmod.repo_lock_name(str(repo).upper()), lockmod.repo_lock_name(str(repo).lower()), "Windows 는 폴더 이름의 대소문자를 가리지 않는다")

    def test_a_link_to_the_folder_has_the_same_lock_name(self):
        link = self.tmp / "link"
        try:
            os.symlink(self.tmp / "chanceblog", link, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                self.skipTest("이 환경에서는 링크를 만들 수 없다")
            done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.tmp / "chanceblog")], capture_output=True)       # Windows 정션(관리자 권한이 필요 없다)
            if done.returncode != 0:
                self.skipTest("이 환경에서는 링크·정션을 만들 수 없다")
        self.assertTrue(link.is_dir())
        self.assertEqual(lockmod.repo_lock_name(link), lockmod.repo_lock_name(self.tmp / "chanceblog"), "같은 폴더를 가리키는 링크·정션은 같은 잠금을 쓴다")

    def test_a_folder_that_does_not_exist_yet_is_named_without_regard_to_case_on_windows(self):
        if os.name != "nt":
            self.skipTest("대소문자를 가리지 않는 것은 Windows 뿐이다")
        missing = self.tmp / "아직없는" / "Chanceblog"
        self.assertEqual(lockmod.repo_lock_name(str(missing).upper()), lockmod.repo_lock_name(str(missing).lower()))

    def test_different_folders_have_different_names_and_the_name_has_a_fixed_shape(self):
        other = self.tmp / "other"
        other.mkdir()
        first, second = lockmod.repo_lock_name(self.tmp / "chanceblog"), lockmod.repo_lock_name(other)
        self.assertNotEqual(first, second)
        for name in (first, second):
            self.assertRegex(name, r"^repo-[0-9a-f]{16}$")
        self.assertTrue(lockmod._ID.match(first), "글 잠금과 같은 이름 규칙을 지킨다")

    def test_a_post_number_that_looks_like_a_repo_lock_is_refused(self):
        ctx = ss.make_ctx(self.tmp)
        name = lockmod.repo_lock_name(self.tmp / "chanceblog")
        with self.assertRaises(AppError) as caught:
            with lockmod.publish_lock(ctx, name):
                self.fail("잡히면 안 된다")
        self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        with lockmod.publish_lock(ctx, "repo"):                                  # 앞머리 `repo-` 가 아니면 평범한 글 번호다
            pass


class RepoLockFileTest(Base):
    def test_the_lock_file_has_the_same_fields_as_a_post_lock_and_is_released(self):
        held = self.repo_lock().acquire()
        data = json.loads(self.lock_file().read_text(encoding="utf-8"))
        self.assertEqual(sorted(data), ["host", "max_seconds", "pid", "project_id", "run", "schema", "started"])
        self.assertEqual((data["pid"], data["project_id"], data["max_seconds"]), (os.getpid(), self.lock_file().stem, 1800))
        held.release()
        self.assertFalse(self.lock_file().exists())

    def test_a_second_holder_is_refused_with_its_own_error_code_and_nothing_changes(self):
        first = self.repo_lock().acquire()
        before = self.lock_file().read_bytes()
        error = ss.code_of(self.repo_lock().acquire)
        self.assertEqual(error.code, "PUBLISH_REPO_BUSY")
        self.assertIn("2026-11-02 10:30:12 한국 시각", error.slots["시작"])
        self.assertEqual(self.lock_file().read_bytes(), before)
        self.assertEqual([path.name for path in self.folder.iterdir()], [self.lock_file().name], "다른 파일을 만들지 않았다")
        shown = error.rendered()
        self.assertIn("저장소", shown.message)
        self.assertIn("같은 명령을 다시", shown.action)
        first.release()
        self.assertTrue(self.repo_lock().acquire().held)

    def test_a_repo_lock_and_a_post_lock_are_different_files_that_never_block_each_other(self):
        post = lockmod.PublishLock(self.folder, "post-a", now=self.clock).acquire()
        repo = self.repo_lock().acquire()
        self.assertTrue(post.held and repo.held)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), sorted(["post-a.lock", self.lock_file().name]))

    def test_two_different_repositories_do_not_block_each_other(self):
        other = self.tmp / "other"
        other.mkdir()
        self.assertTrue(self.repo_lock().acquire().held and self.repo_lock(other).acquire().held)

    def test_release_removes_only_its_own_repo_lock(self):
        held = self.repo_lock().acquire()
        taken = json.loads(self.lock_file().read_text(encoding="utf-8"))
        taken["run"] = "0" * 32
        self.lock_file().write_text(json.dumps(taken), encoding="utf-8")
        held.release()
        self.assertTrue(self.lock_file().exists())
        self.assertIn("내 잠금이 아니어서", held.release_note)

    def test_waiting_stops_as_soon_as_the_holder_lets_go_and_tells_how_long_it_waited(self):
        first = self.repo_lock().acquire()
        told = []
        timer = threading.Timer(0.5, first.release)
        timer.start()
        self.addCleanup(timer.cancel)
        second = self.repo_lock()
        started = time.monotonic()
        second.acquire_waiting(30, progress=told.append, interval=0.1)
        elapsed = time.monotonic() - started
        self.assertTrue(second.held)
        self.assertGreaterEqual(second.waited, 0.4)
        self.assertLess(elapsed, 10, "끝나자마자 이어서 잡았다")
        self.assertEqual(len(told), 1, "기다리기 시작할 때 한 번만 알린다")
        self.assertIn("기다립니다", told[0])
        self.assertIn("2026-11-02 10:30:12 한국 시각", told[0])

    def test_waiting_gives_up_at_the_limit_with_the_busy_error_and_changes_nothing(self):
        first = self.repo_lock().acquire()
        before = self.lock_file().read_bytes()
        second = self.repo_lock()
        started = time.monotonic()
        error = ss.code_of(second.acquire_waiting, 0.6, interval=0.1)
        self.assertEqual(error.code, "PUBLISH_REPO_BUSY")
        self.assertGreaterEqual(time.monotonic() - started, 0.5, "정한 시간만큼은 기다렸다")
        self.assertFalse(second.held)
        self.assertEqual(self.lock_file().read_bytes(), before)
        first.release()

    def test_a_zero_wait_means_no_waiting_at_all(self):
        self.repo_lock().acquire()
        started = time.monotonic()
        self.assertEqual(ss.code_of(self.repo_lock().acquire_waiting, 0).code, "PUBLISH_REPO_BUSY")
        self.assertLess(time.monotonic() - started, 0.4)

    def test_an_error_that_is_not_about_a_busy_lock_is_not_waited_for(self):
        with mock.patch.object(lockmod.os, "write", side_effect=OSError(errno.ENOSPC, "No space left")):
            started = time.monotonic()
            error = ss.code_of(self.repo_lock().acquire_waiting, 30)
        self.assertEqual(error.code, "DISK_FULL")
        self.assertLess(time.monotonic() - started, 5, "디스크가 가득 찬 것은 기다린다고 풀리지 않는다")
        self.assertFalse(self.lock_file().exists())

    def test_a_lock_left_by_a_process_that_is_gone_is_taken_over_at_once_and_says_it_was_the_repository(self):
        self.repo_lock().acquire()                                                 # 이 실행이 죽었다고 치고 풀지 않는다
        newcomer = self.repo_lock(alive=lambda holder: False)
        newcomer.acquire_waiting(0)
        self.assertTrue(newcomer.held)
        self.assertEqual(newcomer.waited, 0.0)
        self.assertIn("이전에 이 저장소에 글을 올리다 멈춘 흔적(그 프로세스는 이미 끝나 있음)을 넘겨받았습니다", newcomer.taken_over)

    def test_an_old_repo_lock_is_taken_over_after_thirty_minutes_even_if_the_process_cannot_be_checked(self):
        self.repo_lock().acquire()
        self.clock.advance(minutes=31)
        newcomer = self.repo_lock(alive=lambda holder: None)
        newcomer.acquire()
        self.assertIn("오래된 잠금", newcomer.taken_over)

    def test_a_lock_that_vanished_between_reading_and_checking_its_age_is_simply_taken_again_without_a_notice(self):
        """읽을 수 없는 잠금(만들다 멈춤)의 시각을 보려는 순간 파일이 사라졌다 — 낡은 흔적을 넘겨받은 것이 아니므로 알리지 않고 다시 잡는다."""
        self.folder.mkdir()
        path = self.lock_file()
        path.write_text("{깨짐", encoding="utf-8")
        real_stat = os.stat

        def vanishing(target, *args, **kwargs):
            if str(target) == str(path):
                os.unlink(path)
                raise FileNotFoundError(errno.ENOENT, "gone", str(target))
            return real_stat(target, *args, **kwargs)

        newcomer = self.repo_lock()
        with mock.patch.object(lockmod.os, "stat", side_effect=vanishing):
            newcomer.acquire()
        self.assertTrue(newcomer.held)
        self.assertEqual(newcomer.taken_over, "", "사라진 잠금은 넘겨받은 것이 아니다")

    def test_a_lock_whose_age_cannot_be_read_is_never_assumed_to_be_old(self):
        """시각을 모르는 읽을 수 없는 잠금(권한·다른 프로세스가 쥐고 있음)은 낡았다고 보지 않는다 — 막는 쪽이 안전하다."""
        self.folder.mkdir()
        self.lock_file().write_text("{깨짐", encoding="utf-8")
        before = self.lock_file().read_bytes()
        path, real_stat = self.lock_file(), os.stat

        def denied(target, *args, **kwargs):
            if str(target) == str(path):
                raise PermissionError(errno.EACCES, "denied", str(target))
            return real_stat(target, *args, **kwargs)

        with mock.patch.object(lockmod.os, "stat", side_effect=denied):
            error = ss.code_of(self.repo_lock().acquire)
        self.assertEqual(error.code, "PUBLISH_REPO_BUSY")
        self.assertIn("시작 시각을 알 수 없음", error.slots["시작"])
        self.assertEqual(self.lock_file().read_bytes(), before, "그 잠금은 건드리지 않았다")


class FlowBase(Base):
    def setUp(self):
        super().setUp()
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)
        self.folder = self.ctx.workspace.journal_dir
        self.repo = self.ctx.repo_path()
        self.journal = Journal(self.folder)

    def approved(self, **kwargs):
        project_id = ss.make_approved(self.ctx, **kwargs)
        self.backend.calls.clear()
        return project_id

    def post_lock(self, project_id):
        return self.folder / f"{project_id}.lock"

    def publish(self, project_id, **kwargs):
        kwargs.setdefault("confirmed", True)
        return pages_flow.run_pages_publish(self.ctx, project_id, **kwargs)

    def hold_repo(self, **kwargs):
        """다른 작업이 이 저장소에 올리는 중인 것처럼 저장소 잠금을 쥔다(같은 프로세스라 '살아 있는' 잠금이다)."""
        held = lockmod.RepoLock(self.folder, self.repo, now=self.ctx.now, **kwargs).acquire()
        self.addCleanup(held.release)
        return held

    def files(self):
        return sorted(path.name for path in self.folder.iterdir()) if self.folder.exists() else []


class RepoLockedFlowTest(FlowBase):
    def test_the_repo_lock_is_held_while_committing_and_pushing_but_not_while_waiting_for_the_public_address(self):
        project_id = self.approved()
        seen = {}
        repo_file = lockmod.repo_lock_name(self.repo) + ".lock"

        def snapshot(name):
            return lambda: seen.__setitem__(name, {"repo": (self.folder / repo_file).exists(), "post": self.post_lock(project_id).exists()})

        for name in ("commit", "push", "check_deployed"):
            self.backend.hooks[name] = snapshot(name)
        self.assertEqual(self.publish(project_id).status, st.PUBLISHED)
        self.assertEqual(seen["commit"], {"repo": True, "post": True}, "commit 하는 동안 두 잠금을 쥔다")
        self.assertEqual(seen["push"], {"repo": True, "post": True}, "push 하는 동안 두 잠금을 쥔다")
        self.assertEqual(seen["check_deployed"], {"repo": False, "post": True}, "공개 확인을 기다리는 동안에는 저장소 잠금을 풀고(다른 글이 올라갈 수 있다) 글 잠금만 쥔다")
        self.assertEqual(self.files(), [], "끝나면 어느 잠금도 남지 않는다(발행 기록도 지웠다)")

    def test_the_lock_order_is_the_post_first_and_a_busy_post_never_touches_the_repo_lock(self):
        project_id = self.approved()
        held = lockmod.PublishLock(self.folder, project_id, now=self.ctx.now).acquire()
        self.ctx.lock_wait = 30
        started = time.monotonic()
        self.assertEqual(ss.code_of(self.publish, project_id).code, "PUBLISH_IN_PROGRESS", "같은 글은 기다리지 않고 바로 물러난다")
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.files(), [f"{project_id}.lock"], "저장소 잠금을 만들지도 않았다")
        self.assertEqual(self.backend.calls, [])
        held.release()

    def test_a_busy_repository_stops_the_publish_before_anything_is_looked_at_and_changes_nothing(self):
        project_id = self.approved()
        held = self.hold_repo()
        self.ctx.lock_wait = 0
        before = (self.files(), held.path and Path(held.path).read_bytes(), ss.tree_snapshot(self.ctx.workspace.root))
        error = ss.code_of(self.publish, project_id)
        self.assertEqual(error.code, "PUBLISH_REPO_BUSY")
        self.assertEqual(self.backend.calls, [], "저장소를 들여다보지도 않았다")
        self.assertEqual(ss.status_of(self.ctx, project_id), st.APPROVED)
        self.assertIsNone(self.journal.read(project_id))
        self.assertEqual((self.files(), Path(held.path).read_bytes(), ss.tree_snapshot(self.ctx.workspace.root)), before, "글 잠금도 남기지 않았다")
        shown = error.rendered()
        self.assertIn("같은 저장소", shown.message)
        self.assertIn("같은 명령을 다시", shown.action)
        held.release()
        self.assertEqual(self.publish(project_id).status, st.PUBLISHED, "끝난 뒤 같은 명령을 다시 하면 올라간다")

    def test_the_busy_error_comes_out_of_the_command_line_with_exit_code_1(self):
        project_id = self.approved()
        self.hold_repo()
        self.ctx.lock_wait = 0
        for extra in ([], ["--no-wait"]):
            code, out, err = ss.run_cli(self.ctx, "publish-pages", project_id, "--yes", *extra)
            self.assertEqual(code, 1)
            self.assertIn("PUBLISH_REPO_BUSY", err)
            self.assertIn("같은 명령을 다시", err)
        self.assertEqual(self.backend.count("commit"), 0)

    def test_a_publish_that_has_to_wait_goes_on_when_the_other_one_finishes_and_says_so(self):
        project_id = self.approved()
        held = self.hold_repo()
        self.ctx.lock_wait = 30
        told = []
        self.backend.progress = told.append
        timer = threading.Timer(1.3, held.release)
        timer.start()
        self.addCleanup(timer.cancel)
        report = self.publish(project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertTrue(any("기다린 뒤 올렸습니다" in note for note in report.notes), report.notes)
        self.assertEqual(len(told), 1)
        self.assertIn("기다립니다", told[0])
        self.assertEqual(self.files(), [])

    def test_a_waiting_publish_takes_over_the_moment_the_holder_is_found_dead_and_says_so(self):
        project_id = self.approved()
        self.hold_repo()
        self.ctx.lock_wait = 60
        answers = iter([True, True])                                                        # 처음 두 번은 아직 살아 있다고, 그다음부터는 이미 끝났다고 답한다
        started = time.monotonic()
        with mock.patch.object(lockmod, "process_alive", side_effect=lambda pid, since: next(answers, False)):
            report = self.publish(project_id)
        self.assertLess(time.monotonic() - started, 30, "죽은 것을 알아보자마자 넘겨받았다(60초를 다 기다리지 않았다)")
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertTrue(any("이 저장소에 글을 올리다 멈춘 흔적(그 프로세스는 이미 끝나 있음)을 넘겨받았습니다" in note for note in report.notes), report.notes)

    def test_ctrl_c_while_waiting_leaves_nothing_behind_and_does_not_touch_the_other_holders_lock(self):
        project_id = self.approved()
        held = self.hold_repo()
        before = Path(held.path).read_bytes()
        self.ctx.lock_wait = 60
        with mock.patch.object(lockmod.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.publish(project_id)
        self.assertEqual(self.files(), [Path(held.path).name], "글 잠금은 풀었고 다른 작업의 저장소 잠금은 그대로다")
        self.assertEqual(Path(held.path).read_bytes(), before)
        self.assertEqual((self.backend.calls, ss.status_of(self.ctx, project_id)), ([], st.APPROVED))

    def test_a_publish_that_did_not_have_to_wait_says_nothing_about_waiting(self):
        project_id = self.approved()
        report = self.publish(project_id)
        self.assertFalse(any("기다린 뒤" in note for note in report.notes))

    def stem(self, offset=0):
        return f"2026-11-02-KR-1030{12 + offset:02d}"

    def test_a_name_whose_second_is_already_taken_moves_to_the_next_second_without_waiting(self):
        """바로 앞 글이 같은 초에 올라갔다 — 새 글은 같은 주소(날짜-언어-시각의 초)를 피해 다음 초의 이름으로 올라간다(재시도가 필요 없다)."""
        project_id = self.approved()
        self.backend.taken_stems = {self.stem()}
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual(plan.path, "_posts/경제·일/" + self.stem(1) + ".md")
        self.assertEqual(plan.now, ss.NOW + timedelta(seconds=1), "시각도 같은 만큼 밀렸다")
        self.assertTrue(plan.expected_url.endswith("KR-103013/"), plan.expected_url)
        self.assertEqual(pages_flow.preview_publish(self.ctx, project_id).plan.path, plan.path, "미리 보기도 같은 이름을 보여 준다")
        report = self.publish(project_id)
        self.assertEqual((report.status, report.plan.path), (st.PUBLISHED, plan.path))
        self.assertEqual([call[1] for call in self.backend.calls if call[0] == "commit"], [plan.path])
        self.assertTrue(report.url.endswith("KR-103013/"), report.url)
        self.assertEqual(self.backend.deployed_at, ss.NOW + timedelta(seconds=1), "공개 확인도 파일 이름과 같은 시각으로 한다")

    def test_the_second_is_pushed_forward_up_to_five_times_and_then_the_duplicate_is_reported(self):
        project_id = self.approved()
        self.backend.taken_stems = {self.stem(n) for n in range(5)}                       # 12~16초가 모두 쓰였다 — 17초(다섯 번째로 민 시각)는 비어 있다
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, project_id).path, "_posts/경제·일/" + self.stem(5) + ".md")
        self.backend.taken_stems = {self.stem(n) for n in range(6)}                       # 17초까지 모두 쓰였다
        error = ss.code_of(self.publish, project_id)
        self.assertEqual(error.code, "DUPLICATE_SLUG")
        self.assertEqual((self.backend.count("commit"), ss.status_of(self.ctx, project_id)), (0, st.APPROVED), "아무것도 올리지 않았다")

    def test_a_name_taken_by_another_post_that_is_still_being_published_is_avoided_too(self):
        first = self.approved()
        self.publish(first, wait=False)                                                    # 올라갔고 공개 확인만 남은 글 — 발행 기록이 있다
        second = self.approved(title="다음 글")
        self.assertEqual(self.ctx.now(), ss.NOW)
        plan = pages_flow.plan_pages_publish(self.ctx, second)
        self.assertEqual(plan.path, "_posts/경제·일/" + self.stem(1) + ".md", "같은 시각이면 다른 글이 쓰는 이름을 피한다")
        self.assertEqual(self.publish(second, wait=False).status, st.PUSHED)

    def test_a_name_that_was_already_fixed_is_never_moved(self):
        """이어서 올릴 글(COMMITTED)의 파일 이름은 이미 정해져 있다 — 시각을 밀지 않는다."""
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.publish(project_id)
        self.backend.taken_stems = {self.stem()}
        plan = pages_flow.plan_pages_publish(self.ctx, project_id)
        self.assertEqual((plan.stage, plan.path, plan.now), (pages_flow.STAGE_PUSH, ss.KO_PATH, ss.NOW))

    def test_a_cancel_is_also_stopped_by_a_busy_repository_and_changes_nothing(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            self.publish(project_id)
        self.backend.calls.clear()
        held = self.hold_repo()
        self.ctx.lock_wait = 0
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "PUBLISH_REPO_BUSY")
        self.assertEqual((self.backend.calls, ss.status_of(self.ctx, project_id)), ([], st.COMMITTED))
        self.assertIsNotNone(self.journal.read(project_id))
        held.release()
        self.assertEqual(pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True).status, st.PUBLISH_FAILED)
        self.assertEqual(self.backend.count("discard"), 1)

    def test_the_dry_run_and_the_public_address_check_do_not_need_the_repo_lock(self):
        project_id = self.approved()
        other = self.approved(title="이미 올라간 글")
        self.ctx.clock.advance(seconds=3)
        pages_flow.run_pages_publish(self.ctx, other, confirmed=True, wait=False)       # 저장소가 비어 있을 때 올려 둔다(공개 확인만 남았다)
        self.ctx.clock.advance(seconds=3)                                               # 다른 파일 이름(시각)이 되게
        self.hold_repo()
        self.ctx.lock_wait = 0
        self.assertTrue(pages_flow.preview_publish(self.ctx, project_id).dry_run, "미리 보기는 읽기만 하므로 기다리지 않는다")
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, other).status, st.PUBLISHED, "공개 확인은 저장소를 쓰지 않으므로 기다리지 않는다")

    def test_the_locks_are_released_after_every_kind_of_ending(self):
        for problem in (AppError("GIT_PUSH_NETWORK"), KeyboardInterrupt()):
            with self.subTest(problem=type(problem).__name__):
                project_id = self.approved(title=f"글 {type(problem).__name__}")
                self.ctx.clock.advance(seconds=3)
                self.backend.push_errors = [problem]
                with self.assertRaises(type(problem)):
                    self.publish(project_id)
                self.assertEqual([name for name in self.files() if name.endswith(".lock")], [], "실패·Ctrl+C 에도 두 잠금 모두 풀었다")
        self.backend.commit_error = AppError("FILE_WRITE_FAILED", {"경로": "x"})
        project_id = self.approved(title="commit 실패")
        self.ctx.clock.advance(seconds=3)
        self.assertEqual(ss.code_of(self.publish, project_id).code, "FILE_WRITE_FAILED")
        self.assertEqual([name for name in self.files() if name.endswith(".lock")], [])

    def test_without_a_connected_repository_nothing_is_locked_and_the_usual_error_comes_first(self):
        ctx = ss.make_ctx(self.tmp / "x", backend=ss.FakeBackend(), repo=None)
        project_id = ss.make_approved(ctx)
        error = ss.code_of(pages_flow.run_pages_publish, ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_INVALID")
        self.assertEqual(list(ctx.workspace.journal_dir.glob("repo-*")), [], "잠글 저장소가 없으니 저장소 잠금 파일도 없다")

    def test_a_not_yet_approved_post_is_still_refused_with_its_own_error_while_the_repository_is_free(self):
        view = ss.projects.new_project(self.ctx, "아직 시작 전", ss.ko_text())
        self.assertEqual(ss.code_of(self.publish, view.project_id).code, "STATUS_TRANSITION_INVALID")
        self.assertEqual(self.files(), [])

    def test_the_wait_the_context_allows_is_a_plain_setting_with_a_default_of_two_minutes(self):
        self.assertEqual(ss.make_ctx(self.tmp / "y").lock_wait, 120.0)

    def test_stale_locks_left_by_one_crashed_publish_are_announced_once(self):
        """같은 글을 올리다 죽어 글 잠금과 저장소 잠금이 둘 다 남았다 — 같은 명령이 둘 다 넘겨받되 알림은 한 번만 나온다."""
        project_id = self.approved()
        lockmod.PublishLock(self.folder, project_id, now=self.ctx.now).acquire()
        lockmod.RepoLock(self.folder, self.repo, now=self.ctx.now).acquire()
        with mock.patch.object(lockmod, "process_alive", return_value=False):
            report = self.publish(project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        notes = [note for note in report.notes if "넘겨받았습니다" in note]
        self.assertEqual(len(notes), 1, report.notes)
        self.assertIn("같은 글을 올리다", notes[0])
        self.assertEqual(self.files(), [])

    def test_only_the_repository_lock_was_left_by_a_crash_and_the_notice_says_the_repository(self):
        """다른 글을 올리다 죽어 저장소 잠금만 남았다 — 이 글의 올리기는 바로 넘겨받고(기다리지 않는다) 저장소 이야기로 알린다."""
        project_id = self.approved()
        lockmod.RepoLock(self.folder, self.repo, now=self.ctx.now).acquire()
        with mock.patch.object(lockmod, "process_alive", return_value=False):
            started = time.monotonic()
            report = self.publish(project_id)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertTrue(any("이 저장소에 글을 올리다 멈춘 흔적" in note for note in report.notes), report.notes)

    def test_a_publish_that_finds_the_post_already_public_takes_the_repo_lock_only_briefly_and_does_nothing(self):
        project_id = self.approved()
        self.publish(project_id)
        self.backend.calls.clear()
        report = self.publish(project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertEqual((self.backend.count("commit"), self.backend.count("push")), (0, 0))
        self.assertEqual(self.files(), [])


# ---- 진짜 git · 진짜 스레드 ----------------------------------------------------------------------------------------------------
@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class TwoThreadsRealGitTest(unittest.TestCase):
    """같은 프로세스 안의 스레드 둘이 서로 다른 글을 올린다(진짜 git·로컬 bare 저장소) — 첫째가 push 하는 동안 둘째는 아무것도 하지 못하고, 끝나면 이어서 올라간다."""

    @classmethod
    def setUpClass(cls):
        cls.box = ss.GitSandbox()
        cls.addClassCleanup(cls.box.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin, self.work = self.box.copy_into(self.tmp)
        self.reached, self.release = threading.Event(), threading.Event()
        count = {"n": 0}
        outer = self

        class Slow(GitPagesBackend):
            def push(self_, repo_path, post):
                count["n"] += 1
                if count["n"] == 1:
                    outer.reached.set()
                    outer.release.wait(120)
                return super().push(repo_path, post)

        self.backend = Slow(git=ss.Spy(), expected_origin=ss.LOCAL_ORIGIN, fetcher=ss.FakeWorld().fetcher)
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend, repo=None, git=ss.Spy(), clock=REAL_CLOCK)
        self.ctx.expected_origin = ss.LOCAL_ORIGIN
        self.ctx.settings.save_repo_path(str(self.work))
        self.journal = Journal(self.ctx.workspace.journal_dir)

    def test_two_posts_from_two_threads_are_published_one_after_the_other_without_any_manual_git(self):
        first = ss.make_approved(self.ctx, title="첫째 글 에너지 절약")
        second = ss.make_approved(self.ctx, title="둘째 글 겨울 난방비")
        base = ss.git(self.work, "rev-parse", "HEAD")
        results = {}

        def run(name, project_id):
            try:
                results[name] = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True, wait=False)
            except BaseException as error:               # 스레드 밖에서 확인한다
                results[name] = error

        thread_a = threading.Thread(target=run, args=("a", first))
        thread_a.start()
        self.assertTrue(self.reached.wait(120), "첫 글이 push 에 닿았다")
        head_a = ss.git(self.work, "rev-parse", "HEAD")
        self.assertNotEqual(head_a, base, "첫 글은 commit 했다")
        thread_b = threading.Thread(target=run, args=("b", second))
        thread_b.start()
        time.sleep(2.5)                                   # 둘째가 끼어들 틈을 준다
        self.assertTrue(thread_b.is_alive(), "둘째는 저장소 잠금을 기다리는 중이다")
        self.assertEqual(ss.git(self.work, "rev-parse", "HEAD"), head_a, "둘째는 commit 을 더하지 않았다(올리지 않은 commit 이 둘이 되지 않는다)")
        self.assertEqual(ss.status_of(self.ctx, second), st.APPROVED)
        self.assertIsNone(self.journal.read(second))
        self.release.set()
        thread_a.join(240)
        thread_b.join(240)
        for name in ("a", "b"):
            self.assertNotIsInstance(results.get(name), BaseException, results.get(name))
            self.assertEqual(results[name].status, st.PUSHED)
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{base}..main"), "2", "원격에 두 글이 모두 올라갔다")
        self.assertEqual(ss.git(self.origin, "diff", "--name-only", f"{base}..main").count("_posts/"), 2)
        self.assertEqual(ss.git(self.work, "rev-list", "--count", "refs/remotes/origin/main..HEAD"), "0", "올리지 않은 commit 이 남지 않았다")
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(sorted(path.name for path in self.ctx.workspace.journal_dir.iterdir()), sorted([f"{first}.json", f"{second}.json"]), "잠금 파일이 남지 않았다")
        for project_id in (first, second):
            self.assertEqual((self.journal.read(project_id).stage, ss.status_of(self.ctx, project_id)), (STAGE_PUSHED, st.PUSHED))
        paths = {self.journal.read(project_id).path for project_id in (first, second)}
        self.assertEqual(len(paths), 2, "두 글의 파일 이름(시각)이 같지 않다")
        self.assertTrue(any("기다린 뒤" in note for note in results["b"].notes), results["b"].notes)


# ---- 진짜 프로세스 둘 -------------------------------------------------------------------------------------------------------------
CHILD = textwrap.dedent('''
    import os, sys, time
    sys.path.insert(0, sys.argv[1])
    sys.path.insert(0, sys.argv[2])
    import service_support as ss
    from chanceblog_desktop.service import cli
    from chanceblog_desktop.service.backend import GitPagesBackend
    from chanceblog_desktop.service.context import make_context

    data, repo, project_id, hold_at, reached, go, lock_wait = sys.argv[3:10]


    class Slow(GitPagesBackend):
        def _hold(self, name):
            if hold_at == name:
                open(reached, "w").close()                                  # 잠금을 쥔 채 이 지점에서 멈춘다
                end = time.time() + 240
                while not os.path.exists(go) and time.time() < end:
                    time.sleep(0.05)

        def commit(self, repo_path, post, title):
            info = super().commit(repo_path, post, title)
            self._hold("commit")
            return info

        def push(self, repo_path, post):
            self._hold("push")
            return super().push(repo_path, post)


    world = ss.FakeWorld()
    backend = Slow(expected_origin=ss.LOCAL_ORIGIN, fetcher=world.fetcher, sleep=world.sleep, monotonic=world.clock)
    ctx = make_context(data_dir=data, repo=repo, backend=backend, expected_origin=ss.LOCAL_ORIGIN)
    ctx.lock_wait = float(lock_wait)
    sys.exit(cli.main(["publish-pages", project_id, "--yes", "--no-wait"], ctx=ctx))
''')

DIE_HOLDING_THE_REPO = textwrap.dedent('''
    import os, sys
    sys.path.insert(0, sys.argv[1])
    sys.path.insert(0, sys.argv[2])
    from datetime import datetime, timedelta, timezone
    from chanceblog_desktop.service.context import make_context
    from chanceblog_desktop.service.lock import RepoLock

    data, repo = sys.argv[3:5]
    ctx = make_context(data_dir=data, repo=repo)
    RepoLock(ctx.workspace.journal_dir, repo, now=lambda: datetime.now(timezone.utc)).acquire()
    os._exit(9)                                                              # 풀지 않고 갑자기 끝난다
''')


@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class TwoRealProcessesDifferentPostsTest(unittest.TestCase):
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
        self.journal = Journal(self.ctx.workspace.journal_dir)
        self.script = self.tmp / "child.py"
        self.script.write_text(CHILD, encoding="utf-8")
        self.base = ss.git(self.work, "rev-parse", "HEAD")
        self.first = ss.make_approved(self.ctx, title="첫째 글 에너지 절약")
        self.second = ss.make_approved(self.ctx, title="둘째 글 겨울 난방비")

    def env(self):
        env = {key: value for key, value in os.environ.items() if key not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA")}
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def spawn(self, project_id, *, hold="-", wait=120, name="x"):
        reached, go = self.tmp / f"reached-{name}", self.tmp / "go"
        args = [sys.executable, "-X", "utf8", str(self.script), str(ss.ROOT / "src"), str(ss.ROOT / "tests"), str(self.ctx.workspace.root), str(self.work), project_id, hold, str(reached), str(go), str(wait)]
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env())
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        return process, reached

    def wait_for(self, path, process, seconds=180):
        end = time.time() + seconds
        while not path.exists():
            if process.poll() is not None:
                self.fail(f"자식 프로세스가 기다리는 지점에 닿기 전에 끝났다: {process.communicate()}")
            if time.time() > end:
                process.kill()
                self.fail("자식 프로세스가 기다리는 지점에 닿지 못했다")
            time.sleep(0.05)

    def release(self):
        (self.tmp / "go").write_text("go", encoding="utf-8")

    def finish(self, process, seconds=300):
        out, err = process.communicate(timeout=seconds)
        return process.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def new_posts(self):
        return [line for line in ss.git(self.origin, "diff", "--name-only", f"{self.base}..main").splitlines() if line.startswith("_posts/")]

    def assert_both_published(self, label):
        self.assertEqual(len(self.new_posts()), 2, f"{label}: 원격에 두 글이 모두 올라갔다")
        self.assertEqual(ss.git(self.origin, "rev-list", "--count", f"{self.base}..main"), "2", label)
        self.assertEqual(ss.git(self.work, "rev-list", "--count", "refs/remotes/origin/main..HEAD"), "0", f"{label}: 올리지 않은 commit 이 남지 않았다")
        self.assertEqual(ss.git(self.work, "status", "--porcelain", "--untracked-files=all"), "", label)
        for project_id in (self.first, self.second):
            self.assertEqual(ss.status_of(self.ctx, project_id), st.PUSHED, label)
        self.assertEqual(sorted(path.name for path in self.ctx.workspace.journal_dir.iterdir()), sorted([f"{self.first}.json", f"{self.second}.json"]), f"{label}: 잠금 파일이 남지 않았다")
        self.assertEqual(len({self.journal.read(project_id).path for project_id in (self.first, self.second)}), 2, f"{label}: 두 글의 파일 이름이 같지 않다")

    def test_the_second_post_waits_while_the_first_pushes_then_both_are_published_and_the_same_post_never_waits(self):
        first, reached = self.spawn(self.first, hold="push", wait=0, name="a")
        self.wait_for(reached, first)
        head = ss.git(self.work, "rev-parse", "HEAD")
        second, _ = self.spawn(self.second, wait=240, name="b")
        again, _ = self.spawn(self.first, wait=240, name="a2")
        code, out, err = self.finish(again, 120)                                           # 같은 글은 저장소를 기다리지 않고 바로 글 잠금에서 물러난다
        self.assertEqual(code, 1, err)
        self.assertIn("PUBLISH_IN_PROGRESS", err)
        end = time.time() + 180
        while not (self.ctx.workspace.journal_dir / f"{self.second}.lock").exists():       # 둘째가 글 잠금을 잡고 저장소 잠금을 기다리는 중
            self.assertIsNone(second.poll(), "둘째가 저장소 잠금을 기다리기 전에 끝났다")
            self.assertLess(time.time(), end)
            time.sleep(0.05)
        time.sleep(2.0)
        self.assertIsNone(second.poll(), "둘째는 아직 기다리는 중이다")
        self.assertEqual(ss.git(self.work, "rev-parse", "HEAD"), head, "둘째는 commit 을 더하지 않았다")
        self.assertIsNone(self.journal.read(self.second))
        self.assertEqual(ss.status_of(self.ctx, self.second), st.APPROVED)
        self.release()
        code_a, out_a, err_a = self.finish(first)
        code_b, out_b, err_b = self.finish(second)
        self.assertEqual((code_a, code_b), (0, 0), f"{err_a} | {err_b}")
        self.assertIn("기다립니다", err_b, "기다리는 동안 진행을 알렸다")
        self.assertIn("기다린 뒤 올렸습니다", out_b)
        self.assert_both_published("기다리기")

    def test_with_no_waiting_the_second_post_steps_back_without_changing_anything_and_the_same_command_works_later(self):
        first, reached = self.spawn(self.first, hold="commit", wait=0, name="a")
        self.wait_for(reached, first)                                                      # 첫째는 commit 만 하고 쥔 채 멈춰 있다
        head = ss.git(self.work, "rev-parse", "HEAD")
        second, _ = self.spawn(self.second, wait=0, name="b")
        code, out, err = self.finish(second, 180)
        self.assertEqual(code, 1, err)
        self.assertIn("PUBLISH_REPO_BUSY", err)
        self.assertIn("같은 명령을 다시", err)
        self.assertEqual(ss.git(self.work, "rev-parse", "HEAD"), head, "물러난 쪽은 commit 도 하지 않았다")
        self.assertEqual(ss.status_of(self.ctx, self.second), st.APPROVED)
        self.assertIsNone(self.journal.read(self.second))
        self.assertFalse((self.ctx.workspace.journal_dir / f"{self.second}.lock").exists(), "글 잠금도 남기지 않았다")
        self.assertEqual(ss.git(self.origin, "rev-parse", "main"), self.base, "아직 아무것도 올라가지 않았다")
        self.release()
        self.assertEqual(self.finish(first)[0], 0)
        again, _ = self.spawn(self.second, wait=0, name="b2")                              # 안내대로 같은 명령을 다시
        code, out, err = self.finish(again)
        self.assertEqual(code, 0, err)
        self.assert_both_published("물러났다가 다시")

    def test_two_posts_started_at_any_gap_are_both_published_by_the_same_command(self):
        for index, gap in enumerate((0.5, 1.0, 1.5, 2.0)):
            with self.subTest(gap=gap):
                if index:
                    self.setUp()                                                          # 간격마다 새 저장소·새 글 둘
                first, _ = self.spawn(self.first, name="a")
                time.sleep(gap)
                second, _ = self.spawn(self.second, name="b")
                results = [self.finish(first), self.finish(second)]
                self.assertEqual([item[0] for item in results], [0, 0], [item[2] for item in results])
                self.assert_both_published(f"간격 {gap}초")

    def test_a_repository_lock_left_by_a_process_that_died_is_taken_over_at_once(self):
        script = self.tmp / "die.py"
        script.write_text(DIE_HOLDING_THE_REPO, encoding="utf-8")
        done = subprocess.run([sys.executable, "-X", "utf8", str(script), str(ss.ROOT / "src"), str(ss.ROOT / "tests"), str(self.ctx.workspace.root), str(self.work)], capture_output=True, env=self.env(), timeout=120)
        self.assertEqual(done.returncode, 9, done.stderr.decode("utf-8", "replace"))
        leftover = list(self.ctx.workspace.journal_dir.glob("repo-*.lock"))
        self.assertEqual(len(leftover), 1, "죽은 프로세스가 남긴 저장소 잠금")
        started = time.time()
        process, _ = self.spawn(self.first, wait=0, name="a")                              # 기다림 0 — 넘겨받지 못하면 곧바로 PUBLISH_REPO_BUSY 가 된다
        code, out, err = self.finish(process)
        self.assertEqual(code, 0, err)
        self.assertLess(time.time() - started, 120)
        self.assertIn("이 저장소에 글을 올리다 멈춘 흔적(그 프로세스는 이미 끝나 있음)을 넘겨받았습니다", out)
        self.assertEqual(list(self.ctx.workspace.journal_dir.glob("repo-*.lock")), [], "넘겨받은 잠금도 끝나고 풀었다")
        second, _ = self.spawn(self.second, name="b")
        self.assertEqual(self.finish(second)[0], 0)
        self.assert_both_published("죽은 잠금")


if __name__ == "__main__":
    unittest.main()
