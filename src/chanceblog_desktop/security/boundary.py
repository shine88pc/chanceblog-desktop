"""공통 경계 — 비밀이 프로세스 밖(표준 출력·표준 오류·로그·처리하지 못한 예외·Qt 메시지)으로 나가기 전에 **한 곳에서** 거른다(PCSEC1 H1, docs/SECURITY.md §2).

가리는 규칙 자체는 `security/mask.py` 한 곳에만 있다. 이 모듈은 그 규칙(`mask`)을 **프로세스 전체의 출구**에 거는 일만 하고 정규식을 새로 만들지 않는다(각 기능이 자기 규칙으로 따로 가리면 규칙이
어긋나고 빠지는 곳이 생긴다 — 시험 `test_source_rules_output` 이 이 모듈 밖에 가리기 규칙·직접 출력이 새로 생기지 않았는지 지킨다).

이 모듈이 하는 일:
  · `RedactingStream` — `sys.stdout`·`sys.stderr` 를 감싸 **줄 단위**로 가려서 쓴다. 여러 번의 `write()` 에 쪼개진 비밀도 줄이 끝날 때 한 덩어리로 가려지고, 개인 키 블록(여러 줄)은 끝줄까지 모아 통째로
    가리며, 값이 다음 줄에 오는 모양(`password:` 줄바꿈 값)도 한 줄을 쥐고 기다렸다 같이 가린다. 줄바꿈 없는 조각은 `flush()` 때 마지막 공백(비밀에는 공백이 없다) 앞까지만 내보내고 나머지는 줄 끝·`close()`·
    프로세스 종료까지 쥔다. 어떤 속성(`encoding`·`isatty`·`reconfigure`·`buffer` …)이든 원래 스트림으로 넘기므로 기존 코드가 그대로 돈다.
  · 처리하지 못한 예외(`sys.excepthook`·`threading.excepthook`·`sys.unraisablehook`)는 추적 전체를 **가린 글**로 표준 오류에 남긴다(`--debug` 의 되던지기도 여기서 가려진다).
  · `logging` — 기록이 만들어지는 순간(`LogRecord` 공장)에 문장·인자·추적을 가린 글로 굳히고, 루트 로거와 `logging.lastResort` 에도 같은 필터를 단다(로그 파일 핸들러는 만들지 않는다 — 없는 기능이다).
  · Qt 가 C++ 쪽에서 직접 찍는 메시지는 `install_qt_message_handler` 가 가린 뒤 표준 오류로 보낸다(PySide6 는 그 함수 안에서만 불러온다 — 이 모듈을 불러온다고 Qt 가 필요하지 않다).
  · `mask_block`·`mask_deep` — 명령줄이 쓰는 여러 줄 글·JSON 값 가리기(예전에 `service/cli.py` 에 있던 것을 옮겼다 — 이름은 cli 에도 그대로 있다).

`install()` 은 **멱등**이고 `uninstall()`(또는 `with install():`)로 원래대로 돌린다(시험이 설치한 뒤 반드시 되돌린다). 설치는 진입점(`__main__`·GUI)에서 한 번만 한다 — `service/cli.main(...)` 는 시험이
넣은 스트림에 래퍼를 씌우지 않는다.

**한계**(걸러지지 않는 것): 스트림의 `.buffer` 로 바이트를 직접 쓰는 것·자식 프로세스가 표준 출력·오류 파일 번호에 직접 쓰는 것(이 앱은 자식 프로세스의 출력을 이어받지 않는다)·`faulthandler` 가 파일 번호에 직접 쓰는
추적·Qt 가 아닌 라이브러리가 C 쪽에서 찍는 글. 비밀을 애초에 출력에 넣지 않는 것(docs/SECURITY.md §1)이 먼저다.
"""
from __future__ import annotations

import atexit
import logging
import re
import sys
import threading
import traceback

from .mask import MAX_MASK_INPUT, mask

