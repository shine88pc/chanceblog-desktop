"""공통 부품의 순수 규칙 — 아래 고정 행동 줄이 좁을 때 무엇을 `더보기 ⋮` 로 접을지, 탭의 키보드 이동, 한 줄 배지의 글자 줄임, **상세 창을 고정으로 둘지 서랍으로 할지**(논리 폭 기준), 격자의 열 수(홈의 KPI·구역 — UI-C1d). PySide6 없이 시험한다(C-Type §5.4·§8.2·§8.3·§10.5·§16.2).

행동 줄의 규칙: 주요 행동 **1개**(늘 보인다) · 보조 최대 3개 · 3차(글자만) 여러 개 · 위험 3차 최대 1개 · `더보기 ⋮`(접힌 것이 있거나 처음부터 더보기 항목이 있을 때만).
자리가 모자라면 **위험·3차 → 보조** 순서로(각각 뒤에 있는 것부터) 더보기 메뉴로 접고, 그래도 모자라면 주요 행동 하나만 남는다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import tokens as K

ACTION_KINDS = ("primary", "secondary", "tertiary", "danger")
SECONDARY_MAX = 3                                    # 보조 행동은 최대 3개
BADGE_MAX_CHARS = 16                                 # 한 줄 배지의 글자 수 상한 — 넘으면 …로 줄이고 전체는 툴팁(그릴 때는 칸 폭으로 한 번 더 줄인다)


def clip_text(text, max_chars):
    """줄바꿈·겹공백을 한 칸 공백으로 바꾸고, `max_chars` 를 넘으면 앞부분 + `…` 로 줄인다(전체 글은 호출한 쪽이 툴팁으로 둔다)."""
    flat = " ".join(str(text).split())
    if max_chars < 1 or len(flat) <= max_chars:
        return flat
    return flat[:max_chars - 1].rstrip() + "…"


def check_actions(kinds):
    """행동 줄 구성이 규칙을 지키는지 — 주요 1개·보조 최대 3개·위험 최대 1개·모르는 종류 없음. 어기면 ValueError(코드 실수를 드러낸다)."""
    kinds = list(kinds)
    for kind in kinds:
        if kind not in ACTION_KINDS:
            raise ValueError(f"행동 종류가 아니에요: {kind!r}")
    if kinds.count("primary") != 1:
        raise ValueError("주요 행동은 정확히 1개여야 해요")
    if kinds.count("secondary") > SECONDARY_MAX:
        raise ValueError(f"보조 행동은 최대 {SECONDARY_MAX}개예요")
    if kinds.count("danger") > 1:
        raise ValueError("위험 행동은 최대 1개예요")
    return tuple(kinds)


def plan_actions(available, kinds, widths, gap, more_width, has_more=False):
    """보이는 폭 `available` 안에 들어가게 행동을 나눈다 → `(보이는 번호들, 더보기로 접힌 번호들, 더보기 단추를 보일지)`.
    `kinds`·`widths` 는 그리는 순서대로. 더보기 단추 자리(`more_width`)는 접힌 것이 있거나 `has_more` 일 때 센다. 주요 행동은 폭이 모자라도 늘 보인다."""
    kinds = check_actions(kinds)
    if len(widths) != len(kinds):
        raise ValueError("행동 수와 폭 수가 달라요")
    order = [i for i, kind in enumerate(kinds) if kind in ("danger", "tertiary")][::-1] + [i for i, kind in enumerate(kinds) if kind == "secondary"][::-1]
    folded = []

    def need():
        shown = [i for i in range(len(kinds)) if i not in folded]
        sizes = [widths[i] for i in shown] + ([more_width] if (folded or has_more) else [])
        return sum(sizes) + gap * max(0, len(sizes) - 1)

    while need() > available and order:
        folded.append(order.pop(0))
    visible = tuple(i for i in range(len(kinds)) if i not in folded)
    return visible, tuple(sorted(folded)), bool(folded or has_more)


def tab_move(index, count, key):
    """탭 줄에서 ←·→·Home·End 를 눌렀을 때 새로 고르는 번호(끝에서 한 바퀴 돈다). 탭이 없으면 -1, 모르는 키는 그대로."""
    if count <= 0:
        return -1
    index = min(max(index, 0), count - 1)
    if key == "right":
        return (index + 1) % count
    if key == "left":
        return (index - 1) % count
    if key == "home":
        return 0
    if key == "end":
        return count - 1
    return index


@dataclass(frozen=True)
class DetailLayout:
    mode: str                                          # `fixed`(옆에 붙은 고정 상세 창) | `drawer`(오른쪽에서 밀려 나오는 서랍)
    detail_width: int                                  # 고정이면 상세 창 폭(px), 서랍이면 0 — 서랍 폭은 `drawer_width`
    columns: int                                       # 목록 카드 열 수


def detail_layout(logical_width):
    """창의 **Qt 논리 폭**(`QWidget.width()` — 윈도 배율이 이미 나뉜 값, 물리 해상도가 아니다) → 상세 창 방식과 카드 열 수(운영자 결정 2026-11-06 확인 요청 004, D-174).
    논리 폭 ≥ 1600: 고정 상세 창 420~500(1600 에서 420, `detail_max_at`=1920 이상에서 500, 사이는 비례)·카드 3열 / 1366~1599: 고정 400·카드 2열 / 1366 미만: 서랍·카드 2열.
    예) 1920×1080 물리 100% = 논리 1920 → 고정 500·3열 · 1920 물리 125% = 논리 1536 → 고정 400·2열 · 1366 물리 100% = 논리 1366 → 고정 400·2열 · 1366 물리 125% = 논리 1093 → 서랍·2열.
    숫자가 아니거나(불리언·글자·NaN·무한대) 0 이하면 ValueError — 위젯 폭을 잘못 넘긴 코드 실수를 드러낸다."""
    if isinstance(logical_width, bool) or not isinstance(logical_width, (int, float)) or not math.isfinite(logical_width) or logical_width <= 0:
        raise ValueError(f"창 폭이 올바른 숫자가 아니에요: {logical_width!r}")
    frame = K.FRAME
    if logical_width >= frame["fixed_detail_min"]:
        low, high = frame["detail_range"]
        share = min(1.0, (logical_width - frame["fixed_detail_min"]) / (frame["detail_max_at"] - frame["fixed_detail_min"]))
        return DetailLayout("fixed", low + int(round((high - low) * share)), frame["detail_columns_wide"])
    if logical_width >= frame["narrow_detail_min"]:
        return DetailLayout("fixed", frame["detail_narrow"], frame["detail_columns_narrow"])
    return DetailLayout("drawer", 0, frame["detail_columns_narrow"])


def grid_columns(width, options, min_col, gap):
    """폭 `width` 안에 한 칸 최소 폭 `min_col`·칸 사이 `gap` 으로 들어가는 가장 큰 열 수 — `options` 는 큰 열 수부터이고 하나도 안 들어가면 마지막(가장 작은) 열 수다. 화면의 격자(`screens.FlowGrid`)가 이 규칙으로 열을 고른다.
    숫자가 아닌 폭(불리언·글자·NaN·무한대)·열 수 후보가 없거나 1 보다 작은 값·0 이하의 최소 폭은 ValueError(코드 실수를 드러낸다). 폭이 음수여도 마지막 열 수다(아직 놓이기 전의 폭 0 처럼)."""
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width):
        raise ValueError(f"폭이 올바른 숫자가 아니에요: {width!r}")
    options = tuple(options)
    if not options or any(isinstance(cols, bool) or not isinstance(cols, int) or cols < 1 for cols in options):
        raise ValueError(f"열 수 후보가 올바르지 않아요: {options!r}")
    if isinstance(min_col, bool) or not isinstance(min_col, (int, float)) or min_col <= 0 or isinstance(gap, bool) or not isinstance(gap, (int, float)) or gap < 0:
        raise ValueError("한 칸의 최소 폭은 0 보다 크고 칸 사이 간격은 0 이상이어야 해요")
    for cols in options:
        if cols * min_col + (cols - 1) * gap <= width:
            return cols
    return options[-1]


HOME_KPI_OPTIONS = (4, 2, 1)                         # 홈 KPI 카드: 4열 → 2열 → 1열
HOME_KPI_GAP = K.SPACE["4"]                          # KPI 카드 사이 간격 16
HOME_SECTION_OPTIONS = (2, 1)                        # 홈 구역(Naver A·B 추천, 작성 중 초안·최근 발행): 두 칸이 들어가면 나란히, 아니면 위아래로


def home_kpi_columns(width):
    """홈 본문 폭(논리 px) → KPI 카드 열 수(4·2·1)."""
    return grid_columns(width, HOME_KPI_OPTIONS, K.LAYOUT["kpi_min_col"], HOME_KPI_GAP)


def home_section_columns(width):
    """홈 본문 폭(논리 px) → 구역 열 수(2 = 나란히·1 = 위아래). 서랍(상세 창)은 폭과 상관없이 홈에서 오른쪽에서 밀려 나오는 서랍이다(`drawer_width`)."""
    return grid_columns(width, HOME_SECTION_OPTIONS, K.LAYOUT["section_min_col"], K.LAYOUT["gap"])


def home_posts_columns(width):
    """홈 본문 폭(논리 px) → 글 구역(작성 중 초안·최근 발행) 열 수(2 = 나란히·1 = 위아래) — 글 줄은 제목과 상태·시각뿐이라 추천 구역보다 좁은 한 칸(`posts_min_col`)까지 나란히 둔다."""
    return grid_columns(width, HOME_SECTION_OPTIONS, K.LAYOUT["posts_min_col"], K.LAYOUT["gap"])


def drawer_width(window_width):
    """서랍 폭 — 정해진 폭(420)이되 창의 92% 를 넘지 않는다(지금 홈의 서랍이 쓰던 규칙 그대로, 이름만 토큰으로 옮김)."""
    return min(K.FRAME["drawer"], int(window_width * K.FRAME["drawer_max_ratio"]))
