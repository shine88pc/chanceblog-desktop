"""접속 틀(`net/`) 시험 도우미(시험이 아니다 — NET 설계서 6.1 '시험이 실제 외부에 접속하지 않는 방법').

가짜 전송기: `net.client` 안의 연결 함수(`_dial`·`_secure`·`_make_context`·`_clock`)를 `mock.patch.object` 로 바꿔 소켓이 한 번도 열리지 않게 한다. `FakeSocket` 은 보낸 바이트를 그대로 기록하고
정해 둔 응답 바이트를 돌려준다(진짜 `http.client` 가 그 바이트를 읽고 쓴다 — 그래서 '보낸 바이트가 고정 모양과 같다' 를 바이트 단위로 확인할 수 있다). `FakeClock` 은 느린 서버를 흉내 내려고 시간을 앞으로 보낸다
(진짜로 기다리지 않는다).
"""
import contextlib
import ssl
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.net import client, usage  # noqa: E402

ORIGINAL_MAKE_CONTEXT = client._make_context                   # 시험이 `_make_context` 를 바꿔도 진짜 것은 여기서 부른다
CANARY = "CANARY_" + "NET" + "_" + "KEY" + "0123456789"        # 조립한 가짜 비밀 — 저장소에는 키 모양 글이 없다
VERSION = "1.2.3"
_CONTEXT = []


def shared_context():
    """진짜 `ssl` 보안 환경 하나(만드는 데 시간이 걸려서 한 번만) — 가짜 전송기 시험이 `_make_context` 대신 돌려준다."""
    if not _CONTEXT:
        _CONTEXT.append(ORIGINAL_MAKE_CONTEXT())
    return _CONTEXT[0]


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def http_response(status=200, reason="OK", headers=(), body=b"", *, chunked=False, length=True):
    """HTTP/1.1 응답 바이트 — 기본은 `Content-Length` 가 있는 응답."""
    lines = [f"HTTP/1.1 {status} {reason}"]
    for name, value in headers:
        lines.append(f"{name}: {value}")
    if chunked:
        lines.append("Transfer-Encoding: chunked")
    elif length:
        lines.append(f"Content-Length: {len(body)}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    if chunked:
        parts = [body[i:i + 5] for i in range(0, len(body), 5)] or []
        return head + b"".join(f"{len(part):x}\r\n".encode() + part + b"\r\n" for part in parts) + b"0\r\n\r\n"
    return head + body


class FakeSocket:
    """`_dial` 이 돌려주는 가짜 소켓. `script` 는 읽을 때마다 한 조각씩 돌려줄 바이트 목록이거나 한 덩어리 바이트다."""

    def __init__(self, data=b"", *, clock=None, delay=0.0, chunk=1 << 16, read_error=None, send_error=None):
        self.sent = bytearray()
        self.send_calls = []
        self.data = bytes(data)
        self.offset = 0
        self.clock = clock
        self.delay = delay
        self.chunk = chunk
        self.read_error = read_error
        self.send_error = send_error
        self.timeout = None
        self.timeouts = []
        self.closed = False
        self.reads = 0

    def settimeout(self, value):
        self.timeout = value
        self.timeouts.append(value)

    def gettimeout(self):
        return self.timeout

    def sendall(self, data):
        if self.send_error is not None:
            raise self.send_error
        self.send_calls.append(bytes(data))
        self.sent.extend(data)

    def recv_into(self, buffer):
        self.reads += 1
        if self.read_error is not None:
            raise self.read_error
        if self.delay and self.clock is not None:
            if self.timeout is not None and self.delay > self.timeout:
                self.clock.advance(self.timeout)
                raise TimeoutError("timed out")                     # 소켓 제한 안에 오지 않았다
            self.clock.advance(self.delay)
        count = min(len(buffer), self.chunk, len(self.data) - self.offset)
        buffer[:count] = self.data[self.offset:self.offset + count]
        self.offset += count
        return count

    def close(self):
        self.closed = True


class Harness:
    """가짜 전송기를 끼운 채 요청을 돌리는 환경 — `with Harness(test, response=...) as h:` 안에서 `h.client.request(...)`."""

    def __init__(self, test, response=b"", *, clock=None, delay=0.0, chunk=1 << 16, read_error=None, send_error=None, dial_error=None, sockets=None, switches=()):
        self.test = test
        self.clock = clock or FakeClock()
        self.usage = usage.Usage(clock=self.clock, wall=lambda: 1_700_000_000.0)
        self.sockets = list(sockets) if sockets is not None else []
        self.template = dict(data=response, clock=self.clock, delay=delay, chunk=chunk, read_error=read_error, send_error=send_error)
        self.dial_error = dial_error
        self.dials = []
        self.switches = tuple(switches)
        self.client = client.NetClient(version=VERSION, usage=self.usage)

    def _dial(self, connection, address):
        self.dials.append((connection.host, address))
        if self.dial_error is not None:
            raise self.dial_error
        sock = self.sockets.pop(0) if self.sockets else FakeSocket(**self.template)
        self.last_socket = sock
        return sock

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        for name in self.switches:
            self.stack.enter_context(mock.patch.object(capabilities, name, True))
        self.stack.enter_context(mock.patch.object(client, "_dial", self._dial))
        self.stack.enter_context(mock.patch.object(client, "_secure", lambda connection, raw: raw))
        self.stack.enter_context(mock.patch.object(client, "_make_context", shared_context))
        self.stack.enter_context(mock.patch.object(client, "_clock", self.clock))
        self.stack.enter_context(mock.patch.object(client, "SESSION", self.usage))                  # 이 안에서 `usage=` 없이 만들어진 클라이언트(생산 경로)의 기록이 전역 세션에 새지 않고 이 환경의 것에 남는다
        self.stack.enter_context(mock.patch.object(usage, "SESSION", self.usage))                   # `doctor` 가 읽는 세션도 같은 것
        return self

    def __exit__(self, *exc):
        self.stack.close()
        return False


USE_SWITCHES = {
    "update_check": ("NET_UPDATE_CHECK",),
    "pages_site": ("EXTERNAL_WRITE", "NET_PAGES_SITE"),
    "blogger_oauth": ("NET_BLOGGER_OAUTH",),
    "blogger_read": ("NET_BLOGGER_OAUTH",),
    "blogger_draft": ("EXTERNAL_WRITE", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT"),
}
ALL_NET_SWITCHES = ("EXTERNAL_WRITE", "NET_UPDATE_CHECK", "NET_PAGES_SITE", "PAGES_BRANCH_PUSH", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT")


def verify_context_is_real(test):
    """가짜 전송기 시험이 쓰는 보안 환경이 진짜 `ssl` 의 것(검증 필수)인지 확인한다."""
    context = shared_context()
    test.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
    test.assertTrue(context.check_hostname)
