"""백업에서 되돌릴 보관함 파일(SQLite)의 '구조' 검사(`content/schema_guard.py`) 시험 — 조작한 백업의 트리거·뷰·모르는 표와 색인이 통째 복사로 들어오지 못하게 하는 순수 검사(L8, 결정 D-554).

지키는 것:
  1) 앱이 스스로 만든 파일은 어느 판(옛 판·올린 판)이든 한 개체도 걸리지 않는다 — 정상 백업은 한 글자도 다르게 되돌려진다(오탐 0).
  2) 앱이 만들지 않는 개체는 종류별로 걸린다: 트리거 · 뷰 · 모르는 표 · 가상 표 · 모르는 색인 · 정해 둔 색인과 다른 모양 · 숨은 열 · 너무 많은 개체 — 적대 입력(이름에 경로·따옴표·제어 문자·아주 긴 이름, 겹겹이 쌓은 뷰, 아주 큰 SQL)을 모두 본다.
  3) 결과는 고정된 종류 이름뿐이다 — 조작한 파일의 개체 이름·SQL 글이 문구·결과·로그 어디에도 되풀이되지 않는다(카나리아 이름).
  4) 읽기만 한다 — 읽기 전용 연결로 돌고 파일 바이트가 그대로이며, 모듈은 표준 라이브러리만 가져오는 잎이고 검사를 건너뛰는 인자가 없다.
네트워크·실제 비밀 없이 돈다. 가짜 이름은 `CANARY_` 로 시작하는 글을 실행할 때 이어 붙여 만든다.
"""
import ast
import contextlib
import inspect
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from chanceblog_desktop.content import schema_guard as sg  # noqa: E402
from chanceblog_desktop.content import store as store_module  # noqa: E402
from chanceblog_desktop.content.store import SCHEMA_STATEMENTS, Store, _read_only_uri  # noqa: E402
from chanceblog_desktop.topicdb import store as topic_module  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore  # noqa: E402

ROOT = HERE.parent
MODULE = ROOT / "src" / "chanceblog_desktop" / "content" / "schema_guard.py"
TOPIC_V1 = topic_module._SCHEMA[:-len(topic_module._NEW_TABLES)]                  # 판 1 의 문장들(표 일곱 + 색인 둘)
STORE_V1 = SCHEMA_STATEMENTS[:4]                                                    # 판 1 의 문장들(표 셋 + 색인 하나) — 판 2 에서 후보 표와 색인 둘이 더해졌다
CANARY = "CANARY_" + "n4m3"                                                         # 가짜 개체 이름 — 어느 문구에도 되풀이되면 안 된다


def read_only(path):
    return sqlite3.connect(_read_only_uri(Path(path)), uri=True)


def build(path, statements, *tampering):
    """`statements` 로 파일을 만들고 `tampering` 의 문장을 더 실행한다(조작한 백업을 흉내 낸다) → 경로."""
    with contextlib.closing(sqlite3.connect(str(path))) as db:
        for statement in (*statements, *tampering):
            db.execute(statement)
        db.commit()
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.count = 0

    def file(self, statements, *tampering, name=None):
        self.count += 1
        return build(self.tmp / (name or f"f{self.count}.db"), statements, *tampering)

    def kinds(self, path, statements):
        with contextlib.closing(read_only(path)) as db:
            return sg.foreign_kinds(db, statements)


