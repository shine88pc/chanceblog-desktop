"""홈 모양(UI-C1d)의 Qt 시험 — 창을 띄우지 않고(offscreen) 새 홈(KPI 넷·Naver A·B 추천·작성 중 초안·최근 발행·연결 상태 한 줄)의 **그려진 모습**·배치·키보드를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 값·규칙은 `test_ui_c1d_core.py`·`test_ui_c1c_core.py` 가 PySide6 없이 지킨다(열 수 규칙·뷰모델·서랍 규칙).

운영자 2026-11-06 확인 요청 004 의 답(홈 구성 5·추천 후보 2·최근 발행 6)을 그려진 모습으로 못박는다:
  · 1366×768(100%) 첫 화면에 추천 구역의 첫 줄들이 보이고(스크롤 없이), 1180 최소 폭·125%·150%·최소 창에서 글자 잘림·가로 스크롤·36px 미만 누르는 칸이 없다.
  · 추천 줄: 점수 링(숫자만, 44px, 구간 색)·구간 이름(링 옆)·변화량(이전 점수가 있을 때만)·제목·관심도(또는 `관심도 데이터 부족`)·채널 열쇠(A·B)·`예시` 표시 — 점수가 없으면 링 없이 `점수 계산 전`(0점 링 금지).
  · KPI: 숫자 28px·이름 13px·보조 글 12px·아이콘 바탕, 눌러서 가는 곳이 없다. 구역마다 따로 상태를 가진다(한 구역의 문제가 다른 구역을 막지 않는다).
  · 추천 줄을 누르면 기존 상세 서랍이 열린다. 카드는 기본 모습(그림자)이고 포커스를 받는 줄은 2px 포커스 테두리다.
"""
import datetime
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from chanceblog_desktop.ui.core import gauges as G, part_rules, services, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core.services import BoardData, ChannelRead, DraftRow, HomeData, ListRead, RecentRow, RecommendRow, ServiceFailure  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QGraphicsDropShadowEffect, QLabel, QWidget
    from chanceblog_desktop.ui.core import clock as clock_rules
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import board as board_module
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import gauges as gauge_module
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module

COLORS = tokens.palette()
FRIDAY = datetime.datetime(2026, 11, 6, 20, 10, 0)
SIZES = ((1180, 720), (1366, 768), (1536, 864), (1280, 720), (1920, 1080), (1093, 614), (900, 560))      # 1180 최소 기준·1366(100%)·1536(1920 의 125%)·1280(1920 의 150%)·1920·1093(1366 의 125%)·최소 창


class Fixed(services.HomeProvider):
    """정해 둔 새 구역 값을 돌려주는 공급자 — 실제 이름·값 없이 시험이 지어낸 값만 쓴다."""

    def __init__(self, board, topics=(), sample=False, **extra):
        self.data = HomeData(topics=tuple(topics), sample=sample, board=board, **extra)

    def load_home(self, progress, cancelled):
        return self.data


def rows_of(prefix, scores, interests=None, previous=None, sample=False):
    interests = interests or (None,) * len(scores)
    previous = previous or (None,) * len(scores)
    return tuple(RecommendRow(f"{prefix}{number}", f"{prefix} 예시 주제 {number}", score, before, interest, sample)
                 for number, (score, before, interest) in enumerate(zip(scores, previous, interests, strict=True), start=1))


def board_of(a_rows=(), b_rows=(), drafts=(), recent=(), sample=False):
    return BoardData((ChannelRead("A", "블로그 A", True, "ok", "", tuple(a_rows)), ChannelRead("B", "블로그 B", True, "ok", "", tuple(b_rows))), ListRead("ok", tuple(drafts)), ListRead("ok", tuple(recent)), sample)


def hexed(image, x, y):
    return image.pixelColor(int(x), int(y)).name().upper()


def mixed_board():
    broken = ServiceFailure(text.T["board_err_store"], code="SAMPLE_STORE_UNREADABLE")
    channels = (ChannelRead("A", "블로그 A", True, "failed", "", (), 0, broken), ChannelRead("B", "블로그 B", False, "ok", "", ()))
    recent = ListRead("ok", (RecentRow("p1", "발행한 예시 글", "2026-11-03T01:00:00Z", True), RecentRow("p2", "발행일을 모르는 예시 글", None, True)), 1)
    return BoardData(channels, ListRead("failed", (), 0, ServiceFailure(text.T["board_err_store"], code="SAMPLE_PROJECTS_UNREADABLE")), recent, True)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class QtBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def setUp(self):
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: self.errors.append(f"{kind.__name__}: {value}")

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def make(self, provider=None, size=(1366, 768), **kwargs):
        window = shell_module.AppShell(provider or services.FakeHomeProvider(), autoload=False, clipboard=lambda _t: True, clock=clock_rules.FixedClock(FRIDAY), **kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        window.reload()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10))
        self.settle()
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        self.settle(3)
        return window

    def rows(self, window):
        return window.screen_widget.findChildren(board_module.BoardRow)

    def focus(self, widget):
        window = widget.window()
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)
        widget.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), widget)


