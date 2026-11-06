"""기존 후보 수를 반영한 '남은 자리'(`remaining_slots`)와 '센 후보·안 센 후보'·'같은 후보' 판정(P3, 계획 11.1·결정 D-56·D-59 — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).

`remaining_slots = max(0, 목표 개수 − 활성 기존 후보 수 − 검토 대기 후보 수)` 이고 채널마다 따로 센다. 후보 한 건은 **한 번만** 센다 — 작업 상태(`work_status`)와 추천 구간(`recommendation_band`)은 다른 축이라
한 후보가 둘 다 해당할 수 있는데 그래도 한 건이다. 한 후보에 대해 아래 순서로 처음 맞는 줄이 이긴다(**제외하는 조건이 먼저**다).
  1) 작업 상태 REJECTED(사람이 제외)                       → 안 센다
  2) 추천 구간 EXCLUDED(0~49점)                            → 안 센다
  3) 보류(작업 상태 HOLD 이거나 구간 HOLD)인데 `hold.is_expired` 가 참(기한이 지남) → 안 센다(만료된 보류)
  4) 글 상태 DRAFTING·DRAFT_READY(호출하는 쪽이 `draft_states` 로 알려 준다 — 글 상태에서 계산하는 값이라 저장하지 않는다) → 센다(활성)
  5) 작업 상태 SELECTED                                    → 센다(활성)
  6) 유효한 보류(기한이 안 지났거나 기한이 없음)           → 센다(검토 대기)
  7) 구간 RECOMMENDED·GENERAL(작업 상태 NEW·REVIEW)        → 센다(활성)
  8) 구간 UNRATED(점수 없음)                               → 센다(검토 대기 — '모름' 을 0 점으로 보고 빼지 않는다)
'활성' 과 '검토 대기' 로 나누는 것은 설명용이고 남은 자리는 둘의 합으로 정한다(어느 쪽으로 세든 같다). 이 나눔은 **초기값 — 전략 원문 확인 전**이다.

**같은 후보**는 번호만 보지 않는다: ① 후보 번호가 같다 ② 채널과 `normalized_topic_hash`(주제 글의 `keyword_key` 를 `expand.stable_id` 로 해시)가 같다 ③ 채널·씨앗 번호·검색 의도·관점이 모두 같다(씨앗 번호가 없는 후보끼리는
'모름 = 모름' 으로 같다고 보지 않는다). 같은 후보 여럿이 저장돼 있어도 한 번만 세고, 그 묶음 안에 사람이 제외한(REJECTED)·구간 제외(EXCLUDED) 후보가 있으면 묶음 전체를 안 센다(제외가 이긴다).
기한이 지난 보류만 있는 묶음은 안 센다. 센 후보가 둘 이상이면 활성이 검토 대기보다 먼저다. 이 모듈은 아무것도 지우거나 바꾸지 않는다 — 센 결과만 돌려준다.
"""
from __future__ import annotations

from typing import NamedTuple

from ..content.candidates import HOLD, REJECTED, SELECTED, keyword_key
from . import hold
from .expand import stable_id
from .model import TopicCandidate
from .score import BAND_EXCLUDED, BAND_GENERAL, BAND_HOLD, BAND_RECOMMENDED, BAND_UNRATED

DRAFTING, DRAFT_READY = "DRAFTING", "DRAFT_READY"
DRAFT_STATES = (DRAFTING, DRAFT_READY)                         # 글(프로젝트)의 상태에서 계산하는 값 — 후보에 저장하지 않고 호출하는 쪽이 번호별로 알려 준다
KIND_ACTIVE, KIND_PENDING = "active", "pending_review"
KINDS = (KIND_ACTIVE, KIND_PENDING)

