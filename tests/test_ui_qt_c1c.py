"""UI-C1c(홈 데이터)의 Qt 시험 — 창을 띄우지 않고(offscreen) **홈 화면이 그대로**임을 확인한다: 새 구역의 값(`board`)은 뷰모델에만 있고 화면은 아직 그리지 않는다(새 홈 모양은 UI-C1d).
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 값·규칙은 `test_ui_c1c_core.py`·`test_ui_c1c_adapters.py` 가 PySide6 없이 지킨다 — 여기서는 **그려진 모습**을 본다.

지키는 것:
  · 새 구역의 값이 있든 없든(`FakeHomeProvider(board=…)`) 홈 화면의 위젯 목록(종류·이름·글·접근 이름·툴팁·포커스·활성·위치·크기)이 같다 — 여섯 시나리오(정상·빈·일부만·오프라인·오류·읽는 중)와 서랍·칩 B·좁은 폭·넓은 화면.
  · 새 구역의 글(`점수 계산 전`·`관심도 데이터 부족`·`발행일 확인 불가`·`작성 중인 초안`·`연결 전` 등)은 어떤 위젯에도 없다(아직 그리지 않는다).
  · 새 KPI 의 글(`0개`·`연결 전`·`집계 전`)을 지금의 요약 카드에 넣어도 깨지지 않는다(잘림 0 — 100%·125%).
  · 실제 어댑터 데이터(임시 폴더의 진짜 보관함)로 앱 틀을 띄워도 슬롯 안 예외 없이 그려진다.
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from chanceblog_desktop.ui.core import board_view, services, text  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget
    from chanceblog_desktop.ui.core import clock as clock_rules
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.qt.screens import FlowGrid

import datetime  # noqa: E402

FRIDAY = datetime.datetime(2026, 11, 6, 20, 10, 0)
BOARD_ONLY = ("점수 계산 전", "관심도 데이터 부족", "관심도 상승", "관심도 하락", "관심도 보통", "발행일 확인 불가", "작성 중인 초안", "작성 중인 초안이 없어요.", "초안 생성됨", "검토 필요",
              "최근 발행", "아직 추천할 후보가 없어요.", "연결 전", "집계 전", "연결 상태", "추천 후보를 읽지 못했어요.")


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

    def make(self, provider, size=(1366, 768), load=True, action=None):
        window = shell_module.AppShell(provider, autoload=False, clipboard=lambda _t: True, clock=clock_rules.FixedClock(FRIDAY))
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        if load:
            window.reload()
            self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10))
        self.settle()
        if action:
            action(window)
            self.settle()
        focus = self.app.focusWidget()
        if focus is not None:
            focus.clearFocus()
        self.settle(3)
        return window

    @staticmethod
    def dump(window):
        """창 안에 보이는 모든 위젯의 목록 — 종류·이름·글·접근 이름·툴팁·포커스·활성·위치·크기."""
        rows = []
        for widget in window.centralWidget().findChildren(QWidget):
            if not widget.isVisible():
                continue
            at = widget.mapTo(window, QPoint(0, 0))
            shown = widget.text() if isinstance(widget, (QLabel, QAbstractButton)) else ""
            rows.append((type(widget).__name__, widget.objectName(), widget.property("role") or "", shown, widget.accessibleName(), widget.toolTip(), int(widget.focusPolicy()), int(widget.isEnabled()),
                         at.x(), at.y(), widget.width(), widget.height()))
        return rows

    def stable_dump(self, window):
        """배치가 가라앉을 때까지(연달아 두 번 같을 때까지) 기다린 뒤의 위젯 목록 — 다시 맞추는 타이머(30ms)가 느린 PC 에서 늦어도 같은 모습끼리 견주게 한다."""
        previous = None
        for _ in range(40):
            self.settle(3)
            current = self.dump(window)
            if current == previous:
                break
            previous = current
        return current

    @staticmethod
    def texts(window):
        found = []
        for widget in window.centralWidget().findChildren(QWidget):
            if widget.isVisible():
                found += [widget.accessibleName(), widget.toolTip()] + ([widget.text()] if isinstance(widget, (QLabel, QAbstractButton)) else [])
        return " | ".join(item for item in found if item)


class HomeLooksTheSameTest(QtBase):
    def test_the_home_screen_is_the_same_whether_or_not_the_provider_brings_the_new_sections(self):
        for scenario in ("normal", "empty", "partial", "offline", "error"):
            with_board = self.make(services.FakeHomeProvider(scenario))
            without = self.make(services.FakeHomeProvider(scenario, board=None))
            self.assertTrue(with_board.state.home_view()["board"]["state"] in ("ready", "unavailable"), scenario)
            self.assertEqual(without.state.home_view()["board"]["state"] in ("before_connect", "unavailable"), True, scenario)
            first, second = self.stable_dump(with_board), self.stable_dump(without)
            self.assertEqual(first, second, scenario)
            self.assertGreater(len(first), 50, scenario)

    def test_the_same_holds_while_loading_with_the_drawer_open_with_a_filter_and_in_a_narrow_window(self):
        loading_a = self.make(services.FakeHomeProvider(delay=5), load=False)
        loading_b = self.make(services.FakeHomeProvider(delay=5, board=None), load=False)
        self.assertEqual((loading_a.state.list_state, self.stable_dump(loading_a) == self.stable_dump(loading_b)), ("loading", True))
        for label, size, action in (("서랍", (1366, 768), lambda w: w.open_drawer("s1")), ("칩 B", (1366, 768), lambda w: w.chip_home("b")), ("좁은 폭", (1100, 700), None), ("넓은 화면", (1920, 1080), None)):
            first = self.make(services.FakeHomeProvider(), size, action=action)
            second = self.make(services.FakeHomeProvider(board=None), size, action=action)
            self.assertEqual(self.stable_dump(first), self.stable_dump(second), label)

    def test_no_text_of_the_new_sections_is_drawn_anywhere_on_the_home_screen(self):
        window = self.make(services.FakeHomeProvider())
        shown = self.texts(window)
        for piece in BOARD_ONLY:
            self.assertNotIn(piece, shown, piece)
        self.assertIn("예시 데이터", shown)                                                                  # 옛 화면의 예시 표시는 그대로

    def test_the_old_cards_and_rows_still_come_from_the_old_keys_and_the_shell_takes_no_today_argument_any_more(self):
        window = self.make(services.FakeHomeProvider())
        self.assertEqual([card["label"] for card in window.state.home_view()["cards"]], ["추천 주제", "작성 완료", "발행 완료", "저장된 아이디어"])
        self.assertEqual(len(window.findChildren(UI.TopicRow)), 5)
        with self.assertRaises(TypeError):
            shell_module.AppShell(services.FakeHomeProvider(), autoload=False, today=datetime.date(2026, 11, 3))
        with self.assertRaises(TypeError):
            import chanceblog_desktop.ui.core.app_state as app_state
            app_state.AppState(services.FakeHomeProvider(), today=datetime.date(2026, 11, 3))


class KpiStringsInTheCurrentCardTest(QtBase):
    """새 KPI 의 글(`0개`·`연결 전`·`집계 전`)이 지금의 요약 카드(`SummaryCard`)에 들어가도 깨지지 않는다 — 카드는 이미 글 값을 받는 모양이라 그대로 쓸 수 있다(UI-C1d 가 쓴다)."""

    CASES = (("value", 7), ("value", 0), ("before_connect", None), ("before_count", None))

    def card_for(self, state, value):
        shown = board_view.kpi_vm("topics", "sum_topics", value, state)
        return {"key": "topics", "icon": "draft", "tone": "blue", "label": shown["label"], "value": shown["text"], "sub": shown["sub"], "go": None, "missing": shown["state"] != "value", "a11y": shown["a11y"]}, shown

    def host(self, width, cards):
        page = QWidget()
        grid = FlowGrid([UI.SummaryCard(card) for card in cards], (4, 2, 1), 190)
        from PySide6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(grid)
        page.resize(width, 400)
        page.show()
        self.addCleanup(page.close)
        self.settle(8)
        return page

    def test_every_kpi_state_fits_a_card_at_the_narrowest_column_and_in_a_wide_one(self):
        cards = [self.card_for(state, value)[0] for state, value in self.CASES]
        for width in (4 * 190 + 3 * 16, 2 * 190 + 16, 190, 420):                                            # 네 칸·두 칸·한 칸(가장 좁은 한 칸 190)·넓은 한 칸
            page = self.host(width, cards)
            self.assertEqual(ui_offscreen.find_clipping(page), [], width)
            self.assertEqual(len(page.findChildren(UI.SummaryCard)), 4)

    def test_the_card_shows_the_new_words_as_plain_text_and_keeps_the_number_style_only_for_numbers(self):
        cards = [self.card_for(state, value) for state, value in self.CASES]
        page = self.host(900, [card for card, _shown in cards])
        shown = [label.text() for label in page.findChildren(QLabel)]
        for _card, view in cards:
            self.assertTrue(any(view["text"] in item for item in shown), view["text"])
        self.assertTrue(any("연결 전" in item for item in shown) and any("집계 전" in item for item in shown))
        roles = {label.text(): label.property("role") for label in page.findChildren(QLabel)}
        self.assertEqual(roles.get("7개"), "metric")
        self.assertEqual(roles.get("연결 전"), "muted")                                                     # 숫자가 아닌 글은 흐린 글(옛 '–' 와 같은 취급)
        self.assertEqual(roles.get("집계 전"), "muted")
        self.assertEqual(text.T["board_before_connect"], "연결 전")


class RealAdapterInTheShellTest(QtBase):
    def test_the_shell_draws_the_real_adapter_data_without_a_slot_error_and_without_the_new_sections(self):
        import service_support as support
        import topics_support as ts
        from chanceblog_desktop.topicdb.store import open_for_write
        from chanceblog_desktop.service import topic_files as tf
        from chanceblog_desktop.ui import adapters
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            with open_for_write(tf.topic_paths(ctx.workspace).database) as store:
                store.add_candidates(lambda existing: [ts.rated(90, channel="naver_a", candidate_id="tc-naver_a-seed-aaaa000000000001", topic="예시 후보 하나"),
                                                       ts.rated(80, channel="naver_b", candidate_id="tc-naver_b-seed-aaaa000000000002", topic="예시 후보 둘")], now="2026-11-10T01:00:00Z")
            window = self.make(adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx))
            board = window.state.home_view()["board"]
            self.assertEqual((board["state"], board["sample"], [item["count"] for item in board["recommend"]]), ("ready", False, [1, 1]))
            shown = self.texts(window)
            for piece in BOARD_ONLY + ("예시 후보 하나", "예시 후보 둘"):
                self.assertNotIn(piece, shown, piece)
            self.assertNotIn("예시 데이터", shown)                                                          # 실제 데이터라 예시 표시가 없다


if __name__ == "__main__":
    unittest.main()
