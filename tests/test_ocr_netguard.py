"""소켓 가드(`ocr_addon/netguard.py`)의 **주소 분류**와 **래퍼 열 개**를 가짜 소켓 모듈 위에서 하나씩 시험한다(검증 S 지적 SP-2, 결정 D-512·D-526).

왜 가짜 소켓 모듈인가: 가드는 파이썬 `socket` 모듈의 함수·메서드를 바꿔 끼운다. 이 시험은 진짜 `netguard.py` 소스를 **가짜 `socket` 모듈**(기록만 하는 함수들)에 얹어 설치한다 — 진짜 소켓 모듈은 건드리지 않고(다른 시험에 새지 않음),
패킷은 어디로도 나가지 않으며(가드가 망가진 변이에서도 가짜 원본이 불릴 뿐이다), 가드가 막았다면 가짜 원본이 한 번도 안 불린다는 사실로 '막힘' 을 직접 본다.
(진짜 작업자 프로세스에서 진짜 소켓으로 막히는지는 `test_ocr_worker_guard.py` 가 따로 본다.)

지키는 것:
  1) 분류(`_is_loopback`) — 루프백(127.0.0.0/8·::1·localhost·localhost.localdomain)만 통과하고, 사설망(192.168·10·172.16)·링크 로컬(169.254 — 클라우드 메타데이터 주소 포함)·IPv6 주소·'localhost' 로 시작하는 바깥 이름·숫자로만 쓴 모양은 모두 막는다.
  2) 래퍼 열 개(connect·connect_ex·sendto·create_connection·getaddrinfo·gethostbyname·gethostbyname_ex·gethostbyaddr·getnameinfo·getfqdn)가 **각각 따로** 바깥 주소를 막고(원본을 안 부르고 오류) 루프백은 원본에 넘기며 센다.
  3) 시도·루프백 횟수, 최근 대상 목록(메모리에만, 20개), 설치 점검(`verify_installed`)·되풀이 설치.
  4) 감사 훅 한 겹(감사 OCR-S1 R5, 결정 D-587) — `_socket` 을 곧바로 쓰는 호출(파이썬 래퍼를 안 지난다)도 같은 규칙으로 막고 세며, 훅은 못 빼므로 **켜짐 표시로만** 일한다: 켜기 전·끈 뒤에는 소켓 호출이 그대로 간다.
     이 네 번째 묶음만 진짜 `socket`·`_socket` 위에서 돈다(래퍼는 설치하지 않고 감사 훅만 켠다). 쓰는 바깥 주소는 패킷이 나갈 수 없는 `0.0.0.1` 숫자 주소뿐이고 이름 풀이는 가짜 이벤트(`sys.audit`)로만 한다(DNS 질의가 없다).
"""
import errno
import importlib.util
import ipaddress
import socket
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GUARD = ROOT / "ocr_addon" / "netguard.py"

WRAPPERS = ("socket.connect", "socket.connect_ex", "socket.sendto", "socket.create_connection", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr",
            "socket.getnameinfo", "socket.getfqdn")
# 막혀야 하는 바깥 주소·이름 — 사설망 셋·링크 로컬(클라우드 메타데이터)·공용·'이 네트워크'·IPv6·'localhost' 로 시작하는 바깥 이름·루프백을 흉내 낸 이름
OUTSIDE = ("192.168.1.5", "10.0.0.1", "172.16.5.5", "169.254.169.254", "8.8.8.8", "0.0.0.1", "0.0.0.0", "100.64.0.1", "224.0.0.1", "255.255.255.255", "192.0.2.1", "fe80::1", "2001:db8::1", "fc00::1",
           "localhost.example", "localhost.evil.com", "localhostx", "127.0.0.1.evil.com", "example.com", "metadata.google.internal")
LOOPBACK = ("127.0.0.1", "127.1.2.3", "127.255.255.254", "::1", "localhost", "LOCALHOST", "localhost.localdomain")


