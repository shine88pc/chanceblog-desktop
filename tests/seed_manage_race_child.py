"""Seed 관리 쓰기 동시 저장 시험의 자식 프로세스(시험이 아니다) — 씨앗 하나의 상태를 사용 중 ↔ 쉬는 중으로 차례로 바꿔 저장한다.

사용: python seed_manage_race_child.py <임시 폴더> <a|b> <횟수>
다른 프로세스가 같은 파일을 쓰는 중이면(낡은 판·잠금·윈도 파일 경쟁) 다시 읽고 다시 저장한다 — 마지막 상태가 파일에 남아야 한다.
"""
import sys
import time
from pathlib import Path

root, which, count = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import seed_manage as sm  # noqa: E402
from chanceblog_desktop.service.context import Context, Settings, Workspace  # noqa: E402

workspace = Workspace(root / "data")
ctx = Context(workspace, Settings(workspace.settings_path), backend=None)
seed_id = "ex-" + which
retries = 0
for number in range(1, count + 1):
    target = "active" if number % 2 else "inactive"
    for attempt in range(400):
        try:
            snap = sm.read_snapshot(ctx)
            if next(item for item in snap.seeds if item.seed_id == seed_id).state == target:
                break
            sm.set_state(ctx, seed_id, target, expected_version=snap.version, wait=2.0)
            break
        except AppError as error:
            if error.code not in ("STORE_CONFLICT", "TOPIC_STORE_LOCKED", "FILE_WRITE_FAILED", "TOPIC_FILE_INVALID"):
                raise
            retries += 1
            time.sleep(0.02 + 0.01 * (attempt % 5))
    else:
        sys.exit("저장하지 못했다")
print(f"저장 {count}번, 다시 시도 {retries}번")
