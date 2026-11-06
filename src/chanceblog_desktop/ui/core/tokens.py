"""디자인 토큰 — 색(Theme Token)·글자 색(Text Token)·글자 모양(Typography Token)·간격·모서리·그림자·크기·움직임을 **이 파일 한 곳**에 둔다.

화면 코드(`ui/qt/`)는 색 값(`#rrggbb`)·글자 크기를 직접 쓰지 않고 여기서 만든 값(스타일시트·팔레트)만 쓴다 — 시험이 지킨다. 값의 출처는 운영자 UI 명세(v1.0.0·v1.1.0)와
2026-11-03 22:27 채팅의 세부 기준이다(문장을 옮기지 않고 값만 적었다). 파이썬 3.10 문법, PySide6 를 불러오지 않는다.

- 글꼴: **특정 글꼴 이름을 두지 않는다.** 일반 글자는 윈도 시스템 기본 글꼴(`QFontDatabase.systemFont(GeneralFont)`), 로그·경로·개발 정보만 고정폭(`FixedFont`)을 쓰고
  글꼴 Family 는 시스템을 따른다. 크기·굵기·행간은 아래 `TYPE`(Typography Token)이 정한다.
- 글자 색: Text Token 5개(`TEXT_TOKENS`). **순수 검정을 기본 글자색으로 쓰지 않는다**(시험이 지킨다).
- 테마: 첫 버전은 **밝은 테마만**이고 사용자 화면에 테마 선택을 두지 않는다. 다만 색은 모두 `THEMES` 의 테마 값으로 중앙 관리해 나중에 어두운 테마를 더할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_THEME = "light"

# ---- Text Token — (운영자 이름, 팔레트 키, 값, 쓰임). 이름·값은 운영자 기준 그대로(2026-11-03 22:27).
TEXT_TOKENS = (
    ("Text/Strong", "text_strong", "#0B1736", "제목·큰 숫자"),
    ("Text/Primary", "text_primary", "#14213D", "본문·단추 글자"),
    ("Text/Secondary", "text_secondary", "#5F6B7A", "보조 설명"),
    ("Text/Muted", "text_muted", "#8491A3", "힌트·빈 값 — 꼭 읽어야 하는 안내에는 쓰지 않는다"),
    ("Text/Disabled", "text_disabled", "#AAB4C3", "꺼진 단추의 글자 — 꺼진 것에만 쓴다"),
)
TEXT_KEYS = tuple(key for _name, key, _value, _use in TEXT_TOKENS)

# ---- Theme Token(밝은 테마). 키 이름은 소문자 snake_case. 화면 코드는 이 키로만 색을 부른다.
LIGHT = {
    "bg_app": "#F6F8FC", "bg_sidebar": "#F3F6FB", "surface": "#FFFFFF", "surface_2": "#F8FAFD", "surface_selected": "#EEF5FF", "surface_hover": "#F5F8FE",
    **{key: value for _name, key, value, _use in TEXT_TOKENS},
    "on_primary": "#FFFFFF",
    "border": "#E2E8F0", "border_strong": "#CCD6E4", "border_focus": "#2F6FED",
    "primary": "#2F6FED", "primary_600": "#245ED4", "primary_100": "#EAF2FF",
    "success": "#22B573", "success_100": "#E9F9F1", "warning": "#E69B2D", "warning_100": "#FFF4DF",
    "danger": "#E05252", "danger_100": "#FDECEC", "purple": "#7A5AF8", "purple_100": "#F0ECFF",
    "blog_a_bg": "#E5F0FF", "blog_a_text": "#1456B8", "blog_b_bg": "#FFF0DD", "blog_b_text": "#A95312",
    # 글자로 쓸 때 흰 바탕과의 대비가 4.5 이상이 되게 진하게 만든 변형(명세에는 없는 추가 값)
    "success_text": "#13794B", "warning_text": "#8F5600", "danger_text": "#B42323", "purple_text": "#5B3FD0", "primary_text": "#245ED4",
    "disabled_bg": "#EDF1F7",
    # 말풍선(툴팁)·토스트·뒤를 덮는 막(scrim)
    "inverse_bg": "#14213D", "inverse_text": "#FFFFFF", "scrim": "#14213D",
}
THEMES = {"light": LIGHT}                       # 어두운 테마를 더할 때는 같은 키를 가진 사전을 여기에 넣는다(사용자 화면에 선택 기능은 두지 않는다)
SCRIM_ALPHA = 0.38

# ---- Typography Token — 이름 → (크기 px, 굵기, 행간 배수). px 는 논리 픽셀이라 Qt6 가 화면 배율을 알아서 곱한다(배율을 직접 곱하지 않는다).
@dataclass(frozen=True)
class TypeStyle:
    size: int
    weight: int
    line_height: float


TYPE = {
    "display": TypeStyle(28, 700, 1.30), "h1": TypeStyle(22, 700, 1.35), "h2": TypeStyle(18, 700, 1.40),
    "body_lg": TypeStyle(15, 600, 1.60), "body": TypeStyle(14, 400, 1.60), "small": TypeStyle(13, 400, 1.50), "caption": TypeStyle(12, 400, 1.45),
    "button": TypeStyle(14, 600, 1.20), "metric": TypeStyle(28, 700, 1.20), "mono": TypeStyle(13, 400, 1.50),
}
# 글자 역할 → 그 역할의 글자 색(Text Token 키). 화면은 역할 이름만 고른다.
ROLE_TEXT = {
    "display": "text_strong", "h1": "text_strong", "h2": "text_strong", "metric": "text_strong",
    "body_lg": "text_primary", "body": "text_primary", "button": "text_primary", "mono": "text_primary",
    "small": "text_secondary", "caption": "text_secondary", "sub": "text_secondary", "muted": "text_muted",
}
ROLE_STYLE = {"sub": "body", "muted": "body"}      # 크기·굵기를 다른 역할에서 빌려 쓰는 역할

# ---- 간격(4px 격자)·모서리·그림자
# **아직 안 쓰는 값**: `SPACE`·`SHADOW`·`SHADOW_COLOR_KEY`·`COPY_FEEDBACK_MS` 와 `MOTION_MS` 의 hover·page — 정해만 두었고 화면 코드는 쓰지 않는다(시험 `test_the_tokens_nobody_uses_yet_are_the_documented_ones` 가 지킨다).
# 부품·화면의 여백·간격은 숫자를 직접 적었고 4px 격자 값(4·8·12·16·20·24)뿐 아니라 2·6·10·14·18·22px 도 있다 — 다음에 `SPACE` 로 정리한다(docs/UI_DESIGN_SPEC.md §2).
SPACE = {"1": 4, "2": 8, "3": 12, "4": 16, "5": 20, "6": 24, "8": 32, "10": 40, "12": 48}
RADIUS = {"button": 10, "input": 10, "card": 14, "chip": 999, "badge": 12, "thumb": 12, "tooltip": 8, "row": 14}
SHADOW = {"card": (0, 2, 10, 0.05), "elevated": (0, 8, 24, 0.10)}        # 안 쓰는 값 — (x, y, 번짐 px, 불투명도), 색은 text_primary 의 RGB(순수 검정을 쓰지 않는다). 이 묶음의 카드는 테두리만 쓴다
SHADOW_COLOR_KEY = "text_primary"

# ---- 크기 — 단추 높이: 큰 주 단추 44 · 표준 40 · 작은 34(그려지는 높이) · 아이콘 단독 36 · 누르는 칸은 모두 36 이상(`hit`)
SIZE = {
    "hit": 36, "control": 40, "control_primary": 44, "control_sm": 34, "icon_button": 36, "chip_h": 34, "menu_h": 44, "badge_h": 24, "sum_min_h": 108, "row_min_h": 96,
    "thumb": 64, "thumb_radius": 12, "input_h": 40, "toggle_w": 44, "toggle_h": 26, "skeleton_line": 14, "acc_h": 52,       # acc_h: 접이식 머리 한 줄의 최소 높이(누르는 칸 36 이상)
}
ICON = {"nav": 18, "card": 22, "button": 18, "button_sm": 16, "empty": 44, "box": 40, "box_radius": 12, "gap": 10, "badge": 14, "trend": 16}
LAYOUT = {
    "topbar": 64, "sidebar": 210, "rail": 280, "drawer": 420, "dialog": 480, "content_max": 1280, "page_margin": 24, "gap": 20,
    "window": (1440, 900), "window_min": (900, 560),
    "rail_beside_min": 1100,       # 본문 폭이 이 이상일 때만 오른쪽 패널을 옆에 둔다(아니면 아래)
    "row_compact_below": 800,      # 추천 행의 폭이 이보다 좁으면 지표 칸(검색량·문서 수·추세)을 접는다
}
MOTION_MS = {"hover": 120, "page": 180, "panel": 200}        # 화면 전환 150~220 · 호버 100~150 · 서랍·접이식 180~240 — **서랍(panel)만 쓴다**, hover·page 는 값만 있다(효과를 입히지 않는다)
TOAST_MS = 3500                                               # 안내(토스트)가 보이는 시간 3~4초
COPY_FEEDBACK_MS = 1800                                       # 안 쓰는 값 — 복사한 단추가 '복사됨' 으로 보이는 시간(이미지 화면 묶음에서 쓴다). 지금은 토스트(TOAST_MS)만 쓴다

# 계열 이름 → (아이콘 색 키, 아이콘 바탕 색 키, 글자 색 키) — 요약 카드·주제 아이콘(진한 면을 쓰지 않고 아이콘 바탕과 숫자에만)
TONES = {
    "blue": ("primary", "primary_100", "primary_text"), "green": ("success", "success_100", "success_text"),
    "purple": ("purple", "purple_100", "purple_text"), "orange": ("warning", "warning_100", "warning_text"),
    "red": ("danger", "danger_100", "danger_text"), "slate": ("text_secondary", "surface_2", "text_secondary"),
}


def palette(theme=DEFAULT_THEME, overrides=None):
    """테마의 색 사전(복사본). `overrides` 는 시험에서 값 하나를 바꿔 스타일시트가 따라 바뀌는지 볼 때만 쓴다."""
    colors = dict(THEMES[theme])
    for key, value in (overrides or {}).items():
        if key not in colors:
            raise KeyError(key)
        colors[key] = value
    return colors


def _channels(color):
    return [int(color[i:i + 2], 16) for i in (1, 3, 5)]


def mix(first, second, amount):
    """두 색(#RRGGBB)을 섞는다 — amount 만큼 second 쪽으로."""
    return "#" + "".join(f"{round(x + (y - x) * amount):02X}" for x, y in zip(_channels(first), _channels(second)))


def rgba(color, alpha):
    r, g, b = _channels(color)
    return f"rgba({r}, {g}, {b}, {alpha})"


def tone(colors, name):
    """계열 이름 → (아이콘 색, 아이콘 바탕 색, 글자 색, 그라디언트 끝 색)"""
    strong, soft, text = TONES[name]
    return colors[strong], colors[soft], colors[text], mix(colors[soft], colors[strong], 0.22)


def role_color(colors, role):
    return colors[ROLE_TEXT[role]]


def type_style(role):
    return TYPE[ROLE_STYLE.get(role, role)]


# ---- 대비(접근성) — WCAG 상대 휘도와 대비비
def _linear(channel):
    value = channel / 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(color):
    r, g, b = (_linear(c) for c in _channels(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(foreground, background):
    first, second = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)
