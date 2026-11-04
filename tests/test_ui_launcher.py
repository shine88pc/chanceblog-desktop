"""화면 실행 진입점(`python -m chanceblog_desktop gui`) 시험 — **PySide6 가 없어도** 명령줄은 그대로 동작하고, 화면을 열려 하면 쉬운 한국어로 안내하고 끝난다.
PySide6 가 없는 환경은 `sys.modules['PySide6'] = None`(불러오기를 막음)으로 흉내 낸 자식 프로세스에서 확인한다 — 이 시험은 PySide6 가 있든 없든 돈다.
"""
import contextlib
import io
import os
import subprocess
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.ui import launcher  # noqa: E402
from chanceblog_desktop.ui.adapters import ServiceHomeProvider  # noqa: E402
from chanceblog_desktop.ui.core.services import FakeHomeProvider  # noqa: E402

SECRET = "AI" + "za" + "SyD4e7Kq9ZmW2xV8bN5tR1cY6uH3jL0pGfA1B"[:35]          # 구글 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)
FIXED_SENTENCE = "사용법 오류: gui 명령의 인자가 올바르지 않습니다(입력한 값은 보이지 않습니다)."


def run_child(code, *args):
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    environment.pop("QT_QPA_PLATFORM", None)
    done = subprocess.run([sys.executable, "-X", "utf8", *args] if not code else [sys.executable, "-X", "utf8", "-c", code, *args], capture_output=True, text=True, encoding="utf-8", env=environment,
                          cwd=str(ROOT), timeout=120, creationflags=0x08000000 if os.name == "nt" else 0)
    return done.returncode, done.stdout, done.stderr


NO_PYSIDE6 = "import sys; sys.modules['PySide6'] = None; sys.modules['shiboken6'] = None\n"


class LauncherTest(unittest.TestCase):
    def test_without_pyside6_the_gui_command_explains_in_easy_korean_and_does_not_crash(self):
        code, out, err = run_child(NO_PYSIDE6 + "from chanceblog_desktop.ui import launcher\nsys.exit(launcher.main([]))")
        self.assertEqual(code, 1)
        self.assertIn("PySide6", out)
        self.assertIn("python -m pip install PySide6", out)
        self.assertIn("화면 없이 쓰는 명령", out)
        self.assertNotIn("Traceback", out + err)
        self.assertEqual(err.strip(), "")

    def test_the_command_line_keeps_working_without_pyside6(self):
        code, out, err = run_child(NO_PYSIDE6 + "import runpy\nsys.argv = ['chanceblog_desktop', '--help']\nrunpy.run_module('chanceblog_desktop', run_name='__main__')")
        self.assertEqual(code, 0, err[-300:])
        self.assertIn("doctor", out)
        self.assertNotIn("PySide6", err)

    def test_the_gui_command_is_routed_by_the_package_entry_point_and_help_needs_no_pyside6(self):
        code, out, err = run_child(NO_PYSIDE6 + "import runpy\nsys.argv = ['chanceblog_desktop', 'gui', '--help']\nrunpy.run_module('chanceblog_desktop', run_name='__main__')")
        self.assertEqual(code, 0, err[-300:])
        self.assertIn("--data-dir", out)
        self.assertIn("--sample", out)
        self.assertIn("읽기만", out)

    def test_the_modules_a_command_line_run_touches_never_import_pyside6(self):
        code, out, err = run_child(NO_PYSIDE6 + "import chanceblog_desktop.ui.launcher, chanceblog_desktop.ui.adapters, chanceblog_desktop.ui.core.app_state, chanceblog_desktop.ui.core.jobs\nprint('ok')")
        self.assertEqual((code, out.strip()), (0, "ok"), err[-300:])

    def test_the_qt_layer_needs_pyside6_and_says_so_by_failing_to_import(self):
        code, _out, err = run_child(NO_PYSIDE6 + "import chanceblog_desktop.ui.qt.shell")
        self.assertNotEqual(code, 0)
        self.assertRegex(err, "ModuleNotFoundError|ImportError")

    def test_in_process_guidance_text(self):
        out = io.StringIO()
        with mock.patch.object(launcher, "has_pyside6", return_value=False):
            self.assertEqual(launcher.main([], out=out), 1)
        self.assertEqual(out.getvalue().strip(), launcher.NEEDS_PYSIDE6)
        for word in ("Traceback", "ModuleNotFoundError", "ImportError"):
            self.assertNotIn(word, out.getvalue())

    def test_the_options_are_only_the_two_documented_ones(self):
        parser = launcher.build_parser()
        args = parser.parse_args(["--data-dir", "C:\\x", "--sample"])
        self.assertEqual((args.data_dir, args.sample), ("C:\\x", True))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--unknown"])


