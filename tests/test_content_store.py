"""콘텐츠 저장소(SQLite) 시험 — 저장·불러오기가 글자 하나 안 틀리고, 깨진 파일·낯선 파일·더 새로운 파일은 건드리지 않고 거절하며, 쓰는 일은 모두 전부 아니면 전무다.

지키는 것:
  1) 저장한 프로젝트가 그대로 돌아오고(모든 칸), 같은 판을 다시 저장하면 바뀐 것만 갱신되고, 낮은 판으로는 덮어쓰지 못한다.
  2) 열 때 이 프로그램의 파일인지·더 새로운 버전은 아닌지·깨지지 않았는지 검사하고, 아니면 **파일을 한 바이트도 바꾸지 않고** 오류 코드로 멈춘다.
  3) 판 기록은 새 판마다 하나씩 남고, 상한을 넘으면 오래된 것부터 지우되 가장 새 판은 남는다. 초안(자동 저장)은 프로젝트와 따로 보관된다.
  4) 구조 바꾸기(마이그레이션)는 사본을 두고, 실패하면 원래대로 남는다.
  5) 백업은 점검을 거친 사본이고 오래된 것은 정리되며, 복구는 깨진·낯선·더 새로운 백업이면 아무것도 바꾸지 않는다.
  6) 잠겨 있으면 멈춰 있지 않고 STORE_LOCKED 로 알리며, 여러 스레드가 함께 써도 안전하다.
  7) 사람이 고치거나 깨진 행은 믿지 않고 STORE_CORRUPT 로 알린다. SQL 처럼 보이는 글도 그냥 글이다.
네트워크 없이 임시 폴더에서 돈다.
"""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import Asset, ContentProject  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content import store as store_module  # noqa: E402
from chanceblog_desktop.content.store import APPLICATION_ID, BUSY_SECONDS, KEEP_BACKUPS, KEEP_REVISIONS, MAX_DRAFT_CHARS, SCHEMA_VERSION, Store, store_error  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.errors.render import UNKNOWN_SLOT  # noqa: E402

NOW = "2026-10-30T03:00:00Z"
T2 = "2026-10-30T04:00:00Z"
T3 = "2026-10-30T05:00:00Z"


def make(project_id="p1", title="주제가 분명한 제목", body="본문 첫 문단입니다.\n\n둘째 문단입니다.", now=NOW):
    return ContentProject.new(title, body, ["https://example.com/source"], [Asset("a.png", "설명", 1)], project_id=project_id, now=now)


def advance(project, platform="github_pages", last=st.COMMITTED):
    """정상 경로의 앞부분(렌더링 만듦 → 검토 → 승인 → 마지막 단계: Pages 는 commit, Blogger 는 초안 저장)."""
    project.set_rendered(platform, "렌더링된 글", now=NOW)
    for status in (st.REVIEW_REQUIRED, st.APPROVED, last):
        project.transition(platform, status, now=NOW)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def corrupt_a_middle_page(path):
    """파일 맨 앞(머리말)은 그대로 두고 가운데 한 쪽(page)을 쓰레기로 덮는다 — 열어 보기만 해서는 모르고 점검해야 드러나는 손상."""
    data = bytearray(Path(path).read_bytes())
    middle = (len(data) // 2 // 4096) * 4096
    data[middle:middle + 4096] = b"\xff" * 4096
    Path(path).write_bytes(bytes(data))


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)                    # 나중에 등록한 것(저장소 닫기)이 먼저 돈다
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "data" / "chanceblog.db"      # 폴더가 아직 없어도 만든다

    def open(self, path=None, **kwargs):
        store = Store.open(self.path if path is None else path, **kwargs)
        self.addCleanup(store.close)
        return store

    def refuses(self, code, callable_, *args, **kwargs):
        """AppError 의 코드를 확인하고, 사용자 문구의 자리표시자가 모두 채워지는지(알 수 없음 없이)도 본다."""
        with self.assertRaises(AppError) as caught:
            callable_(*args, **kwargs)
        error = caught.exception
        self.assertEqual(error.code, code, error.detail)
        shown = error.rendered()
        self.assertNotIn(UNKNOWN_SLOT, shown.message + shown.action, f"{code}: 자리표시자가 비었다")
        return error

    def raw(self, path=None):
        connection = sqlite3.connect(str(self.path if path is None else path), isolation_level=None)
        self.addCleanup(connection.close)
        return connection


