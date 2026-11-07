"""블로그 관리 화면(P4b)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 메뉴·슬롯 카드·폼 칸·행동 줄·확인창·쓰기 흐름(작업 스레드)·입력 유지·읽기 전용 증명·키보드·접근 이름·배치(필수 크기와 최소 창)를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_blogs_core`). 사용자의 클립보드·보관소·데이터 폴더·설정 파일은 건드리지 않는다(가짜 공급자·임시 폴더의 실제 서비스).

지키는 것:
  1) 메뉴에 `블로그 관리` 가 데이터·관리 묶음으로 올라 있고 누르면 새 화면이 열린다. 화면을 열고 슬롯을 고르고 칸을 고치고 되돌려도 **파일이 하나도 안 바뀐다**(임시 폴더 전체 바이트). 홈·설정을 열어도 마찬가지다.
  2) 칸을 고치는 동안 화면을 다시 그리지 않고(같은 위젯) 오류 글·단추·카드 표시만 바뀐다. 칸에 문제가 있으면 서비스를 부르지 않고 문제 칸 옆에 쉬운 문장을 보이며 첫 문제 칸으로 포커스가 간다.
  3) 저장·복제·삭제는 작업 스레드에서 돌고 끝나면 결과를 알린다. 실패해도 입력은 그대로이고, 낡은 판이면 최신 내용을 다시 읽는다. 삭제는 확인창(위험 단추·처음 포커스는 취소)이 먼저이고 취소하면 아무것도 쓰지 않는다.
  4) 이미지는 위치만 정한다(선택기를 주입 — 파일을 읽거나 복사하지 않는다). 색은 프리셋 둘과 '정하지 않음' 뿐이고 색만으로 구분하지 않는다(이름 글자가 늘 함께 있다).
  5) Tab 한 바퀴에 새 부품이 들어 있고 모든 눌리는 부품은 접근 이름과 36px 이상의 누르는 칸을 가지며, 가로 스크롤·글자 잘림이 없고 아래 고정 행동 줄이 1366×768 에서도 보인다.
"""
import ast
import importlib.util
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.ui import adapters, blogs_adapter  # noqa: E402
from chanceblog_desktop.ui.core import blog_form as bf, blogs, services, text, tokens  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QInputMethodEvent, QPainter, QPixmap
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import blog_parts, blog_screen, theme
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module

import service_support as support  # noqa: E402

T = text.T
SIZES = ((1366, 768), (1093, 614), (1536, 864), (1280, 720), (1920, 1080), (900, 560))                  # 1093×614 = 1366×768 노트북의 125%(논리 크기) — 본문이 좁아 목록이 위로 올라가기 쉬운 곳
PICKED = "C:/예시 폴더/예시 이미지.png"                                           # 선택기가 돌려줄 가짜 위치 — 그런 파일은 없다(읽지도 않는다)


class GatedWrites(blogs.FakeBlogsProvider):
    """쓰기(저장·복제·삭제)가 **시험이 문을 열어 줄 때까지** 기다리는 가짜 공급자 — 시간(지연)에 기대지 않아서 느리거나 바쁜 PC 에서도 '쓰는 중' 을 확실히 볼 수 있다(지연 0.5~0.6초에 기댄 옛 시험은 화면을 다시 그리는 데 그만큼 걸리면 쓰기가 끝나 버려 흔들렸다)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def _enter(self, name, version, cancelled):
        if name in ("save", "clone", "clear") and not self.gate.wait(30):
            raise AssertionError("시험이 쓰기의 문을 열어 주지 않았다")
        super()._enter(name, version, cancelled)


class SlowWrites(blogs.FakeBlogsProvider):
    """쓰기가 어느 스레드에서 도는지 기록하는 가짜 공급자."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.threads = []

    def save_blog(self, key, fields, version, progress, cancelled):
        self.threads.append(threading.current_thread())
        return super().save_blog(key, fields, version, progress, cancelled)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class Base(unittest.TestCase):
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

    def activate(self, window):
        """화면 없는 환경에서는 창이 저절로 '활성' 이 되지 않고, 다시 그린 뒤에는 활성이 풀리기도 한다 — 포커스를 확인하기 전에 활성으로 만든다."""
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)

    def focus(self, widget):
        self.activate(widget.window())
        widget.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertIs(QApplication.focusWidget(), widget)

    def make(self, provider=None, size=(1366, 768), picker=None, page="blogs", wait=True):
        provider = provider or blogs.FakeBlogsProvider()
        window = shell_module.AppShell(services.FakeHomeProvider(), blogs=provider, file_picker=picker or (lambda parent, title, filters: PICKED), autoload=False)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        if page == "blogs":
            window.go("blogs")
            if wait:
                ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state != "loading" and not window.state.blogs.loading, 10)
            self.settle()
        return window

    def ui(self, window):
        return window.screen_widget.blogs_ui

    def type_into(self, window, name, value):
        edit = self.ui(window).fields[name].edit
        edit.setFocus(Qt.OtherFocusReason)
        edit.selectAll()
        QTest.keyClick(edit, Qt.Key_Delete)
        if value.isascii():
            QTest.keyClicks(edit, value)
        elif value:
            event = QInputMethodEvent()                                                               # 한글은 입력기(IME)가 글을 확정하는 것과 같은 이벤트로 넣는다 — `QTest.keyClicks` 는 이 환경(offscreen·윈도)에서 한글 글자를 만나면 프로세스가 통째로 죽는다
            event.setCommitString(value)
            QApplication.sendEvent(edit, event)
        self.settle(2)

    def wait_write(self, window):
        ui_offscreen.wait_until(self.app, lambda: not window.state.blogs.busy and window.state.blogs.pending is None, 10)
        self.settle()

    def action(self, window, key):
        return next(button for button, spec in zip(self.ui(window).bar.buttons, self.ui(window).bar.specs, strict=True) if spec["key"] == key)

    def field_error(self, window, name):
        view = self.ui(window).fields[name]
        return view.error.plain_text() if view.error_row.isVisibleTo(window) else ""


