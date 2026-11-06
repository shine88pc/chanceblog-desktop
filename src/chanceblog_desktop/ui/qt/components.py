"""Qt 공통 부품 — 화면(`screens.py`)은 단추·카드·배지·입력을 Qt 기본 위젯으로 직접 만들지 않고 여기 것을 쓴다(시험이 지킨다).

색·글꼴·크기는 토큰(`ui/core/tokens.py`)→`theme.py` 스타일시트에서만 온다 — 여기서 `setStyleSheet` 로 색을 직접 쓰지 않고 속성(`role`·`kind`·`badge`·`tone` …)만 붙인다.
모든 눌리는 부품은 키보드(Tab·Enter·Space)로 쓸 수 있고 포커스 링이 보이며, 접근 이름(`accessibleName`)을 가진다. 누르는 칸은 36px 이상, 중요한 단추는 40~44px.
고정 폭·높이는 쓰지 않고(최소 크기만) `QLayout`·`QSizePolicy` 로 배치한다 — 그림 칸(썸네일·아이콘)만 예외.
"""
from __future__ import annotations

import html

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent, QColor, QDesktopServices, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.attribution import UTM_SOURCE, check_url, with_utm
from ..core.notify import ToastPolicy
from ..core.part_rules import BADGE_MAX_CHARS, clip_text
from ..core.text import T
from . import theme


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# ---- 글자 ---------------------------------------------------------------------------------------------------------------------
class Label(QLabel):
    """역할(Typography Token) 하나를 가진 글자. 길게 줄바꿈하는 글(`wrap`)은 행간 토큰을 `line-height` 로 적용하며, 글은 항상 **그대로(HTML 이스케이프)** 보인다."""

    def __init__(self, text="", role="body", wrap=False, mono=False):
        super().__init__()
        self._role, self._wrap, self._text = role, wrap, ""
        self.setProperty("role", role)
        if mono:
            self.setFont(theme.font_for("mono", fixed=True))          # 로그·경로·개발 정보 — 고정폭(FixedFont)
            self.setProperty("mono", True)
        if wrap:
            self.setWordWrap(True)
            self.setMinimumWidth(0)
            self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)        # 글이 길어도 칸을 밀어내지 않고 줄을 바꾼다
            self.setTextFormat(Qt.RichText)
        else:
            self.setTextFormat(Qt.PlainText)
        self.set_text(text)

    def set_text(self, text):
        self._text = str(text)
        if self._wrap:
            percent = round(K.type_style(self._role).line_height * 100)
            body = html.escape(self._text).replace("\n", "<br>")
            self.setText(f'<div style="line-height:{percent}%">{body}</div>')
        else:
            self.setText(self._text)

    def plain_text(self):
        return self._text

    def set_tone(self, tone_name):
        self.setProperty("tone", tone_name)
        repolish(self)


def label(text, role="body", wrap=False, mono=False):
    return Label(text, role, wrap, mono)


class ElidedLabel(QLabel):
    """한 줄로 보여 주고 넘치면 …(줄임표)로 줄인다. 마우스를 올리면 **받은 글**이 툴팁으로 나온다 — 받은 글은 뷰모델이 가린 뒤 이미 줄인 글(블로그 이름 30자 + …, 한 줄 설명 300자)이라 그보다 긴 원문은 툴팁에도 없다(키가 반쪽으로 남지 않게 가린 뒤에 자르는 원칙)."""

    def __init__(self, text, role="small"):
        super().__init__(text)
        self.setProperty("role", role)
        self._full = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setToolTip(text)

    def sizeHint(self):
        return QSize(0, self.fontMetrics().lineSpacing() + 2)

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().lineSpacing() + 2)

    def changeEvent(self, event):
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):               # 글꼴이 스타일시트로 정해진 뒤에 한 줄 높이를 다시 잰다
            self.updateGeometry()
        super().changeEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.WindowText))
        painter.drawText(self.rect(), int(Qt.AlignLeft | Qt.AlignVCenter), self.fontMetrics().elidedText(self._full, Qt.ElideRight, self.width()))


