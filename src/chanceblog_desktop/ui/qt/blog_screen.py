"""블로그 관리 화면(P4b) — 뷰모델(`ui/core/blogs_view.py` 가 만든 딕셔너리)을 공통 부품(`components.py`·`bars.py`·`blog_parts.py`)으로 조립하기만 한다.
화면: 위 머리(제목·예시 표시·다시 읽기) → 알림 줄(마지막 동작의 결과) → **왼쪽 슬롯 카드 다섯**(빈 슬롯은 '등록' 카드)과 **오른쪽 폼**(제목·칸 구역 셋·**아래 고정 행동 줄** 저장·되돌리기·복제·삭제).
폭이 좁으면(`LAYOUT["blogs_beside_min"]` 미만) 슬롯 목록이 폼 위로 올라간다 — 가로 스크롤은 없다. 폼 칸들은 안쪽 스크롤(`FormScroll`)에 들어가고 행동 줄은 그 밖에 있어 1366×768 에서도 저장 단추가 늘 보인다.
화면은 읽기·고르기·고치기까지만 하고 **파일에 쓰는 일은 하지 않는다** — 단추를 누르면 셸(`shell.blog_*`)이 상태(`BlogsController`)를 거쳐 서비스를 부른다(이 파일에는 쓰기 호출이 없다 — 시험이 소스를 훑는다).
칸을 고치는 동안에는 화면을 다시 그리지 않고(`update_blogs_live` 가 오류 글·단추·카드 표시만 그 자리에서 바꾼다) 입력 중이던 자리가 사라지지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .bars import ActionBar
from .blog_parts import FieldView, FormScroll, NoticeBar, SlotCard
from .screens import FlowGrid, page_head


class BlogsUi:
    """한 번 그린 화면의 부품들 — 칸을 고칠 때 화면을 다시 그리지 않고 이 부품들만 갱신하려고 들고 있는다."""

    def __init__(self):
        self.fields, self.cards = {}, {}
        self.form_scroll = None
        self.bar = None
        self.unsaved = None
        self.first_error = None


class BlogsBody(QWidget):
    """슬롯 목록(왼쪽, 폭 320) + 폼 — 본문 폭이 충분하면 옆에 두고 좁으면 목록이 폼 위로 올라간다(목록은 폭에 맞춰 열을 나눈다)."""

    def __init__(self, listing, scroll, grid, form):
        super().__init__()
        self._listing, self._scroll, self._grid = listing, scroll, grid
        self._layout = QBoxLayout(QBoxLayout.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(K.LAYOUT["gap"])
        self._layout.addWidget(listing, 0)
        self._layout.addWidget(form, 1)
        self.beside = True
        self._apply(True)

    def _apply(self, beside):
        self.beside = beside
        self._layout.setDirection(QBoxLayout.LeftToRight if beside else QBoxLayout.TopToBottom)
        if beside:
            self._listing.setFixedWidth(K.LAYOUT["blogs_list"])
            self._scroll.setMaximumHeight(16777215)
            self._grid.set_options((1,))
        else:
            self._listing.setMinimumWidth(0)
            self._listing.setMaximumWidth(16777215)
            self._scroll.setMaximumHeight(K.LAYOUT["list_stacked_h"])
            self._grid.set_options((3, 2, 1))

    def resizeEvent(self, event):
        wide = self.width() >= K.LAYOUT["blogs_beside_min"]
        if wide != self.beside:
            self._apply(wide)
        super().resizeEvent(event)


def _listing(shell, vm, ui):
    """왼쪽 슬롯 목록 — 제목·안내는 고정이고 카드 다섯은 안쪽 스크롤에 들어간다(카드가 한 화면보다 길어도 페이지가 늘어나 저장 단추가 밀려나지 않는다)."""
    box = QWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(K.SPACE["2"])
    column.addWidget(UI.label(vm["list"]["title"], "h2"))
    column.addWidget(UI.label(vm["list"]["desc"], "caption", wrap=True))
    cards = []
    for card in vm["list"]["cards"]:
        widget = SlotCard(card)
        widget.activated.connect(lambda key=card["key"]: shell.blog_select(key))
        ui.cards[card["key"]] = widget
        cards.append(widget)
    grid = FlowGrid(cards, (1,), min_col=260, gap=K.SPACE["2"])
    holder = QWidget()
    inner = QVBoxLayout(holder)
    inner.setContentsMargins(0, K.SPACE["1"], K.SPACE["2"], K.SPACE["1"])
    inner.addWidget(grid)
    inner.addStretch(1)
    scroll = FormScroll(holder)
    scroll.setMinimumHeight(K.LAYOUT["list_scroll_min_h"])
    scroll.setAccessibleName(vm["list"]["a11y"])
    column.addWidget(scroll, 1)
    return box, scroll, grid


def _form(shell, vm, ui):
    form = vm["form"]
    frame, outer = UI.Card((0, 0, 0, 0))
    outer.setSpacing(0)
    frame.setAccessibleName(form["a11y"])
    head = QWidget()
    row = QHBoxLayout(head)
    row.setContentsMargins(K.SPACE["5"], K.SPACE["4"], K.SPACE["5"], K.SPACE["3"])
    row.setSpacing(K.SPACE["3"])
    titles = QVBoxLayout()
    titles.setSpacing(0)
    titles.addWidget(UI.label(form["title"], "h2", wrap=True))
    if form["kind"]:
        titles.addWidget(UI.label(form["kind"], "caption"))
    row.addLayout(titles, 1)
    if form["preset"]:
        badge = UI.Badge("muted", form["preset_text"])
        badge.setProperty("badge", None)
        badge.setProperty("chbadge", form["preset"])                                          # 채널 색 배지 — 색은 테두리, 글자는 늘 이름이다(색만으로 구분하지 않는다)
        row.addWidget(badge, 0, Qt.AlignTop)
    row.addWidget(UI.Badge(form["status"]["tone"], form["status"]["text"]), 0, Qt.AlignTop)
    ui.unsaved = UI.Badge("warning", form["unsaved"]["text"] if form["unsaved"] else T["blogs_status_unsaved"])
    ui.unsaved.setVisible(bool(form["unsaved"]))
    row.addWidget(ui.unsaved, 0, Qt.AlignTop)
    outer.addWidget(head)
    content = QWidget()
    body = QVBoxLayout(content)
    body.setContentsMargins(K.SPACE["5"], K.SPACE["2"], K.SPACE["5"], K.SPACE["5"])
    body.setSpacing(K.SPACE["5"])
    for section in form["sections"]:
        part = QVBoxLayout()
        part.setSpacing(K.SPACE["3"])
        part.addWidget(UI.label(section["title"], "h3"))
        part.addWidget(UI.label(section["desc"], "caption", wrap=True))
        for field in section["fields"]:
            view = FieldView(field)
            view.edited.connect(shell.blog_edit)
            view.picked.connect(shell.blog_pick_image)
            view.toggled_choice.connect(shell.blog_toggle_choice)
            ui.fields[field["name"]] = view
            part.addWidget(view)
        body.addLayout(part)
    if form["saving"]:
        body.addWidget(UI.label(form["saving_text"], "sub"))
    body.addStretch(1)
    ui.form_scroll = FormScroll(content)
    outer.addWidget(ui.form_scroll, 1)
    bar = ActionBar([{"key": action["key"], "text": action["text"], "kind": action["kind"]} for action in form["actions"]], accessible=form["actions_a11y"])
    bar.triggered.connect(shell.blog_action)
    ui.bar = bar
    outer.addWidget(bar)
    update_blogs_live_parts(ui, vm)
    return frame


def update_blogs_live_parts(ui, vm):
    form = vm["form"]
    if form is None:
        return
    for section in form["sections"]:
        for field in section["fields"]:
            view = ui.fields.get(field["name"])
            if view is not None:
                view.update_from(field)
    for action in form["actions"]:
        ui.bar.set_enabled(action["key"], action["enabled"], action["reason"] or action.get("hint", ""))
    for card in vm["list"]["cards"]:
        widget = ui.cards.get(card["key"])
        if widget is not None:
            widget.update_from(card)
    if ui.unsaved is not None:
        ui.unsaved.setVisible(bool(form["unsaved"]))
    errors = [field["name"] for section in form["sections"] for field in section["fields"] if field["error"]]
    ui.first_error = errors[0] if errors else None


def update_blogs_live(page, vm):
    """칸을 고친 뒤 — 화면을 다시 그리지 않고 오류 글·단추·카드 표시만 그 자리에서 바꾼다(입력 중이던 커서·한글 조합이 사라지지 않게)."""
    ui = getattr(page, "blogs_ui", None)
    if ui is not None:
        update_blogs_live_parts(ui, vm)


def blogs_screen(shell, vm):
    """블로그 관리 — ① 머리 ② 알림 줄 ③ 슬롯 카드 다섯 + 폼(읽는 중·읽기 오류는 홈·설정과 같은 틀의 상태 카드)."""
    page = QWidget()
    outer = QVBoxLayout(page)
    margin = K.LAYOUT["page_margin"]
    outer.setContentsMargins(margin, margin, margin, margin)
    outer.setSpacing(K.LAYOUT["gap"])
    rights = [UI.SampleBadge(lambda: shell.show_sample_info("blogs"), vm["sample_tip"])] if vm["sample"] else []
    refresh = UI.IconButton("refresh", vm["refresh"], focus_key="refresh-blogs")
    refresh.setEnabled(vm["state"] != "loading" and not vm["busy"])
    refresh.clicked.connect(shell.reload_blogs)
    rights.append(refresh)
    outer.addLayout(page_head(vm["title"], vm["sub"], rights))
    for _icon, message in vm["banners"]:
        outer.addWidget(NoticeBar("info", message))
    if vm["notice"]:
        outer.addWidget(NoticeBar(vm["notice"]["level"], vm["notice"]["text"]))
    ui = BlogsUi()
    page.blogs_ui = ui
    state = vm["state"]
    if state == "loading":
        card, inner = UI.Card((24, 20, 24, 20))
        inner.addWidget(UI.Skeleton(3, vm["loading"]["a11y"]))
        note = UI.label(vm["loading"]["text"], "sub")
        note.setAlignment(Qt.AlignCenter)
        inner.addWidget(note)
        outer.addWidget(card)
        outer.addStretch(1)
    elif state == "error":
        diag = UI.Disclosure(T["diag_show"], T["diag_hide"], vm["error"]["diag"])
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(diag)
        box.addWidget(UI.label(T["diag_note"], "caption", wrap=True))
        outer.addWidget(UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["desc"], vm["error"]["button"], shell.reload_blogs, holder))
        outer.addStretch(1)
    else:
        listing, scroll, grid = _listing(shell, vm, ui)
        outer.addWidget(BlogsBody(listing, scroll, grid, _form(shell, vm, ui)), 1)
    return page
