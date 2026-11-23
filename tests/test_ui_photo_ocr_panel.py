"""글자 읽기 화면 규칙 `ui/core/photo_ocr_panel.py`(결정 D-513, 설계서 2-2에서 2-9, 시험 계획 T-C 의 순수 쪽)의 순수 시험 — 가짜 공급자만 쓴다(프로세스·Qt·시계 없음. 시간은 시험이 숫자로 준다).

지키는 것:
  1) 칸이 있느냐 — 컨트롤러가 없거나 읽을 수 없고(꺼짐·끈 뒤·파일 문제) 보일 것이 없으면 사진 줄에 글자 읽기 칸이 없다(`view` 가 `None`). 컨트롤러가 붙어도 `PhotoBoard.view()` 는 한 글자도 안 바뀐다.
  2) 상태 줄 — 기다림(앞에 몇 장·곧 시작)·준비·읽는 중(몇 초째·15초 넘으면 보조 글)·완료·실패(여섯 오류와 끈 뒤 한 줄)·취소. 접근 이름에는 초가 없다. 상태는 색만이 아니라 늘 글이다.
  3) 읽은 글 — 제목줄(확인 전·확인한 줄 수)·안내·숫자 주의·거른 줄·줄 많음·없음(찾지 못함·모두 뺌)·줄마다 확인 전/확인함 글과 접근 이름·모두 맞아요 두 단계·다시 읽기 확인·합치기·되돌리기. 확신도 숫자는 어디에도 없다.
  4) 줄 일이 사진의 '확인했어요' 를 풀면 줄에 한 번 안내가 뜬다(글 칸을 고칠 때와 같다). 비운 칸·입구 검사에 걸린 글·너무 긴 이은 글은 이유가 남고 줄은 그대로다.
  5) Esc — 확인 줄 먼저, 다음에 읽는 중 취소. 끝난 일의 결과 처리(`finish`) — 취소를 모르는 채 온 `cancelled` 는 끄지 않는다.
  6) 문구 — 새 키(`pho_ocr_*`)의 목록을 못박고, 자리 이름·오류 카탈로그와의 일치·금지 표현·글·경로 비노출을 본다.
"""
import json
import re
import string
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import scan_samples  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.errors.render import render  # noqa: E402
from chanceblog_desktop.ui.core import photo_ocr_panel as pp  # noqa: E402
from chanceblog_desktop.ui.core import photo_ocr_view as pov  # noqa: E402
from chanceblog_desktop.ui.core import photo_text, text  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402
from chanceblog_desktop.ui.core.app_state import AppState  # noqa: E402
from chanceblog_desktop.ui.core.services import FakeHomeProvider  # noqa: E402

T = text.T
USER_DIR, FILE_STEM = "UNIQ-USERDIR-p4m8", "UNIQ-FILE-d2c6"
LINES = ("한우 불고기 전골 28,000원", "된장찌개 9,000원", "공기밥 1,000원")
EXPECTED_KEYS = (
    "pho_ocr_again", "pho_ocr_again_a11y", "pho_ocr_all", "pho_ocr_all_a11y", "pho_ocr_all_ask", "pho_ocr_all_no", "pho_ocr_all_no_a11y", "pho_ocr_all_removed", "pho_ocr_all_yes", "pho_ocr_all_yes_a11y",
    "pho_ocr_bigger", "pho_ocr_bigger_a11y", "pho_ocr_btn", "pho_ocr_btn_a11y", "pho_ocr_cancel", "pho_ocr_cancel_a11y", "pho_ocr_cancelled", "pho_ocr_confirm_busy", "pho_ocr_digits", "pho_ocr_err_addon",
    "pho_ocr_err_blocked", "pho_ocr_err_failed", "pho_ocr_err_timeout", "pho_ocr_err_toobig", "pho_ocr_err_unavailable", "pho_ocr_err_unexpected", "pho_ocr_guide", "pho_ocr_hidden", "pho_ocr_hint",
    "pho_ocr_intro", "pho_ocr_keys", "pho_ocr_label", "pho_ocr_line_a11y", "pho_ocr_line_check_a11y", "pho_ocr_line_done", "pho_ocr_line_edit", "pho_ocr_line_edit_a11y", "pho_ocr_line_empty",
    "pho_ocr_line_pending", "pho_ocr_line_remove", "pho_ocr_line_remove_a11y", "pho_ocr_line_text_a11y", "pho_ocr_list_a11y", "pho_ocr_merge", "pho_ocr_merge_a11y", "pho_ocr_more", "pho_ocr_none",
    "pho_ocr_off_note", "pho_ocr_preparing", "pho_ocr_queued", "pho_ocr_queued_soon", "pho_ocr_reading", "pho_ocr_reading_a11y", "pho_ocr_regen_body", "pho_ocr_regen_more", "pho_ocr_regen_ok", "pho_ocr_regen_title",
    "pho_ocr_removed", "pho_ocr_reread_ask", "pho_ocr_reread_no",
    "pho_ocr_reread_no_a11y", "pho_ocr_reread_yes", "pho_ocr_reread_yes_a11y", "pho_ocr_slow", "pho_ocr_status_a11y", "pho_ocr_summary", "pho_ocr_title", "pho_ocr_undo", "pho_ocr_undo_a11y")
FIELDS = {"n", "s", "m", "k", "total", "state", "text", "limit"}                        # 새 문구가 쓸 수 있는 자리 이름


def path_of(number):
    return f"C:\\Users\\{USER_DIR}\\Pictures\\{FILE_STEM}-{number:02d}.jpg"


def make(count=2, provider=None, lines=LINES):
    """사진 `count` 장이 든 목록(파일 상태까지 읽은 열린 창)과 컨트롤러·화면 규칙."""
    board = pv.PhotoBoard()
    manifest = pm.empty_manifest()
    for number in range(1, count + 1):
        manifest, _id = pm.add_photo(manifest, path_of(number), photo_type="메뉴판")
    board.load(manifest)
    board.open()
    ocr = pov.OcrBoard(board, provider if provider is not None else pov.FakeOcrProvider(default=pov.OcrOutcome(lines)))
    return board, ocr, pp.OcrPanel(ocr)


def read(panel, photo_id="p001", lines=LINES, now=0.0):
    """한 장을 끝까지 읽는다(요청 -> 시작 -> 준비됨 -> 결과)."""
    assert panel.read(photo_id) == "queued"
    job = panel.ocr.begin_next(now)
    panel.ready(now)
    assert panel.finish(job.token, pov.OcrOutcome(tuple(lines)), now) == "applied"
    return job


def start(panel, photo_id="p001", now=0.0, ready=True):
    """한 장을 읽기 시작만 한다 → 요청."""
    assert panel.read(photo_id) == "queued"
    job = panel.ocr.begin_next(now)
    if ready:
        panel.ready(now)
    return job


def strings_of(value, skip=()):
    """뷰모델 속 모든 글(딕셔너리·목록 안까지) — `skip` 의 (길, 값) 은 뺀다."""
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, inner in node.items():
                walk(inner, path + (key,))
        elif isinstance(node, (list, tuple)):
            for index, inner in enumerate(node):
                walk(inner, path + (index,))
        elif isinstance(node, str) and path not in skip:
            found.append(node)

    walk(value, ())
    return found


