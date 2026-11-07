"""디자인 토큰 — 색(Theme Token)·글자 색(Text Token)·글자 모양(Typography Token)·간격·모서리·그림자·크기·움직임을 **이 파일 한 곳**에 둔다.

화면 코드(`ui/qt/`)는 색 값(`#rrggbb`)·글자 크기를 직접 쓰지 않고 여기서 만든 값(스타일시트·팔레트)만 쓴다 — 시험이 지킨다. 값의 출처는 운영자 UI 명세(v1.0.0·v1.1.0)·2026-11-03 22:27 채팅의 세부 기준과
**2026-11-06 'C-Type UI 디자인 시스템 v1.0.0'**(2026-11-03 기준과 같은 방향의 다듬기 — 색 값 몇 개·글자 크기·모서리·그림자가 바뀌고 새 토큰이 더해졌다)이다. 문장을 옮기지 않고 값만 적었다.
파이썬 3.10 문법, PySide6 를 불러오지 않는다.

- 글꼴: **특정 글꼴 이름을 두지 않는다.** 일반 글자는 윈도 시스템 기본 글꼴(`QFontDatabase.systemFont(GeneralFont)`), 로그·경로·개발 정보만 고정폭(`FixedFont`)을 쓰고
  글꼴 Family 는 시스템을 따른다. 크기·굵기·행간은 아래 `TYPE`(Typography Token)이 정한다.
- 글자 색: Text Token 5개(`TEXT_TOKENS`). **순수 검정을 기본 글자색으로 쓰지 않는다**(시험이 지킨다).
- 테마: 첫 버전은 **밝은 테마만**이고 사용자 화면에 테마 선택을 두지 않는다. 다만 색은 모두 `THEMES` 의 테마 값으로 중앙 관리해 나중에 어두운 테마를 더할 수 있다.
- 이름 정리(UI-C0): 예전 `primary_600` 은 이름과 달리 '진한 쪽' 값이었다 → 새 문서의 이름에 맞춰 `primary_700`(진한 쪽)·`primary_pressed`(눌림)로 바꾸고, `primary` 가 문서의 'Primary 600'(기본 파랑)이다.
- 접근성 색(UI-C1a, D-170): 운영자 2026-11-06 확인 요청 004 의 답으로 **문서 원값 대신** 의미 배지 글자 추천 `#9D5F07`·가격변화 `#437B28`·주의 `#9F6003` 과 위험 단추 배경 `#CE4646`(흰 글자)을 쓴다 — 모두 대비 4.5 이상.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_THEME = "light"

# ---- Text Token — (운영자 이름, 팔레트 키, 값, 쓰임). 이름·값은 운영자 기준 그대로(2026-11-03 22:27, C-Type 문서도 같은 5개).
TEXT_TOKENS = (
    ("Text/Strong", "text_strong", "#0B1736", "제목·큰 숫자"),
    ("Text/Primary", "text_primary", "#14213D", "본문·단추 글자"),
    ("Text/Secondary", "text_secondary", "#5F6B7A", "보조 설명"),
    ("Text/Muted", "text_muted", "#8491A3", "힌트·빈 값 — 꼭 읽어야 하는 안내에는 쓰지 않는다"),
    ("Text/Disabled", "text_disabled", "#AAB4C3", "꺼진 단추의 글자 — 꺼진 것에만 쓴다"),
)
TEXT_KEYS = tuple(key for _name, key, _value, _use in TEXT_TOKENS)

# ---- 의미별 배지 11쌍(C-Type §4.5) — (열쇠, 한국어 이름, 배경, 글자). 글자와 함께 쓴다(색만으로 뜻을 알리지 않는다).
# 의도적 변경(UI-C1a, D-170): 추천·가격변화·주의의 **글자 색**은 문서 값(#B36A00·#478327·#A86500 — 대비 3.73·4.14·4.18)이 4.5 에 못 미쳐 운영자가 정한 접근성 색으로 바꿨다. 배경은 문서 값 그대로.
SEMANTIC_BADGES = (
    ("public_data", "공공데이터", "#DCEBFF", "#1E63C6"),
    ("recommend", "추천", "#FFF0CA", "#9D5F07"),
    ("global_compare", "해외비교", "#EEE4FF", "#7545B8"),
    ("culture_event", "문화행사", "#FFE3E3", "#B93A3A"),
    ("price_change", "가격변화", "#E8F7DF", "#437B28"),
    ("travel", "여행", "#E5F1FF", "#2C6FAE"),
    ("tech", "기술", "#E6EAF2", "#354665"),
    ("policy", "정책", "#F2E8DE", "#7B573A"),
    ("life", "생활", "#E4F4FF", "#2F759A"),
    ("caution", "주의", "#FFF2D6", "#9F6003"),
    ("blocked", "차단", "#FDE6E6", "#B92F2F"),
)
BADGE_KINDS = tuple(key for key, _label, _bg, _fg in SEMANTIC_BADGES)

# ---- Theme Token(밝은 테마). 키 이름은 소문자 snake_case. 화면 코드는 이 키로만 색을 부른다.
LIGHT = {
    # 바탕·면
    "bg_app": "#F4F7FB", "bg_sidebar": "#F7F9FC", "surface": "#FFFFFF", "surface_2": "#F8FAFD", "surface_selected": "#EEF5FF",
    "surface_hover": "#F4F8FF",
    **{key: value for _name, key, value, _use in TEXT_TOKENS},
    "on_primary": "#FFFFFF",
    # 선 — 테두리·강한 테두리·구분선(새)·가리킬 때 카드 테두리(새)
    "border": "#DCE4F0", "border_strong": "#B8C7DA", "divider": "#E8EDF5", "border_hover": "#AFC7EE",
    # 포커스 — 2px 테두리(`border_focus`)와 바깥 링(`focus_ring`·검색 칸 `focus_ring_input`)
    "border_focus": "#2F6FED", "focus_ring": "#9CC2FF", "focus_ring_input": "#C9DDFF",
    # 주 색상 — `primary`=문서의 Primary 600, `primary_700`=진한 쪽(가리킬 때), `primary_pressed`=눌림, `primary_100`=옅은 면
    "primary": "#2F6FED", "primary_700": "#245ACC", "primary_pressed": "#1D4FAF", "primary_100": "#EAF2FF",
    # 보조 단추(문서 §10.2의 값)
    "secondary_border": "#AFC1D8", "secondary_text": "#28456F",
    # 사이드바(UI-C1a): 현재 메뉴 면·글자(문서의 #DCEAFF·#1F61BC)와 사이드바 오른쪽 선(#E3E9F2) — 1단계 보고 ⑥ 에 '사이드바를 만들 때 더한다' 고 적은 값
    "nav_current_bg": "#DCEAFF", "nav_current_text": "#1F61BC", "sidebar_border": "#E3E9F2",
    # '다음 단계' 목록의 글자·아이콘 색 — `text_secondary` 를 `bg_sidebar` 와 `SOON_OPACITY`(55%) 비율로 섞은 값(시험이 섞은 값과 같은지 견준다). 투명 효과(`QGraphicsOpacityEffect`)는 쓰지 않는다
    "soon_text": "#A3ABB4",
    # 상태색 — 성공·경고·위험·정보와 각자의 옅은 면
    "success": "#159A6C", "success_100": "#E9F8F2", "warning": "#E49A19", "warning_100": "#FFF5DE",
    "danger": "#D94A4A", "danger_100": "#FDECEC", "info": "#2F6FED", "info_100": "#EAF2FF",
    # 위험 **단추** 배경(UI-C1a, D-170): 운영자 2026-11-06 확인 요청 004 의 답 — 위험색(#D94A4A) 위 흰 글자는 4.18 이라 4.5 이상(4.58)이 되도록 #CE4646. 상태색 `danger`(아이콘·사용량 막대·점수 구간)는 문서 값 그대로 둔다.
    "danger_fill": "#CE4646",
    "purple": "#7A5AF8", "purple_100": "#F0ECFF",
    "blog_a_bg": "#E5F0FF", "blog_a_text": "#1456B8", "blog_b_bg": "#FFF0DD", "blog_b_text": "#A95312",
    # 글자로 쓸 때 흰 바탕·자기 옅은 면과의 대비가 4.5 이상이 되게 새 상태색에 맞춰 다시 만든 변형(시험이 못박는다)
    "success_text": "#137D60", "warning_text": "#8F5600", "danger_text": "#BA4247", "purple_text": "#5B3FD0", "primary_text": "#245ACC", "info_text": "#245ACC",
    # 꺼짐 — 보조·고스트 단추의 꺼진 바탕, 주·위험 단추의 꺼진 채움(문서: 흰 글자)
    "disabled_bg": "#EDF1F7", "disabled_fill": "#C5D0E0",
    # 말풍선(툴팁)·토스트·뒤를 덮는 막(scrim)
    "inverse_bg": "#14213D", "inverse_text": "#FFFFFF", "scrim": "#14213D",
    # 그림자의 바탕 색(문서의 rgba(22, 39, 74))
    "shadow_base": "#16274A",
    # 점수 링·사용량 막대의 빈 길(track)
    "track": "#E8EDF5",
    # 점수 구간색(C-Type §9.1) — 80+·65~79·50~64·0~49. 점수 구간은 엔진과 같은 기준(80/65/50)이다
    "score_high": "#159A6C", "score_good": "#2F6FED", "score_mid": "#E49A19", "score_low": "#D94A4A",
    # 구성 막대의 구성별 고정색(C-Type §9.2) — 기존 점수·공공데이터·검색 흐름·기타
    "bar_base": "#8191AA", "bar_data": "#42A5F5", "bar_trend": "#21B77A", "bar_other": "#F4C04B",
    **{f"badge_{key}_bg": bg for key, _label, bg, _fg in SEMANTIC_BADGES},
    **{f"badge_{key}_text": fg for key, _label, _bg, fg in SEMANTIC_BADGES},
}
THEMES = {"light": LIGHT}                       # 어두운 테마를 더할 때는 같은 키를 가진 사전을 여기에 넣는다(사용자 화면에 선택 기능은 두지 않는다)
SCRIM_ALPHA = 0.38

# ---- Typography Token — 이름 → (크기 px, 굵기, 행간 배수). px 는 논리 픽셀이라 Qt6 가 화면 배율을 알아서 곱한다(배율을 직접 곱하지 않는다).
@dataclass(frozen=True)
class TypeStyle:
    size: int
    weight: int
    line_height: float


# C-Type §5.2·§5.3: H1 24·H2 20·H3 17(새)·Body L 15/400·Body 14·Body S 13·Caption 12·Micro 11/500(새), 행간 H1·H2 1.25·H3 1.35·본문 1.45~1.55·캡션 1.35.
# `score_sm`·`score_lg` 는 점수 링 가운데 숫자(문서 18~22 Bold) — 글자 역할(라벨)이 아니라 그릴 때만 쓴다.
TYPE = {
    "display": TypeStyle(28, 700, 1.30), "h1": TypeStyle(24, 700, 1.25), "h2": TypeStyle(20, 700, 1.25), "h3": TypeStyle(17, 600, 1.35),
    "body_lg": TypeStyle(15, 400, 1.55), "body": TypeStyle(14, 400, 1.50), "small": TypeStyle(13, 400, 1.50), "caption": TypeStyle(12, 400, 1.35), "micro": TypeStyle(11, 500, 1.35),
    "button": TypeStyle(14, 600, 1.20), "metric": TypeStyle(28, 700, 1.20), "mono": TypeStyle(13, 400, 1.50),
    "score_sm": TypeStyle(18, 700, 1.20), "score_lg": TypeStyle(22, 700, 1.20),
}
# 글자 역할 → 그 역할의 글자 색(Text Token 키). 화면은 역할 이름만 고른다.
ROLE_TEXT = {
    "display": "text_strong", "h1": "text_strong", "h2": "text_strong", "h3": "text_strong", "metric": "text_strong",
    "body_lg": "text_primary", "body": "text_primary", "button": "text_primary", "mono": "text_primary",
    "small": "text_secondary", "caption": "text_secondary", "micro": "text_secondary", "sub": "text_secondary", "muted": "text_muted",
}
ROLE_STYLE = {"sub": "body", "muted": "body"}      # 크기·굵기를 다른 역할에서 빌려 쓰는 역할

# ---- 간격(4px 격자)·모서리·그림자
# `SPACE`(문서의 space-1~10)와 `SHADOW`(카드 그림자 3종)는 UI-C0 의 새 부품이 쓰기 시작했다 — 옛 화면(홈·설정)의 여백은 아직 숫자를 직접 적은 채로 있다(UI-C1 에서 정리한다).
# **아직 안 쓰는 값**: `COPY_FEEDBACK_MS` 와 `MOTION_MS` 의 hover·page — 정해만 두었고 화면 코드는 쓰지 않는다(시험 `test_the_tokens_nobody_uses_yet_are_the_documented_ones` 가 지킨다).
SPACE = {"1": 4, "2": 8, "3": 12, "4": 16, "5": 20, "6": 24, "8": 32, "10": 40, "12": 48}
# 모서리: 카드 12·단추 10(8~10)·입력 8·칩 17(15~17)·배지 12(24px 높이의 알약)·구성 막대 6·사용량 막대 4·썸네일 12·말풍선 8·행 12·사이드바 메뉴 8(C-Type §14.1, UI-C1a)
RADIUS = {"button": 10, "input": 8, "card": 12, "chip": 17, "badge": 12, "gauge": 6, "usage": 4, "thumb": 12, "tooltip": 8, "row": 12, "nav": 8}


@dataclass(frozen=True)
class ShadowStyle:
    dx: int
    dy: int
    blur: int
    alpha: float
    color_key: str                                  # 팔레트 키 — 순수 검정을 쓰지 않는다


# 카드 그림자 3종(C-Type §7.1): 가만히 `0 2 8 .06` · 가리킬 때 `0 6 16 .10` · 선택됨 `0 6 18 .14`(파랑). Qt 스타일시트로는 그림자를 못 그려 `QGraphicsDropShadowEffect` 로 입힌다(`ui/qt/theme.py`).
SHADOW = {
    "card": ShadowStyle(0, 2, 8, 0.06, "shadow_base"),
    "hover": ShadowStyle(0, 6, 16, 0.10, "shadow_base"),
    "selected": ShadowStyle(0, 6, 18, 0.14, "primary"),
}
# 카드 3상태(C-Type §7.1): 기본 = 1px 테두리·가리킴 = 테두리 색만 바뀜·선택 = 2px 파란 테두리. (테두리 폭, 테두리 색 키, 그림자 키). 포커스 링은 따로 위에 겹쳐 그린다.
CARD_STATES = {
    "default": (1, "border", "card"),
    "hover": (1, "border_hover", "hover"),
    "selected": (2, "primary", "selected"),
}
FOCUS_RING_PX = 2                                   # 포커스 테두리 두께(2px 이상) — 직접 그리는 부품은 그 바깥에 옅은 링(`focus_ring`)을 한 겹 더 그린다

# ---- 크기 — 단추 높이: 큰 주 단추 44 · 표준 40 · 작은 34(그려지는 높이) · 아이콘 단독 36 · 누르는 칸은 모두 36 이상(`hit`)
SIZE = {
    "hit": 36, "control": 40, "control_primary": 44, "control_sm": 34, "icon_button": 36, "chip_h": 34, "menu_h": 44, "badge_h": 24,
    "thumb": 64, "thumb_radius": 12, "input_h": 40, "toggle_w": 44, "toggle_h": 26, "skeleton_line": 14, "acc_h": 52,       # acc_h: 접이식 머리 한 줄의 최소 높이(누르는 칸 36 이상)
    # C-Type 새 값(UI-C0): 누르는 칸 문서 기준(최소 32·권장 40 — 이 앱은 36 을 기본으로 지킨다)·검색 칸 40·탭 46(44~48)·표 머리 40(36~40)·표 행 48(44~52). 검색 칸·표는 아직 안 쓴다
    "hit_min": 32, "hit_comfort": 40, "search_h": 40, "tab_h": 46, "table_head_h": 40, "table_row_h": 48,
    # 점수 링 카드용 44(40~44)·상세용 72(68~80)·구성 막대 높이 12(10~12)·사용량 막대 높이 8
    "ring_card": 44, "ring_detail": 72, "gauge_h": 12, "usage_h": 8,
    # 새 홈(UI-C1d, D-201): KPI 카드 최소 높이 96 · 추천 줄(점수 링 44 + 위아래 여백 10) 최소 높이 64 · 글 줄(작성 중 초안·최근 발행) 최소 높이 56 · 추천 줄 왼쪽 점수 칸의 최소 폭(링 44 + 간격 + 구간 이름·변화량 글)
    "kpi_min_h": 96, "board_row_h": 64, "list_row_h": 56, "board_score_w": 124,
}
RING_STROKE_RATIO = 0.11                            # 링 선 두께 = 지름의 11%(문서 10~12%)
ICON = {"nav": 18, "card": 22, "button": 18, "button_sm": 16, "empty": 44, "box": 40, "box_radius": 12, "gap": 10, "badge": 14, "trend": 16}
LAYOUT = {
    "dialog": 480, "content_max": 1280, "page_margin": 24, "gap": 20,
    "window": (1440, 900), "window_min": (900, 560),
    "kpi_min_col": 190,            # 홈 KPI 카드 한 칸의 최소 폭 — 본문 폭에 따라 4열 → 2열 → 1열(`part_rules.home_kpi_columns`)
    "section_min_col": 480,        # 홈 구역(추천 둘·작성 중 초안·최근 발행) 한 칸의 최소 폭 — 두 칸이 들어가면 나란히, 아니면 위아래로(`part_rules.home_section_columns`). 추천 줄이 점수 칸(링·구간 이름)과 채널 열쇠를 빼고도 제목 한두 줄을 담으려면 한 칸이 이만큼은 있어야 한다
    "posts_min_col": 400,          # 작성 중 초안·최근 발행(글 줄) 한 칸의 최소 폭 — 글 줄은 제목과 상태·시각뿐이라 추천 줄보다 좁아도 되어 한 단계 좁은 창까지 나란히 둔다(`part_rules.home_posts_columns`)
    "blogs_beside_min": 780,       # 블로그 관리(P4b): 본문 폭이 이 이상일 때만 슬롯 목록을 폼 옆(왼쪽)에 둔다(아니면 폼 위) — 1366×768 노트북의 125%(논리 1093 → 본문 약 820)에서도 옆에 두어 아래 고정 행동 줄이 보이게 780
    "blogs_list": 320,             # 블로그 관리: 옆에 둘 때 슬롯 목록의 폭
    "form_scroll_min_h": 160,      # 블로그 관리: 폼 안쪽 스크롤 영역의 최소 높이(알림 줄이 붙은 1366×768 노트북의 125% — 논리 높이 614 — 에서도 아래 고정 행동 줄이 창 안에 들어가게 240→160. 남는 높이는 이 영역이 가져간다) — 아래 고정 행동 줄은 늘 보이고 칸들만 이 안에서 스크롤된다
    "list_scroll_min_h": 200,      # 블로그 관리: 슬롯 목록 스크롤 영역의 최소 높이(슬롯 카드 다섯이 한 화면보다 길면 이 안에서 스크롤 — 페이지가 늘어나 저장 단추가 밀려나지 않게)
    "list_stacked_h": 300,         # 블로그 관리: 폭이 좁아 목록이 폼 위로 올라왔을 때 목록 스크롤 영역의 최대 높이
}
# C-Type 새 틀 크기(§2·§14·§16) — 상단 앱 바·사이드바·서랍은 UI-C1a 부터 이 값을 쓴다(옛 `LAYOUT` 은 본문·대화상자·창 크기가 그대로 쓴다). 범위는 (최소, 최대).
# **상세 창은 운영자 결정(2026-11-06 확인 요청 004, D-174)이 문서 값을 이긴다**: Qt **논리 폭** ≥ 1600 이면 고정 420~500(문서는 420~520)·카드 3열 / 1366~1599 이면 고정 400(문서는 400~440)·카드 2열 / 1366 미만이면 서랍·카드 2열.
# 사이드바 폭 208 은 범위(184~208)의 끝이다(D-172).
# 고정 상세 창 **위젯**은 주제 후보 화면과 함께 만든다 — 지금은 규칙(`ui/core/part_rules.py` 의 `detail_layout`)과 이 상수뿐이다(홈의 상세는 서랍).
FRAME = {
    "app_bar": 60, "app_bar_range": (56, 64), "sidebar": 208, "sidebar_range": (184, 208), "detail": 460, "detail_range": (420, 500), "detail_narrow": 400,
    "window_min": (1180, 720), "window_default": (1600, 960),
    "fixed_detail_min": 1600, "narrow_detail_min": 1366,            # 논리 폭 ≥ 1600 상세 창 고정 420~500 · 1366~1599 고정 400 · 그보다 좁으면 서랍
    "detail_max_at": 1920,                                          # 고정 상세 창 폭은 논리 폭 1600 에서 420, 1920 이상에서 500, 그 사이는 비례(D-174)
    "detail_columns_wide": 3, "detail_columns_narrow": 2,           # 카드 열 수 — 고정 상세 창이 넓을 때 3열, 좁을 때·서랍일 때 2열
    "drawer": 420, "drawer_max_ratio": 0.92,                        # 서랍 폭(창의 92% 이하) — 지금 홈의 서랍이 그대로 쓰는 값(옛 `LAYOUT["drawer"]`)
    "workspace_pad": 24, "workspace_pad_narrow": 16, "pane_pad": (20, 24), "sidebar_pad": 12,
}
# '준비 중' 인 '다음 단계' 메뉴의 흐림(UI-C1a, D-172) — 글자·아이콘 색 `soon_text` 는 글자 색(`text_secondary`) 55% + 사이드바 바탕 45% 를 섞은 값이다(운영자의 50~60%). `QGraphicsOpacityEffect` 는 쓰지 않는다(틀 안 글자까지 다시 그려 흐려질 수 있다).
SOON_OPACITY = 0.55
# 카드 규격(§3.3·§7.1) — 폭 230 이상(권장 260~300)·높이 280~330·안쪽 여백 16·이미지 높이 120~132. **상수만 정해 두었고 카드 부품은 다음 묶음**(UI-C1 이후)이 쓴다.
CARD = {"pad": 16, "gap": 16, "gap_narrow": 12, "min_w": 230, "w_range": (260, 300), "h_range": (280, 330), "image_h": 120}
MOTION_MS = {"hover": 120, "page": 180, "panel": 200}        # 화면 전환 150~220 · 호버 100~150 · 서랍·접이식 180~240 — **서랍(panel)만 쓴다**, hover·page 는 값만 있다(효과를 입히지 않는다)
TOAST_MS = 3500                                               # 안내(토스트)가 보이는 시간 3~4초
COPY_FEEDBACK_MS = 1800                                       # 안 쓰는 값 — 복사한 단추가 '복사됨' 으로 보이는 시간(이미지 화면 묶음에서 쓴다). 지금은 토스트(TOAST_MS)만 쓴다

# 계열 이름 → (아이콘 색 키, 아이콘 바탕 색 키, 글자 색 키) — 요약 카드·주제 아이콘(진한 면을 쓰지 않고 아이콘 바탕과 숫자에만)
TONES = {
    "blue": ("primary", "primary_100", "primary_text"), "green": ("success", "success_100", "success_text"),
    "purple": ("purple", "purple_100", "purple_text"), "orange": ("warning", "warning_100", "warning_text"),
    "red": ("danger", "danger_100", "danger_text"), "slate": ("text_secondary", "surface_2", "text_secondary"),
}


# 채널 색 프리셋(P4b — 운영자 확정 답변 2026-11-06 §5: 값은 운영자 문서 그대로이고 임의 색 입력은 없다). 채널 배지·프로필 카드 테두리·선택 상태에만 쓰고 앱 테마(밝은 파랑)는 그대로다.
# **글자색으로 쓰지 않는다**: 프리셋 Primary 는 연한 바탕 위에서 대비가 4.70(따뜻한 생활 톤)·4.15(차분한 기술 톤)이고 Secondary·Accent 는 3.74 이하라 작은 글자 기준(4.5)을 못 넘는다 —
# 그래서 배지 글자는 `text_strong`(대비 16 이상)이고 프리셋 색은 테두리·점·견본에만 쓴다(색만으로 구분하지 않는다 — 이름 글자가 늘 함께 있다). Primary 는 흰 바탕 대비 4.99·4.55 라 테두리(3 이상)로 충분하다.
CHANNEL_PRESETS = {
    "warm_lifestyle": {"primary": "#A85A44", "secondary": "#4F8B78", "accent": "#F2B38D", "surface": "#FFF7EE"},
    "cool_technology": {"primary": "#2F6FED", "secondary": "#19B8C9", "accent": "#55DDE0", "surface": "#EEF5FF"},
}


def preset_colors(preset):
    """색 프리셋 이름 → `{primary, secondary, accent, surface}`(없는 이름·None·빈 글은 None)."""
    return CHANNEL_PRESETS.get(preset) if isinstance(preset, str) else None


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


def badge_colors(colors, kind):
    """의미별 배지 열쇠 → (배경, 글자)."""
    return colors[f"badge_{kind}_bg"], colors[f"badge_{kind}_text"]


def badge_label(kind):
    """의미별 배지 열쇠 → 기본 글자(한국어 이름)."""
    return next(label for key, label, _bg, _fg in SEMANTIC_BADGES if key == kind)


def shadow_rgba(colors, name):
    """그림자 이름 → (dx, dy, blur, 'rgba(...)' 글자). 색은 팔레트 키에서만 온다."""
    style = SHADOW[name]
    return style.dx, style.dy, style.blur, rgba(colors[style.color_key], style.alpha)


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