class ReferenceTest(Base):
    def test_the_apps_own_fresh_files_have_no_foreign_object(self):
        content = self.tmp / "content.db"
        with Store.open(content):
            pass
        engine = self.tmp / "engine.db"
        with TopicStore.open(engine):
            pass
        self.assertEqual(self.kinds(content, SCHEMA_STATEMENTS), ())
        self.assertEqual(self.kinds(engine, TopicStore.SCHEMA), ())

    def test_old_version_files_are_subsets_of_the_reference(self):
        self.assertEqual(self.kinds(self.file(STORE_V1), SCHEMA_STATEMENTS), (), "판 1 글 보관함(후보 표·색인 둘이 아직 없다)")
        self.assertEqual(self.kinds(self.file(TOPIC_V1), TopicStore.SCHEMA), (), "판 1 주제 엔진 보관함(표 셋이 아직 없다)")

    def test_a_file_upgraded_by_the_apps_own_migration_is_not_flagged(self):
        path = self.file(STORE_V1)
        with contextlib.closing(sqlite3.connect(str(path))) as db:
            db.execute(f"PRAGMA application_id = {store_module.APPLICATION_ID}")
            db.execute("PRAGMA user_version = 1")
            db.commit()
        with Store.open(path):                                                    # 열면서 판 2 로 올린다(후보 표와 색인 둘이 더해진다)
            pass
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ())
        engine = self.file(TOPIC_V1)
        with contextlib.closing(sqlite3.connect(str(engine))) as db:
            db.execute(f"PRAGMA application_id = {topic_module.APPLICATION_ID}")
            db.execute("PRAGMA user_version = 1")
            db.commit()
        with TopicStore.open(engine):
            pass
        self.assertEqual(self.kinds(engine, TopicStore.SCHEMA), ())

    def test_a_file_with_the_planner_statistics_tables_is_not_flagged(self):
        """`ANALYZE`·`PRAGMA optimize` 가 SQLite 스스로 만드는 `sqlite_stat1` 은 정상 파일에도 있을 수 있다(앱은 만들지 않는다)."""
        path = self.file(SCHEMA_STATEMENTS, "INSERT INTO projects VALUES ('p1', 't', 1, 'a', 'b', '{}')", "ANALYZE")
        with contextlib.closing(read_only(path)) as db:
            self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_stat1'").fetchone(), "표본이 정말 통계 표를 만들었다")
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ())

    def test_the_reference_is_built_from_the_statements_so_a_new_version_needs_no_list_edit(self):
        extra = (*SCHEMA_STATEMENTS, "CREATE TABLE brand_new_v3 (x TEXT PRIMARY KEY)", "CREATE INDEX brand_new_v3_x ON brand_new_v3 (x)")
        path = self.file(extra)
        self.assertEqual(self.kinds(path, extra), (), "그 문장으로 만든 파일은 그 문장이 기준이면 깨끗하다")
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("table", "index"), "지금 기준에는 없는 표와 색인이다")

    def test_the_same_statements_in_any_container_give_the_same_reference(self):
        path = self.file(SCHEMA_STATEMENTS)
        self.assertEqual(self.kinds(path, list(SCHEMA_STATEMENTS)), ())
        self.assertEqual(self.kinds(path, tuple(SCHEMA_STATEMENTS)), ())


