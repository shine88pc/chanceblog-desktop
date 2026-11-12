"""가리기 규칙 강화(PCSEC1 H1)의 증거 시험 — `security/mask.py` 의 추가 규칙(`_hidden_forms`)이 운영자 목록(Authorization·serviceKey·api_key·access/refresh token·Cookie·URL 질의·URL 사용자 정보)을
어떤 모양으로 써도 가리고, 평범한 글은 건드리지 않으며, 20만 자 적대적 입력에서도 빠르다는 것을 소스에서 직접 확인한다. 네트워크·파일 없이 돈다.

지키는 것:
  1) **163건 표**(보안 조사 `secaudit` 의 적대적 입력 A01–I12 — `tests/pcsec1_mask_cases.py`): `list`(운영자 목록)·`adv`(고의 눈속임)·`extra`(그 밖의 알려진 모양)는 `mask`·`safe_detail`·`cli.mask_block` 모두에서
     **새는 것 0**. `limit`(이름 표지가 없는 값)은 일부러 가리지 않는다는 사실을 시험이 못박는다(오탐 표의 64자 16진수 해시와 가를 방법이 없다).
  2) 이름 목록 전수(질의·JSON·XML·환경 변수식·헤더·`--옵션 값`·본문 속 꼴), 헤더 줄(스킴·접힌 줄·셸 인자의 따옴표), 쿠키(이름은 남기고 모든 값을 가림 — Set-Cookie 속성은 둠), 눈속임(전각·키릴·퍼센트·이스케이프 JSON·base64·쪼갠 값).
  3) **오탐 표**: 손으로 쓴 평범한 글 100여 개 + 앱이 실제로 내는 글(오류 카탈로그 전 문구·명령줄 도움말 전부·글 검사 예문 모음)이 한 글자도 바뀌지 않는다. 64자 16진수(커밋·SHA-256) 같은 모양만으로는 가리지 않는다.
  4) 멱등(`mask(mask(x)) == mask(x)`)·무예외·20만 자 입력 종류별 시간·크기 4배에 시간 8배 이하(선형)·이미 가린 값은 정규식 안에서 건너뛴다(두 번째·세 번째 패스에서 콜백이 돌지 않는다).
가짜 비밀은 모두 실행 중에 조립한 `CANARY_` 글이다. **실패 메시지에는 비밀 값을 싣지 않는다** — 건 번호·갈래·새는 값의 이름과 종류('full'·'part')만.
"""
import argparse
import hashlib
import random
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import pcsec1_mask_cases as pc  # noqa: E402
from chanceblog_desktop.security import mask as mk  # noqa: E402
from chanceblog_desktop.security.mask import mask, safe_detail  # noqa: E402
from chanceblog_desktop.service.cli import mask_block  # noqa: E402

BS = chr(92)
MARK_VALUE, MARK_TOKEN, MARK_COOKIE, MARK_QUERY, MARK_ENCODED = "[가림: 값]", "[가림: 토큰]", "[가림: 쿠키]", "[가림: 주소 인자]", "[가림: 인코딩된 비밀]"


def canary(label, size=24):
    return f"CANARY_{label}_" + hashlib.sha256(("engine:" + label).encode()).hexdigest()[:size]


def leaked_in(value, output):
    """output 에 value 의 전체나 8글자 조각이 있나(값은 돌려주지 않는다)."""
    if value in output:
        return "full"
    width = 8 if len(value) >= 8 else len(value)
    return "part" if any(value[index:index + width] in output for index in range(0, len(value) - width + 1)) else ""


class SecretFreeTestCase(unittest.TestCase):
    def assertHidden(self, value, output, what):
        """실패 메시지에 값도 출력도 싣지 않는다 — `what` 과 종류만."""
        found = leaked_in(value, output)
        if found:
            self.fail(f"{what}: 비밀이 {found} 로 남았다(길이 {len(value)}, 출력 길이 {len(output)})")


# ---- 1) 163건 표 ---------------------------------------------------------------------------------------------------------------
class AdversarialTableTest(unittest.TestCase):
    FUNCTIONS = (("mask", mask), ("safe_detail", safe_detail), ("mask_block", mask_block))

    def check(self, scopes):
        checked = 0
        for case in pc.CASES:
            if case.scope not in scopes:
                continue
            text = pc.text_of(case)
            for name, function in self.FUNCTIONS:
                with self.subTest(case=case.cid, scope=case.scope, function=name):
                    found = pc.leaks(case, function(text))
                    self.assertEqual(found, [], f"{case.cid}({case.desc}) 의 {name}: 새는 값 {found}")      # found 는 (값 이름, full|part) 뿐이라 비밀이 없다
                    checked += 1
        return checked

    def test_the_table_has_the_expected_shape(self):
        self.assertEqual(len(pc.CASES), 163)
        counts = {scope: sum(1 for case in pc.CASES if case.scope == scope) for scope in pc.SCOPES}
        self.assertEqual(counts, {"list": 129, "adv": 11, "extra": 18, "limit": 5})
        self.assertEqual(len({case.cid for case in pc.CASES}), 163)

    def test_the_operator_list_leaks_nothing_in_every_shape(self):
        """Authorization·serviceKey·api_key·access/refresh token·Cookie·URL 질의·URL 사용자 정보 — 129건 × 세 함수."""
        self.assertEqual(self.check({"list"}), 129 * 3)

    def test_the_deliberate_disguises_leak_nothing(self):
        """키릴·전각·퍼센트 이름·이스케이프 JSON·이중 JSON·base64·쪼갠 값·탭·따옴표 두 겹 — 11건 × 세 함수."""
        self.assertEqual(self.check({"adv"}), 11 * 3)

    def test_the_other_known_shapes_leak_nothing(self):
        """목록 밖의 알려진 모양(다른 API 의 authKey·crtfc_key·appkey·secretKey·키 모양 글) — 18건 × 세 함수."""
        self.assertEqual(self.check({"extra"}), 18 * 3)


class KnownLimitsTest(unittest.TestCase):
    """이름 표지가 없는 값은 모양만으로 정상 글과 가를 수 없다 — 일부러 가리지 않으며, 그 한계를 숨기지 않고 시험으로 못박는다(docs/SECURITY.md 에도 적었다)."""

    def test_unnamed_values_are_left_as_they_are(self):
        for case in pc.CASES:
            if case.scope != "limit":
                continue
            with self.subTest(case=case.cid, desc=case.desc):
                self.assertTrue(pc.leaks(case, mask(pc.text_of(case))), f"{case.cid}: 한계가 풀렸다 — 오탐 표(64자 16진수 해시)가 그대로인지 먼저 본다")

    def test_the_reason_is_that_a_normal_hash_looks_the_same(self):
        """공공데이터 서비스 키(64자 16진수)와 SHA-256·MANIFEST 줄은 같은 모양이다 — 이름이 붙을 때만 가린다."""
        self.assertEqual(len(pc.SHA256), 64)
        self.assertEqual(mask("sha256 " + pc.SHA256), "sha256 " + pc.SHA256)
        self.assertEqual(mask("serviceKey=" + pc.SHA256), "serviceKey=" + MARK_VALUE)
        self.assertEqual(mask("value is " + pc.SHA256 + " done"), "value is " + pc.SHA256 + " done")


# ---- 2) 이름 목록·헤더·쿠키·눈속임 ---------------------------------------------------------------------------------------------------
NAMES = ("serviceKey", "ServiceKey", "SERVICEKEY", "service_key", "authKey", "auth_key", "appKey", "appkey", "app_key", "secretKey", "secret_key", "clientSecret", "client_secret", "X-Api-Key", "x-api-key",
         "X-Naver-Client-Secret", "Ocp-Apim-Subscription-Key", "api_key", "apikey", "api-key", "ApiKey", "access_token", "refresh_token", "id_token", "token", "password", "passwd", "secret", "crtfc_key", "access_key",
         "private_key", "subscription_key", "accessToken", "refreshToken")
