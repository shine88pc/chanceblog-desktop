"""'참고 글 보관함'(결정 D-490)의 Qt 부품 — 대화상자의 안쪽(`ReferencesDialog`). 진입점은 '내 글 문체 참고값 보기' 대화상자 안의 `참고 글 보관함 열기` 단추 하나다(`style_dialog.py`).
화면은 뷰모델(`ui/core/references_view.py` 의 `ReferenceLibrary.view` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 조립하기만 한다 — 규칙(목록·선택·저장 안 한 변경·지우기 두 단계·낡은 결과 버리기)은 모두 core 에 있다.
색·글꼴·크기·간격은 토큰(`K`·스타일시트)에서만 오고 여기서 인라인으로 정하지 않는다. 이 파일에는 파일을 만지는 호출·네트워크·하위 프로세스·표준 출력이 없다(보관함 읽기·쓰기는 어댑터가 서비스를 부른다).

글(제목·본문)은 **편집 칸 두 개에만** 있고(`title_input`·`body`) 어느 길로든 대화상자가 닫히면 칸을 비운다(`discard` — 되돌리기 기록까지 지운다). 목록 줄은 뷰모델이 가린 제목뿐이다.
모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다. 색만으로 상태를 알리지 않는다(저장 안 한 변경·안내는 늘 글이 함께 있다).
몸(안내·목록·편집 칸)은 창이 낮을 때 스크롤되고(`DialogScroll`) 단추 줄은 늘 아래에 보인다.
이 PC 에서는 Qt 화면을 띄워 보지 못했다(PySide6 없음) — 소스 시험과 core·어댑터 시험만 돌렸고, 화면은 PySide6 가 있는 칸(CI)과 개인 PC 에서 확인해야 한다(`docs/UI_VISUAL_QA.md` 15절).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .key_parts import DialogScroll
from .style_dialog import PasteBox, _empty_layout

DIALOG_WIDTH = 760                                                                # 목록과 편집 칸이 들어갈 만큼 넓은 대화상자(창 논리 폭의 94% 를 넘지 않는다 — `Dialog.place`)


class BodyBox(PasteBox):
    """본문 편집 칸 — 평문뿐이고 Tab 은 글자가 아니라 다음 칸으로 간다(붙여 넣기 칸과 같은 부품 — 되돌리기 기록까지 지우는 `wipe` 를 쓴다)."""

    def __init__(self, accessible):
        super().__init__(accessible)
        self.setProperty("focus_key", "ref:body")


class ReferencesDialog(QWidget):
    """대화상자의 안쪽 — 목록·편집 칸(제목·본문)·확인 줄(지우기 두 단계·저장 안 한 변경)·폴더 위치·단추 줄. 모습은 컨트롤러(`ReferenceLibrary`)가 정하고 여기서는 그린다."""

    def __init__(self, shell, library):
        super().__init__()
        self.shell, self.library = shell, library
        self.pending = None                                                           # 저장 안 한 변경 확인이 기다리는 일 — `("select", 번호)`·`("new",)`·`("close",)`
        self.open_buttons = []
        self.setAccessibleName(T["ref_title"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(K.SPACE["3"])
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, K.SPACE["2"], 0)
        column.setSpacing(K.SPACE["3"])
        self.title = UI.label(T["ref_title"], "h2", wrap=True)
        self.intro = UI.label(T["ref_intro"], "body", wrap=True)
        self.limits = UI.label("", "small", wrap=True)
        self.limits.set_tone("blue")
        for widget in (self.title, self.intro, self.limits):
            column.addWidget(widget)
        self._build_list(column)
        self._build_editor(column)
        self.scroll = DialogScroll(body)
        self.scroll.setFocusPolicy(Qt.StrongFocus)                                    # 키보드로 스크롤할 수 있게(방향키) — 이름이 있는 Tab 정거장
        self.scroll.setAccessibleName(T["ref_title"])
        self.scroll.setProperty("focus_key", "ref:scroll")
        outer.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        row.setSpacing(K.SPACE["2"])
        self.delete_button = UI.Button("ghost", T["ref_delete"], accessible=T["ref_delete_a11y"], focus_key="ref:delete")
        self.delete_button.clicked.connect(lambda _=False: self.shell.references_delete())
        self.pick_button = UI.Button("secondary", T["ref_pick"], accessible=T["ref_pick_a11y"], focus_key="ref:pick")
        self.pick_button.clicked.connect(lambda _=False: self.shell.references_pick())
        self.new_button = UI.Button("secondary", T["ref_new"], accessible=T["ref_new_a11y"], focus_key="ref:new")
        self.new_button.clicked.connect(lambda _=False: self.shell.references_new())
        self.save_button = UI.Button("primary", T["ref_save"], accessible=T["ref_save_a11y"], focus_key="ref:save")
        self.save_button.clicked.connect(lambda _=False: self.shell.references_save())
        self.close_button = UI.Button("secondary", T["ref_close"], accessible=T["ref_close_a11y"], focus_key="ref:close")
        self.close_button.clicked.connect(lambda _=False: self.shell.references_close())
        row.addWidget(self.delete_button)
        row.addStretch(1)
        for button in (self.pick_button, self.new_button, self.close_button, self.save_button):
            row.addWidget(button)
        outer.addLayout(row)
        self.refresh()

    # ---- 만들기 ----
    def _build_list(self, column):
        self.list_title = UI.label(T["ref_list_title"], "h3", wrap=True)
        self.list_count = UI.label("", "caption")
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(K.SPACE["1"])
        self.rows_host.setAccessibleName(T["ref_list_a11y"])
        self.list_note = UI.label("", "small", wrap=True)                             # 읽는 중·비어 있음 안내
        self.skipped = UI.label("", "small", wrap=True)
        self.skipped.set_tone("blue")
        for widget in (self.list_title, self.list_count, self.rows_host, self.list_note, self.skipped):
            column.addWidget(widget)

    def _build_editor(self, column):
        self.heading = UI.label(T["ref_editor_new"], "h3", wrap=True)
        column.addWidget(self.heading)
        column.addWidget(UI.label(T["ref_title_label"], "small"))
        self.title_input = UI.TextInput(T["ref_title_a11y"])
        self.title_input.setProperty("focus_key", "ref:title")
        self.title_input.textChanged.connect(lambda _text="": self._edited())
        column.addWidget(self.title_input)
        column.addWidget(UI.label(T["ref_title_hint"], "caption", wrap=True))
        column.addWidget(UI.label(T["ref_body_label"], "small"))
        self.body = BodyBox(T["ref_body_a11y"])
        self.body.textChanged.connect(self._edited)
        column.addWidget(self.body)
        column.addWidget(UI.label(T["ref_body_hint"], "caption", wrap=True))
        self.body_count = UI.label("", "caption")
        self.body_count.setAlignment(Qt.AlignRight)
        column.addWidget(self.body_count)
        self.editor_state = UI.label("", "small", wrap=True)
        self.editor_state.set_tone("slate")
        column.addWidget(self.editor_state)
        self.confirm_host = QWidget()                                                 # 지우기 두 단계·저장 안 한 변경 확인 줄
        self.confirm_layout = QVBoxLayout(self.confirm_host)
        self.confirm_layout.setContentsMargins(0, 0, 0, 0)
        self.confirm_layout.setSpacing(K.SPACE["2"])
        column.addWidget(self.confirm_host)
        self.message = UI.label("", "small", wrap=True)
        self.message.set_tone("red")
        self.message.setVisible(False)
        column.addWidget(self.message)
        self.notice = UI.label("", "small", wrap=True)
        self.notice.set_tone("slate")
        self.notice.setVisible(False)
        column.addWidget(self.notice)
        self.folder_label = UI.label("", "small")
        self.folder_text = UI.label("", "caption", wrap=True)
        self.folder_note = UI.label("", "caption", wrap=True)
        for widget in (self.folder_label, self.folder_text, self.folder_note):
            column.addWidget(widget)
        column.addStretch(1)

    def _rebuild_rows(self, rows):
        """목록 줄들 — 제목·글자 수·고친 때(뷰모델이 가린 글) + `열기` 단추. 열린 글은 접근 이름에 '지금 편집 중' 이 붙는다."""
        _empty_layout(self.rows_layout)
        self.open_buttons = []
        for number, item in enumerate(rows):
            line = QWidget()
            layout = QHBoxLayout(line)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(K.SPACE["2"])
            label = UI.label(item["label"], "body", wrap=True)
            label.setAccessibleName(item["a11y"])
            if item["selected"]:
                label.set_tone("blue")
            layout.addWidget(label, 1)
            button = UI.Button("ghost", item["open"]["text"], size="sm", accessible=item["open"]["a11y"], focus_key=f"ref:open:{number}")
            button.clicked.connect(lambda _=False, ref_id=item["id"]: self.shell.references_select(ref_id))
            layout.addWidget(button)
            self.rows_layout.addWidget(line)
            self.open_buttons.append(button)

    def _rebuild_confirm(self, vm):
        """확인 줄 — 지우기 1·2단계 또는 저장 안 한 변경(버리고 열기). 둘 다 아니면 비어 있다."""
        _empty_layout(self.confirm_layout)
        self.confirm_buttons = []
        step = vm["delete"]["step"]
        if step:
            self._confirm_row(vm["delete"]["question"], (vm["delete"]["next"], self.shell.references_delete_next, "ref:delete-next", "danger" if step == 2 else "secondary"),
                              (vm["delete"]["cancel"], self.shell.references_delete_cancel, "ref:delete-cancel", "ghost"))
        elif self.pending is not None:
            self._confirm_row(vm["discard"]["question"], ({"text": vm["discard"]["yes"], "a11y": vm["discard"]["yes"]}, self.shell.references_discard_yes, "ref:discard-yes", "secondary"),
                              ({"text": vm["discard"]["no"], "a11y": vm["discard"]["no"]}, self.shell.references_discard_no, "ref:discard-no", "ghost"))

    def _confirm_row(self, question, *buttons):
        box = UI.label(question, "body", wrap=True)
        box.set_tone("red")
        self.confirm_layout.addWidget(box)
        line = QHBoxLayout()
        line.setSpacing(K.SPACE["2"])
        for info, handler, key, kind in buttons:
            button = UI.Button(kind, info["text"], accessible=info["a11y"], focus_key=key)
            button.clicked.connect(lambda _=False, call=handler: call())
            line.addWidget(button)
            self.confirm_buttons.append(button)
        line.addStretch(1)
        self.confirm_layout.addLayout(line)

    # ---- 글 칸 ----
    def title_text(self):
        return self.title_input.text()

    def body_text(self):
        """편집 칸의 글 — 저장을 누르는 순간 한 번 읽어 값으로 넘긴다(이 부품이 따로 쥐지 않는다)."""
        return self.body.toPlainText()

    def fill(self, title, body):
        """편집 칸을 채운다(열었을 때·새 글·지웠을 때) — 채우는 동안은 '바뀜' 신호를 끄고 되돌리기 기록을 지운다."""
        for box in (self.title_input, self.body):
            box.blockSignals(True)
        self.title_input.setText(title)
        self.body.setPlainText(body)
        self.body.document().clearUndoRedoStacks()
        for box in (self.title_input, self.body):
            box.blockSignals(False)
        self._edited()

    def _edited(self):
        """글을 치면 글자 수와 '저장 안 한 변경' 표시만 바꾼다(화면 전체를 다시 그리지 않는다) — 글은 어디에도 옮겨 쥐지 않는다."""
        if self.library is None:
            return
        self.library.edited(self.title_input.text(), self.body.toPlainText())
        vm = self.library.view(self.body.chars())
        self.body_count.set_text(vm["editor"]["count"])
        self.body_count.setAccessibleName(vm["editor"]["count_a11y"])
        self.editor_state.set_text(vm["editor"]["state"])
        self.editor_state.setVisible(bool(vm["editor"]["state"]))

    # ---- 그리기 ----
    def refresh(self):
        """컨트롤러의 뷰모델에 맞게 목록·단추·안내를 바꾼다 — 편집 칸의 글은 건드리지 않는다."""
        library = self.library
        if library is None:
            return None
        vm = library.view(self.body.chars())
        self.limits.set_text(vm["limits"])
        self.list_count.set_text(vm["list"]["count"] if library.loaded else "")
        self._rebuild_rows(vm["list"]["rows"])
        note = vm["list"]["loading"] or vm["list"]["empty"]
        self.list_note.set_text(note)
        self.list_note.setVisible(bool(note))
        self.skipped.set_text(vm["list"]["skipped"])
        self.skipped.setVisible(bool(vm["list"]["skipped"]))
        self.heading.set_text(vm["editor"]["heading"])
        self.body_count.set_text(vm["editor"]["count"])
        self.body_count.setAccessibleName(vm["editor"]["count_a11y"])
        self.editor_state.set_text(vm["editor"]["state"])
        self.editor_state.setVisible(bool(vm["editor"]["state"]))
        self._rebuild_confirm(vm)
        buttons = vm["buttons"]
        blocked = self.pending is not None
        self.save_button.setEnabled(buttons["save"]["enabled"] and not blocked)
        self.new_button.setEnabled(buttons["new"]["enabled"] and not blocked)
        self.pick_button.setEnabled(buttons["pick"]["enabled"] and not blocked)
        self.delete_button.setEnabled(buttons["delete"]["enabled"] and not blocked)
        self.close_button.setEnabled(buttons["close"]["enabled"])
        self.message.set_text(vm["message"])
        self.message.setVisible(bool(vm["message"]))
        self.notice.set_text(vm["notice"])
        self.notice.setVisible(bool(vm["notice"]))
        self.folder_label.set_text(vm["folder"]["label"])
        self.folder_text.set_text(vm["folder"]["text"])
        self.folder_note.set_text(vm["folder"]["note"])
        self._tab_order()
        QTimer.singleShot(0, self._refit_later)
        return vm

    def _tab_order(self):
        """Tab 순서 — 몸(스크롤) → 목록의 `열기`들 → 제목 → 본문 → 확인 줄 → 지우기 → 파일에서 올리기 → 새 글 → 닫기 → 저장. 안 보이거나 꺼진 부품은 Qt 가 건너뛴다."""
        chain = [self.scroll, *self.open_buttons, self.title_input, self.body, *getattr(self, "confirm_buttons", []), self.delete_button, self.pick_button, self.new_button, self.close_button, self.save_button]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    def _refit_later(self):
        """모습이 바뀌어 몸의 키가 달라지면 열려 있는 대화상자의 키를 다시 맞춘다."""
        try:
            host = self.parentWidget()
            dialog = getattr(self.shell, "dialog", None)
            if host is None or host is not dialog or not dialog.is_open:
                return
            for layout in (self.rows_layout, self.confirm_layout):
                layout.invalidate()
            for widget in (self.rows_host, self.confirm_host, self.scroll.widget(), self.scroll, self):
                widget.updateGeometry()
            dialog.layout_.activate()
            dialog.place()
        except RuntimeError:                                                          # 그 사이 대화상자가 닫혀 부품이 지워졌다
            pass

    # ---- 포커스 ----
    def focus_start(self):
        """열릴 때의 첫 포커스 — 제목 칸."""
        self.title_input.setFocus(Qt.OtherFocusReason)

    # ---- 버리기 ----
    def discard(self):
        """대화상자가 닫히거나 바뀔 때(어느 길로든) — 제목·본문 칸과 목록을 모두 비운다. 여러 번 불러도 같다."""
        try:
            self.title_input.blockSignals(True)
            self.body.blockSignals(True)
            self.title_input.setText("")
            self.body.wipe()
            _empty_layout(self.rows_layout)
            _empty_layout(self.confirm_layout)
        except RuntimeError:                                                          # 이미 지워진 부품
            pass
        self.pending = None
        self.open_buttons = []
        self.library = None
        return True
