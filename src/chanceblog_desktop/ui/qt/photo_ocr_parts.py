"""'사진 정리' 창의 글자 읽기 부품(결정 D-513, 설계서 2-2·2-6, 시험 계획 T-C) — 사진 한 줄 안의 글자 읽기 칸(`OcrBlock`: 단추·상태 줄·확인 줄·읽은 글 목록)과 읽은 글 목록(`OcrLines`).
뷰모델(`ui/core/photo_ocr_panel.py` 의 `OcrPanel.view` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 그리기만 한다 — 규칙(단추가 보이는 때·문구·확인 줄·줄 규칙)은 모두 core 에 있다. 색·글꼴·크기·간격은 토큰(`K`·스타일시트의 `ocrline` 속성)에서만 오고 여기서 인라인으로 정하지 않는다.
이 파일에는 파일을 읽거나 쓰는 호출·네트워크·하위 프로세스·표준 출력이 없고 사진 경로도 모른다(읽는 일은 `ocr_runner.py` 가 한다).

**읽은 글 목록(`OcrLines`)은 Tab 정거장이 하나다**(칩 묶음의 `ChipGroupKeys` 와 같은 생각 — 줄이 60개여도 Tab 으로 줄마다 서지 않는다). 목록 안은 방향키로 옮긴다: 위·아래 = 줄 이동(끝에서 멈춘다)·Home·End = 처음·마지막 줄 · **Space = 맞아요 켜고 끄기** ·
**Enter 또는 F2 = 글 고치기**(Enter 로 반영하고 다음 줄로 간다) · **Esc = 고치기 그만두기**(읽는 중이면 취소 — 창 전체의 Esc 가 `photos_escape` → `escape_ocr` 로 온다) · **Delete = 빼기**(한 번 되돌릴 수 있다). 줄 안의 체크 상자·고치기·빼기 단추는 마우스용이고 `ClickFocus` 다(눌러도 포커스는 곧 목록으로 돌아온다).
접근 이름은 지금 고른 줄을 말한다('사진 3 읽은 글 12줄 중 4번째, 확인 전' — 접근 설명은 그 줄의 글). 줄을 옮기거나 상태가 바뀔 때마다 이름·설명을 갱신하고 읽는 프로그램에 알린다(Qt 에는 실시간 영역이 없어 이 방식이 실제로 읽히는지는 운영자 PC 에서 확인한다). 키 안내는 목록 아래의 글 한 줄이다(툴팁은 긴 목록에서 화면 밖에 뜬다).
확인 전 줄은 '확인 전' 글과 점선 테두리, 확인함 줄은 '확인함' 글과 체크 표시와 실선 테두리로 구분한다 — 색만으로 알리지 않는다. 줄이 많은 사진은 목록이 자체 높이 상한 안에서 스크롤한다(`LIST_MAX_HEIGHT`).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ..core import tokens as K
from . import components as UI

LIST_ROWS_SHOWN = 8                                                          # 목록이 늘어나지 않고 안에서 스크롤하기 시작하는 줄 수의 어림(줄 높이 기준)
LIST_MAX_HEIGHT = LIST_ROWS_SHOWN * (K.SIZE["table_row_h"] + K.SPACE["2"])   # 읽은 글 목록의 높이 상한 — 넘으면 목록 안에서 스크롤한다(영수증 40줄이 사진 줄 하나를 몇 화면 길이로 만들지 않게)
ASK_REVEAL_DELAYS_MS = (0, 40, 160)                                          # 확인 줄이 새로 떴을 때 보이는 곳으로 스크롤하는 때(ms) — 겹친 배치(줄 → 칸 → 사진 줄 → 창)가 자리를 잡은 뒤에도 한 번씩 더 맞춘다
MOVE_KEYS = {Qt.Key_Up: -1, Qt.Key_Down: 1}                                  # 한 줄씩 옮기는 키(끝에서 멈춘다 — 돌지 않는다)
EDGE_KEYS = {Qt.Key_Home: 0, Qt.Key_End: -1}                                 # 처음·마지막 줄로 가는 키
EDIT_KEYS = (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2)                         # 글 고치기를 여는 키
CONFIRM_KEY, REMOVE_KEY = Qt.Key_Space, Qt.Key_Delete                        # 맞아요 켜고 끄기·빼기
COMBO = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier | Qt.ShiftModifier


def announce(widget, name, alert=False):
    """접근 이름을 바꾸고(같으면 아무것도 안 한다) 읽는 프로그램에 알린다 — `alert` 는 실패·완료처럼 놓치면 안 되는 알림."""
    if widget.accessibleName() == name:
        return False
    widget.setAccessibleName(name)
    QAccessible.updateAccessibility(QAccessibleEvent(widget, QAccessible.NameChanged))
    if alert and name:
        QAccessible.updateAccessibility(QAccessibleEvent(widget, QAccessible.Alert))
    return True


def reveal(widget):
    """프로그램으로 옮긴 포커스·줄은 스크롤이 따라가지 않는다 — 위젯이 보이도록 겹친 스크롤 영역(목록 안·창 몸)을 안쪽부터 모두 맞춘다."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(widget, 0, K.SPACE["2"])
        parent = parent.parentWidget()


