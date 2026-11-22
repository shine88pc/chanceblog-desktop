"""진단 정보 한 번에 복사(L3 의 F035, 결정 D-539 에서 D-541) — 문제가 생겼을 때 운영자·AI 에게 보낼 **짧은 글**을 만드는 순수 규칙. PySide6·파일·네트워크를 쓰지 않는다.

담는 것은 다섯 가지뿐이다(`FIELDS`): 앱 버전 · 빌드 커밋(앞 7자리) · Windows 빌드 번호 · 화면 배율 · 마지막 오류 코드. 글은 머리 한 줄(`ChanceBlog Desktop 진단 정보`)과 `이름: 값` 다섯 줄이다.
**담지 않는 것**: 사용자 이름·폴더 경로·블로그 이름·글 내용·키·토큰·초안 번호·오류 메시지 글. 이 규칙은 '값을 걸러 내는' 것이 아니라 **값마다 좁은 글자표 하나를 통과한 것만 쓰는** 것이다 —
버전은 `v0.1.0-preview.1` 꼴, 커밋은 16진수 7자리, 윈도 빌드는 숫자 3–6자리, 배율은 50–600 의 정수 백분율, 오류 코드는 영문·숫자·밑줄 48자 이하(`GIT_PUSH_AUTH`·`TypeError` 같은 코드·예외 이름)뿐이다.
통과하지 못하면(경로·이름·메시지 글·키 모양이 와도) 그 칸은 `unknown` 이 되고 입력은 어디에도 남지 않는다. 글자표를 통과한 값도 공통 가림(`display_text`)이 한 글자라도 바꾸면 `unknown` 이다(`security/errorlog.py` 의
'이름과 코드 위치만' 규칙과 같은 방향 — 더 느슨하지 않다). 어떤 입력이 와도 예외를 내지 않는다(이상한 객체·글·숫자 모두 `unknown`).

읽는 곳이 둘 있다. Windows 빌드 번호는 `sys.getwindowsversion`(윈도에만 있다 — 리눅스·시험 환경에서는 없어서 None 이 되고 가져오기도 안전하다, `ctypes`·하위 프로세스·파일 읽기 없음),
화면 배율은 Qt 를 아는 앱 틀(`ui/qt/shell.py`)이 화면의 `devicePixelRatio` 를 읽어 `scale_percent` 로 바꿔 넘긴다 — 이 순수 모듈은 Qt 를 모른다.
복사는 기존 복사 길(앱 틀의 `copy`)이 하고 이 모듈은 글만 만든다.
"""
from __future__ import annotations

import re
import sys

from .text import T, display_text

FIELDS = ("version", "commit", "windows_build", "display_scale", "last_error_code")      # 복사되는 글의 이름 다섯 — 이 밖의 이름은 글에 없다(시험이 못박는다)
UNKNOWN = "unknown"                                                                       # 못 읽었거나 모양이 맞지 않은 칸
NONE = "none"                                                                             # 오류가 하나도 없을 때의 마지막 오류 코드 칸
DEV = "dev"                                                                               # 버전 파일을 못 읽은 개발 화면의 버전 칸(화면의 '개발 버전')
SCALE_RANGE = (50, 600)                                                                   # 받아들이는 화면 배율(%) — 윈도의 100–500% 설정과 그 사이 값
_VERSION = re.compile(r"v[0-9]{1,5}[.][0-9]{1,5}[.][0-9]{1,5}(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?")
_COMMIT = re.compile(r"[0-9a-f]{7}")
_BUILD = re.compile(r"[0-9]{3,6}")
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}")


def _shape(value, pattern):
    """글자표(`pattern`)를 통과하고 공통 가림이 한 글자도 바꾸지 않는 글이면 그 글, 아니면 None — 글이 아닌 값·이상한 객체도 None. **정확한 `str` 만** 받는다:
    `str` 의 하위 클래스는 `__format__`·`__str__` 을 바꿔 글자표를 통과한 뒤 다른 글로 찍힐 수 있다(실제 입력 길은 모두 정확한 `str` 이다)."""
    try:
        if type(value) is not str or not pattern.fullmatch(value):
            return None
        return value if display_text(value, len(value) + 1) == value else None
    except Exception:
        return None


def version_text(info):
    """앱 버전 칸 — 버전을 읽은 앱(`VersionInfo.source == "file"`)이면 `v0.1.0-preview.1` 꼴인 글, 못 읽은 개발 화면이거나 버전 정보가 없으면 `dev`, 글이 그 꼴이 아니면 `unknown`."""
    try:
        if info is None or getattr(info, "source", None) != "file":
            return DEV
        return _shape(getattr(info, "text", None), _VERSION) or UNKNOWN
    except Exception:
        return UNKNOWN


def commit_text(info):
    """빌드 커밋 칸 — 묶음 빌드의 정보 파일을 읽었을 때만 있는 앞 7자리(`VersionInfo.commit`). 없거나 16진수 7자리가 아니면 `unknown`(긴 글을 잘라 쓰지 않는다)."""
    try:
        return _shape(getattr(info, "commit", None), _COMMIT) or UNKNOWN
    except Exception:
        return UNKNOWN