class VisibilityTest(unittest.TestCase):
    def test_a_photo_row_has_no_block_when_nothing_can_be_read_and_nothing_is_there_to_show(self):
        board, ocr, panel = make(2, provider=pov.FakeOcrProvider(is_available=False))
        self.assertEqual(panel.views(0.0), {"p001": None, "p002": None})
        self.assertEqual(panel.intro(), "", "도구가 없거나 꺼져 있으면 창 위의 안내도 없다")
        self.assertEqual(panel.read("p001"), "unavailable")

    def test_when_it_can_be_read_every_row_has_a_block_with_the_read_button_and_the_intro_shows(self):
        board, ocr, panel = make(2)
        views = panel.views(0.0)
        self.assertEqual(sorted(views), ["p001", "p002"])
        self.assertEqual(panel.intro(), T["pho_ocr_intro"])
        view = views["p001"]
        self.assertEqual((view["state"], view["busy"], view["label"], view["hint"]), ("idle", False, "사진 속 글자", "이 PC 안에서만 읽어요"))
        self.assertEqual(view["read"], {"visible": True, "text": "글자 읽기", "a11y": "사진 1 글자 읽기", "size": "960"})
        self.assertEqual((view["bigger"]["visible"], view["cancel"]["visible"], view["lines"], view["none"], view["ask_reread"]), (False, False, None, "", None))
        self.assertEqual(view["status"], {"state": "idle", "text": "", "tone": "slate", "a11y": ""})

    def test_after_the_tool_is_turned_off_the_read_button_goes_away_but_what_was_read_stays(self):
        board, ocr, panel = make(2)
        read(panel, "p001")
        ocr.disable("OCR_UNAVAILABLE")
        self.assertIsNone(panel.view("p002", 0.0), "읽은 것이 없는 줄에는 칸이 없다")
        kept = panel.view("p001", 0.0)
        self.assertFalse(kept["read"]["visible"] or kept["bigger"]["visible"])
        self.assertEqual(kept["lines"]["total"], 3, "이미 읽은 글은 그대로 보인다(확인할 수 있다)")
        self.assertEqual(panel.intro(), "")

    def test_a_photo_whose_file_cannot_be_used_has_no_read_button_and_cannot_be_read(self):
        board, ocr, panel = make(2)
        board.states["p002"] = pv.FileState("p002", "missing")
        self.assertIsNone(panel.view("p002", 0.0))
        self.assertEqual(panel.read("p002"), "refused")
        self.assertEqual(ocr.state_of("p002"), pov.IDLE, "요청이 대기열에 들어가지 않았다")
        self.assertEqual(panel.view("p001", 0.0)["read"]["visible"], True, "다른 사진은 그대로다")
        read(panel, "p001")
        board.states["p001"] = pv.FileState("p001", "cloud")
        view = panel.view("p001", 0.0)
        self.assertEqual((view["read"]["visible"], view["bigger"]["visible"], view["lines"]["total"]), (False, False, 3), "읽은 글은 남고 단추만 없다")

    def test_a_cloud_photo_that_is_not_downloaded_is_never_sent_to_the_reader(self):
        board, ocr, panel = make(1, provider=pov.FakeOcrProvider())
        board.states["p001"] = pv.FileState("p001", "cloud")
        self.assertEqual(panel.read("p001"), "refused")
        self.assertEqual(ocr.provider.calls, [])

    def test_a_photo_with_no_file_check_result_is_not_read_either(self):
        """독립 검증 S P4 — 파일 확인 도구가 터져 상태가 비었을 때도 막는다(fail-closed): 확인하지 못한 사진은 작업자에 보내지 않는다."""
        board, ocr, panel = make(2, provider=pov.FakeOcrProvider())
        board.states.pop("p002")
        self.assertIsNone(panel.view("p002", 0.0), "읽을 수 없고 보일 것도 없는 줄에는 칸이 없다")
        self.assertEqual(panel.read("p002"), "refused")
        self.assertEqual((ocr.state_of("p002"), ocr.provider.calls), (pov.IDLE, []))
        board.states.clear()
        self.assertEqual((panel.views(0.0), panel.read("p001"), ocr.provider.calls), ({"p001": None, "p002": None}, "refused", []))

    def test_attaching_the_reader_never_changes_what_the_photo_sheet_view_says(self):
        """컨트롤러가 붙고 읽는 중이어도 `PhotoBoard.view()` 는 글자 읽기 칸이 없던 때와 한 글자도 다르지 않다."""
        manifest = pm.empty_manifest()
        for number in (1, 2):
            manifest, _id = pm.add_photo(manifest, path_of(number), photo_type="메뉴판")
        plain = pv.PhotoBoard()
        plain.load(manifest)
        plain.open()
        attached = pv.PhotoBoard()
        attached.load(manifest)
        attached.open()
        panel = pp.OcrPanel(pov.OcrBoard(attached, pov.FakeOcrProvider()))
        self.assertEqual(json.dumps(plain.view(), ensure_ascii=False, sort_keys=True), json.dumps(attached.view(), ensure_ascii=False, sort_keys=True))
        start(panel, "p001")
        self.assertEqual(json.dumps(plain.view(), ensure_ascii=False, sort_keys=True), json.dumps(attached.view(), ensure_ascii=False, sort_keys=True), "읽는 중에도 같다")
        self.assertEqual(plain.card(), attached.card())


