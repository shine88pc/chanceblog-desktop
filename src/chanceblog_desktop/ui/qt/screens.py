"""Qt 화면(View) — 뷰모델(`ui/core/app_state.py` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 조립하기만 한다.
목록을 거르거나 문구를 만들거나 어떤 상태인지 정하는 일은 하지 않고, Qt 기본 위젯(QPushButton·QLabel·QLineEdit …)을 직접 만들지도 않는다(시험이 지킨다). 눌림은 `shell`(AppShell)의 메서드로 넘긴다.
폭이 바뀌면 배치를 다시 고른다 — 요약 카드 4열→2열→1열, 오른쪽 패널 옆→아래, 추천 행의 지표 칸 접기, 설정 화면의 용도 카드 2열→1열 — 가로 스크롤은 없다.
화면은 홈(`home_screen`)·설정(`settings_screen` — 접이식 다섯 묶음(용도 묶음 넷 + '정보')과 용도 카드, 읽기만) 둘이고(UI-C1a 에서 '아직 만들고 있어요' 자리표시 화면을 없앴다 — 완성된 화면만 연다), 어느 메뉴가 어느 화면인지는 맨 아래 `SCREEN_BUILDERS` 표(메뉴 → 화면 만드는 함수) 한 곳이 정한다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QBoxLayout, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import NO_DATA, T
from . import components as UI
from . import theme
from .gauges import UsageBar


def refit_scroll_area(widget):
    """배치가 바뀌어 최소 크기가 줄었을 때 스크롤 영역이 안쪽 위젯 크기를 다시 계산하게 알린다(안 하면 줄어든 창에서 가로 스크롤이 남는다)."""
    area = widget.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    if area is not None:
        QApplication.postEvent(area, QEvent(QEvent.LayoutRequest))


def relayout_screen(root):
    """화면 위젯 안의 모든 배치를 무효로 하고 처음부터 다시 계산한다 — 다시 그린 직후나 창 크기를 바꾼 직후에 일부 배치가 옛 값으로 굳는 일을 막는다(UI-C1a: 논리 1280×720 에서 홈 추천 행이
    '누르는 칸 최소 높이' 로 눌려 제목이 잘리는 것이 드러났다 — 폭에 따라 줄 수가 바뀌는 글과 폭 문턱에서 접히는 칸이 있는 행의 높이가 위쪽 배치에 반영되지 않은 채 굳는다. 같은 일이 옛 코드의 창 크기 끌기에서도 있었다).
    위젯마다 가진 배치를 모두 무효로 한 뒤 맨 위 배치를 다시 맞추고 스크롤 영역이 안쪽 크기를 다시 재게 알린다 — 홈 위젯 165개에 6~8ms 라 눈에 띄지 않고 여러 번 불러도 결과가 같다."""
    if root is None:
        return
    for widget in (root, *root.findChildren(QWidget)):
        layout = widget.layout()
        if layout is not None:
            layout.invalidate()
    if root.layout() is not None:
        root.layout().activate()
    refit_scroll_area(root)


class FlowGrid(QWidget):
    """폭에 따라 열 수가 바뀌는 격자 — `options` 는 큰 열 수부터(예: 4, 2, 1), 한 칸의 최소 폭 `min_col` 이 들어가는 가장 큰 열 수를 고른다."""

    def __init__(self, widgets, options=(4, 2, 1), min_col=190, gap=16):
        super().__init__()
        self._widgets, self._options, self._min, self._gap, self._cols = widgets, options, min_col, gap, 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(gap)
        self._place(options[0])

    def set_options(self, options):
        """열 수 후보를 바꾸고 지금 폭에 맞게 다시 놓는다."""
        self._options, self._cols = options, 0
        self._place(self.columns_for(self.width()) if self.width() else options[0])

    def columns_for(self, width):
        for cols in self._options:
            if cols * self._min + (cols - 1) * self._gap <= width:
                return cols
        return self._options[-1]

    def _place(self, cols):
        if cols == self._cols:
            return
        self._cols = cols
        for index, widget in enumerate(self._widgets):
            self._grid.addWidget(widget, index // cols, index % cols)
        for column in range(max(self._grid.columnCount(), max(self._options))):
            self._grid.setColumnStretch(column, 1 if column < cols else 0)
        refit_scroll_area(self)

    def resizeEvent(self, event):
        self._place(self.columns_for(self.width()))
        super().resizeEvent(event)


class ResponsiveBody(QWidget):
    """본문(왼쪽 큰 칸) + 오른쪽 패널 — 본문 폭이 충분하면 패널을 옆에 두고(폭 280), 좁으면 본문 아래로 내린다(패널의 카드들은 폭에 맞춰 열을 나눈다)."""

    def __init__(self, main, rail_cards):
        super().__init__()
        self._main = main
        self._layout = QBoxLayout(QBoxLayout.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(K.LAYOUT["gap"])
        self._layout.addWidget(main, 1)
        self.rail = FlowGrid(rail_cards, options=(3, 2, 1), min_col=260)
        self._layout.addWidget(self.rail, 0, Qt.AlignTop)
        self.beside = True
        self._apply(True)

    def _apply(self, beside):
        self.beside = beside
        self._layout.setDirection(QBoxLayout.LeftToRight if beside else QBoxLayout.TopToBottom)
        if beside:
            self.rail.setFixedWidth(K.LAYOUT["rail"])
            self.rail.set_options((1,))
        else:
            self.rail.setMinimumWidth(0)
            self.rail.setMaximumWidth(16777215)
            self.rail.set_options((3, 2, 1))
        refit_scroll_area(self)

    def resizeEvent(self, event):
        wide = self.width() >= K.LAYOUT["rail_beside_min"]
        if wide != self.beside:
            self._apply(wide)
        super().resizeEvent(event)


def page_head(title, sub, rights=()):
    row = QHBoxLayout()
    left = QVBoxLayout()
    left.setSpacing(2)
    left.addWidget(UI.label(title, "display", wrap=True))
    left.addWidget(UI.label(sub, "sub", wrap=True))
    row.addLayout(left, 1)
    right = QHBoxLayout()
    right.setSpacing(12)
    for widget in rights:
        right.addWidget(widget, 0, Qt.AlignVCenter)
    row.addLayout(right)
    row.setAlignment(right, Qt.AlignTop)
    return row


def section_title(title, desc=None, rights=()):
    row = QHBoxLayout()
    left = QVBoxLayout()
    left.setSpacing(0)
    left.addWidget(UI.label(title, "h1"))
    if desc:
        left.addWidget(UI.label(desc, "sub", wrap=True))
    row.addLayout(left, 1)
    for widget in rights:
        row.addWidget(widget, 0, Qt.AlignTop)
    return row


def chip_flow(chips, handler):
    buttons = []
    for chip in chips:
        button = UI.FilterChip(chip["label"], chip["count"], chip["active"], focus_key="chip:" + chip["key"])
        button.clicked.connect(lambda _=False, key=chip["key"]: handler(key))
        buttons.append(button)
    return UI.chip_row(buttons)


# ---- 홈 ---------------------------------------------------------------------------------------------------------------------
def home_screen(shell, vm):
    page = QWidget()
    outer = QVBoxLayout(page)
    margin = K.LAYOUT["page_margin"]
    outer.setContentsMargins(margin, margin, margin, margin)
    outer.setSpacing(K.LAYOUT["gap"])
    rights = [UI.SampleBadge(shell.show_sample_info)] if vm["sample"] else []              # 날짜는 상단 앱 바로 옮겼다(UI-C1a, D-171)
    outer.addLayout(page_head(vm["title"], vm["sub"], rights))
    main = QWidget()
    column = QVBoxLayout(main)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(K.LAYOUT["gap"])
    cards = []
    for card in vm["cards"]:
        widget = UI.SummaryCard(card)                                                       # 요약 카드는 눌러서 가는 곳이 없다(옛 이동 길은 아직 만들지 않은 화면으로 가서 끊었다 — UI-C1a, D-172)
        cards.append(widget)
    column.addWidget(FlowGrid(cards, (4, 2, 1), 190))
    column.addWidget(_recommend(shell, vm))
    column.addStretch(1)
    outer.addWidget(ResponsiveBody(main, _rail(shell, vm["rail"])), 1)
    return page


def _recommend(shell, vm):
    section, inner = UI.Card((24, 20, 24, 20))
    refresh = UI.IconButton("refresh", vm["section"]["refresh"], focus_key="refresh")
    refresh.setEnabled(vm["state"] != "loading")
    refresh.clicked.connect(shell.reload)
    shell.refresh_button = refresh
    inner.addLayout(section_title(vm["section"]["title"], vm["section"]["desc"], (refresh,)))         # '전체 보기' 는 아직 만들지 않은 화면으로 가는 단추라 없앴다(UI-C1a, D-172)
    if vm["fetched"]:
        inner.addWidget(UI.label(vm["fetched"], "caption"))
    inner.addWidget(chip_flow(vm["chips"], shell.chip_home))
    if vm["banner"]:
        inner.addWidget(UI.Banner(*vm["banner"]))
    state = vm["state"]
    if state == "loading":
        inner.addWidget(UI.Skeleton(HOME_SKELETON_ROWS))
        note = UI.label(vm["loading"]["text"], "sub")
        note.setAlignment(Qt.AlignCenter)
        inner.addWidget(note)
        cancel = UI.Button("ghost", vm["loading"]["cancel"], "x", focus_key="cancel-load")
        cancel.clicked.connect(shell.cancel_load)
        shell.cancel_button = cancel
        inner.addWidget(cancel, 0, Qt.AlignHCenter)
    elif state == "empty":
        inner.addWidget(UI.StateCard("inbox", "blue", vm["empty"]["title"], vm["empty"]["desc"], vm["empty"]["button"], lambda: shell.notify_soon(vm["empty"]["button"])))
    elif state == "error":
        diag = UI.Disclosure(T["diag_show"], T["diag_hide"], vm["error"]["diag"])
        note = UI.label(T["diag_note"], "caption", wrap=True)
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(diag)
        box.addWidget(note)
        inner.addWidget(UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["user"] or vm["error"]["desc"], vm["error"]["button"], shell.reload, holder))
    else:
        for row_vm in vm["rows"]:
            row = UI.TopicRow(row_vm, big=row_vm["selected"])
            row.selected.connect(shell.select_topic)
            row.draft.connect(shell.draft)
            row.detail.connect(shell.open_drawer)
            inner.addWidget(row)
        if not vm["rows"]:
            inner.addWidget(UI.StateCard("inbox", "blue", vm["empty"]["title"], vm["empty"]["desc"]))
    return section


HOME_SKELETON_ROWS = 4


def _rail(shell, rail):
    cards = []
    blogs, inner = UI.Card((20, 20, 20, 16))
    inner.setSpacing(4)
    inner.addWidget(UI.label(rail["blogs_title"], "h2"))
    inner.addWidget(UI.label(rail["blogs_sub"], "caption"))
    for blog in rail["blogs"]:
        row = QVBoxLayout()
        row.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(10)
        mark = UI.Badge(blog["key"].lower(), blog["key"])
        mark.setMinimumSize(32, 32)
        head.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(UI.ElidedLabel(blog["name"], "body_lg"))                  # 긴 이름은 카드 밖으로 잘리지 않고 …(줄임표)로 줄어든다(툴팁은 어댑터가 가린 뒤 30자로 줄인 이름 — 40자 이름이면 툴팁도 30자 + …)
        if blog["category"]:
            names.addWidget(UI.label(blog["category"], "caption"))
        head.addLayout(names, 1)
        row.addLayout(head)
        nums = QHBoxLayout()
        for key, text, value in (("total", T["rail_total"], blog["total"]), ("month", T["rail_month"], blog["month"]), ("candidates", T["rail_candidates"], blog["candidates"])):
            if value is not None:                                           # 가져올 수 없는 값은 보이지 않는다
                nums.addWidget(UI.label(f"{text}  {value:,}", "caption"))
        nums.addStretch(1)
        row.addLayout(nums)
        inner.addSpacing(6)
        inner.addLayout(row)
    if not rail["blogs"]:
        inner.addWidget(UI.label(NO_DATA, "muted"))
    inner.addStretch(1)                                                         # 카드가 옆 카드의 높이에 맞춰 늘어나도 내용은 위에 붙어 있게
    cards.append(blogs)
    quick, inner = UI.Card((20, 20, 20, 20))
    inner.addWidget(UI.label(rail["quick_title"], "h2"))
    for item in rail["quick"]:
        action = UI.QuickAction(item)
        action.activated.connect(lambda key=item["key"]: shell.quick(key))
        inner.addWidget(action)
    inner.addStretch(1)
    cards.append(quick)
    if rail["tip"]["visible"]:
        tip, inner = UI.Card((16, 16, 16, 16), kind="warm")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(theme.IconWidget("bulb", theme.colors()["success_text"], K.ICON["card"]), 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(UI.label(rail["tip"]["title"], "body_lg"))
        text.addWidget(UI.label(rail["tip"]["text"], "caption", wrap=True))
        row.addLayout(text, 1)
        row.setAlignment(text, Qt.AlignTop)
        close = UI.IconButton("x", rail["tip"]["close"], focus_key="tip-close")
        close.clicked.connect(shell.tip_close)
        row.addWidget(close, 0, Qt.AlignTop)
        inner.addLayout(row)
        inner.addStretch(1)
        cards.append(tip)
    return cards


# ---- 설정(연결 관리) ----------------------------------------------------------------------------------------------------------------
def badge_line(caption, badge):
    """'준비' · '연결' 배지 한 줄 — 둘은 따로 보인다(준비 중이라는 것과 연결 상태는 다른 말이다)."""
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(UI.label(caption, "caption"))
    row.addWidget(UI.Badge(badge["tone"], badge["text"]))
    row.addStretch(1)
    return row


def purpose_card(card):
    """용도 카드 — 이름·한 줄 설명·배지 두 줄·안내·한도에 닿았을 때 계속하는 방법·키 항목·사용량(기간마다 막대 한 줄 + 작은 글). 준비 중인 용도는 회색 톤이다. 읽기만 하는 화면이라 누르는 것이 하나도 없다."""
    frame, inner = UI.Card((18, 16, 18, 16), kind="quiet" if card["gray"] else "true")
    inner.setSpacing(6)
    inner.addWidget(UI.label(card["name"], "h3", wrap=True))                 # 용도 카드 이름 = 카드 제목 역할(h3)
    if card["desc"]:
        inner.addWidget(UI.label(card["desc"], "small", wrap=True))
    inner.addLayout(badge_line(card["ready_caption"], card["ready"]))
    if card["conn"]:
        inner.addLayout(badge_line(card["conn_caption"], card["conn"]))
    for key in ("note", "policy"):
        if card[key]:
            inner.addWidget(UI.label(card[key], "small", wrap=True))
    if card["limit"]:                                                                       # 한도에 닿으면 어떻게 계속하는지 — 한 줄 + 작은 설명
        inner.addWidget(UI.label(card["limit"]["title"], "small", wrap=True))
        if card["limit"]["desc"]:
            inner.addWidget(UI.label(card["limit"]["desc"], "caption", wrap=True))
    if card["choices"]:
        inner.addWidget(UI.label(f"{card['choices']['label']}: {' · '.join(card['choices']['items'])}", "caption", wrap=True))
    if card["entries"]:
        inner.addSpacing(4)
        inner.addWidget(UI.label(card["entries_title"], "small"))
        for entry in card["entries"]:
            inner.addWidget(UI.ElidedLabel(entry["name"], "body"))
            inner.addWidget(UI.label(entry["state_line"], "caption"))
            if entry["missing"]:
                inner.addWidget(UI.label(entry["missing"], "caption", wrap=True))
    if card["usage"]:
        inner.addSpacing(4)
        inner.addWidget(UI.label(card["usage"]["title"], "small"))
        for row_vm in card["usage"]["rows"]:
            bar = row_vm["bar"]
            if bar is not None:                                                             # 기간마다 사용량 막대 한 줄 — 모르는 값은 막대 없이 글(`UsageBar` 가 정한다), 예시 꼬리표는 줄 끝(UI-C1b)
                inner.addWidget(UsageBar(bar["used"], bar["limit"], bar["unit"], bar["title"], row_vm["tag"]))
                continue
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(UI.label(row_vm["text"], "caption" if row_vm["note"] else "body", wrap=True), 1)
            if row_vm["tag"]:
                row.addWidget(UI.Badge("muted", row_vm["tag"]), 0, Qt.AlignTop)             # 예시 데이터의 글 줄(콘솔 한도·단계 안내 …) 옆 꼬리표
            inner.addLayout(row)
    inner.addStretch(1)
    frame.setAccessibleName(card["a11y"])
    return frame


def info_card(info):
    """'정보' 묶음의 몸 — 버전 한 줄 + 접어 둔 진단 정보(+ '키와 입력한 글은 담기지 않아요' 안내). 읽기만 하는 카드라 누르는 것은 진단 정보 단추 하나뿐이다(UI-C1b)."""
    frame, inner = UI.Card((18, 16, 18, 16))
    inner.setSpacing(6)
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(UI.label(info["version"]["label"], "caption"))
    row.addWidget(UI.label(info["version"]["text"], "body"))
    row.addStretch(1)
    inner.addLayout(row)
    inner.addWidget(UI.Disclosure(info["diag"]["show"], info["diag"]["hide"], info["diag"]["text"], left=True))
    inner.addWidget(UI.label(info["diag"]["note"], "caption", wrap=True))
    inner.addStretch(1)
    return frame


def settings_screen(shell, vm):
    """설정 — ① 연결 관리(접이식 다섯 묶음: 데이터 Provider·이미지·AI 보조·발행·연결·정보) ② 안내 한 줄. 읽기만 한다(키 입력 창은 다음 묶음). 홈과 같은 여섯 상태 틀을 쓴다.
    '정보' 묶음(버전 + 접어 둔 진단 정보)은 옛 '고급 > 진단 정보' 가 옮겨 온 것이다(UI-C1b) — 구조는 아코디언 그대로이고 묶음이 6개 이상이 되면 2단 전환을 검토한다(D-182)."""
    page = QWidget()
    outer = QVBoxLayout(page)
    margin = K.LAYOUT["page_margin"]
    outer.setContentsMargins(margin, margin, margin, margin)
    outer.setSpacing(K.LAYOUT["gap"])
    rights = [UI.SampleBadge(lambda: shell.show_sample_info("settings"), T["conn_sample_tip"])] if vm["sample"] else []
    outer.addLayout(page_head(vm["title"], vm["sub"], rights))
    section, inner = UI.Card((24, 20, 24, 20))
    refresh = UI.IconButton("refresh", vm["refresh"], focus_key="refresh-conn")
    refresh.setEnabled(vm["state"] != "loading")
    refresh.clicked.connect(shell.reload_connections)
    inner.addLayout(section_title(vm["section"]["title"], vm["section"]["desc"], (refresh,)))
    if vm["fetched"]:
        inner.addWidget(UI.label(vm["fetched"], "caption"))
    for icon, message in vm["banners"]:
        inner.addWidget(UI.Banner(icon, message))
    state = vm["state"]
    if state == "loading":
        inner.addWidget(UI.Skeleton(CONN_SKELETON_ROWS, vm["loading"]["a11y"]))
        note = UI.label(vm["loading"]["text"], "sub")
        note.setAlignment(Qt.AlignCenter)
        inner.addWidget(note)
    elif state == "empty":
        inner.addWidget(UI.StateCard("inbox", "blue", vm["empty"]["title"], vm["empty"]["desc"], vm["empty"]["button"], shell.reload_connections))
    elif state == "error":
        diag = UI.Disclosure(T["diag_show"], T["diag_hide"], vm["error"]["diag"])
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(diag)
        box.addWidget(UI.label(T["diag_note"], "caption", wrap=True))
        inner.addWidget(UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["user"] or vm["error"]["desc"], vm["error"]["button"], shell.reload_connections, holder))
    else:
        for group in vm["groups"]:
            grid = FlowGrid([purpose_card(card) for card in group["cards"]], (2, 1), 440)
            accordion = UI.Accordion(group["key"], group["title"], group["chips"], grid, group["open"], T["conn_group_open"], T["conn_group_closed"], group["summary"])
            accordion.toggled.connect(shell.set_group_open)                         # 펴고 접은 것은 기억만 한다(다시 그리지 않는다)
            inner.addWidget(accordion)
        info = vm["info"]                                                           # 마지막 줄 '정보' — 버전 + 접어 둔 진단 정보
        accordion = UI.Accordion(info["key"], info["title"], info["chips"], FlowGrid([info_card(info)], (2, 1), 440), info["open"], T["conn_group_open"], T["conn_group_closed"], info["summary"])
        accordion.toggled.connect(shell.set_group_open)
        inner.addWidget(accordion)
    outer.addWidget(section)
    if state in ("normal", "partial", "offline"):
        outer.addWidget(UI.label(vm["keys_note"], "sub", wrap=True))
    outer.addStretch(1)
    return page


CONN_SKELETON_ROWS = 3


# ---- 메뉴 → 화면 만드는 함수 표 -------------------------------------------------------------------------------------------------------
def _home_builder(shell):
    return home_screen(shell, shell.state.home_view())


def _settings_builder(shell):
    return settings_screen(shell, shell.state.settings_view())


# 실제 메뉴마다 한 줄(`app_state.NAV` 와 같은 열쇠 — 시험이 지킨다). **완성된 화면만** 둔다 — 아직 만들지 않은 화면은 이 표에도 메뉴에도 없고(자리표시 화면을 없앴다), 화면이 완성되면 메뉴 한 줄과 이 표 한 줄을 같이 더한다.
SCREEN_BUILDERS = {"home": _home_builder, "settings": _settings_builder}


# ---- 상세 서랍 ---------------------------------------------------------------------------------------------------------------------
def drawer_content(shell, d):
    """주제 상세(서랍) 안쪽 — (내용 위젯, 닫기 단추)."""
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(20, 18, 20, 20)
    layout.setSpacing(14)
    head = QHBoxLayout()
    head.addWidget(UI.label(d["title"], "h2"), 1)
    close = UI.IconButton("x", d["close"], focus_key="drawer-close")
    close.clicked.connect(shell.close_drawer)
    head.addWidget(close)
    layout.addLayout(head)
    layout.addWidget(UI.label(d["topic"], "h1", wrap=True))
    meta = QHBoxLayout()
    meta.setSpacing(8)
    if d["blog_label"]:
        meta.addWidget(UI.Badge("info", d["blog_label"]))
    meta.addWidget(UI.Badge("muted", f"{T['priority']} {d['priority']}"))
    if d["sample"]:
        meta.addWidget(UI.Badge("muted", d["sample_tag"]))
    meta.addStretch(1)
    layout.addLayout(meta)
    layout.addWidget(UI.label(d["reason_title"], "small"))
    layout.addWidget(UI.label(d["reason"], "body", wrap=True))
    grid, inner = UI.Card((16, 12, 16, 12), kind="plain")
    inner.setSpacing(8)
    for field in d["fields"]:
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(UI.label(field["label"], "small", wrap=True), 4)
        row.addWidget(UI.label(field["value"], "muted" if field["missing"] else "body_lg", wrap=True), 5)
        inner.addLayout(row)
    layout.addWidget(grid)
    for index, draft in enumerate(d["drafts"]):
        button = UI.Button("primary" if index == 0 else "secondary", draft["label"], size="lg" if index == 0 else None, focus_key="drawer-draft:" + draft["key"])
        button.clicked.connect(lambda _=False, key=draft["key"]: shell.draft(d["id"], key))
        layout.addWidget(button)
    extra = QHBoxLayout()
    for text in (d["hold"], d["more"]):
        button = UI.Button("secondary", text, focus_key="drawer-" + text)
        button.clicked.connect(lambda _=False, name=text: shell.notify_soon(name))
        extra.addWidget(button)
    layout.addLayout(extra)
    layout.addStretch(1)
    return body, close