class TriggerAndViewTest(Base):
    """조작한 백업의 핵심 — 저장할 때마다 몰래 도는 트리거와 표 행세를 하는 뷰."""

    def test_a_trigger_on_every_table_of_both_stores_is_found(self):
        for statements, tables in ((SCHEMA_STATEMENTS, ("projects", "revisions", "drafts", "candidates")), (TopicStore.SCHEMA, ("candidates", "hold_box", "history_ledger", "trend_cache"))):
            for table in tables:
                for when in ("AFTER INSERT", "BEFORE UPDATE", "AFTER DELETE"):
                    with self.subTest(table=table, when=when):
                        path = self.file(statements, f"CREATE TRIGGER x_{table} {when} ON {table} BEGIN SELECT 1; END")
                        self.assertEqual(self.kinds(path, statements), ("trigger",))

    def test_a_trigger_that_rewrites_or_deletes_data_is_found(self):
        bodies = ("UPDATE drafts SET text = text || 'x'", "DELETE FROM projects", "INSERT INTO drafts VALUES ('a', 'b', 'c')", "UPDATE projects SET data = '{}'")
        for body in bodies:
            with self.subTest(body=body):
                path = self.file(SCHEMA_STATEMENTS, f"CREATE TRIGGER evil AFTER INSERT ON projects BEGIN {body}; END")
                self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("trigger",))

    def test_a_trigger_chain_is_found_once_as_a_trigger(self):
        path = self.file(SCHEMA_STATEMENTS, "CREATE TRIGGER a AFTER INSERT ON projects BEGIN INSERT INTO drafts VALUES ('x', 'y', 'z'); END",
                         "CREATE TRIGGER b AFTER INSERT ON drafts BEGIN UPDATE projects SET title = title; END")
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("trigger",))

    def test_a_plain_view_is_found(self):
        path = self.file(SCHEMA_STATEMENTS, "CREATE VIEW everything AS SELECT project_id, data FROM projects")
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("view",))

    def test_views_stacked_twenty_deep_are_found_without_trouble(self):
        statements = ["CREATE VIEW v0 AS SELECT project_id FROM projects"] + [f"CREATE VIEW v{number} AS SELECT project_id FROM v{number - 1}" for number in range(1, 20)]
        path = self.file(SCHEMA_STATEMENTS, *statements)
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("view",))

    def test_a_view_posing_as_a_table_with_the_same_columns_is_found(self):
        """`pragma_table_info` 는 뷰의 열도 돌려줘서 열 이름 확인만으로는 진짜 표와 가를 수 없다 — 뷰 이름이 정본의 표 이름이어도 걸린다."""
        for name, columns, source_columns in (("projects", "project_id, title, revision, created_at, updated_at, data", "project_id, title, revision, created_at, updated_at, data"),
                                              ("drafts", "project_id, text, saved_at", "project_id, text, saved_at")):
            with self.subTest(view=name):
                hidden = "hidden_" + name
                path = self.file((), f"CREATE TABLE {hidden} ({columns})", f"CREATE VIEW {name} AS SELECT {source_columns} FROM {hidden}",
                                 f"CREATE TRIGGER w INSTEAD OF INSERT ON {name} BEGIN INSERT INTO {hidden} VALUES ({', '.join('new.' + c.strip() for c in columns.split(','))}); END")
                found = self.kinds(path, SCHEMA_STATEMENTS)
                self.assertIn("view", found)
                self.assertIn("trigger", found)
                self.assertIn("table", found, "진짜 데이터가 든 숨은 표")

    def test_an_instead_of_trigger_on_a_view_reports_both(self):
        path = self.file(SCHEMA_STATEMENTS, "CREATE VIEW alias AS SELECT * FROM drafts", "CREATE TRIGGER t INSTEAD OF DELETE ON alias BEGIN SELECT 1; END")
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("trigger", "view"))

    def test_names_with_paths_quotes_control_characters_and_great_length_are_found_and_never_repeated(self):
        hostile = ("../../" + CANARY, 'quo"te' + CANARY, "tab\t" + CANARY, "line\nbreak" + CANARY, "nul" + chr(1) + CANARY, "한글" + CANARY, "x" * 400 + CANARY, "back\\slash" + CANARY, "semi;colon" + CANARY)
        for name in hostile:
            quoted = '"' + name.replace('"', '""') + '"'
            for statement, expected in ((f"CREATE TRIGGER {quoted} AFTER INSERT ON drafts BEGIN SELECT 1; END", ("trigger",)), (f"CREATE VIEW {quoted} AS SELECT 1", ("view",)),
                                        (f"CREATE TABLE {quoted} (x)", ("table",)), (f"CREATE INDEX {quoted} ON drafts (text)", ("index",))):
                with self.subTest(name=name[:20], statement=statement[:14]):
                    found = self.kinds(self.file(SCHEMA_STATEMENTS, statement), SCHEMA_STATEMENTS)
                    self.assertEqual(found, expected)
                    self.assertNotIn(CANARY, repr(found) + sg.describe(found))

    def test_a_huge_sql_text_does_not_slow_the_check_and_is_never_read_whole(self):
        padding = "x" * 800_000                                                       # 80만 글자짜리 뷰 정의(주석으로 키운다 — SQL 글에 그대로 남는다)
        path = self.file(SCHEMA_STATEMENTS, f"CREATE VIEW big AS SELECT 1 /* {padding} */")
        started = time.monotonic()
        found = self.kinds(path, SCHEMA_STATEMENTS)
        self.assertEqual(found, ("view",))
        self.assertLess(time.monotonic() - started, 5.0)


