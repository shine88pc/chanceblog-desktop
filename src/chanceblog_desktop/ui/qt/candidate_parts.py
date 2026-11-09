"""주제 후보 화면의 부품(P4d) — 후보 카드(`CandidateCard`)·카드 격자(`CandidateGrid`)·고정 상세 창(`DetailPane`)·카드 이미지 자리(`CardImage`)·채널 아바타(`ChannelAvatar`)·줄 수를 줄이는 글(`ClampedLabel`)·키워드 칩(`CardChip`)·점수 구성 한 줄(`FactorRow`).
화면(`candidate_screen.py`)은 뷰모델(`ui/core/candidates_view.py` 가 만든 딕셔너리)을 이 부품으로 조립하기만 하고, 부품은 공통 부품(`components.py`·`gauges.py`)만 쓴다. 색·글꼴·크기·간격은 토큰(`K`·스타일시트)에서만 오고 여기서 인라인 스타일·직접 색·글꼴 이름을 쓰지 않는다
(속성 `candcard`·`selected`·`kw` 만 붙이면 스타일시트가 입힌다). 모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 접근 이름을 가지며 누르는 칸은 36px 이상이다.

카드(C-Type §7): 이미지 자리(**주제 아이콘 + 단색 그라디언트** — 사진 썸네일은 쓰지 않는다) → 배지 최대 둘 → 제목 2줄 → 추천 이유 요약 3줄 → 키워드 칩 최대 셋(+N) → 푸터(채널 아바타·이름 + 점수 링·구간 이름). 점수가 없으면 링 없이 `점수 계산 전`.
카드 하나가 접근 이름 한 줄('제목, 채널, 점수 N점 구간 이름')로 읽히고, 안의 글·배지·링은 따로 읽히지 않는다(상태·주의는 접근 설명에 있다). 카드 그림자는 선택된 카드 하나에만 입힌다(카드 수십 장에 효과를 입히면 스크롤이 느려진다).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from . import theme
from .gauges import ScoreWithLabel, Track


# ---- 줄 수를 줄이는 글 -----------------------------------------------------------------------------------------------------------------
class ClampedLabel(QLabel):
    """여러 줄 글을 `lines` 줄까지만 보이고 넘치면 마지막 줄 끝을 `…` 로 줄인다 — 카드마다 제목·요약 높이가 들쑥날쑥하지 않게 한다. 전체 글은 툴팁에 있다. 글꼴·색은 역할(`role`)의 스타일시트가 정한다.
    줄바꿈은 낱말 단위이고 낱말이 한 줄보다 길면 글자 단위다. 높이는 폭에 따라 정해진다(`heightForWidth`)."""

    def __init__(self, text, role="small", lines=2, tooltip=True):
        super().__init__()
        self.setProperty("role", role)
        self._full, self._max, self._role = str(text), max(1, int(lines)), role
        self.setMinimumWidth(0)
        policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        if tooltip and self._full:
            self.setToolTip(self._full)

    def plain_text(self):
        return self._full

    def _pitch(self):
        return self.fontMetrics().height() * K.type_style(self._role).line_height

    def _lines(self, width):
        """폭 `width` 에서 글이 몇 줄로 나뉘는가 — (시작, 길이) 의 나열."""
        layout = QTextLayout(self._full, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        found = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width))
            found.append((line.textStart(), line.textLength()))
        layout.endLayout()
        return found

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        shown = min(len(self._lines(width)), self._max) if self._full else 1
        return math.ceil(max(1, shown) * self._pitch())

    def sizeHint(self):
        return QSize(0, self.heightForWidth(200))

    def minimumSizeHint(self):
        return QSize(0, math.ceil(self._pitch()))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self.updateGeometry()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.WindowText))
        width, pitch = self.width(), self._pitch()
        metrics = self.fontMetrics()
        found = self._lines(width)
        for index, (start, length) in enumerate(found[:self._max]):
            last = index == self._max - 1 and len(found) > self._max
            text = metrics.elidedText(self._full[start:], Qt.ElideRight, width) if last else self._full[start:start + length].rstrip()
            top = index * pitch + (pitch - metrics.height()) / 2
            painter.drawText(QRectF(0, top, width, metrics.height()), int(Qt.AlignLeft | Qt.AlignVCenter), text)


class CardChip(QLabel):
    """카드의 키워드 칩 — 짧게 줄인 글(뷰모델이 가린 뒤 줄였다)을 한 줄로. 모양은 스타일시트(`kw`)가 입힌다. `+N` 도 같은 모양이다."""

    def __init__(self, text, accessible=None):
        super().__init__(text)
        self.setProperty("kw", True)
        self.setMinimumHeight(K.SIZE["badge_h"])
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setAccessibleName(accessible or text)


# ---- 이미지 자리·아바타 ----------------------------------------------------------------------------------------------------------------
class CardImage(QWidget):
    """카드·상세의 이미지 자리 — **주제 아이콘 + 단색 그라디언트**(빈 회색 상자가 아니다). 사진 썸네일은 쓰지 않는다. 설명(`이미지 검색 전`)은 툴팁에 있고 화면 읽기 프로그램에는 읽히지 않는다(장식이다)."""

    def __init__(self, icon, tone, state_text, height=None, glyph=40, badges=()):
        super().__init__()
        self._icon, self._tone, self._glyph = icon, tone, glyph
        self.setFixedHeight(height or K.CARD["image_h"])
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(state_text)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badges = []
        if badges:                                                                              # 의미 배지는 이미지 위 왼쪽에 얹는다(카드 한 장의 높이를 줄인다 — C-Type §7.2 '이미지 → 상단 의미 배지')
            row = QHBoxLayout(self)
            row.setContentsMargins(K.SPACE["2"], K.SPACE["2"], K.SPACE["2"], K.SPACE["2"])
            row.setSpacing(K.SPACE["2"])
            for badge in badges:
                item = UI.Badge(badge["tone"], badge["text"])
                self.badges.append(item)
                row.addWidget(item, 0, Qt.AlignTop)
            row.addStretch(1)

    def paintEvent(self, _event):
        colors = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height, radius = self.width(), self.height(), K.SIZE["thumb_radius"]
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
        strong, soft, _text, end = K.tone(colors, self._tone)
        gradient = QLinearGradient(0, 0, width, height)
        gradient.setColorAt(0, QColor(soft))
        gradient.setColorAt(1, QColor(end))
        painter.fillPath(path, gradient)
        side = self._glyph
        theme.renderer(self._icon, strong).render(painter, QRectF((width - side) / 2, (height - side) / 2, side, side))


class ChannelAvatar(QWidget):
    """채널 아바타 — 안에 글자 하나(네이버 A·B 는 A·B, 그 밖은 이름의 첫 글자). 채널 색 프리셋은 **테두리와 바탕에만** 쓰고(글자색은 `text_strong`) 프리셋이 없으면 중립색이다. 글자가 늘 함께 있어 색만으로 구분하지 않는다."""

    def __init__(self, letter, preset=None, side=None):
        super().__init__()
        self._letter, self._preset = str(letter)[:1] or "?", preset
        side = side or K.SIZE["avatar"]
        self.setFixedSize(side, side)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        colors, preset = theme.colors(), K.preset_colors(self._preset)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(preset["surface"] if preset else colors["surface_2"]))
        painter.setPen(QPen(QColor(preset["primary"] if preset else colors["border_strong"]), 1.5))
        painter.drawEllipse(rect)
        painter.setPen(QColor(colors["text_strong"]))
        painter.setFont(theme.font_for("micro"))
        painter.drawText(QRectF(self.rect()), int(Qt.AlignCenter), self._letter)


# ---- 후보 카드 ---------------------------------------------------------------------------------------------------------------------------
class CandidateCard(UI.Pressable):
    """후보 카드 한 장 — 전체가 누르는 칸이고(마우스·Enter·Space) 누르면 `opened(번호)` 신호가 나간다. 선택된 카드는 2px 파란 테두리(+ 그림자 하나), 가리키면 테두리 색만 바뀐다. 포커스 링은 스타일시트가 그린다."""
    opened = Signal(str)

    def __init__(self, vm):
        super().__init__(vm["a11y"])
        self.candidate_id = vm["id"]
        self.setProperty("candcard", "true")
        self.setProperty("focus_key", "cand:" + vm["id"])
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(K.CARD["min_w"])
        self._pad = K.CARD["pad"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._pad, self._pad, self._pad, self._pad)
        layout.setSpacing(K.SPACE["2"])
        self._layout = layout
        self.image = CardImage(vm["icon"], vm["tone"], vm["image_state"], badges=vm["badges"])
        self.badges = self.image.badges
        layout.addWidget(self.image)
        self.title_label = ClampedLabel(vm["title"], "h3", 2)
        layout.addWidget(self.title_label)
        self.summary_label = ClampedLabel(vm["summary"], "muted" if vm["summary_missing"] else "small", 3)
        layout.addWidget(self.summary_label)
        self.chips = [CardChip(word) for word in vm["keywords"]]
        self.more_chip = CardChip(vm["more_text"], accessible=vm["more_text"]) if vm["more_text"] else None
        layout.addWidget(UI.chip_row([*self.chips, *([self.more_chip] if self.more_chip is not None else [])]))        # 폭이 모자라면 다음 줄로 넘어간다 — 칩 글이 잘리지 않는다
        layout.addStretch(1)
        footer = QHBoxLayout()
        footer.setSpacing(K.SPACE["2"])
        channel = vm["channel"]
        self.avatar = ChannelAvatar(channel["avatar"], channel["preset"])
        footer.addWidget(self.avatar, 0, Qt.AlignVCenter)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.channel_label = UI.ElidedLabel(channel["name"], "small")
        names.addWidget(self.channel_label)
        self.sample_label = UI.label(vm["sample_tag"], "caption") if vm["sample_tag"] else None
        if self.sample_label is not None:
            names.addWidget(self.sample_label)
        footer.addLayout(names, 1)
        self.score = ScoreWithLabel(vm["score"], None, "card", missing_text=T["cand_score_none"])
        footer.addWidget(self.score, 0, Qt.AlignVCenter)
        layout.addLayout(footer)
        self.activated.connect(lambda: self.opened.emit(self.candidate_id))
        self.update_from(vm)

    def update_from(self, vm):
        """선택 표시와 접근 설명만 그 자리에서 바꾼다(카드를 다시 짓지 않는다)."""
        self.setAccessibleName(vm["a11y"])
        self.setAccessibleDescription(vm["desc"])
        self.set_selected(vm["selected"])

    def set_selected(self, selected):
        selected = bool(selected)
        if bool(self.property("selected")) == selected:
            return
        self.setProperty("selected", selected)
        extra = (K.CARD_STATES["selected"][0] - K.CARD_STATES["default"][0]) if selected else 0
        pad = self._pad - extra
        self._layout.setContentsMargins(pad, pad, pad, pad)                                    # 테두리가 두꺼워진 만큼 안쪽 여백을 줄여 안의 글이 밀리지 않는다
        self.setGraphicsEffect(theme.shadow_effect("selected", self) if selected else None)
        UI.repolish(self)


# ---- 카드 격자 ---------------------------------------------------------------------------------------------------------------------------
class CandidateGrid(QWidget):
    """카드 격자 — **열 수는 규칙이 정한다**(`part_rules.detail_layout`: 3열·2열 — 고정 상세 창이 400 이면 폭이 3열을 담아도 2열이다). 같은 번호의 카드는 다시 짓지 않고 갱신한다(거르기·검색·더 보기 때 빠르다).
    3열일 때 카드는 폭 300 을 넘지 않고(문서 권장 260~300) 격자는 가운데에 놓인다. 비어 있으면 안내 카드 하나, 더 있으면 `더 보기` 단추 하나."""
    opened = Signal(str)
    more = Signal()
    reset = Signal()

    def __init__(self, columns=2, gap=None):
        super().__init__()
        self.setAccessibleName(T["cand_grid_a11y"])
        self._columns, self._gap = columns, gap or K.CARD["gap"]
        self.cards = {}
        self._extras = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(K.SPACE["4"])
        self._outer = outer
        self.holder = QWidget()
        self.grid = QGridLayout(self.holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(self._gap)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self.holder, 1000)
        row.addStretch(1)
        outer.addLayout(row)

    def columns(self):
        return self._columns

    def set_content(self, vm, columns, after=None):
        """카드들(`vm["cards"]`)·빈 화면 안내(`vm["empty"]`)·더 보기(`vm["more"]`)를 지금 열 수로 놓는다. `after` 는 격자 바로 앞의 Tab 정거장(거르기 줄의 마지막) — 글 검색으로 카드를 줄였다 늘려도 Tab 순서가 화면의 읽는 순서(위→아래·왼쪽→오른쪽)를 따르게 한다."""
        self._columns = max(1, int(columns))
        wanted = [card["id"] for card in vm["cards"]]
        for key in [key for key in self.cards if key not in wanted]:
            card = self.cards.pop(key)
            self.grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        for card in self.cards.values():
            self.grid.removeWidget(card)
        for part in self._extras:
            self._outer.removeWidget(part)
            part.hide()
            part.deleteLater()
        self._extras = []
        for index, card_vm in enumerate(vm["cards"]):
            card = self.cards.get(card_vm["id"])
            if card is None:
                card = CandidateCard(card_vm)
                card.opened.connect(self.opened)
                self.cards[card_vm["id"]] = card
            else:
                card.update_from(card_vm)
            self.grid.addWidget(card, index // self._columns, index % self._columns)
        for column in range(max(self.grid.columnCount(), self._columns)):
            self.grid.setColumnStretch(column, 1 if column < self._columns else 0)
        cap = self._columns * K.CARD["w_range"][1] + (self._columns - 1) * self._gap
        self.holder.setMaximumWidth(cap if self._columns == K.FRAME["detail_columns_wide"] else 16777215)
        if vm["empty"] is not None:
            empty = empty_card(vm["empty"], self.reset.emit)
            self._outer.addWidget(empty)
            self._extras.append(empty)
        if vm["more"] is not None:
            button = UI.Button("secondary", vm["more"]["text"], accessible=vm["more"]["a11y"], focus_key="cand-more")
            button.clicked.connect(self.more)
            holder = QWidget()
            inner = QHBoxLayout(holder)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addStretch(1)
            inner.addWidget(button)
            inner.addStretch(1)
            self._outer.addWidget(holder)
            self._extras.append(holder)
        self._order_stops(after)

    def stops(self):
        """격자 안의 Tab 정거장 — 카드(화면의 읽는 순서) → 빈 안내·더 보기 단추."""
        found = []
        for index in range(self.grid.count()):
            card = self.grid.itemAt(index).widget()
            if card is not None:
                row, column = self.grid.getItemPosition(index)[:2]
                found.append((row, column, card))
        extra = [button for part in self._extras for button in part.findChildren(QWidget) if button.focusPolicy() != Qt.NoFocus]
        return [*(card for _row, _column, card in sorted(found, key=lambda item: item[:2])), *extra]

    def _order_stops(self, after):
        chain = [widget for widget in (after, *self.stops()) if widget is not None]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)


def empty_card(vm, on_reset=None):
    """빈 화면 안내 카드 — 아이콘 + 제목 + 설명, 거른 결과가 없을 때만 보조 단추 `거르기 풀기` 하나. **주요 단추는 없다**(주요 행동은 머리의 `후보 만들기` 하나)."""
    frame, layout = UI.Card((K.SPACE["8"], K.SPACE["8"], K.SPACE["8"], K.SPACE["8"]))
    layout.setSpacing(K.SPACE["3"])
    layout.addWidget(UI.ToneSwatch("inbox", "blue", glyph=K.ICON["empty"], box=72), 0, Qt.AlignHCenter)
    head = UI.label(vm["title"], "h2", wrap=True)
    head.setAlignment(Qt.AlignCenter)
    layout.addWidget(head)
    if vm["desc"]:
        sub = UI.label(vm["desc"], "sub", wrap=True)
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)
    frame.action = None
    if vm["reset"]:
        button = UI.Button("secondary", T["cand_filter_reset"], focus_key="cand-empty-reset")
        if on_reset:
            button.clicked.connect(on_reset)
        layout.addWidget(button, 0, Qt.AlignHCenter)
        frame.action = button
    frame.setAccessibleName(vm["title"])
    return frame


# ---- 고정 상세 창 --------------------------------------------------------------------------------------------------------------------------
class DetailPane(QFrame):
    """창 오른쪽에 붙는 고정 상세 창(C-Type §8) — 주제 후보 화면에서 창 논리 폭이 1366 이상일 때만 보인다(그보다 좁으면 서랍). 폭은 규칙(`part_rules.detail_layout`)이 정한다(400~500). 안쪽은 스크롤된다.
    비어 있으면(아무것도 안 골랐으면) 안내 하나만 보인다. 서랍과 같은 내용 부품(`candidate_screen.detail_content`)을 쓴다."""

    def __init__(self):
        super().__init__()
        self.setObjectName("detailpane")
        self.setAccessibleName(T["cand_detail_a11y"])
        self.hide()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setAccessibleName(T["cand_detail_a11y"])
        outer.addWidget(self.scroll)
        self._outer, self._footer = outer, None

    def set_content(self, widget, focusable=True, footer=None):
        """안쪽 내용을 바꾼다. `focusable` 이면 스크롤 영역이 Tab 정거장이라 키보드로 긴 내용을 내려 볼 수 있다(서랍과 같다). 안내만 있을 때는 정거장이 아니다(내릴 것이 없다).
        `footer` 를 주면 스크롤 밖 아래에 붙는다(아래 고정 행동 줄 — 내용이 길어도 늘 보인다, P4e)."""
        old = self.scroll.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        self.scroll.setFocusPolicy(Qt.StrongFocus if focusable else Qt.NoFocus)
        self.scroll.setWidget(widget)
        self._set_footer(footer)

    def _set_footer(self, footer):
        if self._footer is not None:
            self._outer.removeWidget(self._footer)
            self._footer.hide()
            self._footer.setParent(None)                                           # 지워지는 다음 차례까지 이 창의 자식으로 남아 보이거나 Tab 이 가지 않게
            self._footer.deleteLater()
            self._footer = None
        if footer is not None:
            self._outer.addWidget(footer)
            self._footer = footer

    def stops(self):
        """이 창 안의 Tab 정거장(스크롤 영역 → 안쪽 단추 → 아래 고정 행동 줄의 단추) — 읽는 순서."""
        found = [widget for widget in [self.scroll, *self.scroll.findChildren(QWidget)] if widget.focusPolicy() != Qt.NoFocus]
        if self._footer is not None:
            found += [widget for widget in self._footer.findChildren(QWidget) if widget.focusPolicy() != Qt.NoFocus and not widget.isHidden()]      # 줄 안에서 숨겨 둔 `더보기` 단추는 정거장이 아니다
        return found

    def present(self, width):
        self.setFixedWidth(width)
        self.show()

    def dismiss(self):
        self.hide()
        old = self.scroll.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        self._set_footer(None)


# ---- 상세 안쪽의 작은 부품 -------------------------------------------------------------------------------------------------------------
class FactorRow(QWidget):
    """점수 구성 한 줄 — 항목 이름·점수 글(`85점`)·가는 막대(0~100 의 비율)·가중치 작은 글. **평가하지 못한 항목은 막대 없이 `평가 전`** 이다(0점 막대가 아니다). 막대는 구성 막대와 같은 그림 부품이고 색은 하나(`bar_base`)다 —
    사용량 막대처럼 80·90 에서 주의·위험으로 바뀌지 않는다(높은 점수는 경고가 아니다). 이름·점수가 글자로 늘 함께 있다."""

    def __init__(self, vm):
        super().__init__()
        self.setAccessibleName(vm["a11y"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(K.SPACE["1"])
        top = QHBoxLayout()
        top.setSpacing(K.SPACE["3"])
        self.name_label = UI.label(vm["name"], "small")
        top.addWidget(self.name_label, 1)
        self.value_label = UI.label(vm["text"], "muted" if vm["missing"] else "h3")
        top.addWidget(self.value_label)
        layout.addLayout(top)
        self.track = None
        if not vm["missing"]:
            fill = [(vm["fraction"], "bar_base")] if vm["fraction"] > 0 else []
            self.track = Track(K.SIZE["gauge_h"], K.RADIUS["gauge"], fill)
            layout.addWidget(self.track)
        self.weight_label = UI.label(vm["weight_text"], "caption") if vm["weight_text"] else None
        if self.weight_label is not None:
            layout.addWidget(self.weight_label)
