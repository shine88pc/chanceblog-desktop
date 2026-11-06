"""C-Type 공통 부품(UI-C0)의 Qt 시험 — 창을 띄우지 않고(offscreen) 점수 링·구간 이름 라벨·구성 막대·사용량 막대·의미별 배지·탭 줄·행동 줄·카드 그림자 3상태·부품 모음 화면을 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 순수 계산(점수 구간·사용량 경계·접는 순서·탭 키)은 `test_ui_cdesign_core.py` 가 PySide6 없이 지킨다 — 여기서는 **그려진 모습**(픽셀 색)·위젯 배치·키보드·접근 이름을 본다.

지키는 것:
  · 점수 링: 링 안은 숫자뿐(자식 위젯 없음)·호의 색이 구간색·트랙 색·**데이터 부족은 아무것도 안 그림(0점으로 그리지 않음)**·실제 0점은 트랙만 있는 링.
  · 합성 부품: 카드형은 링 오른쪽에 구간 이름 + 그 아래 변화량, 상세형은 링 아래에 가운데 맞춰, 데이터 부족은 링 없이 글만, 접근 이름 `점수 92, 우선 추천, 12 상승`, 글자 색(구간·변화량)이 토큰 색.
  · 구성 막대·사용량 막대: 조각 폭 비율·고정색·경계(80%/90%)의 채움 색·높이(12·8)·이름과 숫자 글·모르면 채우지 않음.
  · 배지 11종: 바탕·글자 색이 토큰 쌍, 한 줄·높이 24, 긴 글은 …와 툴팁, 모르는 종류 거절.
  · 탭 줄: Tab 정거장은 고른 탭 하나·←→Home End 로 이동·밑줄 색·높이 44~48·접근 이름. 행동 줄: 주요 44·접힘 순서·더보기 메뉴·신호·꺼진 이유 툴팁.
  · 카드 그림자: 토큰값의 효과, 선택 2px 파란 테두리, 그림자 번짐이 기본<가리킴, 선택은 파란 기운.
  · 부품 모음: 모든 부품이 있고, 글자 잘림 0·가로 넘침 0(여러 폭), 다섯 환경(해상도×배율) 점검.
"""
import importlib.util
import json
import math
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from chanceblog_desktop.ui.core import gallery_data, gauges as G, part_rules, tokens  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    for _name in ("QT_SCALE_FACTOR", "QT_FONT_DPI"):               # 이 시험은 픽셀을 논리 좌표(배율 1.0)로 본다 — 배율 점검은 `GalleryScaleTest` 가 자식 프로세스에서 따로 한다
        os.environ.pop(_name, None)
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_gallery
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget
    from chanceblog_desktop.ui.core import services
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import bars, gauges, theme
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import shell as shell_module

COLORS = tokens.palette()


def hexed(image, x, y):
    return image.pixelColor(int(round(x)), int(round(y))).name().upper()


def count_color(image, color, tolerance=0):
    target = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    found = 0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() > 200 and all(abs(a - b) <= tolerance for a, b in zip((pixel.red(), pixel.green(), pixel.blue()), target, strict=True)):
                found += 1
    return found


def arc_point(side, stroke, degrees):
    """링의 선 가운데 위의 한 점 — 12시 방향에서 시계 방향으로 `degrees` 도."""
    radius = (side - stroke) / 2
    return side / 2 + radius * math.sin(math.radians(degrees)), side / 2 - radius * math.cos(math.radians(degrees))


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class PartsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def host(self, *widgets, width=None, horizontal=False):
        box = QWidget()
        layout = QHBoxLayout(box) if horizontal else QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        for widget in widgets:
            layout.addWidget(widget)
        if width:
            box.setFixedWidth(width)
        box.show()
        self.addCleanup(box.close)
        self.settle()
        return box

    def unfocus(self):
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        self.settle(3)

    def focus(self, widget):
        window = widget.window()
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)
        widget.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), widget)


