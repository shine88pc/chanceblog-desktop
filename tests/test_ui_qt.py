"""PySide6 화면 시험 — 창을 화면에 띄우지 않고(offscreen) 앱 틀·홈·상태 화면·서랍·대화상자·토스트·키보드·접근 이름·작업 스레드를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — CI 의존성은 바꾸지 않았다). 사용자의 클립보드는 건드리지 않는다(가짜 클립보드).

지키는 것:
  · 메뉴 셋(홈·블로그 관리·설정 — P4b 가 블로그 관리를 더했다)·홈의 KPI 4·추천 줄 9(Naver A 5·B 4)·글 줄 6, 가로 스크롤 없음(1366·1536·1280·1920·1180·최소 창), 눌리는 칸 36px 이상·중요 단추 40~44px, 모든 눌리는 부품의 접근 이름.
    (UI-C1d, D-201: 옛 홈의 요약 카드·추천 행·칩·오른쪽 패널·빠른 작업·활용 팁은 없어졌다 — 아래 시험은 새 홈 기준이고 의도적으로 고친 시험은 이유 주석이 있다.)
  · Tab 한 바퀴(중간에 갇히지 않음)·Enter/Space·Esc(대화상자 먼저, 서랍은 포커스를 가두고 닫으면 돌려줌)·키보드 포커스에도 보이는 툴팁·칩을 눌러도 포커스 유지.
  · 같은 안내(토스트)는 쌓이지 않음(3.5초), 중복 불러오기 막기·취소·실패 뒤 다시 시도, 작업 중에도 화면이 응답.
  · 글꼴은 시스템 글꼴 Family + 토큰 크기, 고정폭은 진단·개발 정보만, 스타일시트는 토큰에서만(순수 검정·직접 색 없음), 화면은 부품만 쓴다(기본 위젯 직접 노출 금지·인라인 스타일 금지).
  · 글은 HTML 로 해석하지 않음, 키 모양 글·영문 오류 코드가 기본 화면에 남지 않음, 테마 선택 없음, 사진 출처 두 줄 복사와 `출처 복사됨`.
"""
import contextlib
import importlib.util
import io
import re
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from chanceblog_desktop.ui.core import attribution, part_rules, services, text, tokens  # noqa: E402  (PySide6 를 모르는 부분 — PySide6 가 없어도 불러온다)
from chanceblog_desktop.ui.core.jobs import JobFailure  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()                       # 창을 띄우지 않는다(offscreen) + 윈도 글꼴 폴더
    from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, QTimer
    from PySide6.QtGui import QFont, QFontDatabase, QIcon
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QPushButton, QStyleFactory, QToolTip, QVBoxLayout, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import board as board_module
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import gauges as gauge_module
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.qt import theme

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
FAKE_KEY = "AI" + "za" + "C" * 35                              # 구글 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)


class Flaky(services.HomeProvider):
    """처음 몇 번은 실패하고 그 뒤에는 정상으로 돌아오는 공급자(다시 시도 시험)."""

    def __init__(self, failures=1, code="NETWORK_DOWN", message="연결이 끊겼어요."):
        self.failures, self.code, self.message = failures, code, message
        self.calls = 0

    def load_home(self, progress, cancelled):
        self.calls += 1
        if self.calls <= self.failures:
            raise JobFailure(self.message, code=self.code)
        return services.FakeHomeProvider().load_home(progress, cancelled)


class Custom(services.HomeProvider):
    def __init__(self, topics, **extra):
        self.data = services.HomeData(topics=tuple(topics), sample=False, **extra)

    def load_home(self, progress, cancelled):
        return self.data


def first_row_id(window, index=0):
    """홈의 `index` 번째 추천 줄(위에서 아래로)의 번호 — 서랍을 여는 데 쓴다(UI-C1d: 옛 `home_rows()` 가 없다)."""
    return [row["id"] for item in window.state.home_view()["board"]["recommend"] for row in item["rows"]][index]


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class QtBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def setUp(self):
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: self.errors.append(f"{kind.__name__}: {value}")        # 화면 슬롯 안의 예외도 시험이 잡는다
        self.clipboard = []

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def make(self, provider=None, size=(1440, 900), wait=True, **kwargs):
        window = shell_module.AppShell(provider or services.FakeHomeProvider(), autoload=False, clipboard=lambda text_: (self.clipboard.append(text_), True)[1], **kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        if wait is not None:
            window.reload()
            if wait:
                self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10))
        self.settle()
        self.activate(window)
        return window

    def activate(self, window):
        """화면 없는 환경에서는 창이 저절로 '활성' 이 되지 않아 포커스가 안 간다 — 활성으로 만든다."""
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)

    def focus(self, widget, reason=None):
        self.activate(widget.window())
        widget.setFocus(Qt.TabFocusReason if reason is None else reason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), widget)

    def interactive(self, window):
        return [w for w in window.findChildren(QWidget) if w.isVisible() and (isinstance(w, (QAbstractButton, QLineEdit)) or isinstance(w, UI.Pressable) and w.focusPolicy() != Qt.NoFocus)]


