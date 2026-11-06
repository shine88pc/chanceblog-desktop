"""직접 그린 선형 아이콘 한 벌 — 24×24 눈금, 선 굵기 1.75(허용 1.75~2), 둥근 끝·둥근 모서리로 통일(채운 아이콘을 섞지 않는다).

경로 문자열을 이 파일에서만 관리하고 Qt 는 QtSvg 로 그려 어느 화면 배율에서도 선명하다(그림 파일·외부 아이콘 라이브러리 없음). 같은 의미는 어디서나 같은 아이콘이다(`MEANING`).
크기 규칙은 `tokens.ICON`(사이드바 18 · 요약 카드 22(바탕 40×40) · 단추 안 18(작은 단추 16) · 빈 화면 34), 의미 표와 설명은 docs/UI_ICONS.md.
"""
from __future__ import annotations

STROKE = 1.75
STROKE_RANGE = (1.75, 2.0)

ICONS = {
    # 메뉴
    "home": '<path d="M4 11.5 12 4.5l8 7"/><path d="M6.5 10v9.5h11V10"/><path d="M10 19.5v-5h4v5"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "draft": '<path d="M7 3.5h7.5l4 4v13H7z"/><path d="M14.5 3.5v4h4"/><path d="M9.5 12.5H16M9.5 16H16"/>',
    # UI-C1a(D-172): 새 의미표(C-Type §6.2 — 원통=공공데이터·차트=분석·기어=설정·슬라이더=조합·필터·씨앗=Seed)에 맞춰 이름과 모양을 정리했다.
    # 옛 `history`(막대 차트)는 `chart`(분석)로, 옛 `blogs`(원통)는 `database`(공공데이터)로, 옛 `settings`(슬라이더)는 `sliders`(조합·필터)로 이름만 바뀌었고, `settings` 는 **기어**가 되었다.
    "chart": '<path d="M5.5 20v-8M12 20V5M18.5 20v-5"/><path d="M3.5 20.5h17"/>',
    "database": '<ellipse cx="12" cy="6.5" rx="7" ry="3"/><path d="M5 6.5v11c0 1.7 3.1 3 7 3s7-1.3 7-3v-11"/><path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    "sliders": '<path d="M4 7h16M4 12h16M4 17h16"/><circle cx="9" cy="7" r="2" fill="none"/><circle cx="15" cy="12" r="2"/><circle cx="8" cy="17" r="2"/>',
    "settings": '<path d="M10.28 5.11L10.55 2.81 L13.45 2.81 L13.72 5.11A7.1 7.1 0 0 1 15.66 5.91L17.47 4.48 L19.52 6.53 L18.09 8.34A7.1 7.1 0 0 1 18.89 10.28L21.19 10.55 L21.19 13.45 L18.89 13.72A7.1 7.1 0 0 1 18.09 15.66L19.52 17.47 L17.47 19.52 L15.66 18.09A7.1 7.1 0 0 1 13.72 18.89L13.45 21.19 L10.55 21.19 L10.28 18.89A7.1 7.1 0 0 1 8.34 18.09L6.53 19.52 L4.48 17.47 L5.91 15.66A7.1 7.1 0 0 1 5.11 13.72L2.81 13.45 L2.81 10.55 L5.11 10.28A7.1 7.1 0 0 1 5.91 8.34L4.48 6.53 L6.53 4.48 L8.34 5.91A7.1 7.1 0 0 1 10.28 5.11z"/><circle cx="12" cy="12" r="3"/>',
    "book": '<path d="M12 6.5C10.5 5.3 8.2 4.8 5 4.8v13c3.2 0 5.5.5 7 1.7 1.5-1.2 3.8-1.7 7-1.7v-13c-3.2 0-5.5.5-7 1.7z"/><path d="M12 6.5v13"/>',
    # 동작
    "bell": '<path d="M6 17v-6a6 6 0 0 1 12 0v6l1.5 1.5h-15z"/><path d="M10 21h4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3.5 7v11c0 1 .7 1.5 1.5 1.5h14c.8 0 1.5-.5 1.5-1.5V9.5c0-.8-.7-1.5-1.5-1.5h-7.5l-2-2.5H5c-.8 0-1.5.7-1.5 1.5z"/>',
    "calendar": '<path d="M4.5 6.5h15v13h-15z"/><path d="M4.5 10.5h15M8.5 4v4M15.5 4v4"/><path d="m9 15 2 2 4-4"/>',
    "bulb": '<path d="M9.5 17h5M10 20h4"/><path d="M12 3.5c-3.3 0-5.5 2.5-5.5 5.5 0 2.2 1.2 3.7 2.5 5 .6.6.5 1.500.5 3h5c0-1.500-.1-2.400.5-3 1.300-1.300 2.500-2.800 2.500-5 0-3-2.200-5.500-5.500-5.500z"/>',
    "check_circle": '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.300 2.500 2.500 4.800-5.300"/>',
    "trend_up": '<path d="m4 16 5.500-5.500L13 14l7-7"/><path d="M15 7h5v5"/>',
    "trend_flat": '<path d="M4 12h15"/><path d="m14.500 7.500 4.500 4.500-4.500 4.500"/>',
    "trend_down": '<path d="m4 8 5.500 5.500L13 10l7 7"/><path d="M15 17h5v-5"/>',
    "arrow_right": '<path d="M5 12h14"/><path d="m13.500 6.500 5.500 5.500-5.500 5.500"/>',
    "chevron_down": '<path d="m6 9.500 6 6 6-6"/>',
    "chevron_right": '<path d="m9.500 6 6 6-6 6"/>',
    "chevron_up": '<path d="m6 14.500 6-6 6 6"/>',
    "x": '<path d="m6.500 6.500 11 11M17.500 6.500l-11 11"/>',
    "copy": '<path d="M8.500 8.500h11v11h-11z"/><path d="M5.500 15.500v-11h11"/>',
    "check": '<path d="m5.500 12.500 4.500 4.500 8.500-9.500"/>',
    "edit": '<path d="M4.500 19.500 5.500 15l10-10 3.500 3.500-10 10z"/><path d="m13.500 7 3.500 3.500"/>',
    "external": '<path d="M13 5h6v6"/><path d="m19 5-8 8"/><path d="M17 14v5H5V7h5"/>',
    "refresh": '<path d="M19.500 12a7.500 7.500 0 1 1-2.500-5.600"/><path d="M18 3.500v4h-4"/>',
    "more": '<circle cx="6" cy="12" r="1.200"/><circle cx="12" cy="12" r="1.200"/><circle cx="18" cy="12" r="1.200"/>',
    "more_vertical": '<circle cx="12" cy="6" r="1.200"/><circle cx="12" cy="12" r="1.200"/><circle cx="12" cy="18" r="1.200"/>',
    "clock": '<circle cx="12" cy="12" r="8.500"/><path d="M12 7.500V12l3 2"/>',
    "user": '<circle cx="12" cy="8" r="3.500"/><path d="M5 20c.5-4 3.500-5.500 7-5.500s6.500 1.500 7 5.500"/>',
    # 상태 화면
    "alert": '<path d="m12 4 9 15.500H3z"/><path d="M12 10v4M12 16.800v.2"/>',
    "inbox": '<path d="m4 13 2.500-7.500h11L20 13v6H4z"/><path d="M4 13h5l1 2.500h4l1-2.500h5"/>',
    "cloud_off": '<path d="M7 18.500h10a4 4 0 0 0 .8-7.900A6 6 0 0 0 7 9.500a4.500 4.500 0 0 0 0 9z"/><path d="m4 4 16 16"/>',
    # 정밀 보완(UI-POLISH v1.1.0)에서 더한 것 — 같은 선 굵기·같은 눈금
    "calendar_check": '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M8 3v4M16 3v4M3.5 10h17"/><path d="m9 15 2.2 2.2L15.5 13"/>',
    "pause_circle": '<circle cx="12" cy="12" r="8.5"/><path d="M10 9v6M14 9v6"/>',
    "info_circle": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "key": '<circle cx="8" cy="15" r="3.5"/><path d="m10.5 12.5 8-8M15 8l2.5 2.5M17.5 5.5 20 8"/>',
    "trash": '<path d="M4.5 7h15"/><path d="M9.5 7V4.5h5V7"/><path d="m6.5 7 .8 12.5h9.4L17.5 7"/><path d="M10 11v5M14 11v5"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="m4 17 5-4.5 3.5 3 3-2.5 4.5 4"/>',
    "upload": '<path d="M12 16V5"/><path d="m7.5 9.5 4.5-4.5 4.5 4.5"/><path d="M4.5 16v2.5A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5V16"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="9.5" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    "shield": '<path d="M12 3.5 5 6v5.5c0 4.2 2.8 7.2 7 9 4.2-1.8 7-4.8 7-9V6z"/><path d="m9 12 2 2 4-4"/>',
    # 브랜드·장식
    "radio": '<circle cx="12" cy="12" r="8.500"/>',
    "leaf": '<path d="M5 19C5 11 10 5 19 5c0 9-5 14-14 14z"/><path d="M5 19 12.500 11.500"/>',
    "sprout": '<path d="M12 20v-9"/><path d="M12 11c0-3.500-2.500-5.500-6-5.500C6 9 8 11 12 11z"/><path d="M12 13.500c0-3 2-5 6-5 0 3-2 5-6 5z"/>',
    # 주제 아이콘(썸네일 대신 쓰는 자리 표시용)
    "t_droplet": '<path d="M12 3.500S6 10 6 14a6 6 0 0 0 12 0c0-4-6-10.500-6-10.500z"/>',
    "t_bolt": '<path d="M13 3 5.500 13.500h6L10.500 21l8-10.500h-6z"/>',
    "t_laptop": '<path d="M5.500 6.500h13v9h-13z"/><path d="M3.500 19h17"/>',
    "t_calc": '<path d="M7 3.500h10v17H7z"/><path d="M9.500 7.500h5M9.500 11.500h1M13.500 11.500h1M9.500 15h1M13.500 15h1"/>',
    "t_box": '<path d="M5 8h14v11H5z"/><path d="m5 8 2-3.500h10L19 8"/><path d="M9 12.500h6"/>',
    "t_headphones": '<path d="M5 15v-3a7 7 0 0 1 14 0v3"/><path d="M5 14h3v5H5zM16 14h3v5h-3z"/>',
    "t_coffee": '<path d="M5.500 9h11v6a4 4 0 0 1-4 4h-3a4 4 0 0 1-4-4z"/><path d="M16.500 10.500h1.500a2 2 0 0 1 0 4h-1.500"/><path d="M8.500 4v2M12 4v2"/>',
    "t_spark": '<path d="m12 4 1.800 5.200L19 11l-5.200 1.800L12 18l-1.800-5.200L5 11l5.200-1.800z"/>',
}


