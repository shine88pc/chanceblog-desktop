"""오류 기록(작은 로그 파일) 시험 — AP14, 확인 015 승인 9번(데스크톱 F034, 결정 D-488): 앱이 처리하지 못한 오류가 나도 남는 기록이 없어 알리기 어려웠다 → 데이터 폴더 안에
**오류 이름과 코드 위치만** 가려서 남기는 256 KB 짜리 세 개 돌려쓰기 로그(`security/errorlog.py`)를 허용했다. 이 시험은 그 한계들이 지켜지는지 본다.

지키는 것(모두 PySide6 없이 돈다 — CI 와 같은 조건):
  1) 켜 두기(`arm`)만으로는 아무것도 읽거나 만들지 않는다 — 폴더도 파일도 없다. **첫 오류가 났을 때 처음 만든다**(`logs/errors.log`).
  2) 줄에는 시각·갈래·**오류 클래스 이름**·**코드 위치(파일 이름:줄, 가장 안쪽 여섯)** 뿐이다. `CANARY_` 가짜 비밀·가짜 경로·가짜 글이 든 오류 메시지는 한 글자도 남지 않고(메시지는 읽지도 않는다), 위치의 폴더 앞부분(사용자 이름이 든 절대경로)도 없다.
     이름의 글자표(클래스·파일·Qt 분류 이름)는 U+0001 에서 U+024F 까지 전부와 위험한 글자 몇 개를 이름의 앞·가운데·끝에 끼워, 클래스·파일 이름은 U+0000 에서 U+10FFFF 까지 전체를 앞·가운데에 끼워
     시험이 따로 적은 정답과 견준다(`NarrowAlphabetTest`). 추적은 아무리 깊어도 가장 안쪽 여섯 곳이 줄에 들어간다(`DeepTraceTest` — 깊이 300·600·재귀 한도·3만 단계).
  3) 줄은 앱의 공통 가림 규칙(`security/mask.py` 의 `mask`)을 한 번 더 거친다 — 이 모듈에 새 가림 규칙은 없다.
  4) 256 KB 를 넘기게 되면 돌려쓰고(경계는 1바이트 단위로 본다) 파일은 셋(`errors.log`·`.1`·`.2`)을 넘지 않으며 가장 오래된 것부터 사라진다. 돌려쓰기는 이름 바꾸기뿐이다(옛 파일을 먼저 지우지 않는다).
     돌려쓰기가 막히면 한도를 넘겨 쓰지 않고 그 줄을 버린다 — 첫 단계(`.1` → `.2`)가 막히면 옛 파일 셋은 그대로이고, 첫 단계가 끝난 뒤 현재 파일 쪽이 막히면 `.2` 가 옛 `.1` 의 내용이 된다(옛 `.2` 는 사라진다).
  5) 쓰기·폴더 만들기·이름 바꾸기·폴더 해석이 실패해도 예외 없이 `False` 이고 다음 오류는 다시 쓸 수 있다. 정해진 1분 구간마다 30줄까지만 쓴다. `KeyboardInterrupt`·`SystemExit` 는 오류가 아니라 남기지 않는다.
  6) 공통 경계(`security/boundary.py`)의 훅 셋·Qt 메시지와 화면의 한 줄 기록(`report_unexpected`)에서 들어오고, 경계를 되돌리면 꺼진다. **화면(GUI) 진입점만 켠다** — 예시 화면(`--sample`)은 켜지 않는다.
  7) 백업에 넣지 않고(담지 않는 것 목록에 `logs/`) 복원이 건드리지 않는다.
  8) 네트워크·하위 프로세스·표준 출력·표준 오류·`logging`·`traceback`·`faulthandler` 가 없다 — 가져오는 것은 아래의 표준 라이브러리 몇 개와 `mask` 뿐이다.
  9) 문서(SECURITY·TROUBLESHOOTING·UI_STATES·UI_DESIGN_SPEC)가 '파일에 쓰지 않는다·로그 파일은 아직 없다' 가 아니라 사실(작은 오류 기록 파일이 있다)을 적는다.
  10) 문서가 '기록이 닿지 않는다' 고 적은 길(묶음 실행 파일의 시작 실패·작업 스레드가 삼킨 오류·네이티브 충돌·데이터 폴더를 풀지 못함)을 낱말이 아니라 **동작으로** 확인한다(`StatedLimitsAreRealTest` —
      기록을 켠 채 그 길에 실패를 시켜 `logs` 폴더가 안 생기고, 같은 설정에서 훅으로 들어온 오류는 파일을 만든다는 대조도 함께 본다).
가짜 비밀은 `CANARY_` 로 시작하는 조립 문자열이다. 임시 폴더만 쓰고 사용자의 데이터 폴더·네트워크를 건드리지 않는다.
"""
import ast
import contextlib
import errno
import hashlib
import io
import os
import re
import shutil
import socket
import string
import sys
import tempfile
import threading
import traceback
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import backup_support as bs  # noqa: E402
import secret_support as sec  # noqa: E402

from chanceblog_desktop.security import backup_note, boundary, errorlog  # noqa: E402
from chanceblog_desktop.security import mask as mask_module  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service.context import Workspace  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"
FIXED = datetime(2026, 11, 15, 7, 41, 5, tzinfo=timezone.utc)
STAMP = "2026-11-15T07:41:05Z"
LINE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z (?:main|thread|unraisable|slot|qt) [A-Za-z_][A-Za-z0-9_]{0,63} (?:-|[A-Za-z0-9_.\-?]+(?::\d+)?(?: < [A-Za-z0-9_.\-?]+(?::\d+)?)*)")
KEY = "AI" + "za" + ("CANARY_ELK_" + hashlib.sha256(b"app15-errorlog-key").hexdigest())[:35]          # 구글 키 모양(35자) — 안에 CANARY 가 든다(런타임 조립)


def fixed_clock():
    return FIXED


def canary_message():
    """오류 메시지에 들어갈 수 있는 모든 것 — 가짜 비밀·가짜 키 모양·가짜 절대 경로·가짜 글 본문."""
    return ("CANARY_BODY 오늘의 비밀 글 본문 " + sec.make_canary("ELMSG") + " " + KEY + " C:\\Users\\" + sec.make_canary("ELUSER") + "\\Secret Folder\\note.txt")


def caught(message="가짜 오류", kind=ValueError):
    """오류를 하나 일으켜 잡아 돌려준다(추적이 붙어 있다)."""
    try:
        raise kind(message)
    except kind as error:
        return error


def caught_deep(message):
    def inner():
        raise RuntimeError(message)

    def outer():
        inner()

    try:
        outer()
    except RuntimeError as error:
        return error


def caught_in_foreign_file(message, filename):
    """다른 파일(폴더가 든 가짜 이름)에서 난 오류 — 추적의 파일 이름이 `filename` 이다."""
    namespace = {}
    exec(compile("def boom(message):\n    raise ValueError(message)\n", filename, "exec"), namespace)
    try:
        namespace["boom"](message)
    except ValueError as error:
        return error


def caught_chain(depth, filename="chain_mod.py"):
    """`depth` 개의 함수가 차례로 부르고 가장 안쪽이 오류를 내는 모양 — 함수마다 줄이 달라(`f{n}` 의 부르는 줄 = `2n + 2`) 추적의 위치를 하나씩 구별할 수 있다.
    추적은 부른 쪽(이 시험 파일) 한 곳 + 함수 `depth` 곳이다."""
    source = []
    for number in range(depth):
        source.append(f"def f{number}():")
        source.append(f"    f{number + 1}()" if number + 1 < depth else "    raise RuntimeError('깊다')")
    namespace = {}
    exec(compile("\n".join(source) + "\n", filename, "exec"), namespace)
    try:
        namespace["f0"]()
    except RuntimeError as error:
        return error


# 좁은 글자표의 '정답' — 소스의 정규식을 가져다 쓰지 않고 시험이 따로 적는다(소스 쪽 글자표가 한 글자라도 넓어지면 아래 전수 시험이 빨개진다).
LETTERS, DIGITS = set(string.ascii_letters), set(string.digits)
CLASS_FIRST, CLASS_REST = LETTERS | {"_"}, LETTERS | DIGITS | {"_"}
FILE_FIRST, FILE_REST = LETTERS | DIGITS | {"_"}, LETTERS | DIGITS | {"_", ".", "-"}
CLASS_FIRST_SET, CLASS_REST_SET = frozenset(CLASS_FIRST), frozenset(CLASS_REST)                    # 전체 유니코드 훑기가 빠르게 쓰는 모음(정답은 위의 글자 모음 그대로다)
FILE_FIRST_SET, FILE_REST_SET = frozenset(FILE_FIRST), frozenset(FILE_REST)
SWEEP = [chr(code) for code in range(1, 0x250)] + list("\u202e\u2028\u2029\u200b\ufeff한٣①")          # U+0001 에서 U+024F 까지 전부 + 방향 바꿈·줄 나눔·폭 없는 공백·한글·아랍 숫자·동그라미 숫자


def class_expected(name):
    narrow = 0 < len(name) <= 64 and name[0] in CLASS_FIRST and all(char in CLASS_REST for char in name[1:])
    return name if narrow else "UnknownError"


def narrow_file(text):
    return 0 < len(text) <= 64 and text[0] in FILE_FIRST and all(char in FILE_REST for char in text[1:])


def file_expected(path):
    last = path.replace("\\", "/").split("/")[-1]                                # 윈도·유닉스 구분자 앞의 폴더는 뗀다
    return last if narrow_file(last) else "?"


class Base(unittest.TestCase):
    def setUp(self):
        self.assertIsNone(errorlog.active(), "다른 시험이 오류 기록을 켜 둔 채 끝났다")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(errorlog.disarm)
        self.root = Path(self.tmp.name) / "data"                      # 데이터 폴더 — 아직 만들지 않는다
        self.logs = self.root / "logs"
        self.file = self.logs / "errors.log"

    def make(self, **options):
        return errorlog.ErrorLog(lambda: self.root, clock=fixed_clock, **options)

    def lines(self, name="errors.log"):
        return (self.logs / name).read_text(encoding="utf-8").splitlines()

    def names(self):
        return sorted(path.name for path in self.logs.iterdir()) if self.logs.is_dir() else []


# ---- 1) 처음 만든다 ----------------------------------------------------------------------------------------------------------------------
class FirstErrorCreatesTest(Base):

    def test_arming_creates_nothing_not_even_the_data_folder(self):
        resolved = []
        log = errorlog.arm(lambda: resolved.append("resolved") or self.root, clock=fixed_clock)
        self.assertIs(errorlog.active(), log)
        self.assertEqual((resolved, self.root.exists()), ([], False), "켜기만으로는 폴더 해석도 만들기도 하지 않는다")

    def test_the_first_error_creates_the_folder_and_the_file_and_nothing_else(self):
        log = self.make()
        self.assertFalse(self.root.exists())
        self.assertTrue(log.record("main", ValueError, caught()))
        self.assertEqual(self.names(), ["errors.log"])
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["logs"], "데이터 폴더에는 logs 폴더 하나만 생긴다")

    def test_a_second_error_appends_a_line_and_creates_no_other_file(self):
        log = self.make()
        log.record("main", ValueError, caught())
        log.record("slot", KeyError, caught(kind=KeyError))
        self.assertEqual(self.names(), ["errors.log"])
        self.assertEqual(len(self.lines()), 2)

    def test_the_folder_is_asked_once_and_remembered(self):
        asked = []
        log = errorlog.ErrorLog(lambda: asked.append(1) or self.root, clock=fixed_clock, rate=(1000, 60.0))
        for _ in range(3):
            log.record("main", ValueError, caught())
        self.assertEqual(len(asked), 1)

    def test_nothing_is_written_while_no_log_is_armed(self):
        self.assertFalse(errorlog.record_exception("main", ValueError, caught()))
        self.assertFalse(errorlog.record_qt(types.SimpleNamespace(name="QtFatalMsg"), types.SimpleNamespace(category="x", file=None, line=0)))
        self.assertFalse(self.root.exists())

    def test_disarming_stops_the_writing_and_only_the_current_log_can_be_disarmed_by_handle(self):
        first = errorlog.arm(lambda: self.root, clock=fixed_clock)
        second = errorlog.arm(lambda: self.root, clock=fixed_clock)
        errorlog.disarm(first)                                                     # 이미 바뀐 옛 기록기를 끄는 것은 지금 것을 끄지 않는다
        self.assertIs(errorlog.active(), second)
        errorlog.disarm(second)
        self.assertIsNone(errorlog.active())
        self.assertFalse(errorlog.record_exception("main", ValueError, caught()))
        self.assertFalse(self.root.exists())