class StatusTest(unittest.TestCase):
    def test_queued_says_how_many_are_ahead_and_soon_when_only_a_cancelled_one_is_finishing(self):
        board, ocr, panel = make(3)
        start(panel, "p001")
        self.assertEqual(panel.read("p002"), "queued")
        self.assertEqual(panel.read("p003"), "queued")
        self.assertEqual(panel.status("p002", 1.0)["text"], "차례를 기다리는 중이에요(앞에 1장)")
        self.assertEqual(panel.status("p003", 1.0)["text"], "차례를 기다리는 중이에요(앞에 2장)")
        panel.cancel("p001", 1.0)
        self.assertEqual(panel.status("p002", 1.0)["text"], T["pho_ocr_queued_soon"], "앞에 기다리는 장이 없는데 '앞에 0장' 이라고 하지 않는다")
        self.assertNotIn("0장", panel.status("p002", 1.0)["text"])

    def test_preparing_then_reading_counts_the_seconds_and_the_accessible_name_never_has_them(self):
        board, ocr, panel = make(1)
        job = start(panel, ready=False)
        self.assertEqual(ocr.state_of("p001"), pov.PREPARING)
        preparing = panel.status("p001", 1.0)
        self.assertEqual((preparing["text"], preparing["tone"]), ("글자 읽기를 준비하고 있어요. 처음 한 번은 몇 초 걸려요", "slate"))
        panel.ready(2.0)
        first, later = panel.status("p001", 2.0), panel.status("p001", 14.0)
        self.assertEqual((first["text"], later["text"]), ("사진 속 글자를 읽고 있어요 · 0초", "사진 속 글자를 읽고 있어요 · 12초"))
        self.assertEqual(first["a11y"], later["a11y"], "읽는 프로그램이 매초 읽지 않게 — 상태가 같으면 접근 이름은 그대로다")
        self.assertEqual(first["a11y"], "사진 1 글자 읽기 상태: 사진 속 글자를 읽고 있어요")
        self.assertNotRegex(first["a11y"], r"\d초")
        self.assertIsNotNone(job)

    def test_after_fifteen_seconds_a_second_line_says_it_takes_longer_when_the_pc_is_busy(self):
        board, ocr, panel = make(1)
        start(panel, now=100.0)
        self.assertNotIn("PC 가 바쁘면", panel.status("p001", 115.0)["text"], "정확히 15초는 아직이다")
        late = panel.status("p001", 116.0)
        self.assertEqual(late["text"].split("\n"), ["사진 속 글자를 읽고 있어요 · 16초", "PC 가 바쁘면 더 걸려요. 기다리거나 취소할 수 있어요"])
        self.assertIn("PC 가 바쁘면 더 걸려요", late["a11y"])
        board, ocr, panel = make(1)
        start(panel, now=100.0, ready=False)
        self.assertIn("PC 가 바쁘면", panel.status("p001", 120.0)["text"], "준비가 길어질 때도 같은 안내가 뜬다")

    def test_cancelled_and_done_states(self):
        board, ocr, panel = make(2)
        job = start(panel, "p001")
        self.assertEqual(panel.cancel("p001", 1.0), "cancelling")
        cancelled = panel.status("p001", 1.0)
        self.assertEqual((cancelled["text"], cancelled["tone"]), ("글자 읽기를 멈췄어요", "slate"))
        self.assertEqual((panel.view("p001", 1.0)["read"]["visible"], panel.view("p001", 1.0)["cancel"]["visible"]), (True, False), "취소한 뒤에는 단추로 다시 읽을 수 있다")
        self.assertEqual(panel.finish(job.token, pov.OcrOutcome(error="cancelled"), 2.0), "late", "작업자가 마무리하면 자리가 비고 결과는 버려진다")
        read(panel, "p002")
        done = panel.status("p002", 1.0)
        self.assertEqual((done["state"], done["text"], done["a11y"]), ("done", "", ""), "완료는 상태 줄이 아니라 읽은 글 제목줄이 말한다")

    def test_every_failure_has_its_own_fixed_sentence_and_is_red_and_never_has_the_text_read(self):
        wanted = {"decode": "pho_ocr_err_failed", "engine": "pho_ocr_err_failed", "died": "pho_ocr_err_failed", "timeout": "pho_ocr_err_timeout", "too_big": "pho_ocr_err_toobig", "net_blocked": "pho_ocr_err_unexpected",
                  "proto": "pho_ocr_err_unexpected", "blocked": "pho_ocr_err_blocked", "addon_invalid": "pho_ocr_err_addon", "unavailable": "pho_ocr_err_unavailable"}
        for name, key in wanted.items():
            board, ocr, panel = make(1)
            job = start(panel)
            panel.finish(job.token, pov.OcrOutcome(error=name), 1.0)
            status = panel.status("p001", 2.0)
            self.assertEqual((status["state"], status["tone"]), ("failed", "red"), name)
            self.assertTrue(status["text"].startswith(T[key]), (name, status["text"]))
            self.assertEqual(status["a11y"], T["pho_ocr_status_a11y"].format(n=1, text=status["text"].replace("\n", " ")), name)

    def test_a_failure_that_turned_the_tool_off_says_so_once_more_unless_the_sentence_already_does(self):
        board, ocr, panel = make(1)
        for number in range(3):                                                    # 연속 실패 3번 — 이번 실행 동안 끈다
            job = start(panel, now=number)
            panel.finish(job.token, pov.OcrOutcome(error="died"), number)
        self.assertEqual(ocr.disabled_code, "OCR_UNAVAILABLE")
        status = panel.status("p001", 5.0)["text"].split("\n")
        self.assertEqual(status, [T["pho_ocr_err_failed"], T["pho_ocr_off_note"]])
        board, ocr, panel = make(1)
        panel.finish(start(panel).token, pov.OcrOutcome(error="net_blocked"), 1.0)
        self.assertEqual(ocr.disabled_code, "OCR_UNEXPECTED")
        self.assertEqual(panel.status("p001", 2.0)["text"], T["pho_ocr_err_unexpected"], "이 문장은 이미 '끌게요' 라고 말한다")

    def test_the_six_error_sentences_are_exactly_the_ones_in_the_error_catalog(self):
        pairs = {"OCR_FAILED": "pho_ocr_err_failed", "OCR_TIMEOUT": "pho_ocr_err_timeout", "OCR_TOO_BIG": "pho_ocr_err_toobig", "OCR_ADDON_INVALID": "pho_ocr_err_addon", "OCR_BLOCKED": "pho_ocr_err_blocked",
                 "OCR_UNEXPECTED": "pho_ocr_err_unexpected"}
        for code, key in pairs.items():
            self.assertEqual(T[key], render(code).message, code)
        self.assertEqual(sorted(pp.ERROR_TEXT), sorted([*pairs, "OCR_UNAVAILABLE"]))
        self.assertEqual(sorted(pp.ERROR_TEXT), sorted(set(pov.ERROR_CODE.values())), "컨트롤러가 내는 오류 코드마다 화면 문장이 있다")