class FirstScreenTest(QtBase):
    def inside(self, window, widget):
        viewport = window.scroll.viewport()
        top = widget.mapTo(viewport, widget.rect().topLeft()).y()
        return top >= 0 and top + widget.height() <= viewport.height()

    def test_the_first_rows_of_both_recommendations_are_in_the_first_screen_at_1366x768(self):
        """운영자 지시: 1366×768(100%)에서 핵심 행동(추천 구역의 첫 행들)이 첫 화면에 보인다 — 스크롤하지 않은 채 두 구역의 첫 세 줄이 통째로 들어온다."""
        window = self.make(size=(1366, 768))
        self.assertEqual(window.scroll.verticalScrollBar().value(), 0)
        rows = self.rows(window)
        self.assertEqual(len(rows), 9)
        recommend = [grid for grid in window.screen_widget.findChildren(S.FlowGrid)][1]
        self.assertEqual(recommend._cols, 2)                                                    # 두 구역이 나란히 — 둘 다 첫 화면에 있다
        for group in (rows[:5], rows[5:]):
            for row in group[:3]:
                self.assertTrue(self.inside(window, row), (row.row["title"], row.geometry()))
        self.assertTrue(self.inside(window, window.refresh_button))

    def test_the_first_row_is_visible_at_the_other_required_sizes_too(self):
        for size in ((1280, 720), (1093, 614), (1180, 720), (1536, 864)):
            window = self.make(size=size)
            self.assertTrue(self.inside(window, self.rows(window)[0]), size)

    def test_the_first_three_rows_stay_visible_in_the_client_area_of_a_real_windows_window(self):
        """진짜 윈도 창은 제목 줄·작업 표시줄만큼 낮다(1366×768 화면의 창 안쪽은 약 697) — 그래도 두 구역의 첫 세 줄이 스크롤 없이 보인다. 더 낮은 650 에서도 세 줄이다(D-202 ④)."""
        for size in ((1366, 697), (1366, 650)):
            window = self.make(size=size)
            rows = self.rows(window)
            self.assertEqual(window.scroll.verticalScrollBar().value(), 0)
            for group in (rows[:5], rows[5:]):
                for row in group[:3]:
                    self.assertTrue(self.inside(window, row), (size, row.row["title"]))
            window.close()


class NoClippingTest(QtBase):
    def test_every_size_and_state_has_no_clipped_text_no_small_targets_and_no_horizontal_scroll(self):
        providers = (("정상", lambda: services.FakeHomeProvider()), ("빈", lambda: services.FakeHomeProvider("empty")), ("구역별 상태", lambda: Fixed(mixed_board(), sample=True)),
                     ("연결 전", lambda: services.FakeHomeProvider(board=None)), ("일부만", lambda: services.FakeHomeProvider("partial")))
        for size in SIZES:
            for name, factory in providers:
                window = self.make(factory(), size=size)
                label = f"{size} {name}"
                self.assertEqual(ui_offscreen.find_clipping(window), [], label)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, label)
                for row in self.rows(window):
                    self.assertGreaterEqual(row.height(), tokens.SIZE["board_row_h"], label)             # 누르는 줄은 36px 보다 훨씬 높다(최소 64)
                    self.assertGreaterEqual(row.height(), row.layout().totalHeightForWidth(row.width()), label)       # 눌려 굳지 않았다
                for button in window.screen_widget.findChildren(QAbstractButton):
                    if button.isVisible():
                        self.assertGreaterEqual(button.height(), tokens.SIZE["hit"], f"{label} {button.accessibleName()}")
                window.close()

    def test_the_columns_follow_the_logical_width_at_every_size(self):
        for size in SIZES:
            window = self.make(size=size)
            kpi, recommend, posts = window.screen_widget.findChildren(S.FlowGrid)
            self.assertEqual((kpi._cols, recommend._cols, posts._cols), (part_rules.home_kpi_columns(kpi.width()), part_rules.home_section_columns(recommend.width()), part_rules.home_posts_columns(posts.width())), size)
            window.close()
        wide = self.make(size=(1366, 768))
        kpi, recommend, posts = wide.screen_widget.findChildren(S.FlowGrid)
        self.assertEqual((kpi._cols, recommend._cols, posts._cols), (4, 2, 2))
        narrow = self.make(size=(1180, 720))
        kpi, recommend, posts = narrow.screen_widget.findChildren(S.FlowGrid)
        self.assertEqual((kpi._cols, recommend._cols, posts._cols), (4, 1, 2))
        minimum = self.make(size=(900, 560))
        kpi, recommend, posts = minimum.screen_widget.findChildren(S.FlowGrid)
        self.assertEqual((kpi._cols, recommend._cols, posts._cols), (2, 1, 1))

    def test_the_columns_flip_at_the_window_widths_the_decision_record_names(self):
        """D-202 가 적은 경계 — 창 폭을 1 씩 바꿔 잰 값(세로 스크롤 막대가 있는 홈): 본문 폭 = 창 − 270, KPI 4열 1078·글 구역 2열 1090·추천 2열 1250. 문서의 숫자가 슬며시 낡지 않게 못박는다."""
        window = self.make(size=(1366, 768))
        for width, expected in ((1077, (2, 1, 1)), (1078, (4, 1, 1)), (1089, (4, 1, 1)), (1090, (4, 1, 2)), (1249, (4, 1, 2)), (1250, (4, 2, 2)), (1093, (4, 1, 2))):
            window.resize(width, 768)
            self.settle(3)
            kpi, recommend, posts = window.screen_widget.findChildren(S.FlowGrid)
            self.assertEqual((kpi._cols, recommend._cols, posts._cols), expected, width)
            self.assertEqual(kpi.width(), width - 270, width)