def fake_qt_app(result=0):
    """`ui.qt.app`(PySide6 가 있어야 불러온다) 자리에 끼워 넣는 가짜 모듈 — `run` 이 받은 공급자를 모아 둔다."""
    module = types.ModuleType("chanceblog_desktop.ui.qt.app")
    module.providers = []
    module.run = lambda provider, argv=None: (module.providers.append(provider), result)[1]
    return module


class EntryTest(unittest.TestCase):
    """`launcher.main` 이 어떤 공급자로 화면을 여는지 — 기본은 내 데이터(읽기 전용 어댑터), `--sample` 은 예시 데이터, `--data-dir` 은 어댑터에 그대로 넘어간다. 화면은 열지 않는다(가짜 `run`)."""

    def open(self, *argv, result=0):
        module = fake_qt_app(result)
        with mock.patch.object(launcher, "has_pyside6", return_value=True), mock.patch.dict(sys.modules, {"chanceblog_desktop.ui.qt.app": module}):
            code = launcher.main(list(argv))
        return code, module.providers

    def test_the_default_opens_my_own_data_through_the_read_only_adapter(self):
        code, providers = self.open()
        self.assertEqual((code, len(providers)), (0, 1))
        self.assertIsInstance(providers[0], ServiceHomeProvider)
        self.assertFalse(providers[0].sample)
        self.assertIsNone(providers[0]._data_dir)

    def test_data_dir_goes_to_the_adapter_untouched(self):
        _code, providers = self.open("--data-dir", "C:\\내 폴더\\데이터")
        self.assertIsInstance(providers[0], ServiceHomeProvider)
        self.assertEqual(providers[0]._data_dir, "C:\\내 폴더\\데이터")

    def test_sample_opens_the_fake_data_and_never_reads_a_data_folder(self):
        for argv in (("--sample",), ("--sample", "--data-dir", "C:\\없는 폴더"), ("--data-dir", "C:\\없는 폴더", "--sample")):
            _code, providers = self.open(*argv)
            self.assertIsInstance(providers[0], FakeHomeProvider, argv)
            self.assertTrue(providers[0].sample)
            self.assertFalse(isinstance(providers[0], ServiceHomeProvider))

    def test_the_exit_code_of_the_screen_is_the_exit_code_of_the_command(self):
        for result in (0, 3):
            self.assertEqual(self.open(result=result)[0], result)

    def test_the_arguments_after_gui_reach_the_launcher_through_the_package_entry_point(self):
        """진입점이 `gui` 자신을 인자로 넘기면 `gui --sample` 이 사용법 오류가 된다 — PySide6 가 없는 PC 에서도 같은 길로 안내문이 나와야 한다."""
        for args in ("'gui', '--sample'", "'gui', '--data-dir', 'C:\\\\내 폴더'", "'gui', '--sample', '--data-dir', 'C:\\\\내 폴더'"):
            code, out, err = run_child(NO_PYSIDE6 + f"import runpy\nsys.argv = ['chanceblog_desktop', {args}]\nrunpy.run_module('chanceblog_desktop', run_name='__main__')")
            self.assertEqual(code, 1, (args, err[-300:]))
            self.assertIn("python -m pip install PySide6", out)
            self.assertEqual(err.strip(), "")


