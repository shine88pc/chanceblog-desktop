"""로그인 코드를 받는 **이 PC 안의 한 번짜리 창구** — 앱에서 `socket` 을 가져오는 **유일한 파일**이다(BLOGGER 설계서 3.6 L1–L13, 결정 D-771, 운영자 확인 038 ③).

Blogger 로그인은 시스템 기본 브라우저가 구글 화면을 열고, 사용자가 허용하면 브라우저가 이 PC 의 임시 포트로 돌아온다(RFC 8252 루프백 방식). 이 파일은 그 돌아오는 요청 **한 번**을 받으려고
`127.0.0.1` 에서만 듣는다. 지키는 것:
  · **주소는 문자열 `127.0.0.1` 하나뿐**이다(포트는 운영체제가 고르게 0 으로 바인딩한 뒤 `getsockname()` 으로 안다). 모든 주소를 듣는 모양·이름으로 듣는 모양·IPv6 는 쓰지 않는다. 바깥으로 나가는 연결(`connect`)은 만들지 않는다.
  · 윈도에서는 `SO_EXCLUSIVEADDRUSE` 로 다른 프로세스가 같은 포트에 겹쳐 바인딩하지 못하게 한다. 그 밖의 곳에서는 주소·포트 재사용 옵션을 **설정하지 않는다**.
  · `listen(1)` — 한 번에 연결 하나, 연결은 **모두 8번까지만** 받는다(브라우저가 아이콘 같은 것을 더 요청할 수 있다). 전체 180초 안에 끝나지 않으면 닫는다. 기다리는 동안 `accept` 는 0.5초 제한으로 돌며 취소·시간을 본다(스레드를 죽이지 않는다).
    연결 하나의 읽기는 5초 · 요청 줄 4,096바이트 · 머리글 8 KiB 이하 · 본문은 읽지 않는다.
  · `GET /callback` 만 받는다. 그 밖의 방법·길은 짧은 고정 글(404)로 답하고 **연결 횟수에는 센다**. `Host` 머리글이 `127.0.0.1:<포트>` 가 아니면 400(다른 사이트가 이름 풀이를 바꿔 이 창구를 두드리는 것을 막는다).
    `state` 는 `hmac.compare_digest` 로 견주고 **틀리면 그 연결에 400 만 보내고 계속 듣는다**(남이 로그인을 끝내 버리지 못하게).
  · 올바른 `code` 가 `state` 와 함께 오거나, `state` 가 맞는 `error` 가 오면 **응답 페이지를 보내고 곧바로 소켓을 닫는다**(응답이 오면 포트를 닫는다 — RFC 8252). 응답 페이지는 고정된 글이고 질의 값을 되풀이하지 않는다.
  · `code`·`state`·콜백 주소는 로그·오류·기록·예외에 쓰지 않는다 — 읽은 직후 필요한 두 값만 남기고 나머지는 버린다.
  · `http.server`·`socketserver` 를 쓰지 않고 `socket` 만 쓴다(표면이 작고 허용 표에 한 줄이면 된다). 공개 함수 `open_listener`·`LoopbackListener.wait` 의 첫 문장이 관문(`capabilities.require_net`)이라 스위치가 꺼져 있으면 소켓을 만들지도 않는다.

시험 훅: 생산 코드에 시계·제한을 바깥에서 넣는 매개변수는 없다 — 시험은 모듈 값 `_clock`·`ACCEPT_TICK` 을 `mock.patch.object` 로 바꾼다(`net/client.py` 와 같은 원칙).
"""
from __future__ import annotations

import hmac
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .. import capabilities

CALLBACK_PATH = "/callback"                 # 구글이 경로를 받지 않는 것으로 실기에서 드러나면 이 한 줄만 `/` 로 바꾼다(설계 Q6)
TOTAL_SECONDS = 180.0                       # 창구가 열려 있는 전체 시간
ACCEPT_TICK = 0.5                           # `accept` 한 번의 제한 — 이 간격으로 취소·시간을 본다
READ_SECONDS = 5.0                          # 연결 하나를 읽는 시간
MAX_CONNECTIONS = 8                         # 받는 연결의 총수(길이 틀린 요청도 센다)
MAX_REQUEST_LINE = 4096
MAX_HEAD = 8192
MAX_HEADER_LINES = 100
MAX_FIELDS = 10
MAX_VALUE = 2048
BACKLOG = 1
LINGER_SECONDS = 0.2                         # 답을 보낸 뒤 남은 요청을 읽어 버리는 시간(아래 `_send`)
LINGER_BYTES = 64 * 1024
REASON_BIND, REASON_TIMEOUT, REASON_CANCELLED, REASON_TOO_MANY = "bind", "timeout", "cancelled", "too_many"
REASONS = (REASON_BIND, REASON_TIMEOUT, REASON_CANCELLED, REASON_TOO_MANY)
_CODE = re.compile(r"[A-Za-z0-9._~/+=-]{1,2048}")
_ERROR = re.compile(r"[a-z][a-z_]{0,39}")
_TARGET = re.compile(r"/[\x21-\x7e]{0,4000}")
_STATE_SAFE = re.compile(r"[A-Za-z0-9_-]{16,128}")
_clock = time.monotonic

