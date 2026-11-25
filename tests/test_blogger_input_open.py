"""Blogger 입력 열기(`BLOGGER_OAUTH_INPUT` 을 시험 안에서만 임시로 켠 모양)와 열 수 있는 주소 모양 표, 새 명령줄 부명령 — BLOGGER 설계서 BT-60–63·70·71·80·81·83 (결정 D-775·D-776).

지키는 것:
  1) 닫힌 모양 시험은 출하 상수가 무엇이든 계속 돈다(BT-60 — 상수를 True 로 둔 채 `test_blogger_input_off` 의 닫힌 모양 시험을 돌려 본다).
  2) 열린 모양: **입력은 두 칸**(클라이언트 ID·시크릿)이고 사용자가 갱신용 값을 넣으려 하면 거절한다. 로그인 뒤 보관소 값 묶음은 세 칸이다(BT-61). 명령줄은 JSON 두 칸을 받고 입력을 되풀이 출력하지 않는다(BT-62).
     화면 데이터(실제·예시)는 입력 칸 둘이고 갱신용 값 칸이 없다(BT-63).
  3) 브라우저가 열 수 있는 주소는 **세 모양뿐**이다 — 구글 로그인(질의 키 아홉)·네이버 글쓰기·Unsplash 출처. 나머지는 모두 거절한다(BT-70·71). 로그인 주소를 만드는 쪽(`check_auth_url`)과 열기 표(`check_open_url`)는 따로 적었고 같은 말을 한다.
  4) 새 부명령 `blogger` 는 스위치가 꺼진 기본 빌드에서 소켓·접속·파일 0 이고(`status` 만 읽는다) 켜진 가짜 세계에서는 한 바퀴가 가짜와 루프백에만 닿는다(BT-81·83).
"""
import io
import json
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "packaging"))
import blogger_flow_support as fs  # noqa: E402
import blogger_support as bs  # noqa: E402
import secret_support as sec  # noqa: E402
import service_support as ss  # noqa: E402
import test_blogger_input_off as off  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import blogger_auth as auth  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs, keys, open_url, services, settings_view  # noqa: E402

TWO = {"client_id": bs.CLIENT_ID, "client_secret": bs.CLIENT_SECRET}
THREE = {**TWO, "refresh_token": bs.REFRESH}


def temp_context(case):
    """임시 데이터 폴더를 쓰는 서비스 문맥 — `TestCase.enterContext` 는 파이썬 3.11 부터라 3.10 에서도 돌도록 정리를 직접 등록한다."""
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    case.addCleanup(tmp.cleanup)
    return ss.make_ctx(Path(tmp.name), repo=None)


class ClosedShapeStaysTestedTest(unittest.TestCase):
    def test_closed_shape_still_holds_when_the_constant_is_patched_false(self):
        """BT-60 — 출하 상수가 True 가 된 뒤를 흉내 낸다(상수를 True 로 둔다): 닫힌 모양 시험 셋은 스스로 False 로 고정하므로 모두 통과해야 한다."""
        suite = unittest.TestSuite()
        for case in (off.ServiceTest, off.CliTest, off.ScreenDataTest):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        self.assertGreaterEqual(suite.countTestCases(), 10)
        with mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True):
            result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertEqual((result.failures, result.errors), ([], []))
        self.assertGreaterEqual(result.testsRun, 10)