# ---- 2) 줄에는 이름과 위치뿐 -----------------------------------------------------------------------------------------------------------------
class LineContentTest(Base):

    def test_the_line_has_the_time_the_source_the_class_name_and_places_only(self):
        self.make().record("slot", ValueError, caught())
        (line,) = self.lines()
        self.assertTrue(LINE.fullmatch(line), "줄이 좁은 글자표 밖이다")
        self.assertTrue(line.startswith(f"{STAMP} slot ValueError test_security_errorlog.py:"), line)
        self.assertRegex(line, r"^\S+ slot ValueError test_security_errorlog\.py:\d+$")

    def test_a_deeper_error_lists_the_places_innermost_first_up_to_six(self):
        error = caught_deep("가짜")
        self.make().record("main", type(error), error)
        (line,) = self.lines()
        places = line.split(" ", 3)[3].split(" < ")
        self.assertEqual(len(places), 3, "caught_deep → outer → inner 세 곳")
        outward = [frame.lineno for frame in traceback.extract_tb(error.__traceback__)]          # 바깥에서 안쪽 순서
        self.assertEqual([int(place.rsplit(":", 1)[1]) for place in places], outward[::-1], "가장 안쪽(오류가 난 곳)이 먼저다")

    def test_at_most_six_places_are_written(self):
        def down(count):
            if count == 0:
                raise RuntimeError("깊다")
            down(count - 1)

        try:
            down(20)
        except RuntimeError as error:
            self.make().record("main", type(error), error)
        (line,) = self.lines()
        self.assertEqual(len(line.split(" ", 3)[3].split(" < ")), errorlog.MAX_FRAMES)

    def test_exactly_the_six_innermost_places_are_written_innermost_first(self):
        """상수를 읽어 견주면 `MAX_FRAMES` 가 바뀌어도 초록이다 — 여섯이라는 값과 '어느 여섯인가'(가장 안쪽 여섯, 안쪽이 먼저)를 못박는다."""
        self.assertEqual(errorlog.MAX_FRAMES, 6)
        error = caught_chain(12)
        extracted = [f"{Path(frame.filename).name}:{frame.lineno}" for frame in traceback.extract_tb(error.__traceback__)]
        self.assertEqual(len(extracted), 13, "부른 쪽 한 곳 + 함수 열두 곳")
        self.make().record("main", type(error), error)
        (line,) = self.lines()
        places = line.split(" ", 3)[3].split(" < ")
        self.assertEqual(places, [f"chain_mod.py:{24 - 2 * step}" for step in range(6)], "가장 안쪽 여섯 곳 — 오류가 난 줄(24)이 맨 앞")
        self.assertEqual(places, extracted[-6:][::-1], "추적 모듈이 말하는 가장 안쪽 여섯과 같다")
        self.assertNotIn("test_security_errorlog.py", line, "가장 바깥(부른 쪽)은 잘려 나간다")

    def test_up_to_six_places_are_all_kept_and_a_seventh_cuts_off_the_outermost(self):
        for depth, count, caller_kept in ((1, 2, True), (5, 6, True), (6, 6, False), (7, 6, False)):
            error = caught_chain(depth)
            log = self.make(rate=(1000, 60.0))
            log.record("main", type(error), error)
            places = self.lines()[-1].split(" ", 3)[3].split(" < ")
            self.assertEqual(len(places), count, depth)
            self.assertEqual(places[0], f"chain_mod.py:{2 * depth}", f"가장 안쪽이 먼저 (깊이 {depth})")
            self.assertEqual(places[-1].startswith("test_security_errorlog.py:"), caller_kept, (depth, places))

    def test_the_message_is_never_read_so_no_canary_and_no_message_text_reaches_the_file(self):
        message = canary_message()
        error = caught(message)
        self.make().record("main", type(error), error)
        text = self.file.read_text(encoding="utf-8")
        for label in ("ELMSG", "ELUSER"):
            sec.assert_no_secret(self, sec.make_canary(label), text, f"오류 기록 파일({label})")
        sec.assert_no_secret(self, KEY, text, "오류 기록 파일(키 모양)")
        for piece in ("CANARY_BODY", "비밀 글", "Secret Folder", "note.txt", "C:\\", "Users"):
            self.assertNotIn(piece, text, "메시지 글의 조각이 파일에 있다")
        self.assertTrue(LINE.fullmatch(text.strip()), "줄이 좁은 글자표 밖이다")

    def test_every_entry_point_keeps_the_message_out_of_the_file(self):
        message = canary_message()
        error = caught(message)
        log = self.make(rate=(1000, 60.0))
        log.record("main", type(error), error)
        log.record("slot", type(error), error, error.__traceback__)
        log.record("thread", type(error), error)
        log.record("unraisable", type(error), error)
        log.record_qt(types.SimpleNamespace(name="QtFatalMsg"), types.SimpleNamespace(category="qt.qpa.fonts", file="qfont.cpp", line=12))
        text = self.file.read_text(encoding="utf-8")
        self.assertEqual(len(text.splitlines()), 5)
        sec.assert_no_secret(self, sec.make_canary("ELMSG"), text, "다섯 출구의 기록")
        sec.assert_no_secret(self, KEY, text, "다섯 출구의 기록(키 모양)")
        for row in text.splitlines():
            self.assertTrue(LINE.fullmatch(row), "줄이 좁은 글자표 밖이다")

    def test_the_folders_of_a_code_path_never_reach_the_file_only_the_file_name_does(self):
        directory = "C:/Users/" + sec.make_canary("ELDIR") + "/proj dir"
        error = caught_in_foreign_file("가짜", directory + "/inner_mod.py")
        self.make().record("main", type(error), error)
        text = self.file.read_text(encoding="utf-8")
        self.assertIn("inner_mod.py:2", text)
        sec.assert_no_secret(self, sec.make_canary("ELDIR"), text, "코드 경로의 폴더")
        for piece in ("Users", "proj dir", "C:"):
            self.assertNotIn(piece, text)
        backslashes = caught_in_foreign_file("가짜", "C:\\Users\\SOMEONE\\app\\win_mod.py")
        self.make().record("main", type(backslashes), backslashes)
        self.assertIn("win_mod.py:2", self.file.read_text(encoding="utf-8"), "윈도식 구분자도 폴더를 뗀다")
        self.assertNotIn("SOMEONE", self.file.read_text(encoding="utf-8"))

    def test_names_outside_the_narrow_alphabet_become_a_question_mark_or_unknown(self):
        self.assertEqual(errorlog._short_file("C:/x/내 파일.py"), "?")
        self.assertEqual(errorlog._short_file("a b.py"), "?")
        self.assertEqual(errorlog._short_file("C:/x/ok_name-1.py"), "ok_name-1.py")
        self.assertEqual(errorlog._short_file(None), "?")
        self.assertEqual(errorlog._short_file("x" * 200), "?", "너무 긴 이름도 줄에 넣지 않는다")
        weird = type("가짜오류", (Exception,), {})
        self.assertEqual(errorlog._class_name(weird, weird()), "UnknownError")
        self.assertEqual(errorlog._class_name("not a class", None), "UnknownError")
        self.assertEqual(errorlog._class_name(ValueError, None), "ValueError")
        self.assertEqual(errorlog._line_number(True), 0)
        self.assertEqual(errorlog._line_number(-3), 0)
        self.assertEqual(errorlog._line_number(10 ** 12), 0)
        self.assertEqual(errorlog._line_number(42), 42)

    def test_a_value_that_is_not_an_exception_still_gives_a_safe_line(self):
        log = self.make(rate=(1000, 60.0))
        self.assertTrue(log.record("main", "글자 하나", "CANARY_NOT_AN_EXCEPTION"))
        self.assertTrue(log.record("no-such-source", ValueError))
        first, second = self.lines()
        self.assertEqual(first, f"{STAMP} main UnknownError -")
        self.assertEqual(second, f"{STAMP} main ValueError -", "모르는 갈래는 main 으로, 추적이 없으면 `-`")
        self.assertNotIn("CANARY_NOT_AN_EXCEPTION", self.file.read_text(encoding="utf-8"))

    def test_the_trace_of_the_error_being_handled_is_used_when_the_value_carries_none(self):
        """셸이 `report_unexpected(type(error), "")` 로 부를 때는 값이 빈 글이다 — 처리 중인 같은 종류의 오류의 추적을 쓴다."""
        log = self.make(rate=(1000, 60.0))
        try:
            raise ValueError("가짜")
        except ValueError:
            log.record("slot", ValueError, "")
        log.record("slot", ValueError, "")                                           # 처리 중인 오류가 없으면 위치가 없다
        inside, outside = self.lines()
        self.assertRegex(inside, r"test_security_errorlog\.py:\d+$")
        self.assertTrue(outside.endswith(" -"), outside)

    def test_the_trace_of_a_different_kind_of_error_being_handled_is_never_borrowed(self):
        """처리 중인 오류가 기록하려는 것과 종류가 다르면 그 추적을 빌려 쓰면 거짓 위치가 된다 — 같은 종류(하위 종류 포함)일 때만 쓴다."""
        log = self.make(rate=(1000, 60.0))
        try:
            raise KeyError("가짜")
        except KeyError:
            log.record("slot", ValueError, "")                      # 처리 중인 것은 KeyError — ValueError 의 위치가 아니다
            log.record("slot", "not a class", "")                   # 클래스가 아닌 것을 종류로 받아도 예외 없이 이름만 UnknownError
            log.record("slot", LookupError, "")                     # 처리 중인 KeyError 는 LookupError 의 하위 종류라 그 추적을 쓴다
        try:
            raise LookupError("가짜")
        except LookupError:
            log.record("slot", KeyError, "")                        # 처리 중인 LookupError 는 KeyError 의 하위 종류가 아니다
        different, odd, related, wider = self.lines()
        self.assertTrue(different.endswith(" slot ValueError -"), different)
        self.assertTrue(odd.endswith(" slot UnknownError -"), odd)
        self.assertRegex(related, r" slot LookupError test_security_errorlog\.py:\d+$")
        self.assertTrue(wider.endswith(" slot KeyError -"), wider)

    def test_the_time_is_utc_and_ascii(self):
        zone = timezone.utc
        log = errorlog.ErrorLog(lambda: self.root, clock=lambda: datetime(2026, 11, 15, 16, 41, 5, tzinfo=timezone.utc).astimezone(zone))
        log.record("main", ValueError, caught())
        self.assertTrue(self.lines()[0].startswith("2026-11-15T16:41:05Z "))
        self.assertTrue(self.file.read_bytes().isascii())

    def test_a_clock_in_another_time_zone_is_written_in_utc(self):
        """시계가 한국 시각(+09:00)이나 서쪽 시각(-05:00)을 줘도 줄의 시각은 UTC(`Z`)다 — 날짜가 하루 넘어가는 경계도 본다."""
        kst, west = timezone(timedelta(hours=9)), timezone(timedelta(hours=-5))
        cases = [(datetime(2026, 11, 15, 16, 41, 5, tzinfo=kst), "2026-11-15T07:41:05Z"),
                 (datetime(2026, 11, 15, 1, 2, 3, tzinfo=kst), "2026-11-14T16:02:03Z"),
                 (datetime(2026, 11, 15, 22, 30, 0, tzinfo=west), "2026-11-16T03:30:00Z"),
                 (datetime(2026, 11, 15, 7, 41, 5, tzinfo=timezone.utc), "2026-11-15T07:41:05Z")]
        for moment, expected in cases:
            log = errorlog.ErrorLog(lambda: self.root, clock=lambda moment=moment: moment, rate=(1000, 60.0))
            self.assertTrue(log.record("main", ValueError, caught()))
            self.assertTrue(self.lines()[-1].startswith(expected + " main ValueError "), (self.lines()[-1], expected))
        self.assertEqual(len(self.lines()), len(cases))

    def test_qt_messages_record_only_the_critical_and_fatal_kinds_and_never_the_text(self):
        log = self.make(rate=(1000, 60.0))
        context = types.SimpleNamespace(category="qt.qpa.plugin", file="C:/Qt/qwidget.cpp", line=77)
        for name in ("QtDebugMsg", "QtWarningMsg", "QtInfoMsg"):
            self.assertFalse(log.record_qt(types.SimpleNamespace(name=name), context), name)
        self.assertFalse(self.root.exists(), "경고·정보는 파일을 만들지도 않는다")
        self.assertTrue(log.record_qt(types.SimpleNamespace(name="QtCriticalMsg"), context))
        self.assertTrue(log.record_qt(3, types.SimpleNamespace(category=None, file=None, line=0)))                  # 번호로 오는 종류(3 = Fatal)
        self.assertFalse(log.record_qt(1, context), "번호 1 은 경고")
        self.assertFalse(log.record_qt(object(), context), "모르는 종류")
        first, second = self.lines()
        self.assertEqual(first, f"{STAMP} qt QtCriticalMsg qt.qpa.plugin < qwidget.cpp:77")
        self.assertEqual(second, f"{STAMP} qt QtFatalMsg -")


