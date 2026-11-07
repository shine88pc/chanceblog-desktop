"""UI-C1c(홈 데이터)의 Qt 시험 — 창을 띄우지 않고(offscreen) 홈 구역의 값(`board`)이 **화면에 그려진 모습**을 확인한다. 값·규칙은 `test_ui_c1c_core.py`·`test_ui_c1c_adapters.py` 가 PySide6 없이 지킨다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다).

의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 홈 구성 5): UI-C1c 는 새 구역의 값을 뷰모델에만 두고 화면은 그대로임을 지켰다(옛 `HomeLooksTheSameTest` — 위젯 목록이 같음·새 글이 어디에도 안 그려짐).
UI-C1d 가 그 값을 그린다 — 그 시험들은 의미가 없어져 같은 자리에 **그려진 것을 확인하는 시험**으로 바꿨다. 새 홈의 모양·배치·키보드는 `test_ui_qt_c1d.py` 가 지킨다. 여기서는:
  · 새 구역의 글(`점수 계산 전`·`관심도 데이터 부족`·`발행일 확인 불가`·`작성 중인 초안`·`연결 전`·`집계 전` 등)이 어느 상태에서 어디에 그려지는지, 새 구역을 안 읽는 공급자(`연결 전`)·오류도 슬롯 안 예외 없이 그려지는지.
  · KPI 의 글(`0개`·`7개`·`연결 전`·`집계 전`)이 가장 좁은 한 칸(190px)에도 잘림 없이 들어가는지(100%·125%·150%).
  · 실제 어댑터 데이터(임시 폴더의 진짜 보관함)로 앱 틀을 띄우면 엔진 후보가 줄로 그려지고 슬롯 안 예외가 없는지.
"""
import datetime
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
    from PySide6.QtWidgets import QAbstractButton, QLabel, QVBoxLayout, QWidget
    from chanceblog_desktop.ui.core import clock as clock_rules
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import board as board_module
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.qt.screens import FlowGrid

FRIDAY = datetime.datetime(2026, 11, 6, 20, 10, 0)


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

    def make(self, provider, size=(1366, 768), load=True):
        window = shell_module.AppShell(provider, autoload=False, clipboard=lambda _t: True, clock=clock_rules.FixedClock(FRIDAY))
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        if load:
            window.reload()
            self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10))
        self.settle()
        return window

    @staticmethod
    def texts(window):
        """창 안에 보이는 모든 글 — 글자·단추 글·접근 이름·툴팁을 한 줄로."""
        found = []
        for widget in window.centralWidget().findChildren(QWidget):
            if widget.isVisible():
                found += [widget.accessibleName(), widget.toolTip()] + ([widget.text()] if isinstance(widget, (QLabel, QAbstractButton)) else [])
        return " | ".join(item for item in found if item)