class LinesViewTest(unittest.TestCase):
    def test_the_title_says_not_confirmed_yet_and_then_how_many_are_confirmed(self):
        board, ocr, panel = make(1)
        read(panel)
        lines = panel.view("p001", 1.0)["lines"]
        self.assertEqual((lines["total"], lines["confirmed"], lines["title"]), (3, 0, "읽은 글 3줄 · 아직 확인 전이에요"))
        panel.confirm_line("p001", 0, True)
        self.assertEqual(panel.view("p001", 1.0)["lines"]["title"], "읽은 글 3줄 중 확인 1줄")
        for index in (1, 2):
            panel.confirm_line("p001", index, True)
        self.assertEqual(panel.view("p001", 1.0)["lines"]["title"], "읽은 글 3줄 중 확인 3줄")

    def test_every_line_says_whether_it_is_confirmed_in_words_and_has_its_own_names(self):
        board, ocr, panel = make(1)
        read(panel)
        panel.confirm_line("p001", 1, True)
        items = panel.view("p001", 1.0)["lines"]["items"]
        self.assertEqual([(item["index"], item["text"], item["confirmed"], item["state_text"]) for item in items], [(0, LINES[0], False, "확인 전"), (1, LINES[1], True, "확인함"), (2, LINES[2], False, "확인 전")])
        self.assertEqual(items[0]["a11y"], "사진 1 읽은 글 3줄 중 1번째, 확인 전")
        self.assertEqual(items[1]["a11y"], "사진 1 읽은 글 3줄 중 2번째, 확인함")
        self.assertEqual((items[2]["text_a11y"], items[2]["check_a11y"], items[2]["edit_a11y"], items[2]["remove_a11y"]),
                         ("사진 1 읽은 글 3번째 줄 글자", "사진 1 읽은 글 3번째 줄 맞아요", "사진 1 읽은 글 3번째 줄 고치기", "사진 1 읽은 글 3번째 줄 빼기"))
        self.assertEqual((items[0]["edit"], items[0]["remove"]), ("고치기", "빼기"))

    def test_the_guide_always_says_it_can_be_wrong_only_confirmed_lines_count_and_nothing_is_saved(self):
        board, ocr, panel = make(1)
        read(panel)
        guide = panel.view("p001", 1.0)["lines"]["guide"]
        for part in ("틀릴 수 있어요", "맞는 줄에만 맞아요를 눌러 주세요", "누른 줄만 초안에 쓰여요", "저장되지 않아요"):
            self.assertIn(part, guide)
        # 감사 OCR-S1 I9(결정 D-589) — 저장에 관한 말을 사실대로: 목록은 저장하지 않고, 맞아요로 확인해 초안에 넣은 글은 초안과 함께 저장된다
        self.assertIn("확인 전 후보와 읽은 결과 목록은 저장되지 않아요. 맞아요로 확인해 초안에 넣은 글은 초안과 함께 저장돼요", guide)
        self.assertNotIn("읽은 글은 저장되지 않아요", guide, "확인해 초안에 넣은 글은 저장되므로 '읽은 글은 저장되지 않아요' 라고만 말하지 않는다")

    def test_the_digits_note_shows_only_when_a_line_has_digits(self):
        board, ocr, panel = make(1)
        read(panel, lines=("한우 불고기", "공기밥"))
        self.assertEqual(panel.view("p001", 1.0)["lines"]["digits"], "")
        board, ocr, panel = make(1)
        read(panel, lines=("한우 불고기", "28,000원"))
        self.assertEqual(panel.view("p001", 1.0)["lines"]["digits"], "가격·날짜·전화번호 같은 숫자는 꼭 사진과 다시 견주어 주세요.")

    def test_lines_that_were_not_shown_and_too_many_lines_are_only_counted(self):
        board, ocr, panel = make(1)
        shaped = ("900101-1234567", "정상 줄", "가" * 201, "다른 줄")
        read(panel, lines=shaped)
        notes = panel.view("p001", 1.0)["lines"]["notes"]
        self.assertEqual(notes, ["읽은 글 중 2줄은 보여 드리지 않았어요(너무 길거나, 눈에 보이지 않는 글자가 섞여 있거나, 알아볼 수 없는 글자가 붙어 있거나, 주민등록번호·카드 번호·키처럼 보이거나, 태그 같은 표시가 들어 있어요)."])
        for line in shaped[:1] + shaped[2:3]:
            self.assertFalse(any(line in value for value in strings_of(panel.view("p001", 1.0), skip={("lines", "items", 0, "text"), ("lines", "items", 1, "text")})), "거른 줄의 글을 되풀이하지 않는다")
        board, ocr, panel = make(1)
        read(panel, lines=tuple(f"줄 {number}" for number in range(70)))
        notes = panel.view("p001", 1.0)["lines"]["notes"]
        self.assertEqual((panel.view("p001", 1.0)["lines"]["total"], notes), (60, ["줄이 많아 처음 60줄만 보여요."]))

    def test_the_hidden_note_names_what_the_entry_check_really_hides_and_phone_email_and_address_shapes_stay_visible(self):
        """감사 OCR-S1 R4(결정 D-589)·검증 SQ 권고 3(결정 D-593) — 거른 줄 안내는 입구 검사가 실제로 가리는 것(너무 긴 줄·눈에 보이지 않거나 빈칸 같은 글자·겹쳐 쌓인 결합 문자·주민등록번호·카드 번호·키 모양·태그나 `{{ }}`)을 빠짐없이 말한다.
        전화번호·이메일·주소 모양은 가리지 않으므로(동작은 그대로 — 운영자 질문 후보) '개인 번호' 처럼 넓게 말하지 않고, 그런 줄은 목록에 그대로 보인다(숫자 주의 한 줄이 사진과 견주라고 알린다)."""
        invisible = ("가" + chr(0x3164) + "나", chr(0x2800) * 2 + "표", "글" + chr(0xFFFD) + "자")             # 빈칸처럼 보이거나 보이지 않는 글자(한글 채움·점자 빈칸·깨진 글자 표시)
        stacked = ("가" + chr(0x0301) * 3,)                                                              # 겹쳐 쌓인 결합 문자
        hidden = ("가" * 201, "900101-1234567", "4111 1111 1111 1111", scan_samples.google(), "<b>굵게</b>", "{{ 사진 3 }}") + invisible + stacked
        shown = ("010-1234-5678", "02-123-4567", "문의 test.user@example.invalid", "서울시 강남구 테헤란로 123", "사업자 123-45-67890")
        for line in hidden:
            self.assertIsNotNone(pm.check_text("observation", line)[1], "입구 검사가 정말 가리는 줄이다")
        for line in shown:
            self.assertIsNone(pm.check_text("observation", line)[1], "입구 검사가 가리지 않는 줄이다")
        board, ocr, panel = make(1)
        read(panel, lines=hidden + shown)
        lines = panel.view("p001", 1.0)["lines"]
        self.assertEqual([item["text"] for item in lines["items"]], list(shown), "전화·이메일·주소 모양은 가려지지 않는다 — 그대로 보인다")
        self.assertEqual(lines["notes"], [T["pho_ocr_hidden"].format(m=len(hidden))])
        note = lines["notes"][0]
        for word in ("너무 길", "눈에 보이지 않는 글자", "알아볼 수 없는 글자", "주민등록번호", "카드 번호", "키", "태그"):
            self.assertIn(word, note)
        for word in ("개인 번호", "전화", "이메일", "주소"):
            self.assertNotIn(word, note, "가리지 않는 것을 가린다고 말하지 않는다: " + word)
        self.assertIn("전화번호", lines["digits"], "가리지 않는 전화번호는 숫자 주의 한 줄이 사진과 견주라고 알린다")
        for line in hidden:
            self.assertFalse(any(line in value for value in strings_of(panel.view("p001", 1.0))), "거른 줄의 글을 되풀이하지 않는다")

    def test_the_lines_are_locked_while_it_reads_again_and_the_buttons_that_change_them_are_off(self):
        board, ocr, panel = make(1)
        read(panel)
        self.assertTrue(panel.view("p001", 1.0)["lines"]["enabled"])
        self.assertEqual(panel.read("p001"), "ask_replace")
        self.assertEqual(panel.confirm_reread("p001"), "queued")
        busy = panel.view("p001", 1.0)
        self.assertEqual((busy["busy"], busy["lines"]["enabled"], busy["lines"]["all"]["enabled"], busy["read"]["visible"], busy["cancel"]["visible"]), (True, False, False, False, True))
        self.assertEqual(panel.confirm_line("p001", 0, True), "busy", "읽는 중에는 줄을 고칠 수 없다")

    def test_all_right_button_is_enabled_only_while_something_is_not_confirmed_and_no_question_is_open(self):
        board, ocr, panel = make(1)
        read(panel)
        self.assertTrue(panel.view("p001", 1.0)["lines"]["all"]["enabled"])
        self.assertEqual(panel.ask_all_right("p001"), "ask")
        self.assertFalse(panel.view("p001", 1.0)["lines"]["all"]["enabled"], "확인 줄이 떠 있는 동안은 또 누르지 않는다")
        panel.cancel_all_right()
        for index in range(3):
            panel.confirm_line("p001", index, True)
        self.assertFalse(panel.view("p001", 1.0)["lines"]["all"]["enabled"])
        self.assertEqual(panel.ask_all_right("p001"), "none")

    def test_the_two_step_all_right_asks_first_then_confirms_only_the_lines_not_yet_confirmed(self):
        board, ocr, panel = make(1)
        read(panel)
        panel.confirm_line("p001", 0, True)
        self.assertEqual(panel.all_right("p001"), "refused", "묻기 전에는 아무것도 하지 않는다")
        self.assertEqual(panel.ask_all_right("p001"), "ask")
        ask = panel.view("p001", 1.0)["lines"]["ask_all"]
        self.assertEqual(ask["text"], "읽은 글 2줄을 모두 맞아요로 표시할까요? 사진과 견주어 보셨는지 한 번만 더 확인해 주세요.")
        self.assertEqual((ask["yes"], ask["no"], ask["yes_a11y"], ask["no_a11y"]), ("네, 모두 맞아요", "그만두기", "사진 1 읽은 글 2줄을 모두 맞아요로 표시하기", "사진 1 모두 맞아요로 표시하지 않고 그만두기"))
        self.assertEqual(panel.all_right("p001"), "ok")
        view = panel.view("p001", 1.0)
        self.assertEqual((view["lines"]["confirmed"], view["lines"]["ask_all"], board.photo("p001").confirmed_by_user), (3, None, False), "줄은 확인해도 사진은 확정되지 않는다")

    def test_the_reread_question_comes_first_when_lines_exist_and_the_yes_button_names_what_changes(self):
        board, ocr, panel = make(1)
        read(panel)
        self.assertEqual(panel.read("p001"), "ask_replace")
        ask = panel.view("p001", 1.0)["ask_reread"]
        self.assertEqual(ask["text"], "다시 읽으면 지금 읽은 글(고친 것·확인한 것 포함)이 바뀌어요. 다시 읽을까요?")
        self.assertEqual((ask["yes"], ask["no"]), ("다시 읽기", "그만두기"))
        self.assertIn("바꾸며 다시 읽기", ask["yes_a11y"])
        panel.cancel_reread()
        self.assertIsNone(panel.view("p001", 1.0)["ask_reread"])
        self.assertEqual(ocr.state_of("p001"), pov.DONE, "그만두면 아무것도 바뀌지 않는다")

    def test_the_bigger_read_button_is_there_only_when_a_read_is_done_and_it_asks_for_the_bigger_size(self):
        board, ocr, panel = make(2)
        self.assertFalse(panel.view("p001", 1.0)["bigger"]["visible"], "아직 읽지 않았으면 없다")
        read(panel, "p001")
        bigger = panel.view("p001", 1.0)["bigger"]
        self.assertEqual((bigger["visible"], bigger["size"], bigger["text"], bigger["a11y"]), (True, "1600", "작은 글씨라면 더 크게 다시 읽기", "사진 1 글자를 더 크게 다시 읽기"))
        start(panel, "p002")
        panel.finish(panel.ocr.active.token, pov.OcrOutcome(error="decode"), 1.0)
        self.assertFalse(panel.view("p002", 1.0)["bigger"]["visible"], "실패한 뒤에는 처음 단추로 다시 한다")

    def test_the_merge_button_names_the_chosen_line_through_a_placeholder_the_screen_fills(self):
        board, ocr, panel = make(1)
        read(panel)
        merge = panel.view("p001", 1.0)["lines"]["merge"]
        self.assertEqual(merge["text"], "아래 줄과 합치기")
        self.assertEqual(merge["a11y"].format(m=2), "사진 1 읽은 글 2번째 줄을 아래 줄과 합치기")

    def test_no_lines_found_and_all_lines_removed_say_different_things(self):
        board, ocr, panel = make(2)
        read(panel, "p001", lines=())
        view = panel.view("p001", 1.0)
        self.assertEqual((view["none"], view["lines"]), (T["pho_ocr_none"], None))
        self.assertIn("직접 적어 주셔도 돼요", view["none"])
        read(panel, "p002", lines=("하나",))
        panel.remove_line("p002", 0)
        view = panel.view("p002", 1.0)
        self.assertEqual((view["none"], view["lines"]), (T["pho_ocr_all_removed"], None))


