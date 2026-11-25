"""보안 접속(TLS) 시험 — **진짜 `ssl`** 이 루프백(127.0.0.1) 서버와 인증서·호스트 이름·최소 버전을 확인한다(NET 설계서 NT-40–NT-48, D-731). 외부 접속 0.

이름 풀이 함수(`client._resolve`)만 가짜 표(`표의 호스트 → 127.0.0.1:서버 포트`)로 바꾼다 — 인증서 검증·호스트 이름 확인은 진짜 `ssl` 이 한다. 서버 인증서는 `net_tls_fixtures.py` 의 **버려도 되는 시험용 자체 서명** 것이다(조립 문자열).
대조 시험(NT-40)이 정상 연결을 보이므로 아래 거절들은 빈 실험이 아니다. 접속 차단 장치(`Tripwire(loopback_only=True)`)가 루프백 밖으로 나가는 연결을 모두 막는다.
"""
import ast
import contextlib
import dataclasses
import hashlib
import inspect
import os
import re
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import net_support as ns  # noqa: E402
import net_tls_fixtures as fx  # noqa: E402
import outgoing_support as og  # noqa: E402

from chanceblog_desktop.net import client, endpoints, errors, usage as net_usage  # noqa: E402

SRC = HERE.parent / "src" / "chanceblog_desktop"
URL = "https://github.com/own/app/releases/latest/download/update-manifest.json"
BODY = b'{"ok": true}'
WATCH_SECONDS = 5                                  # 서버가 응답을 보낸 뒤 클라이언트가 연결을 닫기를 기다리는 시간(느린 PC 에서도 정상 요청이 거짓 실패하지 않게 넉넉히 — 새는 연결만 이만큼 걸려 빨개진다)
SWITCHES = ns.USE_SWITCHES["update_check"]


class LoopbackTlsServer:
    """한 번에 연결 하나씩 받는 TLS 서버(스레드) — 핸드셰이크가 되면 HTTP 요청 머리글과 **요청 본문(`Content-Length` 만큼)을 모두 읽은 뒤** 응답을 보낸다. 핸드셰이크 오류는 `handshake_errors` 에 이름만 남긴다.

    본문을 읽지 않고 답하면 윈도에서 서버가 연결을 닫을 때 RST 가 나가 클라이언트가 응답을 못 받는 일이 가끔 있다(D-738 — 예전 서버가 POST 시험을 약 8퍼센트 빨갛게 했다).
    `handler(server, conn, head, body)` 가 있으면 응답을 그 함수가 보낸다(응답 모양 시험용). `watch_close` 가 켜져 있으면 응답을 보낸 뒤 보내기 쪽을 닫고 클라이언트가 연결을 닫는지 최대 5초 본다(`closed_by_client`)."""

    def __init__(self, cert, key, *, minimum=None, maximum=None, ciphers=None, drip=None, drip_close=False, silent=False, handler=None, watch_close=False):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cert_path, key_path = Path(self.dir.name) / "c.pem", Path(self.dir.name) / "k.pem"
        cert_path.write_text(cert, encoding="ascii")
        key_path.write_text(key, encoding="ascii")
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        if minimum is not None:
            self.context.minimum_version = minimum
        if maximum is not None:
            self.context.maximum_version = maximum
        if ciphers is not None:
            self.context.set_ciphers(ciphers)
        self.context.load_cert_chain(str(cert_path), str(key_path))
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.drip, self.drip_close, self.silent, self.handler, self.watch_close = drip, drip_close, silent, handler, watch_close
        self.accepts, self.handshake_errors, self.requests, self.versions, self.bodies = 0, [], [], [], []
        self.closed_by_client = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                raw, _ = self.listener.accept()
            except (TimeoutError, OSError):
                continue
            self.accepts += 1
            threading.Thread(target=self.serve, args=(raw,), daemon=True).start()

    def serve(self, raw):
        try:
            if self.silent:
                self.stop.wait(5)
                return
            raw.settimeout(5)
            try:
                conn = self.context.wrap_socket(raw, server_side=True)
            except (ssl.SSLError, OSError) as error:
                self.handshake_errors.append(type(error).__name__)
                return
            with conn:
                self.versions.append(conn.version())
                head, body = self.read_request(conn)
                if head is None:
                    return
                self.requests.append(head)
                self.bodies.append(body)
                try:
                    if self.drip:
                        close_line = b"Connection: close\r\n" if self.drip_close else b""
                        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nContent-Type: application/json\r\n" + close_line + b"\r\n")
                        while not self.stop.is_set():
                            time.sleep(self.drip)
                            conn.sendall(b"x")
                    elif self.handler is not None:
                        self.handler(self, conn, head, body)
                    else:
                        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(BODY)).encode() + b"\r\nConnection: close\r\n\r\n" + BODY)
                except (OSError, ssl.SSLError):
                    self.closed_by_client.set()              # 보내다가 끊겼다 — 클라이언트가 먼저 연결을 닫았다는 뜻이다
                    return
                if self.watch_close:
                    self.watch(conn)
        except (OSError, ssl.SSLError):
            pass
        finally:
            with contextlib.suppress(OSError):
                raw.close()

    @staticmethod
    def read_request(conn):
        """요청 머리글(빈 줄까지)과 본문(`Content-Length` 만큼)을 모두 읽는다 → (머리글 바이트, 본문 바이트). 연결이 먼저 끊기면 (None, b"")."""
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return None, b""
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        head += b"\r\n\r\n"
        match = re.search(rb"(?im)^content-length:\s*(\d+)\s*$", head)
        need = int(match.group(1)) if match else 0
        while len(rest) < need:
            chunk = conn.recv(4096)
            if not chunk:
                break
            rest += chunk
        return head, rest[:need]

    def watch(self, conn):
        """응답을 다 보낸 뒤 보내기 쪽을 닫고(길이 없는 응답은 이것이 '끝' 이다) 클라이언트가 연결을 닫는지 최대 5초 본다 — 닫지 않으면 연결이 새고 있는 것이다."""
        try:
            conn.shutdown(socket.SHUT_WR)
            conn.settimeout(WATCH_SECONDS)
            while conn.recv(4096):
                pass
            self.closed_by_client.set()
        except TimeoutError:
            return
        except OSError:
            self.closed_by_client.set()              # 끊김·재설정도 클라이언트가 닫았다는 뜻이다

    def close(self):
        self.stop.set()
        self.listener.close()
        self.thread.join(timeout=2)
        self.dir.cleanup()


