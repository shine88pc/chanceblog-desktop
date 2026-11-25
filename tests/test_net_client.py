"""접속 틀 클라이언트(`net/client.py`) 시험 — 가짜 전송기(소켓 모양, 소켓은 한 번도 열리지 않는다)로 NET 설계서의 NT-13·NT-17·NT-19–NT-30·NT-32·NT-35–NT-38 을 확인한다(D-728에서 D-731).

지키는 것:
  1) 관문이 접속 코드의 첫 문장이고, 스위치가 꺼져 있으면 전송기를 한 번도 부르기 전에 거절한다(NT-13·17).
  2) 호스트·길·질의 표가 설계서와 정확히 같다(NT-19). 보낸 바이트는 용도별 고정 모양과 바이트 단위로 같다(NT-20). 호스트·포트·스킴·사용자 정보·닮은 이름·표 밖 모양은 연결 **전에** 거절한다(NT-21·22·23).
  3) 이동은 기본 거절이고 허용 용도만 호스트·https·횟수가 제한된다(NT-24). 큰 응답·압축된 응답·느린 응답을 막는다(NT-25·26·27). 모든 실패는 카탈로그 코드가 되고 주소·서버 글이 없다(NT-28).
  4) 자체 재시도 0(NT-29), 쿨다운(NT-30), 보낸 뒤 실패만 `outcome_unknown`(NT-37), 접속 기록의 칸(NT-38), 카나리가 어디에도 새지 않음(NT-32), 응답이 닿는 곳의 표(NT-35), 틀린 응답은 아무것도 남기지 않음(NT-36).
네트워크 없이 돈다(`Tripwire` 가 바깥 호출을 막는 안에서 돈다).
"""
import ast
import collections
import contextlib
import dataclasses
import hashlib
import http.client
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import net_support as ns  # noqa: E402
import outgoing_support as og  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.net import client, endpoints, errors, parse, site, usage  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402

SRC = HERE.parent / "src" / "chanceblog_desktop"
HOST_UPDATE = "github.com"
UPDATE_PATH = "/own/app/releases/latest/download/update-manifest.json"
UPDATE_URL = f"https://{HOST_UPDATE}{UPDATE_PATH}"
SITE = f"{gitrepo.EXPECTED_OWNER.lower()}.github.io"
SITE_URL = f"https://{SITE}/blog/posts.json?cb=app"
BLOG = "https://www.googleapis.com/blogger/v3/blogs/123456"
JSON = [("Content-Type", "application/json")]
OK_JSON = ns.http_response(200, headers=JSON, body=b'{"id": "1"}')
ALL_SWITCHES = ns.ALL_NET_SWITCHES


def run(test, response, use="update_check", url=UPDATE_URL, *, method="GET", switches=None, harness=None, **kwargs):
    """가짜 전송기로 요청 하나 — (환경, 응답) 을 돌려준다. 접속 차단 장치 안에서 돈다(소켓이 한 번이라도 열리면 빨개진다)."""
    switches = ns.USE_SWITCHES[use] if switches is None else switches
    env = harness or ns.Harness(test, response, switches=switches)
    with env, og.Tripwire() as wire:
        result = env.client.request(use, method, url, **kwargs)
    test.assertEqual(wire.calls, [], "진짜 바깥 호출이 일어났다")
    return env, result


def raised(test, response, *args, **kwargs):
    """요청이 `NetError` 로 끝나야 하는 경우 — (환경, 오류)."""
    switches = kwargs.pop("switches", None)
    use = args[0] if args else kwargs.get("use", "update_check")
    env = kwargs.pop("harness", None) or ns.Harness(test, response, switches=ns.USE_SWITCHES[use] if switches is None else switches)
    with env, og.Tripwire() as wire:
        with test.assertRaises(errors.NetError) as caught:
            env.client.request(*args, **kwargs) if args else env.client.request("update_check", "GET", UPDATE_URL, **kwargs)
    test.assertEqual(wire.calls, [])
    return env, caught.exception


