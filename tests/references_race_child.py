"""참고 글 보관함의 '두 프로세스가 같은 글을 동시에 고친다' 시험의 자식 프로세스(시험 파일이 아니다 — tests/test_service_references.py 의 TempFileTest 가 띄운다). 독립 검증 S-R1 의 실험을 시험으로 만든 것이다.

사용: references_race_child.py <src 폴더> <데이터 폴더> <글 번호> <표식 글자> <횟수> <신호 파일>
준비가 끝나면 `READY` 를 한 줄 내보내고, 신호 파일이 생길 때까지 기다렸다가 곧바로 `update_reference` 를 `횟수` 번 부른다(본문은 `<표식>-<번호>`). 끝나면 성공·AppError 코드별 횟수·그 밖의 실패를 JSON 한 줄로 알린다.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import references as ref  # noqa: E402
from chanceblog_desktop.service.context import Context, Settings, Workspace, utc_now  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
from chanceblog_desktop.service import external  # noqa: E402

root, ref_id, label, count, go = Path(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6]
workspace = Workspace(root)
ctx = Context(workspace, Settings(workspace.settings_path), backend=None, git=external.refusing_git, expected_origin=gitrepo.EXPECTED_ORIGIN, clock=utc_now)
print("READY", flush=True)
while not os.path.exists(go):
    time.sleep(0.0005)
report = {"ok": 0, "codes": {}, "other": []}
for number in range(count):
    try:
        ref.update_reference(ctx, ref_id, title="경쟁 글", body=f"{label}-{number}")
        report["ok"] += 1
    except AppError as error:
        report["codes"][error.code] = report["codes"].get(error.code, 0) + 1
    except BaseException as error:                 # noqa: BLE001 — AppError 가 아닌 실패도 숨기지 않고 그대로 보고한다
        report["other"].append(type(error).__name__ + ":" + str(error)[:120])
print(json.dumps(report, ensure_ascii=False), flush=True)
