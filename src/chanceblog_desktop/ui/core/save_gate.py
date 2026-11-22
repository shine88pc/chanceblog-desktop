"""복원 중 저장 겹침 막기(F030, 결정 D-534) — 순수 파이썬(화면 도구를 모른다).

백업 복원은 글 보관함·주제 보관함·채널 프로필·Seed 파일을 통째로 바꾼다. 그 사이에 다른 화면의 저장·복제·삭제·승인·등록·후보 만들기가 같은 파일에 쓰면 서로 덮어쓴다 — 복원이 잡는 잠금(`locks/full-backup.lock`)은
블로그(`blog-profiles.lock`)·Seed(`seeds.lock`) 쓰기가 잡는 잠금과 달라서 서비스가 막아 주지 않고, 작업 이름(`JobRunner` 의 열쇠)도 화면마다 따로라 서로를 모른다. 그래서 화면 규칙이 막는다.
  · 복원(또는 안전 사본으로 되돌리기)이 도는 동안 저장 길은 시작하지 않고 `("restoring", None)` 을 돌려준다 — 작업도 만들지 않고 입력도 건드리지 않는다. 셸이 한 줄로 알리고 복원이 끝나면 다시 누르게 한다.
  · 거꾸로 저장 길이 도는 동안 복원은 시작하지 않는다(`BackupController.restore_gate` — `("writing", None)`, `AppState.writers_busy`).
지금 백업(만들기)은 읽기만 해서 어느 쪽도 막지 않는다. 서비스의 쓰기 형식·백업 형식·설정 칸은 이 규칙이 건드리지 않는다.
막는 곳은 아래 데코레이터 하나이고 `AppState` 가 각 컨트롤러의 `save_gate`(복원 중이면 참을 돌려주는 함수)를 이어 준다. 이어 주지 않은 컨트롤러(`save_gate` 가 None)는 막지 않는다.
"""
from __future__ import annotations

import functools

RESTORING = "restoring"                                       # 복원이 도는 동안 저장을 시작하지 못할 때 시작 함수가 돌려주는 상태


def blocked_while_restoring(start):
    """저장·복제·삭제처럼 파일에 쓰는 일을 시작하는 컨트롤러 메서드에 붙인다 — 그 컨트롤러의 `save_gate()` 가 참이면(복원이 도는 중) 메서드를 부르지 않고 `("restoring", None)` 을 돌려준다."""

    @functools.wraps(start)
    def guarded(self, *args, **kwargs):
        gate = self.save_gate
        if gate is not None and gate():
            return RESTORING, None
        return start(self, *args, **kwargs)

    return guarded
