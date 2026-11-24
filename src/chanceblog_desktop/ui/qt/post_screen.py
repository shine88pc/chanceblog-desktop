"""글 검토 화면(글 흐름 1a, 결정 D-620 이후) — 뷰모델(`ui/core/posts_view.py` 의 `PostsController.view` 가 만든 딕셔너리)을 공통 부품(`components.py`·`board.py`·`post_parts.py`)으로 조립하기만 한다.
화면은 두 모습이다: **목록**(머리 — 제목·설명·`글 가져오기`(주요 단추 하나)·`다시 읽기` → 안내 띠·알림 줄 → 글 줄 카드, 읽는 중·오류·빈 화면은 홈·설정과 같은 틀의 상태 카드)과
**상세**(`목록으로` → 글 이름·정보 → 미리보기 카드 → 내보내기 전 검토 카드 — 플랫폼 칩·단추(주요 단추는 하나)·검토 결과 세 층).
화면은 읽기·고르기까지만 하고 **파일에 쓰는 일은 하지 않는다** — 단추를 누르면 셸(`shell.post_*`)이 컨트롤러를 거쳐 서비스를 부른다(이 파일에는 쓰기 호출이 없다 — 시험이 소스를 훑는다).
가로 스크롤은 없고 글은 모두 줄바꿈 평문이다. 접근 이름·포커스 열쇠(`post:*`)는 다시 그린 뒤 포커스를 돌려주는 데 쓰인다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .blog_parts import NoticeBar
from .post_parts import post_list_card, preview_card, review_card
from .screens import page_head

SKELETON_ROWS = 3


class PostsUi:
    """한 번 그린 화면의 부품들 — 시험과 포커스 복원이 단추·카드를 찾으려고 들고 있는다."""

    def __init__(self):
        self.import_button = self.reload_button = self.back_button = None
        self.list_card = self.preview = self.review = None


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


def _list_mode(shell, vm, outer, ui):
    state = vm["state"]
    if state == "loading":
        outer.addWidget(_loading_card(vm["loading"]))
    elif state == "error":
        outer.addWidget(UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["user"] or vm["error"]["desc"], vm["error"]["button"], shell.reload_posts, _diagnostics(vm["error"]["diag"])))
    elif state == "empty":
        empty = vm["list"]["empty"]
        card = UI.StateCard("inbox", "blue", empty["title"], empty["desc"], empty["button"], shell.post_import)
        if card.action is not None:
            card.action.setAccessibleName(vm["import"]["a11y"])
            card.action.setEnabled(vm["import"]["enabled"])
            card.action.setProperty("focus_key", "post:import-empty")
        outer.addWidget(card)
    else:
        ui.list_card = post_list_card(vm["list"], shell.post_open, shell.post_more)
        outer.addWidget(ui.list_card)


def _detail_mode(shell, vm, outer, ui):
    detail = vm["detail"]
    ui.back_button = UI.Button("ghost", detail["back"]["text"], accessible=detail["back"]["a11y"], focus_key="post:back")
    ui.back_button.clicked.connect(lambda _=False: shell.post_close())
    outer.addWidget(ui.back_button, 0, Qt.AlignLeft)
    if detail["state"] == "loading":
        outer.addWidget(_loading_card(detail["loading"]))
        return
    if detail["state"] == "error":
        outer.addWidget(UI.StateCard("alert", "red", detail["error"]["title"], detail["error"]["desc"], detail["error"]["button"], shell.post_reload_detail, _diagnostics(detail["error"]["diag"])))
        return
    title = UI.label(detail["title"], "h1", wrap=True)
    outer.addWidget(title)
    outer.addWidget(UI.label(detail["meta"], "caption", wrap=True))
    ui.preview = preview_card(detail["preview"])
    outer.addWidget(ui.preview)
    ui.review = review_card(shell, detail["review"])
    outer.addWidget(ui.review)


def posts_screen(shell, vm):
    """글 검토 — 목록 또는 상세. 주요 단추는 목록에서는 `글 가져오기`(빈 화면에서는 상태 카드의 같은 단추가 주요이고 머리의 것은 보조), 상세에서는 다음에 할 일 하나(검토 시작·승인하기)다."""
    page = QWidget()
    outer = QVBoxLayout(page)
    margin = K.LAYOUT["page_margin"]
    outer.setContentsMargins(margin, margin, margin, margin)
    outer.setSpacing(K.LAYOUT["gap"])
    ui = PostsUi()
    page.posts_ui = ui
    rights = [UI.SampleBadge(lambda: shell.show_sample_info("posts"), vm["sample_tip"])] if vm["sample"] else []
    listing = vm["mode"] == "list"
    if listing:
        empty = vm["state"] == "empty"
        ui.import_button = UI.Button("secondary" if empty else "primary", vm["import"]["text"], "plus", accessible=vm["import"]["a11y"], focus_key="post:import")
        ui.import_button.setEnabled(vm["import"]["enabled"])
        ui.import_button.clicked.connect(lambda _=False: shell.post_import())
        ui.reload_button = UI.IconButton("refresh", vm["reload"]["a11y"], focus_key="post:reload")
        ui.reload_button.setEnabled(vm["reload"]["enabled"])
        ui.reload_button.clicked.connect(lambda _=False: shell.reload_posts())
        rights += [ui.import_button, ui.reload_button]
        outer.addLayout(page_head(vm["title"], vm["sub"], rights))
        if vm["banner"]:
            outer.addWidget(UI.Banner(*vm["banner"]))
    elif rights:
        outer.addLayout(page_head(vm["title"], vm["sub"], rights))
    if vm["notice"]:
        outer.addWidget(NoticeBar(vm["notice"]["level"], vm["notice"]["text"]))
    if listing:
        _list_mode(shell, vm, outer, ui)
    else:
        _detail_mode(shell, vm, outer, ui)
    outer.addStretch(1)
    return page