class MenuAndLayoutTest(Base):
    def test_the_blog_menu_is_in_the_data_group_and_opens_the_new_screen(self):
        window = self.make(page=None)
        self.assertEqual(list(window.nav_buttons), ["home", "seed", "blogs", "settings"])                # 의도적 갱신(Seed 관리, D-230): Seed 관리가 같은 묶음의 블로그 관리 앞에 올랐다
        self.assertEqual(window.nav_buttons["blogs"].accessibleName(), "블로그 관리 메뉴로 이동")
        self.assertEqual(list(window.sidebar.group_titles), ["core", "data", "system"])
        window.nav_buttons["blogs"].click()
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state != "loading", 10)
        self.settle()
        self.assertEqual((window.state.page, window.nav_buttons["blogs"].isChecked(), window.nav_buttons["home"].isChecked()), ("blogs", True, False))
        self.assertEqual(len(self.ui(window).cards), 5)
        self.assertEqual(len(self.ui(window).fields), 15)
        self.assertEqual(list(S.SCREEN_BUILDERS), ["home", "seed", "blogs", "settings"])                 # 의도적 갱신(Seed 관리, D-230): 화면 표에 Seed 관리 줄이 더해졌다
        self.assertEqual([item.name.text() for item in window.sidebar.soon_list.items], ["주제 후보", "초안 작성", "발행 기록"])        # 의도적 갱신(Seed 관리, D-230): Seed 관리는 완성돼 '다음 단계' 목록에서 빠졌다

    def test_the_five_slot_cards_show_registered_and_empty_slots_as_cards(self):
        window = self.make()
        cards = self.ui(window).cards
        self.assertEqual(list(cards), list(bf.SLOTS))
        self.assertEqual({key: card.property("preset") for key, card in cards.items()}, {"github_pages": "", "blogger_en": "", "blogger_ko": "", "naver_a": "warm_lifestyle", "naver_b": "cool_technology"})
        self.assertEqual([key for key, card in cards.items() if card.property("selected")], ["naver_a"])
        self.assertIn("눌러서 등록", cards["github_pages"].accessibleName())
        self.assertIn("선택됨", cards["naver_a"].accessibleName())
        texts = lambda card: {label.text() for label in card.findChildren(UI.ElidedLabel)}  # noqa: E731
        self.assertIn("블로그를 등록해 보세요", texts(cards["github_pages"]))
        self.assertIn("예시 블로그 가", texts(cards["naver_a"]))
        self.assertIn("예시 역할 — 생활 정보", texts(cards["naver_a"]), "카드에 채널 역할(또는 주요 주제) 한 줄이 있다")
        self.assertIn("예시 역할 — 기술 기록", texts(cards["naver_b"]))
        for card in cards.values():
            self.assertEqual(card.focusPolicy(), Qt.StrongFocus)
            self.assertGreaterEqual(card.height(), tokens.SIZE["hit"])

    def test_the_channel_colors_come_from_the_tokens_and_the_names_are_always_written(self):
        qss = theme.build_qss(tokens.palette())
        for preset, colors in tokens.CHANNEL_PRESETS.items():
            self.assertIn(f'QFrame[slot="true"][preset="{preset}"] {{ border-left: 4px solid {colors["primary"]}; }}', qss)
            self.assertIn(f'QLabel[chbadge="{preset}"] {{ background: {colors["surface"]}; border: 1px solid {colors["primary"]};', qss)
        window = self.make()
        header = [widget for widget in window.screen_widget.findChildren(QWidget) if widget.property("chbadge")]
        self.assertEqual([widget.property("chbadge") for widget in header], ["warm_lifestyle"], "프리셋을 정한 슬롯의 폼 머리에 채널 색 배지가 있다")
        for widget in header:
            self.assertEqual(widget.text(), "색 따뜻한 생활 톤", "색만이 아니라 이름 글자가 함께 있다")

    def test_the_form_has_three_sections_and_the_action_bar_is_the_fixed_row_at_the_bottom(self):
        window = self.make()
        labels = {label.plain_text() for label in window.screen_widget.findChildren(UI.Label)}
        for title in ("기본 정보", "자세한 정보(선택)", "모양(선택)", "네이버 A 정보", "내 블로그"):
            self.assertIn(title, labels)
        bar = self.ui(window).bar
        self.assertEqual([spec["key"] for spec in bar.specs], ["save", "revert", "clone", "delete"])
        self.assertEqual([button.text() for button in bar.buttons], ["저장", "되돌리기", "복제", "삭제"])
        self.assertEqual(bar.kinds, ("primary", "secondary", "secondary", "danger"))
        self.assertEqual(bar.accessibleName(), "블로그 프로필 행동 줄")

    def test_no_horizontal_scroll_no_clipped_text_and_the_save_button_is_visible_at_every_required_size(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(size=size)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)
                self.assertEqual(ui_offscreen.find_clipping(window), [], size)
                self.assertEqual(ui_offscreen.find_squeezed(window), [], f"{size}: 부품이 눌려 반쯤 잘리는 곳이 없다")
                button = self.action(window, "save")
                bottom = button.mapTo(window, button.rect().bottomLeft()).y()
                if size != (900, 560):
                    self.assertLessEqual(bottom, window.height(), f"{size}: 저장 단추가 창 안에 보인다")
                    self.assertEqual(window.scroll.verticalScrollBar().maximum(), 0, f"{size}: 페이지가 창보다 길지 않다(아래 고정 행동 줄이 밀려나지 않는다)")
                for card in self.ui(window).cards.values():
                    self.assertGreaterEqual(card.mapTo(window, card.rect().topLeft()).x(), 0)
                    self.assertLessEqual(card.mapTo(window, card.rect().topRight()).x(), window.width())

    def test_the_slot_cards_are_never_squeezed_below_what_their_content_needs_and_the_badges_keep_their_height(self):
        for size in ((1366, 768), (1093, 614), (900, 560)):
            window = self.make(size=size)
            for key, card in self.ui(window).cards.items():
                with self.subTest(size=size, card=key):
                    self.assertGreaterEqual(card.height(), card.minimumSizeHint().height(), "카드가 안쪽 부품의 필요 높이보다 낮게 눌리지 않는다")
                    for badge in card.findChildren(QLabel):
                        if badge.property("badge"):
                            self.assertEqual(badge.height(), tokens.SIZE["badge_h"], f"{key}: 같은 줄의 옆 카드가 길어도 배지는 늘어나거나 잘리지 않는다")

    def test_the_squeeze_detector_is_not_blind_it_sees_the_old_defect_of_a_card_with_its_own_minimum_height(self):
        original = blog_parts.SlotCard.__init__

        def old(card, vm):
            original(card, vm)
            card.setMinimumHeight(88)                                                                 # 옛 결함 — 카드의 최소 높이를 따로 정하면 배치가 안쪽 필요 높이를 무시하고 눌러 배지가 잘린다

        with mock.patch.object(blog_parts.SlotCard, "__init__", old):
            window = self.make()
        self.assertTrue([line for line in ui_offscreen.find_squeezed(window) if "비어 있음" in line or "등록됨" in line], "옛 결함에서는 잘린 배지를 찾아낸다")

    def test_the_action_bar_stays_in_the_window_even_with_a_notice_bar_at_the_small_laptop_size(self):
        """알림 줄(저장 실패·성공 안내)이 붙으면 페이지가 그만큼 길어진다 — 1366×768 노트북의 125%(논리 1093×614)에서도 아래 고정 행동 줄이 창 밖으로 밀려나지 않는다."""
        for size in ((1093, 614), (1366, 768), (1280, 720)):
            window = self.make(size=size)
            self.type_into(window, "display_name", "")
            self.action(window, "save").click()
            self.settle()
            self.assertEqual(window.state.blogs.notice[0], "error")
            self.assertTrue(window.screen_widget.findChildren(blog_parts.NoticeBar))
            bar = self.ui(window).bar
            self.assertLessEqual(bar.mapTo(window, bar.rect().bottomLeft()).y(), window.height(), f"{size}: 알림 줄이 붙어도 행동 줄이 창 안에 있다")
            self.assertEqual(window.scroll.verticalScrollBar().maximum(), 0, f"{size}: 페이지가 창보다 길지 않다")
            self.assertEqual(ui_offscreen.find_squeezed(window), [], size)

    def test_after_a_wrong_save_the_whole_first_wrong_field_with_its_sentence_is_scrolled_into_view_even_in_a_small_window(self):
        window = self.make(size=(1093, 614))
        self.type_into(window, "alias", "가" * 40)
        self.type_into(window, "display_name", "")
        self.action(window, "save").click()
        self.settle(8)
        ui = self.ui(window)
        self.assertEqual(ui.first_error, "display_name")
        view, viewport = ui.fields["display_name"], ui.form_scroll.viewport()
        top = view.mapTo(viewport, view.rect().topLeft()).y()
        bottom = view.mapTo(viewport, view.rect().bottomLeft()).y()
        self.assertGreaterEqual(top, 0, "칸 이름이 잘리지 않는다")
        self.assertLessEqual(bottom, viewport.height() + 1, "오류 문장까지 한 덩어리로 보인다(행동 줄 뒤로 숨지 않는다)")
        self.assertTrue(view.error_row.isVisibleTo(window))

    def test_the_longest_allowed_values_never_clip_or_squeeze_anything_in_the_form_or_the_cards(self):
        values = (("display_name", "가나다라마바사아자차" * 3), ("blog_ref", "example-" + "a" * 56), ("alias", "별" * 30), ("channel_role", "역할 설명이 아주 긴 줄 " * 3),
                  ("main_topics", ", ".join(f"주제{n}번의긴낱말" for n in range(1, 7))), ("audience", "독자" * 30), ("tone", "문체" * 20), ("categories", ", ".join(f"분류{n}" for n in range(1, 8))),
                  ("intro", "소개글 " * 60), ("profile_image", "C:/아주/긴/폴더/이름/" * 6 + "이미지.png"))
        for size in ((1366, 768), (900, 560)):
            with self.subTest(size=size):
                window = self.make(size=size)
                for name, value in values:
                    window.blog_edit(name, value)
                self.settle(4)
                self.assertEqual(window.state.blogs.problems("naver_a"), {}, "허용된 가장 긴 값이다 — 문제가 없다")
                self.action(window, "save").click()
                self.wait_write(window)
                self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
                self.assertEqual(ui_offscreen.find_clipping(window), [], size)
                self.assertEqual(ui_offscreen.find_squeezed(window), [], size)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{size}: 긴 값이 가로 스크롤을 만들지 않는다")

    def test_a_narrow_window_puts_the_list_above_the_form(self):
        wide = self.make(size=(1366, 768))
        narrow = self.make(size=(900, 560))
        body = lambda window: window.screen_widget.findChild(blog_screen.BlogsBody)  # noqa: E731
        self.assertTrue(body(wide).beside)
        self.assertFalse(body(narrow).beside)
        wide_list, wide_form = body(wide)._listing, body(wide)._layout.itemAt(1).widget()
        narrow_list, narrow_form = body(narrow)._listing, body(narrow)._layout.itemAt(1).widget()
        self.assertLess(wide_list.geometry().right(), wide_form.geometry().left(), "넓으면 목록이 폼 왼쪽에 있다")
        self.assertEqual(wide_list.width(), tokens.LAYOUT["blogs_list"], "옆에 둘 때 목록 폭은 토큰 값이다")
        self.assertLessEqual(narrow_list.geometry().bottom(), narrow_form.geometry().top() + 1, "좁으면 목록이 폼 위에 있다")
        self.assertLessEqual(narrow_list.height(), 2 * tokens.LAYOUT["list_stacked_h"], "위에 올라온 목록이 페이지를 한없이 늘리지 않는다(목록 스크롤 최대 높이)")
        self.assertEqual(narrow.scroll.horizontalScrollBar().maximum(), 0)


