"""글 검토 화면 1b(글 흐름 1b, 결정 D-642 이후)의 Qt 부품 — 네이버 복사용 패키지 카드와 `발행 주소 기록` 창 안 대화상자. 뷰모델(`ui/core/posts_view.py` 의 `PostsController.view`·`record_view`)을 공통 부품(`components.py`)으로 조립하기만 한다.
규칙(복사 단추는 상태를 바꾸지 않는다·복사했어요를 눌러야 복사함·주소 검사·고른 블로그의 패키지만)은 모두 core 에 있다. 글은 모두 일반 글(평문)이고 이 파일에는 파일을 만지는 호출·네트워크·하위 프로세스·표준 출력이 없다.
복사는 셸의 기존 복사 길(`shell.copy` — 클립보드뿐)로만 한다. 주소 칸의 글은 **칸에만** 있고 어느 길로든 대화가 닫히면 비운다(`discard`).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from .post_parts import _Dialog


def package_card(shell, vm):
    """복사용 패키지 카드 — 이름·안내·요약 줄·복사 단추 넷·상태 단추(주요 하나)·접어 둔 확인할 것. `vm` 은 `panel["package"]`(mode: ready·copied·published·missing)."""
    frame, inner = UI.Card((K.SPACE["4"], K.SPACE["3"], K.SPACE["4"], K.SPACE["3"]), kind="plain")
    inner.setSpacing(K.SPACE["2"])
    frame.setAccessibleName(vm["a11y"])
    frame.setProperty("post_part", "package")
    frame.setProperty("package_mode", vm["mode"])
    frame.buttons = {}
    inner.addWidget(UI.label(vm["title"], "h3"))
    if vm.get("sub"):
        inner.addWidget(UI.label(vm["sub"], "small", wrap=True))
    for line in vm["lines"]:
        inner.addWidget(UI.label(line, "body", wrap=True))
    if vm["mode"] == "missing":
        button = UI.Button("secondary", vm["reread"]["text"], accessible=vm["reread"]["a11y"], focus_key="post:package-reread")
        button.clicked.connect(lambda _=False: shell.post_reload_detail())
        inner.addWidget(button, 0, Qt.AlignLeft)
        frame.buttons["reread"] = button
        return frame
    if vm["mode"] == "published":
        copy = vm["copy_url"]
        if copy["visible"]:
            button = UI.Button("secondary", copy["text"], accessible=copy["a11y"], size="sm", focus_key=copy["focus_key"])
            button.setEnabled(bool(copy["enabled"]))
            button.clicked.connect(lambda _=False: shell.post_copy("url"))
            inner.addWidget(button, 0, Qt.AlignLeft)
            frame.buttons["url"] = button
        return frame
    row = QHBoxLayout()
    row.setSpacing(K.SPACE["2"])
    for item in vm["copies"]:
        button = UI.Button("secondary", item["text"], accessible=item["a11y"], size="sm", focus_key=item["focus_key"])
        button.setEnabled(bool(item["enabled"]))
        button.clicked.connect(lambda _=False, kind=item["kind"]: shell.post_copy(kind))
        frame.buttons[item["kind"]] = button
        row.addWidget(button)
    row.addStretch(1)
    inner.addLayout(row)
    if vm["blocked"]:
        inner.addWidget(UI.label(vm["blocked"], "small", wrap=True))
    bar = QHBoxLayout()
    bar.setSpacing(K.SPACE["2"])
    for name, handler, key in (("copied", shell.post_copied, "post:copied"), ("record", shell.post_record, "post:record"), ("uncopy", shell.post_uncopied, "post:uncopy")):
        action = vm[name]
        if not action["visible"]:
            continue
        button = UI.Button("primary" if action.get("primary") else "secondary", action["text"], accessible=action["a11y"], focus_key=key)
        button.setEnabled(bool(action["enabled"]))
        button.clicked.connect(lambda _=False, call=handler: call())
        frame.buttons[name] = button
        bar.addWidget(button)
    bar.addStretch(1)
    inner.addLayout(bar)
    for name in ("copied", "record"):
        action = vm[name]
        if action["visible"] and action.get("note"):
            inner.addWidget(UI.label(action["note"], "caption", wrap=True))
    more = []
    if vm["warnings"]:
        more += [T["post_pkg_warnings"], *vm["warnings"], ""]
    if vm["checklist"]:
        more += [T["post_pkg_checklist"], *vm["checklist"]]
    if more:
        inner.addWidget(UI.Disclosure(T["post_detail_show"], T["post_detail_hide"], "\n".join(more), left=True))
    return frame


class RecordDialog(_Dialog):
    """`발행 주소 기록` — 칸 하나(발행한 글 주소)와 이유 줄. 눌렀을 때 화면이 먼저 검사하고 걸리면 서비스를 부르지 않고 칸 옆에 이유가 보인다. 칸의 글은 이 부품에만 있고 닫히면 비운다."""

    def __init__(self, shell, controller):
        vm = controller.record_view(0)
        super().__init__(shell, vm["title"])
        self.controller = controller
        self.column.addWidget(UI.label(vm["title"], "h2", wrap=True))
        self.column.addWidget(UI.label(vm["intro"], "body", wrap=True))
        self.column.addWidget(UI.label(vm["label"], "small"))
        self.input = UI.TextInput(vm["input_a11y"])
        self.input.setProperty("focus_key", "post:record-url")
        self.input.textChanged.connect(lambda _text="": self._edited())
        self.column.addWidget(self.input)
        self.column.addWidget(UI.label(vm["hint"], "caption", wrap=True))
        self.problem = self.status_label("red")
        self.column.addWidget(self.problem)
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
        self.cancel_button = UI.Button("secondary", vm["cancel"]["text"], accessible=vm["cancel"]["a11y"], focus_key="post:record-cancel")
        self.cancel_button.clicked.connect(lambda _=False: shell.post_record_cancel())
        self.start_button = UI.Button("primary", vm["start"]["text"], accessible=vm["start"]["a11y"], focus_key="post:record-start")
        self.start_button.clicked.connect(lambda _=False: shell.post_record_start())
        row.addWidget(self.cancel_button)
        row.addWidget(self.start_button)
        self.outer.addLayout(row)
        self.refresh()

    def value(self):
        """칸에 적힌 주소 글 — `기록` 을 누르는 순간 한 번 읽어 컨트롤러에 넘긴다(이 부품이 따로 쥐지 않는다)."""
        return self.input.text()

    def _edited(self):
        """글을 치면 단추 켜짐만 바꾼다(대화상자를 다시 그리지 않는다 — 한글 조합이 끊기지 않게)."""
        if self.controller is None:
            return
        self.start_button.setEnabled(self.controller.record_view(len(self.input.text().strip()))["start"]["enabled"])

    def refresh(self):
        """컨트롤러의 뷰모델에 맞게 이유·진행 줄·단추를 바꾼다 — 칸의 글은 건드리지 않는다."""
        if self.controller is None:
            return None
        vm = self.controller.record_view(len(self.input.text().strip()))
        self.show_text(self.problem, vm["problem"])
        self.show_text(self.working, vm["working"])
        self.show_text(self.message, vm["message"])
        self.start_button.setEnabled(vm["start"]["enabled"])
        self.cancel_button.setEnabled(vm["cancel"]["enabled"])
        self.input.setReadOnly(bool(vm["working"]))
        for first, second in zip([self.scroll, self.input, self.cancel_button, self.start_button], [self.input, self.cancel_button, self.start_button]):
            QWidget.setTabOrder(first, second)
        self.refit()
        QTimer.singleShot(0, self.refit_later)
        return vm

    def focus_start(self):
        self.input.setFocus(Qt.OtherFocusReason)

    def focus_problem(self):
        """문제 문장이 있으면 칸으로 포커스를 옮긴다."""
        if self.problem.isVisible():
            self.input.setFocus(Qt.OtherFocusReason)
            return True
        return False

    def discard(self):
        """대화상자가 닫히거나 바뀔 때(어느 길로든) — 주소 칸을 비운다(되돌리기 기록까지). 여러 번 불러도 같다."""
        try:
            self.input.blockSignals(True)
            UI.wipe_input(self.input)
        except RuntimeError:                                                      # 이미 지워진 부품
            pass
        self.controller = None
        return True
