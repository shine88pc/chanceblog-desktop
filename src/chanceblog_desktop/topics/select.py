"""채널별 우수 후보 고르기 — 채널마다 기본 화면에 보일 상위 N 개(순수 계산: 입력을 바꾸지 않고, 같은 입력은 늘 같은 결과).

규칙: ① 우선 추천(80점 이상)을 점수 높은 순으로 훑되 같은 주제 묶음(`topic_cluster`)이 채널의 상한(`cluster_cap`)에 이미 찼으면 건너뛴다.
② N 개(`top_n`)에 못 미치면 일반 후보(65~79점)에서 같은 규칙으로 보충한다(묶음 개수는 두 단계가 이어서 센다).
③ 보류함(50~64점)·제외·점수 없음 후보로는 **억지로 채우지 않는다** — 모자라면 모자란 채로 두고 모자란 수(`shortfall`)만 알린다(한국어 안내문은 화면 층이 만든다).
④ 점수가 같으면 먼저 만든 후보가 앞이고 만든 시각도 같으면 후보 번호 순이다(결정적). 같은 번호의 후보가 두 번 들어 있어도 한 번만 쓴다.
⑤ 다른 채널의 후보는 거른다. 후보 생성이 꺼진 채널(`generation_enabled` 가 아님)은 빈 결과와 이유(`reason`)만 낸다.
작업 상태(`work_status`)는 보지 않는다 — 제외·보류한 후보를 빼는 일은 목록을 만들어 넘기는 쪽의 몫이다(추천 구간과 작업 상태는 다른 축이다).
"""
from __future__ import annotations

from dataclasses import dataclass

from .channels import ChannelProfile
from .model import TopicCandidate
from .score import BAND_GENERAL, BAND_RECOMMENDED

REASON_GENERATION_OFF = "generation_off"            # 이 채널은 후보 생성이 꺼져 있다


@dataclass(frozen=True)
class TopView:
    items: tuple                                    # 고른 후보(앞에서부터 보여 줄 순서)
    shortfall: int                                  # 모자란 수(top_n - 고른 수, 0 이상) — 후보 생성이 꺼진 채널은 0
    reason: str | None = None                       # 빈 까닭: None 이거나 `REASON_GENERATION_OFF`


def _order(candidate):
    return (-candidate.scores.final, candidate.created_at, candidate.candidate_id)


def top_view(candidates, profile):
    """`profile` 채널의 우수 후보를 고른다. `candidates` 는 엔진 후보의 묶음(어떤 채널이 섞여 있어도 된다) — 바꾸지 않는다."""
    if not isinstance(profile, ChannelProfile):
        raise TypeError("top_view(후보 묶음, 채널 프로필) 로 불러야 한다")
    pool = tuple(candidates)
    if not all(isinstance(item, TopicCandidate) for item in pool):
        raise TypeError("엔진 후보(TopicCandidate)만 넘길 수 있다")
    if not profile.generation_enabled:
        return TopView((), 0, REASON_GENERATION_OFF)
    mine = [item for item in pool if item.channel == profile.key]
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


__all__ = ["REASON_GENERATION_OFF", "TopView", "top_view"]