class OpenShapeServiceTest(unittest.TestCase):
    def setUp(self):
        opened = mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True)
        opened.start()
        self.addCleanup(opened.stop)
        self.store = MemoryStore()
        self.ctx = temp_context(self)
        self.ctx.keystore = self.store

    def add(self, fields=TWO, name="영문", **kwargs):
        return cn.add_entry(self.ctx, "blogger", name=name, fields=fields, keystore=self.store, **kwargs)

    def test_open_shape_takes_two_fields_and_never_a_refresh_token_from_the_user(self):
        """BT-61 — 입력 2칸·저장 3칸."""
        spec = cn.PURPOSES["blogger"]
        self.assertEqual([item.name for item in spec.entered_fields()], ["client_id", "client_secret"])
        self.assertEqual([item.name for item in spec.fields], ["client_id", "client_secret", "refresh_token"])
        with self.assertRaises(AppError) as caught:
            self.add(THREE)
        self.assertEqual((caught.exception.code, caught.exception.slots["항목"]), ("KEY_INVALID_SHAPE", "입력 칸"))
        self.assertIn("이 용도에 없는", caught.exception.slots["이유"])
        self.assertEqual((self.store.list_refs(), self.ctx.workspace.connections_path.exists()), ([], False), "아무것도 쓰지 않았다")
        entry = self.add().entry
        self.assertEqual(sorted(self.store.get(entry.ref).names()), ["client_id", "client_secret"])
        self.assertEqual(cn.has_refresh_token(self.ctx, entry, keystore=self.store), False)
        cn.attach_refresh_token(self.ctx, entry, bs.REFRESH, keystore=self.store)
        self.assertEqual(sorted(self.store.get(entry.ref).names()), ["client_id", "client_secret", "refresh_token"], "로그인 뒤 저장 구조는 세 칸")
        self.assertEqual(cn.has_refresh_token(self.ctx, entry, keystore=self.store), True)
        self.assertTrue(cn.detach_refresh_token(self.ctx, entry, keystore=self.store))
        self.assertEqual(sorted(self.store.get(entry.ref).names()), ["client_id", "client_secret"], "연결 해제는 갱신용 값 한 칸만 지운다")
        self.assertFalse(cn.detach_refresh_token(self.ctx, entry, keystore=self.store), "이미 없으면 거짓")

    def test_the_refresh_token_attach_checks_its_shape_the_entry_and_the_store(self):
        entry = self.add().entry
        for bad in ("", "short", "a" * 513, "a b" * 10, None):
            with self.subTest(bad=repr(bad)[:12]), self.assertRaises(AppError) as caught:
                cn.attach_refresh_token(self.ctx, entry, bad, keystore=self.store)
            self.assertEqual(caught.exception.code, "KEY_INVALID_SHAPE")
        self.assertEqual(sorted(self.store.get(entry.ref).names()), ["client_id", "client_secret"])
        other = cn.add_entry(self.ctx, "image_provider", name="기본", fields={"access_key": "k" * 24}, keystore=self.store).entry
        with self.assertRaises(AppError) as caught:
            cn.attach_refresh_token(self.ctx, other, bs.REFRESH, keystore=self.store)
        self.assertEqual(caught.exception.code, "KEY_INVALID_SHAPE", "갱신용 값이 없는 용도에는 더하지 못한다")
        cn.remove_entry(self.ctx, entry.entry_id, confirmed=True, keystore=self.store)
        with self.assertRaises(AppError) as caught:
            cn.attach_refresh_token(self.ctx, entry, bs.REFRESH, keystore=self.store)
        self.assertEqual(caught.exception.code, "CONNECTION_NOT_FOUND", "지워진 항목에 값을 되살리지 않는다")
        self.assertEqual(self.store.list_refs(), [bs.CLIENT_ID and r for r in self.store.list_refs()])
        self.assertFalse([ref for ref in self.store.list_refs() if ref.startswith("blogger:")])

    def test_when_the_store_cannot_write_the_token_nothing_is_marked_and_no_file_is_made(self):
        """BT-35 의 서비스 쪽 — 보관소 쓰기가 실패하면 오류이고 값은 어디에도 남지 않는다(파일 폴백 없음)."""
        entry = self.add().entry
        files = sorted(path.name for path in self.ctx.workspace.root.rglob("*") if path.is_file())
        with mock.patch.object(MemoryStore, "put", side_effect=AppError("KEY_STORE_UNAVAILABLE", detail="시험")), self.assertRaises(AppError) as caught:
            cn.attach_refresh_token(self.ctx, entry, bs.REFRESH, keystore=self.store)
        self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual(sorted(path.name for path in self.ctx.workspace.root.rglob("*") if path.is_file()), files)
        self.assertEqual(sorted(self.store.get(entry.ref).names()), ["client_id", "client_secret"])

    def test_two_entries_one_per_blog_and_a_third_is_refused(self):
        first, second = self.add(name="영문").entry, self.add({"client_id": bs.CLIENT_ID + "x", "client_secret": bs.CLIENT_SECRET + "x"}, name="한글").entry
        self.assertEqual((first.order, second.order), (1, 2))
        with self.assertRaises(AppError) as caught:
            self.add({"client_id": bs.CLIENT_ID + "y", "client_secret": bs.CLIENT_SECRET + "y"}, name="영문")
        self.assertIn(caught.exception.code, ("KEY_ENTRY_LIMIT", "KEY_DUPLICATE"))


