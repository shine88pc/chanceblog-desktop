"""'진단 정보 한 번에 복사'(L3 의 F035, 결정 D-539 에서 D-541)의 순수 부분 시험 — PySide6 없이 돈다(네트워크·실제 보관소·시크릿·파일 쓰기 없음).

지키는 것:
  1) 복사되는 글은 머리 한 줄 + `이름: 값` 다섯 줄(앱 버전·빌드 커밋 7자리·윈도 빌드 번호·화면 배율·마지막 오류 코드)뿐이다 — 이름도 줄 수도 순서도 못박는다.
  2) 값마다 좁은 글자표를 통과한 것만 쓴다 — 사용자 이름·경로·블로그 이름·글 내용·키·토큰·초안 번호·오류 메시지 글이 어느 칸으로 들어와도 `unknown` 이고 글에 남지 않는다.
     오류 코드 칸의 글자표는 `security/errorlog.py` 의 클래스 이름 글자표보다 느슨하지 않고, 공통 가림이 바꾸는 글은 통과하지 못한다.
  3) 오류 칸에는 오류의 **코드**만 간다(메시지 글은 읽지 않는다) — 앱 상태가 가진 실패 중 시각이 가장 늦은 것, 나아져 지워졌으면 없다(`none`).
  4) 윈도 빌드 번호·화면 배율을 읽는 코드는 윈도가 아니어도(리눅스 CI) 가져오기·호출이 안전하고, 어떤 이상한 값이 와도 예외를 내지 않는다.
  5) 설정 화면의 정보 뷰모델이 단추 글(`copy`)을 모든 상태(오류 포함)에서 싣는다 — 복사되는 글 자체는 뷰모델에 없다.
  6) 문서(결정 D-539–D-543·UI 문서·문제 해결·변경 이력)가 이 변경을 사실대로 적는다.
"""
import ast
import builtins
import datetime
import itertools
import os
import re
import string
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from chanceblog_desktop.errors.table import CATALOG  # noqa: E402
from chanceblog_desktop.ui.core import app_state, diagnostics as dg, services, text  # noqa: E402
from chanceblog_desktop.ui.core import settings_view as sv  # noqa: E402
from chanceblog_desktop.ui.core.jobs import JobFailure  # noqa: E402
from chanceblog_desktop.ui.core.version import VersionInfo  # noqa: E402

CORE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core"
SHELL = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt" / "shell.py"
CANARY_GOOGLE = "CANARY_" + "AI" + "za" + "SyD4e7Kq9ZmW2xV8bN5tR1cY6uH3jL0pGfA1B"[:35]       # 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)
CANARY_GITHUB = "CANARY_" + "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
CANARY_SK = "CANARY_" + "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
CANARY_BEARER = "Bearer " + "CANARY_" + "Zq8Lm2Vx9Rt4Yw7Kp3Hn6Bc5Df1Gj0S"
USER_NAME = "TEST_USER_A"                                                                      # 누가 봐도 가짜인 사용자 이름(영문·밑줄이라 '코드 모양' 이기도 하다 — 아래 CODE_SHAPED 의 한계를 보이는 값). 진짜 계정 이름은 저장소 어디에도 쓰지 않는다
WINDOWS_PATH = "C:\\Users\\" + USER_NAME + "\\AppData\\Local\\ChanceblogDesktop\\logs"
UNIX_PATH = "/home/" + "kim" + "/blog/drafts"
UNC_PATH = "\\\\" + "server" + "\\share\\blog"
FILE_URL = "file:///C:/Users/" + USER_NAME + "/Desktop"
BLOG_NAME = "내 맛집 기록 블로그"                                                               # 사용자가 붙인 블로그 별명 모양(가짜)
ARTICLE = "오늘은 에너지 절약 습관 다섯 가지를 정리해 봤어요."                                     # 글 내용 모양(가짜)
DRAFT_ID = "dd-" + "0123456789abcdef0123"                                                     # 저장한 초안 번호 모양
CANDIDATE_ID = "cand-" + "7f3a9c1e5b2d"                                                        # 후보 번호 모양
MESSAGE = "연결 설정을 읽는 중 끊겼어요. " + WINDOWS_PATH                                         # 오류의 안내 문장(경로 포함)
ADVERSARIAL = (USER_NAME, WINDOWS_PATH, UNIX_PATH, UNC_PATH, FILE_URL, BLOG_NAME, ARTICLE, DRAFT_ID, CANDIDATE_ID, MESSAGE, CANARY_GOOGLE, CANARY_GITHUB, CANARY_SK, CANARY_BEARER,
               "", " ", "\n", "v1.2.3\nC:\\x", "dd-0123", "../../etc", "%USERPROFILE%", "a b", "한글코드")
SECRET_PIECES = (USER_NAME, "AppData", "ChanceblogDesktop", "server", "share", "kim", BLOG_NAME, "맛집", ARTICLE, "에너지", DRAFT_ID, "dd-", CANDIDATE_ID, "cand-", "Bearer", "CANARY_", "ghp_", "AIza", "sk-proj", "C:\\", "C:/", "/home", "file:", "끊겼어요")
CODE_SHAPED = (USER_NAME,)                                                                    # 값 하나만으로 이미 '코드 모양'(영문·숫자·밑줄)인 가짜 값 — 오류 코드 칸은 코드 모양이면 통과한다. 사용자가 친 글이 이 칸으로 들어오는 길은 없다(앱 상태는 `failure.code` 만 읽고 그 코드는 프로그램이 정한 이름·예외 클래스 이름이다 — D-541)
ALNUM = set(string.ascii_letters + string.digits)
EXTRA_CODES = (0x200B, 0x200C, 0x200D, 0x2060, 0x202E, 0x3164, 0xFEFF, 0xFF21, 0xFF10, 0xD55C, 0x1F600, 0xE0041, 0x0663, 0x2028, 0x2029, 0x3000)      # 폭 없는 글자·방향 제어·채움 글자·전각 글자·한글·이모지·태그·아랍-인도 숫자·줄 구분 — 눈에 안 보이는 글자는 번호로 적는다
EVERY = [chr(code) for code in range(0, 0x300)] + [chr(code) for code in EXTRA_CODES]                                                       # 글자 상자 훑기에 쓰는 글자 — 제어 문자와 라틴 글자 전부 + 위의 별난 글자
HEADER = "ChanceBlog Desktop 진단 정보"
LINE = {"version": r"version: (?:dev|unknown|v[0-9]{1,5}[.][0-9]{1,5}[.][0-9]{1,5}(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?)",
        "commit": r"commit: (?:unknown|[0-9a-f]{7})", "windows_build": r"windows_build: (?:unknown|[0-9]{3,6})",
        "display_scale": r"display_scale: (?:unknown|(?:[5-9][0-9]|[1-5][0-9]{2}|600)%)", "last_error_code": r"last_error_code: (?:none|unknown|[A-Za-z][A-Za-z0-9_]{0,47})"}
GOOD = VersionInfo("v0.1.0-preview.1", "file", "abcdef0", "알림")
WHEN = datetime.datetime(2026, 11, 22, 9, 0, 0)


def lines_of(report):
    return report.split("\n")


def assert_shape(case, report):
    """복사되는 글의 모양 전수 — 머리 한 줄과 다섯 칸이 정해진 순서·정해진 글자표뿐이다."""
    lines = lines_of(report)
    case.assertEqual(len(lines), 6, report)
    case.assertEqual(lines[0], HEADER, report)
    for line, name in zip(lines[1:], dg.FIELDS):
        case.assertRegex(line, "^" + LINE[name] + "$", report)