PENDING_LIMIT = 4096                   # 줄바꿈 없이 쌓아 두는 조각의 상한(글자) — 넘으면 마지막 공백 앞까지 가려 내보낸다
PENDING_HARD_LIMIT = PENDING_LIMIT * 4  # 공백이 하나도 없는 조각이 이만큼 쌓이면 통째로 가려 내보낸다(메모리 상한)
BLOCK_LIMIT = 65_536                   # 열린 개인 키 블록을 쥐고 기다리는 최대 글자 — 넘으면 끝줄이 없어도 통째로 가려 내보내고, 끝줄이 올 때까지 그 뒤 줄은 버린다
HOLD_LINE_LIMIT = 512                  # 값이 다음 줄에 올지도 몰라 쥐고 기다리는 줄의 최대 글자
_HOLD_WORDS = ("token", "secret", "passw", "key", "authorization", "cookie", "bearer", "basic", "credential", "session")
_HOLD_ENDINGS = (":", "=")
_HOLD_SCHEMES = ("bearer", "basic")
_HEADER_LINE = re.compile(r"(?i)^[\W_]{0,8}(?:proxy-authorization|authorization|set-cookie|cookies?)[ \t]*[:=]")      # 줄머리가 헤더 이름 — 값이 줄 끝까지(여러 쌍이 한 줄에 올 수 있다)
_BEGIN = "-----BEGIN"
_END = "-----END"
_PRIVATE = "PRIVATE KEY"
_LINE_ENDS = "\r\n"
_QT_FAILED = "(Qt 메시지를 가릴 수 없어 생략)"


# ---- 글 한 덩어리를 가리기 ------------------------------------------------------------------------------------------------------------------
def mask_block(text):
    """여러 줄 글을 통째로 가린 글. 줄 단위로 가리면 개인 키 블록(-----BEGIN … PRIVATE KEY----- 부터 END 까지)의 본문 줄과 '다음 줄에 이어지는 값' 이 그대로 나간다.
    글이 아주 길어 한 번에 가릴 수 없으면(`MAX_MASK_INPUT` 초과) 줄 경계에서 나눠 가리되 열린 개인 키 블록 안에서는 끊지 않는다(끝까지 가려진다)."""
    text = str(text)
    if len(text) <= MAX_MASK_INPUT:
        return mask(text)
    pieces, current, size, inside = [], [], 0, False
    for line in text.split("\n"):
        current.append(line)
        size += len(line) + 1
        if _PRIVATE in line:
            if _BEGIN in line:
                inside = True
            if _END in line:
                inside = False
        if size >= MAX_MASK_INPUT // 2 and not inside:
            pieces.append(mask("\n".join(current)))
            current, size = [], 0
    if current:
        pieces.append(mask("\n".join(current)))
    return "\n".join(pieces)


