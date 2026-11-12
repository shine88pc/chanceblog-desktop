"""공통 경계(`security/boundary.py`) 시험 — 비밀이 프로세스 밖(표준 출력·오류·로그·처리하지 못한 예외·Qt 메시지)으로 나가기 전에 한 곳에서 걸러지는가(PCSEC1 H1).

지키는 것:
  1) `RedactingStream`: 여러 `write()` 에 쪼개진 비밀도 줄이 끝날 때 한 덩어리로 가려진다. 평범한 글은 한 글자도 바뀌지 않는다. 줄바꿈 없는 조각은 `flush()` 때 마지막 공백 앞까지만 나가고 나머지는
     줄 끝·`finish()`·`close()`·종료까지 남는다. 개인 키 블록(여러 줄)·값이 다음 줄에 오는 모양·너무 쌓인 조각·여러 스레드의 동시 쓰기를 안전하게 다룬다. `encoding`·`reconfigure`·`buffer` 같은 속성은 원래 스트림이 답한다.
  2) `install()`: 표준 출력·오류·처리하지 못한 예외 훅 셋·`logging` 에 거는 것이 멱등이고 `uninstall()` 이 원래대로 돌린다. 훅 셋과 `logging`(문장·인자·추적)·`warnings`·Qt 메시지 핸들러가 비밀을 가려서 낸다.
  3) 진짜 진입점(`python -m chanceblog_desktop`)이 맨 앞에서 설치하고, `--debug` 가 예외를 되던져도 진짜 프로세스의 추적에 비밀이 없다 — 대조 실험(경계 없이 같은 예외)은 비밀이 나와서, 이 확인이 실제로 빨개질 수 있음을 보인다.
시험이 키 모양 값을 소스에 통째로 쓰지 않는다(런타임 조립 `CANARY_`). 네트워크·실제 보관소 없이 돈다. 설치는 시험마다 반드시 되돌린다.
"""
import ast
import contextlib
import hashlib
import io
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import types
import unittest
import warnings
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import secret_support as sec  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import boundary  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402

KEY = "AI" + "za" + ("CANARY_BND_" + hashlib.sha256(b"pcsec1-boundary-key").hexdigest())[:35]          # 구글 키 모양(35자) — 안에 CANARY 가 든다(런타임 조립)
BEGIN = "-----BEGIN " + "PRIVATE KEY-----\n"
END = "-----END " + "PRIVATE KEY-----\n"
BODY_LINES = ("TUlJRXZRSUJBREFOQmdrcWhraUc5dzBCQVFFRkFBU0M=\n", "YWJjZEVGR0gxMjM0NTY3ODkwYWJjZEVGR0gxMjM0NTY3ODkw\n")


