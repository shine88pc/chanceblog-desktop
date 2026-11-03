"""주제 후보 다루기 — 명령줄 `candidates`(목록·보기·추가·CSV 가져오기·선택·보류·제외·되살리기·검토·지우기·글 연결)의 서비스 함수. 자료·규칙·저장은 `content/candidates.py`·`content/store.py`('a' 묶음)가 하고
여기서는 그것을 사람이 쓰는 흐름으로 잇기만 한다(후보를 모으는 일·키워드 기회도 계산·초안 문장 만들기는 이 모듈의 일이 아니다).

규칙:
  · 후보 번호는 긴 무작위 번호(uuid)라 사람이 쓰기 어렵다 — 화면에는 **순번**(만든 시각 순으로 1부터, 전체 목록 기준)과 **번호 앞 8자**를 함께 보이고, 순번(1~999)이나 번호의 **앞 4자 이상**(겹치지 않을 때)으로 고른다.
    겹치면 `CANDIDATE_AMBIGUOUS` 로 어느 후보들인지 알려 준다. 번호 전체는 `--json`·`--verbose` 에서만 보인다. 순번은 지우면 뒤가 당겨지므로(같은 순번이 다른 후보를 가리키게 된다)
    **지울 때는 번호 앞 8자 이상만** 받는다(`DELETE_PREFIX`) — 순번이나 짧은 앞부분과 `--yes` 를 함께 줘도 아무것도 지우지 않고 지울 명령(번호 앞 8자)을 알려 준다. 1000번 이상의 순번은 쓸 수 없다(번호 앞 8자로 고른다).
  · 보기만 하는 `list`·`show` 는 보관함을 **읽기 전용**으로 연다(`ctx.reading_only()`) — 보관함 파일이 없거나 옛 구조여도 파일을 만들지도 올리지도 않고 '아직 후보가 없습니다' 로 안내한다.
    쓰는 명령은 보관함을 열면서 옛 구조를 올린다(사본 `.v<판>.bak` 을 남긴다).
  · 상태를 옮기는 일은 `store.set_candidate_status`(읽고 바꾸고 쓰는 것이 한 트랜잭션 — 두 명령이 동시에 같은 후보를 바꿔도 서로의 변경을 잃지 않는다)로 하고 이동 표는 후보 자료가 지킨다.
    글 연결처럼 칸을 고치는 일은 불러온 판(`expected_revision`)에서 바뀐 것만 저장되고, 그 사이 다른 명령이 바꿨으면(`STORE_CONFLICT`) 최신 후보를 다시 읽어 최대 3번 다시 한다.
  · 지우기는 `--yes` 가 있어야 하고 없으면 서비스가 먼저 `CONFIRMATION_REQUIRED` 로 멈춘다(사용자가 보는 오류). 저장 계층의 `CANDIDATE_CONFIRM_REQUIRED` 는 이중 방어로만 남는다(여기서는 확인된 뒤에만 부른다).
  · '선택'은 블로그마다 기록하고, 같은 핵심 키워드를 같은 블로그용으로 그 블로그 프로필의 `topic_reuse_days`(프로필이 없으면 기본 90일) 안에 이미 골랐다면 경고만 한다(막지 않는다).
  · CSV 가져오기는 다시 가져와도 같은 후보가 겹치지 않는다(같은 핵심 키워드·같은 주제·같은 블로그가 이미 있으면 건너뜀). 잘못된 줄은 그 줄만 거절하고 나머지는 처리한다.
    '이미 있나 확인 → 저장'은 보관함의 한 쓰기 트랜잭션(`Store.add_candidates`) 안에서 한다 — 같은 파일을 두 프로세스가 동시에 가져와도 겹치지 않고, 가져오다 멈추면 아무것도 저장되지 않는다(다시 실행하면 된다).
  · 조회일은 오늘(UTC) 하루 뒤까지만 받는다(지역 시간대 차이) — 먼 미래의 날짜는 실수로 보고 거절한다.
"""
from __future__ import annotations

import re
import stat
import unicodedata
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..content import candidate_csv as csvmod
from ..content import candidates as cd
from ..content import status as st
from ..content.profiles import DEFAULT_TOPIC_REUSE_DAYS
from ..content.profiles import KEYS as NAVER_KEYS
from ..errors import AppError
from . import projects

MIN_PREFIX = 4                                       # 번호 앞부분으로 고를 때 최소 글자 수(글 번호와 같다)
DELETE_PREFIX = 8                                    # 지울 때 받는 번호 앞부분의 최소 글자 수 — 화면에 보이는 '번호 앞 8자'(`cd.short_id`). 순번(1~3자리)·4~7자 앞부분으로는 지우지 않는다
MAX_ORDINAL_DIGITS = 3                               # 순번은 1~999 — 네 글자 이상은 번호 앞부분으로 읽는다
RETRIES = 3                                          # 글 연결을 저장하다 다른 명령과 부딪쳤을 때 최신 후보를 다시 읽어 해 보는 횟수
_ORDINAL = re.compile(r"[1-9][0-9]{0,%d}" % (MAX_ORDINAL_DIGITS - 1))
_FULL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DIGITS = re.compile(r"[0-9]+")                      # 숫자로만 된 글(순번으로 읽히기 쉬운 것)
_DAY_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SHOWN_CONFLICTS = 8                                  # 겹치는 후보를 오류 세부에 이만큼까지 적는다
KST = timezone(timedelta(hours=9), "KST")                  # 화면에 보이는 시각과 '며칠 전' 은 한국 시간 기준이다(저장은 UTC 그대로)
DAYS_AHEAD = 1                                       # 조회일로 받는 가장 먼 날 — 오늘(UTC)보다 하루 뒤까지(지역 시간대 차이)
RETRYABLE = frozenset({"STORE_LOCKED", "DISK_FULL", "FILE_WRITE_FAILED"})        # 가져오는 도중 이 오류로 멈추면 아무것도 저장되지 않았으니 같은 명령을 다시 하면 된다


