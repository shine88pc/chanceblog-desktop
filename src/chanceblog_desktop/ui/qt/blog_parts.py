"""블로그 관리 화면의 부품(P4b) — 폼 칸(`FieldView`: 글·고르기·스위치·분야 칩·이미지 위치)·슬롯 카드(`SlotCard`)·알림 줄(`NoticeBar`)·폼 안쪽 스크롤(`FormScroll`)·색 프리셋 견본 아이콘.
화면(`blog_screen.py`)은 뷰모델(`ui/core/blogs_view.py` 가 만든 딕셔너리)을 이 부품으로 조립하기만 하고, 부품은 공통 부품(`components.py`)만 쓴다. 색·글꼴·크기는 토큰(스타일시트)에서만 오고 여기서 인라인 스타일·직접 색·글꼴 이름·고정 크기를 쓰지 않는다
(속성 `slot`·`preset`·`selected`·`invalid`·`notice`·`chbadge` 만 붙이면 스타일시트가 입힌다). 모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다.

폼 칸은 **고치는 동안 다시 그리지 않는다**: 글자를 칠 때마다 화면 전체를 다시 만들면 입력 중이던 자리(커서·한글 조합)가 사라지므로, 칸은 `update_from(뷰모델)` 로 오류 글·경고·꺼짐·값만 그 자리에서 바꾼다(값이 이미 같으면 건드리지 않는다).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from . import theme

NOTICE_ICONS = {"ok": "check_circle", "info": "info_circle", "warning": "alert", "error": "alert"}


# ---- 색 프리셋 견본(칩의 아이콘) ----------------------------------------------------------------------------------------------------------
class SwatchIconEngine(QIconEngine):
    """프리셋의 색 셋(Primary·Secondary·Accent)을 나란한 네모로 그린다 — '정하지 않음' 은 속이 빈 네모. 요청된 크기에 맞춰 그릴 때마다 그려 어느 배율에서도 선명하다. 색은 토큰의 프리셋 표에서만 온다."""

    def __init__(self, preset):
        super().__init__()
        self._preset = preset

    def paint(self, painter, rect, mode, state):
        colors, base = K.preset_colors(self._preset), theme.colors()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        area = QRectF(rect)
        if colors is None:
            painter.setPen(QPen(QColor(base["border_strong"]), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(area.adjusted(1, 1, -1, -1), 3, 3)
        else:
            gap = max(1.0, area.width() / 24)
            side = (area.width() - 2 * gap) / 3
            painter.setPen(QPen(QColor(base["surface"]), 1))
            for index, name in enumerate(("primary", "secondary", "accent")):
                painter.setBrush(QColor(colors[name]))
                painter.drawRoundedRect(QRectF(area.left() + index * (side + gap), area.top() + 1, side, area.height() - 2), 3, 3)
        painter.restore()

    def pixmap(self, size, mode, state):
        image = QPixmap(size)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        self.paint(painter, image.rect(), mode, state)
        painter.end()
        return image

    def clone(self):
        return SwatchIconEngine(self._preset)


def swatch_icon(preset):
    return QIcon(SwatchIconEngine(preset or ""))


# ---- 알림 줄·슬롯 카드·폼 스크롤 ----------------------------------------------------------------------------------------------------------
class NoticeBar(QFrame):
    """마지막 동작의 결과 한 줄 — 수준(`ok` 저장했어요 · `info` · `warning` · `error`)마다 바탕이 다르고 아이콘과 글이 늘 함께 있다(색만으로 알리지 않는다)."""

    def __init__(self, level, text):
        super().__init__()
        self.level = level if level in NOTICE_ICONS else "info"
        self.setProperty("notice", self.level)
        self.setAccessibleName(text)
        row = QHBoxLayout(self)
        row.setContentsMargins(K.SPACE["4"], K.SPACE["3"], K.SPACE["4"], K.SPACE["3"])
        row.setSpacing(K.SPACE["3"])
        colors = theme.colors()
        tone = {"ok": "success_text", "info": "info_text", "warning": "warning_text", "error": "danger_text"}[self.level]
        row.addWidget(theme.IconWidget(NOTICE_ICONS[self.level], colors[tone], K.ICON["button"]), 0, Qt.AlignTop)
        self.text = UI.label(text, "body", wrap=True)
        row.addWidget(self.text, 1)


class SlotCard(UI.Pressable):
    """슬롯 카드 — 종류·이름·상태·블로그 ID 한 줄·칩(언어·후보 만들기·저장 전 변경)·색 프리셋 이름. 전체가 누르는 칸이고(Enter·Space 도 된다) 선택은 2px 테두리, 채널 색은 왼쪽 줄·테두리·배지에만 쓴다.
    빈 슬롯은 '등록' 카드로 보인다(블로그를 등록해 보세요 + 눌러서 이름과 블로그 ID 를 넣어요)."""

    def __init__(self, vm):
        super().__init__(vm["a11y"])
        self.key = vm["key"]
        self.setProperty("slot", "true")
        self.setProperty("focus_key", "slot:" + vm["key"])
        self._layout = QVBoxLayout(self)                                                      # 최소 높이를 따로 정하지 않는다 — 정하면 배치가 안쪽 부품의 필요 높이를 무시하고 카드를 그 값까지 눌러 배지가 잘린다
        self._layout.setContentsMargins(K.SPACE["4"], K.SPACE["3"], K.SPACE["3"], K.SPACE["3"])
        self._layout.setSpacing(K.SPACE["1"])
        self._layout.addStretch(1)                                                            # 같은 줄의 옆 카드가 더 길어 카드가 늘어나도 남는 높이는 아래로 간다(배지가 위아래로 늘어나지 않게)
        self._parts = []
        self._signature = None
        self.update_from(vm)

    def update_from(self, vm):
        """뷰모델에 맞게 카드 안을 다시 짠다(선택·저장 전 변경이 바뀔 때만 — 칸을 칠 때마다 다섯 카드를 다시 짜지 않는다)."""
        signature = (vm["selected"], vm["unsaved"], vm["headline"], vm["sub"], vm["meta"], vm["role"], vm["preset"], vm["a11y"], vm["status"]["text"])
        if signature == self._signature:
            return
        self._signature = signature
        for part in self._parts:
            self._layout.removeWidget(part)
            part.deleteLater()
        self._parts = []
        self.setAccessibleName(vm["a11y"])
        self.setProperty("selected", bool(vm["selected"]))
        self.setProperty("preset", vm["preset"])
        top = QWidget()
        row = QHBoxLayout(top)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(K.SPACE["2"])
        row.addWidget(UI.label(vm["title"], "caption"), 1)
        if vm["unsaved"]:
            row.addWidget(UI.Badge("warning", T["blogs_status_unsaved"]))
        row.addWidget(UI.Badge(vm["status"]["tone"], vm["status"]["text"]))
        parts = [top, UI.ElidedLabel(vm["headline"], "h3" if vm["registered"] else "body_lg"), UI.ElidedLabel(vm["sub"], "caption")]
        if vm["meta"]:
            parts.append(UI.ElidedLabel(vm["meta"], "caption"))
        if vm["role"]:
            parts.append(UI.ElidedLabel(vm["role"], "caption"))                               # 채널 역할(없으면 주요 주제 앞 셋) 한 줄 — 카드만 보고도 이 블로그가 무엇을 다루는지 안다
        for index, part in enumerate(parts):
            self._layout.insertWidget(index, part)
        self._parts = parts
        UI.repolish(self)


class FormScroll(QScrollArea):
    """폼 칸들이 들어가는 안쪽 스크롤 — 아래 고정 행동 줄은 이 밖에 있어 칸이 많아도 늘 보인다. 가로 스크롤은 없다(좁으면 칸이 줄어든다). 포커스가 간 칸은 Qt 가 보이는 곳으로 스크롤한다."""

    def __init__(self, content):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumHeight(K.LAYOUT["form_scroll_min_h"])
        self.setWidget(content)
        self.setFocusPolicy(Qt.NoFocus)

    def sizeHint(self):
        """기본 크기는 안쪽 내용의 높이가 아니라 **최소 높이**다 — 줄바꿈 글이 있는 화면의 배치는 '바깥' 스크롤 영역에 맞는 높이를 부분 크기(`sizeHint`)로 합쳐 구하므로, 내용 높이를 주면 페이지가 창보다 길어져
        바깥 스크롤이 생기고 아래 고정 행동 줄이 밀려난다. 남는 자리는 늘어나는 크기 정책으로 채운다."""
        return QSize(super().sizeHint().width(), K.LAYOUT["form_scroll_min_h"])


# ---- 폼 칸 ---------------------------------------------------------------------------------------------------------------------------
class FieldView(QWidget):
    """폼 칸 하나 — 이름(+ 필수 표시)·입력 부품·안내·경고·오류. 종류(`line`·`ref`·`words`·`path`·`choice`·`multi`·`flag`)마다 입력 부품이 다르다. 고칠 때마다 `edited(칸 이름, 값)`·`picked(칸 이름)`·`toggled_tag(분야)` 신호가 나간다."""
    edited = Signal(str, object)
    picked = Signal(str)
    toggled_tag = Signal(str)

    def __init__(self, vm):
        super().__init__()
        self.name, self.kind = vm["name"], vm["kind"]
        self.controls = []
        self.edit = self.pick = self.clear_button = self.toggle = None
        self.chips = {}
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(K.SPACE["1"])
        head = QHBoxLayout()
        head.setSpacing(K.SPACE["2"])
        self.label = UI.label(vm["label"], "small")
        head.addWidget(self.label)
        if vm["required_text"]:
            head.addWidget(UI.Badge("info", vm["required_text"]))
        head.addStretch(1)
        column.addLayout(head)
        self._build(column, vm)
        self._column, self._lazy = column, {}
        self.hint = UI.label(vm["hint"], "caption", wrap=True)
        column.addWidget(self.hint)
        self.setAccessibleName(vm["label"])
        self.update_from(vm)

    def _lazy_row(self, kind):
        """주의·오류 줄과 '목록에 없는 분야' 글은 **처음 필요할 때** 만든다 — 칸 열다섯 × 셋이 거의 늘 숨어 있는데, 숨은 부품도 만들고 붙이는 값은 든다(화면을 다시 그리는 시간의 큰 몫). 만든 뒤에는 보이고 숨기기만 한다."""
        if kind not in self._lazy:
            if kind == "extra":
                row = text = UI.label("", "caption", wrap=True)
            else:
                text, row = self._message("alert", "orange" if kind == "warning" else "red")
            row.setVisible(False)
            self._column.addWidget(row)
            self._lazy[kind] = (text, row)
        return self._lazy[kind]

    @property
    def extra(self):
        return self._lazy_row("extra")[0]

    @property
    def warning(self):
        return self._lazy_row("warning")[0]

    @property
    def warning_row(self):
        return self._lazy_row("warning")[1]

    @property
    def error(self):
        return self._lazy_row("error")[0]

    @property
    def error_row(self):
        return self._lazy_row("error")[1]

    def _show_lazy(self, kind, message, visible):
        """줄이 이미 있거나 보일 일이 있을 때만 건드린다(없는데 숨길 일이면 만들지도 않는다)."""
        if kind in self._lazy or visible:
            text, row = self._lazy_row(kind)
            text.set_text(message)
            row.setVisible(visible)

    def _message(self, icon, tone):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(K.SPACE["2"])
        colors = theme.colors()
        layout.addWidget(theme.IconWidget(icon, colors["warning_text" if tone == "orange" else "danger_text"], K.ICON["badge"]), 0, Qt.AlignTop)
        text = UI.label("", "small", wrap=True)
        text.set_tone(tone)
        layout.addWidget(text, 1)
        return text, row

    def _focus_key(self, suffix=""):
        return f"blogs:field:{self.name}{suffix}"

    def _build(self, column, vm):
        label = vm["label"]
        if self.kind in ("line", "ref", "words"):
            self.edit = UI.TextInput(label, vm["placeholder"])
            self.edit.setProperty("focus_key", self._focus_key())
            self.edit.textEdited.connect(lambda text: self.edited.emit(self.name, text))
            column.addWidget(self.edit)
            self.controls = [self.edit]
        elif self.kind == "path":
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(K.SPACE["2"])
            self.edit = UI.TextInput(label, vm["placeholder"])
            self.edit.setProperty("focus_key", self._focus_key())
            self.edit.textEdited.connect(lambda text: self.edited.emit(self.name, text))
            self.pick = UI.Button("secondary", T["bf_pick"], "folder", accessible=T["bf_pick_a11y"].format(label=label), focus_key=self._focus_key(":pick"))
            self.pick.clicked.connect(lambda: self.picked.emit(self.name))
            self.clear_button = UI.Button("ghost", T["bf_clear"], accessible=T["bf_clear_a11y"].format(label=label), focus_key=self._focus_key(":clear"))
            self.clear_button.clicked.connect(lambda: self.edited.emit(self.name, ""))
            for widget, stretch in ((self.edit, 1), (self.pick, 0), (self.clear_button, 0)):
                row.addWidget(widget, stretch)
            column.addWidget(box)
            self.controls = [self.edit, self.pick, self.clear_button]
        elif self.kind == "choice":
            group = QButtonGroup(self)
            group.setExclusive(True)
            for option in vm["options"]:
                chip = UI.FilterChip(option["label"], None, option["value"] == vm["value"] or (option["value"] == "" and not vm["value"]), focus_key=self._focus_key(":" + (option["value"] or "none")))
                chip.setAccessibleName(f"{label}: {option['label']}")
                if "preset" in option:
                    chip.setIcon(swatch_icon(option["preset"]))
                    chip.setIconSize(QSize(K.SIZE["control"] - 4, K.ICON["badge"]))
                group.addButton(chip)
                chip.clicked.connect(lambda _=False, value=option["value"]: self.edited.emit(self.name, value))
                self.chips[option["value"]] = chip
            column.addWidget(UI.chip_row(list(self.chips.values())))
            self.controls = list(self.chips.values())
            self._tab_stop()
        elif self.kind == "multi":
            for option in vm["options"]:
                chip = UI.FilterChip(option["label"], None, option["value"] in vm["value"], focus_key=self._focus_key(":" + option["value"]))
                chip.setAccessibleName(f"{label}: {option['label']}")
                chip.clicked.connect(lambda _=False, tag=option["value"]: self.toggled_tag.emit(tag))
                self.chips[option["value"]] = chip
            column.addWidget(UI.chip_row(list(self.chips.values())))
            self.controls = list(self.chips.values())
        elif self.kind == "flag":
            self.toggle = UI.Toggle(T["bf_on" if vm["value"] else "bf_off"], accessible=label)
            self.toggle.setProperty("focus_key", self._focus_key())
            self.toggle.toggled.connect(self._on_toggle)
            holder = QHBoxLayout()
            holder.addWidget(self.toggle)
            holder.addStretch(1)
            column.addLayout(holder)
            self.controls = [self.toggle]

    def _tab_stop(self):
        """하나만 고르는 칩 묶음은 **고른 칩만** Tab 정거장이고 나머지는 화살표 키로 옮긴다(라디오 묶음 규칙) — Qt 의 기본은 묶음의 첫 칩이라 지금 고른 것과 다를 수 있어 직접 맞춘다(Tab 으로 들어가 Space 를 눌러도 값이 바뀌지 않는다)."""
        for chip in self.chips.values():
            chip.setFocusPolicy(Qt.StrongFocus if chip.isChecked() else Qt.ClickFocus)

    def _on_toggle(self, checked):
        self.toggle.setText(T["bf_on" if checked else "bf_off"])
        self.edited.emit(self.name, bool(checked))

    # ---- 뷰모델에 맞추기(다시 그리지 않고 그 자리에서) ----
    def update_from(self, vm):
        value = vm["value"]
        if self.edit is not None and self.edit.text() != (value or ""):
            self.edit.setText(value or "")                                                    # 코드로 바꾼 값(이미지 고르기·지우기) — 사용자가 친 글과 같으면 건드리지 않아 커서가 안 튄다
        if self.kind == "choice":
            target = self.chips.get(value or "")
            if target is not None and not target.isChecked():
                target.setChecked(True)
            self._tab_stop()
        elif self.kind == "multi":
            for tag, chip in self.chips.items():
                chip.setChecked(tag in value)
        elif self.kind == "flag" and self.toggle.isChecked() != bool(value):
            blocked = self.toggle.blockSignals(True)
            self.toggle.setChecked(bool(value))
            self.toggle.setText(T["bf_on" if value else "bf_off"])
            self.toggle.blockSignals(blocked)
        self.hint.set_text(vm["disabled_reason"] or vm["hint"])
        self.hint.setVisible(bool(vm["disabled_reason"] or vm["hint"]))
        self._show_lazy("extra", vm["extra"], bool(vm["extra"]))
        self._show_lazy("warning", vm["warning"], bool(vm["warning"]) and not vm["error"])
        self._show_lazy("error", vm["error"], bool(vm["error"]))
        description = vm["error"] or vm["warning"] or vm["disabled_reason"] or vm["hint"]
        for control in self.controls:
            control.setEnabled(not vm["disabled"])
            control.setAccessibleDescription(description)
        if self.edit is not None:
            self.edit.setProperty("invalid", bool(vm["error"]))
            UI.repolish(self.edit)
        if self.clear_button is not None:
            self.clear_button.setEnabled(not vm["disabled"] and bool(value))