# ---- 2b) 좁은 글자표 전수(2차 지시) ---------------------------------------------------------------------------------------------------------
class NarrowAlphabetTest(Base):
    """줄에 들어가는 이름(오류 클래스 이름·파일 이름·Qt 분류 이름)은 허용한 글자 밖의 글자가 **한 글자라도** 끼면 들어가지 못한다 — U+0001 에서 U+024F 까지 전부와 몇몇 위험한 글자를
    이름의 앞·가운데·끝에 끼워 시험이 따로 적은 '정답'(`class_expected`·`file_expected`·`narrow_file`)과 견준다(소스의 정규식은 가져다 쓰지 않는다)."""

    def captured_qt(self, **context):
        """`record_qt` 가 쓰려는 줄 하나(쓰기는 가로채서 파일을 만들지 않는다) — 줄을 만들지 못했으면 None."""
        lines = []
        with mock.patch.object(errorlog.ErrorLog, "write", lambda this, line: lines.append(line) or True):
            self.make().record_qt(types.SimpleNamespace(name="QtFatalMsg"), types.SimpleNamespace(**context))
        return lines[0] if lines else None

    def test_a_class_name_passes_only_when_every_character_is_in_the_narrow_alphabet(self):
        checked = 0
        for char in SWEEP:
            for name in (f"Err{char}", f"E{char}r", f"{char}Err"):                  # 끝·가운데·앞(U+0000 은 파이썬이 클래스 이름으로 허용하지 않아 뺐다)
                kind = type(name, (Exception,), {})
                self.assertEqual(errorlog._class_name(kind, None), class_expected(name), repr(name))
                checked += 1
        self.assertGreater(checked, 1700, "전수 범위가 줄었다")
        for name in ("Err Name", "Err.Name", "Err-Name", "Err@Name", "Err/Name", "1Err", "에러"):                 # 낱말 몇 개는 글자 하나만 틀려도 이름 전체가 바뀐다
            self.assertEqual(errorlog._class_name(type(name, (Exception,), {}), None), "UnknownError", name)

    def test_a_file_name_passes_only_when_every_character_is_in_the_narrow_alphabet(self):
        checked = 0
        for char in ["\x00"] + SWEEP:
            for path in (f"a{char}b.py", f"ab.p{char}", f"{char}ab.py", f"C:/x/dir/a{char}b.py"):
                self.assertEqual(errorlog._short_file(path), file_expected(path), repr(path))
                checked += 1
        self.assertGreater(checked, 2300, "전수 범위가 줄었다")
        self.assertEqual(errorlog._short_file("C:\\Users\\내 이름 @x\\proj dir\\mod.py"), "mod.py", "폴더 쪽의 이상한 글자는 폴더와 함께 떨어진다")
        for path in ("mod py.py", "mod@x.py", ".hidden.py", "-x.py", "C:file.py"):
            self.assertEqual(errorlog._short_file(path), "?", path)

    def test_the_length_limit_is_sixty_four_characters(self):
        self.assertEqual(errorlog._class_name(type("E" * 64, (Exception,), {}), None), "E" * 64)
        self.assertEqual(errorlog._class_name(type("E" * 65, (Exception,), {}), None), "UnknownError")
        self.assertEqual(errorlog._short_file("f" * 61 + ".py"), "f" * 61 + ".py")        # 64 글자
        self.assertEqual(errorlog._short_file("f" * 62 + ".py"), "?")                      # 65 글자

    def test_a_qt_category_passes_only_when_every_character_is_in_the_narrow_alphabet(self):
        checked = 0
        for char in SWEEP:
            for category in (f"qt{char}qpa", f"qt.qpa{char}", f"{char}qt"):
                expected = f"{STAMP} qt QtFatalMsg " + (category if narrow_file(category) else "-")
                self.assertEqual(self.captured_qt(category=category, file=None, line=0), expected, repr(category))
                checked += 1
        self.assertGreater(checked, 1700, "전수 범위가 줄었다")
        for category in ("qt qpa", "C:/Users/x/y", "qt.qpa\\x", "내 분류", "qt@x", "qt.\u202eqpa", "q" * 65, "", ".hidden", "-x", None, 5, b"qt.qpa", ["qt"]):
            self.assertEqual(self.captured_qt(category=category, file=None, line=0), f"{STAMP} qt QtFatalMsg -", repr(category))
        self.assertEqual(self.captured_qt(category="qt.qpa.plugin", file=None, line=0), f"{STAMP} qt QtFatalMsg qt.qpa.plugin")

    def test_a_qt_category_that_cannot_enter_the_line_does_not_reach_the_file_either(self):
        log = self.make(rate=(1000, 60.0))
        for category in ("qt qpa", "C:/Users/" + sec.make_canary("ELCAT"), "qt@x"):
            self.assertTrue(log.record_qt(types.SimpleNamespace(name="QtFatalMsg"), types.SimpleNamespace(category=category, file=None, line=0)))
        text = self.file.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines(), [f"{STAMP} qt QtFatalMsg -"] * 3)
        sec.assert_no_secret(self, sec.make_canary("ELCAT"), text, "Qt 분류 이름")

    def test_a_qt_line_number_outside_the_range_is_written_as_zero(self):
        for value in (-1, -5, 10_000_000, 10 ** 12, True, False, "12", None, 12.5, [7]):
            self.assertEqual(self.captured_qt(category=None, file="qfont.cpp", line=value), f"{STAMP} qt QtFatalMsg qfont.cpp:0", repr(value))
        for value in (0, 1, 77, 9_999_999):
            self.assertEqual(self.captured_qt(category=None, file="qfont.cpp", line=value), f"{STAMP} qt QtFatalMsg qfont.cpp:{value}", repr(value))
        self.assertEqual(self.captured_qt(category=None, file="qfont.cpp", line=12), f"{STAMP} qt QtFatalMsg qfont.cpp:12")

    def test_a_qt_file_name_outside_the_narrow_alphabet_becomes_a_question_mark_and_its_folders_are_dropped(self):
        self.assertEqual(self.captured_qt(category=None, file="C:/Qt/dir/q font.cpp", line=12), f"{STAMP} qt QtFatalMsg ?:12")
        self.assertEqual(self.captured_qt(category=None, file="C:\\Users\\SOMEONE\\qwidget.cpp", line=3), f"{STAMP} qt QtFatalMsg qwidget.cpp:3")
        self.assertEqual(self.captured_qt(category=None, file="", line=3), f"{STAMP} qt QtFatalMsg -", "파일 이름이 비어 있으면 위치를 적지 않는다")
        self.assertEqual(self.captured_qt(category=None, file=7, line=3), f"{STAMP} qt QtFatalMsg -", "글이 아닌 파일 이름은 적지 않는다")

    def test_a_file_name_passes_only_when_every_character_is_in_the_narrow_alphabet_over_all_of_unicode(self):
        """U+0000 에서 U+10FFFF 까지(짝 없는 서로게이트도) **모든** 글자를 파일 이름의 첫 자리와 가운데 자리에 하나씩 끼운다 — 위의 U+024F 까지 훑기가 놓치는 먼 곳의 글자(붙임표를 닮은 마이너스 기호 U+2212 같은 것)를
        글자표에 하나 더 허용해도 빨개진다(3차 지시, 검증자 1 의 X01). 폴더 구분자(`/` 와 역슬래시)를 끼우면 앞의 폴더 쪽이 떨어져 나가므로 그 둘만 따로 정답을 둔다."""
        wrong = []
        for code in range(0x110000):
            char = chr(code)
            if char in "/" + chr(92):
                want_first, want_middle = "ab.py", "b.py"
            else:
                want_first = char + "ab.py" if char in FILE_FIRST_SET else "?"
                want_middle = "a" + char + "b.py" if char in FILE_REST_SET else "?"
            got = (errorlog._short_file(char + "ab.py"), errorlog._short_file("a" + char + "b.py"))
            if got != (want_first, want_middle):
                wrong.append((f"U+{code:04X}", got))
                if len(wrong) >= 5:
                    break
        self.assertEqual(wrong, [], "파일 이름 글자표가 정답과 다르다(처음 몇 글자)")

    def test_a_class_name_passes_only_when_every_character_is_in_the_narrow_alphabet_over_all_of_unicode(self):
        """U+0001 에서 U+10FFFF 까지 **모든** 글자를 클래스 이름의 첫 자리와 가운데 자리에 하나씩 끼운다 — 전각 영문 대문자(U+FF21 에서 U+FF3A)처럼 먼 곳의 비슷한 글자를 글자표에 허용해도 빨개진다(3차 지시, 검증자 1 의 X02).
        같은 클래스 하나의 `__name__` 을 바꿔 가며 훑는다(글자마다 새 클래스를 만들면 느리다). 널 글자와 짝 없는 서로게이트는 파이썬이 클래스 이름으로 받지 않아 뺐다 — 진짜 오류 클래스의 이름에는 올 수 없는 글자다."""
        kind = type("Err", (Exception,), {})
        wrong = []
        for code in range(1, 0x110000):
            if 0xD800 <= code <= 0xDFFF:
                continue
            char = chr(code)
            for template, allowed in (("{}Err", CLASS_FIRST_SET), ("E{}r", CLASS_REST_SET)):
                name = template.format(char)
                kind.__name__ = name
                got = errorlog._class_name(kind, None)
                want = name if char in allowed else "UnknownError"
                if got != want:
                    wrong.append((f"U+{code:04X}", template, got))
            if len(wrong) >= 5:
                break
        self.assertEqual(wrong, [], "클래스 이름 글자표가 정답과 다르다(처음 몇 글자)")

    def test_only_a_real_class_gives_a_name_never_a_function_a_module_or_an_object_that_merely_has_a_name(self):
        """(3차 지시, 검증자 1 의 X19) 종류가 클래스인지 확인하지 않고 `__name__` 만 읽으면 함수·모듈·이름만 가진 객체의 이름이 줄에 들어간다 — 그 이름은 글자표를 통과해 버리므로 글자표로는 막을 수 없다."""
        self.assertEqual(errorlog._class_name(len, None), "UnknownError", "함수에도 `__name__` 이 있다")
        self.assertEqual(errorlog._class_name(os, None), "UnknownError", "모듈에도 있다")
        self.assertEqual(errorlog._class_name(types.SimpleNamespace(__name__="Spoofed"), None), "UnknownError", "이름만 가진 객체도 있다")
        self.assertEqual(errorlog._class_name("ValueError", None), "UnknownError", "클래스 이름을 글로 준 것은 클래스가 아니다")
        self.assertEqual(errorlog._class_name(len, ValueError("x")), "ValueError", "클래스가 아니면 값(예외)의 클래스 이름을 쓴다")
        self.assertEqual(errorlog._class_name(os, KeyError("k")), "KeyError")
        self.assertEqual(errorlog._class_name(KeyError, ValueError("x")), "KeyError", "종류가 클래스면 값의 종류가 아니라 그 클래스의 이름이다")


