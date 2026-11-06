"""실제 서비스 층(`service/`)을 화면의 서비스 인터페이스(`ui/core/services.py`)로 맞추는 얇은 어댑터 — **읽기 전용**이다(보관함을 만들거나 바꾸지 않고 네트워크·로그인을 쓰지 않는다).

화면은 서비스 층을 직접 부르지 않는다. 여기서는 후보 목록(`candidates list` 와 같은 함수)과 글 목록(작성·발행 완료 수)을 읽어 화면용 값(`Topic`·`BlogInfo`·`HomeData`)으로 바꾸기만 한다.
홈의 새 구역(UI-C1c)도 같은 원칙이다 — 주제 엔진의 우수 후보 읽기(`top_candidates`)와 글 목록을 **읽기만** 해서 `BoardData`(채널 A·B 추천 최대 5개·작성 중 초안 최대 5개)로 바꾼다. 구역마다 따로 읽고 따로 실패한다(한 구역의 실패가 홈 전체를 막지 않는다).
가져올 수 없는 값은 `None` 으로 두어 화면이 보이지 않게 한다(지어내지 않는다). 서비스 층의 오류(`AppError`)는 쉬운 문장 + 오류 코드(진단 정보용)의 `ServiceFailure` 로 바꾼다 —
입력한 글이나 비밀이 오류 문구에 들어가지 않는다(오류 문구는 오류 코드 표의 정해진 문장이다). 이 모듈은 PySide6 를 모른다.

**화면에 나갈 글을 자를 때는 가리기가 먼저, 자르기가 나중이다** — 키·토큰은 반쪽으로 잘리면 가림 규칙이 알아보지 못해 앞부분이 그대로 보인다.
그래서 이 모듈은 글을 직접 자르지 않고(후보의 제목·설명·키워드·이유는 값 그대로 넘기고 뷰모델이 `shown` 으로 가린 뒤 줄인다), 꼭 줄여야 하는 블로그 이름도 같은 `shown`(가리기→자르기)을 쓴다.
오류 문구의 값 자리(`「…」`)는 오류 층이 160자에서 자르기 때문에, 자르기 전에 이 모듈이 값을 먼저 가려서 넘긴다.
"""
from __future__ import annotations

import os
import time
from itertools import islice
from pathlib import Path

from ..content import candidates as cd
from ..content import status as st
from ..errors import AppError
from ..errors.render import render
from ..security.mask import mask
from ..service import candidates as candidate_service
from ..service import connections as connection_service
from ..service import projects as project_service
from ..service import quota as quota_service
from ..service.context import make_context
from .core.app_state import shown
from .core.jobs import JobCancelled
from .core.services import (HOME_CHANNELS, HOME_LIMIT, INTERESTS, ON_DEMAND, BlogInfo, BoardData, ChannelRead, ConnectionsData, ConnectionsProvider, DraftRow, EntryInfo, HomeData, HomeProvider,
                            ListRead, PurposeInfo, RecentRow, RecommendRow, ServiceFailure, Topic, UsageInfo)
from .core.text import T
from .core.timed import call_within

