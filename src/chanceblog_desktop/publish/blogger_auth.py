"""Blogger 로그인(OAuth 2.0 — 데스크톱 앱 + 루프백 + PKCE + state)의 요청 모양과 응답 검사(BLOGGER 설계서 3.5 E·F, 3.6, 결정 D-772, 운영자 확인 038 ③).

여기는 **순수한 부분**이다: PKCE 값·`state` 를 만들고, 로그인 주소를 만들어 모양을 검사하고, 토큰 서버로 보낼 요청 본문을 만들고, 응답을 **쓰기 전에 모양을 본다**(`token_type`·`access_token`·`expires_in`·`scope`·`refresh_token`).
접속은 호출하는 쪽이 넘겨 준 클라이언트(`net/client.py` 의 `NetClient` 같은 값)로만 한다 — 이 파일은 소켓·`http`·`ssl` 을 가져오지 않는다. 공개 함수의 첫 문장은 모두 관문(`capabilities.require_net("blogger_oauth", …)`)이다.

지키는 것:
  · 범위는 `auth/blogger` **하나**(쓰기에 필요한 범위가 이것 하나뿐 — 읽기 전용 범위로는 초안을 못 만든다). 토큰 응답의 `scope` 가 기대와 다르면(줄었거나 늘었으면) 저장하지 않는다.
  · PKCE 는 **`S256` 만** 쓴다 — `plain` 으로 물러서지 않는다(RFC 7636 7.2). 검증기는 무작위 32바이트(43자)를 로그인마다 새로 만들고 메모리에만 둔다. `state` 는 256비트.
  · 로그인 주소는 호스트·길·질의 키가 **고정**이다(`check_auth_url`) — `login_hint`·`include_granted_scopes` 같은 것은 쓰지 않는다(이메일을 저장·전송하지 않는다).
  · 토큰은 값 객체(`Secret`·`AccessToken`)에 담는다 — `repr`·`str`·`format` 에 값이 없고 직렬화·복사는 거절한다. 토큰·인증 코드·검증기·`state`·클라이언트 시크릿은 오류·로그·접속 기록 어디에도 쓰지 않는다
    (서버가 보낸 `error_description` 같은 글은 읽지도 않는다 — 오류 이름 하나만 모양을 보고 쓴다).
  · 응답이 '로그인 코드가 맞지 않음(`invalid_grant`)' 이면 교환은 로그인 실패, 갱신은 **재인증 필요**(`BLOGGER_AUTH_EXPIRED`)로 나뉜다. 자동 재로그인은 없다.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from .. import capabilities
from ..errors import AppError
from ..net import loopback
from ..net.endpoints import url_for
from ..net.errors import REASON_SHAPE, NetError, invalid

SCOPE = "https://www.googleapis.com/auth/blogger"
AUTH_HOST = "accounts.google.com"
AUTH_PATH = "/o/oauth2/v2/auth"
AUTH_KEYS = ("client_id", "redirect_uri", "response_type", "scope", "state", "code_challenge", "code_challenge_method", "access_type", "prompt")
MAX_AUTH_URL = 2000
MAX_ACCESS_SECONDS = 55 * 60                 # 접근 토큰을 쓰는 최대 시간(구글은 보통 1시간을 준다)
EARLY_SECONDS = 60                           # 만료 전에 미리 새로 받는 여유
REVOKE_LIMIT = 4096
TOKEN_LIMIT = 64 * 1024
USE = "blogger_oauth"

REASON_NO_WINDOW = "로그인 창구를 열 수 없어요"
REASON_DENIED = "로그인을 허용하지 않았어요"
REASON_TIMEOUT = "시간이 지났거나 취소했어요"
REASON_FLOOD = "로그인과 상관없는 요청이 너무 많이 왔어요"
REASON_BAD_CODE = "로그인 코드가 맞지 않아요"
REASON_NO_VALUE = "로그인 값을 받지 못했어요"
REASON_SCOPE = "허용한 범위가 달라요"
REASON_BUSY = "다른 로그인이 아직 끝나지 않았어요"
REASONS = (REASON_NO_WINDOW, REASON_DENIED, REASON_TIMEOUT, REASON_FLOOD, REASON_BAD_CODE, REASON_NO_VALUE, REASON_SCOPE, REASON_BUSY)
LISTENER_REASON = {loopback.REASON_BIND: REASON_NO_WINDOW, loopback.REASON_TIMEOUT: REASON_TIMEOUT, loopback.REASON_CANCELLED: REASON_TIMEOUT, loopback.REASON_TOO_MANY: REASON_FLOOD}

_TOKEN_TEXT = re.compile(r"[A-Za-z0-9._~+/=-]+")
_ERROR_NAME = re.compile(r"[a-z][a-z_]{0,39}")
_CLIENT_TEXT = re.compile(r"[A-Za-z0-9._-]{1,256}")                # 구글 클라이언트 번호의 글자(영문·숫자·점·밑줄·붙임표)
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")


def login_failed(reason):
    """`BLOGGER_LOGIN_FAILED` — 이유는 위 고정 낱말 가운데 하나다(요청·응답의 글을 싣지 않는다)."""
    if reason not in REASONS:
        reason = REASON_NO_VALUE
    return AppError("BLOGGER_LOGIN_FAILED", {"이유": reason})


# ---- 값 객체 -------------------------------------------------------------------------------------------------------------------------------
class Secret:
    """비밀 글 하나 — `repr`·`str`·`format` 은 값을 보이지 않고 직렬화·복사는 거절한다. 값은 `reveal()` 로만 꺼낸다(쓰는 순간에만 꺼내고 바로 버린다)."""

    __slots__ = ("_value",)

    def __init__(self, value):
        if not isinstance(value, str) or not value:
            raise ValueError("비밀 값은 비어 있지 않은 글이어야 한다")
        object.__setattr__(self, "_value", value)

    def __setattr__(self, name, value):
        raise AttributeError("비밀 값은 바꿀 수 없다")

    def __delattr__(self, name):
        raise AttributeError("비밀 값은 바꿀 수 없다")

    def reveal(self):
        return self._value

    def into(self, values, name):
        """값을 사전 `values` 의 `name` 칸에 넣는다 — 서비스 층이 `reveal` 을 부르지 않고 보관소 값 묶음에 한 칸을 더하는 길(값은 쓰는 순간에만 사전으로 가고 이 객체는 계속 가려져 있다)."""
        values[name] = self._value

    def __repr__(self):
        return f"<{type(self).__name__} — 값은 가려져 있음>"

    __str__ = __repr__

    def __format__(self, spec):
        return repr(self)

    def __reduce__(self):
        raise TypeError("비밀 값은 직렬화하지 않는다")

    def __copy__(self):
        raise TypeError("비밀 값은 복사하지 않는다")

    def __deepcopy__(self, memo):
        raise TypeError("비밀 값은 복사하지 않는다")

    def __eq__(self, other):
        return self is other

    __hash__ = object.__hash__


class AccessToken(Secret):
    """접근 토큰 — 메모리에만 둔다. `valid_until` 은 쓸 수 있는 마지막 시각(시계 초)이다."""

    __slots__ = ("valid_until",)

    def __init__(self, value, valid_until):
        super().__init__(value)
        object.__setattr__(self, "valid_until", float(valid_until))

    def usable(self, now):
        """아직 쓸 수 있는가(만료 직전의 여유 포함 — 만든 때 이미 뺐다)."""
        return now < self.valid_until


@dataclass(frozen=True)
class Tokens:
    """교환 결과 — 접근 토큰과 갱신 토큰(둘 다 값이 가려진다)."""
    access: AccessToken = field(repr=False)
    refresh: Secret = field(repr=False)


@dataclass(frozen=True)
class LoginRequest:
    """로그인 한 번의 값 — 주소·`state`·검증기(메모리에만 둔다). `repr` 에는 아무것도 나오지 않는다."""
    url: str = field(repr=False)
    state: str = field(repr=False)
    verifier: Secret = field(repr=False)
    redirect_uri: str = field(repr=False)
    port: int = 0


# ---- PKCE·state·로그인 주소 ---------------------------------------------------------------------------------------------------------------
def new_verifier():
    """코드 검증기 — 무작위 32바이트를 base64url 로(43자). 로그인마다 새로 만든다."""
    return secrets.token_urlsafe(32)


def challenge_of(verifier):
    """`S256` — 검증기의 SHA-256 을 base64url(패딩 없음)로."""
    if not isinstance(verifier, str) or _VERIFIER.fullmatch(verifier) is None:
        raise ValueError("검증기의 모양이 올바르지 않다")
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def new_state():
    """`state` — 256비트 무작위(43자)."""
    return secrets.token_urlsafe(32)


def redirect_uri_for(port):
    """돌아올 주소 — 평문 http 의 `127.0.0.1:<포트>/callback` 이다(RFC 8252 — 이름이 아니라 IP 글자)."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("포트가 올바르지 않다")
    return f"http://127.0.0.1:{port}{loopback.CALLBACK_PATH}"