class Odd:
    """속성을 읽으면 예외를 내는 이상한 객체 — 어떤 입력에도 규칙이 예외를 내지 않아야 한다."""

    def __getattr__(self, name):
        raise RuntimeError("읽을 수 없다")

    def timestamp(self):
        raise RuntimeError("시각이 아니다")


class FieldRulesTest(unittest.TestCase):
    def test_the_version_field_takes_only_a_read_version_in_the_shape_vnumber_and_names_the_dev_screen_dev(self):
        for text_value in ("v0.1.0-preview.1", "v1.2.3", "v12.0.30+3", "v0.0.0-beta.2"):
            self.assertEqual(dg.version_text(VersionInfo(text_value, "file")), text_value)
        self.assertEqual(dg.version_text(VersionInfo("개발 버전", "dev")), "dev")                      # 버전 파일을 못 읽은 개발 화면
        self.assertEqual(dg.version_text(None), "dev")                                                # 버전 정보가 없다 — 화면의 '개발 버전' 과 같다
        for bad in ("v1.2", "1.2.3", "v1.2.3 ", "v1.2.3\nC:\\x", "v1.2.3-" + "a" * 40, "개발 버전", "", "v1.2.3/../x", WINDOWS_PATH, USER_NAME + " v1.2.3", CANARY_GOOGLE):
            self.assertEqual(dg.version_text(VersionInfo(bad, "file")), dg.UNKNOWN, repr(bad))
        for bad in (123, None, b"v1.2.3", ["v1.2.3"]):
            self.assertEqual(dg.version_text(VersionInfo(bad, "file")), dg.UNKNOWN, repr(bad))
        self.assertEqual(dg.version_text(Odd()), dg.UNKNOWN)                                          # 속성을 읽다 예외가 나는 객체도 예외 없이 `unknown`

    def test_the_commit_field_takes_exactly_seven_lowercase_hex_characters_and_never_cuts_a_longer_text(self):
        self.assertEqual(dg.commit_text(GOOD), "abcdef0")
        self.assertEqual(dg.commit_text(VersionInfo("v1.0.0", "file")), dg.UNKNOWN)                    # 개발 실행 — 정보 파일이 없다
        for bad in ("abcdef", "abcdef01", "0123456789abcdef0123456789abcdef01234567", "ABCDEF0", "abcdefg", "abcdef0\n", " abcdef0", WINDOWS_PATH, DRAFT_ID, CANARY_GITHUB):
            self.assertEqual(dg.commit_text(VersionInfo("v1.0.0", "file", bad)), dg.UNKNOWN, repr(bad))        # 긴 글은 앞 7자를 잘라 쓰지 않고 통째로 버린다
        self.assertEqual(dg.commit_text(None), dg.UNKNOWN)
        self.assertEqual(dg.commit_text(Odd()), dg.UNKNOWN)

    def test_the_windows_build_field_takes_three_to_six_digits_only(self):
        for good, shown in ((22631, "22631"), ("22621", "22621"), (19045, "19045"), (7601, "7601"), (100, "100"), (999999, "999999")):
            self.assertEqual(dg.build_text(good), shown)
        for bad in (None, True, False, -5, 0, 12, 1234567, "12", "1234567", "22631\n", " 22631", "22631 ", 22631.0, "22.631", "0x5867", WINDOWS_PATH, USER_NAME, b"22631", [22631], Odd()):
            self.assertEqual(dg.build_text(bad), dg.UNKNOWN, repr(bad))

    def test_the_display_scale_field_takes_a_whole_percent_from_fifty_to_six_hundred_only(self):
        for good in (50, 75, 100, 125, 150, 175, 200, 250, 300, 500, 600):
            self.assertEqual(dg.scale_text(good), f"{good}%")
        for bad in (None, True, False, 0, 49, 601, -100, 125.0, 1.25, "150", "150%", float("nan"), float("inf"), [150], Odd()):
            self.assertEqual(dg.scale_text(bad), dg.UNKNOWN, repr(bad))

    def test_the_error_code_field_takes_a_code_name_only_and_none_means_no_error_at_all(self):
        self.assertEqual(dg.code_text(None), dg.NONE)
        for code in ("GIT_PUSH_AUTH", "TypeError", "SAMPLE_DOWN", "DATA_DIR_NOT_FOUND", "A", "X" * 48, "Code_2"):
            self.assertEqual(dg.code_text(code), code)
        for bad in ("", " ", "X" * 49, "9CODE", "_CODE", "GIT PUSH", "GIT-PUSH", "GIT.PUSH", "코드", "GIT_PUSH_AUTH\n", MESSAGE, WINDOWS_PATH, UNIX_PATH, DRAFT_ID, CANDIDATE_ID, BLOG_NAME, ARTICLE, 7, True, b"X", ["X"], Odd()):
            self.assertEqual(dg.code_text(bad), dg.UNKNOWN, repr(bad))

    def test_a_code_shaped_text_that_the_common_masking_would_change_is_unknown_too(self):
        """글자표(영문·숫자·밑줄)는 통과하지만 공통 가림(`display_text`)이 키·토큰 모양으로 보고 바꾸는 글 — 한 글자라도 바뀌면 버린다(가림 글자가 코드 칸에 들어가지도 않는다)."""
        for key in (CANARY_GOOGLE, CANARY_GITHUB, CANARY_SK):
            self.assertRegex(key, "^[A-Za-z][A-Za-z0-9_-]*$")
            self.assertNotEqual(text.display_text(key, 200), key, "이 가짜 값은 공통 가림이 바꾸는 모양이어야 한다")
        for key in (CANARY_GOOGLE, CANARY_GITHUB):
            self.assertIsNotNone(dg._CODE.fullmatch(key), key)                                         # 글자표만으로는 통과한다
            self.assertEqual(dg.code_text(key), dg.UNKNOWN, key)
        with mock.patch.object(dg, "display_text", lambda value, limit=300: "바뀐 글"):
            for call, value in ((dg.code_text, "GIT_PUSH_AUTH"), (dg.build_text, 22631), (dg.commit_text, GOOD), (dg.version_text, GOOD)):
                self.assertEqual(call(value), dg.UNKNOWN, call.__name__)                                  # 가림이 바꾸는 글은 어느 칸이든 통과하지 못한다

    def test_the_code_shape_is_never_looser_than_the_error_log_class_name_shape(self):
        """`security/errorlog.py` 의 '이름과 코드 위치만' 규칙을 느슨하게 만들지 않는다 — 그 파일의 클래스 이름 글자표(`_CLASS`)에 맞지 않는 글은 오류 코드 칸에서도 통과하지 못한다
        (같은 글자 상자로 만든 글 3천여 개를 모두 대어 본다). 반대로 그 글자표가 받는 앞 밑줄·65자 가까운 이름은 여기서는 `unknown` 이다 — 더 좁다."""
        from chanceblog_desktop.security import errorlog
        alphabet = ["A", "z", "7", "_", ".", "-", "/", "\\", " ", "한", ":", "$", "%", "\n"]
        samples = [""] + ["".join(chars) for size in (1, 2, 3) for chars in itertools.product(alphabet, repeat=size)] + ["X" * count for count in (47, 48, 49, 63, 64, 65)] + ["_X", "9X"]
        self.assertGreater(len(samples), 2900)
        self.assertEqual([sample for sample in samples if errorlog._CLASS.fullmatch(sample) is None and dg.code_text(sample) not in (dg.UNKNOWN, dg.NONE)], [])
        for wider in ("_X", "X" * 49, "X" * 64):
            self.assertIsNotNone(errorlog._CLASS.fullmatch(wider), wider)
            self.assertEqual(dg.code_text(wider), dg.UNKNOWN, wider)

    def test_every_error_code_of_the_catalog_and_every_builtin_exception_name_survives_unchanged(self):
        """실제로 나올 코드는 모두 그대로 보인다 — 글자표가 너무 좁아 진짜 코드가 `unknown` 이 되는 일이 없다."""
        codes = list(CATALOG)                                                                          # 카탈로그는 코드 → 안내 표다
        self.assertGreater(len(codes), 50)
        self.assertEqual([code for code in codes if dg.code_text(code) != code], [])
        names = [name for name, value in vars(builtins).items() if isinstance(value, type) and issubclass(value, BaseException)]
        self.assertGreater(len(names), 50)
        self.assertEqual([name for name in names if dg.code_text(name) != name], [])
        self.assertEqual(dg.code_text(JobFailure("x", code="CANCELLED").code), "CANCELLED")


    # ---- 글자 상자 훑기(검증 S 의 SP-2) — 글자표의 '상자' 에 경로·메일 글자를 하나 얹어도 빨개져야 한다 ----
    def test_the_version_suffix_first_character_is_alnum_and_the_later_ones_are_alnum_dot_plus_minus_only(self):
        for ch in EVERY:
            first = dg.version_text(VersionInfo("v1.2.3-" + ch + "a", "file")) == "v1.2.3-" + ch + "a"
            later = dg.version_text(VersionInfo("v1.2.3-a" + ch + "a", "file")) == "v1.2.3-a" + ch + "a"
            tail = dg.version_text(VersionInfo("v1.2.3-aa" + ch, "file")) == "v1.2.3-aa" + ch
            self.assertEqual(first, ch in ALNUM, repr(ch))
            self.assertEqual(later, ch in ALNUM | set(".+-"), repr(ch))
            self.assertEqual(tail, ch in ALNUM | set(".+-"), repr(ch))

    def test_the_version_numbers_are_ascii_digits_of_at_most_five_and_the_suffix_has_at_most_thirty_one_characters(self):
        for ch in EVERY:
            digit = ch.isascii() and ch.isdigit()
            for shown, expected in (("v" + ch + ".2.3", digit), ("v1." + ch + ".3", digit), ("v1.2." + ch, digit), ("v1.2.3" + ch, digit), (ch + "1.2.3", ch == "v"), ("v1.2.3-" + ch, ch in ALNUM)):
                self.assertEqual(dg.version_text(VersionInfo(shown, "file")) == shown, expected, repr(shown))
        self.assertEqual(dg.version_text(VersionInfo("v99999.99999.99999", "file")), "v99999.99999.99999")
        self.assertEqual(dg.version_text(VersionInfo("v100000.1.1", "file")), dg.UNKNOWN)
        self.assertEqual(dg.version_text(VersionInfo("v1.2.3-" + "a" * 31, "file")), "v1.2.3-" + "a" * 31)
        self.assertEqual(dg.version_text(VersionInfo("v1.2.3-" + "a" * 32, "file")), dg.UNKNOWN)

    def test_the_error_code_first_character_is_an_ascii_letter_and_the_later_ones_are_ascii_letters_digits_underscore_only(self):
        for ch in EVERY:
            first = dg.code_text(ch + "A") == ch + "A"
            later = dg.code_text("A" + ch + "A") == "A" + ch + "A"
            tail = dg.code_text("AA" + ch) == "AA" + ch
            self.assertEqual(first, ch.isascii() and ch.isalpha(), repr(ch))
            self.assertEqual(later, ch in ALNUM | {"_"}, repr(ch))
            self.assertEqual(tail, ch in ALNUM | {"_"}, repr(ch))
        self.assertEqual(dg.code_text("A" * 48), "A" * 48)
        self.assertEqual(dg.code_text("A" * 49), dg.UNKNOWN)

    def test_the_commit_is_seven_lowercase_hex_characters_in_every_position(self):
        for ch in EVERY:
            for position in range(7):
                shown = "abcdef0"[:position] + ch + "abcdef0"[position + 1:]
                self.assertEqual(dg.commit_text(VersionInfo("v1.0.0", "file", shown)) == shown, ch in set("0123456789abcdef"), (repr(ch), position))

    def test_the_windows_build_is_ascii_digits_only_in_every_position(self):
        for ch in EVERY:
            for position in range(5):
                shown = "22631"[:position] + ch + "22631"[position + 1:]
                self.assertEqual(dg.build_text(shown) == shown, ch.isascii() and ch.isdigit(), (repr(ch), position))

    # ---- 닫힌 쪽(검증 S 의 SP-4) · 정확한 글·정수만(SP-7) ----
    def test_when_the_common_masking_raises_the_masked_fields_are_unknown_and_nothing_is_passed_through(self):
        with mock.patch.object(dg, "display_text", side_effect=RuntimeError("가림 모듈을 못 불렀다")):
            report = dg.build_report(GOOD, 22631, 150, "GIT_PUSH_AUTH")
        self.assertEqual(lines_of(report)[1:], ["version: unknown", "commit: unknown", "windows_build: unknown", "display_scale: 150%", "last_error_code: unknown"])      # 배율은 글자 가림을 안 쓰므로 그대로다

    def test_a_str_or_int_subclass_that_lies_about_its_text_is_unknown_and_never_printed(self):
        class LyingStr(str):
            def __format__(self, spec):
                return WINDOWS_PATH

            def __str__(self):
                return WINDOWS_PATH

        class LyingInt(int):
            def __format__(self, spec):
                return WINDOWS_PATH

            def __str__(self):
                return WINDOWS_PATH

        class LyingFloat(float):
            def __mul__(self, other):
                return 150

        self.assertEqual((dg.code_text(LyingStr("GIT_PUSH_AUTH")), dg.build_text(LyingInt(22631)), dg.scale_text(LyingInt(150))), (dg.UNKNOWN, dg.UNKNOWN, dg.UNKNOWN))
        self.assertEqual((dg.version_text(VersionInfo(LyingStr("v1.2.3"), "file")), dg.commit_text(VersionInfo("v1.2.3", "file", LyingStr("abcdef0")))), (dg.UNKNOWN, dg.UNKNOWN))
        self.assertIsNone(dg.scale_percent(LyingFloat(1.5)))
        self.assertIsNone(dg.windows_build_number(ReadersTest.getter(build=LyingInt(22631))))
        report = dg.build_report(VersionInfo(LyingStr("v1.2.3"), "file", LyingStr("abcdef0")), LyingInt(22631), LyingInt(150), LyingStr("GIT_PUSH_AUTH"))
        assert_shape(self, report)
        self.assertEqual(lines_of(report)[1:], ["version: unknown", "commit: unknown", "windows_build: unknown", "display_scale: unknown", "last_error_code: unknown"])
        for piece in SECRET_PIECES:
            self.assertNotIn(piece, report, piece)

    def test_only_the_exact_str_int_and_float_types_are_accepted_even_a_harmless_subclass_is_unknown(self):
        """정확한 `str`·`int`·`float` 만 받는다 — 거짓말하지 않는 하위 클래스도 `unknown` 이다(실제 입력 길은 모두 정확한 형이고 형 하나만 보면 되어 규칙이 단순하다 — 검증 S 의 SP-7 을 정책으로 못박는다)."""
        class PlainStr(str):
            pass

        class PlainInt(int):
            pass

        class PlainFloat(float):
            pass

        self.assertEqual((dg.code_text("GIT_PUSH_AUTH"), dg.build_text(22631), dg.build_text("22631"), dg.scale_text(150), dg.scale_percent(1.5), dg.scale_percent(2)), ("GIT_PUSH_AUTH", "22631", "22631", "150%", 150, 200))        # 정확한 형은 통과(대조)
        self.assertEqual((dg.code_text(PlainStr("GIT_PUSH_AUTH")), dg.build_text(PlainInt(22631)), dg.build_text(PlainStr("22631")), dg.scale_text(PlainInt(150))), (dg.UNKNOWN,) * 4)
        self.assertEqual((dg.version_text(VersionInfo(PlainStr("v1.2.3"), "file")), dg.commit_text(VersionInfo("v1.2.3", "file", PlainStr("abcdef0")))), (dg.UNKNOWN, dg.UNKNOWN))
        self.assertEqual((dg.scale_percent(PlainFloat(1.5)), dg.scale_percent(PlainInt(2))), (None, None))
        self.assertEqual(dg.windows_build_number(ReadersTest.getter(build=22631)), 22631)                 # 대조
        self.assertIsNone(dg.windows_build_number(ReadersTest.getter(build=PlainInt(22631))))


