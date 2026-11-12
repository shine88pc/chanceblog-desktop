"""전체 복원(`service/backup_flow.py` 의 `restore_full_backup`) 시험 — 바꾸기 전에 모두 확인하고, 안전 사본을 먼저 남기고, 도중에 실패하면 원래대로 돌리며, 재난 뒤 빈 폴더에서도 같은 데이터를 되찾는다(BACKUPUI, P4d 완료 조건 ④⑥⑦).

지키는 것:
  1) 확인(`confirmed=True`)이 없으면 아무것도 하지 않는다. 백업의 목록·파일 이름·크기·해시·보관함 이름표·판·점검·JSON 모양이 하나라도 틀리면(바이트 하나 바뀜·파일 빠짐·목록 위조) 거절하고 **지금 데이터는 그대로**이며 안전 사본·잠금·임시 파일도 남기지 않는다.
     더 새로운 앱(버전)의 백업은 거절한다.
  2) 복원 결과: 보관함은 논리적으로(덤프) 같고 JSON·설정은 바이트가 같다. 키 보관소·`connections.json`·`quota_state.json`·`publish/` 는 건드리지 않는다. 복원 직전 상태는 `before-restore/` 안전 사본이고 그것으로 다시 복원하면 직전 상태로 돌아온다.
  3) 완료(백업의 모든 파일을 바꿨고 백업도 완전했다) · 부분(백업이 부분이었다 — 담기지 않은 항목은 지금 것을 그대로 둠) · 실패(원래대로 돌렸다 — `RESTORE_FAILED`)가 한 가지로 알려진다.
  4) 도중 어디서 실패해도(쓰기 거절·디스크 가득·보관함 바꾸기 실패·바꾼 뒤 점검 실패·취소) 지금까지 바꾼 것을 안전 사본으로 되돌린다. 되돌리다 또 실패하면 이름을 알리고 안전 사본으로 다시 복원할 수 있다.
  5) 깨진 지금 파일은 지우지 않고 옆(`.bad-…`)으로 옮기고, 더 새로운 앱의 데이터·다른 곳이 쓰는 중인 파일은 덮어쓰지 않는다. 데이터 폴더를 통째로 지운 뒤 빈 폴더(다른 PC)에서도 복원된다.
네트워크·실제 시계·실제 자격 증명 관리자 없이 돈다.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security.backup_note import RESTORE_NOTE  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service import connections, projects  # noqa: E402
from chanceblog_desktop.service.context import write_json  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

NAMES = ("chanceblog.db", layout.ENGINE_DB_FILE, layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE, layout.CALENDAR_FILE, "settings.json")
DBS = ("chanceblog.db", layout.ENGINE_DB_FILE)
PLAIN = tuple(name for name in NAMES if name not in DBS)


def state_of(world):
    """지금 데이터의 '논리적 모습' — JSON·설정은 바이트, 보관함은 덤프. 되돌린 뒤 보관함 파일의 바이트는 달라도 내용은 같다."""
    found = {name: hashlib.sha256(world.path(name).read_bytes()).hexdigest() for name in PLAIN if world.path(name).is_file()}
    found.update({f"{name}:dump": "\n".join(bs.dump(world.path(name))) for name in DBS if world.path(name).is_file()})
    return found


def change_everything(world):
    """백업 뒤에 데이터를 바꿔 둔다 — 글 하나 더, 초안 바꿈, Seed·캘린더·프로필·설정을 바꿈, 주제 후보 하나 더."""
    projects.new_project(world.ctx, "백업 뒤에 쓴 글", "새로 쓴 본문")
    with world.ctx.store() as store:
        store.save_draft(world.ids[0], "백업 뒤에 고친 초안")
    for name, key in ((layout.SEEDS_FILE, "keyword"), (layout.CALENDAR_FILE, "name"), (layout.CHANNEL_PROFILES_FILE, "alias"), ("settings.json", "display_name")):
        data = json.loads(world.path(name).read_text(encoding="utf-8"))
        patched = [False]

        def walk(value):
            if isinstance(value, dict):
                for field in list(value):
                    if field == key and isinstance(value[field], str):
                        value[field] = value[field] + " (고침)"
                        patched[0] = True
                        return
                    walk(value[field])
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(data)
        if not patched[0] and name == layout.CHANNEL_PROFILES_FILE:
            data["profiles"][0]["intro"] = "고친 소개"
        write_json(world.path(name), data)
    with bs.contextlib.closing(sqlite3.connect(str(world.path(layout.ENGINE_DB_FILE)))) as connection:
        connection.execute("UPDATE review_log SET last_run_on = last_run_on")
        connection.execute("INSERT INTO review_log (kind, last_run_on) VALUES ('고침', '2026-11-11')")
        connection.commit()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.cleanup)
        self.world = bs.World(self.tmp.name)
        self.ctx = self.world.ctx

    def cleanup(self):
        for path in Path(self.tmp.name).rglob("*"):
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
        self.tmp.cleanup()

    def restore(self, name, **kwargs):
        return bf.restore_full_backup(self.ctx, name, confirmed=True, **kwargs)

    def safety_root(self):
        return self.ctx.workspace.backups_dir / bf.SAFETY_FOLDER

    def assert_untouched(self, before, *, safety=False):
        self.assertEqual(state_of(self.world), before, "지금 데이터는 그대로여야 한다")
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()) if self.ctx.workspace.locks_dir.is_dir() else [], [], "잠금이 남았다")
        leftovers = [path.name for path in self.world.root.rglob("*") if path.name.endswith((".restoring", ".tmp"))]
        self.assertEqual(leftovers, [], "임시 파일이 남았다")
        if not safety:
            self.assertFalse(self.safety_root().exists() and list(self.safety_root().iterdir()), "안전 사본을 만들지 않았다")


class ConfirmationAndNamesTest(Base):
    def test_without_the_confirmation_nothing_happens(self):
        outcome = self.world.backup()
        change_everything(self.world)
        before = state_of(self.world)
        for value in (False, None, 1, "yes", "true", 0):
            with self.subTest(value=value):
                error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=value)
                self.assertEqual(error.code, "CONFIRMATION_REQUIRED")
        with self.assertRaises(TypeError):
            bf.restore_full_backup(self.ctx, outcome.row.name)
        self.assert_untouched(before)

    def test_names_that_are_not_backup_names_are_refused_without_being_repeated(self):
        outcome = self.world.backup()
        before = state_of(self.world)
        key = bs.secret_token("google_api_key")
        for typed in ("full-20990101-000000", key, "..\\..\\x", "../x", "full-20261102-013012/../..", "", "x" * 400, "full-20261102-013012\n"):
            with self.subTest(typed=typed[:20]):
                error = bs.code_of(bf.restore_full_backup, self.ctx, typed, confirmed=True)
                self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "missing"))
                self.assertFalse(bs.S.leaked(str(error) + error.log_line(), key), "친 글을 되풀이하지 않는다")
        self.assertIn(outcome.row.name, [row.name for row in bf.list_full_backups(self.ctx).rows])
        self.assert_untouched(before)

    def test_a_folder_path_object_is_accepted_for_a_backup_kept_elsewhere(self):
        outcome = self.world.backup()
        usb = Path(self.tmp.name) / "usb 메모리"
        shutil.copytree(self.world.folder(outcome), usb / outcome.row.name)
        change_everything(self.world)
        result = bf.restore_full_backup(self.ctx, usb / outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(bs.code_of(bf.restore_full_backup, self.ctx, usb / "없는 폴더", confirmed=True).code, "FULL_BACKUP_INVALID")


class RestoreResultTest(Base):
    def test_restore_brings_back_the_backup_state_and_keeps_a_safety_copy_of_the_state_before(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        change_everything(self.world)
        changed = state_of(self.world)
        self.assertNotEqual(changed, saved)
        result = self.restore(outcome.row.name)
        self.assertEqual(state_of(self.world), saved, "백업을 만들던 때의 상태로 돌아왔다")
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual([(line.name, line.state) for line in result.files], [(name, "restored") for name in NAMES])
        self.assertIn(RESTORE_NOTE, result.notes)
        self.assertRegex(result.safety, r"^before-\d{8}-\d{6}$", "안전 사본은 백업(full-…)과 이름이 겹치지 않는다")
        rows = {row.name + row.kind: row for row in bf.list_full_backups(self.ctx).rows}
        self.assertEqual(rows[result.safety + "safety"].status, bf.STATUS_COMPLETE)
        self.assertEqual(self.safety_root().exists(), True)
        self.assertTrue((self.safety_root() / result.safety).is_dir())

    def test_restoring_the_safety_copy_puts_the_state_from_before_the_restore_back(self):
        outcome = self.world.backup()
        change_everything(self.world)
        changed = state_of(self.world)
        first = self.restore(outcome.row.name)
        self.ctx.clock.advance(seconds=30)
        second = self.restore(first.safety)
        self.assertEqual(state_of(self.world), changed, "되돌리는 법 — 안전 사본으로 다시 복원하면 직전 상태다")
        self.assertEqual(second.status, bf.STATUS_COMPLETE)
        self.assertRegex(second.safety, r"^before-\d{8}-\d{6}$")
        self.assertNotEqual(second.safety, first.safety)

    def test_the_restore_does_not_touch_keys_connections_quota_or_the_publish_records(self):
        connections.add_entry(self.ctx, "image_provider", name="내 이미지 키", fields={"access_key": "CANARY_" + "Ab3dEf5hIj7kLm9n"}, provider="unsplash", keystore=self.ctx.keystore)
        (self.world.root / "quota_state.json").write_text('{"예시": 1}', encoding="utf-8")
        (self.world.root / "publish").mkdir()
        (self.world.root / "publish" / "abc.json").write_text('{"예시": 2}', encoding="utf-8")
        outcome = self.world.backup()
        change_everything(self.world)
        keep = {name: (self.world.root / name).read_bytes() for name in ("connections.json", "quota_state.json", "publish/abc.json")}
        blobs = dict(self.ctx.keystore._blobs)
        self.restore(outcome.row.name)
        self.assertEqual({name: (self.world.root / name).read_bytes() for name in keep}, keep)
        self.assertEqual(self.ctx.keystore._blobs, blobs)
        self.assertEqual(connections.load(self.ctx).of_purpose("image_provider")[0].name, "내 이미지 키")

    def test_a_restore_that_changes_nothing_new_still_reports_complete(self):
        outcome = self.world.backup()
        result = self.restore(outcome.row.name)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)

    def test_the_restored_stores_open_normally_and_hold_the_same_rows(self):
        outcome = self.world.backup()
        before = bs.dump(self.world.path("chanceblog.db"))
        change_everything(self.world)
        self.restore(outcome.row.name)
        self.assertEqual(bs.dump(self.world.path("chanceblog.db")), before)
        self.assertEqual([row.title for row in projects.list_projects(self.ctx)].count("백업 뒤에 쓴 글"), 0)
        self.assertEqual(len(projects.list_projects(self.ctx)), 2)

    def test_the_safety_copy_keeps_only_files_that_are_about_to_be_replaced(self):
        outcome = self.world.backup()
        for name in (layout.SEEDS_FILE, layout.CALENDAR_FILE):
            self.world.path(name).unlink()
        result = self.restore(outcome.row.name)
        safety = self.safety_root() / result.safety
        manifest = json.loads((safety / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest["files"]), sorted(set(NAMES) - {layout.SEEDS_FILE, layout.CALENDAR_FILE}), "지금 있던 것만 안전 사본에 담는다")
        self.assertEqual((manifest["missing"], manifest["skipped"]), ([], {}))
        self.assertEqual(self.world.path(layout.SEEDS_FILE).is_file(), True, "백업에 있던 것은 없던 자리에도 되살아난다")
        self.ctx.clock.advance(seconds=30)
        self.restore(result.safety)
        self.assertEqual(self.world.path(layout.SEEDS_FILE).is_file(), True, "안전 사본에 없는 파일(복원 전에 없던 것)은 되돌릴 때 지우지 않는다")

    def test_a_partial_backup_restores_what_it_holds_and_leaves_the_rest_as_it_is(self):
        self.world.path(layout.SEEDS_FILE).write_text("{ 깨짐", encoding="utf-8")
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_PARTIAL)
        good_seed = json.dumps({"schema": 2, "seeds": []})
        self.world.path(layout.SEEDS_FILE).write_text(good_seed, encoding="utf-8")
        change_everything(self.world)
        seeds_now = self.world.path(layout.SEEDS_FILE).read_bytes()
        result = self.restore(outcome.row.name)
        self.assertEqual(result.status, bf.STATUS_PARTIAL)
        lines = {line.name: line for line in result.files}
        self.assertEqual((lines[layout.SEEDS_FILE].state, lines[layout.SEEDS_FILE].reason), ("kept", "TOPIC_FILE_INVALID"))
        self.assertEqual(self.world.path(layout.SEEDS_FILE).read_bytes(), seeds_now, "백업에 없는 파일은 지금 것을 그대로 둔다")
        self.assertTrue(any("부분" in note for note in result.notes))

    def test_a_backup_that_misses_components_leaves_the_current_ones_alone(self):
        small = bs.World(tempfile.mkdtemp(dir=self.tmp.name), engine=False, profiles=False, seeds=False, calendar=False, settings=False)
        outcome = small.backup()
        shutil.copytree(small.folder(outcome), self.ctx.workspace.backups_dir / outcome.row.name)
        before = state_of(self.world)
        result = self.restore(outcome.row.name)
        after = state_of(self.world)
        for name in (layout.ENGINE_DB_FILE + ":dump", *PLAIN):
            self.assertEqual(after.get(name), before.get(name), name)
        self.assertEqual([(line.name, line.state) for line in result.files], [("chanceblog.db", "restored")] + [(name, "kept") for name in NAMES[1:]])

    def test_after_a_successful_restore_the_lock_and_temp_files_are_gone(self):
        outcome = self.world.backup()
        self.restore(outcome.row.name)
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])
        self.assertEqual([path for path in self.world.root.rglob("*") if path.name.endswith((".restoring", ".tmp", ".bad-"))], [])

    def test_the_progress_steps_go_forward_and_end_at_one(self):
        outcome = self.world.backup()
        seen = []
        self.restore(outcome.row.name, step=lambda fraction, text="": seen.append(fraction))
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)


class DisasterTest(Base):
    def test_a_deleted_data_folder_is_rebuilt_from_a_backup_copied_back_in(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        kept_copy = Path(self.tmp.name) / "밖에 둔 사본"
        shutil.copytree(self.world.folder(outcome), kept_copy / outcome.row.name)
        shutil.rmtree(self.world.root)
        self.assertFalse(self.world.root.exists())
        result = bf.restore_full_backup(self.ctx, kept_copy / outcome.row.name, confirmed=True)
        self.assertEqual(state_of(self.world), saved, "논리적으로 같다 — 덤프·JSON 바이트·settings.json 까지")
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(result.safety, "", "빈 폴더에는 남길 지금 데이터가 없다")
        self.assertFalse(self.safety_root().exists())
        self.assertFalse((self.world.root / "connections.json").exists(), "키 연결 정보는 백업에 없었으니 되살아나지 않는다")

    def test_a_backup_folder_copied_into_a_new_data_folder_shows_up_in_the_list_and_restores(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        new_home = bs.World(tempfile.mkdtemp(dir=self.tmp.name), posts=0, drafts=0, candidates_count=0, engine=False, profiles=False, seeds=False, calendar=False, settings=False)
        new_ctx = new_home.ctx
        shutil.copytree(self.world.folder(outcome), new_ctx.workspace.backups_dir / outcome.row.name)
        listing = bf.list_full_backups(new_ctx)
        self.assertEqual([(row.name, row.status) for row in listing.rows], [(outcome.row.name, bf.STATUS_COMPLETE)])
        bf.restore_full_backup(new_ctx, outcome.row.name, confirmed=True)
        self.assertEqual(state_of(new_home), saved)

    def test_the_connected_folder_of_the_old_pc_is_kept_and_the_result_tells_it_may_be_missing(self):
        outcome = self.world.backup()
        saved_settings = self.world.path("settings.json").read_bytes()
        kept_copy = Path(self.tmp.name) / "밖에 둔 사본"
        shutil.copytree(self.world.folder(outcome), kept_copy / outcome.row.name)
        shutil.rmtree(self.world.root)
        shutil.rmtree(self.tmp.name + "/chanceblog", ignore_errors=True)
        result = bf.restore_full_backup(self.ctx, kept_copy / outcome.row.name, confirmed=True)
        self.assertEqual(self.world.path("settings.json").read_bytes(), saved_settings, "연결한 폴더 경로도 그대로 — 비우지 않는다")
        self.assertTrue(any("연결해 둔 chanceblog 폴더" in note for note in result.notes), result.notes)

    def test_the_notes_do_not_mention_the_connected_folder_when_it_still_exists(self):
        outcome = self.world.backup()
        result = self.restore(outcome.row.name)
        self.assertFalse(any("연결해 둔" in note for note in result.notes))

    def test_a_restore_into_an_empty_but_existing_folder_with_a_blank_database_file_works(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        kept_copy = Path(self.tmp.name) / "밖에 둔 사본"
        shutil.copytree(self.world.folder(outcome), kept_copy / outcome.row.name)
        shutil.rmtree(self.world.root)
        self.world.root.mkdir(parents=True)
        self.world.path("chanceblog.db").write_bytes(b"")
        result = bf.restore_full_backup(self.ctx, kept_copy / outcome.row.name, confirmed=True)
        self.assertEqual(state_of(self.world), saved)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)


class TamperTest(Base):
    def setUp(self):
        super().setUp()
        self.outcome = self.world.backup()
        self.folder = self.world.folder(self.outcome)
        change_everything(self.world)
        self.before = state_of(self.world)

    def attempt(self, code, reason=None):
        error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertIsNotNone(error, "거절돼야 한다")
        self.assertEqual(error.code, code, error.detail)
        if reason is not None:
            self.assertEqual(error.reason, reason)
        self.assert_untouched(self.before)
        return error

    def test_changing_one_byte_of_any_file_refuses_the_restore(self):
        for name in NAMES:
            with self.subTest(name=name):
                path = self.folder / name
                original = path.read_bytes()
                changed = bytearray(original)
                changed[len(changed) // 2] ^= 0x01
                path.write_bytes(bytes(changed))
                try:
                    self.attempt("FULL_BACKUP_INVALID", "hash")
                finally:
                    path.write_bytes(original)

    def test_deleting_any_file_refuses_the_restore(self):
        for name in NAMES:
            with self.subTest(name=name):
                path = self.folder / name
                original = path.read_bytes()
                path.unlink()
                try:
                    self.attempt("FULL_BACKUP_INVALID", "files")
                finally:
                    path.write_bytes(original)

    def test_an_extra_file_or_folder_in_the_backup_refuses_the_restore(self):
        (self.folder / "connections.json").write_text("{}", encoding="utf-8")
        self.attempt("FULL_BACKUP_INVALID", "files")
        (self.folder / "connections.json").unlink()
        (self.folder / "하위 폴더").mkdir()
        self.attempt("FULL_BACKUP_INVALID", "files")

    def forge(self, mutate):
        manifest = json.loads((self.folder / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        mutate(manifest)
        bs.write_manifest(self.folder, manifest)

    def test_a_forged_manifest_refuses_the_restore(self):
        original = (self.folder / bf.MANIFEST_NAME).read_bytes()
        cases = {
            "hash": lambda m: m["files"]["seeds.json"].update(sha256="0" * 64),
            "size": lambda m: m["files"]["seeds.json"].update(size=m["files"]["seeds.json"]["size"] + 1),
            "unknown field": lambda m: m.update(extra="x"),
            "removed field": lambda m: m.pop("excluded"),
            "credential flag": lambda m: m.update(credential_excluded=False),
            "status": lambda m: m.update(status="partial"),
            "kind": lambda m: m.update(kind="other"),
            "unknown file": lambda m: m["files"].update({"connections.json": dict(m["files"]["seeds.json"])}),
            "file listed twice": lambda m: m["missing"].append("seeds.json"),
            "bad time": lambda m: m.update(created_at="어제"),
            "bad version": lambda m: m.update(app_version="아주 새 버전"),
            "bad hash text": lambda m: m["files"]["seeds.json"].update(sha256="XYZ"),
            "negative size": lambda m: m["files"]["seeds.json"].update(size=-1),
            "items not numbers": lambda m: m["files"]["seeds.json"].update(items={"count": "많이"}),
            "empty files": lambda m: m.update(files={}),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                try:
                    self.forge(mutate)
                    self.attempt("FULL_BACKUP_INVALID")
                finally:
                    (self.folder / bf.MANIFEST_NAME).write_bytes(original)

    def test_a_manifest_that_cannot_be_read_refuses_the_restore(self):
        original = (self.folder / bf.MANIFEST_NAME).read_bytes()
        for label, data in (("not json", "{ 깨짐".encode("utf-8")), ("empty", b""), ("list", b"[]"), ("not utf8", b"\xff\xfe\x00"), ("too big", b" " * (bf.MAX_MANIFEST_BYTES + 5))):
            with self.subTest(label=label):
                try:
                    (self.folder / bf.MANIFEST_NAME).write_bytes(data)
                    self.attempt("FULL_BACKUP_INVALID", "manifest")
                finally:
                    (self.folder / bf.MANIFEST_NAME).write_bytes(original)
        (self.folder / bf.MANIFEST_NAME).unlink()
        self.attempt("FULL_BACKUP_INVALID", "manifest")

    def test_a_database_that_is_not_a_database_but_has_the_right_hash_is_refused_by_the_content_check(self):
        path = self.folder / "chanceblog.db"
        path.write_bytes(b"this is not a database " * 30)
        self.forge(lambda m: m["files"]["chanceblog.db"].update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.attempt("FULL_BACKUP_INVALID", "content")

    def test_a_json_file_with_the_wrong_shape_but_the_right_hash_is_refused_by_the_content_check(self):
        path = self.folder / layout.SEEDS_FILE
        path.write_text('{"schema": 99, "seeds": "아님"}', encoding="utf-8")
        self.forge(lambda m: m["files"][layout.SEEDS_FILE].update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.attempt("FULL_BACKUP_INVALID", "content")

    def test_a_settings_file_with_an_unknown_field_is_refused(self):
        path = self.folder / "settings.json"
        path.write_text(json.dumps({"schema": 1, "repo_path": "", "naver_profiles": {}, "모르는 칸": 1}), encoding="utf-8")
        self.forge(lambda m: m["files"]["settings.json"].update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.attempt("FULL_BACKUP_INVALID", "content")

    def test_a_listing_of_a_tampered_backup_does_not_stop_at_it(self):
        (self.folder / "seeds.json").write_bytes(b"{}")
        rows = bf.list_full_backups(self.ctx).rows
        self.assertEqual([row.status for row in rows], [bf.STATUS_BROKEN])


class VersionTest(Base):
    def test_a_backup_made_by_a_newer_app_is_refused_and_a_same_or_older_one_is_accepted(self):
        for current, backup, accepted in (("0.1.0", "99.0.0", False), ("0.1.0", "0.1.1", False), ("0.1.0", "0.2.0", False), ("1.0.0", "0.9.9", True), ("0.1.0", "0.1.0", True), ("0.1.0", "", True),
                                          ("0.1.0", "0.1.0-preview.1", True), ("0.1.0-preview.1", "0.1.0", False), ("0.1.0-preview.2", "0.1.0-preview.1", True), ("0.0.0", "0.0.0", True)):
            with self.subTest(current=current, backup=backup):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World.cached(tmp)
                    with mock.patch.object(bf, "read_app_version", return_value=backup):
                        outcome = world.backup()
                    before = state_of(world)
                    with mock.patch.object(bf, "read_app_version", return_value=current):
                        if accepted:
                            self.assertEqual(bf.restore_full_backup(world.ctx, outcome.row.name, confirmed=True).status, bf.STATUS_COMPLETE)
                        else:
                            error = bs.code_of(bf.restore_full_backup, world.ctx, outcome.row.name, confirmed=True)
                            self.assertEqual((error.code, error.reason), ("STORE_VERSION_UNSUPPORTED", "newer"))
                            self.assertEqual(state_of(world), before)

    def test_a_backup_holding_a_store_made_by_a_newer_app_is_refused_even_if_the_manifest_looks_old(self):
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        bs_sql = bs.contextlib.closing(sqlite3.connect(str(folder / "chanceblog.db")))
        with bs_sql as connection:
            connection.execute("PRAGMA user_version = 99")
            connection.commit()
        manifest = self.world.manifest(outcome)
        manifest["files"]["chanceblog.db"].update(size=(folder / "chanceblog.db").stat().st_size, sha256=hashlib.sha256((folder / "chanceblog.db").read_bytes()).hexdigest())
        bs.write_manifest(folder, manifest)
        before = state_of(self.world)
        error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("STORE_VERSION_UNSUPPORTED", "newer"))
        self.assertEqual(state_of(self.world), before)

    def test_current_data_made_by_a_newer_app_is_not_overwritten(self):
        outcome = self.world.backup()
        with bs.contextlib.closing(sqlite3.connect(str(self.world.path("chanceblog.db")))) as connection:
            connection.execute("PRAGMA user_version = 99")
            connection.commit()
        before = state_of(self.world)
        error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("STORE_VERSION_UNSUPPORTED", "newer"))
        self.assertEqual(state_of(self.world), before)
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])
        self.assertFalse(self.safety_root().exists() and list(self.safety_root().iterdir()))

    def test_current_data_that_another_program_is_writing_is_not_overwritten(self):
        outcome = self.world.backup()
        before = state_of(self.world)
        real = bf.open_read_only
        live = self.world.path(layout.ENGINE_DB_FILE)

        def opener(path):
            if Path(path) == live:
                raise AppError("TOPIC_STORE_LOCKED")
            return real(path)
        with mock.patch.object(bf, "open_read_only", side_effect=opener):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("TOPIC_STORE_LOCKED", "busy"))
        self.assertEqual(state_of(self.world), before)
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])


class DamagedCurrentFilesTest(Base):
    def test_a_damaged_current_store_is_moved_aside_not_deleted_and_the_backup_is_restored(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        garbage = b"this is not a database " * 40
        self.world.path("chanceblog.db").write_bytes(garbage)
        result = self.restore(outcome.row.name)
        self.assertEqual(state_of(self.world), saved)
        aside = [path for path in self.world.root.glob("chanceblog.db.bad-*")]
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_bytes(), garbage, "깨진 파일의 내용은 그대로 옆에 있다")
        self.assertTrue(any("깨져 있던" in note and "글 보관함" in note for note in result.notes), result.notes)

    def test_damaged_json_files_are_moved_aside_too(self):
        outcome = self.world.backup()
        saved = state_of(self.world)
        self.world.path(layout.SEEDS_FILE).write_text("{ 깨짐", encoding="utf-8")
        self.world.path("settings.json").write_text("[1, 2]", encoding="utf-8")
        self.restore(outcome.row.name)
        self.assertEqual(state_of(self.world), saved)
        self.assertEqual(len(list(self.world.root.glob("settings.json.bad-*"))), 1)
        self.assertEqual(len(list((self.world.root / "topic_engine").glob("seeds.json.bad-*"))), 1)

    def test_when_the_restore_fails_the_damaged_files_are_put_back_where_they_were(self):
        outcome = self.world.backup()
        garbage = b"this is not a database " * 40
        self.world.path("chanceblog.db").write_bytes(garbage)
        self.world.path(layout.SEEDS_FILE).write_text("{ 깨짐", encoding="utf-8")
        with mock.patch.object(bf, "_restore_database", side_effect=sqlite3.OperationalError("disk I/O error")):
            error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "RESTORE_FAILED")
        self.assertEqual(self.world.path("chanceblog.db").read_bytes(), garbage)
        self.assertEqual(self.world.path(layout.SEEDS_FILE).read_text(encoding="utf-8"), "{ 깨짐")
        self.assertEqual(list(self.world.root.glob("*.bad-*")) + list((self.world.root / "topic_engine").glob("*.bad-*")), [])


class FailureInjectionTest(Base):
    def setUp(self):
        super().setUp()
        self.outcome = self.world.backup()
        change_everything(self.world)
        self.before = state_of(self.world)

    def fail_restore(self, expect_reason=None, **patches):
        with mock.patch.multiple(bf, **patches):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "RESTORE_FAILED", error.detail)
        if expect_reason:
            self.assertEqual(error.reason, expect_reason)
        return error

    def test_a_refused_write_while_putting_a_json_file_in_place_restores_everything(self):
        calls = []
        real = bf._swap_in

        def flaky(stage, target):
            calls.append(target.name)
            if len(calls) == 2:
                raise PermissionError(13, "Permission denied")
            return real(stage, target)
        error = self.fail_restore("io", _swap_in=flaky)
        self.assertEqual(error.notes, ())
        self.assert_untouched(self.before, safety=True)
        self.assertEqual(len(calls) >= 2, True)

    def test_a_failure_while_replacing_the_first_store_leaves_the_json_files_as_they_were(self):
        error = self.fail_restore("io", _restore_database=mock.Mock(side_effect=sqlite3.OperationalError("disk I/O error")))
        self.assertEqual(error.notes, ())
        self.assert_untouched(self.before, safety=True)

    def test_a_failure_while_replacing_the_second_store_puts_the_first_store_back_from_the_safety_copy(self):
        calls, real = [], bf._restore_database

        def flaky(component, path, source):
            calls.append(component.name)
            if len(calls) == 2:
                raise sqlite3.OperationalError("database or disk is full")
            return real(component, path, source)
        error = self.fail_restore("disk", _restore_database=flaky)
        self.assertEqual(error.notes, ())
        self.assertEqual(calls[:2], ["chanceblog.db", layout.ENGINE_DB_FILE])
        self.assertEqual(len(calls), 3, "첫 보관함을 안전 사본으로 되돌렸다")
        self.assert_untouched(self.before, safety=True)

    def test_a_check_after_the_change_that_fails_rolls_everything_back(self):
        error = self.fail_restore("io", _after_check=mock.Mock(side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})))
        self.assert_untouched(self.before, safety=True)
        self.assertEqual(error.notes, ())

    def test_a_database_that_reads_back_wrong_rolls_everything_back(self):
        error = self.fail_restore("corrupt", _after_check=mock.Mock(side_effect=AppError("STORE_CORRUPT", {"파일": "chanceblog.db"})))
        self.assert_untouched(self.before, safety=True)
        self.assertEqual(error.reason, "corrupt")

    def test_disk_full_while_staging_a_file_restores_everything(self):
        real = bf._write_durably
        calls = []

        def flaky(path, data):
            calls.append(Path(path).name)
            if str(path).endswith(".restoring") and len(calls) > 8:
                raise OSError(28, "No space left on device")
            return real(path, data)
        error = self.fail_restore("disk", _write_durably=flaky)
        self.assert_untouched(self.before, safety=True)
        self.assertEqual(error.notes, ())

    def test_cancelling_during_the_change_rolls_back_and_raises_the_cancel(self):
        class Cancelled(Exception):
            pass

        def step(fraction, text=""):
            if 0.5 <= fraction < 0.9:
                raise Cancelled()
        with self.assertRaises(Cancelled):
            bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True, step=step)
        self.assert_untouched(self.before, safety=True)

    def test_cancelling_before_the_change_leaves_everything_untouched(self):
        class Cancelled(Exception):
            pass

        def step(fraction, text=""):
            if fraction < 0.4:
                raise Cancelled()
        with self.assertRaises(Cancelled):
            bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True, step=step)
        self.assert_untouched(self.before, safety=False)

    def test_when_even_the_rollback_fails_the_names_are_told_and_the_safety_copy_restores_the_old_state(self):
        calls, real = [], bf._restore_database

        def flaky(component, path, source):
            calls.append(component.name)
            if len(calls) == 1:
                return real(component, path, source)
            raise sqlite3.OperationalError("disk I/O error")
        error = self.fail_restore("io", _restore_database=flaky)
        self.assertTrue(any("글 보관함" in note and "원래대로 돌리지 못했어요" in note for note in error.notes), error.notes)
        safety = [row for row in bf.list_full_backups(self.ctx).rows if row.kind == "safety"]
        self.assertEqual(len(safety), 1)
        self.ctx.clock.advance(seconds=30)
        bf.restore_full_backup(self.ctx, safety[0].name, confirmed=True)
        self.assertEqual(state_of(self.world), self.before, "그 사본으로 다시 복원하면 직전 상태다")

    def test_a_json_file_that_cannot_be_put_back_is_named(self):
        calls, real = [], bf._swap_in

        def flaky(stage, target):
            calls.append(target.name)
            if len(calls) == 1:
                return real(stage, target)
            raise PermissionError(13, "denied")
        error = bs.code_of(self.run_restore_with, _swap_in=flaky, _restore_database=mock.Mock(side_effect=sqlite3.OperationalError("disk I/O error")))
        self.assertEqual(error.code, "RESTORE_FAILED")

    def run_restore_with(self, **patches):
        with mock.patch.multiple(bf, **patches):
            return bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True)

    def test_a_failed_restore_is_not_counted_as_success_and_the_next_one_works(self):
        self.fail_restore("io", _restore_database=mock.Mock(side_effect=sqlite3.OperationalError("disk I/O error")))
        result = bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)

    def test_the_safety_copy_that_could_not_be_made_stops_the_restore_before_anything_changes(self):
        with mock.patch.object(bf, "_write_sqlite", side_effect=sqlite3.OperationalError("database or disk is full")):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "DISK_FULL")
        self.assert_untouched(self.before, safety=True)


class ReadOnlyAndPathTest(Base):
    def test_a_read_only_current_settings_file_either_gets_replaced_or_the_restore_rolls_back_cleanly(self):
        outcome = self.world.backup()
        change_everything(self.world)
        before = state_of(self.world)
        os.chmod(self.world.path("settings.json"), stat.S_IREAD)
        try:
            try:
                result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
            except AppError as error:
                self.assertEqual(error.code, "RESTORE_FAILED")
                os.chmod(self.world.path("settings.json"), stat.S_IWRITE | stat.S_IREAD)
                self.assertEqual(state_of(self.world), before)
            else:
                self.assertEqual(result.status, bf.STATUS_COMPLETE)
        finally:
            os.chmod(self.world.path("settings.json"), stat.S_IWRITE | stat.S_IREAD)

    def test_a_data_folder_with_spaces_and_korean_letters_restores(self):
        base = Path(self.tmp.name) / "내 문서 with spaces" / "블로그 데이터"
        base.mkdir(parents=True)
        world = bs.World(base)
        outcome = world.backup()
        saved = state_of(world)
        change_everything(world)
        result = bf.restore_full_backup(world.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(state_of(world), saved)


class SourceKindTest(Base):
    def test_a_backup_kept_in_the_safety_folder_is_found_by_name_and_listed_with_the_safety_kind(self):
        outcome = self.world.backup()
        result = self.restore(outcome.row.name)
        kinds = {(row.name, row.kind) for row in bf.list_full_backups(self.ctx).rows}
        self.assertIn((outcome.row.name, "backup"), kinds)
        self.assertIn((result.safety, "safety"), kinds)

    def test_only_ten_safety_copies_are_kept_and_the_one_being_restored_from_survives(self):
        outcome = self.world.backup()
        made = []
        for _ in range(12):
            self.ctx.clock.advance(seconds=3)
            made.append(self.restore(outcome.row.name).safety)
        safety = [row.name for row in bf.list_full_backups(self.ctx).rows if row.kind == "safety"]
        self.assertEqual(len(safety), bf.KEEP_BACKUPS)
        self.assertEqual(sorted(safety), sorted(made[-bf.KEEP_BACKUPS:]))
        oldest = sorted(safety)[0]
        self.ctx.clock.advance(seconds=3)
        self.restore(oldest)
        names = [row.name for row in bf.list_full_backups(self.ctx).rows if row.kind == "safety"]
        self.assertIn(oldest, names, "되돌리는 데 쓴 사본은 그 자리에서 지워지지 않는다")


if __name__ == "__main__":
    unittest.main()
