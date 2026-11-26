"""브라우저가 열 수 있는 주소의 **모양 표**(BLOGGER 설계서 3.9, 결정 D-776) — 순수 함수(PySide6 를 모른다).

앱이 시스템 기본 브라우저로 여는 주소는 **세 가지 모양뿐**이다. 열기 함수(`ui/qt/shell.py::qt_open_url`·`ui/qt/components.py` 의 출처 링크 열기)가 `check_open_url` 을 **먼저** 지나게 하면
호출하는 쪽의 검사에만 기대지 않고 열기 함수 안쪽에서도 한 번 더 본다 — 그 연결은 화면 갈래가 맡는다(이 갈래는 Qt 코드를 건드리지 않는다). 허용하는 모양:
  · **구글 로그인**(`KIND_LOGIN`) — https · 호스트 `accounts.google.com` · 포트 없음 또는 443 · 길 `/o/oauth2/v2/auth` · 사용자 정보·조각 없음 · 2,000자 이하 · 공백·제어 문자·비 ASCII 없음 ·
    질의 키는 `client_id`·`redirect_uri`·`response_type`·`scope`·`state`·`code_challenge`·`code_challenge_method`·`access_type`·`prompt` 아홉 가지가 **각각 한 번**.
  · **네이버 글쓰기**(`KIND_NAVER_WRITE`) — `draft_rules.naver_write_url` 이 만드는 모양(https · 호스트 `blog.naver.com` · 길은 아이디 한 토막 · 질의는 글쓰기 표시 하나)과 글자까지 같다.
  · **이미지 출처 링크**(`KIND_UNSPLASH`) — `attribution.check_url` 이 받는 Unsplash 의 https 주소.
그 밖은 전부 거절한다: `file:`·`javascript:`·`ms-settings:`·평문 http·다른 호스트·UNC(`\\\\서버`)·너무 긴 글·공백이나 제어 문자가 든 글. 이 표는 로그인 주소를 만드는 쪽(`publish/blogger_auth.py` 의 `check_auth_url`)과 **따로 적었다** — 두 곳이 같은 말을 해야 열린다(시험이 견준다).
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from . import attribution, draft_rules

KIND_LOGIN, KIND_NAVER_WRITE, KIND_UNSPLASH = "login", "naver_write", "unsplash"
KINDS = (KIND_LOGIN, KIND_NAVER_WRITE, KIND_UNSPLASH)
MAX_URL = 2000
LOGIN_HOST = "accounts.google.com"
LOGIN_PATH = "/o/oauth2/v2/auth"
LOGIN_KEYS = ("client_id", "redirect_uri", "response_type", "scope", "state", "code_challenge", "code_challenge_method", "access_type", "prompt")


def _plain(url):
    """열기 전 공통 검사 — 글이고 비어 있지 않고 2,000자 이하이며 ASCII 만, 공백·제어 문자 없음."""
    return isinstance(url, str) and 0 < len(url) <= MAX_URL and url.isascii() and not any(ch <= " " or ch == "\x7f" for ch in url)


def _is_login(url):
    try:
        parts = urlsplit(url)
        port = parts.port
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    if parts.scheme != "https" or parts.hostname != LOGIN_HOST or port not in (None, 443) or parts.username is not None or parts.password is not None or "@" in parts.netloc or parts.fragment:
        return False
    return parts.path == LOGIN_PATH and sorted(key for key, _value in pairs) == sorted(LOGIN_KEYS)


def _is_naver_write(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https" or parts.hostname != "blog.naver.com" or "@" in parts.netloc:
        return False
    return draft_rules.naver_write_url(f"https://blog.naver.com{parts.path}") == url


def _is_unsplash(url):
    try:
        return attribution.check_url(url) == url
    except attribution.CreditError:
        return False


def check_open_url(url):
    """주소 → 허용 모양의 이름(`KIND_*`), 허용하지 않으면 None."""
    if not _plain(url):
        return None
    if _is_login(url):
        return KIND_LOGIN
    if _is_naver_write(url):
        return KIND_NAVER_WRITE
    if _is_unsplash(url):
        return KIND_UNSPLASH
    return None


__all__ = ["KINDS", "KIND_LOGIN", "KIND_NAVER_WRITE", "KIND_UNSPLASH", "LOGIN_KEYS", "check_open_url"]
