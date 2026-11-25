"""복원 전 비밀 모양 훑기가 **인코딩으로 우회되지 않는다**(앱 2차 감사 AS-S2 권고-3, 결정 D-683) — PySide6 없이 돈다(CI 와 같은 조건).

감사 재현: 같은 가짜 키를 ① TEXT(UTF-8) ② BLOB(UTF-8) ③ BLOB(UTF-16LE) ④ BLOB(BOM 붙은 UTF-16) 로 담은 보관함에서 — 주제 엔진 백업의 훑기는 TEXT 만, 전체 백업의 훑기는 TEXT·UTF-8 BLOB 만 잡았고 UTF-16 BLOB 은
둘 다 놓쳤다(앱은 같은 칸을 `json.loads(바이트)` 로 읽어 UTF-16 도 읽는다). 조작해 만든 백업(목록의 해시·크기·항목 수까지 맞게 만든 것)은 `verify_backup` 을 통과하고 복원돼 지금 보관함에 키 글이 들어왔다.
JSON 글은 원문 글자를 훑어 `\\uXXXX` 이스케이프로 쪼갠 가짜 키(`\\u0041KIA…` — JSON 으로는 같은 글)를 못 봤다(주제 엔진 백업의 씨앗·캘린더 파일).

고침: 훑기 앞에 정규화(`security/views.py`) — 바이트는 UTF-8·`json.detect_encoding` 감지·널 바이트 뺀 글·UTF-16/32 로 푼 보기들을, 글은 널 글자를 뺀 보기와 이스케이프를 푼 보기를 더해 **모든 보기를 훑는다**(보기만 늘 뿐 기존에 걸리던 것은 그대로).
이 파일이 못박는 것:
  1) 정규화 함수(`blob_views`·`text_views`·`unescape_json`) — 비밀이 어떤 모양으로 적혀 있어도 보기 하나는 그 글을 그대로 보인다. 평범한 이진 자료·글은 보기가 늘어도 키 모양이 생기지 않는다.
  2) 전체 백업의 훑기(`_scan_connection`)와 주제 엔진 백업의 훑기(`_database_key_shaped`·`_scan_json`·`read_backup`·`make_backup`·`_live_state`)가 위 우회 모양을 모두 잡는다 — 거짓 음성 0.
  3) 조작 백업(전체·주제 엔진)은 `verify_backup`·`read_backup` 에서 거절된다(끝에서 끝까지). 발행 이력 장부 행은 여전히 훑지 않는다(D-75).
  4) 평범한 BLOB·UTF-16 글·정상 JSON 은 막히지 않는다(거짓 양성 0).
"""
import contextlib
import datetime
import hashlib
import json
import random
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import scan_samples as S  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import views  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topicdb import backup as tb  # noqa: E402
from chanceblog_desktop.topics import layout, seeds as topic_seeds  # noqa: E402

SECRET = "AI" + "za" + "CANARY_" + "A" * 28                      # 감사 탐침과 같은 가짜 Google API 키 모양
GITHUB = S.github()                                              # 가짜 GitHub 토큰 모양
JSON_SECRET = "AI" + "za" + "CANARYx" + "A" * 28                  # 씨앗 낱말 칸의 모양 규칙(밑줄 불가)을 지나는 가짜 Google API 키 모양
ENCODINGS = {
    "UTF-8": lambda text: text.encode("utf-8"), "UTF-8 BOM": lambda text: text.encode("utf-8-sig"), "UTF-16LE": lambda text: text.encode("utf-16-le"), "UTF-16BE": lambda text: text.encode("utf-16-be"),
    "UTF-16 BOM": lambda text: text.encode("utf-16"), "UTF-32LE": lambda text: text.encode("utf-32-le"), "UTF-32BE": lambda text: text.encode("utf-32-be"), "UTF-32 BOM": lambda text: text.encode("utf-32"),
    "널 바이트 끼움": lambda text: b"\x00".join(bytes([code]) for code in text.encode("ascii")), "한 바이트 어긋난 UTF-16LE": lambda text: b" " + text.encode("utf-16-le"),
    "JSON 한 줄(UTF-16LE)": lambda text: json.dumps({"note": text}).encode("utf-16-le"), "JSON 한 줄(UTF-16 BOM)": lambda text: json.dumps({"note": text}).encode("utf-16"),
}
BENIGN = {
    "PNG 머리": b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4, "무작위 바이트": random.Random(683).randbytes(4096), "UTF-16 일반 글": "예시 청소기 고르는 기준을 정리해요. 2026년 11월 5일".encode("utf-16"),
    "UTF-8 일반 글": "예시 청소기 고르는 기준".encode("utf-8"), "빈 바이트": b"", "널 바이트뿐": b"\x00" * 64, "짧은 영문 UTF-16": "hello world 12345".encode("utf-16-le"),
}


