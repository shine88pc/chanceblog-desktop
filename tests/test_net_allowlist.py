"""허용 목록·관문·등록·고지·D-415 시험(NET 설계서 NT-10–NT-16·NT-61·NT-63–NT-65, E1–E4·E10, D-735에서 D-737) — 소스 훑기로 '접속은 정확히 이 곳들뿐' 을 못박는다.

지키는 것:
  1) `http`·`ssl` 을 가져오는 파일은 `net/client.py` 하나뿐이고 `socket` 은 `net/loopback.py`(BLOGGER 갈래가 더한다 — 지금은 0곳)뿐이다. `urllib`(`parse` 말고)·`requests`·`webbrowser`·`ftplib` 등은 어디서도 가져오지 않는다(NT-10·11).
  2) TLS 를 약화하는 이름(검증 끄기·낮은 버전·암호 목록 바꾸기)이 `src/` 어디에도 없다(NT-12).
  3) 범주 표 다섯은 정확하고 서로 겹치지 않으며 접속·쓰기 범주의 이유에 관문 이름이 있다. 탐지기는 합성 소스 나무에서 새 접속 가져오기를 잡는다(NT-14·15). 허용 표가 '정확히 6곳' 이다.
  4) vendor 의 `fetch`·`urlopen` 은 앱이 한 번도 부르지 않는다 — 배포 확인은 `fetcher` 를 주입한다(NT-16).
  5) 제3자 고지는 앱이 `ssl` 을 쓰고 인증서 묶음을 싣지 않는다고 사실대로 적고(NT-61), D-415 의 거절 목록은 한 줄도 바뀌지 않았으며(NT-63) `ARCHITECTURE.md` 에 `net/` 행이 있고(NT-64) 새 오류 문구는 쉬운 말로 시작한다(NT-65).
"""
import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "packaging"))
import net_support as ns  # noqa: E402
import outgoing_support as og  # noqa: E402
import packaging_support as ps  # noqa: E402
import test_source_rules_outgoing as sro  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import CATALOG  # noqa: E402
from chanceblog_desktop.net import client, usage as usage_module  # noqa: E402
from chanceblog_desktop.publish import deploy, gitrepo  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"


def files():
    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)


