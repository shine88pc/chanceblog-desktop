"""Trend 연결 틀 — 최근 관심도(상대값) 공급자의 규약 `TrendProvider` 와 '없음'·'가짜' 구현(P3, 계획 3.4·4.2, 결정 D-60 — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).
**실제 호출은 여기에 없다** — 네이버 검색어 트렌드를 부르는 일은 P5(T3)에서 `service/` 밖의 별도 패키지에 두고 호출하는 쪽이 이 규약을 지키는 공급자로 넣어 준다.

공급자는 키워드 하나와 기준일(`today`)을 받아 `TrendReading` 하나를 돌려준다. 돌려주는 값은 계획 4.2 의 칸 — 관심도 상대값 `trend_ratio`·상태 `trend_status`(rising·flat·falling·insufficient)·비교 기간 `trend_period`·
비교 키워드 그룹 `trend_compared_group`·조회일 `trend_queried_on` — 과 자료 상태 `data_status`(sufficient·partial·insufficient·unavailable)다. 상대값은 실제 검색 횟수가 아니고 횟수 칸으로 흘러가지 않는다.
  · `queried` 가 거짓이면 '조회 안 함' 이다(없음 공급자) — 값이 하나도 없고 엔진은 관심도 항목을 빼고(캘린더만으로) 시기 항목을 정한다. '조회 안 함' 은 '조회했지만 모자람(insufficient)'·'조회할 수 없었음(unavailable)' 과 다르다.
  · **장애(unavailable)와 데이터 부족(insufficient)을 구분한다**: 장애는 값이 없고 '조회 불가' 로 기록되며 모든 키워드가 조회 불가일 때만 생성기에 '관심도 조회 불가' 로 알린다(일부만 안 되면 그 키워드는 값이 없는 것으로 둔다).
  · **느린 응답**: 응답에 걸린 시간(`elapsed_seconds` — 가짜는 시나리오가 정하고 실제 공급자는 호출하는 쪽이 잰다)이 기한(`DEADLINE_SECONDS`, 초기값 10초)을 넘으면 값을 쓰지 않고 조회 불가로 본다.
  · 공급자가 오류를 내거나 이상한 값을 줘도 `collect` 는 멈추지 않는다 — 그 키워드를 조회 불가로 두고 안내에 남긴다(조용히 삼키지 않는다). 엔진은 어느 경우에도 규칙 기반으로 계속 돈다.
이 모듈의 숫자(기한·한 번에 조회할 키워드 수)는 **초기값 — 전략 원문 확인 전**이다.
"""
from __future__ import annotations

from typing import NamedTuple, Protocol

from ..content.candidates import keyword_key
from ..errors import AppError
from .generate import InterestReading
from .model import check_trend
from .score import DATA_INSUFFICIENT, DATA_PARTIAL, DATA_STATUSES, DATA_SUFFICIENT, DATA_UNAVAILABLE, DETERMINATE_TRENDS, TREND_INSUFFICIENT, TREND_RISING

DEADLINE_SECONDS = 10.0                                      # 응답을 기다리는 최대 시간(초기값)
MAX_KEYWORDS = 50                                            # `collect` 가 한 번에 조회하는 키워드 수의 상한(초기값)
SLOW_SECONDS = 30.0                                          # 가짜 공급자의 '느린 응답' 시나리오가 쓰는 응답 시간
SCENARIOS = ("value", "insufficient", "unavailable", "slow")
COMPARED_BASE = "기준 키워드"                                 # 가짜 공급자가 비교 그룹에 함께 넣는 가짜 비교 낱말
FAKE_PERIOD = "최근 1년"


class TrendReading(NamedTuple):
    queried: bool                                            # 거짓이면 조회하지 않았다
    trend_status: str                                        # rising·flat·falling·insufficient
    trend_ratio: int | None                                  # 상대값(0~100) — 실제 검색 횟수가 아니다
    trend_period: str | None
    trend_compared_group: tuple
    trend_queried_on: str | None
    data_status: str                                         # sufficient·partial·insufficient·unavailable
    elapsed_seconds: float | None = None                     # 응답에 걸린 시간 — 모르면 None


NOT_QUERIED = TrendReading(False, TREND_INSUFFICIENT, None, None, (), None, DATA_INSUFFICIENT)
UNAVAILABLE = TrendReading(True, TREND_INSUFFICIENT, None, None, (), None, DATA_UNAVAILABLE)


class TrendProvider(Protocol):
    """관심도 공급자의 규약 — `name`(화면에 보일 이름)과 `read(키워드, 기준일)`. 실제 공급자(P5)도 이 모양만 지키면 된다."""
    name: str

    def read(self, keyword: str, today: str) -> TrendReading:
        ...