class TableAndIndexTest(Base):
    def test_an_unknown_table_is_found(self):
        for statement in ("CREATE TABLE evil (x TEXT)", "CREATE TABLE evil2 AS SELECT * FROM drafts", "CREATE TABLE evil3 (id INTEGER PRIMARY KEY AUTOINCREMENT, x)"):
            with self.subTest(statement=statement):
                self.assertEqual(self.kinds(self.file(SCHEMA_STATEMENTS, statement), SCHEMA_STATEMENTS), ("table",), "AUTOINCREMENT 가 만드는 sqlite_sequence 는 정상 표로 본다")

    def test_a_table_with_the_right_name_in_the_wrong_case_is_found(self):
        """SQLite 는 대소문자를 가리지 않아 `PROJECTS` 가 `projects` 열 확인을 통과한다 — 이름이 정확히 같아야 한다."""
        path = self.file((), "CREATE TABLE PROJECTS (project_id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL)")
        self.assertIn("table", self.kinds(path, SCHEMA_STATEMENTS))

    def test_a_virtual_table_is_found_even_under_a_known_name(self):
        for module, arguments in (("fts5", "project_id, title, revision, created_at, updated_at, data"), ("fts4", "project_id, title, revision, created_at, updated_at, data"), ("rtree", "id, minx, maxx, miny, maxy")):
            with self.subTest(module=module):
                try:
                    plain = self.file(SCHEMA_STATEMENTS, f"CREATE VIRTUAL TABLE searchable USING {module}({arguments})")
                except sqlite3.OperationalError:
                    self.skipTest(f"이 SQLite 에는 {module} 이 없다")
                self.assertIn("virtual", self.kinds(plain, SCHEMA_STATEMENTS))
                shadow = self.file((), f"CREATE VIRTUAL TABLE projects USING {module}({arguments})")
                self.assertIn("virtual", self.kinds(shadow, SCHEMA_STATEMENTS), "정본의 표 이름을 쓰는 가상 표")

    def test_an_extra_index_is_found_whether_unique_partial_or_on_an_expression(self):
        for statement in ("CREATE INDEX extra_i ON projects (title)", "CREATE UNIQUE INDEX extra_u ON projects (title)", "CREATE INDEX extra_p ON drafts (text) WHERE saved_at > 'a'",
                          "CREATE INDEX extra_e ON drafts (lower(text))"):
            with self.subTest(statement=statement):
                self.assertEqual(self.kinds(self.file(SCHEMA_STATEMENTS, statement), SCHEMA_STATEMENTS), ("index",))

    def test_a_unique_constraint_added_to_a_known_table_is_found_through_its_automatic_index(self):
        """열에 `UNIQUE` 한 줄이면 이후 같은 제목의 글 저장이 모두 막힌다 — 이름이 있는 색인이 아니라 SQLite 가 만드는 기본 색인으로 나타난다."""
        path = self.file((), "CREATE TABLE projects (project_id TEXT PRIMARY KEY, title TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL)")
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("index",))

    def test_a_known_index_name_with_a_different_shape_is_found(self):
        base = [statement for statement in SCHEMA_STATEMENTS if "candidates_status" not in statement]
        variants = {
            "unique": "CREATE UNIQUE INDEX candidates_status ON candidates (status, updated_at DESC)",
            "partial": "CREATE INDEX candidates_status ON candidates (status, updated_at DESC) WHERE status = 'NEW'",
            "other columns": "CREATE INDEX candidates_status ON candidates (keyword_key, updated_at)",
            "fewer columns": "CREATE INDEX candidates_status ON candidates (status)",
            "expression": "CREATE INDEX candidates_status ON candidates (lower(status), updated_at)",
        }
        for label, statement in variants.items():
            with self.subTest(label=label):
                self.assertEqual(self.kinds(self.file((*base, statement)), SCHEMA_STATEMENTS), ("index_shape",))

    def test_a_known_index_name_on_another_table_is_found(self):
        base = [statement for statement in SCHEMA_STATEMENTS if "candidates_status" not in statement]
        path = self.file((*base, "CREATE INDEX candidates_status ON drafts (text)"))
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("index",))

    def test_a_generated_or_hidden_column_added_to_a_known_table_is_found(self):
        """`table_info` 는 생성 열을 보여 주지 않아 열 이름 확인이 못 본다 — `table_xinfo` 로 본다."""
        for column in ("g TEXT AS (project_id || 'x')", "g TEXT GENERATED ALWAYS AS (text) STORED"):
            with self.subTest(column=column):
                statement = f"CREATE TABLE drafts (project_id TEXT PRIMARY KEY, text TEXT NOT NULL, saved_at TEXT NOT NULL, {column})"
                base = [item for item in SCHEMA_STATEMENTS if not item.startswith("CREATE TABLE drafts")]
                path = self.file((*base, statement))
                self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("hidden_column",))

    def test_too_many_objects_stop_the_check_without_listing_them(self):
        path = self.file(SCHEMA_STATEMENTS, *[f"CREATE TABLE t{number} (x)" for number in range(sg.MAX_OBJECTS + 5)])
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("too_many",))

    def test_the_limit_is_exact_at_the_boundary(self):
        with contextlib.closing(sqlite3.connect(":memory:")) as db:                      # 정본 개체 수(표·색인·기본 색인) — 상한은 이보다 훨씬 넉넉해야 한다
            for statement in SCHEMA_STATEMENTS:
                db.execute(statement)
            base = db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        self.assertEqual(sg.MAX_OBJECTS, 128, "문서·결정 기록이 128개라고 적었다")
        self.assertLess(base * 4, sg.MAX_OBJECTS)
        room = sg.MAX_OBJECTS - base
        at_limit = self.file(SCHEMA_STATEMENTS, *[f"CREATE VIEW w{number} AS SELECT 1" for number in range(room)])
        self.assertEqual(self.kinds(at_limit, SCHEMA_STATEMENTS), ("view",), "딱 상한까지는 개체를 하나씩 본다")
        over = self.file(SCHEMA_STATEMENTS, *[f"CREATE VIEW w{number} AS SELECT 1" for number in range(room + 1)])
        self.assertEqual(self.kinds(over, SCHEMA_STATEMENTS), ("too_many",), "하나만 넘어도 더 훑지 않는다")

    def test_all_kinds_together_come_out_in_the_fixed_order_of_danger(self):
        path = self.file(SCHEMA_STATEMENTS, "CREATE TABLE evil (x)", "CREATE VIEW v AS SELECT 1", "CREATE INDEX extra ON drafts (text)", "CREATE TRIGGER t AFTER INSERT ON drafts BEGIN SELECT 1; END")
        self.assertEqual(self.kinds(path, SCHEMA_STATEMENTS), ("trigger", "view", "table", "index"))
        self.assertEqual(sg.KIND_ORDER[:2], ("trigger", "view"), "가장 위험한 것이 먼저다")


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class OddObjectTest(Base):
    """진짜 파일로는 만들기 어려운 개체 — 개체 목록만 바꿔치기한 연결로 본다(나머지 질문은 진짜 연결이 답한다)."""

    class Tampered:
        def __init__(self, real, rows):
            self.real, self.rows = real, rows

        def execute(self, sql, params=()):
            if "FROM sqlite_master" in sql:
                return FakeRows(self.rows)
            return self.real.execute(sql, params)

    def check(self, rows):
        with contextlib.closing(sqlite3.connect(":memory:")) as real:
            for statement in SCHEMA_STATEMENTS:
                real.execute(statement)
            return sg.foreign_kinds(self.Tampered(real, rows), SCHEMA_STATEMENTS)

    def test_an_object_of_an_unknown_type_is_refused(self):
        self.assertEqual(self.check([("synonym", "x", "x", "CREATE SYNONYM x")]), ("other",))
        self.assertEqual(self.check([("", "x", "x", None)]), ("other",))
        self.assertEqual(self.check([(None, "x", "x", None)]), ("other",))

    def test_a_table_without_any_sql_text_is_refused_unless_it_is_an_internal_one(self):
        self.assertEqual(self.check([("table", "projects", "projects", None)]), ("table",))
        self.assertEqual(self.check([("table", "sqlite_stat1", "sqlite_stat1", "CREATE TABLE sqlite_stat1(tbl,idx,stat)")]), ())

    def test_an_internal_name_is_exempt_only_with_a_plain_create_table_head_and_only_those_five_names(self):
        """독립 검증 S 의 SP-3·Q 의 QG4 — 내부 이름이면 머리를 안 보고 통과시켜 그 이름의 가상 표가 복원을 지났다. 이제 머리가 평범한 `CREATE TABLE` 일 때만 면제하고 면제 이름은 정확히 다섯이다."""
        self.assertEqual(sorted(sg.INTERNAL_TABLES), ["sqlite_sequence", "sqlite_stat1", "sqlite_stat2", "sqlite_stat3", "sqlite_stat4"])
        for name in sorted(sg.INTERNAL_TABLES):
            with self.subTest(name=name):
                self.assertEqual(self.check([("table", name, name, f"CREATE TABLE {name}(a,b)")]), (), "정상 통계 표는 오탐하지 않는다")
                self.assertEqual(self.check([("table", name, name, f"CREATE VIRTUAL TABLE {name} USING fts5(a)")]), ("virtual",), "그 이름의 가상 표는 거절한다")
                self.assertEqual(self.check([("table", name, name, None)]), ("table",), "SQL 글이 없는 것은 거절한다")
        for name in ("sqlite_zz", "sqlite_stat5", "sqlite_master2", "SQLITE_STAT1x"):
            with self.subTest(other=name):
                self.assertEqual(self.check([("table", name, name, f"CREATE TABLE {name}(a)")]), ("table",), "정확히 그 다섯 이름만 면제한다")

    def test_a_real_virtual_table_named_like_an_internal_table_is_refused(self):
        path = self.file(SCHEMA_STATEMENTS)
        try:
            with contextlib.closing(sqlite3.connect(str(path))) as db:
                db.execute("PRAGMA writable_schema = ON")
                db.execute("INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql) VALUES ('table', 'sqlite_stat1', 'sqlite_stat1', 0, 'CREATE VIRTUAL TABLE sqlite_stat1 USING fts5(a)')")
                db.commit()
        except sqlite3.Error:
            self.skipTest("이 SQLite 는 개체 목록 직접 고치기를 막는다")
        try:
            found = self.kinds(path, SCHEMA_STATEMENTS)
        except sqlite3.Error:
            return                                                    # 이 SQLite 가 읽는 순간 깨진 파일로 거절하면 그것도 거절이다(가상 표 생성자가 없다)
        self.assertEqual(found, ("virtual",))

    def test_the_prefix_check_ignores_case_and_leading_spaces_only(self):
        self.assertEqual(self.check([("table", "projects", "projects", "  create table projects(x)")]), ())
        self.assertEqual(self.check([("table", "projects", "projects", "CREATE TEMP TABLE projects(x)")]), ("table",))
        self.assertEqual(self.check([("table", "projects", "projects", "create virtual table projects using fts5(x)")]), ("virtual",))
        self.assertEqual(self.check([("table", "projects", "projects", "")]), ("table",))

    def test_an_automatic_index_of_an_unknown_table_or_with_an_unknown_name_is_refused(self):
        self.assertEqual(self.check([("index", "sqlite_autoindex_projects_1", "projects", None)]), ())
        self.assertEqual(self.check([("index", "sqlite_autoindex_projects_2", "projects", None)]), ("index",))
        self.assertEqual(self.check([("index", "sqlite_autoindex_evil_1", "evil", None)]), ("index",))
        self.assertEqual(self.check([("index", "sqlite_autoindex_projects_1", "evil", None)]), ("index",), "기본 색인 이름이 같아도 딸린 표가 정본의 표여야 한다")