class FlowRow(QWidget):
    """단추 줄 — 폭이 모자라면 다음 줄로 넘어가고 **보이는 것만** 자리를 차지한다(숨은 단추가 빈 자리를 남기지 않게 보이는 묶음이 바뀔 때만 다시 놓는다)."""

    def __init__(self, widgets):
        super().__init__()
        self.widgets, self._shown = list(widgets), None
        for widget in self.widgets:
            widget.setParent(self)                                                # 아직 줄에 놓이지 않은 부품도 처음부터 이 줄의 자식이다 — 부모 없는 위젯에 `setVisible(True)` 를 하면 별도의 창으로 잠깐 떠서 창 활성(포커스)을 빼앗는다
        self.flow = UI.FlowLayout(self, K.SPACE["2"])
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.show_only(())

    def show_only(self, visible):
        key = tuple(id(widget) for widget in visible)
        if key == self._shown:
            return
        self._shown = key
        while self.flow.count():
            self.flow.takeAt(0)
        for widget in self.widgets:
            widget.setVisible(widget in visible)
        for widget in visible:
            self.flow.addWidget(widget)
        self.flow.invalidate()
        self.setVisible(bool(visible))
        self.updateGeometry()


class LineEditor(QLineEdit):
    """읽은 글 한 줄을 고치는 칸 — Enter 는 `committed`, Esc 는 `escaped`(창 전체의 Esc 가 창을 닫지 않게 이 칸이 먼저 받는다), 포커스를 잃으면 `lost`."""
    committed = Signal()
    escaped = Signal()
    lost = Signal()

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            event.accept()                                                   # 창의 Esc 단축키보다 먼저 이 칸이 받는다 — 고치기만 그만둔다
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.accept()
            self.escaped.emit()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & COMBO:
            event.accept()
            self.committed.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if event.reason() not in (Qt.PopupFocusReason, Qt.ActiveWindowFocusReason):          # 다른 창·팝업으로 잠깐 간 것은 그만둔 것이 아니다
            self.lost.emit()


