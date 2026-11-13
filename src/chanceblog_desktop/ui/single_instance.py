"""단일 실행 장치 — 같은 윈도 로그온·같은 데이터 폴더에서 앱을 두 번 열면 새 창을 만들지 않고, 열려 있는 창을 앞으로 가져온 뒤 조용히 끝나게 한다(SINGLEWIN, D-471 이후).

왜: 실행 파일(`ChanceBlogDesktop.exe`)을 두 번 누르면(첫 창이 뜨는 데 몇 초 걸려 다시 누르기 쉽다) 프로세스가 둘 떠서 창도 둘이 된다. 두 창이 같은 데이터 폴더를 쓰면 저장이 엇갈릴 수 있다
(서비스의 잠금이 쓰기는 지키지만 화면은 막지 않는다). 앱 코드에는 자기 자신을 다시 실행하는 길도, 최상위 창을 둘 만드는 길도 없다 — 창이 둘이 되는 원인은 프로세스가 둘인 것뿐이다.

어떻게(윈도 전용 — 다른 운영체제에서는 아무것도 하지 않고 지나간다):
  1) 이름 있는 뮤텍스를 만든다. 이름 = 고정 접두(`Local` 이름 공간) + **해결한 데이터 폴더 경로**(소문자·한 가지 구분자로 맞춤)의 SHA-256 앞 16자리 — 같은 데이터 폴더일 때만 같은 이름이 된다.
     `Local` 이름 공간은 윈도 로그온 세션마다 따로라 다른 계정(다른 세션)과 부딪치지 않고 관리자 권한이 필요 없다(`Global` 은 쓰지 않는다).
  2) `CreateMutexW` 가 오류 183(이미 있음)을 알리면 다른 프로세스가 열려 있는 것이다. 핸들은 이 모듈이 프로세스가 끝날 때까지 쥔다 — 프로세스가 끝나면(강제 종료 포함) OS 가 알아서 지우므로
     낡은 잠금 파일이 남지 않는다.
  3) 이미 열려 있으면 열린 창을 찾는다: 보이는 최상위 창 중 제목이 앱의 실제 창 제목 상수(`T["window_title"]`)로 시작하고, **같은 실행 파일 경로의 프로세스가 가진** 것만(폴더 이름이 같은
     탐색기 창 같은 엉뚱한 창은 건드리지 않는다). 첫 창이 아직 뜨는 중이면 잠깐(`WAIT_SECONDS`) 기다린다. 찾으면 최소화돼 있을 때만 되살리고 앞으로 가져온다.
     앞으로 못 가져오면(윈도가 막을 수 있다) 작업 표시줄이 깜박이게 하고, 창을 못 찾거나 응답이 없으면 쉬운 한국어 안내 상자를 보인다.
     기다리는 사이 먼저 열려 있던 앱이 끝나(방금 닫고 곧바로 다시 연 경우 — 닫힌 프로세스가 아직 끝나는 중이었다) 뮤텍스가 비면 그것을 넘겨받아 이 프로세스가 새 첫 실행이 된다(열려 있는 창이 하나도 없으므로 창은 여전히 하나다).
  4) 어떤 경우에도 새 창을 만들지 않고 예외로 죽지 않는다(모든 호출을 감싼다). 뮤텍스를 만들 수 없는 등 **판정이 서지 않으면 장치를 끈 채** 지나간다(앱을 막지 않는다) — 이유는 `last_note()` 에 남는다.

같은 계정·같은 데이터 폴더일 때만 막는다: 다른 윈도 계정(다른 `Local` 이름 공간)·다른 데이터 폴더(`--data-dir`)·`--sample` 은 따로 열 수 있다(개발·시험 편의). `--selftest` 와 명령줄(`service/cli.py`)은 이 장치를 지나지 않는다.
PySide6 와 Qt 의 네트워크 모듈을 가져오지 않고, 하위 프로세스·네트워크·파일 쓰기가 없으며(윈도 호출뿐), 읽는 환경 변수는 `CHANCEBLOG_DESKTOP_DATA`·`LOCALAPPDATA` 뿐이다(`service/context.py` 와 같은 폴더 규칙).
`ctypes` 는 윈도 길에서만 안에서 가져온다(`Win32Api`) — 시험은 같은 모양의 가짜 층을 끼워 순수 논리를 확인한다.
"""
from __future__ import annotations

