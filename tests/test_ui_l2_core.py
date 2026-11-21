"""앱 묶음 L2(결정 D-534 에서 D-538)의 순수 시험 — PySide6 없이 돈다(CI 와 같은 조건). 두 가지를 지킨다.

지키는 것:
  1) (F025) Seed 관리에서 고치거나 새로 입력했는데 저장하지 않은 내용이 있으면 앱 닫기 앞에 확인창의 글이 있다 — 고친 씨앗이든 새 Seed 폼이든, 서랍을 닫았든 다른 화면에 있든 같다.
     입력이 없으면(서랍만 열었다·글 검색·고른 상자) 없다. 지금 저장하는 중인 것은 그 저장이 끝나기를 기다리므로 세지 않는다. 두 갈래(저장 안 하고 닫기·계속 고치기)이고 `close_guard` 는 초안 → 블로그 → Seed 순서다.
     화면 이동(`leave_guard`)은 Seed 입력이 컨트롤러에 남아 사라지지 않으므로 묻지 않는다(그 사실도 못박는다).
  2) (F030) 복원(또는 안전 사본으로 되돌리기)이 도는 동안 다른 화면의 저장 길을 시작하지 않고(`("restoring", None)`), 저장 길이 도는 동안 복원을 시작하지 않는다(`("writing", None)`).
     지금 백업(만들기)은 어느 쪽도 막지 않는다. 입력은 어느 경우에도 그대로이고 막은 일은 작업을 만들지 않는다.
"""
import ast
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chanceblog_desktop.ui.core import app_state, backup_view, backups, blogs, blogs_view, candidates, candidates_view, drafts, drafts_view, jobs, seeds, seeds_view, services, text  # noqa: E402

UI_CORE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core"
T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
FULL_BACKUP = "full-20261110-210500"
TILDE = chr(0x7E)                                   # 물결 글자는 시험 글에도 직접 쓰지 않는다(문서·주석에 물결표를 두지 않는 규칙)


def load_seeds(controller):
    controller.apply_loaded(controller.provider.load_seeds(SAFE, NEVER))


def load_blogs(controller):
    controller.apply_loaded(controller.provider.load_blogs(SAFE, NEVER))


def seed_state(**kwargs):
    """가짜 공급자들로 만든 화면 상태(Seed 를 읽어 둔)."""
    state = app_state.AppState(services.FakeHomeProvider(), **kwargs)
    load_seeds(state.seeds)
    return state


class GatedSeeds(seeds.FakeSeedsProvider):
    """쓰기가 시험이 문을 열어 줄 때까지 기다리는 가짜 공급자 — 시간에 기대지 않고 '쓰는 중' 을 확실히 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def _enter(self, name, version, cancelled):
        if not self.gate.wait(30):
            raise AssertionError("시험이 쓰기의 문을 열어 주지 않았다")
        super()._enter(name, version, cancelled)


class FailingSeeds(seeds.FakeSeedsProvider):
    def _enter(self, name, version, cancelled):
        super()._enter(name, version, cancelled)
        if name == "edit_seed":
            raise seeds.SeedFailure(T["seeds_fail_io"], code="FILE_WRITE_FAILED", kind="io")


class HeldBackups(backups.FakeBackupsProvider):
    """백업·복원이 시험이 문을 열어 줄 때까지 기다리는 가짜 공급자 — 시간에 기대지 않고 '도는 중' 을 확실히 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def _hold(self, cancelled):
        end = time.monotonic() + 30
        while not self.gate.wait(0.02):
            if cancelled():
                raise jobs.JobCancelled()
            if time.monotonic() > end:
                raise AssertionError("시험이 문을 열어 주지 않았다")

    def create_backup(self, progress, cancelled):
        self._hold(cancelled)
        return super().create_backup(progress, cancelled)

    def _restore(self, name, progress, cancelled):
        self._hold(cancelled)
        return super()._restore(name, progress, cancelled)