def mask_deep(value):
    """JSON 으로 내보낼 값(글·사전·목록·튜플)의 모든 글을 가린 사본. 글이 아닌 값(숫자·불리언·None)은 그대로다."""
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {key: mask_deep(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_deep(item) for item in value]
    return value


def format_exception_masked(kind, value, trace):
    """처리하지 못한 예외의 추적 전체를 가린 글로(경로·값이 든 추적이라도 비밀 모양은 가려진다). 추적을 만들 수 없으면 예외 이름만."""
    try:
        text = "".join(traceback.format_exception(kind, value, trace))
    except Exception:
        text = f"{getattr(kind, '__name__', 'Exception')}\n"
    return mask_block(text)


def _write_error(text):
    """가린 글을 표준 오류에 쓴다(표준 오류가 없는 `pythonw`·창 없는 exe 에서는 남길 곳이 없다). 오류를 처리하는 중에 불리므로 어떤 오류도 다시 내지 않는다."""
    stream = sys.stderr
    if stream is None:
        return False
    try:
        stream.write(text if text.endswith("\n") else text + "\n")
        stream.flush()
        return True
    except Exception:
        return False


def report_exception(kind, value, trace):
    """처리하지 못한 예외를 가린 추적으로 표준 오류에 남긴다 → 남겼으면 True. GUI 의 한 줄 훅이 Ctrl+C 를 넘길 때도 쓴다."""
    return _write_error(format_exception_masked(kind, value, trace))


# ---- 줄 단위로 가려서 쓰는 스트림 -----------------------------------------------------------------------------------------------------------
def _split_last_line(text):
    """줄바꿈으로 끝나는 글 → (마지막 줄 앞까지, 마지막 줄)."""
    stripped = text.rstrip(_LINE_ENDS)
    start = max(stripped.rfind("\n"), stripped.rfind("\r")) + 1
    return text[:start], text[start:]


def _holdable(line):
    """줄 끝이 이름만 있고 값이 없는 모양(`password:`·`Authorization: Bearer`)이면 값이 다음 줄에 올 수 있어 한 줄만 쥐고 기다린다."""
    text = line.rstrip()
    if not text or len(text) > HOLD_LINE_LIMIT:
        return False
    lowered = text.lower()
    return any(word in lowered for word in _HOLD_WORDS) and lowered.endswith(_HOLD_ENDINGS + _HOLD_SCHEMES)


def _last_cut(text):
    """줄바꿈 없는 조각을 나눌 자리(공백) — 마지막 공백이되, 바로 앞이 값이 올 이름(`password:`·`Authorization: Bearer`)이면 그보다 앞의 공백이다(이름과 값 사이에서 자르면 뒤 조각이 가려지지 않는다). 없으면 -1."""
    end = len(text)
    while True:
        cut = max(text.rfind(" ", 0, end), text.rfind("\t", 0, end))
        if cut < 0:
            return -1
        if not _holdable(text[max(0, cut - 80):cut + 1]):
            return cut
        end = cut


def _has_private_end(text):
    """개인 키 블록의 끝줄(`-----END … PRIVATE KEY-----`)이 있는가."""
    pos = 0
    while True:
        found = text.find(_END, pos)
        if found < 0:
            return False
        if _PRIVATE in text[found:found + 60]:
            return True
        pos = found + len(_END)


def _open_block_start(text):
    """아직 끝나지 않은 개인 키 블록이 시작하는 줄의 머리 위치(없으면 -1)."""
    pos = 0
    while True:
        begin = text.find(_BEGIN, pos)
        if begin < 0:
            return -1
        line_end = text.find("\n", begin)
        if _PRIVATE in text[begin:line_end if line_end >= 0 else len(text)] and not _has_private_end(text[begin + len(_BEGIN):]):
            return max(text.rfind("\n", 0, begin), text.rfind("\r", 0, begin)) + 1
        pos = begin + len(_BEGIN)


class RedactingStream:
    """텍스트 스트림 래퍼 — 쓰는 글을 줄 단위로 가려 원래 스트림에 쓴다(모듈 설명 참고). 나머지 속성은 원래 스트림이 그대로 답한다."""

    def __init__(self, raw, redact=None):
        self._raw = raw
        self._redact = redact or mask_block
        self._pending = ""                 # 줄바꿈이 아직 오지 않은 조각
        self._held = ""                    # 값이 다음 줄에 올지 몰라 쥔 줄(줄바꿈 포함)
        self._block = None                 # 열린 개인 키 블록을 모으는 글(없으면 None)
        self._swallow = False              # 너무 긴 블록을 통째로 내보낸 뒤 끝줄이 올 때까지 뒤 줄을 버리는 중
        self._lock = threading.RLock()

    @property
    def raw(self):
        """감싼 원래 스트림."""
        return self._raw

    def __getattr__(self, name):
        if name.startswith("__") or name in ("_raw", "_redact", "_pending", "_held", "_block", "_swallow", "_lock"):
            raise AttributeError(name)
        return getattr(self._raw, name)

    def __repr__(self):
        return f"RedactingStream({self._raw!r})"

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    def __iter__(self):
        return iter(self._raw)

    # ---- 쓰기 ----
    def write(self, text):
        if not isinstance(text, str):
            raise TypeError(f"write() argument must be str, not {type(text).__name__}")
        if not text:
            return 0
        with self._lock:
            data = self._pending + text
            cut = max(data.rfind("\n"), data.rfind("\r"))
            if cut < 0:
                self._pending = data
                self._spill()
            else:
                self._pending = data[cut + 1:]
                self._consume(data[:cut + 1])
                self._spill()
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def _emit(self, text):
        if text:
            self._raw.write(self._redact(text))

    def _consume(self, chunk, *, hold=True):
        """줄바꿈으로 끝나는 글 덩어리를 가려 내보낸다(열린 개인 키 블록·값을 기다리는 줄은 쥐어 둔다 — `hold=False` 는 명시적 `flush()` 라 값을 기다리는 줄도 내보낸다)."""
        if self._swallow:
            if _END in chunk:
                self._swallow = False
            return
        if self._block is not None:
            self._block += chunk
            if _has_private_end(self._block):
                text, self._block = self._block, None
                self._emit(text)
            elif len(self._block) > BLOCK_LIMIT:
                text, self._block, self._swallow = self._block, None, True
                self._emit(text)
            return
        text, self._held = self._held + chunk, ""
        start = _open_block_start(text)
        if start >= 0:
            self._block = text[start:]
            self._emit(text[:start])
            return
        if hold:
            body, tail = _split_last_line(text)
            if tail and _holdable(tail):
                self._emit(body)                               # 이름만 있는 마지막 줄은 값이 다음 줄에 올지 몰라 쥔다(앞 줄들은 지금 내보낸다)
                self._held = tail
                return
        self._emit(text)

    def _spill(self):
        """줄바꿈 없는 조각이 너무 쌓이면(상한) 마지막 공백 앞까지 가려 내보내고 뒤 조각만 쥔다."""
        pending = self._pending
        if len(pending) <= PENDING_LIMIT:
            return
        cut = _last_cut(pending)
        if cut < 0 or _HEADER_LINE.match(pending):                      # 헤더 줄(`Cookie: a=1; b=2 …` — 쌍이 여럿)은 공백에서 자르지 않는다: 자르면 뒤쪽 쌍이 이름표 없이 나간다(PCSEC1 D5) — 상한 안에서는 줄이 끝날 때까지 쥔다
            if len(pending) <= PENDING_HARD_LIMIT:
                return
            cut = len(pending) - 1
        self._pending = pending[cut + 1:]
        self._consume(pending[:cut + 1])

    # ---- 비우기·닫기 ----
    def flush(self):
        """명시적 `flush()` 는 '지금 보여 달라' 는 뜻이다(질문 줄·진행 표시 — 입력을 기다리는 질문이 쥐어져 안 보이면 안 된다): 쥐고 있던 줄(이름만 있던 줄)을 내보내고 줄바꿈 없는 조각은 마지막 공백 앞까지 내보낸다
        (공백 없는 뒤 조각은 줄 끝까지 쥔다). 열린 개인 키 블록은 끝줄이 와야 가릴 수 있어 쥔다. 한계: 이름과 값 사이에서 일부러 `flush()` 를 부르면 이름이 먼저 나간다."""
        with self._lock:
            if self._block is None and not self._swallow:
                pending = self._pending
                cut = max(pending.rfind(" "), pending.rfind("\t"))
                chunk = pending[:cut + 1] if cut >= 0 else ""
                if cut >= 0:
                    self._pending = pending[cut + 1:]
                if chunk or self._held:
                    self._consume(chunk, hold=False)
        flush = getattr(self._raw, "flush", None)
        if flush is not None:
            flush()

    def finish(self):
        """쥐고 있던 조각(열린 블록·값을 기다리던 줄·줄바꿈 없는 끝)을 **모두** 가려 내보낸다. 닫을 때·프로세스가 끝날 때 불린다. 오류를 내지 않는다(끝낼 때는 알릴 곳이 없다)."""
        with self._lock:
            rest, self._block, self._held, self._pending, self._swallow = (self._block or "") + self._held + self._pending, None, "", "", False
            try:
                self._emit(rest)
                flush = getattr(self._raw, "flush", None)
                if flush is not None:
                    flush()
            except (OSError, ValueError):                 # 이미 닫힌 스트림·끊어진 파이프 — 더 할 수 있는 일이 없다
                return False
        return True

    def close(self):
        self.finish()
        close = getattr(self._raw, "close", None)
        if close is not None:
            close()


# ---- 처리하지 못한 예외 ---------------------------------------------------------------------------------------------------------------------
def _excepthook(kind, value, trace):
    report_exception(kind, value, trace)


def _thread_excepthook(args):
    if args.exc_type is SystemExit:                       # 기본 훅도 스레드의 SystemExit 는 조용히 넘긴다
        return
    name = getattr(args.thread, "name", None) or "(이름 없는 스레드)"
    _write_error(f"Exception in thread {name}:\n" + format_exception_masked(args.exc_type, args.exc_value, args.exc_traceback))


def _unraisablehook(unraisable):
    try:
        head = f"{unraisable.err_msg or 'Exception ignored in'}: {mask(repr(unraisable.object))}"
    except Exception:
        head = "Exception ignored"
    _write_error(head + "\n" + format_exception_masked(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback))


# ---- logging --------------------------------------------------------------------------------------------------------------------------------
def _redact_record(record):
    """로그 기록 하나의 문장·인자·추적·호출 위치 글을 가린 글로 굳힌다(여러 번 불러도 같다)."""
    try:
        message = record.getMessage()
    except Exception:
        message = "(로그 문장을 만들 수 없음)"
    record.msg = mask(message)
    record.args = None
    try:
        if record.exc_info:
            record.exc_text = mask_block("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = mask_block(record.exc_text)
        if record.stack_info:
            record.stack_info = mask_block(record.stack_info)
    except Exception:
        record.exc_info, record.exc_text = None, "(추적을 가릴 수 없어 생략)"
    return record


class _MaskingFilter(logging.Filter):
    def filter(self, record):
        _redact_record(record)
        return True


# ---- Qt ------------------------------------------------------------------------------------------------------------------------------------
def _qt_handler(message_type, context, message):
    try:
        shown = mask_block(message)
    except Exception:
        shown = _QT_FAILED
    _write_error(shown)


class QtHandle:
    """`install_qt_message_handler` 가 돌려주는 값 — `uninstall()` 이 Qt 의 옛 메시지 핸들러를 되돌린다."""

    def __init__(self, qtcore, previous):
        self._qtcore = qtcore
        self._previous = previous
        self.active = True

    def uninstall(self):
        global _QT_ACTIVE
        if self.active:
            self._qtcore.qInstallMessageHandler(self._previous)
            self.active = False
            if _QT_ACTIVE is self:
                _QT_ACTIVE = None


def install_qt_message_handler(qtcore=None):
    """Qt 가 직접 찍는 메시지(글꼴·플랫폼·경고 …)를 가려서 표준 오류로 보내는 핸들러를 건다. `qtcore` 는 시험이 넣는 가짜(`qInstallMessageHandler` 만 있으면 된다) — 비우면 PySide6 의 QtCore.
    **멱등**: 같은 QtCore 에 이미 깔려 있으면 새로 깔지 않고 그 핸들을 돌려준다(화면 진입점이 둘 — `__main__` 과 `ui/launcher.main` — 이라 두 번 불릴 수 있다)."""
    global _QT_ACTIVE
    if qtcore is None:
        from PySide6 import QtCore as qtcore                # 늦게 불러온다 — 이 모듈은 Qt 없이도 불러올 수 있다
    with _LOCK:
        current = _QT_ACTIVE
        if current is not None and current.active and current._qtcore is qtcore:
            return current
        handle = QtHandle(qtcore, qtcore.qInstallMessageHandler(_qt_handler))
        _QT_ACTIVE = handle
        return handle


# ---- 설치 ------------------------------------------------------------------------------------------------------------------------------------
class Installed:
    """`install()` 이 돌려주는 설치 상태 — 시험이 어느 훅을 갈았는지 확인하고 `uninstall()` 이 되돌린다."""

    def __init__(self):
        self.stdout = None                 # 감싼 RedactingStream(안 감쌌으면 None)
        self.stderr = None
        self.hooks = ()                    # 갈아 낀 훅 이름
        self.logging = False
        self._undo = []                    # 되돌리는 함수들(깐 순서의 거꾸로 부른다)
        self._streams = []
        self._qt = []                      # `install_gui` 가 이 설치에 붙인 Qt 메시지 핸들(되돌릴 때 함께 되돌린다)

    def status(self):
        return {"stdout": self.stdout is not None, "stderr": self.stderr is not None, "hooks": tuple(self.hooks), "logging": self.logging}

    def _finish_streams(self):
        for stream in self._streams:
            stream.finish()

    def uninstall(self):
        """깐 것을 모두 원래대로 돌린다(쥐고 있던 글은 먼저 내보낸다). 여러 번 불러도 같다."""
        global _ACTIVE
        with _LOCK:
            if _ACTIVE is not self:
                return
            _ACTIVE = None
            atexit.unregister(self._finish_streams)
            self._finish_streams()
            for undo in reversed(self._undo):
                undo()
            self._undo = []
            self._streams = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.uninstall()
        return False


_LOCK = threading.RLock()
_ACTIVE = None
_QT_ACTIVE = None                          # 마지막으로 건 Qt 메시지 핸들(같은 QtCore 로 또 부르면 이것을 돌려준다 — 멱등)


def active():
    """지금 깔려 있는 설치 상태(없으면 None)."""
    return _ACTIVE


def _wrap_stream(installed, name):
    stream = getattr(sys, name)
    if stream is None or isinstance(stream, RedactingStream):
        return None
    wrapper = RedactingStream(stream)
    setattr(sys, name, wrapper)

    def undo():
        if getattr(sys, name) is wrapper:
            setattr(sys, name, stream)

    installed._undo.append(undo)
    installed._streams.append(wrapper)
    return wrapper


def _swap_attribute(installed, owner, name, replacement, label):
    previous = getattr(owner, name)
    setattr(owner, name, replacement)

    def undo():
        if getattr(owner, name) is replacement:
            setattr(owner, name, previous)

    installed._undo.append(undo)
    installed.hooks = (*installed.hooks, label)


def install(*, streams=True, hooks=True, logs=True):
    """프로세스 전체의 출구에 가리기를 건다 — 표준 출력·오류 래퍼(`streams`)·처리하지 못한 예외 훅 셋(`hooks`)·`logging`(`logs`). **멱등**: 이미 깔려 있으면 그 설치 상태를 그대로 돌려준다.
    되돌리려면 돌려받은 값의 `uninstall()`(또는 `with install():`)."""
    global _ACTIVE
    with _LOCK:
        if _ACTIVE is not None:
            return _ACTIVE
        installed = Installed()
        if streams:
            installed.stdout = _wrap_stream(installed, "stdout")
            installed.stderr = _wrap_stream(installed, "stderr")
            atexit.register(installed._finish_streams)             # 종료 때 쥐고 있던 조각을 가려 내보낸다
        if hooks:
            _swap_attribute(installed, sys, "excepthook", _excepthook, "sys.excepthook")
            _swap_attribute(installed, threading, "excepthook", _thread_excepthook, "threading.excepthook")
            _swap_attribute(installed, sys, "unraisablehook", _unraisablehook, "sys.unraisablehook")
        if logs:
            previous_factory = logging.getLogRecordFactory()

            def factory(*args, **kwargs):
                return _redact_record(previous_factory(*args, **kwargs))

            logging.setLogRecordFactory(factory)
            masking = _MaskingFilter()
            root = logging.getLogger()
            root.addFilter(masking)
            last_resort = logging.lastResort
            if last_resort is not None:
                last_resort.addFilter(masking)

            def undo_logging():
                if logging.getLogRecordFactory() is factory:
                    logging.setLogRecordFactory(previous_factory)
                root.removeFilter(masking)
                if last_resort is not None:
                    last_resort.removeFilter(masking)

            installed._undo.append(undo_logging)
            installed.logging = True
        _ACTIVE = installed
        return installed


def install_gui(*, qt=True):
    """화면(GUI) 진입점이 맨 앞에서 부른다 — `install()` 에 더해 Qt 가 직접 찍는 메시지도 가린다(`qt` 가 참이고 PySide6 를 불러올 수 있을 때). **멱등** — `__main__`(소스 실행)과 `ui/launcher.main`
    (묶음 실행 파일의 진입점은 `__main__` 을 거치지 않고 이 함수를 바로 부른다)이 둘 다 불러도 한 번만 깔린다. 돌려주는 `Installed` 의 `uninstall()` 이 Qt 핸들도 되돌린다(시험이 뒷정리에 쓴다)."""
    installed = install()
    if qt:
        try:
            handle = install_qt_message_handler()
        except ImportError:                                  # PySide6 를 불러올 수 없다 — 깔 Qt 핸들이 없을 뿐 경계는 그대로다
            handle = None
        if handle is not None and handle.active and handle not in installed._qt:
            installed._qt.append(handle)
            installed._undo.append(handle.uninstall)
    return installed


__all__ = ["BLOCK_LIMIT", "HOLD_LINE_LIMIT", "Installed", "PENDING_HARD_LIMIT", "PENDING_LIMIT", "QtHandle", "RedactingStream", "active", "format_exception_masked", "install", "install_gui", "install_qt_message_handler",
           "mask_block", "mask_deep", "report_exception"]
