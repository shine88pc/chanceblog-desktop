"""초안 작성 화면의 부품(P4e) — 평문 글 칸(`TextArea` — 본문 편집기·여러 줄 선택 입력 칸)·제목 후보 줄(`TitlePick`)·검사 카드(`InspectCard`)·복사 단추의 `✓ 복사됨` 모양(`set_copy_look`). 아래 고정 행동 줄은 공통 부품 `bars.ActionBar`(UI-C0)를 쓴다.
화면(`draft_screen.py`)은 뷰모델(`ui/core/drafts_view.py` 가 만든 딕셔너리)을 이 부품과 공통 부품(`components.py`)으로 조립하기만 한다. 색·글꼴·크기·간격은 토큰(`K`·스타일시트)에서만 오고 여기서 인라인 스타일·직접 색·글꼴 이름을 쓰지 않는다
(속성 `editor`·`draftpick`·`selected`·`copied` 만 붙이면 스타일시트가 입힌다). 모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다.

글 칸은 **평문뿐**이다(서식·그림 붙이기 없음)이고 Tab 은 글자가 아니라 다음 칸으로 간다(키보드 사용자가 칸에서 빠져나올 수 있게). 글이 바뀌면 `edited(글)` 신호가 나가고 코드로 값을 넣을 때(`set_value`)는 나가지 않는다 — 한글 입력기(IME) 조합 중에는
글 칸의 글이 확정될 때만 바뀐다(조합 중 글자는 칸의 글이 아니다). 글을 칠 때 화면 전체를 다시 그리지 않는다(셸이 이 칸의 상태 줄만 갱신한다).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI


class TextArea(QPlainTextEdit):
    """여러 줄 평문 칸 — 본문 편집기(최소 높이 420~480)와 선택 입력의 여러 줄 칸이 쓴다."""
    edited = Signal(str)

    def __init__(self, accessible, *, min_height, placeholder="", focus_key=None):
        super().__init__()
        self.setProperty("editor", True)
        self.setAccessibleName(accessible)
        self.setMinimumHeight(min_height)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setUndoRedoEnabled(True)
        self.setPlaceholderText(placeholder)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if focus_key:
            self.setProperty("focus_key", focus_key)
        self._quiet = False
        self.textChanged.connect(self._changed)

    def _changed(self):
        if not self._quiet:
            self.edited.emit(self.toPlainText())

    def set_value(self, text):
        """코드로 값을 넣는다 — `edited` 가 나가지 않는다(셸이 상태를 이미 알고 있다)."""
        self._quiet = True
        try:
            self.setPlainText(text)
        finally:
            self._quiet = False

    def value(self):
        return self.toPlainText()

    def inputMethodEvent(self, event):
        """읽기 전용일 때(새 초안을 만드는 동안) 입력기가 확정한 글도 받지 않는다 — Qt 의 읽기 전용은 입력기 이벤트가 곧바로 와도 걸러 주지 않는다(진짜 입력기는 읽기 전용 칸을 꺼 두지만, 이벤트가 와도 글이 바뀌지 않게)."""
        if self.isReadOnly():
            event.ignore()
            return
        super().inputMethodEvent(event)


class TitleInput(QLineEdit):
    """제목 입력 칸 — 공통 `TextInput` 과 같은 모양(최소 높이·접근 이름)이고, 읽기 전용일 때는 입력기가 확정한 글도 받지 않는다(`TextArea.inputMethodEvent` 와 같은 까닭)."""

    def __init__(self, accessible):
        super().__init__()
        self.setMinimumHeight(K.SIZE["input_h"])
        self.setAccessibleName(accessible)

    def inputMethodEvent(self, event):
        if self.isReadOnly():
            event.ignore()
            return
        super().inputMethodEvent(event)


class TitlePick(UI.Pressable):
    """제목 후보 한 줄 — 눌러서 고른다(Enter·Space 도). 선택은 2px 테두리와 `●`/`○` 모양으로 알린다(색만으로 알리지 않는다). 긴 제목은 한 줄로 줄이고 전체는 툴팁에 있다."""
    picked = Signal(int)

    def __init__(self, vm):
        super().__init__(vm["a11y"])
        self.index = vm["index"]
        self.setProperty("draftpick", "true")
        self.setProperty("focus_key", f"drf-pick:{self.index}")
        row = QHBoxLayout(self)
        row.setContentsMargins(K.SPACE["3"], K.SPACE["2"], K.SPACE["3"], K.SPACE["2"])
        row.setSpacing(K.SPACE["3"])
        self.mark = UI.label("○", "body")
        self.number = UI.label(vm["label"], "small")
        self.text = UI.ElidedLabel(vm["text"], "body")
        row.addWidget(self.mark, 0, Qt.AlignVCenter)
        row.addWidget(self.number, 0, Qt.AlignVCenter)
        row.addWidget(self.text, 1, Qt.AlignVCenter)
        self.setMinimumHeight(K.SIZE["hit"])
        self.activated.connect(lambda: self.picked.emit(self.index))
        self.set_selected(vm["selected"])

    def set_selected(self, selected):
        selected = bool(selected)
        self.setProperty("selected", selected)
        self.mark.setText("●" if selected else "○")
        self.setAccessibleDescription(T["drf_pick_selected"] if selected else "")
        UI.repolish(self)


class InspectCard:
    """검사 결과 카드의 글(상태 한 줄·걸린 문장들) — 카드 틀은 화면이 만들고 이 도우미가 상태·줄을 그 자리에서 바꾼다(편집기를 다시 그리지 않는다)."""

    def __init__(self, status_label, lines_box):
        self.status, self.lines = status_label, lines_box

    def set_state(self, vm):
        self.status.set_text(vm["status"])
        self.status.set_tone({"ok": "green", "error": "red", "warning": "orange", "info": "blue", "muted": "slate"}.get(vm["tone"], "slate"))
        layout = self.lines.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        for line in vm["lines"]:
            layout.addWidget(UI.label(line, "small", wrap=True))
        self.lines.setVisible(bool(vm["lines"]))


def lines_box():
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(K.SPACE["1"])
    return box


def set_copy_look(button, text, copied, a11y=None):
    """복사 단추의 `✓ 본문 복사됨` 모양 — 글이 바뀌고 성공색(스타일시트의 `copied` 속성)이 입혀진다. 끝나면 원래 글로 돌아온다. 접근 이름도 같이 바뀌어 화면 읽기 프로그램이 읽는다(글자만이 아니라 ✓ 도 함께 — 색만으로 알리지 않는다)."""
    button.setText(text)
    button.setProperty("copied", bool(copied))
    button.setAccessibleName(text if copied else (a11y or text))
    UI.repolish(button)


__all__ = ["InspectCard", "TextArea", "TitleInput", "TitlePick", "lines_box", "set_copy_look"]