class GateTest(unittest.TestCase):
    def test_every_net_entry_point_passes_its_gate_as_its_first_statement(self):
        """NT-13 — 클라이언트의 두 공개 함수는 첫 문장이 `capabilities.require_net` 이다(설명 글 다음 첫 문장)."""
        tree = ast.parse((SRC / "net" / "client.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "NetClient")
        for name in ("request", "request_to_file"):
            function = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
            body = [node for node in function.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
            self.assertTrue(isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Call) and ast.unparse(body[0].value.func) == "capabilities.require_net", f"{name}: {ast.unparse(body[0])[:70]}")
            self.assertEqual(ast.unparse(body[0].value.args[0]), "use")

    def test_client_refuses_before_any_transport_when_the_switch_is_off(self):
        """NT-17 — 용도마다 스위치가 꺼져 있으면 전송기 호출 0·알맞은 오류 코드, 쿨다운·기록도 건드리지 않는다."""
        wanted = {"update_check": "NETWORK_DISABLED", "pages_site": "EXTERNAL_WRITE_DISABLED", "blogger_oauth": "NETWORK_DISABLED", "blogger_read": "NETWORK_DISABLED", "blogger_draft": "EXTERNAL_WRITE_DISABLED"}
        urls = {"update_check": UPDATE_URL, "pages_site": SITE_URL, "blogger_oauth": "https://oauth2.googleapis.com/token", "blogger_read": BLOG, "blogger_draft": BLOG + "/posts?isDraft=true"}
        for use, code in wanted.items():
            with self.subTest(use=use):
                env = ns.Harness(self, OK_JSON, switches=())
                with env, og.Tripwire() as wire:
                    with self.assertRaises(AppError) as caught:
                        env.client.request(use, "POST" if use in ("blogger_oauth", "blogger_draft") else "GET", urls[use], body=b"x" if use in ("blogger_oauth", "blogger_draft") else None)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual((env.dials, wire.calls, env.usage.records()), ([], [], ()))
                self.assertFalse(env.usage.resting(use))
        for use in ("pages_site", "blogger_draft"):
            with self.subTest(only_write=use):
                env = ns.Harness(self, OK_JSON, switches=("EXTERNAL_WRITE",))
                with env, self.assertRaises(AppError) as caught:
                    env.client.request(use, "GET", SITE_URL)
                self.assertEqual((caught.exception.code, env.dials), ("NETWORK_DISABLED", []), "윗 스위치만 켜서는 열리지 않는다")
        env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"])
        with env, self.assertRaises(AppError) as caught:                      # 모르는 용도 이름도 관문에서 거절된다(전송기 0)
            env.client.request("update_check_x", "GET", UPDATE_URL)
        self.assertEqual((caught.exception.code, env.dials), ("NETWORK_DISABLED", []))
        with env, self.assertRaises(AppError) as caught:                      # git 의 용도는 이 클라이언트의 표에 없다
            with mock.patch.object(capabilities, "PAGES_BRANCH_PUSH", True), mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
                env.client.request("pages_branch", "GET", UPDATE_URL)
        self.assertEqual((caught.exception.code, env.dials), ("UNEXPECTED_ERROR", []))

    def test_the_client_needs_a_version_in_the_documented_shape(self):
        for bad in (None, "", "1.2", "x1.2.3", "1.2.3 ", "1.2.3\r\nX: y", 123):
            with self.subTest(bad=repr(bad)), self.assertRaises(errors.NetError):
                client.NetClient(version=bad)
        client.NetClient(version="1.2.3")
        client.NetClient(version="0.1.0-preview.1")


class HostTableTest(unittest.TestCase):
    EXPECTED = {
        "update_check": ("github.com", ("GET",), ()),
        "pages_site": (SITE, ("GET",), None),
        "blogger_oauth": ("oauth2.googleapis.com", ("POST", "POST"), ()),
        "blogger_read": ("www.googleapis.com", ("GET", "GET", "GET"), None),
        "blogger_draft": ("www.googleapis.com", ("POST",), (("isDraft", "true"),)),
    }

    def test_host_table_is_exactly_the_documented_hosts_and_paths(self):
        """NT-19 — 설계서 3.6 의 표와 소스 표가 같다: 호스트·방법·고정 질의·길 모양."""
        self.assertEqual(sorted(endpoints.ENDPOINTS), sorted(self.EXPECTED))
        for use, (host, methods, query) in self.EXPECTED.items():
            endpoint = endpoints.ENDPOINTS[use]
            with self.subTest(use=use):
                self.assertEqual(endpoint.host, host)
                self.assertEqual(tuple(route.method for route in endpoint.routes), methods)
                if query is not None:
                    self.assertEqual({route.query for route in endpoint.routes}, {query})
        self.assertEqual(endpoints.table_problems(), [])
        hosts = {endpoint.host for endpoint in endpoints.ENDPOINTS.values()} | {host for endpoint in endpoints.ENDPOINTS.values() for host in endpoint.redirect_hosts}
        self.assertEqual(sorted(hosts), sorted({"github.com", SITE, "oauth2.googleapis.com", "www.googleapis.com"}), "표에 있는 호스트가 정확히 이 넷이다")
        self.assertEqual(endpoints.ENDPOINTS["update_check"].redirect_hosts, (), "업데이트 확인의 이동 호스트는 UPDATE 갈래가 확정할 때까지 비어 있다 — 이동은 모두 거절된다")
        redirects = {use: (endpoint.max_redirects, endpoint.redirect_hosts) for use, endpoint in endpoints.ENDPOINTS.items()}
        self.assertEqual(redirects, {"update_check": (0, ()), "pages_site": (2, ()), "blogger_oauth": (0, ()), "blogger_read": (0, ()), "blogger_draft": (0, ())},
                         "이동은 기본 0(거절)이고 열린 곳은 공개 사이트의 같은 호스트 최대 두 번뿐이다(M-NET-10)")
        self.assertLessEqual(len({endpoints.ENDPOINTS["update_check"].host} | set(endpoints.ENDPOINTS["update_check"].redirect_hosts)), 2, "업데이트 확인의 호스트는 최대 둘이다(설계서 3.6)")

    def test_the_blogger_routes_are_the_six_documented_shapes(self):
        read = endpoints.ENDPOINTS["blogger_read"].routes
        self.assertEqual([route.shown for route in read], ["/blogger/v3/blogs/<번호>", "/blogger/v3/blogs/<번호>/posts", "/blogger/v3/blogs/<번호>/posts/<번호>"])
        self.assertEqual(read[1].query, (("status", "DRAFT"), ("orderBy", "UPDATED"), ("maxResults", "5"), ("fetchBodies", "false"), ("view", "ADMIN")))
        self.assertEqual(read[2].query, (("view", "ADMIN"),))
        self.assertTrue(all(route.bearer and not route.max_body for route in read))
        site = endpoints.ENDPOINTS["pages_site"].routes[0]
        self.assertEqual([key for key, _value in site.query], ["cb"])
        self.assertTrue(all(site.query[0][1].fullmatch(value) for value in ("app", "app-1", "app-12", "app-123")))
        self.assertFalse(any(site.query[0][1].fullmatch(value) for value in ("", "other", "app-", "app-1234", "app-x", "xapp", "app ", "APP", "app-1&x=2")), "`cb` 값은 app 또는 app-<시도 번호> 뿐이다")
        self.assertEqual([route.shown for route in endpoints.ENDPOINTS["blogger_oauth"].routes], ["/token", "/revoke"])
        self.assertTrue(all(not route.bearer for route in endpoints.ENDPOINTS["blogger_oauth"].routes), "토큰 요청에는 접근 토큰을 붙이지 않는다")
        self.assertEqual(endpoints.ENDPOINTS["blogger_draft"].routes[0].max_body, 1024 * 1024)
        self.assertEqual(endpoints.ENDPOINTS["blogger_oauth"].routes[0].max_body, 4096)
        self.assertFalse(endpoints.ENDPOINTS["pages_site"].routes[0].bearer, "공개 사이트에는 토큰을 붙이지 않는다")

    def test_the_limits_table_is_exactly_the_documented_values(self):
        """NT-19 의 둘째 몫 — 설계서 3.7 의 시간·크기·내용 인코딩·캐시·쿨다운 제외 표가 소스 상수와 같다(값을 슬쩍 키우거나 늘리는 틀린 코드가 조용히 지나가지 않게)."""
        self.assertEqual((endpoints.CONNECT_TIMEOUT, endpoints.IO_TIMEOUT, endpoints.TOTAL_TIMEOUT), (10.0, 15.0, 30.0))
        self.assertEqual((endpoints.MAX_HEADER_BYTES, endpoints.MAX_URL_CHARS, endpoints.MAX_BEARER_CHARS), (64 * 1024, 500, 4096))
        mib = 1024 * 1024
        self.assertEqual({use: endpoint.max_response for use, endpoint in endpoints.ENDPOINTS.items()},
                         {"update_check": mib, "pages_site": 20 * mib, "blogger_oauth": mib, "blogger_read": 2 * mib, "blogger_draft": 2 * mib})
        for use, endpoint in endpoints.ENDPOINTS.items():
            with self.subTest(use=use):
                self.assertEqual(endpoint.total_timeout, 30.0)
                self.assertEqual((endpoint.download_timeout, endpoint.max_download), (0.0, 0), "내려받기 표는 UPDATE 갈래가 정할 때까지 비어 있다")
                self.assertFalse(any(route.download for route in endpoint.routes), "내려받기 길은 UPDATE 갈래가 정할 때까지 없다")
                self.assertEqual(endpoint.accept_encodings, ("identity", "gzip", "deflate") if use == "pages_site" else ("identity",))
                self.assertEqual(endpoint.cache_control, "no-cache" if use == "pages_site" else "")
                self.assertEqual(endpoint.uncounted_statuses, (400, 404, 422, 429) if use == "pages_site" else (400, 422, 429))

    # 손으로 적은 길 표(D-738, 독립 검증 Q R-3) — 용도·길마다 (방법, 길 글(정규식 글 또는 고정 길), 접속 기록에 적는 길 이름, 고정 질의, 토큰 허용, 본문 종류, 본문 상한, 내려받기 길인가).
    # 코드(`endpoints.py`)와 따로 적은 값이라 길 정규식을 넓히거나(예: 초안 길을 `/posts/<번호>/publish` 까지) 본문 상한·종류를 바꾸면 빨개진다 — 표가 '마지막 방어' 라서 초안 전용 약속이 소리 없이 깨지지 않게 한다.
    NUMBER = "[0-9]{1,25}"
    SEGMENT = "[A-Za-z0-9_-][A-Za-z0-9._-]{0,99}"
    POSTS = f"/blogger/v3/blogs/{NUMBER}/posts"
    FORM = "application/x-www-form-urlencoded"
    SITE_PATH = ("/(?!/)(?!(?:.*/)?\\.\\.(?:/|$))(?!.*%(?:2[eEfF]|5[cC]|00))(?:%[0-9A-Fa-f]{2}|[A-Za-z0-9._" + chr(0x7E) + "+/-]){0,498}")
    ROUTES = {
        "update_check": [("GET", f"/{SEGMENT}/{SEGMENT}/releases/latest/download/{SEGMENT}", "/(릴리스 최신 자산)", (), False, "", 0, False)],
        "pages_site": [("GET", SITE_PATH, "/(공개 사이트)", (("cb", "app(?:-[0-9]{1,3})?"),), False, "", 0, False)],
        "blogger_oauth": [("POST", "/token", "/token", (), False, FORM, 4096, False), ("POST", "/revoke", "/revoke", (), False, FORM, 4096, False)],
        "blogger_read": [("GET", f"/blogger/v3/blogs/{NUMBER}", "/blogger/v3/blogs/<번호>", (), True, "", 0, False),
                         ("GET", POSTS, "/blogger/v3/blogs/<번호>/posts", (("status", "DRAFT"), ("orderBy", "UPDATED"), ("maxResults", "5"), ("fetchBodies", "false"), ("view", "ADMIN")), True, "", 0, False),
                         ("GET", f"{POSTS}/{NUMBER}", "/blogger/v3/blogs/<번호>/posts/<번호>", (("view", "ADMIN"),), True, "", 0, False)],
        "blogger_draft": [("POST", POSTS, "/blogger/v3/blogs/<번호>/posts", (("isDraft", "true"),), True, "application/json; charset=UTF-8", 1024 * 1024, False)],
    }
    FIELDS = {                                                # 용도마다 길 말고 표의 칸 전부(이름 → 값)
        "update_check": dict(host="github.com", accept="application/json", max_response=1024 * 1024, max_redirects=0, redirect_hosts=(), cache_control="", accept_encodings=("identity",), total_timeout=30.0,
                             download_timeout=0.0, max_download=0, keep_headers=(), uncounted_statuses=(400, 422, 429)),
        "pages_site": dict(host=SITE, accept="*/*", max_response=20 * 1024 * 1024, max_redirects=2, redirect_hosts=(), cache_control="no-cache", accept_encodings=("identity", "gzip", "deflate"), total_timeout=30.0,
                           download_timeout=0.0, max_download=0, keep_headers=("age", "last-modified", "cache-control", "x-cache"), uncounted_statuses=(400, 404, 422, 429)),
        "blogger_oauth": dict(host="oauth2.googleapis.com", accept="application/json", max_response=1024 * 1024, max_redirects=0, redirect_hosts=(), cache_control="", accept_encodings=("identity",), total_timeout=30.0,
                              download_timeout=0.0, max_download=0, keep_headers=(), uncounted_statuses=(400, 422, 429)),
        "blogger_read": dict(host="www.googleapis.com", accept="application/json", max_response=2 * 1024 * 1024, max_redirects=0, redirect_hosts=(), cache_control="", accept_encodings=("identity",), total_timeout=30.0,
                             download_timeout=0.0, max_download=0, keep_headers=(), uncounted_statuses=(400, 422, 429)),
        "blogger_draft": dict(host="www.googleapis.com", accept="application/json", max_response=2 * 1024 * 1024, max_redirects=0, redirect_hosts=(), cache_control="", accept_encodings=("identity",), total_timeout=30.0,
                              download_timeout=0.0, max_download=0, keep_headers=(), uncounted_statuses=(400, 422, 429)),
    }

    def test_every_route_and_every_endpoint_field_is_pinned_by_a_hand_written_table(self):
        """R-3 — 용도·길마다 (방법·길 글·길 이름·고정 질의·토큰·본문 종류·본문 상한·내려받기)와 용도의 칸 전부가 손으로 적은 표와 정확히 같다. 표에 칸이 새로 생기면 이 시험도 넓혀야 한다(칸 목록도 못박는다)."""
        import dataclasses as dc
        self.assertEqual({field.name for field in dc.fields(endpoints.Route)}, {"method", "path", "shown", "query", "bearer", "content_type", "max_body", "download"}, "Route 에 칸이 늘었다 — 이 표도 넓힌다")
        self.assertEqual({field.name for field in dc.fields(endpoints.Endpoint)}, {"use", "routes", "label"} | set(next(iter(self.FIELDS.values()))), "Endpoint 에 칸이 늘었다 — 이 표도 넓힌다")
        self.assertEqual(sorted(endpoints.ENDPOINTS), sorted(self.ROUTES))
        for use, endpoint in endpoints.ENDPOINTS.items():
            with self.subTest(use=use):
                actual = [(route.method, route.path_text(), route.shown, tuple((key, value if isinstance(value, str) else value.pattern) for key, value in route.query), route.bearer, route.content_type, route.max_body,
                           route.download) for route in endpoint.routes]
                self.assertEqual(actual, self.ROUTES[use])
                self.assertEqual({name: getattr(endpoint, name) for name in self.FIELDS[use]}, self.FIELDS[use])

    def test_the_page_host_comes_from_the_one_owner_constant_the_origin_check_uses(self):
        self.assertEqual(SITE, f"{gitrepo.EXPECTED_OWNER.lower()}.github.io")
        self.assertTrue(gitrepo.EXPECTED_ORIGIN.match(f"https://github.com/{gitrepo.EXPECTED_OWNER}/{gitrepo.EXPECTED_REPO}.git"))
        self.assertIn(re.escape(gitrepo.EXPECTED_OWNER) + "/" + re.escape(gitrepo.EXPECTED_REPO), gitrepo.EXPECTED_ORIGIN.pattern)
        self.assertFalse(gitrepo.EXPECTED_ORIGIN.match(f"https://github.com/{gitrepo.EXPECTED_OWNER}x/{gitrepo.EXPECTED_REPO}.git"))

    def test_the_table_validator_catches_bad_tables(self):
        good = endpoints.ENDPOINTS["update_check"]
        bad_hosts = ("GitHub.com", "github.com.", "github.com:443", "user@github.com", "gıthub.com", "140.82.1.1", "github", "*.github.com", "a..b.com", "-a.github.com", "")
        for host in bad_hosts:
            with self.subTest(host=host):
                self.assertTrue(endpoints.table_problems({"update_check": dataclasses.replace(good, host=host)}), host)
        self.assertTrue(endpoints.table_problems({"update_check": dataclasses.replace(good, max_redirects=5)}))
        self.assertTrue(endpoints.table_problems({"update_check": dataclasses.replace(good, redirect_hosts=("cdn.example.com",), max_redirects=0)}))
        self.assertTrue(endpoints.table_problems({"update_check": dataclasses.replace(good, accept_encodings=("gzip",))}))
        self.assertTrue(endpoints.table_problems({"other": good}), "표 키와 용도 이름이 다르다")
        self.assertTrue(endpoints.table_problems({"update_check": dataclasses.replace(good, routes=())}))


def golden(method, path, host, *, accept="application/json", encoding="identity", extra=(), body=b""):
    """설계서 3.8 의 요청 모양을 손으로 적은 것(코드와 따로) — 머리글 순서까지 고정이다."""
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}", f"User-Agent: ChanceBlogDesktop/{ns.VERSION}", f"Accept: {accept}", f"Accept-Encoding: {encoding}", "Connection: close"]
    lines += [f"{name}: {value}" for name, value in extra]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


class RequestBytesTest(unittest.TestCase):
    def sent(self, env):
        return bytes(env.last_socket.sent)

    def test_request_bytes_equal_the_golden_shape_for_every_use(self):
        """NT-20 — 보낸 바이트가 용도별 고정 모양과 같다(업데이트 확인은 설계서 3.8 의 모양과 바이트 단위로 같고 버전 번호만 다르다)."""
        env, _ = run(self, OK_JSON)
        self.assertEqual(self.sent(env), golden("GET", UPDATE_PATH, "github.com"))
        env, _ = run(self, ns.http_response(200, body=b"[]"), "pages_site", SITE_URL)
        self.assertEqual(self.sent(env), golden("GET", "/blog/posts.json?cb=app", SITE, accept="*/*", extra=[("Cache-Control", "no-cache")]))
        env, _ = run(self, OK_JSON, "blogger_read", BLOG, bearer="tok.en-1_2")
        self.assertEqual(self.sent(env), golden("GET", "/blogger/v3/blogs/123456", "www.googleapis.com", extra=[("Authorization", "Bearer tok.en-1_2")]))
        env, _ = run(self, OK_JSON, "blogger_read", endpoints.url_for("blogger_read", "GET", "/blogger/v3/blogs/9/posts"), bearer="t")
        self.assertEqual(self.sent(env), golden("GET", "/blogger/v3/blogs/9/posts?status=DRAFT&orderBy=UPDATED&maxResults=5&fetchBodies=false&view=ADMIN", "www.googleapis.com", extra=[("Authorization", "Bearer t")]))
        env, _ = run(self, OK_JSON, "blogger_read", endpoints.url_for("blogger_read", "GET", "/blogger/v3/blogs/9/posts/8"), bearer="t")
        self.assertEqual(self.sent(env), golden("GET", "/blogger/v3/blogs/9/posts/8?view=ADMIN", "www.googleapis.com", extra=[("Authorization", "Bearer t")]))
        payload = '{"kind": "blogger#post", "title": "가짜 제목"}'.encode("utf-8")
        env, _ = run(self, OK_JSON, "blogger_draft", endpoints.url_for("blogger_draft", "POST", "/blogger/v3/blogs/9/posts"), method="POST", body=payload, bearer="t")
        self.assertEqual(self.sent(env), golden("POST", "/blogger/v3/blogs/9/posts?isDraft=true", "www.googleapis.com",
                                                  extra=[("Content-Type", "application/json; charset=UTF-8"), ("Content-Length", str(len(payload))), ("Authorization", "Bearer t")], body=payload))
        form = b"grant_type=refresh_token&client_id=a&refresh_token=b"
        env, _ = run(self, OK_JSON, "blogger_oauth", "https://oauth2.googleapis.com/token", method="POST", body=form)
        self.assertEqual(self.sent(env), golden("POST", "/token", "oauth2.googleapis.com", extra=[("Content-Type", "application/x-www-form-urlencoded"), ("Content-Length", str(len(form)))], body=form))

    def test_only_the_documented_header_names_are_ever_sent_and_nothing_else_is_added(self):
        allowed = {"Host", "User-Agent", "Accept", "Accept-Encoding", "Connection", "Content-Type", "Content-Length", "Authorization", "Cache-Control"}
        cases = [("update_check", UPDATE_URL, "GET", None, None), ("pages_site", SITE_URL, "GET", None, None), ("blogger_read", BLOG, "GET", None, "t"),
                 ("blogger_draft", BLOG + "/posts?isDraft=true", "POST", b"{}", "t"), ("blogger_oauth", "https://oauth2.googleapis.com/revoke", "POST", b"token=x", None)]
        for use, url, method, body, bearer in cases:
            with self.subTest(use=use):
                env, _ = run(self, OK_JSON, use, url, method=method, body=body, bearer=bearer)
                head = bytes(env.last_socket.sent).split(b"\r\n\r\n")[0].decode("ascii").split("\r\n")
                names = [line.split(":", 1)[0] for line in head[1:]]
                self.assertEqual(len(names), len(set(names)), "같은 머리글이 두 번 나갔다")
                self.assertTrue(set(names) <= allowed, set(names) - allowed)
                for banned in ("Cookie", "Referer", "Origin", "Accept-Language", "DNT", "X-"):
                    self.assertFalse(any(name.startswith(banned) for name in names), banned)
                self.assertEqual(head[0].split(" ")[2], "HTTP/1.1")
                if use != "blogger_read" and use != "blogger_draft":
                    self.assertNotIn("Authorization", names, "접근 토큰은 Blogger API 요청에만 붙는다")

    def test_the_user_agent_is_the_only_place_the_version_goes_and_nothing_else_about_this_pc_is_sent(self):
        import getpass
        import os
        import platform
        env, _ = run(self, OK_JSON)
        wire = bytes(env.last_socket.sent).decode("ascii")
        try:
            user = getpass.getuser()
        except Exception:                                  # noqa: BLE001 - 사용자 이름을 알 수 없는 컨테이너에서도 시험이 돈다
            user = ""
        for secret in {user, os.environ.get("USERNAME", "?"), os.environ.get("COMPUTERNAME", "?"), platform.node(), str(Path.home()), str(Path.cwd()), sys.executable, tempfile.gettempdir()}:
            if len(secret) >= 3:
                self.assertNotIn(secret.lower(), wire.lower())
        self.assertEqual(re.findall(r"User-Agent: (.*)\r\n", wire), ["ChanceBlogDesktop/" + ns.VERSION])

    def test_the_request_goes_out_in_one_header_block_and_the_body_follows_exactly(self):
        payload = b'{"a": 1}'
        env, _ = run(self, OK_JSON, "blogger_draft", BLOG + "/posts?isDraft=true", method="POST", body=payload, bearer="t")
        parts = env.last_socket.send_calls
        self.assertEqual(parts[-1], payload)
        self.assertTrue(parts[0].endswith(b"\r\n\r\n"))


class ShapeRefusalTest(unittest.TestCase):
    def refused(self, label, url=UPDATE_URL, *, use="update_check", method="GET", **kwargs):
        with self.subTest(label=label):
            env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES[use])
            with env, og.Tripwire() as wire:
                with self.assertRaises(errors.NetError) as caught:
                    env.client.request(use, method, url, **kwargs)
            self.assertEqual((caught.exception.code, env.dials, wire.calls, env.usage.records()), ("UNEXPECTED_ERROR", [], [], ()), label)
            self.assertFalse(env.usage.resting(use), "접속 전 거절은 쿨다운 계수에 넣지 않는다")
            self.assertEqual(env.usage._active, set(), "진행 중 표시가 풀려야 한다")
            return caught.exception

    def test_host_port_scheme_userinfo_and_look_alike_names_are_refused_before_connect(self):
        """NT-21 — http 스킴·포트·`@`·숫자 IP·유니코드 닮은 이름·끝의 점·표 밖 호스트는 연결 전에 거절한다."""
        bad = {
            "평문": f"http://{HOST_UPDATE}{UPDATE_PATH}", "포트": f"https://{HOST_UPDATE}:443{UPDATE_PATH}", "다른 포트": f"https://{HOST_UPDATE}:8443{UPDATE_PATH}", "사용자 정보": f"https://user@{HOST_UPDATE}{UPDATE_PATH}",
            "골뱅이 속임": f"https://{HOST_UPDATE}@evil.example.test{UPDATE_PATH}", "하위 도메인": f"https://x.{HOST_UPDATE}{UPDATE_PATH}", "뒤에 붙임": f"https://{HOST_UPDATE}.evil.example.test{UPDATE_PATH}",
            "끝의 점": f"https://{HOST_UPDATE}.{UPDATE_PATH}", "숫자 IP": f"https://140.82.112.3{UPDATE_PATH}", "닮은 글자": f"https://g\u0131thub.com{UPDATE_PATH}", "켈빈 기호": f"https://github.co\u212a{UPDATE_PATH}",
            "조각": f"https://{HOST_UPDATE}{UPDATE_PATH}#x", "상대 주소": UPDATE_PATH, "스킴 없음": f"//{HOST_UPDATE}{UPDATE_PATH}", "다른 호스트": f"https://example.test{UPDATE_PATH}", "역슬래시": f"https://{HOST_UPDATE}\\@evil.example.test{UPDATE_PATH}",
            "빈 글": "", "글이 아님": None, "너무 긺": f"https://{HOST_UPDATE}/" + "a" * 600,
        }
        for label, url in bad.items():
            self.refused(label, url)
        for use, host in (("blogger_read", "oauth2.googleapis.com"), ("blogger_oauth", "www.googleapis.com")):                       # 다른 용도의 호스트도 이 용도에서는 표 밖이다
            self.refused(f"{use} 에 {host}", f"https://{host}/token" if use == "blogger_oauth" else f"https://{host}/blogger/v3/blogs/1", use=use, method="POST" if use == "blogger_oauth" else "GET", body=b"x" if use == "blogger_oauth" else None)
        with ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"]) as env:                                        # 대문자는 같은 호스트다(소문자 표와 견준다)
            self.assertEqual(env.client.request("update_check", "GET", f"https://GITHUB.com{UPDATE_PATH}").status, 200)
        self.assertIn(f"Host: {HOST_UPDATE}\r\n".encode(), bytes(env.last_socket.sent), "보내는 Host 는 늘 표의 글이다")

    def test_path_query_header_and_body_outside_the_shape_are_refused(self):
        """NT-22 — 표 밖의 길·질의 키·방법·머리글·본문 크기."""
        self.refused("다른 길", f"https://{HOST_UPDATE}/own/app/releases/latest/download/../x")
        self.refused("길이 한 구간 모자람", f"https://{HOST_UPDATE}/own/releases/latest/download/a.json")
        self.refused("질의 더함", UPDATE_URL + "?a=1")
        self.refused("POST", method="POST")
        self.refused("본문이 있는 GET", body=b"x")
        self.refused("토큰을 못 붙이는 길", bearer="t")
        self.refused("압축 요청", accept_encoding="gzip")
        self.refused("한도가 표보다 큼", limit=10 ** 9)
        self.refused("한도가 음수", limit=-1)
        self.refused("한도가 불리언", limit=True)
        self.refused("pages_site 질의 없음", f"https://{SITE}/blog/posts.json", use="pages_site")
        self.refused("pages_site 질의 키가 다름", f"https://{SITE}/blog/posts.json?x=app", use="pages_site")
        self.refused("pages_site 질의 값이 다름", f"https://{SITE}/blog/posts.json?cb=other", use="pages_site")
        self.refused("pages_site 질의 값이 길다", f"https://{SITE}/blog/posts.json?cb=app-1234", use="pages_site")
        for ok_value in ("app", "app-1", "app-27"):                                                # 경계 값은 통과한다(vendor 확인 도구는 시도마다 app-<번호> 를 보낸다)
            with ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["pages_site"]) as env:
                self.assertEqual(env.client.request("pages_site", "GET", f"https://{SITE}/blog/posts.json?cb={ok_value}").status, 200, ok_value)
        self.refused("pages_site 질의가 둘", f"https://{SITE}/blog/posts.json?cb=app&cb=app", use="pages_site")
        self.refused("pages_site 점점 구간", f"https://{SITE}/blog/../x?cb=app", use="pages_site")
        self.refused("pages_site 인코딩된 점점", f"https://{SITE}/blog/%2e%2e/x?cb=app", use="pages_site")
        self.refused("pages_site 인코딩된 슬래시", f"https://{SITE}/blog%2fx?cb=app", use="pages_site")
        self.refused("pages_site 널", f"https://{SITE}/blog%00?cb=app", use="pages_site")
        self.refused("pages_site 압축 요청인데 본문을 읽음", SITE_URL, use="pages_site", accept_encoding="gzip")
        self.refused("blogger 번호가 숫자가 아님", "https://www.googleapis.com/blogger/v3/blogs/abc", use="blogger_read")
        self.refused("blogger 번호가 길다", "https://www.googleapis.com/blogger/v3/blogs/" + "1" * 26, use="blogger_read")
        self.refused("blogger fields 질의", BLOG + "?fields=id", use="blogger_read")
        self.refused("blogger 질의 순서가 다름", "https://www.googleapis.com/blogger/v3/blogs/1/posts?orderBy=UPDATED&status=DRAFT&maxResults=5&fetchBodies=false&view=ADMIN", use="blogger_read")
        self.refused("blogger 초안이 아님", "https://www.googleapis.com/blogger/v3/blogs/1/posts?isDraft=false", use="blogger_draft", method="POST", body=b"{}")
        self.refused("blogger 초안 질의 없음", "https://www.googleapis.com/blogger/v3/blogs/1/posts", use="blogger_draft", method="POST", body=b"{}")
        self.refused("blogger 초안 본문 없음", BLOG + "/posts?isDraft=true", use="blogger_draft", method="POST")
        self.refused("blogger 초안 본문이 1 MiB 초과", BLOG + "/posts?isDraft=true", use="blogger_draft", method="POST", body=b"x" * (1024 * 1024 + 1))
        self.refused("blogger 읽기에 POST", BLOG, use="blogger_read", method="POST", body=b"x")
        self.refused("토큰 요청에 접근 토큰", "https://oauth2.googleapis.com/token", use="blogger_oauth", method="POST", body=b"x", bearer="t")
        self.refused("토큰 요청 본문이 4 KiB 초과", "https://oauth2.googleapis.com/token", use="blogger_oauth", method="POST", body=b"x" * 4097)
        self.refused("토큰 길이 초과", BLOG, use="blogger_read", bearer="a" * 4097)
        self.refused("토큰 모양", BLOG, use="blogger_read", bearer="has space")
        for ok_limit in (0, 1024 * 1024):                                                          # 경계 값은 통과한다(대조 — 위 거절들이 빈 실험이 아니다)
            with self.subTest(ok_limit=ok_limit), ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"]) as env:
                self.assertEqual(env.client.request("update_check", "GET", UPDATE_URL, limit=ok_limit).status, 200)

    def test_the_draft_route_is_draft_only_and_no_other_blogger_shape_is_reachable(self):
        """R-3(독립 검증 Q) — 초안 길은 `POST /blogger/v3/blogs/<번호>/posts?isDraft=true` 하나뿐이다. 글 하나·공개(`publish`)·되돌리기(`revert`)·다른 질의·다른 방법(PUT·PATCH·DELETE)·다른 길은 접속 전에 거절한다.
        '초안만' 이라는 약속의 길 핀 — 표의 길 글을 넓혀도(변이 Q64) 이 거절들이 빨개진다."""
        base = "https://www.googleapis.com/blogger/v3/blogs/1"
        draft = dict(use="blogger_draft", body=b"{}", bearer="t")
        shapes = (("글 하나에 POST", base + "/posts/2?isDraft=true", "POST"), ("글 하나에 POST(질의 없음)", base + "/posts/2", "POST"), ("공개하기", base + "/posts/2/publish", "POST"),
                  ("공개하기(초안 질의)", base + "/posts/2/publish?isDraft=true", "POST"), ("되돌리기", base + "/posts/2/revert", "POST"), ("초안 값 대문자", base + "/posts?isDraft=True", "POST"),
                  ("초안 값이 빔", base + "/posts?isDraft=", "POST"), ("질의가 더 있음", base + "/posts?isDraft=true&publish=true", "POST"), ("질의가 두 번", base + "/posts?isDraft=true&isDraft=true", "POST"),
                  ("PUT", base + "/posts/2?isDraft=true", "PUT"), ("PATCH", base + "/posts/2?isDraft=true", "PATCH"), ("DELETE", base + "/posts/2", "DELETE"), ("GET", base + "/posts?isDraft=true", "GET"),
                  ("페이지 길", base + "/pages?isDraft=true", "POST"), ("블로그 목록 길", "https://www.googleapis.com/blogger/v3/users/self/blogs", "POST"),
                  ("번호가 숫자가 아님", "https://www.googleapis.com/blogger/v3/blogs/abc/posts?isDraft=true", "POST"), ("끝에 슬래시", base + "/posts/?isDraft=true", "POST"))
        for label, url, method in shapes:
            self.refused(label, url, method=method, **draft)
        for label, url, method in (("읽기 용도에 공개하기", base + "/posts/2/publish", "POST"), ("읽기 용도에 DELETE", base + "/posts/2", "DELETE"), ("읽기 용도에 PUT", base + "/posts/2", "PUT")):
            self.refused(label, url, use="blogger_read", method=method, body=b"{}", bearer="t")
        with ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["blogger_draft"]) as env:                                            # 대조 — 초안 길 하나는 통과한다(위 거절들이 빈 실험이 아니다)
            self.assertEqual(env.client.request("blogger_draft", "POST", base + "/posts?isDraft=true", body=b"{}", bearer="t").status, 200)

    def test_the_revoke_route_has_its_own_body_limit_and_form_content_type(self):
        """R-3 — `/token` 만이 아니라 `/revoke` 도 본문 4 KiB 가 상한이고(정확히는 통과, 한 바이트 넘으면 접속 전 거절) 본문 종류가 양식 인코딩이다."""
        for route in ("/token", "/revoke"):
            url = "https://oauth2.googleapis.com" + route
            with self.subTest(route=route):
                self.refused(f"{route} 본문 4 KiB 초과", url, use="blogger_oauth", method="POST", body=b"x" * 4097)
                env, _ = run(self, OK_JSON, "blogger_oauth", url, method="POST", body=b"x" * 4096)
                sent = bytes(env.last_socket.sent)
                self.assertIn(b"Content-Type: application/x-www-form-urlencoded\r\n", sent)
                self.assertIn(b"Content-Length: 4096\r\n", sent)
                self.assertEqual(sent.count(b"Content-Type:"), 1)

    def test_the_update_check_route_takes_no_dot_segments_and_no_hidden_names(self):
        """G-2(독립 검증 Q·S 권고-2) — 자리표시자 길도 `.`·`..`·점으로 시작하는 구간은 받지 않는다(공개 사이트 길이 `..` 를 막는 것과 같다). 소유자·저장소 고정은 UPDATE 갈래가 확정할 때 한다."""
        for label, url in (("점점 소유자", f"https://{HOST_UPDATE}/../app/releases/latest/download/x.exe"), ("점 저장소", f"https://{HOST_UPDATE}/own/./releases/latest/download/x.exe"),
                           ("점점 둘", f"https://{HOST_UPDATE}/../../releases/latest/download/x"), ("점점 자산", f"https://{HOST_UPDATE}/own/app/releases/latest/download/.."),
                           ("점 자산", f"https://{HOST_UPDATE}/own/app/releases/latest/download/."), ("숨은 자산", f"https://{HOST_UPDATE}/own/app/releases/latest/download/.hidden"),
                           ("숨은 소유자", f"https://{HOST_UPDATE}/.own/app/releases/latest/download/x"), ("인코딩된 점점", f"https://{HOST_UPDATE}/own/app/releases/latest/download/%2e%2e"),
                           ("구간 길이 100 초과", f"https://{HOST_UPDATE}/" + "a" * 101 + "/app/releases/latest/download/x")):
            self.refused(label, url)
        for ok in ("own/app/releases/latest/download/update-manifest.json", "O_w-n.x/a.b-c_d/releases/latest/download/App-1.2.3.exe", "a/b/releases/latest/download/" + "z" * 100):
            with self.subTest(ok=ok), ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"]) as env:
                self.assertEqual(env.client.request("update_check", "GET", f"https://{HOST_UPDATE}/{ok}").status, 200)

    def test_the_public_site_route_refuses_a_leading_double_slash_but_keeps_the_vendor_tool_shapes(self):
        """N-4(독립 검증 Q) — 공개 사이트 길의 맨 앞 `//` 는 거절한다(요청 줄이 `//호스트/...` 모양이 되는 길). vendor 확인 도구의 `//` 는 구간 사이·끝에만 쓰이므로 그 모양은 그대로 통과한다."""
        self.refused("맨 앞 //", f"https://{SITE}//evil.example.test/x?cb=app", use="pages_site")
        self.refused("맨 앞 // 만", f"https://{SITE}//?cb=app", use="pages_site")
        for path in ("/blog/a//b/?cb=app", "/blog//a/b?cb=app", "/blog/a/b//?cb=app", "/blog/./a/b/?cb=app", "/?cb=app", "/blog/posts.json?cb=app-3"):
            with self.subTest(path=path), ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["pages_site"]) as env:
                self.assertEqual(env.client.request("pages_site", "GET", f"https://{SITE}{path}").status, 200, path)

    def test_header_and_crlf_injection_is_refused(self):
        """NT-23 — 줄바꿈·널이 든 값은 접속 전에 거절한다(`http.client` 의 검사와 이중)."""
        self.refused("주소의 CRLF", f"https://{HOST_UPDATE}{UPDATE_PATH}\r\nX-Evil: 1")
        self.refused("주소의 LF", f"https://{HOST_UPDATE}{UPDATE_PATH}\nX-Evil: 1")
        self.refused("주소의 널", f"https://{HOST_UPDATE}{UPDATE_PATH}\x00")
        self.refused("주소의 공백", f"https://{HOST_UPDATE}{UPDATE_PATH} HTTP/1.0")
        self.refused("토큰의 CRLF", BLOG, use="blogger_read", bearer="abc\r\nX-Evil: 1")
        self.refused("토큰의 널", BLOG, use="blogger_read", bearer="abc\x00")
        self.refused("pages_site 의 CRLF", f"https://{SITE}/blog\r\nX: 1?cb=app", use="pages_site")
        conn = http.client.HTTPSConnection("example.test")
        conn.putrequest("GET", "/ok")
        with self.assertRaises(ValueError):
            conn.putheader("X-Test", "a\r\nX-Evil: 1")                 # 두 번째 겹 — 표준 라이브러리 자신의 검사
        with self.assertRaises((ValueError, http.client.InvalidURL)):
            http.client.HTTPSConnection("example.test").putrequest("GET", "/a\r\nX: 1")

    def test_a_refused_shape_never_counts_as_a_failure_and_never_leaves_an_active_marker(self):
        env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"])
        with env:
            for _ in range(6):
                with self.assertRaises(errors.NetError):
                    env.client.request("update_check", "GET", "http://github.com/x")
            self.assertEqual(env.client.request("update_check", "GET", UPDATE_URL).status, 200, "모양 거절이 여섯 번이어도 쉬지 않는다")


