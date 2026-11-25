"""Blogger 로그인의 요청 모양·응답 검사(`publish/blogger_auth.py`) 시험 — BLOGGER 설계서 BT-13·20–22·30·31·36 과 비밀 다루기(결정 D-772).

접속 틀의 진짜 클라이언트(`NetClient`)를 쓰되 소켓은 열리지 않는다 — 전송 자리에 **요청 모양을 엄격히 검사하는 가짜 구글**(`blogger_support.FakeGoogle`)을 끼운다.
가짜가 여섯 모양 밖의 요청·약속에 없는 머리글·본문 칸을 받으면 `violations` 에 적고 시험이 그것을 단언한다. 가짜 비밀은 `CANARY_` 로 시작하는 조립한 글이다.
"""
import copy
import pickle
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blogger_support as bs  # noqa: E402
import net_support as ns  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net.errors import NetError  # noqa: E402
from chanceblog_desktop.publish import blogger_auth as auth  # noqa: E402

PORT = 54321
NOW = 1000.0
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def visible(error):
    """오류가 어디서든 보여 줄 수 있는 모든 글."""
    shown = error.rendered()
    return " ".join([error.code, repr(error.slots), str(error.detail), shown.message, shown.action, repr(error), str(error), repr(getattr(error, "__dict__", {}))])


class World(unittest.TestCase):
    """가짜 구글 + 진짜 접속 틀(가짜 전송기). `self.client` 로 부른다."""

    switches = bs.LOGIN_SWITCHES

    def setUp(self):
        self.google = bs.FakeGoogle()
        self.env = bs.GoogleHarness(self, self.google, switches=self.switches)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.client = self.env.client

    def code(self):
        verifier = auth.new_verifier()
        redirect = auth.redirect_uri_for(PORT)
        return verifier, redirect, self.google.issue_code(auth.challenge_of(verifier), redirect)

    def exchange(self):
        verifier, redirect, code = self.code()
        return auth.exchange_code(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, code, verifier, redirect, now=NOW)

    def assertClean(self):
        self.assertEqual(self.google.violations, [], "가짜 서버가 약속과 다른 요청을 받았다")

    def reset_cooldown(self):
        """같은 용도가 연속 세 번 실패하면 앱이 5분 쉰다(`NET_COOLDOWN`) — 한 시험에서 여러 실패를 차례로 보려면 쉬는 상태를 비운다."""
        self.env.usage._state.clear()


class AuthorizationRequestTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(capabilities, "NET_BLOGGER_OAUTH", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_authorization_request_has_s256_pkce_state_loopback_redirect_and_one_scope(self):
        """BT-20 — 3.6 의 매개변수 표 그대로: 아홉 키뿐 · `S256` · 루프백 http 주소 · 범위 하나 · `login_hint`·`include_granted_scopes` 없음."""
        request = auth.begin_login(bs.CLIENT_ID, PORT)
        parts = urlsplit(request.url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True))
        self.assertEqual((parts.scheme, parts.netloc, parts.path, parts.fragment, parts.port), ("https", "accounts.google.com", "/o/oauth2/v2/auth", "", None))
        self.assertEqual(sorted(query), sorted(("client_id", "redirect_uri", "response_type", "scope", "state", "code_challenge", "code_challenge_method", "access_type", "prompt")))
        self.assertEqual(len(parse_qsl(parts.query)), 9, "같은 키가 두 번 나오지 않는다")
        self.assertEqual(query["client_id"], bs.CLIENT_ID)
        self.assertEqual(query["redirect_uri"], f"http://127.0.0.1:{PORT}/callback")
        self.assertEqual((query["response_type"], query["scope"], query["code_challenge_method"], query["access_type"], query["prompt"]), ("code", bs.SCOPE, "S256", "offline", "consent"))
        self.assertEqual(query["state"], request.state)
        self.assertEqual(query["code_challenge"], auth.challenge_of(request.verifier.reveal()))
        for forbidden in ("login_hint", "include_granted_scopes", "plain", "nonce", "response_mode"):
            self.assertNotIn(forbidden, request.url)
        self.assertEqual(auth.check_auth_url(request.url), [])
        self.assertLessEqual(len(request.url), 2000)

    def test_the_login_request_hides_its_values_in_every_text_form(self):
        request = auth.begin_login(bs.CLIENT_ID, PORT)
        for shown in (repr(request), str(request), f"{request}", repr(request.verifier), str(request.verifier), f"{request.verifier}"):
            self.assertNotIn(request.state, shown)
            self.assertNotIn(request.verifier.reveal(), shown)
            self.assertNotIn(request.url, shown)

    def test_the_check_rejects_every_deviation_from_the_one_allowed_shape(self):
        good = auth.begin_login(bs.CLIENT_ID, PORT).url
        keys = parse_qsl(urlsplit(good).query)
        deviations = {
            "http": good.replace("https://", "http://", 1), "다른 호스트": good.replace("accounts.google.com", "accounts.google.com.evil.test"), "닮은 호스트": good.replace("accounts.google.com", "accounts-google.com"),
            "포트": good.replace("accounts.google.com", "accounts.google.com:8443"), "사용자 정보": good.replace("https://", "https://user:pw@", 1), "다른 길": good.replace("/o/oauth2/v2/auth", "/o/oauth2/auth"),
            "조각": good + "#x", "키 하나 더": good + "&login_hint=a%40b.example", "키 하나 빠짐": good.replace("&prompt=consent", ""), "같은 키 둘": good + "&prompt=consent",
            "공백": good.replace("&prompt", "%20&prompt").replace("%20", " "), "너무 김": good + "&x=" + "a" * 2000, "빈 글": "", "글이 아님": None, "비 ASCII": good.replace("S256", "S25６"),
            "javascript": "javascript:alert(1)", "file": "file:///C:/x", "대문자 호스트도 같은 호스트가 아니면": good.replace("accounts.google.com", "ACCOUNTS.google.com.evil"),
        }
        for label, url in deviations.items():
            with self.subTest(label=label):
                self.assertTrue(auth.check_auth_url(url), f"{label}: 모양 검사를 지나갔다")
        self.assertEqual(len(keys), 9)
        self.assertEqual(auth.check_auth_url(good.replace("accounts.google.com", "accounts.google.com:443")), [], "443 은 같은 주소다")

    def test_verifier_is_32_random_bytes_base64url_and_never_reused(self):
        """BT-21 — 43자·로그인마다 새것·RFC 7636 의 `S256` 예시 값과 같다."""
        with mock.patch.object(auth.secrets, "token_urlsafe", wraps=auth.secrets.token_urlsafe) as spy:
            first, second = auth.begin_login(bs.CLIENT_ID, PORT), auth.begin_login(bs.CLIENT_ID, PORT)
        self.assertEqual([call.args for call in spy.call_args_list], [(32,)] * 4, "검증기 둘·state 둘, 모두 무작위 32바이트")
        for request in (first, second):
            self.assertRegex(request.verifier.reveal(), r"^[A-Za-z0-9_-]{43}$")
            self.assertRegex(request.state, r"^[A-Za-z0-9_-]{43}$")
        self.assertNotEqual(first.verifier.reveal(), second.verifier.reveal())
        self.assertNotEqual(first.state, second.state)
        self.assertEqual(auth.challenge_of(RFC_VERIFIER), RFC_CHALLENGE)
        for bad in ("short", "a" * 129, "a b" * 20, "", None, "한글" * 30):
            with self.assertRaises(ValueError):
                auth.challenge_of(bad)

    def test_a_missing_or_odd_client_id_or_port_is_refused_before_a_url_is_made(self):
        for client_id in ("", None, "a b", "a\nb", "x" * 600, "http://x"):
            with self.subTest(client_id=repr(client_id)[:20]), self.assertRaises(AppError) as caught:
                auth.build_auth_url(client_id, PORT, "s" * 43, "c" * 43)
            self.assertEqual(caught.exception.code, "BLOGGER_LOGIN_FAILED")
        for port in (0, -1, 70000, True, "80", None):
            with self.subTest(port=port), self.assertRaises(ValueError):
                auth.redirect_uri_for(port)