# ---- 키보드 포커스에도 보이는 툴팁 -------------------------------------------------------------------------------------------------
class _FocusTooltips(QObject):
    """포커스가 키보드(Tab·Shift+Tab·단축키)로 오면 툴팁을 보인다. 포커스 이벤트가 끝난 다음 차례에 보인다 — 같은 이벤트 안에서 보이면 Qt 가 곧바로 다시 숨긴다."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FocusIn and event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason) and obj.toolTip():
            QTimer.singleShot(0, lambda widget=obj: self._show(widget))
        elif event.type() == QEvent.FocusOut:
            QToolTip.hideText()
        return False

    @staticmethod
    def _show(widget):
        try:
            if widget.hasFocus() and widget.toolTip():
                QToolTip.showText(widget.mapToGlobal(QPoint(0, widget.height() + 4)), widget.toolTip(), widget)
        except RuntimeError:                                                  # 그 사이 다시 그려서 위젯이 지워졌다
            pass


_FOCUS_TOOLTIPS = _FocusTooltips()


def with_tooltip(widget, text):
    """툴팁을 달고, 마우스뿐 아니라 키보드(Tab)로 포커스가 올 때도 보이게 한다."""
    widget.setToolTip(text)
    widget.installEventFilter(_FOCUS_TOOLTIPS)
    return widget


# ---- 단추 ---------------------------------------------------------------------------------------------------------------------
def Button(kind, text, icon_name=None, size=None, accessible=None, focus_key=None):
    """PrimaryButton·SecondaryButton·GhostButton·DangerButton — kind: primary | secondary | ghost | danger | danger_ghost(위험한 3차 행동 — 배경 없는 빨간 글자, 일반 카드의 `제외` 같은 곳).
    size: None(표준 40) | "lg"(큰 주 단추 44) | "sm"(작은 단추 — 누르는 칸 36)."""
    button = QPushButton(text)
    button.setAutoDefault(True)                                           # Enter 로도 눌린다(대화상자 밖의 단추는 기본이 Space 뿐이다)
    button.setProperty("kind", kind)
    if size == "sm":
        button.setProperty("size", "sm")
    button.setMinimumHeight(K.SIZE["hit"] if size == "sm" else K.SIZE["control_primary"] if size == "lg" else K.SIZE["control"])
    button.setCursor(Qt.PointingHandCursor)
    c = theme.colors()
    if icon_name:
        color = {"primary": c["on_primary"], "secondary": c["secondary_text"], "ghost": c["primary_text"], "danger": c["on_primary"], "danger_ghost": c["danger_text"]}[kind]
        side = K.ICON["button_sm"] if size == "sm" else K.ICON["button"]
        button.setIcon(theme.icon(icon_name, color, disabled_color=c["text_disabled"]))
        button.setIconSize(QSize(side, side))
    button.setAccessibleName(accessible or text)
    if focus_key:
        button.setProperty("focus_key", focus_key)
    return button


def IconButton(icon_name, accessible, focus_key=None):
    """아이콘만 있는 단추 — 접근 이름과 툴팁(키보드 포커스에도 보임)이 필수다. 36×36."""
    button = QPushButton()
    button.setAutoDefault(True)
    button.setProperty("kind", "icon")
    button.setIcon(theme.icon(icon_name, theme.colors()["text_secondary"], disabled_color=theme.colors()["text_disabled"]))
    button.setIconSize(QSize(K.ICON["button"], K.ICON["button"]))
    button.setMinimumSize(K.SIZE["icon_button"], K.SIZE["icon_button"])
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    button.setCursor(Qt.PointingHandCursor)
    button.setAccessibleName(accessible)
    with_tooltip(button, accessible)
    if focus_key:
        button.setProperty("focus_key", focus_key)
    return button


def NavButton(text, icon_name, accessible):
    c = theme.colors()
    button = QPushButton("  " + text)                                       # 아이콘과 글자 사이 간격(스타일시트로는 못 정해 앞에 공백을 둔다)
    button.setAutoDefault(True)
    button.setProperty("nav", True)
    button.setCheckable(True)
    button.setMinimumHeight(K.SIZE["menu_h"])
    button.setIcon(theme.icon(icon_name, c["text_secondary"], on_color=c["primary_text"]))
    button.setIconSize(QSize(K.ICON["nav"], K.ICON["nav"]))
    button.setCursor(Qt.PointingHandCursor)
    button.setAccessibleName(accessible)
    return button


def LinkButton(text, accessible=None):
    button = QPushButton(text)
    button.setAutoDefault(True)
    button.setProperty("link", True)
    button.setMinimumHeight(K.SIZE["hit"])
    button.setCursor(Qt.PointingHandCursor)
    button.setAccessibleName(accessible or text)
    return button


# ---- 칩·배지 ------------------------------------------------------------------------------------------------------------------
def FilterChip(text, count, active, focus_key=None):
    """칩 — 보이는 높이 34, 누르는 칸 36."""
    chip = QPushButton(f"{text}  {count}" if count is not None else text)
    chip.setAutoDefault(True)
    chip.setProperty("chip", True)
    chip.setCheckable(True)
    chip.setChecked(bool(active))
    chip.setMinimumHeight(K.SIZE["hit"])
    chip.setCursor(Qt.PointingHandCursor)
    chip.setAccessibleName(f"{text} {count}" if count is not None else text)
    if focus_key:
        chip.setProperty("focus_key", focus_key)
    return chip


def KeywordChip(text):
    chip = label(text)
    chip.setProperty("kw", True)
    chip.setMinimumHeight(K.SIZE["badge_h"])
    chip.setAlignment(Qt.AlignCenter)
    return chip


def Badge(kind, text):
    """배지 — kind: a · b(블로그, 색과 글자를 함께) · ok · warning · danger · info · muted(상태 배지는 색만이 아니라 늘 글자를 함께 쓴다)."""
    badge = QLabel(text)
    badge.setProperty("badge", kind)
    badge.setAlignment(Qt.AlignCenter)
    badge.setMinimumHeight(K.SIZE["badge_h"])
    badge.setAccessibleName(text)
    return badge


class SemanticBadge(QLabel):
    """의미별 배지(공공데이터·추천·해외비교·문화행사·가격변화·여행·기술·정책·생활·주의·차단 — `K.BADGE_KINDS`) — **색과 글자를 함께**(색만으로 뜻을 알리지 않는다), 한 줄, 높이 24.
    글이 길면 `…` 로 줄이고(`BADGE_MAX_CHARS`) 전체는 툴팁에 둔다. 모르는 종류는 ValueError(코드 실수). 글을 안 주면 그 종류의 한국어 이름이 글이다."""

    def __init__(self, kind, text=None):
        if kind not in K.BADGE_KINDS:
            raise ValueError(f"배지 종류가 아니에요: {kind!r}")
        name = K.badge_label(kind)
        full = " ".join(str(text if text else name).split())
        shown = clip_text(full, BADGE_MAX_CHARS)
        super().__init__(shown)
        self.kind, self.full_text = kind, full
        self.setProperty("semantic", kind)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(K.SIZE["badge_h"])
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setAccessibleName(name if full == name else f"{name}: {full}")
        if shown != full:
            self.setToolTip(full)


def BlogBadge(blog, text):
    """블로그 A·B 배지 — 색만이 아니라 글자('블로그 A')도 함께 보인다."""
    return Badge(blog.lower(), text)


def SampleBadge(on_click=None, tip=None):
    """'예시 데이터' 표시 — 눌러서(Enter·Space 포함) 설명을 볼 수 있다. `tip` 은 화면마다 다른 한 줄 설명(없으면 홈의 설명)."""
    badge = QPushButton(T["sample_tag"])
    badge.setAutoDefault(True)
    badge.setProperty("badge", "warning")
    badge.setMinimumHeight(K.SIZE["hit"])
    badge.setCursor(Qt.PointingHandCursor)
    badge.setAccessibleName(T["sample_tag"])
    with_tooltip(badge, tip or T["sample_tip"])
    if on_click:
        badge.clicked.connect(on_click)
    return badge


def Trend(trend):
    """상승·보통·하락 — 아이콘 + 글자(색만으로 구분하지 않는다)."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    c = theme.colors()
    color = {"up": c["success_text"], "flat": c["warning_text"], "down": c["danger_text"]}.get(trend["key"])
    if trend["icon"]:
        layout.addWidget(theme.IconWidget(trend["icon"], color, K.ICON["trend"]))
    text = label(trend["label"])
    text.setProperty("trend", trend["key"])
    layout.addWidget(text)
    layout.addStretch(1)
    box.setAccessibleName(f"{T['d_trend']} {trend['label']}")
    return box


