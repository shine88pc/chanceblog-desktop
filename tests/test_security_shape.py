"""키 값·이름 모양 검사 시험(`security/shape.py`) — 비밀이 입력 오류 문구에 새지 않고, 붙여 넣기 실수와 키처럼 생긴 이름이 걸러진다.

지키는 것:
  1) `has_hidden_char`·`value_problem`: 공백·개행·NBSP·폭 없는 글자·방향 제어·제어 문자·사용자 지정/미배정 글자·짝 없는 대용 문자가 하나라도 있으면 거절하고, 허용 글자(영문·숫자와 `_ - + / = . ~ :`)
     밖의 글자(따옴표·괄호류·역슬래시·한글·전각 영문 …)도 각각 거절한다. 길이 경계(같으면 통과, 한 글자 모자라거나 넘치면 거절)와 비 문자열을 본다. **어떤 이유 문구에도 입력값이 없다.**
  2) `label_problem`: 이름·소속 프로젝트 칸 — 앞뒤·연속 공백, 줄바꿈, 길이 경계, 키처럼 보이는 글을 거절하고 평범한 이름은 통과한다.
  3) `looks_secret`: 알려진 접두사(Google·GitHub·Slack·AWS·sk-·JWT·개인 키 블록·텔레그램 …) × 이웃 글자(한글·괄호·따옴표·줄바꿈 …) 전수 — 낱말 경계에 기대지 않고 어디에 붙어도 잡는다. 접두사만 있고 뒤가 짧으면 아니고,
     24자 이상 영문·숫자 덩어리(영문자와 숫자가 섞인 것)는 맞다. 긴 입력은 선형 시간으로 처리하고, 너무 긴 입력은 믿지 않고 참이다.
  4) `short_digest`: 값이 해시·문구에 보이지 않는다(끝 4자 표시 `tail_hint` 는 PCSEC1 H2 로 없앴다). 값 전체의 지문(`fingerprint`)은 없다 — 약한 값을 해시만으로 대입해 알아낼 수 있어서 만들지 않는다. 고정 시드의 무작위 입력 몇 백 개에도 예외가 없다.
가짜 키 모양은 실행할 때 조각을 이어 붙여 만든다(저장소의 시험이 `.py` 안의 키 모양 문자열을 막는다). 네트워크·실제 비밀 없이 돈다.
"""
import random
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.security import shape  # noqa: E402

LIMIT_SECONDS = 2.5               # 30만 자 입력의 시간 상한(느린 CI 에서도 넉넉하게)
HIDDEN_REASON = "공백·줄바꿈·눈에 안 보이는 글자가 들어 있습니다(앞뒤 공백도 안 됩니다)"
CHARSET_REASON = "영문·숫자와 _ - + / = . ~ : 만 쓸 수 있습니다(따옴표·괄호·한글·붙여 넣은 설명 글이 섞이지 않았는지 확인합니다)"
SECRET_LOOKING_REASON = "키나 토큰처럼 보이는 글이 들어 있습니다(이름에는 키를 적지 않습니다)"
LABEL_HIDDEN_REASON = "줄바꿈·눈에 안 보이는 글자가 들어 있습니다"
LABEL_SPACING_REASON = "앞뒤 공백이나 연속된 공백이 있습니다"
NOT_TEXT_REASON = "글이 아닙니다"

# (이름, 접두사, 꼬리 글자, 꼬리의 가장 짧은 길이) — 접두사 바로 뒤에 이 글자가 이만큼 이어지면 비밀 모양이다. 조각을 이어 붙여 저장소에는 키 문자열이 없다.
PREFIX_SHAPES = (
    ("Google API 키", "AI" + "za", "A", 10),
    ("Google API 키(새 형식)", "AQ" + ".", "b", 10),
    ("Google OAuth 클라이언트 비밀", "GOC" + "SPX-", "c", 8),
    ("Google refresh token", "1/" + "/0", "d", 10),
    ("Google access token", "ya" + "29.", "e", 10),
    ("GitHub 토큰", "gh" + "p_", "f", 10),
    ("GitHub PAT", "github_" + "pat_", "g", 10),
    ("Slack 토큰", "xo" + "xb-", "h", 6),
    ("AWS 액세스 키", "AK" + "IA", "D", 8),
    ("sk- 형식 키", "s" + "k-", "i", 12),
)