def build_auth_url(client_id, port, state, challenge):
    """브라우저가 열 로그인 주소 — 질의 키는 `AUTH_KEYS` 아홉뿐이다. 만든 뒤 `check_auth_url` 을 지나지 못하면 `BLOGGER_LOGIN_FAILED`."""
    if not isinstance(client_id, str) or _CLIENT_TEXT.fullmatch(client_id) is None:
        raise login_failed(REASON_NO_VALUE)
    pairs = [("client_id", client_id), ("redirect_uri", redirect_uri_for(port)), ("response_type", "code"), ("scope", SCOPE), ("state", state), ("code_challenge", challenge),
             ("code_challenge_method", "S256"), ("access_type", "offline"), ("prompt", "consent")]
    url = f"https://{AUTH_HOST}{AUTH_PATH}?" + urlencode(pairs, quote_via=quote)
    if check_auth_url(url):
        raise login_failed(REASON_NO_VALUE)
    return url


def check_auth_url(url):
    """로그인 주소의 모양 검사 → 어긴 것의 이름 목록(없으면 빈 목록). https · 호스트 `accounts.google.com` · 포트 없음 또는 443 · 길 `/o/oauth2/v2/auth` · 사용자 정보 없음 ·
    2,000자 이하 · 공백·제어 문자 없음 · 질의 키는 `AUTH_KEYS` 아홉 가지가 **각각 한 번**뿐이다."""
    problems = []
    if not isinstance(url, str) or not url:
        return ["주소"]
    if len(url) > MAX_AUTH_URL:
        problems.append("길이")
    if any(ch <= " " or ch == "\x7f" for ch in url) or not url.isascii():
        problems.append("공백·제어 문자")
    try:
        parts = urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        return problems + ["주소"]
    if parts.scheme != "https":
        problems.append("https")
    if host != AUTH_HOST or parts.netloc.lower() != AUTH_HOST + (":443" if port == 443 else "") or port not in (None, 443):
        problems.append("호스트")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        problems.append("사용자 정보")
    if parts.path != AUTH_PATH:
        problems.append("길")
    if parts.fragment:
        problems.append("조각")
    try:
        keys = [key for key, _value in parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)]
    except ValueError:
        keys = None
    if keys is None or sorted(keys) != sorted(AUTH_KEYS):
        problems.append("질의 키")
    return problems


