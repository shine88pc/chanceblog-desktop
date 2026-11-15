"""오류 기록 — 앱이 처리하지 못한 오류가 났을 때 **오류 이름과 코드 위치만** 데이터 폴더의 작은 파일에 남긴다(AP14, 확인 015 승인 9번, 결정 D-488).

왜: 창 없는 실행 파일(더블클릭)에는 표준 오류가 없어 처리하지 못한 오류가 어디에도 남지 않았다(`report_unexpected` 는 `False` 를 돌려줄 뿐이다). 운영자가 문제를 알릴 때 보여 줄 것이 없었다.

남기는 것은 한 줄이다: `시각(UTC) 갈래 오류이름 파일:줄 < 파일:줄 …`(가장 안쪽 위치부터 최대 여섯).
  · **오류 메시지 글·값·경로·키·토큰·글 본문은 남기지 않는다.** 메시지는 읽지도 않는다 — 읽는 것은 오류의 **클래스 이름**과 추적(traceback)의 **파일 이름(폴더 없이)·줄 번호**뿐이다.
    그 이름들도 아래의 좁은 글자표(영문·숫자·밑줄·점·붙임표)를 통과한 것만 줄에 들어가고, 통과하지 못하면 `?` 나 `UnknownError` 로 바꾼다.
  · 완성한 줄은 앱의 공통 가림 규칙(`security/mask.py` 의 `mask`)을 한 번 더 거친다 — 이 모듈에는 새 가림 규칙이 없다.
  · 사용자 이름이 든 절대 경로는 줄에도 파일 어디에도 없다(파일 이름 앞의 폴더는 떼고, 기록 파일 자신의 위치도 줄에 적지 않는다).

언제 만드는가: **첫 오류가 났을 때 처음 만든다.** `arm()`(켜 두기)은 아무것도 읽거나 만들지 않는다 — 앱을 켜기만 해서는 폴더도 파일도 생기지 않는다. 위치는 앱이 쓰는 데이터 폴더 해석 함수가 정한 폴더의 `logs/errors.log`(+ 돌려쓰기 `errors.log.1`·`errors.log.2`)이고,
이 모듈은 폴더 계산을 하지 않고 부른 쪽이 건넨 '폴더 알려 주기' 함수만 부른다. 파일 하나는 256 KB 를 넘지 않고 모두 세 개를 넘지 않는다(`errors.log.2` 가 가장 오래된 것이다).

**어떤 일이 있어도 앱을 멈추지 않는다.** 쓰기 실패(디스크 가득·권한·이름 바꾸기 막힘)·폴더 해석 실패는 모두 삼키고 그 줄만 버린다(돌려쓰기에 실패하면 한도를 넘기지 않으려고 그 줄을 쓰지 않고, 옛 파일은 먼저 지우지 않으므로 가장 오래된 `.2` 도 잃지 않는다 — 이름 바꾸기가 `.2` 를 덮어쓴다). 같은 시간에 오류가 쏟아져도(그리기 오류가 계속 되풀이될 때) 정해진 1분 구간마다 30줄까지만 쓴다(구간은 첫 줄이 쓰일 때 시작하고, 구간 경계에서는 짧은 시간에 더 나올 수 있다).
네트워크·외부 쓰기·하위 프로세스·표준 출력·표준 오류는 쓰지 않는다(파일은 데이터 폴더 안 한 곳뿐). `faulthandler`·미니덤프 같은 충돌 덤프는 만들지 않는다 — 가림을 걸 수 없는 글이 파일에 들어갈 수 있기 때문이다(그래서 네이티브 충돌은 기록되지 않는다).
백업에는 넣지 않는다(`security/backup_note.py` 의 담지 않는 것 목록에 `logs/` 가 있다).

켜는 곳은 화면(GUI) 진입점 하나다(`security/boundary.arm_error_log` — 명령줄과 예시 화면은 켜지 않는다. `--sample` 없이 `launcher.main` 을 끝까지 부르는 기존 시험은 켜지지만, 켜기만으로는 아무것도 읽거나 만들지 않고 시험의 뒷정리가 끈다). `boundary` 의 설치를 되돌리면 함께 꺼진다.

**기록이 닿지 않는 길(한계)**: 묶음 실행 파일의 시작 실패(`packaging/gui_entry.py` 의 `start_gui` 가 잡아 메시지 상자로 오류 종류 이름만 알린다)·작업 스레드(`ui/core/jobs.py`)가 삼킨 오류와 화면 콜백 안의 오류·네이티브 충돌·데이터 폴더를 풀지 못하는 경우.
이 길들에 기록을 잇는 일은 AP14 가 바꾸는 목록 밖이라 하지 않았다(D-488 의 후속 항목).
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .mask import mask

FOLDER_NAME = "logs"
FILE_NAME = "errors.log"
MAX_BYTES = 256 * 1024                      # 파일 하나의 한도(바이트) — 이 크기를 넘기게 되면 먼저 돌려쓴다
BACKUPS = 2                                 # 돌려쓰고 남기는 옛 파일 수 — 현재 파일과 합쳐 모두 세 개
MAX_FRAMES = 6                              # 한 줄에 적는 코드 위치 수(가장 안쪽부터)
RATE_COUNT = 30                             # 이 시간 안에 쓰는 줄의 상한
RATE_SECONDS = 60.0
LOCK_WAIT = 1.0                             # 다른 스레드가 쓰는 중일 때 기다리는 가장 긴 시간(초)
SOURCES = ("main", "thread", "unraisable", "slot", "qt")        # 줄의 '갈래' — 어느 출구로 들어왔나(고정 낱말)
QT_RECORDED = ("QtCriticalMsg", "QtFatalMsg")                   # Qt 메시지는 치명적인 둘만 남긴다(경고·정보는 글이 많고 도움이 적다)
_QT_BY_NUMBER = {2: "QtCriticalMsg", 3: "QtFatalMsg"}
_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_FILE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}")
_SEPARATORS = re.compile(r"[\\/]")
_MAX_LINE = 9_999_999
_NOT_RECORDED = (KeyboardInterrupt, SystemExit, GeneratorExit)


def _class_name(kind, value):
    """오류의 클래스 이름 — 글자표를 통과한 것만(아니면 `UnknownError`). 메시지는 읽지 않는다."""
    name = getattr(kind, "__name__", None) if isinstance(kind, type) else None
    if not isinstance(name, str):
        name = type(value).__name__ if isinstance(value, BaseException) else None
    return name if isinstance(name, str) and _CLASS.fullmatch(name) else "UnknownError"


def _short_file(name):
    """파일 이름 — 폴더 앞부분은 떼고(윈도·유닉스 구분자 모두) 글자표를 통과한 것만(아니면 `?`)."""
    last = _SEPARATORS.split(name)[-1] if isinstance(name, str) else ""
    return last if _FILE.fullmatch(last) else "?"


def _line_number(number):
    return number if isinstance(number, int) and not isinstance(number, bool) and 0 <= number <= _MAX_LINE else 0


def _frames(trace):
    """추적 → 코드 위치 목록(가장 안쪽이 먼저, 최대 `MAX_FRAMES`) — `파일:줄` 글자만 만든다. 추적을 만들 수 없으면 빈 목록."""
    found, steps = [], 0
    while trace is not None and steps < 10_000:
        try:
            found.append(f"{_short_file(trace.tb_frame.f_code.co_filename)}:{_line_number(trace.tb_lineno)}")
            trace = trace.tb_next
        except Exception:
            break
        steps += 1
    return found[-MAX_FRAMES:][::-1]


def _trace_of(kind, value, trace):
    """주어진 추적 → 예외 값에 붙은 추적 → (지금 처리 중인 같은 종류의 예외가 있다면) 그 추적."""
    if trace is not None:
        return trace
    own = getattr(value, "__traceback__", None) if isinstance(value, BaseException) else None
    if own is not None:
        return own
    current = sys.exc_info()
    if current[0] is not None and isinstance(kind, type) and issubclass(current[0], kind):
        return current[2]
    return None


class ErrorLog:
    """작은 오류 기록기 하나. `resolve_folder` 는 '데이터 폴더를 알려 주는' 함수(처음 쓸 때 한 번만 부르고 답을 기억한다)다."""

    def __init__(self, resolve_folder, *, clock=None, max_bytes=MAX_BYTES, backups=BACKUPS, rate=(RATE_COUNT, RATE_SECONDS), monotonic=time.monotonic):
        self._resolve = resolve_folder
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_bytes, self._backups = int(max_bytes), int(backups)
        self._rate_count, self._rate_seconds = rate
        self._monotonic = monotonic
        self._folder = None
        self._window_start, self._window_count = None, 0
        self._lock = threading.RLock()

    # ---- 줄 만들기 -----------------------------------------------------------------------------------------------------------------
    def _stamp(self):
        moment = self._clock()
        if getattr(moment, "tzinfo", None) is not None:
            moment = moment.astimezone(timezone.utc)
        return moment.strftime(_STAMP)

    def _build(self, source, name, places):
        label = source if source in SOURCES else "main"
        return mask(f"{self._stamp()} {label} {name} " + (" < ".join(places) if places else "-"))

    # ---- 쓰기 ---------------------------------------------------------------------------------------------------------------------
    def _allowed(self):
        """정해진 1분 구간마다 `RATE_COUNT` 줄까지만(구간은 첫 줄이 쓰일 때 시작한다 — 구간 경계에서는 짧은 시간에 더 나올 수 있다)."""
        now = self._monotonic()
        if self._window_start is None or now - self._window_start >= self._rate_seconds:
            self._window_start, self._window_count = now, 0
        if self._window_count >= self._rate_count:
            return False
        self._window_count += 1
        return True

    def _logs_folder(self):
        if self._folder is None:
            self._folder = Path(self._resolve()) / FOLDER_NAME
        return self._folder

    def _rotate(self, folder):
        """`errors.log` → `.1` → `.2` — 이름을 바꾸는 것뿐이다: 가장 오래된 `.2` 는 먼저 지우지 않고 `os.replace` 가 덮어쓴다(먼저 지우면 이름 바꾸기가 막혔을 때 새 줄도 못 쓰고 `.2` 도 잃는다).
        한 단계라도 막히면 예외를 내서 호출한 쪽이 이 줄을 버리게 한다(한도를 넘겨 쓰지 않는다)."""
        names = [FILE_NAME] + [f"{FILE_NAME}.{number}" for number in range(1, self._backups + 1)]
        if len(names) == 1:                                            # 옛 파일을 하나도 안 남기는 설정 — 현재 파일을 비운다
            (folder / names[0]).unlink(missing_ok=True)
            return
        for index in range(len(names) - 2, -1, -1):
            source = folder / names[index]
            if source.exists():
                os.replace(source, folder / names[index + 1])

    def _append(self, line):
        folder = self._logs_folder()
        folder.mkdir(parents=True, exist_ok=True)                  # 첫 오류가 날 때 처음 만든다
        path = folder / FILE_NAME
        data = (line + "\n").encode("utf-8")
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size > 0 and size + len(data) > self._max_bytes:
            self._rotate(folder)
        with open(path, "ab") as handle:
            handle.write(data)

    def write(self, line):
        """줄 하나를 쓴다(속도 제한·잠금 안에서). 썼으면 True — 어떤 실패도 예외로 내보내지 않는다. 잠금은 같은 스레드가 다시 들어와도(정리 중에 난 오류의 훅) 막히지 않고,
        다른 스레드가 오래 쥐고 있으면 `LOCK_WAIT` 초만 기다리고 그 줄을 버린다(앱이 기록 때문에 멈추지 않게)."""
        if not self._lock.acquire(timeout=LOCK_WAIT):
            return False
        try:
            if not self._allowed():
                return False
            self._append(line)
            return True
        except Exception:
            return False
        finally:
            self._lock.release()

    # ---- 받는 곳 ------------------------------------------------------------------------------------------------------------------
    def record(self, source, kind, value=None, trace=None):
        """처리하지 못한 예외 하나를 남긴다(`KeyboardInterrupt`·`SystemExit` 는 오류가 아니라 남기지 않는다). 썼으면 True."""
        try:
            if isinstance(kind, type) and issubclass(kind, _NOT_RECORDED):
                return False
            return self.write(self._build(source, _class_name(kind, value), _frames(_trace_of(kind, value, trace))))
        except Exception:
            return False

    def record_qt(self, message_type, context):
        """Qt 의 치명적(Critical·Fatal) 메시지 하나 — **메시지 글은 읽지 않고** 종류 이름·분류 이름(`qt.qpa.…`)·C++ 쪽 파일:줄(있을 때)만 남긴다."""
        try:
            name = _qt_type_name(message_type)
            if name not in QT_RECORDED:
                return False
            places = []
            category = getattr(context, "category", None)
            if isinstance(category, str) and _FILE.fullmatch(category):
                places.append(category)
            file_name = getattr(context, "file", None)
            if isinstance(file_name, str) and file_name:
                places.append(f"{_short_file(file_name)}:{_line_number(getattr(context, 'line', 0))}")
            return self.write(self._build("qt", name, places))
        except Exception:
            return False


def _qt_type_name(message_type):
    name = getattr(message_type, "name", None)
    if isinstance(name, str):
        return name
    try:
        return _QT_BY_NUMBER.get(int(message_type), "")
    except (TypeError, ValueError):
        return ""


# ---- 켜 두기(프로세스에 하나) -----------------------------------------------------------------------------------------------------------------
_LOCK = threading.RLock()
_ACTIVE = None


def arm(resolve_folder, **options):
    """기록기를 켠다(이미 켜져 있으면 새것으로 바꾼다) — **아무것도 읽거나 만들지 않는다.** 돌려받은 기록기를 `disarm(log)` 에 주면 끈다."""
    global _ACTIVE
    with _LOCK:
        _ACTIVE = ErrorLog(resolve_folder, **options)
        return _ACTIVE


def disarm(log=None):
    """기록기를 끈다 — `log` 를 주면 그것이 지금 켜진 것일 때만 끈다(다른 설치가 새로 켠 것을 끄지 않는다)."""
    global _ACTIVE
    with _LOCK:
        if log is None or _ACTIVE is log:
            _ACTIVE = None


def active():
    return _ACTIVE


def record_exception(source, kind, value=None, trace=None):
    """켜져 있으면 처리하지 못한 예외를 남긴다(꺼져 있으면 아무 일도 없다). 예외를 내지 않는다."""
    log = _ACTIVE
    return False if log is None else log.record(source, kind, value, trace)


def record_qt(message_type, context):
    """켜져 있으면 Qt 의 치명적 메시지를 남긴다(꺼져 있으면 아무 일도 없다). 예외를 내지 않는다."""
    log = _ACTIVE
    return False if log is None else log.record_qt(message_type, context)


__all__ = ["BACKUPS", "FILE_NAME", "FOLDER_NAME", "MAX_BYTES", "MAX_FRAMES", "RATE_COUNT", "RATE_SECONDS", "SOURCES", "ErrorLog", "active", "arm", "disarm", "record_exception", "record_qt"]
