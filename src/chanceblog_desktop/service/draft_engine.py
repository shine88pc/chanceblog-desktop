"""엔진 후보(주제 엔진 보관함의 `TopicCandidate`)로 규칙 기반 초안 한 개를 만든다 — 초안 작성 화면의 서비스 함수. **읽기만 한다**(보관함·설정·채널 프로필 파일 어느 것도 만들거나 고치지 않고 초안은 저장하지 않는다).

왜 따로 있나: `draft_body.make_body(ctx, ref)` 는 **옛 후보 보관함**(`chanceblog.db`)에서 순번이나 번호 앞부분으로 후보를 찾는다. 주제 후보 화면의 후보는 **주제 엔진 보관함**(`topic_engine.db`)에 있고 번호도 순번도 따로라서,
화면의 후보 번호를 `make_body` 에 넘기면 옛 보관함이 비어 있을 때는 후보를 못 찾고, 옛 후보가 있으면 **순번이 같은 전혀 다른 후보의 초안이 만들어진다**. 그래서 이 함수가 엔진 후보를 **번호 전체가 같은 것 하나만** 읽어(순번·앞부분 풀이 없음 — 오인 0)
메모리에서 옛 후보로 옮기고(`legacy_of` — `topics/link.py` 의 `NOT_CARRIED` 표가 정한 대로: 주제·핵심 키워드·보조 키워드·글 종류→글 유형) `make_body` 와 **같은 순서**로 만든다:
긴 무작위 영숫자 거절 → 후보 읽기 → 안전 판정 중지 거절(`CONTENT_INVALID`, 엔진이 계산한 `stop` 과 초안 서비스의 판정 둘 다) → 블로그 정하기(네이버 A·B 만) → 프로필 읽기 → `build_body`.
같은 후보를 옛 보관함에 넣어 `make_body` 로 만든 초안과 글자까지 같다(시험이 견준다). `service/draft_body.py` 는 한 글자도 바꾸지 않았다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..content import candidates as cd
from ..content import draft_body as db
from ..content import draft_options as do
from ..echo import shown_ref
from ..errors import AppError
from ..topics import model
from . import blog_profiles, draft, draft_body
from . import topic_files as tf
from . import topics as topic_service


@dataclass(frozen=True)
class EngineBody:
    candidate_id: str               # 엔진 후보 번호(번호 전체)
    ordinal: int                    # 엔진 보관함의 순번(안내용)
    channel: str                    # 후보의 채널
    blog: str                       # 이번에 만든 네이버 블로그(`naver_a`·`naver_b`)
    post_type: str                  # 이번에 쓴 글 유형(정하지 않았으면 후보 기준으로 정해진 값)
    body: object                    # DraftBody
    options: object                 # DraftOptions
    rejected: bool                  # 후보가 '제외' 상태다(상태는 바꾸지 않았다)
    profile_found: bool             # 그 블로그의 네이버 프로필(설정 파일)을 읽었는가
    channel_found: bool             # 채널 프로필 파일을 읽었는가(없으면 기본 프로필)
    blog_url: str                   # 네이버 프로필의 블로그 주소(프로필이 없으면 '')
    blog_names: tuple               # ((`naver_a`, 표시 이름), (`naver_b`, 표시 이름)) — 채널 프로필의 표시 이름
    stopped: bool = False           # 항상 False — 중지 후보는 이 값을 돌려주지 않고 거절한다(CONTENT_INVALID)
    address: str = "none"           # `blog_url` 이 어디서 왔나: `profile`(옛 네이버 프로필) · `channel`(채널 프로필의 블로그 ID·주소) · `unusable`(적어 둔 주소가 네이버 블로그 주소가 아님) · `none`(어디에도 없음)


_BLOG_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
_BLOG_ADDRESS = re.compile(r"(?i:https)://(?i:blog\.naver\.com)/([A-Za-z0-9_-]{1,40})/?")             # 방식·호스트 글자 크기만 가리지 않는다 — 아이디는 크기를 그대로 둔다
ADDRESS_STATES = ("profile", "channel", "unusable", "none")


def naver_blog_url(text):
    """채널 프로필의 `블로그 ID 또는 주소` → 네이버 블로그 주소(방식 https·호스트 blog.naver.com·경로는 아이디 한 토막). 아이디 한 토막(영문·숫자·`_`·`-`, 40자까지)이거나 그 모양의 주소(끝의 `/` 하나는 괜찮다)
    일 때만 만들고, 그 밖은 `''` 다(다른 호스트·다른 방식·로그인 정보·포트·인자·조각·여러 토막 경로·`//`·공백·200자 넘는 글). 주소 문자열을 풀어 읽는 도구를 쓰지 않고 모양을 통째로 맞춘다 —
    화면의 `네이버 글쓰기 열기` 가 마지막으로 한 번 더 본다(`ui/core/draft_rules.naver_write_url`, 화면 규칙이 더 느슨하다 — 시험이 이 규칙이 만든 주소는 늘 화면 규칙도 받는지 견준다)."""
    if not isinstance(text, str) or not text or len(text) > 200 or any(ch.isspace() for ch in text):
        return ""
    found = _BLOG_ADDRESS.fullmatch(text) if "://" in text else _BLOG_ID.fullmatch(text)
    if found is None:
        return ""
    return "https://blog.naver.com/" + (found.group(1) if "://" in text else text)


def channel_address(blog_ref):
    """채널 프로필의 `blog_ref` 에서 글쓰기 주소의 바탕을 얻는다 → `(주소, 상태)`: 만들었으면 `(주소, "channel")`, 적어 두었지만 네이버 블로그 주소가 아니면 `("", "unusable")`, 비어 있으면 `("", "none")`."""
    if not isinstance(blog_ref, str) or not blog_ref.strip():
        return "", "none"
    url = naver_blog_url(blog_ref)
    return (url, "channel") if url else ("", "unusable")


def legacy_of(engine):
    """엔진 후보 → 옛 후보(메모리에서만 — 어디에도 저장하지 않는다). 옮기는 칸은 `topics/link.py` 의 표가 정한 것뿐이고 값을 만들어 넣지 않는다. 옛 후보의 값 검사(`CANDIDATE_INVALID`)가 그대로 심판이다."""
    return cd.Candidate.new(engine.topic, engine.primary_keyword, (engine.channel,), candidate_id=engine.candidate_id, now=engine.created_at, sub_keywords=tuple(engine.secondary_keywords),
                            post_type=model.to_post_type(engine.content_type), status=engine.work_status)


def find_row(ctx, candidate_id):
    """엔진 보관함(읽기 전용)에서 **번호 전체가 같은** 후보 줄 하나. 순번·앞부분으로는 찾지 않는다. 없으면 `TOPIC_CANDIDATE_NOT_FOUND`."""
    wanted = candidate_id if isinstance(candidate_id, str) else ""
    listed = topic_service.list_candidates(ctx)
    row = next((item for item in listed.rows if item.candidate.candidate_id == wanted), None) if wanted else None
    if row is None:
        raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": shown_ref(wanted) if wanted else "(비어 있음)"}, detail="엔진 보관함에 이 번호의 후보가 없다")
    return row


def _refuse_stop(row, legacy):
    """자동 초안 중지 — 엔진이 계산한 `stop` 과 초안 서비스의 판정(`draft_body.screen`)이 **둘 다** 본다. 하나라도 중지면 본문을 만들지 않는다(입력한 글을 오류에 적지 않는다)."""
    report = draft_body.screen(legacy)                              # 중지면 CONTENT_INVALID — `make_body` 와 같은 오류·같은 문구
    if row.stop:
        raise AppError("CONTENT_INVALID", {"항목": db.STOP_ITEM}, detail="주제 엔진의 안전 판정이 자동 초안 중지인 후보라 본문 초안을 만들지 않았다(입력한 글은 적지 않는다)")
    return report


def make_body_for_engine(ctx, candidate_id, *, blog=None, post_type=None, options=None):
    """엔진 후보(번호 전체)로 규칙 기반 초안 한 개를 만든다. 읽기만 한다. 오류는 `make_body` 와 같은 코드(`CONTENT_INVALID`·`DRAFT_OPTION_INVALID`·`CANDIDATE_INVALID` …)이고 후보가 없으면 `TOPIC_CANDIDATE_NOT_FOUND` 다."""
    options = options if options is not None else do.DraftOptions()
    draft.refuse_long_tokens(options)
    row = find_row(ctx, candidate_id)
    legacy = legacy_of(row.candidate)
    report = _refuse_stop(row, legacy)
    chosen, _notes = draft_body.choose_naver_blog(legacy, blog)
    profile, found = draft.load_profile(ctx, chosen)
    snapshot = blog_profiles.read_snapshot(ctx)
    channel = next(item for item in snapshot.profiles if item.key == chosen)
    names = tuple((item.key, item.display_name) for item in snapshot.profiles if item.key in ("naver_a", "naver_b"))
    body = db.build_body(legacy, profile, options, today=draft.today_kst(ctx), blog=chosen, post_type=post_type, channel=channel, safety=report)
    old_url = getattr(profile, "blog_url", "") if profile is not None else ""
    blog_url, address = (old_url, "profile") if old_url else channel_address(channel.blog_ref)           # 옛 네이버 프로필에 주소가 있으면 지금까지와 같다 — 없을 때만 채널 프로필(블로그 관리 화면)에서 얻는다
    return EngineBody(row.candidate.candidate_id, row.ordinal, row.candidate.channel, chosen, body.post_type, body, options, row.candidate.work_status == cd.REJECTED, found, snapshot.state == tf.STATE_OK,
                      blog_url, names, address=address)


@dataclass(frozen=True)
class BlogContext:
    """저장한 초안을 다시 열 때 필요한 블로그 쪽 정보 — `make_body_for_engine` 이 초안과 함께 알려 주던 것(블로그 이름들·글쓰기 주소와 그 출처·프로필을 읽었나)."""
    blog: str
    blog_names: tuple
    blog_url: str
    address: str
    profile_found: bool
    channel_found: bool


def blog_context(ctx, blog):
    """그 네이버 블로그(`naver_a`·`naver_b`)의 이름·글쓰기 주소 — 초안을 만들 때와 **같은 규칙**이다(옛 프로필 주소가 먼저, 없으면 채널 프로필의 블로그 ID·주소). 읽기만 한다. 설정 파일이 깨졌으면 그 오류(`SETTINGS_INVALID` 등)를 그대로 낸다."""
    profile, found = draft.load_profile(ctx, blog)
    snapshot = blog_profiles.read_snapshot(ctx)
    channel = next(item for item in snapshot.profiles if item.key == blog)
    names = tuple((item.key, item.display_name) for item in snapshot.profiles if item.key in ("naver_a", "naver_b"))
    old_url = getattr(profile, "blog_url", "") if profile is not None else ""
    blog_url, address = (old_url, "profile") if old_url else channel_address(channel.blog_ref)
    return BlogContext(blog, names, blog_url, address, found, snapshot.state == tf.STATE_OK)


__all__ = ["BlogContext", "EngineBody", "blog_context", "channel_address", "find_row", "legacy_of", "make_body_for_engine", "naver_blog_url"]