class LatestFailureTest(unittest.TestCase):
    def test_no_failure_is_none_and_the_latest_failure_wins_by_time(self):
        self.assertIsNone(dg.latest_failure_code([]))
        self.assertIsNone(dg.latest_failure_code([(None, WHEN), (None, None)]))
        old, new = JobFailure("옛 문장", code="OLD_ONE"), JobFailure("새 문장", code="NEW_ONE")
        later = WHEN + datetime.timedelta(minutes=5)
        self.assertEqual(dg.latest_failure_code([(old, WHEN), (new, later)]), "NEW_ONE")
        self.assertEqual(dg.latest_failure_code([(new, later), (old, WHEN)]), "NEW_ONE")                # 칸의 순서가 아니라 시각이 정한다
        self.assertEqual(dg.latest_failure_code([(old, WHEN), (None, later), (new, WHEN - datetime.timedelta(days=1))]), "OLD_ONE")        # 지워진 실패(None)는 시각이 늦어도 이기지 않는다

    def test_a_tie_or_a_missing_time_lets_the_earlier_slot_win_and_a_known_time_beats_a_missing_one(self):
        first, second = JobFailure("a", code="FIRST_ONE"), JobFailure("b", code="SECOND_ONE")
        self.assertEqual(dg.latest_failure_code([(first, WHEN), (second, WHEN)]), "FIRST_ONE")
        self.assertEqual(dg.latest_failure_code([(first, None), (second, None)]), "FIRST_ONE")
        self.assertEqual(dg.latest_failure_code([(first, None), (second, WHEN)]), "SECOND_ONE")
        self.assertEqual(dg.latest_failure_code([(first, Odd()), (second, "어제")]), "FIRST_ONE")       # 비교할 수 없는 시각은 가장 오래된 것

    def test_only_the_code_is_read_never_the_message_and_an_unreadable_code_is_an_empty_text(self):
        failure = JobFailure(MESSAGE, code="KEPT_CODE")
        self.assertEqual(dg.latest_failure_code([(failure, WHEN)]), "KEPT_CODE")
        self.assertEqual(dg.latest_failure_code([(JobFailure(MESSAGE, code=""), WHEN)]), "")
        self.assertEqual(dg.latest_failure_code([(Odd(), WHEN)]), "")
        self.assertEqual(dg.latest_failure_code(None), "")                                              # 읽을 수 없으면 '없음' 이 아니라 '코드를 모름' 이다(`unknown`)
        self.assertEqual(dg.code_text(dg.latest_failure_code([(JobFailure(MESSAGE, code=""), WHEN)])), dg.UNKNOWN)


