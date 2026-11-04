"""한도 안전장치(`QuotaGuard`) — 한도가 일을 막지 않게 하는 구조(결정 D-30·D-31).

**기본 안전장치는 '절약'이다**: 캐시를 먼저 쓰고, 예산이 줄면 호출을 우선순위(`critical` > `selected_candidate` > `new_candidate` > `bulk_refresh`)대로 줄이고, 그래도 안 되면 `Denied(degraded=True)` —
호출하는 쪽은 '데이터 없음'으로 계속한다(`degraded` 는 오류가 아니다. 키가 없는 것도 오류가 아니다). 예산의 마지막 10%는 `critical`(규정상 필수 호출·사용자가 고른 것의 후속 호출) 전용이다.
**한도 단위는 '키'가 아니라 '한도 묶음'(같은 앱·프로젝트)** 이다 — 같은 묶음의 다른 키로 넘어가도 한도는 늘지 않으므로 한도 오류 뒤에는 같은 묶음의 항목을 건너뛴다(5xx·시간 초과일 때만 같은 묶음도 허용).

호출 규약: `acquire(용도, calls=1, priority=…, request=…)` → `Lease` 또는 `Denied`, `report(lease, 결과, …)` → `ReportResult`. 한 번의 일(요청)은 `Request` 하나이고 그 안에서:
  · 전환할 수 있는 결과는 정확히 네 가지 — `rate_limited`(429·Retry-After)·`quota_exhausted`(기간 한도)·`transient_error`(500·502·503·504)·`timeout`. 그 밖의 `auth_failed`(401·403)·`bad_request`(400·422)·
    `policy_blocked`·`content_blocked`·`other_error` 는 **어떤 정책에서도 다른 항목으로 바꿔 시도하지 않고** 쉬운 한국어 조치 안내만 한다(`auth_failed` 는 그 항목을 '인증 정보 오류' 로 멈추고 재시도하지 않는다).
  · 전환 대상은 같은 용도·제공자 안의 `사용`·`예비` 항목(순서대로), 다음 제공자는 레지스트리의 `fallback_providers`(운영자가 켠 것만 — 기본은 비어 있다)뿐이다. 한 요청에서 같은 항목을 두 번 시도하지 않고(한 바퀴를 넘지 않는다),
    전부 안 되면 `Denied(degraded=True)`. 요청이 성공하면 다음 요청은 늘 첫 항목부터 시작한다(순환 상태를 저장하지 않는다). 용도마다 항목은 3개까지(`connections.MAX_ENTRIES_PER_PURPOSE` — 키를 하나만 두는 용도는 `Purpose.max_entries`).
  · 제공자의 `rotation` 이 `never`(Unsplash)이면 어떤 결과에도 다른 항목을 시도하지 않는다. 일시 오류(5xx·시간 초과)는 같은 키로 잠깐(2초) 기다렸다 요청마다 **최대 1번**만 다시 한다.
  · `rate_limited` 는 `Retry-After`(정수 초·소수 초·HTTP-date — 읽을 수 없으면 1분 이상 쉰다)를 지키고 지수 백오프(5초에서 두 배씩, 상한 1시간 — 난수 없음)로 그 묶음을 쉬게 한다. 무한 재시도·연타는 없다. `quota_exhausted` 는 초기화 시각까지 막고 '이어 하기' 시각을 알린다.
  · 응답 머리글의 남은 횟수·한도(`X-Ratelimit-Remaining`·`X-Ratelimit-Limit`)가 있으면 로컬 계수보다 우선한다(머리글 보정 창만).
상태는 데이터 폴더의 `quota_state.json`(원자적 쓰기·구조 버전·잠금)에 있고 깨졌으면 보수적으로 '오늘 한도의 절반을 이미 썼다' 고 가정한다. 시계는 `ctx.now()`(주입)다 — 시험은 고정 시각을 쓴다.
막는 쪽은 실패 열림이 없다: 잠금을 못 잡거나 상태를 못 쓰면 호출을 허용하지 않고 `Denied` 로 물러난다.

**장부·Fail-Closed 제공자**(`Provider.ledger`·`fail_closed` — 지금은 NAVER API HUB 검색어 트렌드뿐, 결정 D-35): 이 제공자만 ① 창마다 시도(`used`)와 성공(`successes`)을 따로 센다(실패한 호출도 시도다 — 공식 사용량에 들어가는지 모른다)
② 월 창(한국 시간 달력 월)을 일 창과 **함께** 지킨다(먼저 닿는 쪽이 막는다) ③ 최근 200건의 호출 장부(`audit.ledger` — 비밀·응답 본문·요청 본문 없이 종류·시각·조건 해시·성공 여부·HTTP 상태·재시도·응답 사용·캐시 적중)를 남기고
④ 사용량을 확인할 수 없을 때 호출하지 않는다 — 상태 파일이 깨졌거나 읽을 수 없음·월 계수가 한도·과거 값·장부와 모순·시계가 마지막으로 본 시각보다 5분 넘게 되돌아감·인증 상태가 불명확 — '절반 썼다고 보고 계속' 이 아니다
⑤ 단계는 콘솔 월 한도 기준(70% 안내·80% 자동 새로고침 중지·90% 신규 호출 모두 중지). 다른 제공자의 동작과 상태 파일 모양은 그대로다(판 2 는 장부가 생긴 파일만).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from ..errors import AppError, render
from . import connections as cn
from .context import keep_bad_copy, write_json

SCHEMA = 1                             # 판 1 — 장부가 없는 파일(장부 제공자를 한 번도 부르지 않은 파일은 지금까지와 똑같다)
SCHEMA_LEDGER = 2                      # 판 2 — 장부(`audit`)가 있는 묶음이 하나라도 있는 파일. 판 1 은 그대로 읽는다(이전: 장부가 생긴 파일만 `_save` 가 판 2 로 올려 쓴다 — 내용은 옛 판의 위 집합이라 잃는 것이 없다)
SCHEMAS = (SCHEMA, SCHEMA_LEDGER)
MAX_LEDGER = 200                       # 호출 장부에 남기는 최근 기록 수
CLOCK_TOLERANCE = timedelta(minutes=5)  # 시계가 마지막으로 본 시각보다 이만큼까지 뒤로 간 것은 흔들림으로 본다(넘으면 '시계 이상' — 자동으로 풀지 않는다)
CONDITION_HEX = 12                     # 조건 해시로 남기는 앞부분 길이(16진수)
HOLD_STATE_LOST = "state_lost"         # 사용량 기록이 사라졌다가 새로 만들어진 묶음 — 확인 절차(`acknowledge`)가 있기 전에는 호출하지 않는다
MAX_KIND = 40
LOST_NOTICE = "사용량 기록 파일을 읽을 수 없어 사용량을 확인하지 못합니다 — 절반으로 가정하지 않고 새 조회를 멈춥니다(저장된 정보로 계속합니다)"      # Fail-Closed 제공자용 안내(다른 제공자는 `QUOTA_STATE_INVALID` 의 '절반 가정' 안내)
_ERROR_CODE_NOTE = re.compile(r"\s*\(오류 코드 [A-Za-z0-9_]+\)")      # 거절 문구 속 '(오류 코드 XXX)' — 고정 문구를 쓰는 제공자의 사유에서는 지운다
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


def _month_label(moment):
    """한국 시간 달력 월의 라벨 `YYYY-MM`(서식 글자를 쓰지 않는다 — 로캘에 기대지 않는다)."""
    local = moment.astimezone(KST)
    return f"{local.year:04d}-{local.month:02d}"


def _next_month_start(moment):
    """다음 달 1일 00:00(한국 시간) — UTC 로 돌려준다. 12월은 다음 해 1월."""
    local = moment.astimezone(KST)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(year, month, 1, tzinfo=KST).astimezone(timezone.utc)


_SECRET_FIELD_NAMES = frozenset({"client_" + "sec" + "ret", "client_id", "sec" + "ret", "key", "api_" + "key", "api" + "key", "to" + "ken", "authorization", "pass" + "word", "x_ncp_apigw_api_" + "key", "x_ncp_apigw_api_" + "key_id"})
# 위 목록은 '조건에 들어오면 거절할 칸 이름' 이다 — 이 모듈은 키를 다루지 않는다(서비스 코드에 키·토큰 낱말이 글자 그대로 있으면 안전 시험이 막으므로 조각을 이어 붙였다)


def _normalized(value, depth=0):
    """요청 조건을 해시하기 전의 정규화 — 글(유니코드 NFC·앞뒤 공백 제거)·숫자·참거짓·없음·목록·사전만 받고, 비밀 칸 이름이 든 사전은 거절한다(키가 장부 쪽으로 새지 않게)."""
    if depth > 8:
        raise ValueError("조건이 너무 깊다")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value).strip()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_normalized(item, depth + 1) for item in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("조건의 칸 이름은 글이어야 한다")
            if key.strip().casefold().replace("-", "_") in _SECRET_FIELD_NAMES:
                raise ValueError("조건에 비밀 칸 이름이 있다 — 키·인증 값은 장부에 가는 조건에 넣지 않는다")
            out[unicodedata.normalize("NFC", key).strip()] = _normalized(item, depth + 1)
        return out
    raise ValueError("조건에는 글·숫자·목록·사전만 쓸 수 있다")


def condition_hash(condition):
    """정규화한 요청 조건의 해시 앞부분(`CONDITION_HEX` 자). 조건이 없으면 ''. 이 모듈은 키 값을 받지 않으므로 값에서 키를 유도할 수 없다 — 같은 조건이 같은 해시가 되어 '같은 조회의 반복'만 알아볼 수 있다."""
    if condition is None:
        return ""
    text = json.dumps(_normalized(condition), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(("chanceblog-desktop:call:1\0" + text).encode("utf-8")).hexdigest()[:CONDITION_HEX]


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
    call_id: int = 0                # 장부 제공자의 호출 장부 번호(장부가 없는 제공자는 0)

    @property
    def tried(self):
        return tuple(self.request.tried)


@dataclass(frozen=True)
class Denied:
    purpose: str
    code: str                       # no_key · auth_failed · saving_mode · exhausted · blocked · busy · closed · no_more_keys · unavailable (Fail-Closed 제공자는 unverifiable · clock · auth_unclear 도)
    reason: str                     # 쉬운 한국어 — Fail-Closed 제공자는 고정 문구(`Provider.stop_text`)
    retry_at: object = None         # 다시 해 볼 수 있는 시각(UTC) 또는 None
    degraded: bool = True           # 참이면 호출하는 쪽은 '데이터 없음'(또는 저장해 둔 값)으로 계속한다 — 오류가 아니다
    use_cache: bool = False         # 호출하는 쪽에 저장해 둔 조회 결과가 있으면 그것을 쓰라는 뜻
    resume_text: str = ""
    cause: str = ""                 # 멈춘 사유(쉬운 한국어, 기술 오류 코드 없음) — 고정 문구를 쓰는 제공자만 채운다


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


_WINDOW_KEYS = frozenset({"label", "used", "minutes", "limit", "limit_at"})
_BUCKET_KEYS = frozenset({"windows", "blocked_until", "block_kind", "backoff"})
_AUDIT_KEYS = frozenset({"last_seen", "high_water", "last_success", "last_error", "hold", "next_id", "ledger"})
_LEDGER_KEYS = frozenset({"id", "kind", "started", "finished", "condition", "ok", "status", "outcome", "retries", "used_response", "cache_hit", "calls"})
_KIND_KEY = re.compile(r"[a-z0-9_]{0,%d}" % MAX_KIND)
_CONDITION_KEY = re.compile(r"[0-9a-f]{0,%d}" % CONDITION_HEX)
_MONTH_KEY = re.compile(r"(?:[0-9]{4}-[0-9]{2})?")


def _valid_window(item, *, ledger=False):
    """창 하나의 모양. 장부가 있는 묶음(`ledger`)의 창은 `successes`(성공 수 — 시도 수 `used` 를 넘지 못한다)가 더 있다."""
    keys = _WINDOW_KEYS | {"successes"} if ledger else _WINDOW_KEYS
    if not (isinstance(item, dict) and set(item) == keys and isinstance(item["label"], str) and _count(item["used"]) and _count(item["limit"])
            and isinstance(item["minutes"], dict) and all(isinstance(key, str) and _MINUTE_KEY.fullmatch(key) and _count(value) for key, value in item["minutes"].items())
            and isinstance(item["limit_at"], str) and _is_stamp(item["limit_at"])):
        return False
    return not ledger or (_count(item["successes"]) and item["successes"] <= item["used"])


def _valid_ledger_entry(item):
    return (isinstance(item, dict) and set(item) == _LEDGER_KEYS and _count(item["id"]) and isinstance(item["kind"], str) and _KIND_KEY.fullmatch(item["kind"])
            and isinstance(item["started"], str) and item["started"] != "" and _is_stamp(item["started"]) and isinstance(item["finished"], str) and _is_stamp(item["finished"])
            and isinstance(item["condition"], str) and _CONDITION_KEY.fullmatch(item["condition"]) and isinstance(item["ok"], bool) and _count(item["status"]) and item["status"] <= 599
            and isinstance(item["outcome"], str) and item["outcome"] in ("", *OUTCOMES) and _count(item["retries"]) and isinstance(item["used_response"], bool)
            and isinstance(item["cache_hit"], bool) and _count(item["calls"]))


def _valid_audit(audit):
    """장부 묶음의 꼬리표(`audit`) — 마지막으로 본 시각·월 최고 계수·마지막 성공/오류·확인이 필요한 멈춤·호출 장부."""
    if not isinstance(audit, dict) or set(audit) != _AUDIT_KEYS:
        return False
    water, error, ledger = audit["high_water"], audit["last_error"], audit["ledger"]
    return (isinstance(audit["last_seen"], str) and _is_stamp(audit["last_seen"]) and isinstance(audit["last_success"], str) and _is_stamp(audit["last_success"])
            and isinstance(water, dict) and set(water) == {"month", "attempts"} and isinstance(water["month"], str) and _MONTH_KEY.fullmatch(water["month"]) and _count(water["attempts"])
            and isinstance(error, dict) and set(error) == {"at", "outcome", "status"} and isinstance(error["at"], str) and _is_stamp(error["at"]) and isinstance(error["outcome"], str)
            and error["outcome"] in ("", *OUTCOMES) and _count(error["status"]) and error["status"] <= 599
            and audit["hold"] in ("", HOLD_STATE_LOST) and _count(audit["next_id"]) and isinstance(ledger, list) and len(ledger) <= MAX_LEDGER and all(_valid_ledger_entry(item) for item in ledger))


def _valid_bucket(bucket, schema):
    if not isinstance(bucket, dict) or not isinstance(bucket.get("windows"), dict):
        return False
    audited = schema == SCHEMA_LEDGER and "audit" in bucket
    if set(bucket) != (_BUCKET_KEYS | {"audit"} if audited else _BUCKET_KEYS):
        return False
    if audited and not _valid_audit(bucket["audit"]):
        return False
    return (all(isinstance(name, str) and _valid_window(item, ledger=audited) for name, item in bucket["windows"].items()) and isinstance(bucket["blocked_until"], str)
            and _is_stamp(bucket["blocked_until"]) and bucket["block_kind"] in ("", RATE_LIMITED, QUOTA_EXHAUSTED) and _count(bucket["backoff"]))


def _valid_state(raw):
    """판 1(장부 없음)과 판 2(장부 묶음이 있음) 둘 다 읽는다 — 판 1 은 `audit`·`successes` 칸이 있으면 모양이 틀린 것으로 본다(옛 프로그램이 쓴 파일에는 없다)."""
    if not isinstance(raw, dict) or set(raw) != {"schema", "buckets", "failovers"} or isinstance(raw["schema"], bool) or raw["schema"] not in SCHEMAS:
        return False
    if not isinstance(raw["buckets"], dict) or not isinstance(raw["failovers"], list) or len(raw["failovers"]) > 1000:
        return False
    for key, bucket in raw["buckets"].items():
        if not isinstance(key, str) or not _valid_bucket(bucket, raw["schema"]):
            return False
    return all(isinstance(item, dict) and set(item) == {"at", "purpose", "from", "to", "reason"} and all(isinstance(value, str) for value in item.values()) for item in raw["failovers"])


def bucket_key(entry):
    return f"{entry.purpose}/{entry.provider or '-'}/{entry.bucket}"


def _day_label(now, spec):
    return (now.astimezone(KST) - timedelta(hours=spec.reset_hour)).date().isoformat()


def _next_reset(now, spec, window=None):
    """창이 0 으로 돌아가는 시각(UTC) — 일 창은 다음 초기화 시각, 월 창(`window.kind == 'month'`)은 다음 달 1일 00:00(한국 시간)."""
    if window is not None and window.kind == "month":
        return _next_month_start(now)
    today = (now.astimezone(KST) - timedelta(hours=spec.reset_hour)).date()
    return (datetime(today.year, today.month, today.day, tzinfo=KST) + timedelta(days=1, hours=spec.reset_hour)).astimezone(timezone.utc)


def _label_of(window, spec, moment):
    """이 시각이 속한 창의 라벨 — 일 창은 한국 날짜(초기화 시각 반영), 월 창은 `YYYY-MM`."""
    return _day_label(moment, spec) if window.kind == "day" else _month_label(moment)


def _new_audit():
    return {"last_seen": "", "high_water": {"month": "", "attempts": 0}, "last_success": "", "last_error": {"at": "", "outcome": "", "status": 0}, "hold": "", "next_id": 1, "ledger": []}


def _new_bucket(ledger=False):
    bucket = {"windows": {}, "blocked_until": "", "block_kind": "", "backoff": 0}
    if ledger:
        bucket["audit"] = _new_audit()
    return bucket


def _ensure_audit(bucket):
    """장부 제공자의 묶음에 꼬리표(`audit`)와 창의 `successes` 칸을 갖춘다(이미 있으면 그대로)."""
    audit = bucket.setdefault("audit", _new_audit())
    for held in bucket["windows"].values():
        held.setdefault("successes", 0)
    return audit


def _window_state(bucket, window):
    fresh = {"label": "", "used": 0, "minutes": {}, "limit": 0, "limit_at": ""}
    if "audit" in bucket:
        fresh["successes"] = 0
    return bucket["windows"].setdefault(window.name, fresh)


def _peek(bucket, window):
    """창의 기록(없으면 빈 기록) — 상태를 바꾸지 않고 본다."""
    if bucket is not None and window.name in bucket["windows"]:
        return bucket["windows"][window.name]
    empty = {"label": "", "used": 0, "minutes": {}, "limit": 0, "limit_at": ""}
    if bucket is not None and "audit" in bucket:
        empty["successes"] = 0
    return empty


def _limit_of(state, window, now):
    """창의 한도 — 응답 머리글로 알게 된 한도가 24시간 안이면 그것, 아니면 정해 둔 값."""
    if state["limit"] and state["limit_at"] and now - _parse(state["limit_at"]) <= LIMIT_VALID:
        return state["limit"]
    return window.limit


def _used_of(state, window, spec, now):
    if window.kind in ("day", "month"):
        return state["used"] if state["label"] == _label_of(window, spec, now) else 0
    edge = now - timedelta(minutes=window.minutes)
    return sum(count for key, count in state["minutes"].items() if _minute_start(key) + timedelta(minutes=1) > edge)


def _record(state, window, spec, now, calls):
    if window.kind in ("day", "month"):
        label = _label_of(window, spec, now)
        if state["label"] != label:
            state["label"], state["used"] = label, 0
            if "successes" in state:
                state["successes"] = 0
        state["used"] += calls
        return
    key = _minute_key(now)
    state["minutes"][key] = state["minutes"].get(key, 0) + calls
    edge = now - timedelta(minutes=window.minutes)
    state["minutes"] = {name: count for name, count in state["minutes"].items() if _minute_start(name) + timedelta(minutes=1) > edge}


def _floor(limit, percent):
    return -(-limit * percent // 100)                      # 올림


def _frees_at(state, window, now, need):
    """창이 `need` 만큼 비는 시각 — 슬라이딩 창은 오래된 분 묶음부터 빠지고, 월 창은 다음 달 1일 00:00(한국 시간)에 한꺼번에 비워진다."""
    if window.kind == "month":
        return _next_month_start(now)
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
        state = self._assume_half(data)
        if for_write and any("audit" in bucket for bucket in state["buckets"].values()):
            self._save(state)                                       # 장부 제공자의 '확인 필요' 표시는 깨진 파일을 옮겨 둔 즉시 남긴다 — 호출이 거절돼 저장이 없더라도 다음 호출이 빈 상태로 열리지 않게
        return state, notice

    def _assume_half(self, data):
        """깨진 파일 대신 쓰는 보수적 상태 — 다른 제공자는 오늘 한도의 절반을 썼다고 본다. **Fail-Closed 제공자는 절반으로 가정하지 않고** 사용량을 모른다는 표시(`hold`)만 남겨 확인 절차 전에는 호출하지 않는다."""
        now = self.ctx.now()
        state = _fresh()
        for entry in data.entries:
            spec = self.registry[entry.purpose]
            provider = spec.provider(entry.provider)
            bucket = state["buckets"].setdefault(bucket_key(entry), _new_bucket(provider.ledger))
            if provider.fail_closed:
                _ensure_audit(bucket)["hold"] = HOLD_STATE_LOST
                continue
            for window in provider.windows(data.policy(entry.purpose).tier):
                half = window.limit // 2
                if half:
                    _record(_window_state(bucket, window), window, spec, now, half)
        return state

    def _save(self, state):
        state["failovers"] = state["failovers"][-MAX_LOG:]
        state["schema"] = SCHEMA_LEDGER if any("audit" in bucket for bucket in state["buckets"].values()) else SCHEMA          # 장부가 생긴 파일만 판 2 — 다른 제공자만 쓰는 파일은 지금까지와 같은 판 1
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
        spec, provider, windows = self._windows(entry, data)
        verdict, retry = "ok", None
        for window in windows:
            held = _peek(bucket, window)
            limit = _limit_of(held, window, now)
            used = _used_of(held, window, spec, now)
            after = limit - used - calls
            if after < 0:
                when = _next_reset(now, spec, window) if window.kind in ("day", "month") else _frees_at(held, window, now, -after)
                if retry is None or when > retry:
                    retry = when
                verdict = "exhausted"
            elif not provider.stages and after < _floor(limit, FLOOR_PERCENT[priority]) and verdict == "ok":
                verdict = "saving"
        if provider.stages and verdict == "ok":                     # 단계표가 있는 제공자는 '마지막 10% 예약' 대신 콘솔 월 한도 기준의 단계(70·80·90%)를 쓴다
            stage, _used = self._stage_after(bucket, provider, windows, spec, calls, now)
            if self._stage_blocks(stage, priority, calls):
                verdict = "exhausted" if stage.name == cn.STAGE_CLOSED else "saving"
                retry = _next_month_start(now)
        return verdict, retry

    # ---- 단계(콘솔 월 한도 기준) · Fail-Closed 검사 --------------------------------------------------------------------------------------
    @staticmethod
    def _stage_after(bucket, provider, windows, spec, calls, now):
        """(단계 또는 None, 이번 달 사용량) — 이 호출(`calls` 회)을 하고 난 뒤의 이번 달 시도 수가 어느 단계인가. 월 창이 없으면 단계도 없다."""
        month = next((window for window in windows if window.kind == "month"), None)
        if month is None:
            return None, 0
        used = _used_of(_peek(bucket, month), month, spec, now)
        return cn.stage_of(provider, used + calls), used

    @staticmethod
    def _stage_blocks(stage, priority, calls):
        """이 단계가 이 우선순위의 이번 호출을 막나 — 거절 목록에 있거나, 직접 시작한 분석(`new_candidate`)이 한 번에 부르는 횟수가 단계의 상한을 넘을 때."""
        if stage is None:
            return False
        if priority in stage.deny:
            return True
        return priority == NEW and bool(stage.manual_max_calls) and calls > stage.manual_max_calls

    @staticmethod
    def _closed_provider(spec):
        """이 용도에서 Fail-Closed 인 제공자(고정 문구를 가진 것) 또는 None — 지금은 NAVER API HUB 하나."""
        return next((item for item in spec.providers if item.fail_closed), None)

    def _gate(self, state, notice, data, entry, spec, provider, windows, now, *, check_auth):
        """Fail-Closed 검사 — 신규 호출을 열어도 되는지. 통과하면 None, 막으면 `(코드, 사유, 다시 열릴 수 있는 시각 또는 None)`.
        ① 상태 파일을 읽을 수 없었음(`notice`) ② 사용량 기록이 사라진 적이 있음(`hold` — 확인 절차 전까지) ③ 월·일 계수가 한도·과거 값·장부와 모순 ④ 시계가 마지막으로 본 시각보다 허용 오차를 넘게 되돌아감
        ⑤ 인증 상태가 불명확(`check_auth` 일 때 — 연결 시험 호출 자신은 이 검사를 건너뛴다). 아무것도 자동으로 풀지 않는다 — 시계가 돌아오거나 `acknowledge` 로 확인할 때만 열린다."""
        if notice:
            return "unverifiable", "사용량 기록 파일을 읽을 수 없어 사용량을 확인하지 못합니다", None
        bucket = state["buckets"].get(bucket_key(entry))
        audit = bucket.get("audit") if bucket else None
        if audit is not None and audit["hold"]:
            return "unverifiable", "사용량 기록이 사라진 적이 있어 사용량을 확인하지 못합니다 — 운영자가 확인하기 전에는 새 호출을 하지 않습니다", None
        if bucket is not None:
            why = self._count_anomaly(bucket, windows, spec, now)
            if why:
                return "unverifiable", why, None
        if audit is not None and audit["last_seen"]:
            seen = _parse(audit["last_seen"])
            if now < seen - CLOCK_TOLERANCE:
                return "clock", "컴퓨터 시계가 이전에 확인한 시각보다 뒤로 돌아가 있어 한도를 안전하게 셀 수 없습니다 — 시계를 바로잡으면 다시 열립니다", None
        if check_auth:
            auth = cn.auth_state(entry, now=now)
            if auth == cn.AUTH_BAD:
                return "auth_failed", "인증 정보 오류로 멈췄습니다 — 키를 확인해 다시 넣어 주세요", None
            if auth != cn.AUTH_CLEAR:
                return "auth_unclear", "인증 상태가 확실하지 않습니다 — 연결 시험에 성공한 기록이 있어야 새 호출을 합니다", None
        return None

    @staticmethod
    def _count_anomaly(bucket, windows, spec, now):
        """월·일 계수가 한도·과거 값·장부와 모순이면 사유(쉬운 한국어), 아니면 ''. 값은 이미 `_count`(0 이상 정수)로 걸러졌고 여기서는 서로의 관계를 본다:
        현재 창의 시도 수가 한도를 넘음 · 성공이 시도보다 많음 · 하루 시도가 이번 달 시도보다 많음 · 이번 달 시도가 앞서 본 최고치보다 줄었음(숫자를 되돌린 흔적) ·
        남아 있는 호출 장부의 이번 달·오늘 합이 계수보다 많음(장부는 계수의 일부분일 수밖에 없다)."""
        audit = bucket.get("audit")
        if audit is None:
            return ""
        why = "이번 달 사용량 숫자가 한도나 앞의 기록과 맞지 않아 호출을 멈췄습니다 — 기록을 믿을 수 없습니다"
        used, ok_used = {}, {}
        for window in windows:
            held = _peek(bucket, window)
            used[window.kind] = _used_of(held, window, spec, now)
            if used[window.kind] > window.limit or held.get("successes", 0) > held["used"]:
                return why
            ok_used[window.kind] = held.get("successes", 0) if held["label"] == _label_of(window, spec, now) else 0
        if "day" in used and "month" in used and used["day"] > used["month"]:
            return why
        water = audit["high_water"]
        if "month" in used and water["month"] == _month_label(now) and used["month"] < water["attempts"]:
            return why
        for kind, label_of in (("month", _month_label), ("day", lambda moment: _day_label(moment, spec))):
            if kind not in used:
                continue
            mine = [item for item in audit["ledger"] if item["started"] and label_of(_parse(item["started"])) == label_of(now)]
            if sum(item["calls"] for item in mine) > used[kind] or sum(item["calls"] for item in mine if item["ok"]) > ok_used[kind]:
                return why
        return ""

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

    def _closed_wording(self, purpose, result):
        """Fail-Closed 제공자의 거절은 사용자에게 고정 문구(`Provider.stop_text`)를 보이고 구체적인 사유(기술 오류 코드 없이)는 `cause` 로 따로 둔다. 키가 없는 것(`no_key`)은 오류가 아니라 그대로 둔다."""
        if not isinstance(result, Denied) or result.code == "no_key" or purpose not in self.registry:
            return result
        provider = self._closed_provider(self.registry[purpose])
        if provider is None or not provider.stop_text:
            return result
        return replace(result, reason=provider.stop_text, cause=_ERROR_CODE_NOTE.sub("", result.cause or result.reason).strip())          # 사유에는 '(오류 코드 …)' 같은 기술 코드를 남기지 않는다 — 사용자 화면에는 쉬운 한국어만

    def acquire(self, purpose, calls=1, *, priority=NEW, cached=False, request=None, kind="", condition=None):
        """이번 호출의 몫을 잡는다 → `Lease`(어느 항목으로 부를지) 또는 `Denied`(부르지 않는다 — `degraded`·`use_cache`·`retry_at`). 호출하기 **전에** 사용량을 먼저 센다(동시에 부르는 다른 프로세스가 초과하지 못하게).
        `kind`(호출 종류 이름)·`condition`(정규화할 요청 조건 — 키·응답은 넣지 않는다)은 장부 제공자의 호출 장부에만 쓰인다(`condition_hash` 의 앞부분만 남는다)."""
        self._guard_args(purpose, calls, priority)
        if not isinstance(kind, str) or not _KIND_KEY.fullmatch(kind):
            raise ValueError(f"kind 는 소문자·숫자·밑줄 {MAX_KIND}자 이내여야 한다")
        cond = condition_hash(condition)
        request = request if request is not None else Request(purpose, priority)
        if request.closed or request.purpose != purpose:
            return self._closed_wording(purpose, Denied(purpose, "closed", "이 일은 이미 끝났습니다 — 새 일로 다시 시작합니다", degraded=True))
        try:
            with cn.locked(self.ctx, "quota-state", wait=self.lock_wait):
                return self._closed_wording(purpose, self._acquire(purpose, calls, priority, cached, request, kind, cond))      # `kind` 는 호출 종류 이름 — `_acquire` 안의 `kind` 는 항목 검사 결과라 이름을 달리 받는다
        except AppError as error:                                   # 막는 쪽은 실패 열림이 없다 — 상태를 읽거나 쓰지 못하면 호출하지 않고(숨기지 않고 이유를 적어) 건너뛴다
            if error.code == "KEYS_BUSY":
                return self._closed_wording(purpose, Denied(purpose, "busy", "다른 창이 사용량을 기록하는 중이라 이번 호출은 건너뜁니다(한도를 지키려고 호출하지 않았습니다)", degraded=True, use_cache=bool(cached)))
            return self._closed_wording(purpose, Denied(purpose, "unavailable", f"사용량 기록을 읽거나 쓰지 못해 이번 호출은 건너뜁니다(오류 코드 {error.code})", degraded=True, use_cache=bool(cached)))

    def _acquire(self, purpose, calls, priority, cached, request, call_kind="", cond=""):
        data = cn.load(self.ctx, self.registry)
        chain = self._chain(data, purpose)
        closed = self._closed_provider(self.registry[purpose]) is not None
        state, notice = self._load(data, for_write=not closed)      # Fail-Closed 제공자는 깨진 파일을 스스로 옮기거나 고치지 않는다 — 거절하고 그대로 둔다(고치는 길은 `acknowledge`)
        now = self.ctx.now()
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
            spec_c, provider_c, windows_c = self._windows(candidate, data)
            if provider_c.fail_closed:                              # Fail-Closed: 사용량·시계·계수·인증 상태를 확인할 수 없으면 항목 검사 전에 멈춘다
                stop = self._gate(state, notice, data, candidate, spec_c, provider_c, windows_c, now, check_auth=True)
                if stop is not None:
                    return Denied(purpose, stop[0], stop[1], stop[2], degraded=not cached, use_cache=bool(cached), resume_text=self._resume_text(stop[2], now) if stop[2] else "")
            kind, retry = self._check(state, data, candidate, calls, priority, now)
            if kind == "auth":
                if leading:
                    advice = render("KEY_AUTH_FAILED")
                    return Denied(purpose, "auth_failed", f"{advice.message} {advice.action}", degraded=True)
                continue
            if kind == "saving":
                if leading:
                    why = self._stop_cause(kind, state["buckets"].get(bucket_key(candidate)), provider_c, windows_c, spec_c, calls, now) if provider_c.stages else ""
                    return Denied(purpose, "saving_mode", why or "한도에 가까워 절약 모드입니다 — 저장해 둔 값이나 '데이터 없음' 으로 계속합니다", retry, degraded=not cached, use_cache=bool(cached),
                                  resume_text=self._resume_text(retry, now))
                continue
            if kind in ("blocked", "exhausted"):
                reasons.append((kind, retry, self._stop_cause(kind, state["buckets"].get(bucket_key(candidate)), provider_c, windows_c, spec_c, calls, now) if provider_c.ledger else ""))
                if leading and not self._may_switch(data, purpose, chain, candidate):
                    break
                continue
            return self._lease(state, data, purpose, candidate, first, calls, priority, request, now, notice, call_kind, cond)
        if reasons:
            retry = min((when for _kind, when, _why in reasons if when is not None), default=None)
            exhausted = any(kind == "exhausted" for kind, _when, _why in reasons)
            why = next((text for _kind, _when, text in reasons if text), "")
            return Denied(purpose, "exhausted" if exhausted else "blocked", why or (("한도를 다 써서 " if exhausted else "한도에 걸려 ") + "지금은 호출하지 않습니다 — 저장해 둔 값이나 '데이터 없음' 으로 계속합니다"), retry,
                          degraded=not cached, use_cache=bool(cached), resume_text=self._resume_text(retry, now))
        return Denied(purpose, "no_more_keys", "바꿔 시도할 수 있는 키가 더 없어 이번에는 건너뜁니다 — 저장해 둔 값이나 '데이터 없음' 으로 계속합니다", degraded=not cached, use_cache=bool(cached))

    def _resume_text(self, retry, now):
        if retry is None:
            return ""
        local = retry.astimezone(KST)
        same_day = local.date() == now.astimezone(KST).date()
        return f"{'오늘' if same_day else '내일' if (local.date() - now.astimezone(KST).date()).days == 1 else _korean_date(local)} {local.strftime('%H:%M')} 이후 자동 재개"

    def _lease(self, state, data, purpose, entry, first, calls, priority, request, now, notice, call_kind="", cond=""):
        spec, provider, windows = self._windows(entry, data)
        bucket = state["buckets"].setdefault(bucket_key(entry), _new_bucket(provider.ledger))
        if provider.ledger:
            _ensure_audit(bucket)
        for window in windows:
            _record(_window_state(bucket, window), window, spec, now, calls)
        switched = entry.entry_id != first.entry_id
        note = ""
        if switched:
            before = next((item for item in data.entries if item.entry_id == (request.tried[-1] if request.tried else first.entry_id)), first)
            reason = request.last_kind or "blocked"
            note = f"다른 키로 바꿨습니다: '{before.name}' → '{entry.name}' (이유: {reason})"
            state["failovers"].append({"at": _stamp(now), "purpose": purpose, "from": before.name, "to": entry.name, "reason": reason})
        call_id = 0
        if provider.ledger:                                         # 호출하기 전에 시도를 장부에 적는다 — 결과는 `report` 가 채운다(끝내 못 채워도 시도로 남는다)
            call_id = self._audit_begin(bucket, windows, spec, now, call_kind, cond, calls, len(request.tried))
        if provider.stages:
            stage, _used = self._stage_after(bucket, provider, windows, spec, 0, now)       # 이 호출까지 센 뒤의 단계 — 안내(70%)·제한(80%)·중지(90%) 문구를 호출하는 쪽에 알린다
            if stage is not None:
                note = f"{note} {stage.text}".strip()
        request.tried.append(entry.entry_id)
        self._save(state)
        return Lease(purpose, entry.entry_id, entry.ref, entry.name, entry.provider, entry.bucket, calls, priority, now, note, switched, request, call_id)

    @staticmethod
    def _touch_audit(bucket, windows, spec, now):
        """마지막으로 본 시각(되돌아가지 않는다)과 이번 달 시도 수의 최고치를 갱신한다 — 시계 되돌림·계수 되돌림을 알아보는 기준."""
        audit = bucket["audit"]
        if not audit["last_seen"] or now > _parse(audit["last_seen"]):
            audit["last_seen"] = _stamp(now)
        month = next((window for window in windows if window.kind == "month"), None)
        if month is not None:
            label = _month_label(now)
            used = _used_of(_peek(bucket, month), month, spec, now)
            water = audit["high_water"]
            audit["high_water"] = {"month": label, "attempts": max(used, water["attempts"] if water["month"] == label else 0)}

    def _audit_begin(self, bucket, windows, spec, now, call_kind, cond, calls, retries):
        audit = bucket["audit"]
        call_id = audit["next_id"]
        audit["next_id"] = call_id + 1
        audit["ledger"].append({"id": call_id, "kind": call_kind, "started": _stamp(now), "finished": "", "condition": cond, "ok": False, "status": 0, "outcome": "", "retries": retries,
                                "used_response": False, "cache_hit": False, "calls": calls})
        del audit["ledger"][:-MAX_LEDGER]
        self._touch_audit(bucket, windows, spec, now)
        return call_id

    def _audit_finish(self, bucket, windows, spec, lease, now, outcome, status, used_response):
        """호출 결과를 장부에 채우고 성공이면 창의 성공 수를 올린다(시도 수는 호출 전에 이미 셌다). 성공 수는 **호출을 잡은 때가 속한 창**에만 올려 시도 수를 넘지 않는다."""
        audit = _ensure_audit(bucket)
        ok = outcome == OK
        record = next((item for item in reversed(audit["ledger"]) if lease.call_id and item["id"] == lease.call_id), None)
        if record is None:                                          # 장부에서 밀려났거나 번호가 없는 호출 — 끝난 기록을 새로 적는다
            call_id = audit["next_id"]
            audit["next_id"] = call_id + 1
            record = {"id": call_id, "kind": "", "started": _stamp(lease.at), "finished": "", "condition": "", "ok": False, "status": 0, "outcome": "", "retries": 0, "used_response": False,
                      "cache_hit": False, "calls": lease.calls}
            audit["ledger"].append(record)
            del audit["ledger"][:-MAX_LEDGER]
        record.update({"finished": _stamp(now), "ok": ok, "status": status, "outcome": outcome, "used_response": ok if used_response is None else bool(used_response)})
        if ok:
            for window in windows:
                held = _window_state(bucket, window)
                if held["label"] == _label_of(window, spec, lease.at):
                    held["successes"] = min(held["used"], held["successes"] + lease.calls)
            audit["last_success"] = _stamp(now)
        else:
            audit["last_error"] = {"at": _stamp(now), "outcome": outcome, "status": status}
        self._touch_audit(bucket, windows, spec, now)

    def acquire_entry(self, entry, calls=1, priority=CRITICAL, *, kind="", condition=None):
        """항목 하나를 콕 집어 잡는다(연결 시험용 — 다른 항목으로 바꾸지 않는다). Fail-Closed 검사 중 **인증 상태만** 건너뛴다(이 호출이 인증 상태를 확인하는 호출이다)."""
        self._guard_args(entry.purpose, calls, priority)
        if not isinstance(kind, str) or not _KIND_KEY.fullmatch(kind):
            raise ValueError(f"kind 는 소문자·숫자·밑줄 {MAX_KIND}자 이내여야 한다")
        cond = condition_hash(condition)
        request = Request(entry.purpose, priority)
        try:
            with cn.locked(self.ctx, "quota-state", wait=self.lock_wait):
                data = cn.load(self.ctx, self.registry)
                state, notice = self._load(data, for_write=self._closed_provider(self.registry[entry.purpose]) is None)
                now = self.ctx.now()
                spec, provider, windows = self._windows(entry, data)
                if provider.fail_closed:
                    stop = self._gate(state, notice, data, entry, spec, provider, windows, now, check_auth=False)
                    if stop is not None:
                        return self._closed_wording(entry.purpose, Denied(entry.purpose, stop[0], stop[1], stop[2], degraded=True))
                verdict, retry = self._check(state, data, entry, calls, priority, now)
                if verdict != "ok":
                    return self._closed_wording(entry.purpose, Denied(entry.purpose, "saving_mode" if verdict == "saving" else verdict, "지금은 이 키로 호출할 수 없습니다", retry, degraded=True,
                                                                      resume_text=self._resume_text(retry, now)))
                return self._lease(state, data, entry.purpose, entry, entry, calls, priority, request, now, notice, kind, cond)
        except AppError as error:
            if error.code == "KEYS_BUSY":
                return self._closed_wording(entry.purpose, Denied(entry.purpose, "busy", "다른 창이 사용량을 기록하는 중입니다", degraded=True))
            return self._closed_wording(entry.purpose, Denied(entry.purpose, "unavailable", f"사용량 기록을 읽거나 쓰지 못해 건너뜁니다(오류 코드 {error.code})", degraded=True))

    # ---- 결과 알리기 ---------------------------------------------------------------------------------------------------------------------
    def report(self, lease, outcome, *, retry_after=None, reset_at=None, headers=None, status=None, used_response=None):
        """호출 결과를 알린다. 전환·재시도는 여기서 정해 `ReportResult.action` 으로 알려 준다: `done`(끝) · `try_next`(다음 항목으로 `acquire` 를 다시) · `retry_same`(`wait_seconds` 뒤 같은 항목으로 한 번) · `stop`(멈춤 — `advice` 대로).
        `status`(HTTP 상태 번호)·`used_response`(응답을 실제로 썼나 — 안 적으면 성공일 때 참)는 장부 제공자의 호출 장부에만 적힌다."""
        if outcome not in OUTCOMES:
            raise ValueError("알 수 없는 결과 종류")
        status = status if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599 else 0
        with cn.locked(self.ctx, "quota-state", wait=self.lock_wait):
            data = cn.load(self.ctx, self.registry)
            state, _notice = self._load(data, for_write=True)
            return self._report(state, data, lease, outcome, retry_after, reset_at, headers, status, used_response)

    def _report(self, state, data, lease, outcome, retry_after, reset_at, headers, status=0, used_response=None):
        now = self.ctx.now()
        request = lease.request
        entry = next((item for item in data.entries if item.entry_id == lease.entry_id), None)
        if entry is None:                                           # 그 사이 항목이 지워졌다 — 더 시도하지 않는다
            request.closed = True
            return ReportResult(ACT_STOP, "")
        spec, provider, windows = self._windows(entry, data)
        bucket = state["buckets"].setdefault(bucket_key(entry), _new_bucket(provider.ledger))
        if provider.ledger:
            _ensure_audit(bucket)
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
            for window in () if provider.ledger else windows:       # 장부 제공자는 시도 수를 있는 그대로 둔다(채워 넣으면 '실제로 시도한 횟수' 가 아니게 된다) — 쉬는 시각(`blocked_until`)이 막는다
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
        if provider.ledger:
            self._audit_finish(bucket, windows, spec, lease, now, outcome, status, used_response)
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

    def _stop_cause(self, kind, bucket, provider, windows, spec, calls, now):
        """호출을 멈춘 사유(쉬운 한국어, 기술 오류 코드 없음) — 한도 응답으로 쉬는 중·내부 한도(오늘·이번 달)에 닿음·단계(80%·90%)."""
        if kind == "blocked":
            return "한도 초과 응답을 받아 잠시 쉬는 중입니다" if bucket and bucket["block_kind"] == RATE_LIMITED else "서비스가 기간 한도를 다 썼다고 알려 와 다음 초기화 때까지 쉽니다"
        parts = []
        for window in windows:
            held = _peek(bucket, window)
            limit = _limit_of(held, window, now)
            if limit - _used_of(held, window, spec, now) - calls < 0:
                parts.append(("오늘 내부 한도" if window.kind == "day" else "이번 달 내부 한도") + f"({limit:,}회)를 다 썼습니다")
        if parts:
            return " · ".join(parts)
        stage, _used = self._stage_after(bucket, provider, windows, spec, calls, now)
        return stage.text if stage is not None else ""

    # ---- 사용량 보기(읽기만) --------------------------------------------------------------------------------------------------------
    def usage(self, purpose=None):
        """용도별 사용량 — 읽기만 한다(파일을 만들거나 바꾸지 않는다). 상태 파일이 깨졌으면 보수적으로 절반을 쓴 것으로 보여 주고 안내를 붙인다(Fail-Closed 제공자는 '확인할 수 없음' 으로 보인다). 옛 용도는 사용량이 없어 건너뛴다."""
        data = cn.load(self.ctx, self.registry)
        state, notice = self._load(data, for_write=False)
        now = self.ctx.now()
        views = []
        for key in self.registry:
            if purpose is not None and key != purpose:
                continue
            spec = self.registry[key]
            if not spec.takes_keys or spec.legacy_to:
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
                if provider.stages:                                     # 단계표가 있는 제공자는 '마지막 10%' 대신 단계로 본다 — 월 행은 80% 를 넘었을 때(자동 새로고침 중지), 일 행은 한도에 닿았을 때
                    stage, _total = self._stage_after(held_bucket, provider, windows, spec, 1, now)
                    near = (stage is not None and stage.name != cn.STAGE_NOTICE) if window.kind == "month" else used >= limit
                else:
                    near = limit - used <= _floor(limit, RESERVE_PERCENT)
                saving = saving or near
                successes = (held.get("successes", 0) if held["label"] == _label_of(window, spec, now) else 0) if provider.ledger else None
                span = "하루" if window.kind == "day" else "이번 달" if window.kind == "month" else f"최근 {window.minutes}분"
                rows.append(UsageRow(entry.name, provider.label or spec.label, window.name, used, limit, near, span, successes))
            if held_bucket and held_bucket["blocked_until"] and now < _parse(held_bucket["blocked_until"]):
                blocked = True
                until = _parse(held_bucket["blocked_until"])
                retry = until if retry is None or until < retry else retry
        switches = tuple(f"{self._stamp_text(item['at'])} '{item['from']}' → '{item['to']}' (이유: {item['reason']})" for item in state["failovers"] if item["purpose"] == spec.key)[-3:]
        ledger = self._ledger_usage(state, notice, data, spec, now) if any(item.ledger for item in spec.providers) else None
        if notice and self._closed_provider(spec) is not None:      # 깨진 파일 안내('절반을 썼다고 가정')는 Fail-Closed 제공자에게 거짓이다 — 이 제공자는 절반으로 가정하지 않고 멈춘다
            notice = LOST_NOTICE
        return UsageView(spec.key, spec.label, tuple(rows), saving, blocked, retry, self._resume_text(retry, now) if retry else "", notice, len(mine), switches, ledger)

    def _ledger_usage(self, state, notice, data, spec, now):
        """장부 제공자의 설정 화면용 값 — 오늘·이번 달 시도/성공, 내부 일/월 한도, 콘솔 월 한도, 마지막 성공·오류, 단계, 호출 중지 사유. 읽기만 한다."""
        provider = next(item for item in spec.providers if item.ledger)
        windows = provider.windows(data.policy(spec.key).tier)
        entry = cn.primary_entry(data, spec.key) or next(iter(data.of_purpose(spec.key)), None)
        bucket = state["buckets"].get(bucket_key(entry)) if entry is not None else None
        day = next((window for window in windows if window.kind == "day"), None)
        month = next((window for window in windows if window.kind == "month"), None)

        def count(window, name):
            if window is None:
                return 0
            held = _peek(bucket, window)
            return held.get(name, 0) if held["label"] == _label_of(window, spec, now) else 0

        audit = bucket.get("audit") if bucket else None
        stop_code, stop_cause = "", ""
        if entry is not None:
            gate = self._gate(state, notice, data, entry, spec, provider, windows, now, check_auth=True)
            if gate is not None:
                stop_code, stop_cause = gate[0], gate[1]
            else:
                verdict, _retry = self._check(state, data, entry, 1, CRITICAL, now)
                if verdict in ("blocked", "exhausted"):
                    stop_code, stop_cause = verdict, self._stop_cause(verdict, bucket, provider, windows, spec, 1, now)
        stage, _used = self._stage_after(bucket, provider, windows, spec, 1, now)
        error = audit["last_error"] if audit and audit["last_error"]["at"] else None
        return LedgerUsage(count(day, "used"), count(day, "successes"), count(month, "used"), count(month, "successes"), day.limit if day else 0, month.limit if month else 0, provider.console_limit,
                           audit["last_success"] if audit else "", dict(error) if error else None, stage.name if stage is not None else "ok", stage.text if stage is not None else "",
                           bool(stop_code), stop_code, stop_cause, provider.stop_text if stop_code else "")

    def acknowledge(self, purpose, *, confirmed=False):
        """운영자의 확인 — Fail-Closed 제공자의 '확인 필요' 멈춤(사용량 기록이 사라진 적이 있음)과 시계 이상을 **운영자가 명시적으로** 푼다(자동으로는 풀리지 않는다). `confirmed` 가 True 가 아니면 아무것도 바꾸지 않고 `ValueError`.
        지금 시계를 '마지막으로 본 시각' 으로 받아들이고, 사용량 기록이 사라졌던 묶음은 보수적으로 한도의 절반을 이미 쓴 것으로 두고 다시 센다. 반환: 푼 묶음 수."""
        if purpose not in self.registry:
            raise ValueError("알 수 없는 용도")
        if confirmed is not True:
            raise ValueError("운영자가 확인했다는 표시(confirmed=True)가 있어야 한다")
        spec = self.registry[purpose]
        if self._closed_provider(spec) is None:
            raise ValueError("이 용도는 확인 절차가 필요한 제공자가 아니다")
        released = 0
        with cn.locked(self.ctx, "quota-state", wait=self.lock_wait):
            data = cn.load(self.ctx, self.registry)
            state, _notice = self._load(data, for_write=True)
            now = self.ctx.now()
            for entry in data.of_purpose(purpose):
                _spec, provider, windows = self._windows(entry, data)
                if not provider.fail_closed:
                    continue
                bucket = state["buckets"].setdefault(bucket_key(entry), _new_bucket(True))
                audit = _ensure_audit(bucket)
                if audit["hold"] == HOLD_STATE_LOST:
                    for window in windows:
                        held = _window_state(bucket, window)
                        held["label"], held["used"], held["successes"], held["minutes"] = "", 0, 0, {}
                        if window.limit // 2:
                            _record(held, window, spec, now, window.limit // 2)
                    audit["high_water"] = {"month": "", "attempts": 0}
                audit["hold"] = ""
                audit["last_seen"] = _stamp(now)
                self._touch_audit(bucket, windows, spec, now)
                released += 1
            self._save(state)
        return released

    def record_cache_hit(self, purpose, *, kind="", condition=None):
        """저장해 둔 조회 결과를 대신 쓴 것을 호출 장부에 남긴다(호출이 아니므로 시도·성공은 세지 않는다). 장부 제공자만. 키가 없거나 상태 파일을 읽을 수 없으면 적지 않고 False."""
        self._guard_args(purpose, 1, NEW)
        spec = self.registry[purpose]
        if not any(item.ledger for item in spec.providers):
            raise ValueError("이 용도는 호출 장부를 쓰지 않는다")
        if not isinstance(kind, str) or not _KIND_KEY.fullmatch(kind):
            raise ValueError(f"kind 는 소문자·숫자·밑줄 {MAX_KIND}자 이내여야 한다")
        cond = condition_hash(condition)
        with cn.locked(self.ctx, "quota-state", wait=self.lock_wait):
            data = cn.load(self.ctx, self.registry)
            entry = cn.primary_entry(data, purpose)
            if entry is None:
                return False
            state, notice = self._load(data, for_write=False)
            if notice:
                return False
            _spec, provider, windows = self._windows(entry, data)
            bucket = state["buckets"].setdefault(bucket_key(entry), _new_bucket(True))
            audit = _ensure_audit(bucket)
            now = self.ctx.now()
            call_id = audit["next_id"]
            audit["next_id"] = call_id + 1
            audit["ledger"].append({"id": call_id, "kind": kind, "started": _stamp(now), "finished": _stamp(now), "condition": cond, "ok": True, "status": 0, "outcome": OK, "retries": 0,
                                    "used_response": True, "cache_hit": True, "calls": 0})
            del audit["ledger"][:-MAX_LEDGER]
            self._touch_audit(bucket, windows, spec, now)
            self._save(state)
        return True

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
    successes: object = None        # 장부 제공자의 창에서만 — 성공 횟수(`used` 는 시도 횟수). 다른 제공자는 None 이라 `to_dict` 모양이 그대로다

    def to_dict(self):
        found = {"entry": self.entry, "provider": self.provider, "window": self.window, "used": self.used, "limit": self.limit, "near_limit": self.near_limit, "span": self.span}
        if self.successes is not None:
            found.update({"attempts": self.used, "successes": self.successes})
        return found


@dataclass(frozen=True)
class LedgerUsage:
    """장부 제공자의 설정 화면용 값 — 시도와 성공을 따로 보인다."""
    day_attempts: int
    day_successes: int
    month_attempts: int
    month_successes: int
    day_limit: int                  # 프로그램 안 하루 한도
    month_limit: int                # 프로그램 안 월 한도
    console_limit: int              # 서비스 콘솔의 월 한도(참고 — 단계 비율의 기준)
    last_success: str               # 마지막으로 성공한 호출의 시각(UTC 글자) 또는 ''
    last_error: object              # {'at', 'outcome', 'status'} 또는 None
    stage: str                      # ok · notice · limited · closed
    stage_text: str
    stopped: bool                   # 지금 새 호출을 하지 않는 중인가
    stop_code: str
    stop_cause: str                 # 멈춘 사유(쉬운 한국어)
    stop_text: str                  # 멈춘 때 사용자에게 보이는 고정 문구('' 이면 멈추지 않았다)

    def to_dict(self):
        return {"day_attempts": self.day_attempts, "day_successes": self.day_successes, "month_attempts": self.month_attempts, "month_successes": self.month_successes,
                "day_limit": self.day_limit, "month_limit": self.month_limit, "console_limit": self.console_limit, "last_success": self.last_success, "last_error": self.last_error,
                "stage": self.stage, "stage_text": self.stage_text, "stopped": self.stopped, "stop_code": self.stop_code, "stop_cause": self.stop_cause, "stop_text": self.stop_text}


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
    ledger: object = None           # 장부 제공자의 `LedgerUsage` — 다른 제공자는 None 이라 `to_dict` 모양이 그대로다

    def to_dict(self):
        found = {"purpose": self.purpose, "label": self.label, "rows": [row.to_dict() for row in self.rows], "saving_mode": self.saving_mode, "blocked": self.blocked,
                 "resume_at": _stamp(self.resume_at) if self.resume_at else "", "resume_text": self.resume_text, "notice": self.notice, "entries": self.entries, "switches": list(self.switches)}
        if self.ledger is not None:
            found["ledger"] = self.ledger.to_dict()
        return found


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
