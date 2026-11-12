"""설정 화면의 백업·복원 카드 부품(BACKUPUI) — `backup_section(vm, shell)` 이 뷰모델(`ui/core/backup_view.py` 가 만든 딕셔너리)을 공통 부품(`components.py`)으로 조립하기만 한다: 머리(제목·`지금 백업`) · 안내(백업 위치 글자·직접 복사 안내·Credential 제외 문장) ·
결과 띠 · 진행 줄 · 접어 둔 '백업에 들어 있지 않은 것' · 백업 목록(줄마다 이름·종류·상태·`Credential 제외됨`·크기·담긴 것·`복원`) 또는 상태 화면(읽는 중·비어 있음·읽기 오류).
색·글꼴·크기는 토큰(스타일시트)에서만 오고 여기서 인라인 스타일·직접 색을 쓰지 않는다. **새 외부 호출이 없다** — 폴더 열기 단추도, 파일을 쓰는 호출도 없다(눌림은 `shell` 의 메서드로만 넘긴다).

모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다. 꺼진 단추는 까닭을 툴팁·접근 설명으로 알린다(쓰는 중인 까닭은 진행 줄이 글로 보인다).
색만으로 상태를 알리지 않는다 — 완료·부분·깨짐은 글자 배지고 `Credential 제외됨` 도 글자 배지다. 진행은 글(`40%`)과 막대가 함께이고 막대는 제자리에서 바뀐다(전체를 다시 그리지 않는다).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .blog_parts import NoticeBar
from .gauges import Track

PROGRESS_COLOR = "primary"


class ProgressTrack(Track):
    """진행 막대 — `Track` 의 채움을 제자리에서 바꾼다(`set_fraction`)."""

    def __init__(self, fraction=0.0):
        super().__init__(K.SIZE["usage_h"], K.RADIUS["usage"], [(fraction, PROGRESS_COLOR)] if fraction > 0 else [], rounded_fill=True)

    def set_fraction(self, fraction):
        self._segments = ((min(max(fraction, 0.0), 1.0), PROGRESS_COLOR),) if fraction > 0 else ()
        self.update()


class ProgressLine(QWidget):
    """진행 한 줄 — 글(`백업하는 중이에요… 40% — 파일을 담아요`)과 막대. `set_progress` 로 제자리에서 바꾼다."""

    def __init__(self, vm):
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(K.SPACE["2"])
        self.text = UI.label(vm["text"], "body", wrap=True)
        self.track = ProgressTrack(vm["fraction"])
        column.addWidget(self.text)
        column.addWidget(self.track)
        self.setAccessibleName(vm["a11y"])
        self.fraction = vm["fraction"]

    def set_progress(self, vm):
        self.text.set_text(vm["text"])
        self.track.set_fraction(vm["fraction"])
        self.setAccessibleName(vm["a11y"])
        self.fraction = vm["fraction"]


class BackupRow(QFrame):
    """백업 한 줄 — 이름(시각 + 종류)·배지(종류·상태·`Credential 제외됨` — 글자가 늘 함께)·작은 글 줄(크기·담긴 것·담지 못한 것)·`복원` 단추."""

    def __init__(self, vm, shell):
        super().__init__()
        self.name = vm["name"]
        self.setProperty("card", "plain")
        self.setAccessibleName(vm["a11y"])
        column = QVBoxLayout(self)
        column.setContentsMargins(K.SPACE["3"], K.SPACE["3"], K.SPACE["3"], K.SPACE["3"])
        column.setSpacing(K.SPACE["1"])
        head = QHBoxLayout()
        head.setSpacing(K.SPACE["2"])
        self.title = UI.ElidedLabel(vm["title"], "body_lg")
        head.addWidget(self.title, 1)
        self.badges = [UI.Badge(vm["kind"]["tone"], vm["kind"]["text"]), UI.Badge(vm["status"]["tone"], vm["status"]["text"])]
        if vm["credential"]:
            credential = UI.Badge("ok", vm["credential"]["text"])
            credential.setAccessibleName(vm["credential"]["a11y"])
            self.badges.append(credential)
        for badge in self.badges:
            head.addWidget(badge, 0, Qt.AlignVCenter)
        column.addLayout(head)
        self.lines = []
        if vm["meta"]:
            self.lines.append(UI.label(vm["meta"], "caption", wrap=True))
        self.lines += [UI.label(text, "caption", wrap=True) for text in vm["lines"]]
        for line in self.lines:
            column.addWidget(line)
        info = vm["restore"]
        self.restore = UI.Button("secondary", info["text"], size="sm", accessible=info["a11y"], focus_key=f"backup-restore:{self.name}")
        self.restore.setEnabled(info["enabled"])
        if not info["enabled"] and info["reason"]:
            UI.with_tooltip(self.restore, info["reason"])
            self.restore.setAccessibleDescription(info["reason"])
        self.restore.clicked.connect(lambda _=False, name=self.name: shell.backup_restore(name))
        holder = QHBoxLayout()
        holder.addWidget(self.restore, 0, Qt.AlignLeft)
        holder.addStretch(1)
        column.addLayout(holder)


class BackupSection(QFrame):
    """백업·복원 카드 하나 — 위젯 참조(`create_button`·`rows`·`progress`·`notice`·`excluded`)를 들고 있어 시험·포커스 복귀가 찾는다."""

    def __init__(self, vm, shell):
        super().__init__()
        self.setProperty("card", "true")
        self.setAccessibleName(vm["a11y"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(K.LAYOUT["gap"])
        head = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(K.SPACE["2"])
        title_row.addWidget(UI.label(vm["title"], "h1"))
        if vm["sample"]:
            title_row.addWidget(UI.Badge("muted", vm["sample_tag"]), 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        left.addLayout(title_row)
        left.addWidget(UI.label(vm["desc"], "sub", wrap=True))
        head.addLayout(left, 1)
        info = vm["create"]
        self.create_button = UI.Button("primary", info["text"], "shield", accessible=info["a11y"], focus_key="backup-create")
        self.create_button.setEnabled(info["enabled"])
        if not info["enabled"] and info["reason"]:
            UI.with_tooltip(self.create_button, info["reason"])
            self.create_button.setAccessibleDescription(info["reason"])
        self.create_button.clicked.connect(lambda _=False: shell.backup_now())
        head.addWidget(self.create_button, 0, Qt.AlignTop)
        outer.addLayout(head)
        if vm["sample_note"]:
            outer.addWidget(UI.label(vm["sample_note"], "caption", wrap=True))
        if not info["enabled"] and info["reason"] and not vm["busy"]:
            outer.addWidget(UI.label(info["reason"], "caption", wrap=True))
        self.notes = []
        group = QVBoxLayout()                                                              # 안내 글 넷은 한 묶음으로 촘촘히(카드 칸 사이 간격은 묶음 사이에만)
        group.setSpacing(K.SPACE["1"])
        for text, role in ((vm["location"], "small"), (vm["copy_tip"], "small"), (vm["keep"], "caption"), (vm["credential_line"], "small")):
            if text:
                note = UI.label(text, role, wrap=True)
                if text == vm["location"]:
                    note.setTextInteractionFlags(Qt.TextSelectableByMouse)               # 위치는 글자로 보이고 복사할 수 있다(폴더 열기 단추는 없다)
                group.addWidget(note)
                self.notes.append(note)
        outer.addLayout(group)
        self.notice = None
        if vm["notice"]:
            self.notice = NoticeBar(vm["notice"]["level"], vm["notice"]["text"])
            outer.addWidget(self.notice)
            self.notice_lines = [UI.label(line, "small", wrap=True) for line in vm["notice"]["lines"]]
            for line in self.notice_lines:
                outer.addWidget(line)
        else:
            self.notice_lines = []
        self.interrupted, self.interrupted_lines, self.revert_button = None, [], None
        if vm["interrupted"]:                                                              # 복원이 중간에 멈춘 흔적 — 쉬운 안내와 `안전 사본으로 되돌리기`(확인창이 먼저다)
            box = vm["interrupted"]
            self.interrupted = NoticeBar(box["level"], box["text"])
            outer.addWidget(self.interrupted)
            self.interrupted_lines = [UI.label(line, "small", wrap=True) for line in box["lines"]]
            for line in self.interrupted_lines:
                outer.addWidget(line)
            if box["revert"]:
                info = box["revert"]
                self.revert_button = UI.Button("secondary", info["text"], accessible=info["a11y"], focus_key="backup-revert")
                self.revert_button.setEnabled(info["enabled"])
                if not info["enabled"] and info["reason"]:
                    UI.with_tooltip(self.revert_button, info["reason"])
                    self.revert_button.setAccessibleDescription(info["reason"])
                self.revert_button.clicked.connect(lambda _=False: shell.backup_revert())
                holder = QHBoxLayout()
                holder.addWidget(self.revert_button, 0, Qt.AlignLeft)
                holder.addStretch(1)
                outer.addLayout(holder)
        self.progress = None
        if vm["progress"]:
            self.progress = ProgressLine(vm["progress"])
            outer.addWidget(self.progress)
        excluded = vm["excluded"]
        self.excluded = UI.Disclosure(excluded["show"], excluded["hide"], "\n".join([excluded["intro"], *excluded["lines"]]), mono=False, left=True)
        self.excluded.toggle.setProperty("focus_key", "backup-excluded")
        outer.addWidget(self.excluded)
        outer.addWidget(UI.label(vm["list_title"], "h3"))
        self.rows, self.state_card = [], None
        state = vm["state"]
        if state == "loading":
            outer.addWidget(UI.Skeleton(2, vm["loading"]["a11y"]))
            outer.addWidget(UI.label(vm["loading"]["text"], "sub"))
        elif state == "error":
            diag = QWidget()
            box = QVBoxLayout(diag)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(UI.Disclosure(T["diag_show"], T["diag_hide"], vm["error"]["diag"]))
            box.addWidget(UI.label(T["diag_note"], "caption", wrap=True))
            self.state_card = UI.StateCard("alert", "red", vm["error"]["title"], vm["error"]["user"] or vm["error"]["desc"], vm["error"]["button"], shell.reload_backups, diag)
            outer.addWidget(self.state_card)
        elif state == "empty":
            self.state_card = UI.StateCard("inbox", "blue", vm["empty"]["title"], vm["empty"]["desc"])
            outer.addWidget(self.state_card)
        else:
            outer.addWidget(UI.label(vm["list_note"], "caption", wrap=True))
            for row in vm["rows"]:
                item = BackupRow(row, shell)
                self.rows.append(item)
                outer.addWidget(item)

    def row(self, name):
        return next((item for item in self.rows if item.name == name), None)


def backup_section(vm, shell):
    """설정 화면에 붙이는 백업·복원 카드 — 뷰모델 하나로 만든다."""
    return BackupSection(vm, shell)
