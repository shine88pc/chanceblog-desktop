"""글자 읽기 컨트롤러 `ui/core/photo_ocr_view.py`(결정 D-512, 설계서 2-3·2-5·2-7·3-3·3-10, 시험 계획 T-B)의 순수 시험 — 가짜 공급자만 쓴다(프로세스·Qt·시계 없음).

지키는 것:
  1) 상태 전이 — 쉼 -> 기다림 -> 준비 -> 읽는 중 -> 완료·실패·취소, 한 번에 한 장(FIFO), 줄이 있는 사진은 다시 읽기 확인.
  2) 늦은 결과 버림 — 새 초안·떠남·열기(세대)·사진 지우기·다시 찾기·취소·모르는 번호·같은 결과 두 번은 `late` 이고 목록은 안 바뀐다.
  3) 시간·실패 — 준비 150초·사진 90초 초과·취소 3초 규칙·연속 실패 3번이면 끔·한 번이면 끄는 것·큰 사진은 안 센다.
  4) `PhotoBoard` 와의 짝 — 읽는 중·기다리는 사진은 '확인했어요'·'모두 확인했어요' 가 건너뛴다. 컨트롤러가 없으면 지금과 같다.
  5) 줄 — 확인·고침(입구 검사)·빼기와 한 번 되돌리기·합치기·'모두 맞아요' 두 단계(사진은 확정하지 않는다).
  6) 글·경로가 상태·요청·오류 값에 되풀이되지 않는다.
"""
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.content import photo_ocr as po  # noqa: E402
from chanceblog_desktop.ui.core import photo_ocr_view as pov  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402

USER_DIR, FILE_STEM = "UNIQ-USERDIR-q7w2", "UNIQ-FILE-k3x9"
RESIDENT = ("900101", "1234567")


def path_of(number):
    return f"C:\\Users\\{USER_DIR}\\Pictures\\{FILE_STEM}-{number:02d}.jpg"


def make(count=3, provider=None):
    board = pv.PhotoBoard()
    manifest = pm.empty_manifest()
    for number in range(1, count + 1):
        manifest, _id = pm.add_photo(manifest, path_of(number), photo_type="메뉴판")
    board.load(manifest)
    return board, pov.OcrBoard(board, provider)


def read_one(ocr, photo_id="p001", lines=("한우 불고기", "12,000"), now=0.0):
    assert ocr.request_read(photo_id) == "queued"
    job = ocr.begin_next(now)
    ocr.mark_ready(now)
    assert ocr.on_result(job.token, list(lines), now) == "applied"
    return job


def texts(board, photo_id="p001"):
    return [(item.text, item.confirmed) for item in board.photo(photo_id).visible_text]


class FlowTest(unittest.TestCase):
    def test_the_states_go_idle_queued_preparing_reading_done(self):
        board, ocr = make(1)
        self.assertEqual(ocr.state_of("p001"), pov.IDLE)
        self.assertEqual(ocr.request_read("p001"), "queued")
        self.assertEqual(ocr.state_of("p001"), pov.QUEUED)
        job = ocr.begin_next(1.0)
        self.assertEqual(ocr.state_of("p001"), pov.PREPARING)
        ocr.mark_ready(2.0)
        self.assertEqual(ocr.state_of("p001"), pov.READING)
        self.assertEqual(ocr.on_result(job.token, ["한우 불고기", "12,000"], 3.0), "applied")
        self.assertEqual((ocr.state_of("p001"), texts(board)), (pov.DONE, [("한우 불고기", False), ("12,000", False)]))
        self.assertEqual(ocr.summary_of("p001"), (2, 0, 0))

    def test_a_photo_with_no_lines_is_still_done(self):
        board, ocr = make(1)
        read_one(ocr, lines=[])
        self.assertEqual((ocr.state_of("p001"), texts(board), ocr.summary_of("p001")), (pov.DONE, [], (0, 0, 0)))

    def test_a_ready_worker_starts_the_next_photo_directly_in_reading(self):
        board, ocr = make(2)
        read_one(ocr, "p001")
        ocr.request_read("p002")
        ocr.begin_next(5.0)
        self.assertEqual(ocr.state_of("p002"), pov.READING)

    def test_only_one_photo_is_read_at_a_time_in_the_order_pressed(self):
        board, ocr = make(3)
        for photo_id in ("p002", "p001", "p003"):
            self.assertEqual(ocr.request_read(photo_id), "queued")
        self.assertEqual([ocr.queue_ahead(pid) for pid in ("p002", "p001", "p003")], [0, 1, 2])
        job = ocr.begin_next(0.0)
        self.assertEqual(job.photo_id, "p002")
        self.assertIsNone(ocr.begin_next(0.0), "읽는 중에는 다음을 시작하지 않는다")
        self.assertEqual([ocr.queue_ahead(pid) for pid in ("p001", "p003")], [1, 2])
        ocr.on_result(job.token, ["가"], 1.0)
        self.assertEqual(ocr.begin_next(1.0).photo_id, "p001")

    def test_run_pending_hands_the_queue_to_the_provider_in_order_and_records_no_paths(self):
        provider = pov.FakeOcrProvider({"p002": pov.OcrOutcome(error="engine")})
        board, ocr = make(3, provider)
        for photo_id in ("p001", "p002", "p003"):
            ocr.request_read(photo_id)
        self.assertEqual(ocr.run_pending(), [("p001", "applied"), ("p002", "failed"), ("p003", "applied")])
        self.assertEqual([call[1] for call in provider.calls], ["p001", "p002", "p003"])
        self.assertNotIn(FILE_STEM, repr(provider.calls) + repr(ocr.queue) + repr(provider.calls[0]))
        self.assertEqual((ocr.state_of("p002"), ocr.error_of("p002")), (pov.FAILED, "engine"))

    def test_the_request_answers_for_each_kind_of_refusal(self):
        board, ocr = make(1, pov.FakeOcrProvider(is_available=False))
        self.assertEqual(ocr.request_read("p001"), "unavailable")
        board, ocr = make(1)
        self.assertEqual((ocr.request_read("p009"), ocr.request_read("p001", "720"), ocr.request_read("p001", None)), ("refused", "refused", "refused"))
        self.assertEqual(ocr.request_read("p001"), "queued")
        self.assertEqual(ocr.request_read("p001"), "busy")
        self.assertEqual(ocr.state_of("p001"), pov.QUEUED)

    def test_the_big_size_is_remembered_in_the_request(self):
        board, ocr = make(1)
        ocr.request_read("p001", pov.SIZE_BIG)
        self.assertEqual(ocr.begin_next().size, "1600")

    def test_reading_again_asks_once_and_the_new_reading_replaces_everything(self):
        board, ocr = make(1)
        read_one(ocr)
        ocr.confirm_line("p001", 0)
        self.assertEqual(ocr.request_read("p001"), "ask_replace")
        self.assertEqual(ocr.state_of("p001"), pov.DONE, "확인을 거치기 전에는 아무것도 안 바뀐다")
        self.assertEqual(ocr.confirm_reread("p002"), "refused")
        self.assertEqual(ocr.confirm_reread("p001"), "queued")
        ocr.run_pending(5.0)
        self.assertEqual(texts(board), [("가짜 줄", False)])
        self.assertEqual(ocr.confirm_reread("p001"), "refused", "한 번 거친 확인은 다시 쓸 수 없다")

    def test_cancelling_the_reread_question_clears_it(self):
        board, ocr = make(1)
        read_one(ocr)
        ocr.request_read("p001")
        ocr.cancel_reread()
        self.assertEqual(ocr.confirm_reread("p001"), "refused")

    def test_a_photo_read_earlier_shows_as_done_even_without_a_stored_state(self):
        board, ocr = make(1)
        read_one(ocr)
        ocr.states.clear()
        self.assertEqual(ocr.state_of("p001"), pov.DONE)
        self.assertEqual(make(1)[1].state_of("p001"), pov.IDLE)