TREND = {"상승": "up", "보합": "flat", "하락": "down"}
ICONS = (("t_spark", "blue"), ("t_bolt", "orange"), ("t_laptop", "purple"), ("t_calc", "green"), ("t_box", "blue"), ("t_droplet", "green"))
BLOG_KEYS = {"naver_a": "A", "naver_b": "B"}
DONE_STATES = frozenset({st.APPROVED, st.READY_TO_COPY, st.COPY_COMPLETED, st.DRAFT_SAVED, st.COMMITTED, st.PUSHED, st.PUBLISHED, st.PUBLISHED_MANUAL})
STATUS = {cd.NEW: "new", cd.REVIEW: "new", cd.SELECTED: "selected", cd.HOLD: "hold"}
NAME_LIMIT = 30                                                                       # 블로그 이름이 오른쪽 패널에 보이는 최대 글자 수(가린 뒤에 줄인다)
WRITE_WORDED_CODES = frozenset({"FILE_WRITE_FAILED", "FILE_IN_USE"})                  # '저장하지 못했다·바꾸지 못했다' 로 말하는 오류 — 읽기만 하는 화면에서는 어색해 '읽지 못했다' 로 바꾼다(코드는 진단 정보에 그대로)
RECENT_TIMEOUT = 1.5                                                                  # 최근 발행: 글 하나를 읽는 데 기다리는 최대 시간(초) — 넘으면 그 글만 '발행일 확인 불가'(실제 읽기는 보통 수십 밀리초 — 합성 글 400개에서 다섯 편 0.2초)
RECENT_BUDGET = 4.0                                                                   # 최근 발행: 다섯 편을 읽는 데 쓰는 전체 시간(초) — 다 쓰면 남은 글은 읽지 않고 '발행일 확인 불가'(홈 전체를 오래 붙잡지 않는다)
CHANNEL_CODES = {key: name for name, key in BLOG_KEYS.items()}                        # 홈의 채널 A·B → 서비스(주제 엔진)의 채널 이름
STORE_REASONS = {"missing": "missing", "empty": "missing", "old_structure": "old"}   # 주제 엔진 보관함 상태 → 화면의 '읽을 보관함이 없다' 이유(없음·0바이트는 '없음', 옛 구조는 '옛 구조') — 그 밖의 상태(`ready`)는 읽는다
STAGE_OF = {st.DRAFT_GENERATED: "generated", st.REVIEW_REQUIRED: "review"}           # 작성 중 초안 = 승인 전(초안 생성됨·검토 필요) — 운영자 2026-11-06 확인 요청 004 의 답 홈 구성
ENGINE_WORDED = {"TOPIC_STORE_CORRUPT": "board_err_store", "CANDIDATE_INVALID": "board_err_store", "TOPIC_STORE_VERSION_UNSUPPORTED": "board_err_newer", "TOPIC_STORE_LOCKED": "board_err_locked",
                 "TOPIC_STORE_RECOVERY_PENDING": "board_err_pending", "TOPIC_FILE_INVALID": "board_err_profiles", "CONTENT_INVALID": "board_err_profiles"}      # 주제 엔진을 읽다 날 수 있는 오류 — 카탈로그 안내문에는 명령줄 글(`topics restore …`)이 섞여 있어 화면용 쉬운 문장으로 바꾼다(코드는 진단 정보에 그대로)


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


def engine_failure(error):
    """주제 엔진을 읽다 난 서비스 오류 → 화면용 실패(쉬운 문장 + 오류 코드). 위 표의 오류는 명령 없는 화면 문장으로, 나머지는 홈과 같은 `failure_from` 으로. 세부(detail)는 어느 쪽도 화면에 내지 않는다."""
    wording = ENGINE_WORDED.get(error.code)
    return ServiceFailure(T[wording], code=error.code, retryable=True) if wording else failure_from(error)


def interest_of(status):
    """엔진 후보의 관심도 상태(`rising`·`flat`·`falling`·`insufficient`) → 화면의 관심도. 방향을 말할 수 있는 셋만 그대로 두고 데이터 부족(그 밖의 값 포함)은 None 이다."""
    return status if status in INTERESTS else None


def draft_stage(statuses):
    """한 글의 플랫폼별 상태에서 '작성 중' 단계 — 검토 필요가 하나라도 있으면 `review`, 아니면 초안 생성됨이 있으면 `generated`, 승인 전 상태가 하나도 없으면 None."""
    found = {STAGE_OF[status] for status in statuses.values() if status in STAGE_OF}
    return "review" if "review" in found else "generated" if found else None


def newest_first(rows):
    """글 줄들을 마지막으로 고친 때가 늦은 것부터(같으면 번호가 큰 것부터) — 시각 글(UTC `…Z`)은 글자 순서가 시간 순서다."""
    return sorted(rows, key=lambda row: (str(row.updated_at), row.project_id), reverse=True)


class Counts(tuple):
    """(작성 완료 수, 발행 완료 수) — 두 값으로 풀어 쓸 수 있고, **같은 불러오기 안에서 읽은 글 목록**(`rows`)과 읽지 못한 오류(`error`)를 함께 들고 있어 홈의 작성 중 초안·최근 발행이 글 목록을 다시 읽지 않는다.
    글 목록을 읽지 못했으면 수는 (None, None) 이고 `rows` 는 None, 글 저장소가 아직 없으면 (0, 0) 이고 `rows` 는 빈 목록이다."""

    def __new__(cls, done, published, rows=None, error=None):
        found = super().__new__(cls, (done, published))
        found.rows, found.error = rows, error
        return found


