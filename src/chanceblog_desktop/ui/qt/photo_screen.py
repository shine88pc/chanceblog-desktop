"""'사진 정리' 창(사진 연동 초안 2단계, 결정 D-499)의 Qt 쪽 — 대화상자의 안쪽(`PhotoSheet`). 진입점은 초안 작성 화면의 '사진 넣기(선택)' 줄과 오른쪽 '사진' 카드의 단추다.
화면은 뷰모델(`ui/core/photo_view.py` 의 `PhotoBoard.view` 가 만든 딕셔너리)을 공통 부품(`components.py`)과 사진 줄 부품(`photo_parts.py`)으로 조립하기만 한다 — 규칙(한도·확인이 풀리는 때·한꺼번에 확인의 확인 줄·순서·지우기와 되돌리기·못 넣은 파일 목록·큰 PNG 판정)은 모두 core 에 있다.
색·글꼴·크기·간격은 토큰(`K`·스타일시트)에서만 오고 여기서 인라인으로 정하지 않는다. 이 파일에는 파일을 쓰거나 지우는 호출·네트워크·하위 프로세스·표준 출력이 없다(사진 파일은 `imagecheck` 로 **읽기만** 한다 — 미리보기는 메모리의 `QImage` 로만 만든다).

**몸(제목·안내·사진 줄들·넣지 못한 파일·목록 고치기)은 창이 낮을 때 스크롤되고(`DialogScroll`), 상태 줄(한꺼번에 확인의 확인 줄·안내·되돌리기)과 단추 줄(사진 추가·모두 확인했어요·닫기)은 스크롤 밖 아래에 늘 보인다.**
미리보기는 한 장씩 차례로(`QTimer.singleShot`) 만들어 창이 멈추지 않게 하고, 파일이 없거나 못 읽는 사진·큰 PNG(1억 화소 초과 — 읽기 전에 막는다)는 그림 대신 글이 보인다. 확인 줄이 뜨면 처음 포커스는 안전한 쪽(그만두기)에 둔다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import photo_rules as rules
from ..core import tokens as K
from ..core.text import T
from . import components as UI
from . import imagecheck
from .key_parts import DialogScroll
from .photo_parts import TONE, PhotoRowCard
from .style_dialog import _empty_layout

DIALOG_WIDTH = 820                                                               # 사진 줄이 들어갈 만큼 넓은 대화상자(창 논리 폭의 94% 를 넘지 않는다 — `Dialog.place`)
PREVIEW_PIXELS = rules.THUMB_SIDE * 2                                            # 이미지 읽기 도구가 줄여 읽는 긴 변(화면에는 `THUMB_SIDE` 로 줄여 그린다)


def make_preview(path):
    """사진 한 장의 미리보기 그림(`QPixmap`) — 못 만들면 None. **메모리에서만** 만들고(원본 파일은 읽기만 한다) 큰 PNG 는 이 함수를 부르기 전에 core 가 막는다(`preview_blocked`). 시험이 바꿔 끼우는 자리다."""
    image = imagecheck.make_thumbnail(path, max_side=PREVIEW_PIXELS)
    if image is None:
        return None
    pixmap = QPixmap.fromImage(image)
    return pixmap.scaled(rules.THUMB_SIDE, rules.THUMB_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class PhotoSheet(QWidget):
    """대화상자의 안쪽 — 사진 줄들(스크롤 몸), 상태 줄과 단추 줄(스크롤 밖). 모습은 컨트롤러(`PhotoBoard`)가 정하고 여기서는 그린다."""

    def __init__(self, shell, board):
        super().__init__()
        self.shell, self.board = shell, board
        self.rows = {}                                                            # 사진 번호 → 줄 부품(사진이 지워질 때까지 같은 부품)
        self._previews = {}                                                       # 사진 번호 → (그때의 위치, 그림 또는 None) — 위치는 비교에만 쓰고 어디에도 보이지 않는다
        self._queue = []
        self._making = False
        self.confirm_buttons = []
        self.setAccessibleName(T["pho_title"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(K.SPACE["3"])
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, K.SPACE["2"], 0)
        column.setSpacing(K.SPACE["3"])
        self.title = UI.label(T["pho_title"], "h2", wrap=True)
        self.intro = UI.label(T["pho_intro"], "body", wrap=True)
        self.limits = UI.label("", "small", wrap=True)
        self.limits.set_tone("blue")
        self.count = UI.label("", "h3")
        self.empty = UI.label("", "body", wrap=True)
        self.full = UI.label("", "small", wrap=True)
        self.full.set_tone("orange")
        for widget in (self.title, self.intro, self.limits, self.count, self.empty, self.full):
            column.addWidget(widget)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(K.SPACE["3"])
        column.addWidget(self.rows_host)
        self._build_rejected(column)
        self._build_lists(column)
        column.addStretch(1)
        self.scroll = DialogScroll(body)
        self.scroll.setFocusPolicy(Qt.StrongFocus)                                # 키보드로 스크롤할 수 있게(방향키) — 이름이 있는 Tab 정거장
        self.scroll.setAccessibleName(T["pho_title"])
        self.scroll.setProperty("focus_key", "pho:scroll")
        outer.addWidget(self.scroll, 1)
        self._build_status(outer)
        row = QHBoxLayout()
        row.setSpacing(K.SPACE["2"])
        self.add_button = UI.Button("primary", T["pho_add"], accessible=T["pho_add_a11y"], focus_key="pho:add")
        self.add_button.clicked.connect(lambda _=False: self.shell.photos_pick())
        self.all_button = UI.Button("secondary", T["pho_confirm_all"], accessible=T["pho_confirm_all_a11y"], focus_key="pho:all")
        self.all_button.clicked.connect(lambda _=False: self.act("ask_confirm_all"))
        self.close_button = UI.Button("secondary", T["pho_close"], accessible=T["pho_close_a11y"], focus_key="pho:close")
        self.close_button.clicked.connect(lambda _=False: self.shell.photos_close())
        row.addWidget(self.add_button)
        row.addWidget(self.all_button)
        row.addStretch(1)
        row.addWidget(self.close_button)
        outer.addLayout(row)
        self.refresh()

    # ---- 만들기 ----
    def _build_rejected(self, column):
        self.rejected_host = QWidget()
        box = QVBoxLayout(self.rejected_host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(K.SPACE["1"])
        self.rejected_title = UI.label("", "h3")
        self.rejected_rows = QVBoxLayout()
        self.rejected_rows.setSpacing(K.SPACE["1"])
        self.rejected_clear = UI.Button("ghost", T["pho_rejected_clear"], size="sm", accessible=T["pho_rejected_clear_a11y"], focus_key="pho:rejected-clear")
        self.rejected_clear.clicked.connect(lambda _=False: self.act("clear_rejected"))
        box.addWidget(self.rejected_title)
        box.addLayout(self.rejected_rows)
        box.addWidget(self.rejected_clear, 0, Qt.AlignLeft)
        self.rejected_host.setVisible(False)
        column.addWidget(self.rejected_host)

    def _build_lists(self, column):
        """종류·장소 분위기 목록 고치기 — 접혀 있다(앱을 닫으면 처음 목록으로 돌아간다)."""
        self.lists_toggle = UI.Button("ghost", T["pho_lists_open"], size="sm", accessible=T["pho_lists_a11y"], focus_key="pho:lists")
        self.lists_toggle.clicked.connect(lambda _=False: self._flip_lists())
        column.addWidget(self.lists_toggle, 0, Qt.AlignLeft)
        self.lists_body = QWidget()
        box = QVBoxLayout(self.lists_body)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(K.SPACE["3"])
        self.lists_note = UI.label(T["pho_lists_note"], "caption", wrap=True)
        box.addWidget(self.lists_note)
        self.lists_message = UI.label("", "small", wrap=True)
        box.addWidget(self.lists_message)
        self.lists_parts = {}
        for kind, add_method in (("types", "add_type"), ("settings", "add_setting")):
            title = UI.label("", "h3")
            items = QVBoxLayout()
            items.setContentsMargins(0, 0, 0, 0)
            items.setSpacing(K.SPACE["1"])
            input_box = UI.TextInput(T["pho_lists_new_type_a11y" if kind == "types" else "pho_lists_new_setting_a11y"], placeholder=T["pho_lists_new_type" if kind == "types" else "pho_lists_new_setting"])
            input_box.setProperty("focus_key", f"pho:list-input:{kind}")
            add = UI.Button("secondary", T["pho_lists_add_type" if kind == "types" else "pho_lists_add_setting"], size="sm", accessible=T["pho_lists_add_type_a11y" if kind == "types" else "pho_lists_add_setting_a11y"],
                            focus_key=f"pho:list-add:{kind}")
            add.clicked.connect(lambda _=False, name=add_method, edit=input_box: self._add_label(name, edit))
            input_box.returnPressed.connect(lambda name=add_method, edit=input_box: self._add_label(name, edit))
            line = QHBoxLayout()
            line.setSpacing(K.SPACE["2"])
            line.addWidget(input_box, 1)
            line.addWidget(add, 0)
            box.addWidget(title)
            chip_host = QWidget()
            chip_host.setLayout(items)
            box.addWidget(chip_host)
            box.addLayout(line)
            self.lists_parts[kind] = {"title": title, "items": items, "input": input_box, "add": add, "buttons": []}
        self.lists_body.setVisible(False)
        column.addWidget(self.lists_body)

    def _build_status(self, outer):
        """스크롤 밖 아래의 상태 줄 — 한꺼번에 확인의 확인 줄·안내·되돌리기. 몸이 길어도 늘 보인다."""
        self.status_host = QWidget()
        status = QVBoxLayout(self.status_host)
        status.setContentsMargins(0, 0, K.SPACE["2"], 0)
        status.setSpacing(K.SPACE["2"])
        self.confirm_host = QWidget()
        self.confirm_layout = QVBoxLayout(self.confirm_host)
        self.confirm_layout.setContentsMargins(0, 0, 0, 0)
        self.confirm_layout.setSpacing(K.SPACE["2"])
        self.notice = UI.label("", "small", wrap=True)
        self.undo_button = UI.Button("ghost", T["pho_undo"], size="sm", accessible=T["pho_undo_a11y"], focus_key="pho:undo")
        self.undo_button.clicked.connect(lambda _=False: self.act("undo_remove"))
        self.undo_button.setVisible(False)
        status.addWidget(self.confirm_host)
        status.addWidget(self.notice)
        status.addWidget(self.undo_button, 0, Qt.AlignLeft)
        self.notice.setVisible(False)
        outer.addWidget(self.status_host)

    # ---- 행동(규칙은 core 가 정하고 여기서는 부른 뒤 다시 그린다) ----
    def act(self, name, *args):
        board = self.board
        if board is None:
            return None
        self.flush()                                                              # 칸에 쳐 둔 글(Enter 도 다른 칸으로 가기도 안 한 글)을 먼저 규칙에 넘긴다 — 어떤 길로 눌러도 '글 → 행동' 순서가 같다
        status = getattr(board, name)(*args)
        self.refresh()
        if name == "ask_confirm_all" and status == "ask":
            self.focus_confirm()
        return status

    def commit_text(self, photo_id, field, text):
        board = self.board
        if board is None:
            return None
        status = board.set_text(photo_id, field, text)
        self.refresh()
        return status

    def relink(self, photo_id):
        return self.shell.photos_relink(photo_id)

    def advance(self, photo_id, name):
        """Enter 뒤의 포커스 — 대상 칸에서는 같은 사진의 메모 칸으로, 메모 칸에서는 다음 사진의 대상 칸으로 간다(다음이 없거나 다른 칸이면 그대로 둔다)."""
        cards = self.ordered_cards()
        ids = [card.photo_id for card in cards]
        if photo_id not in ids:
            return
        index = ids.index(photo_id)
        box = None
        if name == "user_subject":
            box = cards[index].note
        elif name == "user_note" and index + 1 < len(cards):
            box = cards[index + 1].subject
        if box is not None:
            box.edit.setFocus(Qt.TabFocusReason)
            self.scroll.ensureWidgetVisible(box, 0, K.SPACE["2"])                    # 칸 전체(이름표·입력 칸·글자 수)를 보이게 한다 — 입력 칸만 넘기면 Qt 는 글자 커서 줄만 맞춘다                  # 프로그램으로 옮긴 포커스는 스크롤이 따라가지 않는다(Tab 은 Qt 가 따라간다) — 다음 사진이 화면 밖이어도 보이게

    def _flip_lists(self):
        opened = not self.lists_body.isVisible()
        self.lists_body.setVisible(opened)
        self.lists_toggle.setText(T["pho_lists_close"] if opened else T["pho_lists_open"])
        self._refit()

    def _add_label(self, method, edit):
        status = self.act(method, edit.text())
        if status == "ok":
            edit.clear()

    def flush(self):
        """닫기 전에 — 아직 규칙에 넘기지 않은 글(Enter 나 다른 칸으로 가지 않고 닫는 경우)을 마지막으로 넘긴다."""
        for card in list(self.rows.values()):
            for box in card.pending_fields():
                box.commit()

    # ---- 그리기 ----
    def refresh(self):
        """컨트롤러의 뷰모델에 맞게 줄·단추·안내를 바꾼다 — 칸의 글은 줄 부품이 지킨다."""
        board = self.board
        if board is None:
            return None
        vm = board.view()
        self.limits.set_text(vm["limits"])
        self.count.set_text(vm["count"]["text"])
        self.count.setAccessibleName(vm["count"]["a11y"])
        self.empty.set_text(vm["empty"])
        self.empty.setVisible(bool(vm["empty"]))
        self.full.set_text(vm["full"])
        self.full.setVisible(bool(vm["full"]))
        self._sync_rows(vm["rows"])
        self._sync_rejected(vm["rejected"])
        self._sync_lists(vm["lists"])
        self.add_button.setEnabled(vm["add"]["enabled"])
        self.all_button.setEnabled(vm["confirm_all"]["enabled"])
        self._rebuild_confirm(vm["confirm_ask"])
        notice = vm["notice"]
        self.notice.set_text(notice["text"] if notice else "")
        self.notice.set_tone(TONE.get(notice["level"], "slate") if notice else "slate")
        self.notice.setVisible(bool(notice))
        self.undo_button.setVisible(bool(vm["undo"]))
        self._queue_previews(vm["rows"])
        self._tab_order()
        self._refit()
        QTimer.singleShot(0, self._refit_later)
        self.shell.photos_card_refresh()
        return vm

    def _sync_rows(self, rows):
        wanted = [row["photo_id"] for row in rows]
        for photo_id in [key for key in self.rows if key not in wanted]:
            card = self.rows.pop(photo_id)
            self._previews.pop(photo_id, None)
            card.hide()
            card.setParent(None)
            card.deleteLater()
        for index, row in enumerate(rows):
            card = self.rows.get(row["photo_id"])
            if card is None:
                card = PhotoRowCard(self, row)
                self.rows[row["photo_id"]] = card
            else:
                card.apply(row)
            if self.rows_layout.indexOf(card) != index:
                self.rows_layout.removeWidget(card)
                self.rows_layout.insertWidget(index, card)

    def _sync_rejected(self, rejected):
        _empty_layout(self.rejected_rows)
        self.rejected_host.setVisible(bool(rejected))
        if not rejected:
            return
        self.rejected_title.set_text(rejected["title"])
        for item in [*rejected["rows"], *rejected["more"]]:                                  # 이름을 보인 줄(많아야 10) + 개수만 센 한두 줄 — 줄 수는 고른 파일 수와 상관없이 일정하다(검증 S T-2)
            line = UI.label(item["text"], "small", wrap=True)
            line.setAccessibleName(item["a11y"])
            line.set_tone("red")
            self.rejected_rows.addWidget(line)
        self.rejected_clear.setText(rejected["clear"])
        self.rejected_clear.setAccessibleName(rejected["clear_a11y"])

    def _sync_lists(self, lists):
        self.lists_message.set_text(lists["notice"]["text"] if lists["notice"] else "")
        self.lists_message.set_tone(TONE.get(lists["notice"]["level"], "slate") if lists["notice"] else "slate")
        self.lists_message.setVisible(bool(lists["notice"]))
        for kind, remove_method in (("types", "remove_type"), ("settings", "remove_setting")):
            part, data = self.lists_parts[kind], lists[kind]
            part["title"].set_text(data["title"])
            _empty_layout(part["items"])
            buttons = []
            for item in data["items"]:
                button = UI.Button("ghost", f"{item['name']} ×", size="sm", accessible=item["a11y"], focus_key=f"pho:list-remove:{kind}:{item['name']}")
                button.setEnabled(bool(item["removable"]))
                button.clicked.connect(lambda _=False, name=item["name"], method=remove_method: self.act(method, name))
                part["items"].addWidget(button, 0, Qt.AlignLeft)
                buttons.append(button)
            part["buttons"] = buttons

    def _rebuild_confirm(self, ask):
        """'모두 확인했어요' 확인 줄 — 뜨면 `{n}장 모두 확인`·`그만두기`. 단추 순서는 (진행, 그만두기) — 마지막이 안전한 쪽이다."""
        _empty_layout(self.confirm_layout)
        self.confirm_buttons = []
        if not ask:
            return
        message = UI.label(ask["text"], "body", wrap=True)
        self.confirm_layout.addWidget(message)
        row = QHBoxLayout()
        row.setSpacing(K.SPACE["2"])
        yes = UI.Button("primary", ask["yes"], accessible=ask["yes_a11y"], focus_key="pho:all-yes")
        yes.clicked.connect(lambda _=False: self.act("confirm_all"))
        no = UI.Button("secondary", ask["no"], accessible=ask["no_a11y"], focus_key="pho:all-no")
        no.clicked.connect(lambda _=False: self.act("cancel_confirm_all"))
        row.addWidget(yes)
        row.addWidget(no)
        row.addStretch(1)
        self.confirm_layout.addLayout(row)
        self.confirm_buttons = [yes, no]

    # ---- 미리보기(한 장씩 차례로 — 창이 멈추지 않게) ----
    def _queue_previews(self, rows):
        for row in rows:
            photo_id = row["photo_id"]
            card = self.rows.get(photo_id)
            if card is None or row["preview"]["blocked"]:
                continue
            path = self.board.local_path(photo_id)
            if row["file"]["state"] != "ok":
                card.preview.clear()
                card.preview.setText(T["pho_preview_none"])
                continue
            known = self._previews.get(photo_id)
            if known is not None and known[0] == path:
                card.set_preview(known[1])
                continue
            if photo_id not in self._queue:
                self._queue.append(photo_id)
                card.show_waiting()
        if self._queue and not self._making:
            self._making = True
            QTimer.singleShot(0, self._make_next)

    def _make_next(self):
        """줄 하나의 미리보기를 만든다 — 큰 PNG·없는 파일은 줄 쪽에서 이미 건너뛰었다. 읽기 도구가 실패해도 그 줄만 '만들지 못했어요' 가 된다."""
        try:
            self._making = False
            board = self.board
            if board is None or not self._queue:
                return
            photo_id = self._queue.pop(0)
            card = self.rows.get(photo_id)
            path = board.local_path(photo_id)
            if card is not None and path:
                try:
                    maker = getattr(self.shell, "photo_preview_maker", None) or make_preview
                    pixmap = maker(path)
                except Exception:                                                    # 읽기 도구가 터져도 이 줄만 안내한다
                    pixmap = None
                self._previews[photo_id] = (path, pixmap)
                card.set_preview(pixmap)
            if self._queue:
                self._making = True
                QTimer.singleShot(0, self._make_next)
        except RuntimeError:                                                         # 그 사이 창이 닫혀 부품이 지워졌다
            self._making = False

    # ---- 탭 순서·크기·포커스 ----
    def ordered_cards(self):
        """줄 부품들을 화면에 보이는 순서(위에서 아래)로 — `rows` 는 넣은 차례라 순서를 바꾸면 달라진다."""
        found = [self.rows_layout.itemAt(index).widget() for index in range(self.rows_layout.count())]
        return [widget for widget in found if widget is not None]

    def _tab_order(self):
        chain = [self.scroll]
        for card in self.ordered_cards():
            chain += card.stops()
        chain += [self.rejected_clear, self.lists_toggle]
        for part in self.lists_parts.values():
            chain += [*part["buttons"], part["input"], part["add"]]
        chain += [*self.confirm_buttons, self.undo_button, self.add_button, self.all_button, self.close_button]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    def _refit(self):
        """모습이 바뀌어 몸·상태 줄의 키가 달라지면 열려 있는 대화상자의 키를 다시 맞춘다."""
        host = self.parentWidget()
        dialog = getattr(self.shell, "dialog", None)
        if host is None or host is not dialog or not dialog.is_open:
            return
        for layout in (self.rows_layout, self.confirm_layout):
            layout.invalidate()
        for widget in (self.rows_host, self.confirm_host, self.status_host, self.scroll.widget(), self.scroll, self):
            widget.updateGeometry()
        dialog.layout_.activate()
        dialog.place()

    def _refit_later(self):
        try:
            self._refit()
        except RuntimeError:                                                          # 그 사이 대화상자가 닫혀 부품이 지워졌다
            pass

    def focus_start(self):
        """열릴 때의 첫 포커스 — 사진이 없으면 `사진 추가`, 있으면 첫 사진의 대상 칸."""
        cards = self.ordered_cards()
        target = cards[0].subject.edit if cards else self.add_button
        target.setFocus(Qt.OtherFocusReason)

    def focus_confirm(self):
        """확인 줄이 떴을 때 — 안전한 쪽(그만두기)에 포커스를 둔다. 없으면 닫기 단추."""
        target = self.confirm_buttons[-1] if self.confirm_buttons else self.close_button
        QTimer.singleShot(0, lambda widget=target: self._focus_later(widget))
        target.setFocus(Qt.OtherFocusReason)

    @staticmethod
    def _focus_later(widget):
        try:
            if widget.isEnabled() and widget.isVisible():
                widget.setFocus(Qt.OtherFocusReason)
        except RuntimeError:                                                          # 그 사이 대화상자가 닫혀 부품이 지워졌다
            pass

    # ---- 버리기 ----
    def discard(self):
        """대화상자가 닫히거나 바뀔 때(어느 길로든) — 줄·그림·대기열을 모두 비운다. 여러 번 불러도 같다."""
        self.board = None
        self._queue = []
        self._previews = {}
        try:
            for card in list(self.rows.values()):
                card.hide()
                card.setParent(None)
                card.deleteLater()
            _empty_layout(self.confirm_layout)
            _empty_layout(self.rejected_rows)
        except RuntimeError:                                                          # 이미 지워진 부품
            pass
        self.rows, self.confirm_buttons = {}, []
        return True