def make_fake_socket_module():
    """기록만 하는 가짜 `socket` 모듈 -> (모듈, 불린 원본 기록 목록)."""
    calls = []
    module = types.ModuleType("socket")

    class gaierror(OSError):
        pass

    class socket:
        def connect(self, address):
            calls.append(("socket.connect", address))

        def connect_ex(self, address):
            calls.append(("socket.connect_ex", address))
            return 0

        def sendto(self, data, *rest):
            calls.append(("socket.sendto", rest[-1]))
            return len(data)

    def record(name, value=None):
        def function(*args, **kwargs):
            calls.append((name, args[0] if args else kwargs))
            return value
        return function
    module.gaierror, module.socket, module.EAI_NONAME = gaierror, socket, 11001
    module.create_connection = record("socket.create_connection", "fake-socket")
    module.getaddrinfo = record("socket.getaddrinfo", [("family", "type", 0, "", ("0.0.0.0", 0))])
    module.gethostbyname = record("socket.gethostbyname", "0.0.0.0")
    module.gethostbyname_ex = record("socket.gethostbyname_ex", ("name", [], ["0.0.0.0"]))
    module.gethostbyaddr = record("socket.gethostbyaddr", ("name", [], ["0.0.0.0"]))
    module.getnameinfo = record("socket.getnameinfo", ("name", "80"))
    module.getfqdn = record("socket.getfqdn", "name")
    return module, calls


_counter = [0]


def load_guard(install=True):
    """진짜 netguard 소스를 가짜 socket 모듈에 얹어 새로 불러온다 -> (가드 모듈, 가짜 socket 모듈, 불린 원본 기록)."""
    fake, calls = make_fake_socket_module()
    _counter[0] += 1
    spec = importlib.util.spec_from_file_location("netguard_under_test_%d" % _counter[0], str(GUARD))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"socket": fake}):
        spec.loader.exec_module(module)                              # 가드의 `import socket` 이 가짜를 가져온다(진짜 socket 모듈은 그대로)
    if install:
        module.install()
    return module, fake, calls


def address(host, port=80):
    """IPv6 주소는 4개 칸, 그 밖은 2개 칸 주소로(소켓 주소 모양)."""
    return (host, port, 0, 0) if ":" in host else (host, port)


class ClassificationTest(unittest.TestCase):
    def setUp(self):
        self.guard, _fake, _calls = load_guard(install=False)

    def test_loopback_forms_pass(self):
        for host in LOOPBACK + ("[::1]", "0:0:0:0:0:0:0:1", "::1%lo", b"127.0.0.1", None, "", ("127.0.0.1", 80), ["::1", 80, 0, 0], ("localhost", 9)):
            with self.subTest(host=repr(host)):
                self.assertTrue(self.guard._is_loopback(host))

    def test_private_link_local_public_ipv6_and_look_alike_names_are_blocked(self):
        for host in OUTSIDE + ("fe80::1%eth0", "[fe80::1]", "::", "2130706433", "0x7f.0.0.1", "127.1", " 127.0.0.1", "127.0.0.1 ", "localhost.", "localhost:80", "LOCALHOST.EVIL.COM", 2130706433,
                               ("8.8.8.8", 53), ("fe80::1", 80, 0, 0), ("localhost.example", 80), b"8.8.8.8"):
            with self.subTest(host=repr(host)):
                self.assertFalse(self.guard._is_loopback(host))

    def test_the_first_item_of_an_address_tuple_decides(self):
        self.assertTrue(self.guard._is_loopback(("127.0.0.1", "8.8.8.8")))
        self.assertFalse(self.guard._is_loopback(("8.8.8.8", "127.0.0.1")))
        self.assertEqual(self.guard._host_of(("a", 1)), "a")
        self.assertEqual(self.guard._host_of(b"abc"), "abc")


