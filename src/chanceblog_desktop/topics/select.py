"""채널별 우수 후보 고르기 — 채널마다 기본 화면에 보일 상위 N 개(순수 계산: 입력을 바꾸지 않고, 같은 입력은 늘 같은 결과).

규칙: ① 우선 추천(80점 이상)을 점수 높은 순으로 훑되 같은 주제 묶음(`topic_cluster`)이 채널의 상한(`cluster_cap`)에 이미 찼으면 건너뛴다.
② N 개(`top_n`)에 못 미치면 일반 후보(65~79점)에서 같은 규칙으로 보충한다(묶음 개수는 두 단계가 이어서 센다).
③ 보류함(50~64점)·제외·점수 없음 후보로는 **억지로 채우지 않는다** — 모자라면 모자란 채로 두고 모자란 수(`shortfall`)만 알린다(한국어 안내문은 화면 층이 만든다).
④ 점수가 같으면 먼저 만든 후보가 앞이고 만든 시각도 같으면 후보 번호 순이다(결정적). 같은 번호의 후보가 두 번 들어 있어도 한 번만 쓴다.
⑤ 다른 채널의 후보는 거른다. 후보 생성이 꺼진 채널(`generation_enabled` 가 아님)은 빈 결과와 이유(`reason`)만 낸다.
⑥ **작업 상태(`work_status`)로 숨기는 것이 기본값이다**(P2a, 결정 D-43): 사람이 '제외'(REJECTED)·'보류'(HOLD)한 후보는 점수가 높아도 우수 후보에 올리지 않는다 — 호출하는 쪽이 거르는 일을 깜빡해도 운영자가 뺀 글이
다시 맨 위에 뜨지 않게 한다(추천 구간과 작업 상태는 다른 축이지만, 사람의 '빼기' 는 점수보다 우선한다). 숨길 상태는 `hide_work_status` 로 바꿀 수 있고 빈 목록(`()`)이면 작업 상태를 보지 않는다.
숨긴 뒤 모자란 수(`shortfall`)는 숨긴 후보를 빼고 센다 — 숨겼다고 다른 후보가 억지로 끼어들지는 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..content.candidates import HOLD, REJECTED, STATUSES
from .channels import ChannelProfile
from .model import TopicCandidate
from .score import BAND_GENERAL, BAND_RECOMMENDED

REASON_GENERATION_OFF = "generation_off"            # 이 채널은 후보 생성이 꺼져 있다
HIDDEN_WORK_STATUSES = (REJECTED, HOLD)             # 우수 후보에서 기본으로 숨기는 작업 상태 — 사람이 제외·보류한 후보(여기의 HOLD 는 작업 상태이고 점수 구간 HOLD(50~64점)와 다른 축이다)


@dataclass(frozen=True)
class TopView:
    items: tuple                                    # 고른 후보(앞에서부터 보여 줄 순서)
    shortfall: int                                  # 모자란 수(top_n - 고른 수, 0 이상) — 후보 생성이 꺼진 채널은 0
    reason: str | None = None                       # 빈 까닭: None 이거나 `REASON_GENERATION_OFF`


def _order(candidate):
    return (-candidate.scores.final, candidate.created_at, candidate.candidate_id)


def _hidden(statuses):
    """`hide_work_status` 를 검사해 튜플로 — 문자열 하나가 아니라 작업 상태(`content.candidates.STATUSES`)의 목록이어야 한다."""
    if isinstance(statuses, (str, bytes)) or not hasattr(statuses, "__iter__"):
        raise TypeError("hide_work_status 는 작업 상태의 목록이어야 한다(예: ('REJECTED', 'HOLD'), 숨기지 않으려면 ())")
    names = tuple(statuses)
    unknown = [name for name in names if not isinstance(name, str) or name not in STATUSES]
    if unknown:
        raise ValueError(f"모르는 작업 상태 {unknown!r} — 다음 중에서 골라야 한다: " + ", ".join(STATUSES))
    return names


def top_view(candidates, profile, *, hide_work_status=HIDDEN_WORK_STATUSES):
    """`profile` 채널의 우수 후보를 고른다. `candidates` 는 엔진 후보의 묶음(어떤 채널이 섞여 있어도 된다) — 바꾸지 않는다.
    `hide_work_status`(기본 제외·보류)에 든 작업 상태의 후보는 점수와 상관없이 올리지 않는다 — 풀려면 `()` 를 넘긴다."""
    if not isinstance(profile, ChannelProfile):
        raise TypeError("top_view(후보 묶음, 채널 프로필) 로 불러야 한다")
    hidden = _hidden(hide_work_status)
    pool = tuple(candidates)
    if not all(isinstance(item, TopicCandidate) for item in pool):
        raise TypeError("엔진 후보(TopicCandidate)만 넘길 수 있다")
    if not profile.generation_enabled:
        return TopView((), 0, REASON_GENERATION_OFF)
    mine = [item for item in pool if item.channel == profile.key and item.work_status not in hidden]
    chosen, per_cluster, seen = [], {}, set()
    for band in (BAND_RECOMMENDED, BAND_GENERAL):
        for item in sorted((item for item in mine if item.recommendation_band == band), key=_order):
            if len(chosen) >= profile.top_n:
                break
            if item.candidate_id in seen or per_cluster.get(item.topic_cluster, 0) >= profile.cluster_cap:
                continue
            chosen.append(item)
            seen.add(item.candidate_id)
            per_cluster[item.topic_cluster] = per_cluster.get(item.topic_cluster, 0) + 1
    return TopView(tuple(chosen), profile.top_n - len(chosen))


__all__ = ["HIDDEN_WORK_STATUSES", "REASON_GENERATION_OFF", "TopView", "top_view"]
