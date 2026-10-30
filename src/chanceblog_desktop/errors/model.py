"""오류 안내의 자료 모양과 '재시도' 칸 해석.

정본은 docs/TROUBLESHOOTING.md 의 표다. 표의 '재시도' 칸은 아래 몇 가지 문구만 쓸 수 있고,
다른 문구를 쓰면 여기서 바로 실패한다(문서가 조용히 어긋나지 않게).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RETRY_NO = "no"              # 아니오 — 앱이 다시 하지 않는다
RETRY_AUTO = "auto"          # 예… — 앱이 자동으로 다시 해 본다(횟수 제한이 있으면 retry_max)
RETRY_AFTER = "after_user"   # 로그인 뒤·고친 뒤… — 사용자가 조치한 뒤에 다시 한다
RETRY_OPTIONAL = "optional"  # 선택 — 다시 할 필요가 없다(그 기능만 건너뛴다)

RETRY_KINDS = (RETRY_NO, RETRY_AUTO, RETRY_AFTER, RETRY_OPTIONAL)

_AFTER_USER = frozenset({"로그인 뒤", "고친 뒤", "해결 뒤", "시각 이후"})
_AUTO = re.compile(r"^예(?:\((?:최대 )?(\d+)회\)|\((?:자동 재확인|자동|연결되면)\))?$")
_SLOT = re.compile(r"「([^」]+)」")


def parse_retry(text):
    """'재시도' 칸 문구 → (종류, 최대 횟수 또는 None). 모르는 문구는 ValueError."""
    text = text.strip()
    if text == "아니오":
        return RETRY_NO, None
    if text in _AFTER_USER:
        return RETRY_AFTER, None
    if text == "선택":
        return RETRY_OPTIONAL, None
    match = _AUTO.match(text)
    if match:
        return RETRY_AUTO, int(match.group(1)) if match.group(1) else None
    raise ValueError(f"해석할 수 없는 재시도 칸: {text!r}")


def slot_names(*texts):
    """문구 속 `「이름」` 자리표시자의 이름을 처음 나온 순서대로(중복 없이)."""
    names = []
    for text in texts:
        for name in _SLOT.findall(text):
            if name not in names:
                names.append(name)
    return tuple(names)


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    area: str                # 표가 속한 절 제목(예: Blogger)
    when: str                # 언제 이 코드가 되는가
    message: str             # 사용자 문구(자리표시자 포함)
    action: str              # 하실 일(자리표시자 포함)
    retry: str               # 재시도 칸 원문
    retry_kind: str
    retry_max: int | None

    @property
    def slots(self):
        return slot_names(self.message, self.action)