def check_reading(reading):
    """`TrendReading` 이 규칙에 맞는지 확인하고 그대로 돌려준다 — 관심도 다섯 칸은 후보와 같은 규칙(`model.check_trend`)이고, 조회 안 함·부족·불가는 값이 없어야 하며 충분·일부는 상대값이 있어야 한다. 어긋나면 `ValueError`."""
    if not isinstance(reading, TrendReading) or not isinstance(reading.queried, bool) or not isinstance(reading.data_status, str) or reading.data_status not in DATA_STATUSES:
        raise ValueError("관심도 값이 올바른 모양이 아니다")
    if reading.elapsed_seconds is not None and (isinstance(reading.elapsed_seconds, bool) or not isinstance(reading.elapsed_seconds, (int, float)) or not 0 <= reading.elapsed_seconds <= 86400):
        raise ValueError("응답 시간은 0~86400 초 사이의 수이거나 None 이어야 한다")
    group = reading.trend_compared_group if isinstance(reading.trend_compared_group, tuple) else None
    if group is None:
        raise ValueError("비교 키워드 그룹은 튜플이어야 한다")
    try:
        check_trend(reading.trend_status, reading.trend_ratio, reading.trend_period, group, reading.trend_queried_on)
    except AppError:                                          # 후보 칸 오류를 값 오류로 바꾼다 — 이 순수 모듈은 개발자용 `ValueError` 만 낸다
        raise ValueError("관심도 다섯 칸이 후보의 규칙에 맞지 않는다") from None
    has_value = reading.trend_ratio is not None
    if reading.data_status in (DATA_SUFFICIENT, DATA_PARTIAL):
        if not reading.queried or not has_value or reading.trend_status not in DETERMINATE_TRENDS:
            raise ValueError("충분·일부 자료에는 조회한 상대값과 상승·보통·하락 상태가 있어야 한다")
    elif has_value or reading.trend_status != TREND_INSUFFICIENT or reading.trend_period is not None or group or reading.trend_queried_on is not None:
        raise ValueError("조회 안 함·자료 부족·조회 불가에는 관심도 값이 없어야 한다(모르는 값은 0 이 아니다)")
    if not reading.queried and reading.data_status == DATA_UNAVAILABLE:
        raise ValueError("조회하지 않았으면 조회 불가일 수 없다")
    return reading


def interpret(reading, deadline=DEADLINE_SECONDS):
    """기한을 넘긴 느린 응답은 값을 버리고 조회 불가로 바꾼다. 그 밖에는 검사한 값 그대로(조회 안 함은 조회 안 함 그대로)."""
    checked = check_reading(reading)
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or deadline <= 0:
        raise ValueError("기한은 0 보다 큰 수(초)여야 한다")
    if checked.queried and checked.elapsed_seconds is not None and checked.elapsed_seconds > deadline:
        return UNAVAILABLE._replace(elapsed_seconds=checked.elapsed_seconds)
    return checked


class NoTrend:
    """'없음' 공급자 — 늘 '조회 안 함' 이다. 키·네트워크 없이 도는 기본 공급자이고 엔진은 캘린더만으로 시기 항목을 정한다."""
    name = "없음"

    def read(self, keyword, today):
        return NOT_QUERIED


class FakeTrend:
    """'가짜' 공급자 — 시험과 시연용이다(실제 값이 아니다). 시나리오 넷: `value`(상대값이 있음) · `insufficient`(조회했지만 모자람) · `unavailable`(조회 불가) · `slow`(값은 있으나 응답이 느림 — `slow_seconds` 가
    기한을 넘으면 `interpret` 이 조회 불가로 바꾼다). `overrides` 는 {키워드: 시나리오} 로 키워드마다 다르게 하고(키워드는 `keyword_key` 로 비교), 같은 입력은 늘 같은 값이다."""
    name = "가짜(시험용)"

    def __init__(self, scenario="value", *, ratio=73, status=TREND_RISING, slow_seconds=SLOW_SECONDS, overrides=None):
        self.scenario = self._scenario(scenario)
        self.ratio, self.status, self.slow_seconds = ratio, status, slow_seconds
        self.overrides = {keyword_key(key): self._scenario(value) for key, value in (overrides or {}).items()}
        self.calls = []                                      # 불린 키워드들(시험이 본다)
        if not isinstance(ratio, int) or isinstance(ratio, bool) or not 0 <= ratio <= 100 or status not in DETERMINATE_TRENDS:
            raise ValueError("가짜 공급자의 상대값은 0~100 정수이고 상태는 rising·flat·falling 이어야 한다")

    @staticmethod
    def _scenario(name):
        if not isinstance(name, str) or name not in SCENARIOS:
            raise ValueError("시나리오는 다음 중 하나여야 한다: " + ", ".join(SCENARIOS))
        return name

    def read(self, keyword, today):
        self.calls.append(keyword)
        scenario = self.overrides.get(keyword_key(keyword), self.scenario)
        if scenario == "unavailable":
            return UNAVAILABLE
        if scenario == "insufficient":
            return TrendReading(True, TREND_INSUFFICIENT, None, None, (), None, DATA_INSUFFICIENT)
        group = (COMPARED_BASE, keyword) if keyword_key(keyword) != keyword_key(COMPARED_BASE) else (keyword,)
        elapsed = self.slow_seconds if scenario == "slow" else 0.0
        return TrendReading(True, self.status, self.ratio, FAKE_PERIOD, group, today, DATA_SUFFICIENT, elapsed)


