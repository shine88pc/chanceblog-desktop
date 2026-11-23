"""`ui/winroot.py`(결정 D-593 — 글자 읽기 감사 R3 의 검증 SQ 참고 4)의 시험 — 윈도 폴더를 **윈도에 직접 묻는** 읽기 전용 도우미.

지키는 것:
  1) 묻기(`windows_directory`) — 윈도가 알려 준 폴더를 돌려주고, 윈도가 아니면 `ctypes` 를 가져오지도 부르지도 않고 None 이다. 호출이 실패하거나 0·너무 큰 길이가 돌아오거나 값이 드라이브 글자 절대 경로가 아니면 None 이다(부르는 쪽이 예전 길로 간다).
  2) 견주기(`same_folder`)·모양(`is_drive_absolute`) — 대소문자·구분자·끝 구분자·`..` 를 정리해 같은 폴더인지 보고, 글자만 닮은 다른 폴더는 같지 않다.
  3) 소스 모양 — 이 파일이 윈도 API 에 닿는 길은 `GetSystemWindowsDirectoryW` 읽기 하나뿐이다(가져오는 모듈·쓰는 이름을 닫힌 집합으로 못박는다). 쓰기·하위 프로세스·네트워크는 없다.
윈도 API 는 가짜 `ctypes` 모듈로 흉내 내어 어느 운영체제에서나 돌고, 진짜 호출은 윈도에서만(건너뛰기 표시) 한 번 본다.
"""
import ast
import ntpath
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.ui import winroot  # noqa: E402

B = chr(92)
SOURCE = ROOT / "src" / "chanceblog_desktop" / "ui" / "winroot.py"


class FakeBuffer:
    """`ctypes.create_unicode_buffer` 흉내 — 길이와 `value` 만 있다."""

    def __init__(self, size):
        self.size, self.value = size, ""

    def __len__(self):
        return self.size


def fake_ctypes(reply="", length=None, boom=None, no_function=False):
    """윈도 API 를 흉내 낸 가짜 `ctypes` -> (모듈, 불린 크기 목록). 부르면 `buffer.value` 에 reply 를 쓰고 length(기본은 reply 의 길이)를 돌려주며 boom 이 있으면 그 예외를 낸다."""
    calls = []

    def ask(buffer, size):
        calls.append(size)
        if boom is not None:
            raise boom
        buffer.value = reply
        return len(reply) if length is None else length
    kernel = types.SimpleNamespace() if no_function else types.SimpleNamespace(GetSystemWindowsDirectoryW=ask)
    module = types.ModuleType("ctypes")
    module.WinDLL = lambda name, use_last_error=False: kernel
    module.c_uint32, module.c_wchar_p, module.create_unicode_buffer = "uint32", "wchar_p", FakeBuffer
    return module, calls


def ask_windows(module):
    with mock.patch.object(os, "name", "nt"), mock.patch.dict(sys.modules, {"ctypes": module}):
        return winroot.windows_directory()


class AskTest(unittest.TestCase):
    def test_it_returns_the_folder_windows_reports_after_one_call_with_a_buffer_of_260(self):
        module, calls = fake_ctypes("E:" + B + "RealWin")
        self.assertEqual(ask_windows(module), "E:" + B + "RealWin")
        self.assertEqual(calls, [260])

    def test_a_reply_that_cannot_be_trusted_is_none(self):
        """0(실패)·버퍼 크기와 같거나 더 큰 길이(너무 길다 — 필요한 크기가 돌아온 것)·드라이브 글자 절대 경로가 아닌 값(네트워크 위치·상대 경로·`E:RealWin`)."""
        cases = (("", 0), ("E:" + B + "RealWin", 0), ("E:" + B + "RealWin", 260), ("E:" + B + "RealWin", 300), ("E:" + B + "RealWin", -1), (B * 2 + "server" + B + "share", None), ("Windows", None), ("E:RealWin", None), ("..", None),
                 (B * 2 + "?" + B + "E:" + B + "RealWin", None))
        for reply, length in cases:
            with self.subTest(reply=reply, length=length):
                module, _calls = fake_ctypes(reply, length)
                self.assertIsNone(ask_windows(module))

    def test_a_call_that_fails_in_any_way_is_none_and_never_raises(self):
        for label, module in (("호출이 예외", fake_ctypes(boom=OSError("실패"))[0]), ("함수가 없음", fake_ctypes(no_function=True)[0])):
            with self.subTest(label=label):
                self.assertIsNone(ask_windows(module))
        broken = types.ModuleType("ctypes")

        def load(name, use_last_error=False):
            raise OSError("kernel32 를 못 연다")
        broken.WinDLL = load
        self.assertIsNone(ask_windows(broken))
        self.assertIsNone(ask_windows(types.ModuleType("ctypes")), "WinDLL 이 아예 없는 ctypes(윈도가 아닌 파이썬)")

    def test_off_windows_ctypes_is_never_imported_or_touched(self):
        touched = []

        class Tripwire(types.ModuleType):
            def __getattr__(self, name):
                touched.append(name)
                raise AssertionError("윈도가 아닌데 ctypes 를 건드렸다: " + name)
        with mock.patch.object(os, "name", "posix"), mock.patch.dict(sys.modules, {"ctypes": Tripwire("ctypes")}):
            self.assertIsNone(winroot.windows_directory())
        self.assertEqual(touched, [])

    @unittest.skipUnless(os.name == "nt", "윈도 API 는 윈도 전용이다")
    def test_the_real_call_gives_an_existing_windows_folder_with_the_system_tool_in_it(self):
        value = winroot.windows_directory()
        self.assertTrue(value and ntpath.isabs(value) and winroot.is_drive_absolute(value), value)
        self.assertTrue(os.path.isfile(ntpath.join(value, "System32", "taskkill.exe")), "윈도가 알려 준 폴더에 시스템 taskkill 이 있다")


