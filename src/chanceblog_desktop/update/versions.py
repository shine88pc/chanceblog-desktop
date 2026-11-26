"""버전 비교 — 업데이트가 '새 버전인가·같은가·낮은가' 를 정하는 순수 규칙(UPDATE 설계서 3-1, 3-6). 접속·파일·시계가 없다.

모양은 `packaging/pkgcommon.py` 의 `VERSION_PATTERN`(`ui/core/version.py` 의 번호 모양과 같다)의 **부분집합**이다 — 숫자는 ASCII 0–9 만(전각·아라비아 숫자 거절), 앞자리 0 없음,
사전판(`-rc.1`)과 빌드 표시(`+3`)는 SemVer 2.0 규칙(빈 토막 없음, 숫자 토막에 앞자리 0 없음)이고 접미사 전체가 `VERSION_PATTERN` 의 길이 한도(맨 앞 글자 + 30자)를 넘지 않는다.
순서는 SemVer 2.0 의 우선순위 규칙이다: 숫자 셋을 숫자로 견주고, 사전판이 있으면 같은 숫자의 정식보다 낮고, 사전판 토막은 왼쪽부터 견주되 숫자 토막은 숫자로(`rc.2` 가 `rc.10` 보다 낮다)
숫자 토막은 글자 토막보다 낮으며 토막이 더 많은 쪽이 높다. 빌드 표시는 순서에 쓰지 않는다.
`service/backup_flow.py` 의 `_version_key` 와 숫자·정식·사전판(한 자리 숫자 토막까지)에서 같은 순서를 낸다 — 시험이 같음을 지킨다. 다만 그쪽은 사전판 글을 글자로 견줘 `rc.10` 이 `rc.2` 보다 낮다고 본다
(이 모듈이 옳다). 읽을 수 없는 글은 `parse_version` 이 None 이고 견주는 함수는 ValueError 로 알린다 — 호출하는 쪽(`manifest`·`update_flow`)이 틀린 값을 데이터로 넘기지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# `pkgcommon.VERSION_PATTERN` 과 같은 뼈대(ASCII 숫자만)이고, 시험이 두 모양의 관계를 지킨다
_SHAPE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?", re.ASCII)
_CORE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z][0-9A-Za-z.-]*))?(?:\+([0-9A-Za-z][0-9A-Za-z.-]*))?", re.ASCII)
_NUMERIC = re.compile(r"(0|[1-9][0-9]*)", re.ASCII)
MAX_TEXT_CHARS = 80                      # 읽기 전에 거르는 글 길이(어떤 값이 와도 정규식이 오래 돌지 않게)


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    pre: tuple                           # 사전판 토막들(글) — 정식이면 빈 튜플
    text: str                            # 읽은 원래 글(빌드 표시 포함)

    @property
    def is_prerelease(self):
        return bool(self.pre)

    def key(self):
        """순서 열쇠 — 튜플 비교가 SemVer 우선순위와 같다(빌드 표시는 들어가지 않는다)."""
        return (self.major, self.minor, self.patch, _pre_key(self.pre))


def _pre_key(pre):
    if not pre:
        return (1,)                      # 정식은 같은 숫자의 사전판보다 높다
    return (0, tuple((0, int(item), "") if item.isdigit() else (1, 0, item) for item in pre))


def parse_version(text):
    """글 → `Version` 또는 None(모양이 틀리거나 글이 아니거나 너무 긴 것). 예외를 내지 않는다."""
    if not isinstance(text, str) or not 5 <= len(text) <= MAX_TEXT_CHARS or _SHAPE.fullmatch(text) is None:
        return None
    found = _CORE.fullmatch(text)
    if found is None:
        return None
    pre = tuple(found.group(4).split(".")) if found.group(4) is not None else ()
    build = tuple(found.group(5).split(".")) if found.group(5) is not None else ()
    if any(item == "" for item in pre + build):
        return None                      # 빈 토막(`1.0.0-rc..1`, `1.0.0-rc.`)은 없다
    if any(item.isdigit() and _NUMERIC.fullmatch(item) is None for item in pre):
        return None                      # 숫자 토막의 앞자리 0(`rc.01`)은 없다
    return Version(int(found.group(1)), int(found.group(2)), int(found.group(3)), pre, text)


def is_valid(text):
    return parse_version(text) is not None


def _need(text):
    version = parse_version(text)
    if version is None:
        raise ValueError("버전 글의 모양이 틀리다")
    return version


def compare(left, right):
    """-1(왼쪽이 낮다)·0(같은 순서)·1(왼쪽이 높다). 읽을 수 없는 글이면 ValueError. 빌드 표시만 다른 두 버전은 같다."""
    one, two = _need(left).key(), _need(right).key()
    return (one > two) - (one < two)


def is_newer(candidate, current):
    """`candidate` 가 `current` 보다 **높은** 버전인가(같은 순서는 아니오)."""
    return compare(candidate, current) > 0


__all__ = ["MAX_TEXT_CHARS", "Version", "compare", "is_newer", "is_valid", "parse_version"]
