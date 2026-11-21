"""앱 묶음 L2(결정 D-534 에서 D-538)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) Seed 를 고치다 앱을 닫을 때의 확인창(F025)과 복원이 도는 동안의 저장 겹침 막기(F030)를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_l2_core`). 사용자의 클립보드·보관소·데이터 폴더·설정 파일은 건드리지 않는다(가짜 공급자의 메모리 상태).

지키는 것:
  1) (F025) 저장하지 않은 Seed 입력(고친 씨앗·새 Seed 폼 — 한글을 입력기 확정 이벤트로 넣은 것 포함)이 있는데 창을 닫으면 닫지 않고 먼저 묻는다: `저장 안 하고 닫기` / `계속 고치기`, 처음 포커스와 Esc 는 계속 고치기이고
     계속 고치기를 누르면 입력이 그대로이며 `저장 안 하고 닫기` 를 눌러야 닫힌다. 서랍을 닫았거나 다른 화면에서 닫아도 같다. 입력이 없으면(서랍만 열었다·글 검색·고른 상자)·저장한 뒤에는 묻지 않는다.
     블로그 입력도 있으면 블로그 확인이 먼저이고 그 확인을 넘기면 Seed 확인이 이어진다. 화면 이동은 묻지 않고 입력이 남는다.
  2) (F030) 복원이 도는 동안 Seed·블로그·저장한 초안의 저장은 시작하지 않고 한 줄로 알리며(입력·화면 그대로, 저장하고 나가기도 나가지 않는다) 복원이 끝나면 같은 입력을 저장할 수 있다. 저장이 도는 동안은 복원을 시작하지 않고(확인창도 띄우지 않는다)
     한 줄로 알린다. 지금 백업(만들기)은 저장을 막지 않는다.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import test_ui_qt_backup as tqb  # noqa: E402
import test_ui_qt_drafts_save as tqd  # noqa: E402
import test_ui_qt_seeds as tqs  # noqa: E402

from chanceblog_desktop.ui.core import clock as clock_rules, seeds, services, text  # noqa: E402

HAVE = tqs.HAVE and tqb.HAVE
T = text.T
if HAVE:
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication
    from chanceblog_desktop.ui.qt import shell as shell_module

    Qt, ui_offscreen = tqs.Qt, tqs.ui_offscreen

FIXED_NOW = tqb.FIXED_NOW
FULL = tqb.FIRST                                                                    # 복원할 백업의 이름(예시 목록의 첫 줄)
TYPED = "내가 고친 이유"
NEW_WORD = "새로 쓴 낱말"


def fresh_toast(window):
    """이전 안내를 치운다 — 다음 안내가 정말 새로 떴는지 보려고(같은 글이 이미 떠 있으면 새로 뜬 것과 구분이 안 된다)."""
    window.toast.policy.expire()
    window.toast.hide()


def force_close(window):
    """시험이 끝났을 때 창을 정리한다 — 입력이 남아 있으면 닫기가 먼저 묻고 닫지 않으므로 '그래도 닫기' 를 건너뛴다(시험 정리용)."""
    window._close_confirmed = True
    window.close()


class Held(tqb.Stepped):
    """복원이 시험이 풀어 줄 때까지 도는 가짜 공급자 — 첫 단계에서 멈춰 '복원 중' 을 확실히 본다(`Stepped` 는 `release` 에 하나를 넣어야 한 걸음 나아간다)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.steps = ((0.3, "복원하는 중"),)

    def let_go(self):
        for _ in range(8):
            self.release.put(1)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class Base(tqs.Base):
    def make(self, provider=None, size=(1366, 768), page="seed", backups_provider=None, wait=True, **kwargs):
        provider = provider or seeds.FakeSeedsProvider()
        window = shell_module.AppShell(services.FakeHomeProvider(), seeds=provider, backups=backups_provider, file_picker=lambda parent, title, filters: tqs.PICKED, autoload=False, clock=clock_rules.FixedClock(FIXED_NOW), **kwargs)
        window.resize(*size)
        window.show()
        self.addCleanup(force_close, window)
        if backups_provider is not None and hasattr(backups_provider, "let_go"):
            self.addCleanup(backups_provider.let_go)                                 # 나중에 등록한 것이 먼저 돈다 — 복원을 풀어 주고 창을 닫는다
        self.settle()
        self.activate(window)
        if page == "seed":
            window.go("seed")
            if wait:
                ui_offscreen.wait_until(self.app, lambda: window.state.seeds.state != "loading" and not window.state.seeds.loading, 10)
            self.settle()
        return window

    def go_seed(self, window):
        window.go("seed")
        ui_offscreen.wait_until(self.app, lambda: window.state.seeds.state != "loading" and not window.state.seeds.loading, 10)
        self.settle(6)

    def dialog_buttons(self, window):
        return {button.text(): button for button in window.dialog.findChildren(QAbstractButton) if button.isVisibleTo(window.dialog)}

    def dialog_texts(self, window):
        return {label.plain_text() for label in window.dialog.findChildren(tqs.UI.Label)}

    def type_ime(self, edit, value):
        edit.setFocus(Qt.OtherFocusReason)
        edit.selectAll()
        event = QInputMethodEvent()
        event.setCommitString(value)
        QApplication.sendEvent(edit, event)
        self.settle(2)

    def edit_seed(self, window, seed_id="EX001", value=TYPED):
        self.open_row(window, seed_id)
        self.type_into(window, "reason", value)

    def edit_new_seed(self, window, value=NEW_WORD):
        window.seed_open_new()
        self.settle(8)
        self.type_into(window, "keyword", value)

    def reason_text(self, window):
        return self.dui(window).fields["reason"].edit.text()

    def toast_text(self, window):
        return window.toast.text() if window.toast.isVisible() else ""

    def fresh_toast(self, window):
        fresh_toast(window)