class ReadOnlyTest(Base):
    def test_opening_selecting_editing_and_reverting_write_nothing_with_the_real_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            before = support.tree_snapshot(Path(ctx.workspace.root))
            listing = sorted(str(path) for path in Path(tmp).rglob("*"))
            window = self.make(provider)
            for key in ("naver_b", "blogger_ko", "github_pages", "naver_a"):
                window.blog_select(key)
                self.settle(2)
            self.type_into(window, "alias", "고치는 중")
            window.blog_revert()
            self.settle()
            window.go("home")
            self.settle()
            window.go("settings")
            self.settle()
            window.go("blogs")
            ui_offscreen.wait_until(self.app, lambda: not window.state.blogs.loading, 10)
            self.settle()
            self.assertEqual(support.tree_snapshot(Path(ctx.workspace.root)), before)
            self.assertEqual(sorted(str(path) for path in Path(tmp).rglob("*")), listing, "읽기·고치기는 파일도 폴더도 만들지 않는다")

    def test_home_and_settings_still_read_only_after_the_blog_screen_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            home = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx)
            before, listing = support.tree_snapshot(Path(ctx.workspace.root)), sorted(str(path) for path in Path(tmp).rglob("*"))
            window = shell_module.AppShell(home, autoload=False)
            window.resize(1366, 768)
            window.show()
            self.addCleanup(window.close)
            window.reload()
            ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
            window.go("settings")
            ui_offscreen.wait_until(self.app, lambda: not window.state.conn_loading, 10)
            self.settle()
            self.assertEqual(support.tree_snapshot(Path(ctx.workspace.root)), before)
            self.assertEqual(sorted(str(path) for path in Path(tmp).rglob("*")), listing)


