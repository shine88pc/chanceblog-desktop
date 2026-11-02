"""판 1(주제 후보 표가 생기기 전)의 글 데이터 파일을 SQL 로 직접 만드는 시험 도우미(시험 파일이 아니다).

지금 코드의 `Store` 를 거치지 않고 표·인덱스·`application_id`·`user_version` 을 옛 프로그램이 만든 것과 같게 적어 둔다 —
스키마 판이 올라가도 '옛 파일' 시험이 진짜 옛 파일로 돌게 하려는 것이다. 이 표는 판 1 의 것이라 앞으로도 고치지 않는다.
"""
import json
import sqlite3
from contextlib import closing

APPLICATION_ID = 0x43424450
V1_SCHEMA = (
    "CREATE TABLE projects ("
    " project_id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL)",
    "CREATE INDEX projects_updated ON projects (updated_at DESC)",
    "CREATE TABLE revisions ("
    " project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE, revision INTEGER NOT NULL, saved_at TEXT NOT NULL, data TEXT NOT NULL,"
    " PRIMARY KEY (project_id, revision))",
    "CREATE TABLE drafts (project_id TEXT PRIMARY KEY, text TEXT NOT NULL, saved_at TEXT NOT NULL)",
)


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def make_v1_file(path, projects=(), drafts=()):
    """`projects`(ContentProject 들)와 `drafts`((프로젝트 번호, 글, 시각) 들)가 든 판 1 파일을 만든다."""
    with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
        db.execute("BEGIN")
        for statement in V1_SCHEMA:
            db.execute(statement)
        for project in projects:
            db.execute("INSERT INTO projects (project_id, title, revision, created_at, updated_at, data) VALUES (?, ?, ?, ?, ?, ?)",
                       (project.project_id, project.title, project.revision, project.created_at, project.updated_at, dump(project.to_dict())))
            snapshot = dump({"title": project.title, "source_content": project.source_content, "references": list(project.references),
                             "assets": [asset.to_dict() for asset in project.assets]})
            db.execute("INSERT INTO revisions (project_id, revision, saved_at, data) VALUES (?, ?, ?, ?)", (project.project_id, project.revision, project.updated_at, snapshot))
        for project_id, text, saved_at in drafts:
            db.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES (?, ?, ?)", (project_id, text, saved_at))
        db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        db.execute("PRAGMA user_version = 1")
        db.execute("COMMIT")