class ReportTest(unittest.TestCase):
    def test_the_report_of_known_values_is_exactly_this_text(self):
        self.assertEqual(dg.build_report(GOOD, 22631, 150, "GIT_PUSH_AUTH"),
                         "ChanceBlog Desktop 진단 정보\nversion: v0.1.0-preview.1\ncommit: abcdef0\nwindows_build: 22631\ndisplay_scale: 150%\nlast_error_code: GIT_PUSH_AUTH")

    def test_the_report_of_nothing_says_dev_unknown_and_no_error_and_keeps_every_line(self):
        self.assertEqual(dg.build_report(), "ChanceBlog Desktop 진단 정보\nversion: dev\ncommit: unknown\nwindows_build: unknown\ndisplay_scale: unknown\nlast_error_code: none")
        self.assertEqual(dg.FIELDS, ("version", "commit", "windows_build", "display_scale", "last_error_code"))

    def test_every_report_has_the_header_and_the_five_lines_in_order_in_the_allowed_letters_whatever_comes_in(self):
        assert_shape(self, dg.build_report(GOOD, 22631, 150, "GIT_PUSH_AUTH"))
        assert_shape(self, dg.build_report())
        for bad in ADVERSARIAL:
            for report in (dg.build_report(VersionInfo(bad, "file", bad), bad, bad, bad), dg.build_report(bad, bad, bad, bad), dg.build_report(VersionInfo("v1.0.0", "file", bad), 1, 1, bad)):
                assert_shape(self, report)
        assert_shape(self, dg.build_report(Odd(), Odd(), Odd(), Odd()))

    def test_no_name_path_blog_article_key_token_draft_number_or_message_reaches_the_report_from_any_field(self):
        """금지 모양 — 사용자 이름·폴더 경로·블로그 이름·글 내용·키·토큰·초안 번호·오류 메시지 글을 **어느 칸에 넣어도** 글에 한 조각도 남지 않는다."""
        for bad in ADVERSARIAL:
            reports = {"버전 글": dg.build_report(VersionInfo(bad, "file"), 22631, 150, "A_CODE"), "커밋": dg.build_report(VersionInfo("v1.0.0", "file", bad), 22631, 150, "A_CODE"),
                       "윈도 빌드": dg.build_report(GOOD, bad, 150, "A_CODE"), "배율": dg.build_report(GOOD, 22631, bad, "A_CODE"), "오류 코드": dg.build_report(GOOD, 22631, 150, bad),
                       "버전 객체": dg.build_report(bad, 22631, 150, "A_CODE")}
            for where, report in reports.items():
                if where == "오류 코드" and bad in CODE_SHAPED:
                    continue                                                                          # 코드 모양 그대로인 값은 코드 칸의 설계상 통과한다(위 `CODE_SHAPED` 설명) — 다른 칸에서는 막힌다
                for piece in SECRET_PIECES:
                    self.assertNotIn(piece, report, f"{where} 에 넣은 {bad!r} 의 조각 {piece!r} 이 글에 남았다")

    def test_a_failure_with_a_message_full_of_private_things_gives_only_its_code(self):
        state = app_state.AppState(version=GOOD)
        state.apply_failure(JobFailure(MESSAGE + " " + BLOG_NAME + " " + CANARY_GITHUB, code="HOME_DOWN"), WHEN)
        report = state.diagnostic_report(22631, 150)
        assert_shape(self, report)
        self.assertEqual(lines_of(report)[-1], "last_error_code: HOME_DOWN")
        for piece in SECRET_PIECES:
            self.assertNotIn(piece, report, piece)

    def test_a_code_made_of_a_key_or_a_path_or_a_message_becomes_unknown_in_the_report(self):
        for bad in (CANARY_GITHUB, CANARY_GOOGLE, WINDOWS_PATH, MESSAGE, DRAFT_ID, BLOG_NAME):
            state = app_state.AppState(version=GOOD)
            state.apply_failure(JobFailure("문장", code=bad), WHEN)
            self.assertEqual(lines_of(state.diagnostic_report(1000, 100))[-1], "last_error_code: unknown", repr(bad))

    def test_the_report_has_no_time_no_data_folder_no_user_and_exactly_these_line_names(self):
        report = dg.build_report(GOOD, 22631, 150, "GIT_PUSH_AUTH")
        self.assertEqual([line.split(": ")[0] for line in lines_of(report)[1:]], list(dg.FIELDS))
        self.assertNotRegex(report, r"\d{4}-\d\d-\d\d")                                                  # 시각도 담지 않는다 — 다섯 가지뿐
        self.assertNotRegex(report, r"[A-Za-z]:[\\/]|[\\/]{2}|~|https?:")
        self.assertEqual(report.count("\n"), 5)
        self.assertNotIn("\r", report)