class TrendResult(NamedTuple):
    interest: dict                                           # {keyword_key(키워드): InterestReading} — 값이 있는 키워드만(`generate(interest=…)` 에 그대로)
    outage: bool                                             # 조회한 모든 키워드가 조회 불가 → `generate(interest_outage=…)`
    readings: tuple                                          # ((키워드, TrendReading), …) — 조회한 순서
    notes: tuple                                             # 쉬운 한국어 안내 줄들


def collect(provider, keywords, today, *, deadline=DEADLINE_SECONDS, limit=MAX_KEYWORDS):
    """공급자에게 키워드들(겹치는 것은 한 번만, 앞에서 `limit` 개까지)을 물어 생성기에 넘길 값으로 모은다. 어떤 일이 있어도 멈추지 않는다 — 오류·이상한 값·느린 응답은 그 키워드를 조회 불가로 두고 안내에 적는다."""
    if not callable(getattr(provider, "read", None)):
        raise TypeError("공급자는 read(키워드, 기준일) 를 가져야 한다(TrendProvider)")
    if isinstance(keywords, (str, bytes)) or not hasattr(keywords, "__iter__"):
        raise TypeError("keywords 는 글의 목록이어야 한다")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("조회할 키워드 수의 상한은 1 이상의 정수여야 한다")
    unique, seen = [], set()
    for word in keywords:
        if not isinstance(word, str):
            raise TypeError("keywords 에는 글만 들어 있어야 한다")
        key = keyword_key(word)
        if key and key not in seen:
            seen.add(key)
            unique.append(word)
    chosen = unique[:limit]
    notes, readings, interest = [], [], {}
    if len(unique) > len(chosen):
        notes.append(f"키워드가 {len(unique)}개라 앞의 {len(chosen)}개만 조회했습니다")
    slow = 0
    for word in chosen:
        try:
            raw = provider.read(word, today)
        except Exception:                                     # 공급자가 무엇을 내든 엔진은 멈추지 않는다 — 조회 불가로 두고 안내에 남긴다
            readings.append((word, UNAVAILABLE))
            notes.append(f"‘{word[:20]}’ 의 관심도를 조회하다 오류가 나서 값 없이 진행합니다")
            continue
        try:
            reading = interpret(raw, deadline)
        except ValueError:
            readings.append((word, UNAVAILABLE))
            notes.append(f"‘{word[:20]}’ 의 관심도 값이 올바른 모양이 아니라 쓰지 않았습니다")
            continue
        if raw.queried and reading.data_status == DATA_UNAVAILABLE and raw.data_status != DATA_UNAVAILABLE:
            slow += 1                                         # 응답이 기한을 넘겨 버려졌다
        readings.append((word, reading))
        if reading.queried and reading.data_status in (DATA_SUFFICIENT, DATA_PARTIAL):
            interest[keyword_key(word)] = InterestReading(reading.trend_status, reading.trend_ratio, reading.trend_period, reading.trend_compared_group, reading.trend_queried_on)
    if slow:
        notes.append(f"응답이 {deadline:g}초를 넘긴 키워드 {slow}개는 값을 쓰지 않았습니다")
    asked = [reading for _word, reading in readings if reading.queried]
    outage = bool(asked) and all(reading.data_status == DATA_UNAVAILABLE for reading in asked)
    if outage:
        notes.append("관심도를 조회할 수 없어 시기 항목은 캘린더만으로 정했습니다")
    elif chosen and not asked:
        notes.append("관심도를 조회하지 않았습니다(캘린더만으로 시기 항목을 정합니다)")
    return TrendResult(interest, outage, tuple(readings), tuple(notes))


__all__ = [
    "COMPARED_BASE", "DEADLINE_SECONDS", "FAKE_PERIOD", "FakeTrend", "MAX_KEYWORDS", "NOT_QUERIED", "NoTrend", "SCENARIOS", "SLOW_SECONDS", "TrendProvider", "TrendReading",
    "TrendResult", "UNAVAILABLE", "check_reading", "collect", "interpret",
]