class OpenTest(StoreCase):
    def test_a_new_file_is_created_with_its_folder_and_marked_as_ours(self):
        store = self.open()
        self.assertTrue(self.path.is_file())
        db = self.raw()
        self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0], APPLICATION_ID)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}, {"projects", "revisions", "drafts"})
        self.assertEqual(store._db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(store._db.execute("PRAGMA secure_delete").fetchone()[0], 1)
        self.assertIsNone(store._db.isolation_level, "트랜잭션은 우리가 직접 정한다(자동으로 열리지 않는다)")
        deep = self.dir / "x" / "y" / "z" / "deep.db"                       # 폴더가 여러 겹 없어도 만든다
        Store.open(deep).close()
        self.assertTrue(deep.is_file())

    def test_reopening_keeps_everything_and_writes_nothing(self):
        with Store.open(self.path) as store:
            store.save(make())
            store.save_draft("p1", "초안")
        before = digest(self.path)
        with Store.open(self.path) as store:
            self.assertEqual(store.load("p1").title, "주제가 분명한 제목")
            self.assertEqual([item.project_id for item in store.list()], ["p1"])
            self.assertEqual(store.load_draft("p1").text, "초안")
        self.assertEqual(digest(self.path), before, "그냥 열고 읽기만 했는데 파일이 바뀌었다")

    def test_an_existing_empty_file_is_treated_as_new(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"")
        store = self.open()
        store.save(make())
        self.assertEqual(store.load("p1").project_id, "p1")

    def test_a_folder_or_a_file_where_the_other_is_expected_is_refused_with_the_path(self):
        self.path.mkdir(parents=True)
        error = self.refuses("FILE_WRITE_FAILED", Store.open, self.path)
        self.assertIn(self.path.name, error.rendered().message)
        blocker = self.dir / "blocker"
        blocker.write_text("파일", encoding="utf-8")
        self.refuses("FILE_WRITE_FAILED", Store.open, blocker / "x.db")

    def test_a_file_that_is_not_a_database_is_refused_and_left_exactly_as_it_was(self):
        self.path.parent.mkdir(parents=True)
        for content in (b"not a database at all " * 30, "그냥 글입니다 ".encode("utf-8") * 40, b"\x00" * 10 + b"x"):
            with self.subTest(size=len(content)):
                self.path.write_bytes(content)
                error = self.refuses("STORE_CORRUPT", Store.open, self.path)
                self.assertIn(self.path.name, error.rendered().message)
                self.assertEqual(self.path.read_bytes(), content)

    def test_a_truncated_database_is_refused_and_left_alone(self):
        with Store.open(self.path) as store:
            store.save(make(body="가나다 " * 20000))
        data = self.path.read_bytes()
        self.assertGreater(len(data), 20000)
        self.path.write_bytes(data[:len(data) // 2])
        half = digest(self.path)
        self.refuses("STORE_CORRUPT", Store.open, self.path)
        self.assertEqual(digest(self.path), half)

    def test_a_database_with_a_damaged_page_is_refused_and_left_alone(self):
        with Store.open(self.path) as store:
            store.save(make(body="가나다 " * 30000))
        corrupt_a_middle_page(self.path)
        before = digest(self.path)
        self.refuses("STORE_CORRUPT", Store.open, self.path)
        self.assertEqual(digest(self.path), before)

    def test_someone_elses_sqlite_database_is_not_taken_over(self):
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(str(self.path))) as other:
            other.execute("CREATE TABLE notes (id INTEGER, body TEXT)")
            other.execute("INSERT INTO notes VALUES (1, '남의 자료')")
            other.commit()
        before = digest(self.path)
        self.refuses("STORE_CORRUPT", Store.open, self.path)
        self.assertEqual(digest(self.path), before)

    def test_a_file_from_a_newer_version_is_refused_and_left_alone(self):
        Store.open(self.path).close()
        with closing(sqlite3.connect(str(self.path))) as db:
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        before = digest(self.path)
        error = self.refuses("STORE_VERSION_UNSUPPORTED", Store.open, self.path)
        self.assertIn(self.path.name, error.rendered().message)
        self.assertEqual(digest(self.path), before)

    def test_the_defaults_are_the_documented_ones(self):
        self.assertEqual((KEEP_REVISIONS, KEEP_BACKUPS, BUSY_SECONDS, SCHEMA_VERSION), (50, 10, 5.0, 1))
        real, calls = sqlite3.connect, []

        def spy(path, *args, **kwargs):
            calls.append(kwargs)
            return real(path, *args, **kwargs)

        with mock.patch.object(store_module.sqlite3, "connect", side_effect=spy):
            self.open()
            self.open(self.dir / "second.db", busy_seconds=0.3)
        self.assertEqual([call["timeout"] for call in calls], [5.0, 0.3])

    def test_a_failed_open_closes_the_connection(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"not a database at all " * 30)
        spy = mock.MagicMock(wraps=sqlite3.connect(str(self.path)))
        with mock.patch.object(store_module.sqlite3, "connect", return_value=spy):
            self.refuses("STORE_CORRUPT", Store.open, self.path)
        spy.close.assert_called_once_with()

    def test_leaving_the_with_block_closes_the_store(self):
        with Store.open(self.path) as store:
            store.list()
        error = self.refuses("UNEXPECTED_ERROR", store.list)
        self.assertIn("closed", error.detail.lower())

    def test_a_write_takes_the_write_lock_first_and_commits_once(self):
        store = self.open()
        real = store._db
        seen = []

        class Recorder:
            def execute(self, sql, *args):
                seen.append(" ".join(sql.split()).split(" (")[0][:40])
                return real.execute(sql, *args)

        store._db = Recorder()
        self.addCleanup(setattr, store, "_db", real)
        store.save(make())
        self.assertEqual(seen[0], "BEGIN IMMEDIATE")
        self.assertEqual(seen[-1], "COMMIT")
        self.assertEqual(seen.count("BEGIN IMMEDIATE"), 1)
        self.assertEqual(seen.count("COMMIT"), 1)
        self.assertNotIn("ROLLBACK", seen)

    def test_keep_revisions_below_one_still_keeps_the_newest(self):
        store = self.open(keep_revisions=0)
        project = make()
        for number in range(3):
            project.edit(title=f"제목 {number}", now=NOW)
            store.save(project)
        self.assertEqual([revision for revision, _when in store.history("p1")], [4])


class SaveLoadTest(StoreCase):
    def test_every_field_survives_the_trip(self):
        store = self.open()
        project = make(title="제목 — 한글·emoji 🙂·따옴표 \"'", body="첫 줄\n둘째 줄 `코드` **굵게**\n\n\n끝 \u2028 줄 구분")
        advance(project)
        advance(project, "blogger_en", st.DRAFT_SAVED)
        project.transition("github_pages", st.PUSHED, now=T2)
        project.transition("github_pages", st.PUBLISHED, published_url="https://example.com/2026/10/30/post/", now=T3)
        project.set_rendered("naver_a", "네이버용", now=T2)
        store.save(project)
        loaded = store.load("p1")
        self.assertEqual(loaded, project)
        self.assertEqual(loaded.to_dict(), project.to_dict())
        self.assertIsNot(loaded, project)
        self.assertEqual(loaded.variant("github_pages").published_url, "https://example.com/2026/10/30/post/")
        loaded.edit(title="바꿈", now=T3)                    # 불러온 것도 그대로 쓸 수 있다
        self.assertEqual(loaded.revision, 2)

    def test_saving_again_updates_in_place_and_keeps_the_created_time(self):
        store = self.open()
        project = make()
        store.save(project)
        project.set_rendered("github_pages", "첫 렌더링", now=T2)
        store.save(project)
        rows = self.raw().execute("SELECT COUNT(*), MAX(created_at), MAX(updated_at) FROM projects").fetchone()
        self.assertEqual(rows, (1, NOW, T2))
        self.assertEqual(store.load("p1").variant("github_pages").rendered, "첫 렌더링")
        self.assertIn("주제가 분명한 제목", self.raw().execute("SELECT data FROM projects").fetchone()[0], "한글은 \\uXXXX 로 풀지 않고 그대로 저장한다")
        project.edit(title="새 제목", now=T3)
        store.save(project)
        listed = store.list()
        self.assertEqual([(item.title, item.revision, item.created_at, item.updated_at) for item in listed], [("새 제목", 2, NOW, T3)])

    def test_the_list_columns_follow_the_saved_project_including_the_created_time(self):
        store = self.open()
        project = make()
        store.save(project)
        data = project.to_dict()
        data["created_at"], data["updated_at"] = T2, T3
        store.save(ContentProject.from_dict(data))
        self.assertEqual([(item.created_at, item.updated_at) for item in store.list()], [(T2, T3)])
        self.assertEqual(store.check(), [])

    def test_the_list_is_newest_first_then_by_id(self):
        store = self.open()
        for project_id, when in (("b", T2), ("a", T2), ("c", T3), ("d", NOW)):
            store.save(make(project_id, title=f"글 {project_id}", now=when))
        listed = store.list()
        self.assertEqual([item.project_id for item in listed], ["c", "a", "b", "d"])
        first = listed[0]
        self.assertEqual((first.title, first.revision, first.created_at, first.updated_at), ("글 c", 1, T3, T3))

    def test_exists_not_found_and_delete(self):
        store = self.open()
        store.save(make())
        self.assertTrue(store.exists("p1"))
        self.assertFalse(store.exists("p2"))
        error = self.refuses("CONTENT_NOT_FOUND", store.load, "p2")
        self.assertIn("p2", error.rendered().message)
        self.refuses("CONTENT_NOT_FOUND", store.delete, "p2")
        store.save(make("p3"))                                                  # 없는 글을 지우려던 일이 열린 트랜잭션을 남기지 않는다
        self.assertEqual([item.project_id for item in store.list()], ["p1", "p3"])

    def test_deleting_removes_the_revisions_and_the_draft_of_that_project_only(self):
        store = self.open()
        for project_id in ("p1", "p2"):
            store.save(make(project_id))
            store.save_draft(project_id, f"{project_id} 초안")
        store.delete("p1")
        db = self.raw()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM revisions WHERE project_id = 'p1'").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM revisions WHERE project_id = 'p2'").fetchone()[0], 1)
        self.assertIsNone(store.load_draft("p1"))
        self.assertEqual(store.load_draft("p2").text, "p2 초안")
        self.assertEqual([item.project_id for item in store.list()], ["p2"])

    def test_a_stale_screen_cannot_overwrite_a_newer_revision(self):
        store = self.open()
        project = make()
        store.save(project)
        stale = store.load("p1")
        project.edit(source_content="더 새로운 본문", now=T2)
        store.save(project)
        stale.edit(source_content="오래된 화면에서 고친 본문", now=T3)       # 판 2 — 저장된 판 2 와 같은 번호
        store.save(stale)                                                      # 같은 번호는 허용(상태만 바뀌는 저장과 구분할 수 없다)
        older = ContentProject.from_dict(store.load("p1").to_dict())
        older.revision = 1
        older.variants = {name: st_variant for name, st_variant in make().variants.items()}
        error = self.refuses("STORE_CONFLICT", store.save, older)
        self.assertIn(older.title, error.rendered().message)
        store.save(make("p5"))                                                  # 거절된 저장이 열린 트랜잭션을 남기지 않는다
        self.assertEqual(store.load("p1").revision, 2)
        self.assertEqual(store.load("p1").source_content, "오래된 화면에서 고친 본문")

    def test_a_save_that_fails_leaves_the_stored_copy_untouched(self):
        store = self.open()
        project = make()
        store.save(project)
        before = store.load("p1")
        broken = make()
        broken.title = ""
        self.refuses("CONTENT_INVALID", store.save, broken)
        self.refuses("CONTENT_INVALID", store.save, {"project_id": "p1"})
        self.refuses("CONTENT_INVALID", store.save, None)
        self.assertEqual(store.load("p1"), before)
        self.assertEqual(self.raw().execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)

    def test_bad_ids_are_refused_by_every_entry_point_before_touching_the_file(self):
        store = self.open()
        for bad in ("", "../x", "a b", "x" * 65, "한글", "p1; DROP TABLE projects", None, 5, b"p1"):
            for call in (store.load, store.exists, store.delete, store.history, store.load_draft, store.discard_draft):
                with self.subTest(call=call.__name__, bad=bad):
                    self.refuses("CONTENT_INVALID", call, bad)
            with self.subTest(call="snapshot", bad=bad):
                self.refuses("CONTENT_INVALID", store.snapshot, bad, 1)
            with self.subTest(call="save_draft", bad=bad):
                self.refuses("CONTENT_INVALID", store.save_draft, bad, "글")
        bad_project = make()
        bad_project.project_id = "../x"
        self.refuses("CONTENT_INVALID", store.save, bad_project)
        self.assertEqual(store.list(), [])

    def test_text_that_looks_like_sql_is_just_text(self):
        store = self.open()
        evil = "x'); DROP TABLE projects; --"
        store.save(make(title=evil, body=f"{evil}\n\n' OR '1'='1\n\n\x00 널 문자도"))
        loaded = store.load("p1")
        self.assertEqual(loaded.title, evil)
        self.assertIn("널 문자도", loaded.source_content)
        self.assertEqual(len(store.list()), 1)
        self.assertEqual(store.list()[0].title, evil)

    def test_a_large_manuscript_round_trips(self):
        store = self.open()
        body = ("긴 문단입니다. " * 300 + "\n\n") * 600
        self.assertGreater(len(body), 1_500_000)
        store.save(make(body=body))
        self.assertEqual(store.load("p1").source_content, body)

    def test_the_stored_copy_has_nothing_but_the_project(self):
        store = self.open()
        store.save(make())
        text = " ".join(str(value) for row in self.raw().execute("SELECT * FROM projects").fetchall() for value in row).lower()
        for needle in ("password", "token", "secret", "api_key", "cookie"):
            self.assertNotIn(needle, text)