def sample_shapes():
    """이웃 글자 시험에 쓰는 비밀 모양 표본(이름 → 글) — 모두 넉넉한 길이로 만든다."""
    found = {name: head + tail * (minimum + 20) for name, head, tail, minimum in PREFIX_SHAPES}
    found["JWT"] = "ey" + "J" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12
    found["개인 키 블록"] = "-----" + "BEGIN " + "PRIVATE KEY-----"
    found["텔레그램 봇 토큰"] = "123456789:" + "AbCdEfGhIj" * 4
    found["영문·숫자 덩어리"] = "a1b2c3d4e5f6" * 4
    return found


# (앞, 뒤) — 비밀 모양 바로 옆에 올 수 있는 글자들. 낱말 경계에 기대면 놓치는 것(한글·밑줄·괄호·따옴표·줄바꿈)이 중심이다.
NEIGHBORS = (
    ("", ""), ("키는", "입니다"), ("가", ""), ("", "나"), ("(", ")"), ("[", "]"), ("{", "}"), ("<", ">"), ('"', '"'), ("'", "'"), ("`", "`"),
    ("\n", "\n"), ("앞줄\n", ""), ("", "\n다음 줄"), ("\r\n", "\r\n"), ("값=", ""), ("값: ", ""), ("값:", ""), ("a,", ",b"), ("a ", " b"), ("\t", "\t"), ("_", "_"),
    ("🙂", "🙂"), ("키\u200b", "\u200b"), ("，", "，"), ("「", "」"),
)

PLAIN_LABELS = ("기본", "예비 키", "회사 계정", "My project 2", "naver-app", "Unsplash", "개인용 앱 #2", "예비(두 번째)", "a" * 23)


class HiddenCharTest(unittest.TestCase):
    CASES = {
        "보통 공백": " ", "탭": "\t", "줄바꿈": "\n", "캐리지 리턴": "\r", "NBSP U+00A0": "\u00a0", "폭 없는 공백 U+200B": "\u200b", "오른쪽에서 왼쪽 덮어쓰기 U+202E": "\u202e",
        "바이트 순서 표시 U+FEFF": "\ufeff", "소프트 하이픈 U+00AD": "\u00ad", "줄 구분 U+2028": "\u2028", "문단 구분 U+2029": "\u2029", "널 문자": "\x00", "삭제 문자 U+007F": "\x7f",
        "다음 줄 U+0085": "\x85", "사용자 지정 U+E000": "\ue000", "미배정 U+0378": "\u0378", "짝 없는 대용 문자 U+D800": "\ud800", "표의 문자 공백 U+3000": "\u3000", "EM 공백 U+2003": "\u2003",
    }

    def test_every_hidden_or_blank_character_is_found_anywhere_in_the_text(self):
        for name, char in self.CASES.items():
            for where, text in (("처음", char + "abcdefghij"), ("가운데", "abcde" + char + "fghij"), ("끝", "abcdefghij" + char), ("혼자", char)):
                with self.subTest(char=name, where=where):
                    self.assertIs(shape.has_hidden_char(text), True)

    def test_ordinary_visible_text_has_no_hidden_character(self):
        for text in ("", "abcDEF123", "한글만", "_-+/=.~:", "🙂", "\uff21", "\"'`()[]{}<>\\|;,", "é"):
            with self.subTest(text=text):
                self.assertIs(shape.has_hidden_char(text), False)

    def test_value_problem_refuses_each_hidden_character_with_the_same_whole_sentence(self):
        for name, char in self.CASES.items():
            for where, text in (("처음", char + "abcdefghij"), ("가운데", "abcde" + char + "fghij"), ("끝", "abcdefghij" + char)):
                with self.subTest(char=name, where=where):
                    self.assertEqual(shape.value_problem(text, min_len=5, max_len=40), HIDDEN_REASON)

    def test_leading_and_trailing_blanks_are_refused_even_when_the_rest_is_a_good_value(self):
        for text in (" abcdefghij", "abcdefghij ", "\tabcdefghij", "abcdefghij\n", "abcdefghij\r\n", "\u00a0abcdefghij\u00a0"):
            with self.subTest(text=repr(text)):
                self.assertEqual(shape.value_problem(text, min_len=5, max_len=40), HIDDEN_REASON)


