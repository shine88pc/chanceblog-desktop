"""초안 작성 화면의 **저장한 초안** 실제 공급자(`ui/drafts_adapter.py` → `service/draft_store.py`) 시험 — 진짜 임시 폴더의 엔진 보관함·글 보관함과 진짜 서비스 함수로 확인한다(PySide6 없이 돈다, CI 와 같은 조건).

지키는 것:
  1) 만든 초안을 저장하고 **새 공급자·새 컨트롤러**(재시작처럼)로 목록·열기를 하면 제목·본문이 글자 그대로이고 선택 입력·글 유형·확인 권장·제목 후보·고친 정도 바탕이 되살아난다. 글쓰기 열기 주소도 같은 규칙으로 얻는다.
  2) 키·토큰 모양이 있으면 저장하지 않고 위치만 알린다 — 보관함 파일이 만들어지지도 않는다.
  3) 목록·열기는 읽기뿐이다(데이터 폴더 바이트가 그대로). 지우기는 확인창 뒤에만 부르고 지우기 직전 사본을 남긴다. 저장 실패(읽기 전용 파일)는 다른 기능을 막지 않는다.
  4) 후보가 지워졌거나 프로필 슬롯이 비어 있어도 열리고(`다시 만들기` 만 꺼진다), 가짜 공급자는 진짜와 같은 결과를 낸다(모양 맞춤). 네트워크·키 보관소를 부르지 않는다.
"""
import dataclasses
import os
import stat
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as SS  # noqa: E402
import service_support as ss  # noqa: E402
from test_ui_drafts_save_core import made_request  # noqa: E402
from test_ui_drafts_service import NoNetwork, Setup, target_of  # noqa: E402

from chanceblog_desktop.service import blog_profiles, draft_store  # noqa: E402
from chanceblog_desktop.ui import drafts_adapter  # noqa: E402
from chanceblog_desktop.ui.core import drafts, jobs, text  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402
from chanceblog_desktop.ui.core import drafts_view as dv  # noqa: E402

T = text.T
EMOJI = chr(0x1F600)
NFD = "e" + chr(0x0301)
OPS = {"save": ("start_save", "apply_saved", "apply_save_failed"), "list": ("start_list", "apply_listing", "apply_list_failed"), "open": ("start_open_saved", "apply_opened", "apply_open_failed"),
       "delete": ("start_delete", "apply_deleted", "apply_delete_failed")}


def store(controller, op, *args, **kwargs):
    starter, ok, failed = (getattr(controller, name) for name in OPS[op])
    results = {}
    status, job = starter(*args, on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure), **kwargs)
    if job is not None:
        job.join(30)
    if "ok" in results:
        return status, ok(results["ok"])
    if "failed" in results:
        return status, failed(results["failed"])
    return status, None