class HistoryTest(StoreCase):
    def test_each_new_revision_gets_one_snapshot_and_saving_the_same_one_again_adds_none(self):
        store = self.open()
        project = make()
        store.save(project)
        project.set_rendered("github_pages", "렌더링", now=T2)       # 판은 그대로(상태만 바뀜)
        store.save(project)
        self.assertEqual(store.history("p1"), [(1, NOW)])
        project.edit(title="둘째 제목", source_content="둘째 본문", now=T3)
        store.save(project)
        self.assertEqual(store.history("p1"), [(2, T3), (1, NOW)])
        first, second = store.snapshot("p1", 1), store.snapshot("p1", 2)
        self.assertEqual((first.title, first.source_content), ("주제가 분명한 제목", "본문 첫 문단입니다.\n\n둘째 문단입니다."))
        self.assertEqual((second.title, second.source_content, second.saved_at), ("둘째 제목", "둘째 본문", T3))
        self.assertEqual(first.references, ("https://example.com/source",))
        self.assertEqual(first.assets, (Asset("a.png", "설명", 1),))
        self.assertEqual(first.revision, 1)

    def test_old_revisions_beyond_the_limit_go_first_and_the_newest_stays(self):
        store = self.open(keep_revisions=3)
        project = make()
        store.save(project)
        for number in range(6):
            project.edit(source_content=f"본문 {number}", now=NOW)
            store.save(project)
        self.assertEqual([revision for revision, _when in store.history("p1")], [7, 6, 5])
        self.assertEqual(store.snapshot("p1", 7).source_content, "본문 5")
        self.refuses("CONTENT_NOT_FOUND", store.snapshot, "p1", 4)

    def test_the_default_limit_keeps_fifty_revisions(self):
        store = self.open()
        project = make()
        store.save(project)
        for number in range(54):
            project.edit(source_content=f"본문 {number}", now=NOW)
            store.save(project)
        revisions = [revision for revision, _when in store.history("p1")]
        self.assertEqual((len(revisions), revisions[0], revisions[-1]), (50, 55, 6))

    def test_the_limit_is_per_project(self):
        store = self.open(keep_revisions=2)
        for project_id in ("p1", "p2"):
            project = make(project_id)
            for number in range(4):
                project.edit(source_content=f"본문 {number}", now=NOW)
                store.save(project)
        self.assertEqual([revision for revision, _when in store.history("p1")], [5, 4])
        self.assertEqual([revision for revision, _when in store.history("p2")], [5, 4])

    def test_going_back_to_an_old_text_makes_a_new_revision_and_keeps_the_record(self):
        store = self.open()
        project = make()
        store.save(project)
        project.edit(source_content="망친 본문", now=T2)
        store.save(project)
        old = store.snapshot("p1", 1)
        project.edit(title=old.title, source_content=old.source_content, references=old.references, assets=old.assets, now=T3)
        store.save(project)
        self.assertEqual(project.revision, 3)
        self.assertEqual([revision for revision, _when in store.history("p1")], [3, 2, 1])
        self.assertEqual(store.snapshot("p1", 3).source_content, old.source_content)
        self.assertEqual(store.snapshot("p1", 2).source_content, "망친 본문")

    def test_a_damaged_snapshot_is_reported(self):
        store = self.open()
        store.save(make())
        for bad in ("not json", "[]", '{"title": "x"}', '{"title":"x","source_content":"y","references":[],"assets":[{"nope":1}]}',
                    '{"title":"x","source_content":"y","references":[],"assets":[{"filename":"../x","alt":"","position":0}]}'):
            with self.subTest(bad=bad):
                self.raw().execute("UPDATE revisions SET data = ?", (bad,))
                self.refuses("STORE_CORRUPT", store.snapshot, "p1", 1)


