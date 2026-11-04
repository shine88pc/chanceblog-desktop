"""6항목 점수와 추천 구간, 시기 항목의 점수표(순수 계산 — 파일·네트워크·시계·난수 없음).

점수 = 여섯 항목(채널 적합도·작성 가능성·차별성·시기·근거·수익화, 각 0~100 정수)을 **그 채널의 가중치**로 가중 평균한 값이다.
**'모름'은 0점이 아니다** — 평가할 수 없는 항목(`None`)은 계산에서 빼고 남은 항목의 가중치를 100 으로 다시 나눈다(`content.suggest_score.combine` 과 같은 규칙, 시험이 같은 결과를 확인한다).
항목이 하나도 없으면 최종 점수도 없다(`None`, 추천 구간은 `UNRATED`) — 0점이 아니라 '점수 없음'이다.
**반올림 규칙은 이 파일의 `round_half_up` 한 곳이다**: 최종 점수는 정수이고 소수점 첫째 자리에서 반올림하되 0.5 는 올린다(79.5 → 80, 64.5 → 65, 49.5 → 50). 구간 경계는 이 정수에 적용한다.
추천 구간(`band_of`)은 작업 흐름 상태(NEW·REVIEW·SELECTED·HOLD·REJECTED)와 **다른 축**이다. 두 축에 모두 HOLD 라는 이름이 있다 — 작업 축의 HOLD 는 사람이 누른 보류이고 구간 축의 HOLD 는 점수 50~64 의 보류함이다.
이 점수는 기존 `content/suggest_score.py` 의 5요인 우선도(결정 D-29)와 별개이고 그것을 바꾸지 않는다. 기존 `search_demand` 같은 옛 칸은 읽지도 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import NamedTuple

from ..content.candidates import _invalid
from .channels import FACTOR_LABELS, FACTOR_NAMES, GRADE_CUTOFFS, TREND_USES, USE_NONE, USE_PRIMARY, ChannelProfile

# ---- 추천 구간(점수에서 계산 — 저장하지 않는다) -----------------------------------------------------------------------------------------
BAND_RECOMMENDED, BAND_GENERAL, BAND_HOLD, BAND_EXCLUDED, BAND_UNRATED = "RECOMMENDED", "GENERAL", "HOLD", "EXCLUDED", "UNRATED"
BANDS = (BAND_RECOMMENDED, BAND_GENERAL, BAND_HOLD, BAND_EXCLUDED, BAND_UNRATED)
BAND_KO = MappingProxyType({BAND_RECOMMENDED: "우선 추천", BAND_GENERAL: "일반 후보", BAND_HOLD: "보류함(점수 구간)", BAND_EXCLUDED: "제외", BAND_UNRATED: "점수 없음"})

# ---- 관심도(Trend) 상태와 자료 상태 -----------------------------------------------------------------------------------------------------
TREND_RISING, TREND_FLAT, TREND_FALLING, TREND_INSUFFICIENT = "rising", "flat", "falling", "insufficient"
TREND_STATUSES = (TREND_RISING, TREND_FLAT, TREND_FALLING, TREND_INSUFFICIENT)
DETERMINATE_TRENDS = (TREND_RISING, TREND_FLAT, TREND_FALLING)           # 상대값으로 방향을 말할 수 있는 상태(데이터 부족이 아닌 셋)
TREND_STATUS_KO = MappingProxyType({TREND_RISING: "상승", TREND_FLAT: "보통", TREND_FALLING: "하락", TREND_INSUFFICIENT: "데이터 부족"})
DATA_SUFFICIENT, DATA_PARTIAL, DATA_INSUFFICIENT, DATA_UNAVAILABLE = "sufficient", "partial", "insufficient", "unavailable"
DATA_STATUSES = (DATA_SUFFICIENT, DATA_PARTIAL, DATA_INSUFFICIENT, DATA_UNAVAILABLE)     # unavailable = 조회할 수 없었다(장애·한도), insufficient = 조회했지만 모자란다


def _point(value, item):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise _invalid(item, "0~100 사이의 정수이거나 비워 두어야 합니다(모르는 값은 0점이 아닙니다)")
    return value


@dataclass(frozen=True)
class Factors:
    """여섯 항목의 점수(각 0~100 정수, `None` = 평가 불가)."""
    channel_fit: int | None = None
    feasibility: int | None = None
    differentiation: int | None = None
    timing: int | None = None
    evidence: int | None = None
    monetization: int | None = None

    def __post_init__(self):
        for name in FACTOR_NAMES:
            _point(getattr(self, name), FACTOR_LABELS[name])

    def present(self):
        """평가할 수 있는 항목만 (이름, 점수) 로 — 항목 순서대로."""
        return tuple((name, getattr(self, name)) for name in FACTOR_NAMES if getattr(self, name) is not None)

    def to_dict(self):
        return {name: getattr(self, name) for name in FACTOR_NAMES}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(FACTOR_NAMES):
            raise _invalid("점수", "여섯 항목이 모두 있어야 하고 다른 칸은 쓸 수 없습니다")
        return cls(**data)


@dataclass(frozen=True)
class ScoreCard:
    """후보에 저장하는 점수 묶음 — 여섯 항목과 최종 점수. 모두 비어 있는 것(`ScoreCard()`)이 '점수 없음'이다."""
    factors: Factors = Factors()
    final: int | None = None

    def __post_init__(self):
        if not isinstance(self.factors, Factors):
            raise _invalid("점수", "여섯 항목 점수(Factors)여야 합니다")
        _point(self.final, "최종 점수")
        if self.final is not None:
            values = [value for _name, value in self.factors.present()]
            if not values:
                raise _invalid("최종 점수", "평가한 항목이 하나도 없는데 최종 점수가 있습니다")
            if not min(values) <= self.final <= max(values):
                raise _invalid("최종 점수", "여섯 항목의 가중 평균은 가장 낮은 항목과 가장 높은 항목 사이여야 합니다")

    @property
    def band(self):
        return band_of(self.final)

    def to_dict(self):
        return {**self.factors.to_dict(), "final": self.final}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {*FACTOR_NAMES, "final"}:
            raise _invalid("점수", "여섯 항목과 최종 점수(final)가 모두 있어야 하고 다른 칸은 쓸 수 없습니다")
        return cls(Factors.from_dict({name: data[name] for name in FACTOR_NAMES}), data["final"])


class Part(NamedTuple):
    name: str                                       # FACTOR_NAMES 중 하나
    value: int                                      # 항목 점수(0~100)
    weight: int                                     # 그 채널이 정한 가중치


@dataclass(frozen=True)
class Score:
    """`score()` 의 결과 — 최종 점수와 그 내역."""
    factors: Factors
    final: int | None                               # 최종 점수(정수) — 계산에 들어간 항목이 없으면 None
    parts: tuple                                    # 계산에 들어간 항목(`Part`) — 평가 불가 항목은 없다
    used_weight: int                                # 계산에 들어간 가중치의 합(0~100) — 이 값을 100 으로 다시 나눈다
    missing: tuple                                  # 평가 불가라 뺀 항목의 이름(항목 순서대로)

    @property
    def band(self):
        return band_of(self.final)

    @property
    def card(self):
        """후보에 저장할 모양(`ScoreCard`)."""
        return ScoreCard(self.factors, self.final)


def round_half_up(numerator, denominator):
    """분수를 소수점 첫째 자리에서 반올림(0.5 는 올림)한 정수 — 정수 계산이라 부동소수점 오차가 없다. 음수가 아닌 분자와 양수 분모만(79.5 → 80)."""
    return (2 * numerator + denominator) // (2 * denominator)


def score(profile, factors):
    """채널 프로필의 가중치로 여섯 항목 점수를 합친다. 평가 불가(None) 항목은 빼고 남은 가중치를 다시 나눈다 — 0점으로 치지 않는다."""
    if not isinstance(profile, ChannelProfile) or not isinstance(factors, Factors):
        raise TypeError("score(채널 프로필, 여섯 항목 점수) 로 불러야 한다")
    parts = tuple(Part(name, value, profile.weights[name]) for name, value in factors.present())
    missing = tuple(name for name in FACTOR_NAMES if getattr(factors, name) is None)
    used = sum(part.weight for part in parts)
    if not used:
        return Score(factors, None, parts, 0, missing)
    return Score(factors, round_half_up(sum(part.value * part.weight for part in parts), used), parts, used, missing)


def band_of(final):
    """최종 점수(정수 또는 None) → 추천 구간: 80 이상 우선 추천·65 이상 일반 후보·50 이상 보류함·그 아래 제외·점수 없음은 `UNRATED`."""
    if final is None:
        return BAND_UNRATED
    if not isinstance(final, int) or isinstance(final, bool) or not 0 <= final <= 100:
        raise ValueError("최종 점수는 0~100 사이의 정수이거나 None 이어야 한다")
    recommended, general, hold = GRADE_CUTOFFS
    if final >= recommended:
        return BAND_RECOMMENDED
    if final >= general:
        return BAND_GENERAL
    if final >= hold:
        return BAND_HOLD
    return BAND_EXCLUDED


# ---- 시기 항목: 캘린더 상태 × 관심도 상태 → 점수 ------------------------------------------------------------------------------------------
# 아래 숫자는 **초기값**이다(운영자가 나중에 조정). 원칙: 시점에 도달했고 관심도가 오르면 높게, 내리면 낮게. 관심도 자료가 없을 때는 0점이 아니라 캘린더만으로 정한 중간값을 쓰고
# '자료 부족'으로 표시한다. 캘린더에도 없고 관심도도 모르면 평가 불가(None)라 계산에서 빠진다.
CALENDAR_DUE, CALENDAR_OUT_OF_RANGE, CALENDAR_UNKNOWN = "due", "out_of_range", "unknown"      # 시점 도달·캘린더 범위 밖·캘린더에 없음(일정 모름)
CALENDAR_STATES = (CALENDAR_DUE, CALENDAR_OUT_OF_RANGE, CALENDAR_UNKNOWN)
TIMING_WITH_TREND = MappingProxyType({
    (CALENDAR_DUE, TREND_RISING): 90, (CALENDAR_DUE, TREND_FLAT): 70, (CALENDAR_DUE, TREND_FALLING): 40,
    (CALENDAR_OUT_OF_RANGE, TREND_RISING): 70, (CALENDAR_OUT_OF_RANGE, TREND_FLAT): 20, (CALENDAR_OUT_OF_RANGE, TREND_FALLING): 10,
    (CALENDAR_UNKNOWN, TREND_RISING): 70, (CALENDAR_UNKNOWN, TREND_FLAT): 50, (CALENDAR_UNKNOWN, TREND_FALLING): 30,
})
TIMING_CALENDAR_ONLY = MappingProxyType({CALENDAR_DUE: 60, CALENDAR_OUT_OF_RANGE: 20, CALENDAR_UNKNOWN: None})       # 관심도를 쓰지 않거나 쓸 수 없을 때


class Timing(NamedTuple):
    score: int | None                               # 시기 항목 점수(0~100) — 평가 불가면 None
    data_status: str                                # 시기 평가에 쓴 자료의 상태: sufficient·insufficient(관심도 데이터 부족)·unavailable(조회 불가)
    realtime: bool                                  # 캘린더 범위 밖인데 관심도가 오른다 — 실시간 후보로 표시
    trend_used: bool                                # 관심도 상태가 점수에 영향을 줬는가


def timing_score(calendar, trend_status, *, trend_use=USE_PRIMARY, outage=False):
    """시기 항목 점수. `calendar` 는 due·out_of_range·unknown, `trend_status` 는 rising·flat·falling·insufficient, `outage` 는 관심도를 조회할 수 없었다(장애·한도).
    `trend_use` 가 none 인 채널(Blogger 영문)은 관심도를 아예 쓰지 않고 캘린더만으로 정한다. 모르는 값은 ValueError."""
    if calendar not in CALENDAR_STATES or trend_status not in TREND_STATUSES or trend_use not in TREND_USES or not isinstance(outage, bool):
        raise ValueError("시기 점수의 입력이 올바르지 않다")
    if trend_use == USE_NONE:
        used, data_status = False, (DATA_INSUFFICIENT if calendar == CALENDAR_UNKNOWN else DATA_SUFFICIENT)
    elif outage:
        used, data_status = False, DATA_UNAVAILABLE
    elif trend_status == TREND_INSUFFICIENT:
        used, data_status = False, DATA_INSUFFICIENT
    else:
        used, data_status = True, DATA_SUFFICIENT
    points = TIMING_WITH_TREND[(calendar, trend_status)] if used else TIMING_CALENDAR_ONLY[calendar]
    realtime = used and calendar == CALENDAR_OUT_OF_RANGE and trend_status == TREND_RISING
    return Timing(points, data_status, realtime, used)


__all__ = [
    "BANDS", "BAND_EXCLUDED", "BAND_GENERAL", "BAND_HOLD", "BAND_KO", "BAND_RECOMMENDED", "BAND_UNRATED", "CALENDAR_DUE", "CALENDAR_OUT_OF_RANGE", "CALENDAR_STATES", "CALENDAR_UNKNOWN",
    "DATA_INSUFFICIENT", "DATA_PARTIAL", "DATA_STATUSES", "DATA_SUFFICIENT", "DATA_UNAVAILABLE", "DETERMINATE_TRENDS", "Factors", "Part", "Score", "ScoreCard", "TIMING_CALENDAR_ONLY",
    "TIMING_WITH_TREND", "TREND_FALLING", "TREND_FLAT", "TREND_INSUFFICIENT", "TREND_RISING", "TREND_STATUSES", "TREND_STATUS_KO", "Timing", "band_of", "round_half_up", "score", "timing_score",
]