class RowLookTest(QtBase):
    def test_a_row_has_the_ring_the_band_the_change_the_title_the_interest_the_example_tag_and_the_channel_key(self):
        window = self.make(Fixed(board_of(rows_of("가", (92,), ("rising",), (88,), sample=True)), sample=True))
        row = self.rows(window)[0]
        ring = row.findChild(gauge_module.ScoreRing)
        self.assertEqual((ring.width(), ring.height()), (44, 44))                                            # 링 40~44
        self.assertEqual((ring.view.text, ring.view.band.key, ring.children() == []), ("92", "high", True))   # 링 안은 숫자뿐(자식 위젯 없음)·구간은 우선 추천
        score = row.score
        self.assertEqual(score.band_label.text(), "우선 추천")
        self.assertEqual(score.band_label.property("scoreband"), "high")
        self.assertEqual(score.delta_label.text(), "▲ +4")                                                    # 이전 점수가 있어 변화량이 보인다(색과 함께 글자)
        self.assertEqual(row.title_label.plain_text(), "가 예시 주제 1")
        self.assertEqual(row.interest.text_label.text(), "관심도 상승")
        self.assertEqual(row.interest.text_label.property("trend"), "up")
        self.assertEqual((row.sample_badge.text(), row.channel_badge.text(), row.channel_badge.property("badge")), ("예시", "A", "a"))
        self.assertEqual(row.channel_badge.accessibleName(), "블로그 A")                                      # 열쇠 한 글자만 읽히지 않게 채널 이름
        self.assertEqual(row.accessibleName(), row.row["a11y"])
        self.assertEqual(row.accessibleDescription(), text.T["board_row_hint"])
        self.assertEqual(ui_offscreen.find_clipping(window), [])

    def test_a_row_without_a_score_has_no_ring_and_says_the_score_is_not_computed_yet(self):
        window = self.make(Fixed(board_of(rows_of("가", (None, 0), (None, None)))))
        none_row, zero_row = self.rows(window)
        self.assertEqual(none_row.findChildren(gauge_module.ScoreRing), [])                                  # 점수를 모르면 0점 링도 그리지 않는다
        self.assertEqual(none_row.score.missing_label.text(), "점수 계산 전")
        self.assertIsNone(none_row.score.delta_label)
        self.assertEqual(none_row.score.accessibleName(), "점수 계산 전")
        self.assertEqual(none_row.interest.text_label.text(), "관심도 데이터 부족")
        self.assertEqual(len(zero_row.findChildren(gauge_module.ScoreRing)), 1)                              # 진짜 0점은 링이 있다(트랙만 + `0`, 제외 구간)
        self.assertEqual((zero_row.score.ring.view.text, zero_row.score.band_label.text()), ("0", "제외"))
        for row in (none_row, zero_row):
            self.assertIsNone(row.sample_badge)                                                              # 예시가 아니면 예시 표시가 없다

    def test_every_band_uses_the_engine_cutoffs_and_its_own_ring_colour(self):
        scores = (100, 80, 79, 65, 64)
        window = self.make(Fixed(board_of(rows_of("가", scores), rows_of("나", (50, 49, 0)))))
        shown = [(row.score.ring.view.text, row.score.band_label.text(), row.score.ring.view.band.color_key) for row in self.rows(window)]
        self.assertEqual(shown, [("100", "우선 추천", "score_high"), ("80", "우선 추천", "score_high"), ("79", "일반 후보", "score_good"), ("65", "일반 후보", "score_good"), ("64", "보류", "score_mid"),
                                 ("50", "보류", "score_mid"), ("49", "제외", "score_low"), ("0", "제외", "score_low")])
        for cutoff, expected in zip(G.SCORE_CUTOFFS, (80, 65, 50), strict=True):
            self.assertEqual(cutoff, expected)                                                               # 구간 경계는 엔진과 같은 80·65·50

    def test_the_ring_is_painted_with_the_band_colour_and_the_number_only(self):
        window = self.make(Fixed(board_of(rows_of("가", (92, 79, 64, 20)))))
        rings = [row.score.ring for row in self.rows(window)]
        self.settle()
        for ring, key in zip(rings, ("score_high", "score_good", "score_mid", "score_low"), strict=True):
            image = ring.grab().toImage()
            stroke = ring.stroke()
            self.assertEqual(hexed(image, ring.width() / 2, stroke / 2), COLORS[key].upper(), key)           # 12시 방향의 호는 구간 색
            self.assertIn(ring.number_font().pixelSize(), (18, 22))                                          # 가운데 숫자는 18~22

    def test_every_part_keeps_its_minimum_height_so_a_target_never_shrinks_below_the_token(self):
        """눌리는 추천 줄 64·글 줄 56·KPI 카드 96 의 최소 높이는 부품이 스스로 지킨다(안쪽 글이 줄어도 누르는 칸이 36px 아래로 내려가지 않게). 지금은 안쪽 점수 링(44)이 줄 높이를 이미 64 로 만들어
        최소 높이가 겉으로 드러나지 않는다 — 변이 점검이 찾은 틈: 최소 높이 줄을 지워도 시험이 못 잡았다(UI-C1d, D-202)."""
        window = self.make(Fixed(board_of(rows_of("가", (92,)), drafts=(DraftRow("d1", "예시 초안", "review", "2026-11-06T02:10:00Z", False),), recent=(RecentRow("r1", "예시 글", "2026-11-03T01:00:00Z", False),))))
        page = window.screen_widget
        expected = ((board_module.BoardRow, "board_row_h"), (board_module.ListRow, "list_row_h"), (board_module.KpiCard, "kpi_min_h"))
        for kind, key in expected:
            parts = page.findChildren(kind)
            self.assertTrue(parts, key)
            for part in parts:
                self.assertEqual(part.minimumHeight(), tokens.SIZE[key], (kind.__name__, key))
                self.assertGreaterEqual(part.minimumHeight(), tokens.SIZE["hit"] if kind is not board_module.KpiCard else 0)

    def test_the_row_is_a_pressable_with_a_two_pixel_focus_border_and_opens_the_drawer(self):
        window = self.make()
        row = self.rows(window)[1]
        self.assertEqual(row.focusPolicy(), Qt.StrongFocus)
        self.assertNotEqual(hexed(row.grab().toImage(), row.width() / 2, 0), COLORS["border_focus"].upper())
        self.focus(row)
        image = row.grab().toImage()
        self.assertEqual((hexed(image, row.width() / 2, 0), hexed(image, row.width() / 2, 1)), (COLORS["border_focus"].upper(),) * 2)       # 포커스 2px
        opened = []
        row.opened.connect(opened.append)
        QTest.keyClick(row, Qt.Key_Return)
        self.assertEqual(opened, [row.row["id"]])
        self.settle()
        self.assertTrue(window.drawer.is_open)

    def test_a_long_title_wraps_inside_its_row_without_clipping_and_the_row_grows(self):
        long_title = "아주 긴 예시 주제 제목이 한 줄에 다 안 들어가도 줄을 바꿔 보이고 잘리지 않아야 해요 " * 2
        rows = (RecommendRow("long", long_title, 70, None, "flat", False), RecommendRow("short", "짧은 주제", 70, None, "flat", False))
        for size in ((1366, 768), (1180, 720), (900, 560)):
            window = self.make(Fixed(board_of(rows)), size=size)
            long_row, short_row = self.rows(window)
            self.assertGreater(long_row.height(), short_row.height(), size)
            self.assertEqual(ui_offscreen.find_clipping(window), [], size)
            self.assertGreaterEqual(long_row.height(), long_row.layout().totalHeightForWidth(long_row.width()), size)
            window.close()


