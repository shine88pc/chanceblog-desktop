"""탭 줄(`TabBar`)과 아래 고정 행동 줄(`ActionBar`) — 규칙은 `ui/core/part_rules.py`(순수), 색·크기는 토큰(스타일시트), 여기서는 위젯 조립만 한다(C-Type §8.2·§8.3·§10.5).

- `TabBar`: 밑줄형 탭(높이 46, 활성은 Primary 700 글자 + 2px 밑줄). 탭 줄에서는 Tab 키 정거장이 하나(고른 탭)이고 ←·→·Home·End 로 탭을 옮긴다. 접근 이름 `○○ 탭, 4개 중 2번째`.
- `ActionBar`: 아래에 붙이는 행동 줄 — 주요 1(큰 단추 44)·보조 최대 3·3차(글자만) 여러 개·위험 3차 최대 1·`더보기 ⋮`. 폭이 모자라면 위험·3차 → 보조 순서로 `더보기` 메뉴로 접고, 더 좁으면 주요 행동 하나만 남는다.
어떤 화면에도 아직 연결하지 않은 독립 부품이다(오른쪽 상세 창에 붙이는 것은 다음 묶음).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QMenu, QPushButton

from ..core import tokens as K
from ..core.part_rules import check_actions, plan_actions, tab_move
from ..core.text import T
from .components import Button, IconButton, with_tooltip

_KEYS = {Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Home: "home", Qt.Key_End: "end"}


class _Tab(QPushButton):
    def __init__(self, bar):
        super().__init__()
        self._bar = bar

    def keyPressEvent(self, event):
        key = _KEYS.get(event.key())
        if key is not None:
            self._bar.move_by_key(key)
            event.accept()
        else:
            super().keyPressEvent(event)


class TabBar(QFrame):
    """밑줄형 탭 줄 — `tabs` 는 `(열쇠, 글자)` 의 나열. 탭을 고르면 `changed(열쇠)` 신호가 나간다."""
    changed = Signal(str)

    def __init__(self, tabs, current=None, accessible=None):
        super().__init__()
        tabs = [(str(key), str(text)) for key, text in tabs]
        if not tabs:
            raise ValueError("탭이 하나도 없어요")
        if len({key for key, _text in tabs}) != len(tabs):
            raise ValueError("탭 열쇠가 겹쳐요")
        self.setObjectName("tabbar")
        self.setAccessibleName(accessible or T["cd_tabs_a11y"])
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(K.SPACE["2"])
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.keys = [key for key, _text in tabs]
        self.buttons = {}
        for index, (key, text) in enumerate(tabs):
            button = _Tab(self)
            button.setText(text)
            button.setProperty("tab", True)
            button.setProperty("focus_key", "tab:" + key)
            button.setCheckable(True)
            button.setMinimumHeight(K.SIZE["tab_h"])
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(T["cd_tab_a11y"].format(name=text, total=len(tabs), index=index + 1))
            button.clicked.connect(lambda _=False, k=key: self.set_current(k))
            self._group.addButton(button)
            self.buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)
        self._current = None
        self.set_current(current if current in self.buttons else self.keys[0])

    def current(self):
        return self._current

    def set_current(self, key):
        if key not in self.buttons:
            raise KeyError(key)
        changed = key != self._current
        self._current = key
        for name, button in self.buttons.items():
            button.setChecked(name == key)
            button.setFocusPolicy(Qt.StrongFocus if name == key else Qt.NoFocus)      # Tab 정거장은 고른 탭 하나(화살표로 옮긴다)
        if changed:
            self.changed.emit(key)

    def move_by_key(self, key):
        """←·→·Home·End — 고른 탭을 옮기고 포커스도 따라간다."""
        target = self.keys[tab_move(self.keys.index(self._current), len(self.keys), key)]
        self.set_current(target)
        self.buttons[target].setFocus(Qt.TabFocusReason)


class ActionBar(QFrame):
    """아래 고정 행동 줄 — `actions` 는 `{"key", "text", "kind"}`(종류 `primary`·`secondary`·`tertiary`·`danger`)의 나열(주요 1·보조 ≤3·위험 ≤1 — 어기면 ValueError),
    `more_items` 는 처음부터 `더보기 ⋮` 메뉴에 들어갈 `{"key", "text"}` 의 나열. 누르면 `triggered(열쇠)` 신호가 나간다."""
    triggered = Signal(str)

    def __init__(self, actions, more_items=(), accessible=None):
        super().__init__()
        actions = [dict(spec) for spec in actions]
        self.kinds = check_actions(spec["kind"] for spec in actions)
        self.specs, self.more_items = actions, [dict(item) for item in more_items]
        self.setObjectName("actionbar")
        self.setAccessibleName(accessible or T["cd_actions_a11y"])
        self._margin = K.SPACE["4"]
        self._gap = K.SPACE["2"]
        row = QHBoxLayout(self)
        row.setContentsMargins(self._margin, K.SPACE["3"], self._margin, K.SPACE["3"])
        row.setSpacing(self._gap)
        self.buttons = []
        for spec in actions:
            kind = spec["kind"]
            if kind == "primary":
                button = Button("primary", spec["text"], size="lg", focus_key="act:" + spec["key"])
            elif kind == "secondary":
                button = Button("secondary", spec["text"], focus_key="act:" + spec["key"])
            elif kind == "tertiary":
                button = Button("ghost", spec["text"], focus_key="act:" + spec["key"])
            else:
                button = Button("danger_ghost", spec["text"], focus_key="act:" + spec["key"])
            button.clicked.connect(lambda _=False, k=spec["key"]: self.triggered.emit(k))
            self.buttons.append(button)
            row.addWidget(button)
        row.addStretch(1)
        self.more_button = IconButton("more_vertical", T["cd_more_a11y"], focus_key="act:more")
        self.more_button.clicked.connect(self.open_menu)
        row.addWidget(self.more_button)
        self.folded = ()
        self._relayout()

    def menu_items(self):
        """더보기 메뉴에 들어 있는 항목 `(열쇠, 글자)` — 폭이 모자라 접힌 행동 + 처음부터 있던 항목(둘 사이에 구분선)."""
        folded = [(self.specs[i]["key"], self.specs[i]["text"]) for i in self.folded]
        return folded + [(item["key"], item["text"]) for item in self.more_items]

    def open_menu(self):
        menu = QMenu(self)
        folded_count = len(self.folded)
        for index, (key, text) in enumerate(self.menu_items()):
            if folded_count and index == folded_count and self.more_items:
                menu.addSeparator()
            action = menu.addAction(text)
            action.triggered.connect(lambda _=False, k=key: self.triggered.emit(k))
        menu.aboutToHide.connect(menu.deleteLater)
        height = menu.sizeHint().height()
        menu.popup(self.more_button.mapToGlobal(QPoint(self.more_button.width() - menu.sizeHint().width(), -height - K.SPACE["1"])))     # 아래 고정 줄이라 위쪽으로 연다
        self.menu = menu
        return menu

    def disable(self, key, reason):
        """꺼진 행동은 이유를 툴팁(키보드 포커스에도 보임)으로 알린다."""
        for spec, button in zip(self.specs, self.buttons, strict=True):
            if spec["key"] == key:
                button.setEnabled(False)
                with_tooltip(button, reason)
                button.setAccessibleDescription(reason)

    def set_enabled(self, key, enabled, reason=""):
        """행동 하나를 켜거나 끈다(화면을 다시 그리지 않고 — 폼을 고치는 동안 저장 단추를 켜고 끌 때). 끌 때는 이유를, 켤 때는 `reason`(있으면 — 예: 복제해 넣을 슬롯 안내)을 툴팁(키보드 포커스에도 보임)과 접근 설명으로 알린다."""
        for spec, button in zip(self.specs, self.buttons, strict=True):
            if spec["key"] == key:
                button.setEnabled(bool(enabled))
                with_tooltip(button, reason or "")
                button.setAccessibleDescription(reason or "")

    def _relayout(self):
        available = self.width() - 2 * self._margin if self.width() > 0 else 10 ** 6
        widths = [button.sizeHint().width() for button in self.buttons]
        visible, folded, show_more = plan_actions(available, self.kinds, widths, self._gap, self.more_button.sizeHint().width(), has_more=bool(self.more_items))
        self.folded = folded
        for index, button in enumerate(self.buttons):
            button.setVisible(index in visible)
        self.more_button.setVisible(show_more)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout()