def build_text(value):
    """Windows 빌드 번호 칸 — 정수(또는 숫자만 있는 글) 3–6자리. 윈도가 아니거나 못 읽었으면 `unknown`."""
    try:
        if isinstance(value, bool):
            return UNKNOWN
        return _shape(str(value) if type(value) is int else value, _BUILD) or UNKNOWN
    except Exception:
        return UNKNOWN


def scale_text(percent):
    """화면 배율 칸 — `SCALE_RANGE` 안의 정수 백분율을 `150%` 꼴로. 정수가 아니거나 범위 밖이면 `unknown`."""
    try:
        if type(percent) is not int:                                                      # 정확한 int 만(bool·int 하위 클래스는 `unknown`)
            return UNKNOWN
        low, high = SCALE_RANGE
        return f"{percent}%" if low <= percent <= high else UNKNOWN
    except Exception:
        return UNKNOWN


def code_text(code):
    """마지막 오류 코드 칸 — 오류가 하나도 없으면(`None`) `none`, 코드가 영문·숫자·밑줄 48자 이하이면 그 코드, 그 밖(빈 코드·메시지 글·경로·키 모양)은 `unknown`.
    **오류의 메시지 글은 받지도 않는다** — 받는 것은 코드(`JobFailure.code` 같은 이름)뿐이다."""
    try:
        if code is None:
            return NONE
        return _shape(code, _CODE) or UNKNOWN
    except Exception:
        return UNKNOWN


def _moment(value):
    try:
        return float(value.timestamp())
    except Exception:
        return float("-inf")                                                              # 시각이 없거나 비교할 수 없으면 가장 오래된 것으로 본다


def latest_failure_code(slots):
    """`(실패, 시각)` 쌍들 가운데 실패가 남아 있는 것 중 시각이 가장 늦은 것의 코드 글(없으면 빈 글) — 남은 실패가 하나도 없으면 None. 시각이 같거나 없으면 앞선 칸이 이긴다.
    '남아 있는 실패' 는 지금 화면 상태가 들고 있는 것이다(나아져서 지워진 실패는 없다). 코드를 읽을 수 없으면 빈 글(`code_text` 가 `unknown` 으로 바꾼다)."""
    best, best_key = None, float("-inf")
    try:
        for failure, when in slots:
            if failure is None:
                continue
            key = _moment(when)
            if best is None or key > best_key:
                best, best_key = failure, key
        if best is None:
            return None
        code = getattr(best, "code", "")
        return code if isinstance(code, str) else ""
    except Exception:
        return ""


def build_report(version=None, windows_build=None, scale_percent=None, error_code=None):
    """복사되는 글 — 머리 한 줄 + `이름: 값` 다섯 줄(`FIELDS` 순서). 모든 값은 위의 `…_text` 규칙을 거친다(주입받은 값이 무엇이든 글자표 밖의 것은 `unknown`).
    `version` 은 `VersionInfo` 같은 값(없으면 개발 화면), `windows_build` 는 정수, `scale_percent` 는 정수 백분율, `error_code` 는 코드 글(오류가 없으면 None)이다."""
    values = (version_text(version), commit_text(version), build_text(windows_build), scale_text(scale_percent), code_text(error_code))
    return "\n".join([f"{T['brand_version']} {T['diag_title']}", *(f"{name}: {value}" for name, value in zip(FIELDS, values))])


def windows_build_number(getter=None):
    """이 PC 의 Windows 빌드 번호(정수) — 윈도가 아니거나 못 읽으면 None. 윈도에만 있는 `sys.getwindowsversion`(주입 가능 — 시험은 가짜를 넣는다)을 부를 뿐이라 리눅스에서도 가져오기·호출이 안전하다.
    두 값 중 **큰 쪽**을 쓴다: `build`(운영체제가 알려 주는 빌드 — 윈도 호환 설정이 걸린 프로그램에서는 낮게 나올 수 있다)와 `platform_version` 의 세 번째 칸(커널 파일의 버전 — 반대로 기능 업데이트가 쌓인 PC 에서는 기반 빌드가 남아 낮을 수 있다).
    이 PC 의 예: `build` 22631(`winver` 와 같다)·`platform_version` 22621 → 22631. 새 프로세스·파일·외부 접속은 없다."""
    try:
        read = getter if getter is not None else getattr(sys, "getwindowsversion", None)
        if read is None:
            return None
        info = read()
        real = getattr(info, "platform_version", None)
        found = [getattr(info, "build", None), real[2] if isinstance(real, tuple) and len(real) >= 3 else None]
        builds = [number for number in found if type(number) is int and 0 < number < 1_000_000]
        return max(builds) if builds else None
    except Exception:
        return None


def scale_percent(ratio):
    """Qt 화면의 `devicePixelRatio`(1.0·1.25·1.5 …)를 정수 백분율로 — 숫자가 아니거나 `SCALE_RANGE` 밖(NaN·무한대 포함)이면 None."""
    try:
        if type(ratio) not in (int, float):                                               # 정확한 int·float 만(bool·하위 클래스는 None)
            return None
        percent = round(ratio * 100)
        low, high = SCALE_RANGE
        return percent if low <= percent <= high else None
    except Exception:
        return None


__all__ = ["DEV", "FIELDS", "NONE", "SCALE_RANGE", "UNKNOWN", "build_report", "build_text", "code_text", "commit_text", "latest_failure_code", "scale_percent", "scale_text", "version_text", "windows_build_number"]