# ---- 번호 ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CandidateRow:
    """목록의 한 줄 — 순번과 후보."""
    ordinal: int
    candidate: cd.Candidate

    def to_dict(self):
        data = self.candidate.to_dict()
        data["ordinal"] = self.ordinal
        data["status_name"] = cd.STATUS_KO[self.candidate.status]
        return data


def numbered(candidates):
    """후보들 → 순번을 붙인 줄들. 순서는 만든 시각(같으면 번호) — 새 후보가 맨 뒤에 붙을 뿐 앞의 순번은 바뀌지 않는다(지우면 뒤의 순번이 하나씩 당겨진다)."""
    ordered = sorted(candidates, key=lambda item: (item.created_at, item.candidate_id))
    return [CandidateRow(position, item) for position, item in enumerate(ordered, start=1)]


def _not_found(what, detail=""):
    return AppError("CANDIDATE_NOT_FOUND", {"항목": what}, detail=detail)


def _short(text, limit=24):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _label(row):
    """후보를 가리키는 말 — `순번 3 주제(번호 1a2b3c4d)`. 오류 세부에서 어느 후보인지 알릴 때 쓴다(순번은 바뀔 수 있어 번호 앞 8자도 함께)."""
    return f"순번 {row.ordinal} {_short(row.candidate.topic)}(번호 {cd.short_id(row.candidate.candidate_id)})"


def resolve(rows, text):
    """순번(1~999)이나 번호 전체, 또는 번호의 앞 4자 이상(겹치지 않을 때) → 그 줄. 없으면 CANDIDATE_NOT_FOUND, 앞부분이 둘 이상과 맞으면 CANDIDATE_AMBIGUOUS(어느 후보들인지 세부에 적는다).
    숫자만 4~7자인데 맞는 번호가 없으면 1000번 이상의 순번을 친 것일 수 있어 '순번은 1~999 까지' 임을 알린다."""
    wanted = text.strip() if isinstance(text, str) else ""
    if not wanted:
        raise _not_found("(비어 있음)", "후보 번호를 적는다 — 목록의 순번이나 번호의 앞 4자 이상")
    if _ORDINAL.fullmatch(wanted):
        number = int(wanted)
        if number > len(rows):
            raise _not_found(f"순번 {number}", f"후보는 {len(rows)}개뿐이다 — `candidates list` 로 순번을 확인한다")
        return rows[number - 1]
    exact = [row for row in rows if row.candidate.candidate_id == wanted]
    if exact:
        return exact[0]
    if len(wanted) < MIN_PREFIX:
        raise _not_found(wanted, f"번호는 목록의 순번(1~{10 ** MAX_ORDINAL_DIGITS - 1})이거나 번호의 앞 {MIN_PREFIX}자 이상으로 적는다")
    lowered = wanted.casefold()
    found = [row for row in rows if row.candidate.candidate_id.casefold().startswith(lowered)]
    if not found:
        if _DIGITS.fullmatch(wanted) and len(wanted) < DELETE_PREFIX:
            raise _not_found(wanted, f"{10 ** MAX_ORDINAL_DIGITS}번 이상은 순번으로 고를 수 없습니다 — 번호 앞 {DELETE_PREFIX}자로 고르세요(`candidates list` 의 '번호' 에 보입니다)")
        raise _not_found(wanted)
    if len(found) > 1:
        shown = " · ".join(_label(row) for row in found[:SHOWN_CONFLICTS])
        more = f" 외 {len(found) - SHOWN_CONFLICTS}개" if len(found) > SHOWN_CONFLICTS else ""
        raise AppError("CANDIDATE_AMBIGUOUS", {"항목": wanted}, detail=f"겹치는 후보 {len(found)}개: {shown}{more}")
    return found[0]


# ---- 읽기 -------------------------------------------------------------------------------------------------------------------
def _read_all(ctx):
    """읽기 전용으로 연 보관함의 모든 후보를 순번대로 → (줄들, 보관함 상태). 상태: 'ready'(지금 구조) · 'old_structure'(옛 구조 — 후보 표가 아직 없다) · 'missing'(보관함 파일이 없다).
    파일을 만들지도 구조를 올리지도 않는다."""
    try:
        store = ctx.reading_only().store()
    except AppError as error:
        if error.code == "CONTENT_NOT_FOUND":                 # 읽기 전용 열기가 이 코드를 내는 것은 보관함 파일이 없거나 비어 있을 때뿐이다
            return [], "missing"
        raise
    with store:
        old = store.needs_migration
        return numbered(store.list_candidates()), "old_structure" if old else "ready"


