"""한도 안전장치(`QuotaGuard`) — 한도가 일을 막지 않게 하는 구조(결정 D-30·D-31).

**기본 안전장치는 '절약'이다**: 캐시를 먼저 쓰고, 예산이 줄면 호출을 우선순위(`critical` > `selected_candidate` > `new_candidate` > `bulk_refresh`)대로 줄이고, 그래도 안 되면 `Denied(degraded=True)` —
호출하는 쪽은 '데이터 없음'으로 계속한다(`degraded` 는 오류가 아니다. 키가 없는 것도 오류가 아니다). 예산의 마지막 10%는 `critical`(규정상 필수 호출·사용자가 고른 것의 후속 호출) 전용이다.
**한도 단위는 '키'가 아니라 '한도 묶음'(같은 앱·프로젝트)** 이다 — 같은 묶음의 다른 키로 넘어가도 한도는 늘지 않으므로 한도 오류 뒤에는 같은 묶음의 항목을 건너뛴다(5xx·시간 초과일 때만 같은 묶음도 허용).

호출 규약: `acquire(용도, calls=1, priority=…, request=…)` → `Lease` 또는 `Denied`, `report(lease, 결과, …)` → `ReportResult`. 한 번의 일(요청)은 `Request` 하나이고 그 안에서:
  · 전환할 수 있는 결과는 정확히 네 가지 — `rate_limited`(429·Retry-After)·`quota_exhausted`(기간 한도)·`transient_error`(500·502·503·504)·`timeout`. 그 밖의 `auth_failed`(401·403)·`bad_request`(400·422)·
    `policy_blocked`·`content_blocked`·`other_error` 는 **어떤 정책에서도 다른 항목으로 바꿔 시도하지 않고** 쉬운 한국어 조치 안내만 한다(`auth_failed` 는 그 항목을 '인증 정보 오류' 로 멈추고 재시도하지 않는다).
  · 전환 대상은 같은 용도·제공자 안의 `사용`·`예비` 항목(순서대로), 다음 제공자는 레지스트리의 `fallback_providers`(운영자가 켠 것만 — 기본은 비어 있다)뿐이다. 한 요청에서 같은 항목을 두 번 시도하지 않고(한 바퀴를 넘지 않는다),
    전부 안 되면 `Denied(degraded=True)`. 요청이 성공하면 다음 요청은 늘 첫 항목부터 시작한다(순환 상태를 저장하지 않는다). 용도마다 항목은 3개까지(`connections.MAX_ENTRIES_PER_PURPOSE`).
  · 제공자의 `rotation` 이 `never`(Unsplash)이면 어떤 결과에도 다른 항목을 시도하지 않는다. 일시 오류(5xx·시간 초과)는 같은 키로 잠깐(2초) 기다렸다 요청마다 **최대 1번**만 다시 한다.
  · `rate_limited` 는 `Retry-After`(정수 초·소수 초·HTTP-date — 읽을 수 없으면 1분 이상 쉰다)를 지키고 지수 백오프(5초에서 두 배씩, 상한 1시간 — 난수 없음)로 그 묶음을 쉬게 한다. 무한 재시도·연타는 없다. `quota_exhausted` 는 초기화 시각까지 막고 '이어 하기' 시각을 알린다.
  · 응답 머리글의 남은 횟수·한도(`X-Ratelimit-Remaining`·`X-Ratelimit-Limit`)가 있으면 로컬 계수보다 우선한다(머리글 보정 창만).
상태는 데이터 폴더의 `quota_state.json`(원자적 쓰기·구조 버전·잠금)에 있고 깨졌으면 보수적으로 '오늘 한도의 절반을 이미 썼다' 고 가정한다. 시계는 `ctx.now()`(주입)다 — 시험은 고정 시각을 쓴다.
막는 쪽은 실패 열림이 없다: 잠금을 못 잡거나 상태를 못 쓰면 호출을 허용하지 않고 `Denied` 로 물러난다.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..errors import AppError, render
from . import connections as cn
from .context import keep_bad_copy, write_json

SCHEMA = 1
FILE_NAME = "quota_state.json"
BULK, NEW, SELECTED, CRITICAL = "bulk_refresh", "new_candidate", "selected_candidate", "critical"
PRIORITIES = (BULK, NEW, SELECTED, CRITICAL)
FLOOR_PERCENT = {BULK: 30, NEW: 20, SELECTED: 10, CRITICAL: 0}      # 이 호출을 하고도 남겨 둬야 하는 예산의 비율 — 마지막 10% 는 critical 전용
RESERVE_PERCENT = 10
OK, RATE_LIMITED, QUOTA_EXHAUSTED, TRANSIENT, TIMEOUT = "ok", "rate_limited", "quota_exhausted", "transient_error", "timeout"
AUTH_FAILED, BAD_REQUEST, POLICY_BLOCKED, CONTENT_BLOCKED, OTHER_ERROR = "auth_failed", "bad_request", "policy_blocked", "content_blocked", "other_error"
OUTCOMES = (OK, RATE_LIMITED, QUOTA_EXHAUSTED, TRANSIENT, TIMEOUT, AUTH_FAILED, BAD_REQUEST, POLICY_BLOCKED, CONTENT_BLOCKED, OTHER_ERROR)
SWITCH_KINDS = frozenset({RATE_LIMITED, QUOTA_EXHAUSTED, TRANSIENT, TIMEOUT})          # 다른 항목으로 넘어갈 수 있는 결과는 이 네 가지뿐
LIMIT_KINDS = frozenset({RATE_LIMITED, QUOTA_EXHAUSTED})
ADVICE_CODE = {RATE_LIMITED: "API_RATE_LIMITED", QUOTA_EXHAUSTED: "API_RATE_LIMITED", TRANSIENT: "API_SERVER_ERROR", TIMEOUT: "NETWORK_TIMEOUT", AUTH_FAILED: "KEY_AUTH_FAILED",
               BAD_REQUEST: "REQUEST_INVALID", POLICY_BLOCKED: "REQUEST_BLOCKED", CONTENT_BLOCKED: "REQUEST_BLOCKED", OTHER_ERROR: "UNEXPECTED_ERROR"}
RETRY_BASE_SECONDS = 5
RETRY_CAP_SECONDS = 3600
RETRY_UNREADABLE_SECONDS = 60          # Retry-After 가 있는데 읽을 수 없으면 적어도 이만큼은 쉰다(0 으로 보고 바로 다시 두드리지 않는다)
MAX_RETRY_TEXT = 64                    # 읽는 Retry-After 글의 최대 길이(정상 값은 40자 안쪽 — 긴 글은 읽지 않고 '읽을 수 없음'으로 본다)
MAX_BLOCK = timedelta(hours=48)
SAME_KEY_RETRY_WAIT = 2
MAX_CALLS = 1000
MAX_LOG = 30
LOCK_WAIT = 5.0
LIMIT_VALID = timedelta(hours=24)
ACT_DONE, ACT_NEXT, ACT_RETRY, ACT_STOP = "done", "try_next", "retry_same", "stop"
_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_MINUTE = "%Y-%m-%dT%H:%M"
_MINUTE_KEY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
KST = timezone(timedelta(hours=9), "KST")


def _stamp(moment):
    return moment.astimezone(timezone.utc).strftime(_STAMP)


def _parse(text):
    return datetime.strptime(text, _STAMP).replace(tzinfo=timezone.utc)


def _minute_key(moment):
    return moment.astimezone(timezone.utc).strftime(_MINUTE)


def _minute_start(key):
    return datetime.strptime(key, _MINUTE).replace(tzinfo=timezone.utc)


def _korean_date(moment):
    """'11월 05일' 꼴. `strftime` 에 한글 서식을 넘기지 않는다 — 윈도 파이썬 3.10 은 서식 글자를 PC 의 로캘 인코딩(영문 윈도는 cp1252)으로 바꾸는데 한글을 못 담아 `UnicodeEncodeError` 로 깨진다(R-091 검사의 윈도·3.10 칸에서 실제로 났다)."""
    return f"{moment.month:02d}월 {moment.day:02d}일"


# ---- 결과 모양 ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Request:
    """한 번의 일 — 그 안에서 시도한 항목을 기억해 한 바퀴를 넘지 않는다(저장하지 않는다: 다음 일은 늘 첫 항목부터)."""
    purpose: str
    priority: str
    tried: list = field(default_factory=list)
    last_kind: str = ""
    closed: bool = False
    retried: bool = False
    pending_retry: str = ""
    failed_bucket: str = ""


@dataclass(frozen=True)
class Lease:
    purpose: str
    entry_id: str
    ref: str
    name: str
    provider: str
    bucket: str
    calls: int
    priority: str
    at: datetime
    notice: str
    switched: bool
    request: object

    @property
    def tried(self):
        return tuple(self.request.tried)


@dataclass(frozen=True)
class Denied:
    purpose: str
    code: str                       # no_key · auth_failed · saving_mode · exhausted · blocked · busy · closed · no_more_keys
    reason: str                     # 쉬운 한국어
    retry_at: object = None         # 다시 해 볼 수 있는 시각(UTC) 또는 None
    degraded: bool = True           # 참이면 호출하는 쪽은 '데이터 없음'(또는 저장해 둔 값)으로 계속한다 — 오류가 아니다
    use_cache: bool = False         # 호출하는 쪽에 저장해 둔 조회 결과가 있으면 그것을 쓰라는 뜻
    resume_text: str = ""


@dataclass(frozen=True)
class ReportResult:
    action: str                     # done · try_next · retry_same · stop
    advice: str                     # 쉬운 한국어 조치 안내('' 일 수 있다)
    wait_seconds: int = 0
    blocked_until: object = None
    notice: str = ""


# ---- 상태 파일 -----------------------------------------------------------------------------------------------------------------------
def _fresh():
    return {"schema": SCHEMA, "buckets": {}, "failovers": []}


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10 ** 9


def _is_stamp(value):
    if value == "":
        return True
    try:
        _parse(value)
    except (TypeError, ValueError):
        return False
    return True


def _valid_window(item):
    return (isinstance(item, dict) and set(item) == {"label", "used", "minutes", "limit", "limit_at"} and isinstance(item["label"], str) and _count(item["used"]) and _count(item["limit"])
            and isinstance(item["minutes"], dict) and all(isinstance(key, str) and _MINUTE_KEY.fullmatch(key) and _count(value) for key, value in item["minutes"].items())
            and isinstance(item["limit_at"], str) and _is_stamp(item["limit_at"]))


def _valid_state(raw):
    if not isinstance(raw, dict) or set(raw) != {"schema", "buckets", "failovers"} or raw["schema"] != SCHEMA or isinstance(raw["schema"], bool):
        return False
    if not isinstance(raw["buckets"], dict) or not isinstance(raw["failovers"], list) or len(raw["failovers"]) > 1000:
        return False
    for key, bucket in raw["buckets"].items():
        if (not isinstance(key, str) or not isinstance(bucket, dict) or set(bucket) != {"windows", "blocked_until", "block_kind", "backoff"} or not isinstance(bucket["windows"], dict)
                or not all(isinstance(name, str) and _valid_window(item) for name, item in bucket["windows"].items()) or not isinstance(bucket["blocked_until"], str)
                or not _is_stamp(bucket["blocked_until"]) or bucket["block_kind"] not in ("", RATE_LIMITED, QUOTA_EXHAUSTED) or not _count(bucket["backoff"])):
            return False
    return all(isinstance(item, dict) and set(item) == {"at", "purpose", "from", "to", "reason"} and all(isinstance(value, str) for value in item.values()) for item in raw["failovers"])


def bucket_key(entry):
    return f"{entry.purpose}/{entry.provider or '-'}/{entry.bucket}"


def _day_label(now, spec):
    return (now.astimezone(KST) - timedelta(hours=spec.reset_hour)).date().isoformat()


def _next_reset(now, spec):
    today = (now.astimezone(KST) - timedelta(hours=spec.reset_hour)).date()
    return (datetime(today.year, today.month, today.day, tzinfo=KST) + timedelta(days=1, hours=spec.reset_hour)).astimezone(timezone.utc)


def _window_state(bucket, window):
    return bucket["windows"].setdefault(window.name, {"label": "", "used": 0, "minutes": {}, "limit": 0, "limit_at": ""})


def _peek(bucket, window):
    """창의 기록(없으면 빈 기록) — 상태를 바꾸지 않고 본다."""
    if bucket is not None and window.name in bucket["windows"]:
        return bucket["windows"][window.name]
    return {"label": "", "used": 0, "minutes": {}, "limit": 0, "limit_at": ""}


def _limit_of(state, window, now):
    """창의 한도 — 응답 머리글로 알게 된 한도가 24시간 안이면 그것, 아니면 정해 둔 값."""
    if state["limit"] and state["limit_at"] and now - _parse(state["limit_at"]) <= LIMIT_VALID:
        return state["limit"]
    return window.limit


def _used_of(state, window, spec, now):
    if window.kind == "day":
        return state["used"] if state["label"] == _day_label(now, spec) else 0
    edge = now - timedelta(minutes=window.minutes)
    return sum(count for key, count in state["minutes"].items() if _minute_start(key) + timedelta(minutes=1) > edge)


def _record(state, window, spec, now, calls):
    if window.kind == "day":
        label = _day_label(now, spec)
        if state["label"] != label:
            state["label"], state["used"] = label, 0
        state["used"] += calls
        return
    key = _minute_key(now)
    state["minutes"][key] = state["minutes"].get(key, 0) + calls
    edge = now - timedelta(minutes=window.minutes)
    state["minutes"] = {name: count for name, count in state["minutes"].items() if _minute_start(name) + timedelta(minutes=1) > edge}


def _floor(limit, percent):
    return -(-limit * percent // 100)                      # 올림


def _frees_at(state, window, now, need):
    """창이 `need` 만큼 비는 시각(슬라이딩 창) — 오래된 분 묶음부터 빠진다."""
    freed = 0
    for key in sorted(state["minutes"]):
        freed += state["minutes"][key]
        if freed >= need:
            return _minute_start(key) + timedelta(minutes=1 + window.minutes)
    return now + timedelta(minutes=window.minutes)


def _headers_get(headers, name):
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name:
            return value
    return None


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MON = "(?P<mon>" + "|".join(_MONTHS) + ")"
_CLOCK = "(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
_WEEKDAY = "(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
_LONG_WEEKDAY = "(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
_HTTP_DATES = (
    re.compile(_WEEKDAY + ", (?P<day>[0-9]{2}) " + _MON + " (?P<year>[0-9]{4}) " + _CLOCK + " GMT"),                # Sun, 06 Nov 1994 08:49:37 GMT
    re.compile(_LONG_WEEKDAY + ", (?P<day>[0-9]{2})-" + _MON + "-(?P<year>[0-9]{2}) " + _CLOCK + " GMT"),            # Sunday, 06-Nov-94 08:49:37 GMT(두 자리 연도)
    re.compile(_WEEKDAY + " " + _MON + " (?P<day>[ 0-9][0-9]) " + _CLOCK + " (?P<year>[0-9]{4})"),                  # Sun Nov  6 08:49:37 1994
)
_RETRY_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def parse_http_date(text, now):
    """HTTP-date(세 가지 꼴 — 모두 GMT) → UTC 시각, 읽을 수 없으면 None. 로캘·`strptime` 을 쓰지 않는다(달 이름은 영어 약어뿐). 두 자리 연도는 지금보다 50년 넘게 앞이면 지난 세기로 본다(RFC 9110)."""
    for pattern in _HTTP_DATES:
        found = pattern.fullmatch(text)
        if found is None:
            continue
        year = int(found["year"])
        if len(found["year"]) == 2:
            year += 2000 if 2000 + year - now.astimezone(timezone.utc).year <= 50 else 1900
        try:
            return datetime(year, _MONTHS.index(found["mon"]) + 1, int(found["day"]), int(found["hour"]), int(found["minute"]), int(found["second"]), tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def retry_after_seconds(value, now):
    """`Retry-After` 값 → 쉬어야 할 초(올림한 정수, 0~48시간). 값이 아예 없으면(None) 0 — 백오프가 정한다.
    읽는 꼴: 정수 초·소수 초(`1.5` → 2초)·HTTP-date(지금과의 차이, 이미 지났으면 0). 값이 **있는데 읽을 수 없으면**(음수·`nan`·글자 섞임·너무 긴 글·달라진 날짜 꼴·글이 아닌 값 …)
    0 으로 보지 않고 `RETRY_UNREADABLE_SECONDS` 만큼은 쉰다(서버가 더 오래 쉬라 했을지도 모르니 안전한 쪽). 거대한 값은 48시간으로 자른다."""
    cap = int(MAX_BLOCK.total_seconds())
    if value is None:
        return 0
    if isinstance(value, bool):
        return RETRY_UNREADABLE_SECONDS
    if isinstance(value, (int, float)):
        if value != value or value < 0:
            return RETRY_UNREADABLE_SECONDS
        return cap if value >= cap else math.ceil(value)
    if not isinstance(value, str):
        return RETRY_UNREADABLE_SECONDS
    text = value.strip(" \t")
    if not text or len(text) > MAX_RETRY_TEXT:
        return RETRY_UNREADABLE_SECONDS
    if _RETRY_NUMBER.fullmatch(text):
        if len(text.partition(".")[0].lstrip("0")) > 9:           # 앞의 0 을 뺀 정수 부분이 10자리 이상이면 이미 48시간보다 길다 — 숫자로 바꾸지 않고 자른다
            return cap
        seconds = float(text)
        return cap if seconds >= cap else math.ceil(seconds)
    moment = parse_http_date(text, now)
    if moment is None:
        return RETRY_UNREADABLE_SECONDS
    seconds = (moment - now.astimezone(timezone.utc)).total_seconds()
    if seconds <= 0:
        return 0
    return cap if seconds >= cap else math.ceil(seconds)


def _int_header(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value.strip()):
        return int(value.strip())
    return None


class QuotaGuard:
    """한도 안전장치. `ctx` 에서 시계·데이터 폴더를 받고 연결 설정(`connections.json`)에서 항목을 읽는다."""

    def __init__(self, ctx, *, registry=cn.PURPOSES, lock_wait=LOCK_WAIT):
        self.ctx = ctx
        self.registry = registry
        self.lock_wait = lock_wait

    # ---- 읽기·쓰기 ------------------------------------------------------------------------------------------------------------------
    def _load(self, data, *, for_write):
        """(상태, 안내 글). 파일이 없으면 새 상태, 깨졌으면 보수적으로 오늘 한도의 절반을 썼다고 가정한 상태와 안내 문구(쓰는 중이면 깨진 파일은 `.bak` 으로 옮겨 둔다)."""
        path = self.ctx.workspace.quota_path
        if not path.exists():
            return _fresh(), ""
        raw, bad = None, False
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):             # 읽을 수 없거나 JSON 이 아니거나 너무 깊게 겹친 파일 — 아래에서 보수적으로 다룬다
            bad = True
        if not bad and _valid_state(raw):
            return raw, ""
        notice = render("QUOTA_STATE_INVALID", {"파일": FILE_NAME}).message
        if for_write:
            keep_bad_copy(path)
        return self._assume_half(data), notice

    def _assume_half(self, data):
        now = self.ctx.now()
        state = _fresh()
        for entry in data.entries:
            spec = self.registry[entry.purpose]
            provider = spec.provider(entry.provider)
            bucket = state["buckets"].setdefault(bucket_key(entry), {"windows": {}, "blocked_until": "", "block_kind": "", "backoff": 0})
            for window in provider.windows(data.policy(entry.purpose).tier):
                half = window.limit // 2
                if half:
                    _record(_window_state(bucket, window), window, spec, now, half)
        return state

    def _save(self, state):
        state["failovers"] = state["failovers"][-MAX_LOG:]
        write_json(self.ctx.workspace.quota_path, state)

    def _windows(self, entry, data):
        spec = self.registry[entry.purpose]
        provider = spec.provider(entry.provider)
        return spec, provider, provider.windows(data.policy(entry.purpose).tier)

    # ---- 항목 하나의 지금 상태 -------------------------------------------------------------------------------------------------------
    def _check(self, state, data, entry, calls, priority, now):
        """(종류, 다시 시도할 시각) — ok · blocked(한도 오류로 쉬는 중) · exhausted(예산을 다 씀) · saving(절약 모드) · auth(인증 실패로 멈춤)."""
        if entry.check_result == cn.CHECK_AUTH:
            return "auth", None
        bucket = state["buckets"].get(bucket_key(entry))
        if bucket and bucket["blocked_until"]:
            until = _parse(bucket["blocked_until"])
            if now < until:
                return "blocked", until
        spec, _provider, windows = self._windows(entry, data)
        verdict, retry = "ok", None
        for window in windows:
            held = _peek(bucket, window)
            limit = _limit_of(held, window, now)
            used = _used_of(held, window, spec, now)
            after = limit - used - calls
            if after < 0:
                when = _next_reset(now, spec) if window.kind == "day" else _frees_at(held, window, now, -after)
                if retry is None or when > retry:
                    retry = when
                verdict = "exhausted"
            elif after < _floor(limit, FLOOR_PERCENT[priority]) and verdict == "ok":
                verdict = "saving"
        return verdict, retry

    def _chain(self, data, purpose):
        """이 용도의 시도 순서 — `사용` 항목들(순서대로) 다음에 `예비` 항목들. 첫 `사용` 항목의 제공자와 레지스트리의 `fallback_providers` 만 쓴다. 첫 `사용` 항목이 없으면 비어 있다."""
        mine = data.of_purpose(purpose)
        active = [item for item in mine if item.state == cn.ACTIVE]
        if not active:
            return []
        allowed = {active[0].provider} | set(self.registry[purpose].fallback_providers)
        return [item for item in active + [item for item in mine if item.state == cn.STANDBY] if item.provider in allowed]

    def _may_switch(self, data, purpose, chain, failed):
        """한도·일시 오류 뒤 다른 항목으로 넘어가도 되나 — 정책이 전환이고, 실패한 항목의 제공자가 `limited` 이고, 바꿀 항목이 있을 때만."""
        if len(chain) < 2 or data.policy(purpose).on_limit != cn.ON_FAILOVER:
            return False
        provider = self.registry[purpose].provider(failed.provider)
        return provider is not None and provider.rotation == cn.ROTATION_LIMITED

    def _target_ok(self, purpose, failed, candidate, kind):
        """실패한 항목에서 이 후보로 넘어가도 되나 — `never` 제공자로는 넘어가지 않고, 한도 오류 뒤에는 같은 한도 묶음으로 넘어가지 않는다(한도가 늘지 않는다)."""
        target = self.registry[purpose].provider(candidate.provider)
        if target is None or (target.rotation == cn.ROTATION_NEVER and candidate.provider != failed.provider):
            return False
        return not (kind in LIMIT_KINDS and candidate.bucket == failed.bucket and candidate.provider == failed.provider)

    # ---- 호출 ---------------------------------------------------------------------------------------------------------------------------
    def _guard_args(self, purpose, calls, priority):
        if purpose not in self.registry:
            raise ValueError("알 수 없는 용도")
        if isinstance(calls, bool) or not isinstance(calls, int) or not 1 <= calls <= MAX_CALLS:
            raise ValueError(f"calls 는 1~{MAX_CALLS} 의 정수여야 한다")
        if priority not in PRIORITIES:
            raise ValueError("알 수 없는 우선순위")

    def acquire(self, purpose, calls=1, *, priority=NEW, cached=False, request=None):
        """이번 호출의 몫을 잡는다 → `Lease`(어느 항목으로 부를지) 또는 `Denied`(부르지 않는다 — `degraded`·`use_cache`·`retry_at`). 호출하기 **전에** 사용량을 먼저 센다(동시에 부르는 다른 프로세스가 초과하지 못하게)."""
        self._guard_args(purpose, calls, priority)
        request = request if request is not None else Request(purpose, priority)
        if request.closed or request.purpose != purpose:
            return Denied(purpose, "closed", "이 일은 이미 끝났습니다 — 새 일로 다시 시작합니다", degraded=True)
        try:
            with cn.locked(self.ctx, "quota-state", wait=self.lock_wait):
                return self._acquire(purpose, calls, priority, cached, request)
        except AppError as error:                                   # 막는 쪽은 실패 열림이 없다 — 상태를 읽거나 쓰지 못하면 호출하지 않고(숨기지 않고 이유를 적어) 건너뛴다
            if error.code == "KEYS_BUSY":
                return Denied(purpose, "busy", "다른 창이 사용량을 기록하는 중이라 이번 호출은 건너뜁니다(한도를 지키려고 호출하지 않았습니다)", degraded=True, use_cache=bool(cached))
            return Denied(purpose, "unavailable", f"사용량 기록을 읽거나 쓰지 못해 이번 호출은 건너뜁니다(오류 코드 {error.code})", degraded=True, use_cache=bool(cached))

    def _acquire(self, purpose, calls, priority, cached, request):
        data = cn.load(self.ctx, self.registry)
        state, notice = self._load(data, for_write=True)
        now = self.ctx.now()
        chain = self._chain(data, purpose)
        if not chain:
            return Denied(purpose, "no_key", "연결된 키가 없어 이 보조 기능만 건너뜁니다(키가 없어도 핵심 기능은 그대로 됩니다)", degraded=True)
        first = chain[0]
        if request.pending_retry:                                   # 같은 키로 다시 해 보는 한 번(전환이 아니다)
            wanted = next((item for item in chain if item.entry_id == request.pending_retry), None)
            candidates, mode, failed = ([wanted] if wanted is not None else []), "start", None
            request.pending_retry = ""
        elif not request.tried:
            candidates, mode, failed = chain, "start", None
        else:                                                       # 앞 시도가 전환할 수 있는 결과로 실패했다 — 아직 안 해 본 항목들만
            failed = next((item for item in chain if item.entry_id == request.tried[-1]), None)
            candidates, mode = [item for item in chain if item.entry_id not in request.tried], "switch"
            if failed is None:
                return Denied(purpose, "no_more_keys", "바꿔 시도할 수 있는 키가 더 없어 이번에는 건너뜁니다", degraded=not cached, use_cache=bool(cached))
        reasons = []
        for index, candidate in enumerate(candidates):
            leading = mode == "start" and index == 0
            if mode == "start" and index > 0 and not (self._may_switch(data, purpose, chain, first) and self._target_ok(purpose, first, candidate, RATE_LIMITED)):
                continue                                            # 시작할 때 첫 항목이 쉬는 중이어도 전환이 허용되지 않으면 다른 항목을 쓰지 않는다
            if mode == "switch" and not (self._may_switch(data, purpose, chain, failed) and self._target_ok(purpose, failed, candidate, request.last_kind)):
                continue
            kind, retry = self._check(state, data, candidate, calls, priority, now)
            if kind == "auth":
                if leading:
                    advice = render("KEY_AUTH_FAILED")
                    return Denied(purpose, "auth_failed", f"{advice.message} {advice.action}", degraded=True)
                continue
            if kind == "saving":
                if leading:
                    return Denied(purpose, "saving_mode", "한도에 가까워 절약 모드입니다 — 저장해 둔 값이나 '데이터 없음' 으로 계속합니다", retry, degraded=not cached, use_cache=bool(cached),
                                  resume_text=self._resume_text(retry, now))
                continue
            if kind in ("blocked", "exhausted"):
                reasons.append((kind, retry))
                if leading and not self._may_switch(data, purpose, chain, candidate):
                    break
                continue
            return self._lease(state, data, purpose, candidate, first, calls, priority, request, now, notice)
        if reasons:
            retry = min((when for _kind, when in reasons if when is not None), default=None)
            exhausted = any(kind == "exhausted" for kind, _when in reasons)
            return Denied(purpose, "exhausted" if exhausted else "blocked", ("한도를 다 써서 " if exhausted else "한도에 걸려 ") + "지금은 호출하지 않습니다 — 저장해 둔 값이나 '데이터 없음' 으로 계속합니다", retry,
                          degraded=not cached, use_cache=bool(cached), resume_text=self._resume_text(retry, now))
        return Denied(purpose, "no_more_keys", "바꿔 시도할 수 있는 키가 더 없어 이번에는 건너뜁니다 — 저장해 둔 값이나 '데이터 없음' 으로 계속합니다", degraded=not cached, use_cache=bool(cached))

    def _resume_text(self, retry, now):
        if retry is None:
            return ""
        local = retry.astimezone(KST)
        same_day = local.date() == now.astimezone(KST).date()
        return f"{'오늘' if same_day else '내일' if (local.date() - now.astimezone(KST).date()).days == 1 else _korean_date(local)} {local.strftime('%H:%M')} 이후 자동 재개"

    def _lease(self, state, data, purpose, entry, first, calls, priority, request, now, notice):
        spec, _provider, windows = self._windows(entry, data)
        bucket = state["buckets"].setdefault(bucket_key(entry), {"windows": {}, "blocked_until": "", "block_kind": "", "backoff": 0})
        for window in windows:
            _record(_window_state(bucket, window), window, spec, now, calls)
        switched = entry.entry_id != first.entry_id
        note = ""
        if switched:
            before = next((item for item in data.entries if item.entry_id == (request.tried[-1] if request.tried else first.entry_id)), first)
            reason = request.last_kind or "blocked"
            note = f"다른 키로 바꿨습니다: '{before.name}' → '{entry.name}' (이유: {reason})"
            state["failovers"].append({"at": _stamp(now), "purpose": purpose, "from": before.name, "to": entry.name, "reason": reason})
        request.tried.append(entry.entry_id)
        self._save(state)
        return Lease(purpose, entry.entry_id, entry.ref, entry.name, entry.provider, entry.bucket, calls, priority, now, note, switched, request)

    def acquire_entry(self, entry, calls=1, priority=CRITICAL):
        """항목 하나를 콕 집어 잡는다(연결 시험용 — 다른 항목으로 바꾸지 않는다)."""
        self._guard_args(entry.purpose, calls, priority)
        request = Request(entry.purpose, priority)
        try:
            with cn.locked(self.ctx, "quota-state", wait=self.lock_wait):
                data = cn.load(self.ctx, self.registry)
                state, notice = self._load(data, for_write=True)
                now = self.ctx.now()
                kind, retry = self._check(state, data, entry, calls, priority, now)
                if kind != "ok":
                    return Denied(entry.purpose, "saving_mode" if kind == "saving" else kind, "지금은 이 키로 호출할 수 없습니다", retry, degraded=True, resume_text=self._resume_text(retry, now))
                return self._lease(state, data, entry.purpose, entry, entry, calls, priority, request, now, notice)
        except AppError as error:
            if error.code == "KEYS_BUSY":
                return Denied(entry.purpose, "busy", "다른 창이 사용량을 기록하는 중입니다", degraded=True)
            return Denied(entry.purpose, "unavailable", f"사용량 기록을 읽거나 쓰지 못해 건너뜁니다(오류 코드 {error.code})", degraded=True)

    # ---- 결과 알리기 ---------------------------------------------------------------------------------------------------------------------
    def report(self, lease, outcome, *, retry_after=None, reset_at=None, headers=None):
        """호출 결과를 알린다. 전환·재시도는 여기서 정해 `ReportResult.action` 으로 알려 준다: `done`(끝) · `try_next`(다음 항목으로 `acquire` 를 다시) · `retry_same`(`wait_seconds` 뒤 같은 항목으로 한 번) · `stop`(멈춤 — `advice` 대로)."""
        if outcome not in OUTCOMES:
            raise ValueError("알 수 없는 결과 종류")
        with cn.locked(self.ctx, "quota-state", wait=self.lock_wait):
            data = cn.load(self.ctx, self.registry)
            state, _notice = self._load(data, for_write=True)
            return self._report(state, data, lease, outcome, retry_after, reset_at, headers)

    def _report(self, state, data, lease, outcome, retry_after, reset_at, headers):
        now = self.ctx.now()
        request = lease.request
        entry = next((item for item in data.entries if item.entry_id == lease.entry_id), None)
        if entry is None:                                           # 그 사이 항목이 지워졌다 — 더 시도하지 않는다
            request.closed = True
            return ReportResult(ACT_STOP, "")
        spec, _provider, windows = self._windows(entry, data)
        bucket = state["buckets"].setdefault(bucket_key(entry), {"windows": {}, "blocked_until": "", "block_kind": "", "backoff": 0})
        self._sync_headers(bucket, windows, spec, now, headers)
        request.last_kind = outcome
        chain = self._chain(data, lease.purpose)
        blocked, wait, action = None, 0, ACT_STOP
        if outcome == OK:
            bucket["backoff"], bucket["blocked_until"], bucket["block_kind"] = 0, "", ""
            request.closed, action = True, ACT_DONE
        elif outcome == RATE_LIMITED:
            step = min(RETRY_BASE_SECONDS * 2 ** min(bucket["backoff"], 20), RETRY_CAP_SECONDS)
            asked = retry_after_seconds(retry_after if retry_after is not None else _headers_get(headers, "retry-after"), now)
            wait = int(min(max(asked, step), MAX_BLOCK.total_seconds()))
            blocked = now + timedelta(seconds=wait)
            bucket["blocked_until"], bucket["block_kind"], bucket["backoff"] = _stamp(blocked), RATE_LIMITED, min(bucket["backoff"] + 1, 20)
            action = ACT_NEXT if self._has_next(state, data, chain, entry, request, now) else ACT_STOP
        elif outcome == QUOTA_EXHAUSTED:
            blocked = self._exhaust_until(spec, windows, now, reset_at)
            bucket["blocked_until"], bucket["block_kind"] = _stamp(blocked), QUOTA_EXHAUSTED
            for window in windows:
                held = _window_state(bucket, window)
                limit = _limit_of(held, window, now)
                if _used_of(held, window, spec, now) < limit:
                    _record(held, window, spec, now, limit - _used_of(held, window, spec, now))
            action = ACT_NEXT if self._has_next(state, data, chain, entry, request, now) else ACT_STOP
        elif outcome in (TRANSIENT, TIMEOUT):
            if self._has_next(state, data, chain, entry, request, now):
                action = ACT_NEXT
            elif not request.retried:
                request.retried, request.pending_retry, action, wait = True, entry.entry_id, ACT_RETRY, SAME_KEY_RETRY_WAIT
        elif outcome == AUTH_FAILED:
            cn.mark_check(self.ctx, entry.entry_id, cn.CHECK_AUTH, registry=self.registry)
        if action in (ACT_DONE, ACT_STOP):
            request.closed = True
        elif action == ACT_NEXT and entry.entry_id not in request.tried:
            request.tried.append(entry.entry_id)
        self._save(state)
        advice = ""
        if outcome != OK:
            shown = render(ADVICE_CODE[outcome], {"재시도 가능 시각": self._retry_text(blocked)} if blocked else None)
            advice = f"{shown.message} {shown.action}"
        return ReportResult(action, advice, wait, blocked)

    def _exhaust_until(self, spec, windows, now, reset_at):
        if isinstance(reset_at, datetime) and reset_at.tzinfo is not None and now < reset_at <= now + MAX_BLOCK:
            return reset_at.astimezone(timezone.utc)
        for window in windows:
            if window.kind == "day":
                return _next_reset(now, spec)
        span = max((window.minutes for window in windows if window.kind == "sliding"), default=60)
        return now + timedelta(minutes=span)

    @staticmethod
    def _retry_text(moment):
        if not moment:
            return ""
        local = moment.astimezone(KST)
        return f"{_korean_date(local)} {local.strftime('%H:%M')}(한국 시간)"

    def _has_next(self, state, data, chain, failed, request, now):
        """이 일에서 바꿔 시도해 볼 항목이 남았나(아직 안 해 봤고, 넘어가도 되고, 지금 쓸 수 있는 것)."""
        if not self._may_switch(data, failed.purpose, chain, failed):
            return False
        tried = set(request.tried) | {failed.entry_id}
        for candidate in chain:
            if candidate.entry_id in tried or not self._target_ok(failed.purpose, failed, candidate, request.last_kind):
                continue
            kind, _retry = self._check(state, data, candidate, 1, request.priority, now)
            if kind == "ok":
                return True
        return False

    def _sync_headers(self, bucket, windows, spec, now, headers):
        remaining = _int_header(_headers_get(headers, "x-ratelimit-remaining"))
        limit = _int_header(_headers_get(headers, "x-ratelimit-limit"))
        if remaining is None or limit is None or not 0 < limit <= 10 ** 7 or remaining > limit:
            return                                                  # 믿을 수 없는 머리글은 쓰지 않는다
        for window in windows:
            if not window.header_sync:
                continue
            held = _window_state(bucket, window)
            used = limit - remaining
            if window.kind == "day":
                held["label"], held["used"] = _day_label(now, spec), used
            else:
                held["minutes"] = {_minute_key(now): used} if used else {}
            held["limit"], held["limit_at"] = limit, _stamp(now)

    # ---- 사용량 보기(읽기만) --------------------------------------------------------------------------------------------------------
    def usage(self, purpose=None):
        """용도별 사용량 — 읽기만 한다(파일을 만들거나 바꾸지 않는다). 상태 파일이 깨졌으면 보수적으로 절반을 쓴 것으로 보여 주고 안내를 붙인다."""
        data = cn.load(self.ctx, self.registry)
        state, notice = self._load(data, for_write=False)
        now = self.ctx.now()
        views = []
        for key in self.registry:
            if purpose is not None and key != purpose:
                continue
            spec = self.registry[key]
            if not spec.takes_keys:
                continue
            views.append(self._usage_of(state, data, spec, now, notice))
        return views

    def _usage_of(self, state, data, spec, now, notice):
        mine = data.of_purpose(spec.key)
        rows, saving, blocked, retry = [], False, False, None
        shown = set()
        for entry in mine:
            if bucket_key(entry) in shown:
                continue
            shown.add(bucket_key(entry))
            held_bucket = state["buckets"].get(bucket_key(entry))
            _spec, provider, windows = self._windows(entry, data)
            for window in windows:
                held = _peek(held_bucket, window)
                limit = _limit_of(held, window, now)
                used = _used_of(held, window, spec, now)
                near = limit - used <= _floor(limit, RESERVE_PERCENT)
                saving = saving or near
                rows.append(UsageRow(entry.name, provider.label or spec.label, window.name, used, limit, near, "하루" if window.kind == "day" else f"최근 {window.minutes}분"))
            if held_bucket and held_bucket["blocked_until"] and now < _parse(held_bucket["blocked_until"]):
                blocked = True
                until = _parse(held_bucket["blocked_until"])
                retry = until if retry is None or until < retry else retry
        switches = tuple(f"{self._stamp_text(item['at'])} '{item['from']}' → '{item['to']}' (이유: {item['reason']})" for item in state["failovers"] if item["purpose"] == spec.key)[-3:]
        return UsageView(spec.key, spec.label, tuple(rows), saving, blocked, retry, self._resume_text(retry, now) if retry else "", notice, len(mine), switches)

    @staticmethod
    def _stamp_text(text):
        try:
            return _parse(text).astimezone(KST).strftime("%m-%d %H:%M")
        except ValueError:
            return "시각 모름"

    def purpose_status(self, purpose, *, keystore=None):
        """용도의 상태 5종 — 연결 설정의 상태에 '요청 한도 도달'(지금 쉬는 중이거나 예산을 다 씀)을 덧붙인다."""
        data = cn.load(self.ctx, self.registry)
        status = cn.purpose_status(self.ctx, data, purpose, self.registry, keystore)
        first = cn.primary_entry(data, purpose)
        if first is None or status in (cn.AUTH_ERROR, cn.NOT_CONNECTED):
            return status
        state, _notice = self._load(data, for_write=False)
        kind, _retry = self._check(state, data, first, 1, CRITICAL, self.ctx.now())
        return cn.RATE_LIMITED if kind in ("blocked", "exhausted") else status


@dataclass(frozen=True)
class UsageRow:
    entry: str
    provider: str
    window: str
    used: int
    limit: int
    near_limit: bool
    span: str

    def to_dict(self):
        return {"entry": self.entry, "provider": self.provider, "window": self.window, "used": self.used, "limit": self.limit, "near_limit": self.near_limit, "span": self.span}


@dataclass(frozen=True)
class UsageView:
    purpose: str
    label: str
    rows: tuple
    saving_mode: bool
    blocked: bool
    resume_at: object
    resume_text: str
    notice: str
    entries: int
    switches: tuple = ()

    def to_dict(self):
        return {"purpose": self.purpose, "label": self.label, "rows": [row.to_dict() for row in self.rows], "saving_mode": self.saving_mode, "blocked": self.blocked,
                "resume_at": _stamp(self.resume_at) if self.resume_at else "", "resume_text": self.resume_text, "notice": self.notice, "entries": self.entries, "switches": list(self.switches)}


def classify_http(status, headers=None):
    """HTTP 상태 번호 → 결과 종류. 429 는 `rate_limited`, 500·502·503·504 는 `transient_error`, 401·403 은 `auth_failed`(**403 이어도 응답 머리글의 남은 횟수가 0 이면 `rate_limited`** — 한도 초과를 403 으로 알리는 서비스가 있다),
    400·422 는 `bad_request`, 그 밖은 `other_error`. 시간 초과는 상태 번호가 없으니 부르는 쪽이 `timeout` 으로 알린다."""
    if status == 429:
        return RATE_LIMITED
    if status in (500, 502, 503, 504):
        return TRANSIENT
    if status == 403 and _int_header(_headers_get(headers, "x-ratelimit-remaining")) == 0:
        return RATE_LIMITED
    if status in (401, 403):
        return AUTH_FAILED
    if status in (400, 422):
        return BAD_REQUEST
    if isinstance(status, int) and 200 <= status < 300:
        return OK
    return OTHER_ERROR