FORMS = (
    ("질의", "https://x.example/y?a=1&{name}={v}&z=2"), ("세미콜론 질의", "https://x.example/y;{name}={v};z=2"), ("JSON", '{{"{name}": "{v}", "z": 1}}'), ("파이썬 dict", "{{'{name}': '{v}'}}"),
    ("이스케이프 JSON", "\"{{" + BS + "\"{name}" + BS + "\": " + BS + "\"{v}" + BS + "\"}}\""), ("환경 변수식", "{name}={v}"), ("콜론", "{name}: {v}"), ("공백 있는 등호", "{name} = {v}"),
    ("XML", "<{name}>{v}</{name}>"), ("본문 속", "요청이 실패했습니다 {name}={v} 다시 시도"), ("전각 등호", "{name}" + chr(0xFF1D) + "{v}"),
)


class NamesAndFormsTest(SecretFreeTestCase):
    def test_every_listed_name_is_hidden_in_every_form(self):
        value = canary("NAMEFORM")
        checked = 0
        for name in NAMES:
            for form_name, template in FORMS:
                text = template.format(name=name, v=value)
                with self.subTest(name=name, form=form_name):
                    self.assertHidden(value, mask(text), f"{name} / {form_name}")
                    checked += 1
        self.assertEqual(checked, len(NAMES) * len(FORMS))

    def test_command_line_options_with_a_space_are_hidden_and_the_next_option_stays(self):
        value = canary("OPTION")
        for option in ("--api-key", "--service-key", "--auth-key", "--app-key", "--secret-key", "--access-token", "--refresh-token", "--id-token", "--token", "--secret", "--client-secret", "--password", "--passwd",
                       "--x-naver-client-secret", "--ocp-apim-subscription-key"):
            with self.subTest(option=option):
                masked = mask(f"tool {option} {value} --verbose")
                self.assertHidden(value, masked, option)
                self.assertTrue(masked.startswith(f"tool {option} ") and masked.endswith(" --verbose"), masked)

    def test_option_look_alikes_are_left_alone(self):
        for text in ("tool --token-file path.txt", "tool --password-stdin", "tool --api-key --verbose", "tool --keyword abcdefgh1234", "tool --tokenizer bpe"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)

    def test_a_bare_key_equals_needs_a_key_like_value(self):
        self.assertEqual(mask("request failed Key=Abcdefgh12 retry"), f"request failed Key={MARK_VALUE} retry")
        for text in ("key=value", "sort key=name", "Key=abcdefghij", "hotkey=ctrl+k", "monkey=Abcdefgh12", "config.key=Abcdefgh12"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)
        self.assertEqual(mask("Key=abcdefghijklmnopqrstu"), f"Key={MARK_VALUE}")                            # 20자 이상이면 소문자뿐이어도 키로 본다

    def test_query_names_added_by_this_change_are_hidden_with_the_query_marker(self):
        value = canary("QUERY")
        for name in ("serviceKey", "authKey", "appKey", "secretKey", "crtfc_key", "accessKey", "clientSecret", "Ocp-Apim-Subscription-Key", "X-Naver-Client-Secret", "authorization", "cookie", "bearer", "access-token"):
            with self.subTest(name=name):
                masked = mask(f"https://x.example/y?b=1&{name}={value}&c=2")
                self.assertEqual(masked, f"https://x.example/y?b=1&{name}={MARK_QUERY}&c=2")


class SpacedNamesAndBasicTest(SecretFreeTestCase):
    """PCSEC1V D4 — 자연어 문장에서 흔한 이름 모양(`API key: x`·`secret key = x`·`api.key=x`)과 `Basic ` 낱말 바로 뒤의 `이름=값-꼬리`."""
    SPACED = ("API key", "api key", "Api Key", "secret key", "Secret Key", "service key", "app key", "auth key", "access key", "client key", "api.key", "api_key", "api-key", "App.Key", "master key")

    def test_a_name_with_a_space_or_a_dot_inside_is_hidden_like_the_underscore_form(self):
        value = canary("SPACED")
        for name in self.SPACED:
            for separator in (": ", " : ", "=", " = ", ":"):
                text = f"설정 {name}{separator}{value} 끝"
                with self.subTest(name=name, separator=separator):
                    shown = mask(text)
                    self.assertHidden(value, shown, f"{name}{separator}")
                    self.assertTrue(shown.startswith("설정 ") and shown.endswith(" 끝"), "앞뒤 글은 그대로다")
                    self.assertIn(MARK_VALUE, shown)

    def test_ordinary_sentences_with_the_same_words_are_left_alone(self):
        for text in ("the api key is stored safely", "Where is my API key?", "secret keys are hard to guess", "monkey key: value1", "turkey = dinner time", "API key 발급 방법을 설명합니다", "app key 입력란",
                     "service key: 필요 없음", "access key rotation", "the secret key to success is practice", "keyboard key = a", "Basic information about the app", "Basic usage: run the tool"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)

    def test_a_name_followed_by_a_credential_shaped_value_without_any_separator_is_hidden(self):
        value = canary("NOSEP")
        for name in ("auth token", "Auth Token", "access token", "refresh token", "bearer token", "id token", "token", "tokens", "secret", "client secret", "password", "api key", "API KEY",
                     "api keys", "secret key", "service key", "app key", "auth_token", "session_id"):
            for text in (f"{name} {value}", f"Your {name} {value} is not valid", f"설정 {name}  {value}.", f"({name}" + chr(9) + f"{value})"):
                with self.subTest(text=text[:36]):
                    shown = mask(text)
                    self.assertHidden(value, shown, name)
                    self.assertIn(name, shown, "이름은 남기고 값만 가린다")
                    self.assertIn(MARK_TOKEN, shown)
                    self.assertEqual(mask(shown), shown, "두 번 가려도 같다")

    def test_words_after_a_name_that_are_not_shaped_like_a_credential_are_left_alone(self):
        for text in ("auth token expired yesterday", "the token bucket algorithm", "secret ingredient list", "password reset flow v2", "api key rotation-policy-draft",
                     "token 12345678901234567890", "secret santa-assignments-final-list", "access token 3600", "token 2026-11-11", "api key Zq8",
                     "token_bucket_size_2026_limit 설정", "client secret 비공개", "password manager comparison-2026", "secrets abcdefghijklmnopqrstuvwxyz"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)

    def test_the_value_needs_sixteen_characters_with_both_a_digit_and_a_letter(self):
        for length, hidden in ((15, False), (16, True), (17, True)):
            value = ("a1" * 9)[:length]
            with self.subTest(length=length):
                self.assertEqual(mask(f"auth token {value} 끝") != f"auth token {value} 끝", hidden)
        self.assertEqual(mask("auth token " + "ab" * 10), "auth token " + "ab" * 10, "글자만이면 낱말이다")
        self.assertEqual(mask("auth token " + "12" * 10), "auth token " + "12" * 10, "숫자만이면 번호다")

    def test_a_name_equals_value_after_the_word_basic_is_hidden_to_its_very_end(self):
        value = canary("BASICTAIL")
        for name in ("serviceKey", "token", "api_key", "access_token", "password", "client_secret"):
            for tail in ("", "-abcdef12", "_tail12345", ".v2-x9", "-" + canary("TAIL2", 8)):
                text = f"HTTP Basic {name}={value}{tail} 뒤 글"
                with self.subTest(name=name, tail=tail):
                    self.assertEqual(mask(text), f"HTTP Basic {name}={MARK_VALUE} 뒤 글")

    def test_a_real_basic_credential_is_still_hidden_and_the_text_around_it_stays(self):
        for credential in ("dXNlcjpwYXNzd29yZA==", "QWxhZGRpbjpvcGVuIHNlc2FtZQ==", "dXNlcjpwYXNzd29yZHBhc3N3b3Jk"):
            for text in (f"Authorization: Basic {credential}", f"Basic {credential} 이후 글", f"Basic {credential}.", f"(Basic {credential})", f'"Basic {credential}"'):
                with self.subTest(text=text[:30]):
                    shown = mask(text)
                    self.assertNotIn(credential[:8], shown)
                    self.assertIn(MARK_TOKEN, shown)
        self.assertEqual(mask("Basic dXNlcjpwYXNzd29yZA== 이후 글"), "Basic " + MARK_TOKEN + " 이후 글")


