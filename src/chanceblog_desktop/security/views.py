"""훑기 앞의 정규화 — 같은 글을 **다르게 적은 모양**을 풀어서, 키·토큰 모양 훑기가 앱이 실제로 읽는 것과 같은 글을 보게 한다(결정 D-683, 앱 2차 감사 AS-S2 권고-3).

배경: 백업 복원 전의 비밀 모양 훑기는 칸의 바이트를 UTF-8 로만 풀었고(전체 백업) 아예 풀지 않았으며(주제 엔진 백업 — SQLite 덤프는 BLOB 을 16진수로 적는다), JSON 글은 원문 글자를 훑어 `\\uXXXX` 이스케이프를 못 봤다.
그런데 앱은 같은 칸을 `json.loads(바이트)` 로 읽고 — 그 함수는 UTF-16·UTF-32 를 알아서 알아본다 — JSON 글자의 이스케이프는 풀어서 쓴다. 그래서 UTF-16 로 쓴 BLOB 이나 `\\u0041KIA…` 로 쪼갠 가짜 키가 훑기를 지나
복원된 보관함에 들어올 수 있었다(감사가 직접 재현).

이 모듈은 **글자 하나 바꾸지 않고 보기만 늘린다**: `blob_views` 는 바이트 하나를 훑을 글 모양들로, `text_views`·`unescape_json` 은 글 하나의 풀린 모양으로 바꾼다. 부른 쪽은 모든 보기를 훑어 하나라도 걸리면 걸린 것으로 본다(보기만 늘 뿐
기존에 걸리던 것은 그대로 걸린다). 어떤 입력에도 예외를 내지 않는다 — 풀 수 없는 바이트는 대체 글자로 풀리고, 그래도 키 모양이 안 보이면 못 읽는 것이라 걸리지 않을 뿐 숨은 키가 지나가는 일은 없다(앱도 그 글을 읽지 못한다).
파일·네트워크·하위 프로세스를 쓰지 않는다.
"""
from __future__ import annotations

import json
import re

_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})|\\([\"\\/bfnrt])")
_SIMPLE = {'"': '"', "\\": "\\", "/": "/", "b": chr(8), "f": chr(12), "n": chr(10), "r": chr(13), "t": chr(9)}
_FIXED_CODECS = ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")


def blob_views(raw):
    """바이트 하나(BLOB)를 훑을 **글 모양들** — 서로 다른 것만 차례대로(제너레이터). ① UTF-8(옛 방식 — 그대로 먼저) ② 앱이 `json.loads(바이트)` 로 읽을 때와 같은 감지(`json.detect_encoding` — BOM·널 바이트 모양에서 UTF-16·UTF-32 를 알아본다)
    ③ 널 바이트를 뺀 글(영문이 UTF-16·UTF-32 로 쓰였으면 글자 사이의 널 바이트가 키 모양을 끊는다 — 감지가 어긋나도 걸리게) ④ UTF-16·UTF-32 의 두 바이트 순서로 푼 글.
    바이트가 아니면(None 포함) 아무것도 내지 않는다. 풀 수 없는 바이트는 대체 글자로 풀린다(예외 없음)."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        return
    raw = bytes(raw)
    seen = set()

    def fresh(text):
        if text in seen:
            return False
        seen.add(text)
        return True

    first = raw.decode("utf-8", "replace")
    seen.add(first)
    yield first
    try:
        detected = raw.decode(json.detect_encoding(raw), "replace")
    except (LookupError, UnicodeError, ValueError, IndexError):
        detected = None
    if detected is not None and fresh(detected):
        yield detected
    if b"\x00" in raw:                                      # 영문이 UTF-16·UTF-32 로 쓰였으면 널 바이트가 반드시 든다 — 널이 없으면 아래 보기들은 영문 키 모양을 만들 수 없어 건너뛴다(큰 BLOB 의 비용)
        stripped = raw.replace(b"\x00", b"").decode("utf-8", "replace")
        if fresh(stripped):
            yield stripped
        for codec in _FIXED_CODECS:
            view = raw.decode(codec, "replace")
            if fresh(view):
                yield view


def unescape_json(text):
    """JSON 글자 이스케이프(`\\uXXXX`·`\\n`·`\\/`·`\\\"` 같은 것)를 푼 글 — 풀 것이 없으면 같은 글 그대로. 서로게이트 쌍(`\\ud83d\\ude00`)은 한 글자로 합치고 짝이 안 맞는 것은 대체 글자로 둔다. 예외를 내지 않는다.
    `\\\\u0041`(역슬래시가 글자로 있는 글)도 풀어 보기에 넣는다 — 보기를 늘릴 뿐이라 과하게 풀어도 걸리는 것이 늘기만 한다."""
    if not isinstance(text, str) or "\\" not in text:
        return text

    def one(found):
        return chr(int(found.group(1), 16)) if found.group(1) is not None else _SIMPLE[found.group(2)]

    out = _ESCAPE.sub(one, text)
    try:
        return out.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    except (UnicodeError, ValueError):
        return out


def text_views(value):
    """글 하나(TEXT 칸의 값)를 훑을 보기들 — 글 그대로를 먼저, 널 글자가 들었으면 뺀 글, 이스케이프가 있으면 푼 글(서로 다른 것만). 글이 아니면 아무것도 내지 않는다."""
    if not isinstance(value, str):
        return
    yield value
    if "\x00" in value:
        yield value.replace("\x00", "")
    if "\\" in value:
        unescaped = unescape_json(value)
        if unescaped != value:
            yield unescaped


__all__ = ["blob_views", "text_views", "unescape_json"]