class EncodingTest(Base):
    """글자 인코딩(L8 독립 검증 S 의 SP-1) — UTF-16 보관함은 구조가 정상이어도 통째 복사 '뒤에야' SQLite 가 인코딩 불일치로 실패해 지금 보관함이 비워진 채 남았다(시작점에서도 같다). UTF-8 이 아니면 거절한다."""

    ENCODINGS = ("UTF-16le", "UTF-16be")

    def utf16(self, statements, encoding):
        self.count += 1
        return build(self.tmp / f"u{self.count}.db", (f"PRAGMA encoding = '{encoding}'", *statements))

    def test_a_utf16_file_with_a_perfectly_normal_structure_is_refused_for_both_storages_and_both_byte_orders(self):
        for statements, label in ((SCHEMA_STATEMENTS, "content"), (TopicStore.SCHEMA, "engine")):
            for encoding in self.ENCODINGS:
                with self.subTest(storage=label, encoding=encoding):
                    path = self.utf16(statements, encoding)
                    with contextlib.closing(read_only(path)) as db:
                        self.assertIn(db.execute("PRAGMA encoding").fetchone()[0], ("UTF-16le", "UTF-16be"), "시험 파일이 정말 UTF-16 이다")
                    self.assertEqual(self.kinds(path, statements), ("encoding",))

    def test_utf8_files_are_untouched_including_an_empty_file_and_the_old_version_files(self):
        empty = self.tmp / "empty.db"
        empty.write_bytes(b"")
        for path, statements in ((self.file(SCHEMA_STATEMENTS), SCHEMA_STATEMENTS), (self.file(TopicStore.SCHEMA), TopicStore.SCHEMA), (empty, SCHEMA_STATEMENTS),
                                 (self.file(STORE_V1), SCHEMA_STATEMENTS), (self.file(TOPIC_V1), TopicStore.SCHEMA), (self.file((f"PRAGMA encoding = 'UTF-8'", *SCHEMA_STATEMENTS)), SCHEMA_STATEMENTS)):
            with self.subTest(path=path.name):
                self.assertEqual(self.kinds(path, statements), ())

    def test_the_encoding_is_reported_together_with_other_findings_in_the_fixed_order(self):
        path = self.utf16(SCHEMA_STATEMENTS, "UTF-16le")
        with contextlib.closing(sqlite3.connect(str(path))) as db:
            db.execute("CREATE TRIGGER t AFTER INSERT ON drafts BEGIN SELECT 1; END")
            db.commit()
        found = self.kinds(path, SCHEMA_STATEMENTS)
        self.assertEqual(found, tuple(kind for kind in sg.KIND_ORDER if kind in ("trigger", "encoding")))
        self.assertEqual(found, ("trigger", "encoding"))
        self.assertIn(sg.KIND_TEXT["encoding"], sg.describe(found))


