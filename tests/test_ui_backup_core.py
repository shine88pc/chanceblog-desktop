"""설정 화면의 백업·복원 카드(BACKUPUI)의 순수 규칙 시험 — 공급자 모양·가짜 공급자·`BackupController`(행동 가능 여부·쓰기 흐름·확인창·중복 클릭)·뷰모델·문구·소스 규칙. PySide6 없이 돈다.

지키는 것:
  1) **쓰기는 사용자가 단추를 눌렀을 때만, 한 번에 하나**(돌고 있으면 두 번째 클릭은 아무 일도 하지 않는다). 복원은 **확인(`confirmed is True`)이 먼저**이고 깨진 백업·없는 줄·읽기 전용 공급자·쓰는 중에는 시작하지 않는다.
  2) 실패 문장은 종류별 정해진 쉬운 말뿐이다 — 서비스 오류의 문구·경로·키 조각이 화면 글에 없다. 키 모양이 발견된 위치(어느 칸·몇 번째 줄·유형)만 줄로 보이고, 되돌리지 못한 것은 이름이 보인다.
  3) 모든 줄에 `Credential 제외됨` 글자 배지가 있고(깨진 줄만 없다) 상태(완료·부분·깨짐)는 글자로도 말한다. 보이는 글에 영문 상태 이름·내부 열쇠·오류 코드가 없다. 키 모양 글은 가린 뒤에 줄인다.
  4) 복원 확인창은 무엇이 바뀌는지·안전 사본 위치·되돌리는 법·키가 백업에 없다는 것을 말한다. 안전 사본('복원 직전 사본')도 같은 줄이고 같은 방법으로 복원한다.
  5) 이 파일들의 소스에는 파일 쓰기·하위 프로세스·네트워크·폴더 열기·파일 대화상자가 없다(새 외부 호출 0).
"""
import ast
import dataclasses
import json
import re
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import scan_samples as S  # noqa: E402

from chanceblog_desktop.security.backup_note import CREDENTIAL_NOTE, EXCLUDED, RESTORE_NOTE, SHORT_NOTE  # noqa: E402
from chanceblog_desktop.ui.core import app_state, backup_view, backups, jobs, services  # noqa: E402
from chanceblog_desktop.ui.core.text import FORBIDDEN, T  # noqa: E402

UI = ROOT / "src" / "chanceblog_desktop" / "ui"
CORE_FILES = [UI / "core" / "backups.py", UI / "core" / "backup_view.py", UI / "core" / "backup_text.py"]
PART_FILES = [UI / "qt" / "backup_parts.py", UI / "backups_adapter.py"]
INTERNAL = re.compile(r"\b(?:complete|partial|broken|backup|safety|saved|missing|skipped|restored|kept|failed|blocked|nothing|invalid|newer|manifest|FULL_BACKUP_[A-Z_]+|RESTORE_FAILED|BACKUP_[A-Z_]+|SAMPLE_[A-Z_]+|STORE_[A-Z_]+|TOPIC_[A-Z_]+)\b")
FIRST = "full-20261110-210500"
PARTIAL = "full-20261108-083000"
SAFETY = "before-20261110-100300"
SKIP_KEYS = frozenset({"name", "key", "tone", "state", "level", "fraction", "percent", "enabled", "writable", "busy", "sample"})


