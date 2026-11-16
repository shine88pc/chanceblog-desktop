"""블로그 관리 화면의 **'블로그 추가' 흐름과 보기 고르기**(blogsel — D-493 부터)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 실제로 화면을 만들어 '블로그 추가' 카드·종류 고르기·새 블로그 폼·제안 칩·보기 칩·제안 문장·읽기 전용 이미지 칸·키보드·배치를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_blog_options`·`test_ui_blogs_add`). 사용자의 클립보드·보관소·데이터 폴더·설정 파일은 건드리지 않는다(가짜 공급자·임시 폴더의 실제 서비스). 옛 시험의 바탕(`Base`)을 그대로 쓴다.

지키는 것:
  1) 등록한 블로그만 카드로 보이고 맨 끝에 '블로그 추가' 카드(점선·키보드·접근 이름)가 있다. 누르면 종류 고르기(네이버·Blogger·GitHub Pages 카드)가 폼 자리에 열리고 자리가 없는 종류는 눌러도 아무 일이 없으며 이유가 글로 보인다. 등록한 블로그가 없으면 처음부터 열려 있다.
  2) 종류를 고르면 새 블로그 폼이 열린다: 이름 칸은 비어 있고 별명은 제안해 넣었으며 처음 포커스는 이름 칸이고 행동 줄은 저장·취소뿐이다. 카드에는 '등록 전' 으로 보인다. 취소하면 카드가 사라진다.
  3) 화면의 어떤 글(보이는 글·접근 이름·툴팁)에도 슬롯 이름(`네이버 A`·`Blogger 한글` …)이 없다.
  4) 낱말 칸은 제안 칩이 먼저이고 직접 추가 칸이 아래 있다 — 칩은 눌러서도 Space 로도 켜고 끄며 한도·겹침으로 못 고르는 칩은 꺼져 있고 이유가 보인다. 보기 칸은 보기 칩과 '직접 입력' 이고 입력 칸은 직접 입력일 때만 보이며, 별명·소개글은 제안 문장과 '쓰기' 단추가 있다.
  5) 이미지 칸은 쓰는 칸이 아니라 읽기 전용이고 고르기·지우기 단추로만 바뀐다. 6) 새 부품도 키보드(Tab·Enter·Space)·접근 이름·36px 이상 누르는 칸을 지키고, 여섯 크기에서 글자 잘림·눌림·가로 스크롤이 없으며 아래 고정 행동 줄이 창 안에 있다.
  7) 종류 고르기·칩·보기·제안·취소는 **파일에 닿지 않는다**(임시 폴더 전체 바이트).
"""
import dataclasses
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.ui import blogs_adapter  # noqa: E402
from chanceblog_desktop.ui.core import blog_form as bf  # noqa: E402
from chanceblog_desktop.ui.core import blog_options as bo  # noqa: E402
from chanceblog_desktop.ui.core import blogs, text, tokens  # noqa: E402

import service_support as support  # noqa: E402
from test_ui_qt_blogs import HAVE, PICKED, SIZES, Base  # noqa: E402,I001

if HAVE:
    import ui_offscreen
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget
    from chanceblog_desktop.ui.qt import blog_parts, blog_screen
    from chanceblog_desktop.ui.qt import components as UI

T = text.T
SLOT_NAME = re.compile(r"네이버 [AB]\b|Blogger (?:한글|영문)|naver_[ab]|blogger_(?:ko|en)|github_pages")