class ActionTest(unittest.TestCase):
    def test_a_line_action_that_loosens_the_photo_confirmation_leaves_one_note_like_the_text_boxes_do(self):
        for label, act in (("맞아요", lambda p: p.confirm_line("p001", 0, True)), ("고치기", lambda p: p.edit_line("p001", 0, "고친 글")), ("빼기", lambda p: p.remove_line("p001", 0)),
                           ("합치기", lambda p: p.merge_line("p001", 0)), ("모두 맞아요", lambda p: (p.ask_all_right("p001"), p.all_right("p001"))[1])):
            board, ocr, panel = make(1)
            read(panel)
            board.confirm("p001", True)
            self.assertTrue(board.photo("p001").confirmed_by_user)
            self.assertEqual(act(panel) in ("ok",), True, label)
            self.assertFalse(board.photo("p001").confirmed_by_user, label)
            self.assertEqual(board.view()["rows"][0]["changed_note"], T["pho_unconfirmed_note"], label)

    def test_no_note_when_the_photo_was_not_confirmed(self):
        board, ocr, panel = make(1)
        read(panel)
        panel.confirm_line("p001", 0, True)
        self.assertEqual(board.view()["rows"][0]["changed_note"], "")

    def test_a_new_read_that_replaces_the_lines_of_a_confirmed_photo_leaves_the_note(self):
        board, ocr, panel = make(1)
        board.confirm("p001", True)
        read(panel)
        self.assertFalse(board.photo("p001").confirmed_by_user)
        self.assertEqual(board.view()["rows"][0]["changed_note"], T["pho_unconfirmed_note"])

    def test_an_empty_box_is_refused_with_the_way_out_and_the_line_stays(self):
        board, ocr, panel = make(1)
        read(panel)
        for value in ("", "   ", None):
            self.assertEqual(panel.edit_line("p001", 1, value), "invalid")
            self.assertEqual(panel.view("p001", 1.0)["lines"]["error"], {"index": 1, "text": "비워 둘 수 없어요. 줄을 없애려면 빼기를 눌러 주세요."})
        self.assertEqual([item.text for item in board.photo("p001").visible_text], list(LINES))

    def test_a_line_that_the_entrance_check_refuses_keeps_its_reason_and_the_old_text(self):
        board, ocr, panel = make(1)
        read(panel)
        self.assertEqual(panel.edit_line("p001", 0, "900101-1234567"), "invalid")
        error = panel.view("p001", 1.0)["lines"]["error"]
        self.assertEqual(error["index"], 0)
        self.assertIn("주민등록번호나 카드 번호처럼 보이는 숫자는 받지 않아요", error["text"])
        self.assertNotIn("900101", error["text"], "이유 문장에 글을 되풀이하지 않는다")
        self.assertEqual(board.photo("p001").visible_text[0].text, LINES[0])
        self.assertEqual(panel.edit_line("p001", 0, "정상으로 고친 글"), "ok")
        self.assertIsNone(panel.view("p001", 1.0)["lines"]["error"], "받아들여지면 이유가 사라진다")
        item = panel.view("p001", 1.0)["lines"]["items"][0]
        self.assertEqual((item["text"], item["confirmed"]), ("정상으로 고친 글", False), "고친 줄은 다시 확인 전이다")

    def test_merging_into_a_line_that_is_too_long_is_refused_with_the_reason(self):
        board, ocr, panel = make(1)
        read(panel, lines=("가" * 150, "나" * 150))
        self.assertEqual(panel.merge_line("p001", 0), "invalid")
        self.assertEqual(panel.view("p001", 1.0)["lines"]["error"]["index"], 0)
        self.assertEqual(len(board.photo("p001").visible_text), 2)

    def test_removing_a_line_can_be_undone_once_and_only_while_nothing_else_changed(self):
        board, ocr, panel = make(1)
        read(panel)
        self.assertEqual(panel.remove_line("p001", 1), "ok")
        undo = panel.view("p001", 1.0)["lines"]
        self.assertEqual((undo["undo"]["text"], undo["undo"]["a11y"], undo["removed"], undo["total"]), ("뺀 줄 되돌리기", "사진 1 방금 뺀 줄 되돌리기", "읽은 글에서 한 줄을 뺐어요.", 2))
        self.assertEqual(panel.undo_remove(), "ok")
        view = panel.view("p001", 1.0)["lines"]
        self.assertEqual(([item["text"] for item in view["items"]], view["undo"], view["removed"]), (list(LINES), None, ""))
        panel.remove_line("p001", 0)
        panel.confirm_line("p001", 0, True)
        self.assertIsNone(panel.view("p001", 1.0)["lines"]["undo"], "그 뒤에 목록이 바뀌었으면 되돌리기 단추가 없다")
        self.assertEqual(panel.undo_remove(), "refused")

    def test_the_undo_button_goes_away_when_the_photo_list_is_changed_by_other_means(self):
        board, ocr, panel = make(1)
        read(panel)
        panel.remove_line("p001", 1)
        self.assertIsNotNone(panel.view("p001", 1.0)["lines"]["undo"])
        self.assertEqual(board.set_type("p001", "간판"), "ok", "줄이 아닌 사진 정보를 바꿨다 — 컨트롤러는 모르는 변화다")
        self.assertIsNone(panel.view("p001", 1.0)["lines"]["undo"], "되돌려도 소용없는데 단추가 남지 않는다")
        self.assertEqual(panel.undo_remove(), "refused")

    def test_escape_takes_the_question_first_then_cancels_the_read_and_otherwise_does_nothing(self):
        board, ocr, panel = make(1)
        self.assertEqual(panel.escape("p001", 0.0), "", "할 일이 없으면 창이 닫힌다")
        read(panel)
        panel.ask_all_right("p001")
        self.assertEqual(panel.escape("p001", 1.0), "all_right")
        self.assertEqual(ocr.all_right_asked, (None, 0))
        panel.read("p001")
        self.assertEqual(panel.escape("p001", 1.0), "reread")
        self.assertEqual(panel.escape("p001", 1.0), "")
        panel.read("p001")
        panel.confirm_reread("p001")
        ocr.begin_next(2.0)
        panel.ready(2.0)
        self.assertEqual(panel.escape("p001", 3.0), "cancel")
        self.assertEqual(ocr.state_of("p001"), pov.CANCELLED)

    def test_a_late_result_for_an_unknown_request_changes_nothing_and_a_cancelled_one_stays_cancelled(self):
        board, ocr, panel = make(1)
        job = start(panel)
        panel.cancel("p001", 1.0)
        before = [item.text for item in board.photo("p001").visible_text]
        self.assertEqual(panel.finish(job.token, pov.OcrOutcome(LINES), 2.0), "late")
        self.assertEqual(([item.text for item in board.photo("p001").visible_text], ocr.state_of("p001"), ocr.active), (before, pov.CANCELLED, None))
        self.assertEqual(panel.finish(999, pov.OcrOutcome(LINES), 2.0), "late")

    def test_a_cancelled_answer_for_a_live_request_counts_as_a_death_and_never_turns_the_tool_off(self):
        board, ocr, panel = make(1)
        job = start(panel)
        self.assertEqual(panel.finish(job.token, pov.OcrOutcome(error="cancelled"), 1.0), "failed")
        self.assertEqual((ocr.disabled_code, ocr.failures, ocr.worker_ready, ocr.error_of("p001")), ("", 1, False, "died"))

    def test_after_an_error_that_ends_the_worker_the_next_read_prepares_again_but_a_decode_error_keeps_it(self):
        for name, ready_after in (("died", False), ("timeout", False), ("proto", False), ("decode", True), ("engine", True), ("too_big", True)):
            board, ocr, panel = make(1)
            panel.finish(start(panel).token, pov.OcrOutcome(error=name), 1.0)
            self.assertEqual(ocr.worker_ready, ready_after, name)

    def test_the_view_model_never_repeats_the_text_read_outside_the_line_items_and_has_no_confidence(self):
        board, ocr, panel = make(2)
        read(panel, "p001")
        start(panel, "p002")
        views = panel.views(5.0)
        skip = {("lines", "items", index, "text") for index in range(len(LINES))}
        for view in views.values():
            self.assertNotIn("score", json.dumps(view, ensure_ascii=False).lower())
            for value in strings_of(view, skip=skip):
                for line in LINES:
                    self.assertNotIn(line, value)
                for marker in (USER_DIR, FILE_STEM, "C:\\", "Pictures", ".jpg"):
                    self.assertNotIn(marker, value)
        self.assertEqual(sorted(views["p001"]["lines"]), sorted(["visible", "enabled", "total", "confirmed", "title", "guide", "digits", "notes", "items", "list_a11y", "keys", "all", "merge", "undo", "removed", "ask_all", "error"]))
        self.assertEqual(sorted(views["p001"]["lines"]["items"][0]), sorted(["index", "text", "confirmed", "state_text", "a11y", "text_a11y", "check_a11y", "edit", "edit_a11y", "remove", "remove_a11y"]))