def imports_of(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            found.add(node.module or "")
    return found


class ImportScopeTest(unittest.TestCase):
    def test_http_and_ssl_are_imported_only_by_net_client_and_socket_only_by_net_loopback(self):
        """NT-10 — 범주 표와 정확히 같다(`http.server` 도 최상위 이름 `http` 라서 걸린다 — 그래서 루프백 듣기는 `http.server` 를 쓰지 않는다)."""
        owners = {"http": set(), "ssl": set(), "socket": set()}
        for path in files():
            for name in imports_of(path):
                top = name.split(".")[0]
                if top in owners:
                    owners[top].add(path.relative_to(SRC).as_posix())
        self.assertEqual(owners["http"], {"net/client.py"})
        self.assertEqual(owners["ssl"], {"net/client.py"})
        self.assertEqual(owners["socket"], {key[0] for key in sro.ALLOWED_LOOPBACK if key[1] == "socket"}, "소켓은 루프백 범주 표의 파일(지금은 없음)뿐이다")
        found = sro.found_outgoing()
        self.assertEqual(sorted(key for key in found if key[1] in ("http", "ssl", "socket")), sorted(key for key in sro.ALLOWED if key[1] in ("http", "ssl", "socket")))

    def test_net_client_imports_neither_socket_nor_urllib_request_nor_subprocess(self):
        """3.11.4(1) — `net/client.py` 가 `socket`·`urllib`(`parse` 말고)·`requests`·`subprocess` 를 가져오면 빨강이다(허용 표에 있는 것은 `http`·`ssl` 뿐)."""
        names = imports_of(SRC / "net" / "client.py")
        self.assertEqual(sorted(name for name in names if name.split(".")[0] in ("socket", "_socket", "subprocess", "requests", "urllib3", "ftplib", "smtplib", "asyncio", "multiprocessing", "webbrowser", "socketserver")), [])
        self.assertEqual(sorted(name for name in names if name.split(".")[0] == "urllib"), ["urllib.parse"])
        for path in sorted((SRC / "net").glob("*.py")):
            if path.name != "client.py":
                self.assertEqual(sorted(name for name in imports_of(path) if name.split(".")[0] in ("http", "ssl", "socket", "subprocess")), [], path.name)

    def test_urllib_requests_and_friends_are_still_never_imported(self):
        """NT-11 — `urllib.request`·`requests`·`webbrowser`·`ftplib` 등은 소스 어디에도 없다."""
        banned = {"requests", "urllib3", "httplib2", "httpx", "aiohttp", "webbrowser", "ftplib", "smtplib", "telnetlib", "imaplib", "poplib", "xmlrpc", "socketserver", "asyncio", "multiprocessing", "certifi", "OpenSSL", "pycurl"}
        for path in files():
            for name in imports_of(path):
                self.assertNotIn(name.split(".")[0], banned, f"{path.relative_to(SRC)}: {name}")
                if name.split(".")[0] == "urllib":
                    self.assertEqual(name, "urllib.parse", f"{path.relative_to(SRC)}: urllib 에서는 parse 만 쓴다")
                if name == "http.server" or name.startswith("http.server"):
                    self.fail(f"{path.relative_to(SRC)}: http.server 를 쓰지 않는다")

    def test_no_tls_weakening_name_appears_anywhere_in_src(self):
        """NT-12 — C3: 검증을 끄거나 낮추는 이름이 `src/` 어디에도 없다. 읽기(`context.verify_mode`)는 되지만 **대입**은 안 된다."""
        names = {"_create_unverified_context", "_create_default_https_context", "CERT_NONE", "CERT_OPTIONAL", "PROTOCOL_SSLv23", "PROTOCOL_SSLv2", "PROTOCOL_SSLv3", "PROTOCOL_TLSv1", "PROTOCOL_TLSv1_1", "PROTOCOL_TLS",
                 "OP_NO_TLSv1_2", "OP_NO_TLSv1_3", "OP_NO_SSLv3", "set_ciphers", "MINIMUM_SUPPORTED", "SSLv3", "TLSv1", "TLSv1_1", "HAS_NEVER_CHECK_COMMON_NAME", "hostname_checks_common_name", "verify_flags"}
        problems = []
        for path in files():
            rel = path.relative_to(SRC).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                label = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else node.arg if isinstance(node, ast.keyword) else None
                if label in names:
                    problems.append((rel, getattr(node, "lineno", 0), label))
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Attribute) and target.attr in ("check_hostname", "verify_mode", "minimum_version", "maximum_version"):
                            value = ast.unparse(node.value) if getattr(node, "value", None) is not None else ""
                            if not (target.attr == "minimum_version" and value in ("ssl.TLSVersion.TLSv1_2", "ssl.TLSVersion.TLSv1_3")) or rel != "net/client.py":
                                problems.append((rel, node.lineno, f"{target.attr} = {value}"))
        self.assertEqual(problems, [], "TLS 를 약화하는 이름·대입이 있다(`minimum_version = ssl.TLSVersion.TLSv1_2` 한 곳만 허용)")
        self.assertIn("ssl.TLSVersion.TLSv1_2", (SRC / "net" / "client.py").read_text(encoding="utf-8"))

    def test_the_tls_weakening_scan_is_not_blind_it_catches_synthetic_shapes(self):
        """대조 — 위 규칙이 합성 코드의 약화 모양을 실제로 잡는다(빈 실험이 아니다)."""
        bad = ["ssl._create_unverified_context()", "ctx.check_hostname = False", "ctx.verify_mode = ssl.CERT_NONE", "ctx.minimum_version = ssl.TLSVersion.TLSv1", "ctx.set_ciphers('ALL')", "ssl.PROTOCOL_TLSv1",
               "ctx.options |= ssl.OP_NO_TLSv1_2", "ssl._create_default_https_context = ssl._create_unverified_context"]
        names = {"_create_unverified_context", "_create_default_https_context", "CERT_NONE", "CERT_OPTIONAL", "PROTOCOL_TLSv1", "OP_NO_TLSv1_2", "set_ciphers", "TLSv1"}
        for source in bad:
            with self.subTest(source=source):
                hit = False
                for node in ast.walk(ast.parse(source)):
                    label = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                    hit = hit or label in names or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr in ("check_hostname", "verify_mode", "minimum_version") for t in node.targets))
                self.assertTrue(hit, source)


