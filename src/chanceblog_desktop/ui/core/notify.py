"""안내(토스트) 규칙 — 한 번에 하나만 보이고, 같은 안내가 보이는 동안 또 오면 쌓지 않고 보이는 시간만 늘린다. PySide6 를 모른다.

`offer(text)` 가 무엇을 해야 하는지 돌려준다: `show`(새로 보인다 — 다른 안내가 떠 있었어도 그 자리를 바꾼다) · `extend`(같은 안내라 시간만 늘린다) · `ignore`(빈 글).
보이는 시간은 3~4초(`tokens.TOAST_MS`).
"""
from __future__ import annotations

from .tokens import TOAST_MS

MAX_CHARS = 120


class ToastPolicy:
    def __init__(self, duration_ms=TOAST_MS):
        if not 3000 <= duration_ms <= 4000:
            raise ValueError("토스트는 3~4초 동안 보인다")
        self.duration_ms = duration_ms
        self.current = ""
        self.shown = 0                 # 새로 보인 횟수(시험·진단용)

    def offer(self, text):
        text = " ".join(str(text or "").split())
        if not text:
            return "ignore", ""
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS - 1] + "…"
        if self.current == text:
            return "extend", text
        self.current = text
        self.shown += 1
        return "show", text

    def expire(self):
        self.current = ""