PAGE = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>ChanceBlog Desktop</title></head>"
        "<body><p>로그인이 끝났어요. 이 창을 닫고 앱으로 돌아가세요.</p></body></html>").encode("utf-8")
NOT_FOUND = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>ChanceBlog Desktop</title></head>"
             "<body><p>찾을 수 없어요.</p></body></html>").encode("utf-8")
BAD_REQUEST = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>ChanceBlog Desktop</title></head>"
               "<body><p>요청이 맞지 않아요.</p></body></html>").encode("utf-8")
HEADERS = (("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer"),
           ("Content-Security-Policy", "default-src 'none'"), ("X-Content-Type-Options", "nosniff"), ("Connection", "close"))


class LoginWindowError(Exception):
    """창구가 코드를 받지 못하고 끝났다 — `reason` 은 고정 이름표(`REASONS`)이고 요청의 글은 담지 않는다."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Callback:
    """돌아온 요청에서 남긴 것 — `code`(빈 글이면 오류 응답) · `error`(구글이 알린 짧은 이름, 모양이 맞지 않으면 `error`) · 받은 연결 수."""
    code: str
    error: str
    served: int

    def __repr__(self):
        return f"<Callback code={'있음' if self.code else '없음'} error={self.error or '없음'} served={self.served}>"        # 코드 값은 출력에 나오지 않는다


def _response(status, reason, body):
    lines = [f"HTTP/1.1 {status} {reason}"] + [f"{name}: {value}" for name, value in HEADERS] + [f"Content-Length: {len(body)}"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


OK_RESPONSE = _response(200, "OK", PAGE)
NOT_FOUND_RESPONSE = _response(404, "Not Found", NOT_FOUND)
BAD_RESPONSE = _response(400, "Bad Request", BAD_REQUEST)


class _Rejected(Exception):
    """요청이 약속과 다르다 — 400 으로 답하고 계속 듣는다(`status` 는 404 일 수 있다)."""

    def __init__(self, status=400):
        super().__init__(status)
        self.status = status


def _read_head(conn, deadline):
    """요청 줄과 머리글까지만 읽는다(본문은 읽지 않는다) → 줄들. 너무 길거나 느리면 `_Rejected`."""
    buffer = bytearray()
    while b"\r\n\r\n" not in buffer:
        first = buffer.find(b"\r\n")
        if (first == -1 and len(buffer) > MAX_REQUEST_LINE) or first > MAX_REQUEST_LINE or len(buffer) > MAX_HEAD:
            raise _Rejected()
        left = deadline - _clock()
        if left <= 0:
            raise _Rejected()
        conn.settimeout(min(READ_SECONDS, left))
        try:
            chunk = conn.recv(2048)
        except OSError:
            raise _Rejected() from None                     # 시간 초과·끊김 모두 — 이 연결은 버린다
        if not chunk:
            raise _Rejected()
        buffer.extend(chunk)
    head = bytes(buffer.split(b"\r\n\r\n", 1)[0])
    if len(head) > MAX_HEAD:
        raise _Rejected()
    try:
        lines = head.decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        raise _Rejected() from None
    if len(lines[0]) > MAX_REQUEST_LINE or len(lines) > MAX_HEADER_LINES:
        raise _Rejected()
    return lines


def _parse(lines, port):
    """요청 줄·머리글 → 질의 글(`code`·`state`·`error` 가 든). 약속과 다르면 `_Rejected`."""
    pieces = lines[0].split(" ")
    if len(pieces) != 3 or not pieces[2].startswith("HTTP/1."):
        raise _Rejected()
    method, target, _version = pieces
    if method != "GET":
        raise _Rejected(404)
    if _TARGET.fullmatch(target) is None:
        raise _Rejected()
    parts = urlsplit(target)
    if parts.path != CALLBACK_PATH:
        raise _Rejected(404)
    hosts = [line.split(":", 1)[1].strip() for line in lines[1:] if line.lower().startswith("host:")]
    if hosts != [f"127.0.0.1:{port}"]:                                # 머리글이 없거나 둘이거나 이 창구의 이름이 아니다
        raise _Rejected()
    try:
        fields = parse_qs(parts.query, keep_blank_values=True, max_num_fields=MAX_FIELDS)
    except ValueError:
        raise _Rejected() from None
    if any(len(value) > MAX_VALUE for values in fields.values() for value in values):
        raise _Rejected()
    return fields


def _single(fields, name):
    values = fields.get(name)
    if values is None:
        return None
    if len(values) != 1:
        raise _Rejected()
    return values[0]


def _judge(fields, expected_state):
    """질의 → ('code', 값) · ('error', 이름) 또는 `_Rejected`(state 가 맞지 않음 포함)."""
    state, code, error = _single(fields, "state"), _single(fields, "code"), _single(fields, "error")
    if state is None or not hmac.compare_digest(state.encode("utf-8"), expected_state.encode("utf-8")):
        raise _Rejected()
    if error is not None:
        return "error", error if _ERROR.fullmatch(error) else "error"
    if code is None or _CODE.fullmatch(code) is None:
        raise _Rejected()
    return "code", code


def _send(conn, data):
    """답을 보내고 **천천히 닫는다** — 쓰기를 닫고 남은 요청을 조금만 읽어 버린 뒤 닫는다(읽지 않은 데이터를 안은 채 닫으면 윈도가 연결을 끊어 버려 방금 보낸 답이 사라질 수 있다)."""
    try:
        conn.settimeout(READ_SECONDS)
        conn.sendall(data)
        conn.shutdown(socket.SHUT_WR)
        conn.settimeout(LINGER_SECONDS)
        total = 0
        while total < LINGER_BYTES:
            chunk = conn.recv(4096)
            if not chunk:
                break
            total += len(chunk)
    except OSError:
        pass                                                   # 브라우저가 이미 닫았다 — 답이 안 가도 창구의 일은 끝났다


class LoopbackListener:
    """`open_listener()` 가 돌려주는 창구 — `port` 를 알려 주고, `wait()` 로 돌아온 요청 한 번을 받고 닫는다."""

    def __init__(self, sock, port):
        self._sock = sock
        self.port = port

    def __repr__(self):
        return f"<LoopbackListener 127.0.0.1:{self.port} {'닫힘' if self._sock is None else '듣는 중'}>"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        """창구를 닫는다(여러 번 불러도 된다). 닫는 일은 스위치와 상관없이 늘 된다."""
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def wait(self, expected_state, *, cancelled=None, seconds=TOTAL_SECONDS):
        """돌아온 요청 한 번을 기다린다 → `Callback`. 못 받으면 `LoginWindowError`(이유 이름표만). **어떻게 끝나도 창구는 닫혀 있다.**"""
        capabilities.require_net("blogger_oauth", "Blogger 로그인 받기")
        if self._sock is None:
            raise LoginWindowError(REASON_CANCELLED)
        if not isinstance(expected_state, str) or _STATE_SAFE.fullmatch(expected_state) is None:
            self.close()
            raise LoginWindowError(REASON_BIND)
        deadline = _clock() + seconds
        served = 0
        try:
            while True:
                if cancelled is not None and cancelled():
                    raise LoginWindowError(REASON_CANCELLED)
                if _clock() >= deadline:
                    raise LoginWindowError(REASON_TIMEOUT)
                if served >= MAX_CONNECTIONS:
                    raise LoginWindowError(REASON_TOO_MANY)
                self._sock.settimeout(ACCEPT_TICK)
                try:
                    conn, _peer = self._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    served += 1                                # 받는 쪽이 계속 오류를 내도 끝이 있게 센다
                    continue
                served += 1
                with conn:
                    outcome = self._handle(conn, expected_state, deadline)
                if outcome is not None:
                    kind, value = outcome
                    return Callback(value if kind == "code" else str(), value if kind == "error" else str(), served)
        finally:
            self.close()                                       # 응답이 왔든 못 받았든 포트는 닫는다

    def _handle(self, conn, expected_state, deadline):
        """연결 하나 → ('code'|'error', 값) 또는 None(계속 듣는다). 올바른 요청이면 응답 페이지를 보낸다."""
        try:
            lines = _read_head(conn, min(deadline, _clock() + READ_SECONDS))
            outcome = _judge(_parse(lines, self.port), expected_state)
        except _Rejected as rejected:
            _send(conn, NOT_FOUND_RESPONSE if rejected.status == 404 else BAD_RESPONSE)
            return None
        _send(conn, OK_RESPONSE)
        return outcome


def open_listener():
    """창구를 연다 → `LoopbackListener`(이미 듣는 중이고 `port` 를 안다). 못 열면 `LoginWindowError('bind')`."""
    capabilities.require_net("blogger_oauth", "Blogger 로그인 받기")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):             # 윈도 — 다른 프로세스가 같은 포트에 겹쳐 바인딩하지 못한다(그 밖의 곳에는 이 이름이 없다)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(BACKLOG)
        port = sock.getsockname()[1]
    except OSError:
        sock.close()
        raise LoginWindowError(REASON_BIND) from None
    return LoopbackListener(sock, port)


__all__ = ["ACCEPT_TICK", "BACKLOG", "CALLBACK_PATH", "Callback", "LoginWindowError", "LoopbackListener", "MAX_CONNECTIONS", "READ_SECONDS", "REASONS", "TOTAL_SECONDS", "open_listener"]
