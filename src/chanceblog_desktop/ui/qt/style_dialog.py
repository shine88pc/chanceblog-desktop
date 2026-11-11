"""'내 글 문체 참고값 보기'(N-3a)의 Qt 부품 — 설정 화면 맨 아래의 작은 진입 카드(`style_entry_card`)와 읽기 전용 대화상자의 안쪽(`StyleDialog`). 결정 D-330–D-339.
화면은 뷰모델(`ui/core/style_view.py` 의 `StyleStudy.view` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 조립하기만 한다. 색·글꼴·크기·간격은 토큰(`K`·스타일시트)에서만 오고 여기서 인라인으로 정하지 않는다.

**저장도 AI 도 네트워크도 없다.** 저장 단추·체크 칸·확인창이 없고(있는 단추는 `파일 고르기`·`빼기`·`계산하기`·`다른 글로 다시 하기`·`닫기` 뿐이다) 프로필·설정·보관함은 읽지도 쓰지도 않는다. 이 화면에서 글이 있는 곳은 **붙여 넣기 칸 하나뿐**이고
(`PasteBox`) 계산이 끝나면 칸을 비우며(되돌리기 기록까지) 어느 길로든 대화상자가 닫히면 칸·고른 글·결과 표를 모두 버린다(`Dialog.cleanups` 의 정리 훅). 결과 표에는 숫자와 고정 문장뿐이고 글의 문장은 없다.
모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다. 색만으로 상태를 알리지 않는다(안내는 글이 늘 함께 있고 거절 문장만 빨강 계열이다).
몸(안내·고르기·표)은 창이 낮을 때 스크롤되고(`DialogScroll`, 키보드로 스크롤할 수 있게 Tab 정거장이다) 단추 줄은 늘 아래에 보인다. 최소 창(900×560)에서도 가로 스크롤이나 잘림이 없다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .key_parts import DialogScroll

DIALOG_WIDTH = 760                                                                # 표가 들어갈 만큼 넓은 대화상자(창 논리 폭의 94% 를 넘지 않는다 — `Dialog.place`)
PASTE_MIN_HEIGHT = 110


def _empty_layout(layout):
    """배치 안의 부품과 안쪽 배치를 모두 치운다(숨기고 떼어 지운다) — 옛 줄의 단추가 새 줄 사이에 남아 눌리지 않게."""
    while layout.count():
        item = layout.takeAt(0)
        widget, inner = item.widget(), item.layout()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif inner is not None:
            _empty_layout(inner)
            inner.deleteLater()


def style_entry_card(shell):
    """설정 화면 맨 아래의 작은 카드 — 제목·한 줄 설명·`열기` 단추 하나. 눌러도 파일·설정·프로필에는 닿지 않고 읽기 전용 대화상자만 연다. 카드 틀에는 접근 이름을 달지 않는다(안의 단추가 이름을 가진다)."""
    frame, inner = UI.Card((18, 16, 18, 16), kind="true")
    inner.setSpacing(6)
    inner.addWidget(UI.label(T["style_entry_title"], "h3", wrap=True))
    inner.addWidget(UI.label(T["style_entry_desc"], "small", wrap=True))
    button = UI.Button("secondary", T["style_entry_open"], accessible=T["style_entry_open_a11y"], focus_key="style-open")
    button.clicked.connect(lambda _=False: shell.style_open())
    inner.addWidget(button, 0, Qt.AlignLeft)
    frame.setProperty("style_entry", True)
    frame.entry_button = button
    return frame


class PasteBox(QPlainTextEdit):
    """붙여 넣기 칸 — 평문뿐(서식·그림 붙이기 없음)이고 Tab 은 글자가 아니라 다음 칸으로 간다. 비울 때는 `wipe`(되돌리기·다시 하기 기록까지 지운다)."""

    def __init__(self, accessible):
        super().__init__()
        self.setProperty("editor", True)
        self.setProperty("focus_key", "style:paste")
        self.setAccessibleName(accessible)
        self.setMinimumHeight(PASTE_MIN_HEIGHT)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setUndoRedoEnabled(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def chars(self):
        return len(self.toPlainText())

    def wipe(self):
        """칸을 비운다 — 글과 되돌리기 기록을 모두 지운다. 비운 뒤 되돌리기가 가능하면 안 된다(→ 참)."""
        self.setPlainText("")
        self.document().clearUndoRedoStacks()
        return not (self.document().isUndoAvailable() or self.document().isRedoAvailable())

    def inputMethodEvent(self, event):
        """읽기 전용·꺼진 동안(숫자를 세는 중) 입력기가 확정한 글도 받지 않는다."""
        if self.isReadOnly() or not self.isEnabled():
            event.ignore()
            return
        super().inputMethodEvent(event)


class StyleDialog(QWidget):
    """대화상자의 안쪽 — 고르기 모습(안내·파일 고르기·고른 글·붙여 넣기 칸)과 결과 모습(숫자 표·센 개수·안내), 아래에 단추 줄. 모습은 컨트롤러(`StyleStudy`)가 정하고 여기서는 그린다."""

    def __init__(self, shell, study):
        super().__init__()
        self.shell, self.study = shell, study
        self._signature = None                                                                      # 결과 표를 마지막에 그린 뷰모델의 모양 — 같으면 다시 만들지 않는다
        self.cells, self.result_card, self.slot_buttons = {}, None, []
        self.setAccessibleName(T["style_title"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(K.SPACE["3"])
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, K.SPACE["2"], 0)
        column.setSpacing(K.SPACE["3"])
        self.title = UI.label(T["style_title"], "h2", wrap=True)
        self.intro = UI.label(T["style_intro"], "body", wrap=True)
        self.only_yours = UI.label(T["style_only_yours"], "small", wrap=True)
        self.only_yours.set_tone("blue")
        for widget in (self.title, self.intro, self.only_yours):
            column.addWidget(widget)
        self._build_select(column)
        self.result_host = QWidget()
        self.result_layout = QVBoxLayout(self.result_host)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        self.result_layout.setSpacing(K.SPACE["3"])
        column.addWidget(self.result_host)
        column.addStretch(1)                                                                        # 남는 키는 아래로(모습이 바뀌어 몸이 짧아져도 글 사이가 벌어지지 않는다)
        self.scroll = DialogScroll(body)
        self.scroll.setFocusPolicy(Qt.StrongFocus)                                                  # 키보드로 스크롤할 수 있게(방향키) — 이름이 있는 Tab 정거장
        self.scroll.setAccessibleName(T["style_scroll_a11y"])
        self.scroll.setProperty("focus_key", "style:scroll")
        outer.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        row.setSpacing(K.SPACE["2"])
        row.addStretch(1)
        self.again_button = UI.Button("ghost", T["style_again"], accessible=T["style_again_a11y"], focus_key="style:again")
        self.again_button.clicked.connect(lambda _=False: self.shell.style_again())
        self.close_button = UI.Button("secondary", T["style_close"], accessible=T["style_close_a11y"], focus_key="style:close")
        self.close_button.clicked.connect(lambda _=False: self.shell.style_close())
        self.compute_button = UI.Button("primary", T["style_compute"], accessible=T["style_compute_a11y"], focus_key="style:compute")
        self.compute_button.clicked.connect(lambda _=False: self.shell.style_compute())
        for button in (self.again_button, self.close_button, self.compute_button):
            row.addWidget(button)
        outer.addLayout(row)
        self.refresh()

    # ---- 만들기 ----
    def _build_select(self, column):
        self.select_host = QWidget()
        box = QVBoxLayout(self.select_host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(K.SPACE["2"])
        self.pick_button = UI.Button("secondary", T["style_pick"], accessible=T["style_pick_a11y"], focus_key="style:pick")
        self.pick_button.clicked.connect(lambda _=False: self.shell.style_pick())
        box.addWidget(self.pick_button, 0, Qt.AlignLeft)
        self.pick_hint = UI.label(T["style_pick_hint"], "caption", wrap=True)
        box.addWidget(self.pick_hint)
        self.slots_host = QWidget()
        self.slots_layout = QVBoxLayout(self.slots_host)
        self.slots_layout.setContentsMargins(0, 0, 0, 0)
        self.slots_layout.setSpacing(K.SPACE["1"])
        self.slots_host.setAccessibleName(T["style_slots_a11y"])
        box.addWidget(self.slots_host)
        self.paste_label = UI.label(T["style_paste_label"], "small")
        box.addWidget(self.paste_label)
        self.paste = PasteBox(T["style_paste_a11y"])
        self.paste.textChanged.connect(self._pasted_changed)
        box.addWidget(self.paste)
        self.paste_hint = UI.label(T["style_paste_hint"], "caption", wrap=True)
        box.addWidget(self.paste_hint)
        self.paste_count = UI.label(T["style_paste_count"].format(n=0), "caption")
        self.paste_count.setAlignment(Qt.AlignRight)
        box.addWidget(self.paste_count)
        self.message = UI.label("", "small", wrap=True)
        self.message.set_tone("red")
        self.message.setVisible(False)
        box.addWidget(self.message)
        self.status = UI.label("", "small", wrap=True)
        self.status.set_tone("slate")
        box.addWidget(self.status)
        column.addWidget(self.select_host)

    def _rebuild_slots(self, slots):
        """고른 파일 줄들(`글 1 · 파일에서 가져옴` + `빼기`) — 파일 이름·위치는 보이지 않는다."""
        _empty_layout(self.slots_layout)
        self.slot_buttons = []
        for slot in slots:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(K.SPACE["2"])
            line.addWidget(UI.label(slot["label"], "body"), 1)
            button = UI.Button("ghost", slot["remove"], size="sm", accessible=slot["a11y"], focus_key=f"style:remove:{slot['index']}")
            button.clicked.connect(lambda _=False, index=slot["index"]: self.shell.style_remove(index))
            line.addWidget(button)
            self.slots_layout.addWidget(row)
            self.slot_buttons.append(button)

    def _build_result(self, result):
        """결과 모습 — 표 카드(항목 × 글별·범위·합산)·센 개수·안내. 숫자와 고정 문장뿐이다."""
        self._clear_result()
        card, inner = UI.Card((K.SPACE["4"], K.SPACE["3"], K.SPACE["4"], K.SPACE["3"]), kind="plain")
        inner.setSpacing(K.SPACE["2"])
        card.setAccessibleName(result["a11y"])
        inner.addWidget(UI.label(result["title"], "h3", wrap=True))
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(K.SPACE["3"])
        grid.setVerticalSpacing(K.SPACE["2"])
        grid.setColumnStretch(0, 5)
        grid.addWidget(UI.label(result["item_header"], "caption"), 0, 0)
        columns = result["columns"]
        for number, column in enumerate(columns, start=1):
            head = UI.label(column["text"], "caption")
            head.setAlignment(Qt.AlignRight | Qt.AlignTop)
            grid.addWidget(head, 0, number)
            grid.setColumnStretch(number, 2)
        self.cells = {}
        for index, row in enumerate(result["rows"], start=1):
            label = UI.label(row["label"], "body", wrap=True)
            label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            label.setAccessibleName(row["a11y"])
            grid.addWidget(label, index, 0)
            texts = [*row["cells"], *([row["range"]] if any(item["key"] == "range" for item in columns) else []), *([row["total"]] if any(item["key"] == "total" for item in columns) else [])]
            for number, text in enumerate(texts, start=1):
                cell = UI.label(text, "body", wrap=True)                                            # 줄 높이를 항목 이름과 같게(같은 줄에서 글자 높이가 어긋나지 않게)
                cell.setAlignment(Qt.AlignRight | Qt.AlignTop)
                grid.addWidget(cell, index, number)
                self.cells[(row["key"], number)] = cell
        inner.addWidget(grid_host)
        self.result_layout.addWidget(card)
        self.result_layout.addWidget(UI.label(result["counts_title"], "small"))
        for line in result["counts"]:
            self.result_layout.addWidget(UI.label(line, "caption", wrap=True))
        for note in (result["range_only_note"], result["total_note"]):
            if note:
                self.result_layout.addWidget(self._note(note, "blue" if note == result["range_only_note"] else "slate"))
        if result["notes"]:
            self.result_layout.addWidget(UI.label(result["notes_title"], "small"))
            for line in result["notes"]:
                self.result_layout.addWidget(self._note(line, "blue"))
        self.result_layout.addWidget(self._note(result["trust"], "slate", role="small"))
        self.result_layout.addWidget(self._note(result["yours"], "slate", role="small"))                     # 결과 화면만 봐도 직접 쓴 글만 골랐을 때의 숫자라는 것을 알게(D-434)
        self.result_layout.addWidget(self._note(result["rough"], "slate"))
        self.result_card = card

    @staticmethod
    def _note(text, tone, role="caption"):
        label = UI.label(text, role, wrap=True)
        label.set_tone(tone)
        return label

    def _clear_result(self):
        _empty_layout(self.result_layout)
        self.cells = {}
        self.result_card = None

    # ---- 그리기 ----
    def pasted_chars(self):
        return self.paste.chars()

    def pasted_text(self):
        """입력 칸의 글 — 계산을 시작하는 순간 한 번 읽어 값으로 넘긴다(이 부품이 따로 쥐지 않는다)."""
        return self.paste.toPlainText()

    def refresh(self):
        """컨트롤러의 뷰모델에 맞게 모습·고른 글·단추·안내를 바꾼다 — 입력 칸의 글은 건드리지 않는다."""
        study = self.study
        if study is None:
            return None
        vm = study.view(self.pasted_chars())
        phase = vm["phase"]
        result = phase == "result"
        self.select_host.setVisible(not result)
        self.intro.setVisible(not result)                                                           # 결과 모습에서는 안내를 접어 표가 먼저 보이게 한다(제목은 그대로)
        self.only_yours.setVisible(not result)
        self.result_host.setVisible(result)
        self.compute_button.setVisible(not result)
        self.again_button.setVisible(result)
        self._rebuild_slots(vm["slots"])
        self.pick_button.setEnabled(vm["pick"]["enabled"])
        self.paste.setEnabled(vm["paste"]["enabled"])
        self.paste_count.set_text(vm["paste"]["count"])
        self.paste_count.setAccessibleName(vm["paste"]["count_a11y"])
        self.compute_button.setEnabled(vm["compute"]["enabled"])
        self.message.set_text(vm["message"])
        self.message.setVisible(bool(vm["message"]))
        self.status.set_text(vm["status"])
        self.status.setVisible(bool(vm["status"]))
        self.status.setAccessibleName(vm["status_a11y"] or vm["status"])
        if result:
            signature = repr(vm["result"])
            if signature != self._signature:
                self._build_result(vm["result"])
                self._signature = signature
        else:
            if self._signature is not None:
                self._clear_result()
                self._signature = None
        self._tab_order()
        self._refit()
        QTimer.singleShot(0, self._refit_later)                                                     # 새로 만든 부품은 보이고 글꼴이 입혀진 다음에야 제 키를 알린다 — 한 번 더 맞춘다
        return vm

    def _tab_order(self):
        """Tab 순서 — 몸(스크롤) → 파일 고르기 → 빼기들 → 붙여 넣기 칸 → (결과 모습의) 다시 하기 → 닫기 → 계산하기. 안 보이거나 꺼진 부품은 Qt 가 건너뛴다."""
        chain = [self.scroll, self.pick_button, *self.slot_buttons, self.paste, self.again_button, self.close_button, self.compute_button]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    def _refit(self):
        """모습이 바뀌어 몸의 키가 달라지면 열려 있는 대화상자의 키를 다시 맞춘다(창에 들어가는 한 스크롤 없이 몸이 다 보이게)."""
        host = self.parentWidget()
        dialog = getattr(self.shell, "dialog", None)
        if host is None or host is not dialog or not dialog.is_open:
            return
        for layout in (self.result_layout, self.slots_layout):
            layout.invalidate()
        for widget in (self.result_host, self.slots_host, self.select_host, self.scroll.widget(), self.scroll, self):
            widget.updateGeometry()
        dialog.layout_.activate()
        dialog.place()

    def _refit_later(self):
        try:
            self._refit()
        except RuntimeError:                                                                        # 그 사이 대화상자가 닫혀 부품이 지워졌다
            pass

    def _pasted_changed(self):
        """글을 치면 글자 수와 `계산하기` 단추 상태만 바꾼다(화면 전체를 다시 그리지 않는다) — 글은 어디에도 옮겨 쥐지 않는다."""
        if self.study is None:
            return
        vm = self.study.view(self.pasted_chars())
        self.paste_count.set_text(vm["paste"]["count"])
        self.paste_count.setAccessibleName(vm["paste"]["count_a11y"])
        self.compute_button.setEnabled(vm["compute"]["enabled"])
        self.pick_button.setEnabled(vm["pick"]["enabled"])

    def wipe_paste(self):
        """붙여 넣기 칸을 비운다(계산이 끝났을 때·닫을 때)."""
        return self.paste.wipe()

    # ---- 포커스 ----
    def focus_start(self):
        """열릴 때의 첫 포커스 — 고르기 모습의 `파일 고르기`."""
        self.pick_button.setFocus(Qt.OtherFocusReason)

    def focus_result(self):
        """결과가 나왔을 때 — 몸(스크롤)에 포커스를 둔다(방향키로 읽는다)."""
        self.scroll.setFocus(Qt.OtherFocusReason)

    def focus_after_pick(self):
        """고른 뒤 포커스 — `파일 고르기`(꺼졌으면 `계산하기`, 그것도 꺼졌으면 `닫기`)."""
        target = self.pick_button if self.pick_button.isEnabled() else self.compute_button if self.compute_button.isEnabled() else self.close_button
        QTimer.singleShot(0, lambda widget=target: self._focus_later(widget))

    @staticmethod
    def _focus_later(widget):
        try:
            if widget.isEnabled() and widget.isVisible():
                widget.setFocus(Qt.OtherFocusReason)
        except RuntimeError:                                                                        # 그 사이 대화상자가 닫혀 부품이 지워졌다
            pass

    # ---- 버리기 ----
    def discard(self):
        """대화상자가 닫히거나 바뀔 때(어느 길로든) — 입력 칸·고른 글·결과 표를 모두 비운다. 여러 번 불러도 같다."""
        try:
            self.paste.wipe()
            self._clear_result()
            self._rebuild_slots([])
        except RuntimeError:                                                                        # 이미 지워진 부품
            pass
        self._signature = None
        self.study = None
        return True
