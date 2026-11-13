"""단일 실행 장치(`ui/single_instance.py`, SINGLEWIN) 시험 — 같은 윈도 로그온·같은 데이터 폴더로 앱을 두 번 열면 새 창을 만들지 않고 열린 창을 앞으로 가져온 뒤 조용히 끝난다.

지키는 것:
  1) 이름 만들기(순수 — 어느 운영체제에서든 같다): 접두는 세션별 `Local` 이름 공간이고, 이름은 해결한 데이터 폴더(소문자·구분자 맞춤)의 SHA-256 앞 16자리라 폴더가 다르면 이름이 다르고 적는 방식(대소문자·슬래시·끝 구분자·`..`)이
     달라도 같은 폴더면 같다. 폴더 해석은 `Workspace.resolve` 와 같은 우선순위다(`--data-dir` > 환경 변수 > 기본 위치).
  2) 판정 논리(가짜 윈도 층 — CI 윈도·리눅스 모두): 첫 실행은 뮤텍스를 만들고 **핸들을 모듈 전역에 쥔다**(가비지 수집으로 풀리지 않는다), 이미 있으면(오류 183) 새 창 없이 `False`, 같은 프로세스가 쥔 이름은 통과,
     엉뚱한 창(같은 제목의 다른 프로그램·다른 제목의 같은 프로그램·소유 창·보이지 않는 창·내 프로세스·경로를 모르는 프로세스)은 건드리지 않고, 창 제목은 앱의 실제 상수(`T["window_title"]`)를 읽고, 첫 창이 뜨는 중이면 기다리고,
     찾지 못하거나 응답이 없으면 쉬운 한국어 안내 상자, 앞으로 못 오면 작업 표시줄 깜박임, 어떤 호출이 예외를 던져도 죽지 않고(판정이 안 서면 장치를 끈 채 통과) 새 창은 열지 않는다. 비윈도·`--sample` 은 아무것도 하지 않는다.
  3) `launcher.main` 이 맨 앞쪽(PySide6 확인 뒤·Qt 를 불러오기 전)에서 부르고 `False` 이면 새 창 없이 0 으로 끝난다. 이 장치를 부르는 곳은 `launcher.main` 한 곳뿐이다(`--selftest`·명령줄·묶음 시작 파일은 안 부른다).
  4) 소스 규칙: Qt·네트워크·하위 프로세스·파일 쓰기·출력이 없고 ctypes 는 윈도 길 안에서만 가져온다.
  5) (윈도 전용) 진짜 `CreateMutexW` 두 번째가 183·정리 뒤 다시 첫 실행·가비지 수집 뒤에도 쥐고 있음, **진짜 프로세스 둘**이 같은 데이터 폴더로 열면 둘째만 막히고 다른 폴더·첫 프로세스가 끝난 뒤에는 열린다.
  6) 문서(시험지 1-4·결정·변경 이력·문제 해결)가 쉬운 말로 이 동작을 적고 기존 번호를 바꾸지 않는다.
"""
import ast
import gc
import hashlib
import io
import ntpath
import os
import queue
import re
import subprocess
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import secret_support as sec  # noqa: E402
from chanceblog_desktop.ui import launcher  # noqa: E402
from chanceblog_desktop.ui import single_instance as si  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

UI = ROOT / "src" / "chanceblog_desktop" / "ui"
SRC = ROOT / "src" / "chanceblog_desktop"
CHILD = Path(__file__).resolve().parent / "single_instance_child.py"
WINDOWS = sys.platform == "win32"
W = chr(92)                                                      # 역슬래시 — 소스에는 글자로 적지 않는다
FOLDER = "C:/Temp/singlewin/folder-a"
OWN_PID = os.getpid()
OTHER_PID = OWN_PID + 7
OWN_IMAGE = "C:/Apps/ChanceBlog/ChanceBlogDesktop.exe"
OTHER_IMAGE = "C:/Windows/explorer.exe"
TITLE = T["window_title"]


def win(hwnd, title=None, pid=OTHER_PID, owner=0, visible=True):
    return (hwnd, TITLE if title is None else title, pid, owner, visible)


class Clock:
    """가짜 시계 — `sleep` 이 시간을 앞으로 돌려 시험이 기다리지 않는다."""

    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Handle(int):
    """진짜 윈도 핸들 래퍼(pywin32 의 PyHANDLE 처럼)와 같이 **가비지 수집 때 스스로 닫히는** 가짜 핸들 — 지역 변수에만 둔 핸들이 반환 즉시 풀려 장치가 무력해지는 함정을 그대로 흉내 낸다."""

    kernel = None

    def __del__(self):
        if self.kernel is not None:
            self.kernel.close(self)


class FakeKernel:
    """커널의 이름 있는 뮤텍스 표 — 열린 핸들이 하나도 없어지면 이름이 사라진다(진짜 윈도와 같다). 프로세스 여럿이 같은 표를 본다. 이미 닫은 핸들을 또 닫아도 한 번만 센다."""

    def __init__(self):
        self.counts, self.owner, self.last, self.elsewhere = {}, {}, 100, []

    def create(self, name):
        existed = self.counts.get(name, 0) > 0
        self.last += 1
        handle = Handle(self.last)
        handle.kernel = self
        self.counts[name] = self.counts.get(name, 0) + 1
        self.owner[int(handle)] = name
        return handle, (si.ERROR_ALREADY_EXISTS if existed else 0)

    def close(self, handle):
        name = self.owner.pop(int(handle), None)
        if name is not None:
            self.counts[name] -= 1

    def open_count(self, name):
        return self.counts.get(name, 0)


class FakeApi:
    """윈도 호출 층의 가짜 — 모든 호출을 `calls` 에 기록하고, 창 목록·응답·앞으로 가는지·예외를 시험이 정한다."""

    ALL_AFTER_CREATE = ("close_handle", "image_path", "top_windows", "is_hung", "is_iconic", "restore", "activate", "foreground", "flash", "message_box")

    def __init__(self, kernel=None, *, scripted=(), images=None, iconic=False, hung=False, foreground_ok=True, flash_ok=True, restore_works=True, raises=(), no_handle=False, raise_on_create=(), on_poll=None,
                 no_handle_after=None):
        self.kernel = kernel if kernel is not None else FakeKernel()
        self.scripted = list(scripted)
        self.images = {OWN_PID: OWN_IMAGE, OTHER_PID: OWN_IMAGE} if images is None else dict(images)
        self.iconic, self.hung, self.restore_works = iconic, hung, restore_works
        self.foreground_ok, self.flash_ok = foreground_ok, flash_ok
        self.raises, self.no_handle = set(raises), no_handle
        self.raise_on_create, self.on_poll = set(raise_on_create), on_poll                 # 몇 번째 `create_mutex`(1부터)가 예외를 던지는지 · 창 목록을 읽을 때마다 부르는 함수(몇 번째 읽기인지 받는다)
        self.no_handle_after = no_handle_after                                              # 이 횟수 뒤의 `create_mutex` 는 핸들을 주지 못한다
        self.calls, self.polls, self.front = [], 0, 5

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if name in self.raises:
            raise RuntimeError("가짜 오류 " + name)

    def made(self, name):
        return [call for call in self.calls if call[0] == name]

    def create_mutex(self, name):
        self._call("create_mutex", name)
        if len(self.made("create_mutex")) in self.raise_on_create:
            raise RuntimeError("가짜 오류 create_mutex 둘째")
        if self.no_handle or (self.no_handle_after is not None and len(self.made("create_mutex")) > self.no_handle_after):
            return None, 5
        return self.kernel.create(name)

    def close_handle(self, handle):
        self._call("close_handle", handle)
        self.kernel.close(handle)

    def image_path(self, pid):
        self._call("image_path", pid)
        return self.images.get(pid)

    def top_windows(self):
        self._call("top_windows")
        index, self.polls = self.polls, self.polls + 1
        if self.on_poll is not None:
            self.on_poll(index)
        return list(self.scripted[min(index, len(self.scripted) - 1)]) if self.scripted else []

    def is_hung(self, hwnd):
        self._call("is_hung", hwnd)
        return self.hung

    def is_iconic(self, hwnd):
        self._call("is_iconic", hwnd)
        return self.iconic

    def restore(self, hwnd):
        self._call("restore", hwnd)
        if self.restore_works:
            self.iconic = False
        return True

    def activate(self, hwnd):
        self._call("activate", hwnd)
        if self.foreground_ok:
            self.front = hwnd
        return self.foreground_ok

    def foreground(self):
        self._call("foreground")
        return self.front

    def flash(self, hwnd):
        self._call("flash", hwnd)
        return self.flash_ok

    def message_box(self, title, text):
        self._call("message_box", title, text)


def held_elsewhere(kernel, folder=FOLDER):
    """다른 프로세스가 이미 이 데이터 폴더의 뮤텍스를 쥔 상태를 만든다(이 프로세스의 `_HELD` 에는 없다)."""
    name = si.mutex_name(si.resolve_folder(folder, {}))
    handle, _error = kernel.create(name)
    kernel.elsewhere.append(handle)                                  # 그 프로세스가 쥐고 있다 — 시험이 놓기 전에는 가비지 수집으로 풀리지 않는다
    return name


def run_claim(api, folder=FOLDER, clock=None, **kwargs):
    clock = clock or Clock()
    result = si.claim(folder, env={}, platform="win32", api=api, sleep=clock.sleep, monotonic=clock.monotonic, **kwargs)
    return result, clock


