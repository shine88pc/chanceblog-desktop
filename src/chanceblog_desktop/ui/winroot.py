"""윈도 폴더를 **윈도에 직접 묻는** 읽기 전용 도우미(결정 D-593 — 글자 읽기 감사 R3 의 검증 SQ 참고 4).
환경 변수 `SystemRoot` 는 앱을 띄운 쪽이 정하므로 그대로 믿지 않는다 — 윈도가 `GetSystemWindowsDirectoryW` 로 알려 주는 값과 견준다(`ui/ocr_adapter.py` 의 `taskkill_path` 가 쓴다).
하는 일은 그 한 번의 읽기뿐이다: 쓰기·하위 프로세스·네트워크가 없다. 윈도가 아니면(`os.name` 이 `nt` 가 아니면) `ctypes` 를 가져오지도 부르지도 않고 None 을 돌려준다.
"""
from __future__ import annotations

import ntpath
import os

_MAX_PATH = 260                                  # 윈도 폴더 이름은 이보다 짧다 — 더 길게 돌아오면 못 믿고 None(부르는 쪽이 환경 값·기본 폴더로 간다)


def is_drive_absolute(path):
    """드라이브 글자(영문 한 글자)로 시작하는 절대 경로(`C:` 다음에 구분자)인가 — 상대 경로·네트워크 위치·장치 경로·`C:Windows`·글이 아닌 값은 아니다."""
    drive, rest = ntpath.splitdrive(path) if isinstance(path, str) else ("", "")
    return len(drive) == 2 and drive[1] == ":" and drive[0].isascii() and drive[0].isalpha() and rest[:1] in ("\\", "/")


def same_folder(first, second):
    """같은 폴더를 가리키는 두 글인가 — 대소문자·구분자 모양·끝 구분자·`..` 를 정리해서 견준다(글자만 닮은 다른 폴더는 같지 않다)."""
    return ntpath.normcase(ntpath.normpath(first)) == ntpath.normcase(ntpath.normpath(second))


def windows_directory():
    """윈도가 알려 주는 윈도 폴더(`GetSystemWindowsDirectoryW`) 또는 None — 윈도가 아니거나·부를 수 없거나·0 이나 너무 큰 길이가 돌아오거나·값이 드라이브 글자 절대 경로가 아니면 None."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        ask = kernel.GetSystemWindowsDirectoryW
        ask.restype = ctypes.c_uint32
        ask.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        buffer = ctypes.create_unicode_buffer(_MAX_PATH)
        length = ask(buffer, _MAX_PATH)
        value = buffer.value
    except Exception:
        return None
    if not 0 < length < _MAX_PATH or not is_drive_absolute(value):
        return None
    return value


__all__ = ["is_drive_absolute", "same_folder", "windows_directory"]
