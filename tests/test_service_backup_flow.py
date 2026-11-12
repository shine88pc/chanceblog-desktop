"""전체 백업 만들기(`service/backup_flow.py` 의 `create_full_backup`·`list_full_backups`) 시험 — 폴더 모양·목록 파일(MANIFEST)·완료/부분/실패·지금 데이터 불변·잠금·취소·경로 모양.

지키는 것(BACKUPUI, 결정 D-380–D-399):
  1) 백업 폴더 `backups/full-날짜-시각/` 에는 글 보관함·주제 보관함·JSON 셋·설정과 목록 파일뿐이다. 목록에는 파일마다 크기·해시·항목 수, 앱 버전·만든 때, **`credential_excluded: true` 와 쉬운 문장**, 담지 않는 것과 이유가 있다.
  2) 백업은 지금 데이터를 한 바이트도 바꾸지 않고, 임시 폴더·잠금 파일을 남기지 않으며, 없는 파일은 '아직 없음' 으로 적는다. 같은 초의 백업은 `-2`… 로 구별하고 오래된 것은 10개만 남긴다.
  3) 결과는 완료(있는 것을 모두 담음) · 부분(담지 못한 파일이 있음 — 이유가 파일마다) · 실패(오류 — 아무것도 남기지 않음) 한 가지다.
  4) 디스크 가득·쓰기 거절·경로가 너무 김·취소는 폴더를 남기지 않는다. 다른 백업·복원이 도는 중이면 `BACKUP_IN_PROGRESS`. 한글·공백 경로·읽기 전용 파일·긴 경로에서도 안전하다.
네트워크·실제 시계 없이 돈다. 키 모양은 `backup_support`(실행할 때 조각을 이어 붙임)가 만든다.
"""
import contextlib
import errno
import json
import os
import sqlite3
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.security import scan  # noqa: E402
from chanceblog_desktop.security.backup_note import CREDENTIAL_NOTE, EXCLUDED_NAMES  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

NAMES = ("chanceblog.db", layout.ENGINE_DB_FILE, layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE, layout.CALENDAR_FILE, "settings.json")


class Cancelled(Exception):
    pass


World = bs.World


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.cleanup)
        self.world = World(self.tmp.name)
        self.ctx = self.world.ctx

    def cleanup(self):
        for path in Path(self.tmp.name).rglob("*"):
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
        self.tmp.cleanup()

    def backups(self):
        return sorted(path.name for path in self.ctx.workspace.backups_dir.iterdir()) if self.ctx.workspace.backups_dir.is_dir() else []