class CancelAndTimeTest(unittest.TestCase):
    def test_a_queued_photo_is_removed_at_once(self):
        board, ocr = make(2)
        ocr.request_read("p001")
        ocr.request_read("p002")
        ocr.begin_next(0.0)
        self.assertEqual(ocr.cancel("p002"), "cancelled")
        self.assertEqual((ocr.state_of("p002"), ocr.queue), (pov.CANCELLED, []))

    def test_cancelling_the_reading_photo_discards_its_late_result(self):
        board, ocr = make(1)
        ocr.request_read("p001")
        job = ocr.begin_next(0.0)
        ocr.mark_ready(0.5)
        self.assertEqual(ocr.cancel("p001", 1.0), "cancelling")
        self.assertEqual((ocr.state_of("p001"), ocr.take_cancels(), ocr.take_cancels()), (pov.CANCELLED, [job.token], []))
        self.assertEqual(ocr.on_result(job.token, ["늦은 글"], 1.5), "late")
        self.assertEqual((texts(board), ocr.state_of("p001")), ([], pov.CANCELLED))
        self.assertIsNone(ocr.active, "작업자가 끝냈으니 다음 요청을 받을 수 있다")

    def test_nothing_to_cancel_is_refused(self):
        board, ocr = make(1)
        self.assertEqual(ocr.cancel("p001"), "refused")
        self.assertEqual(ocr.cancel("p009"), "refused")

    def test_a_worker_that_does_not_finish_within_three_seconds_is_killed(self):
        board, ocr = make(2)
        ocr.request_read("p001")
        ocr.request_read("p002")
        job = ocr.begin_next(0.0)
        ocr.mark_ready(0.0)
        ocr.cancel("p001", 10.0)
        self.assertIsNone(ocr.expire(13.0), "정확히 3초는 아직이다")
        self.assertEqual(ocr.expire(13.01), ("kill", job.token))
        self.assertEqual((ocr.worker_ready, ocr.active), (False, None))
        self.assertEqual(ocr.begin_next(14.0).photo_id, "p002")
        self.assertEqual(ocr.state_of("p002"), pov.PREPARING, "죽였으니 다시 준비부터")

    def test_a_cancel_without_a_time_starts_counting_at_the_first_check(self):
        board, ocr = make(1)
        ocr.request_read("p001")
        job = ocr.begin_next(0.0)
        board.clear()
        self.assertIsNone(ocr.expire(100.0))
        self.assertIsNone(ocr.expire(102.9))
        self.assertEqual(ocr.expire(103.1), ("kill", job.token))

    def test_the_prepare_time_out_is_one_hundred_fifty_seconds(self):
        board, ocr = make(1)
        ocr.request_read("p001")
        job = ocr.begin_next(10.0)
        self.assertIsNone(ocr.expire(160.0))
        self.assertEqual(ocr.expire(160.1), ("timeout", job.token))
        self.assertEqual((ocr.state_of("p001"), ocr.error_of("p001"), ocr.failures, ocr.worker_ready), (pov.FAILED, "timeout", 1, False))

    def test_the_read_time_out_is_ninety_seconds_after_the_worker_was_ready(self):
        board, ocr = make(1)
        ocr.request_read("p001")
        job = ocr.begin_next(0.0)
        ocr.mark_ready(20.0)
        self.assertIsNone(ocr.expire(110.0))
        self.assertEqual(ocr.expire(110.1), ("timeout", job.token))
        self.assertEqual(ocr.on_result(job.token, ["늦은 글"], 111.0), "late")
        self.assertEqual(texts(board), [])

    def test_the_numbers_are_literal(self):
        self.assertEqual((pov.PREPARE_TIMEOUT_S, pov.READ_TIMEOUT_S, pov.CANCEL_WAIT_S, pov.IDLE_EXIT_S, pov.SLOW_HINT_S, pov.FAILURE_LIMIT), (150, 90, 3, 300, 15, 3))
        self.assertEqual(pov.SIZES, ("960", "1600"))

    def test_the_slow_hint_shows_after_fifteen_seconds_of_reading(self):
        board, ocr = make(1)
        ocr.request_read("p001")
        ocr.begin_next(0.0)
        ocr.mark_ready(0.0)
        self.assertFalse(ocr.slow("p001", 15.0))
        self.assertTrue(ocr.slow("p001", 15.1))
        self.assertFalse(ocr.slow("p002", 99.0))

    def test_the_worker_is_asked_to_leave_after_five_idle_minutes(self):
        board, ocr = make(1)
        read_one(ocr, now=10.0)
        self.assertFalse(ocr.idle_exit_due(309.9))
        self.assertTrue(ocr.idle_exit_due(310.0))
        ocr.worker_stopped()
        self.assertFalse(ocr.idle_exit_due(999.0))
        board2, ocr2 = make(2)
        read_one(ocr2, now=0.0)
        ocr2.request_read("p002")
        self.assertFalse(ocr2.idle_exit_due(999.0), "기다리는 일이 있으면 끝내지 않는다")