def finish(job, collected, controller, kind):
    """작업이 끝나기를 기다리고 화면 스레드가 하는 일(결과 받기)을 한다."""
    job.join(10)
    if "ok" in collected:
        controller.apply_write_ok(collected["ok"])
    else:
        controller.apply_write_failed(collected["failed"])
    return kind


def callbacks(collected):
    return {"on_done": lambda result, _payload: collected.setdefault("ok", result), "on_error": lambda failure, _payload: collected.setdefault("failed", failure)}


# ---- 1) Seed 를 고치다 앱을 닫을 때 먼저 묻기 -------------------------------------------------------------------------------------------------
class SeedCloseRuleTest(unittest.TestCase):
    def test_a_fresh_screen_and_a_drawer_opened_without_typing_ask_nothing(self):
        state = seed_state()
        self.assertEqual((state.seeds.unsaved_targets(), state.seeds.has_unsaved(), state.seeds.close_dialog(), state.close_guard()), ([], False, None, None))
        state.seeds.open_detail("EX001")
        self.assertIsNone(state.seeds.close_dialog(), "서랍을 열기만 했다")
        state.seeds.open_new()
        self.assertIsNone(state.seeds.close_dialog(), "새 Seed 서랍을 열기만 했다 — 폼의 처음 값은 사용자가 친 것이 아니다")
        self.assertIsNone(state.close_guard())

    def test_filters_a_search_text_and_checked_boxes_are_view_settings_not_input_to_lose(self):
        state = seed_state()
        state.seeds.set_query("검색어")
        state.seeds.set_status("proposed")
        state.seeds.toggle_check("EX001")
        state.seeds.select_found()
        self.assertTrue(state.seeds.filters_active() and state.seeds.checked)
        self.assertIsNone(state.seeds.close_dialog())
        self.assertIsNone(state.close_guard())

    def test_an_edited_seed_asks_with_a_two_way_question_whose_cancel_is_keep_editing(self):
        state = seed_state()
        state.seeds.open_detail("EX001")
        self.assertTrue(state.seeds.edit("reason", "고친 이유"))
        self.assertEqual((state.seeds.unsaved_targets(), state.seeds.has_unsaved()), ([("seed", "EX001")], True))
        dialog = state.close_guard()
        self.assertEqual(dialog, {"title": T["seeds_close_title"], "body": T["seeds_close_body"], "ok": T["seeds_close_ok"], "cancel": T["seeds_close_cancel"], "seeds": True})
        self.assertEqual((dialog["ok"], dialog["cancel"]), ("저장 안 하고 닫기", "계속 고치기"))
        self.assertNotIn("choices", dialog, "저장은 씨앗마다 서랍에서 따로 한다 — 한 번에 이어 주지 않는 두 갈래다")

    def test_putting_the_saved_value_back_or_reverting_asks_nothing(self):
        state = seed_state()
        state.seeds.open_detail("EX001")
        saved = state.seeds.values(state.seeds.open_seed())["reason"]
        state.seeds.edit("reason", "고친 이유")
        self.assertIsNotNone(state.seeds.close_dialog())
        state.seeds.edit("reason", saved)
        self.assertIsNone(state.seeds.close_dialog(), "저장된 값과 같아진 칸은 고친 것이 아니다")
        state.seeds.edit("reason", "또 고친 이유")
        self.assertTrue(state.seeds.revert())
        self.assertIsNone(state.seeds.close_dialog())

    def test_a_new_seed_form_asks_only_after_something_was_typed_and_a_closed_drawer_does_not_hide_it(self):
        state = seed_state()
        state.nav("seed")
        state.seeds.open_new()
        self.assertTrue(state.seeds.edit("keyword", "새 낱말"))
        self.assertEqual(state.seeds.unsaved_targets(), [("new", None)])
        state.seeds.close_drawer()
        self.assertEqual(state.seeds.unsaved_targets(), [("new", None)], "서랍을 닫아도 쓰던 값은 남아 있다 — 닫기에서는 그 값도 사라진다")
        state.nav("home")
        self.assertTrue(state.close_guard()["seeds"], "다른 화면에서 닫아도 묻는다")
        state.seeds.open_new()
        state.seeds.edit("keyword", "")
        self.assertIsNone(state.seeds.close_dialog(), "다시 비웠으면 쓰던 값이 없다")

    def test_several_places_still_make_one_question(self):
        state = seed_state()
        for seed_id in ("EX001", "EX002"):
            state.seeds.open_detail(seed_id)
            state.seeds.edit("reason", "고친 이유 " + seed_id)
        state.seeds.open_new()
        state.seeds.edit("minor", "새 중분류")
        self.assertEqual(state.seeds.unsaved_targets(), [("seed", "EX001"), ("seed", "EX002"), ("new", None)])
        self.assertEqual(state.close_guard()["title"], T["seeds_close_title"])

    def test_a_write_in_flight_is_waited_for_not_asked_about_but_other_inputs_still_count(self):
        provider = GatedSeeds()
        controller = seeds_view.SeedsController(provider, jobs.JobRunner())
        load_seeds(controller)
        controller.open_detail("EX001")
        controller.edit("reason", "저장할 이유")
        controller.open_detail("EX002")
        controller.edit("reason", "저장하지 않을 이유")
        controller.open_detail("EX001")
        collected = {}
        status, job = controller.start_save(**callbacks(collected))
        self.assertEqual(status, "started")
        self.addCleanup(provider.gate.set)
        self.assertTrue(controller.busy)
        self.assertEqual(controller.unsaved_targets(), [("seed", "EX002")], "저장 중인 씨앗은 그 저장이 끝나기를 기다린다 — 다른 씨앗의 입력은 그대로 센다")
        provider.gate.set()
        finish(job, collected, controller, "edit")
        self.assertEqual(controller.unsaved_targets(), [("seed", "EX002")], "저장이 끝나도 다른 씨앗의 입력은 남아 있다")

    def test_a_create_in_flight_leaves_the_new_form_out_and_a_busy_write_without_a_known_kind_counts_everything(self):
        controller = seeds_view.SeedsController(seeds.FakeSeedsProvider(), jobs.JobRunner())
        load_seeds(controller)
        controller.open_new()
        controller.edit("keyword", "새 낱말")
        gate = threading.Event()
        job = controller.runner.start(seeds_view.WRITE_KEY, lambda progress, cancelled: gate.wait(30))
        self.addCleanup(job.join, 10)
        self.addCleanup(gate.set)
        self.assertTrue(controller.busy)
        self.assertEqual(controller.unsaved_targets(), [("new", None)], "무슨 일인지 모르는 쓰기는 입력을 뺄 근거가 없다 — 묻는 쪽이 안전하다")
        controller.pending = {"kind": "create"}
        self.assertEqual(controller.unsaved_targets(), [], "새 Seed 를 등록하는 중이면 그 등록이 끝나기를 기다린다")

    def test_a_failed_save_keeps_the_input_and_the_question_stays(self):
        controller = seeds_view.SeedsController(FailingSeeds(), jobs.JobRunner())
        load_seeds(controller)
        controller.open_detail("EX001")
        controller.edit("reason", "저장에 실패할 이유")
        collected = {}
        status, job = controller.start_save(**callbacks(collected))
        self.assertEqual(status, "started")
        finish(job, collected, controller, "edit")
        self.assertIn("failed", collected)
        self.assertEqual(controller.unsaved_targets(), [("seed", "EX001")], "실패해도 입력은 그대로이고 닫기에서는 묻는다")

    def test_a_saved_seed_asks_nothing_afterwards(self):
        controller = seeds_view.SeedsController(seeds.FakeSeedsProvider(), jobs.JobRunner())
        load_seeds(controller)
        controller.open_detail("EX001")
        controller.edit("reason", "저장할 이유")
        collected = {}
        status, job = controller.start_save(**callbacks(collected))
        self.assertEqual(status, "started")
        finish(job, collected, controller, "edit")
        self.assertIn("ok", collected)
        self.assertEqual((controller.unsaved_targets(), controller.close_dialog()), ([], None))

    def test_when_the_data_could_not_be_read_the_edits_that_cannot_be_checked_still_count(self):
        state = seed_state()
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        state.seeds.apply_unexpected(RuntimeError("예시"))
        self.assertIsNone(state.seeds.data)
        self.assertEqual(state.seeds.unsaved_targets(), [("seed", "EX001")], "읽은 내용이 없어 같은지 견줄 수 없는 입력은 묻는 쪽이 안전하다")

    def test_moving_to_another_screen_never_asks_because_the_input_stays_in_the_controller(self):
        state = seed_state()
        state.nav("seed")
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        state.seeds.open_new()
        state.seeds.edit("keyword", "새 낱말")
        self.assertIsNone(state.leave_guard("home"), "Seed 입력은 화면 이동에 사라지지 않는다 — 묻지 않는다")
        self.assertTrue(state.nav("home"))
        self.assertEqual(state.seeds.unsaved_targets(), [("seed", "EX001"), ("new", None)], "서랍은 닫혀도 고친 값·쓰던 값은 그대로다")
        self.assertTrue(state.nav("seed"))
        self.assertEqual(state.seeds.values(state.seeds.by_id()["EX001"])["reason"], "고친 이유")

    def test_the_close_guard_goes_drafts_then_blogs_then_seeds(self):
        state = seed_state()
        load_blogs(state.blogs)
        self.assertIsNone(state.close_guard())
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        self.assertTrue(state.close_guard()["seeds"])
        state.blogs.edit("intro", "저장 전 소개")
        first = state.close_guard()
        self.assertEqual((first["title"], first.get("blogs"), first.get("seeds")), (T["blogs_close_title"], True, None), "블로그 확인이 Seed 확인보다 먼저다")
        self.assertEqual(state.seeds.close_dialog()["title"], T["seeds_close_title"], "블로그 확인 뒤에도 Seed 입력은 그대로라 Seed 확인이 이어서 뜬다")
        with mock.patch.object(state.drafts, "has_unsaved", return_value=True):
            third = state.close_guard()
            self.assertEqual((third.get("blogs"), third.get("seeds")), (None, None), "초안 확인이 맨 먼저다")

    def test_the_new_texts_exist_are_plain_and_every_one_is_used_in_the_code(self):
        keys = ("seeds_close_title", "seeds_close_body", "seeds_close_ok", "seeds_close_cancel")
        used = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "chanceblog_desktop" / "ui").rglob("*.py") if path.name != "seed_text.py")
        for key in keys:
            self.assertIn(key, T)
            self.assertIn(f'"{key}"', used, key)
            self.assertNotIn(TILDE, T[key])
        self.assertTrue(T["seeds_close_title"].endswith("닫을까요?"), "기존 블로그 닫기 질문처럼 물음으로 끝난다")


