"""Blogger API 의 네 요청(블로그 확인 A · **초안 저장 B** · 같은 제목 초안 찾기 C · 초안인지 확인 D)과 응답 검사(BLOGGER 설계서 3.5, 결정 D-773, 운영자 확인 038 ③).

이 파일이 만들 수 있는 요청은 이 네 모양뿐이다(토큰 서버의 둘은 `blogger_auth.py`). 길·질의는 접속 틀의 소스 표(`net/endpoints.py`)가 정하고 여기서는 `url_for` 로만 주소를 만든다 —
**초안 전용 질의는 그 표에 한 번 있고 이 파일 어디에도 글자로 없다.** 게시(`publish`)·되돌리기(`revert`)·수정(`update`·`patch`)·삭제(`delete`) 요청은 이 파일에도 표에도 **없다**(공개·삭제는 사람이 Blogger 에서 한다).
공개 함수의 첫 문장은 관문이다 — 읽기(A·C·D)는 `require_net("blogger_read")`, 쓰기(B)는 `require_external_write` 와 `require_net("blogger_draft")` 둘이다.

응답은 **쓰기 전에 모양을 본다**(NET R3): 객체인가 · 글 번호는 숫자 25자 이하 · 블로그 번호는 요청한 것과 같은가 · 상태는 `DRAFT` 인가(대문자로 바꿔 견준다 — 공개(`LIVE`)·예약(`SCHEDULED`)이면 즉시 `BLOGGER_NOT_DRAFT`로 멈춘다) ·
주소는 https·500자 이하·사용자 정보 없음 · 블로그 이름은 태그를 지운 글자로만. 서버가 보낸 오류 문장(`message`)은 읽지도 않고 **사유 낱말**(`reason`)만 모양을 보고 쓴다.
쓰기 요청(B)의 응답이 이상하면 서버가 글을 저장했을 수 있으므로 `outcome_unknown=True` 로 알린다 — 자동으로 다시 보내지 않고 호출하는 쪽이 같은 제목 초안을 먼저 찾는다.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .. import capabilities
from ..errors import AppError
from ..net.endpoints import url_for
from ..net.errors import REASON_SHAPE, NetError, invalid
from ..net.parse import check_display_url
from . import blogger_auth as auth

USE_READ, USE_DRAFT = "blogger_read", "blogger_draft"
NUMBER = re.compile(r"[0-9]{1,25}")
MAX_BODY = 1024 * 1024                         # 보내는 본문 상한 — 접속 틀의 표와 같다
MAX_NAME = 500
MAX_TITLE_ECHO = 1000
MAX_ITEMS = 5
KIND = "blogger#post"
DRAFT = "DRAFT"
# 403 이어도 호출 한도(속도·쿼터)면 권한 오류가 아니다 — 권한 오류로 오인하면 운영자가 멀쩡한 설정을 고치러 간다(블로그 저장소 어댑터의 경험, 설계 2.3). 여섯 사유.
LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg", "sharedRateLimitExceeded"})
API_OFF_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})            # 로그인 정보를 만든 프로젝트에서 Blogger API 를 켜지 않았다
_REASON = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
_TAG = re.compile(r"<[^<>]{0,2000}>")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_RFC3339 = re.compile(r"(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|z|[+-]\d{2}:\d{2})")


# ---- 값 -----------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class BlogInfo:
    blog_id: str
    name: str              # 태그를 지운 글자(화면에는 글자로만 보인다)
    url: str               # 화면에 글자로만 보이는 주소(검사를 지나지 못했으면 빈 글)


@dataclass(frozen=True)
class Inserted:
    post_id: str
    blog_id: str
    status: str            # 응답이 알려 줬으면 `DRAFT`(아니면 빈 글 — 확인 요청 D 가 보강한다)
    url: str


@dataclass(frozen=True)
class DraftItem:
    post_id: str
    title: str
    updated: object        # 시간대가 있는 UTC `datetime`
    status: str


@dataclass(frozen=True)
class PostStatus:
    post_id: str
    status: str            # 응답이 알려 줬으면 `DRAFT`, 아니면 빈 글('확인하지 못함' — 실패가 아니라 경고)


# ---- 작은 도구 -----------------------------------------------------------------------------------------------------------------------------
def check_number(value, what):
    """블로그·글 번호는 **숫자만**(1–25자) — 길을 만들기 전에 검사한다. 틀리면 CONTENT_INVALID(입력한 글은 싣지 않는다)."""
    if not isinstance(value, str) or NUMBER.fullmatch(value) is None:
        raise AppError("CONTENT_INVALID", {"항목": what})
    return value


def plain_text(value, limit=MAX_NAME):
    """응답 속 글(블로그 이름 등) → 태그를 지우고 글자 참조를 푼 한 줄. 너무 길면 None(검사에서 거절)."""
    if not isinstance(value, str):
        return None
    text = value
    for _ in range(3):                                           # 글자 참조로 숨긴 태그(`&lt;b&gt;`)도 풀어서 지운다 — 두세 겹까지
        text = _TAG.sub("", html_lib.unescape(text))
    text = text.replace("<", " ").replace(">", " ")              # 짝이 없는 꺾쇠도 남기지 않는다(화면이 글을 서식으로 읽는 일이 없게)
    text = " ".join(_CONTROL.sub(" ", text).split())
    return text if len(text) <= limit else None


def parse_rfc3339(text):
    """`2026-11-25T09:00:00.123-08:00` 같은 글 → UTC `datetime`. 모양이 틀리면 None(파이썬 3.10 의 `fromisoformat` 은 `Z` 를 못 읽어 직접 푼다)."""
    match = _RFC3339.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(match.group(index)) for index in range(1, 7))
    zone = match.group(7)
    try:
        moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        if zone not in ("Z", "z"):
            offset = timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
            moment = moment - offset if zone[0] == "+" else moment + offset
    except (ValueError, OverflowError):
        return None
    return moment


def _shape(use, phase, *, sent=False):
    return invalid(use, REASON_SHAPE, phase=phase, outcome_unknown=sent)


def _object(response, *, sent=False):
    try:
        data = response.json()
    except NetError as error:
        if sent:
            error.outcome_unknown = True
        raise
    if not isinstance(data, dict):
        raise _shape(response.use, "object", sent=sent)
    return data


def _reasons(response):
    """오류 응답의 사유 낱말들 — `error.errors[*].reason` 과 `error.details[*].reason`(ErrorInfo)에서 **모양이 맞는 것만**. 서버의 문장(`message`)은 읽지 않는다."""
    try:
        data = response.json()
    except NetError:
        return set()
    error = data.get("error") if isinstance(data, dict) else None
    found = set()
    if isinstance(error, dict):
        for key in ("errors", "details"):
            items = error.get(key)
            for item in items[:10] if isinstance(items, list) else ():
                reason = item.get("reason") if isinstance(item, dict) else None
                if isinstance(reason, str) and _REASON.fullmatch(reason):
                    found.add(reason)
    return found


def failure(response, *, write):
    """2xx 가 아닌 답 → 오류 코드 하나(설계 3.7 의 표). 401 은 `BLOGGER_AUTH_EXPIRED`(호출하는 쪽이 토큰을 한 번 갱신해 본다), 403 은 한도·API 꺼짐·권한으로 가르고,
    쓰기(B) 요청의 5xx 는 서버가 글을 저장했을 수 있어 `outcome_unknown=True` 다. 429 와 한도 403 에는 `Retry-After`(초)를 `retry_after` 로 달아 준다."""
    status, use = response.status, response.use
    detail = f"{use}:status:{status}"
    unknown = False
    if status == 401:
        code = "BLOGGER_AUTH_EXPIRED"
    elif status == 403:
        reasons = _reasons(response)
        code = "API_RATE_LIMITED" if reasons & LIMIT_REASONS else "BLOGGER_API_NOT_ENABLED" if reasons & API_OFF_REASONS else "BLOGGER_PERMISSION_DENIED"
    elif status == 404:
        code = "BLOGGER_NOT_FOUND"
    elif status in (400, 422):
        code = "REQUEST_INVALID"
    elif status == 429:
        code = "API_RATE_LIMITED"
    elif status >= 500:
        code, unknown = "BLOGGER_SERVER_ERROR", bool(write)
    else:
        return invalid(use, REASON_SHAPE, phase=f"status:{status}", outcome_unknown=bool(write))
    error = NetError(code, {}, detail=detail, use=use, outcome_unknown=unknown)
    error.retry_after = response.retry_after if code == "API_RATE_LIMITED" else None
    return error


def _get(client, use, path, token):
    return client.request(use, "GET", url_for(use, "GET", path), bearer=token.reveal())


# ---- A: 블로그 확인 ----------------------------------------------------------------------------------------------------------------------
def get_blog(client, token, blog_id):
    """`GET /blogger/v3/blogs/<번호>` → `BlogInfo`. 응답의 `id` 가 요청한 번호와 같아야 하고 이름은 태그를 지운 글자로만 쓴다."""
    capabilities.require_net(USE_READ, "Blogger 블로그 확인")
    blog_id = check_number(blog_id, "블로그 번호(숫자)")
    response = _get(client, USE_READ, f"/blogger/v3/blogs/{blog_id}", token)
    if not response.ok:
        raise failure(response, write=False)
    data = _object(response)
    if str(data.get("id")) != blog_id:
        raise _shape(USE_READ, "blog_id")
    name = plain_text(data.get("name"))
    if not name:
        raise _shape(USE_READ, "name")
    url = ""
    if data.get("url") is not None:
        url = check_display_url(data.get("url"))
        if not url:
            raise _shape(USE_READ, "url")
    return BlogInfo(blog_id, name, url)


# ---- B: 초안 저장 ------------------------------------------------------------------------------------------------------------------------
def encode_post(post):
    """초안으로 보낼 본문 — JSON 한 객체(`kind`·`title`·`content`·`labels` 는 있을 때만). 1 MiB 를 넘으면 CONTENT_INVALID."""
    body = {"kind": KIND, "title": post.title, "content": post.html}
    if post.labels:
        body["labels"] = list(post.labels)
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_BODY:
        raise AppError("CONTENT_INVALID", {"항목": "본문 크기"})
    return data


def _status(data, use, *, sent):
    value = data.get("status")
    if value is None:
        return str()
    if not isinstance(value, str) or not 0 < len(value) <= 20:
        raise _shape(use, "status", sent=sent)
    return value.upper()


def _not_draft(use):
    return AppError("BLOGGER_NOT_DRAFT", {}, detail=f"{use}:not_draft")


def insert_draft(client, token, blog_id, post):
    """`POST /blogger/v3/blogs/<번호>/posts` — **초안 저장**(쓰기 한 가지). 응답이 공개(LIVE)·예약 같은 초안이 아닌 상태면 `BLOGGER_NOT_DRAFT`(되돌리는 일은 사람),
    모양이 이상하면 `NET_RESPONSE_INVALID`(서버가 저장했을 수 있어 `outcome_unknown=True`). 자동으로 다시 보내지 않는다 — 한 번 부르면 요청 한 건이다."""
    capabilities.require_external_write("Blogger 초안 저장")
    capabilities.require_net(USE_DRAFT, "Blogger 초안 저장")
    blog_id = check_number(blog_id, "블로그 번호(숫자)")
    body = encode_post(post)
    response = client.request(USE_DRAFT, "POST", url_for(USE_DRAFT, "POST", f"/blogger/v3/blogs/{blog_id}/posts"), body=body, bearer=token.reveal())
    if not response.ok:
        raise failure(response, write=True)
    data = _object(response, sent=True)
    post_id = data.get("id")
    if not isinstance(post_id, str) or NUMBER.fullmatch(post_id) is None:
        raise _shape(USE_DRAFT, "post_id", sent=True)
    owner = data.get("blog")
    if owner is not None and (not isinstance(owner, dict) or str(owner.get("id")) != blog_id):
        raise _shape(USE_DRAFT, "blog_id", sent=True)
    status = _status(data, USE_DRAFT, sent=True)
    if status and status != DRAFT:
        raise _not_draft(USE_DRAFT)
    url = str()
    if data.get("url") is not None:
        url = check_display_url(data.get("url"))
        if not url:
            raise _shape(USE_DRAFT, "url", sent=True)
    return Inserted(post_id, blog_id, status, url)


# ---- C: 같은 제목 초안 찾기 ----------------------------------------------------------------------------------------------------------------
def find_drafts(client, token, blog_id):
    """`GET …/posts` 의 고정 질의(최근 고친 초안 5개, 본문 없이) → `DraftItem` 튜플(없으면 빈 튜플). 항목의 모양이 틀리면 `NET_RESPONSE_INVALID`."""
    capabilities.require_net(USE_READ, "Blogger 같은 제목 초안 찾기")
    blog_id = check_number(blog_id, "블로그 번호(숫자)")
    response = _get(client, USE_READ, f"/blogger/v3/blogs/{blog_id}/posts", token)
    if not response.ok:
        raise failure(response, write=False)
    data = _object(response)
    items = data.get("items")
    if items is None:
        return ()
    if not isinstance(items, list):
        raise _shape(USE_READ, "items")
    found = []
    for item in items[:MAX_ITEMS]:
        if not isinstance(item, dict):
            raise _shape(USE_READ, "item")
        post_id, title = item.get("id"), item.get("title")
        updated = parse_rfc3339(item.get("updated"))
        if not isinstance(post_id, str) or NUMBER.fullmatch(post_id) is None or not isinstance(title, str) or len(title) > MAX_TITLE_ECHO or updated is None:
            raise _shape(USE_READ, "item")
        found.append(DraftItem(post_id, title, updated, _status(item, USE_READ, sent=False)))
    return tuple(found)


# ---- D: 초안인지 확인 ----------------------------------------------------------------------------------------------------------------------
def get_post(client, token, blog_id, post_id):
    """`GET …/posts/<글번호>` 의 고정 질의(관리자 수준) → `PostStatus`. 상태가 있고 `DRAFT` 가 아니면 `BLOGGER_NOT_DRAFT`. 상태가 없으면 '확인하지 못함'(빈 글)이다."""
    capabilities.require_net(USE_READ, "Blogger 초안인지 확인")
    blog_id = check_number(blog_id, "블로그 번호(숫자)")
    post_id = check_number(post_id, "글 번호(숫자)")
    response = _get(client, USE_READ, f"/blogger/v3/blogs/{blog_id}/posts/{post_id}", token)
    if not response.ok:
        raise failure(response, write=False)
    data = _object(response)
    if str(data.get("id")) != post_id:
        raise _shape(USE_READ, "post_id")
    status = _status(data, USE_READ, sent=False)
    if status and status != DRAFT:
        raise _not_draft(USE_READ)
    return PostStatus(post_id, status)


class BloggerAdapter:
    """한 클라이언트를 들고 로그인·API 요청을 부르는 얇은 묶음 — 흐름(`service/blogger_flow.py`)이 이것으로만 접속한다(시험은 가짜 클라이언트로 같은 묶음을 쓰거나 이 묶음을 통째로 바꾼다)."""

    def __init__(self, client):
        self.client = client

    # 로그인·갱신·취소는 보관소의 값 묶음(`SecretFields`)을 **그대로** 받는다 — 값은 이 층에서만 꺼낸다(서비스·화면 층은 값을 꺼내는 호출이 없어야 한다: `test_source_rules_key_display`).
    def begin_login(self, secrets, port):
        return auth.begin_login(secrets.reveal("client_id"), port)

    def exchange(self, secrets, code, verifier, redirect_uri, *, now):
        return auth.exchange_code(self.client, secrets.reveal("client_id"), secrets.reveal("client_secret"), code, verifier.reveal(), redirect_uri, now=now)

    def refresh(self, secrets, *, now):
        return auth.refresh_access_token(self.client, secrets.reveal("client_id"), secrets.reveal("client_secret"), secrets.reveal("refresh_token"), now=now)

    def revoke(self, secrets):
        """값 묶음의 갱신용 값을 구글에서 취소한다(이미 무효여도 성공)."""
        return auth.revoke_token(self.client, secrets.reveal("refresh_token"))

    def get_blog(self, token, blog_id):
        return get_blog(self.client, token, blog_id)

    def insert_draft(self, token, blog_id, post):
        return insert_draft(self.client, token, blog_id, post)

    def find_drafts(self, token, blog_id):
        return find_drafts(self.client, token, blog_id)

    def get_post(self, token, blog_id, post_id):
        return get_post(self.client, token, blog_id, post_id)


__all__ = ["API_OFF_REASONS", "BlogInfo", "BloggerAdapter", "DraftItem", "Inserted", "LIMIT_REASONS", "PostStatus", "check_number", "encode_post", "failure", "find_drafts", "get_blog", "get_post", "insert_draft",
           "parse_rfc3339", "plain_text"]