class StaleQuestionTest(unittest.TestCase):
    """독립 검증 S SP-1(2026-11-22) — '읽은 글 모두 맞아요' 질문을 띄운 뒤 다시 읽어 줄이 바뀌면, 질문이 살아남아 사용자가 보지 못한 새 줄을 한꺼번에 '맞아요' 로 만들던 틈. 뿌리는 B1 컨트롤러가 다시 읽기를 시작할 때도 결과를 적용할 때도 질문을 지우지 않는 것이고(결정 D-519 한계), 이 화면 규칙이 막는다."""
    NEW = tuple(f"새로 읽은 {number}번째 줄 {number},000원" for number in range(1, 6))

    def asked(self, count=1):
        board, ocr, panel = make(count)
        read(panel)
        self.assertEqual(panel.ask_all_right("p001"), "ask")
        self.assertEqual(ocr.all_right_asked, ("p001", 3))
        return board, ocr, panel

    def finish_reread(self, panel, lines, now=1.0):
        job = panel.ocr.begin_next(now)
        panel.ready(now)
        self.assertEqual(panel.finish(job.token, pov.OcrOutcome(tuple(lines)), now + 1), "applied")

    def test_starting_the_reread_takes_the_question_away_and_the_old_yes_cannot_confirm_the_new_lines(self):
        board, ocr, panel = self.asked()
        self.assertEqual(panel.read("p001"), "ask_replace")
        self.assertEqual(panel.confirm_reread("p001"), "queued")
        self.assertEqual(ocr.all_right_asked, (None, 0), "다시 읽기가 시작되면 질문은 바로 거둔다")
        self.assertIsNone(panel.view("p001", 1.0)["lines"]["ask_all"])
        self.finish_reread(panel, self.NEW)
        view = panel.view("p001", 3.0)
        self.assertEqual((view["lines"]["total"], view["lines"]["confirmed"], view["lines"]["ask_all"]), (5, 0, None), "새 줄은 확인 전이고 질문은 되살아나지 않는다")
        self.assertEqual(panel.all_right("p001"), "refused", "낡은 '네' 는 보지도 못한 새 줄을 맞아요로 만들지 못한다")
        self.assertEqual(panel.view("p001", 3.0)["lines"]["confirmed"], 0)
        self.assertEqual(panel.ask_all_right("p001"), "ask", "새 줄에는 새로 묻는다")
        self.assertEqual(panel.view("p001", 3.0)["lines"]["ask_all"]["text"], T["pho_ocr_all_ask"].format(n=5))
        self.assertEqual(panel.all_right("p001"), "ok")
        self.assertEqual(panel.view("p001", 3.0)["lines"]["confirmed"], 5)

    def test_a_question_that_outlives_the_lines_it_was_asked_about_is_dropped_even_when_the_reread_did_not_go_through_the_screen_rule(self):
        board, ocr, panel = self.asked()
        self.assertEqual(ocr.request_read("p001"), "ask_replace")
        self.assertEqual(ocr.confirm_reread("p001"), "queued")                         # 화면 규칙을 거치지 않고 컨트롤러로 곧바로
        job = ocr.begin_next(1.0)
        ocr.mark_ready(1.0)
        self.assertEqual(ocr.on_result(job.token, self.NEW, 2.0), "applied")
        self.assertEqual(panel.all_right("p001"), "refused", "그리기 전에 불러도 낡은 질문을 거절한다")
        self.assertEqual((ocr.all_right_asked, ocr.confirmed_line_count("p001")), ((None, 0), 0))

    def test_drawing_drops_the_stale_question_too(self):
        board, ocr, panel = self.asked()
        ocr.request_read("p001")
        ocr.confirm_reread("p001")
        job = ocr.begin_next(1.0)
        ocr.mark_ready(1.0)
        ocr.on_result(job.token, self.NEW, 2.0)
        view = panel.view("p001", 3.0)
        self.assertEqual((view["lines"]["ask_all"], view["lines"]["all"]["enabled"], ocr.all_right_asked), (None, True, (None, 0)), "확인 줄이 안 보이고 단추가 다시 눌린다")

    def test_the_question_survives_everything_that_does_not_change_the_lines_it_asked_about(self):
        board, ocr, panel = self.asked(2)
        for now in (1.0, 2.0, 3.0):
            self.assertEqual(panel.view("p001", now)["lines"]["ask_all"]["text"], T["pho_ocr_all_ask"].format(n=3))
        self.assertEqual(panel.read("p001"), "ask_replace")
        panel.cancel_reread()
        self.assertEqual(ocr.all_right_asked, ("p001", 3), "다시 읽을지 묻다 그만두는 것은 줄을 바꾸지 않는다")
        read(panel, "p002")
        self.assertEqual(ocr.all_right_asked, ("p001", 3), "다른 사진을 읽어 끝내도 이 사진의 질문은 그대로다")
        self.assertEqual(panel.read("p002"), "ask_replace")
        self.assertEqual(panel.confirm_reread("p002"), "queued")
        self.assertEqual(ocr.all_right_asked, ("p001", 3), "다른 사진을 다시 읽기 시작해도 이 사진의 질문은 그대로다")
        self.assertEqual(panel.all_right("p001"), "ok")

    def test_closing_the_question_by_hand_forgets_what_it_asked_about(self):
        board, ocr, panel = self.asked()
        panel.cancel_all_right()
        self.assertEqual(panel.all_right("p001"), "refused")
        self.assertEqual(panel.ask_all_right("p001"), "ask")
        self.assertEqual(panel.escape("p001", 1.0), "all_right")
        self.assertEqual(panel.all_right("p001"), "refused")
        self.assertEqual(panel.ask_all_right("p001"), "ask")