class LayoutAndManifestTest(Base):
    def test_a_backup_is_one_folder_with_the_six_files_and_a_manifest(self):
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        self.assertRegex(outcome.row.name, r"^full-\d{8}-\d{6}$")
        self.assertEqual(sorted(path.name for path in folder.iterdir()), sorted((*NAMES, bf.MANIFEST_NAME)))
        self.assertEqual((outcome.row.status, outcome.row.kind, outcome.row.credential_excluded), (bf.STATUS_COMPLETE, "backup", True))
        self.assertEqual([(line.name, line.state) for line in outcome.row.files], [(name, "saved") for name in NAMES])

    def test_the_manifest_lists_size_hash_and_item_counts_of_every_file(self):
        manifest = self.world.manifest(self.world.backup())
        self.assertEqual(sorted(manifest["files"]), sorted(NAMES))
        folder = self.ctx.workspace.backups_dir / next(iter(self.backups()))
        import hashlib
        for name, info in manifest["files"].items():
            data = (folder / name).read_bytes()
            self.assertEqual((info["size"], info["sha256"]), (len(data), hashlib.sha256(data).hexdigest()), name)
        self.assertEqual(manifest["files"]["chanceblog.db"]["items"]["projects"], 2)
        self.assertEqual(manifest["files"]["chanceblog.db"]["items"]["drafts"], 1)
        self.assertEqual(manifest["files"]["chanceblog.db"]["items"]["candidates"], 1)
        self.assertEqual(manifest["files"][layout.ENGINE_DB_FILE]["items"]["candidates"], 2)
        self.assertEqual(manifest["files"][layout.CHANNEL_PROFILES_FILE]["items"], {"count": 5})
        self.assertEqual(manifest["files"][layout.SEEDS_FILE]["items"], {"count": 1})
        self.assertEqual(manifest["files"][layout.CALENDAR_FILE]["items"], {"count": 1})
        self.assertEqual(manifest["files"]["settings.json"]["items"], {"profiles": 2, "repo": 1})

    def test_the_manifest_says_in_plain_words_that_no_key_is_inside_and_what_is_left_out_and_why(self):
        manifest = self.world.manifest(self.world.backup())
        self.assertIs(manifest["credential_excluded"], True)
        self.assertEqual(manifest["credential_excluded_note"], CREDENTIAL_NOTE)
        self.assertEqual(CREDENTIAL_NOTE, "자격 증명(키·토큰·쿠키·세션)은 이 백업에 들어 있지 않아요 — 복원한 뒤 키는 다시 등록하세요")
        self.assertEqual([item["name"] for item in manifest["excluded"]], list(EXCLUDED_NAMES))
        for name in ("connections.json", "quota_state.json", "publish/", "locks/"):
            entry = next(item for item in manifest["excluded"] if item["name"] == name)
            self.assertTrue(len(entry["reason"]) > 15, name)
        self.assertEqual(manifest["secret_scan"], {"checked": True, "kinds": list(scan.KINDS), "found": 0})
        self.assertEqual((manifest["schema"], manifest["kind"], manifest["status"]), (1, "full-backup", "complete"))
        self.assertEqual((manifest["missing"], manifest["skipped"]), ([], {}))

    def test_the_manifest_records_the_clock_time_and_the_app_version(self):
        with mock.patch.object(bf, "read_app_version", return_value="1.2.3"):
            manifest = self.world.manifest(self.world.backup())
        self.assertEqual(manifest["created_at"], "2026-11-02T01:30:12Z")
        self.assertEqual(manifest["app_version"], "1.2.3")

    def test_the_manifest_is_plain_utf8_json_without_a_path_of_this_pc(self):
        outcome = self.world.backup()
        text = (self.world.folder(outcome) / bf.MANIFEST_NAME).read_text(encoding="utf-8")
        self.assertNotIn(str(self.world.root), text)
        self.assertNotIn(str(self.world.root).replace("\\", "/"), text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text)["credential_excluded_note"], CREDENTIAL_NOTE)

    def test_a_backup_changes_no_byte_of_the_live_data_and_leaves_no_lock_or_temp(self):
        def stamps():
            return {path: path.stat().st_mtime_ns for path in self.world.root.rglob("*") if path.is_file() and not ({"backups", "locks"} & set(path.relative_to(self.world.root).parts))}
        before, before_stamps = self.world.data_digests(), stamps()
        self.world.backup()
        self.assertEqual(self.world.data_digests(), before)
        self.assertEqual(stamps(), before_stamps, "수정 시각까지 그대로다")
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [], "잠금 파일은 끝나면 지워진다")
        self.assertFalse([name for name in self.backups() if name.endswith(".tmp")])

    def test_components_that_do_not_exist_yet_are_recorded_as_missing_and_the_backup_is_still_complete(self):
        world = World(tempfile.mkdtemp(dir=self.tmp.name), engine=False, profiles=False, seeds=False, calendar=False, settings=False)
        outcome = world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        self.assertEqual([(line.name, line.state) for line in outcome.row.files], [("chanceblog.db", "saved"), (layout.ENGINE_DB_FILE, "missing"), (layout.CHANNEL_PROFILES_FILE, "missing"),
                                                                                    (layout.SEEDS_FILE, "missing"), (layout.CALENDAR_FILE, "missing"), ("settings.json", "missing")])
        manifest = world.manifest(outcome)
        self.assertEqual(manifest["missing"], [layout.ENGINE_DB_FILE, layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE, layout.CALENDAR_FILE, "settings.json"])
        self.assertEqual(sorted(path.name for path in world.folder(outcome).iterdir()), ["MANIFEST.json", "chanceblog.db"])

    def test_a_zero_byte_file_is_a_leftover_of_an_interrupted_write_and_counts_as_missing(self):
        self.world.path(layout.SEEDS_FILE).write_bytes(b"")
        outcome = self.world.backup()
        self.assertEqual(next(line.state for line in outcome.row.files if line.name == layout.SEEDS_FILE), "missing")
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)

    def test_a_backup_made_only_of_json_files_works_too(self):
        world = World(tempfile.mkdtemp(dir=self.tmp.name), posts=0, drafts=0, candidates_count=0, engine=False, settings=False)
        self.assertFalse(world.path("chanceblog.db").exists())
        outcome = world.backup()
        self.assertEqual([line.name for line in outcome.row.files if line.state == "saved"], [layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE, layout.CALENDAR_FILE])
        self.assertFalse(world.path("chanceblog.db").exists(), "백업이 글 보관함을 새로 만들지 않는다")

    def test_the_size_of_a_row_is_the_sum_of_the_saved_files(self):
        outcome = self.world.backup()
        self.assertEqual(outcome.row.size, sum(line.size for line in outcome.row.files))
        self.assertGreater(outcome.row.size, 1000)