class ReadersTest(unittest.TestCase):
    @staticmethod
    def getter(**fields):
        class Version:
            pass
        found = Version()
        for name, value in fields.items():
            setattr(found, name, value)
        return lambda: found

    def test_the_build_is_the_larger_of_the_reported_build_and_the_kernel_version_third_number(self):
        self.assertEqual(dg.windows_build_number(self.getter(build=22631, platform_version=(10, 0, 22621))), 22631)        # 이 PC 의 모습 — `winver` 와 같은 쪽이 이긴다
        self.assertEqual(dg.windows_build_number(self.getter(build=9200, platform_version=(10, 0, 22621))), 22621)         # 호환 설정이 걸려 낮게 나온 build 는 이긴다고 하지 않는다
        self.assertEqual(dg.windows_build_number(self.getter(build=19045)), 19045)
        self.assertEqual(dg.windows_build_number(self.getter(platform_version=(10, 0, 26100))), 26100)
        self.assertEqual(dg.windows_build_number(self.getter(build=19045, platform_version=(10, 0))), 19045)              # 짧은 튜플은 건너뛴다

    def test_an_unreadable_or_odd_answer_is_none_and_never_an_error(self):
        for odd in (self.getter(build=True), self.getter(build=0), self.getter(build=-3), self.getter(build=10 ** 7), self.getter(build="22631"), self.getter(build=22631.0), self.getter(), self.getter(platform_version="x")):
            self.assertIsNone(dg.windows_build_number(odd))
        self.assertIsNone(dg.windows_build_number(lambda: None))

        def broken():
            raise OSError("읽을 수 없다")
        self.assertIsNone(dg.windows_build_number(broken))
        self.assertIsNone(dg.windows_build_number(lambda: Odd()))

    def test_without_the_windows_only_function_the_answer_is_none_on_any_system(self):
        """리눅스 CI 흉내 — `sys.getwindowsversion` 이 없어도 호출이 안전하다(가져오기도 윈도 전용 모듈을 쓰지 않는다)."""
        with mock.patch.object(dg.sys, "getwindowsversion", None, create=True):
            self.assertIsNone(dg.windows_build_number())

    @unittest.skipUnless(os.name == "nt", "윈도에서만 실제 윈도 빌드 번호가 있다")
    def test_on_windows_the_real_reading_is_a_plausible_whole_number(self):
        number = dg.windows_build_number()
        self.assertIsInstance(number, int)
        self.assertGreaterEqual(number, 10000)
        self.assertLess(number, 1_000_000)
        self.assertEqual(dg.build_text(number), str(number))

    @unittest.skipIf(os.name == "nt", "윈도가 아닌 시스템에서만 윈도 빌드 번호가 없다")
    def test_off_windows_the_real_reading_is_none_and_the_report_says_unknown(self):
        self.assertIsNone(dg.windows_build_number())
        self.assertEqual(lines_of(dg.build_report(GOOD, dg.windows_build_number(), 100, None))[3], "windows_build: unknown")

    def test_the_scale_comes_from_a_pixel_ratio_as_a_whole_percent_and_odd_ratios_are_none(self):
        for ratio, percent in ((1.0, 100), (1.25, 125), (1.5, 150), (1.75, 175), (2.0, 200), (2.5, 250), (3.0, 300), (1, 100), (0.5, 50), (6.0, 600), (1.1, 110), (1.15, 115), (2.25, 225), (1.005, 100)):          # 1.15 는 소수 오차로 114.999… — 버림이 아니라 반올림이어야 115 다
            self.assertEqual(dg.scale_percent(ratio), percent, ratio)
        for odd in (None, True, False, 0, 0.0, 0.49, 6.01, -1.0, float("nan"), float("inf"), float("-inf"), "1.5", [1.5], Odd()):
            self.assertIsNone(dg.scale_percent(odd), repr(odd))
        self.assertEqual(dg.scale_text(dg.scale_percent(1.5)), "150%")
        self.assertEqual(dg.scale_text(dg.scale_percent(None)), dg.UNKNOWN)