class SeveralPhotosTest(unittest.TestCase):
    """독립 검증 Q QP-6 — 사진이 둘 이상일 때 한 사진의 질문·이유·안내가 다른 사진으로 번지지 않고, 새 읽기가 지난 이유를 지우며, 바뀐 것 없는 일은 확정한 사진에 안내를 붙이지 않는다(위 시험들은 거의 사진 한 장만 보았다)."""

    def both_read(self):
        board, ocr, panel = make(2)
        read(panel, "p001")
        read(panel, "p002")
        return board, ocr, panel

    def test_a_question_open_on_one_photo_does_not_show_on_the_other_photo(self):
        board, ocr, panel = self.both_read()
        self.assertEqual(panel.ask_all_right("p001"), "ask")
        self.assertEqual(panel.read("p001"), "ask_replace")
        first, second = panel.view("p001", 1.0), panel.view("p002", 1.0)
        self.assertEqual((first["lines"]["ask_all"] is not None, first["ask_reread"] is not None), (True, True), "묻은 사진에는 두 확인 줄이 뜬다")
        self.assertEqual((second["lines"]["ask_all"], second["ask_reread"]), (None, None), "다른 사진에는 뜨지 않는다")
        self.assertEqual((first["lines"]["all"]["enabled"], second["lines"]["all"]["enabled"]), (False, True), "다른 사진의 모두 맞아요 단추는 그대로 눌린다")

    def test_a_line_reason_stays_with_its_own_photo_and_a_new_read_takes_it_away(self):
        board, ocr, panel = self.both_read()
        self.assertEqual(panel.edit_line("p001", 0, ""), "invalid")
        self.assertEqual(panel.view("p001", 1.0)["lines"]["error"], {"index": 0, "text": T["pho_ocr_line_empty"]})
        self.assertIsNone(panel.view("p002", 1.0)["lines"]["error"], "다른 사진에는 이 이유가 나오지 않는다")
        self.assertEqual(panel.read("p001"), "ask_replace")
        self.assertIsNone(panel.view("p001", 2.0)["lines"]["error"], "새 읽기를 시작하면 지난 줄 이유는 사라진다")
        panel.cancel_reread()
        self.assertEqual(panel.edit_line("p002", 1, ""), "invalid")
        self.assertEqual(panel.view("p002", 3.0)["lines"]["error"], {"index": 1, "text": T["pho_ocr_line_empty"]})
        self.assertIsNone(panel.view("p001", 3.0)["lines"]["error"], "첫 사진에는 둘째 사진의 이유가 나오지 않는다")
        self.assertEqual(panel.read("p001"), "ask_replace")
        self.assertIsNone(panel.view("p002", 4.0)["lines"]["error"], "어느 사진의 읽기든 시작하면 지난 이유는 지운다(다음 일이 시작되면 지운다)")

    def test_a_line_job_that_changes_nothing_leaves_a_confirmed_photo_and_its_notes_alone(self):
        board, ocr, panel = self.both_read()
        board.confirm("p001", True)
        self.assertEqual(panel.edit_line("p001", 0, LINES[0]), "unchanged")
        self.assertTrue(board.photo("p001").confirmed_by_user, "바뀐 것이 없으면 확정은 그대로다")
        self.assertFalse(board.view()["rows"][0]["changed_note"], "확정이 풀리지 않았으니 풀렸다는 안내도 없다")
        self.assertEqual(panel.confirm_line("p001", 0, True), "ok")
        self.assertFalse(board.photo("p001").confirmed_by_user, "줄이 바뀌면 풀리고 안내가 붙는다")
        self.assertEqual(board.view()["rows"][0]["changed_note"], T["pho_unconfirmed_note"])
        self.assertFalse(board.view()["rows"][1]["changed_note"], "다른 사진 줄에는 안내가 붙지 않는다")