class NamesAndKeepingTest(Base):
    def test_backups_made_in_the_same_second_get_numbered_names(self):
        names = [self.world.backup().row.name for _ in range(3)]
        self.assertEqual(names, ["full-20261102-013012", "full-20261102-013012-2", "full-20261102-013012-3"])
        self.assertEqual([row.name for row in bf.list_full_backups(self.ctx).rows], names[::-1])

    def test_only_the_newest_ten_backups_are_kept(self):
        clock = self.ctx.clock
        made = []
        for _ in range(12):
            clock.advance(seconds=5)
            made.append(self.world.backup().row.name)
        self.assertEqual(self.backups(), sorted(made[2:]))
        self.assertEqual([row.name for row in bf.list_full_backups(self.ctx).rows], made[2:][::-1])

    def test_a_clock_that_went_backwards_never_costs_the_backup_just_made(self):
        """시계가 뒤로 가서 지금보다 미래 날짜인 백업이 열 개 있어도(D3) 방금 만든 백업은 '성공' 한 직후에 지워지지 않는다 — 미래 날짜 가운데 가장 낡은 것이 대신 정리된다."""
        clock = self.ctx.clock
        start = clock.now
        clock.advance(days=400)
        future = []
        for _ in range(10):
            clock.advance(seconds=5)
            future.append(self.world.backup().row.name)
        self.assertEqual(self.backups(), sorted(future))
        clock.now = start
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        kept = self.backups()
        self.assertIn(outcome.row.name, kept, "방금 만든 백업이 지워졌다")
        self.assertEqual(kept, sorted([outcome.row.name, *future[1:]]), "정리는 미래 날짜 가운데 가장 낡은 것 하나만 지운다")
        self.assertTrue((self.ctx.workspace.backups_dir / outcome.row.name / bf.MANIFEST_NAME).is_file())
        self.assertIn(outcome.row.name, [row.name for row in bf.list_full_backups(self.ctx).rows])

    def test_with_the_clock_still_behind_every_new_backup_stays_and_the_future_ones_go_one_by_one(self):
        """시계가 계속 뒤에 있으면 새로 만든 백업이 차례로 쌓이고 미래 날짜의 옛 것이 하나씩 사라진다 — 새 백업이 먼저 지워지는 일은 없다."""
        clock = self.ctx.clock
        start = clock.now
        clock.advance(days=400)
        future = []
        for _ in range(10):
            clock.advance(seconds=5)
            future.append(self.world.backup().row.name)
        clock.now = start
        fresh = []
        for _ in range(4):
            clock.advance(seconds=7)
            fresh.append(self.world.backup().row.name)
            self.assertIn(fresh[-1], self.backups())
        self.assertEqual(self.backups(), sorted([*fresh, *future[4:]]))
        for _ in range(8):
            clock.advance(seconds=7)
            fresh.append(self.world.backup().row.name)
        self.assertEqual(self.backups(), sorted(fresh[2:]), "미래 날짜가 모두 정리되고 새 백업이 가장 새 열 개로 남는다")

    def test_the_backup_just_made_is_protected_by_name_even_when_the_order_would_put_it_last(self):
        """정리가 정렬을 잘못하더라도(이름 시각이 가장 이른 방금 만든 백업) 이름으로 보호해 지우지 않는다."""
        root = self.ctx.workspace.backups_dir
        root.mkdir(parents=True, exist_ok=True)
        for number in range(12):
            (root / f"full-203001{number + 1:02d}-000000").mkdir()
        oldest = "full-20300101-000000"
        bf._prune(root, bf.KEEP_BACKUPS, protect=(oldest,))
        kept = sorted(path.name for path in root.iterdir())
        self.assertIn(oldest, kept)
        self.assertEqual(len(kept), bf.KEEP_BACKUPS)
        self.assertEqual(kept[1:], [f"full-203001{day:02d}-000000" for day in range(4, 13)])

    def test_the_backup_flow_tells_the_pruning_to_protect_the_new_backup_and_what_the_time_is_now(self):
        calls = []
        real = bf._prune

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return real(*args, **kwargs)

        with mock.patch.object(bf, "_prune", spy):
            outcome = self.world.backup()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["protect"], (outcome.row.name,))
        self.assertEqual(calls[0][1]["moment"], self.ctx.now())

    def test_backups_of_the_same_second_are_not_counted_as_the_future_and_stay_ahead_of_older_ones(self):
        """'지금' 과 같은 초의 백업(`-2`…)은 미래 날짜가 아니다 — 열 개 넘게 쌓일 때 같은 초의 것이 더 낡은 것보다 먼저 지워지지 않는다."""
        clock = self.ctx.clock
        old = []
        for _ in range(10):
            clock.advance(seconds=5)
            old.append(self.world.backup().row.name)
        clock.advance(seconds=5)
        same = [self.world.backup().row.name for _ in range(3)]
        self.assertEqual(self.backups(), sorted([*old[3:], *same]), "같은 초의 셋이 남고 가장 낡은 셋이 정리된다")

    def test_with_more_protected_names_than_kept_every_protected_one_stays(self):
        root = self.ctx.workspace.backups_dir
        root.mkdir(parents=True, exist_ok=True)
        for day in range(1, 6):
            (root / f"full-203001{day:02d}-000000").mkdir()
        protect = ("full-20300101-000000", "full-20300102-000000")
        bf._prune(root, 1, protect=protect)
        self.assertEqual(sorted(path.name for path in root.iterdir()), sorted(protect), "보호한 이름은 남길 개수보다 많아도 모두 남는다")

    def test_pruning_never_removes_a_folder_that_holds_a_file_the_app_did_not_make(self):
        clock = self.ctx.clock
        first = self.world.backup().row.name
        (self.ctx.workspace.backups_dir / first / "내 메모.txt").write_text("지우지 마세요", encoding="utf-8")
        for _ in range(11):
            clock.advance(seconds=5)
            self.world.backup()
        self.assertIn(first, self.backups(), "낯선 파일이 든 폴더는 지우지 않는다")
        self.assertEqual(len([name for name in self.backups() if bf.FULL_NAME.fullmatch(name)]), 11)

    def test_only_folders_with_the_names_the_app_makes_are_listed(self):
        self.world.backup()
        root = self.ctx.workspace.backups_dir
        for name in ("full-2026", "full-20261102-013012.tmp", "other", "full-20261102-013012-100"):
            (root / name).mkdir()
        (root / "full-20261102-999999-x").write_text("파일", encoding="utf-8")
        self.assertEqual([row.name for row in bf.list_full_backups(self.ctx).rows], ["full-20261102-013012"])

    def test_the_backup_folder_is_separate_from_the_older_single_file_backups(self):
        from chanceblog_desktop.service import projects
        legacy = projects.backup_store(self.ctx)
        self.world.backup()
        self.assertEqual([path.name for path in projects.list_backups(self.ctx)], [legacy.name])
        self.assertEqual([row.name for row in bf.list_full_backups(self.ctx).rows], ["full-20261102-013012"])


