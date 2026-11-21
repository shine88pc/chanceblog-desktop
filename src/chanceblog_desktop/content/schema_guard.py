"""백업에서 되돌릴 보관함 파일(SQLite)의 '구조' 검사 — 앱이 만들지 않는 것(트리거·뷰·모르는 표와 색인·가상 표·숨은 열)이 되돌리기로 몰래 들어오지 못하게 한다(L8, 결정 D-554).

왜 필요한가: 복원은 보관함 파일을 SQLite 백업 방식으로 통째 복사한다. 지금까지의 확인(이름표·판·점검·`_shape_problem`)은 정해 둔 표의 열 이름만 봐서, 조작한 백업에 든 **트리거**(저장할 때마다 몰래 도는 문장)나
**뷰**(`pragma_table_info` 는 뷰의 열도 돌려줘서 표 행세를 해도 모양 확인을 통과한다)와 **모르는 표·색인**(유일 색인 하나면 이후 저장이 모두 막힌다)이 그대로 들어왔다. 목록의 해시는 같은 폴더 안의 값이라 조작한 사람이 다시 계산하면 맞는다.

기준: 보관함 클래스가 새 파일을 만들 때 실행하는 문장(`SCHEMA`)을 메모리 연결에서 한 번 실행해 얻은 개체 목록('정본')이다 — 손으로 적은 목록이 아니라서 판이 늘어도 같이 맞는다. 되돌릴 파일의 개체는 이 정본의 부분집합이어야 한다
(옛 판의 백업은 표 몇 개가 없을 뿐이라 부분집합이다). 지금 열려 있는 보관함은 이 검사를 받지 않는다 — 되돌리려는 **들어오는 파일**만 검사한다.

이 모듈은 읽기만 한다(파일·네트워크·시계 없음). 결과는 고정된 종류 이름(`KIND_TEXT`)뿐이고 개체 이름·SQL 글은 어디에도 싣지 않는다(조작한 파일의 글이 문구·로그에 되풀이되지 않게).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from functools import lru_cache

MAX_OBJECTS = 128                      # 앱이 만드는 개체는 서른 개 안쪽이다(내용 보관함 열한 개·주제 엔진 스물두 개) — 이보다 많으면 더 훑지 않고 거절한다
INTERNAL_TABLES = frozenset({"sqlite_sequence", "sqlite_stat1", "sqlite_stat2", "sqlite_stat3", "sqlite_stat4"})        # SQLite 가 스스로 만드는 표(내용은 계획 통계뿐) — 앱은 만들지 않지만 정상 파일에 있어도 된다
AUTO_INDEX = "sqlite_autoindex_"       # 기본 키·유일 제약이 SQLite 가 만드는 색인 이름의 머리(SQL 글이 없다)
KIND_TEXT = {
    "trigger": "트리거", "view": "뷰", "virtual": "가상 표", "table": "모르는 표", "index": "모르는 색인", "index_shape": "정해 둔 색인과 다른 모양", "hidden_column": "숨은 열", "other": "모르는 종류의 개체",
    "too_many": "너무 많은 개체",
}
KIND_ORDER = tuple(KIND_TEXT)          # 알릴 때의 순서(위험한 것부터)


def _signature(db, owner, name):
    """색인 하나의 모양 — (열 이름들, 유일 색인인가, 일부 행만 거는 색인인가)."""
    columns = tuple(row[0] for row in db.execute("SELECT name FROM pragma_index_info(?) ORDER BY seqno", (name,)))
    flags = db.execute('SELECT "unique", partial FROM pragma_index_list(?) WHERE name = ?', (owner, name)).fetchone() or (None, None)
    return columns, flags[0], flags[1]


@lru_cache(maxsize=16)
def _reference(statements):
    """정본 — `statements`(새 파일을 만드는 문장들)를 메모리 연결에서 실행해 얻은 (표 이름들, 기본 색인 이름들, {이름 있는 색인: (표, 모양)})."""
    with closing(sqlite3.connect(":memory:")) as db:
        for statement in statements:
            db.execute(statement)
        tables = frozenset(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))
        automatic = frozenset(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NULL"))
        named = {name: (owner, _signature(db, owner, name)) for name, owner in db.execute("SELECT name, tbl_name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL")}
    return tables, automatic, named


def foreign_kinds(connection, statements):
    """열린 연결(읽기 전용으로 연 되돌릴 파일)의 개체 중 정본에 없는 것의 종류 → `KIND_ORDER` 순서의 고정 이름 튜플(없으면 빈 튜플). `statements` 는 그 보관함이 새 파일을 만들 때 실행하는 문장들이다.
    읽다가 나는 `sqlite3.Error`(깨진 파일)는 그대로 올린다 — 부르는 쪽이 자기 오류 코드로 바꾼다."""
    tables, automatic, named = _reference(tuple(statements))
    rows = connection.execute("SELECT type, name, tbl_name, substr(sql, 1, 40) FROM sqlite_master LIMIT ?", (MAX_OBJECTS + 1,)).fetchall()
    if len(rows) > MAX_OBJECTS:
        return ("too_many",)
    found, present = set(), []
    for kind, name, owner, head in rows:
        if kind == "table":
            known = name in tables
            if not known and name in INTERNAL_TABLES:
                continue
            if (head or "").lstrip()[:12].upper() != "CREATE TABLE":
                found.add("virtual" if (head or "").lstrip()[:14].upper() == "CREATE VIRTUAL" else "table")        # 가상 표(전문 검색 같은 것) — 같은 이름으로 정본의 표 행세를 해도 거절한다
            elif not known:
                found.add("table")
            else:
                present.append(name)
        elif kind == "index":
            if head is None:                                                                  # SQL 글이 없는 색인 = 기본 키·유일 제약이 만든 것 — 정본에 있는 이름뿐이다(제약을 더하면 이름이 하나 더 생긴다)
                if name not in automatic or owner not in tables:
                    found.add("index")
            elif name not in named or named[name][0] != owner:
                found.add("index")
            elif _signature(connection, owner, name) != named[name][1]:
                found.add("index_shape")
        elif kind in ("trigger", "view"):
            found.add(kind)
        else:
            found.add("other")
    for name in present:                                                                      # 정본의 표에 생성 열(`AS (…)`)·숨은 열이 더해졌나 — `table_info` 는 그 열을 보여 주지 않는다
        if connection.execute("SELECT 1 FROM pragma_table_xinfo(?) WHERE hidden != 0 LIMIT 1", (name,)).fetchone():
            found.add("hidden_column")
    return tuple(kind for kind in KIND_ORDER if kind in found)


def describe(kinds):
    """`foreign_kinds` 의 결과 → 쉬운 한 줄('트리거·뷰'). 개체 이름은 싣지 않는다."""
    return "·".join(KIND_TEXT[kind] for kind in kinds)


__all__ = ["KIND_ORDER", "KIND_TEXT", "MAX_OBJECTS", "describe", "foreign_kinds"]