class KpiLookTest(QtBase):
    def test_the_kpi_cards_show_label_number_and_sub_text_with_the_icon_and_nothing_to_click(self):
        window = self.make()
        cards = window.screen_widget.findChildren(board_module.KpiCard)
        self.assertEqual([(card.kpi["label"], card.kpi["text"]) for card in cards], [("추천 주제", "9개"), ("작성 완료", "3개"), ("발행 완료", "2개"), ("저장된 아이디어", "2개")])
        for card in cards:
            self.assertEqual(card.value_label.property("role"), "metric")                                    # 숫자 28px 굵게
            self.assertEqual(tokens.type_style("metric").size, 28)
            self.assertEqual(card.focusPolicy(), Qt.NoFocus)                                                 # 눌러서 가는 곳이 없다
            self.assertNotEqual(card.cursor().shape(), Qt.PointingHandCursor)
            self.assertEqual(len(card.findChildren(UI.ToneSwatch)), 1)                                       # 아이콘 바탕
            self.assertEqual(card.accessibleName(), card.kpi["a11y"])
            self.assertGreaterEqual(card.height(), tokens.SIZE["kpi_min_h"])

    def test_a_kpi_that_is_not_connected_or_counted_shows_its_word_and_never_a_zero(self):
        window = self.make(services.FakeHomeProvider(board=None))
        first = window.screen_widget.findChildren(board_module.KpiCard)[0]
        self.assertEqual((first.value_label.text(), first.value_label.property("role"), first.sub_label.plain_text()), ("연결 전", "h3", "아직 연결하지 않았어요"))
        failing = self.make(Fixed(mixed_board(), sample=True))
        cards = failing.screen_widget.findChildren(board_module.KpiCard)
        self.assertEqual((cards[0].value_label.text(), cards[0].sub_label.plain_text()), ("집계 전", "아직 집계하지 않아요"))          # 한 채널을 못 읽었으면 일부만 센 수를 합계로 내지 않는다
        for card in cards:
            if card.kpi["state"] != "value":
                self.assertNotEqual(card.value_label.text(), "0개", card.kpi["key"])                           # 모르는 값은 0 이 아니다