class ValueProblemTest(unittest.TestCase):
    def problem(self, value, min_len=5, max_len=40):
        return shape.value_problem(value, min_len=min_len, max_len=max_len)

    def test_every_allowed_character_is_accepted_at_a_good_length(self):
        for char in "abcxyzABCXYZ0123456789_-+/=.~:":
            with self.subTest(char=char):
                self.assertEqual(self.problem("abc" + char + "def"), "")
        self.assertEqual(self.problem("Aa0_-+/=.~:Zz9"), "")

    def test_every_character_outside_the_allowed_set_is_refused_with_the_whole_charset_sentence(self):
        outside = {
            "큰따옴표": '"', "작은따옴표": "'", "백틱": "`", "소괄호 열기": "(", "소괄호 닫기": ")", "대괄호 열기": "[", "대괄호 닫기": "]", "중괄호 열기": "{", "중괄호 닫기": "}",
            "작다": "<", "크다": ">", "역슬래시": "\\", "세로선": "|", "쉼표": ",", "세미콜론": ";", "한글": "한", "전각 영문 \uff21": "\uff21", "악센트 é": "é", "별표": "*", "느낌표": "!",
            "골뱅이": "@", "샵": "#", "달러": "$", "퍼센트": "%", "캐럿": "^", "앰퍼샌드": "&", "물음표": "?", "이모지": "🙂", "전각 쉼표": "，", "한자": "鍵",
        }
        for name, char in outside.items():
            for where, text in (("처음", char + "abcdefghij"), ("가운데", "abcde" + char + "fghij"), ("끝", "abcdefghij" + char)):
                with self.subTest(char=name, where=where):
                    self.assertEqual(self.problem(text), CHARSET_REASON)

    def test_a_value_wrapped_in_quotes_or_brackets_or_with_a_label_is_refused(self):
        for text in ('"abcdefghij"', "'abcdefghij'", "<abcdefghij>", "[abcdefghij]", "(abcdefghij)", "키=abcdefghij", "key: abcdefghij"):
            with self.subTest(text=text):
                self.assertNotEqual(self.problem(text), "")

    def test_length_boundaries_pass_at_the_limit_and_fail_one_character_beyond(self):
        self.assertEqual(self.problem("a" * 8, min_len=8, max_len=12), "")
        self.assertEqual(self.problem("a" * 12, min_len=8, max_len=12), "")
        self.assertEqual(self.problem("a" * 7, min_len=8, max_len=12), "너무 짧습니다(최소 8자)")
        self.assertEqual(self.problem("a" * 13, min_len=8, max_len=12), "너무 깁니다(최대 12자)")
        self.assertEqual(self.problem("", min_len=1, max_len=12), "너무 짧습니다(최소 1자)")
        self.assertEqual(self.problem("a", min_len=1, max_len=1), "")
        self.assertEqual(self.problem("ab", min_len=1, max_len=1), "너무 깁니다(최대 1자)")

    def test_blank_check_comes_before_the_length_check(self):
        """짧고 공백도 든 값은 공백 때문에 거절한다(길이 문구가 먼저 나와 공백을 놓치지 않는다)."""
        self.assertEqual(self.problem("a b", min_len=8, max_len=12), HIDDEN_REASON)
        self.assertEqual(self.problem("a" * 6 + " " + "b" * 12, min_len=8, max_len=12), HIDDEN_REASON)

    def test_a_value_that_is_not_text_is_refused(self):
        for value in (None, 123, 1.5, b"abcdefghij", ["abcdefghij"], ("abcdefghij",), {"a": "b"}, object()):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(self.problem(value), NOT_TEXT_REASON)

    def test_no_reason_ever_contains_the_value_that_was_checked(self):
        marker = "SECRETVALUE" + "123"
        bad_values = (marker + " ", " " + marker, marker + '"', "'" + marker + "'", marker + "한글", marker * 40, marker[:3], "\u200b" + marker, marker + "\n", "(" + marker + ")", marker.lower() + "\x00")
        for text in bad_values:
            for min_len, max_len in ((5, 40), (1, 3), (60, 80)):
                with self.subTest(text=repr(text), limits=(min_len, max_len)):
                    reason = self.problem(text, min_len, max_len)
                    for piece in (marker, marker.lower(), marker[:6], text.strip()):
                        if piece:
                            self.assertNotIn(piece, reason)

    def test_a_huge_value_is_refused_quickly_as_too_long(self):
        for text in ("a" * 300_000, "한" * 300_000, "a b " * 75_000, "\u200b" * 300_000):
            with self.subTest(head=text[:4]):
                started = time.perf_counter()
                reason = self.problem(text, min_len=5, max_len=40)
                self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)
                self.assertEqual(reason, "너무 깁니다(최대 40자)")

    def test_a_value_just_past_the_scan_limit_is_too_long_and_one_at_the_limit_is_still_judged_by_the_other_rules(self):
        over = shape.MAX_SCAN_CHARS + 1
        self.assertEqual(self.problem("a" * over, min_len=5, max_len=shape.MAX_SCAN_CHARS * 2), f"너무 깁니다(최대 {shape.MAX_SCAN_CHARS * 2}자)")
        self.assertEqual(self.problem("a" * shape.MAX_SCAN_CHARS, min_len=5, max_len=shape.MAX_SCAN_CHARS * 2), "")