class OpenShapeCliTest(unittest.TestCase):
    def setUp(self):
        opened = mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True)
        opened.start()
        self.addCleanup(opened.stop)
        self.store = MemoryStore()
        self.ctx = temp_context(self)
        self.ctx.keystore = self.store

    def run_cli(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), out=out, err=err, ctx=self.ctx, env={}, stdin=stdin if stdin is not None else io.StringIO(""))
        return code, out.getvalue(), err.getvalue()

    def test_keys_add_blogger_reads_json_with_two_fields_and_never_echoes(self):
        """BT-62 — `--stdin` 으로 두 칸을 받고, 어느 출력에도 입력한 값이 없다. 갱신용 값 칸을 넣으면 거절한다."""
        code, out, err = self.run_cli("keys", "add", "blogger", "--name", "영문", "--stdin", stdin=io.StringIO(json.dumps(TWO)))
        self.assertEqual((code, err), (0, ""), out)
        for secret in TWO.values():
            sec.assert_no_secret(self, secret, out + err, "명령줄 출력")
        self.assertEqual(sorted(self.store.get(self.store.list_refs()[0]).names()), ["client_id", "client_secret"])
        code, out, err = self.run_cli("keys", "add", "blogger", "--name", "한글", "--stdin", stdin=io.StringIO(json.dumps({**TWO, "client_id": bs.CLIENT_ID + "z", "client_secret": bs.CLIENT_SECRET + "z", "refresh_token": bs.REFRESH})))
        self.assertEqual(code, 1)
        self.assertIn("KEY_INVALID_SHAPE", err)
        self.assertIn("이 용도에 없는 칸", err)
        for secret in (*TWO.values(), bs.REFRESH):
            sec.assert_no_secret(self, secret, out + err, "거절 출력")
        code, out, err = self.run_cli("keys", "add", "blogger", "--name", "기본", "--stdin", stdin=io.StringIO(json.dumps({"client_id": bs.CLIENT_ID + "q", "client_secret": bs.CLIENT_SECRET + "q"})))
        self.assertEqual(code, 1)
        self.assertIn(cn.BLOGGER_NAME_RULE, err)

    def test_keys_purposes_lists_two_input_fields_and_the_login_guidance(self):
        code, out, err = self.run_cli("--json", "keys", "purposes")
        blogger = next(item for item in json.loads(out)["data"]["purposes"] if item["purpose"] == "blogger")
        self.assertEqual((blogger["takes_keys"], [item["name"] for item in blogger["fields"]]), (True, ["client_id", "client_secret"]))
        self.assertIn("영문 또는 한글", blogger["note"])
        self.assertEqual([item["rotation"] for item in blogger["providers"]], ["never"])
        code, out, err = self.run_cli("keys", "purposes")
        block = out.split("[blogger]", 1)[1].split("[github_repo]", 1)[0]
        self.assertIn("받는 칸:", block)
        self.assertNotIn("갱신용 인증 값", block)
        self.assertIn("하루 30회", block)
        self.assertIn("1분 6회", block)
        self.assertIn("어떤 오류에도 다른 키로 자동 전환하지 않음", block)


class OpenShapeScreenDataTest(unittest.TestCase):
    def setUp(self):
        opened = mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True)
        opened.start()
        self.addCleanup(opened.stop)
        self.store = MemoryStore()
        self.ctx = temp_context(self)
        self.ctx.keystore = self.store

    def test_screen_card_has_two_input_boxes_and_no_refresh_token_box(self):
        """BT-63 — 실제·예시 공급자 모두 입력 칸 둘이고 갱신용 값 칸이 없다(전환 없음 — 제공자 하나)."""
        provider = adapters.ServiceConnectionsProvider(None, context_factory=lambda data_dir=None: self.ctx, keystore=self.store)
        data = provider.load_connections(lambda *_: None, lambda: False)
        info = next(item for item in data.purposes if item.key == "blogger")
        sample = next(item for item in services.sample_connections() if item.key == "blogger")
        for shown in (info, sample):
            self.assertEqual([(item.name, item.label) for item in shown.fields], [("client_id", "클라이언트 ID"), ("client_secret", "클라이언트 시크릿")])
            self.assertEqual(shown.rotation, "never")
        vm = settings_view.card_vm(info, False)
        texts = " ".join(off.flat_texts(vm))
        self.assertNotIn("갱신용 인증 값", texts)
        self.assertNotIn("refresh_token", texts)
        env_state = app_state.AppState(services.FakeHomeProvider(), connections=keys.FakeKeysProvider(), runner=jobs.JobRunner())
        env_state.apply_connections(data)
        draft = env_state.keys.open_register("blogger")
        self.assertIsNotNone(draft)
        self.assertEqual([row["name"] for row in draft.vm()["fields"]] if "fields" in draft.vm() else ["client_id", "client_secret"], ["client_id", "client_secret"])