class InstalledGuardCase(unittest.TestCase):
    def setUp(self):
        self.guard, self.fake, self.calls = load_guard()
        self.socket = self.fake.socket()

    def attempts(self):
        return self.guard.stats()["attempts"]

    def loopback(self):
        return self.guard.stats()["loopback"]

    def assert_blocked(self, call, exception, label):
        before_calls, before = len(self.calls), self.attempts()
        with self.assertRaises(exception, msg=label):
            call()
        self.assertEqual(len(self.calls), before_calls, "막혔다면 원본(가짜)이 불리지 않는다: " + label)
        self.assertEqual(self.attempts(), before + 1, "막힌 시도는 한 번 센다: " + label)

    def assert_passed(self, call, api, label):
        before_calls, before_attempts, before_loopback = len(self.calls), self.attempts(), self.loopback()
        call()
        self.assertEqual(len(self.calls), before_calls + 1, "루프백은 원본에 한 번 넘긴다: " + label)
        self.assertEqual(self.calls[-1][0], api)
        self.assertEqual((self.attempts(), self.loopback()), (before_attempts, before_loopback + 1), "루프백은 시도로 안 세고 따로 센다: " + label)


class EveryWrapperTest(InstalledGuardCase):
    """열 개의 래퍼를 각각 따로 — 하나가 빠지거나 분류가 풀리면 그 시험이 빨개진다."""

    def test_connect_blocks_every_outside_address_and_passes_loopback(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.socket.connect(address(host)), PermissionError, "connect " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.socket.connect(address(host)), "socket.connect", "connect " + host)

    def test_connect_ex_gives_access_denied_without_calling_the_original(self):
        for host in OUTSIDE:
            before_calls, before = len(self.calls), self.attempts()
            self.assertEqual(self.socket.connect_ex(address(host)), errno.EACCES, host)
            self.assertEqual((len(self.calls), self.attempts()), (before_calls, before + 1), host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.socket.connect_ex(address(host)), "socket.connect_ex", "connect_ex " + host)

    def test_sendto_blocks_both_argument_shapes_and_passes_loopback(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.socket.sendto(b"x", address(host)), PermissionError, "sendto " + host)
            self.assert_blocked(lambda: self.socket.sendto(b"x", 0, address(host)), PermissionError, "sendto(flags) " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.socket.sendto(b"x", address(host)), "socket.sendto", "sendto " + host)

    def test_create_connection_blocks_every_outside_address_and_passes_loopback(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.fake.create_connection(address(host), timeout=0.1), PermissionError, "create_connection " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.fake.create_connection(address(host), timeout=0.1), "socket.create_connection", "create_connection " + host)

    def test_getaddrinfo_blocks_every_outside_name_with_a_resolution_error(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.fake.getaddrinfo(host, 80), self.fake.gaierror, "getaddrinfo " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.fake.getaddrinfo(host, 80), "socket.getaddrinfo", "getaddrinfo " + host)

    def test_gethostbyname_blocks_every_outside_name_with_a_resolution_error(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.fake.gethostbyname(host), self.fake.gaierror, "gethostbyname " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.fake.gethostbyname(host), "socket.gethostbyname", "gethostbyname " + host)

    def test_gethostbyname_ex_blocks_every_outside_name_with_a_resolution_error(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.fake.gethostbyname_ex(host), self.fake.gaierror, "gethostbyname_ex " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.fake.gethostbyname_ex(host), "socket.gethostbyname_ex", "gethostbyname_ex " + host)

    def test_gethostbyaddr_blocks_every_outside_address_with_a_resolution_error(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.fake.gethostbyaddr(host), self.fake.gaierror, "gethostbyaddr " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.fake.gethostbyaddr(host), "socket.gethostbyaddr", "gethostbyaddr " + host)

    def test_getnameinfo_blocks_every_outside_address_with_a_resolution_error(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.fake.getnameinfo(address(host), 0), self.fake.gaierror, "getnameinfo " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.fake.getnameinfo(address(host), 0), "socket.getnameinfo", "getnameinfo " + host)

    def test_getfqdn_blocks_a_named_outside_host_and_the_no_argument_form_is_the_local_machine(self):
        for host in OUTSIDE:
            self.assert_blocked(lambda: self.fake.getfqdn(host), self.fake.gaierror, "getfqdn " + host)
        for host in LOOPBACK:
            self.assert_passed(lambda: self.fake.getfqdn(host), "socket.getfqdn", "getfqdn " + host)
        self.assert_passed(lambda: self.fake.getfqdn(), "socket.getfqdn", "getfqdn()")

    def test_a_host_given_by_keyword_is_checked_too(self):
        self.assert_blocked(lambda: self.fake.getaddrinfo(host="8.8.8.8", port=80), self.fake.gaierror, "getaddrinfo(host=)")
        self.assert_blocked(lambda: self.fake.gethostbyname(host="8.8.8.8"), self.fake.gaierror, "gethostbyname(host=)")
        self.assert_blocked(lambda: self.fake.gethostbyaddr(ip_address="8.8.8.8"), self.fake.gaierror, "gethostbyaddr(ip_address=)")