def pattern(size):
    """크기가 `size` 인 시험용 본문 — 반복 무늬라 잘리거나 겹쳐 읽히면 같지 않다."""
    return (b"0123456789abcdef" * (size // 16 + 1))[:size]


def head_bytes(*lines):
    """응답 머리글 바이트(상태 줄과 `Content-Type` 에 고른 줄들을 더하고 빈 줄로 끝낸다)."""
    return ("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + "".join(line + "\r\n" for line in lines) + "\r\n").encode("ascii")


def shaped(body, *, framing, close, split=True, piece=4000):
    """응답 모양을 고르는 서버 동작. `framing`: `length`(Content-Length)·`chunked`·`none`(길이 없이 연결을 닫아 끝냄). `close`: 응답에 `Connection: close` 를 넣는가.
    `split`: 머리글과 본문을 **따로 보내는가**(다른 보안 레코드로 오므로 클라이언트의 읽기가 둘 이상 필요하다 — 보통의 서버 모양이다)."""
    def handler(server, conn, head, request_body):
        lines = []
        if framing == "length":
            lines.append(f"Content-Length: {len(body)}")
        elif framing == "chunked":
            lines.append("Transfer-Encoding: chunked")
        if close:
            lines.append("Connection: close")
        conn.sendall(head_bytes(*lines))
        if split:
            time.sleep(0.02)
        if framing == "chunked":
            for start in range(0, len(body), piece):
                part = body[start:start + piece]
                conn.sendall(f"{len(part):x}\r\n".encode() + part + b"\r\n")
            conn.sendall(b"0\r\n\r\n")
        else:
            conn.sendall(body)
    return handler


def trusting(*pems):
    """진짜 `_make_context`(기본 보안 환경 + 최소 TLS 1.2)에 시험용 인증서를 **믿을 곳으로 더한** 환경 — 검증 필수·호스트 이름 확인은 그대로다."""
    def make():
        context = ns.ORIGINAL_MAKE_CONTEXT()
        for pem in pems:
            context.load_verify_locations(cadata=pem)
        return context
    return make


class TlsBase(unittest.TestCase):
    def setUp(self):
        self.servers = []
        self.addCleanup(lambda: [server.close() for server in self.servers])

    def serve(self, *args, **kwargs):
        server = LoopbackTlsServer(*args, **kwargs)
        self.servers.append(server)
        return server

    def call(self, server, *, context=None, url=URL, total=None, switches=SWITCHES, use="update_check", method="GET", request=None, download=None, table_use=None, **kwargs):
        """진짜 `ssl` 로 서버에 요청한다 → (응답 또는 오류, 사용량). 이름 풀이만 가짜 표다. `request` 는 `NetClient.request` 에 더 넘길 인자(본문·읽을 상한 등),
        `download` 가 있으면 `request_to_file` 로 받는다(그 인자 모음 — `dest`·`max_bytes`·`expected_sha256`), `table_use` 는 그 용도의 표 줄을 바꿔 끼운다(내려받기 길 같은 합성 표)."""
        usage = net_usage.Usage()
        net = client.NetClient(version=ns.VERSION, usage=usage)
        table = endpoints.ENDPOINTS
        if table_use is not None:
            table = dict(table, **{use: table_use})
        if total is not None:
            table = dict(table, **{use: dataclasses.replace(table[use], total_timeout=total)})
        with contextlib.ExitStack() as stack:
            for name in switches:
                stack.enter_context(mock.patch.object(client.capabilities, name, True))
            stack.enter_context(mock.patch.object(client, "_resolve", lambda host, port: ("127.0.0.1", server.port)))
            stack.enter_context(mock.patch.object(client, "_make_context", context or trusting(fx.GOOD_CERT)))
            stack.enter_context(mock.patch.object(client, "ENDPOINTS", table))
            for key, value in kwargs.items():
                stack.enter_context(mock.patch.object(client, key, value))
            wire = stack.enter_context(og.Tripwire(loopback_only=True))
            try:
                result = net.request_to_file(use, method, url, **download) if download is not None else net.request(use, method, url, **(request or {}))
            except errors.NetError as error:
                result = error
        self.assertEqual(wire.calls, [], "루프백 밖으로 나가는 연결이 있었다")
        return result, usage


class ValidCertificateTest(TlsBase):
    def test_valid_certificate_and_matching_name_connects(self):
        """NT-40 — 대조: 인증서·이름이 맞으면 정상 연결된다(아래 거절들이 빈 실험이 아니다). TLS 1.2 이상이고 요청 바이트는 고정 모양이다."""
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
        result, usage = self.call(server)
        self.assertEqual((result.status, result.json()), (200, {"ok": True}))
        self.assertIn(server.versions[0], ("TLSv1.2", "TLSv1.3"))
        self.assertEqual(server.requests[0], (f"GET /own/app/releases/latest/download/update-manifest.json HTTP/1.1\r\nHost: github.com\r\nUser-Agent: ChanceBlogDesktop/{ns.VERSION}\r\nAccept: application/json\r\n"
                                              "Accept-Encoding: identity\r\nConnection: close\r\n\r\n").encode())
        self.assertEqual((usage.records()[0].status, usage.records()[0].error, usage.records()[0].host), (200, "", "github.com"))

    def test_the_trusted_certificate_must_match_each_table_host(self):
        for use, url, host in (("update_check", URL, "github.com"), ("blogger_oauth", "https://oauth2.googleapis.com/token", "oauth2.googleapis.com"), ("blogger_read", "https://www.googleapis.com/blogger/v3/blogs/1", "www.googleapis.com")):
            with self.subTest(host=host):
                server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
                with contextlib.ExitStack() as stack:
                    for name in ns.USE_SWITCHES[use]:
                        stack.enter_context(mock.patch.object(client.capabilities, name, True))
                    stack.enter_context(mock.patch.object(client, "_resolve", lambda h, p, port=server.port: ("127.0.0.1", port)))
                    stack.enter_context(mock.patch.object(client, "_make_context", trusting(fx.GOOD_CERT)))
                    stack.enter_context(og.Tripwire(loopback_only=True))
                    net = client.NetClient(version=ns.VERSION, usage=net_usage.Usage())
                    response = net.request(use, "POST" if use == "blogger_oauth" else "GET", url, body=b"x=1" if use == "blogger_oauth" else None)
                self.assertEqual(response.status, 200)
                self.assertIn(f"Host: {host}\r\n".encode(), server.requests[0])


class CertificateNameTest(TlsBase):
    """인증서 확인 이름은 **요청한 용도의 표의 호스트**다(고정 글자가 아니다 — D-738, 독립 검증 Q G-4). 예전 시험 인증서는 세 호스트를 모두 이름으로 가져서 확인 이름을 `github.com` 으로 못박아도 시험이 초록이었다(변이 Q28).
    이름이 하나뿐인 인증서를 내놓는 서버에는 그 이름의 용도만 연결되고 다른 호스트 용도는 `NET_TLS_FAILED` 로 거절된다."""

    USES = (("update_check", "GET", URL, "github.com", None),
            ("blogger_oauth", "POST", "https://oauth2.googleapis.com/token", "oauth2.googleapis.com", {"body": b"x=1"}),
            ("blogger_read", "GET", "https://www.googleapis.com/blogger/v3/blogs/1", "www.googleapis.com", {"bearer": "t"}))

    def test_a_certificate_for_one_table_host_is_accepted_only_for_that_host(self):
        for cert_host, cert, key in (("github.com", fx.ONLY_GITHUB_CERT, fx.ONLY_GITHUB_KEY), ("www.googleapis.com", fx.ONLY_WWW_CERT, fx.ONLY_WWW_KEY)):
            for use, method, url, host, request in self.USES:
                with self.subTest(certificate=cert_host, request=host):
                    server = self.serve(cert, key)
                    result, usage = self.call(server, context=trusting(cert), use=use, method=method, url=url, switches=ns.USE_SWITCHES[use], request=request)
                    if host == cert_host:
                        self.assertIsInstance(result, client.NetResponse, f"{getattr(result, 'code', '')} {getattr(result, 'detail', '')}")
                        self.assertEqual(result.status, 200)
                        self.assertIn(f"Host: {host}\r\n".encode(), server.requests[0])
                    else:
                        self.assertIsInstance(result, errors.NetError, "이름이 다른 인증서인데 연결됐다")
                        self.assertEqual((result.code, result.outcome_unknown), ("NET_TLS_FAILED", False))
                        self.assertEqual(server.requests, [], "핸드셰이크가 실패했으니 서버는 요청을 한 바이트도 받지 못했다")
                        self.assertEqual(usage.records()[0].error, "NET_TLS_FAILED")

    def test_a_certificate_with_all_three_names_is_accepted_for_all_three_hosts(self):
        """대조 — 세 이름을 모두 가진 인증서는 세 호스트 모두에 통과한다(위 거절이 이름이 아닌 다른 까닭이 아님을 보인다)."""
        for use, method, url, host, request in self.USES:
            with self.subTest(request=host):
                server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
                result, usage = self.call(server, use=use, method=method, url=url, switches=ns.USE_SWITCHES[use], request=request)
                self.assertIsInstance(result, client.NetResponse)
                self.assertEqual(result.status, 200)


class ResponseShapeTest(TlsBase):
    """응답의 모양이 달라도 본문을 끝까지 읽고 연결은 끝나면 닫는다(D-738 — 독립 검증 Q-R1).

    진짜 보안 연결에서 `http.client` 는 응답이 `Connection: close` 이거나 길이가 없으면 본문을 읽기 **전에** 소켓의 `close()` 를 부른다(표준 소켓은 읽개가 열려 있는 동안 진짜로는 안 닫는다).
    마감을 아는 소켓 껍데기가 그 호출로 진짜 소켓을 곧바로 닫던 때는, 머리글과 본문이 다른 레코드로 오거나 본문이 읽기 버퍼(8 KiB)보다 크면 `NETWORK_OFFLINE` 로 끝났다 —
    가짜 소켓 시험은 닫은 뒤에도 읽혀서 이것을 못 잡았다. 아래는 모두 진짜 `ssl` 의 루프백 서버다(외부 접속 0)."""

    def fetch(self, framing, close, size, *, split=True, limit=None):
        body = pattern(size)
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, handler=shaped(body, framing=framing, close=close, split=split), watch_close=True)
        result, usage = self.call(server, request=None if limit is None else {"limit": limit})
        return body, server, result, usage

    def assert_read_whole(self, body, server, result, usage, label):
        self.assertIsInstance(result, client.NetResponse, f"{label}: {getattr(result, 'code', '')} {getattr(result, 'detail', '')}")
        self.assertEqual((result.status, len(result.body)), (200, len(body)), label)
        self.assertEqual(result.body, body, f"{label}: 받은 본문이 보낸 것과 다르다")
        self.assertEqual((usage.records()[0].status, usage.records()[0].error), (200, ""), label)
        self.assertTrue(server.closed_by_client.wait(WATCH_SECONDS + 2), f"{label}: 끝난 뒤 클라이언트가 연결을 닫지 않았다(연결이 샌다)")

    def test_headers_and_body_sent_separately_are_read_whole_with_or_without_connection_close(self):
        """(a) 머리글과 본문을 따로 보내는 응답(보통의 서버 모양) — 본문이 12바이트여도 레코드가 둘이라 읽기가 둘이다."""
        for close in (True, False):
            for size in (0, 12, 5000, 8192, 20_000, 100_000):
                with self.subTest(close=close, size=size):
                    self.assert_read_whole(*self.fetch("length", close, size), f"Content-Length close={close} size={size}")

    def test_connection_close_with_a_body_bigger_than_the_read_buffer_is_read_whole(self):
        """(b) `Connection: close` 와 읽기 버퍼(8 KiB)보다 큰 본문 — 한 번에 보내든 나눠 보내든 같다."""
        for split in (True, False):
            for size in (9000, 20_000, 100_000, 300_000):
                with self.subTest(split=split, size=size):
                    self.assert_read_whole(*self.fetch("length", True, size, split=split), f"Content-Length+close split={split} size={size}")

    def test_a_response_without_any_length_is_read_until_the_server_closes(self):
        """(c) 길이가 없는 응답(서버가 연결을 닫을 때까지가 본문) — 항상 `http.client` 가 `close()` 를 먼저 부른다."""
        for close in (True, False):
            for size in (12, 9000, 100_000):
                with self.subTest(close=close, size=size):
                    self.assert_read_whole(*self.fetch("none", close, size), f"길이 없음 close={close} size={size}")

    def test_chunked_responses_are_read_whole_with_or_without_connection_close(self):
        """(d) 덩어리(chunked) 응답."""
        for close in (True, False):
            for size in (12, 9000, 100_000):
                with self.subTest(close=close, size=size):
                    self.assert_read_whole(*self.fetch("chunked", close, size), f"chunked close={close} size={size}")

    def test_a_download_is_written_whole_and_hash_checked_on_every_shape(self):
        """독립 검증 Q 제안 — `request_to_file` 도 같은 서버 모양(Connection: close·chunked·길이 없음)에서 본문을 끝까지 파일에 쓰고 해시를 맞춰 보며, 해시가 틀리면 파일을 지우고 거절하고, 끝나면 연결을 닫는다."""
        base = endpoints.ENDPOINTS["update_check"]
        table_use = dataclasses.replace(base, routes=(dataclasses.replace(base.routes[0], download=True),), download_timeout=60.0, max_download=1024 * 1024)
        for framing, close, size in (("length", True, 300_000), ("chunked", True, 120_000), ("none", False, 50_000), ("length", False, 20_000)):
            body = pattern(size)
            digest = hashlib.sha256(body).hexdigest()
            with self.subTest(framing=framing, close=close, size=size), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, handler=shaped(body, framing=framing, close=close), watch_close=True)
                dest = Path(tmp) / "part.bin"
                result, usage = self.call(server, table_use=table_use, download=dict(dest=dest, max_bytes=len(body), expected_sha256=digest))
                self.assertIsInstance(result, client.NetResponse, f"{getattr(result, 'code', '')} {getattr(result, 'detail', '')}")
                self.assertEqual((result.status, result.file_size, result.file_sha256), (200, size, digest))
                self.assertEqual(dest.read_bytes(), body)
                self.assertTrue(server.closed_by_client.wait(WATCH_SECONDS + 2))
                wrong = Path(tmp) / "wrong.bin"
                server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, handler=shaped(body, framing=framing, close=close), watch_close=True)
                result, usage = self.call(server, table_use=table_use, download=dict(dest=wrong, max_bytes=len(body), expected_sha256="0" * 64))
                self.assertEqual((type(result).__name__, result.code, wrong.exists()), ("NetError", "NET_RESPONSE_INVALID", False), "해시가 틀리면 파일을 지우고 거절한다")
                self.assertTrue(server.closed_by_client.wait(WATCH_SECONDS + 2))

    def test_the_size_limit_still_holds_on_every_shape(self):
        """기존 약속 — 읽을 상한은 어떤 모양이든 지켜진다(선언 크기·덩어리·길이 없음). 한도 안은 통과하고 한 바이트 넘으면 거절한다."""
        limit = 10_000
        for framing in ("length", "chunked", "none"):
            with self.subTest(framing=framing, size=limit):
                self.assert_read_whole(*self.fetch(framing, True, limit, limit=limit), f"{framing} 한도 정확히")
            with self.subTest(framing=framing, size=limit + 1):
                body, server, result, usage = self.fetch(framing, True, limit + 1, limit=limit)
                self.assertIsInstance(result, errors.NetError, framing)
                self.assertEqual((result.code, result.outcome_unknown), ("NET_RESPONSE_INVALID", True), framing)
                self.assertIn(errors.REASON_TOO_LARGE, result.rendered().message)
                self.assertTrue(server.closed_by_client.wait(WATCH_SECONDS + 2), f"{framing}: 거절한 뒤에도 연결을 닫는다")

    def test_an_endless_body_without_length_is_cut_at_the_limit_not_at_the_deadline(self):
        """길이 없이 끝없이 오는 본문은 읽을 상한에서 끊긴다(마감까지 기다리지 않는다)."""
        def endless(server, conn, head, request_body):
            conn.sendall(head_bytes("Connection: close"))
            block = pattern(16_384)
            while not server.stop.is_set():
                conn.sendall(block)
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, handler=endless)
        began = time.monotonic()
        result, usage = self.call(server, request={"limit": 50_000})
        elapsed = time.monotonic() - began
        self.assertIsInstance(result, errors.NetError)
        self.assertEqual((result.code, result.outcome_unknown), ("NET_RESPONSE_INVALID", True))
        self.assertLess(elapsed, 15.0, f"상한을 넘겨도 {elapsed:.1f}초나 읽었다")                    # 상한이 없으면 총 시간(30초)까지 읽는다 — 바쁜 PC 에서도 거짓으로 빨개지지 않게 넉넉히 둔다
        self.assertLess(usage.records()[0].received, 2 * 50_000 + 200_000, "상한 근처에서 끊겼다")

    def test_a_declared_size_over_the_limit_is_refused_before_the_body_is_read(self):
        """선언한 크기가 상한보다 크면 본문을 읽기 전에 거절한다(서버가 본문을 보내지 않고 기다려도 걸리지 않는다)."""
        def declare_only(server, conn, head, request_body):
            conn.sendall(head_bytes("Content-Length: 99999999", "Connection: close"))
            server.stop.wait(8)
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, handler=declare_only)
        began = time.monotonic()
        result, usage = self.call(server)
        self.assertIsInstance(result, errors.NetError)
        self.assertEqual(result.code, "NET_RESPONSE_INVALID")
        self.assertLess(time.monotonic() - began, 6.0, "본문을 기다리지 않고 거절해야 한다(서버는 8초 동안 본문을 안 보낸다)")

    def test_a_redirect_on_a_real_connection_is_refused_without_a_second_connection_and_the_first_is_closed(self):
        """이동 거절 — 응답이 `Connection: close` 와 본문을 달고 와도 둘째 연결은 없고 첫 연결은 닫힌다."""
        def redirect(server, conn, head, request_body):
            conn.sendall(b"HTTP/1.1 302 Found\r\nLocation: https://github.com/other/path\r\nContent-Length: 5000\r\nConnection: close\r\n\r\n" + pattern(5000))
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, handler=redirect, watch_close=True)
        result, usage = self.call(server)
        self.assertIsInstance(result, errors.NetError)
        self.assertEqual((result.code, server.accepts), ("NET_RESPONSE_INVALID", 1), "둘째 연결 0")
        self.assertTrue(server.closed_by_client.wait(WATCH_SECONDS + 2), "거절한 뒤에도 첫 연결을 닫는다")

    def test_an_error_status_with_connection_close_comes_back_as_a_response_and_the_connection_is_closed(self):
        """2xx 가 아닌 답(여기서는 404)도 `Connection: close` 와 본문이 있어도 상태·본문을 돌려주고 연결을 닫는다."""
        body = pattern(30_000)

        def not_found(server, conn, head, request_body):
            conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n")
            time.sleep(0.02)
            conn.sendall(body)
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, handler=not_found, watch_close=True)
        result, usage = self.call(server)
        self.assertIsInstance(result, client.NetResponse)
        self.assertEqual((result.status, result.body), (404, body))
        self.assertTrue(server.closed_by_client.wait(WATCH_SECONDS + 2))


