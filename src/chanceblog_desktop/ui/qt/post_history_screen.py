"""발행 기록 화면(글 흐름 1b, 결정 D-649·D-650) — 뷰모델(`ui/core/post_history_view.py` 의 `HistoryController.view` 가 만든 딕셔너리)을 공통 부품으로 조립하기만 한다. **읽기 전용이다** — 쓰는 단추가 없다.
머리(제목·설명·정렬 바꾸기·다시 읽기) → 안내 띠 → 글 줄 카드(읽는 중·오류·빈 화면은 홈·설정과 같은 틀의 상태 카드) → 작업 로그 카드(접어 두었다가 펼칠 때 읽는다).
글(제목·주소·로그 줄)은 모두 가린 뒤에 줄인 일반 글이다. 접근 이름·포커스 열쇠(`hist:*`)는 다시 그린 뒤 포커스를 돌려주는 데 쓰인다. 이 파일에는 쓰기 호출이 없다(시험이 소스를 훑는다).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import board
from . import components as UI
from .screens import page_head

SKELETON_ROWS = 3


class HistoryUi:
    """한 번 그린 화면의 부품들 — 시험과 포커스 복원이 단추·카드를 찾으려고 들고 있는다."""

    def __init__(self):
        self.reload_button = self.order_button = self.list_card = self.log_card = self.log_toggle = self.log_retry = self.more_button = self.empty_card = None
        self.rows = {}
        self.copy_buttons = {}


def _diagnostics(text):
    holder = QWidget()
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(UI.Disclosure(T["diag_show"], T["diag_hide"], text))
    box.addWidget(UI.label(T["diag_note"], "caption", wrap=True))
    return holder


def _loading_card(vm_loading):
    card, inner = UI.Card((24, 20, 24, 20))
    inner.addWidget(UI.Skeleton(SKELETON_ROWS, vm_loading["a11y"]))
    note = UI.label(vm_loading["text"], "sub")
    note.setAlignment(Qt.AlignCenter)
    inner.addWidget(note)
    return card


def history_row(shell, row, ui):
    """발행 기록 한 줄 — 제목·`플랫폼 · 상태 · 때`·기록한 주소와 `주소 복사`(클립보드뿐). 눌러서 가는 곳은 없다(읽기 전용)."""
    frame, inner = UI.Card((K.SPACE["3"], K.SPACE["2"], K.SPACE["3"], K.SPACE["2"]), kind="plain")
    inner.setSpacing(K.SPACE["1"])
    frame.setAccessibleName(row["a11y"])
    frame.setProperty("history_key", row["key"])
    inner.addWidget(UI.label(row["title"], "h3", wrap=True))
    inner.addWidget(UI.label(row["meta"], "caption", wrap=True))
    if row["url"]:
        line = QHBoxLayout()
        line.setSpacing(K.SPACE["2"])
        line.addWidget(UI.label(row["url"], "small", wrap=True), 1)
        copy = row["copy"]
        button = UI.Button("secondary", copy["text"], accessible=copy["a11y"], size="sm", focus_key=copy["focus_key"])
        button.setEnabled(bool(copy["enabled"]))
        button.clicked.connect(lambda _=False, key=row["key"]: shell.history_copy_url(key))
        line.addWidget(button, 0, Qt.AlignVCenter)
        inner.addLayout(line)
        ui.copy_buttons[row["key"]] = button
    ui.rows[row["key"]] = frame
    return frame


def history_list_card(shell, vm_list, ui):
    """글 줄 카드 — 머리(이름 + 기록 수)와 줄들, 맨 아래에 `더 보기`(줄이 더 있을 때만)."""
    frame, inner = board.section_card(T["hist_title"], vm_list["count"], accessible=vm_list["a11y"])
    for row in vm_list["rows"]:
        frame.rows_layout.addWidget(history_row(shell, row, ui))
    if vm_list["more"] is not None:
        more = UI.Button("ghost", vm_list["more"]["text"], size="sm", accessible=vm_list["more"]["a11y"], focus_key="hist:more")
        more.clicked.connect(lambda _=False: shell.history_more())
        inner.addWidget(more, 0, Qt.AlignLeft)
        ui.more_button = more
    board.finish_section(frame, inner)
    return frame


def log_card(shell, vm, ui):
    """작업 로그 카드 — 이름·설명·`작업 로그 보기`(펴고 접기) 아래에, 펼쳤을 때만 줄들(최신이 위)과 세는 말. 읽기 전용이라 지우기·내보내기·복사 단추가 없다."""
    frame, inner = UI.Card((K.SPACE["5"], K.SPACE["4"], K.SPACE["5"], K.SPACE["4"]))
    inner.setSpacing(K.SPACE["2"])
    frame.setAccessibleName(vm["a11y"])
    frame.setProperty("post_part", "worklog")
    frame.setProperty("log_state", vm["state"])
    head = QHBoxLayout()
    head.setSpacing(K.SPACE["2"])
    head.addWidget(UI.label(vm["title"], "h2"), 1)
    ui.log_toggle = UI.Button("ghost", vm["toggle"]["text"], "chevron_up" if vm["open"] else "chevron_down", accessible=vm["toggle"]["a11y"], size="sm", focus_key="hist:log-toggle")
    ui.log_toggle.clicked.connect(lambda _=False: shell.history_toggle_log())
    head.addWidget(ui.log_toggle, 0, Qt.AlignVCenter)
    inner.addLayout(head)
    inner.addWidget(UI.label(vm["sub"], "small", wrap=True))
    if not vm["open"]:
        return frame
    if vm["state"] == "loading":
        inner.addWidget(UI.label(vm["loading"], "sub", wrap=True))
    elif vm["state"] == "error":
        inner.addWidget(UI.label(vm["error"]["text"], "body", wrap=True))
        inner.addWidget(_diagnostics(vm["error"]["diag"]))
    elif not vm["lines"] and not vm["notes"]:
        inner.addWidget(UI.label(vm["empty"], "sub", wrap=True))
    for line in vm["lines"]:
        inner.addWidget(UI.label(line, "small", wrap=True))
    for note in vm["notes"]:
        inner.addWidget(UI.label(note, "caption", wrap=True))
    if vm["retry"] is not None:
        ui.log_retry = UI.Button("secondary", vm["retry"]["text"], accessible=vm["retry"]["a11y"], size="sm", focus_key="hist:log-retry")
        ui.log_retry.setEnabled(bool(vm["retry"]["enabled"]))
        ui.log_retry.clicked.connect(lambda _=False: shell.history_reload_log())
        inner.addWidget(ui.log_retry, 0, Qt.AlignLeft)
    return frame


def history_screen(shell, vm):
    """발행 기록 — 목록 카드와 작업 로그 카드. 읽기뿐이라 주요 단추는 없고(빈 화면의 상태 카드 단추만 주요), 가로 스크롤 없이 글은 모두 줄바꿈 평문이다."""
    page = QWidget()
    outer = QVBoxLayout(page)
    margin = K.LAYOUT["page_margin"]
    outer.setContentsMargins(margin, margin, margin, margin)
    outer.setSpacing(K.LAYOUT["gap"])
    ui = HistoryUi()
    page.history_ui = ui
    rights = [UI.SampleBadge(lambda: shell.show_sample_info("history"), vm["sample_tip"])] if vm["sample"] else []
    if vm["order"]["visible"]:
        ui.order_button = UI.Button("secondary", vm["order"]["text"], accessible=vm["order"]["a11y"], size="sm", focus_key="hist:order")
        ui.order_button.clicked.connect(lambda _=False: shell.history_toggle_order())
        rights.append(ui.order_button)
    ui.reload_button = UI.IconButton("refresh", vm["reload"]["a11y"], focus_key="hist:reload")
    ui.reload_button.setEnabled(vm["reload"]["enabled"])
    ui.reload_button.clicked.connect(lambda _=False: shell.reload_history())
    rights.append(ui.reload_button)
    outer.addLayout(page_head(vm["title"], vm["sub"], rights))
    if vm["banner"]:
        outer.addWidget(UI.Banner(*vm["banner"]))
    state = vm["state"]
    if state == "loading":
        outer.addWidget(_loading_card(vm["loading"]))
    elif state == "error":
        outer.addWidget(UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["user"] or vm["error"]["desc"], vm["error"]["button"], shell.reload_history, _diagnostics(vm["error"]["diag"])))
    elif not vm["list"]["rows"]:
        empty = vm["list"]["empty"]
        ui.empty_card = UI.StateCard("inbox", "blue", empty["title"], empty["desc"], empty["button"], shell.history_go_posts)
        if ui.empty_card.action is not None:
            ui.empty_card.action.setAccessibleName(empty["a11y"])
            ui.empty_card.action.setProperty("focus_key", "hist:empty")
        outer.addWidget(ui.empty_card)
    else:
        ui.list_card = history_list_card(shell, vm["list"], ui)
        outer.addWidget(ui.list_card)
    ui.log_card = log_card(shell, vm["log"], ui)
    outer.addWidget(ui.log_card)
    outer.addStretch(1)
    return page