class HeaderRulesTest(unittest.TestCase):
    EXACT = (
        ("Authorization: Bearer abc", f"Authorization: Bearer {MARK_TOKEN}"),
        ("Authorization: Basic Zm9v", f"Authorization: Basic {MARK_TOKEN}"),
        ('Authorization: Digest username="u", response="r"', f"Authorization: Digest {MARK_TOKEN}"),
        ("Authorization: Token abc123", f"Authorization: Token {MARK_TOKEN}"),
        ("Authorization: opaque-token-value", f"Authorization: {MARK_TOKEN}"),
        ("Authorization: key=abc123", f"Authorization: {MARK_TOKEN}"),
        ("Proxy-Authorization: Basic Zm9v", f"Proxy-Authorization: Basic {MARK_TOKEN}"),
        ("authorization: bearer " + "abcdefgh" + "ijklmnopqrstuvwx", f"authorization: bearer {MARK_TOKEN}"),
        ("Authorization:    Bearer     abc", f"Authorization:    Bearer {MARK_TOKEN}"),
        ("Authorization = Bearer abc", f"Authorization = Bearer {MARK_TOKEN}"),
        ('Authorization: "Bearer abc"', f'Authorization: "Bearer {MARK_TOKEN}"'),
        ("Authorization: 'x y z'", f"Authorization: '{MARK_TOKEN}'"),
        ("Authorization: Bearer abc; Cookie: a=1", f"Authorization: Bearer {MARK_TOKEN}"),
        ("Authorization: Token abc\n    def\nHost: x", f"Authorization: Token {MARK_TOKEN}\nHost: x"),
        ("GET /x HTTP/1.1\nHost: x\nAuthorization: Bearer q\nAccept: */*\n", f"GET /x HTTP/1.1\nHost: x\nAuthorization: Bearer {MARK_TOKEN}\nAccept: */*\n"),
        ('curl -H "Authorization: Token abc123" -H "Accept: */*" https://x', f'curl -H "Authorization: Token {MARK_TOKEN}" -H "Accept: */*" https://x'),
        ("curl -H 'Authorization: Basic Zm9v' https://x", f"curl -H 'Authorization: Basic {MARK_TOKEN}' https://x"),
        (BS + '"Authorization' + BS + '": ' + BS + '"Token abc' + BS + '"', BS + '"Authorization' + BS + '": ' + BS + f'"Token {MARK_TOKEN}' + BS + '"'),
        ("Authorization%3A%20Token%20abc123", f"Authorization%3A%20Token {MARK_TOKEN}"),
        # 값이 없거나 스킴 낱말뿐이면 가릴 것이 없다
        ("Authorization: Bearer", "Authorization: Bearer"), ("Authorization:", "Authorization:"), ("Authorization: ", "Authorization: "),
        # 이미 가린 값은 그대로(정규식 안에서 건너뛴다)
        (f"Authorization: Bearer {MARK_TOKEN}", f"Authorization: Bearer {MARK_TOKEN}"), (f'Authorization: "Bearer {MARK_TOKEN}"', f'Authorization: "Bearer {MARK_TOKEN}"'), (f"Authorization: {MARK_TOKEN}", f"Authorization: {MARK_TOKEN}"),
    )

    def test_exact_outputs(self):
        for text, expected in self.EXACT:
            with self.subTest(text=text):
                self.assertEqual(mask(text), expected)

    def test_a_whole_http_request_dump_is_masked_line_by_line_and_the_rest_stays(self):
        bearer, secret = "abc123def456" + "ghi789jkl", "S3CR3T" + "-value-12345"                      # 조립한 가짜 값(저장소 비밀 스캐너가 소스 글자를 훑는다)
        dump = ("POST /v1/token HTTP/1.1\nHost: api.example.com\nAuthorization: Bearer " + bearer + "\nCookie: sid=abc; theme=dark\nContent-Type: application/json\n\n"
                '{"client_id": "x", "client_secret": "' + secret + '"}\n')
        expected = (f"POST /v1/token HTTP/1.1\nHost: api.example.com\nAuthorization: Bearer {MARK_TOKEN}\nCookie: sid={MARK_COOKIE}; theme={MARK_COOKIE}\nContent-Type: application/json\n\n"
                    '{"client_id": "x", [가림: client_secret JSON 값]}\n')
        self.assertEqual(mask(dump), expected)
        self.assertEqual(mask(expected), expected)

    def test_headers_printed_as_a_python_dict_are_masked(self):
        self.assertEqual(mask("{'Authorization': 'Bearer abc', 'Cookie': 'a=1; b=2', 'Accept': '*/*'}"),
                         f"{{'Authorization': 'Bearer {MARK_TOKEN}', 'Cookie': 'a={MARK_COOKIE}; b={MARK_COOKIE}', 'Accept': '*/*'}}")
        self.assertEqual(mask("headers = {'X-Api-Key': 'abcd1234', 'User-Agent': 'x'}"), f"headers = {{'X-Api-Key': {MARK_VALUE}, 'User-Agent': 'x'}}")

    def test_names_that_only_look_like_a_header_are_left_alone(self):
        for text in ("Authorization 헤더는 쓰지 않습니다.", "Authorization failed (401)", "Authorization", "X-Forwarded-Authorization: abc", "authorizations: 3",
                     "The Authorization header is required.", "Cookie policy: we use cookies", "cookie_name is optional", "Cookie-Policy: strict"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)

    def test_a_header_value_in_a_shell_argument_stops_at_the_closing_quote(self):
        masked = mask('curl -H "Authorization: Token abc123" https://example.invalid/path?x=1 -H "Accept: */*"')
        self.assertIn("https://example.invalid/path?x=1", masked)
        self.assertIn('-H "Accept: */*"', masked)
        self.assertNotIn("abc123", masked)

    def test_an_indented_line_that_is_not_a_value_is_not_swallowed_by_the_fold(self):
        """줄 접기(들여쓴 다음 줄을 앞 헤더의 값으로 이어 받는 것)는 값처럼 생긴 줄(토큰 글자뿐)만 받는다 — doctor·오류 출력의 들여쓴 줄이 앞 줄의 헤더 값에 먹혀 사라지지 않고,
        그 줄 안의 `Cookie:` 도 따로 가려진다(경계 시험 '위치 × 이름 표' 의 진단 정보 × Cookie 칸이 한때 샜다)."""
        value = canary("FOLD")
        text = f"Cookie: a=1\n  하실 일: 확인\n  [정상] git - Cookie: sid={value}; theme=dark\n  [정상] 다음 줄"
        masked = mask(text)
        self.assertEqual(leaked_in(value, masked), "", "접힌 줄 뒤의 Cookie 줄")
        self.assertEqual(masked, f"Cookie: a={MARK_COOKIE}\n  하실 일: 확인\n  [정상] git - Cookie: sid={MARK_COOKIE}; theme={MARK_COOKIE}\n  [정상] 다음 줄")
        self.assertEqual(mask(f"Cookie: {value}\n  하실 일: 확인"), f"Cookie: {MARK_COOKIE}\n  하실 일: 확인")
        self.assertEqual(mask("Authorization: Token abc\n    def\nHost: x"), f"Authorization: Token {MARK_TOKEN}\nHost: x", "값처럼 생긴 접힌 줄은 여전히 이어 받는다")

    def test_a_masked_header_is_skipped_by_the_regex_so_the_callback_never_runs_again(self):
        for text in (f"Authorization: Bearer {MARK_TOKEN}", f'Authorization: "Bearer {MARK_TOKEN}"', f"Proxy-Authorization: Basic {MARK_TOKEN}", f"Authorization: {MARK_TOKEN}"):
            with self.subTest(text=text), mock.patch.object(mk, "_authorization_value", wraps=mk._authorization_value) as spy:
                self.assertEqual(mask(text), text)
                self.assertEqual(spy.call_count, 0)

    def test_the_scheme_helper(self):
        self.assertEqual(mk._authorization_value("Bearer abc"), f"Bearer {MARK_TOKEN}")
        self.assertEqual(mk._authorization_value("  basic   Zm9v  "), f"basic {MARK_TOKEN}")
        self.assertEqual(mk._authorization_value("Digest a=b c=d"), f"Digest {MARK_TOKEN}")
        self.assertEqual(mk._authorization_value("mystery abc"), MARK_TOKEN)
        self.assertEqual(mk._authorization_value("opaque"), MARK_TOKEN)
        for value in ("", "   ", "Bearer", "bearer ", f"Bearer {MARK_TOKEN}", MARK_TOKEN):
            self.assertIsNone(mk._authorization_value(value), repr(value))


