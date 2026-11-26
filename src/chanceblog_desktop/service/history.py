"""발행 기록 읽기(글 흐름 1b, 결정 D-649) — 글 저장소를 **한 번만 열어** 승인 이후 단계에 있는 (글, 플랫폼) 쌍의 상태·발행 주소·때를 모두 읽는다. 읽기만 한다.

`projects.list_projects` 는 글마다 플랫폼 상태만 주고 발행 주소·시각이 없어서, 글을 하나씩 다시 읽으면(`show_project`) 글 저장소를 글 수만큼 열고 원고 전문(최대 2MB)도 매번 읽게 된다.
이 함수는 글을 한 번씩만 읽어 화면에 필요한 작은 값만 낸다(원고는 담지 않는다).

**닫힌 목록으로 못박지 않는다**: 검토 전 상태(`BEFORE_REVIEWED` — 시작 전·글 만듦·검토 중)만 빼고 **나머지는 모두** 낸다. 그래서 서비스에 새 상태가 생겨도(예: 병합 대기) 이 함수는 그 줄을 그대로 낸다.
읽을 수 없는 글(깨진 행 등)은 건너뛰고 개수만 알린다 — 한 글이 목록 전체를 막지 않는다. 글 저장소 파일이 없으면 CONTENT_NOT_FOUND(읽기 전용 컨텍스트는 파일을 만들지 않는다).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..content import status as st
from ..errors import AppError

BEFORE_REVIEWED = frozenset({st.NOT_STARTED, st.DRAFT_GENERATED, st.REVIEW_REQUIRED})        # 아직 승인 전 — 발행 기록에 오르지 않는다(이 셋 말고는 모두 오른다)


@dataclass(frozen=True)
class HistoryRow:
    project_id: str
    title: str
    platform: str
    status: str
    revision: int
    updated_at: str                 # 글을 마지막으로 고친 때(UTC, `2026-11-24T05:30:12Z` 모양)
    published_url: str = ""         # 발행 주소를 기록했으면 그 주소('' 이면 없다)
    published_at: str = ""          # 발행 주소를 기록한 때('' 이면 없다)

    def to_dict(self):
        return {"project_id": self.project_id, "title": self.title, "platform": self.platform, "status": self.status, "revision": self.revision, "updated_at": self.updated_at,
                "published_url": self.published_url, "published_at": self.published_at}


@dataclass(frozen=True)
class History:
    rows: tuple                     # HistoryRow
    unreadable: int                 # 읽을 수 없어 건너뛴 글의 수

    def to_dict(self):
        return {"rows": [row.to_dict() for row in self.rows], "unreadable": self.unreadable}


def list_history(ctx):
    """승인 이후 단계에 있는 (글, 플랫폼) 쌍을 모두 → `History`(순서는 정하지 않는다 — 보이는 쪽이 정한다). 글 저장소를 한 번 열어 읽기만 한다."""
    rows, unreadable = [], 0
    with ctx.store() as store:
        for summary in store.list():
            try:
                project = store.load(summary.project_id)
            except AppError:
                unreadable += 1
                continue
            for platform in st.PLATFORMS:
                variant = project.variants.get(platform)
                if variant is None or variant.status in BEFORE_REVIEWED:
                    continue
                rows.append(HistoryRow(project.project_id, project.title, platform, variant.status, project.revision, project.updated_at, variant.published_url or "", variant.published_at or ""))
    return History(tuple(rows), unreadable)
