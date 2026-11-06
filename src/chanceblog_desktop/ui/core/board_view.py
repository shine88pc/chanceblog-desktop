"""홈의 새 구역(UI-C1c)의 뷰모델 — 순수 파이썬(화면 도구·서비스 층을 모른다). 공급자가 준 `BoardData`(`HomeData.board`)를 화면이 그리기만 하면 되는 딕셔너리로 바꾼다.
**지금 화면(UI-C1c)은 이 값을 그리지 않는다** — 새 홈 모양(UI-C1d)이 그린다. 그래서 `AppState.home_view()` 의 옛 키(`cards`·`rows`·`chips`·`rail` …)는 한 글자도 바뀌지 않고 이 값은 새 키 `board` 하나로만 들어간다.

규칙(운영자 2026-11-06 확인 요청 004 의 답 — 홈 구성 5·최근 발행 6·추천 후보 2, 모두 시험이 지킨다):
  · Naver A·B 추천은 채널마다 **최대 5개**(`HOME_LIMIT`)다. 줄은 제목·점수(정수만)·점수 구간(80/65/50 — 점수 링과 같은 `gauges.score_band`)·관심도 라벨뿐이고 **월 검색량·문서 수는 칸도 글도 없다**.
  · 점수가 없으면 링 없이 `점수 계산 전`(0점이 아니다), 관심도가 없으면 `관심도 데이터 부족`, 이전 점수가 없으면 변화량은 숨긴다(`delta` 가 None).
  · 예시(가짜) 값은 줄마다 `예시` 꼬리표가 붙는다. 후보가 없으면 **정상 빈 상태**이고(오류가 아니다) 쓰기 단추(`주제 분석 시작` 같은 것)는 어디에도 없다.
  · 구역마다 따로 상태를 가진다 — 한 구역의 읽기 실패는 그 구역만 오류 상태로 두고 다른 구역과 홈 전체를 막지 않는다. 내부 번호(후보·글 번호)와 영문 상태 이름은 뷰모델의 글에 없다(`key`·`state` 같은 값은 글이 아니라 그림·상태를 고르는 값이다).
  · 최근 발행의 날짜는 **발행한 때**뿐이다 — 마지막으로 고친 때(`updated_at`)로 대신하지 않고, 모르면 `발행일 확인 불가`. 시각은 한국 시각(UTC+9)으로 보인다(주제 엔진의 날짜 기준과 같다).
  · KPI 값이 연결·집계되지 않았으면 0 이 아니라 `연결 전`·`집계 전` 글이다(숫자 칸이 글 상태를 가질 수 있다). 실제 0 은 `0개` 다.
  · 화면에 나가는 글(제목·이름·오류 문장)은 비밀 모양을 가린 뒤에 줄인다(`security.mask`) — 가리기가 먼저, 자르기가 나중이다.
"""
from __future__ import annotations

import datetime
import re
from itertools import islice

from . import gauges
from . import settings_view as sv
from .services import HOME_CHANNELS, HOME_LIMIT, INTERESTS, STAGES
from .text import T

KST = datetime.timezone(datetime.timedelta(hours=9))
_STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z")
NAME_LIMIT = 40                                   # 채널 이름이 화면에 보이는 최대 글자 수(가린 뒤에 줄인다)
TITLE_LIMIT = 200
KPIS = (("topics", "sum_topics"), ("done", "sum_done"), ("pub", "sum_pub"), ("ideas", "sum_ideas"))      # 홈 KPI 넷의 열쇠와 이름 문구 열쇠(옛 요약 카드와 같은 이름)
KPI_STATES = ("value", "before_connect", "before_count")


def _shown(value, limit=300):
    from ...security.mask import safe_detail                                   # 명령줄 출력·홈 화면과 같은 가리기 규칙(가린 뒤에 줄인다)
    return safe_detail(value, limit)


