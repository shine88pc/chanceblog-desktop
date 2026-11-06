"""주제 엔진 보관함(`topicdb/file.py`·`topicdb/store.py`, `topic_engine.db`) 시험 — 여는 규칙·판 올리기·원복·동시 열기·표 읽고 쓰기·보류 기한의 기준(P3, D-61·D-62). 네트워크·실제 시계 없이 돈다.

지키는 것:
  1) 낯선 파일(기존 글 보관함 포함)·더 새로운 판·깨진 파일·모양이 다른 파일은 **한 바이트도 안 바꾸고** 거절한다. 읽기 전용 열기는 파일이나 폴더를 만들지 않고 수정 시각까지 그대로다.
  2) 판을 올릴 때는 쓰기 잠금 뒤 판 번호를 다시 읽고, 사전 사본(`.v1.bak`)을 두며(이미 있는 다른 사본은 덮어쓰지 않는다) 한 트랜잭션으로 올리고 실패하면 원래대로이며 여러 창이 동시에 열어도 안전하다.
  3) 후보 저장은 읽고 판단하고 쓰는 것이 한 트랜잭션이라 중간에 실패하면 하나도 저장되지 않는다(발행 이력 장부 포함). 같은 후보를 두 곳에서 동시에 더해도 겹치지 않는다.
  4) 보류 기한의 기준은 최초로 보류함에 든 때이고 다시 평가해도 앞당기거나 미루지 않는다. 구간 밖으로 나갔다 자동으로 돌아와도 최초 시각을 유지하고 새 주기는 사용자가 직접 다시 활성화할 때만이다(P3b-1, D-62 정정).
  5) 후보를 지우는 길은 90일 뒤 상세 정리(사용자 확인 뒤 한 트랜잭션) 하나뿐이고, 점수 스냅샷·관심도 캐시·연결·출처·장부가 정해진 규칙대로 쓰인다. 기존 보관함 `chanceblog.db` 와 서로 모른다.
"""
import contextlib
import dataclasses
import hashlib
import os
import sqlite3
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topicdb import file as engine_file  # noqa: E402
from chanceblog_desktop.topicdb import store as topic_store  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore  # noqa: E402
from chanceblog_desktop.topics import history as hs  # noqa: E402
from chanceblog_desktop.topics import trend  # noqa: E402
from chanceblog_desktop.topics.link import CandidateLink, Provenance  # noqa: E402

NOW = "2026-11-10T01:00:00Z"
CREATED = "2026-11-10T00:00:00Z"
DAY90 = "2027-02-08T00:00:00Z"                          # CREATED + 90일


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cand(number, *, final=70, channel="naver_a", expires=None, **more):
    """번호로 서로 다른 주제를 가진 후보 — 최종 점수가 `final`(보류 구간이면 기한을 따로 준다)."""
    values = {"topic": f"예시 주제 {number}번 모음", "seed_id": f"seed-{number}", "source_topic_id": f"src-{number}", "created_at": CREATED, "review_expires_at": expires}
    values.update(more)
    return ts.rated(final, candidate_id=f"cid-{number:03d}", channel=channel, cluster="local-ai", **values)


def hold_cand(number, **more):
    return cand(number, final=60, expires=DAY90, **more)


@contextlib.contextmanager
def connect(path):
    """닫는 것까지 하는 연결(Windows 는 열린 연결이 남으면 임시 폴더를 못 지운다) — 블록이 끝나면 저장하고 닫는다."""
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("PRAGMA foreign_keys = OFF")                      # 일부러 규칙을 어기는 손질(부모 번호 바꾸기 …)은 시스템 SQLite 빌드의 외래 키 기본값(켜진 빌드가 있다)에 기대지 않는다
        with connection:
            yield connection
    finally:
        connection.close()


def raw(path, sql, params=()):
    with connect(path) as connection:
        return connection.execute(sql, params).fetchall()


def v1_class():
    """P3 병합 시점의 판 1 파일을 만드는 서브클래스 — 옛 DDL(새 표 둘을 뺀 앞부분) 그대로 새 파일을 만든다. 실제 판 1 → 판 2 올리기와 '낡은 프로그램이 판 2 를 거절하는지' 를 시험하는 데 쓴다(P3b-1)."""
    class V1(TopicStore):
        SCHEMA_VERSION = 1
        SCHEMA = topic_store._SCHEMA[:-len(topic_store._NEW_TABLES)]
        SHAPES = {1: topic_store._SHAPES_V1}
        MIGRATIONS = {}
        _retired_ids = staticmethod(lambda db: set())                       # D-120: 판 1 흉내는 정리 이력·관계 표가 없다 — 옛 프로그램에는 '정리한 번호' 가 없었으니 거절할 번호도 없다

    return V1


