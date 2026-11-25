"""'접속 0' 시험의 확장(NET 설계서 NT-50–NT-55, E7·E8, D-734) — 스위치를 켠 채로도 **사용자가 누르기 전에는 바깥 호출이 0** 임을 못박는다.

기존 `test_external_write_zero` 는 그대로 두고(한 줄도 안 바뀌었다) 여기서 '스위치를 하나씩 켠 채'·'스위치를 모두 켠 채'·'키가 있는 채'로 같은 부명령·화면 어댑터 훑기를 더한다. 어떤 스위치를 켜도
(그리고 어댑터 공장이 아직 없어도) 시작·모든 화면 읽기·`doctor`(`--online` 없이)·확인 없는 명령은 소켓·`http.client`·`urlopen`·하위 프로세스·`os` 실행·브라우저를 한 번도 부르지 않는다.
확인한 동작이 가짜 전송기에만 닿는다는 것(NT-55)과 `Tripwire(loopback_only=True)` 가 루프백만 통과시킨다는 것, 그 판정이 글자 읽기 가드와 같다는 것도 여기서 본다.
"""
import contextlib
import dataclasses
import importlib.util
import io
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import net_support as ns  # noqa: E402
import outgoing_support as og  # noqa: E402
import service_support as ss  # noqa: E402
import test_external_write_zero as zero  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.net import client, usage  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.service import cli, doctor, external, wiring  # noqa: E402
from chanceblog_desktop.service.context import make_context  # noqa: E402

