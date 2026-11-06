"""상단 앱 바(UI-C1a, D-171) — 높이 60·자체 제작 잎 아이콘 + `ChanceBlog`(20px) + 한 줄 소개(이름 옆 13px) + 오른쪽 **날짜·시간**. 설정 아이콘·검색·알림·사용자·날씨·자체 창 조절은 만들지 않는다.

- 시계는 **주입**받는다(`clock.now()` — 위젯이 `datetime.now()` 를 직접 부르지 않는다). 시험은 가짜 시계(`FixedClock`)로 분 경계 갱신을 본다.
- 갱신: 분이 바뀔 때 그 글자 하나만 다시 그린다. 타이머는 다음 분 경계까지 남은 시간(+ 30ms)만큼 한 번 기다리고 깨어나서 다시 건다 — 초 단위로 돌지 않는다.
- 좁은 폭: **소개 문구를 먼저 숨기고**, 그래도 모자라면 날짜를 줄인다(`clock.plan_topbar`). 폭은 글자 폭을 실제로 재서 판단한다(125% 배율·글꼴에 강하다). 화면 읽기용 이름에는 늘 전체 날짜가 들어간다.
- 이 바는 화면을 바꿔도 다시 만들지 않는다(틀의 일부) — 시계 글자도 그대로 이어진다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout

from ..core import tokens as K
from ..core.clock import TICK_MARGIN_MS, date_levels, ms_until_next_minute, plan_topbar
from ..core.text import T
from . import components as UI
from . import theme


class TopBar(QFrame):
    def __init__(self, clock):
        super().__init__()
        self._clock = clock
        self.setObjectName("topbar")
        self.setFixedHeight(K.FRAME["app_bar"])
        self.setAccessibleName(T["topbar_a11y"])
        self._gap = K.SPACE["3"]                                                      # 이름·소개·날짜 사이 간격(12)
        row = QHBoxLayout(self)
        row.setContentsMargins(K.SPACE["6"], 0, K.SPACE["6"], 0)
        row.setSpacing(self._gap)
        self.icon = theme.IconWidget("leaf", theme.colors()["primary"], 26)
        self.name = UI.label(T["app_name"], "h2")                                      # 20px 굵게
        self.tagline = UI.label(T["brand_line"], "small")                              # 13px — 이름 옆
        self.date_label = UI.label("", "sub")
        self.date_label.setObjectName("clock")
        for widget in (self.icon, self.name, self.tagline):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(self.date_label)
        self._levels = ("", "", "")
        self._plan = None
        self._timer = QTimer(self)                                                    # 분이 바뀔 때만 깨어난다
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.tick)
        self.tick()

    # ---- 시계 ----
    def tick(self):
        """시계를 읽어 글을 바꾸고(바뀐 것이 있을 때만) 다음 분 경계에 다시 깨어나게 건다. 시험은 이 메서드를 직접 부른다."""
        now = self._clock.now()
        levels = date_levels(now)
        if levels != self._levels:
            self._levels = levels
            self.date_label.setAccessibleName(T["clock_a11y"].format(text=levels[0]))        # 화면 읽기 프로그램에는 늘 전체 날짜
            self._apply()
        self._timer.start(ms_until_next_minute(now) + TICK_MARGIN_MS)

    @property
    def timer(self):
        return self._timer

    @property
    def levels(self):
        return self._levels

    @property
    def plan(self):
        return self._plan

    # ---- 좁은 폭 ----
    def measures(self):
        """폭 판단에 쓴 실제 숫자(px) — (남은 폭, 소개 문구 폭, 날짜 글 단계별 폭, 간격). 시험이 이 숫자로 경계를 만든다."""
        for widget in (self.name, self.tagline, self.date_label):
            widget.ensurePolished()
        margins = self.layout().contentsMargins()
        inner = self.width() - margins.left() - margins.right()
        fixed = self.icon.width() + self.name.sizeHint().width() + 3 * self._gap          # 잎·이름과 그 사이·소개 앞·날짜 앞 간격(소개가 숨어도 남는 것)
        tagline = self.tagline.fontMetrics().horizontalAdvance(T["brand_line"]) + 2
        dates = tuple(self.date_label.fontMetrics().horizontalAdvance(text) + 2 for text in self._levels)
        return inner - fixed, tagline, dates, self._gap

    def _apply(self):
        if self.width() <= 0:                                                          # 아직 놓이기 전 — 폭이 정해지면(resizeEvent) 다시 판단한다
            self.date_label.set_text(self._levels[0])
            return
        available, tagline, dates, gap = self.measures()
        plan = plan_topbar(available, tagline, dates, gap)
        self._plan = plan
        self.tagline.setVisible(plan.show_tagline)
        text = self._levels[plan.level]
        if self.date_label.plain_text() != text:
            self.date_label.set_text(text)
        self.date_label.setToolTip(self._levels[0] if plan.level else "")                  # 줄여 보일 때는 전체 날짜를 말풍선으로

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def changeEvent(self, event):
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._apply()
        super().changeEvent(event)
