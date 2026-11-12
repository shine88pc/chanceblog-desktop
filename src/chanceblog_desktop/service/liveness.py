"""프로세스가 지금 살아 있는지 — 잠금 파일을 남긴 작업이 이미 죽었는지 보려고 쓴다(읽기만 한다. 프로세스를 끝내거나 건드리지 않는다).

PC 가 갑자기 꺼지거나 창을 닫아 작업이 죽으면 잠금 파일이 남는다. 그 프로세스가 이미 없다는 것을 알면 30분을 기다리지 않고 바로 넘겨받을 수 있다.
 · Windows: `OpenProcess`(상태를 읽는 권한 `PROCESS_QUERY_LIMITED_INFORMATION` 뿐 — 끝내거나 바꾸는 권한이 아니다)·`GetExitCodeProcess`·`GetProcessTimes` 로 본다.
   번호는 재사용되므로 그 프로세스가 **잠금을 잡은 시각보다 나중에 시작했다면** 그 번호를 이어받은 다른 프로세스로 보고 '없다' 로 친다.
   Windows 에서 `os.kill(pid, 0)` 은 프로세스를 끝내 버리므로 절대 쓰지 않는다.
 · 그 밖의 운영체제: `os.kill(pid, 0)`(신호 0 — 있는지만 보고 아무것도 보내지 않는다).
알 수 없으면(None) 살아 있다고 보고 시간 기준(30분)만 쓴다 — 확신이 없으면 넘겨받지 않는다.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

_STILL_ACTIVE = 259
_QUERY_LIMITED = 0x1000            # PROCESS_QUERY_LIMITED_INFORMATION
_NO_SUCH_PROCESS = 87              # ERROR_INVALID_PARAMETER — 그 번호의 프로세스가 없다
_REUSE_SLACK = timedelta(seconds=5)
_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def host_name():
    """이 PC 의 이름 — 잠금 파일에 적어 '같은 PC 에서 시작한 잠금' 인지 가린다(읽기만 한다). `platform.node()` 는 쓰지 않는다: Windows 에서 `platform` 모듈이 OS 버전을 읽으려고
    하위 프로세스(`cmd /c ver`)를 띄울 수 있다(PCSEC1 H3 'Network Write 0' 시험이 찾았다 — 이 앱은 하위 프로세스를 띄우지 않는다). Windows 는 `GetComputerNameW`, 그 밖은 `os.uname`. 알 수 없으면 ''."""
    if os.name == "nt":
        try:
            import ctypes
            buffer = ctypes.create_unicode_buffer(256)
            size = ctypes.c_uint32(len(buffer))
            if ctypes.WinDLL("kernel32").GetComputerNameW(buffer, ctypes.byref(size)):
                return buffer.value
        except (OSError, AttributeError, ValueError):
            return ""
        return ""
    try:
        return os.uname().nodename
    except (AttributeError, OSError):
        return ""


def process_alive(pid, started):
    """그 번호의 프로세스가 같은 PC 에서 `started`(잠금을 잡은 시각) 이전부터 지금도 살아 있는가 →
    True · False(없거나 이미 끝났거나, 그 번호를 나중에 다른 프로세스가 받았다) · None(알 수 없다)."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None                    # 0·음수는 프로세스 그룹을 가리킬 수 있다 — 보지 않는다
    if pid == os.getpid():
        return True
    return _windows(pid, started) if os.name == "nt" else _posix(pid)


def _posix(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                    # 있지만 내 것이 아니다
    except OSError:
        return None
    return True


def _windows(pid, started):
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                                             ctypes.POINTER(wintypes.FILETIME))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(_QUERY_LIMITED, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == _NO_SUCH_PROCESS else None          # 5(접근 거부)는 '있지만 열 수 없다' — 모른다
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            if code.value != _STILL_ACTIVE:
                return False           # 이미 끝났다(다른 프로그램이 손잡이를 쥐고 있어 프로세스 개체만 남은 경우)
            created, spare1, spare2, spare3 = (wintypes.FILETIME() for _ in range(4))
            if kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(spare1), ctypes.byref(spare2), ctypes.byref(spare3)):
                ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime           # 1601-01-01 부터 100 나노초 단위
                if _EPOCH + timedelta(microseconds=ticks // 10) > started + _REUSE_SLACK:
                    return False       # 잠금을 잡은 뒤에 시작한 프로세스 — 그 번호를 이어받은 다른 프로세스다
            return True
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError, OverflowError):
        return None
