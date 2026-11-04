"""콘텐츠 저장소(SQLite) — 원고 프로젝트를 한 파일에 안전하게 저장·불러오기·판 기록·자동 저장 초안·주제 후보·백업·복구(docs/ARCHITECTURE.md §5 `content/`).

지키는 것(데이터를 잃지 않는 것이 첫째):
  ① 쓰는 일은 모두 하나의 트랜잭션이다 — 중간에 실패하거나 전원이 나가도 '저장 전' 아니면 '저장 후'다.
  ② 열 때 이 프로그램의 데이터 파일인지(`application_id`)·더 새로운 버전이 만든 것은 아닌지(`user_version`)·깨지지 않았는지(`quick_check`)
     확인하고, 아니면 **파일에 아무것도 쓰지 않고** 오류 코드로 멈춘다(깨진 파일을 덮어쓰지 않는다).
  ③ 저장된 판(revision)보다 낮은 판으로는 덮어쓰지 않는다(`STORE_CONFLICT`) — 오래된 화면이 새 원고를 지우지 못하게.
  ④ 구조를 바꿀 때(마이그레이션)는 쓰기 잠금을 잡은 **뒤** 사본(`.v<번호>.bak`)을 두고 한 트랜잭션으로 바꾸며, 실패하면 되돌려 원래 파일 그대로다(`MIGRATION_FAILED`·`MIGRATION_BLOCKED`).
     여러 창이 동시에 열어도 한 곳만 올리고 나머지는 이미 올랐음을 알아보며(잠금을 쥔 채 판 번호를 다시 읽는다), 이미 있는 사본은 덮어쓰지 않는다.
  ⑤ 읽을 때는 `ContentProject.from_dict` 의 엄격한 검사를 다시 거친다 — 파일을 사람이 고쳤거나 깨졌으면 `STORE_CORRUPT`.
  ⑥ 모든 SQL 은 값을 매개변수로 넘긴다(글이 SQL 로 해석될 수 없다). 프로젝트 번호는 `[A-Za-z0-9_-]{1,64}` 만 받는다.
  ⑦ 화면과 작업 줄(스레드)이 같은 저장소를 함께 써도 한 번에 하나씩만 실행한다(자동 저장·백업이 겹쳐도 안전).
  ⑧ 주제 후보(`candidates` 표, 판 2 에서 더했다)도 같은 규칙이다 — 후보의 상태 이동은 읽고 바꾸고 쓰는 것이 한 트랜잭션이고, 저장은 내가 불러온 판에서 바뀐 것만 받으며(아니면 `STORE_CONFLICT`),
     상태는 저장될 때도 이동 표대로만 바뀌고(`CANDIDATE_TRANSITION_INVALID`), 지우려면 확인이 있어야 한다. 연결한 글을 지우면 후보는 남고 연결만 끊긴다. 깨진 후보 한 행은 그 후보만 막는다(`CANDIDATE_CORRUPT`).
  ⑨ 읽기만 하는 도구는 `Store.open(경로, migrate=False)` 로 연다 — 파일을 만들지도 구조를 올리지도 않고 한 바이트도 바꾸지 않으며 쓰는 일은 모두 거절한다(보관함 파일을 바꾸지 않고 다른 폴더에 사본만 만드는 `backup(폴더)` 는 예외로 허용한다).

SQLite 의 실패는 오류 코드로 옮긴다: 잠김 → STORE_LOCKED, 디스크 가득 → DISK_FULL, 못 열거나 못 씀 → FILE_WRITE_FAILED, 깨짐 → STORE_CORRUPT.
비밀번호·토큰은 이 파일에 두지 않는다(원고와 발행 상태뿐이다).
"""
from __future__ import annotations

import errno
import itertools
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

from ..echo import shown_ref
from ..errors import AppError
from .candidates import STAMP_FORMAT, STATUS_KO, TRANSITIONS, Candidate, keyword_key, parse_stamp, short_id
from .candidates import STATUSES as CANDIDATE_STATUSES
from .candidates import _invalid as candidate_invalid
from .model import Asset, ContentProject, utc_now
from .profiles import MAX_REUSE_DAYS
from .status import PLATFORMS

APPLICATION_ID = 0x43424450          # 'CBDP' — 이 프로그램의 데이터 파일 표시
SCHEMA_VERSION = 2
MIN_SCHEMA_VERSION = 1               # 이 프로그램이 만든 파일의 가장 낮은 판 — 0·음수는 이 프로그램이 만든 적이 없다(이름표만 맞춘 낯선 파일)
KEEP_REVISIONS = 50                  # 프로젝트마다 남기는 판 기록 수(가장 새 판은 늘 남긴다)
KEEP_BACKUPS = 10
MAX_DRAFT_CHARS = 2_000_000
BUSY_SECONDS = 5.0
_SQLITE_BUSY, _SQLITE_LOCKED = 5, 6        # backup 진행 콜백이 받는 상태(파이썬 3.10 에는 sqlite3.SQLITE_BUSY 이름이 없어 숫자로 둔다)
COPY_SECONDS = 30.0                  # 올리기 전 사본을 만드는 데 줄 수 있는 시간 — 파일이 계속 잠겨 있으면 이 시간 뒤 멈추고 알린다(끝없이 기다리지 않는다)
MAX_COPY_NAMES = 20                  # 사본 이름(.v1.bak → .v1.2.bak …)을 이만큼까지 찾아본다
_COPY_PATH_LIMIT = 259 if os.name == "nt" else None      # Windows 의 경로 길이 한계(MAX_PATH 260 에서 끝 글자 하나) — 사본 이름이 이를 넘기 전에 알린다
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BACKUP_NAME = re.compile(r"^(?P<stem>.+)-(?P<stamp>\d{8}-\d{6})\.db$")
_CANDIDATE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

# 판 2 에서 더한 주제 후보 표의 DDL — 이미 나간 판의 올리기 단계(1 → 2)가 쓰는 문장이라 **고치지 않는다**(시험이 해시로 지킨다). 앞으로 이 표를 바꿀 일이 생기면
# 이 문장은 그대로 두고 판 3 의 단계를 따로 만든다(그렇지 않으면 판 1 파일의 1 → 2 가 새 모양으로 표를 만들어 2 → 3 과 부딪친다).
# project_id 는 연결한 글 — 그 글을 지우면 연결만 끊긴다(후보는 남는다). 연결은 이 열이 기준이라 자료(data)에는 적지 않는다. `IF NOT EXISTS` 는 이 단계를 다시 돌려도 안전하게 한다.
_V2_CANDIDATES = (
    "CREATE TABLE IF NOT EXISTS candidates ("
    " candidate_id TEXT PRIMARY KEY, keyword_key TEXT NOT NULL, status TEXT NOT NULL, project_id TEXT REFERENCES projects (project_id) ON DELETE SET NULL,"
    " revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS candidates_status ON candidates (status, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS candidates_keyword ON candidates (keyword_key, status)",
)

# 새 파일은 가장 새 모양으로 만든다(판 3 이 생기면 이 목록을 그 모양으로 고치고, 시험이 '새 파일 = 옛 파일을 올린 것' 을 확인한다)
_SCHEMA = (
    "CREATE TABLE projects ("
    " project_id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL)",
    "CREATE INDEX projects_updated ON projects (updated_at DESC)",
    "CREATE TABLE revisions ("
    " project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE, revision INTEGER NOT NULL, saved_at TEXT NOT NULL, data TEXT NOT NULL,"
    " PRIMARY KEY (project_id, revision))",
    "CREATE TABLE drafts (project_id TEXT PRIMARY KEY, text TEXT NOT NULL, saved_at TEXT NOT NULL)",
    *_V2_CANDIDATES,
)

# 판마다 있어야 하는 표와 열(차례대로). 이름표(application_id·user_version)만 맞고 표가 없거나 열이 다른 깨진 파일은 올리기 전에 거절하려고 본다. 앞 판의 표는 뒤 판에도 그대로 있다.
_SHAPES = {1: {"projects": ("project_id", "title", "revision", "created_at", "updated_at", "data"),
               "revisions": ("project_id", "revision", "saved_at", "data"),
               "drafts": ("project_id", "text", "saved_at")}}