class OcrLineRow(QFrame):
    """읽은 글 한 줄 — 맞아요 체크 상자·글(고치는 동안은 입력 칸)·확인 전/확인함 글·고치기·빼기. 줄 위젯은 위치마다 하나이고 내용만 바뀐다(`apply`)."""

    def __init__(self, owner, index):
        super().__init__()
        self.owner, self.index, self._key = owner, index, None
        self.setProperty("ocrline", "pending")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(K.SPACE["2"], K.SPACE["1"], K.SPACE["2"], K.SPACE["1"])
        outer.setSpacing(K.SPACE["1"])
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(K.SPACE["2"])
        self.check = UI.CheckBox("")
        self.check.setFocusPolicy(Qt.ClickFocus)
        self.check.toggled.connect(lambda on: self.owner.row_confirm(self.index, bool(on)))
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.text = UI.label("", "body", wrap=True)
        self.editor = LineEditor()
        self.editor.setMinimumHeight(K.SIZE["input_h"])
        self.editor.committed.connect(lambda: self.owner.commit_edit(True))
        self.editor.escaped.connect(self.owner.cancel_edit)
        self.editor.lost.connect(lambda: self.owner.commit_edit(False))
        self.editor.setVisible(False)
        self.state = UI.label("", "caption")
        for widget in (self.text, self.editor, self.state):
            column.addWidget(widget)
        self.edit_button = UI.Button("ghost", "", size="sm")
        self.edit_button.setFocusPolicy(Qt.ClickFocus)
        self.edit_button.clicked.connect(lambda _=False: self.owner.begin_edit(self.index))
        self.remove_button = UI.Button("danger_ghost", "", size="sm")
        self.remove_button.setFocusPolicy(Qt.ClickFocus)
        self.remove_button.clicked.connect(lambda _=False: self.owner.row_remove(self.index))
        row.addWidget(self.check, 0, Qt.AlignTop)
        row.addLayout(column, 1)
        row.addWidget(self.edit_button, 0, Qt.AlignTop)
        row.addWidget(self.remove_button, 0, Qt.AlignTop)
        outer.addLayout(row)
        self.error = UI.label("", "small", wrap=True)
        self.error.set_tone("red")
        self.error.setVisible(False)
        outer.addWidget(self.error)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.owner.set_current(self.index, focus=True)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.owner.begin_edit(self.index)
        super().mouseDoubleClickEvent(event)

    def apply(self, item, current, focused, enabled, error):
        """뷰모델의 한 줄(`items` 의 한 칸)로 바꾼다 — 그대로면 아무것도 건드리지 않는다. `error`: 이 줄 아래에 보일 이유 문장(없으면 빈 글)."""
        editing = not self.editor.isHidden()
        key = (item["text"], item["confirmed"], item["a11y"], current, focused, enabled, error, editing)
        if key == self._key:
            return
        self._key = key
        kind = "done" if item["confirmed"] else "pending"
        if (self.property("ocrline"), self.property("current"), self.property("focused")) != (kind, current, focused):
            self.setProperty("ocrline", kind)
            self.setProperty("current", current)
            self.setProperty("focused", focused)
            UI.repolish(self)
        self.text.set_text(item["text"])
        self.text.setVisible(not editing)
        self.text.setAccessibleName(item["a11y"])
        self.text.setAccessibleDescription(item["text"])
        self.state.set_text(item["state_text"])
        self.state.set_tone("green" if item["confirmed"] else "slate")
        self.check.blockSignals(True)
        self.check.setChecked(bool(item["confirmed"]))
        self.check.blockSignals(False)
        self.check.setAccessibleName(item["check_a11y"])
        self.editor.setAccessibleName(item["text_a11y"])
        self.edit_button.setText(item["edit"])
        self.edit_button.setAccessibleName(item["edit_a11y"])
        self.remove_button.setText(item["remove"])
        self.remove_button.setAccessibleName(item["remove_a11y"])
        for widget in (self.check, self.edit_button, self.remove_button):
            widget.setEnabled(enabled)
        self.error.set_text(error)
        self.error.setVisible(bool(error))


