"""업데이트 상태 기계의 전이 표(UPDATE 설계서 3-5) — 순수하다(파일·접속·시계 없음). 허용되는 전이만 표에 있고 그 밖의 (상태, 사건) 짝은 모두 `IllegalTransition` 이다(시험이 모든 짝을 훑는다).

흐름: IDLE → CHECKING → UP_TO_DATE·AVAILABLE·CHECK_FAILED → (사용자가 '내려받고 설치') DOWNLOADING → VERIFYING → READY → BACKING_UP → APPLYING → HANDED_OFF(앱이 곧 정상 종료).
새 판이 처음 켜지면 시작 후크(`state.note_boot`)가 POST_UPDATE_BOOT 로 시작하고 HEALTH_CHECK → HEALTHY 로 끝나거나 UNHEALTHY → RECOVERY_OFFERED(연속 두 번 정상 표식이 없었다) → ROLLING_BACK → ROLLED_BACK·ROLLBACK_FAILED 로 간다.
실패(내려받기·검증·백업·넘기기)는 IDLE 로 돌아가고 **지금 판은 그대로**다(`UPDATE_*` 오류 코드는 흐름이 알린다). 취소는 설치를 시작하기 전(APPLYING 이전)까지만 된다.
이 표는 어떤 일을 하라고 시키지 않는다 — 단계마다 해야 할 일(백업 완료 확인·`pending` 기록·`last_seq` 올리기)은 `service/update_flow.py` 가 하고, 순서가 틀린 호출은 이 표가 거절한다.
"""
from __future__ import annotations

IDLE = "IDLE"
CHECKING = "CHECKING"
UP_TO_DATE = "UP_TO_DATE"
AVAILABLE = "AVAILABLE"
CHECK_FAILED = "CHECK_FAILED"
DOWNLOADING = "DOWNLOADING"
VERIFYING = "VERIFYING"
READY = "READY"
BACKING_UP = "BACKING_UP"
APPLYING = "APPLYING"
HANDED_OFF = "HANDED_OFF"
POST_UPDATE_BOOT = "POST_UPDATE_BOOT"
HEALTH_CHECK = "HEALTH_CHECK"
HEALTHY = "HEALTHY"
UNHEALTHY = "UNHEALTHY"
RECOVERY_OFFERED = "RECOVERY_OFFERED"
ROLLING_BACK = "ROLLING_BACK"
ROLLED_BACK = "ROLLED_BACK"
ROLLBACK_FAILED = "ROLLBACK_FAILED"

STATES = (IDLE, CHECKING, UP_TO_DATE, AVAILABLE, CHECK_FAILED, DOWNLOADING, VERIFYING, READY, BACKING_UP, APPLYING, HANDED_OFF, POST_UPDATE_BOOT, HEALTH_CHECK, HEALTHY, UNHEALTHY, RECOVERY_OFFERED,
          ROLLING_BACK, ROLLED_BACK, ROLLBACK_FAILED)

CLICK_CHECK = "click_check"                    # 사용자가 '지금 확인'
CHECK_AVAILABLE = "check_available"            # 서명·규칙을 통과한 더 높은 판
CHECK_UP_TO_DATE = "check_up_to_date"
CHECK_ERROR = "check_error"
CLICK_INSTALL = "click_install"                # '내려받고 설치' + 확인창
DOWNLOAD_DONE = "download_done"
VERIFY_OK = "verify_ok"
PROCEED = "proceed"                            # 검증된 파일로 백업부터 시작
BACKUP_COMPLETE = "backup_complete"            # 백업 상태가 완료(부분·실패는 이 사건이 아니다)
HANDED_OFF_OK = "handed_off"                   # 설치 도구에 넘김 성공
HANDOFF_FAILED = "handoff_failed"
STEP_FAILED = "step_failed"                    # 내려받기·검증·백업 단계의 실패
CANCEL = "cancel"
BOOT_PENDING_MATCHES = "boot_pending_matches"  # 시작 후크: pending.to 가 지금 버전이고 시작 전 횟수가 기준 미만
BOOT_RECOVERY_NEEDED = "boot_recovery_needed"  # 시작 후크: 시작 전 횟수가 기준 이상
BOOT_NOT_APPLIED = "boot_not_applied"          # 시작 후크: pending 이 있는데 지금 버전이 pending.from
START_HEALTH_CHECK = "start_health_check"
HEALTH_OK = "health_ok"
HEALTH_FAILED = "health_failed"
MIGRATION_FAILED = "migration_failed"          # 새 판의 첫 시작에서 데이터 변환이 실패해 기존 코드가 백업으로 되돌림
OFFER_RECOVERY = "offer_recovery"
CLICK_RECOVER = "click_recover"                # 사용자가 '복구'
DISMISS = "dismiss"                            # 나중에 · 안내 확인
ROLLBACK_DONE = "rollback_done"
ROLLBACK_FAILED_EVENT = "rollback_failed"
ACK = "ack"

