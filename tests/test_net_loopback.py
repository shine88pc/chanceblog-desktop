"""로그인 코드를 받는 창구(`net/loopback.py`) 시험 — BLOGGER 설계서 BT-23–29·BT-80·81 의 창구 쪽(결정 D-771).

지키는 것(진짜 소켓 — `Tripwire(loopback_only=True)` 아래에서 `127.0.0.1` 만 쓴다. 바깥 주소로의 연결·이름 풀이는 막고 센다 — 0 이어야 한다):
  1) 소스 훑기(BT-23): `socket` 은 이 파일 하나 · 바인딩 주소는 글자 `127.0.0.1` · `0.0.0.0`·빈 글·`localhost`·`::` 이 없다 · `listen` 인자 1 이하 · `accept` 는 `settimeout` 과 함께 · `http.server`·`socketserver` 없음 · 첫 문장이 관문.
  2) 진짜 창구의 행동(BT-24·26–29): 다른 호스트 머리글·길·방법·너무 큰 요청·느린 요청은 거절하고 계속 듣는다 · 올바른 첫 콜백 뒤에는 연결이 안 된다 · 180초·취소 · 응답 페이지는 질의 값을 되풀이하지 않는다 · 연결은 8번까지.
  3) 윈도 독점 바인딩과 그 밖의 곳의 '재사용 옵션 없음'(BT-25).
  4) 적대적 요청 한 번이 창구를 죽이지 못한다(재작업 1 필수-1, 안전 검증 S 의 탐침 A1 — 길이 `//` 로 시작하는 요청·잘못된 퍼센트 부호·제어 문자·빈 요청 줄·GET 이 아닌 방법·예상 밖의 예외 모두 400 또는 404 로 거절하고 계속 듣고
     이어서 오는 올바른 콜백을 받는다)와, 답을 보낸 뒤 읽어 버리기가 **전체 시간**으로 묶여 있다(필수-2, 탐침 A7 — 1바이트씩 천천히 보내는 연결 하나가 마감·취소·정상 콜백을 막지 못한다).
스위치가 꺼져 있으면 소켓을 만들지도 않는다(BT-80·81).
"""
import ast
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import outgoing_support as og  # noqa: E402
import service_support as ss  # noqa: E402,F401

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net import loopback as lb  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"
STATE = "S" * 20 + "tateValue_-" + "0123456789"        # 31자 — 모양만 맞는 가짜 state
CODE_TEXT = "4/0" + "CANARY_" + "CODE_" + "abcdefghij"
SOURCE = (SRC / "net" / "loopback.py").read_text(encoding="utf-8")


def valid(port, state=STATE, code=CODE_TEXT, extra="", host=None):
    host = f"127.0.0.1:{port}" if host is None else host
    return f"GET /callback?code={code}&state={state}{extra} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode("ascii")