BOXES = []                                                       # 이 시험 모듈이 진짜 안내 상자를 띄우려 한 글 — 늘 비어 있어야 한다(진짜 상자는 모달이라 사람이 누르기 전에는 시험이 멈춘다)
REAL_MESSAGE_BOX = si.Win32Api.message_box                       # `setUpModule` 이 클래스의 것을 기록 함수로 바꾸기 전의 진짜 함수 — 호출 층 인자 시험만 가짜 DLL 위에서 이것을 부른다


def setUpModule():
    """이 모듈 안의 어떤 길도 진짜 안내 상자(`MessageBoxW`)를 띄우지 못하게 한다 — 장치가 잘못 '이미 열려 있음' 으로 판정해도(변이·버그) 시험이 사람의 클릭을 기다리며 멈추지 않게 하는 마지막 그물이다."""
    patcher = mock.patch.object(si.Win32Api, "message_box", lambda self, title, text: BOXES.append(text))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class Isolated(unittest.TestCase):
    """각 시험은 이 프로세스가 쥔 뮤텍스가 없는 상태에서 시작하고 끝난다."""

    def setUp(self):
        si.release_all()
        self.addCleanup(si.release_all)


# ---- 1) 이름 만들기 --------------------------------------------------------------------------------------------------------------------------

class NameTest(unittest.TestCase):
    def test_the_prefix_is_the_per_session_local_namespace_never_global(self):
        name = si.mutex_name(FOLDER)
        self.assertTrue(name.startswith("Local" + W + "ChanceBlogDesktop-"), name)
        self.assertEqual(si.MUTEX_PREFIX, "Local" + W + "ChanceBlogDesktop-")
        self.assertNotIn("Global", name)
        self.assertRegex(name[len(si.MUTEX_PREFIX):], r"^[0-9a-f]{16}$")
        self.assertEqual(len(name), len(si.MUTEX_PREFIX) + 16)

    def test_the_suffix_is_the_first_16_hex_digits_of_sha256_of_the_normalized_folder(self):
        for folder in (FOLDER, "C:/Users/내 이름/AppData/Local/ChanceblogDesktop", "D:/데이터 폴더"):
            normalized = ntpath.normcase(ntpath.normpath(folder))
            expected = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
            self.assertEqual(si.mutex_name(folder), si.MUTEX_PREFIX + expected, folder)

    def test_the_name_of_a_known_folder_is_pinned_so_a_silent_change_of_the_derivation_is_noticed(self):
        """이름 만드는 방식(접두·해시·정규화)이 슬쩍 바뀌면 서로 다른 버전의 앱이 같은 데이터 폴더를 쓰면서도 서로를 못 알아본다 — 알려진 폴더의 이름을 못박는다(글자만 쓰는 순수 계산이라 운영체제와 무관하다)."""
        expected = "Local" + W + "ChanceBlogDesktop-a8fd45534bd73f57"
        self.assertEqual(si.mutex_name("C:/Users/Example/AppData/Local/ChanceblogDesktop"), expected)
        self.assertEqual(si.mutex_name("c:" + W + "USERS" + W + "example" + W + "appdata" + W + "local" + W + "chanceblogdesktop" + W), expected)

    def test_a_different_data_folder_gives_a_different_name(self):
        names = {si.mutex_name(folder) for folder in ("C:/Temp/a", "C:/Temp/b", "C:/Temp/a/b", "D:/Temp/a", "C:/Temp/ab", "C:/Temp/A2")}
        self.assertEqual(len(names), 6)

    def test_the_same_folder_written_differently_gives_the_same_name(self):
        base = si.mutex_name("C:/Users/Me/Data")
        for spelled in ("c:/users/me/data", "C:/USERS/ME/DATA", "C:" + W + "Users" + W + "Me" + W + "Data", "c:" + W + "USERS" + W + "me" + W + "data" + W, "C:/Users/Me/Data/",
                        "C:/Users//Me/Data", "C:/Users/Me/./Data", "C:/Users/Me/Other/../Data", "C:/Users/Me" + W + "Data"):
            with self.subTest(spelled=spelled):
                self.assertEqual(si.mutex_name(spelled), base)

    def test_korean_folder_names_are_deterministic_and_distinct(self):
        first, second = si.mutex_name("C:/데이터/가"), si.mutex_name("C:/데이터/나")
        self.assertEqual(first, si.mutex_name("c:/데이터/가"))
        self.assertNotEqual(first, second)

    def test_the_name_does_not_depend_on_the_process_or_the_time(self):
        with mock.patch.object(os, "getpid", return_value=1), mock.patch("time.time", return_value=1.0):
            first = si.mutex_name(FOLDER)
        with mock.patch.object(os, "getpid", return_value=2), mock.patch("time.time", return_value=2.0):
            self.assertEqual(si.mutex_name(FOLDER), first)

    def test_the_already_exists_error_number_is_the_windows_one(self):
        self.assertEqual(si.ERROR_ALREADY_EXISTS, 183)


class ResolveFolderTest(unittest.TestCase):
    def test_the_argument_beats_the_environment_variable_beats_the_default(self):
        env = {si.ENV_DATA_DIR: "C:/FromEnv", "LOCALAPPDATA": "C:/Local"}
        self.assertEqual(si.resolve_folder("C:/FromArg", env), os.path.realpath("C:/FromArg"))
        self.assertEqual(si.resolve_folder(None, env), os.path.realpath("C:/FromEnv"))
        self.assertEqual(si.resolve_folder("", env), os.path.realpath("C:/FromEnv"), "빈 인자는 안 준 것과 같다(`Workspace.resolve` 와 같다)")
        self.assertEqual(si.resolve_folder(None, {"LOCALAPPDATA": "C:/Local"}), os.path.realpath(ntpath.join("C:/Local", si.APP_DIR_NAME)))

    def test_without_local_app_data_the_default_is_under_the_user_profile(self):
        folder = si.resolve_folder(None, {})
        self.assertTrue(folder.endswith(si.APP_DIR_NAME), folder)
        self.assertIn("AppData", folder)

    def test_the_constants_are_the_ones_of_the_service_layer(self):
        from chanceblog_desktop.service import context
        self.assertEqual(si.APP_DIR_NAME, context.APP_DIR_NAME)
        self.assertEqual(si.ENV_DATA_DIR, context.ENV_DATA_DIR)

    def test_the_folder_is_the_one_the_service_layer_resolves(self):
        """데이터 폴더 해석이 어긋나면 같은 폴더를 쓰는 두 창이 다른 이름을 얻는다 — `Workspace.resolve` 와 같은 폴더인지 맞춰 본다."""
        import tempfile
        from chanceblog_desktop.service.context import Workspace
        with tempfile.TemporaryDirectory() as tmp:
            arg, from_env = os.path.join(tmp, "arg"), os.path.join(tmp, "env")
            for data_dir, env in ((arg, {}), (None, {si.ENV_DATA_DIR: from_env}), (arg, {si.ENV_DATA_DIR: from_env})):
                with self.subTest(data_dir=data_dir, env=env):
                    expected = os.path.realpath(str(Workspace.resolve(data_dir, env=env).root))
                    self.assertEqual(si.resolve_folder(data_dir, env), expected)
            if WINDOWS:
                env = {"LOCALAPPDATA": tmp}
                self.assertEqual(si.resolve_folder(None, env), os.path.realpath(str(Workspace.resolve(None, env=env).root)))

    def test_resolving_creates_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "not-there", "deeper")
            si.resolve_folder(target, {})
            si.mutex_name(si.resolve_folder(target, {}))
            self.assertEqual(os.listdir(tmp), [])


# ---- 1-2) 윈도 호출 층의 인자·순서(가짜 ctypes·가짜 DLL — 진짜 윈도 없이 CI 리눅스에서도 돈다) ---------------------------------------------------------------------

class Recorder:
    """부른 이름과 인자를 `log` 에 적고, 정해 준 결과(값 또는 함수)를 돌려주는 가짜 DLL."""

    def __init__(self, log=None, **results):
        self.log = [] if log is None else log
        self.results = results

    def __getattr__(self, name):
        def call(*args):
            self.log.append((name, *args))
            result = self.results.get(name)
            return result(*args) if callable(result) else result
        return call


class FakeBuffer:
    def __init__(self, value=""):
        self.value = value


class FakeCtypes:
    def __init__(self, log=None, last_error=183):
        self.log, self.last_error = [] if log is None else log, last_error

    def set_last_error(self, value):
        self.log.append(("set", value))

    def get_last_error(self):
        self.log.append(("get",))
        return self.last_error

    def create_unicode_buffer(self, size):
        return FakeBuffer("C:/x/app.exe")

    def byref(self, value):
        return value

    def sizeof(self, cls):
        return 20


class FakeWintypes:
    class DWORD:
        def __init__(self, value=0):
            self.value = value


class FakeFlashInfo:
    def __init__(self, *args):
        self.args = args


