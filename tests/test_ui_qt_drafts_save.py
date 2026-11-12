"""초안 작성 화면의 **저장한 초안**(PySide6, 결정 D-361 에서 D-363 까지) 시험 — 창을 화면에 띄우지 않고(offscreen) `저장` 단추·Ctrl+S·저장 상태 줄·세 갈래 확인창(떠나기·`← 주제 후보`·앱 닫기)·저장한 초안 목록(열기·지우기)·홈의 개수와 연결을 확인한다.
**PySide6 가 없으면 Qt 시험은 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_drafts_save_core`·`test_ui_drafts_save_service`·`test_ui_home_saved_drafts`, 증거는 이 PC 의 offscreen 실행이다).
사용자의 클립보드·브라우저·보관소·데이터 폴더는 건드리지 않는다(가짜 클립보드·가짜 열기 함수·가짜 공급자의 메모리 저장소). 키 모양 입력은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다.

지키는 것:
  1) `저장` 단추가 아래 행동 줄 맨 앞에 있고(주요 단추는 여전히 하나) 저장 상태 줄이 편집기 아래에 글로 있다. 단추·Ctrl+S 가 저장하고 글을 치던 편집기는 다시 그려지지 않는다(커서·한글 조합이 사라지지 않는다).
  2) 키·토큰 모양이면 저장하지 않고 위치·종류만 알리는 창(확인 하나 — **저장을 이어 가는 단추가 없다**)이고 찾은 글이 어느 화면 글에도 없다. 그 밖의 저장 실패는 알림이고 복사·편집은 그대로다.
  3) **세 갈래 확인창**: 고친 내용이 저장되지 않았으면 떠나기·`← 주제 후보`·`저장한 초안`·앱 닫기 앞에 `저장 / 저장 안 하고 나가기 / 계속 고치기`(처음 포커스는 저장, Esc 는 계속 고치기). 저장이 안 되면 나가기를 막지 않되 경고한다.
  4) 목록: 후보 없이 `초안 작성` 을 열면 저장한 초안이 보이고 `열기`(저장한 제목·본문 그대로)·`지우기`(확인창이 먼저)가 된다. 홈 구역은 머리 개수와 `저장한 초안 보기` 로 목록에 닿는다.
  5) 읽는 이름·Tab 순서·창 크기(최소 900×560 까지 가로 스크롤 없음).
"""
import ast
import re
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as SS  # noqa: E402
from test_ui_drafts_core import CATALOG, GENERIC  # noqa: E402
from test_ui_qt_drafts import HAVE, QT_DIR, SIZES, Base  # noqa: E402

if HAVE:
    from test_ui_qt_drafts import QAbstractButton, QTest, Qt, ui_offscreen  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.ui.core import board_view, drafts, services, text  # noqa: E402

T = text.T
PROVIDER_CALL = re.compile(r"(?<![A-Za-z0-9_])(?:save_draft|open_saved|list_saved|delete_saved)\b")           # 공급자 함수의 이름(`start_open_saved` 같은 컨트롤러 함수는 앞에 글자가 붙어 걸리지 않는다)
EMOJI = chr(0x1F600)
KEY_LINE = SS.sample("github_token")[1]
KEY_TOKEN = SS.sample("github_token")[0]


