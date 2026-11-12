"""홈의 새 구역 부품(UI-C1d, D-201) — KPI 카드·구역 카드(머리 + 줄)·추천 줄·글 줄(작성 중 초안·최근 발행)·구역 안내·연결 한 줄.

모양을 정하는 값(글·상태·아이콘·계열)은 뷰모델(`ui/core/board_view.py`)이 주고 여기서는 부품(`components.py`·`gauges.py`)으로 조립하기만 한다 — 목록을 거르거나 문구를 만들거나 어떤 상태인지 정하지 않고, Qt 기본 위젯
(`QPushButton`·`QLabel` …)을 직접 만들지도 않는다(시험이 지킨다). 색·글자 크기·반경은 토큰(스타일시트)에서만 오고 여기에 `#rrggbb`·글자 크기·반경이 없다.

- `KpiCard`: 숫자 28px 굵게·이름 13px·보조 글 12px·아이콘 바탕(카드 전체에 강한 색을 칠하지 않는다). 숫자를 모르면 0 이 아니라 `연결 전`·`집계 전` 글이 (큰 숫자 모양이 아니라) 17px 굵은 상태 낱말로 보인다. 눌러서 가는 곳이 없다(포커스도 받지 않는다).
- `BoardRow`: 추천 줄 — 점수 링(숫자만, 44) + 구간 이름(링 옆 글) + 제목 + 관심도(상대값의 방향) 또는 `관심도 데이터 부족` + 채널 열쇠(A·B). 점수가 없으면 링 없이 `점수 계산 전`. 눌러서(Enter·Space 포함) 기존 상세 서랍을 연다.
- `ListRow`: 글 한 줄(제목 + 상태·시각) — 눌리지 않는다(포커스도 받지 않는다). 연한 면(`plain` 카드)이라 눌리는 추천 줄(흰 면·가리키면 바뀜)과 구분된다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.text import T
from . import components as UI
from . import theme
from .gauges import ScoreWithLabel

TONE_COLORS = {"ok": "success_text", "warning": "warning_text", "danger": "danger_text", "muted": "text_secondary"}       # 연결 한 줄의 아이콘 색(글자 대비 4.5 이상인 변형) — 글이 늘 함께 있다
TREND_COLORS = {"up": "success_text", "flat": "warning_text", "down": "danger_text"}                                  # 관심도 아이콘 색 — 글자(상승·보통·하락)와 늘 함께


class KpiCard(QFrame):
    """KPI 카드 하나 — 아이콘 바탕 + 이름 + 숫자(또는 `연결 전`·`집계 전`) + 보조 글. 뷰모델의 KPI 한 칸(`board_view.kpi_vm`)을 그린다."""

    def __init__(self, kpi):
        super().__init__()
        self.setProperty("card", "true")
        self.setMinimumHeight(K.SIZE["kpi_min_h"])
        self.setAccessibleName(kpi["a11y"])
        self.kpi = kpi
        layout = QHBoxLayout(self)
        layout.setContentsMargins(K.SPACE["4"], K.SPACE["4"], K.SPACE["4"], K.SPACE["4"])
        layout.setSpacing(K.SPACE["3"])
        layout.addWidget(UI.ToneSwatch(kpi["icon"], kpi["tone"]), 0, Qt.AlignVCenter)
        body = QVBoxLayout()
        body.setSpacing(0)
        body.addWidget(UI.label(kpi["label"], "small"))
        known = kpi["state"] == "value"
        self.value_label = UI.label(kpi["text"], "metric" if known else "h3")              # 모르는 값(`연결 전`·`집계 전`)은 큰 숫자 모양이 아니라 한 단계 작은 굵은 글 — 흐린 힌트 색이 아니라 읽히는 상태 낱말이다
        if known:
            self.value_label.set_tone(kpi["tone"])
        body.addWidget(self.value_label)
        self.sub_label = UI.label(kpi["sub"], "caption", wrap=True)
        self.sub_label.setVisible(bool(kpi["sub"]))
        body.addWidget(self.sub_label)
        layout.addLayout(body, 1)
        UI.set_card_state(self, "default", layout)                                           # 카드 기본 모습(그림자 `0 2 8`) — 글이 다 들어간 뒤 한 번만 입힌다


def section_card(title, count_text="", badges=(), accessible=None):
    """구역 카드 — 머리(이름 한 줄 + 후보 수 + 작은 배지들) 아래에 줄들이 들어간다. 돌려주는 값: (카드 틀, 줄들이 들어갈 세로 배치). 줄이 모자란 카드가 옆 카드의 높이에 맞춰 늘어나도 줄은 위에 붙어 있다(아래 늘림)."""
    frame, layout = UI.Card((K.SPACE["5"], K.SPACE["4"], K.SPACE["5"], K.SPACE["4"]))
    layout.setSpacing(K.SPACE["2"])
    head = QHBoxLayout()
    head.setSpacing(K.SPACE["2"])
    name = UI.ElidedLabel(title, "h2")                                                      # 긴 이름은 …(줄임표)로 줄고 받은 글이 툴팁에 있다(이미 뷰모델이 가린 뒤 줄인 글이다)
    head.addWidget(name, 1)
    frame.title_label = name
    frame.count_label = None
    if count_text:
        frame.count_label = UI.label(count_text, "caption")
        head.addWidget(frame.count_label, 0, Qt.AlignVCenter)
    for badge in badges:
        head.addWidget(badge, 0, Qt.AlignVCenter)
    layout.addLayout(head)
    rows = QVBoxLayout()
    rows.setSpacing(K.SPACE["1"])
    layout.addLayout(rows)
    frame.rows_layout = rows
    frame.setAccessibleName(accessible or title)
    return frame, layout


def finish_section(frame, layout):
    """구역 카드를 마무리한다 — 맨 아래에 빈칸을 두어 남는 높이를 그쪽이 받게 하고(줄이 늘어나지 않는다) 카드 기본 모습(그림자)을 입힌다. 줄을 다 넣은 뒤 한 번만 부른다."""
    layout.addStretch(1)
    UI.set_card_state(frame, "default", layout)


def interest_label(interest):
    """관심도 — 방향이 있으면 아이콘 + 글자(색과 함께 늘 글자가 있다), 없으면 `관심도 데이터 부족` 글만(읽히는 보조 글 색)."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(K.SPACE["1"])
    text = UI.label(interest["label"], "caption")
    if interest["icon"]:
        row.addWidget(theme.IconWidget(interest["icon"], theme.colors()[TREND_COLORS[interest["trend"]]], K.ICON["badge"]), 0, Qt.AlignVCenter)
        text.setProperty("trend", interest["trend"])
        UI.repolish(text)
    row.addWidget(text, 0, Qt.AlignVCenter)
    box.setAccessibleName(interest["label"])
    box.text_label = text
    return box