def talk(port, data, *, wait_reply=True, timeout=6.0, close_write=False):
    """브라우저 역할 — 요청을 보내고 답 바이트를 읽는다(연결이 안 되면 `ConnectionError`)."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
        try:
            if data:
                conn.sendall(data)
            if close_write:
                conn.shutdown(socket.SHUT_WR)
        except ConnectionError:
            pass                                                   # 서버가 먼저 끊었다 — 그래도 답이 있으면 읽는다
        chunks = []
        if wait_reply:
            while True:
                try:
                    piece = conn.recv(65536)
                except (socket.timeout, ConnectionError):
                    break
                if not piece:
                    break
                chunks.append(piece)
        return b"".join(chunks)


class Run:
    """창구의 `wait` 를 다른 스레드에서 돌린다."""

    def __init__(self, listener, state=STATE, **kwargs):
        self.result, self.error = None, None
        self.thread = threading.Thread(target=self._go, args=(listener, state), kwargs=kwargs, daemon=True)
        self.thread.start()

    def _go(self, listener, state, **kwargs):
        try:
            self.result = listener.wait(state, **kwargs)
        except BaseException as error:                                   # noqa: BLE001
            self.error = error

    def finish(self, seconds=12.0):
        self.thread.join(seconds)
        assert not self.thread.is_alive(), "창구가 끝나지 않았다"
        return self


class Base(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(capabilities, "NET_BLOGGER_OAUTH", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.wire = og.Tripwire(loopback_only=True)
        self.wire.__enter__()
        self.addCleanup(self.wire.__exit__, None, None, None)
        self.listeners = []
        self.addCleanup(self.close_all)

    def close_all(self):
        for listener in self.listeners:
            listener.close()

    def open(self):
        listener = lb.open_listener()
        self.listeners.append(listener)
        return listener

    def assertNoOutside(self):
        self.assertEqual(self.wire.calls, [], "바깥 주소로 나가는 연결·이름 풀이가 있었다")


# ---- 1) 소스 훑기 ------------------------------------------------------------------------------------------------------------------------------
def string_constants(tree):
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def calls_named(tree, name):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name]


class SourceRulesTest(unittest.TestCase):
    tree = ast.parse(SOURCE)

    def test_socket_is_imported_by_this_file_only(self):
        owners = set()
        for path in sorted(SRC.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
                if any(name.split(".")[0] in ("socket", "_socket") for name in names):
                    owners.add(path.relative_to(SRC).as_posix())
        self.assertEqual(owners, {"net/loopback.py"})

    def test_bind_takes_only_the_literal_loopback_address_and_port_zero(self):
        binds = calls_named(self.tree, "bind")
        self.assertEqual(len(binds), 1)
        argument = binds[0].args[0]
        self.assertIsInstance(argument, ast.Tuple)
        self.assertEqual([ast.unparse(item) for item in argument.elts], ["'127.0.0.1'", "0"])
        self.assertIsInstance(argument.elts[0], ast.Constant, "주소는 글자 상수여야 한다(조립한 글이 아니다)")

    def test_no_wildcard_name_or_ipv6_literal_exists_anywhere_even_in_comments_of_strings(self):
        for text in string_constants(self.tree):
            self.assertNotEqual(text, str(), "빈 글 상수가 있다")
            for banned in ("0.0.0.0", "localhost", "::", "INADDR_ANY"):
                self.assertNotIn(banned, text, f"문자열 상수에 {banned} 가 들어 있다")
        names = {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)} | {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)}
        for banned in ("AF_INET6", "INADDR_ANY", "gethostname", "gethostbyname", "getaddrinfo", "create_connection", "connect", "connect_ex", "sendto", "SO_REUSEADDR", "SO_REUSEPORT", "create_server"):
            self.assertNotIn(banned, names, banned)

    def test_listen_takes_one_or_less_and_every_accept_sits_with_a_timeout(self):
        listens = calls_named(self.tree, "listen")
        self.assertEqual(len(listens), 1)
        self.assertEqual(ast.unparse(listens[0].args[0]), "BACKLOG")
        self.assertLessEqual(lb.BACKLOG, 1)
        functions = [node for node in ast.walk(self.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        accepting = [function for function in functions if calls_named(function, "accept")]
        self.assertTrue(accepting)
        for function in accepting:
            self.assertTrue(calls_named(function, "settimeout"), f"{function.name}: accept 가 제한 없이 불린다")

    def test_the_only_socket_option_is_the_exclusive_bind_one(self):
        options = calls_named(self.tree, "setsockopt")
        self.assertEqual([ast.unparse(call.args[1]) for call in options], ["socket.SO_EXCLUSIVEADDRUSE"])

    def test_no_http_server_or_socketserver_is_imported(self):
        imported = {alias.name for node in ast.walk(self.tree) if isinstance(node, ast.Import) for alias in node.names} | {node.module for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom) and node.module}
        for name in imported:
            self.assertNotIn(name.split(".")[0], ("socketserver", "http", "ssl", "urllib3", "requests", "asyncio", "threading", "subprocess"), name)

    def test_the_public_entry_points_pass_the_gate_as_their_first_statement(self):
        functions = {node.name: node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef)}
        for name in ("open_listener", "wait"):
            body = [node for node in functions[name].body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
            self.assertEqual(ast.unparse(body[0]), "capabilities.require_net('blogger_oauth', 'Blogger 로그인 받기')", name)
        self.assertIn("close", functions, "닫기는 스위치와 상관없이 늘 된다(관문 없음)")
        close_body = ast.unparse(functions["close"])
        self.assertNotIn("require_net", close_body)

    def test_the_state_is_compared_with_compare_digest_and_never_with_equality(self):
        judge = next(node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef) and node.name == "_judge")
        self.assertIn("hmac.compare_digest", ast.unparse(judge))
        for node in ast.walk(judge):
            if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                self.assertNotIn("state", ast.unparse(node), f"state 를 == 로 견준다: {ast.unparse(node)}")

    def test_one_request_cannot_kill_the_window_the_parser_and_the_handler_are_walled_three_ways(self):
        """재작업 1 필수-1·필수-2 의 구조 못박기 — 행동 시험이 각각 따로 보지만 줄이 지워지면 소스에서도 바로 보이게 한다."""
        parse = next(node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef) and node.name == "_parse")
        parents = {child: parent for parent in ast.walk(parse) for child in ast.iter_child_nodes(parent)}
        splits = [node for node in ast.walk(parse) if isinstance(node, ast.Call) and ast.unparse(node.func) == "urlsplit"]
        self.assertEqual(len(splits), 1)
        cursor, guarded = splits[0], False
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, ast.Try) and any(handler.type is not None and ast.unparse(handler.type) == "ValueError" for handler in cursor.handlers):
                guarded = True
        self.assertTrue(guarded, "주소 쪼개기는 ValueError 를 잡는 try 안에 있어야 한다")
        self.assertIn("target.startswith('//')", ast.unparse(parse), "길이 // 로 시작하는 요청은 쪼개기 전에 거절한다")
        handle = next(node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef) and node.name == "_handle")
        caught = [ast.unparse(handler.type) for node in ast.walk(handle) if isinstance(node, ast.Try) for handler in node.handlers if handler.type is not None]
        self.assertEqual(caught, ["_Rejected", "Exception"], "연결 하나를 처리하다 나는 예외는 모두 400 으로 닫는다")
        send = next(node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef) and node.name == "_send")
        loops = [node for node in ast.walk(send) if isinstance(node, ast.While)]
        self.assertEqual(len(loops), 1)
        loop_text = ast.unparse(loops[0])
        self.assertIn("_clock()", loop_text, "읽어 버리기 반복은 전체 시간(남은 시간)을 매번 본다")
        self.assertIn("conn.settimeout(left)", loop_text, "한 번의 recv 제한은 남은 시간을 넘지 않는다")

    def test_the_scan_is_not_blind(self):
        probe = ast.parse("import socket\ns = socket.socket()\ns.bind(('0.0.0.0', 0))\ns.bind(('', 80))\nx = 'localhost'\n")
        self.assertEqual(len(calls_named(probe, "bind")), 2)
        self.assertIn("0.0.0.0", string_constants(probe))
        self.assertIn(str(), string_constants(probe))


# ---- 2) 진짜 창구 -----------------------------------------------------------------------------------------------------------------------------
class ListenerTest(Base):
    def test_it_binds_to_the_loopback_address_only_with_an_os_chosen_port(self):
        binds = []
        real = socket.socket.bind

        def spy(sock, address):
            binds.append(address)
            return real(sock, address)

        with mock.patch.object(socket.socket, "bind", spy):
            listener = self.open()
        self.assertEqual(binds, [("127.0.0.1", 0)])
        self.assertGreater(listener.port, 0)
        self.assertEqual(listener._sock.getsockname()[0], "127.0.0.1")
        self.assertNoOutside()

    def test_a_valid_callback_returns_code_and_closes_the_port_at_once(self):
        """BT-26 — 응답을 보낸 뒤 포트는 닫힌다. 두 번째 연결은 되지 않는다."""
        listener = self.open()
        port = listener.port
        run = Run(listener)
        answer = talk(port, valid(port))
        run.finish()
        self.assertIsNone(run.error)
        self.assertEqual((run.result.code, run.result.error, run.result.served), (CODE_TEXT, str(), 1))
        self.assertTrue(answer.startswith(b"HTTP/1.1 200 OK\r\n"))
        with self.assertRaises(OSError):
            talk(port, valid(port), timeout=2.0)
        self.assertIsNone(listener._sock)
        self.assertNoOutside()

    def test_the_response_page_is_static_and_never_echoes_the_query(self):
        """BT-28 — 질의 값이 응답 바이트에 없고 머리글은 여섯(+ 길이)이다."""
        listener = self.open()
        port = listener.port
        run = Run(listener)
        canary = "CANARY_ECHO_" + "ZZZ"
        answer = talk(port, valid(port, code=CODE_TEXT, extra=f"&scope={canary}&authuser=0&prompt={canary}"))
        run.finish()
        self.assertEqual(run.result.code, CODE_TEXT)
        for secret in (CODE_TEXT, STATE, canary, str(port), "127.0.0.1"):
            self.assertNotIn(secret.encode(), answer, secret)
        head, _, body = answer.partition(b"\r\n\r\n")
        lines = head.decode("ascii").split("\r\n")
        self.assertEqual(lines[0], "HTTP/1.1 200 OK")
        self.assertEqual(sorted(line.split(":", 1)[0] for line in lines[1:]), sorted(["Content-Type", "Cache-Control", "Referrer-Policy", "Content-Security-Policy", "X-Content-Type-Options", "Connection", "Content-Length"]))
        self.assertIn("Content-Type: text/html; charset=utf-8", lines)
        self.assertIn("Cache-Control: no-store", lines)
        self.assertIn("Referrer-Policy: no-referrer", lines)
        self.assertIn("Content-Security-Policy: default-src 'none'", lines)
        self.assertIn("X-Content-Type-Options: nosniff", lines)
        self.assertIn("Connection: close", lines)
        self.assertEqual(body, lb.PAGE)
        self.assertIn("로그인이 끝났어요", body.decode("utf-8"))
        self.assertNotIn(b"<script", body.lower())

    def test_a_wrong_state_gets_400_and_the_window_keeps_listening(self):
        """B-02 — 남이 보낸 요청이 로그인을 끝내 버리지 못한다. 틀린 요청은 400 뿐이고 코드는 어디로도 나가지 않는다."""
        listener = self.open()
        port = listener.port
        run = Run(listener)
        wrong = talk(port, valid(port, state="W" * 43, code="4/0CANARY_FORGED_CODE_ABCDEFGH"))
        self.assertTrue(wrong.startswith(b"HTTP/1.1 400 "))
        self.assertTrue(run.thread.is_alive(), "틀린 state 로는 끝나지 않는다")
        right = talk(port, valid(port))
        run.finish()
        self.assertTrue(right.startswith(b"HTTP/1.1 200 "))
        self.assertEqual((run.result.code, run.result.served), (CODE_TEXT, 2))
        self.assertNotIn("FORGED", repr(run.result))

    def test_state_that_is_a_prefix_or_longer_or_empty_is_wrong(self):
        listener = self.open()
        port = listener.port
        run = Run(listener)
        for state in (STATE[:-1], STATE + "x", "", "%00"):
            self.assertTrue(talk(port, valid(port, state=state)).startswith(b"HTTP/1.1 400 "), state)
        talk(port, valid(port))
        run.finish()
        self.assertEqual(run.result.code, CODE_TEXT)

    def test_an_error_answer_with_the_right_state_ends_the_window_with_the_error_name(self):
        listener = self.open()
        port = listener.port
        run = Run(listener)
        answer = talk(port, f"GET /callback?error=access_denied&state={STATE} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode("ascii"))
        run.finish()
        self.assertTrue(answer.startswith(b"HTTP/1.1 200 "))
        self.assertEqual((run.result.code, run.result.error), (str(), "access_denied"))
        self.assertNotIn("access_denied", answer.decode("ascii", "replace"), "오류 이름도 되풀이하지 않는다")

    def test_an_error_answer_with_a_wrong_state_does_not_end_the_window(self):
        listener = self.open()
        port = listener.port
        run = Run(listener)
        self.assertTrue(talk(port, f"GET /callback?error=access_denied&state=bad HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode("ascii")).startswith(b"HTTP/1.1 400 "))
        self.assertTrue(run.thread.is_alive())
        talk(port, valid(port))
        run.finish()
        self.assertEqual(run.result.code, CODE_TEXT)

    def test_an_error_name_that_is_not_a_short_word_is_reported_as_a_plain_error(self):
        listener = self.open()
        port = listener.port
        run = Run(listener)
        talk(port, f"GET /callback?error=CANARY%20<script>&state={STATE} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode("ascii"))
        run.finish()
        self.assertEqual((run.result.code, run.result.error), (str(), "error"))

    def check_refused(self, build_cases):
        """거절할 요청들을 차례로 보내고(모두 센다) 마지막에 올바른 요청이 와야 끝난다 — 연결은 모두 여덟 번까지라 한 시험에 일곱을 넘기지 않는다."""
        listener = self.open()
        port = listener.port
        run = Run(listener)
        cases = build_cases(port)
        self.assertLessEqual(len(cases), lb.MAX_CONNECTIONS - 1)
        for label, (data, status) in cases.items():
            with self.subTest(label=label):
                self.assertTrue(talk(port, data).startswith(status), label)
        self.assertTrue(run.thread.is_alive())
        talk(port, valid(port))
        run.finish()
        self.assertEqual((run.result.code, run.result.served), (CODE_TEXT, len(cases) + 1), "거절한 연결도 모두 센다")

    def test_other_host_headers_are_refused_with_400_and_counted(self):
        """BT-24 — 다른 호스트·호스트 없음·다른 포트·이름 호스트·호스트 둘은 400 이다(다른 사이트가 이름 풀이를 바꿔 두드리는 것을 막는다)."""
        def cases(port):
            good_host = f"Host: 127.0.0.1:{port}\r\n"
            return {"다른 호스트": (valid(port, host="evil.example"), b"HTTP/1.1 400 "), "호스트 없음": (f"GET /callback?code=a&state={STATE} HTTP/1.1\r\n\r\n".encode(), b"HTTP/1.1 400 "),
                    "다른 포트": (valid(port, host="127.0.0.1:1"), b"HTTP/1.1 400 "), "이름 호스트": (valid(port, host=f"localhost:{port}"), b"HTTP/1.1 400 "),
                    "호스트 둘": (f"GET /callback?code=a&state={STATE} HTTP/1.1\r\n{good_host}{good_host}\r\n".encode(), b"HTTP/1.1 400 ")}
        self.check_refused(cases)

    def test_other_paths_and_methods_are_refused_with_404_and_counted(self):
        def cases(port):
            good_host = f"Host: 127.0.0.1:{port}\r\n"
            return {"다른 길": (f"GET /other?code=a&state={STATE} HTTP/1.1\r\n{good_host}\r\n".encode(), b"HTTP/1.1 404 "), "아이콘": (f"GET /favicon.ico HTTP/1.1\r\n{good_host}\r\n".encode(), b"HTTP/1.1 404 "),
                    "POST": (f"POST /callback?code=a&state={STATE} HTTP/1.1\r\n{good_host}Content-Length: 0\r\n\r\n".encode(), b"HTTP/1.1 404 "),
                    "길 끝에 붙임": (f"GET /callback/x?code=a&state={STATE} HTTP/1.1\r\n{good_host}\r\n".encode(), b"HTTP/1.1 404 "),
                    "대문자 길": (f"GET /Callback?code=a&state={STATE} HTTP/1.1\r\n{good_host}\r\n".encode(), b"HTTP/1.1 404 ")}
        self.check_refused(cases)

    def test_head_and_shapes_that_are_not_get_callback_are_never_a_result(self):
        listener = self.open()
        port = listener.port
        run = Run(listener)
        for data in (f"HEAD /callback?code=a&state={STATE} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n", f"OPTIONS /callback HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n",
                     f"GET http://127.0.0.1:{port}/callback?code=a&state={STATE} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n", f"GET /callback?code=a&state={STATE}\r\n\r\n", "\r\n\r\n", "GARBAGE\r\n\r\n"):
            talk(port, data.encode("ascii"))
        self.assertTrue(run.thread.is_alive())
        talk(port, valid(port))
        run.finish()
        self.assertEqual(run.result.code, CODE_TEXT)

    def test_a_missing_or_doubled_or_odd_code_is_400(self):
        def cases(port):
            host = f"Host: 127.0.0.1:{port}\r\n"
            return {query[:30]: (f"GET /callback?{query.replace(' ', '%20')} HTTP/1.1\r\n{host}\r\n".encode("ascii"), b"HTTP/1.1 400 ")
                    for query in (f"state={STATE}", f"code=&state={STATE}", f"code=a&code=b&state={STATE}", f"code=a&state={STATE}&state={STATE}", f"code=a b&state={STATE}", f"code=<x>&state={STATE}")}
        self.check_refused(cases)

    def test_too_many_fields_or_a_too_long_value_is_400(self):
        def cases(port):
            host = f"Host: 127.0.0.1:{port}\r\n"
            return {label: (f"GET /callback?{query} HTTP/1.1\r\n{host}\r\n".encode("ascii"), b"HTTP/1.1 400 ")
                    for label, query in (("필드 열둘", "&".join([f"code=a&state={STATE}"] + [f"f{n}=1" for n in range(12)])), ("값 2100자", f"code={'a' * 2100}&state={STATE}"))}
        self.check_refused(cases)

    def test_an_oversized_request_line_or_head_is_refused_without_reading_forever(self):
        listener = self.open()
        port = listener.port
        run = Run(listener)
        host = f"Host: 127.0.0.1:{port}\r\n"
        self.assertTrue(talk(port, f"GET /callback?code={'a' * 5000}&state={STATE} HTTP/1.1\r\n{host}\r\n".encode()).startswith(b"HTTP/1.1 400 "))
        self.assertTrue(talk(port, ("GET /callback HTTP/1.1\r\n" + host + "".join(f"X-{n}: {'v' * 200}\r\n" for n in range(60)) + "\r\n").encode()).startswith(b"HTTP/1.1 400 "))
        self.assertTrue(talk(port, b"A" * 20000).startswith(b"HTTP/1.1 400 "), "끝없는 글도 상한에서 끊고 400 으로 답한다")
        self.assertTrue(run.thread.is_alive())
        talk(port, valid(port))
        run.finish()
        self.assertEqual(run.result.code, CODE_TEXT)

    def test_a_slow_request_is_dropped_after_the_read_limit_and_the_window_goes_on(self):
        listener = self.open()
        port = listener.port
        with mock.patch.object(lb, "READ_SECONDS", 0.4):
            run = Run(listener)
            started = time.monotonic()
            answer = talk(port, b"GET /callback?code=a", timeout=5.0)                       # 나머지를 보내지 않는다
            self.assertLess(time.monotonic() - started, 4.0)
            self.assertTrue(answer.startswith(b"HTTP/1.1 400 "), "느린 요청은 읽기 제한에서 끊고 400 으로 답한다")
            self.assertTrue(run.thread.is_alive())
            talk(port, valid(port))
            run.finish()
        self.assertEqual(run.result.code, CODE_TEXT)

    def test_only_eight_connections_are_served_and_the_ninth_is_refused(self):
        """BT-29 — 길이 틀린 요청도 센다. 여덟 번째 뒤에는 창구가 닫혀 아홉째 연결은 되지 않는다."""
        self.assertEqual(lb.MAX_CONNECTIONS, 8, "여덟 — 아래 반복 횟수를 상수에서 가져오므로 숫자는 여기서 글자로 못박는다(재작업 1 — 시험 렌즈 Q R5)")
        listener = self.open()
        port = listener.port
        run = Run(listener)
        for number in range(lb.MAX_CONNECTIONS):
            talk(port, f"GET /x{number} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
        run.finish()
        self.assertEqual((run.result, type(run.error).__name__, run.error.reason), (None, "LoginWindowError", lb.REASON_TOO_MANY))
        with self.assertRaises(OSError):
            talk(port, valid(port), timeout=2.0)
        self.assertNoOutside()

    def test_the_window_stops_at_the_deadline_and_on_cancel(self):
        """BT-27 — 180초(시계를 앞으로 보낸다)·취소 단추. 어느 쪽이든 포트는 닫혀 있다."""
        now = [1000.0]

        def clock():
            now[0] += 40.0
            return now[0]

        listener = self.open()
        port = listener.port
        with mock.patch.object(lb, "_clock", clock), mock.patch.object(lb, "ACCEPT_TICK", 0.01):
            run = Run(listener)
            run.finish()
        self.assertEqual(run.error.reason, lb.REASON_TIMEOUT)
        self.assertEqual(lb.TOTAL_SECONDS, 180.0)
        with self.assertRaises(OSError):
            talk(port, valid(port), timeout=2.0)
        second = self.open()
        flag = [False]
        with mock.patch.object(lb, "ACCEPT_TICK", 0.02):
            run = Run(second, cancelled=lambda: flag[0])
            time.sleep(0.15)
            self.assertTrue(run.thread.is_alive())
            flag[0] = True
            run.finish()
        self.assertEqual(run.error.reason, lb.REASON_CANCELLED)
        self.assertIsNone(second._sock)

    def test_closing_twice_and_waiting_after_close_are_safe(self):
        listener = self.open()
        listener.close()
        listener.close()
        with self.assertRaises(lb.LoginWindowError) as caught:
            listener.wait(STATE)
        self.assertEqual(caught.exception.reason, lb.REASON_CANCELLED)

    def test_a_bad_expected_state_never_listens(self):
        listener = self.open()
        with self.assertRaises(lb.LoginWindowError):
            listener.wait("short")
        self.assertIsNone(listener._sock)

    def test_the_callback_object_hides_the_code_in_its_text(self):
        callback = lb.Callback(CODE_TEXT, str(), 1)
        for shown in (repr(callback), str(callback), f"{callback}"):
            self.assertNotIn(CODE_TEXT, shown)

    def test_a_bind_failure_is_reported_with_a_fixed_reason_and_closes_the_socket(self):
        with mock.patch.object(socket.socket, "bind", side_effect=OSError(98, "CANARY_OS_TEXT")):
            with self.assertRaises(lb.LoginWindowError) as caught:
                lb.open_listener()
        self.assertEqual(caught.exception.reason, lb.REASON_BIND)
        self.assertNotIn("CANARY_OS_TEXT", repr(caught.exception) + str(caught.exception))


def raw(first, port, extra=""):
    """요청 줄 하나(글 또는 바이트)와 올바른 `Host` 머리글이 든 요청 — 요청 줄은 시험이 정하고 나머지는 올바르다."""
    first = first.encode("latin-1") if isinstance(first, str) else first
    return first + f"\r\nHost: 127.0.0.1:{port}\r\n{extra}\r\n".encode("ascii")


class HostileRequestTest(Base):
    """재작업 1 필수-1 — 이 PC 의 어떤 프로그램이 어떤 요청을 보내도 로그인 창구는 죽지 않는다: 거절(400, 방법이 다르면 404)하고 계속 들으며 이어서 오는 올바른 콜백을 받는다.
    안전 검증 S 의 탐침 A1(`//[x` 한 줄에 `wait()` 가 `ValueError` 로 끝났다)을 시험으로 옮기고 같은 종류의 모양을 더했다. 요청마다 연결 횟수를 세므로 한 시험에 일곱을 넘기지 않는다."""

    def check(self, build_cases):
        listener = self.open()
        port = listener.port
        run = Run(listener)
        cases = build_cases(port)
        self.assertLessEqual(len(cases), lb.MAX_CONNECTIONS - 1)
        for label, (data, status) in cases.items():
            with self.subTest(label=label):
                try:
                    answer = talk(port, data)
                except OSError as error:
                    self.fail(f"{label}: 창구가 이미 끝나서 연결이 되지 않는다({type(error).__name__}) — wait() 의 끝: {run.error!r}")
                self.assertTrue(answer.startswith(status), f"{label}: {answer[:40]!r}")
                self.assertTrue(run.thread.is_alive(), f"{label}: 요청 하나로 창구가 끝났다 — {run.error!r}")
        self.assertIsNone(run.error)
        talk(port, valid(port))
        run.finish()
        self.assertIsNone(run.error)
        self.assertEqual((run.result.code, run.result.served), (CODE_TEXT, len(cases) + 1), "거절한 연결도 모두 세고 마지막 올바른 콜백은 받는다")
        self.assertNoOutside()

    def test_a_path_that_starts_with_two_slashes_is_a_400_and_never_ends_the_window(self):
        """탐침 A1 — `//[x`·`//x]`·`//[::1` 은 주소 쪼개기가 예외를 던지던 글이고 `//호스트/길`·`///callback?…` 은 쪼개기가 사이트 이름·빈 이름으로 읽는 글이다. 마지막 것은 `state` 와 `code` 가 **맞는** 요청이라
        길 검사가 없으면 올바른 콜백으로 받아들여진다 — 그래도 길이 `//` 로 시작하면 거절한다."""
        def cases(port):
            paths = ["//[x", "//x]", "//[::1", "//[v1.x]/callback", "//host/path", f"//callback?code=a&state={STATE}", f"///callback?code={CODE_TEXT}&state={STATE}"]
            return {path[:26]: (raw(f"GET {path} HTTP/1.1", port), b"HTTP/1.1 400 ") for path in paths}
        self.check(cases)

    def test_bad_percent_encodings_odd_bytes_and_long_paths_are_refused_and_the_window_goes_on(self):
        def cases(port):
            state_query = f"state={STATE}"
            return {"퍼센트 뒤가 16진수가 아님": (raw(f"GET /callback?code=%zz&{state_query} HTTP/1.1", port), b"HTTP/1.1 400 "),
                    "끝이 잘린 퍼센트": (raw(f"GET /callback?code=abc%&{state_query} HTTP/1.1", port), b"HTTP/1.1 400 "),
                    "state 가 잘못된 UTF-8": (raw("GET /callback?code=abc&state=%ff%fe%c3 HTTP/1.1", port), b"HTTP/1.1 400 "),
                    "길에 제어 문자": (raw(b"GET /call\x01back?code=a HTTP/1.1", port), b"HTTP/1.1 400 "),
                    "길에 DEL": (raw(b"GET /callback\x7f?code=a HTTP/1.1", port), b"HTTP/1.1 400 "),
                    "길에 ASCII 가 아닌 바이트": (raw(b"GET /callback\xe9?code=a HTTP/1.1", port), b"HTTP/1.1 400 "),
                    "아주 긴 길": (raw("GET /" + "a" * 5000 + " HTTP/1.1", port), b"HTTP/1.1 400 ")}
        self.check(cases)

    def test_a_percent_zero_zero_in_the_path_and_a_long_but_legal_path_are_404_and_the_window_goes_on(self):
        def cases(port):
            return {"길 속 %00": (raw(f"GET /callback%00?code=a&state={STATE} HTTP/1.1", port), b"HTTP/1.1 404 "),
                    "한도 안의 긴 길": (raw("GET /" + "a" * 3900 + " HTTP/1.1", port), b"HTTP/1.1 404 "),
                    "점 마디": (raw(f"GET /./callback?code=a&state={STATE} HTTP/1.1", port), b"HTTP/1.1 404 "),
                    "위로 가기": (raw(f"GET /x/../callback?code=a&state={STATE} HTTP/1.1", port), b"HTTP/1.1 404 ")}
        self.check(cases)

    def test_an_empty_or_broken_request_line_is_400(self):
        def cases(port):
            return {"빈 요청 줄": (raw("", port), b"HTTP/1.1 400 "), "방법만": (raw("GET", port), b"HTTP/1.1 400 "), "버전이 없음": (raw("GET /callback", port), b"HTTP/1.1 400 "),
                    "조각이 넷": (raw(f"GET /callback?code=a&state={STATE} HTTP/1.1 extra", port), b"HTTP/1.1 400 "), "공백 둘": (raw(f"GET  /callback?code=a&state={STATE} HTTP/1.1", port), b"HTTP/1.1 400 "),
                    "HTTP/2": (raw(f"GET /callback?code=a&state={STATE} HTTP/2.0", port), b"HTTP/1.1 400 "), "탭으로 가른 조각": (raw(f"GET\t/callback?code=a&state={STATE}\tHTTP/1.1", port), b"HTTP/1.1 400 ")}
        self.check(cases)

    def test_methods_that_are_not_get_are_404_whatever_the_path_and_the_window_goes_on(self):
        def cases(port):
            query = f"/callback?code={CODE_TEXT}&state={STATE}"
            return {method: (raw(f"{method} {query} HTTP/1.1", port, "Content-Length: 0\r\n"), b"HTTP/1.1 404 ") for method in ("POST", "PUT", "DELETE", "HEAD", "TRACE", "get", "PATCH")}
        self.check(cases)

    def test_connect_and_options_shapes_are_404_and_the_window_goes_on(self):
        def cases(port):
            return {"CONNECT": (raw("CONNECT example.test:443 HTTP/1.1", port), b"HTTP/1.1 404 "), "OPTIONS *": (raw("OPTIONS * HTTP/1.1", port), b"HTTP/1.1 404 "),
                    "방법이 길다": (raw("G" * 300 + " /callback HTTP/1.1", port), b"HTTP/1.1 404 "), "방법이 숫자": (raw("12345 /callback HTTP/1.1", port), b"HTTP/1.1 404 ")}
        self.check(cases)

    def test_an_unexpected_error_while_judging_a_request_is_a_400_and_the_window_goes_on(self):
        """어느 곳에서 예상 밖의 예외가 나도(여기서는 요청을 따지는 함수가 한 번 깨진다 — 올바른 요청도 그 한 번은 400) 창구는 죽지 않고 예외의 글은 답에도 결과에도 나오지 않는다."""
        real = lb._parse
        calls = []

        def flaky(lines, port):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("CANARY_PARSER_FAILURE")
            return real(lines, port)

        listener = self.open()
        port = listener.port
        with mock.patch.object(lb, "_parse", flaky):
            run = Run(listener)
            first = talk(port, valid(port))
            self.assertTrue(first.startswith(b"HTTP/1.1 400 "), first[:40])
            self.assertNotIn(b"CANARY_PARSER_FAILURE", first)
            self.assertTrue(run.thread.is_alive(), f"예상 밖의 예외 하나로 창구가 끝났다 — {run.error!r}")
            talk(port, valid(port))
            run.finish()
        self.assertIsNone(run.error)
        self.assertEqual((run.result.code, run.result.served), (CODE_TEXT, 2))
        self.assertNotIn("CANARY_PARSER_FAILURE", repr(run.result))
        self.assertNoOutside()

    def test_a_socket_error_while_reading_the_head_is_a_400_too_and_the_window_goes_on(self):
        real = lb._read_head
        calls = []

        def flaky(conn, deadline):
            calls.append(1)
            if len(calls) == 1:
                raise OSError(10038, "CANARY_SOCKET_FAILURE")
            return real(conn, deadline)

        listener = self.open()
        port = listener.port
        with mock.patch.object(lb, "_read_head", flaky):
            run = Run(listener)
            first = talk(port, valid(port))
            self.assertNotIn(b"CANARY_SOCKET_FAILURE", first)
            self.assertTrue(run.thread.is_alive(), f"읽다가 난 소켓 오류 하나로 창구가 끝났다 — {run.error!r}")
            talk(port, valid(port))
            run.finish()
        self.assertEqual((run.error, run.result.code, run.result.served), (None, CODE_TEXT, 2))

    def test_the_parser_turns_a_url_split_error_into_a_rejection_and_asks_the_splitter_nothing_for_a_double_slash(self):
        lines = [f"GET /callback?code=a&state={STATE} HTTP/1.1", "Host: 127.0.0.1:4242"]
        with mock.patch.object(lb, "urlsplit", side_effect=ValueError("CANARY_SPLIT_FAILURE")):
            with self.assertRaises(lb._Rejected) as caught:
                lb._parse(lines, 4242)
        self.assertEqual(caught.exception.status, 400)
        self.assertNotIn("CANARY_SPLIT_FAILURE", repr(caught.exception) + str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__, "쪼개기의 예외는 이어 붙이지 않는다")
        with mock.patch.object(lb, "urlsplit", side_effect=AssertionError("길이 // 로 시작하면 쪼개기를 부르지 않는다")):
            with self.assertRaises(lb._Rejected) as caught:
                lb._parse(["GET //[x HTTP/1.1", "Host: 127.0.0.1:4242"], 4242)
        self.assertEqual(caught.exception.status, 400)
        for target in ("//[x", "//x]", "//[::1", "//host/path", "///callback"):
            with self.subTest(target=target), self.assertRaises(lb._Rejected) as caught:
                lb._parse([f"GET {target} HTTP/1.1", "Host: 127.0.0.1:4242"], 4242)
            self.assertEqual(caught.exception.status, 400, target)

    def test_a_normal_callback_still_parses_and_a_single_slash_path_never_trips_the_url_splitter(self):
        """고침이 정상 요청을 막지 않는다 — `/callback?…`(퍼센트·질의 포함)은 그대로 받고, 길이 `/` 하나로 시작하면 이상한 글(대괄호·이중 빗금이 안쪽에 있는 길)도 쪼개기가 예외를 던지지 않고 404 로 거절된다."""
        for target in (f"/callback?code=a&state={STATE}", f"/callback?code=a%2Fb&state={STATE}", "/callback"):
            fields = lb._parse([f"GET {target} HTTP/1.1", "Host: 127.0.0.1:4242"], 4242)
            self.assertIsInstance(fields, dict, target)
        for target in ("/x?" + "a" * 3000, "/[x", "/x]", "/a//[b", "/?//[x"):
            with self.assertRaises(lb._Rejected) as caught:
                lb._parse([f"GET {target} HTTP/1.1", "Host: 127.0.0.1:4242"], 4242)
            self.assertEqual(caught.exception.status, 404, target)


class Drip:
    """느리게 보내는 나쁜 연결 하나 — 요청 하나를 보내 답(404)을 받게 한 뒤 **서버가 쓰기를 닫은 다음에도** `gap` 초마다 1바이트씩 `seconds` 동안 보낸다(안전 검증 S 의 탐침 A7).
    받는 쪽이 끝(FIN)을 본 뒤에도 보낼 수 있는 반닫힘이다. 서버가 연결을 닫으면 스스로 끝난다."""

    def __init__(self, port, *, seconds=6.0, gap=0.01):
        self.port, self.seconds, self.gap = port, seconds, gap
        self.stop = threading.Event()
        self.sent = 0
        self.thread = threading.Thread(target=self._go, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _go(self):
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=5.0) as conn:
                conn.sendall(f"GET /nope HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode("ascii"))
                end = time.monotonic() + self.seconds
                while not self.stop.is_set() and time.monotonic() < end:
                    try:
                        conn.sendall(b"x")
                    except OSError:
                        return                                                 # 서버가 연결을 닫았다 — 이 나쁜 연결의 일은 끝났다
                    self.sent += 1
                    self.stop.wait(self.gap)
        except OSError:
            return

    def finish(self):
        self.stop.set()
        self.thread.join(5.0)


class SlowCloseTest(Base):
    """재작업 1 필수-2 — 답을 보낸 뒤 남은 요청을 읽어 버리는 일은 **전체 시간**으로 묶여 있다. 안전 검증 S 의 탐침 A7: 연결 하나가 1바이트씩 천천히 보내면 한 번의 `recv` 제한(0.2초)만으로는 끝나지 않아
    `wait()` 가 마감(3초)이 아니라 15초 넘게 돌았고 취소도 정상 콜백도 먹지 않았다(설계 L4·L13)."""

    def start_drip(self, port, **kwargs):
        drip = Drip(port, **kwargs).start()
        self.addCleanup(drip.finish)
        return drip

    def test_the_linger_after_a_reply_is_bounded_in_total_time_even_when_the_peer_keeps_dripping(self):
        listener = self.open()
        listener._sock.settimeout(5.0)
        drip = self.start_drip(listener.port, seconds=6.0)
        conn, _peer = listener._sock.accept()
        with conn:
            began = time.monotonic()
            lb._send(conn, lb.NOT_FOUND_RESPONSE)
            elapsed = time.monotonic() - began
        drip.finish()
        self.assertLess(elapsed, 2.0, f"읽어 버리기가 {elapsed:.2f}초 걸렸다 — 전체 시간으로 묶이지 않았다(상대가 계속 보내는 동안 안 끝났다)")
        self.assertGreater(drip.sent, 0, "시험이 헛돌지 않았다 — 나쁜 연결이 실제로 보내고 있었다")
        self.assertNoOutside()

    def test_the_total_time_of_the_linger_is_short_so_it_cannot_slow_the_deadline_or_a_cancel(self):
        """전체 시간 상수 자체를 못박는다 — 다른 시험의 한도가 이 상수에서 계산되면 상수를 늘려도 시험이 따라 늘어나 못 잡는다(변이 R-M06 이 그랬다)."""
        self.assertGreater(lb.LINGER_SECONDS, 0)
        self.assertLessEqual(lb.LINGER_SECONDS, 1.0, "답을 보낸 뒤 읽어 버리는 전체 시간은 1초 이하여야 마감·취소·정상 콜백을 늦추지 않는다")

    def test_the_linger_does_not_wait_for_a_silent_peer_longer_than_its_total_time(self):
        """보내지도 닫지도 않는 상대 — 한 번의 `recv` 제한이 남은 시간을 넘지 않으니 읽어 버리기는 전체 시간 안에 끝난다(답은 그대로 간다)."""
        listener = self.open()
        listener._sock.settimeout(5.0)
        peer = socket.create_connection(("127.0.0.1", listener.port), timeout=5.0)
        self.addCleanup(peer.close)
        conn, _address = listener._sock.accept()
        with conn:
            began = time.monotonic()
            lb._send(conn, lb.BAD_RESPONSE)
            elapsed = time.monotonic() - began
        self.assertLess(elapsed, 2.0, f"조용한 상대를 {elapsed:.2f}초 기다렸다 — 한 번의 recv 제한이 남은 시간보다 길다")
        self.assertTrue(peer.recv(65536).startswith(b"HTTP/1.1 400 "))
        self.assertNoOutside()

    def test_the_linger_still_drains_what_the_browser_already_sent_before_closing(self):
        """묶은 뒤에도 천천히 닫는 본래 이유는 남는다 — 이미 와 있던 남은 요청은 읽어 버리고 닫는다(윈도가 읽지 않은 데이터 때문에 연결을 끊어 답이 사라지는 일을 막는다)."""
        listener = self.open()
        port = listener.port
        run = Run(listener)
        extra = "X-Padding: " + "p" * 3000 + "\r\n"
        answer = talk(port, f"GET /nope HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{extra}\r\n".encode("ascii") + b"q" * 20000)
        self.assertTrue(answer.startswith(b"HTTP/1.1 404 "), answer[:40])
        self.assertTrue(run.thread.is_alive())
        talk(port, valid(port))
        run.finish()
        self.assertEqual(run.result.code, CODE_TEXT)

    def test_the_window_ends_at_its_deadline_even_while_one_connection_drips_after_its_reply(self):
        listener = self.open()
        port = listener.port
        began = time.monotonic()
        with mock.patch.object(lb, "ACCEPT_TICK", 0.05):
            run = Run(listener, seconds=1.0)
            drip = self.start_drip(port, seconds=6.0)
            run.finish(10.0)
        elapsed = time.monotonic() - began
        drip.finish()
        self.assertEqual((type(run.error).__name__, run.error.reason), ("LoginWindowError", lb.REASON_TIMEOUT))
        self.assertLess(elapsed, 1.0 + 2.5, f"마감 1초인 창구가 {elapsed:.2f}초 만에 끝났다 — 나쁜 연결 하나가 마감을 늦췄다")
        self.assertIsNone(listener._sock)

    def test_a_cancel_is_honoured_while_one_connection_drips_after_its_reply(self):
        listener = self.open()
        port = listener.port
        flag = [False]
        with mock.patch.object(lb, "ACCEPT_TICK", 0.05):
            run = Run(listener, seconds=60.0, cancelled=lambda: flag[0])
            drip = self.start_drip(port, seconds=6.0)
            time.sleep(0.6)
            self.assertTrue(run.thread.is_alive())
            flag[0] = True
            cancelled_at = time.monotonic()
            run.finish(10.0)
        elapsed = time.monotonic() - cancelled_at
        drip.finish()
        self.assertEqual(run.error.reason, lb.REASON_CANCELLED)
        self.assertLess(elapsed, 2.5, f"취소가 {elapsed:.2f}초 뒤에야 먹었다 — 나쁜 연결 하나가 취소를 막았다")
        self.assertIsNone(listener._sock)

    def test_a_real_callback_is_answered_and_received_while_another_connection_drips(self):
        listener = self.open()
        port = listener.port
        with mock.patch.object(lb, "ACCEPT_TICK", 0.05):
            run = Run(listener, seconds=20.0)
            drip = self.start_drip(port, seconds=8.0)
            time.sleep(0.5)
            self.assertTrue(run.thread.is_alive())
            answer = talk(port, valid(port), timeout=4.0)
            run.finish(10.0)
        drip.finish()
        self.assertTrue(answer.startswith(b"HTTP/1.1 200 "), f"정상 콜백이 답을 받지 못했다: {answer[:40]!r}")
        self.assertIsNone(run.error)
        self.assertEqual((run.result.code, run.result.served), (CODE_TEXT, 2))
        self.assertNoOutside()


class ExclusiveBindTest(Base):
    def test_windows_asks_for_exclusive_use_and_other_systems_ask_for_no_reuse_option(self):
        """BT-25 — 설정하는 소켓 옵션은 윈도의 독점 바인딩 하나뿐이고, 윈도가 아니면 아무것도 설정하지 않는다."""
        options = []
        real = socket.socket.setsockopt

        def spy(sock, *args):
            options.append(args)
            return real(sock, *args)

        with mock.patch.object(socket.socket, "setsockopt", spy):
            self.open()
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.assertEqual(options, [(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)])
        else:
            self.assertEqual(options, [])
        for option in options:
            self.assertNotIn(option[1], [getattr(socket, "SO_REUSEADDR", -1), getattr(socket, "SO_REUSEPORT", -1)])

    @unittest.skipUnless(hasattr(socket, "SO_EXCLUSIVEADDRUSE"), "윈도 전용 — 독점 바인딩의 효과")
    def test_on_windows_a_second_socket_cannot_take_the_same_port_even_when_it_asks_to_reuse(self):
        listener = self.open()
        intruder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(intruder.close)
        intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)                 # 독점이 아니면 이 요청으로 같은 포트를 가로챌 수 있다
        with self.assertRaises(OSError):
            intruder.bind(("127.0.0.1", listener.port))
        plain = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(plain.close)
        with self.assertRaises(OSError):
            plain.bind(("127.0.0.1", listener.port))

    def test_the_exclusive_option_constant_exists_on_windows_in_this_python(self):
        """설계서 Q18 — `SO_EXCLUSIVEADDRUSE` 가 이 파이썬(3.10·3.12·3.13)의 윈도에 있다."""
        if sys.platform == "win32":
            self.assertTrue(hasattr(socket, "SO_EXCLUSIVEADDRUSE"))


class GateTest(unittest.TestCase):
    def test_with_the_switch_off_no_socket_is_ever_created(self):
        """BT-80·81 의 창구 쪽 — 스위치가 꺼져 있으면 소켓을 만들기 전에 거절한다."""
        created = []
        with mock.patch.object(socket, "socket", side_effect=lambda *args, **kwargs: created.append(args)), og.Tripwire() as wire:
            with self.assertRaises(AppError) as caught:
                lb.open_listener()
        self.assertEqual((caught.exception.code, created, wire.calls), ("NETWORK_DISABLED", [], []))
        listener = lb.LoopbackListener(mock.Mock(), 1234)
        with self.assertRaises(AppError) as caught:
            listener.wait(STATE)
        self.assertEqual(caught.exception.code, "NETWORK_DISABLED")
        listener.close()

    def test_the_draft_switch_alone_does_not_open_the_window(self):
        with mock.patch.object(capabilities, "NET_BLOGGER_DRAFT", True), mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
            with self.assertRaises(AppError) as caught:
                lb.open_listener()
        self.assertEqual(caught.exception.code, "NETWORK_DISABLED")


if __name__ == "__main__":
    unittest.main()