class FailureTest(unittest.TestCase):
    def fail_with(self, ocr, photo_id, name):
        ocr.request_read(photo_id)
        job = ocr.begin_next(0.0)
        ocr.mark_ready(0.0)
        return ocr.on_error(job.token, name, 1.0)

    def test_three_failures_in_a_row_turn_it_off_for_this_run(self):
        board, ocr = make(1)
        self.assertEqual([self.fail_with(ocr, "p001", "died") for _ in range(3)], ["failed", "failed", "disabled"])
        self.assertEqual((ocr.disabled_code, ocr.available, ocr.request_read("p001")), ("OCR_UNAVAILABLE", False, "unavailable"))

    def test_a_success_resets_the_count(self):
        board, ocr = make(1)
        self.fail_with(ocr, "p001", "engine")
        self.fail_with(ocr, "p001", "timeout")
        read_one(ocr, lines=[])
        self.assertEqual(ocr.failures, 0)
        self.assertEqual([self.fail_with(ocr, "p001", "died") for _ in range(2)], ["failed", "failed"])
        self.assertTrue(ocr.available)

    def test_a_too_big_photo_is_the_users_problem_and_does_not_count(self):
        board, ocr = make(1)
        for _ in range(5):
            self.assertEqual(self.fail_with(ocr, "p001", "too_big"), "failed")
        self.assertEqual((ocr.failures, ocr.available), (0, True))
        self.assertEqual(pov.code_of(ocr.error_of("p001")), "OCR_TOO_BIG")

    def test_these_turn_it_off_at_once_with_their_own_code(self):
        for name, code in (("net_blocked", "OCR_UNEXPECTED"), ("proto", "OCR_UNEXPECTED"), ("blocked", "OCR_BLOCKED"), ("addon_invalid", "OCR_ADDON_INVALID"), ("unavailable", "OCR_UNAVAILABLE"), ("something_new", "OCR_UNEXPECTED")):
            with self.subTest(name=name):
                board, ocr = make(2)
                ocr.request_read("p001")
                job = ocr.begin_next(0.0)
                ocr.mark_ready(0.0)
                ocr.request_read("p002")
                self.assertEqual(ocr.on_error(job.token, name, 1.0), "disabled")
                self.assertEqual((ocr.disabled_code, ocr.queue, ocr.state_of("p002")), (code, [], pov.IDLE), "기다리던 요청도 비운다")

    def test_every_name_maps_to_a_catalog_code(self):
        from chanceblog_desktop.errors import CATALOG
        for name, code in pov.ERROR_CODE.items():
            self.assertIn(code, CATALOG, name)
        self.assertEqual(pov.code_of("zzz"), "OCR_UNEXPECTED")

    def test_a_reset_does_not_turn_a_disabled_reader_back_on_within_the_run(self):
        board, ocr = make(1)
        self.fail_with(ocr, "p001", "net_blocked")
        board.clear()
        manifest, _id = pm.add_photo(pm.empty_manifest(), path_of(1), photo_type="메뉴판")
        board.load(manifest)
        self.assertEqual((ocr.disabled_code, ocr.available, ocr.request_read("p001")), ("OCR_UNEXPECTED", False, "unavailable"))

    def test_the_apply_failing_is_counted_as_an_engine_failure(self):
        board, ocr = make(1)
        ocr.request_read("p001")
        job = ocr.begin_next(0.0)
        board.manifest = pm.remove_photo(board.manifest, "p001")           # 컨트롤러를 거치지 않고 사진이 사라진 이상한 경우
        self.assertEqual(ocr.on_result(job.token, ["가"], 1.0), "failed")
        self.assertEqual(ocr.error_of("p001"), "engine")


