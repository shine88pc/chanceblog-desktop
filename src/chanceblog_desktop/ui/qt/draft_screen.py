"""초안 작성 화면(P4e) — 뷰모델(`ui/core/drafts_view.py` 가 만든 딕셔너리)을 공통 부품(`components.py`)과 이 화면의 부품(`draft_parts.py`)으로 조립하기만 한다.
화면(C-Type §15.4): 위 머리(`← 주제 후보`) → 알림 줄 → 맥락 한 줄(후보·블로그·글 유형 + `만드는 방법 바꾸기`) → (펼치면) 만드는 방법(블로그·글 유형·선택 입력·`다시 만들기`) →
**왼쪽 약 68%**: 제목(입력 + 제목 후보 셋) · 본문 편집기(최소 높이 420~480) / **오른쪽 약 32%**: 검사 결과 · 키워드 · 태그 · 추천 카테고리 · 한 줄 요약 · 대표 이미지(상태 둘) · 확인 권장(이 글에만 해당은 펼침·모든 글 공통은 접힘) →
**아래 고정 행동 줄**(스크롤 밖): `제목 복사`·`본문 복사`·`전체 복사`(주요 단추 하나)·`네이버 글쓰기 열기`(주소만 연다). 창 논리 폭이 1280 미만이면 오른쪽 칸이 편집기 아래로 내려온다. 가로 스크롤은 없다.
화면은 읽기·고치기·복사 단추까지만 하고 **파일에 쓰는 일은 하지 않는다** — 단추를 누르면 셸(`shell.drf_*`)이 상태(`DraftsController`)를 거쳐 서비스·클립보드를 부른다(이 파일에는 쓰기·복사·네트워크 호출이 없다 — 시험이 소스를 훑는다).
글을 치는 동안에는 화면 전체를 다시 그리지 않는다(글자 수·고친 정도·제목 후보 표시만 그 자리에서 바꾼다) — 입력 중이던 커서·한글 조합이 사라지지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core import draft_rules as rules
from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .bars import ActionBar
from .blog_parts import NoticeBar
from .candidate_parts import CardChip
from .draft_parts import GarbageCard, InspectCard, SavedRowCard, TextArea, TitleInput, TitlePick, lines_box, set_copy_look
from .screens import page_head


class DraftsUi:
    """한 번 그린 화면의 부품들 — 글을 치는 동안 화면을 다시 그리지 않고 이 부품들만 갱신하려고 들고 있는다."""

    def __init__(self):
        self.title = self.editor = self.count = self.edit = self.inspect = self.inspect_button = self.notice = None
        self.picks, self.copy, self.blog_chips, self.type_chips, self.fields = [], {}, {}, {}, {}
        self.options_panel = self.options_toggle = self.pending_note = None
        self.image_state = self.image_button = None
        self.accordions = {}
        self.checks_status = None
        self.back = self.apply = self.actions = self.action_bar = None
        self.side = False
        self.stops = []
        self.saved_list = self.save_status = None                                 # 머리의 `저장한 초안` 단추 · 편집기 아래의 저장 상태 줄(D-361)
        self.saved_rows = []                                                      # 저장한 초안 목록의 줄들(`SavedRowCard`)
        self.garbage = None                                                      # 글 모양 점검 카드(`draft_parts.GarbageCard`) — 항목별 무시 단추가 동적이라 Tab 순서를 다시 잇는다
        self.garbage_focus = False                                               # 검사 중 꺼 둔 `검사하기` 단추가 포커스를 쥐고 있었다 — 끝나면 돌려준다


def _section(title):
    card, inner = UI.Card((16, 12, 16, 12), kind="plain")
    inner.setSpacing(K.SPACE["2"])
    inner.addWidget(UI.label(title, "h3"))
    return card, inner


def _pad(shell):
    return K.FRAME["workspace_pad"] if shell.width() >= rules.SIDE_BY_SIDE_FROM else K.FRAME["workspace_pad_narrow"]


def _head(shell, vm, ui, back=True):
    """화면 머리 — 제목·설명·(예시일 때) 예시 표시·`← 주제 후보`. 빈 화면·거절·후보 없음은 자기 안의 `주제 후보로 가기` 단추 하나뿐이라 머리의 되돌아가기를 두지 않는다(`back=False`)."""
    rights = [UI.SampleBadge(lambda: shell.show_sample_info("drafts"), vm["sample_tip"])] if vm["sample"] else []
    if back:
        ui.back = UI.Button("ghost", vm["back"]["text"], accessible=vm["back"]["a11y"], focus_key="drf-back")
        ui.back.clicked.connect(lambda: shell.drf_to_topics())
        rights.append(ui.back)
        if vm.get("saved_list"):                                                  # 저장 기능이 있으면 머리에서 저장한 초안 목록으로 갈 수 있다(고친 내용이 저장되지 않았으면 떠나기 확인창이 먼저)
            ui.saved_list = UI.Button("ghost", vm["saved_list"]["text"], accessible=vm["saved_list"]["a11y"], focus_key="drf-saved-list")
            ui.saved_list.setEnabled(vm["saved_list"]["enabled"])
            ui.saved_list.clicked.connect(lambda: shell.drf_show_saved())
            rights.append(ui.saved_list)
    return page_head(vm["title"], vm["sub"], rights)


def _copy_button(shell, ui, vm, size="sm"):
    button = UI.Button("secondary", vm["text"], "copy", size=size, accessible=vm["a11y"], focus_key="drf-copy:" + vm["key"])
    button.setEnabled(vm["enabled"])
    button.setProperty("base_text", vm["a11y"])                                  # 복사됨 모양이 끝나면 돌아갈 글
    button.clicked.connect(lambda _=False, key=vm["key"]: shell.drf_copy(key))
    if vm["copied"]:
        set_copy_look(button, vm["text"], True, vm["a11y"])
    ui.copy[vm["key"]] = button
    return button


# ---- 읽는 중·오류·거절·빈 화면 -----------------------------------------------------------------------------------------------------------------
def _saved_card(shell, saved, ui):
    """저장한 초안 목록 카드 — 읽는 중(자리 표시)·오류(다시 읽기)·비어 있음·줄들. 줄마다 `열기`·`지우기`(지우기는 확인창이 먼저). 위에 알림 한 줄(지웠다·열지 못했다)이 있을 수 있다. 목록은 읽기뿐이다."""
    count = saved["count_text"]
    card, inner = _section(f"{saved['title']} · {count}" if count else saved["title"])
    card.setAccessibleName(saved["a11y"])
    inner.addWidget(UI.label(saved["sub"], "caption", wrap=True))
    if saved["notice"]:
        inner.addWidget(NoticeBar(saved["notice"]["level"], saved["notice"]["text"]))
    state = saved["state"]
    if state == "loading":
        inner.addWidget(UI.Skeleton(2, saved["loading_a11y"]))
        inner.addWidget(UI.label(saved["loading"], "sub"))
    elif state == "error":
        inner.addWidget(UI.label(saved["error"]["text"], "body", wrap=True))
        retry = UI.Button("secondary", saved["error"]["button"], "refresh", size="sm", accessible=saved["error"]["a11y"], focus_key="drf-saved-retry")
        retry.clicked.connect(lambda: shell.drf_saved_retry())
        inner.addWidget(retry, 0, Qt.AlignLeft)
    elif not saved["rows"]:
        inner.addWidget(UI.label(saved["empty"], "muted", wrap=True))
    else:
        if saved["unreadable_note"]:
            inner.addWidget(UI.label(saved["unreadable_note"], "small", wrap=True))
        for index, row in enumerate(saved["rows"]):
            line = SavedRowCard(row, index)
            line.opened.connect(shell.drf_saved_open)
            line.deleted.connect(shell.drf_saved_delete)
            ui.saved_rows.append(line)
            inner.addWidget(line)
    return card


def _state_page(shell, vm):
    ui = DraftsUi()
    page = QWidget()
    outer = QVBoxLayout(page)
    pad = _pad(shell)
    outer.setContentsMargins(pad, pad, pad, pad)
    outer.setSpacing(K.LAYOUT["gap"])
    state = vm["state"]
    outer.addLayout(_head(shell, vm, ui, back=state in ("loading", "error")))
    if vm["notice"]:
        outer.addWidget(NoticeBar(vm["notice"]["level"], vm["notice"]["text"]))
    if state == "loading":
        card, inner = UI.Card((24, 20, 24, 20))
        inner.addWidget(UI.Skeleton(3, vm["loading"]["a11y"]))
        note = UI.label(vm["loading"]["text"], "sub")
        note.setAlignment(Qt.AlignCenter)
        inner.addWidget(note)
        outer.addWidget(card)
    elif state == "error":
        diag = UI.Disclosure(T["diag_show"], T["diag_hide"], vm["error"]["diag"])
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(diag)
        box.addWidget(UI.label(T["diag_note"], "caption", wrap=True))
        outer.addWidget(UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["user"] or vm["error"]["desc"], vm["error"]["button"], shell.drf_retry, holder))
    elif state == "refused":
        extra = UI.label(vm["refused"]["candidate"], "caption", wrap=True) if vm["refused"]["candidate"] else None
        outer.addWidget(UI.StateCard("shield", "orange", vm["refused"]["title"], vm["refused"]["desc"], vm["refused"]["button"], lambda: shell.drf_to_topics(), extra))
    elif state == "notfound":
        outer.addWidget(UI.StateCard("inbox", "slate", vm["notfound"]["title"], vm["notfound"]["desc"], vm["notfound"]["button"], lambda: shell.drf_to_topics()))
    else:
        outer.addWidget(UI.StateCard("draft", "blue", vm["empty"]["title"], "", vm["empty"]["button"], lambda: shell.drf_to_topics()))
        if vm["empty"].get("saved"):
            outer.addWidget(_saved_card(shell, vm["empty"]["saved"], ui))
    outer.addStretch(1)
    page.drf_ui = ui
    return page


# ---- 왼쪽: 제목·본문 ---------------------------------------------------------------------------------------------------------------------------
def _title_card(shell, box, ui):
    card, inner = _section(box["label"])
    ui.title = TitleInput(box["a11y"])
    ui.title.setProperty("focus_key", "drf-title")
    ui.title.setText(box["value"])
    ui.title.textEdited.connect(shell.drf_title_edited)
    inner.addWidget(ui.title)
    inner.addWidget(UI.label(box["picks_title"], "small"))
    for vm in box["picks"]:
        pick = TitlePick(vm)
        pick.picked.connect(shell.drf_pick)
        ui.picks.append(pick)
        inner.addWidget(pick)
    if not box["editable"]:                                                      # 새 초안을 만드는 동안 — 친 글이 새 초안에 덮이지 않게 읽기 전용(독립 검증 V5)
        ui.title.setReadOnly(True)
        ui.title.setAccessibleDescription(box["locked_text"])
        for pick in ui.picks:
            pick.setEnabled(False)
    return card


def _body_card(shell, editor, ui):
    card, inner = _section(editor["label"])
    ui.editor = TextArea(editor["a11y"], min_height=editor["min_height"], focus_key="drf-body")
    ui.editor.set_value(editor["value"])
    ui.editor.edited.connect(shell.drf_body_edited)
    if not editor["editable"]:                                                   # 새 초안을 만드는 동안 읽기 전용 — 글을 칠 수 없으니 새 초안에 덮여 사라지는 글도 없다(독립 검증 V5)
        ui.editor.setReadOnly(True)
        ui.editor.setAccessibleDescription(editor["locked_text"])
    inner.addWidget(ui.editor, 1)
    row = QHBoxLayout()
    row.setSpacing(K.SPACE["3"])
    ui.count = UI.label(editor["count_text"], "caption")
    ui.edit = UI.label(editor["edit_text"], "caption")
    row.addWidget(ui.count, 1)
    row.addWidget(ui.edit)
    inner.addLayout(row)
    if "save_text" in editor:                                                    # 저장 상태 — 글로 말한다(`● 저장 안 됨`·`✓ 저장됨 · 시각`·`● 저장한 뒤 고쳤어요`) 색만으로 전하지 않는다
        ui.save_status = UI.label(editor["save_text"], "caption")
        ui.save_status.set_tone(editor["save_tone"])
        ui.save_status.setAccessibleName(editor["save_a11y"])
        inner.addWidget(ui.save_status)
    return card


# ---- 맥락·만드는 방법 ------------------------------------------------------------------------------------------------------------------------
def _context_card(shell, normal, ui):
    context, options = normal["context"], normal["options"]
    frame, inner = UI.Card((16, 10, 16, 10), kind="plain")
    frame.setAccessibleName(context["a11y"])
    row = QHBoxLayout()
    row.setSpacing(K.SPACE["3"])
    texts = QVBoxLayout()
    texts.setSpacing(0)
    if context["candidate"]:
        texts.addWidget(UI.label(context["candidate"], "body", wrap=True))
    texts.addWidget(UI.label(context["made"], "small", wrap=True))
    row.addLayout(texts, 1)
    ui.options_toggle = UI.Button("ghost", options["toggle"], "chevron_up" if options["open"] else "chevron_down", size="sm", focus_key="drf-options-toggle")
    ui.options_toggle.clicked.connect(shell.drf_toggle_options)
    row.addWidget(ui.options_toggle, 0, Qt.AlignVCenter)
    inner.addLayout(row)
    return frame


def _choice_row(title, items, ui_map, handler, focus_prefix):
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(K.SPACE["3"])
    label = UI.label(title, "small")
    label.setMinimumWidth(K.SIZE["control"] + K.SPACE["8"])
    row.addWidget(label, 0, Qt.AlignTop)
    chips = []
    for item in items:
        chip = UI.FilterChip(item["label"], None, item["active"], focus_key=f"{focus_prefix}:{item['key']}")
        chip.setAccessibleName(item["a11y"])
        chip.clicked.connect(lambda _=False, key=item["key"]: handler(key))
        ui_map[item["key"]] = chip
        chips.append(chip)
    row.addWidget(UI.chip_row(chips), 1)
    return box


def _options_panel(shell, options, ui):
    frame, inner = UI.Card((16, 12, 16, 12), kind="plain")
    frame.setAccessibleName(options["title"])
    inner.setSpacing(K.SPACE["3"])
    inner.addWidget(UI.label(options["title"], "h3"))
    inner.addWidget(UI.label(options["note"], "caption", wrap=True))
    inner.addWidget(_choice_row(options["blog_title"], options["blogs"], ui.blog_chips, shell.drf_blog, "drf-blog"))
    inner.addWidget(_choice_row(options["type_title"], options["types"], ui.type_chips, shell.drf_post_type, "drf-type"))
    for field in options["fields"]:
        inner.addWidget(UI.label(field["label"], "small"))
        if field["single"]:
            edit = UI.TextInput(field["a11y"])
            edit.setProperty("focus_key", "drf-field:" + field["name"])
            edit.setText(field["value"])
            edit.textEdited.connect(lambda text, name=field["name"]: shell.drf_option_edited(name, text))
        else:
            edit = TextArea(field["a11y"], min_height=K.SIZE["control"] * 2, focus_key="drf-field:" + field["name"])
            edit.setMaximumHeight(K.SIZE["control"] * 2 + K.SPACE["4"])
            edit.set_value(field["value"])
            edit.edited.connect(lambda text, name=field["name"]: shell.drf_option_edited(name, text))
        edit.setToolTip(field["hint"])
        ui.fields[field["name"]] = edit
        inner.addWidget(edit)
        inner.addWidget(UI.label(field["hint"], "caption", wrap=True))
    ui.pending_note = UI.label(options["pending_text"], "small", wrap=True)
    ui.pending_note.set_tone("orange")
    ui.pending_note.setVisible(bool(options["pending"]))
    inner.addWidget(ui.pending_note)
    ui.apply = UI.Button("secondary", options["apply"]["text"], "refresh", accessible=options["apply"]["text"], focus_key="drf-remake")
    ui.apply.setEnabled(options["apply"]["enabled"])
    UI.with_tooltip(ui.apply, options["apply"]["tip"])
    ui.apply.setAccessibleDescription(options["apply"]["tip"])
    ui.apply.clicked.connect(shell.drf_remake)
    inner.addWidget(ui.apply, 0, Qt.AlignLeft)
    frame.setVisible(bool(options["open"]))
    ui.options_panel = frame
    return frame


# ---- 오른쪽 칸 --------------------------------------------------------------------------------------------------------------------------------
def _inspect_card(shell, vm, ui):
    card, inner = _section(vm["title"])
    button = UI.Button("secondary", vm["button"], "check_circle", size="sm", accessible=vm["button_a11y"], focus_key="drf-inspect")
    button.clicked.connect(shell.drf_inspect)
    inner.addWidget(button, 0, Qt.AlignLeft)
    inner.addWidget(UI.label(vm["hint"], "caption", wrap=True))
    status = UI.label(vm["status"], "body", wrap=True)
    inner.addWidget(status)
    box = lines_box()
    inner.addWidget(box)
    ui.inspect = InspectCard(status, box)
    ui.inspect.set_state(vm)
    ui.inspect_button = button
    return card


def _garbage_card(shell, vm, ui):
    """글 모양 점검 카드(N-2) — 검사 결과 카드 바로 아래의 새 카드. 머리에 `복사를 막지 않아요` 한 줄, 안내·상태 줄·`본문이 변경됨`·종류별 항목과 `무시` 단추. 색은 안내(파랑)와 흐림(회색)뿐이고 복사·확인창과 이어진 것이 없다."""
    card, inner = _section(vm["title"])
    inner.addWidget(UI.label(vm["note"], "caption"))
    inner.addWidget(UI.label(vm["hint"], "caption", wrap=True))
    status = UI.label(vm["status"], "body", wrap=True)
    inner.addWidget(status)
    stale = UI.label(vm["stale_text"], "small", wrap=True)
    inner.addWidget(stale)
    rows = lines_box()
    rows.layout().setSpacing(K.SPACE["2"])
    inner.addWidget(rows)
    ignore_all = UI.Button("ghost", vm["ignore_all"]["text"], size="sm", accessible=vm["ignore_all"]["a11y"], focus_key="drf-garbage:all")
    restore = UI.Button("ghost", vm["restore"]["text"] or "-", size="sm", accessible=vm["restore"]["a11y"] or "-", focus_key="drf-garbage:restore")
    inner.addWidget(ignore_all, 0, Qt.AlignLeft)
    inner.addWidget(restore, 0, Qt.AlignLeft)
    ui.garbage = GarbageCard(status, stale, rows, ignore_all, restore, shell.drf_garbage_ignore, shell.drf_garbage_ignore_all, shell.drf_garbage_restore)
    ui.garbage.set_state(vm)
    return card


def _chips_card(shell, ui, title, parts, copy_vm):
    card, inner = _section(title)
    for label, items in parts:
        if label:
            inner.addWidget(UI.label(label, "small"))
        inner.addWidget(UI.chip_row([CardChip(item) for item in items]) if items else UI.label("—", "muted"))
    inner.addWidget(_copy_button(shell, ui, copy_vm), 0, Qt.AlignLeft)
    return card


def _text_card(title, text, missing=False, copy=None):
    card, inner = _section(title)
    inner.addWidget(UI.label(text, "muted" if missing else "body", wrap=True))
    if copy is not None:
        inner.addWidget(copy, 0, Qt.AlignLeft)
    return card


def _image_card(shell, vm, ui):
    card, inner = _section(vm["title"])
    ui.image_state = UI.label(vm["state_text"], "h3")
    inner.addWidget(ui.image_state)
    inner.addWidget(UI.label(vm["desc"], "caption", wrap=True))
    ui.image_button = UI.Button("secondary", vm["button"], size="sm", accessible=vm["button_a11y"], focus_key="drf-image")
    ui.image_button.clicked.connect(shell.drf_toggle_image)
    inner.addWidget(ui.image_button, 0, Qt.AlignLeft)
    return card


def _checks_card(shell, vm, ui):
    card, inner = _section(vm["title"])
    ui.checks_status = UI.label(vm["status"], "small", wrap=True)                    # 출처와 확인 필요 상태 한 줄(완료 조건 ⑭)
    inner.addWidget(ui.checks_status)
    for group in (vm["specific"], vm["common"]):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(K.SPACE["2"], 0, 0, K.SPACE["2"])
        layout.setSpacing(K.SPACE["2"])
        for line in (group["lines"] or ([group["empty"]] if group.get("empty") else [])):
            layout.addWidget(UI.label("· " + line if group["lines"] else line, "small" if group["lines"] else "muted", wrap=True))
        accordion = UI.Accordion(group["key"], group["title"], [{"tone": group["tone"], "text": group["chip"]}], body, group["open"], vm["open_text"], vm["closed_text"], group["chip"], focus_key="drf-checks:" + group["key"])
        accordion.toggled.connect(shell.drf_checks_toggled)
        ui.accordions[group["key"]] = accordion
        inner.addWidget(accordion)
    return card


def _right(shell, side, ui):
    column = QVBoxLayout()
    column.setSpacing(K.LAYOUT["gap"])
    column.addWidget(_inspect_card(shell, side["inspect"], ui))
    column.addWidget(_garbage_card(shell, side["garbage"], ui))                  # 글 모양 점검 — 검사 결과 카드 바로 아래, 따로 선 새 카드(경고만)
    keywords = side["keywords"]
    column.addWidget(_chips_card(shell, ui, keywords["title"], ((keywords["core_title"], keywords["core"]), (keywords["sub_title"], keywords["sub"])), keywords["copy"]))
    column.addWidget(_chips_card(shell, ui, side["tags"]["title"], ((None, side["tags"]["items"]),), side["tags"]["copy"]))
    column.addWidget(_text_card(side["category"]["title"], side["category"]["text"], side["category"]["missing"]))
    column.addWidget(_text_card(side["summary"]["title"], side["summary"]["text"], False, _copy_button(shell, ui, side["summary"]["copy"])))
    column.addWidget(_image_card(shell, side["image"], ui))
    column.addWidget(_checks_card(shell, side["checks"], ui))
    column.addStretch(1)
    return column


# ---- 아래 고정 행동 줄 --------------------------------------------------------------------------------------------------------------------------
def _action_bar(shell, vm, ui):
    """공통 부품 `bars.ActionBar`(UI-C0 — 주요 1·보조 ≤3·폭이 모자라면 `더보기 ⋮` 로 접힘)를 쓴다. 단추를 누르면 `triggered(열쇠)` 가 셸의 `drf_action` 으로 간다."""
    specs = [{"key": item["key"], "text": item["text"], "kind": {"save": "secondary", "title": "secondary", "body": "secondary", "all": "primary", "open": "tertiary"}[item["key"]]} for item in vm["buttons"]]
    bar = ActionBar(specs, accessible=vm["a11y"])
    bar.triggered.connect(shell.drf_action)
    ui.actions = {}
    for item, button in zip(vm["buttons"], bar.buttons, strict=True):
        bar.set_enabled(item["key"], item["enabled"], item["tip"])
        if item["key"] == "save":
            button.setAccessibleName(item["a11y"])                               # 읽는 이름은 단축키까지(`초안 저장하기(Ctrl+S)`) — 보이는 글자는 `저장`
        if item["key"] not in ("open", "save"):
            button.setProperty("base_text", item["a11y"])
            ui.copy[item["key"]] = button
            if item["copied"]:
                set_copy_look(button, item["text"], True, item["a11y"])
        ui.actions[item["key"]] = button
    ui.action_bar = bar
    return bar


# ---- 화면 ---------------------------------------------------------------------------------------------------------------------------------------
def _normal_page(shell, vm):
    normal = vm["normal"]
    ui = DraftsUi()
    ui.side = rules.side_by_side(shell.width())
    root = QWidget()
    root_layout = QVBoxLayout(root)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setFocusPolicy(Qt.NoFocus)                                           # Tab 정거장이 아니다 — 포커스가 간 칸이 보이도록 스크롤은 Qt 가 해 준다
    scroll.setAccessibleName(T["body_area"])
    content = QWidget()
    outer = QVBoxLayout(content)
    pad = _pad(shell)
    outer.setContentsMargins(pad, pad, pad, pad)
    outer.setSpacing(K.LAYOUT["gap"])
    outer.addLayout(_head(shell, vm, ui))
    if vm["notice"]:
        ui.notice = NoticeBar(vm["notice"]["level"], vm["notice"]["text"])
        outer.addWidget(ui.notice)
    outer.addWidget(_context_card(shell, normal, ui))
    outer.addWidget(_options_panel(shell, normal["options"], ui))
    left = QVBoxLayout()
    left.setSpacing(K.LAYOUT["gap"])
    left.addWidget(_title_card(shell, normal["title_box"], ui))
    left.addWidget(_body_card(shell, normal["editor"], ui), 1)
    right = _right(shell, normal["side"], ui)
    if ui.side:
        columns = QHBoxLayout()
        columns.setSpacing(K.LAYOUT["gap"])
        columns.addLayout(left, 68)
        columns.addLayout(right, 32)
        outer.addLayout(columns)
    else:
        outer.addLayout(left)
        outer.addLayout(right)
    outer.addStretch(1)
    scroll.setWidget(content)
    root_layout.addWidget(scroll, 1)
    root_layout.addWidget(_action_bar(shell, normal["actions"], ui))
    ui.stops = _stops(ui)
    for first, second in zip(ui.stops, ui.stops[1:]):
        QWidget.setTabOrder(first, second)
    root.drf_ui = ui
    return root


def _stops(ui):
    """Tab 정거장의 읽는 순서 — 뒤로 → 만드는 방법 → (펼쳤다면 그 안) → 제목 → 제목 후보 → 본문 → 오른쪽 칸(`검사하기` 다음에 글 모양 점검의 `무시` 단추들이 이어진다) → 아래 행동 줄."""
    chain = [ui.back, ui.saved_list, ui.options_toggle]
    chain += [ui.blog_chips.get(key) for key in ("naver_a", "naver_b")] + list(ui.type_chips.values()) + list(ui.fields.values()) + [ui.apply]
    chain += [ui.title, *ui.picks, ui.editor, ui.inspect_button, *(ui.garbage.stops() if ui.garbage is not None else []), ui.copy.get("keywords"), ui.copy.get("tags"), ui.copy.get("summary"), ui.image_button]
    chain += [ui.accordions[key].toggle for key in ("specific", "common")]
    chain += [ui.actions[key] for key in ("save", "title", "body", "all", "open") if key in ui.actions]
    return [widget for widget in chain if widget is not None]


def drafts_screen(shell, vm):
    """초안 작성 — 읽는 중·오류·거절·후보 없음은 홈·설정·주제 후보와 같은 틀의 상태 카드, 초안이 있으면 두 칸 화면과 아래 고정 행동 줄. 열 수 있는 모든 상태에서 `← 주제 후보` 로 돌아갈 수 있다."""
    if vm["state"] == "normal" and vm["normal"] is not None:
        return _normal_page(shell, vm)
    return _state_page(shell, vm)


# ---- 그 자리에서 고치기(화면 전체를 다시 그리지 않는다) ------------------------------------------------------------------------------------------
def _ui(page):
    return getattr(page, "drf_ui", None)


def refresh_editor_status(page, status):
    """글을 칠 때 — 글자 수와 고친 정도 줄만 바꾼다."""
    ui = _ui(page)
    if ui is not None and ui.count is not None:
        ui.count.set_text(status["count_text"])
        ui.edit.set_text(status["edit_text"])
        if ui.save_status is not None and "save_text" in status:
            ui.save_status.set_text(status["save_text"])
            ui.save_status.set_tone(status["save_tone"])
            ui.save_status.setAccessibleName(status["save_a11y"])


def refresh_save(page, vm):
    """저장을 시작했거나 끝났을 때 — 저장 상태 줄과 `저장` 단추(켜짐·꺼짐·설명)만 그 자리에서 바꾼다(편집기를 다시 그리지 않는다 — 커서·한글 조합이 사라지지 않게)."""
    ui = _ui(page)
    if ui is None or vm is None:
        return
    if ui.save_status is not None:
        ui.save_status.set_text(vm["text"])
        ui.save_status.set_tone(vm["tone"])
        ui.save_status.setAccessibleName(vm["a11y"])
    if ui.action_bar is not None:
        ui.action_bar.set_enabled("save", vm["button"]["enabled"], vm["button"]["tip"])


def refresh_picks(page, picks):
    """제목을 고치거나 후보를 골랐을 때 — 제목 후보 줄의 선택 표시만 바꾼다."""
    ui = _ui(page)
    if ui is not None:
        for row, vm in zip(ui.picks, picks):
            row.set_selected(vm["selected"])


def show_title(page, text):
    """제목 후보를 골랐을 때 제목 칸의 글을 바꾼다(`textEdited` 가 나가지 않는다 — 코드로 넣은 글이라)."""
    ui = _ui(page)
    if ui is not None and ui.title is not None and ui.title.text() != text:
        ui.title.setText(text)


def refresh_inspection(page, vm):
    ui = _ui(page)
    if ui is not None and ui.inspect is not None:
        ui.inspect.set_state(vm)


def refresh_garbage(page, vm):
    """글 모양 점검 카드를 그 자리에서 바꾼다 — 상태 줄·`본문이 변경됨`·항목·`무시` 단추와, 검사 중에는 공용 `검사하기` 단추의 글(`검사 중…`)과 꺼짐. 항목이 그대로면 아무것도 다시 만들지 않는다(글을 칠 때마다 불린다).
    단추가 새로 만들어졌으면 Tab 순서를 다시 잇는다. 꺼 둔 단추가 포커스를 쥐고 있었다면 검사가 끝났을 때 돌려준다(키보드 사용자가 자리를 잃지 않게)."""
    ui = _ui(page)
    if ui is None or ui.garbage is None:
        return
    button = ui.inspect_button
    if not vm["button"]["enabled"] and button.hasFocus():
        ui.garbage_focus = True
    button.setText(vm["button"]["text"])
    button.setAccessibleName(vm["button"]["a11y"])
    button.setEnabled(vm["button"]["enabled"])
    if vm["button"]["enabled"] and ui.garbage_focus:
        ui.garbage_focus = False
        button.setFocus(Qt.OtherFocusReason)
    if ui.garbage.set_state(vm):
        ui.stops = _stops(ui)
        for first, second in zip(ui.stops, ui.stops[1:]):
            QWidget.setTabOrder(first, second)


def garbage_button_index(page, key):
    """항목 열쇠의 `무시` 단추가 몇 번째인가(없으면 -1) — 누른 단추가 사라진 뒤 포커스를 이웃에게 주려고 쓴다."""
    ui = _ui(page)
    return ui.garbage.keys.index(key) if ui is not None and ui.garbage is not None and key in ui.garbage.keys else -1


def focus_garbage(page, index):
    """무시한 뒤 포커스를 이웃 `무시` 단추로(없으면 `검사하기` 로) 옮긴다 — 눌렀던 단추는 사라졌다."""
    ui = _ui(page)
    if ui is None or ui.garbage is None:
        return
    buttons = ui.garbage.buttons
    target = buttons[min(max(index, 0), len(buttons) - 1)] if buttons else ui.inspect_button
    target.setFocus(Qt.OtherFocusReason)


def refresh_options(page, options):
    """만드는 방법 칸 — 펼침·접힘·고른 블로그/글 유형 표시·반영하지 않은 글 안내를 그 자리에서 바꾼다."""
    ui = _ui(page)
    if ui is None or ui.options_panel is None:
        return
    ui.options_panel.setVisible(bool(options["open"]))
    ui.options_toggle.setText(options["toggle"])
    ui.options_toggle.setAccessibleName(options["toggle"])
    for item in options["blogs"]:
        chip = ui.blog_chips.get(item["key"])
        if chip is not None:
            chip.setChecked(item["active"])
    for item in options["types"]:
        chip = ui.type_chips.get(item["key"])
        if chip is not None:
            chip.setChecked(item["active"])
    ui.pending_note.setVisible(bool(options["pending"]))
    ui.apply.setEnabled(options["apply"]["enabled"])


def refresh_image(page, vm):
    ui = _ui(page)
    if ui is not None and ui.image_state is not None:
        ui.image_state.set_text(vm["state_text"])
        ui.image_button.setText(vm["button"])
        ui.image_button.setAccessibleName(vm["button_a11y"])


def show_copy(page, key, copied_text, copied):
    """복사 단추의 `✓ … 복사됨` 모양을 켜고 끈다(끄면 원래 글로 돌아간다) — 아래 줄이든 오른쪽 칸이든 그 열쇠의 단추를 바꾼다."""
    ui = _ui(page)
    button = ui.copy.get(key) if ui is not None else None
    if button is not None:
        base = button.property("base_text") or button.text()
        set_copy_look(button, copied_text if copied else base, copied, base)
