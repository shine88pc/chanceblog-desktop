"""Seed 관리 화면 — 뷰모델(`ui/core/seeds_view.py` 가 만든 딕셔너리)을 공통 부품(`components.py`·`bars.py`·`seed_parts.py`)으로 조립하기만 한다.
화면: 위 머리(제목·예시 표시·제안 파일 불러오기·새 Seed 등록·다시 읽기) → 알림 줄(마지막 동작의 결과) → **한 카드**(개수 요약: 승인 전 N개 — 승인하기 전에는 후보 생성에 쓰이지 않습니다 · 채널마다 쓸 수 있는 Seed 수와 후보 생성 켜짐 여부 /
거르기: 상태 칩·글 검색·'더 거르기' 의 소속·중요도 칩 / 일괄 변경 줄: 고른 개수·사용 중으로 바꾸기·쉬게 하기) → **Seed 줄 목록**(줄을 누르면 오른쪽 서랍에 상세·고치기·아래 고정 행동 줄).
화면에는 주요(Primary) 행동이 없다 — 머리의 두 단추는 보조이고 주요 행동은 서랍의 행동 줄에 하나(승인하기·저장·다시 쓰기·승인 전으로 등록)뿐이다. 가로 스크롤은 없다.
화면은 읽기·고르기·고치기까지만 하고 **파일에 쓰는 일은 하지 않는다** — 단추를 누르면 셸(`shell.seed_*`)이 상태(`SeedsController`)를 거쳐 서비스를 부른다(이 파일에는 쓰기 호출이 없다 — 시험이 소스를 훑는다).
글자를 치거나 상자를 고르는 동안에는 화면 전체를 다시 그리지 않고(`update_seeds_live`·`refilter_seeds_live`·`update_seed_drawer_live`) 입력 중이던 자리가 사라지지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .bars import ActionBar
from .blog_parts import FormScroll, NoticeBar  # noqa: F401  — 알림 줄은 블로그 관리와 같은 부품이다
from .screens import page_head
from .seed_parts import SeedFieldView, SeedList


class SeedsUi:
    """한 번 그린 화면의 부품들 — 고르거나 칠 때 화면을 다시 그리지 않고 이 부품들만 갱신하려고 들고 있는다."""

    def __init__(self):
        self.list = None
        self.result = None
        self.reset = None
        self.bulk_text = None
        self.bulk_buttons = {}
        self.bulk_select = self.bulk_clear = None


class SeedDrawerUi:
    def __init__(self):
        self.fields, self.bar, self.unsaved, self.first_error = {}, None, None, None


def _chips(items, focus_prefix, on_click):
    group = []
    for item in items:
        chip = UI.FilterChip(item["label"], item["count"], item["active"], focus_key=f"{focus_prefix}:{item['key']}")
        chip.clicked.connect(lambda _=False, key=item["key"]: on_click(key))
        group.append(chip)
    return UI.chip_row(group)


def _labeled(title, widget):
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(K.SPACE["3"])
    label = UI.label(title, "small")
    label.setMinimumWidth(K.SIZE["control"] + K.SPACE["6"])
    label.setMinimumHeight(K.SIZE["chip_h"])                                     # 첫 줄 칩과 같은 높이에 가운데 맞춤(칩이 다음 줄로 넘어가도 이름은 첫 줄 곁에 있다)
    label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    row.addWidget(label, 0, Qt.AlignTop)
    row.addWidget(widget, 1)
    return box


def _overview_card(shell, vm, ui):
    """위쪽 한 카드 — 개수 요약(승인 전 안내 줄·개수 칩·채널별 쓸 수 있는 Seed 와 후보 생성 켜짐 여부) → 거르기(상태 칩·글 검색·'더 거르기') → 일괄 변경 줄. 세로 칸을 아껴 1366×768 에서도 Seed 줄이 보이게 한 카드로 묶었다."""
    summary, filters, bulk = vm["summary"], vm["filters"], vm["bulk"]
    frame, inner = UI.Card((16, 12, 16, 12))
    inner.setSpacing(K.SPACE["2"])
    frame.setAccessibleName(summary["a11y"])
    inner.addWidget(NoticeBar("warning" if summary["proposed"]["count"] else "info", summary["proposed"]["text"]))
    chips = [UI.Badge(chip["tone"], chip["text"]) for chip in summary["chips"]]
    channels = summary["channels"]
    for row in channels["rows"]:
        badge = UI.Badge(row["chip"]["tone"], row["chip"]["text"])
        badge.setAccessibleName(row["a11y"])
        chips.append(badge)
    inner.addWidget(UI.chip_row(chips))
    inner.addWidget(UI.label(channels["caption"], "caption", wrap=True))
    if channels["unknown"]:
        inner.addWidget(NoticeBar("warning", channels["unknown"]))
    inner.addWidget(_labeled(filters["status_title"], _chips(filters["status"], "seeds:status", shell.seed_status)))
    row = QHBoxLayout()
    row.setSpacing(K.SPACE["2"])
    edit = UI.TextInput(filters["query"]["label"], filters["query"]["placeholder"])
    edit.setProperty("focus_key", "seeds-query")
    edit.setText(filters["query"]["value"])
    edit.textEdited.connect(shell.seed_query)
    row.addWidget(edit, 1)
    more = UI.Button("ghost", filters["more"]["text"], "chevron_up" if filters["more"]["open"] else "chevron_down", focus_key="seeds-filter-more")
    more.clicked.connect(shell.seed_toggle_filters)
    row.addWidget(more)
    inner.addLayout(row)
    if filters["more"]["open"]:
        inner.addWidget(_labeled(filters["scope_title"], _chips(filters["scope"], "seeds:scope", shell.seed_scope)))
        inner.addWidget(_labeled(filters["importance_title"], _chips(filters["importance"], "seeds:importance", shell.seed_importance)))
    foot = QHBoxLayout()
    foot.setSpacing(K.SPACE["2"])
    ui.result = UI.label(filters["result"], "caption", wrap=True)
    foot.addWidget(ui.result, 1)
    ui.reset = UI.Button("ghost", filters["reset"], size="sm", focus_key="seeds-filter-reset")
    ui.reset.clicked.connect(shell.seed_reset_filters)
    ui.reset.setVisible(bool(filters["active"]))
    foot.addWidget(ui.reset)
    inner.addLayout(foot)
    ui.bulk_text = UI.label(bulk["text"], "small")
    ui.bulk_text.setMinimumHeight(K.SIZE["control_sm"])                          # 줄 안의 단추와 같은 높이에 가운데 맞춤(다음 줄로 넘어가는 배치는 위에 붙여 놓으므로)
    ui.bulk_text.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    ui.bulk_select = UI.Button("ghost", bulk["select_all"]["text"], size="sm", focus_key="seeds-select-all")
    ui.bulk_select.clicked.connect(shell.seed_select_all)
    ui.bulk_clear = UI.Button("ghost", bulk["clear"]["text"], size="sm", focus_key="seeds-clear-checks")
    ui.bulk_clear.clicked.connect(shell.seed_clear_checks)
    for action in bulk["actions"]:
        button = UI.Button("secondary", action["text"], size="sm", focus_key="seeds-bulk:" + action["key"])
        button.clicked.connect(lambda _=False, key=action["key"]: shell.seed_bulk(key))
        ui.bulk_buttons[action["key"]] = button
    bar = UI.chip_row([ui.bulk_text, ui.bulk_select, ui.bulk_clear, *ui.bulk_buttons.values()])      # 폭이 모자라면(최소 창 900×560) 다음 줄로 넘어간다 — 가로 스크롤이 생기지 않게
    bar.setAccessibleName(bulk["a11y"])
    inner.addWidget(bar)
    _update_bulk(ui, bulk)
    return frame


def _update_bulk(ui, bulk):
    ui.bulk_text.set_text(bulk["text"])
    ui.bulk_select.setText(bulk["select_all"]["text"])
    ui.bulk_select.setAccessibleName(bulk["select_all"]["text"])
    ui.bulk_select.setEnabled(bulk["select_all"]["enabled"])
    ui.bulk_clear.setEnabled(bulk["clear"]["enabled"])
    for action in bulk["actions"]:
        button = ui.bulk_buttons[action["key"]]
        button.setText(action["text"])
        button.setAccessibleName(action["text"])
        button.setEnabled(action["enabled"])
        UI.with_tooltip(button, action["reason"])
        button.setAccessibleDescription(action["reason"])


def update_seeds_live(page, vm):
    """고름·서랍이 열림이 바뀐 뒤 — 화면을 다시 그리지 않고 줄의 고름 표시와 일괄 변경 줄만 바꾼다."""
    ui = getattr(page, "seeds_ui", None)
    if ui is not None and ui.list is not None and vm["state"] == "normal":
        ui.list.update_checks(vm["list"])
        _update_bulk(ui, vm["bulk"])


def refilter_seeds_live(page, vm):
    """글 검색을 칠 때 — 줄 목록만 새로 짓고(검색 칸은 그대로라 커서가 안 튄다) 결과 글·일괄 변경 줄을 바꾼다."""
    ui = getattr(page, "seeds_ui", None)
    if ui is not None and ui.list is not None and vm["state"] == "normal":
        ui.list.set_rows(vm["list"])
        ui.result.set_text(vm["filters"]["result"])
        ui.reset.setVisible(bool(vm["filters"]["active"]))
        _update_bulk(ui, vm["bulk"])


def seeds_screen(shell, vm):
    """Seed 관리 — ① 머리 ② 알림 줄 ③ 개수 요약 ④ 거르기 ⑤ 일괄 변경 줄 ⑥ 줄 목록(읽는 중·읽기 오류는 홈·설정·블로그 관리와 같은 틀의 상태 카드)."""
    page = QWidget()
    outer = QVBoxLayout(page)
    margin = K.LAYOUT["page_margin"]
    outer.setContentsMargins(margin, margin, margin, margin)
    outer.setSpacing(K.LAYOUT["gap"])
    rights = [UI.SampleBadge(lambda: shell.show_sample_info("seed"), vm["sample_tip"])] if vm["sample"] else []
    normal = vm["state"] == "normal"
    pick = UI.Button("secondary", vm["import"], "upload", focus_key="seeds-import")
    pick.setEnabled(normal and not vm["busy"])
    pick.clicked.connect(shell.seed_import)
    new = UI.Button("secondary", vm["new"], "plus", focus_key="seed:new")
    new.setEnabled(normal and not vm["busy"])
    new.clicked.connect(shell.seed_open_new)
    refresh = UI.IconButton("refresh", vm["refresh"], focus_key="refresh-seeds")
    refresh.setEnabled(vm["state"] != "loading" and not vm["busy"])
    refresh.clicked.connect(shell.reload_seeds)
    rights += [pick, new, refresh]
    outer.addLayout(page_head(vm["title"], vm["sub"], rights))
    for _icon, message in vm["banners"]:
        outer.addWidget(NoticeBar("info", message))
    if vm["notice"]:
        outer.addWidget(NoticeBar(vm["notice"]["level"], vm["notice"]["text"]))
    ui = SeedsUi()
    page.seeds_ui = ui
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
        outer.addWidget(UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["desc"], vm["error"]["button"], shell.reload_seeds, holder))
        outer.addStretch(1)
    else:
        outer.addWidget(_overview_card(shell, vm, ui))
        ui.list = SeedList()
        ui.list.checked.connect(shell.seed_check)
        ui.list.opened.connect(shell.seed_open)
        ui.list.more.connect(shell.seed_more)
        ui.list.set_rows(vm["list"])
        outer.addWidget(ui.list)
        outer.addStretch(1)
    return page


# ---- 서랍(상세·새 Seed) ------------------------------------------------------------------------------------------------------------------
def _info_card(rows, label_stretch=4, value_stretch=5):
    card, inner = UI.Card((16, 12, 16, 12), kind="plain")
    inner.setSpacing(K.SPACE["2"])
    for row in rows:
        line = QHBoxLayout()
        line.setSpacing(K.SPACE["3"])
        line.addWidget(UI.label(row["label"], "small", wrap=True), label_stretch)
        line.addWidget(UI.label(row["value"], "muted" if row["missing"] else "body_lg", wrap=True), value_stretch)
        inner.addLayout(line)
    return card, inner


def update_seed_drawer_live(ui, vm):
    """칸을 고친 뒤 — 서랍을 다시 그리지 않고 오류 글·단추·'저장 전 변경' 표시만 그 자리에서 바꾼다(입력 중이던 커서·한글 조합이 사라지지 않게)."""
    for field in vm["fields"]:
        view = ui.fields.get(field["name"])
        if view is not None:
            view.update_from(field)
    for action in vm["actions"]:
        ui.bar.set_enabled(action["key"], action["enabled"], action["reason"] or action.get("hint", ""))
    if ui.unsaved is not None:
        ui.unsaved.setVisible(bool(vm["unsaved"]))
    errors = [field["name"] for field in vm["fields"] if field["error"]]
    ui.first_error = errors[0] if errors else None


def seed_drawer(shell, vm):
    """서랍 안쪽 → (내용 위젯, 닫기 단추, 아래 고정 행동 줄, 부품 모음). 행동 줄은 스크롤 밖이라 칸이 길어도 늘 보인다."""
    ui = SeedDrawerUi()
    body = QWidget()
    body.setAccessibleName(vm["a11y"])
    layout = QVBoxLayout(body)
    layout.setContentsMargins(K.SPACE["5"], K.SPACE["4"], K.SPACE["5"], K.SPACE["5"])
    layout.setSpacing(K.SPACE["4"])
    head = QHBoxLayout()
    head.addWidget(UI.label(vm["title"], "h2"), 1)
    close = UI.IconButton("x", vm["close"], focus_key="drawer-close")
    close.clicked.connect(shell.close_drawer)
    head.addWidget(close)
    layout.addLayout(head)
    if vm["heading"]:
        layout.addWidget(UI.label(vm["heading"], "h1", wrap=True))
    if vm["path"]:
        layout.addWidget(UI.label(vm["path"], "caption", wrap=True))
    meta = QHBoxLayout()
    meta.setSpacing(K.SPACE["2"])
    if vm["status"]:
        meta.addWidget(UI.Badge(vm["status"]["tone"], vm["status"]["text"]))
    ui.unsaved = UI.Badge("warning", vm["unsaved"]["text"] if vm["unsaved"] else T["seeds_flag_unsaved"])
    ui.unsaved.setVisible(bool(vm["unsaved"]))
    meta.addWidget(ui.unsaved)
    if vm["sample"]:
        meta.addWidget(UI.Badge("muted", vm["sample_tag"]))
    meta.addStretch(1)
    layout.addLayout(meta)
    for note in vm["notes"]:
        layout.addWidget(UI.label(note, "small", wrap=True))
    if vm["info"]:
        card, _inner = _info_card(vm["info"])
        layout.addWidget(card)
    schedule = vm["schedule"]
    if schedule is not None:
        card, inner = _info_card(schedule["rows"])
        inner.insertWidget(0, UI.label(schedule["title"], "h3"))
        inner.addWidget(UI.label(schedule["note"], "caption", wrap=True))
        layout.addWidget(card)
    for field in vm["fields"]:
        view = SeedFieldView(field)
        view.edited.connect(shell.seed_edit)
        view.toggled_choice.connect(lambda _name, value, shell=shell: shell.seed_toggle_channel(value))           # 칩 묶음의 신호는 (칸 이름, 값) 이다(P4c 가 일반화) — Seed 서랍의 칩 칸은 허용 채널 하나뿐이라 값만 넘긴다
        ui.fields[field["name"]] = view
        layout.addWidget(view)
    if vm["saving"]:
        layout.addWidget(UI.label(vm["saving_text"], "sub"))
    layout.addStretch(1)
    bar = ActionBar([{"key": action["key"], "text": action["text"], "kind": action["kind"]} for action in vm["actions"]], accessible=vm["actions_a11y"])
    bar.triggered.connect(shell.seed_action)
    ui.bar = bar
    update_seed_drawer_live(ui, vm)
    return body, close, bar, ui