def _check_filters(status, blog):
    if status is not None and (not isinstance(status, str) or status not in cd.STATUSES):
        raise AppError("CANDIDATE_INVALID", {"항목": cd.LABELS["status"], "이유": "다음 중 하나여야 합니다: " + ", ".join(cd.STATUS_KO[item] for item in cd.STATUSES)})
    if blog is not None and (not isinstance(blog, str) or blog not in st.PLATFORMS):
        raise AppError("CANDIDATE_INVALID", {"항목": "블로그", "이유": "다음 중 하나여야 합니다: " + ", ".join(st.PLATFORMS)})


@dataclass(frozen=True)
class ListResult:
    rows: tuple                     # CandidateRow — 거른 뒤의 것
    total: int                      # 거르기 전의 전체 후보 수
    status: object                  # 거른 상태(없으면 None)
    blog: object                    # 거른 블로그(없으면 None)
    store_state: str                # ready · old_structure · missing

    def to_dict(self):
        return {"candidates": [row.to_dict() for row in self.rows], "total": self.total, "shown": len(self.rows), "status": self.status, "blog": self.blog, "store": self.store_state}


def list_candidates(ctx, *, status=None, blog=None):
    """후보 목록(읽기 전용). 순번은 거르기 전 전체 목록 기준이다 — 거르면 건너뛴 번호가 생긴다."""
    _check_filters(status, blog)
    rows, state = _read_all(ctx)
    shown = [row for row in rows if (status is None or row.candidate.status == status) and (blog is None or blog in row.candidate.blogs)]
    return ListResult(tuple(shown), len(rows), status, blog, state)


@dataclass(frozen=True)
class ProjectBrief:
    project_id: str
    title: str
    statuses: tuple                 # ((플랫폼, 상태), …) — 아직 시작하지 않은 플랫폼은 뺀다
    error: str = ""                 # 글을 읽을 수 없을 때의 오류 코드

    def to_dict(self):
        return {"project_id": self.project_id, "title": self.title, "statuses": dict(self.statuses), "error": self.error}


@dataclass(frozen=True)
class ShowResult:
    row: CandidateRow
    project: object                 # ProjectBrief 또는 None(연결한 글이 없다)

    def to_dict(self):
        data = self.row.to_dict()
        data["project"] = None if self.project is None else self.project.to_dict()
        return {"candidate": data}


def _project_brief(store, project_id):
    try:
        project = store.load(project_id)
    except AppError as error:
        return ProjectBrief(project_id, "", (), error.code)
    return ProjectBrief(project_id, project.title, tuple((name, item.status) for name, item in project.variants.items() if item.status != st.NOT_STARTED))


def show_candidate(ctx, text):
    """후보 하나(읽기 전용) — 연결한 글이 있으면 그 글의 제목과 플랫폼별 상태까지."""
    try:
        store = ctx.reading_only().store()
    except AppError as error:
        if error.code != "CONTENT_NOT_FOUND":
            raise
        raise _not_found(_short(text), "아직 보관함이 없다 — 후보가 하나도 없다") from None
    with store:
        row = resolve(numbered(store.list_candidates()), text)
        link = row.candidate.project_id
        return ShowResult(row, None if link is None else _project_brief(store, link))


# ---- 같은 후보 찾기 ------------------------------------------------------------------------------------------------------------------
def _topic_key(topic):
    return " ".join(unicodedata.normalize("NFKC", topic).casefold().split())


def duplicate_key(candidate):
    """같은 후보인지 보는 열쇠 — 같은 핵심 키워드(`keyword_key`)와 같은 주제(띄어쓰기·대소문자 무시)."""
    return cd.keyword_key(candidate.keyword), _topic_key(candidate.topic)


def find_duplicate(rows, candidate):
    """이미 있는 후보 중 이 후보와 같은 것 — 핵심 키워드·주제가 같고 이 후보의 블로그가 모두 그 후보의 블로그 안에 있다(앞 순번이 먼저). 없으면 None."""
    key, blogs = duplicate_key(candidate), set(candidate.blogs)
    for row in rows:
        if duplicate_key(row.candidate) == key and blogs <= set(row.candidate.blogs):
            return row
    return None


def _moment(ctx, candidate):
    """바꾼 시각 — 지금. 다만 PC 시계가 뒤로 갔어도 고친 시각이 거꾸로 가지 않게 그 후보의 마지막 고친 시각보다 앞서지 않는다."""
    return max(ctx.stamp(), candidate.updated_at)


def _fresh_stamp(ctx, rows):
    """새 후보를 만들 시각 — 지금. 다만 이미 있는 후보 중 가장 늦게 만든 것과 같거나 그보다 앞서면(같은 초에 연달아 만들었거나 시계가 뒤로 갔다) 그 1초 뒤로 한다.
    순번이 (만든 시각, 번호) 순이라 만든 시각이 같으면 무작위 번호가 순서를 정해 버린다 — 이렇게 해 두면 연달아 만든 후보가 만든 순서대로 뒤에 붙고 이미 보인 순번이 바뀌지 않는다."""
    now = ctx.stamp()
    last = max((row.candidate.created_at for row in rows), default="")
    if now > last:
        return now
    return (cd.parse_stamp(last) + timedelta(seconds=1)).strftime(cd.STAMP_FORMAT)