class CookieRulesTest(unittest.TestCase):
    EXACT = (
        ("Cookie: a=1; b=2", f"Cookie: a={MARK_COOKIE}; b={MARK_COOKIE}"),
        ("Cookie: a=1;b=2", f"Cookie: a={MARK_COOKIE};b={MARK_COOKIE}"),
        ("cookie: NID_AUT=x; NID_SES=y", f"cookie: NID_AUT={MARK_COOKIE}; NID_SES={MARK_COOKIE}"),
        ("Cookie: abc", f"Cookie: {MARK_COOKIE}"),
        ('Cookie: sid="abc def"', f"Cookie: sid={MARK_COOKIE}"),
        ("Set-Cookie: sid=abc; Path=/; Secure; HttpOnly", f"Set-Cookie: sid={MARK_COOKIE}; Path=/; Secure; HttpOnly"),
        ("Set-Cookie: sid=abc; Foo=bar", f"Set-Cookie: sid={MARK_COOKIE}; Foo={MARK_COOKIE}"),
        ("Set-Cookie: sid=abc; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Max-Age=3600; SameSite=Lax", f"Set-Cookie: sid={MARK_COOKIE}; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Max-Age=3600; SameSite=Lax"),
        ('{"Cookie": "a=1; b=2", "Host": "x"}', f'{{"Cookie": "a={MARK_COOKIE}; b={MARK_COOKIE}", "Host": "x"}}'),
        ("GET /x HTTP/1.1\nHost: x\nCookie: a=1\nAccept: */*\n", f"GET /x HTTP/1.1\nHost: x\nCookie: a={MARK_COOKIE}\nAccept: */*\n"),
        ('curl -H "Cookie: a=1" https://x', f'curl -H "Cookie: a={MARK_COOKIE}" https://x'),
        ("cookies = {'a': 'x', 'b': 'y'}", f"cookies = {{'a': '{MARK_COOKIE}', 'b': '{MARK_COOKIE}'}}"),
        ('document.cookie = "a=1; b=2"', f'document.cookie = "a={MARK_COOKIE}; b={MARK_COOKIE}"'),
        ("curl -b 'a=1; b=2' https://x", f"curl -b 'a={MARK_COOKIE}; b={MARK_COOKIE}' https://x"),
        ("curl --cookie sid=abc https://x", f"curl --cookie sid={MARK_COOKIE} https://x"),
        ("curl -b cookies.txt https://x", "curl -b cookies.txt https://x"),                                  # 파일 이름 — 쌍이 아니다
        ("git checkout -b feature/new-post", "git checkout -b feature/new-post"),
        # 이미 가린 값
        (f"Cookie: a={MARK_COOKIE}; b={MARK_VALUE}", f"Cookie: a={MARK_COOKIE}; b={MARK_VALUE}"),
    )

    def test_exact_outputs(self):
        for text, expected in self.EXACT:
            with self.subTest(text=text):
                self.assertEqual(mask(text), expected)

    def test_every_cookie_value_is_hidden_whatever_its_name(self):
        """이름 불문 — 로그인 쿠키가 아니어도(`theme`·`a`·`_ga`) 값은 모두 가리고 이름은 남긴다(운영자 결정: 쿠키는 이름 불문 모든 값)."""
        value = canary("COOKIE")
        for name in ("sessionid", "NID_SES", "NNB", "SID", "theme", "a", "_ga", "csrftoken", "logged_in", "key", "token", "x-1.y"):
            with self.subTest(name=name):
                masked = mask(f"Cookie: {name}={value}; other=1")
                self.assertEqual(masked.count(MARK_COOKIE) + masked.count(MARK_VALUE), 2, masked)
                self.assertIn(f"{name}=", masked)
                self.assertNotIn(value[:12], masked)

    def test_the_cookie_helper(self):
        self.assertEqual(mk._cookie_value("a=1; b=2", False), f"a={MARK_COOKIE}; b={MARK_COOKIE}")
        self.assertEqual(mk._cookie_value("a=1; Path=/", True), f"a={MARK_COOKIE}; Path=/")
        self.assertEqual(mk._cookie_value("a=1; Path=/", False), f"a={MARK_COOKIE}; Path={MARK_COOKIE}")
        self.assertEqual(mk._cookie_value("a=1; HttpOnly", True), f"a={MARK_COOKIE}; HttpOnly")
        self.assertEqual(mk._cookie_value("a=1; HttpOnly", False), f"a={MARK_COOKIE}; {MARK_COOKIE}")
        self.assertIsNone(mk._cookie_value(f"a={MARK_COOKIE}", False))
        self.assertIsNone(mk._cookie_value("", False))
        self.assertIsNone(mk._cookie_value("a=", False))
        self.assertEqual(sorted(mk._COOKIE_ATTRS), sorted({"path", "domain", "expires", "max-age", "samesite", "secure", "httponly", "partitioned", "priority", "version", "comment"}))


