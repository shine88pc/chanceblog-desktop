"""복구 모드(UPDATE 설계서 3-6) — 새 판이 연속 두 번 제대로 켜지지 않았을 때의 안내 데이터와 복구 순서. 순수 판정 + **주입한 부품**을 부르는 순서 조정이다(파일·접속·하위 프로세스를 직접 만지지 않는다).

원칙: **사용자가 결정한다** — 앱은 낮은 판을 몰래 깔지 않는다. 복구는 안내 상자에서 사용자가 '복구'를 눌러야 시작한다(상자는 Qt 에 기대지 않는 윈도 메시지 상자 — 새 판이 Qt 때문에 안 켜질 수 있다. 상자를 띄우는 코드는 시작 파일 쪽이고
이 모듈은 상자에 들어갈 **글과 단추 이름**만 만든다). 낮은 판 허용은 `pending.from` 하나로 제한된다(임의의 옛 판으로 되돌리는 길이 아니다 — 매니페스트 검사의 `recovery_target`).
복구 순서(어느 단계에서 실패해도 거기서 멈추고 `UPDATE_ROLLBACK_FAILED` 로 손으로 하는 방법을 안내한다):
  1 업데이트 잠금 잡기(이미 진행 중이면 `UPDATE_IN_PROGRESS` 그대로 — 아무것도 시작하지 않았다)
  2 데이터: **이관이 일어났거나 표식이 없던 경우에만** 업데이트 직전 백업을 복원한다(복원 직전 안전 사본이 먼저 만들어진다). 이관 전에 멈춘 것이 분명하면(`data_migrated()` 가 False) 복원하지 않는다 — 새 판에서 한 일을 잃지 않게. 모르면(None) 복원한다.
  3 프로그램: 이전 판의 검증된 설치 파일을 구한다(보관해 둔 것이 있으면 그것, 없으면 이전 릴리스의 서명된 매니페스트와 파일을 복구 모드에서만 다시 받는다 — 서명·해시 검증은 똑같다)
  4 적용 어댑터로 설치 → 5 결과 기록(`ROLLED_BACK`). 잠금은 어느 경우든 푼다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..errors import AppError, render
from . import state as state_module
from . import versions

PROMPT_TITLE = "ChanceBlog Desktop 업데이트 복구"
BUTTON_RECOVER = "복구"
BUTTON_LATER = "나중에"
STEP_LOCK = "lock"
STEP_DATA = "data"
STEP_INSTALLER = "installer"
STEP_APPLY = "apply"
STEP_RECORD = "record"
STEPS = (STEP_LOCK, STEP_DATA, STEP_INSTALLER, STEP_APPLY, STEP_RECORD)
RESULT_ROLLED_BACK = "rolled_back"
RESULT_FAILED = "rollback_failed"


@dataclass(frozen=True)
class RecoveryPrompt:
    """안내 상자에 들어갈 데이터 — 제목·본문(오류 표의 문구 그대로)·두 단추의 이름. 단추를 눌러야만 복구가 시작된다."""
    title: str
    text: str
    recover_label: str
    later_label: str


@dataclass(frozen=True)
class RecoveryOutcome:
    restored_data: bool
    steps: tuple


class RollbackFailure(AppError):
    """복구 도중 실패 — 오류 코드는 `UPDATE_ROLLBACK_FAILED`, `step` 은 어느 단계였는지(고정 낱말), `cause_code` 는 그 단계의 원래 오류 코드(없으면 빈 글)다. 글·경로는 담지 않는다."""

    def __init__(self, step, cause_code=""):
        super().__init__("UPDATE_ROLLBACK_FAILED", detail=f"step:{step} cause:{cause_code or 'none'}")
        self.step = step
        self.cause_code = cause_code


def needs_recovery(state, current_version):
    """복구를 안내해야 하는가 — `pending.to` 가 지금 버전이고 정상 표식 없이 이미 기준 횟수 시작했다."""
    pending = getattr(state, "pending", None)
    if pending is None or versions.parse_version(current_version) is None:
        return False
    return versions.compare(current_version, pending.to_version) == 0 and pending.boot_attempts >= state_module.RECOVERY_AFTER_FAILED_BOOTS


def prompt_for(pending):
    """안내 상자 데이터(`pending` 은 복구 대상 기록 — 없으면 그래도 같은 글). 글은 오류 표의 `UPDATE_RECOVERY_NEEDED` 행에서 온다."""
    shown = render("UPDATE_RECOVERY_NEEDED")
    return RecoveryPrompt(PROMPT_TITLE, shown.message + "\n\n" + shown.card_action, BUTTON_RECOVER, BUTTON_LATER)


def downgrade_target(pending):
    """복구가 되돌아갈 수 있는 유일한 판(`pending.from`) — 기록이 없으면 빈 글(어떤 낮은 판도 허용하지 않는다)."""
    return pending.from_version if pending is not None else ""


def may_downgrade_to(pending, version):
    """그 버전으로 낮추는 것이 복구에서 허용되는가 — `pending.from` 과 같은 순서의 판 하나만."""
    target = downgrade_target(pending)
    return bool(target) and versions.parse_version(version) is not None and versions.compare(version, target) == 0


def should_restore_data(migrated):
    """업데이트 직전 백업을 복원할 것인가 — 이관이 일어났거나(True) 모를 때(None)만. 이관 전에 멈췄음이 분명하면(False) 복원하지 않는다."""
    return migrated is not False


def run_recovery(pending, *, acquire_lock, data_migrated, restore_backup, obtain_previous, apply_previous, record):
    """복구 순서(위 머리글)를 돌린다 → `RecoveryOutcome`. 부품은 모두 주입한다:
    `acquire_lock()` → 잠금 개체(`release()` 가 있다) · `data_migrated()` → True·False·None · `restore_backup(이름)` · `obtain_previous(버전)` → 설치 파일 묶음 · `apply_previous(묶음, 버전)` · `record(결과, 복원했는가)`.
    잠금을 못 잡으면 그 오류(`UPDATE_IN_PROGRESS`)가 그대로 나가고 아무것도 시작하지 않는다. 그 뒤 어느 단계든 실패하면 `RollbackFailure`(단계 이름 포함)이고 결과 기록은 `rollback_failed` 다."""
    if pending is None:
        raise RollbackFailure(STEP_LOCK, "no_pending")
    lock = acquire_lock()
    steps = [STEP_LOCK]
    restored = False
    step = STEP_DATA
    try:
        if should_restore_data(data_migrated()):
            restore_backup(pending.backup_name)
            restored = True
        steps.append(STEP_DATA)
        step = STEP_INSTALLER
        package = obtain_previous(pending.from_version)
        steps.append(STEP_INSTALLER)
        step = STEP_APPLY
        apply_previous(package, pending.from_version)
        steps.append(STEP_APPLY)
        step = STEP_RECORD
        record(RESULT_ROLLED_BACK, restored)
        steps.append(STEP_RECORD)
    except Exception as error:     # noqa: BLE001 - 어느 단계의 어떤 실패든 거기서 멈추고 손으로 하는 방법을 안내한다(원래 오류의 글은 담지 않고 코드만)
        cause = error.code if isinstance(error, AppError) else type(error).__name__
        try:
            record(RESULT_FAILED, restored)
        except Exception:          # noqa: BLE001 - 기록마저 실패해도 원래 실패가 우선이다
            pass
        raise RollbackFailure(step, cause) from None
    finally:
        release = getattr(lock, "release", None)
        if callable(release):
            release()
    return RecoveryOutcome(restored, tuple(steps))


__all__ = ["BUTTON_LATER", "BUTTON_RECOVER", "PROMPT_TITLE", "RESULT_FAILED", "RESULT_ROLLED_BACK", "RecoveryOutcome", "RecoveryPrompt", "RollbackFailure", "STEPS", "STEP_APPLY", "STEP_DATA",
           "STEP_INSTALLER", "STEP_LOCK", "STEP_RECORD", "downgrade_target", "may_downgrade_to", "needs_recovery", "prompt_for", "run_recovery", "should_restore_data"]