class UsageErrorTest(unittest.TestCase):
    """`gui` 의 사용법 오류는 사용자가 친 값을 되풀이하지 않는다(키가 들어 있을 수도 있다) — 값 없는 고정 한국어 문장 + 사용법 한 줄, 종료 코드 2(명령줄의 사용법 오류와 같다)."""

    def gui(self, *args):
        code, out, err = run_child("", "-m", "chanceblog_desktop", "gui", *args)         # 진짜 프로세스(이 시험을 도는 파이썬 그대로 — 3.10 이든 3.12 이든)
        return code, out + err

    def assert_no_echo(self, shown, secret=SECRET, context=""):
        for piece in (secret, secret[:8], secret[-8:], secret[10:20]):
            self.assertNotIn(piece, shown, context)

    def assert_fixed_usage_error(self, args, secret=SECRET):
        code, shown = self.gui(*args)
        self.assertEqual(code, 2, shown[-300:])
        self.assertIn(FIXED_SENTENCE, shown)
        self.assertIn(launcher.USAGE_LINE, shown)
        self.assert_no_echo(shown, secret, args)
        self.assertNotRegex(shown, r"ignored explicit|unrecognized|expected one|usage:|error:|Traceback")             # 영어 기본 문구도 없다
        return shown

    def test_an_explicit_value_on_a_flag_that_takes_none_is_not_repeated(self):
        self.assert_fixed_usage_error([f"--sample={SECRET}"])

    def test_a_stray_value_is_not_repeated(self):
        self.assert_fixed_usage_error([SECRET])

    def test_an_unknown_option_and_its_value_are_not_repeated(self):
        shown = self.assert_fixed_usage_error(["--unknown-option", SECRET])
        self.assertNotIn("--unknown-option", shown)
        self.assert_fixed_usage_error(["--모름", SECRET, "--sample"])
        self.assert_fixed_usage_error([f"--모름={SECRET}"])

    def test_a_short_option_glued_to_a_value_is_not_repeated(self):
        for glued in (f"-x{SECRET}", f"-s{SECRET}", f"-d{SECRET}"):
            self.assert_fixed_usage_error([glued])

    def test_help_with_a_value_never_shows_the_value(self):
        """`-h값` 은 3.10 에서 사용법 오류, 3.12 에서 도움말로 끝난다(파이썬 버전 차이) — 어느 쪽이든 값은 안 나온다. `--help=값` 은 오류."""
        code, shown = self.gui(f"-h{SECRET}")
        self.assertIn(code, (0, 2))
        self.assert_no_echo(shown)
        self.assertIn(launcher.USAGE_LINE if code == 2 else "옵션:", shown)
        self.assert_fixed_usage_error([f"--help={SECRET}"])

    def test_a_missing_value_and_a_value_after_a_valid_option_are_fixed_sentences(self):
        self.assert_fixed_usage_error(["--data-dir"])
        self.assert_fixed_usage_error(["--sample", SECRET, "--data-dir", "C:\\x"])
        code, shown = self.gui("--help")
        self.assertEqual(code, 0)
        self.assertNotIn(FIXED_SENTENCE, shown)

    def test_very_long_multiline_and_backslash_values_are_not_repeated_either(self):
        for secret in (("가" * 12000 + " " + SECRET + " " + "나" * 12000), SECRET + "\nsecond line " + SECRET[::-1], "C:\\Users\\" + SECRET + "\\x\\y\\", SECRET + "\r\n" + SECRET):
            code, shown = self.gui("--sample=" + secret)
            self.assertEqual(code, 2)
            self.assert_no_echo(shown, SECRET, secret[:30])
            self.assertNotIn("second line", shown)
            self.assertNotIn("가가가가", shown)
            self.assertIn(FIXED_SENTENCE, shown)

    def test_in_process_the_error_text_is_fixed_whatever_comes_in_and_a_huge_value_is_cheap(self):
        huge = "x" * 1_000_000 + SECRET
        table = ((f"--sample={SECRET}", (2,)), (SECRET, (2,)), (f"-x{SECRET}", (2,)), (f"--모름={SECRET}", (2,)), (f"-h{SECRET}", (0, 2)), (f"--help={SECRET}", (2,)),
                 ("--sample=\\", (2,)), ("--sample=" + huge, (2,)), (huge, (2,)), ("-x" + huge, (2,)), ("--모름=" + huge, (2,)),
                 (f"--data-dir={SECRET}\nx", (1,)))                                                         # 올바른 옵션이면 오류가 아니다(PySide6 가 없다는 안내로 끝난다) — 값은 어디에도 안 나온다
        for value, expected in table:
            err, out = io.StringIO(), io.StringIO()
            started = time.perf_counter()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out), mock.patch.object(launcher, "has_pyside6", return_value=False):
                try:
                    code = launcher.main([value], out=out)
                except SystemExit as stop:
                    code = stop.code
            elapsed = time.perf_counter() - started
            shown = err.getvalue() + out.getvalue()
            self.assertLess(elapsed, 5, f"{len(value)}자 값을 처리하는 데 {elapsed:.1f}초")                       # 값 길이에 비례할 뿐 제곱으로 늘지 않는다
            self.assertIn(code, expected, value[:30])
            self.assertNotIn(SECRET[:8], shown)
            self.assertNotIn("xxxxxxxx", shown)
            if code == 2:
                self.assertEqual(err.getvalue().splitlines()[0], FIXED_SENTENCE)

    def test_the_help_is_in_korean_and_lists_only_the_two_options(self):
        for flag in ("--help", "-h"):
            code, shown = self.gui(flag)
            self.assertEqual(code, 0)
            for word in ("사용법:", "옵션:", "--data-dir", "--sample", "읽기만"):
                self.assertIn(word, shown, flag)
            self.assertNotRegex(shown, r"\busage:|\boptions:|optional arguments|show this help")
        self.assertNotIn("positional", shown)

    def test_the_parser_is_a_small_subclass_that_only_replaces_the_error_text(self):
        parser = launcher.build_parser()
        self.assertIsInstance(parser, launcher.GuiParser)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
            parser.error(f"argument --sample: ignored explicit argument '{SECRET}'")          # argparse 가 값을 넣어 부르는 모양 그대로
        self.assertEqual(stop.exception.code, 2)
        self.assertEqual(err.getvalue().splitlines(), [FIXED_SENTENCE, launcher.USAGE_LINE, launcher.USAGE_HINT])
        self.assertNotIn(SECRET[:8], err.getvalue())


if __name__ == "__main__":
    unittest.main()
