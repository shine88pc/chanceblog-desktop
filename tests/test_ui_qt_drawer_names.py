"""긴 별명이 세 서랍(홈 주제 상세·새 Seed·Seed 상세)을 넘치게 하지 않는지 — BLOGSEL-2 독립 검증 Q2-1(필수)의 PySide6 시험(창을 화면에 띄우지 않고 offscreen). **PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다).

왜: 서랍은 폭이 늘 420 인데 별명이 길면(한글 열 자부터 홈 서랍, 스물다섯 자부터 Seed 서랍) 내용의 최소 폭이 서랍 안쪽 폭보다 넓어져 오른쪽 열·`{이름} 초안` 단추·닫기(X)가 잘렸다.
**자동 잘림 점검(`find_clipping`·`find_squeezed`)은 서랍 안의 이런 가로 넘침을 못 본다** — 서랍의 안쪽 스크롤 영역이 가로 줄을 감추고 위젯만 더 넓어지기 때문이다. 이 시험이 그 틈을 메운다:
서랍 안쪽 내용의 폭(최소 폭 포함)이 보이는 폭 안이고, 보이는 모든 부품(닫기·초안 단추·칩·배지)의 오른쪽 끝도 보이는 폭 안이다.

지키는 것:
  1) 별명이 한도(30자) 가득이어도(같은 이름 둘로 가른 이름 포함) 세 서랍의 내용이 서랍보다 넓지 않고 닫기·초안 단추·칩이 모두 보인다 — 두 창 크기(1366×768·900×560)에서.
  2) 줄인 이름은 전체 이름이 툴팁·접근 이름이다(홈 서랍의 배지·`{이름} 초안` 단추·Seed 서랍의 칩) — 이름을 안 줄이면 툴팁이 따로 없다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ui_qt_candidates import Base as CandidatesBase  # noqa: E402,I001
from test_ui_qt_seeds import HAVE, Base  # noqa: E402,I001

from chanceblog_desktop.ui.core import channel_names as cn  # noqa: E402

if HAVE:
    import ui_offscreen
    from PySide6.QtWidgets import QAbstractButton, QWidget

LONG30 = ("가나다라마바사아자차카타파하" * 3)[:30]                                              # 한도(30자) 가득한 별명
LONG30_B = ("나다라마바사아자차카타파하가" * 3)[:30]
SIZES = ((1366, 768), (900, 560))


def assert_content_fits(case, holder, label):
    """서랍·고정 상세 창(안쪽 스크롤 영역) 안쪽 내용이 보이는 폭 안이다 — 내용의 최소 폭·실제 폭·보이는 모든 부품의 오른쪽 끝(검증 Q2-1·S3-8)."""
    body, viewport = holder.scroll.widget(), holder.scroll.viewport()
    case.assertLessEqual(body.minimumSizeHint().width(), viewport.width(), f"{label}: 내용의 최소 폭이 안쪽 폭보다 넓다")
    case.assertLessEqual(body.width(), viewport.width(), f"{label}: 내용이 안쪽 폭보다 넓다")
    for widget in body.findChildren(QWidget):
        if widget.isVisibleTo(body) and widget.width() > 0:
            right = widget.mapTo(body, widget.rect().topRight()).x()
            case.assertLessEqual(right, viewport.width(), f"{label}: {type(widget).__name__} {getattr(widget, 'text', lambda: '')()!r:.30} 의 오른쪽 끝이 잘린다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class LongAliasDrawersTest(Base):
    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def long_names(self):
        cn.use(cn.labels({"naver_a": (LONG30, True), "naver_b": (LONG30_B, True), "blogger_ko": ("", True), "blogger_en": ("", False), "github_pages": ("", False)}))     # 둘은 한도 가득한 별명, 나머지는 기본 이름

    def assert_fits(self, window, label):
        """서랍 안쪽 내용이 보이는 폭 안이다 — 내용의 최소 폭·실제 폭·보이는 모든 부품의 오른쪽 끝(검증 Q2-1)."""
        self.settle(10)
        self.assertTrue(window.drawer.is_open, label)
        assert_content_fits(self, window.drawer, label)

    def home_window(self, size):
        window = self.make(size=size, page="home")
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        self.settle()
        return window

    def test_the_home_topic_drawer_stays_inside_the_drawer_for_a_thirty_character_alias_and_the_cut_names_carry_the_full_name(self):
        for size in SIZES:
            window = self.home_window(size)
            self.long_names()
            window.render()
            self.settle()
            window.open_drawer("rA1")
            self.assert_fits(window, f"홈 서랍 {size}")
            body = window.drawer.scroll.widget()
            draft = next(button for button in body.findChildren(QAbstractButton) if button.text().endswith(" 초안"))
            self.assertEqual((draft.toolTip(), draft.accessibleName()), (f"{LONG30} 초안", f"{LONG30} 초안"), "줄인 단추 글의 전체 이름이 툴팁·접근 이름이다")
            self.assertLessEqual(len(draft.text()), cn.DRAWER_LIMIT + len(" 초안"))
            badge = next(widget for widget in body.findChildren(QWidget) if widget.property("badge") == "info")
            self.assertEqual((badge.text(), badge.toolTip(), badge.accessibleName()), (cn.short_label("naver_a"), LONG30, LONG30))
            window.close_drawer()

    def test_the_home_topic_drawer_has_no_tooltip_for_a_name_that_was_not_cut(self):
        window = self.home_window(SIZES[0])
        window.open_drawer("rA1")
        self.assert_fits(window, "홈 서랍(기본 이름)")
        body = window.drawer.scroll.widget()
        badge = next(widget for widget in body.findChildren(QWidget) if widget.property("badge") == "info")
        draft = next(button for button in body.findChildren(QAbstractButton) if button.text().endswith(" 초안"))
        self.assertEqual((badge.text(), badge.toolTip(), draft.text(), draft.toolTip()), ("네이버 블로그 1", "", "네이버 블로그 1 초안", ""))

    def test_the_new_seed_drawer_stays_inside_the_drawer_for_thirty_character_aliases_and_the_chips_carry_the_full_name(self):
        for size in SIZES:
            window = self.make(size=size)
            self.long_names()
            window.render()
            self.settle()
            window.seed_open_new()
            self.settle(8)
            fields = self.dui(window).fields
            fields["scope"].chips["common"].click()                                                  # 공통을 고르면 허용 채널 칩이 나타난다
            self.settle(8)
            self.assert_fits(window, f"새 Seed 서랍(허용 채널·소속 칩) {size}")
            fields = self.dui(window).fields
            for name, code in (("scope", "naver_a"), ("allowed_channels", "naver_a"), ("allowed_channels", "naver_b")):
                chip = fields[name].chips[code]
                self.assertEqual(chip.toolTip(), cn.label(code), (name, code))
                self.assertIn(cn.label(code), chip.accessibleName())
                self.assertLessEqual(len(chip.text()), cn.DRAWER_LIMIT)
            self.assertEqual(fields["allowed_channels"].chips["github_pages"].toolTip(), "", "줄이지 않은 이름에는 툴팁이 따로 없다")

    def test_the_seed_detail_drawer_stays_inside_the_drawer_for_thirty_character_aliases(self):
        for size in SIZES:
            window = self.make(size=size)
            self.long_names()
            window.render()
            self.settle()
            self.open_row(window, "EX011")
            self.assert_fits(window, f"Seed 상세 서랍 {size}")
            chips = self.dui(window).fields["allowed_channels"].chips
            self.assertEqual(chips["naver_a"].toolTip(), cn.label("naver_a"))


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class SpecialCharactersTest(Base):
    """검증 S2-3: 별명의 `&`·`<b>`·`&lt;` 가 칩·단추·배지에서 글자 그대로 보인다 — Qt 는 단추 글의 `&` 를 Alt 단축키로 읽어(`A&B` → `AB`·Alt+B, `&lt;` → `lt;`) 사라지게 하고 라벨은 `<b>` 를 서식으로 읽는다."""

    NAMES = {"naver_a": "A&B 블로그", "naver_b": "<b>x</b>", "blogger_ko": "&lt;"}

    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def names(self):
        cn.use(cn.labels({**{key: (alias, True) for key, alias in self.NAMES.items()}, "blogger_en": ("", False), "github_pages": ("", False)}))

    def test_the_chip_and_button_factories_show_an_ampersand_as_typed_and_make_no_shortcut_while_the_accessible_name_stays_raw(self):
        from chanceblog_desktop.ui.qt import components as UI
        for text in ("A&B 블로그", "&lt;", "<b>x</b>"):
            chip = UI.FilterChip(text, None, False)
            button = UI.Button("primary", text)
            for widget in (chip, button):
                self.assertTrue(widget.shortcut().isEmpty(), (type(widget).__name__, text))
                self.assertEqual(widget.text().replace("&&", "&"), text)
                self.assertEqual(widget.accessibleName(), text, "접근 이름은 별명 그대로")
        counted = UI.FilterChip("A&B", 3, True)
        self.assertEqual((counted.text(), counted.accessibleName()), ("A&&B · 3", "A&B 3"))

    def test_a_badge_shows_markup_in_a_name_as_typed(self):
        from PySide6.QtCore import Qt
        from chanceblog_desktop.ui.qt import components as UI
        badge = UI.Badge("info", "<b>x</b> &lt;")
        self.assertEqual((badge.textFormat(), badge.text(), badge.accessibleName()), (Qt.PlainText, "<b>x</b> &lt;", "<b>x</b> &lt;"))

    def test_the_seed_drawer_chips_and_the_home_drawer_show_such_names_as_typed(self):
        window = self.make()
        self.names()
        window.render()
        self.settle()
        window.seed_open_new()
        self.settle(8)
        self.dui(window).fields["scope"].chips["common"].click()
        self.settle(8)
        fields = self.dui(window).fields
        for name in ("scope", "allowed_channels"):
            for code, alias in self.NAMES.items():
                chip = fields[name].chips[code]
                self.assertTrue(chip.shortcut().isEmpty(), (name, code))
                self.assertEqual(chip.text().replace("&&", "&"), alias, (name, code))
                self.assertIn(alias, chip.accessibleName())
        window.close_drawer()
        window.go("home")
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        self.settle()
        window.open_drawer("rA1")
        self.settle(8)
        body = window.drawer.scroll.widget()
        draft = next(button for button in body.findChildren(QAbstractButton) if button.text().endswith(" 초안"))
        self.assertTrue(draft.shortcut().isEmpty())
        self.assertEqual((draft.text().replace("&&", "&"), draft.accessibleName()), ("A&B 블로그 초안", "A&B 블로그 초안"))
        badge = next(widget for widget in body.findChildren(QWidget) if widget.property("badge") == "info")
        self.assertEqual(badge.text(), "A&B 블로그")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class CandidateDetailTest(CandidatesBase):
    """검증 S3-8: 주제 후보 화면의 상세(창 폭 1366 이상이면 오른쪽에 붙는 고정 창, 그보다 좁으면 서랍)도 30자 별명에서 넘치지 않는다 — 채널 이름 줄은 줄임표 라벨이고 정보 줄은 줄바꿈 라벨이라 줄이지 않아도 안쪽 폭 안이다(이 시험이 그것을 못박는다)."""

    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def test_the_candidate_detail_pane_and_the_candidate_drawer_stay_inside_their_width_for_thirty_character_aliases(self):
        for size, holder_name in (((1600, 960), "detail_pane"), ((1100, 700), "drawer")):
            window = self.make(size=size)
            cn.use(cn.labels({"naver_a": (LONG30, True), "naver_b": (LONG30_B, True), "blogger_ko": (LONG30, True), "blogger_en": ("", False), "github_pages": ("", False)}))
            window.render()
            self.settle()
            for part in ("예시 후보 가", "예시 후보 카", "예시 후보 타"):                                  # 네이버·Blogger·GitHub Pages 의 후보
                self.open_card(window, self.id_of(window, part))
                self.settle(10)
                holder = getattr(window, holder_name)
                self.assertTrue(holder.isVisible() if holder_name == "detail_pane" else holder.is_open, (size, part))
                assert_content_fits(self, holder, f"후보 상세 {holder_name} {size} {part}")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ChipValuesTest(Base):
    """검증 S3-2(a): 칩을 누르면 **값(열쇠)** 이 나가고 보이는 글(별명)이 나가지 않는다 — 별명이 값으로 새면 저장되는 허용 채널·소속이 망가진다. 눌림 신호를 직접 받아 본다."""

    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def test_the_multi_chips_of_a_seed_send_the_channel_keys_and_the_single_choice_chips_send_the_scope_key(self):
        window = self.make()
        cn.use(cn.labels({"naver_a": ("맛집 블로그", True), "naver_b": (LONG30_B, True)}))
        window.render()
        self.settle()
        window.seed_open_new()
        self.settle(8)
        fields = self.dui(window).fields
        sent = []
        fields["scope"].edited.connect(lambda name, value: sent.append(("edited", name, value)))
        fields["scope"].chips["common"].click()                                                     # 공통을 고르면 허용 채널 칩이 나타난다
        self.settle(8)
        fields = self.dui(window).fields
        fields["allowed_channels"].toggled_choice.connect(lambda name, value: sent.append(("toggled", name, value)))
        fields["allowed_channels"].chips["naver_a"].click()
        fields["allowed_channels"].chips["naver_b"].click()
        self.settle(4)
        self.assertEqual(sent, [("edited", "scope", "common"), ("toggled", "allowed_channels", "naver_a"), ("toggled", "allowed_channels", "naver_b")], "눌림이 내보낸 것은 열쇠다 — 보이는 글(별명)이 아니다")
        self.assertEqual(fields["allowed_channels"].chips["naver_a"].text(), "맛집 블로그", "보이는 글은 별명이다")

    def test_the_multi_chips_of_the_blog_form_send_the_tag_keys_not_the_shown_words(self):
        from chanceblog_desktop.ui.core import blogs as blogs_core
        from chanceblog_desktop.ui.core import services as services_core
        from chanceblog_desktop.ui.qt import shell as shell_module
        window = shell_module.AppShell(services_core.FakeHomeProvider(), blogs=blogs_core.FakeBlogsProvider(), autoload=False)
        window.resize(1366, 768)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        window.go("blogs")
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state != "loading" and not window.state.blogs.loading, 10)
        self.settle()
        view = window.screen_widget.blogs_ui.fields["monetization_focus"]
        sent = []
        view.toggled_choice.connect(lambda name, value: sent.append((name, value)))
        key, chip = next((key, chip) for key, chip in view.chips.items() if key != chip.text())
        chip.click()
        self.assertEqual(sent, [("monetization_focus", key)], "눌림이 내보낸 것은 값(열쇠)이다 — 보이는 글이 아니다")
        self.assertNotEqual(key, chip.text())


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class LateNameReadTest(Base):
    """검증 S2-6: 시작 직후 늦게 도착한 이름 읽기가 Seed 서랍에 입력 중인 칸을 다시 만들면 커서·한글 조합이 끊긴다 — 입력이 든 서랍은 다시 그리지 않고 이름은 다음에 그릴 때 바뀐다. 입력이 없는 서랍은 바로 새 이름으로 다시 그린다."""

    def tearDown(self):
        cn.use(None)
        super().tearDown()

    def read_names(self, window):
        provider = window.state.blogs.provider
        window.state.blogs.apply_loaded(provider.load_blogs(lambda *a: None, lambda: False))
        window._names_changed()
        self.settle(6)

    def test_a_late_name_read_does_not_rebuild_a_seed_drawer_that_holds_typed_input(self):
        window = self.make()
        window.seed_open_new()
        self.settle(8)
        self.type_into(window, "keyword", "시험 낱말")
        edit = self.dui(window).fields["keyword"].edit
        self.read_names(window)
        self.assertEqual(cn.label("naver_a"), "예시 별명", "이름은 바뀌었다")
        self.assertIs(self.dui(window).fields["keyword"].edit, edit, "입력 중인 서랍의 칸을 다시 만들지 않는다")
        self.assertEqual(edit.text(), "시험 낱말")

    def test_a_late_name_read_redraws_a_seed_drawer_that_holds_no_input_so_it_shows_the_new_names(self):
        window = self.make()
        window.seed_open_new()
        self.settle(8)
        before = self.dui(window).fields["scope"].chips["naver_a"].text()
        self.assertEqual(before, "네이버 블로그 1")
        self.read_names(window)
        self.assertEqual(self.dui(window).fields["scope"].chips["naver_a"].text(), "예시 별명", "입력이 없으면 바로 새 이름으로 다시 그린다")

    def test_a_late_name_read_does_not_rebuild_the_detail_drawer_of_a_seed_with_an_edit(self):
        window = self.make()
        self.open_row(window, "EX011")
        self.type_into(window, "reason", "고친 이유")
        edit = self.dui(window).fields["reason"].edit
        self.read_names(window)
        self.assertEqual(cn.label("naver_a"), "예시 별명")
        self.assertIs(self.dui(window).fields["reason"].edit, edit)
        self.assertEqual(edit.text(), "고친 이유")


if __name__ == "__main__":
    unittest.main()