# ---- 1) Seed 를 고치다 창을 닫을 때 먼저 묻기 -------------------------------------------------------------------------------------------------
class CloseQuestionTest(Base):
    def test_closing_with_an_edited_seed_asks_first_with_keep_editing_focused_and_keep_editing_keeps_the_korean_text(self):
        window = self.make()
        self.edit_seed(window)
        self.assertEqual(self.reason_text(window), TYPED)
        window.close()
        self.settle(3)
        self.assertTrue(window.isVisible(), "저장하지 않은 Seed 입력이 있으면 닫지 않고 먼저 묻는다")
        self.assertTrue(window.dialog.is_open)
        self.assertTrue({T["seeds_close_title"], T["seeds_close_body"]} <= self.dialog_texts(window))
        buttons = self.dialog_buttons(window)
        self.assertEqual(sorted(buttons), sorted([T["seeds_close_ok"], T["seeds_close_cancel"]]), "두 갈래다")
        self.assertIs(QApplication.focusWidget(), buttons[T["seeds_close_cancel"]], "처음 포커스는 계속 고치기")
        self.assertIs(window.dialog_default, buttons[T["seeds_close_cancel"]])
        buttons[T["seeds_close_cancel"]].click()
        self.settle(3)
        self.assertEqual((window.isVisible(), window.dialog.is_open), (True, False))
        self.assertEqual(self.reason_text(window), TYPED, "계속 고치기를 누르면 입력이 그대로다")
        self.assertTrue(window.state.seeds.is_dirty("EX001"))

    def test_escape_also_keeps_editing_and_the_enter_key_on_the_first_focus_does_not_close(self):
        window = self.make()
        self.edit_seed(window)
        window.close()
        self.settle(3)
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle(2)
        self.assertEqual((window.isVisible(), window.dialog.is_open, self.reason_text(window)), (True, False, TYPED))
        window.close()
        self.settle(3)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Space)                        # 처음 포커스에서 누르는 키는 계속 고치기를 누른 것이다
        self.settle(3)
        self.assertEqual((window.isVisible(), window.dialog.is_open, self.reason_text(window)), (True, False, TYPED))

    def test_choosing_close_without_saving_closes_and_writes_nothing(self):
        window = self.make()
        self.edit_seed(window)
        before = window.state.seeds.data
        window.close()
        self.settle(3)
        self.dialog_buttons(window)[T["seeds_close_ok"]].click()
        self.settle(3)
        self.assertFalse(window.isVisible(), "'저장 안 하고 닫기' 를 눌러야 닫힌다")
        self.assertIs(window.state.seeds.data, before, "아무것도 저장하지 않았다")

    def test_a_new_seed_form_asks_even_after_the_drawer_was_closed_and_from_another_screen(self):
        window = self.make()
        self.edit_new_seed(window)
        window.close_drawer()
        self.settle(4)
        self.assertFalse(window.drawer.is_open)
        window.go("home")
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "화면을 옮길 때는 묻지 않는다 — 쓰던 값은 남아 있다")
        window.close()
        self.settle(3)
        self.assertTrue(window.isVisible() and window.dialog.is_open)
        self.assertIn(T["seeds_close_title"], self.dialog_texts(window))
        self.dialog_buttons(window)[T["seeds_close_cancel"]].click()
        self.settle(3)
        window.go("seed")
        self.settle(4)
        window.seed_open_new()
        self.settle(8)
        self.assertEqual(self.dui(window).fields["keyword"].edit.text(), NEW_WORD, "쓰던 값이 그대로 남아 있다")

    def test_no_input_no_question_a_drawer_a_search_text_and_checked_boxes_do_not_count(self):
        window = self.make()
        self.open_row(window, "EX001")
        self.assertTrue(window.drawer.is_open)
        window.close()
        self.settle(3)
        self.assertFalse(window.isVisible(), "서랍만 열었으면 바로 닫힌다")
        other = self.make()
        other.state.seeds.set_query("검색어")
        other.state.seeds.toggle_check("EX001")
        other.state.seeds.open_new()
        other.close()
        self.settle(3)
        self.assertFalse(other.isVisible(), "글 검색·고른 상자·열기만 한 새 Seed 서랍은 잃을 입력이 아니다")

    def test_after_saving_the_same_input_nothing_is_asked(self):
        window = self.make()
        self.edit_seed(window)
        self.bar_button(window, "save").click()
        self.wait_write(window)
        self.assertEqual(window.state.seeds.notice, ("ok", T["seeds_saved"]))
        window.close()
        self.settle(3)
        self.assertFalse(window.isVisible(), "저장한 뒤에는 묻지 않는다")

    def test_moving_between_screens_never_asks_and_keeps_the_seed_input_and_its_badge(self):
        window = self.make()
        self.edit_seed(window)
        window.go("home")
        self.settle(4)
        self.assertEqual((window.dialog.is_open, window.state.page), (False, "home"))
        self.go_seed(window)
        self.assertTrue(window.state.seeds.is_dirty("EX001"))
        self.assertEqual(self.row(window, "EX001").badges[-1].text(), T["seeds_flag_unsaved"], "줄에 '저장 전 변경' 이 보인다")

    def test_the_blog_question_comes_first_and_the_seed_question_follows_and_either_cancel_keeps_both_inputs(self):
        window = self.make()
        window.go("blogs")
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state != "loading" and not window.state.blogs.loading, 10)
        self.settle(6)
        self.type_ime(window.screen_widget.blogs_ui.fields["alias"].edit, "저장 전 별명")
        self.go_seed(window)
        self.edit_seed(window)
        window.close()
        self.settle(3)
        self.assertIn(T["blogs_close_title"], self.dialog_texts(window), "블로그 확인이 먼저다")
        self.dialog_buttons(window)[T["blogs_close_ok"]].click()
        self.settle(3)
        self.assertTrue(window.isVisible(), "블로그 확인을 넘겨도 Seed 입력이 있으면 닫지 않는다")
        self.assertIn(T["seeds_close_title"], self.dialog_texts(window), "이어서 Seed 확인이 뜬다")
        buttons = self.dialog_buttons(window)
        self.assertIs(QApplication.focusWidget(), buttons[T["seeds_close_cancel"]], "처음 포커스는 계속 고치기")
        buttons[T["seeds_close_cancel"]].click()
        self.settle(3)
        self.assertEqual((window.isVisible(), window.dialog.is_open, self.reason_text(window), window.state.blogs.has_unsaved()), (True, False, TYPED, True), "둘 다 그대로다")
        window.close()
        self.settle(3)
        self.dialog_buttons(window)[T["blogs_close_ok"]].click()
        self.settle(3)
        self.dialog_buttons(window)[T["seeds_close_ok"]].click()
        self.settle(3)
        self.assertFalse(window.isVisible(), "두 확인을 모두 넘기면 닫힌다")

    def test_with_the_drafts_question_first_the_blog_and_seed_questions_still_follow_in_order(self):
        window = self.make()
        window.go("blogs")
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state != "loading" and not window.state.blogs.loading, 10)
        self.settle(6)
        self.type_ime(window.screen_widget.blogs_ui.fields["alias"].edit, "저장 전 별명")
        self.go_seed(window)
        self.edit_seed(window)
        with mock.patch.object(window.state.drafts, "has_unsaved", return_value=True):
            window.close()
            self.settle(3)
            first = self.dialog_buttons(window)
            self.assertEqual(sorted(first), sorted([T["drf_close_ok"], T["drf_cancel"]]), "초안 확인이 맨 먼저다")
            first[T["drf_close_ok"]].click()
            self.settle(3)
            self.assertIn(T["blogs_close_title"], self.dialog_texts(window))
            self.dialog_buttons(window)[T["blogs_close_ok"]].click()
            self.settle(3)
            self.assertIn(T["seeds_close_title"], self.dialog_texts(window))
            self.dialog_buttons(window)[T["seeds_close_ok"]].click()
            self.settle(3)
            self.assertFalse(window.isVisible())

    def test_the_two_buttons_have_names_a_big_enough_hit_area_and_tab_stays_inside_the_dialog(self):
        window = self.make()
        self.edit_seed(window)
        window.close()
        self.settle(3)
        buttons = self.dialog_buttons(window)
        for button in buttons.values():
            self.assertTrue(button.accessibleName() or button.text())
            self.assertGreaterEqual(button.height(), 36)
        order = []
        for _ in range(2):
            order.append(QApplication.focusWidget().text())
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab)
            self.settle(1)
        self.assertEqual(sorted(order), sorted([T["seeds_close_ok"], T["seeds_close_cancel"]]), "두 단추를 한 바퀴 돈다")
        self.assertEqual(QApplication.focusWidget().text(), order[0], "대화상자 밖으로 나가지 않는다")