# 센 이유(활성·검토 대기)와 안 센 이유 — 코드의 이름. 화면 글은 `REASON_KO` 로만 만든다.
WHY_DRAFTING, WHY_DRAFT_READY, WHY_SELECTED, WHY_HOLD, WHY_RECOMMENDED, WHY_GENERAL, WHY_UNRATED = "drafting", "draft_ready", "selected", "hold", "recommended", "general", "unrated"
WHY_REJECTED, WHY_EXCLUDED, WHY_EXPIRED, WHY_DUPLICATE = "rejected", "excluded", "expired_hold", "duplicate"
COUNTED_REASONS = (WHY_DRAFTING, WHY_DRAFT_READY, WHY_SELECTED, WHY_RECOMMENDED, WHY_GENERAL, WHY_HOLD, WHY_UNRATED)
IGNORED_REASONS = (WHY_REJECTED, WHY_EXCLUDED, WHY_EXPIRED, WHY_DUPLICATE)
REASONS = COUNTED_REASONS + IGNORED_REASONS
REASON_KO = {WHY_DRAFTING: "초안을 쓰는 중", WHY_DRAFT_READY: "초안이 준비됨", WHY_SELECTED: "선택됨", WHY_HOLD: "보류 중(기한 안)", WHY_RECOMMENDED: "우선 추천", WHY_GENERAL: "일반 후보",
             WHY_UNRATED: "점수 없음(검토 대기)", WHY_REJECTED: "사람이 제외함", WHY_EXCLUDED: "점수가 제외 구간", WHY_EXPIRED: "보류 기한이 지남", WHY_DUPLICATE: "같은 후보가 이미 세어짐"}
MAX_COUNT = 1_000_000                                          # 목표·개수의 상한(실수로 아주 큰 값을 넣지 않게)


class Verdict(NamedTuple):
    counted: bool                                              # 자리를 차지하는가
    kind: str | None                                           # 센 후보면 active·pending_review, 아니면 None
    why: str                                                   # `REASONS` 중 하나


class Slots(NamedTuple):
    target: int                                                # 목표 개수
    active_existing: int                                       # 활성 기존 후보 수
    pending_review: int                                        # 검토 대기 후보 수
    remaining: int                                             # 남은 자리 = max(0, 목표 − 활성 − 대기)
    ignored: tuple                                             # ((이유, 수), …) — 안 센 후보(같은 후보로 묶여 한 번만 센 중복 포함), `IGNORED_REASONS` 순서
    verdicts: tuple                                            # ((후보 번호, Verdict), …) — 들어온 순서, 후보마다 하나