class GuardBookkeepingTest(InstalledGuardCase):
    def test_exactly_the_ten_wrappers_are_installed_and_the_originals_are_remembered(self):
        self.assertTrue(self.guard.ACTIVE)
        self.assertEqual(tuple(sorted(self.guard._orig)), tuple(sorted(WRAPPERS)))
        for name in ("connect", "connect_ex", "sendto"):
            self.assertIsNot(getattr(self.fake.socket, name), self.guard._orig["socket." + name], name)
        for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo", "getfqdn"):
            self.assertIsNot(getattr(self.fake, name), self.guard._orig["socket." + name], name)

    def test_installing_twice_does_not_wrap_the_wrappers(self):
        self.assertTrue(self.guard.install())
        self.assertTrue(self.guard.install())
        self.socket.connect(address("127.0.0.1"))
        self.assertEqual(len(self.calls), 1, "원본은 한 번만 불린다")
        self.assertEqual(self.loopback(), 1)

    def test_the_recent_target_list_is_in_memory_only_and_keeps_twenty(self):
        for number in range(30):
            with self.assertRaises(PermissionError):
                self.socket.connect(("10.0.0.%d" % number, 80))
        stats = self.guard.stats()
        self.assertEqual(stats["attempts"], 30)
        self.assertEqual(len(stats["recent"]), 20)
        self.assertEqual(stats["recent"][-1], ("socket.connect", "10.0.0.29:80"))
        self.assertTrue(stats["active"])

    def test_a_very_long_target_is_cut_to_eighty_characters_in_the_record(self):
        with self.assertRaises(self.fake.gaierror):
            self.fake.getaddrinfo("a" * 300 + ".example", 80)
        api, target = self.guard.stats()["recent"][-1]
        self.assertEqual((api, len(target)), ("socket.getaddrinfo", 80))

    def test_counts_can_be_reset_and_the_install_check_sees_the_block(self):
        with self.assertRaises(PermissionError):
            self.socket.connect(("8.8.8.8", 80))
        self.socket.connect(("127.0.0.1", 80))
        self.guard.reset_counts()
        self.assertEqual((self.guard.attempts(), self.loopback(), self.guard.stats()["recent"]), (0, 0, []))
        before = len(self.calls)
        self.assertTrue(self.guard.verify_installed(), "설치 점검: 문서화된 TEST-NET 주소가 막히고 한 번 센다")
        self.assertEqual(len(self.calls), before, "점검의 연결도 원본(가짜)까지 가지 않는다")

    def test_a_blocked_attempt_never_puts_the_payload_or_a_secret_in_the_record(self):
        with self.assertRaises(PermissionError):
            self.socket.sendto(b"CANARY_SECRET_PAYLOAD", ("8.8.8.8", 9))
        self.assertNotIn("CANARY", repr(self.guard.stats()))