# ---- 2) 복원 중 저장 겹침 막기 -----------------------------------------------------------------------------------------------------------------
class RestoreOverlapTest(Base):
    def start_restore(self, window):
        """설정 화면의 복원 확인창에서 `복원하기` 를 눌러 복원을 시작한다(복원은 풀어 줄 때까지 돈다)."""
        window.go("settings")
        controller = window.state.backups
        ui_offscreen.wait_until(self.app, lambda: controller.state != "loading" and not controller.loading, 10)
        self.settle()
        window.backup_restore(FULL)
        self.assertTrue(window.dialog.is_open)
        ok = next(button for button in window.dialog.findChildren(QAbstractButton) if button.property("focus_key") == "dialog-ok")
        QTest.mouseClick(ok, Qt.LeftButton)
        self.settle(3)
        self.assertTrue(controller.restoring)

    def finish_restore(self, window, provider):
        provider.let_go()
        ui_offscreen.wait_until(self.app, lambda: window.state.backups.pending is None and not window.state.backups.busy, 20)
        self.settle(4)
        self.assertFalse(window.state.backups.restoring)

    def test_a_seed_save_during_a_restore_says_one_line_changes_nothing_and_works_after_it(self):
        held = Held()
        window = self.make(backups_provider=held)
        self.start_restore(window)
        self.go_seed(window)
        self.edit_seed(window)
        before = window.state.seeds.data
        self.fresh_toast(window)
        self.bar_button(window, "save").click()
        self.settle(3)
        self.assertEqual(self.toast_text(window), T["backup_blocks_save"], "한 줄로 알린다")
        self.assertEqual((window.state.seeds.busy, window.state.seeds.pending, window.state.seeds.is_dirty("EX001"), self.reason_text(window)), (False, None, True, TYPED), "저장은 시작하지 않았고 입력은 그대로다")
        self.assertIs(window.state.seeds.data, before)
        self.finish_restore(window, held)
        self.bar_button(window, "save").click()
        self.wait_write(window)
        self.assertEqual((window.state.seeds.notice, window.state.seeds.is_dirty("EX001")), (("ok", T["seeds_saved"]), False), "복원이 끝나면 같은 입력을 저장할 수 있다")

    def test_the_other_seed_writes_and_a_new_seed_are_refused_the_same_way(self):
        held = Held()
        window = self.make(backups_provider=held)
        self.start_restore(window)
        self.go_seed(window)
        self.open_row(window, "EX001")
        for action in ("approve",):
            self.fresh_toast(window)
            self.bar_button(window, action).click()
            self.settle(3)
            self.assertEqual(self.toast_text(window), T["backup_blocks_save"], action)
        self.assertEqual(window.state.seeds.data.seeds[0].state, "proposed", "승인은 시작하지 않았다")
        self.fresh_toast(window)
        window.state.seeds.toggle_check("EX001")
        window.seed_bulk("activate")
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "복원이 도는 동안은 바꿀 수 없는 일을 묻지 않는다")
        self.assertEqual(self.toast_text(window), T["backup_blocks_save"])
        window.close_drawer()
        self.settle(3)
        self.edit_new_seed(window)
        self.fresh_toast(window)
        window.seed_create()
        self.settle(3)
        self.assertEqual((self.toast_text(window), window.state.seeds.busy, window.state.seeds.pending), (T["backup_blocks_save"], False, None))
        self.finish_restore(window, held)

    def test_a_blog_save_and_a_blog_delete_during_a_restore_are_refused_with_the_same_line(self):
        held = Held()
        window = self.make(backups_provider=held, page=None)
        self.start_restore(window)
        window.go("blogs")
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state != "loading" and not window.state.blogs.loading, 10)
        self.settle(6)
        self.type_ime(window.screen_widget.blogs_ui.fields["alias"].edit, "저장 전 별명")
        self.fresh_toast(window)
        window.blog_action("save")
        self.settle(3)
        self.assertEqual(self.toast_text(window), T["backup_blocks_save"])
        self.assertEqual((window.state.blogs.busy, window.state.blogs.pending, window.state.blogs.has_unsaved()), (False, None, True))
        self.fresh_toast(window)
        window.blog_action("delete")
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "복원이 도는 동안은 지울 수 없는 일을 묻지 않는다")
        self.assertEqual(self.toast_text(window), T["backup_blocks_save"])
        self.finish_restore(window, held)
        window.blog_action("save")
        self.wait_blog_write(window)
        self.assertFalse(window.state.blogs.has_unsaved(), "복원이 끝난 뒤에는 저장된다")

    def wait_blog_write(self, window):
        ui_offscreen.wait_until(self.app, lambda: not window.state.blogs.busy and window.state.blogs.pending is None, 10)
        self.settle()

    def test_a_save_runs_even_while_a_plain_backup_is_being_made(self):
        held = Held()
        window = self.make(backups_provider=held, page=None)
        window.go("settings")
        controller = window.state.backups
        ui_offscreen.wait_until(self.app, lambda: controller.state != "loading" and not controller.loading, 10)
        self.settle()
        self.assertEqual(window.backup_now(), "started")
        self.assertTrue(controller.busy and not controller.restoring)
        self.go_seed(window)
        self.edit_seed(window)
        self.bar_button(window, "save").click()
        self.wait_write(window)
        self.assertEqual((window.state.seeds.notice, window.state.seeds.is_dirty("EX001")), (("ok", T["seeds_saved"]), False), "지금 백업은 저장을 막지 않는다")
        held.let_go()

    # ---- 거꾸로: 저장이 도는 동안은 복원을 시작하지 않는다 ----
    def test_a_restore_is_not_started_while_a_seed_save_runs_and_asks_nothing(self):
        gated = tqs.Gated()
        held = Held()
        window = self.make(provider=gated, backups_provider=held)
        self.addCleanup(gated.gate.set)
        self.edit_seed(window)
        self.bar_button(window, "save").click()
        self.settle(3)
        self.assertTrue(window.state.seeds.busy, "저장이 문 앞에서 기다리는 중이다")
        window.go("settings")
        controller = window.state.backups
        ui_offscreen.wait_until(self.app, lambda: controller.state != "loading" and not controller.loading, 10)
        self.settle()
        self.fresh_toast(window)
        window.backup_restore(FULL)
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "시작할 수 없는 복원은 묻지 않는다")
        self.assertEqual(self.toast_text(window), T["backup_wait_save"])
        self.fresh_toast(window)
        self.assertEqual(window.backup_restore_confirmed(FULL), "writing", "확인창이 먼저 떠 있었어도 시작하지 않는다")
        self.assertEqual(self.toast_text(window), T["backup_wait_save"], "그 길에서도 한 줄로 알린다")
        self.assertEqual((controller.busy, held.started), (False, []))
        gated.gate.set()
        ui_offscreen.wait_until(self.app, lambda: not window.state.seeds.busy and window.state.seeds.pending is None, 10)
        self.settle(4)
        self.start_restore(window)
        self.assertEqual(held.started, ["restore:" + FULL], "저장이 끝난 뒤에는 복원을 시작한다")
        self.finish_restore(window, held)


