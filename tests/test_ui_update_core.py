"""`ui/core/updates.py` 시험(UPDATE 설계서 3-7 카드 표, v1update U-5 의 순수 층) — 설정 화면 '업데이트' 카드가 그릴 데이터. Qt 코드는 이 갈래에 없고 PySide6 없이 돈다.

지키는 것:
  1) 상태마다 카드 한 장(표) — 꺼짐에는 단추가 없고(키보드로 갈 곳도 없다), 확인 전·최신에는 '지금 확인', 새 버전에는 '내려받고 설치'(설치가 꺼져 있으면 '릴리스 페이지 열기' 뿐), 확인 중·진행 중에는 주 단추가 없다.
     **주 단추는 많아야 하나**이고 취소는 설치 도구에 넘기기 시작하기 전(내려받기·검증·준비·백업)에만 보인다.
  2) 확인 스위치가 꺼져 있으면 어떤 진행 상태도 '꺼짐' 으로 돌아간다(복구·진행 중인 일은 예외 — 이미 시작된 일을 숨기지 않는다). 확인만 켜고 설치는 꺼진 단계가 보인다.
  3) 휴대용·소스 실행은 새 압축 파일 안내와 '릴리스 페이지 열기' 뿐이다. 복구 안내는 확인 스위치와 상관없이 보이고 복구 단추는 설치 스위치가 켜져 있을 때만 눌린다.
  4) 동적 글은 가리기를 거친다(비밀 모양·긴 글), 영문 상태 이름·오류 코드는 '오류 이름' 줄 말고 글에 없다, 오류는 오류 표의 문구와 카드용 하실 일(명령줄 꼬리 없음)이다. 문구표(`T`)에 합쳐졌고 금지 표현·물결표·웹 주소가 없다.
네트워크·Qt 없이 돈다.
"""
import itertools
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.ui.core import text, update_text, updates  # noqa: E402
from chanceblog_desktop.update import machine, state  # noqa: E402

T = text.T
LAST = state.LastCheck("2026-12-02T03:04:05Z", "AVAILABLE", "1.0.1", "")


def view(**overrides):
    options = dict(check_enabled=True, apply_enabled=True, install_kind="inno", state="IDLE", version="1.0.0", last_check=None, available_version="", summary="", error=None, progress=None, notice="")
    options.update(overrides)
    return updates.card_view(**options)