class ListingTest(Base):
    def test_the_list_is_newest_first_and_reads_only(self):
        self.ctx.clock.advance(seconds=1)
        first = self.world.backup().row.name
        self.ctx.clock.advance(seconds=1)
        second = self.world.backup().row.name
        before = self.world.data_digests()
        listing = bf.list_full_backups(self.ctx)
        self.assertEqual([row.name for row in listing.rows], [second, first])
        self.assertEqual((listing.location, listing.keep), (str(self.ctx.workspace.backups_dir), bf.KEEP_BACKUPS))
        self.assertEqual(self.world.data_digests(), before)

    def test_listing_a_data_folder_that_never_had_a_backup_creates_nothing(self):
        fresh = Path(tempfile.mkdtemp(dir=self.tmp.name)) / "nothing-here"
        ctx = ss.make_ctx(fresh, repo=None)
        listing = bf.list_full_backups(ctx)
        self.assertEqual((listing.rows, listing.keep), ((), bf.KEEP_BACKUPS))
        self.assertFalse(ctx.workspace.root.exists())

    def test_a_row_carries_what_the_card_shows(self):
        row = self.world.backup().row
        listing_row = bf.list_full_backups(self.ctx).rows[0]
        self.assertEqual(listing_row, row)
        self.assertEqual((row.created_at, row.app_version), ("2026-11-02T01:30:12Z", row.app_version))
        self.assertEqual(sorted(dict(row.files[0].items)), ["candidates", "drafts", "projects", "revisions"])

    def test_a_backup_whose_manifest_is_broken_is_listed_as_broken_with_a_reason(self):
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        (folder / bf.MANIFEST_NAME).write_text("{ 깨졌어요", encoding="utf-8")
        row = bf.list_full_backups(self.ctx).rows[0]
        self.assertEqual((row.status, row.problem, row.files, row.size), (bf.STATUS_BROKEN, "manifest", (), 0))
        self.assertEqual(row.created_at, "2026-11-02T01:30:12Z", "이름의 시각을 쓴다")

    def test_a_backup_with_a_missing_or_resized_file_is_listed_as_broken(self):
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        (folder / "seeds.json").unlink()
        row = bf.list_full_backups(self.ctx).rows[0]
        self.assertEqual((row.status, row.problem), (bf.STATUS_BROKEN, "files"))
        self.assertTrue(row.files, "목록은 읽혔으니 담긴 파일 줄은 보인다")
        second = self.world.backup()
        (self.world.folder(second) / "calendar.json").write_bytes(b"{}")
        self.assertEqual(bf.list_full_backups(self.ctx).rows[0].problem, "files")

    def test_a_newer_manifest_schema_is_not_listed_as_a_good_backup(self):
        """더 새로운 목록 판은 값이 얼마든(2·99·100·5000 — 경계에 걸린 값 하나만 보면 비교 숫자를 바꾼 코드를 못 잡는다) '깨짐' 으로 보이고, 복원은 '깨졌다' 가 아니라 '더 새로운 프로그램의 것' 으로 거절한다."""
        outcome = self.world.backup()
        original = self.world.manifest(outcome)
        for newer in (2, 99, 100, 5000):
            with self.subTest(schema=newer):
                bs.write_manifest(self.world.folder(outcome), {**original, "schema": newer})
                self.assertEqual(bf.list_full_backups(self.ctx).rows[0].status, bf.STATUS_BROKEN)
                before = self.world.data_digests()
                error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
                self.assertEqual((error.code, error.reason), ("STORE_VERSION_UNSUPPORTED", "newer"))
                self.assertEqual(self.world.data_digests(), before, "아무것도 바꾸지 않았다")
        bs.write_manifest(self.world.folder(outcome), original)
        self.assertEqual(bf.list_full_backups(self.ctx).rows[0].status, bf.STATUS_COMPLETE, "원래 목록으로 돌리면 다시 좋은 백업이다")


