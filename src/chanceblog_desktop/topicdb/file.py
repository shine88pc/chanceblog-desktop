"""한 SQLite 파일을 안전하게 여는 기계 장치 — `content/store.py` 의 `Store` 와 **같은 규칙**을 이 파일(`topic_engine.db`)에 따로 적용한다(P3, D-61). 표와 읽고 쓰기는 `store.py` 가 하고 여기는 여는 일만 한다.

지키는 것(데이터를 잃지 않는 것이 첫째):
  ① 쓰는 일은 모두 하나의 트랜잭션이다 — 중간에 실패하거나 전원이 나가도 '저장 전' 아니면 '저장 후'다.
  ② 열 때 이 프로그램의 주제 엔진 파일인지(`application_id` — 기존 보관함 `chanceblog.db` 의 이름표와 다르다)·더 새로운 버전이 만든 것은 아닌지(`user_version`)·깨지지 않았는지(`quick_check`)·표와 열이 맞는지 확인하고,
     아니면 **파일에 아무것도 쓰지 않고** 오류 코드로 멈춘다(낯선 파일·더 새로운 파일·깨진 파일을 덮어쓰지 않는다 — 한 바이트도 바뀌지 않는다).
  ③ 구조를 올릴 때(마이그레이션)는 쓰기 잠금을 잡은 **뒤** 판 번호를 **다시 읽고**(그 사이 다른 창이 이미 올렸으면 아무것도 안 한다) 사본(`.v<번호>.bak`)을 둔 뒤 한 트랜잭션으로 올리며, 실패하면 되돌려 원래 파일 그대로다.
     이미 있는 사본은 덮어쓰지 않는다(같은 것이면 쓰고, 다르면 다음 이름). 여러 창이 동시에 열어도 한 곳만 올린다.
  ④ 읽기 전용 열기(`migrate=False`)는 파일을 만들지도 구조를 올리지도 않고 한 바이트도(수정 시각까지) 바꾸지 않으며 쓰는 일은 모두 거절한다.
SQLite 의 실패는 오류 코드로 옮긴다: 잠김 → TOPIC_STORE_LOCKED, 디스크 가득 → DISK_FULL, 못 열거나 못 씀 → FILE_WRITE_FAILED, 깨짐·낯선 파일 → TOPIC_STORE_CORRUPT, 더 새로운 판 → TOPIC_STORE_VERSION_UNSUPPORTED.
이 파일의 판·이름표·표 모양은 서브클래스가 정한다(`APPLICATION_ID`·`SCHEMA_VERSION`·`SCHEMA`·`SHAPES`·`INDEXES`·`MIGRATIONS`) — 시험은 이 값들을 바꾼 서브클래스로 '판 2 로 올리기' 를 흉내 낸다. 비밀(키·자격 증명)은 이 파일에 두지 않는다.
"""
from __future__ import annotations

import errno
import itertools
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from ..content.store import _read_only_uri
from ..errors import AppError

BUSY_SECONDS = 5.0                                       # 잠겨 있을 때 기다리는 시간 — 윈도에서는 타이머 간격 때문에 실제로 약 7초까지 걸릴 수 있다(D-73)
_SQLITE_BUSY, _SQLITE_LOCKED = 5, 6                      # backup 진행 콜백이 받는 상태(파이썬 3.10 에는 이름이 없어 숫자로 둔다)
COPY_SECONDS = 30.0                                      # 올리기 전 사본을 만드는 데 줄 수 있는 시간
MAX_COPY_NAMES = 20                                      # 사본 이름(.v1.bak → .v1.2.bak …)을 이만큼까지 찾아본다
_COPY_PATH_LIMIT = 259 if os.name == "nt" else None      # Windows 의 경로 길이 한계 — 사본 이름이 이를 넘기 전에 알린다
_ERROR_RULES = (
    (("database is locked", "database table is locked", "database schema is locked"), "TOPIC_STORE_LOCKED"),
    (("disk is full", "database or disk is full"), "DISK_FULL"),
    (("malformed", "not a database", "file is encrypted", "corrupt", "no such table", "no such column"), "TOPIC_STORE_CORRUPT"),
    (("unable to open", "readonly", "read-only", "disk i/o error", "cannot open", "permission denied", "access is denied", "no such file or directory"), "FILE_WRITE_FAILED"),
)


