"""플랫폼별 발행 상태와 허용되는 단계. docs/ARCHITECTURE.md §9 의 표가 정본이고, 시험이 둘이 같은지 확인한다.

세 가지 흐름이 있다: GitHub Pages(승인하면 앱이 commit·push, 배포는 기존 자동 흐름), Blogger(공식 API 로 초안 저장, 공개는 운영자),
네이버(복사 패키지, 발행은 운영자). 공개된 상태는 되돌리지 않는다(공개 취소는 사람이 플랫폼에서 하는 일이다).
"""
from __future__ import annotations

NOT_STARTED = "NOT_STARTED"
DRAFT_GENERATED = "DRAFT_GENERATED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
APPROVED = "APPROVED"
COMMITTED = "COMMITTED"
PUSHED = "PUSHED"
PUBLISHED = "PUBLISHED"
DRAFT_SAVED = "DRAFT_SAVED"
READY_TO_COPY = "READY_TO_COPY"
COPY_COMPLETED = "COPY_COMPLETED"
PUBLISHED_MANUAL = "PUBLISHED_MANUAL"
PUBLISH_FAILED = "PUBLISH_FAILED"

PAGES, BLOGGER, NAVER = "pages", "blogger", "naver"
PLATFORM_FAMILY = {
    "github_pages": PAGES,
    "blogger_en": BLOGGER,
    "blogger_ko": BLOGGER,
    "naver_a": NAVER,
    "naver_b": NAVER,
}
PLATFORMS = tuple(PLATFORM_FAMILY)

# 흐름(가족 → 상태 → 갈 수 있는 다음 상태). 순서가 곧 화면에 보이는 진행 순서다.
FLOWS = {
    PAGES: {
        NOT_STARTED: (DRAFT_GENERATED,),
        DRAFT_GENERATED: (REVIEW_REQUIRED,),
        REVIEW_REQUIRED: (APPROVED, DRAFT_GENERATED),
        APPROVED: (COMMITTED, REVIEW_REQUIRED, PUBLISH_FAILED),
        COMMITTED: (PUSHED, PUBLISH_FAILED),
        PUSHED: (PUBLISHED, PUBLISH_FAILED),
        PUBLISHED: (),
        PUBLISH_FAILED: (REVIEW_REQUIRED, DRAFT_GENERATED),
    },
    BLOGGER: {
        NOT_STARTED: (DRAFT_GENERATED,),
        DRAFT_GENERATED: (REVIEW_REQUIRED,),
        REVIEW_REQUIRED: (APPROVED, DRAFT_GENERATED),
        APPROVED: (DRAFT_SAVED, REVIEW_REQUIRED, PUBLISH_FAILED),
        DRAFT_SAVED: (PUBLISHED_MANUAL, REVIEW_REQUIRED, PUBLISH_FAILED),
        PUBLISHED_MANUAL: (),
        PUBLISH_FAILED: (REVIEW_REQUIRED, DRAFT_GENERATED),
    },
    NAVER: {
        NOT_STARTED: (DRAFT_GENERATED,),
        DRAFT_GENERATED: (REVIEW_REQUIRED,),
        REVIEW_REQUIRED: (READY_TO_COPY, DRAFT_GENERATED),
        READY_TO_COPY: (COPY_COMPLETED, REVIEW_REQUIRED, PUBLISH_FAILED),
        COPY_COMPLETED: (PUBLISHED_MANUAL, READY_TO_COPY, PUBLISH_FAILED),
        PUBLISHED_MANUAL: (),
        PUBLISH_FAILED: (REVIEW_REQUIRED, DRAFT_GENERATED),
    },
}

PUBLISHED_STATES = {PAGES: PUBLISHED, BLOGGER: PUBLISHED_MANUAL, NAVER: PUBLISHED_MANUAL}
# 사람이 '승인'한 상태 — 이때의 렌더링이 현재 원고와 같은 판이어야 하고, 원고를 고치면 풀린다
APPROVED_STATES = frozenset({APPROVED, READY_TO_COPY})
# 원고를 고치면 처음부터 다시 검토해야 하는 상태(이미 올라간 상태 COMMITTED·PUSHED·PUBLISHED* 는 과거의 사실이라 그대로 둔다)
RESET_ON_EDIT = frozenset({REVIEW_REQUIRED, APPROVED, DRAFT_SAVED, READY_TO_COPY, COPY_COMPLETED, PUBLISH_FAILED})


def family(platform):
    return PLATFORM_FAMILY[platform]


def statuses(platform):
    """그 플랫폼에서 쓰는 상태(진행 순서대로)."""
    return tuple(FLOWS[family(platform)])


def next_statuses(platform, status):
    return FLOWS[family(platform)].get(status, ())


def can_transition(platform, current, requested):
    return requested in next_statuses(platform, current)


def is_published(platform, status):
    return status == PUBLISHED_STATES[family(platform)]