class ScoreRingTest(PartsBase):
    def test_the_arc_has_the_band_color_and_the_rest_is_the_track(self):
        ring = gauges.ScoreRing(92, "card")
        self.host(ring)
        image = ring.grab().toImage()
        stroke = ring.stroke()
        self.assertEqual(hexed(image, *arc_point(44, stroke, 30)), COLORS["score_high"].upper())
        self.assertEqual(hexed(image, *arc_point(44, stroke, 345)), COLORS["track"].upper())            # 331.2° 에서 끝나는 호의 빈 자리
        half = gauges.ScoreRing(50, "card")
        self.host(half)
        image = half.grab().toImage()
        self.assertEqual(hexed(image, *arc_point(44, stroke, 90)), COLORS["score_mid"].upper())         # 오른쪽 반은 호
        self.assertEqual(hexed(image, *arc_point(44, stroke, 270)), COLORS["track"].upper())            # 왼쪽 반은 트랙

    def test_every_band_color_on_the_arc(self):
        expected = {92: "score_high", 80: "score_high", 79: "score_good", 65: "score_good", 64: "score_mid", 50: "score_mid", 49: "score_low", 1: "score_low"}
        for score, key in expected.items():
            ring = gauges.ScoreRing(score, "detail")
            self.host(ring)
            image = ring.grab().toImage()
            self.assertEqual(hexed(image, *arc_point(72, ring.stroke(), 2)), COLORS[key].upper(), score)       # 12시 바로 옆은 어느 점수에서나 호의 시작

    def test_only_the_number_is_inside_the_ring(self):
        ring = gauges.ScoreRing(92, "card")
        self.host(ring)
        self.assertEqual(ring.findChildren(QWidget), [])                                                # 구간 이름·변화량 같은 위젯이 없다
        self.assertEqual(ring.view.text, "92")
        image = ring.grab().toImage()
        center = image.copy(12, 12, 20, 20)
        self.assertGreater(count_color(center, COLORS["text_strong"], 40), 8)                           # 가운데에 숫자 글자가 그려져 있다
        for band_text in ("우선 추천", "일반 후보", "보류", "제외"):
            self.assertNotIn(band_text, ring.accessibleName().split(", ")[0])

    def test_data_shortage_draws_nothing_at_all_and_is_not_a_zero_ring(self):
        for bad in (None, 101, -1, 79.5, "92", True):
            ring = gauges.ScoreRing(bad, "card")
            self.host(ring)
            image = ring.grab().toImage()
            self.assertFalse(ring.view.visible, repr(bad))
            for y in range(image.height()):
                for x in range(image.width()):
                    self.assertEqual(image.pixelColor(x, y).alpha(), 0, (bad, x, y))                  # 링도 트랙도 숫자도 없다
            self.assertEqual(ring.accessibleName(), "점수 데이터 부족")

    def test_a_real_zero_has_a_track_but_no_arc(self):
        ring = gauges.ScoreRing(0, "card")
        self.host(ring)
        image = ring.grab().toImage()
        for degrees in (2, 90, 180, 270, 358):
            self.assertEqual(hexed(image, *arc_point(44, ring.stroke(), degrees)), COLORS["track"].upper(), degrees)
        self.assertEqual(count_color(image, COLORS["score_low"]), 0)
        self.assertGreater(count_color(image.copy(12, 12, 20, 20), COLORS["text_strong"], 40), 4)         # 숫자 0 은 보인다
        self.assertEqual(ring.accessibleName(), "점수 0, 제외")

    def test_sizes_stroke_and_a_three_digit_number_that_still_fits(self):
        card, detail = gauges.ScoreRing(70, "card"), gauges.ScoreRing(70, "detail")
        self.host(card, detail)
        self.assertEqual((card.width(), card.height(), detail.width(), detail.height()), (44, 44, 72, 72))
        for ring in (card, detail):
            self.assertTrue(0.10 * ring.side <= ring.stroke() + 1e-9 <= 0.12 * ring.side + 1.0, ring.side)
        full = gauges.ScoreRing(100, "card")
        self.host(full)
        from PySide6.QtGui import QFontMetricsF
        font = full.number_font()
        inner = full.side - 2 * full.stroke() - 2 * tokens.SPACE["1"]
        self.assertLessEqual(QFontMetricsF(font).horizontalAdvance("100"), inner + 0.01)
        self.assertLess(font.pixelSize(), tokens.TYPE["score_sm"].size)                                 # 세 자리는 18 에서 줄어든다
        self.assertEqual(gauges.ScoreRing(92, "card").number_font().pixelSize(), tokens.TYPE["score_sm"].size)
        self.assertEqual(gauges.ScoreRing(92, "detail").number_font().pixelSize(), tokens.TYPE["score_lg"].size)

    def test_the_accessible_name_and_the_tip_say_score_and_band(self):
        ring = gauges.ScoreRing(58, "card")
        self.assertEqual((ring.accessibleName(), ring.toolTip()), ("점수 58, 보류", "점수 58, 보류"))


class ScoreWithLabelTest(PartsBase):
    def label_texts(self, widget):
        return [label.text() for label in widget.findChildren(QLabel)]

    def test_the_card_layout_puts_the_band_name_right_of_the_ring_and_the_change_below_it(self):
        part = gauges.ScoreWithLabel(92, 12, "card")
        self.host(part, horizontal=True)
        self.assertEqual(self.label_texts(part), ["우선 추천", "▲ +12"])
        ring_box = part.ring.geometry()
        band, delta = part.band_label.geometry(), part.delta_label.geometry()
        self.assertGreaterEqual(band.left(), ring_box.right())                                          # 링 오른쪽
        self.assertGreater(delta.top(), band.top())                                                     # 그 아래 줄
        self.assertLessEqual(abs(delta.left() - band.left()), 1)                                        # 왼쪽 끝을 맞춘다
        self.assertEqual(part.ring.width(), 44)
        self.assertEqual(part.accessibleName(), "점수 92, 우선 추천, 12 상승")
        self.assertEqual((part.band_label.property("scoreband"), part.delta_label.property("delta")), ("high", "up"))

    def test_the_detail_layout_puts_the_labels_under_the_ring_centered(self):
        part = gauges.ScoreWithLabel(65, 0, "detail")
        self.host(part)
        self.assertEqual(self.label_texts(part), ["일반 후보", "― 변화 없음"])
        ring_box, band, delta = part.ring.geometry(), part.band_label.geometry(), part.delta_label.geometry()
        self.assertGreaterEqual(band.top(), ring_box.bottom())
        self.assertGreater(delta.top(), band.top())
        for box in (band, delta):
            self.assertLessEqual(abs(box.center().x() - ring_box.center().x()), 2)                      # 가운데 맞춤
        self.assertEqual(part.ring.width(), 72)
        self.assertEqual(part.accessibleName(), "점수 65, 일반 후보, 변화 없음")
        self.assertEqual((part.band_label.property("scoreband"), part.delta_label.property("delta")), ("good", "flat"))

    def test_without_a_change_there_is_no_change_label(self):
        part = gauges.ScoreWithLabel(31, None, "card")
        self.host(part)
        self.assertIsNone(part.delta_label)
        self.assertEqual(self.label_texts(part), ["제외"])
        self.assertEqual(part.accessibleName(), "점수 31, 제외")

    def test_data_shortage_shows_only_the_label_and_no_ring(self):
        for layout in ("card", "detail"):
            part = gauges.ScoreWithLabel(None, 5, layout)
            self.host(part)
            self.assertEqual(part.findChildren(gauges.ScoreRing), [])
            self.assertIsNone(part.ring)
            self.assertEqual(self.label_texts(part), ["데이터 부족"])                                   # 변화량도 말하지 않는다
            self.assertEqual(part.accessibleName(), "점수 데이터 부족")
            self.assertGreaterEqual(part.height(), G.ring_pixels(layout))                               # 링이 있을 때와 같은 높이를 지킨다
        with self.assertRaises(ValueError):
            gauges.ScoreWithLabel(50, None, "wide")

    def test_the_band_name_and_change_use_the_token_colors_as_readable_text(self):
        cases = ((92, 12, "success_text", "success_text"), (70, -4, "primary_text", "danger_text"), (55, 0, "warning_text", "text_secondary"), (20, 3, "danger_text", "success_text"))
        for score, delta, band_key, delta_key in cases:
            part = gauges.ScoreWithLabel(score, delta, "card")
            self.host(part)
            self.assertGreater(count_color(part.band_label.grab().toImage(), COLORS[band_key], 24), 3, (score, band_key))
            self.assertGreater(count_color(part.delta_label.grab().toImage(), COLORS[delta_key], 24), 3, (score, delta_key))