def keylog_uses(source):
    """소스의 코드(독스트링·주석 말고)에서 세션 비밀 로그(`keylog`)가 이름·속성·키워드 인자·글자로 나오는 곳 → [(함수 이름, 노드 종류, 글)]."""
    tree = ast.parse(source)
    docstrings = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
                  and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    owner = {}
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(function):
                owner[id(node)] = function.name                # 바깥 함수부터 훑으므로 안쪽 함수가 나중에 덮어쓴다
    uses = []
    for node in ast.walk(tree):
        label = None
        if isinstance(node, ast.Attribute):
            label = node.attr
        elif isinstance(node, ast.Name):
            label = node.id
        elif isinstance(node, (ast.keyword, ast.arg)):
            label = node.arg
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            label = node.value
        if label and "keylog" in label.lower():
            uses.append((owner.get(id(node), "<module>"), type(node).__name__, label))
    return uses


class KeyLogScopeTest(unittest.TestCase):
    def test_session_key_logging_is_named_only_to_turn_it_off_in_the_one_client_file(self):
        """D-738(독립 검증 S 필수-1) — 세션 비밀 로그(`keylog`)는 `src/` 에서 `net/client.py` 한 파일에만 나오고, 거기서도 `_make_context` 의 끄기 한 줄(`context.keylog_filename = None`)과
        `_check_context` 의 켜진 환경 거절 한 줄(`context.keylog_filename is not None`)뿐이다. 다른 곳에서 비밀 로그 파일을 대입하거나 환경 변수 이름을 읽으면 빨개진다."""
        elsewhere = [path.relative_to(SRC).as_posix() for path in files() if re.search("keylog", path.read_text(encoding="utf-8"), re.I) and path.relative_to(SRC).as_posix() != "net/client.py"]
        self.assertEqual(elsewhere, [], "세션 비밀 로그를 다루는 코드는 접속 클라이언트 한 파일뿐이다")
        source = (SRC / "net" / "client.py").read_text(encoding="utf-8")
        self.assertEqual(sorted(keylog_uses(source)), [("_check_context", "Attribute", "keylog_filename"), ("_make_context", "Attribute", "keylog_filename")])
        tree = ast.parse(source)
        shapes = sorted(ast.unparse(node) for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.Compare)) and "keylog" in ast.unparse(node))
        self.assertEqual(shapes, ["context.keylog_filename = None", "context.keylog_filename is not None"])
        guard = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_check_context")
        self.assertIn("raise NetError('NET_TLS_FAILED'", ast.unparse(guard), "켜진 환경은 접속하기 전에 거절한다")

    def test_the_key_log_scan_is_not_blind_it_catches_synthetic_shapes(self):
        """대조 — 위 규칙이 합성 코드의 비밀 로그 모양(속성 대입·환경 변수 이름·키워드 인자·글자)을 실제로 잡는다(빈 실험이 아니다). 독스트링·주석의 낱말은 코드가 아니라 세지 않는다."""
        for source in ('ctx.keylog_filename = path', 'import os\nos.environ.get("SSLKEYLOGFILE")', 'make(keylog_filename=path)', 'KEYLOG = 1', 'x = "SSLKEYLOGFILE"', 'def f(keylog):\n    pass'):
            with self.subTest(source=source):
                self.assertTrue(keylog_uses(source), source)
        self.assertEqual(keylog_uses('def f():\n    """세션 비밀 로그(keylog)를 끈다"""\n    # keylog 설명\n    return 1'), [])