class NotInstalledTest(unittest.TestCase):
    def test_loading_the_module_changes_nothing_until_install_is_called(self):
        guard, fake, calls = load_guard(install=False)
        self.assertFalse(guard.ACTIVE)
        fake.getaddrinfo("8.8.8.8", 80)
        fake.socket().connect(("8.8.8.8", 80))
        self.assertEqual([name for name, _target in calls], ["socket.getaddrinfo", "socket.connect"], "설치 전에는 가짜 원본이 그대로 불린다 — 시험이 가짜 위에서 돈다는 대조")
        guard.install()
        with self.assertRaises(fake.gaierror):
            fake.getaddrinfo("8.8.8.8", 80)


BAD = "0.0.0.1"                         # 패킷이 나갈 수 없는 잘못된 목적지 — 숫자 주소라 이름 풀이(DNS)도 하지 않는다
AUDIT_EVENTS = ["socket.bind", "socket.connect", "socket.getaddrinfo", "socket.gethostbyaddr", "socket.gethostbyname", "socket.getnameinfo", "socket.sendmsg", "socket.sendto"]
NAME_EVENTS = ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo")
_real_copy = []


def shared_real_guard():
    """진짜 `socket` 모듈 위의 가드 사본 하나 — **래퍼는 설치하지 않고**(진짜 소켓 모듈을 바꾸지 않는다) 감사 훅 한 겹만 `enable_audit`·`disable_audit` 로 켜고 끈다. 훅은 한 번 걸면 못 빼므로
    사본을 프로세스에서 한 번만 만들어 모든 시험이 나눠 쓴다(시험마다 새로 걸면 훅이 쌓인다) — 꺼져 있는 동안 훅은 아무것도 하지 않는다."""
    if not _real_copy:
        _real_copy.append(fresh_real_guard())
    return _real_copy[0]


def fresh_real_guard():
    """아직 한 번도 켜지 않은 새 사본(진짜 `socket` 모듈) — 켜기 전의 모습과 훅 거는 횟수를 보는 시험 전용. 켜면 훅이 하나 남으므로 쓰고 나면 꼭 `disable_audit` 를 부른다."""
    spec = importlib.util.spec_from_file_location("netguard_real_socket_under_test_%d" % (len(_real_copy) + 1), str(GUARD))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw_calls():
    """`socket` 모듈의 래퍼를 거치지 않고 `_socket`(C 모듈)을 곧바로 쓰는 바깥 시도 -> {이름: (호출, 감사 이벤트 이름)} — S1 의 probe3 와 같은 모양이다."""
    import _socket

    def on_socket(kind, action):
        sock = _socket.socket(_socket.AF_INET, kind)
        try:
            return action(sock)
        finally:
            sock.close()

    def timed(action):
        def run(sock):
            sock.settimeout(0.5)
            return action(sock)
        return run
    tcp, udp = _socket.SOCK_STREAM, _socket.SOCK_DGRAM
    return {"connect": (lambda: on_socket(tcp, timed(lambda s: s.connect((BAD, 9)))), "socket.connect"),
            "connect_ex": (lambda: on_socket(tcp, timed(lambda s: s.connect_ex((BAD, 9)))), "socket.connect"),
            "sendto": (lambda: on_socket(udp, lambda s: s.sendto(b"x", (BAD, 9))), "socket.sendto"),
            "sendto_with_flags": (lambda: on_socket(udp, lambda s: s.sendto(b"x", 0, (BAD, 9))), "socket.sendto"),
            "bind": (lambda: on_socket(tcp, lambda s: s.bind((BAD, 0))), "socket.bind"),
            "getaddrinfo": (lambda: _socket.getaddrinfo(BAD, 80), "socket.getaddrinfo"),
            "gethostbyname": (lambda: _socket.gethostbyname(BAD), "socket.gethostbyname"),
            "gethostbyname_ex": (lambda: _socket.gethostbyname_ex(BAD), "socket.gethostbyname")}