class OcrLines(QWidget):
    """읽은 글 목록 — Tab 정거장 하나·방향키 이동·Space·Enter·F2·Delete(위 설명). 줄 수만큼의 줄 위젯을 위치마다 하나씩 쥐고 `apply` 로 내용만 바꾼다(줄이 사라져 포커스를 잃는 일이 없게)."""

    def __init__(self, block):
        super().__init__()
        self.block, self.rows, self.items = block, [], []
        self.current, self.editing, self._error, self._enabled = 0, None, None, True
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("focus_key", f"pho:ocr-lines:{block.photo_id}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(K.SPACE["1"])
        self.rows_layout = layout

    # ---- 그리기 ----
    def apply(self, vm):
        """`lines` 뷰모델로 바꾼다 — 줄 수가 달라지면 끝에서 줄 위젯을 더하거나 빼고, 고르는 줄은 범위 안으로 맞춘다. 고치는 중인데 목록이 잠기거나 줄이 사라졌으면 고치기를 그만둔다."""
        self.items, self._enabled = list(vm["items"]), bool(vm["enabled"])
        self._error = vm["error"]
        while len(self.rows) < len(self.items):
            row = OcrLineRow(self, len(self.rows))
            self.rows.append(row)
            self.rows_layout.addWidget(row)
        while len(self.rows) > len(self.items):
            row = self.rows.pop()
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.current = max(0, min(self.current, len(self.items) - 1))
        if self.editing is not None and (self.editing >= len(self.items) or not self._enabled):
            self._end_edit()
        self.setEnabled(self._enabled)
        self._sync()

    def _sync(self):
        focused = self.hasFocus() or self.editing is not None
        for index, (row, item) in enumerate(zip(self.rows, self.items)):
            error = self._error["text"] if self._error is not None and self._error["index"] == index else ""
            row.apply(item, index == self.current, focused, self._enabled, error)
        if self.items:
            now = self.items[self.current]
            announce(self, now["a11y"])
            self.setAccessibleDescription(now["text"])
        self.block.sync_merge()                                                # 합치기 단추는 고른 줄을 따라간다

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._sync()
        self.reveal_current()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._sync()

    def reveal_current(self):
        if self.rows:
            reveal(self.rows[self.current])

    # ---- 고르기 ----
    def set_current(self, index, focus=False):
        """지금 고른 줄을 바꾼다(범위 밖이면 가장자리로) — 접근 이름·설명이 따라 바뀌고 보이는 곳으로 스크롤한다."""
        if not self.rows:
            return
        index = max(0, min(index, len(self.rows) - 1))
        changed = index != self.current
        self.current = index
        if focus and self.editing is None:
            self.setFocus(Qt.MouseFocusReason)
        if changed:
            self._sync()
        self.reveal_current()

    def keyPressEvent(self, event):
        key = event.key()
        if event.modifiers() & COMBO or not self.rows:
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat() and (key in (CONFIRM_KEY, REMOVE_KEY) or key in EDIT_KEYS):
            event.accept()                                                  # 키를 계속 누르고 있어도 맞아요가 깜박이거나 줄이 연달아 빠지지 않는다
            return
        if key in MOVE_KEYS:
            self.set_current(self.current + MOVE_KEYS[key])
        elif key in EDGE_KEYS:
            self.set_current(EDGE_KEYS[key] % len(self.rows))
        elif key == CONFIRM_KEY:
            self.row_confirm(self.current, not self.items[self.current]["confirmed"])
        elif key in EDIT_KEYS:
            self.begin_edit(self.current)
        elif key == REMOVE_KEY:
            self.row_remove(self.current)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # ---- 줄에 하는 일(규칙은 창이 core 에 묻는다) ----
    def row_confirm(self, index, on):
        self.current = max(0, min(index, len(self.rows) - 1))
        self.block.line_do("confirm_line", index, on)
        self.setFocus(Qt.OtherFocusReason)

    def row_remove(self, index):
        self.current = max(0, min(index, len(self.rows) - 1))
        self._end_edit()
        self.block.line_do("remove_line", index)
        self.setFocus(Qt.OtherFocusReason)

    def begin_edit(self, index):
        """글 고치기 — 줄의 글이 입력 칸으로 바뀐다(Enter 로 반영하고 다음 줄로, Esc 로 그만둔다)."""
        if not self._enabled or not 0 <= index < len(self.rows):
            return
        if self.editing is not None and self.editing != index:
            self.commit_edit(False)                                         # 앞서 고치던 줄을 먼저 반영한다 — 받아들여지지 않았으면(이유가 보인다) 그 줄에 머문다
            if self.editing is not None:
                return
        self.current, self.editing = index, index
        row = self.rows[index]
        row.editor.setText(self.items[index]["text"])
        row.text.setVisible(False)
        row.editor.setVisible(True)
        row._key = None
        self._sync()
        row.editor.setFocus(Qt.OtherFocusReason)
        row.editor.selectAll()
        reveal(row)

    def commit_edit(self, advance):
        """고친 글을 규칙에 넘긴다 — 받아들여지면(또는 그대로면) 고치기를 끝내고 `advance` 면 다음 줄로 간다. 받아들이지 않으면 입력 칸을 그대로 두고 이유가 줄 아래에 보인다."""
        index = self.editing
        if index is None or index >= len(self.rows):
            return None
        row = self.rows[index]
        status = self.block.line_do("edit_line", index, row.editor.text())
        if status in ("ok", "unchanged") and self.editing == index:
            self._end_edit()
            if advance:
                self.set_current(index + 1)
                self.setFocus(Qt.OtherFocusReason)
        return status

    def cancel_edit(self):
        """Esc — 고치기를 그만두고(고친 글은 버린다) 목록으로 돌아온다."""
        if self.editing is None:
            return False
        self.block.clear_error()                                        # 이유 문장을 지운다(규칙은 부르지 않는다 — 고친 글은 버린다)
        self._end_edit()
        self.setFocus(Qt.OtherFocusReason)
        return True

    def _end_edit(self):
        index, self.editing = self.editing, None
        if index is not None and index < len(self.rows):
            row = self.rows[index]
            row.editor.setVisible(False)
            row.text.setVisible(True)
            row._key = None
        self._sync()


class OcrScroll(QScrollArea):
    """읽은 글 목록을 담는 높이 상한이 있는 스크롤 영역 — 줄이 적으면 목록 키만큼, 많으면 `LIST_MAX_HEIGHT` 까지만 늘어나고 그 안에서 스크롤한다. 사진 정리 창 몸(`DialogScroll`)처럼 '폭에 따른 높이'를 알려 준다."""

    def __init__(self, body):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.NoFocus)                                  # Tab 정거장은 안의 목록이다
        self.setWidget(body)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def content_changed(self):
        """줄이 늘거나 줄거나 줄 안의 글이 바뀌어 목록의 필요 높이가 달라졌다 — 부모 배치에 알린다. 알리지 않으면 부모 배치가 옛 높이(줄이 없던 때의 0)를 쥐고 있어 목록이 높이 0 으로 보인다."""
        QWidget.updateGeometry(self)

    def eventFilter(self, watched, event):
        """안쪽 배치가 다시 계산되라는 신호(`LayoutRequest`)가 오면 목록의 필요 높이가 달라졌을 수 있다."""
        if watched is self.widget() and event.type() == QEvent.LayoutRequest:
            self.content_changed()
        return super().eventFilter(watched, event)

    def heightForWidth(self, width):
        body = self.widget()
        if body is None:
            return 0
        inner = max(width - 2 * self.frameWidth(), 1)
        height = body.heightForWidth(inner) if body.hasHeightForWidth() else body.sizeHint().height()
        return min(max(height, 0), LIST_MAX_HEIGHT) + 2 * self.frameWidth()

    def sizeHint(self):
        width = max(self.width(), K.LAYOUT["dialog"] - 48)
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        return QSize(0, K.SIZE["hit"])


