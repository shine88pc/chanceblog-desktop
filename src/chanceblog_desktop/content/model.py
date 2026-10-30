"""콘텐츠 프로젝트 — 하나의 원본 글과 플랫폼별 변형(docs/ARCHITECTURE.md §9). 저장(SQLite)은 다음 묶음이고, 여기서는 자료의 모양·검증·상태 전환만 한다.

규칙: ① 모든 검증 실패는 AppError(오류 코드)로 낸다 ② 원고를 고치면 승인·검토 상태가 풀려 처음부터 다시 검토한다(이미 올라간 상태는 그대로)
③ 승인은 '현재 원고와 같은 판으로 만든 렌더링'에만 줄 수 있다 ④ 공개된 상태로 바꿀 때는 발행 주소가 있어야 하고 되돌릴 수 없다.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..errors import AppError
from ..errors.table import CATALOG
from . import status as st

SCHEMA = 1
MAX_TITLE = 200
MAX_REFERENCES = 50
MAX_ASSETS = 100
MAX_ALT = 300
NAVER_HOSTS = ("blog.naver.com", "m.blog.naver.com")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _invalid(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": item}, detail=detail)


def _text(value, item, *, required=True, limit=None):
    if not isinstance(value, str) or (required and not value.strip()) or (limit and len(value) > limit):
        raise _invalid(item)
    return value


def _url(value, item, schemes):
    """공백이 없고 호스트가 있으며 로그인 정보(user:pass@)가 없는 주소만 받는다."""
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value):
        raise _invalid(item)
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        raise _invalid(item) from None
    if parts.scheme not in schemes or not host or parts.username or parts.password:
        raise _invalid(item)
    return value


def _stamp(value, item):
    if not isinstance(value, str) or not _TIME.match(value):
        raise _invalid(item)
    return value


@dataclass(frozen=True)
class Asset:
    """원고에 쓰는 이미지 등. filename 은 파일 이름만(폴더 구분 없음), position 은 본문 속 삽입 위치(문단 번호, 0 은 맨 위)."""
    filename: str
    alt: str = ""
    position: int = 0

    def __post_init__(self):
        name = _text(self.filename, "이미지 파일 이름", limit=255)
        if "/" in name or "\\" in name or name in (".", "..") or any(ord(ch) < 32 for ch in name):
            raise _invalid("이미지 파일 이름")
        _text(self.alt, "이미지 설명", required=False, limit=MAX_ALT)
        if not isinstance(self.position, int) or isinstance(self.position, bool) or self.position < 0:
            raise _invalid("이미지 위치")

    def to_dict(self):
        return {"filename": self.filename, "alt": self.alt, "position": self.position}


@dataclass
class PlatformVariant:
    platform: str
    status: str = st.NOT_STARTED
    rendered: str = ""
    rendered_revision: int | None = None     # 이 렌더링을 만든 원고의 판(revision)
    published_url: str | None = None
    published_at: str | None = None
    remote_id: str | None = None             # Blogger Post ID 등 플랫폼 쪽 식별자
    error_code: str | None = None

    def __post_init__(self):
        if self.platform not in st.PLATFORM_FAMILY:
            raise _invalid("플랫폼")
        if self.status not in st.statuses(self.platform):
            raise _invalid("상태")

    def to_dict(self):
        return {
            "status": self.status, "rendered": self.rendered, "rendered_revision": self.rendered_revision, "published_url": self.published_url,
            "published_at": self.published_at, "remote_id": self.remote_id, "error_code": self.error_code,
        }


def _published_url(platform, value):
    """공개된 글의 주소: https 만, 로그인 정보 없이. 네이버는 blog.naver.com 주소여야 한다."""
    if not value:
        raise AppError("PUBLISHED_URL_REQUIRED")
    naver = st.family(platform) == st.NAVER
    wrong = "NAVER_PUBLISH_URL_INVALID" if naver else "PUBLISHED_URL_INVALID"
    try:
        _url(value, "발행 주소", ("https",))
    except AppError:
        raise AppError(wrong) from None
    if naver and urlsplit(value).hostname not in NAVER_HOSTS:
        raise AppError(wrong)
    return value


@dataclass
class ContentProject:
    project_id: str
    title: str
    source_content: str
    references: tuple = ()
    assets: tuple = ()
    created_at: str = ""
    updated_at: str = ""
    revision: int = 1
    variants: dict = field(default_factory=dict)

    # ---- 만들기 ----------------------------------------------------------------------------------------------------------
    @classmethod
    def new(cls, title, source_content, references=(), assets=(), *, project_id=None, now=None):
        now = utc_now() if now is None else now
        project = cls(uuid.uuid4().hex if project_id is None else project_id, title, source_content, tuple(references), tuple(assets), now, now, 1,
                      {platform: PlatformVariant(platform) for platform in st.PLATFORMS})
        project._validate()
        return project

    def _validate(self):
        if not isinstance(self.project_id, str) or not _ID.match(self.project_id):
            raise _invalid("프로젝트 번호")
        _text(self.title, "제목", limit=MAX_TITLE)
        _text(self.source_content, "본문")
        self.references = self._references(self.references)
        self.assets = self._assets(self.assets)
        _stamp(self.created_at, "만든 시각")
        _stamp(self.updated_at, "고친 시각")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise _invalid("판 번호")
        if set(self.variants) != set(st.PLATFORMS):
            raise _invalid("플랫폼 목록")
        for platform, variant in self.variants.items():
            self._validate_variant(platform, variant)

    @staticmethod
    def _references(values):
        if isinstance(values, (str, bytes)) or len(values) > MAX_REFERENCES:
            raise _invalid("출처 주소")
        return tuple(_url(value, "출처 주소", ("http", "https")) for value in values)

    @staticmethod
    def _assets(values):
        if isinstance(values, (str, bytes)) or len(values) > MAX_ASSETS or not all(isinstance(value, Asset) for value in values):
            raise _invalid("이미지")
        return tuple(values)

    def _validate_variant(self, platform, variant):
        if not isinstance(variant, PlatformVariant) or variant.platform != platform:
            raise _invalid("플랫폼 변형")
        if not isinstance(variant.rendered, str):
            raise _invalid("렌더링")
        if variant.rendered_revision is not None and (not isinstance(variant.rendered_revision, int) or isinstance(variant.rendered_revision, bool)
                                                      or not 1 <= variant.rendered_revision <= self.revision):
            raise _invalid("렌더링 판 번호")
        for item, value in (("발행 주소", variant.published_url), ("발행 시각", variant.published_at), ("플랫폼 식별자", variant.remote_id), ("오류 코드", variant.error_code)):
            if value is not None and not isinstance(value, str):
                raise _invalid(item)
        if st.is_published(platform, variant.status):
            try:
                _published_url(platform, variant.published_url)
            except AppError:
                raise _invalid("발행 주소") from None
            _stamp(variant.published_at, "발행 시각")
        elif variant.published_url is not None or variant.published_at is not None:
            raise _invalid("발행 주소")
        if (variant.status == st.PUBLISH_FAILED) != (variant.error_code is not None) or (variant.error_code is not None and variant.error_code not in CATALOG):
            raise _invalid("오류 코드")
        if variant.status in st.APPROVED_STATES and variant.rendered_revision != self.revision:
            raise _invalid("승인된 렌더링의 판 번호")

    # ---- 원고 고치기 -----------------------------------------------------------------------------------------------------
    def edit(self, *, title=None, source_content=None, references=None, assets=None, now=None):
        """바뀐 것이 있으면 판(revision)을 올리고, 검토·승인·초안 저장 상태를 '렌더링 만듦'으로 되돌린다. 바뀐 것이 없으면 아무것도 하지 않는다."""
        new_title = self.title if title is None else _text(title, "제목", limit=MAX_TITLE)
        new_body = self.source_content if source_content is None else _text(source_content, "본문")
        new_refs = self.references if references is None else self._references(references)
        new_assets = self.assets if assets is None else self._assets(assets)
        if (new_title, new_body, new_refs, new_assets) == (self.title, self.source_content, self.references, self.assets):
            return False
        self.title, self.source_content, self.references, self.assets = new_title, new_body, new_refs, new_assets
        self.revision += 1
        self.updated_at = utc_now() if now is None else now
        for variant in self.variants.values():
            if variant.status in st.RESET_ON_EDIT:
                variant.status = st.DRAFT_GENERATED
                variant.error_code = None
        return True

    # ---- 플랫폼별 변형 ---------------------------------------------------------------------------------------------------
    def variant(self, platform):
        if platform not in self.variants:
            raise _invalid("플랫폼")
        return self.variants[platform]

    def set_rendered(self, platform, text, *, now=None):
        """그 플랫폼용으로 만든 글(렌더링)을 현재 판으로 기록하고 '렌더링 만듦' 상태로 둔다."""
        variant = self.variant(platform)
        _text(text, "렌더링")
        if variant.status != st.DRAFT_GENERATED:
            self._move(platform, variant, st.DRAFT_GENERATED)
            variant.status, variant.error_code = st.DRAFT_GENERATED, None
        variant.rendered, variant.rendered_revision = text, self.revision
        self.updated_at = utc_now() if now is None else now

    def transition(self, platform, requested, *, published_url=None, error_code=None, remote_id=None, now=None):
        """허용된 다음 상태로만 바꾼다. 공개 상태는 발행 주소가, 실패 상태는 오류 코드가 있어야 하고, 승인은 현재 판의 렌더링에만 줄 수 있다."""
        variant = self.variant(platform)
        self._move(platform, variant, requested)
        now = utc_now() if now is None else now
        if requested in st.APPROVED_STATES and (not variant.rendered or variant.rendered_revision != self.revision):
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": requested}, detail="렌더링이 현재 원고의 판과 다르다")
        url = _published_url(platform, published_url) if st.is_published(platform, requested) else None
        if requested == st.PUBLISH_FAILED and error_code not in CATALOG:
            raise _invalid("오류 코드")
        if remote_id is not None and (not isinstance(remote_id, str) or not remote_id or len(remote_id) > 200 or any(ch.isspace() for ch in remote_id)):
            raise _invalid("플랫폼 식별자")
        # 여기까지 오면 바꿔도 된다(중간에 실패해서 절반만 바뀐 상태가 남지 않게 검사를 모두 끝낸 뒤에 쓴다)
        if url:
            variant.published_url, variant.published_at = url, now
        variant.error_code = error_code if requested == st.PUBLISH_FAILED else None
        if remote_id is not None:
            variant.remote_id = remote_id
        variant.status = requested
        self.updated_at = now

    @staticmethod
    def _move(platform, variant, requested):
        if requested not in st.statuses(platform) or not st.can_transition(platform, variant.status, requested):
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": requested})

    # ---- JSON 로 저장·불러오기 ---------------------------------------------------------------------------------------------
    def to_dict(self):
        return {
            "schema": SCHEMA, "project_id": self.project_id, "title": self.title, "source_content": self.source_content,
            "references": list(self.references), "assets": [asset.to_dict() for asset in self.assets], "created_at": self.created_at,
            "updated_at": self.updated_at, "revision": self.revision, "variants": {name: variant.to_dict() for name, variant in self.variants.items()},
        }

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 모르는 칸·빠진 칸·어긋난 값은 CONTENT_INVALID 로 거절한다."""
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise _invalid("저장 형식")
        keys = {"schema", "project_id", "title", "source_content", "references", "assets", "created_at", "updated_at", "revision", "variants"}
        if set(data) != keys:
            raise _invalid("저장 형식", detail=f"칸이 다르다: {sorted(set(data) ^ keys)}")
        variant_keys = {"status", "rendered", "rendered_revision", "published_url", "published_at", "remote_id", "error_code"}
        if not isinstance(data["variants"], dict):
            raise _invalid("플랫폼 목록")
        variants = {}
        for name, raw in data["variants"].items():
            if not isinstance(raw, dict) or set(raw) != variant_keys:
                raise _invalid("플랫폼 변형")
            variants[name] = PlatformVariant(name, **raw)
        if not isinstance(data["references"], list) or not isinstance(data["assets"], list) or not all(isinstance(raw, dict) for raw in data["assets"]):
            raise _invalid("저장 형식")
        try:
            assets = tuple(Asset(**raw) for raw in data["assets"])
        except TypeError:
            raise _invalid("이미지") from None
        project = cls(data["project_id"], data["title"], data["source_content"], tuple(data["references"]), assets,
                      data["created_at"], data["updated_at"], data["revision"], variants)
        project._validate()
        return project
