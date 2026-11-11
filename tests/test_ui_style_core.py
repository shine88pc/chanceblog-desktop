"""'내 글 문체 참고값 보기'(N-3a)의 화면 쪽 순수 논리(`ui/core/style_view.py`·문구 `style_text.py`·실제 공급자 `ui/style_adapter.py`, 결정 D-330–D-339) 시험 — PySide6 없이 돈다(CI 에서 그대로).

지키는 것:
  1) 문구 — 판정 라벨(`전문적`·`격식체` 같은 말)·결과를 약속하는 말·영문 오류 코드·물결표·웹 주소가 없고, 숫자 옆 안내는 한 문장이다. 상수는 운영자가 정한 값(글은 최대 2개)이다.
  2) 숫자 서식 — 분수를 반올림(0.5 는 올림)해 보이고 알 수 없는 값은 0 이 아니라 `알 수 없음` 이다.
  3) 컨트롤러 — 고르기(취소하면 공급자를 안 부름·꽉 차면 거절·거절 문장)·계산(작업 스레드에서 돌고 화면 스레드가 받는다)·세대 번호(닫은 뒤·다시 한 뒤·새로 연 뒤에 늦게 온 결과는 버린다·두 번 받지 않는다)·실패(고정 문장만).
  4) 뷰모델 — 글 하나·둘(범위·합산·범위만)·`알 수 없음`·글마다 안내와 CP949 안내. 글이 어떤 뷰모델·상태에도 담기지 않는다(카나리).
  5) 실제 공급자 — 읽기 기반(`own_posts`)과 순수 계산을 잇는 얇은 어댑터: 고른 글 형식은 입력 경로의 확장자로 가르고 거절은 고정 문장이며 경로·파일 이름·글을 되풀이하지 않고 파일을 쓰지 않는다.
  6) 소스 규칙 — 새 파일이 서비스·프로필·설정·보관함·Qt 를 가져오지 않고(무거운 모듈은 늦게) 쓰는 길이 없다.
소스·시험에는 물결 글자와 웹 주소를 날것으로 쓰지 않는다.
"""
import ast
import builtins
import contextlib
import io
import os
import re
import sys
import tempfile
import threading
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import key_leak_support as leak  # noqa: E402
from chanceblog_desktop.content import style_stats  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import own_posts  # noqa: E402
from chanceblog_desktop.ui import style_adapter  # noqa: E402
from chanceblog_desktop.ui.core import style_text, style_view, text  # noqa: E402
from chanceblog_desktop.ui.core.jobs import JobFailure  # noqa: E402
from chanceblog_desktop.ui.core.style_view import FakeStyleProvider, StyleRefusal, StyleStudy  # noqa: E402

UI = ROOT / "src" / "chanceblog_desktop" / "ui"
NEW_CORE = (UI / "core" / "style_text.py", UI / "core" / "style_view.py")
NEW_FILES = (*NEW_CORE, UI / "style_adapter.py", UI / "qt" / "style_dialog.py")
TILDE = chr(0x7E)
SCHEME = "https" + "://"
MARK = "UNIQ-STYLE-m3k9-본문"
TRUST = "이 숫자는 고른 글을 세어 본 참고값이에요. 글의 성격이나 전문성을 판단하는 값이 아니에요."
RANGE_ONLY = "글 사이 차이가 커서 평균 대신 범위만 보여 드려요"
VERDICTS_N3A = ("전문적", "전문성", "격식체", "비격식", "친근", "딱딱", "수준이", "좋은 글", "나쁜 글", "신뢰도", "점수", "등급", "추천", "진단", "성향", "성격이")      # N-3a 가 이미 막던 낱말
VERDICTS_AUDIT = ("전문적", "비전문", "격식", "공식적", "딱딱", "친근", "정중", "공손", "존댓말", "반말", "합쇼", "해요체", "합니다체", "권위", "신뢰도", "전문가", "초보", "수준", "품질", "좋은 글", "나쁜 글", "훌륭", "우수", "미흡", "부족한 글", "AI가 쓴", "표절", "작성자는", "성격은", "페르소나", "경력", "자격")      # 독립 검증의 판정 라벨 낱말 32종
GRADING_WORDS = ("좋은", "나쁜", "정확", "정상", "권장", "점수")                                                                          # 지시서가 든 평가 낱말
N3AFIX_KEYS = ("style_rough", "style_yours_result", "style_col_one_pasted", "style_notice_wrap")                                       # n3afix 가 더하거나 바꾼 문구

P_MD = "# 제목\n\n## 하나\n\n## 둘\n\n저는 갑니다. 정말요? 좋아요. 끝났다."            # 문장 4(글자 18)·문단 1·소제목 2·합쇼 1 해요 2 평서 1·질문 1
Q_TXT_ONE_PARAGRAPH = "갑니다. 정말요? 좋아요. 끝났다."                                    # 문장 4(글자 16)·문단 1
Q_TXT_TWO_PARAGRAPHS = "저는 갑니다.\n\n정말요?"                                          # 문장 2(글자 10)·문단 2