class PartialAndFailureTest(Base):
    def assert_nothing_left(self):
        self.assertFalse([name for name in self.backups() if name.endswith(".tmp")])
        self.assertFalse(list(self.ctx.workspace.locks_dir.iterdir()) if self.ctx.workspace.locks_dir.is_dir() else [])
        self.assertTrue(all(bf.FULL_NAME.fullmatch(name) for name in self.backups()), self.backups())

    def test_a_damaged_store_is_left_out_and_the_backup_is_partial_with_the_reason(self):
        self.world.path("chanceblog.db").write_bytes(b"not a database " * 50)
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_PARTIAL)
        lines = {line.name: line for line in outcome.row.files}
        self.assertEqual((lines["chanceblog.db"].state, lines["chanceblog.db"].reason), ("skipped", "STORE_CORRUPT"))
        self.assertEqual(sum(1 for line in outcome.row.files if line.state == "saved"), 5)
        manifest = self.world.manifest(outcome)
        self.assertEqual((manifest["status"], manifest["skipped"]), ("partial", {"chanceblog.db": "STORE_CORRUPT"}))
        self.assertRegex(outcome.row.name, r"^full-\d{8}-\d{6}$")
        self.assertFalse((self.world.folder(outcome) / "chanceblog.db").exists())
        self.assertEqual(sorted(path.name for path in self.world.folder(outcome).iterdir()), sorted([*(set(NAMES) - {"chanceblog.db"}), bf.MANIFEST_NAME]), "훑기만 한 복사본은 백업에 남지 않는다")
        self.assert_nothing_left()

    def test_an_unreadable_json_file_and_a_strictly_invalid_settings_file_are_each_left_out(self):
        self.world.path(layout.SEEDS_FILE).write_text("{ 깨짐", encoding="utf-8")
        self.world.path("settings.json").write_text(json.dumps({"schema": 1, "repo_path": "", "naver_profiles": {}, "모르는 칸": 1}), encoding="utf-8")
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_PARTIAL)
        manifest = self.world.manifest(outcome)
        self.assertEqual(manifest["skipped"], {layout.SEEDS_FILE: "TOPIC_FILE_INVALID", "settings.json": "SETTINGS_INVALID"})
        self.assertRegex(outcome.row.name, r"^full-\d{8}-\d{6}$")
        self.assertEqual(sorted(path.name for path in self.world.folder(outcome).iterdir()), sorted([*manifest["files"], bf.MANIFEST_NAME]))
        self.assertEqual(sorted(manifest["files"]), sorted(set(NAMES) - set(manifest["skipped"])))
        self.assert_nothing_left()

    def test_a_store_made_by_a_newer_app_is_left_out_not_copied(self):
        with contextlib.closing(sqlite3.connect(str(self.world.path("chanceblog.db")))) as connection:
            connection.execute("PRAGMA user_version = 99")
        outcome = self.world.backup()
        self.assertEqual({line.name: line.reason for line in outcome.row.files if line.state == "skipped"}, {"chanceblog.db": "STORE_VERSION_UNSUPPORTED"})

    def test_a_store_that_cannot_be_opened_for_reading_because_of_an_unfinished_save_is_left_out(self):
        error = AppError("STORE_RECOVERY_PENDING", {"파일": "chanceblog.db"})
        real = bf.Store.open

        def opener(path, **kwargs):
            if Path(path) == self.world.path("chanceblog.db") and kwargs.get("migrate") is False:
                raise error
            return real(path, **kwargs)
        with mock.patch.object(bf.Store, "open", side_effect=opener):
            outcome = self.world.backup()
        self.assertEqual({line.name: line.reason for line in outcome.row.files if line.state == "skipped"}, {"chanceblog.db": "STORE_RECOVERY_PENDING"})

    def test_when_nothing_at_all_can_be_saved_the_backup_fails_and_leaves_no_folder(self):
        for name in NAMES:
            if name.endswith(".db"):
                self.world.path(name).write_bytes(b"garbage " * 40)
            else:
                self.world.path(name).write_text("{ 깨짐", encoding="utf-8")
        failure = bs.code_of(self.world.backup)
        self.assertEqual((failure.code, failure.reason), ("BACKUP_FAILED", "nothing"))
        self.assertEqual(sorted(failure.skipped), sorted(NAMES))
        self.assertEqual(self.backups(), [], "빈 backups 폴더도 남기지 않는다")
        self.assert_nothing_left()

    def test_with_no_data_at_all_the_backup_says_so_and_creates_nothing(self):
        empty = Path(tempfile.mkdtemp(dir=self.tmp.name))
        ctx = ss.make_ctx(empty, repo=None)
        ctx.workspace.ensure()
        failure = bs.code_of(bf.create_full_backup, ctx)
        self.assertEqual(failure.code, "CONTENT_NOT_FOUND")
        self.assertEqual(sorted(path.name for path in ctx.workspace.root.iterdir()), ["locks"], "잠금 폴더 말고는 만들지 않는다")
        self.assertEqual(list(ctx.workspace.locks_dir.iterdir()), [])
        missing = ss.make_ctx(Path(tempfile.mkdtemp(dir=self.tmp.name)) / "없는 폴더", repo=None)
        self.assertEqual(bs.code_of(bf.create_full_backup, missing).code, "CONTENT_NOT_FOUND")
        self.assertFalse(missing.workspace.root.exists())

    def test_disk_full_while_copying_a_store_stops_everything_and_leaves_nothing(self):
        before = self.world.data_digests()
        with mock.patch.object(bf, "_write_sqlite", side_effect=sqlite3.OperationalError("database or disk is full")):
            failure = bs.code_of(self.world.backup)
        self.assertEqual(failure.code, "DISK_FULL")
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.world.data_digests(), before)

    def test_disk_full_while_writing_a_json_copy_stops_everything_and_leaves_nothing(self):
        with mock.patch.object(bf, "_write_durably", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            failure = bs.code_of(self.world.backup)
        self.assertEqual(failure.code, "DISK_FULL")
        self.assertEqual(self.backups(), [])
        self.assert_nothing_left()

    def test_a_refused_write_and_a_too_long_path_are_told_in_plain_words(self):
        with mock.patch.object(bf, "_make_folder", side_effect=PermissionError(errno.EACCES, "Permission denied")):
            self.assertEqual(bs.code_of(self.world.backup).code, "FILE_WRITE_FAILED")
        with mock.patch.object(bf, "_write_durably", side_effect=OSError(errno.ENAMETOOLONG, "File name too long")):
            self.assertEqual(bs.code_of(self.world.backup).code, "FILE_PATH_TOO_LONG")
        self.assertEqual(self.backups(), [])
        self.assert_nothing_left()

    def test_a_failure_while_renaming_the_finished_folder_leaves_no_temp_folder(self):
        with mock.patch.object(bf, "_finish_folder", side_effect=PermissionError(errno.EACCES, "denied")):
            self.assertEqual(bs.code_of(self.world.backup).code, "FILE_WRITE_FAILED")
        self.assertEqual(self.backups(), [])

    def test_a_stale_temp_folder_from_a_crashed_run_is_cleared_and_a_foreign_one_is_not_trusted(self):
        root = self.ctx.workspace.backups_dir
        stale = root / "full-20261102-013012.tmp"
        stale.mkdir(parents=True)
        (stale / "chanceblog.db").write_bytes(b"half written")
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        self.assertEqual(self.backups(), ["full-20261102-013012"])
        stale.mkdir()
        (stale / "내 파일.txt").write_text("내 것", encoding="utf-8")
        failure = bs.code_of(self.world.backup)
        self.assertEqual(failure.code, "FILE_WRITE_FAILED", "낯선 파일이 든 임시 폴더는 지우지 않고 멈춘다")
        self.assertTrue((stale / "내 파일.txt").exists())

    def test_the_lock_is_released_after_a_failure_so_the_next_backup_works(self):
        with mock.patch.object(bf, "_write_sqlite", side_effect=sqlite3.OperationalError("database or disk is full")):
            self.assertEqual(bs.code_of(self.world.backup).code, "DISK_FULL")
        self.assertEqual(self.world.backup().row.status, bf.STATUS_COMPLETE)


class StepAndCancelTest(Base):
    def test_the_progress_steps_only_go_forward_and_end_at_one(self):
        seen = []
        self.world.backup(step=lambda fraction, text="": seen.append((fraction, text)))
        fractions = [fraction for fraction, _ in seen]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)
        self.assertTrue(all(0 <= fraction <= 1 and isinstance(text, str) and text for fraction, text in seen))
        self.assertGreaterEqual(len(seen), 6)

    def test_cancelling_at_any_step_leaves_no_folder_and_no_lock(self):
        total = []
        self.world.backup(step=lambda fraction, text="": total.append(fraction))
        self.backups()
        for stop in range(len(total) - 1):
            with self.subTest(stop=stop):
                count = [0]

                def step(fraction, text="", stop=stop):
                    if count[0] == stop:
                        raise Cancelled()
                    count[0] += 1
                before = set(self.backups())
                with self.assertRaises(Cancelled):
                    self.world.backup(step=step)
                self.assertEqual(set(self.backups()), before)
                self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])

    def test_an_error_from_the_progress_function_is_not_swallowed(self):
        with self.assertRaises(ZeroDivisionError):
            self.world.backup(step=lambda fraction, text="": 1 / 0)
        self.assertEqual(self.backups(), [])