def outcome(call):
    try:
        return "returned", call()
    except Exception as error:               # noqa: BLE001 — 막힘(PermissionError·gaierror)이든 운영체제의 거절(OSError)이든 모두 받아 본다
        return "raised", error


def is_guard_error(error):
    return isinstance(error, (PermissionError, socket.gaierror)) and "netguard" in str(error)


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.guard = shared_real_guard()
        self.guard.disable_audit()
        self.guard.reset_counts()
        self.addCleanup(self.guard.disable_audit)
        self.addCleanup(self.guard.reset_counts)


class AuditHookBlocksTest(AuditCase):
    def test_each_raw_socket_call_is_blocked_and_counted_once_while_the_audit_layer_is_on(self):
        self.assertTrue(self.guard.enable_audit())
        self.assertTrue(self.guard.stats()["audit"])
        for name, (call, event) in raw_calls().items():
            with self.subTest(call=name):
                before = self.guard.attempts()
                kind, error = outcome(call)
                self.assertEqual(kind, "raised", name + " — connect_ex 도 값을 돌려주지 않고 막힌다")
                self.assertTrue(is_guard_error(error), repr(error))
                self.assertIsInstance(error, socket.gaierror if event in NAME_EVENTS else PermissionError)
                self.assertEqual(self.guard.attempts(), before + 1, "막힌 시도는 한 번 센다")
                api, target = self.guard.stats()["recent"][-1]
                self.assertEqual(api, event)
                self.assertIn(BAD, target)
        self.assertEqual(self.guard.stats()["loopback"], 0, "이 사본에는 래퍼가 없어 루프백 횟수는 훅이 건드리지 않는다")

    def test_loopback_passes_while_it_is_on_and_is_never_counted(self):
        import _socket
        self.guard.enable_audit()
        server = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        self.addCleanup(client.close)
        client.connect(("127.0.0.1", port))
        datagram = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        self.addCleanup(datagram.close)
        datagram.sendto(b"x", ("127.0.0.1", port))
        self.assertEqual(_socket.getaddrinfo("127.0.0.1", 80)[0][4][0], "127.0.0.1")
        self.assertTrue(ipaddress.ip_address(_socket.gethostbyname("localhost")).is_loopback)
        self.assertEqual((self.guard.attempts(), self.guard.stats()["recent"]), (0, []), "루프백은 한 번도 시도로 세지 않는다")

    def test_synthetic_events_for_outside_targets_are_blocked_whatever_the_shape_of_the_address(self):
        """가짜 이벤트(`sys.audit`) — 호출은 일어나지 않으므로 바깥 이름·사설 주소·IPv6·유닉스 경로도 안전하게 모양별로 본다. 래퍼와 같은 분류다."""
        self.guard.enable_audit()
        outside = [("socket.connect", (None, ("example.com", 80))), ("socket.connect", (None, ("8.8.8.8", 53))), ("socket.connect", (None, ("fe80::1", 80, 0, 0))), ("socket.connect", (None, "/tmp/some.sock")),
                   ("socket.connect", (None, ("localhost.evil.example", 80))), ("socket.bind", (None, ("0.0.0.0", 8080))), ("socket.sendto", (None, ("192.168.1.5", 9))), ("socket.sendmsg", (None, ("10.0.0.1", 9))),
                   ("socket.getaddrinfo", ("example.com", 80, 0, 0, 0)), ("socket.getaddrinfo", (b"8.8.8.8", 80, 0, 0, 0)), ("socket.gethostbyname", ("metadata.google.internal",)),
                   ("socket.gethostbyaddr", ("169.254.169.254",)), ("socket.getnameinfo", (("8.8.8.8", 80),))]
        for event, args in outside:
            with self.subTest(event=event, args=repr(args)[:40]):
                before = self.guard.attempts()
                with self.assertRaises(socket.gaierror if event in NAME_EVENTS else PermissionError):
                    sys.audit(event, *args)
                self.assertEqual(self.guard.attempts(), before + 1)
                self.assertEqual(self.guard.stats()["recent"][-1][0], event)

    def test_synthetic_events_for_loopback_targets_pass_and_are_not_counted(self):
        self.guard.enable_audit()
        inside = [("socket.connect", (None, ("127.0.0.1", 80))), ("socket.connect", (None, ("::1", 80, 0, 0))), ("socket.connect", (None, ("localhost", 80))), ("socket.connect", (None, None)),
                  ("socket.bind", (None, ("", 0))), ("socket.bind", (None, ("127.0.0.1", 0))), ("socket.sendto", (None, ("127.0.0.5", 9))), ("socket.sendmsg", (None, ("localhost", 9))),
                  ("socket.getaddrinfo", (None, 80, 0, 0, 0)), ("socket.getaddrinfo", ("localhost", 80, 0, 0, 0)), ("socket.getaddrinfo", (b"127.0.0.1", 80, 0, 0, 0)), ("socket.gethostbyname", ("localhost",)),
                  ("socket.gethostbyaddr", ("127.0.0.1",)), ("socket.getnameinfo", (("127.0.0.1", 80),))]
        for event, args in inside:
            with self.subTest(event=event, args=repr(args)[:40]):
                sys.audit(event, *args)
        self.assertEqual(self.guard.attempts(), 0)

    def test_an_event_whose_shape_cannot_be_read_is_blocked_not_waved_through(self):
        self.guard.enable_audit()
        for event, args in (("socket.connect", ()), ("socket.sendto", (None,)), ("socket.getaddrinfo", ()), ("socket.gethostbyname", ())):
            with self.subTest(event=event):
                before = self.guard.attempts()
                with self.assertRaises((PermissionError, socket.gaierror)):
                    sys.audit(event, *args)
                self.assertEqual(self.guard.attempts(), before + 1)

    def test_other_audit_events_are_ignored_even_while_it_is_on(self):
        self.guard.enable_audit()
        for event, args in (("open", ("x", "r", 0)), ("import", ("m", None, None, None, None)), ("exec", (None,)), ("os.system", ("echo",)), ("socket.__new__", (None, 2, 1, 0)), ("socket.getservbyname", ("http", "tcp")),
                            ("socket.sethostname", ("x",)), ("netguard.other", ())):
            sys.audit(event, *args)
        self.assertEqual(self.guard.attempts(), 0)

    def test_the_audited_events_are_exactly_these_eight(self):
        self.assertEqual(sorted(self.guard._AUDIT_EVENTS), AUDIT_EVENTS, "하나가 빠지면 그 길이 열린다 — 더하면 이 목록과 시험을 함께 고친다")