# ---- 추가 ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AddResult:
    row: object                     # 추가한 후보의 CandidateRow(추가하지 않았으면 None)
    twin: object                    # 이미 있던 같은 후보의 CandidateRow(없으면 None)

    def to_dict(self):
        return {"added": self.row is not None, "candidate": None if self.row is None else self.row.to_dict(), "duplicate_of": None if self.twin is None else self.twin.to_dict()}


def _future_reason(ctx, day):
    """조회일(`YYYY-MM-DD`)이 받는 가장 먼 날(오늘(UTC)보다 `DAYS_AHEAD` 일 뒤)을 넘으면 그 이유 한 구절, 아니면 None.
    모양이 틀리거나 달력에 없는 값은 여기서 보지 않는다(후보 자료가 거절한다)."""
    if not isinstance(day, str) or not _DAY_SHAPE.fullmatch(day):
        return None
    try:
        asked = datetime.strptime(day, cd.DAY_FORMAT)
    except ValueError:
        return None
    latest = cd.parse_stamp(ctx.stamp()) + timedelta(days=DAYS_AHEAD)
    if asked.date() > latest.date():
        return f"오늘보다 뒤의 날짜입니다 — 지표를 조회한 날을 적습니다(받는 가장 먼 날은 {latest.strftime(cd.DAY_FORMAT)})"
    return None


def _check_day_not_future(ctx, day):
    reason = _future_reason(ctx, day)
    if reason is not None:
        raise AppError("CANDIDATE_INVALID", {"항목": cd.LABELS["data_date"], "이유": reason})


def add_candidate(ctx, *, topic, keyword, blogs, **fields):
    """후보 하나를 직접 더한다. 값 검사(CANDIDATE_INVALID)는 후보 자료가 한다(조회일은 오늘보다 하루 뒤까지). 같은 핵심 키워드·주제·블로그의 후보가 이미 있으면 더하지 않고 그 후보를 알려 준다.
    '이미 있나 확인 → 저장' 은 보관함의 한 쓰기 트랜잭션 안에서 한다(같은 후보를 동시에 더해도 겹치지 않는다)."""
    _check_day_not_future(ctx, fields.get("data_date"))
    checked = cd.Candidate.new(topic, keyword, tuple(blogs), now=ctx.stamp(), **fields)         # 값 검사 — 틀렸으면 보관함을 열기 전에 CANDIDATE_INVALID
    outcome = {}

    def plan(existing):
        rows = numbered(existing)
        twin = find_duplicate(rows, checked)
        if twin is not None:
            outcome["twin"] = twin
            return ()
        stamp = _fresh_stamp(ctx, rows)
        outcome["rows"], outcome["candidate"] = rows, replace(checked, created_at=stamp, updated_at=stamp)
        return (outcome["candidate"],)

    with ctx.store() as store:
        store.add_candidates(plan)
    if "twin" in outcome:
        return AddResult(None, outcome["twin"])
    candidate = outcome["candidate"]
    after = numbered([row.candidate for row in outcome["rows"]] + [candidate])
    return AddResult(next(row for row in after if row.candidate.candidate_id == candidate.candidate_id), None)


# ---- 상태 옮기기 -----------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ReuseWarning:
    """같은 핵심 키워드를 같은 블로그용으로 기준 일수 안에 이미 고른 후보가 있다는 경고."""
    blog: str
    days: int                       # 그 블로그 프로필의 같은 주제 재사용 기준(일)
    other: CandidateRow
    picked_at: str
    days_ago: int

    def to_dict(self):
        return {"blog": self.blog, "reuse_days": self.days, "other_ordinal": self.other.ordinal, "other_topic": self.other.candidate.topic, "picked_at": self.picked_at, "days_ago": self.days_ago}


@dataclass(frozen=True)
class MoveResult:
    row: CandidateRow
    before: str                     # 옮기기 전의 상태
    blog: object = None             # 선택할 때만 — 고른 블로그
    warnings: tuple = ()            # 선택할 때만 — ReuseWarning
    outside: bool = False           # 선택할 때만 — 이 후보의 추천 대상 블로그가 아닌 블로그를 골랐다
    again: bool = False             # 선택할 때만 — 이미 '선택됨' 이던 후보에 블로그를 더 골랐다

    def to_dict(self):
        return {"candidate": self.row.to_dict(), "before": self.before, "blog": self.blog, "warnings": [item.to_dict() for item in self.warnings], "outside_recommended_blogs": self.outside, "again": self.again}


def _reuse_days(ctx, blog):
    """그 블로그의 같은 주제 재사용 기준(일) — 네이버 프로필이 있으면 그 값, 없으면(다른 블로그·프로필 미설정) 기본값."""
    if blog in NAVER_KEYS:
        try:
            return ctx.settings.naver_profile(blog).topic_reuse_days
        except AppError as error:
            if error.code != "NAVER_PROFILE_MISSING":
                raise
    return DEFAULT_TOPIC_REUSE_DAYS