class AppStateTest(unittest.TestCase):
    def state(self, **kwargs):
        return app_state.AppState(version=kwargs.pop("version", GOOD), **kwargs)

    def test_a_fresh_state_has_no_error_and_a_report_with_the_given_version_and_environment(self):
        state = self.state()
        self.assertIsNone(state.last_error_code())
        self.assertEqual(state.diagnostic_report(22631, 150), "ChanceBlog Desktop 진단 정보\nversion: v0.1.0-preview.1\ncommit: abcdef0\nwindows_build: 22631\ndisplay_scale: 150%\nlast_error_code: none")
        self.assertEqual(lines_of(self.state(version=None).diagnostic_report())[1:3], ["version: dev", "commit: unknown"])             # 버전을 못 받은 상태 — 화면의 '개발 버전' 과 같다
        self.assertEqual(lines_of(self.state(version=VersionInfo("개발 버전", "dev")).diagnostic_report())[1:3], ["version: dev", "commit: unknown"])

    def test_the_home_and_settings_failures_both_count_and_the_later_one_wins(self):
        state = self.state()
        state.apply_failure(JobFailure("홈 문장", code="HOME_DOWN"), WHEN)
        self.assertEqual(state.last_error_code(), "HOME_DOWN")
        state.apply_conn_failure(JobFailure("설정 문장", code="CONN_DOWN"), WHEN + datetime.timedelta(seconds=30))
        self.assertEqual(state.last_error_code(), "CONN_DOWN")
        state.apply_failure(JobFailure("다시 홈 문장", code="HOME_AGAIN"), WHEN + datetime.timedelta(minutes=2))
        self.assertEqual(state.last_error_code(), "HOME_AGAIN")
        self.assertEqual(lines_of(state.diagnostic_report(22631, 125))[-1], "last_error_code: HOME_AGAIN")

    def test_a_recovered_screen_no_longer_counts_and_a_state_with_no_failure_left_says_none(self):
        state = self.state()
        state.apply_failure(JobFailure("홈", code="HOME_DOWN"), WHEN)
        state.apply_conn_failure(JobFailure("설정", code="CONN_DOWN"), WHEN + datetime.timedelta(seconds=30))
        state.apply_connections(services.FakeConnectionsProvider().load_connections(lambda *a: None, lambda: False), WHEN + datetime.timedelta(minutes=1))
        self.assertEqual(state.last_error_code(), "HOME_DOWN")                                          # 설정은 나았으니 아직 남은 홈의 실패가 마지막이다
        state.apply_home(services.FakeHomeProvider().load_home(lambda *a: None, lambda: False))
        self.assertIsNone(state.last_error_code())
        self.assertEqual(lines_of(state.diagnostic_report(22631, 100))[-1], "last_error_code: none")

    def test_every_screen_controller_failure_counts_with_its_own_time(self):
        for name, apply in (("candidates", lambda s, f, w: s.candidates.apply_load_failed(f, w)),
                            ("drafts", lambda s, f, w: s.drafts.apply_unexpected(type(f.code, (Exception,), {})(), w)),            # 초안은 만들 후보가 있어야 실패를 받는다 — 예상 못 한 오류는 예외 클래스 이름이 코드다
                            ("seeds", lambda s, f, w: s.seeds.apply_load_failed(f, w)), ("blogs", lambda s, f, w: s.blogs.apply_load_failed(f, w))):
            with self.subTest(controller=name):
                state = self.state()
                apply(state, JobFailure("문장", code=name.upper() + "_DOWN"), WHEN)
                self.assertEqual(state.last_error_code(), name.upper() + "_DOWN")
                state.apply_failure(JobFailure("더 늦은 홈", code="LATER_HOME"), WHEN + datetime.timedelta(seconds=1))
                self.assertEqual(state.last_error_code(), "LATER_HOME")
                apply(state, JobFailure("가장 늦은", code="LATEST_ONE"), WHEN + datetime.timedelta(seconds=5))
                self.assertEqual(state.last_error_code(), "LATEST_ONE")

    def test_the_backup_card_failure_counts_when_the_backup_pair_exists_and_is_skipped_when_it_does_not(self):
        plain = self.state()
        self.assertIsNone(plain.backups)
        self.assertIsNone(plain.last_error_code())                                                       # 백업 짝이 없어도 예외 없이 건너뛴다
        paired = self.state(provider=services.FakeHomeProvider(backups=True))
        self.assertIsNotNone(paired.backups)
        paired.backups.apply_load_failed(JobFailure("백업 문장", code="BACKUP_DOWN"), WHEN)
        self.assertEqual(paired.last_error_code(), "BACKUP_DOWN")

    def test_the_unexpected_error_name_is_the_code_and_its_text_is_never_read(self):
        state = self.state()
        state.apply_conn_unexpected(ValueError(WINDOWS_PATH + " " + CANARY_GITHUB), WHEN)
        self.assertEqual(state.last_error_code(), "ValueError")
        report = state.diagnostic_report(22631, 150)
        self.assertEqual(lines_of(report)[-1], "last_error_code: ValueError")
        for piece in SECRET_PIECES:
            self.assertNotIn(piece, report, piece)

    def test_the_report_is_made_when_asked_so_a_later_failure_shows_up_the_next_time(self):
        state = self.state()
        before = state.diagnostic_report(22631, 150)
        state.apply_failure(JobFailure("문장", code="HOME_DOWN"), WHEN)
        after = state.diagnostic_report(22631, 150)
        self.assertNotEqual(before, after)
        self.assertEqual((lines_of(before)[-1], lines_of(after)[-1]), ("last_error_code: none", "last_error_code: HOME_DOWN"))


    # ---- 홈 새 구역이 따로 읽지 못한 구역(검증 S 의 SP-3) — 홈 전체는 성공이라 `failure` 는 None 이지만 구역 오류 카드는 보인다 ----
    @staticmethod
    def board(channels=(), drafts=None, recent=None):
        return services.HomeData(board=services.BoardData(channels=tuple(channels), drafts=drafts or services.ListRead(), recent=recent or services.ListRead()))

    def test_a_home_board_section_that_could_not_be_read_counts_with_its_own_code_even_though_the_whole_home_loaded(self):
        failed = lambda code: services.ServiceFailure("구역 문장 " + MESSAGE, code=code)
        state = self.state()
        state.apply_home(self.board(channels=(services.ChannelRead(key="A", state="failed", failure=failed("TOPIC_STORE_CORRUPT")), services.ChannelRead(key="B"))))
        self.assertIsNone(state.failure)                                                                  # 홈 전체의 실패는 없다
        self.assertEqual(state.last_error_code(), "TOPIC_STORE_CORRUPT")
        only_drafts = self.state()
        only_drafts.apply_home(self.board(channels=(services.ChannelRead(key="A"), services.ChannelRead(key="B")), drafts=services.ListRead(state="failed", failure=failed("DRAFT_STORE_CORRUPT"))))
        self.assertEqual(only_drafts.last_error_code(), "DRAFT_STORE_CORRUPT")
        only_recent = self.state()
        only_recent.apply_home(self.board(recent=services.ListRead(state="failed", failure=failed("PUBLISH_RECORD_BROKEN"))))
        self.assertEqual(only_recent.last_error_code(), "PUBLISH_RECORD_BROKEN")
        report = state.diagnostic_report(22631, 150)
        self.assertEqual(lines_of(report)[-1], "last_error_code: TOPIC_STORE_CORRUPT")
        for piece in SECRET_PIECES:
            self.assertNotIn(piece, report, piece)                                                        # 구역 문장(경로가 든)은 읽지도 않는다

    def test_board_failures_have_no_time_so_the_first_section_wins_among_them_a_timed_failure_beats_them_and_an_empty_failure_is_unknown(self):
        failed = lambda code: services.ServiceFailure("문장", code=code)
        both = self.board(channels=(services.ChannelRead(key="A", state="failed", failure=failed("FIRST_SECTION")), services.ChannelRead(key="B", state="failed", failure=failed("SECOND_SECTION"))),
                          drafts=services.ListRead(state="failed", failure=failed("THIRD_SECTION")))
        state = self.state()
        state.apply_home(both)
        self.assertEqual(state.last_error_code(), "FIRST_SECTION")                                         # 시각이 없으면 앞선 구역이 이긴다(추천 A → B → 작성 중 초안 → 최근 발행)
        state.apply_conn_failure(JobFailure("설정 문장", code="CONN_DOWN"), WHEN)
        self.assertEqual(state.last_error_code(), "CONN_DOWN")                                             # 시각이 있는 실패가 먼저다
        blank = self.state()
        blank.apply_home(self.board(recent=services.ListRead(state="failed")))                              # 못 읽었다는 표시는 있는데 실패 값이 없다
        self.assertEqual(blank.last_error_code(), "")                                                      # 코드를 모르는 실패 — 글에서는 `unknown`
        self.assertEqual(lines_of(blank.diagnostic_report(22631, 150))[-1], "last_error_code: unknown")

    def test_a_healthy_or_missing_board_adds_nothing_an_unavailable_section_is_not_a_failure_and_a_good_reload_clears_the_old_one(self):
        plain = self.state()
        self.assertIsNone(plain.last_error_code())                                                         # 홈을 아직 못 읽었다 — 구역도 없다
        plain.apply_home(services.HomeData(board=None))
        self.assertIsNone(plain.last_error_code())                                                         # 새 구역을 읽지 않는 공급자('연결 전')
        plain.apply_home(self.board(channels=(services.ChannelRead(key="A", state="unavailable", reason="missing"), services.ChannelRead(key="B", enabled=False))))
        self.assertIsNone(plain.last_error_code())                                                         # 보관함이 없거나 꺼진 구역은 오류가 아니다
        state = self.state()
        state.apply_home(self.board(drafts=services.ListRead(state="failed", failure=services.ServiceFailure("문장", code="DRAFT_STORE_CORRUPT"))))
        self.assertEqual(state.last_error_code(), "DRAFT_STORE_CORRUPT")
        state.apply_home(self.board(drafts=services.ListRead()))                                           # 다시 읽어 나았다
        self.assertIsNone(state.last_error_code())

    def test_the_saved_drafts_list_that_could_not_be_read_counts_with_its_code_without_a_time_and_a_good_reload_clears_it(self):
        """초안 작성은 저장한 초안 목록의 읽기 실패를 따로 든다(`list_state`·`list_failure`, 시각 없음) — 목록 자리에 오류와 `다시 시도` 가 보이는 읽기 실패라서 마지막 오류 코드에 든다(검증 S 의 SP-3 을 따라 읽다가 찾은 같은 틈)."""
        state = self.state()
        state.drafts.store_pending = {"op": "list"}
        self.assertTrue(state.drafts.apply_list_failed(JobFailure("목록 문장 " + MESSAGE, code="DRAFT_LIST_DOWN")))
        self.assertEqual(state.last_error_code(), "DRAFT_LIST_DOWN")
        report = state.diagnostic_report(22631, 150)
        self.assertEqual(lines_of(report)[-1], "last_error_code: DRAFT_LIST_DOWN")
        for piece in SECRET_PIECES:
            self.assertNotIn(piece, report, piece)                                                        # 목록 문장(경로가 든)은 읽지도 않는다
        state.apply_conn_failure(JobFailure("설정 문장", code="CONN_DOWN"), WHEN)
        self.assertEqual(state.last_error_code(), "CONN_DOWN")                                             # 시각이 있는 실패가 먼저다
        recovered = self.state()
        recovered.drafts.store_pending = {"op": "list"}
        recovered.drafts.apply_list_failed(JobFailure("목록 문장", code="DRAFT_LIST_DOWN"))
        recovered.drafts.store_pending = {"op": "list"}
        self.assertTrue(recovered.drafts.apply_listing(None))                                              # 다시 읽어 나았다
        self.assertIsNone(recovered.last_error_code())
        blank = self.state()
        blank.drafts.store_pending = {"op": "list"}
        blank.drafts.apply_list_failed(None)                                                               # 못 읽었다는 표시는 있는데 실패 값이 없다
        self.assertEqual(blank.last_error_code(), "")
        self.assertIsNone(self.state().last_error_code())                                                  # 읽지 않았거나 읽는 중인 목록은 실패가 아니다


    def test_a_failed_write_leaves_a_notice_but_no_error_code_which_is_the_documented_limit(self):
        """알려 둔 한계(D-541 ③) — 단추를 눌러 하는 일(저장·복원·만들기)의 실패는 컨트롤러가 안내 줄(`notice`)만 남기고 코드를 상태로 들지 않으므로 그 뒤에 복사해도 `none` 이다. 문서가 이것을 사실대로 적었다는 약속을
        시험이 못박는다 — 쓰기 실패 코드까지 담게 바꾸면(운영자에게 묻는 일, D-543) 이 시험과 D-541·UI_STATES·TROUBLESHOOTING 을 함께 고친다(검증 S 의 SP-3)."""
        paired = self.state(provider=services.FakeHomeProvider(backups=True))
        failure = JobFailure("쓰기 문장 " + MESSAGE, code="FILE_WRITE_FAILED")
        for name in ("blogs", "seeds", "candidates", "backups"):
            controller = getattr(paired, name)
            controller.apply_write_failed(failure)
            self.assertEqual(controller.notice[0], "error", name)                                          # 화면에는 오류 안내가 남는다
            self.assertIsNone(paired.last_error_code(), name)                                              # 그러나 코드는 안 모은다 — `none`
        self.assertEqual(lines_of(paired.diagnostic_report(22631, 150))[-1], "last_error_code: none")

    def test_failures_at_the_very_same_time_are_decided_by_the_slot_order_home_settings_candidates_drafts_seeds_blogs_backups(self):
        """같은 시각의 실패가 여럿이면 앞선 칸이 이긴다(D-541 ① 의 순서)를 앱 상태 수준에서 못박는다(검증 Q 의 QP-12) — 뒤 칸부터 같은 시각의 실패를 하나씩 더해 갈 때마다 방금 더한(더 앞선) 칸이 이겨야 한다."""
        state = self.state(provider=services.FakeHomeProvider(backups=True))
        steps = (("backups", lambda failure: state.backups.apply_load_failed(failure, WHEN)), ("blogs", lambda failure: state.blogs.apply_load_failed(failure, WHEN)),
                 ("seeds", lambda failure: state.seeds.apply_load_failed(failure, WHEN)), ("drafts", lambda failure: state.drafts.apply_unexpected(type("DRAFTS_SLOT", (Exception,), {})(), WHEN)),
                 ("candidates", lambda failure: state.candidates.apply_load_failed(failure, WHEN)), ("settings", lambda failure: state.apply_conn_failure(failure, WHEN)),
                 ("home", lambda failure: state.apply_failure(failure, WHEN)))
        for name, apply in steps:
            apply(JobFailure("문장", code=name.upper() + "_SLOT"))
            self.assertEqual(state.last_error_code(), name.upper() + "_SLOT", name)