class EvasionTest(SecretFreeTestCase):
    def test_name_look_alikes_fold_to_the_real_name(self):
        value = canary("FOLD")
        cyrillic = {"a": chr(0x430), "e": chr(0x435), "o": chr(0x43E), "p": chr(0x440), "c": chr(0x441), "i": chr(0x456), "s": chr(0x455)}
        for letter, fake in cyrillic.items():
            name = "api_key" if letter in "api" else ("service_key" if letter in "seic" else "password")
            if letter not in name:
                continue
            with self.subTest(letter=letter):
                self.assertHidden(value, mask(name.replace(letter, fake, 1) + "=" + value), f"키릴 {letter}")
        self.assertHidden(value, mask(pc.fullwidth("serviceKey") + "=" + value), "전각 이름")
        self.assertHidden(value, mask("serviceKey" + chr(0xFF1A) + " " + value), "전각 콜론")
        self.assertHidden(value, mask("access" + chr(0x2011) + "token=" + value), "비분리 붙임표")
        self.assertHidden(value, mask("pass" + chr(0xFF57) + "ord=" + value), "전각 w")
        self.assertHidden(value, mask("API" + chr(0x212A) + "EY=" + value), "켈빈 기호")

    def test_percent_encoded_names_and_separators_are_read(self):
        value = canary("PERCENT")
        for text in (f"service%4Bey={value}", f"api%5Fkey={value}", f"access%2Dtoken={value}", f"password%3D{value}", f"token%3A%20{value}", f"%73ecret={value}", f"Authorization%3A%20Bearer%20{value}",
                     f"Cookie%3A%20a%3D{value}", f"https://x/y?a=1%26token=ignored&secretKey%3D{value}"):
            with self.subTest(text=text[:30]):
                self.assertHidden(value, mask(text), "퍼센트")

    def test_query_only_names_are_read_through_percent_and_full_width_letters(self):
        """대입 이름 목록에는 없고 주소 인자 이름 목록에만 있는 이름(`sig`·`auth`·`jwt`·`pwd` …) — 눈속임을 푼 뒤 주소 인자 규칙이 `[가림: 주소 인자]` 로 가린다."""
        value = canary("QONLY")
        for name in ("sig", "signature", "auth", "session", "jwt", "pwd", "x-amz-signature"):
            for how, disguised in (("퍼센트", name[0] + "%" + format(ord(name[1]), "02X") + name[2:]), ("전각", pc.fullwidth(name))):
                with self.subTest(name=name, how=how):
                    self.assertEqual(mask(f"https://x.example/y?a=1&{disguised}={value}&b=2"), f"https://x.example/y?a=1&{disguised}={MARK_QUERY}&b=2")

    def test_escaped_json_and_double_json(self):
        value = canary("ESCAPED")
        for text in ('"{' + BS + '"api_key' + BS + '": ' + BS + '"' + value + BS + '"}"', '{"body": "{' + BS + '"access_token' + BS + '": ' + BS + '"' + value + BS + '"}"}',
                     '{"a": "{' + BS + '"password' + BS + '":' + BS + '"' + value + BS + '", ' + BS + '"x' + BS + '": 1}"}'):
            with self.subTest(text=text[:30]):
                masked = mask(text)
                self.assertHidden(value, masked, "이스케이프 JSON")
                self.assertIn(MARK_VALUE, masked)

    def test_a_value_wrapped_in_base64_is_hidden_only_when_decoding_finds_a_secret(self):
        value = canary("WRAPPED")
        wrapped = pc.b64("Authorization: Bearer " + value)
        self.assertEqual(mask("payload=" + wrapped), "payload=" + MARK_ENCODED)
        self.assertEqual(mask(wrapped), MARK_ENCODED)
        self.assertEqual(mask("먼저 " + pc.b64("password=" + value) + " 나중"), "먼저 " + MARK_ENCODED + " 나중")
        self.assertEqual(mask(pc.b64url("api_key=" + value + "&a=1")), MARK_ENCODED)
        harmless = pc.b64("이 글은 평범한 안내문이고 아무 비밀도 없습니다 plain text only")
        self.assertEqual(mask("data " + harmless), "data " + harmless)
        self.assertEqual(mask("hash " + pc.SHA256), "hash " + pc.SHA256)                                      # 해시는 풀어도 이진 자료다

    def test_base64_inside_a_decoded_text_is_not_decoded_again(self):
        """깊이는 1이다(알려 둔 한계) — 풀린 글 속 base64 는 다시 풀지 않는다(느려지거나 끝없이 풀리지 않게). 두 겹으로 감싼 값은 가려지지 않지만 원문도 아니다."""
        value = canary("TWICE")
        twice = pc.b64(pc.b64("Authorization: Bearer " + value))
        self.assertEqual(mask("x=" + twice), "x=" + twice)
        self.assertEqual(mk._hide_encoded(pc.b64("Authorization: Bearer " + value), 1), pc.b64("Authorization: Bearer " + value))
        self.assertEqual(mk._hide_encoded(pc.b64("Authorization: Bearer " + value), 0), MARK_ENCODED)

    def test_after_the_decoding_budget_every_text_like_run_is_hidden(self):
        """풀어 보는 횟수(64)를 다 쓰면 글로 읽히는 덩어리는 풀어 보지 않고 가린다(실패하면 가리는 쪽) — 처음 64개는 풀어서 비밀이 없으니 그대로다."""
        runs = [pc.b64(f"plain ascii sentence number {index} with no secret at all") for index in range(mk.MAX_ENCODED_DECODES + 6)]
        masked = mask(" ".join(runs))
        self.assertEqual(masked.count(MARK_ENCODED), 6)
        self.assertTrue(masked.startswith(" ".join(runs[:mk.MAX_ENCODED_DECODES])))
        value = canary("BUDGET")
        wrapped = [pc.b64("password=" + value + str(index)) for index in range(mk.MAX_ENCODED_DECODES + 6)]
        self.assertEqual(mask(" ".join(wrapped)).count(MARK_ENCODED), len(wrapped))

    def test_a_very_long_run_is_read_from_its_start_only(self):
        """아주 긴 덩어리는 앞 8192자만 풀어 본다(알려 둔 한계) — 비밀이 앞에 있으면 덩어리 전체를 가리고, 8192자 뒤에만 있으면 못 본다."""
        value = canary("LONG")
        early = pc.b64("password=" + value + " " + "x" * 30000)
        self.assertEqual(mask(early), MARK_ENCODED)
        late = pc.b64("x" * 30000 + " password=" + value)
        self.assertEqual(mask(late), late)
        self.assertEqual(mk.MAX_ENCODED_RUN % 4, 0)

    def test_a_value_split_by_a_space_or_a_newline_is_hidden_to_its_end(self):
        value = canary("SPLIT0123456789")
        for cut in (14, 16, 20):
            with self.subTest(cut=cut):
                self.assertHidden(value, mask("api_key=" + value[:cut] + " " + value[cut:]), "공백으로 쪼갬")
                self.assertHidden(value, mask("Authorization: Bearer " + value[:cut] + "\n" + value[cut:]), "줄바꿈으로 쪼갬")
        self.assertEqual(mask("password=hunter2 and then some words"), f"password={MARK_VALUE} and then some words")      # 평범한 낱말은 이어 가리지 않는다
        self.assertEqual(mask("password=hunter2 documentation"), f"password={MARK_VALUE} documentation")                      # 숫자가 없는 긴 낱말도 이어 가리지 않는다(숫자가 든 12자 이상 한 덩어리만)
        self.assertEqual(mask("api_key=abcd1234 internationalization is long"), f"api_key={MARK_VALUE} internationalization is long")
        self.assertEqual(mask("password=hunter2 0123456789ab"), f"password={MARK_VALUE}")                                  # 숫자가 든 12자 이상 한 덩어리는 이어 가린다
        self.assertEqual(mask("password=hunter2 0123456789a"), f"password={MARK_VALUE} 0123456789a")                         # 11자는 아니다

    def test_tab_separated_compound_names_and_double_quotes(self):
        value = canary("TAB")
        self.assertHidden(value, mask("api_key" + chr(9) + value), "탭")
        self.assertHidden(value, mask('api_key=""' + value + '""'), "따옴표 두 겹")
        self.assertEqual(mask("token" + chr(9) + "count"), "token" + chr(9) + "count")                      # 낱말 하나(token)는 탭만으로 대입으로 보지 않는다


