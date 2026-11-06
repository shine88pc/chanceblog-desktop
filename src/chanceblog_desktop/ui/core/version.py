"""앱 버전 — `VERSION` 파일을 읽어 화면에 보일 글(`v0.0.0` 꼴)과 출처를 정하는 순수 규칙(UI-C1a, D-173). PySide6 를 불러오지 않는다.

- 읽으면 `v` + 번호(예 `v0.0.0`), 못 읽으면(파일 없음·읽기 실패·모양이 번호가 아님) 개발 화면에는 `개발 버전`.
- **Release 에서는 못 읽는 것을 오류로 잡는다**(`release_problem`) — Release 판정은 묶음 실행 파일(`sys.frozen`) 이거나 환경 변수 `CHANCEBLOG_RELEASE=1` 일 때다. 릴리스 도구는 아직 없어 이 묶음은 함수·시험·문서까지 하고, 앱 시작(`ui/launcher.py`)이 Release 인데 못 읽으면 쉬운 한국어 안내로 끝낸다.
- 새 오류 코드를 만들지 않는다(시작 때 한 번 보이는 안내 글뿐 — 카탈로그에 올릴 실패 경로가 아니다).
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .text import T

RELEASE_ENV = "CHANCEBLOG_RELEASE"
SOURCE_FILE = "file"                                   # VERSION 파일에서 읽음
SOURCE_DEV = "dev"                                     # 못 읽어 개발 표시
_NUMBER = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?")      # 0.0.0 · 0.1.0-beta · 1.0.0+3 (공백·줄바꿈·글 없음)


@dataclass(frozen=True)
class VersionInfo:
    text: str                                          # 화면에 보일 글 — `v0.0.0` 또는 `개발 버전`
    source: str                                        # `file` 또는 `dev`

    @property
    def known(self):
        return self.source == SOURCE_FILE


def default_path():
    """저장소 맨 위 폴더의 `VERSION` — `ui/core/version.py` 에서 네 단계 위."""
    return Path(__file__).resolve().parents[4] / "VERSION"


def parse_version(raw):
    """파일 내용 → 번호(`0.0.0` 꼴) 또는 None. 앞뒤 공백·줄바꿈만 허용하고 안에 다른 글이 있으면 못 읽은 것으로 본다(이상한 글을 화면에 그대로 내보내지 않는다)."""
    if not isinstance(raw, str):
        return None
    number = raw.lstrip("\ufeff").strip()                # 메모장 등이 맨 앞에 붙이는 UTF-8 BOM(보이지 않는 글자)은 번호가 아니다
    return number if _NUMBER.fullmatch(number) else None


def read_version(path=None, *, reader=None):
    """버전 글과 출처를 정한다 — `reader(path)` 는 시험에서 파일 대신 쓰는 읽개(없으면 UTF-8 로 읽는다 — 맨 앞의 BOM 은 있어도 없어도 같다). 어떤 읽기 실패도 예외로 번지지 않고 `개발 버전` 이 된다."""
    target = Path(path) if path is not None else default_path()
    try:
        raw = reader(target) if reader is not None else target.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError, ValueError):
        raw = None
    number = parse_version(raw)
    if number is None:
        return VersionInfo(T["dev_version"], SOURCE_DEV)
    return VersionInfo(f"v{number}", SOURCE_FILE)


def is_release(environ=None, frozen=None):
    """Release 인가 — 묶음 실행 파일(`sys.frozen` 참)이거나 환경 변수 `CHANCEBLOG_RELEASE` 가 정확히 `1` 일 때. 그 밖의 값(`true`·`0`·빈 글)은 개발로 본다(켜진 줄 알았는데 꺼진 것보다 안전한 쪽이 아니라 **명확한 한 값**만 인정한다)."""
    env = os.environ if environ is None else environ
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    return bool(frozen) or env.get(RELEASE_ENV) == "1"


def release_problem(info, release):
    """Release 인데 버전을 못 읽었으면 쉬운 한국어 안내 글, 아니면 None(개발 화면은 `개발 버전` 으로 계속)."""
    if release and not info.known:
        return T["version_release_error"]
    return None