class LabelProblemTest(unittest.TestCase):
    def problem(self, value, max_len=40):
        return shape.label_problem(value, max_len=max_len)

    def test_ordinary_names_are_accepted(self):
        for text in PLAIN_LABELS:
            with self.subTest(name=text):
                self.assertEqual(self.problem(text), "")

    def test_leading_trailing_and_repeated_blanks_are_refused_with_the_spacing_sentence(self):
        for text in (" 기본", "기본 ", "회사  계정", "회사\u00a0계정", "회사\u3000계정", "  ", " ", "회사\u2003계정"):
            with self.subTest(text=repr(text)):
                self.assertEqual(self.problem(text), LABEL_SPACING_REASON)

    def test_line_breaks_and_invisible_characters_are_refused_with_the_hidden_sentence(self):
        for char in ("\n", "\r", "\t", "\u200b", "\u202e", "\ufeff", "\u00ad", "\u2028", "\x00", "\x7f", "\ue000", "\u0378", "\ud800"):
            for where, text in (("처음", char + "기본"), ("가운데", "기" + char + "본"), ("끝", "기본" + char)):
                with self.subTest(char=repr(char), where=where):
                    self.assertEqual(self.problem(text), LABEL_HIDDEN_REASON)

    def test_length_boundaries(self):
        self.assertEqual(self.problem("가" * 10, max_len=10), "")
        self.assertEqual(self.problem("가" * 11, max_len=10), "너무 깁니다(최대 10자)")
        self.assertEqual(self.problem("", max_len=10), "")

    def test_a_name_that_looks_like_a_key_is_refused_wherever_the_key_sits(self):
        for name, secret in sample_shapes().items():
            for before, after in NEIGHBORS:
                text = "기본" + before + secret + after
                with self.subTest(shape=name, before=repr(before), after=repr(after)):
                    reason = self.problem(text, max_len=500)
                    self.assertNotEqual(reason, "", "키 모양이 이름에 들어가면 거절한다")
                    self.assertNotIn(secret, reason)
                    if not set(before + after) & {"\n", "\r", "\t", "\u200b", " "}:        # 공백·줄바꿈 규칙에 먼저 걸리지 않는 이웃이면 이유는 '키처럼 보인다' 이다
                        self.assertEqual(reason, SECRET_LOOKING_REASON)

    def test_the_reason_for_a_key_shaped_name_is_the_whole_sentence_and_never_holds_the_name(self):
        secret = "AI" + "za" + "A" * 35
        self.assertEqual(self.problem("기본 " + secret, max_len=500), SECRET_LOOKING_REASON)

    def test_a_value_that_is_not_text_is_refused(self):
        for value in (None, 5, b"abc", ["a"], object()):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(self.problem(value), NOT_TEXT_REASON)

    def test_a_name_made_of_or_ending_in_an_invisible_filler_character_is_refused(self):
        """**알려진 빈틈(소스 수정 대기)** — 한글 채움 문자(U+3164·U+115F·U+1160·U+FFA0)·점자 빈칸(U+2800)·결합 문자 결합기(U+034F)·변형 선택자(U+FE0F)·크메르·몽골 보이지 않는 글자는
        범주 검사(`Cc·Cf·Cs·Co·Cn·Zl·Zp`)에 걸리지 않아 이름이 되어 버린다(`security.mask` 는 이 글자들을 지운다). 같은 모양의 두 이름이나 '비어 보이는' 이름이 생길 수 있다.
        `label_problem` 이 이 글자들도 거절하게 고치면 이 시험이 '예상 밖의 성공' 이 되니 그때 `@unittest.expectedFailure` 표시를 지운다."""
        fillers = ("\u3164", "\u115f", "\u1160", "\u2800", "\u034f", "\ufe0f", "\uffa0", "\u17b4", "\u180b")
        accepted = [hex(ord(char)) for char in fillers if self.problem("기본" + char) == "" or self.problem(char) == ""]
        self.assertEqual(accepted, [])

    def test_a_huge_label_is_refused_quickly(self):
        for text in ("한" * 300_000, "a " * 150_000, "a" * 300_000, "\u200b" * 300_000):
            with self.subTest(head=text[:2]):
                started = time.perf_counter()
                reason = self.problem(text, max_len=20)
                self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)
                self.assertEqual(reason, "너무 깁니다(최대 20자)")