class ViewMappingTest(unittest.TestCase):
    def test_a_plain_text_is_its_own_view(self):
        for text in ("api_key=abc", "한글만 있는 문장입니다.", "한글 and english 12345"):
            view, anchors = mk._view_of(text)
            self.assertIs(view, text)
            self.assertIsNone(anchors)

    def test_look_alike_characters_are_folded_one_to_one(self):
        text = chr(0x430) + pc.fullwidth("pi_key") + chr(0xFF1D) + chr(0xA0) + "v"
        view, anchors = mk._view_of(text)
        self.assertEqual(view, "api_key= v")
        self.assertEqual(len(view), len(text))
        self.assertIsNone(anchors)

    def test_percent_escapes_are_decoded_and_positions_map_back(self):
        text = "x%41y%20z"
        view, anchors = mk._view_of(text)
        self.assertEqual(view, "xAy z")
        self.assertEqual([mk._origin(anchors, index) for index in range(len(view) + 1)], [0, 1, 4, 5, 8, 9])
        self.assertEqual(mk._apply_spans(text, anchors, [(1, 2, "Q")]), "xQy%20z")
        self.assertEqual(mk._apply_spans(text, anchors, [(2, 5, "...")]), "x%41...")
        self.assertEqual(mk._apply_spans(text, anchors, []), text)

    def test_only_visible_ascii_and_line_breaks_are_decoded(self):
        for text in ("a%zzb", "a%0", "a%00b", "a%7Fb", "a%C3%A9b", "100%"):
            with self.subTest(text=text):
                self.assertEqual(mk._view_of(text), (text, None))
        self.assertEqual(mk._view_of("a%0Ab")[0], "a" + chr(10) + "b")
        self.assertEqual(mk._view_of("a%09b")[0], "a" + chr(9) + "b")

    def test_overlapping_spans_keep_the_first_and_longer_one(self):
        self.assertEqual(mk._apply_spans("0123456789", None, [(2, 6, "A"), (3, 5, "B"), (6, 8, "C"), (2, 4, "D")]), "01AC89")
        self.assertEqual(mk._apply_spans("0123456789", None, [(5, 7, "X"), (5, 9, "Y")]), "01234Y9")

    def test_the_fold_table_covers_the_look_alikes_and_stays_one_to_one(self):
        table = mk._fold_table()
        for code, letter in ((0xFF41, "a"), (0x430, "a"), (0xFF1D, "="), (0xA0, " "), (0x2011, "-"), (0x212A, "K"), (0x130, "I"), (0xFF3F, "_"), (0x435, "e")):
            self.assertEqual(table[code], letter, hex(code))
        self.assertTrue(all(len(letter) == 1 for letter in table.values()))
        self.assertTrue(all(code >= 0x80 for code in table))
        plain = "평범한 한글 문장과 english 12345 !@#"
        self.assertEqual(plain.translate(table), plain)
        self.assertEqual(("가" + chr(0xFF41)).translate(table), "가a")


# ---- 3) 오탐 표 ----------------------------------------------------------------------------------------------------------------
# 이 앱의 가리기가 **전부터** 가리던 '정상 목록의 주소'(질의 이름이 비밀 낱말이라 초안 규칙은 짧은 값이라고 통과시키지만 가리기는 원래 가린다) — 이번에 생긴 것이 아니다.
ALREADY_MASKED_BEFORE = frozenset({
    "https://example.com/api/docs?access_token=YOUR_TOKEN", "https://example.com/api?api_key=1234567", "https://example.com/page?token=123456", "https://example.com/page?key=value", "https://example.com/download?sig=ok",
})