class ReadOnlyAndMessageTest(Base):
    def test_the_check_runs_on_a_read_only_connection_and_leaves_the_file_byte_for_byte(self):
        path = self.file(SCHEMA_STATEMENTS, "CREATE TRIGGER t AFTER INSERT ON drafts BEGIN SELECT 1; END", "CREATE VIEW v AS SELECT 1")
        before = path.read_bytes()
        with contextlib.closing(read_only(path)) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("CREATE TABLE writes_must_fail (x)")
            self.assertEqual(sg.foreign_kinds(db, SCHEMA_STATEMENTS), ("trigger", "view"))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual({entry.name for entry in self.tmp.iterdir()}, {path.name}, "짝 파일(-journal·-wal)도 남기지 않는다")

    def test_a_file_that_is_not_a_database_raises_the_sqlite_error_for_the_caller_to_map(self):
        junk = self.tmp / "junk.db"
        junk.write_bytes(b"this is not a database " * 200)
        with contextlib.closing(read_only(junk)) as db:
            with self.assertRaises(sqlite3.DatabaseError):
                sg.foreign_kinds(db, SCHEMA_STATEMENTS)

    def test_the_description_is_the_fixed_words_joined_and_empty_for_nothing(self):
        self.assertEqual(sg.describe(()), "")
        self.assertEqual(sg.describe(("trigger", "view")), "트리거·뷰")
        self.assertEqual(sg.describe(sg.KIND_ORDER), "·".join(sg.KIND_TEXT[kind] for kind in sg.KIND_ORDER))
        self.assertEqual(set(sg.KIND_TEXT), set(sg.KIND_ORDER))
        with self.assertRaises(KeyError):
            sg.describe(("not-a-kind",))

    def test_no_message_or_result_carries_the_text_of_a_hostile_file(self):
        path = self.file(SCHEMA_STATEMENTS, f'CREATE TRIGGER "{CANARY}trigger" AFTER INSERT ON drafts BEGIN SELECT \'{CANARY}body\'; END', f'CREATE VIEW "{CANARY}view" AS SELECT \'{CANARY}text\'',
                         f'CREATE TABLE "{CANARY}table" ("{CANARY}column")', f'CREATE INDEX "{CANARY}index" ON drafts (text)')
        found = self.kinds(path, SCHEMA_STATEMENTS)
        self.assertEqual(found, ("trigger", "view", "table", "index"))
        for text in (repr(found), sg.describe(found), str(sg.KIND_TEXT)):
            self.assertNotIn(CANARY, text)