class ExchangeTest(World):
    def test_the_exchange_sends_exactly_the_planned_form_and_returns_hidden_tokens(self):
        tokens = self.exchange()
        self.assertClean()
        self.assertEqual(self.google.summaries(), ["POST oauth2.googleapis.com/token"])
        request = self.google.requests[0]
        self.assertEqual(set(request.form()), {"client_id", "client_secret", "code", "code_verifier", "grant_type", "redirect_uri"})
        self.assertEqual(request.form()["grant_type"], "authorization_code")
        self.assertNotIn("authorization", request.headers, "토큰 서버 요청에는 Authorization 이 없다")
        self.assertEqual(request.headers["content-type"], "application/x-www-form-urlencoded")
        self.assertTrue(tokens.refresh.reveal().startswith("1//0"))
        self.assertTrue(tokens.access.usable(NOW) and not tokens.access.usable(NOW + 3600))
        self.assertAlmostEqual(tokens.access.valid_until, NOW + 55 * 60, places=3, msg="3,599초에서 60초를 빼도 55분보다 길어서 55분으로 자른다")
        for secret in (tokens.access.reveal(), tokens.refresh.reveal()):
            for shown in (repr(tokens), str(tokens), f"{tokens}", repr(tokens.access), repr(tokens.refresh)):
                self.assertNotIn(secret, shown)

    def test_access_token_validity_is_expires_in_minus_a_minute_and_at_most_fifty_five_minutes(self):
        short = auth._access_from({"token_type": "Bearer", "access_token": "ya29." + "a" * 30, "expires_in": 120}, NOW)
        self.assertEqual(short.valid_until, NOW + 60)
        long = auth._access_from({"token_type": "bearer", "access_token": "ya29." + "a" * 30, "expires_in": 7200}, NOW)
        self.assertEqual(long.valid_until, NOW + 55 * 60, "최대 55분")

    def test_token_response_scope_and_type_and_shapes_are_checked(self):
        """BT-13 — 범위가 줄거나 늘거나 없으면 거절하고, `token_type`·`expires_in`·`access_token`·`refresh_token` 의 모양이 틀리면 거절한다. 어느 쪽도 토큰을 돌려주지 않는다."""
        scope_cases = {"scope_narrow": "허용한 범위가 달라요", "scope_wide": "허용한 범위가 달라요", "scope_missing": "허용한 범위가 달라요", "no_refresh": "로그인 값을 받지 못했어요"}
        for mode, reason in scope_cases.items():
            with self.subTest(mode=mode):
                self.google.mode["token"] = mode
                with self.assertRaises(AppError) as caught:
                    self.exchange()
                self.assertEqual((caught.exception.code, caught.exception.slots), ("BLOGGER_LOGIN_FAILED", {"이유": reason}))
        for mode in ("bad_type", "bad_expires", "tiny_expires", "huge_expires", "short_access", "long_access", "space_access", "short_refresh", "long_refresh"):
            with self.subTest(mode=mode):
                self.google.mode["token"] = mode
                with self.assertRaises(NetError) as caught:
                    self.exchange()
                self.assertEqual(caught.exception.code, "NET_RESPONSE_INVALID", mode)
                self.assertNotIn("ya29", visible(caught.exception))
        self.assertClean()

    def test_a_response_without_a_refresh_token_is_a_login_failure_and_never_a_connected_state(self):
        """BT-31 — 접근 토큰만으로 '연결됨' 이 되지 않는다."""
        self.google.mode["token"] = "no_refresh"
        with self.assertRaises(AppError) as caught:
            self.exchange()
        self.assertEqual(caught.exception.slots, {"이유": auth.REASON_NO_VALUE})

    def test_exchange_failures_map_to_codes(self):
        """BT-30 — `invalid_grant` → 로그인 코드가 맞지 않음 · `invalid_client` → KEY_AUTH_FAILED · 서버 오류·한도·네트워크."""
        self.google.mode["token"] = "invalid_grant"
        with self.assertRaises(AppError) as caught:
            self.exchange()
        self.assertEqual((caught.exception.code, caught.exception.slots), ("BLOGGER_LOGIN_FAILED", {"이유": auth.REASON_BAD_CODE}))
        self.google.mode["token"] = "invalid_client"
        with self.assertRaises(NetError) as caught:
            self.exchange()
        self.assertEqual(caught.exception.code, "KEY_AUTH_FAILED")
        for status, code in ((503, "BLOGGER_SERVER_ERROR"), (500, "BLOGGER_SERVER_ERROR"), (429, "API_RATE_LIMITED")):
            self.google.mode["token"] = f"status:{status}"
            self.reset_cooldown()
            with self.subTest(status=status), self.assertRaises(NetError) as caught:
                self.exchange()
            self.assertEqual(caught.exception.code, code)
        self.google.mode["token"] = "ok"
        self.reset_cooldown()
        self.google.push("token", bs.DISCONNECT)
        with self.assertRaises(NetError) as caught:
            self.exchange()
        self.assertEqual(caught.exception.code, "NETWORK_OFFLINE")
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertClean()

    def test_a_code_or_verifier_that_does_not_match_is_an_invalid_grant(self):
        verifier, redirect, code = self.code()
        with self.assertRaises(AppError) as caught:
            auth.exchange_code(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, code, auth.new_verifier(), redirect, now=NOW)         # 남의 검증기 — PKCE 가 막는다
        self.assertEqual(caught.exception.slots, {"이유": auth.REASON_BAD_CODE})
        verifier, redirect, code = self.code()
        with self.assertRaises(AppError):
            auth.exchange_code(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, code, verifier, auth.redirect_uri_for(1111), now=NOW)  # 다른 돌아올 주소
        verifier, redirect, code = self.code()
        auth.exchange_code(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, code, verifier, redirect, now=NOW)
        with self.assertRaises(AppError):
            auth.exchange_code(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, code, verifier, redirect, now=NOW)                    # 코드는 한 번만 쓸 수 있다

    def test_no_error_or_text_carries_the_server_message_the_tokens_the_secret_or_the_code(self):
        verifier, redirect, code = self.code()
        modes = ("invalid_grant", "invalid_client", "status:503", "status:429", "scope_narrow", "no_refresh", "bad_type")
        secrets = (bs.CLIENT_SECRET, code, verifier, "CANARY_SERVER_DESCRIPTION", "CANARY_SERVER_MESSAGE", bs.REFRESH)
        for mode in modes:
            self.google.mode["token"] = mode
            self.reset_cooldown()
            self.google.codes[code] = {"challenge": auth.challenge_of(verifier), "redirect_uri": redirect, "client_id": bs.CLIENT_ID}
            with self.subTest(mode=mode), self.assertRaises(AppError) as caught:
                auth.exchange_code(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, code, verifier, redirect, now=NOW)
            text = visible(caught.exception)
            for secret in secrets:
                self.assertNotIn(secret, text, mode)
        records = " ".join(repr(record) for record in self.env.usage.records())
        for secret in secrets:
            self.assertNotIn(secret, records, "접속 기록에도 없다")


