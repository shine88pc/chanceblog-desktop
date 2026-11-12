"""초안 작성 화면의 **저장한 초안**(순수 층 — `ui/core/drafts.py`·`drafts_view.py`·`draft_text.py`, 결정 D-361) 시험 — PySide6 없이 돈다(CI 와 같은 조건). 가짜 공급자의 메모리 저장소(`FakeDraftsProvider(saving=True)`)로 확인하고
실제 서비스와의 연결은 `test_ui_drafts_save_service` 가 본다.

지키는 것:
  1) **저장은 눌렀을 때뿐이다** — 만들기·고치기·검사·복사는 저장하지 않는다. 저장하면 '저장됨', 저장한 뒤 고치면 '저장한 뒤 고쳤어요'(글자 그대로 견준다), 새로 만든 초안은 새 초안이다(앞에 저장한 초안을 덮어쓰지 않는다).
  2) **저장 직전 검사**: 키·토큰 모양(여섯 종류)이 있으면 저장하지 않고 위치·종류만 알린다 — 찾은 글은 어디에도 없고 **건너뛰고 저장하는 길이 없다**. 그 밖의 저장 실패는 알림 줄이고 복사·편집은 그대로 쓸 수 있다.
  3) 떠나기·앱 닫기 앞의 확인창은 저장 기능이 있으면 세 갈래(저장 / 저장 안 하고 나가기 / 계속 고치기, 처음 포커스는 저장, Esc 는 계속 고치기)이고 저장 기능이 없으면 예전 그대로다. 저장하고 고치지 않았으면 묻지 않는다.
  4) 저장한 초안 목록·열기(글자 그대로·선택 입력·글 유형 복원, 후보가 없어도 열림)·지우기(확인창이 먼저)·늦게 온 답 버리기.
  5) 저장 기능이 없는 공급자에서는 저장 단추·상태·목록이 모두 없다(예전 그대로).
"""
import inspect
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as SS  # noqa: E402
from test_ui_drafts_core import CATALOG, GENERIC, HEALTH, KEYS_NOT_SHOWN, all_strings, made, target_of  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.ui.core import app_state, board_view, draft_rules as rules, draft_text, drafts, drafts_view as dv, jobs, text  # noqa: E402

T = text.T
EMOJI = chr(0x1F600)
NFD = "e" + chr(0x0301)
STORE_OPS = {"save": ("start_save", "apply_saved", "apply_save_failed"), "list": ("start_list", "apply_listing", "apply_list_failed"),
             "open": ("start_open_saved", "apply_opened", "apply_open_failed"), "delete": ("start_delete", "apply_deleted", "apply_delete_failed")}


def saving(rows=None, **more):
    provider = drafts.FakeDraftsProvider(lambda: CATALOG if rows is None else rows, saving=True, **more)
    return dv.DraftsController(provider, jobs.JobRunner()), provider


def drive(controller, starter=None, **kwargs):
    results = {}
    status, job = (starter or controller.start_make)(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure), **kwargs)
    if job is not None:
        job.join(30)
    if "ok" in results:
        controller.apply_made(results["ok"])
    elif "failed" in results:
        controller.apply_make_failed(results["failed"])
    return status


def made_saving(row=GENERIC, **more):
    controller, provider = saving(**more)
    controller.open_target(target_of(row))
    drive(controller)
    return controller, provider


def store(controller, op, *args, **kwargs):
    """저장한 초안 작업 하나를 작업 스레드에서 돌리고 도착한 값을 적용한다 → `(시작 상태, 적용 결과)`."""
    starter, ok, failed = (getattr(controller, name) for name in STORE_OPS[op])
    results = {}
    status, job = starter(*args, on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure), **kwargs)
    if job is not None:
        job.join(30)
    if "ok" in results:
        return status, ok(results["ok"])
    if "failed" in results:
        return status, failed(results["failed"])
    return status, None


def save(controller, **kwargs):
    return store(controller, "save", **kwargs)


def saved_id(provider):
    return next(iter(provider.saved))


class Slow(drafts.FakeDraftsProvider):
    """저장·열기·만들기를 시험이 문을 열어 줄 때까지 붙잡는다 — 시간에 기대지 않고 '도는 중' 을 확실히 본다."""

    def __init__(self, *args, hold=("save",), **kwargs):
        super().__init__(*args, **kwargs)
        self.hold, self.entered, self.release = set(hold), threading.Event(), threading.Event()

    def wait(self, name):
        if name in self.hold:
            self.entered.set()
            if not self.release.wait(30):
                raise AssertionError("시험이 문을 열어 주지 않았다")

    def save_draft(self, request, progress, cancelled):
        self.wait("save")
        return super().save_draft(request, progress, cancelled)

    def open_saved(self, draft_id, progress, cancelled):
        self.wait("open")
        return super().open_saved(draft_id, progress, cancelled)

    def make_draft(self, request, progress, cancelled):
        self.wait("make")
        return super().make_draft(request, progress, cancelled)


def slow_saving(hold=("save",)):
    provider = Slow(lambda: CATALOG, saving=True, hold=hold)
    controller = dv.DraftsController(provider, jobs.JobRunner())
    provider.hold = set()
    controller.open_target(target_of(GENERIC))
    drive(controller)
    provider.hold = set(hold)
    return controller, provider


