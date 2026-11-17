"""글자 읽기 컨트롤러 `ui/core/photo_ocr_view.py`(결정 D-512, 설계서 2-3·2-5·2-7·3-3·3-10, 시험 계획 T-B)의 순수 시험 — 가짜 공급자만 쓴다(프로세스·Qt·시계 없음).

지키는 것:
  1) 상태 전이 — 쉼 -> 기다림 -> 준비 -> 읽는 중 -> 완료·실패·취소, 한 번에 한 장(FIFO), 줄이 있는 사진은 다시 읽기 확인.
  2) 늦은 결과 버림 — 새 초안·떠남·열기(세대)·사진 지우기·다시 찾기·취소·모르는 번호·같은 결과 두 번은 `late` 이고 목록은 안 바뀐다.
  3) 시간·실패 — 준비 150초·사진 90초 초과·취소 3초 규칙·연속 실패 3번이면 끔·한 번이면 끄는 것·큰 사진은 안 센다.
  4) `PhotoBoard` 와의 짝 — 읽는 중·기다리는 사진은 '확인했어요'·'모두 확인했어요' 가 건너뛴다. 컨트롤러가 없으면 지금과 같다.
  5) 줄 — 확인·고침(입구 검사)·빼기와 한 번 되돌리기·합치기·'모두 맞아요' 두 단계(사진은 확정하지 않는다).
  6) 글·경로가 상태·요청·오류 값에 되풀이되지 않는다.
"""
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
