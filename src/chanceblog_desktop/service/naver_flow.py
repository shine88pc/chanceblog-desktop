"""네이버 A·B 복사 패키지 — 만들기·저장(JSON)·두 블로그 비교(유사도)·복사용 글 내어 주기·발행 주소 기록.

네이버에는 공식 글쓰기 수단이 없어 **복사 패키지**를 쓴다: 앱은 패키지를 만들어 보여 주고, 사람이 네이버 글쓰기 화면에 붙여 넣어 직접 발행한 뒤 주소를 입력한다.
**로그인·쿠키·브라우저 자동화는 하지 않는다**(AGENTS.md 규칙 6) — 이 모듈은 네트워크도 쓰지 않는다.
패키지는 변형(`PlatformVariant`)의 `rendered` 칸에 JSON 으로 저장해, 사람이 검토한 바로 그 패키지가 복사용으로 나가고 두 블로그를 비교할 때도 같은 글을 쓴다.
두 블로그 글이 너무 비슷하면(`NAVER_SIMILARITY_HIGH`) 사람이 직접 승인(`similarity_approved=True`)해야 복사 준비(READY_TO_COPY)로 넘어간다 — 같은 원고를 그대로 두 블로그에 올리지 않게.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta, timezone

from ..check import similarity
from ..content import status as st
from ..content.profiles import KEYS as NAVER_KEYS
from ..content.profiles import NaverProfile
from ..errors import AppError
from ..render.naver import NaverImage, NaverPackage, build_package

KST = timezone(timedelta(hours=9))
SCHEMA = 1
_KEYS = {"schema", "profile_key", "title", "category", "tags", "body_html", "body_text", "core_text", "intro", "images", "chars", "paragraphs", "warnings", "checklist"}
_IMAGE_KEYS = {"number", "label", "filename", "url", "alt", "position"}


@dataclass(frozen=True)
class NaverOptions:
    """블로그별로 사람이 고치는 값(비우면 원고 그대로) — 블로그마다 제목·도입부·태그를 다르게 하려고."""
    title: object = None
    body: object = None
    tags: tuple = ()
    category: str = ""
    ai_assisted: bool = True


def other_blog(key):
    return "naver_b" if key == "naver_a" else "naver_a"


def package_to_json(package):
    data = {
        "schema": SCHEMA, "profile_key": package.profile_key, "title": package.title, "category": package.category, "tags": list(package.tags), "body_html": package.body_html,
        "body_text": package.body_text, "core_text": package.core_text, "intro": package.intro,
        "images": [{"number": item.number, "label": item.label, "filename": item.filename, "url": item.url, "alt": item.alt, "position": item.position} for item in package.images],
        "chars": package.chars, "paragraphs": package.paragraphs, "warnings": list(package.warnings), "checklist": list(package.checklist),
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def package_from_json(text):
    """저장된 패키지를 엄격하게 읽는다 — 모양이 틀리면 CONTENT_INVALID(저장된 글이 사람이 고쳐졌거나 깨졌다)."""
    def bad():
        return AppError("CONTENT_INVALID", {"항목": "네이버 복사 패키지"})

    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise bad() from None
    if not isinstance(data, dict) or set(data) != _KEYS or data["schema"] != SCHEMA:
        raise bad()
    try:
        images = tuple(NaverImage(**item) for item in data["images"] if isinstance(item, dict) and set(item) == _IMAGE_KEYS)
        if len(images) != len(data["images"]):
            raise bad()
        texts = ("profile_key", "title", "category", "body_html", "body_text", "core_text", "intro")
        if not all(isinstance(data[name], str) for name in texts) or not all(isinstance(data[name], list) and all(isinstance(item, str) for item in data[name]) for name in ("tags", "warnings", "checklist")):
            raise bad()
        return NaverPackage(data["profile_key"], data["title"], data["category"], tuple(data["tags"]), data["body_html"], data["body_text"], data["core_text"], data["intro"], images,
                            int(data["chars"]), int(data["paragraphs"]), tuple(data["warnings"]), tuple(data["checklist"]))
    except (TypeError, ValueError):
        raise bad() from None


def build_for_blog(profile, project, options=None):
    """프로젝트의 원고(또는 블로그별로 고친 값)를 그 블로그 프로필에 맞는 패키지로. 글을 AI 로 다시 쓰지 않고 파일·네트워크도 쓰지 않는다."""
    options = options or NaverOptions()
    return build_package(profile, title=project.title if options.title is None else options.title, body=project.source_content if options.body is None else options.body,
                         tags=options.tags, assets=project.assets, category=options.category, ai_assisted=options.ai_assisted)


def kst_date(now):
    return now.astimezone(KST).strftime("%Y-%m-%d")


def comparable(package, date):
    return similarity.Comparable.from_package(package, date)


def other_package(project, key):
    """다른 네이버 블로그의 변형에 저장된 패키지(아직 없으면 None)와 그 블로그의 발행일(YYYY-MM-DD, 아직 공개 전이면 '')."""
    variant = project.variant(other_blog(key))
    if not variant.rendered:
        return None, ""
    package = package_from_json(variant.rendered)
    published = variant.published_at[:10] if variant.published_at else ""
    return package, published


def compare_with_other(project, key, package, now, *, approved=False):
    """이 블로그의 패키지를 다른 블로그의 저장된 패키지와 비교한다 → (SimilarityReport 또는 None). 기준(high)을 넘었는데 직접 승인이 없으면 NAVER_SIMILARITY_HIGH."""
    other, other_date = other_package(project, key)
    if other is None:
        return None
    today = kst_date(now)
    first, second = comparable(package, today), comparable(other, other_date or today)
    return similarity.check_pair(first, second, approved=approved)      # 기준을 넘었는데 승인이 없으면 여기서 NAVER_SIMILARITY_HIGH


def copy_text(package):
    """사람이 붙여 넣을 복사용 글(제목·본문·태그·이미지 자리·체크리스트)."""
    lines = ["[제목]", package.title, "", "[본문]", package.body_text.rstrip(), "", "[태그]", package.tags_text]
    if package.category:
        lines += ["", "[카테고리]", package.category]
    if package.images:
        lines += ["", "[이미지 자리]"]
        lines += [f"[이미지 {item.number}] {'파일 ' + item.filename if item.filename else '주소 ' + item.url}" + (f" — {item.alt}" if item.alt else "") for item in package.images]
    lines += ["", "[발행 전 체크리스트]", *package.checklist]
    if package.warnings:
        lines += ["", "[주의]", *[f"- {item}" for item in package.warnings]]
    return "\n".join(lines) + "\n"


def set_profile(settings, key, fields):
    """블로그 프로필을 만들거나 고쳐 저장한다(주어진 칸만 바꾼다). 처음 만들 때는 표시명(display_name)과 블로그 주소(blog_url)가 꼭 있어야 하고, 값은 `NaverProfile` 이 엄격히 검사한다(CONTENT_INVALID)."""
    if key not in NAVER_KEYS:
        raise AppError("CONTENT_INVALID", {"항목": "블로그 구분"})
    try:
        current = settings.naver_profile(key).to_dict()
    except AppError as error:
        if error.code != "NAVER_PROFILE_MISSING":
            raise
        if not (fields.get("display_name") and fields.get("blog_url")):
            raise AppError("NAVER_PROFILE_MISSING", {"블로그": key}, detail="처음 만들 때는 --name(표시명)과 --url(블로그 주소)이 꼭 필요하다") from None
        current = {"key": key}
    profile = NaverProfile.from_dict({**current, **fields, "key": key})
    settings.save_naver_profile(profile)
    return profile


def stage_ok_for_issue(status):
    """복사용 글을 내어 줄 수 있는 상태: 승인(READY_TO_COPY)된 뒤 — 또는 이미 복사까지 마친 글을 다시 볼 때."""
    return status in (st.READY_TO_COPY, st.COPY_COMPLETED)