def screen_texts(root):
    """화면(또는 창) 안의 모든 글 — 보이는 글·접근 이름·접근 설명·툴팁."""
    found = []
    for widget in [root, *root.findChildren(QWidget)]:
        for getter in ("accessibleName", "accessibleDescription", "toolTip"):
            value = getattr(widget, getter)()
            if value:
                found.append(value)
        if isinstance(widget, (QLabel, QAbstractButton)) and widget.text():
            found.append(widget.text())
        if isinstance(widget, UI.Label):
            found.append(widget.plain_text())
        if hasattr(widget, "placeholderText") and widget.placeholderText():
            found.append(widget.placeholderText())
    return found


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class PickerTest(Base):
    def test_the_add_card_is_the_last_card_with_a_name_and_pressing_it_opens_the_kind_picker_in_place_of_the_form(self):
        window = self.make()
        ui = self.ui(window)
        add = ui.add_card
        self.assertIsInstance(add, blog_parts.AddCard)
        self.assertEqual((add.accessibleName(), add.property("addcard"), add.focusPolicy()), (T["blogs_add_a11y"], "true", Qt.StrongFocus))
        self.assertGreaterEqual(add.height(), tokens.SIZE["hit"])
        self.assertEqual(sorted(ui.cards), ["blogger_ko", "naver_a", "naver_b"], "등록한 블로그만 카드다")
        bottoms = [card.mapTo(window, card.rect().bottomLeft()).y() for card in ui.cards.values()]
        self.assertGreater(add.mapTo(window, add.rect().topLeft()).y(), max(bottoms) - 1, "'블로그 추가' 카드는 맨 끝이다")
        self.assertEqual({label.text() for label in add.findChildren(UI.ElidedLabel)}, {"블로그 추가", "연결할 사이트를 골라요."})
        self.assertFalse(add.property("selected"))
        self.assertEqual(ui.kind_cards, {})
        add.activated.emit()
        self.settle()
        ui = self.ui(window)
        self.assertTrue(window.state.blogs.picking)
        self.assertEqual(list(ui.kind_cards), ["naver", "blogger", "github"])
        self.assertEqual(ui.fields, {}, "종류 고르기가 열려 있으면 폼 칸이 없다")
        self.assertTrue(ui.add_card.property("selected"))
        self.assertFalse(any(card.property("selected") for card in ui.cards.values()))
        labels = {label.plain_text() for label in window.screen_widget.findChildren(UI.Label)}
        for part in (T["blogs_pick_title"], "네이버 블로그", "Blogger", "GitHub Pages", "연결 2개 · 남은 자리 0개", "연결 1개 · 남은 자리 1개", "연결 0개 · 남은 자리 1개", T["blogs_pick_full"]):
            self.assertIn(part, labels, part)
        for card in ui.kind_cards.values():
            self.assertEqual(card.focusPolicy(), Qt.StrongFocus)
            self.assertGreaterEqual(card.height(), tokens.SIZE["hit"])
        self.assertIn("더 연결할 수 없음", ui.kind_cards["naver"].accessibleName())
        self.assertTrue(ui.kind_cards["naver"].property("kindfull"))
        self.assertFalse(ui.kind_cards["blogger"].property("kindfull"))

    def test_a_full_kind_does_nothing_when_pressed_and_a_free_kind_opens_the_new_blog_form(self):
        window = self.make()
        window.blog_add_open()
        self.settle()
        calls = list(window.state.blogs.provider.calls)
        screen = window.screen_widget
        full = self.ui(window).kind_cards["naver"]
        chosen = []
        full.chosen.connect(chosen.append)
        full.activated.emit()
        self.settle()
        self.assertEqual(chosen, [], "자리가 없는 종류 카드는 '고른 종류' 신호를 내지 않는다 — 셸에 닿기 전에 카드가 먼저 막는다")
        self.assertIs(window.screen_widget, screen, "자리가 없는 종류를 눌러도 화면이 바뀌지 않는다")
        self.assertTrue(window.state.blogs.picking)
        self.assertEqual(window.state.blogs.listed_keys(), ("blogger_ko", "naver_a", "naver_b"))
        QTest.keyClick(self.ui(window).kind_cards["naver"], Qt.Key_Return)
        self.assertTrue(window.state.blogs.picking)
        self.assertEqual(chosen, [], "키보드로 눌러도 같다")
        self.ui(window).kind_cards["blogger"].activated.emit()
        self.settle()
        self.assertFalse(window.state.blogs.picking)
        self.assertEqual(window.state.blogs.selected, "blogger_en")
        self.assertEqual(sorted(self.ui(window).cards), ["blogger_en", "blogger_ko", "naver_a", "naver_b"])
        self.assertEqual(window.state.blogs.provider.calls, calls, "종류 고르기·새 블로그 열기는 파일에 닿지 않는다")

    def test_with_no_registered_blog_the_picker_is_open_from_the_start_and_cannot_be_closed(self):
        window = self.make(blogs.FakeBlogsProvider("empty"))
        ui = self.ui(window)
        self.assertEqual((ui.cards, ui.fields), ({}, {}))
        self.assertEqual(list(ui.kind_cards), ["naver", "blogger", "github"])
        self.assertTrue(ui.add_card.property("selected"))
        buttons = {button.text() for button in window.screen_widget.findChildren(QAbstractButton)}
        self.assertNotIn(T["blogs_pick_close"], buttons, "돌아갈 카드가 없으면 닫기 단추가 없다")
        self.assertEqual(window.screen_widget.findChildren(blog_parts.NoticeBar), [], "예시 데이터에는 파일 안내가 없다")

    def test_the_close_button_returns_to_the_form_of_the_selected_card(self):
        window = self.make()
        window.blog_select("naver_b")
        self.settle()
        window.blog_add_open()
        self.settle()
        close = next(button for button in window.screen_widget.findChildren(QAbstractButton) if button.text() == T["blogs_pick_close"])
        close.click()
        self.settle()
        self.assertFalse(window.state.blogs.picking)
        self.assertEqual(window.state.blogs.selected, "naver_b")
        self.assertIn("alias", self.ui(window).fields)
        self.assertTrue(self.ui(window).cards["naver_b"].property("selected"))

    def test_the_add_card_and_the_kind_cards_work_with_enter_and_space_and_are_tab_stops(self):
        window = self.make()
        add = self.ui(window).add_card
        self.focus(add)
        QTest.keyClick(add, Qt.Key_Space)
        self.settle()
        self.assertTrue(window.state.blogs.picking)
        start = window.nav_buttons["blogs"]
        self.focus(start)
        seen, current = [], start
        for _ in range(200):
            seen.append(current)
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            if current is start:
                break
        else:
            self.fail("Tab 이 한 바퀴를 돌지 못했다")
        stops = {id(widget) for widget in seen}
        ui = self.ui(window)
        self.assertIn(id(ui.add_card), stops)
        for kind, card in ui.kind_cards.items():
            self.assertIn(id(card), stops, f"{kind}: 막힌 종류도 이유를 읽을 수 있게 Tab 정거장이다")
        self.assertTrue(all(widget.accessibleName().strip() for widget in seen))
        focused = ui.kind_cards["github"]
        self.focus(focused)
        QTest.keyClick(focused, Qt.Key_Return)
        self.settle()
        self.assertEqual(window.state.blogs.selected, "github_pages")
        self.assertIs(window.focusWidget(), self.ui(window).fields["display_name"].edit, "새 블로그 폼이 열리면 처음 포커스는 이름 칸이다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class NewBlogFormTest(Base):
    def open_new(self, window, kind="naver"):
        window.blog_add_open()
        self.settle()
        window.blog_add_kind(kind)
        self.settle()
        return self.ui(window)

    def test_the_new_blog_form_has_a_blank_name_a_suggested_alias_the_focus_on_the_name_and_only_save_and_cancel(self):
        window = self.make(blogs.FakeBlogsProvider("empty"))
        ui = self.open_new(window)
        self.assertEqual((ui.fields["display_name"].edit.text(), ui.fields["alias"].edit.text(), ui.fields["blog_ref"].edit.text()), ("", "네이버 블로그 1", ""))
        self.assertIs(window.focusWidget(), ui.fields["display_name"].edit)
        self.assertEqual([spec["key"] for spec in ui.bar.specs], ["save", "revert"])
        self.assertEqual([button.text() for button in ui.bar.buttons], ["저장", "취소"])
        self.assertTrue(all(button.isEnabled() for button in ui.bar.buttons))
        labels = {label.plain_text() for label in window.screen_widget.findChildren(UI.Label)}
        for part in ("네이버 블로그 새로 연결하기", T["blogs_form_new_desc"], "기본 정보"):
            self.assertIn(part, labels, part)
        self.assertEqual(list(ui.cards), ["naver_a"])
        card = ui.cards["naver_a"]
        texts = {label.text() for label in card.findChildren(UI.ElidedLabel)} | {label.text() for label in card.findChildren(QLabel)}
        for part in ("새 블로그", "네이버 블로그 1", "등록 전"):
            self.assertIn(part, texts, part)
        self.assertTrue(card.property("selected"))
        self.assertIn("등록 전", card.accessibleName())
        self.assertIsNotNone(ui.unsaved)
        self.assertFalse(ui.unsaved.isVisibleTo(window), "새로 연결하는 중에는 '저장 전 변경' 배지를 따로 붙이지 않는다(등록 전)")

    def test_cancel_removes_the_new_card_and_goes_back_to_the_picker_when_nothing_is_registered(self):
        window = self.make(blogs.FakeBlogsProvider("empty"))
        self.open_new(window)
        self.type_into(window, "display_name", "임시 이름")
        self.action(window, "revert").click()
        self.settle()
        ui = self.ui(window)
        self.assertEqual((ui.cards, ui.fields, list(ui.kind_cards)), ({}, {}, ["naver", "blogger", "github"]))
        window2 = self.make()
        ui2 = self.open_new(window2, "github")
        self.assertEqual(sorted(ui2.cards), ["blogger_ko", "github_pages", "naver_a", "naver_b"])
        self.action(window2, "revert").click()
        self.settle()
        self.assertEqual(sorted(self.ui(window2).cards), ["blogger_ko", "naver_a", "naver_b"])
        self.assertEqual(window2.state.blogs.selected, "naver_a", "의도적 갱신(blogsel 수정 1, D-493 ④ — 검증 Q-2): 취소하면 슬롯 순서의 첫 카드(blogger_ko)가 아니라 새 블로그를 열기 전에 폼에 열려 있던 카드로 돌아간다")

    def test_saving_a_new_blog_needs_the_name_and_the_address_then_the_card_becomes_a_registered_one(self):
        provider = blogs.FakeBlogsProvider("empty")
        window = self.make(provider)
        self.open_new(window)
        calls = list(provider.calls)
        self.action(window, "save").click()
        self.settle()
        self.assertEqual(provider.calls, calls, "필수 칸이 비어 있으면 서비스를 부르지 않는다")
        self.assertEqual((self.field_error(window, "display_name"), self.field_error(window, "blog_ref")), (T["bf_err_required"], T["bf_err_required"]))
        self.assertIs(window.focusWidget(), self.ui(window).fields["display_name"].edit, "첫 문제 칸으로 포커스가 간다")
        self.type_into(window, "display_name", "예시 블로그 가")
        self.type_into(window, "blog_ref", "example-blog-a")
        self.action(window, "save").click()
        self.wait_write(window)
        self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
        ui = self.ui(window)
        card = ui.cards["naver_a"]
        texts = {label.text() for label in card.findChildren(UI.ElidedLabel)} | {label.text() for label in card.findChildren(QLabel)}
        for part in ("예시 블로그 가", "등록됨", "네이버 블로그 1"):
            self.assertIn(part, texts, part)
        self.assertEqual([spec["key"] for spec in ui.bar.specs], ["save", "revert", "clone", "delete"], "저장하면 보통 블로그의 폼이 된다")
        self.assertEqual(provider.slots["naver_a"].alias, "네이버 블로그 1")

    def test_no_text_on_the_screen_names_a_slot_in_any_state(self):
        window = self.make()
        every = list(screen_texts(window.screen_widget))
        window.blog_add_open()
        self.settle()
        every += screen_texts(window.screen_widget)
        window.blog_add_kind("github")
        self.settle()
        every += screen_texts(window.screen_widget)
        window.blog_select("blogger_ko")
        self.settle()
        every += screen_texts(window.screen_widget)
        self.action(window, "delete").click()
        self.settle()
        every += screen_texts(window.dialog)
        window.escape()
        self.settle()
        self.assertGreater(len(every), 250)
        for item in every:
            self.assertNotRegex(item, SLOT_NAME, item)
        empty = self.make(blogs.FakeBlogsProvider("empty"))
        for item in screen_texts(empty.screen_widget):
            self.assertNotRegex(item, SLOT_NAME, item)

    def test_no_text_names_a_slot_for_a_blog_saved_by_the_old_screen_with_the_default_name_nor_for_a_slot_with_only_an_alias(self):
        """의도적 넓힘(blogsel 수정 1, 검증 S-2·Q-8): ① 옛 화면에서 이름 칸을 안 고치고(기본값이 미리 들어 있었다) 등록한 파일 — 서비스로 같은 상태를 만든다 ② 손으로 고친 파일의 주소 없이 별명만 있는 슬롯.
        두 상태 모두 카드·접근 이름·툴팁·삭제 확인창 어디에도 슬롯 이름이 없다(이름 입력 칸의 저장된 값은 사용자 자료라 훑는 글이 아니다)."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            for key in bf.SLOTS:
                bp.save_slot(ctx, key, {"display_name": bf.default_values(key)["display_name"], "blog_ref": "example-old-blog"}, expected_version=bp.read_snapshot(ctx).version)
            window = self.make(blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx))
            self.assertEqual(sorted(self.ui(window).cards), sorted(bf.SLOTS))
            every = list(screen_texts(window.screen_widget))
            for key in self.ui(window).cards:
                window.blog_select(key)
                self.settle()
                self.action(window, "delete").click()
                self.settle()
                every += screen_texts(window.dialog)
                window.escape()
                self.settle()
            kinds = {card.property("slot") for card in self.ui(window).cards.values()}
            self.assertEqual(kinds, {"true"})
            self.assertGreater(len(every), 200)
            for item in every:
                self.assertNotRegex(item, SLOT_NAME, item)
        provider = blogs.FakeBlogsProvider("empty")
        provider.slots["naver_b"] = dataclasses.replace(provider.slots["naver_b"], alias="손으로 쓴 별명")
        window = self.make(provider)
        every = list(screen_texts(window.screen_widget))
        self.action(window, "delete").click()
        self.settle()
        every += screen_texts(window.dialog)
        window.escape()
        self.settle()
        self.assertEqual(list(self.ui(window).cards), ["naver_b"])
        for item in every:
            self.assertNotRegex(item, SLOT_NAME, item)

    def test_opening_choosing_picking_and_cancelling_write_nothing_with_the_real_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            before = support.tree_snapshot(Path(ctx.workspace.root))
            listing = sorted(str(path) for path in Path(tmp).rglob("*"))
            window = self.make(provider)
            ui = self.open_new(window, "blogger")
            ui.fields["main_topics"].chips["소형가전"].click()
            ui.fields["channel_role"].chips["정보 공유"].click()
            ui.fields["tone"].custom_chip.click()
            self.settle()
            self.ui(window).fields["alias"].edit.setFocus()
            self.action(window, "revert").click()
            self.settle()
            window.go("home")
            window.go("blogs")
            ui_offscreen.wait_until(self.app, lambda: not window.state.blogs.loading, 10)
            self.settle()
            self.assertEqual(support.tree_snapshot(Path(ctx.workspace.root)), before)
            self.assertEqual(sorted(str(path) for path in Path(tmp).rglob("*")), listing, "파일도 폴더도 만들지 않는다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ChipsTest(Base):
    def test_the_word_fields_show_suggestion_chips_first_and_the_direct_add_box_below_them(self):
        window = self.make()
        fields = self.ui(window).fields
        for name in ("main_topics", "categories", "priority_keywords", "exclude_keywords"):
            view = fields[name]
            self.assertEqual((view.kind, list(view.chips)), ("words", list(bo.WORD_SUGGESTIONS[name])), name)
            self.assertIs(view.controls[0], view.edit, "첫 문제 칸 포커스는 입력 칸이다")
            self.assertEqual(len(view.controls), 1 + len(view.chips))
            first = next(iter(view.chips.values()))
            self.assertLess(first.mapTo(window, first.rect().topLeft()).y(), view.edit.mapTo(window, view.edit.rect().topLeft()).y(), f"{name}: 제안 칩이 입력 칸보다 위에 있다")
            self.assertEqual(view.edit.placeholderText(), T["bf_placeholder_words"])
            for word, chip in view.chips.items():
                self.assertEqual((chip.text(), chip.accessibleName()), (word, f"{view.label.plain_text()}: {word}"))
                self.assertGreaterEqual(chip.height(), tokens.SIZE["hit"], word)
            self.assertIn("제안에서 골라요", view.hint.plain_text(), name)
        self.assertEqual(sorted(word for word, chip in fields["priority_keywords"].chips.items() if chip.isChecked()), [], "손으로 쓴 낱말은 제안에 없어 칩이 켜지지 않는다")
        self.assertEqual(fields["priority_keywords"].edit.text(), "예시 키워드 하나, 예시 키워드 둘", "직접 쓴 낱말은 입력 칸에 그대로 있다")

    def test_a_chip_adds_and_removes_a_word_by_click_and_by_keyboard_and_keeps_the_typed_words(self):
        window = self.make()
        screen, view = window.screen_widget, self.ui(window).fields["main_topics"]
        view.chips["소형가전"].click()
        self.settle()
        self.assertIs(window.screen_widget, screen, "고치는 동안 화면을 다시 그리지 않는다")
        self.assertEqual(view.edit.text(), "예시 주제 하나, 예시 주제 둘, 예시 주제 셋, 소형가전")
        self.assertTrue(view.chips["소형가전"].isChecked())
        self.assertTrue(self.action(window, "save").isEnabled())
        chip = view.chips["PC 주변기기"]
        chip.setFocus(Qt.TabFocusReason)
        QTest.keyClick(chip, Qt.Key_Space)
        self.settle()
        self.assertEqual(window.state.blogs.values("naver_a")["main_topics"], "예시 주제 하나, 예시 주제 둘, 예시 주제 셋, 소형가전, PC 주변기기")
        view.chips["소형가전"].click()
        view.chips["PC 주변기기"].click()
        self.settle()
        self.assertEqual((view.edit.text(), view.chips["소형가전"].isChecked(), self.action(window, "save").isEnabled()), ("예시 주제 하나, 예시 주제 둘, 예시 주제 셋", False, False), "켰다 끄면 저장된 값으로 돌아간다")
        self.type_into(window, "main_topics", "소형가전, 새 낱말")
        self.assertTrue(view.chips["소형가전"].isChecked(), "직접 쓴 글에 제안 낱말이 있으면 칩도 켜진다")
        self.assertEqual(window.state.blogs.values("naver_a")["main_topics"], "소형가전, 새 낱말")

    def test_chips_stop_at_the_limit_with_the_reason_and_the_keyword_chips_of_the_other_field_are_off(self):
        window = self.make(blogs.FakeBlogsProvider("empty"))
        window.blog_add_open()
        window.blog_add_kind("naver")
        self.settle()
        fields = self.ui(window).fields
        for word in bo.TOPIC_WORDS[:10]:
            fields["main_topics"].chips[word].click()
        self.settle()
        view = self.ui(window).fields["main_topics"]
        off = [word for word, chip in view.chips.items() if not chip.isEnabled()]
        self.assertEqual(off, [word for word in bo.TOPIC_WORDS if word not in bo.TOPIC_WORDS[:10]])
        self.assertEqual(view.chips[off[0]].toolTip(), T["bf_chip_full"])
        self.assertEqual(view.chips[off[0]].accessibleDescription(), T["bf_chip_full"])
        self.assertTrue(view.extra.isVisibleTo(window))
        self.assertEqual(view.extra.plain_text(), T["bf_note_full"].format(count=10))
        self.assertTrue(all(view.chips[word].isEnabled() for word in bo.TOPIC_WORDS[:10]), "고른 칩은 끌 수 있다")
        fields["priority_keywords"].chips["소형가전"].click()
        self.settle()
        other = self.ui(window).fields["exclude_keywords"].chips["소형가전"]
        self.assertFalse(other.isEnabled())
        self.assertEqual(other.toolTip(), T["bf_chip_other"])
        self.assertTrue(self.ui(window).fields["exclude_keywords"].chips["PC 주변기기"].isEnabled())
        self.assertEqual(window.state.blogs.problems(window.state.blogs.selected).get("priority_keywords"), None)

    def test_a_refused_chip_click_is_put_back_to_the_screens_state(self):
        window = self.make()
        view = self.ui(window).fields["main_topics"]
        chip = view.chips["소형가전"]
        with mock.patch.object(type(window.state.blogs), "toggle_choice", lambda *a: False):
            chip.setEnabled(True)
            chip.click()
            self.settle()
        self.assertFalse(chip.isChecked(), "모델이 거절하면 칩 표시도 되돌아간다")

    def test_the_choice_chips_pick_one_clear_it_again_and_show_the_text_box_only_for_direct_input(self):
        window = self.make(blogs.FakeBlogsProvider("empty"))
        window.blog_add_open()
        window.blog_add_kind("naver")
        self.settle()
        view = self.ui(window).fields["tone"]
        self.assertEqual(list(view.chips), list(bo.TONE_CHOICES))
        self.assertIsNotNone(view.custom_chip)
        self.assertEqual((view.custom_chip.text(), view.custom_chip.accessibleName()), ("직접 입력", "문체 직접 입력"))
        self.assertFalse(view.edit.isVisibleTo(window), "직접 입력이 아니면 입력 칸이 없다")
        self.assertEqual(view.edit.placeholderText(), T["bf_input_custom"])
        view.chips["친근한 말투"].click()
        self.settle()
        self.assertEqual(window.state.blogs.values(window.state.blogs.selected)["tone"], "친근한 말투")
        self.assertTrue(view.chips["친근한 말투"].isChecked() and not view.custom_chip.isChecked())
        view.chips["정중한 설명체"].click()
        self.settle()
        self.assertEqual((view.chips["친근한 말투"].isChecked(), view.chips["정중한 설명체"].isChecked()), (False, True), "하나만 고른다")
        view.chips["정중한 설명체"].click()
        self.settle()
        self.assertEqual((window.state.blogs.values(window.state.blogs.selected)["tone"], view.chips["정중한 설명체"].isChecked()), ("", False), "고른 보기를 다시 누르면 비워진다")
        view.custom_chip.click()
        self.settle()
        self.assertTrue(view.edit.isVisibleTo(window))
        self.assertTrue(view.custom_chip.isChecked())
        self.assertIs(window.focusWidget(), view.edit, "직접 입력을 누르면 입력 칸에 포커스가 간다")
        view.custom_chip.click()                                                                  # 이미 눌린 칩을 다시 누르면 Qt 가 먼저 풀어 놓는다 — 화면이 모델(직접 입력 중)에 다시 맞춘다
        self.settle()
        self.assertTrue(view.custom_chip.isChecked() and view.edit.isVisibleTo(window), "이미 눌린 '직접 입력' 을 다시 눌러도 그대로다")
        self.type_into(window, "tone", "나만의 말투")
        self.assertEqual(window.state.blogs.values(window.state.blogs.selected)["tone"], "나만의 말투")
        self.assertTrue(view.custom_chip.isChecked() and not any(chip.isChecked() for chip in view.chips.values()))
        self.type_into(window, "tone", "간결한 정보체")
        self.assertTrue(view.edit.isVisibleTo(window), "직접 친 글이 보기와 같아져도 입력 칸은 그대로 있다")
        view.chips["간결한 정보체"].click()
        self.settle()
        self.assertFalse(view.edit.isVisibleTo(window))
        self.assertTrue(view.chips["간결한 정보체"].isChecked())

    def test_a_stored_value_outside_the_choices_shows_in_the_text_box_and_survives_looking(self):
        window = self.make()
        view = self.ui(window).fields["tone"]
        self.assertTrue(view.edit.isVisibleTo(window))
        self.assertEqual(view.edit.text(), "친절한 설명체")
        self.assertTrue(view.custom_chip.isChecked())
        self.assertFalse(any(chip.isChecked() for chip in view.chips.values()))
        self.assertFalse(window.state.blogs.is_dirty("naver_a"))
        view.chips["친근한 말투"].click()
        self.settle()
        self.action(window, "revert").click()
        self.settle()
        view = self.ui(window).fields["tone"]
        self.assertEqual((view.edit.text(), view.edit.isVisibleTo(window)), ("친절한 설명체", True), "되돌리면 손으로 쓴 값이 그대로 돌아온다")

    def test_the_alias_and_intro_show_a_suggestion_with_a_use_button_that_only_fills_the_box(self):
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider)
        window.blog_select("naver_b")
        self.settle()
        fields = self.ui(window).fields
        alias = fields["alias"]
        self.assertTrue(alias.suggest_row.isVisibleTo(window))
        self.assertEqual(alias.suggest_text.plain_text(), "네이버 블로그 2")
        self.assertEqual((alias.suggest_button.text(), alias.suggest_button.accessibleName()), ("쓰기", "별명 제안 쓰기"))
        self.assertGreaterEqual(alias.suggest_button.height(), tokens.SIZE["hit"])
        calls = list(provider.calls)
        alias.suggest_button.click()
        self.settle()
        self.assertEqual(alias.edit.text(), "네이버 블로그 2")
        self.assertFalse(alias.suggest_row.isVisibleTo(window), "이미 그 글이면 제안이 사라진다")
        self.assertEqual(provider.calls, calls, "제안을 쓰는 것은 저장이 아니다")
        self.assertTrue(self.action(window, "save").isEnabled())
        intro = fields["intro"]
        self.assertTrue(intro.suggest_row.isVisibleTo(window), "예시 값(역할·독자·주제)이 있어 소개글 제안이 보인다")
        before = intro.suggest_text.plain_text()
        self.assertIn("블로그예요.", before)
        fields["channel_role"].chips["후기 기록"].click()
        self.settle()
        self.assertEqual(intro.suggest_text.plain_text(), bo.suggest_intro("후기 기록", "예시 독자 둘", "", ("예시 주제 넷",)), "고른 값이 바뀌면 제안도 그 자리에서 바뀐다")
        intro.suggest_button.click()
        self.settle()
        self.assertEqual(intro.edit.text(), window.state.blogs.values("naver_b")["intro"])
        self.assertIn("후기 기록 블로그예요.", intro.edit.text())
        self.assertEqual(provider.calls, calls)

    def test_the_image_fields_are_read_only_boxes_with_pick_and_clear_buttons(self):
        picked = []
        window = self.make(picker=lambda parent, title, filters: (picked.append(title), PICKED)[1])
        fields = self.ui(window).fields
        for name in ("profile_image", "cover_image"):
            view = fields[name]
            self.assertTrue(view.edit.isReadOnly(), name)
            self.assertEqual((view.pick.text(), view.edit.placeholderText()), ("파일 고르기", T["bf_placeholder_path"]))
            self.assertIn("파일 고르기", view.hint.plain_text())
        self.assertFalse(any(fields[name].edit.isReadOnly() for name in fields if name not in ("profile_image", "cover_image") and fields[name].edit is not None), "이미지 칸만 읽기 전용이다")
        fields["cover_image"].pick.click()
        self.settle()
        self.assertEqual((fields["cover_image"].edit.text(), picked), (PICKED, ["커버 이미지 고르기"]))
        self.assertTrue(fields["cover_image"].clear_button.isEnabled())
        QTest.keyClicks(fields["cover_image"].edit, "abc")
        self.assertEqual(fields["cover_image"].edit.text(), PICKED, "위치를 손으로 적을 수 없다")
        fields["cover_image"].clear_button.click()
        self.settle()
        self.assertEqual(fields["cover_image"].edit.text(), "")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class RealServiceAddTest(Base):
    def test_add_two_naver_blogs_from_an_empty_folder_through_the_screen_and_the_file_has_the_chosen_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            window = self.make(provider)
            ui = self.ui(window)
            self.assertEqual((ui.cards, list(ui.kind_cards)), ({}, ["naver", "blogger", "github"]), "처음에는 카드가 없고 종류 고르기가 열려 있다")
            ui.kind_cards["naver"].activated.emit()
            self.settle()
            self.type_into(window, "display_name", "예시 블로그 가")
            self.type_into(window, "blog_ref", "example-blog-a")
            fields = self.ui(window).fields
            fields["channel_role"].chips["정보 공유"].click()
            fields["audience"].chips["대학생"].click()
            fields["tone"].chips["친근한 말투"].click()
            fields["main_topics"].chips["소형가전"].click()
            fields["main_topics"].chips["PC 주변기기"].click()
            fields["priority_keywords"].chips["숙박"].click()
            fields["exclude_keywords"].chips["지역"].click()
            fields["intro"].suggest_button.click()
            fields["color_preset"].chips["warm_lifestyle"].click()
            self.settle()
            self.action(window, "save").click()
            self.wait_write(window)
            self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
            saved = {profile.key: profile for profile in bp.read_snapshot(ctx).profiles}["naver_a"]
            self.assertEqual((saved.display_name, saved.blog_ref, saved.alias, saved.channel_role, saved.audience, saved.tone), ("예시 블로그 가", "example-blog-a", "네이버 블로그 1", "정보 공유", "대학생", "친근한 말투"))
            self.assertEqual((saved.main_topics, saved.priority_keywords, saved.exclude_keywords, saved.color_preset), (("소형가전", "PC 주변기기"), ("숙박",), ("지역",), "warm_lifestyle"))
            self.assertEqual(saved.intro, bo.suggest_intro("정보 공유", "대학생", "친근한 말투", ("소형가전", "PC 주변기기")))
            files = sorted(path.relative_to(ctx.workspace.root).as_posix() for path in Path(ctx.workspace.root).rglob("*") if path.is_file() and path.name != "settings.json")
            self.assertEqual(files, ["topic_engine/channel_profiles.json"])
            window.blog_add_open()
            self.settle()
            self.ui(window).kind_cards["naver"].activated.emit()
            self.settle()
            self.assertEqual(window.state.blogs.selected, "naver_b")
            self.assertEqual(self.ui(window).fields["alias"].edit.text(), "네이버 블로그 2")
            window.blog_add_open()
            self.settle()
            self.assertTrue(self.ui(window).kind_cards["naver"].property("kindfull"), "네이버 자리 둘이 모두 열려 있어(하나는 아직 저장 전) 더 연결할 수 없다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class LayoutTest(Base):
    def test_the_picker_the_new_form_and_the_chip_rows_never_clip_or_squeeze_and_the_save_row_stays_in_the_window_at_every_size(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(size=size)
                window.blog_add_open()
                self.settle(8)
                self.assertEqual(ui_offscreen.find_clipping(window), [], f"{size}: 종류 고르기")
                self.assertEqual(ui_offscreen.find_squeezed(window), [], f"{size}: 종류 고르기")
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)
                if size != (900, 560):
                    self.assertEqual(window.scroll.verticalScrollBar().maximum(), 0, f"{size}: 종류 고르기가 열려도 페이지가 창보다 길지 않다 — 넘치는 높이는 안쪽 스크롤이 받는다")
                window.blog_add_kind("github")
                self.settle(8)
                ui = self.ui(window)
                for name in ("channel_role", "main_topics", "priority_keywords", "intro", "profile_image"):
                    ui.form_scroll.ensureWidgetVisible(ui.fields[name], 0, 12)
                    self.settle(3)
                    self.assertEqual(ui_offscreen.find_clipping(window), [], f"{size}: {name}")
                    self.assertEqual(ui_offscreen.find_squeezed(window), [], f"{size}: {name}")
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{size}: 가로 스크롤이 없다")
                button = self.action(window, "save")
                if size != (900, 560):
                    self.assertLessEqual(button.mapTo(window, button.rect().bottomLeft()).y(), window.height(), f"{size}: 저장 단추가 창 안에 보인다")
                    self.assertEqual(window.scroll.verticalScrollBar().maximum(), 0, f"{size}: 페이지가 창보다 길지 않다")
                add = ui.add_card
                self.assertGreaterEqual(add.mapTo(window, add.rect().topLeft()).x(), 0)
                self.assertLessEqual(add.mapTo(window, add.rect().topRight()).x(), window.width())

    def test_all_chips_open_and_direct_input_boxes_open_never_make_a_horizontal_scroll_or_clip_text(self):
        for size in ((1366, 768), (900, 560)):
            with self.subTest(size=size):
                window = self.make(size=size)
                for name in ("tone", "audience", "channel_role"):
                    window.blog_open_custom(name)
                self.settle(6)
                window.blog_pick_option("channel_role", "정보 공유")
                for word in bo.TOPIC_WORDS[:10]:
                    window.blog_toggle_choice("main_topics", word)
                self.settle(6)
                self.assertEqual(ui_offscreen.find_clipping(window), [], size)
                self.assertEqual(ui_offscreen.find_squeezed(window), [], size)
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)

    def test_a_narrow_window_puts_the_cards_and_the_add_card_above_the_picker(self):
        window = self.make(size=(900, 560))
        body = window.screen_widget.findChild(blog_screen.BlogsBody)
        self.assertFalse(body.beside)
        window.blog_add_open()
        self.settle(6)
        listing, right = body._listing, body._layout.itemAt(1).widget()
        self.assertLessEqual(listing.geometry().bottom(), right.geometry().top() + 1)
        self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)
        ui = self.ui(window)
        self.assertTrue(ui.add_card.isVisibleTo(window))


def mouse(kind, widget, position):
    """위젯 안 `position` 에 보내는 마우스 이벤트(왼쪽 단추) — `QTest.mouseDClick` 은 오프스크린에서 단추를 못 눌러, 더블클릭의 두 번째 눌림을 이벤트로 직접 보낸다."""
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
    return QMouseEvent(kind, position, widget.mapToGlobal(position.toPoint()), Qt.LeftButton, buttons, Qt.NoModifier)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class FocusAndGuardTest(Base):
    """수정 1(검증 S·Q 1차) — 취소·되돌리기·삭제 뒤 포커스, 더블클릭의 두 번째 눌림, 최소 창의 이름 칸, 앱 창 닫기 확인."""

    def focus_key(self):
        widget = QApplication.focusWidget()
        while widget is not None and not widget.property("focus_key"):
            widget = widget.parentWidget()
        return widget.property("focus_key") if widget is not None else None

    def press(self, button, space=True):
        self.focus(button)
        QTest.keyClick(button, Qt.Key_Space if space else Qt.Key_Return)
        self.settle()

    def click_event(self, button, kinds):
        position = QPointF(button.rect().center())
        for kind in kinds:
            QApplication.sendEvent(button, mouse(kind, button, position))
        self.settle()

    def test_cancelling_a_new_blog_and_reverting_a_card_with_the_keyboard_keep_the_focus_on_the_card_not_the_top_menu(self):
        window = self.make()
        self.add_blog(window, "github")
        self.press(self.action(window, "revert"))
        self.assertEqual((window.state.blogs.selected, self.focus_key()), ("naver_a", "slot:naver_a"), "취소 뒤 포커스는 돌아간 카드에 있다 — 맨 위 홈 메뉴로 튀지 않는다")
        self.type_into(window, "alias", "고치는 별명")
        self.assertTrue(window.state.blogs.is_dirty("naver_a"))
        self.press(self.action(window, "revert"))
        self.assertEqual((window.state.blogs.is_dirty("naver_a"), self.focus_key()), (False, "slot:naver_a"), "되돌리기 뒤에도 같다")

    def test_cancelling_the_only_new_form_with_no_card_puts_the_focus_on_the_add_card(self):
        window = self.make(blogs.FakeBlogsProvider("empty"))
        window.blog_add_kind("naver")
        self.settle()
        self.press(self.action(window, "revert"))
        self.assertEqual((window.state.blogs.selected, self.focus_key()), (None, "slot:add"))

    def test_after_deleting_the_last_blog_the_focus_is_on_the_add_card(self):
        window = self.make()
        for _ in range(3):
            self.action(window, "delete").click()
            self.settle()
            next(button for button in window.dialog.findChildren(QAbstractButton) if button.text() == "지우기").click()
            self.wait_write(window)
        self.assertEqual(window.state.blogs.listed_keys(), ())
        self.assertEqual(self.focus_key(), "slot:add", "마지막 블로그를 지우면 카드가 없다 — 포커스는 '블로그 추가' 카드로 간다")

    def test_a_double_click_second_press_never_reaches_the_revert_or_delete_buttons_while_a_normal_click_still_does(self):
        window = self.make()
        window.blog_select("blogger_ko")
        self.settle()
        self.type_into(window, "alias", "고치는 별명")
        self.add_blog(window, "github")
        self.assertEqual(self.action(window, "revert").text(), T["blogs_cancel"])
        self.action(window, "revert").click()                                                      # 더블클릭의 첫 클릭 — 새 블로그가 취소된다
        self.settle()
        self.assertEqual(window.state.blogs.selected, "blogger_ko", "취소하면 열기 전의 카드로 돌아간다")
        revert = self.action(window, "revert")
        self.assertEqual((revert.text(), revert.isEnabled()), (T["blogs_revert"], True), "같은 자리에 그 카드의 '되돌리기' 가 켜져 있다")
        self.click_event(revert, (QEvent.MouseButtonDblClick, QEvent.MouseButtonRelease))        # 더블클릭의 두 번째 눌림과 뗌
        self.assertEqual(window.state.blogs.drafts.get("blogger_ko"), {"alias": "고치는 별명"}, "더블클릭의 두 번째 눌림은 되돌리기를 누르지 않는다 — 그 카드의 입력이 그대로다")
        delete = self.action(window, "delete")
        self.click_event(delete, (QEvent.MouseButtonDblClick, QEvent.MouseButtonRelease))
        self.assertFalse(window.dialog.is_open, "삭제도 더블클릭의 두 번째 눌림으로는 확인창이 열리지 않는다")
        self.click_event(revert, (QEvent.MouseButtonPress, QEvent.MouseButtonRelease))            # 보통 클릭(눌림 + 뗌)은 그대로 된다 — 시험 도구가 단추에 닿는다는 증거
        self.assertEqual(window.state.blogs.drafts.get("blogger_ko"), None, "보통 클릭은 되돌리기를 누른다")
        self.click_event(self.action(window, "delete"), (QEvent.MouseButtonPress, QEvent.MouseButtonRelease))
        self.assertTrue(window.dialog.is_open, "보통 클릭은 삭제 확인창을 연다")

    def test_at_the_smallest_window_the_name_field_of_a_new_blog_is_inside_the_visible_area_right_after_choosing_the_kind(self):
        window = self.make(size=(900, 560))
        window.blog_add_open()
        self.settle()
        window.blog_add_kind("github")
        self.settle(8)
        name = self.ui(window).fields["display_name"].edit
        self.assertIs(QApplication.focusWidget(), name, "처음 포커스는 이름 칸이다")
        viewport = window.scroll.viewport()
        top, bottom = name.mapTo(viewport, name.rect().topLeft()).y(), name.mapTo(viewport, name.rect().bottomLeft()).y()
        self.assertGreaterEqual(top, 0, "이름 칸이 보이는 영역 위로 밀려나지 않는다")
        self.assertLessEqual(bottom, viewport.height(), f"최소 창에서도 이름 칸이 보이는 영역 안이다(칸 아래 {bottom}, 영역 높이 {viewport.height()})")

    def test_closing_the_window_with_an_unsaved_new_blog_form_asks_first_cancel_keeps_the_input_and_close_closes(self):
        window = self.make()
        self.add_blog(window, "github")
        self.type_into(window, "display_name", "입력 중인 이름")
        window.close()
        self.settle()
        self.assertTrue(window.isVisible(), "저장하지 않은 입력이 있으면 닫지 않고 먼저 묻는다")
        self.assertTrue(window.dialog.is_open)
        labels = {label.plain_text() for label in window.dialog.findChildren(UI.Label)}
        self.assertEqual((T["blogs_close_title"] in labels, T["blogs_close_body"] in labels), (True, True))
        buttons = {button.text(): button for button in window.dialog.findChildren(QAbstractButton)}
        self.assertEqual(sorted(buttons), sorted([T["blogs_close_ok"], T["blogs_close_cancel"]]))
        self.assertIs(QApplication.focusWidget(), buttons[T["blogs_close_cancel"]], "처음 포커스는 취소(삭제 확인창과 같은 원칙)")
        for item in screen_texts(window.dialog):
            self.assertNotRegex(item, SLOT_NAME, item)
        buttons[T["blogs_close_cancel"]].click()
        self.settle()
        self.assertEqual((window.isVisible(), window.dialog.is_open), (True, False))
        self.assertEqual(self.ui(window).fields["display_name"].edit.text(), "입력 중인 이름", "취소하면 입력이 그대로다")
        window.close()
        self.settle()
        buttons = {button.text(): button for button in window.dialog.findChildren(QAbstractButton)}
        buttons[T["blogs_close_ok"]].click()
        self.settle()
        self.assertFalse(window.isVisible(), "'닫기' 를 누르면 닫힌다")

    def test_closing_with_no_unsaved_blog_input_never_asks(self):
        window = self.make()
        self.add_blog(window, "github")                                                            # 제안 별명만 들어 있는 새 폼 — 사용자가 친 것이 없다
        window.close()
        self.settle()
        self.assertEqual((window.isVisible(), window.dialog.is_open), (False, False))
        other = self.make()
        other.close()
        self.settle()
        self.assertFalse(other.isVisible(), "고친 것이 없는 창도 바로 닫힌다")

    def test_an_edited_registered_blog_asks_too_and_a_saved_one_does_not(self):
        window = self.make()
        self.type_into(window, "alias", "저장 전 별명")
        window.close()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        window.close_dialog()
        self.settle()
        self.action(window, "save").click()
        self.wait_write(window)
        window.close()
        self.settle()
        self.assertFalse(window.isVisible(), "저장한 뒤에는 묻지 않는다")


if __name__ == "__main__":
    unittest.main()