class SectionStatesTest(QtBase):
    def test_a_section_that_could_not_be_read_only_blocks_itself(self):
        window = self.make(Fixed(mixed_board(), sample=True))
        page = window.screen_widget
        self.assertEqual(len(page.findChildren(board_module.BoardRow)), 0)                                   # 추천 둘이 모두 줄이 없다(하나는 못 읽음·하나는 꺼짐)
        self.assertEqual(len(page.findChildren(board_module.ListRow)), 2)                                    # 그래도 최근 발행의 두 줄은 그려졌다
        notes = {note.title_label.plain_text(): note for note in page.findChildren(QWidget) if hasattr(note, "title_label") and hasattr(note, "desc_label")}
        self.assertIn(text.T["board_rec_error_title"], notes)
        self.assertIn(text.T["board_rec_off"], notes)
        self.assertIn(text.T["board_draft_error_title"], notes)
        headers = [label.text() for label in page.findChildren(UI.ElidedLabel) if label.property("role") == "h2"]
        self.assertEqual(headers, ["블로그 A 추천", "블로그 B 추천", "작성 중인 초안", "최근 발행"])             # 네 구역 머리가 모두 있다
        self.assertIn("꺼짐", [label.text() for label in page.findChildren(QLabel) if label.property("badge") == "muted"])      # 꺼진 채널은 색이 아니라 글자로
        self.assertIn(text.T["board_posts_skipped"].format(n=1), [label.plain_text() for label in page.findChildren(UI.Label)])
        recent = [row.caption_label.text() for row in page.findChildren(board_module.ListRow)]
        self.assertEqual(recent, ["2026-11-03", "발행일 확인 불가"])                                           # 발행일을 모르면 고친 때로 대신하지 않는다

    def test_the_error_code_of_a_section_is_only_in_the_folded_diagnostics(self):
        window = self.make(Fixed(mixed_board(), sample=True))
        page = window.screen_widget
        visible = " | ".join(label.plain_text() for label in page.findChildren(UI.Label) if label.isVisible())
        for code in ("SAMPLE_STORE_UNREADABLE", "SAMPLE_PROJECTS_UNREADABLE"):
            self.assertNotIn(code, visible)
        disclosures = page.findChildren(UI.Disclosure)
        self.assertEqual(len(disclosures), 2)                                                                # 못 읽은 구역마다 접어 둔 진단 정보
        for disclosure in disclosures:
            self.assertFalse(disclosure.body.isVisible())
        disclosures[0].flip()
        self.settle()
        self.assertIn("SAMPLE_STORE_UNREADABLE", disclosures[0].body.plain_text())
        self.assertEqual([button.text() for button in page.findChildren(QAbstractButton) if button.property("kind") == "primary"], [])         # 구역 안내에는 쓰기·주 단추가 없다

    def test_an_empty_board_draws_normal_empty_sections_without_any_write_button(self):
        window = self.make(services.FakeHomeProvider("empty"))
        self.assertEqual([note.title_label.plain_text() for note in window.screen_widget.findChildren(QWidget) if hasattr(note, "title_label") and hasattr(note, "desc_label")],
                         ["아직 추천할 후보가 없어요.", "아직 추천할 후보가 없어요.", "작성 중인 초안이 없어요.", "아직 발행한 글이 없어요."])
        self.assertEqual({b.accessibleName() for b in window.screen_widget.findChildren(QAbstractButton)}, {"예시 데이터", text.T["refresh"]})


class ListRowLookTest(QtBase):
    def test_a_draft_row_and_a_recent_row_show_the_state_the_time_and_the_example_tag(self):
        """작성 중 초안 줄 = 제목 + 상태 배지(`검토 필요`=경고·`초안 생성됨`=정보 — 색과 글자)와 고친 때(한국 시각), 최근 발행 줄 = 제목 + 발행일(모르면 `발행일 확인 불가`).
        예시 값이면 줄마다 `예시` 꼬리표가 붙고 실제 값이면 없다. 글 줄은 눌리지 않는다(UI-C1d, D-202 — 변이 점검이 찾은 틈: 글 줄의 `예시` 꼬리표가 빠져도 시험이 못 잡았다)."""
        drafts = (DraftRow("d1", "검토할 예시 초안", "review", "2026-11-06T02:10:00Z", True), DraftRow("d2", "방금 만든 예시 초안", "generated", "2026-11-05T09:30:00Z", True),
                  DraftRow("d3", "단계를 모르는 예시 초안", "", "", True))
        recent = (RecentRow("r1", "발행한 예시 글", "2026-11-03T01:00:00Z", True), RecentRow("r2", "날짜를 모르는 예시 글", None, True))
        window = self.make(Fixed(board_of(drafts=drafts, recent=recent, sample=True), sample=True))
        rows = window.screen_widget.findChildren(board_module.ListRow)
        draft_rows, recent_rows = rows[:3], rows[3:]
        self.assertEqual(len(rows), 5)
        self.assertEqual([(row.badge.text(), row.badge.property("badge")) if row.badge else None for row in draft_rows], [("검토 필요", "warning"), ("초안 생성됨", "info"), None])
        self.assertEqual([row.caption_label.text() if row.caption_label else "" for row in draft_rows], ["2026-11-06 11:10", "2026-11-05 18:30", ""])
        self.assertEqual([(row.badge, row.caption_label.text()) for row in recent_rows], [(None, "2026-11-03"), (None, "발행일 확인 불가")])
        for row in rows:
            self.assertEqual(row.sample_badge.text(), "예시")
            self.assertEqual(row.focusPolicy(), Qt.NoFocus)
            self.assertEqual(row.property("card"), "plain")
            self.assertIn("예시", row.accessibleName())
        real = self.make(Fixed(board_of(drafts=(DraftRow("d1", "실제 초안", "review", "2026-11-06T02:10:00Z", False),), recent=(RecentRow("r1", "실제 글", "2026-11-03T01:00:00Z", False),))))
        real_rows = real.screen_widget.findChildren(board_module.ListRow)
        self.assertEqual(len(real_rows), 2)
        for row in real_rows:
            self.assertIsNone(row.sample_badge)                                                              # 예시가 아니면 `예시` 꼬리표가 없다
            self.assertNotIn("예시", row.accessibleName())


class ConnectionLineTest(QtBase):
    def test_the_connection_line_has_the_icon_the_title_the_text_and_the_example_tag(self):
        window = self.make()
        strip = next(frame for frame in window.screen_widget.findChildren(QWidget) if hasattr(frame, "text_label") and frame.property("card") == "true" and not hasattr(frame, "title_label"))
        self.assertEqual(strip.text_label.plain_text(), "연결 상태를 아직 읽지 않았어요. 설정에서 확인할 수 있어요.")
        self.assertEqual(strip.accessibleName(), window.state.home_view()["board"]["connection"]["a11y"])
        self.assertEqual(strip.focusPolicy(), Qt.NoFocus)
        window.go("settings")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10))
        window.go("home")
        self.settle()
        strip = next(frame for frame in window.screen_widget.findChildren(QWidget) if hasattr(frame, "text_label") and frame.property("card") == "true" and not hasattr(frame, "title_label"))
        self.assertIn("준비 중", strip.text_label.plain_text())
        self.assertIsNotNone(strip.sample_badge)                                                             # 예시 연결 정보라 예시 표시
        self.assertEqual(strip.sample_badge.text(), "예시")


