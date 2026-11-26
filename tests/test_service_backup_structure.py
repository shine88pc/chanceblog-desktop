"""조작한 백업의 트리거·뷰·모르는 표와 색인이 복원으로 들어오지 못하게 하는 검사의 통합 시험 — 전체 백업·복원(`service/backup_flow.py`), 옛 `restore` 명령(`Store.restore_from`), 주제 엔진 복원(`TopicStore.restore_from`·`topicdb/backup.py`) (L8, 결정 D-554).

위협: 조작한 사람이 백업 폴더의 보관함 파일에 트리거·뷰를 넣고 **목록의 크기·해시를 다시 계산해 둔다**(해시는 같은 폴더 안의 값이라 조작을 막지 못하고 깨짐만 막는다). 예전에는 그 백업이 그대로 복원돼 이후 저장할 때마다 트리거가 돌았다.
지키는 것:
  1) 그런 백업은 **바꾸기 전에** 거절한다(`FULL_BACKUP_INVALID` 이유 `structure` — 지금 데이터·안전 사본 폴더·표지·잠금·임시 파일이 모두 그대로). 보관함 둘 × 구조 종류 여섯을 모두 본다.
  2) 구조 확인은 내용을 읽기 전에 먼저 한다(키 모양이 함께 있어도 이유는 `structure`). 확인과 복사 사이에 파일이 바뀌어도(바꿔치기) 바꾼 뒤 확인이 걸러 안전 사본으로 원래대로 돌린다.
  3) 정상 백업은 한 글자도 다르게 복원되지 않는다 — 복원 뒤 보관함은 덤프가 같고 개체 목록(종류·이름·딸린 표·SQL 글)도 같으며, 안전 사본으로의 되돌리기·옛 판(판 1) 백업도 그대로 된다.
  4) 복원 길 셋(전체 백업·옛 `restore` 명령·주제 엔진 백업)이 모두 막힌다 — 낮은 층의 `restore_from` 이 막으므로 어느 길로 와도 같다. 거절 문구에는 조작한 파일의 이름·글이 없다.
네트워크·실제 시계·실제 자격 증명 관리자 없이 돈다.
"""
import contextlib
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import store_v1  # noqa: E402
import test_service_backup_restore as tr  # noqa: E402

from chanceblog_desktop.content import schema_guard  # noqa: E402
from chanceblog_desktop.content.model import ContentProject  # noqa: E402
from chanceblog_desktop.content.store import SCHEMA_STATEMENTS, Store, _read_only_uri  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topicdb import backup as tbackup  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore, open_for_write  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

DBS = ("chanceblog.db", layout.ENGINE_DB_FILE)
CANARY = "CANARY_" + "str" + "uct"                                                     # 가짜 개체 이름 — 거절 문구에 되풀이되면 안 된다
# 보관함마다 (건드릴 표, 그 표의 글 칸, 표의 모든 열) — 조작 문장의 재료
TARGET = {"chanceblog.db": ("drafts", "text"), layout.ENGINE_DB_FILE: ("review_log", "kind")}


def tampering(name):
    """보관함 `name` 에 넣을 조작 문장들 — {종류 이름: [SQL, …]}. 모두 열 이름·행 내용은 그대로라 모양 확인·점검을 통과한다."""
    table, column = TARGET[name]
    found = {
        "trigger": [f"CREATE TRIGGER {CANARY}_t AFTER INSERT ON {table} BEGIN SELECT 1; END"],
        "destructive trigger": [f"CREATE TRIGGER {CANARY}_d AFTER INSERT ON {table} BEGIN DELETE FROM {table}; END"],
        "view": [f"CREATE VIEW {CANARY}_v AS SELECT * FROM {table}"],
        "extra table": [f"CREATE TABLE {CANARY}_x (x TEXT)"],
        "unique index": [f"CREATE UNIQUE INDEX {CANARY}_i ON {table} ({column})"],
        "partial index": [f"CREATE INDEX {CANARY}_p ON {table} ({column}) WHERE {column} > 'a'"],
    }
    if name == "chanceblog.db":                                                        # 표 행세를 하는 뷰 — 열 이름이 같아 예전 모양 확인을 통과한다
        found["view posing as a table"] = ["ALTER TABLE drafts RENAME TO drafts_real", "CREATE VIEW drafts AS SELECT project_id, text, saved_at FROM drafts_real",
                                           "CREATE TRIGGER pose INSTEAD OF INSERT ON drafts BEGIN INSERT INTO drafts_real VALUES (new.project_id, new.text || 'x', new.saved_at); END"]
    return found