def make(controller, engine):
    controller.open_target(target_of(engine))
    results = {}
    status, job = controller.start_make(on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
    job.join(30)
    controller.apply_made(results["ok"]) if "ok" in results else controller.apply_make_failed(results["failed"])
    return controller


def fresh(setup):
    """재시작처럼 — 같은 데이터 폴더를 새 공급자·새 컨트롤러가 읽는다."""
    provider = drafts_adapter.ServiceDraftsProvider(context_factory=lambda data_dir=None: setup.ctx)
    return dv.DraftsController(provider, jobs.JobRunner())


def register_channel(ctx, ref, key="naver_a"):
    snapshot = blog_profiles.read_snapshot(ctx)
    blog_profiles.save_slot(ctx, key, {"display_name": "예시 블로그", "blog_ref": ref}, expected_version=snapshot.version)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.setup = Setup(self, count=2)
        self.engine = self.setup.engines[0]
        self.tree = lambda: ss.tree_snapshot(self.setup.world.tmp)

    def test_the_real_provider_has_saving_and_the_screen_shows_the_save_button(self):
        self.assertTrue(self.setup.provider.saving)
        controller = make(self.setup.controller(), self.engine)
        self.assertEqual([button["key"] for button in controller.view()["normal"]["actions"]["buttons"]][:2], ["save", "title"])

    def test_a_saved_draft_comes_back_to_the_character_after_a_restart(self):
        controller = make(self.setup.controller(), self.engine)
        controller.set_title("  고친 제목 " + EMOJI)
        controller.set_body("고친 본문\r\n둘째 줄 " + NFD + chr(0) + "끝  ")
        controller.set_option("message", "전하고 싶은 말")
        status, applied = store(controller, "save")
        self.assertEqual((status, applied), ("started", ("saved", None)))
        self.assertEqual(controller.save_state(), "saved")
        again = fresh(self.setup)
        self.assertEqual(store(again, "list"), ("started", True))
        saved = again.view()["empty"]["saved"]
        self.assertEqual([row["title"] for row in saved["rows"]], [rules.shown("  고친 제목 " + EMOJI, 80)])
        self.assertEqual(store(again, "open", again.listing.rows[0].draft_id)[1], True)
        self.assertEqual((again.title, again.body), ("  고친 제목 " + EMOJI, "고친 본문\r\n둘째 줄 " + NFD + chr(0) + "끝  "))
        self.assertEqual((again.state, again.save_state(), again.has_unsaved()), ("normal", "saved", False))

    def test_the_options_the_made_draft_the_title_picks_and_the_checks_come_back_too(self):
        controller = self.setup.controller()
        controller.open_target(target_of(self.engine))
        controller.set_option("message", "독자에게 전하고 싶은 한 줄")
        controller.set_option("price_date", "가격은 직접 확인한 것만")
        controller.set_post_type("비교형")
        controller.start_make(on_done=lambda result, _p: controller.apply_made(result))[1].join(30)
        self.assertEqual(controller.state, "normal")
        controller.set_body(controller.body + "\n직접 덧붙인 문장")
        store(controller, "save")
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", again.listing.rows[0].draft_id)
        self.assertEqual((again.fields.get("message"), again.fields.get("price_date"), again.post_type), ("독자에게 전하고 싶은 한 줄", "가격은 직접 확인한 것만", "비교형"))
        self.assertFalse(again.options_pending())
        self.assertEqual((tuple(again.draft_body().titles), tuple(again.draft_body().checks), again.draft_body().domain),
                         (tuple(controller.draft_body().titles), tuple(controller.draft_body().checks), controller.draft_body().domain))
        self.assertEqual(again.draft_body().body_text, controller.draft_body().body_text, "처음 만든 본문이 바탕이라 고친 정도가 그대로 계산된다")
        self.assertTrue(again.body_edited())

    def test_listing_and_opening_change_no_byte_and_create_no_file(self):
        controller = make(self.setup.controller(), self.engine)
        store(controller, "save")
        before = self.tree()
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", again.listing.rows[0].draft_id)
        self.assertEqual(self.tree(), before)

    def test_listing_with_no_store_file_is_an_empty_list_and_makes_no_file(self):
        before = self.tree()
        controller = fresh(self.setup)
        self.assertEqual(store(controller, "list"), ("started", True))
        self.assertEqual((controller.list_state, controller.listing.rows, controller.listing.unreadable), ("ok", (), ()))
        self.assertEqual(self.tree(), before)

    def test_a_key_shape_in_the_body_is_not_saved_and_no_store_file_is_made(self):
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            with self.subTest(kind=kind):
                setup = Setup(self, count=1)
                controller = make(setup.controller(), setup.engines[0])
                controller.set_body("앞글\n" + line)
                before = ss.tree_snapshot(setup.world.tmp)
                status, applied = store(controller, "save")
                self.assertEqual(applied, ("keyshape", None))
                failure = controller.take_save_problem()
                self.assertIn("본문에서 1건", failure.advice)
                self.assertIn("2번째 줄", failure.advice)
                self.assertFalse(SS.leaked(failure.advice + failure.user_message + repr(controller.save_failure_dialog(failure)), token))
                self.assertEqual(ss.tree_snapshot(setup.world.tmp), before, "보관함 파일이 만들어지지도 않았다")
                self.assertEqual(controller.save_state(), "unsaved")

    def test_a_second_save_updates_and_the_list_has_one_row_and_the_revision_is_two(self):
        controller = make(self.setup.controller(), self.engine)
        store(controller, "save")
        controller.set_body(controller.body + "\n둘째 저장")
        self.assertEqual(store(controller, "save")[1], ("saved", None))
        again = fresh(self.setup)
        store(again, "list")
        self.assertEqual([(row.revision, row.title) for row in again.listing.rows], [(2, controller.title)])

    def test_a_stale_window_cannot_overwrite_a_newer_save_and_keeps_its_text(self):
        first = make(self.setup.controller(), self.engine)
        store(first, "save")
        second = fresh(self.setup)
        store(second, "list")
        store(second, "open", second.listing.rows[0].draft_id)
        second.set_body("다른 창에서 고친 글")
        store(second, "save")
        first.set_body(first.body + " 낡은 화면에서 고침")
        status, applied = store(first, "save")
        self.assertEqual(applied, ("conflict", None))
        self.assertEqual(first.notice, ("error", T["drf_savefail_conflict"]))
        self.assertTrue(first.body.endswith("낡은 화면에서 고침"))
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", again.listing.rows[0].draft_id)
        self.assertEqual(again.body, "다른 창에서 고친 글")

    def test_delete_goes_through_the_dialog_and_leaves_the_before_delete_copy(self):
        controller = make(self.setup.controller(), self.engine)
        store(controller, "save")
        listing = fresh(self.setup)
        store(listing, "list")
        row = listing.listing.rows[0]
        self.assertEqual(listing.start_delete(), ("unconfirmed", None))
        self.assertEqual(len(draft_store.list_drafts(self.setup.ctx).entries), 1)
        self.assertIsNotNone(listing.delete_dialog(row.draft_id))
        self.assertEqual(store(listing, "delete")[1], True)
        self.assertEqual(listing.list_notice, ("ok", T["drf_deleted_notice"]))
        self.assertEqual(draft_store.list_drafts(self.setup.ctx).entries, ())
        copies = list((self.setup.ctx.workspace.backups_dir / "before-delete").glob("chanceblog-*.db"))
        self.assertEqual(len(copies), 1)

    def test_a_read_only_store_file_fails_the_save_with_one_notice_and_copy_and_edit_still_work(self):
        controller = make(self.setup.controller(), self.engine)
        store(controller, "save")
        path = self.setup.ctx.workspace.store_path
        os.chmod(path, stat.S_IREAD)
        self.addCleanup(os.chmod, path, stat.S_IREAD | stat.S_IWRITE)
        if os.access(path, os.W_OK):
            self.skipTest("이 계정은 읽기 전용 표시를 무시한다(관리자 권한)")
        controller.set_body(controller.body + " 더")
        status, applied = store(controller, "save")
        self.assertEqual(applied[0], "io")
        self.assertEqual(controller.notice, ("error", T["drf_savefail_io"]))
        self.assertEqual(controller.copy_decision("tags")[0], "copy")
        self.assertTrue(controller.set_title("고침"))
        self.assertEqual(controller.save_state(), "changed")
        shown = repr(controller.view()["error"]) + repr(controller.notice)
        self.assertNotIn(str(self.setup.ctx.workspace.root), shown)

    def test_a_damaged_store_file_fails_every_store_step_with_an_easy_sentence_and_the_draft_screen_works(self):
        controller = make(self.setup.controller(), self.engine)
        self.setup.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        damaged = b"not a database " * 100
        self.setup.ctx.workspace.store_path.write_bytes(damaged)
        self.assertEqual(store(controller, "save")[1], ("corrupt", None))
        self.assertEqual(controller.notice, ("error", T["drf_savefail_corrupt"]))
        listing = fresh(self.setup)
        self.assertEqual(store(listing, "list"), ("started", True))
        self.assertEqual(listing.view()["empty"]["saved"]["state"], "error")
        self.assertEqual(self.setup.ctx.workspace.store_path.read_bytes(), damaged)

    def test_the_candidate_deleted_after_the_save_still_opens_and_regenerate_is_off(self):
        controller = make(self.setup.controller(), self.engine)
        store(controller, "save")
        self.setup.world.paths.database.unlink()
        again = fresh(self.setup)
        store(again, "list")
        self.assertEqual(store(again, "open", again.listing.rows[0].draft_id)[1], True)
        self.assertEqual(again.notice, ("info", T["drf_open_nocandidate"]))
        self.assertEqual(again.start_make(), ("unavailable", None))
        self.assertEqual(again.body, controller.body)

    def test_the_write_address_comes_from_the_channel_profile_when_the_old_profile_has_none(self):
        register_channel(self.setup.ctx, "myblogid")
        controller = make(self.setup.controller(), self.engine)
        self.assertEqual(controller.open_info(), ("https://blog.naver.com/myblogid?Redirect=Write", ""))
        store(controller, "save")
        again = fresh(self.setup)
        store(again, "list")
        store(again, "open", again.listing.rows[0].draft_id)
        self.assertEqual(again.open_info(), ("https://blog.naver.com/myblogid?Redirect=Write", ""))
        open_button = next(button for button in again.view()["normal"]["actions"]["buttons"] if button["key"] == "open")
        self.assertEqual((open_button["enabled"], open_button["url"]), (True, "https://blog.naver.com/myblogid?Redirect=Write"))

    def test_the_off_button_says_the_true_reason_for_no_address_and_for_an_unusable_one(self):
        controller = make(self.setup.controller(), self.engine)
        self.assertEqual(controller.open_info(), ("", T["drf_open_why_profile"]))
        register_channel(self.setup.ctx, "https://example.invalid/myid")
        controller = make(self.setup.controller(), self.engine)
        self.assertEqual(controller.open_info(), ("", T["drf_open_why_unusable"]))
        self.assertIn("블로그 ID 또는 주소", T["drf_open_why_profile"])

    def test_the_old_profile_address_behaves_as_before(self):
        ss.naver_profiles(self.setup.ctx)
        register_channel(self.setup.ctx, "channelid")
        controller = make(self.setup.controller(), self.engine)
        self.assertEqual(controller.open_info(), ("https://blog.naver.com/exampleaaa?Redirect=Write", ""))

    def test_no_network_and_no_key_store_are_touched_by_any_store_step(self):
        with NoNetwork():
            controller = make(self.setup.controller(), self.engine)
            store(controller, "save")
            again = fresh(self.setup)
            store(again, "list")
            store(again, "open", again.listing.rows[0].draft_id)
            again.delete_dialog(again.listing.rows[0].draft_id)
            store(again, "delete")


class FakeParityTest(unittest.TestCase):
    """가짜 공급자(메모리)는 진짜 서비스와 같은 모양으로 일한다 — 같은 요청에 같은 결과."""

    def pair(self):
        setup = Setup(self, count=1)
        engine = setup.engines[0]
        real = make(setup.controller(), engine)
        fake_provider = drafts.FakeDraftsProvider(lambda: [engine], saving=True)
        fake = dv.DraftsController(fake_provider, jobs.JobRunner())
        make(fake, engine)
        return setup, real, fake, fake_provider

    def test_the_same_edit_saves_and_opens_the_same_text_in_both(self):
        setup, real, fake, _ = self.pair()
        for controller in (real, fake):
            controller.set_title("같은 제목 " + EMOJI)
            controller.set_body("같은 본문\r\n" + NFD)
            self.assertEqual(store(controller, "save")[1], ("saved", None))
        results = []
        for controller in (real, fake):
            again = dv.DraftsController(controller.provider if controller is fake else drafts_adapter.ServiceDraftsProvider(context_factory=lambda data_dir=None: setup.ctx), jobs.JobRunner())
            store(again, "list")
            store(again, "open", again.listing.rows[0].draft_id)
            results.append((again.title, again.body, again.blog, again.save_state(), again.has_unsaved(), again.draft_body().selected_title))
        self.assertEqual(results[0][:5], results[1][:5])

    def test_the_same_key_shape_is_refused_in_both_with_the_same_advice(self):
        setup, real, fake, _ = self.pair()
        for kind in SS.KINDS:
            line = SS.sample(kind)[1]
            advice = []
            for controller in (real, fake):
                controller.set_body("글\n" + line)
                applied = store(controller, "save")[1]
                self.assertEqual(applied, ("keyshape", None), kind)
                advice.append(controller.take_save_problem().advice)
            self.assertEqual(advice[0], advice[1], kind)

    def test_the_same_key_shape_in_the_made_draft_is_refused_in_both_with_the_same_advice_and_nothing_is_stored(self):
        """만든 초안(화면에서 못 고치는 칸)에서만 찾아도 진짜 서비스와 가짜 공급자가 똑같이 저장을 멈추고 같은 안내를 한다(D-368)."""
        setup, real, fake, fake_provider = self.pair()
        real_provider = drafts_adapter.ServiceDraftsProvider(context_factory=lambda data_dir=None: setup.ctx)
        before = ss.tree_snapshot(setup.world.tmp)
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            for field in ("title", "titles", "body", "checks", "replaced"):
                with self.subTest(kind=kind, field=field):
                    advice = []
                    for provider in (real_provider, fake_provider):
                        with self.assertRaises(drafts.DraftFailure) as caught:
                            provider.save_draft(made_request(field, line), lambda *_: None, lambda: False)
                        self.assertEqual(caught.exception.kind, "keyshape")
                        advice.append(caught.exception.advice)
                    self.assertEqual(advice[0], advice[1])
                    self.assertIn("만든 초안", advice[0])
                    self.assertIn("다시 만들기", advice[0])
                    self.assertFalse(SS.leaked(advice[0], token))
        self.assertEqual(ss.tree_snapshot(setup.world.tmp), before, "아무것도 저장하지 않았고 보관함 파일을 만들지도 않았다")
        self.assertEqual(fake_provider.saved, {})

    def test_the_same_conflict_and_the_same_unchanged_save_in_both(self):
        setup, real, fake, fake_provider = self.pair()
        for controller in (real, fake):
            store(controller, "save")
            store(controller, "save")                                   # 바뀐 것이 없다 — 저장 횟수가 오르지 않는다
            self.assertEqual(controller.saved_rev, 1)
        for controller in (real, fake):
            controller.saved_rev = 7                                    # 낡은 화면이 불러온 횟수가 맞지 않는다
            controller.set_body(controller.body + " 더")
            self.assertEqual(store(controller, "save")[1], ("conflict", None))


class SourceRulesTest(unittest.TestCase):
    def test_the_adapter_reaches_the_service_through_four_calls_and_no_file_function(self):
        import ast
        path = ROOT / "src" / "chanceblog_desktop" / "ui" / "drafts_adapter.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertEqual(sorted({call for call in calls if call.startswith("draft_store.")}), ["draft_store.delete_draft", "draft_store.list_drafts", "draft_store.open_saved", "draft_store.save_draft"])
        self.assertEqual([call for call in calls if call.startswith("draft_engine.")], ["draft_engine.make_body_for_engine"])
        for call in calls:
            self.assertFalse(any(word in call for word in ("write_text", "write_bytes", "unlink", "mkdir", "sqlite3", "subprocess", "socket", "urllib")) or call in ("open", "os.open"), call)
        top = [("." * node.level) + (node.module or "") for node in tree.body if isinstance(node, ast.ImportFrom)]
        self.assertFalse([name for name in top if name.startswith(("..service.draft", "..content"))], "서비스·내용 모듈은 쓰는 함수 안에서 늦게 가져온다 — " + repr(top))

    def test_the_provider_sets_saving_and_the_base_class_does_not(self):
        self.assertTrue(drafts_adapter.ServiceDraftsProvider.saving)
        self.assertFalse(drafts.DraftsProvider.saving)


if __name__ == "__main__":
    unittest.main()
