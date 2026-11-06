"""주제 엔진 백업·복원(`topicdb/backup.py`) 시험 — 보관함(SQLite 백업 방식)과 설정 파일 셋(모양 검사 뒤 복사)의 점검한 백업, 바꾸기 전에 전부 확인하는 복원, 실패하면 원래대로, 키 모양은 어떤 백업에도 없다(P3, D-63). 네트워크·실제 시계 없이 돈다.

지키는 것:
  1) 백업은 임시 폴더에서 다 만들고 해시를 다시 확인한 뒤에야 이름을 바꾼다. 목록(MANIFEST)의 이름·크기·해시가 실제 파일과 같고, 오래된 것은 개수만큼만 남기며 낯선 파일이 든 폴더는 지우지 않는다.
  2) 키·토큰 모양이 파일이나 보관함 안에 있으면 백업을 만들지 않고, 만든 어떤 백업 파일에도 키 모양이 없다. 깨졌거나 더 새로운 보관함도 백업하지 않는다.
  3) 복원은 바꾸기 전에 백업의 모든 파일(이름·크기·해시·SQLite 이름표·판·모양·JSON 모양·키 모양)을 확인하고, 틀리면 아무것도 바꾸지 않는다.
  4) 복원 도중 어디서 실패해도 JSON 은 원래 내용으로 돌아가고 보관함은 바뀌지 않으며, 바꾸기 직전 상태는 `before-restore` 백업에 남는다. 깨진 지금 보관함은 지우지 않고 옆으로 옮긴다. 백업에 없는 파일은 그대로 둔다.
"""
import contextlib
import datetime
import errno
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security.mask import has_key_shape  # noqa: E402
from chanceblog_desktop.topicdb import backup as bk  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore  # noqa: E402
from chanceblog_desktop.topics import channels, layout, schedule, seeds  # noqa: E402
from chanceblog_desktop.topics import history as hist  # noqa: E402
from test_repo_layout import KEY_SHAPES  # noqa: E402

NOW = datetime.datetime(2026, 11, 6, 8, 0, 0)
STAMP = "2026-11-06T00:00:00Z"
FAKE_KEY = "AI" + "za" + "B" * 35                         # 키 모양(조합해서 만든 값이라 저장소에는 키 문자열이 없다)


# 보관함 표마다 키 모양 한 줄을 넣는 문장 — 발행 이력 장부만 키 모양 검사에서 빠지고 나머지는 모두 걸려야 한다(D-75). 보관함에 표가 더해지면 이 표도 함께 고친다
KEY_ROWS = {
    "candidates": ("UPDATE candidates SET saved_at = ? WHERE candidate_id = 'cid-001'", (STAMP + " " + FAKE_KEY,)),
    "hold_box": ("INSERT INTO hold_box (candidate_id, entered_at, expires_at, left_at) VALUES ('cid-001', ?, '2027-02-04T00:00:00Z', NULL)", (FAKE_KEY,)),
    "score_snapshots": ("INSERT INTO score_snapshots (candidate_id, evaluated_at, final_score, band, data) VALUES ('cid-001', ?, 70, 'good', '{}')", (FAKE_KEY,)),
    "trend_cache": ("INSERT INTO trend_cache (keyword_key, period, compared_hash, queried_on, status, ratio, data_status, stored_at, data) VALUES (?, 'p', 'h', '2026-11-06', 'ok', 1, 'ok', '2026-11-06T00:00:00Z', '{}')", (FAKE_KEY,)),
    "candidate_links": ("INSERT INTO candidate_links (engine_candidate_id, legacy_candidate_id, draft_plan_id, source_topic_id, seed_id, channel, saved_at, data) VALUES ('cid-001', ?, NULL, NULL, NULL, 'naver_a', '2026-11-06T00:00:00Z', '{}')", (FAKE_KEY,)),
    "provenance": ("INSERT INTO provenance (engine_candidate_id, taken_at, data) VALUES ('cid-001', '2026-11-06T00:00:00Z', ?)", (FAKE_KEY,)),
    # P3b-1 의도적 갱신: 판 2 의 새 표 둘(점검 기록·보류 이력)도 키 모양 검사에 걸려야 한다(사용자가 쓴 글이 들어갈 수 있는 표는 모두 훑는다)
    "review_log": ("INSERT INTO review_log (kind, last_run_on) VALUES (?, '2026-11-06')", (FAKE_KEY,)),
    # D-120 의도적 갱신: 보류 이력이 13칸이 되고(`first_created_at`·`cleaned_at`·`cleanup_reason`) 재생성 관계 표(`candidate_lineage`)가 더해졌다 — 새 표도 키 모양 검사에 걸려야 한다
    "hold_history": ("INSERT INTO hold_history (candidate_id, normalized_keyword, topic_summary, first_created_at, last_evaluated_on, hold_reason, exclusion_reason, normalized_topic_hash, seed_id, channel, search_intent, topic_angle,"
                     " cleaned_at, cleanup_reason) VALUES ('cid-777', ?, '요약', '2026-08-01T00:00:00Z', '2026-11-01', '', '', 'h', 's', 'naver_a', 'information', 'angle', '2026-11-06T00:00:00Z', 'hold_90d_unchanged')", (FAKE_KEY,)),
    "candidate_lineage": ("INSERT INTO candidate_lineage (candidate_id, recreated_from, relation, created_at) VALUES (?, 'cid-777', 'RECREATED_FROM', '2026-11-06T00:00:00Z')", (FAKE_KEY,)),
    "history_ledger": ("INSERT INTO history_ledger (channel, record_key, title, keywords, date, url, language, topic, ref, origin, first_seen_at, last_seen_at) VALUES ('naver_a', 'k1', ?, '[]', NULL, NULL, NULL, NULL, 'p1', 'naver_items', '2026-11-06T00:00:00Z', '2026-11-06T00:00:00Z')", (FAKE_KEY,)),
}


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


def digests(folder):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(folder).iterdir()) if path.is_file()}


def put_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def candidate(number, **more):
    return ts.rated(70, candidate_id=f"cid-{number:03d}", channel="naver_a", cluster="local-ai", topic=f"예시 주제 {number}번 모음", created_at="2026-11-06T00:00:00Z", **more)


class World:
    """데이터 폴더(주제 엔진 파일 넷)와 백업 폴더를 임시 폴더에 만든다."""

    def __init__(self, tmp, *, database=True, profiles=True, seed_file=True, calendar=True):
        self.root = Path(tmp)
        self.data = self.root / "topic_engine"
        self.backups = self.root / "backups" / "topic_engine"
        self.data.mkdir(parents=True)
        if database:
            with TopicStore.open(self.data / layout.ENGINE_DB_FILE) as store:
                store.add_candidates(lambda existing: [candidate(1), candidate(2)], now=STAMP)
        if profiles:
            put_json(self.data / layout.CHANNEL_PROFILES_FILE, channels.profiles_to_dict(channels.default_profiles()))
        if seed_file:
            put_json(self.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed()]))
        if calendar:
            put_json(self.data / layout.CALENDAR_FILE, schedule.entries_to_dict([ts.example_entry()]))

    def backup(self, now=NOW, **kwargs):
        return bk.make_backup(self.data, self.backups, now=now, **kwargs)

    def candidates(self):
        with TopicStore.open(self.data / layout.ENGINE_DB_FILE, migrate=False) as store:
            return [item.candidate_id for item in store.list_candidates()]


class MakeBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def test_only_the_published_history_ledger_is_left_out_of_the_key_check_and_every_other_table_is_scanned(self):
        with contextlib.closing(sqlite3.connect(str(self.world.data / layout.ENGINE_DB_FILE))) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
        self.assertEqual(tables, set(KEY_ROWS), "보관함의 표가 바뀌면 이 시험의 표 목록도 함께 고친다 — 장부 말고는 모두 키 모양 검사에 걸려야 한다")
        for table, (statement, values) in KEY_ROWS.items():
            with self.subTest(table=table):
                with tempfile.TemporaryDirectory() as tmp:
                    path = World(tmp).data / layout.ENGINE_DB_FILE
                    with contextlib.closing(sqlite3.connect(str(path))) as connection:
                        connection.execute("PRAGMA foreign_keys = OFF")                  # 일부러 규칙을 어기는 한 줄(관계 표의 옛 번호가 이력에 없음)은 시스템 SQLite 빌드의 외래 키 기본값에 기대지 않는다
                        with connection:
                            connection.execute(statement, values)
                    self.assertEqual(bk._database_key_shaped(path), table != "history_ledger", f"{table} 표의 키 모양")

    def test_the_ledger_prefix_text_inside_another_tables_row_does_not_hide_a_key_shape(self):
        path = self.world.data / layout.ENGINE_DB_FILE
        with contextlib.closing(sqlite3.connect(str(path))) as connection:
            with connection:
                connection.execute("UPDATE candidates SET saved_at = ? WHERE candidate_id = 'cid-001'", ('INSERT INTO "history_ledger" ' + FAKE_KEY,))
        self.assertTrue(bk._database_key_shaped(path), "장부 행은 줄 맨 앞이 장부 표 이름일 때만 뺀다 — 다른 표의 글 안에 그 낱말이 있어도 훑는다")
        self.assertEqual(code_of(self.world.backup, now=NOW + datetime.timedelta(seconds=5)), "TOPIC_BACKUP_BLOCKED")

    def test_a_key_shape_in_the_published_history_ledger_does_not_block_the_backup_but_one_in_a_candidate_does(self):
        record = hist.HistoryRecord(channel="naver_a", title=f"예시 발행 글 {FAKE_KEY}", keywords=(), date="2026-10-01", ref="p1", origin="naver_items")
        with TopicStore.open(self.world.data / layout.ENGINE_DB_FILE) as store:
            store.sync_history([record], now=STAMP)
        made = self.world.backup(now=NOW + datetime.timedelta(seconds=3))
        self.assertIn(FAKE_KEY.encode("utf-8"), (made.path / layout.ENGINE_DB_FILE).read_bytes(), "이미 공개된 글의 값이라 그대로 담는다(D-75)")
        with contextlib.closing(sqlite3.connect(str(self.world.data / layout.ENGINE_DB_FILE))) as connection:
            with connection:
                connection.execute("UPDATE candidates SET saved_at = ? WHERE candidate_id = 'cid-001'", (STAMP + " " + FAKE_KEY,))
        self.assertEqual(code_of(self.world.backup, now=NOW + datetime.timedelta(seconds=9)), "TOPIC_BACKUP_BLOCKED", "후보에 있는 키 모양은 여전히 막는다")

    def test_a_backup_is_a_folder_with_the_four_files_and_a_manifest_that_matches_them(self):
        result = self.world.backup()
        self.assertEqual(result.path.name, "topic-20261106-080000")
        self.assertEqual((result.files, result.missing), (layout.USER_DATA_FILES, ()))
        self.assertEqual(sorted(os.listdir(result.path)), sorted([*layout.USER_DATA_FILES, "MANIFEST.json"]))
        manifest = json.loads((result.path / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["schema"], manifest["created_at"], manifest["missing"]), (1, "2026-11-06T08:00:00Z", []))
        actual = digests(result.path)
        for name in layout.USER_DATA_FILES:
            data = (result.path / name).read_bytes()
            self.assertEqual(manifest["files"][name], {"size": len(data), "sha256": actual[name]})
        for name in layout.JSON_FILES:
            self.assertEqual((result.path / name).read_bytes(), (self.world.data / name).read_bytes(), "JSON 은 그대로 복사한다")
        with TopicStore.open(result.path / layout.ENGINE_DB_FILE, migrate=False) as copy:
            self.assertEqual((copy.count(), copy.check()), (2, []))
        self.assertEqual([entry for entry in os.listdir(self.world.backups) if entry.endswith(".tmp")], [])
        self.assertEqual(bk.list_backups(self.world.backups), [result.path])

    def test_only_the_files_that_exist_are_backed_up_and_the_rest_are_recorded_as_missing(self):
        with tempfile.TemporaryDirectory() as other:
            world = World(other, database=False, calendar=False)
            result = world.backup()
            self.assertEqual((result.files, result.missing), ((layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE), (layout.CALENDAR_FILE, layout.ENGINE_DB_FILE)))
            self.assertEqual(json.loads((result.path / "MANIFEST.json").read_text(encoding="utf-8"))["missing"], [layout.CALENDAR_FILE, layout.ENGINE_DB_FILE])
        with tempfile.TemporaryDirectory() as empty:
            nothing = World(empty, database=False, profiles=False, seed_file=False, calendar=False)
            self.assertEqual(code_of(nothing.backup), "CONTENT_NOT_FOUND")
            self.assertFalse(nothing.backups.exists(), "담을 것이 없으면 백업 폴더도 만들지 않는다")

    def test_two_backups_in_the_same_second_do_not_overwrite_each_other(self):
        first, second, third = self.world.backup(), self.world.backup(), self.world.backup()
        self.assertEqual([item.name for item in (first.path, second.path, third.path)], ["topic-20261106-080000", "topic-20261106-080000-2", "topic-20261106-080000-3"])
        self.assertTrue(all(bk.BACKUP_NAME.fullmatch(item.name) for item in (first.path, second.path, third.path)))

    def test_only_the_newest_ones_are_kept_and_only_app_made_folders_are_removed(self):
        stranger = self.world.backups / "topic-20200101-000000"
        stranger.mkdir(parents=True)
        (stranger / "my-notes.txt").write_text("지우면 안 되는 파일", encoding="utf-8")
        other = self.world.backups / "just-a-folder"
        other.mkdir()
        for second in range(5):
            self.world.backup(now=NOW + datetime.timedelta(seconds=second), keep=3)
        names = [item.name for item in bk.list_backups(self.world.backups)]
        self.assertEqual(names[:3], ["topic-20261106-080004", "topic-20261106-080003", "topic-20261106-080002"], "가장 새 셋만 남는다")
        self.assertEqual(names[3:], ["topic-20200101-000000"], "앱이 지울 수 없는 낯선 폴더는 목록에 남는다(지우려다 건드리지 않는다)")
        self.assertTrue(stranger.exists() and (stranger / "my-notes.txt").exists(), "낯선 파일이 든 폴더는 건드리지 않는다")
        self.assertTrue(other.exists())

    def test_a_key_shaped_text_in_any_file_or_in_the_store_blocks_the_backup_and_nothing_is_made(self):
        for where in ("seeds", "store"):
            with self.subTest(where=where), tempfile.TemporaryDirectory() as other:
                world = World(other)
                if where == "seeds":
                    put_json(world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(keyword=f"예시 {FAKE_KEY}")]))
                else:
                    with TopicStore.open(world.data / layout.ENGINE_DB_FILE) as store:
                        store.add_candidates(lambda existing: [ts.rated(70, candidate_id="cid-099", channel="naver_a", topic=f"예시 {FAKE_KEY} 모음", created_at=STAMP)], now=STAMP)
                self.assertEqual(code_of(world.backup), "TOPIC_BACKUP_BLOCKED")
                self.assertFalse(world.backups.exists() and any(world.backups.iterdir()), "키 모양이 있으면 백업 폴더(임시 포함)가 남지 않는다")

    def test_no_file_of_a_backup_has_a_key_shape_and_the_backup_never_reads_the_key_store(self):
        result = self.world.backup()
        pattern = re.compile("|".join(KEY_SHAPES))
        for path in result.path.iterdir():
            text = path.read_bytes().decode("utf-8", errors="replace")
            self.assertIsNone(pattern.search(text), path.name)
        with contextlib.closing(sqlite3.connect(str(result.path / layout.ENGINE_DB_FILE))) as connection:
            dumped = "\n".join(connection.iterdump())
        self.assertIsNone(pattern.search(dumped))
        source = Path(bk.__file__).read_text(encoding="utf-8")
        for needle in ("keystore", "KeyStore", "get_keystore", "CredRead", "environ"):
            self.assertNotIn(needle, source, "백업은 키 보관소를 읽지 않는다")

    def test_a_broken_foreign_or_newer_store_is_not_backed_up_and_not_changed(self):
        database = self.world.data / layout.ENGINE_DB_FILE
        saved = database.read_bytes()
        for name, make in (("깨짐", lambda: database.write_bytes(os.urandom(4096))), ("더 새로움", lambda: (database.write_bytes(saved), self.bump(database)))):
            with self.subTest(case=name):
                make()
                before = database.read_bytes()
                self.assertEqual(code_of(self.world.backup), "TOPIC_BACKUP_BLOCKED")
                self.assertEqual(database.read_bytes(), before)
                self.assertFalse(self.world.backups.exists() and any(self.world.backups.iterdir()))

    def bump(self, database):
        with sqlite3.connect(str(database)) as connection:
            connection.execute("PRAGMA user_version = 9")
        connection.close()

    def test_a_store_whose_rows_disagree_with_themselves_is_not_backed_up(self):
        with contextlib.closing(sqlite3.connect(str(self.world.data / layout.ENGINE_DB_FILE))) as connection:
            with connection:
                connection.execute("UPDATE score_snapshots SET data = '{}' WHERE candidate_id = 'cid-001'")
        self.assertEqual(code_of(self.world.backup), "TOPIC_BACKUP_BLOCKED", "구조 점검만이 아니라 행 자료 점검도 한다")
        self.assertFalse(self.world.backups.exists() and any(self.world.backups.iterdir()))

    def test_a_backup_that_does_not_read_back_as_listed_is_not_kept(self):
        real = bk._write_bytes

        def wrong(path, data):                                       # 디스크가 마지막 글자 하나를 잘못 쓴 것처럼 — 크기는 같고 해시만 다르다
            return real(path, data[:-1] + b" " if Path(path).name == layout.SEEDS_FILE else data)

        bk._write_bytes = wrong
        self.addCleanup(setattr, bk, "_write_bytes", real)
        self.assertEqual(code_of(self.world.backup), "BACKUP_FAILED", "다 만든 백업은 다시 읽어 목록과 맞는지 확인한다")
        self.assertFalse(self.world.backups.exists() and any(self.world.backups.iterdir()), "다시 읽어 맞지 않은 백업은 남지 않는다")

    def test_a_blocked_backup_leaves_no_folder_behind_but_keeps_a_folder_that_was_already_there(self):
        for where in ("seeds", "database"):
            with self.subTest(where=where), tempfile.TemporaryDirectory() as other:
                world = World(other)
                if where == "seeds":
                    put_json(world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(keyword=f"예시 {FAKE_KEY}")]))
                else:
                    (world.data / layout.ENGINE_DB_FILE).write_bytes(os.urandom(4096))
                self.assertEqual(code_of(world.backup), "TOPIC_BACKUP_BLOCKED")
                self.assertFalse(world.backups.exists(), "막힌 백업은 빈 폴더도 남기지 않는다('아무것도 만들지 않음')")
                self.assertFalse(world.backups.parent.exists())
        with tempfile.TemporaryDirectory() as other:
            world = World(other)
            world.backups.mkdir(parents=True)
            (world.backups / "메모.txt").write_text("내 메모", encoding="utf-8")
            (world.data / layout.ENGINE_DB_FILE).write_bytes(os.urandom(4096))
            self.assertEqual(code_of(world.backup), "TOPIC_BACKUP_BLOCKED")
            self.assertEqual(os.listdir(world.backups), ["메모.txt"], "이미 있던 폴더와 그 안의 것은 그대로다")

    def test_the_reason_of_a_blocked_backup_names_the_real_cause_not_always_a_key_shape(self):
        cases = (("TOPIC_STORE_RECOVERY_PENDING", "정리 안 된 저장"), ("TOPIC_STORE_VERSION_UNSUPPORTED", "더 새로운 버전"), ("TOPIC_STORE_CORRUPT", "깨져"))
        for code, needle in cases:
            with self.subTest(code=code):
                with mock.patch.object(bk.TopicStore, "open", side_effect=AppError(code, {"파일": layout.ENGINE_DB_FILE}, detail="일부러 낸 오류")):
                    with self.assertRaises(AppError) as caught:
                        self.world.backup()
                self.assertEqual(caught.exception.code, "TOPIC_BACKUP_BLOCKED")
                reason = caught.exception.slots["이유"]
                self.assertIn(needle, reason)
                self.assertNotIn("키", reason, "키 모양이 아닌 이유에서 키 모양을 말하지 않는다")
        self.assertFalse(self.world.backups.exists())

    def test_a_key_shape_far_behind_the_first_200_thousand_characters_blocks_the_backup(self):
        pool = [ts.example_seed(seed_id=f"s{number:04d}", keyword=f"예시 씨앗 {number:04d} 번 낱말 모음") for number in range(1000)]
        pool[-1] = ts.example_seed(seed_id="s9999", keyword=f"예시 {FAKE_KEY}")
        put_json(self.world.data / layout.SEEDS_FILE, seeds.seeds_to_dict(pool))
        self.assertGreater((self.world.data / layout.SEEDS_FILE).stat().st_size, 250_000)
        self.assertEqual(code_of(self.world.backup), "TOPIC_BACKUP_BLOCKED", "앞 20만 자만 보면 놓친다 — 끝까지 훑는다")
        self.assertFalse(self.world.backups.exists())

    def test_a_utf8_bom_is_accepted_and_other_encodings_are_refused_with_the_file_error(self):
        good = json.dumps(seeds.seeds_to_dict([ts.example_seed()]), ensure_ascii=False, indent=2)
        for name, data in (("BOM+LF", b"\xef\xbb\xbf" + good.encode("utf-8")), ("BOM+CRLF", b"\xef\xbb\xbf" + good.replace("\n", "\r\n").encode("utf-8")), ("BOM 없음+CRLF", good.replace("\n", "\r\n").encode("utf-8"))):
            with self.subTest(case=name):
                self.assertEqual(len(bk.check_json_bytes(layout.SEEDS_FILE, data)), 1)
        for name, data in (("UTF-16(BOM)", good.encode("utf-16")), ("UTF-16(BOM 없음)", good.encode("utf-16-le")), ("cp949", good.encode("cp949"))):
            with self.subTest(case=name):
                self.assertEqual(code_of(bk.check_json_bytes, layout.SEEDS_FILE, data), "TOPIC_FILE_INVALID")

    def test_an_invalid_json_file_stops_the_backup_with_the_reason_and_changes_nothing(self):
        (self.world.data / layout.SEEDS_FILE).write_text("{not json", encoding="utf-8")
        self.assertEqual(code_of(self.world.backup), "TOPIC_FILE_INVALID")
        put_json(self.world.data / layout.SEEDS_FILE, {"schema": 1, "seeds": [{"seed_id": "x"}]})
        self.assertEqual(code_of(self.world.backup), "CONTENT_INVALID")
        self.assertFalse(self.world.backups.exists() and any(self.world.backups.iterdir()))

    def test_check_json_bytes_reads_strictly(self):
        good = json.dumps(seeds.seeds_to_dict([ts.example_seed()]), ensure_ascii=False).encode("utf-8")
        self.assertEqual(len(bk.check_json_bytes(layout.SEEDS_FILE, good)), 1)
        self.assertEqual(code_of(bk.check_json_bytes, layout.SEEDS_FILE, b"\xff\xfe\x00"), "TOPIC_FILE_INVALID")
        self.assertEqual(code_of(bk.check_json_bytes, layout.SEEDS_FILE, b"[1, 2"), "TOPIC_FILE_INVALID")
        self.assertEqual(code_of(bk.check_json_bytes, layout.SEEDS_FILE, b"{}"), "CONTENT_INVALID")
        self.assertEqual(code_of(bk.check_json_bytes, layout.CALENDAR_FILE, good), "CONTENT_INVALID", "씨앗 파일을 캘린더로 읽지 않는다")
        self.assertEqual(code_of(bk.check_json_bytes, layout.SEEDS_FILE, b" " * (bk.MAX_JSON_BYTES + 1)), "TOPIC_FILE_INVALID")
        small = b'{"schema": 1, "seeds": []}'                  # 올바른 JSON 에 공백만 덧붙여 크기만 키운다 — 크기 상한이 없으면 읽혀 버린다
        self.assertEqual(len(bk.check_json_bytes(layout.SEEDS_FILE, small + b" " * (bk.MAX_JSON_BYTES - len(small)))), 0, "상한과 같은 크기는 받는다")
        self.assertEqual(code_of(bk.check_json_bytes, layout.SEEDS_FILE, small + b" " * (bk.MAX_JSON_BYTES - len(small) + 1)), "TOPIC_FILE_INVALID", "올바른 JSON 이어도 상한을 넘으면 읽지 않는다")
        with self.assertRaises(ValueError):
            bk.check_json_bytes("other.json", good)


