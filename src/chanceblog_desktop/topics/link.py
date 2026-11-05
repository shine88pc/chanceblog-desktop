"""엔진 후보를 기존 후보·초안으로 이어 줄 **연결**(`CandidateLink`)과 **출처 스냅샷**(`Provenance`) — 순수 자료형(저장·변환은 다음 묶음).

기존 `content.candidates.Candidate` 는 모르는 칸을 거절하므로 연결과 출처는 엔진 쪽 저장소(연결 표)에 두고 초안 계획을 만들 때 서비스 층이 붙인다.
- `CandidateLink`: 엔진 후보 번호·기존 후보 번호·초안 계획 번호·원천 주제 번호·씨앗 번호·채널 — 기존 후보로 옮기고 초안을 만들어도 서로를 찾아갈 수 있게 한다. 기존 후보 번호와 초안 계획 번호는 옮기기 전·계획 전에는 비어 있다.
  (`draft_plan_id` 의 정의 — 지금은 초안 계획을 저장하지 않으므로 '계획 입력의 안정된 식별자'를 어떻게 만들지 — 는 다음 묶음에서 정한다. 여기서는 번호 모양만 검사한다.)
- `Provenance`: 새 점수(여섯 항목·최종·추천 구간)·선정 이유·관심도 상태와 그 기준·자료 상태·씨앗 출처가 초안 단계에서 **유실되지 않게** 그 시점의 값을 그대로 담은 스냅샷이다. 후보가 나중에 바뀌어도 스냅샷은 바뀌지 않는다.
후보의 모든 값은 스냅샷에 '담는다'(`Provenance` 의 칸) 아니면 '담지 않는다'(`NOT_CARRIED` 와 그 까닭) 둘 중 하나다 — 새 칸이 생기면 어느 쪽인지 정하지 않으면 시험이 실패한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from ..content.candidates import _invalid
from . import wording
from .model import LABELS, MAX_REASONS, SOURCE_TYPES, TopicCandidate, _channel, _choice, _optional_id, _texts, check_trend, stored_id
from .score import BAND_KO, BANDS, DATA_STATUSES, ScoreCard, band_of

SCHEMA = 1
LINK_FIELD_KO = MappingProxyType({"engine_candidate_id": "엔진 후보 번호", "legacy_candidate_id": "기존 후보 번호", "draft_plan_id": "초안 계획 번호", **LABELS})        # 칸 이름 → 쉬운 한국어(오류 안내용)

# 스냅샷에 담지 않는 후보의 값과 그 까닭(어디에 있는지) — '새 칸을 빠뜨리지 않기' 시험이 이 목록과 `Provenance` 의 칸이 후보의 모든 값을 남김없이 나눠 갖는지 확인한다.
NOT_CARRIED = MappingProxyType({
    "candidate_id": "연결(CandidateLink)이 엔진 후보 번호로 가진다",
    "language": "채널에서 정해지는 값이다",
    "topic": "기존 후보의 '추천 포스팅 주제' 칸으로 옮겨진다",
    "primary_keyword": "기존 후보의 '핵심 키워드' 칸으로 옮겨진다",
    "secondary_keywords": "기존 후보의 '보조 키워드' 칸으로 옮겨진다",
    "candidate_type": "엔진 보관함이 가진다 — 초안에 필요하면 다음 묶음에서 스냅샷에 더한다(열린 항목)",
    "search_intent": "초안 계획이 따로 계산한다 — 초안에 필요하면 다음 묶음에서 스냅샷에 더한다(열린 항목)",
    "content_type": "기존 후보의 '추천 글 유형' 으로 옮겨진다(`model.to_post_type`)",
    "topic_cluster": "엔진 보관함이 가진다 — 초안에 필요하면 다음 묶음에서 스냅샷에 더한다(열린 항목)",
    "topic_angle": "엔진 보관함이 가진다 — 초안에 필요하면 다음 묶음에서 스냅샷에 더한다(열린 항목)",
    "target_reader": "엔진 보관함이 가진다 — 초안에 필요하면 다음 묶음에서 스냅샷에 더한다(열린 항목)",
    "search_demand_count": "기존 후보의 옛 검색 수요 칸으로 옮기지 않는다(출처가 분명한 값을 사람이 명시적으로 옮기는 길은 따로 정한다)",
    "search_count_source": "실제 검색 횟수와 함께 엔진 보관함에만 있다",
    "duplicate_status": "엔진 보관함이 가진다(중복 판정은 후보 단계의 일이다)",
    "similar_post_ids": "엔진 보관함이 가진다(중복 판정은 후보 단계의 일이다)",
    "monetization_tags": "엔진 보관함이 가진다 — 협찬 고지를 만드는 묶음에서 필요하면 스냅샷에 더한다(열린 항목)",
    "safety_flags": "엔진 보관함이 가진다 — 협찬 고지 문구를 만드는 묶음(P6)에서 필요하면 스냅샷에 더한다(열린 항목)",
    "processing_errors": "처리 중 문제는 엔진 보관함에 남기고 초안으로 넘기지 않는다",
    "work_status": "다른 축이다 — 기존 후보의 작업 상태가 따로 있다",
    "created_at": "기존 후보가 자기 만든 시각을 가진다",
    "review_expires_at": "엔진 보관함이 가진다(보류함 기한)",
})


@dataclass(frozen=True, kw_only=True)
class CandidateLink:
    engine_candidate_id: str                            # 엔진 후보 번호(`TopicCandidate.candidate_id`)
    legacy_candidate_id: str | None                     # 기존 후보로 옮긴 뒤의 번호(옮기기 전에는 None)
    draft_plan_id: str | None                           # 초안 계획 번호(계획을 만들기 전에는 None)
    source_topic_id: str | None
    seed_id: str | None
    channel: str                                        # 채널 코드 키

    def __post_init__(self):
        stored_id(self.engine_candidate_id, "엔진 후보 번호")
        _optional_id(self.legacy_candidate_id, "기존 후보 번호")
        _optional_id(self.draft_plan_id, "초안 계획 번호")
        _optional_id(self.source_topic_id, LABELS["source_topic_id"])
        _optional_id(self.seed_id, LABELS["seed_id"])
        _channel(self.channel)

    @classmethod
    def of(cls, candidate, *, legacy_candidate_id=None, draft_plan_id=None):
        """엔진 후보에서 만든 연결 — 후보에 있는 값(번호·원천 주제·씨앗·채널)은 그대로 옮기고, 기존 후보 번호·초안 계획 번호는 나중에 붙는다."""
        if not isinstance(candidate, TopicCandidate):
            raise TypeError("엔진 후보(TopicCandidate)여야 한다")
        return cls(engine_candidate_id=candidate.candidate_id, legacy_candidate_id=legacy_candidate_id, draft_plan_id=draft_plan_id, source_topic_id=candidate.source_topic_id,
                   seed_id=candidate.seed_id, channel=candidate.channel)

    def to_dict(self):
        return {"schema": SCHEMA, "engine_candidate_id": self.engine_candidate_id, "legacy_candidate_id": self.legacy_candidate_id, "draft_plan_id": self.draft_plan_id,
                "source_topic_id": self.source_topic_id, "seed_id": self.seed_id, "channel": self.channel}

    @classmethod
    def from_dict(cls, data):
        """엄격하게 읽는다 — `schema` 1 과 정확히 이 칸들(값이 없으면 None 을 적는다)."""
        return cls(**_strict(data, ("engine_candidate_id", "legacy_candidate_id", "draft_plan_id", "source_topic_id", "seed_id", "channel"), "연결 저장 형식"))


def _strict(data, names, item):
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != SCHEMA:
        raise _invalid(item, f"{wording.FILE_KEY_KO['schema']}가 {SCHEMA}인 연결이 아닙니다", detail="저장된 모양(schema 1)이 아닙니다")
    unknown, missing = sorted(map(str, set(data) - {"schema", *names})), sorted({*names} - set(data))
    if unknown or missing:
        raise _invalid(item, wording.unknown_and_missing(unknown, missing, LINK_FIELD_KO), detail=f"모르는 칸 {unknown}, 빠진 칸 {missing}")
    return {name: data[name] for name in names}


@dataclass(frozen=True, kw_only=True)
class Provenance:
    scores: ScoreCard                                   # 여섯 항목 + 최종 점수
    recommendation_band: str                            # 그 점수의 추천 구간(점수와 어긋나면 거절)
    selection_reasons: tuple                            # 선정 이유
    trend_status: str
    trend_ratio: int | None
    trend_period: str | None
    trend_compared_group: tuple
    trend_queried_on: str | None
    data_status: str
    seed_id: str | None                                 # 씨앗 출처
    source_type: str                                    # 후보가 생긴 경로
    source_topic_id: str | None
    channel: str

    def __post_init__(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        if not isinstance(self.scores, ScoreCard):
            raise _invalid(LABELS["scores"], "점수 묶음(ScoreCard)이어야 합니다")
        _choice(self.recommendation_band, BANDS, LABELS["recommendation_band"], BAND_KO)
        if self.recommendation_band != band_of(self.scores.final):
            raise _invalid(LABELS["recommendation_band"], "최종 점수에서 계산한 구간과 다릅니다")
        put("selection_reasons", _texts(self.selection_reasons, LABELS["selection_reasons"], count=MAX_REASONS))
        _status, _ratio, period, group, _queried = check_trend(self.trend_status, self.trend_ratio, self.trend_period, self.trend_compared_group, self.trend_queried_on)
        put("trend_period", period)
        put("trend_compared_group", group)
        _choice(self.data_status, DATA_STATUSES, LABELS["data_status"], wording.DATA_STATUS_KO)
        _optional_id(self.seed_id, LABELS["seed_id"])
        _choice(self.source_type, SOURCE_TYPES, LABELS["source_type"], wording.SOURCE_TYPE_KO)
        _optional_id(self.source_topic_id, LABELS["source_topic_id"])
        _channel(self.channel)

    @classmethod
    def of(cls, candidate):
        """엔진 후보의 이 값들을 그대로 담은 스냅샷(구간은 후보의 점수에서 계산한 값)."""
        if not isinstance(candidate, TopicCandidate):
            raise TypeError("엔진 후보(TopicCandidate)여야 한다")
        return cls(scores=candidate.scores, recommendation_band=candidate.recommendation_band, selection_reasons=candidate.selection_reasons, trend_status=candidate.trend_status,
                   trend_ratio=candidate.trend_ratio, trend_period=candidate.trend_period, trend_compared_group=candidate.trend_compared_group,
                   trend_queried_on=candidate.trend_queried_on, data_status=candidate.data_status, seed_id=candidate.seed_id, source_type=candidate.source_type,
                   source_topic_id=candidate.source_topic_id, channel=candidate.channel)

    def to_dict(self):
        return {"schema": SCHEMA, "scores": self.scores.to_dict(), "recommendation_band": self.recommendation_band, "selection_reasons": list(self.selection_reasons),
                "trend_status": self.trend_status, "trend_ratio": self.trend_ratio, "trend_period": self.trend_period, "trend_compared_group": list(self.trend_compared_group),
                "trend_queried_on": self.trend_queried_on, "data_status": self.data_status, "seed_id": self.seed_id, "source_type": self.source_type,
                "source_topic_id": self.source_topic_id, "channel": self.channel}

    @classmethod
    def from_dict(cls, data):
        """엄격하게 읽는다 — `schema` 1 과 정확히 이 칸들(스냅샷은 빠짐이 없어야 하므로 값이 없는 칸도 None·빈 목록으로 적는다)."""
        names = ("scores", "recommendation_band", "selection_reasons", "trend_status", "trend_ratio", "trend_period", "trend_compared_group", "trend_queried_on", "data_status",
                 "seed_id", "source_type", "source_topic_id", "channel")
        values = _strict(data, names, "출처 스냅샷 저장 형식")
        values["scores"] = ScoreCard.from_dict(values["scores"])
        return cls(**values)


__all__ = ["CandidateLink", "LINK_FIELD_KO", "NOT_CARRIED", "Provenance", "SCHEMA"]