class LockTest(Base):
    def test_a_backup_started_while_another_backup_or_restore_runs_stops_without_touching_anything(self):
        outcome = self.world.backup()
        before = (self.world.data_digests(), self.backups())
        with bf._flow_lock(self.ctx):
            failure = bs.code_of(self.world.backup)
            self.assertEqual(failure.code, "BACKUP_IN_PROGRESS")
            self.assertIn("시작", failure.slots)
            restore = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
            self.assertEqual(restore.code, "BACKUP_IN_PROGRESS")
        self.assertEqual((self.world.data_digests(), self.backups()), before)
        self.assertEqual(self.world.backup().row.status, bf.STATUS_COMPLETE, "잠금이 풀리면 다시 된다")

    def test_two_backups_at_the_same_moment_never_corrupt_each_other(self):
        results, barrier = [], threading.Barrier(2)

        def run():
            barrier.wait()
            try:
                results.append(self.world.backup())
            except AppError as error:
                results.append(error)
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(len(results), 2)
        done = [item for item in results if not isinstance(item, AppError)]
        self.assertGreaterEqual(len(done), 1)
        for item in results:
            if isinstance(item, AppError):
                self.assertEqual(item.code, "BACKUP_IN_PROGRESS")
        for row in bf.list_full_backups(self.ctx).rows:
            self.assertEqual(row.status, bf.STATUS_COMPLETE, row.name)
            bf._verify_backup(self.ctx.workspace.backups_dir / row.name)                  # 복원이 읽는 방법 그대로 끝까지 확인해도 통과한다
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])

    def test_the_lock_does_not_read_the_name_of_this_pc(self):
        with mock.patch("platform.node", side_effect=AssertionError("PC 이름을 읽었다")):
            self.world.backup()


class PathShapeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_data_folder_with_spaces_and_korean_letters_backs_up_and_lists(self):
        base = Path(self.tmp.name) / "내 문서 폴더 with spaces" / "블로그 데이터"
        base.mkdir(parents=True)
        world = World(base)
        outcome = world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        self.assertEqual(bf.list_full_backups(world.ctx).rows[0].name, outcome.row.name)
        bf._verify_backup(world.folder(outcome))

    def test_a_very_long_data_folder_path_either_works_or_fails_cleanly(self):
        base, target = Path(self.tmp.name), 207                               # 데이터 폴더(`base/data`)가 212자 — 그 안의 파일은 260자 안이고 백업 임시 폴더 안의 파일은 넘는다(윈도 기본 설정)
        while len(str(base)) + 31 < target:
            base = base / ("길게이어지는폴더이름" + "x" * 20)
        base = base / ("y" * (target - len(str(base)) - 1))
        try:
            base.mkdir(parents=True)
            world = World(base)
        except (OSError, AppError):
            self.skipTest("이 PC 는 이 길이의 경로에 파일을 만들 수 없다")
        before = bs.digests(world.root)
        try:
            outcome = world.backup()
        except AppError as error:
            self.assertIn(error.code, ("FILE_PATH_TOO_LONG", "FILE_WRITE_FAILED"))
            self.assertEqual(bs.digests(world.root), before)
            self.assertFalse([path for path in world.ctx.workspace.backups_dir.glob("*")] if world.ctx.workspace.backups_dir.is_dir() else [], "실패하면 아무것도 남기지 않는다")
        else:
            self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)

    def test_read_only_files_are_backed_up_because_the_backup_only_reads(self):
        world = World(Path(self.tmp.name) / "ro")
        paths = [path for path in world.root.rglob("*") if path.is_file()]
        for path in paths:
            os.chmod(path, stat.S_IREAD)
        self.addCleanup(lambda: [os.chmod(path, stat.S_IWRITE | stat.S_IREAD) for path in world.root.rglob("*") if path.is_file()])
        before = bs.digests(world.root)
        outcome = world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        self.assertEqual(bs.digests(world.root), before)