def secret_in_any(views_):
    return any(tb.scan_key_shape(view) for view in views_)


class ViewsTest(unittest.TestCase):
    def test_every_way_of_writing_a_secret_gives_a_view_that_shows_it_plainly(self):
        for secret in (SECRET, GITHUB):
            for label, encode in ENCODINGS.items():
                raw = encode(secret)
                with self.subTest(label=label, secret=secret[:4]):
                    shown = list(views.blob_views(raw))
                    self.assertTrue(any(secret in view for view in shown), "보기 하나는 비밀을 그대로 보인다")
                    self.assertTrue(secret_in_any(shown))

    def test_plain_data_never_grows_a_key_shape_from_the_extra_views(self):
        for label, raw in BENIGN.items():
            with self.subTest(label=label):
                self.assertFalse(secret_in_any(views.blob_views(raw)))

    def test_plain_utf8_text_costs_one_view_and_the_views_are_distinct(self):
        self.assertEqual(len(list(views.blob_views("정상 글입니다 abc123".encode("utf-8")))), 1, "널 바이트가 없는 바이트는 UTF-16·UTF-32 로 풀어 볼 까닭이 없다(영문 키 모양이 나올 수 없다)")
        for label, encode in ENCODINGS.items():
            shown = list(views.blob_views(encode(SECRET)))
            self.assertEqual(len(shown), len(set(shown)), label)
        self.assertEqual(list(views.blob_views(None)), [])
        self.assertEqual(list(views.blob_views("글")), [])
        self.assertEqual(list(views.blob_views(bytearray(SECRET.encode("utf-16-le"))))[1:2] != [], True)

    def test_json_escapes_are_resolved_the_way_json_does(self):
        self.assertEqual(views.unescape_json("\\u0041KIA"), "AKIA")
        self.assertEqual(views.unescape_json("\\u00411\\u0062c"), "A1bc")
        self.assertEqual(views.unescape_json("a\\nb\\tc\\/d\\\"e\\\\f"), "a" + chr(10) + "b" + chr(9) + "c/d" + chr(34) + "e" + chr(92) + "f")
        self.assertEqual(ascii(views.unescape_json("\\ud83d\\ude00")), ascii(chr(0x1F600)), "서로게이트 쌍은 한 글자")                      # (ascii 로 견준다 — 틀렸을 때 짝 없는 서로게이트 글자를 화면에 찍다가 죽지 않게)
        self.assertEqual(ascii(views.unescape_json("\\ud83d")), ascii(chr(0xFFFD)), "짝이 없는 서로게이트는 대체 글자")
        text = "이스케이프가 없는 글"
        self.assertIs(views.unescape_json(text), text)
        for odd in (None, 5, b"\\u0041"):
            self.assertEqual(views.unescape_json(odd), odd)
        self.assertEqual(list(views.text_views("a\\u0041")), ["a\\u0041", "aA"])
        self.assertEqual(list(views.text_views("a" + chr(0) + "b")), ["a" + chr(0) + "b", "ab"])
        self.assertEqual(list(views.text_views("정상")), ["정상"])
        self.assertEqual(list(views.text_views(b"x")), [])
        escaped = "".join(f"\\u{ord(char):04x}" for char in SECRET[:6]) + SECRET[6:]
        self.assertFalse(tb.scan_key_shape(escaped), "(전제) 원문 글자로는 못 본다")
        self.assertTrue(tb.scan_key_shape(views.unescape_json(escaped)))
        json.loads('"' + escaped + '"')                                                             # (전제) JSON 으로는 올바른 글이다

    def test_the_module_touches_nothing_outside_memory(self):
        source = (ROOT / "src" / "chanceblog_desktop" / "security" / "views.py").read_text(encoding="utf-8")
        for word in ("open(", "import os", "import sys", "subprocess", "socket", "urllib", "pathlib", "print(", "logging"):
            self.assertNotIn(word, source)


