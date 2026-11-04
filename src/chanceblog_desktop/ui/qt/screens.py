"""Qt 화면(View) — 뷰모델(`ui/core/app_state.py` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 조립하기만 한다.
목록을 거르거나 문구를 만들거나 어떤 상태인지 정하는 일은 하지 않고, Qt 기본 위젯(QPushButton·QLabel·QLineEdit …)을 직접 만들지도 않는다(시험이 지킨다). 눌림은 `shell`(AppShell)의 메서드로 넘긴다.
폭이 바뀌면 배치를 다시 고른다 — 요약 카드 4열→2열→1열, 오른쪽 패널 옆→아래, 추천 행의 지표 칸 접기 — 가로 스크롤은 없다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QBoxLayout, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import NO_DATA, T
from . import components as UI
from . import theme


def refit_scroll_area(widget):
    """배치가 바뀌어 최소 크기가 줄었을 때 스크롤 영역이 안쪽 위젯 크기를 다시 계산하게 알린다(안 하면 줄어든 창에서 가로 스크롤이 남는다)."""
    area = widget.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    if area is not None:
        QApplication.postEvent(area, QEvent(QEvent.LayoutRequest))


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
    rights = ([UI.SampleBadge(shell.show_sample_info)] if vm["sample"] else []) + [UI.label(vm["date"], "sub")]
    outer.addLayout(page_head(vm["title"], vm["sub"], rights))
    main = QWidget()
    column = QVBoxLayout(main)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(K.LAYOUT["gap"])
    cards = []
    for card in vm["cards"]:
        widget = UI.SummaryCard(card)
        widget.clicked.connect(shell.go)
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
    all_link = UI.Button("ghost", vm["section"]["all"], "arrow_right", focus_key="all-topics")
    all_link.setLayoutDirection(Qt.RightToLeft)
    all_link.clicked.connect(lambda: shell.go("topics"))
    inner.addLayout(section_title(vm["section"]["title"], vm["section"]["desc"], (refresh, all_link)))
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


# ---- 아직 만들지 않은 화면 ----------------------------------------------------------------------------------------------------------
def placeholder_screen(shell, vm):
    page = QWidget()
    outer = QVBoxLayout(page)
    margin = K.LAYOUT["page_margin"]
    outer.setContentsMargins(margin, margin, margin, margin)
    outer.setSpacing(K.LAYOUT["gap"])
    outer.addLayout(page_head(vm["name"], vm["desc"]))
    outer.addWidget(UI.StateCard("info_circle", "blue", vm["title"], vm["desc"], vm["button"], lambda: shell.go("home")))
    outer.addStretch(1)
    return page


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
