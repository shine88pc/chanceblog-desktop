"""점수 링·변화량·구성 막대·사용량 막대의 **순수 계산** — PySide6 없이 시험한다(C-Type §9). 화면 부품(`ui/qt/gauges.py`)은 여기서 나온 값만 그린다.

규칙(운영자 2026-11-06 결정):
- 점수 구간은 엔진(`topics.channels.GRADE_CUTOFFS` = 80·65·50)과 **같은 기준**이다 — 80 이상 우선 추천(초록)·65~79 일반 후보(파랑)·50~64 보류(노랑)·0~49 제외(빨강). 구간 이름도 엔진의 말과 같다(시험이 엔진 값과 맞춰 본다).
- 링 안에는 **숫자만** 넣는다. 구간 이름과 변화량은 링 옆·아래의 별도 글(라벨)이고, 색만으로 구간을 알리지 않는다.
- **데이터 부족은 링을 그리지 않는다** — 점수가 없거나 0~100 밖이거나 숫자가 아니면 0점으로 그리지 않고 `데이터 부족` 글만 보인다(실제 0점은 링이 있고 '제외' 구간이다).
- 사용량은 표시한 퍼센트가 80 이상이면 경고색, 90 이상이면 위험색 — 색과 함께 `주의`·`위험` 글이 따라온다. 숫자와 단위를 늘 함께 쓴다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import tokens as K
from .text import T

SCORE_CUTOFFS = (80, 65, 50)                        # 엔진의 점수 구간 경계와 같다(`topics.channels.GRADE_CUTOFFS`) — 시험이 맞춰 본다
USAGE_WARN, USAGE_DANGER = 80, 90                   # 사용량 막대: 표시한 퍼센트가 이 이상이면 경고색·위험색
BAR_KINDS = ("base", "data", "trend", "other")      # 구성 막대의 구성별 고정색 — 팔레트 `bar_<종류>`


@dataclass(frozen=True)
class Band:
    key: str            # high | good | mid | low
    name: str           # 화면에 보이는 구간 이름
    color_key: str      # 링·막대 색(팔레트 키)
    text_key: str       # 구간 이름 글자 색(흰 바탕에서 대비 4.5 이상인 변형)


BANDS = (
    Band("high", T["band_high"], "score_high", "success_text"),
    Band("good", T["band_good"], "score_good", "primary_text"),
    Band("mid", T["band_mid"], "score_mid", "warning_text"),
    Band("low", T["band_low"], "score_low", "danger_text"),
)


def _round_half_up(value):
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def _number(value):
    """숫자(정수·실수)면 그 값, 아니면 None — 불리언·글자·NaN·무한대는 숫자로 치지 않는다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def clean_score(value):
    """점수 → 0~100 의 정수. 엔진의 점수(`score.band_of`)처럼 **정수만** 받는다(92.0 처럼 정수인 실수는 92). 없거나·숫자가 아니거나·소수이거나·0~100 밖이면 **None**(데이터 부족 — 0점이 아니다)."""
    number = _number(value)
    if number is None or (isinstance(number, float) and not number.is_integer()):
        return None
    score = int(number)
    return score if 0 <= score <= 100 else None


def score_band(score):
    """점수 → 구간(`Band`). 데이터 부족이면 None."""
    n = clean_score(score)
    if n is None:
        return None
    for band, cutoff in zip(BANDS, SCORE_CUTOFFS, strict=False):             # 구간은 넷, 경계는 셋 — 마지막 구간(제외)은 경계 없이 남는 값이다
        if n >= cutoff:
            return band
    return BANDS[-1]


RING_SIZES = {"card": K.SIZE["ring_card"], "detail": K.SIZE["ring_detail"]}      # 카드용 44(문서 40~44)·상세용 72(문서 68~80)
RING_RANGE = (40, 80)


