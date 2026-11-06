"""상단 앱 바의 날짜·시간 — 시계를 **주입**받는다(위젯이 `datetime.now()` 를 직접 부르지 않는다). 글(세 단계)·다음 갱신 시각·좁은 폭에서 무엇을 줄일지를 순수 함수로 두어 PySide6 없이 시험한다(UI-C1a, D-171).

- 날짜·시간은 컴퓨터 시계라 '예시' 가 아니다. 화면 글은 `strftime` 이 아니라 직접 만든다(한글 서식을 `strftime` 에 넘기면 영문 윈도 파이썬 3.10 에서 오류가 난 적이 있다).
- 갱신: 분이 바뀔 때만 그 글자만 다시 그린다 — 다음 분 경계까지 남은 시간(`ms_until_next_minute`)만큼 한 번 기다리는 타이머이고, 초 단위로 돌지 않는다.
- 좁은 폭: **소개 문구를 먼저 숨기고**, 그래도 모자라면 날짜를 줄인다(`2026년 11월 6일 (금) 20:10` → `11월 6일 (금) 20:10` → `11/6 20:10`). 폭은 글자 폭을 실제로 재서 판단한다(배율·글꼴에 강하다) — 재는 일은 화면 쪽이 하고, 이 파일은 잰 숫자로 고르기만 한다.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from .text import WEEKDAYS, date_text

DATE_LEVELS = 3                                       # 날짜 글의 단계 수 — 0 전체 · 1 연도 없이 · 2 숫자만
TICK_MARGIN_MS = 30                                   # 분 경계보다 조금 늦게 깨어나 '같은 분' 에 또 깨는 일을 줄인다


class SystemClock:
    """실제 컴퓨터 시계(앱의 기본값)."""

    def now(self):
        return datetime.datetime.now()


class FixedClock:
    """시험·사진용 시계 — 시각을 직접 정하고(`set`) 앞으로 보낸다(`advance`). 스스로 흐르지 않는다."""

    def __init__(self, now):
        if not isinstance(now, datetime.datetime):
            raise ValueError("시각은 datetime 이어야 해요")
        self._now = now

    def now(self):
        return self._now

    def set(self, now):
        if not isinstance(now, datetime.datetime):
            raise ValueError("시각은 datetime 이어야 해요")
        self._now = now

    def advance(self, seconds):
        self._now = self._now + datetime.timedelta(seconds=seconds)


def date_levels(now):
    """시각 하나 → 날짜·시간 글 세 단계(긴 것부터): `2026년 11월 6일 (금) 20:10` · `11월 6일 (금) 20:10` · `11/6 20:10`."""
    hm = f"{now.hour:02d}:{now.minute:02d}"
    return (f"{date_text(now.date())} {hm}", f"{now.month}월 {now.day}일 ({WEEKDAYS[now.weekday()]}) {hm}", f"{now.month}/{now.day} {hm}")


def ms_until_next_minute(now):
    """다음 분 경계까지 남은 밀리초(1 이상 60000 이하 — 정각에는 60000). 분이 바뀔 때 그 글자만 다시 그리려고 타이머를 이 시간만큼 건다."""
    elapsed = now.second * 1000 + now.microsecond // 1000
    return 60000 - elapsed


@dataclass(frozen=True)
class TopbarPlan:
    show_tagline: bool                                # 이름 옆 한 줄 소개를 보일지
    level: int                                        # 날짜 글 단계(0 전체 · 1 연도 없이 · 2 숫자만)


def plan_topbar(available, tagline_width, date_widths, gap):
    """왼쪽 이름 묶음을 뺀 남은 폭 `available` 안에서 소개 문구와 날짜를 어떻게 보일지 — **소개 문구를 먼저 숨기고**, 그래도 모자라면 날짜를 한 단계씩 줄인다.
    `tagline_width` 는 소개 문구의 글자 폭, `date_widths` 는 날짜 글 단계별(긴 것부터) 글자 폭, `gap` 은 소개 문구와 날짜 사이 최소 간격. 모두 잰 값(px).
    순서: ① 소개+전체 날짜 → ② 전체 날짜만 → ③ 연도 없는 날짜 → ④ 숫자만. 어느 것도 안 들어가면 ④(가장 짧은 것)로 둔다 — 날짜를 아예 없애지는 않는다."""
    if not date_widths:
        raise ValueError("날짜 글 폭이 있어야 해요")
    if tagline_width + gap + date_widths[0] <= available:
        return TopbarPlan(True, 0)
    for level, width in enumerate(date_widths):
        if width <= available:
            return TopbarPlan(False, level)
    return TopbarPlan(False, len(date_widths) - 1)
