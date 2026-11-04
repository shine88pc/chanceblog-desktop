"""실제 서비스 층(`service/`)을 화면의 서비스 인터페이스(`ui/core/services.py`)로 맞추는 얇은 어댑터 — **읽기 전용**이다(보관함을 만들거나 바꾸지 않고 네트워크·로그인을 쓰지 않는다).

화면은 서비스 층을 직접 부르지 않는다. 여기서는 후보 목록(`candidates list` 와 같은 함수)과 글 목록(작성·발행 완료 수)을 읽어 화면용 값(`Topic`·`BlogInfo`·`HomeData`)으로 바꾸기만 한다.
가져올 수 없는 값은 `None` 으로 두어 화면이 보이지 않게 한다(지어내지 않는다). 서비스 층의 오류(`AppError`)는 쉬운 문장 + 오류 코드(진단 정보용)의 `ServiceFailure` 로 바꾼다 —
입력한 글이나 비밀이 오류 문구에 들어가지 않는다(오류 문구는 오류 코드 표의 정해진 문장이다). 이 모듈은 PySide6 를 모른다.

**화면에 나갈 글을 자를 때는 가리기가 먼저, 자르기가 나중이다** — 키·토큰은 반쪽으로 잘리면 가림 규칙이 알아보지 못해 앞부분이 그대로 보인다.
그래서 이 모듈은 글을 직접 자르지 않고(후보의 제목·설명·키워드·이유는 값 그대로 넘기고 뷰모델이 `shown` 으로 가린 뒤 줄인다), 꼭 줄여야 하는 블로그 이름도 같은 `shown`(가리기→자르기)을 쓴다.
오류 문구의 값 자리(`「…」`)는 오류 층이 160자에서 자르기 때문에, 자르기 전에 이 모듈이 값을 먼저 가려서 넘긴다.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..content import candidates as cd
from ..content import status as st
from ..errors import AppError
from ..errors.render import render
from ..security.mask import mask
from ..service import candidates as candidate_service
from ..service import projects as project_service
from ..service.context import make_context
from .core.app_state import shown
from .core.jobs import JobCancelled
from .core.services import BlogInfo, HomeData, HomeProvider, ServiceFailure, Topic
from .core.text import T

TREND = {"상승": "up", "보합": "flat", "하락": "down"}
ICONS = (("t_spark", "blue"), ("t_bolt", "orange"), ("t_laptop", "purple"), ("t_calc", "green"), ("t_box", "blue"), ("t_droplet", "green"))
BLOG_KEYS = {"naver_a": "A", "naver_b": "B"}
DONE_STATES = frozenset({st.APPROVED, st.READY_TO_COPY, st.COPY_COMPLETED, st.DRAFT_SAVED, st.COMMITTED, st.PUSHED, st.PUBLISHED, st.PUBLISHED_MANUAL})
STATUS = {cd.NEW: "new", cd.REVIEW: "new", cd.SELECTED: "selected", cd.HOLD: "hold"}
NAME_LIMIT = 30                                                                       # 블로그 이름이 오른쪽 패널에 보이는 최대 글자 수(가린 뒤에 줄인다)
WRITE_WORDED_CODES = frozenset({"FILE_WRITE_FAILED", "FILE_IN_USE"})                  # '저장하지 못했다·바꾸지 못했다' 로 말하는 오류 — 읽기만 하는 화면에서는 어색해 '읽지 못했다' 로 바꾼다(코드는 진단 정보에 그대로)


def is_folder(path):
    """`--data-dir` 로 받은 경로가 이미 있는 폴더인가(읽기만 한다) — 파일이거나 없으면 아니다. 알 수 없는 경로(널 문자 등)도 아니다. 서비스 층(`Workspace.resolve`)과 같이 `~` 는 사용자 폴더로 푼다."""
    try:
        return Path(os.path.expanduser(str(path))).is_dir()
    except (OSError, ValueError):
        return False


def priority_label(score):
    """콘텐츠 작성 우선도(0~100) → 높음·보통·낮음. 값이 없으면 빈 글(지어내지 않는다)."""
    if score is None:
        return ""
    return "높음" if score >= 70 else "보통" if score >= 40 else "낮음"


def to_topic(candidate, index=0):
    blogs = tuple(key for name, key in BLOG_KEYS.items() if name in candidate.blogs)
    icon, tone = ICONS[index % len(ICONS)]                                          # 장식(분야를 모르므로 돌려 가며 쓴다)
    months = candidate.seasonality
    return Topic(
        id=candidate.candidate_id, title=candidate.topic, blogs=blogs, desc=candidate.reason or candidate.keyword, keywords=(candidate.keyword,) + tuple(candidate.sub_keywords)[:2],
        post_type=candidate.post_type, status=STATUS.get(candidate.status, "new"), priority=priority_label(candidate.priority),
        date=candidate.data_date or str(candidate.created_at)[:10], demand=candidate.search_demand, docs=candidate.related_blog_results, trend=TREND.get(candidate.trend),
        mobile=None if candidate.mobile_share is None else int(candidate.mobile_share), season=None if not months else "·".join(f"{month}월" for month in months),
        written=candidate.duplicate, icon=icon, tone=tone, reason=candidate.reason)


def failure_from(error):
    """서비스 층 오류 → 화면용 실패(쉬운 문장 + 오류 코드). 세부(detail)는 화면에 내지 않는다. 문구의 값 자리는 오류 층이 160자에서 자르기 **전에** 비밀 모양을 가린다(자르기가 먼저면 키가 반쪽이 되어 안 가려진다)."""
    if error.code in WRITE_WORDED_CODES:
        return ServiceFailure(T["data_unreadable"], code=error.code, retryable=True)
    shown_text = render(error.code, {name: mask(value) for name, value in error.slots.items()})
    return ServiceFailure(f"{shown_text.message} {shown_text.action}".strip(), code=error.code, retryable=True)


class ServiceHomeProvider(HomeProvider):
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context

    def _projects(self, ctx):
        """(작성 완료 수, 발행 완료 수) — 집계할 수 없으면 (None, None). 글 저장소가 없으면 0 이다."""
        try:
            rows = project_service.list_projects(ctx.reading_only())
        except AppError as error:
            return (0, 0) if error.code == "CONTENT_NOT_FOUND" else (None, None)
        done = sum(1 for row in rows if any(status in DONE_STATES for status in row.statuses.values()))
        published = sum(1 for row in rows if any(st.is_published(platform, status) for platform, status in row.statuses.items()))
        return done, published

    def _names(self, ctx):
        """블로그 A·B 의 표시 이름 — 네이버 프로필에 정한 이름이 있으면 그것, 없으면 기본 이름. 설정 파일이 깨졌으면 숨기지 않고 오류(SETTINGS_INVALID)로 알린다.
        이름은 **비밀 모양을 가린 뒤에** `NAME_LIMIT` 자로 줄인다(`shown` — 가리기 → 자르기. 거꾸로 하면 이름에 든 키의 앞 20여 글자가 오른쪽 패널에 그대로 보인다)."""
        names = {"A": "블로그 A", "B": "블로그 B"}
        for key, raw in ctx.settings.naver_profile_dicts().items():
            label = BLOG_KEYS.get(key)
            if label and isinstance(raw, dict) and isinstance(raw.get("display_name"), str) and raw["display_name"].strip():
                names[label] = shown(raw["display_name"], NAME_LIMIT) or names[label]          # 가린 뒤 비면(눈에 안 보이는 글자뿐) 기본 이름
        return names

    def load_home(self, progress, cancelled):
        if self._data_dir is not None and not is_folder(self._data_dir):                # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(기본 위치는 아직 없어도 빈 화면 — 처음 쓰는 PC)
            raise ServiceFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", retryable=True)
        try:
            ctx = self._factory(data_dir=self._data_dir)
            result = candidate_service.list_candidates(ctx)
            if cancelled():                                                          # 단계 사이마다 취소를 본다(서비스 함수 하나가 도는 동안은 끊을 수 없다)
                raise JobCancelled()
            done, published = self._projects(ctx)
            names = self._names(ctx)
        except AppError as error:
            raise failure_from(error) from None
        if cancelled():
            raise JobCancelled()
        topics = tuple(to_topic(row.candidate, index) for index, row in enumerate(row for row in result.rows if row.candidate.status != cd.REJECTED))
        blogs = tuple(BlogInfo(key, names[key], candidates=sum(1 for topic in topics if key in topic.blogs and topic.status != "hold")) for key in ("A", "B"))
        return HomeData(topics=topics, blogs=blogs, done=done, pub=published, sample=False)