class RefreshTest(World):
    def test_refresh_sends_four_fields_and_returns_a_hidden_access_token(self):
        refresh = self.google.grant()
        token = auth.refresh_access_token(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, refresh, now=NOW)
        self.assertClean()
        request = self.google.requests[0]
        self.assertEqual(request.form(), {"client_id": bs.CLIENT_ID, "client_secret": bs.CLIENT_SECRET, "grant_type": "refresh_token", "refresh_token": refresh})
        self.assertNotIn("authorization", request.headers)
        for shown in (repr(token), str(token), f"{token}", "%s" % (token,)):
            self.assertNotIn(token.reveal(), shown)
        self.assertTrue(token.usable(NOW))

    def test_a_refresh_answer_without_scope_is_accepted_but_a_different_scope_is_not(self):
        refresh = self.google.grant()
        self.google.mode["refresh"] = "scope_missing"
        auth.refresh_access_token(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, refresh, now=NOW)
        for mode in ("scope_narrow", "scope_wide"):
            self.google.mode["refresh"] = mode
            with self.subTest(mode=mode), self.assertRaises(AppError) as caught:
                auth.refresh_access_token(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, refresh, now=NOW)
            self.assertEqual(caught.exception.code, "BLOGGER_LOGIN_FAILED")

    def test_a_refused_refresh_token_means_login_again_and_nothing_logs_in_by_itself(self):
        """B-15 — 갱신이 `invalid_grant` 면 `BLOGGER_AUTH_EXPIRED`. 자동 재로그인은 없다(요청은 갱신 한 번뿐)."""
        with self.assertRaises(NetError) as caught:
            auth.refresh_access_token(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, bs.REFRESH, now=NOW)         # 서버가 모르는 갱신 토큰
        self.assertEqual(caught.exception.code, "BLOGGER_AUTH_EXPIRED")
        self.assertEqual(self.google.summaries(), ["POST oauth2.googleapis.com/token"])
        self.assertNotIn(bs.REFRESH, visible(caught.exception))

    def test_other_refresh_failures_map_to_codes(self):
        refresh = self.google.grant()
        table = {"invalid_client": "KEY_AUTH_FAILED", "status:503": "BLOGGER_SERVER_ERROR", "status:429": "API_RATE_LIMITED", "invalid_grant": "BLOGGER_AUTH_EXPIRED"}
        for mode, code in table.items():
            self.google.mode["refresh"] = mode
            self.reset_cooldown()
            with self.subTest(mode=mode), self.assertRaises(NetError) as caught:
                auth.refresh_access_token(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, refresh, now=NOW)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("CANARY_SERVER", visible(caught.exception))

    def test_the_wrong_client_secret_is_refused_by_the_server_as_a_key_failure(self):
        refresh = self.google.grant()
        with self.assertRaises(NetError) as caught:
            auth.refresh_access_token(self.client, bs.CLIENT_ID, "GOCSPX-" + "CANARY_WRONG_SECRET" + "x" * 8, refresh, now=NOW)
        self.assertEqual(caught.exception.code, "KEY_AUTH_FAILED")