class ServiceEngine:
    """주제 엔진을 **읽기만** 한다 — 서비스의 읽기 함수(우수 후보 `top_candidates`·채널 프로필 읽기)만 부른다(보관함·설정 파일을 만들거나 바꾸지 않고, 파일이 없으면 없는 채로 읽는다).
    서비스 모듈은 함수 안에서 가져온다(주제 엔진 코드를 이 화면이 처음 읽을 때까지 올리지 않는다). 시험은 같은 모양(`top`·`names`)의 가짜로 바꿔 끼운다."""

    def top(self, ctx):
        from ..service import topics as topic_service
        return topic_service.top_candidates(ctx)

    def names(self, ctx):
        """채널 프로필의 표시 이름 `{채널 이름: 이름}` — 설정 파일(`channel_profiles.json`)이 없으면 기본 프로필의 이름이다."""
        from ..service import topic_files
        return {profile.key: profile.display_name for profile in topic_files.load_profiles(topic_files.topic_paths(ctx.workspace)).value}


class ServiceHomeProvider(HomeProvider):
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None, engine=None, show_project=None, recent_timeout=RECENT_TIMEOUT, recent_budget=RECENT_BUDGET, monotonic=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context
        self._engine = engine or ServiceEngine()                                     # 주제 엔진을 읽는 곳(`top`·`names`) — 시험이 가짜를 끼운다
        self._show = show_project                                                    # 글 하나를 읽는 함수 `(ctx, 글 번호) → 글` — 없으면 서비스의 `show_project`(시험이 느린·실패하는 가짜를 끼운다)
        self._item_timeout, self._budget, self._monotonic = recent_timeout, recent_budget, monotonic or time.monotonic

    def connections_provider(self):
        """설정 화면의 짝 공급자 — 같은 데이터 폴더를 읽는다(홈과 같은 `--data-dir`)."""
        return ServiceConnectionsProvider(self._data_dir, context_factory=self._factory)

    def _projects(self, ctx):
        """(작성 완료 수, 발행 완료 수) — 집계할 수 없으면 (None, None). 글 저장소가 없으면 0 이다. 읽은 글 목록(`rows`)과 오류(`error`)도 들고 있다(`Counts`)."""
        try:
            rows = project_service.list_projects(ctx.reading_only())
        except AppError as error:
            return Counts(0, 0, []) if error.code == "CONTENT_NOT_FOUND" else Counts(None, None, None, error)
        done = sum(1 for row in rows if any(status in DONE_STATES for status in row.statuses.values()))
        published = sum(1 for row in rows if any(st.is_published(platform, status) for platform, status in row.statuses.items()))
        return Counts(done, published, rows)

    def _explicit_names(self, ctx):
        """네이버 프로필에 **사용자가 정한** 블로그 이름만 `{A·B: 이름}` — 정하지 않은(또는 가리면 비는) 블로그는 없다. 이름은 **비밀 모양을 가린 뒤에** `NAME_LIMIT` 자로 줄인다
        (`shown` — 가리기 → 자르기. 거꾸로 하면 이름에 든 키의 앞 20여 글자가 오른쪽 패널에 그대로 보인다)."""
        names = {}
        for key, raw in ctx.settings.naver_profile_dicts().items():
            label = BLOG_KEYS.get(key)
            if label and isinstance(raw, dict) and isinstance(raw.get("display_name"), str) and raw["display_name"].strip():
                found = shown(raw["display_name"], NAME_LIMIT)
                if found:                                                              # 가린 뒤 비면(눈에 안 보이는 글자뿐) 정하지 않은 것
                    names[label] = found
        return names

    def _names(self, ctx):
        """블로그 A·B 의 표시 이름 — 네이버 프로필에 정한 이름이 있으면 그것, 없으면 기본 이름. 설정 파일이 깨졌으면 숨기지 않고 오류(SETTINGS_INVALID)로 알린다."""
        return {"A": "블로그 A", "B": "블로그 B", **self._explicit_names(ctx)}

    # ---- 홈의 새 구역(UI-C1c) — 읽기만 하고, 구역마다 따로 실패한다 ----
    def _profile_names(self, ctx):
        """채널 프로필의 표시 이름 — 이름을 보이려고 한 번 더 읽을 뿐이라 못 읽어도(어떤 오류든) 그냥 비운다(그러면 이름은 서비스의 채널 이름이 된다)."""
        try:
            return self._engine.names(ctx)
        except Exception:                                                              # 이름 읽기가 추천 구역을 막지 않는다
            return {}

    def _channels(self, ctx):
        """채널 A·B 의 추천 구역 — 서비스의 우수 후보 읽기를 **한 번만** 부르고, 채널마다 서비스가 고른 앞줄을 `HOME_LIMIT` 개까지만 받는다(전부 읽어 자르지 않는다 — 많이 들어와도 앞의 다섯만 본다).
        다만 서비스의 `top_candidates` 자신이 안에서 후보 전체를 읽어 고른다(합성 후보 천 개에 1.4초 안팎 — 작업 스레드에서 돌아 화면은 안 막힌다. 서비스에 앞줄만 가볍게 읽는 함수가 생기면 빨라진다: 서비스 변경이라 `DEFERRED`).
        표시 이름은 **사용자가 네이버 프로필에 정한 이름 → 채널 프로필의 표시 이름 → 서비스의 채널 이름** 순서로 정한다(모두 가린 뒤에 줄인다). 읽지 못하면 두 채널이 같은 오류 구역이 되고 다른 구역은 그대로다."""
        explicit = self._explicit_names(ctx)
        try:
            result = self._engine.top(ctx)
        except JobCancelled:
            raise
        except AppError as error:
            return self._failed_channels(explicit, engine_failure(error))
        except Exception as error:                                                     # 보관함·파일을 못 읽은 이상한 오류 — 쉬운 문장 + 예외 이름(진단용)만, 내용·경로는 싣지 않는다
            return self._failed_channels(explicit, ServiceFailure(T["data_unreadable"], code=type(error).__name__, retryable=True))
        profile_names = self._profile_names(ctx)
        by_name = {item.channel: item for item in result.channels}
        reason = STORE_REASONS.get(result.store_state)
        channels = []
        for key in HOME_CHANNELS:
            code = CHANNEL_CODES[key]
            top = by_name.get(code)
            name = explicit.get(key) or shown(profile_names.get(code, ""), NAME_LIMIT) or (shown(top.name, NAME_LIMIT) if top is not None else "")
            enabled = None if top is None else top.enabled
            if reason is not None:
                channels.append(ChannelRead(key, name, enabled, "unavailable", reason))
                continue
            rows = () if top is None else tuple(RecommendRow(row.candidate.candidate_id, row.candidate.topic, row.candidate.scores.final, None, interest_of(row.candidate.trend_status))
                                                for row in islice(top.rows, HOME_LIMIT))
            channels.append(ChannelRead(key, name, enabled, "ok", "", rows, 0 if top is None else len(top.problems)))
        return tuple(channels)

    @staticmethod
    def _failed_channels(explicit, failure):
        return tuple(ChannelRead(key, explicit.get(key, ""), None, "failed", "", (), 0, failure) for key in HOME_CHANNELS)

    @staticmethod
    def _drafts(counts):
        """작성 중 초안 — 이미 읽은 글 목록(`counts`)에서 승인 전(초안 생성됨·검토 필요) 단계의 글을 고친 때가 늦은 순으로 최대 `HOME_LIMIT` 개. 글 목록을 못 읽었으면 이 구역만 오류다."""
        if counts.error is not None:
            return ListRead("failed", (), 0, failure_from(counts.error))
        rows = counts.rows or ()
        readable = [row for row in rows if not row.error]
        drafting = [(row, draft_stage(row.statuses)) for row in newest_first(readable)]
        found = tuple(DraftRow(row.project_id, row.title, stage, str(row.updated_at)) for row, stage in islice((item for item in drafting if item[1]), HOME_LIMIT))
        return ListRead("ok", found, len(rows) - len(readable))

    def _published_at(self, ctx, project_id, left):
        """글 하나의 발행한 때 — 글을 한 번 더 읽어(`show_project`) 발행된 플랫폼들의 `published_at` 중 가장 늦은 것. 제한 시간(`left` 초 안에서 `RECENT_TIMEOUT`) 안에 못 읽거나 읽다 실패하거나 값이 없으면 None('발행일 확인 불가').
        마지막으로 고친 때(`updated_at`)로 대신하지 않는다 — 고친 때는 발행한 때가 아니다."""
        show = self._show or project_service.show_project
        try:
            view = call_within(min(self._item_timeout, left), show, ctx.reading_only(), project_id)
        except JobCancelled:
            raise
        except Exception:                                                              # 시간 초과·읽기 실패·이상한 값 — 이 글만 날짜를 모르고 다른 글과 홈은 그대로다
            return None
        stamps = [variant.published_at for variant in view.variants if st.is_published(variant.platform, variant.status) and isinstance(variant.published_at, str) and variant.published_at]
        return max(stamps) if stamps else None

    def _recent(self, ctx, counts, cancelled):
        """최근 발행(**임시 방식** — 서비스 목록에 발행한 때가 없어 글마다 읽는다, 운영자 2026-11-06 확인 요청 004 의 답 6) — 이미 읽은 글 목록에서 발행한 글을 **고친 때가 늦은 순으로 최대 `HOME_LIMIT` 편만** 골라
        글마다 발행한 때를 읽고(`_published_at` — 글마다 시간 제한, 다섯 편 전체에도 시간 제한), 발행한 때가 늦은 순으로 놓는다(모르는 글은 뒤). 글 하나의 읽기 실패가 구역 전체를 막지 않는다.
        한계: 고르는 기준이 '고친 때' 라 오래전에 발행했지만 최근에 고친 글이 앞설 수 있다 — 서비스 목록에 발행한 때가 생기면 정확해진다(서비스 변경이라 `DEFERRED`)."""
        if counts.error is not None:
            return ListRead("failed", (), 0, failure_from(counts.error))
        rows = counts.rows or ()
        readable = [row for row in rows if not row.error]
        published = (row for row in newest_first(readable) if any(st.is_published(platform, status) for platform, status in row.statuses.items()))
        started, found = self._monotonic(), []
        for row in islice(published, HOME_LIMIT):
            if cancelled():
                raise JobCancelled()
            left = self._budget - (self._monotonic() - started)
            found.append(RecentRow(row.project_id, row.title, self._published_at(ctx, row.project_id, left) if left > 0 else None))
        found.sort(key=lambda item: item.published or "", reverse=True)                  # 발행한 때가 늦은 것부터, 모르는 것은 뒤(같으면 고친 때 순서 그대로 — 정렬은 순서를 지킨다)
        return ListRead("ok", tuple(found), len(rows) - len(readable))

    def _board(self, ctx, counts, cancelled):
        """홈의 새 구역들을 읽는다 — 구역마다 따로 읽고(`_channels`·`_drafts`·`_recent`) 취소는 구역 사이마다 본다."""
        channels = self._channels(ctx)
        if cancelled():
            raise JobCancelled()
        drafts = self._drafts(counts)
        if cancelled():
            raise JobCancelled()
        recent = self._recent(ctx, counts, cancelled)
        if cancelled():                                                                # 다섯 편을 읽는 동안 취소했으면 결과를 내놓지 않는다
            raise JobCancelled()
        return BoardData(channels, drafts, recent, False)

    def load_home(self, progress, cancelled):
        if self._data_dir is not None and not is_folder(self._data_dir):                # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(기본 위치는 아직 없어도 빈 화면 — 처음 쓰는 PC)
            raise ServiceFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", retryable=True)
        try:
            ctx = self._factory(data_dir=self._data_dir)
            result = candidate_service.list_candidates(ctx)
            if cancelled():                                                          # 단계 사이마다 취소를 본다(서비스 함수 하나가 도는 동안은 끊을 수 없다)
                raise JobCancelled()
            counts = self._projects(ctx)
            done, published = counts
            names = self._names(ctx)
        except AppError as error:
            raise failure_from(error) from None
        if cancelled():
            raise JobCancelled()
        topics = tuple(to_topic(row.candidate, index) for index, row in enumerate(row for row in result.rows if row.candidate.status != cd.REJECTED))
        blogs = tuple(BlogInfo(key, names[key], candidates=sum(1 for topic in topics if key in topic.blogs and topic.status != "hold")) for key in ("A", "B"))
        board = self._board(ctx, counts, cancelled)
        return HomeData(topics=topics, blogs=blogs, done=done, pub=published, sample=False, board=board)