class Harness:
    """가짜 공급자로 컨트롤러를 움직이는 도우미 — 작업 스레드의 결과를 기다린다."""

    def __init__(self, files=None, refuse=(), provider=None, opened=True):
        self.provider = provider or FakeStyleProvider(files or {}, refuse)
        self.study = StyleStudy(self.provider)
        if opened:
            self.study.open()

    def start(self, pasted="", wait=True):
        box = {"done": threading.Event()}

        def on_done(result, payload):
            box.update(result=result, thread=threading.current_thread())
            box["done"].set()

        def on_error(failure, payload):
            box.update(failure=failure, thread=threading.current_thread())
            box["done"].set()

        def on_cancel(payload):
            box.update(cancel=True)
            box["done"].set()

        status, job = self.study.start(pasted, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        box.update(status=status, job=job)
        if status == "started" and wait:
            assert box["done"].wait(10), "계산이 끝나지 않았다"
        return box

    def finish(self, pasted=""):
        """계산을 시작하고 받은 결과를 컨트롤러에 넣는다 → 상태."""
        box = self.start(pasted)
        if "result" in box:
            self.study.apply(box["result"])
        return box


def deep_strings(value, depth=0, seen=None):
    """값 안(목록·사전·객체 속성, 깊이 6까지)의 모든 글·바이트."""
    seen = set() if seen is None else seen
    if id(value) in seen or depth > 6:
        return
    seen.add(id(value))
    if isinstance(value, (str, bytes)):
        yield value
    elif isinstance(value, dict):
        for key, item in list(value.items()):
            yield from deep_strings(key, depth + 1, seen)
            yield from deep_strings(item, depth + 1, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in list(value):
            yield from deep_strings(item, depth + 1, seen)
    elif hasattr(value, "__dict__") and not callable(value):
        yield from deep_strings(vars(value), depth + 1, seen)


# ---- 1) 상수·문구 -----------------------------------------------------------------------------------------------------------------
class ConstantsAndTextTest(unittest.TestCase):
    def test_the_item_limit_is_the_value_the_operator_confirmed_and_the_reading_base_uses_the_same(self):
        self.assertEqual(style_view.MAX_ITEMS, 2)
        self.assertEqual(style_view.MAX_ITEMS, own_posts.MAX_FILES)
        self.assertEqual(style_view.FILE_SUFFIXES, own_posts.ALLOWED_SUFFIXES)
        self.assertEqual(style_view.PHASES, ("select", "running", "result"))

    def test_the_rows_are_the_nine_numbers_in_a_fixed_order_and_match_the_computation(self):
        self.assertEqual(tuple(key for key, _label, _kind in style_view.ROWS), style_stats.METRICS)
        self.assertEqual(len(style_view.ROWS), 9)

    def test_every_phrase_is_merged_into_the_shared_table_after_the_draft_phrases(self):
        for key, value in style_text.STYLE_T.items():
            self.assertEqual(text.T[key], value, key)
        source = (UI / "core" / "text.py").read_text(encoding="utf-8")
        self.assertIn("T.update(STYLE_T)", source)
        self.assertLess(source.index("T.update(DRAFT_T)"), source.index("T.update(STYLE_T)"))

    def test_no_promise_word_no_english_code_no_tilde_no_web_address_in_the_phrases(self):
        for key, value in style_text.STYLE_T.items():
            with self.subTest(key=key):
                for word in text.FORBIDDEN:
                    self.assertNotIn(word, value)
                self.assertNotRegex(value, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
                self.assertNotRegex(value, r"Traceback|Exception|Error\b")
                self.assertNotIn(TILDE, value)
                self.assertNotRegex(value, r"(?i)(https?|ftp)://|www[.]")

    def test_there_is_no_verdict_label_only_the_one_trust_sentence_names_what_the_numbers_are_not(self):
        verdicts = ("전문적", "전문성", "격식체", "비격식", "친근", "딱딱", "수준이", "좋은 글", "나쁜 글", "신뢰도", "점수", "등급", "추천", "진단", "성향", "성격이")
        for key, value in style_text.STYLE_T.items():
            if key == "style_trust":
                continue
            for word in verdicts:
                self.assertNotIn(word, value, f"{key}: 판정처럼 읽히는 말 {word}")
        self.assertEqual(text.T["style_trust"], TRUST, "숫자 옆 안내는 이 한 문장이다")

    def test_the_row_names_are_the_look_of_the_ending_and_say_nothing_about_the_writer(self):
        for key in ("style_row_end_formal", "style_row_end_polite", "style_row_end_plain"):
            self.assertIn("로 끝나는 문장", text.T[key])
        self.assertIn("끝나는 문장", text.T["style_row_end_other"])
        self.assertIn("‘…니다·…니까·…십시오’", text.T["style_row_end_formal"])
        self.assertIn("‘…요·…죠’", text.T["style_row_end_polite"])
        self.assertIn("‘…다’", text.T["style_row_end_plain"])

    def test_the_notice_and_range_sentences_are_the_ones_the_operator_expects(self):
        self.assertIn(RANGE_ONLY, text.T["style_range_only"])
        for key in style_stats.NOTICES:
            self.assertIn("style_notice_" + key, text.T)
        self.assertIn("style_notice_cp949", text.T)
        self.assertIn("직접 쓴 글만 골라 주세요", text.T["style_only_yours"])
        self.assertIn("저장하지 않", text.T["style_intro"])
        self.assertIn("AI", text.T["style_intro"])
        self.assertIn("창을 닫으면", text.T["style_intro"])

    def test_the_phrases_added_or_changed_by_n3afix_have_no_verdict_or_grading_word(self):
        """독립 검증의 판정 라벨 낱말 32종·N-3a 가 막던 낱말·평가 낱말(좋은·나쁜·정확·정상·권장·점수) 가운데 하나도 새 문구에 없다."""
        for key in N3AFIX_KEYS:
            for word in (*VERDICTS_N3A, *VERDICTS_AUDIT, *GRADING_WORDS):
                self.assertNotIn(word, text.T[key], f"{key}: {word}")
            self.assertNotIn(TILDE, text.T[key])

    def test_the_rough_note_names_the_sentence_split_the_sentence_end_and_the_numbers_that_can_be_off(self):
        """D-432 — `문장 끝` 만 말하던 한 줄을 문장 나누기와 문장 수·문단 수·질문형·목록 비율까지 말하게 넓혔다(한 줄 안내라 길지 않다)."""
        rough = text.T["style_rough"]
        for part in ("문장 나누기", "문장 끝", "글자 모양", "문장 수", "문단 수", "질문형", "목록 비율", "실제와 조금 다를 수 있어요"):
            self.assertIn(part, rough, part)
        self.assertLessEqual(len(rough), 80)

    def test_the_yours_line_keeps_the_sentence_about_other_peoples_and_ai_texts_of_the_picking_note(self):
        """D-434 — 결과 화면만 봐도 본인 글의 숫자가 아닐 수 있다는 것을 알게 하는 한 줄. 고르기 모습의 문장(부탁)과 같은 사실 문장을 쓴다."""
        tail = "다른 사람의 글이나 AI 가 쓴 글이면 이 숫자는 내 글의 모습이 아니에요."
        self.assertIn(tail, text.T["style_only_yours"])
        self.assertIn(tail, text.T["style_yours_result"])
        self.assertIn("직접 쓴 글만 골랐을 때의 숫자예요", text.T["style_yours_result"])
        self.assertNotIn("골라 주세요", text.T["style_yours_result"], "결과 모습의 문장은 부탁이 아니라 사실을 말한다")

    def test_the_wrap_notice_says_the_numbers_may_change_with_the_line_breaking_and_does_not_say_they_change_a_lot(self):
        """D-430 — 새 켜짐 조건(작은 차이도 포함)에 맞게 '크게 달라져요' 를 '달라질 수 있어요' 로 바로잡았다."""
        wrap = text.T["style_notice_wrap"]
        for part in ("줄바꿈 습관", "문장 수", "달라질 수 있어요"):
            self.assertIn(part, wrap)
        self.assertNotIn("크게", wrap)

    def test_a_pasted_column_header_says_it_is_pasted_and_the_other_headers_do_not(self):
        self.assertEqual(text.T["style_col_one_pasted"].format(n=2), "글 2 (붙여 넣음)")
        self.assertEqual(text.T["style_col_one"].format(n=2), "글 2")


# ---- 2) 숫자 서식 -----------------------------------------------------------------------------------------------------------------
class FormatTest(unittest.TestCase):
    def test_a_fraction_is_rounded_half_up_to_one_decimal(self):
        for value, shown in ((Fraction(0), "0.0"), (Fraction(1, 20), "0.1"), (Fraction(49, 1000), "0.0"), (Fraction(1303, 22), "59.2"), (Fraction(5, 2), "2.5"), (Fraction(999, 100), "10.0"), (Fraction(17, 4), "4.3"), (Fraction(41, 10), "4.1")):
            with self.subTest(value=value):
                self.assertEqual(style_view.fmt_tenth(value), shown)

    def test_a_percent_is_rounded_half_up_to_a_whole_number(self):
        for value, shown in ((Fraction(1, 3), "33"), (Fraction(2, 3), "67"), (Fraction(1, 2), "50"), (Fraction(1, 200), "1"), (Fraction(1, 201), "0"), (Fraction(1), "100"), (Fraction(0), "0")):
            with self.subTest(value=value):
                self.assertEqual(style_view.fmt_percent_number(value), shown)

    def test_each_kind_of_cell_has_its_unit_and_an_unknown_value_is_the_unknown_sentence(self):
        self.assertEqual(style_view.cell_text("tenth_chars", Fraction(1303, 22)), "59.2자")
        self.assertEqual(style_view.cell_text("tenth_sentences", Fraction(7, 2)), "3.5문장")
        self.assertEqual(style_view.cell_text("count", 5), "5개")
        self.assertEqual(style_view.cell_text("count", Fraction(9, 2)), "4.5개")
        self.assertEqual(style_view.cell_text("count", Fraction(8, 2)), "4개", "정수가 되는 분수는 정수로 보인다")
        self.assertEqual(style_view.cell_text("count", 0), "0개", "0 은 센 결과이다")
        self.assertEqual(style_view.cell_text("percent", Fraction(5, 8)), "63%")
        for kind in ("tenth_chars", "tenth_sentences", "count", "percent"):
            self.assertEqual(style_view.cell_text(kind, None), "알 수 없음")
        self.assertNotEqual(style_view.cell_text("count", None), style_view.cell_text("count", 0))

    def test_a_range_shows_one_value_when_both_ends_are_the_same_and_the_unit_once_otherwise(self):
        self.assertEqual(style_view.range_text("tenth_chars", Fraction(4), Fraction(9, 2)), "4.0–4.5자")
        self.assertEqual(style_view.range_text("percent", Fraction(2, 5), Fraction(4, 5)), "40–80%")
        self.assertEqual(style_view.range_text("percent", Fraction(1, 2), Fraction(1, 2)), "50%")
        self.assertEqual(style_view.range_text("count", 3, 3), "3개")
        self.assertEqual(style_view.range_text("count", 2, 5), "2–5개")


# ---- 3) 컨트롤러 ------------------------------------------------------------------------------------------------------------------
FILES = {"A.md": (P_MD, "md"), "B.txt": (Q_TXT_ONE_PARAGRAPH, "txt"), "C.txt": (Q_TXT_TWO_PARAGRAPHS, "txt")}


class ControllerTest(unittest.TestCase):
    def test_before_it_is_opened_nothing_can_be_done(self):
        study = StyleStudy(FakeStyleProvider(FILES))
        self.assertEqual(study.add_file("A.md"), "closed")
        self.assertEqual(study.start("글입니다.")[0], "closed")
        self.assertFalse(study.remove_file(0))
        self.assertEqual(study.provider.calls, [])

    def test_picking_a_file_asks_the_provider_with_all_chosen_files_and_adds_it(self):
        harness = Harness(FILES)
        self.assertEqual(harness.study.add_file("A.md"), "added")
        self.assertEqual(harness.study.add_file("B.txt"), "added")
        self.assertEqual(harness.study.paths, ["A.md", "B.txt"])
        self.assertEqual(harness.provider.calls, [("check_files", 1), ("check_files", 2)], "고를 때마다 지금까지 고른 것 전부를 함께 확인한다(같은 파일 두 번을 알아보려고)")

    def test_cancelling_the_file_dialog_never_calls_the_provider(self):
        harness = Harness(FILES)
        for empty in ("", None):
            self.assertEqual(harness.study.add_file(empty), "cancelled")
        self.assertEqual(harness.provider.calls, [])
        self.assertEqual(harness.study.paths, [])

    def test_the_third_choice_is_refused_and_nothing_is_read(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.study.add_file("B.txt")
        before = list(harness.provider.calls)
        self.assertEqual(harness.study.add_file("C.txt"), "full")
        self.assertEqual(harness.provider.calls, before)
        self.assertEqual(harness.study.message, text.T["style_pick_full"])

    def test_a_pasted_text_counts_as_one_of_the_two(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        self.assertEqual(harness.study.add_file("B.txt", pasted_chars=10), "full")
        self.assertEqual(harness.study.add_file("B.txt", pasted_chars=0), "added")
        self.assertEqual(harness.study.start("붙여 넣은 글입니다.")[0], "toomany")
        self.assertEqual(harness.study.message, text.T["style_fail_toomany"])

    def test_a_refused_file_is_not_added_and_the_sentence_is_the_providers_fixed_one(self):
        harness = Harness({**FILES, "bad.txt": ("가", "txt")}, refuse=("bad",))
        self.assertEqual(harness.study.add_file("bad.txt"), "refused")
        self.assertEqual(harness.study.paths, [])
        self.assertEqual(harness.study.message, "가짜 공급자의 고정 거절 문장이에요")
        self.assertEqual(harness.study.add_file("A.md"), "added")
        self.assertEqual(harness.study.message, "", "새로 더하면 지난 안내는 사라진다")

    def test_removing_a_file_works_only_for_a_real_index_while_choosing(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.study.add_file("B.txt")
        for bad in (-1, 2, 5, True, "0", None):
            self.assertFalse(harness.study.remove_file(bad), repr(bad))
        self.assertTrue(harness.study.remove_file(0))
        self.assertEqual(harness.study.paths, ["B.txt"])

    def test_start_without_anything_chosen_says_so_and_never_starts_a_job(self):
        harness = Harness(FILES)
        for pasted in ("", "   \n  ", None):
            box = harness.start(pasted)
            self.assertEqual(box["status"], "nothing")
        self.assertEqual(harness.study.message, text.T["style_none_yet"])
        self.assertEqual(harness.provider.calls, [])

    def test_a_refused_pasted_text_keeps_the_input_and_never_starts_a_job(self):
        harness = Harness(FILES)
        box = harness.start("x" * 100_001)
        self.assertEqual(box["status"], "refused")
        self.assertFalse(harness.study.running)
        self.assertEqual(harness.study.message, "가짜 공급자의 고정 거절 문장이에요")
        self.assertNotIn("compute", [call[0] for call in harness.provider.calls])

    def test_the_computation_runs_on_a_worker_thread_and_the_result_is_applied_once(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        box = harness.start()
        self.assertEqual(box["status"], "started")
        self.assertIsNot(box["thread"], threading.main_thread())
        self.assertTrue(harness.study.running)
        self.assertEqual(harness.study.phase, "running")
        result = box["result"]
        self.assertEqual((result.generation, harness.study.pending), (harness.study.generation, harness.study.generation))
        self.assertTrue(harness.study.apply(result))
        self.assertEqual(harness.study.phase, "result")
        self.assertFalse(harness.study.running)
        self.assertFalse(harness.study.apply(result), "같은 결과를 두 번 받지 않는다")

    def test_a_second_start_while_running_or_with_a_result_only_says_busy(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        gate = threading.Event()
        real = harness.provider.compute

        def slow(paths, pasted):
            gate.wait(10)
            return real(paths, pasted)

        harness.provider.compute = slow
        first = harness.start(wait=False)
        self.assertEqual(first["status"], "started")
        self.assertEqual(harness.study.start("")[0], "busy")
        self.assertEqual(harness.study.add_file("B.txt"), "busy")
        self.assertFalse(harness.study.remove_file(0))
        gate.set()
        self.assertTrue(first["done"].wait(10))
        harness.study.apply(first["result"])
        self.assertEqual(harness.study.start("")[0], "busy", "결과가 있는 동안에도 새로 시작하지 않는다(다시 하려면 reset)")

    def test_a_result_that_arrives_after_closing_resetting_or_reopening_is_dropped(self):
        for how in ("close", "reset", "open", "shutdown"):
            with self.subTest(how=how):
                harness = Harness(FILES)
                harness.study.add_file("A.md")
                old = harness.start()["result"]                     # 끝난 결과를 받지 않고 쥐고 있다가 세대가 바뀐 뒤에 넣어 본다
                getattr(harness.study, how)()
                self.assertFalse(harness.study.apply(old), "세대가 달라진 결과는 받지 않는다")
                self.assertIsNone(harness.study.outcome)
                self.assertFalse(harness.study.running)

    def test_a_job_that_is_cancelled_by_closing_delivers_a_cancel_not_a_result(self):
        for how in ("close", "reset", "open", "shutdown"):
            with self.subTest(how=how):
                harness = Harness(FILES)
                harness.study.add_file("A.md")
                gate = threading.Event()
                real = harness.provider.compute
                harness.provider.compute = lambda paths, pasted, real=real, gate=gate: (gate.wait(10), real(paths, pasted))[1]
                box = harness.start(wait=False)
                getattr(harness.study, how)()
                gate.set()
                self.assertTrue(box["done"].wait(10))
                self.assertTrue(box.get("cancel"))
                self.assertNotIn("result", box)
                self.assertFalse(harness.study.running)

    def test_the_generation_number_keeps_rising_across_openings_so_an_old_result_never_fits_a_new_window(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        old = harness.start()["result"]
        generations = [harness.study.generation]
        harness.study.close()
        harness.study.open()
        harness.study.add_file("A.md")
        gate = threading.Event()
        real = harness.provider.compute
        harness.provider.compute = lambda paths, pasted: (gate.wait(10), real(paths, pasted))[1]
        harness.start(wait=False)
        generations.append(harness.study.generation)
        self.assertEqual(generations, sorted(set(generations)), "번호는 늘 오른다")
        self.assertGreater(harness.study.generation, old.generation)
        self.assertFalse(harness.study.apply(old), "옛 창의 결과가 새 창의 계산인 척하지 않는다")
        gate.set()

    def test_open_close_reset_and_every_start_each_raise_the_generation_number_by_one(self):
        """번호가 오르는 자리가 넷이고 각각 따로 올라야 한다 — 한 자리가 빠져도 나머지 셋이 낡은 결과를 막아 주므로 겉으로는 안 드러난다. 그래서 번호 자체를 본다."""
        harness = Harness(FILES)
        study = harness.study
        for step in ("close", "open", "reset", "close", "open"):
            before = study.generation
            getattr(study, step)()
            self.assertEqual(study.generation, before + 1, step)
        study.add_file("A.md")
        before = study.generation
        harness.start()
        self.assertEqual(study.generation, before + 1, "start")

    def test_a_failure_of_an_older_run_is_dropped_even_while_a_newer_run_is_waiting_for_its_result(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        real = harness.provider.compute
        harness.provider.compute = lambda paths, pasted: (_ for _ in ()).throw(JobFailure("고정", code="CONTENT_INVALID"))
        old = harness.start()["failure"]
        harness.study.reset()
        harness.provider.compute = real
        harness.study.add_file("A.md")
        harness.start()                                                                  # 새 계산의 결과가 와 있지만 아직 받지 않았다 — 기다리는 계산이 있다
        self.assertIsNotNone(harness.study.pending)
        self.assertFalse(harness.study.apply_failed(old), "옛 계산의 실패는 새 계산을 기다리는 동안에도 받지 않는다")
        self.assertEqual(harness.study.message, "")
        self.assertIsNotNone(harness.study.pending)

    def test_a_failure_shows_the_fixed_sentence_only_for_the_current_run_and_keeps_the_chosen_files(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        real = harness.provider.compute

        def failing(paths, pasted):
            raise JobFailure("고정 거절 문장 하나예요", code="CONTENT_INVALID")

        harness.provider.compute = failing
        box = harness.start()
        self.assertTrue(harness.study.apply_failed(box["failure"]))
        self.assertEqual(harness.study.message, "고정 거절 문장 하나예요")
        self.assertEqual(harness.study.paths, ["A.md"])
        self.assertEqual(harness.study.phase, "select")
        self.assertFalse(harness.study.apply_failed(box["failure"]), "두 번 받지 않는다")
        harness.provider.compute = real

    def test_an_unexpected_error_text_never_reaches_the_screen_only_the_easy_sentence(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")

        def breaking(paths, pasted):
            raise RuntimeError(MARK + " 경로 C:/Users/누군가/글.txt")

        harness.provider.compute = breaking
        box = harness.start()
        self.assertTrue(harness.study.apply_failed(box["failure"]))
        self.assertEqual(harness.study.message, text.T["style_fail_other"])
        self.assertNotIn(MARK, repr(harness.study.view()))

    def test_a_failure_with_another_code_never_shows_its_own_message(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.provider.compute = lambda paths, pasted: (_ for _ in ()).throw(JobFailure(MARK + " 문장", code="OTHER_PROBLEM"))
        box = harness.start()
        harness.study.apply_failed(box["failure"])
        self.assertEqual(harness.study.message, text.T["style_fail_other"])

    def test_a_failure_of_a_closed_or_replaced_run_is_dropped(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.provider.compute = lambda paths, pasted: (_ for _ in ()).throw(JobFailure("고정", code="CONTENT_INVALID"))
        box = harness.start()
        harness.study.close()
        self.assertFalse(harness.study.apply_failed(box["failure"]))
        harness.study.open()
        self.assertFalse(harness.study.apply_failed(box["failure"]))
        self.assertEqual(harness.study.message, "")

    def test_unexpected_screen_trouble_returns_to_choosing_with_the_easy_sentence(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.finish()
        self.assertTrue(harness.study.apply_unexpected())
        self.assertEqual((harness.study.phase, harness.study.message, harness.study.paths), ("select", text.T["style_fail_other"], ["A.md"]))
        harness.study.close()
        self.assertFalse(harness.study.apply_unexpected())

    def test_closing_and_resetting_forget_everything(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.finish()
        harness.study.reset()
        self.assertEqual((harness.study.paths, harness.study.outcome, harness.study.pending, harness.study.message, harness.study.is_open), ([], None, None, "", True))
        harness.study.add_file("B.txt")
        harness.study.close()
        self.assertEqual((harness.study.paths, harness.study.outcome, harness.study.is_open), ([], None, False))
        harness.study.close()
        harness.study.shutdown()

    def test_cancel_notice_changes_nothing(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        before = dict(vars(harness.study))
        self.assertFalse(harness.study.apply_cancelled())
        self.assertEqual(dict(vars(harness.study)), before, "취소 알림은 어떤 상태도 바꾸지 않는다")

    def test_shutdown_closes_the_study_for_good(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.study.shutdown()
        self.assertEqual((harness.study.is_open, harness.study.paths, harness.study.running), (False, [], False))

    def test_a_file_cannot_be_added_while_a_result_is_showing_and_the_provider_is_not_asked(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.finish()
        self.assertEqual(harness.study.phase, "result")
        calls = list(harness.provider.calls)
        self.assertEqual(harness.study.add_file("B.md"), "busy")
        self.assertEqual(harness.provider.calls, calls)
        self.assertEqual(harness.study.paths, ["A.md"])

    def test_the_pasted_text_goes_to_the_job_as_a_value_and_the_state_does_not_keep_it(self):
        harness = Harness(FILES)
        pasted = MARK + " 입니다. 정말요?"
        box = harness.start(pasted)
        harness.study.apply(box["result"])
        state = {name: item for name, item in vars(harness.study).items() if name != "provider"}
        found = [value for value in deep_strings(state) if MARK in (value if isinstance(value, str) else value.decode("utf-8", "ignore"))]
        self.assertEqual(found, [], "붙여 넣은 글이 상태에 남지 않는다")
        self.assertIsNone(harness.study._job, "결과를 받으면 작업(과 그 안에 담긴 글)을 놓는다")
        self.assertEqual(harness.provider.calls[-1], ("compute", 0, True))
        self.assertEqual(len(harness.study.outcome.summary.items), 1)


# ---- 4) 뷰모델 --------------------------------------------------------------------------------------------------------------------
class ViewTest(unittest.TestCase):
    def test_the_choosing_view_has_the_buttons_in_their_states(self):
        harness = Harness(FILES)
        view = harness.study.view(0)
        self.assertEqual(view["phase"], "select")
        self.assertTrue(view["pick"]["enabled"])
        self.assertFalse(view["compute"]["enabled"], "고른 글이 없으면 계산하기는 꺼져 있다")
        self.assertEqual(view["status"], text.T["style_none_yet"])
        self.assertTrue(view["paste"]["enabled"])
        self.assertIsNone(view["result"])
        self.assertEqual(view["paste"]["count"], "0자")
        self.assertEqual(harness.study.view(1234)["paste"]["count"], "1234자")
        self.assertTrue(harness.study.view(5)["compute"]["enabled"], "붙여 넣은 글이 있으면 계산할 수 있다")

    def test_each_chosen_file_is_a_numbered_row_without_its_name_or_place(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.study.add_file("B.txt")
        view = harness.study.view(0)
        self.assertEqual([slot["label"] for slot in view["slots"]], ["글 1 · 파일에서 가져옴", "글 2 · 파일에서 가져옴"])
        self.assertEqual([slot["a11y"] for slot in view["slots"]], ["글 1 빼기", "글 2 빼기"])
        self.assertFalse(view["pick"]["enabled"], "둘을 골랐으면 더 고를 수 없다")
        self.assertFalse(view["paste"]["enabled"])
        self.assertNotIn("A.md", repr(view))
        self.assertNotIn("B.txt", repr(view))
        self.assertTrue(view["compute"]["enabled"])

    def test_a_pasted_text_takes_one_slot_so_only_one_more_file_can_be_chosen(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        self.assertFalse(harness.study.view(7)["pick"]["enabled"])
        self.assertTrue(harness.study.view(0)["pick"]["enabled"])

    def test_the_running_view_disables_everything_but_close_and_says_it_is_working(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        gate = threading.Event()
        real = harness.provider.compute
        harness.provider.compute = lambda paths, pasted: (gate.wait(10), real(paths, pasted))[1]
        harness.start(wait=False)
        view = harness.study.view(0)
        self.assertEqual(view["phase"], "running")
        self.assertEqual(view["status"], text.T["style_running"])
        self.assertEqual(view["status_a11y"], text.T["style_running_a11y"])
        self.assertFalse(view["pick"]["enabled"] or view["paste"]["enabled"] or view["compute"]["enabled"])
        gate.set()

    def test_one_text_has_one_column_and_no_range_or_total(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.finish()
        result = harness.study.view()["result"]
        self.assertEqual([column["text"] for column in result["columns"]], ["글 1"])
        row = {item["key"]: item for item in result["rows"]}
        self.assertEqual(row["sentence_length"]["cells"], ["4.5자"])
        self.assertEqual(row["per_paragraph"]["cells"], ["4.0문장"])
        self.assertEqual(row["headings"]["cells"], ["2개"])
        self.assertEqual([row[key]["cells"][0] for key in ("end_formal", "end_polite", "end_plain", "end_other")], ["25%", "50%", "25%", "0%"])
        self.assertEqual((row["question"]["cells"], row["list"]["cells"]), (["25%"], ["0%"]))
        for item in result["rows"]:
            self.assertEqual((item["range"], item["total"]), ("", ""))
        self.assertEqual(result["counts"], ["문장 4개 · 문단 1개 · 목록 0개 · 글자 18자(공백 뺀)"])
        self.assertEqual((result["range_only"], result["range_only_note"], result["total_note"]), (False, "", ""))
        self.assertEqual(result["trust"], TRUST)

    def test_two_calm_texts_show_both_columns_the_range_and_the_pooled_values(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.study.add_file("B.txt")
        harness.finish()
        result = harness.study.view()["result"]
        self.assertEqual([column["key"] for column in result["columns"]], ["item0", "item1", "range", "total"])
        self.assertEqual([column["text"] for column in result["columns"]], ["글 1", "글 2", "범위", "두 글 합산"])
        row = {item["key"]: item for item in result["rows"]}
        self.assertEqual((row["sentence_length"]["cells"], row["sentence_length"]["range"], row["sentence_length"]["total"]), (["4.5자", "4.0자"], "4.0–4.5자", "4.3자"), "합산은 (18+16)/(4+4)=4.25 → 반올림 4.3")
        self.assertEqual((row["per_paragraph"]["cells"], row["per_paragraph"]["total"]), (["4.0문장", "4.0문장"], "4.0문장"))
        self.assertEqual((row["headings"]["cells"], row["headings"]["range"], row["headings"]["total"]), (["2개", "알 수 없음"], "2개", "알 수 없음"))
        self.assertEqual((row["end_formal"]["cells"], row["end_formal"]["range"], row["end_formal"]["total"]), (["25%", "25%"], "25%", "25%"))
        self.assertEqual((row["end_polite"]["cells"], row["end_polite"]["total"]), (["50%", "50%"], "50%"))
        self.assertEqual(result["total_note"], text.T["style_total_note"])
        self.assertFalse(result["range_only"])
        self.assertEqual(len(result["counts"]), 2)
        self.assertTrue(result["counts"][0].startswith("글 1 — 문장 4개"))

    def test_two_texts_that_differ_a_lot_show_only_the_range_and_say_so(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.study.add_file("C.txt")
        harness.finish()
        result = harness.study.view()["result"]
        self.assertTrue(result["range_only"])
        self.assertEqual([column["key"] for column in result["columns"]], ["item0", "item1", "range"], "합산 열이 없다")
        self.assertIn(RANGE_ONLY, result["range_only_note"])
        self.assertEqual(result["total_note"], "")
        for item in result["rows"]:
            self.assertEqual(item["total"], "")
        row = {item["key"]: item for item in result["rows"]}
        self.assertEqual(row["per_paragraph"]["range"], "1.0–4.0문장")

    def test_the_headings_total_is_the_average_per_text_when_both_are_known(self):
        files = {"A.md": ("## a\n\n저는 갑니다. 좋아요.", "md"), "B.md": ("## a\n\n## b\n\n## c\n\n저는 갑니다. 좋아요.", "md")}
        harness = Harness(files)
        harness.study.add_file("A.md")
        harness.study.add_file("B.md")
        harness.finish()
        row = {item["key"]: item for item in harness.study.view()["result"]["rows"]}
        self.assertEqual((row["headings"]["cells"], row["headings"]["range"], row["headings"]["total"]), (["1개", "3개"], "1–3개", "2개"))

    def test_two_text_form_files_show_unknown_headings_in_every_column_including_the_range_and_the_total(self):
        harness = Harness({"T1.txt": (Q_TXT_ONE_PARAGRAPH, "txt"), "T2.txt": (Q_TXT_ONE_PARAGRAPH, "txt")})
        harness.study.add_file("T1.txt")
        harness.study.add_file("T2.txt")
        harness.finish()
        result = harness.study.view()["result"]
        row = {item["key"]: item for item in result["rows"]}
        self.assertEqual((row["headings"]["cells"], row["headings"]["range"], row["headings"]["total"]), (["알 수 없음", "알 수 없음"], "알 수 없음", "알 수 없음"))
        self.assertFalse(result["range_only"])

    def test_a_text_with_nothing_to_count_shows_unknown_not_zero(self):
        harness = Harness({"E.md": ("![그림](a.png)", "md")})
        harness.study.add_file("E.md")
        harness.finish()
        result = harness.study.view()["result"]
        row = {item["key"]: item for item in result["rows"]}
        for key in ("sentence_length", "per_paragraph", "end_formal", "end_polite", "end_plain", "end_other", "question", "list"):
            self.assertEqual(row[key]["cells"], ["알 수 없음"], key)
        self.assertEqual(row["headings"]["cells"], ["0개"], "제목 표시가 있는 형식이라 0 은 센 결과이다")
        self.assertEqual(result["notes"], [text.T["style_notice_empty"]])

    def test_a_text_form_has_unknown_headings_and_a_markdown_one_does_not(self):
        harness = Harness({"T.txt": ("## 가\n\n저는 갑니다.", "txt")})
        harness.study.add_file("T.txt")
        harness.finish()
        row = {item["key"]: item for item in harness.study.view()["result"]["rows"]}
        self.assertEqual(row["headings"]["cells"], ["알 수 없음"])

    def test_notes_name_the_text_when_there_are_two_and_do_not_when_there_is_one(self):
        one = Harness({"S.txt": ("갑니다.", "txt")})
        one.study.add_file("S.txt")
        one.finish()
        self.assertEqual(one.study.view()["result"]["notes"], [text.T["style_notice_short"]])
        two = Harness({"S.txt": ("갑니다.", "txt"), "L.txt": (" ".join(["가" * 60 + "."] * 10), "txt")})
        two.study.add_file("S.txt")
        two.study.add_file("L.txt")
        two.finish()
        self.assertEqual(two.study.view()["result"]["notes"], ["글 1 — " + text.T["style_notice_short"]])

    def test_the_cp949_note_follows_the_text_that_was_read_that_way(self):
        class Cp949(FakeStyleProvider):
            def compute(self, paths, pasted):
                summary, _cp949, pasted_flags = super().compute(paths, pasted)
                return summary, (False, True), pasted_flags

        harness = Harness(provider=Cp949(FILES))
        harness.study.add_file("A.md")
        harness.study.add_file("B.txt")
        harness.finish()
        notes = harness.study.view()["result"]["notes"]
        self.assertIn("글 2 — " + text.T["style_notice_cp949"], notes)
        self.assertEqual(len([note for note in notes if "CP949" in note]), 1)

    def test_every_row_has_an_accessible_sentence_with_its_name_and_cells(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.study.add_file("B.txt")
        harness.finish()
        result = harness.study.view()["result"]
        for row in result["rows"]:
            self.assertIn(row["label"], row["a11y"])
            for cell in row["cells"]:
                self.assertIn(cell, row["a11y"])
            self.assertIn("범위", row["a11y"])
            self.assertIn("두 글 합산", row["a11y"])
        self.assertEqual(result["a11y"], text.T["style_result_a11y"])

    def test_the_result_has_the_yours_line_and_the_wider_rough_note_for_one_and_two_texts(self):
        for names in (("A.md",), ("A.md", "B.txt")):
            with self.subTest(names=names):
                harness = Harness(FILES)
                for name in names:
                    harness.study.add_file(name)
                harness.finish()
                result = harness.study.view()["result"]
                self.assertEqual(result["yours"], text.T["style_yours_result"])
                self.assertEqual(result["rough"], text.T["style_rough"])
                self.assertEqual(result["trust"], TRUST, "숫자 옆 안내 문장은 그대로 하나다")

    def test_a_pasted_text_is_marked_in_its_column_header_and_in_the_spoken_row_names(self):
        """D-434 — 파일이 먼저, 붙여 넣은 글이 맨 뒤라는 고르기 모습의 순서와 같게 결과 열 머리에 `(붙여 넣음)` 이 붙는다."""
        pasted = "갑니다. 정말요? 좋아요. 끝났다."
        both = Harness(FILES)
        both.study.add_file("A.md")
        both.finish(pasted)
        self.assertEqual(both.study.outcome.pasted, (False, True))
        result = both.study.view()["result"]
        self.assertEqual([column["text"] for column in result["columns"]], ["글 1", "글 2 (붙여 넣음)", "범위", "두 글 합산"])
        for row in result["rows"]:
            self.assertIn("글 1 " + row["cells"][0], row["a11y"])
            self.assertIn("글 2 (붙여 넣음) " + row["cells"][1], row["a11y"])
        alone = Harness(FILES)
        alone.finish(pasted)
        self.assertEqual(alone.study.outcome.pasted, (True,))
        self.assertEqual([column["text"] for column in alone.study.view()["result"]["columns"]], ["글 1"], "열이 하나뿐이면 구별할 열이 없어 붙여 넣은 글 하나여도 머리는 그대로다")
        files_only = Harness(FILES)
        files_only.study.add_file("A.md")
        files_only.study.add_file("B.txt")
        files_only.finish()
        self.assertEqual([column["text"] for column in files_only.study.view()["result"]["columns"]], ["글 1", "글 2", "범위", "두 글 합산"], "파일뿐이면 머리는 그대로다")

    def test_the_headers_follow_the_order_of_the_texts_when_the_pasted_text_would_be_first_in_the_flags(self):
        """머리는 `outcome.pasted` 의 칸 순서를 그대로 따른다(어댑터가 파일을 먼저, 붙여 넣은 글을 맨 뒤에 두므로 실제로는 늘 맨 뒤)."""
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.study.add_file("B.txt")
        harness.finish()
        outcome = harness.study.outcome
        for flags, expected in (((True, False), ["글 1 (붙여 넣음)", "글 2"]), ((False, True), ["글 1", "글 2 (붙여 넣음)"]), ((True, True), ["글 1 (붙여 넣음)", "글 2 (붙여 넣음)"]), ((), ["글 1", "글 2"])):
            harness.study.outcome = style_view.StyleOutcome(outcome.generation, outcome.summary, outcome.cp949, flags)
            self.assertEqual([column["text"] for column in harness.study.view()["result"]["columns"]][:2], expected, flags)

    def test_the_view_holds_no_text_of_the_input_and_no_verdict(self):
        files = {"M.md": (f"# 제목\n\n## {MARK} 소제목\n\n{MARK} 입니다. 이 문장은 {MARK} 를 담고 있습니다.\n\n> 인용 {MARK}\n\n- {MARK} 목록", "md")}
        harness = Harness(files)
        harness.study.add_file("M.md")
        harness.finish()
        shown = repr(harness.study.view(0))
        for piece in (MARK, MARK[:8], "UNIQ-STY"):
            self.assertNotIn(piece, shown)
        for word in ("전문적", "격식체", "비격식", "친근"):
            self.assertNotIn(word, shown)

    def test_numbers_only_in_the_cells_and_known_phrases_everywhere_else(self):
        harness = Harness(FILES)
        harness.study.add_file("A.md")
        harness.finish()
        result = harness.study.view()["result"]
        for row in result["rows"]:
            for cell in row["cells"]:
                self.assertRegex(cell, r"^(\d+(\.\d)?(자|문장|개|%)|알 수 없음)$")


# ---- 5) 실제 공급자 ---------------------------------------------------------------------------------------------------------------
class AdapterTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="style-adapter-")
        self.addCleanup(holder.cleanup)
        self.root = Path(os.path.realpath(holder.name))
        self.provider = style_adapter.ServiceStyleProvider()

    def put(self, name, data):
        path = self.root / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)

    def refusal(self, call, *args):
        try:
            call(*args)
        except StyleRefusal as refusal:
            return refusal
        self.fail("거절되지 않았다")

    def test_a_good_file_and_a_good_pasted_text_pass_the_check(self):
        self.provider.check_files([self.put("a.md", P_MD), self.put("b.txt", Q_TXT_ONE_PARAGRAPH)])
        self.provider.check_pasted("붙여 넣은 글입니다.")

    def test_every_refusal_is_the_reading_bases_fixed_sentence_without_the_path_the_name_or_the_text(self):
        secret = "고유이름-w5p2m8"
        good = self.put(secret + ".txt", MARK + " 입니다.")
        cases = {"missing": [str(self.root / (secret + "-없음.txt"))], "suffix": [self.put(secret + ".docx", "글")], "same": [good, good], "relative": [secret + ".txt"], "count": [good, good, good],
                 "empty": [self.put(secret + "-빈.txt", " \n")], "binary": [self.put(secret + "-바이너리.txt", MARK.encode("utf-8") + b"\x00")]}
        for label, paths in cases.items():
            with self.subTest(label=label):
                refusal = self.refusal(self.provider.check_files, paths)
                self.assertIn("기존 글 파일 — ", refusal.message)
                for piece in (secret, MARK, str(self.root), self.root.name):
                    self.assertNotIn(piece, refusal.message)
                    self.assertNotIn(piece, repr(refusal))
                self.assertIsNone(refusal.__cause__)
                self.assertIsNone(refusal.__context__, "앞 오류가 따라붙지 않는다")

    def test_the_pasted_text_refusals_are_the_reading_bases_sentences_too(self):
        for build, key in ((lambda: "", "읽을 글이 없어요"), (lambda: "a\x00b", "글 파일이 아닌 것 같아요"), (lambda: "x" * 100_001, "글이 너무 길어요")):
            refusal = self.refusal(self.provider.check_pasted, build())
            self.assertIn(key, refusal.message)
            self.assertIsNone(refusal.__context__)

    def test_the_form_is_decided_by_the_extension_of_the_chosen_path(self):
        md, txt = self.put("a.MD", "# 제목\n\n## 소제목\n\n저는 갑니다. 정말요?"), self.put("b.txt", "## 소제목\n\n저는 갑니다. 정말요?")
        summary, cp949, pasted = self.provider.compute([md, txt], "")
        self.assertEqual([stats.headings for stats in summary.items], [1, None])
        self.assertEqual((cp949, pasted), ((False, False), (False, False)))

    def test_pasted_text_comes_last_and_is_flagged(self):
        a = self.put("a.txt", "저는 갑니다. 정말요?")
        summary, cp949, pasted = self.provider.compute([a], "붙여 넣은 글입니다.")
        self.assertEqual((len(summary.items), cp949, pasted), (2, (False, False), (False, True)))
        summary, _cp949, pasted = self.provider.compute([], "붙여 넣은 글입니다.")
        self.assertEqual((len(summary.items), pasted), (1, (True,)))
        self.assertEqual(self.provider.compute([a], "   ")[2], (False,), "공백뿐인 붙여 넣기는 글이 아니다")

    def test_a_cp949_file_is_flagged_so_the_screen_can_say_how_it_was_read(self):
        path = self.put("c.txt", "오늘은 날씨가 좋습니다. 산책을 했어요.".encode("cp949"))
        _summary, cp949, _pasted = self.provider.compute([path], "")
        self.assertEqual(cp949, (True,))

    def test_more_than_two_texts_is_refused_by_the_adapter_itself_with_a_fixed_sentence(self):
        a, b = self.put("a.md", P_MD), self.put("b.txt", Q_TXT_ONE_PARAGRAPH)
        with self.assertRaises(JobFailure) as caught:
            self.provider.compute([a, b], "붙여 넣은 글입니다.")
        self.assertEqual((caught.exception.code, caught.exception.user_message), ("CONTENT_INVALID", text.T["style_fail_toomany"]))

    def test_a_file_that_vanishes_before_the_count_is_a_fixed_failure_without_the_path(self):
        path = self.put("gone.txt", "저는 갑니다.")
        os.remove(path)
        with self.assertRaises(JobFailure) as caught:
            self.provider.compute([path], "")
        failure = caught.exception
        self.assertEqual(failure.code, "CONTENT_INVALID")
        self.assertIn("기존 글 파일 — ", failure.user_message)
        for piece in ("gone", str(self.root), self.root.name):
            self.assertNotIn(piece, failure.user_message)
        self.assertIsNone(failure.__context__)

    def test_the_provider_writes_nothing_and_opens_only_the_chosen_files_for_reading(self):
        a, b = self.put("a.md", P_MD), self.put("b.txt", Q_TXT_ONE_PARAGRAPH)
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        mtimes = {path.name: path.stat().st_mtime_ns for path in self.root.iterdir()}
        real_open = builtins.open
        opened = []

        def watching(file, mode="r", *args, **kwargs):
            opened.append((os.fspath(file), mode))
            if mode != "rb":
                raise AssertionError(f"읽기가 아닌 열기: {mode}")
            return real_open(file, mode, *args, **kwargs)

        with mock.patch("builtins.open", watching):
            self.provider.check_files([a, b])
            self.provider.check_pasted("글입니다.")
            self.provider.compute([a], "붙여 넣은 글입니다.")
            self.provider.compute([a, b], "")
        self.assertTrue(opened)
        self.assertTrue(all(mode == "rb" and path in (a, b) for path, mode in opened), opened)
        self.assertEqual({path.name: path.read_bytes() for path in self.root.iterdir()}, before)
        self.assertEqual({path.name: path.stat().st_mtime_ns for path in self.root.iterdir()}, mtimes)

    def test_the_whole_flow_with_the_real_provider_gives_numbers_and_leaves_nothing_behind(self):
        a = self.put("a.md", P_MD)
        study = StyleStudy(self.provider)
        study.open()
        self.assertEqual(study.add_file(a), "added")
        harness = Harness(provider=self.provider, opened=False)
        harness.study = study
        harness.finish("붙여 넣은 글입니다. 정말요?")
        result = study.view()["result"]
        self.assertGreaterEqual(len(result["columns"]), 3)
        self.assertEqual(result["rows"][0]["cells"][0], "4.5자")
        study.close()
        self.assertIsNone(study.outcome)


# ---- 5-2) 오류의 호출 흔적 -------------------------------------------------------------------------------------------------------
class ErrorFramesTest(unittest.TestCase):
    """오류를 쥐고 있는 쪽이 호출 흔적의 지역 변수(`frame.f_locals`)·작업의 닫힘(클로저)으로 글·위치를 읽을 수 없다 — 거절·실패 어느 쪽도."""
    MARK = "고유표지문장zq7k3j9x다른낱말r4t6y8입니다"

    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="style-frames-")
        self.addCleanup(holder.cleanup)
        self.root = Path(os.path.realpath(holder.name))
        self.provider = style_adapter.ServiceStyleProvider()
        self.text_probes = leak.needles(self.MARK, size=8)
        self.probes = self.text_probes + leak.needles("고유파일이름a1b2c3d4", size=8)                  # 글 조각 + 파일 이름 조각

    def test_a_refused_check_keeps_no_path_or_text_in_the_error_or_its_frames(self):
        named = self.root / "고유파일이름a1b2c3d4.docx"
        named.write_text(self.MARK, encoding="utf-8")
        refusals = []
        for call, argument in ((self.provider.check_files, [str(named)]), (self.provider.check_pasted, self.MARK + "\x00" + self.MARK), (self.provider.check_pasted, (self.MARK + " ") * 6000)):
            try:
                call(argument)
            except StyleRefusal as refusal:
                refusals.append(refusal)
        self.assertEqual(len(refusals), 3)
        for refusal in refusals:
            self.assertEqual(leak.error_hits(refusal, self.probes), [])

    def test_the_adapter_lets_go_of_the_call_trace_of_the_service_error_in_all_three_places(self):
        """오류 객체를 시험이 쥐고 있어도 어댑터가 고정 문장을 꺼낸 뒤 그 호출 흔적을 비웠다 — 흔적이 붙드는 지역 변수(경로·글)가 남지 않는다."""
        try:
            own_posts.check_pasted_text("")
        except AppError as caught:
            held = caught
        places = (
            ("check_files", "read_own_files", lambda: self.provider.check_files(["x.md"]), StyleRefusal),
            ("check_pasted", "check_pasted_text", lambda: self.provider.check_pasted("글입니다."), StyleRefusal),
            ("compute", "read_own_files", lambda: self.provider.compute(["x.md"], ""), JobFailure),
        )

        def raising(*args, **kwargs):
            raise held

        for name, patched, call, expected in places:
            with self.subTest(place=name):
                with mock.patch.object(own_posts, patched, side_effect=raising):
                    with self.assertRaises(expected):
                        call()
                self.assertIsNone(held.__traceback__, "서비스 오류의 호출 흔적을 비우지 않았다")

    def test_a_failed_computation_keeps_no_path_or_text_in_the_failure_its_frames_or_the_job(self):
        named = self.root / "고유파일이름a1b2c3d4.txt"
        named.write_text(self.MARK + " 입니다.", encoding="utf-8")
        study = StyleStudy(self.provider)
        study.open()
        self.assertEqual(study.add_file(str(named)), "added")
        os.remove(named)
        harness = Harness(provider=self.provider, opened=False)
        harness.study = study
        box = harness.start(self.MARK + " 붙여 넣은 글입니다.")
        failure = box["failure"]
        self.assertEqual(leak.error_hits(failure, self.probes, skip=(study,)), [], "작업 오류의 호출 흔적·닫힘에 글과 위치가 없다(컨트롤러가 고른 위치를 쥐고 있는 것은 설계다 — 컨트롤러만 따라가지 않는다)")
        self.assertEqual(leak.graph_hits(box["job"], self.probes, skip=(study,)), [], "끝난 작업(그 안의 닫힘)에도 없다")
        self.assertTrue(study.apply_failed(failure))
        self.assertEqual(leak.graph_hits(study, self.text_probes), [], "컨트롤러 상태에 글은 없다")
        self.assertEqual(leak.graph_hits(study.view(0), self.probes), [], "뷰모델에는 글도 파일 이름도 없다")
        self.assertIn("기존 글 파일 — ", study.message)

    def test_a_good_computation_leaves_nothing_in_the_job_or_the_state(self):
        named = self.root / "고유파일이름a1b2c3d4.md"
        named.write_text("# 제목\n\n" + self.MARK + " 입니다.", encoding="utf-8")
        study = StyleStudy(self.provider)
        study.open()
        study.add_file(str(named))
        harness = Harness(provider=self.provider, opened=False)
        harness.study = study
        box = harness.start(self.MARK + " 붙여 넣은 글입니다.")
        self.assertEqual(leak.graph_hits(box["job"], self.probes, skip=(study,)), [], "작업의 닫힘 칸은 읽고 난 뒤 비어 있다")
        self.assertTrue(study.apply(box["result"]))
        self.assertEqual(leak.graph_hits(study, self.text_probes), [])
        self.assertEqual(leak.graph_hits(study.view(0), self.probes), [])
        self.assertEqual(leak.graph_hits(box["result"], self.probes), [])


# ---- 6) 소스 규칙 ----------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    @staticmethod
    def parse(path):
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    @staticmethod
    def imports(tree, top_level_only=False):
        nodes = tree.body if top_level_only else list(ast.walk(tree))
        found = []
        for node in nodes:
            if isinstance(node, ast.Import):
                found += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                found.append("." * node.level + (node.module or ""))
        return found

    def test_the_core_files_never_import_a_service_a_profile_a_store_or_a_gui_toolkit(self):
        banned = ("service", "publish", "render", "assist", "topicdb", "security", "topics", "profiles", "blog_profiles", "channels", "context", "store", "journal", "connections", "PySide6", "shiboken6")
        for path in NEW_CORE:
            for name in self.imports(self.parse(path)):
                with self.subTest(file=path.name, module=name):
                    self.assertFalse(any(part in banned for part in re.split(r"[./]", name)), name)

    def test_the_heavy_module_is_loaded_late_in_the_core_view(self):
        top = self.imports(self.parse(UI / "core" / "style_view.py"), top_level_only=True)
        self.assertEqual(sorted(top), sorted(["__future__", "dataclasses", "fractions", ".jobs", ".text"]))
        late = [name for name in self.imports(self.parse(UI / "core" / "style_view.py")) if name not in top]
        self.assertEqual(sorted(set(late)), ["...content"])

    def test_the_adapter_reaches_the_service_and_the_computation_only_late_and_calls_four_functions(self):
        tree = self.parse(UI / "style_adapter.py")
        top = self.imports(tree, top_level_only=True)
        self.assertEqual(sorted(top), sorted(["__future__", "..errors", ".core.jobs", ".core.style_view", ".core.text"]))
        late = sorted(set(name for name in self.imports(tree) if name not in top))
        self.assertEqual(late, ["..content", "..service"])
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        used = sorted(call for call in calls if call.startswith(("own_posts.", "style_stats.")))
        self.assertEqual(used, ["own_posts.check_pasted_text", "own_posts.read_own_files", "style_stats.analyze", "style_stats.summarize"])
        for forbidden in ("open", "print", "write", "write_text", "write_bytes", "mkdir", "unlink", "remove", "rename", "replace", "system", "popen"):
            self.assertFalse([call for call in calls if call == forbidden or call.endswith("." + forbidden)], forbidden)

    def test_the_new_files_have_no_write_network_clock_or_random_call_and_no_logging(self):
        banned_calls = {"open", "print", "exec", "eval", "compile", "input", "__import__"}
        banned_modules = {"os", "sys", "time", "random", "datetime", "socket", "urllib", "http", "subprocess", "shutil", "tempfile", "logging", "json", "sqlite3", "pathlib", "io", "ctypes", "threading"}
        for path in NEW_FILES:
            tree = self.parse(path)
            with self.subTest(file=path.name):
                names = {name.split(".")[0].lstrip(".") for name in self.imports(tree)}
                self.assertEqual(names & banned_modules, set(), path.name)
                calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
                self.assertEqual(calls & banned_calls, set())
                self.assertEqual({call for call in calls if call.rsplit(".", 1)[-1] in ("write_text", "write_bytes", "unlink", "mkdir", "rmdir", "rename", "replace", "remove", "rmtree", "copy", "copyfile", "move", "touch", "chmod")}, set())

    def test_the_new_files_set_no_clipboard_and_save_nothing(self):
        for path in NEW_FILES:
            source = path.read_text(encoding="utf-8")
            for word in ("clipboard", "QSettings", "QFileDialog", "write_json", "make_context", "settings.json", "channel_profiles", "naver_profiles"):
                self.assertNotIn(word, source, f"{path.name}: {word}")

    def test_the_text_and_comments_of_the_new_files_have_no_tilde_and_no_web_address(self):
        for path in NEW_FILES:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn(TILDE, source, path.name)
            self.assertNotRegex(source, r"(?i)(https?|ftp)://|www[.]", path.name)

    def test_no_secret_word_and_no_error_code_string_in_the_new_files(self):
        words = re.compile(r"(?i)(?<![A-Za-z0-9_])(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?(?![A-Za-z0-9_])")
        for path in NEW_FILES:
            for node in ast.walk(self.parse(path)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(words.search(node.value), (path.name, node.value[:40]))
        self.assertNotIn("AppError(", (UI / "style_adapter.py").read_text(encoding="utf-8"), "새 오류 코드를 만들지 않는다")

    def test_the_text_file_is_pure_data(self):
        tree = self.parse(UI / "core" / "style_text.py")
        self.assertEqual([type(node).__name__ for node in tree.body], ["Expr", "ImportFrom", "Assign"])


# ---- 7) 안전 증명(순수 층) --------------------------------------------------------------------------------------------------------
class NothingElseIsTouchedTest(unittest.TestCase):
    """프로필·설정·보관함·데이터 폴더·네트워크를 읽지도 쓰지도 않는다 — 부르면 시험이 깨지게 막아 두고 전체 흐름을 돌린다."""

    def test_the_whole_flow_never_reaches_settings_profiles_stores_or_the_network(self):
        from chanceblog_desktop.service import context
        holder = tempfile.TemporaryDirectory(prefix="style-data-")
        self.addCleanup(holder.cleanup)
        data = Path(os.path.realpath(holder.name))
        (data / "settings.json").write_text('{"naver_profiles": {}}', encoding="utf-8")
        (data / "topic_engine").mkdir()
        (data / "topic_engine" / "channel_profiles.json").write_text("{}", encoding="utf-8")
        (data / "posts.sqlite3").write_bytes(b"\x00" * 64)
        before = {str(path.relative_to(data)): (path.read_bytes(), path.stat().st_mtime_ns) for path in data.rglob("*") if path.is_file()}
        chosen = tempfile.TemporaryDirectory(prefix="style-chosen-")
        self.addCleanup(chosen.cleanup)
        source = Path(os.path.realpath(chosen.name)) / "style-flow.txt"
        source.write_text("저는 오늘 갑니다. 정말요? 좋아요.", encoding="utf-8")

        def forbidden(*args, **kwargs):
            raise AssertionError("프로필·설정·보관함·네트워크를 건드렸다")

        import socket
        with mock.patch.dict(os.environ, {"CHANCEBLOG_DESKTOP_DATA": str(data)}), mock.patch.object(context, "make_context", forbidden), mock.patch.object(context, "write_json", forbidden), \
                mock.patch.object(socket, "socket", forbidden), mock.patch.object(socket, "create_connection", forbidden):
            harness = Harness(provider=style_adapter.ServiceStyleProvider(), opened=False)
            harness.study.open()
            self.assertEqual(harness.study.add_file(str(source)), "added")
            harness.finish("붙여 넣은 글입니다.")
            self.assertEqual(harness.study.phase, "result")
            harness.study.close()
        after = {str(path.relative_to(data)): (path.read_bytes(), path.stat().st_mtime_ns) for path in data.rglob("*") if path.is_file()}
        self.assertEqual(after, before, "데이터 폴더의 바이트·수정 시각이 그대로다")

    def test_nothing_is_printed_logged_or_warned(self):
        out, err = io.StringIO(), io.StringIO()
        harness = Harness(FILES)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertNoLogs(level="DEBUG"):
            harness.study.add_file("A.md")
            harness.study.add_file("bad.txt")
            harness.finish()
            harness.study.view()
            harness.study.close()
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))


if __name__ == "__main__":
    unittest.main()
