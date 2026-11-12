"""백업·복원 카드의 실제 공급자(`ui/backups_adapter.py`) 시험 — 서비스(`service/backup_flow.py`)를 진짜 임시 폴더에서 돌려 화면이 아는 모양으로 바꾸는 얇은 어댑터가 옳게 잇는지 본다(BACKUPUI).

지키는 것:
  1) 목록 읽기는 읽기뿐이다 — 데이터 폴더 파일이 한 바이트도 안 바뀌고 없는 폴더를 만들지 않는다. 직접 정한 데이터 폴더가 없거나 안전하지 않으면 쉬운 안내다.
  2) 백업 만들기·복원의 결과가 서비스의 결과와 같고(이름·상태·파일 줄·시각·안전 사본·알림) 진행이 앞으로만 간다. 취소하면 임시 폴더를 남기지 않는다.
  3) 서비스 오류는 **종류**(키 모양 발견·담을 것 없음·다른 작업 중·백업이 깨짐·더 새로운 프로그램·저장 공간·쓰기 실패·복원 중 문제)로만 바뀐다 — 실패 객체에는 키 글자·경로·예외 문구가 없고 호출 흔적도 이어지지 않는다.
  4) 키 모양이 발견되면 위치 줄(어느 칸·몇 번째 줄·유형)만 실리고 키 글자는 어디에도 없다. 되돌리다 또 실패하면 되돌리지 못한 것의 이름이 실린다.
  5) 컨트롤러와 함께 돌려도 같다 — 만들고 읽고 되돌리는 흐름, 실패 안내, 그리고 키를 등록한 채여도 컨트롤러·뷰모델 어디에도 키가 없다.
네트워크·실제 자격 증명 관리자 없이 돈다.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security.backup_note import RESTORE_NOTE  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service import connections, projects  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402
from chanceblog_desktop.ui import adapters, backups_adapter  # noqa: E402
from chanceblog_desktop.ui.core import backup_view, backups, jobs  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

S = bs.S


def quiet(*_):
    return None


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = bs.World(self.tmp.name)
        self.ctx = self.world.ctx
        self.provider = backups_adapter.ServiceBackupsProvider(str(self.world.root), context_factory=lambda data_dir=None: self.ctx)

    def create(self):
        return self.provider.create_backup(quiet, lambda: False)

    def failure_of(self, call, *args):
        with self.assertRaises(backups.BackupFailure) as caught:
            call(*args)
        return caught.exception

    def assert_clean(self, failure, *tokens):
        """실패 객체 어디에도 키 글자·경로·예외 문구가 없고 호출 흔적이 이어지지 않는다."""
        blob = " ".join([failure.user_message, failure.code, failure.kind, failure.reason, *failure.summary, *failure.notes, repr(failure), str(failure)])
        for token in tokens:
            self.assertFalse(S.leaked(blob, token), "키 글자가 실패 객체에 있다")
        self.assertNotIn(str(self.world.root), blob)
        self.assertNotIn("Traceback", blob)
        self.assertIsNone(failure.__context__)
        self.assertIsNone(failure.__cause__)


class LoadTest(Base):
    def test_the_list_is_read_only_and_creates_nothing(self):
        before = self.world.data_digests()
        data = self.provider.load_backups(quiet, lambda: False)
        self.assertEqual((data.rows, data.location, data.keep, data.sample), ((), str(self.ctx.workspace.backups_dir), bf.KEEP_BACKUPS, False))
        self.assertEqual(self.world.data_digests(), before)
        self.assertFalse(self.ctx.workspace.backups_dir.exists())

    def test_the_rows_match_what_the_service_lists(self):
        made = bf.create_full_backup(self.ctx)
        self.ctx.clock.advance(seconds=30)
        bf.restore_full_backup(self.ctx, made.row.name, confirmed=True)
        data = self.provider.load_backups(quiet, lambda: False)
        service = bf.list_full_backups(self.ctx)
        self.assertEqual([(row.name, row.kind, row.created_at, row.status, row.size, row.problem, row.app_version) for row in data.rows],
                         [(row.name, row.kind, row.created_at, row.status, row.size, row.problem, row.app_version) for row in service.rows])
        for mine, theirs in zip(data.rows, service.rows):
            self.assertEqual([(line.name, line.label, line.state, line.size, line.items, line.reason) for line in mine.files],
                             [(line.name, line.label, line.state, line.size, tuple(line.items), line.reason) for line in theirs.files])
        self.assertEqual({row.kind for row in data.rows}, {"backup", "safety"})

    def test_a_broken_backup_keeps_the_reason_name_so_the_card_can_say_why(self):
        """깨진 줄은 이유 이름(`files`·`manifest`)을 잃지 않는다 — 카드가 '파일이 빠졌거나 바뀌었어요' 와 '목록 파일을 읽을 수 없어요' 를 가려 말한다."""
        made = bf.create_full_backup(self.ctx)
        folder = self.ctx.workspace.backups_dir / made.row.name
        (folder / layout.SEEDS_FILE).unlink()
        row = self.provider.load_backups(quiet, lambda: False).rows[0]
        self.assertEqual((row.status, row.problem), ("broken", "files"))
        (folder / bf.MANIFEST_NAME).write_bytes(b"not json at all")
        row = self.provider.load_backups(quiet, lambda: False).rows[0]
        self.assertEqual((row.status, row.problem), ("broken", "manifest"))

    def test_an_explicit_data_folder_that_is_not_a_folder_gets_the_plain_message(self):
        missing = backups_adapter.ServiceBackupsProvider(str(Path(self.tmp.name) / "없는 폴더"), context_factory=lambda data_dir=None: self.ctx)
        with self.assertRaises(adapters.ServiceFailure) as caught:
            missing.load_backups(quiet, lambda: False)
        self.assertEqual((caught.exception.user_message, caught.exception.code), (T["data_dir_missing"], "DATA_DIR_NOT_FOUND"))

    def test_an_unsafe_data_folder_gets_the_screen_sentence_not_the_catalog_text(self):
        def refuse(data_dir=None):
            raise AppError("DATA_DIR_UNSAFE", {"경로": "C:\\저장소"})
        provider = backups_adapter.ServiceBackupsProvider(str(self.world.root), context_factory=refuse)
        with self.assertRaises(adapters.ServiceFailure) as caught:
            provider.load_backups(quiet, lambda: False)
        self.assertEqual(caught.exception.user_message, T["conn_dir_unsafe"])

    def test_cancelling_a_read_raises_the_cancel(self):
        with self.assertRaises(jobs.JobCancelled):
            self.provider.load_backups(quiet, lambda: True)


class CreateTest(Base):
    def test_a_backup_is_made_and_the_result_matches_the_service(self):
        seen = []
        result = self.provider.create_backup(lambda fraction, text="": seen.append((fraction, text)), lambda: False)
        self.assertEqual((result.action, result.status), ("created", "complete"))
        self.assertRegex(result.name, r"^full-\d{8}-\d{6}$")
        self.assertEqual(result.created_at, "2026-11-02T01:30:12Z")
        self.assertEqual([(line.name, line.state) for line in result.files], [(name, "saved") for name in bf.BY_NAME])
        self.assertEqual(seen and [fraction for fraction, _ in seen], sorted(fraction for fraction, _ in seen))
        self.assertEqual(seen[-1][0], 1.0)
        self.assertTrue(all(isinstance(text, str) and text for _, text in seen))
        self.assertEqual([row.name for row in self.provider.load_backups(quiet, lambda: False).rows], [result.name])

    def test_a_partial_backup_keeps_the_reason_codes_for_the_card(self):
        self.world.path(layout.SEEDS_FILE).write_text("{ 깨짐", encoding="utf-8")
        result = self.create()
        self.assertEqual(result.status, "partial")
        self.assertEqual([(line.name, line.reason) for line in result.files if line.state == "skipped"], [(layout.SEEDS_FILE, "TOPIC_FILE_INVALID")])

    def test_a_key_shape_in_the_data_is_reported_by_place_and_kind_only(self):
        for kind in bs.KINDS:
            with self.subTest(kind=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World(tmp)
                    bs.plant_post(world, bs.three_lines(kind))
                    provider = backups_adapter.ServiceBackupsProvider(str(world.root), context_factory=lambda data_dir=None, ctx=world.ctx: ctx)
                    failure = self.failure_of(provider.create_backup, quiet, lambda: False)
                    self.assertEqual((failure.kind, failure.code), ("blocked", "FULL_BACKUP_BLOCKED"))
                    self.assertTrue(failure.summary and any("3번째 줄" in line for line in failure.summary))
                    self.assertEqual(failure.user_message, T["backup_fail_blocked"])
                    self.assertFalse(S.leaked(" ".join([failure.user_message, *failure.summary, repr(failure)]), bs.secret_token(kind)))

    def test_every_service_failure_becomes_a_kind_with_the_fixed_sentence(self):
        cases = (
            ("nothing", AppError("CONTENT_NOT_FOUND", {"항목": "백업할 데이터"}), "CONTENT_NOT_FOUND"), ("busy", AppError("BACKUP_IN_PROGRESS", {"시작": "방금"}), "BACKUP_IN_PROGRESS"),
            ("disk", AppError("DISK_FULL"), "DISK_FULL"), ("io", AppError("FILE_WRITE_FAILED", {"경로": "x"}), "FILE_WRITE_FAILED"), ("io", AppError("FILE_PATH_TOO_LONG"), "FILE_PATH_TOO_LONG"),
            ("io", AppError("FILE_IN_USE", {"경로": "x"}), "FILE_IN_USE"), ("newer", AppError("STORE_VERSION_UNSUPPORTED", {"파일": "x"}), "STORE_VERSION_UNSUPPORTED"), ("invalid", AppError("FULL_BACKUP_INVALID", {"파일": "x", "이유": "y"}), "FULL_BACKUP_INVALID"),
            ("other", AppError("UNEXPECTED_ERROR"), "UNEXPECTED_ERROR"), ("other", AppError("BACKUP_FAILED"), "BACKUP_FAILED"))
        for kind, error, code in cases:
            with self.subTest(code=code):
                with mock.patch.object(bf, "create_full_backup", side_effect=error):
                    failure = self.failure_of(self.provider.create_backup, quiet, lambda: False)
                self.assertEqual((failure.kind, failure.code, failure.user_message), (kind, code, T["backup_fail_" + kind]))
                self.assert_clean(failure)

    def test_real_failures_of_the_service_map_to_the_same_kinds(self):
        with mock.patch.object(bf, "_write_sqlite", side_effect=sqlite3.OperationalError("database or disk is full")):
            self.assertEqual(self.failure_of(self.provider.create_backup, quiet, lambda: False).kind, "disk")
        with mock.patch.object(bf, "_make_folder", side_effect=PermissionError(13, "denied")):
            self.assertEqual(self.failure_of(self.provider.create_backup, quiet, lambda: False).kind, "io")
        for name in bf.BY_NAME:
            if name.endswith(".db"):
                self.world.path(name).write_bytes(b"garbage " * 40)
            else:
                self.world.path(name).write_text("{ 깨짐", encoding="utf-8")
        nothing = self.failure_of(self.provider.create_backup, quiet, lambda: False)
        self.assertEqual((nothing.kind, nothing.code), ("nothing", "BACKUP_FAILED"))
        with bf._flow_lock(self.ctx):
            self.assertEqual(self.failure_of(self.provider.create_backup, quiet, lambda: False).kind, "busy")

    def test_an_unexpected_exception_becomes_other_with_only_the_exception_name(self):
        key = bs.secret_text("google_api_key")
        with mock.patch.object(bf, "create_full_backup", side_effect=ValueError("C:\\Users\\누군가 " + key)):
            failure = self.failure_of(self.provider.create_backup, quiet, lambda: False)
        self.assertEqual((failure.kind, failure.code), ("other", "ValueError"))
        self.assert_clean(failure, bs.secret_token("google_api_key"))
        self.assertNotIn("Users", repr(failure))

    def test_cancelling_leaves_nothing_behind(self):
        with self.assertRaises(jobs.JobCancelled):
            self.provider.create_backup(quiet, lambda: True)
        count = []

        def cancelled():
            count.append(1)
            return len(count) > 3
        with self.assertRaises(jobs.JobCancelled):
            self.provider.create_backup(quiet, cancelled)
        self.assertEqual(list(self.ctx.workspace.backups_dir.iterdir()) if self.ctx.workspace.backups_dir.exists() else [], [])
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])


class RestoreTest(Base):
    def test_a_restore_result_matches_the_service(self):
        made = self.create()
        projects.new_project(self.ctx, "백업 뒤에 쓴 글", "새 본문")
        seen = []
        self.ctx.clock.advance(seconds=30)
        result = self.provider.restore_backup(made.name, lambda fraction, text="": seen.append(fraction), lambda: False)
        self.assertEqual((result.action, result.status, result.name), ("restored", "complete", made.name))
        self.assertRegex(result.safety, r"^before-\d{8}-\d{6}$")
        self.assertEqual([(line.name, line.state) for line in result.files], [(name, "restored") for name in bf.BY_NAME])
        self.assertIn(RESTORE_NOTE, result.notes)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)
        self.assertEqual(len(projects.list_projects(self.ctx)), 2)
        kinds = {row.name: row.kind for row in self.provider.load_backups(quiet, lambda: False).rows}
        self.assertEqual(kinds[result.safety], "safety")

    def test_the_adapter_hands_the_service_the_confirmation_it_got_from_the_dialog(self):
        made = self.create()
        real = bf.restore_full_backup
        with mock.patch.object(bf, "restore_full_backup", side_effect=real) as spy:
            self.provider.restore_backup(made.name, quiet, lambda: False)
        self.assertIs(spy.call_args.kwargs["confirmed"], True)

    def test_a_changed_backup_a_missing_name_and_a_newer_backup_map_to_their_kinds(self):
        made = self.create()
        folder = self.ctx.workspace.backups_dir / made.name
        original = (folder / "seeds.json").read_bytes()
        (folder / "seeds.json").write_bytes(original + b" ")
        invalid = self.failure_of(self.provider.restore_backup, made.name, quiet, lambda: False)
        self.assertEqual((invalid.kind, invalid.code, invalid.user_message), ("invalid", "FULL_BACKUP_INVALID", T["backup_fail_invalid"]))
        (folder / "seeds.json").write_bytes(original)
        self.assertEqual(self.failure_of(self.provider.restore_backup, "full-19990101-000000", quiet, lambda: False).kind, "invalid")
        with mock.patch.object(bf, "read_app_version", return_value="0.0.0"):
            newer = self.create()
        manifest = json.loads((self.ctx.workspace.backups_dir / newer.name / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        manifest["app_version"] = "99.0.0"
        bs.write_manifest(self.ctx.workspace.backups_dir / newer.name, manifest)
        self.assertEqual(self.failure_of(self.provider.restore_backup, newer.name, quiet, lambda: False).kind, "newer")

    def test_a_key_shape_inside_the_backup_is_blocked_and_the_text_says_the_app_cannot_fix_it(self):
        made = self.create()
        folder = self.ctx.workspace.backups_dir / made.name
        data = json.loads((folder / "seeds.json").read_text(encoding="utf-8"))
        data["seeds"][0]["keyword"] = bs.secret_text("github_token")
        (folder / "seeds.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = json.loads((folder / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        import hashlib
        manifest["files"]["seeds.json"].update(size=(folder / "seeds.json").stat().st_size, sha256=hashlib.sha256((folder / "seeds.json").read_bytes()).hexdigest())
        bs.write_manifest(folder, manifest)
        failure = self.failure_of(self.provider.restore_backup, made.name, quiet, lambda: False)
        self.assertEqual(failure.kind, "blocked")
        self.assertIn("이 백업 안의 글이라 앱이 고치지 않아요", failure.summary[-1])
        self.assert_clean(failure, bs.secret_token("github_token"))

    def test_a_failure_in_the_middle_is_a_restore_failure_with_its_reason_and_the_names_not_put_back(self):
        made = self.create()
        projects.new_project(self.ctx, "백업 뒤에 쓴 글", "새 본문")
        before = self.world.data_digests()
        with mock.patch.object(bf, "_restore_database", side_effect=sqlite3.OperationalError("disk I/O error")):
            failure = self.failure_of(self.provider.restore_backup, made.name, quiet, lambda: False)
        self.assertEqual((failure.kind, failure.code, failure.reason, failure.notes), ("restore", "RESTORE_FAILED", "io", ()))
        self.assertEqual(self.world.data_digests(), before)
        self.assert_clean(failure)
        calls, real = [], bf._restore_database

        def flaky(component, path, source):
            calls.append(component.name)
            if len(calls) == 1:
                return real(component, path, source)
            raise sqlite3.OperationalError("disk I/O error")
        with mock.patch.object(bf, "_restore_database", flaky):
            failure = self.failure_of(self.provider.restore_backup, made.name, quiet, lambda: False)
        self.assertEqual(failure.kind, "restore")
        self.assertTrue(any("글 보관함" in note for note in failure.notes), failure.notes)
        self.assert_clean(failure)

    def test_cancelling_before_or_during_a_restore_leaves_the_data_as_it_was(self):
        made = self.create()
        projects.new_project(self.ctx, "백업 뒤에 쓴 글", "새 본문")
        before = {name: (self.world.path(name).read_bytes() if name not in ("chanceblog.db", layout.ENGINE_DB_FILE) else b"") for name in bf.BY_NAME}
        with self.assertRaises(jobs.JobCancelled):
            self.provider.restore_backup(made.name, quiet, lambda: True)
        count = []

        def cancelled():
            count.append(1)
            return len(count) > 6
        with self.assertRaises(jobs.JobCancelled):
            self.provider.restore_backup(made.name, quiet, cancelled)
        self.assertEqual({name: (self.world.path(name).read_bytes() if name not in ("chanceblog.db", layout.ENGINE_DB_FILE) else b"") for name in bf.BY_NAME}, before)
        self.assertEqual(len(projects.list_projects(self.ctx)), 3, "글 보관함은 그대로(원복했다)")
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])


class InterruptedTest(Base):
    """복원이 중간에 멈춘 흔적(D-463)을 서비스에서 읽어 화면의 모양으로 바꾸고, 되돌리기가 서비스의 되돌리기를 부른다."""

    def stop_a_restore_in_the_middle(self):
        made = self.create()
        projects.new_project(self.ctx, "백업 뒤에 쓴 글", "새 본문")
        self.ctx.clock.advance(seconds=30)
        with mock.patch.object(bf, "_apply", side_effect=KeyboardInterrupt()), mock.patch.object(bf, "_roll_back", return_value=("설정은 돌리지 못했어요",)):
            with self.assertRaises(KeyboardInterrupt):
                bf.restore_full_backup(self.ctx, made.name, confirmed=True)
        return made

    def test_a_normal_list_has_no_interrupted_trace(self):
        self.create()
        self.assertIsNone(self.provider.load_backups(quiet, lambda: False).interrupted)

    def test_the_trace_is_read_from_the_service_as_names_and_times_only(self):
        made = self.stop_a_restore_in_the_middle()
        pending = self.provider.load_backups(quiet, lambda: False).interrupted
        self.assertIsInstance(pending, backups.InterruptedData)
        self.assertEqual((pending.backup, pending.can_revert), (made.name, True))
        self.assertRegex(pending.safety, r"^before-\d{8}-\d{6}$")
        self.assertRegex(pending.started_at, r"^\d{4}-\d{2}-\d{2}T[0-9:]{8}Z$")
        self.assertNotIn(str(self.world.root), repr(pending))

    def test_loading_still_writes_nothing_when_there_is_a_trace(self):
        self.stop_a_restore_in_the_middle()
        before = self.world.data_digests()
        marker = bf._marker_path(self.ctx).read_bytes()
        self.provider.load_backups(quiet, lambda: False)
        self.assertEqual((self.world.data_digests(), bf._marker_path(self.ctx).read_bytes()), (before, marker))

    def test_reverting_brings_the_data_back_with_the_service_semantics_and_clears_the_trace(self):
        made = self.stop_a_restore_in_the_middle()
        pending = self.provider.load_backups(quiet, lambda: False).interrupted
        self.ctx.clock.advance(seconds=30)
        seen = []
        result = self.provider.revert_interrupted(lambda fraction, text="": seen.append(fraction), lambda: False)
        self.assertEqual((result.action, result.status, result.name), ("restored", "complete", pending.safety))
        self.assertRegex(result.safety, r"^before-\d{8}-\d{6}$")
        self.assertEqual(seen, sorted(seen))
        self.assertIsNone(self.provider.load_backups(quiet, lambda: False).interrupted)
        self.assertEqual(len(projects.list_projects(self.ctx)), 3, "복원 직전의 글 둘(원래 둘 + 백업 뒤에 쓴 하나)")
        self.assertIsNotNone(made)

    def test_the_adapter_hands_the_service_the_confirmation_it_got_from_the_dialog(self):
        self.stop_a_restore_in_the_middle()
        real = bf.revert_interrupted_restore
        with mock.patch.object(bf, "revert_interrupted_restore", side_effect=real) as spy:
            self.provider.revert_interrupted(quiet, lambda: False)
        self.assertIs(spy.call_args.kwargs["confirmed"], True)

    def test_without_a_trace_or_a_safety_copy_the_failure_has_a_fixed_sentence(self):
        failure = self.failure_of(self.provider.revert_interrupted, quiet, lambda: False)
        self.assertEqual(failure.kind, "nothing")
        self.assert_clean(failure)
        self.stop_a_restore_in_the_middle()
        import shutil
        pending = self.provider.load_backups(quiet, lambda: False).interrupted
        self.assertTrue(pending.can_revert, "시험의 전제 — 안전 사본이 있을 때는 되돌릴 수 있다")
        shutil.rmtree(self.ctx.workspace.backups_dir / bf.SAFETY_FOLDER / pending.safety)
        gone = self.provider.load_backups(quiet, lambda: False).interrupted
        self.assertEqual((gone.safety, gone.can_revert), (pending.safety, False), "안전 사본이 없어졌으면 서비스가 말한 '되돌릴 수 없다' 를 그대로 옮긴다")
        failure = self.failure_of(self.provider.revert_interrupted, quiet, lambda: False)
        self.assertEqual(failure.kind, "invalid")
        self.assert_clean(failure)

    def test_cancelling_a_revert_before_it_starts_raises_the_cancel_and_changes_nothing(self):
        self.stop_a_restore_in_the_middle()
        before = self.world.data_digests()
        with self.assertRaises(jobs.JobCancelled):
            self.provider.revert_interrupted(quiet, lambda: True)
        self.assertEqual(self.world.data_digests(), before)

    def test_the_whole_flow_through_the_controller(self):
        controller = backup_view.BackupController(self.provider, jobs.JobRunner())
        self.stop_a_restore_in_the_middle()
        controller.apply_loaded(self.provider.load_backups(quiet, lambda: False))
        box = controller.view()["interrupted"]
        self.assertEqual((box["text"], box["revert"]["enabled"]), (T["backup_interrupted_can"], True))
        results = []
        status, job = controller.start_revert(confirmed=True, on_done=lambda result, _payload: results.append(result), on_error=lambda failure, _payload: results.append(failure))
        self.assertEqual(status, "started")
        job.join(30)
        controller.apply_write_ok(results[0])
        controller.apply_loaded(self.provider.load_backups(quiet, lambda: False))
        self.assertIsNone(controller.view()["interrupted"])
        self.assertEqual(controller.notice[:2], ("ok", T["backup_ok_restored"]))


class WithTheControllerTest(Base):
    CANARY = "CANARY_" + "Qw3rTy5uIo7pAs9d"

    def setUp(self):
        super().setUp()
        self.runner = jobs.JobRunner()
        self.controller = backup_view.BackupController(self.provider, self.runner)

    def run_write(self, starter):
        results = []
        status, job = starter(on_done=lambda result, _payload: results.append(("ok", result)), on_error=lambda failure, _payload: results.append(("err", failure)), on_cancel=lambda _payload: results.append(("cancel", None)))
        self.assertEqual(status, "started")
        job.join(30)
        kind, value = results[0]
        (self.controller.apply_write_ok if kind == "ok" else self.controller.apply_write_failed)(value)
        if self.controller.reload_wanted:
            self.controller.reload_wanted = False
            self.controller.apply_loaded(self.provider.load_backups(quiet, lambda: False))
        return kind, value

    def test_create_list_and_restore_through_the_controller(self):
        self.controller.apply_loaded(self.provider.load_backups(quiet, lambda: False))
        self.assertEqual((self.controller.state, self.controller.view()["rows"]), ("empty", []))
        kind, result = self.run_write(lambda **callbacks: self.controller.start_create(**callbacks))
        self.assertEqual(kind, "ok")
        self.assertEqual(self.controller.notice[0], "ok")
        self.assertIn("2026-11-02 10:30", self.controller.notice[1])
        view = self.controller.view()
        self.assertEqual((view["state"], len(view["rows"])), ("normal", 1))
        self.assertEqual(view["rows"][0]["status"]["text"], T["backup_status_complete"])
        self.assertTrue(view["rows"][0]["restore"]["enabled"])
        self.ctx.clock.advance(seconds=30)
        kind, restored = self.run_write(lambda **callbacks: self.controller.start_restore(result.name, confirmed=True, **callbacks))
        self.assertEqual(kind, "ok")
        self.assertEqual(self.controller.notice[:2], ("ok", T["backup_ok_restored"]))
        rows = self.controller.view()["rows"]
        self.assertEqual(sorted(row["kind"]["text"] for row in rows), sorted([T["backup_kind_backup"], T["backup_kind_safety"]]))

    def test_a_key_shape_in_the_data_shows_places_and_kinds_in_the_notice_and_no_key(self):
        bs.plant_post(self.world, bs.three_lines("aws_access_key"))
        self.controller.apply_loaded(self.provider.load_backups(quiet, lambda: False))
        kind, failure = self.run_write(lambda **callbacks: self.controller.start_create(**callbacks))
        self.assertEqual(kind, "err")
        level, text, lines = self.controller.notice
        self.assertEqual((level, text), ("error", T["backup_fail_blocked"]))
        self.assertTrue(any("글 보관함" in line and "3번째 줄" in line and "AWS 액세스 키" in line for line in lines), lines)
        blob = json.dumps(self.controller.view(), ensure_ascii=False)
        self.assertFalse(S.leaked(blob, bs.secret_token("aws_access_key")))
        backups_dir = self.ctx.workspace.backups_dir
        self.assertEqual(list(backups_dir.iterdir()) if backups_dir.exists() else [], [], "부분 폴더를 남기지 않았다")

    def test_with_a_registered_key_nothing_of_it_reaches_the_controller_the_view_or_the_backup(self):
        connections.add_entry(self.ctx, "image_provider", name="내 이미지 키", fields={"access_key": self.CANARY}, provider="unsplash", keystore=self.ctx.keystore)
        self.controller.apply_loaded(self.provider.load_backups(quiet, lambda: False))
        _kind, result = self.run_write(lambda **callbacks: self.controller.start_create(**callbacks))
        self.ctx.clock.advance(seconds=30)
        self.run_write(lambda **callbacks: self.controller.start_restore(result.name, confirmed=True, **callbacks))
        blob = json.dumps(self.controller.view(), ensure_ascii=False) + repr(self.controller.__dict__) + repr(result)
        for name, data in bs.encodings(self.CANARY).items():
            self.assertNotIn(data.decode("utf-8", "ignore") if name.startswith("utf-8") else data.decode("latin-1"), blob, name)
        folder_bytes = bs.all_bytes(self.ctx.workspace.backups_dir)
        for name, data in bs.encodings(self.CANARY).items():
            self.assertNotIn(data, folder_bytes, name)

    def test_a_failure_the_service_raised_never_reaches_the_screen_text_as_it_was_written(self):
        self.controller.apply_loaded(self.provider.load_backups(quiet, lambda: False))
        key = S.google()
        with mock.patch.object(bf, "create_full_backup", side_effect=OSError("C:\\Users\\누군가\\데이터 " + key)):
            kind, failure = self.run_write(lambda **callbacks: self.controller.start_create(**callbacks))
        self.assertEqual((kind, failure.kind), ("err", "other"))
        shown = json.dumps(self.controller.view(), ensure_ascii=False)
        self.assertNotIn("누군가", shown, "예외 문구의 경로 조각이 화면에 없다(보이는 경로는 백업 위치 글자 하나뿐이다)")
        self.assertFalse(S.leaked(shown, key))
        self.assertEqual(self.controller.notice[1], T["backup_fail_other"])


class HomeProviderPairingTest(unittest.TestCase):
    def test_the_home_provider_hands_its_data_folder_and_factory_to_the_adapter(self):
        marker = object()
        provider = adapters.ServiceHomeProvider("C:\\어딘가", context_factory=marker).backups_provider()
        self.assertIsInstance(provider, backups_adapter.ServiceBackupsProvider)
        self.assertEqual((provider._data_dir, provider._factory), ("C:\\어딘가", marker))


if __name__ == "__main__":
    unittest.main()