class ScanKeyShapeTest(unittest.TestCase):
    def test_a_key_shape_anywhere_in_a_long_text_is_found_including_across_window_edges(self):
        base = "가" * 320_000
        for position in (0, 100_000, 145_900, 149_000, 149_990, 150_000, 150_010, 291_800, 295_000, 319_990):
            with self.subTest(position=position):
                self.assertTrue(bk.scan_key_shape(base[:position] + " " + FAKE_KEY + " " + base[position:]))
        self.assertFalse(bk.scan_key_shape(base))
        self.assertFalse(bk.scan_key_shape(""))

    def test_a_key_between_200k_and_246k_characters_in_a_long_text_is_found(self):
        for position in (200_100, 220_000, 245_000):                 # `has_key_shape` 은 입력의 앞 20만 자만 본다 — 창이 그보다 크면 이 사이의 키를 놓친다
            with self.subTest(position=position):
                self.assertTrue(bk.scan_key_shape("가" * position + FAKE_KEY + "나" * (300_000 - position)))

    def test_a_long_token_that_straddles_a_window_edge_is_found_only_because_the_windows_overlap(self):
        token = "eyJ" + "A" * 97 + "." + "B" * 20 + "." + "C" * 20     # 첫 덩어리가 길어서 겹침이 짧으면 어느 창에도 온전히 들어가지 않는다
        text = "가" * (bk._KEY_WINDOW - (3 + 97 + 1 + 5)) + token + "나" * 40_000       # 창 경계가 두 번째 덩어리 안(5자째)에 온다
        self.assertFalse(has_key_shape(text[:bk._KEY_WINDOW]), "첫 창만으로는 알아보지 못한다")
        self.assertTrue(bk.scan_key_shape(text))

    def test_a_short_text_goes_through_the_plain_check_and_a_long_clean_text_is_clean(self):
        self.assertTrue(bk.scan_key_shape("키 " + FAKE_KEY))
        self.assertFalse(bk.scan_key_shape("키 없는 글 " * 100))
        self.assertFalse(bk.scan_key_shape("예시 문장입니다. " * 60_000))

    def test_hostile_texts_do_not_make_the_scan_blow_up(self):
        size = 1_000_000
        for name, hostile in (("sk- 반복", "sk-aa-" * (size // 6)), ("영숫자", "A1b2" * (size // 4)), ("Bearer 반복", "Bearer " * (size // 7)), ("한글", "가나다라" * (size // 4)),
                              ("줄바꿈 글", ("예시 문장입니다 " * 8 + "\n") * (size // 100))):
            with self.subTest(case=name):
                started = time.monotonic()
                bk.scan_key_shape(hostile)
                self.assertLess(time.monotonic() - started, 40, "정규식이 폭주하지 않는다(보통 1MB 에 1초 안팎)")

    def test_a_restore_refuses_a_backup_whose_json_has_a_key_shape_behind_the_first_200_thousand_characters(self):
        with tempfile.TemporaryDirectory() as other:
            world = World(other)
            backup = world.backup().path
            pool = [ts.example_seed(seed_id=f"s{number:04d}", keyword=f"예시 씨앗 {number:04d} 번 낱말 모음") for number in range(1000)]
            pool[-1] = ts.example_seed(seed_id="s9999", keyword=f"예시 {FAKE_KEY}")
            copy = Path(other) / "variants" / "topic-20260101-000021"
            copy.parent.mkdir()
            copy.mkdir()
            for entry in backup.iterdir():
                (copy / entry.name).write_bytes(entry.read_bytes())
            put_json(copy / layout.SEEDS_FILE, seeds.seeds_to_dict(pool))
            manifest = json.loads((copy / "MANIFEST.json").read_text(encoding="utf-8"))
            for name in manifest["files"]:
                data = (copy / name).read_bytes()
                manifest["files"][name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            (copy / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            before = digests(world.data)
            self.assertEqual(code_of(bk.restore_backup, copy, world.data, world.backups, now=NOW + datetime.timedelta(minutes=5)), "TOPIC_BACKUP_INVALID")
            self.assertEqual(digests(world.data), before)


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.first = self.world.backup(now=NOW).path
        self.second = self.world.backup(now=NOW + datetime.timedelta(seconds=1)).path

    def test_latest_a_name_and_a_path_inside_the_backups_folder_are_found(self):
        self.assertEqual(bk.resolve_backup(self.world.backups, latest=True), self.second)
        self.assertEqual(bk.resolve_backup(self.world.backups, self.first.name), self.first)
        self.assertEqual(bk.resolve_backup(self.world.backups, str(self.first)), self.first)
        safety = self.world.backups / bk.SAFETY_FOLDER / "topic-20260101-000000"
        safety.mkdir(parents=True)
        self.assertEqual(bk.resolve_backup(self.world.backups, f"{bk.SAFETY_FOLDER}/{safety.name}"), safety)

    def test_unknown_names_paths_that_climb_out_and_nothing_at_all_are_refused_without_echoing_the_typed_text(self):
        for ref in ("topic-20200101-000000", "../topic_engine", FAKE_KEY, "topic-20261106-080000/../x", str(self.world.data)):
            with self.subTest(ref=ref[:20]):
                with self.assertRaises(AppError) as caught:
                    bk.resolve_backup(self.world.backups, ref)
                self.assertEqual(caught.exception.code, "TOPIC_BACKUP_INVALID")
                self.assertNotIn(FAKE_KEY, str(caught.exception.slots) + str(caught.exception.detail))
        self.assertEqual(code_of(bk.resolve_backup, self.world.backups), "TOPIC_BACKUP_INVALID")
        self.assertEqual(code_of(bk.resolve_backup, self.world.backups / "none", latest=True), "TOPIC_BACKUP_INVALID")
        self.assertEqual(bk.list_backups(self.world.backups / "none"), [])

    def test_a_name_that_climbs_out_of_the_backups_folder_is_refused_even_if_a_backup_shaped_folder_is_there(self):
        outside = self.world.backups.parent / "topic-20260101-000009"                 # backups 폴더 바로 위(형제)에 백업 이름 모양의 폴더가 있다
        outside.mkdir()
        for ref in ("../topic-20260101-000009", "./../topic-20260101-000009", f"{bk.SAFETY_FOLDER}/../../topic-20260101-000009"):
            with self.subTest(ref=ref):
                self.assertEqual(code_of(bk.resolve_backup, self.world.backups, ref), "TOPIC_BACKUP_INVALID")


OS_REFUSALS = tuple(getattr(errno, name) for name in ("ENAMETOOLONG", "ELOOP", "ENOTDIR", "EACCES", "EIO", "ENOENT", "EBADF", "EINVAL") if hasattr(errno, name))
SHAPE_REFUSED = {                                                # 모양부터 걸러야 하는 친 글 — 파일 시스템에 묻기 전에 '찾을 수 없음'
    "name-256": "n" * 256,
    "name-261": "n" * 261,
    "hangul-258-bytes": "가" * 86 + "/topic-20260101-000000",
    "long-directory": "d" * 260 + "/topic-20260101-000000",
    "many-short-directories": "/".join(["s" * 40] * 8) + "/topic-20260101-000000",
    "backslashes": "C:\\" + "e" * 300 + "\\topic-20260101-000000",
    "newline": "topic-20260101-000000\n",
    "carriage-return": "topic-20260101-000000\r",
    "tab": "topic\t-20260101-000000",
    "nul": "topic-20260101-000000\0",
    "escape": "topic-20260101-000000\x1b",
    "delete": "topic-20260101-000000\x7f",
    "newline-in-directory": "dir\nname/topic-20260101-000000",                # 제어 문자가 이름(마지막 마디) 밖에 있어도 걸러야 한다 — 이름만 보면 백업 이름 모양이다
    "carriage-return-in-directory": "dir\rname/topic-20260101-000000",
    "tab-in-directory": "dir\tname/topic-20260101-000000",
    "nul-in-directory": "dir\0name/topic-20260101-000000",
    "escape-in-directory": "dir\x1bname/topic-20260101-000000",
    "delete-in-directory": "dir\x7fname/topic-20260101-000000",
}


class ResolveTypedTextTest(unittest.TestCase):
    """사용자가 친 백업 참조는 파일 시스템에 묻기 전에 모양부터 본다(D-80) — 리눅스는 이름이 너무 길면 `OSError(ENAMETOOLONG, '…: <그 이름>')` 를 내고 `pathlib` 은 ENOENT·ENOTDIR·EBADF·ELOOP 만 삼켜
    그 문구(친 글이 든)가 오류 세부로 올라가 화면에 되풀이됐다. 모양이 이상한 글은 OS 에 묻지 않고, 물어서 OS 가 거절해도 '찾을 수 없음' 일 뿐 친 글은 어디에도 없다."""

    TYPED = "typed" + "k" * 40                                   # 친 글의 알맹이 — 어디에도 되풀이되면 안 된다

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.made = self.world.backup(now=NOW).path

    @contextlib.contextmanager
    def watching(self, error=None):
        """파일 시스템에 묻는 호출(`os.stat`·`os.lstat`·`Path.stat`)을 지켜본다 — `error` 가 있으면 그 호출이 그 오류를 낸다(없으면 진짜로 돈다). 물은 호출 이름 목록을 준다."""
        real = {"os.stat": os.stat, "os.lstat": os.lstat, "Path.stat": Path.stat}
        asked = []

        def make(name):
            def call(*args, **kwargs):
                asked.append(name)
                if error is not None:
                    raise error
                return real[name](*args, **kwargs)
            return call

        with mock.patch.object(os, "stat", make("os.stat")), mock.patch.object(os, "lstat", make("os.lstat")), mock.patch.object(Path, "stat", make("Path.stat")):
            yield asked

    def refused(self, ref):
        with self.assertRaises(AppError) as caught:
            bk.resolve_backup(self.world.backups, ref)
        return caught.exception

    def assert_plain(self, error, *typed, refused_by_os=False):
        """쉬운 '백업을 찾을 수 없음' 이고, 친 글 조각(`typed`)이 칸·세부·화면 문구·기록 한 줄 어디에도 없다. OS 가 거절했으면 세부에 그 종류만 덧붙는다(이름은 없다)."""
        self.assertEqual(error.code, "TOPIC_BACKUP_INVALID")
        if refused_by_os:
            self.assertTrue(error.detail.startswith("백업 폴더에서 찾을 수 없다(OS 가 묻기를 거절했다: "), error.detail)
        else:
            self.assertEqual(error.detail, "백업 폴더에서 찾을 수 없다")
        shown = "\n".join([str(error.slots), error.detail, error.rendered().message, error.rendered().action, error.log_line(), str(error)])
        for piece in typed:
            self.assertGreaterEqual(len(piece), 8)
            self.assertNotIn(piece, shown)

    def test_a_text_with_a_strange_shape_is_refused_without_asking_the_filesystem(self):
        for name, ref in SHAPE_REFUSED.items():
            with self.subTest(name=name):
                with self.watching() as asked:
                    error = self.refused(ref)
                self.assertEqual(asked, [], "파일 시스템에 묻지 않았다")
                self.assert_plain(error, ref, ref[:12], ref[-12:])
                self.assertEqual(error.slots["파일"], "(입력한 파일)")

    def test_the_limits_are_two_hundred_fifty_five_bytes_a_part_and_two_hundred_sixty_characters_in_all(self):
        edge = "e" * 238 + "/topic-20260101-000000"
        self.assertEqual(len(edge), 260)
        with self.watching() as asked:
            self.assertEqual(self.refused(edge).code, "TOPIC_BACKUP_INVALID")
        self.assertTrue(asked, "한계 안의 글은(백업 이름 모양이므로) 파일 시스템에 묻는다 — 없는 폴더라서 '찾을 수 없음'")
        with self.watching() as asked:
            self.refused("e" * 239 + "/topic-20260101-000000")
        self.assertEqual(asked, [], "전체 261자는 묻지 않는다")
        with self.watching() as asked:
            self.refused("가" * 85 + "/topic-20260101-000000")
        self.assertTrue(asked, "마디 255바이트(한글 85자)는 한계 안이다")

    def test_a_path_of_short_hangul_directories_is_still_asked_about_even_when_the_bytes_add_up_past_255(self):
        """마디마다 짧은 한글 폴더 여러 개 — 합친 UTF-8 바이트(279)가 255 를 넘어도 마디 하나는 30바이트라 '한 마디가 너무 길다' 로 잘못 걸러지면 안 되고 파일 시스템에 묻는다.
        `/` 로 이은 경로라 어느 OS 에서 돌려도 같다(백슬래시 판은 아래 윈도 전용 시험과 모양 판정 함수 시험이 맡는다)."""
        ref = "사용자/" + "/".join(["가나다라마바사아자차"] * 9) + "/topic-20260101-000000"
        self.assertLessEqual(len(ref), 260)
        self.assertGreater(len(ref.encode("utf-8")), 255)
        with self.watching() as asked:
            error = self.refused(ref)
        self.assertTrue(asked, "한계 안의 경로는 파일 시스템에 묻는다(없는 폴더라서 '찾을 수 없음')")
        self.assertEqual(error.code, "TOPIC_BACKUP_INVALID")

    @unittest.skipUnless(os.name == "nt", "리눅스에서는 `\\` 가 파일 이름의 글자라 `Path(ref).name` 이 글 전체가 되어 백업 이름 모양이 아니므로 묻지 않는다 — 윈도 경로 풀이(`C:\\…\\topic-…` 의 이름이 마지막 마디)는 윈도에서만 시험한다")
    def test_a_windows_style_path_of_short_hangul_directories_is_still_asked_about(self):
        """`\\` 도 마디 구분으로 본다 — 한글 폴더가 많은 윈도 경로(마디마다 30바이트, 합쳐 270바이트 넘음)는 한 마디로 잘못 읽혀 걸러지면 안 된다."""
        folders = "\\".join(["가나다라마바사아자차"] * 9)
        ref = "C:\\사용자\\" + folders + "\\topic-20260101-000000"
        self.assertLessEqual(len(ref), 260)
        self.assertGreater(len(ref.encode("utf-8")), 255)
        with self.watching() as asked:
            error = self.refused(ref)
        self.assertTrue(asked, "한계 안의 윈도 경로는 파일 시스템에 묻는다(없는 폴더라서 '찾을 수 없음')")
        self.assertEqual(error.code, "TOPIC_BACKUP_INVALID")

    def test_the_shape_judgement_reads_backslashes_and_slashes_alike_as_part_separators_on_every_os(self):
        """`_ref_has_a_path_shape` 는 `re.split` 으로 `/`·`\\` 를 둘 다 마디 구분으로 보는 순수 함수라 어느 OS 에서 돌려도 같다 — 마디가 255바이트 이하면 통과, 한 마디라도 넘으면 거절(전체 260자 한계는 따로 지키려고 아래 글은 모두 260자 이하다). 파일 시스템에 묻는지는 보지 않는다."""
        short = "가나다라마바사아자차"                                              # 한 마디 30바이트
        accepted = {
            "backslash path of nine short hangul directories": "C:\\사용자\\" + "\\".join([short] * 9) + "\\topic-20260101-000000",
            "slash path of nine short hangul directories": "사용자/" + "/".join([short] * 9) + "/topic-20260101-000000",
            "mixed separators": "C:\\사용자/" + "\\".join([short] * 4) + "/" + "/".join([short] * 5) + "\\topic-20260101-000000",
            "a part of exactly 255 bytes between backslashes": "a\\" + "b" * 255 + "\\c",
            "a part of exactly 255 bytes between slashes": "a/" + "b" * 255 + "/c",
            "a hangul part of exactly 255 bytes": "D:\\" + "가" * 85,
        }
        for name, ref in accepted.items():
            with self.subTest(accepted=name):
                self.assertLessEqual(len(ref), 260)
                self.assertTrue(bk._ref_has_a_path_shape(ref))
        refused = {
            "a part of 256 bytes between backslashes": "a\\" + "b" * 256 + "\\c",
            "a part of 256 bytes between slashes": "a/" + "b" * 256 + "/c",
            "a part of 256 bytes between mixed separators": "a\\" + "b" * 256 + "/c",
            "a hangul part of 258 bytes after a drive": "D:\\" + "가" * 86,
            "a long part first": "b" * 256 + "\\x",
            "a long part last": "C:\\" + "b" * 256,
        }
        for name, ref in refused.items():
            with self.subTest(refused=name):
                self.assertLessEqual(len(ref), 260, "마디 규칙만 시험한다 — 전체 길이 규칙에 걸리면 안 된다")
                self.assertFalse(bk._ref_has_a_path_shape(ref))
        at_the_limit = "\\".join(["x" * 60] * 4 + ["y" * 16])                      # 마디 다섯(모두 짧다)·전체 260자
        self.assertEqual(len(at_the_limit), 260)
        self.assertTrue(bk._ref_has_a_path_shape(at_the_limit))
        self.assertFalse(bk._ref_has_a_path_shape(at_the_limit + "z"), "전체 261자는 마디가 모두 짧아도 거절")

    def test_a_text_whose_name_is_not_a_backup_name_is_not_asked_about_either(self):
        for ref in ("somewhere", "somewhere/else", "a" * 200, "x/topic-2026", "topic-20260101-000000.bak", "topic-20260101-000000/inner", "../outside"):
            with self.subTest(ref=ref[:30]):
                with self.watching() as asked:
                    error = self.refused(ref)
                self.assertEqual(asked, [])
                self.assertEqual(error.code, "TOPIC_BACKUP_INVALID")

    def test_a_refusal_from_the_operating_system_is_the_same_plain_not_found_error_with_no_name_in_it(self):
        """ENAMETOOLONG·ELOOP·ENOTDIR·EACCES(그 밖 몇 가지 포함) — 모양은 통과한 글을 OS 가 거절해도 같은 쉬운 오류이고 세부에 이름·OS 문구가 없다."""
        for number in OS_REFUSALS:
            for label, ref in (("relative", f"{self.TYPED}/topic-20260101-000000"), ("absolute", str(Path(self.tmp.name) / self.TYPED / "topic-20260101-000000"))):
                refusal = OSError(number, os.strerror(number), ref)
                with self.subTest(errno=errno.errorcode.get(number, number), ref=label):
                    with self.watching(refusal) as asked:
                        error = self.refused(ref)
                    self.assertTrue(asked, "OS 에 물었다(모양 검사는 통과)")
                    swallowed_by_pathlib = number in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EBADF)          # `Path.is_dir()` 가 스스로 삼키는 것 — 나머지는 `_is_directory` 가 받는다
                    self.assert_plain(error, self.TYPED, ref, refused_by_os=not swallowed_by_pathlib)
                    self.assertEqual(error.slots["파일"], "topic-20260101-000000", "백업 이름 모양이므로 이름만 보인다")
                    self.assertNotIn(os.strerror(number), error.rendered().message)
                    if not swallowed_by_pathlib:
                        self.assertIn(f"errno={number} {os.strerror(number)}", error.detail, "거절한 종류는 세부에 남는다(원인을 숨기지 않는다)")

    def test_the_directory_question_turns_any_refusal_into_no(self):
        ref = Path(self.TYPED) / "topic-20260101-000000"
        for number in OS_REFUSALS:
            with self.subTest(errno=errno.errorcode.get(number, number)):
                refusals = []
                with mock.patch.object(Path, "is_dir", side_effect=OSError(number, os.strerror(number), str(ref))):
                    self.assertIs(bk._is_directory(ref, refusals), False)
                self.assertEqual(len(refusals), 1)
                self.assertIn(f"errno={number} {os.strerror(number)}", refusals[0], "거절한 종류가 남는다")
                self.assertNotIn(self.TYPED, refusals[0], "파일 이름(친 글)은 없다")
        refusals = []
        with mock.patch.object(Path, "is_dir", side_effect=ValueError("embedded null byte " + self.TYPED)):
            self.assertIs(bk._is_directory(ref, refusals), False)
        self.assertEqual(refusals, ["ValueError"], "예외 이름만 남고 문구(친 글이 낄 수 있다)는 없다")
        refusals = []
        self.assertIs(bk._is_directory(self.made, refusals), True, "진짜 폴더는 그대로 참")
        self.assertIs(bk._is_directory(self.made / "nothing", refusals), False)
        self.assertEqual(refusals, [], "그냥 없는 폴더는 거절이 아니다")

    def test_real_backups_are_still_found_by_name_by_path_and_by_the_folder_inside_the_backups_folder(self):
        self.assertEqual(bk.resolve_backup(self.world.backups, self.made.name), self.made)
        self.assertEqual(bk.resolve_backup(self.world.backups, str(self.made)), self.made)
        self.assertEqual(bk.resolve_backup(self.world.backups, str(self.made).replace("\\", "/")), self.made)


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.backup = self.world.backup().path
        self.later = NOW + datetime.timedelta(minutes=5)

    def change_live(self):
        with TopicStore.open(self.world.data / layout.ENGINE_DB_FILE) as store:
            store.add_candidates(lambda existing: [candidate(3)], now=STAMP)
        put_json(self.world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(seed_id="changed-1", keyword="예시 바뀐 씨앗")]))

    def restore(self, backup=None, **kwargs):
        return bk.restore_backup(backup or self.backup, self.world.data, self.world.backups, now=self.later, **kwargs)

    def test_restore_brings_back_the_backed_up_state_and_keeps_the_state_before_in_a_safety_backup(self):
        original_seeds = (self.world.data / layout.SEEDS_FILE).read_bytes()
        self.change_live()
        changed_seeds = (self.world.data / layout.SEEDS_FILE).read_bytes()
        result = self.restore()
        self.assertEqual((result.source, result.restored, result.kept, result.moved_aside), (self.backup, layout.USER_DATA_FILES, (), None))
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])
        self.assertEqual((self.world.data / layout.SEEDS_FILE).read_bytes(), original_seeds)
        self.assertEqual(result.safety.parent.name, bk.SAFETY_FOLDER)
        self.assertEqual((result.safety / layout.SEEDS_FILE).read_bytes(), changed_seeds, "바꾸기 직전 상태가 안전 백업에 있다")
        with TopicStore.open(result.safety / layout.ENGINE_DB_FILE, migrate=False) as before:
            self.assertEqual(before.count(), 3)
        self.assertEqual([entry for entry in os.listdir(self.world.data) if entry.endswith(".restoring")], [])
        again = self.restore(result.safety)                       # 안전 백업으로 되돌리면 다시 3개
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002", "cid-003"])
        self.assertEqual((self.world.data / layout.SEEDS_FILE).read_bytes(), changed_seeds)
        self.assertEqual(again.safety.parent.name, bk.SAFETY_FOLDER)

    def test_a_bad_backup_is_refused_before_anything_is_changed(self):
        self.change_live()
        live_before = digests(self.world.data)
        cases = {}

        def copy(name):
            target = Path(self.tmp.name) / "bad" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.mkdir()
            for entry in self.backup.iterdir():
                (target / entry.name).write_bytes(entry.read_bytes())
            return target

        broken_db = copy("topic-20260101-000001")
        with open(broken_db / layout.ENGINE_DB_FILE, "r+b") as handle:
            handle.seek(2000)
            handle.write(b"\x00\x01\x02")
        cases["보관함 바이트가 바뀜"] = broken_db
        no_manifest = copy("topic-20260101-000002")
        (no_manifest / "MANIFEST.json").unlink()
        cases["목록 없음"] = no_manifest
        extra = copy("topic-20260101-000003")
        (extra / "notes.txt").write_text("낯선 파일", encoding="utf-8")
        cases["낯선 파일"] = extra
        bad_manifest = copy("topic-20260101-000004")
        manifest = json.loads((bad_manifest / "MANIFEST.json").read_text(encoding="utf-8"))
        manifest["files"]["secret.json"] = manifest["files"]["seeds.json"]
        (bad_manifest / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
        cases["목록에 모르는 이름"] = bad_manifest
        wrong_json = copy("topic-20260101-000005")
        (wrong_json / layout.SEEDS_FILE).write_text('{"schema": 1, "seeds": [{"seed_id": "x"}]}', encoding="utf-8")
        self.rewrite_manifest(wrong_json)
        cases["모양이 틀린 JSON(해시는 맞음)"] = wrong_json
        foreign = copy("topic-20260101-000006")
        (foreign / layout.ENGINE_DB_FILE).unlink()
        with sqlite3.connect(str(foreign / layout.ENGINE_DB_FILE)) as connection:
            connection.execute("CREATE TABLE other (x TEXT)")
        connection.close()
        self.rewrite_manifest(foreign)
        cases["다른 프로그램의 SQLite(해시는 맞음)"] = foreign
        keyed = copy("topic-20260101-000007")
        put_json(keyed / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(keyword=f"예시 {FAKE_KEY}")]))
        self.rewrite_manifest(keyed)
        cases["키 모양이 든 백업(해시는 맞음)"] = keyed
        wrong_name = copy("not-a-backup-name")
        cases["이름이 백업 이름이 아님"] = wrong_name
        for name, folder in cases.items():
            with self.subTest(case=name):
                self.assertEqual(code_of(self.restore, folder), "TOPIC_BACKUP_INVALID")
                self.assertEqual(digests(self.world.data), live_before, "지금 데이터는 한 바이트도 바뀌지 않았다")
        self.assertFalse((self.world.backups / bk.SAFETY_FOLDER).exists(), "거절한 복원은 안전 백업도 만들지 않는다")
        self.assertEqual(code_of(self.restore, Path(self.tmp.name) / "does-not-exist"), "TOPIC_BACKUP_INVALID")

    def rewrite_manifest(self, folder):
        manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
        for name in manifest["files"]:
            data = (folder / name).read_bytes()
            manifest["files"][name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        (folder / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    def folder_copy(self, name):
        target = Path(self.tmp.name) / "variants" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir()
        for entry in self.backup.iterdir():
            (target / entry.name).write_bytes(entry.read_bytes())
        return target

    def test_a_file_changed_after_it_was_listed_is_refused_even_when_its_size_and_shape_are_fine(self):
        self.change_live()
        live_before = digests(self.world.data)
        folder = self.folder_copy("topic-20260101-000011")
        path = folder / layout.SEEDS_FILE
        data = path.read_bytes()
        self.assertEqual(data.count(b"ex-seed-001"), 1)
        path.write_bytes(data.replace(b"ex-seed-001", b"ex-seed-002"))                 # 같은 길이·올바른 모양 — 목록의 해시만 다르다
        self.assertEqual(len(path.read_bytes()), len(data))
        self.assertEqual(len(bk.check_json_bytes(layout.SEEDS_FILE, path.read_bytes())), 1)
        self.assertEqual(code_of(self.restore, folder), "TOPIC_BACKUP_INVALID")
        self.assertEqual(digests(self.world.data), live_before)

    def test_a_listed_file_with_an_unknown_name_is_refused_even_when_the_file_and_its_hash_are_there(self):
        self.change_live()
        live_before = digests(self.world.data)
        folder = self.folder_copy("topic-20260101-000012")
        (folder / "secret.json").write_bytes((folder / layout.SEEDS_FILE).read_bytes())
        manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
        manifest["files"]["secret.json"] = manifest["files"][layout.SEEDS_FILE]
        (folder / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(code_of(self.restore, folder), "TOPIC_BACKUP_INVALID")
        self.assertEqual(digests(self.world.data), live_before)

    def test_a_key_shape_or_a_row_inconsistency_inside_the_database_of_a_backup_is_refused(self):
        self.change_live()
        live_before = digests(self.world.data)
        keyed = self.folder_copy("topic-20260101-000013")
        other = Path(self.tmp.name) / "keyed.db"
        with TopicStore.open(other) as store:
            store.add_candidates(lambda existing: [ts.rated(70, candidate_id="cid-099", channel="naver_a", topic=f"예시 {FAKE_KEY} 모음", created_at=STAMP)], now=STAMP)
        (keyed / layout.ENGINE_DB_FILE).write_bytes(other.read_bytes())
        self.rewrite_manifest(keyed)
        broken = self.folder_copy("topic-20260101-000014")
        with contextlib.closing(sqlite3.connect(str(broken / layout.ENGINE_DB_FILE))) as connection:
            with connection:
                connection.execute("UPDATE score_snapshots SET data = '{}' WHERE candidate_id = 'cid-001'")
        self.rewrite_manifest(broken)
        for name, folder in (("키 모양", keyed), ("행 자료가 어긋남", broken)):
            with self.subTest(case=name):
                self.assertEqual(code_of(self.restore, folder), "TOPIC_BACKUP_INVALID")
                self.assertEqual(digests(self.world.data), live_before)

    def test_a_current_json_with_a_key_shape_stops_the_restore_before_anything_changes(self):
        put_json(self.world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(keyword=f"예시 {FAKE_KEY}")]))
        before = digests(self.world.data)
        with self.assertRaises(AppError) as caught:
            self.restore()
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_BLOCKED")
        self.assertIn(layout.SEEDS_FILE, caught.exception.slots["이유"], "어느 파일인지 알려 준다")
        self.assertIn("아무것도 바꾸지 않았습니다", caught.exception.slots["이유"], "되돌리기를 시작하기 전에 멈췄다고 말한다(백업 만들기의 거절 문구와 다르다)")
        self.assertNotIn(FAKE_KEY, str(caught.exception.slots) + str(caught.exception.detail))
        self.assertEqual(digests(self.world.data), before, "한 바이트도 안 바뀌었다 — 멀쩡한 보관함도 옆으로 옮기지 않았다")
        self.assertFalse((self.world.backups / bk.SAFETY_FOLDER).exists(), "직전 상태를 담지 못하니 시작하지 않았다")
        self.assertEqual([name for name in os.listdir(self.world.data) if ".bad-" in name], [])
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])

    def test_a_key_shape_inside_a_healthy_current_database_stops_the_restore_too(self):
        with contextlib.closing(sqlite3.connect(str(self.world.data / layout.ENGINE_DB_FILE))) as connection:
            with connection:
                connection.execute("UPDATE candidates SET saved_at = ? WHERE candidate_id = 'cid-001'", (STAMP + " " + FAKE_KEY,))
        before = digests(self.world.data)
        with self.assertRaises(AppError) as caught:
            self.restore()
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_BLOCKED")
        self.assertIn(layout.ENGINE_DB_FILE, caught.exception.slots["이유"], "어느 파일인지 알려 준다")
        self.assertIn("아무것도 바꾸지 않았습니다", caught.exception.slots["이유"], "되돌리기를 시작하기 전에 멈췄다고 말한다")
        self.assertEqual(digests(self.world.data), before)
        self.assertFalse((self.world.backups / bk.SAFETY_FOLDER).exists())
        self.assertEqual([name for name in os.listdir(self.world.data) if ".bad-" in name], [], "멀쩡한 보관함을 '깨졌다' 며 옮기지 않는다")

    def test_a_key_shaped_file_that_the_backup_does_not_replace_does_not_block_the_restore(self):
        partial = self.world.backup(now=NOW + datetime.timedelta(seconds=7), names=(layout.CALENDAR_FILE,)).path
        self.assertEqual(sorted(os.listdir(partial)), ["MANIFEST.json", layout.CALENDAR_FILE], "담을 파일만 담는다")
        put_json(self.world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(keyword=f"예시 {FAKE_KEY}")]))
        seeds_before = (self.world.data / layout.SEEDS_FILE).read_bytes()
        put_json(self.world.data / layout.CALENDAR_FILE, schedule.entries_to_dict([ts.example_entry(entry_id="ex-cal-002", name="예시 바뀐 시기")]))
        result = bk.restore_backup(partial, self.world.data, self.world.backups, now=self.later)
        self.assertEqual(result.restored, (layout.CALENDAR_FILE,))
        self.assertEqual((self.world.data / layout.SEEDS_FILE).read_bytes(), seeds_before, "바뀌지 않는 파일은 그대로(키 모양이 있어도 막지 않는다)")
        self.assertEqual(sorted(os.listdir(result.safety)), ["MANIFEST.json", layout.CALENDAR_FILE], "바뀌는 파일의 직전 상태만 남긴다")

    def test_a_broken_current_json_is_kept_aside_verbatim_and_the_restore_goes_on(self):
        self.change_live()
        broken = b'{"schema": 1, "seeds": [oops'
        (self.world.data / layout.SEEDS_FILE).write_bytes(broken)
        result = self.restore()
        self.assertEqual(len(result.moved_json), 1)
        self.assertEqual(result.moved_json[0].read_bytes(), broken, "깨진 파일은 한 바이트도 안 바뀐 채 옆에 있다")
        self.assertTrue(result.moved_json[0].name.startswith(layout.SEEDS_FILE + ".bad-"))
        self.assertEqual((self.world.data / layout.SEEDS_FILE).read_bytes(), (self.backup / layout.SEEDS_FILE).read_bytes(), "그 자리에는 백업의 파일이 들어갔다")
        self.assertNotIn(layout.SEEDS_FILE, os.listdir(result.safety), "깨진 파일은 검사를 거쳐야 하는 직전 상태 백업에 담지 않고 옆에 보존한다")
        self.assertEqual(sorted(os.listdir(result.safety)), sorted(["MANIFEST.json", layout.CHANNEL_PROFILES_FILE, layout.CALENDAR_FILE, layout.ENGINE_DB_FILE]))
        self.assertIsNone(result.moved_aside)

    def test_a_broken_json_and_a_broken_store_together_are_both_kept_aside(self):
        self.change_live()
        (self.world.data / layout.SEEDS_FILE).write_bytes(b"{")
        junk = os.urandom(4096)
        (self.world.data / layout.ENGINE_DB_FILE).write_bytes(junk)
        result = self.restore()
        self.assertEqual(result.moved_aside.read_bytes(), junk)
        self.assertEqual(result.moved_json[0].read_bytes(), b"{")
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])

    def test_the_unfinished_save_file_of_a_broken_store_is_cleared_when_the_store_is_moved_aside(self):
        self.change_live()
        database = self.world.data / layout.ENGINE_DB_FILE
        database.write_bytes(os.urandom(4096))
        journal = Path(str(database) + "-journal")
        journal.write_bytes(b"")                                                       # 비어 있는 저널(0바이트)은 '정리 못 한 저장' 이 아니라 읽기 전용 열기가 거절하지 않는다 — 깨진 보관함만 옆으로 옮겨진다
        result = self.restore()
        self.assertFalse(journal.exists(), "깨진 보관함을 옮길 때 그 저널 파일도 치워 새 보관함 옆에 남지 않게 한다")
        self.assertTrue(result.moved_aside is not None and result.moved_aside.exists())
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])

    def test_moving_a_broken_store_aside_clears_whatever_unfinished_save_file_it_left_next_to_it(self):
        database = self.world.data / layout.ENGINE_DB_FILE
        junk = os.urandom(4096)
        database.write_bytes(junk)
        journal = Path(str(database) + "-journal")
        journal.write_bytes(os.urandom(700))                                             # 새 보관함 옆에 남으면 잘못 적용될 수 있는 옛 저널 — 안에 무엇이 들었든 함께 치운다
        moved = bk._move_aside(self.world.data, layout.ENGINE_DB_FILE, self.later)
        self.assertEqual(moved.read_bytes(), junk, "깨진 보관함은 지우지 않고 한 바이트도 안 바뀐 채 옆으로 옮겨진다")
        self.assertFalse(database.exists())
        self.assertFalse(journal.exists(), "그 저널 파일도 함께 치운다")
        self.assertIsNone(bk._move_aside(self.world.data, layout.ENGINE_DB_FILE, self.later), "옮길 파일이 없으면 아무것도 안 한다")

    def break_current_files(self):
        """깨진 보관함·깨진 씨앗 JSON·백업과 다른 멀쩡한 캘린더 — 복원이 앞의 둘을 옆으로 옮기고 캘린더를 바꾸게 하는 지금 상태."""
        database, seeds_path = self.world.data / layout.ENGINE_DB_FILE, self.world.data / layout.SEEDS_FILE
        junk, broken = b"junk" * 1024, b'{"seeds": [oops'
        database.write_bytes(junk)
        seeds_path.write_bytes(broken)
        put_json(self.world.data / layout.CALENDAR_FILE, schedule.entries_to_dict([ts.example_entry(entry_id="ex-cal-002", name="예시 바뀐 시기")]))
        return database, junk, seeds_path, broken

    def test_a_key_shape_only_in_the_current_published_history_ledger_does_not_stop_the_restore(self):
        record = hist.HistoryRecord(channel="naver_a", title=f"예시 발행 글 {FAKE_KEY}", keywords=(), date="2026-10-01", ref="p1", origin="naver_items")
        with TopicStore.open(self.world.data / layout.ENGINE_DB_FILE) as store:
            store.sync_history([record], now=STAMP)
        result = self.restore()
        self.assertEqual(result.restored, layout.USER_DATA_FILES)
        self.assertIsNotNone(result.safety, "바꾸기 직전 상태는 안전 백업에 남는다")
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])

    def test_a_zero_byte_current_store_is_neither_backed_up_nor_moved_aside(self):
        (self.world.data / layout.ENGINE_DB_FILE).write_bytes(b"")
        result = self.restore()
        self.assertIsNone(result.moved_aside, "0바이트는 깨진 보관함이 아니라 '아직 없음' 이다")
        self.assertEqual([name for name in os.listdir(self.world.data) if ".bad-" in name], [])
        self.assertNotIn(layout.ENGINE_DB_FILE, os.listdir(result.safety), "담을 내용이 없다")
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])

    def test_a_current_store_that_opens_but_fails_its_own_check_is_moved_aside_and_not_backed_up(self):
        database = self.world.data / layout.ENGINE_DB_FILE
        with contextlib.closing(sqlite3.connect(str(database))) as connection:
            with connection:
                connection.execute("UPDATE candidates SET final_score = final_score + 1 WHERE candidate_id = 'cid-001'")
        with TopicStore.open(database, migrate=False) as store:
            self.assertTrue(store.check(), "점검이 문제를 찾는 상태다")
        result = self.restore()
        self.assertIsNotNone(result.moved_aside, "점검을 통과하지 못하는 보관함은 멀쩡한 것으로 보지 않는다")
        self.assertNotIn(layout.ENGINE_DB_FILE, os.listdir(result.safety))
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])

    def test_an_aside_name_that_is_already_taken_is_never_overwritten(self):
        stamp = self.later.strftime("%Y%m%d-%H%M%S")
        taken = [self.world.data / f"{layout.ENGINE_DB_FILE}.bad-{stamp}", self.world.data / f"{layout.ENGINE_DB_FILE}.bad-{stamp}-2"]
        for number, path in enumerate(taken):
            path.write_bytes(f"먼저 있던 파일 {number}".encode())
        (self.world.data / layout.ENGINE_DB_FILE).write_bytes(os.urandom(4096))
        result = self.restore()
        self.assertEqual([path.read_bytes() for path in taken], ["먼저 있던 파일 0".encode(), "먼저 있던 파일 1".encode()], "같은 이름이 이미 있으면 덮어쓰지 않는다")
        self.assertEqual(result.moved_aside.name, taken[0].name + "-3")

    def test_a_second_failure_while_rolling_back_still_puts_the_moved_files_back_and_names_what_it_could_not_undo(self):
        database, junk, seeds_path, broken = self.break_current_files()
        calendar_before = (self.world.data / layout.CALENDAR_FILE).read_bytes()
        state, real_write = {"rolling": False}, bk._write_bytes

        def fail_restore(self_, backup):
            state["rolling"] = True
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 첫 실패")

        def full_disk(path, data):
            if state["rolling"]:
                raise OSError(errno.ENOSPC, "일부러 낸 디스크 가득")
            return real_write(path, data)

        with mock.patch.object(TopicStore, "restore_from", fail_restore), mock.patch.object(bk, "_write_bytes", full_disk):
            with self.assertRaises(AppError) as caught:
                self.restore()
        self.assertEqual(caught.exception.code, "TOPIC_STORE_LOCKED", "원래 오류 분류가 그대로다 — 두 번째 실패가 원시 OSError 로 새지 않는다")
        notes = " ".join(caught.exception.notes)
        self.assertIn(layout.CALENDAR_FILE, notes, "원래 내용으로 돌리지 못한 파일의 이름")
        self.assertIn(bk.SAFETY_FOLDER, notes, "그 원래 내용이 어디 있는지")
        self.assertEqual(seeds_path.read_bytes(), broken, "옮겨 둔 깨진 JSON 이 제자리로 돌아왔다(되돌리기가 건너뛰어지지 않는다)")
        self.assertEqual(database.read_bytes(), junk, "옮겨 둔 깨진 보관함도 제자리로 돌아왔다")
        self.assertEqual([name for name in os.listdir(self.world.data) if ".bad-" in name or name.endswith(".restoring")], [])
        safety = bk.list_backups(self.world.backups / bk.SAFETY_FOLDER)[0]
        self.assertEqual((safety / layout.CALENDAR_FILE).read_bytes(), calendar_before, "돌리지 못한 파일의 원래 내용은 직전 상태 백업에 있다")

    def test_a_move_that_cannot_be_undone_is_named_and_the_other_moved_file_is_still_put_back(self):
        database, junk, seeds_path, broken = self.break_current_files()
        real_replace = os.replace

        def fail_restore(self_, backup):
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 첫 실패")

        def replace(source, target, *args, **kwargs):
            if Path(source).name.startswith(layout.SEEDS_FILE + ".bad-"):
                raise PermissionError(errno.EACCES, "일부러 낸 권한 오류")
            return real_replace(source, target, *args, **kwargs)

        with mock.patch.object(TopicStore, "restore_from", fail_restore), mock.patch("os.replace", replace):
            with self.assertRaises(AppError) as caught:
                self.restore()
        self.assertEqual(caught.exception.code, "TOPIC_STORE_LOCKED", "원래 오류 분류가 그대로다")
        aside = [name for name in os.listdir(self.world.data) if name.startswith(layout.SEEDS_FILE + ".bad-")]
        self.assertEqual(len(aside), 1)
        notes = " ".join(caught.exception.notes)
        self.assertIn(layout.SEEDS_FILE, notes)
        self.assertIn(aside[0], notes, "옮겨 둔 이름을 알린다")
        self.assertEqual((self.world.data / aside[0]).read_bytes(), broken, "깨진 JSON 은 그 이름으로 그대로 있다")
        self.assertEqual(database.read_bytes(), junk, "다른 옮긴 파일은 제자리로 돌아왔다")

    def test_a_temp_file_that_cannot_be_removed_does_not_stop_the_rollback(self):
        database, junk, seeds_path, broken = self.break_current_files()
        real_write, real_remove, writes = bk._write_bytes, bk._remove_file, {"n": 0}

        def failing_write(path, data):                              # 두 번째 JSON 쓰기에서 디스크 가득 — 앞에서 쓴 임시 파일이 남는다
            if str(path).endswith(".restoring"):
                writes["n"] += 1
                if writes["n"] == 2:
                    raise OSError(errno.ENOSPC, "일부러 낸 디스크 가득")
            return real_write(path, data)

        def stubborn_remove(path):                                  # 임시 파일은 치워지지 않는다(백신·동기화가 잡은 순간)
            if str(path).endswith(".restoring"):
                raise PermissionError(errno.EACCES, "일부러 낸 권한 오류")
            return real_remove(path)

        with mock.patch.object(bk, "_write_bytes", failing_write), mock.patch.object(bk, "_remove_file", stubborn_remove):
            with self.assertRaises(AppError) as caught:
                self.restore()
        self.assertEqual(caught.exception.code, "DISK_FULL", "첫 실패의 쉬운 오류가 그대로 나간다 — 임시 파일 치우기 실패가 원시 오류로 새지 않는다")
        self.assertEqual(seeds_path.read_bytes(), broken, "임시 파일을 못 치워도 옮겨 둔 깨진 JSON 은 제자리로 돌아온다")
        self.assertEqual(database.read_bytes(), junk, "옮겨 둔 깨진 보관함도 제자리로 돌아온다")
        self.assertEqual([name for name in os.listdir(self.world.data) if ".bad-" in name], [])

    def test_a_partial_temp_file_left_by_a_failed_rollback_write_is_removed(self):
        self.break_current_files()
        state, real_write = {"rolling": False}, bk._write_bytes

        def fail_restore(self_, backup):
            state["rolling"] = True
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 첫 실패")

        def half_write(path, data):                                 # 디스크가 가득 차기 전에 쓴 일부가 임시 파일로 남는다
            if state["rolling"]:
                Path(path).write_bytes(data[:3])
                raise OSError(errno.ENOSPC, "일부러 낸 디스크 가득")
            return real_write(path, data)

        with mock.patch.object(TopicStore, "restore_from", fail_restore), mock.patch.object(bk, "_write_bytes", half_write):
            self.assertEqual(code_of(self.restore), "TOPIC_STORE_LOCKED")
        self.assertEqual([name for name in os.listdir(self.world.data) if name.endswith(".restoring")], [], "되돌리다 실패해 남은 임시 파일을 치운다")

    def test_a_journal_file_left_next_to_the_new_store_is_removed_with_it(self):
        database = self.world.data / layout.ENGINE_DB_FILE
        journal = Path(str(database) + "-journal")

        def fail_restore(self_, backup):
            journal.write_bytes(os.urandom(600))                    # 보관함 단계가 도중에 멈춰 남긴 저널
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 실패")

        for start in ("absent", "blank"):
            with self.subTest(start=start):
                database.unlink(missing_ok=True)
                if start == "blank":
                    database.write_bytes(b"")
                with mock.patch.object(TopicStore, "restore_from", fail_restore):
                    self.assertEqual(code_of(self.restore), "TOPIC_STORE_LOCKED")
                self.assertFalse(journal.exists(), "복원이 만든 새 보관함의 저널도 함께 치운다")
                self.assertEqual(database.exists() and database.stat().st_size, 0 if start == "blank" else False)

    def test_a_new_store_that_cannot_be_removed_is_named_and_the_moved_files_are_still_put_back(self):
        database, seeds_path, broken = self.world.data / layout.ENGINE_DB_FILE, self.world.data / layout.SEEDS_FILE, b'{"seeds": [oops'
        database.unlink()
        seeds_path.write_bytes(broken)
        real_remove = bk._remove_file

        def fail_restore(self_, backup):
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 실패")

        def stubborn(path):
            if Path(path).name == layout.ENGINE_DB_FILE:
                raise PermissionError(errno.EACCES, "일부러 낸 권한 오류")
            return real_remove(path)

        with mock.patch.object(TopicStore, "restore_from", fail_restore), mock.patch.object(bk, "_remove_file", stubborn):
            with self.assertRaises(AppError) as caught:
                self.restore()
        self.assertEqual(caught.exception.code, "TOPIC_STORE_LOCKED", "원래 오류 코드가 그대로다 — 새 보관함을 못 치운 것이 원시 오류로 새지 않는다")
        self.assertIn(layout.ENGINE_DB_FILE, " ".join(caught.exception.notes), "못 치운 새 보관함은 이름으로 알린다")
        self.assertEqual(seeds_path.read_bytes(), broken, "그래도 옮겨 둔 깨진 JSON 은 제자리로 돌아온다")
        self.assertEqual([name for name in os.listdir(self.world.data) if ".bad-" in name], [])

    def test_a_failure_before_the_store_step_never_touches_a_zero_byte_store(self):
        database = self.world.data / layout.ENGINE_DB_FILE
        database.write_bytes(b"")
        touched, real_write, real_remove, writes = [], bk._write_bytes, bk._remove_file, {"n": 0}

        def spy_write(path, data):
            touched.append(Path(path).name)
            if str(path).endswith(".restoring"):
                writes["n"] += 1
                if writes["n"] == 2:
                    raise OSError(errno.ENOSPC, "일부러 낸 디스크 가득")
            return real_write(path, data)

        def spy_remove(path):
            touched.append(Path(path).name)
            return real_remove(path)

        with mock.patch.object(bk, "_write_bytes", spy_write), mock.patch.object(bk, "_remove_file", spy_remove):
            self.assertEqual(code_of(self.restore), "DISK_FULL")
        self.assertFalse([name for name in touched if name.startswith(layout.ENGINE_DB_FILE)], "보관함 단계 앞에서 난 실패는 보관함 파일을 건드리지 않는다")
        self.assertTrue(database.is_file())
        self.assertEqual(database.stat().st_size, 0)

    def undo_with_one_failing_move(self, failing):
        database, junk, seeds_path, broken = self.break_current_files()
        real_replace = os.replace

        def fail_restore(self_, backup):
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 첫 실패")

        def replace(source, target, *args, **kwargs):
            if Path(source).name.startswith(failing + ".bad-"):
                raise PermissionError(errno.EACCES, "일부러 낸 권한 오류")
            return real_replace(source, target, *args, **kwargs)

        with mock.patch.object(TopicStore, "restore_from", fail_restore), mock.patch("os.replace", replace):
            with self.assertRaises(AppError) as caught:
                self.restore()
        self.assertEqual(caught.exception.code, "TOPIC_STORE_LOCKED")
        self.assertIn(failing, " ".join(caught.exception.notes), "못 돌린 파일의 이름")
        placed = {layout.SEEDS_FILE: (seeds_path, broken), layout.ENGINE_DB_FILE: (database, junk)}
        for name, (path, content) in placed.items():
            if name != failing:
                self.assertEqual(path.read_bytes(), content, f"{name} 은(는) 다른 파일의 되돌리기가 실패해도 제자리로 돌아온다")

    def test_a_failing_undo_of_the_store_does_not_stop_the_undo_of_the_json_file(self):
        self.undo_with_one_failing_move(layout.ENGINE_DB_FILE)

    def test_a_failing_undo_of_the_json_file_does_not_stop_the_undo_of_the_store(self):
        self.undo_with_one_failing_move(layout.SEEDS_FILE)

    def test_a_failed_restore_does_not_leave_a_new_store_where_there_was_none(self):
        database = self.world.data / layout.ENGINE_DB_FILE
        database.unlink()

        def fail_restore(self_, backup):
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 실패")

        with mock.patch.object(TopicStore, "restore_from", fail_restore):
            self.assertEqual(code_of(self.restore), "TOPIC_STORE_LOCKED")
        self.assertFalse(database.exists(), "복원이 만들다 만 빈 보관함을 남기지 않는다 — 복원 전과 같다")
        self.assertFalse(Path(str(database) + "-journal").exists())

    def test_a_failed_restore_puts_a_zero_byte_store_back_as_it_was(self):
        database = self.world.data / layout.ENGINE_DB_FILE
        database.write_bytes(b"")

        def fail_restore(self_, backup):
            raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 실패")

        with mock.patch.object(TopicStore, "restore_from", fail_restore):
            self.assertEqual(code_of(self.restore), "TOPIC_STORE_LOCKED")
        self.assertTrue(database.is_file())
        self.assertEqual(database.stat().st_size, 0, "0바이트였으면 0바이트로 돌아온다")

    def test_a_failure_puts_the_files_that_were_moved_aside_back_in_place(self):
        self.change_live()
        broken = b'{"seeds": [oops'
        (self.world.data / layout.SEEDS_FILE).write_bytes(broken)
        before = digests(self.world.data)
        original = TopicStore.restore_from

        def fail(self_, backup):
            raise AppError("DISK_FULL", detail="일부러 낸 실패")

        TopicStore.restore_from = fail
        self.addCleanup(setattr, TopicStore, "restore_from", original)
        self.assertEqual(code_of(self.restore), "DISK_FULL")
        self.assertEqual((self.world.data / layout.SEEDS_FILE).read_bytes(), broken, "옆으로 옮겼던 깨진 파일이 제자리로 돌아왔다")
        self.assertEqual(digests(self.world.data), before)
        self.assertEqual([name for name in os.listdir(self.world.data) if ".bad-" in name or name.endswith(".restoring")], [])

    @unittest.skipUnless(os.name == "nt", "읽기 전용 속성으로 이름 바꾸기가 막히는 것은 윈도 동작이다")
    def test_a_write_failure_while_restoring_becomes_an_easy_error_with_only_the_file_name(self):
        self.change_live()
        before = digests(self.world.data)
        target = self.world.data / layout.SEEDS_FILE
        os.chmod(target, stat.S_IREAD)
        self.addCleanup(os.chmod, target, stat.S_IWRITE | stat.S_IREAD)
        with self.assertRaises(AppError) as caught:
            self.restore()
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertEqual(caught.exception.slots, {"경로": layout.SEEDS_FILE}, "화면에는 파일 이름만 — 경로·예외 이름은 없다")
        self.assertEqual(digests(self.world.data), before, "먼저 바꾼 파일은 원래대로 돌아왔다")
        self.assertEqual([name for name in os.listdir(self.world.data) if name.endswith(".restoring")], [])

    def test_a_full_disk_while_restoring_is_reported_as_a_full_disk_and_nothing_changes(self):
        self.change_live()
        before = digests(self.world.data)
        real = bk._write_bytes

        def full(path, data):
            if str(path).endswith(".restoring"):
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(path, data)

        bk._write_bytes = full
        self.addCleanup(setattr, bk, "_write_bytes", real)
        self.assertEqual(code_of(self.restore), "DISK_FULL")
        self.assertEqual(digests(self.world.data), before)
        self.assertEqual([name for name in os.listdir(self.world.data) if name.endswith(".restoring")], [])

    def test_the_os_error_mapping_names_only_the_file_and_keeps_the_exception_in_the_developer_detail(self):
        cases = [(OSError(errno.ENOSPC, "full"), "DISK_FULL", None), (OSError(errno.ENAMETOOLONG, "long"), "FILE_PATH_TOO_LONG", None), (PermissionError(errno.EACCES, "denied"), "FILE_WRITE_FAILED", {"경로": "seeds.json"})]
        if os.name == "nt":
            cases.append((OSError(errno.EACCES, "in use", None, 32), "FILE_IN_USE", {"경로": "seeds.json"}))
        for error, code, slots in cases:
            with self.subTest(code=code):
                mapped = bk._io_error(error, "seeds.json")
                self.assertEqual((mapped.code, mapped.slots or None), (code, slots))
                self.assertIn(type(error).__name__, mapped.detail)

    def test_a_listed_file_that_is_really_a_folder_is_an_invalid_backup_not_a_crash(self):
        self.change_live()
        before = digests(self.world.data)
        folder = self.folder_copy("topic-20260101-000015")
        (folder / layout.SEEDS_FILE).unlink()
        (folder / layout.SEEDS_FILE).mkdir()
        with self.assertRaises(AppError) as caught:
            self.restore(folder)
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_INVALID")
        self.assertNotIn(self.tmp.name, str(caught.exception.slots))
        self.assertEqual(digests(self.world.data), before)

    def test_a_failure_in_the_last_step_puts_the_json_files_back_and_leaves_the_store_alone(self):
        self.change_live()
        before = digests(self.world.data)
        original = TopicStore.restore_from

        def fail(self_, backup):
            raise AppError("DISK_FULL", detail="일부러 낸 실패")

        TopicStore.restore_from = fail
        self.addCleanup(setattr, TopicStore, "restore_from", original)
        self.assertEqual(code_of(self.restore), "DISK_FULL")
        after = digests(self.world.data)
        self.assertEqual(after, before, "JSON 은 원래 내용으로, 보관함은 바뀌지 않은 채")
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002", "cid-003"])

    def test_a_failure_while_staging_a_json_file_leaves_everything_as_it_was(self):
        self.change_live()
        before = digests(self.world.data)
        real = bk._write_bytes
        calls = []

        def flaky(path, data):
            if str(path).endswith(".restoring"):
                calls.append(path)
                if len(calls) == 2:                                  # 두 번째 JSON 을 쓰다가 실패 — 첫 JSON 은 이미 쓴 뒤다
                    raise OSError("일부러 낸 실패")
            return real(path, data)

        bk._write_bytes = flaky
        self.addCleanup(setattr, bk, "_write_bytes", real)
        self.assertEqual(code_of(self.restore), "FILE_WRITE_FAILED", "쓰다 난 OS 오류는 쉬운 오류로 바뀐다(P3 수정 1차 M3)")
        self.assertEqual(len(calls), 2)
        self.assertEqual(digests(self.world.data), before)
        self.assertEqual([entry for entry in os.listdir(self.world.data) if entry.endswith(".restoring")], [], "쓰다 만 임시 파일을 남기지 않는다")

    def test_a_json_file_that_did_not_exist_before_is_removed_again_when_the_last_step_fails(self):
        (self.world.data / layout.CALENDAR_FILE).unlink()
        before = digests(self.world.data)
        original = TopicStore.restore_from

        def fail(self_, backup):
            raise AppError("DISK_FULL", detail="일부러 낸 실패")

        TopicStore.restore_from = fail
        self.addCleanup(setattr, TopicStore, "restore_from", original)
        self.assertEqual(code_of(self.restore), "DISK_FULL")
        self.assertEqual(digests(self.world.data), before)
        self.assertFalse((self.world.data / layout.CALENDAR_FILE).exists(), "원래 없던 파일은 도로 없앤다")

    def test_a_failed_safety_backup_stops_the_restore_before_anything_changes(self):
        self.change_live()
        before = digests(self.world.data)
        real = bk.make_backup

        def failing(*args, **kwargs):
            raise AppError("BACKUP_FAILED", detail="일부러 낸 실패")

        bk.make_backup = failing
        self.addCleanup(setattr, bk, "make_backup", real)
        self.assertEqual(code_of(self.restore), "BACKUP_FAILED")
        self.assertEqual(digests(self.world.data), before, "바꾸기 직전 상태를 남기지 못하면 아무것도 바꾸지 않는다")

    def test_a_missing_live_state_is_just_created_from_the_backup_without_a_safety_backup(self):
        with tempfile.TemporaryDirectory() as other:
            fresh = Path(other) / "topic_engine"
            result = bk.restore_backup(self.backup, fresh, Path(other) / "backups" / "topic_engine", now=self.later)
            self.assertEqual((result.safety, result.moved_aside, result.kept), (None, None, ()))
            self.assertEqual(sorted(os.listdir(fresh)), sorted(layout.USER_DATA_FILES))

    def test_a_broken_live_store_is_moved_aside_not_deleted_and_the_json_is_saved(self):
        database = self.world.data / layout.ENGINE_DB_FILE
        database.write_bytes(os.urandom(5000))
        broken = database.read_bytes()
        put_json(self.world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(seed_id="changed-2", keyword="예시 깨진 뒤 씨앗")]))
        changed_seeds = (self.world.data / layout.SEEDS_FILE).read_bytes()
        result = self.restore()
        self.assertEqual(self.world.candidates(), ["cid-001", "cid-002"])
        self.assertIsNotNone(result.moved_aside)
        self.assertEqual(result.moved_aside.read_bytes(), broken, "깨진 파일은 지우지 않고 옆에 그대로 있다")
        self.assertTrue(result.moved_aside.name.startswith("topic_engine.db.bad-"))
        self.assertEqual((result.safety / layout.SEEDS_FILE).read_bytes(), changed_seeds, "읽을 수 있는 JSON 은 안전 백업에 남는다")

    def test_a_newer_live_store_blocks_the_restore_without_moving_anything(self):
        self.bump_live()
        before = digests(self.world.data)
        self.assertEqual(code_of(self.restore), "TOPIC_STORE_VERSION_UNSUPPORTED")
        self.assertEqual(digests(self.world.data), before)
        self.assertFalse((self.world.backups / bk.SAFETY_FOLDER).exists())

    def bump_live(self):
        connection = sqlite3.connect(str(self.world.data / layout.ENGINE_DB_FILE))
        with connection:
            connection.execute("PRAGMA user_version = 9")
        connection.close()

    def test_files_that_the_backup_does_not_have_are_left_as_they_are(self):
        with tempfile.TemporaryDirectory() as other:
            partial = World(other, calendar=False, profiles=False)
            small = partial.backup().path
            put_json(self.world.data / layout.CALENDAR_FILE, schedule.entries_to_dict([ts.example_entry(entry_id="live-cal-9", name="지금 있는 항목")]))
            calendar_before = (self.world.data / layout.CALENDAR_FILE).read_bytes()
            profiles_before = (self.world.data / layout.CHANNEL_PROFILES_FILE).read_bytes()
            result = bk.restore_backup(small, self.world.data, self.world.backups, now=self.later)
            self.assertEqual((result.restored, result.kept), ((layout.SEEDS_FILE, layout.ENGINE_DB_FILE), (layout.CHANNEL_PROFILES_FILE, layout.CALENDAR_FILE)))
            self.assertEqual((self.world.data / layout.CALENDAR_FILE).read_bytes(), calendar_before)
            self.assertEqual((self.world.data / layout.CHANNEL_PROFILES_FILE).read_bytes(), profiles_before)

    def test_reading_a_backup_never_changes_it(self):
        before = digests(self.backup)
        manifest, contents = bk.read_backup(self.backup)
        self.assertEqual((sorted(contents), sorted(manifest["files"])), (sorted(layout.USER_DATA_FILES), sorted(layout.USER_DATA_FILES)))
        self.assertEqual(digests(self.backup), before)
        self.assertEqual(sorted(os.listdir(self.backup)), sorted([*layout.USER_DATA_FILES, "MANIFEST.json"]), "읽는 동안 저널 같은 것도 남기지 않는다")


class PublicNamesTest(unittest.TestCase):
    def test_all_lists_exactly_the_public_names_and_the_write_helpers_stay_private(self):
        for name in bk.__all__:
            self.assertTrue(hasattr(bk, name), name)
        self.assertEqual(set(bk.BACKUP_FILES), set(layout.USER_DATA_FILES))
        self.assertEqual(bk.KEEP_BACKUPS, 10)


if __name__ == "__main__":
    unittest.main()
