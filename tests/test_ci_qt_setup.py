"""정식 CI Qt 칸의 준비 스크립트(`scripts/ci_qt_setup.py`, D-710·D-711) 시험 — 잠금 파일의 PySide6 두 줄만, 고정 인자로, 셸 없이 설치하고, 실패하면 실패한다는 것을 지킨다.
이 시험은 진짜 설치를 하지 않는다(pip 를 부르는 곳은 가짜로 바꿔 끼운다 — 이 PC 에도 CI 의 열두 칸에도 아무것도 받지 않는다). 네트워크·시크릿이 없이 돈다.

지키는 것:
  1) 잠금 읽기: 진짜 잠금 파일에서 정확히 두 줄(같은 버전)을 읽는다. 세 줄·한 줄·버전 불일치·표시 없음·다른 이름·`이름==버전` 이 아닌 모양(범위·주소·옵션·표시)은 거절하고, 거절 글에 줄 내용을 담지 않는다. 해시는 둘 다 있거나 둘 다 없어야 한다.
  2) 설치 명령: 고정 인자(`--disable-pip-version-check`·`--isolated`·`--only-binary=:all:`·`--no-deps`)와 잠금의 두 줄뿐, 셸 없음, 설치처를 바꾸는 옵션 없음. 해시가 생기면 `--require-hashes` 와 임시 요구 파일.
  3) 점검: 설치된 버전이 잠금과 다르거나 없으면 실패(종료 코드 4), 설치 실패는 3, 잠금·인자 거절은 2, Qt 점검 실패는 5. 한글 글꼴이 없는 것은 알림일 뿐 실패가 아니다.
  4) 출력: 경로·사용자 이름이 없다. 한글을 파이프에 cp1252 로 찍다 죽지 않는다.
  5) 소스: 표준 라이브러리만(맨 위 가져오기), 셸·네트워크 코드 없음, 버전 숫자를 소스에 적지 않는다(잠금 파일이 유일한 출처).
"""
import ast
import contextlib
import importlib.metadata
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci_qt_setup.py"
sys.path.insert(0, str(ROOT / "scripts"))
import ci_qt_setup  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
GOOD = "# 머리 설명\n\n# [runtime]\nPySide6_Essentials==6.12.0\nshiboken6==6.12.0\n\n# [build]\npyinstaller==6.22.3\nsetuptools==84.0.0\n"
ALLOWED_OPTIONS = {"--disable-pip-version-check", "--isolated", "--only-binary=:all:", "--no-deps", "--require-hashes", "-r", "-m"}


def lock_text(*runtime_lines, build=("pyinstaller==6.22.3",)):
    return "# [runtime]\n" + "".join(line + "\n" for line in runtime_lines) + "\n# [build]\n" + "".join(line + "\n" for line in build)


def good_lock():
    return ci_qt_setup.read_lock(GOOD)


class FakeRun:
    """`subprocess.run` 자리에 끼우는 가짜 — 어떤 명령이 어떤 인자로 불렸는지 적어 두고 정해 둔 결과를 돌려준다(아무것도 실행하지 않는다)."""

    def __init__(self, returncode=0, stdout="", stderr="", error=None, peek=None):
        self.returncode, self.stdout, self.stderr, self.error, self.peek = returncode, stdout, stderr, error, peek
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.peek is not None:
            self.peek(command)
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, self.stderr)