class PostBodyTest(TlsBase):
    """시험 서버가 POST 본문을 읽고 답하는가(D-738 — 독립 검증 Q-R2). 본문을 안 읽고 답하면 윈도에서 서버가 닫을 때 RST 가 나가 응답이 사라져 시험이 가끔 빨개졌다(실측 약 8퍼센트)."""

    def post(self, server, body):
        return self.call(server, use="blogger_oauth", method="POST", url="https://oauth2.googleapis.com/token", switches=ns.USE_SWITCHES["blogger_oauth"], request={"body": body})

    def test_a_post_is_answered_only_after_its_whole_body_was_read_and_it_never_flakes(self):
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
        for index in range(40):
            body = b"x=1" if index % 2 == 0 else b"a=" + pattern(3500)
            result, usage = self.post(server, body)
            self.assertIsInstance(result, client.NetResponse, f"{index}번째: {getattr(result, 'code', '')} {getattr(result, 'detail', '')}")
            self.assertEqual((result.status, server.bodies[-1]), (200, body), f"{index}번째")


class RefusedCertificateTest(TlsBase):
    def assert_tls_failed(self, result, usage, server=None):
        self.assertIsInstance(result, errors.NetError)
        self.assertEqual((result.code, result.outcome_unknown), ("NET_TLS_FAILED", False))
        self.assertEqual(usage.records()[0].error, "NET_TLS_FAILED")
        for text in (str(result), result.detail, result.log_line(), result.rendered().message, result.rendered().action):
            self.assertNotIn("github.com", text)
            self.assertNotIn("certificate", text.lower())
        if server is not None:
            self.assertEqual(server.requests, [], "핸드셰이크가 실패했으니 서버는 요청을 한 바이트도 받지 못했다")

    def test_certificate_for_another_name_is_refused(self):
        """NT-41 — 인증서는 믿지만 이름이 다르면(호스트 이름 확인) 거절한다."""
        server = self.serve(fx.OTHER_CERT, fx.OTHER_KEY)
        result, usage = self.call(server, context=trusting(fx.OTHER_CERT))
        self.assert_tls_failed(result, usage, server)

    def test_expired_certificate_is_refused(self):
        """NT-42 — 믿는 인증서라도 만료됐으면 거절한다."""
        server = self.serve(fx.EXPIRED_CERT, fx.EXPIRED_KEY)
        result, usage = self.call(server, context=trusting(fx.EXPIRED_CERT))
        self.assert_tls_failed(result, usage, server)

    def test_untrusted_self_signed_certificate_is_refused(self):
        """NT-43 — 믿지 않는 발급자(자체 서명)는 기본 보안 환경으로는 거절한다(진짜 `_make_context`)."""
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
        result, usage = self.call(server, context=ns.ORIGINAL_MAKE_CONTEXT)
        self.assert_tls_failed(result, usage, server)
        self.assertEqual(server.handshake_errors[:1] != [] or server.accepts >= 1, True)

    def test_server_that_only_speaks_tls_1_1_is_refused(self):
        """NT-44 — TLS 1.1 만 말하는 서버는 최소 버전(1.2)에서 거절한다."""
        try:
            server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, minimum=ssl.TLSVersion.TLSv1_1, maximum=ssl.TLSVersion.TLSv1_1, ciphers="ALL:@SECLEVEL=0")
        except (ssl.SSLError, ValueError) as error:
            self.skipTest(f"이 파이썬의 OpenSSL 은 TLS 1.1 서버를 만들 수 없다({type(error).__name__}) — 변이 시험으로 대신한다")
        if not self.lenient_client_reaches(server):
            self.skipTest("이 파이썬의 OpenSSL 은 관대한 클라이언트로도 TLS 1.1 연결을 못 만든다 — '거절' 이 클라이언트의 일이라고 보일 수 없으니 변이 시험으로 대신한다")
        server.versions.clear()                                           # 양성 대조 연결의 기록을 지운다 — 아래 단언은 '접속 틀' 의 연결만 본다
        result, usage = self.call(server)
        if isinstance(result, client.NetResponse):
            self.fail(f"TLS 1.1 서버와 연결됐다({server.versions})")
        self.assert_tls_failed(result, usage, server)
        self.assertEqual(server.versions, [], "TLS 1.1 로는 한 번도 연결되지 않았다")

    @staticmethod
    def lenient_client_reaches(server):
        """양성 대조(독립 검증 G-3) — 최소 버전 1.1·보안 수준 0 인 **관대한** 클라이언트가 이 서버와 실제로 TLS 1.1 로 연결되는가. 그래야 접속 틀의 거절이 '서버가 1.1 을 못 말해서' 가 아니라 클라이언트의 일임이 보인다."""
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_1
        context.maximum_version = ssl.TLSVersion.TLSv1_1
        try:
            context.set_ciphers("ALL:@SECLEVEL=0")
            context.load_verify_locations(cadata=fx.GOOD_CERT)
            with socket.create_connection(("127.0.0.1", server.port), timeout=5) as raw, context.wrap_socket(raw, server_hostname="github.com") as secured:
                reached = secured.version() == "TLSv1.1"
        except (ssl.SSLError, OSError, ValueError):
            return False
        for _ in range(100):                                          # 서버 스레드가 이 연결을 기록할 때까지(최대 5초) — 기록이 늦게 와서 지운 뒤에 남지 않게
            if server.versions:
                break
            time.sleep(0.05)
        return reached

    def test_the_weak_context_a_test_could_swap_in_is_refused_by_the_last_guard(self):
        """생산 코드의 마지막 방어 — 검증을 낮춘 보안 환경을 바꿔 끼워도 접속하지 않는다."""
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
        for label, build in (("검증 없음", lambda: self.unverified()), ("이름 확인 없음", lambda: self.no_hostname()), ("낮은 버전", lambda: self.low_version())):
            with self.subTest(label=label):
                result, usage = self.call(server, context=build)
                self.assertEqual((type(result).__name__, result.code), ("NetError", "NET_TLS_FAILED"))
        self.assertEqual(server.accepts, 0, "방어가 막았으니 서버에는 연결도 오지 않았다")

    @staticmethod
    def unverified():
        context = ns.ORIGINAL_MAKE_CONTEXT()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    @staticmethod
    def no_hostname():
        context = ns.ORIGINAL_MAKE_CONTEXT()
        context.check_hostname = False
        return context

    @staticmethod
    def low_version():
        context = ns.ORIGINAL_MAKE_CONTEXT()
        context.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        return context


