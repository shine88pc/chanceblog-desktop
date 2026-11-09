"""주제 후보 화면(P4d) — 뷰모델(`ui/core/candidates_view.py` 가 만든 딕셔너리)을 공통 부품(`components.py`·`gauges.py`·`candidate_parts.py`)으로 조립하기만 한다.
화면: 위 머리(제목·예시 표시·**후보 만들기**(주요 행동 하나)·다시 읽기) → 알림 줄들 → (후보를 만들 수 없을 때) 준비 안내 카드 → **한 카드**(채널·작업 상태·점수 구간 칩·글 검색·더 거르기의 주제 묶음 칩·결과 개수) → **카드 격자**(3열·2열은 규칙이 정한다) —
오른쪽에는 **고정 상세 창**(셸이 창 오른쪽에 붙이는 `DetailPane`, 논리 폭 1366 이상) 또는 서랍(그보다 좁을 때)이 같은 상세 내용(`detail_content`)을 보인다.
화면은 읽기·고르기까지만 하고 **파일에 쓰는 일은 하지 않는다** — `후보 만들기` 를 누르면 셸(`shell.cand_*`)이 상태(`CandidatesController`)를 거쳐 미리 보기 → 확인창 → 서비스를 부른다(이 파일에는 쓰기 호출이 없다 — 시험이 소스를 훑는다).
글자를 치는 동안에는 화면 전체를 다시 그리지 않고(`refilter_candidates_live`) 입력 중이던 자리가 사라지지 않는다. 가로 스크롤은 없다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .blog_parts import NoticeBar
from .candidate_parts import CandidateGrid, CardChip, CardImage, ChannelAvatar, FactorRow
from .bars import ActionBar
from .gauges import ScoreWithLabel
from .screens import page_head


class CandidatesUi:
    """한 번 그린 화면의 부품들 — 글을 치는 동안 화면을 다시 그리지 않고 이 부품들만 갱신하려고 들고 있는다."""

    def __init__(self):
        self.grid = None
        self.columns = 2
        self.result = None
        self.reset = None


def _chips(items, focus_prefix, on_click):
    group = []
    for item in items:
        chip = UI.FilterChip(item["label"], item["count"], item["active"], focus_key=f"{focus_prefix}:{item['key']}")
        chip.setAccessibleName(item["a11y"] if item["key"] != "all" else f"{item['label']} {item['count']}")
        chip.clicked.connect(lambda _=False, key=item["key"]: on_click(key))
        group.append(chip)
    return UI.chip_row(group)


def _labeled(title, widget):
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(K.SPACE["3"])
    label = UI.label(title, "small")
    label.setMinimumWidth(K.SIZE["control"] + K.SPACE["8"])
    label.setMinimumHeight(K.SIZE["chip_h"])
    label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    row.addWidget(label, 0, Qt.AlignTop)
    row.addWidget(widget, 1)
    return box


def _filter_card(shell, vm, ui):
    """위쪽 한 카드 — 채널·작업 상태 칩 → 글 검색과 `더 거르기`(점수 구간·주제 묶음 칩) → 결과 개수와 거르기 풀기. 세로 칸을 아껴 1366×768 에서도 카드 격자가 보이게 한 카드로 묶었고, 덜 쓰는 거르기(점수 구간·주제 묶음)는 `더 거르기` 뒤에 둔다."""
    filters = vm["filters"]
    frame, inner = UI.Card((16, 12, 16, 12))
    inner.setSpacing(K.SPACE["2"])
    frame.setAccessibleName(filters["a11y"])
    inner.addWidget(_labeled(filters["channel_title"], _chips(filters["channel"], "cand:channel", shell.cand_channel)))
    inner.addWidget(_labeled(filters["status_title"], _chips(filters["status"], "cand:status", shell.cand_status)))
    row = QHBoxLayout()
    row.setSpacing(K.SPACE["2"])
    edit = UI.TextInput(filters["query"]["label"], filters["query"]["placeholder"])
    edit.setProperty("focus_key", "cand-query")
    edit.setText(filters["query"]["value"])
    edit.textEdited.connect(shell.cand_query)
    row.addWidget(edit, 1)
    if filters["more"]["available"]:
        more = UI.Button("ghost", filters["more"]["text"], "chevron_up" if filters["more"]["open"] else "chevron_down", focus_key="cand-filter-more")
        more.clicked.connect(shell.cand_toggle_filters)
        row.addWidget(more)
    inner.addLayout(row)
    if filters["more"]["open"] and filters["more"]["available"]:                                          # 점수 구간·주제 묶음 — 조건이 걸려 있으면 열린 채
        inner.addWidget(_labeled(filters["band_title"], _chips(filters["band"], "cand:band", shell.cand_band)))
        if len(filters["cluster"]) > 1:
            inner.addWidget(_labeled(filters["cluster_title"], _chips(filters["cluster"], "cand:cluster", shell.cand_cluster)))
    foot = QHBoxLayout()
    foot.setSpacing(K.SPACE["2"])
    ui.result = UI.label(filters["result"], "caption", wrap=True)
    foot.addWidget(ui.result, 1)
    ui.reset = UI.Button("ghost", filters["reset"], size="sm", focus_key="cand-filter-reset")
    ui.reset.clicked.connect(shell.cand_reset_filters)
    ui.reset.setVisible(bool(filters["active"]))
    foot.addWidget(ui.reset)
    inner.addLayout(foot)
    return frame


def _prep_card(shell, prep):
    """후보를 만들 수 없을 때의 안내 — 아무것도 만들지 않았고 파일도 바꾸지 않았다는 것·무엇이 모자란지·이미 있는 화면(Seed 관리·블로그 관리)으로 가는 단추. 쓰기 단추는 없다."""
    frame, inner = UI.Card((20, 16, 20, 16))
    inner.setSpacing(K.SPACE["2"])
    frame.setAccessibleName(prep["a11y"])
    head = QHBoxLayout()
    head.setSpacing(K.SPACE["3"])
    head.addWidget(UI.ToneSwatch("alert", "orange"), 0, Qt.AlignVCenter)
    head.addWidget(UI.label(prep["title"], "h2", wrap=True), 1)
    if prep["sample"]:
        head.addWidget(UI.Badge("muted", prep["sample_tag"]), 0, Qt.AlignVCenter)
    inner.addLayout(head)
    inner.addWidget(UI.label(prep["lead"], "small", wrap=True))
    for line in prep["lines"]:
        inner.addWidget(UI.label("· " + line, "body", wrap=True))
    buttons = []
    for button in prep["buttons"]:
        made = UI.Button("ghost" if button["key"] == "close" else "secondary", button["text"], focus_key="cand-prep:" + button["key"])
        made.clicked.connect(lambda _=False, key=button["key"]: shell.cand_prep_action(key))
        buttons.append(made)
    inner.addWidget(UI.chip_row(buttons))
    frame.buttons = buttons
    return frame


def candidates_screen(shell, vm):
    """주제 후보 — ① 머리 ② 알림 줄들 ③ (준비 안내) ④ 거르기 카드 ⑤ 카드 격자(읽는 중·읽기 오류는 홈·설정·Seed 관리와 같은 틀의 상태 카드). 열 수·상세 창 방식은 창 폭이 정한 `part_rules.DetailLayout`(`shell.detail_layout()`)이다."""
    layout = shell.detail_layout()
    page = QWidget()
    outer = QVBoxLayout(page)
    wide = layout.columns == K.FRAME["detail_columns_wide"]
    pad = K.FRAME["workspace_pad"] if wide else K.FRAME["workspace_pad_narrow"]
    outer.setContentsMargins(pad, pad, pad, pad)
    outer.setSpacing(K.LAYOUT["gap"])
    rights = [UI.SampleBadge(lambda: shell.show_sample_info("topics"), vm["sample_tip"])] if vm["sample"] else []
    make = UI.Button("primary", vm["make"]["text"], "plus", focus_key="cand-make")
    make.setEnabled(vm["make"]["enabled"])
    UI.with_tooltip(make, vm["make"]["reason"] or vm["make"]["tip"])
    make.setAccessibleDescription(vm["make"]["reason"] or vm["make"]["tip"])
    make.clicked.connect(shell.cand_make)
    refresh = UI.IconButton("refresh", vm["refresh"], focus_key="refresh-candidates")
    refresh.setEnabled(vm["state"] != "loading" and not vm["busy"])
    refresh.clicked.connect(shell.reload_candidates)
    rights += [make, refresh]
    outer.addLayout(page_head(vm["title"], vm["sub"], rights))
    for _level, message in vm["banners"]:
        outer.addWidget(NoticeBar(_level, message))
    if vm["notice"]:
        outer.addWidget(NoticeBar(vm["notice"]["level"], vm["notice"]["text"]))
    ui = CandidatesUi()
    ui.columns = layout.columns
    page.cand_ui = ui
    if vm["prep"] is not None:
        page.prep_card = _prep_card(shell, vm["prep"])
        outer.addWidget(page.prep_card)
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
        outer.addWidget(UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["user"] or vm["error"]["desc"], vm["error"]["button"], shell.reload_candidates, holder))
        outer.addStretch(1)
    else:
        if vm["filters"] is not None:                                                                      # 후보가 하나도 없으면(보관함 없음·옛 구조·후보 없음) 거를 것이 없어 거르기 카드를 두지 않는다
            outer.addWidget(_filter_card(shell, vm, ui))
        ui.grid = CandidateGrid(layout.columns, K.CARD["gap"] if wide else K.CARD["gap_narrow"])
        ui.grid.opened.connect(shell.cand_open)
        ui.grid.more.connect(shell.cand_more)
        ui.grid.reset.connect(shell.cand_reset_filters)
        ui.grid.set_content(vm["grid"], layout.columns, after=ui.reset)
        outer.addWidget(ui.grid)
        outer.addStretch(1)
    return page


def refilter_candidates_live(page, vm):
    """글 검색을 칠 때 — 카드 격자만 새로 놓고(검색 칸은 그대로라 커서가 안 튄다) 결과 글·거르기 풀기 단추를 바꾼다."""
    ui = getattr(page, "cand_ui", None)
    if ui is not None and ui.grid is not None and vm["state"] == "normal" and vm["filters"] is not None:
        ui.grid.set_content(vm["grid"], ui.columns, after=ui.reset)
        ui.result.set_text(vm["filters"]["result"])
        ui.reset.setVisible(bool(vm["filters"]["active"]))


# ---- 상세(고정 창·서랍 공용) ---------------------------------------------------------------------------------------------------------------
def _section(title):
    card, inner = UI.Card((16, 12, 16, 12), kind="plain")
    inner.setSpacing(K.SPACE["2"])
    inner.addWidget(UI.label(title, "h3"))
    return card, inner


def _rows(inner, rows):
    for row in rows:
        line = QHBoxLayout()
        line.setSpacing(K.SPACE["3"])
        line.addWidget(UI.label(row["label"], "small", wrap=True), 4)
        line.addWidget(UI.label(row["value"], "muted" if row["missing"] else "body_lg", wrap=True), 5)
        inner.addLayout(line)


def _safety_card(card_vm):
    box = QWidget()
    inner = QVBoxLayout(box)
    inner.setContentsMargins(0, K.SPACE["1"], 0, K.SPACE["1"])
    inner.setSpacing(K.SPACE["1"])
    head = QHBoxLayout()
    head.setSpacing(K.SPACE["2"])
    head.addWidget(UI.Badge(card_vm["tone"], card_vm["level"]), 0, Qt.AlignVCenter)
    head.addWidget(UI.label(card_vm["title"], "h3", wrap=True), 1)
    inner.addLayout(head)
    inner.addWidget(UI.label(card_vm["message"], "small", wrap=True))
    inner.addWidget(UI.label(card_vm["action"], "small", wrap=True))
    for line in card_vm["details"]:
        inner.addWidget(UI.label("· " + line, "caption", wrap=True))
    box.setAccessibleName(f"{card_vm['level']}, {card_vm['title']}")
    return box


def detail_content(shell, vm):
    """상세 안쪽 — (내용 위젯, 닫기 단추). 고정 상세 창과 서랍이 같은 내용을 쓴다. 아래 고정 행동 줄은 이 안이 아니라 `detail_footer`(P4e — `이 주제로 만들기`)가 스크롤 밖에 따로 만든다(`번호 복사` 는 머리 줄의 작은 단추 그대로다).
    순서: 머리(닫기) → 이미지 자리 → 제목·배지 → 점수 링과 채널·번호 → 키워드·협업 유형 → 점수 구성 → 추천 이유 → 최근 관심도(상대값) → Seed 출처 → 안전 표시 → 다시 볼 기한 → 기본 정보."""
    body = QWidget()
    body.setAccessibleName(vm["a11y"])
    layout = QVBoxLayout(body)
    layout.setContentsMargins(K.SPACE["5"], K.SPACE["4"], K.SPACE["5"], K.SPACE["5"])
    layout.setSpacing(K.SPACE["4"])
    head = QHBoxLayout()
    head.addWidget(UI.label(vm["title"], "small"), 1)
    close = UI.IconButton("x", vm["close"], focus_key="detail-close")
    close.clicked.connect(shell.close_drawer)
    head.addWidget(close)
    layout.addLayout(head)
    layout.addWidget(CardImage(vm["image"]["icon"], vm["image"]["tone"], vm["image"]["state_text"], height=96, glyph=36))
    layout.addWidget(UI.label(vm["heading"], "h2", wrap=True))
    badges = [UI.Badge(badge["tone"], badge["text"]) for badge in vm["badges"]]
    if vm["sample"]:
        badges.append(UI.Badge("muted", vm["sample_tag"]))
    layout.addWidget(UI.chip_row(badges))
    top = QHBoxLayout()
    top.setSpacing(K.SPACE["4"])
    score = ScoreWithLabel(vm["score"], None, "detail", missing_text=vm["missing_text"])
    top.addWidget(score, 0, Qt.AlignTop)
    side = QVBoxLayout()
    side.setSpacing(K.SPACE["2"])
    if vm["final_text"]:
        side.addWidget(UI.label(vm["final_text"], "h3"))
    channel = QHBoxLayout()
    channel.setSpacing(K.SPACE["2"])
    channel.addWidget(ChannelAvatar(vm["channel"]["avatar"], vm["channel"]["preset"]), 0, Qt.AlignVCenter)
    channel.addWidget(UI.ElidedLabel(vm["channel"]["name"], "body"), 1)
    side.addLayout(channel)
    number = QHBoxLayout()
    number.setSpacing(K.SPACE["2"])
    number.addWidget(UI.label(vm["number"]["text"], "caption"), 1)
    copy = UI.IconButton("copy", vm["number"]["a11y"], focus_key="detail-copy")
    copy.clicked.connect(lambda: shell.cand_copy(vm["number"]))
    number.addWidget(copy)
    side.addLayout(number)
    top.addLayout(side, 1)
    layout.addLayout(top)
    words, tags = vm["keywords"], vm["tags"]
    card, inner = _section(words["title"])
    inner.addWidget(UI.chip_row([CardChip(word) for word in words["items"]]))
    if tags is not None:
        inner.addWidget(UI.label(tags["title"], "small"))
        inner.addWidget(UI.chip_row([CardChip(item) for item in tags["items"]]))
    layout.addWidget(card)
    factors = vm["factors"]
    card, inner = _section(factors["title"])
    if factors["rows"]:
        for row in factors["rows"]:
            inner.addWidget(FactorRow(row))
        if factors["note"]:
            inner.addWidget(UI.label(factors["note"], "caption", wrap=True))
    else:
        inner.addWidget(UI.label(factors["empty"], "muted", wrap=True))
    layout.addWidget(card)
    reason = vm["reason"]
    card, inner = _section(reason["title"])
    if reason["lines"]:
        for line in reason["lines"]:
            inner.addWidget(UI.label("· " + line, "body", wrap=True))
    else:
        inner.addWidget(UI.label(reason["empty"], "muted", wrap=True))
    layout.addWidget(card)
    trend = vm["trend"]
    card, inner = _section(trend["title"])
    _rows(inner, trend["rows"])
    inner.addWidget(UI.label(trend["note"], "caption", wrap=True))
    layout.addWidget(card)
    seed = vm["seed"]
    card, inner = _section(seed["title"])
    _rows(inner, seed["rows"])
    layout.addWidget(card)
    safety = vm["safety"]
    card, inner = _section(safety["title"])
    for item in safety["cards"]:
        inner.addWidget(_safety_card(item))
    if safety["stop"]:
        inner.addWidget(UI.label(safety["stop"], "small", wrap=True))
    if safety["none"]:
        inner.addWidget(UI.label(safety["none"], "muted", wrap=True))
    layout.addWidget(card)
    if vm["hold"] is not None:
        card, inner = _section(vm["hold"]["label"])
        inner.addWidget(UI.label(vm["hold"]["value"], "body_lg"))
        inner.addWidget(UI.label(vm["hold"]["note"], "caption", wrap=True))
        layout.addWidget(card)
    info = vm["info"]
    card, inner = _section(info["title"])
    _rows(inner, info["rows"])
    layout.addWidget(card)
    layout.addStretch(1)
    return body, close


def detail_footer(shell, vm):
    """상세 아래 고정 행동 줄(C-Type §8.3, P4e) — 주요 단추 `이 주제로 만들기` 하나. 안전 판정이 '자동 초안 중지' 인 후보·네이버가 아닌 채널의 후보는 꺼 두고 까닭을 단추 아래에 글로 보인다(꺼진 단추는 Tab 이 가지 않아 툴팁만으로는 못 읽는다).
    보류·제외·Seed 로 등록은 동작하지 않아 만들지 않는다. 고정 상세 창과 서랍이 같은 줄을 쓴다."""
    draft = vm["draft"]
    footer = QWidget()
    box = QVBoxLayout(footer)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(0)
    if draft["reason"]:
        reason = UI.label(draft["reason"], "caption", wrap=True)
        reason.setContentsMargins(K.SPACE["4"], K.SPACE["2"], K.SPACE["4"], K.SPACE["2"])
        box.addWidget(reason)
    bar = ActionBar([{"key": "make", "text": draft["text"], "kind": "primary"}], accessible=draft["bar_a11y"])
    bar.set_enabled("make", draft["enabled"], draft["tip"])
    bar.triggered.connect(lambda _key: shell.cand_make_draft())
    box.addWidget(bar)
    footer.bar = bar
    return footer


def pane_placeholder(vm):
    """고정 상세 창이 비어 있을 때(아무것도 안 골랐을 때)의 안내 — 아이콘 + 제목 + 한 줄 설명(단추 없음)."""
    body = QWidget()
    body.setAccessibleName(vm["title"])
    layout = QVBoxLayout(body)
    layout.setContentsMargins(K.SPACE["6"], K.SPACE["10"], K.SPACE["6"], K.SPACE["6"])
    layout.setSpacing(K.SPACE["3"])
    layout.addWidget(UI.ToneSwatch("search", "blue", glyph=K.ICON["empty"], box=72), 0, Qt.AlignHCenter)
    head = UI.label(vm["title"], "h2", wrap=True)
    head.setAlignment(Qt.AlignCenter)
    layout.addWidget(head)
    sub = UI.label(vm["desc"], "sub", wrap=True)
    sub.setAlignment(Qt.AlignCenter)
    layout.addWidget(sub)
    layout.addStretch(1)
    return body