class LateResultTest(unittest.TestCase):
    def reading(self, count=2):
        board, ocr = make(count)
        ocr.request_read("p001")
        job = ocr.begin_next(0.0)
        ocr.mark_ready(0.0)
        return board, ocr, job

    def test_a_new_draft_or_leaving_the_screen_drops_the_result(self):
        board, ocr, job = self.reading()
        before = ocr.generation
        board.clear()
        self.assertEqual((ocr.generation, ocr.state_of("p001"), ocr.queue), (before + 1, pov.IDLE, []))
        self.assertEqual(ocr.take_cancels(), [job.token])
        self.assertEqual(ocr.on_result(job.token, ["늦은 글"], 1.0), "late")
        self.assertEqual(board.manifest.photos, (), "비워진 목록에 아무것도 안 들어간다")

    def test_opening_a_saved_draft_drops_the_result_and_the_queue(self):
        board, ocr, job = self.reading()
        ocr.request_read("p002")
        board.load(pm.empty_manifest())
        self.assertEqual((ocr.queue, ocr.states), ([], {}))
        self.assertEqual(ocr.on_result(job.token, ["늦은 글"], 1.0), "late")

    def test_removing_the_photo_drops_its_result_and_undo_does_not_bring_reading_back(self):
        board, ocr, job = self.reading()
        self.assertEqual(board.remove("p001"), "ok")
        self.assertEqual(ocr.on_result(job.token, ["늦은 글"], 1.0), "late")
        self.assertEqual(board.undo_remove(), "ok")
        self.assertEqual((ocr.state_of("p001"), texts(board)), (pov.IDLE, []), "되돌려도 읽는 중은 되살리지 않고 결과도 없다")

    def test_undoing_a_removal_brings_back_the_lines_as_they_were(self):
        board, ocr = make(1)
        read_one(ocr)
        board.remove("p001")
        board.undo_remove()
        self.assertEqual((texts(board), ocr.state_of("p001")), ([("한우 불고기", False), ("12,000", False)], pov.DONE))

    def test_relinking_to_another_file_drops_the_request_and_the_lines(self):
        board, ocr, job = self.reading()
        board.provider = pv.FakePhotoProvider()
        self.assertEqual(board.relink("p001", path_of(9)), "ok")
        self.assertEqual(ocr.on_result(job.token, ["늦은 글"], 1.0), "late")
        self.assertEqual((texts(board), ocr.state_of("p001")), ([], pov.IDLE))

    def test_closing_the_window_cancels_waiting_and_reading_but_keeps_what_was_read(self):
        board, ocr = make(3)
        read_one(ocr, "p001")
        ocr.request_read("p002")
        job = ocr.begin_next(5.0)
        ocr.request_read("p003")
        board.open()
        board.close()
        self.assertEqual((ocr.state_of("p001"), ocr.state_of("p002"), ocr.state_of("p003")), (pov.DONE, pov.CANCELLED, pov.IDLE))
        self.assertEqual(ocr.take_cancels(), [job.token])
        self.assertEqual(ocr.on_result(job.token, ["늦은 글"], 6.0), "late")
        self.assertEqual(len(texts(board, "p001")), 2)

    def test_an_unknown_wrong_or_repeated_token_is_late_and_changes_nothing(self):
        board, ocr, job = self.reading()
        self.assertEqual(ocr.on_result(job.token + 99, ["가"], 1.0), "late")
        self.assertEqual(ocr.on_error(job.token + 99, "died", 1.0), "late")
        self.assertIs(ocr.active, job, "모르는 번호의 결과는 지금 읽는 요청을 건드리지 않는다")
        self.assertEqual(ocr.on_result(job.token, ["가"], 1.0), "applied")
        self.assertEqual(ocr.on_result(job.token, ["나"], 2.0), "late")
        self.assertEqual(texts(board), [("가", False)])

    def test_a_result_for_an_old_generation_is_dropped_even_with_the_right_token(self):
        board, ocr, job = self.reading()
        job.generation -= 1
        self.assertEqual(ocr.on_result(job.token, ["가"], 1.0), "late")
        self.assertEqual(texts(board), [])

    def test_shutdown_cancels_everything_asks_the_provider_to_stop_and_can_repeat(self):
        provider = pov.FakeOcrProvider()
        board, ocr = make(2, provider)
        ocr.request_read("p001")
        ocr.request_read("p002")
        ocr.begin_next(0.0)
        ocr.shutdown()
        ocr.shutdown()
        self.assertEqual((provider.shut_down, ocr.queue, ocr.worker_ready), (2, [], False))


class BoardPairTest(unittest.TestCase):
    def test_confirming_a_photo_that_is_waiting_or_reading_is_refused(self):
        board, ocr = make(2)
        ocr.request_read("p001")
        self.assertEqual(board.confirm("p001", True), "busy")
        ocr.begin_next(0.0)
        self.assertEqual(board.confirm("p001", True), "busy")
        self.assertFalse(board.photo("p001").confirmed_by_user)
        self.assertEqual(board.confirm("p002", True), "ok")
        self.assertEqual(board.confirm("p001", False), "unchanged", "푸는 것은 막지 않는다")

    def test_confirm_all_skips_the_photos_that_are_waiting_or_reading(self):
        board, ocr = make(3)
        ocr.request_read("p001")
        ocr.request_read("p002")
        ocr.begin_next(0.0)
        self.assertEqual(board.ask_confirm_all(), "ask")
        self.assertEqual(board.confirm_all_asked, 1, "확인 줄에는 읽는 중이 아닌 사진 수만")
        self.assertEqual(board.confirm_all(), "ok")
        self.assertEqual([photo.confirmed_by_user for photo in board.manifest.photos], [False, False, True])

    def test_confirm_all_says_none_when_every_photo_is_busy(self):
        board, ocr = make(1)
        ocr.request_read("p001")
        self.assertEqual(board.ask_confirm_all(), "none")

    def test_when_the_result_comes_the_photo_is_not_confirmed_and_a_question_is_closed(self):
        board, ocr = make(2)
        ocr.request_read("p001")
        job = ocr.begin_next(0.0)
        board.ask_confirm_all()
        ocr.on_result(job.token, ["가"], 1.0)
        self.assertEqual((board.confirm_all_asked, board.photo("p001").confirmed_by_user), (0, False))
        self.assertEqual(board.confirm("p001", True), "ok", "다 읽은 뒤에는 확인할 수 있다")

    def test_without_the_reader_attached_the_board_behaves_as_before(self):
        board = pv.PhotoBoard()
        manifest, _id = pm.add_photo(pm.empty_manifest(), path_of(1), photo_type="메뉴판")
        board.load(manifest)
        self.assertIsNone(board.ocr)
        self.assertFalse(board.is_reading("p001"))
        self.assertEqual((board.confirm("p001", True), board.ask_confirm_all()), ("ok", "none"))
        self.assertEqual(board.remove("p001"), "ok")
        board.clear()
        board.open()
        self.assertEqual(board.close(), "closed")


