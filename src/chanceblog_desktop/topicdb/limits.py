"""받은(믿을 수 없는) SQLite 파일을 읽는 연결에 거는 한도 — AS-S2 권고-5(결정 D-691).

왜: 되돌릴 백업 폴더는 다른 PC 에서 온 것일 수 있어 보관함 파일(SQLite)이 조작됐을 수 있다. 앱은 SQLite 한도를 어디에도 걸지 않아서(감사 때 0건) 뷰 하나(끝없는 재귀 질의)나 아주 큰 값만으로 점검 질의가
CPU·메모리를 끝없이 쓰게 만들 수 있었다(20만 행짜리 뷰는 거절되기 전에 2.4초). 첫 방어선은 순서다 — 구조 검사(뷰·트리거·모르는 표 거절)를 내용 질의보다 먼저 한다(`topicdb/backup.py::read_backup`).
이 모듈은 두 번째 방어선이다: 구조가 정상인 척하는 파일이 어떤 질의를 돌리더라도 연결이 스스로 한도를 넘지 못한다.

걸리는 한도(받은 파일을 여는 읽기 연결에만 건다 — 앱이 쓰는 보관함 연결과 지금 데이터를 점검하는 연결에는 걸지 않으므로 정상 데이터는 영향이 없다):
  1) 시간 상한: `set_progress_handler` 가 가상 기계 명령 `CHECK_EVERY` 개마다 시계를 보고 `SECONDS` 가 지났으면 질의를 끊는다(`sqlite3.OperationalError: interrupted`). 끊었으면 `Guard.tripped` 가 참이다 — 부르는 쪽이 이 표시로
     '깨진 파일' 이 아니라 '점검이 시간 안에 끝나지 않음' 이라고 쉬운 말로 알린다. 시계는 첫 연결을 붙일 때 시작하고 한 번의 읽기에 쓰는 모든 연결이 나눠 쓴다.
  2) 길이 한도(`LIMITS`): 한 값의 길이·SQL 글 길이·열 수·식 깊이·합친 질의 수·붙이는 파일 수·트리거 깊이 — `Connection.setlimit` 로 건다. 이 메서드는 파이썬 3.11 부터 있어 3.10 에서는 건너뛴다(그때는 시간 상한과 파일 크기 상한이 지킨다).
  3) 파일 크기 상한(`MAX_DB_BYTES`·`MAX_MANIFEST_BYTES`): 파일을 통째로 메모리에 읽기 **전에** 크기만 본다(`topicdb/backup.py`) — 앱이 만드는 보관함은 이보다 훨씬 작다.
값은 앱이 만드는 정상 보관함(표 열한 개·열 열네 개 안쪽·한 칸 수십 KB 안쪽·점검 질의 수 ms)보다 몇 배 넉넉하게 잡았다 — 정상 백업이 이 한도에 걸리는 일은 없어야 하고, 걸리는 것은 조작했거나 이 프로그램의 것이 아닌 파일뿐이다.
이 모듈은 외부 접속도 파일 쓰기도 하지 않는다(연결 객체에 한도만 건다).
"""
from __future__ import annotations

import sqlite3
import time

SECONDS = 60.0                                           # 한 번의 읽기(백업 폴더 하나의 보관함 점검)에 줄 수 있는 시간 — 정상 보관함의 점검은 수 ms에서 수 초, 부하가 큰 PC 의 여유를 두었다
CHECK_EVERY = 1_000                                      # 가상 기계 명령 이만큼마다 시계를 본다(질의가 끝나지 않아도 끊을 수 있는 가장 잘게 — 너무 잘게 하면 정상 질의가 느려진다)
MAX_DB_BYTES = 512 * 1024 * 1024                         # 받은 보관함 파일 하나의 크기 상한 — 읽기 전에 stat 으로 본다(앱이 만드는 보관함은 수 MB 안쪽)
MAX_MANIFEST_BYTES = 1024 * 1024                         # 받은 백업 목록 파일(MANIFEST.json)의 크기 상한 — 정상 목록은 1KB 안쪽이다
LIMITS = (                                               # (sqlite3 상수 이름, 값) — 상수가 없는 파이썬(3.10)에서는 건너뛴다
    ("SQLITE_LIMIT_LENGTH", 16 * 1024 * 1024),           # 한 값(글·BLOB)·한 줄의 길이 — 앱이 쓰는 칸은 수십 KB 안쪽(JSON 설정 파일 한도가 8MB)
    ("SQLITE_LIMIT_SQL_LENGTH", 1_000_000),              # SQL 문장 하나의 길이 — 점검 질의는 수백 자
    ("SQLITE_LIMIT_COLUMN", 64),                         # 표·결과의 열 수 — 앱의 표는 열네 개 안쪽
    ("SQLITE_LIMIT_EXPR_DEPTH", 256),                    # 식의 깊이(재귀하는 식) — 훑기 질의(`iterdump`)가 열 하나에 두 겹씩 쌓아도 64열이면 130
    ("SQLITE_LIMIT_COMPOUND_SELECT", 16),                # 합친 질의(UNION 등)의 조각 수 — 점검 질의는 둘
    ("SQLITE_LIMIT_ATTACHED", 0),                        # 다른 파일 붙이기(ATTACH)는 쓰지 않는다
    ("SQLITE_LIMIT_TRIGGER_DEPTH", 0),                   # 트리거는 아예 돌지 않는다(읽기 연결이라 쓰는 일이 없다 — 트리거 자체는 구조 검사가 거절한다)
)
TIME_REASON = "백업 안의 보관함을 정해 둔 시간 안에 점검하지 못해 쓰지 않습니다(너무 크거나 복잡한 파일입니다)"
BIG_REASON = "백업 안의 파일이 너무 커서 쓰지 않습니다(이 프로그램이 만드는 백업보다 훨씬 큽니다)"


class Guard:
    """한 번의 읽기가 쓰는 모든 SQLite 연결이 나눠 가지는 한도 — `attach(연결)` 로 붙인다. `tripped` 는 시간이 다 돼서 질의를 끊은 적이 있는가."""

    def __init__(self, seconds=None, *, clock=time.monotonic):
        self.seconds = SECONDS if seconds is None else float(seconds)
        self._clock = clock
        self._deadline = None
        self.tripped = False
        self.limits_applied = ()                         # 이번에 실제로 건 길이 한도 이름들(3.10 은 빈 튜플)

    def attach(self, connection):
        """연결에 시간 상한과 길이 한도를 건다 → 같은 연결. 쿼리를 하나라도 돌리기 **전에** 부른다."""
        if self._deadline is None:
            self._deadline = self._clock() + self.seconds                 # 첫 연결에서 시계가 시작한다
        connection.set_progress_handler(self._tick, CHECK_EVERY)
        applied = []
        if hasattr(connection, "setlimit"):                               # 파이썬 3.11 부터
            for name, value in LIMITS:
                category = getattr(sqlite3, name, None)
                if category is None:
                    continue
                connection.setlimit(category, value)
                applied.append(name)
        self.limits_applied = tuple(applied)
        return connection

    def _tick(self):
        """진행 처리 콜백 — 0 이면 계속, 0 이 아니면 지금 도는 질의를 끊는다."""
        if self._clock() > self._deadline:
            self.tripped = True
            return 1
        return 0


__all__ = ["BIG_REASON", "CHECK_EVERY", "Guard", "LIMITS", "MAX_DB_BYTES", "MAX_MANIFEST_BYTES", "SECONDS", "TIME_REASON"]