ROOT = HERE.parent
NEW = ("NET_UPDATE_CHECK", "NET_PAGES_SITE", "PAGES_BRANCH_PUSH", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT")
EVERYTHING = ("EXTERNAL_WRITE", "BLOGGER_OAUTH_INPUT") + NEW


def unregister_all():
    """꽂힌 어댑터를 모두 뺀다(시험 뒷정리 — 종류가 늘어도 빠뜨리지 않게 `KINDS` 전체)."""
    for kind in external.KINDS:
        external.unregister(kind)


@contextlib.contextmanager
def switches(*names):
    with contextlib.ExitStack() as stack:
        for name in names:
            stack.enter_context(mock.patch.object(capabilities, name, True))
        yield


def sweep_commands(test, ctx, with_yes=False):
    """모든 말단 부명령을 한 번씩(확인 옵션 없이) 돌린다 → (돌린 수, 문제 목록). 결과 코드는 따지지 않고 예외로 끝나지 않음과 바깥 호출 0 만 본다."""
    parser = cli.build_parser()
    ran, problems = 0, []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for path, leaf in zero.leaf_commands(parser):
            argv = zero.argv_for(path, leaf, tmp, with_yes=with_yes)
            out, err = io.StringIO(), io.StringIO()
            try:
                code = cli.main(argv, out=out, err=err, ctx=ctx, env={}, stdin=io.StringIO(""))
            except SystemExit as stop:
                problems.append((" ".join(argv[:2]), "SystemExit", stop.code))
                continue
            if code not in (0, 1, 2):
                problems.append((" ".join(argv[:2]), "exit", code))
            ran += 1
    return ran, problems


class EverySwitchAloneTest(unittest.TestCase):
    def tearDown(self):
        unregister_all()

    def fresh_ctx(self, tmp, keystore=None):
        ctx = make_context(data_dir=str(Path(tmp) / "data"), env={}, expected_origin=ss.LOCAL_ORIGIN, clock=ss.Clock())
        return dataclasses.replace(ctx, keystore=keystore) if keystore is not None else ctx

    def test_default_build_every_subcommand_and_adapter_makes_zero_calls(self):
        """NT-50 — 기본 빌드(스위치 모두 꺼짐): 새 부명령이 생겨도 자동으로 훑고, 어댑터는 하나도 꽂히지 않는다."""
        leaves = zero.leaf_commands(cli.build_parser())
        self.assertGreaterEqual(len(leaves), 50)
        self.assertEqual(capabilities.open_switch_names(), ())
        with tempfile.TemporaryDirectory() as tmp, og.Tripwire() as wire:
            ran, problems = sweep_commands(self, self.fresh_ctx(tmp))
        self.assertEqual((wire.calls, problems), ([], []))
        self.assertGreaterEqual(ran, 50)
        self.assertEqual(external.registered_kinds(), ())

    def test_each_switch_alone_without_user_action_makes_zero_calls(self):
        """NT-51 — 스위치를 하나씩만 켠 채(그리고 모두 켠 채) 모든 부명령(확인 없이)이 바깥 호출 0 이고, 켜진 스위치의 어댑터 종류만 꽂힌다."""
        for names in [(name,) for name in EVERYTHING] + [EVERYTHING]:
            with self.subTest(open=names), tempfile.TemporaryDirectory() as tmp:
                with switches(*names), og.Tripwire() as wire:
                    ran, problems = sweep_commands(self, self.fresh_ctx(tmp))
                    kinds = external.registered_kinds()
                self.assertEqual((wire.calls, problems), ([], []), f"스위치 {names} 를 켠 채 바깥 호출이 있었다")
                self.assertGreaterEqual(ran, 50)
                self.assertEqual(kinds, ("blogger", "pages_git", "update") if names == EVERYTHING else {"NET_BLOGGER_OAUTH": ("blogger",), "NET_UPDATE_CHECK": ("update",)}.get(names[0], ()), names)
                unregister_all()

    def test_each_switch_with_credentials_but_without_confirmation_makes_zero_calls(self):
        """NT-52 — 키·토큰이 보관소에 있어도 `--yes`·확인이 없으면 0(`--yes` 를 줘도 이 빌드에는 어댑터가 없어 0 이다)."""
        store = MemoryStore()
        for ref in ("github_repo:aaaaaaaa", "ai_assist:bbbbbbbb", "blogger:cccccccc"):
            try:
                store.put(ref, {"api_key": ns.CANARY})
            except Exception:               # noqa: BLE001 - 보관소가 거절하는 이름 모양은 건너뛴다(대조 — 하나는 들어간다)
                continue
        self.assertGreaterEqual(len(store.list_refs()), 1)
        for names, with_yes in (((NEW[0],), False), (EVERYTHING, False), (EVERYTHING, True)):                    # 모든 조합은 NT-51 이 이미 훑는다 — 여기서는 키가 있는 채로 대표 셋(시험 시간을 줄인다)
            with self.subTest(open=names, yes=with_yes), tempfile.TemporaryDirectory() as tmp:
                with switches(*names), og.Tripwire() as wire:
                    ran, problems = sweep_commands(self, self.fresh_ctx(tmp, keystore=store), with_yes=with_yes)
                self.assertEqual((wire.calls, problems), ([], []))
                unregister_all()

    def test_start_up_and_loading_every_screen_makes_zero_calls_even_with_all_switches_on(self):
        """NT-53 — 시작(맥락 만들기)과 화면이 서비스를 읽는 모든 어댑터 동작은 스위치를 모두 켠 채로도 바깥 호출 0 이다."""
        with tempfile.TemporaryDirectory() as tmp, switches(*EVERYTHING), og.Tripwire() as wire:
            ctx = make_context(data_dir=str(Path(tmp) / "data"), env={}, clock=ss.Clock())
            self.assertEqual(ctx.git, external.refusing_git)
            self.assertIsInstance(ctx.backend, external.LocalOnlyBackend, "자리표시자 어댑터도 파일만 읽는 backend 와 같은 일을 한다")
            from chanceblog_desktop.ui.adapters import ServiceHomeProvider
            data = Path(tmp) / "data2"
            data.mkdir()
            home = ServiceHomeProvider(str(data))
            progress, cancelled = (lambda *a, **k: None), (lambda: False)
            for call in (lambda: home.load_home(progress, cancelled), lambda: home.load_connections(progress, cancelled), lambda: home.blogs_provider().load_blogs(progress, cancelled),
                         lambda: home.candidates_provider().load_candidates(progress, cancelled), lambda: home.drafts_provider().list_saved(progress, cancelled), lambda: home.seeds_provider().load_seeds(progress, cancelled),
                         lambda: home.backups_provider().load_backups(progress, cancelled)):
                with contextlib.suppress(Exception):
                    call()
            unregister_all()
        self.assertEqual(wire.calls, [])

    def test_doctor_without_online_makes_zero_calls_and_lists_open_switches(self):
        """NT-54 — `doctor`(`--online` 없이)는 접속하지 않고 열려 있는 스위치 이름을 알린다(기본은 '없음')."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(usage, "SESSION", usage.Usage()):         # 같은 프로세스의 다른 시험이 남긴 전역 세션 기록과 무관하게(CI 는 시험 전부를 한 프로세스로 돈다)
            ctx = self.fresh_ctx(tmp)
            with og.Tripwire() as wire:
                results = doctor.run_doctor(ctx)
            line = next(item for item in results if item.name == "인터넷 접속")
            self.assertEqual((line.status, line.code), ("ok", ""))
            self.assertIn("열려 있는 스위치가 없어요", line.message)
            self.assertIn("0건", line.message)
            self.assertNotIn("\n", line.message)
            with switches("NET_UPDATE_CHECK", "PAGES_BRANCH_PUSH"), og.Tripwire() as wire2:
                results = doctor.run_doctor(ctx)
            line = next(item for item in results if item.name == "인터넷 접속")
            self.assertEqual(line.status, "warn")
            self.assertIn("NET_UPDATE_CHECK, PAGES_BRANCH_PUSH", line.message)
            self.assertEqual((wire.calls, wire2.calls), ([], []))
            out, err = io.StringIO(), io.StringIO()
            with og.Tripwire() as wire3:
                code = cli.main(["doctor"], out=out, err=err, ctx=ctx, env={})
            self.assertEqual((code, wire3.calls), (0, []))
            self.assertIn("인터넷 접속", out.getvalue())


class ConfirmedActionTest(unittest.TestCase):
    def test_a_confirmed_action_reaches_only_the_fake_transport(self):
        """NT-55 — 사용자가 확인한 동작(여기서는 클라이언트 요청)은 가짜 전송기에만 닿고 `Tripwire` 는 0 이다. 쿨다운·기록도 그 한 건만 남는다."""
        env = ns.Harness(self, ns.http_response(200, headers=[("Content-Type", "application/json")], body=b"{}"), switches=ns.USE_SWITCHES["update_check"])
        with env, og.Tripwire() as wire:
            response = env.client.request("update_check", "GET", "https://github.com/shine88pc/chanceblog-desktop/releases/latest/download/update-manifest.json")
        self.assertEqual((response.status, wire.calls, len(env.dials), len(env.usage.records())), (200, [], 1, 1))
        self.assertTrue(env.last_socket.closed, "끝나면 연결을 닫는다")
        self.assertEqual(env.usage._active, set())


class RegistrationFollowsSwitchesTest(unittest.TestCase):
    def tearDown(self):
        unregister_all()

    def test_registration_follows_the_switches_both_ways(self):
        """NT-18 — 켜진 스위치와 등록된 종류가 정확히 같다: 켜지지 않았는데 등록되지 않고, 켜졌으면 등록된다(`naver_publish` 는 스위치가 없어 늘 미등록)."""
        names = ("EXTERNAL_WRITE", "PAGES_BRANCH_PUSH", "NET_BLOGGER_OAUTH", "NET_UPDATE_CHECK")
        import itertools
        for bits in itertools.product((False, True), repeat=4):
            unregister_all()
            opened = {name for name, bit in zip(names, bits) if bit}
            expected = tuple(sorted(kind for kind, wanted in (("pages_git", {"EXTERNAL_WRITE", "PAGES_BRANCH_PUSH"} <= opened), ("blogger", "NET_BLOGGER_OAUTH" in opened), ("update", "NET_UPDATE_CHECK" in opened)) if wanted))
            with self.subTest(open=sorted(opened)), switches(*opened):
                self.assertEqual(wiring.register_enabled(), expected)
                self.assertEqual(external.registered_kinds(), expected)
                self.assertNotIn("naver_publish", external.registered_kinds())
        unregister_all()
        self.assertEqual(external.registered_kinds(), (), "스위치를 모두 끄면 등록도 없다(기본 빌드)")
        self.assertEqual(wiring.register_enabled(), ())

    def test_the_wiring_never_overwrites_an_adapter_a_test_plugged_and_never_removes_anything(self):
        marker = object()
        with external.registered(external.KIND_PAGES_GIT, lambda **parts: marker), switches("EXTERNAL_WRITE", "PAGES_BRANCH_PUSH"):
            self.assertEqual(wiring.register_enabled(), ("pages_git",))
            self.assertIs(external.pages_backend(), marker)
        with external.registered(external.KIND_BLOGGER, lambda **parts: marker):
            self.assertEqual(wiring.register_enabled(), ("blogger",), "스위치가 꺼져 있어도 이미 꽂힌 것을 빼지 않는다")

    def test_the_placeholder_adapters_open_nothing(self):
        with switches("EXTERNAL_WRITE", "PAGES_BRANCH_PUSH", "NET_BLOGGER_OAUTH"):
            wiring.register_enabled()
            backend = external.pages_backend(expected_origin=ss.LOCAL_ORIGIN)
            self.assertIsInstance(backend, external.LocalOnlyBackend)
            from chanceblog_desktop.errors import AppError
            with self.assertRaises(AppError) as caught:
                backend.push(Path("x"), None)
            self.assertEqual(caught.exception.code, "EXTERNAL_WRITE_DISABLED")


class TripwireLoopbackTest(unittest.TestCase):
    """E8 — `Tripwire` 는 기존 모드가 한 글자도 바뀌지 않았고, 새 `loopback_only` 모드는 루프백만 진짜로 통과시킨다."""

    LOOPBACK = ("127.0.0.1", "127.1.2.3", "::1", "localhost", "LOCALHOST", "localhost.localdomain", "[::1]")
    OUTSIDE = ("192.168.1.5", "10.0.0.1", "8.8.8.8", "169.254.169.254", "0.0.0.0", "example.com", "localhost.example", "127.0.0.1.evil.com", "fe80::1", "metadata.google.internal", "localhostx")

    def test_the_default_mode_still_blocks_even_loopback(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            with og.Tripwire() as wire:
                with self.assertRaises(og.OutgoingBlocked):
                    socket.create_connection(("127.0.0.1", port), timeout=2)
            self.assertEqual(wire.kinds(), ["socket"])
        finally:
            listener.close()

    def test_loopback_only_mode_lets_a_real_loopback_connection_through_and_blocks_everything_else(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            with og.Tripwire(loopback_only=True) as wire:
                with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                    self.assertEqual(sock.getpeername()[1], port)
                self.assertEqual(wire.calls, [], "루프백은 막지도 세지도 않는다")
                for host in self.OUTSIDE:
                    with self.subTest(host=host):
                        with self.assertRaises(og.OutgoingBlocked):
                            socket.create_connection((host, 80), timeout=1)
                        with self.assertRaises(og.OutgoingBlocked):
                            socket.getaddrinfo(host, 80)
                with self.assertRaises(og.OutgoingBlocked):
                    socket.gethostbyname("example.com")
                with self.assertRaises(og.OutgoingBlocked):
                    sock = socket.socket()
                    sock.settimeout(1)
                    sock.connect(("93.184.216.34", 80))
                import http.client
                with self.assertRaises(og.OutgoingBlocked):
                    http.client.HTTPSConnection("example.com", 443, timeout=1).connect()
                import urllib.request
                with self.assertRaises(og.OutgoingBlocked):
                    urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=1)                 # urlopen 은 루프백이어도 막는다(이 틀은 쓰지 않는다)
            self.assertEqual(sorted(set(wire.kinds())), ["http", "socket"])
            self.assertGreaterEqual(wire.count(), len(self.OUTSIDE) * 2)
        finally:
            listener.close()

    def test_the_other_kinds_are_blocked_in_loopback_mode_too(self):
        import subprocess
        with og.Tripwire(loopback_only=True) as wire:
            with self.assertRaises(og.OutgoingBlocked):
                subprocess.Popen(["x"])
            with self.assertRaises(og.OutgoingBlocked):
                __import__("os").system("x")
        self.assertEqual(wire.kinds(), ["os", "subprocess"])

    def test_the_loopback_table_equals_the_text_reading_guard_table(self):
        """6.1-3 — 판정 함수가 글자 읽기 가드(`ocr_addon/netguard._is_loopback`)와 같은 표다(두 구현이 어긋나지 않게)."""
        spec = importlib.util.spec_from_file_location("netguard_for_net_zero", ROOT / "ocr_addon" / "netguard.py")
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        for host in self.LOOPBACK + self.OUTSIDE + ("", None, "127.0.0.1%lo", "::ffff:127.0.0.1", "0:0:0:0:0:0:0:1", "2130706433", "127.1", "LocalHost.LocalDomain", " localhost"):
            with self.subTest(host=host):
                self.assertEqual(og.is_loopback(host), guard._is_loopback(host), repr(host))
        for host in self.LOOPBACK:
            self.assertTrue(og.is_loopback(host), host)
        for host in self.OUTSIDE:
            self.assertFalse(og.is_loopback(host), host)


if __name__ == "__main__":
    unittest.main()