class LineTest(unittest.TestCase):
    def setUp(self):
        self.board, self.ocr = make(2)
        read_one(self.ocr, lines=("한우 불고기", "12,000", "공기밥"))

    def test_confirming_a_line_releases_the_photo_confirmation(self):
        self.board.manifest = pm.set_confirmed(self.board.manifest, "p001", True)
        self.assertEqual(self.ocr.confirm_line("p001", 0), "ok")
        self.assertEqual((texts(self.board)[0], self.board.photo("p001").confirmed_by_user), (("한우 불고기", True), False))
        self.assertEqual(self.ocr.confirm_line("p001", 0), "unchanged")
        self.assertEqual(self.ocr.confirm_line("p001", 0, False), "ok")

    def test_bad_input_is_refused(self):
        self.assertEqual([self.ocr.confirm_line("p001", 9), self.ocr.confirm_line("p001", 0, "yes"), self.ocr.confirm_line("p009", 0)], ["refused"] * 3)

    def test_editing_a_line_goes_through_the_entry_check(self):
        self.ocr.confirm_line("p001", 0)
        self.assertEqual(self.ocr.edit_line("p001", 0, "  한우   불고기 전골 "), "ok")
        self.assertEqual(texts(self.board)[0], ("한우 불고기 전골", False), "고친 줄은 다시 확인 전")
        tag = "<" + "script" + ">x</" + "script" + ">"
        for bad in ("", "   ", tag, "가" * 201, " ".join(RESIDENT), "{{사진 1}}", None, 5):
            self.assertEqual(self.ocr.edit_line("p001", 0, bad), "invalid", repr(bad)[:20])
            self.assertTrue(self.ocr.line_error("p001", 0))
        self.assertEqual(texts(self.board)[0], ("한우 불고기 전골", False))
        self.assertEqual(self.ocr.edit_line("p001", 0, "한우 불고기 전골"), "unchanged")
        self.assertEqual(self.ocr.line_error("p001", 0), "", "고쳐 쓰면 이유가 사라진다")
        self.assertEqual(self.ocr.edit_line("p001", 7, "글"), "refused")

    def test_the_reason_never_repeats_the_text(self):
        self.ocr.edit_line("p001", 0, " ".join(RESIDENT))
        self.assertNotIn(RESIDENT[1], self.ocr.line_error("p001", 0))

    def test_removing_a_line_can_be_undone_once_if_nothing_else_changed(self):
        self.assertEqual(self.ocr.remove_line("p001", 1), "ok")
        self.assertEqual([text for text, _c in texts(self.board)], ["한우 불고기", "공기밥"])
        self.assertEqual(self.ocr.undo_remove_line(), "ok")
        self.assertEqual([text for text, _c in texts(self.board)], ["한우 불고기", "12,000", "공기밥"])
        self.assertEqual(self.ocr.undo_remove_line(), "refused", "한 번만")

    def test_the_undo_is_gone_after_another_change(self):
        self.ocr.remove_line("p001", 1)
        self.ocr.confirm_line("p001", 0)
        self.assertEqual(self.ocr.undo_remove_line(), "refused")
        self.assertEqual(len(texts(self.board)), 2)

    def test_the_undo_is_refused_if_the_board_changed_behind_the_controllers_back(self):
        self.ocr.remove_line("p001", 1)
        self.board.manifest = pm.update_photo(self.board.manifest, "p001", user_note="새 메모")
        self.assertEqual(self.ocr.undo_remove_line(), "refused")
        self.assertEqual(self.board.photo("p001").user_note, "새 메모", "메모를 되돌리지 않는다")

    def test_removing_a_bad_number_is_refused(self):
        self.assertEqual([self.ocr.remove_line("p001", 9), self.ocr.remove_line("p009", 0)], ["refused", "refused"])
        self.assertEqual(len(texts(self.board)), 3)

    def test_merging_joins_a_line_with_the_one_below(self):
        self.assertEqual(self.ocr.merge_line("p001", 0), "ok")
        self.assertEqual(texts(self.board), [("한우 불고기 12,000", False), ("공기밥", False)])
        self.assertEqual(self.ocr.merge_line("p001", 1), "invalid", "마지막 줄은 아래 줄이 없다")
        self.assertEqual(len(texts(self.board)), 2)

    def test_merging_into_a_personal_number_shape_is_refused_with_a_fixed_reason(self):
        board, ocr = make(1)
        read_one(ocr, lines=RESIDENT)
        self.assertEqual(ocr.merge_line("p001", 0), "invalid")
        self.assertTrue(ocr.line_error("p001", 0))
        self.assertNotIn(RESIDENT[1], ocr.line_error("p001", 0))
        self.assertEqual([text for text, _c in texts(board)], list(RESIDENT))

    def test_all_right_needs_the_question_first_and_never_confirms_the_photo(self):
        self.assertEqual(self.ocr.all_right("p001"), "refused", "1단계를 건너뛰고 부르면 아무것도 안 한다")
        self.assertEqual(self.ocr.confirmed_line_count("p001"), 0)
        self.ocr.confirm_line("p001", 0)
        self.assertEqual(self.ocr.ask_all_right("p001"), "ask")
        self.assertEqual(self.ocr.all_right_asked, ("p001", 2))
        self.assertEqual(self.ocr.all_right("p001"), "ok")
        self.assertEqual((self.ocr.last_all_right, self.ocr.confirmed_line_count("p001"), self.board.photo("p001").confirmed_by_user), (2, 3, False))
        self.assertEqual(self.ocr.ask_all_right("p001"), "none")
        self.assertEqual(self.ocr.all_right("p001"), "refused")

    def test_the_question_is_for_one_photo_and_other_changes_cancel_it(self):
        read_one(self.ocr, "p002", lines=("글",))
        self.ocr.ask_all_right("p001")
        self.assertEqual(self.ocr.all_right("p002"), "refused", "묻지 않은 사진에는 안 된다")
        self.ocr.edit_line("p001", 0, "다른 글")
        self.assertEqual(self.ocr.all_right("p001"), "refused", "그 사이에 고쳤으면 다시 묻는다")
        self.ocr.ask_all_right("p001")
        self.ocr.cancel_all_right()
        self.assertEqual(self.ocr.all_right("p001"), "refused")

    def test_the_lines_of_a_photo_that_is_being_read_again_cannot_be_changed(self):
        self.ocr.request_read("p001")
        self.ocr.confirm_reread("p001")
        for result in (self.ocr.confirm_line("p001", 0), self.ocr.edit_line("p001", 0, "글"), self.ocr.remove_line("p001", 0), self.ocr.merge_line("p001", 0), self.ocr.ask_all_right("p001")):
            self.assertEqual(result, "busy")
        self.assertEqual(len(texts(self.board)), 3)

    def test_a_removed_lines_photo_forgets_the_undo_and_the_questions(self):
        self.ocr.remove_line("p001", 0)
        self.ocr.ask_all_right("p001")
        self.board.remove("p001")
        self.assertEqual((self.ocr.undo_line, self.ocr.all_right_asked), (None, (None, 0)))