import hashlib
import ntpath
import os
import sys
import time
from pathlib import Path

BACKSLASH = chr(92)
MUTEX_PREFIX = "Local" + BACKSLASH + "ChanceBlogDesktop-"        # 윈도 로그온 세션별 이름 공간 — 다른 계정과 부딪치지 않고 관리자 권한이 필요 없다(Global 은 쓰지 않는다)
HASH_LENGTH = 16
ERROR_ALREADY_EXISTS = 183                                       # `CreateMutexW` 가 '이미 있는 이름' 이라고 알리는 오류 번호
APP_DIR_NAME = "ChanceblogDesktop"                               # `service/context.py` 의 같은 이름 상수와 같아야 한다(시험이 지킨다)
ENV_DATA_DIR = "CHANCEBLOG_DESKTOP_DATA"                         # 〃
WAIT_SECONDS = 12.0                                              # 첫 창이 아직 뜨는 중일 수 있어 이 시간까지 기다려 본다(두 번 누르기 쉬운 몇 초 — 느린 PC 의 첫 실행 포함)
POLL_SECONDS = 0.25
RESTORE_TRIES = 20                                               # 최소화된 창을 되살리는 것은 비동기라 풀릴 때까지 (RESTORE_TRIES x RESTORE_POLL = 1초) 기다린다
RESTORE_POLL = 0.05
ALREADY_OPEN_TEXT = ("{name} 이 이미 열려 있거나 열리는 중이에요.\n"
                     "작업 표시줄에서 열려 있는 창을 눌러 보세요.\n"
                     "한참 지나도 창이 보이지 않으면 작업 관리자(Ctrl+Shift+Esc)에서 {name} 을 찾아 끝낸 뒤 다시 열어 주세요.")

_HELD = {}                                                       # 이름 → 쥔 핸들(`_Hold`). 이 프로세스가 끝날 때까지 쥔다 — 핸들을 놓으면 OS 가 '열려 있음' 을 지운다
_state = {"note": "", "api": None}


def last_note():
    """마지막 판정의 짧은 이유(`first`·`held`·`sample`·`not_windows`·`create_mutex:OSError` 처럼 종류 이름뿐 — 경로·값은 담지 않는다). 화면에 보이지 않고 시험이 읽는다."""
    return _state["note"]


def _note(where, error=None):
    _state["note"] = where if error is None else f"{where}:{type(error).__name__}"


# ---- 이름 만들기(순수 — 어느 운영체제에서든 같은 결과) -----------------------------------------------------------------------------------------

def normalized_folder(folder_text):
    """폴더 경로를 비교용 글로 맞춘다 — 소문자·구분자는 윈도 방식 하나(슬래시도 같은 것으로)·`..` 접기·끝 구분자 없음. 윈도는 대소문자와 구분자 모양을 가리지 않으므로 같은 폴더의 다른 적기는 같은 글이 된다."""
    return ntpath.normcase(ntpath.normpath(str(folder_text)))


def mutex_name(folder_text):
    """뮤텍스 이름 — 고정 접두 + 맞춘 폴더 경로의 SHA-256 앞 16자리. 데이터 폴더가 다르면 이름이 다르다."""
    digest = hashlib.sha256(normalized_folder(folder_text).encode("utf-8", "replace")).hexdigest()
    return MUTEX_PREFIX + digest[:HASH_LENGTH]