# ---- 2c) 깊은 추적(3차 지시 — 검증자 1 의 X03, N4) ---------------------------------------------------------------------------------------
def synthetic_trace(count):
    """`count` 단계의 진짜 `TracebackType` 추적 — 가장 안쪽(오류가 난 곳)이 줄 1, 가장 바깥이 줄 `count`. 재귀 없이 만들어 재귀 한도가 걸리지 않는다."""
    frame, trace = sys._getframe(), None
    for number in range(1, count + 1):
        trace = types.TracebackType(trace, frame, 0, number)
    return trace


class DeepTraceTest(Base):
    """추적이 아무리 깊어도 줄에는 **가장 안쪽 여섯 곳**이 들어간다. 옛 읽기는 바깥에서 1만 단계까지만 읽어(그 상한이 100 으로 줄어도 시험이 몰랐다) 더 깊은 추적은 오류가 난 자리가 빠졌다 —
    이제 끝까지 걸으며 `deque(maxlen=MAX_FRAMES)` 로 안쪽 여섯만 쥔다."""

    def innermost_six(self, line):
        return line.split(" ", 3)[3].split(" < ")

    def test_traces_three_hundred_and_six_hundred_calls_deep_keep_exactly_the_six_innermost_places(self):
        for depth in (300, 600):
            with self.subTest(depth=depth):
                error = caught_chain(depth)
                extracted = [f"{Path(frame.filename).name}:{frame.lineno}" for frame in traceback.extract_tb(error.__traceback__)]
                self.assertEqual(len(extracted), depth + 1, "부른 쪽 한 곳 + 함수 depth 곳")
                log = self.make(rate=(10 ** 9, 60.0))
                self.assertTrue(log.record("main", type(error), error))
                places = self.innermost_six(self.lines()[-1])
                self.assertEqual(places, [f"chain_mod.py:{2 * depth - 2 * step}" for step in range(6)], "오류가 난 줄이 맨 앞이고 안쪽 여섯 곳이다")
                self.assertEqual(places, extracted[-6:][::-1], "추적 모듈이 말하는 가장 안쪽 여섯과 같다")

    def test_a_real_recursion_error_keeps_the_six_innermost_places(self):
        def descend(number):
            return descend(number + 1)

        try:
            descend(0)
        except RecursionError as error:
            recursion = error
        extracted = [f"{Path(frame.filename).name}:{frame.lineno}" for frame in traceback.extract_tb(recursion.__traceback__)]
        self.assertGreater(len(extracted), 100, "재귀 한도까지 내려간 진짜 추적이다")
        log = self.make(rate=(10 ** 9, 60.0))
        self.assertTrue(log.record("main", RecursionError, recursion))
        self.assertEqual(self.innermost_six(self.lines()[-1]), extracted[-6:][::-1])

    def test_a_trace_of_thirty_thousand_steps_still_ends_at_the_real_innermost_place(self):
        """옛 읽기는 바깥에서 1만 단계까지만 봐서 3만 단계 추적의 '안쪽' 이 실제 안쪽이 아니었다."""
        trace = synthetic_trace(30_000)
        want = [f"test_security_errorlog.py:{number}" for number in range(1, 7)]
        self.assertEqual(errorlog._frames(trace), want)
        log = self.make(rate=(10 ** 9, 60.0))
        self.assertTrue(log.record("main", ValueError, ValueError("x"), trace))
        self.assertEqual(self.innermost_six(self.lines()[-1]), want)

    def test_every_depth_from_zero_to_eight_keeps_the_smaller_of_depth_and_six_places_innermost_first(self):
        for count in range(0, 9):
            self.assertEqual(errorlog._frames(synthetic_trace(count)), [f"test_security_errorlog.py:{number}" for number in range(1, min(count, 6) + 1)], count)

    def test_a_fake_trace_that_loops_or_never_ends_is_cut_by_the_safety_limit_instead_of_hanging_the_app(self):
        frame, seen = sys._getframe(), [0]

        class Looping:
            tb_frame, tb_lineno = frame, 7

        looping = Looping()
        looping.tb_next = looping                               # 진짜 추적은 고리를 만들 수 없지만(파이썬이 막는다) 가짜 객체는 만들 수 있다

        class Endless:
            def __init__(self):
                seen[0] += 1
                self.tb_frame, self.tb_lineno = frame, seen[0]

            @property
            def tb_next(self):
                return Endless() if seen[0] < 50_000 else None

        with mock.patch.object(errorlog, "_MAX_WALK", 1000):
            self.assertEqual(errorlog._frames(looping), ["test_security_errorlog.py:7"] * errorlog.MAX_FRAMES)
            self.assertEqual(len(errorlog._frames(Endless())), errorlog.MAX_FRAMES)
        self.assertLessEqual(seen[0], 1002, "안전 상한에서 멈춘다(상한이 없으면 가짜 추적 끝까지 5만 단계를 걷는다)")


# ---- 3) 공통 가림 경로 ---------------------------------------------------------------------------------------------------------------------
class RedactionPathTest(Base):

    def test_the_module_uses_the_one_common_mask_function(self):
        self.assertIs(errorlog.mask, mask_module.mask, "새 가림 규칙을 만들지 않고 `security/mask.py` 의 mask 를 쓴다")

    def test_the_finished_line_goes_through_the_mask_before_it_is_written(self):
        seen = []
        with mock.patch.object(errorlog, "mask", side_effect=lambda text: seen.append(text) or "MASKED|" + text):
            self.make().record("main", ValueError, caught())
        self.assertEqual(len(seen), 1)
        self.assertTrue(LINE.fullmatch(seen[0]), "줄이 좁은 글자표 밖이다")
        self.assertTrue(self.lines()[0].startswith("MASKED|" + STAMP), "가린 글이 쓰인다 — mask 를 건너뛰면 이 줄이 달라진다")

    def test_a_mask_that_breaks_drops_the_line_without_an_error(self):
        with mock.patch.object(errorlog, "mask", side_effect=RuntimeError("가림이 고장")):
            self.assertFalse(self.make().record("main", ValueError, caught()))
        self.assertFalse(self.root.exists())