def begin_login(client_id, port):
    """로그인 한 번을 시작하는 값들을 만든다(창구가 이미 듣는 중일 때 — `port` 를 안다). 아직 접속하지 않는다."""
    capabilities.require_net(USE, "Blogger 로그인 시작")
    verifier = new_verifier()
    state = new_state()
    return LoginRequest(build_auth_url(client_id, port, state, challenge_of(verifier)), state, Secret(verifier), redirect_uri_for(port), port)


# ---- 응답 읽기 ---------------------------------------------------------------------------------------------------------------------------------
def _error_name(response):
    """토큰 서버가 알린 오류 이름(`invalid_grant` 같은 짧은 낱말) — 모양이 맞을 때만. 서버의 설명 글은 읽지 않는다."""
    try:
        data = response.json()
    except NetError:
        return str()
    value = data.get("error") if isinstance(data, dict) else None
    return value if isinstance(value, str) and _ERROR_NAME.fullmatch(value) else str()


def _bad_shape(phase):
    return invalid(USE, REASON_SHAPE, phase=phase)


def _token_text(data, key, low, high, *, required=True):
    value = data.get(key)
    if value is None:
        if required:
            raise _bad_shape(key)
        return None
    if not isinstance(value, str) or not low <= len(value) <= high or _TOKEN_TEXT.fullmatch(value) is None:
        raise _bad_shape(key)
    return value


def _access_from(data, now):
    """응답 객체 → `AccessToken`. `token_type` 은 Bearer, `access_token` 20–2,048자, `expires_in` 정수 60–7,200."""
    if not isinstance(data, dict):
        raise _bad_shape("object")
    token_type = data.get("token_type")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise _bad_shape("token_type")
    value = _token_text(data, "access_token", 20, 2048)
    seconds = data.get("expires_in")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 60 <= seconds <= 7200:
        raise _bad_shape("expires_in")
    return AccessToken(value, now + min(seconds - EARLY_SECONDS, MAX_ACCESS_SECONDS))


def _scope_ok(data, *, required):
    """`scope` 에 기대한 범위 **하나만** 있어야 한다(줄었거나 늘었으면 거절). 갱신 응답에는 없을 수 있어 `required=False`."""
    scope = data.get("scope")
    if scope is None:
        return not required
    return isinstance(scope, str) and scope.split() == [SCOPE]