class RedirectTest(unittest.TestCase):
    def redirect(self, location, status=302):
        return ns.http_response(status, "Found", headers=[("Location", location)])

    def test_redirects_are_refused_by_default_and_the_second_request_is_never_made(self):
        """NT-24 — 기본은 거절(업데이트 확인·Blogger 읽기 표는 이동 0): 전송 시도는 한 번뿐이다. 이동 주소가 표에 맞는 같은 호스트의 올바른 주소여도 따라가지 않는다 —
        기본값이 0 이라는 것을 직접 못박는다(표 밖 주소만 시험하면 기본값이 3 으로 바뀌어도 표 검사 때문에 거절돼 못 알아챈다 — 변이 M-NET-10 의 첫 실행이 이 틈을 드러내 시험을 강화했다)."""
        cases = (("update_check", UPDATE_URL, {}, f"https://{HOST_UPDATE}/elsewhere"),
                 ("update_check", UPDATE_URL, {}, f"https://{HOST_UPDATE}/own/app/releases/latest/download/other.json"),
                 ("blogger_read", BLOG, {"bearer": "t"}, BLOG + "/posts/1?view=ADMIN"))
        for status in (301, 302, 303, 307, 308):
            for use, url, extra, location in cases:
                with self.subTest(status=status, use=use, location=location):
                    sockets = [ns.FakeSocket(self.redirect(location, status)), ns.FakeSocket(OK_JSON)]
                    env, error = raised(self, b"", use, "GET", url, harness=ns.Harness(self, sockets=sockets, switches=ns.USE_SWITCHES[use]), **extra)
                    self.assertEqual(error.code, "NET_RESPONSE_INVALID")
                    self.assertIn(errors.REASON_REDIRECT, error.rendered().message)
                    self.assertEqual(len(env.dials), 1, "두 번째 요청은 만들어지지 않는다")

    def test_pages_site_follows_same_host_redirects_up_to_two_and_checks_each_step(self):
        site = lambda path: f"https://{SITE}{path}?cb=app"        # noqa: E731
        final = ns.http_response(200, body=b"[]")
        sockets = [ns.FakeSocket(self.redirect("/a/b?cb=app")), ns.FakeSocket(self.redirect(site("/c"), 301)), ns.FakeSocket(final)]
        env, response = run(self, b"", "pages_site", SITE_URL, harness=ns.Harness(self, sockets=sockets, switches=ns.USE_SWITCHES["pages_site"]))
        self.assertEqual((response.status, response.body, len(env.dials)), (200, b"[]", 3))
        env.last_socket                                              # 마지막 연결도 같은 호스트다
        self.assertTrue(all(host == SITE for host, _address in env.dials))
        sockets = [ns.FakeSocket(self.redirect("/1?cb=app")), ns.FakeSocket(self.redirect("/2?cb=app")), ns.FakeSocket(self.redirect("/3?cb=app")), ns.FakeSocket(final)]
        env, error = raised(self, b"", "pages_site", "GET", SITE_URL, harness=ns.Harness(self, sockets=sockets, switches=ns.USE_SWITCHES["pages_site"]))
        self.assertEqual((error.code, len(env.dials)), ("NET_RESPONSE_INVALID", 3), "이동은 최대 두 번 — 세 번째 이동은 거절")

    def test_redirects_to_other_hosts_plain_http_userinfo_ports_loops_and_bad_shapes_are_refused(self):
        bad = {"다른 호스트": "https://evil.example.test/x?cb=app", "평문": f"http://{SITE}/x?cb=app", "사용자 정보": f"https://u@{SITE}/x?cb=app", "포트": f"https://{SITE}:444/x?cb=app",
               "질의 없음": "/x", "표 밖 길": "/a/%2e%2e/b?cb=app", "자기 자신": SITE_URL, "공백": "/x y?cb=app", "닮은 이름": f"https://{SITE}.evil.example.test/x?cb=app",
               "스킴만 같음": "//evil.example.test/x?cb=app", "아주 긴 주소": "/" + "a" * 2500 + "?cb=app", "비 ASCII": "/\ud55c?cb=app"}
        for label, location in bad.items():
            with self.subTest(label=label):
                try:
                    location.encode("latin-1")
                except UnicodeEncodeError:
                    continue                                          # 헤더 줄에 실을 수 없는 글은 가짜 서버도 보낼 수 없다
                env, error = raised(self, self.redirect(location), "pages_site", "GET", SITE_URL, switches=ns.USE_SWITCHES["pages_site"])
                self.assertEqual(error.code, "NET_RESPONSE_INVALID", label)
                self.assertEqual(len(env.dials), 1, label)

    def test_a_redirect_without_exactly_one_location_is_refused_and_a_post_never_follows(self):
        env, error = raised(self, ns.http_response(302, "Found"), "pages_site", "GET", SITE_URL, switches=ns.USE_SWITCHES["pages_site"])
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        two = ns.http_response(302, "Found", headers=[("Location", "/a?cb=app"), ("Location", "/b?cb=app")])
        env, error = raised(self, two, "pages_site", "GET", SITE_URL, switches=ns.USE_SWITCHES["pages_site"])
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        env, error = raised(self, self.redirect("/token"), "blogger_oauth", "POST", "https://oauth2.googleapis.com/token", body=b"x")
        self.assertEqual((error.code, len(env.dials)), ("NET_RESPONSE_INVALID", 1))

    def test_a_listed_other_host_is_followed_without_the_token_and_an_unlisted_one_is_not(self):
        base = endpoints.ENDPOINTS["blogger_read"]
        table = dict(endpoints.ENDPOINTS, blogger_read=dataclasses.replace(base, max_redirects=2, redirect_hosts=("cdn.example.net",)))
        first = self.redirect("https://cdn.example.net/f/x?sig=ab-1&e=2")
        final = ns.http_response(200, body=b"{}")
        sockets = [ns.FakeSocket(first), ns.FakeSocket(final)]
        env = ns.Harness(self, sockets=sockets, switches=ns.USE_SWITCHES["blogger_read"])
        with mock.patch.object(client, "ENDPOINTS", table):
            _env, response = run(self, b"", "blogger_read", BLOG, harness=env, bearer="SECRETTOKEN")
        self.assertEqual((response.status, response.host, [host for host, _ in env.dials]), (200, "cdn.example.net", ["www.googleapis.com", "cdn.example.net"]))
        second = bytes(sockets[1].sent).decode("ascii")
        self.assertNotIn("SECRETTOKEN", second, "다른 호스트로는 토큰을 보내지 않는다")
        self.assertIn("Host: cdn.example.net\r\n", second)
        self.assertIn("SECRETTOKEN", bytes(sockets[0].sent).decode("ascii"))
        for location in ("https://other.example.net/f", "https://cdn.example.net/f?x=<script>", "https://cdn.example.net:8443/f", "http://cdn.example.net/f",
                         "https://cdn.example.net/f/x<y"):          # 마지막: 길 끝에 나쁜 글자가 붙은 주소(Q 재검증 참고-2 — 길 검사가 앞부분 일치로 느슨해져도 초록이던 틈, 변이 Z15)
            with self.subTest(location=location), mock.patch.object(client, "ENDPOINTS", table):
                env, error = raised(self, self.redirect(location), "blogger_read", "GET", BLOG, bearer="t", switches=ns.USE_SWITCHES["blogger_read"])
                self.assertEqual((error.code, len(env.dials)), ("NET_RESPONSE_INVALID", 1))

    def test_a_post_is_never_redirected_even_when_the_table_allows_redirects_for_its_use(self):
        """G-5(c)·S 권고-3(d) — 지금 표에는 POST 를 이동시키는 용도가 없어 `hops >= max_redirects(0)` 가 먼저 막아 주는 이중 방어라 '쓰기는 따라가지 않는다' 줄이 시험 없이 남았다(변이 Q16·X03).
        표를 바꿔 — 같은 호스트에 POST 길과 GET 길이 둘 다 있고 이동 2번을 허용하는 합성 용도 — POST 가 302 를 받아도 둘째 연결이 0 임을 직접 시험한다(대조: 같은 표에서 GET 은 같은 호스트 이동을 따라간다)."""
        base = endpoints.ENDPOINTS["blogger_oauth"]
        routes = (base.routes[0], endpoints.Route("GET", "/token", "/token"), endpoints.Route("GET", "/other", "/other"))
        table = dict(endpoints.ENDPOINTS, blogger_oauth=dataclasses.replace(base, max_redirects=2, routes=routes))
        sockets = [ns.FakeSocket(self.redirect("https://oauth2.googleapis.com/other")), ns.FakeSocket(OK_JSON)]
        env = ns.Harness(self, sockets=sockets, switches=ns.USE_SWITCHES["blogger_oauth"])
        with mock.patch.object(client, "ENDPOINTS", table), env, self.assertRaises(errors.NetError) as caught:
            env.client.request("blogger_oauth", "POST", "https://oauth2.googleapis.com/token", body=b"x=1")
        self.assertEqual((caught.exception.code, len(env.dials), sockets[1].reads), ("NET_RESPONSE_INVALID", 1, 0), "POST 가 이동을 받아도 둘째 연결은 없다")
        sockets = [ns.FakeSocket(self.redirect("https://oauth2.googleapis.com/other")), ns.FakeSocket(OK_JSON)]
        env = ns.Harness(self, sockets=sockets, switches=ns.USE_SWITCHES["blogger_oauth"])
        with mock.patch.object(client, "ENDPOINTS", table), env:
            response = env.client.request("blogger_oauth", "GET", "https://oauth2.googleapis.com/token")
        self.assertEqual((response.status, len(env.dials)), (200, 2), "대조 — 같은 표에서 GET 은 같은 호스트 이동을 따라간다(위 거절이 빈 실험이 아니다)")


    UNPARSABLE_LOCATIONS = ("//[x", "https://[x]/p?cb=app", "https://exa]mple/", "https://[::1/blog/x", "//[", "//]", "https://[/", "https://]/", "https://[]/", "https://[::g]/", "//a]b", "https://a[b]c/", "//[x]",
                            "https://[1:2:3:4:5:6:7:8:9]/x")

    def test_a_location_that_urljoin_cannot_read_is_a_bad_answer_not_a_raw_value_error(self):
        """S 재검증 권고-1 — 서버가 준 `Location` 이 `//[x`·`https://[x]/p` 꼴이면 `urljoin` 이 `ValueError` 를 올리는데(파이썬 3.10·3.12 둘 다, 3.12 는 서버가 보낸 글이 예외 문장에 실린다) 그것이 `try` 밖이라
        `NetError` 가 아닌 원시 예외가 새어 나갔다(T-06·T-17 '서버 글은 오류 문장에 안 실린다' 위반). 이제 고정 문구의 `NET_RESPONSE_INVALID`(이유: 이동)이고 연결은 한 번뿐이며 어디에도 `Location` 글(카나리)이 없다."""
        import traceback
        canary = ns.CANARY
        shapes = self.UNPARSABLE_LOCATIONS + (f"https://[{canary}]/p", f"//[{canary}", f"https://{canary}]/p")
        for location in shapes:
            with self.subTest(location=location.replace(canary, "CANARY")):
                env, error = raised(self, self.redirect(location), "pages_site", "GET", SITE_URL, switches=ns.USE_SWITCHES["pages_site"])
                self.assertEqual((error.code, len(env.dials)), ("NET_RESPONSE_INVALID", 1), "이동 주소를 못 읽었다 — 틀린 답이고 둘째 연결은 없다")
                self.assertEqual(error.detail, "pages_site:redirect")
                self.assertIn(errors.REASON_REDIRECT, error.rendered().message)
                shown = [str(error), repr(error.args), error.detail, error.log_line(), error.rendered().message, error.rendered().action, repr(error.slots), "".join(traceback.format_exception(type(error), error, error.__traceback__))]
                for text in shown:
                    self.assertNotIn(canary, text, "서버가 보낸 글이 오류 문장에 실렸다")
                self.assertIsNone(error.__context__)
                self.assertEqual(env.usage.records()[0].error, "NET_RESPONSE_INVALID")

    def test_the_conversion_of_a_urljoin_failure_carries_nothing_of_the_original_exception(self):
        """권고-1 의 고정 문구 약속을 파이썬 버전과 상관없이 못박는다 — 합성: `urljoin` 이 서버 글이 든 문장으로 `ValueError` 를 올려도(3.12 가 실제로 그렇다) 판정 함수의 오류는 고정 문구뿐이고
        원래 예외는 원인도 표시할 맥락도 아니다(`from None`). 요청 전체를 거치면 바깥 `_run` 이 `__context__` 를 한 번 더 지우므로 판정 함수를 직접 부른다."""
        import traceback
        endpoint = endpoints.ENDPOINTS["pages_site"]
        canary = ns.CANARY
        with mock.patch.object(client, "urljoin", side_effect=ValueError(f"{canary} does not appear to be an IPv4 or IPv6 address")):
            with self.assertRaises(errors.NetError) as caught:
                client._redirect_url(endpoint, SITE_URL, "/x?cb=app", 0)
        error = caught.exception
        self.assertEqual((error.code, error.detail, error.use, error.outcome_unknown), ("NET_RESPONSE_INVALID", "pages_site:redirect", "pages_site", False))
        self.assertIn(errors.REASON_REDIRECT, error.rendered().message)
        self.assertIsNone(error.__cause__)
        self.assertTrue(error.__suppress_context__, "원래 예외를 표시할 맥락으로 남기지 않는다(`from None`)")
        for text in (str(error), repr(error.args), error.detail, error.log_line(), error.rendered().message, error.rendered().action, repr(error.slots), "".join(traceback.format_exception(type(error), error, error.__traceback__))):
            self.assertNotIn(canary, text)

    def test_the_redirect_judgement_raises_nothing_but_net_error_for_any_ascii_location(self):
        """같은 약속의 일반형 — `Location` 으로 올 수 있는 아무 ASCII 글(대괄호·콜론·`@`·`#`·`%` 를 섞은 짧은 글 3000개와 여러 스킴 머리)을 판정 함수에 넣어도 주소 글을 돌려주거나 `NetError` 를 올릴 뿐
        다른 예외가 새지 않는다(`urljoin` 이 `ValueError` 를 내는 모양을 하나하나 적지 않아도 되게). 시험 입력은 고정된 씨앗으로 만든다."""
        import random
        import urllib.parse
        endpoint = endpoints.ENDPOINTS["pages_site"]
        current = f"https://{SITE}/blog/posts.json?cb=app"
        rng = random.Random(20261125)
        alphabet = "[]:/@?#%.a1x-_=&"
        heads = ("", "//", "https://", "http://", "/", "./", "../", "file://", "https:", "//[", "https://[", "https://a]")
        passed = refused = 0
        for _ in range(3000):
            location = rng.choice(heads) + "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 10)))
            try:
                target = client._redirect_url(endpoint, current, location, 0)
            except errors.NetError as error:
                self.assertEqual(error.code, "NET_RESPONSE_INVALID", location)
                refused += 1
                continue
            except Exception as error:                                    # noqa: BLE001 - 어떤 모양에서든 다른 예외가 새면 그 입력을 알려 준다
                self.fail(f"{location!r}: NetError 가 아닌 {type(error).__name__} 이 새어 나왔다")
            passed += 1
            self.assertEqual(urllib.parse.urlsplit(target).scheme, "https", location)
        self.assertGreater(passed, 0, "표에 맞는 주소도 통과한다(대조 — 위 거절들이 모든 입력을 막는 빈 실험이 아니다)")
        self.assertGreater(refused, 0)
        self.assertEqual(client._redirect_url(endpoint, current, "/blog/other.json?cb=app", 0), f"https://{SITE}/blog/other.json?cb=app")


