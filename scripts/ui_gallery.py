"""부품 모음(개발용) — C-Type 공통 부품(의미별 배지·점수 링·구성 막대·사용량 막대·탭·행동 줄·카드 그림자 3상태)을 **한 화면에** 늘어놓는다. 사용자 화면·메뉴에는 없다(`ui_capture.py --gallery` 와 시험이 쓴다).
샘플 값은 모두 '예시' 로 지은 가짜 값이다(`ui/core/gallery_data.py`) — 실제 이름·블로그·사진·주소·키가 없다. 화면 부품은 토큰에서만 색·크기를 받으므로 여기에도 색·글자 크기를 적지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def build_gallery(width):
    """부품 모음 한 장 — 폭 `width`(논리 px)에 맞춘 위젯과 만든 부품들의 이름표(`parts` 사전: 시험이 종류별 개수를 센다)를 돌려준다."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

    from chanceblog_desktop.ui.core import gallery_data as data, tokens as K
    from chanceblog_desktop.ui.core.text import T
    from chanceblog_desktop.ui.qt import bars, gauges
    from chanceblog_desktop.ui.qt import components as UI

    parts = {"badges": [], "rings_card": [], "rings_detail": [], "bar": None, "usage": [], "tabs": None, "actions": [], "cards": []}
    page = QWidget()
    page.setObjectName("root")
    body = QVBoxLayout(page)
    side = max(K.SPACE["6"], (width - K.LAYOUT["content_max"]) // 2)                  # 넓은 화면에서는 본문을 가운데 한 줄(최대 폭)로 — 정렬 지정 없이 옆 여백으로 맞춘다
    body.setContentsMargins(side, K.SPACE["6"], side, K.SPACE["6"])
    body.setSpacing(K.SPACE["5"])

    head = QHBoxLayout()
    head.setSpacing(K.SPACE["3"])
    head.addWidget(UI.label(T["cd_gallery_title"], "h1"))
    head.addWidget(UI.Badge("warning", T["sample_tag"]))
    head.addStretch(1)
    body.addLayout(head)
    body.addWidget(UI.label(T["cd_gallery_sub"], "sub", wrap=True))

    def section(title, note):
        frame, layout = UI.Card((K.SPACE["6"], K.SPACE["5"], K.SPACE["6"], K.SPACE["5"]))
        layout.setSpacing(K.SPACE["3"])
        layout.addWidget(UI.label(title, "h3"))
        layout.addWidget(UI.label(note, "small", wrap=True))
        body.addWidget(frame)
        return layout

    layout = section("의미별 배지 11종", "색과 글자를 함께 쓰고 한 줄이에요. 글이 길면 …로 줄이고 전체는 툴팁에 있어요.")
    for kind in K.BADGE_KINDS:
        parts["badges"].append(UI.SemanticBadge(kind))
    parts["badges"].append(UI.SemanticBadge("caution", data.LONG_BADGE_TEXT))
    layout.addWidget(UI.chip_row(parts["badges"]))

    layout = section("점수 링 — 카드형", "링 안에는 숫자만 있고, 구간 이름(우선 추천·일반 후보·보류·제외)과 변화량은 링 옆의 글이에요. 데이터 부족은 링을 그리지 않아요.")
    for score, delta in data.SCORE_SAMPLES:
        parts["rings_card"].append(gauges.ScoreWithLabel(score, delta, "card"))
    flow = UI.FlowLayout(spacing=K.SPACE["6"])
    holder = QWidget()
    holder.setLayout(flow)
    flow.setContentsMargins(0, 0, 0, 0)
    for widget in parts["rings_card"]:
        flow.addWidget(widget)
    layout.addWidget(holder)

    layout = section("점수 링 — 상세형", "상세 창 머리에 쓰는 큰 링이에요. 구간 이름과 변화량이 링 아래에 가운데 맞춰 놓여요.")
    row = QHBoxLayout()
    row.setSpacing(K.SPACE["8"])
    for score, delta in ((92, 12), (65, 0), (49, -4), (None, None)):
        widget = gauges.ScoreWithLabel(score, delta, "detail")
        parts["rings_detail"].append(widget)
        row.addWidget(widget)
    row.addStretch(1)
    layout.addLayout(row)

    layout = section("구성 막대", "구성마다 색이 고정이고, 아래에 이름과 숫자를 글자로 함께 적어요. 오른쪽에 큰 총점이 있어요.")
    parts["bar"] = gauges.BarGauge(data.BAR_SAMPLE)
    layout.addWidget(parts["bar"])

    layout = section("사용량 막대", "숫자와 단위를 함께 적어요. 80% 부터 경고색과 `주의`, 90% 부터 위험색과 `위험` 글이 따라와요.")
    for used, limit, unit, title in data.USAGE_SAMPLES:
        bar = gauges.UsageBar(used, limit, unit, title)
        parts["usage"].append(bar)
        layout.addWidget(bar)

    layout = section("탭 줄", "밑줄형이고 고른 탭은 진한 파랑 글자와 2px 밑줄이에요. ←·→·Home·End 로 탭을 옮겨요.")
    parts["tabs"] = bars.TabBar(data.TAB_SAMPLE, "basis")
    layout.addWidget(parts["tabs"])

    layout = section("아래 고정 행동 줄", "주요 행동 1개는 늘 보여요. 폭이 좁아지면 위험·3차 → 보조 순서로 더보기(⋮) 메뉴로 접혀요.")
    actions = [{"key": key, "text": text, "kind": kind} for key, text, kind in data.ACTION_SAMPLE]
    more = [{"key": key, "text": text} for key, text in data.ACTION_MORE_SAMPLE]
    for shown_width in (None, 560, 360):
        row = QVBoxLayout()
        row.setSpacing(K.SPACE["1"])
        row.addWidget(UI.label("폭 " + ("넓게" if shown_width is None else f"{shown_width}px"), "caption"))
        bar = bars.ActionBar(actions, more)
        if shown_width is not None:
            bar.setFixedWidth(shown_width)
        parts["actions"].append(bar)
        row.addWidget(bar, 0, Qt.AlignLeft if shown_width is not None else Qt.Alignment())
        layout.addLayout(row)

    layout = section("카드 그림자 3상태", "기본 · 가리킴 · 선택됨(2px 파란 테두리). 그림자는 카드 틀에만 입히고, 번짐이 잘리지 않게 바깥에 여백을 둬요.")
    row = QHBoxLayout()
    row.setSpacing(K.SPACE["6"])
    for state, caption in (("default", "기본"), ("hover", "가리킴"), ("selected", "선택됨")):
        shell = QWidget()
        inner = QVBoxLayout(shell)
        inner.setContentsMargins(K.SPACE["4"], K.SPACE["3"], K.SPACE["4"], K.SPACE["6"])
        frame, frame_layout = UI.Card((K.SPACE["4"], K.SPACE["4"], K.SPACE["4"], K.SPACE["4"]))
        frame.setMinimumWidth(K.CARD["min_w"])
        frame_layout.addWidget(UI.label(caption, "h3"))
        frame_layout.addWidget(UI.label(T["sample_tag"], "caption"))
        UI.set_card_state(frame, state, frame_layout)
        parts["cards"].append(frame)
        inner.addWidget(frame)
        row.addWidget(shell)
    row.addStretch(1)
    layout.addLayout(row)

    body.addStretch(1)
    page.setFixedWidth(width)
    return page, parts


def fit(page, app, ui_offscreen):
    """폭에 맞는 높이로 맞춘다 — 줄바꿈 글의 높이는 폭에 달려서 계산으로는 모자라게 나오므로(부품이 눌려 잘렸다), 먼저 아주 길게 늘려 부품이 제 크기를 받게 하고 마지막 부품 아래까지만 남긴다(`ui_capture.py` 의 설정 화면 사진과 같은 방식)."""
    from PySide6.QtWidgets import QWidget

    from chanceblog_desktop.ui.core import tokens as K
    page.show()
    page.resize(page.width(), 8000)
    ui_offscreen.settle(app, 8)
    bottom = max(widget.mapTo(page, widget.rect().bottomLeft()).y() for widget in page.findChildren(QWidget) if widget.isVisible()) + K.SPACE["6"]
    page.resize(page.width(), bottom)
    ui_offscreen.settle(app, 6)
    from PySide6.QtWidgets import QApplication
    focus = QApplication.focusWidget()
    if focus is not None:
        focus.clearFocus()                                                         # 창이 처음 활성이 되면 첫 탭에 포커스 링이 그려진다 — 사진에는 링 없는 모습을 담는다(포커스 링은 별도 시험)
        ui_offscreen.settle(app, 3)
    return page


def overflow(page):
    """페이지 오른쪽 끝을 넘어간 위젯의 설명 목록(비어 있으면 가로 스크롤이 생길 일이 없다)."""
    from PySide6.QtWidgets import QWidget
    found = []
    for widget in page.findChildren(QWidget):
        if widget.isVisible() and widget.mapTo(page, widget.rect().topRight()).x() > page.width() + 1:
            found.append(f"{type(widget).__name__} {widget.accessibleName()[:24]!r} 이(가) 오른쪽으로 넘어감")
    return found