def run_main(*argv, **hooks):
    """`main` 을 이 프로세스 안에서 돌려 (종료 코드, 표준 출력, 표준 오류)를 돌려준다. 두 출력을 모두 바꿔 끼워 시험 러너의 출력 설정을 건드리지 않는다."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ci_qt_setup.main(list(argv), **hooks)
    return code, out.getvalue(), err.getvalue()


def fake_facts(**changes):
    facts = {"qt": "6.0.0", "platform": "offscreen", **ci_qt_setup.font_facts(["Segoe UI", "Malgun Gothic", "Arial"], ["Malgun Gothic"], "Segoe UI")}
    facts.update(changes)
    return facts


def run_script(*args, env_extra=None, drop=()):
    env = {key: value for key, value in os.environ.items() if key not in drop}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, encoding="utf-8", env=env, cwd=str(ROOT), timeout=300)


class ReadLockTest(unittest.TestCase):
    def test_the_real_lock_file_has_exactly_the_two_runtime_lines_with_one_version(self):
        lock = ci_qt_setup.read_lock((ROOT / "packaging" / "requirements-package.txt").read_text(encoding="utf-8"))
        self.assertEqual([name for name, _version, _hashes in lock.requirements], ["PySide6_Essentials", "shiboken6"])
        self.assertEqual({version for _name, version, _hashes in lock.requirements}, {lock.version})
        self.assertRegex(lock.version, r"^\d+\.\d+\.\d+$")
        self.assertEqual(lock.hashed, all(hashes for _name, _version, hashes in lock.requirements), "해시 표시는 두 줄 모두에 해시가 있을 때만 켜진다(지금 잠금에는 해시가 없다 — 해시 잠금은 따로 승인받는 일, D-711)")

    def test_a_good_lock_reads_to_two_pins(self):
        lock = good_lock()
        self.assertEqual(lock.version, "6.12.0")
        self.assertEqual(lock.requirements, (("PySide6_Essentials", "6.12.0", ()), ("shiboken6", "6.12.0", ())))

    def test_lines_after_the_build_mark_are_not_read_as_runtime(self):
        self.assertEqual(len(ci_qt_setup.runtime_lines(GOOD)), 2)
        self.assertEqual(ci_qt_setup.runtime_lines(lock_text("PySide6_Essentials==6.12.0", "shiboken6==6.12.0", build=("a==1", "b==2", "c==3"))), ["PySide6_Essentials==6.12.0", "shiboken6==6.12.0"])

    def test_a_third_runtime_line_is_refused(self):
        with self.assertRaises(ci_qt_setup.LockError) as caught:
            ci_qt_setup.read_lock(lock_text("PySide6_Essentials==6.12.0", "shiboken6==6.12.0", "requests==2.0.0"))
        self.assertIn("정확히 두 줄", str(caught.exception), "이유가 '두 줄이 아니다' 여야 한다 — 이름 검사가 대신 거절해도 두 줄 검사가 빠진 것이다")

    def test_a_single_runtime_line_or_none_is_refused(self):
        for lines in (("PySide6_Essentials==6.12.0",), ()):
            with self.subTest(lines=lines), self.assertRaises(ci_qt_setup.LockError) as caught:
                ci_qt_setup.read_lock(lock_text(*lines))
            self.assertIn("정확히 두 줄", str(caught.exception))

    def test_different_versions_are_refused(self):
        with self.assertRaises(ci_qt_setup.LockError) as caught:
            ci_qt_setup.read_lock(lock_text("PySide6_Essentials==6.12.0", "shiboken6==6.11.0"))
        self.assertIn("버전이 같아야", str(caught.exception))

    def test_a_lock_without_the_runtime_mark_or_with_two_is_refused(self):
        for text in ("PySide6_Essentials==6.12.0\nshiboken6==6.12.0\n", "# [build]\npyinstaller==6.22.3\n", GOOD + "# [runtime]\nrequests==2.0.0\n"):
            with self.subTest(text=text[:40]), self.assertRaises(ci_qt_setup.LockError):
                ci_qt_setup.read_lock(text)

    def test_other_names_are_refused_even_when_there_are_two_lines(self):
        for pair in (("PySide6_Essentials==6.12.0", "requests==2.0.0"), ("PySide6_Addons==6.12.0", "shiboken6==6.12.0"), ("PySide6==6.12.0", "shiboken6==6.12.0"),
                     ("PySide6_Essentials==6.12.0", "PySide6_Essentials==6.12.0")):
            with self.subTest(pair=pair), self.assertRaises(ci_qt_setup.LockError) as caught:
                ci_qt_setup.read_lock(lock_text(*pair))
            self.assertIn("이름은 PySide6_Essentials", str(caught.exception))

    def test_names_are_compared_after_the_package_name_normalisation(self):
        lock = ci_qt_setup.read_lock(lock_text("pyside6-essentials==6.12.0", "Shiboken6==6.12.0"))
        self.assertEqual(lock.version, "6.12.0")

    def test_anything_but_name_equals_version_is_refused(self):
        odd = ("PySide6_Essentials>=6.12.0", "PySide6_Essentials~=6.12", "PySide6_Essentials==6.*", "PySide6_Essentials[extra]==6.12.0", "PySide6_Essentials==6.12.0; python_version >= '3.10'",
               "PySide6_Essentials @ file:///x.whl", "-r other.txt", "--index-url something", "--extra-index-url something", "PySide6_Essentials==6.12.0 --index-url x",
               "PySide6_Essentials===6.12.0", "git+ssh://example/x.git#egg=PySide6_Essentials", "PySide6_Essentials==6.12.0 --hash=md5:abc")
        for line in odd:
            with self.subTest(line=line), self.assertRaises(ci_qt_setup.LockError):
                ci_qt_setup.read_lock(lock_text(line, "shiboken6==6.12.0"))

    def test_the_refusal_never_repeats_the_line_it_refused(self):
        secretish = "PySide6_Essentials @ user:CANARY_" + "x" * 8 + "@example.invalid/p.whl"
        with self.assertRaises(ci_qt_setup.LockError) as caught:
            ci_qt_setup.read_lock(lock_text(secretish, "shiboken6==6.12.0"))
        self.assertNotIn("CANARY_", str(caught.exception))
        self.assertNotIn("example.invalid", str(caught.exception))

    def test_blank_lines_comments_inline_comments_and_crlf_are_fine(self):
        text = "# [runtime]\r\n\r\n# 설명 한 줄\r\nPySide6_Essentials==6.12.0   # 화면 도구\r\n\r\nshiboken6==6.12.0\r\n# [build]\r\nx==1\r\n"
        self.assertEqual(ci_qt_setup.read_lock(text).version, "6.12.0")

    def test_hash_options_on_both_lines_make_a_hashed_lock_and_continuations_are_joined(self):
        one_line = ci_qt_setup.read_lock(lock_text(f"PySide6_Essentials==6.12.0 --hash={HASH_A}", f"shiboken6==6.12.0 --hash={HASH_A} --hash={HASH_B}"))
        self.assertTrue(one_line.hashed)
        self.assertEqual(one_line.requirements[1][2], (f"--hash={HASH_A}", f"--hash={HASH_B}"))
        continued = ci_qt_setup.read_lock(lock_text(f"PySide6_Essentials==6.12.0 \\\n    --hash={HASH_A}", f"shiboken6==6.12.0 \\\n    --hash={HASH_B} \\\n    --hash={HASH_A}\n    # via -r x"))
        self.assertTrue(continued.hashed)
        self.assertEqual(len(continued.requirements[1][2]), 2)

    def test_a_hash_on_only_one_line_or_a_malformed_hash_is_refused(self):
        for pair in ((f"PySide6_Essentials==6.12.0 --hash={HASH_A}", "shiboken6==6.12.0"), ("PySide6_Essentials==6.12.0 --hash=sha256:abc", "shiboken6==6.12.0 --hash=sha256:abc"),
                     (f"PySide6_Essentials==6.12.0 --hash=sha256:{'A' * 64}", f"shiboken6==6.12.0 --hash={HASH_B}")):
            with self.subTest(pair=pair[0][:50]), self.assertRaises(ci_qt_setup.LockError):
                ci_qt_setup.read_lock(lock_text(*pair))

    def test_a_dangling_backslash_is_refused(self):
        for text in ("# [runtime]\nPySide6_Essentials==6.12.0 \\\n\n# [build]\n", "# [runtime]\nPySide6_Essentials==6.12.0\nshiboken6==6.12.0 \\\n"):
            with self.subTest(text=text[:30]), self.assertRaises(ci_qt_setup.LockError):
                ci_qt_setup.read_lock(text)


class PipCommandTest(unittest.TestCase):
    def test_the_command_is_a_fixed_list_plus_the_two_pins(self):
        self.assertEqual(ci_qt_setup.pip_command(good_lock(), "py"),
                         ["py", "-m", "pip", "install", "--disable-pip-version-check", "--isolated", "--only-binary=:all:", "--no-deps", "PySide6_Essentials==6.12.0", "shiboken6==6.12.0"])

    def test_the_command_can_neither_change_the_index_nor_build_from_source_nor_pull_dependencies(self):
        command = ci_qt_setup.pip_command(good_lock(), "py")
        options = [item for item in command[1:] if item.startswith("-")]
        self.assertEqual(sorted(set(options) - ALLOWED_OPTIONS), [])
        for word in ("index", "find-links", "trusted-host", "--pre", "no-binary", "upgrade", "target", "user", "break-system", "constraint", "extra"):
            self.assertFalse([item for item in command if word in item], word)
        self.assertIn("--only-binary=:all:", command)
        self.assertIn("--no-deps", command)
        self.assertIn("--isolated", command)

    def test_a_hashed_lock_installs_from_a_temporary_requirements_file_with_require_hashes(self):
        lock = ci_qt_setup.read_lock(lock_text(f"PySide6_Essentials==6.12.0 --hash={HASH_A}", f"shiboken6==6.12.0 --hash={HASH_B}"))
        command = ci_qt_setup.pip_command(lock, "py", "file.txt")
        self.assertEqual(command[-3:], ["--require-hashes", "-r", "file.txt"])
        self.assertFalse([item for item in command if "==" in item], "해시 잠금에서는 두 줄이 명령줄이 아니라 요구 파일에 있다")
        self.assertEqual(ci_qt_setup.requirements_text(lock), f"PySide6_Essentials==6.12.0 --hash={HASH_A}\nshiboken6==6.12.0 --hash={HASH_B}\n")

    def test_install_runs_the_fixed_list_without_a_shell_with_a_time_limit_and_utf8(self):
        fake = FakeRun()
        code, tail = ci_qt_setup.install(good_lock(), run=fake)
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.calls), 1)
        command, kwargs = fake.calls[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command, ci_qt_setup.pip_command(good_lock(), sys.executable))
        self.assertIs(kwargs.get("shell"), False)
        self.assertTrue(kwargs.get("capture_output"))
        self.assertEqual(kwargs["timeout"], ci_qt_setup.PIP_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["env"]["PYTHONUTF8"], "1")

    def test_a_hashed_install_writes_the_requirements_file_only_while_pip_runs(self):
        lock = ci_qt_setup.read_lock(lock_text(f"PySide6_Essentials==6.12.0 --hash={HASH_A}", f"shiboken6==6.12.0 --hash={HASH_B}"))
        seen = {}

        def peek(command):
            seen["path"] = Path(command[-1])
            seen["text"] = seen["path"].read_text(encoding="utf-8")

        code, _tail = ci_qt_setup.install(lock, run=FakeRun(peek=peek))
        self.assertEqual(code, 0)
        self.assertEqual(seen["text"], ci_qt_setup.requirements_text(lock))
        self.assertFalse(seen["path"].exists(), "임시 요구 파일은 설치 도구가 끝나면 지워진다")

    def test_a_failed_install_returns_the_code_and_only_the_last_lines_with_the_home_folder_hidden(self):
        home = str(Path.home())
        noisy = "\n".join(f"줄 {number}" for number in range(100)) + f"\nERROR: 실패 {home}\\x\\y"
        code, tail = ci_qt_setup.install(good_lock(), run=FakeRun(returncode=1, stdout=noisy, stderr=""))
        self.assertEqual(code, 1)
        self.assertEqual(len(tail.splitlines()), ci_qt_setup.TAIL_LINES)
        self.assertIn("ERROR", tail)
        self.assertNotIn("줄 5\n", tail + "\n")
        self.assertNotIn(home, tail)

    def test_a_timeout_or_a_missing_tool_is_a_failure_with_a_short_reason(self):
        for error in (subprocess.TimeoutExpired(["pip"], 1), FileNotFoundError("x")):
            with self.subTest(error=type(error).__name__):
                code, tail = ci_qt_setup.install(good_lock(), run=FakeRun(error=error))
                self.assertNotEqual(code, 0)
                self.assertTrue(tail)

    def test_scrub_hides_the_home_folder_in_both_slash_styles_and_the_account_name(self):
        home = str(Path.home())
        with mock.patch.dict(os.environ, {"USERNAME": "ciqt_tester_name", "USER": "ciqt_tester_name"}):
            text = ci_qt_setup.scrub(f"a {home} b {home.replace(chr(92), '/')}/x c ciqt_tester_name d")
        self.assertNotIn(home, text)
        self.assertNotIn(home.replace("\\", "/"), text)
        self.assertNotIn("ciqt_tester_name", text)


class VersionCheckTest(unittest.TestCase):
    def lookup(self, table):
        def inner(name):
            if name not in table:
                raise importlib.metadata.PackageNotFoundError(name)
            return table[name]
        return inner

    def test_equal_versions_have_no_problem(self):
        self.assertEqual(ci_qt_setup.version_problems(good_lock(), self.lookup({"PySide6_Essentials": "6.12.0", "shiboken6": "6.12.0"})), [])

    def test_a_different_version_is_a_problem_for_each_package(self):
        problems = ci_qt_setup.version_problems(good_lock(), self.lookup({"PySide6_Essentials": "6.11.0", "shiboken6": "6.12.1"}))
        self.assertEqual(len(problems), 2)
        self.assertIn("6.11.0", problems[0])

    def test_a_missing_package_is_a_problem(self):
        problems = ci_qt_setup.version_problems(good_lock(), self.lookup({"shiboken6": "6.12.0"}))
        self.assertEqual(len(problems), 1)
        self.assertIn("PySide6_Essentials", problems[0])


class FontReportTest(unittest.TestCase):
    def test_hangul_fonts_come_from_the_qt_writing_system_and_from_known_names(self):
        facts = ci_qt_setup.font_facts(["Arial", "Malgun Gothic", "Batang", "Other"], ["Other"], "Segoe UI")
        self.assertEqual(facts["count"], 4)
        self.assertEqual(facts["hangul"], ["Batang", "Malgun Gothic", "Other"], "알려진 이름이 앞에, 나머지는 이름 순")
        self.assertFalse(facts["message_in_list"])

    def test_the_korean_name_of_the_windows_message_font_matches_its_english_family(self):
        self.assertTrue(ci_qt_setup.font_facts(["Malgun Gothic"], [], "맑은 고딕")["message_in_list"])
        self.assertFalse(ci_qt_setup.font_facts(["Arial"], [], "맑은 고딕")["message_in_list"])
        self.assertFalse(ci_qt_setup.font_facts(["Arial"], [], None)["message_in_list"])

    def test_the_report_has_the_versions_the_platform_and_the_font_names(self):
        lines = ci_qt_setup.report_lines(good_lock(), fake_facts())
        text = "\n".join(lines)
        self.assertEqual(len(lines), 4)
        for needle in ("6.12.0", "offscreen", "Malgun Gothic", "Segoe UI", "목록 3개"):
            self.assertIn(needle, text, needle)
        self.assertNotIn("알림", text)

    def test_no_hangul_font_is_a_notice_and_not_a_failure(self):
        facts = fake_facts(**ci_qt_setup.font_facts(["Arial"], [], "Segoe UI"))
        lines = ci_qt_setup.report_lines(good_lock(), facts)
        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[-1].startswith("알림:"))
        self.assertIn("docs/CI_QT.md", lines[-1])
        code, out, _err = run_main("--probe-only", f"--lock={self.write_lock()}", lookup=lambda name: "6.12.0", probe_function=lambda: facts)
        self.assertEqual(code, 0, "한글 글꼴이 없어도 준비 단계는 실패하지 않는다 — 판정은 첫 실행 뒤 사람이 한다")
        self.assertIn("알림:", out)

    def write_lock(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "lock.txt"
        path.write_text(GOOD, encoding="utf-8")
        return path

    def test_a_long_font_list_is_cut_to_six_names(self):
        names = [f"Font{number:02d}" for number in range(30)]
        text = ci_qt_setup.report_lines(good_lock(), fake_facts(**ci_qt_setup.font_facts(names, names, None)))[2]
        self.assertIn("외 24개", text)
        self.assertNotIn("Font29", text)

    def test_the_report_has_no_path_or_drive_letter(self):
        text = "\n".join(ci_qt_setup.report_lines(good_lock(), fake_facts()))
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]|/Users/|\\Users\\|/home/", text))
        self.assertNotIn(str(Path.home()), text)


def fake_pyside6(platform="offscreen", families=("Segoe UI", "Malgun Gothic", "Arial"), korean=("Malgun Gothic",), create_error=None):
    """`sys.modules` 에 끼워 넣는 가짜 PySide6 — 점검(`probe`)의 가져오기·QApplication 만들기·글꼴 읽기를 PySide6 없이도(열두 칸에서도) 진짜 코드로 시험한다."""
    core = types.ModuleType("PySide6.QtCore")
    core.qVersion = lambda: "6.0.0"
    gui = types.ModuleType("PySide6.QtGui")

    class QFontDatabase:
        class WritingSystem:
            Korean = "korean"

        @staticmethod
        def families(system=None):
            return list(korean if system == "korean" else families)

    gui.QFontDatabase = QFontDatabase
    widgets = types.ModuleType("PySide6.QtWidgets")

    class QApplication:
        current = None

        def __init__(self, argv):
            if create_error is not None:
                raise create_error
            QApplication.current = self

        @staticmethod
        def instance():
            return QApplication.current

        def platformName(self):
            return platform

    widgets.QApplication = QApplication
    package = types.ModuleType("PySide6")
    return {"PySide6": package, "PySide6.QtCore": core, "PySide6.QtGui": gui, "PySide6.QtWidgets": widgets}


class ProbeTest(unittest.TestCase):
    """`probe()` 를 가짜 PySide6 로 — 진짜 PySide6 없이도 점검의 판정(화면 방식·예외 → ProbeError·글꼴 사실)이 지켜진다."""

    def probe_with(self, **kwargs):
        with mock.patch.dict(sys.modules, fake_pyside6(**kwargs)), mock.patch.dict(os.environ):
            return ci_qt_setup.probe()

    def test_a_working_application_gives_the_versions_the_platform_and_the_font_facts(self):
        facts = self.probe_with()
        self.assertEqual((facts["qt"], facts["platform"], facts["count"]), ("6.0.0", "offscreen", 3))
        self.assertEqual(facts["hangul"], ["Malgun Gothic"])

    def test_the_probe_forces_the_offscreen_platform_for_itself(self):
        with mock.patch.dict(sys.modules, fake_pyside6()), mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "windows"}):
            ci_qt_setup.probe()
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "offscreen")

    def test_a_platform_other_than_offscreen_fails_the_probe(self):
        with self.assertRaises(ci_qt_setup.ProbeError) as caught:
            self.probe_with(platform="windows")
        self.assertIn("offscreen", str(caught.exception))

    def test_an_error_while_making_the_application_fails_the_probe_with_its_type_name(self):
        with self.assertRaises(ci_qt_setup.ProbeError) as caught:
            self.probe_with(create_error=RuntimeError("platform plugin missing"))
        self.assertIn("RuntimeError", str(caught.exception))

    def test_a_package_that_cannot_be_imported_fails_the_probe(self):
        modules = fake_pyside6()
        modules["PySide6.QtWidgets"] = None                                                        # `import` 가 ImportError 를 낸다
        with mock.patch.dict(sys.modules, modules), mock.patch.dict(os.environ), self.assertRaises(ci_qt_setup.ProbeError) as caught:
            ci_qt_setup.probe()
        self.assertRegex(str(caught.exception), "ModuleNotFoundError|ImportError", "가져오기 실패의 종류가 글에 있다")

    def test_the_home_folder_is_hidden_in_the_failure_text(self):
        home = str(Path.home())
        with self.assertRaises(ci_qt_setup.ProbeError) as caught:
            self.probe_with(create_error=RuntimeError(f"cannot load {home}\\x.dll"))
        self.assertNotIn(home, str(caught.exception))

    def test_main_turns_a_failed_probe_into_exit_five_end_to_end(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "lock.txt"
            lock.write_text(GOOD, encoding="utf-8")
            with mock.patch.dict(sys.modules, fake_pyside6(platform="windows")), mock.patch.dict(os.environ):
                code, _out, err = run_main("--probe-only", f"--lock={lock}", lookup=lambda name: "6.12.0")
        self.assertEqual(code, 5)
        self.assertIn("offscreen", err)


class MainFlowTest(unittest.TestCase):
    """종료 코드: 0 성공 · 2 잠금·인자 · 3 pip · 4 버전 · 5 Qt 점검. 모든 외부 일(pip·가져오기·QApplication)은 가짜로 바꿔 끼운다."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.lock = Path(self.folder.name) / "lock.txt"
        self.lock.write_text(GOOD, encoding="utf-8")

    def ok_lookup(self, name):
        return "6.12.0"

    def test_the_exit_codes_are_distinct_and_fixed(self):
        self.assertEqual((ci_qt_setup.EXIT_LOCK, ci_qt_setup.EXIT_PIP, ci_qt_setup.EXIT_VERSION, ci_qt_setup.EXIT_QT), (2, 3, 4, 5))

    def test_everything_fine_installs_checks_probes_and_exits_zero(self):
        fake = FakeRun()
        code, out, err = run_main(f"--lock={self.lock}", run=fake, lookup=self.ok_lookup, probe_function=fake_facts)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("offscreen", out)

    def test_dry_run_prints_the_command_and_never_runs_anything(self):
        def boom(*args, **kwargs):
            raise AssertionError("--dry-run 이 설치 도구를 불렀다")

        code, out, _err = run_main("--dry-run", f"--lock={self.lock}", run=boom, probe_function=boom, lookup=boom)
        self.assertEqual(code, 0)
        self.assertIn("실행하지 않는다", out)
        for needle in ("--only-binary=:all:", "--no-deps", "--isolated", "PySide6_Essentials==6.12.0", "shiboken6==6.12.0"):
            self.assertIn(needle, out, needle)
        self.assertNotIn(sys.executable, out)

    def test_a_refused_lock_exits_two_and_installs_nothing(self):
        self.lock.write_text(lock_text("PySide6_Essentials==6.12.0", "shiboken6==6.12.0", "extra==1.0"), encoding="utf-8")
        fake = FakeRun()
        code, _out, err = run_main(f"--lock={self.lock}", run=fake, lookup=self.ok_lookup, probe_function=fake_facts)
        self.assertEqual(code, 2)
        self.assertEqual(fake.calls, [], "잠금을 거절하면 pip 도 부르지 않는다")
        self.assertIn("두 줄", err)

    def test_a_missing_lock_file_exits_two(self):
        code, _out, err = run_main(f"--lock={self.lock}.nope", run=FakeRun(), lookup=self.ok_lookup, probe_function=fake_facts)
        self.assertEqual(code, 2)
        self.assertIn("FileNotFoundError", err)

    def test_bad_arguments_exit_two_and_install_nothing(self):
        for argv in (("--bogus",), ("--lock=",), ("--dry-run", "--probe-only"), ("extra",)):
            with self.subTest(argv=argv):
                fake = FakeRun()
                code, _out, err = run_main(*argv, run=fake, lookup=self.ok_lookup, probe_function=fake_facts)
                self.assertEqual(code, 2)
                self.assertEqual(fake.calls, [])
                self.assertIn("인자를 읽지 못했다", err, "잠금을 읽다 실패한 것이 아니라 인자 자체가 거절돼야 한다")

    def test_a_failed_pip_exits_three_and_stops_before_the_probe(self):
        def boom():
            raise AssertionError("설치가 실패했는데 점검까지 갔다")

        code, _out, err = run_main(f"--lock={self.lock}", run=FakeRun(returncode=1, stdout="ERROR: no matching distribution"), lookup=self.ok_lookup, probe_function=boom)
        self.assertEqual(code, 3)
        self.assertIn("no matching distribution", err)

    def test_an_installed_version_that_differs_from_the_lock_exits_four(self):
        code, _out, err = run_main(f"--lock={self.lock}", run=FakeRun(), lookup=lambda name: "6.11.0", probe_function=fake_facts)
        self.assertEqual(code, 4)
        self.assertIn("6.11.0", err)

    def test_a_pip_that_succeeds_without_installing_anything_exits_four(self):
        def missing(name):
            raise importlib.metadata.PackageNotFoundError(name)

        code, _out, _err = run_main(f"--lock={self.lock}", run=FakeRun(), lookup=missing, probe_function=fake_facts)
        self.assertEqual(code, 4, "조용히 빠진 설치를 초록으로 두지 않는다")

    def test_a_failed_probe_exits_five(self):
        def broken():
            raise ci_qt_setup.ProbeError("ImportError: DLL")

        code, _out, err = run_main(f"--lock={self.lock}", run=FakeRun(), lookup=self.ok_lookup, probe_function=broken)
        self.assertEqual(code, 5)
        self.assertIn("DLL", err)

    def test_probe_only_skips_the_install_but_still_checks_versions_and_the_probe(self):
        fake = FakeRun()
        code, _out, _err = run_main("--probe-only", f"--lock={self.lock}", run=fake, lookup=self.ok_lookup, probe_function=fake_facts)
        self.assertEqual((code, fake.calls), (0, []))
        code, _out, _err = run_main("--probe-only", f"--lock={self.lock}", run=fake, lookup=lambda name: "1.0.0", probe_function=fake_facts)
        self.assertEqual(code, 4)

    def test_the_default_lock_is_the_packaging_lock_file(self):
        self.assertEqual(ci_qt_setup.LOCK_FILE, ROOT / "packaging" / "requirements-package.txt")
        self.assertEqual(ci_qt_setup.parse([])["lock"], ci_qt_setup.LOCK_FILE)