class BoardRow(UI.Pressable):
    """추천 줄 하나 — 눌러서(마우스·Enter·Space) 기존 상세 서랍을 연다. `opened(번호)` 신호가 나가고 화면 틀이 서랍을 연다."""
    opened = Signal(str)

    def __init__(self, row, channel_name=""):
        super().__init__(row["a11y"])
        self.setObjectName("row")
        self.row = row
        self.setProperty("focus_key", "detail:" + row["id"])                                # 서랍을 닫으면 포커스가 이 줄로 돌아온다
        self.setMinimumHeight(K.SIZE["board_row_h"])
        self.setAccessibleDescription(T["board_row_hint"])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(K.SPACE["3"], K.SPACE["3"] - 2, K.SPACE["3"], K.SPACE["3"] - 2)
        layout.setSpacing(K.SPACE["3"])
        delta = row["delta"]["value"] if row["delta"] else None
        self.score = ScoreWithLabel(row["score"], delta, "card", missing_text=T["board_score_none"])
        self.score.setMinimumWidth(K.SIZE["board_score_w"])
        layout.addWidget(self.score, 0, Qt.AlignVCenter)
        body = QVBoxLayout()
        body.setSpacing(K.SPACE["1"])
        self.title_label = UI.label(row["title"], "h3", wrap=True)
        body.addWidget(self.title_label)
        self.interest = interest_label(row["interest"])
        body.addWidget(self.interest)
        layout.addLayout(body, 1)
        side = QHBoxLayout()                                                                 # 오른쪽 끝: `예시` 표시(예시 값일 때만)와 채널 열쇠 — 줄 높이를 늘리지 않게 제목·관심도 옆에 둔다
        side.setSpacing(K.SPACE["2"])
        self.sample_badge = None
        if row["sample"]:
            self.sample_badge = UI.Badge("muted", row["sample_tag"])                       # 예시 값에는 `예시` 표시
            self.sample_badge.setProperty("compact", True)                                 # 좁은 자리라 안쪽 여백과 글자를 작게(11px — 사이드바 '준비 중' 과 같다)
            side.addWidget(self.sample_badge, 0, Qt.AlignVCenter)
        self.channel_badge = UI.BlogBadge(row["channel"], row["channel"]) if row["channel"] in ("A", "B") else None             # 채널 열쇠(A·B) — 색과 글자를 함께
        if self.channel_badge is not None:
            self.channel_badge.setAccessibleName(channel_name or row["channel"])
            side.addWidget(self.channel_badge, 0, Qt.AlignVCenter)
        layout.addLayout(side)
        layout.setAlignment(side, Qt.AlignVCenter)
        self.activated.connect(lambda: self.opened.emit(row["id"]))