def resolve_folder(data_dir=None, env=None):
    """이 실행이 쓸 사용자 데이터 폴더 — `service/context.py` 의 `Workspace.resolve` 와 같은 우선순위(`--data-dir` > 환경 변수 `CHANCEBLOG_DESKTOP_DATA` > `%LOCALAPPDATA%/ChanceblogDesktop`).
    폴더를 만들지도 읽지도 않는다(없어도 된다). 이어서 `realpath` 로 정션·짧은 이름(8.3)·상대 경로를 풀어 같은 폴더가 같은 글이 되게 한다(풀 수 없으면 그대로)."""
    env = os.environ if env is None else env
    chosen = data_dir or env.get(ENV_DATA_DIR)
    if not chosen:
        base = env.get("LOCALAPPDATA") or ntpath.join(str(Path.home()), "AppData", "Local")
        chosen = ntpath.join(base, APP_DIR_NAME)
    path = os.path.expanduser(str(chosen))
    try:
        path = os.path.realpath(path)
    except (OSError, ValueError):
        _note("realpath")
    return path


# ---- 쥐고 있기 ------------------------------------------------------------------------------------------------------------------------------

class _Hold:
    """뮤텍스 핸들 하나를 쥔다 — 쥔 동안 이 이름은 '열려 있음' 이다. 놓으면(`release`) 핸들을 닫아 자리가 비게 한다. 반드시 모듈 전역(`_HELD`)에 보관한다 — 지역 변수에만 두면 반환 즉시 사라진다
    (핸들이 가비지 수집 때 스스로 닫히는 종류이면 그 순간 뮤텍스가 풀려 장치가 무력해진다. 시험이 그런 가짜 핸들로 못박는다)."""

    def __init__(self, api, handle):
        self._api, self._handle = api, handle

    def release(self):
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                self._api.close_handle(handle)
            except Exception as error:      # noqa: BLE001 - 닫기 실패는 어차피 OS 가 프로세스 종료 때 치운다
                _note("close", error)


def release_all():
    """쥔 뮤텍스를 모두 놓는다(시험 뒷정리용 — 앱은 프로세스가 끝날 때 OS 가 치운다)."""
    holds = list(_HELD.values())
    _HELD.clear()
    for hold in holds:
        hold.release()


# ---- 윈도 호출 층(ctypes) — 이 모듈에서 ctypes 를 가져오는 유일한 곳 --------------------------------------------------------------------------------