def kst(stamp):
    """저장된 시각(UTC, `2026-11-02T03:00:00Z`) → 한국 시간의 시각."""
    return cd.parse_stamp(stamp).replace(tzinfo=timezone.utc).astimezone(KST)


def _day_gap(now, earlier):
    """두 시각이 한국 시간의 달력으로 며칠 떨어졌나(어젯밤에 고른 것을 오늘 아침에 보면 1일 전). 시계가 거꾸로 가도 0 아래로 내려가지 않는다."""
    return max((kst(now).date() - kst(earlier).date()).days, 0)


def select_candidate(ctx, text, blog):
    """후보를 그 블로그용으로 고른다(상태 '선택됨' + 그 블로그의 선택 기록). 같은 핵심 키워드를 같은 블로그용으로 기준 일수 안에 이미 고른 후보가 있으면 경고를 함께 돌려주되 막지 않는다."""
    if not isinstance(blog, str) or blog not in st.PLATFORMS:
        raise AppError("CANDIDATE_INVALID", {"항목": "블로그", "이유": "다음 중 하나여야 합니다: " + ", ".join(st.PLATFORMS)})
    with ctx.store() as store:
        rows = numbered(store.list_candidates())
        row = resolve(rows, text)
        days = _reuse_days(ctx, blog)
        now = ctx.stamp()
        earlier = store.recent_selections(row.candidate.keyword, blog, days, now=now, exclude=row.candidate.candidate_id)
        moved = store.set_candidate_status(row.candidate.candidate_id, cd.SELECTED, blog=blog, now=_moment(ctx, row.candidate))
        fresh = {item.candidate.candidate_id: item for item in numbered(store.list_candidates())}      # 그 사이 다른 명령이 후보를 더하거나 지웠어도 순번이 맞도록 고른 뒤의 목록으로 매긴다
    warnings = []
    for other in earlier:
        shown = fresh.get(other.candidate_id)
        if shown is None:                                      # 확인한 뒤 지워졌다 — 더는 이전에 고른 후보가 아니다
            continue
        picked = other.selected_time(blog) or other.updated_at
        warnings.append(ReuseWarning(blog, days, shown, picked, _day_gap(now, picked)))
    mine = fresh.get(moved.candidate_id)
    return MoveResult(CandidateRow(row.ordinal if mine is None else mine.ordinal, moved), row.candidate.status, blog, tuple(warnings), blog not in row.candidate.blogs, row.candidate.status == cd.SELECTED)


def move_candidate(ctx, text, status):
    """후보를 보류(`HOLD`)·제외(`REJECTED`)·검토 중(`REVIEW`)으로 옮긴다. 이동 표에 없으면 CANDIDATE_TRANSITION_INVALID(저장된 것은 그대로)."""
    if status not in (cd.HOLD, cd.REJECTED, cd.REVIEW):
        raise AppError("CANDIDATE_INVALID", {"항목": cd.LABELS["status"], "이유": "여기서는 보류·제외·검토 중으로만 옮깁니다(고르려면 select)"})
    with ctx.store() as store:
        row = resolve(numbered(store.list_candidates()), text)
        moved = store.set_candidate_status(row.candidate.candidate_id, status, now=_moment(ctx, row.candidate))
    return MoveResult(CandidateRow(row.ordinal, moved), row.candidate.status)


def restore_candidate(ctx, text):
    """제외한 후보를 검토 중으로 되살린다 — 제외한 후보만(다른 상태의 후보는 CANDIDATE_TRANSITION_INVALID)."""
    with ctx.store() as store:
        row = resolve(numbered(store.list_candidates()), text)
        if row.candidate.status != cd.REJECTED:
            raise AppError("CANDIDATE_TRANSITION_INVALID", {"현재 상태": cd.STATUS_KO[row.candidate.status], "요청 상태": "되살리기(제외한 후보만 되살립니다)"})
        moved = store.set_candidate_status(row.candidate.candidate_id, cd.REVIEW, now=_moment(ctx, row.candidate))
    return MoveResult(CandidateRow(row.ordinal, moved), row.candidate.status)


# ---- 지우기 ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DeleteResult:
    ordinal: object                 # 지운 후보의 순번(깨져서 순번을 모르면 None)
    topic: str
    candidate_id: str

    def to_dict(self):
        return {"deleted": self.candidate_id, "ordinal": self.ordinal, "topic": self.topic}


def _confirm_delete(what, number, confirmed):
    """확인(`confirmed is True`)이 없으면 아무것도 지우지 않고 CONFIRMATION_REQUIRED — 사용자가 보는 오류는 이것이다(저장 계층의 CANDIDATE_CONFIRM_REQUIRED 는 이중 방어).
    세부에 지울 정확한 명령(번호 앞 8자)을 적는다 — 순번은 지울 때마다 뒤가 당겨져 같은 명령을 되풀이하면 다른 후보가 지워질 수 있어 순번으로는 지우지 않는다."""
    if confirmed is not True:
        raise AppError("CONFIRMATION_REQUIRED", {"항목": what},
                       detail=f"지우면 되돌릴 수 없습니다 — 나중에 다시 볼 후보면 지우지 말고 `candidates reject` 로 제외해 둡니다. 이 후보가 맞으면 번호 앞 {DELETE_PREFIX}자로 지웁니다: "
                              f"`candidates delete {number} --yes` (순번은 지울 때마다 당겨지므로 순번으로는 지우지 않습니다)")