def detail_of(error):
    return " ".join(str(error).split())[:200]


def store_error(error, path=""):
    """sqlite3 의 예외 → AppError. 이미 AppError 면 그대로."""
    if isinstance(error, AppError):
        return error
    text = str(error).lower()
    for needles, code in _ERROR_RULES:
        if any(needle in text for needle in needles):
            if code == "TOPIC_STORE_CORRUPT":
                return AppError(code, {"파일": Path(str(path)).name}, detail=detail_of(error))
            return AppError(code, {"경로": str(path)} if code == "FILE_WRITE_FAILED" else None, detail=detail_of(error))
    return AppError("UNEXPECTED_ERROR", detail=f"{type(error).__name__}: {detail_of(error)}")


def _blocked_reason(code, text):
    lowered = text.lower()
    if code == "DISK_FULL":
        return "저장 공간이 부족합니다"
    if "readonly" in lowered or "read-only" in lowered:
        return "데이터 파일이 읽기 전용입니다"
    if "i/o" in lowered:
        return "디스크 읽기·쓰기 오류가 났습니다(디스크나 외장 저장장치 연결을 확인하세요)"
    return "데이터 파일이나 그 폴더에 쓸 수 없습니다(쓸 권한이 없거나 경로가 너무 깁니다)"


def _os_blocked_reason(error):
    winerror = getattr(error, "winerror", None)
    if error.errno == errno.ENOSPC or winerror == 112:
        return "저장 공간이 부족합니다"
    if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS) or isinstance(error, PermissionError):
        return "데이터 파일이 있는 폴더에 쓸 수 없습니다(읽기 전용이거나 권한이 없습니다)"
    if error.errno == errno.ENAMETOOLONG or winerror == 206:
        return "데이터 파일의 경로가 너무 길어 사본을 만들 수 없습니다"
    return None