class Win32Api:
    """윈도 호출을 한곳에 모은 얇은 층 — 판단은 하지 않는다(판단은 아래 함수들). 다른 코드가 쓰는 `ctypes.windll` 공용 함수의 인자 모양을 건드리지 않으려고 이 층 전용 DLL 객체를 따로 연다.
    윈도가 아니면 만들 때 오류가 난다(`default_api` 가 None 으로 바꾼다). 모든 핸들·창 번호는 정수로 주고받는다."""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    GW_OWNER = 4
    SW_RESTORE = 9
    MESSAGE_BOX_FLAGS = 0x00010040              # 확인 단추 + 정보 그림 + 앞으로(SETFOREGROUND)
    FLASH_FLAGS = 0x0000000F                    # 제목과 작업 표시줄 단추를 창이 앞으로 올 때까지 깜박인다(ALL | TIMERNOFG)
    TEXT_MAX = 512
    PATH_MAX = 32768

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ctypes, self._wintypes = ctypes, wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class FlashInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

        self._flash_info = FlashInfo
        self._enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        user32.EnumWindows.argtypes = [self._enum_proc, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.IsHungAppWindow.argtypes = [wintypes.HWND]
        user32.IsHungAppWindow.restype = wintypes.BOOL
        user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindowAsync.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.FlashWindowEx.argtypes = [ctypes.POINTER(FlashInfo)]
        user32.FlashWindowEx.restype = wintypes.BOOL
        user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
        user32.MessageBoxW.restype = ctypes.c_int
        self._kernel32, self._user32 = kernel32, user32

    # 뮤텍스
    def create_mutex(self, name):
        """(핸들 또는 None, 마지막 오류 번호). 호출 전에 오류 번호를 0 으로 비워 두어 앞선 호출의 찌꺼기가 '이미 있음(183)' 으로 읽히지 않게 한다."""
        self._ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, False, name)
        error = self._ctypes.get_last_error()
        return (int(handle) if handle else None), int(error)

    def close_handle(self, handle):
        self._kernel32.CloseHandle(handle)

    # 창 찾기
    def image_path(self, pid):
        """그 프로세스의 실행 파일 경로(읽을 수 없으면 None)."""
        handle = self._kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            buffer = self._ctypes.create_unicode_buffer(self.PATH_MAX)
            size = self._wintypes.DWORD(self.PATH_MAX)
            if not self._kernel32.QueryFullProcessImageNameW(handle, 0, buffer, self._ctypes.byref(size)):
                return None
            return buffer.value
        finally:
            self._kernel32.CloseHandle(handle)

    def top_windows(self):
        """보이는 최상위 창들 — [(창 번호, 제목, 프로세스 번호, 소유 창 번호(없으면 0), 보임)]. 창 하나를 읽다 난 오류는 그 창만 건너뛴다."""
        found = []
        text = self._ctypes.create_unicode_buffer(self.TEXT_MAX)
        pid = self._wintypes.DWORD()
        user32 = self._user32

        def visit(hwnd, _parameter):
            try:
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextW(hwnd, text, self.TEXT_MAX)
                    user32.GetWindowThreadProcessId(hwnd, self._ctypes.byref(pid))
                    owner = user32.GetWindow(hwnd, self.GW_OWNER)
                    found.append((int(hwnd), text.value if length > 0 else "", int(pid.value), int(owner or 0), True))
            except Exception as error:      # noqa: BLE001 - 콜백 밖으로 예외를 내보내지 않는다(그 창만 건너뛴다)
                _note("window", error)
            return True

        user32.EnumWindows(self._enum_proc(visit), 0)
        return found

    # 앞으로 가져오기
    def is_hung(self, hwnd):
        return bool(self._user32.IsHungAppWindow(hwnd))

    def is_iconic(self, hwnd):
        return bool(self._user32.IsIconic(hwnd))

    def restore(self, hwnd):
        """최소화된 창을 되살린다 — 비동기(`ShowWindowAsync`)라 상대 창이 멈춰 있어도 이쪽이 기다리지 않는다."""
        return bool(self._user32.ShowWindowAsync(hwnd, self.SW_RESTORE))

    def activate(self, hwnd):
        self._user32.BringWindowToTop(hwnd)
        return bool(self._user32.SetForegroundWindow(hwnd))

    def foreground(self):
        handle = self._user32.GetForegroundWindow()
        return int(handle) if handle else 0

    def flash(self, hwnd):
        info = self._flash_info(self._ctypes.sizeof(self._flash_info), hwnd, self.FLASH_FLAGS, 0, 0)
        return bool(self._user32.FlashWindowEx(self._ctypes.byref(info)))

    def message_box(self, title, text):
        self._user32.MessageBoxW(None, text, title, self.MESSAGE_BOX_FLAGS)


def default_api(platform=None):
    """진짜 윈도 호출 층(한 번 만들어 둔다) — 윈도가 아니거나 DLL 을 열 수 없으면 None(장치 끔)."""
    if (sys.platform if platform is None else platform) != "win32":
        return None
    if _state["api"] is None:
        try:
            _state["api"] = Win32Api()
        except Exception as error:      # noqa: BLE001 - 호출 층을 못 만들면 판정을 못 하므로 장치를 끈 채 지나간다
            _note("api", error)
            return None
    return _state["api"]


# ---- 열린 창 찾기·앞으로 가져오기(층을 끼워 시험하는 순수 논리) --------------------------------------------------------------------------------