# ---- 4) 돌려쓰기 ---------------------------------------------------------------------------------------------------------------------------
class RotationTest(Base):

    def test_the_real_limits_are_256_kilobytes_and_three_files(self):
        self.assertEqual((errorlog.MAX_BYTES, errorlog.BACKUPS), (256 * 1024, 2))
        self.assertEqual((errorlog.FOLDER_NAME, errorlog.FILE_NAME), ("logs", "errors.log"))
        self.assertEqual((errorlog.MAX_FRAMES, errorlog.LOCK_WAIT), (6, 1.0), "코드 위치는 여섯 곳, 다른 스레드가 쓰는 중이면 1초만 기다린다(문서와 결정 기록의 값)")

    def fill(self, size, byte):
        self.logs.mkdir(parents=True, exist_ok=True)
        self.file.write_bytes(byte * size)

    def test_a_line_that_would_pass_the_limit_rolls_the_files_first_with_the_real_constants(self):
        log = self.make(rate=(10 ** 9, 60.0))
        self.fill(errorlog.MAX_BYTES - 10, b"a")
        self.assertTrue(log.record("main", ValueError, caught()))
        self.assertEqual(self.names(), ["errors.log", "errors.log.1"])
        self.assertEqual((self.logs / "errors.log.1").stat().st_size, errorlog.MAX_BYTES - 10, "넘기기 전의 파일이 통째로 .1 이 된다")
        self.assertLess(self.file.stat().st_size, 400)
        self.fill(errorlog.MAX_BYTES - 10, b"b")
        self.assertTrue(log.record("main", ValueError, caught()))
        self.assertEqual(self.names(), ["errors.log", "errors.log.1", "errors.log.2"])
        self.assertEqual((self.logs / "errors.log.2").read_bytes()[:1], b"a", "가장 오래된 것이 맨 뒤로 밀린다")
        self.assertEqual((self.logs / "errors.log.1").read_bytes()[:1], b"b")
        self.fill(errorlog.MAX_BYTES - 10, b"c")
        self.assertTrue(log.record("main", ValueError, caught()))
        self.assertEqual(self.names(), ["errors.log", "errors.log.1", "errors.log.2"], "셋을 넘지 않는다")
        self.assertEqual((self.logs / "errors.log.2").read_bytes()[:1], b"b", "가장 오래된 것(a)은 사라졌다")
        self.assertEqual((self.logs / "errors.log.1").read_bytes()[:1], b"c")
        for path in self.logs.iterdir():
            self.assertLessEqual(path.stat().st_size, errorlog.MAX_BYTES, path.name)

    def test_a_line_that_still_fits_is_appended_without_rolling(self):
        log = self.make(rate=(10 ** 9, 60.0))
        self.fill(errorlog.MAX_BYTES - 1000, b"a")
        self.assertTrue(log.record("main", ValueError, caught()))
        self.assertEqual(self.names(), ["errors.log"])

    def test_many_errors_keep_three_small_files_with_the_newest_lines_in_the_current_one(self):
        log = self.make(max_bytes=700, rate=(10 ** 9, 60.0))
        for number in range(60):
            kind = type(f"Err{number}", (Exception,), {})
            log.record("main", kind, caught(kind=kind))
        self.assertEqual(self.names(), ["errors.log", "errors.log.1", "errors.log.2"])
        for path in self.logs.iterdir():
            self.assertLessEqual(path.stat().st_size, 700, path.name)
        everything = "".join(path.read_text(encoding="utf-8") for path in self.logs.iterdir())
        self.assertIn("Err59 ", self.file.read_text(encoding="utf-8"))
        self.assertNotIn("Err0 ", everything, "가장 오래된 줄은 돌려쓰다 사라졌다")
        self.assertIn("Err59 ", everything)

    def test_removing_the_size_check_would_let_one_file_grow_past_the_limit(self):
        """(이 시험의 눈) 한도를 아주 작게 해도 현재 파일이 한도를 넘지 않는다."""
        log = self.make(max_bytes=300, rate=(10 ** 9, 60.0))
        for _ in range(20):
            log.record("main", ValueError, caught())
        self.assertLessEqual(self.file.stat().st_size, 300)
        self.assertGreater(len(self.names()), 1)

    def test_a_rotation_that_fails_drops_the_line_and_does_not_pass_the_limit(self):
        log = self.make(rate=(10 ** 9, 60.0))
        self.fill(errorlog.MAX_BYTES - 10, b"a")
        with mock.patch.object(errorlog.os, "replace", side_effect=PermissionError(errno.EACCES, "다른 프로그램이 잡고 있다")):
            self.assertFalse(log.record("main", ValueError, caught()))
        self.assertEqual(self.file.stat().st_size, errorlog.MAX_BYTES - 10, "한도를 넘겨 쓰지 않는다")
        self.assertEqual(self.names(), ["errors.log"])
        self.assertTrue(log.record("main", ValueError, caught()), "막힘이 풀리면 다시 쓴다")

    def three_old_files(self):
        """현재 파일이 한도 가까이 찼고 `.1`·`.2` 도 있는 상태 — 내용이 서로 달라 어느 것이 어디로 갔는지 알 수 있다."""
        self.logs.mkdir(parents=True, exist_ok=True)
        contents = {"errors.log": b"a" * (errorlog.MAX_BYTES - 10), "errors.log.1": b"b" * 60, "errors.log.2": b"c" * 50}
        for name, data in contents.items():
            (self.logs / name).write_bytes(data)
        return contents

    def test_a_blocked_rotation_never_deletes_the_oldest_file(self):
        """이름 바꾸기가 막혔는데 가장 오래된 `.2` 를 먼저 지워 버리면 새 줄도 못 쓰고 옛 기록 하나만 잃는다 — 첫 단계(`.1` → `.2`)가 막히면 셋 모두 한 글자도 바뀌지 않아야 한다
        (이름 바꾸기가 모두 막힌 모양이다. 첫 단계가 끝난 뒤 둘째가 막히는 모양은 아래 시험이 따로 본다 — 그때는 `.2` 가 옛 `.1` 의 내용이 된다)."""
        log = self.make(rate=(10 ** 9, 60.0))
        before = self.three_old_files()
        with mock.patch.object(errorlog.os, "replace", side_effect=PermissionError(errno.EACCES, "다른 프로그램이 잡고 있다")):
            self.assertFalse(log.record("main", ValueError, caught()))
        self.assertEqual({name: (self.logs / name).read_bytes() for name in before}, before, "첫 단계가 막히면 옛 파일 셋은 그대로다")
        self.assertEqual(self.names(), sorted(before))

    def test_a_rotation_blocked_half_way_loses_nothing_new_and_finishes_next_time(self):
        log = self.make(rate=(10 ** 9, 60.0))
        self.three_old_files()
        real, calls = os.replace, []

        def blocked_on_the_second_step(source, target):
            calls.append((Path(source).name, Path(target).name))
            if len(calls) == 2:
                raise PermissionError(errno.EACCES, "다른 프로그램이 잡고 있다")
            return real(source, target)

        with mock.patch.object(errorlog.os, "replace", side_effect=blocked_on_the_second_step):
            self.assertFalse(log.record("main", ValueError, caught()))
        self.assertEqual(calls, [("errors.log.1", "errors.log.2"), ("errors.log", "errors.log.1")], "가장 오래된 쪽부터 한 칸씩 민다")
        self.assertEqual((self.logs / "errors.log.2").read_bytes(), b"b" * 60, "첫 단계(.1 → .2)는 끝났다")
        self.assertEqual(self.names(), ["errors.log", "errors.log.2"], "둘째 단계가 막힌 동안 `.1` 은 비어 있다")
        self.assertNotIn(b"c" * 50, [path.read_bytes() for path in self.logs.iterdir()], "옛 `.2` 는 덮어쓰여 사라졌다 — '막혀도 옛 파일 셋이 그대로' 는 첫 단계가 막힐 때만 참이다")
        self.assertEqual(self.file.read_bytes(), b"a" * (errorlog.MAX_BYTES - 10), "현재 파일은 그대로 남았다")
        self.assertTrue(log.record("main", ValueError, caught()), "막힘이 풀리면 이어서 끝낸다")
        self.assertEqual((self.logs / "errors.log.2").read_bytes(), b"b" * 60)
        self.assertEqual((self.logs / "errors.log.1").read_bytes(), b"a" * (errorlog.MAX_BYTES - 10), "현재 파일이 .1 이 된다")
        self.assertEqual(len(self.lines()), 1, "현재 파일에는 새 줄 하나뿐")

    def test_a_normal_rotation_only_renames_and_never_deletes_a_file(self):
        log = self.make(rate=(10 ** 9, 60.0))
        self.three_old_files()
        refuse = AssertionError("돌려쓰기는 이름 바꾸기뿐이다 — 지우면 안 된다")
        with mock.patch.object(Path, "unlink", side_effect=refuse), mock.patch.object(errorlog.os, "remove", side_effect=refuse), mock.patch.object(errorlog.os, "unlink", side_effect=refuse):
            self.assertTrue(log.record("main", ValueError, caught()))
        self.assertEqual(self.names(), ["errors.log", "errors.log.1", "errors.log.2"])
        self.assertEqual((self.logs / "errors.log.2").read_bytes(), b"b" * 60, "가장 오래된 것은 덮어 쓰여 사라진다(그것이 돌려쓰기다)")
        self.assertEqual((self.logs / "errors.log.1").read_bytes(), b"a" * (errorlog.MAX_BYTES - 10))

    def test_with_no_old_file_kept_the_full_file_is_cleared_instead_of_growing_past_the_limit(self):
        log = self.make(max_bytes=300, backups=0, rate=(10 ** 9, 60.0))
        for _ in range(20):
            self.assertTrue(log.record("main", ValueError, caught()))
        self.assertEqual(self.names(), ["errors.log"], "옛 파일을 남기지 않는 설정이면 현재 파일 하나뿐")
        self.assertLessEqual(self.file.stat().st_size, 300)
        self.assertGreater(len(self.lines()), 0)

    def test_the_limit_is_exact_to_the_byte_a_line_that_just_fits_is_appended_and_one_more_byte_rolls_the_files(self):
        """`파일 크기 + 새 줄 > 한도` 의 경계(3차 지시, 검증자 1 의 X07 — 기준에 5바이트 여유가 붙어도 시험이 몰랐다): 정확히 한도에 닿는 줄은 돌리지 않고 덧붙이고, 1바이트만 넘어도 먼저 돌린다.
        진짜 한도(256 KB)와 작은 한도 둘로 본다. `write` 로 줄을 직접 넣어 줄 길이(줄바꿈 포함 11바이트)를 시험이 정한다."""
        line = "y" * 10
        for limit, options in ((errorlog.MAX_BYTES, {}), (1000, {"max_bytes": 1000}), (64, {"max_bytes": 64})):
            with self.subTest(limit=limit):
                shutil.rmtree(self.logs, ignore_errors=True)
                log = self.make(rate=(10 ** 9, 60.0), **options)
                self.fill(limit - 11, b"x")
                self.assertTrue(log.write(line))
                self.assertEqual((self.names(), self.file.stat().st_size), (["errors.log"], limit), "정확히 한도에 닿는 줄은 돌리지 않고 덧붙인다")
                shutil.rmtree(self.logs, ignore_errors=True)
                self.fill(limit - 10, b"x")
                self.assertTrue(log.write(line))
                self.assertEqual(self.names(), ["errors.log", "errors.log.1"], "한도를 1바이트 넘기는 줄은 먼저 돌린다")
                self.assertEqual((self.logs / "errors.log.1").stat().st_size, limit - 10, "넘기기 전의 파일이 통째로 .1 이 된다")
                self.assertEqual(self.file.read_bytes(), (line + "\n").encode("ascii"), "새 파일에는 새 줄뿐이다")


# ---- 5) 실패해도 앱은 그대로 ---------------------------------------------------------------------------------------------------------------
class NeverBreaksTheAppTest(Base):

    def test_a_full_disk_is_swallowed_and_the_next_error_can_still_be_written(self):
        log = self.make(rate=(1000, 60.0))
        with mock.patch("builtins.open", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            self.assertFalse(log.record("main", ValueError, caught()))
        self.assertEqual(self.file.exists(), False)
        self.assertTrue(log.record("main", ValueError, caught()))

    def test_the_write_step_itself_also_swallows_a_full_disk_and_a_blocked_folder(self):
        """`record` 가 한 겹 더 감싸 주지만 `write` 도 스스로 약속을 지킨다 — 어느 한 겹이 빠져도 앱이 멈추지 않게."""
        log = self.make(rate=(1000, 60.0))
        line = f"{STAMP} main ValueError -"
        with mock.patch("builtins.open", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            self.assertFalse(log.write(line))
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError(errno.EACCES, "denied")):
            self.assertFalse(log.write(line))
        self.assertTrue(log.write(line))
        self.assertEqual(self.lines(), [line])

    def test_a_folder_that_cannot_be_made_is_swallowed(self):
        log = self.make(rate=(1000, 60.0))
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError(errno.EACCES, "denied")):
            self.assertFalse(log.record("main", ValueError, caught()))
        self.assertTrue(log.record("main", ValueError, caught()))

    def test_a_data_folder_that_cannot_be_resolved_is_swallowed_and_asked_again_next_time(self):
        state = {"fail": True}

        def resolve():
            if state["fail"]:
                raise RuntimeError("데이터 폴더를 알 수 없다")
            return self.root

        log = errorlog.ErrorLog(resolve, clock=fixed_clock, rate=(1000, 60.0))
        self.assertFalse(log.record("main", ValueError, caught()))
        state["fail"] = False
        self.assertTrue(log.record("main", ValueError, caught()))
        self.assertEqual(len(self.lines()), 1)

    def test_a_resolver_that_returns_nothing_usable_is_swallowed(self):
        for bad in (None, 5, object()):
            log = errorlog.ErrorLog(lambda bad=bad: bad, clock=fixed_clock)
            self.assertFalse(log.record("main", ValueError, caught()), repr(bad)[:20])

    def test_the_hooks_never_raise_whatever_they_are_given(self):
        log = self.make()
        for args in ((None, None, None), (ValueError, None, None), (object, object(), object()), ("a", "b", "c"), (KeyError, KeyError("k"), 5)):
            self.assertIn(log.record("main", *args), (True, False))
        self.assertIn(log.record_qt(None, None), (True, False))

    def test_the_rate_limit_is_thirty_lines_a_minute(self):
        self.assertEqual((errorlog.RATE_COUNT, errorlog.RATE_SECONDS), (30, 60.0))
        clock = [100.0]
        log = errorlog.ErrorLog(lambda: self.root, clock=fixed_clock, rate=(3, 60.0), monotonic=lambda: clock[0])
        self.assertEqual([log.record("main", ValueError, caught()) for _ in range(5)], [True, True, True, False, False])
        clock[0] = 159.0
        self.assertFalse(log.record("main", ValueError, caught()), "아직 같은 1분 안")
        clock[0] = 160.5
        self.assertTrue(log.record("main", ValueError, caught()), "1분이 지나면 다시 쓴다")
        self.assertEqual(len(self.lines()), 4)

    def test_the_default_limit_is_thirty_lines_per_sixty_seconds_when_nothing_is_passed(self):
        """생성자에 속도 제한을 넘기지 않으면 정해진 값이 쓰인다(3차 지시, 검증자 1 의 X09 — 시험이 늘 값을 직접 넘기면 기본값 자리가 30 에서 100만으로 틀려도 아무도 몰랐다). 구간 경계(정확히 60초)도 본다."""
        clock = [100.0]
        log = errorlog.ErrorLog(lambda: self.root, clock=fixed_clock, monotonic=lambda: clock[0])
        line = f"{STAMP} main ValueError -"
        self.assertEqual([log.write(line) for _ in range(35)], [True] * 30 + [False] * 5, "첫 구간은 30줄까지다")
        clock[0] = 159.999
        self.assertFalse(log.write(line), "59.999초 — 아직 같은 구간이다")
        clock[0] = 160.0
        self.assertTrue(log.write(line), "정확히 60초가 지나면 새 구간이다")
        self.assertEqual([log.write(line) for _ in range(30)], [True] * 29 + [False], "새 구간도 30줄까지다")
        self.assertEqual(len(self.lines()), 60)

    def test_the_armed_log_uses_the_same_default_limit(self):
        errorlog.arm(lambda: self.root, clock=fixed_clock)
        sent = [errorlog.record_exception("main", ValueError, caught()) for _ in range(40)]
        self.assertEqual((sent.count(True), len(self.lines())), (30, 30))

    def test_keyboard_interrupt_and_system_exit_are_not_errors_to_record(self):
        log = self.make()
        for kind in (KeyboardInterrupt, SystemExit, GeneratorExit):
            self.assertFalse(log.record("main", kind, kind()), kind.__name__)
        self.assertFalse(self.root.exists())

    def test_an_error_reported_while_a_line_is_being_written_does_not_deadlock(self):
        """쓰는 도중 정리(`__del__` 등)에서 난 오류가 훅으로 들어와 같은 기록기를 다시 부르는 모양 — 같은 스레드는 잠금에 다시 들어올 수 있어야 한다."""
        log = self.make(rate=(1000, 60.0))
        real = errorlog.ErrorLog._append
        state = {"entered": False, "nested": None}

        def append_with_a_nested_error(this, line):
            if not state["entered"]:
                state["entered"] = True
                state["nested"] = this.record("unraisable", ValueError, caught())
            return real(this, line)

        result = []
        worker = threading.Thread(target=lambda: result.append(log.record("main", ValueError, caught())))
        with mock.patch.object(errorlog.ErrorLog, "_append", append_with_a_nested_error):
            worker.start()
            worker.join(10)
        self.assertFalse(worker.is_alive(), "잠금이 다시 들어오지 못해 멈췄다")
        self.assertEqual((result, state["nested"]), ([True], True))
        self.assertEqual(len(self.lines()), 2)

    def test_a_writer_that_cannot_get_the_lock_in_time_drops_its_line_instead_of_freezing_the_app(self):
        log = self.make(rate=(1000, 60.0))
        held, release = threading.Event(), threading.Event()

        def hold():
            with log._lock:
                held.set()
                release.wait(10)

        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(held.wait(5))
        try:
            with mock.patch.object(errorlog, "LOCK_WAIT", 0.05):
                self.assertFalse(log.record("main", ValueError, caught()))
        finally:
            release.set()
            holder.join(5)
        self.assertTrue(log.record("main", ValueError, caught()), "잠금이 풀리면 다시 쓴다")

    def test_two_threads_writing_at_once_never_mix_a_line(self):
        log = self.make(rate=(10 ** 9, 60.0))

        def work(kind):
            for _ in range(40):
                log.record("thread", kind, caught(kind=kind))

        threads = [threading.Thread(target=work, args=(kind,)) for kind in (ValueError, KeyError)]
        with mock.patch.object(errorlog, "LOCK_WAIT", 60.0):                       # 느린 PC 에서 잠금을 기다리다 줄을 버리는 일로 시험이 흔들리지 않게(버리는 쪽은 아래 시험이 본다)
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        rows = self.lines()
        self.assertEqual(len(rows), 80)
        for row in rows:
            self.assertTrue(LINE.fullmatch(row), "줄이 좁은 글자표 밖이다")


