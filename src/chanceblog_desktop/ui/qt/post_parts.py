"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)의 Qt 부품 — 글 줄·미리보기 카드·검토 카드(플랫폼 칩·단추·결과 세 층)와 창 안 대화상자 둘(가져오기·Pages 검토 값).
부품은 뷰모델(`ui/core/posts_view.py` 의 `PostsController.view`·`import_view`·`pages_view` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 조립하기만 한다 — 규칙(승인 조건·확인창·낡은 결과·입력 보존)은 모두 core 에 있다.
**글은 모두 일반 글(평문)로 그린다**: 미리보기·사유·제목은 `UI.label`(글 전체를 `html.escape` 한 줄바꿈 글)과 평문 입력 칸뿐이고 서식 글 위젯(`QTextBrowser` 등)·`setHtml` 은 이 앱에 없다 — 글 속의 `<script>` 는 글자 그대로 보인다.
색·글꼴·크기·간격은 토큰(`K`·스타일시트)에서만 온다. 이 파일에는 파일을 만지는 호출·네트워크·하위 프로세스·표준 출력이 없다.
대화상자의 입력 칸 글은 **칸에만** 있고(컨트롤러는 '입력이 있나' 만 안다) 어느 길로든 대화가 닫히면 칸을 비우고 되돌리기 기록까지 지운다(`discard`). 눌리는 모든 것은 Tab·Enter·Space 로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import board
from . import components as UI
from .blog_parts import NoticeBar
from .key_parts import DialogScroll
from .style_dialog import PasteBox, _empty_layout

DIALOG_WIDTH = 760                                                                # 입력 칸과 설명이 들어갈 만큼 넓은 대화상자(창 논리 폭의 94% 를 넘지 않는다 — `Dialog.place`)
INDENT_STEP = 2                                                                   # 목록 글의 앞 공백 몇 칸이 한 단계 들여쓰기인가


class PostRow(UI.Pressable):
    """글 줄 — 제목·`판 N · 고친 때`·플랫폼별 상태 글. 전체가 누르는 칸이다(마우스·Tab·Enter·Space). 읽을 수 없는 글은 눌리지 않는 안내 줄이다."""
    def __init__(self, row, on_open):
        super().__init__(row["a11y"])
        self.setObjectName("row")
        self.post_id = row["id"]
        self.setProperty("focus_key", row["focus_key"])
        self.setMinimumHeight(K.SIZE["list_row_h"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(K.SPACE["3"], K.SPACE["2"], K.SPACE["3"], K.SPACE["2"])
        layout.setSpacing(K.SPACE["1"])
        self.title_label = UI.label(row["title"], "h3", wrap=True)
        layout.addWidget(self.title_label)
        if row["meta"]:
            layout.addWidget(UI.label(row["meta"], "caption", wrap=True))
        for line in row["status_lines"]:
            layout.addWidget(UI.label(line, "small", wrap=True))
        if row["open"] is None:
            self.setFocusPolicy(Qt.NoFocus)                                       # 읽을 수 없는 글은 열지 않는다 — 눌림도 포커스도 없다
            self.setCursor(Qt.ArrowCursor)
        else:
            self.setAccessibleDescription(row["open"]["a11y"])
            self.activated.connect(lambda: on_open(row["id"]))


def post_list_card(vm_list, on_open, on_more):
    """글 목록 카드 — 머리(이름 + 글 수)와 글 줄들, 맨 아래에 `더 보기`(글이 더 있을 때만)."""
    frame, inner = board.section_card(T["post_title"], vm_list["count"], accessible=vm_list["a11y"])
    for row in vm_list["rows"]:
        frame.rows_layout.addWidget(PostRow(row, on_open))
    if vm_list["more"] is not None:
        more = UI.Button("ghost", vm_list["more"]["text"], size="sm", accessible=vm_list["more"]["a11y"], focus_key="post:more")
        more.clicked.connect(lambda _=False: on_more())
        inner.addWidget(more, 0, Qt.AlignLeft)
        frame.more_button = more
    board.finish_section(frame, inner)
    return frame


def _block(block):
    """미리보기 블록 하나 → 위젯(일반 글). 소제목은 작은 제목 글, 목록은 줄마다 한 줄(앞 공백만큼 들여쓰기), 인용은 흐린 카드 안의 글."""
    kind, text = block["kind"], block["text"]
    if kind == "heading":
        widget = UI.label(text, "h3", wrap=True)
    elif kind == "list":
        widget = QWidget()
        column = QVBoxLayout(widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(K.SPACE["1"])
        for line in text.split("\n"):
            level = (len(line) - len(line.lstrip(" "))) // INDENT_STEP
            item = UI.label(line.strip(), "body", wrap=True)
            item.setContentsMargins(K.SPACE["4"] * level, 0, 0, 0)
            column.addWidget(item)
    elif kind == "quote":
        widget, inner = UI.Card((K.SPACE["3"], K.SPACE["2"], K.SPACE["3"], K.SPACE["2"]), kind="plain")
        inner.addWidget(UI.label(text, "sub", wrap=True))
    else:
        widget = UI.label(text, "body", wrap=True)
    widget.setProperty("block", kind)
    return widget


def preview_card(vm):
    """미리보기 카드 — 제목·'글자만 그려 보여 줘요' 안내·정보 한 줄·블록들·앞부분만 보인다는 안내."""
    frame, inner = UI.Card((K.SPACE["6"], K.SPACE["5"], K.SPACE["6"], K.SPACE["5"]))
    inner.setSpacing(K.SPACE["3"])
    frame.setAccessibleName(vm["a11y"])
    frame.setProperty("post_part", "preview")
    inner.addWidget(UI.label(vm["title"], "h2"))
    inner.addWidget(UI.label(vm["note"], "small", wrap=True))
    if vm["info"]:
        inner.addWidget(UI.label(vm["info"], "caption", wrap=True))
    host = QWidget()
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(K.SPACE["3"])
    for block in vm["blocks"]:
        column.addWidget(_block(block))
    if vm["empty"]:
        column.addWidget(UI.label(vm["empty"], "sub", wrap=True))
    inner.addWidget(host)
    frame.blocks_host = host
    if vm["cut"]:
        inner.addWidget(UI.label(vm["cut"], "caption", wrap=True))
    return frame


def result_section(section):
    """검토 결과 한 층 — 이름 + 글자 배지(통과·막힘·확인 필요·참고) + 사유 줄 + 접어 둔 자세히(서비스가 쓴 원래 사유와 코드)."""
    frame, inner = UI.Card((K.SPACE["4"], K.SPACE["3"], K.SPACE["4"], K.SPACE["3"]), kind="plain")
    inner.setSpacing(K.SPACE["2"])
    frame.setAccessibleName(section["a11y"])
    frame.setProperty("post_part", "section:" + section["key"])
    head = QHBoxLayout()
    head.setSpacing(K.SPACE["2"])
    head.addWidget(UI.label(section["title"], "h3"), 1)
    badge = UI.Badge(section["badge"]["tone"], section["badge"]["text"])
    head.addWidget(badge, 0, Qt.AlignVCenter)
    inner.addLayout(head)
    frame.badge = badge
    for line in section["lines"]:
        inner.addWidget(UI.label(line, "body", wrap=True))
    if section["details"]:
        inner.addWidget(UI.Disclosure(T["post_detail_show"], T["post_detail_hide"], "\n".join(section["details"]), left=True))
        inner.addWidget(UI.label(T["post_detail_note"], "caption", wrap=True))
    return frame


def review_card(shell, vm):
    """검토 카드 — 플랫폼 칩 셋 → 고른 플랫폼의 상태 줄 → 단추(주요 단추는 하나) → 검토 결과(세 층). 눌림은 셸(`shell.post_*`)로 넘긴다."""
    frame, inner = UI.Card((K.SPACE["6"], K.SPACE["5"], K.SPACE["6"], K.SPACE["5"]))
    inner.setSpacing(K.SPACE["3"])
    frame.setProperty("post_part", "review")
    inner.addWidget(UI.label(vm["title"], "h2"))
    inner.addWidget(UI.label(vm["sub"], "small", wrap=True))
    chips = []
    frame.chips = {}
    for item in vm["chips"]:
        chip = UI.FilterChip(item["text"], None, item["selected"], focus_key="post:platform:" + item["key"])
        chip.setAccessibleName(item["a11y"])
        chip.clicked.connect(lambda _=False, key=item["key"]: shell.post_platform(key))
        frame.chips[item["key"]] = chip
        chips.append(chip)
    strip = UI.chip_row(chips)
    strip.setAccessibleName(vm["pick_a11y"])
    inner.addWidget(strip)
    panel = vm["panel"]
    inner.addWidget(UI.label(panel["status_line"], "body"))
    if panel["profile_missing"]:
        inner.addWidget(NoticeBar("warning", panel["profile_missing"]))
    if panel["after"]:
        inner.addWidget(UI.label(panel["after"], "small", wrap=True))
    bar = QHBoxLayout()
    bar.setSpacing(K.SPACE["2"])
    frame.buttons = {}
    for name, handler, focus in (("review", lambda: shell.post_review(panel["platform"]), "post:review"), ("approve", shell.post_approve, "post:approve"), ("revoke", shell.post_revoke, "post:revoke")):
        action = panel[name]
        if not action["visible"]:
            continue
        button = UI.Button("primary" if action.get("primary") else "secondary", action["text"], accessible=action["a11y"], focus_key=focus)
        button.setEnabled(bool(action["enabled"]))
        button.clicked.connect(lambda _=False, call=handler: call())
        if name == "approve" and action["why"]:
            button.setAccessibleDescription(action["why"])
            UI.with_tooltip(button, action["why"])
        frame.buttons[name] = button
        bar.addWidget(button)
    bar.addStretch(1)
    inner.addLayout(bar)
    for text in (panel["review"]["note"] if panel["review"]["visible"] else "", panel["approve"]["why"] if panel["approve"]["visible"] else ""):
        if text:
            inner.addWidget(UI.label(text, "caption", wrap=True))
    result = panel["result"]
    if result is not None:
        inner.addWidget(_result(result))
    return frame


def _result(result):
    box = QWidget()
    box.setAccessibleName(result["a11y"])
    column = QVBoxLayout(box)
    column.setContentsMargins(0, K.SPACE["2"], 0, 0)
    column.setSpacing(K.SPACE["3"])
    column.addWidget(UI.label(result["title"], "h3"))
    column.addWidget(UI.label(result["text"], "small" if result["state"] == "ready" else "sub", wrap=True))
    for section in result["sections"]:
        column.addWidget(result_section(section))
    box.setProperty("result_state", result["state"])
    return box


# ---- 창 안 대화상자 ------------------------------------------------------------------------------------------------------------------------
class ChoiceStrip(QWidget):
    """둘 중 하나 고르기 — 글자가 있는 칩 둘(색만으로 고른 것을 알리지 않는다: 고른 칩은 눌린 모양이고 접근 이름이 같다). 누르면 `picked(열쇠)`."""

    def __init__(self, options, selected, on_pick, focus_prefix, accessible):
        super().__init__()
        self.setAccessibleName(accessible)
        flow = QHBoxLayout(self)
        flow.setContentsMargins(0, 0, 0, 0)
        flow.setSpacing(K.SPACE["2"])
        self.chips = {}
        for option in options:
            chip = UI.FilterChip(option["text"], None, option["key"] == selected, focus_key=f"{focus_prefix}:{option['key']}")
            chip.clicked.connect(lambda _=False, key=option["key"]: on_pick(key))
            self.chips[option["key"]] = chip
            flow.addWidget(chip)
        flow.addStretch(1)

    def select(self, key):
        for name, chip in self.chips.items():
            chip.setChecked(name == key)


class _Dialog(QWidget):
    """두 대화상자가 함께 쓰는 틀 — 몸(제목·안내·칸들 — 낮은 창에서는 스크롤)과 스크롤 밖 아래의 상태 줄·단추 줄. 모습은 컨트롤러가 정하고 여기서는 그린다."""

    def __init__(self, shell, title):
        super().__init__()
        self.shell = shell
        self.setAccessibleName(title)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(K.SPACE["3"])
        self.body = QWidget()
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(0, 0, K.SPACE["2"], 0)
        self.column.setSpacing(K.SPACE["3"])
        self.scroll = DialogScroll(self.body)
        self.scroll.setFocusPolicy(Qt.StrongFocus)                                # 키보드로 스크롤할 수 있게(방향키) — 이름이 있는 Tab 정거장
        self.scroll.setAccessibleName(title)
        self.outer.addWidget(self.scroll, 1)

    def status_label(self, tone):
        label = UI.label("", "small", wrap=True)
        label.set_tone(tone)
        label.setVisible(False)
        return label

    @staticmethod
    def show_text(label, text):
        label.set_text(text)
        label.setVisible(bool(text))

    def refit(self):
        """모습이 바뀌어 키가 달라지면 열려 있는 대화상자의 키를 다시 맞춘다."""
        host = self.parentWidget()
        dialog = getattr(self.shell, "dialog", None)
        if host is None or host is not dialog or not dialog.is_open:
            return
        for widget in (self.body, self.scroll, self):
            widget.updateGeometry()
        dialog.layout_.activate()
        dialog.place()

    def refit_later(self):
        try:
            self.refit()
        except RuntimeError:                                                      # 그 사이 대화상자가 닫혀 부품이 지워졌다
            pass


class ImportDialog(_Dialog):
    """`글 가져오기` — 종류(Markdown·HTML)·제목·본문(붙여 넣기)·파일에서 읽기·거절 이유·닫기 확인 줄. 칸의 글은 이 부품에만 있다."""

    def __init__(self, shell, controller):
        vm = controller.import_view(0, 0)
        super().__init__(shell, vm["title"])
        self.controller = controller
        self.column.addWidget(UI.label(vm["title"], "h2", wrap=True))
        self.column.addWidget(UI.label(vm["intro"], "body", wrap=True))
        self.column.addWidget(UI.label(vm["kind_label"], "small"))
        self.kinds = ChoiceStrip(vm["kinds"], vm["kind"], shell.post_import_kind, "post:kind", vm["kind_a11y"])
        self.column.addWidget(self.kinds)
        self.kind_note = UI.label("", "caption", wrap=True)
        self.column.addWidget(self.kind_note)
        self.column.addWidget(UI.label(vm["title_label"], "small"))
        self.title_input = UI.TextInput(T["post_im_title_a11y"])
        self.title_input.setProperty("focus_key", "post:title")
        self.title_input.textChanged.connect(lambda _text="": self._edited())
        self.column.addWidget(self.title_input)
        self.column.addWidget(UI.label(vm["title_hint"], "caption", wrap=True))
        self.column.addWidget(UI.label(vm["body_label"], "small"))
        self.body_input = PasteBox(T["post_im_body_a11y"])
        self.body_input.setProperty("focus_key", "post:body")
        self.body_input.textChanged.connect(self._edited)
        self.column.addWidget(self.body_input)
        self.column.addWidget(UI.label(vm["body_hint"], "caption", wrap=True))
        self.count = UI.label("", "caption")
        self.count.setAlignment(Qt.AlignRight)
        self.column.addWidget(self.count)
        self.column.addStretch(1)
        self.state_line = self.status_label("slate")
        self.message = self.status_label("red")
        self.note = self.status_label("blue")
        self.confirm_host = QWidget()
        self.confirm_layout = QVBoxLayout(self.confirm_host)
        self.confirm_layout.setContentsMargins(0, 0, 0, 0)
        self.confirm_layout.setSpacing(K.SPACE["2"])
        self.confirm_buttons = []
        status = QWidget()
        box = QVBoxLayout(status)
        box.setContentsMargins(0, 0, K.SPACE["2"], 0)
        box.setSpacing(K.SPACE["2"])
        for widget in (self.state_line, self.confirm_host, self.message, self.note):
            box.addWidget(widget)
        self.outer.addWidget(status)
        row = QHBoxLayout()
        row.setSpacing(K.SPACE["2"])
        self.pick_button = UI.Button("secondary", vm["pick"]["text"], "upload", accessible=vm["pick"]["a11y"], focus_key="post:pick")
        self.pick_button.clicked.connect(lambda _=False: shell.post_import_pick())
        self.cancel_button = UI.Button("secondary", vm["cancel"]["text"], accessible=vm["cancel"]["a11y"], focus_key="post:import-cancel")
        self.cancel_button.clicked.connect(lambda _=False: shell.post_import_cancel())
        self.start_button = UI.Button("primary", vm["start"]["text"], accessible=vm["start"]["a11y"], focus_key="post:import-start")
        self.start_button.clicked.connect(lambda _=False: shell.post_import_start())
        row.addWidget(self.pick_button)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        row.addWidget(self.start_button)
        self.outer.addLayout(row)
        self.refresh()

    # ---- 칸 ----
    def title_text(self):
        return self.title_input.text()

    def body_text(self):
        """본문 칸의 글 — 가져오기를 누르는 순간 한 번 읽어 값으로 넘긴다(이 부품이 따로 쥐지 않는다)."""
        return self.body_input.toPlainText()

    def body_has_text(self):
        """본문 칸에 글이 이미 있나(파일을 읽으면 그 글이 바뀐다 — 안내 줄이 되돌리는 법을 알린다)."""
        return bool(self.body_input.toPlainText().strip())

    def fill(self, title, body):
        """파일에서 읽은 글을 칸에 채운다(제목 칸이 비어 있을 때만 제목 제안을 넣는다) — 채우는 동안은 '바뀜' 신호를 끈다.
        본문은 **한 번의 편집으로 바꾼다**(전체 선택 뒤 끼워 넣기): 이미 쓴 글이 있었으면 Ctrl+Z 한 번으로 되돌릴 수 있다(되돌리기 기록을 지우지 않는다)."""
        for box in (self.title_input, self.body_input):
            box.blockSignals(True)
        if not self.title_input.text().strip() and title:
            self.title_input.setText(title)
        self.body_input.selectAll()
        self.body_input.insertPlainText(body)
        for box in (self.title_input, self.body_input):
            box.blockSignals(False)
        self._edited()

    def _edited(self):
        """글을 치면 글자 수·단추만 바꾼다(화면 전체·대화상자를 다시 그리지 않는다 — 한글 조합이 끊기지 않게)."""
        if self.controller is None:
            return
        self.controller.import_edited(bool(self.title_input.text().strip() or self.body_input.toPlainText().strip()))
        self._apply(self.controller.import_view(len(self.title_input.text().strip()), len(self.body_input.toPlainText().strip())))

    # ---- 그리기 ----
    def _apply(self, vm):
        self.count.set_text(vm["count"])
        self.count.setAccessibleName(vm["count_a11y"])
        self.kinds.select(vm["kind"])
        self.show_text(self.kind_note, vm["kind_note"])
        self.pick_button.setVisible(vm["pick"]["visible"])
        self.pick_button.setEnabled(vm["pick"]["enabled"])
        self.start_button.setEnabled(vm["start"]["enabled"])
        self.cancel_button.setEnabled(vm["cancel"]["enabled"])
        busy = bool(vm["working"])
        for box in (self.title_input, self.body_input):
            box.setReadOnly(busy)
        self.show_text(self.state_line, vm["working"] or vm["state"])
        self.show_text(self.message, vm["message"])
        self.show_text(self.note, vm["note"])
        _empty_layout(self.confirm_layout)
        self.confirm_buttons = []
        discard = vm["discard"]
        if discard["open"]:
            question = UI.label(discard["question"], "body", wrap=True)
            question.set_tone("red")
            question.setAccessibleName(discard["question"])
            self.confirm_layout.addWidget(question)
            line = QHBoxLayout()
            line.setSpacing(K.SPACE["2"])
            for info, handler, key, kind in ((discard["yes"], self.shell.post_import_discard_yes, "post:discard-yes", "secondary"), (discard["no"], self.shell.post_import_discard_no, "post:discard-no", "ghost")):
                button = UI.Button(kind, info["text"], accessible=info["a11y"], focus_key=key)
                button.clicked.connect(lambda _=False, call=handler: call())
                line.addWidget(button)
                self.confirm_buttons.append(button)
            line.addStretch(1)
            self.confirm_layout.addLayout(line)

    def refresh(self):
        """컨트롤러의 뷰모델에 맞게 단추·안내·확인 줄을 바꾼다 — 칸의 글은 건드리지 않는다."""
        if self.controller is None:
            return None
        vm = self.controller.import_view(len(self.title_input.text().strip()), len(self.body_input.toPlainText().strip()))
        self._apply(vm)
        self._tab_order()
        self.refit()
        QTimer.singleShot(0, self.refit_later)
        return vm

    def _tab_order(self):
        chain = [self.scroll, *self.kinds.chips.values(), self.title_input, self.body_input, *self.confirm_buttons, self.pick_button, self.cancel_button, self.start_button]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    def focus_start(self):
        self.title_input.setFocus(Qt.OtherFocusReason)

    def focus_confirm(self):
        """닫기 확인 줄이 떴을 때 — 안전한 쪽(`계속 쓰기`)에 포커스를 둔다."""
        target = self.confirm_buttons[-1] if self.confirm_buttons else self.cancel_button
        QTimer.singleShot(0, lambda widget=target: self._focus_later(widget))
        target.setFocus(Qt.OtherFocusReason)

    @staticmethod
    def _focus_later(widget):
        try:
            if widget.isEnabled() and widget.isVisible():
                widget.setFocus(Qt.OtherFocusReason)
        except RuntimeError:                                                      # 그 사이 대화상자가 닫혀 부품이 지워졌다
            pass

    def discard(self):
        """대화상자가 닫히거나 바뀔 때(어느 길로든) — 제목·본문 칸을 비운다(되돌리기 기록까지). 여러 번 불러도 같다."""
        try:
            self.title_input.blockSignals(True)
            self.body_input.blockSignals(True)
            UI.wipe_input(self.title_input)
            self.body_input.wipe()
            _empty_layout(self.confirm_layout)
        except RuntimeError:                                                      # 이미 지워진 부품
            pass
        self.confirm_buttons = []
        self.controller = None
        return True


class PagesDialog(_Dialog):
    """`GitHub Pages 검토 값` — 분야·언어·대표 이미지 주소·태그·한 줄 설명. 칸 옆에 문제 문장이 보이고 값은 거절돼도 그대로 남는다. 값은 이 앱을 닫으면 사라진다(파일에 쓰지 않는다)."""

    def __init__(self, shell, controller, raw):
        vm = controller.pages_view()
        super().__init__(shell, vm["title"])
        self.controller = controller
        self.column.addWidget(UI.label(vm["title"], "h2", wrap=True))
        self.column.addWidget(UI.label(vm["intro"], "body", wrap=True))
        self.inputs, self.problem_labels = {}, {}
        first = vm["fields"][:1]
        for field in first:
            self._field(field, raw)
        self.column.addWidget(UI.label(vm["lang"]["label"], "small"))
        self.lang_strip = ChoiceStrip(vm["lang"]["options"], raw.get("lang") or "ko", self._pick_lang, "post:lang", vm["lang"]["a11y"])
        self.lang = raw.get("lang") or "ko"
        self.column.addWidget(self.lang_strip)
        self.problem_labels["lang"] = self._problem()
        self.column.addWidget(self.problem_labels["lang"])
        for field in vm["fields"][1:]:
            self._field(field, raw)
        self.column.addStretch(1)
        self.working = self.status_label("slate")
        self.message = self.status_label("red")
        status = QWidget()
        box = QVBoxLayout(status)
        box.setContentsMargins(0, 0, K.SPACE["2"], 0)
        box.setSpacing(K.SPACE["2"])
        box.addWidget(self.working)
        box.addWidget(self.message)
        self.outer.addWidget(status)
        row = QHBoxLayout()
        row.setSpacing(K.SPACE["2"])
        row.addStretch(1)
        self.cancel_button = UI.Button("secondary", vm["cancel"]["text"], accessible=vm["cancel"]["a11y"], focus_key="post:pages-cancel")
        self.cancel_button.clicked.connect(lambda _=False: shell.post_pages_cancel())
        self.start_button = UI.Button("primary", vm["start"]["text"], accessible=vm["start"]["a11y"], focus_key="post:pages-start")
        self.start_button.clicked.connect(lambda _=False: shell.post_pages_start())
        row.addWidget(self.cancel_button)
        row.addWidget(self.start_button)
        self.outer.addLayout(row)
        self.refresh()

    def _problem(self):
        label = UI.label("", "small", wrap=True)
        label.set_tone("red")
        label.setVisible(False)
        return label

    def _field(self, field, raw):
        self.column.addWidget(UI.label(field["label"], "small"))
        box = UI.TextInput(field["a11y"])
        box.setProperty("focus_key", "post:pv:" + field["name"])
        box.setText(raw.get(field["name"]) or "")
        self.inputs[field["name"]] = box
        self.column.addWidget(box)
        self.column.addWidget(UI.label(field["hint"], "caption", wrap=True))
        self.problem_labels[field["name"]] = self._problem()
        self.column.addWidget(self.problem_labels[field["name"]])

    def _pick_lang(self, key):
        self.lang = key
        self.lang_strip.select(key)

    def values(self):
        """칸에 적힌 값(칸 글) — `검토 시작` 을 누르는 순간 한 번 읽어 컨트롤러에 넘긴다."""
        return {name: box.text() for name, box in self.inputs.items()} | {"lang": self.lang}

    def refresh(self):
        if self.controller is None:
            return None
        vm = self.controller.pages_view()
        for name, label in self.problem_labels.items():
            self.show_text(label, vm["problems"].get(name, ""))
        self.show_text(self.working, vm["working"])
        self.show_text(self.message, vm["message"])
        self.start_button.setEnabled(vm["start"]["enabled"])
        self.cancel_button.setEnabled(vm["cancel"]["enabled"])
        for box in self.inputs.values():
            box.setReadOnly(bool(vm["working"]))
        chain = [self.scroll, self.inputs["category"], *self.lang_strip.chips.values(), *(self.inputs[name] for name in ("image_url", "tags", "description")), self.cancel_button, self.start_button]      # 화면에 보이는 순서대로
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)
        self.refit()
        QTimer.singleShot(0, self.refit_later)
        return vm

    def focus_start(self):
        self.inputs["category"].setFocus(Qt.OtherFocusReason)

    def focus_problem(self):
        """문제 문장이 있는 첫 칸으로 포커스를 옮긴다."""
        for name in ("category", "lang", "image_url", "tags", "description"):
            if self.problem_labels[name].isVisible():
                target = self.lang_strip.chips[self.lang] if name == "lang" else self.inputs[name]
                target.setFocus(Qt.OtherFocusReason)
                return name
        return None

    def discard(self):
        try:
            for box in self.inputs.values():
                box.blockSignals(True)
                UI.wipe_input(box)
        except RuntimeError:
            pass
        self.controller = None
        return True