class CallLayerProtocolTest(unittest.TestCase):
    """`Win32Api` 가 윈도에 넘기는 인자·호출 순서 — 진짜 DLL 을 열지 않고(`__init__` 을 건너뛴다) 가짜 ctypes·DLL 로 확인한다. 글자 순서(본문·제목)·상수·핸들 닫기처럼 눈으로는 안 보이는 것을 못박는다."""

    def layer(self, log=None, ctypes_=None, kernel32=None, user32=None):
        api = si.Win32Api.__new__(si.Win32Api)
        api._ctypes = ctypes_ if ctypes_ is not None else FakeCtypes(log)
        api._wintypes = FakeWintypes
        api._kernel32, api._user32 = kernel32, user32
        api._enum_proc = lambda function: function
        api._flash_info = FakeFlashInfo
        return api

    def test_create_mutex_clears_the_last_error_first_calls_with_no_security_and_no_owner_and_reads_the_error_right_after(self):
        log = []
        name = "Local" + W + "x"
        api = self.layer(log, kernel32=Recorder(log, CreateMutexW=lambda *args: 77))
        self.assertEqual(api.create_mutex(name), (77, 183))
        self.assertEqual(log, [("set", 0), ("CreateMutexW", None, False, name), ("get",)], "호출 전에 비우고 호출 바로 뒤에 읽는다 — 앞선 호출의 찌꺼기가 '이미 있음' 으로 읽히지 않게")

    def test_create_mutex_gives_no_handle_when_windows_gives_none_and_keeps_the_error_number(self):
        api = self.layer(ctypes_=FakeCtypes(last_error=5), kernel32=Recorder(CreateMutexW=lambda *args: 0))
        self.assertEqual(api.create_mutex("n"), (None, 5))
        api = self.layer(ctypes_=FakeCtypes(last_error=5), kernel32=Recorder(CreateMutexW=lambda *args: None))
        self.assertEqual(api.create_mutex("n"), (None, 5))

    def test_the_executable_path_query_asks_for_the_least_privilege_and_always_closes_the_process_handle(self):
        for query_works, expected in ((True, "C:/x/app.exe"), (False, None)):
            with self.subTest(query_works=query_works):
                kernel = Recorder(OpenProcess=lambda *args: 99, QueryFullProcessImageNameW=lambda *args: query_works)
                api = self.layer(kernel32=kernel)
                self.assertEqual(api.image_path(4321), expected)
                self.assertEqual(kernel.log[0], ("OpenProcess", 0x1000, False, 4321), "읽기 제한 권한(PROCESS_QUERY_LIMITED_INFORMATION)만 요청한다")
                self.assertEqual([entry for entry in kernel.log if entry[0] == "CloseHandle"], [("CloseHandle", 99)], "질의가 실패해도 프로세스 핸들은 닫는다")

    def test_a_process_that_cannot_be_opened_has_no_path_and_nothing_is_closed(self):
        kernel = Recorder(OpenProcess=lambda *args: 0)
        self.assertIsNone(self.layer(kernel32=kernel).image_path(1))
        self.assertEqual([entry[0] for entry in kernel.log], ["OpenProcess"])

    def test_the_window_list_keeps_only_visible_windows_with_their_owner_and_survives_a_window_that_fails_to_read(self):
        windows = {1: ("앱", 10, 0, True), 2: ("숨김", 11, 0, False), 3: ("대화상자", 12, 99, True), 4: ("", 13, 0, True), 5: ("고장", 14, 0, True)}

        def text(hwnd, buffer, size):
            if hwnd == 5:
                raise OSError("읽기 실패")
            buffer.value = windows[hwnd][0]
            return len(windows[hwnd][0])

        def pid_of(hwnd, pid):
            pid.value = windows[hwnd][1]
            return 1
        user32 = Recorder(IsWindowVisible=lambda hwnd: windows[hwnd][3], GetWindowTextW=text, GetWindowThreadProcessId=pid_of, GetWindow=lambda hwnd, kind: windows[hwnd][2] or None,
                          EnumWindows=lambda proc, parameter: [proc(hwnd, 0) for hwnd in windows] and 1)
        found = self.layer(user32=user32).top_windows()
        self.assertEqual(found, [(1, "앱", 10, 0, True), (3, "대화상자", 12, 99, True), (4, "", 13, 0, True)], "숨김은 빼고, 소유 창 번호(없으면 0)·빈 제목을 그대로, 읽다 실패한 창만 건너뛴다")
        owner_calls = [entry for entry in user32.log if entry[0] == "GetWindow"]
        self.assertTrue(owner_calls and all(entry[2] == 4 for entry in owner_calls), "GW_OWNER(4) 로 소유 창을 묻는다")

    def test_the_action_calls_pass_the_expected_constants_and_the_text_goes_before_the_title_in_the_message_box(self):
        user32 = Recorder(ShowWindowAsync=lambda *args: 1, BringWindowToTop=lambda *args: 1, SetForegroundWindow=lambda *args: 1, FlashWindowEx=lambda *args: 1, MessageBoxW=lambda *args: 1,
                          IsHungAppWindow=lambda *args: 1, IsIconic=lambda *args: 0, GetForegroundWindow=lambda *args: 0)
        api = self.layer(user32=user32)
        self.assertIs(api.restore(500), True)
        self.assertIs(api.activate(500), True)
        self.assertIs(api.flash(500), True)
        REAL_MESSAGE_BOX(api, "제목", "본문")                                                         # 가짜 DLL 위에서만 — 진짜 상자는 뜨지 않는다
        self.assertIs(api.is_hung(500), True)
        self.assertIs(api.is_iconic(500), False)
        self.assertEqual(api.foreground(), 0)
        by_name = {entry[0]: entry[1:] for entry in user32.log}
        self.assertEqual(by_name["ShowWindowAsync"], (500, 9), "SW_RESTORE")
        self.assertEqual([entry[0] for entry in user32.log if entry[0] in ("BringWindowToTop", "SetForegroundWindow")], ["BringWindowToTop", "SetForegroundWindow"])
        self.assertEqual(by_name["FlashWindowEx"][0].args, (20, 500, 0xF, 0, 0), "제목과 작업 표시줄 단추를 창이 앞으로 올 때까지 깜박인다(FLASHW_ALL | FLASHW_TIMERNOFG)")
        self.assertEqual(by_name["MessageBoxW"], (None, "본문", "제목", 0x00010040), "MessageBoxW 의 둘째 인자가 본문, 셋째가 제목이다 — 확인 단추 하나·정보 그림·앞으로")


# ---- 2) 판정 논리 ------------------------------------------------------------------------------------------------------------------------------

class FirstRunTest(Isolated):
    def test_the_first_run_creates_the_named_mutex_keeps_its_handle_and_may_open_the_window(self):
        api = FakeApi()
        result, clock = run_claim(api)
        name = si.mutex_name(si.resolve_folder(FOLDER, {}))
        self.assertIs(result, True)
        self.assertEqual(api.made("create_mutex"), [("create_mutex", name)])
        self.assertEqual(api.kernel.open_count(name), 1)
        self.assertEqual(si.last_note(), "first")
        for untouched in ("top_windows", "image_path", "restore", "activate", "flash", "message_box", "close_handle"):
            self.assertEqual(api.made(untouched), [], untouched)
        self.assertEqual(clock.sleeps, [])

    def test_the_handle_is_kept_in_a_module_global_so_garbage_collection_cannot_release_it(self):
        api = FakeApi()
        run_claim(api)
        name = si.mutex_name(si.resolve_folder(FOLDER, {}))
        gc.collect()
        self.assertEqual(api.made("close_handle"), [], "핸들을 지역 변수에만 두면 반환 즉시 풀려 장치가 무력해진다")
        self.assertIn(name, si._HELD)
        self.assertEqual(api.kernel.open_count(name), 1)
        si.release_all()
        self.assertEqual(len(api.made("close_handle")), 1)
        self.assertEqual(api.kernel.open_count(name), 0)
        self.assertEqual(si._HELD, {})

    def test_the_same_process_asking_again_for_the_same_folder_passes_without_any_os_call(self):
        api = FakeApi()
        run_claim(api)
        again = FakeApi(api.kernel)
        result, _clock = run_claim(again)
        self.assertIs(result, True)
        self.assertEqual(again.calls, [])
        self.assertEqual(si.last_note(), "held")
        self.assertEqual(api.kernel.open_count(si.mutex_name(si.resolve_folder(FOLDER, {}))), 1)

    def test_a_different_data_folder_is_independent_and_both_stay_held(self):
        api = FakeApi()
        first, _ = run_claim(api, "C:/Temp/singlewin/folder-a")
        second, _ = run_claim(api, "C:/Temp/singlewin/folder-b")
        self.assertEqual((first, second), (True, True))
        self.assertEqual(len(si._HELD), 2)
        self.assertEqual(len(api.made("create_mutex")), 2)

    def test_after_release_the_same_folder_can_be_claimed_again(self):
        api = FakeApi()
        run_claim(api)
        si.release_all()
        result, _ = run_claim(api)
        self.assertIs(result, True)
        self.assertEqual(si.last_note(), "first")
        self.assertEqual(api.kernel.open_count(si.mutex_name(si.resolve_folder(FOLDER, {}))), 1)

    def test_the_environment_variable_folder_decides_the_name_when_there_is_no_argument(self):
        api = FakeApi()
        result = si.claim(None, env={si.ENV_DATA_DIR: "C:/FromEnv/data"}, platform="win32", api=api)
        self.assertIs(result, True)
        self.assertEqual(api.made("create_mutex"), [("create_mutex", si.mutex_name(si.resolve_folder("C:/FromEnv/data", {})))])

    def test_the_error_number_decides_whether_someone_else_is_open(self):
        for error, expected in ((0, True), (si.ERROR_ALREADY_EXISTS, False), (997, True)):
            with self.subTest(error=error):
                si.release_all()
                api = FakeApi(scripted=[[win(500)]])
                with mock.patch.object(api, "create_mutex", return_value=(7, error)):
                    result, _ = run_claim(api)
                self.assertIs(result, expected)
                si.release_all()


