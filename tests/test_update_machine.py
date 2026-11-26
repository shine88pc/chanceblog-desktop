"""`update/machine.py` 시험(UPDATE 설계서 3-5 전이 표, v1update U-2) — 모든 전이와 **모든 불가능한 전이**.

지키는 것:
  1) (상태 19 × 사건 26) 짝을 **전부** 훑어 표에 있는 짝만 허용되고 나머지는 `IllegalTransition` 이며 거절돼도 기계의 상태가 바뀌지 않는다.
  2) 설계서의 전이 표(코드와 따로 적은 값)와 정확히 같다 — 한 줄이 빠지거나 더해지면 빨개진다.
  3) 안전한 순서: 백업을 건너뛰는 길이 없다(`APPLYING` 은 `BACKING_UP` 에서 백업이 완료된 사건으로만 들어간다), 설치 도구에 넘기기 시작한 뒤에는 취소가 없다, 실패는 모두 IDLE 로 돌아가 지금 판을 건드리지 않는다,
     복구는 사용자가 '복구' 를 눌러야(`click_recover`) 시작한다(`RECOVERY_OFFERED` 에서만, 다른 어떤 길도 `ROLLING_BACK` 으로 가지 않는다).
  4) 모든 상태에 닿을 수 있고(IDLE 에서 사건만으로) 끝 상태는 `HANDED_OFF` 하나뿐이다.
네트워크·파일 없이 돈다.
"""
import itertools
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.update import machine as m  # noqa: E402

# 설계서 3-5 의 전이 표를 코드와 따로 적은 값(상태, 사건, 다음)
DESIGN = (
    ("IDLE", "click_check", "CHECKING"), ("UP_TO_DATE", "click_check", "CHECKING"), ("CHECK_FAILED", "click_check", "CHECKING"),
    ("CHECKING", "check_available", "AVAILABLE"), ("CHECKING", "check_up_to_date", "UP_TO_DATE"), ("CHECKING", "check_error", "CHECK_FAILED"), ("CHECKING", "cancel", "IDLE"),
    ("AVAILABLE", "click_install", "DOWNLOADING"), ("AVAILABLE", "dismiss", "IDLE"),
    ("DOWNLOADING", "download_done", "VERIFYING"), ("DOWNLOADING", "step_failed", "IDLE"), ("DOWNLOADING", "cancel", "IDLE"),
    ("VERIFYING", "verify_ok", "READY"), ("VERIFYING", "step_failed", "IDLE"), ("VERIFYING", "cancel", "IDLE"),
    ("READY", "proceed", "BACKING_UP"), ("READY", "cancel", "IDLE"),
    ("BACKING_UP", "backup_complete", "APPLYING"), ("BACKING_UP", "step_failed", "IDLE"), ("BACKING_UP", "cancel", "IDLE"),
    ("APPLYING", "handed_off", "HANDED_OFF"), ("APPLYING", "handoff_failed", "IDLE"),
    ("IDLE", "boot_pending_matches", "POST_UPDATE_BOOT"), ("IDLE", "boot_recovery_needed", "RECOVERY_OFFERED"), ("IDLE", "boot_not_applied", "IDLE"),
    ("POST_UPDATE_BOOT", "start_health_check", "HEALTH_CHECK"), ("POST_UPDATE_BOOT", "migration_failed", "UNHEALTHY"),
    ("HEALTH_CHECK", "health_ok", "HEALTHY"), ("HEALTH_CHECK", "health_failed", "UNHEALTHY"),
    ("UNHEALTHY", "offer_recovery", "RECOVERY_OFFERED"),
    ("RECOVERY_OFFERED", "click_recover", "ROLLING_BACK"), ("RECOVERY_OFFERED", "dismiss", "IDLE"),
    ("ROLLING_BACK", "rollback_done", "ROLLED_BACK"), ("ROLLING_BACK", "rollback_failed", "ROLLBACK_FAILED"),
    ("HEALTHY", "ack", "IDLE"), ("ROLLED_BACK", "ack", "IDLE"), ("ROLLBACK_FAILED", "ack", "IDLE"),
)


class ExhaustiveTest(unittest.TestCase):
    def test_every_state_event_pair_is_legal_only_if_the_design_table_lists_it(self):
        legal = {(state, event): after for state, event, after in DESIGN}
        checked = 0
        for state, event in itertools.product(m.STATES, m.EVENTS):
            with self.subTest(state=state, event=event):
                machine = m.Machine(state)
                if (state, event) in legal:
                    self.assertEqual(m.next_state(state, event), legal[(state, event)])
                    self.assertEqual(machine.send(event), legal[(state, event)])
                    self.assertTrue(Machine_can(state, event))
                else:
                    with self.assertRaises(m.IllegalTransition) as caught:
                        m.next_state(state, event)
                    self.assertEqual((caught.exception.state, caught.exception.event), (state, event))
                    with self.assertRaises(m.IllegalTransition):
                        machine.send(event)
                    self.assertEqual((machine.state, machine.history), (state, [state]), "거절돼도 상태가 바뀌지 않는다")
                    self.assertFalse(Machine_can(state, event))
                checked += 1
        self.assertEqual(checked, len(m.STATES) * len(m.EVENTS))
        self.assertEqual(len(m.STATES), 19)
        self.assertEqual(len(m.EVENTS), 26)

    def test_the_table_has_exactly_the_design_rows(self):
        self.assertEqual(sorted((state, event, after) for (state, event), after in m.TRANSITIONS.items()), sorted(DESIGN))
        self.assertEqual(len(m.TRANSITIONS), len(DESIGN))

    def test_states_and_events_have_no_duplicates_and_every_table_name_is_declared(self):
        self.assertEqual(len(set(m.STATES)), len(m.STATES))
        self.assertEqual(len(set(m.EVENTS)), len(m.EVENTS))
        for (state, event), after in m.TRANSITIONS.items():
            self.assertIn(state, m.STATES)
            self.assertIn(event, m.EVENTS)
            self.assertIn(after, m.STATES)
        for event in m.EVENTS:
            self.assertTrue(any(key[1] == event for key in m.TRANSITIONS), f"{event} 는 어디에도 쓰이지 않는다")

    def test_garbage_inputs_are_illegal_not_crashes(self):
        for state, event in ((None, "ack"), ("IDLE", None), (["IDLE"], "ack"), ("idle", "click_check"), ("IDLE", "CLICK_CHECK"), ({}, {})):
            with self.assertRaises(m.IllegalTransition):
                m.next_state(state, event)
        with self.assertRaises(ValueError):
            m.Machine("NOT_A_STATE")


