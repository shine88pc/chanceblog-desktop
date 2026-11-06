"""보류함의 만료일 — 점수 구간이 `HOLD`(50~64점)인 후보를 며칠까지 보관하는지 계산한다(순수 계산: 날짜·시각은 인자로 받고 시계를 읽지 않는다).

계획 문서 3.1 표의 `bands.py`('보류 만료일' 자리) 대신 이 파일에 둔다 — 구간 계산(`score.band_of`)은 P1 에서 `score.py` 로 들어갔고 여기에는 그 구간의 **보관 기한**만 있다(독립 검증 L8-①, 결정 D-43).
  · 만료일 = 평가한 시각 + `channels.HOLD_DAYS`(90일). 시각은 협정세계시(UTC) `YYYY-MM-DDTHH:MM:SSZ` 이고 후보의 `review_expires_at` 칸과 같은 모양이다.
  · 보류 구간이 아닌 후보(우선 추천·일반·제외·점수 없음)는 만료일이 없다(`None`) — '만료일 없음' 과 '지났다' 는 다르다.
  · **90일은 최초로 보류 구간에 든 시각이 기준이다**(P3b-1, D-62 정정): 일반 재평가로 초기화하지 않고, 다른 구간으로 잠시 이동했다가 자동으로 돌아와도 최초 시각을 유지하며, 사용자가 직접 다시 활성화할 때만 새 주기다
    (저장 단계가 지킨다 — `topicdb/store.py`). 90일 뒤 변화가 없으면 상세 후보 데이터를 정리하고(`topics hold cleanup --yes` 와 미리 보기가 보인 확인 번호) 이력 13칸(`HISTORY_FIELDS`)만 남긴다 — `history_row` 가 그 13칸을 후보에서 뽑는다. 정리한 후보 번호는 영구히 다시 쓰지 않고(저장소가 거절한다)
    같은 주제를 다시 후보로 만들 때는 새 번호를 받아 정리 이력과 `RECREATED_FROM` 관계로 이어진다(`recreation_input`·`next_recreated_id` — 저장 쪽은 `TopicStore.recreate_candidate`).
  · 시각·날수가 틀렸을 때의 오류는 주제 엔진 안내 틀(`CONTENT_INVALID`, '보류함의 …')이다 — P2a 에서는 후보 칸 오류(`CANDIDATE_INVALID`)여서 '주제는 200자…' 같은 후보용 조치가 따라 나왔다(P2b, 독립 검증 M7).
  · 지났는가는 `now >= 만료일` 이다(만료 시각 정각이면 지난 것). 지났어도 이 함수들은 아무것도 지우거나 바꾸지 않는다 — '90일이 지나도 변화가 없으면 상세 후보는 정리하고 이력만 남긴다' 는 저장·서비스 단계의 일이고
    여기서는 '지났다' 는 표시만 돌려준다. 처음 보류함에 들어간 때를 기준으로 한 번만 정할지 다시 평가할 때마다 새로 정할지도 부르는 쪽(저장 단계)이 정한다.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import NamedTuple

from ..content.candidates import HOLD as WORK_HOLD
from ..content.candidates import REJECTED, STAMP_FORMAT, keyword_key, parse_stamp
from ..errors import AppError
from .channels import GRADE_CUTOFFS, HOLD_DAYS, invalid_in
from .score import BAND_EXCLUDED, BAND_HOLD, BANDS

SUBJECT = "보류함"
MAX_DAYS = 3650                                                       # 보관 날수의 상한(10년) — 실수로 아주 큰 값을 넣지 않게
MAX_GENERATION = 1000                                                 # 같은 옛 번호에서 다시 만든 횟수의 상한 — 번호 찾기가 끝없이 돌지 않게
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _invalid(item, detail=""):
    return invalid_in(SUBJECT, item, detail)


def _stamp(value, item):
    """UTC 시각 글(`YYYY-MM-DDTHH:MM:SSZ`) → 시각. 모양이 틀리면 후보 칸 오류 대신 보류함 오류(주제 엔진 안내 틀)로 바꿔 던진다."""
    try:
        return parse_stamp(value, item)
    except AppError as error:
        raise _invalid(item, str(error.slots.get("이유", "")) or "시각의 모양이 맞지 않습니다") from None


# 90일 뒤 상세 데이터를 정리하고도 남기는 이력 13칸(전략 원문 §19 의 여섯 + 중복 판정·씨앗·채널·검색 의도·관점 + 정리한 시각·정리 사유) — 칸 이름은 영문 스네이크 케이스, 쉬운 한국어 이름은 `HISTORY_FIELD_KO`(D-120: 판 2 가 배포 전이라
# 앞선 11칸의 `first_created_on`(날짜)을 `first_created_at`(후보의 만든 시각 그대로)으로 바꾸고 `cleaned_at`·`cleanup_reason` 을 더했다). 없는 값은 빈 글('')이다. 이 칸들로 같은 후보를 계속 알아보고(`slots.sameness_keys` 가 보는 번호·주제 해시·씨앗·검색 의도·관점이
# 모두 들어 있다) 정리한 주제를 새 후보로 다시 만들 최소 정보도 남는다(`recreation_input`). 후보 상세(점수·선정 이유·출처 JSON)는 어느 칸에도 담지 않는다 — 날짜·고정 문장·해시·식별자뿐이다.
HISTORY_FIELDS = ("normalized_keyword", "topic_summary", "first_created_at", "last_evaluated_on", "hold_reason", "exclusion_reason", "normalized_topic_hash", "seed_id", "channel", "search_intent", "topic_angle",
                  "cleaned_at", "cleanup_reason")
HISTORY_FIELD_KO = MappingProxyType({
    "normalized_keyword": "정규화 키워드", "topic_summary": "주제 요약", "first_created_at": "처음 생성 시각", "last_evaluated_on": "마지막 평가일", "hold_reason": "보류 사유", "exclusion_reason": "제외 사유",
    "normalized_topic_hash": "주제 비교 번호", "seed_id": "씨앗 번호", "channel": "채널", "search_intent": "검색 의도", "topic_angle": "관점", "cleaned_at": "정리한 시각", "cleanup_reason": "정리 사유"})
CLEANUP_REASON = "hold_90d_unchanged"                                  # 정리 사유의 고정 코드 글 — 후보 글을 되풀이하지 않는다(보류 90일 동안 변화가 없었다)
RELATION_RECREATED = "RECREATED_FROM"                                  # 정리한 후보의 주제를 새 번호의 후보로 다시 만들었을 때 `candidate_lineage` 에 적는 관계 종류
RECREATED_PREFIX = "rc-"                                               # 다시 만든 후보 번호의 머리 — 엔진이 만드는 번호(`tc-…`)와 절대 같지 않게 한다
# 정리할 때 **지워지는 것**(어느 표의 어떤 칸인지 못박는다 — 이 밖의 것은 건드리지 않는다): 후보 행 전체(상세 JSON `candidates.data`: 점수·선정 이유·보조 키워드·관심도·안전 표시·처리 문제 포함)·
# 점수 스냅샷(`score_snapshots.data` 본문)·출처 스냅샷(`provenance.data`)·보류함 기록(`hold_box`)·기존 후보 연결(`candidate_links`, 연결이 있는 후보는 애초에 정리 대상이 아니다).
CLEANUP_ERASES = (("candidates", "data", "후보의 상세 내용(점수·선정 이유·보조 키워드·관심도·안전 표시)"), ("score_snapshots", "data", "점수 기록 본문"), ("provenance", "data", "출처 기록"),
                  ("hold_box", "*", "보류함 기록(머문 기간)"), ("candidate_links", "data", "기존 후보·초안과의 연결(연결이 있는 후보는 정리하지 않는다)"))


def history_row(candidate, last_evaluated_on, topic_hash, cleaned_at):
    """엔진 후보 → 보류 이력 13칸(`HISTORY_FIELDS` 순서의 사전). `last_evaluated_on` 은 마지막 평가 시각(UTC 시각 글), `topic_hash` 는 `slots.normalized_topic_hash` 의 값(없으면 None → ''), `cleaned_at` 은 정리를 실행한 시각(UTC 시각 글)이다.
    `first_created_at` 은 후보의 만든 시각 그대로(UTC 시각 글), `cleanup_reason` 은 고정 코드 글(`CLEANUP_REASON`)이다. 보류 사유·제외 사유는 후보의 구간·작업 상태에서 쉬운 말로 만든다(점수 숫자 외에 후보의 글을 되풀이하지 않는다)."""
    low, high = GRADE_CUTOFFS[2], GRADE_CUTOFFS[1] - 1
    final = candidate.scores.final
    hold_reason = ""
    if candidate.recommendation_band == BAND_HOLD or candidate.work_status == WORK_HOLD:
        hold_reason = (f"점수 {final}점으로 보류 구간({low}~{high}점)에 들어 {HOLD_DAYS}일 동안 변화가 없었습니다" if candidate.recommendation_band == BAND_HOLD
                       else f"사람이 보류했고 {HOLD_DAYS}일 동안 변화가 없었습니다")
    exclusion_reason = ""
    if candidate.recommendation_band == BAND_EXCLUDED:
        exclusion_reason = f"점수 {final}점이라 제외 구간입니다"
    elif candidate.work_status == REJECTED:
        exclusion_reason = "사람이 제외했습니다"
    return {"normalized_keyword": keyword_key(candidate.primary_keyword), "topic_summary": candidate.topic, "first_created_at": candidate.created_at, "last_evaluated_on": str(last_evaluated_on)[:10],
            "hold_reason": hold_reason, "exclusion_reason": exclusion_reason, "normalized_topic_hash": topic_hash or "", "seed_id": candidate.seed_id or "", "channel": candidate.channel,
            "search_intent": candidate.search_intent, "topic_angle": candidate.topic_angle, "cleaned_at": _stamp(cleaned_at, "정리한 시각").strftime(STAMP_FORMAT), "cleanup_reason": CLEANUP_REASON}


class RecreationInput(NamedTuple):
    """정리 이력 한 줄에서 정리한 주제를 새 후보로 다시 만들 때 필요한 최소 정보(D-120) — 후보 상세(점수·선정 이유 …)는 지워졌으므로 이 값들로 새 후보를 만들고 새로 평가한다."""
    seed_id: str
    channel: str
    search_intent: str
    topic_angle: str
    normalized_keyword: str
    normalized_topic_hash: str
    first_created_at: str


def recreation_input(row):
    """정리 이력 한 줄(`HoldHistory` 같은 이름 있는 값이나 `history_row` 의 사전) → `RecreationInput`. 없는 칸이 있으면 `KeyError`/`AttributeError`."""
    get = (lambda name: row[name]) if isinstance(row, Mapping) else (lambda name: getattr(row, name))
    return RecreationInput(*(get(name) for name in RecreationInput._fields))


def next_recreated_id(old_id, generation=1, used=()):
    """정리한 옛 번호 → 다시 만들 후보의 **새 번호**(`rc-세대-16진수 16자`). 옛 번호와 세대 수에서 결정적으로 만든다(시계·난수 없음) — 같은 입력이면 같은 번호이고 옛 번호를 되살리지 않는다.
    `used`(`TopicStore.used_candidate_ids()` 의 번호들)에 이미 있는 번호이거나 옛 번호와 같으면 세대를 올려 다음 번호를 쓴다. 번호는 영문·숫자·밑줄·붙임표 1~64자다."""
    if not isinstance(old_id, str) or not _ID.fullmatch(old_id):
        raise ValueError("옛 후보 번호는 영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 한다")
    if not isinstance(generation, int) or isinstance(generation, bool) or not 1 <= generation <= MAX_GENERATION:
        raise ValueError(f"세대는 1~{MAX_GENERATION} 사이의 정수여야 한다")
    taken = set(used)
    while generation <= MAX_GENERATION:
        digest = hashlib.sha256(f"recreate|{old_id}|{generation}".encode()).hexdigest()[:16]
        found = f"{RECREATED_PREFIX}{generation}-{digest}"
        if found != old_id and found not in taken:
            return found
        generation += 1
    raise ValueError("쓸 수 있는 새 번호를 찾지 못했다(세대가 한도를 넘었다)")


TOKEN_VERSION = "cleanup-v1"                                           # 확인 번호를 만드는 방식의 이름 — 방식이 바뀌면 이 이름도 바꿔 옛 번호가 통하지 않게 한다


def cleanup_token(targets):
    """정리 대상들의 **확인 번호**(D-120) — 대상 후보마다 `번호|채널|기한` 한 줄을 후보 번호 순으로 이어 붙이고 앞에 방식 이름(`TOKEN_VERSION`)을 붙인 글의 SHA-256 앞 12자리(16진수). 대상이 없으면 None.
    미리 보기가 이 번호를 보여 주고 `--yes` 는 같은 번호를 다시 받아야 정리한다 — 미리 본 뒤 대상이 하나라도 바뀌면(후보가 늘거나 줄거나 기한·채널이 달라지면) 번호가 달라져 정리되지 않는다.
    `targets` 는 `candidate_id`·`channel`·`expires_at` 을 가진 것들이다(시계·난수·파일을 쓰지 않는다)."""
    lines = [f"{item.candidate_id}|{item.channel}|{item.expires_at}" for item in sorted(targets, key=lambda item: item.candidate_id)]
    if not lines:
        return None
    return hashlib.sha256(("\n".join([TOKEN_VERSION, *lines])).encode("utf-8")).hexdigest()[:12]


def review_expires_at(evaluated_at, days=HOLD_DAYS):
    """평가한 시각(UTC `YYYY-MM-DDTHH:MM:SSZ`) + `days`일(기본 `HOLD_DAYS` = 90) → 만료 시각(같은 모양의 글). 모양이 틀린 시각·범위 밖 날수·달력을 넘는 값은 `CANDIDATE_INVALID`."""
    moment = _stamp(evaluated_at, "평가한 시각")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= MAX_DAYS:
        raise _invalid("보관 날수", f"1~{MAX_DAYS} 사이의 정수여야 합니다")
    try:
        due = moment + timedelta(days=days)
    except OverflowError:
        raise _invalid("검토 기한", "너무 먼 미래라 보관 기한을 계산할 수 없습니다") from None
    return due.strftime(STAMP_FORMAT)


def expiry_for(band, evaluated_at, days=HOLD_DAYS):
    """추천 구간(`score.band_of` 의 값)이 보류(`HOLD`)이면 만료 시각을, 그 밖의 구간이면 None 을 돌려준다. 모르는 구간 이름은 `ValueError`.
    평가한 시각과 날수는 구간과 상관없이 늘 검사한다(틀린 시각이 구간에 따라 숨지 않게)."""
    if not isinstance(band, str) or band not in BANDS:
        raise ValueError("모르는 추천 구간이다: " + ", ".join(BANDS) + " 중 하나여야 한다")
    expiry = review_expires_at(evaluated_at, days)
    return expiry if band == BAND_HOLD else None


def is_expired(expires_at, now):
    """만료 시각이 있고 `now`(UTC 시각 글)가 그 시각 이후(같은 시각 포함)이면 True. 만료 시각이 없으면(None) 항상 False — 보류 구간이 아닌 후보는 '지나지' 않는다."""
    if expires_at is None:
        _stamp(now, "지금 시각")
        return False
    return _stamp(now, "지금 시각") >= _stamp(expires_at, "검토 기한")


__all__ = ["CLEANUP_ERASES", "CLEANUP_REASON", "HISTORY_FIELDS", "HISTORY_FIELD_KO", "MAX_DAYS", "MAX_GENERATION", "RECREATED_PREFIX", "RELATION_RECREATED", "RecreationInput", "TOKEN_VERSION", "cleanup_token",
           "expiry_for", "history_row", "is_expired", "next_recreated_id", "recreation_input", "review_expires_at"]