class ConnectionWiringTest(QtBase):
    """홈이 열릴 때 설정 정보를 함께 읽는 배선(UI-C1d, D-203) — 앱이 열릴 때(`autoload`)만 한 번. 읽기 전용임은 `test_ui_c1d_core.HomeConnectionsReadTest` 가 넷(없음·옛 구조·깨짐·정상)에서 바이트까지 못박는다.
    여기서는 **진짜 셸**이 그 길로 읽어 한 줄을 채우는지, 실패가 그 한 줄뿐인지, 시험·예시처럼 `autoload` 가 꺼진 창은 읽지 않는지를 본다."""

    def opened(self, provider, size=(1366, 768)):
        """앱이 열리는 것과 같게(`autoload=True`) — 홈 불러오기와 연결 정보 읽기가 자동으로 시작된다."""
        window = shell_module.AppShell(provider, clipboard=lambda _t: True, clock=clock_rules.FixedClock(FRIDAY))
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading" and window.state.conn_load_count >= 1 and not window.state.conn_loading, 15))
        self.settle(8)
        return window

    @staticmethod
    def strip_text(window):
        return window.state.home_view()["board"]["connection"]["text"]

    def test_the_real_shell_reads_the_connections_once_at_start_and_the_line_shows_the_value(self):
        import tempfile
        import service_support as support
        from chanceblog_desktop.ui import adapters
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp, repo="")
            before = (support.tree_snapshot(tmp), dict(ctx.keystore._blobs))
            window = self.opened(adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx))
            self.assertEqual((window.state.conn_load_count, window.state.conn_state), (1, "normal"))
            QTest.qWait(700)                                                                                                       # 독립 검증 UI-C1d L4(변이 Q15): 첫 읽기 직후뿐 아니라 잠시 뒤에도 한 번만 읽었다(늦게 한 번 더 읽는 일이 없다)
            self.assertEqual(window.state.conn_load_count, 1)
            line = window.state.home_view()["board"]["connection"]
            self.assertEqual((line["state"], line["sample"]), ("ready", False))
            self.assertNotIn("연결 상태를 아직 읽지 않았어요", " ".join(label.plain_text() for label in window.screen_widget.findChildren(UI.Label)))      # 화면의 글도 값으로 바뀌었다
            self.assertIn(line["text"], " ".join(label.plain_text() for label in window.screen_widget.findChildren(UI.Label)))
            self.assertEqual((support.tree_snapshot(tmp), dict(ctx.keystore._blobs)), before)                                       # 홈을 여는 것만으로 파일이 하나도 늘거나 바뀌지 않았다

    def test_a_connection_file_that_cannot_be_read_only_changes_its_own_line(self):
        import tempfile
        import service_support as support
        from chanceblog_desktop.service import connections as cn
        from chanceblog_desktop.ui import adapters
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp, repo="")
            cn.add_entry(ctx, "naver_apihub", name="내 키", fields={"client_id": "hubclient001", "client_secret": "A1b2C3d4E5f6G7h8"}, keystore=ctx.keystore)
            ctx.workspace.connections_path.write_text("{ 깨진 연결 설정 ", encoding="utf-8")
            before = support.tree_snapshot(tmp)
            window = self.opened(adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx))
            self.assertEqual(window.state.conn_state, "error")
            labels = [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]
            self.assertIn("연결 상태를 읽지 못했어요.", labels)                                                                      # 그 한 줄만
            self.assertEqual(window.state.list_state, "empty")                                                                      # 홈 자체는 정상으로 읽혔다(옛 후보가 없을 뿐)
            self.assertEqual([card.kpi["text"] for card in window.screen_widget.findChildren(board_module.KpiCard)][1:], ["0개", "0개", "0개"])        # KPI 도 그대로
            self.assertEqual(len(window.screen_widget.findChildren(board_module.ListRow)) + len(window.screen_widget.findChildren(board_module.BoardRow)), 0)
            self.assertEqual({b.accessibleName() for b in window.screen_widget.findChildren(QAbstractButton)}, {text.T["refresh"]})        # 오류 때문에 새 단추가 생기지 않는다
            self.assertEqual(support.tree_snapshot(tmp), before)                                                                    # 깨진 파일을 고치거나 옮기지 않았다

    def test_a_window_that_does_not_autoload_never_reads_the_connections_and_a_second_read_is_not_started_while_one_runs(self):
        provider = services.FakeConnectionsProvider(delay=0.5)
        window = shell_module.AppShell(services.FakeHomeProvider(), connections=provider, autoload=False, clipboard=lambda _t: True, clock=clock_rules.FixedClock(FRIDAY))
        window.resize(1366, 768)
        window.show()
        self.addCleanup(window.close)
        window.reload()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10))
        self.settle(8)
        self.assertEqual((provider.calls, window.state.conn_load_count), (0, 0))                                                    # 홈을 불러와도(다시 불러오기도) 연결 정보는 읽지 않는다
        self.assertTrue(window.read_connections())
        self.assertFalse(window.read_connections())                                                                                 # 읽는 중이면 또 시작하지 않고 안내도 하지 않는다
        self.assertEqual(window.toast.text(), "")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 10))
        self.assertEqual(provider.calls, 1)


