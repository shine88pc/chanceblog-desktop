"""검토 요청 → 승인 → 승인 취소 — 사람이 글을 읽고 '이대로 내보내도 좋다' 고 **직접** 말하는 단계(AGENTS.md 규칙 7·9).

  request_review   글을 그 플랫폼용으로 만들어(렌더링) 현재 판으로 기록하고 '검토 중(REVIEW_REQUIRED)' 으로 보낸다. 이미 승인된 글을 다시 만들면 먼저 승인이 풀린다.
                   이 단계의 검사 결과는 보여 주기만 한다(막지 않는다) — 고친 뒤 다시 만들면 된다.
  grant_approval   사람이 승인한다. Pages 는 검사(`service/gate.py`)를 **다시** 통과해야 하고(걸리면 CHECK_FAILED·승인 안 됨), 네이버는 다른 블로그와의 유사도 점검을 통과해야 한다
                   (많이 비슷하면 NAVER_SIMILARITY_HIGH — `similarity_approved=True` 로 사람이 직접 승인해야 복사 준비가 된다).
  revoke_approval  승인을 거둔다(검토 중으로 되돌린다).
원고를 고치면 모델이 알아서 승인을 풀어 처음부터 다시 검토하게 한다(`content/model.py`) — 여기서 그 규칙을 우회하지 않는다. 잘못된 단계는 STATUS_TRANSITION_INVALID.
Blogger 는 이 묶음에서 다루지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..check import similarity
from ..content import status as st
from ..errors import AppError
from ..security.refuse import refuse_secret_shapes, text_of
from . import naver_flow
from .gate import GateReport, require_gates
from .previews import PLATFORM_PAGES, NaverItem, pages_preview_of, similarity_dict
from .projects import resolve_id

SUPPORTED = (PLATFORM_PAGES, "naver_a", "naver_b")


@dataclass(frozen=True)
class ReviewResult:
    project_id: str
    platform: str
    status: str
    pages: object = None            # PagesPreview
    naver: object = None            # NaverItem
    similarity: object = None       # SimilarityReport(다른 블로그의 패키지가 이미 있을 때)

    def to_dict(self):
        return {"project_id": self.project_id, "platform": self.platform, "status": self.status, "pages": self.pages.to_dict() if self.pages else None,
                "naver": self.naver.to_dict() if self.naver else None, "similarity": similarity_dict(self.similarity)}


@dataclass(frozen=True)
class ApprovalResult:
    project_id: str
    platform: str
    status: str
    gates: object = None            # GateReport (Pages)
    similarity: object = None       # SimilarityReport (네이버)

    def to_dict(self):
        return {"project_id": self.project_id, "platform": self.platform, "status": self.status, "gates": self.gates.to_dict() if isinstance(self.gates, GateReport) else None,
                "similarity": similarity_dict(self.similarity)}


def _check_platform(platform):
    if platform not in SUPPORTED:
        raise AppError("CONTENT_INVALID", {"항목": "플랫폼(이 묶음은 GitHub Pages·네이버 A·B 만 다룹니다)"}, detail=str(platform)[:40])


def _back_to_review(project, platform, now):
    """승인(또는 복사 준비·복사함)된 글을 다시 만들기 전에 검토 중으로 되돌린다 — 승인은 새 글에 따라가지 않는다."""
    variant = project.variant(platform)
    if variant.status == st.COPY_COMPLETED:
        project.transition(platform, st.READY_TO_COPY, now=now)
    if variant.status in (st.APPROVED, st.READY_TO_COPY):
        project.transition(platform, st.REVIEW_REQUIRED, now=now)


def _review_fields(pages, naver_options):
    """검토를 요청할 때 사람이 주는 글칸(Pages 매개변수·네이버 선택 항목) — 비밀 형태 검사 대상(PCSEC1 D3). 칸 이름은 명령줄 도움말의 이름이다."""
    fields = {}
    if pages is not None:
        source = pages.source if isinstance(pages.source, dict) else {}
        fields.update({"분야": pages.category, "대표 이미지 주소": pages.image_url, "태그": text_of(pages.tags), "한 줄 설명": text_of(pages.description),
                       "출처 이름": source.get("name"), "출처 주소": source.get("url"), "출처 글 제목": source.get("title")})
    if naver_options is not None:
        fields.update({"제목": naver_options.title, "본문 파일": naver_options.body, "태그": text_of(naver_options.tags), "분야": naver_options.category})
    return fields


def request_review(ctx, text_id, platform, *, pages=None, naver_options=None):
    """글을 그 플랫폼용으로 만들어 검토 중으로 보낸다. Pages 는 `pages`(PagesParams), 네이버는 선택 `naver_options`(NaverOptions)."""
    refuse_secret_shapes(_review_fields(pages, naver_options), "저장")                      # 저장소를 열기 전에 — 키 모양이 있으면 아무것도 쓰지 않고 위치·유형만 알린다(PCSEC1 D3)
    _check_platform(platform)
    with ctx.store() as store:
        project = store.load(resolve_id(store, text_id))
        now = ctx.stamp()
        preview = naver = report = None
        if platform == PLATFORM_PAGES:
            preview = pages_preview_of(ctx, project, pages)
            rendering = preview.text
        else:
            profile = ctx.settings.naver_profile(platform)
            package = naver_flow.build_for_blog(profile, project, naver_options)
            naver = NaverItem(platform, package)
            rendering = naver_flow.package_to_json(package)
            report = _soft_compare(ctx, project, platform, package)
        _back_to_review(project, platform, now)
        project.set_rendered(platform, rendering, now=now)           # 검토 중·실패였다면 '글 만듦' 으로 돌아가 현재 판으로 기록한다(올라간 상태에서는 STATUS_TRANSITION_INVALID)
        project.transition(platform, st.REVIEW_REQUIRED, now=now)
        store.save(project)
        return ReviewResult(project.project_id, platform, project.variant(platform).status, preview, naver, report)


def _soft_compare(ctx, project, platform, package):
    """저장된 다른 블로그 패키지와의 유사도(알려 주기만 한다 — 막는 것은 승인 단계)."""
    other, other_date = naver_flow.other_package(project, platform)
    if other is None:
        return None
    today = naver_flow.kst_date(ctx.now())
    return similarity.compare(naver_flow.comparable(package, today), naver_flow.comparable(other, other_date or today))


def grant_approval(ctx, text_id, platform, *, similarity_approved=False):
    """사람이 승인한다(Pages: APPROVED, 네이버: READY_TO_COPY). 검사·유사도 점검에 걸리면 승인하지 않고 오류 코드로 알린다."""
    _check_platform(platform)
    target = st.APPROVED if platform == PLATFORM_PAGES else st.READY_TO_COPY
    with ctx.store() as store:
        project = store.load(resolve_id(store, text_id))
        variant = project.variant(platform)
        if not st.can_transition(platform, variant.status, target):
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": target})
        gates = report = None
        if platform == PLATFORM_PAGES:
            gates = require_gates(variant.rendered, local_paths=ctx.local_paths())          # 승인하는 순간에도 다시 검사한다(fail closed)
        else:
            package = naver_flow.package_from_json(variant.rendered)
            report = naver_flow.compare_with_other(project, platform, package, ctx.now(), approved=similarity_approved is True)
        project.transition(platform, target, now=ctx.stamp())
        store.save(project)
        return ApprovalResult(project.project_id, platform, project.variant(platform).status, gates, report)


def revoke_approval(ctx, text_id, platform):
    """승인(또는 복사 준비)을 거둬 검토 중으로 되돌린다. 올라간 글·복사를 마친 글은 되돌리지 않는다(STATUS_TRANSITION_INVALID)."""
    _check_platform(platform)
    with ctx.store() as store:
        project = store.load(resolve_id(store, text_id))
        project.transition(platform, st.REVIEW_REQUIRED, now=ctx.stamp())
        store.save(project)
        return ApprovalResult(project.project_id, platform, project.variant(platform).status)


@dataclass(frozen=True)
class NaverIssue:
    project_id: str
    platform: str
    status: str
    package: object                 # NaverPackage
    similarity: object              # SimilarityReport 또는 None

    def to_dict(self):
        item = NaverItem(self.platform, self.package)
        return {"project_id": self.project_id, "platform": self.platform, "status": self.status, "similarity": similarity_dict(self.similarity), "package": item.to_dict(with_text=True),
                "copy_text": naver_flow.copy_text(self.package)}


def issue_naver_package(ctx, text_id, blog, *, similarity_approved=False):
    """복사용 패키지를 내어 준다. 검토 중이면 이 명령이 승인이다(유사도 점검을 통과해야 복사 준비 READY_TO_COPY 가 된다) — 이미 복사 준비·복사함이면 같은 패키지를 다시 보여 준다.
    사람이 검토한 바로 그 패키지(저장된 것)가 나간다. 네이버 로그인·글쓰기 화면 자동 열기는 하지 않는다."""
    if blog not in ("naver_a", "naver_b"):
        raise AppError("CONTENT_INVALID", {"항목": "네이버 블로그 구분"})
    with ctx.store() as store:
        project = store.load(resolve_id(store, text_id))
        variant = project.variant(blog)
        report = None
        if variant.status == st.REVIEW_REQUIRED:
            package = naver_flow.package_from_json(variant.rendered)
            report = naver_flow.compare_with_other(project, blog, package, ctx.now(), approved=similarity_approved is True)
            project.transition(blog, st.READY_TO_COPY, now=ctx.stamp())
            store.save(project)
        elif not naver_flow.stage_ok_for_issue(variant.status):
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.READY_TO_COPY})
        package = naver_flow.package_from_json(variant.rendered)
        return NaverIssue(project.project_id, blog, project.variant(blog).status, package, report)


def record_naver_published(ctx, text_id, blog, url):
    """사람이 네이버에 직접 발행한 뒤 그 글의 주소를 기록한다(복사 준비 → 복사함 → 직접 발행함). 주소가 blog.naver.com 의 https 주소가 아니면 NAVER_PUBLISH_URL_INVALID 이고 아무것도 바꾸지 않는다."""
    refuse_secret_shapes({"발행 주소": url}, "저장")                                         # 주소 검사·저장보다 먼저(PCSEC1 D3)
    if blog not in ("naver_a", "naver_b"):
        raise AppError("CONTENT_INVALID", {"항목": "네이버 블로그 구분"})
    with ctx.store() as store:
        project = store.load(resolve_id(store, text_id))
        now = ctx.stamp()
        if project.variant(blog).status == st.READY_TO_COPY:
            project.transition(blog, st.COPY_COMPLETED, now=now)
        project.transition(blog, st.PUBLISHED_MANUAL, published_url=url, now=now)      # 주소 검사는 여기서 — 실패하면 아래 저장까지 가지 않는다
        store.save(project)
        return ApprovalResult(project.project_id, blog, project.variant(blog).status)