class AllRightFreshnessTest(unittest.TestCase):
    """검증 B2-S SP-1 — '읽은 글 모두 맞아요' 질문은 질문을 띄운 때의 줄에 대한 것이다. 다시 읽기로 줄이 바뀐 뒤에도 낡은 질문이 남아 '네' 가 보지 못한 줄까지 확인하면 안 된다
    (확인한 줄만 초안에 간다는 절대 조건). 질문은 새 결과가 오거나 다시 읽기가 줄을 설 때 닫히고, 그래도 살아남은 낡은 질문에 눌린 '네' 는 줄이 달라졌다는 것을 보고 거절한다."""

    OLD = ("한우 불고기", "12,000", "공기밥")
    NEW = ("새 줄 하나", "새 줄 둘", "새 줄 셋", "새 줄 넷", "새 줄 다섯")

    def asked(self):
        board, ocr = make(1)
        read_one(ocr, lines=self.OLD)
        self.assertEqual(ocr.ask_all_right("p001"), "ask")
        self.assertEqual(ocr.all_right_asked, ("p001", 3))
        return board, ocr

    def test_queueing_the_read_again_closes_the_question_at_once(self):
        board, ocr = self.asked()
        self.assertEqual(ocr.request_read("p001"), "ask_replace")
        self.assertEqual(ocr.all_right_asked, ("p001", 3), "다시 읽을지 묻는 동안에는 줄이 그대로라 질문도 그대로")
        self.assertEqual(ocr.confirm_reread("p001"), "queued")
        self.assertEqual(ocr.all_right_asked, (None, 0), "다시 읽기가 줄을 서면 줄이 곧 바뀌므로 질문을 닫는다")

    def test_a_new_result_closes_the_question_and_a_late_yes_confirms_nothing(self):
        board, ocr = self.asked()
        ocr.request_read("p001")
        ocr.confirm_reread("p001")
        job = ocr.begin_next(5.0)
        ocr.mark_ready(5.0)
        self.assertEqual(ocr.on_result(job.token, list(self.NEW), 6.0), "applied")
        self.assertEqual(ocr.all_right_asked, (None, 0), "새 결과가 오면 낡은 질문은 닫힌다")
        self.assertEqual(ocr.all_right("p001"), "refused", "3줄을 물었는데 새로 읽은 5줄을 확인해 버리면 안 된다")
        self.assertEqual(texts(board), [(text, False) for text in self.NEW], "거절된 '네' 는 새 줄을 하나도 확인하지 않는다")
        self.assertEqual(ocr.ask_all_right("p001"), "ask")
        self.assertEqual(ocr.all_right_asked, ("p001", 5), "다시 물으면 새 줄 수로 묻는다")
        self.assertEqual(ocr.all_right("p001"), "ok")
        self.assertEqual(texts(board), [(text, True) for text in self.NEW])

    def test_a_result_closes_a_question_that_survived_the_queueing(self):
        """방어 한 겹 — 줄 서기가 질문을 닫지만, 어떤 길로든 질문이 줄 선 뒤에 떠 있게 되어도(다른 호출자가 그 사이에 세움) 새 결과가 오는 때 한 번 더 닫는다."""
        board, ocr = self.asked()
        ocr.request_read("p001")
        ocr.confirm_reread("p001")
        job = ocr.begin_next(5.0)
        ocr.mark_ready(5.0)
        ocr.all_right_asked, ocr._all_right_lines = ("p001", 3), ocr.lines("p001")        # 줄 선 뒤에 질문이 떠 있는 상태를 일부러 만든다
        self.assertEqual(ocr.on_result(job.token, list(self.NEW), 6.0), "applied")
        self.assertEqual(ocr.all_right_asked, (None, 0), "새 결과가 오는 때 한 번 더 닫는다")
        self.assertEqual(ocr.all_right("p001"), "refused")
        self.assertEqual(texts(board), [(text, False) for text in self.NEW])

    def test_a_read_of_another_photo_leaves_the_question_alone(self):
        board, ocr = make(2)
        read_one(ocr, "p001", lines=self.OLD)
        ocr.ask_all_right("p001")
        read_one(ocr, "p002", lines=("다른 사진 줄",))
        self.assertEqual(ocr.all_right_asked, ("p001", 3), "다른 사진의 줄 서기·결과는 이 사진의 줄을 바꾸지 않으므로 질문도 그대로")
        self.assertEqual(ocr.all_right("p001"), "ok")
        self.assertEqual(texts(board), [(text, True) for text in self.OLD])
        self.assertEqual(texts(board, "p002"), [("다른 사진 줄", False)], "다른 사진의 줄은 건드리지 않는다")

    def test_a_yes_for_lines_that_are_not_the_asked_ones_is_refused_even_if_the_question_survived(self):
        for name, change in (("같은 줄 수·다른 글", lambda board: pm.edit_item(board.manifest, "p001", pm.TEXTS, 0, "바뀐 줄")),
                             ("확인한 줄이 하나 늘어남", lambda board: pm.confirm_item(board.manifest, "p001", pm.TEXTS, 1, True)),
                             ("줄 하나가 빠짐", lambda board: pm.remove_item(board.manifest, "p001", pm.TEXTS, 2))):
            with self.subTest(name):
                board, ocr = self.asked()
                board.manifest = change(board)                       # 컨트롤러가 모르는 길로 줄이 바뀐 경우(질문은 아직 떠 있다)
                self.assertEqual(ocr.all_right_asked[0], "p001")
                before = texts(board)
                self.assertEqual(ocr.all_right("p001"), "refused")
                self.assertEqual(texts(board), before, "거절된 '네' 는 줄을 바꾸지 않는다")
                self.assertEqual(ocr.all_right_asked, (None, 0), "낡은 질문은 거절하면서 닫는다")
                self.assertEqual(ocr.all_right("p001"), "refused", "닫힌 질문에는 다시 눌러도 안 된다")
                self.assertEqual(ocr.ask_all_right("p001"), "ask")
                self.assertEqual(ocr.all_right("p001"), "ok", "다시 물어 눌렀을 때는 된다")

    def test_the_yes_still_works_when_nothing_changed_since_the_question(self):
        board, ocr = self.asked()
        ocr.confirm_line("p001", 0)                                  # 줄 고침은 질문을 닫는다
        self.assertEqual(ocr.all_right("p001"), "refused")
        self.assertEqual(ocr.ask_all_right("p001"), "ask")
        self.assertEqual((ocr.all_right_asked, ocr.all_right("p001")), (("p001", 2), "ok"))
        self.assertEqual(texts(board), [(text, True) for text in self.OLD])

    def test_in_random_sequences_a_floating_question_always_matches_the_lines_it_was_asked_about(self):
        """무작위 동작(읽기·다시 읽기·질문·네·줄 고침 다섯·지우기 되돌리기)에서 질문이 떠 있는 동안 줄은 질문을 띄운 때와 같고, '네' 는 그 줄에만 닿으며, 거절된 '네' 는 아무것도 바꾸지 않는다 — 씨앗이 정해져 있어 매번 같다."""
        for seed in range(40):
            rng = random.Random(seed)
            provider = pov.FakeOcrProvider()
            board, ocr = make(2, provider)
            asked = None
            for step in range(150):
                photo_id = rng.choice(("p001", "p002"))
                action = rng.choice(("read", "read", "read", "ask", "ask", "yes", "yes", "confirm", "edit", "remove", "merge", "undo_line", "drop_question", "board_remove", "board_undo"))
                label = f"씨앗 {seed} 단계 {step} {action} {photo_id}"
                if action == "read":
                    provider.default = pov.OcrOutcome(tuple(f"줄 {step} {number}" for number in range(rng.randrange(0, 6))))
                    answer = ocr.request_read(photo_id)
                    if answer == "ask_replace" and rng.random() < 0.8:
                        ocr.confirm_reread(photo_id)
                    ocr.run_pending(float(step))
                elif action == "ask":
                    if ocr.ask_all_right(photo_id) == "ask":
                        asked = (photo_id, ocr.lines(photo_id))
                elif action == "yes":
                    before, floating = ocr.lines(photo_id), ocr.all_right_asked
                    result = ocr.all_right(photo_id)
                    after = ocr.lines(photo_id)
                    if result == "ok":
                        self.assertEqual((floating[0], before), asked, f"{label}: '네' 는 질문을 띄운 때의 줄에만 닿아야 한다")
                        self.assertEqual(after, tuple((text, True) for text, _confirmed in before), label)
                    else:
                        self.assertEqual(after, before, f"{label}: 거절된 '네' 는 줄을 바꾸지 않는다")
                elif action == "confirm":
                    ocr.confirm_line(photo_id, rng.randrange(0, 4), rng.random() < 0.7)
                elif action == "edit":
                    ocr.edit_line(photo_id, rng.randrange(0, 4), f"고친 줄 {step}")
                elif action == "remove":
                    ocr.remove_line(photo_id, rng.randrange(0, 4))
                elif action == "merge":
                    ocr.merge_line(photo_id, rng.randrange(0, 4))
                elif action == "undo_line":
                    ocr.undo_remove_line()
                elif action == "drop_question":
                    ocr.cancel_all_right()
                elif action == "board_remove":
                    board.remove(photo_id)
                else:
                    board.undo_remove()
                question = ocr.all_right_asked
                if question[0] is not None:
                    self.assertIsNotNone(asked, label)
                    self.assertEqual(question[0], asked[0], label)
                    self.assertEqual(ocr.lines(question[0]), asked[1], f"{label}: 떠 있는 질문의 줄이 질문을 띄운 때와 다르다")
                    self.assertEqual(question[1], sum(1 for _text, confirmed in asked[1] if not confirmed), label)