def flat_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from flat_strings(key)
            yield from flat_strings(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from flat_strings(item)


def help_texts(parser):
    yield parser.format_help()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from help_texts(sub)


def harvested_normal_texts():
    """앱이 실제로 내거나 시험이 '정상' 이라고 못박은 글: 오류 카탈로그 전 문구, 명령줄 도움말 전부, 글 검사·주제·초안 예문 모음 → {모음 이름: [글]}."""
    import claims_accuracy_examples as claims
    import draft_samples
    import garbage_samples
    import topics_corpus
    from chanceblog_desktop.errors import CATALOG
    from chanceblog_desktop.service import cli

    groups = {"errors.CATALOG": [text for info in CATALOG.values() for text in (info.code, info.when, info.message, info.action, info.retry)], "cli.help": list(help_texts(cli.build_parser()))}
    for module, wanted in ((claims, None), (topics_corpus, None), (draft_samples, ("CONTROL", "DAILY", "NORMAL_ADDRESSES", "NORMAL_FILE_NAMES", "NORMAL_MORE", "OPERATOR_C", "KNOWN_LIMITS")),
                           (garbage_samples, ("NORMAL_TEXTS",))):
        for name in dir(module):
            if name.isupper() and not name.startswith("_") and (wanted is None or name in wanted):
                groups[f"{module.__name__}.{name}"] = list(flat_strings(getattr(module, name)))
    return {name: [text for text in texts if text] for name, texts in groups.items() if texts}


class NormalOutputsTest(unittest.TestCase):
    def test_the_hand_written_normal_texts_are_not_touched(self):
        self.assertGreaterEqual(len(pc.NORMAL_TEXTS), 100)
        for text in pc.NORMAL_TEXTS:
            with self.subTest(text=text[:50]):
                self.assertEqual(mask(text), text)
                self.assertEqual(safe_detail(text, 10 ** 6), " ".join(text.split()))

    def test_text_the_app_really_prints_is_not_touched(self):
        groups = harvested_normal_texts()
        total = checked = 0
        for name, texts in sorted(groups.items()):
            for index, text in enumerate(texts):
                total += 1
                if text in ALREADY_MASKED_BEFORE or mk._strip_invisible(text) != text:                       # 숨은 글자는 가리기가 원래 지운다(비밀이 아니어도)
                    continue
                checked += 1
                with self.subTest(group=name, index=index):
                    self.assertEqual(mask(text), text, f"{name}[{index}] 가 바뀌었다: {text[:60]!r}")
        self.assertGreater(total, 2000, "예문 모음을 거두지 못했다")
        self.assertGreater(checked, 1900)
        self.assertGreaterEqual(len(groups), 35)

    def test_hashes_alone_are_never_masked(self):
        for text in (pc.SHA1, pc.SHA256, pc.MD5, "commit " + pc.SHA1, '"sha256": "' + pc.SHA256 + '"', pc.SHA256[:7], "abcdef0123456789" * 8):
            self.assertEqual(mask(text), text)

    def test_ordinary_words_and_punctuation_around_the_names_are_kept(self):
        for text in ("The token expired.", "Secret garden", "비밀번호 규칙", "key points", "Key: value", "secrets and tokens", "passwords differ", "Cookie 정책", "authorization 절차", "The cookies are stored.",
                     "토큰: 만료됨", "api key 입력", "set cookie 규칙"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)


# ---- 4) 멱등·무예외·속도 ---------------------------------------------------------------------------------------------------------------
class IdempotenceTest(unittest.TestCase):
    def test_masking_twice_changes_nothing_for_the_whole_table_and_the_normal_texts(self):
        for case in pc.CASES:
            if len(pc.text_of(case)) > 20000:
                continue
            text = pc.text_of(case)
            once = mask(text)
            with self.subTest(case=case.cid):
                self.assertEqual(mask(once), once)
        for text in pc.NORMAL_TEXTS:
            self.assertEqual(mask(mask(text)), mask(text))

    def test_random_mixtures_are_stable_and_never_raise(self):
        fragments = ["Authorization", "Cookie", "Set-Cookie", "api_key", "serviceKey", "token", "password", "secret", "X-Api-Key", "Key", "Bearer", "Basic", "Token", "=", ":", ": ", " = ", '"', "'", BS + '"', " ", "\t", "\n", "\r\n",
                     "\n    ", ";", "; ", ",", "&", "?", "<", ">", "</", "<token>", "</token>", "--token ", "--api-key ", "-b ", "--cookie ", "%3A", "%20", "%5F", "%41", "%0A", "%", chr(0xFF1D), chr(0x430), chr(0xFF41), chr(0x200B),
                     chr(0xA0), "abcd1234", "VALUE_0123456789abcdef", "0123456789abc", MARK_VALUE, MARK_TOKEN, MARK_COOKIE, MARK_QUERY, MARK_ENCODED, "[가림", pc.b64("Authorization: Bearer ABCDEF123456"), "a=1", "sid=Z9y8x7w6",
                     "Path=/", "HttpOnly", "{", "}", "(", ")", "한글", "curl ", "document.", "dict(", "{'a': '", "'}"]
        rnd = random.Random(20261111)
        for index in range(4000):
            text = "".join(rnd.choice(fragments) for _ in range(rnd.randint(1, 14)))
            once = mask(text)
            self.assertEqual(mask(once), once, f"{index}: 두 번 가리면 달라진다 — {text!r}")


class RobustnessTest(unittest.TestCase):
    def test_odd_inputs_never_raise(self):
        class Broken:
            def __str__(self):
                raise RuntimeError("표시할 수 없다")

        for value in (None, 0, 1.5, b"authorization: bearer abc", ["Cookie: a=1"], {"password": "abcd1234"}, Broken(), object()):
            with self.subTest(value=type(value).__name__):
                self.assertIsInstance(mask(value), str)
        for text in ("", " ", "\x00", "\x00" * 50, chr(0xD800) * 20, "Authorization:" + chr(0xD800), "Cookie: a=" + chr(0xDFFF), "%", "%%%%", "\\", "\\\\\\\\", '"', "<", "<token", "<token>", "</token>", "key=", "--token", "--token ",
                     "Authorization: " + "\x00" * 10, "a" * 25 + "==" + "=" * 5, "A" * 24, "====" * 100):
            with self.subTest(text=text[:20]):
                self.assertIsInstance(mask(text), str)


class LoweredViewTest(unittest.TestCase):
    """`_lowered`(소문자판)는 바꿀 글자(`İ`·`ı`·`ſ`·켈빈 기호)가 있을 때만 `translate` 를 거치고, 그 밖에는 `lower()` 만 쓴다 — 결과는 어느 쪽이든 같다."""

    def test_the_result_is_the_same_as_the_translate_path_for_every_kind_of_text(self):
        for text in ("", "plain ASCII Text", "한글만 있는 글", "[가림: 주소 인자] 한글과 ASCII", chr(0x130) + "stanbul", "ba" + chr(0x131) + "k", "pa" + chr(0x17F) + "word", chr(0x212A) + "ey=Value", "가" + chr(0x212A) + "나"):
            with self.subTest(text=text[:12]):
                self.assertEqual(mk._lowered(text), text.translate(mk._LOWER_FIX).lower())

    def test_the_slow_translate_is_not_used_when_no_special_letter_is_present(self):
        calls = []
        real = str.translate

        class Spy(str):
            def translate(self, table):
                calls.append(1)
                return real(self, table)

        mk._lowered(Spy("한글 ABC"))
        self.assertEqual(calls, [], "바꿀 글자가 없으면 translate 를 부르지 않는다")
        mk._lowered(Spy("한글 " + chr(0x130)))
        self.assertEqual(calls, [1], "바꿀 글자가 있으면 translate 를 거친다")


class SpeedTest(unittest.TestCase):
    N = 200_000
    LIMIT = 2.0                                                                                              # CPU 시간(초) — 목표는 0.5초이고, 느린 CI 칸(윈도 러너)을 위해 4배의 여유를 둔다. 실제 값은 engine_notes 의 시간 표

    def inputs(self):
        n = self.N
        b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldY"
        yield "평범한 한글", ("가나다라마바사 " * n)[:n]
        yield "평범한 영문", ("The quick brown fox jumps over the lazy dog. " * n)[:n]
        yield "Authorization 줄 반복", ("Authorization: x" + chr(10)) * (n // 17)
        yield "Authorization 줄바꿈 없이 반복", "Authorization: " * (n // 15)
        yield "Authorization 따옴표 안 닫힘", 'Authorization:"' * (n // 15)
        yield "api_key 반복", "api_key=abcd " * (n // 13)
        yield "api_key 따옴표 반복", 'api_key="' * (n // 9)
        yield "이스케이프 JSON 반복", (BS + '"api_key' + BS + '": ' + BS + '"abcde' + BS + '" ') * (n // 24)
        yield "퍼센트 이름 반복", "api%5Fkey=abcd " * (n // 15)
        yield "%41 반복", "%41" * (n // 3)
        yield "전각 글자만", chr(0xFF41) * n
        yield "키릴 글자만", chr(0x430) * n
        yield "서로 다른 글자", "".join(chr(0x4E00 + index) for index in range(n))
        yield "base64 덩어리 반복", (b64 + " ") * (n // 33)
        yield "token 반복", "token" * (n // 5)
        yield "= 만", "=" * n
        yield "공백만", " " * n
        yield "Cookie 쌍 반복", "Cookie: " + "a=1; " * (n // 5)
        yield "Cookie 줄 반복", ("Cookie: a=1; b=2" + chr(10)) * (n // 17)
        yield "<token> 반복", "<token>" * (n // 7)
        yield "--token 반복", "--token " * (n // 8)
        yield "key= 반복", "key=abcdefgh1 " * (n // 14)
        yield "표지 뒤 조각 반복", "[가림: 값] 0123456789abc " * (n // 24)
        yield "이름 뒤 값 모양 반복", "auth token a1 " * (n // 14)
        yield "이름 뒤 긴 덩어리", "token " + "a1" * (n // 2)
        yield "이름 뒤 공백 많음", "token" + " " * (n - 7) + "x1"
        yield "주소 인자 한 글자 값 반복", "?token=a&" * (n // 9)                                    # 가림 표지의 한글로 글이 ASCII 가 아니게 되는 길(PCSEC1V D10)
        yield "헤더와 일반 줄", ("Host: example.com" + chr(10) + "Authorization: Bearer abcdef" + chr(10) + "Cookie: x=1" + chr(10) + "그냥 문장" + chr(10)) * (n // 70)

    def test_every_adversarial_input_of_200k_characters_is_fast(self):
        slowest = (0.0, "")
        for name, text in self.inputs():
            text = text[:self.N]
            started = time.process_time()
            mask(text)
            took = time.process_time() - started
            slowest = max(slowest, (took, name))
            with self.subTest(input=name):
                self.assertLess(took, self.LIMIT, f"{name}: {took:.2f}초(CPU)")
        self.assertLess(slowest[0], self.LIMIT)

    def test_the_time_grows_with_the_input_not_faster(self):
        """크기를 4배로 하면 시간은 8배 이하(선형이면 4배) — 입력 종류마다."""
        for name, text in (("헤더 줄", ("Authorization: Bearer x" + chr(10)) * 8000), ("쿠키 쌍", "Cookie: " + "a=1; " * 8000), ("이름 대입", "api_key=abcd " * 8000), ("이스케이프", (BS + '"token' + BS + '": ' + BS + '"abcde' + BS + '" ') * 4000),
                           ("평범한 글", "가나다라마바사 " * 8000)):
            def took(times):
                best = 1e9
                for _ in range(2):
                    started = time.process_time()
                    mask(text * times if len(text) * times <= 200_000 else (text * times)[:200_000])
                    best = min(best, time.process_time() - started)
                return best

            small, large = took(1), took(4)
            with self.subTest(input=name):
                self.assertLess(large, max(small * 8, 0.5), f"{name}: 4배 입력에 {large / max(small, 1e-9):.1f}배")


class PrefilterTest(SecretFreeTestCase):
    """규칙마다 '글에 반드시 있어야 하는 낱말'을 먼저 보고 없으면 그 규칙의 검색을 건너뛴다(20만 자 평범한 글이 0.19초 → 0.03초). 건너뛰는 것이 결과를 바꾸면 안 된다 — 같은 입력에 켜고 끈 결과가 같고,
    일치하는 규칙은 늘 사전 확인을 통과한다(필요 조건이 정말 필요 조건이다)."""

    FRAGMENTS = ("Authorization", "Cookie", "api_key", "serviceKey", "token", "password", "secret", "X-Api-Key", "Key", "Bearer", "Basic", "=", ":", ": ", '"', "'", BS + '"', " ", chr(9), chr(10), ";", "&", "?", "<token>", "</token>", "--token ",
                 "-b ", "%3A", "%5F", chr(0xFF1D), chr(0x430), chr(0xA0), chr(0x130) + "d", chr(0x131), chr(0x17F) + "ecret", chr(0x212A) + "ey=", "abcd1234", "VALUE_0123456789abcdef", "[가림: 값]", "한글", "a=1", "https://u:p@host/", "?code=abcdefgh12",
                 "AI" + "za" + "x" * 35, "gh" + "p_" + "y" * 36, "AK" + "IA" + "Z" * 16, "xox" + "b-" + "1" * 12, "sk" + "-" + "q" * 40, "ey" + "J" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12, "bearer " + "abcdefghijklmnop123456", "np" + "m_" + "a1B2" * 9,
                 "-----BEGIN " + "PRIVATE KEY-----" + chr(10) + "QUJD" + chr(10) + "-----END PRIVATE KEY-----", "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG", "hooks.slack.com/services/T0/B0/XXXXXXXXXXXXXXXXXXXXXXXX", "123456789:" + "AbCdEfGhIj" * 4,
                 "api_key = '" + "j" * 30 + "'")

    def samples(self, count, seed):
        rnd = random.Random(seed)
        found = [pc.text_of(case) for case in pc.CASES if len(pc.text_of(case)) < 30000] + list(pc.NORMAL_TEXTS)
        found += ["".join(rnd.choice(self.FRAGMENTS) for _ in range(rnd.randint(1, 12))) for _ in range(count)]
        return found

    def test_the_prefilters_are_on_and_every_pattern_is_in_the_chain(self):
        self.assertTrue(mk._USE_PREFILTERS)
        in_chain = [entry[0] for entry in mk._CHAIN]
        for label, pattern in (*mk.SECRET_PATTERNS, *mk._BOUNDED_PATTERNS, *mk._NEW_SK_PATTERNS):
            self.assertTrue(any(pattern is item for item in in_chain), label)
        for pattern in (mk._PEM, mk._USERINFO, mk._USERINFO_ESCAPED, mk._QUERY_SECRET, mk._QUERY_CODE, mk._BEARER, mk._BASIC, mk._JWT, mk._SLACK_HOOK, mk._NPM_TOKEN, mk._AWS_SECRET, mk._ASSIGNMENT):
            self.assertTrue(any(pattern is item for item in in_chain), pattern.pattern[:30])
        self.assertEqual(set(mk._VENDOR_NEEDS), {label for label, _pattern in mk.SECRET_PATTERNS}, "정본의 패턴 종류가 바뀌었다 — 사전 확인 표(`_VENDOR_NEEDS`)도 맞춘다(모르는 종류는 늘 돈다)")

    def test_turning_the_prefilters_off_gives_the_same_result(self):
        for text in self.samples(2500, 4242):
            with mock.patch.object(mk, "_USE_PREFILTERS", True):
                fast = mask(text)
            with mock.patch.object(mk, "_USE_PREFILTERS", False):
                slow = mask(text)
            self.assertEqual(fast, slow, f"사전 확인이 결과를 바꿨다: {text[:80]!r}")

    def test_a_pattern_that_matches_is_never_skipped(self):
        checked = 0
        for text in self.samples(3000, 777):
            clean = mk._strip_invisible(text)
            low = mk._lowered(clean)
            for pattern, _replacement, need in mk._CHAIN:
                if pattern.search(clean):
                    checked += 1
                    self.assertTrue(mk._applies(clean, low, need), f"일치하는 규칙을 사전 확인이 건너뛴다: {pattern.pattern[:40]!r} / {clean[:60]!r}")
        self.assertGreater(checked, 1000)

    def test_the_lowercase_view_reads_like_ignorecase(self):
        """정규식의 대소문자 무시가 영문 글자와 같다고 보는 비ASCII 글자는 İ·ı·ſ·켈빈 기호 뿐이다(파이썬 판마다 다시 확인 — 더 늘면 `_LOWER_FIX` 를 늘려야 사전 확인이 놓치지 않는다)."""
        rx = re.compile("(?i)[a-z]")
        extras = {code for code in range(0x80, 0x20000) if rx.fullmatch(chr(code))}
        self.assertEqual(extras, set(mk._LOWER_FIX))
        for code, letter in mk._LOWER_FIX.items():
            self.assertEqual(mk._lowered(chr(code)), letter)
        self.assertEqual(mk._lowered("ABC가" + chr(0x130)), "abc가i")
        self.assertEqual(mk._lowered("Plain ASCII"), "plain ascii")

    def test_exotic_letters_in_names_still_reach_the_rules(self):
        """`İ`·`ı`·`ſ`·켈빈 기호로 쓴 이름도 사전 확인에서 떨어지지 않고 규칙에 닿는다(정규식의 대소문자 무시가 영문 글자로 읽는 글자들)."""
        value = canary("EXOTIC")
        for text in ("AP" + chr(0x130) + "_KEY=" + value, chr(0x17F) + "ecret=" + value, "sess" + chr(0x131) + "onid=" + value, "Authorization: Bas" + chr(0x131) + "c " + value,
                     chr(0x212A) + "ey=" + value + "A1", "api_" + chr(0x212A) + "ey: " + value, "pa" + chr(0x17F) + chr(0x17F) + "word=" + value, "Cookie: sess" + chr(0x131) + "on=" + value,
                     "{" + BS + '"' + chr(0x17F) + "ecret" + BS + '": ' + BS + '"' + value + BS + '"}', chr(0x217D) + "ookie: a=" + value):
            with self.subTest(text=text[:24]):
                self.assertHidden(value, mask(text), text[:24])


class KeptApiTest(unittest.TestCase):
    """다른 곳이 쓰는 이름 — `security/secret_scan.py`(저장 전 검사)·`gate`·`pages`·`ui` 가 가져간다. 바꾸면 여기서 먼저 알린다."""

    def test_the_names_other_modules_import_still_exist(self):
        for name in ("mask", "safe_detail", "has_key_shape", "MAX_MASK_INPUT", "MAX_LOG_CHARS", "_mask_once", "_strip_invisible", "_INVISIBLE", "_ascii_bounded", "_BOUNDED_PATTERNS", "_NEW_SK_PATTERNS", "_SHAPE_PATTERNS",
                     "_NOT_AFTER", "_NOT_BEFORE", "SECRET_PATTERNS", "_PEM", "_JWT", "_SLACK_HOOK", "_NPM_TOKEN", "_BEARER", "_BASIC", "_hidden_forms"):
            self.assertTrue(hasattr(mk, name), name)

    def test_module_own_patterns_do_not_use_word_boundaries(self):
        for name, value in vars(mk).items():
            if isinstance(value, re.Pattern) and isinstance(value.pattern, str):
                self.assertNotIn(BS + "b", value.pattern, name)

    def test_has_key_shape_still_looks_only_at_shapes(self):
        for text in ("password: required", "token=abc", "Authorization: Bearer abc", "Cookie: a=1", "serviceKey=" + pc.SHA256, "https://example.com/?token=abc"):
            self.assertFalse(mk.has_key_shape(text), text)

    def test_depth_one_decoding_is_a_keyword_argument_of_the_single_pass(self):
        self.assertEqual(mk._mask_once("Authorization: Token abc"), f"Authorization: Token {MARK_TOKEN}")
        self.assertEqual(mk._mask_once("Authorization: Token abc", 1), f"Authorization: Token {MARK_TOKEN}")


if __name__ == "__main__":
    unittest.main()