class HomeDrawsTheBoardTest(QtBase):
    def test_the_example_board_is_drawn_with_every_kind_of_row(self):
        """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 `HomeLooksTheSameTest` 의 첫 시험(새 구역을 안 읽어도 있어도 홈 화면이 같음)의 자리 — 이제 새 구역을 그린다. 예시 보드(점수 있음·점수 없음·관심도 없음·이전 점수 없음·오르내림·발행일 모름)가 모두 그려진다 — 새 구역의 글이 화면에 있다."""
        shown = self.texts(self.make(services.FakeHomeProvider()))
        for piece in ("점수 계산 전", "관심도 데이터 부족", "관심도 상승", "관심도 하락", "관심도 보통", "발행일 확인 불가", "작성 중인 초안", "초안 생성됨", "검토 필요", "최근 발행", "연결 상태", "예시", "블로그 A 추천", "블로그 B 추천",
                      "우선 추천", "일반 후보", "후보 5개", "후보 4개"):
            self.assertIn(piece, shown, piece)
        self.assertIn("예시 데이터", shown)

    def test_each_state_draws_its_own_words_and_a_provider_without_the_new_sections_draws_not_connected(self):
        """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 `HomeLooksTheSameTest` 의 '읽는 중·서랍·필터·좁은 폭에서도 화면이 그대로' 시험의 자리 — 구역마다 자기 상태 글을 그린다. 새 구역을 안 읽는 공급자(`board=None`)는 KPI 한 칸이 `연결 전` 이고 구역마다 `아직 연결하지 않았어요.` 이다 — 0 이나 빈 줄이 아니다. 빈·오류도 슬롯 안 예외 없이 그려진다."""
        window = self.make(services.FakeHomeProvider(board=None))
        self.assertEqual(window.state.home_view()["board"]["state"], "before_connect")
        shown = self.texts(window)
        self.assertIn("연결 전", shown)
        titles = [label.plain_text() for label in window.screen_widget.findChildren(UI.Label)]
        self.assertEqual(titles.count("아직 연결하지 않았어요."), 4)                                      # 구역마다 한 번(네 구역 — 추천 둘·작성 중 초안·최근 발행)
        self.assertEqual([card.kpi["text"] for card in window.screen_widget.findChildren(board_module.KpiCard)], ["연결 전", "3개", "2개", "2개"])      # 추천 주제만 연결 전, 나머지는 센 값
        self.assertEqual(len(window.screen_widget.findChildren(board_module.BoardRow)), 0)
        for scenario, expected in (("empty", "아직 추천할 후보가 없어요."), ("error", "후보를 불러오는 중 연결이 끊겼어요.")):
            shown = self.texts(self.make(services.FakeHomeProvider(scenario)))
            self.assertIn(expected, shown, scenario)

    def test_the_connection_line_says_not_read_yet_until_the_settings_have_been_read(self):
        """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 `HomeLooksTheSameTest` 의 '새 구역의 글이 화면 어디에도 없음' 시험의 자리 — 연결 한 줄의 글이 그려진다."""
        window = self.make(services.FakeHomeProvider())
        self.assertIn("연결 상태를 아직 읽지 않았어요. 설정에서 확인할 수 있어요.", self.texts(window))
        window.go("settings")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10))
        self.settle()
        window.go("home")
        self.settle()
        shown = self.texts(window)
        self.assertNotIn("연결 상태를 아직 읽지 않았어요", shown)                                         # 설정을 읽은 뒤에는 그 값(설정 묶음 머리와 같은 칩 글)으로 바뀐다
        self.assertIn("준비 중", shown)

    def test_a_connection_line_that_was_reading_when_the_user_came_back_home_gets_its_value_when_it_arrives(self):
        """의도적 추가(UI-C1d, D-203): 새 시험 — 연결 정보를 읽는 중에 홈으로 돌아와도 읽기가 끝나면 그 한 줄이 값으로 바뀐다. 설정 화면을 열어 연결 정보를 읽기 시작한 뒤 읽기가 끝나기 전에 홈으로 돌아오면 홈의 `연결 상태` 한 줄은 `읽고 있어요…` 이다 — 읽기가 끝나면 그 줄이 값으로 바뀐다(예전처럼 설정 화면을 보는 중일 때만 다시 그리면 홈의 줄이 영영 그대로다)."""
        window = self.make(services.FakeHomeProvider())
        window.state.conn_provider = services.FakeConnectionsProvider(delay=0.6)
        window.go("settings")
        self.assertTrue(window.state.conn_loading)
        window.go("home")
        self.settle()
        self.assertIn("연결 상태를 읽고 있어요…", self.texts(window))
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 10))
        self.settle(10)
        shown = self.texts(window)
        self.assertNotIn("연결 상태를 읽고 있어요…", shown)
        self.assertIn("준비 중", shown)
        self.assertEqual(window.state.page, "home")

    def test_the_shell_takes_no_today_argument_any_more(self):
        """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 시험은 옛 카드·행이 옛 키에서 그려지는 것과 `today` 인자 없음을 함께 봤다 — 옛 카드·행이 없어져 `today` 인자 없음(단언 그대로)만 남겼다. UI-C1c 가 지운 죽은 인자 `today` 는 여전히 받지 않는다(받으면 `TypeError`)."""
        with self.assertRaises(TypeError):
            shell_module.AppShell(services.FakeHomeProvider(), autoload=False, today=datetime.date(2026, 11, 3))
        with self.assertRaises(TypeError):
            import chanceblog_desktop.ui.core.app_state as app_state
            app_state.AppState(services.FakeHomeProvider(), today=datetime.date(2026, 11, 3))