class CategoryTablesTest(unittest.TestCase):
    def test_allowed_categories_are_exact_disjoint_and_each_network_reason_names_its_gate(self):
        """NT-14 — E1–E3: 범주 표는 정확하고(1·1·2·2·0 = 6곳) 서로 겹치지 않고 합집합이 허용 표이며, 접속·쓰기 범주의 이유에 `require_…` 관문 이름이 있다."""
        sizes = {name: len(table) for name, table in sro.ALLOWED_CATEGORIES.items()}
        self.assertEqual(sizes, {"git_write": 1, "local_worker": 1, "browser": 2, "net_client": 2, "loopback": 0})
        keys = [key for table in sro.ALLOWED_CATEGORIES.values() for key in table]
        self.assertEqual(len(keys), len(set(keys)), "범주 표의 키가 겹친다")
        self.assertEqual(sorted(keys), sorted(sro.ALLOWED))
        self.assertEqual(len(sro.ALLOWED), 6)
        for table in (sro.ALLOWED_GIT_WRITE, sro.ALLOWED_NET_CLIENT, sro.ALLOWED_LOOPBACK):
            for key, reason in table.items():
                self.assertRegex(reason, r"require_[a-z_]+", key)
        for key in sro.ALLOWED_NET_CLIENT:
            self.assertIn("require_net", sro.ALLOWED_NET_CLIENT[key], key)

    def test_detector_catches_a_new_network_import_in_a_synthetic_tree(self):
        """NT-15 — 합성 소스 나무에서 새 `http`·`ssl`·`socket` 가져오기(`getattr`·`__import__` 포함)가 잡힌다 — 표에 없으니 진짜 나무라면 빨개진다."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "net").mkdir()
            (root / "net" / "client.py").write_text("import http.client\nimport ssl\n", encoding="utf-8")
            (root / "net" / "other.py").write_text("import http.client\n", encoding="utf-8")
            (root / "net" / "tls2.py").write_text("import ssl\nfrom ssl import SSLContext\n", encoding="utf-8")
            (root / "net" / "raw.py").write_text("import socket\n", encoding="utf-8")
            (root / "net" / "sneaky.py").write_text("getattr(__import__('http.client'), 'HTTPSConnection')\n", encoding="utf-8")
            (root / "net" / "dyn.py").write_text("import importlib\nimportlib.import_module('ssl')\n", encoding="utf-8")
            (root / "net" / "old.py").write_text("import urllib.request\nimport requests\n", encoding="utf-8")
            (root / "net" / "fine.py").write_text("import json\nfrom urllib.parse import urlsplit\n", encoding="utf-8")
            found = sro.found_outgoing(root=root)
            guarded = sro.found_outgoing(guarded=True, root=root)
            self.assertEqual(sorted(found), [("net/client.py", "http"), ("net/client.py", "ssl"), ("net/old.py", "requests"), ("net/old.py", "urllib"), ("net/other.py", "http"), ("net/raw.py", "socket"),
                                              ("net/tls2.py", "ssl")])
            self.assertEqual(sorted(guarded), [("net/dyn.py", "importlib.import_module"), ("net/sneaky.py", "__import__")])
            surprises = [key for key in list(found) + list(guarded) if key not in sro.ALLOWED and key not in sro.NATIVE_ALLOWED]
            self.assertEqual(sorted(surprises), [("net/dyn.py", "importlib.import_module"), ("net/old.py", "requests"), ("net/old.py", "urllib"), ("net/other.py", "http"), ("net/raw.py", "socket"),
                                                  ("net/sneaky.py", "__import__"), ("net/tls2.py", "ssl")], "표에 없는 곳은 빨개진다 — 표의 것(`net/client.py` 둘)만 통과")


class RoutingSocket(ns.FakeSocket):
    """요청 길을 보고 답을 고르는 가짜 소켓 — `posts.json` 은 404, 글 주소는 `open_after` 번째 요청부터 200(vendor 확인 도구의 가짜 요청기와 같은 흉내)."""
    seen = []

    def sendall(self, data):
        super().sendall(data)
        head = bytes(self.sent).split(b"\r\n", 1)[0].decode("ascii")
        path = head.split(" ")[1]
        RoutingSocket.seen.append(bytes(self.sent))
        is_index = path.split("?")[0].endswith("posts.json")
        posts = sum(1 for item in RoutingSocket.seen if b"KR-101652" in item.split(b"\r\n", 1)[0])
        status = 404 if is_index or posts < RoutingSocket.open_after else 200
        self.data = ns.http_response(status, "OK" if status == 200 else "Not Found", body=b"")


class VendorFetchTest(unittest.TestCase):
    def test_vendor_fetch_and_urlopen_are_never_called_by_the_app(self):
        """NT-16 — 배포 확인은 vendor 의 `fetch`·`urlopen` 을 부르지 않는다: 소스 어디에도 그 길을 부르는 코드가 없고, `fetcher` 가 없으면 이 틀의 fetcher 를 쓴다."""
        for path in files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr == "urlopen":
                    self.fail(f"{path.relative_to(SRC)}:{node.lineno} urlopen 을 부른다")
                if isinstance(node, ast.Attribute) and node.attr == "fetch" and isinstance(node.value, ast.Name) and node.value.id in ("verifier", "VERIFY", "verify_pages_deploy"):
                    self.fail(f"{path.relative_to(SRC)}:{node.lineno} vendor 의 fetch 를 부른다")
        tree = ast.parse((SRC / "publish" / "deploy.py").read_text(encoding="utf-8"))
        check = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "check_deployed")
        body = ast.unparse(check)
        self.assertIn("site_fetcher(verifier.Resp)", body, "fetcher 가 없으면 이 틀의 fetcher 를 쓴다(vendor 의 `urlopen` 으로 돌아가지 않는다)")
        self.assertLess(body.index("require_external_write"), body.index("require_net('pages_site'"), "첫 문장 옛 관문, 둘째 문장 좁은 관문")

    def check_without_a_fetcher(self, open_after, deadline):
        import urllib.request

        import test_pages_deploy as pd
        from chanceblog_desktop.errors import AppError
        RoutingSocket.seen = []
        RoutingSocket.open_after = open_after
        site = pd.Site(pd.CONFIG.replace("https://example.invalid", f"https://{gitrepo.EXPECTED_OWNER.lower()}.github.io"))
        self.addCleanup(site.cleanup)
        world = pd.FakeWorld()
        verifier = deploy._verifier()

        def refuse(*args, **kwargs):
            raise AssertionError("vendor 의 접속 길이 불렸다")

        env = ns.Harness(self, switches=("EXTERNAL_WRITE", "NET_PAGES_SITE"))
        env.template = {}
        original = env._dial

        def factory_dial(connection, address):
            env.dials.append((connection.host, address))
            sock = RoutingSocket(clock=env.clock)
            env.last_socket = sock
            return sock
        outcome = None
        before = usage_module.SESSION.records()
        with env, mock.patch.object(verifier, "fetch", refuse), mock.patch.object(urllib.request, "urlopen", refuse), mock.patch.object(client, "_dial", factory_dial), og.Tripwire() as wire:
            try:
                outcome = deploy.check_deployed(site.root, pd.KO_PATH, pd.KO_TEXT, deadline=deadline, interval=1, sleep=world.sleep, clock=world.clock, now=pd.NOW)
            except AppError as error:
                outcome = error
        self.assertEqual(wire.calls, [])
        self.assertEqual(original.__name__, "_dial")
        self.assertEqual(usage_module.SESSION.records(), before, "이 환경 밖의 전역 접속 기록에는 아무것도 새지 않는다")
        return env, outcome, pd

    def test_without_an_injected_fetcher_the_check_goes_through_the_net_client_and_never_the_vendor_urlopen(self):
        """기본 경로 — `fetcher=None` 이어도 요청은 `pages_site` 표(호스트·`cb=app` 질의·`no-cache`)를 지나 이 틀의 클라이언트로 나가고(가짜 전송기), 열리면 공개 주소를 확인한다."""
        env, outcome, pd = self.check_without_a_fetcher(open_after=1, deadline=0)
        self.assertEqual(getattr(outcome, "url", outcome), pd.KO_URL.replace("example.invalid", f"{gitrepo.EXPECTED_OWNER.lower()}.github.io"))
        hosts = {host for host, _address in env.dials}
        self.assertEqual(hosts, {f"{gitrepo.EXPECTED_OWNER.lower()}.github.io"})
        self.assertGreaterEqual(len(RoutingSocket.seen), 2, "posts.json 과 글 주소를 모두 요청했다")
        for raw in RoutingSocket.seen:
            head = raw.split(b"\r\n\r\n")[0].decode("ascii")
            self.assertRegex(head.splitlines()[0], r"\?cb=app(-[0-9]+)? HTTP/1\.1$")                 # vendor 확인 도구가 시도마다 app-<번호> 를 보낸다
            self.assertIn("Cache-Control: no-cache", head)
            self.assertIn(f"User-Agent: ChanceBlogDesktop/", head)
            self.assertNotIn("chanceblog-verify-pages", head, "vendor 도구의 User-Agent 는 나가지 않는다(앱의 고정 모양만 나간다)")
            self.assertNotRegex(head, r"(?i)cookie|referer|authorization")

    def test_the_check_that_never_opens_stays_inside_the_net_client_and_ends_with_the_documented_error(self):
        env, outcome, _pd = self.check_without_a_fetcher(open_after=10 ** 6, deadline=0)
        self.assertEqual(getattr(outcome, "code", ""), "PAGES_DEPLOY_NOT_VISIBLE")
        self.assertTrue(env.dials)
        records = env.usage.records()
        self.assertTrue(records, "요청이 이 틀의 접속 기록에 남는다(이 틀을 지났다는 증거 — 기록이 비어 있으면 아래 단언이 빈 단언이 된다)")
        self.assertTrue(all(record.use == "pages_site" for record in records))


class NarrowGateTest(unittest.TestCase):
    """NT-13(쓰기·올리기 흐름 쪽)·NT-17 — 공개 주소 확인 네 곳은 첫 문장이 옛 관문(`require_external_write`), **둘째 문장이 좁은 관문**(`require_net('pages_site', …)`)이다. `EXTERNAL_WRITE` 만 켠 채로는 전송기·하위 프로세스·가짜 backend 를 한 번도 부르기 전에 `NETWORK_DISABLED` 로 거절한다."""

    SITES = (("publish/deploy.py", "check_deployed"), ("service/backend.py", "GitPagesBackend.check_deployed"), ("service/pages_flow.py", "check_pages_deploy"), ("service/cli.py", "cmd_check_deploy"))

    def test_every_public_check_entry_point_passes_both_gates_as_its_first_two_statements(self):
        import test_external_write_gate as gate
        for rel, name in self.SITES:
            with self.subTest(entry=f"{rel}:{name}"):
                body = gate.statements(gate.function_node(gate.parse(rel), name))
                self.assertTrue(gate.is_gate_call(body[0]), f"{rel}:{name} 의 첫 문장이 옛 관문이 아니다")
                second = ast.unparse(body[1])
                self.assertTrue(second.startswith("capabilities.require_net('pages_site',"), f"{rel}:{name} 의 둘째 문장이 좁은 관문이 아니다 — {second[:70]}")

    def test_with_only_the_upper_switch_on_the_four_checks_refuse_before_any_outgoing_call_or_fake_backend_use(self):
        import io

        import service_support as ss
        from chanceblog_desktop.errors import AppError
        from chanceblog_desktop.service import cli, pages_flow
        from chanceblog_desktop.service.backend import GitPagesBackend
        from chanceblog_desktop.render.pages import PagesPost
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
            backend = ss.FakeBackend()
            ctx = ss.make_ctx(Path(tmp), backend=backend)
            project_id = ss.make_approved(ctx)
            backend.calls.clear()
            post = PagesPost(ss.KO_PATH, ss.ko_text(), "경제·일", "ko")
            spied = []
            git_backend = GitPagesBackend(git=lambda *a, **k: spied.append(a), expected_origin=ss.LOCAL_ORIGIN)
            cases = {"check_deployed": lambda: deploy.check_deployed(Path(tmp) / "chanceblog", post.path, post.text), "GitPagesBackend.check_deployed": lambda: git_backend.check_deployed(Path(tmp), post, ss.NOW, 1, 1),
                     "check_pages_deploy": lambda: pages_flow.check_pages_deploy(ctx, project_id)}
            for label, call in cases.items():
                with self.subTest(label=label), og.Tripwire() as wire:
                    with self.assertRaises(AppError) as caught:
                        call()
                    self.assertEqual((caught.exception.code, wire.calls), ("NETWORK_DISABLED", []), label)
            out, err = io.StringIO(), io.StringIO()
            with og.Tripwire() as wire:
                code = cli.main(["check-deploy", project_id], out=out, err=err, ctx=ctx, env={})
            self.assertEqual((code, wire.calls, out.getvalue()), (1, [], ""))
            self.assertIn("NETWORK_DISABLED", err.getvalue())
            self.assertEqual((backend.calls, spied), ([], []), "가짜 backend·가짜 git 은 한 번도 불리지 않았다")
        with mock.patch.object(capabilities, "EXTERNAL_WRITE", True), mock.patch.object(capabilities, "NET_PAGES_SITE", True), self.assertRaises(Exception) as caught:
            deploy.check_deployed(Path("not-a-repo"), "_posts/2026-11-01-x.md", "x")                 # 두 스위치가 모두 켜지면 관문은 지나고 그 다음의 일(저장소 읽기)에서 멈춘다
        self.assertNotEqual(getattr(caught.exception, "code", ""), "NETWORK_DISABLED")


class RegistrationScopeTest(unittest.TestCase):
    def test_no_code_in_src_registers_an_adapter_outside_the_one_wiring_file_and_every_call_sits_in_a_switch_if(self):
        """E4 — `register` 호출은 `service/wiring.py` 한 곳뿐이고 그 호출은 스위치를 읽는 함수(`capabilities.…_enabled()`)의 `if` 안에 있다."""
        calls = []
        for path in files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and ast.unparse(node.func) in ("external.register", "register") and path.name != "external.py":
                    guarded, cursor = False, node
                    while cursor in parents:
                        cursor = parents[cursor]
                        if isinstance(cursor, ast.If) and re.search(r"capabilities\.\w+_enabled\(\)", ast.unparse(cursor.test)):
                            guarded = True
                    calls.append((path.relative_to(SRC).as_posix(), guarded))
        self.assertEqual(calls, [("service/wiring.py", True), ("service/wiring.py", True)], "어댑터를 꽂는 곳은 wiring.py 의 스위치 `if` 안 두 줄뿐이다")

    def test_net_client_objects_are_made_in_one_known_place_for_now(self):
        """NT-18(3.11.4 의 4) — 접속 클라이언트 객체(`NetClient(…)`)를 만드는 곳이 `src/` 에 표의 곳뿐이다. 지금은 공개 주소 확인용 fetcher(`net/site.py::site_fetcher`)의 기본값 한 곳이고,
        그곳은 `check_deployed` 의 두 관문(옛 관문 + `require_net('pages_site')`) 뒤에서만 불린다. PUBPR·BLOGGER 갈래가 자기 어댑터 공장의 한 줄을 이 표에 더한다."""
        found = []
        for path in files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "NetClient":
                    function = next((outer.name for outer in ast.walk(tree) if isinstance(outer, ast.FunctionDef) and node in ast.walk(outer)), "")
                    found.append((path.relative_to(SRC).as_posix(), function))
        self.assertEqual(sorted(set(found)), [("net/site.py", "site_fetcher")], "NetClient 를 만드는 곳이 표와 다르다 — 새 곳은 어댑터 공장 안이어야 하고 이 표에 이유와 함께 더한다")
        callers = [path.relative_to(SRC).as_posix() for path in files() if "site_fetcher(" in path.read_text(encoding="utf-8") and path.name != "site.py"]
        self.assertEqual(callers, ["publish/deploy.py"], "site_fetcher 를 부르는 곳은 두 관문을 지난 공개 주소 확인뿐이다")

    def test_the_scan_catches_an_unguarded_register_in_a_synthetic_file(self):
        source = "from . import external\ndef go():\n    external.register('pages_git', lambda **p: 1)\n"
        tree = ast.parse(source)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "external.register")
        cursor, guarded = call, False
        while cursor in parents:
            cursor = parents[cursor]
            guarded = guarded or isinstance(cursor, ast.If)
        self.assertFalse(guarded)


class NoticesAndPackageTest(unittest.TestCase):
    def notices(self):
        packages = [{"name": "PySide6_Essentials", "version": "6.0", "license": "LGPL", "role": "runtime"}, {"name": "shiboken6", "version": "6.0", "license": "LGPL", "role": "runtime"}]
        return ps.build_package.notices_text("1.0.0", packages, "0" * 40)

    def test_notices_say_the_app_uses_ssl_and_ships_no_ca_bundle(self):
        """NT-61 — E10: 제3자 고지의 OpenSSL 줄이 사실대로다 — 앱의 접속 틀이 `ssl` 을 쓰고 인증서 묶음은 싣지 않으며 Qt 네트워크는 뺐다. 옛 '화면은 쓰지 않음' 은 없다."""
        text = self.notices()
        row = next(line for line in text.splitlines() if line.startswith("| OpenSSL 3"))
        self.assertIn("접속 틀(`net/`)이 보안 접속(TLS)에 쓴다", row)
        self.assertIn("인증서 묶음(CA bundle)을 싣지 않는다", row)
        self.assertIn("윈도 신뢰 저장소", row)
        self.assertNotIn("화면은 쓰지 않음", text)
        self.assertIn("QtNetwork", row)
        self.assertIn("들어 있으면 빌드가 거절합니다", row, "D-415 의 거절 안내는 그대로다")
        doc = (ROOT / "docs" / "PACKAGE.md").read_text(encoding="utf-8")
        self.assertIn("접속 틀(`net/`)이 보안 접속(TLS)에 쓴다", doc)
        self.assertNotIn("화면은 쓰지 않음", doc)

    def test_d415_refusal_list_is_unchanged(self):
        """NT-63 — Qt 네트워크 제외·거절 목록은 한 줄도 바뀌지 않았다(이 틀은 Qt 를 쓰지 않고 파이썬 자신의 OpenSSL 만 쓴다)."""
        build = ps.build_package
        self.assertEqual(build.EXCLUDED_MODULES, ("PySide6.QtNetwork",))
        self.assertEqual(build.UNWANTED_BUNDLED, ("libssl-3-x64.dll", "libcrypto-3-x64.dll", "PySide6/QtNetwork.pyd", "PySide6/plugins/tls", "PySide6/plugins/networkinformation"))
        self.assertTrue(build.OPENSSL_X64.fullmatch("libssl-3-x64.dll"))
        self.assertTrue(build.OPENSSL_X64.fullmatch("LIBCRYPTO-1_1-x64.DLL"))
        self.assertFalse(build.OPENSSL_X64.fullmatch("libssl-3.dll"), "파이썬 자신의 OpenSSL 은 거절하지 않는다")
        self.assertFalse(build.OPENSSL_X64.fullmatch("libcrypto-3.dll"))
        for path in sorted((SRC / "net").glob("*.py")):
            self.assertFalse([name for name in imports_of(path) if "PySide6" in name or "Qt" in name], f"{path.name}: 접속 틀은 Qt 를 쓰지 않는다")

    def test_net_package_is_documented_in_architecture(self):
        """NT-64 — `ARCHITECTURE.md` §5 에 `net/` 행이 있다(Q6 — 흩어 두지 않고 새 패키지)."""
        text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^\| `net/` \|", "ARCHITECTURE.md 에 `net/` 행이 없다")
        self.assertIn("`net/client.py`", text)
        self.assertIn("`service/wiring.py`", text)

    def test_new_troubleshooting_rows_match_the_catalog_and_start_with_easy_words(self):
        """NT-65 — 새 오류 코드 넷이 표와 카탈로그에 같게 있고, 하실 일 앞부분이 쉬운 말이며(명령·옵션·파일 이름 없음), 날짜·시간 안내가 있다."""
        doc = (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
        for code in ("NETWORK_DISABLED", "NET_TLS_FAILED", "NET_RESPONSE_INVALID", "NET_COOLDOWN"):
            self.assertIn(f"| `{code}` |", doc, code)
            info = CATALOG[code]
            card = info.action.split("명령줄·개발자 안내:")[0]
            self.assertTrue(card.strip(), code)
            for banned in ("--", "python", "터미널", ".json", ".log", "git ", "명령"):
                self.assertNotIn(banned, info.message + card, f"{code}: 카드 글에 개발 말이 있다 — {banned}")
        self.assertIn("날짜와 시간", CATALOG["NET_TLS_FAILED"].action)
        self.assertIn("환경 변수", CATALOG["NET_TLS_FAILED"].action.split("명령줄·개발자 안내:")[1])
        self.assertEqual(CATALOG["NET_COOLDOWN"].slots, ("재시도 가능 시각",))
        self.assertEqual(CATALOG["NETWORK_DISABLED"].slots, ("작업",))
        self.assertEqual(CATALOG["NET_RESPONSE_INVALID"].slots, ("이유",))
        self.assertEqual((CATALOG["NET_TLS_FAILED"].retry_kind, CATALOG["NET_COOLDOWN"].retry_kind, CATALOG["NETWORK_DISABLED"].retry_kind), ("after_user", "after_user", "no"))


if __name__ == "__main__":
    unittest.main()