_SHAPES[2] = {**_SHAPES[1], "candidates": ("candidate_id", "keyword_key", "status", "project_id", "revision", "created_at", "updated_at", "data")}
_V2_INDEXES = {"candidates_status": ("status", "updated_at"), "candidates_keyword": ("keyword_key", "status")}


def _shape_problem(connection, version, *, indexes=False):
    """그 판의 파일이어야 하는 표·열(`indexes=True` 면 판 2 의 색인도)이 맞는지 — 어긋난 첫 곳을 설명하는 글, 맞으면 None. 모르는 판은 보지 않는다."""
    expected = _SHAPES.get(version)
    if expected is None:
        return None
    for table, columns in expected.items():
        found = tuple(row[0] for row in connection.execute("SELECT name FROM pragma_table_info(?) ORDER BY cid", (table,)))
        if found != columns:
            return f"표 {table} 이 없다" if not found else f"표 {table} 의 열이 다르다: {', '.join(found)}"
    if indexes and version >= 2:
        for index, columns in _V2_INDEXES.items():
            owner = connection.execute("SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?", (index,)).fetchone()
            found = tuple(row[0] for row in connection.execute("SELECT name FROM pragma_index_info(?) ORDER BY seqno", (index,)))
            if owner is None or owner[0] != "candidates" or found != columns:
                return f"색인 {index} 이 없거나 다르다"
    return None


def _add_candidates(db):
    """판 1 → 2: 주제 후보 표를 더한다(있던 표와 자료는 건드리지 않는다). 다시 돌려도 안전하고(`IF NOT EXISTS`), 끝나면 만든 것이 정해 둔 모양인지 확인한다 —
    같은 이름의 다른 모양 표·색인이 이미 있었다면 조용히 넘기지 않고 실패해 트랜잭션이 되돌려진다."""
    table, *indexes = _V2_CANDIDATES
    db.execute(table)
    problem = _shape_problem(db, 2)                          # 같은 이름의 다른 표가 이미 있으면 색인을 만들다 엉뚱한 오류가 나기 전에 여기서 알려 준다
    if problem:
        raise RuntimeError(problem)
    for statement in indexes:
        db.execute(statement)
    problem = _shape_problem(db, 2, indexes=True)
    if problem:
        raise RuntimeError(problem)


# 구조를 바꾸는 단계: {지금 버전: 다음 버전으로 바꾸는 함수(연결)}. 한 번에 한 단계씩, 모두 한 트랜잭션 안에서 돈다.
MIGRATIONS = {1: _add_candidates}

# SQLite 의 오류 문구 → 오류 코드(위에서부터 처음 맞는 것)
_ERROR_RULES = (
    (("database is locked", "database table is locked", "database schema is locked"), "STORE_LOCKED"),
    (("disk is full", "database or disk is full"), "DISK_FULL"),
    (("malformed", "not a database", "file is encrypted", "corrupt", "no such table", "no such column"), "STORE_CORRUPT"),
    (("unable to open", "readonly", "read-only", "disk i/o error", "cannot open", "permission denied", "access is denied", "no such file or directory"), "FILE_WRITE_FAILED"),
)


@dataclass(frozen=True)
class Summary:
    project_id: str
    title: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Snapshot:
    """저장된 옛 판의 원고(제목·본문·출처·이미지)."""
    revision: int
    saved_at: str
    title: str
    source_content: str
    references: tuple
    assets: tuple


@dataclass(frozen=True)
class Draft:
    project_id: str
    text: str
    saved_at: str


def _detail(error):
    return " ".join(str(error).split())[:200]


def store_error(error, path=""):
    """sqlite3 의 예외 → AppError. 이미 AppError 면 그대로."""
    if isinstance(error, AppError):
        return error
    text = str(error).lower()
    for needles, code in _ERROR_RULES:
        if any(needle in text for needle in needles):
            slots = {"경로": str(path), "파일": Path(str(path)).name} if code in ("FILE_WRITE_FAILED", "STORE_CORRUPT") else None
            return AppError(code, slots, detail=_detail(error))
    return AppError("UNEXPECTED_ERROR", detail=f"{type(error).__name__}: {_detail(error)}")


def _blocked_reason(code, text):
    """SQLite 의 디스크 가득·쓰기 실패를 '올리기를 시작하지 못한 이유' 한 구절로(사용자 문구에 들어간다)."""
    lowered = text.lower()
    if code == "DISK_FULL":
        return "저장 공간이 부족합니다"
    if "readonly" in lowered or "read-only" in lowered:
        return "데이터 파일이 읽기 전용입니다"
    if "i/o" in lowered:
        return "디스크 읽기·쓰기 오류가 났습니다(디스크나 외장 저장장치 연결을 확인하세요)"
    return "데이터 파일이나 그 폴더에 쓸 수 없습니다(쓸 권한이 없거나 경로가 너무 깁니다)"


def _os_blocked_reason(error):
    """운영체제 오류(사본 파일 이름 바꾸기 등) → 올리기를 시작하지 못한 이유. 환경 문제가 아니면 None."""
    winerror = getattr(error, "winerror", None)
    if error.errno == errno.ENOSPC or winerror == 112:
        return "저장 공간이 부족합니다"
    if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS) or isinstance(error, PermissionError):
        return "데이터 파일이 있는 폴더에 쓸 수 없습니다(읽기 전용이거나 권한이 없습니다)"
    if error.errno == errno.ENAMETOOLONG or winerror == 206:
        return "데이터 파일의 경로가 너무 길어 사본을 만들 수 없습니다"
    return None


def _check_id(project_id):
    if not isinstance(project_id, str) or not _ID.match(project_id):
        raise AppError("CONTENT_INVALID", {"항목": "프로젝트 번호"})
    return project_id


def _check_candidate_id(candidate_id):
    if not isinstance(candidate_id, str) or not _CANDIDATE_ID.fullmatch(candidate_id):
        raise candidate_invalid("후보 번호", "영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 합니다")
    return candidate_id


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


_UNC_OR_EXTENDED = re.compile(r"^\\\\")                                                       # 역슬래시 둘로 시작하는 경로 = 네트워크(UNC) 경로나 확장 경로. 드라이브 경로는 `Path.as_uri()` 가 이미 맞게 만든다


def _read_only_uri(path):
    """그 파일을 **읽기 전용**(`mode=ro`)으로 여는 SQLite 주소.

    `Path.as_uri()` 는 네트워크 경로(UNC — 매핑한 네트워크 드라이브를 `resolve()` 하면 `\\\\서버\\공유\\…` 가 된다)에 `file://서버/공유/…` 를 내는데, SQLite 는 주소의 authority(`file://` 바로 뒤)가
    비었거나 `localhost` 가 아니면 `invalid uri authority` 로 거절한다(독립 검증 'a' 2차 낮음 1). 그래서 UNC 는 슬래시를 하나 더해 authority 를 비우고 `//서버/공유/…` 를 경로로 넘긴다(`file:////서버/공유/…` —
    Windows 가 그 경로를 UNC 로 읽는다). 확장 경로 접두사(`\\\\?\\C:\\…`·`\\\\?\\UNC\\서버\\공유\\…`)는 먼저 걷는다(그대로는 authority 가 `?` 가 된다). 일반 경로의 주소는 예전과 같다.
    같은 `mode=ro` 라서 오래된 저널은 여전히 정리하지 못하고(읽기 전용 열기의 약속) 파일은 한 바이트도 바뀌지 않는다 — 일반 경로로 열어 `PRAGMA query_only` 를 거는 방법은 연결이 쓰기 가능이라 옛 저널을 되돌려 파일을 바꿀 수 있어 쓰지 않았다."""
    resolved = Path(path).resolve()
    text = os.fspath(resolved)
    if not _UNC_OR_EXTENDED.match(text):
        uri = resolved.as_uri()
    else:
        for prefix, replacement in (("\\\\?\\UNC\\", "\\\\"), ("\\\\?\\", "")):
            if text.startswith(prefix):
                text = replacement + text[len(prefix):]
                break
        uri = PureWindowsPath(text).as_uri()
    if uri.startswith("file://") and not uri.startswith("file:///"):        # `file://서버/공유/…` — authority 가 있다
        uri = "file:////" + uri[len("file://"):]
    return uri + "?mode=ro"


