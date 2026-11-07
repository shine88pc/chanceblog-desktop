"""블로그 프로필 동시 저장 시험의 자식 프로세스(시험이 아니다) — 한 슬롯의 별명을 `a-1`·`a-2`… 처럼 차례로 바꿔 저장한다.

사용: python blog_profiles_race_child.py <임시 폴더> <슬롯> <횟수>
다른 프로세스가 같은 파일을 쓰는 중이면(낡은 판·잠금·윈도 파일 경쟁) 다시 읽고 다시 저장한다 — 마지막 값이 파일에 남아야 한다.
"""
import sys
import time
from pathlib import Path

root, slot, count = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.service.context import Context, Settings, Workspace  # noqa: E402

workspace = Workspace(root / "data")
ctx = Context(workspace, Settings(workspace.settings_path), backend=None)
prefix = "a" if slot == "naver_a" else "b"
retries = 0
for number in range(1, count + 1):
    for attempt in range(400):
        try:
            snap = bp.read_snapshot(ctx)
            bp.save_slot(ctx, slot, {"alias": f"{prefix}-{number}"}, expected_version=snap.version, wait=2.0)
            break
        except AppError as error:
            if error.code not in ("STORE_CONFLICT", "TOPIC_STORE_LOCKED", "FILE_WRITE_FAILED", "TOPIC_FILE_INVALID"):
                raise
            retries += 1
            time.sleep(0.02 + 0.01 * (attempt % 5))
    else:
        sys.exit("저장하지 못했다")
print(f"저장 {count}번, 다시 시도 {retries}번")
