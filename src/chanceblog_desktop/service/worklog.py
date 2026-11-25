"""작업 로그 읽기(글 흐름 1b, 결정 D-650) — 앱이 처리하지 못한 오류가 났을 때 남긴 작은 기록(`logs/errors.log` 와 돌려쓰기 `.1`·`.2`, `security/errorlog.py` 가 쓴다)을 **읽기만** 한다.

기록의 한 줄은 `시각(UTC) 갈래 오류이름 파일:줄 < 파일:줄 …` 이다. 이 함수는 줄을 **그대로 내보내지 않는다**(결정 D-93 — 키·토큰·끝 4자도 안 보인다):
  · 줄을 칸(때·갈래·오류 이름·코드 위치들)으로 쪼개 **쓰는 쪽과 같은 글자표**(영문·숫자·밑줄·점·붙임표·물음표, 갈래는 고정 낱말 다섯)를 통과한 줄만 낸다. 사람이 고쳤거나 깨진 줄·글자표 밖의 줄은 **건너뛰고 개수만** 알린다.
  · 있는 파일만 읽는다(없으면 만들지 않는다). 파일 하나는 쓰는 쪽 한도(256 KB)의 두 배까지만 읽고 그보다 크면 그 파일은 건너뛴다. 링크(심볼릭)는 따라가지 않는다. 최근 `MAX_LINES` 줄만 낸다(오래된 줄은 개수로).
  · 쓰지 않는다: 지우기·고치기·내보내기·이름 바꾸기가 없다. 네트워크·하위 프로세스 0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..security import errorlog
from ..security.mask import mask

MAX_LINES = 200                                                     # 화면에 내는 최근 줄 수
MAX_FILE_BYTES = 2 * errorlog.MAX_BYTES                              # 한 파일에서 읽는 최대 바이트(쓰는 쪽 한도의 두 배)
SOURCES = frozenset(errorlog.SOURCES)                                # 갈래 — 쓰는 쪽이 정한 고정 낱말 다섯
_PLACE = r"[A-Za-z0-9_?][A-Za-z0-9_.\-]{0,63}(?::\d{1,7})?"           # 코드 위치(파일:줄) 또는 Qt 분류 이름 — 쓰는 쪽 글자표
_LINE = re.compile(r"(?P<at>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) (?P<source>[a-z]{2,12}) (?P<name>[A-Za-z_][A-Za-z0-9_]{0,63}) (?P<places>-|" + _PLACE + r"(?: < " + _PLACE + r"){0,11})")


@dataclass(frozen=True)
class WorkLogLine:
    at: str                         # 시각(UTC, `2026-11-24T05:30:12Z` 모양)
    source: str                     # 갈래(`main`·`thread`·`unraisable`·`slot`·`qt`)
    name: str                       # 오류 클래스 이름
    places: tuple                   # 코드 위치들(가장 안쪽이 먼저)

    def to_dict(self):
        return {"at": self.at, "source": self.source, "name": self.name, "places": list(self.places)}


@dataclass(frozen=True)
class WorkLog:
    lines: tuple                    # WorkLogLine — 최신이 먼저, 최대 `MAX_LINES`
    files: int                      # 읽은 파일 수
    skipped: int                    # 모양이 달라 건너뛴 줄과 너무 커서 건너뛴 파일의 수(내용은 어디에도 없다)
    older: int                      # 한도 때문에 내지 않은 오래된 줄의 수

    def to_dict(self):
        return {"lines": [line.to_dict() for line in self.lines], "files": self.files, "skipped": self.skipped, "older": self.older}


def _parse(text):
    """줄 하나 → `WorkLogLine`(글자표 밖이거나 가리기 엔진이 건드리는 줄이면 None). 쓰는 쪽은 줄을 `mask` 에 한 번 거쳐 쓰므로 정상 줄은 `mask` 를 거쳐도 그대로다 —
    키·토큰 모양이 든 줄(사람이 고쳐 넣은 줄)은 글자표를 통과하더라도 건드려져서 여기서 걸러진다(어느 칸도 내지 않는다)."""
    found = _LINE.fullmatch(text.strip())
    if found is None or found.group("source") not in SOURCES or mask(text.strip()) != text.strip():
        return None
    places = () if found.group("places") == "-" else tuple(found.group("places").split(" < "))
    return WorkLogLine(found.group("at"), found.group("source"), found.group("name"), places)


def _read_file(path):
    """파일 하나의 글(없거나 링크이거나 파일이 아니면 None, 너무 크면 False)."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > MAX_FILE_BYTES:
            return False                                              # 쓰는 쪽 한도의 두 배를 넘는 파일은 읽지 않는다
        raw = path.read_bytes()
    except OSError:
        return False                                                  # 읽을 수 없다 — 건너뛴다(오류를 내서 화면 전체를 막지 않는다)
    return False if len(raw) > MAX_FILE_BYTES else raw.decode("utf-8", errors="replace")


def read_work_log(ctx, *, limit=MAX_LINES):
    """작업 로그의 최근 줄들 → `WorkLog`(읽기만 — 파일도 폴더도 만들지 않는다). 기록이 없으면 빈 결과다."""
    folder = ctx.workspace.root / errorlog.FOLDER_NAME
    names = [f"{errorlog.FILE_NAME}.{number}" for number in range(errorlog.BACKUPS, 0, -1)] + [errorlog.FILE_NAME]          # 오래된 것(.2)부터
    parsed, files, skipped = [], 0, 0
    for name in names:
        text = _read_file(folder / name)
        if text is None:
            continue
        if text is False:
            skipped += 1
            continue
        files += 1
        for raw in text.splitlines():
            if not raw.strip():
                continue
            line = _parse(raw)
            if line is None:
                skipped += 1
            else:
                parsed.append(line)
    newest_first = parsed[::-1]
    return WorkLog(tuple(newest_first[:limit]), files, skipped, max(0, len(newest_first) - limit))