EVENTS = (CLICK_CHECK, CHECK_AVAILABLE, CHECK_UP_TO_DATE, CHECK_ERROR, CLICK_INSTALL, DOWNLOAD_DONE, VERIFY_OK, PROCEED, BACKUP_COMPLETE, HANDED_OFF_OK, HANDOFF_FAILED, STEP_FAILED, CANCEL,
          BOOT_PENDING_MATCHES, BOOT_RECOVERY_NEEDED, BOOT_NOT_APPLIED, START_HEALTH_CHECK, HEALTH_OK, HEALTH_FAILED, MIGRATION_FAILED, OFFER_RECOVERY, CLICK_RECOVER, DISMISS, ROLLBACK_DONE,
          ROLLBACK_FAILED_EVENT, ACK)

# (지금 상태, 사건) → 다음 상태. 허용되는 전이의 전부다.
TRANSITIONS = {
    (IDLE, CLICK_CHECK): CHECKING,
    (UP_TO_DATE, CLICK_CHECK): CHECKING,
    (CHECK_FAILED, CLICK_CHECK): CHECKING,
    (CHECKING, CHECK_AVAILABLE): AVAILABLE,
    (CHECKING, CHECK_UP_TO_DATE): UP_TO_DATE,
    (CHECKING, CHECK_ERROR): CHECK_FAILED,
    (CHECKING, CANCEL): IDLE,
    (AVAILABLE, CLICK_INSTALL): DOWNLOADING,
    (AVAILABLE, DISMISS): IDLE,
    (DOWNLOADING, DOWNLOAD_DONE): VERIFYING,
    (DOWNLOADING, STEP_FAILED): IDLE,
    (DOWNLOADING, CANCEL): IDLE,
    (VERIFYING, VERIFY_OK): READY,
    (VERIFYING, STEP_FAILED): IDLE,
    (VERIFYING, CANCEL): IDLE,
    (READY, PROCEED): BACKING_UP,
    (READY, CANCEL): IDLE,
    (BACKING_UP, BACKUP_COMPLETE): APPLYING,
    (BACKING_UP, STEP_FAILED): IDLE,
    (BACKING_UP, CANCEL): IDLE,
    (APPLYING, HANDED_OFF_OK): HANDED_OFF,
    (APPLYING, HANDOFF_FAILED): IDLE,
    (IDLE, BOOT_PENDING_MATCHES): POST_UPDATE_BOOT,
    (IDLE, BOOT_RECOVERY_NEEDED): RECOVERY_OFFERED,
    (IDLE, BOOT_NOT_APPLIED): IDLE,
    (POST_UPDATE_BOOT, START_HEALTH_CHECK): HEALTH_CHECK,
    (POST_UPDATE_BOOT, MIGRATION_FAILED): UNHEALTHY,
    (HEALTH_CHECK, HEALTH_OK): HEALTHY,
    (HEALTH_CHECK, HEALTH_FAILED): UNHEALTHY,
    (UNHEALTHY, OFFER_RECOVERY): RECOVERY_OFFERED,
    (RECOVERY_OFFERED, CLICK_RECOVER): ROLLING_BACK,
    (RECOVERY_OFFERED, DISMISS): IDLE,
    (ROLLING_BACK, ROLLBACK_DONE): ROLLED_BACK,
    (ROLLING_BACK, ROLLBACK_FAILED_EVENT): ROLLBACK_FAILED,
    (HEALTHY, ACK): IDLE,
    (ROLLED_BACK, ACK): IDLE,
    (ROLLBACK_FAILED, ACK): IDLE,
}

# 사용자가 더는 취소할 수 없는 상태(설치 도구에 넘기는 일이 시작됐다)
NO_CANCEL = (APPLYING, HANDED_OFF)


class IllegalTransition(Exception):
    """표에 없는 (상태, 사건) — 호출 순서가 틀렸다. `state`·`event` 는 고정 이름이다."""

    def __init__(self, state, event):
        super().__init__(f"{state} + {event}")
        self.state = state
        self.event = event


def next_state(state, event):
    """표대로 다음 상태. 표에 없으면 `IllegalTransition`(아무것도 바뀌지 않는다)."""
    try:
        return TRANSITIONS[(state, event)]
    except (KeyError, TypeError):
        raise IllegalTransition(str(state)[:40], str(event)[:40]) from None


def allowed_events(state):
    """그 상태에서 허용되는 사건들(표의 순서)."""
    return tuple(event for (known, event) in TRANSITIONS if known == state)


class Machine:
    """상태 하나와 지나온 길. `send(사건)` 이 표대로 옮기고 새 상태를 돌려준다(틀린 사건이면 상태를 바꾸지 않고 IllegalTransition)."""

    def __init__(self, state=IDLE):
        if state not in STATES:
            raise ValueError("모르는 상태")
        self.state = state
        self.history = [state]

    def send(self, event):
        self.state = next_state(self.state, event)
        self.history.append(self.state)
        return self.state

    def can(self, event):
        return (self.state, event) in TRANSITIONS


__all__ = ["EVENTS", "IllegalTransition", "Machine", "NO_CANCEL", "STATES", "TRANSITIONS", "allowed_events", "next_state"]