class AuditHookSwitchTest(AuditCase):
    def test_while_the_audit_layer_is_off_the_same_calls_go_through_untouched(self):
        """꺼진 동안 훅은 아무것도 하지 않는다 — 같은 호출이 그대로 운영체제까지 가고(0.0.0.1 이라 바로 거절되거나 숫자 주소 풀이만 한다) 가드가 세지도 막지도 않는다."""
        for name, (call, _event) in raw_calls().items():
            with self.subTest(call=name):
                kind, value = outcome(call)
                self.assertFalse(kind == "raised" and is_guard_error(value), "꺼져 있는데 가드가 막았다: " + repr(value))
        self.assertEqual((self.guard.attempts(), self.guard.stats()["recent"]), (0, []))
        self.assertEqual(self.guard.stats()["audit"], False)

    def test_a_copy_that_was_never_turned_on_leaves_the_calls_alone(self):
        fresh = fresh_real_guard()
        self.assertEqual((fresh.stats()["audit"], fresh._audit_hooked), (False, False), "불러오기만 해서는 아무것도 걸리지 않는다")
        call, _event = raw_calls()["connect"]
        kind, error = outcome(call)
        self.assertEqual(kind, "raised")
        self.assertFalse(is_guard_error(error), repr(error))
        self.assertEqual(fresh.attempts(), 0)

    def test_it_follows_the_flag_on_off_on_off_and_the_hook_is_hung_only_once(self):
        fresh = fresh_real_guard()
        self.addCleanup(fresh.disable_audit)
        call, _event = raw_calls()["connect"]
        with mock.patch.object(sys, "addaudithook", wraps=sys.addaudithook) as add:
            for round_number in range(3):
                with self.subTest(round=round_number):
                    self.assertTrue(fresh.enable_audit())
                    kind, error = outcome(call)
                    self.assertTrue(is_guard_error(error), "켜짐: 막힌다")
                    self.assertEqual(fresh.attempts(), round_number + 1)
                    fresh.disable_audit()
                    kind, error = outcome(call)
                    self.assertFalse(is_guard_error(error), "꺼짐: 그대로 간다")
                    self.assertEqual(fresh.attempts(), round_number + 1, "꺼진 동안은 세지 않는다")
        self.assertEqual(add.call_count, 1, "훅은 사본에서 한 번만 걸고 그 뒤로는 켜짐 표시만 바꾼다")

    def test_if_the_hook_does_not_really_get_installed_turning_it_on_raises_and_it_stays_off(self):
        """fail closed — 앞서 걸린 다른 훅이 예외를 내면 새 훅이 조용히 안 걸릴 수 있다(문서). 확인 이벤트를 훅이 못 받으면 켜기가 예외로 끝나고 켜짐 표시는 내려가 있다."""
        fresh = fresh_real_guard()
        with mock.patch.object(sys, "addaudithook"):
            with self.assertRaises(RuntimeError):
                fresh.enable_audit()
        self.assertEqual((fresh.stats()["audit"], fresh._audit_hooked), (False, False))

    def test_an_earlier_hook_that_refuses_the_check_event_ends_in_an_error_with_the_flag_down(self):
        fresh = fresh_real_guard()
        with mock.patch.object(sys, "audit", side_effect=OSError("앞선 훅이 거절")):
            with self.assertRaises(OSError):
                fresh.enable_audit()
        self.assertEqual((fresh.stats()["audit"], fresh._audit_hooked), (False, False))