class DeviceOffTest(Isolated):
    def test_a_non_windows_system_passes_without_touching_anything(self):
        class Forbidden:
            def __getattr__(self, name):
                raise AssertionError("윈도가 아니면 호출 층을 쓰지 않는다: " + name)
        for platform in ("linux", "darwin", "cygwin"):
            result = si.claim(FOLDER, env={}, platform=platform, api=Forbidden())
            self.assertIs(result, True)
            self.assertEqual(si.last_note(), "not_windows")
        self.assertEqual(si._HELD, {})

    def test_the_sample_screen_never_takes_the_mutex_even_when_someone_else_holds_it(self):
        api = FakeApi()
        held_elsewhere(api.kernel)
        result, _ = run_claim(api, sample=True)
        self.assertIs(result, True)
        self.assertEqual(api.calls, [])
        self.assertEqual(si.last_note(), "sample")

    def test_the_real_call_layer_is_not_built_off_windows(self):
        with mock.patch.dict(si._state, {"api": None}):
            self.assertIsNone(si.default_api("linux"))
            self.assertIsNone(si.default_api("darwin"))

    def test_a_call_layer_that_cannot_be_built_switches_the_device_off(self):
        with mock.patch.dict(si._state, {"api": None}), mock.patch.object(si, "Win32Api", side_effect=OSError("dll")):
            self.assertIsNone(si.default_api("win32"))
            self.assertEqual(si.last_note(), "api:OSError")
            self.assertIs(si.claim(FOLDER, env={}, platform="win32"), True)

    def test_a_mutex_that_cannot_be_created_switches_the_device_off_and_does_not_block_the_app(self):
        api = FakeApi(raises={"create_mutex"})
        result, _ = run_claim(api)
        self.assertIs(result, True)
        self.assertEqual(si.last_note(), "create_mutex:RuntimeError")
        self.assertEqual(si._HELD, {})
        api = FakeApi(no_handle=True)
        result, _ = run_claim(api)
        self.assertIs(result, True)
        self.assertEqual(si.last_note(), "create_mutex_failed:5")
        for untouched in ("top_windows", "message_box", "restore", "activate", "flash"):
            self.assertEqual(api.made(untouched), [], untouched)

    def test_an_unexpected_error_inside_the_decision_switches_the_device_off(self):
        with mock.patch.object(si, "mutex_name", side_effect=ValueError("x")):
            self.assertIs(si.claim(FOLDER, env={}, platform="win32", api=FakeApi()), True)
        self.assertEqual(si.last_note(), "claim:ValueError")


class AlreadyOpenTest(Isolated):
    def setUp(self):
        super().setUp()
        self.kernel = FakeKernel()
        self.name = held_elsewhere(self.kernel)

    def api(self, **kwargs):
        return FakeApi(self.kernel, **{"scripted": [[win(500)]], **kwargs})

    def test_a_second_run_gets_no_window_and_closes_only_its_own_copy_of_the_handle(self):
        api = self.api(iconic=True)
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(len(api.made("close_handle")), 1)
        self.assertEqual(self.kernel.open_count(self.name), 1, "먼저 연 프로세스의 뮤텍스는 그대로다")
        self.assertEqual(si._HELD, {}, "둘째 실행은 아무것도 쥐지 않는다")

    def test_the_open_window_is_restored_when_minimized_and_brought_to_the_front_without_any_box(self):
        api = self.api(iconic=True)
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(api.made("restore"), [("restore", 500)])
        self.assertEqual(api.made("activate"), [("activate", 500)])
        self.assertEqual(api.made("message_box"), [], "앞으로 가져왔으면 조용히 끝난다")
        self.assertEqual(si.last_note(), "front")

    def test_a_window_that_is_not_minimized_is_not_restored_so_a_maximized_window_stays_maximized(self):
        api = self.api(iconic=False)
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(api.made("restore"), [])
        self.assertEqual(api.made("activate"), [("activate", 500)])

    def test_a_window_that_does_not_come_back_up_is_waited_for_one_second_at_most(self):
        api = self.api(iconic=True, restore_works=False)
        result, clock = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(clock.sleeps, [si.RESTORE_POLL] * si.RESTORE_TRIES)
        self.assertLessEqual(sum(clock.sleeps), 1.01)

    def test_the_first_window_that_is_still_starting_is_waited_for(self):
        api = self.api(scripted=[[], [], [win(500)]])
        result, clock = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(api.polls, 3)
        self.assertEqual(clock.sleeps, [si.POLL_SECONDS, si.POLL_SECONDS])
        self.assertEqual(api.made("message_box"), [])
        self.assertEqual(api.made("activate"), [("activate", 500)])

    def test_when_no_window_ever_appears_the_easy_korean_box_is_shown_once_after_the_wait(self):
        api = self.api(scripted=[[]])
        result, clock = run_claim(api)
        self.assertIs(result, False)
        boxes = api.made("message_box")
        self.assertEqual(boxes, [("message_box", TITLE, si.ALREADY_OPEN_TEXT.format(name=TITLE))])
        self.assertGreaterEqual(clock.now, si.WAIT_SECONDS)
        self.assertLess(clock.now, si.WAIT_SECONDS + si.POLL_SECONDS * 2)
        self.assertEqual(si.last_note(), "no_window")
        for untouched in ("restore", "activate", "flash"):
            self.assertEqual(api.made(untouched), [], untouched)

    def test_an_unresponsive_window_is_not_touched_and_the_box_explains(self):
        api = self.api(hung=True, iconic=True)
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(len(api.made("message_box")), 1)
        for untouched in ("restore", "activate", "flash"):
            self.assertEqual(api.made(untouched), [], untouched)
        self.assertEqual(si.last_note(), "not_responding")

    def test_when_windows_refuses_to_bring_it_forward_the_taskbar_button_flashes_instead_of_a_box(self):
        api = self.api(foreground_ok=False)
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(api.made("flash"), [("flash", 500)])
        self.assertEqual(api.made("message_box"), [])
        self.assertEqual(si.last_note(), "flashed")

    def test_when_it_can_neither_come_forward_nor_flash_the_box_is_shown(self):
        api = self.api(foreground_ok=False, flash_ok=False)
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(len(api.made("message_box")), 1)
        self.assertEqual(si.last_note(), "failed")

    def test_the_front_check_is_the_real_foreground_window_not_the_return_value_of_the_call(self):
        api = self.api()
        api.front = 999
        with mock.patch.object(api, "activate", return_value=True):
            result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(api.made("flash"), [("flash", 500)])

    def test_without_our_own_executable_path_no_window_can_be_judged_to_be_ours_so_the_box_comes_at_once(self):
        api = self.api(images={OTHER_PID: OWN_IMAGE})
        result, clock = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(clock.sleeps, [], "기다려도 소용없다")
        self.assertEqual(len(api.made("message_box")), 1)
        self.assertEqual(api.made("top_windows"), [])
        self.assertEqual(si.last_note(), "no_image")


class TakeOverTest(Isolated):
    """방금 닫고 곧바로 다시 열어서 아직 끝나는 중인 앱과 부딪쳤을 때 — 기다리는 사이 그 앱이 끝나 뮤텍스가 비면 넘겨받는다(열려 있는 창이 하나도 없으므로 창은 여전히 하나다)."""

    def setUp(self):
        super().setUp()
        self.kernel = FakeKernel()
        self.name = held_elsewhere(self.kernel)

    def ends_at(self, poll):
        return lambda index: self.kernel.close(self.kernel.elsewhere[0]) if index == poll else None

    def test_when_the_first_app_ends_while_waiting_this_process_takes_over_and_may_open_its_window(self):
        api = FakeApi(self.kernel, scripted=[[]], on_poll=self.ends_at(2))
        result, clock = run_claim(api)
        self.assertIs(result, True)
        self.assertEqual(si.last_note(), "took_over")
        self.assertEqual(api.made("message_box"), [], "열려 있는 창이 없는데 '이미 열려 있어요' 상자를 보이지 않는다")
        for untouched in ("restore", "activate", "flash"):
            self.assertEqual(api.made(untouched), [], untouched)
        self.assertIn(self.name, si._HELD)
        gc.collect()
        self.assertEqual(self.kernel.open_count(self.name), 1, "넘겨받은 핸들도 쥐고 있다(가비지 수집으로 풀리지 않는다)")
        self.assertLess(clock.now, si.WAIT_SECONDS)
        again, _ = run_claim(FakeApi(self.kernel))
        self.assertIs(again, True)
        self.assertEqual(si.last_note(), "held")

    def test_a_window_that_is_found_first_wins_and_no_retake_is_tried_at_all(self):
        api = FakeApi(self.kernel, scripted=[[win(500)]])
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(len(api.made("create_mutex")), 1, "창을 찾았으면 뮤텍스를 다시 만들어 보지 않는다")
        self.assertEqual(si._HELD, {})

    def test_while_the_first_app_is_still_there_every_retry_closes_its_own_copy_and_never_takes_over(self):
        api = FakeApi(self.kernel, scripted=[[]])
        result, clock = run_claim(api)
        self.assertIs(result, False)
        self.assertGreater(len(api.made("create_mutex")), 10, "기다리는 동안 계속 넘겨받을 수 있는지 본다")
        self.assertEqual(self.kernel.open_count(self.name), 1, "시도마다 얻은 사본은 닫았다 — 먼저 연 앱의 것만 남는다")
        self.assertEqual(si._HELD, {})
        self.assertEqual(len(api.made("message_box")), 1)
        self.assertGreaterEqual(clock.now, si.WAIT_SECONDS)

    def test_a_retake_that_fails_in_any_way_changes_nothing_and_the_box_still_comes(self):
        cases = {"넘겨받기 호출이 예외": dict(raise_on_create={2, 5}), "넘겨받기 호출이 핸들을 못 줌": dict(no_handle_after=1)}
        for label, extra in cases.items():
            with self.subTest(label=label):
                si.release_all()
                api = FakeApi(self.kernel, scripted=[[]], **extra)
                result, _ = run_claim(api)
                self.assertIs(result, False)
                self.assertEqual(len(api.made("message_box")), 1)
                self.assertEqual(si._HELD, {})
                self.assertEqual(self.kernel.open_count(self.name), 1)

    def test_a_takeover_never_happens_for_a_window_that_belongs_to_the_still_running_app(self):
        """먼저 열려 있던 앱이 살아 있고 창도 있으면(정상) 아무리 기다려도 넘겨받지 않고 창을 앞으로 가져온다."""
        api = FakeApi(self.kernel, scripted=[[], [], [win(500)]])
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(api.made("activate"), [("activate", 500)])
        self.assertEqual(si._HELD, {})