class ListRow(QFrame):
    """글 한 줄(작성 중 초안·최근 발행) — 제목 한 줄(길면 줄바꿈) + 아래 줄에 상태 배지·시각·예시 표시. 눌리지 않는다."""

    def __init__(self, title, a11y, badge=None, caption="", sample_tag=""):
        super().__init__()
        self.setProperty("card", "plain")
        self.setMinimumHeight(K.SIZE["list_row_h"])
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName(a11y)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(K.SPACE["3"], K.SPACE["2"], K.SPACE["3"], K.SPACE["2"])
        layout.setSpacing(K.SPACE["1"])
        self.title_label = UI.label(title, "body_lg", wrap=True)
        layout.addWidget(self.title_label)
        meta = QHBoxLayout()
        meta.setSpacing(K.SPACE["2"])
        self.badge = None
        if badge:
            self.badge = UI.Badge(badge[0], badge[1])
            meta.addWidget(self.badge, 0, Qt.AlignVCenter)
        self.caption_label = UI.label(caption, "caption") if caption else None
        if self.caption_label is not None:
            meta.addWidget(self.caption_label, 0, Qt.AlignVCenter)
        self.sample_badge = None
        if sample_tag:
            self.sample_badge = UI.Badge("muted", sample_tag)
            meta.addWidget(self.sample_badge, 0, Qt.AlignVCenter)
        meta.addStretch(1)
        layout.addLayout(meta)


def draft_row(row):
    """작성 중 초안 한 줄 — 상태(`초안 생성됨`=정보 배지·`검토 필요`=경고 배지, 색과 글자)와 마지막으로 고친 때."""
    tone = "warning" if row["stage"] == "review" else "ok" if row["stage"] == "saved" else "info"          # 저장됨은 초록 배지 — 색과 함께 글자('저장됨')가 늘 있다
    badge = (tone, row["stage_label"]) if row["stage_label"] else None
    return ListRow(row["title"], row["a11y"], badge, row["time"], row["sample_tag"])


def recent_row(row):
    """최근 발행 한 줄 — 발행한 날짜, 모르면 `발행일 확인 불가`(마지막으로 고친 때로 대신하지 않는다)."""
    return ListRow(row["title"], row["a11y"], None, row["date_text"], row["sample_tag"])


def section_note(icon, tone, title, desc="", extra=None):
    """구역 안내(빈 상태·읽지 못함·읽기 전) — 아이콘 바탕 + 제목 + 짧은 설명(+ 접어 둔 진단 정보). 쓰기 단추는 없다. 이 구역만 이 모습이고 홈 전체는 그대로다."""
    box = QFrame()
    box.setFocusPolicy(Qt.NoFocus)
    row = QHBoxLayout(box)
    row.setContentsMargins(0, K.SPACE["2"], 0, K.SPACE["2"])
    row.setSpacing(K.SPACE["3"])
    row.addWidget(UI.ToneSwatch(icon, tone), 0, Qt.AlignTop)
    column = QVBoxLayout()
    column.setSpacing(K.SPACE["1"])
    box.title_label = UI.label(title, "h3", wrap=True)
    column.addWidget(box.title_label)
    box.desc_label = UI.label(desc, "small", wrap=True) if desc else None
    if box.desc_label is not None:
        column.addWidget(box.desc_label)
    if extra is not None:
        column.addWidget(extra)
    row.addLayout(column, 1)
    box.setAccessibleName(f"{title} {desc}".strip())
    return box


def connection_strip(view):
    """연결 상태 요약 — 머리 줄(아이콘 + 이름 + 예시 표시) 아래에 한 줄 글(설정 묶음 머리와 같은 칩 글 — 폭이 모자라면 줄바꿈). 색·아이콘만이 아니라 글이 늘 함께 있다. 눌러서 가는 곳이 없다.
    (이름과 글을 한 줄에 놓으면 줄바꿈 글의 첫 줄이 이름보다 위에 떠 보여 머리와 글을 위아래로 나눴다.)"""
    frame, layout = UI.Card((K.SPACE["5"], K.SPACE["3"], K.SPACE["5"], K.SPACE["3"]))
    layout.setSpacing(K.SPACE["1"])
    head = QHBoxLayout()
    head.setSpacing(K.SPACE["3"])
    head.addWidget(theme.IconWidget(view["icon"], theme.colors()[TONE_COLORS[view["tone"]]], K.ICON["card"]), 0, Qt.AlignVCenter)
    head.addWidget(UI.label(view["title"], "h3"), 1, Qt.AlignVCenter)
    frame.sample_badge = None
    if view["sample"]:
        frame.sample_badge = UI.Badge("muted", view["sample_tag"])
        head.addWidget(frame.sample_badge, 0, Qt.AlignVCenter)
    layout.addLayout(head)
    text_row = QHBoxLayout()
    text_row.setContentsMargins(K.ICON["card"] + K.SPACE["3"], 0, 0, 0)                      # 아이콘 폭만큼 들여 이름과 왼쪽을 맞춘다
    frame.text_label = UI.label(view["text"], "body", wrap=True)
    text_row.addWidget(frame.text_label, 1)
    layout.addLayout(text_row)
    frame.setAccessibleName(view["a11y"])
    UI.set_card_state(frame, "default", layout)
    return frame