LEDGER_SPANS = ("오늘", "이번 달")                                                      # 장부 제공자(NAVER API HUB)의 한도 줄 — 하루·한 달 시도 수
LIMIT_STOPS = ("blocked", "exhausted")                                                 # 서비스가 '한도에 실제로 닿아' 새 조회를 멈춘 때의 코드 — 서비스의 고정 멈춤 문구는 이때만 화면에 낸다(인증이 아직 확실하지 않은 처음 모습에는 내지 않는다)
SETTINGS_WORDED = {"CONNECTIONS_FILE_INVALID": "conn_file_invalid", "DATA_DIR_UNSAFE": "conn_dir_unsafe"}      # 설정 화면을 읽다 날 수 있는 오류 — 카탈로그 안내문에는 명령줄 글(`keys add`·`.bak` 이름)이 섞여 있어 화면용 쉬운 문장으로 바꾼다(코드는 진단 정보에 그대로)


def settings_failure(error):
    """설정 화면을 읽다 난 서비스 오류 → 화면용 실패(쉬운 문장 + 오류 코드). 위 표의 오류는 명령 없는 화면 문장으로, 나머지는 홈과 같은 `failure_from` 으로. 세부(detail)는 어느 쪽도 화면에 내지 않는다."""
    wording = SETTINGS_WORDED.get(error.code)
    return ServiceFailure(T[wording], code=error.code, retryable=True) if wording else failure_from(error)


