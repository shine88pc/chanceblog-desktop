"""응답을 **데이터로만** 읽는 순수 함수들(NET 설계서 3.9 R1–R9, D-726) — 접속 코드가 없다(`http`·`ssl`·소켓을 가져오지 않는다).

규칙: 본문은 크기를 먼저 보고 바이트로 받는다 → 글자로 바꾸는 것은 UTF-8 엄격 모드로 한 번(BOM·깨진 글자 거절) → JSON 은 같은 키가 둘이거나 `NaN`·`Infinity`·깊이 20 초과·정수 20자리 초과·문자열 100만 글자 초과면 거절
(아주 깊은 JSON 의 `RecursionError` 도 같은 오류로) → 용도별 모양(필드 이름·형·길이·정규식)을 쓰기 전에 검사하고 **모르는 필드는 버린다**. 응답 속 주소·글은 요청·경로·명령·문구에 쓰지 않는다 —
화면에 보일 주소는 `check_display_url` 을 지났을 때만 **글자로만** 보인다. 이 모듈의 오류(`ParseError`)는 이유 이름표만 갖고 응답의 글을 담지 않는다.
"""
from __future__ import annotations

import json
import math
import re
from urllib.parse import urlsplit

MAX_DEPTH = 20
MAX_INT_DIGITS = 20
MAX_STRING_CHARS = 1_000_000
MAX_HEADER_VALUE = 200
BOM = chr(0xFEFF)
_KEEP_EXACT = frozenset({"retry-after", "content-type", "content-length"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class ParseError(ValueError):
    """읽기 실패 — `reason` 은 고정 이름표(`utf8`·`bom`·`syntax`·`duplicate_key`·`constant`·`depth`·`integer`·`string`·`surrogate`·`float`)다. 응답의 글은 담지 않는다."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def decode_text(data):
    """바이트 → 글자(UTF-8 엄격). BOM 이 맨 앞에 있거나 깨진 글자가 있으면 `ParseError`."""
    if not isinstance(data, (bytes, bytearray)):
        raise ParseError("syntax")
    if bytes(data[:3]) == b"\xef\xbb\xbf":
        raise ParseError("bom")
    try:
        text = bytes(data).decode("utf-8", "strict")
    except UnicodeDecodeError:
        raise ParseError("utf8") from None
    if text.startswith(BOM):
        raise ParseError("bom")
    return text


def _pairs(items):
    keys = [key for key, _value in items]
    if len(keys) != len(set(keys)):
        raise ParseError("duplicate_key")
    return dict(items)


def _constant(_name):
    raise ParseError("constant")                 # NaN · Infinity · -Infinity


def _integer(text):
    if len(text.lstrip("-")) > MAX_INT_DIGITS:
        raise ParseError("integer")
    return int(text)


def _float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ParseError("float")
    return value


def _check_shape(root):
    """깊이·문자열 길이·글자 모양을 반복으로 훑는다(재귀 없음)."""
    stack = [(root, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise ParseError("depth")
        if isinstance(value, str):
            if len(value) > MAX_STRING_CHARS:
                raise ParseError("string")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ParseError("surrogate") from None
        elif isinstance(value, dict):
            for key, item in value.items():
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            for item in value:
                stack.append((item, depth + 1))


def read_json(data):
    """바이트 → JSON 값(엄격). 어떤 모양이 틀려도 `ParseError`(이유 이름표만) 하나로 끝난다 — 호출하는 쪽이 `NET_RESPONSE_INVALID` 로 바꾼다."""
    text = decode_text(data)
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_int=_integer, parse_float=_float)
    except ParseError:
        raise
    except RecursionError:
        raise ParseError("depth") from None
    except (ValueError, TypeError):
        raise ParseError("syntax") from None
    _check_shape(value)
    return value


# ---- 머리글 고르기(R8) ---------------------------------------------------------------------------------------------------
def _clean(value):
    return _CONTROL.sub(" ", str(value)).strip()[:MAX_HEADER_VALUE]


def pick_headers(items, extra=()):
    """받은 머리글 (이름, 값) 목록에서 **쓸 것만** 고른다: `retry-after`·`content-type`·`content-length`·`x-ratelimit-*` 와 용도가 더 고른 `extra`(이동 판정용 `location` 은 클라이언트가 따로 읽고 여기에 남기지 않는다).
    값은 제어 문자를 지우고 200자로 자른다. 같은 이름이 둘이면 처음 것만 남긴다."""
    picked = {}
    wanted = _KEEP_EXACT | frozenset(extra)
    for name, value in items:
        key = str(name).lower()
        if (key in wanted or key.startswith("x-ratelimit-")) and key not in picked:
            picked[key] = _clean(value)
    return picked


def retry_after_seconds(headers):
    """`Retry-After` 의 초(정수 1–86400)만 읽는다(날짜 모양은 읽지 않는다 → None)."""
    text = (headers or {}).get("retry-after", "")
    if text.isascii() and text.isdigit() and 0 < len(text) <= 6:
        seconds = int(text)
        if 1 <= seconds <= 86400:
            return seconds
    return None


# ---- 화면에 보일 주소(R4) ---------------------------------------------------------------------------------------------------
def check_display_url(value, *, hosts=None, max_chars=500):
    """응답 속 주소를 화면에 **글자로만** 보여도 되는가(R4) — https · 길이 500 이하 · 사용자 정보(`@`) 없음 · 공백·제어 문자 없음 · ASCII ·
    (`hosts` 가 주어지면 그 호스트 가운데 하나와 정확히 같음). 통과하면 그 글을, 아니면 빈 글을 돌려준다. 앱이 이 주소를 열거나 요청에 쓰지 않는다."""
    if not isinstance(value, str) or not value or len(value) > max_chars or not value.isascii():
        return ""
    if any(ch <= " " or ch == "\x7f" for ch in value):
        return ""
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme != "https" or not host or "@" in parts.netloc or port not in (None, 443) or parts.fragment:
        return ""
    if hosts is not None and host not in hosts:
        return ""
    return value


# ---- 용도별 모양 검사를 돕는 작은 도구(R3 — 쓰기 전에 모양을 보고 모르는 필드는 버린다) -----------------------------------------------------
def expect_object(value):
    if not isinstance(value, dict):
        raise ParseError("syntax")
    return value


def expect_text(obj, key, *, max_chars, pattern=None, required=True):
    """객체의 글 칸 하나를 검사해 돌려준다(없고 필수가 아니면 빈 글). 모양이 틀리면 `ParseError`. 다른 칸은 읽지도 않는다."""
    if key not in obj:
        if required:
            raise ParseError("syntax")
        return ""
    value = obj[key]
    if not isinstance(value, str) or len(value) > max_chars or (pattern is not None and re.fullmatch(pattern, value) is None):
        raise ParseError("syntax")
    return value


def expect_int(obj, key, *, low, high, required=True):
    if key not in obj:
        if required:
            raise ParseError("syntax")
        return None
    value = obj[key]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ParseError("syntax")
    return value


__all__ = ["MAX_DEPTH", "MAX_INT_DIGITS", "MAX_STRING_CHARS", "ParseError", "check_display_url", "decode_text", "expect_int", "expect_object", "expect_text", "pick_headers", "read_json", "retry_after_seconds"]