class ShellTest(QtBase):
    def test_shell_has_the_two_completed_menus_and_the_home_shows_the_kpis_the_recommendations_the_lists_and_the_connection_line(self):
        """의도적 갱신(UI-C1a, D-172): 옛 시험은 메뉴 6개를 못박았다. 운영자 2026-11-06 확인 요청 004 의 답 — 완성된 화면(홈·설정)만 실제 메뉴다.
        의도적 갱신(UI-C1d, D-201): 옛 시험은 홈의 요약 카드 4·추천 행 5·칩 5 를 봤다. 새 홈은 KPI 넷·Naver A 추천(5)·Naver B 추천(4)·작성 중 초안(3)·최근 발행(3)·연결 상태 한 줄이고 칩은 없다."""
        window = self.make()
        self.assertEqual(list(window.nav_buttons), ["home", "topics", "drafts", "seed", "blogs", "settings"])    # 의도적 갱신(P4e, D-282): 초안 작성도 완성돼 주제 후보 다음에 올랐다 / 의도적 갱신(P4b, D-210): 블로그 관리가 완성돼 실제 메뉴로 올랐다(옛 값 홈·설정 둘) — 시험 이름의 '둘' 은 그대로 둔다 / 의도적 갱신(Seed 관리, D-230): Seed 관리도 완성돼 올랐다 / 의도적 갱신(P4d, D-270): 주제 후보도 완성돼 홈 다음에 올랐다
        self.assertTrue(window.nav_buttons["home"].isChecked())
        page = window.screen_widget
        self.assertEqual(len(page.findChildren(board_module.KpiCard)), 4)
        self.assertEqual(len(page.findChildren(board_module.BoardRow)), 9)
        self.assertEqual(len(page.findChildren(board_module.ListRow)), 6)
        self.assertEqual([label.text() for label in page.findChildren(UI.ElidedLabel) if label.property("role") == "h2"], ["블로그 A 추천", "블로그 B 추천", "작성 중인 초안", "최근 발행"])
        self.assertEqual([row.row["channel"] for row in page.findChildren(board_module.BoardRow)], ["A"] * 5 + ["B"] * 4)         # 위에서 아래로 Naver A 추천 다음 Naver B 추천
        self.assertEqual([b for b in page.findChildren(QAbstractButton) if b.property("chip")], [])                              # 칩은 없다
        self.assertTrue(any(b.accessibleName() == "예시 데이터" for b in window.findChildren(QAbstractButton)))

    def test_unfinished_screens_cannot_be_opened_at_all_and_the_page_stays_where_it_was(self):
        """의도적 갱신(UI-C1a, D-172): 옛 시험은 다른 메뉴가 '아직 만들고 있어요' 자리표시 화면을 열고 '홈으로' 로 돌아오는 것을 보았다. 이제 그 화면은 없다 — 화면 이름을 직접 불러도 열리지 않고 지금 화면이 그대로다.
        (UI-C1d: 추천 줄의 수로 확인한다.)"""
        window = self.make()
        before = window.screen_widget
        for key in ("draft", "history", "nope"):                                                 # 의도적 갱신(P4b, D-210): 'blogs' 는 이제 완성된 화면이라 열린다(아래 화면 표 시험이 확인) / 의도적 갱신(Seed 관리, D-230): 'seed' 도 이제 완성된 화면이라 열린다(`test_ui_qt_seeds` 가 확인) / 의도적 갱신(P4d, D-270): 'topics' 도 이제 완성된 화면이라 열린다(`test_ui_qt_candidates` 가 확인)
            window.go(key)
            self.settle()
            self.assertEqual(window.state.page, "home", key)
            self.assertIs(window.screen_widget, before, key)                                  # 다시 그리지도 않았다
            self.assertTrue(window.nav_buttons["home"].isChecked(), key)
        self.assertEqual(len(window.screen_widget.findChildren(board_module.BoardRow)), 9)

    def test_a_redraw_never_deletes_the_old_page_inside_the_click_that_caused_it(self):
        """눌린 단추가 자기 눌림 처리 안에서 지워지면 위험하다 — 옛 화면은 처리가 끝난 다음 차례에 지워진다.
        의도적 갱신(UI-C1d, D-201): 옛 시험은 칩을 눌러 다시 그렸다 — 칩이 없어졌다. 추천 줄을 눌러 서랍을 여는 것(다시 그린다)으로 같은 것을 본다."""
        import shiboken6
        window = self.make()
        old = window.screen_widget
        window.open_drawer(first_row_id(window))
        self.assertIsNot(window.screen_widget, old)
        self.assertTrue(shiboken6.isValid(old))                                           # 아직 안 지워졌다
        self.settle(3)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)                    # (이 시험에는 이벤트 루프가 없어 '지우기 예약' 을 직접 처리한다)
        self.assertFalse(shiboken6.isValid(old))                                          # 처리가 끝난 뒤에 지워졌다

    def test_there_is_no_horizontal_scroll_at_any_required_size_and_the_minimum_window(self):
        window = self.make()
        for size in ((1366, 768), (1536, 864), (1280, 720), (1920, 1080), (window.minimumWidth(), window.minimumHeight())):
            window.resize(*size)
            self.settle()
            ui_offscreen.wait_until(self.app, lambda: window.scroll.horizontalScrollBar().maximum() == 0, 2)      # 배치가 몇 차례 다시 계산되는 동안 잠깐 걸린다
            self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, size)
            self.assertLessEqual(window.screen_widget.width(), window.scroll.viewport().width(), size)

    def test_the_body_and_the_drawer_never_offer_a_horizontal_scroll_bar_by_policy(self):
        """가로 스크롤 없음은 결과(넘치지 않음)만이 아니라 규칙이다 — 배치가 언제 넘치더라도 가로 막대를 내밀지 않는다."""
        window = self.make()
        self.assertEqual(window.scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertEqual(window.drawer.scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

    def test_layout_changes_with_the_width_not_with_fixed_sizes(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 오른쪽 패널이 옆에서 아래로(`ResponsiveBody`)·요약 카드 4→2→1열·추천 행의 지표 칸 접기를 봤다 — 모두 없어졌다.
        새 홈의 배치 바뀜: KPI 4→2→1열·추천 구역 두 칸 나란히 → 위아래·글 구역 두 칸 → 위아래(논리 폭 기준, 규칙은 `part_rules`)."""
        window = self.make(size=(1440, 900))
        kpi, recommend, posts = window.screen_widget.findChildren(S.FlowGrid)
        self.assertEqual((kpi._cols, recommend._cols, posts._cols), (4, 2, 2))
        for width, expected in ((1180, (4, 1, 2)), (900, (2, 1, 1)), (1920, (4, 2, 2)), (1280, (4, 2, 2))):
            window.resize(width, 800)
            self.settle()
            ui_offscreen.wait_until(self.app, lambda: window.scroll.horizontalScrollBar().maximum() == 0, 2)
            self.assertEqual((kpi._cols, recommend._cols, posts._cols), expected, width)
            self.assertEqual((kpi._cols, recommend._cols, posts._cols), (part_rules.home_kpi_columns(kpi.width()), part_rules.home_section_columns(recommend.width()), part_rules.home_posts_columns(posts.width())), width)
        for width in (200, 395, 396, 807, 808, 1500):                                    # 격자가 쓰는 규칙은 순수 함수와 같다
            self.assertEqual(kpi.columns_for(width), part_rules.grid_columns(width, (4, 2, 1), tokens.LAYOUT["kpi_min_col"], 16), width)

    def test_the_default_window_size_is_near_1440_by_900_and_never_larger_than_a_small_screen_allows(self):
        width, height = shell_module.AppShell.default_size()
        self.assertGreaterEqual(width, tokens.LAYOUT["window_min"][0])
        self.assertGreaterEqual(height, tokens.LAYOUT["window_min"][1])
        self.assertLessEqual(width, 1440)
        self.assertLessEqual(height, 900)

    def test_a_long_channel_name_in_a_section_header_is_elided_with_the_text_in_the_tooltip_and_never_leaves_its_card(self):
        """오른쪽 패널이 옆에 있는 넓은 창에서 블로그 이름이 한글 14자쯤부터 카드 밖으로 잘렸다(검증 M-4) — 이제 한 줄 …(줄임표)로 줄고 부품이 받은 글이 툴팁에 있다(받은 글은 뷰모델이 이미 40자로 줄인 글이라 전체 이름이 아니다 — N-5).
        의도적 갱신(UI-C1d, D-201): 오른쪽 패널(내 블로그 현황)이 없어졌다 — 이름이 보이는 새 자리는 추천 구역 머리(`블로그 이름 추천`)다."""
        long_name = "가나다라마바사아자차카타파하" * 2 + "가나"
        rows = (services.RecommendRow("x1", "주제", 80, None, None),)
        board = services.BoardData((services.ChannelRead("A", long_name, True, "ok", "", rows), services.ChannelRead("B", "블로그 비", True, "ok", "", rows)), services.ListRead(), services.ListRead())
        provider = Custom([], board=board)
        for size in ((1920, 1080), (1440, 900), (1366, 768), (1100, 700)):
            window = self.make(provider, size=size)
            labels = [w for w in window.screen_widget.findChildren(UI.ElidedLabel) if w.text().startswith("가나다라")]
            self.assertEqual(len(labels), 1, size)
            label = labels[0]
            self.assertEqual(label.text(), f"{long_name} 추천")                              # 부품이 받은 글(뷰모델이 가린 뒤 40자까지 두는 이름 — 30자라 그대로 + 추천)
            self.assertEqual(label.toolTip(), label.text())                                  # 툴팁은 부품이 받은 글
            card = label.parentWidget()
            while card is not None and card.property("card") != "true":
                card = card.parentWidget()
            self.assertIsNotNone(card)
            self.assertLessEqual(label.mapTo(card, label.rect().bottomRight()).x(), card.width(), size)       # 카드 밖으로 나가지 않는다
            self.assertEqual(ui_offscreen.find_clipping(window), [], size)
            self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, size)
            if label.width() < label.fontMetrics().horizontalAdvance(label.text()):          # 폭이 모자라면 줄임표로 끝난다
                self.assertTrue(label.fontMetrics().elidedText(label.text(), Qt.ElideRight, label.width()).endswith("…"))
            short = [w for w in window.screen_widget.findChildren(UI.ElidedLabel) if w.text() == "블로그 비 추천"]
            self.assertEqual(len(short), 1)
            self.assertGreaterEqual(short[0].width(), short[0].fontMetrics().horizontalAdvance("블로그 비 추천"), size)       # 짧은 이름은 줄지 않는다


class AccessibilityTest(QtBase):
    def test_every_interactive_part_has_an_accessible_name_and_a_big_enough_target(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 서랍을 연 상태에서 24개 이상을 봤다(실제 메뉴 4·상단 설정 아이콘·전체 보기·빠른 작업 3·눌리는 요약 카드 2·칩·행마다 상세·초안 단추 …). 새 홈의 누르는 부품은 적다:
        메뉴 4(홈·Seed 관리·블로그 관리·설정 — UI-C1d 때는 2, P4b 와 Seed 관리가 하나씩 더했다)·예시 데이터·다시 불러오기·추천 줄 9(홈) — 서랍이 열려 있으면 서랍 안(닫기·초안·보류·더보기 4)이 더해지고 홈 쪽은 포커스를 받지 못한다(가둠). 두 상태를 모두 보고 이름·크기는 하나도 빠뜨리지 않고 점검한다."""
        window = self.make()
        shown = {"홈": self.interactive(window)}
        self.assertEqual(len(shown["홈"]), 6 + 2 + 9)                                     # 메뉴 6(홈·주제 후보·초안 작성·Seed 관리·블로그 관리·설정 — P4b·Seed 관리 병합으로 둘 늘었고 의도적 갱신(P4d, D-270)으로 주제 후보가, 의도적 갱신(P4e, D-282)으로 초안 작성이 하나씩 더했다) + (예시 데이터·다시 불러오기) + 추천 줄 9
        window.open_drawer(first_row_id(window))
        self.settle()
        shown["서랍"] = self.interactive(window)
        self.assertGreaterEqual(len(shown["서랍"]), 2 + 2 + 4)                            # 메뉴·머리 단추(눌리지만 가둠으로 포커스는 못 받음) + 서랍 안 4
        for where, found in shown.items():
            for widget in found:
                self.assertTrue(widget.accessibleName().strip(), f"접근 이름이 없다({where}): {type(widget).__name__} {getattr(widget, 'text', lambda: '')()!r}")
                if isinstance(widget, QAbstractButton):
                    self.assertGreaterEqual(widget.height(), tokens.SIZE["hit"], widget.accessibleName())
                    self.assertGreaterEqual(widget.width(), tokens.SIZE["hit"], widget.accessibleName())
                    if not widget.text().strip():                                            # 아이콘만 있는 단추는 툴팁도 같은 말
                        self.assertEqual(widget.toolTip(), widget.accessibleName())
                else:
                    self.assertGreaterEqual(widget.height(), tokens.SIZE["hit"], widget.accessibleName())        # 추천 줄도 누르는 칸이 36 이상(실제 64+)

    def test_important_buttons_are_between_40_and_44_pixels_tall(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 홈의 주 단추(이 주제로 초안 만들기·주제 분석 시작)를 봤다 — 홈에서 쓰기·이동 단추를 없애 **홈에는 주 단추가 없다**(화면당 주 행동 1개 이하). 주 단추가 남은 곳(상세 서랍의
        초안 단추·오류 카드의 다시 시도)에서 같은 높이 규칙을 본다."""
        window = self.make()
        self.assertEqual([b for b in window.screen_widget.findChildren(QAbstractButton) if b.property("kind") == "primary"], [])
        window.open_drawer(first_row_id(window))
        self.settle()
        primary = [b for b in window.drawer.findChildren(QAbstractButton) if b.property("kind") == "primary"]
        self.assertEqual(len(primary), 1)                                                  # 서랍에는 주 단추가 하나
        failing = self.make(Flaky(failures=9))
        primary += [b for b in failing.screen_widget.findChildren(QAbstractButton) if b.property("kind") == "primary"]
        self.assertEqual(len(primary), 2)                                                  # 오류 카드의 다시 시도 하나
        for button in primary:
            self.assertTrue(40 <= button.height() <= 48, button.accessibleName())
        for button in (b for b in window.findChildren(QAbstractButton) if b.property("nav")):
            self.assertGreaterEqual(button.height(), 40)

    def test_tab_goes_all_the_way_around_and_never_lands_on_something_unnamed(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 25곳 이상·메뉴·칩·행·단추 네 종류를 봤다(칩·행마다 단추가 없어졌다). 새 홈의 Tab 한 바퀴는 정확히 15곳 — 메뉴 넷(홈·Seed 관리·블로그 관리·설정 — UI-C1d 때는 13곳·메뉴 둘이었고 P4b 가 블로그 관리, Seed 관리가 Seed 관리 메뉴를 더했다)·예시 데이터·다시 불러오기·추천 줄 아홉(위에서 아래로,
        Naver A 추천 다섯 다음 Naver B 추천 넷) — 이고 같은 곳을 두 번 지나지 않고 이름 없는 곳에 닿지 않는다."""
        window = self.make()
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
                break
        else:
            self.fail("Tab 이 한 바퀴를 돌지 못했다")
        names = [w.accessibleName() for w in seen]
        self.assertTrue(all(name.strip() for name in names), names)
        self.assertTrue(all(isinstance(w, (QAbstractButton, QLineEdit, UI.Pressable)) for w in seen), [type(w).__name__ for w in seen])      # 눌리거나 쓰는 곳만 정거장(스크롤 영역 같은 틀은 아니다)
        self.assertEqual(len(seen), 17)                                                   # 메뉴 여섯(홈·주제 후보·초안 작성·Seed 관리·블로그 관리·설정 — 의도적 갱신(P4d, D-270): 주제 후보가 하나 더했고 의도적 갱신(P4e, D-282): 초안 작성이 하나 더했다)·예시 데이터·다시 불러오기·추천 줄 아홉
        self.assertEqual(len(seen), len(set(map(id, seen))))                              # 같은 곳을 두 번 지나지 않는다(갇히지 않는다)
        kinds = ["nav" if w.property("nav") else "row" if isinstance(w, board_module.BoardRow) else "button" for w in seen]
        self.assertEqual(kinds, ["nav"] * 6 + ["button", "button"] + ["row"] * 9)         # 의도적 갱신(P4d, D-270): 메뉴가 넷에서 다섯 / 의도적 갱신(P4e, D-282): 다섯에서 여섯
        self.assertEqual([w.row["channel"] for w in seen if isinstance(w, board_module.BoardRow)], ["A"] * 5 + ["B"] * 4)                    # 옆 칸을 건너뛰지 않고 Naver A 추천 → Naver B 추천

    def test_enter_and_space_press_buttons_rows_and_cards(self):
        """의도적 갱신(UI-C1a, D-172): 요약 카드는 눌러서 가는 곳이 없다(미완성 '주제 후보' 로 가던 길을 끊었다).
        의도적 갱신(UI-C1d, D-201): 옛 시험은 행을 Enter·Space 로 '고르는 것'(선택)을 봤다 — 선택이 없어졌다. 새 추천 줄은 Enter·Space 로 **기존 상세 서랍을 연다**. KPI 카드는 그대로 누르는 곳이 아니다(포커스도 안 받는다)."""
        window = self.make()
        pressed = []
        button = UI.Button("secondary", "누름")
        button.clicked.connect(lambda: pressed.append("button"))
        button.setParent(window.centralWidget())
        button.show()
        self.focus(button)
        QTest.keyClick(button, Qt.Key_Return)
        QTest.keyClick(button, Qt.Key_Space)
        self.assertEqual(pressed, ["button", "button"])
        rows = window.screen_widget.findChildren(board_module.BoardRow)
        self.focus(rows[2])
        QTest.keyClick(rows[2], Qt.Key_Return)
        self.settle()
        self.assertEqual(window.state.drawer_id, rows[2].row["id"])
        self.assertTrue(window.drawer.is_open)
        window.close_drawer()
        self.settle()
        rows = window.screen_widget.findChildren(board_module.BoardRow)
        self.focus(rows[3])
        QTest.keyClick(rows[3], Qt.Key_Space)
        self.settle()
        self.assertEqual(window.state.drawer_id, rows[3].row["id"])
        window.close_drawer()
        self.settle()
        card = window.screen_widget.findChildren(board_module.KpiCard)[0]
        self.assertEqual(card.focusPolicy(), Qt.NoFocus)
        QTest.keyClick(card, Qt.Key_Return)
        self.settle()
        self.assertEqual((window.state.page, window.state.drawer_id), ("home", None))                      # KPI 카드는 눌러도 아무 일이 없다

    def test_a_redraw_keeps_the_keyboard_focus_on_the_same_row(self):
        """의도적 교체(UI-C1d, D-201): 옛 `test_clicking_a_chip_with_the_keyboard_keeps_the_focus_on_it` 는 칩을 키보드로 눌러 홈이 다시 그려져도 포커스가 그 칩에 남는 것을 봤다(칩이 없어졌다).
        같은 성질 — 다시 그려도 키보드 포커스가 같은 곳(`focus_key`)에 남는다 — 을 추천 줄로 본다."""
        window = self.make()
        row = window.screen_widget.findChildren(board_module.BoardRow)[1]
        key = row.property("focus_key")
        self.focus(row)
        old = window.screen_widget
        window.render()
        self.settle()
        self.assertIsNot(window.screen_widget, old)                                         # 정말 다시 그렸다
        focus = window.focusWidget()
        self.assertIsNotNone(focus)
        self.assertEqual(focus.property("focus_key"), key)
        self.assertIsInstance(focus, board_module.BoardRow)

    def test_a_tooltip_shows_when_the_keyboard_focus_arrives(self):
        window = self.make()
        refresh = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.accessibleName() == text.T["refresh"])
        QToolTip.hideText()
        self.focus(refresh)
        self.assertTrue(QToolTip.isVisible())
        self.assertEqual(QToolTip.text(), text.T["refresh"])
        other = window.screen_widget.findChildren(board_module.BoardRow)[0]                  # 의도적 갱신(UI-C1d): 옛 시험은 칩으로 옮겼다 — 말풍선이 없는 곳(추천 줄)으로 옮기면 사라진다
        self.focus(other)
        self.assertFalse(QToolTip.isVisible())

    def test_the_window_has_no_theme_chooser_anywhere(self):
        """의도적 갱신(UI-C1d, D-201): 서랍을 여는 후보를 옛 홈 행(`home_rows()[0]`)에서 새 홈의 첫 추천 줄(`first_row_id`)로 바꿨다 — 단언은 그대로다."""
        window = self.make()
        window.open_drawer(first_row_id(window))
        window.show_sample_info()
        self.settle()
        shown = [w.text() for w in window.findChildren(QLabel)] + [w.text() + w.accessibleName() for w in window.findChildren(QAbstractButton)]
        for item in shown:
            self.assertNotRegex(item, r"테마|다크|Dark|Light", item)


class OverlayTest(QtBase):
    def test_the_drawer_opens_traps_the_tab_key_and_gives_the_focus_back_on_esc(self):
        """의도적 갱신(UI-C1d, D-201): 서랍을 여는 곳이 행 끝의 상세 단추에서 추천 줄 자신(Enter)이 되었다 — 닫으면 포커스가 그 줄로 돌아오는 규칙(`focus_key`)은 그대로다."""
        window = self.make()
        topic_id = first_row_id(window, 1)
        opener = next(w for w in window.screen_widget.findChildren(board_module.BoardRow) if w.property("focus_key") == "detail:" + topic_id)
        self.focus(opener)
        QTest.keyClick(opener, Qt.Key_Return)
        self.settle()
        self.assertTrue(window.drawer.is_open)
        self.activate(window)
        self.assertIs(window.focusWidget(), window.drawer_close)                          # 처음 포커스는 닫기 단추
        current = window.drawer_close
        self.focus(current)
        for _ in range(40):
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            self.assertTrue(window.drawer.isAncestorOf(current), "서랍이 열린 동안 Tab 이 서랍 밖으로 나갔다")
        QTest.keyClick(current, Qt.Key_Escape)                                           # 진짜 Esc 키(단축키)로 닫는다 — 직접 함수를 부르지 않는다
        self.settle()
        self.assertFalse(window.drawer.is_open)
        self.assertEqual(window.focusWidget().property("focus_key"), "detail:" + topic_id)
        self.assertIsInstance(window.focusWidget(), board_module.BoardRow)

    def test_clicking_outside_the_drawer_closes_it_and_the_page_buttons_work_again(self):
        window = self.make()
        window.open_drawer(first_row_id(window))
        self.settle()
        window.drawer.scrim.mousePressEvent(None)
        self.settle()
        self.assertFalse(window.drawer.is_open)
        row = window.screen_widget.findChildren(board_module.BoardRow)[0]                  # 의도적 갱신(UI-C1d): 옛 시험은 칩을 봤다 — 페이지의 누르는 부품(추천 줄·다시 불러오기)이 다시 포커스를 받는다
        self.assertNotEqual(row.focusPolicy(), Qt.NoFocus)
        self.assertNotEqual(window.refresh_button.focusPolicy(), Qt.NoFocus)

    def test_the_dialog_comes_first_on_esc_and_traps_focus_too(self):
        """의도적 갱신(UI-C1d, D-201): 서랍을 여는 후보를 옛 홈 행(`home_rows()[0]`)에서 새 홈의 첫 추천 줄(`first_row_id`)로 바꿨다 — 단언은 그대로다."""
        window = self.make()
        window.open_drawer(first_row_id(window))
        window.show_dialog("확인해 주세요", "정말 그렇게 할까요?", ok="그렇게 해요", cancel="아니요")
        self.settle()
        self.assertTrue(window.dialog.is_open and window.drawer.is_open)
        self.assertEqual(window.focusWidget().text(), "그렇게 해요")                    # 처음 포커스는 기본 단추
        self.activate(window)
        current = window.focusWidget()
        self.focus(current)
        for _ in range(12):
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertTrue(window.dialog.isAncestorOf(current))
        QTest.keyClick(current, Qt.Key_Escape)
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertTrue(window.drawer.is_open)                                            # 서랍은 그대로
        self.activate(window)
        self.assertTrue(window.focusWidget() is not None)
        QTest.keyClick(window.focusWidget(), Qt.Key_Escape)
        self.settle()
        self.assertFalse(window.drawer.is_open)

    def test_the_dialog_buttons_do_what_they_say(self):
        window = self.make()
        done = []
        window.show_dialog("제목", "본문", ok="좋아요", cancel="그만둘래요", on_ok=lambda: done.append("ok"))
        buttons = {b.text(): b for b in window.dialog.findChildren(QAbstractButton)}
        QTest.mouseClick(buttons["그만둘래요"], Qt.LeftButton)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(done, [])
        window.show_dialog("제목", "본문", ok="좋아요", cancel="그만둘래요", on_ok=lambda: done.append("ok"))
        buttons = {b.text(): b for b in window.dialog.findChildren(QAbstractButton)}
        QTest.keyClick(buttons["좋아요"], Qt.Key_Return)
        self.assertEqual(done, ["ok"])
        self.assertFalse(window.dialog.is_open)

    def test_the_sample_badge_opens_the_explanation_dialog(self):
        window = self.make()
        badge = next(b for b in window.findChildren(QAbstractButton) if b.accessibleName() == "예시 데이터")
        QTest.mouseClick(badge, Qt.LeftButton)
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(window.dialog.accessibleName(), text.T["sample_dialog_title"])
        self.assertLessEqual(window.dialog.width(), window.width())

    def test_modals_fit_inside_a_small_window(self):
        """의도적 갱신(UI-C1d, D-201): 서랍을 여는 후보를 옛 홈 행(`home_rows()[0]`)에서 새 홈의 첫 추천 줄(`first_row_id`)로 바꿨다 — 단언은 그대로다."""
        window = self.make(size=(900, 560))
        window.open_drawer(first_row_id(window))
        self.settle()
        self.assertLessEqual(window.drawer.width(), window.width())
        window.show_sample_info()
        self.settle()
        self.assertLessEqual(window.dialog.width(), window.width())
        self.assertLessEqual(window.dialog.height(), window.height())

    def test_the_drawer_and_the_dialog_never_get_wider_than_the_window_they_sit_in(self):
        """최소 창(900)에서는 서랍(420)·대화상자(480)가 어차피 창보다 좁아 위 시험이 폭 상한(92%·94%)을 못 잰다 — 아주 좁은 부모 창에서 직접 잰다."""
        host = QWidget()
        host.resize(300, 500)
        self.addCleanup(host.close)
        drawer = UI.Drawer(host)
        self.assertEqual(drawer.width_px(), 276)                                          # 300 의 92%
        wide = QWidget()
        wide.resize(2000, 900)
        self.addCleanup(wide.close)
        self.assertEqual(UI.Drawer(wide).width_px(), tokens.FRAME["drawer"])               # 넓은 창에서는 정해진 폭(UI-C1a: 옛 `LAYOUT["drawer"]` 를 새 틀 상수 `FRAME["drawer"]` 로 옮겼다 — 값 420 은 그대로)
        dialog = UI.Dialog(host)
        dialog.present()
        self.assertEqual(dialog.width(), 282)                                             # 300 의 94%
        dialog.dismiss()
        dialog = UI.Dialog(wide)
        dialog.present()
        self.assertEqual(dialog.width(), tokens.LAYOUT["dialog"])
        dialog.dismiss()

    def test_the_default_window_follows_a_small_screen_but_never_goes_below_the_minimum(self):
        from PySide6.QtCore import QRect

        def default_on(width, height):
            screen = types.SimpleNamespace(availableGeometry=lambda: QRect(0, 0, width, height))
            with mock.patch.object(shell_module.QGuiApplication, "primaryScreen", return_value=screen):
                return shell_module.AppShell.default_size()

        self.assertEqual(default_on(1000, 700), (960, 658))                               # 화면의 96%·94%
        self.assertEqual(default_on(3000, 2000), (1440, 900))                             # 큰 화면에서는 정해진 크기
        self.assertEqual(default_on(800, 500), tokens.LAYOUT["window_min"])               # 너무 작은 화면에서도 최소 창보다 작게 만들지 않는다


class ToastAndActionTest(QtBase):
    def test_a_new_toast_tells_the_screen_reader_with_one_alert_event_and_a_repeat_does_not(self):
        from PySide6.QtGui import QAccessible
        calls = []
        window = self.make()
        with mock.patch.object(UI, "QAccessible", types.SimpleNamespace(Alert=QAccessible.Alert, updateAccessibility=calls.append)):
            window.notify("새 안내")
            window.notify("새 안내")                                                      # 같은 안내는 보이는 시간만 늘린다 — 알림을 또 보내지 않는다
            window.notify("다른 안내")
        self.assertEqual([(event.type(), event.object() is window.toast) for event in calls], [(QAccessible.Alert, True)] * 2)

    def test_the_same_toast_never_stacks_and_lasts_three_and_a_half_seconds(self):
        window = self.make()
        for _ in range(6):
            window.notify("같은 안내예요")
        self.settle()
        self.assertEqual(len(window.findChildren(UI.Toast)), 1)
        self.assertEqual(window.toast.policy.shown, 1)
        self.assertTrue(window.toast.isVisible())
        self.assertEqual(window.toast.text(), "같은 안내예요")
        self.assertEqual(window.toast._timer.interval(), 3500)
        window.notify("다른 안내예요")
        self.assertEqual(window.toast.text(), "다른 안내예요")
        self.assertEqual(len(window.findChildren(UI.Toast)), 1)
        window.toast._expire()
        self.assertFalse(window.toast.isVisible())
        window.notify("")
        self.assertFalse(window.toast.isVisible())

    def test_the_toast_stays_inside_a_narrow_window(self):
        window = self.make(size=(900, 560))
        window.notify("아주 긴 안내 " * 20)
        self.settle()
        self.assertGreaterEqual(window.toast.x(), 0)
        self.assertLessEqual(window.toast.x() + window.toast.width(), window.width())

    def test_unbuilt_features_only_show_a_notice(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 추천 행의 '초안 만들기' 단추와 빠른 작업을 눌러 안내만 뜨는 것을 봤다 — 둘 다 홈에서 없어졌다(동작하지 않는 단추를 없앴다). 아직 만들지 않은 기능의 안내는
        기존 상세 서랍의 초안 단추가 그대로 한다 — 눌러도 안내만 뜨고 화면은 그대로다."""
        window = self.make()
        window.open_drawer(first_row_id(window))
        self.settle()
        before = (window.state.page, window.state.drawer_id, window.state.list_state)
        button = next(b for b in window.drawer.findChildren(QAbstractButton) if str(b.property("focus_key")).startswith("drawer-draft:"))
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertIn("다음 단계", window.toast.text())
        self.assertEqual(before, (window.state.page, window.state.drawer_id, window.state.list_state))

    def test_the_removed_home_parts_are_not_on_the_screen_in_any_state(self):
        """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 `test_closing_the_tip_removes_only_the_tip`(활용 팁 닫기)과 `test_the_quick_action_that_is_left_only_says_not_yet_and_never_navigates`(빠른 작업)의 자리.
        전체 보기·빠른 작업·활용 팁·동작하지 않는 초안 만들기·빈 상태의 주제 분석 시작·월 검색량·문서 수는 어느 상태의 홈에도 없고, 홈의 단추는 `예시 데이터`·`다시 불러오기`(와 그 상태 자신의 다시 시도·진단 정보·취소)뿐이다."""
        banned = ("전체 보기", "빠른 작업", "활용 팁", "초안 만들기", "주제 분석 시작", "새 초안 만들기", "월 검색량", "문서 수", "검색량")
        allowed = {"예시 데이터", text.T["refresh"], text.T["retry"], text.T["diag_show"], text.T["load_cancel"]}
        cases = (("정상", services.FakeHomeProvider(), {"예시 데이터", text.T["refresh"]}), ("빈", services.FakeHomeProvider("empty"), {"예시 데이터", text.T["refresh"]}),
                 ("일부만", services.FakeHomeProvider("partial"), {"예시 데이터", text.T["refresh"]}), ("오프라인", services.FakeHomeProvider("offline"), {"예시 데이터", text.T["refresh"]}),
                 ("연결 전", services.FakeHomeProvider(board=None), {"예시 데이터", text.T["refresh"]}), ("오류", Flaky(failures=9), {text.T["refresh"], text.T["retry"], text.T["diag_show"]}),
                 ("읽는 중", services.FakeHomeProvider(delay=2), {text.T["refresh"], text.T["load_cancel"]}))
        for name, provider, expected_buttons in cases:
            window = self.make(provider, wait=None if name == "읽는 중" else True)
            if name == "읽는 중":
                window.reload()
                self.settle()
            shown = []
            for widget in window.screen_widget.findChildren(QWidget):
                if isinstance(widget, (QLabel, QAbstractButton)):
                    shown.append(widget.text() if not isinstance(widget, UI.Label) else widget.plain_text())
                shown += [widget.accessibleName(), widget.toolTip()]
            flat = " | ".join(item for item in shown if item)
            for word in banned:
                self.assertNotIn(word, flat, f"{name}: {word}")
            names = {b.accessibleName() for b in window.screen_widget.findChildren(QAbstractButton)}
            self.assertEqual(names, expected_buttons, name)
            self.assertLessEqual(names, allowed, name)
            if name == "읽는 중":
                window.cancel_load()
                ui_offscreen.wait_until(self.app, lambda current=window: not current.state.loading, 5)
        for gone in ("SummaryCard", "TopicRow", "QuickAction"):                                    # 옛 부품은 코드에도 없다
            self.assertFalse(hasattr(UI, gone), gone)
        for gone in ("ResponsiveBody", "chip_flow", "_rail"):
            self.assertFalse(hasattr(S, gone), gone)

    def test_pressing_a_row_opens_the_drawer_and_never_navigates_anywhere(self):
        """의도적 교체(UI-C1d, D-201): 옛 시험은 빠른 작업 하나가 안내만 하고 화면을 안 바꾸는 것을 봤다(빠른 작업이 없어졌다). 새 홈의 누르는 곳(추천 줄)은 **기존 상세 서랍을 열 뿐** 어떤 화면으로도 가지 않는다 —
        점수가 없는 줄도 같다."""
        window = self.make()
        rows = window.screen_widget.findChildren(board_module.BoardRow)
        for index in (0, 4, 8):
            row = window.screen_widget.findChildren(board_module.BoardRow)[index]
            QTest.mouseClick(row, Qt.LeftButton)
            self.settle()
            self.assertEqual((window.state.page, window.state.drawer_id), ("home", rows[index].row["id"]), index)
            self.assertTrue(window.drawer.is_open)
            self.assertTrue(window.nav_buttons["home"].isChecked())
            window.close_drawer()
            self.settle()

    def test_source_credit_copies_two_lines_and_says_copied(self):
        window = self.make()
        credit = attribution.PhotoCredit("샘플 작가", "https://unsplash.com/photos/abc", "https://unsplash.com/@sample")
        window.copy_credit(credit)
        self.assertEqual(len(self.clipboard), 1)
        lines = self.clipboard[0].split("\n")
        self.assertEqual(lines[0], "Photo by 샘플 작가 on Unsplash")
        self.assertEqual(lines[1], "https://unsplash.com/photos/abc?utm_source=chanceblog_desktop&utm_medium=referral")
        self.assertEqual(window.toast.text(), "출처 복사됨")

    def test_a_clipboard_that_fails_only_says_so(self):
        window = shell_module.AppShell(services.FakeHomeProvider(), autoload=False, clipboard=lambda text_: 1 / 0)
        self.addCleanup(window.close)
        window.copy_credit(attribution.PhotoCredit("작가", "https://unsplash.com/photos/a", "https://unsplash.com/@a"))
        self.assertEqual(window.toast.text(), text.T["credit_failed"])

    def test_the_attribution_part_links_only_to_unsplash_and_copies_through_its_button(self):
        opened, copied = [], []
        credit = attribution.PhotoCredit("샘플 작가", "https://unsplash.com/photos/abc", "https://unsplash.com/@sample")
        row = UI.AttributionRow(credit, copied.append, opener=opened.append)
        row.show()
        self.addCleanup(row.close)
        self.assertIn("utm_source=chanceblog_desktop", row.credit_label.text())
        self.assertIn("@sample", row.credit_label.text())
        row.open_link("https://evil.example/x")
        row.open_link("javascript:alert(1)")
        self.assertEqual(opened, [])
        row.open_link("https://unsplash.com/@sample?utm_source=chanceblog_desktop&utm_medium=referral")
        self.assertEqual(len(opened), 1)
        QTest.mouseClick(row.button, Qt.LeftButton)
        self.assertEqual(copied[0].split("\n")[0], "Photo by 샘플 작가 on Unsplash")
        self.assertEqual(row.button.accessibleName(), text.T["credit_copy_a11y"])


class StatesTest(QtBase):
    def test_loading_shows_a_skeleton_a_cancel_button_and_disables_refresh(self):
        """의도적 갱신(UI-C1d, D-201): 추천 행이 없어 `BoardRow` 가 하나도 없음을 본다. 읽는 중에도 KPI 는 그대로 있고(`집계 전` — 0 이 아니다) 구역 대신 자리 표시 하나와 취소 단추가 있다."""
        window = self.make(services.FakeHomeProvider(delay=2), wait=None)
        window.reload()
        self.settle()
        self.assertEqual(window.state.list_state, "loading")
        self.assertIsNotNone(window.screen_widget.findChild(QWidget, "skel"))
        self.assertEqual(window.screen_widget.findChild(board_module.BoardRow), None)
        self.assertEqual([card.kpi["text"] for card in window.screen_widget.findChildren(board_module.KpiCard)], ["집계 전"] * 4)
        self.assertIsNotNone(window.cancel_button)
        self.assertFalse(window.refresh_button.isEnabled())
        window.cancel_load()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 5))
        self.assertIn("취소", window.toast.text())

    def test_cancelling_a_load_that_cannot_be_stopped_frees_the_screen_at_once_and_discards_the_late_result(self):
        """서비스 호출 하나는 도중에 끊을 수 없다(검증 M-6 — 2.7초) — 취소를 누르면 화면은 곧바로 풀리고, 늦게 끝난 결과는 버려진다."""
        release = threading.Event()

        class Stubborn(services.HomeProvider):
            def load_home(self, progress, cancelled):
                release.wait(5)                                                          # 취소를 보지 않는다 — 끝나면 취소를 알아차리지 못한 채 결과를 돌려준다(예시 공급자는 시작할 때 취소를 보고 멈추므로 쓰지 않는다)
                return services.HomeData(topics=services.sample_topics(3), sample=False)

        window = self.make(Stubborn(), wait=None)
        self.assertTrue(window.reload())
        self.assertEqual(window.state.list_state, "loading")
        started = time.perf_counter()
        window.cancel_load()
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertNotEqual(window.state.list_state, "loading")                         # 일은 아직 도는데 화면은 이미 풀렸다
        self.assertTrue(window.state.loading)
        self.assertIn("취소", window.toast.text())
        self.assertIsNone(window.screen_widget.findChild(QWidget, "skel"))
        self.assertFalse(window.reload())                                                # 아직 도는 일이 있으면 새로 시작하지 않고 안내만
        self.assertEqual(window.toast.text(), text.T["load_busy"])
        release.set()                                                                    # 이제 일이 끝난다 — 결과는 버려진다
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: not window.state.loading, 5))
        ui_offscreen.settle(self.app, 15, 0.03)                                          # 작업이 '끝남' 으로 바뀐 직후 결과 신호가 화면 스레드에 닿을 때까지 충분히 기다린다(그래야 버려졌는지 안다)
        self.assertIsNone(window.state.data)
        self.assertNotEqual(window.state.list_state, "normal")
        self.assertEqual(window.state.load_count, 1)
        window.state.provider = services.FakeHomeProvider()
        self.assertTrue(window.reload())                                                 # 끝난 뒤에는 다시 불러올 수 있다
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state == "normal", 5))

    def test_a_second_reload_while_loading_is_refused_with_a_notice(self):
        window = self.make(services.FakeHomeProvider(delay=1.5), wait=None)
        self.assertTrue(window.reload())
        self.assertFalse(window.reload())
        self.assertEqual(window.toast.text(), text.T["load_busy"])
        self.assertEqual(window.state.load_count, 1)
        window.cancel_load()
        ui_offscreen.wait_until(self.app, lambda: not window.state.loading, 5)

    def test_the_empty_state_is_a_normal_state_without_any_button_that_writes(self):
        """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 `test_the_empty_state_has_a_next_step_button_that_does_not_pretend` 는 빈 상태의 `주제 분석 시작` 단추가 안내만 하는 것을 봤다.
        그 단추(쓰기)를 없앴다 — 빈 상태는 정상 상태이고 구역마다 자기 말을 하며 단추는 `예시 데이터`·`다시 불러오기` 뿐이다."""
        window = self.make(services.FakeHomeProvider("empty"))
        self.assertEqual(window.state.list_state, "empty")
        names = {b.accessibleName() for b in window.screen_widget.findChildren(QAbstractButton)}
        self.assertEqual(names, {"예시 데이터", text.T["refresh"]})
        shown = " | ".join(label.plain_text() for label in window.screen_widget.findChildren(UI.Label))
        self.assertEqual(shown.count("아직 추천할 후보가 없어요."), 2)                      # Naver A·B 추천이 각자
        self.assertIn("작성 중인 초안이 없어요.", shown)
        self.assertIn("아직 발행한 글이 없어요.", shown)
        self.assertEqual(len(window.screen_widget.findChildren(board_module.BoardRow)), 0)
        self.assertEqual(len(window.screen_widget.findChildren(board_module.KpiCard)), 4)
        self.assertEqual([b for b in window.screen_widget.findChildren(QAbstractButton) if b.property("kind") == "primary"], [])
        self.assertIsNone(window.screen_widget.findChild(QWidget, "banner"))

    def test_the_error_state_shows_a_friendly_message_hides_the_code_and_retry_recovers(self):
        provider = Flaky(failures=1, code="NETWORK_DOWN")
        window = self.make(provider)
        self.assertEqual(window.state.list_state, "error")
        visible = " ".join(w.text() for w in window.screen_widget.findChildren(QLabel) if w.isVisible())
        self.assertIn("연결이 끊겼어요.", visible)
        self.assertNotIn("NETWORK_DOWN", visible)                                         # 영문 코드는 기본 화면에 없다
        self.assertNotRegex(visible, r"Traceback|Exception")
        diag = window.screen_widget.findChild(UI.Disclosure)
        self.assertFalse(diag.body.isVisible())
        QTest.mouseClick(diag.toggle, Qt.LeftButton)
        self.settle()
        self.assertTrue(diag.body.isVisible())
        self.assertIn("NETWORK_DOWN", diag.body.plain_text())
        self.assertTrue(diag.body.property("mono"))
        self.assertEqual(diag.body.font().family(), theme.fixed_font().family())          # 진단 정보는 고정폭 글꼴
        retry = next(b for b in window.screen_widget.findChildren(QAbstractButton) if b.text() == text.T["retry"])
        QTest.mouseClick(retry, Qt.LeftButton)
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state == "normal", 5))
        self.assertEqual(len(window.screen_widget.findChildren(board_module.BoardRow)), 9)                   # (UI-C1d: 옛 추천 행 5 → 새 추천 줄 9)
        self.assertEqual(provider.calls, 2)

    def test_a_failure_after_data_keeps_the_old_data_in_the_state(self):
        window = self.make()
        before = window.state.data
        window.provider_failed = None
        window.state.provider = Flaky(failures=1)
        window.reload()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state == "error", 5))
        self.assertIs(window.state.data, before)

    def test_partial_and_offline_banners_and_hidden_trends(self):
        partial = self.make(services.FakeHomeProvider("partial"))
        self.assertEqual(partial.state.list_state, "partial")
        banners = [w for w in partial.screen_widget.findChildren(QWidget, "banner")]
        self.assertEqual(len(banners), 1)
        self.assertIn(text.T["partial"], banners[0].accessibleName())
        rows = partial.screen_widget.findChildren(board_module.BoardRow)
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(row.row["interest"]["key"] == "none" for row in rows))                          # (UI-C1d: 옛 추세 칸 → 추천 줄의 관심도) 못 가져온 지표는 `관심도 데이터 부족`
        self.assertTrue(all(row.interest.text_label.text() == "관심도 데이터 부족" for row in rows))
        offline = self.make(services.FakeHomeProvider("offline"))
        self.assertIn(text.T["offline"], offline.screen_widget.findChild(QWidget, "banner").accessibleName())

    def test_the_window_stays_responsive_while_a_slow_load_runs_in_the_thread(self):
        """작업 스레드면 화면 스레드가 멈추지 않는다(시제품 실측: 스레드 최대 38ms, 직접 기다리면 1,231ms) — 1.2초짜리 불러오기 동안 5ms 타이머가 끊기지 않는다."""
        window = self.make(services.FakeHomeProvider(delay=1.2), wait=None)
        gaps, last = [], [time.perf_counter()]

        def tick():
            now = time.perf_counter()
            gaps.append(now - last[0])
            last[0] = now

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(5)
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        timer.stop()
        self.assertGreater(len(gaps), 50)
        type(self).measured_thread_max_gap = max(gaps)
        self.assertLess(max(gaps), 0.6, f"화면이 {max(gaps) * 1000:.0f}ms 멈췄다")                     # 일 시간(1.2초)의 절반 미만 — 끝날 때 화면을 다시 그리는 시간(약 0.15초)이 들어 있다
        self.assertEqual(window.state.list_state, "normal")

    def test_a_blocking_wait_on_the_screen_thread_would_freeze_it_so_the_measure_is_meaningful(self):
        gaps, last = [], [time.perf_counter()]

        def tick():
            now = time.perf_counter()
            gaps.append(now - last[0])
            last[0] = now
            if len(gaps) == 5:
                time.sleep(0.4)                                                          # 화면 스레드에서 직접 기다리면

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(5)
        ui_offscreen.wait_until(self.app, lambda: len(gaps) >= 12, 5)
        timer.stop()
        self.assertGreaterEqual(max(gaps), 0.4)

    def test_results_are_delivered_on_the_screen_thread(self):
        window = self.make(wait=None)
        seen = []
        original = window._on_loaded
        window.bridge.loaded.disconnect(window._on_loaded)
        window.bridge.loaded.connect(lambda data: (seen.append(threading.current_thread() is threading.main_thread()), original(data)))
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 5)
        self.assertEqual(seen, [True])

    def test_closing_the_window_cancels_a_running_load(self):
        window = self.make(services.FakeHomeProvider(delay=5), wait=None)
        window.reload()
        self.assertTrue(window.state.loading)
        window.close()
        self.assertFalse(window.state.runner.running())

    def test_the_window_disappears_at_once_even_when_a_job_cannot_be_stopped_quickly(self):
        """취소를 안 보는 작업을 기다리는 동안(최대 1초) 창이 멈춘 채 떠 있지 않게 — 창을 먼저 숨기고 기다린다."""
        release = threading.Event()

        class Stubborn(services.HomeProvider):
            def load_home(self, progress, cancelled):
                release.wait(5)                                                          # 취소를 보지 않는다
                return services.FakeHomeProvider().load_home(progress, cancelled)

        window = self.make(Stubborn(), wait=None)
        window.reload()
        self.assertTrue(window.state.loading)
        seen, original = [], window.state.runner.join_all
        window.state.runner.join_all = lambda timeout=2.0: (seen.append((window.isVisible(), timeout)), release.set(), original(timeout))[2]
        window.close()
        self.assertEqual(seen, [(False, 1.0)])                                           # 기다릴 때는 이미 숨은 뒤, 기다림은 최대 1초

    def test_data_that_breaks_the_screen_ends_in_an_error_state_not_a_forever_loading_page(self):
        """의도적 갱신(UI-C1d, D-201): 옛 추천 행(`TopicRow` 5개)을 새 추천 줄(`BoardRow` 9개)로 센다 — 이상한 데이터가 슬롯에서 예외를 내도 오류 상태가 되고 다시 불러오면 회복한다는 단언은 그대로다. 화면 스레드의 슬롯 안에서 예외가 나면(이상한 데이터) 예전에는 오류 화면 없이 '불러오는 중' 에 멈췄다(검증 M-6)."""
        class Broken(services.HomeProvider):
            def load_home(self, progress, cancelled):
                return services.HomeData(topics=("주제가 아닌 값",), blogs=(), sample=False)

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            window = self.make(Broken())
        self.assertEqual(window.state.list_state, "error")
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)                    # 원인은 표준 오류에 한 줄로 남는다(조용한 실패 아님) — 추적·경로 없음
        self.assertIn("(AttributeError)", err.getvalue())
        self.assertNotRegex(err.getvalue(), r"Traceback|File \"")
        self.assertIsNone(window.screen_widget.findChild(QWidget, "skel"))                # 스켈레톤(불러오는 중)이 아니다
        visible = " ".join(w.text() for w in window.screen_widget.findChildren(QLabel) if w.isVisible())
        self.assertIn(text.T["job_failed"], visible)
        self.assertNotRegex(visible, r"Traceback|AttributeError|주제가 아닌")
        diag = window.screen_widget.findChild(UI.Disclosure)
        self.assertIn("AttributeError", diag.body.plain_text())                           # 진단 정보에는 예외 이름만
        self.assertNotIn("주제가 아닌", diag.body.plain_text())
        self.assertFalse(window.state.loading)
        window.state.provider = services.FakeHomeProvider()                              # 고쳐진 뒤 다시 불러오면 회복한다
        self.assertTrue(window.reload())
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state == "normal", 5))
        self.assertEqual(len(window.screen_widget.findChildren(board_module.BoardRow)), 9)                   # (UI-C1d: 옛 추천 행 5 → 새 추천 줄 9)

    def test_a_crash_in_each_result_slot_is_caught_and_the_screen_is_never_left_loading(self):
        window = self.make()
        err = io.StringIO()
        for slot, args in ((window._on_loaded, ("이상한 값",)), (window._on_failed, (None,)), (window._on_cancelled, ())):
            with mock.patch.object(window.state, "apply_home", side_effect=RuntimeError("속 사정")), mock.patch.object(window.state, "apply_failure", side_effect=RuntimeError("속 사정")), \
                    mock.patch.object(window.state, "apply_cancelled", side_effect=RuntimeError("속 사정")), contextlib.redirect_stderr(err):
                slot(*args)
            self.assertEqual(window.state.list_state, "error", slot.__name__)
            self.assertEqual(window.state.failure.code, "RuntimeError")
            self.assertNotIn("속 사정", repr(window.state.home_view()))
            window.state.apply_home(services.FakeHomeProvider().load_home(lambda *a: None, lambda: False))
            window.render()
        self.assertEqual(err.getvalue().count("(RuntimeError)"), 3)                       # 슬롯마다 원인 한 줄이 표준 오류에 남는다
        self.assertEqual(len(err.getvalue().strip().splitlines()), 3)

    def test_when_even_the_error_screen_cannot_be_drawn_only_a_notice_is_shown(self):
        window = self.make()
        err = io.StringIO()
        with mock.patch.object(window, "render", side_effect=RuntimeError("그리기 실패")), contextlib.redirect_stderr(err):
            window._on_loaded(None)
        self.assertEqual(window.toast.text(), text.T["job_failed"])
        self.assertEqual(window.state.list_state, "error")
        self.assertIn("(RuntimeError): 그리기 실패", err.getvalue())

    def test_the_global_exception_hook_prints_one_masked_line_and_shows_a_gentle_notice(self):
        window = self.make()
        stream = io.StringIO()
        hook = qapp.make_excepthook(window, stream)
        try:
            raise ValueError(f"열 수 없음 C:\\Users\\홍길동\\비밀.txt 키 {FAKE_KEY}")
        except ValueError:
            hook(*sys.exc_info())
        line = stream.getvalue()
        self.assertEqual(len(line.strip().splitlines()), 1)
        self.assertIn("(ValueError)", line)
        for piece in (FAKE_KEY, FAKE_KEY[:12], "홍길동", "비밀.txt", "Traceback", "File \""):
            self.assertNotIn(piece, line)
        self.assertEqual(window.toast.text(), text.T["job_failed"])
        qapp.make_excepthook(None, object())(ValueError, ValueError("x"), None)          # 훅 안의 오류(쓸 수 없는 표준 오류)는 다시 내지 않는다
        window.close()
        hook(RuntimeError, RuntimeError("창이 이미 닫힘"), None)                              # 닫힌 창에 안내를 못 보여도 조용히 넘어간다
        with mock.patch.object(sys, "__excepthook__") as passed:
            qapp.make_excepthook(window, stream)(KeyboardInterrupt, KeyboardInterrupt(), None)
        passed.assert_called_once()                                                       # Ctrl+C 는 그대로 둔다

    def test_the_real_entry_installs_the_hook_after_the_window_exists(self):
        windows = []
        with mock.patch.object(qapp.QApplication, "exec", return_value=7), mock.patch.object(sys, "excepthook", sys.excepthook):
            code = qapp.run(services.FakeHomeProvider(), argv=["t"])
            installed = sys.excepthook
        self.assertEqual(code, 7)
        self.assertEqual(installed.__name__, "hook")
        self.assertIsNot(installed, sys.__excepthook__)
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, shell_module.AppShell):
                windows.append(widget)
        for window in windows:
            window.close()

    def test_the_real_run_path_prints_one_clean_line_for_a_slot_error_with_a_path_with_spaces(self):
        """진짜 `run()` 으로(이벤트 루프만 가짜) — 타이머 슬롯에서 난 예외가 설치된 훅을 거쳐 표준 오류에 한 줄로 나가고, 공백이 든 경로는 통째로 지워진다(독립 검증 N-1 — `(경로) Doe/Documents/x.db`)."""
        err = io.StringIO()

        def fake_exec(*_):
            def boom():
                raise OSError("열 수 없음 'C:\\\\Users\\\\Jane Doe\\\\Documents\\\\x.db' (접근 거부)")

            QTimer.singleShot(0, boom)
            ui_offscreen.settle(self.app, 6)
            return 0

        with mock.patch.object(qapp.QApplication, "exec", fake_exec), mock.patch.object(sys, "excepthook", sys.excepthook), contextlib.redirect_stderr(err):
            self.assertEqual(qapp.run(services.FakeHomeProvider(), argv=["t"]), 0)
        self.assertEqual(err.getvalue().strip().splitlines(), [f"{text.T['unexpected_line']} (OSError): 열 수 없음 '(경로)' (접근 거부)"])
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, shell_module.AppShell):
                widget.close()

    def test_a_late_cancel_signal_after_the_screen_was_already_freed_shows_nothing_again(self):
        """취소를 누르면 화면이 바로 풀리고 안내가 한 번 뜬다. 끊을 수 없던 일이 몇 초 뒤 끝나며 보내는 취소 신호가 같은 안내와 다시 그리기를 또 부르던 것(독립 검증 N-3 — 5초 일은 5초 뒤에 안내가 다시 떴다)."""
        gates, fail_next = [], []

        class Stubborn(services.HomeProvider):
            def load_home(self, progress, cancelled):
                gate = threading.Event()
                gates.append(gate)
                gate.wait(8)                                                             # 취소를 보지 않는다
                if fail_next:
                    raise JobFailure("늦은 실패", code="LATE_FAILURE")
                return services.HomeData(topics=services.sample_topics(3), sample=False)

        window = self.make(Stubborn(), wait=None)
        notices, renders = [], []
        notify, render = window.notify, window.render
        window.notify = lambda message: (notices.append(message), notify(message))[1]
        window.render = lambda: (renders.append(1), render())[1]

        def cancelled_notices():
            return notices.count(text.T["load_cancelled"])

        def finish_the_job():
            gates[-1].set()
            self.assertTrue(ui_offscreen.wait_until(self.app, lambda: not window.state.loading, 8))
            ui_offscreen.settle(self.app, 15, 0.03)                                      # 끝 신호가 화면 스레드에 닿을 때까지 충분히

        for cycle in (1, 2):                                                             # 두 번째에도 취소가 보인다(첫 취소가 귀를 막아 두지 않는다)
            self.assertTrue(window.reload(), cycle)
            window.cancel_load()
            self.assertEqual(cancelled_notices(), cycle)
            self.assertNotEqual(window.state.list_state, "loading")
            window.cancel_load()                                                         # 같은 일에 또 눌러도 안내·다시 그리기는 그대로
            self.assertEqual(cancelled_notices(), cycle)
            drawn = len(renders)
            finish_the_job()                                                             # 이제 일이 끝난다 — 늦은 취소 신호가 온다
            self.assertEqual(cancelled_notices(), cycle, "늦은 취소 신호가 같은 안내를 또 띄웠다")
            self.assertEqual(len(renders), drawn, "늦은 취소 신호가 화면을 다시 그렸다")
        with mock.patch.object(window.state, "cancel_load"):                             # 취소가 일에 닿지 못한 경우(일이 막 끝나던 때) — 취소 신호 대신 결과가 온다
            self.assertTrue(window.reload())
            window.cancel_load()
        self.assertEqual(cancelled_notices(), 3)
        finish_the_job()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state == "normal", 5))      # 결과가 와서 보인다
        self.assertEqual(cancelled_notices(), 3)
        self.assertTrue(window.reload())                                                 # 그 뒤 새 일에 취소를 눌러도 보인다(안 온 취소 신호를 기다리며 막혀 있지 않다)
        window.cancel_load()
        self.assertEqual(cancelled_notices(), 4)
        finish_the_job()
        self.assertEqual(cancelled_notices(), 4)
        fail_next.append(1)                                                              # 일이 늦게 '실패' 로 끝나는 경우도 같다 — 실패 신호가 오면 기억이 지워진다
        with mock.patch.object(window.state, "cancel_load"):
            self.assertTrue(window.reload())
            window.cancel_load()
        self.assertEqual(cancelled_notices(), 5)
        finish_the_job()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state == "error", 5))
        fail_next.clear()
        self.assertTrue(window.reload())
        window.cancel_load()
        self.assertEqual(cancelled_notices(), 6)
        finish_the_job()
        self.assertEqual(cancelled_notices(), 6)

    def test_cancel_with_no_job_running_shows_no_notice_and_leaves_no_trace(self):
        """G0c(재확인 권장·변이 G30): 도는 일이 없을 때 취소를 눌러도 안내가 뜨지 않고 '취소를 눌러 풀었다' 는 기억(`_cancel_released`)이 남지 않는다 — 남으면 다음 일의 정상 취소 신호가 삼켜진다."""
        window = self.make()
        self.assertFalse(window.state.loading)
        notices = []
        notify = window.notify
        window.notify = lambda message: (notices.append(message), notify(message))[1]
        window.cancel_load()
        self.assertFalse(window.state.loading)
        self.assertEqual(notices.count(text.T["load_cancelled"]), 0)
        self.assertFalse(window._cancel_released)

    def test_the_global_hook_and_the_slot_guard_survive_having_no_standard_error(self):
        """pythonw·창 없는 exe 처럼 `sys.stderr` 가 None 이어도 훅·슬롯 보호는 예외 없이 쉬운 안내와 오류 상태로 끝난다(독립 검증 N-2)."""
        window = self.make()
        out = io.StringIO()
        with mock.patch.object(sys, "stderr", None), contextlib.redirect_stdout(out):
            try:
                raise ValueError("C:\\Users\\Jane Doe\\x.db")
            except ValueError:
                qapp.make_excepthook(window)(*sys.exc_info())
            self.assertEqual(window.toast.text(), text.T["job_failed"])
            window._on_loaded("이상한 값")
        self.assertEqual(window.state.list_state, "error")
        self.assertEqual(out.getvalue(), "")                                             # 표준 출력으로 새지도 않는다

    def test_the_global_hook_erases_a_path_with_spaces_whole(self):
        window = self.make()
        stream = io.StringIO()
        try:
            raise OSError(f"열 수 없음 'C:\\\\Users\\\\Jane Doe\\\\비밀 노트.txt' 키 {FAKE_KEY}")
        except OSError:
            qapp.make_excepthook(window, stream)(*sys.exc_info())
        line = stream.getvalue()
        self.assertEqual(line.strip().splitlines(), [f"{text.T['unexpected_line']} (OSError): 열 수 없음 '(경로)' 키 [가림: Google API 키]"])


class SafetyTest(QtBase):
    def test_titles_and_text_with_html_are_shown_as_plain_text(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 옛 추천 행의 제목을 봤다 — 새 홈에서 후보의 글이 나가는 곳(추천 줄 제목·글 줄 제목·구역 머리의 채널 이름)과 기존 서랍(옛 후보의 이유)을 모두 본다."""
        evil_title = "<b>굵게</b><script>alert(1)</script>"
        old = services.Topic(id="x1", title="<b>옛</b>", blogs=("A",), desc="<img src=x onerror=alert(1)>", keywords=("<i>키</i>",), priority="높음", date="2026-11-01", reason="<a href='javascript:alert(1)'>눌러</a>")
        board = services.BoardData((services.ChannelRead("A", "<i>이름</i>", True, "ok", "", (services.RecommendRow("e1", evil_title, 85, None, "rising"),)), services.ChannelRead("B", "비", True, "ok", "", ())),
                                   services.ListRead("ok", (services.DraftRow("d1", "<u>초안</u>", "review", ""),)), services.ListRead("ok", (services.RecentRow("p1", "<h1>발행</h1>", None),)))
        window = self.make(Custom([old], board=board))
        row = window.screen_widget.findChild(board_module.BoardRow)
        self.assertEqual(row.title_label.plain_text(), evil_title)
        self.assertNotIn("<script", row.title_label.text())                               # 화면에는 이스케이프된 글자로 들어간다
        self.assertIn("&lt;script&gt;", row.title_label.text())
        for list_row, raw in zip(window.screen_widget.findChildren(board_module.ListRow), ("<u>초안</u>", "<h1>발행</h1>"), strict=True):
            self.assertEqual(list_row.title_label.plain_text(), raw)
            self.assertNotIn("<u>", list_row.title_label.text())
            self.assertNotIn("<h1>", list_row.title_label.text())
        header = next(w for w in window.screen_widget.findChildren(UI.ElidedLabel) if "이름" in w.text())
        self.assertEqual(header.text(), "<i>이름</i> 추천")                                  # 머리의 이름은 한 줄 평문으로 그려진다(서식 해석 없음)
        window.open_drawer("x1")
        self.settle()
        reason = next(label for label in window.drawer.findChildren(UI.Label) if "눌러" in label.plain_text())
        self.assertNotIn("<a href", reason.text())

    def test_a_key_shaped_text_in_a_failure_is_not_kept_in_the_state_or_on_the_screen(self):
        window = self.make(Flaky(failures=9, code=f"KEY_{FAKE_KEY}", message=f"실패 {FAKE_KEY} 입니다"))
        self.assertEqual(window.state.list_state, "error")
        window.screen_widget.findChild(UI.Disclosure).flip()
        self.settle()
        everything = " ".join(w.text() for w in window.findChildren(QLabel)) + " ".join(w.accessibleName() for w in window.findChildren(QWidget)) + repr(vars(window.state.failure)) + repr(window.state.home_view())
        self.assertNotIn(FAKE_KEY, everything)
        self.assertNotIn(FAKE_KEY, window.state.failure.user_message + window.state.failure.code)

    def test_a_key_in_a_blog_name_and_in_candidate_text_never_reaches_a_widget_through_the_real_adapter(self):
        """어댑터를 거치는 시험(검증 M-1) — 블로그 이름이 마스킹 전에 잘려 키 앞 24~26자가 화면에 보였다. 화면의 모든 글자(글자·단추·툴팁·접근 이름)에 키 조각이 없다.
        의도적 갱신(UI-C1d, D-201): 옛 시험은 오른쪽 패널(내 블로그 현황)의 블로그 이름과 옛 후보 행을 봤다. 새 홈에서는 블로그 이름이 추천 구역 머리에, 후보의 글이 주제 엔진 후보 줄(과 서랍)에 나간다 — 같은 가짜 키를 거기에 넣고
        같은 모든 글자를 훑는다(옛 후보 저장소의 후보에도 넣어 홈 뷰모델에 새지 않는지 함께 본다).
        의도적 갱신(PCSEC1 M3, D-375): PCSEC1 이후 `add_candidate` 는 키·토큰 모양을 쓰기 전에 거절하므로(그 거절은 `test_secret_shape_refusal` 이 본다) 옛 후보는 보관함에 직접 넣는다 —
        `service_support.inject_candidate`(옛 버전이 저장한 것처럼). '화면 어디에도 닿지 않는다' 는 단언은 그대로이고, 후보가 실제로 들어갔다는 준비 확인 한 줄을 더했다."""
        sys.path.insert(0, str(ROOT / "tests"))
        import service_support as support
        import topics_support as ts
        from chanceblog_desktop.content.profiles import NaverProfile
        from chanceblog_desktop.service import topic_files as tf
        from chanceblog_desktop.topicdb.store import open_for_write
        from chanceblog_desktop.ui import adapters
        key = "AI" + "za" + "SyD4e7Kq9ZmW2xV8bN5tR1cY6uH3jL0pGfA1B"[:35]
        github = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"

        def leaked(everything):
            return sorted({secret[i:i + 6] for secret in (key, github) for i in range(len(secret) - 5) if secret[i:i + 6] in everything})

        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            ctx.settings.save_naver_profile(NaverProfile("naver_a", "블로그 " + key, "https://blog.naver.com/exampleaaa", default_tags=("생활",), min_chars=10, max_chars=20000))
            ctx.settings.save_naver_profile(NaverProfile("naver_b", "블로그 비 " + github, "https://blog.naver.com/examplebbb", default_tags=("정보",), min_chars=10, max_chars=20000))
            support.inject_candidate(ctx, topic="옛 제목 " + key, keyword="키워드 " + github, blogs=("naver_a", "naver_b"), sub_keywords=("보조 " + key,), reason="이유 " + key + " " + github)         # 옛 버전이 저장한 것처럼 보관함에 직접 — PCSEC1 이후 `add_candidate` 는 키·토큰 모양을 쓰기 전에 거절한다
            with ctx.store() as legacy:
                self.assertEqual(len(legacy.list_candidates()), 1, "옛 후보 저장소에 키 모양이 든 후보가 실제로 들어 있다 — 준비가 비면 아래의 '새지 않는다' 단언이 아무것도 보지 못한다")
            with open_for_write(tf.topic_paths(ctx.workspace).database) as store:
                store.add_candidates(lambda existing: [ts.rated(90, channel="naver_a", candidate_id="tc-naver_a-seed-aaaa000000000001", topic="제목 " + key),
                                                       ts.rated(80, channel="naver_b", candidate_id="tc-naver_b-seed-bbbb000000000002", topic="제목 비 " + github)], now="2026-11-10T01:00:00Z")
            for size in ((1920, 1080), (1366, 768)):
                window = self.make(adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx), size=size)
                rows = window.screen_widget.findChildren(board_module.BoardRow)
                self.assertEqual(len(rows), 2, size)
                self.assertNotIn("sample", repr(window.state.home_view()["board"]["state"]))
                window.open_drawer(rows[0].row["id"])
                self.settle()
                everything = " ".join(w.text() for w in window.findChildren(QLabel)) + " ".join(w.accessibleName() + w.toolTip() for w in window.findChildren(QWidget)) + " ".join(w.text() for w in window.findChildren(QAbstractButton))
                everything += repr(window.state.home_view()) + repr(window.state.drawer_view())
                self.assertEqual(leaked(everything), [], size)
                self.assertIn("가림", everything)
                self.assertIn("블로그 [가림", " ".join(w.text() for w in window.findChildren(QLabel)))        # 구역 머리의 블로그 이름: 앞부분은 보이고 키는 가려졌다
                self.assertNotIn("옛 제목", everything)                                                      # 옛 후보 저장소의 글은 홈에도 서랍에도 나오지 않는다
                window.close()

    def test_a_forty_character_blog_name_shows_and_tooltips_the_thirty_character_text_the_adapter_made(self):
        """툴팁은 '전체' 가 아니라 받은 글이다 — 어댑터가 가린 뒤 30자로 줄인 글(독립 검증 N-5). 40자 이름은 라벨도 툴팁도 29자 + …
        의도적 갱신(UI-C1d, D-201): 이름이 보이는 자리가 오른쪽 패널에서 추천 구역 머리(`이름 추천`)로 옮겨 글에 ` 추천` 이 붙는다."""
        sys.path.insert(0, str(ROOT / "tests"))
        import service_support as support
        from chanceblog_desktop.content.profiles import NaverProfile
        from chanceblog_desktop.ui import adapters
        name = "가나다라마바사아자차" * 4
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            ctx.settings.save_naver_profile(NaverProfile("naver_a", name, "https://blog.naver.com/exampleaaa", default_tags=("생활",), min_chars=10, max_chars=20000))
            window = self.make(adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx))
            labels = [w for w in window.screen_widget.findChildren(UI.ElidedLabel) if w.text().startswith("가나다라")]
            self.assertEqual(len(labels), 1)
            expected = name[:adapters.NAME_LIMIT - 1] + "…"
            self.assertEqual((labels[0].text(), labels[0].toolTip()), (expected + " 추천", expected + " 추천"))
            self.assertEqual(len(labels[0].toolTip()), adapters.NAME_LIMIT + len(" 추천"))
            self.assertNotIn(name[:adapters.NAME_LIMIT + 1], labels[0].toolTip())
            window.close()

    def test_visible_texts_never_contain_english_codes_internal_ids_or_promises(self):
        """의도적 갱신(UI-C1d, D-201): 옛 후보 번호(`s1`)에 더해 추천 줄 번호(예시 `rA1`)도 어떤 글에도 나가지 않는다 — 서랍을 연 상태에서 홈과 서랍의 모든 글을 훑는다."""
        window = self.make()
        window.open_drawer(first_row_id(window))
        self.settle()
        for label in window.findChildren(QLabel):
            shown = label.text() if not isinstance(label, UI.Label) else label.plain_text()
            self.assertNotRegex(shown, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", shown)
            self.assertNotRegex(shown, r"\b(?:s\d+|r[AB]\d)\b")
            for word in text.FORBIDDEN:
                self.assertNotIn(word, shown)
        for widget in window.findChildren(QWidget):                                      # 접근 이름·툴팁에도 번호가 없다
            for shown in (widget.accessibleName(), widget.toolTip()):
                self.assertNotRegex(shown, r"\b(?:s\d+|r[AB]\d)\b", shown)

    def test_the_numbers_and_names_of_the_old_side_panel_are_not_shown_any_more(self):
        """의도적 교체(UI-C1d, D-201): 옛 `test_blog_numbers_that_could_not_be_read_are_not_shown_at_all` 은 오른쪽 패널의 총 글·이번 달(못 읽은 값은 아예 안 보임)을 봤다. 그 패널(내 블로그 현황)이 없어졌다 —
        블로그 정보(`BlogInfo`)의 이름·수는 어느 값이든 홈에 나오지 않는다."""
        window = self.make(Custom([services.Topic(id="b1", title="주제", blogs=("A",), date="2026-11-01")], blogs=(services.BlogInfo("A", "블로그 에이", "생활", 64, 6, 3),)))
        shown = " | ".join(label.plain_text() for label in window.screen_widget.findChildren(UI.Label)) + " | " + " | ".join(w.text() for w in window.screen_widget.findChildren(UI.ElidedLabel))
        for piece in ("내 블로그 현황", "총 글", "이번 달", "후보  3", "블로그 에이", "생활", "64", "관리 중인 블로그"):
            self.assertNotIn(piece, shown, piece)

    def test_a_real_looking_row_without_numbers_shows_no_invented_values(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 숫자가 없는 옛 후보 행이 `데이터 없음` 세 칸(검색량·문서 수·추세)을 보이는 것을 봤다. 새 추천 줄에서 같은 질문 — 점수·관심도·이전 점수가 없는 줄은 링 없이 `점수 계산 전`,
        `관심도 데이터 부족` 이고 0 이나 지어낸 값이 없다(예시가 아니니 `예시` 표시도 없다)."""
        bare = services.RecommendRow("b1", "숫자가 없는 주제", None, None, None, False)
        board = services.BoardData((services.ChannelRead("A", "에이", True, "ok", "", (bare,)), services.ChannelRead("B", "비", True, "ok", "", ())), services.ListRead(), services.ListRead())
        window = self.make(Custom([], board=board))
        row = window.screen_widget.findChild(board_module.BoardRow)
        shown = [label.plain_text() for label in row.findChildren(UI.Label)]
        self.assertIn("점수 계산 전", shown)
        self.assertIn("관심도 데이터 부족", shown)
        self.assertEqual(row.findChildren(gauge_module.ScoreRing), [])                     # 0점 링을 그리지 않는다
        self.assertFalse(any(character.isdigit() for item in shown for character in item.replace("숫자가 없는 주제", "")), shown)      # 지어낸 숫자가 없다
        self.assertIsNone(row.sample_badge)
        self.assertFalse(window.screen_widget.findChild(QWidget, "banner"))
        self.assertFalse(any(b.accessibleName() == "예시 데이터" for b in window.findChildren(QAbstractButton)))     # 가짜 데이터가 아니면 예시 표시도 없다


class ComponentsTest(QtBase):
    def column(self, window, *widgets):
        """위젯들을 세로 배치에 넣어 보이게 한다 — 배치가 있어야 단추가 자기 최소 높이를 받는다."""
        box = QWidget(window.centralWidget())
        layout = QVBoxLayout(box)
        for widget in widgets:
            layout.addWidget(widget)
        box.show()
        self.settle(3)
        return box

    def test_the_toggle_works_with_space_has_a_name_and_a_big_target_and_paints(self):
        window = self.make()
        toggle = UI.Toggle("알림 받기")
        self.column(window, toggle)
        self.focus(toggle)
        self.assertEqual(toggle.accessibleName(), "알림 받기")
        self.assertGreaterEqual(toggle.sizeHint().height(), tokens.SIZE["hit"])
        self.assertGreaterEqual(toggle.sizeHint().width(), tokens.SIZE["toggle_w"])
        off = toggle.grab().toImage()
        QTest.keyClick(toggle, Qt.Key_Space)
        self.assertTrue(toggle.isChecked())
        self.assertNotEqual(toggle.grab().toImage(), off)                                  # 켜지면 모양이 바뀐다(포커스 링도 그려진다)
        QTest.keyClick(toggle, Qt.Key_Space)
        self.assertFalse(toggle.isChecked())
        toggle.setEnabled(False)
        self.assertFalse(toggle.grab().isNull())

    def test_the_text_input_has_a_name_a_placeholder_and_a_40px_height_and_takes_typing(self):
        window = self.make()
        box = UI.TextInput("제목 입력", "여기에 적어요")
        self.column(window, box)
        self.focus(box)
        self.assertEqual((box.accessibleName(), box.placeholderText()), ("제목 입력", "여기에 적어요"))
        self.assertGreaterEqual(box.height(), tokens.SIZE["input_h"])
        QTest.keyClicks(box, "abc")
        self.assertEqual(box.text(), "abc")

    def test_the_four_button_kinds_get_their_token_colors_and_heights(self):
        window = self.make()
        colors = tokens.palette()
        found = {}
        buttons = {kind: UI.Button(kind, "단추") for kind in ("primary", "secondary", "ghost", "danger")}
        self.column(window, *buttons.values())
        for kind, button in buttons.items():
            self.assertTrue(40 <= button.height() <= 48, kind)
            image = button.grab().toImage()
            found[kind] = image.pixelColor(8, image.height() // 2).name().upper()
        self.assertEqual(found["primary"], colors["primary"].upper())
        self.assertEqual(found["danger"], colors["danger_fill"].upper())             # 의도적 갱신(UI-C1a, D-170): 위험 단추 배경은 접근성 색 `danger_fill`(#CE4646) — 운영자 2026-11-06 확인 요청 004 의 답
        self.assertEqual(found["secondary"], colors["surface"].upper())
        self.assertEqual(len(set(found.values())), 4 - (1 if found["ghost"] in (found["secondary"], found["primary"], found["danger"]) else 0))
        large = UI.Button("primary", "큰 단추", size="lg")
        small = UI.Button("secondary", "작은 단추", size="sm")
        self.column(window, large, small)
        self.assertEqual(large.height(), tokens.SIZE["control_primary"])
        self.assertEqual(small.height(), tokens.SIZE["hit"])                                 # 보이는 높이 34, 누르는 칸 36
        small.setEnabled(False)
        self.settle(2)
        self.assertEqual(small.grab().toImage().pixelColor(8, 18).name().upper(), colors["disabled_bg"].upper())

    def test_every_kind_of_button_draws_a_focus_ring_in_the_agreed_color_when_it_has_the_keyboard_focus(self):
        """공통 포커스 링 규칙을 지워도 시험이 통과했다(검증 Q17) — 단추 종류마다 포커스 전후의 모양이 다르고 위쪽 테두리 한가운데가 정해진 색인지 본다."""
        window = self.make()
        colors = tokens.palette()
        buttons = {"secondary": UI.Button("secondary", "보조 단추"), "ghost": UI.Button("ghost", "고스트 단추", "arrow_right"), "icon": UI.IconButton("settings", "설정"), "link": UI.LinkButton("링크 단추"),
                   "primary": UI.Button("primary", "주 단추"), "danger": UI.Button("danger", "위험 단추"), "chip": UI.FilterChip("칩", 3, False), "chip_on": UI.FilterChip("칩", 3, True),
                   "nav": UI.NavButton("메뉴", "home", "메뉴로 이동"), "badge": UI.SampleBadge()}
        self.column(window, *buttons.values())
        dark_ring = colors["inverse_bg"].upper()                                         # 파란 바탕 위의 단추(주·위험·켜진 칩)는 어두운 링
        for name, button in buttons.items():
            window.setFocus()
            self.settle(2)
            before = button.grab().toImage()
            self.focus(button)
            after = button.grab().toImage()
            self.assertNotEqual(before, after, f"{name}: 포커스가 와도 모양이 같다(링 없음)")
            expected = dark_ring if name in ("primary", "danger", "chip_on") else colors["border_focus"].upper()
            top = lambda image: [image.pixelColor(image.width() // 2, y).name().upper() for y in range(4)]       # noqa: E731  (칩은 위 여백 1px 이 있어 테두리가 한 줄 아래에서 시작한다)
            self.assertIn(expected, top(after), name)
            self.assertNotIn(expected, top(before), name)                                    # 포커스가 없을 때는 이 색의 테두리가 없다

    def test_a_key_shaped_text_in_a_candidate_never_reaches_a_widget(self):
        topic = services.Topic(id="k1", title=f"제목 {FAKE_KEY}", desc=f"설명 {FAKE_KEY}", keywords=(FAKE_KEY,), reason=f"이유 {FAKE_KEY}", blogs=("A",), priority="높음", date="2026-11-01")
        window = self.make(Custom([topic]))
        window.open_drawer("k1")
        self.settle()
        everything = " ".join(w.text() for w in window.findChildren(QLabel)) + " ".join(w.accessibleName() + w.toolTip() for w in window.findChildren(QWidget))
        self.assertNotIn(FAKE_KEY, everything)
        self.assertIn("가림", everything)

    def test_an_elided_label_keeps_a_one_line_height_that_follows_its_font(self):
        """글꼴이 스타일시트로 정해지거나 바뀌면 한 줄 높이도 따라 달라진다 — 레이아웃이 새 높이를 받아야 큰 글자가 안 잘린다. 글이 있든 없든 같다.
        (독립 검증의 변이 N52 — `changeEvent` 의 `updateGeometry()` 를 지우는 것 — 는 동등 변이다: 부모 클래스의 `QWidget.changeEvent` 가 글꼴·스타일이 바뀔 때 어차피 `updateGeometry()` 를 부른다. 이 시험은 높이가 글꼴을 따라가야 한다는 약속 자체를 지킨다.)"""
        window = self.make()
        for shown in ("높이 시험 글", ""):
            label = UI.ElidedLabel(shown, "small")
            box = QWidget(window.centralWidget())
            layout = QVBoxLayout(box)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(label)
            layout.addStretch(1)
            box.resize(300, 300)
            box.show()
            self.settle(4)
            before = label.height()
            self.assertEqual(before, label.fontMetrics().lineSpacing() + 2, repr(shown))
            label.setStyleSheet("QLabel { font-size: 40px; }")
            self.settle(4)
            self.assertEqual(label.height(), label.fontMetrics().lineSpacing() + 2, repr(shown))
            self.assertGreater(label.height(), before)
            label.setStyleSheet("")
            self.settle(4)
            self.assertEqual(label.height(), before, repr(shown))
            label.setStyleSheet("QLabel { font-size: 8px; }")                            # 작아질 때도 따라간다(커질 때는 `minimumSizeHint` 가 받쳐 줘서 이 쪽이 `sizeHint` 를 확인한다)
            self.settle(4)
            self.assertEqual(label.height(), label.fontMetrics().lineSpacing() + 2, repr(shown))
            self.assertLess(label.height(), before)
            box.deleteLater()


class ToolsTest(QtBase):
    def test_the_clipping_check_really_catches_clipped_text_and_small_targets(self):
        """점검 도구(`scripts/ui_offscreen.find_clipping`)가 잘림을 정말 잡는지 — 일부러 칸을 좁힌 부품을 넣어 본다. 멀쩡한 화면에서는 아무것도 안 잡는다."""
        window = self.make()
        self.assertEqual(ui_offscreen.find_clipping(window), [])
        one_line = UI.Label("아주아주아주 긴 한 줄 글자입니다 " * 3, "body")
        wrapped = UI.Label("줄바꿈 글 " * 40, "body", wrap=True)
        narrow = UI.Button("secondary", "아주 긴 글자가 든 단추입니다")
        short = UI.Button("secondary", "낮은 단추")
        for widget, (width, height) in ((one_line, (60, 24)), (wrapped, (80, 20)), (narrow, (40, 40)), (short, (200, 20))):
            widget.setParent(window.centralWidget())
            widget.setFixedSize(width, height)
            widget.show()
        self.settle(3)
        found = " | ".join(ui_offscreen.find_clipping(window))
        for needle in ("한 줄 글이 칸보다 김", "줄바꿈 글이 잘림", "단추 글자가 단추보다 김", "누르는 칸이 36px 보다 낮음"):
            self.assertIn(needle, found)


class ThemeAndFontTest(QtBase):
    def test_fonts_come_from_the_system_and_only_the_size_and_weight_come_from_tokens(self):
        theme.use_font_source(None, None)                                                 # 점검용 대체를 잠깐 끄고 진짜 시스템 글꼴을 본다
        try:
            general = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
            fixed = QFontDatabase.systemFont(QFontDatabase.FixedFont)
            self.assertEqual(theme.general_font().family(), general.family())
            self.assertEqual(theme.fixed_font().family(), fixed.family())
            body = theme.font_for("body")
            self.assertEqual((body.family(), body.pixelSize(), body.weight()), (general.family(), tokens.TYPE["body"].size, QFont.Normal))
            title = theme.font_for("h1")
            self.assertEqual((title.family(), title.pixelSize(), title.weight()), (general.family(), tokens.TYPE["h1"].size, QFont.Bold))
            mono = theme.font_for("mono", fixed=True)
            self.assertEqual((mono.family(), mono.pixelSize()), (fixed.family(), tokens.TYPE["mono"].size))
        finally:
            ui_offscreen.install_system_fonts()
        self.assertEqual(self.app.font().pixelSize(), tokens.TYPE["body"].size)

    def test_the_fixed_font_is_only_used_for_the_mono_role(self):
        window = self.make()
        normal = [label for label in window.screen_widget.findChildren(UI.Label) if not label.property("mono")]
        self.assertTrue(normal)
        fixed = theme.fixed_font().family()
        self.assertTrue(all(label.font().family() != fixed for label in normal))
        sample = UI.Label("C:\\로그\\경로", "mono", mono=True)
        self.assertEqual(sample.font().family(), fixed)

    def test_the_stylesheet_is_made_of_tokens_only(self):
        colors = tokens.palette()
        qss = theme.build_qss(colors)
        self.assertNotIn("#000000", qss.upper())
        self.assertNotRegex(qss, r"font-family")                                           # 글꼴 이름을 스타일시트에 쓰지 않는다
        values = {value.upper() for value in colors.values()}
        values |= {value.upper() for preset in tokens.CHANNEL_PRESETS.values() for value in preset.values()}      # 의도적 갱신(P4b, D-210): 채널 색 프리셋(운영자가 정한 값 둘)도 토큰 파일(`tokens.CHANNEL_PRESETS`)에서 온다 — 그 밖의 색은 여전히 허용하지 않는다
        for found in set(re.findall(r"#[0-9A-Fa-f]{6}\b", qss)):
            self.assertIn(found.upper(), values, found)
        self.assertNotIn("#123456", qss)
        changed = theme.build_qss(tokens.palette(overrides={"primary": "#123456"}))
        self.assertIn("#123456", changed)
        self.assertIn("font-size: 14px", qss)

    def test_every_text_role_has_its_own_text_token_color_in_the_stylesheet(self):
        colors = tokens.palette()
        qss = theme.build_qss(colors)
        for role, key in tokens.ROLE_TEXT.items():
            self.assertRegex(qss, rf'QLabel\[role="{role}"\] \{{[^}}]*color: {re.escape(colors[key])}', role)

    def test_icons_render_at_every_size_the_screens_use_and_at_125_and_150_percent(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter
        from chanceblog_desktop.ui.core import icons
        for name in icons.ICONS:
            for side in (16, 18, 20, 22, 25, 28, 30, 34, 44):                             # 100%·125%·150% 에서의 실제 픽셀 크기
                image = QImage(side, side, QImage.Format_ARGB32)
                image.fill(0)
                painter = QPainter(image)
                theme.renderer(name, "#245ED4").render(painter, QRectF(0, 0, side, side))
                painter.end()
                visible = sum(1 for x in range(side) for y in range(side) if (image.pixel(x, y) >> 24) & 0xFF)
                self.assertGreater(visible, 3, f"{name} {side}px")
        icon = theme.icon("home", "#245ED4", on_color="#2F6FED")
        self.assertFalse(icon.pixmap(QSize(18, 18)).isNull())
        pixmap = icon.pixmap(QSize(25, 25))                                               # 화면 배율에 따라 실제 픽셀 수가 다르다(125%·150% 는 더 크다) — 논리 크기는 늘 25
        ratio = pixmap.devicePixelRatio()
        self.assertGreaterEqual(ratio, 1.0)
        self.assertAlmostEqual(pixmap.width() / ratio, 25, delta=1)
        self.assertAlmostEqual(pixmap.height() / ratio, 25, delta=1)
        self.assertAlmostEqual(pixmap.width(), 25 * ratio, delta=1)                        # 실제 화면 점 수만큼 그려서 흐려지지 않는다
        on = icon.pixmap(QSize(20, 20), QIcon.Normal, QIcon.On).toImage()
        off = icon.pixmap(QSize(20, 20), QIcon.Normal, QIcon.Off).toImage()
        self.assertNotEqual(on, off)                                                       # 켜진 상태는 다른 색

    def test_disabled_buttons_use_the_disabled_text_token(self):
        colors = tokens.palette()
        qss = theme.build_qss(colors)
        self.assertIn(f"color: {colors['text_disabled']}", qss)
        self.assertRegex(qss, rf"QPushButton:disabled \{{[^}}]*color: {re.escape(colors['text_disabled'])}")                  # 꺼진 단추 규칙 안에서(다른 규칙의 같은 색이 가리지 않게)
        self.assertNotRegex(qss, rf"QPushButton:disabled \{{[^}}]*color: {re.escape(colors['text_muted'])}")


class NativeFocusRectTest(QtBase):
    """진짜 윈도에서 사이드바 메뉴 단추에 키보드 포커스가 오면 파란 링 안에 윈도 기본 포커스 사각형(검은 점 356개)이 겹쳤다(검증 M-5) — 스타일시트의 `outline: none` 으로 막는다.
    offscreen 의 기본 스타일(Fusion)에는 이 사각형이 없어서 사진으로는 안 보였다 — 윈도 11 스타일(`windows11`)을 입히고 **진짜 Tab 키 이벤트**로 포커스를 옮기면(코드로 `setFocus` 하면 Qt 가 '키보드로 옮김' 표시를 안 한다) offscreen 에서도 같은 사각형이 그려진다."""
    STYLES = {"QFusionStyle": "Fusion", "QWindows11Style": "windows11", "QWindowsVistaStyle": "windowsvista", "QWindowsStyle": "Windows"}

    def use_style(self, name):
        if name not in QStyleFactory.keys():
            self.skipTest(f"이 PySide6 에는 {name} 스타일이 없다")
        original = self.STYLES.get(self.app.style().metaObject().className(), "Fusion")

        def restore():
            self.app.setStyle(original)
            theme.apply(self.app)                                                          # 글꼴·스타일시트를 다시 입힌다(다른 시험이 같은 앱을 쓴다)

        self.addCleanup(restore)
        self.app.setStyle(name)
        theme.apply(self.app)

    def tab_to(self, window, button, limit=120):
        window.nav_buttons["home"].setFocus(Qt.OtherFocusReason)
        self.settle(2)
        for _ in range(limit):
            if QApplication.focusWidget() is button:
                return True
            QTest.keyClick(QApplication.focusWidget() or window, Qt.Key_Tab)
            self.settle(1)
        return QApplication.focusWidget() is button

    @staticmethod
    def black_dots(image, tolerance=12):
        return sum(1 for y in range(image.height()) for x in range(image.width()) if all(c <= tolerance for c in (image.pixelColor(x, y).red(), image.pixelColor(x, y).green(), image.pixelColor(x, y).blue()))
                   and image.pixelColor(x, y).alpha() > 200)

    def focused_dots(self, window):
        """Tab 으로 닿는 모든 단추에 차례로 포커스를 주고 단추마다 검은 점 수를 센다 → {단추 이름: 검은 점 수}."""
        found = {}
        window.nav_buttons["home"].setFocus(Qt.OtherFocusReason)
        self.settle(2)
        for _ in range(80):
            QTest.keyClick(QApplication.focusWidget() or window, Qt.Key_Tab)
            self.settle(1)
            widget = QApplication.focusWidget()
            if isinstance(widget, QPushButton) and widget.isVisible():
                found[widget.accessibleName() or widget.text()] = self.black_dots(widget.grab().toImage())
            if widget is window.nav_buttons["home"] or (widget is not None and widget.accessibleName() in found and len(found) > 25):
                break
        return found

    def test_no_native_focus_rectangle_is_drawn_inside_a_focused_menu_button_and_the_old_stylesheet_did_draw_one(self):
        self.use_style("windows11")
        window = self.make(size=(1366, 768))
        button = window.nav_buttons["settings"]                                            # 의도적 갱신(UI-C1a): 옛 시험은 '주제 후보' 메뉴였다 — 실제 메뉴는 홈·설정뿐이다
        self.assertTrue(self.tab_to(window, button))
        self.assertEqual(self.black_dots(button.grab().toImage()), 0)                      # 고친 스타일시트: 윈도 기본 포커스 사각형이 없다
        self.app.setStyleSheet(theme.build_qss(theme.colors()).replace("outline: none;", ""))      # 대조: 옛 스타일시트(outline 없음)
        self.settle(4)
        self.assertTrue(self.tab_to(window, button))
        self.assertGreater(self.black_dots(button.grab().toImage()), 100, "대조가 안 맞는다 — 이 시험이 윈도 기본 포커스 사각형을 못 그리고 있다")
        self.app.setStyleSheet(theme.build_qss(theme.colors()))

    def test_no_kind_of_button_the_tab_key_reaches_has_a_native_focus_rectangle(self):
        """의도적 갱신(UI-C1d, D-201): 새 홈에는 칩·행마다 초안 만들기·상세 단추가 없어 홈에서 Tab 이 닿는 단추가 적다(메뉴·예시 데이터·다시 불러오기). 그래서 서랍을 연 상태(닫기·초안·보류·더보기)와
        오류 카드(다시 시도·진단 정보)에서도 같은 점검을 해 단추 종류를 빠뜨리지 않는다."""
        self.use_style("windows11")
        window = self.make(size=(1366, 768))
        found = self.focused_dots(window)
        window.open_drawer(first_row_id(window))
        self.settle()
        found.update(self.focused_dots(window))
        failing = self.make(Flaky(failures=9), size=(1366, 768))
        found.update(self.focused_dots(failing))
        self.assertGreater(len(found), 9, found)                                           # 메뉴·예시 데이터·다시 불러오기·서랍 안 넷·다시 시도·진단 정보
        self.assertEqual({name: dots for name, dots in found.items() if dots}, {})

    def test_the_base_button_rule_carries_the_outline_none(self):
        qss = theme.build_qss(tokens.palette())
        self.assertRegex(qss, r"\nQPushButton \{[^}]*outline: none;")
        self.assertEqual(qss.count("outline: none"), 1)


class SourceRulesTest(unittest.TestCase):
    """화면은 공통 부품만 쓴다 — 기본 위젯 직접 노출·인라인 스타일·직접 색·직접 글꼴을 소스에서 막는다."""

    def read(self, name):
        return (UI_DIR / name).read_text(encoding="utf-8")

    def test_screens_and_the_shell_never_build_raw_widgets(self):
        raw = re.compile(r"\b(?:QPushButton|QLabel|QLineEdit|QCheckBox|QToolButton|QRadioButton|QComboBox|QTextEdit|QPlainTextEdit|QSpinBox)\(")
        for name in ("screens.py", "shell.py", "topbar.py", "sidebar.py", "board.py"):     # 새 틀 파일(UI-C1a)·새 홈 부품 파일(UI-C1d)도 같은 규칙
            self.assertEqual(raw.findall(self.read(name)), [], name)
        self.assertNotIn("UI.QLabel", self.read("shell.py"))

    def test_no_inline_styles_or_literal_colors_or_fonts_outside_the_theme(self):
        """의도적 갱신(UI-C1d, D-201): 새 파일 `board.py` 를 훑는 파일 목록에 더했다 — 직접 쓴 색·글자 크기·반경 금지가 새 홈 부품에도 걸린다(단언은 그대로)."""
        for name in ("components.py", "screens.py", "shell.py", "workers.py", "imagecheck.py", "app.py", "topbar.py", "sidebar.py", "board.py"):
            source = self.read(name)
            self.assertNotIn("setStyleSheet(", source, name)
            self.assertNotRegex(source, r"#[0-9A-Fa-f]{6}\b", name)
            self.assertNotRegex(source, r"QFont\(\s*[\"']", name)                          # 글꼴 이름을 직접 지정하지 않는다
        self.assertEqual(self.read("theme.py").count("setStyleSheet("), 1)                 # 앱 전체 스타일시트 한 곳

    def test_the_app_code_never_calls_the_font_source_override(self):
        """의도적 갱신(UI-C1d, D-201): 새 파일 `board.py` 를 훑는 파일 목록에 더했다 — 단언은 그대로다."""
        for name in ("components.py", "screens.py", "shell.py", "app.py", "workers.py", "topbar.py", "sidebar.py", "board.py"):
            self.assertNotIn("use_font_source", self.read(name), name)


if __name__ == "__main__":
    unittest.main()