class EditingTest(Base):
    def test_typing_changes_the_buttons_and_cards_without_redrawing_the_screen(self):
        window = self.make()
        screen, ui = window.screen_widget, self.ui(window)
        self.assertFalse(self.action(window, "save").isEnabled())
        self.assertFalse(self.action(window, "revert").isEnabled())
        self.type_into(window, "alias", "새 별명")
        self.assertIs(window.screen_widget, screen, "고치는 동안 화면을 다시 그리지 않는다(입력 중이던 자리가 사라지지 않는다)")
        self.assertEqual(ui.fields["alias"].edit.text(), "새 별명")
        self.assertTrue(self.action(window, "save").isEnabled() and self.action(window, "revert").isEnabled())
        self.assertTrue(ui.unsaved.isVisibleTo(window))
        self.assertIn("저장 전 변경", {label.text() for label in ui.cards["naver_a"].findChildren(UI.Label)} | {label.text() for label in ui.cards["naver_a"].findChildren(QWidget) if hasattr(label, "text") and callable(label.text)})
        self.type_into(window, "alias", "예시 별명")
        self.assertFalse(self.action(window, "save").isEnabled(), "저장된 값으로 돌아가면 저장 단추가 다시 꺼진다")

    def test_the_draft_survives_leaving_and_coming_back_to_the_slot_and_the_screen(self):
        window = self.make()
        self.type_into(window, "tone", "임시 문체")
        window.blog_select("naver_b")
        self.settle()
        self.assertEqual(self.ui(window).fields["tone"].edit.text(), "")
        window.blog_select("naver_a")
        self.settle()
        self.assertEqual(self.ui(window).fields["tone"].edit.text(), "임시 문체")
        window.go("home")
        window.go("blogs")
        ui_offscreen.wait_until(self.app, lambda: not window.state.blogs.loading, 10)
        self.settle()
        self.assertEqual(self.ui(window).fields["tone"].edit.text(), "임시 문체", "화면을 떠났다 돌아와도 초안이 남는다")

    def test_a_wrong_value_shows_an_easy_sentence_beside_the_field_and_the_save_button_does_not_call_the_service(self):
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider)
        calls = list(provider.calls)
        self.type_into(window, "alias", "가" * 40)
        self.assertIn("30자까지", self.field_error(window, "alias"))
        self.assertIn("지금 40자", self.field_error(window, "alias"))
        self.assertTrue(self.ui(window).fields["alias"].edit.property("invalid"))
        self.type_into(window, "display_name", "")
        self.assertEqual(self.field_error(window, "display_name"), T["bf_err_required"])
        self.action(window, "save").click()
        self.settle()
        self.assertEqual(provider.calls, calls, "문제가 있으면 서비스를 부르지 않는다")
        self.assertEqual(window.state.blogs.notice, ("error", T["blogs_save_invalid"]))
        focused = window.focusWidget()                                                            # 창 안의 포커스 — 화면 없는 환경에서 창이 비활성이어도 같다
        self.assertIs(focused, self.ui(window).fields[self.ui(window).first_error].controls[0], "첫 문제 칸으로 포커스가 간다")
        self.assertEqual(self.ui(window).first_error, "display_name")
        self.assertEqual(self.field_error(window, "alias"), T["bf_err_too_long"].format(limit=30, now=40))
        self.type_into(window, "display_name", "예시 블로그 가")
        self.type_into(window, "alias", "정상 별명")
        self.assertEqual((self.field_error(window, "alias"), self.field_error(window, "display_name")), ("", ""))

    def test_required_marks_hints_and_keyboard_names_of_every_field(self):
        window = self.make()
        fields = self.ui(window).fields
        for name in ("display_name", "blog_ref", "language", "generation_enabled"):
            badges = [label.text() for label in fields[name].findChildren(QLabel) if label.text() == "필수"]
            self.assertEqual(badges, ["필수"], name)
        for name in ("alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "monetization_focus", "color_preset", "profile_image", "cover_image"):
            self.assertEqual([label.text() for label in fields[name].findChildren(QLabel) if label.text() == "필수"], [], f"{name}: 선택 칸에는 필수 표시가 없다")
        for name, view in fields.items():
            self.assertTrue(view.controls, name)
            for control in view.controls:
                self.assertTrue(control.accessibleName(), name)
                self.assertGreaterEqual(control.height(), tokens.SIZE["hit"], f"{name}: 누르는 칸 36px")
            self.assertTrue(view.hint.plain_text() or view.name == "color_preset", name)

    def test_the_language_and_color_choices_and_the_sponsor_chips_work_by_click_and_by_keyboard(self):
        window = self.make()
        fields = self.ui(window).fields
        fields["language"].chips["en"].click()
        self.settle()
        self.assertEqual(window.state.blogs.values("naver_a")["language"], "en")
        self.assertTrue(fields["language"].chips["en"].isChecked() and not fields["language"].chips["ko"].isChecked())
        fields["color_preset"].chips["cool_technology"].click()
        self.assertEqual(window.state.blogs.values("naver_a")["color_preset"], "cool_technology")
        fields["color_preset"].chips[""].click()
        self.assertEqual(window.state.blogs.values("naver_a")["color_preset"], "")
        self.assertEqual(sorted(fields["color_preset"].chips), ["", "cool_technology", "warm_lifestyle"], "색은 프리셋 둘과 '정하지 않음' 뿐 — 직접 색을 넣는 칸이 없다")
        for chip in fields["color_preset"].chips.values():
            self.assertFalse(chip.icon().isNull(), "견본 아이콘")
            self.assertIn(chip.text(), ("정하지 않음", "따뜻한 생활 톤", "차분한 기술 톤"), "색만으로 구분하지 않는다 — 이름 글자가 있다")
        chip = fields["monetization_focus"].chips["pc_parts"]
        chip.setFocus(Qt.TabFocusReason)
        QTest.keyClick(chip, Qt.Key_Space)
        self.settle()
        self.assertIn("pc_parts", window.state.blogs.values("naver_a")["monetization_focus"])
        self.assertTrue(chip.isChecked())
        toggle = fields["generation_enabled"].toggle
        toggle.setFocus(Qt.TabFocusReason)
        QTest.keyClick(toggle, Qt.Key_Space)
        self.settle()
        self.assertFalse(window.state.blogs.values("naver_a")["generation_enabled"])
        self.assertEqual(toggle.text(), "꺼짐")

    def test_the_candidate_switch_of_the_other_channels_is_off_disabled_and_says_why(self):
        window = self.make()
        window.blog_select("blogger_ko")
        self.settle()
        view = self.ui(window).fields["generation_enabled"]
        self.assertFalse(view.toggle.isEnabled())
        self.assertIn("아직 지원하지 않아요", view.hint.plain_text())
        self.assertIn("아직 지원하지 않아요", view.toggle.accessibleDescription())

    def test_picking_an_image_only_sets_the_location_and_never_reads_the_file(self):
        picked = []
        window = self.make(picker=lambda parent, title, filters: (picked.append((title, filters)), PICKED)[1])
        view = self.ui(window).fields["profile_image"]
        with mock.patch("builtins.open", side_effect=AssertionError("파일을 열면 안 된다")):
            view.pick.click()
            self.settle()
        self.assertEqual(view.edit.text(), PICKED)
        self.assertEqual(window.state.blogs.values("naver_a")["profile_image"], PICKED)
        self.assertEqual(picked[0][0], "프로필 이미지 고르기")
        self.assertIn("*.png", picked[0][1])
        self.assertTrue(view.clear_button.isEnabled())
        view.clear_button.click()
        self.settle()
        self.assertEqual((view.edit.text(), window.state.blogs.values("naver_a")["profile_image"]), ("", ""))
        self.assertFalse(view.clear_button.isEnabled())
        window2 = self.make(picker=lambda parent, title, filters: "")
        self.ui(window2).fields["cover_image"].pick.click()
        self.settle()
        self.assertEqual(window2.state.blogs.values("naver_a")["cover_image"], "", "대화상자를 취소하면(빈 글) 아무것도 안 바뀐다")
        self.assertFalse(window2.state.blogs.is_dirty("naver_a"))


class WritingTest(Base):
    def test_a_save_runs_on_a_worker_thread_shows_the_result_and_clears_the_draft(self):
        provider = SlowWrites()
        window = self.make(provider)
        self.type_into(window, "alias", "저장할 별명")
        self.action(window, "save").click()
        self.assertTrue(window.state.blogs.busy or provider.threads)
        self.wait_write(window)
        self.assertEqual(provider.load_blogs(lambda *a: None, lambda: False).by_key()["naver_a"].alias, "저장할 별명")
        self.assertNotIn(threading.main_thread(), provider.threads, "쓰기는 화면 스레드가 아니라 작업 스레드에서 돈다")
        self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
        notice = window.screen_widget.findChildren(blog_parts.NoticeBar)
        self.assertEqual([bar.text.plain_text() for bar in notice], ["저장했어요."])
        self.assertFalse(self.action(window, "save").isEnabled())
        self.assertFalse(window.state.blogs.is_dirty("naver_a"))
        self.assertEqual(self.ui(window).fields["alias"].edit.text(), "저장할 별명")

    def test_while_saving_the_fields_and_buttons_are_off_and_a_second_click_does_nothing(self):
        provider = GatedWrites()
        window = self.make(provider)
        self.type_into(window, "alias", "저장할 별명")
        self.action(window, "save").click()
        self.settle(2)
        self.assertTrue(window.state.blogs.busy)
        self.assertTrue(all(not button.isEnabled() for button in self.ui(window).bar.buttons))
        self.assertTrue(all(not control.isEnabled() for view in self.ui(window).fields.values() for control in view.controls))
        self.assertIn("저장하는 중이에요…", {label.plain_text() for label in window.screen_widget.findChildren(UI.Label)})
        window.blog_save()
        window.blog_clone()
        provider.gate.set()
        self.wait_write(window)
        self.assertEqual(provider.calls.count("save"), 1)
        self.assertEqual(provider.calls.count("clone"), 0)

    def test_a_failed_save_keeps_the_typed_values_and_says_why(self):
        for kind, key in (("io", "blogs_fail_io"), ("busy", "blogs_fail_busy"), ("disk", "blogs_fail_disk"), ("corrupt", "blogs_fail_corrupt")):
            provider = blogs.FakeBlogsProvider()
            provider.save_blog = lambda *a, k=kind: (_ for _ in ()).throw(blogs.BlogFailure("x", code="C", kind=k))
            window = self.make(provider)
            self.type_into(window, "alias", "남아야 하는 별명")
            self.type_into(window, "intro", "남아야 하는 소개글")
            self.action(window, "save").click()
            self.wait_write(window)
            with self.subTest(kind=kind):
                self.assertEqual(window.state.blogs.notice, ("error", T[key]))
                self.assertEqual((self.ui(window).fields["alias"].edit.text(), self.ui(window).fields["intro"].edit.text()), ("남아야 하는 별명", "남아야 하는 소개글"))
                self.assertTrue(self.action(window, "save").isEnabled(), "다시 저장할 수 있다")
                self.assertEqual([bar.level for bar in window.screen_widget.findChildren(blog_parts.NoticeBar)], ["error"])
                self.assertNotRegex(" ".join(label.plain_text() for label in window.screen_widget.findChildren(UI.Label)), r"Traceback|\[['\"]|Exception|C:[\\/]")

    def test_a_service_rejection_marks_the_field_beside_it(self):
        provider = blogs.FakeBlogsProvider()
        provider.save_blog = lambda *a: (_ for _ in ()).throw(blogs.BlogFailure("x", code="CONTENT_INVALID", kind="invalid", problems={"alias": "key_shape"}))
        window = self.make(provider)
        self.type_into(window, "alias", "별명")
        self.action(window, "save").click()
        self.wait_write(window)
        self.assertEqual(self.field_error(window, "alias"), T["bf_err_key_shape"])
        self.assertEqual(self.ui(window).fields["alias"].edit.text(), "별명")

    def test_a_stale_version_reloads_the_latest_and_keeps_the_input_then_saves_again(self):
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider)
        self.type_into(window, "alias", "내 별명")
        provider.slots["naver_b"] = provider.slots["naver_b"].__class__(**{**provider.slots["naver_b"].__dict__, "alias": "다른 창이 저장한 별명"})
        provider.revision += 1
        self.action(window, "save").click()
        self.wait_write(window)
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.notice and window.state.blogs.notice[0] == "warning", 10)
        self.settle()
        self.assertEqual(window.state.blogs.notice, ("warning", T["blogs_stale_reloaded"]))
        self.assertEqual(self.ui(window).fields["alias"].edit.text(), "내 별명", "입력은 그대로다")
        self.assertEqual(window.state.blogs.base_raw("naver_b")["alias"], "다른 창이 저장한 별명", "최신 내용을 다시 읽었다")
        self.action(window, "save").click()
        self.wait_write(window)
        self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))

    def test_clone_fills_the_empty_slot_and_selects_it_and_the_button_says_why_when_it_cannot(self):
        window = self.make()
        clone = self.action(window, "clone")
        self.assertFalse(clone.isEnabled())
        self.assertIn("같은 종류의 비어 있는 슬롯이 없어요", clone.toolTip())
        window.blog_select("blogger_ko")
        self.settle()
        clone = self.action(window, "clone")
        self.assertTrue(clone.isEnabled())
        self.assertIn("Blogger 영문", clone.toolTip(), "복제해 넣을 슬롯을 알려 준다")
        clone.click()
        self.wait_write(window)
        self.assertEqual(window.state.blogs.selected, "blogger_en")
        self.assertEqual(self.ui(window).fields["blog_ref"].edit.text(), "example-blog-c")
        self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_cloned"]))
        self.assertEqual(self.field_error(window, "blog_ref"), "")
        self.assertIn(T["bf_warn_same_ref"], {label.plain_text() for label in window.screen_widget.findChildren(UI.Label)}, "같은 블로그가 두 슬롯에 있다는 주의")

    def test_delete_asks_first_with_a_danger_button_focused_on_cancel_and_cancelling_writes_nothing(self):
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider)
        calls = list(provider.calls)
        self.action(window, "delete").click()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        names = {label.plain_text() for label in window.dialog.findChildren(UI.Label)}
        self.assertIn("이 프로필을 지울까요?", names)
        body = next(name for name in names if "비워져요" in name)
        for part in ("예시 블로그 가", "되돌릴 수 없어요", "후보·초안·발행 기록은 지워지지 않아요", "슬롯은 사라지지 않고"):
            self.assertIn(part, body)
        buttons = {button.text(): button for button in window.dialog.findChildren(QAbstractButton)}
        self.assertEqual(sorted(buttons), ["지우기", "취소"])
        self.assertEqual(buttons["지우기"].property("kind"), "danger", "최종 삭제 확인은 위험 단추")
        self.assertIs(window.focusWidget(), window.dialog_default, "대화상자가 열리면 처음 포커스는 기본 단추에 있다")
        self.assertIs(window.dialog_default, buttons["취소"], "처음 포커스는 취소 — Enter 를 잘못 눌러도 지워지지 않는다")
        QTest.keyClick(window.dialog_default, Qt.Key_Return)
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(provider.calls, calls, "취소하면 아무것도 쓰지 않는다")
        self.assertTrue(provider.slots["naver_a"].registered)
        self.action(window, "delete").click()
        self.settle()
        window.escape()
        self.settle()
        self.assertEqual(provider.calls, calls, "Esc 로 닫아도 마찬가지")

    def test_confirming_the_delete_empties_the_slot_but_the_card_stays(self):
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider)
        self.action(window, "delete").click()
        self.settle()
        next(button for button in window.dialog.findChildren(QAbstractButton) if button.text() == "지우기").click()
        self.wait_write(window)
        self.assertEqual(provider.calls[-1], "clear")
        self.assertFalse(provider.slots["naver_a"].registered)
        self.assertEqual(len(self.ui(window).cards), 5, "슬롯 카드는 사라지지 않는다")
        self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_cleared"]))
        self.assertEqual(self.ui(window).fields["blog_ref"].edit.text(), "")
        self.assertFalse(self.action(window, "delete").isEnabled(), "이미 비었다")
        self.assertIn("블로그를 등록해 보세요", {label.text() for label in self.ui(window).cards["naver_a"].findChildren(UI.ElidedLabel)})

    def test_closing_the_window_waits_for_a_write_in_progress(self):
        provider = GatedWrites()
        window = self.make(provider)
        self.type_into(window, "alias", "저장할 별명")
        self.action(window, "save").click()
        self.settle(2)
        self.assertTrue(window.state.blogs.busy)
        hide = window.hide

        def hide_then_open_the_gate_a_little_later():
            hide()
            threading.Timer(2.0, provider.gate.set).start()                                       # 창을 닫기 시작한 **뒤 2초에야** 쓰기가 끝난다 — 작업 정리가 기다리는 1초보다 길어서, 닫는 쪽이 따로(최대 10초) 기다려야만 아래 값이 맞는다

        window.hide = hide_then_open_the_gate_a_little_later
        window.close()
        self.assertFalse(window.state.blogs.busy, "창을 닫을 때 쓰기가 끝나기를 기다렸다")
        self.assertEqual(provider.slots["naver_a"].alias, "저장할 별명")