class WordingTest(unittest.TestCase):
    def test_the_key_list_of_the_new_texts_is_pinned(self):
        """문구가 위젯과 어긋나지 않게 키 목록을 못박는다 — 키를 더하거나 빼면 이 목록과 쓰임(`test_ui_qt_photo` 의 문구 사용 검사)을 함께 고친다."""
        self.assertEqual(tuple(sorted(photo_text.PHOTO_OCR_T)), EXPECTED_KEYS)
        self.assertEqual(sorted(key for key in photo_text.PHOTO_T if key.startswith("pho_ocr_")), list(EXPECTED_KEYS), "새 문구는 모두 같은 표(PHOTO_T)에도 있다")

    def test_every_new_text_follows_the_house_rules(self):
        for key, value in photo_text.PHOTO_OCR_T.items():
            self.assertIs(T[key], value, key)
            self.assertTrue(key.startswith("pho_ocr_"), key)
            for word in text.FORBIDDEN:
                self.assertNotIn(word, value, key)
            self.assertNotIn("~", value, key)
            self.assertNotIn("http", value.lower(), key)
            self.assertNotRegex(value, r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+", f"{key}: 영문 오류 코드·상수 이름이 없다")
            self.assertNotRegex(value, r"[A-Za-z]:\\|/Users/|\\Users\\", f"{key}: 경로가 없다")
            self.assertNotIn("Traceback", value, key)
            names = {field for _text, field, _spec, _conversion in string.Formatter().parse(value) if field}
            self.assertLessEqual(names, FIELDS, f"{key}: 알 수 없는 자리 이름 {sorted(names - FIELDS)}")

    def test_the_a11y_names_with_a_photo_number_all_start_with_the_photo_number(self):
        for key, value in photo_text.PHOTO_OCR_T.items():
            if key.endswith("_a11y") and "{n}" in value and key not in ("pho_ocr_status_a11y",):
                self.assertTrue(value.startswith("사진 {n} "), key)
        self.assertEqual(T["pho_ocr_status_a11y"], "사진 {n} 글자 읽기 상태: {text}")

    def test_the_wording_matches_the_design_sentences(self):
        self.assertEqual(T["pho_ocr_intro"], "글자 읽기는 이 PC 안에서만 해요. 사진은 밖으로 나가지 않아요. 읽은 글은 틀릴 수 있어서, 확인한 줄만 초안에 쓰여요. 확인 전 후보와 읽은 결과 목록은 저장되지 않아요. 맞아요로 확인해 초안에 넣은 글은 초안과 함께 저장돼요.")
        self.assertEqual(T["pho_ocr_guide"], "읽은 글은 틀릴 수 있어요. 사진과 견주어 맞는 줄에만 맞아요를 눌러 주세요. 누른 줄만 초안에 쓰여요. 확인 전 후보와 읽은 결과 목록은 저장되지 않아요. 맞아요로 확인해 초안에 넣은 글은 초안과 함께 저장돼요.")
        self.assertEqual(T["pho_ocr_hidden"], "읽은 글 중 {m}줄은 보여 드리지 않았어요(너무 길거나, 눈에 보이지 않는 글자가 섞여 있거나, 알아볼 수 없는 글자가 붙어 있거나, 주민등록번호·카드 번호·키처럼 보이거나, 태그 같은 표시가 들어 있어요).")
        self.assertEqual(T["pho_ocr_regen_body"], "저장해 둔 글에 사진 속 글자 문단이 들어 있었다면, 지금 확인한 글자가 없는 사진의 문단은 새 글에서 빠져요. 읽은 결과 목록은 저장되지 않아요. 넣으려면 먼저 사진 정리에서 그 사진의 글자를 다시 읽고 맞아요를 누른 뒤 사진을 다시 확인했어요로 해 주세요.")
        self.assertEqual(T["pho_ocr_regen_more"], "저장해 둔 글의 사진 속 글자 문단도 새 글에서 빠질 수 있어요. 읽은 결과 목록은 저장되지 않아서 지금은 확인한 글자가 없어요.")
        self.assertEqual((T["pho_ocr_btn"], T["pho_ocr_again"], T["pho_ocr_bigger"], T["pho_ocr_cancel"], T["pho_ocr_all"]), ("글자 읽기", "다시 읽기", "작은 글씨라면 더 크게 다시 읽기", "취소", "읽은 글 모두 맞아요"))
        self.assertEqual((T["pho_ocr_line_pending"], T["pho_ocr_line_done"], T["pho_ocr_line_remove"]), ("확인 전", "확인함", "빼기"))
        self.assertEqual(T["pho_ocr_summary"].format(n=47, k=5), "읽은 글 47줄 중 확인 5줄")
        self.assertEqual(T["pho_ocr_hint"], "이 PC 안에서만 읽어요")
        self.assertEqual(T["pho_ocr_cancelled"], "글자 읽기를 멈췄어요")

    def test_every_text_that_speaks_of_saving_says_the_same_thing_and_the_old_one_line_sentence_is_nowhere(self):
        """감사 OCR-S1 I9(결정 D-589)·검증 SQ 참고 7(결정 D-593) — '읽은 글은 저장되지 않아요' 는 맞아요로 확인해 초안에 넣은 글이 초안과 함께 저장된다는 사실을 가린다. 창 위 안내·읽은 글 안내는 '읽은 결과 목록은 저장되지 않고 확인해 넣은 글은 초안과
        함께 저장된다' 로, 저장해 둔 초안을 다시 만들 때의 확인창 두 글(`pho_ocr_regen_*`)도 같은 '읽은 결과 목록' 말씨로 맞췄고, 어느 문구에도 옛 한 줄짜리 말이 없다 — 이 표의 모든 문구를 훑는다."""
        for key, value in photo_text.PHOTO_OCR_T.items():
            self.assertNotIn("읽은 글은 저장되지 않아", value, key)
            self.assertNotIn("읽은 글은 저장하지 않아", value, key)
        pair = "확인 전 후보와 읽은 결과 목록은 저장되지 않아요. 맞아요로 확인해 초안에 넣은 글은 초안과 함께 저장돼요."
        for key in ("pho_ocr_intro", "pho_ocr_guide"):
            self.assertIn(pair, T[key], key)
        self.assertIn("읽은 결과 목록은 저장되지 않아요.", T["pho_ocr_regen_body"])
        self.assertIn("읽은 결과 목록은 저장되지 않아서", T["pho_ocr_regen_more"])
        mentions = sorted(key for key, value in photo_text.PHOTO_OCR_T.items() if "저장" in value and key not in ("pho_ocr_regen_title",))
        self.assertEqual(mentions, ["pho_ocr_guide", "pho_ocr_intro", "pho_ocr_regen_body", "pho_ocr_regen_more"], "저장을 말하는 문구는 이 넷뿐이다 — 새로 생기면 위 말씨와 맞는지 보고 이 목록을 고친다")

    def test_the_screen_states_document_quotes_the_intro_the_guide_the_digits_note_and_the_hidden_note_word_for_word(self):
        """검증 SQ 권고 3(결정 D-593) — 화면 문구를 바꾸고도 문서의 인용이 옛 글로 남던 틈(검증이 눈으로 찾았다)을 닫는다: `docs/UI_STATES.md` 의 글자 읽기 표가 창 위 안내·읽은 글 안내·숫자 주의·거른 줄 안내(줄 수 자리는 `M`, 끝의 마침표는 빼고)를
        문구 표와 한 글자 같게 인용한다."""
        doc = (ROOT / "docs" / "UI_STATES.md").read_text(encoding="utf-8")
        for key in ("pho_ocr_intro", "pho_ocr_guide", "pho_ocr_digits"):
            self.assertIn(T[key], doc, key)
        hidden = T["pho_ocr_hidden"].replace("{m}", "M")
        self.assertTrue(hidden.endswith(")."), hidden)
        self.assertIn(hidden[:-1], doc, "거른 줄 안내")


class AppStateTest(unittest.TestCase):
    def test_without_a_reader_nothing_of_it_exists_and_the_photo_board_has_no_hook_target(self):
        state = AppState(FakeHomeProvider())
        self.assertEqual((state.ocr, state.ocr_panel, state.drafts.photos.ocr), (None, None, None))

    def test_an_injected_reader_gets_a_controller_and_a_panel_on_the_draft_photo_board(self):
        provider = pov.FakeOcrProvider()
        state = AppState(FakeHomeProvider(), ocr=provider)
        self.assertIsInstance(state.ocr, pov.OcrBoard)
        self.assertIs(state.drafts.photos.ocr, state.ocr)
        self.assertIs(state.ocr.provider, provider)
        self.assertIs(state.ocr_panel.ocr, state.ocr)

    def test_a_paired_reader_of_the_home_provider_is_used_only_when_it_gives_one(self):
        class Paired(FakeHomeProvider):
            given = None

            def ocr_provider(self):
                return self.given

        plain = Paired()
        self.assertIsNone(AppState(plain).ocr, "짝 공급자가 None 을 주면(도구 없음·관문 꺼짐) 아무것도 붙지 않는다")
        plain.given = pov.FakeOcrProvider()
        self.assertIs(AppState(plain).ocr.provider, plain.given)

    def test_the_real_home_provider_gives_none_while_the_gate_is_off_in_the_source(self):
        from chanceblog_desktop.ui.adapters import ServiceHomeProvider
        self.assertFalse(capabilities.local_ocr_enabled(), "이 빌드는 꺼져 있다 — 켜지 않고 병합한다")
        self.assertIsNone(ServiceHomeProvider("nowhere").ocr_provider())


if __name__ == "__main__":
    unittest.main()