def _delete_corrupt(store, text, blocked, confirmed):
    """깨진 후보 하나가 목록을 막고 있을 때(CANDIDATE_CORRUPT) — 오류에 나온 번호 앞 8자(또는 더 긴 앞부분·번호 전체)를 적은 경우에만 그 후보를 지운다(자료를 읽을 수 없으니 순번은 없다).
    그 밖에는 원래 오류를 그대로 낸다."""
    wanted = text.strip() if isinstance(text, str) else ""
    if blocked.code != "CANDIDATE_CORRUPT" or not _FULL_ID.fullmatch(wanted) or len(wanted) < DELETE_PREFIX:
        raise blocked
    lowered = wanted.casefold()
    found = [item for item in store.candidate_ids() if item.casefold().startswith(lowered)]
    if not found:                                                    # 맞는 번호가 없다 — 목록이 막힌 이유(깨진 후보)를 다시 알린다
        raise blocked
    if len(found) > 1:
        raise AppError("CANDIDATE_AMBIGUOUS", {"항목": wanted}, detail=f"겹치는 후보 {len(found)}개: " + " · ".join(f"번호 {item[:12]}" for item in found[:SHOWN_CONFLICTS]) + " — 더 긴 번호를 적습니다")
    target = found[0]
    number = cd.short_id(target)
    _confirm_delete(f"깨진 후보 지우기 — 번호 {number}(목록이 깨져 있어 주제를 읽지 못했습니다)", number, confirmed)
    store.delete_candidate(target, confirm=True)
    return DeleteResult(None, "", target)


def _named_by_number(row, text):
    """번호 앞 8자 이상(또는 짧은 번호 전체)으로 정한 것인가 — 순번이나 짧은 앞부분이 아니라 바뀌지 않는 번호여야 한다."""
    wanted = text.strip().casefold()
    return len(wanted) >= DELETE_PREFIX or wanted == row.candidate.candidate_id.casefold()


def delete_candidate(ctx, text, *, confirmed):
    """후보를 지운다(되돌릴 수 없다). `confirmed` 가 `True` 가 아니면 아무것도 지우지 않고 CONFIRMATION_REQUIRED(어느 후보인지, 지울 명령은 무엇인지 보인다). 연결한 글은 남는다.
    **순번이나 짧은 앞부분으로는 지우지 않는다**(`CANDIDATE_DELETE_NEEDS_NUMBER`) — 순번은 지울 때마다 뒤가 당겨져 같은 명령을 되풀이하면 다른 후보가 지워진다. 번호 앞 8자 이상으로만 지운다.
    깨진 후보 하나가 목록을 막고 있으면(CANDIDATE_CORRUPT) 오류에 나온 번호 앞 8자로 그 후보만 지울 수 있다."""
    with ctx.store() as store:
        try:
            row = resolve(numbered(store.list_candidates()), text)
        except AppError as blocked:
            return _delete_corrupt(store, text, blocked, confirmed)
        candidate = row.candidate
        number = cd.short_id(candidate.candidate_id)
        what = f"후보 지우기 — {_short(candidate.topic, 60)} (순번 {row.ordinal}, 번호 {number}, {cd.STATUS_KO[candidate.status]})"
        _confirm_delete(what, number, confirmed)
        if not _named_by_number(row, text):
            raise AppError("CANDIDATE_DELETE_NEEDS_NUMBER", {"항목": what},
                           detail=f"아무것도 지우지 않았습니다 — 순번은 지울 때마다 뒤가 당겨져 같은 명령을 되풀이하면 다른 후보가 지워질 수 있습니다. 이 후보를 지우려면: `candidates delete {number} --yes`")
        store.delete_candidate(candidate.candidate_id, confirm=True)
    return DeleteResult(row.ordinal, candidate.topic, candidate.candidate_id)


# ---- 글 연결 --------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LinkResult:
    row: CandidateRow
    project: object                 # ProjectBrief(연결을 끊었으면 None)
    changed: bool
    previous: object                # 전에 연결돼 있던 글 번호(없었으면 None)

    def to_dict(self):
        return {"candidate": self.row.to_dict(), "project": None if self.project is None else self.project.to_dict(), "changed": self.changed, "previous_project_id": self.previous}


def _change(ctx, store, candidate_id, work):
    """후보의 칸을 고쳐 저장한다 — 불러온 판에서 바뀐 것만 저장되고, 그 사이 다른 명령이 바꿨으면(STORE_CONFLICT) 최신 후보를 다시 읽어 `RETRIES` 번까지 다시 한다. → (후보, 바뀌었는가, 고치기 전 후보)."""
    attempt = 0
    while True:
        current = store.load_candidate(candidate_id)
        changed = work(current)
        if changed == current:
            return current, False, current
        try:
            store.save_candidate(changed, expected_revision=current.revision)
        except AppError as error:
            attempt += 1
            if error.code != "STORE_CONFLICT" or attempt >= RETRIES:
                raise
            continue
        return changed, True, current