class WrongWindowTest(Isolated):
    """엉뚱한 창을 끌어오지 않는다 — 같은 앱의 보이는 최상위 창만."""

    DECOYS = {
        "같은 제목의 다른 프로그램(탐색기)": win(601, pid=OTHER_PID + 1),
        "같은 프로그램의 다른 제목 창": win(602, title="다른 창"),
        "같은 제목이지만 소유 창이 있는 창(대화상자)": win(603, owner=77),
        "같은 제목이지만 보이지 않는 창": win(604, visible=False),
        "같은 제목이지만 내 프로세스의 창": win(605, pid=OWN_PID),
        "같은 제목이지만 실행 파일 경로를 알 수 없는 프로세스": win(606, pid=OTHER_PID + 2),
        "빈 제목": win(607, title=""),
    }

    def setUp(self):
        super().setUp()
        self.kernel = FakeKernel()
        held_elsewhere(self.kernel)
        self.images = {OWN_PID: OWN_IMAGE, OTHER_PID: OWN_IMAGE, OTHER_PID + 1: OTHER_IMAGE}

    def test_no_decoy_is_ever_restored_brought_forward_or_flashed(self):
        for label, decoy in self.DECOYS.items():
            with self.subTest(label=label):
                api = FakeApi(self.kernel, scripted=[[decoy]], images=self.images, iconic=True)
                result, _ = run_claim(api)
                self.assertIs(result, False)
                for method in ("restore", "activate", "flash", "is_hung"):
                    self.assertEqual(api.made(method), [], f"{label}: {method}")
                self.assertEqual(len(api.made("message_box")), 1, label)

    def test_among_decoys_the_real_window_is_the_one_that_is_chosen(self):
        windows = [*self.DECOYS.values(), win(500)]
        api = FakeApi(self.kernel, scripted=[windows], images=self.images, iconic=True)
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(api.made("restore"), [("restore", 500)])
        self.assertEqual(api.made("activate"), [("activate", 500)])
        self.assertEqual(api.made("message_box"), [])

    def test_the_executable_path_is_compared_case_and_separator_blind_but_not_by_name_only(self):
        for image, matches in ((OWN_IMAGE.lower(), True), (OWN_IMAGE.replace("/", W), True), ("C:/Other/Place/ChanceBlogDesktop.exe", False), ("C:/Apps/ChanceBlog/Other.exe", False)):
            with self.subTest(image=image):
                api = FakeApi(self.kernel, scripted=[[win(500)]], images={OWN_PID: OWN_IMAGE, OTHER_PID: image})
                result, _ = run_claim(api)
                self.assertIs(result, False)
                self.assertEqual(bool(api.made("activate")), matches)

    def test_the_title_may_have_a_suffix_but_must_start_with_the_apps_title(self):
        for title, matches in ((TITLE + " — 홈", True), (TITLE, True), ("앞 " + TITLE, False), (TITLE[:-1], False)):
            with self.subTest(title=title):
                api = FakeApi(self.kernel, scripted=[[win(500, title=title)]], images=self.images)
                run_claim(api)
                self.assertEqual(bool(api.made("activate")), matches)

    def test_the_title_is_read_from_the_apps_own_title_constant_and_not_written_into_the_code(self):
        with mock.patch.dict(T, {"window_title": "완전히 다른 제목"}):
            api = FakeApi(self.kernel, scripted=[[win(500, title="완전히 다른 제목"), win(501, title=TITLE)]], images=self.images)
            run_claim(api)
            self.assertEqual(api.made("activate"), [("activate", 500)])
            self.assertEqual(api.made("message_box"), [])
            api = FakeApi(self.kernel, scripted=[[win(501, title=TITLE)]], images=self.images)
            run_claim(api)
            self.assertEqual(api.made("activate"), [])
            self.assertEqual(api.made("message_box")[0][1], "완전히 다른 제목")
            self.assertIn("완전히 다른 제목", api.made("message_box")[0][2])


class NeverDiesTest(Isolated):
    """어떤 윈도 호출이 예외를 던져도 죽지 않고, 이미 열려 있음이 확인된 뒤에는 새 창을 열지 않는다(`False`)."""

    def scenario(self, **extra):
        kernel = FakeKernel()
        held_elsewhere(kernel)
        return FakeApi(kernel, scripted=[[win(500)]], iconic=True, foreground_ok=False, flash_ok=False, **extra)

    def test_the_scenario_really_calls_every_method_so_the_sweep_below_is_complete(self):
        api = self.scenario()
        run_claim(api)
        self.assertEqual({call[0] for call in api.calls} - {"create_mutex"}, set(FakeApi.ALL_AFTER_CREATE))

    def test_each_method_raising_alone_never_escapes_and_never_lets_a_new_window_open(self):
        for method in FakeApi.ALL_AFTER_CREATE:
            with self.subTest(method=method):
                api = self.scenario(raises={method})
                result, _ = run_claim(api)
                self.assertIs(result, False, f"{method} 가 예외를 던져도 이미 열려 있다는 판정은 그대로다")

    def test_every_method_raising_at_once_still_ends_quietly_without_a_new_window(self):
        api = self.scenario(raises=set(FakeApi.ALL_AFTER_CREATE))
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(si.last_note(), "message_box:RuntimeError")

    def test_when_the_window_search_fails_the_box_is_the_fallback(self):
        api = self.scenario(raises={"top_windows"})
        result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(len(api.made("message_box")), 1)

    def test_a_real_looking_error_inside_the_reveal_does_not_become_a_second_window(self):
        api = self.scenario()
        with mock.patch.object(si, "reveal", side_effect=KeyError("secret path C:/x")):
            result, _ = run_claim(api)
        self.assertIs(result, False)
        self.assertEqual(si.last_note(), "failed")
        self.assertNotIn("secret", si.last_note())