class AskBar(QWidget):
    """확인 줄 — 글 한 줄과 두 단추(진행·그만두기). 단추 순서는 (진행, 그만두기) — 마지막이 안전한 쪽이고 처음 포커스도 거기에 둔다."""

    def __init__(self, yes_kind, yes_key, no_key):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(K.SPACE["2"])
        self.message = UI.label("", "small", wrap=True)
        self.yes = UI.Button(yes_kind, "", size="sm", focus_key=yes_key)
        self.no = UI.Button("secondary", "", size="sm", focus_key=no_key)
        self.buttons = FlowRow([self.yes, self.no])
        layout.addWidget(self.message)
        layout.addWidget(self.buttons)
        self.buttons.show_only((self.yes, self.no))                            # 줄을 자리(부모)에 놓은 뒤에 보인다 — 부모 없는 위젯을 보이면 별도의 창으로 뜬다
        self.setVisible(False)

    def apply(self, vm):
        """확인 줄을 보이거나 거둔다 → 이번에 새로 떴으면 True."""
        was = self.isVisibleTo(self.parentWidget()) if self.parentWidget() is not None else self.isVisible()
        if vm is None:
            self.setVisible(False)
            return False
        self.message.set_text(vm["text"])
        self.yes.setText(vm["yes"])
        self.yes.setAccessibleName(vm["yes_a11y"])
        self.no.setText(vm["no"])
        self.no.setAccessibleName(vm["no_a11y"])
        self.setVisible(True)
        return not was


