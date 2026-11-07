"""사이드바(UI-C1a, D-172) — 폭 208(184~208)·3묶음(핵심 작업 / 데이터·관리 / 시스템 — **묶음 이름은 그 묶음에 실제 메뉴가 있을 때만** 보인다)·실제 Navigation(완성된 화면 홈·설정)·
'다음 단계' 목록(열 수 없는 항목)·하단은 브랜드와 버전뿐. 채널 바로가기는 표시하지 않는다(주제 후보 화면과 채널 필터가 생기기 전 — 운영자 결정).

**'다음 단계' 목록**(운영자가 허용한 절충 — 미완성 화면의 이름만 보여 준다): 클릭 불가(단추·신호 0)·**Tab 대상 제외**(`NoFocus`)·글자·아이콘 색을 바탕과 55% 섞은 토큰 색(`soon_text` — 투명 효과 `QGraphicsOpacityEffect` 는 쓰지 않는다)·
'준비 중' 배지(글자가 있는 중립 배지)·실제 Navigation 과 구분(작은 제목 '다음 단계'·가리켜도 변화 없음·기본 화살표 커서)·미완성 화면으로 가는 이동 경로 0개. 화면 읽기용 이름은 '준비 중 — 아직 열 수 없는 화면'.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout

from ..core import tokens as K
from ..core.app_state import NEXT_STEPS, nav_groups
from ..core.text import T
from . import components as UI
from . import theme


class SoonItem(QFrame):
    """'다음 단계' 목록의 한 줄 — 아이콘 + 이름 + '준비 중' 배지. 단추가 아니다: 눌러도 아무 일이 없고(마우스 이벤트를 처리하지 않는다) Tab 이 오지 않으며 가리켜도 모양이 바뀌지 않는다."""

    def __init__(self, name, icon_name):
        super().__init__()
        self.setObjectName("soonitem")
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.ArrowCursor)
        self.setMinimumHeight(K.SIZE["hit_min"])                                            # 줄 높이만(32) — 누르는 칸이 아니다. 최소 창(900×560)의 높이 안에 사이드바 전체가 들어가게 한다
        self.setAccessibleName(T["nav_soon_item_a11y"].format(name=name))
        row = QHBoxLayout(self)
        row.setContentsMargins(K.SPACE["2"], 0, K.SPACE["1"], 0)
        row.setSpacing(K.SPACE["2"])
        self.icon = theme.IconWidget(icon_name, theme.colors()["soon_text"], K.ICON["nav"])
        self.name = UI.ElidedLabel(name, "small")
        self.name.setProperty("soon", True)                                                # 스타일시트가 55% 섞은 색을 입힌다
        self.name.setToolTip("")                                                           # 가리켜도 아무 변화가 없다(말풍선 없음)
        self.badge = UI.Badge("muted", T["ready_prep"])                                    # 색만이 아니라 글자 '준비 중'
        self.badge.setProperty("compact", True)                                            # 좁은 사이드바 안이라 안쪽 여백과 글자를 작게(11px)
        row.addWidget(self.icon)
        row.addWidget(self.name, 1)
        row.addWidget(self.badge)


class Sidebar(QFrame):
    def __init__(self, navigate, version_info):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(K.FRAME["sidebar"])
        self.setAccessibleName(T["nav_menu"])
        pad = K.FRAME["sidebar_pad"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad, K.SPACE["2"], pad, K.SPACE["2"])                  # 위아래 8 — 메뉴가 하나 늘어(블로그 관리, P4b D-210) 최소 창(900×560)에서도 사이드바가 들어가게 세로 여백을 줄였다(옛 16)
        layout.setSpacing(K.SPACE["1"])
        self.nav_buttons = {}                                                              # 실제로 열 수 있는 화면(홈·설정)만
        self.group_titles = {}                                                             # 묶음 이름 — 실제 메뉴가 있는 묶음만 있다
        for index, (group_key, label_key, items) in enumerate(nav_groups()):
            if index:
                layout.addSpacing(K.SPACE["2"])                                                 # 묶음 사이 8(옛 12)
            title = UI.label(T[label_key], "micro")
            title.setContentsMargins(K.SPACE["3"], 0, 0, K.SPACE["1"])
            self.group_titles[group_key] = title
            layout.addWidget(title)
            for key, name_key, icon_name in items:
                button = UI.NavButton(T[name_key], icon_name, T["nav_a11y"].format(name=T[name_key]))
                button.setProperty("focus_key", "nav:" + key)
                button.clicked.connect(lambda _=False, k=key: navigate(k))
                layout.addWidget(button)
                self.nav_buttons[key] = button
        self.soon_list = self._soon_list()
        if self.soon_list is not None:
            layout.addSpacing(K.SPACE["2"])                                                 # '다음 단계' 앞 8(옛 20)
            layout.addWidget(self.soon_list)
        layout.addStretch(1)
        layout.addWidget(self._brand(version_info))

    @staticmethod
    def _soon_list():
        if not NEXT_STEPS:
            return None
        box = QFrame()
        box.setObjectName("navsoon")
        box.setFocusPolicy(Qt.NoFocus)
        box.setAccessibleName(T["nav_soon_a11y"])
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        title = UI.label(T["nav_soon_title"], "micro")
        title.setContentsMargins(K.SPACE["3"], 0, 0, K.SPACE["1"])
        layout.addWidget(title)
        box.items = []
        for _key, name_key, icon_name in NEXT_STEPS:
            item = SoonItem(T[name_key], icon_name)
            layout.addWidget(item)
            box.items.append(item)
        box.title = title
        return box

    @staticmethod
    def _brand(version_info):
        """하단 — 브랜드와 버전뿐(한 줄 소개는 상단 앱 바로 갔다). 버전은 `v0.0.0`, 못 읽으면 개발 화면에서는 `개발 버전`."""
        card = QFrame()
        card.setObjectName("brandcard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(K.SPACE["4"], K.SPACE["2"], K.SPACE["4"], K.SPACE["2"])
        inner.setSpacing(K.SPACE["1"])
        inner.addWidget(theme.IconWidget("sprout", theme.colors()["success"], 24), 0, Qt.AlignHCenter)
        name = UI.label(T["brand_version"], "caption", wrap=True)
        name.setAlignment(Qt.AlignCenter)
        inner.addWidget(name)
        version = UI.label(version_info.text, "caption")
        version.setAlignment(Qt.AlignCenter)
        version.setObjectName("brandversion")
        inner.addWidget(version)
        card.version_label = version
        return card