class TextTest(unittest.TestCase):
    def test_the_box_text_is_easy_korean_and_says_what_to_do(self):
        text = si.ALREADY_OPEN_TEXT.format(name=TITLE)
        for needle in (TITLE, "이미 열려", "작업 표시줄", "작업 관리자", "다시 열어 주세요"):
            self.assertIn(needle, text, needle)
        self.assertEqual(si.ALREADY_OPEN_TEXT.count("{"), 2)
        self.assertEqual(si.ALREADY_OPEN_TEXT.count("{name}"), 2, "창 제목 한 가지 이름만 쓴다 — 작업 관리자에서 찾을 이름도 같다")
        self.assertLessEqual(len(text.splitlines()), 3)
        self.assertNotRegex(text, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")                         # 영문 오류 코드 없음
        self.assertNotRegex(text, r"Traceback|Exception|Error\b|mutex|Mutex|뮤텍스|183")
        self.assertNotIn(chr(0x7E), text)
        self.assertIsNone(re.search(r"(?i)https?://|www[.]", text))

    def test_the_wait_is_long_enough_for_a_slow_first_start_and_short_enough_not_to_look_stuck(self):
        self.assertGreaterEqual(si.WAIT_SECONDS, 8)
        self.assertLessEqual(si.WAIT_SECONDS, 20)
        self.assertLessEqual(si.POLL_SECONDS, 0.5)


# ---- 3) launcher.main 에 걸린 곳 ---------------------------------------------------------------------------------------------------------------

def fake_qt_app(result=0):
    module = types.ModuleType("chanceblog_desktop.ui.qt.app")
    module.providers = []
    module.run = lambda provider, argv=None: (module.providers.append(provider), result)[1]
    return module


class LauncherWiringTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(sec.uninstall_boundary)                    # `launcher.main` 이 맨 앞에서 공통 출력 경계를 깐다 — 같은 프로세스의 다른 시험에 남기지 않는다

    def open(self, *argv, claimed=True, pyside6=True):
        module = fake_qt_app()
        out = io.StringIO()
        with mock.patch.object(launcher, "has_pyside6", return_value=pyside6), mock.patch.dict(sys.modules, {"chanceblog_desktop.ui.qt.app": module}), \
                mock.patch.object(si, "claim", return_value=claimed) as claim:
            code = launcher.main(list(argv), out=out)
        return code, module.providers, claim, out.getvalue()

    def test_an_already_open_app_ends_quietly_with_code_0_and_never_builds_a_screen(self):
        code, providers, claim, shown = self.open(claimed=False)
        self.assertEqual((code, providers, shown), (0, [], ""))
        claim.assert_called_once_with(None, sample=False)

    def test_the_first_run_goes_on_and_builds_the_screen(self):
        code, providers, claim, _shown = self.open(claimed=True)
        self.assertEqual((code, len(providers)), (0, 1))
        claim.assert_called_once_with(None, sample=False)

    def test_the_data_dir_and_the_sample_flag_reach_the_device_untouched(self):
        _code, _providers, claim, _ = self.open("--data-dir", "C:" + W + "내 폴더")
        claim.assert_called_once_with("C:" + W + "내 폴더", sample=False)
        _code, _providers, claim, _ = self.open("--sample")
        claim.assert_called_once_with(None, sample=True)
        _code, _providers, claim, _ = self.open("--sample", "--data-dir", "C:" + W + "x")
        claim.assert_called_once_with("C:" + W + "x", sample=True)

    def test_without_pyside6_the_device_is_not_asked_because_no_window_could_open_anyway(self):
        code, providers, claim, shown = self.open(pyside6=False)
        self.assertEqual((code, providers), (1, []))
        self.assertEqual(shown.strip(), launcher.NEEDS_PYSIDE6)
        claim.assert_not_called()

    def test_a_release_without_a_readable_version_ends_before_the_device_is_asked(self):
        from chanceblog_desktop.ui.core import version
        with mock.patch.object(version, "release_problem", return_value="버전 안내"):
            code, providers, claim, shown = self.open()
        self.assertEqual((code, providers, shown.strip()), (1, [], "버전 안내"))
        claim.assert_not_called()

    def test_a_usage_error_ends_before_the_device_is_asked(self):
        with mock.patch.object(si, "claim") as claim, contextlib_redirect_stderr():
            with self.assertRaises(SystemExit):
                launcher.main(["--nope-" + "x"])
        claim.assert_not_called()

    def test_the_call_sits_after_the_pyside6_check_and_before_the_qt_handler_and_the_heavy_imports(self):
        tree = ast.parse((UI / "launcher.py").read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        shown = [ast.unparse(node) for node in main.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        check = next(index for index, text in enumerate(shown) if text.startswith("if not has_pyside6():"))
        claim = [index for index, text in enumerate(shown) if "single_instance.claim(" in text]
        qt = next(index for index, text in enumerate(shown) if text == "boundary.install_gui()")
        adapters = next(index for index, text in enumerate(shown) if text.startswith("from .adapters import"))
        opened = next(index for index, text in enumerate(shown) if text.startswith("from .qt.app import"))
        self.assertEqual(len(claim), 1, "장치를 부르는 곳은 `launcher.main` 안의 한 곳이다")
        self.assertTrue(check < claim[0] < qt < adapters < opened, shown)
        self.assertEqual(shown[claim[0]].split("\n")[1].strip(), "return 0", "이미 열려 있으면 종료 코드 0 으로 끝난다")
        self.assertIn("args.data_dir", shown[claim[0]])
        self.assertIn("sample=args.sample", shown[claim[0]])


def contextlib_redirect_stderr():
    import contextlib
    return contextlib.redirect_stderr(io.StringIO())


class OnlyTheLauncherAsksTest(unittest.TestCase):
    """장치를 부르는 곳은 `launcher.main` 한 곳이다 — `--selftest`·명령줄·묶음 시작 파일은 뮤텍스를 잡지 않는다(묶음 빌드의 점검이 화면과 동시에 돌 수 있다)."""

    def references(self, path):
        found = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found += [alias.name for alias in node.names if "single_instance" in alias.name]
            elif isinstance(node, ast.ImportFrom):
                if "single_instance" in (node.module or "") or any(alias.name == "single_instance" for alias in node.names):
                    found.append(node.module or "from-import")
            elif isinstance(node, ast.Attribute) and node.attr == "single_instance":
                found.append("attribute")
            elif isinstance(node, ast.Name) and node.id == "single_instance":
                found.append("name")
        return found

    def test_exactly_one_source_file_refers_to_the_device_and_it_is_the_launcher(self):
        referring = {}
        for path in sorted(SRC.rglob("*.py")):
            if path.name == "single_instance.py":
                continue
            found = self.references(path)
            if found:
                referring[path.relative_to(SRC).as_posix()] = found
        self.assertEqual(sorted(referring), ["ui/launcher.py"], referring)

    def test_the_bundled_start_file_the_command_line_and_the_package_entry_never_name_it(self):
        for path in (ROOT / "packaging" / "gui_entry.py", SRC / "__main__.py", SRC / "service" / "cli.py"):
            self.assertEqual(self.references(path), [], path.name)

    def test_the_selftest_and_the_refusal_paths_of_the_bundled_start_file_never_ask_the_device(self):
        sys.path.insert(0, str(ROOT / "packaging"))
        try:
            import gui_entry
        finally:
            sys.path.remove(str(ROOT / "packaging"))
        with mock.patch.object(si, "claim", side_effect=AssertionError("이 길은 단일 실행 장치를 부르지 않는다")):
            said = []
            for args in (["--selftest", "x"], ["doctor"], ["gui"], ["--sample"]):
                self.assertEqual(gui_entry.main(args, say=lambda text, error=False: said.append(text), start=lambda: self.fail("화면")), 2)
            self.assertEqual(gui_entry.check_gui_only(gui_entry.main, modules={}).status, "ok")


class InProcessCallersCleanUpTest(unittest.TestCase):
    """같은 프로세스에서 `launcher.main` 을 부르는 시험 파일은 모두 뒷정리(`sec.uninstall_boundary` — 출력 경계와 단일 실행 뮤텍스를 함께 놓는다)를 건다. 안 걸면 시험 프로세스가 끝날 때까지 이 PC 의 기본 데이터 폴더
    뮤텍스를 쥐고 있어, 같은 PC 에서 동시에 도는 다른 시험 프로세스(이 PC 에서는 여러 작업 줄이 동시에 돈다)의 같은 시험이 '이미 열려 있음' 으로 판정해 진짜 안내 상자에서 멈춘다."""

    def test_every_test_file_that_calls_launcher_main_in_process_registers_the_cleanup(self):
        tests = Path(__file__).resolve().parent
        callers = []
        for path in sorted(tests.glob("test_*.py")):                                               # 도우미 프로그램(`*_child.py` — 자기 프로세스의 진입점이다)은 시험이 아니다
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            if any(isinstance(node, ast.Call) and ast.unparse(node.func) == "launcher.main" for node in ast.walk(tree)):
                callers.append(path.name)
                self.assertIn("uninstall_boundary", source, f"{path.name}: launcher.main 을 부르는데 뒷정리(sec.uninstall_boundary)가 없다")
        for known in ("test_ui_launcher.py", "test_ui_backup_core.py", "test_single_instance.py"):
            self.assertIn(known, callers, f"{known}: 이 시험 훑기가 launcher.main 호출을 찾지 못했다 — 훑는 규칙이 깨졌다")

    def test_the_cleanup_helper_releases_the_mutexes_this_process_holds(self):
        api = FakeApi()
        run_claim(api)
        name = si.mutex_name(si.resolve_folder(FOLDER, {}))
        self.assertIn(name, si._HELD)
        sec.uninstall_boundary()
        self.assertEqual(si._HELD, {})
        self.assertEqual(api.kernel.open_count(name), 0)

    def test_the_cleanup_helper_does_nothing_when_nothing_is_held(self):
        si.release_all()
        sec.uninstall_boundary()
        self.assertEqual(si._HELD, {})


# ---- 4) 소스 규칙 ------------------------------------------------------------------------------------------------------------------------------

class SourceRulesTest(unittest.TestCase):
    def setUp(self):
        self.text = (UI / "single_instance.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def imported(self):
        names = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names.append(("." * node.level) + (node.module or ""))
        return names

    def test_only_standard_modules_and_the_apps_text_table_are_imported_and_nothing_reaches_out(self):
        self.assertEqual(sorted(set(self.imported())), [".core.text", "__future__", "ctypes", "hashlib", "ntpath", "os", "pathlib", "sys", "time"])
        forbidden = {"subprocess", "socket", "ssl", "urllib", "http", "asyncio", "webbrowser", "multiprocessing", "threading", "shutil", "tempfile", "sqlite3", "PySide6", "shiboken6", "requests", "logging", "traceback"}
        for name in self.imported():
            self.assertNotIn(name.split(".")[0], forbidden, name)
        self.assertNotIn("QtNetwork", self.text)

    def test_ctypes_is_imported_only_inside_the_windows_call_layer_and_wintypes_with_it(self):
        top_level = [node for node in self.tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertNotIn("ctypes", [getattr(node, "module", None) or alias.name for node in top_level for alias in node.names] + [getattr(node, "module", "") for node in top_level])
        layer = next(node for node in self.tree.body if isinstance(node, ast.ClassDef) and node.name == "Win32Api")
        inside = {alias.name for node in ast.walk(layer) if isinstance(node, ast.Import) for alias in node.names} | {node.module for node in ast.walk(layer) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(inside, {"ctypes"})
        outside = [node for node in ast.walk(self.tree) if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in list(ast.walk(layer)) and "ctypes" in ast.unparse(node)]
        self.assertEqual(outside, [])

    def test_no_file_write_process_start_print_or_environment_write_exists(self):
        calls = {ast.unparse(node.func) for node in ast.walk(self.tree) if isinstance(node, ast.Call)}
        for name in calls:
            self.assertFalse(name.startswith(("os.system", "os.startfile", "os.popen", "os.spawn", "os.exec", "os.write", "os.makedirs", "os.mkdir", "os.remove", "os.rename", "os.replace",
                                              "subprocess.", "webbrowser.", "shutil.", "tempfile.")), name)
            self.assertNotIn(name, {"open", "print", "exec", "eval", "compile", "__import__", "os.putenv", "os.environ.update", "os.environ.setdefault"}, name)
            self.assertFalse(name.endswith((".write_text", ".write_bytes", ".mkdir", ".unlink", ".touch", ".rmdir")), name)
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    self.assertNotIn("environ", ast.unparse(target))

    def test_the_names_of_the_environment_variables_it_reads_are_the_two_known_ones(self):
        gets = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and ast.unparse(node.func.value) == "env" and node.args and isinstance(node.args[0], ast.Constant):
                gets.append(node.args[0].value)
        self.assertEqual(sorted(gets), ["LOCALAPPDATA"])
        self.assertIn("env.get(ENV_DATA_DIR)", ast.unparse(self.tree))
        self.assertEqual(si.ENV_DATA_DIR, "CHANCEBLOG_DESKTOP_DATA")

    def test_global_is_not_used_as_a_namespace_anywhere_in_the_code(self):
        docstrings = {id(node.body[0].value) for node in ast.walk(self.tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Constant)}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                self.assertNotIn("Global", node.value)
        self.assertTrue(si.MUTEX_PREFIX.startswith("Local"))

    def test_the_title_is_read_from_the_text_table_and_never_written_as_a_literal_in_the_code(self):
        docstrings = {id(node.body[0].value) for node in ast.walk(self.tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Constant)}
        literals = [node.value for node in ast.walk(self.tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]
        self.assertFalse([text for text in literals if TITLE in text], "창 제목 글자를 코드에 따로 적지 않는다")
        function = next(node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef) and node.name == "_window_title")
        self.assertIn("T['window_title']", ast.unparse(function))

    def test_the_real_window_of_the_app_gets_exactly_that_title_constant(self):
        """장치가 찾는 제목과 앱 창이 다는 제목이 같은 상수여야 한다 — 창 제목을 만지는 곳이 `shell.py` 한 곳이고 그 값이 `T['window_title']` 이다."""
        found = []
        for path in sorted(UI.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setWindowTitle":
                    found.append((path.relative_to(UI).as_posix(), ast.unparse(node.args[0]) if node.args else ""))
        self.assertEqual(found, [("qt/shell.py", "T['window_title']")])

    def test_the_decision_logic_functions_take_the_call_layer_as_an_argument_so_the_fake_can_be_swapped_in(self):
        for name in ("find_window", "bring_to_front", "reveal", "_announce"):
            function = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertEqual(function.args.args[0].arg, "api", name)

    def test_the_bare_except_and_silent_pass_are_not_used_and_each_broad_catch_leaves_a_reason(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ExceptHandler):
                self.assertIsNotNone(node.type, "맨 except 금지")
                body = [ast.unparse(item) for item in node.body]
                self.assertNotEqual(body, ["pass"], "본문이 pass 뿐인 except 금지")
                if ast.unparse(node.type) == "Exception":
                    self.assertTrue(any("_note(" in text for text in body), "넓게 잡은 예외는 이유를 남긴다: " + " / ".join(body))


# ---- 5) 윈도 전용 — 진짜 뮤텍스·진짜 프로세스 -----------------------------------------------------------------------------------------------------

class SafeApi(si.Win32Api):
    """진짜 뮤텍스(커널)와 진짜 프로세스 정보는 그대로 쓰고 **창 층만 가짜** — 열린 창이 없다고 답하고 안내 상자는 기록만 한다. 시험이 진짜 창을 건드리거나 진짜 상자를 띄우지 않는다."""

    def top_windows(self):
        return []

    def message_box(self, title, text):
        BOXES.append(text)


@unittest.skipUnless(WINDOWS, "진짜 윈도 뮤텍스는 윈도에만 있다")
class RealWindowsTest(Isolated):
    def setUp(self):
        super().setUp()
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "data")
        self.name = si.mutex_name(si.resolve_folder(self.folder, {}))
        self.api = SafeApi()
        self.opened = []
        self.addCleanup(self.close_all)
        self.addCleanup(lambda: self.assertEqual(BOXES, [], "진짜 안내 상자를 띄우려 했다"))

    def claim(self, folder):
        clock = Clock()                                              # 12초 기다림을 진짜로 기다리지 않는다
        return si.claim(folder, api=self.api, sleep=clock.sleep, monotonic=clock.monotonic)

    def close_all(self):
        for handle in self.opened:
            self.api.close_handle(handle)

    def take(self):
        handle, error = self.api.create_mutex(self.name)
        self.assertTrue(handle)
        self.opened.append(handle)
        return error

    def test_the_second_acquisition_of_a_real_mutex_in_one_process_is_reported_as_already_existing(self):
        self.assertEqual(self.take(), 0)
        self.assertEqual(self.take(), si.ERROR_ALREADY_EXISTS)
        self.assertEqual(self.take(), si.ERROR_ALREADY_EXISTS)

    def test_after_every_handle_is_closed_the_name_is_free_again(self):
        self.take()
        self.close_all()
        self.opened.clear()
        self.assertEqual(self.take(), 0)

    def test_a_stale_last_error_cannot_be_mistaken_for_already_exists(self):
        import ctypes
        ctypes.set_last_error(si.ERROR_ALREADY_EXISTS)
        ctypes.windll.kernel32.SetLastError(si.ERROR_ALREADY_EXISTS)
        self.assertEqual(self.take(), 0)

    def test_claim_holds_the_real_handle_until_released_and_survives_garbage_collection(self):
        self.assertIs(self.claim(self.folder), True)
        self.assertEqual(si.last_note(), "first")
        gc.collect()
        self.assertEqual(self.take(), si.ERROR_ALREADY_EXISTS, "가비지 수집 뒤에도 뮤텍스를 쥐고 있어야 다음 실행이 '이미 열려 있음' 을 안다")
        self.close_all()
        self.opened.clear()
        self.assertIs(self.claim(self.folder), True, "같은 프로세스의 두 번째 호출은 통과")
        self.assertEqual(si.last_note(), "held")
        si.release_all()
        self.assertEqual(self.take(), 0, "놓은 뒤에는 이름이 비었다")

    def test_a_different_data_folder_has_its_own_real_mutex(self):
        other = os.path.join(self.tmp.name, "other")
        self.assertIs(self.claim(self.folder), True)
        self.assertIs(self.claim(other), True)
        self.assertEqual(len(si._HELD), 2)

    def test_the_own_executable_path_is_readable_and_an_unknown_process_has_none(self):
        image = self.api.image_path(os.getpid())
        self.assertTrue(image and os.path.isfile(image) and image.lower().endswith(".exe"), image)
        self.assertIsNone(self.api.image_path(0xFFFFFFF0))

    def test_the_window_list_has_the_documented_shape(self):
        windows = self.api.top_windows()
        self.assertIsInstance(windows, list)
        for hwnd, title, pid, owner, visible in windows:
            self.assertIsInstance(hwnd, int)
            self.assertIsInstance(title, str)
            self.assertIsInstance(pid, int)
            self.assertIsInstance(owner, int)
            self.assertIs(visible, True)

    def test_the_foreground_and_state_calls_accept_a_window_number_that_does_not_exist(self):
        for call in (self.api.is_hung, self.api.is_iconic):
            self.assertIsInstance(call(0x7FFFFFF0), bool)
        self.assertIsInstance(self.api.foreground(), int)


@unittest.skipUnless(WINDOWS, "진짜 윈도 뮤텍스는 윈도에만 있다")
class RealProcessesTest(unittest.TestCase):
    """진짜 프로세스 둘 — 커널의 뮤텍스가 프로세스 사이에서 둘째를 막고, 첫 프로세스가 끝나면(낡은 잠금 파일 없이) 다시 열린다."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "data")
        self.holders = []
        self.addCleanup(self.kill_holders)

    def kill_holders(self):
        for holder in self.holders:
            if holder.poll() is None:
                holder.kill()
            holder.wait(timeout=30)
            for stream in (holder.stdin, holder.stdout, holder.stderr):
                try:
                    stream.close()
                except OSError:
                    pass

    def spawn(self, role, folder=None):
        env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"))
        env.pop("QT_QPA_PLATFORM", None)
        return subprocess.Popen([sys.executable, "-X", "utf8", str(CHILD), role, folder or self.folder], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True,
                                encoding="utf-8", creationflags=0x08000000)

    def first_lines(self, process, count, timeout=60):
        """도우미가 찍는 줄을 `count` 개까지 읽는다(막히지 않게 스레드로 읽고 시간 제한을 둔다)."""
        box = queue.Queue()

        def read():
            for _ in range(count):
                box.put(process.stdout.readline().strip())

        threading.Thread(target=read, daemon=True).start()
        return [box.get(timeout=timeout) for _ in range(count)]

    def probe(self, role, folder=None):
        process = self.spawn(role, folder)
        self.holders.append(process)
        out, err = process.communicate(input="", timeout=120)
        return process.returncode, out.split(), err

    def hold(self, role, count, folder=None):
        process = self.spawn(role, folder)
        self.holders.append(process)
        return process, self.first_lines(process, count)

    def release(self, process):
        process.stdin.write("끝\n")
        process.stdin.flush()
        process.wait(timeout=60)

    def test_the_second_process_for_the_same_data_folder_is_blocked_and_the_first_is_not(self):
        holder, lines = self.hold("claim-hold", 1)
        self.assertEqual(lines, ["CLAIM True first"])
        code, words, err = self.probe("claim-probe")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(words, ["BOX", "CLAIM", "False", "no_window"], "열린 창이 없다고 답하는 가짜 창 층에서는 안내 상자 쪽으로 간다 — 새 창은 만들지 않는다")
        self.release(holder)
        code, words, _err = self.probe("claim-probe")
        self.assertEqual((code, words), (0, ["CLAIM", "True", "first"]), "첫 프로세스가 끝나면 낡은 잠금 없이 바로 열린다")

    def test_another_data_folder_opens_next_to_a_running_one(self):
        holder, lines = self.hold("claim-hold", 1)
        self.assertEqual(lines, ["CLAIM True first"])
        code, words, _err = self.probe("claim-probe", os.path.join(self.tmp.name, "other"))
        self.assertEqual((code, words), (0, ["CLAIM", "True", "first"]))
        self.release(holder)

    def test_a_killed_first_process_leaves_no_stale_lock(self):
        holder, lines = self.hold("claim-hold", 1)
        self.assertEqual(lines, ["CLAIM True first"])
        holder.kill()
        holder.wait(timeout=60)
        code, words, _err = self.probe("claim-probe")
        self.assertEqual((code, words), (0, ["CLAIM", "True", "first"]), "강제 종료해도 OS 가 뮤텍스를 지운다")

    def test_a_second_process_waiting_for_a_closing_first_one_takes_the_mutex_over_instead_of_showing_the_box(self):
        """방금 닫고 곧바로 다시 연 경우 — 첫 프로세스가 아직 끝나는 중이라 뮤텍스가 남아 있어도 기다리는 사이 끝나면 넘겨받는다(열려 있는 창이 없는데 '이미 열려 있어요' 상자를 보이지 않는다)."""
        holder, lines = self.hold("claim-hold", 1)
        self.assertEqual(lines, ["CLAIM True first"])
        waiter = self.spawn("claim-waithold")
        self.holders.append(waiter)
        self.assertEqual(self.first_lines(waiter, 1), ["POLL"], "둘째가 열린 창을 찾으며 기다리기 시작했다")
        self.release(holder)
        self.assertEqual(self.first_lines(waiter, 1), ["CLAIM True took_over"])
        code, words, _err = self.probe("claim-probe")
        self.assertEqual((code, words), (0, ["BOX", "CLAIM", "False", "no_window"]), "이제 넘겨받은 프로세스가 쥐고 있어서 셋째는 막힌다")
        self.release(waiter)

    def test_the_real_launcher_never_builds_a_second_screen_for_the_second_process(self):
        holder, lines = self.hold("launcher-hold", 2)
        self.assertEqual(lines, ["RUN", "EXIT 0 first"], "첫 프로세스는 화면을 연다")
        code, words, err = self.probe("launcher-probe")
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("RUN", words, "둘째 프로세스는 화면을 만들지 않는다")
        self.assertEqual(words, ["BOX", "EXIT", "0", "no_window"])
        self.release(holder)
        code, words, _err = self.probe("launcher-probe")
        self.assertEqual((code, words), (0, ["RUN", "EXIT", "0", "first"]))


# ---- 6) 문서 ------------------------------------------------------------------------------------------------------------------------------------

def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def new_text(rel):
    """이 묶음이 그 문서에 더한 글(절 하나 또는 줄들)."""
    body = read(rel)
    if rel == "docs/PERSONAL_PC_TEST.md":
        return body.split("### 1-4.")[1].split("## 2단계")[0]
    if rel == "docs/TROUBLESHOOTING.md":
        return body.split("## 14. 앱을 두 번 열었을 때")[1].split("\n## ")[0]
    if rel in ("docs/DECISIONS.md", "CHANGELOG.md"):
        return "\n".join(line for line in body.splitlines() if "SINGLEWIN" in line)
    heading = next(line for line in body.splitlines() if line.startswith("## ") and "SINGLEWIN" in line)
    return body[body.index(heading):].split("\n## ")[0]


NEW_TEXT_FILES = ("docs/PERSONAL_PC_TEST.md", "docs/TROUBLESHOOTING.md", "docs/PACKAGE.md", "docs/UI_STATES.md", "docs/SECURITY.md", "docs/ARCHITECTURE.md", "docs/DECISIONS.md", "CHANGELOG.md")


class DocsTest(unittest.TestCase):
    """시험지(1-4)·결정·변경 이력·문제 해결·구조·보안·화면 상태·Package 문서가 쉬운 말로 이 동작을 적고, 시험지의 기존 번호는 그대로이며 새 칸은 덧붙임뿐이다."""

    def test_the_personal_pc_sheet_has_one_new_check_in_step_1_after_the_existing_ones(self):
        step1 = read("docs/PERSONAL_PC_TEST.md").split("## 1단계")[1].split("## 2단계")[0]
        self.assertEqual(re.findall(r"(?m)^### (1-\d)\.", step1), ["1-1", "1-2", "1-3", "1-4"], "기존 1-1·1-2·1-3 번호는 그대로이고 새 칸은 1-4 한 개다")
        new = new_text("docs/PERSONAL_PC_TEST.md")
        for needle in ("ChanceBlogDesktop.exe", "한 번 더", "새 창", "작업 표시줄", "이렇게 보이면 통과", "창이 두 개", "실패", "이미 열려", "하나만", "안내 상자"):
            self.assertIn(needle, new, needle)
        self.assertEqual(new.count("- [ ] "), 2, "새 칸은 체크 줄 둘(한 번 더 누르기·창 수 보기)")
        self.assertNotRegex(new, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")                          # 영문 오류 코드 없음
        self.assertNotRegex(new, r"뮤텍스|[Mm]utex|183|Traceback|Exception")                   # 운영자가 읽는 글에 장치 내부 용어를 쓰지 않는다
        for word in ("python", "pip ", "git ", "PyInstaller", "venv"):
            self.assertNotIn(word, new, word)

    def test_the_report_table_row_of_the_new_check_sits_between_1_3_and_2_and_has_the_three_columns(self):
        table = read("docs/PERSONAL_PC_TEST.md").split("## 7단계. 결과 보고")[1].split("## 8단계")[0]
        rows = [line for line in table.splitlines() if re.match(r"^\| (\d)(-\d)? \|", line)]
        ids = [row.split("|")[1].strip() for row in rows]
        index = ids.index("1-4")
        self.assertEqual(ids[index - 1], "1-3")
        self.assertLess(index, ids.index("2"))
        self.assertEqual(rows[index].count("|"), 5)
        self.assertIn("새 창이 떴나(예/아니요)", rows[index])
        for old in ("0-1", "0-2", "0-3", "1-1", "1-2", "1-3", "2", "3", "4", "5", "6-1", "6-2", "6-3", "6-4"):
            self.assertEqual(ids.count(old), 1, old)

    def test_the_new_text_has_no_tilde_no_link_and_no_unfilled_placeholder(self):
        for rel in NEW_TEXT_FILES:
            body = new_text(rel)
            self.assertGreater(len(body), 100, rel)
            self.assertNotIn(chr(0x7E), body, rel)
            self.assertIsNone(re.search(r"(?i)(https?|ftp)://|www[.]", body), rel)
            self.assertNotIn("@@", body, rel)
            for target in re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", body):
                self.assertTrue((ROOT / "docs" / target.split("#")[0]).exists(), f"{rel}: {target}")

    def test_the_troubleshooting_section_says_that_one_window_after_a_second_start_is_normal_and_makes_no_error_code(self):
        section = new_text("docs/TROUBLESHOOTING.md")
        for needle in ("두 번 열어도 하나만 뜨는 것은 정상", "작업 표시줄", "작업 관리자", "같은 데이터 폴더", "이미 열려 있거나 열리는 중이에요", "새 오류 코드는 없습니다"):
            self.assertIn(needle, section, needle)
        self.assertNotRegex(section, r"(?m)^\| ")                                                  # 오류 코드 표가 아니다 — 새 오류 코드를 만들지 않았다
        self.assertNotRegex(section, r"뮤텍스|[Mm]utex|183")

    def test_the_decisions_record_the_device(self):
        rows = {re.match(r"^\| (D-\d+) \|", line).group(1): line for line in read("docs/DECISIONS.md").splitlines() if "SINGLEWIN" in line and re.match(r"^\| D-\d+ \|", line)}
        self.assertGreaterEqual(len(rows), 4)
        text = "\n".join(rows.values())
        for needle in ("single_instance.py", "Local", "SHA-256", "183", "모듈 전역", "launcher.main", "--selftest", "--sample", "Global", "제목", "경로", "깜박", "12초", "T2", "test_packaging_docs", "변이", "원복"):
            self.assertIn(needle, text, needle)
        for line in rows.values():
            self.assertEqual(line.count(" | "), 3, line[:40])
            self.assertTrue(line.rstrip().endswith("|"))
            self.assertTrue(line.split("|")[2].strip().startswith("2026-11-"))
        numbers = [int(key[2:]) for key in rows]
        self.assertEqual(numbers, sorted(set(numbers)), "번호는 오름차순이고 겹치지 않는다(다른 묶음의 행이 사이에 끼어도 된다)")

    def test_the_changelog_names_it_in_the_first_section_and_says_the_double_start_is_normal(self):
        first = read("CHANGELOG.md").split("\n## [")[1]
        for needle in ("single_instance.py", "두 번 열어도 하나만 뜨는 것은 정상", "PERSONAL_PC_TEST.md", "T2", "launcher.py"):
            self.assertIn(needle, first, needle)

    def test_the_four_explanation_documents_have_their_sections(self):
        for rel, needles in (("docs/PACKAGE.md", ("단일 실행", "Local", "ChanceBlogDesktop.exe", "--selftest", "PERSONAL_PC_TEST", "한계")),
                             ("docs/ARCHITECTURE.md", ("single_instance.py", "launcher.main", "Local", "gui_entry", "claim")),
                             ("docs/SECURITY.md", ("single_instance.py", "관리자 권한", "네트워크", "하위 프로세스", "Local", "접근 거부", "한계")),
                             ("docs/UI_STATES.md", ("한 번 더 열었을 때", "작업 표시줄", "안내 상자", "앞으로", "12초"))):
            body = new_text(rel)
            for needle in needles:
                self.assertIn(needle, body, f"{rel}: {needle}")


if __name__ == "__main__":
    unittest.main()
