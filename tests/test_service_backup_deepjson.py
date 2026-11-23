"""아주 깊게 겹친 JSON 이 백업·복원에서 원시 `RecursionError` 로 새지 않는 것을 지키는 시험 — AS-S1 참고-1(결정 D-613).

발견(감사 탐침 p2): 작은(2KB) `seeds.json` 을 `[` 1100개로 만들어 목록을 맞추면 `restore_full_backup` 이 `FULL_BACKUP_INVALID` 가 아니라 원시 `RecursionError` 로 끝났다(깊이 300·900 은 거절, 10만은 json 이 `RecursionError` 를
스스로 잡아 거절 — 그 사이인 1000–1500 단이 파이썬 재귀 한도와 json 의 C 한도 사이에 낀다). 지금 `seeds.json` 이 그 깊이이면 `create_full_backup` 은 부분 백업이 아니라 **통째로 중단**됐다.
지키는 것: ① 들어오는 JSON·설정이 얼마나 깊어도 복원은 쉬운 `FULL_BACKUP_INVALID` 이다 ② 지금 파일 하나가 너무 깊으면 그 파일만 건너뛴 부분 백업이다(나머지는 담는다) ③ 보관함 칸 속 JSON 이 너무 깊어도 백업은 멈추지 않는다
④ **훑기가 재귀 한도에 걸려도 키 모양은 놓치지 않는다** — 걸리면 그 글을 통째로 일반 글로 다시 훑는다(깊이 겹친 JSON 에 숨긴 키도 막힌다). 네트워크·실제 시계 없이 돈다.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import test_service_backup_paths as tp  # noqa: E402
import test_service_backup_restore as tr  # noqa: E402

from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

DEPTHS = (300, 900, 1100, 1400, 5000, 100000)
KIND = bs.KINDS[0]


def nested(depth, inner=b""):
    return b"[" * depth + inner + b"]" * depth


def json_reads(raw):
    """이 파이썬의 json 이 그 바이트를 재귀 한도에 걸리지 않고 읽는가(읽는 쪽의 한도는 파이썬 판마다 다르다)."""
    try:
        json.loads(raw.decode("utf-8"))
    except RecursionError:
        return False
    return True


class DeepRestoreTest(tp.ForgedBackup):
    def test_deeply_nested_json_files_in_a_backup_are_refused_gracefully_at_every_depth_and_nothing_changes(self):
        for name in (layout.SEEDS_FILE, layout.CALENDAR_FILE, layout.CHANNEL_PROFILES_FILE, "settings.json"):
            for depth in DEPTHS:
                with self.subTest(file=name, depth=depth):
                    saved = (self.folder / name).read_bytes(), (self.folder / bf.MANIFEST_NAME).read_bytes()
                    try:
                        self.forge_bytes(name, nested(depth))
                        error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
                        self.assertIsNotNone(error, "거절돼야 한다")
                        self.assertEqual(error.code, "FULL_BACKUP_INVALID", error.detail)
                        self.assert_untouched(self.before)
                    finally:
                        (self.folder / name).write_bytes(saved[0])
                        (self.folder / bf.MANIFEST_NAME).write_bytes(saved[1])

    def test_when_the_scan_hits_the_recursion_limit_the_text_is_scanned_as_plain_text_so_a_key_inside_is_still_found(self):
        secret = bs.secret_text(KIND)
        raw = ('{"note": "' + secret + '"}').encode("utf-8")
        self.forge_bytes(layout.SEEDS_FILE, raw)
        with mock.patch.object(bf, "_scan_json_value", side_effect=RecursionError("일부러 낸 재귀 한도")):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED", "재귀 한도에 걸렸다고 키 모양을 놓쳤다")
        self.assert_untouched(self.before)

    def test_a_real_deep_value_with_a_key_hidden_at_the_bottom_is_refused_not_crashed_and_blocked_where_the_scan_can_follow_it(self):
        raw = nested(1100, b'"' + bs.secret_text(KIND).encode("utf-8") + b'"')
        self.forge_bytes(layout.SEEDS_FILE, raw)
        error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertIsNotNone(error)
        # 이 파이썬의 json 이 그 깊이를 읽으면(3.12 — C 재귀 한도가 파이썬 한도보다 높다) 훑기가 구조를 따라가다 파이썬 재귀 한도에 걸려 글로 다시 훑으므로 키 모양을 찾아 BLOCKED 다.
        # json 이 읽지도 못하면(3.10 — C 재귀가 파이썬 한도 1000 을 같이 써 약 990단부터) 훑기 앞의 읽기에서 INVALID 로 거절된다. 어느 쪽이든 원시 RecursionError 가 아니고 복원은 거절되며 아무것도 바뀌지 않는다.
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED" if json_reads(raw) else "FULL_BACKUP_INVALID", error.detail)
        self.assert_untouched(self.before)


class DeepEdgesTest(tp.ForgedBackup):
    """훑기·엄격한 읽기·지금 파일 상태 — 어느 자리에서 재귀 한도가 나도 쉬운 결과다."""

    def test_the_folder_scan_turns_a_recursion_error_into_an_easy_error_unless_the_file_is_lenient(self):
        with mock.patch.object(bf, "_scan_json_file", side_effect=RecursionError("일부러 낸 재귀 한도")):
            with self.assertRaises(bf.AppError) as caught:
                bf.scan_folder(self.folder, [layout.SEEDS_FILE])
            self.assertEqual(caught.exception.code, "TOPIC_FILE_INVALID")
            self.assertEqual(bf.scan_folder(self.folder, [layout.SEEDS_FILE], lenient=frozenset({layout.SEEDS_FILE})), [], "읽을 수 없는 파일은 훑지 못한 채 넘어간다 — 엄격한 읽기가 따로 거절한다")

    def test_a_recursion_error_in_the_strict_reading_of_a_backup_file_is_an_invalid_backup(self):
        real = bf.check_json_bytes

        def deep(name, data):
            if name == layout.CALENDAR_FILE:
                raise RecursionError("일부러 낸 재귀 한도")
            return real(name, data)
        with mock.patch.object(bf, "check_json_bytes", deep):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertIsNotNone(error)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "content"))
        self.assertNotIn("Recursion", str(error.slots))
        self.assert_untouched(self.before)

    def test_a_live_json_file_too_deep_to_read_is_treated_as_damaged_and_moved_aside_not_crashed(self):
        deep_bytes = nested(1100)
        self.world.path(layout.SEEDS_FILE).write_bytes(deep_bytes)
        real = bf.check_json_bytes

        def deep(name, data):
            if data == deep_bytes:
                raise RecursionError("일부러 낸 재귀 한도")
            return real(name, data)
        with mock.patch.object(bf, "check_json_bytes", deep):
            result = self.restore(self.outcome.row.name)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        aside = sorted(self.world.path(layout.SEEDS_FILE).parent.glob(layout.SEEDS_FILE + ".bad-*"))
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_bytes(), deep_bytes, "읽을 수 없는 지금 파일은 지우지 않고 옆으로 옮겨 둔다")
        self.assertTrue(any("깨져 있던" in note for note in result.notes), result.notes)


class DeepCreateTest(tr.Base):
    def test_a_live_json_file_nested_too_deep_gives_a_partial_backup_instead_of_stopping_the_whole_backup(self):
        for depth in (1100, 1400, 100000):
            with self.subTest(depth=depth):
                self.world.path(layout.SEEDS_FILE).write_bytes(nested(depth))
                outcome = self.world.backup()
                self.assertEqual(outcome.row.status, bf.STATUS_PARTIAL)
                lines = {line.name: line for line in outcome.row.files}
                self.assertEqual(lines[layout.SEEDS_FILE].state, bf.LINE_SKIPPED)
                self.assertTrue(lines[layout.SEEDS_FILE].reason)
                for name in ("chanceblog.db", layout.ENGINE_DB_FILE, layout.CALENDAR_FILE, "settings.json"):
                    self.assertEqual(lines[name].state, bf.LINE_SAVED, name)
                self.ctx.clock.advance(seconds=5)

    def test_a_database_cell_holding_too_deep_json_does_not_stop_the_backup(self):
        bs.plant_draft(self.world, nested(1100).decode("ascii"))
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)

    def test_a_key_hidden_at_the_bottom_of_a_deep_database_value_is_blocked_by_the_text_scan(self):
        deep = nested(1100, b'"' + bs.secret_text(KIND).encode("utf-8") + b'"').decode("utf-8")
        bs.plant_draft(self.world, deep)
        error = bs.code_of(self.world.backup)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
        self.assertEqual([path.name for path in self.ctx.workspace.backups_dir.iterdir()] if self.ctx.workspace.backups_dir.is_dir() else [], [], "막힌 백업은 폴더를 남기지 않는다")

    def test_a_recursion_error_inside_the_cell_scan_is_scanned_as_text_too(self):
        bs.plant_draft(self.world, '{"a": "' + bs.secret_text(KIND) + '"}')
        with mock.patch.object(bf, "_scan_json_value", side_effect=RecursionError("일부러 낸 재귀 한도")):
            error = bs.code_of(self.world.backup)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")

    def test_a_recursion_error_escaping_the_json_file_scan_is_an_easy_skip_not_a_crash(self):
        """훑기 밖(`check_json_bytes` 같은 엄격한 읽기)에서 재귀 한도가 나도 그 파일만 건너뛴다."""
        real = bf.check_json_bytes

        def deep(name, data):
            if name == layout.CALENDAR_FILE:
                raise RecursionError("일부러 낸 재귀 한도")
            return real(name, data)
        with mock.patch.object(bf, "check_json_bytes", deep):
            outcome = self.world.backup()
        lines = {line.name: line for line in outcome.row.files}
        self.assertEqual((outcome.row.status, lines[layout.CALENDAR_FILE].state), (bf.STATUS_PARTIAL, bf.LINE_SKIPPED))
        self.assertEqual(lines[layout.SEEDS_FILE].state, bf.LINE_SAVED)


if __name__ == "__main__":
    unittest.main()