class CardTableTest(unittest.TestCase):
    def test_each_documented_state_has_its_card(self):
        cases = (
            (dict(state="IDLE"), "idle", T["upd_check"], True, False),
            (dict(state="UP_TO_DATE", last_check=LAST), "up_to_date", T["upd_check"], True, False),
            (dict(state="CHECKING"), "checking", "", False, True),
            (dict(state="AVAILABLE", available_version="1.0.1", summary="글 목록이 더 빨리 열려요."), "available", T["upd_install"], True, False),
            (dict(state="CHECK_FAILED", error=AppError("UPDATE_CHECK_FAILED")), "failed", T["upd_retry"], True, False),
            (dict(state="DOWNLOADING", progress=0.5), "working", "", False, True),
            (dict(state="VERIFYING"), "working", "", False, True),
            (dict(state="READY"), "working", "", False, True),
            (dict(state="BACKING_UP"), "working", "", False, True),
            (dict(state="APPLYING"), "working", "", False, False),
            (dict(state="HANDED_OFF"), "working", "", False, False),
            (dict(state="POST_UPDATE_BOOT"), "booting", "", False, False),
            (dict(state="HEALTH_CHECK"), "booting", "", False, False),
            (dict(state="HEALTHY"), "healthy", T["upd_ok"], True, False),
            (dict(state="UNHEALTHY"), "recovery", T["upd_recover"], True, False),
            (dict(state="RECOVERY_OFFERED"), "recovery", T["upd_recover"], True, False),
            (dict(state="ROLLING_BACK"), "working", "", False, False),
            (dict(state="ROLLED_BACK"), "rolled_back", T["upd_ok"], True, False),
            (dict(state="ROLLBACK_FAILED"), "rollback_failed", T["upd_ok"], True, False),
        )
        seen = set()
        for overrides, key, primary, enabled, cancel in cases:
            with self.subTest(state=overrides["state"]):
                card = view(**overrides)
                self.assertEqual((card.key, card.primary, card.primary_enabled, card.cancel), (key, primary, enabled, cancel))
                self.assertIn(card.key, updates.ICON_KEYS)
                seen.add(overrides["state"])
        self.assertEqual(seen, set(machine.STATES), "상태 기계의 모든 상태가 카드를 가진다")

    def test_every_state_in_every_switch_and_kind_combination_gives_a_card_with_at_most_one_primary_button(self):
        for state_name, check_on, apply_on, kind in itertools.product(machine.STATES, (False, True), (False, True), ("velopack", "inno", "portable", "source", "")):
            with self.subTest(state=state_name, check=check_on, apply=apply_on, kind=kind):
                card = view(state=state_name, check_enabled=check_on, apply_enabled=apply_on, install_kind=kind, available_version="1.0.1", error=AppError("UPDATE_CHECK_FAILED"))
                self.assertIsInstance(card.primary, str)
                self.assertIsInstance(card.lines, tuple)
                self.assertTrue(card.lines and all(isinstance(line, str) and line for line in card.lines))
                if not card.primary:
                    self.assertFalse(card.primary_enabled)
                self.assertTrue(card.a11y.startswith(T["upd_a11y"].split("{")[0]))
                self.assertEqual(card.title, T["upd_title"])

    def test_cancel_is_shown_only_before_the_hand_off_starts(self):
        for state_name in machine.STATES:
            card = view(state=state_name)
            self.assertEqual(card.cancel, state_name in ("CHECKING", "DOWNLOADING", "VERIFYING", "READY", "BACKING_UP"), state_name)
        self.assertEqual(updates.CANCELLABLE, ("DOWNLOADING", "VERIFYING", "READY", "BACKING_UP"))
        for state_name in machine.NO_CANCEL:
            self.assertFalse(view(state=state_name).cancel, state_name)
            self.assertFalse(machine.Machine(state_name).can("cancel"), "카드와 상태 기계가 같은 말을 한다")
        for state_name in ("CHECKING", "DOWNLOADING", "VERIFYING", "READY", "BACKING_UP"):
            self.assertTrue(machine.Machine(state_name).can("cancel"), state_name)

    def test_the_folder_update_action_appears_only_with_the_apply_switch_on_an_installed_kind_in_a_quiet_state(self):
        """'파일에서 업데이트…'(설계 3-7 표의 마지막 행, 3-11) — 접속이 없어 확인 스위치와 상관없다. 모든 상태 x 스위치 x 설치 종류에서 손으로 적은 식과 같다."""
        for state_name, check_on, apply_on, kind in itertools.product(machine.STATES, (False, True), (False, True), ("velopack", "inno", "portable", "source", "")):
            expected = T["upd_from_folder"] if apply_on and kind in ("inno",) and state_name in ("IDLE", "UP_TO_DATE", "AVAILABLE", "CHECK_FAILED") else ""
            with self.subTest(state=state_name, check=check_on, apply=apply_on, kind=kind):
                card = view(state=state_name, check_enabled=check_on, apply_enabled=apply_on, install_kind=kind, available_version="1.0.1", error=AppError("UPDATE_CHECK_FAILED"))
                self.assertEqual(card.folder_action, expected)
        self.assertEqual(updates.FOLDER_STATES, ("IDLE", "UP_TO_DATE", "AVAILABLE", "CHECK_FAILED"))
        self.assertEqual(T["upd_from_folder"], "파일에서 업데이트…")
        self.assertEqual(view(state="IDLE", check_enabled=False, apply_enabled=True).primary, "", "꺼짐 카드의 주 단추는 여전히 없다 — 파일에서 업데이트는 주 단추가 아니다")

    def test_the_card_treats_exactly_the_adapters_installed_kinds_as_installed_and_velopack_is_not_one(self):
        """카드의 '설치형' 판단(`ui/core` 는 `update` 를 가져오지 않아 글자로 적는다)이 적용 어댑터가 있는 설치 종류(`apply.INSTALLED_KINDS`)와 같다 — 설치 도구가 Inno 로 정해진 뒤 Velopack 은 설치형이 아니다(U-4)."""
        from chanceblog_desktop.update import apply
        self.assertEqual(apply.INSTALLED_KINDS, ("inno",))
        for kind in ("inno", "velopack", "portable", "source", "", "INNO", "msi"):
            with self.subTest(kind=kind):
                card = view(state="IDLE", install_kind=kind)
                self.assertEqual(bool(card.folder_action), kind in apply.INSTALLED_KINDS)

    def test_progress_is_a_fraction_or_unknown_never_a_wrong_value(self):
        self.assertEqual(view(state="DOWNLOADING", progress=0.25).progress, 0.25)
        for bad in (None, -0.1, 1.5, "0.5", True, float("nan")):
            self.assertIsNone(view(state="DOWNLOADING", progress=bad).progress, repr(bad))
        self.assertTrue(view(state="DOWNLOADING").busy)
        self.assertFalse(view(state="IDLE").busy)