class SettingsViewTest(unittest.TestCase):
    DATA = services.ConnectionsData(purposes=services.sample_connections("normal"), sample=True)

    def test_the_info_group_carries_the_copy_button_text_in_every_state_including_the_error_without_data(self):
        for state in ("loading", "normal", "empty", "error", "partial", "offline"):
            for data in (self.DATA, None):
                info = sv.build_settings_view(data, state, failure=JobFailure("문장", code="X_DOWN") if state == "error" else None, error_diag="code: X_DOWN", version=GOOD)["info"]
                self.assertEqual(info["copy"], {"text": "진단 정보 복사", "note": text.T["diag_copy_note"]}, (state, data is None))
                self.assertEqual(info["version"]["text"], "v0.1.0-preview.1 · 커밋 abcdef0")                # 오류 상태에서도 버전·커밋 줄이 뷰모델에 있다(F022·F040)

    def test_the_view_model_never_holds_the_text_that_gets_copied(self):
        state = app_state.AppState(version=GOOD)
        state.apply_failure(JobFailure("문장", code="HOME_DOWN"), WHEN)
        view = state.settings_view()
        shown = repr(view)
        self.assertNotIn(state.diagnostic_report(22631, 150), shown)
        self.assertNotIn("last_error_code", shown)
        self.assertNotIn("windows_build", shown)

    def test_the_new_texts_say_what_is_copied_and_what_is_not_without_forbidden_words_or_the_word_commit(self):
        for key in ("diag_copy", "diag_copy_note", "diag_copy_done", "diag_copy_failed"):
            value = text.T[key]
            self.assertTrue(value.strip(), key)
            self.assertNotIn("~", value, key)
            for word in text.FORBIDDEN:
                self.assertNotIn(word, value, (key, word))
        note = text.T["diag_copy_note"]
        for needle in ("앱 버전", "빌드 정보", "윈도 빌드 번호", "화면 배율", "마지막 오류 코드", "뿐", "이름", "폴더", "글", "키", "담기지 않아요"):
            self.assertIn(needle, note, needle)
        self.assertNotIn("커밋", note)                                                                    # 커밋 줄이 없는 개발 화면의 정보 카드 글에 '커밋' 이 없다는 기존 시험(`test_packaging_qt`)과 맞물린다
        self.assertEqual(text.T["diag_copy"], "진단 정보 복사")
        self.assertEqual(text.T["diag_copy_failed"], text.T["credit_failed"])                              # 복사 실패는 다른 복사 단추와 같은 문장이다

    def test_the_copy_notices_say_exactly_what_happened_and_promise_nothing_more(self):
        """복사 완료 안내의 글을 못박는다(검증 Q 의 QP-2) — 이 단추는 클립보드에 복사할 뿐이라 '보냈어요·전달·접수·운영자에게·곧 답을 드려요' 처럼 없는 동작이나 결과를 약속하는 말이 새 문구 어디에도 들어오면 안 된다."""
        self.assertEqual(text.T["diag_copy_done"], "진단 정보를 복사했어요. 도움을 받을 때 붙여 넣어 주세요.")
        for key in ("diag_copy", "diag_copy_note", "diag_copy_done", "diag_copy_failed"):
            for word in ("보냈", "보내", "전송", "전달", "접수", "제출", "운영자에게", "답을", "곧 ", "해결", "고쳐"):
                self.assertNotIn(word, text.T[key], (key, word))


