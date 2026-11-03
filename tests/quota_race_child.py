"""사용량 기록을 두 프로세스가 동시에 부르는 시험의 자식 프로세스(시험이 아니다) — `python quota_race_child.py <src 폴더> <데이터 폴더> <횟수>`.
같은 데이터 폴더의 연결 설정(네이버 오픈 API 항목 하나)을 읽어 `acquire` 를 횟수만큼 부르고, 잡은 수와 막힌 수를 `잡음 막힘` 으로 출력한다."""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from chanceblog_desktop.service import quota  # noqa: E402
from chanceblog_desktop.service.context import Context, Settings, Workspace  # noqa: E402

root = Path(sys.argv[2])
workspace = Workspace(root)
context = Context(workspace, Settings(workspace.settings_path), None)
guard = quota.QuotaGuard(context, lock_wait=60)
granted = denied = 0
for _ in range(int(sys.argv[3])):
    got = guard.acquire("naver_openapi")
    if isinstance(got, quota.Lease):
        granted += 1
    else:
        denied += 1
print(granted, denied)