def usage_of(spec, view):
    """서비스의 사용량(`UsageView`) → 화면용 한도 줄. 사용량 기록을 못 읽었거나 믿을 수 없으면(`notice`·확인 불가 멈춤) 숫자를 싣지 않고 `readable=False` 로 알린다 — 깨진 파일을 절반으로 가정한 값은 실제 값이 아니다.
    장부 제공자는 시도(실패한 호출도 센다)와 콘솔 한도·한도 단계 안내·멈춤 문구를 함께 준다. 다른 제공자는 첫 항목의 한도 창을 요청 수로 보이고, 한도를 모르는 용도는 숫자가 없다(쉬는 중이면 다시 열리는 때만)."""
    if view is None:
        return None
    ledger = view.ledger
    closed = any(item.fail_closed for item in spec.providers)
    if ledger is not None:
        if view.notice or ledger.stop_code == "unverifiable":
            return UsageInfo(readable=False, fail_closed=closed, stop_cause=ledger.stop_cause)
        stop_text = ledger.stop_text if ledger.stop_code in LIMIT_STOPS else ""            # 고정 문구('…사용할 수 없습니다')는 한도에 실제로 닿았을 때만 — 처음 상태(인증 확인 전)에는 고장 난 것처럼 읽힌다
        return UsageInfo(((LEDGER_SPANS[0], ledger.day_attempts, ledger.day_limit), (LEDGER_SPANS[1], ledger.month_attempts, ledger.month_limit)), True, ledger.console_limit,
                         "" if ledger.stopped else ledger.stage_text, stop_text, ledger.stop_cause, view.resume_text if view.blocked else "", True, closed)       # 멈춘 때는 사유 한 줄(단계 안내가 곧 사유일 수 있다)
    if not view.entries:                                                                 # 키 항목이 없으면 셀 것도 없다(기록 파일이 깨졌어도 말할 것이 없다)
        return None
    if view.notice:
        return UsageInfo(readable=False, fail_closed=closed)
    first = view.rows[0].entry if view.rows else None
    rows = tuple((row.span, row.used, row.limit) for row in view.rows if row.entry == first and row.limit > 0)             # 첫 항목의 한도 창만 — 항목마다 같은 줄이 되풀이되지 않게
    resume = view.resume_text if view.blocked else ""
    return UsageInfo(rows, resume_text=resume) if rows or resume else None


