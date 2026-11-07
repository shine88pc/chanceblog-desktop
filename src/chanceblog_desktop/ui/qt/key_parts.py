"""키 연결 화면(P4f)의 부품 — 용도 카드의 키 구역(`key_section`: 키 행 `KeyRow` + '키 등록' 단추 + 저장소 안내)·키 등록 대화상자(`KeyDialog`: 입력 단계 → 확인 단계)·별칭 바꾸기 입력(`RenameForm`).
화면(`screens.py`)은 뷰모델(`ui/core/keys_view.py` 가 만든 딕셔너리)을 이 부품으로 조립하기만 하고, 부품은 공통 부품(`components.py`)만 쓴다. 색·글꼴·크기는 토큰(스타일시트)에서만 오고 여기서 인라인 스타일·직접 색을 쓰지 않는다.

**키가 새지 않게**(시험이 위젯 트리·상태·클립보드를 전수로 훑는다):
  · 키는 **마스킹 입력 칸**(`UI.SecretInput`)에만 있다. 칸의 글을 뷰모델·상태·신호에 싣지 않는다 — 키 칸에는 `textChanged`·`textEdited` 를 잇지 않고, 글은 '다음'(검사)과 '저장'(통에 담기)을 누를 때 **그 순간** 읽는다. 요약(확인 단계)에는 서비스·제공자·별칭만 있다.
  · 저장·취소·창 닫기·다른 대화상자로 바뀔 때 칸을 모두 비운다(`UI.wipe_input` — 되돌리기 기록까지). 대화상자의 정리 훅(`Dialog.cleanups`)이 어느 길로 닫혀도 부른다.
  · 붙여 넣은 글과 같은 글이 클립보드에 그대로 있으면 저장·닫을 때 클립보드도 비운다(`shell.wipe_clipboard`). 앱이 키를 클립보드에 **넣는** 일은 없다(마스킹 칸은 복사·잘라내기가 글을 안 내보낸다).
  · 별칭 칸(눈에 보이는 칸)에 키처럼 보이는 글이 들어오면 바로 비운다.
모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다. 꺼진 단추는 까닭을 툴팁·접근 설명으로 알리고(중요한 까닭은 글로도 보인다) 색만으로 상태를 알리지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core import key_rules as rules
from ..core import tokens as K
from ..core.keys import SecretBox
from ..core.text import T
from . import components as UI

LEVEL_TONE = {"ok": "green", "info": "slate", "warning": "orange", "error": "red"}                  # 줄 안내 글의 색 계열 — 글자('연결을 확인했어요' …)가 늘 함께 있다
VISIBLE_REASONS = ("keys_why_prep", "keys_why_terms")                                               # 꺼진 단추의 까닭 중 글로도 보이는 것(툴팁만으로는 놓치기 쉬운 것 — 시험이 못 하는 까닭)


# ---- 카드의 키 구역 ------------------------------------------------------------------------------------------------------------------
class KeyRow(QFrame):
    """키 하나의 줄 — 별칭(한 줄)·배지(사용/예비/꺼짐 + 우선순위 — 글자가 늘 함께)·작은 글 줄(제공자·마지막 성공·마지막 오류)·이 줄만의 안내·행동 단추들(폭이 모자라면 다음 줄로)."""

    def __init__(self, vm, purpose, shell):
        super().__init__()
        self.ref, self.purpose = vm["ref"], purpose
        self.setProperty("card", "plain")
        self.setAccessibleName(vm["a11y"])
        column = QVBoxLayout(self)
        column.setContentsMargins(K.SPACE["3"], K.SPACE["3"], K.SPACE["3"], K.SPACE["3"])
        column.setSpacing(K.SPACE["1"])
        head = QHBoxLayout()
        head.setSpacing(K.SPACE["2"])
        self.name = UI.ElidedLabel(vm["name"], "body_lg")
        head.addWidget(self.name, 1)
        for badge in vm["badges"]:
            head.addWidget(UI.Badge(badge["tone"], badge["text"]), 0, Qt.AlignVCenter)
        column.addLayout(head)
        self.lines = [UI.label(text, "caption", wrap=True) for text in vm["lines"]]
        for line in self.lines:
            column.addWidget(line)
        self.note = None
        if vm["note"]:
            self.note = UI.label(vm["note"]["text"], "small", wrap=True)
            self.note.set_tone(LEVEL_TONE.get(vm["note"]["level"], "slate"))
            column.addWidget(self.note)
        self.buttons = {}
        for action in vm["actions"]:
            button = UI.Button(action["kind"], action["text"], size="sm", accessible=action["a11y"], focus_key=f"key:{self.ref}:{action['key']}")
            button.setProperty("action", action["key"])
            button.setEnabled(action["enabled"])
            if not action["enabled"] and action["reason"]:
                UI.with_tooltip(button, action["reason"])
                button.setAccessibleDescription(action["reason"])
            button.clicked.connect(lambda _=False, key=action["key"]: shell.key_action(self.purpose, self.ref, key))
            self.buttons[action["key"]] = button
        column.addWidget(UI.chip_row(list(self.buttons.values())))
        self.reasons = []
        for action in vm["actions"]:
            if not action["enabled"] and action["reason"] and action["key"] == "test" and action["reason"] in (T[key] for key in VISIBLE_REASONS):
                reason = UI.label(action["reason"], "caption", wrap=True)
                column.addWidget(reason)
                self.reasons.append(reason)


def key_section(keys, shell, purpose):
    """용도 카드의 키 구역 — 저장소 안내(쓸 수 없을 때)·'키 없음' 안내·키 행들·'키 등록' 단추. 쓰는 중이면 안내 한 줄."""
    box = QWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(K.SPACE["2"])
    column.addWidget(UI.label(keys["title"], "small"))
    if keys["store_note"]:
        column.addWidget(UI.label(keys["store_note"]["title"], "small", wrap=True))
        column.addWidget(UI.label(keys["store_note"]["why"], "caption", wrap=True))
    if keys["none"]:
        column.addWidget(UI.label(keys["none"], "body", wrap=True))
    rows = []
    for row in keys["rows"]:
        item = KeyRow(row, purpose, shell)
        rows.append(item)
        column.addWidget(item)
    register = None
    if keys["register"]:
        info = keys["register"]
        register = UI.Button("secondary", info["text"], "plus", accessible=info["a11y"], focus_key=f"key-register:{purpose}")
        register.setEnabled(info["enabled"])
        if not info["enabled"] and info["reason"]:
            UI.with_tooltip(register, info["reason"])
            register.setAccessibleDescription(info["reason"])
        register.clicked.connect(lambda _=False: shell.key_register(purpose))
        holder = QHBoxLayout()
        holder.addWidget(register, 0, Qt.AlignLeft)
        holder.addStretch(1)
        column.addLayout(holder)
        if not info["enabled"] and info["reason"] and info["reason"] != T["keys_busy"] and not keys["store_note"]:
            column.addWidget(UI.label(info["reason"], "caption", wrap=True))                         # 자리가 없을 때처럼 눈에 보여야 하는 까닭(저장소 안내가 있으면 그 글이 까닭이다)
    box.rows, box.register = rows, register
    return box


# ---- 대화상자 ------------------------------------------------------------------------------------------------------------------------
class DialogScroll(QScrollArea):
    """대화상자 몸이 창보다 길 때만 스크롤되는 영역 — 기본 크기는 몸의 **전체 높이**(Qt 기본은 글줄 24개로 잘라 큰 창에서도 스크롤바가 생긴다)다. 대화상자(`Dialog.place`)가 창 높이로 한 번 더 줄이면 그때 스크롤된다. 가로 스크롤은 없다.
    대화상자는 안쪽의 '폭에 따른 높이'(`heightForWidth`)로 키를 정하는데 스크롤 영역은 기본으로 그것이 없어 최소 크기(120px)로 쪼그라든다 — 몸의 폭에 따른 높이를 그대로 알려 준다."""

    def __init__(self, body):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWidget(body)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def heightForWidth(self, width):
        body = self.widget()
        if body is None:
            return 0
        inner = max(width - 2 * self.frameWidth(), 1)
        height = body.heightForWidth(inner) if body.hasHeightForWidth() else body.sizeHint().height()
        return max(height, 0) + 2 * self.frameWidth()

    def sizeHint(self):
        width = max(self.width(), K.LAYOUT["dialog"] - 48)
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        return QSize(0, 120)


class KeyDialog(QWidget):
    """키 등록 대화상자의 안쪽 — 입력 단계(별칭·제공자·마스킹 입력 칸들)와 확인 단계(요약에는 서비스·제공자·별칭만, 키는 안 보인다 + 둘째 키 약관 확인). 단계 상태는 `RegisterDraft`(비밀 아님)가 들고 있고 키 글은 입력 칸에만 있다.
    '다음' 은 칸을 검사하고(문제는 칸 옆에 문장으로), '저장' 은 그 순간 칸의 글을 `SecretBox` 에 담아 칸을 비우고 대화상자를 닫은 뒤 컨트롤러에 넘긴다. 취소·Esc·닫기는 칸을 비우고 초안을 버린다.
    몸(제목·안내·칸들)은 창이 낮을 때 스크롤되고 단추 줄은 늘 아래에 보인다(`DialogScroll`)."""

    def __init__(self, draft, shell):
        super().__init__()
        self.draft, self.shell = draft, shell
        vm = draft.vm()
        self.setAccessibleName(vm["a11y"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(K.SPACE["3"])
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, K.SPACE["2"], 0)
        column.setSpacing(K.SPACE["3"])
        self.title = UI.label(vm["title"], "h2", wrap=True)
        column.addWidget(self.title)
        self.intro = UI.label(vm["intro"], "body", wrap=True)
        column.addWidget(self.intro)
        self.input_page, self.confirm_page = QWidget(), QWidget()
        self.input_buttons, self.confirm_buttons = QWidget(), QWidget()
        self.secret_edits, self.chips, self.errors = {}, {}, {}
        self._build_input(vm)
        self._build_confirm(vm)
        column.addWidget(self.input_page)
        column.addWidget(self.confirm_page)
        column.addStretch(1)                                                                       # 남는 키는 아래로(단계가 바뀌어 몸이 짧아져도 글 사이가 벌어지지 않는다)
        self.scroll = DialogScroll(body)
        outer.addWidget(self.scroll, 1)
        outer.addWidget(self.input_buttons)
        outer.addWidget(self.confirm_buttons)
        self.refresh()

    # ---- 만들기 ----
    def _error_label(self):
        label = UI.label("", "small", wrap=True)
        label.set_tone("red")
        label.setVisible(False)
        return label

    def _build_input(self, vm):
        column = QVBoxLayout(self.input_page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(K.SPACE["2"])
        column.addWidget(UI.label(vm["alias"]["label"], "small"))
        self.alias_edit = UI.TextInput(vm["alias"]["a11y"])
        self.alias_edit.setProperty("focus_key", "keydlg:alias")
        self.alias_edit.setText(vm["alias"]["value"])
        self.alias_edit.textEdited.connect(self._alias_edited)
        column.addWidget(self.alias_edit)
        column.addWidget(UI.label(vm["alias"]["hint"], "caption", wrap=True))
        self.errors["name"] = self._error_label()
        column.addWidget(self.errors["name"])
        if vm["providers"]:
            column.addWidget(UI.label(vm["provider_label"], "small"))
            group = QButtonGroup(self)
            group.setExclusive(True)
            for item in vm["providers"]:
                chip = UI.FilterChip(item["label"], None, item["selected"], focus_key=f"keydlg:provider:{item['key']}")
                chip.setEnabled(item["enabled"])
                if not item["enabled"]:
                    UI.with_tooltip(chip, item["reason"])
                    chip.setAccessibleName(f"{item['label']}, {item['reason']}")
                chip.clicked.connect(lambda _=False, key=item["key"]: self._provider(key))
                group.addButton(chip)
                self.chips[item["key"]] = chip
            column.addWidget(UI.chip_row(list(self.chips.values())))
            self.errors["provider"] = self._error_label()
            column.addWidget(self.errors["provider"])
        for index, field in enumerate(vm["fields"]):
            column.addWidget(UI.label(field["label"], "small"))
            edit = UI.SecretInput(field["a11y"])
            edit.setProperty("focus_key", f"keydlg:secret:{field['name']}")
            self.secret_edits[field["name"]] = edit
            column.addWidget(edit)
            if index == 0:
                column.addWidget(UI.label(field["hint"], "caption", wrap=True))                  # 칸마다 되풀이하지 않는다 — 대화상자가 낮아도 칸이 다 보이게
            self.errors[field["name"]] = self._error_label()
            column.addWidget(self.errors[field["name"]])
        column.addWidget(UI.label(vm["clipboard"], "caption", wrap=True))
        row = QHBoxLayout(self.input_buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        self.cancel_button = UI.Button("secondary", vm["buttons"]["cancel"], accessible=vm["buttons"]["cancel"], focus_key="keydlg:cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.next_button = UI.Button("primary", vm["buttons"]["next"], accessible=vm["buttons"]["next"], focus_key="keydlg:next")
        self.next_button.clicked.connect(self.go_next)
        row.addWidget(self.cancel_button)
        row.addWidget(self.next_button)

    def _build_confirm(self, vm):
        column = QVBoxLayout(self.confirm_page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(K.SPACE["2"])
        confirm = vm["confirm"]
        column.addWidget(UI.label(confirm["title"], "h3", wrap=True))
        self.summary = [UI.label(line, "body", wrap=True) for line in confirm["lines"]]
        for label in self.summary:
            column.addWidget(label)
        column.addWidget(UI.label(confirm["note"], "caption", wrap=True))
        self.terms_text = UI.label(confirm["terms"]["text"], "small", wrap=True)
        self.terms_toggle = UI.Toggle(confirm["terms"]["check"], confirm["terms"]["check"])
        self.terms_toggle.setProperty("focus_key", "keydlg:terms")
        self.terms_toggle.toggled.connect(self._terms)
        column.addWidget(self.terms_text)
        column.addWidget(self.terms_toggle)
        row = QHBoxLayout(self.confirm_buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        self.confirm_cancel = UI.Button("secondary", vm["buttons"]["cancel"], accessible=vm["buttons"]["cancel"], focus_key="keydlg:confirm-cancel")
        self.confirm_cancel.clicked.connect(self.cancel)
        self.back_button = UI.Button("ghost", vm["buttons"]["back"], accessible=vm["buttons"]["back"], focus_key="keydlg:back")
        self.back_button.clicked.connect(self.go_back)
        self.save_button = UI.Button("primary", vm["buttons"]["save"]["text"], accessible=vm["buttons"]["save"]["text"], focus_key="keydlg:save")
        self.save_button.clicked.connect(self.save)
        for button in (self.confirm_cancel, self.back_button, self.save_button):
            row.addWidget(button)

    # ---- 그리기 ----
    def refresh(self):
        """초안(비밀 아닌 값)에 맞게 단계·오류 문장·요약·단추를 바꾼다 — 입력 칸의 글은 건드리지 않는다."""
        vm = self.draft.vm()
        confirm = vm["step"] == "confirm"
        self.input_page.setVisible(not confirm)
        self.input_buttons.setVisible(not confirm)
        self.intro.setVisible(not confirm)                                                          # 확인 단계의 안내(아래 요약 글)가 같은 말이라 되풀이하지 않는다
        self.confirm_page.setVisible(confirm)
        self.confirm_buttons.setVisible(confirm)
        self.setAccessibleName(vm["a11y"])
        if self.alias_edit.text() != vm["alias"]["value"]:
            self.alias_edit.setText(vm["alias"]["value"])
        messages = {"name": vm["alias"]["error"], "provider": vm["provider_error"], **{field["name"]: field["error"] for field in vm["fields"]}}
        for name, label in self.errors.items():
            label.set_text(messages.get(name, ""))
            label.setVisible(bool(messages.get(name)))
        for key, chip in self.chips.items():
            chip.setChecked(key == self.draft.provider)
        for label, line in zip(self.summary, vm["confirm"]["lines"]):
            label.set_text(line)
        terms = vm["confirm"]["terms"]
        self.terms_text.setVisible(terms["show"])
        self.terms_toggle.setVisible(terms["show"])
        self.terms_toggle.blockSignals(True)
        self.terms_toggle.setChecked(terms["checked"])
        self.terms_toggle.blockSignals(False)
        save = vm["buttons"]["save"]
        self.save_button.setEnabled(save["enabled"])
        self.save_button.setToolTip(save["reason"] if not save["enabled"] else "")
        self.save_button.setAccessibleDescription(save["reason"] if not save["enabled"] else "")
        self.title.set_text(vm["title"])
        host = self.parentWidget()
        if host is not None and host is getattr(self.shell, "dialog", None):
            host.setAccessibleName(vm["a11y"])                                                   # 단계가 바뀌면 대화상자의 접근 이름도 바뀐다("… 2단계 확인")
            self._refit(host)
        return vm

    def _refit(self, dialog):
        """단계가 바뀌거나 문제 글이 나타나 몸의 키가 달라지면 열려 있는 대화상자의 키를 다시 맞춘다(창에 들어가는 한 스크롤 없이 몸이 다 보이게)."""
        if not dialog.is_open:
            return
        for widget in (self.scroll.widget(), self.scroll, self):
            widget.updateGeometry()                                                              # 배치가 기억해 둔 폭에 따른 높이를 버린다(안 버리면 옛 단계의 키로 남는다)
        dialog.layout_.activate()
        dialog.place()

    def focus_start(self):
        """열릴 때의 첫 포커스 — 입력 단계는 문제가 있는 첫 칸(없으면 첫 키 칸), 확인 단계는 **취소**(Enter 를 잘못 눌러도 저장되지 않는다)."""
        if self.draft.step == "confirm":
            self.confirm_cancel.setFocus(Qt.OtherFocusReason)
            return
        order = ["name", *self.secret_edits]
        first = next((name for name in order if name in self.draft.problems), None)
        target = self.alias_edit if first == "name" else self.secret_edits.get(first) or next(iter(self.secret_edits.values()), self.alias_edit)
        target.setFocus(Qt.OtherFocusReason)

    # ---- 동작 ----
    def _alias_edited(self, text):
        """별칭 칸 — 키처럼 보이는 글이 들어오면 바로 비운다(눈에 보이는 칸에 키가 남지 않게)."""
        if rules.alias_problem(text) == "keyish":
            self.alias_edit.setText("")
            self.draft.set_alias("")
            self.draft.problems["name"] = "keyish"
            self.refresh()
            return
        self.draft.set_alias(text)
        if "name" in self.errors:
            self.errors["name"].setVisible(False)

    def _provider(self, key):
        self.draft.set_provider(key)
        self.refresh()

    def _terms(self, checked):
        self.draft.set_terms(checked)
        self.refresh()

    def go_next(self):
        """'다음' — 입력 칸을 검사한다(글은 이 순간 읽어 문제 이름만 남긴다). 문제가 없으면 확인 단계로 간다(키 칸의 글은 그대로 칸에 둔다)."""
        problems = {}
        for name, edit in self.secret_edits.items():
            cleaned = rules.clean_secret(edit.text())
            if cleaned != edit.text():
                edit.setText(cleaned)                                                          # 줄바꿈·앞뒤 공백을 지운 글을 칸에 돌려놓는다(칸은 마스킹이라 점으로만 보인다)
            code = rules.secret_problem(cleaned)
            if code:
                problems[name] = code
        self.draft.set_alias(self.alias_edit.text())
        moved = self.draft.go_confirm(problems)
        self.refresh()
        if moved:
            self.confirm_cancel.setFocus(Qt.OtherFocusReason)
        else:
            self.focus_start()
        return moved

    def go_back(self):
        self.draft.back()
        self.refresh()
        self.focus_start()

    def save(self):
        """'저장' — 칸의 글을 이 순간 통에 담고 칸을 비운 뒤 대화상자를 닫고 컨트롤러에 넘긴다. 약관 확인이 필요한데 안 했으면 아무 일도 하지 않는다."""
        if not self.draft.can_save():
            return False
        box = SecretBox()
        for name, edit in self.secret_edits.items():
            box.put(name, rules.clean_secret(edit.text()))
        self.wipe()
        draft = self.draft
        draft.submitted = True                                                                  # 저장으로 넘어갔다 — 대화상자를 닫아도 초안은 컨트롤러가 들고 있는다(실패하면 별칭이 남아 다시 시도한다)
        self.shell.close_dialog()
        self.shell.key_add(draft, box)
        return True

    def cancel(self):
        self.shell.key_cancel()

    def wipe(self):
        """키 입력 칸을 모두 비운다 — 붙여 넣은 글과 같은 글이 클립보드에 있으면 클립보드도 비운다. 여러 번 불러도 같다."""
        texts = [rules.clean_secret(edit.text()) for edit in self.secret_edits.values() if edit.text()]
        if texts:
            self.shell.wipe_clipboard(texts)
        for edit in self.secret_edits.values():
            UI.wipe_input(edit)
        return True


class RenameForm(QWidget):
    """별칭 바꾸기 입력(대화상자의 안쪽) — 지금 별칭이 채워진 한 줄 입력과 [취소][바꾸기]. 별칭은 비밀이 아니지만 키처럼 보이는 글은 바로 비운다. 문제는 칸 옆에 문장으로 보이고 입력은 남는다."""

    def __init__(self, vm, purpose, ref, shell):
        super().__init__()
        self.purpose, self.ref, self.shell, self.vm = purpose, ref, shell, vm
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(K.SPACE["3"])
        self.setAccessibleName(vm["title"])
        column.addWidget(UI.label(vm["title"], "h2", wrap=True))
        column.addWidget(UI.label(vm["body"], "body", wrap=True))
        column.addWidget(UI.label(vm["label"], "small"))
        self.edit = UI.TextInput(vm["a11y"])
        self.edit.setProperty("focus_key", "keyren:edit")
        self.edit.setText(vm["value"])
        self.edit.selectAll()
        self.edit.textEdited.connect(self._edited)
        column.addWidget(self.edit)
        self.error = UI.label("", "small", wrap=True)
        self.error.set_tone("red")
        self.error.setVisible(False)
        column.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_button = UI.Button("secondary", vm["cancel"], accessible=vm["cancel"], focus_key="keyren:cancel")
        self.cancel_button.clicked.connect(shell.close_dialog)
        self.ok_button = UI.Button("primary", vm["ok"], accessible=vm["ok"], focus_key="keyren:ok")
        self.ok_button.clicked.connect(self.submit)
        row.addWidget(self.cancel_button)
        row.addWidget(self.ok_button)
        column.addLayout(row)

    def _edited(self, text):
        if rules.alias_problem(text) == "keyish":
            self.edit.setText("")
            self.show_problem("keyish")
        else:
            self.error.setVisible(False)

    def show_problem(self, code):
        from ..core.keys_view import alias_text
        self.error.set_text(alias_text(code))
        self.error.setVisible(True)

    def submit(self):
        status, detail = self.shell.key_rename(self.purpose, self.ref, self.edit.text())
        if status == "invalid":
            self.show_problem(detail.get("name", "other"))
            self.edit.setFocus(Qt.OtherFocusReason)
        return status

    def focus_start(self):
        QTimer.singleShot(0, lambda: self.edit.setFocus(Qt.OtherFocusReason) if self.edit.isVisible() else None)