class OcrBlock(QWidget):
    """사진 한 줄 안의 글자 읽기 칸 — 이름표·`글자 읽기`/`다시 읽기`/`더 크게`/`취소` 단추·상태 줄·다시 읽기 확인 줄·읽은 글(제목·안내·목록·모두 맞아요·합치기·되돌리기·모두 맞아요 확인 줄).
    뷰모델이 `None` 이면 통째로 숨는다. 눌림은 창(`PhotoSheet.ocr_do`)에 넘기고 규칙은 core 가 정한다. 포커스가 있던 단추가 사라지면 남은 부품 가운데 가장 알맞은 곳으로 포커스를 옮긴다(키보드 사용자가 길을 잃지 않게)."""

    def __init__(self, sheet, photo_id):
        super().__init__()
        self.sheet, self.photo_id, self.vm = sheet, photo_id, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(K.SPACE["1"])
        self.title = UI.label("", "small")
        self.read_button = UI.Button("secondary", "", size="sm", focus_key=f"pho:ocr-read:{photo_id}")
        self.read_button.clicked.connect(lambda _=False: self._read(self.vm["read"]["size"]))
        self.bigger_button = UI.Button("ghost", "", size="sm", focus_key=f"pho:ocr-bigger:{photo_id}")
        self.bigger_button.clicked.connect(lambda _=False: self._read(self.vm["bigger"]["size"]))
        self.cancel_button = UI.Button("secondary", "", size="sm", focus_key=f"pho:ocr-cancel:{photo_id}")
        self.cancel_button.clicked.connect(lambda _=False: self.sheet.ocr_do("cancel", photo_id))
        self.hint = UI.label("", "caption")
        self.head = FlowRow([self.title, self.read_button, self.bigger_button, self.cancel_button, self.hint])
        self.status = UI.label("", "small", wrap=True)
        self.reread = AskBar("primary", f"pho:ocr-reread-yes:{photo_id}", f"pho:ocr-reread-no:{photo_id}")
        self.reread.yes.clicked.connect(lambda _=False: self.sheet.ocr_do("confirm_reread", photo_id))
        self.reread.no.clicked.connect(lambda _=False: self.sheet.ocr_do("cancel_reread", photo_id))
        self.none = UI.label("", "small", wrap=True)
        self.result = QWidget()
        box = QVBoxLayout(self.result)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(K.SPACE["1"])
        self.lines_title = UI.label("", "h3")
        self.guide = UI.label("", "caption", wrap=True)
        self.digits = UI.label("", "caption", wrap=True)
        self.digits.set_tone("orange")
        self.notes = UI.label("", "caption", wrap=True)
        self.lines = OcrLines(self)
        self.scroll = OcrScroll(self.lines)
        self.keys = UI.label("", "caption", wrap=True)                         # 키 안내 한 줄 — 툴팁은 긴 목록이면 화면 밖에 뜨므로 목록 아래에 늘 보이는 글로 둔다
        self.all_button = UI.Button("secondary", "", size="sm", focus_key=f"pho:ocr-all:{photo_id}")
        self.all_button.clicked.connect(lambda _=False: self.sheet.ocr_do("ask_all_right", photo_id))
        self.merge_button = UI.Button("secondary", "", size="sm", focus_key=f"pho:ocr-merge:{photo_id}")
        self.merge_button.clicked.connect(lambda _=False: self.line_do("merge_line", self.lines.current))
        self.undo_button = UI.Button("ghost", "", size="sm", focus_key=f"pho:ocr-undo:{photo_id}")
        self.undo_button.clicked.connect(lambda _=False: self.line_do("undo_remove"))
        self.removed = UI.label("", "caption")
        self.tools = FlowRow([self.all_button, self.merge_button, self.undo_button, self.removed])
        self.all_ask = AskBar("primary", f"pho:ocr-all-yes:{photo_id}", f"pho:ocr-all-no:{photo_id}")
        self.all_ask.yes.clicked.connect(lambda _=False: self.sheet.ocr_do("all_right", photo_id))
        self.all_ask.no.clicked.connect(lambda _=False: self.sheet.ocr_do("cancel_all_right", photo_id))
        for widget in (self.lines_title, self.guide, self.digits, self.notes, self.scroll, self.keys, self.tools, self.all_ask):
            box.addWidget(widget)
        for widget in (self.head, self.status, self.reread, self.none, self.result):
            layout.addWidget(widget)
        self.setVisible(False)

    # ---- 눌림(창에 넘긴다) ----
    def _read(self, size):
        self.sheet.ocr_do("read", self.photo_id, size)

    def line_do(self, name, *args):
        """줄에 하는 일 — 창이 core 에 묻고 다시 그린다 → 컨트롤러의 상태 이름."""
        return self.sheet.ocr_do(name, self.photo_id, *args)

    def clear_error(self):
        """받아들여지지 않은 일의 이유 문장을 지운다(고치기를 그만둘 때)."""
        return self.sheet.ocr_do("clear_error", self.photo_id)

    def stops(self):
        """Tab 정거장(보이는 순서) — 단추들 → 읽은 글 목록(하나) → 목록 아래 단추들 → 확인 줄의 단추들. 보이지 않거나 꺼진 것은 Qt 가 건너뛴다."""
        return [self.read_button, self.bigger_button, self.cancel_button, self.reread.yes, self.reread.no, self.lines, self.all_button, self.merge_button, self.undo_button, self.all_ask.yes, self.all_ask.no]

    def contains_focus(self):
        focus = QApplication.focusWidget()
        return focus is not None and (focus is self or self.isAncestorOf(focus))

    def _rescue(self, had):
        """포커스가 있던 부품이 사라졌거나 꺼졌으면 남은 부품으로 옮긴다 — 읽기를 시작하면 취소 단추로, 끝나면 목록(없으면 읽기 단추)으로."""
        if had is None or not (had is self or self.isAncestorOf(had)):
            return
        if had.isVisibleTo(self) and had.isEnabled():
            return
        for target in (self.cancel_button, self.lines, self.read_button, self.bigger_button, self.all_button):
            if target.isVisibleTo(self) and target.isEnabled():
                target.setFocus(Qt.OtherFocusReason)
                return

    # ---- 그리기 ----
    def apply(self, vm):
        had = QApplication.focusWidget()
        previous, self.vm = self.vm, vm
        if vm is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        read, bigger, cancel, status = vm["read"], vm["bigger"], vm["cancel"], vm["status"]
        self.title.set_text(vm["label"])
        self.hint.set_text(vm["hint"])
        for button, part in ((self.read_button, read), (self.bigger_button, bigger), (self.cancel_button, cancel)):
            button.setText(part["text"])
            button.setAccessibleName(part["a11y"])
        self.head.show_only([widget for widget, shown in ((self.title, True), (self.read_button, read["visible"]), (self.bigger_button, bigger["visible"]), (self.cancel_button, cancel["visible"]), (self.hint, True)) if shown])
        self.status.set_text(status["text"])
        self.status.set_tone(status["tone"])
        self.status.setVisible(bool(status["text"]))
        announce(self.status, status["a11y"], alert=status["state"] == "failed")
        asked = self.reread.apply(vm["ask_reread"])
        self.none.set_text(vm["none"])
        self.none.setVisible(bool(vm["none"]))
        lines = vm["lines"]
        self.result.setVisible(lines is not None)
        all_asked = False
        if lines is not None:
            self.lines_title.set_text(lines["title"])
            announce(self.lines_title, lines["title"], alert=previous is None or previous["lines"] is None)
            self.guide.set_text(lines["guide"])
            self.digits.set_text(lines["digits"])
            self.digits.setVisible(bool(lines["digits"]))
            self.notes.set_text("\n".join(lines["notes"]))
            self.notes.setVisible(bool(lines["notes"]))
            self.lines.apply(lines)
            self.scroll.content_changed()                                         # 줄 수가 달라졌으면 목록의 필요 높이도 달라졌다
            self.keys.set_text(lines["keys"])
            self.all_button.setText(lines["all"]["text"])
            self.all_button.setAccessibleName(lines["all"]["a11y"])
            self.all_button.setEnabled(lines["all"]["enabled"])
            self.merge_button.setText(lines["merge"]["text"])
            self.sync_merge()
            undo = lines["undo"]
            if undo is not None:
                self.undo_button.setText(undo["text"])
                self.undo_button.setAccessibleName(undo["a11y"])
                self.removed.set_text(lines["removed"])
            self.tools.show_only([widget for widget, shown in ((self.all_button, True), (self.merge_button, True), (self.undo_button, undo is not None), (self.removed, undo is not None)) if shown])
            all_asked = self.all_ask.apply(lines["ask_all"])
        else:
            self.lines.apply({"items": [], "enabled": True, "error": None})        # 줄이 하나도 없다 — 줄 위젯도 비운다
            self.all_ask.apply(None)
        if asked:
            self.reread.no.setFocus(Qt.OtherFocusReason)                      # 확인 줄이 뜨면 처음 포커스는 안전한 쪽(그만두기)
            self._reveal_later(self.reread)                                    # 프로그램으로 옮긴 포커스는 스크롤이 따라가지 않는다 — 새로 뜬 확인 줄이 보이는 곳 안에 오게 한다(독립 검증 Q QP-19). `asked`·`all_asked` 는 '이번에 새로 떴다' 라 이미 열려 있는 확인 줄은 다시 그릴 때 스크롤을 끌어오지 않는다
        elif all_asked:
            self.all_ask.no.setFocus(Qt.OtherFocusReason)
            self._reveal_later(self.all_ask)
        else:
            self._rescue(had)
        self.updateGeometry()

    def _reveal_later(self, widget):
        """새로 뜬 확인 줄을 몸·목록 스크롤 안의 보이는 곳으로 가져온다 — 배치가 자리를 잡은 뒤여야 높이가 맞아서 바로·조금 뒤·그다음 세 번 맞춘다(이미 보이면 아무것도 안 한다). 이미 열려 있는 확인 줄은 다시 그릴 때마다 스크롤을 끌어오지 않는다(새로 뜰 때만 부른다)."""
        for delay in ASK_REVEAL_DELAYS_MS:
            QTimer.singleShot(delay, lambda target=widget: self._reveal_if_shown(target))

    @staticmethod
    def _reveal_if_shown(widget):
        try:
            if widget.isVisible():
                reveal(widget)
        except RuntimeError:                                                  # 그 사이 화면이 다시 그려져 부품이 사라졌다
            pass

    def sync_merge(self):
        """`아래 줄과 합치기` 단추를 지금 고른 줄에 맞춘다 — 접근 이름은 고른 줄의 번호('읽은 글 2번째 줄을 아래 줄과 합치기')이고 마지막 줄은 아래 줄이 없어 꺼진다. 방향키·마우스로 고른 줄이 바뀔 때마다 부른다(다시 그리기를 기다리지 않는다)."""
        lines = None if self.vm is None else self.vm["lines"]
        if lines is None:
            return
        self.merge_button.setAccessibleName(lines["merge"]["a11y"].format(m=self.lines.current + 1))
        self.merge_button.setEnabled(lines["enabled"] and self.lines.current < lines["total"] - 1)

    def apply_status(self, status):
        """매초 바뀌는 상태 줄만 가볍게 바꾼다(전체를 다시 그리지 않는다) — 접근 이름은 상태가 바뀔 때만 바뀐다. 글의 줄 수가 달라졌으면 True(15초가 넘어 보조 글이 붙은 때 — 창이 키를 다시 맞춘다)."""
        if self.vm is None:
            return False
        grew = self.status.plain_text().count("\n") != status["text"].count("\n")
        self.vm["status"] = status
        self.status.set_text(status["text"])
        announce(self.status, status["a11y"], alert=status["state"] == "failed")
        return grew

    def handle_escape(self):
        """Esc — 이 칸에서 할 일이 있으면(고치기·확인 줄·읽는 중) 하고 True, 없으면 False(창이 닫힌다)."""
        if self.lines.cancel_edit():
            return True
        return bool(self.sheet.ocr_do("escape", self.photo_id))


__all__ = ["AskBar", "FlowRow", "LIST_MAX_HEIGHT", "LineEditor", "OcrBlock", "OcrLineRow", "OcrLines", "OcrScroll", "announce", "reveal"]