class KeyLogTest(TlsBase):
    """세션 비밀 로그 — 접속 틀은 TLS 세션 비밀(트래픽 열쇠)을 어떤 파일에도 쓰지 않는다(D-738, 독립 검증 S 필수-1 · 위협 T-09).
    파이썬 `ssl.create_default_context()` 는 환경 변수 `SSLKEYLOGFILE` 이 있으면 그 파일에 세션 비밀을 쓰는 보안 환경을 만든다(패킷 분석용 표준 동작) — 개발 PC 에 흔히 걸려 있다.
    이 틀 위에 접근 토큰이 실리면 그 트래픽을 푸는 열쇠가 파일에 남으므로 컨텍스트에서 끄고, 켜진 컨텍스트는 마지막 방어가 거절한다."""

    LABELS = (b"CLIENT_TRAFFIC_SECRET", b"SERVER_TRAFFIC_SECRET", b"CLIENT_HANDSHAKE_TRAFFIC_SECRET", b"SERVER_HANDSHAKE_TRAFFIC_SECRET", b"EXPORTER_SECRET", b"CLIENT_RANDOM")

    def secrets_in(self, path):
        """파일에 세션 비밀 이름표가 몇 가지 들어 있는가(값은 읽어도 출력하지 않는다) — 파일이 없으면 빈 목록."""
        if not path.exists():
            return []
        data = path.read_bytes()
        return [label.decode("ascii") for label in self.LABELS if label in data]

    def test_the_production_context_has_no_key_log_even_when_the_environment_asks_for_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            log = Path(tmp) / "keys.log"
            with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(log)}):
                context = ns.ORIGINAL_MAKE_CONTEXT()
            if not hasattr(context, "keylog_filename"):
                self.skipTest("이 파이썬의 OpenSSL 에는 세션 비밀 로그 기능이 없다")
            self.assertIsNone(context.keylog_filename, "환경 변수가 있어도 접속 틀의 보안 환경에는 세션 비밀 로그가 없다")

    def test_a_connection_through_the_client_never_writes_session_secrets_even_when_the_environment_asks_for_it(self):
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            log = Path(tmp) / "keys.log"
            with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(log)}):
                result, usage = self.call(server)                           # 진짜 `_make_context`(환경 변수를 읽는 `create_default_context`)가 만든 환경으로 진짜 핸드셰이크
            self.assertIsInstance(result, client.NetResponse, "환경 변수는 연결을 막지 않고 비밀 로그만 끈다")
            self.assertEqual(self.secrets_in(log), [], "세션 비밀이 파일에 쓰였다")

    def test_a_context_that_has_a_key_log_is_refused_by_the_last_guard_before_any_connection(self):
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            log = Path(tmp) / "keys.log"

            def keylogged():
                context = ns.ORIGINAL_MAKE_CONTEXT()
                context.load_verify_locations(cadata=fx.GOOD_CERT)
                context.keylog_filename = str(log)
                return context
            result, usage = self.call(server, context=keylogged)
            self.assertEqual((type(result).__name__, result.code), ("NetError", "NET_TLS_FAILED"))
            self.assertEqual(server.accepts, 0, "마지막 방어가 막았으니 서버에는 연결도 오지 않았다")
            self.assertEqual(self.secrets_in(log), [])
            self.assertEqual(usage.records(), (), "접속하지 않았으니 기록도 없다")