class SourceRulesTest(unittest.TestCase):
    """새 순수 모듈은 윈도·Qt·파일·외부 접속을 모른다 — 리눅스 CI 에서도 가져오기가 안전하고 복사는 기존 길(앱 틀의 `copy`) 하나뿐이다."""

    def tree(self, name):
        return ast.parse((CORE / name).read_text(encoding="utf-8"))

    def test_the_new_pure_modules_import_nothing_outside_the_standard_library_and_the_text_table(self):
        allowed = {"__future__", "re", "sys", "text"}
        for name in ("diagnostics.py", "diag_text.py"):
            imported = set()
            for node in ast.walk(self.tree(name)):
                if isinstance(node, ast.Import):
                    imported |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or "")
            self.assertLessEqual(imported, allowed, name)
            self.assertFalse({"PySide6", "ctypes", "msvcrt", "winreg", "subprocess", "socket", "os", "platform", "pathlib", "urllib", "http", "tempfile", "shutil", "io"} & imported, name)

    def test_the_diagnostics_module_opens_no_file_calls_no_process_and_reads_neither_a_message_nor_a_path(self):
        source = (CORE / "diagnostics.py").read_text(encoding="utf-8")
        calls = {ast.unparse(node.func) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)}
        self.assertFalse({"open", "print", "exec", "eval", "compile", "__import__"} & calls)
        attributes = {node.attr for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Attribute)}
        self.assertFalse({"user_message", "message", "args", "detail", "__cause__", "__traceback__", "__context__", "write_text", "read_text", "mkdir", "environ", "getenv", "expanduser", "home"} & attributes)

    def test_the_shell_reaches_the_clipboard_only_through_its_existing_copy_and_the_new_method_adds_no_write(self):
        tree = ast.parse(SHELL.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "copy_diagnostics")
        calls = [ast.unparse(node.func) for node in ast.walk(method) if isinstance(node, ast.Call)]
        self.assertIn("self.copy", calls)
        self.assertFalse([call for call in calls if "clipboard" in call.lower() or call in ("open", "print") or call.startswith(("os.", "subprocess", "socket"))], calls)
        environment = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_read_environment")
        used = {ast.unparse(node.func) for node in ast.walk(environment) if isinstance(node, ast.Call)}
        self.assertFalse([call for call in used if call.startswith(("os.", "subprocess", "socket", "open"))], used)


class DocsTest(unittest.TestCase):
    ROW = re.compile(r"^\| (D-5(?:39|4[0-3])) \|", re.MULTILINE)

    @staticmethod
    def read(rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_the_decision_rows_d539_to_d543_exist_once_each_and_name_what_they_decide(self):
        decisions = self.read("docs/DECISIONS.md")
        self.assertEqual(self.ROW.findall(decisions), ["D-539", "D-540", "D-541", "D-542", "D-543"])
        rows = {match.group(1): line for line in decisions.splitlines() if (match := self.ROW.match(line))}
        words = {"D-539": ("진단 정보 복사", "F035", "diagnostics.py", "unknown", "다섯"), "D-540": ("F022", "F040", "사이드바", "오류 상태", "건드리지 않"),
                 "D-541": ("마지막 오류 코드", "failed_at", "한계", "errors.log", "홈 새 구역", "저장한 초안 목록", "`none` 은", "안내 줄", "FailureCodeOriginRuleTest"),
                 "D-542": ("새 시험", "변이", "원복", "바뀐 기존 시험", "11,644", "11,726", "글자 상자 훑기", "소스 규칙", "코드 모양"), "D-543": ("운영자", "다른 화면", "오류 카드", "물을 것 둘", "붙여 넣", "쓰기")}
        for number, needles in words.items():
            for needle in needles:
                self.assertIn(needle, rows[number], (number, needle))

    def test_the_ui_docs_the_troubleshooting_page_and_the_changelog_tell_the_same_story(self):
        states, components, trouble, changelog = (self.read(name) for name in ("docs/UI_STATES.md", "docs/UI_COMPONENTS.md", "docs/TROUBLESHOOTING.md", "CHANGELOG.md"))
        for needle in ("진단 정보 복사", "D-539", "D-540", "오류 카드 아래", "접이식 없이", "unknown", "앱 버전", "화면 배율", "마지막 오류 코드", "읽기 실패", "안내 줄", "저장한 초안 목록"):
            self.assertIn(needle, states, needle)
        for needle in ("진단 정보 복사", "info_card", "copy_diagnostics", "diag-copy", "D-539"):
            self.assertIn(needle, components, needle)
        for needle in ("진단 정보 복사", "설정", "정보", "붙여 넣", "안내 문장", "none"):
            self.assertIn(needle, trouble, needle)
        for needle in ("진단 정보 복사", "F035", "F022", "D-539", "D-543"):
            self.assertIn(needle, changelog, needle)

    def test_the_new_doc_text_has_no_ascii_tilde_no_http_link_and_no_unfilled_placeholder(self):
        for rel in ("docs/UI_STATES.md", "docs/UI_COMPONENTS.md", "docs/TROUBLESHOOTING.md", "docs/DECISIONS.md", "CHANGELOG.md"):
            body = self.read(rel)
            added = [line for line in body.splitlines() if "D-539" in line or "진단 정보 복사" in line]
            self.assertTrue(added, rel)
            for line in added:
                self.assertNotIn("@@", line, rel)
                self.assertNotRegex(line, r"(?i)https?://|www[.]", rel)
                self.assertNotIn("~", line, rel)


if __name__ == "__main__":
    unittest.main()