def cell_database(path, value):
    """감사 탐침과 같은 모양의 작은 SQLite — `drafts` 표 한 줄(글 칸이 `value`)."""
    with contextlib.closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE drafts (project_id TEXT PRIMARY KEY, text TEXT NOT NULL, saved_at TEXT NOT NULL)")
        db.execute("INSERT INTO drafts VALUES (?, ?, ?)", ("dd-" + "0" * 20, value, "2026-11-24T00:00:00Z"))
        db.commit()
    return path


class Folder(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def database(self, name, value):
        self.count = getattr(self, "count", 0) + 1                                  # 같은 이름을 되풀이해 써도 파일은 늘 새것이다
        return cell_database(self.tmp / f"{self.count}-{name}", value)


class FullBackupScanTest(Folder):
    def scanned(self, value):
        path = self.database("one.db", value)
        sink = []
        with contextlib.closing(sqlite3.connect(path)) as db:
            bf._scan_connection(sink, db, "chanceblog.db")
        return sink

    def test_every_encoding_of_a_secret_in_a_cell_is_found(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label=label):
                self.assertTrue(self.scanned(encode(SECRET)), "BLOB 칸의 가짜 키를 못 잡았다")
        self.assertTrue(self.scanned(SECRET), "(대조) TEXT 칸")
        self.assertTrue(self.scanned("A" + chr(0) + "I" + chr(0) + "z" + chr(0) + "a" + chr(0) + SECRET[4:]), "널 글자를 끼운 TEXT")

    def test_json_text_in_a_cell_with_escapes_or_nuls_is_found(self):
        escaped = "".join(f"\\u{ord(char):04x}" for char in SECRET[:6]) + SECRET[6:]
        for label, value in (("JSON 객체 이스케이프", '{"note": "' + escaped + '"}'), ("JSON 글 이스케이프", '"' + escaped + '"'), ("이스케이프한 일반 글", "메모 " + escaped), ("JSON 목록", '["' + escaped + '"]')):
            with self.subTest(label=label):
                self.assertTrue(self.scanned(value), label)

    def test_plain_cells_are_not_blocked(self):
        for label, raw in BENIGN.items():
            with self.subTest(label=label):
                self.assertEqual(self.scanned(raw), [])
        for text in ("정상 글입니다", '{"note": "평범한 \\u00e9 글"}', "줄\\n바꿈 이스케이프", "경로 C:\\users\\예시"):
            with self.subTest(text=text[:10]):
                self.assertEqual(self.scanned(text), [])

    def test_a_forged_backup_with_a_hidden_secret_is_refused_by_verify_backup(self):
        """감사 probe_05 (B) — 목록의 해시·크기·항목 수까지 맞게 만든 조작 백업의 `drafts.text` 를 UTF-16LE BLOB 으로 두면 통과·복원되던 것."""
        for label in ("UTF-16LE", "UTF-16 BOM", "널 바이트 끼움", "TEXT(대조)"):
            with self.subTest(label=label):
                holder = tempfile.TemporaryDirectory()
                self.addCleanup(holder.cleanup)
                world = bs.World.cached(holder.name, posts=1, drafts=1, candidates_count=0, engine=False, profiles=False, seeds=False, calendar=False, settings=False)
                outcome = world.backup()
                folder = world.folder(outcome)
                value = SECRET if label.startswith("TEXT") else ENCODINGS[label](SECRET)
                with contextlib.closing(sqlite3.connect(folder / "chanceblog.db")) as db:
                    db.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES (?, ?, ?)", ("dd-" + "1" * 20, value, "2026-11-24T00:00:00Z"))
                    db.commit()
                manifest = world.manifest(outcome)
                data = (folder / "chanceblog.db").read_bytes()
                manifest["files"]["chanceblog.db"].update(size=len(data), sha256=hashlib.sha256(data).hexdigest(), items=bf._table_counts(folder / "chanceblog.db"))
                bs.write_manifest(folder, manifest)
                with self.assertRaises(AppError) as caught:
                    bf._verify_backup(folder)
                self.assertEqual(caught.exception.code, "FULL_BACKUP_BLOCKED", label)


class TopicBackupScanTest(Folder):
    def test_every_encoding_of_a_secret_in_a_cell_is_found(self):
        for number, (label, encode) in enumerate(ENCODINGS.items()):
            with self.subTest(label=label):
                self.assertTrue(tb._database_key_shaped(self.database(f"blob-{number}.db", encode(SECRET))), "BLOB 칸의 가짜 키를 못 잡았다")
        self.assertTrue(tb._database_key_shaped(self.database("text.db", SECRET)), "(대조) TEXT 칸")

    def test_escaped_secrets_in_text_cells_are_found(self):
        escaped = "".join(f"\\u{ord(char):04x}" for char in SECRET[:6]) + SECRET[6:]
        self.assertTrue(tb._database_key_shaped(self.database("esc.db", '{"note": "' + escaped + '"}')))

    def test_a_table_definition_that_looks_like_a_hex_blob_does_not_stop_the_scan(self):
        """덤프의 `CREATE TABLE` 줄에는 표를 만든 문장이 그대로 실린다 — 그 안의 주석에 `aX'abc'` 처럼 길이가 홀수인 가짜 16진수를 적은 조작한 보관함이 훑기를 예외로 멈추게 못 해야 한다(BLOB 이 아니라 글이라 풀지 않는다)."""
        for number, comment in enumerate(("aX'abc'", "aX'abcd'", "X'0'", "X'zz'", "X''")):
            path = self.tmp / f"hostile-definition-{number}.db"
            with contextlib.closing(sqlite3.connect(path)) as db:
                db.execute(f"CREATE TABLE notes (id TEXT /* {comment} */)")
                db.execute("INSERT INTO notes VALUES (?)", ("정상 글",))
                db.commit()
            with self.subTest(comment=comment):
                self.assertFalse(tb._database_key_shaped(path))
                self.assertIsNone(tb._database_location(path))

    def test_escaped_secrets_inside_a_blob_are_found_too(self):
        """앱은 BLOB 칸의 JSON 도 `json.loads(바이트)` 로 읽어 이스케이프를 푼다 — BLOB 안에서 이스케이프로 쪼갠 키도 걸린다(글 칸과 같은 정규화)."""
        escaped = "".join(f"\\u{ord(char):04x}" for char in SECRET[:6]) + SECRET[6:]
        for label, raw in (("UTF-8", escaped.encode("utf-8")), ("UTF-16LE", escaped.encode("utf-16-le")), ("UTF-16 BOM", escaped.encode("utf-16"))):
            with self.subTest(label=label):
                self.assertTrue(tb._database_key_shaped(self.database("blob-escaped.db", raw)))
        self.assertFalse(tb._database_key_shaped(self.database("blob-harmless-escape.db", "메모 \\u00e9 글".encode("utf-16-le"))), "평범한 이스케이프는 막지 않는다")

    def test_plain_cells_are_not_blocked(self):
        for number, (label, raw) in enumerate(BENIGN.items()):
            with self.subTest(label=label):
                self.assertFalse(tb._database_key_shaped(self.database(f"benign-{number}.db", raw)))
        self.assertFalse(tb._database_key_shaped(self.database("odd.db", "글 X'abc' 끝")), "16진수처럼 보이는 글자(길이가 홀수)는 BLOB 이 아니다")

    def test_published_ledger_rows_are_still_not_scanned_even_as_blobs(self):
        """발행 이력 장부 행은 공개된 글에서 온 값이라 훑지 않는다(D-75) — BLOB 으로 적힌 것도 같다."""
        for value in (SECRET, SECRET.encode("utf-16-le"), SECRET.encode("utf-8")):
            path = self.tmp / f"ledger-{type(value).__name__}-{len(value)}.db"
            with contextlib.closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE history_ledger (id TEXT PRIMARY KEY, title TEXT)")
                db.execute("INSERT INTO history_ledger VALUES (?, ?)", ("h1", value))
                db.commit()
            self.assertFalse(tb._database_key_shaped(path))

    def test_the_reason_and_the_place_do_not_crash_and_never_repeat_the_key(self):
        path = self.database("reason.db", SECRET.encode("utf-16-le"))
        reason, detail = tb._database_reason(path)
        for text in (reason, detail):
            self.assertNotIn(SECRET[:8], text)
            self.assertIn("백업하지 않았습니다", reason)
        where = tb._database_location(path)
        self.assertIsNotNone(where, "어느 표의 몇 번째 행인지 짚는다")
        self.assertEqual(where[0], "drafts")


def seeds_json(keyword, *, escape):
    seed = topic_seeds.Seed(seed_id="seed-1", major="가전", minor="청소", keyword="예시 청소기", seed_type="general", scope="common", registered_on="2026-11-24", state="active")
    text = json.dumps(topic_seeds.seeds_to_dict([seed]), ensure_ascii=False)
    shown = "".join(f"\\u{ord(char):04x}" for char in keyword[:6]) + keyword[6:] if escape else keyword
    return text.replace("예시 청소기", shown, 1).encode("utf-8")


class TopicJsonScanTest(Folder):
    def test_a_json_secret_written_with_escapes_is_found_in_every_place_it_is_scanned(self):
        data = seeds_json(JSON_SECRET, escape=True)
        self.assertEqual(json.loads(data)["seeds"][0]["keyword"], JSON_SECRET, "(전제) JSON 으로는 같은 글")
        self.assertFalse(tb.scan_key_shape(data.decode("utf-8")), "(전제) 원문 글자로는 안 보인다")
        with self.assertRaises(AppError) as caught:
            tb._scan_json("seeds.json", data)
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_BLOCKED")
        for text in (str(caught.exception.detail), caught.exception.rendered().message):
            self.assertNotIn(JSON_SECRET[:8], text)

    def test_plain_json_and_a_plain_secret_behave_as_before(self):
        clean = seeds_json("예시 청소기", escape=False)
        tb._scan_json("seeds.json", clean)                                                          # 정상 — 오류 없음
        with self.assertRaises(AppError) as caught:
            tb._scan_json("seeds.json", seeds_json(JSON_SECRET, escape=False))
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_BLOCKED")
        harmless = seeds_json("예시 청소기", escape=False).replace("가전".encode("utf-8"), "\\ud55c\\uae00".encode("utf-8"))
        tb._scan_json("seeds.json", harmless)

    def test_make_backup_refuses_and_leaves_nothing_behind(self):
        data_dir, backups = self.tmp / "data", self.tmp / "backups"
        data_dir.mkdir()
        (data_dir / "seeds.json").write_bytes(seeds_json(JSON_SECRET, escape=True))
        with self.assertRaises(AppError) as caught:
            tb.make_backup(data_dir, backups, now=datetime.datetime(2026, 11, 24, 9, 0, 0))
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_BLOCKED")
        self.assertFalse(backups.exists() and any(backups.iterdir()), "빈 폴더도 남기지 않는다")

    def test_read_backup_refuses_a_tampered_folder_whose_list_was_made_to_match(self):
        data_dir, backups = self.tmp / "data", self.tmp / "backups"
        data_dir.mkdir()
        (data_dir / "seeds.json").write_bytes(seeds_json("예시 청소기", escape=False))
        result = tb.make_backup(data_dir, backups, now=datetime.datetime(2026, 11, 24, 9, 0, 0))
        tb.read_backup(result.path)                                                                  # (전제) 정상 백업은 읽힌다
        tampered = seeds_json(JSON_SECRET, escape=True)
        (result.path / "seeds.json").write_bytes(tampered)
        manifest_path = result.path / tb.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["seeds.json"] = {"size": len(tampered), "sha256": hashlib.sha256(tampered).hexdigest()}
        manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        with self.assertRaises(AppError) as caught:
            tb.read_backup(result.path)
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_INVALID")

    def test_the_live_state_of_a_file_with_an_escaped_secret_is_keyed(self):
        data_dir = self.tmp / "live"
        data_dir.mkdir()
        (data_dir / "seeds.json").write_bytes(seeds_json(JSON_SECRET, escape=True))
        self.assertEqual(tb._live_state(data_dir, "seeds.json"), tb._KEYED)
        (data_dir / "seeds.json").write_bytes(seeds_json("예시 청소기", escape=False))
        self.assertEqual(tb._live_state(data_dir, "seeds.json"), tb._OK)


if __name__ == "__main__":
    unittest.main()
