"""'사진 정리' 창의 Qt 부품(사진 연동 2단계, 결정 D-499) — 사진 한 줄(`PhotoRowCard`)과 글 칸 묶음(`FieldBox`). 뷰모델(`ui/core/photo_view.py` 의 `PhotoBoard.view` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 그리기만 한다 —
규칙(한도·확인이 풀리는 때·종류별 예시·기본 들어갈 곳·큰 PNG 판정)은 모두 core 에 있다. 색·글꼴·크기·간격은 토큰(`K`·스타일시트)에서만 오고 여기서 인라인으로 정하지 않는다.
이 파일에는 파일을 읽거나 쓰는 호출·네트워크·하위 프로세스·표준 출력이 없다(미리보기 그림은 창(`photo_screen.py`)이 `imagecheck` 로 메모리에서만 만들어 넘긴다).

**입력 칸(이 사진은 무엇인가요? · 한마디 메모)은 접지 않고 늘 보인다**(운영자 요구). 종류·장소 분위기도 늘 보이고, 들어갈 곳·자리·설명 글만 '자리 정하기' 로 접는다(값이 있으면 펼쳐 둔다).
줄은 **사진이 지워지기 전까지 같은 부품**이다 — 창이 다시 그릴 때(`apply`) 칸의 글을 덮어쓰지 않고(포커스가 있거나 한도를 넘겨 반영하지 못한 글은 그대로), 클릭한 칸이 사라져 포커스를 잃는 일이 없다.
글자 수(`12/60`)는 치는 동안 그 자리에서 바뀌고 한도를 넘으면 글(`60자까지만 적을 수 있어요`)로도 알린다(색만으로 알리지 않는다). 모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core import photo_rules as rules
from ..core import tokens as K
from . import components as UI

TONE = {"ok": "green", "warn": "orange", "muted": "slate", "error": "red", "info": "slate"}       # 뷰모델의 상태 말 → 글 색 계열(글이 늘 함께 있다)
PREVIEW_SIDE = rules.THUMB_SIDE


def _clean_length(text):
    """칸에 친 글이 규칙의 한 줄 정리(`clean_line`)를 거친 뒤 몇 글자인가 — 글자 수 표시용 근사(공백을 접는다)."""
    return len(" ".join(str(text).split()))


class FieldBox(QWidget):
    """글 칸 하나 — 이름표·입력 칸·글자 수·한도 넘음/거절 이유. 입력은 `editingFinished`(Enter·다른 칸으로 가기)에서 한 번 규칙에 넘기고, 치는 동안은 글자 수만 바꾼다."""

    def __init__(self, sheet, photo_id, vm, focus_prefix):
        super().__init__()
        self.sheet, self.photo_id, self.name, self.limit = sheet, photo_id, vm["name"], vm["limit"]
        self.invalid = False                                                           # 한도를 넘기거나 검사에 걸려 반영하지 못한 글이 칸에 있다
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(K.SPACE["1"])
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(K.SPACE["2"])
        self.title = UI.label(vm["label"], "small")
        self.count = UI.label("", "caption")
        self.count.setAlignment(Qt.AlignRight)
        head.addWidget(self.title, 1)
        head.addWidget(self.count, 0)
        layout.addLayout(head)
        self.edit = UI.TextInput(vm["a11y"], placeholder=vm["example"])
        self.edit.setProperty("focus_key", f"{focus_prefix}:{photo_id}")
        self.edit.textChanged.connect(self._live)
        self.edit.editingFinished.connect(self.commit)
        layout.addWidget(self.edit)
        self.error = UI.label("", "small", wrap=True)
        self.error.set_tone("red")
        self.error.setVisible(False)
        layout.addWidget(self.error)
        self.apply(vm)

    def _live(self, text=""):
        """치는 동안 — 글자 수와 한도 넘음 안내만 그 자리에서 바꾼다(규칙에는 넘기지 않는다)."""
        length = _clean_length(self.edit.text())
        self.count.set_text(rules.count_text(length, self.limit))
        self.count.set_tone("red" if rules.over_limit(length, self.limit) else "slate")
        over = rules.over_text(length, self.limit)
        if over:
            self.error.set_text(over)
            self.error.setVisible(True)
        elif not self.invalid:
            self.error.setVisible(False)

    def commit(self):
        """칸의 글을 한 번 규칙에 넘긴다 — 반영되면 정리한 글로 칸을 다시 채우고(포커스가 옮겨 간 뒤) 거절되면 칸의 글은 그대로 두고 이유만 보인다."""
        self.sheet.commit_text(self.photo_id, self.name, self.edit.text())

    def apply(self, vm):
        self.title.set_text(vm["label"])
        self.edit.setAccessibleName(vm["a11y"])
        self.edit.setPlaceholderText(vm["example"])
        self.invalid = bool(vm["error"])
        if not self.invalid and not self.edit.hasFocus() and self.edit.text() != vm["value"]:
            self.edit.blockSignals(True)
            self.edit.setText(vm["value"])                                             # 반영된 글(정리한 모양)로 — 거절돼 남은 글·치고 있는 글은 건드리지 않는다
            self.edit.blockSignals(False)
        self._live()
        if vm["error"]:
            self.error.set_text(vm["error"])
            self.error.setVisible(True)
        elif not rules.over_text(_clean_length(self.edit.text()), self.limit):
            self.error.setVisible(False)

    def differs(self, vm):
        """칸의 글이 반영된 글과 다른가(닫기 전에 마지막으로 넘길 글이 있나)."""
        return " ".join(self.edit.text().split()) != vm["value"]


class PhotoRowCard(QWidget):
    """사진 한 줄 — 미리보기·번호·파일 이름·파일 상태·순서/지우기·종류·장소 분위기·대상·메모·자리 정하기(들어갈 곳·자리·몇 번째·설명 글)·확인 표시."""

    def __init__(self, sheet, vm):
        super().__init__()
        self.sheet, self.photo_id, self.vm = sheet, vm["photo_id"], vm
        self._chip_keys = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card, inner = UI.Card((K.SPACE["4"], K.SPACE["3"], K.SPACE["4"], K.SPACE["3"]), kind="plain")
        inner.setSpacing(K.SPACE["3"])
        outer.addWidget(card)
        self.card = card
        self.setAccessibleName(vm["a11y"])
        self._build_head(inner, vm)
        self.types_host = self._host(inner)
        self.settings_host = self._host(inner)
        self.subject = FieldBox(sheet, self.photo_id, vm["subject"], "pho:subject")
        self.note = FieldBox(sheet, self.photo_id, vm["note"], "pho:note")
        inner.addWidget(self.subject)
        inner.addWidget(self.note)
        self._build_place(inner, vm)
        self._build_confirm(inner, vm)
        self.apply(vm)

    @staticmethod
    def _host(layout):
        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(K.SPACE["1"])
        layout.addWidget(host)
        return host

    # ---- 만들기 ----
    def _build_head(self, inner, vm):
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(K.SPACE["3"])
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_SIDE + K.SPACE["2"], PREVIEW_SIDE + K.SPACE["2"])
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setProperty("role", "caption")
        top.addWidget(self.preview, 0, Qt.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(K.SPACE["1"])
        self.number = UI.label("", "h3", wrap=True)
        self.file_name = UI.label("", "caption", wrap=True)
        self.badge = UI.label("", "small", wrap=True)
        self.file_warning = UI.label("", "caption", wrap=True)
        self.file_warning.set_tone("orange")
        self.preview_note = UI.label("", "caption", wrap=True)
        self.preview_note.set_tone("orange")
        self.relink = UI.Button("secondary", vm["file"]["relink_text"], size="sm", accessible=vm["file"]["relink_a11y"], focus_key=f"pho:relink:{self.photo_id}")
        self.relink.clicked.connect(lambda _=False: self.sheet.relink(self.photo_id))
        for widget in (self.number, self.file_name, self.badge, self.file_warning, self.preview_note):
            info.addWidget(widget)
        info.addWidget(self.relink, 0, Qt.AlignLeft)
        info.addStretch(1)
        top.addLayout(info, 1)
        actions = QVBoxLayout()
        actions.setSpacing(K.SPACE["1"])
        self.up = UI.Button("ghost", vm["up"]["text"], size="sm", accessible=vm["up"]["a11y"], focus_key=f"pho:up:{self.photo_id}")
        self.down = UI.Button("ghost", vm["down"]["text"], size="sm", accessible=vm["down"]["a11y"], focus_key=f"pho:down:{self.photo_id}")
        self.remove = UI.Button("danger_ghost", vm["remove"]["text"], size="sm", accessible=vm["remove"]["a11y"], focus_key=f"pho:remove:{self.photo_id}")
        self.up.clicked.connect(lambda _=False: self.sheet.act("move", self.photo_id, -1))
        self.down.clicked.connect(lambda _=False: self.sheet.act("move", self.photo_id, 1))
        self.remove.clicked.connect(lambda _=False: self.sheet.act("remove", self.photo_id))
        for button in (self.up, self.down, self.remove):
            actions.addWidget(button)
        actions.addStretch(1)
        top.addLayout(actions, 0)
        inner.addLayout(top)

    def _build_place(self, inner, vm):
        place = vm["place"]
        self.place_toggle = UI.Button("ghost", place["close_text"] if place["open"] else place["open_text"], size="sm", accessible=place["a11y"], focus_key=f"pho:place:{self.photo_id}")
        self.place_toggle.clicked.connect(lambda _=False: self.set_place_open(not self.place_body.isVisible()))
        inner.addWidget(self.place_toggle, 0, Qt.AlignLeft)
        self.place_body = QWidget()
        body = QVBoxLayout(self.place_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(K.SPACE["3"])
        self.section_host = self._host(body)
        self.kind_host = self._host(body)
        nth = QHBoxLayout()
        nth.setContentsMargins(0, 0, 0, 0)
        nth.setSpacing(K.SPACE["2"])
        self.nth_label = UI.label(place["nth"]["label"], "small")
        self.nth_less = UI.Button("secondary", place["nth"]["less"], size="sm", accessible=place["nth"]["less_a11y"], focus_key=f"pho:nthless:{self.photo_id}")
        self.nth_value = UI.label("", "body")
        self.nth_more = UI.Button("secondary", place["nth"]["more"], size="sm", accessible=place["nth"]["more_a11y"], focus_key=f"pho:nthmore:{self.photo_id}")
        self.nth_less.clicked.connect(lambda _=False: self.sheet.act("step_nth", self.photo_id, -1))
        self.nth_more.clicked.connect(lambda _=False: self.sheet.act("step_nth", self.photo_id, 1))
        self.nth_box = QWidget()
        nth_row = QHBoxLayout(self.nth_box)
        nth_row.setContentsMargins(0, 0, 0, 0)
        nth_row.setSpacing(K.SPACE["2"])
        for widget in (self.nth_label, self.nth_less, self.nth_value, self.nth_more):
            nth_row.addWidget(widget)
        nth_row.addStretch(1)
        body.addWidget(self.nth_box)
        self.caption = FieldBox(self.sheet, self.photo_id, vm["caption"], "pho:caption")
        body.addWidget(self.caption)
        inner.addWidget(self.place_body)
        self.place_body.setVisible(bool(place["open"]))

    def _build_confirm(self, inner, vm):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(K.SPACE["2"])
        self.confirm_box = UI.CheckBox(vm["confirm"]["a11y"])
        self.confirm_box.setProperty("focus_key", f"pho:confirm:{self.photo_id}")
        self.confirm_box.toggled.connect(lambda on: self.sheet.act("confirm", self.photo_id, bool(on)))
        self.confirm_text = UI.label(vm["confirm"]["text"], "body", wrap=True)
        self.confirm_status = UI.label("", "small")
        row.addWidget(self.confirm_box, 0)
        row.addWidget(self.confirm_text, 1)
        row.addWidget(self.confirm_status, 0)
        inner.addLayout(row)
        self.changed_note = UI.label("", "small", wrap=True)
        self.changed_note.set_tone("orange")
        inner.addWidget(self.changed_note)

    # ---- 그리기 ----
    def _fill_chips(self, host, kind, title, items, current, handler, focus_prefix, a11y):
        """칩 줄 — 고를 이름이 바뀌었을 때만 다시 만들고, 그 밖에는 고른 표시만 바꾼다(칩이 사라져 포커스를 잃는 일이 없게)."""
        key = tuple(items)
        layout = host.layout()
        if self._chip_keys.get(kind) != key:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()
            layout.addWidget(UI.label(title, "small"))
            chips = {}
            for value, text in items:
                chip = UI.FilterChip(text, None, value == current, focus_key=f"{focus_prefix}:{self.photo_id}:{value}")
                chip.setAccessibleName(f"{a11y} {text}")
                chip.clicked.connect(lambda _=False, chosen=value: handler(chosen))
                chips[value] = chip
            layout.addWidget(UI.chip_row(list(chips.values())))
            self._chip_keys[kind] = key
            setattr(self, f"_chips_{kind}", chips)
        for value, chip in getattr(self, f"_chips_{kind}").items():
            chip.setChecked(value == current)

    def set_place_open(self, opened):
        self.place_body.setVisible(bool(opened))
        place = self.vm["place"]
        self.place_toggle.setText(place["close_text"] if opened else place["open_text"])

    def apply(self, vm):
        """뷰모델에 맞게 줄을 바꾼다 — 칸의 글은 `FieldBox.apply` 가 지키고, 칩·배지·단추만 그 자리에서 바꾼다."""
        self.vm = vm
        self.setAccessibleName(vm["a11y"])
        self.number.set_text(vm["label"])
        self.file_name.set_text(vm["file_name"])
        file = vm["file"]
        self.badge.set_text(file["badge"])
        self.badge.set_tone(TONE.get(file["tone"], "slate"))
        self.badge.setAccessibleName(file["a11y"])
        self.file_warning.set_text(file["warning"])
        self.file_warning.setVisible(bool(file["warning"]))
        self.relink.setVisible(bool(file["relink"]))
        self.relink.setAccessibleName(file["relink_a11y"])
        preview = vm["preview"]
        self.preview_note.set_text(preview["blocked_text"] if preview["blocked"] else "")
        self.preview_note.setVisible(preview["blocked"])
        self.preview.setAccessibleName(preview["a11y"])
        if preview["blocked"]:
            self.preview.clear()                                                       # 큰 PNG 는 그림을 만들지 않는다 — 글만 보인다
            self.preview.setText(preview["blocked_text"])
        self.up.setEnabled(vm["up"]["enabled"])
        self.down.setEnabled(vm["down"]["enabled"])
        self._fill_chips(self.types_host, "type", vm["type"]["label"], [(name, name) for name in vm["type"]["choices"]], vm["type"]["value"], lambda value: self.sheet.act("set_type", self.photo_id, value),
                         "pho:type", vm["type"]["a11y"])
        self._fill_chips(self.settings_host, "setting", vm["setting"]["label"], list(vm["setting"]["choices"]), vm["setting"]["value"], lambda value: self.sheet.act("set_setting", self.photo_id, value),
                         "pho:setting", vm["setting"]["a11y"])
        self.subject.apply(vm["subject"])
        self.note.apply(vm["note"])
        place = vm["place"]
        self._fill_chips(self.section_host, "section", place["section"]["label"], list(place["section"]["choices"]), place["section"]["value"], lambda value: self.sheet.act("set_section", self.photo_id, value),
                         "pho:section", place["section"]["a11y"])
        self._fill_chips(self.kind_host, "kind", place["kind"]["label"], list(place["kind"]["choices"]), place["kind"]["value"], lambda value: self.sheet.act("set_placement", self.photo_id, value),
                         "pho:kind", place["kind"]["a11y"])
        self.nth_box.setVisible(bool(place["nth"]["visible"]))
        self.nth_value.set_text(place["nth"]["text"])
        self.caption.apply(vm["caption"])
        if not self.place_body.isVisible() and place["open"]:
            self.set_place_open(True)                                                  # 값이 생겼으면 펼친다(접는 것은 사용자가 한다)
        self.confirm_box.blockSignals(True)
        self.confirm_box.setChecked(bool(vm["confirmed"]))
        self.confirm_box.blockSignals(False)
        self.confirm_box.setAccessibleName(vm["confirm"]["a11y"])
        self.confirm_status.set_text(vm["confirm"]["status"])
        self.confirm_status.set_tone("green" if vm["confirmed"] else "slate")
        self.changed_note.set_text(vm["changed_note"])
        self.changed_note.setVisible(bool(vm["changed_note"]))

    def set_preview(self, pixmap):
        """미리보기 그림(메모리에서만 만든 것) — 없으면 안내 글."""
        if pixmap is None:
            self.preview.setText(self.vm["preview"]["failed_text"])
            return
        self.preview.setText("")
        self.preview.setPixmap(pixmap)

    def show_waiting(self):
        self.preview.setText(self.vm["preview"]["wait_text"])

    def fields(self):
        return (self.subject, self.note, self.caption)

    def stops(self):
        """Tab 정거장(화면에 보이는 순서) — 줄 머리의 단추들 → 종류 칩 → 장소 분위기 칩 → 대상 → 메모 → 자리 정하기(펼쳤을 때만 그 안) → 확인했어요. 보이지 않거나 꺼진 것은 Qt 가 건너뛴다."""
        chips = [*getattr(self, "_chips_type", {}).values(), *getattr(self, "_chips_setting", {}).values()]
        place = [*getattr(self, "_chips_section", {}).values(), *getattr(self, "_chips_kind", {}).values(), self.nth_less, self.nth_more, self.caption.edit]
        return [self.relink, self.up, self.down, self.remove, *chips, self.subject.edit, self.note.edit, self.place_toggle, *place, self.confirm_box]

    def pending_fields(self):
        """닫기 전에 마지막으로 규칙에 넘길 글이 든 칸들."""
        pairs = ((self.subject, self.vm["subject"]), (self.note, self.vm["note"]), (self.caption, self.vm["caption"]))
        return [box for box, vm in pairs if box.differs(vm) and not box.invalid]