class RealServiceFlowTest(Base):
    def test_register_save_again_and_delete_through_the_screen_with_the_real_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            window = self.make(provider)
            self.assertEqual(window.screen_widget.findChildren(blog_parts.NoticeBar)[0].level, "info", "처음에는 파일이 아직 없다는 안내")
            self.assertEqual(window.sidebar.findChild(QWidget, "brandcard") is not None, True)
            self.assertFalse([widget for widget in window.screen_widget.findChildren(QWidget) if widget.accessibleName() == "예시 데이터"], "실제 어댑터에는 '예시 데이터' 표시가 없다")
            self.type_into(window, "display_name", "예시 블로그 가")
            self.type_into(window, "blog_ref", "example-blog-a")
            self.type_into(window, "main_topics", "예시 주제 하나, 예시 주제 둘")
            self.ui(window).fields["color_preset"].chips["warm_lifestyle"].click()
            self.action(window, "save").click()
            self.wait_write(window)
            self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
            saved = {profile.key: profile for profile in bp.read_snapshot(ctx).profiles}["naver_a"]
            self.assertEqual((saved.display_name, saved.blog_ref, saved.main_topics, saved.color_preset), ("예시 블로그 가", "example-blog-a", ("예시 주제 하나", "예시 주제 둘"), "warm_lifestyle"))
            files = sorted(path.relative_to(ctx.workspace.root).as_posix() for path in Path(ctx.workspace.root).rglob("*") if path.is_file() and path.name != "settings.json")
            self.assertEqual(files, ["topic_engine/channel_profiles.json"])
            self.type_into(window, "alias", "예시 별명")
            self.action(window, "save").click()
            self.wait_write(window)
            self.assertTrue((Path(ctx.workspace.root) / "topic_engine" / "channel_profiles.json.bak").is_file(), "두 번째 저장부터 직전 내용의 사본이 있다")
            self.action(window, "delete").click()
            self.settle()
            next(button for button in window.dialog.findChildren(QAbstractButton) if button.text() == "지우기").click()
            self.wait_write(window)
            self.assertTrue(bp.is_empty({profile.key: profile for profile in bp.read_snapshot(ctx).profiles}["naver_a"]))
            self.assertEqual(len(bp.read_snapshot(ctx).profiles), 5)

    def test_a_broken_profile_file_shows_a_read_error_with_a_retry_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            folder = Path(ctx.workspace.root) / "topic_engine"
            folder.mkdir(parents=True)
            (folder / "channel_profiles.json").write_bytes(b"{broken")
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            before = support.tree_snapshot(Path(ctx.workspace.root))
            window = self.make(provider)
            self.assertEqual(window.state.blogs.state, "error")
            labels = {label.plain_text() for label in window.screen_widget.findChildren(UI.Label)}
            self.assertIn("블로그 정보를 읽지 못했어요.", labels)
            self.assertEqual(self.ui(window).fields, {}, "폼이 없다 — 틀린 파일 위에 쓸 길이 없다")
            self.assertEqual(support.tree_snapshot(Path(ctx.workspace.root)), before)
            (folder / "channel_profiles.json").unlink()
            retry = next(button for button in window.screen_widget.findChildren(QAbstractButton) if button.text() == "다시 읽기")
            retry.click()
            ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state == "normal", 10)
            self.settle()
            self.assertEqual(len(self.ui(window).cards), 5)