def same_file(path_a, path_b):
    """윈도 경로 둘이 같은 파일을 가리키는가 — 대소문자·구분자·`..` 만 맞춘다(운영체제에서 받은 실행 파일 경로끼리라 이 정도면 된다)."""
    return ntpath.normcase(ntpath.normpath(str(path_a))) == ntpath.normcase(ntpath.normpath(str(path_b)))


def find_window(api, title, own_pid, own_image):
    """이미 열린 앱의 창 번호(없으면 None) — 보이는 최상위 창(소유 창 없음)이고, 제목이 `title` 로 시작하고, **같은 실행 파일 경로의 다른 프로세스**가 가진 것만."""
    for hwnd, text, pid, owner, visible in api.top_windows():
        if not visible or owner or pid == own_pid or not text.startswith(title):
            continue
        other = api.image_path(pid)
        if other and same_file(other, own_image):
            return hwnd
    return None


def bring_to_front(api, hwnd, sleep):
    """창을 앞으로 가져온다 — 최소화돼 있을 때만 되살리고(최대화한 창을 줄이지 않는다) `front`·`flashed`(앞으로는 못 왔지만 작업 표시줄이 깜박임)·`failed` 를 돌려준다."""
    if api.is_iconic(hwnd):
        api.restore(hwnd)
        for _ in range(RESTORE_TRIES):
            if not api.is_iconic(hwnd):
                break
            sleep(RESTORE_POLL)
    api.activate(hwnd)
    if api.foreground() == hwnd:
        return "front"
    return "flashed" if api.flash(hwnd) else "failed"


def reveal(api, title, *, wait, poll, sleep, monotonic, retake=None):
    """이미 열린 창을 찾아(첫 창이 뜨는 중이면 `wait` 초까지 기다린다) 앞으로 가져온다 — `front`·`flashed`(성공), `took_over`(기다리는 사이 먼저 열려 있던 앱이 끝나 뮤텍스가 비었고 `retake` 가 그것을 넘겨받았다 —
    이제 이 프로세스가 첫 실행이다), 또는 `no_image`·`no_window`·`not_responding`·`failed`(안내 상자가 필요한 경우)."""
    own_pid = os.getpid()
    own_image = api.image_path(own_pid)
    if not own_image:
        return "no_image"                                       # 내 실행 파일 경로를 모르면 어느 창이 같은 앱의 것인지 가릴 수 없다 — 기다려도 소용없다
    deadline = monotonic() + wait
    while True:
        hwnd = find_window(api, title, own_pid, own_image)
        if hwnd is not None:
            break
        if retake is not None and retake():
            return "took_over"                                  # 방금 닫은 앱이 아직 끝나는 중이었다 — 창이 없어 안내 상자를 보이는 대신 이 프로세스가 새 첫 실행이 된다
        if monotonic() >= deadline:
            return "no_window"
        sleep(poll)
    if api.is_hung(hwnd):
        return "not_responding"
    return bring_to_front(api, hwnd, sleep)


def _window_title():
    from .core.text import T
    return str(T["window_title"])                               # 앱의 실제 창 제목 상수(`ui/qt/shell.py` 의 `setWindowTitle(T["window_title"])`) — 글자를 따로 적지 않는다


def _announce(api, wait, poll, sleep, monotonic, retake=None):
    """이미 열려 있음을 사용자에게 알린다 — 창을 앞으로 가져오고, 안 되면 안내 상자. 어떤 오류도 밖으로 내보내지 않는다(이미 열려 있음이 확인된 뒤에는 새 창을 열지 않는다 — 단 기다리는 사이 먼저 열려 있던 앱이
    끝나 뮤텍스를 `retake` 가 넘겨받았다면 `took_over`: 열려 있는 창이 하나도 없으므로 이 프로세스가 새 첫 실행이다)."""
    outcome = "failed"
    title = ""
    try:
        title = _window_title()
        outcome = reveal(api, title, wait=wait, poll=poll, sleep=sleep, monotonic=monotonic, retake=retake)
    except Exception as error:      # noqa: BLE001
        _note("reveal", error)
    if outcome in ("front", "flashed", "took_over"):
        _note(outcome)
        return outcome
    try:
        api.message_box(title, ALREADY_OPEN_TEXT.format(name=title))
        _note(outcome)
    except Exception as error:      # noqa: BLE001 - 안내 상자도 못 보이면 조용히 끝난다(이미 열린 앱이 있다는 것은 확인됐다)
        _note("message_box", error)
    return outcome