def _failure(response, *, refresh):
    """토큰 서버의 실패 응답 → 오류. 서버의 글은 쓰지 않고 상태 번호와 오류 이름만 본다."""
    status = response.status
    name = _error_name(response)
    if status == 429:
        return NetError("API_RATE_LIMITED", {}, detail=f"{USE}:status:429", use=USE)
    if status >= 500:
        return NetError("BLOGGER_SERVER_ERROR", {}, detail=f"{USE}:status:{status}", use=USE, outcome_unknown=True)
    if name == "invalid_grant":
        return NetError("BLOGGER_AUTH_EXPIRED", {}, detail=f"{USE}:invalid_grant", use=USE) if refresh else login_failed(REASON_BAD_CODE)
    if status in (401, 403) or name in ("invalid_client", "unauthorized_client", "access_denied"):
        return NetError("KEY_AUTH_FAILED", {}, detail=f"{USE}:status:{status}", use=USE)
    if status in (400, 422):
        return NetError("REQUEST_INVALID", {}, detail=f"{USE}:status:{status}", use=USE)
    return invalid(USE, REASON_SHAPE, phase=f"status:{status}")


def _form(pairs):
    return urlencode(pairs).encode("ascii")


def _post(client, path, pairs, limit):
    url = url_for(USE, "POST", path)
    return client.request(USE, "POST", url, body=_form(pairs), limit=limit)


# ---- 요청 셋: 교환·갱신·취소 ---------------------------------------------------------------------------------------------------------------------
def exchange_code(client, client_id, client_secret, code, verifier, redirect_uri, *, now):
    """로그인 코드 → `Tokens`(접근 토큰 + 갱신 토큰). 갱신 토큰이 없거나 범위가 기대와 다르면 `BLOGGER_LOGIN_FAILED`(저장하지 않는다 — 접근 토큰만으로 '연결됨' 이 되지 않는다)."""
    capabilities.require_net(USE, "Blogger 로그인 코드 교환")
    response = _post(client, "/token", [("client_id", client_id), ("client_secret", client_secret), ("code", code), ("code_verifier", verifier), ("grant_type", "authorization_code"),
                                       ("redirect_uri", redirect_uri)], TOKEN_LIMIT)
    if not response.ok:
        raise _failure(response, refresh=False)
    data = response.json()
    if not isinstance(data, dict):
        raise _bad_shape("object")
    if not _scope_ok(data, required=True):
        raise login_failed(REASON_SCOPE)
    access = _access_from(data, now)
    if data.get("refresh_token") is None:
        raise login_failed(REASON_NO_VALUE)
    return Tokens(access, Secret(_token_text(data, "refresh_token", 20, 512)))


def refresh_access_token(client, client_id, client_secret, refresh_token, *, now):
    """갱신 토큰 → 새 `AccessToken`. 토큰이 거절되면(`invalid_grant`) `BLOGGER_AUTH_EXPIRED` — 자동으로 다시 로그인하지 않는다."""
    capabilities.require_net(USE, "Blogger 토큰 갱신")
    response = _post(client, "/token", [("client_id", client_id), ("client_secret", client_secret), ("grant_type", "refresh_token"), ("refresh_token", refresh_token)], TOKEN_LIMIT)
    if not response.ok:
        raise _failure(response, refresh=True)
    data = response.json()
    if not isinstance(data, dict):
        raise _bad_shape("object")
    if not _scope_ok(data, required=False):
        raise login_failed(REASON_SCOPE)
    return _access_from(data, now)


def revoke_token(client, token):
    """토큰 취소(F 요청) → 취소했거나 이미 무효였으면 True. 응답 본문은 상한 안에서 버린다. 200·400 이 성공이고 그 밖은 오류다."""
    capabilities.require_net(USE, "Blogger 토큰 취소")
    response = _post(client, "/revoke", [("token", token)], REVOKE_LIMIT)
    if response.status in (200, 400):
        return True
    if response.status == 429:
        raise NetError("API_RATE_LIMITED", {}, detail=f"{USE}:status:429", use=USE)
    if response.status >= 500:
        raise NetError("BLOGGER_SERVER_ERROR", {}, detail=f"{USE}:status:{response.status}", use=USE, outcome_unknown=True)
    raise invalid(USE, REASON_SHAPE, phase=f"status:{response.status}")


__all__ = ["AUTH_HOST", "AUTH_KEYS", "AUTH_PATH", "AccessToken", "LISTENER_REASON", "LoginRequest", "REASONS", "SCOPE", "Secret", "Tokens", "begin_login", "build_auth_url", "challenge_of", "check_auth_url",
           "exchange_code", "login_failed", "new_state", "new_verifier", "redirect_uri_for", "refresh_access_token", "revoke_token"]
