"""안내(토스트) 규칙 — 한 번에 하나만 보이고, 같은 안내가 보이는 동안 또 오면 쌓지 않고 보이는 시간만 늘린다. PySide6 를 모른다.

`offer(text)` 가 무엇을 해야 하는지 돌려준다: `show`(새로 보인다 — 다른 안내가 떠 있었어도 그 자리를 바꾼다) · `extend`(같은 안내라 시간만 늘린다) · `ignore`(빈 글).
보이는 시간은 3~4초(`tokens.TOAST_MS`).
"""
from __future__ import annotations

from .text import display_text
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
        text = display_text(text or "", MAX_CHARS)              # 안내가 화면에 나가는 한 지점 — 비밀 모양을 가린 뒤 한 줄로 줄인다(`text.display_text`, 가리기가 먼저)
        if not text:
            return "ignore", ""
        if self.current == text:
            return "extend", text
        self.current = text
        self.shown += 1
        return "show", text

    def expire(self):
        self.current = ""