def v2_class(fail=False, calls=None):
    """판 2 를 흉내 내는 서브클래스 — 새 표 하나를 더하는 올리기 단계가 있다(`fail` 이면 단계가 도중에 실패한다)."""
    def step(db):
        if calls is not None:
            calls.append(1)
        db.execute("CREATE TABLE extra_notes (note_id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        if fail:
            raise RuntimeError("일부러 낸 실패")
        db.execute("INSERT INTO extra_notes (note_id, body) VALUES ('n1', '올림')")

    class V2(TopicStore):
        SCHEMA_VERSION = 2
        SCHEMA = (*TopicStore.SCHEMA, "CREATE TABLE extra_notes (note_id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        SHAPES = {**TopicStore.SHAPES, 2: {**TopicStore.SHAPES[1], "extra_notes": ("note_id", "body")}}
        MIGRATIONS = {1: step}

    return V2


class OpenRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sub" / "topic_engine.db"

    def test_a_new_file_gets_its_own_name_tag_version_and_the_exact_shape(self):
        with TopicStore.open(self.path) as store:
            self.assertEqual((store.schema_version, store.needs_migration, store.read_only, store.check(), store.count()), (2, False, False, [], 0))        # P3b-1 의도적 갱신: 새 파일은 판 2
        self.assertEqual(raw(self.path, "PRAGMA application_id")[0][0], topic_store.APPLICATION_ID)
        self.assertEqual(raw(self.path, "PRAGMA user_version")[0][0], topic_store.SCHEMA_VERSION)
        with connect(self.path) as connection:
            self.assertIsNone(TopicStore(self.path, connection)._shape_problem(connection, 2, indexes=True))

    def test_the_name_tag_differs_from_the_existing_post_store_and_the_two_files_do_not_know_each_other(self):
        from chanceblog_desktop.content import store as post_store
        self.assertNotEqual(topic_store.APPLICATION_ID, post_store.APPLICATION_ID)
        folder = Path(self.tmp.name) / "data"
        with Store.open(folder / "chanceblog.db"):
            pass
        before = digest(folder / "chanceblog.db")
        with TopicStore.open(folder / "topic_engine.db") as store:
            store.add_candidates(lambda existing: [cand(1)], now=NOW)
        self.assertEqual(digest(folder / "chanceblog.db"), before, "주제 엔진 보관함을 쓰는 일이 글 보관함을 바꾸지 않는다")
        self.assertEqual(code_of(TopicStore.open, folder / "chanceblog.db"), "TOPIC_STORE_CORRUPT", "글 보관함은 주제 엔진 보관함으로 열리지 않는다")
        self.assertEqual(code_of(Store.open, folder / "topic_engine.db"), "STORE_CORRUPT", "주제 엔진 보관함은 글 보관함으로도 열리지 않는다")

    def test_reopening_works_and_the_data_is_still_there(self):
        with TopicStore.open(self.path) as store:
            store.add_candidates(lambda existing: [cand(1), cand(2)], now=NOW)
        with TopicStore.open(self.path) as store:
            self.assertEqual([item.candidate_id for item in store.list_candidates()], ["cid-001", "cid-002"])

    def test_a_zero_byte_file_is_treated_as_new(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"")
        with TopicStore.open(self.path) as store:
            self.assertEqual(store.count(), 0)
        self.assertGreater(self.path.stat().st_size, 0)

    def test_a_read_only_open_of_a_missing_file_creates_neither_file_nor_folder(self):
        self.assertEqual(code_of(TopicStore.open, self.path, migrate=False), "CONTENT_NOT_FOUND")
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"")
        self.assertEqual(code_of(TopicStore.open, self.path, migrate=False), "CONTENT_NOT_FOUND", "비어 있는 파일도 읽기 전용으로는 만들지 않는다")
        self.assertEqual(self.path.stat().st_size, 0)

    def test_a_read_only_open_changes_nothing_not_even_the_modification_time(self):
        with TopicStore.open(self.path) as store:
            store.add_candidates(lambda existing: [cand(1)], now=NOW)
        before = (digest(self.path), self.path.stat().st_mtime_ns, sorted(os.listdir(self.path.parent)))
        with TopicStore.open(self.path, migrate=False) as store:
            self.assertTrue(store.read_only)
            self.assertEqual(len(store.list_candidates()), 1)
            self.assertEqual(code_of(store.add_candidates, lambda existing: [cand(2)], now=NOW), "UNEXPECTED_ERROR")
            self.assertEqual(code_of(store.set_work_status, "cid-001", "REVIEW"), "UNEXPECTED_ERROR")
            self.assertEqual(code_of(store.sync_history, [], now=NOW), "UNEXPECTED_ERROR")
        self.assertEqual((digest(self.path), self.path.stat().st_mtime_ns, sorted(os.listdir(self.path.parent))), before)

    def test_foreign_files_are_refused_without_changing_a_byte(self):
        self.path.parent.mkdir(parents=True)
        foreign = self.path.parent / "foreign.db"
        with connect(foreign) as connection:
            connection.execute("CREATE TABLE other (x TEXT)")
            connection.execute("PRAGMA application_id = 12345")
        noise = self.path.parent / "noise.db"
        noise.write_bytes(os.urandom(4096))
        wrong_shape = self.path.parent / "wrong_shape.db"
        with TopicStore.open(wrong_shape):
            pass
        with connect(wrong_shape) as connection:
            connection.execute("ALTER TABLE hold_box RENAME COLUMN left_at TO gone_at")
        zero = self.path.parent / "zero_version.db"
        with TopicStore.open(zero):
            pass
        with connect(zero) as connection:
            connection.execute("PRAGMA user_version = 0")
        for name in ("foreign.db", "noise.db", "wrong_shape.db", "zero_version.db"):
            target = self.path.parent / name
            before = (digest(target), target.stat().st_mtime_ns, sorted(os.listdir(self.path.parent)))
            for migrate in (True, False):
                with self.subTest(file=name, migrate=migrate):
                    self.assertEqual(code_of(TopicStore.open, target, migrate=migrate), "TOPIC_STORE_CORRUPT")
                    self.assertEqual((digest(target), target.stat().st_mtime_ns, sorted(os.listdir(self.path.parent))), before)

    def test_a_newer_file_is_refused_without_changing_a_byte_and_without_leaving_a_copy(self):
        with TopicStore.open(self.path):
            pass
        with connect(self.path) as connection:
            connection.execute("PRAGMA user_version = 3")                     # P3b-1 의도적 갱신: 지금 판이 2 라서 '더 새로운 판' 은 3 이다
        before = (digest(self.path), sorted(os.listdir(self.path.parent)))
        for migrate in (True, False):
            with self.subTest(migrate=migrate):
                self.assertEqual(code_of(TopicStore.open, self.path, migrate=migrate), "TOPIC_STORE_VERSION_UNSUPPORTED")
        self.assertEqual((digest(self.path), sorted(os.listdir(self.path.parent))), before)

    def test_a_truncated_file_is_refused_not_overwritten(self):
        with TopicStore.open(self.path) as store:
            store.add_candidates(lambda existing: [cand(n) for n in range(1, 30)], now=NOW)
        data = self.path.read_bytes()
        self.path.write_bytes(data[: len(data) // 2])
        before = digest(self.path)
        self.assertIn(code_of(TopicStore.open, self.path), ("TOPIC_STORE_CORRUPT", "FILE_WRITE_FAILED"))
        self.assertEqual(digest(self.path), before)

    def test_a_file_whose_structure_check_reports_damage_is_refused_without_changing_a_byte(self):
        with TopicStore.open(self.path) as store:
            store.add_candidates(lambda existing: [cand(1), cand(2)], now=NOW)
        page_size = raw(self.path, "PRAGMA page_size")[0][0]
        root = raw(self.path, "SELECT rootpage FROM sqlite_master WHERE type = 'index' AND name = 'candidates_channel'")[0][0]
        damaged = bytearray(self.path.read_bytes())
        damaged[(root - 1) * page_size: root * page_size] = b"\xff" * page_size                # 색인 한 쪽만 망가뜨린다 — 이름표·판 번호·표 모양은 멀쩡해서 '구조 점검' 만이 알아챈다
        self.path.write_bytes(bytes(damaged))
        with connect(self.path) as connection:                                                 # 시험이 맞는 곳을 깼는지 확인한다
            self.assertEqual((connection.execute("PRAGMA application_id").fetchone()[0], connection.execute("PRAGMA user_version").fetchone()[0]), (topic_store.APPLICATION_ID, 2))
            self.assertEqual(len(connection.execute("SELECT name FROM pragma_table_info('hold_box')").fetchall()), 4)
            self.assertNotEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
        before = (digest(self.path), self.path.stat().st_mtime_ns, sorted(os.listdir(self.path.parent)))
        for migrate in (True, False):
            with self.subTest(migrate=migrate):
                self.assertEqual(code_of(TopicStore.open, self.path, migrate=migrate), "TOPIC_STORE_CORRUPT")
                self.assertEqual((digest(self.path), self.path.stat().st_mtime_ns, sorted(os.listdir(self.path.parent))), before)

    def test_a_read_only_open_cannot_write_even_through_the_raw_connection(self):
        with TopicStore.open(self.path) as store:
            store.add_candidates(lambda existing: [cand(1)], now=NOW)
        before = (digest(self.path), self.path.stat().st_mtime_ns)
        with TopicStore.open(self.path, migrate=False) as store:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                store._db.execute("CREATE TABLE zz_probe (x TEXT)")                      # 파이썬 쪽 확인(`_refuse_if_read_only`)을 우회해도 운영 체제 수준 읽기 전용(`mode=ro`)이라 쓸 수 없다
            self.assertIn("readonly", str(caught.exception).lower())
        self.assertEqual((digest(self.path), self.path.stat().st_mtime_ns), before)

    def test_a_creation_that_finds_the_schema_already_there_changes_nothing(self):
        with TopicStore.open(self.path) as first:
            first.add_candidates(lambda existing: [cand(1)], now=NOW)
        before = digest(self.path)
        connection = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        late = TopicStore(self.path, connection)
        try:
            late._prepare(True)                                                           # 이 창은 '처음 만든다' 고 믿고 열었지만 기다리는 사이 다른 창이 이미 만들었다
            self.assertEqual(late.count(), 1)
        finally:
            late.close()
        self.assertEqual(digest(self.path), before)

    def test_a_file_that_another_window_keeps_locked_is_reported_as_locked_not_as_something_else(self):
        with TopicStore.open(self.path) as store:
            store.add_candidates(lambda existing: [cand(1)], now=NOW)
        holder = sqlite3.connect(str(self.path), isolation_level=None)
        holder.execute("BEGIN EXCLUSIVE")
        try:
            self.assertEqual(code_of(TopicStore.open, self.path, busy_seconds=0.05), "TOPIC_STORE_LOCKED")
            self.assertEqual(code_of(TopicStore.open, self.path, busy_seconds=0.05, migrate=False), "TOPIC_STORE_LOCKED")
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        with TopicStore.open(self.path, busy_seconds=0.05) as store:
            holder = sqlite3.connect(str(self.path), isolation_level=None)
            holder.execute("BEGIN EXCLUSIVE")
            try:
                self.assertEqual(code_of(store.add_candidates, lambda existing: [cand(2)], now=NOW), "TOPIC_STORE_LOCKED", "쓰기도 같은 코드")
            finally:
                holder.execute("ROLLBACK")
                holder.close()
            self.assertEqual(store.count(), 1)

    def test_the_schema_is_pinned_so_changing_the_released_shape_is_a_conscious_change(self):
        # P3b-1 의도적 갱신: 지금 판이 2 다. 판 1 의 DDL(새 표 둘을 뺀 앞부분)은 한 글자도 바뀌지 않았고(기준값 그대로) 판 2 의 DDL 은 새 기준값으로 못박는다.
        v1_part = hashlib.sha256("\n".join(topic_store._SCHEMA[:-len(topic_store._NEW_TABLES)]).encode("utf-8")).hexdigest()
        self.assertEqual(v1_part, PINNED_SCHEMA_HASH, "판 1 의 DDL 은 바뀌지 않았다 — 고치려면 새 판의 올리기 단계를 만들고 이 값과 결정 기록을 함께 고친다")
        pinned = hashlib.sha256("\n".join(topic_store._SCHEMA).encode("utf-8")).hexdigest()
        self.assertEqual(pinned, PINNED_SCHEMA_V2_HASH, "판 2 의 DDL 을 고치려면 새 판의 올리기 단계를 만들고 이 값과 결정 기록을 함께 고친다")
        self.assertEqual((topic_store.APPLICATION_ID, topic_store.SCHEMA_VERSION), (0x43425445, 2))
        self.assertEqual(set(topic_store._SHAPES[1]), {"candidates", "hold_box", "score_snapshots", "trend_cache", "candidate_links", "provenance", "history_ledger"})
        # D-120 의도적 갱신(판 2 는 배포 전이라 같은 판 2 안에서 고쳤다): 보류 이력이 11칸 → 13칸(`first_created_on` → `first_created_at`, `cleaned_at`·`cleanup_reason` 추가)이고 재생성 관계 표 `candidate_lineage` 가 더해졌다
        self.assertEqual(set(topic_store._SHAPES[2]), set(topic_store._SHAPES[1]) | {"review_log", "hold_history", "candidate_lineage"})
        self.assertEqual(topic_store._SHAPES[2]["hold_history"], ("candidate_id", *topic_store.HOLD_HISTORY_FIELDS))
        self.assertEqual(topic_store._SHAPES[2]["candidate_lineage"], ("candidate_id", "recreated_from", "relation", "created_at"))
        self.assertEqual(len(topic_store.HOLD_HISTORY_FIELDS), 13, "보류 이력 13칸")


PINNED_SCHEMA_V2_HASH = "26f8253315dc9791de9e72218925f7ac0c6b6c0d7302ecc9f70a4a2ef05ff8d7"          # 판 2 의 DDL 문장들 전체의 SHA-256 — D-120 의도적 갱신: 보류 이력 13칸·재생성 관계 표(`candidate_lineage`)로 새 기준값(앞 값 `5a7e9c38…` 은 11칸·표 둘)
PINNED_SCHEMA_HASH = "5bb1fc020652892044220de588d480cac7afb3188d61275a44f861863e22d730"      # 판 1 의 DDL 문장들을 줄바꿈으로 이은 글의 SHA-256 — 낱말 하나만 고쳐도 달라진다


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"
        with v1_class().open(self.path) as store:                           # P3b-1 의도적 갱신: 지금 판이 2 라서 '올리기 전 파일' 은 판 1 흉내 클래스로 만든다
            store.add_candidates(lambda existing: [cand(1), hold_cand(2)], now=NOW)
        self.before_dump = self.dump()

    def dump(self):
        with connect(self.path) as connection:
            return list(connection.iterdump())

    def copies(self):
        return sorted(name for name in os.listdir(self.path.parent) if ".bak" in name)

    def test_a_v1_file_is_upgraded_with_a_pre_copy_and_the_data_survives(self):
        v2 = v2_class()
        with v2.open(self.path) as store:
            self.assertEqual((store.schema_version, store.needs_migration), (2, False))
            self.assertEqual([item.candidate_id for item in store.list_candidates()], ["cid-001", "cid-002"])
        self.assertEqual(raw(self.path, "PRAGMA user_version")[0][0], 2)
        self.assertEqual(raw(self.path, "SELECT body FROM extra_notes"), [("올림",)])
        self.assertEqual(self.copies(), ["topic_engine.db.v1.bak"])
        with connect(self.path.parent / "topic_engine.db.v1.bak") as connection:
            self.assertEqual(list(connection.iterdump()), self.before_dump, "사전 사본은 올리기 전 파일과 똑같다")
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_a_failing_step_puts_everything_back_as_it_was(self):
        self.assertEqual(code_of(v2_class(fail=True).open, self.path), "MIGRATION_FAILED")
        self.assertEqual(self.dump(), self.before_dump)
        self.assertEqual(raw(self.path, "PRAGMA user_version")[0][0], 1)
        with v1_class().open(self.path) as store:
            self.assertEqual(store.count(), 2, "원래 판으로 다시 열린다")

    def test_a_read_only_open_of_an_older_file_reports_it_and_changes_nothing(self):
        before = (digest(self.path), self.path.stat().st_mtime_ns, sorted(os.listdir(self.path.parent)))
        with v2_class().open(self.path, migrate=False) as store:
            self.assertEqual((store.schema_version, store.needs_migration), (1, True))
        self.assertEqual((digest(self.path), self.path.stat().st_mtime_ns, sorted(os.listdir(self.path.parent))), before)

    def test_an_existing_different_copy_is_never_overwritten_and_a_same_copy_is_reused(self):
        different = self.path.parent / "topic_engine.db.v1.bak"
        different.write_bytes(b"not the same")
        v2_class().open(self.path).close()
        self.assertEqual(different.read_bytes(), b"not the same")
        self.assertEqual(self.copies(), ["topic_engine.db.v1.2.bak", "topic_engine.db.v1.bak"])
        again = Path(self.tmp.name) / "again"
        again.mkdir()
        other = again / "topic_engine.db"
        other.write_bytes(self.path.with_name("topic_engine.db.v1.2.bak").read_bytes())
        (again / "topic_engine.db.v1.bak").write_bytes(other.read_bytes())            # 똑같은 사본이 이미 있다
        v2_class().open(other).close()
        self.assertEqual(sorted(os.listdir(again)), ["topic_engine.db", "topic_engine.db.v1.bak"], "같은 사본은 다시 만들지 않고 쓴다")

    def test_a_pre_copy_that_does_not_match_the_file_is_refused_and_leaves_no_copy(self):
        real = engine_file.EngineFile._snapshot

        def wrong(self_, destination):
            with connect(destination) as connection:                                      # 이름표·판 번호가 다른 파일을 사본이라고 내민다
                connection.execute("CREATE TABLE zz_probe (x TEXT)")

        engine_file.EngineFile._snapshot = wrong
        self.addCleanup(setattr, engine_file.EngineFile, "_snapshot", real)
        self.assertEqual(code_of(v2_class().open, self.path), "MIGRATION_FAILED", "점검에 실패한 사본으로는 올리지 않는다")
        self.assertEqual(self.copies(), [], "점검에 실패한 사본은 자리에 남지 않는다")
        self.assertEqual(self.dump(), self.before_dump)
        self.assertEqual(raw(self.path, "PRAGMA user_version")[0][0], 1)

    def test_an_existing_copy_with_the_same_tag_and_version_but_other_rows_is_not_reused(self):
        other = Path(self.tmp.name) / "other" / "topic_engine.db"
        with v1_class().open(other) as store:
            store.add_candidates(lambda existing: [cand(7)], now=NOW)                    # 이름표·판·표 모양은 같고 행만 다르다
        stale = self.path.parent / "topic_engine.db.v1.bak"
        stale.write_bytes(other.read_bytes())
        v2_class().open(self.path).close()
        self.assertEqual(stale.read_bytes(), other.read_bytes(), "다른 사본은 건드리지 않는다")
        self.assertEqual(self.copies(), ["topic_engine.db.v1.2.bak", "topic_engine.db.v1.bak"], "다른 내용의 사본은 믿지 않고 새 이름으로 따로 만든다")
        with connect(self.path.parent / "topic_engine.db.v1.2.bak") as connection:
            self.assertEqual(list(connection.iterdump()), self.before_dump, "새 사본은 올리기 전 파일과 똑같다")

    def test_a_missing_step_is_refused_and_leaves_the_file_alone(self):
        class Broken(TopicStore):
            SCHEMA_VERSION = 3
            MIGRATIONS = {}

        before = digest(self.path)
        self.assertEqual(code_of(Broken.open, self.path), "MIGRATION_FAILED")
        self.assertEqual(digest(self.path), before)

    def test_a_read_only_file_is_refused_before_any_copy_is_made(self):
        os.chmod(self.path, stat.S_IREAD)
        self.addCleanup(os.chmod, self.path, stat.S_IWRITE | stat.S_IREAD)
        if os.access(self.path, os.W_OK):
            self.skipTest("이 환경은 읽기 전용 표시를 무시한다(관리자 권한 등)")
        before = digest(self.path)
        self.assertEqual(code_of(v2_class().open, self.path), "MIGRATION_BLOCKED")
        self.assertEqual((digest(self.path), self.copies()), (before, []))

    def test_two_windows_opening_at_once_upgrade_once_and_both_succeed(self):
        calls, errors, barrier = [], [], threading.Barrier(2)
        v2 = v2_class(calls=calls)

        def open_it():
            try:
                barrier.wait(timeout=10)
                with v2.open(self.path) as store:
                    self.assertEqual(store.schema_version, 2)
            except BaseException as error:                                         # 시험 스레드의 실패를 모아 본 스레드에서 알린다
                errors.append(repr(error))

        threads = [threading.Thread(target=open_it) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1, "올리기 단계는 한 번만 돈다")
        self.assertEqual(self.copies(), ["topic_engine.db.v1.bak"])

    def test_the_version_is_read_again_after_taking_the_write_lock(self):
        calls = []
        v2 = v2_class(calls=calls)
        real_begin = engine_file.EngineFile._begin
        state = {"done": False}

        def begin_after_another_window_upgraded(self):
            if not state["done"] and self.SCHEMA_VERSION == 2:
                state["done"] = True
                v2_class(calls=calls).open(self.path).close()                     # 우리가 잠금을 잡기 직전에 다른 창이 먼저 올렸다
            return real_begin(self)

        engine_file.EngineFile._begin = begin_after_another_window_upgraded
        self.addCleanup(setattr, engine_file.EngineFile, "_begin", real_begin)
        with v2.open(self.path) as store:
            self.assertEqual(store.schema_version, 2)
        self.assertEqual(len(calls), 1, "잠금 안에서 판 번호를 다시 읽어 이미 올랐으면 아무것도 하지 않는다")
        self.assertEqual(len(self.copies()), 1)


class CandidateWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"
        self.store = TopicStore.open(self.path)
        self.addCleanup(self.store.close)

    def test_saved_candidates_come_back_equal_with_the_lookup_columns_filled(self):
        first, held = cand(1, final=85, seed_id="seed-1"), hold_cand(2, channel="naver_b")
        saved = self.store.add_candidates(lambda existing: [first, held], now=NOW)
        self.assertEqual(saved, (first, held))
        self.assertEqual(self.store.load_candidate("cid-001"), first)
        self.assertEqual(self.store.list_candidates(), [first, held])
        rows = {row[0]: row for row in raw(self.path, "SELECT candidate_id, channel, work_status, band, final_score, created_at, review_expires_at, normalized_topic_hash, seed_id, saved_at FROM candidates")}
        from chanceblog_desktop.topics.slots import normalized_topic_hash
        self.assertEqual(rows["cid-001"], ("cid-001", "naver_a", "NEW", "RECOMMENDED", 85, CREATED, None, normalized_topic_hash(first.topic), "seed-1", NOW))
        self.assertEqual(rows["cid-002"][3:7], ("HOLD", 60, CREATED, DAY90))

    def test_list_filters_and_the_order_is_the_saved_order(self):
        items = [cand(3, created_at="2026-11-10T00:00:00Z"), cand(2, created_at="2026-11-09T00:00:00Z"), cand(1, created_at="2026-11-10T00:00:00Z", channel="naver_b"), hold_cand(4)]
        self.store.add_candidates(lambda existing: items, now=NOW)
        self.assertEqual([c.candidate_id for c in self.store.list_candidates()], ["cid-003", "cid-002", "cid-001", "cid-004"], "저장한 순서 — 만든 시각이 달라도 순서는 안 바뀐다")
        self.assertEqual([c.candidate_id for c in self.store.list_candidates(channel="naver_b")], ["cid-001"])
        self.assertEqual([c.candidate_id for c in self.store.list_candidates(band="HOLD")], ["cid-004"])
        self.assertEqual([c.candidate_id for c in self.store.list_candidates(work_status="NEW", channel="naver_a")], ["cid-003", "cid-002", "cid-004"])
        self.assertEqual((self.store.count(), self.store.count("naver_b"), self.store.count("github_pages")), (4, 1, 0))
        for kwargs in ({"channel": "nowhere"}, {"work_status": "DONE"}, {"band": "BEST"}, {"channel": 3}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(code_of(self.store.list_candidates, **kwargs), "CANDIDATE_INVALID")

    def test_a_later_save_never_moves_the_order_of_what_was_saved_before_even_with_an_earlier_or_equal_creation_time(self):
        self.store.add_candidates(lambda existing: [cand(5, created_at="2026-11-10T00:00:00Z"), cand(6, created_at="2026-11-10T00:00:00Z")], now=NOW)
        first = [c.candidate_id for c in self.store.list_candidates()]
        self.store.add_candidates(lambda existing: [cand(1, created_at="2026-11-10T00:00:00Z"), cand(2, created_at="2025-01-01T00:00:00Z")], now=NOW)    # 같은 시각·더 이른 시각·번호가 앞선 후보
        self.assertEqual([c.candidate_id for c in self.store.list_candidates()], [*first, "cid-001", "cid-002"], "먼저 저장한 후보의 순서는 그대로이고 새 후보는 뒤에 붙는다")

    def test_a_hold_band_candidate_enters_the_hold_box_and_every_candidate_gets_a_first_score_snapshot(self):
        self.store.add_candidates(lambda existing: [cand(1, final=85), hold_cand(2)], now=NOW)
        self.assertEqual([tuple(stay) for stay in self.store.hold_stays()], [("cid-002", CREATED, DAY90, None)])
        for number, band in ((1, "RECOMMENDED"), (2, "HOLD")):
            history = self.store.score_history(f"cid-00{number}")
            self.assertEqual([(item.evaluated_at, item.band) for item in history], [(CREATED, band)])
            self.assertEqual(history[0].scores, self.store.load_candidate(f"cid-00{number}").scores)

    def test_there_is_no_way_to_delete_a_candidate(self):
        names = {name for name in dir(TopicStore) if not name.startswith("_")}
        self.assertFalse({name for name in names if "delete" in name or "remove" in name or "drop" in name or "purge" in name or "clear" in name}, "지우는 이름의 도구는 없다 — 지울지는 운영자가 정한다")
        source = Path(topic_store.__file__).read_text(encoding="utf-8")
        # P3b-1 의도적 갱신(2026-11-06 운영자 결정 — 90일 뒤 변화가 없으면 상세 데이터 정리, 자동 삭제 금지): 후보를 지우는 길은 `cleanup_hold` 하나뿐이다(사용자가 `--yes` 로 확인했을 때만 서비스가 부른다)
        self.assertEqual(source.count("DELETE FROM candidates"), 1)
        body = source[source.index("    def cleanup_hold(self"):source.index("    def hold_history(self")]
        self.assertIn("DELETE FROM candidates", body, "그 한 곳이 `cleanup_hold` 안이다")

    def test_nothing_is_saved_when_the_plan_fails_halfway_or_gives_a_wrong_object_or_a_taken_number(self):
        record = hs.HistoryRecord(channel="naver_a", title="예시 이력 글", ref="p1", origin="naver_items")
        self.store.add_candidates(lambda existing: [cand(1)], now=NOW)

        def half(existing):
            yield cand(2)
            raise RuntimeError("계산 도중에 멈춤")

        for name, plan, code in (("계산 도중 실패", half, None), ("후보가 아닌 값", lambda existing: [cand(3), {"candidate_id": "x"}], "CANDIDATE_INVALID"),
                                 ("이미 있는 번호", lambda existing: [cand(4), cand(1)], "UNEXPECTED_ERROR"), ("같은 번호 둘", lambda existing: [cand(5), cand(5)], "UNEXPECTED_ERROR"),
                                 ("기한이 구간과 어긋남", lambda existing: [cand(6), cand(7, final=60, expires=None)], "CANDIDATE_INVALID")):
            with self.subTest(case=name):
                if code is None:
                    with self.assertRaises(RuntimeError):
                        self.store.add_candidates(plan, now=NOW, history=[record])
                else:
                    self.assertEqual(code_of(self.store.add_candidates, plan, now=NOW, history=[record]), code)
                self.assertEqual([c.candidate_id for c in self.store.list_candidates()], ["cid-001"])
                self.assertEqual(self.store.history_records(), [], "발행 이력 장부도 같은 트랜잭션이라 함께 되돌려진다")
                self.assertEqual(self.store.hold_stays(), [])
                self.assertEqual(raw(self.path, "SELECT COUNT(*) FROM score_snapshots"), [(1,)])

    def test_the_plan_sees_the_candidates_read_after_the_write_lock_was_taken(self):
        self.store.add_candidates(lambda existing: [cand(1)], now=NOW)
        seen = []
        self.store.add_candidates(lambda existing: (seen.append([c.candidate_id for c in existing]), [cand(2)])[1], now=NOW)
        self.assertEqual(seen, [["cid-001"]])

    def test_two_windows_adding_the_same_candidates_at_once_do_not_duplicate(self):
        errors, barrier = [], threading.Barrier(2)

        def add():
            try:
                with TopicStore.open(self.path) as other:
                    barrier.wait(timeout=10)
                    other.add_candidates(lambda existing: [item for item in (cand(n) for n in range(1, 7)) if item.candidate_id not in {c.candidate_id for c in existing}], now=NOW)
            except BaseException as error:
                errors.append(repr(error))

        threads = [threading.Thread(target=add) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual([c.candidate_id for c in self.store.list_candidates()], [f"cid-00{n}" for n in range(1, 7)])

    def test_a_taken_number_is_refused_by_the_store_with_its_own_reason_not_by_a_database_constraint(self):
        self.store.add_candidates(lambda existing: [cand(1)], now=NOW)
        for name, plan in (("이미 저장된 번호", lambda existing: [cand(1)]), ("한 번에 같은 번호 둘", lambda existing: [cand(2), cand(2)])):
            with self.subTest(case=name):
                with self.assertRaises(AppError) as caught:
                    self.store.add_candidates(plan, now=NOW)
                self.assertEqual(caught.exception.code, "UNEXPECTED_ERROR")
                self.assertIn("같은 번호의 후보가 이미 있다", caught.exception.detail)
                self.assertNotIn("UNIQUE", caught.exception.detail)
        self.assertEqual([c.candidate_id for c in self.store.list_candidates()], ["cid-001"])

    def test_the_work_status_moves_only_along_the_table_and_touches_nothing_else(self):
        self.store.add_candidates(lambda existing: [hold_cand(1)], now=NOW)
        before = self.store.load_candidate("cid-001")
        moved = self.store.set_work_status("cid-001", "REVIEW")
        self.assertEqual((moved.work_status, moved.scores, moved.review_expires_at, moved.recommendation_band), ("REVIEW", before.scores, before.review_expires_at, "HOLD"))
        self.assertEqual(self.store.load_candidate("cid-001"), moved)
        self.assertEqual(raw(self.path, "SELECT work_status, band, review_expires_at FROM candidates"), [("REVIEW", "HOLD", DAY90)])
        self.assertEqual(self.store.set_work_status("cid-001", "REVIEW").work_status, "REVIEW", "같은 상태 유지는 괜찮다")
        self.assertEqual(code_of(self.store.set_work_status, "cid-001", "NEW"), "CANDIDATE_TRANSITION_INVALID")
        self.store.set_work_status("cid-001", "REJECTED")
        self.assertEqual(code_of(self.store.set_work_status, "cid-001", "SELECTED"), "CANDIDATE_TRANSITION_INVALID", "제외한 후보는 검토 중으로만 되살린다")
        self.assertEqual(self.store.set_work_status("cid-001", "REVIEW", now=NOW).work_status, "REVIEW")        # P3b-1 의도적 갱신: 보류함에 든 적이 있는 후보를 제외에서 되살리는 것은 '직접 다시 활성화' 라 지금 시각이 필요하다
        self.assertEqual(code_of(self.store.set_work_status, "cid-404", "REVIEW"), "TOPIC_CANDIDATE_NOT_FOUND")
        self.assertEqual(code_of(self.store.set_work_status, "cid-001", "DONE"), "CANDIDATE_INVALID")
        self.assertEqual(code_of(self.store.set_work_status, "bad id!", "REVIEW"), "CANDIDATE_INVALID")
        self.assertEqual(len(self.store.hold_stays()), 1, "작업 상태를 바꿔도 보류함 기록은 그대로다")

    def test_a_corrupt_row_blocks_only_by_a_clear_error(self):
        self.store.add_candidates(lambda existing: [cand(1), cand(2)], now=NOW)
        raw_update = sqlite3.connect(str(self.path))
        with raw_update:
            raw_update.execute("UPDATE candidates SET data = ? WHERE candidate_id = 'cid-002'", ("{not json",))
        raw_update.close()
        self.assertEqual(code_of(self.store.load_candidate, "cid-002"), "TOPIC_STORE_CORRUPT")
        self.assertEqual(code_of(self.store.list_candidates), "TOPIC_STORE_CORRUPT")
        self.assertEqual(self.store.load_candidate("cid-001").candidate_id, "cid-001")
        self.assertEqual(self.store.count(), 2, "자료를 읽지 않는 세기는 깨진 후보도 센다")
        self.assertTrue(any("cid-002" in problem for problem in self.store.check()))
        self.assertEqual(code_of(self.store.load_candidate, "cid-404"), "TOPIC_CANDIDATE_NOT_FOUND")


class TransactionPrimitivesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"
        self.store = TopicStore.open(self.path)
        self.addCleanup(self.store.close)

    def test_rolling_back_with_nothing_to_roll_back_gives_text_instead_of_raising(self):
        self.assertNotEqual(self.store._rollback(), "", "시작한 트랜잭션이 없으면 되돌릴 것이 없다 — 오류를 내지 않고 이유를 글로 돌려준다")
        self.store._begin()
        self.assertEqual(self.store._rollback(), "", "되돌리기에 성공하면 빈 글이다")

    def test_a_failing_rollback_never_hides_the_original_error(self):
        def work(db):
            db.execute("COMMIT")                                       # 트랜잭션을 스스로 끝내 버렸으니 뒤이은 되돌리기는 '되돌릴 것이 없다' 로 실패한다
            raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": "시험"})

        self.assertEqual(code_of(self.store._write, work), "TOPIC_CANDIDATE_NOT_FOUND", "되돌리다 난 오류가 원래 오류를 가리면 안 된다")
        self.assertEqual(self.store.count(), 0)


class JournalAndRowChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"
        self.store = TopicStore.open(self.path)
        self.addCleanup(self.store.close)
        self.store.add_candidates(lambda existing: [cand(1), cand(2)], now=NOW)

    def test_an_unfinished_save_is_recognised_only_by_a_non_empty_journal_file(self):
        journal = Path(str(self.path) + "-journal")
        self.assertFalse(self.store._has_unfinished_save())
        journal.write_bytes(b"")
        self.assertFalse(self.store._has_unfinished_save(), "빈 저널은 정리할 것이 없다")
        journal.write_bytes(b"x")
        self.addCleanup(lambda: journal.exists() and journal.unlink())
        self.assertTrue(self.store._has_unfinished_save())

    def test_a_row_whose_number_differs_from_the_number_inside_its_data_is_refused(self):
        with connect(self.path) as connection:
            connection.execute("UPDATE candidates SET candidate_id = 'cid-777' WHERE candidate_id = 'cid-002'")
        self.assertEqual(code_of(self.store.load_candidate, "cid-777"), "TOPIC_STORE_CORRUPT")
        self.assertEqual(code_of(self.store.list_candidates), "TOPIC_STORE_CORRUPT")


class HoldBasisTest(unittest.TestCase):
    """보류 기한의 기준 시각(열린 항목 7, D-62) — 처음 보류함에 든 때 + 90일이고 다시 평가해도 앞당기거나 미루지 않는다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"
        self.store = TopicStore.open(self.path)
        self.addCleanup(self.store.close)
        self.store.add_candidates(lambda existing: [hold_cand(1), cand(2, final=70)], now=NOW)

    def test_re_evaluating_inside_the_hold_band_keeps_the_first_deadline(self):
        newer = dataclasses.replace(hold_cand(1), scores=ts.flat_card(58), created_at="2026-12-01T00:00:00Z", review_expires_at="2027-03-01T00:00:00Z")
        changed = self.store.re_evaluate(newer, evaluated_at="2026-12-20T00:00:00Z")
        self.assertEqual(changed.review_expires_at, DAY90, "다시 평가해도 기한이 미뤄지지 않는다(처음 든 때 기준)")
        self.assertEqual(changed.created_at, CREATED, "만든 시각은 저장된 것을 지킨다")
        self.assertEqual(changed.scores.final, 58)
        self.assertEqual([tuple(stay) for stay in self.store.hold_stays()], [("cid-001", CREATED, DAY90, None)])
        self.assertEqual([(item.evaluated_at, item.final_score) for item in self.store.score_history("cid-001")], [(CREATED, 60), ("2026-12-20T00:00:00Z", 58)])
        self.assertEqual(raw(self.path, "SELECT final_score, review_expires_at FROM candidates WHERE candidate_id = 'cid-001'"), [(58, DAY90)])

    def test_an_earlier_looking_new_deadline_does_not_pull_the_deadline_forward_either(self):
        earlier = dataclasses.replace(hold_cand(1), review_expires_at="2026-11-12T00:00:00Z")
        self.assertEqual(self.store.re_evaluate(earlier, evaluated_at="2026-11-11T00:00:00Z").review_expires_at, DAY90)

    def test_leaving_the_band_closes_the_stay_and_coming_back_keeps_the_first_time(self):
        # P3b-1 의도적 갱신(D-62 정정): 예전에는 '나갔다 다시 들어오면 그때부터 새로 센다' 였다 — 이제 자동으로 돌아와도 최초 시각(과 기한)을 그대로 쓴다. 새 주기는 사용자가 직접 다시 활성화할 때만이다.
        left = self.store.re_evaluate(dataclasses.replace(hold_cand(1), scores=ts.flat_card(72), review_expires_at=None), evaluated_at="2026-12-01T00:00:00Z")
        self.assertEqual((left.recommendation_band, left.review_expires_at), ("GENERAL", None))
        self.assertEqual([tuple(stay) for stay in self.store.hold_stays()], [])
        self.assertEqual([tuple(stay) for stay in self.store.hold_stays(open_only=False)], [("cid-001", CREATED, DAY90, "2026-12-01T00:00:00Z")])
        back = self.store.re_evaluate(dataclasses.replace(hold_cand(1), scores=ts.flat_card(55)), evaluated_at="2027-01-10T00:00:00Z")
        self.assertEqual(back.review_expires_at, DAY90, "나갔다 자동으로 돌아와도 최초 시각의 기한 그대로다")
        self.assertEqual([tuple(stay) for stay in self.store.hold_stays()], [("cid-001", CREATED, DAY90, None)])

    def test_a_candidate_that_was_not_on_hold_gets_its_stay_when_it_first_falls_into_the_band(self):
        fell = self.store.re_evaluate(dataclasses.replace(cand(2, final=70), scores=ts.flat_card(60)), evaluated_at="2026-12-01T00:00:00Z")
        self.assertEqual(fell.review_expires_at, "2027-03-01T00:00:00Z")
        self.assertEqual(sorted(tuple(stay) for stay in self.store.hold_stays()), [("cid-001", CREATED, DAY90, None), ("cid-002", "2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z", None)])

    def test_re_evaluating_at_an_instant_that_already_has_a_snapshot_keeps_one_line_for_that_instant(self):
        newer = dataclasses.replace(hold_cand(1), scores=ts.flat_card(58))
        self.store.re_evaluate(newer, evaluated_at=CREATED)                              # 처음 점수와 같은 시각 — 그 시각의 줄은 하나뿐이다(오류도 새 줄도 없다)
        self.store.re_evaluate(newer, evaluated_at="2026-12-20T00:00:00Z")
        self.store.re_evaluate(newer, evaluated_at="2026-12-20T00:00:00Z")
        self.assertEqual([item.evaluated_at for item in self.store.score_history("cid-001")], [CREATED, "2026-12-20T00:00:00Z"])
        self.assertEqual(self.store.check(), [])

    def test_the_work_status_stays_and_wrong_calls_are_refused(self):
        self.store.set_work_status("cid-001", "SELECTED")
        kept = self.store.re_evaluate(dataclasses.replace(hold_cand(1), work_status="NEW"), evaluated_at="2026-12-01T00:00:00Z")
        self.assertEqual(kept.work_status, "SELECTED", "다시 평가가 사람의 작업 상태를 바꾸지 않는다")
        self.assertEqual(code_of(self.store.re_evaluate, hold_cand(99), evaluated_at="2026-12-01T00:00:00Z"), "TOPIC_CANDIDATE_NOT_FOUND")
        self.assertEqual(code_of(self.store.re_evaluate, dataclasses.replace(hold_cand(1), channel="naver_b", language="ko"), evaluated_at="2026-12-01T00:00:00Z"), "CANDIDATE_INVALID")
        self.assertEqual(code_of(self.store.re_evaluate, hold_cand(1), evaluated_at="어제"), "CANDIDATE_INVALID")
        self.assertEqual(code_of(self.store.re_evaluate, {"a": 1}, evaluated_at="2026-12-01T00:00:00Z"), "CANDIDATE_INVALID")
        self.assertEqual(self.store.check(), [])


class SideTablesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"
        self.store = TopicStore.open(self.path)
        self.addCleanup(self.store.close)
        self.store.add_candidates(lambda existing: [cand(1, final=85), cand(2)], now=NOW)

    def reading(self, **more):
        values = dict(queried=True, trend_status="rising", trend_ratio=73, trend_period="최근 1년", trend_compared_group=("기준", "예시"), trend_queried_on="2026-11-10", data_status="sufficient")
        values.update(more)
        return trend.TrendReading(**values)

    def test_the_trend_cache_keeps_valued_readings_for_a_while_and_never_the_unavailable_ones(self):
        self.assertTrue(self.store.put_trend("예시 키워드", self.reading(), now=NOW))
        got = self.store.get_trend("예시 키워드", "최근 1년", ("기준", "예시"), today="2026-11-10")
        self.assertEqual((got.trend_ratio, got.trend_status, got.trend_compared_group, got.trend_queried_on), (73, "rising", ("기준", "예시"), "2026-11-10"))
        self.assertEqual(self.store.get_trend("예시키워드", "최근 1년", ("기준", "예시"), today="2026-11-10").trend_ratio, 73, "키워드는 띄어쓰기를 가리지 않는다")
        self.assertIsNone(self.store.get_trend("예시 키워드", "최근 1년", ("다른", "그룹"), today="2026-11-10"), "비교 그룹이 다르면 다른 값이다")
        self.assertIsNone(self.store.get_trend("예시 키워드", "최근 2년", ("기준", "예시"), today="2026-11-10"))
        for day, expected in (("2026-11-17", True), ("2026-11-18", False), ("2026-11-09", False)):                      # 조회일 +7일까지, 그 뒤·미래 날짜는 믿지 않는다
            with self.subTest(today=day):
                self.assertEqual(self.store.get_trend("예시 키워드", "최근 1년", ("기준", "예시"), today=day) is not None, expected)
        self.assertIsNotNone(self.store.get_trend("예시 키워드", "최근 1년", ("기준", "예시"), today="2026-11-18", max_age_days=8))
        for name, reading in (("조회 불가", trend.UNAVAILABLE), ("조회 안 함", trend.NOT_QUERIED), ("자료 부족", trend.TrendReading(True, "insufficient", None, None, (), None, "insufficient"))):
            with self.subTest(case=name):
                self.assertFalse(self.store.put_trend("다른 키워드", reading, now=NOW))
        self.assertEqual(raw(self.path, "SELECT COUNT(*) FROM trend_cache"), [(1,)])

    def test_the_trend_cache_updates_the_same_key_and_refuses_wrong_input(self):
        self.store.put_trend("예시 키워드", self.reading(), now=NOW)
        self.store.put_trend("예시 키워드", self.reading(trend_ratio=20, trend_status="falling"), now=NOW)
        self.assertEqual(raw(self.path, "SELECT COUNT(*) FROM trend_cache"), [(1,)])
        self.assertEqual(self.store.get_trend("예시 키워드", "최근 1년", ("기준", "예시"), today="2026-11-10").trend_ratio, 20)
        with self.assertRaises(ValueError):
            self.store.put_trend("예시 키워드", {"a": 1}, now=NOW)
        with self.assertRaises(ValueError):
            self.store.get_trend("예시 키워드", "최근 1년", ("기준", "예시"), today="어제")
        for days in (-1, True, "7", 4000):
            with self.assertRaises(ValueError):
                self.store.get_trend("예시 키워드", "최근 1년", ("기준", "예시"), today="2026-11-10", max_age_days=days)

    def test_links_are_saved_per_candidate_and_must_match_the_stored_candidate(self):
        candidate = self.store.load_candidate("cid-001")
        link = CandidateLink.of(candidate)
        self.store.save_link(link, now=NOW)
        self.assertEqual(self.store.load_link("cid-001"), link)
        self.assertEqual(raw(self.path, "SELECT draft_plan_id, legacy_candidate_id FROM candidate_links"), [(None, None)], "초안 계획 번호는 정하지 않았다 — NULL")
        updated = CandidateLink.of(candidate, legacy_candidate_id="legacy-1")
        self.store.save_link(updated, now="2026-11-11T00:00:00Z")
        self.assertEqual((self.store.load_link("cid-001"), len(self.store.links())), (updated, 1))
        self.assertIsNone(self.store.load_link("cid-002"))
        wrong = dataclasses.replace(link, seed_id="other-seed")
        self.assertEqual(code_of(self.store.save_link, wrong, now=NOW), "CANDIDATE_INVALID")
        ghost = CandidateLink(engine_candidate_id="cid-404", legacy_candidate_id=None, draft_plan_id=None, source_topic_id=None, seed_id=None, channel="naver_a")
        self.assertEqual(code_of(self.store.save_link, ghost, now=NOW), "TOPIC_CANDIDATE_NOT_FOUND")
        self.assertEqual(code_of(self.store.save_link, {"a": 1}, now=NOW), "CANDIDATE_INVALID")

    def test_the_provenance_snapshot_is_kept_once_and_never_replaced(self):
        first = Provenance.of(self.store.load_candidate("cid-001"))
        self.assertTrue(self.store.save_provenance("cid-001", first, taken_at=NOW))
        changed = dataclasses.replace(first, selection_reasons=("다른 이유",))
        self.assertFalse(self.store.save_provenance("cid-001", changed, taken_at=NOW), "같은 시각의 두 번째 스냅샷은 처음 것을 바꾸지 못한다")
        self.assertTrue(self.store.save_provenance("cid-001", changed, taken_at="2026-11-11T00:00:00Z"))
        got = self.store.provenance_history("cid-001")
        self.assertEqual([(when, item.selection_reasons) for when, item in got], [(NOW, first.selection_reasons), ("2026-11-11T00:00:00Z", ("다른 이유",))])
        self.assertEqual(code_of(self.store.save_provenance, "cid-404", first, taken_at=NOW), "TOPIC_CANDIDATE_NOT_FOUND")
        self.assertEqual(code_of(self.store.save_provenance, "cid-001", {"a": 1}, taken_at=NOW), "CANDIDATE_INVALID")

    def test_the_history_ledger_keeps_what_was_read_and_keeps_the_first_seen_time(self):
        posts = [hs.HistoryRecord(channel="naver_a", title="예시 이력 글 하나", ref="p1", date="2026-10-01", origin="naver_items"),
                 hs.HistoryRecord(channel="github_pages", title="예시 사이트 글", ref="2026-10-02-KR-1", date="2026-10-02", origin="front_matter", keywords=("가", "나")),
                 hs.HistoryRecord(channel="blogger_en", title="Example post without a number", date="2026-09-01", origin="history_entries")]
        self.assertEqual(self.store.sync_history(posts, now=NOW), 3)
        self.store.sync_history([dataclasses.replace(posts[0], title="예시 이력 글 하나(고침)")], now="2026-11-11T00:00:00Z")
        got = self.store.history_records()
        self.assertEqual([(item.channel, item.title) for item in got], [("github_pages", "예시 사이트 글"), ("blogger_en", "Example post without a number"), ("naver_a", "예시 이력 글 하나(고침)")])
        self.assertEqual(got[0].keywords, ("가", "나"))
        self.assertEqual(raw(self.path, "SELECT first_seen_at, last_seen_at FROM history_ledger WHERE ref = 'p1'"), [(NOW, "2026-11-11T00:00:00Z")])
        self.assertEqual([item.channel for item in self.store.history_records("naver_a")], ["naver_a"])
        self.assertEqual(self.store.sync_history(posts, now=NOW), 3)
        self.assertEqual(raw(self.path, "SELECT COUNT(*) FROM history_ledger"), [(3,)], "같은 기록을 다시 올려도 겹치지 않는다")
        self.assertNotEqual(topic_store.history_key(posts[0]), topic_store.history_key(posts[2]))
        self.assertEqual(topic_store.history_key(posts[0]), "ref:p1")
        self.assertTrue(topic_store.history_key(posts[2]).startswith("id:"))
        self.assertEqual(code_of(self.store.sync_history, [{"a": 1}], now=NOW), "CANDIDATE_INVALID")
        self.assertEqual(code_of(self.store.history_records, "nowhere"), "CANDIDATE_INVALID")

    def test_check_finds_each_kind_of_tampering(self):
        self.assertEqual(self.store.check(), [])
        connection = sqlite3.connect(str(self.path))
        self.addCleanup(connection.close)
        with connection:
            connection.execute("UPDATE candidates SET channel = 'naver_b' WHERE candidate_id = 'cid-002'")
        self.assertTrue(any("cid-002" in problem and "찾기용 칸" in problem for problem in self.store.check()))
        with connection:
            connection.execute("UPDATE candidates SET channel = 'naver_a' WHERE candidate_id = 'cid-002'")
            connection.execute("INSERT INTO hold_box (candidate_id, entered_at, expires_at, left_at) VALUES ('cid-002', ?, ?, NULL)", (CREATED, DAY90))
        self.assertTrue(any("보류함 cid-002" in problem for problem in self.store.check()), "구간이 보류가 아닌 후보가 보류함에 있다")
        with connection:
            connection.execute("DELETE FROM hold_box")
            connection.execute("UPDATE score_snapshots SET data = '{}' WHERE candidate_id = 'cid-001'")
        self.assertTrue(any("score_snapshots cid-001" in problem for problem in self.store.check()))


class BackupPrimitivesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "topic_engine.db"
        self.store = TopicStore.open(self.path)
        self.addCleanup(self.store.close)
        self.store.add_candidates(lambda existing: [cand(1), hold_cand(2)], now=NOW)

    def test_a_copy_is_a_complete_valid_store_even_while_open_and_read_only(self):
        copy = Path(self.tmp.name) / "copy.db"
        self.store.copy_to(copy)
        with TopicStore.open(copy, migrate=False) as other:
            self.assertEqual(([c.candidate_id for c in other.list_candidates()], other.check()), (["cid-001", "cid-002"], []))
        read_only_copy = Path(self.tmp.name) / "copy2.db"
        with TopicStore.open(self.path, migrate=False) as reader:
            reader.copy_to(read_only_copy)
        with TopicStore.open(read_only_copy, migrate=False) as other:
            self.assertEqual(other.count(), 2)

    def test_restore_from_replaces_the_content_and_refuses_bad_backups_before_touching_anything(self):
        copy = Path(self.tmp.name) / "copy.db"
        self.store.copy_to(copy)
        self.store.add_candidates(lambda existing: [cand(3)], now=NOW)
        self.store.restore_from(copy)
        self.assertEqual([c.candidate_id for c in self.store.list_candidates()], ["cid-001", "cid-002"])
        before = [c.candidate_id for c in self.store.list_candidates()]
        foreign, noise, newer = (Path(self.tmp.name) / name for name in ("foreign.db", "noise.db", "newer.db"))
        with connect(foreign) as connection:
            connection.execute("CREATE TABLE other (x TEXT)")
        noise.write_bytes(os.urandom(2048))
        self.store.copy_to(newer)
        with connect(newer) as connection:
            connection.execute("PRAGMA user_version = 9")
        for path in (foreign, noise, newer, Path(self.tmp.name) / "missing.db"):
            with self.subTest(file=path.name):
                self.assertEqual(code_of(self.store.restore_from, path), "TOPIC_BACKUP_INVALID")
                self.assertEqual([c.candidate_id for c in self.store.list_candidates()], before)

    def test_a_backup_with_a_foreign_name_tag_or_a_changed_shape_is_refused_whole_and_the_live_file_is_not_touched(self):
        names = ("tag.db", "missing_table.db", "changed_columns.db")
        tag, missing_table, changed_columns = (Path(self.tmp.name) / name for name in names)
        for target in (tag, missing_table, changed_columns):
            self.store.copy_to(target)
        with connect(tag) as connection:
            connection.execute("PRAGMA application_id = 12345")                  # 판 번호·구조·표 모양은 멀쩡하고 이름표만 다르다
        with connect(missing_table) as connection:
            connection.execute("DROP TABLE history_ledger")                       # 이름표·판 번호·구조는 멀쩡하고 표 하나가 없다
        with connect(changed_columns) as connection:
            connection.execute("ALTER TABLE hold_box RENAME COLUMN left_at TO gone_at")
        before = (digest(self.path), [item.candidate_id for item in self.store.list_candidates()])
        for target in (tag, missing_table, changed_columns):
            with self.subTest(file=target.name):
                self.assertEqual(code_of(self.store.restore_from, target), "TOPIC_BACKUP_INVALID", "바꾸기 전에 거절해야 한다(바꾼 뒤 열기 검사에서 걸리면 이미 늦다)")
                self.assertEqual((digest(self.path), [item.candidate_id for item in self.store.list_candidates()]), before)


if __name__ == "__main__":
    unittest.main()