# ---- 3) 저장한 초안 ----------------------------------------------------------------------------------------------------------------------------
class DraftRestoreTest(tqd.SaveBase):
    def make_with(self, held, fake):
        window = self.drafted(drafts_provider=fake, home=services.FakeHomeProvider(backups=held))
        self.addCleanup(held.let_go)
        self.addCleanup(lambda: setattr(window, "_close_confirmed", True))
        return window

    def start_restore(self, window):
        controller = window.state.backups
        controller.apply_loaded(controller.provider.load_backups(lambda *a: None, lambda: False))
        self.assertEqual(window.backup_restore_confirmed(FULL), "started")
        self.assertTrue(controller.restoring)

    def test_a_draft_save_during_a_restore_is_refused_with_the_line_and_save_and_leave_does_not_leave(self):
        held = Held()
        fake = tqd.provider()
        window = self.make_with(held, fake)
        self.edit_body(window)
        body = window.state.drafts.body
        self.start_restore(window)
        fresh_toast(window)
        self.button(window, "act:save").click()
        self.settle(3)
        self.assertEqual(window.toast.text() if window.toast.isVisible() else "", T["backup_blocks_save"], "한 줄로 알린다")
        self.assertEqual((fake.save_calls, window.state.drafts.store_busy, window.state.drafts.body), ([], False, body), "저장은 시작하지 않았고 고친 글은 그대로다")
        window.go("topics")
        self.settle(3)
        buttons = self.dialog_buttons(window)
        self.assertIn(T["drf_choice_save"], buttons)
        fresh_toast(window)
        buttons[T["drf_choice_save"]].click()
        self.settle(4)
        self.assertEqual((window.state.page, fake.save_calls), ("drafts", []), "저장하고 나가기를 눌러도 저장하지 못했으면 나가지 않는다 — 고친 글이 그대로 남는다")
        self.assertEqual(window.toast.text() if window.toast.isVisible() else "", T["backup_blocks_save"])
        self.assertEqual(window.state.drafts.body, body)
        held.let_go()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.backups.pending is None and not window.state.backups.busy, 20))
        self.settle(4)
        self.button(window, "act:save").click()
        self.assertTrue(self.wait_store(window))
        self.assertEqual(len(fake.saved), 1, "복원이 끝나면 같은 글을 저장할 수 있다")


if __name__ == "__main__":
    unittest.main()