class LargeDataTest(unittest.TestCase):
    def test_a_few_thousand_posts_back_up_and_restore_in_a_reasonable_time(self):
        import time
        from chanceblog_desktop.content.model import ContentProject
        from chanceblog_desktop.content import store as store_module
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, posts=1, drafts=0, candidates_count=0)
            body = ("긴 본문 문단이에요. " * 120 + "\n\n") * 4
            rows = []
            for number in range(1000):
                project = ContentProject.new(f"대량 글 {number}", body, now="2026-11-02T01:30:12Z", project_id=f"{number:032x}")
                data = store_module._dump(project.to_dict())
                rows.append((project.project_id, project.title, project.revision, project.created_at, project.updated_at, data))
            with contextlib.closing(sqlite3.connect(str(world.path("chanceblog.db")))) as connection:
                connection.executemany("INSERT INTO projects (project_id, title, revision, created_at, updated_at, data) VALUES (?, ?, ?, ?, ?, ?)", rows)
                connection.commit()
            size = world.path("chanceblog.db").stat().st_size
            self.assertGreater(size, 10_000_000)
            started = time.monotonic()
            outcome = world.backup()
            backup_seconds = time.monotonic() - started
            started = time.monotonic()
            result = bf.restore_full_backup(world.ctx, outcome.row.name, confirmed=True)
            restore_seconds = time.monotonic() - started
            self.assertEqual(result.status, bf.STATUS_COMPLETE)
            self.assertLess(backup_seconds, 60, f"백업 {backup_seconds:.1f}초")
            self.assertLess(restore_seconds, 90, f"복원 {restore_seconds:.1f}초")
            self.assertEqual(dict(outcome.row.files[0].items)["projects"], 1001)


class CatalogTest(unittest.TestCase):
    def test_every_code_the_backup_flow_raises_is_in_the_error_catalog_with_the_slots_it_fills(self):
        for code in ("FULL_BACKUP_BLOCKED", "FULL_BACKUP_INVALID", "BACKUP_IN_PROGRESS", "RESTORE_FAILED"):
            info = CATALOG[code]
            self.assertTrue(info.message and info.action and info.when, code)
        self.assertEqual(CATALOG["FULL_BACKUP_BLOCKED"].slots, ("위치",))
        self.assertEqual(CATALOG["FULL_BACKUP_INVALID"].slots, ("파일", "이유"))
        self.assertEqual(CATALOG["BACKUP_IN_PROGRESS"].slots, ("시작",))
        self.assertEqual(CATALOG["RESTORE_FAILED"].slots, ("이유",))


if __name__ == "__main__":
    unittest.main()