class CardLookTest(QtBase):
    def test_the_kpi_and_section_cards_carry_the_default_card_look_and_the_rows_do_not(self):
        window = self.make()
        cards = [frame for frame in window.screen_widget.findChildren(QWidget) if frame.property("card") == "true"]
        self.assertEqual(len(cards), 4 + 4 + 1)                                                              # KPI 넷 + 구역 넷 + 연결 한 줄
        for card in cards:
            self.assertEqual(card.property("cardstate"), "default")
            self.assertIsInstance(card.graphicsEffect(), QGraphicsDropShadowEffect)
            self.assertEqual(card.graphicsEffect().blurRadius(), tokens.SHADOW["card"].blur)                 # 기본 그림자 `0 2 8`
        for row in self.rows(window):
            self.assertIsNone(row.graphicsEffect())                                                          # 줄은 구역 카드 안의 목록이라 그림자가 없다(가리키면 바탕만 바뀐다)
        for row in window.screen_widget.findChildren(board_module.ListRow):
            self.assertEqual(row.property("card"), "plain")                                                  # 글 줄은 연한 면 — 눌리는 추천 줄과 구분된다


class HeadTest(QtBase):
    def test_the_home_title_is_24px_and_the_settings_title_keeps_28px(self):
        """운영자 지시: 홈 제목 24px. 설정 화면의 제목은 그대로(UI-C1b 몫 — 이 묶음이 바꾸지 않는다)."""
        window = self.make()
        title = next(label for label in window.screen_widget.findChildren(UI.Label) if label.plain_text() == text.T["home_title"])
        self.assertEqual((title.property("role"), tokens.type_style("h1").size), ("h1", 24))
        self.assertEqual(next(label for label in window.screen_widget.findChildren(UI.Label) if label.plain_text() == text.T["home_sub"]).property("role"), "sub")
        window.go("settings")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10))
        settings_title = next(label for label in window.screen_widget.findChildren(UI.Label) if label.plain_text() == text.T["settings_title"])
        self.assertEqual((settings_title.property("role"), tokens.type_style("display").size), ("display", 28))

    def test_the_head_has_the_sample_badge_then_the_refresh_button_and_the_last_fetch_line(self):
        window = self.make()
        buttons = [b for b in window.screen_widget.findChildren(QAbstractButton)]
        self.assertEqual([b.accessibleName() for b in buttons], ["예시 데이터", text.T["refresh"]])
        self.assertTrue(any(label.plain_text() == "마지막 조회 오늘 09:12" for label in window.screen_widget.findChildren(UI.Label)))
        real = self.make(Fixed(board_of(), sample=False))
        self.assertEqual([b.accessibleName() for b in real.screen_widget.findChildren(QAbstractButton)], [text.T["refresh"]])        # 예시 데이터가 아니면 예시 표시가 없다