class ScriptRunTest(unittest.TestCase):
    """진짜 스크립트를 자식 프로세스로 — 설치하지 않는 모양(`--dry-run`·거절·`--probe-only`)만 부른다."""

    def test_dry_run_against_the_real_lock_shows_the_fixed_command_and_exits_zero(self):
        done = run_script("--dry-run")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        for needle in ("-m pip install", "--disable-pip-version-check", "--isolated", "--only-binary=:all:", "--no-deps", "PySide6_Essentials==", "shiboken6==", "실행하지 않는다"):
            self.assertIn(needle, done.stdout, needle)
        self.assertNotIn(sys.executable, done.stdout)
        self.assertNotIn(str(ROOT), done.stdout)

    def test_a_bad_lock_or_argument_exits_two_in_the_real_script(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.txt"
            bad.write_text(lock_text("PySide6_Essentials==6.12.0"), encoding="utf-8")
            self.assertEqual(run_script("--dry-run", f"--lock={bad}").returncode, 2)
            self.assertEqual(run_script("--probe-only", f"--lock={bad}").returncode, 2)       # 인자 없이는 부르지 않는다 — 인자 없이 부르면 진짜로 설치한다
        self.assertEqual(run_script("--bogus").returncode, 2)
        self.assertEqual(run_script("--lock=" + str(ROOT / "no-such-file.txt"), "--dry-run").returncode, 2)

    def test_korean_text_reaches_a_pipe_even_when_the_console_encoding_is_not_utf8(self):
        # ci.yml 의 이 단계에는 PYTHONUTF8 이 없다 — 윈도 러너에서 출력이 파이프(cp1252)여도 한글 때문에 죽지 않아야 한다.
        done = run_script("--dry-run", env_extra={"PYTHONIOENCODING": "cp1252"}, drop=("PYTHONUTF8",))
        self.assertEqual(done.returncode, 0, done.stderr[-300:])
        self.assertIn("실행하지 않는다", done.stdout)
        bad = run_script("--bogus", env_extra={"PYTHONIOENCODING": "cp1252"}, drop=("PYTHONUTF8",))
        self.assertEqual(bad.returncode, 2)
        self.assertIn("인자를 읽지 못했다", bad.stderr)

    @unittest.skipUnless(HAVE, "PySide6 가 있어야 한다")
    def test_the_real_probe_makes_an_offscreen_application_and_prints_versions_and_fonts(self):
        try:
            installed = importlib.metadata.version("PySide6_Essentials")
            shiboken = importlib.metadata.version("shiboken6")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("PySide6_Essentials 나 shiboken6 의 설치 정보를 못 읽는다 — 이 PC 의 환경 이야기")
        if installed != shiboken:
            self.skipTest("PySide6 와 shiboken6 의 설치된 버전이 달라 잠금 모양(같은 버전)을 만들 수 없다 — 이 PC 의 환경 이야기")
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "lock.txt"
            lock.write_text(lock_text(f"PySide6_Essentials=={installed}", f"shiboken6=={shiboken}"), encoding="utf-8")
            done = run_script("--probe-only", f"--lock={lock}")
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        for needle in (installed, "offscreen", "글꼴: 목록", "윈도 메시지 글꼴"):
            self.assertIn(needle, done.stdout, needle)
        self.assertIsNone(re.search(r"[A-Za-z]:\\|/Users/", done.stdout))
        self.assertNotIn(str(Path.home()), done.stdout)


class SourceRulesTest(unittest.TestCase):
    def setUp(self):
        self.source = SCRIPT.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_the_top_level_imports_are_the_standard_library_only(self):
        names = set()
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        self.assertTrue(names)
        self.assertEqual(sorted(names - set(sys.stdlib_module_names)), [])

    def test_there_is_no_shell_no_network_and_no_native_call(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.keyword) and node.arg == "shell":
                self.assertTrue(isinstance(node.value, ast.Constant) and node.value.value is False, "shell 은 늘 False 다")
            elif isinstance(node, ast.Attribute) and node.attr in ("system", "popen", "startfile", "spawnl", "spawnv"):
                self.fail(f"셸·프로세스를 여는 호출: {node.attr}")
        self.assertEqual(sorted(imported & {"socket", "ssl", "http", "urllib", "requests", "ftplib", "smtplib", "ctypes", "webbrowser", "asyncio"}), [])
        self.assertTrue([node for node in ast.walk(self.tree) if isinstance(node, ast.keyword) and node.arg == "shell"], "시험이 shell 인자를 보는 자리가 있다")

    def test_subprocess_is_only_named_for_the_injectable_run_and_the_timeout_error_and_never_called_directly(self):
        names = {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "subprocess"}
        self.assertEqual(sorted(names), ["TimeoutExpired", "run"])
        direct = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"]
        self.assertEqual(direct, [], "설치 도구는 바꿔 끼울 수 있는 `run` 인자로만 부른다(시험이 가짜로 바꿔 끼운다)")

    def test_the_lock_file_is_the_only_place_that_names_the_version(self):
        self.assertEqual(re.findall(r"\b\d+\.\d+\.\d+\b", self.source), [], "버전 숫자를 소스에 적지 않는다 — 잠금 파일이 유일한 출처다")

    def test_the_documented_flags_are_the_only_flags_the_parser_accepts(self):
        for flag in ("--dry-run", "--probe-only", "--lock="):
            self.assertIn(flag, self.source)
        self.assertEqual(sorted(re.findall(r'item == "(--[a-z-]+)"', self.source)), ["--dry-run", "--probe-only"])


if __name__ == "__main__":
    unittest.main()