class ServiceConnectionsProvider(ConnectionsProvider):
    """설정 화면(연결 관리)의 실제 공급자 — 서비스 층(`service/connections.py`·`quota.py`)을 **읽기만** 한다(파일을 만들거나 바꾸지 않고 네트워크·로그인을 쓰지 않는다).

    **키 값을 꺼내지 않는다** — 보관소(윈도 자격 증명 관리자)에는 '이 항목의 키가 있나' 만 묻고(`secret_present` → `exists`), `keystore.get` 도 `list_entries` 의 끝 4자 읽기도 부르지 않는다. 항목 이름·상태·사용량 숫자만 화면 값(`PurposeInfo`)이 된다.
    보관소 읽기는 작업 스레드에서 돈다(홈 불러오기처럼). 보관소를 못 열면 키가 있는지만 모르는 채로('연결 확인 필요') 나머지를 보이고(`partial`), 연결 설정 파일이 깨졌으면 숨기지 않고 오류로 알린다(`CONNECTIONS_FILE_INVALID` — 쉬운 문장 + 진단 정보의 코드)."""
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None, registry=None, keystore=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context
        self._registry = registry                                                     # 시험이 호출 코드가 있는 용도가 든 가짜 레지스트리를 끼운다(`None` 이면 실제 서비스 표)
        self._keystore = keystore                                                     # 시험이 가짜 보관소를 끼운다(`None` 이면 컨텍스트의 보관소)

    def _open_keystore(self, ctx, partial):
        if self._keystore is not None:
            return self._keystore
        try:
            return ctx.get_keystore()
        except AppError:                                                              # 보관소를 못 열어도 나머지는 보인다 — 키가 있는지만 모른다
            partial.append("keystore")
            return None

    def load_connections(self, progress, cancelled):
        if self._data_dir is not None and not is_folder(self._data_dir):               # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(홈과 같다)
            raise ServiceFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", retryable=True)
        registry = self._registry or connection_service.PURPOSES
        partial, infos = [], []
        try:
            ctx = self._factory(data_dir=self._data_dir)
            data = connection_service.load(ctx, registry)
            if cancelled():
                raise JobCancelled()
            store = self._open_keystore(ctx, partial)
            guard = quota_service.QuotaGuard(ctx, registry=registry)
            try:
                usages = {view.purpose: view for view in guard.usage()}
            except AppError:                                                          # 사용량 기록만 못 읽었다 — 나머지는 그대로 보인다
                usages = {}
                partial.append("usage")
            for key in connection_service.listed_purposes(data, registry):             # 옛 용도는 항목이 남아 있을 때만
                if cancelled():
                    raise JobCancelled()
                spec = registry[key]
                entries = []
                for entry in data.of_purpose(key):
                    found = connection_service.secret_present(ctx, entry, store)        # True·False, 못 물었으면 None — 값은 꺼내지 않는다
                    if found is None and store is not None and "keystore" not in partial:
                        partial.append("keystore")
                    entries.append(EntryInfo(entry.name, entry.state, found))
                status = guard.purpose_status(key, keystore=store) if spec.takes_keys and not spec.legacy_to else ""
                infos.append(PurposeInfo(key, spec.label, spec.implemented, spec.takes_keys, spec.max_entries, spec.providers[0].rotation, bool(spec.legacy_to), status, tuple(entries),
                                         usage_of(spec, usages.get(key)), key in ON_DEMAND))
        except AppError as error:
            raise settings_failure(error) from None
        if cancelled():
            raise JobCancelled()
        if "usage" not in partial and any(info.usage is not None and not info.usage.readable for info in infos):      # 사용량 기록을 못 읽은 용도가 있다 — 그 줄은 숫자 대신 '확인할 수 없어요' 이고 화면 위에 안내가 붙는다
            partial.append("usage")
        return ConnectionsData(purposes=tuple(infos), sample=False, partial=tuple(partial))