def visible_strings(value, skip=SKIP_KEYS):
    """뷰모델에서 사람에게 보이는 글만(열쇠·색 이름·수준·상태 이름 칸은 뺀다)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in skip:
                yield from visible_strings(item, skip)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from visible_strings(item, skip)


class Env:
    """가짜 공급자 + 실제 작업 스레드 틀 — 쓰기 하나를 실제 작업 스레드에서 돌리고 결과를 컨트롤러에 넘긴다(화면이 시그널로 하는 일을 시험이 직접 한다)."""

    def __init__(self, provider=None, **kwargs):
        self.runner = jobs.JobRunner()
        self.provider = provider or backups.FakeBackupsProvider(**kwargs)
        self.controller = backup_view.BackupController(self.provider, self.runner)
        self.progress = []
        self.reload()

    def reload(self):
        self.controller.apply_loaded(self.provider.load_backups(lambda *_: None, lambda: False))

    def run(self, starter):
        results = []
        status, job = starter(on_progress=lambda fraction, text: self.progress.append((fraction, text)), on_done=lambda result, _payload: results.append(("ok", result)),
                              on_error=lambda failure, _payload: results.append(("err", failure)), on_cancel=lambda _payload: results.append(("cancel", None)))
        if status != "started":
            return status, job
        job.join(10)
        kind, value = results[0]
        if kind == "ok":
            self.controller.apply_write_ok(value)
        elif kind == "err":
            self.controller.apply_write_failed(value)
        if self.controller.reload_wanted:
            self.controller.reload_wanted = False
            self.reload()
        return status, (kind, value)

    def create(self):
        return self.run(lambda **callbacks: self.controller.start_create(**callbacks))

    def restore(self, name, confirmed=True):
        return self.run(lambda **callbacks: self.controller.start_restore(name, confirmed=confirmed, **callbacks))


class ReadOnlyProvider(backups.BackupsProvider):
    """쓰는 메서드가 없는 공급자 — 카드의 단추는 모두 꺼진다."""

    def load_backups(self, progress, cancelled):
        return backups.BackupsData(backups.sample_rows(), "예시", 10, True)


class ProviderShapeTest(unittest.TestCase):
    def test_the_fake_provider_is_a_writer_and_a_reader_and_marked_as_a_sample(self):
        provider = backups.FakeBackupsProvider()
        self.assertTrue(isinstance(provider, backups.BackupsWriter) and isinstance(provider, backups.BackupsProvider))
        self.assertTrue(provider.can_write and provider.sample)
        self.assertFalse(getattr(backups.BackupsProvider(), "can_write", False))

    def test_the_sample_list_per_scenario(self):
        for scenario, count in (("normal", 3), ("empty", 0), ("broken", 4)):
            with self.subTest(scenario=scenario):
                data = backups.FakeBackupsProvider(scenario).load_backups(lambda *_: None, lambda: False)
                self.assertEqual((len(data.rows), data.sample, data.keep), (count, True, 10))
        with self.assertRaises(jobs.JobFailure) as caught:
            backups.FakeBackupsProvider("error").load_backups(lambda *_: None, lambda: False)
        self.assertEqual(caught.exception.user_message, T["backup_load_failed"])

    def test_creating_adds_a_row_at_the_top_and_reports_forward_progress(self):
        provider, seen = backups.FakeBackupsProvider(), []
        result = provider.create_backup(lambda fraction, text="": seen.append(fraction), lambda: False)
        self.assertEqual((result.action, result.status, result.safety), ("created", "complete", ""))
        self.assertTrue(result.name.startswith("full-") and result.created_at.endswith("Z"))
        self.assertEqual(seen, sorted(seen))
        data = provider.load_backups(lambda *_: None, lambda: False)
        self.assertEqual((data.rows[0].name, data.rows[0].kind, len(data.rows)), (result.name, "backup", 4))

    def test_restoring_adds_a_safety_row_and_a_broken_or_unknown_row_is_refused(self):
        provider = backups.FakeBackupsProvider("broken")
        result = provider.restore_backup(FIRST, lambda *_: None, lambda: False)
        self.assertEqual((result.action, result.status), ("restored", "complete"))
        self.assertTrue(result.safety.startswith("before-"))
        self.assertEqual([item.state for item in result.files], ["restored"] * 6)
        self.assertEqual(provider.restore_backup(PARTIAL, lambda *_: None, lambda: False).status, "partial")
        for name in ("full-20261101-120000", "full-19990101-000000"):
            with self.assertRaises(backups.BackupFailure) as caught:
                provider.restore_backup(name, lambda *_: None, lambda: False)
            self.assertEqual(caught.exception.kind, "invalid")
        kinds = [row.kind for row in provider.load_backups(lambda *_: None, lambda: False).rows]
        self.assertEqual(kinds.count("safety"), 3)

    def test_injected_failures_and_cancel(self):
        for kind in backups.KINDS_OF_FAILURE:
            with self.subTest(kind=kind):
                with self.assertRaises(backups.BackupFailure) as caught:
                    backups.FakeBackupsProvider(create_failure=kind).create_backup(lambda *_: None, lambda: False)
                self.assertEqual((caught.exception.kind, caught.exception.user_message), (kind, backups.failure_text(kind)))
        with self.assertRaises(jobs.JobCancelled):
            backups.FakeBackupsProvider().create_backup(lambda *_: None, lambda: True)
        with self.assertRaises(jobs.JobCancelled):
            backups.FakeBackupsProvider().restore_backup(FIRST, lambda *_: None, lambda: True)

    def test_the_values_hold_no_key_or_text_field_and_are_frozen(self):
        banned = re.compile(r"(?i)secret|token|passw|cookie|credential|(^|_)key($|_)|content|body|text")
        samples = {backups.FileInfo: backups.FileInfo("a", "b", "saved"), backups.BackupRowData: backups.BackupRowData("n", "backup", "", "complete"), backups.BackupsData: backups.BackupsData(),
                   backups.BackupResult: backups.BackupResult("created", "complete")}
        for cls, instance in samples.items():
            self.assertTrue(dataclasses.is_dataclass(cls))
            self.assertEqual([field.name for field in dataclasses.fields(cls) if banned.search(field.name)], [], cls.__name__)
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(instance, "anything", "x")
        failure = backups.make_failure("blocked", "X", summary=("줄",), notes=("이름",), reason="io")
        self.assertEqual((failure.kind, failure.summary, failure.notes, failure.reason), ("blocked", ("줄",), ("이름",), "io"))
        self.assertEqual(backups.make_failure("엉뚱한 종류").kind, "other")
        self.assertEqual(backups.failure_text("엉뚱한 종류"), T["backup_fail_other"])


class TextTest(unittest.TestCase):
    def test_every_backup_text_key_is_in_the_table_and_obeys_the_text_rules(self):
        from chanceblog_desktop.ui.core.backup_text import BACKUP_T
        self.assertGreater(len(BACKUP_T), 100)
        for key, value in BACKUP_T.items():
            with self.subTest(key=key):
                self.assertIs(T[key], value)
                for word in FORBIDDEN:
                    self.assertNotIn(word, value)
                self.assertNotRegex(value, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
                self.assertNotRegex(value, r"Traceback|Exception|Error\b|https?:|" + chr(126))

    def test_the_credential_sentences_are_the_same_words_the_manifest_carries(self):
        self.assertEqual(T["backup_credential_line"], CREDENTIAL_NOTE)
        self.assertEqual(T["backup_credential_badge"], SHORT_NOTE)
        self.assertEqual(T["backup_note_keys"], RESTORE_NOTE)
        self.assertIn("키·토큰·쿠키·세션은 이 백업에 들어 있지 않아요", T["backup_credential_a11y"])

    def test_every_failure_kind_has_a_fixed_sentence_that_says_what_changed(self):
        for kind in backups.KINDS_OF_FAILURE:
            self.assertIn("backup_fail_" + kind, T)
        for kind in ("blocked", "nothing", "busy", "invalid", "newer", "disk", "io"):
            self.assertRegex(T["backup_fail_" + kind], "바뀌지 않았어요|그대로예요|남기지 않았고|만들지 않았어요", kind)
        self.assertIn("복원 직전 사본", T["backup_fail_restore_left"])
        self.assertIn("그냥 진행하는 선택지도 없어요", T["backup_fail_blocked"])
        self.assertIn("자동으로 지우거나 바꾸지 않고", T["backup_fail_blocked"])


class HelperTest(unittest.TestCase):
    def test_times_are_shown_in_korean_time_and_unknown_ones_are_empty(self):
        self.assertEqual(backup_view.when_text("2026-11-10T12:05:00Z"), "2026-11-10 21:05")
        self.assertEqual(backup_view.when_text("2026-11-10T15:30:00Z"), "2026-11-11 00:30")
        for bad in ("", None, "어제", "2026-11-10 12:05", 5, "2026-13-01T00:00:00Z"):
            self.assertEqual(backup_view.when_text(bad), "", repr(bad))

    def test_sizes(self):
        cases = {0: "0 B", 1023: "1023 B", 1024: "1.0 KB", 1536: "1.5 KB", 10 * 1024: "10.0 KB", 204800: "200 KB", 1048576: "1.0 MB", 4_670_000: "4.5 MB", 1024 ** 3: "1.0 GB"}
        for number, shown in cases.items():
            self.assertEqual(backup_view.size_text(number), shown, number)
        for bad in (-1, None, "3", 1.5, True):
            self.assertEqual(backup_view.size_text(bad), "", repr(bad))

    def test_reasons_become_plain_words_and_unknown_codes_never_show(self):
        for code, key in (("STORE_CORRUPT", "backup_why_unreadable"), ("TOPIC_FILE_INVALID", "backup_why_unreadable"), ("SETTINGS_INVALID", "backup_why_unreadable"), ("STORE_VERSION_UNSUPPORTED", "backup_why_newer"),
                          ("TOPIC_STORE_LOCKED", "backup_why_busy"), ("STORE_RECOVERY_PENDING", "backup_why_pending"), ("무슨코드", "backup_why_other"), ("", "backup_why_other")):
            self.assertEqual(backup_view.reason_text(code), T[key], code)

    def test_contents_lines_count_only_the_saved_files_and_use_plain_labels(self):
        text = backup_view.contents_text(backups.sample_files())
        self.assertEqual(text, "글 12개 · 저장한 초안 3개 · 주제 후보 5개 · 추천 후보 40개 · 채널 프로필 5개 · Seed 130개 · 캘린더 항목 6개 · 설정 · 옛 네이버 프로필 2개")
        partial = backup_view.contents_text(backups.sample_files(partial=True))
        self.assertNotIn("Seed", partial)
        self.assertEqual(backup_view.skipped_text(backups.sample_files(partial=True)), f"Seed({T['backup_why_unreadable']})")
        self.assertEqual(backup_view.contents_text(()), "")

    def test_a_row_with_an_unknown_kind_or_status_is_treated_safely(self):
        row = backups.BackupRowData("full-20261110-210500", "이상한 종류", "엉뚱한 시각", "이상한 상태", 5)
        self.assertEqual(backup_view.kind_of(row), "backup")
        self.assertEqual(backup_view.status_of(row), "broken", "모르는 상태는 복원하지 않는다")
        self.assertEqual(backup_view.row_title(row), T["backup_row_unknown"].format(kind=T["backup_kind_backup"]))


class ControllerTest(unittest.TestCase):
    def test_the_initial_state_is_loading_and_a_read_only_provider_has_no_writer(self):
        controller = backup_view.BackupController(ReadOnlyProvider(), jobs.JobRunner())
        self.assertEqual((controller.state, controller.writable, controller.busy), ("loading", False, False))
        view = controller.view()
        self.assertFalse(view["create"]["enabled"])
        self.assertEqual(view["create"]["reason"], T["backup_no_write"])

    def test_loading_a_list_changes_the_state_and_never_writes(self):
        env = Env()
        self.assertEqual(env.controller.state, "normal")
        self.assertEqual(env.provider.writes, [])
        empty = Env(scenario="empty")
        self.assertEqual(empty.controller.state, "empty")
        env.controller.apply_load_failed(jobs.JobFailure("읽지 못했어요 " + S.google(), "STORE_CORRUPT"), when=None)
        self.assertEqual(env.controller.state, "error")
        self.assertFalse(S.leaked(env.controller.failure.user_message, S.google()), "키 모양은 가린다")
        self.assertIsNotNone(env.controller.data, "이전에 읽은 목록은 지우지 않는다")
        env.controller.apply_loaded(env.provider.load_backups(lambda *_: None, lambda: False))
        env.controller.apply_load_cancelled()
        self.assertEqual(env.controller.state, "normal")

    def test_start_load_does_nothing_while_writing_or_already_loading(self):
        env = Env(delay=0.4)
        results = []
        status, job = env.controller.start_create(on_done=lambda result, _payload: results.append(result))
        self.assertEqual(status, "started")
        self.assertIsNone(env.controller.start_load(), "쓰는 도중의 폴더를 읽지 않는다")
        job.join(10)
        env.controller.apply_write_ok(results[0])
        self.assertIsNotNone(env.controller.start_load(), "끝나면 읽는다")
        env.runner.join_all(10)

    def test_creating_runs_once_at_a_time_and_reports_the_result(self):
        env = Env(delay=0.15)
        results = []
        first, job = env.controller.start_create(on_done=lambda result, _payload: results.append(result), on_progress=lambda fraction, text: env.progress.append(fraction))
        second = env.controller.start_create()
        self.assertEqual((first, second), ("started", ("busy", None)))
        self.assertTrue(env.controller.busy)
        self.assertEqual(env.controller.pending, {"kind": "create", "name": ""})
        job.join(10)
        self.assertFalse(env.controller.busy)
        env.controller.apply_write_ok(results[0])
        self.assertEqual(env.controller.notice[0], "ok")
        self.assertIn("2026-11-11 12:00", env.controller.notice[1])
        self.assertTrue(env.controller.reload_wanted and env.controller.focus_after)
        self.assertEqual(env.progress, sorted(env.progress))
        self.assertEqual(env.provider.writes, ["create"], "두 번째 클릭은 아무 일도 하지 않았다")

    def test_a_partial_backup_is_announced_as_partial_with_what_was_left_out(self):
        env = Env(create_status="partial")
        env.create()
        level, text, lines = env.controller.notice
        self.assertEqual(level, "warning")
        self.assertIn(T["backup_why_unreadable"], text)
        self.assertIn("Seed", text)
        self.assertEqual(lines, ())

    def test_a_read_only_provider_never_starts_anything(self):
        controller = backup_view.BackupController(ReadOnlyProvider(), jobs.JobRunner())
        controller.apply_loaded(ReadOnlyProvider().load_backups(lambda *_: None, lambda: False))
        self.assertEqual(controller.start_create(), ("unavailable", None))
        self.assertEqual(controller.start_restore(FIRST, confirmed=True), ("unavailable", None))
        self.assertIsNone(controller.restore_dialog(FIRST))

    def test_restore_needs_the_confirmation_and_refuses_broken_unknown_and_busy(self):
        env = Env(scenario="broken", delay=0.1)
        for value in (False, None, 1, "yes", 0):
            self.assertEqual(env.controller.start_restore(FIRST, confirmed=value), ("unconfirmed", None), repr(value))
        self.assertEqual(env.controller.start_restore("full-20261101-120000", confirmed=True), ("unavailable", None), "깨진 백업")
        self.assertEqual(env.controller.start_restore("full-19990101-000000", confirmed=True), ("unavailable", None), "없는 줄")
        self.assertEqual(env.provider.writes, [])
        status, job = env.controller.start_restore(FIRST, confirmed=True)
        self.assertEqual(status, "started")
        self.assertEqual(env.controller.start_restore(PARTIAL, confirmed=True), ("busy", None))
        self.assertEqual(env.controller.start_create(), ("busy", None))
        job.join(10)
        self.assertEqual(env.provider.writes, ["restore:" + FIRST])

    def test_restore_result_texts_for_complete_partial_and_no_safety_copy(self):
        env = Env()
        env.restore(FIRST)
        level, text, lines = env.controller.notice
        self.assertEqual((level, text, lines), ("ok", T["backup_ok_restored"], (RESTORE_NOTE,)))
        env2 = Env()
        env2.restore(PARTIAL)
        self.assertEqual((env2.controller.notice[0], env2.controller.notice[1]), ("warning", T["backup_ok_restored_partial"]))
        controller = env.controller
        controller.pending = {"kind": "restore", "name": FIRST}
        controller.apply_write_ok(backups.BackupResult("restored", "complete", FIRST, "", "", (), ()))
        self.assertEqual(controller.notice[1], T["backup_ok_restored_nosafety"])

    def test_the_restore_dialog_says_what_changes_where_the_safety_copy_goes_and_how_to_undo(self):
        env = Env()
        dialog = env.controller.restore_dialog(FIRST)
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), (T["backup_restore_title"], T["backup_restore_ok"], T["backup_restore_cancel"]))
        body = dialog["body"]
        for needle in ("2026-11-10 21:05", "글 보관함", "주제 보관함", "채널 프로필", "Seed", "캘린더", "설정", "복원 직전 사본", "다시 복원하면 돼요", "키는 백업에 없어서 그대로예요", "다른 화면에서 저장하지 마세요",
                       backups.SAMPLE_LOCATION):
            self.assertIn(needle, body)
        self.assertNotIn(T["backup_restore_partial"], body)
        self.assertIn(T["backup_restore_partial"], env.controller.restore_dialog(PARTIAL)["body"])
        self.assertNotIn("Seed", env.controller.restore_dialog(PARTIAL)["body"].split("바뀌어요")[0], "담기지 않은 파일은 '바뀌는 것' 에 없다")
        self.assertIsNotNone(env.controller.restore_dialog(SAFETY), "안전 사본도 같은 방법으로 복원한다")
        self.assertIsNone(env.controller.restore_dialog("full-19990101-000000"))

    def test_every_failure_kind_gets_its_fixed_sentence_and_only_the_right_lines(self):
        for kind in backups.KINDS_OF_FAILURE:
            with self.subTest(kind=kind):
                env = Env()
                env.controller.pending = {"kind": "create", "name": ""}
                failure = backups.make_failure(kind, "X", summary=("글 보관함 · 원고 · 본문 · 글 3f2a91bc에서 1건(GitHub 토큰 1) — 3번째 줄",), notes=("글 보관함은(는) 원래대로 돌리지 못했어요",), reason="io")
                self.assertEqual(env.controller.apply_write_failed(failure), kind)
                level, text, lines = env.controller.notice
                self.assertEqual(level, "error")
                self.assertEqual(text, T["backup_fail_restore_left"] if kind == "restore" else T["backup_fail_" + kind])
                if kind == "blocked":
                    self.assertEqual(lines, failure.summary)
                elif kind == "restore":
                    self.assertEqual(lines, (T["backup_restore_reason_io"],) + failure.notes)
                else:
                    self.assertEqual(lines, ())
                self.assertFalse(env.controller.busy)

    def test_a_restore_failure_without_anything_left_undone_says_everything_was_put_back(self):
        env = Env()
        env.controller.pending = {"kind": "restore", "name": FIRST}
        env.controller.apply_write_failed(backups.make_failure("restore", "RESTORE_FAILED", reason="disk"))
        self.assertEqual(env.controller.notice, ("error", T["backup_fail_restore"], (T["backup_restore_reason_disk"],)))
        self.assertTrue(env.controller.reload_wanted)

    def test_the_sentence_never_repeats_the_error_text_or_a_path_or_a_key_piece(self):
        env = Env()
        key = S.google()
        failure = backups.BackupFailure("C:\\Users\\누군가\\data " + key + " Traceback", "STORE_CORRUPT", kind="io")
        env.controller.pending = {"kind": "create", "name": ""}
        env.controller.apply_write_failed(failure)
        shown = " ".join(visible_strings({"n": env.controller.notice}))
        self.assertNotIn("Users", shown)
        self.assertNotIn("Traceback", shown)
        self.assertFalse(S.leaked(shown, key))
        self.assertEqual(env.controller.notice[1], T["backup_fail_io"])
        env.controller.pending = {"kind": "create", "name": ""}
        env.controller.apply_write_failed(jobs.JobFailure("키 " + key))                            # 우리 종류가 아닌 실패도
        self.assertEqual(env.controller.notice[1], T["backup_fail_other"])
        self.assertEqual(env.controller.apply_unexpected(ValueError(key)), "ValueError")
        self.assertEqual(env.controller.notice, ("error", T["backup_fail_other"], ()))

    def test_a_summary_line_that_somehow_holds_a_key_shape_is_masked(self):
        env = Env()
        env.controller.pending = {"kind": "create", "name": ""}
        key = S.google()
        env.controller.apply_write_failed(backups.make_failure("blocked", "X", summary=("위치 " + key,)))
        self.assertFalse(S.leaked(" ".join(env.controller.notice[2]), key))

    def test_progress_is_clamped_and_masked(self):
        env = Env()
        for given, expected in ((0.5, 0.5), (-3, 0.0), (7, 1.0), ("0.25", 0.25), ("abc", 0.0), (None, 0.0), (float("nan"), 0.0), (float("inf"), 0.0)):
            env.controller.apply_progress(given, "일하는 중")
            self.assertEqual(env.controller.progress[0], expected, repr(given))
        env.controller.apply_progress(0.3, "키 " + S.google())
        self.assertFalse(S.leaked(env.controller.progress[1], S.google()))
        env.controller.apply_progress(0.3, 5)
        self.assertEqual(env.controller.progress, (0.3, ""))


class InterruptedTest(unittest.TestCase):
    """복원이 중간에 멈춘 흔적(D-463) — 쉬운 안내·`안전 사본으로 되돌리기`(확인이 먼저)·다른 일이 도는 동안은 꺼짐·되돌린 뒤에는 사라짐."""

    def revert(self, env, confirmed=True):
        return env.run(lambda **callbacks: env.controller.start_revert(confirmed=confirmed, **callbacks))

    def test_only_the_interrupted_scenario_shows_the_notice_and_it_says_what_to_do_in_plain_words(self):
        for scenario in ("normal", "empty", "broken"):
            self.assertIsNone(Env(scenario=scenario).controller.view()["interrupted"], scenario)
        env = Env(scenario="interrupted")
        box = env.controller.view()["interrupted"]
        self.assertEqual((box["level"], box["text"]), ("warning", T["backup_interrupted_can"]))
        self.assertEqual(box["lines"], [T["backup_interrupted_when"].format(when="2026-11-10 21:20")])
        self.assertEqual((box["revert"]["text"], box["revert"]["enabled"], box["revert"]["reason"]), (T["backup_revert"], True, ""))
        self.assertIn("안전 사본으로 되돌릴 수 있어요", box["text"])
        for text in visible_strings(box):
            self.assertIsNone(INTERNAL.search(text), text)
            for word in FORBIDDEN:
                self.assertNotIn(word, text)

    def test_without_a_safety_copy_the_notice_says_so_and_has_no_revert_button(self):
        data = backups.BackupsData(backups.sample_rows(), "예시", 10, True, backups.InterruptedData("", "", "", False))
        controller = backup_view.BackupController(backups.FakeBackupsProvider(), jobs.JobRunner())
        controller.apply_loaded(data)
        box = controller.view()["interrupted"]
        self.assertEqual((box["text"], box["lines"], box["revert"]), (T["backup_interrupted_cannot"], [], None))
        self.assertIsNone(controller.revert_dialog())
        self.assertEqual(controller.start_revert(confirmed=True), ("unavailable", None))

    def test_the_revert_asks_first_and_only_a_confirmed_one_writes(self):
        env = Env(scenario="interrupted")
        dialog = env.controller.revert_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), (T["backup_revert_title"], T["backup_revert_ok"], T["backup_restore_cancel"]))
        self.assertIn("2026-11-10 10:03", dialog["body"], "되돌릴 안전 사본의 시각")
        self.assertIn(backups.SAMPLE_LOCATION, dialog["body"])
        self.assertIn("복원 직전 사본", dialog["body"])
        for confirmed in (False, None, 1, "yes"):
            self.assertEqual(env.controller.start_revert(confirmed=confirmed), ("unconfirmed", None), confirmed)
        self.assertEqual(env.provider.writes, [], "확인 없이는 아무것도 쓰지 않는다")

    def test_a_confirmed_revert_restores_the_safety_copy_and_the_notice_goes_away(self):
        env = Env(scenario="interrupted")
        status, (kind, result) = self.revert(env)
        self.assertEqual((status, kind), ("started", "ok"))
        self.assertEqual((result.action, result.status, result.name), ("restored", "complete", "before-20261110-100300"))
        self.assertEqual(env.provider.writes, ["revert"])
        self.assertEqual(env.controller.notice[:2], ("ok", T["backup_ok_restored"]))
        self.assertIsNone(env.controller.view()["interrupted"], "되돌린 뒤에는 안내가 사라진다")
        self.assertEqual(env.controller.start_revert(confirmed=True), ("unavailable", None), "흔적이 없으면 되돌릴 것도 없다")

    def test_any_restore_ends_the_interrupted_state_like_the_service_clears_its_marker(self):
        env = Env(scenario="interrupted")
        env.restore(FIRST)
        self.assertIsNone(env.controller.view()["interrupted"])

    def test_the_button_is_off_while_something_else_runs_and_for_a_read_only_provider(self):
        env = Env(scenario="interrupted", delay=0.3)
        results = []
        status, job = env.controller.start_create(on_done=lambda result, _payload: results.append(result))
        self.assertEqual(status, "started")
        box = env.controller.view()["interrupted"]
        self.assertEqual((box["revert"]["enabled"], box["revert"]["reason"]), (False, T["backup_busy"]))
        self.assertEqual(env.controller.start_revert(confirmed=True), ("busy", None))
        self.assertIsNone(env.controller.revert_dialog())
        job.join(10)
        env.controller.apply_write_ok(results[0])
        readonly = backup_view.BackupController(ReadOnlyProvider(), jobs.JobRunner())
        readonly.apply_loaded(backups.BackupsData(backups.sample_rows(), "예시", 10, True, backups.InterruptedData("2026-11-10T12:20:00Z", FIRST, SAFETY, True)))
        box = readonly.view()["interrupted"]
        self.assertEqual((box["revert"]["enabled"], box["revert"]["reason"]), (False, T["backup_no_write"]))
        self.assertEqual(readonly.start_revert(confirmed=True), ("unavailable", None))

    def test_a_failed_revert_uses_the_same_fixed_sentences_as_a_failed_restore(self):
        env = Env(scenario="interrupted", restore_failure="restore")
        status, (kind, failure) = self.revert(env)
        self.assertEqual((status, kind), ("started", "err"))
        self.assertEqual(env.controller.notice[0], "error")
        self.assertIn(env.controller.notice[1], (T["backup_fail_restore"], T["backup_fail_restore_left"]))
        self.assertIsNotNone(env.controller.view()["interrupted"], "되돌리지 못했으면 안내가 남는다")

    def test_the_values_of_the_trace_hold_only_names_and_times(self):
        fields = [field.name for field in dataclasses.fields(backups.InterruptedData)]
        self.assertEqual(fields, ["started_at", "backup", "safety", "can_revert"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(backups.InterruptedData(), "safety", "x")
        self.assertIn("revert_interrupted", dir(backups.BackupsWriter))


class ViewTest(unittest.TestCase):
    def test_the_view_has_the_pieces_the_card_draws(self):
        env = Env()
        view = env.controller.view()
        for key in ("title", "desc", "sample", "sample_tag", "sample_note", "state", "writable", "busy", "create", "progress", "notice", "location", "copy_tip", "keep", "credential_line", "excluded",
                    "list_title", "list_note", "rows", "loading", "empty", "error", "a11y"):
            self.assertIn(key, view)
        self.assertEqual((view["state"], len(view["rows"]), view["progress"], view["notice"]), ("normal", 3, None, None))
        self.assertEqual(view["location"], T["backup_location"].format(path=backups.SAMPLE_LOCATION))
        self.assertEqual(view["keep"], T["backup_keep"].format(n=10))
        self.assertEqual(view["excluded"]["lines"], [f"{name} — {reason}" for name, reason in EXCLUDED])
        self.assertEqual(view["a11y"], T["backup_a11y"].format(n=3))

    def test_every_row_has_a_credential_excluded_badge_a_text_status_and_a_restore_button(self):
        view = Env(scenario="broken").controller.view()
        by_name = {row["name"]: row for row in view["rows"]}
        for name, row in by_name.items():
            if name == "full-20261101-120000":
                self.assertIsNone(row["credential"])
                self.assertFalse(row["restore"]["enabled"])
                self.assertEqual(row["restore"]["reason"], T["backup_restore_broken"])
                self.assertEqual(row["status"], {"text": T["backup_status_broken"], "tone": "danger"})
                self.assertIn(T["backup_broken_manifest"], row["lines"][0])
                self.assertEqual(row["meta"], "")
                continue
            self.assertEqual(row["credential"]["text"], SHORT_NOTE)
            self.assertIn("키·토큰·쿠키·세션", row["credential"]["a11y"])
            self.assertTrue(row["restore"]["enabled"], name)
            self.assertIn(row["status"]["text"], (T["backup_status_complete"], T["backup_status_partial"]))
            self.assertIn(row["status"]["text"], row["a11y"])
            self.assertIn(row["title"], row["restore"]["a11y"])
        self.assertEqual(by_name[PARTIAL]["status"], {"text": T["backup_status_partial"], "tone": "warning"})
        self.assertEqual(by_name[SAFETY]["kind"], {"text": T["backup_kind_safety"], "tone": "muted"})
        self.assertEqual(by_name[FIRST]["kind"], {"text": T["backup_kind_backup"], "tone": "info"})
        self.assertTrue(by_name[SAFETY]["title"].endswith(T["backup_kind_safety"]))
        self.assertTrue(any(line.startswith(T["backup_skipped"].split("{")[0]) for line in by_name[PARTIAL]["lines"]))

    def test_the_buttons_turn_off_with_a_reason_while_something_is_running(self):
        env = Env(delay=0.3)
        status, job = env.controller.start_create()
        view = env.controller.view()
        self.assertFalse(view["create"]["enabled"])
        self.assertEqual(view["create"]["reason"], T["backup_busy_create"])
        self.assertTrue(all(not row["restore"]["enabled"] and row["restore"]["reason"] == T["backup_busy"] for row in view["rows"]))
        self.assertTrue(view["busy"])
        self.assertEqual(view["progress"]["percent"], 0)
        job.join(10)
        env2 = Env(delay=0.3)
        _status, job2 = env2.controller.start_restore(FIRST, confirmed=True)
        self.assertEqual(env2.controller.view()["create"]["reason"], T["backup_busy_restore"])
        self.assertIn("복원하는 중이에요", env2.controller.view()["progress"]["text"])
        job2.join(10)

    def test_the_progress_line_has_a_percent_and_the_step_text_and_an_accessible_name(self):
        env = Env(delay=0.3)
        _status, job = env.controller.start_create()
        env.controller.apply_progress(0.4, "파일을 담아요")
        progress = env.controller.view()["progress"]
        self.assertEqual((progress["fraction"], progress["percent"]), (0.4, 40))
        self.assertEqual(progress["text"], T["backup_progress_create"].format(percent=40) + " — 파일을 담아요")
        self.assertEqual(progress["a11y"], progress["text"])
        job.join(10)

    def test_the_state_screens_have_their_own_texts(self):
        loading = backup_view.BackupController(backups.FakeBackupsProvider(), jobs.JobRunner()).view()
        self.assertEqual((loading["state"], loading["rows"]), ("loading", []))
        self.assertEqual(loading["loading"], {"text": T["backup_loading"], "a11y": T["backup_loading_a11y"]})
        self.assertEqual(Env(scenario="empty").controller.view()["empty"], {"title": T["backup_empty_title"], "desc": T["backup_empty_desc"]})
        env = Env()
        env.controller.apply_load_failed(jobs.JobFailure("읽지 못했어요", "STORE_CORRUPT"))
        view = env.controller.view("코드: STORE_CORRUPT")
        self.assertEqual(view["state"], "error")
        self.assertEqual((view["error"]["title"], view["error"]["button"], view["error"]["diag"], view["error"]["user"]), (T["backup_error_title"], T["backup_reload"], "코드: STORE_CORRUPT", "읽지 못했어요"))
        self.assertTrue(view["create"]["enabled"], "목록을 못 읽어도 백업은 만들 수 있다")

    def test_no_visible_text_holds_an_english_state_name_an_internal_key_or_an_error_code(self):
        scenes = []
        for scenario in ("normal", "empty", "broken"):
            scenes.append((scenario, Env(scenario=scenario).controller.view()))
        env = Env()
        env.create()
        scenes.append(("created", env.controller.view()))
        env.restore(FIRST)
        scenes.append(("restored", env.controller.view()))
        for kind in backups.KINDS_OF_FAILURE:
            failing = Env()
            failing.controller.pending = {"kind": "restore", "name": FIRST}
            failing.controller.apply_write_failed(backups.make_failure(kind, "FULL_BACKUP_BLOCKED", summary=("글 보관함 · 원고 · 본문 · 글 3f2a91bc에서 1건(GitHub 토큰 1) — 3번째 줄",), notes=("글 보관함은(는) 원래대로 돌리지 못했어요",), reason="other"))
            scenes.append((kind, failing.controller.view()))
        for name, view in scenes:
            for shown in visible_strings(view):
                self.assertIsNone(INTERNAL.search(shown), f"{name}: {shown!r}")

    def test_a_key_shaped_text_in_the_location_the_labels_or_a_row_is_masked_everywhere(self):
        key = S.google()
        data = backups.BackupsData((backups.BackupRowData("full-20261110-210500", "backup", "2026-11-10T12:05:00Z", "partial", 10,
                                                          (backups.FileInfo("chanceblog.db", "글 보관함 " + key, "skipped", 0, (), "STORE_CORRUPT"),)),), "C:\\데이터\\" + key, 10, False)
        env = Env(provider=backups.FakeBackupsProvider())
        env.controller.apply_loaded(data)
        blob = json.dumps(env.controller.view(), ensure_ascii=False)
        self.assertFalse(S.leaked(blob, key))

    def test_the_view_never_holds_anything_but_text_and_plain_values(self):
        view = Env().controller.view()
        json.dumps(view, ensure_ascii=False)                                              # 직렬화가 되는 값뿐이다(위젯·함수 없음)
        self.assertEqual(sorted(view["create"]), ["a11y", "enabled", "reason", "text"])
        self.assertEqual(sorted(view["rows"][0]), ["a11y", "credential", "key", "kind", "lines", "meta", "name", "restore", "status", "title"])


class AppStateTest(unittest.TestCase):
    def test_the_card_exists_only_when_a_provider_is_paired_so_old_screens_stay_as_they_were(self):
        """D-391 — 짝 공급자를 정하지 않은 홈 공급자(`FakeHomeProvider()` 기본값)는 카드가 없다: 설정 화면을 세는 기존 시험도, 단추가 필요 없는 화면도 그대로다."""
        for provider in (services.FakeHomeProvider(), services.HomeProvider()):
            state = app_state.AppState(provider)
            self.assertIsNone(state.backups)
            self.assertIsNone(state.backups_provider)
            self.assertIsNone(state.backups_view())
            self.assertIsNone(state.settings_view()["backup"], "카드 뷰모델이 없으면 화면이 카드를 그리지 않는다")
            self.assertIsNone(provider.backups_provider())

    def test_the_state_owns_a_backup_controller_when_the_home_provider_or_the_caller_pairs_one(self):
        own = backups.FakeBackupsProvider("empty")
        state = app_state.AppState(services.FakeHomeProvider(), backups=own)
        self.assertIsInstance(state.backups, backup_view.BackupController)
        self.assertIs(state.backups_provider, own)
        for value in (True, own):
            paired = app_state.AppState(services.FakeHomeProvider(backups=value))
            self.assertIsInstance(paired.backups, backup_view.BackupController)
            self.assertIsInstance(paired.backups_provider, backups.FakeBackupsProvider)
        for value in (None, False):
            self.assertIsNone(services.FakeHomeProvider(backups=value).backups_provider())
        self.assertIs(services.FakeHomeProvider(backups=own).backups_provider(), own)

    def test_the_settings_view_carries_the_backup_card_and_survives_a_connection_error(self):
        state = app_state.AppState(services.FakeHomeProvider(), backups=backups.FakeBackupsProvider())
        view = state.settings_view()
        self.assertEqual(view["backup"]["state"], "loading")
        self.assertEqual(view["state"], "loading")
        state.apply_conn_failure(jobs.JobFailure("읽지 못했어요", "CONNECTIONS_FILE_INVALID"))
        self.assertEqual(state.settings_view()["backup"]["title"], T["backup_title"])
        state.backups.apply_load_failed(jobs.JobFailure("읽지 못했어요", "STORE_CORRUPT"), None)
        self.assertEqual(state.settings_view()["backup"]["error"]["diag"].splitlines()[0].split(": ")[1], "STORE_CORRUPT")

    def test_the_launcher_pairs_the_sample_screen_with_example_backups_and_the_real_screen_with_the_real_adapter(self):
        """`gui --sample` 은 메모리 예시 백업 카드를, 기본 `gui` 는 실제 어댑터 카드를 연다(D-391) — 짝이 없으면 두 길 모두 카드가 사라지므로 연결 한 줄을 못박는다."""
        from chanceblog_desktop.ui import backups_adapter, launcher
        seen = []
        module = types.ModuleType("chanceblog_desktop.ui.qt.app")
        module.run = lambda provider, argv=None: seen.append(provider) or 0
        with mock.patch.object(launcher, "has_pyside6", return_value=True), mock.patch.dict(sys.modules, {"chanceblog_desktop.ui.qt.app": module}):
            launcher.main(["--sample"])
            launcher.main([])
        sample, real = seen
        self.assertIsInstance(sample.backups_provider(), backups.FakeBackupsProvider)
        self.assertIsInstance(real.backups_provider(), backups_adapter.ServiceBackupsProvider)
        for provider in (sample, real):
            state = app_state.AppState(provider)
            self.assertIsNotNone(state.backups, "두 길 모두 카드가 있다")
            self.assertIsInstance(state.settings_view()["backup"], dict)

    def test_the_service_home_provider_pairs_the_real_adapter_without_touching_disk(self):
        import tempfile
        from chanceblog_desktop.ui import adapters, backups_adapter
        with tempfile.TemporaryDirectory() as tmp:
            provider = adapters.ServiceHomeProvider(tmp).backups_provider()
            self.assertIsInstance(provider, backups_adapter.ServiceBackupsProvider)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class SourceRulesTest(unittest.TestCase):
    BANNED_IMPORTS = {"subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "shutil", "requests", "tempfile", "sqlite3", "pickle", "json5", "os", "pathlib", "io", "glob"}
    BANNED_NAMES = {"open", "write_text", "write_bytes", "unlink", "rmtree", "mkdir", "startfile", "QDesktopServices", "QFileDialog", "QProcess", "QUrl", "openUrl", "system", "Popen", "print"}

    def parse(self, path):
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def names(self, tree):
        found = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        return found | {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}

    def test_the_card_files_import_no_file_process_network_or_dialog_module(self):
        for path in CORE_FILES + PART_FILES:
            tree = self.parse(path)
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [node.module or ""]
                for module in modules:
                    with self.subTest(file=path.name, module=module):
                        self.assertNotIn(module.split(".")[0], self.BANNED_IMPORTS)
            with self.subTest(file=path.name, rule="names"):
                self.assertEqual(sorted(self.names(tree) & self.BANNED_NAMES), [], f"{path.name}: 파일 쓰기·폴더 열기·파일 대화상자·하위 프로세스를 쓰지 않는다")

    def test_the_core_files_do_not_know_the_service_layer_or_qt(self):
        for path in CORE_FILES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotRegex(text, r"(?m)^\s*(?:from|import)\s+(?:\.\.\.service|chanceblog_desktop\.service|PySide6|\.\.qt)")
        self.assertNotRegex((UI / "qt" / "backup_parts.py").read_text(encoding="utf-8"), r"(?m)^\s*(?:from|import)\s+(?:\.\.\.service|\.\.service|chanceblog_desktop\.service)")

    def test_the_adapter_calls_exactly_the_four_service_functions_each_from_its_own_method(self):
        tree = self.parse(UI / "backups_adapter.py")
        callers = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "flow":
                    callers.setdefault(node.func.attr, set()).add(function.name)
        self.assertEqual(callers, {"list_full_backups": {"load_backups"}, "create_full_backup": {"create_backup"}, "restore_full_backup": {"restore_backup"}, "revert_interrupted_restore": {"revert_interrupted"}})
        confirmed = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.keyword) and node.arg == "confirmed":
                    confirmed.setdefault(function.name, []).append(ast.unparse(node.value))
        self.assertEqual({name: values for name, values in confirmed.items() if name in ("restore_backup", "revert_interrupted")}, {"restore_backup": ["True"], "revert_interrupted": ["True"]},
                         "서비스에 확인을 넘기는 곳은 복원과 멈춘 복원 되돌리기 둘뿐이다(둘 다 컨트롤러가 확인창 뒤에만 부른다)")
        self.assertEqual(sorted(name for name in confirmed if name not in ("restore_backup", "revert_interrupted")), [], "다른 메서드는 확인을 넘기지 않는다")

    def test_the_shell_asks_for_the_confirmation_before_a_restore_can_start(self):
        tree = self.parse(UI / "qt" / "shell.py")
        starters = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("start_restore", "start_create")
                        and ast.unparse(node.func.value) in ("backups", "self._backups()", "self.state.backups")):                 # 다른 화면(Seed 관리 등)의 `start_create` 와 구별한다
                    starters.setdefault(node.func.attr, set()).add(function.name)
        self.assertEqual(starters, {"start_create": {"backup_now"}, "start_restore": {"backup_restore_confirmed"}})
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "backup_restore")
        dialogs = [node for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "show_dialog"]
        self.assertEqual(len(dialogs), 1)
        self.assertTrue(any(keyword.arg == "on_ok" and "backup_restore_confirmed" in ast.unparse(keyword.value) for keyword in dialogs[0].keywords))
        self.assertTrue(any(keyword.arg == "safe_focus" and ast.unparse(keyword.value) == "True" for keyword in dialogs[0].keywords), "처음 포커스는 취소")
        self.assertNotIn("start_restore", ast.unparse(function), "복원은 확인창 안에서 시작하지 않는다")

    def test_the_controller_starts_a_write_only_from_two_methods_and_every_write_goes_through_one_start(self):
        tree = self.parse(UI / "core" / "backup_view.py")
        starts = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "start" and ast.unparse(node.func.value) == "self.runner"]
        self.assertEqual(len(starts), 2, "읽기 하나와 쓰기 하나")
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_restore")
        first = [node for node in function.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))][0]
        self.assertIn("confirmed is not True", ast.unparse(first), "확인 검사가 `start_restore` 의 첫 일이다")

    def test_python_3_10_grammar(self):
        for path in CORE_FILES + PART_FILES:
            ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))

    def test_the_card_text_module_has_no_logic(self):
        tree = self.parse(UI / "core" / "backup_text.py")
        kinds = {type(node).__name__ for node in tree.body}
        self.assertLessEqual(kinds, {"Expr", "ImportFrom", "Assign"})


class ConcurrencyTest(unittest.TestCase):
    def test_two_clicks_from_two_threads_start_one_write(self):
        env = Env(delay=0.3)
        results, barrier = [], threading.Barrier(2)

        def click():
            barrier.wait()
            results.append(env.controller.start_create()[0])
        threads = [threading.Thread(target=click) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(sorted(results), ["busy", "started"])
        env.runner.join_all(10)
        self.assertEqual(env.provider.writes, ["create"])


if __name__ == "__main__":
    unittest.main()