class RevokeTest(World):
    def test_revoke_sends_only_the_token_and_treats_200_and_400_as_done(self):
        refresh = self.google.grant()
        self.assertTrue(auth.revoke_token(self.client, refresh))
        self.assertEqual(self.google.requests[0].form(), {"token": refresh})
        self.assertNotIn("authorization", self.google.requests[0].headers)
        self.assertNotIn(refresh, self.google.refresh_tokens)
        self.assertTrue(auth.revoke_token(self.client, refresh), "이미 무효인 토큰(400)도 성공이다")
        self.assertClean()

    def test_revoke_failures_are_errors_not_successes(self):
        refresh = self.google.grant()
        for mode, code in (("status:503", "BLOGGER_SERVER_ERROR"), ("status:429", "API_RATE_LIMITED"), ("status:404", "NET_RESPONSE_INVALID")):
            self.google.mode["revoke"] = mode
            self.reset_cooldown()
            with self.subTest(mode=mode), self.assertRaises(NetError) as caught:
                auth.revoke_token(self.client, refresh)
            self.assertEqual(caught.exception.code, code)
        self.assertIn(refresh, self.google.refresh_tokens, "실패하면 서버 쪽 토큰은 그대로다")
        self.google.mode["revoke"] = "ok"
        self.reset_cooldown()
        self.google.push("revoke", bs.DISCONNECT)
        with self.assertRaises(NetError) as caught:
            auth.revoke_token(self.client, refresh)
        self.assertEqual(caught.exception.code, "NETWORK_OFFLINE")


