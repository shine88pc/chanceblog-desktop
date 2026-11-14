"""오류 기록(작은 로그 파일) 시험 — AP14, 확인 015 승인 9번(데스크톱 F034, 결정 D-488): 앱이 처리하지 못한 오류가 나도 남는 기록이 없어 알리기 어려웠다 → 데이터 폴더 안에
**오류 이름과 코드 위치만** 가려서 남기는 256 KB 짜리 세 개 돌려쓰기 로그(`security/errorlog.py`)를 허용했다. 이 시험은 그 한계들이 지켜지는지 본다.

지키는 것(모두 PySide6 없이 돈다 — CI 와 같은 조건):
  1) 켜 두기(`arm`)만으로는 아무것도 읽거나 만들지 않는다 — 폴더도 파일도 없다. **첫 오류가 났을 때 처음 만든다**(`logs/errors.log`).
  2) 줄에는 시각·갈래·**오류 클래스 이름**·**코드 위치(파일 이름:줄)** 뿐이다. `CANARY_` 가짜 비밀·가짜 경로·가짜 글이 든 오류 메시지는 한 글자도 남지 않고(메시지는 읽지도 않는다), 위치의 폴더 앞부분(사용자 이름이 든 절대경로)도 없다.
  3) 줄은 앱의 공통 가림 규칙(`security/mask.py` 의 `mask`)을 한 번 더 거친다 — 이 모듈에 새 가림 규칙은 없다.
  4) 256 KB 를 넘기게 되면 돌려쓰고 파일은 셋(`errors.log`·`.1`·`.2`)을 넘지 않으며 가장 오래된 것부터 사라진다. 돌려쓰기가 막히면 한도를 넘겨 쓰지 않고 그 줄을 버린다.
  5) 쓰기·폴더 만들기·이름 바꾸기·폴더 해석이 실패해도 예외 없이 `False` 이고 다음 오류는 다시 쓸 수 있다. 1분에 30줄까지만 쓴다. `KeyboardInterrupt`·`SystemExit` 는 오류가 아니라 남기지 않는다.
  6) 공통 경계(`security/boundary.py`)의 훅 셋·Qt 메시지와 화면의 한 줄 기록(`report_unexpected`)에서 들어오고, 경계를 되돌리면 꺼진다. **화면(GUI) 진입점만 켠다** — 예시 화면(`--sample`)은 켜지 않는다.
  7) 백업에 넣지 않고(담지 않는 것 목록에 `logs/`) 복원이 건드리지 않는다.
  8) 네트워크·하위 프로세스·표준 출력·표준 오류·`logging`·`traceback`·`faulthandler` 가 없다 — 가져오는 것은 아래의 표준 라이브러리 몇 개와 `mask` 뿐이다.
  9) 문서(SECURITY·TROUBLESHOOTING·UI_STATES·UI_DESIGN_SPEC)가 '파일에 쓰지 않는다·로그 파일은 아직 없다' 가 아니라 사실(작은 오류 기록 파일이 있다)을 적는다.
가짜 비밀은 `CANARY_` 로 시작하는 조립 문자열이다. 임시 폴더만 쓰고 사용자의 데이터 폴더·네트워크를 건드리지 않는다.
"""
import ast
import contextlib
import errno
import hashlib
import io
import os
import re
import socket
import sys
import tempfile
import threading
import traceback
import types
import unittest
from datetime import datetime, timezone
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
from chanceblog_desktop.ui.core import app_state  # noqa: E402

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

    def test_the_time_is_utc_and_ascii(self):
        zone = timezone.utc
        log = errorlog.ErrorLog(lambda: self.root, clock=lambda: datetime(2026, 11, 15, 16, 41, 5, tzinfo=timezone.utc).astimezone(zone))
        log.record("main", ValueError, caught())
        self.assertTrue(self.lines()[0].startswith("2026-11-15T16:41:05Z "))
        self.assertTrue(self.file.read_bytes().isascii())

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
    ALLOWED_IMPORTS = {"__future__", "os", "re", "sys", "threading", "time", "datetime", "pathlib"}

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
        for word in ("subprocess", "socket", "urllib", "http", "faulthandler", "traceback", "logging", "ctypes", "shutil", "tempfile"):
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

    def test_the_docstrings_of_the_screens_record_and_the_boundary_say_the_truth(self):
        state = (SRC / "ui" / "core" / "app_state.py").read_text(encoding="utf-8")
        self.assertNotIn("이 묶음은 파일을 쓰지 않는다(읽기 전용)", state)
        self.assertIn("errorlog", state)
        gate = (SRC / "security" / "boundary.py").read_text(encoding="utf-8")
        self.assertNotIn("로그 파일 핸들러는 만들지 않는다 — 없는 기능이다", gate)


if __name__ == "__main__":
    unittest.main()