class LooksSecretTest(unittest.TestCase):
    def test_every_known_shape_is_found_next_to_every_kind_of_neighbor(self):
        for name, secret in sample_shapes().items():
            for before, after in NEIGHBORS:
                with self.subTest(shape=name, before=repr(before), after=repr(after)):
                    self.assertIs(shape.looks_secret(before + secret + after), True)

    def test_at_least_seven_known_prefix_shapes_are_covered_by_the_table(self):
        self.assertGreaterEqual(len(PREFIX_SHAPES), 7)
        self.assertGreaterEqual(len(sample_shapes()), 12)

    def test_a_prefix_with_a_tail_one_short_of_the_minimum_is_not_a_secret_and_the_minimum_is(self):
        for name, head, tail, minimum in PREFIX_SHAPES:
            with self.subTest(shape=name, tail="모자람"):
                self.assertIs(shape.looks_secret(head + tail * (minimum - 1)), False)
            with self.subTest(shape=name, tail="딱 맞음"):
                self.assertIs(shape.looks_secret(head + tail * minimum), True)
            with self.subTest(shape=name, tail="넉넉함, 한글 사이에"):
                self.assertIs(shape.looks_secret("가" + head + tail * (minimum + 5) + "나"), True)

    def test_the_prefix_alone_is_not_a_secret(self):
        for name, head, _tail, _minimum in PREFIX_SHAPES:
            with self.subTest(shape=name):
                self.assertIs(shape.looks_secret(head), False)
                self.assertIs(shape.looks_secret("키 " + head + " 입니다"), False)

    def test_the_jwt_shape_needs_both_dots_with_enough_characters(self):
        head = "ey" + "J"
        self.assertIs(shape.looks_secret(head + "a" * 8 + "." + "b" * 4), True)
        self.assertIs(shape.looks_secret(head + "a" * 7 + "." + "b" * 4), False)
        self.assertIs(shape.looks_secret(head + "a" * 8 + "." + "b" * 3), False)
        self.assertIs(shape.looks_secret(head + "a" * 8), False)

    def test_the_private_key_header_is_enough_and_a_cut_header_is_not(self):
        full = "-----" + "BEGIN"
        self.assertIs(shape.looks_secret(full), True)
        self.assertIs(shape.looks_secret("앞" + full + " PRIVATE KEY-----"), True)
        self.assertIs(shape.looks_secret("-----" + "BEGI"), False)
        self.assertIs(shape.looks_secret("----" + "BEGIN"), False)

    def test_the_telegram_shape_needs_six_to_twelve_digits_then_a_colon_and_twenty_more(self):
        self.assertIs(shape.looks_secret("123456" + ":" + "A" * 20), True)
        self.assertIs(shape.looks_secret("123456789012" + ":" + "A" * 20), True)
        self.assertIs(shape.looks_secret("12345" + ":" + "A" * 20), False)
        self.assertIs(shape.looks_secret("123456" + ":" + "A" * 19), False)

    def test_a_long_run_of_letters_and_digits_is_a_token_but_only_from_twenty_four_characters(self):
        self.assertIs(shape.looks_secret("a1" * 12), True)
        self.assertIs(shape.looks_secret("a1" * 11 + "a"), False)
        self.assertIs(shape.looks_secret("a1-" * 8), True)
        self.assertIs(shape.looks_secret("a" * 24), False)
        self.assertIs(shape.looks_secret("1" * 24), False)
        self.assertIs(shape.looks_secret("a" * 300 + "1"), True)
        self.assertIs(shape.looks_secret("a1" * 6 + " " + "a1" * 6), False)
        self.assertIs(shape.looks_secret("a1" * 11 + "한" + "a1" * 11), False)

    def test_ordinary_words_and_names_are_not_secrets(self):
        for text in ("", "기본", "예비 키", "회사 계정", "My project 2", "naver-app", "internationalization", "hello world 1234", "2026-11-03", "https://example.invalid/a/b"):
            with self.subTest(text=text):
                self.assertIs(shape.looks_secret(text), False)

    def test_a_value_that_is_not_text_is_not_trusted(self):
        for value in (None, 5, b"abc", ["a"], object()):
            with self.subTest(kind=type(value).__name__):
                self.assertIs(shape.looks_secret(value), True)

    def test_a_text_longer_than_the_scan_limit_is_trusted_as_secret_and_one_at_the_limit_is_scanned(self):
        self.assertIs(shape.looks_secret("가" * (shape.MAX_SCAN_CHARS + 1)), True)
        self.assertIs(shape.looks_secret("가" * shape.MAX_SCAN_CHARS), False)
        self.assertIs(shape.looks_secret("가" * (shape.MAX_SCAN_CHARS - 40) + "a1" * 12), True)

    def test_inputs_over_the_scan_limit_are_answered_true_at_once(self):
        for text in ("a" * 300_000, "1" * 300_000, "한" * 300_000, " " * 300_000, "a1" * 150_000):
            with self.subTest(head=text[:2]):
                started = time.perf_counter()
                self.assertIs(shape.looks_secret(text), True)
                self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)

    def test_inputs_just_inside_the_scan_limit_are_really_scanned_in_linear_time_with_the_right_answer(self):
        n = shape.MAX_SCAN_CHARS
        head = "AI" + "za"
        telegram_near_miss = "123456" + ":" + "A" * 19 + " "
        jwt_head = "ey" + "J" + "a" * 7 + "."
        cases = {
            "한 글자 반복": ("a" * n, False), "숫자만": ("1" * n, False), "기호만": ("-" * n, False), "영문 숫자 번갈아": ("a1" * (n // 2), True), "구분 있는 반복": ("ab1-" * (n // 4), True),
            "접두사 뒤가 끊김": ((head + "!") * (n // 5), False), "숫자가 길게 이어지다 끝에 영문자": ("1" * (n - 1) + "x", True),
            "텔레그램 모양에 한 글자 모자람": (telegram_near_miss * (n // len(telegram_near_miss)), False),
            "한글": ("가" * n, False), "공백": (" " * n, False), "접두사 겹침": (("gh" + "p_") * (n // 4), False), "점 반복": ("." * n, False),
            "JWT 머리에 한 글자 모자람": (jwt_head * (n // len(jwt_head)), False),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(shape=name):
                self.assertLessEqual(len(text), n)
                started = time.perf_counter()
                result = shape.looks_secret(text)
                self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)
                self.assertIs(result, expected)


class DerivedValuesTest(unittest.TestCase):
    HEX = set("0123456789abcdef")

    def test_there_is_no_whole_value_fingerprint_function_any_more(self):
        """값 전체를 해시한 지문은 약한 값(8자)을 사전 대입으로 알아내게 하므로 이 모듈에 두지 않는다 — 같은 값 중복은 보관소의 값을 직접 비교한다."""
        public = {name for name in dir(shape) if not name.startswith("_")}
        self.assertEqual({name for name in public if "finger" in name.lower() or "print" in name.lower()}, set())
        self.assertEqual({name for name in public if callable(getattr(shape, name)) and name.endswith("digest")}, {"short_digest"})

    def test_the_short_digest_is_eight_hex_digits_stable_distinct_and_not_a_plain_hash(self):
        import hashlib
        one = shape.short_digest("abc")
        self.assertEqual(len(one), 8)
        self.assertTrue(set(one) <= self.HEX)
        self.assertEqual(one, shape.short_digest("abc"))
        self.assertNotEqual(one, shape.short_digest("abd"))
        self.assertNotEqual(one, shape.short_digest(""))
        self.assertNotEqual(one, hashlib.sha256(b"abc").hexdigest()[:8], "구분 글자 없이 그냥 해시한 값과 달라야 한다(다른 용도의 해시와 섞이지 않게)")
        self.assertEqual(len(shape.short_digest("\ud800")), 8)

    def test_no_function_shows_any_part_of_a_value_so_the_tail_hint_is_gone(self):
        """의도적 강화(PCSEC1 H2): 예전에는 값이 16자 이상이면 끝 4자(`****abcd`)를 목록에 보였다 — 운영자 결정(2026-11-11)으로 마지막 네 글자 표시도 모두 없앴다.
        이 모듈에는 값의 일부(끝·앞·접두어·길이)를 돌려주는 함수·상수가 없다."""
        for name in ("tail_hint", "TAIL_MIN_LEN", "TAIL_SHOWN", "head_hint", "prefix_hint", "last4", "mask_tail"):
            self.assertFalse(hasattr(shape, name), name)
        public = sorted(name for name in dir(shape) if not name.startswith("_") and callable(getattr(shape, name)) and getattr(getattr(shape, name), "__module__", "") == shape.__name__)
        self.assertEqual(public, ["has_hidden_char", "label_problem", "looks_secret", "short_digest", "value_problem"],
                         "모양을 검사하는 함수와 비밀이 아닌 칸의 해시뿐이다 — 새 함수가 생기면 값의 일부를 내는 것이 아닌지 이 시험에서 확인한다")
        secret = "Qx7Zk-Wm3Vp_" + "Ty8Rn2Hs+Jd6Lg4Bf9Nc1Mu"                      # 조립한 가짜 값(저장소 비밀 스캐너가 소스 글자를 훑는다)
        for name in public:
            function = getattr(shape, name)
            if name == "short_digest":
                self.assertNotIn(secret[-4:], function(secret))
                self.assertEqual(len(function(secret)), 8)



class RandomInputsTest(unittest.TestCase):
    """고정 시드의 무작위 입력(몇 백 개)에도 예외가 없고 결과 종류가 일정하며, 서로의 판정이 어긋나지 않는다."""

    ALPHABETS = (
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "abc123_-+/=.~:",
        "가나다라마바사아자차카타파하",
        "\"'`()[]{}<>\\|;,!@#$%^&*? \t\n\r",
        "\u200b\u202e\ufeff\u00ad\u2028\x00\x7f\ue000\u0378\ud800\u3000\u00a0",
        "🙂🚀한글\uff21",
    )

    def make_texts(self, count=400):
        rng = random.Random(7)
        texts = []
        for _ in range(count):
            alphabet = "".join(rng.choice(self.ALPHABETS) for _ in range(rng.randint(1, 3)))
            texts.append("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 200))))
        for _ in range(count // 2):                                              # 값 모양(영문·숫자·허용 기호)만으로 된 표본 — 받아들여지는 쪽의 성질을 보려면 이런 표본이 많아야 한다
            texts.append("".join(rng.choice(self.ALPHABETS[rng.randint(0, 1)]) for _ in range(rng.randint(0, 60))))
        return texts

    def test_no_function_raises_and_every_result_has_the_documented_kind(self):
        for text in self.make_texts():
            with self.subTest(head=repr(text[:12])):
                self.assertIsInstance(shape.has_hidden_char(text), bool)
                self.assertIsInstance(shape.looks_secret(text), bool)
                self.assertIsInstance(shape.value_problem(text, min_len=3, max_len=50), str)
                self.assertIsInstance(shape.label_problem(text, max_len=30), str)
                self.assertEqual(len(shape.short_digest(text)), 8)

    def test_an_accepted_value_really_has_the_documented_properties(self):
        accepted = 0
        for text in self.make_texts(800):
            if shape.value_problem(text, min_len=3, max_len=50) == "":
                accepted += 1
                with self.subTest(text=text):
                    self.assertFalse(shape.has_hidden_char(text))
                    self.assertTrue(3 <= len(text) <= 50)
                    self.assertTrue(all(ch.isascii() and (ch.isalnum() or ch in "_-+/=.~:") for ch in text))
        self.assertGreater(accepted, 20, "받아들여지는 표본이 너무 적어 이 시험이 아무것도 보지 못한다")

    def test_an_accepted_label_has_no_key_shape_and_no_hidden_or_repeated_blank(self):
        accepted = 0
        for text in self.make_texts(800):
            if shape.label_problem(text, max_len=30) == "":
                accepted += 1
                with self.subTest(text=text):
                    self.assertFalse(shape.looks_secret(text))
                    self.assertEqual(text, " ".join(text.split()))
                    self.assertLessEqual(len(text), 30)
        self.assertGreater(accepted, 20, "받아들여지는 표본이 너무 적어 이 시험이 아무것도 보지 못한다")


if __name__ == "__main__":
    unittest.main()
