"""글자 읽기(사진 속 글자 읽기, 결정 D-512)가 돌려준 줄을 **후보로 다듬는** 순수 규칙 — 작업자가 보낸 줄(글) 목록 -> 확인 전 후보 줄들 + 거른 개수.
순수 파이썬이다 — 파일·네트워크·시계·무작위·표준 출력을 쓰지 않는다. 같은 입력은 늘 같은 결과다. 작업자 프로세스·약속(프로토콜)·화면은 이 파일이 모른다(`ui/ocr_adapter.py`·`ui/core/ocr_protocol.py`).

운영자 승인(확인 026 ②·028 ②, 이슈 #225·#232): 읽은 글은 **확인하기 전에는 사실이 아니다**. 그래서 이 규칙은 글을 해석하거나 구조화하지 않고(가격·메뉴 칸 없음), 지어내지 않고, 줄의 순서도 바꾸지 않는다 —
작업자가 낸 위에서 아래·왼쪽에서 오른쪽 순서 그대로다. 하는 일은 다듬기뿐이다:
  · 한 줄로 정리한다(제어·보이지 않는 글자를 지우고 공백을 하나로 접는다 — `clean_line`). 정리하고 나니 빈 줄이면 조용히 뺀다(`blank`).
  · 같은 글의 줄이 또 나오면 처음 것만 남긴다(`duplicates`).
  · 기존 입구 검사(`photo_manifest.check_text('observation')` — 200자 한도·보이지 않는 글자·태그·`{{ }}`·키·토큰 모양·주민/카드 번호 모양)에 걸린 줄은 **글을 되풀이하지 않고 개수만** 센다(`filtered` — 사용자에게는 '보여 드리지 않았어요').
  · 줄 수가 한도(`MAX_LINES` — 읽은 글자 칸의 한도 60개)를 넘으면 처음 한도까지만 남기고 나머지는 개수만 센다(`over_limit`).
`set_analysis` 가 같은 검사를 한 번 더 한다(플러그인 출력은 믿지 않는다는 기존 규칙) — 여기서 이미 걸러 두므로 거기서 더 버려지는 것은 없어야 하고, 있으면 `filtered` 에 더한다.
`OcrLines` 는 글을 `repr` 에 내지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from . import photo_manifest as pm
from .profiles import clean_line

METHOD = "local:rapidocr-ko-v5"                  # 분석 방법 이름 — 기존 정규식 `local:[a-z0-9][a-z0-9._-]{0,39}` 를 통과한다(메모리에서만 쓰고 저장할 때는 `manual` 로 쓴다)
MAX_LINES = pm.MAX_TEXT_ITEMS                    # 한 사진의 읽은 글자 줄 수 한도(한도 상수 분리 — 대상 칸의 20개와 따로)
MAX_LINE_CHARS = pm.MAX_OBSERVATION_CHARS        # 줄당 글자 수 한도(200)
_DIGIT = re.compile(r"[0-9０-９]")


@dataclass(frozen=True)
class OcrLines:
    """다듬은 결과 — 확인 전 후보 줄들(`texts`)과 개수들. 글은 `repr` 에 나오지 않는다."""
    texts: tuple = field(default=(), repr=False)
    filtered: int = 0          # 입구 검사에 걸려(너무 길거나 개인 번호·키 모양 …) 보이지 않는 줄 수 — 글은 되풀이하지 않는다
    over_limit: int = 0        # 줄 수 한도를 넘어 잘린 줄 수
    blank: int = 0             # 정리하고 나니 빈 줄이라 뺀 수
    duplicates: int = 0        # 같은 글이 또 나와서 뺀 수

    @property
    def found(self):
        """보여 줄 줄 수."""
        return len(self.texts)

    @property
    def hidden(self):
        """사용자에게 '보여 드리지 않았어요' 로 알릴 줄 수(입구 검사에 걸린 것만 — 빈 줄·되풀이는 알리지 않는다)."""
        return self.filtered

    @property
    def truncated(self):
        return self.over_limit > 0


def _text_of(raw):
    """작업자 줄 하나(글 또는 `{text: …}` 모양)에서 글만 꺼낸다 — 글이 아니면 None. 좌표 같은 다른 칸은 보지 않는다(줄 합치기·정렬에도 쓰지 않는다)."""
    value = raw.get("text") if isinstance(raw, dict) else raw
    return value if isinstance(value, str) else None


def prepare(raw_lines, limit=MAX_LINES):
    """작업자가 보낸 줄들 -> `OcrLines`. 순서는 그대로, 한 줄씩 위의 규칙으로 다듬는다. 목록이 아니면(None 포함) 빈 결과다."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        limit = MAX_LINES
    limit = min(limit, MAX_LINES)
    texts, seen = [], set()
    filtered = over = blank = duplicates = 0
    for raw in (raw_lines if isinstance(raw_lines, (list, tuple)) else ()):
        value = _text_of(raw)
        if value is None:
            filtered += 1
            continue
        if not clean_line(value):
            blank += 1
            continue
        clean, reason = pm.check_text("observation", value)
        if reason is not None:
            filtered += 1
            continue
        if clean in seen:
            duplicates += 1
            continue
        if len(texts) >= limit:
            over += 1
            continue
        seen.add(clean)
        texts.append(clean)
    return OcrLines(tuple(texts), filtered, over, blank, duplicates)


def apply(manifest, photo_id, raw_lines, limit=MAX_LINES):
    """읽은 줄을 사진 한 장의 **확인 전** 후보로 채운다 -> `(새 목록, OcrLines)`. 이전 결과는 모두 대체되고 사진의 확정은 풀린다(`set_analysis` 의 규칙).
    `set_analysis` 가 더 버린 줄이 있으면 `filtered` 에 더한다."""
    result = prepare(raw_lines, limit)
    updated, dropped = pm.set_analysis(manifest, photo_id, method=METHOD, texts=result.texts)
    return updated, (replace(result, filtered=result.filtered + dropped) if dropped else result)


def has_digits(texts):
    """줄들 중 숫자(가격·날짜·전화번호일 수 있는)가 하나라도 있나 — '숫자는 꼭 사진과 다시 견주어 주세요' 안내를 보일지 가리는 데만 쓴다(글은 되풀이하지 않는다)."""
    return any(_DIGIT.search(text) for text in texts if isinstance(text, str))


__all__ = ["MAX_LINES", "MAX_LINE_CHARS", "METHOD", "OcrLines", "apply", "has_digits", "prepare"]