class StatesTest(Base):
    def test_loading_shows_a_skeleton_with_its_own_name_and_the_error_state_has_a_retry(self):
        slow = blogs.FakeBlogsProvider(delay=30)
        window = self.make(slow, wait=False)
        self.assertEqual(window.state.blogs.state, "loading")
        self.assertTrue([w for w in window.screen_widget.findChildren(QWidget) if w.accessibleName() == "블로그 정보를 읽는 중"])
        window.close()
        broken = blogs.FakeBlogsProvider("error")
        window = self.make(broken)
        self.assertEqual(window.state.blogs.state, "error")
        labels = {label.plain_text() for label in window.screen_widget.findChildren(UI.Label)}
        self.assertIn("블로그 정보를 읽지 못했어요.", labels)
        self.assertIn("진단 정보 보기", {button.text() for button in window.screen_widget.findChildren(QAbstractButton)})

    def test_the_sample_badge_and_dialog_belong_to_the_sample_data_only(self):
        window = self.make()
        badge = next(button for button in window.screen_widget.findChildren(QAbstractButton) if button.accessibleName() == "예시 데이터")
        badge.click()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertIn("저장해도 이 PC 의 파일에는 아무것도 쓰지 않아요", " ".join(label.plain_text() for label in window.dialog.findChildren(UI.Label)))
        window.escape()


