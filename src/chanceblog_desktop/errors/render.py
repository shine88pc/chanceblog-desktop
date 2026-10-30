"""오류 코드 → 사용자에게 보일 문구, 그리고 앱 안의 모든 실패가 모이는 예외.

문구는 docs/TROUBLESHOOTING.md 의 것을 그대로 쓰고, `「이름」` 자리에만 값을 넣는다. 외부 응답(HTTP 본문 등)을
문구에 통째로 끼워 넣지 않는다 — 정해진 칸의 값만 길이·제어 문자를 정리해서 넣는다. 키·토큰 가리기는
보안 모듈(로그 마스킹)의 일이고 여기서는 하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import ErrorInfo
from .table import UNEXPECTED, lookup

UNKNOWN_SLOT = "알 수 없음"
MAX_SLOT_CHARS = 160

_SLOT = re.compile(r"「([^」]+)」")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")


def clean_slot(value):
    """자리표시자에 넣을 값을 한 줄의 짧은 글로 정리한다(제어 문자·굵은 글씨 표시·긴 값 제거)."""
    text = _CONTROL.sub(" ", str(value))
    text = " ".join(text.split()).replace("**", "").replace("「", "").replace("」", "")
    if len(text) > MAX_SLOT_CHARS:
        text = text[: MAX_SLOT_CHARS - 1] + "…"
    return text


@dataclass(frozen=True)
class Rendered:
    code: str
    message: str
    action: str
    retry_kind: str
    retry_max: int | None
    retry_text: str


def _fill(text, slots):
    def put(match):
        value = slots.get(match.group(1))
        shown = clean_slot(value) if value is not None else ""
        return "「" + (shown or UNKNOWN_SLOT) + "」"

    return _SLOT.sub(put, text).replace("**", "")


def render(code, slots=None):
    """코드와 자리표시자 값 → 화면에 보일 문구. 모르는 코드는 UNEXPECTED_ERROR 문구."""
    info = lookup(code)
    values = dict(slots or {})
    return Rendered(info.code, _fill(info.message, values), _fill(info.action, values), info.retry_kind, info.retry_max, info.retry)


class AppError(Exception):
    """앱 안의 실패는 오류 코드 하나로 모인다. `rendered()` 가 사용자 문구를 만든다.

    detail 은 개발자용 세부 메모다 — 화면에 그대로 내지 않고, 로그에 쓸 때는 마스킹을 거친다.
    표에 없는 코드는 UNEXPECTED_ERROR 로 받고 원래 요청한 코드는 requested_code 에 남긴다.
    """

    def __init__(self, code, slots=None, *, detail=""):
        self.info: ErrorInfo = lookup(code)
        self.code = self.info.code
        self.requested_code = code
        self.slots = dict(slots or {})
        self.detail = detail
        super().__init__(self.code)

    def rendered(self):
        return render(self.code, self.slots)

    def __str__(self):
        shown = self.rendered()
        return f"{self.code}: {shown.message}"


__all__ = ["AppError", "Rendered", "UNEXPECTED", "UNKNOWN_SLOT", "clean_slot", "render"]