def forge(folder, name, *statements):
    """백업 폴더의 보관함 `name` 에 `statements` 를 실행하고 목록의 크기·해시를 다시 계산해 둔다(조작한 사람이 하는 일)."""
    path = Path(folder) / name
    with contextlib.closing(sqlite3.connect(str(path))) as database:
        for statement in statements:
            database.execute(statement)
        database.commit()
    manifest = json.loads((Path(folder) / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
    data = path.read_bytes()
    manifest["files"][name].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    bs.write_manifest(folder, manifest)


def utf16_twin(path, encoding):
    """`path` 의 보관함과 표·색인·이름표(application_id·판)가 같지만 글자 인코딩이 `encoding` 이고 자료는 없는 보관함의 바이트 — 조작한 사람이 하는 일(독립 검증 S 의 SP-1)."""
    with contextlib.closing(sqlite3.connect(_read_only_uri(Path(path)), uri=True)) as old:
        statements = [row[0] for row in old.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY rowid")]
        application = old.execute("PRAGMA application_id").fetchone()[0]
        version = old.execute("PRAGMA user_version").fetchone()[0]
    with tempfile.TemporaryDirectory() as tmp:
        twin = Path(tmp) / "twin.db"
        with contextlib.closing(sqlite3.connect(str(twin))) as new:
            new.execute(f"PRAGMA encoding = '{encoding}'")
            for statement in statements:
                new.execute(statement)
            new.execute(f"PRAGMA application_id = {application}")
            new.execute(f"PRAGMA user_version = {version}")
            new.commit()
        return twin.read_bytes()


def forge_bytes(folder, name, raw):
    """백업 폴더의 `name` 을 `raw` 로 바꾸고 목록의 크기·해시를 다시 계산해 둔다(조작한 사람이 하는 일)."""
    (Path(folder) / name).write_bytes(raw)
    manifest = json.loads((Path(folder) / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["files"][name].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    bs.write_manifest(folder, manifest)


def encoding_of(path):
    with contextlib.closing(sqlite3.connect(str(path))) as database:
        return database.execute("PRAGMA encoding").fetchone()[0]


def schema_rows(path):
    with contextlib.closing(sqlite3.connect(_read_only_uri(Path(path)), uri=True)) as database:
        return sorted(database.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"), key=lambda row: (row[0], row[1]))


class Base(tr.Base):
    """`test_service_backup_restore.Base` 와 같은 틀(세계·임시 폴더·`assert_untouched`)에 구조 검사용 도우미를 더한다."""

    def setUp(self):
        super().setUp()
        self.outcome = self.world.backup()
        self.folder = self.world.folder(self.outcome)
        tr.change_everything(self.world)
        self.before = tr.state_of(self.world)

    def foreign_in(self, path, name):
        statements = SCHEMA_STATEMENTS if name == "chanceblog.db" else TopicStore.SCHEMA
        with contextlib.closing(sqlite3.connect(_read_only_uri(Path(path)), uri=True)) as database:
            return schema_guard.foreign_kinds(database, statements)

    def snapshot_folder(self):
        return {path.name: path.read_bytes() for path in self.folder.iterdir()}

    def restore_folder(self, saved):
        for name, data in saved.items():
            (self.folder / name).write_bytes(data)

    def assert_clean_refusal(self, error, reason="structure"):
        self.assertIsNotNone(error, "거절돼야 한다")
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", reason), error.detail)
        self.assert_untouched(self.before)
        self.assertFalse((self.ctx.workspace.backups_dir / bf.RESTORE_MARKER).exists(), "복원 중 표지를 만들지 않았다 — 바꾸기 전에 거절했다")
        text = str(error) + error.log_line() + error.detail
        self.assertNotIn(CANARY, text, "조작한 파일의 개체 이름은 되풀이하지 않는다")


class RefusalTest(Base):
    def test_every_kind_of_foreign_structure_in_either_database_is_refused_before_anything_changes(self):
        for name in DBS:
            for label, statements in tampering(name).items():
                with self.subTest(database=name, kind=label):
                    saved = self.snapshot_folder()
                    try:
                        forge(self.folder, name, *statements)
                        error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
                        self.assert_clean_refusal(error)
                        self.assertIn(name, error.detail)
                    finally:
                        self.restore_folder(saved)

    def test_the_refusal_says_in_one_easy_line_what_is_wrong(self):
        forge(self.folder, "chanceblog.db", *tampering("chanceblog.db")["trigger"])
        error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertIn("앱이 만들지 않는 구조", str(error))
        self.assertIn("트리거", error.detail)
        self.assertEqual(bf.INVALID_REASONS["structure"], "안의 보관함에 앱이 만들지 않는 구조(트리거·뷰·모르는 표 같은 것)가 들어 있어요")

    def test_the_manifest_hash_alone_does_not_stop_the_attack_but_the_structure_check_does(self):
        """조작한 사람은 목록의 해시를 다시 계산하므로 해시 확인(`_verify_folder`)은 통과한다 — 막는 것은 구조 확인이다."""
        forge(self.folder, "chanceblog.db", *tampering("chanceblog.db")["trigger"])
        self.assertEqual(bf._verify_folder(self.folder)["files"]["chanceblog.db"]["size"], (self.folder / "chanceblog.db").stat().st_size)
        with self.assertRaises(bf.FlowError) as caught:
            bf._verify_backup(self.folder)
        self.assertEqual(caught.exception.reason, "structure")

    def test_a_newer_version_database_with_new_tables_is_reported_as_newer_not_as_a_foreign_structure(self):
        """새 판이 더한 표를 '앱이 만들지 않는 구조' 로 잘못 거절하지 않는다 — 판이 새로우면 내용 확인이 '더 새로운 프로그램' 으로 거절한다(안내가 '프로그램을 업데이트하세요' 로 맞다)."""
        for name in DBS:
            with self.subTest(database=name):
                saved = self.snapshot_folder()
                try:
                    forge(self.folder, name, "CREATE TABLE brand_new_table (x TEXT)", "PRAGMA user_version = 99")
                    error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
                    self.assertEqual((error.code, error.reason), ("STORE_VERSION_UNSUPPORTED", "newer"), error.detail)
                    self.assert_untouched(self.before)
                finally:
                    self.restore_folder(saved)

    def test_the_same_extra_table_in_a_database_of_the_current_version_is_a_foreign_structure(self):
        for name in DBS:
            with self.subTest(database=name):
                saved = self.snapshot_folder()
                try:
                    forge(self.folder, name, "CREATE TABLE brand_new_table (x TEXT)")
                    self.assert_clean_refusal(bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True))
                finally:
                    self.restore_folder(saved)

    def test_an_extra_or_renamed_column_in_a_known_table_is_still_refused_by_the_old_shape_check(self):
        """보존 시험(옛 코드에서도 초록) — 알 수 없는 칸(열)은 구조 검사가 아니라 옛 모양 확인(`_shape_problem`)이 거절한다. 구조 검사가 들어와도 그 거절이 그대로이고 바꾸기 전에 일어나며
        열 이름 글은 오류에 되풀이되지 않음을 못박는다(적대 입력 목록의 '알 수 없는 칸')."""
        for name in DBS:
            table, column = TARGET[name]
            attacks = {"extra column": f"ALTER TABLE {table} ADD COLUMN {CANARY}_c TEXT DEFAULT ''", "renamed column": f"ALTER TABLE {table} RENAME COLUMN {column} TO {CANARY}_r"}
            for label, statement in attacks.items():
                with self.subTest(database=name, kind=label):
                    saved = self.snapshot_folder()
                    try:
                        forge(self.folder, name, statement)
                        self.assertEqual(self.foreign_in(self.folder / name, name), (), "개체는 그대로다 — 구조 검사의 몫이 아니다")
                        self.assert_clean_refusal(bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True), "content")
                    finally:
                        self.restore_folder(saved)

    def test_the_newer_version_deferral_is_only_for_the_backup_check_and_never_for_the_after_check(self):
        component = bf.BY_NAME["chanceblog.db"]
        path = self.folder / "chanceblog.db"
        with contextlib.closing(sqlite3.connect(str(path))) as database:
            database.execute("CREATE TABLE brand_new_table (x TEXT)")
            database.execute("PRAGMA user_version = 99")
            database.commit()
        self.assertEqual(bf._foreign_in(component, path, defer_newer=True), ())
        self.assertEqual(bf._foreign_in(component, path), ("table",), "바꾼 뒤 확인은 판에 상관없이 본다")

    def test_the_listing_still_shows_the_backup_because_listing_never_opens_the_databases(self):
        forge(self.folder, "chanceblog.db", *tampering("chanceblog.db")["view"])
        rows = bf.list_full_backups(self.ctx).rows
        self.assertIn(self.outcome.row.name, [row.name for row in rows])
        self.assertNotEqual({row.name: row.status for row in rows}[self.outcome.row.name], bf.STATUS_BROKEN)
        self.assert_untouched(self.before)

    def test_a_clean_backup_still_restores_after_a_refusal(self):
        saved = self.snapshot_folder()
        forge(self.folder, "chanceblog.db", *tampering("chanceblog.db")["trigger"])
        self.assert_clean_refusal(bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True))
        self.restore_folder(saved)
        result = self.restore(self.outcome.row.name)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)

    def test_the_structure_comes_first_even_when_a_key_shaped_text_is_inside_too(self):
        key = bs.secret_text("google_api_key")
        quoted = key.replace("'", "''")
        forge(self.folder, "chanceblog.db", *tampering("chanceblog.db")["view"], f"INSERT INTO drafts (project_id, text, saved_at) VALUES ('keyed', '{quoted}', '2026-11-11T00:00:00Z')")
        error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assert_clean_refusal(error)

    def test_a_database_that_cannot_be_read_is_still_the_content_reason_not_the_structure_one(self):
        path = self.folder / "chanceblog.db"
        path.write_bytes(b"this is not a database " * 30)
        manifest = json.loads((self.folder / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        manifest["files"]["chanceblog.db"].update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        bs.write_manifest(self.folder, manifest)
        self.assert_clean_refusal(bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True), "content")

    def test_json_and_settings_files_are_not_subject_to_the_database_structure_check(self):
        """JSON·설정에는 트리거·뷰가 없다 — 그쪽은 엄격한 읽기(칸 모양·크기)가 그대로 지킨다."""
        self.assertIsNone(bf._check_structure(self.folder, layout.SEEDS_FILE))
        self.assertIsNone(bf._check_structure(self.folder, "settings.json"))
        self.assertIsNone(bf._check_structure(self.folder, "chanceblog.db"))

    def test_the_foreign_structure_inside_a_safety_copy_is_refused_the_same_way(self):
        """안전 사본(`before-…`)도 같은 길로 복원한다 — 같은 구조 확인을 받는다."""
        self.restore(self.outcome.row.name)
        safety = self.safety_root() / next(entry.name for entry in self.safety_root().iterdir() if bf.SAFETY_NAME.fullmatch(entry.name))
        manifest = json.loads((safety / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        name = "chanceblog.db"
        before = tr.state_of(self.world)
        with contextlib.closing(sqlite3.connect(str(safety / name))) as database:
            database.execute(tampering(name)["trigger"][0])
            database.commit()
        data = (safety / name).read_bytes()
        manifest["files"][name].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        bs.write_manifest(safety, manifest)
        error = bs.code_of(bf.restore_full_backup, self.ctx, safety.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "structure"))
        self.assertEqual(tr.state_of(self.world), before, "지금 데이터는 그대로")


class AfterCheckTest(Base):
    """확인 때는 멀쩡했는데 복사하는 사이 파일이 바뀐 경우(바꿔치기) — 바꾼 뒤 확인이 걸러 안전 사본으로 원래대로 돌린다."""

    def swapped_import(self, evil_name):
        """`_restore_database` 를 보관함 확인 없이 통째 복사하는 것으로 바꿔치기한다(보관함 하나는 미리 만든 조작 파일로)."""
        real, calls = bf._restore_database, []

        def raw(component, path, source):
            if component.name != evil_name or calls:                                  # 바꿔치기는 처음 한 번뿐 — 원래대로 돌릴 때는 진짜 복원이 돈다
                return real(component, path, source)
            calls.append(component.name)
            with contextlib.closing(sqlite3.connect(str(self.evil))) as origin, contextlib.closing(sqlite3.connect(str(path))) as target:
                origin.backup(target)

        return raw

    def test_a_database_swapped_in_during_the_copy_is_caught_after_the_change_and_rolled_back(self):
        for name in DBS:
            with self.subTest(database=name):
                self.evil = Path(self.tmp.name) / f"evil-{name}"
                shutil.copyfile(self.folder / name, self.evil)
                with contextlib.closing(sqlite3.connect(str(self.evil))) as database:
                    database.execute(tampering(name)["trigger"][0])
                    database.commit()
                with mock.patch.object(bf, "_restore_database", side_effect=self.swapped_import(name)):
                    error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
                self.assertIsNotNone(error)
                self.assertEqual((error.code, error.reason), ("RESTORE_FAILED", "corrupt"), error.detail)
                self.assertEqual(error.notes, (), "모두 원래대로 돌렸다")
                self.assertEqual(tr.state_of(self.world), self.before, "지금 데이터가 원래대로 돌아왔다")
                self.assertEqual(self.foreign_in(self.world.path(name), name), ())
                self.assertFalse((self.ctx.workspace.backups_dir / bf.RESTORE_MARKER).exists())


class RoundTripTest(Base):
    """정상 백업은 한 글자도 다르게 복원되지 않는다."""

    def test_restoring_a_normal_backup_gives_the_same_content_and_the_same_structure(self):
        for name in DBS:
            self.assertEqual(self.foreign_in(self.folder / name, name), ())
        backed_up = {name: bs.dump(self.folder / name) for name in DBS}
        schema_before = {name: schema_rows(self.folder / name) for name in DBS}
        result = self.restore(self.outcome.row.name)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        for name in DBS:
            self.assertEqual(bs.dump(self.world.path(name)), backed_up[name], f"{name}: 보관함 내용이 백업과 같다")
            self.assertEqual(schema_rows(self.world.path(name)), schema_before[name], f"{name}: 개체 목록(종류·이름·딸린 표·SQL 글)이 백업과 같다")
            with contextlib.closing(sqlite3.connect(_read_only_uri(self.world.path(name)), uri=True)) as database:
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        for name in tr.PLAIN:
            self.assertEqual((self.folder / name).read_bytes(), self.world.path(name).read_bytes(), f"{name}: 바이트가 같다")

    def test_restoring_the_safety_copy_goes_back_to_the_state_before_the_first_restore(self):
        self.restore(self.outcome.row.name)
        safety = next(entry.name for entry in self.safety_root().iterdir() if bf.SAFETY_NAME.fullmatch(entry.name))
        self.restore(safety)
        self.assertEqual(tr.state_of(self.world), self.before)

    def test_a_backup_of_the_live_data_made_right_after_a_restore_restores_to_the_same_state_again(self):
        self.restore(self.outcome.row.name)
        again = self.world.backup()
        restored = tr.state_of(self.world)
        tr.change_everything(self.world)
        self.restore(again.row.name)
        self.assertEqual(tr.state_of(self.world), restored)

    def test_a_first_version_content_backup_restores_and_is_upgraded_like_before(self):
        """판 1(후보 표가 생기기 전) 보관함이 든 백업도 그대로 되돌려진다 — 구조 확인은 정본의 부분집합을 받아들인다."""
        old = Path(self.tmp.name) / "v1.db"
        project = ContentProject.new("옛 판의 글", "옛 판의 본문", project_id="legacy-1")
        store_v1.make_v1_file(old, [project])
        shutil.copyfile(old, self.folder / "chanceblog.db")
        forge(self.folder, "chanceblog.db")                                            # 문장 없이 목록의 크기·해시만 다시 계산한다
        result = self.restore(self.outcome.row.name)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        with Store.open(self.world.path("chanceblog.db"), migrate=False) as store:
            self.assertEqual([item.project_id for item in store.list()], ["legacy-1"])
            self.assertEqual(store.schema_version, 3, "되돌린 뒤 지금 판(PUBPR 가 올린 판 3)으로 올라갔다")
            self.assertEqual(store.check(), [])


class EncodingTest(Base):
    """독립 검증 S 의 SP-1(필수) — 글자 인코딩이 UTF-16 인 조작 백업은 구조가 정상이라 모든 확인을 지나, 통째 복사 뒤에야 SQLite 가 실패해 지금 보관함이 UTF-16 으로 바뀌고 표가 비었는데
    화면은 '원래대로 돌려 두었어요' 라고 알렸다(시작점에서도 같다). 구조 검사가 UTF-8 이 아닌 보관함을 바꾸기 전에 거절한다."""

    ENCODINGS = ("UTF-16le", "UTF-16be")

    def test_the_full_backup_road_refuses_a_utf16_database_in_either_storage_before_anything_changes(self):
        for name in DBS:
            for encoding in self.ENCODINGS:
                with self.subTest(database=name, encoding=encoding):
                    saved = self.snapshot_folder()
                    try:
                        forge_bytes(self.folder, name, utf16_twin(self.folder / name, encoding))
                        self.assertIn(encoding_of(self.folder / name), ("UTF-16le", "UTF-16be"), "조작한 파일이 정말 UTF-16 이다")
                        error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
                        self.assert_clean_refusal(error)
                        self.assertIn(name, error.detail)
                        self.assertIn(schema_guard.KIND_TEXT["encoding"], error.detail)
                    finally:
                        self.restore_folder(saved)

    def test_the_listing_does_not_open_the_databases_so_a_utf16_backup_is_still_listed_and_only_the_restore_is_refused(self):
        forge_bytes(self.folder, "chanceblog.db", utf16_twin(self.folder / "chanceblog.db", "UTF-16le"))
        self.assertIn(self.outcome.row.name, [row.name for row in bf.list_full_backups(self.ctx).rows])
        self.assert_clean_refusal(bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True))

    def test_a_clean_utf8_backup_still_restores_right_after_a_utf16_refusal(self):
        saved = self.snapshot_folder()
        forge_bytes(self.folder, "chanceblog.db", utf16_twin(self.folder / "chanceblog.db", "UTF-16be"))
        self.assert_clean_refusal(bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True))
        self.restore_folder(saved)
        self.assertEqual(self.restore(self.outcome.row.name).status, bf.STATUS_COMPLETE)


class EveryRestoreRouteTest(unittest.TestCase):
    """전체 백업 화면 말고도 복원 길이 둘 더 있다 — 모두 낮은 층의 `restore_from` 이 막는다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def content_pair(self):
        live, source = self.tmp / "live.db", self.tmp / "backup.db"
        for path, title in ((live, "지금 글"), (source, "백업의 글")):
            with Store.open(path) as store:
                store.save(ContentProject.new(title, "본문", project_id="p1"))
        return live, source

    def test_the_old_restore_command_refuses_a_tampered_content_backup_and_changes_nothing(self):
        live, source = self.content_pair()
        for label, statements in tampering("chanceblog.db").items():
            with self.subTest(kind=label):
                tampered = self.tmp / f"t-{label.replace(' ', '-')}.db"
                shutil.copyfile(source, tampered)
                with contextlib.closing(sqlite3.connect(str(tampered))) as database:
                    for statement in statements:
                        database.execute(statement)
                    database.commit()
                before = bs.dump(live)
                with Store.open(live) as store:
                    error = bs.code_of(store.restore_from, tampered)
                    self.assertEqual(error.code, "STORE_CORRUPT")
                    self.assertIn("앱이 만들지 않는 구조", error.detail)
                    self.assertNotIn(CANARY, str(error) + error.detail)
                self.assertEqual(bs.dump(live), before, "지금 저장소는 그대로")

    def test_the_refusal_comes_before_the_safety_copy_the_function_can_make(self):
        live, source = self.content_pair()
        with contextlib.closing(sqlite3.connect(str(source))) as database:
            database.execute(tampering("chanceblog.db")["trigger"][0])
            database.commit()
        safety = self.tmp / "safety"
        with Store.open(live) as store:
            self.assertEqual(bs.code_of(store.restore_from, source, safety_folder=safety).code, "STORE_CORRUPT")
        self.assertFalse(safety.exists(), "거절은 안전 사본보다 먼저다")

    def test_a_clean_content_backup_restores_through_the_same_function(self):
        live, source = self.content_pair()
        with Store.open(live) as store:
            store.restore_from(source)
            self.assertEqual([item.title for item in store.list()], ["백업의 글"])

    def test_the_topic_engine_store_refuses_a_tampered_backup_and_changes_nothing(self):
        for label, statements in tampering(layout.ENGINE_DB_FILE).items():
            with self.subTest(kind=label):
                live, source = self.tmp / f"e-live-{label.replace(' ', '-')}.db", self.tmp / f"e-source-{label.replace(' ', '-')}.db"
                with open_for_write(live) as store:
                    store._write(lambda db: db.execute("INSERT INTO review_log (kind, last_run_on) VALUES ('지금', '2026-11-11')"))
                shutil.copyfile(live, source)
                with open_for_write(source) as store:
                    store._write(lambda db: db.execute("INSERT INTO review_log (kind, last_run_on) VALUES ('백업', '2026-11-12')"))
                with contextlib.closing(sqlite3.connect(str(source))) as database:
                    for statement in statements:
                        database.execute(statement)
                    database.commit()
                before = bs.dump(live)
                with open_for_write(live) as store:
                    error = bs.code_of(store.restore_from, source)
                    self.assertEqual(error.code, "TOPIC_BACKUP_INVALID")
                    self.assertIn("앱이 만들지 않는 구조", str(error))
                    self.assertNotIn(CANARY, str(error) + error.detail)
                self.assertEqual(bs.dump(live), before)

    def test_the_old_restore_command_refuses_a_utf16_content_backup_and_changes_nothing(self):
        """SP-1 — 길 2: 시작점에서는 복사 뒤에 SQLite 가 실패해 지금 저장소가 UTF-16 으로 바뀌고 표가 비었다."""
        live, source = self.content_pair()
        for encoding in ("UTF-16le", "UTF-16be"):
            with self.subTest(encoding=encoding):
                twin = self.tmp / f"utf16-{encoding}.db"
                twin.write_bytes(utf16_twin(source, encoding))
                before = bs.dump(live)
                with Store.open(live) as store:
                    error = bs.code_of(store.restore_from, twin)
                    self.assertEqual(error.code, "STORE_CORRUPT")
                    self.assertIn("앱이 만들지 않는 구조", error.detail)
                    self.assertIn(schema_guard.KIND_TEXT["encoding"], error.detail)
                self.assertEqual(bs.dump(live), before, "지금 저장소는 그대로")
                self.assertEqual(encoding_of(live), "UTF-8")
                with Store.open(live) as store:
                    self.assertEqual([item.title for item in store.list()], ["지금 글"])

    def test_the_topic_engine_store_refuses_a_utf16_backup_and_changes_nothing(self):
        """SP-1 — 길 3: 주제 엔진 보관함도 같다."""
        for encoding in ("UTF-16le", "UTF-16be"):
            with self.subTest(encoding=encoding):
                live, source = self.tmp / f"u-live-{encoding}.db", self.tmp / f"u-source-{encoding}.db"
                with open_for_write(live) as store:
                    store._write(lambda db: db.execute("INSERT INTO review_log (kind, last_run_on) VALUES ('지금', '2026-11-11')"))
                shutil.copyfile(live, source)
                source.write_bytes(utf16_twin(source, encoding))
                before = bs.dump(live)
                with open_for_write(live) as store:
                    error = bs.code_of(store.restore_from, source)
                    self.assertEqual(error.code, "TOPIC_BACKUP_INVALID")
                    self.assertIn("앱이 만들지 않는 구조", str(error))
                self.assertEqual(bs.dump(live), before)
                self.assertEqual(encoding_of(live), "UTF-8")
                with open_for_write(live) as store:
                    self.assertEqual(store._read("SELECT kind FROM review_log"), [("지금",)])

    def test_a_clean_topic_engine_backup_restores_through_the_same_function(self):
        live, source = self.tmp / "live.db", self.tmp / "source.db"
        with open_for_write(live):
            pass
        shutil.copyfile(live, source)
        with open_for_write(source) as store:
            store._write(lambda db: db.execute("INSERT INTO review_log (kind, last_run_on) VALUES ('백업', '2026-11-12')"))
        with open_for_write(live) as store:
            store.restore_from(source)
            self.assertEqual(store._read("SELECT kind FROM review_log"), [("백업",)])


class TopicBackupFolderTest(Base):
    """`topics backup` 이 만드는 폴더(`topic-날짜-시각`)의 복원 — JSON 을 바꾸기 전에 거절한다."""

    def setUp(self):
        super().setUp()
        self.paths = self.world.paths
        self.backups = self.ctx.workspace.backups_dir / "topic_engine"
        self.made = tbackup.make_backup(self.paths.folder, self.backups, now=self.ctx.now())
        self.topic_folder = self.made.path

    def forge_topic(self, *statements):
        path = self.topic_folder / layout.ENGINE_DB_FILE
        with contextlib.closing(sqlite3.connect(str(path))) as database:
            for statement in statements:
                database.execute(statement)
            database.commit()
        manifest = json.loads((self.topic_folder / tbackup.MANIFEST_NAME).read_text(encoding="utf-8"))
        data = path.read_bytes()
        manifest["files"][layout.ENGINE_DB_FILE].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        (self.topic_folder / tbackup.MANIFEST_NAME).write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    def test_an_untampered_topic_backup_reads_back_fine(self):
        manifest, contents = tbackup.read_backup(self.topic_folder)
        self.assertIn(layout.ENGINE_DB_FILE, contents)

    def test_a_tampered_engine_database_in_a_topic_backup_is_refused_before_any_file_changes(self):
        for label, statements in tampering(layout.ENGINE_DB_FILE).items():
            with self.subTest(kind=label):
                saved = {path.name: path.read_bytes() for path in self.topic_folder.iterdir()}
                try:
                    self.forge_topic(*statements)
                    before = tr.state_of(self.world)
                    error = bs.code_of(tbackup.restore_backup, self.topic_folder, self.paths.folder, self.backups, now=self.ctx.now())
                    self.assertIsNotNone(error)
                    self.assertEqual(error.code, "TOPIC_BACKUP_INVALID")
                    self.assertIn("앱이 만들지 않는 구조", str(error))
                    self.assertNotIn(CANARY, str(error) + error.detail)
                    self.assertEqual(tr.state_of(self.world), before, "JSON 도 보관함도 그대로")
                    self.assertFalse((self.backups / tbackup.SAFETY_FOLDER).exists(), "직전 상태 백업도 만들지 않았다")
                finally:
                    for name, data in saved.items():
                        (self.topic_folder / name).write_bytes(data)

    def test_a_topic_backup_made_after_adding_a_foreign_object_to_the_live_database_is_still_made(self):
        """백업을 만드는 쪽은 바뀌지 않았다 — 지금 파일을 그대로 담는다(들어오는 것만 검사한다)."""
        with contextlib.closing(sqlite3.connect(str(self.paths.database))) as database:
            database.execute("CREATE VIEW user_made AS SELECT 1")
            database.commit()
        made = tbackup.make_backup(self.paths.folder, self.backups, now=self.ctx.now())
        self.assertTrue(made.path.is_dir())


if __name__ == "__main__":
    unittest.main()