# ---- 2) 복원 중 저장 겹침 막기 ---------------------------------------------------------------------------------------------------------------
GUARDED = {"blogs_view.py": {"start_save", "start_clone", "start_clear"}, "seeds_view.py": {"start_save", "start_state", "start_bulk", "start_create", "start_import_apply"},
           "candidates_view.py": {"start_make"}, "drafts_view.py": {"start_save", "start_delete"}}
NOT_GUARDED = {"blogs_view.py": {"start_load", "start_adding"}, "seeds_view.py": {"start_load", "start_import_preview"}, "candidates_view.py": {"start_load", "start_preview"},
               "drafts_view.py": {"start_make", "start_regenerate", "start_list", "start_open_saved", "start_restore_photos", "start_clear_trash", "start_garbage"}}      # 읽기이거나 복원이 바꾸는 파일에 쓰지 않는 시작 함수


def held_state():
    """복원이 시험이 문을 열어 줄 때까지 도는 가짜 공급자를 짝으로 둔 화면 상태."""
    provider = HeldBackups()
    state = app_state.AppState(services.FakeHomeProvider(), backups=provider)
    state.backups.apply_loaded(provider.load_backups(SAFE, NEVER))
    load_seeds(state.seeds)
    load_blogs(state.blogs)
    return state, provider


