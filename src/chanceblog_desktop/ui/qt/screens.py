"""Qt 화면(View) — 뷰모델(`ui/core/app_state.py` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 조립하기만 한다.
목록을 거르거나 문구를 만들거나 어떤 상태인지 정하는 일은 하지 않고, Qt 기본 위젯(QPushButton·QLabel·QLineEdit …)을 직접 만들지도 않는다(시험이 지킨다). 눌림은 `shell`(AppShell)의 메서드로 넘긴다.
폭이 바뀌면 배치를 다시 고른다 — 홈의 KPI 카드 4열→2열→1열·구역 두 칸 나란히→위아래(`part_rules.home_kpi_columns`·`home_section_columns`), 설정 화면의 용도 카드 2열→1열 — 가로 스크롤은 없다.
화면은 홈(`home_screen` — KPI 넷·Naver A·B 추천·작성 중 초안·최근 발행·연결 상태 한 줄, 읽기만: UI-C1d)·블로그 관리(`blog_screen.blogs_screen` — 슬롯 카드·폼, **이 앱에서 처음으로 저장·복제·삭제를 눌렀을 때만 파일에 쓴다**)·설정(`settings_screen` — 접이식 다섯 묶음(용도 묶음 넷 + '정보')과 용도 카드, 읽기만) 셋이고(UI-C1a 에서 '아직 만들고 있어요' 자리표시 화면을 없앴다 — 완성된 화면만 연다), 어느 메뉴가 어느 화면인지는 맨 아래 `SCREEN_BUILDERS` 표(메뉴 → 화면 만드는 함수) 한 곳이 정한다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core import part_rules
from ..core import tokens as K
from ..core.text import T
from . import board
from . import components as UI
from .backup_parts import backup_section
from .blog_parts import NoticeBar
from .gauges import UsageBar
from .key_parts import key_section
from .style_dialog import style_entry_card


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
        return part_rules.grid_columns(width, self._options, self._min, self._gap)             # 규칙은 순수 함수 한 곳(시험이 CI 에서도 지킨다)

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


def page_head(title, sub, rights=(), role="display", note=""):
    """화면 머리 — 제목(역할 `role`: 설정은 `display` 28px, 홈은 `h1` 24px)·설명·(있으면) 작은 글 한 줄(`note` — 마지막 조회) + 오른쪽 위젯들."""
    row = QHBoxLayout()
    left = QVBoxLayout()
    left.setSpacing(2)
    left.addWidget(UI.label(title, role, wrap=True))
    left.addWidget(UI.label(sub, "sub", wrap=True))
    if note:
        left.addWidget(UI.label(note, "caption"))
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


# ---- 홈 ---------------------------------------------------------------------------------------------------------------------
HOME_SKELETON_ROWS = 4
NOTE_LOOK = {"empty": ("inbox", "blue"), "off": ("pause_circle", "orange"), "error": ("alert", "red"), "unavailable": ("inbox", "slate"), "before_connect": ("inbox", "slate"), "loading": ("inbox", "slate")}       # 구역 안내의 (아이콘, 계열)


def home_screen(shell, vm):
    """홈(UI-C1d, D-201) — 제목·설명 / KPI 넷 / (안내 띠) / Naver A·B 추천 / 작성 중 초안·최근 발행 / 연결 상태 한 줄. 눌러서 가는 곳이 없고(미완성 화면으로 가는 길 0) 쓰기 단추도 없다 — 읽기만 한다.
    읽는 중에는 구역 대신 자리 표시 하나, 홈 전체를 못 읽었으면 구역 대신 오류 카드 하나(다시 시도). 구역 하나를 못 읽은 것은 그 구역만 안내하고 홈은 그대로다. 추천 줄을 누르면 기존 상세 서랍이 열린다."""
    page = QWidget()
    outer = QVBoxLayout(page)
    margin = K.LAYOUT["page_margin"]
    outer.setContentsMargins(margin, margin, margin, margin)
    outer.setSpacing(K.LAYOUT["gap"])
    data = vm["board"]
    rights = [UI.SampleBadge(shell.show_sample_info)] if vm["sample"] else []              # 날짜는 상단 앱 바로 옮겼다(UI-C1a, D-171)
    refresh = UI.IconButton("refresh", vm["refresh"], focus_key="refresh")
    refresh.setEnabled(vm["state"] != "loading")
    refresh.clicked.connect(shell.reload)
    shell.refresh_button = refresh
    rights.append(refresh)
    outer.addLayout(page_head(vm["title"], vm["sub"], rights, role="h1", note=vm["fetched"]))
    outer.addWidget(FlowGrid([board.KpiCard(item) for item in data["kpi"]], part_rules.HOME_KPI_OPTIONS, K.LAYOUT["kpi_min_col"], part_rules.HOME_KPI_GAP))      # KPI 는 눌러서 가는 곳이 없다
    if vm["banner"]:
        outer.addWidget(UI.Banner(*vm["banner"]))
    if vm["state"] == "loading":
        outer.addWidget(_loading(shell, vm))
    elif vm["state"] == "error":
        outer.addWidget(_error(shell, vm))
    else:
        outer.addWidget(FlowGrid([_recommend(shell, section) for section in data["recommend"]], part_rules.HOME_SECTION_OPTIONS, K.LAYOUT["section_min_col"], K.LAYOUT["gap"]))
        outer.addWidget(FlowGrid([_posts(data["drafts"], board.draft_row, shell), _posts(data["recent"], board.recent_row)], part_rules.HOME_SECTION_OPTIONS, K.LAYOUT["posts_min_col"], K.LAYOUT["gap"]))
        outer.addWidget(board.connection_strip(data["connection"]))
    outer.addStretch(1)
    return page


def _loading(shell, vm):
    section, inner = UI.Card((24, 20, 24, 20))
    inner.addWidget(UI.Skeleton(HOME_SKELETON_ROWS))
    note = UI.label(vm["loading"]["text"], "sub")
    note.setAlignment(Qt.AlignCenter)
    inner.addWidget(note)
    cancel = UI.Button("ghost", vm["loading"]["cancel"], "x", focus_key="cancel-load")
    cancel.clicked.connect(shell.cancel_load)
    shell.cancel_button = cancel
    inner.addWidget(cancel, 0, Qt.AlignHCenter)
    return section


def _diagnostics(text, left=False):
    """접어 둔 진단 정보(오류 코드·시각뿐) + 안내 한 줄 — 기본 화면에는 코드가 없다. 구역 안내 안에서는 단추를 왼쪽에 붙이고(`left`), 홈 전체 오류 카드에서는 가운데에 둔다."""
    holder = QWidget()
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(UI.Disclosure(T["diag_show"], T["diag_hide"], text, left=left))
    box.addWidget(UI.label(T["diag_note"], "caption", wrap=True))
    return holder


def _error(shell, vm):
    return UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["user"] or vm["error"]["desc"], vm["error"]["button"], shell.reload, _diagnostics(vm["error"]["diag"]))


def _note(state, section):
    """구역 하나의 안내 — 빈 상태·꺼짐·못 읽음·읽기 전·연결 전. 문장은 모두 뷰모델이 준다(여기서는 상태에 맞는 아이콘만 고른다). 쓰기 단추는 없다."""
    icon, tone = NOTE_LOOK[state]
    if state == "error":
        return board.section_note(icon, tone, section["error"]["title"], section["error"]["desc"], _diagnostics(section["error"]["diag"], left=True))
    if state == "off":
        return board.section_note(icon, tone, section["off"])
    return board.section_note(icon, tone, section["empty"]["title"], section["empty"]["desc"])


def _recommend(shell, section):
    """Naver A·B 추천 한 구역 — 머리(채널 이름 + 후보 수 + 꺼짐 표시) 아래에 추천 줄(최대 5) 또는 이 구역만의 안내. 줄을 누르면 기존 상세 서랍이 열린다."""
    state = section["state"]
    badges = [UI.Badge("muted", section["enabled_text"])] if section["enabled"] is False else []                  # 꺼진 채널은 색이 아니라 글자('꺼짐')로 말한다
    count = section["count_text"] if state in ("normal", "empty") else ""
    frame, inner = board.section_card(section["title"], count, badges, accessible=T["board_section_a11y"].format(title=section["title"], count=count) if count else section["title"])
    if state == "normal":
        for row in section["rows"]:
            item = board.BoardRow(row, section["name"])
            item.opened.connect(shell.open_drawer)
            frame.rows_layout.addWidget(item)
        if section["note"]:
            inner.addWidget(UI.label(section["note"], "caption", wrap=True))
    else:
        inner.addWidget(_note(state, section))
    board.finish_section(frame, inner)
    return frame


def _posts(section, build_row, shell=None):
    """작성 중 초안·최근 발행 한 구역 — 글 줄(최대 5, 눌리지 않는다) 또는 이 구역만의 안내(빈 상태·읽지 못함 — 홈은 그대로). 작성 중 초안은 머리에 전체 개수(`count_text` — 저장한 초안 수와 같다)가 있고
    구역 맨 아래에 작은 `저장한 초안 보기`(`link`)가 있어 초안 작성 화면의 저장한 초안 목록으로 간다(D-363)."""
    count = section.get("count_text", "")
    frame, inner = board.section_card(section["title"], count, accessible=T["board_section_a11y"].format(title=section["title"], count=count) if count else section["title"])
    if section["state"] == "normal":
        for row in section["rows"]:
            frame.rows_layout.addWidget(build_row(row))
        if section["note"]:
            inner.addWidget(UI.label(section["note"], "caption", wrap=True))
    else:
        inner.addWidget(_note(section["state"], section))
    link = section.get("link")
    if link and shell is not None:
        button = UI.Button("ghost", link["text"], size="sm", accessible=link["a11y"], focus_key="home-drafts-link")
        button.clicked.connect(lambda _=False: shell.home_saved_drafts())
        inner.addWidget(button, 0, Qt.AlignLeft)
    board.finish_section(frame, inner)
    return frame


# ---- 설정(연결 관리) ----------------------------------------------------------------------------------------------------------------
def badge_line(caption, badge):
    """'준비' · '연결' 배지 한 줄 — 둘은 따로 보인다(준비 중이라는 것과 연결 상태는 다른 말이다)."""
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(UI.label(caption, "caption"))
    row.addWidget(UI.Badge(badge["tone"], badge["text"]))
    row.addStretch(1)
    return row


def purpose_card(card, shell=None):
    """용도 카드 — 이름·한 줄 설명·배지 두 줄·안내·한도에 닿았을 때 계속하는 방법·키 항목·사용량(기간마다 막대 한 줄 + 작은 글). 준비 중인 용도는 회색 톤이다.
    **쓰는 공급자일 때만**(`card["keys"]` 가 있을 때 — P4f) 키 구역이 단추(등록·삭제·시험·사용/예비·별칭·우선순위)를 가진다. 읽기만 하는 공급자에서는 누르는 것이 하나도 없다(이전과 같다)."""
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
    if card.get("keys") is not None and shell is not None:
        inner.addSpacing(4)
        inner.addWidget(key_section(card["keys"], shell, card["key"]))
    elif card["entries"]:
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
    refresh.setEnabled(vm["state"] != "loading" and not vm.get("busy"))              # 키를 쓰는 중에는 다시 읽지 않는다(쓰는 도중의 파일을 읽어 낡은 값이 남지 않게)
    refresh.clicked.connect(shell.reload_connections)
    inner.addLayout(section_title(vm["section"]["title"], vm["section"]["desc"], (refresh,)))
    if vm["fetched"]:
        inner.addWidget(UI.label(vm["fetched"], "caption"))
    for icon, message in vm["banners"]:
        inner.addWidget(UI.Banner(icon, message))
    if vm.get("notice"):                                                                    # 키 행동의 마지막 결과(저장했어요·실패 이유 …) — 아이콘과 글이 늘 함께 있다
        inner.addWidget(NoticeBar(vm["notice"]["level"], vm["notice"]["text"]))
    elif vm.get("busy"):
        inner.addWidget(NoticeBar("info", T["keys_busy_status"]))
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
            grid = FlowGrid([purpose_card(card, shell) for card in group["cards"]], (2, 1), 440)
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
    if vm.get("backup"):                                                                    # 백업·복원 카드(BACKUPUI) — 연결 정보와 따로 읽고 그리므로 연결 정보를 못 읽은 상태에서도 보인다
        outer.addWidget(backup_section(vm["backup"], shell))
    outer.addWidget(style_entry_card(shell))                                           # 맨 아래의 작은 카드 — 내 글 문체 참고값 보기(N-3a)를 여는 읽기 전용 대화상자의 진입점(연결 상태와 상관없이 늘 있다)
    outer.addStretch(1)
    return page


CONN_SKELETON_ROWS = 3


# ---- 메뉴 → 화면 만드는 함수 표 -------------------------------------------------------------------------------------------------------
def _home_builder(shell):
    return home_screen(shell, shell.state.home_view())


def _settings_builder(shell):
    return settings_screen(shell, shell.state.settings_view())


def _topics_builder(shell):
    from .candidate_screen import candidates_screen                             # 늦게 가져온다 — 주제 후보 화면 파일이 이 파일의 머리 도우미(`page_head`)를 쓴다(서로 가져오지 않게)
    return candidates_screen(shell, shell.state.candidates_view())


def _drafts_builder(shell):
    from .draft_screen import drafts_screen                                     # 늦게 가져온다 — 초안 작성 화면 파일이 이 파일의 머리 도우미(`page_head`)를 쓴다(서로 가져오지 않게)
    return drafts_screen(shell, shell.state.drafts_view())


def _seed_builder(shell):
    from .seed_screen import seeds_screen                                      # 늦게 가져온다 — Seed 관리 화면 파일이 이 파일의 격자·머리 도우미를 쓴다(서로 가져오지 않게)
    return seeds_screen(shell, shell.state.seeds_view())


def _blogs_builder(shell):
    from .blog_screen import blogs_screen                                       # 늦게 가져온다 — 블로그 관리 화면 파일이 이 파일의 격자·머리 도우미를 쓴다(서로 가져오지 않게)
    return blogs_screen(shell, shell.state.blogs_view())


# 실제 메뉴마다 한 줄(`app_state.NAV` 와 같은 열쇠 — 시험이 지킨다). **완성된 화면만** 둔다 — 아직 만들지 않은 화면은 이 표에도 메뉴에도 없고(자리표시 화면을 없앴다), 화면이 완성되면 메뉴 한 줄과 이 표 한 줄을 같이 더한다.
SCREEN_BUILDERS = {"home": _home_builder, "topics": _topics_builder, "drafts": _drafts_builder, "seed": _seed_builder, "blogs": _blogs_builder, "settings": _settings_builder}


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