# ---- 카드·배치 -----------------------------------------------------------------------------------------------------------------
def Card(padding=(24, 20, 24, 20), kind="true"):
    frame = QFrame()
    frame.setProperty("card", kind)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*padding)
    layout.setSpacing(12)
    return frame, layout


def set_card_state(frame, state, layout=None):
    """카드 틀에 상태(`default` 기본·`hover` 가리킴·`selected` 선택 — 선택은 2px 파란 테두리)와 그림자를 입힌다. 값은 `theme.card_look`(토큰)에서만 온다 — 상태를 정하는 한 곳.
    테두리가 두꺼워진 만큼 안쪽 여백을 줄여(`layout` 을 주면) 안의 글이 밀리지 않게 한다. 그림자는 틀 하나에만 입힌다(번짐이 잘리지 않게 부모에 여백이 있어야 한다)."""
    look = theme.card_look(state)
    frame.setProperty("card", "true")
    frame.setProperty("cardstate", state)
    if layout is not None:
        base = frame.property("_base_margins")
        if base is None:
            margins = layout.contentsMargins()
            base = (margins.left(), margins.top(), margins.right(), margins.bottom())
            frame.setProperty("_base_margins", base)
        extra = look.border_px - theme.card_look("default").border_px
        layout.setContentsMargins(*(max(0, value - extra) for value in base))
    frame.setGraphicsEffect(theme.shadow_effect(look.shadow, frame))
    repolish(frame)
    return look