class KeyboardTest(Base):
    def test_tab_goes_all_the_way_around_through_cards_fields_and_the_action_bar_and_every_stop_has_a_name(self):
        window = self.make()
        start = window.nav_buttons["blogs"]
        self.focus(start)
        seen, current = [], start
        for _ in range(150):
            seen.append(current)
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            if current is start:
                break
        else:
            self.fail("Tab 이 한 바퀴를 돌지 못했다")
        self.assertEqual(len(seen), len(set(map(id, seen))), "같은 곳을 두 번 지나지 않는다(갇히지 않는다)")
        ui = self.ui(window)
        stops = {id(widget) for widget in seen}
        for card in ui.cards.values():
            self.assertIn(id(card), stops, card.accessibleName())
        for name, view in ui.fields.items():
            groups = {}
            for control in view.controls:
                group = control.group() if hasattr(control, "group") and control.group() is not None and control.group().exclusive() else None
                groups.setdefault(id(group) if group is not None else id(control), []).append(control)
            for members in groups.values():
                enabled = [control for control in members if control.isEnabled()]
                if enabled:
                    self.assertTrue(any(id(control) in stops for control in enabled), f"Tab 한 바퀴에 {name} 칸이 있다")
            if view.kind == "choice":                                                             # 하나만 고르는 칩 묶음은 **고른 칩만** 정거장이고 나머지는 화살표 키로 옮긴다(Tab 으로 들어가 Space 를 눌러도 값이 안 바뀐다)
                self.assertEqual([chip.isChecked() for chip in view.chips.values() if id(chip) in stops], [True], name)
        for button in ui.bar.buttons:
            if button.isEnabled() and button.isVisible():
                self.assertIn(id(button), stops, button.text())
        for widget in seen:
            self.assertTrue(widget.accessibleName().strip(), type(widget).__name__)
            self.assertGreaterEqual(widget.height(), tokens.SIZE["hit"] if not widget.property("nav") else 1, widget.accessibleName())

    def test_the_arrow_keys_move_between_the_options_of_a_choice_and_space_picks_one(self):
        window = self.make()
        fields = self.ui(window).fields
        chip = fields["language"].chips["ko"]
        self.focus(chip)
        QTest.keyClick(chip, Qt.Key_Right)
        self.settle()
        self.assertEqual(window.state.blogs.values("naver_a")["language"], "en", "화살표 키가 옆 선택지로 옮기며 고른다(하나만 고르는 묶음)")
        self.assertTrue(fields["language"].chips["en"].isChecked())

    def test_enter_and_space_on_a_slot_card_select_it_and_the_focus_returns_to_the_card(self):
        window = self.make()
        card = self.ui(window).cards["naver_b"]
        self.focus(card)
        QTest.keyClick(card, Qt.Key_Return)
        self.settle()
        self.assertEqual(window.state.blogs.selected, "naver_b")
        focused = window.focusWidget()
        self.assertEqual(getattr(focused, "key", None), "naver_b", "다시 그린 뒤에도 그 카드에 포커스가 남는다")
        QTest.keyClick(focused, Qt.Key_Space)
        window.blog_select("blogger_en")
        self.settle()
        self.assertEqual(window.state.blogs.selected, "blogger_en")