def _count(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_COUNT:
        raise ValueError(f"{name} 는 0~{MAX_COUNT} 사이의 정수여야 한다")
    return value


def remaining_slots(target, active_existing, pending_review):
    """`max(0, 목표 − 활성 기존 후보 − 검토 대기 후보)`. 세 값은 0 이상의 정수여야 하고(참·거짓 불가) 음수가 되지 않는다."""
    return max(0, _count(target, "목표 개수") - _count(active_existing, "활성 기존 후보 수") - _count(pending_review, "검토 대기 후보 수"))


def normalized_topic_hash(topic):
    """주제 글 → 같은 주제인지 비교하는 해시(`expand.stable_id(keyword_key(주제))` 16자리). 글자·숫자가 하나도 없는 글은 None(모름 — 같다고 보지 않는다)."""
    if not isinstance(topic, str):
        raise TypeError("주제는 글이어야 한다")
    key = keyword_key(topic)
    return stable_id(key) if key else None


def _check_pool(candidates):
    if isinstance(candidates, (str, bytes)) or not hasattr(candidates, "__iter__"):
        raise TypeError("후보 목록(TopicCandidate 의 목록)을 넘겨야 한다")
    pool = tuple(candidates)
    if not all(isinstance(item, TopicCandidate) for item in pool):
        raise TypeError("엔진 후보(TopicCandidate)만 넘길 수 있다")
    return pool


def same_candidate(first, second):
    """같은 후보인가 — ① 번호가 같다 ② 같은 채널이고 주제 해시가 같다(해시를 못 만드는 주제는 비교하지 않는다) ③ 같은 채널이고 씨앗 번호가 있고 씨앗 번호·검색 의도·관점이 모두 같다."""
    if not isinstance(first, TopicCandidate) or not isinstance(second, TopicCandidate):
        raise TypeError("엔진 후보(TopicCandidate)여야 한다")
    if first.candidate_id == second.candidate_id:
        return True
    if first.channel != second.channel:
        return False
    hashed = normalized_topic_hash(first.topic)
    if hashed is not None and hashed == normalized_topic_hash(second.topic):
        return True
    return first.seed_id is not None and (first.seed_id, first.search_intent, first.topic_angle) == (second.seed_id, second.search_intent, second.topic_angle)


def find_same(candidate, pool):
    """`pool` 에서 `candidate` 와 같은 후보들의 번호(들어온 순서). 자기 자신(같은 번호)도 같은 후보다."""
    return tuple(item.candidate_id for item in _check_pool(pool) if same_candidate(candidate, item))


def sameness_keys(candidate):
    """후보 한 건의 '같은 후보' 열쇠들 — 두 후보가 열쇠를 하나라도 나눠 가지면 `same_candidate` 가 참이다(같은 후보 3규칙과 정확히 같다): ① 번호(채널과 무관) ② 채널+주제 해시(해시를 못 만드는 주제는 없음)
    ③ 채널+씨앗 번호+검색 의도+관점(씨앗 번호가 없으면 없음 — 모름 = 모름 으로 같다고 보지 않는다). 후보가 많아도 쌍마다 견주지 않고 열쇠로 묶으려고 있다(P3 수정 1차, D-71)."""
    if not isinstance(candidate, TopicCandidate):
        raise TypeError("엔진 후보(TopicCandidate)여야 한다")
    keys = [("id", candidate.candidate_id)]
    hashed = normalized_topic_hash(candidate.topic)
    if hashed is not None:
        keys.append(("topic", candidate.channel, hashed))
    if candidate.seed_id is not None:
        keys.append(("seed", candidate.channel, candidate.seed_id, candidate.search_intent, candidate.topic_angle))
    return tuple(keys)


def group_same(candidates):
    """같은 후보끼리 묶는다 → 묶음(후보 번호 튜플)의 튜플. 묶음은 첫 후보가 나온 순서이고 안의 순서는 들어온 순서다. 'A 와 B 가 같고 B 와 C 가 같으면' 셋이 한 묶음이다.
    열쇠(`sameness_keys`) 사전으로 묶어 후보 수에 거의 비례해서 걸린다(쌍마다 견주던 옛 구현은 후보 1,000개에서 약 10초 — 같은 결과임은 시험이 무작위 입력으로 옛 구현과 견준다)."""
    pool = _check_pool(candidates)
    parent = list(range(len(pool)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    first_with = {}
    for index, item in enumerate(pool):
        for key in sameness_keys(item):
            earlier = first_with.setdefault(key, index)
            if earlier != index:
                parent[root(index)] = root(earlier)
    groups = {}
    for index, item in enumerate(pool):
        groups.setdefault(root(index), []).append(item.candidate_id)
    return tuple(tuple(ids) for ids in groups.values())


def classify(candidate, now, *, draft_state=None):
    """후보 한 건이 자리를 차지하는가 → `Verdict`. `now` 는 UTC 시각 글(`YYYY-MM-DDTHH:MM:SSZ`), `draft_state` 는 None 이거나 DRAFTING·DRAFT_READY(글 상태에서 계산한 값)."""
    if not isinstance(candidate, TopicCandidate):
        raise TypeError("엔진 후보(TopicCandidate)여야 한다")
    if draft_state is not None and (not isinstance(draft_state, str) or draft_state not in DRAFT_STATES):
        raise ValueError("글 상태는 " + ", ".join(DRAFT_STATES) + " 중 하나이거나 None 이어야 한다")
    band, status = candidate.recommendation_band, candidate.work_status
    expired = hold.is_expired(candidate.review_expires_at, now)                         # 만료 시각이 없으면 거짓 — 시각 모양이 틀리면 여기서 오류
    held = status == HOLD or band == BAND_HOLD
    if status == REJECTED:
        return Verdict(False, None, WHY_REJECTED)
    if band == BAND_EXCLUDED:
        return Verdict(False, None, WHY_EXCLUDED)
    if held and expired:
        return Verdict(False, None, WHY_EXPIRED)
    if draft_state == DRAFTING:
        return Verdict(True, KIND_ACTIVE, WHY_DRAFTING)
    if draft_state == DRAFT_READY:
        return Verdict(True, KIND_ACTIVE, WHY_DRAFT_READY)
    if status == SELECTED:
        return Verdict(True, KIND_ACTIVE, WHY_SELECTED)
    if held:
        return Verdict(True, KIND_PENDING, WHY_HOLD)
    if band == BAND_RECOMMENDED:
        return Verdict(True, KIND_ACTIVE, WHY_RECOMMENDED)
    if band == BAND_GENERAL:
        return Verdict(True, KIND_ACTIVE, WHY_GENERAL)
    if band == BAND_UNRATED:
        return Verdict(True, KIND_PENDING, WHY_UNRATED)
    raise ValueError("모르는 추천 구간이다: " + str(band))


def _group_verdict(verdicts):
    """같은 후보 묶음의 한 판정 — 제외가 이기고(사람 제외 → 구간 제외), 그다음 센 것 중 활성이 먼저이며(들어온 순서), 센 것이 없으면 만료된 보류다."""
    for why in (WHY_REJECTED, WHY_EXCLUDED):
        found = next((item for item in verdicts if item.why == why), None)
        if found is not None:
            return found
    for kind in KINDS:
        found = next((item for item in verdicts if item.counted and item.kind == kind), None)
        if found is not None:
            return found
    return verdicts[0]


def count_slots(candidates, target, now, *, draft_states=None):
    """한 채널의 기존 후보들로 남은 자리를 센다 → `Slots`. `candidates` 는 **한 채널의** 엔진 후보 목록이어야 한다(다른 채널이 섞이면 `ValueError` — 채널마다 따로 센다).
    `draft_states` 는 {후보 번호: DRAFTING·DRAFT_READY} 또는 None. 같은 후보는 한 번만 세고(묶음의 판정은 첫 후보에 적고, 나머지는 안 센 이유 `duplicate` 로 적는다)."""
    pool = _check_pool(candidates)
    _count(target, "목표 개수")
    if len({item.channel for item in pool}) > 1:
        raise ValueError("채널마다 따로 세야 한다 — 한 채널의 후보만 넘긴다")
    states = {} if draft_states is None else draft_states
    if not isinstance(states, dict) or not all(isinstance(key, str) and (value is None or value in DRAFT_STATES) for key, value in states.items()):
        raise ValueError("draft_states 는 {후보 번호: DRAFTING·DRAFT_READY} 사전이어야 한다")
    own = {item.candidate_id: classify(item, now, draft_state=states.get(item.candidate_id)) for item in pool}
    active = pending = 0
    ignored = {why: 0 for why in IGNORED_REASONS}
    verdicts = {}
    for group in group_same(pool):
        group_verdict = _group_verdict([own[key] for key in group])
        for position, key in enumerate(group):
            if position == 0:
                verdicts[key] = group_verdict
                if group_verdict.counted:
                    active += group_verdict.kind == KIND_ACTIVE
                    pending += group_verdict.kind == KIND_PENDING
                else:
                    ignored[group_verdict.why] += 1
            else:
                verdicts[key] = Verdict(False, None, WHY_DUPLICATE)
                ignored[WHY_DUPLICATE] += 1
    return Slots(target, active, pending, remaining_slots(target, active, pending), tuple((why, ignored[why]) for why in IGNORED_REASONS if ignored[why]),
                 tuple((item.candidate_id, verdicts[item.candidate_id]) for item in pool))


__all__ = [
    "COUNTED_REASONS", "DRAFTING", "DRAFT_READY", "DRAFT_STATES", "IGNORED_REASONS", "KINDS", "KIND_ACTIVE", "KIND_PENDING", "MAX_COUNT", "REASONS", "REASON_KO", "Slots", "Verdict", "WHY_DRAFTING",
    "WHY_DRAFT_READY", "WHY_DUPLICATE", "WHY_EXCLUDED", "WHY_EXPIRED", "WHY_GENERAL", "WHY_HOLD", "WHY_RECOMMENDED", "WHY_REJECTED", "WHY_SELECTED", "WHY_UNRATED", "classify", "count_slots", "find_same",
    "group_same", "normalized_topic_hash", "remaining_slots", "same_candidate", "sameness_keys",
]