def svg(name, size=20, color="currentColor", stroke=STROKE):
    """아이콘 하나를 완전한 SVG 글로 — QSvgRenderer 가 읽어 어느 크기에서나 같은 모양을 얻는다."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


# 기능 → (아이콘, 강조 색 계열) — 명세 §4.2 의 의미 표. 같은 의미는 어느 화면에서나 같은 아이콘을 쓴다(docs/ICON_SYSTEM.md).
MEANING = {
    "home": ("home", "blue"), "topics": ("search", "blue"), "draft": ("draft", "blue"), "history": ("calendar_check", "purple"), "seed": ("sprout", "green"), "blogs": ("book", "slate"), "settings": ("settings", "slate"),
    "recommended": ("draft", "blue"), "done": ("check_circle", "green"), "published": ("calendar_check", "purple"), "ideas": ("bulb", "orange"),
    "trend_up": ("trend_up", "green"), "trend_flat": ("trend_flat", "orange"), "trend_down": ("trend_down", "red"),
    "copy": ("copy", "blue"), "external": ("external", "slate"), "hold": ("pause_circle", "orange"), "error": ("alert", "red"), "info": ("info_circle", "blue"),
    "image": ("image", "blue"), "key": ("key", "slate"), "delete": ("trash", "red"), "upload": ("upload", "slate"), "secure": ("lock", "green"),
    "empty": ("inbox", "blue"), "offline": ("cloud_off", "orange"), "partial": ("alert", "orange"), "refresh": ("refresh", "blue"), "close": ("x", "slate"), "detail": ("chevron_right", "slate"),
    "more_menu": ("more_vertical", "slate"), "quick_new": ("plus", "blue"), "tip": ("bulb", "green"),
}
