"""발행 기록·작업 로그 화면(글 흐름 1b, 결정 D-649·D-650)이 아는 값과 순수 규칙 — 공급자가 돌려주는 모양과 한 줄을 만드는 규칙. PySide6 도 파일도 서비스도 시계도 모른다.

  · 발행 기록(`HistoryData`): 승인 이후 단계에 있는 (글, 플랫폼) 쌍의 줄들. 검토 전 상태(`BEFORE_REVIEWED`)만 빼고 모두 오른다 — 닫힌 목록이 아니라서 서비스에 새 상태가 생겨도 그 줄은
    상태 이름이 `알 수 없음` 으로 보일 뿐 화면이 죽지 않는다(D-653). 정렬은 오래된 순서가 기본이다(`sort_rows`).
  · 작업 로그(`WorkLogData`): 앱이 처리하지 못한 오류의 작은 기록을 칸(때·갈래·오류 이름·코드 위치)으로 쪼갠 줄들 — 서비스가 글자표를 통과한 줄만 준다. 화면은 칸마다 다시 가린 뒤 줄인다(D-93).
글(제목)·주소는 값 객체의 `repr` 에 나오지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...content import status as st

BEFORE_REVIEWED = frozenset({st.NOT_STARTED, st.DRAFT_GENERATED, st.REVIEW_REQUIRED})        # 서비스(`service/history.py`)와 같다 — 시험이 견준다. 이 셋 말고는 모두 발행 기록에 오른다
ORDERS = ("oldest", "newest")                                                              # 정렬: 오래된 순서(기본)·최신 순서
LOG_SOURCES = ("main", "thread", "unraisable", "slot", "qt")                                # 작업 로그 줄의 갈래(쓰는 쪽이 정한 고정 낱말 — 서비스의 `worklog.SOURCES` 와 같다)


@dataclass(frozen=True)
class HistoryEntry:
    project_id: str
    title: str = field(default="", repr=False)
    platform: str = ""
    status: str = ""
    revision: int = 1
    updated_at: str = ""                                     # 글을 마지막으로 고친 때(UTC 글)
    published_url: str = field(default="", repr=False)       # 발행 주소를 기록했으면 그 주소
    published_at: str = ""                                   # 발행 주소를 기록한 때(UTC 글)

    @property
    def key(self):
        """줄 하나를 가리키는 열쇠(글 번호와 플랫폼)."""
        return f"{self.project_id}:{self.platform}"

    @property
    def when(self):
        """줄의 때 — 발행 주소를 기록한 때, 없으면 글을 마지막으로 고친 때(UTC 글, 정렬에 쓴다)."""
        return self.published_at or self.updated_at or ""


@dataclass(frozen=True)
class HistoryData:
    rows: tuple = ()                                         # HistoryEntry
    unreadable: int = 0                                      # 읽을 수 없어 건너뛴 글의 수
    state: str = "ok"                                        # ok · missing(글 저장소 파일이 아직 없다 — 빈 목록)
    sample: bool = False
    offline: bool = False                                    # 예시에서만(실제 읽기는 네트워크를 쓰지 않는다)


@dataclass(frozen=True)
class LogEntry:
    at: str = ""                                             # 시각(UTC 글, `2026-11-24T05:30:12Z` 모양)
    source: str = ""                                         # 갈래(`LOG_SOURCES` 중 하나)
    name: str = ""                                           # 오류 클래스 이름
    places: tuple = ()                                       # 코드 위치들(가장 안쪽이 먼저)


@dataclass(frozen=True)
class WorkLogData:
    lines: tuple = ()                                        # LogEntry — 최신이 먼저
    files: int = 0
    skipped: int = 0                                         # 모양이 달라 건너뛴 줄·파일의 수(내용은 어디에도 없다)
    older: int = 0                                           # 한도 때문에 보이지 않는 오래된 줄의 수
    sample: bool = False


def sort_rows(rows, order="oldest"):
    """발행 기록 줄들을 때 순서로 — `oldest`(오래된 것이 위, 기본)·`newest`(최신이 위). 같은 때는 글 번호·플랫폼으로 정해 늘 같은 순서다. 때가 없는(빈 글) 줄은 가장 오래된 쪽에 선다. 다른 값이면 오래된 순서다."""
    ordered = sorted(rows, key=lambda row: (row.when, row.project_id, row.platform))
    return list(reversed(ordered)) if order == "newest" else ordered


__all__ = ["BEFORE_REVIEWED", "HistoryData", "HistoryEntry", "LOG_SOURCES", "LogEntry", "ORDERS", "WorkLogData", "sort_rows"]