class SourceRulesTest(unittest.TestCase):
    QT = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
    NEW = ("blog_parts.py", "blog_screen.py")

    def test_the_new_qt_files_follow_the_part_rules(self):
        raw = re.compile(r"\b(?:QPushButton|QLabel|QLineEdit|QCheckBox|QToolButton|QRadioButton|QComboBox|QTextEdit|QPlainTextEdit|QSpinBox)\(")
        for name in self.NEW:
            source = (self.QT / name).read_text(encoding="utf-8")
            self.assertEqual(raw.findall(source), [], name)
            self.assertNotIn("setStyleSheet(", source, name)
            self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", source), [], name)
            self.assertNotRegex(source, r"QFont\(|font-size|setPointSize|datetime\.now|date\.today|use_font_source", name)
            self.assertNotRegex(source, r"\b(?:go|nav|navigate)\(", name + ": 화면 이동 요청은 사이드바·셸뿐이다")

    def test_the_part_files_hold_no_file_writing_call_and_the_screen_never_calls_the_service(self):
        for name in self.NEW:
            source = (self.QT / name).read_text(encoding="utf-8")
            calls = [ast.unparse(node.func) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
            for call in calls:
                self.assertNotRegex(call, r"write_text|write_bytes|write_json|unlink|mkdir|os\.|shutil|\bopen$|save_slot|clone_slot|clear_slot|save_blog|clone_blog|clear_blog", f"{name}: {call}")
            imports = [node.module or "" for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
            self.assertEqual([module for module in imports if "service" in module or "adapter" in module], [], f"{name}: 화면 부품은 서비스 층·어댑터를 가져오지 않는다")

    def test_the_shell_reaches_the_service_only_through_the_state(self):
        source = (self.QT / "shell.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertFalse({module for module in imports if module and "service" in module}, "셸은 서비스 층을 직접 가져오지 않는다")
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        for forbidden in ("save_slot", "clone_slot", "clear_slot", "write_json", "open"):
            self.assertNotIn(forbidden, calls)

    def test_the_swatch_icon_paints_from_the_tokens_and_the_preset_colors_never_become_text_colors(self):
        pixmap = QPixmap(48, 16) if HAVE else None
        if not HAVE:
            self.skipTest("PySide6 가 없다")
        for preset in ("", "warm_lifestyle", "cool_technology"):
            pixmap.fill(Qt.white)
            painter = QPainter(pixmap)
            blog_parts.SwatchIconEngine(preset).paint(painter, QRect(0, 0, 48, 16), 0, 0)
            painter.end()
            image = pixmap.toImage()
            colors = {image.pixelColor(x, 8).name().upper() for x in range(0, 48)}
            if preset:
                for name in ("primary", "secondary", "accent"):
                    self.assertIn(tokens.CHANNEL_PRESETS[preset][name], colors, (preset, name))
            else:
                self.assertGreater(len(colors), 1)
        qss = theme.build_qss(tokens.palette())
        for preset, palette in tokens.CHANNEL_PRESETS.items():
            for line in qss.splitlines():
                if f'"{preset}"' in line and "QLabel[chbadge" in line:
                    self.assertIn(f"color: {tokens.palette()['text_strong']};", line, "배지 글자는 text_strong — 프리셋 색은 글자로 쓰지 않는다")
                    self.assertNotIn(f"color: {palette['primary']}", line.replace(f"border: 1px solid {palette['primary']}", ""))


if __name__ == "__main__":
    unittest.main()