class SwitchTest(unittest.TestCase):
    def test_while_the_check_switch_is_off_the_card_is_the_disabled_one_with_no_button(self):
        for state_name in ("IDLE", "UP_TO_DATE", "CHECK_FAILED", "AVAILABLE", "CHECKING"):
            card = view(state=state_name, check_enabled=False, apply_enabled=False)
            self.assertEqual((card.key, card.primary, card.primary_enabled, card.cancel, card.busy), ("disabled", "", False, False, False), state_name)
            self.assertIn(T["upd_disabled"], card.lines)
            self.assertIn(T["upd_disabled_help"], card.lines)
        self.assertEqual(view(state="IDLE", check_enabled=False, apply_enabled=True).key, "disabled", "설치만 켜져 있어도 확인이 꺼져 있으면 꺼짐")

    def test_things_already_started_or_needing_the_user_are_not_hidden_by_a_closed_check_switch(self):
        for state_name, key in (("RECOVERY_OFFERED", "recovery"), ("ROLLING_BACK", "working"), ("ROLLED_BACK", "rolled_back"), ("ROLLBACK_FAILED", "rollback_failed"), ("HEALTHY", "healthy"), ("POST_UPDATE_BOOT", "booting"),
                                ("DOWNLOADING", "working"), ("APPLYING", "working")):
            self.assertEqual(view(state=state_name, check_enabled=False, apply_enabled=False).key, key, state_name)

    def test_the_recovery_button_is_pressable_only_when_the_apply_switch_is_on_and_there_is_a_later_choice(self):
        card = view(state="RECOVERY_OFFERED", apply_enabled=False)
        self.assertEqual((card.primary, card.primary_enabled, card.secondary), (T["upd_recover"], False, T["upd_later"]))
        self.assertTrue(view(state="RECOVERY_OFFERED", apply_enabled=True).primary_enabled)

    def test_check_on_and_install_off_shows_the_new_version_and_only_the_release_page(self):
        card = view(state="AVAILABLE", apply_enabled=False, available_version="1.0.1", summary="새 소식")
        self.assertEqual((card.key, card.primary, card.primary_enabled), ("available_manual", T["upd_open_release"], True))
        self.assertIn(T["upd_install_off"], card.lines)
        self.assertNotIn(T["upd_install"], (card.primary, *card.lines))
        full = view(state="AVAILABLE", apply_enabled=True, available_version="1.0.1")
        self.assertEqual(full.primary, T["upd_install"])
        self.assertIn(T["upd_backup_first"], full.lines)

    def test_portable_and_source_runs_get_guidance_and_the_release_page_only(self):
        for kind in ("portable", "source"):
            for state_name in ("IDLE", "UP_TO_DATE", "AVAILABLE", "CHECK_FAILED"):
                card = view(state=state_name, install_kind=kind, available_version="1.0.1")
                self.assertEqual((card.key, card.primary, card.primary_enabled), ("portable", T["upd_open_release"], True), (kind, state_name))
                self.assertIn(T["upd_portable"], card.lines)
        self.assertIn(T["upd_portable_new"].format(version="v1.0.1"), view(state="AVAILABLE", install_kind="portable", available_version="1.0.1").lines)