# ---- 앱이 부르는 곳 ---------------------------------------------------------------------------------------------------------------------------

def claim(data_dir=None, *, sample=False, env=None, platform=None, api=None, sleep=None, monotonic=None):
    """이 프로세스가 창을 열어도 되는가 — `True`: 첫 실행이거나 장치가 꺼진 경우, 또는 기다리는 사이 먼저 열려 있던 앱이 끝나 뮤텍스를 넘겨받은 경우(창을 연다). `False`: 같은 데이터 폴더로 이미 열린 앱이 있어 그 창을 앞으로 가져오는 일까지 끝냈다 — 부른 쪽은
    새 창을 만들지 않고 조용히 끝낸다(종료 코드 0). 예외를 내지 않는다. 같은 프로세스가 이미 쥔 이름은 통과로 친다(한 프로세스는 한 번만 부르는 것이 정상이고, 같은 프로세스 안의 시험 호출을 위해서다)."""
    try:
        return _claim(data_dir, sample, env, platform, api, sleep, monotonic)
    except Exception as error:      # noqa: BLE001 - 판정 도중 예상 못 한 오류 — 장치를 끈 채 지나간다(앱을 막지 않는다)
        _note("claim", error)
        return True


def _claim(data_dir, sample, env, platform, api, sleep, monotonic):
    if sample:
        _note("sample")
        return True                                             # 예시 화면은 아무 파일에도 쓰지 않는다 — 따로 열 수 있다
    if (sys.platform if platform is None else platform) != "win32":
        _note("not_windows")
        return True
    name = mutex_name(resolve_folder(data_dir, env))
    if name in _HELD:
        _note("held")
        return True
    api = default_api(platform) if api is None else api
    if api is None:
        return True
    try:
        handle, error = api.create_mutex(name)
    except Exception as failure:      # noqa: BLE001
        _note("create_mutex", failure)
        return True
    if not handle:
        _note(f"create_mutex_failed:{error}")                   # 예: 다른 사용자가 같은 세션에서 만든 이름(접근 거부) — 판정이 서지 않으면 막지 않는다
        return True
    if error != ERROR_ALREADY_EXISTS:
        _HELD[name] = _Hold(api, handle)
        _note("first")
        return True
    _close_copy(api, handle)                                    # 우리 쪽 사본만 닫는다 — 먼저 연 프로세스의 뮤텍스는 그대로다

    def retake():
        """기다리는 사이 먼저 열려 있던 앱이 끝났으면(방금 닫고 곧바로 다시 연 경우) 뮤텍스를 넘겨받는다 — 넘겨받았으면 True. 아직 있으면 우리 쪽 사본만 닫고 False."""
        try:
            again, number = api.create_mutex(name)
        except Exception as failure:      # noqa: BLE001
            _note("retake", failure)
            return False
        if not again:
            return False
        if number == ERROR_ALREADY_EXISTS:
            _close_copy(api, again)
            return False
        _HELD[name] = _Hold(api, again)
        return True

    outcome = _announce(api, WAIT_SECONDS, POLL_SECONDS, time.sleep if sleep is None else sleep, time.monotonic if monotonic is None else monotonic, retake)
    return outcome == "took_over"


def _close_copy(api, handle):
    try:
        api.close_handle(handle)
    except Exception as failure:      # noqa: BLE001 - 닫기 실패는 어차피 OS 가 프로세스 종료 때 치운다
        _note("close", failure)