def pieces(text, count):
    step = max(len(text) // count, 1)
    return [text[index:index + step] for index in range(0, len(text), step)]


class Isolated(unittest.TestCase):
    """경계를 깐 시험은 끝나면 반드시 되돌린다(다른 시험의 `sys.stdout` 이 래핑된 채 남지 않게)."""

    def setUp(self):
        self.assertIsNone(boundary.active(), "다른 시험이 경계를 깔아 둔 채 끝났다")
        self.addCleanup(self._undo)

    @staticmethod
    def _undo():
        installed = boundary.active()
        if installed is not None:
            installed.uninstall()


class StreamTest(unittest.TestCase):
    def stream(self, **kwargs):
        raw = io.StringIO()
        return raw, boundary.RedactingStream(raw, **kwargs)

    def test_a_long_header_line_with_many_pairs_is_not_cut_at_a_space_so_the_last_pair_keeps_its_label(self):
        """PCSEC1V D5(a): 줄바꿈 없는 4096자 넘는 헤더 줄(`Cookie: a=1; …; sid=값`)을 마지막 공백에서 자르면 뒤쪽 쌍이 이름표 없이 나갔다 — 헤더 줄은 줄이 끝날 때까지(상한 안) 쥐고 통째로 가린다."""
        value = sec.make_canary("HDRPAIR")                                                   # 모양이 없는 가짜 값 — 키 모양이면 이름표 없이도 모양으로 가려져 이 시험이 아무것도 못 본다
        for name in ("Cookie", "cookie", "Set-Cookie", "> Cookie", "Authorization", "Proxy-Authorization"):
            with self.subTest(header=name):
                raw, stream = self.stream()
                stream.write(name + ": " + "a=1; " * 1100 + "sid=" + value)                  # 줄바꿈 없이 4096자를 넘는다
                self.assertEqual(raw.getvalue(), "", "상한 안의 헤더 줄은 줄이 끝나기 전에 조각으로 나가지 않는다(자르면 마지막 쌍이 이름표 없이 나간다)")
                stream.write("\n")
                out = raw.getvalue()
                sec.assert_no_secret(self, value, out, "긴 헤더 줄")
                self.assertTrue(out.startswith(name + ": "), out[:30])

    def test_a_header_line_beyond_the_hard_limit_is_still_flushed_masked_as_a_whole(self):
        raw, stream = self.stream()
        value = sec.make_canary("HDRHARD")
        stream.write("Cookie: " + "a=1; " * 4000 + "sid=" + value)                         # 상한(16384자)을 넘는다 — 쥐고만 있을 수는 없다
        self.assertGreater(len(raw.getvalue()), 0, "상한을 넘으면 줄이 끝나기 전에도 내보낸다")
        sec.assert_no_secret(self, value, raw.getvalue(), "줄이 끝나기 전에 나간 글")
        stream.write("\n")
        out = raw.getvalue()
        sec.assert_no_secret(self, value, out, "상한을 넘은 헤더 줄")
        self.assertTrue(out.startswith("Cookie: "))

    def test_a_long_line_that_is_not_a_header_is_still_cut_at_a_space_and_flows_out_early(self):
        raw, stream = self.stream()
        stream.write("가나다 " * 2000)                                                      # 헤더가 아닌 긴 줄은 예전처럼 공백에서 잘라 먼저 나간다
        self.assertGreater(len(raw.getvalue()), 4000)
        self.assertLess(len(raw.getvalue()), 8001)


    def test_a_secret_split_over_many_writes_is_masked_when_the_line_ends(self):
        for count in (2, 3, 7, len(KEY)):
            with self.subTest(pieces=count):
                raw, stream = self.stream()
                stream.write("앞 글 ")
                for part in pieces(KEY, count):
                    stream.write(part)
                stream.write(" 뒤 글")
                self.assertEqual(raw.getvalue(), "", "줄바꿈이 오기 전에는 아무것도 내보내지 않는다")
                stream.write("\n")
                out = raw.getvalue()
                sec.assert_no_secret(self, KEY, out, f"{count}조각으로 쪼갠 비밀")
                self.assertTrue(out.startswith("앞 글 ") and out.endswith(" 뒤 글\n"), "앞뒤 글은 그대로다")

    def test_ordinary_text_comes_out_byte_for_byte(self):
        text = "평범한 문장입니다.\n둘째 줄 — 해시 " + "0123456789abcdef" * 2 + "01234567\n\n셋째 https://example.com/a?b=c 끝\n"
        raw, stream = self.stream()
        for chunk in pieces(text, 9):
            stream.write(chunk)
        stream.finish()
        self.assertEqual(raw.getvalue(), text)
        raw, stream = self.stream()
        print("a", "b", 3, sep=" | ", file=stream)                   # print 는 글자 조각 → 구분 → 줄바꿈을 따로 쓴다
        self.assertEqual(raw.getvalue(), "a | b | 3\n")

    def test_flush_sends_text_up_to_the_last_space_and_keeps_a_piece_without_one(self):
        raw, stream = self.stream()
        stream.write("진행 중 ")
        stream.flush()
        self.assertEqual(raw.getvalue(), "진행 중 ", "공백으로 끝난 조각(질문 같은 것)은 바로 나간다")
        stream.write("키는 " + KEY[:10])
        stream.flush()
        sec.assert_no_secret(self, KEY, raw.getvalue(), "flush 로 나간 글")
        self.assertEqual(raw.getvalue(), "진행 중 키는 ", "공백 없는 뒤 조각은 줄 끝까지 쥔다")
        stream.write(KEY[10:] + "\n")
        sec.assert_no_secret(self, KEY, raw.getvalue(), "줄이 끝난 뒤 글")
        self.assertTrue(raw.getvalue().startswith("진행 중 키는 ") and raw.getvalue().endswith("\n"))

    def test_finish_and_close_send_the_last_piece_masked(self):
        raw, stream = self.stream()
        stream.write("끝줄 " + KEY)                                    # 줄바꿈 없이 끝난 글(프로세스 종료 때 남는 조각)
        self.assertEqual(raw.getvalue(), "")
        self.assertTrue(stream.finish())
        sec.assert_no_secret(self, KEY, raw.getvalue(), "finish 로 나간 글")
        self.assertTrue(raw.getvalue().startswith("끝줄 "))
        class Keeping(io.StringIO):
            saved = None

            def close(self):
                self.saved = self.getvalue()                               # 닫으면 getvalue 가 안 되므로 닫기 직전의 글을 적어 둔다
                super().close()

        raw = Keeping()
        stream = boundary.RedactingStream(raw)
        stream.write("닫기 " + KEY)
        stream.close()
        sec.assert_no_secret(self, KEY, raw.saved, "close 로 나간 글")
        self.assertTrue(raw.saved.startswith("닫기 "))
        self.assertTrue(raw.closed, "닫으면 원래 스트림도 닫힌다")
        stream.write("닫힌 뒤에 온 조각")
        self.assertFalse(stream.finish(), "이미 닫힌 스트림에 낼 글이 남았으면 오류 없이 False")

    def test_attributes_come_from_the_wrapped_stream(self):
        buffer = io.BytesIO()
        text = io.TextIOWrapper(buffer, encoding="cp949", errors="strict", newline="")
        stream = boundary.RedactingStream(text)
        self.assertEqual(stream.encoding, "cp949")
        stream.reconfigure(errors="replace")                              # 명령줄이 부르는 `_lenient`
        self.assertEqual(stream.errors, "replace")
        self.assertIs(stream.buffer, buffer)
        self.assertFalse(stream.isatty())
        stream.write("가나\n")
        stream.flush()
        self.assertEqual(buffer.getvalue(), "가나\n".encode("cp949"))
        self.assertIs(stream.raw, text)
        self.assertIn("RedactingStream", repr(stream))
        with self.assertRaises(AttributeError):
            stream.no_such_attribute_here

    def test_a_private_key_block_spread_over_many_writes_is_masked_whole(self):
        raw, stream = self.stream()
        stream.write("앞 줄\n")
        stream.write(BEGIN)
        self.assertEqual(raw.getvalue(), "앞 줄\n", "블록이 끝나기 전에는 본문 줄이 나가지 않는다")
        for line in BODY_LINES:
            stream.write(line)
        self.assertEqual(raw.getvalue(), "앞 줄\n")
        stream.write(END)
        stream.write("뒷 줄\n")
        out = raw.getvalue()
        for line in BODY_LINES:
            self.assertNotIn(line.strip(), out)
        self.assertTrue(out.startswith("앞 줄\n") and out.endswith("뒷 줄\n"))
        raw, stream = self.stream()
        stream.write(BEGIN + BODY_LINES[0])                                # 끝줄 없이 끝나는 블록
        stream.finish()
        self.assertNotIn(BODY_LINES[0].strip(), raw.getvalue())

    def test_an_endless_block_is_sent_masked_at_the_limit_and_the_lines_after_it_are_dropped_until_the_end_line(self):
        with mock.patch.object(boundary, "BLOCK_LIMIT", 120):
            raw, stream = self.stream()
            stream.write(BEGIN)
            for _ in range(8):
                stream.write(BODY_LINES[1])
            self.assertTrue(raw.getvalue(), "한도를 넘으면 통째로 가려 내보낸다")
            sent = raw.getvalue()
            self.assertNotIn(BODY_LINES[1].strip(), sent)
            stream.write(BODY_LINES[1])
            self.assertEqual(raw.getvalue(), sent, "끝줄이 오기 전의 뒤 줄은 버린다")
            stream.write(END)
            stream.write("블록 뒤 줄\n")
            self.assertTrue(raw.getvalue().endswith("블록 뒤 줄\n"), "끝줄이 오면 다시 보통대로")

    def test_a_value_on_the_next_line_is_masked_together_with_its_name(self):
        raw, stream = self.stream()
        stream.write("앞 줄\n")
        stream.write("password:\n")
        self.assertEqual(raw.getvalue(), "앞 줄\n", "이름만 있는 줄은 값이 다음 줄에 올지 몰라 한 줄 쥔다")
        stream.write("   hunter2hunter2hunter2\n")
        out = raw.getvalue()
        self.assertNotIn("hunter2hunter2hunter2", out)
        raw, stream = self.stream()
        stream.write("토큰:\n")                                           # 한글 이름은 쥐지 않는다
        self.assertEqual(raw.getvalue(), "토큰:\n")
        raw, stream = self.stream()
        stream.write("다음 단계:\n")
        self.assertEqual(raw.getvalue(), "다음 단계:\n", "비밀 이름이 없는 줄은 바로 나간다")
        raw, stream = self.stream()
        stream.write("api_key =\n")
        stream.finish()                                                   # 값이 끝내 안 오면 종료 때 쥔 줄이 나간다
        self.assertEqual(raw.getvalue(), "api_key =\n")
        raw, stream = self.stream()
        stream.write("앞 줄\n")
        stream.write("Authorization: Bearer\n")                          # 스킴만 있고 값이 다음 줄인 접힌 헤더도 쥔다
        self.assertEqual(raw.getvalue(), "앞 줄\n")
        stream.write("    abcdefghijklmnop0123456789XYZ\n")
        self.assertNotIn("abcdefghijklmnop0123456789XYZ", raw.getvalue())

    def test_a_piece_that_grows_without_a_newline_is_sent_in_parts_so_memory_stays_bounded(self):
        with mock.patch.object(boundary, "PENDING_LIMIT", 50), mock.patch.object(boundary, "PENDING_HARD_LIMIT", 200):
            raw, stream = self.stream()
            stream.write("낱말 " * 40)
            self.assertTrue(raw.getvalue(), "상한을 넘으면 마지막 공백 앞까지 내보낸다")
            self.assertLessEqual(len(stream._pending), 50)
            raw, stream = self.stream()
            stream.write("가" * 150)
            self.assertEqual(raw.getvalue(), "", "공백이 없으면 하드 상한까지는 쥔다")
            stream.write("가" * 100)
            self.assertTrue(raw.getvalue(), "하드 상한을 넘으면 통째로 내보낸다")

    def test_only_text_can_be_written(self):
        _raw, stream = self.stream()
        with self.assertRaises(TypeError):
            stream.write(b"bytes")
        self.assertEqual(stream.write(""), 0)
        self.assertEqual(stream.write("가나"), 2)

    def test_many_threads_write_whole_lines_and_none_of_them_leaks(self):
        raw, stream = self.stream()
        errors = []

        def work(number):
            try:
                for index in range(150):
                    stream.write(f"T{number}-{index} 가나다\n")
                    if index % 25 == 0:
                        stream.write(f"T{number}-비밀 {KEY}\n")
            except Exception as problem:                                  # 스레드 안의 예외도 시험이 본다
                errors.append(type(problem).__name__)

        threads = [threading.Thread(target=work, args=(number,)) for number in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        out = raw.getvalue()
        sec.assert_no_secret(self, KEY, out, "스레드 여섯이 동시에 쓴 글")
        lines = out.splitlines()
        self.assertEqual(len(lines), 6 * 150 + 6 * 6)
        self.assertEqual(sum(1 for line in lines if line.endswith(" 가나다")), 6 * 150, "줄이 서로 섞여 깨지지 않았다")

    def test_odd_characters_never_raise(self):
        raw, stream = self.stream()
        for text in (chr(0) + chr(0xD800) + " 이상한 글\n", "탭\t과\r\n캐리지\r", "가" * 5000 + "\n", chr(0x202E) + "뒤집힌\n"):
            stream.write(text)
        stream.finish()
        self.assertTrue(raw.getvalue())


class InstallTest(Isolated):
    def test_install_wraps_the_streams_and_swaps_the_hooks_and_uninstall_puts_everything_back(self):
        out, err = io.StringIO(), io.StringIO()
        before = (sys.excepthook, threading.excepthook, sys.unraisablehook, logging.getLogRecordFactory())
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            installed = boundary.install()
            self.assertIsInstance(sys.stdout, boundary.RedactingStream)
            self.assertIsInstance(sys.stderr, boundary.RedactingStream)
            self.assertEqual(installed.status(), {"stdout": True, "stderr": True, "hooks": ("sys.excepthook", "threading.excepthook", "sys.unraisablehook"), "logging": True})
            self.assertIs(boundary.active(), installed)
            self.assertIsNot(sys.excepthook, before[0])
            print("출력", KEY, "끝")
            print("오류", KEY, "끝", file=sys.stderr)
            installed.uninstall()
            self.assertIs(sys.stdout, out)
            self.assertIs(sys.stderr, err)
            self.assertIsNone(boundary.active())
        self.assertEqual((sys.excepthook, threading.excepthook, sys.unraisablehook, logging.getLogRecordFactory()), before)
        sec.assert_no_secret(self, KEY, out.getvalue(), "표준 출력")
        sec.assert_no_secret(self, KEY, err.getvalue(), "표준 오류")
        self.assertTrue(out.getvalue().startswith("출력 ") and err.getvalue().startswith("오류 "))

    def test_install_is_idempotent_and_a_context_manager(self):
        first = boundary.install()
        self.assertIs(boundary.install(), first)
        self.assertIs(boundary.install(streams=False, hooks=False, logs=False), first, "이미 깔려 있으면 그 상태를 그대로 돌려준다")
        first.uninstall()
        first.uninstall()                                                   # 여러 번 불러도 같다
        self.assertIsNone(boundary.active())
        with boundary.install() as installed:
            self.assertIs(boundary.active(), installed)
        self.assertIsNone(boundary.active())

    def test_each_part_can_be_left_out(self):
        original = (sys.stdout, sys.stderr, sys.excepthook)
        with boundary.install(streams=False, hooks=True, logs=False) as installed:
            self.assertEqual((sys.stdout, sys.stderr), original[:2])
            self.assertEqual(installed.status(), {"stdout": False, "stderr": False, "hooks": ("sys.excepthook", "threading.excepthook", "sys.unraisablehook"), "logging": False})
        with boundary.install(streams=True, hooks=False, logs=False) as installed:
            self.assertIs(sys.excepthook, original[2])
            self.assertEqual(installed.hooks, ())
        self.assertEqual((sys.stdout, sys.stderr, sys.excepthook), original)

    def test_a_missing_standard_stream_is_left_alone_and_an_already_wrapped_one_is_not_wrapped_twice(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            installed = boundary.install()
            self.assertIsNone(installed.stdout)
            self.assertIsNone(installed.stderr)
            self.assertIsNone(sys.stdout)
            self.assertFalse(boundary.report_exception(RuntimeError, RuntimeError("x"), None), "표준 오류가 없으면 남길 곳이 없다")
            installed.uninstall()
        wrapper = boundary.RedactingStream(io.StringIO())
        with mock.patch.object(sys, "stdout", wrapper):
            installed = boundary.install()
            self.assertIsNone(installed.stdout)
            self.assertIs(sys.stdout, wrapper)
            installed.uninstall()
            self.assertIs(sys.stdout, wrapper)

    def test_uninstall_sends_the_text_it_was_holding_and_leaves_a_stream_somebody_else_replaced(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            installed = boundary.install()
            sys.stderr.write("password=hunter2hunter2")                     # 줄바꿈 없이 쥐고 있는 조각
            self.assertEqual(err.getvalue(), "")
            installed.uninstall()
        self.assertTrue(err.getvalue().startswith("password="))
        self.assertNotIn("hunter2hunter2", err.getvalue())
        other = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            installed = boundary.install()
            sys.stderr = other                                              # 누가 중간에 바꿔 놓았다 — 되돌릴 때 남의 것을 덮어쓰지 않는다
            installed.uninstall()
            self.assertIs(sys.stderr, other)

    def test_the_exit_handler_is_registered_while_installed_and_removed_on_uninstall(self):
        with mock.patch.object(boundary.atexit, "register") as register, mock.patch.object(boundary.atexit, "unregister") as unregister:
            installed = boundary.install()
            register.assert_called_once_with(installed._finish_streams)    # 종료할 때 쥐고 있던 조각을 가려 내보내는 처리기
            unregister.assert_not_called()
            installed.uninstall()
            unregister.assert_called_once_with(installed._finish_streams)


class HookTest(Isolated):
    def capture(self):
        err = io.StringIO()
        stack = contextlib.ExitStack()
        stack.enter_context(contextlib.redirect_stderr(err))
        stack.enter_context(boundary.install())
        self.addCleanup(stack.close)
        return err

    def test_the_excepthook_writes_a_masked_traceback(self):
        err = self.capture()
        try:
            raise RuntimeError("실패 " + KEY)
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        out = err.getvalue()
        sec.assert_no_secret(self, KEY, out, "처리하지 못한 예외의 추적")
        self.assertIn("Traceback", out)
        self.assertIn("RuntimeError", out)
        self.assertIn("실패 ", out)

    def test_a_chained_exception_is_masked_too(self):
        err = self.capture()
        try:
            try:
                raise ValueError("원인 " + KEY)
            except ValueError as cause:
                raise RuntimeError("결과 " + KEY) from cause
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        sec.assert_no_secret(self, KEY, err.getvalue(), "연쇄 예외의 추적")
        self.assertIn("ValueError", err.getvalue())

    def test_the_thread_hook_names_the_thread_and_masks_the_error(self):
        err = self.capture()

        def work():
            raise RuntimeError("스레드 " + KEY)

        thread = threading.Thread(target=work, name="작업-1")
        thread.start()
        thread.join()
        out = err.getvalue()
        sec.assert_no_secret(self, KEY, out, "스레드 안의 예외")
        self.assertIn("작업-1", out)
        self.assertIn("RuntimeError", out)
        before = err.getvalue()
        quiet = threading.Thread(target=lambda: sys.exit(0))              # 스레드의 SystemExit 는 기본 훅처럼 조용히 넘긴다
        quiet.start()
        quiet.join()
        self.assertEqual(err.getvalue(), before)

    def test_the_unraisable_hook_masks_the_object_and_the_error(self):
        err = self.capture()
        fake = types.SimpleNamespace(exc_type=RuntimeError, exc_value=RuntimeError("소멸 " + KEY), exc_traceback=None, err_msg="Exception ignored in", object=("값", KEY))
        sys.unraisablehook(fake)
        sec.assert_no_secret(self, KEY, err.getvalue(), "무시된 예외")
        self.assertIn("Exception ignored in", err.getvalue())

        class Boom:
            def __del__(self):
                raise RuntimeError("진짜 소멸 " + KEY)

        thing = Boom()
        del thing                                                           # 진짜 `__del__` 오류도 훅을 지난다
        sec.assert_no_secret(self, KEY, err.getvalue(), "진짜 소멸 오류")
        self.assertIn("진짜 소멸", err.getvalue())

    def test_warnings_go_through_the_wrapped_standard_error(self):
        err = self.capture()
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn("경고 " + KEY)
        sec.assert_no_secret(self, KEY, err.getvalue(), "경고")
        self.assertIn("경고 ", err.getvalue())


class LoggingTest(Isolated):
    def setUp(self):
        super().setUp()
        self.stream = io.StringIO()
        self.logger = logging.getLogger("pcsec1.boundary.test")
        handler = logging.StreamHandler(self.stream)
        self.logger.addHandler(handler)
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        self.addCleanup(self.logger.removeHandler, handler)

    def test_message_arguments_and_traceback_are_masked_when_the_record_is_made(self):
        with boundary.install():
            self.logger.warning("키 %s 와 %r", KEY, {"값": KEY})
            try:
                raise RuntimeError("예외 " + KEY)
            except RuntimeError:
                self.logger.exception("실패 " + KEY)
            self.logger.info("%d%% 끝", 5)
            self.logger.error("글자 퍼센트 %s", "100%")
        out = self.stream.getvalue()
        sec.assert_no_secret(self, KEY, out, "로그 출력")
        self.assertIn("RuntimeError", out)
        self.assertIn("5% 끝", out, "인자를 채운 평범한 글은 그대로다")
        self.assertIn("글자 퍼센트 100%", out)

    def test_the_last_resort_handler_prints_through_the_wrapped_standard_error(self):
        if logging.getLogger().handlers:
            self.skipTest("루트 로거에 핸들러가 있어 마지막 수단(lastResort)을 쓰지 않는다")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), boundary.install():
            logging.getLogger("pcsec1.boundary.last").warning("마지막 수단 %s", KEY)
        sec.assert_no_secret(self, KEY, err.getvalue(), "lastResort 출력")
        self.assertIn("마지막 수단", err.getvalue())

    def test_the_filters_and_the_factory_are_removed_on_uninstall(self):
        factory = logging.getLogRecordFactory()
        filters = (list(logging.getLogger().filters), list(logging.lastResort.filters))
        installed = boundary.install()
        self.assertIsNot(logging.getLogRecordFactory(), factory)
        self.assertEqual(len(logging.getLogger().filters), len(filters[0]) + 1)
        self.assertEqual(len(logging.lastResort.filters), len(filters[1]) + 1)
        installed.uninstall()
        self.assertIs(logging.getLogRecordFactory(), factory)
        self.assertEqual((list(logging.getLogger().filters), list(logging.lastResort.filters)), filters)

    def test_a_broken_message_does_not_break_logging(self):
        with boundary.install():
            self.logger.warning("인자가 모자란 %s %s", "하나")
        self.assertIn("로그 문장을 만들 수 없음", self.stream.getvalue())


class QtHandlerTest(Isolated):
    class FakeQtCore:
        def __init__(self):
            self.handler = None
            self.installs = []

        def qInstallMessageHandler(self, handler):
            previous, self.handler = self.handler, handler
            self.installs.append(handler)
            return previous

    def test_the_qt_handler_masks_the_message_and_uninstall_restores_the_previous_handler(self):
        fake = self.FakeQtCore()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            handle = boundary.install_qt_message_handler(fake)
            self.assertIsNotNone(fake.handler)
            fake.handler(1, None, "qt.qpa.fonts: 키 " + KEY)
            handle.uninstall()
            handle.uninstall()                                              # 여러 번 불러도 같다
        sec.assert_no_secret(self, KEY, err.getvalue(), "Qt 메시지")
        self.assertIn("qt.qpa.fonts", err.getvalue())
        self.assertEqual(fake.installs[-1], None, "되돌리면 Qt 의 처음 핸들러(None)가 돌아온다")
        self.assertFalse(handle.active)

    def test_the_qt_handler_survives_a_message_it_cannot_mask(self):
        fake = self.FakeQtCore()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            boundary.install_qt_message_handler(fake)
            with mock.patch.object(boundary, "mask_block", side_effect=RuntimeError("가릴 수 없다")):
                fake.handler(1, None, "본문 " + KEY)
        sec.assert_no_secret(self, KEY, err.getvalue(), "가리기가 실패한 Qt 메시지")
        self.assertIn("Qt 메시지를 가릴 수 없어 생략", err.getvalue())

    def test_importing_the_boundary_does_not_need_qt(self):
        self.assertNotIn("PySide6", [name for name in ("PySide6",) if name in boundary.__dict__])
        source = (ROOT / "src" / "chanceblog_desktop" / "security" / "boundary.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        top_imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = {alias.name.split(".")[0] for node in top_imports for alias in node.names} | {(node.module or "").split(".")[0] for node in top_imports if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("PySide6", names, "Qt 는 `install_qt_message_handler` 안에서만 불러온다")


class MaskHelpersTest(unittest.TestCase):
    def test_the_cli_uses_the_same_functions(self):
        self.assertIs(cli.mask_block, boundary.mask_block)
        self.assertIs(cli._mask_deep, boundary.mask_deep)

    def test_mask_deep_masks_every_text_and_keeps_the_rest(self):
        value = {"a": KEY, "b": [KEY, ("x", KEY)], "c": 3, "d": None, "e": True, "f": {"g": KEY}}
        masked = boundary.mask_deep(value)
        sec.assert_no_secret(self, KEY, repr(masked), "가린 JSON 값")
        self.assertEqual((masked["c"], masked["d"], masked["e"]), (3, None, True))
        self.assertIsInstance(masked["b"][1], list)

    def test_mask_block_masks_a_key_block_and_the_value_on_the_next_line(self):
        out = boundary.mask_block("앞\n" + BEGIN + BODY_LINES[0] + END + "뒤\npassword:\n   hunter2hunter2hunter2\n")
        self.assertNotIn(BODY_LINES[0].strip(), out)
        self.assertNotIn("hunter2hunter2hunter2", out)

    def test_mask_block_handles_a_text_longer_than_the_mask_limit_without_cutting_a_block(self):
        filler = "가나다라 " * 60000
        text = filler + "\n" + BEGIN + BODY_LINES[0] * 3 + END + "\n" + filler
        out = boundary.mask_block(text)
        self.assertNotIn(BODY_LINES[0].strip(), out)
        self.assertGreater(len(out), 100000)

    def test_a_traceback_text_can_always_be_made(self):
        text = boundary.format_exception_masked(RuntimeError, RuntimeError("이름 " + KEY), None)
        sec.assert_no_secret(self, KEY, text, "추적 글")
        with mock.patch.object(boundary.traceback, "format_exception", side_effect=RuntimeError("추적 실패")):
            self.assertEqual(boundary.format_exception_masked(ValueError, ValueError("x"), None).strip(), "ValueError")


class EntryPointTest(Isolated):
    SRC = str(ROOT / "src")

    def run_driver(self, body, canary, *, extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "driver.py"
            script.write_text(textwrap.dedent(body), encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if key not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA", "CHANCEBLOG_KEYSTORE", "CHANCEBLOG_KEYSTORE_DIR")}
            env.update({"PCSEC1_CANARY": canary, "PCSEC1_SRC": self.SRC, "LOCALAPPDATA": str(Path(tmp) / "local"), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
            env.update(extra_env or {})
            done = subprocess.run([sys.executable, "-X", "utf8", str(script)], capture_output=True, env=env, cwd=tmp, timeout=180)
        return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")

    DRIVER_REAL = """
        import os, runpy, sys
        sys.path.insert(0, os.environ["PCSEC1_SRC"])
        from unittest import mock
        from chanceblog_desktop.service import cli
        canary = os.environ["PCSEC1_CANARY"]

        def boom(*args, **kwargs):
            raise RuntimeError("치명적 오류 Authorization: Token " + canary + " 와 키 " + canary)

        with mock.patch.object(cli, "make_context", boom):
            sys.argv = ["chanceblog_desktop", "list", "--debug"]
            runpy.run_module("chanceblog_desktop", run_name="__main__", alter_sys=True)
    """
    DRIVER_CONTROL = """
        import os, sys
        sys.path.insert(0, os.environ["PCSEC1_SRC"])
        from unittest import mock
        from chanceblog_desktop.service import cli
        canary = os.environ["PCSEC1_CANARY"]

        def boom(*args, **kwargs):
            raise RuntimeError("치명적 오류 Authorization: Token " + canary + " 와 키 " + canary)

        with mock.patch.object(cli, "make_context", boom):
            cli.main(["list", "--debug"])
    """

    def test_the_real_entry_point_prints_a_masked_traceback_for_an_uncaught_debug_error(self):
        code, out, err = self.run_driver(self.DRIVER_REAL, KEY)
        self.assertEqual(code, 1, "처리하지 못한 예외의 종료 코드는 1 이다")
        sec.assert_no_secret(self, KEY, out + err, "진짜 프로세스의 표준 출력·오류")
        self.assertIn("RuntimeError", err)
        self.assertIn("치명적 오류", err)
        self.assertIn("Traceback", err)

    def test_the_control_run_without_the_boundary_does_leak_so_the_check_above_can_fail(self):
        code, out, err = self.run_driver(self.DRIVER_CONTROL, KEY)
        self.assertEqual(code, 1)
        self.assertIsNotNone(sec.find_leak(KEY, out + err), "대조 실험(경계 없이 같은 예외)에서 비밀이 나와야 위 시험이 실제로 빨개질 수 있다")

    def test_the_real_entry_point_still_works_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = str(Path(tmp) / "data")
            for argv in (["--help"], ["list", "--data-dir", data], ["--json", "list", "--data-dir", data], ["keys", "purposes", "--data-dir", data]):
                with self.subTest(argv=argv):
                    done = subprocess.run([sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", *argv], capture_output=True, cwd=tmp, timeout=180,
                                          env={**{k: v for k, v in os.environ.items() if k not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA")}, "PYTHONPATH": self.SRC,
                                               "LOCALAPPDATA": str(Path(tmp) / "local"), "PYTHONIOENCODING": "utf-8"})
                    self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace")[:300])
                    self.assertTrue(done.stdout.decode("utf-8", "replace").strip())

    def test_the_main_module_installs_the_boundary_before_it_dispatches_anything(self):
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "__main__.py").read_text(encoding="utf-8"))
        guard = next(node for node in tree.body if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test))
        calls = [ast.unparse(node.value) for node in guard.body if isinstance(node, ast.Expr)]
        self.assertEqual(calls[:1], ["boundary.install()"], "진입점의 첫 일은 경계를 까는 것이다")
        installed_at = next(node.lineno for node in guard.body if isinstance(node, ast.Expr) and ast.unparse(node.value) == "boundary.install()")
        other_imports = [node.lineno for node in ast.walk(guard) if isinstance(node, ast.ImportFrom) and node.module and "boundary" not in ast.unparse(node) and node.lineno < installed_at]
        self.assertEqual(other_imports, [], "경계를 깔기 전에 다른 모듈을 불러오지 않는다(불러오다 찍는 글도 걸러지게)")
        source = ast.unparse(guard)
        self.assertIn("install_qt_message_handler", source, "화면 진입은 Qt 메시지 핸들러까지 깐다")
        self.assertIn("has_pyside6", source, "PySide6 가 없으면 Qt 핸들러를 깔려다 실패하지 않고 launcher 의 쉬운 안내로 간다")

    def test_a_test_stream_given_to_the_cli_is_never_wrapped_and_debug_still_raises(self):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp)
            code = cli.main(["list"], out=out, err=err, ctx=ctx, env={})
            self.assertEqual(code, 0)
            self.assertIsNone(boundary.active(), "`cli.main` 은 경계를 깔지 않는다 — 진입점이 한다")

            class Boom(MemoryStore):
                def exists(self, ref):
                    raise RuntimeError("보관소 오류 " + KEY)

            cn.add_entry(ctx, "ai_assist", name="기본", fields={"key": sec.make_canary("ENTRY_KEY")}, provider="gemini", keystore=MemoryStore())
            ctx.keystore = Boom()
            with self.assertRaises(RuntimeError):
                cli.main(["keys", "list", "--debug"], out=io.StringIO(), err=io.StringIO(), ctx=ctx, env={})
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(cli.main(["keys", "list"], out=out, err=err, ctx=ctx, env={}), 1)
            sec.assert_no_secret(self, KEY, out.getvalue() + err.getvalue(), "예상 못 한 예외의 명령줄 출력")


class GuiEntryTest(Isolated):
    """화면(GUI) 진입점이 둘이다 — 소스 실행(`python -m chanceblog_desktop gui` → `__main__.py`)과 묶음 실행 파일(PCKIT 의 `gui_entry` 가 `__main__` 을 거치지 않고 `ui.launcher.main` 을 바로 부른다).
    둘 다 공통 경계가 깔려야 한다(PCKIT 독립 검증 D2) — 경계는 `__main__` 맨 앞에서도, `launcher.main` 맨 앞에서도 깔고(멱등), 이 시험이 두 길을 진짜 프로세스로 못박는다.
    PySide6 가 없는 환경은 `sys.modules['PySide6'] = None` 으로 흉내 낸다(이 시험은 PySide6 가 있든 없든 돈다)."""

    SRC = str(ROOT / "src")
    NO_PYSIDE6 = "import sys; sys.modules['PySide6'] = None; sys.modules['shiboken6'] = None" + chr(10)
    # 소스 실행: `python -m chanceblog_desktop gui` 와 같은 길(runpy 로 `__main__` 을 돌린다)
    SOURCE_RUN = NO_PYSIDE6 + """
import os, runpy
sys.path.insert(0, os.environ["PCSEC1_SRC"])
sys.argv = ["chanceblog_desktop", "gui"]
try:
    runpy.run_module("chanceblog_desktop", run_name="__main__", alter_sys=True)
except SystemExit as stop:
    code = stop.code
from chanceblog_desktop.security import boundary
print("BOUNDARY", boundary.active() is not None, type(sys.stdout).__name__, type(sys.stderr).__name__, code)
print("Authorization: Bearer " + os.environ["PCSEC1_CANARY"])
"""
    # 묶음 실행 파일: `__main__` 을 거치지 않고 화면 시작 함수를 바로 부른다(PCKIT 의 `gui_entry.start_gui` 와 같은 모양)
    BUNDLED_RUN = NO_PYSIDE6 + """
import os
sys.path.insert(0, os.environ["PCSEC1_SRC"])
from chanceblog_desktop.ui import launcher
code = launcher.main([])
from chanceblog_desktop.security import boundary
print("BOUNDARY", boundary.active() is not None, type(sys.stdout).__name__, type(sys.stderr).__name__, code)
print("Authorization: Bearer " + os.environ["PCSEC1_CANARY"])
"""

    def run_child(self, body):
        env = {key: value for key, value in os.environ.items() if key not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA", "CHANCEBLOG_KEYSTORE", "CHANCEBLOG_KEYSTORE_DIR", "QT_QPA_PLATFORM")}
        env.update({"PCSEC1_CANARY": KEY, "PCSEC1_SRC": self.SRC, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        with tempfile.TemporaryDirectory() as tmp:
            env["LOCALAPPDATA"] = str(Path(tmp) / "local")
            done = subprocess.run([sys.executable, "-X", "utf8", "-c", body], capture_output=True, env=env, cwd=tmp, timeout=180)
        return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")

    def assert_boundary_is_on(self, out, err, label):
        self.assertIn("BOUNDARY True RedactingStream RedactingStream 1", out, f"{label}: 진입점을 거친 뒤 경계가 깔려 있고 표준 출력·오류가 가리는 래퍼다 — {out[-200:]!r}")
        sec.assert_no_secret(self, KEY, out + err, f"{label}: 진짜 프로세스의 표준 출력·오류")
        self.assertIn("[가림", out, f"{label}: 진입점 뒤에 찍은 비밀 모양이 가려진 자리 표지로 나왔다")

    def test_the_source_run_entry_installs_the_boundary(self):
        code, out, err = self.run_child(self.SOURCE_RUN)
        self.assertEqual(code, 0, err[-300:])
        self.assert_boundary_is_on(out, err, "소스 실행(__main__)")

    def test_the_bundled_entry_that_calls_the_launcher_directly_installs_the_boundary_too(self):
        code, out, err = self.run_child(self.BUNDLED_RUN)
        self.assertEqual(code, 0, err[-300:])
        self.assert_boundary_is_on(out, err, "묶음 실행 파일 진입점(launcher.main 직접 호출)")

    def test_a_process_that_never_goes_through_the_launcher_has_no_boundary(self):
        """대조 — 경계를 까는 곳이 위 둘뿐이라는 것: 아무 진입점도 거치지 않은 프로세스는 래퍼가 없다."""
        code, out, err = self.run_child("; ".join(["import sys", "sys.path.insert(0, " + repr(self.SRC) + ")", "from chanceblog_desktop.security import boundary", "print('BOUNDARY', boundary.active() is not None, type(sys.stdout).__name__)"]))
        self.assertEqual((code, out.strip()), (0, "BOUNDARY False TextIOWrapper"), err[-300:])

    # 창 없는(windowed) 실행 파일 — 표준 출력·오류가 없다(None). 묶음 진입점은 빈 쓰개를 달 수도(PCKIT `prepare_streams`) 그대로 둘 수도 있다 — 어느 쪽이든 죽지 않고 경계는 깔린다.
    WINDOWED_RUN = NO_PYSIDE6 + """
import os
sys.path.insert(0, os.environ["PCSEC1_SRC"])


class NullWriter:
    encoding = "utf-8"

    def write(self, text):
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


mode = os.environ["PCSEC1_MODE"]
sys.stdout = sys.stderr = None if mode == "none" else NullWriter()
from chanceblog_desktop.ui import launcher
from chanceblog_desktop.security import boundary
code = launcher.main([])
installed = boundary.active()
shown = (installed is not None, type(installed.stdout).__name__, type(installed.stderr).__name__, len(installed.hooks), code)
sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
print("WINDOWED", mode, *shown)
"""

    def test_a_windowed_bundle_without_console_streams_starts_with_the_boundary_and_does_not_crash(self):
        for mode, stream_type in (("none", "NoneType"), ("null_writer", "RedactingStream")):
            with self.subTest(streams=mode):
                with mock.patch.dict(os.environ, {"PCSEC1_MODE": mode}):
                    code, out, err = self.run_child(self.WINDOWED_RUN)
                self.assertEqual(code, 0, err[-300:])
                self.assertIn(f"WINDOWED {mode} True {stream_type} {stream_type} 3 1", out, "스트림이 없으면 감싸지 않고(훅 셋만), 빈 쓰개가 있으면 그것을 감싼다 — 어느 쪽이든 경계는 깔리고 안내 한 줄 뒤 종료 코드 1")

    def test_the_launcher_installs_the_boundary_before_it_reads_anything(self):
        calls = []

        def stop():
            calls.append("parser")
            raise SystemExit(0)

        from chanceblog_desktop.ui import launcher
        with mock.patch.object(boundary, "install", side_effect=lambda **kwargs: calls.append("install")), mock.patch.object(launcher, "has_pyside6", side_effect=lambda: calls.append("pyside6-check")), \
                mock.patch.object(launcher, "build_parser", side_effect=stop):
            with self.assertRaises(SystemExit):
                launcher.main([])
        self.assertEqual(calls, ["install", "parser"], "경계가 인자 읽기보다 먼저다 — 그리고 그 전에 PySide6 확인(버전 검사보다 뒤여야 하는 일)을 하지 않는다")

    def test_the_launcher_source_installs_the_boundary_first_and_the_qt_handler_only_after_pyside6_is_confirmed(self):
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "launcher.py").read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        body = [node for node in main.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        shown = [ast.unparse(node) for node in body]
        self.assertEqual(shown[0], "from ..security import boundary")
        self.assertEqual(shown[1], "boundary.install()", "화면 시작 함수의 첫 일은 경계를 까는 것이다(인자·버전 오류의 글도 가려져 나가도록)")
        check = next(index for index, text in enumerate(shown) if text.startswith("if not has_pyside6():"))
        qt = [index for index, text in enumerate(shown) if text == "boundary.install_gui()"]
        opened = next(index for index, text in enumerate(shown) if text.startswith("from .qt.app import"))
        self.assertEqual(len(qt), 1)
        self.assertTrue(1 < check < qt[0] < opened, "Qt 메시지 핸들러는 PySide6 확인 뒤·화면을 만들기 전에 건다 — 버전 검사·PySide6 확인의 순서는 그대로")

    def test_the_qt_handler_goes_in_after_pyside6_is_confirmed_and_before_the_screen_is_made(self):
        from chanceblog_desktop.ui import launcher
        fake = QtHandlerTest.FakeQtCore()
        package = types.ModuleType("PySide6")
        package.QtCore = fake
        app = types.ModuleType("chanceblog_desktop.ui.qt.app")
        seen = []
        app.run = lambda provider, argv=None: (seen.append(len(fake.installs)), 0)[1]
        with mock.patch.object(launcher, "has_pyside6", return_value=True), mock.patch.dict(sys.modules, {"PySide6": package, "chanceblog_desktop.ui.qt.app": app}):
            self.assertEqual(launcher.main(["--sample"]), 0)
        self.assertEqual(seen, [1], "화면을 만들 때(run)는 Qt 메시지 핸들러가 이미 한 번 걸려 있다")
        self.assertIsNotNone(boundary.active())

    def test_without_pyside6_the_launcher_ends_with_the_guidance_and_installs_no_qt_handler_but_the_boundary_stays(self):
        from chanceblog_desktop.ui import launcher
        fake = QtHandlerTest.FakeQtCore()
        package = types.ModuleType("PySide6")
        package.QtCore = fake
        out = io.StringIO()
        with mock.patch.object(launcher, "has_pyside6", return_value=False), mock.patch.dict(sys.modules, {"PySide6": package}):
            self.assertEqual(launcher.main([], out=out), 1)
        self.assertEqual(fake.installs, [], "PySide6 가 없다고 판단하면 Qt 쪽은 건드리지 않는다")
        self.assertIsNotNone(boundary.active(), "그래도 표준 출력·오류·훅의 경계는 맨 앞에서 깔렸다")

    def test_a_usage_error_message_goes_out_through_the_boundary(self):
        """`launcher.main` 이 인자를 읽기 전에 경계를 깔았으므로, 사용법 오류 글(고정 한국어 문장)도 래퍼를 지나 나간다 — 경계가 깔렸는지는 표준 오류가 래퍼인지로 본다."""
        from chanceblog_desktop.ui import launcher
        raw = io.StringIO()
        with contextlib.redirect_stderr(raw):
            with self.assertRaises(SystemExit):
                launcher.main(["--" + "nope"])
            self.assertIsInstance(sys.stderr, boundary.RedactingStream, "인자 읽기 전에 표준 오류가 가리는 래퍼로 바뀌어 있다")
            boundary.active().uninstall()                                   # 쥐고 있던 글을 내보낸다
        self.assertIn(launcher.USAGE_LINE, raw.getvalue())

    def test_installing_twice_is_safe_and_the_qt_handler_is_installed_once_per_qtcore(self):
        fake = QtHandlerTest.FakeQtCore()
        first = boundary.install_gui(qt=False)
        self.assertIs(boundary.install(), first, "install() 은 멱등이다")
        self.assertIs(boundary.install_gui(qt=False), first, "화면 진입점이 둘 다 불러도 한 번만 깔린다")
        handle = boundary.install_qt_message_handler(fake)
        again = boundary.install_qt_message_handler(fake)
        self.assertIs(again, handle, "같은 QtCore 에는 한 번만 깐다")
        self.assertEqual(len(fake.installs), 1)
        other = QtHandlerTest.FakeQtCore()
        self.assertIsNot(boundary.install_qt_message_handler(other), handle, "다른 QtCore 는 따로 깐다")
        handle.uninstall()
        self.assertEqual(fake.installs[-1], None, "되돌리면 처음 핸들러로 돌아온다")
        reinstalled = boundary.install_qt_message_handler(fake)
        self.assertIsNot(reinstalled, handle, "되돌린 뒤에는 새로 깐다")
        reinstalled.uninstall()
        boundary.install_qt_message_handler(other).uninstall()
        solo = QtHandlerTest.FakeQtCore()
        stale = boundary.install_qt_message_handler(solo)
        stale.active = False                                                # 되돌려졌다고 표시된 핸들(되돌리기를 거치지 않고 표시만 바뀐 경우)
        fresh = boundary.install_qt_message_handler(solo)
        self.assertIsNot(fresh, stale, "되돌려진 핸들은 깔려 있는 것으로 치지 않는다 — 새로 깐다")
        self.assertEqual(len(solo.installs), 2)
        fresh.uninstall()

    def test_install_gui_without_pyside6_still_installs_the_boundary_and_uninstall_restores_the_qt_handler(self):
        with mock.patch.object(boundary, "install_qt_message_handler", side_effect=ImportError("PySide6")):
            installed = boundary.install_gui(qt=True)
        self.assertIs(boundary.active(), installed, "PySide6 가 없어도 경계는 깔린다")
        installed.uninstall()
        self.assertIsNone(boundary.active())
        fake = QtHandlerTest.FakeQtCore()
        with mock.patch.object(boundary, "install_qt_message_handler", side_effect=lambda: boundary.QtHandle(fake, fake.qInstallMessageHandler(boundary._qt_handler))):
            installed = boundary.install_gui(qt=True)
        self.assertEqual(len(installed._qt), 1)
        installed.uninstall()
        self.assertEqual(fake.installs[-1], None, "경계를 되돌리면 Qt 메시지 핸들러도 되돌아간다")


class SecretSupportTest(unittest.TestCase):
    """시험 도우미 자신 — 비밀의 흔한 모양을 찾고, 실패 메시지에는 값을 싣지 않는다."""

    def test_every_shape_a_secret_takes_in_an_output_is_found(self):
        import base64
        import urllib.parse
        raw = KEY.encode("utf-8")
        shapes = {"원문": KEY, "퍼센트": urllib.parse.quote(KEY, safe=""), "16진수": raw.hex(), "base64": base64.b64encode(raw).decode(), "base64url": base64.urlsafe_b64encode(raw).decode().rstrip("="),
                  "조각": "앞 " + sec.unique_part(KEY)[3:15] + " 뒤"}
        for label, text in shapes.items():
            with self.subTest(shape=label):
                self.assertIsNotNone(sec.find_leak(KEY, "출력 " + text + " 끝"), f"{label}: 못 찾았다")
        self.assertIsNone(sec.find_leak(KEY, "평범한 출력입니다 — 비밀이 없다. [가림: Google API 키]"))
        self.assertIsNone(sec.find_leak(KEY, ""))
        self.assertEqual(sec.leak_count([KEY, sec.make_canary("OTHER")], "x " + KEY), 1)

    def test_the_failure_message_never_contains_the_secret_or_the_output(self):
        output = "앞 글 " + KEY + " 뒤 글 " + "나머지 출력 " * 5
        message = sec.failure_message(KEY, output, what="확인 중인 곳")
        self.assertIsNotNone(message)
        self.assertIn("확인 중인 곳", message)
        self.assertIsNone(sec.find_leak(KEY, message), "실패 메시지에 비밀이 없다")
        self.assertNotIn("나머지 출력", message)
        self.assertNotIn("앞 글", message)
        self.assertIsNone(sec.failure_message(KEY, "비밀 없는 출력"), "새지 않았으면 메시지가 없다")
        many = []

        class Recorder:
            def fail(self, text):
                many.append(text)

        sec.assert_masked_only(Recorder(), [sec.make_canary("A1"), KEY, sec.make_canary("A2")], "x " + KEY + " " + sec.make_canary("A2"), what="여럿")
        self.assertEqual(len(many), 2)
        self.assertIn("2번", many[0])
        self.assertIn("3번", many[1])
        for text in many:
            self.assertIsNone(sec.find_leak(KEY, text))

    def test_canaries_are_runtime_built_and_deterministic(self):
        self.assertEqual(sec.make_canary("X"), sec.make_canary("X"))
        self.assertNotEqual(sec.make_canary("X"), sec.make_canary("Y"))
        self.assertTrue(sec.make_canary("X").startswith("CANARY_X_"))

    def test_the_cleanup_helper_for_in_process_launcher_tests_removes_the_boundary(self):
        """`launcher.main` 을 같은 프로세스에서 부르는 시험(`test_ui_launcher`·`test_ui_c1a_core`)이 `addCleanup(sec.uninstall_boundary)` 로 거는 도우미 — 깔린 경계를 걷고, 안 깔려 있으면 아무 일도 없다."""
        self.addCleanup(Isolated._undo)                                    # 도우미가 고장 나도 다른 시험에 경계가 남지 않게
        sec.uninstall_boundary()
        self.assertIsNone(boundary.active())
        installed = boundary.install(streams=False, hooks=False, logs=False)
        self.assertIs(boundary.active(), installed)
        sec.uninstall_boundary()
        self.assertIsNone(boundary.active(), "도우미가 깔린 경계를 걷어야 한다")


class CutPositionTest(unittest.TestCase):
    def test_a_cut_never_lands_between_a_name_and_its_value(self):
        self.assertEqual(boundary._last_cut("가나 다라 "), len("가나 다라 ") - 1)
        text = "앞 글 " + "password: "
        cut = boundary._last_cut(text)
        self.assertEqual(text[:cut + 1], "앞 글 ", "password: 바로 뒤의 공백이 아니라 그 앞의 공백에서 자른다")
        self.assertEqual(boundary._last_cut("password: "), -1)
        self.assertEqual(boundary._last_cut("Authorization: Bearer "), -1)
        self.assertEqual(boundary._last_cut("공백없음"), -1)

    def test_a_long_piece_is_not_split_between_a_name_and_its_value(self):
        with mock.patch.object(boundary, "PENDING_LIMIT", 60):
            raw = io.StringIO()
            stream = boundary.RedactingStream(raw)
            stream.write("나 " * 30 + "password: ")                                     # 70자 — 상한(60)을 넘어야 조각을 나누는 길(`_spill`)을 탄다(상한 이하면 시험이 아무것도 안 본다)
            self.assertTrue(raw.getvalue(), "상한을 넘어 앞 조각이 내보내졌다(그렇지 않으면 이 시험이 나누는 길을 타지 않은 것이다)")
            self.assertFalse(raw.getvalue().rstrip().endswith("password:"), "이름과 값 사이에서 잘라 내보내지 않는다")
            stream.write("hunter2hunter2hunter2\n")
            self.assertNotIn("hunter2hunter2hunter2", raw.getvalue())

    def test_an_explicit_flush_shows_a_prompt_even_when_it_ends_with_a_name(self):
        """명시적 flush 는 '지금 보여 달라' 는 뜻이다 — 입력을 기다리는 질문(`Password: `)이 쥐어져 안 보이면 프로그램이 멈춘 것처럼 보인다."""
        raw = io.StringIO()
        stream = boundary.RedactingStream(raw)
        stream.write("Password: ")
        stream.flush()
        self.assertEqual(raw.getvalue(), "Password: ")
        raw = io.StringIO()
        stream = boundary.RedactingStream(raw)
        stream.write("API key:\n")
        self.assertEqual(raw.getvalue(), "", "flush 없이는 값이 다음 줄에 올지 몰라 한 줄 쥔다")
        stream.flush()
        self.assertEqual(raw.getvalue(), "API key:\n", "flush 를 부르면 쥔 줄도 나간다(질문 다음에 입력을 기다리는 프로그램이 멈추지 않는다)")
        stream.write("hunter2hunter2hunter2\n")                              # flush 뒤에 온 값은 이름과 떨어져 있어 가려지지 않는다 — 한계(문서에 적었다)

    def test_flush_never_releases_an_open_private_key_block(self):
        raw = io.StringIO()
        stream = boundary.RedactingStream(raw)
        stream.write(BEGIN + BODY_LINES[0])
        stream.flush()
        self.assertEqual(raw.getvalue(), "", "끝줄이 와야 통째로 가릴 수 있어 flush 로도 내보내지 않는다")
        stream.write(END)
        self.assertNotIn(BODY_LINES[0].strip(), raw.getvalue())


class ErrorRenderingTest(unittest.TestCase):
    def test_slot_values_are_masked_in_the_message_and_the_action(self):
        shown = AppError("FILE_WRITE_FAILED", {"경로": "열 수 없음 " + KEY}).rendered()
        sec.assert_no_secret(self, KEY, shown.message + "\n" + shown.action, "오류 문구")
        self.assertIn("열 수 없음", shown.message)
        sec.assert_no_secret(self, KEY, str(AppError("FILE_WRITE_FAILED", {"경로": KEY})), "str(오류)")

    def test_the_value_is_masked_before_it_is_cut_to_the_slot_limit(self):
        value = "가" * 150 + KEY + " 끝"                                  # 비밀이 값 상한(160자)에 걸쳐 있다
        shown = AppError("FILE_WRITE_FAILED", {"경로": value}).rendered().message
        sec.assert_no_secret(self, KEY, shown, "상한에 걸친 비밀")
        self.assertFalse(KEY[:8] in shown, "자른 뒤에 가리면 상한에서 잘린 앞 조각(AIza…)이 가려지지 않고 남는다")        # assert_no_secret 은 비밀의 뒷부분만 찾으므로 앞 조각은 따로 본다(값이 든 실패 글을 찍지 않으려고 assertFalse)

    def test_without_the_masking_module_the_value_is_replaced_by_a_fixed_sentence(self):
        with mock.patch.dict(sys.modules, {"chanceblog_desktop.security.mask": None}):
            shown = AppError("FILE_WRITE_FAILED", {"경로": "비밀 메모 " + KEY}).rendered().message
        self.assertIn("(가릴 수 없어 생략)", shown)
        self.assertNotIn("비밀 메모", shown)
        sec.assert_no_secret(self, KEY, shown, "가리기 모듈이 없을 때의 오류 문구")

    def test_odd_values_do_not_break_the_rendering(self):
        for value in (123, None, ("a", KEY), b"bytes", 1.5):
            with self.subTest(value=type(value).__name__):
                shown = AppError("FILE_WRITE_FAILED", {"경로": value}).rendered().message
                sec.assert_no_secret(self, KEY, shown, "이상한 값의 오류 문구")
                self.assertIn("파일을 저장하지 못했습니다", shown)


class DisplayTextTest(unittest.TestCase):
    def test_it_masks_first_then_shortens_and_collapses_whitespace(self):
        from chanceblog_desktop.ui.core.text import display_text
        self.assertEqual(display_text("  가   나\n다  "), "가 나 다")
        self.assertEqual(display_text(None), "")
        text = display_text("가" * 100 + KEY, 110)                        # 비밀이 상한에 걸쳐 있다 — 자르고 나서 가리면 앞부분이 남는다
        sec.assert_no_secret(self, KEY, text, "한도에 걸친 비밀")
        self.assertLessEqual(len(text), 110)
        self.assertTrue(display_text("가" * 500, 50).endswith("…"))


class TopicsDebugTest(unittest.TestCase):
    def test_the_topics_quiet_wrapper_raises_with_debug_and_masks_without_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp)
            with mock.patch.object(cli.topics, "status", side_effect=RuntimeError("주제 엔진 오류 " + KEY)):
                with self.assertRaises(RuntimeError):
                    cli.main(["topics", "status", "--debug"], out=io.StringIO(), err=io.StringIO(), ctx=ctx, env={})
                for flags in ([], ["--verbose"], ["--json"]):
                    out, err = io.StringIO(), io.StringIO()
                    self.assertEqual(cli.main(["topics", "status", *flags], out=out, err=err, ctx=ctx, env={}), 1)
                    sec.assert_no_secret(self, KEY, out.getvalue() + err.getvalue(), "topics 의 예상 못 한 오류 " + " ".join(flags))


class MaskingRunnerTest(unittest.TestCase):
    """시험 실패 출력 위치 — 가린 러너는 실패 글·시험 설명에서 비밀을 가리고, 보통 러너(대조)는 그대로 찍는다."""

    @staticmethod
    def run_leaky(runner_class):
        class Leaky(unittest.TestCase):
            def test_leaks(self):
                self.assertNotIn(KEY, "출력 " + KEY + " 끝")

            def test_sub(self):
                with self.subTest(secret=KEY):
                    self.fail("실패 " + KEY)

        stream = io.StringIO()
        result = runner_class(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Leaky))
        return stream.getvalue(), result

    def test_the_plain_runner_prints_the_secret_so_the_check_can_fail(self):
        out, result = self.run_leaky(unittest.TextTestRunner)
        self.assertEqual(len(result.failures), 2)
        self.assertIsNotNone(sec.find_leak(KEY, out), "대조 — 보통 러너는 실패 글에 비밀을 그대로 찍는다")

    def test_the_masking_runner_hides_it_in_failure_texts_and_descriptions(self):
        out, result = self.run_leaky(sec.MaskingTextTestRunner)
        self.assertEqual(len(result.failures), 2, "시험 결과(실패 개수)는 그대로다")
        sec.assert_no_secret(self, KEY, out, "가린 러너의 출력")
        self.assertIn("test_leaks", out)
        self.assertIn("FAIL", out)

    def test_the_launcher_script_masks_a_real_process_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "test_leak.py").write_text("import os, unittest\nKEY = os.environ['PCSEC1_KEY']\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        self.assertNotIn(KEY, '출력 ' + KEY)\n", encoding="utf-8")
            env = {**os.environ, "PCSEC1_KEY": KEY, "PYTHONIOENCODING": "utf-8"}
            done = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tests" / "run_masked.py"), "discover", "-s", tmp, "-p", "test_leak.py"], capture_output=True, env=env, cwd=tmp, timeout=120)
            plain = subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", tmp, "-p", "test_leak.py"], capture_output=True, env=env, cwd=tmp, timeout=120)
        output = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        self.assertEqual(done.returncode, 1, "실패한 시험이 있으면 종료 코드는 1 이다")
        self.assertIn("FAIL", output)
        sec.assert_no_secret(self, KEY, output, "가린 러너 스크립트의 출력")
        self.assertIsNotNone(sec.find_leak(KEY, plain.stdout.decode("utf-8", "replace") + plain.stderr.decode("utf-8", "replace")), "대조 — 보통 `python -m unittest` 는 비밀을 찍는다")


if __name__ == "__main__":
    unittest.main()