def ring_pixels(size):
    """링 지름(px) — `"card"`(44)·`"detail"`(72) 이름이거나 숫자(40~80 으로 맞춘다). 모르는 이름은 ValueError(코드 실수)."""
    if isinstance(size, str):
        if size not in RING_SIZES:
            raise ValueError(f"링 크기 이름이 아니에요: {size!r}")
        return RING_SIZES[size]
    number = _number(size)
    if number is None:
        raise ValueError(f"링 크기가 숫자가 아니에요: {size!r}")
    return min(max(int(number), RING_RANGE[0]), RING_RANGE[1])


@dataclass(frozen=True)
class RingView:
    score: object           # int 또는 None
    band: object            # Band 또는 None
    sweep: float            # 그리는 호의 각도(0~360, 12시 방향에서 시계 방향)
    visible: bool           # 링을 그릴지 — 데이터 부족이면 False
    text: str               # 링 안의 글(숫자만) — 데이터 부족이면 빈 글


def ring_view(score):
    n = clean_score(score)
    if n is None:
        return RingView(None, None, 0.0, False, "")
    return RingView(n, score_band(n), 360.0 * n / 100, True, str(n))


@dataclass(frozen=True)
class DeltaView:
    kind: str               # up | down | flat | none
    text: str               # 화면에 보이는 글(▲ +12 · ▼ -5 · ― 변화 없음) — 없으면 빈 글
    spoken: str             # 접근 이름에 들어가는 글(12 상승 …)
    color_key: str          # 글자 색(팔레트 키): 상승 초록·하락 빨강·변화 없음 회색


def delta_view(delta):
    """점수 변화량 → 글. 상승 `▲ +12`(초록)·하락 `▼ -5`(빨강)·0 은 `― 변화 없음`(회색), 값이 없으면 보이는 글이 없다. 글자(▲▼―)와 색을 함께 쓴다."""
    number = _number(delta)
    if number is None:
        return DeltaView("none", "", "", "text_muted")
    n = _round_half_up(number)
    if n > 0:
        return DeltaView("up", f"▲ +{n}", T["cd_delta_up"].format(n=n), "success_text")
    if n < 0:
        return DeltaView("down", f"▼ -{-n}", T["cd_delta_down"].format(n=-n), "danger_text")
    return DeltaView("flat", T["cd_delta_flat_visible"], T["cd_delta_flat"], "text_secondary")


def score_spoken(score, delta=None):
    """접근 이름 — `점수 92, 우선 추천, 12 상승`. 데이터 부족이면 `점수 데이터 부족`(변화량은 말하지 않는다)."""
    n = clean_score(score)
    if n is None:
        return T["cd_score_none_a11y"]
    parts = [T["cd_score_a11y"].format(score=n), score_band(n).name]
    spoken = delta_view(delta).spoken
    if spoken:
        parts.append(spoken)
    return ", ".join(parts)


# ---- 구성 막대 ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SegmentView:
    label: str
    value: float
    text: str               # 막대 아래 숫자(첫 구성은 그대로, 나머지는 부호를 붙인다)
    fraction: float         # 막대 길이에서 차지하는 비율(양수 구성끼리의 비율 — 합이 1)
    color_key: str          # 팔레트 키 `bar_<종류>` — 구성마다 고정색


@dataclass(frozen=True)
class BarView:
    segments: tuple
    total_label: str
    total_text: str
    spoken: str
    empty: bool             # 그릴 구성이 하나도 없다 — 막대를 그리지 않고 안내 글만


def number_text(value, signed=False):
    """정수는 그대로, 소수는 한 자리까지. `signed` 면 0 보다 큰 값에 `+` 를 붙인다(음수는 `-`)."""
    number = _number(value)
    if number is None:
        return ""
    shown = f"{_round_half_up(number)}" if float(number).is_integer() else f"{number:.1f}"
    return f"+{shown}" if signed and number > 0 else shown