class TrustEnvironmentTest(TlsBase):
    def test_trust_changing_environment_variables_do_not_add_trust(self):
        """NT-45 — C5: 신뢰 저장소를 바꾸는 환경 변수가 있으면 접속하지 않는다(서버에는 연결도 오지 않는다). 그 변수가 정말 믿는 곳을 더하는지는 진짜 `ssl` 로 따로 재 본다(사실 기록)."""
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            ca = Path(tmp) / "ca.pem"
            ca.write_text(fx.GOOD_CERT, encoding="ascii")
            for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
                with self.subTest(name=name), mock.patch.dict(os.environ, {name: str(ca) if name == "SSL_CERT_FILE" else tmp}):
                    result, usage = self.call(server, context=ns.ORIGINAL_MAKE_CONTEXT)
                    self.assertEqual((type(result).__name__, result.code, result.outcome_unknown), ("NetError", "NET_TLS_FAILED", False))
                    self.assertEqual(server.accepts, 0)
                    self.assertEqual(usage.records(), (), "접속하지 않았으니 기록도 없다")
                    self.assertFalse(usage.resting("update_check"), "신뢰 설정 문제는 연속 실패에 세지 않는다")
            with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(ca)}):               # 사실 확인 — 환경 변수가 있으면 기본 보안 환경이 그 인증서를 믿는가
                context = ssl.create_default_context()
                try:
                    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as raw, context.wrap_socket(raw, server_hostname="github.com") as secured:
                        trusted_by_env = bool(secured.version())
                except (ssl.SSLError, OSError):
                    trusted_by_env = False
        self.assertIsInstance(trusted_by_env, bool)
        print(f"[NT-45 사실] SSL_CERT_FILE 이 이 PC 의 파이썬 {sys.version.split()[0]} 기본 보안 환경에 믿는 곳을 더하는가: {trusted_by_env}")
        if sys.platform == "win32":
            self.assertTrue(trusted_by_env, "윈도 빌드에서도 환경 변수가 신뢰를 바꾼다 — 그래서 C5 거절 규칙이 필요하다(먹지 않는다면 이 규칙을 문서 한 줄로 줄인다)")

    def test_plain_http_scheme_is_refused_before_connect(self):
        """NT-46 — 평문 `http` 는 연결 전에 거절한다(서버에는 아무것도 오지 않는다)."""
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY)
        result, usage = self.call(server, url=URL.replace("https://", "http://", 1))
        self.assertEqual((type(result).__name__, result.code), ("NetError", "UNEXPECTED_ERROR"))
        self.assertEqual((server.accepts, usage.records()), (0, ()))