class SourceRulesTest(unittest.TestCase):
    def test_the_module_is_a_leaf_that_imports_only_the_standard_library_it_needs(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "상대 import 가 없다 — 이 앱의 다른 모듈을 가져오지 않는다")
                imported.add(node.module)
        self.assertEqual(imported, {"__future__", "sqlite3", "contextlib", "functools"})

    def test_the_only_connection_it_opens_is_in_memory_and_it_never_writes_or_opens_files(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        connects = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "sqlite3.connect"]
        self.assertEqual([ast.unparse(node.args[0]) for node in connects], ["':memory:'"])
        names = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        for forbidden in ("open", "os.open", "os.unlink", "os.replace", "os.rename", "Path", "print", "eval", "exec", "__import__"):
            self.assertNotIn(forbidden, names)
        statements = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"
                      and node.args and isinstance(node.args[0], ast.Constant)]
        self.assertTrue(statements)
        for text in statements:
            self.assertTrue(text.lstrip().upper().startswith("SELECT"), f"읽는 문장뿐이다: {text[:40]}")

    def test_there_is_no_switch_to_skip_the_check(self):
        self.assertEqual(list(inspect.signature(sg.foreign_kinds).parameters), ["connection", "statements"])
        self.assertEqual(list(inspect.signature(sg.describe).parameters), ["kinds"])
        self.assertEqual(sorted(name for name in vars(sg) if not name.startswith("_") and callable(getattr(sg, name)) and getattr(getattr(sg, name), "__module__", "") == sg.__name__),
                         ["describe", "foreign_kinds"])

    def test_the_restore_functions_gained_no_parameter(self):
        self.assertEqual(list(inspect.signature(Store.restore_from).parameters), ["self", "backup", "safety_folder"])
        self.assertEqual(list(inspect.signature(TopicStore.restore_from).parameters), ["self", "backup"])

    def test_the_text_of_the_module_has_no_ascii_tilde_and_no_web_link(self):
        text = MODULE.read_text(encoding="utf-8")
        self.assertNotIn(chr(126), text)
        self.assertNotIn("http" + "://", text)
        self.assertNotIn("http" + "s://", text)


if __name__ == "__main__":
    unittest.main()