# ---- 6) 공통 경계·화면과의 연결 ----------------------------------------------------------------------------------------------------------
class FakeQtCore:
    def __init__(self):
        self.installs = []

    def qInstallMessageHandler(self, handler):
        previous = self.installs[-1] if self.installs else None
        self.installs.append(handler)
        return previous


class BoundaryTest(Base):
    def setUp(self):
        super().setUp()
        self.assertIsNone(boundary.active(), "다른 시험이 경계를 깔아 둔 채 끝났다")
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.addCleanup(self._undo)

    @staticmethod
    def _undo():
        installed = boundary.active()
        if installed is not None:
            installed.uninstall()

    def armed(self):
        installed = boundary.install_gui(qt=False)
        self.assertTrue(boundary.arm_error_log(lambda: self.root))
        errorlog.active()._clock = fixed_clock
        return installed

    def test_the_three_hooks_and_the_qt_handler_write_their_own_line(self):
        installed = self.armed()
        error = caught(canary_message())
        sys.excepthook(type(error), error, error.__traceback__)
        threading.excepthook(types.SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=error.__traceback__, thread=types.SimpleNamespace(name="작업")))
        sys.unraisablehook(types.SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=error.__traceback__, err_msg="무시된 오류", object=None))
        boundary._qt_handler(types.SimpleNamespace(name="QtFatalMsg"), types.SimpleNamespace(category="qt.qpa.fonts", file="qfont.cpp", line=9), canary_message())
        self.assertEqual([row.split(" ")[1] for row in self.lines()], ["main", "thread", "unraisable", "qt"])
        text = self.file.read_text(encoding="utf-8")
        sec.assert_no_secret(self, sec.make_canary("ELMSG"), text, "경계를 지난 기록")
        sec.assert_no_secret(self, KEY, text, "경계를 지난 기록(키 모양)")
        installed.uninstall()

    def test_the_boundary_still_writes_its_masked_trace_to_standard_error_as_before(self):
        installed = self.armed()
        error = caught(canary_message())
        sys.excepthook(type(error), error, error.__traceback__)
        installed.uninstall()                                                       # 쥐고 있던 글을 내보낸다
        shown = self.stderr.getvalue()
        self.assertIn("ValueError", shown)
        sec.assert_no_secret(self, KEY, shown, "표준 오류의 가려진 추적")

    def test_a_thread_system_exit_and_keyboard_interrupt_are_not_recorded(self):
        installed = self.armed()
        threading.excepthook(types.SimpleNamespace(exc_type=SystemExit, exc_value=SystemExit(), exc_traceback=None, thread=None))
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        self.assertFalse(self.root.exists())
        installed.uninstall()

    def test_uninstalling_the_boundary_switches_the_log_off(self):
        installed = self.armed()
        self.assertIsNotNone(errorlog.active())
        installed.uninstall()
        self.assertIsNone(errorlog.active())
        boundary._excepthook(ValueError, caught(), None)
        self.assertFalse(self.root.exists())

    def test_installing_the_boundary_alone_never_arms_the_log(self):
        installed = boundary.install_gui(qt=False)
        self.assertIsNone(errorlog.active())
        error = caught()
        sys.excepthook(type(error), error, error.__traceback__)
        self.assertFalse(self.root.exists())
        installed.uninstall()

    def test_arming_without_an_installed_boundary_does_nothing(self):
        self.assertFalse(boundary.arm_error_log(lambda: self.root))
        self.assertIsNone(errorlog.active())

    def test_the_cli_installation_never_arms_the_log(self):
        installed = boundary.install()
        self.assertIsNone(errorlog.active())
        installed.uninstall()

    def test_the_screens_one_line_record_writes_the_file_even_when_there_is_no_standard_error(self):
        errorlog.arm(lambda: self.root, clock=fixed_clock)
        error = caught(canary_message())
        self.assertTrue(app_state.report_unexpected(type(error), error, io.StringIO()))
        with mock.patch.object(sys, "stderr", None):
            self.assertFalse(app_state.report_unexpected(type(error), error), "표준 오류가 없으면 한 줄은 False — 그래도 파일에는 남는다")
        self.assertFalse(app_state.report_unexpected(type(error), "", object()), "쓸 수 없는 흐름도 예외 없이 False")
        rows = self.lines()
        self.assertEqual([row.split(" ")[1] for row in rows], ["slot", "slot", "slot"])
        text = self.file.read_text(encoding="utf-8")
        sec.assert_no_secret(self, sec.make_canary("ELMSG"), text, "화면의 한 줄 기록")
        sec.assert_no_secret(self, KEY, text, "화면의 한 줄 기록(키 모양)")

    def test_the_hooks_never_raise_even_when_the_log_itself_breaks(self):
        """오류 기록은 덤이다 — 기록기가 고장 나도 훅은 예전처럼 표준 오류에 가린 글을 남기고 아무 예외도 내지 않는다."""
        installed = self.armed()
        error = caught()
        broken = RuntimeError("기록기가 고장")
        with mock.patch.object(errorlog, "record_exception", side_effect=broken), mock.patch.object(errorlog, "record_qt", side_effect=broken):
            sys.excepthook(type(error), error, error.__traceback__)
            threading.excepthook(types.SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=error.__traceback__, thread=types.SimpleNamespace(name="작업")))
            sys.unraisablehook(types.SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=None, err_msg="무시된 오류", object=None))
            boundary._qt_handler(types.SimpleNamespace(name="QtFatalMsg"), types.SimpleNamespace(category="qt.qpa.fonts", file=None, line=0), "Qt 글")
        installed.uninstall()
        shown = self.stderr.getvalue()
        self.assertIn("ValueError", shown, "표준 오류의 가린 추적은 그대로다")
        self.assertIn("Qt 글", shown)

    def test_the_screens_one_line_record_still_prints_when_the_log_breaks(self):
        error = caught()
        with mock.patch.object(errorlog, "record_exception", side_effect=RuntimeError("기록기가 고장")):
            stream = io.StringIO()
            self.assertTrue(app_state.report_unexpected(type(error), error, stream))
        self.assertIn("ValueError", stream.getvalue())

    def test_the_screens_one_line_record_writes_nothing_while_the_log_is_off(self):
        error = caught()
        app_state.report_unexpected(type(error), error, io.StringIO())
        self.assertFalse(self.root.exists())