class UndoGuardTest(unittest.TestCase):
    """검증 Q QP-4 — '사진 지우기 되돌리기'(board.undo)는 목록 전체를 지우기 전 판으로 되돌리므로, 그 사이에 다른 고침(읽은 결과·줄 고침)이 생기면 쓸 수 없어야 한다. 규칙은 코드에 있었으나 시험이 없어,
    되돌리기 단추와 줄 고치기를 한 화면에 올릴 때 조용히 깨지면 확인해 둔 줄이 클릭 한 번에 사라진다(메모리 안, 저장 전)."""

    def test_a_result_that_arrives_after_a_photo_was_removed_empties_the_undo_and_the_confirm_all_question(self):
        board, ocr = make(3)
        self.assertEqual(ocr.request_read("p001"), "queued")
        job = ocr.begin_next(0.0)
        ocr.mark_ready(0.5)
        self.assertEqual(board.remove("p003"), "ok")
        self.assertIsNotNone(board.undo, "지운 직후에는 되돌릴 수 있다")
        self.assertEqual((board.ask_confirm_all(), board.confirm_all_asked), ("ask", 1), "읽는 중인 첫 사진은 빼고 둘째 사진 하나")
        self.assertEqual(ocr.on_result(job.token, ["한우 불고기", "12,000"], 1.0), "applied")
        self.assertIsNone(board.undo, "읽은 결과가 오면 지우기 되돌리기는 사라진다 — 되돌리면 목록 전체가 옛 판이 되어 방금 읽은 글이 없어진다")
        self.assertEqual(board.confirm_all_asked, 0, "'모두 확인했어요' 확인 줄도 사라진다")
        self.assertEqual(board.undo_remove(), "refused")
        self.assertEqual(texts(board), [("한우 불고기", False), ("12,000", False)], "거절된 되돌리기가 읽은 글을 건드리지 않는다")
        self.assertIsNone(board.photo("p003"))

    def test_every_line_edit_empties_the_undo_and_the_confirm_all_question_and_nothing_is_restored(self):
        lines = ("한우 불고기", "12,000", "국수")
        cases = (
            ("confirm", lambda ocr: ocr.confirm_line("p001", 0), [("한우 불고기", True), ("12,000", False), ("국수", False)]),
            ("edit", lambda ocr: ocr.edit_line("p001", 0, "한우 갈비"), [("한우 갈비", False), ("12,000", False), ("국수", False)]),
            ("remove", lambda ocr: ocr.remove_line("p001", 0), [("12,000", False), ("국수", False)]),
            ("merge", lambda ocr: ocr.merge_line("p001", 0), [("한우 불고기 12,000", False), ("국수", False)]),
            ("all_right", lambda ocr: (ocr.ask_all_right("p001"), ocr.all_right("p001"))[1], [("한우 불고기", True), ("12,000", True), ("국수", True)]),
        )
        for name, act, expected in cases:
            with self.subTest(name):
                board, ocr = make(3)
                read_one(ocr, lines=lines)
                self.assertEqual(board.remove("p003"), "ok")
                self.assertEqual(board.ask_confirm_all(), "ask")
                self.assertIsNotNone(board.undo)
                self.assertTrue(board.confirm_all_asked)
                self.assertEqual(act(ocr), "ok")
                self.assertIsNone(board.undo, "줄을 고치면 사진 지우기 되돌리기는 사라진다")
                self.assertEqual(board.confirm_all_asked, 0, "'모두 확인했어요' 확인 줄도 사라진다")
                self.assertEqual(board.undo_remove(), "refused")
                self.assertEqual(texts(board), expected, "되돌리기가 거절돼도 줄은 방금 고친 그대로 — 고친 것이 사라지면 자료 손실이다")


