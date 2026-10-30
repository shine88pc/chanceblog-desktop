"""콘텐츠 저장소(SQLite) — 원고 프로젝트를 한 파일에 안전하게 저장·불러오기·판 기록·자동 저장 초안·백업·복구(docs/ARCHITECTURE.md §5 `content/`).

지키는 것(데이터를 잃지 않는 것이 첫째):
  ① 쓰는 일은 모두 하나의 트랜잭션이다 — 중간에 실패하거나 전원이 나가도 '저장 전' 아니면 '저장 후'다.
  ② 열 때 이 프로그램의 데이터 파일인지(`application_id`)·더 새로운 버전이 만든 것은 아닌지(`user_version`)·깨지지 않았는지(`quick_check`)
     확인하고, 아니면 **파일에 아무것도 쓰지 않고** 오류 코드로 멈춘다(깨진 파일을 덮어쓰지 않는다).
  ③ 저장된 판(revision)보다 낮은 판으로는 덮어쓰지 않는다(`STORE_CONFLICT`) — 오래된 화면이 새 원고를 지우지 못하게.
  ④ 구조를 바꿀 때(마이그레이션)는 바꾸기 전에 사본(`.v<번호>.bak`)을 두고, 실패하면 되돌려 원래 파일 그대로다(`MIGRATION_FAILED`).
  ⑤ 읽을 때는 `ContentProject.from_dict` 의 엄격한 검사를 다시 거친다 — 파일을 사람이 고쳤거나 깨졌으면 `STORE_CORRUPT`.
  ⑥ 모든 SQL 은 값을 매개변수로 넘긴다(글이 SQL 로 해석될 수 없다). 프로젝트 번호는 `[A-Za-z0-9_-]{1,64}` 만 받는다.
  ⑦ 화면과 작업 줄(스레드)이 같은 저장소를 함께 써도 한 번에 하나씩만 실행한다(자동 저장·백업이 겹쳐도 안전).

SQLite 의 실패는 오류 코드로 옮긴다: 잠김 → STORE_LOCKED, 디스크 가득 → DISK_FULL, 못 열거나 못 씀 → FILE_WRITE_FAILED, 깨짐 → STORE_CORRUPT.
비밀번호·토큰은 이 파일에 두지 않는다(원고와 발행 상태뿐이다).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..errors import AppError
from .model import Asset, ContentProject, utc_now

APPLICATION_ID = 0x43424450          # 'CBDP' — 이 프로그램의 데이터 파일 표시
SCHEMA_VERSION = 1
KEEP_REVISIONS = 50                  # 프로젝트마다 남기는 판 기록 수(가장 새 판은 늘 남긴다)
KEEP_BACKUPS = 10
MAX_DRAFT_CHARS = 2_000_000
BUSY_SECONDS = 5.0
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BACKUP_NAME = re.compile(r"^(?P<stem>.+)-(?P<stamp>\d{8}-\d{6})\.db$")

_SCHEMA = (
    "CREATE TABLE projects ("
    " project_id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL)",
    "CREATE INDEX projects_updated ON projects (updated_at DESC)",
    "CREATE TABLE revisions ("
    " project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE, revision INTEGER NOT NULL, saved_at TEXT NOT NULL, data TEXT NOT NULL,"
    " PRIMARY KEY (project_id, revision))",
    "CREATE TABLE drafts (project_id TEXT PRIMARY KEY, text TEXT NOT NULL, saved_at TEXT NOT NULL)",
)

# 구조를 바꾸는 단계: {지금 버전: 다음 버전으로 바꾸는 함수(연결)}. 한 번에 한 단계씩, 모두 한 트랜잭션 안에서 돈다.
MIGRATIONS = {}

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


def _check_id(project_id):
    if not isinstance(project_id, str) or not _ID.match(project_id):
        raise AppError("CONTENT_INVALID", {"항목": "프로젝트 번호"})
    return project_id


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Store:
    """한 SQLite 파일을 여는 저장소. `with Store.open(경로) as store:` 로 쓴다(밖으로 나가면 닫는다). 여러 스레드가 함께 써도 된다."""

    def __init__(self, path, connection, keep_revisions):
        self.path = Path(path)
        self._db = connection
        self._keep = max(int(keep_revisions), 1)
        self._lock = threading.RLock()

    # ---- 열기·닫기 -------------------------------------------------------------------------------------------------------
    @classmethod
    def open(cls, path, *, keep_revisions=KEEP_REVISIONS, busy_seconds=BUSY_SECONDS):
        """파일이 없으면 만들고(폴더도), 있으면 이 프로그램의 데이터 파일인지 검사한다. 검사에 걸리면 파일을 건드리지 않고 AppError."""
        path = Path(os.fspath(path))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not path.exists() or path.stat().st_size == 0
        except OSError as error:
            raise AppError("FILE_WRITE_FAILED", {"경로": str(path.parent)}, detail=_detail(error)) from None
        try:
            connection = sqlite3.connect(str(path), timeout=busy_seconds, isolation_level=None, check_same_thread=False)
        except sqlite3.Error as error:
            raise store_error(error, path) from None
        store = cls(path, connection, keep_revisions)
        try:
            store._prepare(fresh)
        except BaseException:
            connection.close()
            raise
        return store

    def _prepare(self, fresh):
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA secure_delete = ON")
            if fresh:
                self._create()
            else:
                self._verify()
                self._migrate()
        except sqlite3.Error as error:
            raise store_error(error, self.path) from None

    def _create(self):
        """처음 만들 때(`open` 이 실패하면 연결을 닫아 트랜잭션이 되돌려지므로 따로 되돌리지 않는다)."""
        self._begin()
        for statement in _SCHEMA:
            self._db.execute(statement)
        self._db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.execute("COMMIT")

    def _verify(self):
        application = self._db.execute("PRAGMA application_id").fetchone()[0]
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if application != APPLICATION_ID:
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail="이 프로그램의 데이터 파일이 아니다")
        if version > SCHEMA_VERSION:
            raise AppError("STORE_VERSION_UNSUPPORTED", {"파일": self.path.name}, detail=f"파일 버전 {version} > 지원 {SCHEMA_VERSION}")
        result = self._db.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise AppError("STORE_CORRUPT", {"파일": self.path.name}, detail=_detail(result))

    def _migrate(self):
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        try:
            self._copy_to(self.path.with_name(f"{self.path.name}.v{version}.bak"))
            self._begin()
            while version < SCHEMA_VERSION:
                step = MIGRATIONS.get(version)
                if step is None:
                    raise RuntimeError(f"버전 {version} 에서 올리는 단계가 없다")
                step(self._db)
                version += 1
            self._db.execute(f"PRAGMA user_version = {version}")
            self._db.execute("COMMIT")
        except Exception as error:
            self._rollback()
            raise AppError("MIGRATION_FAILED", detail=f"{type(error).__name__}: {_detail(error)}") from None

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

    def _write(self, work):
        """work(연결) 을 한 트랜잭션으로 실행하고 결과를 돌려준다. 실패하면 되돌리고 AppError."""
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
            raise AppError("CONTENT_NOT_FOUND", {"항목": project_id})
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
                raise AppError("CONTENT_NOT_FOUND", {"항목": project_id})
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
            raise AppError("CONTENT_NOT_FOUND", {"항목": f"{project_id} 의 {revision}판"})
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

    # ---- 점검·백업·복구 ----------------------------------------------------------------------------------------------------
    def check(self):
        """전체 점검 — 문제 문장 목록(비어 있으면 이상 없음). 파일 구조(integrity_check)와 각 프로젝트의 자료가 올바른지·열과 자료가 같은지 본다."""
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
        backup = Path(os.fspath(backup))
        with self._lock:
            try:
                source = sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True)
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
                if safety_folder is not None:
                    self.backup(safety_folder)
                try:
                    source.backup(self._db)
                except sqlite3.Error as error:
                    raise store_error(error, self.path) from None
            self._prepare(fresh=False)                     # 옛 구조의 백업이면 지금 구조로 올린다