class ShapeAndSameFolderTest(unittest.TestCase):
    def test_only_a_drive_letter_absolute_path_counts(self):
        good = ("C:" + B + "Windows", "c:/windows", "Z:" + B, "D:/")
        bad = ("C:Windows", "C:", "Windows", ".", "..", "", " ", "/usr/bin", B + "Windows", B * 2 + "server" + B + "share" + B + "Windows", B * 2 + "?" + B + "C:" + B + "Windows", B * 2 + "." + B + "C:", "1:" + B + "x", "CC:" + B + "x",
               None, 5, 0, ["C:" + B + "Windows"], ("C:" + B + "Windows").encode("ascii"))
        for value in good:
            with self.subTest(value=value):
                self.assertTrue(winroot.is_drive_absolute(value))
        for value in bad:
            with self.subTest(value=repr(value)):
                self.assertFalse(winroot.is_drive_absolute(value))

    def test_the_same_folder_is_recognized_through_case_separators_trailing_separator_and_dot_dot(self):
        for first, second in (("C:" + B + "Windows", "c:/windows"), ("C:" + B + "WINDOWS" + B, "C:" + B + "Windows"), ("C:/Windows/", "C:" + B + "Windows"), ("C:" + B + "Windows" + B + "System32" + B + "..", "C:" + B + "Windows"),
                              ("C:" + B + "Windows" + B + B + "Temp" + B + ".." + B, "C:" + B + "Windows")):
            with self.subTest(first=first, second=second):
                self.assertTrue(winroot.same_folder(first, second))

    def test_a_different_folder_is_never_taken_for_the_same_one(self):
        for first, second in (("D:" + B + "evil", "C:" + B + "Windows"), ("C:" + B + "Windows" + B + ".." + B + "Users", "C:" + B + "Windows"), ("C:" + B + "WindowsX", "C:" + B + "Windows"), ("C:" + B + "Windows" + B + "System32", "C:" + B + "Windows"),
                              ("C:Windows", "C:" + B + "Windows"), (B * 2 + "server" + B + "Windows", "C:" + B + "Windows"), ("C:" + B + "Windows.", "C:" + B + "Windows"), ("", "C:" + B + "Windows")):
            with self.subTest(first=first, second=second):
                self.assertFalse(winroot.same_folder(first, second))


class SourceShapeTest(unittest.TestCase):
    """이 파일이 윈도 API 에 닿는 길을 닫힌 집합으로 못박는다 — 새 길이 생기면 빨개져 사람이 그 길이 읽기 전용인지 본다."""

    def setUp(self):
        self.text = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def function(self, name):
        return next(node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name)

    def test_only_two_standard_modules_are_imported_at_the_top_and_ctypes_only_inside_the_one_function_after_the_windows_guard(self):
        top = [alias.name for node in self.tree.body if isinstance(node, ast.Import) for alias in node.names]
        froms = [node.module for node in self.tree.body if isinstance(node, ast.ImportFrom)]
        self.assertEqual((sorted(top), froms), (["ntpath", "os"], ["__future__"]))
        inside = [(function.name, node.lineno) for function in ast.walk(self.tree) if isinstance(function, ast.FunctionDef) for node in ast.walk(function) if isinstance(node, ast.Import) and any(alias.name == "ctypes" for alias in node.names)]
        self.assertEqual([name for name, _line in inside], ["windows_directory"])
        body = [node for node in self.function("windows_directory").body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        self.assertEqual(ast.unparse(body[0]), "if os.name != 'nt':\n    return None", "첫 문장이 윈도 검사다 — ctypes 는 그 뒤에서만")
        self.assertIsInstance(body[1], ast.Try)

    def test_the_names_used_from_the_windows_api_are_exactly_the_one_read_only_question(self):
        names = {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)}
        self.assertEqual(names, {"splitdrive", "normcase", "normpath", "isascii", "isalpha", "name", "WinDLL", "GetSystemWindowsDirectoryW", "restype", "argtypes", "c_uint32", "c_wchar_p", "create_unicode_buffer", "value"})
        self.assertEqual(self.text.count("kernel32"), 1)
        calls = {ast.unparse(node.func) for node in ast.walk(self.tree) if isinstance(node, ast.Call)}
        for word in ("open", "exec", "eval", "system", "popen", "Popen", "run", "call", "write", "remove", "unlink", "connect", "socket", "getattr", "__import__"):
            self.assertFalse([name for name in calls if name.rsplit(".", 1)[-1] == word], word)

    def test_the_text_has_no_tilde_and_no_web_address(self):
        self.assertNotIn(chr(126), self.text)
        self.assertNotIn("http", self.text.lower())


if __name__ == "__main__":
    unittest.main()
