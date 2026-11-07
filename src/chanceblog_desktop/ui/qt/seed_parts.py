"""Seed 관리 화면의 부품 — Seed 줄(`SeedRow`: 고르는 상자 + 눌러서 상세를 여는 줄)·줄 목록(`SeedList`)·서랍의 폼 칸(`SeedFieldView` — 블로그 관리의 `FieldView` 를 그대로 쓰되 포커스 이름만 다르다).
화면(`seed_screen.py`)은 뷰모델(`ui/core/seeds_view.py` 가 만든 딕셔너리)을 이 부품으로 조립하기만 하고, 부품은 공통 부품(`components.py`)만 쓴다. 색·글꼴·크기는 토큰(스타일시트)에서만 오고 여기서 인라인 스타일·직접 색·글꼴 이름을 쓰지 않는다
(속성 `seedrow`·`checked`·`selected` 만 붙이면 스타일시트가 입힌다). 모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다.
상태는 **색만이 아니라 글자로도** 보인다(상태 배지 — `제안(승인 전)`·`사용 중`·`쉬는 중`).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .blog_parts import FieldView


class SeedFieldView(FieldView):
    """서랍의 폼 칸 — 블로그 관리의 칸 부품과 같고 포커스 이름(`seeds:field:…`)만 다르다."""

    def _focus_key(self, suffix=""):
        return f"seeds:field:{self.name}{suffix}"


class SeedRow(UI.Pressable):
    """Seed 한 줄 — 고르는 상자(일괄 변경용)·낱말·`대분류 › 중분류`·상태 배지(글자)·소속·중요도·대상 유형·허용 채널·표시들. 줄 전체가 누르는 칸이고(Enter·Space 도 된다) 누르면 상세 서랍이 열린다.
    상자는 따로 누르는 칸이라 줄을 열지 않고 고르기만 한다. 서랍이 열린 줄은 2px 파란 테두리, 고른 줄은 옅은 파랑 바탕이다."""
    checked = Signal(str)

    def __init__(self, vm):
        super().__init__(vm["a11y"])
        self.seed_id = vm["id"]
        self.setProperty("seedrow", "true")
        self.setProperty("focus_key", "seed:" + vm["id"])
        self.setAccessibleDescription(T["seeds_row_open_hint"])
        row = QHBoxLayout(self)
        row.setContentsMargins(K.SPACE["2"], K.SPACE["2"], K.SPACE["4"], K.SPACE["2"])
        row.setSpacing(K.SPACE["2"])
        self.box = UI.CheckBox(vm["check_a11y"])
        self.box.setProperty("focus_key", "seedcheck:" + vm["id"])
        self.box.toggled.connect(lambda _on: self.checked.emit(self.seed_id))
        row.addWidget(self.box, 0, Qt.AlignTop)
        body = QVBoxLayout()
        body.setSpacing(K.SPACE["1"])
        top = QHBoxLayout()
        top.setSpacing(K.SPACE["2"])
        self.title = UI.ElidedLabel(vm["title"], "h3")
        top.addWidget(self.title, 1)
        self.badges = []
        for kind, text in ((vm["status"]["tone"], vm["status"]["text"]), *((("warning", vm["idle_text"]),) if vm["idle"] else ()), *((("warning", vm["unsaved_text"]),) if vm["unsaved"] else ())):
            badge = UI.Badge(kind, text)
            self.badges.append(badge)
            top.addWidget(badge, 0, Qt.AlignVCenter)
        body.addLayout(top)
        self.lines = [UI.ElidedLabel(vm["path"], "caption"), UI.ElidedLabel(vm["meta"], "caption"), UI.ElidedLabel(vm["channels"] + ("  ·  " + " · ".join(vm["flags"]) if vm["flags"] else ""), "caption")]
        for line in self.lines:
            body.addWidget(line)
        row.addLayout(body, 1)
        self.update_from(vm)

    def update_from(self, vm):
        """고름·서랍이 열림 표시만 그 자리에서 바꾼다(줄을 다시 짓지 않는다)."""
        self.setProperty("checked", bool(vm["checked"]))
        self.setProperty("selected", bool(vm["selected"]))
        if self.box.isChecked() != bool(vm["checked"]):
            blocked = self.box.blockSignals(True)
            self.box.setChecked(bool(vm["checked"]))
            self.box.blockSignals(blocked)
        UI.repolish(self)


class SeedList(QWidget):
    """줄 목록 — 거르기·더 보기가 바뀌면 줄들을 새로 짓는다(`set_rows`). 줄을 고르면 `checked(번호)`, 줄을 누르면 `opened(번호)`, 더 보기를 누르면 `more()` 가 나간다."""
    checked = Signal(str)
    opened = Signal(str)
    more = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName(T["seeds_list_a11y"])
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(K.SPACE["2"])
        self.rows = {}
        self._parts = []

    def set_rows(self, vm):
        for part in self._parts:
            self._layout.removeWidget(part)
            part.hide()
            part.deleteLater()
        self._parts, self.rows = [], {}
        empty = vm["empty"]
        if empty is not None:
            card = UI.StateCard("inbox", "blue", empty["title"], empty["desc"])
            self._layout.addWidget(card)
            self._parts.append(card)
            return
        for row_vm in vm["rows"]:
            row = SeedRow(row_vm)
            row.checked.connect(self.checked)
            row.activated.connect(lambda seed_id=row_vm["id"]: self.opened.emit(seed_id))
            self.rows[row_vm["id"]] = row
            self._layout.addWidget(row)
            self._parts.append(row)
        if vm["more"] is not None:
            button = UI.Button("secondary", vm["more"]["text"], accessible=vm["more"]["a11y"], focus_key="seeds-more")
            button.clicked.connect(self.more)
            holder = QWidget()
            inner = QHBoxLayout(holder)
            inner.setContentsMargins(0, K.SPACE["2"], 0, 0)
            inner.addStretch(1)
            inner.addWidget(button)
            inner.addStretch(1)
            self._layout.addWidget(holder)
            self._parts.append(holder)

    def update_checks(self, vm):
        """고름·서랍이 열림 표시만 바꾼다."""
        for row_vm in vm["rows"]:
            row = self.rows.get(row_vm["id"])
            if row is not None:
                row.update_from(row_vm)
