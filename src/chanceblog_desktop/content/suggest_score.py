"""콘텐츠 작성 우선도·키워드 기회도 **계산 틀** — 가중치·구간·경계값을 모두 이 파일의 상수로 **그대로 공개**한다(시험이 값을 못박고, 문서 `docs/DECISIONS.md`·`docs/ARCHITECTURE.md` §9 가 같은 값을 적는다).
순수 계산이다 — 파일·네트워크·현재 시각을 쓰지 않는다(날짜는 인자로 받는다).

점수는 **이 프로그램이 가진 정보로 정한 작성 순서의 참고값(0~100)** 이다 — 검색 결과·노출·방문자 수를 약속하지 않고 그렇게 읽히게 쓰지도 않는다. 쓰는 이름은 '콘텐츠 작성 우선도'·'키워드 기회도'·'블로그 프로필 적합도'·'최근 관심도 변화'·'관련 블로그 검색 결과 수' 뿐이다.

**콘텐츠 작성 우선도** = 다섯 요인의 가중 평균: 블로그 프로필 적합도(`fit`)·시기 적합(`season`)·신선도(`freshness`)·주제 균형(`balance`)·키워드 기회도(`opportunity`).
앞의 네 요인은 프로필·기존 글·달력만으로 늘 계산된다. **키워드 기회도는 외부 지표(월간 검색 수요·관련 블로그 검색 결과 수·최근 관심도 변화)가 하나라도 있을 때만 계산**하고, 없으면 그 요인을 빼고
나머지 가중치를 다시 나눈다 — '데이터 없음' 을 0점으로 치지 않는다(`combine`).
**키워드 기회도** = 세 하위 점수의 가중 평균(역시 없는 것은 빼고 다시 나눈다): 월간 검색 수요(많을수록 ↑, 로그 눈금)·관련 블로그 검색 결과 수(많을수록 경쟁이 커서 ↓, 로그 눈금)·최근 관심도 변화(상승 100·보합 50·하락 0).
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import NamedTuple

from . import suggest_text as text
from .suggest_data import SEASONS

# ---- 우선도 요인과 가중치(합 100) ------------------------------------------------------------------------------------------------
FACTORS = ("fit", "season", "freshness", "balance", "opportunity")
WEIGHTS = {"fit": 30, "season": 20, "freshness": 20, "balance": 15, "opportunity": 15}
FACTOR_NAMES = {"fit": "블로그 프로필 적합도", "season": "시기 적합", "freshness": "신선도", "balance": "주제 균형", "opportunity": "키워드 기회도"}
FACTOR_HELP = {"fit": "프로필의 주제·카테고리·기본 태그와 맞는 정도", "season": "이번 달 시기와 맞는 정도", "freshness": "기존 글과 겹치지 않는 정도",
               "balance": "아직 덜 다룬 주제인 정도", "opportunity": "검색 수요·경쟁·관심도 변화(외부 지표가 있을 때만)"}

# ---- 구간 ---------------------------------------------------------------------------------------------------------------------
HIGH_FROM = 70                      # 이 점수 이상이면 '높음'
MID_FROM = 40                       # 이 점수 이상이면 '보통', 아래는 '낮음'
HIGH, MID, LOW = "높음", "보통", "낮음"

# ---- 블로그 프로필 적합도 ----------------------------------------------------------------------------------------------------------
SEED_STRENGTH = {"주제": 90, "카테고리": 75, "태그": 60}     # 씨앗이 프로필의 어디에서 왔나 — 주제가 가장 강하다
TYPE_BONUS = 10                     # 글 유형이 프로필의 기본 글 유형과 같으면 더하는 점수(최대 100)

# ---- 시기 적합 ---------------------------------------------------------------------------------------------------------------
SEASON_MATCH = 100                  # 글에 이번 달 시기 낱말이 들어 있다
SEASON_RELATED = 70                 # 시기 낱말은 없지만 이번 달 시기와 이어지는 주제다
SEASON_NEUTRAL = 50                 # 시기와 무관한 상시 주제
SEASON_OFF = 30                     # 외부 계절성 자료가 있는데 이번 달이 아니다

# ---- 신선도·주제 균형 ----------------------------------------------------------------------------------------------------------
SIMILAR_FROM = 0.6                  # 기존 글 제목과 낱말 집합이 이만큼(0~1) 이상 겹치면 '비슷한 글 있음'
BALANCE_STEP = 20                   # 같은 씨앗을 다룬 기존 글 하나마다 주제 균형에서 빼는 점수(5편이면 0)

# ---- 키워드 기회도 ---------------------------------------------------------------------------------------------------------------
OPPORTUNITY_WEIGHTS = {"demand": 50, "competition": 30, "trend": 20}
DEMAND_FULL = 100_000               # 월간 검색 수요가 이 값 이상이면 수요 점수 100(로그 눈금)
RESULTS_FULL = 10_000_000           # 관련 블로그 검색 결과 수가 이 값 이상이면 경쟁이 가장 큰 것(점수 0)
TREND_POINTS = {"상승": 100, "보합": 50, "하락": 0}

# ---- 조회일 ----------------------------------------------------------------------------------------------------------------------
STALE_DATA_DAYS = 30                # 조회한 지 이 날수를 넘으면 '오래된 데이터'(정확히 30일은 아직 아니다)


class Part(NamedTuple):
    name: str                       # FACTORS 중 하나
    value: float                    # 요인 점수(0~100)
    weight: int                     # 정해 둔 가중치(WEIGHTS)
    share: float                    # 실제 비중(없는 요인을 빼고 다시 나눈 뒤, 합 1)
    points: float                   # 우선도에 기여한 점수(value × share)


class Priority(NamedTuple):
    level: str                      # 높음·보통·낮음
    score: float                    # 0~100(소수 한 자리)

    def to_dict(self):
        return {"level": self.level, "score": self.score}


def clamp(value):
    return min(100.0, max(0.0, float(value)))


def level_of(score):
    """점수(0~100) → 높음·보통·낮음 — 경계는 `HIGH_FROM`(70) 이상 높음·`MID_FROM`(40) 이상 보통."""
    return HIGH if score >= HIGH_FROM else MID if score >= MID_FROM else LOW


def combine(values):
    """요인 점수들(이름 → 0~100 또는 None='데이터 없음') → (콘텐츠 작성 우선도 | None, 요인별 내역).
    None 인 요인은 계산에서 빼고 남은 요인의 가중치를 합 1 로 다시 나눈다(없는 것을 0점으로 치지 않는다). 모르는 요인 이름은 ValueError, 요인이 하나도 없으면 (None, ())."""
    unknown = set(values) - set(FACTORS)
    if unknown:
        raise ValueError(f"모르는 요인: {sorted(unknown)}")
    present = [(name, clamp(values[name])) for name in FACTORS if values.get(name) is not None]
    total = sum(WEIGHTS[name] for name, _value in present)
    if not total:
        return None, ()
    parts = tuple(Part(name, value, WEIGHTS[name], WEIGHTS[name] / total, value * WEIGHTS[name] / total) for name, value in present)
    score = round(sum(part.points for part in parts), 1)
    return Priority(level_of(score), score), parts


def fit_score(strength, type_matches):
    """블로그 프로필 적합도 — 씨앗이 프로필에서 온 자리의 강도(`SEED_STRENGTH`) + 글 유형이 프로필의 기본 글 유형과 같으면 `TYPE_BONUS`(최대 100)."""
    return min(100, strength + (TYPE_BONUS if type_matches else 0))


def freshness_score(similarity):
    """신선도 — 기존 글과 전혀 안 겹치면(0) 100, `SIMILAR_FROM` 이상 겹치면 0, 그 사이는 직선으로."""
    return clamp(100.0 * (1.0 - similarity / SIMILAR_FROM))


def balance_score(covered):
    """주제 균형 — 같은 씨앗을 이미 다룬 글이 없으면 100, 하나마다 `BALANCE_STEP` 씩 빼서 0 아래로는 내려가지 않는다."""
    return max(0, 100 - BALANCE_STEP * covered)


def _log_scale(value, full):
    return min(100.0, 100.0 * math.log10(1 + max(0, value)) / math.log10(1 + full))


def opportunity(search_demand=None, related_blog_results=None, trend=None):
    """키워드 기회도(0~100) — 월간 검색 수요·관련 블로그 검색 결과 수·최근 관심도 변화 중 **있는 것만** 가중 평균한다(`OPPORTUNITY_WEIGHTS`, 없는 것은 빼고 다시 나눔). 셋 다 없으면 None('데이터 없음').
    수요는 많을수록, 검색 결과 수는 적을수록(경쟁이 작을수록), 관심도 변화는 상승일수록 높다. 모르는 관심도 변화는 ValueError."""
    parts = []
    if search_demand is not None:
        parts.append((OPPORTUNITY_WEIGHTS["demand"], _log_scale(search_demand, DEMAND_FULL)))
    if related_blog_results is not None:
        parts.append((OPPORTUNITY_WEIGHTS["competition"], 100.0 - _log_scale(related_blog_results, RESULTS_FULL)))
    if trend is not None:
        if trend not in TREND_POINTS:
            raise ValueError(f"모르는 관심도 변화: {trend}")
        parts.append((OPPORTUNITY_WEIGHTS["trend"], float(TREND_POINTS[trend])))
    if not parts:
        return None
    return sum(weight * value for weight, value in parts) / sum(weight for weight, _value in parts)


# ---- 시기 -------------------------------------------------------------------------------------------------------------------------
GENERIC_WORD_STEMS = frozenset({"준비", "시즌", "시기", "행사", "마무리"})      # 시기 낱말 속에 들어 있어도 주제를 가리키지 않는 말('여름 휴가 준비' 의 '준비') — 이어지는 낱말로는 쓰지 않는다


def _related_stems(item):
    """시기와 이어지는 낱말 — 항목의 `related` 와 시기 낱말의 어근(너무 흔한 말은 뺀다)."""
    return frozenset(text.stem(word) for word in item.related) | (text.stem_set(item.word) - GENERIC_WORD_STEMS)


def _is_related(tokens, related):
    """글의 낱말(두 글자 이상) 중 하나가 시기와 이어지는 낱말과 같거나 서로 포함되면 이어진다."""
    for token in tokens:
        if len(token) < text.MIN_STEM:
            continue
        for word in related:
            if len(word) >= text.MIN_STEM and (token == word or word in token or token in word):
                return True
    return False


def season_fit(sentence, month):
    """(시기 적합 점수, 맞은 시기 항목 | None) — 글에 그 달의 시기 낱말이 통째로 들어 있으면 `SEASON_MATCH`, 시기 낱말은 없지만 시기와 이어지는 낱말이 있으면 `SEASON_RELATED`, 아니면 `SEASON_NEUTRAL`."""
    stems = text.stems(sentence)
    present = frozenset(stems)
    for item in SEASONS[month]:
        if text.contains_all(present, text.stem_set(item.word)):
            return SEASON_MATCH, item
    for item in SEASONS[month]:
        if _is_related(stems, _related_stems(item)):
            return SEASON_RELATED, item
    return SEASON_NEUTRAL, None


def related_items(sentence, month):
    """그 달의 시기 항목 중 글(씨앗)과 이어지는 것들(표의 순서대로)."""
    stems = text.stems(sentence)
    return tuple(item for item in SEASONS[month] if _is_related(stems, _related_stems(item)))


def month_of(value):
    """달(1~12) 확인 — 정수가 아니거나 범위 밖이면 ValueError."""
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 12:
        raise ValueError("달은 1~12 사이의 정수여야 한다")
    return value


# ---- 조회일 -------------------------------------------------------------------------------------------------------------------------
class DataAge(NamedTuple):
    data_date: object               # 조회일(YYYY-MM-DD) 또는 None
    days: object                    # 조회한 지 며칠(오늘 기준, 0 아래로 내려가지 않는다) 또는 None
    stale: bool                     # `STALE_DATA_DAYS` 를 넘었다
    future: bool = False            # 조회일이 오늘보다 이틀 이상 뒤다(시간대 차이는 하루까지만 봐 준다) — 날짜를 잘못 적었을 수 있다

    def text(self):
        if self.data_date is None:
            return "외부 데이터 없음"
        if self.future:
            return f"조회일 {self.data_date} — 오늘보다 앞선 날짜입니다(날짜를 잘못 적었는지 확인하세요)"
        when = "오늘 조회" if self.days == 0 else f"{self.days}일 전 조회"
        return f"조회일 {self.data_date}({when})" + (f" — 오래된 데이터({STALE_DATA_DAYS}일 넘음, 다시 조회해 확인)" if self.stale else "")

    def to_dict(self):
        return {"data_date": self.data_date, "days_ago": self.days, "stale": self.stale, "future": self.future}


def data_age(data_date, today):
    """외부 지표를 조회한 날(YYYY-MM-DD 또는 None)과 오늘(date) → `DataAge`. 조회일이 오늘보다 하루 뒤(시간대 차이)여도 0일로 보고, 이틀 이상 뒤면 `future` 로 알린다(점수는 깎지 않는다). 없으면 '외부 데이터 없음'. 모양이 틀린 날짜는 ValueError."""
    if data_date is None:
        return DataAge(None, None, False)
    raw = (today - datetime.strptime(data_date, "%Y-%m-%d").date()).days
    days = max(raw, 0)
    return DataAge(data_date, days, days > STALE_DATA_DAYS, raw < -1)


__all__ = [
    "BALANCE_STEP", "DEMAND_FULL", "DataAge", "FACTORS", "FACTOR_HELP", "FACTOR_NAMES", "HIGH", "HIGH_FROM", "LOW", "MID", "MID_FROM", "OPPORTUNITY_WEIGHTS", "Part", "Priority", "RESULTS_FULL",
    "SEASON_MATCH", "SEASON_NEUTRAL", "SEASON_OFF", "SEASON_RELATED", "SEED_STRENGTH", "SIMILAR_FROM", "STALE_DATA_DAYS", "TREND_POINTS", "TYPE_BONUS", "WEIGHTS", "balance_score", "clamp",
    "combine", "data_age", "fit_score", "freshness_score", "level_of", "month_of", "opportunity", "related_items", "season_fit",
]