def Machine_can(state, event):
    return m.Machine(state).can(event)


class SafetyShapeTest(unittest.TestCase):
    def sources_of(self, target):
        return sorted((state, event) for (state, event), after in m.TRANSITIONS.items() if after == target)

    def test_applying_is_entered_only_from_backing_up_by_a_completed_backup(self):
        self.assertEqual(self.sources_of("APPLYING"), [("BACKING_UP", "backup_complete")])
        self.assertEqual(self.sources_of("BACKING_UP"), [("READY", "proceed")])
        self.assertEqual(self.sources_of("READY"), [("VERIFYING", "verify_ok")])
        self.assertEqual(self.sources_of("VERIFYING"), [("DOWNLOADING", "download_done")])
        self.assertEqual(self.sources_of("DOWNLOADING"), [("AVAILABLE", "click_install")])
        for event in m.EVENTS:
            self.assertFalse(m.Machine("READY").can(event) and m.next_state("READY", event) == "APPLYING")

    def test_the_happy_path_walks_every_step_in_order(self):
        machine = m.Machine()
        for event in ("click_check", "check_available", "click_install", "download_done", "verify_ok", "proceed", "backup_complete", "handed_off"):
            machine.send(event)
        self.assertEqual(machine.history, ["IDLE", "CHECKING", "AVAILABLE", "DOWNLOADING", "VERIFYING", "READY", "BACKING_UP", "APPLYING", "HANDED_OFF"])

    def test_nothing_can_be_cancelled_once_the_hand_off_started(self):
        for state in m.NO_CANCEL:
            self.assertFalse(m.Machine(state).can("cancel"), state)
        for state in ("CHECKING", "DOWNLOADING", "VERIFYING", "READY", "BACKING_UP"):
            self.assertEqual(m.next_state(state, "cancel"), "IDLE")
        self.assertEqual(m.NO_CANCEL, ("APPLYING", "HANDED_OFF"))

    def test_every_failure_event_goes_back_to_idle_and_only_the_check_failure_has_its_own_state(self):
        for (state, event), after in m.TRANSITIONS.items():
            if event in ("step_failed", "handoff_failed"):
                self.assertEqual(after, "IDLE", (state, event))
        self.assertEqual(m.next_state("CHECKING", "check_error"), "CHECK_FAILED")

    def test_rolling_back_starts_only_when_the_user_clicks_recover_from_the_offer(self):
        self.assertEqual(self.sources_of("ROLLING_BACK"), [("RECOVERY_OFFERED", "click_recover")])
        self.assertEqual(self.sources_of("RECOVERY_OFFERED"), [("IDLE", "boot_recovery_needed"), ("UNHEALTHY", "offer_recovery")])
        self.assertEqual(m.next_state("RECOVERY_OFFERED", "dismiss"), "IDLE", "나중에 → 아무것도 하지 않는다")

    def test_the_post_update_states_are_reached_only_by_the_boot_hook_events(self):
        self.assertEqual(self.sources_of("POST_UPDATE_BOOT"), [("IDLE", "boot_pending_matches")])
        self.assertEqual(self.sources_of("HEALTHY"), [("HEALTH_CHECK", "health_ok")])
        self.assertEqual(self.sources_of("HEALTH_CHECK"), [("POST_UPDATE_BOOT", "start_health_check")])
        self.assertEqual(sorted(self.sources_of("UNHEALTHY")), [("HEALTH_CHECK", "health_failed"), ("POST_UPDATE_BOOT", "migration_failed")])

    def test_every_state_is_reachable_from_idle_and_only_handed_off_is_a_dead_end(self):
        reached, frontier = {"IDLE"}, ["IDLE"]
        while frontier:
            state = frontier.pop()
            for event in m.allowed_events(state):
                after = m.next_state(state, event)
                if after not in reached:
                    reached.add(after)
                    frontier.append(after)
        self.assertEqual(reached, set(m.STATES))
        self.assertEqual([state for state in m.STATES if not m.allowed_events(state)], ["HANDED_OFF"])

    def test_allowed_events_lists_the_table_order(self):
        self.assertEqual(m.allowed_events("IDLE"), ("click_check", "boot_pending_matches", "boot_recovery_needed", "boot_not_applied"))
        self.assertEqual(m.allowed_events("HANDED_OFF"), ())


class SourceShapeTest(unittest.TestCase):
    def test_the_module_is_pure(self):
        import ast
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "update" / "machine.py").read_text(encoding="utf-8"))
        imports = sorted({alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)})
        self.assertEqual(imports, ["__future__"])


if __name__ == "__main__":
    unittest.main()