class BarGaugeTest(PartsBase):
    def test_the_pieces_have_fixed_colors_in_proportion_to_their_values(self):
        bar = gauges.BarGauge(gallery_data.BAR_SAMPLE)
        self.host(bar, width=700)
        image = bar.track.grab().toImage()
        width, middle = image.width(), image.height() // 2
        self.assertEqual(image.height(), tokens.SIZE["gauge_h"])
        shares = [55 / 92, 12 / 92, 10 / 92, 15 / 92]
        starts, keys = [0.0], ["bar_base", "bar_data", "bar_trend", "bar_other"]
        for share in shares:
            starts.append(starts[-1] + share)
        for index, key in enumerate(keys):
            centre = (starts[index] + starts[index + 1]) / 2
            self.assertEqual(hexed(image, width * centre, middle), COLORS[key].upper(), key)
        self.assertEqual(image.pixelColor(0, 0).alpha() < 255 or hexed(image, 0, 0) != COLORS["bar_base"].upper(), True)          # 양 끝이 둥글다(모서리에는 조각 색이 없다)

    def test_names_numbers_and_the_big_total_are_text(self):
        bar = gauges.BarGauge(gallery_data.BAR_SAMPLE)
        self.host(bar, width=700)
        texts = [label.text() for label in bar.findChildren(QLabel)]
        for expected in ("기존 점수", "55", "추가 근거", "+12", "검색 흐름", "+10", "기타", "+15", "최종 점수", "92"):
            self.assertIn(expected, texts)
        total = next(label for label in bar.findChildren(QLabel) if label.text() == "92")
        self.assertEqual(total.property("role"), "h2")                                                  # 총점은 가장 크게
        self.assertGreater(total.mapTo(bar, total.rect().topLeft()).x(), max(name.mapTo(bar, name.rect().topLeft()).x() for name in bar.names))         # 맨 오른쪽
        self.assertTrue(bar.accessibleName().startswith("점수 구성: 기존 점수 55"))
        self.assertTrue(bar.accessibleName().endswith("최종 점수 92"))

    def test_a_long_name_is_cut_with_the_full_name_in_the_tip(self):
        long_name = "아주 긴 구성 이름이 한 칸에 다 들어가지 않을 때"
        bar = gauges.BarGauge((("기본", 50, "base"), (long_name, 10, "data")))
        self.host(bar, width=300)
        name = next(n for n in bar.names if n.toolTip() == long_name)
        self.assertEqual(name.toolTip(), long_name)
        self.assertEqual(ui_offscreen.find_clipping(bar), [])

    def test_no_parts_means_no_bar(self):
        bar = gauges.BarGauge(())
        self.host(bar)
        self.assertIsNone(bar.track)
        self.assertEqual([label.text() for label in bar.findChildren(QLabel)], ["구성 정보 없음"])


