"""미리보기 — Pages 글(경로와 내용)과 네이버 A·B 패키지(그리고 두 블로그 비교)를 **만들어 보여 주기만** 한다.

아무 파일도 쓰지 않고(연결한 저장소·데이터 폴더 모두) 네트워크도 쓰지 않는다. 글을 AI 로 다시 쓰지도 않는다. 공개 주소는 연결한 저장소의 `_config.yml` 을 읽어 계산할 수 있을 때만 덧붙인다(읽기만).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..check import similarity
from ..content.profiles import KEYS as NAVER_KEYS
from ..errors import AppError
from ..render.pages import render_pages_post
from . import naver_flow
from .gate import GateReport, require_clean_front_values, run_gates
from .projects import resolve_id

PLATFORM_PAGES = "github_pages"


@dataclass(frozen=True)
class PagesParams:
    """Pages 글을 만들 때 사람이 정하는 값(원고에는 없는 것)."""
    category: str
    lang: str
    image_url: str
    tags: tuple = ()
    description: object = None
    source: object = None          # {"name", "url", "title"?}


@dataclass(frozen=True)
class PagesPreview:
    path: str                      # 지금 시각으로 만든 글 경로(실제로 올릴 때는 그 순간의 시각으로 이름이 정해진다)
    text: str
    category: str
    lang: str
    size_bytes: int
    gates: GateReport
    expected_url: str              # '' 이면 계산하지 않았다(이유는 url_note)
    url_note: str

    def to_dict(self, *, with_text=False):
        data = {"path": self.path, "category": self.category, "lang": self.lang, "size_bytes": self.size_bytes, "gates": self.gates.to_dict(), "expected_url": self.expected_url, "url_note": self.url_note}
        if with_text:
            data["text"] = self.text
        return data


@dataclass(frozen=True)
class NaverItem:
    key: str
    package: object                # NaverPackage

    def to_dict(self, *, with_text=False):
        package = self.package
        data = {"blog": self.key, "title": package.title, "category": package.category, "tags": list(package.tags), "chars": package.chars, "paragraphs": package.paragraphs,
                "images": [{"number": item.number, "label": item.label, "filename": item.filename, "url": item.url, "alt": item.alt, "position": item.position} for item in package.images],
                "warnings": list(package.warnings), "checklist": list(package.checklist)}
        if with_text:
            data.update({"body_text": package.body_text, "body_html": package.body_html, "tags_text": package.tags_text})
        return data


def similarity_dict(report):
    if report is None:
        return None
    return {"title": report.title, "intro": report.intro, "body": report.body, "structure": report.structure, "images": report.images, "tags": report.tags, "overall": report.overall,
            "same_day": report.same_day, "level": report.level, "reasons": list(report.reasons), "needs_approval": report.needs_approval}


@dataclass(frozen=True)
class NaverPreview:
    items: tuple                   # NaverItem — 프로필이 있는 블로그
    missing: tuple                 # 프로필이 아직 없는 블로그
    similarity: object             # SimilarityReport 또는 None(두 블로그가 모두 있을 때만)

    def to_dict(self, *, with_text=False):
        return {"items": [item.to_dict(with_text=with_text) for item in self.items], "missing_profiles": list(self.missing), "similarity": similarity_dict(self.similarity)}


def render_pages(ctx, project, params):
    """승인할 Pages 글(경로+내용) — 파일은 쓰지 않는다. 값이 올바르지 않으면 CONTENT_INVALID."""
    if not isinstance(params, PagesParams):
        raise AppError("CONTENT_INVALID", {"항목": "Pages 글 설정"})
    post = render_pages_post(project, category=params.category, lang=params.lang, image_url=params.image_url, tags=params.tags, description=params.description,
                             source=params.source, now=ctx.now())
    require_clean_front_values(post.text)           # 방금 준 값(분야·태그·이미지 주소·설명·출처)과 제목이 머리말에 넣어도 되는 값인가 — 아니면 여기서 CHECK_FAILED(검토 중으로 보내지도 보여 주지도 않는다)
    return post


def expected_url_note(ctx, post):
    """공개 주소(읽기만 한다)와, 계산하지 못했을 때의 이유."""
    repo = ctx.repo_path_or_none()
    if repo is None:
        return "", "연결한 chanceblog 폴더가 없어 공개 주소는 계산하지 않았습니다."
    try:
        return ctx.backend.expected_url(repo, post, ctx.now()), ""
    except AppError as error:
        return "", f"공개 주소를 계산하지 못했습니다: {error.rendered().message}"


def pages_preview_of(ctx, project, params):
    post = render_pages(ctx, project, params)
    url, note = expected_url_note(ctx, post)
    return PagesPreview(post.path, post.text, post.category, post.lang, len(post.text.encode("utf-8")), run_gates(post.text, local_paths=ctx.local_paths()), url, note)


def preview_pages(ctx, text_id, params):
    with ctx.store() as store:
        project = store.load(resolve_id(store, text_id))
    return pages_preview_of(ctx, project, params)


def preview_naver(ctx, text_id, options=None):
    """프로필이 있는 네이버 블로그마다 패키지를 만들고, 둘 다 있으면 서로 얼마나 비슷한지 잰다. 프로필이 하나도 없으면 NAVER_PROFILE_MISSING."""
    options = options or {}
    with ctx.store() as store:
        project = store.load(resolve_id(store, text_id))
    items, missing = [], []
    for key in NAVER_KEYS:
        try:
            profile = ctx.settings.naver_profile(key)
        except AppError as error:
            if error.code != "NAVER_PROFILE_MISSING":
                raise
            missing.append(key)
            continue
        items.append(NaverItem(key, naver_flow.build_for_blog(profile, project, options.get(key))))
    if not items:
        raise AppError("NAVER_PROFILE_MISSING", {"블로그": ", ".join(NAVER_KEYS)})
    report = None
    if len(items) == 2:
        today = naver_flow.kst_date(ctx.now())
        report = similarity.compare(naver_flow.comparable(items[0].package, today), naver_flow.comparable(items[1].package, today))
    return NaverPreview(tuple(items), tuple(missing), report)