class RestoreGateTest(unittest.TestCase):
    def start_restore(self, state, provider):
        collected = {}
        status, job = state.backups.start_restore(FULL_BACKUP, confirmed=True, **callbacks(collected))
        self.assertEqual(status, "started")
        self.addCleanup(job.join, 10)
        self.addCleanup(provider.gate.set)                                           # 나중에 등록한 것이 먼저 돈다 — 문을 먼저 열고 작업이 끝나기를 기다린다
        return job, collected

    def test_restoring_is_true_only_while_a_restore_or_a_revert_runs_and_a_plain_backup_never_counts(self):
        state, provider = held_state()
        self.assertEqual((state.backups.restoring, state.save_blocked()), (False, False))
        collected = {}
        status, job = state.backups.start_create(**callbacks(collected))
        self.assertEqual(status, "started")
        self.addCleanup(job.join, 10)
        self.addCleanup(provider.gate.set)
        self.assertEqual((state.backups.busy, state.backups.restoring, state.save_blocked()), (True, False, False), "지금 백업은 저장을 막지 않는다 — 읽기만 한다")
        provider.gate.set()
        finish(job, collected, state.backups, "create")
        provider.gate.clear()
        job, collected = self.start_restore(state, provider)
        self.assertEqual((state.backups.restoring, state.save_blocked()), (True, True))
        provider.gate.set()
        finish(job, collected, state.backups, "restore")
        self.assertEqual((state.backups.restoring, state.save_blocked()), (False, False), "끝나면 풀린다")

    def test_a_revert_of_a_stopped_restore_blocks_saves_like_a_restore(self):
        provider = HeldBackups("interrupted")
        state = app_state.AppState(services.FakeHomeProvider(), backups=provider)
        state.backups.apply_loaded(provider.load_backups(SAFE, NEVER))
        collected = {}
        status, job = state.backups.start_revert(confirmed=True, **callbacks(collected))
        self.assertEqual(status, "started")
        self.addCleanup(job.join, 10)
        self.addCleanup(provider.gate.set)
        self.assertEqual((state.backups.restoring, state.save_blocked()), (True, True))
        self.assertEqual(state.seeds.start_save(), ("restoring", None))

    def test_while_restoring_every_save_starter_refuses_starts_no_job_and_keeps_the_input(self):
        state, provider = held_state()
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        state.blogs.edit("intro", "저장 전 소개")
        self.start_restore(state, provider)
        starters = {"blogs.start_save": state.blogs.start_save, "blogs.start_clone": state.blogs.start_clone, "blogs.start_clear": state.blogs.start_clear,
                    "seeds.start_save": state.seeds.start_save, "seeds.start_state": lambda: state.seeds.start_state("approve"), "seeds.start_bulk": lambda: state.seeds.start_bulk("activate"),
                    "seeds.start_create": state.seeds.start_create, "seeds.start_import_apply": state.seeds.start_import_apply,
                    "candidates.start_make": state.candidates.start_make, "drafts.start_save": state.drafts.start_save, "drafts.start_delete": state.drafts.start_delete}
        for name, starter in starters.items():
            with self.subTest(starter=name):
                self.assertEqual(starter(), ("restoring", None))
        self.assertEqual((state.blogs.busy, state.seeds.busy, state.candidates.busy, state.drafts.store_busy), (False, False, False, False), "막은 일은 작업을 만들지 않았다")
        self.assertEqual((state.blogs.pending, state.seeds.pending), (None, None))
        self.assertEqual((state.seeds.unsaved_targets(), state.blogs.has_unsaved()), ([("seed", "EX001")], True), "입력은 그대로다")

    def test_without_a_restore_the_same_starters_are_not_refused_for_that_reason(self):
        state, _provider = held_state()
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        status, job = state.seeds.start_save(**callbacks({}))
        self.assertEqual(status, "started")
        job.join(10)
        self.assertNotEqual(state.blogs.start_clear(), ("restoring", None))
        self.assertNotEqual(state.drafts.start_save()[0], "restoring")

    def test_a_save_works_again_as_soon_as_the_restore_has_finished(self):
        state, provider = held_state()
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        job, collected = self.start_restore(state, provider)
        self.assertEqual(state.seeds.start_save(), ("restoring", None))
        provider.gate.set()
        finish(job, collected, state.backups, "restore")
        collected = {}
        status, saving = state.seeds.start_save(**callbacks(collected))
        self.assertEqual(status, "started", "복원이 끝난 뒤에는 같은 입력을 그대로 저장할 수 있다")
        finish(saving, collected, state.seeds, "edit")
        self.assertEqual(state.seeds.unsaved_targets(), [])

    def test_the_guard_reads_the_gate_of_each_controller_so_an_unwired_controller_is_never_blocked(self):
        controllers = {"blogs": blogs_view.BlogsController(blogs.FakeBlogsProvider(), jobs.JobRunner()), "seeds": seeds_view.SeedsController(seeds.FakeSeedsProvider(), jobs.JobRunner()),
                       "candidates": candidates_view.CandidatesController(candidates.FakeCandidatesProvider(), jobs.JobRunner()),
                       "drafts": drafts_view.DraftsController(drafts.FakeDraftsProvider(lambda: ()), jobs.JobRunner())}
        for name, controller in controllers.items():
            with self.subTest(controller=name):
                self.assertIsNone(controller.save_gate, "AppState 가 이어 줄 때만 생긴다")
        for name, controller in controllers.items():
            controller.save_gate = lambda: True
        self.assertEqual(controllers["seeds"].start_save(), ("restoring", None))
        self.assertEqual(controllers["blogs"].start_save(), ("restoring", None))
        self.assertEqual(controllers["candidates"].start_make(), ("restoring", None))
        self.assertEqual(controllers["drafts"].start_delete(), ("restoring", None))
        for controller in controllers.values():
            controller.save_gate = lambda: False
        self.assertNotEqual(controllers["seeds"].start_save(), ("restoring", None))
        self.assertNotEqual(controllers["drafts"].start_save(), ("restoring", None))

    def test_exactly_the_write_starters_carry_the_guard_and_every_other_start_function_is_a_known_read(self):
        found = {}
        for name in GUARDED:
            tree = ast.parse((UI_CORE / name).read_text(encoding="utf-8"))
            guarded, other = set(), set()
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("start_"):
                    (guarded if any(ast.unparse(item).endswith("blocked_while_restoring") for item in node.decorator_list) else other).add(node.name)
            found[name] = (guarded, other)
            with self.subTest(file=name):
                self.assertEqual(guarded, GUARDED[name], "쓰는 시작 함수에는 모두 복원 중 막기가 붙어 있다")
                self.assertEqual(other, NOT_GUARDED[name], "붙지 않은 시작 함수는 읽기이거나 복원이 바꾸는 파일에 쓰지 않는 것뿐이다 — 새 시작 함수가 생기면 어느 쪽인지 정해야 한다")

    # ---- 거꾸로: 저장 길이 도는 동안은 복원을 시작하지 않는다 ----
    def test_a_restore_is_not_started_while_a_save_runs_and_is_after_it_ends(self):
        provider = GatedSeeds()
        held = HeldBackups()
        state = app_state.AppState(services.FakeHomeProvider(), seeds=provider, backups=held)
        state.backups.apply_loaded(held.load_backups(SAFE, NEVER))
        load_seeds(state.seeds)
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        collected = {}
        status, job = state.seeds.start_save(**callbacks(collected))
        self.assertEqual(status, "started")
        self.addCleanup(provider.gate.set)
        self.assertTrue(state.writers_busy())
        self.assertEqual(state.backups.start_restore(FULL_BACKUP, confirmed=True), ("writing", None))
        self.assertEqual((state.backups.busy, state.backups.pending, held.writes), (False, None, []), "막은 복원은 작업을 만들지 않았다")
        provider.gate.set()
        finish(job, collected, state.seeds, "edit")
        self.assertFalse(state.writers_busy())
        held.gate.set()
        status, restoring = state.backups.start_restore(FULL_BACKUP, confirmed=True, **callbacks({}))
        self.assertEqual(status, "started", "저장이 끝나면 복원을 시작할 수 있다")
        restoring.join(10)

    def test_a_revert_of_a_stopped_restore_is_not_started_while_a_save_runs_either(self):
        provider = GatedSeeds()
        held = HeldBackups("interrupted")
        state = app_state.AppState(services.FakeHomeProvider(), seeds=provider, backups=held)
        state.backups.apply_loaded(held.load_backups(SAFE, NEVER))
        load_seeds(state.seeds)
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        collected = {}
        status, job = state.seeds.start_save(**callbacks(collected))
        self.assertEqual(status, "started")
        self.addCleanup(provider.gate.set)
        self.assertEqual(state.backups.start_revert(confirmed=True), ("writing", None))
        self.assertEqual((state.backups.busy, held.writes), (False, []))
        provider.gate.set()
        finish(job, collected, state.seeds, "edit")
        held.gate.set()
        status, reverting = state.backups.start_revert(confirmed=True, **callbacks({}))
        self.assertEqual(status, "started")
        reverting.join(10)

    def test_the_restore_gate_looks_at_all_four_writers(self):
        state = seed_state()
        gate = threading.Event()
        self.addCleanup(gate.set)
        keys = {"blogs": blogs_view.WRITE_KEY, "seeds": seeds_view.WRITE_KEY, "candidates": candidates_view.WRITE_KEY, "drafts": drafts_view.STORE_KEY}
        self.assertFalse(state.writers_busy())
        for name, key in keys.items():
            job = state.runner.start(key, lambda progress, cancelled: gate.wait(30))
            self.assertTrue(state.writers_busy(), name)
            gate.set()
            job.join(10)
            gate.clear()
            self.assertFalse(state.writers_busy(), name)

    def test_a_plain_backup_is_never_blocked_by_a_running_save(self):
        provider = GatedSeeds()
        state = app_state.AppState(services.FakeHomeProvider(), seeds=provider, backups=HeldBackups())
        load_seeds(state.seeds)
        state.seeds.open_detail("EX001")
        state.seeds.edit("reason", "고친 이유")
        status, saving = state.seeds.start_save(**callbacks({}))
        self.assertEqual(status, "started")
        self.addCleanup(saving.join, 10)
        self.addCleanup(provider.gate.set)
        self.assertTrue(state.writers_busy())
        backups_status, job = state.backups.start_create()
        self.assertEqual(backups_status, "started", "백업을 만드는 일은 저장과 겹쳐도 읽기만 한다")
        state.backups.runner.cancel(backup_view.WRITE_KEY)
        job.join(10)

    def test_the_two_new_notice_texts_exist_are_plain_and_are_used(self):
        used = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "chanceblog_desktop" / "ui").rglob("*.py") if path.name != "backup_text.py")
        for key in ("backup_blocks_save", "backup_wait_save"):
            self.assertIn(key, T)
            self.assertIn(f'"{key}"', used, key)
            self.assertNotIn(TILDE, T[key])
            self.assertLessEqual(len(T[key]), 90, "한 줄 안내다")
        self.assertIn("입력한 내용은 그대로", T["backup_blocks_save"])


if __name__ == "__main__":
    unittest.main()