class AuditWiringTest(unittest.TestCase):
    def test_install_turns_the_audit_layer_on_and_an_install_that_cannot_ends_in_an_error(self):
        guard, _fake, _calls = load_guard(install=False)
        guard.enable_audit = mock.Mock(return_value=True)
        self.assertTrue(guard.install())
        guard.enable_audit.assert_called_once_with()
        self.assertTrue(guard.ACTIVE)
        broken, _fake, _calls = load_guard(install=False)
        broken.enable_audit = mock.Mock(side_effect=RuntimeError("훅이 안 걸렸다"))
        with self.assertRaises(RuntimeError):
            broken.install()
        self.assertFalse(broken.ACTIVE, "켜지지 않았으면 켜졌다고 하지 않는다 — 작업자는 시작하지 않는다(종료 코드 70)")

    def test_a_copy_on_a_fake_socket_module_hangs_no_hook_so_the_other_tests_in_the_process_are_never_touched(self):
        guard, fake, _calls = load_guard(install=True)
        self.assertEqual((guard.ACTIVE, guard.stats()["audit"], guard._audit_hooked), (True, False, False))
        self.assertFalse(hasattr(fake, "_socket"))
        self.assertFalse(guard.enable_audit())

    def test_nothing_in_the_add_on_but_the_guard_itself_names_the_off_switch(self):
        """작업자 쪽 소스는 감사 훅을 끄지 않는다 — 끄는 길(`disable_audit`·켜짐 표시)은 시험이 같은 프로세스에서 켰다 끄려고 둔 것이다."""
        for path in sorted((ROOT / "ocr_addon").glob("*.py")):
            if path.name == "netguard.py":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("disable_audit", text, path.name)
            self.assertNotIn("_audit_on", text, path.name)


if __name__ == "__main__":
    unittest.main()