def _count(value):
    """센 수로 믿을 수 있는 값인가 — 0 이상의 정수(불리언은 아니다)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# ---- 시각 글 ------------------------------------------------------------------------------------------------------------------------
def _kst(stamp):
    """UTC 시각 글(`2026-11-06T02:10:00Z`) → 한국 시각, 모양이 다르거나 달력에 없는 날이면 None(지어내지 않는다)."""
    if not isinstance(stamp, str):
        return None
    found = _STAMP.fullmatch(stamp)
    if found is None:
        return None
    try:
        return datetime.datetime(*(int(part) for part in found.groups()), tzinfo=datetime.timezone.utc).astimezone(KST)
    except (ValueError, OverflowError):
        return None


def time_text(stamp):
    """`2026-11-06 11:10`(한국 시각) — 시각을 알 수 없으면 빈 글."""
    moment = _kst(stamp)
    return "" if moment is None else moment.strftime("%Y-%m-%d %H:%M")


def date_text(stamp):
    """`2026-11-06`(한국 날짜) — 날짜를 알 수 없으면 빈 글."""
    moment = _kst(stamp)
    return "" if moment is None else moment.strftime("%Y-%m-%d")


# ---- 추천 후보 ----------------------------------------------------------------------------------------------------------------------
def interest_vm(value, hidden=False):
    """관심도 라벨 — 모르면(또는 못 가져온 지표로 표시했으면) `관심도 데이터 부족`. 영문 값은 글에 나가지 않는다."""
    key = value if (value in INTERESTS and not hidden) else "none"
    return {"key": key, "label": T["board_interest_" + key]}


def delta_vm(score, previous):
    """점수 변화량 — 이전 점수가 없으면(또는 점수를 알 수 없으면) **숨긴다**(None). 있으면 점수 링 부품과 같은 글(`▲ +4`·`▼ -4`·`― 변화 없음`)이다."""
    now, before = gauges.clean_score(score), gauges.clean_score(previous)
    if now is None or before is None:
        return None
    view = gauges.delta_view(now - before)
    return {"kind": view.kind, "text": view.text, "spoken": view.spoken, "color_key": view.color_key, "value": now - before}


def row_vm(row, rank, trend_hidden=False, channel=""):
    """추천 후보 한 줄 — 채널(A·B)·제목·점수(정수만)·구간·변화량·관심도·예시 꼬리표. 점수가 없으면 링 없이 `점수 계산 전`. 월 검색량·문서 수·내부 번호는 없다."""
    score = gauges.clean_score(row.score)
    band = gauges.score_band(score)
    delta = delta_vm(score, row.prev_score)
    interest = interest_vm(row.interest, trend_hidden)
    title = _shown(row.title, TITLE_LIMIT)
    sample = bool(row.sample)
    heard = T["board_score_none"] if score is None else gauges.score_spoken(score, None if delta is None else delta["value"])
    return {"rank": rank, "channel": channel, "title": title, "score": score, "score_text": T["board_score_none"] if score is None else str(score), "ring": score is not None,
            "band": band.key if band else None, "band_label": band.name if band else "", "delta": delta, "interest": interest,
            "sample": sample, "sample_tag": T["board_sample_tag"] if sample else "",
            "a11y": ", ".join(part for part in (title, heard, interest["label"], T["board_sample_tag"] if sample else "") if part)}


def _failure_vm(failure, title_key):
    """읽기 실패의 화면 모습 — 쉬운 문장(비밀 모양을 가린 것)과 진단용 코드 한 줄. 입력한 글·경로는 담기지 않는다."""
    message = _shown(getattr(failure, "user_message", "") or T["job_failed"], 200)
    code = _shown(getattr(failure, "code", "") or "UNKNOWN", 80)
    return {"title": T[title_key], "desc": message, "diag": f"{T['diag_code']}: {code}"}


def channel_vm(channel, trend_hidden=False):
    """채널 하나(A·B)의 추천 구역. 상태: `normal`(줄이 있다) · `empty`(정상 빈 상태 — 보관함이 아직 없거나 옛 구조인 때도 오류가 아니다) · `off`(후보 생성이 꺼져 있다) · `error`(그 구역만 못 읽었다)."""
    key = channel.key
    name = _shown(channel.name, NAME_LIMIT) or T["chip_" + key.lower()]
    rows = [row_vm(row, rank, trend_hidden, key) for rank, row in enumerate(islice(channel.rows, HOME_LIMIT), start=1)]      # 많아야 5개 — 많이 들어와도 앞의 다섯만 본다
    if channel.state == "failed":
        state = "error"
    elif channel.state == "unavailable":
        state = "empty"
    elif channel.enabled is False:
        state = "off"
    else:
        state = "empty" if not rows else "normal"
    desc = {"missing": T["board_rec_nostore"], "old": T["board_rec_oldstore"]}.get(channel.reason, T["board_rec_empty_desc"]) if channel.state == "unavailable" else T["board_rec_empty_desc"]
    skipped = channel.skipped if _count(channel.skipped) else 0
    return {"key": key, "name": name, "title": T["board_rec_title"].format(name=name), "enabled": channel.enabled, "enabled_text": "" if channel.enabled is None else T["board_on" if channel.enabled else "board_off"],
            "state": state, "count": len(rows), "count_text": T["board_count"].format(n=len(rows)), "rows": rows, "empty": {"title": T["board_rec_empty_title"], "desc": desc},
            "off": T["board_rec_off"], "error": _failure_vm(channel.failure, "board_rec_error_title") if state == "error" else None,
            "note": T["board_rec_skipped"].format(n=skipped) if skipped else ""}


# ---- 작성 중 초안·최근 발행 -----------------------------------------------------------------------------------------------------------
def draft_vm(row, rank):
    title = _shown(row.title, TITLE_LIMIT)
    stage = row.stage if row.stage in STAGES else ""
    label = T["board_stage_" + stage] if stage else ""
    when = time_text(row.updated)
    sample = bool(row.sample)
    return {"rank": rank, "title": title, "stage": stage, "stage_label": label, "time": when, "sample": sample, "sample_tag": T["board_sample_tag"] if sample else "",
            "a11y": ", ".join(part for part in (title, label, when, T["board_sample_tag"] if sample else "") if part)}


def recent_vm(row, rank):
    """최근 발행 한 줄 — 날짜는 발행한 때뿐이다(`updated_at` 으로 대신하지 않는다). 모르면 `발행일 확인 불가`."""
    title = _shown(row.title, TITLE_LIMIT)
    when = date_text(row.published)
    text = when or T["board_date_unknown"]
    sample = bool(row.sample)
    return {"rank": rank, "title": title, "date": when, "date_text": text, "known": bool(when), "sample": sample, "sample_tag": T["board_sample_tag"] if sample else "",
            "a11y": ", ".join(part for part in (title, text, T["board_sample_tag"] if sample else "") if part)}


def list_vm(read, build, titles, state=None):
    """글 구역 하나 — `state` 를 주면(읽기 전 상태) 줄 없이 그 상태만, 아니면 읽은 결과에서 `normal`·`empty`·`error` 를 정한다. 줄은 많아야 5개다."""
    title_key, empty_key, desc_key, error_key = titles
    if state is None:
        failed = read.state == "failed"
        rows = [] if failed else [build(row, rank) for rank, row in enumerate(islice(read.rows, HOME_LIMIT), start=1)]
        state = "error" if failed else ("normal" if rows else "empty")
        skipped = read.skipped if _count(read.skipped) else 0
        error = _failure_vm(read.failure, error_key) if failed else None
    else:
        rows, skipped, error = [], 0, None
    return {"title": T[title_key], "state": state, "rows": rows, "empty": {"title": T[empty_key], "desc": T[desc_key]}, "error": error,
            "note": T["board_posts_skipped"].format(n=skipped) if skipped else ""}


DRAFT_TEXTS = ("board_draft_title", "board_draft_empty_title", "board_draft_empty_desc", "board_draft_error_title")
RECENT_TEXTS = ("board_recent_title", "board_recent_empty_title", "board_recent_empty_desc", "board_recent_error_title")


# ---- KPI ----------------------------------------------------------------------------------------------------------------------------
def kpi_vm(key, label_key, value, state):
    """KPI 하나. 숫자 칸(`value`)이 있으면 `N개`, 없으면 0 이 아니라 `연결 전`(그 값을 읽는 곳이 아직 연결되지 않음)·`집계 전`(연결은 됐으나 아직 못 셌음) 글이다."""
    if state == "value" and _count(value):
        text, sub = f"{value}개", ""
    elif state == "before_connect":
        value, text, sub = None, T["board_before_connect"], T["board_kpi_connect_sub"]
    else:
        state, value, text, sub = "before_count", None, T["board_before_count"], T["sum_unavailable"]
    label = T[label_key]
    return {"key": key, "label": label, "value": value, "text": text, "state": state, "sub": sub, "a11y": f"{label} {text}"}


def _topics_kpi(board):
    """추천 주제 수 — 홈이 보이는 A·B 추천 줄의 합. 보관함이 아직 없으면 `연결 전`, 한 채널이라도 못 읽었으면 `집계 전`(일부만 센 수를 합계로 내지 않는다)."""
    by_key = {channel.key: channel for channel in board.channels}
    channels = [by_key.get(key) or _ABSENT[key] for key in HOME_CHANNELS]
    if any(channel.state == "failed" for channel in channels):
        return None, "before_count"
    if all(channel.state == "unavailable" for channel in channels):
        return None, "before_connect"
    return sum(len(tuple(islice(channel.rows, HOME_LIMIT))) for channel in channels if channel.state == "ok"), "value"


def kpi_vms(data, board):
    """KPI 넷(추천 주제·작성 완료·발행 완료·저장된 아이디어). 값마다 따로 상태를 가진다 — 홈 데이터가 아직 없으면 모두 `집계 전`, 새 구역을 읽지 않는 공급자(`board` 가 None)면 추천 주제만 `연결 전`."""
    if data is None:
        return [kpi_vm(key, label, None, "before_count") for key, label in KPIS]
    topics = _topics_kpi(board) if board is not None else (None, "before_connect")
    held = sum(1 for topic in data.topics if topic.status == "hold")
    values = {"topics": topics, "done": (data.done, "value"), "pub": (data.pub, "value"), "ideas": (held, "value")}
    return [kpi_vm(key, label, *values[key]) for key, label in KPIS]


# ---- 연결 요약 ----------------------------------------------------------------------------------------------------------------------
def connection_vm(conn_data, conn_state="", loading=False):
    """연결 상태 한 줄 요약 — **설정 화면이 이미 읽은 정보를 그대로 쓴다**(새로 읽지 않는다). 아직 읽지 않았으면 그렇게 말하고, 읽은 값이 있으면 설정 묶음 머리와 같은 칩 글(`준비 중 4 · 연결 확인 필요 2`)을 한 줄로 잇는다."""
    title = T["board_conn_title"]
    if conn_data is None:
        state, text, tone = ("loading", T["board_conn_loading"], "muted") if loading else ("error", T["board_conn_error"], "warning") if conn_state == "error" else ("before", T["board_conn_before"], "muted")
        return {"title": title, "state": state, "text": text, "tone": tone, "problem": False, "sample": False, "sample_tag": "", "a11y": f"{title}, {text}"}
    infos = [info for _group, items in sv.grouped(conn_data.purposes) for info in items]
    text = " · ".join(chip["text"] for chip in sv.chips_of(infos)) or T["board_conn_nothing"]
    found = {sv.effective_status(info) for info in infos}
    tone = "danger" if "auth_error" in found else "warning" if found & {"rate_limited", "needs_check"} else "ok" if "connected" in found else "muted"
    sample = bool(conn_data.sample)
    return {"title": title, "state": "ready", "text": text, "tone": tone, "problem": sv.has_problem(infos), "sample": sample, "sample_tag": T["board_sample_tag"] if sample else "",
            "a11y": ", ".join(part for part in (title, text, T["board_sample_tag"] if sample else "") if part)}


# ---- 홈의 새 구역 전부 ---------------------------------------------------------------------------------------------------------------
class _Absent:
    """공급자가 주지 않은 채널의 자리 — 정상 빈 상태로 보인다(읽는 쪽이 채널을 빠뜨려도 두 구역은 늘 있다)."""

    def __init__(self, key):
        self.key, self.name, self.enabled, self.state, self.reason, self.rows, self.skipped, self.failure = key, "", None, "ok", "", (), 0, None


_ABSENT = {key: _Absent(key) for key in HOME_CHANNELS}


def build_board_view(data, list_state, *, conn_data=None, conn_state="", conn_loading=False):
    """홈의 새 구역 뷰모델 — `state`: `ready`(값이 있다) · `loading`(홈 데이터를 읽는 중) · `unavailable`(홈 데이터가 없다 — 읽지 못했거나 아직 안 읽음) · `before_connect`(이 공급자는 새 구역을 읽지 않는다).
    읽기 전 상태에서도 구역(추천 둘·작성 중 초안·최근 발행)은 늘 같은 모양으로 있어 화면이 같은 틀로 그릴 수 있다."""
    board = None if data is None else data.board
    state = ("loading" if list_state == "loading" else "unavailable") if data is None else "before_connect" if board is None else "ready"
    trend_hidden = bool(data is not None and "trend" in data.partial)                           # 관심도를 못 가져왔다고 표시한 데이터는 값이 남아 있어도 보이지 않는다(옛 추세 칸과 같은 규칙)
    if state == "ready":
        by_key = {channel.key: channel for channel in board.channels}
        recommend = [channel_vm(by_key.get(key) or _ABSENT[key], trend_hidden) for key in HOME_CHANNELS]
        drafts, recent = list_vm(board.drafts, draft_vm, DRAFT_TEXTS), list_vm(board.recent, recent_vm, RECENT_TEXTS)
    else:
        recommend = [{**channel_vm(_ABSENT[key]), "state": state} for key in HOME_CHANNELS]
        drafts, recent = list_vm(None, draft_vm, DRAFT_TEXTS, state), list_vm(None, recent_vm, RECENT_TEXTS, state)
    return {"state": state, "sample": bool(board is not None and board.sample), "sample_tag": T["board_sample_tag"], "kpi": kpi_vms(data, board), "recommend": recommend,
            "drafts": drafts, "recent": recent, "connection": connection_vm(conn_data, conn_state, conn_loading)}