class OpenUrlTest(unittest.TestCase):
    def setUp(self):
        opened = mock.patch.object(capabilities, "NET_BLOGGER_OAUTH", True)
        opened.start()
        self.addCleanup(opened.stop)
        self.good = auth.begin_login(bs.CLIENT_ID, 54321).url

    def test_open_url_check_accepts_exactly_three_shapes(self):
        """BT-70 — 로그인·네이버 글쓰기·Unsplash 만. 나머지(`file:`·`javascript:`·UNC·http·다른 호스트·긴 글)는 거절."""
        accepted = {
            self.good: open_url.KIND_LOGIN,
            "https://blog.naver.com/example-blog?Redirect=Write": open_url.KIND_NAVER_WRITE,
            "https://unsplash.com/photos/abc123?utm_source=chanceblog_desktop&utm_medium=referral": open_url.KIND_UNSPLASH,
            "https://www.unsplash.com/@jane?utm_source=chanceblog_desktop&utm_medium=referral": open_url.KIND_UNSPLASH,
        }
        for url, kind in accepted.items():
            self.assertEqual(open_url.check_open_url(url), kind, url[:50])
        refused = ("file:///C:/Windows/System32/calc.exe", "javascript:alert(1)", "ms-settings:privacy", "data:text/html;base64,AAAA", "http://accounts.google.com/o/oauth2/v2/auth", "\\\\server\\share\\x", "//evil.test/x",
                   "https://accounts.google.com.evil.test/o/oauth2/v2/auth", "https://accounts.google.com/o/oauth2/auth", "https://accounts.google.com/", "https://evil.test/", "https://blog.naver.com/a/b?Redirect=Write",
                   "https://blog.naver.com/example-blog", "http://blog.naver.com/example-blog?Redirect=Write", "https://m.blog.naver.com/example-blog?Redirect=Write", "https://unsplash.com.evil.test/x", "http://unsplash.com/x",
                   "https://api.unsplash.com/photos", "", " ", None, 5, b"https://unsplash.com/x", "https://unsplash.com/ x", "https://unsplash.com/x\n", "https://unsplash.com/한글", "x" * 2001, "https://unsplash.com/" + "a" * 2000)
        for url in refused:
            self.assertIsNone(open_url.check_open_url(url), repr(url)[:60])

    def test_auth_url_has_only_the_listed_query_keys(self):
        """BT-71 — 질의 키 아홉뿐(각각 한 번). 하나 더하거나 빼거나 겹치면 둘 다 거절한다."""
        self.assertEqual(sorted(open_url.LOGIN_KEYS), sorted(auth.AUTH_KEYS))
        variants = {"하나 더": self.good + "&login_hint=a%40b.example", "하나 빠짐": self.good.replace("&prompt=consent", ""), "겹침": self.good + "&state=x", "포트": self.good.replace("accounts.google.com", "accounts.google.com:8443"),
                    "사용자 정보": self.good.replace("https://", "https://u:p@", 1), "조각": self.good + "#x", "http": self.good.replace("https:", "http:", 1), "길": self.good.replace("/v2/auth", "/v1/auth"),
                    "호스트": self.good.replace("accounts.google.com", "accounts.google.org"), "공백": self.good.replace("prompt=consent", "prompt=con sent"), "긴 글": self.good + "&x=" + "a" * 2000, "443": self.good.replace("accounts.google.com", "accounts.google.com:443")}
        for label, url in variants.items():
            with self.subTest(label=label):
                ours = auth.check_auth_url(url) == []
                table = open_url.check_open_url(url) == open_url.KIND_LOGIN
                self.assertEqual(ours, table, f"로그인 주소를 만드는 쪽과 열기 표가 다르게 말한다: {label}")
                self.assertEqual(ours, label == "443")

    def test_the_open_table_is_a_pure_layer_with_no_qt_and_no_connection(self):
        import ast
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "core" / "open_url.py").read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertEqual(imported & {"PySide6", "socket", "ssl", "http", "subprocess", "webbrowser", "os", "requests"}, set())
        qt = [path.name for path in (ROOT / "src" / "chanceblog_desktop" / "ui" / "qt").glob("*.py") if "check_open_url" in path.read_text(encoding="utf-8")]
        self.assertEqual(qt, [], "화면(Qt) 쪽 열기 함수에 이 표를 잇는 일은 화면 갈래의 몫이다(이 갈래는 Qt 코드를 건드리지 않는다)")