class DraftTest(StoreCase):
    def test_drafts_are_kept_replaced_listed_newest_first_and_discarded(self):
        store = self.open()
        self.assertIsNone(store.load_draft("p1"))
        store.save_draft("p1", "첫 초안", now=NOW)
        store.save_draft("p2", "다른 글 초안", now=T3)
        store.save_draft("p1", "고친 초안", now=T2)
        draft = store.load_draft("p1")
        self.assertEqual((draft.project_id, draft.text, draft.saved_at), ("p1", "고친 초안", T2))
        self.assertEqual([(item.project_id, item.saved_at) for item in store.drafts()], [("p2", T3), ("p1", T2)])
        store.save_draft("p4", "같은 시각", now=T2)
        store.save_draft("p3", "같은 시각", now=T2)
        self.assertEqual([item.project_id for item in store.drafts()], ["p2", "p1", "p3", "p4"], "시각이 같으면 번호 순")
        store.discard_draft("p1")
        self.assertIsNone(store.load_draft("p1"))
        store.discard_draft("p1")                              # 없는 것을 버려도 오류가 아니다
        self.assertEqual([item.project_id for item in store.drafts()], ["p2", "p3", "p4"])

    def test_a_draft_needs_no_project_and_survives_a_sudden_stop(self):
        with Store.open(self.path) as store:
            store.save_draft("new-1", "아직 저장 못 한 글")
        reopened = self.open()
        self.assertEqual(reopened.load_draft("new-1").text, "아직 저장 못 한 글")
        self.assertEqual(reopened.list(), [])

    def test_a_draft_that_is_too_big_or_not_text_is_refused(self):
        store = self.open()
        store.save_draft("p1", "가" * MAX_DRAFT_CHARS)
        self.refuses("CONTENT_INVALID", store.save_draft, "p1", "가" * (MAX_DRAFT_CHARS + 1))
        for bad in (None, 5, b"bytes", ["목록"]):
            self.refuses("CONTENT_INVALID", store.save_draft, "p1", bad)
        self.assertEqual(len(store.load_draft("p1").text), MAX_DRAFT_CHARS)

    def test_the_draft_time_defaults_to_now(self):
        store = self.open()
        store.save_draft("p1", "글")
        self.assertRegex(store.load_draft("p1").saved_at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class TamperTest(StoreCase):
    def test_a_healthy_store_has_no_problems(self):
        store = self.open()
        self.assertEqual(store.check(), [])
        store.save(make())
        store.save(make("p2"))
        self.assertEqual(store.check(), [])

    def test_rows_that_were_edited_by_hand_or_damaged_are_reported_and_not_trusted(self):
        store = self.open()
        store.save(make())
        good = self.raw().execute("SELECT data FROM projects").fetchone()[0]
        extra = json.loads(good)
        extra["비밀"] = "x"
        other_id = json.loads(good)
        other_id["project_id"] = "p9"
        wrong_revision = json.loads(good)
        wrong_revision["revision"] = 0
        for name, bad in (("깨진 글", "not json"), ("빈 글", ""), ("목록", "[]"), ("모르는 칸", json.dumps(extra)), ("번호가 다름", json.dumps(other_id)), ("판이 올바르지 않음", json.dumps(wrong_revision)),
                          ("깊은 중첩", "[" * 100000), ("글이 아닌 값", 5)):
            with self.subTest(name):
                self.raw().execute("UPDATE projects SET data = ?", (bad,))
                error = self.refuses("STORE_CORRUPT", store.load, "p1")
                self.assertIn("p1", error.detail)
                problems = store.check()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("p1", problems[0])
        self.raw().execute("UPDATE projects SET data = ?", (good,))
        self.assertEqual(store.check(), [])

    def test_a_list_column_that_disagrees_with_the_stored_project_is_reported(self):
        store = self.open()
        store.save(make())
        for change in ("title = '다른 제목'", "revision = 5", f"created_at = '{T3}'", f"updated_at = '{T3}'"):
            with self.subTest(change):
                self.raw().execute(f"UPDATE projects SET {change}")
                problems = store.check()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("열과 자료가 다르다", problems[0])
                self.raw().execute("UPDATE projects SET title = ?, revision = 1, created_at = ?, updated_at = ?", ("주제가 분명한 제목", NOW, NOW))
                self.assertEqual(store.check(), [])

    def test_an_unexpected_type_problem_inside_a_stored_project_is_reported_as_damage_too(self):
        store = self.open()
        store.save(make())
        with mock.patch.object(ContentProject, "from_dict", side_effect=TypeError("뜻밖의 모양")):
            self.refuses("STORE_CORRUPT", store.load, "p1")

    def test_a_damaged_file_structure_is_reported_by_the_check(self):
        store = self.open()
        store.save(make())
        real = store._db

        class Broken:
            def execute(self, *args):
                raise sqlite3.DatabaseError("database disk image is malformed")

        store._db = Broken()
        self.addCleanup(setattr, store, "_db", real)         # 닫기 전에 진짜 연결로 되돌린다
        problems = store.check()
        self.assertEqual(len(problems), 1)
        self.assertIn("점검 중 오류", problems[0])
        self.assertIn("malformed", problems[0])

    def test_a_structure_problem_reported_by_sqlite_is_listed_as_such(self):
        store = self.open()
        real = store._db

        class Wrapper:
            def execute(self, sql, *args):
                if sql == "PRAGMA integrity_check":
                    return real.execute("SELECT 'row 3 missing from index x' UNION ALL SELECT 'ok'")
                return real.execute(sql, *args)

        store._db = Wrapper()
        self.addCleanup(setattr, store, "_db", real)
        problems = store.check()
        self.assertEqual(problems, ["파일 구조: row 3 missing from index x"])


class ErrorMappingTest(StoreCase):
    CASES = (
        ("database is locked", "STORE_LOCKED"), ("database table is locked: projects", "STORE_LOCKED"), ("database schema is locked: main", "STORE_LOCKED"),
        ("database or disk is full", "DISK_FULL"), ("disk is full", "DISK_FULL"),
        ("database disk image is malformed", "STORE_CORRUPT"), ("file is not a database", "STORE_CORRUPT"), ("file is encrypted or is not a database", "STORE_CORRUPT"),
        ("no such table: projects", "STORE_CORRUPT"), ("no such column: data", "STORE_CORRUPT"), ("database corruption at line 1", "STORE_CORRUPT"),
        ("unable to open database file", "FILE_WRITE_FAILED"), ("attempt to write a readonly database", "FILE_WRITE_FAILED"), ("disk I/O error", "FILE_WRITE_FAILED"),
        ("cannot open file", "FILE_WRITE_FAILED"), ("Permission denied", "FILE_WRITE_FAILED"), ("Access is denied", "FILE_WRITE_FAILED"),
        ("something nobody has seen", "UNEXPECTED_ERROR"), ("", "UNEXPECTED_ERROR"),
    )

    def test_sqlite_messages_become_error_codes(self):
        for message, code in self.CASES:
            with self.subTest(message=message):
                error = store_error(sqlite3.OperationalError(message), "C:/데이터/chanceblog.db")
                self.assertEqual(error.code, code)
                self.assertIn(code, CATALOG)
                shown = error.rendered()
                self.assertNotIn(UNKNOWN_SLOT, shown.message + shown.action)

    def test_the_path_and_file_names_go_into_the_slots_that_use_them(self):
        error = store_error(sqlite3.OperationalError("unable to open database file"), "C:/데이터/chanceblog.db")
        self.assertIn("C:/데이터/chanceblog.db", error.rendered().message)
        corrupt = store_error(sqlite3.DatabaseError("file is not a database"), "C:/데이터/chanceblog.db")
        self.assertIn("chanceblog.db", corrupt.rendered().message)
        self.assertNotIn("C:/데이터", corrupt.rendered().message)

    def test_an_app_error_passes_through_unchanged_and_the_detail_is_short_and_one_line(self):
        original = AppError("CONTENT_INVALID", {"항목": "x"})
        self.assertIs(store_error(original), original)
        long = store_error(sqlite3.OperationalError("database is locked\n" + "아주 긴 설명 " * 100))
        self.assertLessEqual(len(long.detail), 200)
        self.assertNotIn("\n", long.detail)

    def test_the_error_table_has_the_new_codes_with_the_slots_the_store_fills(self):
        for code, slots in (("STORE_CORRUPT", {"파일"}), ("STORE_LOCKED", set()), ("STORE_VERSION_UNSUPPORTED", {"파일"}), ("STORE_CONFLICT", {"항목"}), ("CONTENT_NOT_FOUND", {"항목"})):
            with self.subTest(code):
                self.assertEqual(set(CATALOG[code].slots), slots)


class LockAndThreadTest(StoreCase):
    def test_a_database_held_by_someone_else_is_reported_as_locked_not_waited_on_forever(self):
        store = self.open(busy_seconds=0.05)
        store.save(make())
        other = self.raw()
        other.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        self.refuses("STORE_LOCKED", store.save, make("p2"))
        self.refuses("STORE_LOCKED", store.list)
        self.refuses("STORE_LOCKED", store.load, "p1")
        self.refuses("STORE_LOCKED", Store.open, self.path, busy_seconds=0.05)
        self.assertLess(time.monotonic() - started, 3, "정한 기다림(0.05초)보다 훨씬 오래 멈춰 있었다")
        other.execute("ROLLBACK")
        self.assertEqual([item.project_id for item in store.list()], ["p1"])
        store.save(make("p2"))
        self.assertEqual([item.project_id for item in store.list()], ["p1", "p2"])

    def test_several_threads_can_share_one_store(self):
        store = self.open()
        errors = []

        def work(number):
            try:
                for step in range(12):
                    project = make(f"t{number}", title=f"글 {number}-{step}")
                    store.save(project)
                    store.save_draft(f"t{number}", f"초안 {step}")
                    store.list()
            except BaseException as error:                      # noqa: BLE001 — 스레드 안의 어떤 실패도 모은다
                errors.append(error)

        threads = [threading.Thread(target=work, args=(number,)) for number in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(item.project_id for item in store.list()), [f"t{number}" for number in range(5)])
        self.assertEqual(store.check(), [])
        self.assertEqual(len(store.drafts()), 5)


class MigrationTest(StoreCase):
    def make_old_file(self):
        with Store.open(self.path) as store:
            store.save(make())

    def add_table(self, db):
        db.execute("CREATE TABLE extra (id INTEGER)")

    def test_an_old_file_is_migrated_and_a_copy_is_kept(self):
        self.make_old_file()
        with mock.patch.object(store_module, "SCHEMA_VERSION", 2), mock.patch.object(store_module, "MIGRATIONS", {1: self.add_table}):
            store = self.open()
            self.assertEqual(store._db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(store._db.execute("SELECT COUNT(*) FROM extra").fetchone()[0], 0)
            self.assertEqual(store.load("p1").title, "주제가 분명한 제목")
        copy = self.path.with_name(self.path.name + ".v1.bak")
        self.assertTrue(copy.is_file())
        with closing(sqlite3.connect(str(copy))) as old:
            self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(old.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'extra'").fetchone()[0], 0)
            self.assertEqual(old.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)

    def test_steps_run_in_order_one_version_at_a_time(self):
        self.make_old_file()
        order = []
        with mock.patch.object(store_module, "SCHEMA_VERSION", 3), \
                mock.patch.object(store_module, "MIGRATIONS", {1: lambda db: order.append(1), 2: lambda db: order.append(2)}):
            store = self.open()
            self.assertEqual(store._db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(order, [1, 2])

    def test_a_failing_step_rolls_everything_back(self):
        self.make_old_file()

        def broken(db):
            db.execute("CREATE TABLE half_done (id INTEGER)")
            raise RuntimeError("중간에 실패")

        with mock.patch.object(store_module, "SCHEMA_VERSION", 2), mock.patch.object(store_module, "MIGRATIONS", {1: broken}):
            self.refuses("MIGRATION_FAILED", Store.open, self.path)
        db = self.raw()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'half_done'").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)
        self.assertTrue(self.path.with_name(self.path.name + ".v1.bak").is_file())
        self.assertEqual(self.open().load("p1").title, "주제가 분명한 제목", "원래 구조로는 그대로 열린다")

    def test_a_missing_step_is_a_failure_not_a_half_upgrade(self):
        self.make_old_file()
        with mock.patch.object(store_module, "SCHEMA_VERSION", 3), mock.patch.object(store_module, "MIGRATIONS", {1: self.add_table}):
            self.refuses("MIGRATION_FAILED", Store.open, self.path)
        db = self.raw()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'extra'").fetchone()[0], 0)

    def test_a_copy_that_cannot_be_made_stops_the_migration_before_it_starts(self):
        self.make_old_file()
        self.path.with_name(self.path.name + ".v1.bak").mkdir()          # 사본 자리에 폴더가 있다
        with mock.patch.object(store_module, "SCHEMA_VERSION", 2), mock.patch.object(store_module, "MIGRATIONS", {1: self.add_table}):
            self.refuses("MIGRATION_FAILED", Store.open, self.path)
        db = self.raw()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'extra'").fetchone()[0], 0)

    def test_no_copy_is_made_when_nothing_needs_migrating(self):
        self.make_old_file()
        self.open().close()
        self.assertEqual(sorted(entry.name for entry in self.path.parent.iterdir()), [self.path.name])


class BackupTest(StoreCase):
    WHEN = datetime(2026, 10, 30, 6, 0, 0, tzinfo=timezone.utc)

    def test_a_backup_is_a_timestamped_copy_that_opens_like_the_original(self):
        store = self.open()
        store.save(make())
        store.save(make("p2", title="둘째 글"))
        folder = self.dir / "backups"
        made = store.backup(folder, now=self.WHEN)
        self.assertEqual(made, folder / "chanceblog-20261030-060000.db")
        self.assertEqual([entry.name for entry in folder.iterdir()], [made.name], "임시 파일이 남지 않는다")
        with Store.open(made) as copy:
            self.assertEqual([item.project_id for item in copy.list()], [item.project_id for item in store.list()])
            self.assertEqual(copy.load("p2").title, "둘째 글")
            self.assertEqual(copy.check(), [])

    def test_a_backup_defaults_to_the_current_time(self):
        store = self.open()
        made = store.backup(self.dir / "backups")
        self.assertRegex(made.name, r"^chanceblog-\d{8}-\d{6}\.db$")

    def test_only_the_newest_backups_are_kept_and_other_files_are_left_alone(self):
        store = self.open()
        store.save(make())
        folder = self.dir / "backups"
        folder.mkdir()
        (folder / "notes.txt").write_text("메모", encoding="utf-8")
        (folder / "other-20200101-000000.db").write_bytes(b"x")          # 다른 이름의 백업은 건드리지 않는다
        (folder / "chanceblog-notes.db").write_bytes(b"x")
        for hour in range(5):
            store.backup(folder, keep=3, now=datetime(2026, 10, 30, hour, 0, 0, tzinfo=timezone.utc))
        left = sorted(entry.name for entry in folder.iterdir())
        self.assertEqual(left, ["chanceblog-20261030-020000.db", "chanceblog-20261030-030000.db", "chanceblog-20261030-040000.db",
                                "chanceblog-notes.db", "notes.txt", "other-20200101-000000.db"])

    def test_keeping_zero_still_keeps_the_one_just_made(self):
        store = self.open()
        folder = self.dir / "backups"
        store.backup(folder, keep=0, now=self.WHEN)
        store.backup(folder, keep=0, now=datetime(2026, 10, 30, 7, 0, 0, tzinfo=timezone.utc))
        self.assertEqual([entry.name for entry in folder.iterdir()], ["chanceblog-20261030-070000.db"])

    def test_a_failed_backup_is_reported_and_leaves_no_half_file(self):
        store = self.open()
        store.save(make())
        blocker = self.dir / "blocker"
        blocker.write_text("파일", encoding="utf-8")
        self.refuses("BACKUP_FAILED", store.backup, blocker)                  # 폴더 자리에 파일이 있다
        folder = self.dir / "backups"
        with mock.patch.object(store_module.os, "replace", side_effect=PermissionError("Access is denied")):
            self.refuses("BACKUP_FAILED", store.backup, folder, now=self.WHEN)
        self.assertEqual(list(folder.iterdir()), [], "실패한 백업의 임시 파일이 남았다")
        self.assertEqual(store.load("p1").project_id, "p1")

    def test_the_default_keeps_ten_backups(self):
        store = self.open()
        folder = self.dir / "backups"
        for hour in range(12):
            store.backup(folder, now=datetime(2026, 10, 30, hour, 0, 0, tzinfo=timezone.utc))
        names = sorted(entry.name for entry in folder.iterdir())
        self.assertEqual((len(names), names[0], names[-1]), (10, "chanceblog-20261030-020000.db", "chanceblog-20261030-110000.db"))

    def test_a_sqlite_failure_while_copying_is_also_a_failed_backup(self):
        store = self.open()
        folder = self.dir / "backups"
        with mock.patch.object(Store, "_copy_to", side_effect=sqlite3.OperationalError("disk I/O error")):
            error = self.refuses("BACKUP_FAILED", store.backup, folder, now=self.WHEN)
        self.assertIn("disk I/O error", error.detail)
        self.assertEqual(list(folder.iterdir()), [])

    def test_a_copy_that_fails_its_own_check_is_not_kept(self):
        store = self.open()
        folder = self.dir / "backups"
        real_connect, calls = sqlite3.connect, []

        def second_connection_says_the_copy_is_bad(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 2:                               # 첫 연결은 사본 만들기, 둘째 연결이 사본 점검
                fake = mock.MagicMock()
                fake.execute.return_value.fetchone.return_value = ("*** in database main ***",)
                return fake
            return real_connect(path, *args, **kwargs)

        with mock.patch.object(store_module.sqlite3, "connect", side_effect=second_connection_says_the_copy_is_bad):
            self.refuses("BACKUP_FAILED", store.backup, folder, now=self.WHEN)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(str(path).endswith(".tmp") for path in calls), f"사본은 임시 이름으로 만들어 점검한 뒤 이름을 바꾼다: {calls}")
        self.assertEqual(list(folder.iterdir()), [], "점검에 걸린 사본이 남았다")


class RestoreTest(StoreCase):
    def test_restoring_brings_back_the_backed_up_state_and_the_store_keeps_working(self):
        store = self.open()
        project = make()
        store.save(project)
        store.save_draft("p1", "그때의 초안")
        made = store.backup(self.dir / "backups")
        project.edit(title="그 뒤에 고친 제목", now=T2)
        store.save(project)
        store.save(make("p2"))
        store.save_draft("p3", "그 뒤의 초안")
        store.restore_from(made)
        self.assertEqual([item.project_id for item in store.list()], ["p1"])
        self.assertEqual(store.load("p1").title, "주제가 분명한 제목")
        self.assertEqual([item.project_id for item in store.drafts()], ["p1"])
        self.assertEqual(store.check(), [])
        self.assertFalse((self.path.parent / "safety").exists(), "안전 사본 폴더를 주지 않으면 만들지 않는다")
        store.save(make("p4"))                                                # 복구 뒤에도 쓸 수 있고
        store.delete("p4")
        self.assertEqual(store._db.execute("PRAGMA foreign_keys").fetchone()[0], 1)   # 연결 설정도 그대로다

    def test_a_failed_upgrade_while_restoring_leaves_the_store_usable(self):
        with Store.open(self.dir / "old.db") as old:
            old.save(make())
            made = old.backup(self.dir / "backups")
        digest_before = digest(made)

        def broken(db):
            raise RuntimeError("올리다 실패")

        with mock.patch.object(store_module, "SCHEMA_VERSION", 2), mock.patch.object(store_module, "MIGRATIONS", {1: broken}):
            store = self.open(self.dir / "new.db")
            self.refuses("MIGRATION_FAILED", store.restore_from, made)
            store._db.execute("PRAGMA user_version")                           # 열린 트랜잭션이 남았다면 아래 저장이 막힌다
        with mock.patch.object(store_module, "SCHEMA_VERSION", 1):
            store.save(make("p9"))
            self.assertEqual(store.load("p9").project_id, "p9")
        self.assertEqual(digest(made), digest_before, "복구에 쓴 백업 파일은 그대로다")

    def test_a_safety_copy_of_the_current_state_can_be_made_first(self):
        store = self.open()
        store.save(make())
        made = store.backup(self.dir / "backups")
        store.save(make("p2"))
        safety = self.dir / "safety"
        store.restore_from(made, safety_folder=safety)
        copies = list(safety.iterdir())
        self.assertEqual(len(copies), 1)
        with Store.open(copies[0]) as before:
            self.assertEqual([item.project_id for item in before.list()], ["p1", "p2"])
        self.assertEqual([item.project_id for item in store.list()], ["p1"])

    def test_a_bad_backup_changes_nothing(self):
        store = self.open()
        store.save(make())
        before = [item.project_id for item in store.list()]
        garbage = self.dir / "garbage.db"
        garbage.write_bytes(b"not a database " * 50)
        foreign = self.dir / "foreign.db"
        with closing(sqlite3.connect(str(foreign))) as other:
            other.execute("CREATE TABLE projects (project_id TEXT)")
            other.commit()
        newer = self.dir / "newer.db"
        with Store.open(newer):
            pass
        with closing(sqlite3.connect(str(newer))) as db:
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        for path, code in ((garbage, "STORE_CORRUPT"), (foreign, "STORE_CORRUPT"), (newer, "STORE_VERSION_UNSUPPORTED"), (self.dir / "missing.db", "FILE_WRITE_FAILED")):
            with self.subTest(path.name):
                error = self.refuses(code, store.restore_from, path, safety_folder=self.dir / "never")
                if code != "FILE_WRITE_FAILED":
                    self.assertIn(path.name, error.rendered().message)
                self.assertEqual([item.project_id for item in store.list()], before)
        self.assertFalse((self.dir / "never").exists(), "받아들이지 않을 백업이면 안전 사본도 만들지 않는다")
        self.assertEqual(store.check(), [])

    def test_a_read_only_backup_file_can_be_restored_from_and_is_not_changed(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("관리자(root)는 읽기 전용 파일도 쓸 수 있다")
        store = self.open()
        store.save(make())
        made = store.backup(self.dir / "backups")
        store.save(make("p2"))
        made.chmod(0o444)
        self.addCleanup(made.chmod, 0o644)
        before = digest(made)
        store.restore_from(made)
        self.assertEqual([item.project_id for item in store.list()], ["p1"])
        self.assertEqual(digest(made), before)

    def test_a_backup_with_a_damaged_page_is_refused(self):
        store = self.open()
        store.save(make(body="가나다 " * 30000))
        made = store.backup(self.dir / "backups")
        corrupt_a_middle_page(made)
        self.refuses("STORE_CORRUPT", store.restore_from, made)
        self.assertEqual(store.load("p1").project_id, "p1")

    def test_a_backup_with_a_damaged_inside_is_refused(self):
        store = self.open()
        store.save(make(body="가나다 " * 20000))
        made = store.backup(self.dir / "backups")
        data = made.read_bytes()
        made.write_bytes(data[:len(data) // 2])
        self.refuses("STORE_CORRUPT", store.restore_from, made)
        self.assertEqual(store.load("p1").project_id, "p1")

    def test_restoring_an_older_structure_brings_it_up_to_date(self):
        with Store.open(self.dir / "old.db") as old:
            old.save(make())
            made = old.backup(self.dir / "backups")
        with mock.patch.object(store_module, "SCHEMA_VERSION", 2), mock.patch.object(store_module, "MIGRATIONS", {1: lambda db: db.execute("CREATE TABLE extra (id INTEGER)")}):
            store = self.open(self.dir / "new.db")
            self.assertEqual(store._db.execute("PRAGMA user_version").fetchone()[0], 2)
            store.restore_from(made)
            self.assertEqual(store._db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(store._db.execute("SELECT COUNT(*) FROM extra").fetchone()[0], 0)
            self.assertEqual(store.load("p1").project_id, "p1")


if __name__ == "__main__":
    unittest.main()
