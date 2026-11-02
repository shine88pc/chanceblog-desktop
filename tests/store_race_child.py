"""`Store.open` 을 여러 프로세스가 동시에 부르는 시험의 자식 프로세스(시험 파일이 아니다 — tests/test_content_migration.py 가 띄운다).

사용: store_race_child.py <src 폴더> <데이터 파일> <신호 파일>
준비가 끝나면 `READY` 를 한 줄 내보내고, 신호 파일이 생길 때까지 기다렸다가 곧바로 `Store.open` 을 부른다(여러 자식이 거의 같은 순간에 연다). 결과는 JSON 한 줄.
"""
import json
import os
import sys
import time

sys.path.insert(0, sys.argv[1])
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

path, go = sys.argv[2], sys.argv[3]
print("READY", flush=True)
while not os.path.exists(go):
    time.sleep(0.0005)
started = time.time()
try:
    with Store.open(path, busy_seconds=30) as store:
        result = {"ok": True, "version": store.schema_version, "check": store.check()}
except AppError as error:
    result = {"ok": False, "code": error.code, "detail": error.detail}
except BaseException as error:                 # noqa: BLE001 — AppError 가 아닌 실패도 숨기지 않고 그대로 보고한다
    result = {"ok": False, "code": "NOT_AN_APP_ERROR:" + type(error).__name__, "detail": str(error)[:300]}
result["seconds"] = round(time.time() - started, 3)
print(json.dumps(result, ensure_ascii=False), flush=True)