class TextTest(unittest.TestCase):
    def test_the_fixed_texts_are_merged_into_the_ui_table_and_follow_the_style_rules(self):
        for key, value in update_text.UPDATE_T.items():
            self.assertEqual(T[key], value, key)
            self.assertTrue(key.startswith("upd_"), key)
            self.assertNotIn(chr(0x7E), value, key)
            self.assertIsNone(re.search(r"(?i)https?://|www\.", value), key)
            self.assertNotIn("{" * 2, value, key)
            for word in text.FORBIDDEN:
                self.assertNotIn(word, value, key)
            for word in ("자동으로", "몰래", "알아서"):
                self.assertNotIn(word, value, f"{key}: 확인은 사용자가 누를 때만이다")
        self.assertEqual(len(update_text.UPDATE_T), len(set(update_text.UPDATE_T)))

    def test_no_state_name_or_error_code_leaks_into_the_sentences_except_the_one_error_name_line(self):
        for state_name in machine.STATES:
            card = view(state=state_name, available_version="1.0.1", error=AppError("UPDATE_CHECK_FAILED"))
            for line in card.lines:
                if line.startswith(T["upd_code"].split("{")[0]):
                    continue
                self.assertIsNone(re.search(r"\b[A-Z][A-Z_]{5,}\b", line), (state_name, line))
        failed = view(state="CHECK_FAILED", error=AppError("UPDATE_SIGNATURE_INVALID"))
        self.assertEqual(failed.code, "UPDATE_SIGNATURE_INVALID")
        self.assertIn(T["upd_code"].format(code="UPDATE_SIGNATURE_INVALID"), failed.lines)

    def test_an_error_shows_its_table_message_and_the_card_action_without_the_command_tail(self):
        from chanceblog_desktop.errors import CLI_TAIL_LABEL, CATALOG
        for code in ("UPDATE_SIGNATURE_INVALID", "UPDATE_DOWNGRADE_BLOCKED", "UPDATE_MANIFEST_EXPIRED", "UPDATE_CHECK_FAILED", "UPDATE_NEEDS_MANUAL_INSTALL"):
            with self.subTest(code=code):
                card = view(state="CHECK_FAILED", error=AppError(code))
                shown = AppError(code).rendered()
                self.assertIn(shown.message.replace("**", ""), " ".join(card.lines))
                self.assertIn(shown.card_action, " ".join(card.lines))
                self.assertNotIn(CLI_TAIL_LABEL, " ".join(card.lines))
        self.assertIn("UPDATE_SIGNATURE_INVALID", CATALOG)

    def test_a_non_error_failed_state_still_shows_a_plain_sentence_and_the_retry_button(self):
        card = view(state="CHECK_FAILED", error=None)
        self.assertEqual((card.lines, card.primary, card.code), ((T["upd_failed"], T["upd_failed"]), T["upd_retry"], ""))

    def test_dynamic_text_is_masked_and_shortened(self):
        canary = "AIza" + "SyCANARYCANARYCANARYCANARYCANARY123"
        card = view(state="AVAILABLE", available_version="1.0.1", summary=f"설명 {canary} " + "길" * 800)
        shown = " ".join(card.lines)
        self.assertNotIn(canary, shown)
        self.assertLess(max(len(line) for line in card.lines), 600)
        self.assertEqual(view(state="IDLE", version="x" * 500).lines[0].count("x") < 100, True)

    def test_the_version_and_time_lines(self):
        self.assertEqual(view(state="IDLE").lines[:2], (T["upd_version_line"].format(version="v1.0.0"), T["upd_never_checked"]))
        self.assertEqual(view(state="UP_TO_DATE", last_check=LAST).lines[0], T["upd_up_to_date"].format(version="v1.0.0"))
        self.assertIn(T["upd_last_checked"].format(when="2026-12-02 03:04:05 (UTC)"), view(state="IDLE", last_check=LAST).lines)
        self.assertEqual(view(state="IDLE", version="").lines[0], T["upd_unknown_version"])
        self.assertIn(T["upd_notice_not_applied"], view(state="IDLE", notice="not_applied").lines)
        self.assertNotIn(T["upd_notice_not_applied"], view(state="IDLE", notice="").lines)


class SourceShapeTest(unittest.TestCase):
    def test_the_module_is_pure_no_qt_no_files_no_connection(self):
        import ast
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "core" / "updates.py").read_text(encoding="utf-8"))
        names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(names & {"PySide6", "PyQt5", "PyQt6", "http", "ssl", "socket", "subprocess", "os", "pathlib", "json", "urllib", "ctypes"}, names)
        body = (ROOT / "src" / "chanceblog_desktop" / "ui" / "core" / "updates.py").read_text(encoding="utf-8")
        for word in ("open(", "read_text", "capabilities", "datetime.now", "time.time"):
            self.assertNotIn(word, body, word)


if __name__ == "__main__":
    unittest.main()