class ProductionSurfaceTest(unittest.TestCase):
    def test_production_api_has_no_parameter_to_inject_a_context(self):
        """NT-47 — 생산 코드에는 보안 환경·전송기·소켓을 바깥에서 넣는 매개변수가 없다(시험은 모듈 함수를 `mock.patch.object` 로 바꾼다)."""
        banned = {"context", "ssl_context", "sslcontext", "transport", "sock", "socket", "opener", "verify", "cafile", "capath", "cadata", "proxy", "proxies", "tunnel", "connection", "conn", "check_hostname", "timeout", "retries", "retry"}
        functions = [client.NetClient.__init__, client.NetClient.request, client.NetClient.request_to_file, client.NetResponse.raise_for_status]
        for function in functions:
            names = set(inspect.signature(function).parameters)
            self.assertEqual(names & banned, set(), f"{function.__qualname__}: {names & banned}")
        self.assertEqual(sorted(client.__all__), ["DeadlineExceeded", "NetClient", "NetResponse"], "클라이언트 모듈이 내놓는 이름이 늘었다 — 바깥에서 부품을 넣는 길이 생기지 않았는지 보고 표를 고친다")
        hooks = sorted(name for name in vars(client) if name in ("_make_context", "_resolve", "_dial", "_secure", "_clock"))
        self.assertEqual(hooks, ["_clock", "_dial", "_make_context", "_resolve", "_secure"], "시험이 바꾸는 자리는 모듈 함수 다섯뿐이다")

    def test_no_proxy_or_tunnel_names_in_src(self):
        """NT-48 — C6: 프록시를 쓰지 않는다 — 소스에 터널·프록시 이름이 없다(`http.client` 는 시스템 프록시를 읽지 않고 우리는 `set_tunnel` 도 부르지 않는다)."""
        pattern = re.compile(r"set_tunnel|ProxyHandler|getproxies|build_opener|proxy_bypass|_tunnel|CONNECT_RESPONSE|(?i:https?_proxy)|ALL_PROXY")
        found = []
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and not line.lstrip().startswith("#"):
                    found.append((path.relative_to(SRC).as_posix(), number))
        # 글자 읽기 작업자의 환경 정리(`ui/ocr_adapter.py`)는 작업자가 프록시를 쓰지 못하게 프록시 변수를 '함정 값' 으로 덮는 줄이다 — 우리 클라이언트가 프록시를 쓴다는 뜻이 아니다(D-512)
        trap = [item for item in found if item[0] == "ui/ocr_adapter.py"]
        lines = (SRC / "ui" / "ocr_adapter.py").read_text(encoding="utf-8").splitlines()
        self.assertTrue(all("PROXY_TRAP" in lines[item[1]] for item in trap), "그 줄의 다음 줄이 함정 값을 대입한다")
        self.assertEqual([item for item in found if item[0] != "ui/ocr_adapter.py"], [], "소스에 프록시·터널 이름이 있다")
        self.assertEqual(len(trap), 1, "글자 읽기 작업자의 환경 정리 한 줄뿐이다")