class AccessibilityTest(QtBase):
    """접근 이름·읽는 순서·포커스(UI-C1d, D-202) — 화면 읽기 프로그램과 키보드가 홈의 어느 크기·어느 칸에서도 같은 말·같은 순서로 만난다.
    말은 뷰모델이 주고(`a11y`) 여기서는 **그려진 부품이 그 말을 그대로 달고 있는지**·Tab 이 읽는 순서(위에서 아래로, Naver A 다음 Naver B)로 도는지를 본다."""

    def ring(self, window):
        """홈 왼쪽 위의 메뉴에서 시작해 Tab(`focusNextChild`)이 한 바퀴 도는 정거장들."""
        start = window.nav_buttons["home"]
        self.focus(start)
        seen, current = [], start
        for _ in range(120):
            seen.append(current)
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            if current is start:
                return seen
        self.fail("Tab 이 한 바퀴를 돌지 못했다")

    def test_every_drawn_part_carries_the_name_the_view_model_gave_it(self):
        window = self.make()
        page = window.screen_widget
        view = window.state.home_view()["board"]
        self.assertEqual([card.accessibleName() for card in page.findChildren(board_module.KpiCard)], ["추천 주제 9개", "작성 완료 3개", "발행 완료 2개", "저장된 아이디어 2개"])
        self.assertEqual([card.accessibleName() for card in page.findChildren(board_module.KpiCard)], [kpi["a11y"] for kpi in view["kpi"]])
        sections = [frame for frame in page.findChildren(QWidget) if hasattr(frame, "rows_layout")]
        self.assertEqual([frame.accessibleName() for frame in sections], ["블로그 A 추천, 후보 5개", "블로그 B 추천, 후보 4개", "작성 중인 초안", "최근 발행"])      # 구역 이름 + 후보 수(구역을 읽으면 어느 블로그인지 먼저 들린다)
        self.assertEqual([row.accessibleName() for row in self.rows(window)], [row["a11y"] for section in view["recommend"] for row in section["rows"]])
        self.assertEqual([row.accessibleName() for row in page.findChildren(board_module.ListRow)], [row["a11y"] for section in (view["drafts"], view["recent"]) for row in section["rows"]])
        self.assertTrue(all("예시" in row.accessibleName() for row in self.rows(window)))                    # 예시 데이터는 말로도 알려 준다
        strip = next(frame for frame in page.findChildren(QWidget) if hasattr(frame, "text_label") and frame.property("card") == "true" and not hasattr(frame, "title_label"))
        self.assertEqual(strip.accessibleName(), view["connection"]["a11y"])
        for row in self.rows(window):
            self.assertEqual(row.accessibleDescription(), text.T["board_row_hint"])                         # 눌렀을 때 일어나는 일(상세가 열린다)을 안내한다
            if row.row["score"] is None:
                self.assertEqual(row.score.accessibleName(), "점수 계산 전")                                  # 점수가 없는 줄(가짜 데이터에 하나 있다)은 점수 말 대신 `점수 계산 전`
            else:
                self.assertTrue(row.score.accessibleName().startswith("점수 " + row.row["score_text"] + ", " + row.row["band_label"]), row.score.accessibleName())
            self.assertIn(row.score.accessibleName(), row.accessibleName())                                 # 줄의 이름이 점수 말을 그대로 품는다

    def test_a_row_without_a_score_is_read_as_not_computed_and_never_as_zero(self):
        window = self.make(Fixed(board_of(rows_of("가", (None,), (None,)))))
        row = self.rows(window)[0]
        self.assertIn("점수 계산 전", row.accessibleName())
        self.assertNotIn("0점", row.accessibleName())
        self.assertNotIn("점수 0", row.accessibleName())
        self.assertEqual(row.score.accessibleName(), "점수 계산 전")
        self.assertIn("관심도 데이터 부족", row.accessibleName())

    def test_the_tab_ring_follows_the_reading_order_at_every_width(self):
        """읽는 순서 = 위에서 아래로 한 구역을 다 지난 뒤 다음 구역 — 두 구역이 나란히(1366)여도 위아래로(1180·900)여도 Naver A 다섯 줄 다음 Naver B 네 줄이고, 구역 안에서는 아래로 간다."""
        for size in ((1366, 768), (1180, 720), (900, 560)):
            window = self.make(size=size)
            stops = self.ring(window)
            rows = [stop for stop in stops if isinstance(stop, board_module.BoardRow)]
            self.assertEqual([row.row["channel"] for row in rows], ["A"] * 5 + ["B"] * 4, size)
            for group in (rows[:5], rows[5:]):
                tops = [row.mapTo(window.scroll.widget(), row.rect().topLeft()).y() for row in group]
                self.assertEqual(tops, sorted(tops), size)                                                  # 구역 안에서는 아래로 간다
            self.assertEqual(len(stops), 16, size)                                                          # 메뉴 다섯(홈·주제 후보·Seed 관리·블로그 관리·설정 — UI-C1d 때는 둘, P4b 와 Seed 관리가 하나씩 더했고 의도적 갱신(P4d, D-270)으로 주제 후보가 하나 더했다)·예시 데이터·다시 불러오기·추천 줄 아홉 — 다른 정거장이 끼지 않는다
            window.close()

    def test_shift_tab_walks_the_same_ring_backwards_and_every_stop_has_a_name(self):
        window = self.make()
        forward = self.ring(window)
        self.assertTrue(all(stop.accessibleName().strip() for stop in forward))
        self.focus(forward[0])
        backward = [forward[0]]
        for _ in range(len(forward) - 1):
            backward[-1].focusPreviousChild()
            self.settle(1)
            backward.append(QApplication.focusWidget())
        self.assertEqual([id(stop) for stop in backward], [id(forward[0])] + [id(stop) for stop in reversed(forward[1:])])

    def test_closing_the_drawer_gives_the_focus_back_to_the_row_that_opened_it_in_either_section(self):
        window = self.make()
        for index in (0, 5):                                                                                # Naver A 의 첫 줄·Naver B 의 첫 줄
            row = self.rows(window)[index]
            row_id = row.row["id"]
            self.focus(row)
            QTest.keyClick(row, Qt.Key_Space)
            self.settle()
            self.assertTrue(window.drawer.is_open, index)
            self.focus(window.drawer_close)
            QTest.keyClick(window.drawer_close, Qt.Key_Escape)
            self.settle()
            self.assertFalse(window.drawer.is_open, index)
            focused = QApplication.focusWidget()
            self.assertIsInstance(focused, board_module.BoardRow)
            self.assertEqual(focused.property("focus_key"), "detail:" + row_id)
            self.assertIs(window.state.drawer_id, None)

    def test_the_only_widgets_that_take_focus_in_the_home_are_buttons_and_rows(self):
        for provider in (services.FakeHomeProvider(), services.FakeHomeProvider("empty"), Fixed(mixed_board(), sample=True), services.FakeHomeProvider(board=None)):
            window = self.make(provider)
            for widget in window.screen_widget.findChildren(QWidget):
                if widget.focusPolicy() != Qt.NoFocus and widget.isVisible():
                    self.assertIsInstance(widget, (QAbstractButton, UI.Pressable), type(widget).__name__)
                    self.assertTrue(widget.accessibleName().strip(), type(widget).__name__)
            for card in window.screen_widget.findChildren(board_module.KpiCard) + window.screen_widget.findChildren(board_module.ListRow):
                self.assertEqual(card.focusPolicy(), Qt.NoFocus)                                            # 눌리지 않는 카드·글 줄은 Tab 이 서지 않는다
            window.close()


class ScoreWithLabelMissingTextTest(QtBase):
    def test_the_missing_text_is_the_callers_and_the_old_default_stays(self):
        default = gauge_module.ScoreWithLabel(None, None, "card")
        self.assertEqual((default.missing_label.text(), default.accessibleName()), ("데이터 부족", "점수 데이터 부족"))
        custom = gauge_module.ScoreWithLabel(None, None, "card", missing_text="점수 계산 전")
        self.assertEqual((custom.missing_label.text(), custom.accessibleName()), ("점수 계산 전", "점수 계산 전"))
        known = gauge_module.ScoreWithLabel(92, 4, "card", missing_text="점수 계산 전")
        self.assertIsNone(known.missing_label)
        self.assertEqual(known.accessibleName(), "점수 92, 우선 추천, 4 상승")                                  # 점수가 있으면 안내 글은 쓰이지 않는다


if __name__ == "__main__":
    unittest.main()