def link_candidate(ctx, text, project_text):
    """후보와 보관함의 글(원고)을 잇는다 — 글 번호는 전체 또는 앞 4자 이상. 없는 글이면 CONTENT_NOT_FOUND(연결하지 않는다). 이미 다른 글과 이어져 있으면 새 글로 바꾼다."""
    with ctx.store() as store:
        row = resolve(numbered(store.list_candidates()), text)
        project_id = projects.resolve_id(store, project_text)
        brief = _project_brief(store, project_id)
        moved, changed, before = _change(ctx, store, row.candidate.candidate_id, lambda current: current.edited(project_id=project_id, now=_moment(ctx, current)))
    return LinkResult(CandidateRow(row.ordinal, moved), brief, changed, before.project_id)


def unlink_candidate(ctx, text):
    """후보와 글의 연결을 끊는다(글은 그대로다). 연결돼 있지 않으면 바뀐 것이 없다."""
    with ctx.store() as store:
        row = resolve(numbered(store.list_candidates()), text)
        moved, changed, before = _change(ctx, store, row.candidate.candidate_id, lambda current: current.edited(project_id=None, now=_moment(ctx, current)))
    return LinkResult(CandidateRow(row.ordinal, moved), None, changed, before.project_id)


# ---- CSV 가져오기 ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LineNote:
    line: int                       # 파일의 줄 번호
    reason: str

    def to_dict(self):
        return {"line": self.line, "reason": self.reason}


@dataclass(frozen=True)
class ImportResult:
    file: str                       # 파일 이름(경로 없이)
    added: tuple                    # CandidateRow — 새로 들어간 후보(전체 목록 기준 순번)
    skipped: tuple                  # LineNote — 이미 있는 후보라 건너뛴 줄
    rejected: tuple                 # LineNote — 잘못이라 거절한 줄
    unknown_columns: tuple          # 알아듣지 못해 무시한 열 이름
    blank_lines: int                # 무시한 빈 줄 수
    rows: int                       # 읽은 자료 줄 수(빈 줄 제외)

    def summary(self):
        return f"{len(self.added)}개 추가·{len(self.skipped)}개 건너뜀·{len(self.rejected)}개 거절"

    def to_dict(self):
        return {"file": self.file, "summary": self.summary(), "rows": self.rows, "added": [row.to_dict() for row in self.added], "skipped": [item.to_dict() for item in self.skipped],
                "rejected": [item.to_dict() for item in self.rejected], "unknown_columns": list(self.unknown_columns), "blank_lines": self.blank_lines}


def _read_csv_bytes(path):
    """CSV 파일의 바이트. **보통 파일만** 읽는다 — `CON`·`NUL` 같은 장치 이름이나 폴더·파이프를 읽으면 끝없이 기다리거나 끝없이 읽을 수 있어 읽기 전에 거절한다."""
    try:
        target = Path(path)
        info = target.stat()
        if not stat.S_ISREG(info.st_mode):
            raise csvmod.csv_invalid("보통 파일이 아닙니다(폴더나 `CON`·`NUL` 같은 장치 이름은 읽지 않습니다) — CSV 파일의 경로를 적습니다")
        if info.st_size > csvmod.MAX_CSV_BYTES:                       # 거대한 파일을 통째로 메모리에 올리지 않는다
            raise csvmod.csv_invalid(f"파일이 너무 큽니다(최대 {csvmod.MAX_CSV_BYTES // (1024 * 1024)}MB)")
        return target.read_bytes()
    except OSError as error:
        raise csvmod.csv_invalid("파일을 읽을 수 없습니다(경로와 권한을 확인합니다)", detail=f"{type(error).__name__}: 파일을 읽을 수 없다") from None


def _invalid_reason(error):
    """CANDIDATE_INVALID → 줄 거절 사유 한 줄(`칸: 이유`)."""
    item, reason = error.slots.get("항목", ""), error.slots.get("이유", "")
    return f"{item}: {reason}" if item else error.rendered().message


def _span_hint(record):
    return f" (이 줄은 파일의 {record.span}줄에 걸쳐 있습니다 — 큰따옴표가 닫히지 않았는지 확인합니다)" if record.span > 1 else ""