class RealSocketDeadlineTest(TlsBase):
    """마감 껍데기를 **진짜 소켓·진짜 TLS** 로 확인한다(Q10 — 윈도에서 다른 스레드가 연결을 닫는 방식은 막힌 읽기를 깨우지 못해서 읽는 쪽 안에 마감을 넣었다)."""

    def test_a_server_that_drips_bytes_is_cut_at_the_total_deadline_on_a_real_connection(self):
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, drip=0.2)
        watchdog = threading.Timer(8.0, server.stop.set)             # 총 시간 감시가 없는 틀린 코드에서도 시험이 끝나게 — 8초 뒤 서버가 찔끔 보내기를 그만두고 연결을 닫는다(그러면 아래 단언이 빨개진다)
        watchdog.daemon = True
        watchdog.start()
        self.addCleanup(watchdog.cancel)
        began = time.monotonic()
        result, usage = self.call(server, total=1.5)
        elapsed = time.monotonic() - began
        self.assertEqual((type(result).__name__, result.code, result.outcome_unknown), ("NetError", "NETWORK_TIMEOUT", True))
        self.assertLess(elapsed, 4.0, f"총 시간 1.5초를 넘겨 {elapsed:.1f}초나 걸렸다")
        self.assertGreater(elapsed, 1.0)
        print(f"[Q10 사실] 진짜 TLS 연결에서 찔끔 보내는 서버를 총 시간 1.5초로 끊는 데 {elapsed:.2f}초 걸렸다")

    def test_a_dripping_body_is_cut_at_the_total_deadline_even_when_the_response_says_connection_close(self):
        """같은 찔끔 서버인데 응답에 `Connection: close` 가 있다 — 이때 `http.client` 는 본문을 읽기 전에 `close()` 를 부른다. 마감 초과(`NETWORK_TIMEOUT`)가 아니라 닫힌 소켓 오류가 되면 안 된다."""
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, drip=0.2, drip_close=True, watch_close=True)
        watchdog = threading.Timer(8.0, server.stop.set)
        watchdog.daemon = True
        watchdog.start()
        self.addCleanup(watchdog.cancel)
        began = time.monotonic()
        result, usage = self.call(server, total=1.5)
        elapsed = time.monotonic() - began
        self.assertEqual((type(result).__name__, result.code, result.outcome_unknown), ("NetError", "NETWORK_TIMEOUT", True), getattr(result, "detail", ""))
        self.assertLess(elapsed, 6.0, f"총 시간 1.5초를 넘겨 {elapsed:.1f}초나 걸렸다")                # 감시가 없으면 서버가 그만 보내는 8초 뒤에야 끝난다
        self.assertGreater(elapsed, 1.0)
        self.assertTrue(server.closed_by_client.wait(WATCH_SECONDS + 2), "마감으로 끝난 뒤에도 연결을 닫는다")

    def test_a_server_that_accepts_but_never_speaks_tls_times_out_in_the_connect_limit(self):
        server = self.serve(fx.GOOD_CERT, fx.GOOD_KEY, silent=True)
        began = time.monotonic()
        result, usage = self.call(server, CONNECT_TIMEOUT=0.6)
        elapsed = time.monotonic() - began
        self.assertEqual((type(result).__name__, result.code, result.outcome_unknown), ("NetError", "NETWORK_TIMEOUT", False))
        self.assertLess(elapsed, 3.0)

    def test_a_refused_connection_is_offline_and_not_sent(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()                                               # 아무도 듣지 않는 포트
        dead = mock.Mock(port=port)
        result, usage = self.call(dead)
        self.assertEqual((type(result).__name__, result.code, result.outcome_unknown), ("NetError", "NETWORK_OFFLINE", False))


if __name__ == "__main__":
    unittest.main()