class FlowLayout(QLayout):
    """칩처럼 폭이 모자라면 다음 줄로 넘어가는 배치."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items, self._space = [], spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _layout(self, rect, dry):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._space, 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._space
            line = max(line, hint.height())
        return y + line - rect.y()


def chip_row(widgets):
    box = QWidget()
    flow = FlowLayout(box, 8)
    flow.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        flow.addWidget(widget)
    return box


# ---- 아이콘 바탕·이미지 자리 표시 -------------------------------------------------------------------------------------------------
class ToneSwatch(QWidget):
    """색 계열 바탕(둥근 사각형) 가운데에 아이콘 — 요약 카드·빠른 작업의 아이콘."""

    def __init__(self, icon_name, tone_name, glyph=None, box=None):
        super().__init__()
        self._icon, self._tone = icon_name, tone_name
        self._glyph = glyph or K.ICON["card"]
        side = box or K.ICON["box"]
        self.setMinimumSize(side, side)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def sizeHint(self):
        return self.minimumSize()

    def paintEvent(self, _event):
        c = theme.colors()
        strong, soft, _text, _end = K.tone(c, self._tone)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(soft))
        painter.drawRoundedRect(QRectF(self.rect()), K.ICON["box_radius"], K.ICON["box_radius"])
        side = self._glyph
        theme.renderer(self._icon, strong).render(painter, QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side))


class ImagePlaceholder(QWidget):
    """주제 이미지 자리 표시 — 주제 색 그라디언트 + 아이콘. 실제 사진이 없거나 못 불러와도 깨진 그림 대신 이 부품이 나온다.
    `wide` 는 16:9(패널용, 폭에 맞춰 높이가 정해진다). 설명은 접근 이름과 툴팁에 있다."""

    def __init__(self, thumb, wide=False):
        super().__init__()
        self._t, self._wide = thumb, wide
        if wide:
            policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            policy.setHeightForWidth(True)
            self.setSizePolicy(policy)
            self.setMinimumWidth(160)
        else:
            self.setMinimumSize(K.SIZE["thumb"], K.SIZE["thumb"])
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAccessibleName(f"{thumb['label']}. {thumb['state_text']}")
        self.setToolTip(thumb["state_text"])

    def hasHeightForWidth(self):
        return self._wide

    def heightForWidth(self, width):
        return round(width * 9 / 16)

    def sizeHint(self):
        return QSize(288, 162) if self._wide else self.minimumSize()

    def paintEvent(self, _event):
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h, radius = self.width(), self.height(), K.SIZE["thumb_radius"]
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        strong, soft, _text, end = K.tone(c, self._t["tone"])
        gradient = QLinearGradient(0, 0, w, h)
        gradient.setColorAt(0, QColor(soft))
        gradient.setColorAt(1, QColor(end))
        painter.fillPath(path, gradient)
        side = 44 if self._wide else 28
        theme.renderer(self._t["icon"], strong).render(painter, QRectF((w - side) / 2, (h - side) / 2, side, side))


# ---- 눌리는 틀(카드·행) ---------------------------------------------------------------------------------------------------------
class Pressable(QFrame):
    """마우스로 누르거나 키보드(Enter·Space)로 열 수 있는 틀 — 목록 행·요약 카드·빠른 작업이 쓴다. 포커스 링은 스타일시트(:focus)가 그린다."""
    activated = Signal()

    def __init__(self, accessible):
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(accessible)
        self._down = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._down = True
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._down and event.button() == Qt.LeftButton:
            self._down = False
            if self.rect().contains(event.position().toPoint()):
                self.activated.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
        else:
            super().keyPressEvent(event)


class SummaryCard(Pressable):
    """요약 카드 — 아이콘 바탕·숫자에만 색(카드 전체를 칠하지 않는다). `go` 가 있으면 눌러서 그 화면으로 간다."""
    clicked = Signal(str)

    def __init__(self, card):
        super().__init__(card["a11y"])
        self.setProperty("card", "true")
        self._go = card["go"]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.setMinimumHeight(K.SIZE["sum_min_h"])
        layout.addWidget(ToneSwatch(card["icon"], card["tone"]), 0, Qt.AlignVCenter)
        body = QVBoxLayout()
        body.setSpacing(0)
        body.addWidget(label(card["label"], "small"))
        value = label(card["value"], "muted" if card["missing"] else "metric")
        if not card["missing"]:
            value.set_tone(card["tone"])
        body.addWidget(value)
        sub = label(card["sub"], "caption", wrap=True)
        sub.setVisible(bool(card["sub"]))
        body.addWidget(sub)
        layout.addLayout(body, 1)
        if self._go:
            layout.addWidget(theme.IconWidget("arrow_right", theme.colors()["text_muted"], K.ICON["button_sm"]), 0, Qt.AlignVCenter)
        else:
            self.setCursor(Qt.ArrowCursor)
            self.setFocusPolicy(Qt.NoFocus)
        self.activated.connect(lambda: self._go and self.clicked.emit(self._go))


class TopicRow(Pressable):
    """추천 주제 한 줄 — 썸네일 자리 표시·제목·한 줄 설명·키워드 칩·지표·추세·블로그 배지·`초안 만들기`. 행이 좁아지면 지표 칸을 접는다(행 자신의 폭을 본다)."""
    selected = Signal(str)
    draft = Signal(str, str)
    detail = Signal(str)

    def __init__(self, vm, big=False):
        super().__init__(vm["a11y"])
        self.setObjectName("row")
        self.vm = vm
        self.setProperty("selected", bool(vm["selected"]))
        self.setProperty("focus_key", "row:" + vm["id"])
        grid = QHBoxLayout(self)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setSpacing(16)
        self.setMinimumHeight(K.SIZE["row_min_h"])
        grid.addWidget(ImagePlaceholder(vm["thumb"]), 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(vm["title"], "h3", wrap=True))                  # 행 제목 = 카드 제목 역할(C-Type h3 17/600) — 본문 큰 글씨(15/400)로 두면 굵기 위계가 사라진다
        text.addWidget(ElidedLabel(vm["desc"], "small"))
        text.addSpacing(2)
        text.addWidget(chip_row([KeywordChip(k) for k in vm["keywords"]]))
        grid.addLayout(text, 1)
        self.optional = []                                                    # 행이 좁으면 접는 칸(월 검색량·문서 수·추세)
        for key, tip in (("demand", T["tip_demand"]), ("docs", T["tip_docs"])):
            box = QWidget()
            column = QVBoxLayout(box)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(2)
            caption = label(T[key], "caption")
            caption.setToolTip(tip)
            column.addWidget(caption)
            column.addWidget(label(vm[key], "muted" if vm[key + "_missing"] else "body_lg"))
            grid.addWidget(box, 0, Qt.AlignVCenter)
            self.optional.append(box)
        trend = Trend(vm["trend"])
        grid.addWidget(trend, 0, Qt.AlignVCenter)
        self.optional.append(trend)
        side = QVBoxLayout()
        side.setSpacing(6)
        badges = QHBoxLayout()
        badges.setSpacing(6)
        badges.addStretch(1)
        for blog in vm["blogs"]:
            badges.addWidget(BlogBadge(blog["key"], blog["label"]), 0, Qt.AlignVCenter)
        more = IconButton("chevron_right", T["detail_a11y"].format(title=vm["title"]), focus_key="detail:" + vm["id"])
        more.clicked.connect(lambda _=False: self.detail.emit(vm["id"]))
        badges.addWidget(more)
        side.addLayout(badges)
        if big:
            button = Button("primary", T["make_primary"], "arrow_right", size="lg", accessible=T["make_a11y"].format(title=vm["title"]), focus_key="draft:" + vm["id"])
            button.setLayoutDirection(Qt.RightToLeft)                         # 아이콘을 글자 오른쪽에
        else:
            button = Button("secondary", T["make_small"], size="sm", accessible=T["make_a11y"].format(title=vm["title"]), focus_key="draft:" + vm["id"])
        first = vm["blog"]
        button.clicked.connect(lambda _=False: self.draft.emit(vm["id"], first))
        side.addWidget(button, 0, Qt.AlignRight)
        grid.addLayout(side)
        grid.setAlignment(side, Qt.AlignVCenter)
        self.activated.connect(lambda: self.selected.emit(vm["id"]))

    def set_compact(self, compact):
        for widget in self.optional:
            widget.setVisible(not compact)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_compact(self.width() < K.LAYOUT["row_compact_below"])


class QuickAction(Pressable):
    """빠른 작업 한 줄 — 아이콘·제목·한 줄 설명."""

    def __init__(self, item):
        super().__init__(item["title"])
        self.setProperty("quick", "primary" if item["primary"] else "true")
        self.setProperty("focus_key", "quick:" + item["key"])
        self.setMinimumHeight(K.SIZE["control_primary"] + 8)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(12)
        c = theme.colors()
        row.addWidget(theme.IconWidget(item["icon"], c["on_primary"] if item["primary"] else c["text_primary"], K.ICON["card"]), 0, Qt.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(0)
        column.addWidget(label(item["title"], "body_lg"))
        column.addWidget(label(item["desc"], "caption", wrap=True))
        row.addLayout(column, 1)


# ---- 입력·토글 ----------------------------------------------------------------------------------------------------------------
def TextInput(accessible, placeholder=""):
    box = QLineEdit()
    box.setMinimumHeight(K.SIZE["input_h"])
    box.setPlaceholderText(placeholder)
    box.setAccessibleName(accessible)
    return box


class Toggle(QCheckBox):
    """스위치 — Space 로 켜고 끈다. 글자와 함께 보이고 접근 이름을 가진다."""

    def __init__(self, text, accessible=None):
        super().__init__(text)
        self.setAccessibleName(accessible or text)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(K.SIZE["hit"])

    def sizeHint(self):
        return QSize(K.SIZE["toggle_w"] + K.ICON["gap"] + self.fontMetrics().horizontalAdvance(self.text()) + 4, K.SIZE["hit"])

    def paintEvent(self, _event):
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QRectF(0, (self.height() - K.SIZE["toggle_h"]) / 2, K.SIZE["toggle_w"], K.SIZE["toggle_h"])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(c["disabled_bg"] if not self.isEnabled() else c["primary"] if self.isChecked() else c["border_strong"]))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        knob = track.height() - 6
        x = track.right() - knob - 3 if self.isChecked() else track.left() + 3
        painter.setBrush(QColor(c["on_primary"]))
        painter.drawEllipse(QRectF(x, track.top() + 3, knob, knob))
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(c["border_focus"]), 2))
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), track.height() / 2 + 2, track.height() / 2 + 2)
        painter.setPen(QColor(c["text_primary"] if self.isEnabled() else c["text_disabled"]))
        painter.setFont(self.font())
        painter.drawText(QRectF(track.right() + K.ICON["gap"], 0, self.width() - track.right() - K.ICON["gap"], self.height()), int(Qt.AlignLeft | Qt.AlignVCenter), self.text())


# ---- 상태 부품(스켈레톤·빈/오류 상태·배너·진단 영역) ---------------------------------------------------------------------------------
def Skeleton(rows=5, accessible=None):
    """LoadingState — 전체 화면 스피너 대신 행 모양 자리 표시(움직이지 않는다). 접근 이름은 화면마다 다르다(없으면 홈의 `후보를 불러오는 중`)."""
    box = QWidget()
    box.setAccessibleName(accessible or T["loading_a11y"])
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for _ in range(rows):
        row = QFrame()
        row.setObjectName("row")
        row.setProperty("bordered", True)
        inner = QHBoxLayout(row)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(16)
        thumb = QFrame()
        thumb.setObjectName("skel")
        thumb.setMinimumSize(56, 56)
        thumb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        inner.addWidget(thumb)
        lines = QVBoxLayout()
        lines.setSpacing(10)
        for stretch in (2, 3):
            line = QFrame()
            line.setObjectName("skel")
            line.setMinimumHeight(K.SIZE["skeleton_line"])
            line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            lines.addWidget(line)
        inner.addLayout(lines, 1)
        button = QFrame()
        button.setObjectName("skel")
        button.setMinimumSize(110, K.SIZE["control_sm"])
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        inner.addWidget(button)
        layout.addWidget(row)
    return box


class Disclosure(QWidget):
    """접고 펴는 영역 — 기본은 접혀 있다. 진단 정보처럼 보통은 숨겨 둘 내용에 쓴다(고정폭 글꼴). `left` 면 단추를 왼쪽에 붙인다(가운데가 기본)."""

    def __init__(self, show_text, hide_text, content, mono=True, left=False):
        super().__init__()
        self._show, self._hide = show_text, hide_text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.toggle = Button("ghost", show_text, "chevron_down", accessible=show_text)
        self.toggle.clicked.connect(self.flip)
        layout.addWidget(self.toggle, 0, Qt.AlignLeft if left else Qt.AlignHCenter)
        self.body = label(content, "mono", wrap=True, mono=mono)
        self.body.setProperty("mono", True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setVisible(False)
        layout.addWidget(self.body)

    @property
    def is_open(self):
        return self.body.isVisible() or self.body.property("shown") is True

    def flip(self):
        opened = not self.body.isVisible()
        self.body.setVisible(opened)
        self.body.setProperty("shown", opened)
        self.toggle.setText(self._hide if opened else self._show)
        self.toggle.setAccessibleName(self._hide if opened else self._show)
        self.toggle.setIcon(theme.icon("chevron_up" if opened else "chevron_down", theme.colors()["primary_text"]))

    def set_content(self, text):
        self.body.set_text(text)


class Accordion(QWidget):
    """접이식 한 칸 — 머리 한 줄(제목 + 요약 칩)과 몸(펼치면 보이는 위젯). `Disclosure` 와 같은 여닫기 규칙(기본은 접힘, 머리를 누르거나 Enter·Space 로 펴고 접고, 접근 이름이 지금 상태를 말한다)을
    제목·요약 칩이 있는 머리 한 줄로 넓힌 것이다 — 새 키보드 규칙은 없다(머리는 보통 단추 하나라 Tab 한 정거장). 접어 둬도 머리의 칩으로 문제가 보인다.
    펴고 접으면 `toggled(이름, 펼침)` 신호가 나간다(화면 틀이 기억만 하고 다시 그리지 않는다). 칩은 마우스를 받지 않아 칩을 눌러도 머리가 눌린다."""
    toggled = Signal(str, bool)

    def __init__(self, key, title, chips, body, opened=False, open_text="", closed_text="", summary="", focus_key=None):
        super().__init__()
        self.key, self.body, self._title, self._summary, self._texts, self._opened = key, body, title, summary, (closed_text, open_text), bool(opened)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.toggle = QPushButton("  " + title)                                # 아이콘과 글자 사이 간격(스타일시트로는 못 정해 앞에 공백을 둔다 — `NavButton` 과 같다)
        self.toggle.setAutoDefault(True)
        self.toggle.setProperty("acc", True)
        self.toggle.setProperty("focus_key", focus_key or "acc:" + key)
        self.toggle.setMinimumHeight(K.SIZE["acc_h"])
        self.toggle.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self.toggle)                                        # 칩은 머리 단추 위에 얹는다(단추는 제목·아이콘만 그린다)
        row.setContentsMargins(0, 0, 14, 0)
        row.setSpacing(8)
        row.addStretch(1)
        for chip in chips:
            badge = Badge(chip["tone"], chip["text"])
            badge.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(badge, 0, Qt.AlignVCenter)
        self.toggle.clicked.connect(self.flip)
        layout.addWidget(self.toggle)
        layout.addWidget(body)
        self._sync()

    @property
    def is_open(self):
        return self._opened

    def _sync(self):
        self.body.setVisible(self._opened)
        self.toggle.setIcon(theme.icon("chevron_up" if self._opened else "chevron_down", theme.colors()["text_secondary"]))
        self.toggle.setIconSize(QSize(K.ICON["button"], K.ICON["button"]))
        self.toggle.setAccessibleName(", ".join(part for part in (self._title, self._summary, self._texts[1 if self._opened else 0]) if part))
        self.toggle.setProperty("expanded", self._opened)

    def flip(self):
        self._opened = not self._opened
        self._sync()
        self.toggled.emit(self.key, self._opened)


def StateCard(icon_name, tone_name, title, desc, button_text=None, on_click=None, extra=None):
    """EmptyState / ErrorState — 아이콘 + 한 줄 설명 + 다음 행동 단추(+ 접어 둔 진단 정보). 영문 코드는 기본 화면에 없다."""
    frame, layout = Card((32, 40, 32, 40))
    layout.setSpacing(12)
    layout.addWidget(ToneSwatch(icon_name, tone_name, glyph=K.ICON["empty"], box=72), 0, Qt.AlignHCenter)
    head = label(title, "h2", wrap=True)
    head.setAlignment(Qt.AlignCenter)
    layout.addWidget(head)
    sub = label(desc, "sub", wrap=True)
    sub.setAlignment(Qt.AlignCenter)
    layout.addWidget(sub)
    frame.action = None
    if button_text:
        button = Button("primary", button_text, "refresh" if tone_name == "red" else None, size="lg", focus_key="state-action")
        if on_click:
            button.clicked.connect(on_click)
        layout.addWidget(button, 0, Qt.AlignHCenter)
        frame.action = button
    if extra is not None:
        layout.addWidget(extra)
    frame.setAccessibleName(title)
    return frame


def Banner(icon_name, text):
    frame = QFrame()
    frame.setObjectName("banner")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(16, 10, 16, 10)
    layout.setSpacing(10)
    layout.addWidget(theme.IconWidget(icon_name, theme.colors()["warning_text"], K.ICON["button"]), 0, Qt.AlignTop)
    layout.addWidget(label(text, "body", wrap=True), 1)
    frame.setAccessibleName(text)
    return frame


# ---- 출처 표시(Unsplash) ----------------------------------------------------------------------------------------------------
class AttributionRow(QWidget):
    """사진 출처 표시 — `Photo by 작가 on Unsplash`(작가 이름은 프로필, Unsplash 는 홈으로 UTM 이 붙은 링크) + `출처 복사` 단추(두 줄이 복사된다 — 둘째 줄은 사진 페이지 주소).
    복사하면 `copied` 가 나가고 화면 틀이 `출처 복사됨` 토스트를 보인다. 링크는 Unsplash 의 https 주소만 연다."""
    copied = Signal()

    def __init__(self, credit, copy_text, opener=None, source=UTM_SOURCE):
        super().__init__()
        self._credit, self._copy, self._source = credit, copy_text, source
        self._opener = opener or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        home = with_utm("https://unsplash.com/", source)
        name = html.escape(credit.photographer_name)
        self.credit_label = QLabel(f'Photo by <a href="{html.escape(credit.profile_link(source))}">{name}</a> on <a href="{html.escape(home)}">Unsplash</a>')
        self.credit_label.setProperty("role", "small")
        self.credit_label.setTextFormat(Qt.RichText)
        self.credit_label.setOpenExternalLinks(False)
        self.credit_label.setWordWrap(True)
        self.credit_label.setMinimumWidth(0)
        self.credit_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.credit_label.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        self.credit_label.setAccessibleName(f"{T['credit_a11y']}: {credit.first_line()}")
        self.credit_label.linkActivated.connect(self.open_link)
        row.addWidget(self.credit_label, 1)
        self.button = Button("secondary", T["credit_copy"], "copy", size="sm", accessible=T["credit_copy_a11y"], focus_key="credit-copy")
        self.button.clicked.connect(self.copy)
        row.addWidget(self.button)

    def open_link(self, url):
        try:
            self._opener(check_url(url))
        except ValueError:                                              # Unsplash 가 아닌 주소는 열지 않는다
            return

    def copy(self):
        self._copy(self._credit.copy_text(self._source))
        self.copied.emit()


# ---- 토스트·서랍·대화상자 -----------------------------------------------------------------------------------------------------
class Toast(QLabel):
    """안내 토스트 — 아래 가운데에 3~4초 보였다 사라진다. 한 번에 하나만 보이고, 같은 안내가 또 오면 쌓지 않고 보이는 시간만 늘린다(`ToastPolicy`)."""

    def __init__(self, parent, policy=None):
        super().__init__(parent)
        self.policy = policy or ToastPolicy()
        self.setObjectName("toast")
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._expire)

    def show_message(self, text):
        action, text = self.policy.offer(text)
        if action == "ignore":
            return
        if action == "show":
            self.setText(text)
            self.setAccessibleName(text)
            self.place()
            self.show()
            self.raise_()
            QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Alert))      # 화면 읽기 프로그램에 알림
        self._timer.start(self.policy.duration_ms)

    def place(self):
        parent = self.parentWidget()
        self.setMaximumWidth(max(240, min(560, parent.width() - 48)))
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)

    def _expire(self):
        self.policy.expire()
        self.hide()


class Drawer(QFrame):
    """오른쪽에서 밀려 나오는 상세 패널 — Esc·바깥(막) 누르기·닫기 단추로 닫는다(여닫는 데 200ms). 안의 내용은 스크롤된다. 포커스는 안에서만 돈다(`Shell` 이 가둔다)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("drawer")
        self.scrim = QWidget(parent)
        self.scrim.setObjectName("scrim")
        self.scrim.setAttribute(Qt.WA_StyledBackground, True)
        self.scrim.hide()
        self.scrim.mousePressEvent = lambda _e: self.close_requested()
        self.hide()
        self.close_requested = lambda: None
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(K.MOTION_MS["panel"])
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.is_open = False
        self.setAccessibleName(T["drawer_title"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll)

    def set_content(self, widget):
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.scroll.setWidget(widget)

    def width_px(self):
        return min(K.LAYOUT["drawer"], int(self.parentWidget().width() * 0.92))

    def place(self):
        parent = self.parentWidget()
        self.scrim.setGeometry(0, 0, parent.width(), parent.height())
        width = self.width_px()
        self.setGeometry(parent.width() - width if self.is_open else parent.width(), 0, width, parent.height())

    def open(self):
        parent = self.parentWidget()
        width = self.width_px()
        self.scrim.setGeometry(0, 0, parent.width(), parent.height())
        self.scrim.show()
        self.scrim.raise_()
        self.setGeometry(parent.width(), 0, width, parent.height())
        self.show()
        self.raise_()
        self.is_open = True
        self._anim.stop()
        self._anim.setStartValue(QPoint(parent.width(), 0))
        self._anim.setEndValue(QPoint(parent.width() - width, 0))
        self._anim.start()

    def dismiss(self):
        if not self.is_open:
            return
        self.is_open = False
        parent = self.parentWidget()
        self.scrim.hide()
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(QPoint(parent.width(), 0))
        self._anim.start()
        QTimer.singleShot(K.MOTION_MS["panel"] + 20, lambda: None if self.is_open else self.hide())


class Dialog(QFrame):
    """가운데 뜨는 대화상자 — 뒤를 어둡게(scrim) 덮고 안의 위젯만 Tab 으로 돈다. 창 위에 겹쳐 놓는다(별도 창을 만들지 않는다)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("dialog")
        self.scrim = QWidget(parent)
        self.scrim.setObjectName("scrim")
        self.scrim.setAttribute(Qt.WA_StyledBackground, True)
        self.scrim.hide()
        self.hide()
        self.is_open = False
        self._width = K.LAYOUT["dialog"]
        self.setAccessibleName(T["sample_dialog_title"])
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(24, 22, 24, 20)
        self.layout_.setSpacing(12)

    def clear(self):
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def place(self):
        parent = self.parentWidget()
        self.scrim.setGeometry(0, 0, parent.width(), parent.height())
        width = min(self._width, int(parent.width() * 0.94))
        self.setFixedWidth(width)
        self.resize(width, min(max(self.layout_.totalHeightForWidth(width), self.layout_.totalMinimumSize().height()), max(120, parent.height() - 32)))     # 폭이 정해진 뒤의 줄바꿈 높이(창보다 크지 않게)
        self.move((parent.width() - width) // 2, max(16, (parent.height() - self.height()) // 2))

    def present(self, width=None):
        self._width = width or K.LAYOUT["dialog"]
        self.scrim.show()
        self.scrim.raise_()
        self.show()
        self.raise_()
        self.is_open = True
        self.place()

    def dismiss(self):
        self.scrim.hide()
        self.hide()
        self.is_open = False