class Store:
    """한 SQLite 파일을 여는 저장소. `with Store.open(경로) as store:` 로 쓴다(밖으로 나가면 닫는다). 여러 스레드가 함께 써도 된다."""

    def __init__(self, path, connection, keep_revisions, *, busy_seconds=BUSY_SECONDS, read_only=False):
        self.path = Path(path)
        self._db = connection
        self._keep = max(int(keep_revisions), 1)
        self._busy = busy_seconds
        self._read_only = read_only
        self._version = SCHEMA_VERSION                    # 열 때 파일의 실제 구조 판으로 다시 적힌다(`_prepare`)
        self._lock = threading.RLock()

    # ---- 열기·닫기 -------------------------------------------------------------------------------------------------------
    @classmethod
    def open(cls, path, *, keep_revisions=KEEP_REVISIONS, busy_seconds=BUSY_SECONDS, migrate=True):
        """파일이 없으면 만들고(폴더도), 있으면 이 프로그램의 데이터 파일인지 검사한다. 검사에 걸리면 파일을 건드리지 않고 AppError.
        `migrate=False` 는 **읽기 전용 열기**다 — 상태를 보기만 하는 도구(점검 같은 것)가 쓴다: 파일을 만들지도 구조를 올리지도 않고 한 바이트도(수정 시각까지) 바꾸지 않으며,
        옛 구조의 파일은 `needs_migration`·`schema_version` 으로 알려 줄 뿐이고, 쓰는 일은 모두 거절한다(보관함 파일을 바꾸지 않고 다른 폴더에 사본만 만드는 `backup(폴더)` 는 예외로 허용한다). 읽기만 하는 도구는 이 방식으로 연다(docs/ARCHITECTURE.md §10).
        (쓰다가 갑자기 꺼져 정리 못 한 저장이 남은 파일은 읽기 전용으로는 읽을 수 없어 STORE_RECOVERY_PENDING — 일반 열기가 그것을 정리한다.)"""
        path = Path(os.fspath(path))
        if not migrate:
            return cls._open_read_only(path, keep_revisions, busy_seconds)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not path.exists() or path.stat().st_size == 0
        except OSError as error:
            raise AppError("FILE_WRITE_FAILED", {"경로": str(path.parent)}, detail=_detail(error)) from None
        try:
            connection = sqlite3.connect(str(path), timeout=busy_seconds, isolation_level=None, check_same_thread=False)
        except sqlite3.Error as error:
            raise store_error(error, path) from None
        store = cls(path, connection, keep_revisions, busy_seconds=busy_seconds)
        try:
            store._prepare(fresh)
        except BaseException:
            connection.close()
            raise
        return store

    @classmethod
    def _open_read_only(cls, path, keep_revisions, busy_seconds):
        try:
            missing = not path.exists() or (path.is_file() and path.stat().st_size == 0)
            uri = _read_only_uri(path)
        except (OSError, ValueError) as error:
            raise AppError("FILE_WRITE_FAILED", {"경로": str(path)}, detail=_detail(error)) from None
        if missing:
            raise AppError("CONTENT_NOT_FOUND", {"항목": f"글 데이터 파일 {path.name}"}, detail="읽기 전용으로 열 파일이 없거나 비어 있다(읽기 전용 열기는 파일을 만들지 않는다)")
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=busy_seconds, isolation_level=None, check_same_thread=False)
        except sqlite3.Error as error:
            raise store_error(error, path) from None
        store = cls(path, connection, keep_revisions, busy_seconds=busy_seconds, read_only=True)
        try:
            store._prepare_read_only()
        except BaseException:
            connection.close()
            raise
        return store

    def _prepare(self, fresh):
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA secure_delete = ON")
            if not (fresh and self._create()):             # 새로 만들었으면 끝. 아니면(원래 있던 파일이거나 기다리는 사이 다른 프로세스가 먼저 만들었다) 검사하고 올린다
                self._verify()
                self._migrate()
            self._version = self._read_version()
        except sqlite3.Error as error:
            raise store_error(error, self.path) from None

    def _prepare_read_only(self):
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._verify()
            self._version = self._read_version()
        except sqlite3.Error as error:
            mapped = store_error(error, self.path)
            if mapped.code == "FILE_WRITE_FAILED" and self._has_unfinished_save():
                raise AppError("STORE_RECOVERY_PENDING", {"파일": self.path.name}, detail=mapped.detail) from None
            raise mapped from None

    def _has_unfinished_save(self):
        """앱이 쓰다가 갑자기 꺼지면서 남긴 저널(`<파일>-journal`)이 있는가 — 읽기 전용 연결은 그것을 정리하지 못해 '쓸 수 없다' 는 오류를 낸다(일반 열기는 읽으면서 정리한다)."""
        try:
            return os.path.getsize(str(self.path) + "-journal") > 0
        except OSError:
            return False

    def _read_version(self):
        return self._db.execute("PRAGMA user_version").fetchone()[0]

    @property
    def schema_version(self):
        """열린 파일의 구조 판 번호(보통 열면서 올리므로 지금 프로그램의 판 `SCHEMA_VERSION`, 읽기 전용으로 연 옛 파일은 그 파일의 판)."""
        return self._version

    @property
    def needs_migration(self):
        """파일이 지금 프로그램보다 낮은 구조 판인가 — 읽기 전용(`migrate=False`)으로 열었을 때만 참일 수 있다(보통 열기는 열면서 올린다)."""
        return self._version < SCHEMA_VERSION

    @property
    def read_only(self):
        return self._read_only

    def _create(self):
        """처음 만들 때. 쓰기 잠금을 잡은 뒤에도 파일이 비어 있을 때만 만든다 — 기다리는 사이 다른 프로세스가 먼저 만들었으면 만들지 않고 False
        (부른 쪽이 검사·올리기로 이어 간다). `open` 이 실패하면 연결을 닫아 트랜잭션이 되돌려지므로 중간 실패는 따로 되돌리지 않는다."""
        self._begin()
        if self._db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]:
            self._rollback()
            return False
        for statement in _SCHEMA:
            self._db.execute(statement)
        self._db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.execute("COMMIT")
        return True

    def _verify(self):
        application = self._db.execute("PRAGMA application_id").fetchone()[0]
        version = self._read_version()
        if application != APPLICATION_ID:
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail="이 프로그램의 데이터 파일이 아니다")
        if version > SCHEMA_VERSION:
            raise AppError("STORE_VERSION_UNSUPPORTED", {"파일": self.path.name}, detail=f"파일 버전 {version} > 지원 {SCHEMA_VERSION}")
        if version < MIN_SCHEMA_VERSION:
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail=f"파일 버전 {version} 은 이 프로그램이 만든 적이 없다")
        result = self._db.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail=_detail(result))
        problem = _shape_problem(self._db, version)
        if problem:
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail=problem)

    def _migrate(self):
        """구조를 지금 판으로 올린다 — 한 트랜잭션이고 실패하면 파일은 올리기 전 그대로다.
        순서: ① 쓰기 잠금(`BEGIN IMMEDIATE`)을 먼저 잡고 ② 잠금을 쥔 채 판 번호를 **다시 읽어** 기다리는 사이 다른 프로세스가 이미 올렸으면 아무것도 하지 않고 끝낸다
        (여러 창이 동시에 열어도 하나만 올리고 나머지는 성공으로 이어 간다) ③ 사본(`<파일>.v<번호>.bak`)을 두고 ④ 단계를 하나씩 실행하고 ⑤ 같은 트랜잭션 안에서 판 번호를 올린 뒤 COMMIT.
        사본을 잠금 안에서 만들므로 다른 프로세스가 올린 뒤의 내용으로 사본을 덮어쓸 수 없고, 판 번호가 COMMIT 앞에 있으므로 어느 순간에 죽어도 '표는 있는데 판 번호는 옛 것' 인 파일이 남지 않는다."""
        if self._read_version() >= SCHEMA_VERSION:
            return
        if not os.access(self.path, os.W_OK):                # 읽기 전용 파일은 쓰기 잠금이 잡혀도 첫 쓰기에서야 실패한다 — 사본 같은 것을 만들기 전에 알린다
            raise AppError("MIGRATION_BLOCKED", {"이유": "데이터 파일이 읽기 전용입니다"}, detail="쓸 수 없는 파일이라 올리지 않았다")
        self._check_copy_path()
        try:
            self._begin()
            version = self._read_version()
            if version >= SCHEMA_VERSION:
                self._rollback()                            # 기다리는 사이 다른 프로세스가 올렸다 — 바꾼 것이 없으니 되돌리기와 같다
                return
            missing = next((number for number in range(version, SCHEMA_VERSION) if number not in MIGRATIONS), None)
            if missing is not None:
                raise RuntimeError(f"버전 {missing} 에서 올리는 단계가 없다")
            self._keep_copy(version)
            while version < SCHEMA_VERSION:
                MIGRATIONS[version](self._db)
                version += 1
            self._db.execute(f"PRAGMA user_version = {version}")
            self._db.execute("COMMIT")
        except AppError:
            self._rollback()
            raise
        except Exception as error:
            self._rollback()
            raise self._migration_error(error) from None

    def _migration_error(self, error):
        """올리다 난 오류를 쉬운 안내로 — 잠김은 STORE_LOCKED('잠시 뒤 다시'), 깨짐은 STORE_CORRUPT, 디스크 가득·읽기 전용·사본을 못 두는 폴더 같은 환경 문제는 MIGRATION_BLOCKED
        (파일은 바뀌지 않았다고 알린다), 그 밖은 MIGRATION_FAILED."""
        if isinstance(error, sqlite3.Error):
            mapped = store_error(error, self.path)
            if mapped.code in ("STORE_LOCKED", "STORE_CORRUPT"):
                return mapped
            if mapped.code in ("DISK_FULL", "FILE_WRITE_FAILED"):
                return AppError("MIGRATION_BLOCKED", {"이유": _blocked_reason(mapped.code, str(error))}, detail=mapped.detail)
        elif isinstance(error, OSError):
            reason = _os_blocked_reason(error)
            if reason:
                return AppError("MIGRATION_BLOCKED", {"이유": reason}, detail=f"{type(error).__name__}: {_detail(error)}")
        return AppError("MIGRATION_FAILED", detail=f"{type(error).__name__}: {_detail(error)}")

    def _check_copy_path(self):
        """Windows 는 경로가 260 자를 넘으면 파일을 못 만든다 — 사본 이름이 그 한계를 넘기 전에(아무것도 만들거나 바꾸기 전에) 알린다."""
        if _COPY_PATH_LIMIT is not None and len(os.path.abspath(self.path)) + len(f".v{self._read_version()}.bak.tmp") > _COPY_PATH_LIMIT:
            raise AppError("MIGRATION_BLOCKED", {"이유": "데이터 파일의 경로가 너무 길어 사본을 만들 수 없습니다(더 짧은 폴더로 옮겨 주세요)"}, detail=f"사본 경로가 {_COPY_PATH_LIMIT}자를 넘는다")

    def _copy_name(self, version, number):
        return self.path.with_name(f"{self.path.name}.v{version}.bak" if number == 1 else f"{self.path.name}.v{version}.{number}.bak")

    def _keep_copy(self, version):
        """지금 파일(판 `version`)과 똑같은 사본이 파일로 있게 한다 — 이미 있는 사본은 **덮어쓰지 않는다**: 똑같은 것이면 그것을 쓰고, 다르거나 읽을 수 없으면 건드리지 않고 다음 이름
        (`.v1.bak` → `.v1.2.bak` …)으로 새로 만든다. 쓰기 잠금을 쥐고 있을 때만 부른다(그래야 사본과 파일이 같은 내용이다)."""
        for number in range(1, MAX_COPY_NAMES + 1):
            target = self._copy_name(version, number)
            if not os.path.lexists(target):
                self._make_copy(target, version)
                return target
            if self._same_content(target, version):
                return target
        raise AppError("MIGRATION_BLOCKED", {"이유": f"사본 이름({self._copy_name(version, 1).name} 등 {MAX_COPY_NAMES}개)이 모두 쓰이고 있습니다(오래된 사본을 정리해 주세요)"},
                        detail="사본 이름이 모두 쓰이고 있다")

    def _make_copy(self, target, version):
        """임시 이름으로 사본을 만들고 점검한 뒤 이름을 바꿔 둔다 — 도중에 죽거나 실패해도 `target` 자리에는 반쯤 쓴 파일이 보이지 않는다."""
        temp = target.with_name(target.name + ".tmp")
        self._discard(temp)                                 # 앞서 죽은 시도의 찌꺼기(쓰기 잠금을 쥐고 있으니 지금 이 파일을 올리는 다른 곳은 없다)
        try:
            self._snapshot(temp)
            with closing(sqlite3.connect(_read_only_uri(temp), uri=True, timeout=self._busy)) as copy:
                found = (copy.execute("PRAGMA application_id").fetchone()[0], copy.execute("PRAGMA user_version").fetchone()[0], copy.execute("PRAGMA quick_check").fetchone()[0])
            if found != (APPLICATION_ID, version, "ok"):
                raise RuntimeError(f"만든 사본이 올바르지 않다(이름표·판 번호·점검: {found})")
            os.rename(temp, target)                          # Windows 는 이미 있으면 실패한다(덮어쓰지 않는다). 이름이 비어 있는지는 위에서 쓰기 잠금을 쥔 채 확인했다
        except BaseException:
            self._discard(temp)
            raise

    def _snapshot(self, destination):
        """지금 파일의 일관된 사본을 `destination` 에 만든다. **다른 연결**(읽기 전용)으로 읽는다 — 이 연결은 쓰기 잠금을 쥐고 있어 같은 연결로 backup 하면 영원히 기다린다.
        쓰기 잠금은 읽기를 막지 않고, 우리가 잠금을 쥐고 있어 읽는 동안 다른 쪽이 바꾸지도 못한다. 시간 상한(`COPY_SECONDS`)이 있어 **계속 잠겨(BUSY·LOCKED) 있으면** 멈추고 알린다 —
        큰 파일이라 오래 걸려도 진행되고 있으면 끝까지 기다린다."""
        stuck_since = []                                    # 잠겨서 못 나아가기 시작한 시각(나아가면 비운다)

        def watch(status, remaining, total):
            if status not in (_SQLITE_BUSY, _SQLITE_LOCKED):
                stuck_since.clear()
                return
            if not stuck_since:
                stuck_since.append(time.monotonic())
            if time.monotonic() - stuck_since[0] > COPY_SECONDS:
                raise AppError("STORE_LOCKED", detail=f"사본을 만드는 동안 {COPY_SECONDS:g}초가 넘도록 파일이 계속 잠겨 있다")

        with closing(sqlite3.connect(_read_only_uri(self.path), uri=True, timeout=self._busy)) as source, closing(sqlite3.connect(str(destination))) as target:
            source.backup(target, progress=watch)

    def _same_content(self, existing, version):
        """이미 있는 사본이 지금 파일(판 `version`)과 이름표·판 번호·모든 표와 행까지 똑같은가. 파일이 아니거나 읽을 수 없으면(깨짐·다른 프로그램이 잠금) 믿지 않는다."""
        try:
            if not existing.is_file():
                return False
            with closing(sqlite3.connect(_read_only_uri(existing), uri=True, timeout=self._busy)) as old:
                if (old.execute("PRAGMA application_id").fetchone()[0], old.execute("PRAGMA user_version").fetchone()[0]) != (APPLICATION_ID, version):
                    return False
                nothing = object()
                return all(mine == theirs for mine, theirs in itertools.zip_longest(self._db.iterdump(), old.iterdump(), fillvalue=nothing))
        except (sqlite3.Error, OSError):
            return False

    @staticmethod
    def _discard(path):
        """임시 사본과 그 저널을 지운다(없으면 그대로 둔다)."""
        for suffix in ("", "-journal"):
            try:
                os.unlink(str(path) + suffix)
            except OSError:
                pass                                         # 없거나 못 지워도 사본 만들기 자체의 성공·실패와 무관하다 — 다음 시도가 다시 치운다

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- 트랜잭션 ---------------------------------------------------------------------------------------------------------
    def _begin(self):
        self._db.execute("BEGIN IMMEDIATE")

    def _rollback(self):
        try:
            self._db.execute("ROLLBACK")
        except sqlite3.Error:
            pass                                          # 시작도 못 했거나 이미 끝난 트랜잭션 — 되돌릴 것이 없다

    def _refuse_if_read_only(self):
        """읽기 전용(`migrate=False`)으로 연 저장소는 쓰는 일을 모두 거절한다(보관함 파일을 바꾸지 않는 `backup(폴더)` 만 예외) — 부르는 쪽의 실수이므로 사용자 안내가 아니라 '예상 밖 오류' 로 낸다."""
        if self._read_only:
            raise AppError("UNEXPECTED_ERROR", detail="읽기 전용(migrate=False)으로 연 저장소에는 쓸 수 없다")

    def _write(self, work):
        """work(연결) 을 한 트랜잭션으로 실행하고 결과를 돌려준다. 실패하면 되돌리고 AppError."""
        self._refuse_if_read_only()
        with self._lock:
            try:
                self._begin()
                try:
                    result = work(self._db)
                    self._db.execute("COMMIT")
                    return result
                except BaseException:
                    self._rollback()
                    raise
            except sqlite3.Error as error:
                raise store_error(error, self.path) from None

    def _read(self, sql, params=()):
        with self._lock:
            try:
                return self._db.execute(sql, params).fetchall()
            except sqlite3.Error as error:
                raise store_error(error, self.path) from None

    # ---- 프로젝트 ---------------------------------------------------------------------------------------------------------
    def save(self, project):
        """프로젝트 전체를 저장한다(없으면 만들고 있으면 바꾼다). 저장된 판보다 낮은 판이면 STORE_CONFLICT. 새 판이면 판 기록을 남긴다."""
        if not isinstance(project, ContentProject):
            raise AppError("CONTENT_INVALID", {"항목": "프로젝트"})
        project._validate()                                # 저장하기 전에 한 번 더 — 깨진 자료를 파일에 넣지 않는다(프로젝트 번호 모양도 여기서)
        data = _dump(project.to_dict())
        snapshot = _dump({"title": project.title, "source_content": project.source_content, "references": list(project.references),
                          "assets": [asset.to_dict() for asset in project.assets]})

        def work(db):
            row = db.execute("SELECT revision FROM projects WHERE project_id = ?", (project.project_id,)).fetchone()
            if row is not None and row[0] > project.revision:
                raise AppError("STORE_CONFLICT", {"항목": project.title}, detail=f"저장된 판 {row[0]} > 이 화면의 판 {project.revision}")
            db.execute(
                "INSERT INTO projects (project_id, title, revision, created_at, updated_at, data) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (project_id) DO UPDATE SET title = excluded.title, revision = excluded.revision, created_at = excluded.created_at,"
                " updated_at = excluded.updated_at, data = excluded.data",
                (project.project_id, project.title, project.revision, project.created_at, project.updated_at, data))
            db.execute("INSERT OR IGNORE INTO revisions (project_id, revision, saved_at, data) VALUES (?, ?, ?, ?)",
                       (project.project_id, project.revision, project.updated_at, snapshot))
            db.execute(
                "DELETE FROM revisions WHERE project_id = ? AND revision <= ("
                " SELECT revision FROM revisions WHERE project_id = ? ORDER BY revision DESC LIMIT 1 OFFSET ?)",
                (project.project_id, project.project_id, self._keep))

        self._write(work)

    def load(self, project_id):
        """프로젝트 하나. 없으면 CONTENT_NOT_FOUND, 저장된 자료가 올바르지 않으면 STORE_CORRUPT."""
        _check_id(project_id)
        rows = self._read("SELECT data FROM projects WHERE project_id = ?", (project_id,))
        if not rows:
            raise AppError("CONTENT_NOT_FOUND", {"항목": shown_ref(project_id)})
        return self._parse(project_id, rows[0][0])

    def _parse(self, project_id, text):
        try:
            project = ContentProject.from_dict(json.loads(text))
        except (ValueError, TypeError, RecursionError, AppError) as error:
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail=f"프로젝트 {project_id}: {type(error).__name__}") from None
        if project.project_id != project_id:
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail=f"프로젝트 {project_id}: 번호가 다르다")
        return project

    def list(self):
        """프로젝트 목록(최근에 고친 것이 먼저, 같으면 번호 순)."""
        rows = self._read("SELECT project_id, title, revision, created_at, updated_at FROM projects ORDER BY updated_at DESC, project_id ASC")
        return [Summary(*row) for row in rows]

    def exists(self, project_id):
        _check_id(project_id)
        return bool(self._read("SELECT 1 FROM projects WHERE project_id = ?", (project_id,)))

    def delete(self, project_id):
        """프로젝트와 그 판 기록·초안을 지운다. 없으면 CONTENT_NOT_FOUND. (되돌릴 수 없다 — 부르는 쪽이 사용자 확인을 거친다.)"""
        _check_id(project_id)

        def work(db):
            if db.execute("DELETE FROM projects WHERE project_id = ?", (project_id,)).rowcount == 0:
                raise AppError("CONTENT_NOT_FOUND", {"항목": shown_ref(project_id)})
            db.execute("DELETE FROM drafts WHERE project_id = ?", (project_id,))

        self._write(work)

    # ---- 판 기록 ----------------------------------------------------------------------------------------------------------
    def history(self, project_id):
        """남아 있는 판 번호와 저장 시각(새 것이 먼저)."""
        _check_id(project_id)
        return [(row[0], row[1]) for row in self._read("SELECT revision, saved_at FROM revisions WHERE project_id = ? ORDER BY revision DESC", (project_id,))]

    def snapshot(self, project_id, revision):
        """옛 판의 원고. 없으면 CONTENT_NOT_FOUND. 되돌리려면 `project.edit(...)` 에 넣는다 — 기록은 다시 쓰지 않고 새 판이 생긴다."""
        _check_id(project_id)
        rows = self._read("SELECT saved_at, data FROM revisions WHERE project_id = ? AND revision = ?", (project_id, revision))
        if not rows:
            raise AppError("CONTENT_NOT_FOUND", {"항목": f"{shown_ref(project_id)} 의 {revision}판"})
        try:
            data = json.loads(rows[0][1])
            return Snapshot(revision, rows[0][0], data["title"], data["source_content"], tuple(data["references"]), tuple(Asset(**raw) for raw in data["assets"]))
        except (ValueError, TypeError, KeyError, RecursionError, AppError):
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail=f"프로젝트 {project_id} 의 {revision}판 기록") from None

    # ---- 자동 저장 초안 ----------------------------------------------------------------------------------------------------
    def save_draft(self, project_id, text, *, now=None):
        """편집기에서 아직 저장하지 않은 글을 자동으로 보관한다(프로젝트와 별개 — 프로젝트가 아직 없어도 된다)."""
        _check_id(project_id)
        if not isinstance(text, str) or len(text) > MAX_DRAFT_CHARS:
            raise AppError("CONTENT_INVALID", {"항목": "초안"})
        stamp = utc_now() if now is None else now
        self._write(lambda db: db.execute(
            "INSERT INTO drafts (project_id, text, saved_at) VALUES (?, ?, ?)"
            " ON CONFLICT (project_id) DO UPDATE SET text = excluded.text, saved_at = excluded.saved_at", (project_id, text, stamp)))

    def load_draft(self, project_id):
        _check_id(project_id)
        rows = self._read("SELECT project_id, text, saved_at FROM drafts WHERE project_id = ?", (project_id,))
        return Draft(*rows[0]) if rows else None

    def drafts(self):
        """보관된 초안 모두(최근 것이 먼저) — 앱이 갑자기 꺼진 뒤 되살릴 글을 찾을 때."""
        return [Draft(*row) for row in self._read("SELECT project_id, text, saved_at FROM drafts ORDER BY saved_at DESC, project_id ASC")]

    def discard_draft(self, project_id):
        _check_id(project_id)
        self._write(lambda db: db.execute("DELETE FROM drafts WHERE project_id = ?", (project_id,)))

    # ---- 주제 후보 ----------------------------------------------------------------------------------------------------------
    def _has_candidates(self):
        """파일에 후보 표가 있는가(판 2 부터). 읽기 전용으로 연 판 1 파일에는 아직 없다 — 그때 후보를 읽는 일은 '후보가 하나도 없음' 이다."""
        return self._version >= 2

    def save_candidate(self, candidate, *, expected_revision=None):
        """후보 하나를 저장한다(없으면 만들고 있으면 바꾼다). 이미 있는 후보는 **내가 불러온 판에서 바뀐 것**일 때만 저장된다 — `expected_revision` 은 내가 불러왔을 때의 판이고,
        주지 않으면 이 후보의 판 바로 앞(`revision - 1`, 한 번 고친 것)이다. 저장된 판이 그것과 다르면 다른 쪽이 그 사이에 바꾼 것이므로 STORE_CONFLICT 다(한 번에 한 판씩만 오르는
        저장이라, 낡은 복사본이 판이 더 높아졌다는 이유로 다른 쪽의 변경을 덮어쓰지 못한다 — 여러 번 고친 복사본은 `expected_revision=불러온 판` 을 주어 저장한다).
        같은 판에 똑같은 내용을 다시 저장하는 것은 괜찮다(연결이 끊겨 다시 시도한 경우 등). 상태는 저장된 상태에서 `TRANSITIONS` 표에 있는 곳으로만 바뀐다(같은 상태 유지는 허용,
        표에 없으면 CANDIDATE_TRANSITION_INVALID). 연결한 글(project_id)이 없으면 CONTENT_NOT_FOUND. 거절되면 저장된 것은 그대로다. 새 후보(저장된 것이 없음)는 판 번호와 상관없이
        만들 수 있지만, `expected_revision` 을 줬는데 저장된 것이 없으면(그 사이 지워졌다) CANDIDATE_NOT_FOUND 다."""
        if not isinstance(candidate, Candidate):
            raise candidate_invalid("후보", "후보(Candidate)여야 합니다")
        candidate._validate()                              # 저장하기 전에 한 번 더 — 깨진 자료를 파일에 넣지 않는다
        if expected_revision is not None and (not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or not 1 <= expected_revision < candidate.revision):
            raise candidate_invalid("불러온 판", f"1 이상이고 이 후보의 판({candidate.revision})보다 작은 정수여야 합니다")
        self._write(lambda db: self._put_candidate(db, candidate, expected_revision))

    @staticmethod
    def _candidate_columns(candidate):
        payload = candidate.to_dict()
        return payload.pop("project_id"), _dump(payload)      # 연결한 글은 열이 기준이다(그 글을 지우면 DB 가 연결을 끊는다) — 자료(data)에는 적지 않는다

    def _put_candidate(self, db, candidate, expected_revision=None):
        link, data = self._candidate_columns(candidate)
        row = db.execute("SELECT revision, project_id, data, status FROM candidates WHERE candidate_id = ?", (candidate.candidate_id,)).fetchone()
        if row is None and expected_revision is not None:
            raise AppError("CANDIDATE_NOT_FOUND", {"항목": short_id(candidate.candidate_id)}, detail="불러온 뒤 그 후보가 지워졌다")
        if row is not None:
            stored_revision, stored_link, stored_data, stored_status = row
            if candidate.revision == stored_revision:
                if (stored_link, stored_data) != (link, data):
                    raise AppError("STORE_CONFLICT", {"항목": f"주제 후보 {candidate.topic}"}, detail=f"같은 판 {stored_revision} 인데 저장된 내용이 다르다")
                return                                      # 똑같은 것을 다시 저장 — 할 일이 없다(연결이 끊겨 다시 시도한 경우 등)
            base = candidate.revision - 1 if expected_revision is None else expected_revision
            if stored_revision != base:                     # 내가 불러온(고치기 시작한) 판이 아니다 — 그 사이 다른 쪽이 바꿨다(또는 판 번호를 건너뛰었다)
                raise AppError("STORE_CONFLICT", {"항목": f"주제 후보 {candidate.topic}"}, detail=f"저장된 후보 판 {stored_revision} / 이 화면이 고치기 시작한 판 {base}(저장하려는 판 {candidate.revision})")
            if candidate.status != stored_status and candidate.status not in TRANSITIONS.get(stored_status, ()):
                raise AppError("CANDIDATE_TRANSITION_INVALID", {"현재 상태": STATUS_KO.get(stored_status, str(stored_status)), "요청 상태": STATUS_KO[candidate.status]},
                               detail=f"저장된 상태 {stored_status} → {candidate.status} 는 표에 없다")
        if link is not None and db.execute("SELECT 1 FROM projects WHERE project_id = ?", (link,)).fetchone() is None:
            raise AppError("CONTENT_NOT_FOUND", {"항목": shown_ref(link)})
        db.execute(
            "INSERT INTO candidates (candidate_id, keyword_key, status, project_id, revision, created_at, updated_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (candidate_id) DO UPDATE SET keyword_key = excluded.keyword_key, status = excluded.status, project_id = excluded.project_id,"
            " revision = excluded.revision, created_at = excluded.created_at, updated_at = excluded.updated_at, data = excluded.data",
            (candidate.candidate_id, keyword_key(candidate.keyword), candidate.status, link, candidate.revision, candidate.created_at, candidate.updated_at, data))

    @staticmethod
    def _decode_candidate(candidate_id, project_id, text):
        """저장된 한 행 → Candidate. 올바르지 않으면 ValueError(왜인지 짧은 글) — 읽는 쪽(`_parse_candidate`)과 점검(`check`)이 각자 알맞게 알린다."""
        try:
            payload = json.loads(text)
        except (ValueError, TypeError, RecursionError) as error:
            raise ValueError(type(error).__name__) from None
        if not isinstance(payload, dict) or "project_id" in payload:        # 연결한 글은 열이 기준이다 — 자료 안에 있으면 사람이 고친 것이다
            raise ValueError("자료의 모양이 올바르지 않다")
        try:
            candidate = Candidate.from_dict({**payload, "project_id": project_id})
        except (ValueError, TypeError, RecursionError, AppError) as error:
            raise ValueError(_detail(error.detail) if isinstance(error, AppError) and error.detail else type(error).__name__) from None
        if candidate.candidate_id != candidate_id:
            raise ValueError("자료 속 후보 번호가 다르다")
        return candidate

    def _parse_candidate(self, candidate_id, project_id, text):
        try:
            return self._decode_candidate(candidate_id, project_id, text)
        except ValueError as error:
            raise AppError("CANDIDATE_CORRUPT", {"번호": short_id(candidate_id)}, detail=f"후보 {candidate_id}: {error}") from None

    def _topic_of(self, candidate_id):
        """그 후보의 주제(사람이 읽는 이름) — 후보가 없으면 None, 있는데 읽을 수 없으면(깨짐·잠김) 빈 글(번호만 보여 준다)."""
        if not self._has_candidates():
            return None
        try:
            rows = self._read("SELECT data FROM candidates WHERE candidate_id = ?", (candidate_id,))
            if not rows:
                return None
            topic = json.loads(rows[0][0]).get("topic")
        except (AppError, ValueError, TypeError, AttributeError, RecursionError):
            return ""
        return topic[:40] if isinstance(topic, str) else ""

    def load_candidate(self, candidate_id):
        """후보 하나. 없으면 CANDIDATE_NOT_FOUND, 저장된 자료가 올바르지 않으면 CANDIDATE_CORRUPT(그 후보 하나만 막힌다)."""
        _check_candidate_id(candidate_id)
        rows = self._read("SELECT project_id, data FROM candidates WHERE candidate_id = ?", (candidate_id,)) if self._has_candidates() else []
        if not rows:
            raise AppError("CANDIDATE_NOT_FOUND", {"항목": short_id(candidate_id)})
        return self._parse_candidate(candidate_id, *rows[0])

    def list_candidates(self, *, status=None, blog=None):
        """후보 목록(최근에 고친 것이 먼저, 같으면 번호 순). `status` 로 상태를, `blog` 로 '추천 대상 블로그'에 그 블로그가 든 후보만 거를 수 있다(둘 다 알려진 값이어야 한다).
        깨진 후보가 하나라도 걸리면 CANDIDATE_CORRUPT 로 멈춘다(그 후보만 `delete_candidate` 로 지울 수 있다)."""
        sql, params = "SELECT candidate_id, project_id, data FROM candidates", ()
        if status is not None:
            if not isinstance(status, str) or status not in CANDIDATE_STATUSES:
                raise candidate_invalid("상태", "다음 중 하나여야 합니다: " + ", ".join(STATUS_KO[state] for state in CANDIDATE_STATUSES))
            sql, params = sql + " WHERE status = ?", (status,)
        if blog is not None and (not isinstance(blog, str) or blog not in PLATFORMS):
            raise candidate_invalid("블로그", "다음 중 하나여야 합니다: " + ", ".join(PLATFORMS))
        if not self._has_candidates():
            return []
        found = [self._parse_candidate(candidate_id, link, data) for candidate_id, link, data in self._read(sql + " ORDER BY updated_at DESC, candidate_id ASC", params)]
        return found if blog is None else [candidate for candidate in found if blog in candidate.blogs]

    def set_candidate_status(self, candidate_id, status, *, blog=None, now=None):
        """후보의 상태를 `TRANSITIONS` 표대로 옮기고 옮긴 후보를 돌려준다. 읽고 바꾸고 쓰는 것이 한 트랜잭션이라 다른 곳의 변경을 덮어쓰지 않는다.
        없으면 CANDIDATE_NOT_FOUND, 표에 없는 이동이면 CANDIDATE_TRANSITION_INVALID(저장된 것은 그대로). '선택됨' 으로 옮길 때의 `blog` 는 `Candidate.moved` 를 본다."""
        _check_candidate_id(candidate_id)
        moved = []

        def work(db):
            row = db.execute("SELECT project_id, data FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
            if row is None:
                raise AppError("CANDIDATE_NOT_FOUND", {"항목": short_id(candidate_id)})
            changed = self._parse_candidate(candidate_id, *row).moved(status, blog=blog, now=now)
            self._put_candidate(db, changed)
            moved.append(changed)

        self._write(work)
        return moved[0]

    def delete_candidate(self, candidate_id, *, confirm=False):
        """후보를 지운다(되돌릴 수 없다). `confirm=True` 를 주지 않으면 아무것도 지우지 않고 CANDIDATE_CONFIRM_REQUIRED(문구에 그 후보의 주제가 보인다), 없는 후보면 CANDIDATE_NOT_FOUND.
        연결한 글(프로젝트)은 그대로 둔다. 깨져서 읽을 수 없는 후보도 이 방법으로 그 후보만 지울 수 있다."""
        _check_candidate_id(candidate_id)
        if confirm is not True:
            topic = self._topic_of(candidate_id)
            if topic is None:
                raise AppError("CANDIDATE_NOT_FOUND", {"항목": short_id(candidate_id)})
            raise AppError("CANDIDATE_CONFIRM_REQUIRED", {"항목": f"{topic} (번호 {short_id(candidate_id)})" if topic else f"번호 {short_id(candidate_id)}"})

        def work(db):
            if db.execute("DELETE FROM candidates WHERE candidate_id = ?", (candidate_id,)).rowcount == 0:
                raise AppError("CANDIDATE_NOT_FOUND", {"항목": short_id(candidate_id)})

        self._write(work)

    def add_candidates(self, plan):
        """새 후보들을 **한 트랜잭션**으로 더한다. 쓰기 잠금을 잡은 **뒤** 지금 있는 후보들을 읽어 `plan(후보들)` 에 넘기고, 그것이 돌려준 새 후보들을 모두 저장한다 — 읽고(이미 있는지 보고) 저장하는
        사이에 다른 프로세스가 끼어들 수 없어 같은 후보를 두 곳에서 동시에 더해도 겹치지 않고, 하나라도 안 되면(번호가 이미 있음·값이 틀림·디스크 오류 …) 하나도 저장되지 않는다.
        `plan` 은 순수하게 계산만 한다(안에서 이 저장소를 부르면 안 된다). 깨진 후보가 있으면 `list_candidates` 처럼 CANDIDATE_CORRUPT 로 멈춘다. 저장한 후보들을 튜플로 돌려준다."""
        saved = []

        def work(db):
            rows = db.execute("SELECT candidate_id, project_id, data FROM candidates ORDER BY updated_at DESC, candidate_id ASC").fetchall() if self._has_candidates() else []
            for candidate in plan([self._parse_candidate(*row) for row in rows]):
                if not isinstance(candidate, Candidate):
                    raise candidate_invalid("후보", "후보(Candidate)여야 합니다")
                candidate._validate()                      # 저장하기 전에 한 번 더 — 깨진 자료를 파일에 넣지 않는다
                if db.execute("SELECT 1 FROM candidates WHERE candidate_id = ?", (candidate.candidate_id,)).fetchone() is not None:
                    raise AppError("STORE_CONFLICT", {"항목": f"주제 후보 {candidate.topic}"}, detail="같은 번호의 후보가 이미 있다(새 후보만 더할 수 있다)")
                self._put_candidate(db, candidate)
                saved.append(candidate)

        self._write(work)
        return tuple(saved)

    def candidate_ids(self):
        """저장된 모든 후보의 번호(오름차순). 자료를 읽지 않으므로 깨져서 목록을 막는 후보도 나온다 — 그 후보를 번호 앞부분으로 찾아 지울 때 쓴다."""
        if not self._has_candidates():
            return ()
        return tuple(row[0] for row in self._read("SELECT candidate_id FROM candidates ORDER BY candidate_id"))

    def recent_selections(self, keyword, blog, within_days, *, now=None, exclude=None):
        """같은 핵심 키워드를 같은 블로그용으로 `within_days` 일 안에 이미 '선택'해 둔 후보들(방금 고른 것이 먼저) — 다시 고르려 할 때 경고하는 데 쓴다.
        지금 '선택됨' 인 후보만 센다(보류·제외·검토 중으로 물린 것은 쓰지 않기로 한 것이다). 키워드는 띄어쓰기·대소문자·덜 중요한 기호 차이를 무시하고 비교한다(`keyword_key` — C++ 와 C# 은 다르다).
        '선택됨' 인데 선택 기록이 하나도 없는 후보(상태만 적어 들여온 것)는 마지막으로 고친 시각에 추천 블로그 모두로 고른 것으로 본다 — 놓치느니 경고하는 쪽이 낫다.
        `within_days` 는 대상 블로그 프로필의 `topic_reuse_days`(0 이면 경고하지 않으므로 빈 목록). 고른 지 정확히 `within_days` 일째까지는 안에 든다.
        `exclude` 는 지금 고르려는 후보의 번호(자기 자신은 뺀다), `now` 는 기준 시각(시험용)."""
        key = keyword_key(keyword) if isinstance(keyword, str) else ""
        if not key:
            raise candidate_invalid("핵심 키워드", "글자나 숫자가 든 키워드여야 합니다")
        if not isinstance(blog, str) or blog not in PLATFORMS:
            raise candidate_invalid("블로그", "다음 중 하나여야 합니다: " + ", ".join(PLATFORMS))
        if not isinstance(within_days, int) or isinstance(within_days, bool) or not 0 <= within_days <= MAX_REUSE_DAYS:
            raise candidate_invalid("같은 주제 재사용 기준", f"0~{MAX_REUSE_DAYS} 사이의 정수(날수)여야 합니다")
        if exclude is not None:
            _check_candidate_id(exclude)
        moment = parse_stamp(utc_now() if now is None else now, "기준 시각")
        if within_days == 0 or not self._has_candidates():
            return []
        cutoff = (moment - timedelta(days=within_days)).strftime(STAMP_FORMAT)
        found = []
        for row in self._read("SELECT candidate_id, project_id, data FROM candidates WHERE keyword_key = ? AND status = ?", (key, "SELECTED")):
            candidate = self._parse_candidate(*row)
            picked = candidate.selected_time(blog)
            if picked is None and not candidate.selections and blog in candidate.blogs:
                picked = candidate.updated_at
            if candidate.candidate_id != exclude and picked is not None and picked >= cutoff:
                found.append(candidate)
        found.sort(key=lambda candidate: candidate.candidate_id)
        found.sort(key=lambda candidate: candidate.selected_time(blog) or candidate.updated_at, reverse=True)
        return found

    # ---- 점검·백업·복구 ----------------------------------------------------------------------------------------------------
    def check(self):
        """전체 점검 — 문제 문장 목록(비어 있으면 이상 없음). 파일 구조(integrity_check)와 각 프로젝트·주제 후보의 자료가 올바른지·열과 자료가 같은지 본다."""
        problems = []
        with self._lock:
            try:
                for row in self._db.execute("PRAGMA integrity_check").fetchall():
                    if row[0] != "ok":
                        problems.append(f"파일 구조: {_detail(row[0])}")
                for project_id, title, revision, created_at, updated_at, data in self._db.execute(
                        "SELECT project_id, title, revision, created_at, updated_at, data FROM projects ORDER BY project_id").fetchall():
                    try:
                        project = self._parse(project_id, data)
                    except AppError as error:
                        problems.append(f"프로젝트 {project_id}: {error.detail}")
                        continue
                    if (project.title, project.revision, project.created_at, project.updated_at) != (title, revision, created_at, updated_at):
                        problems.append(f"프로젝트 {project_id}: 목록 열과 자료가 다르다")
                for candidate_id, key_column, state, link, revision, created_at, updated_at, data in (self._db.execute(
                        "SELECT candidate_id, keyword_key, status, project_id, revision, created_at, updated_at, data FROM candidates ORDER BY candidate_id").fetchall()
                        if self._has_candidates() else ()):
                    try:
                        candidate = self._decode_candidate(candidate_id, link, data)
                    except ValueError as error:
                        problems.append(f"후보 {candidate_id}: {error}")
                        continue
                    if (keyword_key(candidate.keyword), candidate.status, candidate.revision, candidate.created_at, candidate.updated_at) != (key_column, state, revision, created_at, updated_at):
                        problems.append(f"후보 {candidate_id}: 목록 열과 자료가 다르다")
                    if link is not None and self._db.execute("SELECT 1 FROM projects WHERE project_id = ?", (link,)).fetchone() is None:
                        problems.append(f"후보 {candidate_id}: 없는 글({link})에 연결돼 있다")
            except sqlite3.Error as error:
                problems.append(f"점검 중 오류: {_detail(error)}")
        return problems

    def _copy_to(self, destination):
        """SQLite 백업 기능으로 지금 내용을 다른 파일로 복사한다(열려 있어도 일관된 사본)."""
        with closing(sqlite3.connect(str(destination))) as target:
            self._db.backup(target)

    def backup(self, folder, *, keep=KEEP_BACKUPS, now=None):
        """폴더에 `<이름>-YYYYMMDD-HHMMSS.db` 사본을 만든다(임시 파일에서 점검한 뒤 이름을 바꾼다). 오래된 사본은 `keep` 개만 남긴다. 실패하면 BACKUP_FAILED."""
        folder = Path(os.fspath(folder))
        moment = datetime.now(timezone.utc) if now is None else now
        name = f"{self.path.stem}-{moment.strftime('%Y%m%d-%H%M%S')}.db"
        final, temp = folder / name, folder / (name + ".tmp")
        with self._lock:
            try:
                folder.mkdir(parents=True, exist_ok=True)
                self._copy_to(temp)
                with closing(sqlite3.connect(str(temp))) as copy:
                    if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise OSError("만든 사본의 점검이 실패했다")
                os.replace(temp, final)
            except (OSError, sqlite3.Error) as error:
                try:
                    temp.unlink()
                except OSError:
                    pass
                raise AppError("BACKUP_FAILED", detail=_detail(error)) from None
        self._prune_backups(folder, keep)
        return final

    def _prune_backups(self, folder, keep):
        try:
            mine = sorted((entry for entry in folder.iterdir() if entry.is_file() and (m := _BACKUP_NAME.match(entry.name)) and m["stem"] == self.path.stem),
                          key=lambda entry: entry.name, reverse=True)
        except OSError:
            return
        for old in mine[max(keep, 1):]:
            try:
                old.unlink()
            except OSError:
                pass                                       # 못 지워도 백업 자체는 성공이다

    def restore_from(self, backup, *, safety_folder=None):
        """백업 파일의 내용으로 지금 저장소를 바꾼다. 백업이 이 프로그램의 것이 아니거나 깨졌거나 더 새로우면 아무것도 바꾸지 않고 AppError.
        `safety_folder` 를 주면 바꾸기 직전 상태를 거기에 먼저 백업한다(실수로 복구했을 때 되돌릴 수 있게)."""
        self._refuse_if_read_only()
        backup = Path(os.fspath(backup))
        with self._lock:
            try:
                source = sqlite3.connect(_read_only_uri(backup), uri=True)
            except sqlite3.Error as error:
                raise store_error(error, backup) from None
            with closing(source):
                try:
                    application = source.execute("PRAGMA application_id").fetchone()[0]
                    version = source.execute("PRAGMA user_version").fetchone()[0]
                    problem = source.execute("PRAGMA integrity_check").fetchone()[0]
                except sqlite3.Error as error:
                    raise store_error(error, backup) from None
                if application != APPLICATION_ID or problem != "ok":
                    raise AppError("STORE_CORRUPT", {"파일": backup.name}, detail="이 프로그램의 온전한 백업이 아니다")
                if version > SCHEMA_VERSION:
                    raise AppError("STORE_VERSION_UNSUPPORTED", {"파일": backup.name}, detail=f"백업 버전 {version} > 지원 {SCHEMA_VERSION}")
                try:
                    shape = _shape_problem(source, version) if version >= MIN_SCHEMA_VERSION else f"백업 버전 {version} 은 이 프로그램이 만든 적이 없다"
                except sqlite3.Error as error:
                    raise store_error(error, backup) from None
                if shape:                                # 바꾸기 전에 거절한다 — 바꾼 뒤 열기 검사에서 걸리면 이미 지금 저장소가 그 백업으로 덮인 뒤다
                    raise AppError("STORE_CORRUPT", {"파일": backup.name}, detail=f"이 프로그램의 온전한 백업이 아니다: {shape}")
                if safety_folder is not None:
                    self.backup(safety_folder)
                try:
                    source.backup(self._db)
                except sqlite3.Error as error:
                    raise store_error(error, self.path) from None
            self._prepare(fresh=False)                     # 옛 구조의 백업이면 지금 구조로 올린다