def import_csv(ctx, path, *, blogs=(), data_date=None):
    """CSV 파일의 후보들을 가져온다. 파일 전체가 안 되면(크기·글자 모양·머리줄·줄 수) CANDIDATE_CSV_INVALID 로 아무것도 저장하지 않고 멈춘다.
    줄마다: 칸 값을 바꿀 수 없거나 후보 규칙(`Candidate`)에 어긋나면 그 줄만 거절하고(조회일이 오늘보다 하루 넘게 뒤인 것도), 이미 있는 후보(같은 핵심 키워드·주제·블로그)면 건너뛰고, 아니면 저장한다 — 그래서 다시 가져와도 겹치지 않는다.
    줄 검사는 보관함을 열기 전에 끝내고, '이미 있나 확인 → 저장' 은 보관함의 **한 쓰기 트랜잭션**(`Store.add_candidates`) 안에서 한꺼번에 한다 — 같은 파일을 두 프로세스가 동시에 가져와도 겹치지 않고, 가져오다 멈추면
    아무것도 저장되지 않는다(같은 명령을 다시 실행하면 된다).
    `blogs` 는 대상 블로그 칸이 없거나 빈 줄에 쓸 기본값, `data_date`(YYYY-MM-DD)는 조회일 칸이 없거나 빈 줄에 쓸 기본값이다."""
    try:
        day = None if data_date is None else csvmod.check_day(data_date)
    except csvmod.CsvCellError as error:
        raise AppError("CANDIDATE_INVALID", {"항목": error.item, "이유": error.reason}) from None
    _check_day_not_future(ctx, day)
    default_blogs = tuple(blogs)
    if any(blog not in st.PLATFORMS for blog in default_blogs):
        raise AppError("CANDIDATE_INVALID", {"항목": "블로그", "이유": "다음 중 하나여야 합니다: " + ", ".join(st.PLATFORMS)})
    table = csvmod.parse_table(csvmod.decode(_read_csv_bytes(path)), blogs_given=bool(default_blogs))
    if not table.records:                                            # 자료 줄이 하나도 없으면 보관함을 열지도 않는다(파일이 없으면 만들어지므로)
        return ImportResult(Path(path).name, (), (), (), table.unknown, table.blank, 0)
    ids = sorted(uuid.uuid4().hex for _ in table.records)           # 한 번에 만든 번호를 오름차순으로 나눠 준다 — 같은 시각에 만든 후보도 파일의 줄 순서대로 순번이 매겨진다
    now, checked, rejected = ctx.stamp(), [], []
    for position, record in enumerate(table.records):               # 1단계 — 줄마다 후보로 바꿔 본다(보관함은 아직 열지 않는다)
        try:
            fields = csvmod.row_fields(table, record, default_blogs=default_blogs, default_day=day)
            reason = _future_reason(ctx, fields.get("data_date"))
            if reason is not None:
                raise csvmod.CsvCellError(cd.LABELS["data_date"], reason)
            candidate = cd.Candidate.new(fields.pop("topic"), fields.pop("keyword"), fields.pop("blogs"), candidate_id=ids[position], now=now, **fields)
        except csvmod.CsvCellError as error:
            rejected.append(LineNote(record.line, str(error) + _span_hint(record)))
            continue
        except AppError as error:
            if error.code != "CANDIDATE_INVALID":
                raise
            rejected.append(LineNote(record.line, _invalid_reason(error) + _span_hint(record)))
            continue
        checked.append((record, candidate))
    outcome = {"skipped": [], "rows": []}

    def plan(existing_candidates):                                   # 2단계 — 쓰기 잠금 안에서: 이미 있는 후보와 견주어 건너뛸 것을 가리고 새 후보에 만든 시각을 붙인다
        existing = numbered(existing_candidates)
        stamp = _fresh_stamp(ctx, existing)                         # 이미 있는 후보보다 뒤에 붙는다
        index = {}
        for row in existing:
            index.setdefault(duplicate_key(row.candidate), []).append((f"순번 {row.ordinal}", set(row.candidate.blogs)))
        fresh, skipped = [], []
        for record, candidate in checked:
            key, blog_set = duplicate_key(candidate), set(candidate.blogs)
            twin = next((label for label, blogs_of in index.get(key, ()) if blog_set <= blogs_of), None)
            if twin is not None:
                skipped.append(LineNote(record.line, f"같은 핵심 키워드·주제·블로그의 후보가 이미 있습니다({twin})"))
                continue
            fresh.append(replace(candidate, created_at=stamp, updated_at=stamp))
            index.setdefault(key, []).append((f"이 파일의 줄 {record.line}", blog_set))
        outcome["skipped"], outcome["rows"] = skipped, existing
        return fresh

    with ctx.store() as store:
        try:
            added = store.add_candidates(plan)
        except AppError as error:
            if error.code in RETRYABLE:                              # 잠겼거나 쓰지 못했다 — 아무것도 저장되지 않았으니 같은 명령을 다시 하면 된다
                error.detail = (f"{error.detail} | " if error.detail else "") + "가져오기는 한꺼번에 저장하므로 아무것도 저장하지 않았습니다 — 같은 명령을 다시 실행하면 됩니다"
            raise
    final = {row.candidate.candidate_id: row for row in numbered([row.candidate for row in outcome["rows"]] + list(added))}
    return ImportResult(Path(path).name, tuple(final[item.candidate_id] for item in added), tuple(outcome["skipped"]), tuple(rejected), table.unknown, table.blank, len(table.records))


__all__ = [
    "AddResult", "CandidateRow", "DeleteResult", "ImportResult", "LineNote", "LinkResult", "ListResult", "MoveResult", "ProjectBrief", "ReuseWarning", "ShowResult", "add_candidate", "delete_candidate",
    "duplicate_key", "find_duplicate", "import_csv", "link_candidate", "list_candidates", "move_candidate", "numbered", "resolve", "restore_candidate", "select_candidate", "show_candidate",
    "unlink_candidate",
]