class UsageBarTest(PartsBase):
    def fill_probe(self, used, limit=27000):
        bar = gauges.UsageBar(used, limit, "회", "이번 달")
        self.host(bar, width=600)
        image = bar.track.grab().toImage()
        self.assertEqual(image.height(), tokens.SIZE["usage_h"])
        return bar, image

    def test_the_fill_color_follows_the_80_and_90_percent_lines(self):
        for used, key in ((12400, "primary"), (21500, "warning"), (22000, "warning"), (24100, "warning"), (24200, "danger"), (25000, "danger"), (30000, "danger")):
            bar, image = self.fill_probe(used)
            self.assertEqual(hexed(image, 4, image.height() // 2), COLORS[key].upper(), used)
            self.assertEqual(bar.view.color_key, key)

    def test_the_fill_length_is_the_usage_share_and_the_rest_is_the_track(self):
        bar, image = self.fill_probe(12400)
        width = image.width()
        self.assertEqual(hexed(image, width * 0.2, 4), COLORS["primary"].upper())
        self.assertEqual(hexed(image, width * 0.7, 4), COLORS["track"].upper())
        bar, image = self.fill_probe(30000)                                                             # 한도를 넘어도 막대는 끝까지
        self.assertEqual(hexed(image, image.width() * 0.99, 4), COLORS["danger"].upper())

    def test_text_percent_and_the_state_word_come_with_the_color(self):
        bar, _image = self.fill_probe(12400)
        self.assertEqual((bar.text_label.toolTip(), bar.percent_label.text()), ("이번 달 12,400 / 27,000회", "46%"))
        self.assertIsNone(bar.percent_label.property("usage"))
        bar, _image = self.fill_probe(22000)
        self.assertEqual((bar.percent_label.text(), bar.percent_label.property("usage")), ("주의 · 81%", "warn"))
        bar, _image = self.fill_probe(25000)
        self.assertEqual((bar.percent_label.text(), bar.percent_label.property("usage")), ("위험 · 93%", "danger"))
        bar, _image = self.fill_probe(30000)
        self.assertEqual(bar.percent_label.text(), "한도 넘음 · 111%")
        self.assertEqual(bar.accessibleName(), "이번 달 30,000 / 27,000회, 111%, 한도 넘음")

    def test_unknown_usage_has_no_fill_and_no_percent(self):
        bar, image = self.fill_probe(None)
        self.assertEqual(hexed(image, 4, 4), COLORS["track"].upper())
        self.assertEqual(hexed(image, image.width() // 2, 4), COLORS["track"].upper())
        self.assertIsNone(bar.percent_label)
        self.assertEqual(bar.text_label.toolTip(), "이번 달 확인할 수 없어요")
        self.assertFalse(bar.view.known)


class SemanticBadgeTest(PartsBase):
    def test_every_kind_paints_its_token_pair_in_one_line(self):
        badges = [UI.SemanticBadge(kind) for kind in tokens.BADGE_KINDS]
        self.host(*badges, width=300)
        for kind, badge in zip(tokens.BADGE_KINDS, badges, strict=True):
            image = badge.grab().toImage()
            bg, fg = tokens.badge_colors(COLORS, kind)
            self.assertEqual(hexed(image, 5, image.height() // 2), bg.upper(), kind)                    # 알약 왼쪽 끝 안쪽의 바탕
            self.assertGreater(count_color(image, fg, 30), 3, kind)                                      # 글자 색
            self.assertEqual(badge.text(), tokens.badge_label(kind))
            self.assertEqual(badge.accessibleName(), tokens.badge_label(kind))
            self.assertEqual(badge.property("semantic"), kind)
            self.assertGreaterEqual(badge.height(), tokens.SIZE["badge_h"])
            self.assertLess(badge.height(), 2 * tokens.SIZE["badge_h"])                                  # 한 줄
        self.assertEqual(ui_offscreen.find_clipping(badges[0].window()), [])

    def test_a_long_text_is_cut_with_the_whole_text_in_the_tip_and_a_custom_text_is_named_with_its_kind(self):
        long = UI.SemanticBadge("caution", gallery_data.LONG_BADGE_TEXT)
        self.assertTrue(long.text().endswith("…"))
        self.assertLessEqual(len(long.text()), part_rules.BADGE_MAX_CHARS)
        self.assertEqual((long.toolTip(), long.full_text), (gallery_data.LONG_BADGE_TEXT, gallery_data.LONG_BADGE_TEXT))
        short = UI.SemanticBadge("blocked", "기준 미달")
        self.assertEqual((short.text(), short.toolTip(), short.accessibleName()), ("기준 미달", "", "차단: 기준 미달"))
        self.assertEqual(UI.SemanticBadge("life", "생활").accessibleName(), "생활")
        for bad in ("blue", "", None, "Tech"):
            with self.assertRaises(ValueError):
                UI.SemanticBadge(bad)


class TabBarTest(PartsBase):
    def make(self, current=None):
        bar = bars.TabBar(gallery_data.TAB_SAMPLE, current)
        self.host(bar, width=600)
        return bar

    def test_selection_and_the_changed_signal(self):
        bar = self.make()
        seen = []
        bar.changed.connect(seen.append)
        self.assertEqual(bar.current(), "overview")
        bar.set_current("basis")
        bar.set_current("basis")                                                                        # 같은 탭을 또 골라도 신호는 한 번
        bar.buttons["memo"].click()
        self.assertEqual((seen, bar.current()), (["basis", "memo"], "memo"))
        self.assertEqual([key for key, button in bar.buttons.items() if button.isChecked()], ["memo"])
        with self.assertRaises(KeyError):
            bar.set_current("none")
        for bad in ([], [("a", "하나"), ("a", "둘")]):
            with self.assertRaises(ValueError):
                bars.TabBar(bad)

    def test_height_names_and_the_single_tab_stop(self):
        bar = self.make("compare")
        for button in bar.buttons.values():
            self.assertTrue(44 <= button.height() <= 48, button.height())
        self.assertEqual(bar.buttons["overview"].accessibleName(), "개요 탭, 4개 중 1번째")
        self.assertEqual(bar.buttons["memo"].accessibleName(), "메모 탭, 4개 중 4번째")
        self.assertEqual([key for key, button in bar.buttons.items() if button.focusPolicy() == Qt.StrongFocus], ["compare"])          # Tab 정거장은 고른 탭 하나
        bar.set_current("memo")
        self.assertEqual([key for key, button in bar.buttons.items() if button.focusPolicy() == Qt.StrongFocus], ["memo"])

    def test_the_arrow_keys_home_and_end_move_the_selection_and_the_focus(self):
        bar = self.make("overview")
        self.focus(bar.buttons["overview"])
        QTest.keyClick(bar.buttons["overview"], Qt.Key_Right)
        self.assertEqual(bar.current(), "basis")
        self.assertIs(QApplication.focusWidget(), bar.buttons["basis"])
        QTest.keyClick(bar.buttons["basis"], Qt.Key_End)
        self.assertEqual((bar.current(), QApplication.focusWidget()), ("memo", bar.buttons["memo"]))
        QTest.keyClick(bar.buttons["memo"], Qt.Key_Right)                                               # 끝에서 한 바퀴 돈다
        self.assertEqual(bar.current(), "overview")
        QTest.keyClick(bar.buttons["overview"], Qt.Key_Left)
        self.assertEqual(bar.current(), "memo")
        QTest.keyClick(bar.buttons["memo"], Qt.Key_Home)
        self.assertEqual(bar.current(), "overview")
        QTest.keyClick(bar.buttons["overview"], Qt.Key_Space)                                           # 다른 키는 옮기지 않는다
        self.assertEqual(bar.current(), "overview")

    def test_the_selected_tab_has_a_two_pixel_underline_and_strong_blue_text(self):
        bar = self.make("basis")
        self.unfocus()                                                                                  # 처음 창이 활성이 되면 첫 탭에 포커스가 가서 링이 그려진다 — 링 없는 모습을 본다
        chosen, other = bar.buttons["basis"].grab().toImage(), bar.buttons["compare"].grab().toImage()
        middle = chosen.width() // 2
        for offset in (1, 2):
            self.assertEqual(hexed(chosen, middle, chosen.height() - offset), COLORS["primary_700"].upper(), offset)       # 밑줄 2px
        self.assertNotEqual(hexed(chosen, middle, chosen.height() - 3), COLORS["primary_700"].upper())
        self.assertNotEqual(hexed(other, middle, other.height() - 1), COLORS["primary_700"].upper())
        self.assertGreater(count_color(chosen, COLORS["primary_700"], 30), count_color(other, COLORS["primary_700"], 30) + 20)


class ActionBarTest(PartsBase):
    ACTIONS = [{"key": key, "text": text, "kind": kind} for key, text, kind in gallery_data.ACTION_SAMPLE]
    MORE = [{"key": key, "text": text} for key, text in gallery_data.ACTION_MORE_SAMPLE]

    def make(self, width=900, more=True):
        bar = bars.ActionBar(self.ACTIONS, self.MORE if more else [])
        self.host(bar, width=width)
        return bar

    def test_wide_shows_everything_with_the_right_heights_and_the_more_button_only_for_listed_items(self):
        bar = self.make()
        self.assertEqual([button.isVisible() for button in bar.buttons], [True] * 5)
        self.assertEqual([button.height() for button in bar.buttons], [44, 40, 40, 40, 40])
        self.assertTrue(bar.more_button.isVisible())                                                    # 처음부터 더보기 항목이 있다
        self.assertEqual(bar.menu_items(), [("note", "메모 남기기")])
        plain = self.make(more=False)
        self.assertFalse(plain.more_button.isVisible())                                                 # 접힌 것도 처음 항목도 없으면 ⋮ 가 없다
        self.assertEqual(plain.menu_items(), [])

    def test_narrowing_folds_danger_and_tertiary_first_then_secondary_and_the_primary_stays(self):
        order_of_folding = [4, 3, 2, 1]                                                                 # 위험 → 3차 → 보조(뒤에서부터)
        bar = self.make()
        previous = 0
        for width in range(900, 100, -20):
            bar.setFixedWidth(width)
            self.settle(2)
            folded = bar.folded
            self.assertEqual(set(folded), set(order_of_folding[:len(folded)]), width)
            self.assertTrue(bar.buttons[0].isVisible(), width)
            self.assertEqual([not button.isVisible() for button in bar.buttons], [index in folded for index in range(5)], width)
            self.assertTrue(bar.more_button.isVisible() if folded else True)
            self.assertGreaterEqual(len(folded), previous)
            previous = len(folded)
        self.assertEqual(bar.folded, (1, 2, 3, 4))
        self.assertEqual(bar.menu_items(), [(self.ACTIONS[i]["key"], self.ACTIONS[i]["text"]) for i in (1, 2, 3, 4)] + [("note", "메모 남기기")])

    def test_buttons_and_menu_items_send_their_key(self):
        bar = self.make(width=140)
        sent = []
        bar.triggered.connect(sent.append)
        bar.buttons[0].click()
        menu = bar.open_menu()
        texts = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertEqual(texts, ["Seed로 등록", "나중에 보기", "보류하기", "제외하기", "메모 남기기"])
        self.assertEqual(sum(1 for action in menu.actions() if action.isSeparator()), 1)                # 접힌 행동과 처음부터 있던 항목 사이
        menu.actions()[0].trigger()
        menu.actions()[-1].trigger()
        menu.close()
        self.assertEqual(sent, ["make", "seed", "note"])

    def test_the_rules_are_enforced_and_a_disabled_action_says_why(self):
        for kinds in (["secondary"], ["primary", "primary"], ["primary"] + ["secondary"] * 4, ["primary", "danger", "danger"]):
            with self.assertRaises(ValueError, msg=str(kinds)):
                bars.ActionBar([{"key": str(i), "text": "행동", "kind": kind} for i, kind in enumerate(kinds)])
        bar = self.make()
        bar.disable("make", "먼저 주제를 골라 주세요")
        self.assertFalse(bar.buttons[0].isEnabled())
        self.assertEqual((bar.buttons[0].toolTip(), bar.buttons[0].accessibleDescription()), ("먼저 주제를 골라 주세요", "먼저 주제를 골라 주세요"))

    def test_names_and_the_more_button_tip(self):
        bar = self.make()
        self.assertEqual(bar.accessibleName(), "행동 줄")
        self.assertEqual((bar.more_button.accessibleName(), bar.more_button.toolTip()), ("더보기 메뉴 열기", "더보기 메뉴 열기"))
        self.assertEqual([button.accessibleName() for button in bar.buttons], [spec["text"] for spec in self.ACTIONS])
        self.assertGreaterEqual(bar.more_button.height(), tokens.SIZE["hit"])


class CardStateTest(PartsBase):
    def test_the_shadow_effect_carries_the_token_values(self):
        for name, rgb in (("card", (22, 39, 74)), ("hover", (22, 39, 74)), ("selected", (47, 111, 237))):
            effect = theme.shadow_effect(name)
            style = tokens.SHADOW[name]
            self.assertIsInstance(effect, QGraphicsDropShadowEffect)
            self.assertEqual((effect.offset().x(), effect.offset().y(), effect.blurRadius()), (style.dx, style.dy, style.blur))
            color = effect.color()
            self.assertEqual((color.red(), color.green(), color.blue()), rgb, name)
            self.assertAlmostEqual(color.alphaF(), style.alpha, delta=0.01)

    def test_card_looks_come_from_the_tokens(self):
        self.assertEqual(theme.card_look("default"), theme.CardLook(1, COLORS["border"], "card"))
        self.assertEqual(theme.card_look("hover"), theme.CardLook(1, COLORS["border_hover"], "hover"))
        self.assertEqual(theme.card_look("selected"), theme.CardLook(2, COLORS["primary"], "selected"))
        with self.assertRaises(ValueError):
            theme.card_look("pressed")

    def framed(self, state):
        frame, layout = UI.Card((16, 16, 16, 16))
        frame.setMinimumSize(160, 80)
        layout.addWidget(UI.label("카드", "h3"))
        look = UI.set_card_state(frame, state, layout)
        shell = QWidget()
        inner = QVBoxLayout(shell)
        inner.setContentsMargins(16, 12, 16, 28)                                                        # 그림자가 잘리지 않게 바깥 여백
        inner.addWidget(frame)
        shell.setObjectName("root")                                                                     # 앱 바탕색(`QWidget#root`) — 그림자가 번진 색을 바탕과 견주려고
        shell.show()
        self.addCleanup(shell.close)
        self.settle(8)
        return frame, layout, shell, look

    def test_the_border_is_one_pixel_by_default_and_two_pixels_blue_when_selected(self):
        frame, _layout, _shell, _look = self.framed("default")
        image = frame.grab().toImage()
        middle = image.width() // 2
        self.assertEqual(hexed(image, middle, 0), COLORS["border"].upper())
        self.assertNotEqual(hexed(image, middle, 1), COLORS["border"].upper())
        frame, layout, _shell, look = self.framed("selected")
        image = frame.grab().toImage()
        self.assertEqual((hexed(image, middle, 0), hexed(image, middle, 1)), (COLORS["primary"].upper(),) * 2)
        self.assertNotEqual(hexed(image, middle, 2), COLORS["primary"].upper())
        self.assertEqual(look.border_px, 2)
        margins = layout.contentsMargins()
        self.assertEqual((margins.left(), margins.top()), (15, 15))                                     # 테두리가 1px 두꺼워진 만큼 안쪽 여백을 줄여 글이 밀리지 않는다
        hover, _l, _s, _k = self.framed("hover")
        self.assertEqual(hexed(hover.grab().toImage(), middle, 0), COLORS["border_hover"].upper())

    def test_the_shadow_gets_stronger_on_hover_and_blue_when_selected(self):
        """카드 바로 아래(4px)의 색을 바탕색과 견준다 — 기본에도 약한 그림자가 있고, 가리키면 더 짙고, 선택됨은 파란 그림자라 같은 자리의 파랑-빨강 차이가 기본보다 커진다."""
        background = COLORS["bg_app"]
        base_sum = sum(int(background[i:i + 2], 16) for i in (1, 3, 5))

        def below(state):
            frame, _layout, shell, _look = self.framed(state)
            image = shell.grab().toImage()
            self.assertEqual(hexed(image, 2, image.height() - 2), background.upper(), state)           # 그림자가 닿지 않는 구석은 바탕색 그대로
            pixel = image.pixelColor(frame.mapTo(shell, frame.rect().center()).x(), frame.mapTo(shell, frame.rect().bottomLeft()).y() + 4)
            return pixel
        near = {state: below(state) for state in ("default", "hover", "selected")}
        darkness = {state: base_sum - (pixel.red() + pixel.green() + pixel.blue()) for state, pixel in near.items()}
        self.assertGreater(darkness["default"], 0)                                                      # 기본에도 약한 그림자가 있다
        self.assertGreater(darkness["hover"], darkness["default"])                                      # 가리키면 더 짙다
        tint = {state: pixel.blue() - pixel.red() for state, pixel in near.items()}
        self.assertGreater(tint["selected"], tint["default"] + 8)                                       # 선택됨은 파란 기운


class ExistingPartsFollowTheNewTokensTest(PartsBase):
    def test_the_buttons_use_the_document_values(self):
        secondary, primary, danger = UI.Button("secondary", "보조"), UI.Button("primary", "주요"), UI.Button("danger", "위험")
        quiet = UI.Button("secondary", "꺼진 보조")
        disabled_primary, disabled_danger = UI.Button("primary", "꺼진 주요"), UI.Button("danger", "꺼진 위험")
        for button in (quiet, disabled_primary, disabled_danger):
            button.setEnabled(False)
        self.host(secondary, primary, danger, quiet, disabled_primary, disabled_danger)
        self.unfocus()                                                                                  # 처음 활성이 되면 첫 단추에 포커스 링이 그려진다 — 링 없는 모습을 본다
        image = secondary.grab().toImage()
        self.assertEqual(hexed(image, image.width() // 2, 0), COLORS["secondary_border"].upper())          # 보조 단추 테두리
        self.assertGreater(count_color(image, COLORS["secondary_text"], 24), 5)                          # 보조 단추 글자
        self.assertEqual(hexed(primary.grab().toImage(), 8, primary.height() // 2), COLORS["primary"].upper())
        self.assertEqual(hexed(danger.grab().toImage(), 8, danger.height() // 2), COLORS["danger"].upper())
        self.assertEqual(hexed(quiet.grab().toImage(), 8, quiet.height() // 2), COLORS["disabled_bg"].upper())          # 꺼진 보조는 옅은 바탕(그대로)
        for button in (disabled_primary, disabled_danger):                                               # 꺼진 주요·위험은 꺼진 채움 + 흰 글자
            image = button.grab().toImage()
            self.assertEqual(hexed(image, 8, image.height() // 2), COLORS["disabled_fill"].upper())
            self.assertGreater(count_color(image, COLORS["on_primary"], 10), 5)
        ghost = UI.Button("danger_ghost", "제외하기")
        self.host(ghost)
        self.assertGreater(count_color(ghost.grab().toImage(), COLORS["danger_text"], 24), 5)
        self.assertEqual(ghost.property("kind"), "danger_ghost")

    def test_the_state_card_and_the_banner_follow_the_new_status_colors_and_keep_title_message_and_action(self):
        """상태 카드(빈·오류)와 안내 띠는 새 상태색을 토큰으로 따라가고, 문서의 필수 필드(제목·설명·행동)가 모두 있다. 새 상태 띠 부품은 이 묶음에서 만들지 않았다."""
        self.assertEqual(tokens.tone(COLORS, "red")[:3], (COLORS["danger"], COLORS["danger_100"], COLORS["danger_text"]))
        self.assertEqual(tokens.tone(COLORS, "green")[:3], (COLORS["success"], COLORS["success_100"], COLORS["success_text"]))
        self.assertEqual(tokens.tone(COLORS, "orange")[:3], (COLORS["warning"], COLORS["warning_100"], COLORS["warning_text"]))
        card = UI.StateCard("alert", "red", "제목이에요", "설명이에요", "다시 시도")
        banner = UI.Banner("alert", "안내예요")
        self.host(card, banner, width=520)
        self.assertEqual(sorted(label.plain_text() for label in card.findChildren(UI.Label)), ["설명이에요", "제목이에요"])                # 제목·설명(줄바꿈 글은 서식 글이라 받은 글을 본다)
        self.assertIsNotNone(card.action)
        self.assertEqual(card.action.text(), "다시 시도")                                                # 행동 단추
        swatch = card.findChild(UI.ToneSwatch)
        self.assertEqual(hexed(swatch.grab().toImage(), 3, 20), COLORS["danger_100"].upper())          # 오류 아이콘 바탕 = 새 위험 옅은 면
        image = banner.grab().toImage()
        self.assertEqual(hexed(image, 3, image.height() // 2), COLORS["warning_100"].upper())          # 안내 띠 바탕 = 새 경고 옅은 면
        self.assertGreater(count_color(image, COLORS["warning_text"], 24), 3)

    def test_the_stylesheet_has_the_new_rules_and_only_token_colors(self):
        qss = theme.build_qss(COLORS)
        for kind in tokens.BADGE_KINDS:
            bg, fg = tokens.badge_colors(COLORS, kind)
            self.assertRegex(qss, rf'QLabel\[semantic="{kind}"\] \{{ background: {bg}; color: {fg};')
        for band in G.BANDS:
            self.assertRegex(qss, rf'QLabel\[scoreband="{band.key}"\] \{{ color: {COLORS[band.text_key]};')
        self.assertIn(f'QFrame[card="true"][cardstate="selected"] {{ border: 2px solid {COLORS["primary"]}; }}', qss)
        self.assertIn(f'QFrame[card="true"][cardstate="hover"] {{ border: 1px solid {COLORS["border_hover"]}; }}', qss)
        self.assertRegex(qss, rf'QPushButton\[kind="primary"\]:pressed \{{ background: {COLORS["primary_pressed"]};')
        self.assertRegex(qss, rf'QPushButton\[kind="primary"\]:hover \{{ background: {COLORS["primary_700"]};')
        self.assertRegex(qss, rf'QPushButton\[tab="true"\]:checked \{{ color: {COLORS["primary_700"]}; border-bottom: 2px solid {COLORS["primary_700"]};')
        self.assertNotIn("primary_600", qss)
        for role in ("h3", "micro"):
            self.assertRegex(qss, rf'QLabel\[role="{role}"\] \{{ font-size: {tokens.TYPE[role].size}px; font-weight: {tokens.TYPE[role].weight};')

    def test_home_and_settings_get_the_new_backgrounds_automatically(self):
        window = shell_module.AppShell(services.FakeHomeProvider(), autoload=False, clipboard=lambda text_: True)
        window.resize(1440, 900)
        window.show()
        self.addCleanup(window.close)
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        self.settle()
        image = window.grab().toImage()
        self.assertEqual(hexed(image, tokens.LAYOUT["sidebar"] + 6, 600), COLORS["bg_app"].upper())      # 본문 바탕 #F4F7FB
        self.assertEqual(hexed(image, 4, 400), COLORS["bg_sidebar"].upper())                              # 사이드바 바탕 #F7F9FC
        self.assertEqual([button.accessibleName() for button in window.nav_buttons.values()][:1], ["홈 메뉴로 이동"])
        self.assertEqual(len(window.nav_buttons), 6)                                                      # 메뉴 동작·개수는 이 묶음에서 그대로


class GalleryTest(PartsBase):
    def build(self, width):
        page, parts = ui_gallery.build_gallery(width)
        ui_gallery.fit(page, self.app, ui_offscreen)
        self.addCleanup(page.close)
        return page, parts

    def test_every_part_is_in_the_gallery_and_nothing_is_clipped_at_several_widths(self):
        for width in (1366, 1536, 1280, 1180):
            page, parts = self.build(width)
            self.assertEqual({key: (len(value) if isinstance(value, list) else int(value is not None)) for key, value in parts.items()},
                             {"badges": 12, "rings_card": 9, "rings_detail": 4, "bar": 1, "usage": 5, "tabs": 1, "actions": 3, "cards": 3}, width)
            self.assertEqual(ui_offscreen.find_clipping(page), [], width)
            self.assertEqual(ui_gallery.overflow(page), [], width)
            self.assertEqual(len(page.findChildren(gauges.ScoreRing)), 8 + 3, width)                       # 데이터 부족 둘(카드형 1·상세형 1)은 링이 없다
            self.assertEqual(len(page.findChildren(UI.SemanticBadge)), 12)
            self.assertEqual(len(page.findChildren(bars.ActionBar)), 3)

    def test_the_sample_values_are_marked_as_examples(self):
        page, _parts = self.build(1366)
        texts = " ".join(label.text() for label in page.findChildren(QLabel))
        self.assertIn("예시 데이터", texts)
        self.assertIn("모든 이름·숫자는 예시예요", texts)

    def test_the_narrow_action_bars_in_the_gallery_really_fold(self):
        page, parts = self.build(1366)
        wide, medium, narrow = parts["actions"]
        self.assertEqual(wide.folded, ())
        self.assertGreater(len(medium.folded), 0)
        self.assertGreater(len(narrow.folded), len(medium.folded))
        self.assertTrue(narrow.buttons[0].isVisible())


ENVIRONMENTS = {"1366x768@100": (1366, 1.0), "1366x768@125": (1366, 1.25), "1920x1080@100": (1920, 1.0), "1920x1080@125": (1920, 1.25), "1920x1080@150": (1920, 1.5)}


@unittest.skipUnless(HAVE and os.name == "nt", "PySide6 와 윈도 글꼴이 있어야 한다(글자 잘림은 글꼴에 달렸다)")
class GalleryScaleTest(unittest.TestCase):
    """해상도 × 배율 점검 — `ui_capture.py --gallery --check` 가 환경마다 자식 프로세스에서 `QT_SCALE_FACTOR` 로 배율을 흉내 낸다(앱 코드에는 배율 값이 없다)."""

    def test_each_environment_has_no_clipped_text_and_no_horizontal_overflow(self):
        for environment, (width, scale) in ENVIRONMENTS.items():
            with self.subTest(environment=environment):
                command = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "ui_capture.py"), "unused", "--env", environment, "--gallery", "--check"]
                done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1"), timeout=240, creationflags=0x08000000 if os.name == "nt" else 0)
                if done.returncode != 0:
                    raise AssertionError(done.stderr[-400:])
                report = json.loads(done.stdout)[0]
                self.assertEqual((report["env"], float(report["scale_factor_env"])), (environment, scale))
                shot = report["shots"]["gallery"]
                self.assertLessEqual(abs(shot[0] - width), 1)                                              # 물리 폭 = 화면 폭(논리 폭 × 배율, 반올림 1px 이내)
                self.assertEqual(shot[2], scale)
                found = report["checks"]["gallery"]
                self.assertEqual(found["clipped"], [], environment)
                self.assertFalse(found["horizontal_scroll"], environment)
                self.assertEqual(found["overflow"], [], environment)
                self.assertEqual(found["counts"], {"badges": 12, "rings_card": 9, "rings_detail": 4, "bar": 1, "usage": 5, "tabs": 1, "actions": 3, "cards": 3})


if __name__ == "__main__":
    unittest.main()
