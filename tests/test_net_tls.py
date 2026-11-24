"""보안 접속(TLS) 시험 — **진짜 `ssl`** 이 루프백(127.0.0.1) 서버와 인증서·호스트 이름·최소 버전을 확인한다(NET 설계서 NT-40–NT-48, D-731). 외부 접속 0.

이름 풀이 함수(`client._resolve`)만 가짜 표(`표의 호스트 → 127.0.0.1:서버 포트`)로 바꾼다 — 인증서 검증·호스트 이름 확인은 진짜 `ssl` 이 한다. 서버 인증서는 `net_tls_fixtures.py` 의 **버려도 되는 시험용 자체 서명** 것이다(조립 문자열).
대조 시험(NT-40)이 정상 연결을 보이므로 아래 거절들은 빈 실험이 아니다. 접속 차단 장치(`Tripwire(loopback_only=True)`)가 루프백 밖으로 나가는 연결을 모두 막는다.
"""
import ast
import contextlib
import dataclasses
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
SWITCHES = ns.USE_SWITCHES["update_check"]


class LoopbackTlsServer:
    """한 번에 연결 하나씩 받는 TLS 서버(스레드) — 핸드셰이크가 되면 HTTP 요청 머리글을 읽고 고정 응답을 보낸다. 핸드셰이크 오류는 `handshake_errors` 에 이름만 남긴다."""

    def __init__(self, cert, key, *, minimum=None, maximum=None, ciphers=None, drip=None, silent=False):
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
        self.drip, self.silent = drip, silent
        self.accepts, self.handshake_errors, self.requests, self.versions = 0, [], [], []
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
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    data += chunk
                self.requests.append(data)
                if self.drip:
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nContent-Type: application/json\r\n\r\n")
                    while not self.stop.is_set():
                        time.sleep(self.drip)
                        conn.sendall(b"x")
                else:
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(BODY)).encode() + b"\r\nConnection: close\r\n\r\n" + BODY)
        except (OSError, ssl.SSLError):
            pass
        finally:
            with contextlib.suppress(OSError):
                raw.close()

    def close(self):
        self.stop.set()
        self.listener.close()
        self.thread.join(timeout=2)
        self.dir.cleanup()


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

    def call(self, server, *, context=None, url=URL, total=None, switches=SWITCHES, **kwargs):
        """진짜 `ssl` 로 서버에 요청한다 → (응답 또는 오류, 사용량). 이름 풀이만 가짜 표다."""
        usage = net_usage.Usage()
        net = client.NetClient(version=ns.VERSION, usage=usage)
        table = endpoints.ENDPOINTS
        if total is not None:
            table = dict(table, update_check=dataclasses.replace(table["update_check"], total_timeout=total))
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
                result = net.request("update_check", "GET", url)
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
        result, usage = self.call(server)
        if isinstance(result, client.NetResponse):
            self.fail(f"TLS 1.1 서버와 연결됐다({server.versions})")
        self.assert_tls_failed(result, usage, server)
        self.assertEqual(server.versions, [], "TLS 1.1 로는 한 번도 연결되지 않았다")

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
        began = time.monotonic()
        result, usage = self.call(server, total=1.5)
        elapsed = time.monotonic() - began
        self.assertEqual((type(result).__name__, result.code, result.outcome_unknown), ("NetError", "NETWORK_TIMEOUT", True))
        self.assertLess(elapsed, 4.0, f"총 시간 1.5초를 넘겨 {elapsed:.1f}초나 걸렸다")
        self.assertGreater(elapsed, 1.0)
        print(f"[Q10 사실] 진짜 TLS 연결에서 찔끔 보내는 서버를 총 시간 1.5초로 끊는 데 {elapsed:.2f}초 걸렸다")

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