class KpiCardStringsTest(QtBase):
    """KPI 의 글(`0개`·`7개`·`연결 전`·`집계 전`)이 카드(`board.KpiCard`)에 들어가도 깨지지 않는다 — 가장 좁은 한 칸 190px 에서도 글자 잘림 0."""

    CASES = (("value", 7), ("value", 0), ("before_connect", None), ("before_count", None))

    @staticmethod
    def card_for(state, value):
        return board_module.KpiCard(board_view.kpi_vm("topics", "sum_topics", value, state, "draft", "blue"))

    def host(self, width, cards):
        page = QWidget()
        grid = FlowGrid(cards, (4, 2, 1), 190)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(grid)
        page.resize(width, 400)
        page.show()
        self.addCleanup(page.close)
        self.settle(8)
        return page

    def test_every_kpi_state_fits_a_card_at_the_narrowest_column_and_in_a_wide_one(self):
        """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 `KpiStringsInTheCurrentCardTest` 는 새 KPI 글이 옛 요약 카드(`SummaryCard`)에 들어가는지 봤다 — 요약 카드가 `KpiCard` 로 바뀌어 같은 점검을 새 카드로 한다."""
        for width in (4 * 190 + 3 * 16, 2 * 190 + 16, 190, 420):                                            # 네 칸·두 칸·한 칸(가장 좁은 한 칸 190)·넓은 한 칸
            page = self.host(width, [self.card_for(state, value) for state, value in self.CASES])
            self.assertEqual(ui_offscreen.find_clipping(page), [], width)
            self.assertEqual(len(page.findChildren(board_module.KpiCard)), 4)

    def test_the_card_shows_the_new_words_as_plain_text_and_keeps_the_number_style_only_for_numbers(self):
        """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 `KpiStringsInTheCurrentCardTest` 의 같은 시험을 새 카드(`KpiCard`)로 다시 썼다 — 단언은 그대로다."""
        cards = [self.card_for(state, value) for state, value in self.CASES]
        page = self.host(900, cards)
        roles = {label.text(): label.property("role") for label in page.findChildren(QLabel)}
        self.assertEqual(roles.get("7개"), "metric")
        self.assertEqual(roles.get("0개"), "metric")                                                        # 진짜 0 은 숫자 모양
        self.assertEqual(roles.get("연결 전"), "h3")                                                        # 숫자가 아닌 글은 큰 숫자 모양이 아니라 상태 낱말
        self.assertEqual(roles.get("집계 전"), "h3")
        self.assertEqual(text.T["board_before_connect"], "연결 전")
        for card in cards:
            self.assertEqual(card.accessibleName(), card.kpi["a11y"])


class RealAdapterInTheShellTest(QtBase):
    def test_the_shell_draws_the_real_adapter_engine_candidates_as_rows_without_a_slot_error(self):
        """의도적 갱신(UI-C1d, D-201): UI-C1c 는 같은 실제 어댑터 데이터에서 새 구역의 글이 **안** 그려지는 것을 봤다. 이제 엔진 후보(가짜 이름의 예시 후보 둘)가 줄로 그려지고 실제 데이터라 `예시` 표시는 없다."""
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
            rows = window.screen_widget.findChildren(board_module.BoardRow)
            self.assertEqual([row.title_label.plain_text() for row in rows], ["예시 후보 하나", "예시 후보 둘"])
            shown = self.texts(window)
            for piece in ("예시 후보 하나", "예시 후보 둘", "관심도 데이터 부족"):
                self.assertIn(piece, shown, piece)
            self.assertNotIn("예시 데이터", shown)                                                          # 실제 데이터라 예시 표시가 없다
            self.assertEqual([row.sample_badge for row in rows], [None, None])
            self.assertEqual([card.kpi["text"] for card in window.screen_widget.findChildren(board_module.KpiCard)], ["2개", "0개", "0개", "0개"])
            window.close()


if __name__ == "__main__":
    unittest.main()