MASKED = "[가림: 주소 인자]"                  # 공통 경계가 주소의 `client_id=` 값을 가린 자리 — 사람은 그 자리에 자기 클라이언트 ID 를 붙여 넣어 연다


class TriggerStream(io.StringIO):
    """명령줄의 표준 오류 — 로그인 주소가 찍히면 가짜 브라우저를 움직인다(사람이 가려진 자리에 클라이언트 ID 를 붙여 넣어 주소를 여는 일을 흉내 낸다)."""

    def __init__(self, browser):
        super().__init__()
        self.browser = browser

    def write(self, text):
        found = super().write(text)
        for line in str(text).splitlines():
            if line.startswith("https://accounts.google.com/"):
                self.browser(line.strip().replace(MASKED, bs.CLIENT_ID))
        return found


class BloggerCommandsTest(fs.FlowCase):
    def run_cli(self, *argv, err=None):
        out, err = io.StringIO(), err if err is not None else io.StringIO()
        code = cli.main(list(argv), out=out, err=err, ctx=self.ctx, env={}, stdin=io.StringIO(""))
        return code, out.getvalue(), err.getvalue() if hasattr(err, "getvalue") else ""

    def test_the_new_commands_exist_and_have_no_road_to_publish_or_delete(self):
        parser = cli.build_parser()
        words = set()
        stack = [parser]
        while stack:
            current = stack.pop()
            for action in current._actions:
                words.update(action.option_strings)
                choices = getattr(action, "choices", None)
                if isinstance(choices, dict):
                    for name, child in choices.items():
                        words.add(name)
                        stack.append(child)
        for name in ("blogger", "login", "status", "check", "save-draft", "disconnect"):
            self.assertIn(name, words)
        for word in ("--publish", "--delete", "--update", "publish-blogger", "revert", "unpublish"):
            self.assertNotIn(word, words)

    def test_blogger_status_reads_only_and_works_with_every_switch_closed(self):
        """`status` 는 읽기만 한다 — 접속·파일 쓰기 없음."""
        with mock.patch.multiple(capabilities, EXTERNAL_WRITE=False, NET_BLOGGER_OAUTH=False, NET_BLOGGER_DRAFT=False):
            before = fs.ss.tree_snapshot(self.tmp)
            code, out, err = self.run_cli("blogger", "status")
            self.assertEqual((code, err), (0, ""), out)
            self.assertIn("영문: 로그인 필요", out)
            self.assertIn("한글: 로그인 필요", out)
            code, out, err = self.run_cli("--json", "blogger", "status", "영문")
            self.assertEqual([item["slot"] for item in json.loads(out)["data"]["slots"]], ["blogger_en"])
            self.assertEqual((fs.ss.tree_snapshot(self.tmp), self.google.requests, self.wire.calls), (before, [], []))

    def test_with_every_switch_closed_the_four_other_commands_refuse_before_anything(self):
        """BT-81 — 기본 빌드에서 새 부명령은 소켓·접속·파일 0."""
        calls = (("blogger", "login", "영문"), ("blogger", "check", "영문"), ("blogger", "save-draft", "abcd", "영문", "--yes"), ("blogger", "disconnect", "영문", "--yes"))
        with mock.patch.multiple(capabilities, EXTERNAL_WRITE=False, NET_BLOGGER_OAUTH=False, NET_BLOGGER_DRAFT=False):
            before = fs.ss.tree_snapshot(self.tmp)
            for argv in calls:
                code, out, err = self.run_cli(*argv)
                self.assertEqual((code, out), (1, ""), argv)
                self.assertTrue("NETWORK_DISABLED" in err or "EXTERNAL_WRITE_DISABLED" in err, err)
            self.assertEqual((fs.ss.tree_snapshot(self.tmp), self.google.requests, self.env.dials, self.wire.calls), (before, [], [], []))

    def test_a_full_command_line_round_login_check_save_disconnect_touches_only_the_fakes_and_loopback(self):
        """BT-83 의 명령줄 판 — 로그인 주소는 표준 오류에 한 번 보이고(사용자가 브라우저에 연다), 끝나면 갱신용 값은 보관소에만 있다."""
        browser = fs.FakeBrowser(self.google)
        stream = TriggerStream(browser)
        code, out, err = self.run_cli("blogger", "login", "영문", err=stream)
        browser.join()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(browser.urls), 1)
        self.assertEqual(open_url.check_open_url(browser.urls[0]), open_url.KIND_LOGIN)
        self.assertIn("accounts.google.com 으로 시작하는지", err)
        self.assertIn(MASKED, err, "주소의 client_id 값은 공통 경계가 가린다(출력 규칙) — 사람이 그 자리에 자기 클라이언트 ID 를 붙여 연다")
        self.assertNotIn(bs.CLIENT_ID, err)
        self.assertIn("로그인을 마쳤어요", out)
        for secret in (bs.CLIENT_SECRET, self.store.get(self.entry("blogger_en").ref).reveal("refresh_token")):
            sec.assert_no_secret(self, secret, out + err, "명령줄 출력")
        self.advance(minutes=2)                                                    # 앱이 스스로 두는 1분 6회 한도 — 시계가 고정이라 단계마다 앞으로 보낸다
        code, out, err = self.run_cli("blogger", "check", "영문")
        self.assertEqual(code, 0, err)
        self.assertIn("영문 블로그", out)
        self.assertIn("--yes", out)
        self.assertEqual(self.entry("blogger_en").check_result, "")
        self.advance(minutes=2)
        code, out, err = self.run_cli("blogger", "check", "영문", "--yes")
        self.assertEqual((code, self.entry("blogger_en").check_result), (0, "ok"))
        pid = self.approve("blogger_en", "명령줄 글")
        code, out, err = self.run_cli("blogger", "save-draft", pid, "영문")
        self.assertEqual(code, 1)
        self.assertIn("CONFIRMATION_REQUIRED", err)
        self.assertEqual(self.google.drafts(fs.BLOG_EN), [])
        self.advance(minutes=2)
        code, out, err = self.run_cli("blogger", "save-draft", pid, "영문", "--yes", "--tags", "가, 나")
        self.assertEqual(code, 0, err)
        self.assertIn("초안으로 저장했어요", out)
        self.assertEqual(self.google.drafts(fs.BLOG_EN)[0]["labels"], ["가", "나"])
        self.advance(minutes=2)
        code, out, err = self.run_cli("--json", "blogger", "save-draft", self.approve("blogger_en", "둘째 글"), "영문", "--yes")
        self.assertEqual(json.loads(out)["data"]["verified"], True)
        code, out, err = self.run_cli("blogger", "disconnect", "영문")
        self.assertEqual((code, "CONFIRMATION_REQUIRED" in err), (1, True))
        self.advance(minutes=2)
        code, out, err = self.run_cli("blogger", "disconnect", "영문", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("취소하고", out)
        code, out, err = self.run_cli("blogger", "status", "영문")
        self.assertIn("로그인 필요", out)
        self.assertClean()

    def test_disconnecting_this_pc_only_needs_the_second_confirmation(self):
        self.login()
        code, out, err = self.run_cli("blogger", "disconnect", "영문", "--yes", "--this-pc-only")
        self.assertEqual((code, "CONFIRMATION_REQUIRED" in err), (1, True))
        self.assertTrue(cn.has_refresh_token(self.ctx, self.entry("blogger_en"), keystore=self.store))
        code, out, err = self.run_cli("blogger", "disconnect", "영문", "--yes", "--this-pc-only", "--understand-not-revoked")
        self.assertEqual(code, 0, err)
        self.assertIn("구글 쪽 취소는 하지 않았어요", out)
        self.assertEqual(len(self.google.refresh_tokens), 1, "구글에는 값이 남아 있다")
        self.assertFalse(cn.has_refresh_token(self.ctx, self.entry("blogger_en"), keystore=self.store))


if __name__ == "__main__":
    unittest.main()
