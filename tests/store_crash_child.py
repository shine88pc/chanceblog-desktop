"""구조 올리기 도중 프로세스를 갑자기 죽이는 시험의 자식 프로세스(시험 파일이 아니다 — tests/test_content_migration.py 가 띄운다).

사용: store_crash_child.py <src 폴더> <데이터 파일> <지점>
`os._exit` 로 곧바로 죽는다(정리 코드·`finally` 가 돌지 않는다 — 전원이 나가는 것과 가장 비슷하다). 지점이 한 번도 지나가지 않으면 죽지 않고 끝나(종료 코드 0) 시험이 실패한다.
"""
import os
import sqlite3
import sys

sys.path.insert(0, sys.argv[1])
from chanceblog_desktop.content import store as store_module  # noqa: E402

path, point = sys.argv[2], sys.argv[3]
DIED = 9


def die():
    os._exit(DIED)


def starts(prefix):
    return lambda sql: " ".join(sql.split()).upper().startswith(prefix)


class Main:
    """진짜 연결을 감싸 정해 둔 문장 앞이나 뒤에서 죽는다."""

    def __init__(self, real, before=None, after=None):
        self._real, self._before, self._after = real, before, after

    def execute(self, sql, *args):
        if self._before and self._before(sql):
            die()
        result = self._real.execute(sql, *args)
        if self._after and self._after(sql):
            die()
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)


class HalfCopy:
    """사본의 원본 쪽 연결 — 한 쪽(page)만 옮기고 죽는다."""

    def __init__(self, real):
        self._real = real

    def backup(self, target, **kwargs):
        return self._real.backup(target, pages=1, progress=lambda status, remaining, total: die(), sleep=0)

    def __getattr__(self, name):
        return getattr(self._real, name)


MAIN_POINTS = {
    "before_begin": dict(before=starts("BEGIN")),
    "after_begin": dict(after=starts("BEGIN IMMEDIATE")),
    "after_first_statement": dict(after=starts("CREATE TABLE IF NOT EXISTS CANDIDATES")),
    "after_all_statements": dict(after=starts("CREATE INDEX IF NOT EXISTS CANDIDATES_KEYWORD")),
    "before_user_version": dict(before=starts("PRAGMA USER_VERSION =")),
    "after_user_version": dict(after=starts("PRAGMA USER_VERSION =")),
    "before_commit": dict(before=starts("COMMIT")),
    "after_commit": dict(after=starts("COMMIT")),
}
real_connect = sqlite3.connect
seen = {"main": False, "source": False}


def connect(*args, **kwargs):
    real = real_connect(*args, **kwargs)
    if kwargs.get("isolation_level", 0) is None and not kwargs.get("uri") and not seen["main"]:
        seen["main"] = True
        return Main(real, **MAIN_POINTS[point]) if point in MAIN_POINTS else real
    if kwargs.get("uri") and point == "mid_copy" and not seen["source"]:
        seen["source"] = True
        return HalfCopy(real)
    return real


if point == "after_copy":
    real_rename = os.rename

    def rename_then_die(source, destination):
        real_rename(source, destination)
        die()

    store_module.os.rename = rename_then_die
store_module.sqlite3.connect = connect
try:
    store_module.Store.open(path).close()
    print("SURVIVED", point)
except BaseException as error:               # noqa: BLE001 — 죽지 않고 실패했다면 그 사실을 알린다
    print("EXC", type(error).__name__, error)
    sys.exit(1)