class SaveStateTest(unittest.TestCase):
    def test_a_fresh_draft_is_unsaved_and_the_view_has_the_save_button_first_and_the_status_in_words(self):
        controller, _ = made_saving()
        view = controller.view()
        normal = view["normal"]
        self.assertTrue(controller.can_save)
        self.assertEqual(controller.save_state(), "unsaved")
        self.assertEqual([button["key"] for button in normal["actions"]["buttons"]], ["save", "title", "body", "all", "open"])
        self.assertEqual(normal["actions"]["buttons"][0]["kind"], "secondary")
        self.assertEqual([button["kind"] for button in normal["actions"]["buttons"]].count("primary"), 1, "화면의 주요 단추는 하나 — 전체 복사")
        self.assertEqual(normal["save"]["state"], "unsaved")
        self.assertEqual(normal["save"]["text"], T["drf_state_unsaved"])
        self.assertEqual(normal["save"]["a11y"], T["drf_state_a11y_unsaved"])
        self.assertEqual(normal["editor"]["save_text"], T["drf_state_unsaved"])
        self.assertEqual(normal["save"]["button"], {"key": "save", "text": T["drf_save"], "a11y": T["drf_save_a11y"], "enabled": True, "tip": T["drf_save_tip"]})
        self.assertEqual(view["saved_list"], {"text": T["drf_saved_list_btn"], "a11y": T["drf_saved_list_btn_a11y"], "enabled": True})
        self.assertEqual(view["sub"], T["drf_sub_save"], "저장 기능이 있으면 머리 설명이 저장을 알린다")
        self.assertNotIn("저장은 하지 않아요", T["drf_sub_save"])
        self.assertIn("Ctrl+S", T["drf_save_a11y"])

    def test_a_provider_without_saving_has_no_save_button_status_or_list(self):
        controller = made()
        view = controller.view()
        self.assertFalse(controller.can_save)
        self.assertEqual([button["key"] for button in view["normal"]["actions"]["buttons"]], ["title", "body", "all", "open"])
        self.assertNotIn("save", view["normal"])
        self.assertNotIn("save_text", view["normal"]["editor"])
        self.assertNotIn("saved_list", view)
        self.assertNotIn("saved", view["empty"])
        self.assertEqual(view["sub"], T["drf_sub"], "저장 기능이 없으면 머리 설명도 예전 그대로 — '저장은 하지 않아요'")
        self.assertIn("저장은 하지 않아요", T["drf_sub"])
        self.assertEqual(controller.save_state(), "none")
        self.assertEqual(controller.start_save(), ("unavailable", None))
        self.assertEqual(controller.start_list(), ("unavailable", None))
        self.assertEqual(controller.start_open_saved("dd-" + "0" * 20), ("unavailable", None))
        self.assertEqual(controller.start_delete(), ("unconfirmed", None))
        controller.set_body(controller.body + "x")
        self.assertEqual(sorted(controller.leave_dialog()), ["body", "cancel", "ok", "title"], "저장 기능이 없으면 예전의 두 갈래 그대로")

    def test_the_default_fake_provider_does_not_save(self):
        self.assertFalse(drafts.FakeDraftsProvider().saving)
        self.assertFalse(drafts.DraftsProvider.saving)
        self.assertTrue(drafts.FakeDraftsProvider(saving=True).saving)

    def test_saving_makes_it_saved_with_the_time_and_a_notice_and_nothing_is_saved_before_the_press(self):
        controller, provider = made_saving()
        self.assertEqual((provider.save_calls, provider.saved), ([], {}))
        controller.set_title(controller.title + "!")
        controller.inspect()
        controller.copy_decision("body")
        self.assertEqual((provider.save_calls, provider.saved), ([], {}), "고치기·검사·복사는 저장하지 않는다")
        status, applied = save(controller)
        self.assertEqual((status, applied), ("started", ("saved", None)))
        self.assertEqual(controller.save_state(), "saved")
        row = provider.saved[saved_id(provider)]
        when = board_view.time_text(row.updated_at)
        view = controller.view()["normal"]
        self.assertEqual(view["save"]["text"], T["drf_state_saved"].format(when=when))
        self.assertEqual(view["save"]["tone"], "green")
        self.assertEqual(controller.notice, ("ok", T["drf_saved_notice"].format(when=when)))
        self.assertEqual((row.title, row.body, row.revision), (controller.title, controller.body, 1))
        self.assertFalse(controller.has_unsaved())

    def test_editing_after_a_save_says_changed_and_editing_back_says_saved_again(self):
        controller, _ = made_saving()
        save(controller)
        before = controller.body
        controller.set_body(before + " 더")
        self.assertEqual(controller.save_state(), "changed")
        self.assertTrue(controller.has_unsaved())
        view = controller.view()["normal"]
        self.assertEqual((view["save"]["text"], view["save"]["tone"]), (T["drf_state_changed"], "orange"))
        controller.set_body(before)
        self.assertEqual(controller.save_state(), "saved")
        self.assertFalse(controller.has_unsaved())
        controller.set_title(controller.title + " ")
        self.assertEqual(controller.save_state(), "changed", "공백 하나도 달라진 글이다")

    def test_a_second_save_updates_the_same_draft_and_hands_the_revision_back(self):
        controller, provider = made_saving()
        save(controller)
        first = saved_id(provider)
        controller.set_body(controller.body + "\n둘째 저장")
        save(controller)
        second_request = provider.save_calls[1]
        self.assertEqual((second_request.draft_id, second_request.expected_revision), (first, 1))
        self.assertEqual((len(provider.saved), provider.saved[first].revision), (1, 2))
        self.assertEqual(controller.saved_rev, 2)

    def test_the_request_carries_the_edited_text_the_options_and_the_made_draft_as_the_base(self):
        controller, provider = made_saving()
        controller.set_title("고친 제목")
        controller.set_body("고친 본문\r\n둘째 줄 " + EMOJI + NFD)
        controller.set_blog("naver_b")
        controller.set_post_type("비교형")
        save(controller)
        request = provider.save_calls[0]
        body = controller.draft_body()
        self.assertEqual((request.title, request.body), ("고친 제목", "고친 본문\r\n둘째 줄 " + EMOJI + NFD))
        self.assertEqual((request.core_keywords, request.sub_keywords, request.tags, request.category, request.summary), (tuple(body.core_keywords), tuple(body.sub_keywords), tuple(body.tags), body.category, body.summary))
        self.assertEqual((request.candidate_id, request.topic, request.blog, request.post_type_choice, request.post_type), (GENERIC.candidate_id, body.topic, "naver_b", "비교형", controller.result.post_type))
        self.assertEqual(request.base["title"], body.selected_title)
        self.assertEqual(request.base["titles"], tuple(body.titles))
        self.assertEqual(request.base["body"], body.body_text)
        self.assertEqual(request.base["checks"], tuple(body.checks))
        self.assertEqual(request.base["domain"], body.domain)

    def test_a_save_without_a_draft_or_while_a_draft_is_made_or_while_another_save_runs_does_not_start(self):
        controller, _ = saving()
        self.assertEqual(controller.start_save(), ("unavailable", None))
        controller, provider = slow_saving(hold=("make",))
        self.assertEqual(controller.start_regenerate()[0], "started")
        self.assertTrue(provider.entered.wait(10))
        self.assertEqual(controller.start_save(), ("making", None))
        view = controller.view()["normal"]
        self.assertFalse(view["save"]["button"]["enabled"])
        self.assertEqual(view["save"]["button"]["tip"], T["drf_save_why_making"])
        provider.release.set()
        controller.runner.job(dv.DRAFT_KEY).join(30)
        controller, provider = slow_saving()
        status, job = controller.start_save(on_done=lambda *args: None, on_error=lambda *args: None)
        self.assertEqual(status, "started")
        self.assertTrue(provider.entered.wait(10))
        self.assertEqual(controller.save_state(), "saving")
        self.assertEqual(controller.start_save(), ("busy", None))
        self.assertEqual(controller.start_list(), ("busy", None))
        view = controller.view()["normal"]
        self.assertEqual((view["save"]["text"], view["save"]["button"]["enabled"], view["save"]["button"]["tip"]), (T["drf_state_saving"], False, T["drf_save_why_busy"]))
        provider.release.set()
        job.join(30)

    def test_text_typed_while_the_save_runs_stays_changed_after_it_because_the_saved_text_is_the_text_of_the_press(self):
        controller, provider = slow_saving()
        results = {}
        status, job = controller.start_save(on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
        self.assertTrue(provider.entered.wait(10))
        pressed = controller.body
        controller.set_body(pressed + " 저장하는 동안 친 글")
        provider.release.set()
        job.join(30)
        self.assertEqual(controller.apply_saved(results["ok"]), ("saved", None))
        self.assertEqual(controller.save_state(), "changed")
        self.assertEqual(provider.saved[saved_id(provider)].body, pressed)

    def test_a_new_draft_cuts_the_link_to_the_saved_one_and_saving_it_keeps_both(self):
        controller, provider = made_saving()
        save(controller)
        first = saved_id(provider)
        self.assertEqual(drive(controller, controller.start_regenerate), "started")
        self.assertEqual((controller.saved_id, controller.saved_rev, controller.saved_snapshot, controller.save_state()), (None, None, None, "unsaved"))
        controller.set_body(controller.body + "\n새로 만든 뒤 고침")
        save(controller)
        self.assertEqual(len(provider.saved), 2)
        self.assertIn(first, provider.saved)
        self.assertEqual(provider.save_calls[1].draft_id, None)

    def test_saving_a_second_draft_of_the_same_candidate_gives_a_second_row(self):
        first, provider = made_saving()
        save(first)
        first.set_title("다른 제목")
        first.set_body("다른 본문")
        self.assertEqual(drive(first), "started")
        save(first)
        self.assertEqual(len(provider.saved), 2)


def made_request(field, line):
    """키 모양 한 줄을 만든 초안의 칸 하나에만 넣은 저장 요청 — 고친 글(제목·본문)은 깨끗하다(`test_ui_drafts_save_service` 도 가져다 쓴다)."""
    base = {"title": "만든 제목", "titles": ["만든 제목", "후보 둘"], "body": "만든 본문", "checks": ["확인 하나"], "domain": "generic", "replaced": None}
    if field == "title":
        base["title"] = "앞 " + line
    elif field == "titles":
        base["titles"] = ["후보 하나", line]
    elif field == "body":
        base["body"] = "만든 본문\n" + line
    elif field == "checks":
        base["checks"] = ["확인 하나", line]
    else:
        base["replaced"] = ["후기형", "앞 " + line]
    return drafts.SaveRequest(title="깨끗한 제목", body="깨끗한 본문", blog="naver_a", post_type="정보형", base=base)


class SaveFailureTest(unittest.TestCase):
    def leaked(self, controller, failure, token):
        view = controller.view()
        normal = view["normal"]
        shown = {key: item for key, item in view.items() if key != "normal"}
        shown["normal"] = {**normal, "editor": {key: item for key, item in normal["editor"].items() if key != "value"},
                           "title_box": {key: item for key, item in normal["title_box"].items() if key not in ("value", "picks")}}      # 편집기·제목 칸의 값은 사용자가 쓴 글 자신이다
        pieces = [repr(shown), repr(controller.save_failure_dialog(failure)), failure.user_message, failure.advice, repr(failure.__dict__), repr(controller.notice)]
        return SS.leaked(" | ".join(pieces), token)

    def test_a_key_shape_in_the_body_or_the_title_is_not_saved_in_any_of_the_six_kinds_and_only_the_place_is_told(self):
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            for where, field in (("본문", "set_body"), ("제목", "set_title")):
                with self.subTest(kind=kind, where=where):
                    controller, provider = made_saving()
                    getattr(controller, field)("앞글 " + line + " 뒷글")
                    status, applied = save(controller)
                    self.assertEqual((status, applied[0], applied[1]), ("started", "keyshape", None))
                    failure = controller.take_save_problem()
                    self.assertEqual((failure.kind, failure.user_message), ("keyshape", T["drf_savefail_secret_head"]))
                    self.assertIn(where, failure.advice)
                    self.assertIn("자동으로 지우거나 바꾸지 않아요", failure.advice)
                    self.assertEqual((provider.saved, controller.save_state()), ({}, "unsaved"))
                    self.assertFalse(self.leaked(controller, failure, token), "찾은 글이 화면·안내·실패 값 어디에도 없다")
                    self.assertIsNone(controller.take_save_problem(), "한 번만 알리고 거둔다")

    def test_the_alert_for_a_key_shape_has_one_ok_button_and_no_way_to_save_anyway(self):
        controller, _ = made_saving()
        controller.set_body("글 " + SS.sample("github_token")[1])
        save(controller)
        failure = controller.take_save_problem()
        dialog = controller.save_failure_dialog(failure)
        self.assertEqual(sorted(dialog), ["body", "cancel", "ok", "title"])
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), (T["drf_savefail_secret_title"], T["drf_savefail_secret_ok"], None))
        self.assertIn(T["drf_savefail_secret_head"], dialog["body"])
        self.assertIn("본문에서 1건(GitHub 토큰 1)", dialog["body"])
        self.assertNotIn("choices", dialog)
        shown = " ".join(all_strings(dialog))
        for word in ("무시", "그래도 저장", "건너", "강제"):
            self.assertNotIn(word, shown)

    def test_the_controller_has_no_argument_that_could_skip_the_check(self):
        self.assertEqual(list(inspect.signature(dv.DraftsController.start_save).parameters), ["self", "on_progress", "on_done", "on_error", "on_cancel", "after"])
        self.assertEqual(list(inspect.signature(drafts.SaveRequest).parameters), ["title", "body", "core_keywords", "sub_keywords", "tags", "category", "summary", "candidate_id", "topic", "blog",
                                                                                   "post_type_choice", "post_type", "options", "base", "draft_id", "expected_revision"])
        for name in dir(dv.DraftsController):
            self.assertFalse(any(word in name.lower() for word in ("force", "ignore_secret", "skip_check", "bypass", "override", "save_anyway")), name)

    def test_the_fake_store_stops_for_a_key_shape_only_in_the_made_draft_and_tells_the_special_advice(self):
        """서비스와 같은 규칙(D-368) — 만든 초안의 칸 다섯 곳 어디에서든 찾으면 저장하지 않고, 안내는 위치와 전용 문구(후보·블로그 프로필·선택 입력을 고쳐 다시 만들기·먼저 복사)다."""
        from chanceblog_desktop.content import saved_draft as sd
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            for field, label in (("title", "만든 초안 제목"), ("titles", "만든 초안 제목 후보"), ("body", "만든 초안 본문"), ("checks", "만든 초안 확인 권장"), ("replaced", "만든 초안 바꾼 형식")):
                with self.subTest(kind=kind, field=field):
                    provider = drafts.FakeDraftsProvider(saving=True)
                    with self.assertRaises(drafts.DraftFailure) as caught:
                        provider.save_draft(made_request(field, line), lambda *_: None, lambda: False)
                    failure = caught.exception
                    self.assertEqual((failure.kind, failure.user_message), ("keyshape", T["drf_savefail_secret_head"]))
                    self.assertIn(label, failure.advice)
                    self.assertTrue(failure.advice.endswith(sd.MADE_DRAFT_ADVICE))
                    self.assertEqual(provider.saved, {}, "아무것도 저장하지 않았다")
                    self.assertFalse(SS.leaked(failure.advice + repr(failure.__dict__) + failure.user_message, token))

    def test_the_fake_store_gives_the_made_draft_advice_only_for_made_draft_places(self):
        provider = drafts.FakeDraftsProvider(saving=True)
        line = SS.sample("github_token")[1]
        with self.assertRaises(drafts.DraftFailure) as caught:
            provider.save_draft(drafts.SaveRequest(title="깨끗한 제목", body="본문\n" + line, blog="naver_a", post_type="정보형"), lambda *_: None, lambda: False)
        self.assertNotIn("다시 만들기", caught.exception.advice)
        self.assertIn("본문에서 1건(GitHub 토큰 1) — 2번째 줄", caught.exception.advice)

    def test_the_fake_store_caps_any_new_row_like_the_service(self):
        """서비스와 같은 규칙(D-371) — 새 행을 만드는 저장은 번호를 직접 주었어도 300편 한도에 걸린다. 있는 글을 고치는 저장은 한도에 걸리지 않는다."""
        from chanceblog_desktop.content import saved_draft as sd
        provider = drafts.FakeDraftsProvider(saving=True)
        for number in range(sd.MAX_SAVED):
            provider.save_draft(drafts.SaveRequest(title=f"제목 {number}", body=f"본문 {number}", blog="naver_a", post_type="정보형"), lambda *_: None, lambda: False)
        self.assertEqual(len(provider.saved), sd.MAX_SAVED)
        with self.assertRaises(drafts.DraftFailure) as caught:
            provider.save_draft(drafts.SaveRequest(title="번호를 준 새 글", body="본문", blog="naver_a", post_type="정보형", draft_id="dd-" + "f" * 20, expected_revision=1), lambda *_: None, lambda: False)
        self.assertEqual(caught.exception.kind, "limit")
        first = sorted(provider.saved)[0]
        updated = provider.save_draft(drafts.SaveRequest(title="고친 제목", body="고친 본문", blog="naver_a", post_type="정보형", draft_id=first, expected_revision=1), lambda *_: None, lambda: False)
        self.assertEqual(updated.revision, 2)

    def test_the_fake_store_scans_every_edited_field_like_the_service(self):
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            controller, provider = made_saving()
            controller.set_body("글 " + line)
            applied = save(controller)[1]
            self.assertEqual(applied[0], "keyshape", kind)
            self.assertEqual(provider.saved, {})

    def test_other_failures_are_a_notice_line_and_copy_and_edit_still_work(self):
        for code, kind, key in (("DISK_FULL", "io", "drf_savefail_io"), ("FILE_WRITE_FAILED", "io", "drf_savefail_io"), ("STORE_LOCKED", "locked", "drf_savefail_locked"), ("STORE_CORRUPT", "corrupt", "drf_savefail_corrupt"), ("DRAFT_CORRUPT", "record", "drf_savefail_record"),
                                ("STORE_VERSION_UNSUPPORTED", "newer", "drf_savefail_newer"), ("STORE_CONFLICT", "conflict", "drf_savefail_conflict"), ("CONTENT_INVALID", "invalid", "drf_savefail_invalid"),
                                ("SOMETHING_ELSE", "other", "drf_savefail_other")):
            with self.subTest(code=code):
                controller, provider = made_saving(save_fail=drafts.save_failure(AppError(code, {"파일": "C:/secret/path/chanceblog.db"}, detail="C:/Users/someone/AppData")))
                status, applied = save(controller)
                self.assertEqual(applied, (kind, None))
                self.assertEqual(controller.notice, ("error", T[key]))
                self.assertIsNone(controller.save_failure_dialog(controller.take_save_problem()))
                self.assertEqual(controller.save_state(), "unsaved")
                shown = repr(controller.view())
                for leak in ("C:/", "someone", "AppData", code if code != "SOMETHING_ELSE" else "STORE_"):
                    self.assertNotIn(leak, shown)
                controller.set_body(controller.body + "!")
                self.assertEqual(controller.copy_decision("tags")[0], "copy", "저장이 안 돼도 복사는 그대로다")
                self.assertTrue(controller.set_title("고침"))

    def test_a_locked_store_and_one_broken_record_are_told_as_they_are(self):
        """예전에는 잠긴 보관함이 '디스크 공간이나 파일 권한' 문장으로, 기록 하나만 깨진 것이 '글 보관함 파일이 깨져' 문장으로 나갔다(D-371) — 사실 그대로 말한다."""
        locked = drafts.save_failure(AppError("STORE_LOCKED"))
        record = drafts.save_failure(AppError("DRAFT_CORRUPT", {"항목": "저장한 초안"}))
        file_broken = drafts.save_failure(AppError("STORE_CORRUPT", {"파일": "chanceblog.db"}))
        self.assertEqual((locked.kind, record.kind, file_broken.kind), ("locked", "record", "corrupt"))
        self.assertEqual((locked.user_message, record.user_message), (T["drf_savefail_locked"], T["drf_savefail_record"]))
        for word in ("디스크", "권한", "폴더"):
            self.assertNotIn(word, locked.user_message)
        self.assertIn("다른 곳에서 쓰고 있어서", locked.user_message)
        self.assertIn("잠시 뒤에 다시 저장", locked.user_message)
        self.assertNotIn("파일이 깨져", record.user_message)
        self.assertIn("기록 하나", record.user_message)
        self.assertIn("먼저 복사", record.user_message)
        self.assertIn("파일이 깨져", file_broken.user_message, "파일 전체가 깨진 경우는 그대로 파일이 깨졌다고 말한다")
        for failure in (locked, record):
            self.assertIn("복사와 편집은 그대로 쓸 수 있어요", failure.user_message)
            self.assertEqual(failure.advice, "")

    def test_every_kind_of_failure_has_its_own_sentence_and_the_two_new_kinds_are_known(self):
        self.assertIn("locked", drafts.KINDS_OF_FAILURE)
        self.assertIn("record", drafts.KINDS_OF_FAILURE)
        self.assertEqual(sorted(set(drafts.KINDS_OF_FAILURE) - {"keyshape", "stopped", "channel", "option"}), sorted(drafts.SAVE_SENTENCE_OF_KIND))
        self.assertEqual(drafts.SAVE_KIND_OF_CODE["STORE_LOCKED"], "locked")
        self.assertEqual(drafts.SAVE_KIND_OF_CODE["DRAFT_CORRUPT"], "record")

    def test_a_limit_failure_names_the_reason_in_one_phrase(self):
        failure = drafts.save_failure(AppError("DRAFT_LIMIT", {"이유": "저장한 초안이 300편이에요"}))
        self.assertEqual((failure.kind, failure.reason), ("limit", "저장한 초안이 300편이에요"))
        self.assertIn("저장한 초안이 300편이에요", failure.user_message)
        self.assertIn("지운 뒤 다시 저장", failure.user_message)

    def test_a_failed_save_keeps_the_saved_state_of_an_earlier_save(self):
        controller, provider = made_saving()
        save(controller)
        controller.set_body(controller.body + " 더")
        provider.save_fail = drafts.save_failure(AppError("DISK_FULL"))
        self.assertEqual(save(controller)[1][0], "io")
        self.assertEqual(controller.save_state(), "changed")
        self.assertEqual((controller.saved_id, controller.saved_rev), (saved_id(provider), 1))
        provider.save_fail = None
        self.assertEqual(save(controller)[1], ("saved", None))
        self.assertEqual(controller.saved_rev, 2)

    def test_a_conflict_failure_does_not_overwrite_and_keeps_the_text(self):
        controller, provider = made_saving()
        save(controller)
        row = provider.saved[saved_id(provider)]
        import dataclasses
        provider.saved[row.draft_id] = dataclasses.replace(row, revision=5)
        controller.set_body(controller.body + " 낡은 화면에서 고침")
        self.assertEqual(save(controller)[1][0], "conflict")
        self.assertEqual(provider.saved[row.draft_id].revision, 5)
        self.assertEqual(provider.saved[row.draft_id].body, row.body)
        self.assertTrue(controller.body.endswith("낡은 화면에서 고침"))

    def test_a_failure_after_the_leave_dialog_asks_before_leaving_and_warns(self):
        controller, provider = made_saving()
        controller.set_body("글 " + SS.sample("aws_access_key")[1])
        for after, discard in ((("leave", "topics"), "drf_choice_discard_leave"), (("close", None), "drf_choice_discard_close")):
            status, applied = save(controller, after=after)
            self.assertEqual(applied, ("keyshape", after))
            failure = controller.take_save_problem()
            dialog = controller.save_failure_dialog(failure, after)
            self.assertEqual((dialog["ok"], dialog["cancel"]), (T[discard], T["drf_choice_stay"]))
            self.assertTrue(dialog["body"].endswith(T["drf_savefail_leave_tail"]))
            self.assertIn("AWS 액세스 키", dialog["body"])
            self.assertEqual(dialog["title"], T["drf_savefail_secret_title"])
        provider.save_fail = drafts.save_failure(AppError("DISK_FULL"))
        controller.set_body("고친 글")
        applied = save(controller, after=("leave", "topics"))[1]
        dialog = controller.save_failure_dialog(controller.take_save_problem(), applied[1])
        self.assertEqual(dialog["title"], T["drf_savefail_leave_title"])
        self.assertIn(T["drf_savefail_io"], dialog["body"])

    def test_a_save_that_succeeds_after_the_dialog_hands_back_what_to_do_next(self):
        controller, _ = made_saving()
        self.assertEqual(save(controller, after=("leave", "topics"))[1], ("saved", ("leave", "topics")))
        controller.set_body(controller.body + "x")
        self.assertEqual(save(controller, after=("close", None))[1], ("saved", ("close", None)))

    def test_a_late_answer_after_leaving_changes_nothing(self):
        controller, provider = slow_saving()
        results = {}
        status, job = controller.start_save(on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
        self.assertTrue(provider.entered.wait(10))
        controller.leave()
        provider.release.set()
        job.join(30)
        self.assertEqual(controller.apply_saved(results["ok"]), ("left", None))
        self.assertEqual((controller.state, controller.saved_id, controller.notice), ("empty", None, None))
        self.assertEqual(len(provider.saved), 1, "저장은 됐다 — 이 화면만 모른다")


class LeaveDialogTest(unittest.TestCase):
    def test_with_saving_the_dialog_has_three_choices_in_a_fixed_order(self):
        controller, _ = made_saving()
        controller.set_body(controller.body + " 고침")
        for kind, discard, body in (("leave", "drf_choice_discard_leave", "drf_leave3_body"), ("close", "drf_choice_discard_close", "drf_close3_body")):
            dialog = controller.leave_dialog(kind)
            self.assertEqual([choice["key"] for choice in dialog["choices"]], ["save", "discard", "stay"])
            self.assertEqual([choice["kind"] for choice in dialog["choices"]], ["primary", "danger", "secondary"])
            self.assertEqual([choice["text"] for choice in dialog["choices"]], [T["drf_choice_save"], T[discard], T["drf_choice_stay"]])
            self.assertEqual((dialog["title"], dialog["body"], dialog["first"], dialog["after"]), (T["drf_leave3_title"], T[body], "save", kind))
            self.assertEqual((dialog["ok"], dialog["cancel"]), (T["drf_choice_save"], T["drf_choice_stay"]))
            self.assertEqual(controller.leave_asked, kind)
            controller.discard_leave()
            self.assertIsNone(controller.leave_asked)

    def test_the_three_choice_texts_are_the_ones_the_brief_names(self):
        self.assertEqual(T["drf_choice_save"], "저장")
        self.assertEqual(T["drf_choice_discard_leave"], "저장 안 하고 나가기")
        self.assertEqual(T["drf_choice_stay"], "계속 고치기")

    def test_a_saved_and_unchanged_draft_asks_nothing_and_an_unsaved_edit_asks(self):
        controller, _ = made_saving()
        self.assertIsNone(controller.leave_dialog(), "고치지 않은 새 초안은 예전처럼 묻지 않는다")
        controller.set_body(controller.body + "x")
        self.assertIsNotNone(controller.leave_dialog())
        save(controller)
        self.assertIsNone(controller.leave_dialog())
        self.assertIsNone(controller.leave_dialog("close"))
        controller.set_body(controller.body + "y")
        self.assertIsNotNone(controller.leave_dialog("close"))

    def test_an_unapplied_option_text_still_asks(self):
        controller, _ = made_saving()
        save(controller)
        controller.set_option("message", "아직 반영하지 않은 글")
        self.assertTrue(controller.has_unsaved())
        self.assertIsNotNone(controller.leave_dialog())

    def test_the_app_state_guards_use_the_same_dialog_and_navigation_follows_saved_state(self):
        provider = drafts.FakeDraftsProvider(lambda: CATALOG, saving=True)
        state = app_state.AppState(drafts=provider)
        state.page = "drafts"
        state.drafts.open_target(target_of(GENERIC))
        drive(state.drafts)
        state.drafts.set_body(state.drafts.body + "x")
        self.assertIn("choices", state.leave_guard("topics"))
        self.assertIn("choices", state.close_guard())
        self.assertFalse(state.nav("topics"))
        self.assertEqual(state.page, "drafts")
        save(state.drafts)
        self.assertIsNone(state.leave_guard("topics"))
        self.assertTrue(state.nav("topics"))
        self.assertEqual((state.page, state.drafts.state), ("topics", "empty"))

    def test_the_choices_never_offer_to_save_without_the_check(self):
        controller, _ = made_saving()
        controller.set_body(controller.body + "x")
        dialog = controller.leave_dialog()
        for item in all_strings(dialog):
            for word in ("무시", "건너", "그래도 저장"):
                self.assertNotIn(word, item)


class OpenSavedTest(unittest.TestCase):
    def saved_one(self, **edits):
        controller, provider = made_saving()
        if "title" in edits:
            controller.set_title(edits["title"])
        if "body" in edits:
            controller.set_body(edits["body"])
        save(controller)
        return controller, provider, saved_id(provider)

    def reopen(self, provider, draft_id):
        fresh = dv.DraftsController(provider, jobs.JobRunner())
        status, applied = store(fresh, "open", draft_id)
        return fresh, status, applied

    def test_the_editor_gets_the_saved_title_and_body_to_the_character(self):
        body = "첫 줄\r\n둘째 줄\r\n" + EMOJI + NFD + chr(0) + "  끝  "
        controller, provider, draft_id = self.saved_one(title="  고친 제목  ", body=body)
        fresh, status, applied = self.reopen(provider, draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual((fresh.state, fresh.title, fresh.body), ("normal", "  고친 제목  ", body))
        self.assertEqual((fresh.saved_id, fresh.saved_rev, fresh.save_state(), fresh.has_unsaved()), (draft_id, 1, "saved", False))
        self.assertEqual(fresh.view()["normal"]["save"]["text"], T["drf_state_saved"].format(when=board_view.time_text(provider.saved[draft_id].updated_at)))

    def test_the_options_the_blog_and_the_post_type_come_back_and_nothing_is_pending(self):
        controller, provider = made_saving()
        controller.set_option("message", "전하고 싶은 말")
        controller.set_option("must_include", "줄 하나\n줄 둘")
        controller.set_blog("naver_b")
        controller.set_post_type("비교형")
        self.assertEqual(drive(controller), "started")
        save(controller)
        fresh, _, applied = self.reopen(provider, saved_id(provider))
        self.assertTrue(applied)
        self.assertEqual((fresh.blog, fresh.post_type), ("naver_b", "비교형"))
        self.assertEqual(fresh.fields.get("message"), "전하고 싶은 말")
        self.assertEqual(fresh.fields.get("must_include"), "줄 하나\n줄 둘")
        self.assertFalse(fresh.options_pending())
        vm = fresh.view()["normal"]["options"]
        self.assertEqual([item["key"] for item in vm["blogs"] if item["active"]], ["naver_b"])
        self.assertEqual([item["key"] for item in vm["types"] if item["active"]], ["비교형"])

    def test_the_made_draft_bases_the_edit_amount_the_title_picks_and_the_checks(self):
        controller, provider, draft_id = self.saved_one(title="아주 다른 제목", body="완전히 다른 본문 " * 40)
        original = controller.draft_body()
        fresh, *_ = self.reopen(provider, draft_id)
        body = fresh.draft_body()
        self.assertEqual((tuple(body.titles), body.selected_title, body.body_text, tuple(body.checks), body.domain), (tuple(original.titles), original.selected_title, original.body_text, tuple(original.checks), original.domain))
        self.assertEqual((fresh.title_edited(), fresh.body_edited()), (True, True))
        self.assertTrue(fresh.editor_status()["edited"])
        self.assertEqual([item["text"] for item in fresh.title_picks()], [item["text"] for item in controller.title_picks()])
        self.assertEqual(fresh.checks(), controller.checks())

    def test_a_restored_draft_copies_like_the_made_one_with_the_same_gates(self):
        controller, provider, draft_id = self.saved_one()
        fresh, *_ = self.reopen(provider, draft_id)
        for item in ("title", "keywords", "tags", "summary"):
            self.assertEqual(fresh.copy_decision(item)[0], controller.copy_decision(item)[0], item)
        self.assertEqual(fresh.text_for("all"), controller.text_for("all"))
        self.assertEqual(fresh.text_for("tags"), controller.text_for("tags"))

    def test_with_the_candidate_still_there_regenerate_works_and_the_target_is_set(self):
        controller, provider, draft_id = self.saved_one()
        fresh, *_ = self.reopen(provider, draft_id)
        self.assertIsNone(fresh.notice)
        self.assertEqual(fresh.target.candidate_id, GENERIC.candidate_id)
        self.assertTrue(fresh.view()["normal"]["options"]["apply"]["enabled"])
        self.assertEqual(drive(fresh, fresh.start_regenerate), "started")
        self.assertEqual((fresh.save_state(), fresh.saved_id), ("unsaved", None))

    def test_without_the_candidate_it_still_opens_with_a_note_and_regenerate_is_off(self):
        controller, provider, draft_id = self.saved_one()
        provider._source = lambda: ()
        fresh, status, applied = self.reopen(provider, draft_id)
        self.assertTrue(applied)
        self.assertEqual(fresh.state, "normal")
        self.assertEqual(fresh.notice, ("info", T["drf_open_nocandidate"]))
        self.assertIsNone(fresh.target)
        self.assertEqual(fresh.start_make(), ("unavailable", None))
        self.assertEqual(fresh.start_regenerate(), ("unavailable", None))
        vm = fresh.view()["normal"]
        self.assertEqual(vm["context"]["candidate"], "")
        self.assertEqual(fresh.body, controller.body)
        self.assertFalse(fresh.has_unsaved())

    def test_a_draft_that_had_no_candidate_says_so_in_the_same_words(self):
        controller, provider, draft_id = self.saved_one()
        import dataclasses
        provider.saved[draft_id] = dataclasses.replace(provider.saved[draft_id], candidate_id="")
        fresh, _, applied = self.reopen(provider, draft_id)
        self.assertTrue(applied)
        self.assertEqual(fresh.notice, ("info", T["drf_open_nocandidate"]))

    def test_opening_shows_the_loading_state_with_its_own_sentence_then_the_draft(self):
        controller, provider, draft_id = self.saved_one()
        slow = Slow(lambda: CATALOG, saving=True, hold=("open",), saved=provider.saved)
        fresh = dv.DraftsController(slow, jobs.JobRunner())
        results = {}
        status, job = fresh.start_open_saved(draft_id, on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
        self.assertTrue(slow.entered.wait(10))
        view = fresh.view()
        self.assertEqual((view["state"], view["loading"]["text"], fresh.opening), ("loading", T["drf_saved_opening"], draft_id))
        slow.release.set()
        job.join(30)
        self.assertTrue(fresh.apply_opened(results["ok"]))
        self.assertEqual((fresh.view()["state"], fresh.opening), ("normal", None))

    def test_leaving_while_it_opens_drops_the_late_answer(self):
        controller, provider, draft_id = self.saved_one()
        slow = Slow(lambda: CATALOG, saving=True, hold=("open",), saved=provider.saved)
        fresh = dv.DraftsController(slow, jobs.JobRunner())
        results = {}
        status, job = fresh.start_open_saved(draft_id, on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
        self.assertTrue(slow.entered.wait(10))
        fresh.leave()
        slow.release.set()
        job.join(30)
        self.assertFalse(fresh.apply_opened(results["ok"]))
        self.assertEqual((fresh.state, fresh.result, fresh.title), ("empty", None, ""))

    def test_a_draft_that_is_gone_or_unreadable_goes_back_to_the_list_with_one_line(self):
        controller, provider = saving()
        status, applied = store(controller, "open", "dd-" + "0" * 20)
        self.assertEqual((status, applied), ("started", "notfound"))
        self.assertEqual((controller.state, controller.list_notice), ("empty", ("error", T["drf_openfail_notfound"])))
        for code, key in (("DRAFT_CORRUPT", "drf_openfail_corrupt"), ("DISK_FULL", "drf_openfail_other")):
            with self.subTest(code=code):
                bad = Slow(lambda: CATALOG, saving=True, hold=())
                bad.open_saved = lambda draft_id, progress, cancelled, code=code: (_ for _ in ()).throw(drafts.save_failure(AppError(code)))
                fresh = dv.DraftsController(bad, jobs.JobRunner())
                store(fresh, "open", "dd-" + "0" * 20)
                self.assertEqual(fresh.list_notice, ("error", T[key]))

    def test_an_open_draft_with_unsaved_edits_is_not_replaced_without_the_dialog(self):
        controller, provider, draft_id = self.saved_one()
        controller.set_body(controller.body + "x")
        self.assertEqual(controller.start_open_saved(draft_id), ("unconfirmed", None))
        save(controller)
        self.assertEqual(controller.start_open_saved(draft_id)[0], "started")


class ListAndDeleteTest(unittest.TestCase):
    def fill(self, count=3):
        controller, provider = made_saving()
        for number in range(count):
            controller.set_title(f"제목 {number}")
            controller.set_body(f"본문 {number}\n둘째 줄 {number}")
            save(controller)
            if number + 1 < count:
                drive(controller, controller.start_regenerate)
        fresh = dv.DraftsController(provider, jobs.JobRunner())
        return fresh, provider

    def test_the_list_shows_newest_first_with_title_candidate_blog_time_and_character_count(self):
        controller, provider = self.fill(3)
        self.assertEqual(store(controller, "list"), ("started", True))
        saved = controller.view()["empty"]["saved"]
        self.assertEqual((saved["visible"], saved["state"], saved["count"], saved["count_text"]), (True, "ok", 3, T["drf_saved_count"].format(n=3)))
        self.assertEqual([row["title"] for row in saved["rows"]], ["제목 2", "제목 1", "제목 0"])
        row = saved["rows"][0]
        record = next(item for item in provider.saved.values() if item.title == "제목 2")
        self.assertEqual(row["meta"], T["drf_saved_row_meta"].format(topic=rules.shown(record.topic, 40), blog=T["drf_saved_blog_naver_a"], when=board_view.time_text(record.updated_at), chars=f"{len(''.join(record.body.split())):,}"))
        self.assertEqual((row["open"]["text"], row["delete"]["text"], row["unreadable"]), (T["drf_saved_open"], T["drf_saved_delete"], False))
        self.assertIn("제목 2", row["open"]["a11y"])
        self.assertIn("제목 2", row["delete"]["a11y"])
        self.assertTrue(row["a11y"].startswith("제목 2, "))
        self.assertEqual(row["id"], record.draft_id, "열쇠는 줄에 있지만 글에는 나가지 않는다")

    def test_the_numbers_are_keys_only_and_never_part_of_a_shown_text(self):
        controller, provider = self.fill(2)
        store(controller, "list")
        saved = controller.view()["empty"]["saved"]
        for value in all_strings(saved, KEYS_NOT_SHOWN):
            for draft_id in provider.saved:
                self.assertNotIn(draft_id, value)
                self.assertNotIn(draft_id[3:], value)

    def test_an_empty_list_an_error_and_the_loading_state_have_their_own_sentences(self):
        controller, provider = saving()
        self.assertEqual(controller.view()["empty"]["saved"]["state"], "loading", "아직 읽기 전")
        store(controller, "list")
        saved = controller.view()["empty"]["saved"]
        self.assertEqual((saved["state"], saved["rows"], saved["empty"], saved["count_text"]), ("ok", [], T["drf_saved_empty"], T["drf_saved_count"].format(n=0)))
        provider.list_saved = lambda progress, cancelled: (_ for _ in ()).throw(drafts.save_failure(AppError("STORE_CORRUPT")))
        status, applied = store(controller, "list")
        self.assertEqual(applied, True)
        saved = controller.view()["empty"]["saved"]
        self.assertEqual((saved["state"], saved["error"]["text"], saved["error"]["button"]), ("error", T["drf_saved_error"], T["drf_saved_retry"]))
        self.assertEqual(saved["rows"], [])

    def test_an_unreadable_draft_has_only_a_delete_button_and_the_other_rows_stay(self):
        controller, provider = self.fill(1)
        provider.list_saved = lambda progress, cancelled: drafts.SavedListing(provider.__class__.list_saved(provider, progress, cancelled).rows, ("dd-" + "b" * 20,))
        store(controller, "list")
        saved = controller.view()["empty"]["saved"]
        self.assertEqual(len(saved["rows"]), 2)
        bad = saved["rows"][1]
        self.assertEqual((bad["unreadable"], bad["open"], bad["delete"]["text"]), (True, None, T["drf_saved_delete"]))
        self.assertEqual(bad["title"], T["drf_saved_unreadable_row"].format(number="dd-bbbbbbbb"))
        self.assertEqual(saved["unreadable_note"], T["drf_saved_unreadable_note"].format(n=1))
        self.assertEqual(saved["count"], 1)

    def test_delete_asks_first_with_cancel_as_the_way_out_and_does_nothing_without_the_dialog(self):
        controller, provider = self.fill(2)
        store(controller, "list")
        self.assertEqual(controller.start_delete(), ("unconfirmed", None))
        target = controller.listing.rows[0]
        dialog = controller.delete_dialog(target.draft_id)
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), (T["drf_delete_title"], T["drf_delete_ok"], T["drf_cancel"]))
        self.assertIn(target.title, dialog["body"])
        self.assertIn("백업", dialog["body"])
        controller.discard_delete()
        self.assertEqual(controller.start_delete(), ("unconfirmed", None))
        self.assertEqual(len(provider.saved), 2)
        self.assertIsNone(controller.delete_dialog("dd-" + "9" * 20), "목록에 없는 번호는 묻지 않는다")

    def test_a_confirmed_delete_removes_only_that_draft_and_says_so(self):
        controller, provider = self.fill(3)
        store(controller, "list")
        target = controller.listing.rows[1]
        controller.delete_dialog(target.draft_id)
        status, applied = store(controller, "delete")
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(controller.list_notice, ("ok", T["drf_deleted_notice"]))
        self.assertNotIn(target.draft_id, provider.saved)
        self.assertEqual(len(provider.saved), 2)
        self.assertEqual(controller.start_delete(), ("unconfirmed", None), "확인은 한 번만 쓰인다")

    def test_a_failed_delete_says_nothing_was_deleted(self):
        controller, provider = self.fill(1)
        store(controller, "list")
        provider.delete_saved = lambda draft_id, progress, cancelled: (_ for _ in ()).throw(drafts.save_failure(AppError("BACKUP_FAILED")))
        controller.delete_dialog(controller.listing.rows[0].draft_id)
        self.assertEqual(store(controller, "delete"), ("started", True))
        self.assertEqual(controller.list_notice, ("error", T["drf_deletefail"]))
        self.assertEqual(len(provider.saved), 1)

    def test_deleting_an_unreadable_draft_asks_with_its_short_number(self):
        controller, provider = self.fill(1)
        provider.list_saved = lambda progress, cancelled: drafts.SavedListing((), ("dd-" + "c" * 20,))
        store(controller, "list")
        dialog = controller.delete_dialog("dd-" + "c" * 20)
        self.assertIn("dd-cccccccc", dialog["body"])
        self.assertNotIn("c" * 20, dialog["body"])

    def test_the_store_jobs_run_one_at_a_time(self):
        controller, provider = made_saving()
        slow = Slow(lambda: CATALOG, saving=True, hold=("save",))
        slow_controller = dv.DraftsController(slow, jobs.JobRunner())
        slow.hold = set()
        slow_controller.open_target(target_of(GENERIC))
        drive(slow_controller)
        slow.hold = {"save"}
        status, job = slow_controller.start_save(on_done=lambda *a: None, on_error=lambda *a: None)
        self.assertTrue(slow.entered.wait(10))
        self.assertEqual(slow_controller.start_list(), ("busy", None))
        self.assertEqual(slow_controller.start_open_saved("dd-" + "0" * 20), ("busy", None))
        slow_controller.delete_asked = "dd-" + "0" * 20
        self.assertEqual(slow_controller.start_delete(), ("busy", None))
        slow.release.set()
        job.join(30)

    def test_the_list_buttons_are_off_while_a_store_job_runs(self):
        controller, provider = self.fill(1)
        store(controller, "list")
        slow = Slow(lambda: CATALOG, saving=True, hold=("open",), saved=provider.saved)
        busy = dv.DraftsController(slow, jobs.JobRunner())
        store(busy, "list")
        row = busy.listing.rows[0]
        status, job = busy.start_open_saved(row.draft_id, on_done=lambda *a: None, on_error=lambda *a: None)
        self.assertTrue(slow.entered.wait(10))
        saved = busy.view()["empty"]["saved"]
        self.assertTrue(saved["busy"])
        self.assertEqual([(row["open"]["enabled"], row["delete"]["enabled"]) for row in saved["rows"]], [(False, False)])
        slow.release.set()
        job.join(30)


class FakeStoreTest(unittest.TestCase):
    def test_the_fake_limit_and_conflict_work_like_the_services(self):
        controller, provider = made_saving()
        save(controller)
        import dataclasses
        from chanceblog_desktop.content import saved_draft as sd
        template = next(iter(provider.saved.values()))
        for number in range(sd.MAX_SAVED - 1):
            draft_id = f"dd-{number:020x}"
            provider.saved[draft_id] = dataclasses.replace(template, draft_id=draft_id)
        drive(controller, controller.start_regenerate)
        controller.set_body("다른 본문")
        status, applied = save(controller)
        self.assertEqual(applied[0], "limit")
        self.assertEqual(len(provider.saved), sd.MAX_SAVED)

    def test_the_fake_clock_is_a_counter_not_the_real_clock(self):
        controller, provider = made_saving()
        save(controller)
        controller.set_body(controller.body + "x")
        save(controller)
        stamps = [call for call in (provider.saved[saved_id(provider)].updated_at,)]
        self.assertTrue(stamps[0].startswith(drafts.SAMPLE_DAY))

    def test_a_save_of_the_same_text_changes_nothing(self):
        controller, provider = made_saving()
        save(controller)
        first = dict(provider.saved)
        save(controller)
        self.assertEqual(provider.saved, first)


class TextAndViewTest(unittest.TestCase):
    def test_every_new_text_is_easy_and_free_of_python_text_forbidden_words_and_commands(self):
        new = {key: value for key, value in draft_text.DRAFT_T.items() if key.startswith(("drf_save", "drf_state_", "drf_saved", "drf_open_", "drf_openfail", "drf_delete", "drf_leave3", "drf_close3", "drf_choice"))}
        self.assertGreaterEqual(len(new), 70)
        import re
        for key, value in new.items():
            with self.subTest(key=key):
                self.assertTrue(value.strip())
                self.assertNotRegex(value, r"\bNone\b|\bTrue\b|\bFalse\b|\['|Traceback|Exception|Error")
                self.assertNotRegex(value, r"https?://|\w:[\\/]|\\|`|--[a-z]")
                for word in text.FORBIDDEN:
                    self.assertNotIn(word, value)
                self.assertIsNone(re.search(r"(?i)(?<![A-Za-z0-9_])(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?(?![A-Za-z0-9_])", value), key)

    def test_the_view_models_with_saving_have_no_python_text_enum_names_or_codes(self):
        leaks = r"\['|\bNone\b|\bTrue\b|\bFalse\b|Traceback|\bnaver_[ab]\b|\bgeneric\b|\bDRAFT_[A-Z_]+\b|\bSTORE_[A-Z_]+\b|\bkeyshape\b|\bunsaved\b|\bchanged\b|\bdd-[0-9a-f]{20}\b"
        import re
        views = []
        controller, provider = made_saving()
        views.append(controller.view()["normal"]["save"])
        views.append(controller.view()["normal"]["actions"])
        views.append(controller.view()["normal"]["editor"]["save_text"])
        save(controller)
        views.append(controller.view()["normal"]["save"])
        controller.set_body(controller.body + "x")
        views.append(controller.view()["normal"]["save"])
        views.append(controller.leave_dialog())
        views.append(controller.leave_dialog("close"))
        empty, other = saving()
        views.append(empty.view()["empty"])
        fresh = dv.DraftsController(provider, jobs.JobRunner())
        views.append(fresh.view()["empty"])
        store(fresh, "list")
        views.append(fresh.view()["empty"])
        fresh.delete_dialog(fresh.listing.rows[0].draft_id)
        views.append(fresh.delete_dialog(fresh.listing.rows[0].draft_id))
        for view in views:
            for value in all_strings(view, KEYS_NOT_SHOWN + ("first", "after")):
                self.assertIsNone(re.search(leaks, value), value[:60])
                for word in text.FORBIDDEN:
                    self.assertNotIn(word, value)


class SourceRulesTest(unittest.TestCase):
    CORE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core"

    def test_only_the_store_methods_of_the_controller_call_the_provider_store_functions_and_each_only_once(self):
        import ast
        tree = ast.parse((self.CORE / "drafts_view.py").read_text(encoding="utf-8"))
        callers = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Attribute) and node.attr in ("save_draft", "list_saved", "open_saved", "delete_saved"):
                    callers.setdefault(node.attr, set()).add(function.name)
        self.assertEqual(callers, {"save_draft": {"start_save"}, "list_saved": {"start_list"}, "open_saved": {"start_open_saved"}, "delete_saved": {"start_delete"}})

    def test_the_core_files_import_no_service_or_gui_module_at_the_top(self):
        import ast
        for name in ("drafts.py", "drafts_view.py"):
            tree = ast.parse((self.CORE / name).read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.ImportFrom):
                    module = ("." * node.level) + (node.module or "")
                    self.assertFalse(module.lstrip(".").split(".")[0] in ("service", "publish", "render", "assist", "topicdb", "content", "security", "check", "topics") and "profiles" not in module, (name, module))
                    self.assertNotIn("PySide6", module)

    def test_deleting_always_goes_through_the_confirmation_flag(self):
        import ast
        tree = ast.parse((self.CORE / "drafts_view.py").read_text(encoding="utf-8"))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_delete")
        source = ast.unparse(function)
        self.assertLess(source.index("delete_asked"), source.index("delete_saved"))
        self.assertIn("unconfirmed", source)


if __name__ == "__main__":
    unittest.main()