def bar_view(items, total_label=None, total=None, signed=True):
    """구성 막대 계산. `items` 는 `(이름, 값, 종류)` 의 나열 — 종류는 `BAR_KINDS`(`base`·`data`·`trend`·`other`)로 색이 고정이다(모르는 종류는 ValueError — 코드 실수).
    값이 숫자가 아닌 구성은 그리지 않는다. 막대 길이는 양수인 구성끼리의 비율이고, 총점은 `total`(없으면 값의 합)이다. 구성이 하나도 없으면 `empty`."""
    label = total_label or T["cd_bar_total"]
    kept = []
    for name, value, kind in items:
        if kind not in BAR_KINDS:
            raise ValueError(f"구성 종류가 아니에요: {kind!r}")
        if _number(value) is not None:
            kept.append((str(name), value, kind))
    if not kept:
        return BarView((), label, "", T["cd_bar_empty"], True)
    positive = sum(value for _name, value, _kind in kept if value > 0)
    segments = tuple(SegmentView(name, value, number_text(value, signed and index > 0), (value / positive if value > 0 and positive else 0.0), f"bar_{kind}")
                     for index, (name, value, kind) in enumerate(kept))
    shown_total = number_text(total if _number(total) is not None else sum(value for _name, value, _kind in kept))
    spoken = T["cd_bar_a11y"] + ": " + ", ".join(f"{s.label} {s.text}" for s in segments) + f", {label} {shown_total}"
    return BarView(segments, label, shown_total, spoken, False)


# ---- 사용량 막대 -------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class UsageView:
    known: bool
    state: str              # ok | warn | danger | unknown
    percent: object         # 표시하는 퍼센트(정수) 또는 None
    fraction: float         # 막대 채움(0~1) — 한도를 넘어도 1
    color_key: str          # 채움 색(팔레트 키): 기본 파랑·80% 경고·90% 위험
    text: str               # `이번 달 12,400 / 27,000회` — 숫자와 단위를 함께
    percent_text: str       # `46%`
    state_text: str         # 경고·위험이면 `주의`·`위험`(한도를 넘으면 `한도 넘음`) — 색과 함께 보이는 글
    spoken: str             # 접근 이름


def usage_view(used, limit, unit="회", label=""):
    """사용량 → 막대·글 계산. 표시한 퍼센트(반올림)가 80 이상이면 경고, 90 이상이면 위험(한도를 넘으면 위험 + `한도 넘음`). 값을 모르면(없음·음수·한도 0 이하·숫자 아님) 막대를 채우지 않고 `확인할 수 없어요`."""
    u, cap = _number(used), _number(limit)
    prefix = f"{label} " if label else ""
    if u is None or cap is None or u < 0 or cap <= 0:
        text = f"{prefix}{T['cd_usage_unknown']}"
        return UsageView(False, "unknown", None, 0.0, "primary", text, "", "", text)
    u, cap = _round_half_up(u), _round_half_up(cap)
    if cap <= 0:
        text = f"{prefix}{T['cd_usage_unknown']}"
        return UsageView(False, "unknown", None, 0.0, "primary", text, "", "", text)
    percent = _round_half_up(u * 100 / cap)
    if u > cap:
        state, color, state_text = "danger", "danger", T["cd_usage_over"]
    elif percent >= USAGE_DANGER:
        state, color, state_text = "danger", "danger", T["cd_usage_danger"]
    elif percent >= USAGE_WARN:
        state, color, state_text = "warn", "warning", T["cd_usage_warn"]
    else:
        state, color, state_text = "ok", "primary", ""
    text = f"{prefix}{u:,} / {cap:,}{unit}"
    percent_text = f"{percent}%"
    if state_text:
        spoken = T["cd_usage_a11y_state"].format(text=text, percent=percent, state=state_text)
    else:
        spoken = T["cd_usage_a11y"].format(text=text, percent=percent)
    return UsageView(True, state, percent, min(1.0, u / cap), color, text, percent_text, state_text, spoken)
