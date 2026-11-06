"""점수 링·구성 막대·사용량 막대 — 계산은 `ui/core/gauges.py`(순수)가 하고 여기서는 그리기만 한다(C-Type §9). 색·글자 크기는 토큰, 여백은 `K.SPACE`.

- `ScoreRing`: 원형 점수 링 — **링 안에는 숫자만**. 구간 이름·변화량은 링 옆·아래의 별도 글(라벨)이라 `ScoreWithLabel` 이 합쳐 준다(카드형·상세형 두 배치). 데이터 부족은 링을 그리지 않는다.
- `BarGauge`: 구성 막대(높이 12·반경 6, 구성마다 고정색) + 아래에 이름·숫자 + 오른쪽에 큰 총점. 색만 보지 않도록 이름과 값이 글자로 늘 함께 있다.
- `UsageBar`: 사용량 막대(높이 8, 80% 경고색·90% 위험색) + `이번 달 12,400 / 27,000회` + `46%`(경고·위험이면 `주의`·`위험` 글도). 모르는 값은 막대 없이 글만(UI-C1b 에서 고침).
`UsageBar` 는 설정 화면의 용도 카드가 쓴다(UI-C1b). 점수 링·구성 막대는 아직 어떤 화면에도 연결하지 않은 독립 부품이다(샘플 값으로 시험·사진을 찍는다).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..core import gauges as G, tokens as K
from ..core.text import T
from . import theme
from .components import Badge, ElidedLabel, label, repolish


class ScoreRing(QWidget):
    """원형 점수 링 — 지름 카드용 44·상세용 72(`size="card"|"detail"` 또는 40~80 의 숫자). 트랙은 옅은 회색, 호는 점수 구간색(80+ 초록·65~79 파랑·50~64 노랑·0~49 빨강), 선 두께는 지름의 11%.
    가운데에는 **숫자만** 그린다. 데이터 부족(점수 없음·범위 밖)은 **아무것도 그리지 않는다** — 0점 링으로 그리지 않는다(실제 0점은 트랙만 있는 링에 `0`)."""

    def __init__(self, score, size="card"):
        super().__init__()
        self.view = G.ring_view(score)
        self.side = G.ring_pixels(size)
        self.setFixedSize(self.side, self.side)
        self.setAccessibleName(G.score_spoken(score))
        self.setToolTip(G.score_spoken(score))

    def sizeHint(self):
        return QSize(self.side, self.side)

    def stroke(self):
        return max(3.0, self.side * K.RING_STROKE_RATIO)

    def number_font(self):
        """가운데 숫자의 글꼴 — 지름이 작으면 18, 크면 22(굵게). 세 자리 숫자(100)처럼 링 안쪽에 안 들어가면 한 자씩 줄인다."""
        font = theme.font_for("score_sm" if self.side < 56 else "score_lg")
        inner = self.side - 2 * self.stroke() - 2 * K.SPACE["1"]
        while font.pixelSize() > 10:
            if QFontMetricsF(font).horizontalAdvance(self.view.text) <= inner:
                break
            font.setPixelSize(font.pixelSize() - 1)
        return font

    def paintEvent(self, _event):
        if not self.view.visible:
            return                                                     # 데이터 부족 — 링도 트랙도 그리지 않는다
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        stroke = self.stroke()
        rect = QRectF(stroke / 2, stroke / 2, self.side - stroke, self.side - stroke)
        painter.setBrush(Qt.NoBrush)
        track = QPen(QColor(c["track"]), stroke)
        painter.setPen(track)
        painter.drawEllipse(rect)
        if self.view.sweep > 0:
            arc = QPen(QColor(c[self.view.band.color_key]), stroke)
            arc.setCapStyle(Qt.RoundCap)
            painter.setPen(arc)
            painter.drawArc(rect, 90 * 16, -round(self.view.sweep * 16))      # 12시 방향에서 시계 방향
        painter.setFont(self.number_font())
        painter.setPen(QColor(c["text_strong"]))
        painter.drawText(QRectF(0, 0, self.side, self.side), int(Qt.AlignCenter), self.view.text)


class ScoreWithLabel(QWidget):
    """점수 링 + 구간 이름 라벨 + 변화량 라벨을 합친 부품. `layout="card"`: 링 오른쪽에 구간 이름(`우선 추천`), 그 아래 줄에 변화량(`▲ +12`) — 카드 아래 줄용(링 44).
    `layout="detail"`: 링(72) 아래에 구간 이름, 그 아래에 변화량을 가운데 맞춰 — 상세 창 머리용. 구간 이름은 구간색의 진한 글자색(대비 4.5 이상)이고 변화량은 상승 초록·하락 빨강·변화 없음 회색 + 글자(▲▼―)다.
    **데이터 부족**이면 링도 변화량도 없이 `데이터 부족` 글만 보인다. 접근 이름은 `점수 92, 우선 추천, 12 상승`."""

    def __init__(self, score, delta=None, layout="card"):
        super().__init__()
        if layout not in ("card", "detail"):
            raise ValueError(f"배치 이름이 아니에요: {layout!r}")
        self.view, self.delta, self.mode = G.ring_view(score), G.delta_view(delta), layout
        card = layout == "card"
        self.ring = self.band_label = self.delta_label = self.missing_label = None
        self.setAccessibleName(G.score_spoken(score, delta))
        outer = QHBoxLayout(self) if card else QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(K.SPACE["3"] if card else K.SPACE["2"])
        if not self.view.visible:
            self.missing_label = label(T["cd_score_missing"], "sub")
            self.missing_label.setMinimumHeight(G.ring_pixels(layout))             # 링이 있을 때와 같은 높이를 지켜 줄이 흔들리지 않게
            self.missing_label.setAlignment(Qt.AlignCenter if not card else Qt.AlignLeft | Qt.AlignVCenter)
            outer.addWidget(self.missing_label)
            return
        self.ring = ScoreRing(score, layout)
        self.band_label = label(self.view.band.name, "small" if card else "body")
        self.band_label.setProperty("scoreband", self.view.band.key)
        repolish(self.band_label)
        if self.delta.kind != "none":
            self.delta_label = label(self.delta.text, "caption" if card else "small")
            self.delta_label.setProperty("delta", self.delta.kind)
            repolish(self.delta_label)
        if card:
            outer.addWidget(self.ring, 0, Qt.AlignVCenter)
            column = QVBoxLayout()
            column.setSpacing(0)
            column.addStretch(1)
            column.addWidget(self.band_label)
            if self.delta_label is not None:
                column.addWidget(self.delta_label)
            column.addStretch(1)
            outer.addLayout(column)
        else:
            outer.addWidget(self.ring, 0, Qt.AlignHCenter)
            for widget in (self.band_label, self.delta_label):
                if widget is not None:
                    widget.setAlignment(Qt.AlignCenter)
                    outer.addWidget(widget, 0, Qt.AlignHCenter)


class _Dot(QWidget):
    """구성 이름 앞의 작은 색 표시(8×8) — 막대의 색과 이름을 이어 준다(색만으로 구분하지 않고 이름·숫자 글자도 늘 함께 있다)."""

    def __init__(self, color_key):
        super().__init__()
        self._key = color_key
        self.setFixedSize(K.SPACE["2"], K.SPACE["2"])
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.colors()[self._key]))
        painter.drawRoundedRect(QRectF(self.rect()), 2, 2)


class _Track(QWidget):
    """막대 한 줄 — 옅은 빈 길(track) 위에 `(폭 비율, 색 키)` 조각들을 왼쪽부터 이어 그린다. `rounded_fill` 이면 채움의 오른쪽 끝도 둥글다(사용량 막대), 아니면 조각을 빈 길 모양으로 잘라 이어 붙인다(구성 막대)."""

    def __init__(self, height, radius, segments, rounded_fill=False):
        super().__init__()
        self._radius, self._segments, self._rounded = radius, tuple(segments), rounded_fill
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        full = QRectF(self.rect())
        painter.setBrush(QColor(c["track"]))
        painter.drawRoundedRect(full, self._radius, self._radius)
        if not self._segments:
            return
        if self._rounded:
            fraction, key = self._segments[0]
            painter.setBrush(QColor(c[key]))
            painter.drawRoundedRect(QRectF(0, 0, max(full.width() * fraction, min(full.width(), self._radius * 2)), full.height()), self._radius, self._radius)
            return
        clip = QPainterPath()
        clip.addRoundedRect(full, self._radius, self._radius)
        painter.setClipPath(clip)
        x = 0.0
        for fraction, key in self._segments:
            width = full.width() * fraction
            painter.setBrush(QColor(c[key]))
            painter.drawRect(QRectF(x, 0, width, full.height()))
            x += width


class BarGauge(QWidget):
    """구성 막대 — `items` 는 `(이름, 값, 종류)`(종류 `base`·`data`·`trend`·`other` 는 색이 고정). 막대 길이는 양수 구성끼리의 비율, 아래에 이름(작은 글·색 표시)과 숫자, 맨 오른쪽에 `최종 점수` 와 큰 총점.
    구성이 하나도 없으면 막대를 그리지 않고 `구성 정보 없음` 만 보인다."""

    def __init__(self, items, total_label=None, total=None, signed=True):
        super().__init__()
        self.view = G.bar_view(items, total_label, total, signed)
        self.setAccessibleName(self.view.spoken)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(K.SPACE["2"])
        self.track = None
        if self.view.empty:
            outer.addWidget(label(self.view.spoken, "sub"))
            return
        self.track = _Track(K.SIZE["gauge_h"], K.RADIUS["gauge"], [(segment.fraction, segment.color_key) for segment in self.view.segments])
        outer.addWidget(self.track)
        row = QHBoxLayout()
        row.setSpacing(K.SPACE["3"])
        self.names = []
        for segment in self.view.segments:
            column = QVBoxLayout()
            column.setSpacing(0)
            head = QHBoxLayout()
            head.setSpacing(K.SPACE["1"])
            head.addWidget(_Dot(segment.color_key), 0, Qt.AlignVCenter)
            name = ElidedLabel(segment.label, "caption")
            head.addWidget(name, 1)
            self.names.append(name)
            column.addLayout(head)
            column.addWidget(label(segment.text, "h3"))
            row.addLayout(column, 1)
        total_column = QVBoxLayout()
        total_column.setSpacing(0)
        caption = label(self.view.total_label, "caption")
        caption.setAlignment(Qt.AlignRight)
        figure = label(self.view.total_text, "h2")
        figure.setAlignment(Qt.AlignRight)
        total_column.addWidget(caption)
        total_column.addWidget(figure)
        row.addLayout(total_column, 1)
        outer.addLayout(row)


class UsageBar(QWidget):
    """사용량 막대 — `이번 달 12,400 / 27,000회` + `46%`(숫자와 단위를 늘 함께). 표시한 퍼센트가 80 이상이면 경고색·90 이상이면 위험색이고 색과 함께 `주의`·`위험`(한도를 넘으면 `한도 넘음`) 글이 붙는다.
    사용량을 모르면(없음·음수·한도 0 이하) **막대를 아예 만들지 않고**(빈 길도 없다 — 빈 길이 남으면 0% 로 읽힌다) `확인할 수 없어요` 글만 보인다(`track` 은 None).
    UI-C1b 에서 고침: 옛 부품은 모르는 값에도 빈 길을 그렸다(UI-C0 독립 검증 M1) — 운영자 2026-11-06 확인 요청 004 의 답 7 '값을 읽지 못하면 Bar 없이 `확인할 수 없어요`'.
    `tag` 는 줄 끝에 붙는 작은 꼬리표(예시 값이면 `예시`)이고 접근 이름에도 같이 들어간다."""

    def __init__(self, used, limit, unit="회", title="", tag=""):
        super().__init__()
        self.view = G.usage_view(used, limit, unit, title)
        self.setAccessibleName(", ".join(part for part in (self.view.spoken, tag) if part))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(K.SPACE["2"])
        row = QHBoxLayout()
        row.setSpacing(K.SPACE["3"])
        self.text_label = ElidedLabel(self.view.text, "body")
        row.addWidget(self.text_label, 1)
        self.percent_label = None
        if self.view.known:
            shown = f"{self.view.state_text} · {self.view.percent_text}" if self.view.state_text else self.view.percent_text
            self.percent_label = label(shown, "body")
            if self.view.state != "ok":
                self.percent_label.setProperty("usage", self.view.state)             # warn | danger — 글자 색(`QLabel[usage]`)
                repolish(self.percent_label)
            row.addWidget(self.percent_label)
        self.tag_label = None
        if tag:
            self.tag_label = Badge("muted", tag)                                         # 예시 값의 꼬리표 — 줄 끝(퍼센트 뒤)
            row.addWidget(self.tag_label, 0, Qt.AlignVCenter)
        outer.addLayout(row)
        self.track = None                                                                # 모르는 값에는 막대(빈 길 포함)가 없다
        if self.view.known:
            fill = [(self.view.fraction, self.view.color_key)] if self.view.fraction > 0 else []
            self.track = _Track(K.SIZE["usage_h"], K.RADIUS["usage"], fill, rounded_fill=True)
            outer.addWidget(self.track)