class LauncherTest(Base):
    """`ui.launcher.main` 이 켠다 — 내 데이터 화면만(예시 화면은 아무것도 쓰지 않는다)."""

    def run_main(self, argv):
        from chanceblog_desktop.ui import launcher
        fake_core = FakeQtCore()
        package = types.ModuleType("PySide6")
        package.QtCore = fake_core
        seen = {}
        app = types.ModuleType("chanceblog_desktop.ui.qt.app")

        def run(provider, argv=None):
            log = errorlog.active()
            seen["armed"] = log is not None
            seen["folder"] = log._resolve() if log is not None else None
            seen["created_before_error"] = self.root.exists() or self.logs.exists()
            return 0

        app.run = run

        class FakeProvider:
            def __init__(self, *args, **kwargs):
                pass

        self.addCleanup(sec.uninstall_boundary)
        with mock.patch.object(launcher, "has_pyside6", return_value=True), mock.patch.dict(sys.modules, {"PySide6": package, "chanceblog_desktop.ui.qt.app": app}), \
                mock.patch("chanceblog_desktop.ui.adapters.ServiceHomeProvider", FakeProvider):
            self.assertEqual(launcher.main(argv), 0)
        return seen

    def test_the_screen_entry_arms_the_log_with_the_apps_own_data_folder_resolution_and_creates_nothing(self):
        seen = self.run_main(["--data-dir", str(self.root)])
        self.assertTrue(seen["armed"])
        self.assertEqual(seen["folder"], Workspace.resolve(str(self.root)).root, "새 경로 계산이 아니라 `Workspace.resolve` 그대로")
        self.assertFalse(seen["created_before_error"], "앱을 켜기만 해서는 폴더도 파일도 만들지 않는다")
        self.assertFalse(self.root.exists())

    def test_without_data_dir_the_apps_own_environment_variable_rule_picks_the_folder(self):
        """폴더 해석은 앱이 쓰는 함수(`Workspace.resolve` — `--data-dir` > 환경 변수 > 기본 위치)가 한다 — 이 시험이 그 순서를 새로 계산하는 코드를 잡는다."""
        with mock.patch.dict(os.environ, {"CHANCEBLOG_DESKTOP_DATA": str(self.root)}):
            seen = self.run_main([])
            expected = Workspace.resolve(None).root
        self.assertTrue(seen["armed"])
        self.assertEqual(seen["folder"], expected)
        self.assertEqual(seen["folder"], Path(os.path.expanduser(str(self.root))))

    def test_the_sample_screen_never_arms_the_log(self):
        seen = self.run_main(["--sample"])
        self.assertFalse(seen["armed"])

    def test_the_log_is_switched_off_when_the_boundary_is_taken_down(self):
        self.run_main(["--data-dir", str(self.root)])
        sec.uninstall_boundary()
        self.assertIsNone(errorlog.active())

    def test_the_launcher_source_arms_after_the_qt_handler_and_never_for_the_sample(self):
        tree = ast.parse((SRC / "ui" / "launcher.py").read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        shown = [ast.unparse(node) for node in main.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        qt = next(index for index, text in enumerate(shown) if text == "boundary.install_gui()")
        arm = [index for index, text in enumerate(shown) if "arm_error_log" in text]
        adapters = next(index for index, text in enumerate(shown) if text.startswith("from .adapters import"))
        self.assertEqual(len(arm), 1)
        self.assertTrue(qt < arm[0] < adapters, shown)
        self.assertIn("args.sample", shown[arm[0]], "예시 화면은 켜지 않는다")


# ---- 6b) 문서가 말한 '기록이 닿지 않는 길' 을 동작으로(3차 지시 — 검증자 1 의 N2) ------------------------------------------------------------------
class StatedLimitsAreRealTest(Base):
    """문서(SECURITY·TROUBLESHOOTING·D-488)는 네 길이 `errors.log` 에 남지 않는다고 적었다 — 묶음 실행 파일의 시작 실패(`start_gui`)·작업 스레드가 삼킨 오류(`Job`)·네이티브 충돌·데이터 폴더를 풀지 못함.
    소스에서 낱말(`errorlog`)을 찾는 대신 **기록을 켠 채 그 길에 실패를 시켜** `logs` 폴더가 안 생기는지 본다(낱말 검사는 다른 이름으로 기록기를 부르면 못 잡는다). 위에서 '폴더 없음' 이 시험 장치의 고장이 아님은
    같은 설정에서 훅으로 들어온 오류가 파일을 만드는 것(대조)으로 보인다. 누가 그 길을 기록으로 이으면(후속 항목) 이 시험들이 빨개져 문서의 한계도 함께 고치게 한다."""

    def setUp(self):
        super().setUp()
        self.assertIsNone(boundary.active(), "다른 시험이 경계를 깔아 둔 채 끝났다")
        environment = mock.patch.dict(os.environ, {"CHANCEBLOG_DESKTOP_DATA": str(self.root), "LOCALAPPDATA": str(Path(self.tmp.name) / "local")})
        environment.start()
        self.addCleanup(environment.stop)                       # 앱의 데이터 폴더 해석(`Workspace.resolve`)이 이 시험이 끝날 때까지 늘 임시 폴더로 풀린다 — 기록은 처음 쓸 때 폴더를 풀므로 환경이 되돌려진 뒤에 쓰면 진짜 기본 데이터 폴더에 쓴다
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.addCleanup(sec.uninstall_boundary)

    def armed(self):
        installed = boundary.install_gui(qt=False)
        self.assertTrue(boundary.arm_error_log(lambda: self.root))
        return installed

    def assert_the_control_writes(self):
        """대조 — 같은 설정에서 처리하지 못한 예외가 훅으로 들어오면 파일이 만들어진다(위의 '폴더 없음' 이 시험 장치의 고장이 아니다)."""
        error = caught(canary_message())
        sys.excepthook(type(error), error, error.__traceback__)
        self.assertEqual(self.names(), ["errors.log"])

    def test_a_start_failure_of_the_bundle_entry_is_only_told_by_a_message_and_never_reaches_the_log(self):
        import packaging_support as ps
        from chanceblog_desktop.ui import launcher
        entry, spoken, seen = ps.gui_entry, [], {}
        package = types.ModuleType("PySide6")
        package.QtCore = FakeQtCore()
        app = types.ModuleType("chanceblog_desktop.ui.qt.app")

        def run(provider, argv=None):
            seen["armed"] = errorlog.active() is not None
            raise ImportError("DLL load failed while importing QtWidgets: C:/Users/" + sec.make_canary("ELDLL") + "/x.dll")          # 창 없는 묶음에서 흔한 시작 실패

        app.run = run

        class FakeProvider:
            def __init__(self, *args, **kwargs):
                pass

        with mock.patch.object(launcher, "has_pyside6", return_value=True), \
                mock.patch.dict(sys.modules, {"PySide6": package, "chanceblog_desktop.ui.qt.app": app}), mock.patch("chanceblog_desktop.ui.adapters.ServiceHomeProvider", FakeProvider), \
                mock.patch.object(entry, "say", lambda text, error=False: spoken.append(text)):
            code = entry.start_gui()
        self.assertEqual((code, spoken), (entry.EXIT_FAILED, [entry.START_FAILED.format(kind="ImportError")]), "시작 실패는 메시지 상자(고정 문장, 오류 종류 이름만)로만 알린다")
        self.assertTrue(seen["armed"], "화면 진입점이 기록을 켠 뒤에 시작이 실패했다")
        self.assertFalse(self.root.exists(), "시작 실패는 훅까지 오지 않으므로 데이터 폴더도 `logs` 도 생기지 않는다")
        self.assert_the_control_writes()

    def test_a_job_that_fails_is_told_to_the_screen_and_never_reaches_the_log(self):
        self.armed()
        heard, done = {}, threading.Event()

        def work(progress, cancelled):
            raise KeyError(canary_message())

        def on_error(failure, payload):
            heard["code"], heard["shown"] = failure.code, failure.user_message
            done.set()

        job = jobs.JobRunner().start("limit-probe", work, on_error=on_error)
        self.assertTrue(done.wait(10))
        job.join(10)
        self.assertEqual(heard["code"], "KeyError", "작업 실패는 화면으로 올라갔다(오류 이름만)")
        self.assertNotIn("CANARY_BODY", heard["shown"])
        self.assertFalse(self.root.exists(), "작업 스레드가 삼킨 오류는 훅까지 오지 않으므로 `logs` 가 생기지 않는다")
        self.assert_the_control_writes()

    def test_an_error_inside_a_screen_callback_of_a_job_never_reaches_the_log(self):
        self.armed()
        finished = threading.Event()

        def work(progress, cancelled):
            return "결과"

        def on_done(result, payload):
            finished.set()
            raise ValueError(canary_message())

        job = jobs.JobRunner().start("callback-probe", work, on_done=on_done)
        self.assertTrue(finished.wait(10))
        job.join(10)
        self.assertEqual((job.state, job.callback_error), (jobs.Job.DONE, "ValueError"), "콜백의 오류는 이름만 기억하고 삼킨다")
        self.assertFalse(self.root.exists(), "화면 콜백의 오류도 훅까지 오지 않는다")
        self.assert_the_control_writes()

    def test_a_native_crash_leaves_no_dump_because_the_app_never_turns_the_crash_handler_on(self):
        import faulthandler
        if faulthandler.is_enabled():
            self.skipTest("시험 실행기가 이미 충돌 덤프를 켜 두었다")
        self.armed()
        self.assertFalse(faulthandler.is_enabled(), "경계와 오류 기록을 켜도 충돌 덤프는 켜지지 않는다")
        self.assertFalse(self.root.exists())

    def test_a_data_folder_the_app_refuses_is_not_written_to_and_the_line_is_dropped(self):
        """데이터 폴더를 풀지 못하는 실제 모습 — git 저장소 안의 폴더는 앱이 거절(`DATA_DIR_UNSAFE`)하므로 그 줄은 버려지고 그 폴더에도 `logs` 가 생기지 않는다."""
        from chanceblog_desktop.ui import launcher
        repo = Path(self.tmp.name) / "repo"
        (repo / ".git").mkdir(parents=True)
        unsafe = repo / "data"
        log = errorlog.ErrorLog(launcher._data_folder_of(str(unsafe)), clock=fixed_clock)
        self.assertFalse(log.record("main", ValueError, caught()))
        self.assertFalse(unsafe.exists(), "앱이 거절한 폴더에는 아무것도 만들지 않는다")
        self.assertFalse(log.record("main", ValueError, caught()), "다음 오류도 같은 이유로 버려진다")


# ---- 7) 백업 ---------------------------------------------------------------------------------------------------------------------------
class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = bs.World(self.tmp.name)
        self.logs = self.world.root / "logs"

    def plant(self):
        log = errorlog.ErrorLog(lambda: self.world.root, clock=fixed_clock)
        self.assertTrue(log.record("main", ValueError, caught()))
        return sorted(path.name for path in self.logs.iterdir())

    def test_the_manifest_lists_logs_as_left_out_and_says_what_it_is(self):
        names = [name for name, _ in backup_note.EXCLUDED]
        self.assertIn("logs/", names)
        reason = dict(backup_note.EXCLUDED)["logs/"]
        for word in ("오류 이름", "코드 위치", "담지 않아요"):
            self.assertIn(word, reason)
        self.assertNotIn("로그 파일을 만들지 않", " ".join(text for _, text in backup_note.EXCLUDED), "더는 사실이 아니다")
        self.assertEqual(len(set(names)), len(names))

    def test_a_backup_of_a_folder_that_has_the_log_does_not_contain_it_and_the_manifest_names_logs(self):
        planted = self.plant()
        self.assertEqual(planted, ["errors.log"])
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        self.assertEqual(sorted(path.name for path in folder.iterdir()), sorted([item.name for item in bf.COMPONENTS] + [bf.MANIFEST_NAME]), "백업 폴더에는 담는 여섯 파일과 목록뿐이다")
        self.assertFalse(any(path.name.startswith(("logs", "errors.log")) for path in folder.rglob("*")), "백업에 오류 기록이 들어갔다")
        manifest = self.world.manifest(outcome)
        self.assertIn("logs/", [item["name"] for item in manifest["excluded"]])
        self.assertNotIn("errors.log", json_text(manifest), "목록에도 로그 내용·파일이 없다")

    def test_a_backup_made_before_and_after_the_log_exists_has_the_same_files(self):
        first = self.world.backup()
        before = sorted(path.name for path in self.world.folder(first).iterdir())
        self.plant()
        second = self.world.backup()
        after = sorted(path.name for path in self.world.folder(second).iterdir())
        self.assertEqual(before, after)

    def test_a_restore_leaves_the_log_alone(self):
        outcome = self.world.backup()
        self.plant()
        before = (self.logs / "errors.log").read_bytes()
        bf.restore_full_backup(self.world.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((self.logs / "errors.log").read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.logs.iterdir()), ["errors.log"])


def json_text(value):
    import json
    return json.dumps(value, ensure_ascii=False)


# ---- 8) 없어야 하는 것 ----------------------------------------------------------------------------------------------------------------
class NothingElseTest(unittest.TestCase):
    ALLOWED_IMPORTS = {"__future__", "collections", "os", "re", "sys", "threading", "time", "datetime", "pathlib"}          # `collections` 는 추적의 안쪽 여섯만 쥐는 `deque`(N4)

    def test_the_module_imports_only_a_few_standard_modules_and_the_common_mask(self):
        tree = ast.parse((SRC / "security" / "errorlog.py").read_text(encoding="utf-8"))
        absolute, relative = set(), []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                absolute.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    relative.append((node.module, tuple(alias.name for alias in node.names)))
                else:
                    absolute.add((node.module or "").split(".")[0])
        self.assertEqual(sorted(absolute - self.ALLOWED_IMPORTS), [])
        self.assertEqual(relative, [("mask", ("mask",))], "이 모듈이 가져오는 앱 안의 것은 공통 가림 함수 하나다")

    def test_the_module_never_prints_never_names_standard_output_or_error_and_never_runs_a_process(self):
        source = (SRC / "security" / "errorlog.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertNotIn("print", calls)
        attributes = {ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        for forbidden in ("sys.stdout", "sys.stderr", "sys.__stdout__", "sys.__stderr__", "sys.excepthook", "threading.excepthook", "sys.unraisablehook"):
            self.assertNotIn(forbidden, attributes)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(part for alias in node.names for part in alias.name.split("."))
            elif isinstance(node, ast.ImportFrom):
                imported.update((node.module or "").split(".") + [alias.name for alias in node.names])
        for word in ("subprocess", "socket", "urllib", "ht" + "tp", "faulthandler", "traceback", "logging", "ctypes", "shutil", "tempfile"):          # 'ht'+'tp' — 낱말이 소스에 그대로 적히지 않게 이어 붙였다
            self.assertNotIn(word, imported)
        self.assertEqual({name for name in calls if name.startswith("os.")}, {"os.replace"}, "os 로 하는 일은 이름 바꾸기 하나뿐이다(프로세스·셸·파일 열기 호출 없음)")

    def test_writing_a_line_opens_no_socket_and_reaches_no_network(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(socket, "socket", side_effect=AssertionError("네트워크")), mock.patch.object(socket, "create_connection", side_effect=AssertionError("네트워크")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("네트워크")):
            log = errorlog.ErrorLog(lambda: Path(tmp), clock=fixed_clock)
            self.assertTrue(log.record("main", ValueError, caught()))

    def test_no_crash_dump_is_made_by_the_app(self):
        """충돌 덤프(`faulthandler`·미니덤프)는 가림을 걸 수 없어 만들지 않는다 — 소스 어디에도 가져오기·호출이 없다."""
        found = []
        for path in sorted(SRC.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                if any(name.split(".")[0] == "faulthandler" for name in names):
                    found.append(path.name)
            if re.search(r"MiniDump|minidump|enable_crash|dump_traceback", text.replace("`", "")):
                if path.name not in ("boundary.py", "errorlog.py"):
                    found.append(path.name + ":dump")
        self.assertEqual(found, [])


# ---- 9) 문서 ---------------------------------------------------------------------------------------------------------------------------
class DocsTest(unittest.TestCase):
    def doc(self, name):
        return (ROOT / "docs" / name).read_text(encoding="utf-8")

    def test_the_docs_say_there_is_a_small_error_log_and_where_it_is(self):
        security, trouble = self.doc("SECURITY.md"), self.doc("TROUBLESHOOTING.md")
        for text in (security, trouble):
            for word in ("logs", "errors.log", "256 KB"):
                self.assertIn(word, text)
        self.assertIn("오류 이름과 코드 위치", security)
        self.assertIn("처음 만들", security)
        self.assertIn("충돌 덤프", security)
        self.assertNotIn("**로그 파일·내보내기**: 아직 없다", security)
        self.assertNotIn("지금은 로그 파일이나", trouble, "로그 파일이 없다는 옛 문장이 남았다")
        self.assertIn("'설정 → 로그 내보내기' 기능은 **아직 없습니다**", trouble, "내보내기 기능이 아직 없다는 것은 그대로 사실이다")

    def test_the_screen_docs_no_longer_say_the_app_writes_no_file_when_there_is_no_standard_error(self):
        for name in ("UI_STATES.md", "UI_DESIGN_SPEC.md"):
            text = self.doc(name)
            self.assertIn("콘솔 실행 기준", text, name)
            self.assertNotIn("이 묶음은 파일을 쓰지 않는다", text, name)
            self.assertNotIn("로그 파일은 설치 파일 묶음", text, name)
            self.assertIn("errors.log", text, name)

    def test_the_architecture_doc_lists_the_new_module(self):
        self.assertIn("errorlog.py", self.doc("ARCHITECTURE.md"))

    def decision_row(self, number):
        rows = re.findall(rf"^\| {number} \|.*$", self.doc("DECISIONS.md"), re.M)
        self.assertEqual(len(rows), 1, number)
        return rows[0]

    def test_the_docs_list_the_ways_that_never_reach_the_log(self):
        """한계 — 묶음 실행 파일의 시작 실패·작업 스레드가 삼키는 오류·네이티브 충돌·데이터 폴더를 풀지 못함은 기록되지 않는다고 문서가 말한다(모든 오류가 남는다는 인상을 주지 않게)."""
        security = self.doc("SECURITY.md")
        section = security[security.index("## 오류 기록("):]
        for word in ("기록이 닿지 않는 길", "start_gui", "ui/core/jobs.py", "네이티브 충돌", "데이터 폴더를 풀지 못하면", "후속 항목"):
            self.assertIn(word, section, word)
        trouble = self.doc("TROUBLESHOOTING.md")
        for word in ("이 파일에 남지 않는 경우", "시작하자마자 멈춘", "화면의 안내 문장으로 바꿔", "갑자기 꺼진", "데이터 폴더를 찾지 못한"):
            self.assertIn(word, trouble, word)
        for word in ("start_gui", "jobs.py", "네이티브 충돌", "후속 항목"):
            self.assertIn(word, self.decision_row("D-488"), word)
        self.assertIn("기록이 닿지 않는 길", (SRC / "security" / "errorlog.py").read_text(encoding="utf-8"))

    def test_the_stated_limits_are_still_true_in_the_code(self):
        """문서가 '기록되지 않는다' 고 적은 길(`start_gui`·`Job._run`·`Job._emit`)이 실제로 기록기를 부르지 않는다 — 누가 그 길을 이으면 이 시험이 빨개져 문서의 한계를 함께 고치게 한다."""
        for rel in ("packaging/gui_entry.py", "src/chanceblog_desktop/ui/core/jobs.py"):
            self.assertNotIn("errorlog", (ROOT / rel).read_text(encoding="utf-8"), rel)
        entry = ast.parse((ROOT / "packaging" / "gui_entry.py").read_text(encoding="utf-8"))
        start = next(node for node in ast.walk(entry) if isinstance(node, ast.FunctionDef) and node.name == "start_gui")
        handlers = [node for node in ast.walk(start) if isinstance(node, ast.ExceptHandler)]
        self.assertEqual([ast.unparse(node.type) for node in handlers], ["Exception"], "`start_gui` 는 시작 실패를 잡아 메시지 상자로 알리고 끝낸다")

    def test_the_docs_describe_the_rate_limit_and_the_tests_that_arm_the_log_accurately(self):
        security = self.doc("SECURITY.md")
        source = (SRC / "security" / "errorlog.py").read_text(encoding="utf-8")
        self.assertIn("정해진 1분 구간마다 30줄", security)
        self.assertIn("정해진 1분 구간마다 30줄", source)
        self.assertIn("구간 경계에서는 짧은 시간에 더 나올 수 있다", security)
        for text, label in ((security, "SECURITY.md"), (source, "errorlog.py")):
            self.assertNotIn("1분에 30줄까지만", text, label)
            self.assertNotIn("예시 화면·시험은 켜지 않는다", text, label)
            self.assertNotIn("예시 화면(`--sample`)·시험은 켜지 않고", text, label)
        self.assertIn("`--sample` 없이 `launcher.main` 을 끝까지 부르는 기존 시험은 켜진다", security)
        self.assertNotIn("이름 바꾸기가 막히면 옛 파일 셋은 한 글자도 바뀌지 않는다", security, "첫 단계가 막힐 때만 참인 말이다 — 현재 파일 쪽이 막히면 `.2` 가 옛 `.1` 이 된다")
        self.assertIn("첫 단계(`.1` → `.2`)가 막히면 옛 파일 셋은 한 글자도 바뀌지 않고", security)
        self.assertIn("`.2` 가 옛 `.1` 의 내용으로 바뀌어 있고(옛 `.2` 는 덮어쓰여 사라진다)", security)
        self.assertIn("어느 단계가 막혔느냐에 따라 남는 모습이 다르다", source)
        self.assertIn("`--sample` 없이 `launcher.main` 을 끝까지 부르는 기존 시험은 켜지지만", source)

    def error_report_block(self):
        """TROUBLESHOOTING 의 '오류 보고서' 항목 — 첫 줄과 그 아래 들여 쓴 하위 항목들(다음 바깥 항목 앞까지)."""
        rows = self.doc("TROUBLESHOOTING.md").splitlines()
        start = next(index for index, row in enumerate(rows) if row.startswith("- **오류 보고서**"))
        end = start + 1
        while end < len(rows) and rows[end].startswith("  - "):
            end += 1
        return rows[start:end]

    def test_the_troubleshooting_doc_says_how_to_open_the_log_folder(self):
        line = "\n".join(self.error_report_block())
        for word in ("`Win` 키와 `R` 키", "'실행' 창", "%LOCALAPPDATA%\\ChanceblogDesktop\\logs", "Enter", "CHANCEBLOG_DESKTOP_DATA"):
            self.assertIn(word, line, word)

    def test_the_docstrings_of_the_screens_record_and_the_boundary_say_the_truth(self):
        state = (SRC / "ui" / "core" / "app_state.py").read_text(encoding="utf-8")
        self.assertNotIn("이 묶음은 파일을 쓰지 않는다(읽기 전용)", state)
        self.assertIn("errorlog", state)
        gate = (SRC / "security" / "boundary.py").read_text(encoding="utf-8")
        self.assertNotIn("로그 파일 핸들러는 만들지 않는다 — 없는 기능이다", gate)

    def test_the_error_report_item_is_short_items_and_does_not_contradict_itself(self):
        """(3차 지시, N5) 한 항목에 1,500자가 넘게 들어 있던 '오류 보고서' 를 짧은 하위 항목으로 쪼갰고, '폴더가 없으면 기록할 오류가 없었던 것' 이라는 말이 '이 파일에 남지 않는 경우' 와 어긋나던 것을 고쳤다.
        '로그 파일·내보내기 기능은 아직 없습니다' 라는 UNEXPECTED_ERROR 안내도 로그 파일이 생긴 지금은 거짓이라 '내보내는 기능' 만 없다고 고쳤다."""
        block = self.error_report_block()
        self.assertGreaterEqual(len(block), 7, "첫 줄 하나와 하위 항목 여섯 이상")
        for row in block:
            self.assertLessEqual(len(row), 380, "항목이 다시 길어졌다: " + row[:30])
        text = "\n".join(block)
        self.assertNotIn("기록할 오류가 없었던 것입니다", text, "남지 않는 경우가 있으므로 '폴더가 없으면 오류가 없었다' 고 말할 수 없다")
        self.assertIn("오류가 있어도 폴더가 없을 수 있습니다", text)
        self.assertIn("오류가 없었다는 뜻이 아니니", text)
        row = next(row for row in self.doc("TROUBLESHOOTING.md").splitlines() if row.startswith("| `UNEXPECTED_ERROR` |"))
        self.assertNotIn("로그 파일·내보내기 기능은 아직 없습니다", row, "로그 파일은 있다 — 없는 것은 내보내기 기능이다")
        self.assertIn("로그를 내보내는 기능은 아직 없습니다", row)
        self.assertIn("로그를 내보내는 기능은 아직 없습니다", (SRC / "errors" / "catalog.py").read_text(encoding="utf-8"), "화면에 나오는 안내(오류 카탈로그)도 같다")

    def test_no_living_document_keeps_a_sentence_the_log_file_made_false_and_no_text_over_claims_the_rotation(self):
        """(3차 지시) 로그 파일이 생겨 거짓이 된 문장('로그 파일이 없다·설치 파일 묶음에서 정한다')이 지금 쓰는 문서와 코드 설명 어디에도 없고, 돌려쓰기를 과장하는 문장('막혀도 옛 파일이 그대로·잃지 않는다')이
        변경 이력·결정 기록(D-488)을 포함해 어디에도 없다. 결정 기록과 변경 이력은 옛 결정·옛 변경의 원문을 그대로 두는 곳이라 '거짓이 된 문장' 은 훑지 않는다."""
        stale = ("로그 파일은 설치 파일 묶음", "로그 파일과 내보내기 기능은 아직 없다", "로그 파일·내보내기 기능은 아직 없", "로그 파일 핸들러는 만들지 않았다(없는 기능)", "이 묶음은 파일을 쓰지 않는다")
        over_claims = ("막혀도 옛 파일을 잃지 않는다", "옛 파일 셋도 그대로 둔다", "막혀도 옛 파일 셋이 그대로", "가장 오래된 `.2` 도 잃지 않는다", "이름 바꾸기가 막히면 옛 파일 셋은 한 글자도 바뀌지 않는다", "돌려쓰기가 막혔을 때 옛 파일 보존")
        living = {name: self.doc(name) for name in ("SECURITY.md", "TROUBLESHOOTING.md", "ARCHITECTURE.md", "UI_STATES.md", "UI_DESIGN_SPEC.md", "PACKAGE.md", "PERSONAL_PC_TEST.md")}
        living["README.md"] = (ROOT / "README.md").read_text(encoding="utf-8")
        living["errorlog.py"] = (SRC / "security" / "errorlog.py").read_text(encoding="utf-8")
        living["errors/catalog.py"] = (SRC / "errors" / "catalog.py").read_text(encoding="utf-8")
        for name, text in living.items():
            for phrase in stale:
                self.assertNotIn(phrase, text, f"{name}: 로그 파일이 생겨 거짓이 된 문장이 남았다")
        history = dict(living, **{"CHANGELOG.md": (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), "D-488": self.decision_row("D-488")})
        for name, text in history.items():
            for phrase in over_claims:
                self.assertNotIn(phrase, text, f"{name}: 돌려쓰기를 과장하는 문장이 남았다")
        self.assertIn("`.2` 가 옛 `.1` 의 내용이 된다", self.decision_row("D-488"), "결정 기록이 막힌 단계에 따라 다른 모습을 적는다")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        line = next(row for row in changelog.splitlines() if row.startswith("- 앱이 처리하지 못한 오류의 이름과 코드 위치만"))
        self.assertIn("첫 단계가 막히면 옛 파일 셋이 그대로이고", line)
        self.assertIn("현재 파일 쪽이 막히면 `.2` 가 옛 `.1` 이 되며", line)


if __name__ == "__main__":
    unittest.main()