class SecretObjectTest(unittest.TestCase):
    def test_a_secret_hides_itself_in_every_text_form_and_refuses_pickling_copying_and_changes(self):
        """BT-36 — `repr`·`str`·`format`·% 서식에 값이 없다."""
        secret = auth.Secret("CANARY_" + "SECRET_VALUE_" + "0042")
        token = auth.AccessToken("ya29." + "CANARY_TOKEN_" + "0042", 100.0)
        for item in (secret, token):
            for shown in (repr(item), str(item), f"{item}", "%s" % (item,), "%r" % (item,), format(item, ">40"), repr([item]), repr({"k": item}), repr((item,))):
                self.assertNotIn("CANARY_", shown)
            with self.assertRaises(TypeError):
                pickle.dumps(item)
            with self.assertRaises(TypeError):
                copy.copy(item)
            with self.assertRaises(TypeError):
                copy.deepcopy(item)
            with self.assertRaises(AttributeError):
                item._value = "x"
            with self.assertRaises(AttributeError):
                del item._value
            self.assertEqual(item, item)
            self.assertNotEqual(item, object())
        self.assertEqual(secret.reveal(), "CANARY_SECRET_VALUE_0042")
        self.assertFalse(token.usable(100.0))
        self.assertTrue(token.usable(99.9))
        with self.assertRaises(ValueError):
            auth.Secret("")
        with self.assertRaises(ValueError):
            auth.Secret(5)

    def test_two_secrets_with_the_same_value_are_not_equal_so_a_value_cannot_be_probed_by_comparison(self):
        self.assertNotEqual(auth.Secret("CANARY_SAME_VALUE_0042"), auth.Secret("CANARY_SAME_VALUE_0042"))


class GateTest(World):
    switches = ()

    def test_with_the_switch_off_every_public_function_refuses_before_any_connection(self):
        """BT-80 의 하위 층 — 스위치가 꺼져 있으면 요청 본문을 만들기 전에 거절한다."""
        calls = (lambda: auth.begin_login(bs.CLIENT_ID, PORT), lambda: auth.exchange_code(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, bs.CODE, "v" * 43, "http://127.0.0.1:1/callback", now=NOW),
                 lambda: auth.refresh_access_token(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, bs.REFRESH, now=NOW), lambda: auth.revoke_token(self.client, bs.REFRESH))
        for call in calls:
            with self.subTest(call=call), self.assertRaises(AppError) as caught:
                call()
            self.assertEqual(caught.exception.code, "NETWORK_DISABLED")
        self.assertEqual((self.env.dials, self.google.requests), ([], []))

    def test_the_draft_switch_without_the_login_switch_is_still_closed(self):
        with mock.patch.object(capabilities, "NET_BLOGGER_DRAFT", True), mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
            with self.assertRaises(AppError) as caught:
                auth.begin_login(bs.CLIENT_ID, PORT)
        self.assertEqual(caught.exception.code, "NETWORK_DISABLED")


class CodeDoesNotImportConnectionModulesTest(unittest.TestCase):
    def test_the_auth_module_has_no_socket_http_or_ssl_of_its_own(self):
        import ast
        tree = ast.parse((HERE.parent / "src" / "chanceblog_desktop" / "publish" / "blogger_auth.py").read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertEqual(imported & {"socket", "ssl", "http", "urllib3", "requests", "subprocess", "webbrowser"}, set())
        self.assertNotIn("urllib.request", " ".join(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names))
        self.assertEqual(ns.VERSION, "1.2.3")


if __name__ == "__main__":
    unittest.main()
