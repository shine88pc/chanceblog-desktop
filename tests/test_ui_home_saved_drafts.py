"""홈의 '작성 중인 초안' 구역과 저장한 초안(`ui/adapters.py`·`ui/core/board_view.py`·`services.py`, 결정 D-363) 시험 — PySide6 없이 돈다(CI 와 같은 조건). 진짜 임시 폴더의 글 보관함·진짜 서비스로 확인한다.

지키는 것:
  1) **머리 개수 = 저장한 초안 수**(옛 글 목록의 초안이 없는 PC 에서) — 줄은 많아야 5개이고 개수는 줄로 다 보이지 않아도 센 전체 수다. 줄은 고친 때가 늦은 순이고 `저장됨` 배지가 붙는다.
  2) 저장한 초안을 앞에 두고 옛 글 목록의 초안 생성됨·검토 필요 글을 뒤에 둔다(개수는 둘의 합). 옛 글 목록을 못 읽어도 저장한 초안이 있으면 그것을 보이고, 없으면 오류를 숨기지 않는다. 저장한 초안을 못 읽으면 옛 글 목록 그대로다.
  3) 읽기뿐이다 — 홈을 읽어도 파일이 하나도 바뀌지 않고, 줄·글에 내부 번호가 나가지 않는다. 개수·연결은 전체 수를 아는 공급자에서만 보이고(가짜 홈은 예전 그대로) `저장한 초안 보기` 는 초안 작성 화면의 목록으로 가는 연결이다.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
from test_ui_c1c_adapters import FakeEngine, World as HomeWorld  # noqa: E402
from test_ui_drafts_core import KEYS_NOT_SHOWN, all_strings  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import draft_store  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import app_state, board_view, services, text  # noqa: E402

T = text.T
NEVER = lambda: False  # noqa: E731


class HomeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.world = HomeWorld(tmp.name)
        self.ctx = self.world.ctx

    def save(self, title):
        self.ctx.clock.advance(minutes=1)
        return draft_store.save_draft(self.ctx, title=title, body=f"본문 {title}", blog="naver_a", post_type="정보형")

    def load(self):
        return self.world.load(engine=FakeEngine())

    def view(self):
        provider = self.world.provider(engine=FakeEngine())
        state = app_state.AppState(provider)
        state.apply_home(provider.load_home(lambda *a: None, NEVER))
        return state.home_view()["board"]["drafts"]

    def test_with_no_saved_and_no_old_drafts_the_count_is_zero_and_the_section_is_the_normal_empty_state(self):
        drafts = self.load().board.drafts
        self.assertEqual((drafts.state, drafts.rows, drafts.total), ("ok", (), 0))
        vm = self.view()
        self.assertEqual((vm["state"], vm["count_text"], vm["rows"]), ("empty", T["board_draft_count"].format(n=0), []))
        self.assertNotIn("link", vm, "저장한 초안이 하나도 없으면 갈 목록이 없다 — 연결은 없다")

    def test_the_count_is_the_number_of_saved_drafts_and_the_rows_are_newest_first_with_the_saved_label(self):
        for title in ("가", "나", "다"):
            self.save(title)
        drafts = self.load().board.drafts
        self.assertEqual([(row.title, row.stage) for row in drafts.rows], [("다", "saved"), ("나", "saved"), ("가", "saved")])
        self.assertEqual(drafts.total, 3)
        vm = self.view()
        self.assertEqual((vm["state"], vm["count"], vm["count_text"]), ("normal", 3, T["board_draft_count"].format(n=3)))
        self.assertEqual([(row["title"], row["stage"], row["stage_label"]) for row in vm["rows"]], [("다", "saved", T["board_stage_saved"]), ("나", "saved", T["board_stage_saved"]), ("가", "saved", T["board_stage_saved"])])
        self.assertEqual(vm["link"], {"text": T["board_draft_link"], "a11y": T["board_draft_link_a11y"]})
        self.assertEqual(T["board_stage_saved"], "저장됨")

    def test_the_count_always_equals_the_saved_draft_count_even_when_the_rows_are_capped_at_five(self):
        for number in range(1, 9):
            self.save(f"초안 {number}")
            expected = len(draft_store.list_drafts(self.ctx).entries)
            vm = self.view()
            self.assertEqual(vm["count"], expected)
            self.assertEqual(vm["count_text"], T["board_draft_count"].format(n=expected))
            self.assertEqual(len(vm["rows"]), min(expected, services.HOME_LIMIT))
        self.assertEqual([row["title"] for row in self.view()["rows"]], [f"초안 {number}" for number in range(8, 3, -1)])

    def test_each_row_has_a_time_and_the_numbers_never_appear_in_any_shown_text(self):
        saved = self.save("제목")
        vm = self.view()
        self.assertTrue(vm["rows"][0]["time"])
        for value in all_strings(vm, KEYS_NOT_SHOWN):
            self.assertNotIn(saved.draft_id, value)
            self.assertNotIn(saved.draft_id[3:], value)
        self.assertIn("저장됨", vm["rows"][0]["a11y"])

    def test_saved_drafts_come_first_and_old_post_drafts_follow_and_the_count_is_the_sum(self):
        old = self.world.draft("옛 글 제목", naver_a="generated")
        self.save("저장 하나")
        self.save("저장 둘")
        drafts = self.load().board.drafts
        self.assertEqual([(row.title, row.stage) for row in drafts.rows], [("저장 둘", "saved"), ("저장 하나", "saved"), ("옛 글 제목", "generated")])
        self.assertEqual((drafts.total, old != ""), (3, True))
        self.assertEqual(self.view()["count"], 3)

    def test_the_rows_are_capped_at_five_with_saved_first_and_the_total_still_counts_everything(self):
        for number in range(4):
            self.world.draft(f"옛 글 {number}", naver_a="review", updated=f"2026-11-0{number + 1}T00:00:00Z")
        for number in range(3):
            self.save(f"저장 {number}")
        drafts = self.load().board.drafts
        self.assertEqual(len(drafts.rows), services.HOME_LIMIT)
        self.assertEqual([row.stage for row in drafts.rows], ["saved", "saved", "saved", "review", "review"])
        self.assertEqual(drafts.total, 7)

    def test_a_failed_old_post_list_still_shows_the_saved_drafts_and_without_any_it_keeps_the_failure(self):
        failure = AppError("DATA_DIR_UNSAFE", {"경로": "x"}, detail="시험")
        with mock.patch.object(adapters.project_service, "list_projects", side_effect=failure):
            drafts = self.load().board.drafts
            self.assertEqual((drafts.state, drafts.rows, drafts.failure.code), ("failed", (), "DATA_DIR_UNSAFE"))
            self.save("저장한 초안")
            drafts = self.load().board.drafts
            self.assertEqual((drafts.state, [row.title for row in drafts.rows], drafts.total), ("ok", ["저장한 초안"], 1))

    def test_when_the_saved_drafts_cannot_be_read_the_old_post_drafts_are_shown_as_before(self):
        self.world.draft("옛 글 제목", naver_a="generated")
        self.save("저장한 초안")
        with mock.patch.object(adapters.draft_store_service, "list_drafts", side_effect=AppError("STORE_CORRUPT", {"파일": "x"})):
            drafts = self.load().board.drafts
        self.assertEqual((drafts.state, [(row.title, row.stage) for row in drafts.rows], drafts.total), ("ok", [("옛 글 제목", "generated")], 1))

    def test_reading_the_home_changes_no_file(self):
        self.save("제목")
        before = ss.tree_snapshot(self.tmp)
        self.load()
        self.view()
        self.assertEqual(ss.tree_snapshot(self.tmp), before)

    def test_a_provider_that_does_not_know_the_total_shows_no_count_and_no_link(self):
        sample = services.sample_board("normal")
        vm = board_view.build_board_view(services.HomeData(board=sample, sample=True), "normal")["drafts"]
        self.assertNotIn("count_text", vm)
        self.assertNotIn("link", vm)
        self.assertIsNone(sample.drafts.total)

    def test_the_count_and_the_link_are_only_for_a_readable_section(self):
        failed = services.BoardData(drafts=services.ListRead("failed", (), 0, services.ServiceFailure("x", code="A"), 3))
        vm = board_view.build_board_view(services.HomeData(board=failed), "normal")["drafts"]
        self.assertNotIn("link", vm)
        self.assertNotIn("count_text", vm)
        before_load = board_view.build_board_view(None, "loading")["drafts"]
        self.assertNotIn("link", before_load)
        for bad in (-1, True, "3", 2.5):
            odd = services.BoardData(drafts=services.ListRead("ok", (), 0, None, bad))
            self.assertNotIn("count_text", board_view.build_board_view(services.HomeData(board=odd), "normal")["drafts"], bad)

    def test_the_new_stage_is_separate_from_the_old_stage_table_and_an_unknown_stage_has_no_label(self):
        self.assertEqual(services.STAGES, ("generated", "review"))
        self.assertEqual(services.SAVED_STAGE, "saved")
        self.assertEqual(board_view.draft_vm(services.DraftRow("d", "t", "saved", ""), 1)["stage_label"], T["board_stage_saved"])
        self.assertEqual(board_view.draft_vm(services.DraftRow("d", "t", "approved", ""), 1)["stage_label"], "")

    def test_the_new_home_texts_are_easy_and_free_of_forbidden_words(self):
        for key in ("board_stage_saved", "board_draft_count", "board_draft_link", "board_draft_link_a11y"):
            self.assertTrue(T[key].strip())
            for word in text.FORBIDDEN:
                self.assertNotIn(word, T[key])
        self.assertIn("저장한 초안", T["board_draft_link"])


if __name__ == "__main__":
    unittest.main()