class ResponseLimitsTest(unittest.TestCase):
    def test_response_size_limit_by_content_length_and_by_stream(self):
        """NT-25 — 선언 크기와 실제 크기 모두. 정확히 한도는 통과, 한 바이트 넘으면 거절."""
        limit = 1024
        env, response = run(self, ns.http_response(200, body=b"x" * limit), limit=limit)
        self.assertEqual(len(response.body), limit)
        env, error = raised(self, ns.http_response(200, body=b"x" * (limit + 1)), limit=limit)
        self.assertEqual((error.code, error.outcome_unknown), ("NET_RESPONSE_INVALID", True))
        self.assertIn(errors.REASON_TOO_LARGE, error.rendered().message)
        env, error = raised(self, ns.http_response(200, length=False, body=b"x" * (limit + 50)), limit=limit)              # 길이 없이 연결을 닫아 끝내는 응답
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        env, error = raised(self, ns.http_response(200, chunked=True, body=b"x" * (limit + 50)), limit=limit)             # 덩어리 응답
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        env, error = raised(self, ns.http_response(200, headers=[("Content-Length", "999999999999")], length=False, body=b""), limit=limit)
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        for value in ("-5", "1e3", "0x10", " ", "1" * 20, "+5", "5.0"):
            with self.subTest(content_length=value):
                env, error = raised(self, ns.http_response(200, headers=[("Content-Length", value)], length=False, body=b"abc"), limit=limit)
                self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        env, response = run(self, ns.http_response(200, chunked=True, body=b"y" * 777), limit=limit)
        self.assertEqual(response.body, b"y" * 777)

    def test_the_read_limit_a_caller_may_ask_for_is_exactly_the_table_maximum(self):
        """Q 재검증 참고-1(변이 Z22 — `limit > cap` 이 `> cap + 1` 이 돼도 초록이던 틈) — 호출하는 쪽이 부탁하는 읽기 상한은 표의 최대 응답 크기까지다: 정확히 최대는 되고 한 바이트라도 넘으면 접속 전에 프로그램 오류로 거절한다."""
        cap = endpoints.ENDPOINTS["update_check"].max_response
        env, response = run(self, ns.http_response(200, body=b"ok"), limit=cap)
        self.assertEqual(response.body, b"ok")
        for limit in (cap + 1, cap + 2):
            with self.subTest(limit=limit):
                env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"])
                with env, og.Tripwire() as wire, self.assertRaises(errors.NetError) as caught:
                    env.client.request("update_check", "GET", UPDATE_URL, limit=limit)
                self.assertEqual((caught.exception.code, caught.exception.detail, env.dials, wire.calls), ("UNEXPECTED_ERROR", "update_check:limit", [], []))

    def test_a_short_body_and_two_content_lengths_are_refused_and_status_only_reads_no_body(self):
        env, error = raised(self, b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nabc")
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        self.assertIn(errors.REASON_LENGTH, error.rendered().message)
        two = b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Length: 3\r\n\r\nabc"
        env, error = raised(self, two)
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        env, response = run(self, ns.http_response(200, body=b"z" * 5000), limit=0)
        self.assertEqual((response.status, response.body), (200, b""), "상태만 볼 때 본문을 읽지 않는다(돌려주는 본문이 없다)")

    def test_too_many_or_too_big_headers_are_refused(self):
        many = ns.http_response(200, headers=[(f"X-H{i}", "v") for i in range(120)], body=b"{}")
        env, error = raised(self, many)
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        big = ns.http_response(200, headers=[(f"X-B{i}", "v" * 8000) for i in range(10)], body=b"{}")
        env, error = raised(self, big)
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        env, error = raised(self, b"HTTP/1.1 200 OK\r\nX-Long: " + b"a" * 70000 + b"\r\n\r\n")
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")

    def test_content_encoding_other_than_identity_is_refused(self):
        """NT-26 — 압축된 응답은 거절한다(압축 폭탄). 본문을 읽지 않는 상태 확인(`limit=0`)만 `Accept-Encoding: gzip` 을 허용한다."""
        for value in ("gzip", "deflate", "br", "GZIP", "identity, gzip"):
            with self.subTest(value=value):
                env, error = raised(self, ns.http_response(200, headers=[("Content-Encoding", value)], body=b"{}"))
                self.assertEqual(error.code, "NET_RESPONSE_INVALID")
                self.assertIn(errors.REASON_ENCODING, error.rendered().message)
        for value in ("identity", "Identity", ""):
            with self.subTest(ok=value):
                env, response = run(self, ns.http_response(200, headers=[("Content-Encoding", value)], body=b"{}"))
                self.assertEqual(response.body, b"{}")
        env, response = run(self, ns.http_response(200, headers=[("Content-Encoding", "gzip")], body=b"\x1f\x8b" * 100), "pages_site", SITE_URL.replace("posts.json", "x"), accept_encoding="gzip", limit=0)
        self.assertEqual((response.status, response.body), (200, b""))
        self.assertIn(b"Accept-Encoding: gzip\r\n", bytes(env.last_socket.sent))


def pieces_of(framing, close, body, *, piece=4000, extra=()):
    """응답 바이트를 `[머리글, 본문 조각 …]` 으로 — 가짜 소켓이 조각마다 읽기 한 번씩 돌려준다(진짜 보안 연결이 레코드 하나씩 돌려주는 모양). `framing`: length·chunked·none."""
    lines = ["HTTP/1.1 200 OK", "Content-Type: application/json"] + list(extra)
    if framing == "length":
        lines.append(f"Content-Length: {len(body)}")
    elif framing == "chunked":
        lines.append("Transfer-Encoding: chunked")
    if close:
        lines.append("Connection: close")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    if framing == "chunked":
        parts = [f"{len(body[i:i + piece]):x}\r\n".encode() + body[i:i + piece] + b"\r\n" for i in range(0, len(body), piece)] + [b"0\r\n\r\n"]
    else:
        parts = [body[i:i + 16384] for i in range(0, len(body), 16384)]
    return [head] + parts


class ConnectionCloseTest(unittest.TestCase):
    """`http.client` 는 응답이 `Connection: close` 이거나 길이가 없으면 본문을 읽기 **전에** 소켓의 `close()` 를 부른다 — 그 뒤에도 본문은 끝까지 읽혀야 하고, 요청이 끝나면 연결은 진짜로 닫혀야 한다(D-738, 독립 검증 Q-R1).
    진짜 TLS 시험(`test_net_tls.ResponseShapeTest`)은 윈도 3.12 에서만 도는 것으로 측정했으므로, 같은 결함을 **가짜 소켓**(닫은 뒤에 읽으면 진짜처럼 실패한다 — `net_support.FakeSocket`)으로도 지킨다."""

    BODY = b"0123456789abcdef" * 7000                           # 112,000 바이트 — 읽기 버퍼(8 KiB)보다 훨씬 크다

    def fetch(self, framing, close, size, **options):
        body = self.BODY[:size]
        sock = ns.FakeSocket(pieces=pieces_of(framing, close, body))
        env = ns.Harness(self, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
        with env, og.Tripwire() as wire:
            try:
                result = env.client.request("update_check", "GET", UPDATE_URL, **options)
            except errors.NetError as error:
                result = error
        self.assertEqual(wire.calls, [])
        return env, sock, body, result

    def test_a_response_that_asks_to_close_is_read_whole_after_http_client_closes_its_end(self):
        for framing in ("length", "chunked", "none"):
            for close in (True, False):
                for size in (12, 9000, 112_000):
                    with self.subTest(framing=framing, close=close, size=size):
                        env, sock, body, result = self.fetch(framing, close, size)
                        self.assertIsInstance(result, client.NetResponse, f"{getattr(result, 'code', '')} {getattr(result, 'detail', '')}")
                        self.assertEqual((result.status, result.body), (200, body))
                        self.assertTrue(sock.closed, "끝났으니 연결은 진짜로 닫혀 있다")
                        self.assertEqual(env.usage.records()[0].error, "")

    def test_every_way_a_request_can_end_closes_the_connection_for_real(self):
        """성공·2xx 아닌 답·너무 큼·짧음·압축·이동·시간 초과·읽기 오류 — 어떻게 끝나든 진짜 소켓은 닫힌다(읽개가 열려 있다고 새지 않는다)."""
        big = self.BODY[:30_000]
        cases = {
            "성공": (ns.FakeSocket(pieces=pieces_of("length", True, big)), {}),
            "404": (ns.FakeSocket(pieces=[b"HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 20000\r\n\r\n", big[:20000]]), {}),
            "너무 큼": (ns.FakeSocket(pieces=pieces_of("length", True, big)), {"limit": 1000}),
            "길이 없이 너무 큼": (ns.FakeSocket(pieces=pieces_of("none", True, big)), {"limit": 1000}),
            "짧게 끊김": (ns.FakeSocket(pieces=[b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 30000\r\n\r\n", big[:9000]]), {}),
            "압축됨": (ns.FakeSocket(pieces=pieces_of("length", True, big, extra=["Content-Encoding: gzip"])), {}),
            "이동": (ns.FakeSocket(pieces=[b"HTTP/1.1 302 Found\r\nLocation: https://github.com/a/b\r\nConnection: close\r\nContent-Length: 20000\r\n\r\n", big[:20000]]), {}),
            "읽기 오류": (ns.FakeSocket(pieces=[b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 30000\r\n\r\n"], read_error=OSError("reset")), {}),
        }
        for label, (sock, options) in cases.items():
            with self.subTest(label=label):
                env = ns.Harness(self, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
                kept = None
                with env, og.Tripwire() as wire:
                    try:
                        env.client.request("update_check", "GET", UPDATE_URL, **options)
                    except errors.NetError as error:
                        kept = error              # 오류를 붙들고 있으면 역추적이 `_once` 의 지역 변수(응답·소켓)를 붙들어 둔다 — 요청이 스스로 닫지 않으면 이 시점에 열려 있다(가비지 수집이 닫아 주는 것에 기대지 않는다)
                self.assertEqual((wire.calls, sock.closed), ([], True), label)
                del kept

    def test_the_connection_is_closed_for_real_even_when_closing_the_response_fails(self):
        """마지막 안전장치 — 응답을 닫다가 실패해도(읽개가 열린 채 남아도) 요청이 끝나면 `abort()` 가 진짜 소켓을 닫는다. 응답을 붙들어 가비지 수집이 대신 닫아 주지 못하게 한 채 본다
        (예전에는 응답 닫기만으로 충분한지 시험이 가려내지 못했다 — 변이 R2-04)."""
        kept = []

        def failing_close(response):
            kept.append(response)                                       # 응답 객체를 붙들어 두면 읽개도 열린 채 남는다
            raise RuntimeError("닫다가 실패")
        sock = ns.FakeSocket(pieces=pieces_of("length", True, self.BODY[:30_000]))
        env = ns.Harness(self, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
        with env, mock.patch.object(http.client.HTTPResponse, "close", failing_close), self.assertRaises(errors.NetError) as caught:
            env.client.request("update_check", "GET", UPDATE_URL, limit=1000)          # 선언 크기가 한도보다 커서 본문을 읽지 않고 거절 — 읽개가 열린 채 끝난다
        self.assertEqual(caught.exception.code, "NET_RESPONSE_INVALID")
        self.assertTrue(kept, "응답 닫기가 불렸다")
        self.assertTrue(sock.closed, "응답을 닫는 데 실패해도 요청이 끝나면 진짜 소켓은 닫힌다")

    def test_a_dripping_body_with_connection_close_still_stops_at_the_total_deadline(self):
        """응답에 `Connection: close` 가 있어도 찔끔 오는 본문은 마감에서 끊긴다 — 닫힌 소켓 오류(`NETWORK_OFFLINE`)가 아니라 마감 초과(`NETWORK_TIMEOUT`)다."""
        clock = ns.FakeClock()
        head = b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 100000\r\n\r\n"
        sock = ns.FakeSocket(pieces=[head] + [b"x"] * 100_000, clock=clock)
        calls = {"n": 0}
        original = sock.recv_into

        def drip(buffer):
            calls["n"] += 1
            if calls["n"] > 1:
                sock.delay = 9.0
            return original(buffer)
        sock.recv_into = drip
        env = ns.Harness(self, clock=clock, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
        with env, self.assertRaises(errors.NetError) as caught:
            env.client.request("update_check", "GET", UPDATE_URL)
        self.assertEqual((caught.exception.code, caught.exception.outcome_unknown), ("NETWORK_TIMEOUT", True), caught.exception.detail)
        self.assertLessEqual(clock.now - 1000.0, endpoints.TOTAL_TIMEOUT + 0.001)
        self.assertTrue(sock.closed)

    def test_a_fake_socket_that_is_closed_fails_like_a_real_one(self):
        """시험 도우미의 약속 — 닫은 소켓을 읽거나 쓰면 실패한다(그래야 위 시험들이 '닫은 뒤 읽기' 결함을 잡는다)."""
        sock = ns.FakeSocket(b"abc")
        sock.close()
        with self.assertRaises(OSError):
            sock.recv_into(bytearray(3))
        with self.assertRaises(OSError):
            sock.sendall(b"x")
        lenient = ns.FakeSocket(b"abc", strict=False)
        lenient.close()
        self.assertEqual(lenient.recv_into(bytearray(3)), 3)


class WireCapTest(unittest.TestCase):
    """받는 바이트 **전체**의 상한(D-738, 독립 검증 S 권고-1). 본문은 누적 크기로 막았지만 머리글·덩어리 틀·끝 머리글(트레일러)·`100 Continue` 구간은 총 시간(30초)에만 묶여 있어,
    루프백에서 3초 동안 약 164 MiB 를 읽고서야 끝났다(본문 상한은 1 MiB). 이제 읽은 바이트의 합이 `본문 상한 x 2 + 머리글 몫 두 번` 을 넘으면 `NET_RESPONSE_INVALID`(너무 큼)로 끊는다."""

    @staticmethod
    def flood(head, repeat):
        def stream():
            yield head
            block = repeat * max(1, 65536 // len(repeat))                 # 되풀이하는 글을 통째로 몇 번 이은 덩어리(중간에서 잘리지 않아야 틀이 깨지지 않는다)
            while True:
                yield block
        return ns.FakeSocket(stream=stream())

    def cut(self, sock, *, limit=1000, reason=errors.REASON_TOO_LARGE):
        """끝없는 응답이 상한 안에서 끊기는지 본다. `reason` 은 이유 낱말 하나이거나 (너무 큼, 모양) 둘의 묶음이다.

        묶음을 받는 까닭(Q 재검증 필수-1): 이 홍수를 **누가 끊는지는 파이썬 패치 판에 따라 다르다** — 옛 패치(3.12.0·3.10.5)의 `http.client` 에는 100 Continue 연속 답·끝 머리글 줄 수의 한도가 없어 우리 상한이 끊고
        (이유 '너무 큼', 세부 `wire`), 최신 패치에는 그 한도가 있어 `http.client` 가 상한에 닿기 전에 스스로 끊는다(이유 '답의 모양'). 두 경우 모두 '끊김'이므로 코드·보낸 뒤 실패·읽은 바이트 상한·연결 닫힘·기록은 그대로 단언하고,
        느슨한 것은 이유 낱말 하나뿐이다 — 그 대신 **이유와 읽은 바이트가 서로 맞아야 한다**: '너무 큼' 이면 세부가 `wire` 이고 읽은 바이트가 상한을 넘었고, '모양' 이면 읽은 바이트가 상한 이하(우리 상한은 건드리지도 않았다)다."""
        env = ns.Harness(self, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
        with env, og.Tripwire() as wire, self.assertRaises(errors.NetError) as caught:
            env.client.request("update_check", "GET", UPDATE_URL, limit=limit)
        self.assertEqual(wire.calls, [])
        error = caught.exception
        self.assertEqual((error.code, error.outcome_unknown), ("NET_RESPONSE_INVALID", True), f"{error.code} {error.detail} — 읽은 바이트 {sock.served}")
        reasons = reason if isinstance(reason, tuple) else (reason,)
        said = [item for item in reasons if item in error.rendered().message]
        self.assertEqual(len(said), 1, f"허용한 이유 {reasons} 가운데 정확히 하나가 있어야 한다: {error.rendered().message}")
        cap = 2 * limit + 2 * endpoints.MAX_HEADER_BYTES
        self.assertLessEqual(sock.served, cap + 8192, f"상한 {cap} 바이트를 넘겨 {sock.served} 바이트나 읽었다")
        self.assertTrue(sock.closed)
        self.assertEqual(env.usage.records()[0].error, "NET_RESPONSE_INVALID")
        if said[0] == errors.REASON_TOO_LARGE:
            self.assertEqual(error.detail, "update_check:wire", "'너무 큼' 은 받는 바이트 상한이 끊었다는 뜻이다")
            self.assertGreater(sock.served, cap, f"'너무 큼' 인데 읽은 바이트 {sock.served} 가 상한 {cap} 을 넘지 않았다")
        else:
            self.assertLessEqual(sock.served, cap, f"'모양' 은 표준 라이브러리 한도가 상한 안에서 먼저 끊었다는 뜻인데 읽은 바이트 {sock.served} 가 상한 {cap} 을 넘었다")

    def test_the_wire_cap_is_twice_the_body_limit_plus_two_header_allowances(self):
        for limit in (0, 1, 1000, 1024 * 1024, 20 * 1024 * 1024):
            self.assertEqual(client._wire_cap(limit), 2 * limit + 2 * endpoints.MAX_HEADER_BYTES, limit)

    def test_endless_trailer_lines_after_a_complete_chunked_body_are_cut(self):
        """끝없는 끝 머리글 줄 — 옛 패치에서는 우리 상한이, 줄 수에 한도를 둔 최신 패치에서는 `http.client` 가 먼저 끊는다(Q 재검증 필수-1). 어느 쪽이든 끊기고 이유와 읽은 바이트가 서로 맞는다(`cut` 설명).
        파이썬 판과 상관없이 우리 상한이 끊는다는 것은 바로 아래 '몇 줄 안 되는 큰 줄' 시험이 지킨다."""
        self.cut(self.flood(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n5\r\nhello\r\n0\r\n", b"X-Trailer: " + b"a" * 1000 + b"\r\n"), reason=(errors.REASON_TOO_LARGE, errors.REASON_SHAPE))

    def test_a_few_huge_trailer_lines_are_cut_by_our_cap_on_every_python(self):
        """상한이 `http.client` 의 줄 수 한도와 상관없이 일한다는 증거 — 줄 하나가 약 59 KB(표준 라이브러리의 줄 한도 64 KiB 안)라 상한(133,072바이트)에 닿는 데 세 줄이면 되어 줄 수 한도(100)에 닿지 않는다.
        그래서 어느 파이썬 판에서도 우리 상한이 끊고 이유는 늘 '너무 큼'(세부 `wire`, 읽은 바이트 > 상한)이다 — 위 시험처럼 이유를 느슨하게 받지 않는다."""
        self.cut(self.flood(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n5\r\nhello\r\n0\r\n", b"X-Trailer: " + b"a" * 59_000 + b"\r\n"))

    @staticmethod
    def trailer_response(total):
        """받은 바이트가 **정확히 `total`** 인 chunked 응답 — 머리글 + 본문 5바이트(`hello`) + 끝 머리글(트레일러) 줄들 + 끝 빈 줄. 줄은 6만 바이트씩(마지막 줄만 다르다) — **줄이 몇 개 안 돼야 한다**:
        최신 패치 파이썬의 `http.client` 는 끝 머리글 줄 수가 100 을 넘으면 스스로 끊어서(Q 재검증 필수-1), 천 바이트 줄로 상한 크기를 채우면 상한에 닿기 전에 끊겨 경계를 볼 수 없다(3.13 에서 확인)."""
        head = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n5\r\nhello\r\n0\r\n"
        tail = b"\r\n"
        remaining = total - len(head) - len(tail)
        lines = []
        while remaining > 60_008:
            lines.append(b"X-T: " + b"a" * 59_993 + b"\r\n")
            remaining -= 60_000
        lines.append(b"X-T: " + b"a" * (remaining - 7) + b"\r\n")
        data = head + b"".join(lines) + tail
        assert len(data) == total, (len(data), total)
        return data

    def test_a_response_of_exactly_the_cap_is_read_to_the_end(self):
        """S 재검증 참고-1(경계 ±1, 변이 S04 `>=`) — 받은 바이트가 정확히 상한이면 통과한다(`>` 이지 `>=` 가 아니다). 본문 5바이트는 그대로 돌아오고 접속 기록의 받은 바이트도 정확히 그 값이다."""
        limit = 1000
        cap = client._wire_cap(limit)
        for total in (cap - 1, cap):
            with self.subTest(total=total, cap=cap):
                sock = ns.FakeSocket(self.trailer_response(total))
                env = ns.Harness(self, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
                with env, og.Tripwire() as wire:
                    response = env.client.request("update_check", "GET", UPDATE_URL, limit=limit)
                self.assertEqual(wire.calls, [])
                self.assertEqual((response.status, response.body), (200, b"hello"))
                self.assertEqual((sock.served, env.usage.records()[0].received), (total, total))

    def test_a_response_one_byte_over_the_cap_is_cut(self):
        """S 재검증 참고-1(경계 ±1, 변이 S05 `> cap + 1`) — 상한보다 한 바이트라도 많으면 끊긴다: `NET_RESPONSE_INVALID`(너무 큼, 세부 `wire`, 보낸 뒤 실패)이고 연결은 닫힌다."""
        limit = 1000
        cap = client._wire_cap(limit)
        for total in (cap + 1, cap + 2):
            with self.subTest(total=total, cap=cap):
                sock = ns.FakeSocket(self.trailer_response(total))
                env = ns.Harness(self, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
                with env, og.Tripwire() as wire, self.assertRaises(errors.NetError) as caught:
                    env.client.request("update_check", "GET", UPDATE_URL, limit=limit)
                self.assertEqual(wire.calls, [])
                self.assertEqual((caught.exception.code, caught.exception.outcome_unknown, caught.exception.detail), ("NET_RESPONSE_INVALID", True, "update_check:wire"))
                self.assertIn(errors.REASON_TOO_LARGE, caught.exception.rendered().message)
                self.assertTrue(sock.closed)

    def test_an_endless_run_of_100_continue_answers_is_cut(self):
        """끝없는 `100 Continue` 연속 답 — 옛 패치에서는 우리 상한이, 연속 답 수에 한도를 둔 최신 패치에서는 `http.client` 가 8 KB 쯤에서 먼저 끊는다(Q 재검증 필수-1). 어느 쪽이든 끊기고 이유와 읽은 바이트가 서로 맞는다(`cut` 설명)."""
        self.cut(self.flood(b"HTTP/1.1 100 Continue\r\n\r\n", b"HTTP/1.1 100 Continue\r\n\r\n"), reason=(errors.REASON_TOO_LARGE, errors.REASON_SHAPE))

    def test_a_few_huge_100_continue_answers_are_cut_by_our_cap_on_every_python(self):
        """위와 같은 약속 — 연속 답 하나가 약 59 KB(머리글 한 줄이 줄 한도 안)라 상한에 세 번이면 닿아 연속 답 수 한도(100)에 닿지 않는다. 어느 파이썬 판에서도 우리 상한이 끊고 이유는 늘 '너무 큼'(세부 `wire`)이다."""
        huge = b"HTTP/1.1 100 Continue\r\nX-Pad: " + b"a" * 59_000 + b"\r\n\r\n"
        self.cut(self.flood(huge, huge))

    def test_a_flood_of_one_byte_chunks_is_cut_by_the_wire_cap_before_the_body_limit_is_reached(self):
        """덩어리 하나가 1바이트면 본문 1바이트에 틀이 5바이트다 — 본문 상한만으로는 6배를 읽어야 끊겼다."""
        self.cut(self.flood(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n", b"1\r\nx\r\n"), limit=100_000)

    def test_an_endless_header_block_is_cut(self):
        """머리글은 `http.client` 의 개수 한도(100개)가 먼저 끊는다 — 상한과 부딪치지 않고 같은 오류 코드로 끝난다(이유 낱말만 다르다)."""
        self.cut(self.flood(b"HTTP/1.1 200 OK\r\nConnection: close\r\n", b"X-Header: value\r\n"), reason=errors.REASON_SHAPE)

    def test_a_legitimate_response_at_the_body_limit_is_never_cut_by_the_wire_cap(self):
        """상한 정확히 크기의 본문은(덩어리 틀·머리글이 붙어도) 통과한다 — 틀 몫이 본문의 한 푼도 깎지 않는다."""
        limit = 1024 * 1024
        for framing in ("length", "chunked", "none"):
            with self.subTest(framing=framing):
                body = (b"0123456789abcdef" * (limit // 16))[:limit]
                sock = ns.FakeSocket(pieces=pieces_of(framing, True, body, extra=["X-Pad: " + "p" * 3000]))
                env = ns.Harness(self, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
                with env:
                    response = env.client.request("update_check", "GET", UPDATE_URL)
                self.assertEqual(len(response.body), limit)
                self.assertLess(sock.served, client._wire_cap(limit))


class DeadlineTest(unittest.TestCase):
    def test_slow_headers_and_slow_body_stop_at_the_total_deadline(self):
        """NT-27 — 한 바이트씩 찔끔 보내는 서버가 총 시간 안에 끊긴다(소켓 제한은 작업마다라 이것만으로는 못 막는다 — 마감 껍데기가 막는다)."""
        clock = ns.FakeClock()
        slow = ns.http_response(200, body=b"x" * 5)
        env = ns.Harness(self, slow, clock=clock, delay=10.0, chunk=1, switches=ns.USE_SWITCHES["update_check"])
        with env, self.assertRaises(errors.NetError) as caught:
            env.client.request("update_check", "GET", UPDATE_URL)
        error = caught.exception
        self.assertEqual((error.code, error.outcome_unknown), ("NETWORK_TIMEOUT", True))
        self.assertLessEqual(clock.now - 1000.0, endpoints.TOTAL_TIMEOUT + 0.001, "총 시간을 넘겨서까지 읽었다")
        self.assertGreaterEqual(clock.now - 1000.0, endpoints.TOTAL_TIMEOUT - 10.001)
        self.assertLess(min(env.last_socket.timeouts), 15.0, "남은 시간이 작업 제한보다 작아지면 소켓 제한을 줄인다")
        self.assertEqual(env.usage.records()[0].error, "NETWORK_TIMEOUT")
        # 머리글은 빨리 오고 본문만 찔끔 오는 경우
        head = ns.http_response(200, body=b"y" * 200)
        sock = ns.FakeSocket(head, clock=clock, delay=0.0, chunk=len(head) - 200)
        calls = {"n": 0}
        original = sock.recv_into

        def drip(buffer):
            calls["n"] += 1
            if calls["n"] > 1:
                sock.delay = 9.0
                sock.chunk = 1
            return original(buffer)
        sock.recv_into = drip
        clock.now = 1000.0
        env = ns.Harness(self, clock=clock, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
        with env, self.assertRaises(errors.NetError) as caught:
            env.client.request("update_check", "GET", UPDATE_URL)
        self.assertEqual(caught.exception.code, "NETWORK_TIMEOUT")
        self.assertLessEqual(clock.now - 1000.0, endpoints.TOTAL_TIMEOUT + 0.001)

    def test_nothing_is_sent_once_the_deadline_has_passed(self):
        """G-5(a)(독립 검증 Q) — 보내기도 남은 시간을 본다: 보안 확인이 오래 걸려 마감이 지났으면 한 바이트도 보내지 않고 `NETWORK_TIMEOUT` 이다(예전에는 마감 시험이 읽기 쪽뿐이어서 보내기 쪽 점검이 지워져도 몰랐다 — 변이 Q29)."""
        clock = ns.FakeClock()
        env = ns.Harness(self, ns.http_response(200, body=b"{}"), clock=clock, switches=ns.USE_SWITCHES["update_check"])

        def slow_secure(connection, raw):
            clock.advance(40.0)                                          # 보안 확인이 오래 걸려 총 시간(30초)이 지났다
            return raw
        with env, mock.patch.object(client, "_secure", slow_secure), self.assertRaises(errors.NetError) as caught:
            env.client.request("update_check", "GET", UPDATE_URL)
        self.assertEqual(caught.exception.code, "NETWORK_TIMEOUT")
        self.assertEqual((env.last_socket.send_calls, bytes(env.last_socket.sent), env.last_socket.reads), ([], b"", 0), "마감이 지난 뒤에는 보내지도 읽지도 않는다")
        self.assertTrue(env.last_socket.closed)

    def test_one_slow_read_beyond_the_socket_limit_is_a_timeout_and_the_deadline_is_counted_from_the_start(self):
        clock = ns.FakeClock()
        env = ns.Harness(self, ns.http_response(200, body=b"{}"), clock=clock, delay=16.0, switches=ns.USE_SWITCHES["update_check"])
        with env, self.assertRaises(errors.NetError) as caught:
            env.client.request("update_check", "GET", UPDATE_URL)
        self.assertEqual(caught.exception.code, "NETWORK_TIMEOUT")
        self.assertEqual(env.last_socket.timeouts[0], endpoints.IO_TIMEOUT)

    def test_a_connect_that_returns_after_the_deadline_stops_before_the_handshake(self):
        clock = ns.FakeClock()

        class SlowDial(ns.Harness):
            def _dial(self, connection, address):
                sock = super()._dial(connection, address)
                clock.advance(40.0)                                   # 이름 풀이가 오래 걸렸다
                return sock
        env = SlowDial(self, ns.http_response(200, body=b"{}"), clock=clock, switches=ns.USE_SWITCHES["update_check"])
        secured = []
        with env, mock.patch.object(client, "_secure", lambda connection, raw: secured.append(1) or raw), self.assertRaises(errors.NetError) as caught:
            env.client.request("update_check", "GET", UPDATE_URL)
        self.assertEqual((caught.exception.code, caught.exception.outcome_unknown, secured), ("NETWORK_TIMEOUT", False, []))


class ErrorMappingTest(unittest.TestCase):
    def secret_exception(self, kind=OSError):
        return kind(f"{ns.CANARY} https://{HOST_UPDATE}{UPDATE_PATH} server said: 'secret details' C:\\Users\\someone\\x")

    def assert_clean(self, error):
        everything = [str(error), repr(error.args), error.detail, error.log_line(), error.rendered().message, error.rendered().action, error.rendered().card_action, repr(error.slots)]
        for text in everything:
            for leak in (ns.CANARY, HOST_UPDATE, UPDATE_PATH, "secret details", "someone", "server said", "https://"):
                self.assertNotIn(leak, text, f"{error.code}: {leak} 가 {text[:60]!r} 에 있다")
        self.assertIn(error.code, CATALOG)

    def test_every_failure_maps_to_a_catalog_code_without_url_or_server_text(self):
        """NT-28 — 전송 중 터진 모든 예외는 표의 코드가 되고, 예외 문장·주소·서버 글·경로가 문구·세부·기록 어디에도 없다."""
        import ssl
        cases = [
            ("이름 풀이", dict(dial_error=self.secret_exception(OSError)), "NETWORK_OFFLINE", False),
            ("연결 거부", dict(dial_error=self.secret_exception(ConnectionRefusedError)), "NETWORK_OFFLINE", False),
            ("연결 시간 초과", dict(dial_error=self.secret_exception(TimeoutError)), "NETWORK_TIMEOUT", False),
            ("보내다 끊김", dict(send_error=self.secret_exception(ConnectionResetError)), "NETWORK_OFFLINE", True),
            ("보내다 시간 초과", dict(send_error=self.secret_exception(TimeoutError)), "NETWORK_TIMEOUT", True),
            ("읽다 끊김", dict(read_error=self.secret_exception(ConnectionAbortedError)), "NETWORK_OFFLINE", True),
            ("읽다 시간 초과", dict(read_error=self.secret_exception(TimeoutError)), "NETWORK_TIMEOUT", True),
            ("읽다 TLS 오류", dict(read_error=self.secret_exception(ssl.SSLError)), "NETWORK_OFFLINE", True),
            ("답 없이 끊김", dict(), "NETWORK_OFFLINE", True),
            ("상태 줄이 이상함", dict(response=b"BOGUS\r\n\r\n"), "NET_RESPONSE_INVALID", True),
            ("머리글 줄이 너무 긺", dict(response=b"HTTP/1.1 200 OK\r\n" + b"a" * 70000), "NET_RESPONSE_INVALID", True),
        ]
        for label, spec, code, unknown in cases:
            with self.subTest(label=label):
                env = ns.Harness(self, spec.get("response", b""), dial_error=spec.get("dial_error"), send_error=spec.get("send_error"), read_error=spec.get("read_error"), switches=ns.USE_SWITCHES["update_check"])
                with env, self.assertRaises(errors.NetError) as caught:
                    env.client.request("update_check", "GET", UPDATE_URL)
                error = caught.exception
                self.assertEqual((error.code, error.outcome_unknown), (code, unknown), label)
                self.assert_clean(error)
                records = repr(env.usage.records())
                for leak in (ns.CANARY, "secret details", "someone"):
                    self.assertNotIn(leak, records)
                self.assertEqual(env.usage.records()[0].error, code)

    def test_tls_failures_at_the_handshake_are_tls_failed_and_never_say_why_in_words(self):
        import ssl
        for exception in (self.secret_exception(ssl.SSLCertVerificationError), self.secret_exception(ssl.SSLError), ssl.CertificateError(f"{ns.CANARY} hostname mismatch")):
            with self.subTest(kind=type(exception).__name__):
                env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"])
                with env, mock.patch.object(client, "_secure", mock.Mock(side_effect=exception)), self.assertRaises(errors.NetError) as caught:
                    env.client.request("update_check", "GET", UPDATE_URL)
                self.assertEqual((caught.exception.code, caught.exception.outcome_unknown), ("NET_TLS_FAILED", False))
                self.assert_clean(caught.exception)
                self.assertTrue(env.last_socket.closed, "핸드셰이크가 실패하면 열린 소켓을 닫는다")

    def test_status_codes_map_to_the_documented_default_codes(self):
        """3.4 의 기본표 — 2xx 는 정상, 400·422 REQUEST_INVALID, 401 KEY_AUTH_FAILED, 403 은 사유가 한도면 API_RATE_LIMITED, 429 API_RATE_LIMITED, 5xx 넷 API_SERVER_ERROR, 그 밖은 NET_RESPONSE_INVALID."""
        expected = {200: None, 201: None, 204: None, 299: None, 400: "REQUEST_INVALID", 422: "REQUEST_INVALID", 401: "KEY_AUTH_FAILED", 403: "KEY_AUTH_FAILED", 404: "NET_RESPONSE_INVALID", 405: "NET_RESPONSE_INVALID",
                    409: "NET_RESPONSE_INVALID", 429: "API_RATE_LIMITED", 500: "API_SERVER_ERROR", 502: "API_SERVER_ERROR", 503: "API_SERVER_ERROR", 504: "API_SERVER_ERROR", 501: "NET_RESPONSE_INVALID", 505: "NET_RESPONSE_INVALID"}
        for status, code in expected.items():
            with self.subTest(status=status):
                response = client.NetResponse(status=status, use="update_check", host=HOST_UPDATE, body=b"SERVER TEXT secret details")
                if code is None:
                    response.raise_for_status()
                    continue
                with self.assertRaises(errors.NetError) as caught:
                    response.raise_for_status()
                self.assertEqual(caught.exception.code, code)
                self.assert_clean_status(caught.exception)
        for reason in errors.RATE_LIMIT_REASONS:
            with self.assertRaises(errors.NetError) as caught:
                client.NetResponse(status=403, use="blogger_read", host="x.example").raise_for_status(reason=reason)
            self.assertEqual(caught.exception.code, "API_RATE_LIMITED", reason)
        with self.assertRaises(errors.NetError) as caught:
            client.NetResponse(status=403, use="blogger_read", host="x.example").raise_for_status(reason="forbidden")
        self.assertEqual(caught.exception.code, "KEY_AUTH_FAILED")
        with self.assertRaises(errors.NetError) as caught:
            client.NetResponse(status=401, use="blogger_read", host="x.example").raise_for_status(overrides={401: "BLOGGER_AUTH_EXPIRED"})
        self.assertEqual(caught.exception.code, "BLOGGER_AUTH_EXPIRED")
        self.assertEqual([errors.counts_as_failure(status) for status in (200, 400, 422, 429, 401, 403, 404, 500, 503)], [False, False, False, False, True, True, True, True, True])

    def assert_clean_status(self, error):
        for text in (str(error), error.detail, error.log_line(), error.rendered().message, error.rendered().action):
            self.assertNotIn("SERVER TEXT", text)
            self.assertNotIn("secret details", text)

    def test_a_status_that_is_not_ok_comes_back_as_a_response_and_is_recorded_with_its_default_code(self):
        env, response = run(self, ns.http_response(503, "Service Unavailable", body=b"<html>oops secret details</html>"))
        self.assertEqual((response.status, response.ok), (503, False))
        self.assertEqual((env.usage.records()[0].status, env.usage.records()[0].error), (503, "API_SERVER_ERROR"))
        self.assertNotIn("secret details", repr(response), "본문은 repr 에 찍히지 않는다")
        self.assertNotIn("secret details", repr(env.usage.records()))

    def test_the_client_never_retries_by_itself(self):
        """NT-29 — 실패해도 전송 시도는 1회다(503·연결 실패·끊김 모두)."""
        env, response = run(self, ns.http_response(503, "Service Unavailable"))
        self.assertEqual(len(env.dials), 1)
        for spec in (dict(dial_error=OSError("x")), dict(send_error=ConnectionResetError("x")), dict(read_error=TimeoutError("x"))):
            with self.subTest(spec=list(spec)):
                env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"], **spec)
                with env, self.assertRaises(errors.NetError):
                    env.client.request("update_check", "GET", UPDATE_URL)
                self.assertEqual(len(env.dials), 1)
        env = ns.Harness(self, sockets=[ns.FakeSocket(b""), ns.FakeSocket(OK_JSON)], switches=ns.USE_SWITCHES["update_check"])
        with env, self.assertRaises(errors.NetError):
            env.client.request("update_check", "GET", UPDATE_URL)
        self.assertEqual((len(env.dials), len(env.sockets)), (1, 1), "두 번째 가짜 서버는 쓰이지 않았다")

    def test_outcome_unknown_is_reported_only_after_the_request_was_sent(self):
        """NT-37 — 보내기 전 실패(풀이·연결·TLS)는 False, 보낸 뒤 실패(보내다 끊김·답 없음·읽다 끊김)는 True."""
        import ssl
        before = [dict(dial_error=OSError("x")), dict(dial_error=TimeoutError("x"))]
        for spec in before:
            env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["blogger_draft"], **spec)
            with env, self.assertRaises(errors.NetError) as caught:
                env.client.request("blogger_draft", "POST", BLOG + "/posts?isDraft=true", body=b"{}", bearer="t")
            self.assertFalse(caught.exception.outcome_unknown)
        env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["blogger_draft"])
        with env, mock.patch.object(client, "_secure", mock.Mock(side_effect=ssl.SSLError("x"))), self.assertRaises(errors.NetError) as caught:
            env.client.request("blogger_draft", "POST", BLOG + "/posts?isDraft=true", body=b"{}", bearer="t")
        self.assertFalse(caught.exception.outcome_unknown)
        for spec in (dict(send_error=ConnectionResetError("x")), dict(read_error=ConnectionResetError("x")), dict(read_error=TimeoutError("x")), dict()):
            with self.subTest(spec=list(spec)):
                env = ns.Harness(self, b"", switches=ns.USE_SWITCHES["blogger_draft"], **spec)
                with env, self.assertRaises(errors.NetError) as caught:
                    env.client.request("blogger_draft", "POST", BLOG + "/posts?isDraft=true", body=b"{}", bearer="t")
                self.assertTrue(caught.exception.outcome_unknown)


class CooldownTest(unittest.TestCase):
    def test_cooldown_after_three_failures_and_half_open_probe(self):
        """NT-30 — 연속 3번 실패하면 5분 쉰다(쉬는 동안 즉시 거절·접속 0), 끝나면 한 건만 보내 보고 실패하면 두 배(10분·20분·상한 30분), 성공하면 닫힌다."""
        clock = ns.FakeClock()
        env = ns.Harness(self, clock=clock, switches=ns.USE_SWITCHES["update_check"], dial_error=OSError("x"))
        with env:
            for _ in range(3):
                with self.assertRaises(errors.NetError) as caught:
                    env.client.request("update_check", "GET", UPDATE_URL)
                self.assertEqual(caught.exception.code, "NETWORK_OFFLINE")
            self.assertEqual(len(env.dials), 3)
            with self.assertRaises(errors.NetError) as caught:
                env.client.request("update_check", "GET", UPDATE_URL)
            self.assertEqual(caught.exception.code, "NET_COOLDOWN")
            self.assertEqual(len(env.dials), 3, "쉬는 동안에는 접속하지 않는다")
            self.assertRegex(caught.exception.slots["재시도 가능 시각"], r"^\d\d:\d\d$")
            self.assertEqual(caught.exception.rendered().retry_kind, "after_user")
            self.assertEqual(len(env.usage.records()), 3, "쉬는 중 거절은 접속 기록에 남지 않는다")
            clock.advance(usage.REST_SECONDS[0] + 1)                                               # 5분이 지났다 — 반쯤 열림: 한 건만 보내 본다
            with self.assertRaises(errors.NetError) as caught:
                env.client.request("update_check", "GET", UPDATE_URL)
            self.assertEqual((caught.exception.code, len(env.dials)), ("NETWORK_OFFLINE", 4))
            with self.assertRaises(errors.NetError) as caught:                                    # 그 한 건이 실패했으니 곧바로 더 길게(10분) 쉰다
                env.client.request("update_check", "GET", UPDATE_URL)
            self.assertEqual((caught.exception.code, len(env.dials)), ("NET_COOLDOWN", 4))
        self.assertTrue(env.usage.resting("update_check"))
        # 성공하면 닫힌다
        clock = ns.FakeClock()
        env = ns.Harness(self, clock=clock, switches=ns.USE_SWITCHES["update_check"], dial_error=OSError("x"))
        with env:
            for _ in range(3):
                with self.assertRaises(errors.NetError):
                    env.client.request("update_check", "GET", UPDATE_URL)
            clock.advance(usage.REST_SECONDS[0] + 1)
            env.dial_error = None
            env.template["data"] = OK_JSON
            self.assertEqual(env.client.request("update_check", "GET", UPDATE_URL).status, 200)
            self.assertFalse(env.usage.resting("update_check"))
            for _ in range(2):
                env.dial_error = OSError("x")
                with self.assertRaises(errors.NetError) as caught:
                    env.client.request("update_check", "GET", UPDATE_URL)
                self.assertEqual(caught.exception.code, "NETWORK_OFFLINE", "닫힌 뒤에는 다시 세어 처음부터다")

    def test_rest_lengths_double_up_to_the_cap_and_a_failed_probe_rests_longer(self):
        clock = ns.FakeClock()
        env = ns.Harness(self, clock=clock, switches=ns.USE_SWITCHES["update_check"], dial_error=OSError("x"))
        rests = []
        with env:
            for _ in range(3):
                with self.assertRaises(errors.NetError):
                    env.client.request("update_check", "GET", UPDATE_URL)
            for _ in range(5):
                state = env.usage._state["update_check"]
                rests.append(round(state["until"] - clock.now))
                clock.advance(rests[-1] + 1)
                with self.assertRaises(errors.NetError) as caught:
                    env.client.request("update_check", "GET", UPDATE_URL)                          # 반쯤 열림의 한 건 — 실패
                self.assertEqual(caught.exception.code, "NETWORK_OFFLINE")
        self.assertEqual(rests, [300, 600, 1200, 1800, 1800])

    def test_a_success_after_resting_longer_brings_the_rest_length_back_to_the_start(self):
        """G-5(d)(독립 검증 Q 변이 Q66) — 반쯤 열림에서 실패해 더 길게(10분) 쉬었다가 성공하면 닫히고 쉬는 단계도 처음(5분)으로 돌아간다. 단계가 남으면 다음 연속 실패 뒤 20분을 쉰다."""
        clock = ns.FakeClock()
        env = ns.Harness(self, clock=clock, switches=ns.USE_SWITCHES["update_check"], dial_error=OSError("x"))
        with env:
            for _ in range(3):
                with self.assertRaises(errors.NetError):
                    env.client.request("update_check", "GET", UPDATE_URL)
            clock.advance(usage.REST_SECONDS[0] + 1)
            with self.assertRaises(errors.NetError):
                env.client.request("update_check", "GET", UPDATE_URL)                              # 반쯤 열림의 한 건이 실패 — 10분 쉼
            self.assertEqual(round(env.usage._state["update_check"]["until"] - clock.now), 600)
            clock.advance(usage.REST_SECONDS[1] + 1)
            env.dial_error = None
            env.template["data"] = OK_JSON
            self.assertEqual(env.client.request("update_check", "GET", UPDATE_URL).status, 200)   # 이번 한 건은 성공 — 닫힘
            env.dial_error = OSError("x")
            for _ in range(3):
                with self.assertRaises(errors.NetError) as caught:
                    env.client.request("update_check", "GET", UPDATE_URL)
                self.assertEqual(caught.exception.code, "NETWORK_OFFLINE")
            self.assertEqual(round(env.usage._state["update_check"]["until"] - clock.now), 300, "성공했으니 쉬는 단계가 처음(5분)으로 돌아간다")

    def test_user_mistakes_and_rate_limits_do_not_count_toward_resting_but_server_errors_do(self):
        for status, rests in ((400, False), (422, False), (429, False), (401, True), (403, True), (404, True), (500, True), (503, True)):
            with self.subTest(status=status):
                env = ns.Harness(self, ns.http_response(status, "x"), switches=ns.USE_SWITCHES["update_check"])
                with env:
                    for _ in range(3):
                        self.assertEqual(env.client.request("update_check", "GET", UPDATE_URL).status, status)
                    self.assertEqual(env.usage.resting("update_check"), rests)

    def test_an_expected_404_while_waiting_for_a_deployment_never_rests_the_public_site_check(self):
        """공개 사이트 확인은 글이 열릴 때까지 404 가 이어지는 것이 정상이다 — 계수에서 빠진다(다른 용도의 404 는 센다). 5xx 는 센다."""
        self.assertEqual(endpoints.ENDPOINTS["pages_site"].uncounted_statuses, (400, 404, 422, 429))
        self.assertEqual(endpoints.ENDPOINTS["update_check"].uncounted_statuses, (400, 422, 429))
        env = ns.Harness(self, ns.http_response(404, "Not Found"), switches=ns.USE_SWITCHES["pages_site"])
        with env:
            for _ in range(8):
                self.assertEqual(env.client.request("pages_site", "GET", SITE_URL).status, 404)
            self.assertFalse(env.usage.resting("pages_site"), "404 가 여덟 번 이어져도 쉬지 않는다")
            env.template["data"] = ns.http_response(503, "Service Unavailable")
            for _ in range(3):
                self.assertEqual(env.client.request("pages_site", "GET", SITE_URL).status, 503)
            self.assertTrue(env.usage.resting("pages_site"), "5xx 는 센다")
        self.assertEqual(endpoints.table_problems({"pages_site": dataclasses.replace(endpoints.ENDPOINTS["pages_site"], uncounted_statuses=(404,))}) != [], True, "400·422·429 는 늘 빠져야 한다")
        self.assertEqual(endpoints.table_problems({"pages_site": dataclasses.replace(endpoints.ENDPOINTS["pages_site"], uncounted_statuses=(400, 422, 429, 500))}) != [], True, "4xx 만 더할 수 있다")

    def test_cooldown_is_per_use_and_a_second_request_in_flight_is_refused(self):
        clock = ns.FakeClock()
        env = ns.Harness(self, clock=clock, switches=("EXTERNAL_WRITE", "NET_UPDATE_CHECK", "NET_PAGES_SITE"), dial_error=OSError("x"))
        with env:
            for _ in range(3):
                with self.assertRaises(errors.NetError):
                    env.client.request("update_check", "GET", UPDATE_URL)
            env.dial_error = None
            env.template["data"] = ns.http_response(200, body=b"[]")
            self.assertEqual(env.client.request("pages_site", "GET", SITE_URL).status, 200, "다른 용도는 쉬지 않는다")
            env.usage.begin("pages_site")
            with self.assertRaises(errors.NetError) as caught:                      # 진행 중인 같은 용도의 두 번째 요청
                env.client.request("pages_site", "GET", SITE_URL)
            self.assertEqual(caught.exception.code, "NET_COOLDOWN")
            env.usage.abort("pages_site")
            self.assertEqual(env.client.request("pages_site", "GET", SITE_URL).status, 200)

    def test_the_usage_log_is_a_ring_of_fifty_and_only_takes_the_documented_fields(self):
        """NT-38 — 접속 기록은 고리 50건이고 칸은 정해진 것뿐이며(머리글·본문·질의 값·토큰·주소 없음) 숫자 ID 는 `<번호>` 로 가린다."""
        self.assertEqual(usage.RECORD_FIELDS, ("at", "use", "host", "method", "route", "status", "error", "sent", "received", "seconds"))
        with ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["blogger_read"]) as env:
            for number in range(55):
                env.template["data"] = OK_JSON
                env.client.request("blogger_read", "GET", f"https://www.googleapis.com/blogger/v3/blogs/{number}0123/posts?status=DRAFT&orderBy=UPDATED&maxResults=5&fetchBodies=false&view=ADMIN", bearer="CANARY_TOKEN")
            records = env.usage.records()
            self.assertEqual(len(records), 50)
            self.assertEqual({record.route for record in records}, {"/blogger/v3/blogs/<번호>/posts"})
            text = repr(records)
            for leak in ("CANARY_TOKEN", "status=DRAFT", "0123", "Bearer", "Authorization", "orderBy"):
                self.assertNotIn(leak, text)
            self.assertEqual({field.name for field in dataclasses.fields(records[0])}, set(usage.RECORD_FIELDS))
            with self.assertRaises(ValueError):
                env.usage.record(at=0, use="x", host="h", method="GET", route="r", status=0, error="", sent=0, received=0, seconds=0.0, body="secret")
            self.assertEqual(records[0].host, "www.googleapis.com")
            self.assertEqual((records[0].method, records[0].status, records[0].error), ("GET", 200, ""))
            self.assertGreater(records[0].sent, 0)
            self.assertGreater(records[0].received, 0)
        with ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"], dial_error=OSError("x")) as env:
            with self.assertRaises(errors.NetError):
                env.client.request("update_check", "GET", UPDATE_URL)
            self.assertEqual((env.usage.records()[0].status, env.usage.records()[0].error), (0, "NETWORK_OFFLINE"))


class LeakTest(unittest.TestCase):
    def test_canary_never_appears_in_request_bytes_logs_errors_or_records(self):
        """NT-32 — 사진 이름·OCR 글·사용자 이름·데이터 폴더 경로의 카나리가 요청 바이트·표준 출력·오류·기록 어디에도 없다(요청에 실리는 것은 표의 값과 호출하는 쪽이 정한 토큰·본문뿐)."""
        canary = ns.CANARY
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / f"{canary}_data"
            data_dir.mkdir()
            (data_dir / f"{canary}_photo.jpg").write_bytes(b"x")
            (data_dir / "ocr.txt").write_text(f"{canary} OCR 글", encoding="utf-8")
            with mock.patch.dict("os.environ", {"USERNAME": canary + "user", "LOCALAPPDATA": str(data_dir), "COMPUTERNAME": canary + "pc"}):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    env, _ = run(self, OK_JSON, "blogger_read", BLOG, bearer="TOKEN123")
                    env2 = ns.Harness(self, b"", dial_error=OSError(canary), switches=ns.USE_SWITCHES["update_check"])
                    with env2, self.assertRaises(errors.NetError) as caught:
                        env2.client.request("update_check", "GET", UPDATE_URL)
                wire = bytes(env.last_socket.sent).decode("ascii")
                self.assertNotIn(canary, wire)
                self.assertEqual(wire.count("TOKEN123"), 1, "토큰은 Authorization 한 곳에만 있다")
                for text in (out.getvalue(), err.getvalue(), repr(env.usage.records()), repr(env2.usage.records()), caught.exception.log_line(), str(caught.exception), caught.exception.detail):
                    self.assertNotIn(canary, text)
                    self.assertNotIn("TOKEN123", text)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""), "클라이언트는 아무것도 출력하지 않는다")


class ErrorChainTest(unittest.TestCase):
    def test_the_error_does_not_drag_the_original_exception_with_the_server_text_along(self):
        """S 참고-2(독립 검증) — `raise 새 오류 from None` 은 표시만 숨길 뿐 `__context__` 에 원래 예외(예: 서버가 보낸 줄이 든 잘못된 상태 줄)를 남겼다. 이제 원래 예외는 오류에 매달려 있지 않고 표준 역추적에도 안 나온다."""
        import traceback
        canary = ns.CANARY
        for label, response in (("잘못된 상태 줄", f"{canary} not http at all\r\n\r\n".encode("ascii")), ("상태 번호가 숫자가 아님", f"HTTP/1.1 {canary} OK\r\n\r\n".encode("ascii")),
                                ("모르는 프로토콜", f"HTTP/9.{canary} 200 OK\r\n\r\n".encode("ascii"))):
            with self.subTest(label=label):
                env, error = raised(self, response)
                self.assertEqual(error.code, "NET_RESPONSE_INVALID")
                self.assertIsNone(error.__context__, "원래 예외가 매달려 있다")
                self.assertIsNone(error.__cause__)
                shown = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                self.assertNotIn(canary, shown)
        env, error = raised(self, b"", harness=ns.Harness(self, b"", dial_error=OSError(f"{canary} refused"), switches=ns.USE_SWITCHES["update_check"]))
        self.assertEqual(error.code, "NETWORK_OFFLINE")
        self.assertIsNone(error.__context__, "연결 실패의 원래 예외도 매달려 있지 않다")
        self.assertNotIn(canary, "".join(traceback.format_exception(type(error), error, error.__traceback__)))


class TlsGuidanceWordingTest(unittest.TestCase):
    def test_the_action_sends_the_user_to_the_security_team_and_never_tells_to_turn_security_off(self):
        """Q 재검증 참고-3(변이 Z37) — `NET_TLS_FAILED` 의 하실 일은 보안을 끄거나 예외로 두라고 하지 않고 정보 보안 담당자에게 문의하라고 한다(S 참고-7). 카탈로그와 문서가 함께 다른 말로 바뀌어도
        동기 시험이 초록이던 틈 — 문구의 핵심 낱말을 못박는다."""
        action = AppError("NET_TLS_FAILED", {}).rendered().action
        self.assertIn("정보 보안 담당자에게 문의", action)
        self.assertIn("앱은 확인을 건너뛰는 선택지를 두지 않아요", action)
        for banned in ("끄고", "끄세요", "꺼 주", "예외로", "예외 처리", "허용 목록", "무시하고", "해제"):
            self.assertNotIn(banned, action, banned)


class HelperEnvironmentTest(unittest.TestCase):
    """Q 재검증 필수-2 — 신뢰 저장소를 바꾸는 환경 변수(`SSL_CERT_FILE`·`SSL_CERT_DIR`)가 PC·러너에 걸려 있으면 접속 틀이 접속을 거절하므로(설계 C5) 시험 도우미가 이 둘을 비우지 않던 때는
    정상 연결을 기대하는 시험 80개가 한꺼번에 빨개졌다. 가짜 전송기 도우미(`net_support.Harness`)가 안에서 두 변수를 비우고 끝나면 되돌린다(NT-45 는 변수를 직접 설정한다)."""

    def test_the_fake_transport_helper_clears_the_trust_changing_variables_and_puts_them_back(self):
        poisoned = {"SSL_CERT_FILE": "poison_file", "SSL_CERT_DIR": "poison_dir"}
        with mock.patch.dict(os.environ, poisoned):
            self.assertTrue(client._trust_env_changed(), "대조 — 변수가 걸려 있으면 생산 코드는 접속하지 않는다(그래서 도우미가 비워야 한다)")
            env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"])
            with env:
                self.assertEqual([name for name in poisoned if name in os.environ], [], "도우미가 변수를 비우지 않았다")
                self.assertFalse(client._trust_env_changed())
                response = env.client.request("update_check", "GET", UPDATE_URL)
            self.assertEqual(response.status, 200)
            self.assertEqual({name: os.environ.get(name) for name in poisoned}, poisoned, "끝나면 원래 값으로 되돌린다")

    def test_a_request_through_the_helper_succeeds_with_either_variable_alone(self):
        for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
            with self.subTest(name=name), mock.patch.dict(os.environ, {name: "poison"}):
                env, response = run(self, OK_JSON)
                self.assertEqual(response.status, 200)
                self.assertEqual(os.environ.get(name), "poison")


class SiteFetcherTest(unittest.TestCase):
    """공개 확인 `fetcher`(D-736)는 vendor 확인 도구가 넘기는 `limit`(상태만 볼 때 0 = 본문을 읽지 않음)과 `Accept-Encoding` 을 그대로 지킨다(G-5(b) — 변이 Q46)."""

    Resp = collections.namedtuple("Resp", "status body headers error")
    BODY = b"p" * 5000

    def fetch(self, response=None, **kwargs):
        env = ns.Harness(self, response if response is not None else ns.http_response(200, body=self.BODY), switches=ns.USE_SWITCHES["pages_site"])
        with env, og.Tripwire() as wire:
            result = site.site_fetcher(self.Resp, client=env.client)(f"https://{SITE}/blog/post.html?cb=app", **kwargs)
        self.assertEqual(wire.calls, [])
        return env, result

    def test_a_limit_of_zero_reads_no_body_and_a_real_limit_is_enforced(self):
        env, result = self.fetch(limit=0)
        self.assertEqual((result.status, result.body, result.error), (200, b"", ""), "limit 0 은 상태만 본다 — 본문을 읽지 않는다")
        env, result = self.fetch()
        self.assertEqual((result.status, result.body), (200, self.BODY), "limit 을 안 주면 표의 기본 한도 안에서 본문을 읽는다")
        env, result = self.fetch(limit=100)
        self.assertEqual((result.status, result.body, result.error), (0, b"", "NET_RESPONSE_INVALID"), "한도(100)보다 큰 답은 거절한다")
        env, result = self.fetch(limit=len(self.BODY))
        self.assertEqual(len(result.body), len(self.BODY), "정확히 한도는 통과한다")

    def test_the_accept_encoding_the_tool_asks_for_is_sent_only_with_limit_zero(self):
        env, result = self.fetch(ns.http_response(200, headers=[("Content-Encoding", "gzip")], body=b"\x1f\x8b" * 50), limit=0, headers={"Accept-Encoding": "gzip"})
        self.assertEqual((result.status, result.body, result.error), (200, b"", ""))
        self.assertIn(b"Accept-Encoding: gzip\r\n", bytes(env.last_socket.sent))
        env, result = self.fetch(limit=1000, headers={"Accept-Encoding": "gzip"})
        self.assertEqual((result.status, result.error), (0, "UNEXPECTED_ERROR"), "본문을 읽으면서 압축을 청하는 요청은 접속 전에 거절한다")
        self.assertEqual(env.dials, [])


class SourceFlowTest(unittest.TestCase):
    """NT-35 — 응답에서 온 값이 닿는 곳의 표: `net/` 소스에서 위험한 호출(파일·경로·명령·정규식·형식·동적 실행)이 이 표의 것뿐이다. 새 호출이 생기면 이 표를 읽고 이유와 함께 더한다."""

    SINKS = {"open", "eval", "exec", "compile", "getattr", "setattr", "__import__", "os.system", "os.popen", "os.unlink", "os.remove", "os.rename", "os.replace", "os.mkdir", "os.makedirs", "os.fspath",
             "os.getenv", "os.environ.get", "shutil.rmtree", "importlib.import_module"}
    # (파일, 함수, 부르는 것) → 이유 — 응답 값은 이 가운데 어디에도 닿지 않는다(받은 글은 바이트·고른 머리글·표 안의 글로만 흐른다)
    ALLOWED = {
        ("client.py", "NetClient._read_body", "getattr"): "`OSError` 의 `errno` 숫자만 읽어 디스크 부족을 가른다 — 응답과 무관(내려받기 파일 쓰기 실패)",
        ("client.py", "_trust_env_changed", "os.environ.get"): "신뢰 저장소를 바꾸는 환경 변수 두 개의 이름(상수)을 읽는다 — 응답과 무관",
        ("client.py", "_FileSink.__init__", "os.fspath"): "호출하는 쪽이 정한 목적지 경로를 글로 바꾼다(응답이 정한 이름이 아니다)",
        ("client.py", "_FileSink.open", "open"): "호출하는 쪽이 정한 새 파일 한 곳을 만든다(`xb` — 이미 있으면 실패)",
        ("client.py", "_FileSink.discard", "os.unlink"): "성공하지 못한 내려받기 파일을 지운다(같은 목적지)",
    }

    def calls(self):
        found = {}
        for path in sorted((SRC / "net").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for owner in ast.walk(tree):
                if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    parents = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and owner in node.body]
                    qualified = f"{parents[0].name}.{owner.name}" if parents else owner.name
                    for node in ast.walk(owner):
                        if isinstance(node, ast.Call):
                            name = ast.unparse(node.func)
                            if name in self.SINKS or name.startswith("subprocess.") or name.endswith(".format"):
                                found[(path.name, qualified, name)] = node.lineno
        return found

    def test_response_data_never_reaches_paths_commands_or_format_strings(self):
        found = self.calls()
        self.assertEqual(sorted(found), sorted(self.ALLOWED), "net/ 에서 위험한 호출이 표와 다르다 — 새로 생겼거나 사라졌다. 응답 값이 닿지 않는 이유와 함께 표에 더한다")
        for key, reason in self.ALLOWED.items():
            self.assertGreater(len(reason), 15, key)

    def test_no_dynamic_format_or_regex_is_built_from_data_in_the_net_package(self):
        for path in sorted((SRC / "net").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and ast.unparse(node.func) in ("re.compile", "re.match", "re.fullmatch", "re.search", "re.sub", "re.findall", "re.split"):
                    first = node.args[0]
                    constant_name = lambda item: isinstance(item, ast.Name) and item.id.lstrip("_").isupper()          # noqa: E731 - 모듈 맨 위의 상수(대문자 이름)
                    ok = (isinstance(first, ast.Constant) or (isinstance(first, ast.Name) and (first.id == "pattern" or constant_name(first)))
                          or (isinstance(first, ast.JoinedStr) and all(constant_name(part.value) for part in first.values if isinstance(part, ast.FormattedValue))))
                    self.assertTrue(ok, f"{path.name}:{node.lineno} 정규식은 상수 글(또는 대문자 상수·호출하는 쪽의 pattern 인자)로만 만든다")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                    self.fail(f"{path.name}:{node.lineno} 글자 서식(.format) 을 쓰지 않는다")
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                    self.fail(f"{path.name}:{node.lineno} % 서식을 쓰지 않는다")


class FileDownloadTest(unittest.TestCase):
    """UPDATE 가 쓰는 `request_to_file` — 같은 관문·표·시간 규칙, 목적지는 호출하는 쪽이 정한 새 파일 한 곳, 틀리면 지운다(NT-36 — 틀린 응답은 아무것도 남기지 않는다)."""

    def table(self, **changes):
        base = endpoints.ENDPOINTS["update_check"]
        route = dataclasses.replace(base.routes[0], download=True)
        return dict(endpoints.ENDPOINTS, update_check=dataclasses.replace(base, routes=(route,), download_timeout=600.0, max_download=1024 * 1024, **changes))

    def download(self, response, dest, **kwargs):
        env = ns.Harness(self, response, switches=ns.USE_SWITCHES["update_check"])
        with mock.patch.object(client, "ENDPOINTS", self.table()), env, og.Tripwire() as wire:
            try:
                result = env.client.request_to_file("update_check", "GET", UPDATE_URL, dest, **kwargs)
            except errors.NetError as error:
                result = error
        self.assertEqual(wire.calls, [])
        return env, result

    def test_a_good_download_writes_exactly_the_body_and_reports_its_hash(self):
        body = bytes(range(256)) * 300
        digest = hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "part.bin"
            env, result = self.download(ns.http_response(200, body=body), dest, max_bytes=len(body), expected_sha256=digest)
            self.assertEqual((result.status, result.file_size, result.file_sha256, result.body), (200, len(body), digest, b""))
            self.assertEqual(dest.read_bytes(), body)
            self.assertEqual(env.usage.records()[0].received > len(body), True)

    def test_a_one_byte_download_is_a_success(self):
        """Q 재검증 참고-1(변이 Z11 — 받을 크기의 최소를 2 로 해도 초록이던 틈) — 받을 크기가 1 바이트인 내려받기도 성공이다(0 은 거절한다 — 아래 시험)."""
        digest = hashlib.sha256(b"x").hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "one.bin"
            env, result = self.download(ns.http_response(200, body=b"x"), dest, max_bytes=1, expected_sha256=digest)
            self.assertEqual((result.status, result.file_size, result.file_sha256), (200, 1, digest))
            self.assertEqual(dest.read_bytes(), b"x")

    def test_every_bad_download_leaves_no_file_behind(self):
        """NT-36 — 해시가 틀리거나 너무 크거나 짧거나 압축됐거나 상태가 나쁘거나 중간에 끊겨도 목적지에 파일이 남지 않는다."""
        body = b"abcdef" * 100
        good = hashlib.sha256(body).hexdigest()
        cases = {
            "해시가 다름": (ns.http_response(200, body=body), dict(max_bytes=10_000, expected_sha256="0" * 64), "NET_RESPONSE_INVALID"),
            "선언 크기가 큼": (ns.http_response(200, body=body), dict(max_bytes=10), "NET_RESPONSE_INVALID"),
            "길이 없이 큼": (ns.http_response(200, length=False, body=body), dict(max_bytes=10), "NET_RESPONSE_INVALID"),
            "짧게 끊김": (b"HTTP/1.1 200 OK\r\nContent-Length: 600\r\n\r\nabc", dict(max_bytes=10_000), "NET_RESPONSE_INVALID"),
            "압축됨": (ns.http_response(200, headers=[("Content-Encoding", "gzip")], body=body), dict(max_bytes=10_000), "NET_RESPONSE_INVALID"),
            "중간에 끊김": (ns.http_response(200, body=body)[:-100] + b"", dict(max_bytes=10_000, expected_sha256=good), "NET_RESPONSE_INVALID"),
        }
        for label, (response, kwargs, code) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "part.bin"
                env, result = self.download(response, dest, **kwargs)
                self.assertIsInstance(result, errors.NetError, label)
                self.assertEqual(result.code, code, label)
                self.assertFalse(dest.exists(), f"{label}: 파일이 남았다")
        for status in (404, 500):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "part.bin"
                env, result = self.download(ns.http_response(status, "x", body=b"error page"), dest, max_bytes=10_000)
                self.assertEqual((result.status, dest.exists()), (status, False))

    def test_a_204_answer_or_a_zero_size_limit_never_leaves_an_empty_file_as_a_success(self):
        """G-1(독립 검증 Q) — 204(받을 파일이 없다)나 `max_bytes=0` 은 해시를 약속했어도 빈 파일을 성공으로 남기고 해시 검사를 건너뛰던 틈이 있었다. 이제 204 는 `NET_RESPONSE_INVALID`(파일 없음)이고
        0 이하 한도는 접속 전에 거절한다. 대조: 정말 빈 파일을 빈 글의 해시와 함께 약속한 200 은 통과한다."""
        empty = hashlib.sha256(b"").hexdigest()
        no_content = b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n"
        with tempfile.TemporaryDirectory() as tmp:
            for label, kwargs in (("204 + 틀린 해시 약속", dict(max_bytes=100, expected_sha256="0" * 64)), ("204 + 빈 글의 해시 약속", dict(max_bytes=100, expected_sha256=empty)), ("204 해시 약속 없음", dict(max_bytes=100))):
                with self.subTest(label=label):
                    dest = Path(tmp) / "a.bin"
                    env, result = self.download(no_content, dest, **kwargs)
                    self.assertIsInstance(result, errors.NetError, label)
                    self.assertEqual((result.code, result.outcome_unknown), ("NET_RESPONSE_INVALID", True), label)
                    self.assertFalse(dest.exists(), f"{label}: 빈 파일이 남았다")
            for label, kwargs in (("max_bytes 0", dict(max_bytes=0, expected_sha256=empty)), ("max_bytes 0 해시 없음", dict(max_bytes=0)), ("max_bytes 음수", dict(max_bytes=-1)), ("max_bytes 불리언", dict(max_bytes=True))):
                with self.subTest(label=label):
                    dest = Path(tmp) / "b.bin"
                    env, result = self.download(ns.http_response(200, body=b""), dest, **kwargs)
                    self.assertEqual((type(result).__name__, result.code, env.dials, dest.exists()), ("NetError", "UNEXPECTED_ERROR", [], False), label)
            dest = Path(tmp) / "c.bin"
            env, result = self.download(ns.http_response(200, body=b""), dest, max_bytes=100, expected_sha256=empty)
            self.assertEqual((result.status, result.file_size, dest.exists(), dest.stat().st_size), (200, 0, True, 0), "정말 빈 파일은 빈 글의 해시와 함께일 때만 성공이다")
            dest = Path(tmp) / "d.bin"
            env, result = self.download(ns.http_response(200, body=b""), dest, max_bytes=100, expected_sha256="0" * 64)
            self.assertEqual((type(result).__name__, result.code, dest.exists()), ("NetError", "NET_RESPONSE_INVALID", False))

    def test_a_download_flood_is_cut_at_the_wire_cap_and_leaves_no_file_behind(self):
        """S 권고-1 — 내려받기도 받는 바이트 전체 상한(`max_bytes` x 2 + 머리글 몫)에서 끊기고 파일은 남지 않는다."""
        sock = WireCapTest.flood(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n5\r\nhello\r\n0\r\n", b"X-Trailer: " + b"a" * 1000 + b"\r\n")
        env = ns.Harness(self, sockets=[sock], switches=ns.USE_SWITCHES["update_check"])
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "part.bin"
            with mock.patch.object(client, "ENDPOINTS", self.table()), env, self.assertRaises(errors.NetError) as caught:
                env.client.request_to_file("update_check", "GET", UPDATE_URL, dest, max_bytes=1000)
            self.assertEqual(caught.exception.code, "NET_RESPONSE_INVALID")
            self.assertLessEqual(sock.served, client._wire_cap(1000) + 8192)
            self.assertFalse(dest.exists())

    def test_the_destination_is_chosen_by_the_caller_only_and_an_existing_file_is_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "exists.bin"
            dest.write_bytes(b"keep me")
            env, result = self.download(ns.http_response(200, body=b"new"), dest, max_bytes=100)
            self.assertEqual((type(result).__name__, result.code, env.dials), ("NetError", "UNEXPECTED_ERROR", []), "이미 있으면 접속 전에 거절")
            self.assertEqual(dest.read_bytes(), b"keep me")
            redirect = ns.http_response(200, headers=[("Content-Disposition", 'attachment; filename="../../evil.txt"')], body=b"new")
            env, result = self.download(redirect, Path(tmp) / "mine.bin", max_bytes=100)
            self.assertEqual((result.status, sorted(path.name for path in Path(tmp).iterdir())), (200, ["exists.bin", "mine.bin"]), "응답이 정한 이름은 쓰지 않는다")

    def test_a_use_without_a_download_route_refuses_to_download_before_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"])
            with env, self.assertRaises(errors.NetError) as caught:
                env.client.request_to_file("update_check", "GET", UPDATE_URL, Path(tmp) / "x.bin", max_bytes=100)
            self.assertEqual((caught.exception.code, env.dials, list(Path(tmp).iterdir())), ("UNEXPECTED_ERROR", [], []))
            env = ns.Harness(self, OK_JSON, switches=())
            with env, self.assertRaises(AppError) as caught:                                    # 스위치가 꺼져 있으면 같은 관문에서 거절
                env.client.request_to_file("update_check", "GET", UPDATE_URL, Path(tmp) / "x.bin", max_bytes=100)
            self.assertEqual((caught.exception.code, env.dials), ("NETWORK_DISABLED", []))
            for bad in ("zz", "A" * 64, "0" * 63):
                with self.subTest(sha=bad), mock.patch.object(client, "ENDPOINTS", self.table()), ns.Harness(self, OK_JSON, switches=ns.USE_SWITCHES["update_check"]) as env:
                    with self.assertRaises(errors.NetError):
                        env.client.request_to_file("update_check", "GET", UPDATE_URL, Path(tmp) / "y.bin", max_bytes=100, expected_sha256=bad)


if __name__ == "__main__":
    unittest.main()