class Slow(drafts.FakeDraftsProvider):
    """저장이 시험이 문을 열어 줄 때까지 기다리는 가짜 공급자 — 시간에 기대지 않고 '저장하는 중' 을 확실히 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate, self.entered = threading.Event(), threading.Event()
        self.holding = False
        self.starts = 0                                                              # 저장이 시작된 횟수(문이 열리기 전에도 센다 — `save_calls` 는 저장이 끝나야 늘어난다)

    def save_draft(self, request, progress, cancelled):
        self.starts += 1
        if self.holding:
            self.entered.set()
            if not self.gate.wait(30):
                raise AssertionError("시험이 문을 열어 주지 않았다")
        return super().save_draft(request, progress, cancelled)


def provider(**more):
    return drafts.FakeDraftsProvider(lambda: CATALOG, saving=True, **more)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class SaveBase(Base):
    def saved_status(self, window):
        return self.ui(window).save_status.plain_text()

    def wait_store(self, window):
        ok = ui_offscreen.wait_until(self.app, lambda: not window.state.drafts.store_busy and window.state.drafts.store_pending is None, 10)
        self.settle()
        return ok

    def dialog_keys(self, window):
        return {button.property("focus_key"): button for button in window.dialog.findChildren(QAbstractButton) if button.isVisibleTo(window.dialog) and button.property("focus_key")}

    def press_save(self, window):
        self.button(window, "act:save").click()
        self.assertTrue(self.wait_store(window))


class ScreenTest(SaveBase):
    def test_the_save_button_is_first_in_the_action_row_and_the_status_is_text_below_the_editor(self):
        window = self.drafted(drafts_provider=provider())
        ui = self.ui(window)
        self.assertEqual(list(ui.actions), ["save", "title", "body", "all", "open"])
        self.assertEqual(ui.actions["save"].text(), T["drf_save"])
        self.assertEqual(ui.actions["save"].accessibleName(), T["drf_save_a11y"])
        self.assertEqual(self.saved_status(window), T["drf_state_unsaved"])
        self.assertEqual(ui.save_status.accessibleName(), T["drf_state_a11y_unsaved"])
        self.assertTrue(ui.actions["save"].isEnabled())
        self.assertEqual([spec["kind"] for spec in ui.action_bar.specs].count("primary"), 1, "화면의 주요 단추는 전체 복사 하나뿐이다")
        self.assertEqual(ui.action_bar.specs[0]["key"], "save")

    def test_without_a_saving_provider_there_is_no_save_button_and_no_status(self):
        window = self.drafted(drafts_provider=drafts.FakeDraftsProvider(lambda: CATALOG))
        ui = self.ui(window)
        self.assertEqual(list(ui.actions), ["title", "body", "all", "open"])
        self.assertIsNone(ui.save_status)
        self.assertIsNone(ui.saved_list)

    def test_pressing_save_makes_the_status_saved_with_the_time_and_a_toast_and_keeps_the_same_editor(self):
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        editor = self.edit_body(window)
        cursor = editor.textCursor()
        cursor.setPosition(7)
        editor.setTextCursor(cursor)
        before = self.ui(window)
        self.button(window, "act:save").click()
        self.assertTrue(self.wait_store(window))
        self.assertIs(self.ui(window), before, "화면을 다시 그리지 않았다")
        self.assertIs(self.ui(window).editor, editor)
        self.assertEqual(editor.textCursor().position(), 7)
        row = next(iter(fake.saved.values()))
        self.assertEqual(self.saved_status(window), T["drf_state_saved"].format(when=board_view.time_text(row.updated_at)))
        self.assertEqual((row.body, row.title), (window.state.drafts.body, window.state.drafts.title))
        self.assertTrue(window.toast.isVisible())
        self.assertIn(board_view.time_text(row.updated_at), window.state.drafts.notice[1])
        self.assertEqual(window.state.drafts.save_state(), "saved")

    def test_typing_after_a_save_turns_the_status_into_changed_without_redrawing(self):
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        self.press_save(window)
        ui = self.ui(window)
        ui.editor.setPlainText(ui.editor.toPlainText() + " 더 씀")
        self.settle(2)
        self.assertIs(self.ui(window), ui)
        self.assertEqual(self.saved_status(window), T["drf_state_changed"])
        self.assertEqual(window.state.drafts.save_state(), "changed")
        ui.editor.setPlainText(window.state.drafts.draft_body().body_text)         # 저장한 글과 글자까지 같아지면 다시 `저장됨` — 기준은 저장한 글이지 고친 기록이 아니다
        self.settle(2)
        self.assertIs(self.ui(window), ui)
        self.assertEqual(window.state.drafts.save_state(), "saved")
        row = next(iter(fake.saved.values()))
        self.assertEqual(self.saved_status(window), T["drf_state_saved"].format(when=board_view.time_text(row.updated_at)))

    def test_ctrl_s_saves_only_on_the_draft_screen_with_a_draft_and_no_dialog(self):
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
        self.assertTrue(self.wait_store(window))
        self.assertEqual(len(fake.save_calls), 1)
        self.edit_body(window)
        window.show_dialog("제목", "본문", ok="확인", cancel=None)
        QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
        self.settle(3)
        self.assertEqual(len(fake.save_calls), 1, "확인창이 열려 있으면 저장하지 않는다")
        window.close_dialog()
        window.state.drafts.leave()
        window.go("home")
        self.settle()
        QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
        self.settle(3)
        self.assertEqual(len(fake.save_calls), 1, "다른 화면에서는 아무 일도 하지 않는다")

    def test_while_saving_the_button_is_off_the_status_says_so_and_the_second_press_does_nothing(self):
        fake = Slow(lambda: CATALOG, saving=True)
        window = self.drafted(drafts_provider=fake)
        fake.holding = True
        self.button(window, "act:save").click()
        self.assertTrue(fake.entered.wait(10))
        self.settle(2)
        self.assertEqual(self.saved_status(window), T["drf_state_saving"])
        self.assertFalse(self.ui(window).actions["save"].isEnabled())
        QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
        self.settle(2)
        self.assertEqual((fake.starts, fake.save_calls), (1, []), "두 번째 누름은 새 저장을 시작하지 않는다(첫 저장은 아직 끝나지 않았다)")
        fake.gate.set()
        self.assertTrue(self.wait_store(window))
        self.assertEqual((fake.starts, len(fake.save_calls)), (1, 1))
        self.assertTrue(self.ui(window).actions["save"].isEnabled())

    def test_a_key_shape_shows_one_alert_with_the_place_and_no_way_to_save_anyway_and_the_key_is_nowhere(self):
        fake = provider()
        window = self.drafted(drafts_provider=fake)
        self.edit_body(window, "\n" + KEY_LINE)
        self.press_save(window)
        self.assertTrue(window.dialog.is_open)
        buttons = self.dialog_buttons(window)
        self.assertEqual(list(buttons), [T["drf_savefail_secret_ok"]])
        body = " ".join(self.texts(window.dialog))
        self.assertIn(T["drf_savefail_secret_head"], body)
        self.assertIn("본문에서 1건(GitHub 토큰 1)", body)
        self.assertEqual(fake.saved, {})
        shown = " ".join(self.everything(window))                                  # 편집기 안의 글은 사용자가 쓴 글 자신이라 이 목록(이름·글·설명)에 없다 — 화면 글 어디에도 찾은 글이 없다
        self.assertFalse(SS.leaked(shown, KEY_TOKEN))
        for word in ("무시", "그래도 저장", "건너"):
            self.assertNotIn(word, shown)
        buttons[T["drf_savefail_secret_ok"]].click()
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(window.state.drafts.save_state(), "unsaved")

    def test_a_key_shape_found_only_in_the_made_draft_is_told_with_the_special_advice_in_the_same_one_button_alert(self):
        """만든 초안(화면에서 못 고치는 칸)에서만 찾아도 같은 알림창이다(D-368) — 위치와 종류, 그리고 후보·블로그 프로필·선택 입력을 고쳐 다시 만들기(먼저 복사)라는 전용 문구. 저장을 이어 가는 단추는 없다."""
        from chanceblog_desktop.security import scan
        token, line = SS.sample("google_api_key")
        findings = tuple(scan.scan_fields({"만든 초안 본문": "만든 본문\n" + line}))
        window = self.drafted(drafts_provider=provider(save_fail=drafts.secret_failure(findings)))
        self.press_save(window)
        self.assertTrue(window.dialog.is_open)
        buttons = self.dialog_buttons(window)
        self.assertEqual(list(buttons), [T["drf_savefail_secret_ok"]])
        body = " ".join(self.texts(window.dialog))
        self.assertIn(T["drf_savefail_secret_head"], body)
        self.assertIn("만든 초안 본문에서 1건(Google API 키 1) — 2번째 줄", body)
        self.assertIn("다시 만들기", body)
        self.assertIn("먼저 복사", body)
        self.assertNotIn("해당 줄을 만든 초안 본문에서", body, "화면에서 못 고치는 칸이라 '그 줄을 지우라' 는 말은 없다")
        self.assertEqual(ui_offscreen.find_clipping(window.dialog), [], "긴 안내도 알림창 안에서 잘리지 않는다")
        self.assertTrue(window.dialog.height() <= window.height() and window.dialog.width() <= window.width())
        shown = " ".join(self.everything(window))
        self.assertFalse(SS.leaked(shown, token))
        for word in ("무시", "그래도 저장", "건너"):
            self.assertNotIn(word, shown)
        buttons[T["drf_savefail_secret_ok"]].click()
        self.settle()
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(window.state.drafts.save_state(), "unsaved")

    def test_a_locked_store_is_a_notice_that_says_it_is_in_use_and_copy_and_edit_still_work(self):
        window = self.drafted(drafts_provider=provider(save_fail=drafts.save_failure(AppError("STORE_LOCKED"))))
        self.press_save(window)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(window.state.drafts.notice, ("error", T["drf_savefail_locked"]))
        self.assertNotIn("디스크", T["drf_savefail_locked"])
        self.button(window, "drf-copy:tags").click()
        self.settle(2)
        self.assertEqual(len(self.copied), 1)

    def test_another_failure_is_a_notice_and_copy_and_edit_still_work(self):
        window = self.drafted(drafts_provider=provider(save_fail=drafts.save_failure(AppError("DISK_FULL"))))
        self.press_save(window)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(window.state.drafts.notice, ("error", T["drf_savefail_io"]))
        self.button(window, "drf-copy:tags").click()
        self.settle(2)
        self.assertEqual(len(self.copied), 1)
        self.edit_body(window)
        self.assertTrue(self.ui(window).actions["save"].isEnabled())


class LeaveChoicesTest(SaveBase):
    def edited(self, **more):
        fake = more.pop("provider", None) or provider()
        window = self.drafted(drafts_provider=fake)
        self.edit_body(window)
        return window, fake

    def open_dialog_by_nav(self, window):
        window.go("topics")
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        return self.dialog_buttons(window)

    def test_leaving_with_unsaved_edits_asks_with_three_choices_and_focus_starts_on_save(self):
        window, fake = self.edited()
        buttons = self.open_dialog_by_nav(window)
        self.assertEqual(list(buttons), [T["drf_choice_save"], T["drf_choice_discard_leave"], T["drf_choice_stay"]])
        self.assertEqual(window.dialog_default.text(), T["drf_choice_save"])
        self.assertTrue(window.dialog_default.hasFocus())
        self.assertEqual(window.state.page, "drafts")
        self.assertEqual(window.state.drafts.leave_asked, "leave")

    def test_the_dialog_buttons_have_names_and_tab_stays_inside_the_dialog(self):
        window, fake = self.edited()
        self.open_dialog_by_nav(window)
        keys = self.dialog_keys(window)
        self.assertEqual(sorted(keys), ["dialog-discard", "dialog-save", "dialog-stay"])
        for button in keys.values():
            self.assertTrue(button.accessibleName() or button.text())
            self.assertGreaterEqual(button.height(), 36)
        order = []
        for _ in range(3):
            order.append(self.app.focusWidget().text())
            QTest.keyClick(self.app.focusWidget(), Qt.Key_Tab)
            self.settle(1)
        self.assertEqual(sorted(order), sorted([T["drf_choice_save"], T["drf_choice_discard_leave"], T["drf_choice_stay"]]), "세 단추를 한 바퀴 돈다")

    def test_escape_and_keep_editing_stay_on_the_screen_with_the_edits_and_forget_the_question(self):
        window, fake = self.edited()
        body = window.state.drafts.body
        buttons = self.open_dialog_by_nav(window)
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle(2)
        self.assertEqual((window.dialog.is_open, window.state.page, window.state.drafts.body, window.state.drafts.leave_asked), (False, "drafts", body, None))
        buttons = self.open_dialog_by_nav(window)
        buttons[T["drf_choice_stay"]].click()
        self.settle(2)
        self.assertEqual((window.dialog.is_open, window.state.page, window.state.drafts.body, window.state.drafts.leave_asked), (False, "drafts", body, None))
        self.assertEqual(fake.saved, {})

    def test_save_saves_and_then_leaves(self):
        window, fake = self.edited()
        buttons = self.open_dialog_by_nav(window)
        body = window.state.drafts.body
        buttons[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.page == "topics", 10))
        self.settle()
        self.assertEqual([row.body for row in fake.saved.values()], [body])

    def test_discard_leaves_without_saving(self):
        window, fake = self.edited()
        buttons = self.open_dialog_by_nav(window)
        buttons[T["drf_choice_discard_leave"]].click()
        self.settle(3)
        self.assertEqual((window.state.page, fake.saved, fake.save_calls), ("topics", {}, []))

    def test_the_back_button_and_the_saved_list_button_use_the_same_three_choices(self):
        window, fake = self.edited()
        self.button(window, "drf-back").click()
        self.settle(3)
        self.assertEqual(list(self.dialog_buttons(window)), [T["drf_choice_save"], T["drf_choice_discard_leave"], T["drf_choice_stay"]])
        QTest.keyClick(window, Qt.Key_Escape)
        self.settle(2)
        self.button(window, "drf-saved-list").click()
        self.settle(3)
        self.assertEqual(list(self.dialog_buttons(window)), [T["drf_choice_save"], T["drf_choice_discard_leave"], T["drf_choice_stay"]])
        self.dialog_buttons(window)[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.state == "empty" and window.state.drafts.listing is not None, 10))
        self.settle()
        self.assertEqual(window.state.page, "drafts")
        self.assertEqual(len(fake.saved), 1)

    def test_a_saved_and_unchanged_draft_leaves_without_any_question(self):
        window, fake = self.edited()
        self.press_save(window)
        window.go("topics")
        self.settle(3)
        self.assertEqual((window.dialog.is_open, window.state.page), (False, "topics"))

    def test_when_the_save_fails_the_warning_dialog_lets_the_user_leave_or_keep_editing(self):
        window, fake = self.edited(provider=provider(save_fail=drafts.save_failure(AppError("DISK_FULL"))))
        buttons = self.open_dialog_by_nav(window)
        buttons[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open and T["drf_savefail_leave_title"] in self.texts(window.dialog), 10))
        self.settle()
        buttons = self.dialog_buttons(window)
        self.assertEqual(list(buttons), [T["drf_choice_stay"], T["drf_choice_discard_leave"]])
        self.assertTrue(buttons[T["drf_choice_stay"]].hasFocus(), "처음 포커스는 계속 고치기")
        self.assertIn(T["drf_savefail_leave_tail"], " ".join(self.texts(window.dialog)))
        self.assertEqual(window.state.page, "drafts")
        buttons[T["drf_choice_stay"]].click()
        self.settle(2)
        self.assertEqual((window.state.page, window.dialog.is_open), ("drafts", False))
        buttons = self.open_dialog_by_nav(window)
        buttons[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open and T["drf_savefail_leave_title"] in self.texts(window.dialog), 10))
        self.settle()
        self.dialog_buttons(window)[T["drf_choice_discard_leave"]].click()
        self.settle(3)
        self.assertEqual(window.state.page, "topics")

    def test_a_key_shape_in_the_leave_flow_names_the_place_and_does_not_trap_the_user(self):
        window = self.drafted(drafts_provider=provider())
        self.edit_body(window, "\n" + KEY_LINE)
        buttons = self.open_dialog_by_nav(window)
        buttons[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.dialog.is_open and T["drf_savefail_secret_title"] in self.texts(window.dialog), 10))
        self.settle()
        body = " ".join(self.texts(window.dialog))
        self.assertIn("본문에서 1건(GitHub 토큰 1)", body)
        self.assertFalse(SS.leaked(body, KEY_TOKEN))
        self.assertEqual(list(self.dialog_buttons(window)), [T["drf_choice_stay"], T["drf_choice_discard_leave"]])
        self.dialog_buttons(window)[T["drf_choice_discard_leave"]].click()
        self.settle(3)
        self.assertEqual(window.state.page, "topics")

    def test_closing_the_window_with_unsaved_edits_asks_with_the_close_words_and_save_closes_after_saving(self):
        window, fake = self.edited()
        window.close()
        self.settle(3)
        self.assertTrue(window.isVisible() and window.dialog.is_open)
        self.assertEqual(list(self.dialog_buttons(window)), [T["drf_choice_save"], T["drf_choice_discard_close"], T["drf_choice_stay"]])
        self.assertIn(T["drf_close3_body"], " ".join(self.texts(window.dialog)))
        self.dialog_buttons(window)[T["drf_choice_stay"]].click()
        self.settle(2)
        self.assertTrue(window.isVisible())
        window.close()
        self.settle(3)
        self.dialog_buttons(window)[T["drf_choice_save"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: not window.isVisible(), 10))
        self.assertEqual(len(fake.saved), 1)

    def test_closing_and_discarding_closes_without_saving(self):
        window, fake = self.edited()
        window.close()
        self.settle(3)
        self.dialog_buttons(window)[T["drf_choice_discard_close"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: not window.isVisible(), 10))
        self.assertEqual(fake.saved, {})

    def test_closing_while_a_save_runs_waits_for_it_to_finish(self):
        fake = Slow(lambda: CATALOG, saving=True)
        window = self.drafted(drafts_provider=fake)
        self.edit_body(window)
        fake.holding = True
        self.button(window, "act:save").click()
        self.assertTrue(fake.entered.wait(10))
        threading.Timer(1.5, fake.gate.set).start()                                  # 저장이 1.5초 뒤에야 끝난다 — 닫기가 기다리지 않으면 닫기가 돌아온 때 아직 저장이 끝나지 않았다
        window.state.drafts.leave()
        window.close()
        self.assertEqual(len(fake.saved), 1, "닫는 순간에도 저장은 끝까지 갔다(닫기가 저장이 끝나기를 기다렸다)")
        self.settle(3)
        self.assertFalse(window.isVisible())

    def test_a_provider_without_saving_keeps_the_old_two_choice_dialog(self):
        window = self.drafted(drafts_provider=drafts.FakeDraftsProvider(lambda: CATALOG))
        self.edit_body(window)
        window.go("topics")
        self.settle(3)
        self.assertEqual(list(self.dialog_buttons(window)), [T["drf_cancel"], T["drf_leave_ok"]])


class ListTest(SaveBase):
    def with_saved(self, count=3, **more):
        fake = provider(**more)
        window = self.drafted(drafts_provider=fake)
        for number in range(count):
            ui = self.ui(window)
            ui.title.selectAll()
            self.type_ime(ui.title, f"저장한 제목 {number}")                            # 사용자가 치는 것과 같은 길(`textEdited`) — `setText` 는 이 신호를 내지 않는다
            ui.editor.setPlainText(f"저장한 본문 {number}\n둘째 줄")
            self.settle(2)
            self.press_save(window)
            if number + 1 < count:
                window.state.drafts.start_make(**window.drafts_bridge.callbacks())
                self.assertTrue(self.wait_draft(window))
        window.state.drafts.leave()
        window.go("home")
        self.settle()
        return window, fake

    def open_list(self, window):
        window.go("drafts")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.list_state == "ok", 10))
        self.settle()
        self.activate(window)                                                        # 화면을 오간 뒤 창이 활성이 아닌 채로 남는 offscreen 의 모습 — 포커스는 활성 창에서만 말이 된다

    def test_opening_the_menu_without_a_candidate_shows_the_saved_drafts_below_the_empty_card(self):
        window, fake = self.with_saved(3)
        self.open_list(window)
        names = self.texts(window.screen_widget)
        self.assertIn(T["drf_empty_title"], names)
        self.assertIn(f"{T['drf_saved_title']} · {T['drf_saved_count'].format(n=3)}", names)
        rows = self.ui(window).saved_rows
        self.assertEqual(len(rows), 3)
        self.assertEqual([row.title_label.plain_text() for row in rows], ["저장한 제목 2", "저장한 제목 1", "저장한 제목 0"])
        for row in rows:
            self.assertTrue(row.meta_label.plain_text().startswith("후보: "))
            self.assertIn("본문", row.meta_label.plain_text())
            self.assertTrue(row.open_button.accessibleName().startswith("‘저장한 제목"))
            self.assertTrue(row.delete_button.accessibleName().startswith("‘저장한 제목"))

    def test_the_list_reads_nothing_and_changes_nothing_just_by_opening(self):
        window, fake = self.with_saved(2)
        before = dict(fake.saved)
        self.open_list(window)
        self.assertEqual(fake.saved, before)

    def test_without_a_saving_provider_the_empty_screen_has_no_list(self):
        window = self.make(drafts_provider=drafts.FakeDraftsProvider(lambda: CATALOG))
        window.go("drafts")
        self.settle(3)
        self.assertEqual(self.ui(window).saved_rows, [])
        self.assertNotIn(T["drf_saved_title"], self.texts(window.screen_widget))

    def test_an_empty_list_says_so_in_words(self):
        window = self.make(drafts_provider=provider())
        window.go("drafts")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.list_state == "ok", 10))
        self.settle()
        self.assertIn(T["drf_saved_empty"], self.texts(window.screen_widget))

    def test_open_brings_back_the_saved_title_and_body_to_the_character(self):
        window, fake = self.with_saved(2)
        self.open_list(window)
        self.ui(window).saved_rows[0].open_button.click()
        self.assertTrue(self.wait_draft(window))
        ui = self.ui(window)
        self.assertEqual((ui.title.text(), window.state.drafts.title, window.state.drafts.body), ("저장한 제목 1", "저장한 제목 1", "저장한 본문 1\n둘째 줄"))
        self.assertEqual(ui.editor.toPlainText(), "저장한 본문 1\n둘째 줄")
        self.assertEqual(self.saved_status(window), T["drf_state_saved"].format(when=board_view.time_text(fake.saved[window.state.drafts.saved_id].updated_at)))
        self.assertEqual(window.state.drafts.save_state(), "saved")
        window.go("home")
        self.settle(3)
        self.assertEqual(window.state.page, "home", "열기만 하고 고치지 않았으면 나갈 때 묻지 않는다")

    def test_open_keeps_the_saved_line_endings_in_the_controller_though_the_editor_shows_one_kind(self):
        """저장한 글이 CRLF·CR 을 품고 있어도 열기만 하고 고치지 않으면 저장한 글 그대로다(편집기는 줄 끝을 하나로 보이지만 컨트롤러가 저장한 글을 들고 있다) — 열고 곧바로 `저장` 을 눌러도 아무것도 새로 쓰지 않는다."""
        from chanceblog_desktop.content import saved_draft as sd
        stamp, body = "2026-11-05T09:00:00Z", "첫 줄\r\n둘째 줄\r\n\r\n셋째 줄\r마지막 줄"
        draft_id = sd.make_draft_id(stamp, "", "naver_a", "줄 끝 시험", body)
        base = sd.BaseDraft.build("줄 끝 시험", ["줄 끝 시험"], body, [], "", None)
        seeded = sd.SavedDraft.build(draft_id=draft_id, revision=1, created_at=stamp, updated_at=stamp, title="줄 끝 시험", body=body, topic="줄 끝", blog="naver_a", post_type=sd.POST_TYPES[0], base=base)
        fake = provider(saved={draft_id: seeded})
        window = self.make(drafts_provider=fake)
        window.go("drafts")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.list_state == "ok", 10))
        self.settle()
        self.ui(window).saved_rows[0].open_button.click()
        self.assertTrue(self.wait_draft(window))
        self.assertEqual(window.state.drafts.body, body)
        self.assertEqual(window.state.drafts.save_state(), "saved")
        self.button(window, "act:save").click()
        self.assertTrue(self.wait_store(window))
        self.assertEqual(fake.saved[draft_id], seeded, "고치지 않고 저장해도 저장한 글은 그대로다(줄 끝도)")
        window.go("home")
        self.settle(3)
        self.assertEqual(window.state.page, "home")

    def test_open_shows_a_loading_state_then_the_draft_and_back_goes_to_the_topics(self):
        window, fake = self.with_saved(1)
        self.open_list(window)
        self.ui(window).saved_rows[0].open_button.click()
        self.assertTrue(self.wait_draft(window))
        self.button(window, "drf-back").click()
        self.settle(3)
        self.assertEqual(window.state.page, "topics")

    def test_delete_asks_first_and_cancel_is_the_first_focus_and_confirm_removes_only_that_row(self):
        window, fake = self.with_saved(3)
        self.open_list(window)
        before = set(fake.saved)
        self.ui(window).saved_rows[1].delete_button.click()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        buttons = self.dialog_buttons(window)
        self.assertEqual(list(buttons), [T["drf_cancel"], T["drf_delete_ok"]])
        self.assertTrue(buttons[T["drf_cancel"]].hasFocus())
        self.assertIn("저장한 제목 1", " ".join(self.texts(window.dialog)))
        buttons[T["drf_cancel"]].click()
        self.settle(2)
        self.assertEqual(set(fake.saved), before)
        self.ui(window).saved_rows[1].delete_button.click()
        self.settle(3)
        self.dialog_buttons(window)[T["drf_delete_ok"]].click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.list_state == "ok" and not window.state.drafts.store_busy and len(window.state.drafts.listing.rows) == 2, 10))
        self.settle()
        self.assertEqual(len(fake.saved), 2)
        self.assertEqual([row.title_label.plain_text() for row in self.ui(window).saved_rows], ["저장한 제목 2", "저장한 제목 0"])
        self.assertIn(T["drf_deleted_notice"], self.texts(window.screen_widget))

    def test_the_row_buttons_are_in_the_tab_order_after_the_empty_card_button(self):
        window, fake = self.with_saved(2)
        self.open_list(window)
        window.activateWindow()
        rows = self.ui(window).saved_rows
        first = rows[0].open_button
        first.setFocus(Qt.TabFocusReason)
        self.settle(1)
        order = []
        for _ in range(4):
            focus = self.app.focusWidget()
            order.append(focus.property("focus_key"))
            QTest.keyClick(focus, Qt.Key_Tab)
            self.settle(1)
        self.assertEqual(order[:4], ["drf-saved-open:0", "drf-saved-delete:0", "drf-saved-open:1", "drf-saved-delete:1"])

    def test_every_list_button_has_a_reading_name_and_a_big_enough_hit_area(self):
        window, fake = self.with_saved(2)
        self.open_list(window)
        for row in self.ui(window).saved_rows:
            for button in row.stops():
                self.assertTrue(button.accessibleName())
                self.assertGreaterEqual(button.height(), 28)

    def test_the_list_fits_every_window_size_with_no_sideways_scroll(self):
        window, fake = self.with_saved(5)
        self.open_list(window)
        for width, height in SIZES:
            with self.subTest(size=(width, height)):
                window.resize(width, height)
                self.settle(4)
                bar = window.scroll.horizontalScrollBar()
                self.assertEqual(bar.maximum(), 0, "가로 스크롤이 없다")
                viewport = window.scroll.viewport().rect()
                for row in self.ui(window).saved_rows:
                    corner = row.mapTo(window.scroll.viewport(), row.rect().bottomRight())
                    self.assertLessEqual(corner.x(), viewport.right() + 1)

    def test_a_list_that_cannot_be_read_shows_the_error_and_a_retry_button(self):
        fake = provider()
        window = self.make(drafts_provider=fake)
        fake.list_saved = lambda progress, cancelled: (_ for _ in ()).throw(drafts.save_failure(AppError("STORE_CORRUPT")))
        window.go("drafts")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.list_state == "error", 10))
        self.settle()
        self.assertIn(T["drf_saved_error"], self.texts(window.screen_widget))
        fake.list_saved = drafts.FakeDraftsProvider.list_saved.__get__(fake)
        self.button(window, "drf-saved-retry").click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.drafts.list_state == "ok", 10))


class HomeTest(SaveBase):
    def home_with(self, total):
        rows = tuple(services.DraftRow(f"d{number}", f"저장한 초안 {number}", services.SAVED_STAGE, "2026-11-05T01:00:00Z") for number in range(min(total, 5)))
        board = services.sample_board("normal")
        board = services.BoardData(board.channels, services.ListRead("ok", rows, 0, None, total), board.recent, True)
        return services.FakeHomeProvider(board=board)

    def test_the_home_drafts_section_shows_the_count_and_a_small_link_to_the_saved_list(self):
        fake = provider()
        window = self.make(drafts_provider=fake, home=self.home_with(7))
        window.go("home")
        window.reload()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state not in ("loading",), 10))
        self.settle(4)
        names = self.texts(window.screen_widget)
        self.assertIn(T["board_draft_count"].format(n=7), names)
        link = self.button(window, "home-drafts-link")
        self.assertEqual((link.text(), link.accessibleName()), (T["board_draft_link"], T["board_draft_link_a11y"]))
        self.assertIn(T["board_stage_saved"], names)
        link.click()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.page == "drafts" and window.state.drafts.list_state in ("ok", "error"), 10))
        self.settle()
        self.assertEqual(window.state.page, "drafts")
        self.assertIn(T["drf_saved_empty"], self.texts(window.screen_widget))

    def test_a_home_without_a_known_total_has_no_count_and_no_link(self):
        window = self.make(drafts_provider=provider())
        window.go("home")
        window.reload()
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.list_state not in ("loading",), 10))
        self.settle(4)
        self.assertNotIn(T["board_draft_link"], self.texts(window.screen_widget))
        self.assertEqual([key for key in self.buttons(window.screen_widget) if key == "home-drafts-link"], [])


class SourceRulesTest(unittest.TestCase):
    def methods(self):
        tree = ast.parse((QT_DIR / "shell.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AppShell")
        return {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}

    def calls(self, function):
        return {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "") for node in ast.walk(function) if isinstance(node, ast.Call)}

    def dotted(self, function):
        return {ast.unparse(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)}

    def test_the_new_shell_handlers_never_touch_providers_services_files_or_the_network(self):
        methods = self.methods()
        names = ("drf_save_shortcut", "drf_save", "_on_store_done", "_on_store_failed", "_show_store_done", "_show_store_failed", "_after_save", "_after_save_failed", "_continue_after",
                 "_show_leave_choices", "_recover_store", "_start_saved_list", "drf_show_saved", "_drf_show_saved_now", "drf_saved_retry", "drf_saved_open", "drf_saved_delete", "_drf_delete_confirmed")
        for name in names:
            source = "\n".join(ast.unparse(statement) for statement in methods[name].body)
            for forbidden in ("provider", "service.", "sqlite3", "subprocess", "socket", "urllib"):
                self.assertNotIn(forbidden, source, f"{name}: {forbidden}")
            self.assertIsNone(PROVIDER_CALL.search(source), f"{name}: 공급자 함수를 직접 부르지 않는다 — 컨트롤러의 `start_…` 를 거친다")
            self.assertFalse(self.calls(methods[name]) & {"open", "write", "write_text", "write_bytes", "mkdir", "unlink", "rename", "replace"}, name)

    def test_only_drf_save_starts_a_save_and_it_does_so_through_the_controller(self):
        methods = self.methods()
        starters = [name for name, function in methods.items() if "self.state.drafts.start_save" in self.dotted(function)]          # 블로그·Seed 화면의 `start_save` 는 다른 컨트롤러의 것이라 세지 않는다
        self.assertEqual(starters, ["drf_save"])
        self.assertIn("store_bridge", ast.unparse(methods["drf_save"]))

    def test_the_choice_dialog_is_built_in_one_place_and_the_leave_dialogs_all_go_through_it(self):
        methods = self.methods()
        builders = [name for name, function in methods.items() if "show_choice_dialog" in self.calls(function)]
        self.assertEqual(builders, ["_show_leave_choices"])
        users = sorted(name for name, function in methods.items() if "_show_leave_choices" in self.calls(function))
        self.assertEqual(users, ["closeEvent", "drf_show_saved", "go"])

    def test_the_only_ctrl_s_binding_is_the_save_shortcut(self):
        source = (QT_DIR / "shell.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('QKeySequence("Ctrl+S")'), 1)
        self.assertIn("activated=self.drf_save_shortcut", source)

    def test_the_draft_screen_files_still_call_no_service_provider_or_file_function(self):
        for name in ("draft_screen.py", "draft_parts.py"):
            source = (QT_DIR / name).read_text(encoding="utf-8")
            for forbidden in ("chanceblog_desktop.service", "..service", "..content", "..security", "drafts_adapter", "save_draft", "delete_saved", "list_saved", "open_saved", "sqlite3"):
                self.assertNotIn(forbidden, source, f"{name}: {forbidden}")


if __name__ == "__main__":
    unittest.main()
