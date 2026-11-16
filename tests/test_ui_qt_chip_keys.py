"""블로그 관리 폼의 **칩 묶음 키보드 규칙**(BLOGSEL-2 ② — 검증 Q-1)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 가짜 공급자로, 아무것도 쓰지 않는다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다). 칩이 백여 개라 이름 칸에서 저장 단추까지 Tab 을 백사십 번 가까이 눌러야 하던 것(검증 Q-1 은 134번이라 적었다)을 줄이는 규칙이다.

지키는 것:
  1) 칩이 많은 묶음(낱말 제안 넷·보기 셋·여럿 고르기 둘)은 **묶음 하나가 Tab 정거장 하나**다 — 처음엔 고른 첫 칩(꺼진 칩은 빼고, 없으면 첫 칩)이고 나머지 칩은 마우스로만 포커스를 받는다.
  2) 묶음 안에서는 화살표 키(← ↑ 이전 · → ↓ 다음, 끝에서는 반대 끝으로)·Home·End 로 **옮기기만** 하고(고르지 않는다) 꺼진(못 고르는) 칩은 건너뛴다. 키 조합(Ctrl 등)은 건드리지 않는다.
  3) Tab 으로 묶음을 지나가면 Shift+Tab 으로 마지막에 있던 칩으로 돌아오고, 마우스로 누른 칩이 새 정거장이다. Space·Enter 로 켜고 끄는 것은 그대로이고 정거장은 그대로 남는다.
  4) 쓸 수 있는 칩이 하나도 없으면 정거장도 없고(갇히지 않는다), 정거장이던 칩이 꺼지면 다른 칩으로 옮긴다. 하나만 고르는 묶음(언어·색)은 그대로다(고른 칩만 정거장).
  5) 이름 칸에서 저장 단추까지 Tab 횟수가 크게 줄었다(직접 센 값 140 → 29, 아래 상한 45). 접근 이름은 그대로다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ui_qt_blogs import HAVE, Base  # noqa: E402,I001

if HAVE:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
    from chanceblog_desktop.ui.qt import blog_parts
    from chanceblog_desktop.ui.qt import components as UI

GROUPS = ("main_topics", "categories", "priority_keywords", "exclude_keywords", "channel_role", "audience", "tone", "monetization_focus", "preferred_post_types")
TAB_LIMIT = 45                                                    # 이름 칸에서 저장 단추까지(옛 134) — 지금 값에 여유를 둔 상한


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ChipGroupRuleTest(Base):
    """`ChipGroup` 한 묶음의 규칙 — 칩 여섯 개와 묶음 밖의 단추 하나로 직접 만든 작은 창에서 본다."""

    def build(self, count=6, checked=(), disabled=()):
        box = QWidget()
        layout = QHBoxLayout(box)
        chips = []
        for index in range(count):
            chip = UI.FilterChip(f"칩 {index}", None, index in checked)
            chip.setEnabled(index not in disabled)
            layout.addWidget(chip)
            chips.append(chip)
        after = UI.FilterChip("묶음 밖", None, False)
        layout.addWidget(after)
        group = blog_parts.ChipGroup(chips, box)
        box.show()
        self.addCleanup(box.close)
        self.settle()
        self.activate(box)
        return chips, group, after

    @staticmethod
    def stops(chips):
        return [chip for chip in chips if chip.focusPolicy() == Qt.StrongFocus]

    def test_the_stop_is_the_first_checked_chip_that_is_usable_else_the_first_usable_chip(self):
        chips, group, _ = self.build(checked=(2, 4))
        self.assertEqual((self.stops(chips), group.current), ([chips[2]], chips[2]), "고른 첫 칩")
        self.assertTrue(all(chip.focusPolicy() == Qt.ClickFocus for chip in chips if chip is not chips[2]), "나머지는 마우스로만 포커스를 받는다(NoFocus 가 아니다)")
        chips, group, _ = self.build()
        self.assertEqual(self.stops(chips), [chips[0]], "고른 칩이 없으면 첫 칩")
        chips, group, _ = self.build(checked=(1,), disabled=(1,))
        self.assertEqual(self.stops(chips), [chips[0]], "고른 칩이 꺼져 있으면 쓸 수 있는 첫 칩")
        chips, group, _ = self.build(disabled=(0, 1))
        self.assertEqual(self.stops(chips), [chips[2]], "꺼진 칩은 정거장이 아니다")

    def test_the_arrow_keys_home_and_end_move_the_focus_without_choosing_skip_disabled_chips_and_wrap_at_the_ends(self):
        chips, group, _ = self.build(checked=(1,), disabled=(3,))
        before = [chip.isChecked() for chip in chips]
        self.focus(chips[1])
        path = [(Qt.Key_Right, 2), (Qt.Key_Right, 4), (Qt.Key_Down, 5), (Qt.Key_Right, 0), (Qt.Key_Left, 5), (Qt.Key_Up, 4), (Qt.Key_Left, 2),
                (Qt.Key_Home, 0), (Qt.Key_End, 5), (Qt.Key_Left, 4)]                                  # 꺼진 셋째(3)는 건너뛰고 끝에서는 반대 끝으로
        for key, expected in path:
            QTest.keyClick(QApplication.focusWidget(), key)
            self.settle(1)
            self.assertIs(QApplication.focusWidget(), chips[expected], (key, expected))
            self.assertEqual(self.stops(chips), [chips[expected]], "화살표로 옮긴 칩이 새 정거장이다")
        self.assertEqual([chip.isChecked() for chip in chips], before, "화살표는 옮기기만 한다 — 고르지 않는다")

    def test_a_key_combination_is_left_to_qt(self):
        chips, group, after = self.build()
        self.focus(chips[1])
        QTest.keyClick(chips[1], Qt.Key_Right, Qt.ControlModifier)
        self.settle(1)
        self.assertIsNot(QApplication.focusWidget(), chips[2], "Ctrl+→ 는 이 묶음의 화살표가 아니다")

    def test_tab_leaves_the_group_and_shift_tab_comes_back_to_the_chip_last_used_and_a_click_moves_the_stop(self):
        chips, group, after = self.build(checked=(0,))
        self.focus(chips[0])
        for _ in range(2):
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Right)
        self.settle(1)
        self.assertIs(QApplication.focusWidget(), chips[2])
        chips[2].focusNextChild()
        self.settle(1)
        self.assertIs(QApplication.focusWidget(), after, "Tab 은 묶음을 한 번에 지나간다")
        after.focusPreviousChild()
        self.settle(1)
        self.assertIs(QApplication.focusWidget(), chips[2], "Shift+Tab 은 마지막에 있던 칩으로 돌아온다")
        QTest.mouseClick(chips[4], Qt.LeftButton)
        self.settle(1)
        self.assertEqual((self.stops(chips), chips[4].isChecked()), ([chips[4]], True), "마우스로 누른 칩이 새 정거장이다")

    def test_space_and_enter_still_turn_the_focused_chip_on_and_off_and_the_stop_stays(self):
        chips, group, _ = self.build()
        self.focus(chips[3])
        QTest.keyClick(chips[3], Qt.Key_Space)
        self.settle(1)
        self.assertEqual((chips[3].isChecked(), self.stops(chips)), (True, [chips[3]]))
        QTest.keyClick(chips[3], Qt.Key_Return)
        self.settle(1)
        self.assertEqual((chips[3].isChecked(), self.stops(chips)), (False, [chips[3]]))

    def test_without_a_usable_chip_there_is_no_stop_and_a_stop_that_turns_off_moves_to_another_chip(self):
        chips, group, _ = self.build(checked=(2,))
        self.assertEqual(self.stops(chips), [chips[2]])
        chips[2].setEnabled(False)
        group.refresh()
        self.assertEqual(self.stops(chips), [chips[0]], "정거장이던 칩이 꺼지면 쓸 수 있는 첫 칩으로 옮긴다")
        for chip in chips:
            chip.setEnabled(False)
        group.refresh()
        self.assertEqual((self.stops(chips), group.current), ([], None), "쓸 수 있는 칩이 없으면 정거장도 없다")
        self.assertTrue(all(chip.focusPolicy() == Qt.ClickFocus for chip in chips))
        chips[4].setEnabled(True)
        group.refresh()
        self.assertEqual(self.stops(chips), [chips[4]], "다시 쓸 수 있게 되면 정거장이 돌아온다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ChipGroupsOnTheFormTest(Base):
    def groups(self, window):
        fields = self.ui(window).fields
        return {name: view.chip_group for name, view in fields.items() if view.chip_group is not None}

    def test_every_chip_group_of_the_form_is_one_tab_stop_and_the_single_choice_groups_keep_their_own_rule(self):
        window = self.make()
        groups = self.groups(window)
        self.assertEqual(sorted(groups), sorted(GROUPS), "낱말 제안 넷·보기 셋·여럿 고르기 둘")
        for name, group in groups.items():
            usable = group.usable()
            expected = next((chip for chip in usable if chip.isChecked()), usable[0])
            self.assertEqual([chip for chip in group.chips if chip.focusPolicy() == Qt.StrongFocus], [expected], name)
            self.assertGreaterEqual(len(group.chips), 5, name)
            view = self.ui(window).fields[name]
            self.assertEqual(list(group.chips), [*view.chips.values(), *([view.custom_chip] if view.custom_chip is not None else [])], f"{name}: 묶음은 그 칸의 모든 칩(보기 칸은 `직접 입력` 칩까지)이다")
        for name in ("language", "color_preset"):
            view = self.ui(window).fields[name]
            self.assertIsNone(view.chip_group, "하나만 고르는 묶음은 라디오 규칙(고른 칩만 정거장)이다")
            self.assertEqual([chip.isChecked() for chip in view.chips.values() if chip.focusPolicy() == Qt.StrongFocus], [True], name)

    def test_the_arrow_keys_move_inside_a_keyword_group_and_never_change_the_value(self):
        window = self.make()
        group = self.groups(window)["main_topics"]
        chips = group.chips
        before = window.state.blogs.values("naver_a")["main_topics"]
        self.focus(group.current)
        start = chips.index(group.current)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Right)
        self.settle(1)
        self.assertIs(QApplication.focusWidget(), chips[(start + 1) % len(chips)])
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_End)
        self.settle(1)
        self.assertIs(QApplication.focusWidget(), chips[-1])
        self.assertEqual(window.state.blogs.values("naver_a")["main_topics"], before, "옮기기만 했다 — 값은 그대로다")
        self.assertEqual(window.state.blogs.dirty_names("naver_a"), ())

    def test_a_word_chosen_in_the_other_keyword_field_is_skipped_by_the_arrows_and_a_stop_on_it_moves_away(self):
        window = self.make()
        groups = self.groups(window)
        priority, exclude = groups["priority_keywords"], groups["exclude_keywords"]
        word = next(value for value, chip in window.screen_widget.blogs_ui.fields["priority_keywords"].chips.items() if chip is priority.chips[3])
        self.focus(priority.chips[3])                                                              # 이 칩이 정거장이 된다
        self.assertEqual(priority.current, priority.chips[3])
        QTest.mouseClick(window.screen_widget.blogs_ui.fields["exclude_keywords"].chips[word], Qt.LeftButton)   # 다른 칸에서 같은 낱말을 고른다
        self.settle(2)
        self.assertFalse(priority.chips[3].isEnabled(), "다른 칸에서 이미 고른 낱말은 꺼진다")
        self.assertEqual([chip for chip in priority.chips if chip.focusPolicy() == Qt.StrongFocus], [priority.chips[0]], "정거장이던 칩이 꺼지면 쓸 수 있는 첫 칩으로 옮긴다")
        self.focus(priority.chips[2])
        QTest.keyClick(priority.chips[2], Qt.Key_Right)
        self.settle(1)
        self.assertIs(QApplication.focusWidget(), priority.chips[4], "꺼진 칩은 건너뛴다")
        self.assertEqual([chip for chip in exclude.chips if chip.focusPolicy() == Qt.StrongFocus].count(exclude.current), 1)

    def test_the_arrow_keys_scroll_the_form_so_the_focused_chip_is_always_in_view(self):
        window = self.make(size=(1093, 614))
        ui = self.ui(window)
        group = self.groups(window)["main_topics"]
        viewport = ui.form_scroll.viewport()

        def in_view(chip):
            top = chip.mapTo(viewport, chip.rect().topLeft()).y()
            return 0 <= top and top + chip.height() <= viewport.height()

        self.focus(group.current)                                                                  # 코드로 준 포커스는 스크롤하지 않는다 — 아래 칸의 칩이라 처음엔 보이지 않을 수 있다
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_End)
        self.settle(2)
        last = QApplication.focusWidget()
        self.assertIs(last, group.usable()[-1])
        self.assertTrue(in_view(last), "End 로 옮긴 칩이 스크롤 영역 안에 보인다(Tab 으로 옮길 때와 같다)")
        QTest.keyClick(last, Qt.Key_Home)
        self.settle(2)
        first = QApplication.focusWidget()
        self.assertIs(first, group.usable()[0])
        self.assertTrue(in_view(first), "Home 으로 옮긴 칩도 보인다")

    def test_tab_count_from_the_name_field_to_the_save_button_is_a_third_of_what_it_was(self):
        window = self.make()
        ui = self.ui(window)
        start = ui.fields["display_name"].edit
        self.type_into(window, "display_name", "시험 이름")                                         # 바뀐 것이 있어야 `저장` 이 켜져 Tab 정거장이 된다
        self.focus(start)
        save = self.action(window, "save")
        self.assertTrue(save.isEnabled())
        current, steps = start, 0
        while current is not save and steps < 200:
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            steps += 1
        self.assertIs(current, save, "Tab 으로 저장 단추에 닿는다")
        self.assertLessEqual(steps, TAB_LIMIT, "의도적 개선(blogsel-2, D-510): 칩 묶음이 정거장 하나라 이름 칸에서 저장까지 140번 → 29번(상한 안)")

    def test_the_chips_keep_their_accessible_names_and_every_group_still_reaches_each_chip_by_arrows(self):
        window = self.make()
        for name, group in self.groups(window).items():
            label = self.ui(window).fields[name].label.plain_text()
            for chip in group.chips:
                self.assertTrue(chip.accessibleName().strip(), name)
                self.assertIn(label, chip.accessibleName(), "접근 이름에 칸 이름이 들어 있다")
            reached = {id(group.current)}
            self.focus(group.current)
            for _ in range(len(group.chips)):
                QTest.keyClick(QApplication.focusWidget(), Qt.Key_Right)
                reached.add(id(QApplication.focusWidget()))
            self.assertEqual(reached, {id(chip) for chip in group.usable()}, f"{name}: 화살표로 쓸 수 있는 모든 칩에 닿는다")


if __name__ == "__main__":
    unittest.main()