class SideBranchTest(unittest.TestCase):
    """검증 Q QP-8 — 컨트롤러 곁가지 셋: 시간 초과·종료 뒤에는 작업자가 없다고 보는 것, 크게 다시 읽기 크기, 끈 동안 시작 안 함."""

    def test_after_any_time_out_or_kill_the_worker_counts_as_gone_and_the_next_request_starts_in_preparing(self):
        for name in ("prepare_timeout", "read_timeout", "cancel_kill"):
            with self.subTest(name):
                board, ocr = make(2)
                ocr.request_read("p001")
                job = ocr.begin_next(0.0)
                if name == "prepare_timeout":
                    ocr.worker_ready = True                              # 낡은 표지가 남은 도달 못 할 상태를 일부러 만든다 — 시간 초과가 이것도 거둔다(방어 한 줄)
                    self.assertEqual(ocr.expire(pov.PREPARE_TIMEOUT_S + 1), ("timeout", job.token))
                elif name == "read_timeout":
                    ocr.mark_ready(0.0)
                    self.assertEqual(ocr.expire(pov.READ_TIMEOUT_S + 1), ("timeout", job.token))
                else:
                    ocr.mark_ready(0.0)
                    self.assertEqual(ocr.cancel("p001", 1.0), "cancelling")
                    self.assertEqual(ocr.expire(1.0 + pov.CANCEL_WAIT_S + 1), ("kill", job.token))
                self.assertFalse(ocr.worker_ready, "프로세스 트리를 끈 뒤에는 준비된 작업자가 없다")
                self.assertEqual(ocr.request_read("p002"), "queued")
                ocr.begin_next(500.0)
                self.assertEqual(ocr.state_of("p002"), pov.PREPARING, "다음 요청은 읽는 중(90초)이 아니라 준비 중(150초) 시계로 시작한다")

    def test_reading_again_at_the_big_size_keeps_the_size_through_the_confirmation(self):
        board, ocr = make(1)
        read_one(ocr)
        self.assertEqual(ocr.request_read("p001", pov.SIZE_BIG), "ask_replace")
        self.assertEqual(ocr.confirm_reread("p001"), "queued")
        self.assertEqual(ocr.begin_next(5.0).size, pov.SIZE_BIG, "'더 크게 다시 읽기' 가 확인을 거쳐도 1600 이다")
        board, ocr = make(1)
        read_one(ocr)
        ocr.request_read("p001")
        ocr.confirm_reread("p001")
        self.assertEqual(ocr.begin_next(5.0).size, pov.SIZE_NORMAL)

    def test_nothing_is_started_while_the_reading_is_unavailable_and_the_request_stays_queued(self):
        provider = pov.FakeOcrProvider()
        board, ocr = make(1, provider)
        self.assertEqual(ocr.request_read("p001"), "queued")
        provider.is_available = False
        self.assertIsNone(ocr.begin_next(0.0))
        self.assertEqual((ocr.state_of("p001"), len(ocr.queue)), (pov.QUEUED, 1))
        provider.is_available = True
        ocr.disabled_code = "OCR_UNEXPECTED"
        self.assertIsNone(ocr.begin_next(0.0), "이번 실행 동안 끈 뒤에도 시작하지 않는다")
        ocr.disabled_code = ""
        self.assertEqual(ocr.begin_next(0.0).photo_id, "p001")


class NoLeakTest(unittest.TestCase):
    def test_no_state_request_or_error_value_repeats_the_text_or_the_path(self):
        provider = pov.FakeOcrProvider({"p001": pov.OcrOutcome(("개인적인 글 한 줄",))})
        board, ocr = make(1, provider)
        ocr.request_read("p001")
        job = ocr.begin_next(0.0)
        for value in (repr(job), repr(provider.calls), repr(ocr.queue), repr(pov.OcrOutcome(("개인적인 글 한 줄",), "")), repr(pov.OcrOutcome((), "engine"))):
            self.assertNotIn("개인적인", value)
            self.assertNotIn(FILE_STEM, value)
            self.assertNotIn(USER_DIR, value)
        ocr.run_pending()
        self.assertNotIn("개인적인", repr((ocr.states, ocr.summary, ocr.errors, ocr.summary_of("p001"))))

    def test_the_job_has_no_place_for_a_path(self):
        self.assertEqual(pov.OcrJob.__slots__, ("token", "photo_id", "size", "generation", "began", "started", "cancelled", "cancel_at"))


if __name__ == "__main__":
    unittest.main()