class EngineFile:
    """한 SQLite 파일을 여는 저장소의 바탕. `with TopicStore.open(경로) as store:` 로 쓴다(밖으로 나가면 닫는다). 여러 스레드가 함께 써도 한 번에 하나씩 실행한다."""

    APPLICATION_ID = 0
    SCHEMA_VERSION = 1
    MIN_SCHEMA_VERSION = 1
    SCHEMA = ()                                          # 새 파일을 만들 때 실행할 문장들(가장 새 모양)
    SHAPES = {}                                          # {판: {표: (열, …)}} — 판마다 있어야 하는 표와 열(앞 판의 표는 뒤 판에도 있다)
    INDEXES = {}                                         # {판: {색인: (표, (열, …))}} — 그 판에 처음 생긴 색인(뒤 판에도 있다)
    MIGRATIONS = {}                                      # {지금 판: 다음 판으로 바꾸는 함수(연결)} — 한 번에 한 단계씩, 모두 한 트랜잭션 안에서 돈다
    KIND = "주제 엔진 보관함"                              # 오류 문구에 쓸 이름

    def __init__(self, path, connection, *, busy_seconds=BUSY_SECONDS, read_only=False):
        self.path = Path(path)
        self._db = connection
        self._busy = busy_seconds
        self._read_only = read_only
        self._version = self.SCHEMA_VERSION                # 열 때 파일의 실제 구조 판으로 다시 적힌다
        self._lock = threading.RLock()

    # ---- 열기·닫기 ---------------------------------------------------------------------------------------------------------
    @classmethod
    def open(cls, path, *, busy_seconds=BUSY_SECONDS, migrate=True):
        """파일이 없으면 만들고(폴더도), 있으면 이 프로그램의 주제 엔진 파일인지 검사한다. 걸리면 파일을 건드리지 않고 AppError.
        `migrate=False` 는 **읽기 전용 열기**다 — 파일을 만들지도 구조를 올리지도 않고 한 바이트도 바꾸지 않으며 옛 판의 파일은 `needs_migration` 으로 알려 줄 뿐이다."""
        path = Path(os.fspath(path))
        if not migrate:
            return cls._open_read_only(path, busy_seconds)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not path.exists() or path.stat().st_size == 0
        except OSError as error:
            raise AppError("FILE_WRITE_FAILED", {"경로": str(path.parent)}, detail=detail_of(error)) from None
        try:
            connection = sqlite3.connect(str(path), timeout=busy_seconds, isolation_level=None, check_same_thread=False)
        except sqlite3.Error as error:
            raise store_error(error, path) from None
        opened = cls(path, connection, busy_seconds=busy_seconds)
        try:
            opened._prepare(fresh)
        except BaseException:
            connection.close()
            raise
        return opened

    @classmethod
    def _open_read_only(cls, path, busy_seconds):
        try:
            missing = not path.exists() or (path.is_file() and path.stat().st_size == 0)
            uri = _read_only_uri(path)
        except (OSError, ValueError) as error:
            raise AppError("FILE_WRITE_FAILED", {"경로": str(path)}, detail=detail_of(error)) from None
        if missing:
            raise AppError("CONTENT_NOT_FOUND", {"항목": cls.KIND}, detail="읽기 전용으로 열 파일이 없거나 비어 있다(읽기 전용 열기는 파일을 만들지 않는다)")
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=busy_seconds, isolation_level=None, check_same_thread=False)
        except sqlite3.Error as error:
            raise store_error(error, path) from None
        opened = cls(path, connection, busy_seconds=busy_seconds, read_only=True)
        try:
            opened._prepare_read_only()
        except BaseException:
            connection.close()
            raise
        return opened

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
                raise AppError("TOPIC_STORE_RECOVERY_PENDING", {"파일": self.path.name}, detail=mapped.detail) from None
            raise mapped from None

    def _has_unfinished_save(self):
        """앱이 쓰다가 갑자기 꺼지면서 남긴 저널(`<파일>-journal`)이 있는가 — 읽기 전용 연결은 그것을 정리하지 못한다(일반 열기는 읽으면서 정리한다)."""
        try:
            return os.path.getsize(str(self.path) + "-journal") > 0
        except OSError:
            return False

    def _read_version(self):
        return self._db.execute("PRAGMA user_version").fetchone()[0]

    @property
    def schema_version(self):
        """열린 파일의 구조 판 번호(보통 열면서 올리므로 지금 프로그램의 판, 읽기 전용으로 연 옛 파일은 그 파일의 판)."""
        return self._version

    @property
    def needs_migration(self):
        return self._version < self.SCHEMA_VERSION

    @property
    def read_only(self):
        return self._read_only

    def _create(self):
        """처음 만들 때. 쓰기 잠금을 잡은 뒤에도 파일이 비어 있을 때만 만든다 — 기다리는 사이 다른 프로세스가 먼저 만들었으면 만들지 않고 False(부른 쪽이 검사·올리기로 이어 간다)."""
        self._begin()
        if self._db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]:
            self._rollback()
            return False
        for statement in self.SCHEMA:
            self._db.execute(statement)
        self._db.execute(f"PRAGMA application_id = {int(self.APPLICATION_ID)}")
        self._db.execute(f"PRAGMA user_version = {int(self.SCHEMA_VERSION)}")
        self._db.execute("COMMIT")
        return True

    def _shape_problem(self, connection, version, *, indexes=False):
        """그 판의 파일이어야 하는 표·열(`indexes=True` 면 색인도)이 맞는지 — 어긋난 첫 곳을 설명하는 글, 맞으면 None. 모르는 판은 보지 않는다."""
        expected = self.SHAPES.get(version)
        if expected is None:
            return None
        for table, columns in expected.items():
            found = tuple(row[0] for row in connection.execute("SELECT name FROM pragma_table_info(?) ORDER BY cid", (table,)))
            if found != columns:
                return f"표 {table} 이 없다" if not found else f"표 {table} 의 열이 다르다: {', '.join(found)}"
        if indexes:
            for number in sorted(self.INDEXES):
                if number > version:
                    continue
                for index, (table, columns) in self.INDEXES[number].items():
                    owner = connection.execute("SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?", (index,)).fetchone()
                    found = tuple(row[0] for row in connection.execute("SELECT name FROM pragma_index_info(?) ORDER BY seqno", (index,)))
                    if owner is None or owner[0] != table or found != columns:
                        return f"색인 {index} 이 없거나 다르다"
        return None

    def _verify(self):
        application = self._db.execute("PRAGMA application_id").fetchone()[0]
        version = self._read_version()
        if application != self.APPLICATION_ID:
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail="이 프로그램의 주제 엔진 파일이 아니다")
        if version > self.SCHEMA_VERSION:
            raise AppError("TOPIC_STORE_VERSION_UNSUPPORTED", {"파일": self.path.name}, detail=f"파일 버전 {version} > 지원 {self.SCHEMA_VERSION}")
        if version < self.MIN_SCHEMA_VERSION:
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=f"파일 버전 {version} 은 이 프로그램이 만든 적이 없다")
        result = self._db.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=detail_of(result))
        problem = self._shape_problem(self._db, version)
        if problem:
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=problem)

    def _migrate(self):
        """구조를 지금 판으로 올린다 — 한 트랜잭션이고 실패하면 파일은 올리기 전 그대로다. 순서: ① 쓰기 잠금을 먼저 잡고 ② 잠금을 쥔 채 판 번호를 **다시 읽어** 기다리는 사이 다른 프로세스가 이미 올렸으면 아무것도 하지 않고 끝낸다
        ③ 사본을 두고 ④ 단계를 하나씩 실행하고 ⑤ 같은 트랜잭션 안에서 판 번호를 올린 뒤 COMMIT. 사본은 잠금 안에서 만든다."""
        if self._read_version() >= self.SCHEMA_VERSION:
            return
        if not os.access(self.path, os.W_OK):                # 읽기 전용 파일은 쓰기 잠금이 잡혀도 첫 쓰기에서야 실패한다 — 사본 같은 것을 만들기 전에 알린다
            raise AppError("MIGRATION_BLOCKED", {"이유": "데이터 파일이 읽기 전용입니다"}, detail="쓸 수 없는 파일이라 올리지 않았다")
        self._check_copy_path()
        try:
            self._begin()
            version = self._read_version()
            if version >= self.SCHEMA_VERSION:
                self._rollback()                            # 기다리는 사이 다른 프로세스가 올렸다 — 바꾼 것이 없으니 되돌리기와 같다
                return
            missing = next((number for number in range(version, self.SCHEMA_VERSION) if number not in self.MIGRATIONS), None)
            if missing is not None:
                raise RuntimeError(f"버전 {missing} 에서 올리는 단계가 없다")
            self._keep_copy(version)
            while version < self.SCHEMA_VERSION:
                self.MIGRATIONS[version](self._db)
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
        if isinstance(error, sqlite3.Error):
            mapped = store_error(error, self.path)
            if mapped.code in ("TOPIC_STORE_LOCKED", "TOPIC_STORE_CORRUPT"):
                return mapped
            if mapped.code in ("DISK_FULL", "FILE_WRITE_FAILED"):
                return AppError("MIGRATION_BLOCKED", {"이유": _blocked_reason(mapped.code, str(error))}, detail=mapped.detail)
        elif isinstance(error, OSError):
            reason = _os_blocked_reason(error)
            if reason:
                return AppError("MIGRATION_BLOCKED", {"이유": reason}, detail=f"{type(error).__name__}: {detail_of(error)}")
        return AppError("MIGRATION_FAILED", detail=f"{type(error).__name__}: {detail_of(error)}")

    def _check_copy_path(self):
        if _COPY_PATH_LIMIT is not None and len(os.path.abspath(self.path)) + len(f".v{self._read_version()}.bak.tmp") > _COPY_PATH_LIMIT:
            raise AppError("MIGRATION_BLOCKED", {"이유": "데이터 파일의 경로가 너무 길어 사본을 만들 수 없습니다(더 짧은 폴더로 옮겨 주세요)"}, detail=f"사본 경로가 {_COPY_PATH_LIMIT}자를 넘는다")

    def _copy_name(self, version, number):
        return self.path.with_name(f"{self.path.name}.v{version}.bak" if number == 1 else f"{self.path.name}.v{version}.{number}.bak")

    def _keep_copy(self, version):
        """지금 파일(판 `version`)과 똑같은 사본이 파일로 있게 한다 — 이미 있는 사본은 **덮어쓰지 않는다**: 똑같은 것이면 그것을 쓰고, 다르거나 읽을 수 없으면 건드리지 않고 다음 이름으로 새로 만든다.
        쓰기 잠금을 쥐고 있을 때만 부른다(그래야 사본과 파일이 같은 내용이다)."""
        for number in range(1, MAX_COPY_NAMES + 1):
            target = self._copy_name(version, number)
            if not os.path.lexists(target):
                self._make_copy(target, version)
                return target
            if self._same_content(target, version):
                return target
        raise AppError("MIGRATION_BLOCKED", {"이유": f"사본 이름({self._copy_name(version, 1).name} 등 {MAX_COPY_NAMES}개)이 모두 쓰이고 있습니다(오래된 사본을 정리해 주세요)"}, detail="사본 이름이 모두 쓰이고 있다")

    def _make_copy(self, target, version):
        """임시 이름으로 사본을 만들고 점검한 뒤 이름을 바꿔 둔다 — 도중에 죽거나 실패해도 `target` 자리에는 반쯤 쓴 파일이 보이지 않는다."""
        temp = target.with_name(target.name + ".tmp")
        self._discard(temp)
        try:
            self._snapshot(temp)
            with closing(sqlite3.connect(_read_only_uri(temp), uri=True, timeout=self._busy)) as copy:
                found = (copy.execute("PRAGMA application_id").fetchone()[0], copy.execute("PRAGMA user_version").fetchone()[0], copy.execute("PRAGMA quick_check").fetchone()[0])
            if found != (self.APPLICATION_ID, version, "ok"):
                raise RuntimeError(f"만든 사본이 올바르지 않다(이름표·판 번호·점검: {found})")
            os.rename(temp, target)                          # Windows 는 이미 있으면 실패한다(덮어쓰지 않는다)
        except BaseException:
            self._discard(temp)
            raise

    def _snapshot(self, destination):
        """지금 파일의 일관된 사본을 `destination` 에 만든다. **다른 연결**(읽기 전용)으로 읽는다 — 이 연결은 쓰기 잠금을 쥐고 있어 같은 연결로 backup 하면 영원히 기다린다.
        시간 상한(`COPY_SECONDS`)이 있어 **계속 잠겨 있으면** 멈추고 알린다."""
        stuck_since = []

        def watch(status, remaining, total):
            if status not in (_SQLITE_BUSY, _SQLITE_LOCKED):
                stuck_since.clear()
                return
            if not stuck_since:
                stuck_since.append(time.monotonic())
            if time.monotonic() - stuck_since[0] > COPY_SECONDS:
                raise AppError("TOPIC_STORE_LOCKED", detail=f"사본을 만드는 동안 {COPY_SECONDS:g}초가 넘도록 파일이 계속 잠겨 있다")

        with closing(sqlite3.connect(_read_only_uri(self.path), uri=True, timeout=self._busy)) as source, closing(sqlite3.connect(str(destination))) as target:
            source.backup(target, progress=watch)

    def _same_content(self, existing, version):
        """이미 있는 사본이 지금 파일(판 `version`)과 이름표·판 번호·모든 표와 행까지 똑같은가. 파일이 아니거나 읽을 수 없으면 믿지 않는다."""
        try:
            if not existing.is_file():
                return False
            with closing(sqlite3.connect(_read_only_uri(existing), uri=True, timeout=self._busy)) as old:
                if (old.execute("PRAGMA application_id").fetchone()[0], old.execute("PRAGMA user_version").fetchone()[0]) != (self.APPLICATION_ID, version):
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
                continue                                     # 없거나 못 지워도 사본 만들기 자체의 성공·실패와 무관하다 — 다음 시도가 다시 치운다

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- 트랜잭션 ----------------------------------------------------------------------------------------------------------
    def _begin(self):
        self._db.execute("BEGIN IMMEDIATE")

    def _rollback(self):
        """되돌린다. 되돌릴 것이 없거나(시작도 못 했거나 이미 끝난 트랜잭션) 되돌리다 난 오류는 **원래 오류를 가리지 않도록** 글로 돌려주기만 한다(부른 쪽은 원래 오류를 다시 낸다)."""
        try:
            self._db.execute("ROLLBACK")
        except sqlite3.Error as error:
            return detail_of(error)
        return ""

    def _refuse_if_read_only(self):
        """읽기 전용으로 연 저장소는 쓰는 일을 모두 거절한다 — 부르는 쪽의 실수이므로 사용자 안내가 아니라 '예상 밖 오류' 로 낸다."""
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

    def restore_from(self, backup):
        """백업 파일의 내용으로 지금 저장소를 바꾼다(SQLite 백업 방식 — 한 트랜잭션이라 도중에 실패하면 지금 저장소는 그대로다). 백업이 이 프로그램의 주제 엔진 파일이 아니거나 깨졌거나 더 새롭거나 표 모양이 다르면
        **아무것도 바꾸지 않고** TOPIC_BACKUP_INVALID. 옛 판의 백업이면 바꾼 뒤 지금 판으로 올린다."""
        self._refuse_if_read_only()
        backup = Path(os.fspath(backup))
        name = backup.name
        with self._lock:
            try:
                source = sqlite3.connect(_read_only_uri(backup), uri=True)
            except (sqlite3.Error, OSError, ValueError) as error:
                raise AppError("TOPIC_BACKUP_INVALID", {"파일": name, "이유": "백업 파일을 열 수 없습니다"}, detail=detail_of(error)) from None
            with closing(source):
                try:
                    application = source.execute("PRAGMA application_id").fetchone()[0]
                    version = source.execute("PRAGMA user_version").fetchone()[0]
                    problem = source.execute("PRAGMA integrity_check").fetchone()[0]
                    shape = self._shape_problem(source, version) if self.MIN_SCHEMA_VERSION <= version <= self.SCHEMA_VERSION else None
                except sqlite3.Error as error:
                    raise AppError("TOPIC_BACKUP_INVALID", {"파일": name, "이유": "백업 파일이 깨졌습니다"}, detail=detail_of(error)) from None
                if application != self.APPLICATION_ID or problem != "ok":
                    raise AppError("TOPIC_BACKUP_INVALID", {"파일": name, "이유": "이 프로그램의 온전한 주제 엔진 백업이 아닙니다"}, detail="이름표가 다르거나 점검에 실패했다")
                if version > self.SCHEMA_VERSION or version < self.MIN_SCHEMA_VERSION:
                    raise AppError("TOPIC_BACKUP_INVALID", {"파일": name, "이유": "지원하지 않는 버전의 백업입니다"}, detail=f"백업 버전 {version} / 지원 {self.MIN_SCHEMA_VERSION}~{self.SCHEMA_VERSION}")
                if shape:                                     # 바꾸기 전에 거절한다 — 바꾼 뒤 열기 검사에서 걸리면 이미 지금 저장소가 그 백업으로 덮인 뒤다
                    raise AppError("TOPIC_BACKUP_INVALID", {"파일": name, "이유": "표 모양이 맞지 않습니다"}, detail=shape)
                try:
                    source.backup(self._db)
                except sqlite3.Error as error:
                    raise store_error(error, self.path) from None
            self._prepare(fresh=False)                         # 옛 구조의 백업이면 지금 구조로 올린다

    def copy_to(self, destination):
        """SQLite 백업 기능으로 지금 내용을 다른 파일로 복사한다(열려 있어도 일관된 사본 — 읽기 전용으로 연 저장소도 된다)."""
        with self._lock, closing(sqlite3.connect(str(destination))) as target:
            try:
                self._db.backup(target)
            except sqlite3.Error as error:
                raise store_error(error, destination) from None


__all__ = ["BUSY_SECONDS", "COPY_SECONDS", "EngineFile", "MAX_COPY_NAMES", "detail_of", "store_error"]
