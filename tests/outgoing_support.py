"""바깥으로 나가는 호출(하위 프로세스·소켓·HTTP·셸·브라우저)을 막고 세는 시험 도우미(시험이 아니다 — PCSEC1 H3 'Network Write 0').

`with Tripwire() as wire:` 안에서 아래 호출이 하나라도 일어나면 **막고**(예외) `wire.calls` 에 (종류, 짧은 인자) 로 적는다. 시험은 `wire.calls == []` 를 단언한다.
막는 것: `socket` 연결·이름 풀이 · `http.client` 연결 · `urllib.request.urlopen` · `subprocess.Popen`(그래서 `run`·`call`·`check_*` 도) · `os.system`·`os.popen`·`os.spawn*`·`os.exec*`·`os.startfile` ·
`webbrowser.open*`. 허용 목록(`allow`)에 종류 이름(`socket`·`http`·`subprocess`·`os`·`browser`)을 주면 그 종류는 막지도 세지도 않는다(이 빌드는 허용하는 종류가 없다 — 네이버 글쓰기 주소는 화면(Qt)의 `qt_open_url` 한 길이고 명령줄에는 없다).

`loopback_only=True`(NET 설계서 E8·6.1, D-734) — 접속 틀의 TLS 시험(루프백 서버)용 모드: `socket`·`http` 종류에서 **127.0.0.1·::1·localhost 로 가는 연결·이름 풀이만 진짜로 통과**시키고 그 밖의 주소는 막고 센다(`urlopen`·하위 프로세스·`os`·브라우저는 그대로 막는다).
판정은 글자 읽기 가드(`ocr_addon/netguard._is_loopback`)와 같은 표다(`test_net_zero` 가 두 구현이 어긋나지 않음을 견준다). 기존 모드의 동작은 한 글자도 바뀌지 않았다.
"""
import contextlib
import http.client
import ipaddress
import os
import socket
import subprocess
import urllib.request
import webbrowser
from unittest import mock


def is_loopback(host):
    """이 주소·이름이 루프백(127.0.0.0/8·::1·localhost·localhost.localdomain)인가 — 글자 읽기 가드(`ocr_addon/netguard._is_loopback`)와 같은 표. 주소가 없으면(None·빈 글) 연결이 아니라서 통과한다."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host in (None, ""):
        return True
    text = str(host).strip("[]").lower()
    if text in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(text.split("%")[0]).is_loopback
    except ValueError:
        return False


class OutgoingBlocked(Exception):
    """막힌 호출이 일으키는 예외 — 이 예외를 삼키는 코드가 있어도 `Tripwire.calls` 에는 남는다."""


class Tripwire:
    OS_NAMES = ("system", "popen", "startfile", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
                "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe", "posix_spawn", "posix_spawnp")

    def __init__(self, allow=(), loopback_only=False):
        self.allow = frozenset(allow)
        self.loopback_only = loopback_only
        self.calls = []
        self._stack = None

    def count(self, kind=None):
        return len([call for call in self.calls if kind is None or call[0] == kind])

    def kinds(self):
        return sorted({call[0] for call in self.calls})

    def _trip(self, kind):
        def trip(*args, **kwargs):
            self.calls.append((kind, repr(args[1:] if args else args)[:80]))      # 인자는 짧게(시험 입력이 비밀을 닮았을 수 있다)
            raise OutgoingBlocked(kind)
        return trip

    def _loopback(self, kind, name, real):
        """`loopback_only` — 루프백 주소면 진짜 함수를 부르고, 아니면 막고 센다."""
        def host_of(args, kwargs):
            if name in ("connect", "connect_ex"):
                address = args[1] if len(args) > 1 else kwargs.get("address")
                return address[0] if isinstance(address, tuple) and address else address
            if name == "create_connection":
                address = args[0] if args else kwargs.get("address")
                return address[0] if isinstance(address, tuple) and address else address
            if name in ("getaddrinfo", "gethostbyname"):
                return args[0] if args else kwargs.get("host")
            return getattr(args[0], "host", None)                                     # HTTPConnection.connect(self)

        def guarded(*args, **kwargs):
            try:
                host = host_of(args, kwargs)
                inside = is_loopback(host)
            except Exception:
                host, inside = "?", False
            if inside:
                return real(*args, **kwargs)
            self.calls.append((kind, repr(host)[:80]))
            raise OutgoingBlocked(kind)
        return guarded

    def __enter__(self):
        stack = contextlib.ExitStack()
        wire = self

        class TrippedPopen:
            def __init__(self, *args, **kwargs):
                wire.calls.append(("subprocess", repr(args[0] if args else "")[:80]))
                raise OutgoingBlocked("subprocess")

        targets = [(socket.socket, "connect", "socket"), (socket.socket, "connect_ex", "socket"), (socket, "create_connection", "socket"), (socket, "getaddrinfo", "socket"),
                   (socket, "gethostbyname", "socket"), (http.client.HTTPConnection, "connect", "http"), (http.client.HTTPSConnection, "connect", "http"),
                   (urllib.request, "urlopen", "http"), (webbrowser, "open", "browser"), (webbrowser, "open_new", "browser"), (webbrowser, "open_new_tab", "browser")]
        targets += [(os, name, "os") for name in self.OS_NAMES if hasattr(os, name)]
        for owner, name, kind in targets:
            if kind in self.allow:
                continue
            if self.loopback_only and kind in ("socket", "http") and name != "urlopen":
                stack.enter_context(mock.patch.object(owner, name, self._loopback(kind, name, getattr(owner, name))))
            else:
                stack.enter_context(mock.patch.object(owner, name, self._trip(kind)))
        if "subprocess" not in self.allow:
            stack.enter_context(mock.patch.object(subprocess, "Popen", TrippedPopen))
        self._stack = stack
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False
