"""공개 확인을 접속 틀(NET)로 — 가지 올리기(PUBPR)의 어댑터가 공개 주소 확인에서 쓰는 길을 확인한다(설계서 PT-50–52, 외부 접속 0: 가짜 전송기·`Tripwire`).

지키는 것:
  1) `GitBranchBackend.check_deployed` 는 fetcher 를 따로 끼워 넣지 않으면 NET 의 `pages_site` 길(`site_fetcher`)로만 나가고 vendor 도구의 `urlopen` 은 한 번도 불리지 않는다(NT-16 과 짝).
  2) 사이트 호스트는 `<소유자>.github.io` 한 곳이고 소유자·저장소 상수 하나(`gitrepo.EXPECTED_OWNER`·`EXPECTED_REPO`)에서 origin 정규식·사이트 호스트·비교 주소가 모두 나온다 — `_config.yml` 이 다른 호스트
     (사용자 지정 도메인 등)를 가리키면 12분을 기다리지 않고 곧바로 알린다(Q11).
  3) 이동은 같은 호스트로 최대 2번이고 다른 호스트·평문·세 번째 이동은 거절된다 — 접속 틀을 지난 길에서.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import net_support as ns  # noqa: E402
import outgoing_support as og  # noqa: E402
import service_support as ss  # noqa: E402
import test_net_allowlist as na  # noqa: E402
import test_pages_deploy as pd  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net import client, site  # noqa: E402
from chanceblog_desktop.net import usage as usage_module  # noqa: E402
from chanceblog_desktop.net.endpoints import ENDPOINTS  # noqa: E402
from chanceblog_desktop.publish import deploy, gitrepo, pages  # noqa: E402
from chanceblog_desktop.service import wiring  # noqa: E402
from chanceblog_desktop.service.backend import GitBranchBackend  # noqa: E402

OWNER_HOST = f"{gitrepo.EXPECTED_OWNER.lower()}.github.io"
POST = pd.KO_PATH


def setUpModule():
    ss.external_write_on()                                    # 공개 확인 두 관문(`EXTERNAL_WRITE`·`NET_PAGES_SITE`)을 임시로만 연다(소스 상수는 모두 False)


def tearDownModule():
    ss.external_write_off()


class BackendPathTest(unittest.TestCase):
    def test_check_deployed_uses_the_net_fetcher_and_never_urlopen(self):
        """PT-50 — 어댑터를 기본값으로 만들면(fetcher 주입 없음) 공개 확인 요청이 접속 틀(`pages_site` 표: 호스트·`cb=app`·`no-cache`)로만 나가고 `urlopen`·vendor `fetch` 는 불리지 않는다."""
        import urllib.request
        verifier = deploy._verifier()
        na.RoutingSocket.seen = []
        na.RoutingSocket.open_after = 1
        site_dir = pd.Site(pd.CONFIG.replace("https://example.invalid", f"https://{OWNER_HOST}"))
        self.addCleanup(site_dir.cleanup)
        world = pd.FakeWorld()

        def refuse(*args, **kwargs):
            raise AssertionError("vendor 의 접속 길이 불렸다")

        env = ns.Harness(self, switches=("EXTERNAL_WRITE", "NET_PAGES_SITE"))
        env.template = {}

        def factory_dial(connection, address):
            env.dials.append((connection.host, address))
            env.last_socket = na.RoutingSocket(clock=env.clock)
            return env.last_socket

        backend = GitBranchBackend(sleep=world.sleep, monotonic=world.clock)
        self.assertIsNone(backend.fetcher, "기본 어댑터는 fetcher 를 끼워 넣지 않는다 — 공개 확인이 접속 틀로 간다")
        before = usage_module.SESSION.records()
        with env, mock.patch.object(verifier, "fetch", refuse), mock.patch.object(urllib.request, "urlopen", refuse), mock.patch.object(client, "_dial", factory_dial), og.Tripwire() as wire:
            result = backend.check_deployed(site_dir.root, _Post(POST, pd.KO_TEXT), pd.NOW, 0, 1)
        self.assertEqual(wire.calls, [])
        self.assertEqual({host for host, _address in env.dials}, {OWNER_HOST})
        self.assertEqual(result.url, pd.KO_URL.replace("example.invalid", OWNER_HOST))
        self.assertTrue(env.usage.records() and all(record.use == "pages_site" for record in env.usage.records()), "요청이 이 틀의 접속 기록에 남는다")
        self.assertEqual(usage_module.SESSION.records(), before)
        for raw in na.RoutingSocket.seen:
            head = raw.split(b"\r\n\r\n")[0].decode("ascii")
            self.assertRegex(head.splitlines()[0], r"\?cb=app(-[0-9]+)? HTTP/1\.1$")
            self.assertIn("Cache-Control: no-cache", head)

    def test_the_default_factory_builds_the_adapter_without_an_injected_fetcher(self):
        backend = wiring.make_branch_backend(expected_origin=ss.LOCAL_ORIGIN)
        self.assertIsNone(backend.fetcher)
        self.assertIsInstance(backend, GitBranchBackend)

    def test_the_adapter_passes_both_gates_before_any_work(self):
        """둘째 문장이 좁은 스위치다 — `EXTERNAL_WRITE` 만 켠 채로는 접속을 시도하기 전에 거절한다."""
        ss.external_write_off()
        self.addCleanup(ss.external_write_on)
        from capability_support import switch_on, switch_off
        switch_on("EXTERNAL_WRITE")
        self.addCleanup(switch_off, "EXTERNAL_WRITE")
        with og.Tripwire() as wire:
            error = ss.code_of(GitBranchBackend().check_deployed, ".", _Post(POST, pd.KO_TEXT), pd.NOW, 0, 1)
        self.assertEqual((error.code, wire.calls), ("NETWORK_DISABLED", []))


class _Post:
    def __init__(self, path, text):
        self.path, self.text = path, text


class SiteHostTest(unittest.TestCase):
    def test_site_host_is_the_single_fixed_host_and_derived_from_the_owner_constant(self):
        """PT-51 — 호스트 한 곳(`<소유자>.github.io`)이 소유자 상수에서 나오고, origin 정규식·비교 주소도 같은 상수에서 나온다."""
        self.assertEqual(ENDPOINTS["pages_site"].host, OWNER_HOST)
        self.assertEqual(ENDPOINTS["pages_site"].redirect_hosts, ())
        owner, repo = gitrepo.EXPECTED_OWNER, gitrepo.EXPECTED_REPO
        for good in (f"https://github.com/{owner}/{repo}.git", f"https://github.com/{owner}/{repo}", f"git@github.com:{owner}/{repo}.git", f"ssh://git@github.com/{owner}/{repo}.git"):
            self.assertTrue(gitrepo.EXPECTED_ORIGIN.match(good), good)
        for bad in (f"https://github.com/other/{repo}.git", f"https://github.com/{owner}/other.git", f"https://evil.example/{owner}/{repo}.git", f"http://github.com/{owner}/{repo}.git"):
            self.assertFalse(gitrepo.EXPECTED_ORIGIN.match(bad), bad)
        branch = "desktop/post-20261102-103012-0123abcd"
        self.assertTrue(pages.compare_link(branch, "x").startswith(f"https://github.com/{owner}/{repo}/compare/main...{branch}?"))

    def test_a_site_address_on_another_host_is_refused_at_once_without_waiting_or_connecting(self):
        """Q11 — `_config.yml` 의 `url` 이 `<소유자>.github.io` 가 아니면(사용자 지정 도메인·닮은 이름·가는 길에 끼운 이름) 접속하지 않고 곧바로 알린다."""
        hosts = {"사용자 지정 도메인": "https://blog.example.com", "닮은 이름 뒤": f"https://{OWNER_HOST}.evil.example.com", "닮은 이름 앞": f"https://evil-{OWNER_HOST}",
                 "다른 소유자": "https://someoneelse.github.io", "예시 주소": "https://example.invalid"}
        world = pd.FakeWorld()
        for label, url in hosts.items():
            with self.subTest(label=label):
                folder = pd.Site(pd.CONFIG.replace("https://example.invalid", url))
                self.addCleanup(folder.cleanup)
                with og.Tripwire() as wire:
                    error = ss.code_of(_default_fetcher_check, folder.root, world)
                self.assertEqual(error.code, "CONTENT_INVALID")
                self.assertIn(OWNER_HOST, error.detail)
                self.assertEqual((wire.calls, world.sleeps), ([], []), "접속도 기다림도 없었다")

    def test_require_pages_host_accepts_only_the_exact_host_ignoring_case(self):
        deploy.require_pages_host(f"https://{OWNER_HOST}/chanceblog/posts/x/", OWNER_HOST)
        deploy.require_pages_host(f"https://{OWNER_HOST.upper()}/x/", OWNER_HOST)
        for url in (f"https://{OWNER_HOST}.evil.example/", f"https://x.{OWNER_HOST}/", f"https://evil.example/{OWNER_HOST}/", "https://127.0.0.1/", "not a url", ""):
            with self.subTest(url=url):
                self.assertEqual(ss.code_of(deploy.require_pages_host, url, OWNER_HOST).code, "CONTENT_INVALID")


def _default_fetcher_check(root, world):
    """`fetcher` 를 끼우지 않은 기본 경로(NET) — 호스트 점검이 접속 틀을 만들기 전에 막는다."""
    return deploy.check_deployed(root, POST, pd.KO_TEXT, deadline=720, interval=10, sleep=world.sleep, clock=world.clock, now=pd.NOW)


class RedirectPolicyTest(unittest.TestCase):
    URL = f"https://{OWNER_HOST}/chanceblog/posts/2026/11/02/KR-103012/?cb=app"

    def redirect(self, location, status=302):
        return ns.http_response(status, "Found", headers=[("Location", location)])

    def fetch(self, sockets):
        env = ns.Harness(self, sockets=sockets, switches=ns.USE_SWITCHES["pages_site"])
        resp = deploy._verifier().Resp
        with env, og.Tripwire() as wire:
            result = site.site_fetcher(resp, client=env.client)(self.URL)
        self.assertEqual(wire.calls, [])
        return env, result

    def test_redirect_policy_same_host_two_hops(self):
        """PT-52 — 공개 확인 길은 같은 호스트로 최대 두 번 이동을 따라가고, 세 번째 이동·다른 호스트·평문·사용자 정보는 거절한다(오류는 코드 이름으로만 돌아온다)."""
        final = ns.http_response(200, body=b"")
        env, result = self.fetch([ns.FakeSocket(self.redirect("/a?cb=app")), ns.FakeSocket(self.redirect(f"https://{OWNER_HOST}/b?cb=app", 301)), ns.FakeSocket(final)])
        self.assertEqual((result.status, result.error, len(env.dials)), (200, "", 3))
        self.assertTrue(all(host == OWNER_HOST for host, _address in env.dials))
        env, result = self.fetch([ns.FakeSocket(self.redirect(f"/{n}?cb=app")) for n in range(1, 4)] + [ns.FakeSocket(final)])
        self.assertEqual((result.status, result.error, len(env.dials)), (0, "NET_RESPONSE_INVALID", 3), "이동은 최대 두 번 — 세 번째는 거절")
        for label, location in (("다른 호스트", "https://evil.example.test/x?cb=app"), ("평문", f"http://{OWNER_HOST}/x?cb=app"), ("사용자 정보", f"https://u@{OWNER_HOST}/x?cb=app"),
                                ("닮은 이름", f"https://{OWNER_HOST}.evil.example.test/x?cb=app")):
            with self.subTest(label=label):
                env, result = self.fetch([ns.FakeSocket(self.redirect(location)), ns.FakeSocket(final)])
                self.assertEqual((result.status, result.error, len(env.dials)), (0, "NET_RESPONSE_INVALID", 1), label)


if __name__ == "__main__":
    unittest.main()
