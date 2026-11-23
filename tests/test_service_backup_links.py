"""백업 폴더 자리에 놓인 링크(심볼릭 링크·junction)를 따라가 그 안의 앱 이름 파일을 지우는 틈을 막는 시험 — AS-S1 권고-1·참고-3(결정 D-608).

위협(감사 탐침 p3·p3b): `backups/` 안에 `full-YYYYMMDD-HHMMSS.tmp`(낡은 임시 폴더) 이름이나 낡은 백업 이름의 junction 이 있으면 폴더 자신이 링크인지 보지 않고 그 목적지의 항목을 훑어,
이름이 앱 이름(`chanceblog.db`·`settings.json` …)뿐이면 목적지의 파일을 지웠다 — 백업 **목록을 보기만 해도** 지워졌다(윈도에서 junction 의 `is_symlink()` 는 거짓이고 `is_dir()` 은 링크를 따라간다).
복원 임시 파일은 고정 이름(`<이름>.restoring`)이라 미리 심은 링크로 쓰기를 돌릴 수 있었다(참고-3).

지키는 것:
  1) `_is_link` 함수 하나가 폴더 자신과 항목을 함께 본다 — 심볼릭 링크·윈도 reparse point(junction·마운트 지점). 클라우드 파일 자리표시(OneDrive)는 링크가 아니다. 없는 경로는 거짓, 읽을 수 없으면 참.
  2) `_folders`·`_temp_folders`·`_remove_known_folder`·`_resolve`·`_verify_folder`·`_quick_row` 가 그 함수를 쓴다(소스 시험 — 옛 `is_symlink()` 반쪽 검사가 돌아오지 않는다).
  3) 링크인 폴더는 목록에 안 보이고 · 정리(임시 폴더·옛 백업)가 건드리지 않으며 · 복원 대상으로 받지 않고(`FULL_BACKUP_INVALID` 이유 `missing`) · 목적지의 파일은 그대로다.
  4) `<이름>.restoring` 자리에 미리 심은 링크는 그 이름만 지우고(목적지에 쓰지 않는다) 복원은 끝까지 간다.
junction 은 윈도에서만 만들 수 있으니 junction 시험은 윈도에서만 돈다. 심볼릭 링크 시험은 만들 수 있는 곳(리눅스·권한이 있는 윈도)에서 돈다 — 못 만들면 건너뛴다. 네트워크·실제 시계 없이 돈다.
"""
import ast
import contextlib
import os
import stat
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import test_service_backup_restore as tr  # noqa: E402

from chanceblog_desktop.service import backup_flow as bf  # noqa: E402

SOURCE = Path(bf.__file__)
IO_REPARSE_TAG_CLOUD = 0x9000001A                                                  # OneDrive 같은 클라우드 파일 자리표시의 reparse 종류(이름을 돌리는 링크가 아니다)
# 아래 둘은 `stat.IO_REPARSE_TAG_SYMLINK`·`stat.IO_REPARSE_TAG_MOUNT_POINT` 와 같은 값이지만 그 이름은 윈도 C 모듈(`_stat`)에만 있어 리눅스 판에는 없을 수 있다(AS2 시험 렌즈 Q 필수-2, D-619) — 어디서나 돌도록 숫자로 둔다
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def remove_link(path):
    """링크 자체를 지운다(목적지는 건드리지 않는다) — 이미 없으면 그대로 둔다."""
    if not os.path.lexists(path):
        return
    try:
        os.unlink(path)
    except OSError:
        os.rmdir(path)


def make_dir_link(link, target):
    """폴더 링크를 만든다 — 윈도는 junction(권한 없이 된다), 그 밖에는 심볼릭 링크. 만들 수 없으면 SkipTest → 만든 종류."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return "junction"
        os.symlink(target, link, target_is_directory=True)
        return "symlink"
    except (OSError, ImportError, AttributeError) as error:
        raise unittest.SkipTest(f"폴더 링크를 만들 수 없다: {type(error).__name__}") from None


def make_file_symlink(link, target):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as error:
        raise unittest.SkipTest(f"심볼릭 링크를 만들 수 없다: {type(error).__name__}") from None


def fake_lstat(mode=stat.S_IFDIR | 0o755, **fields):
    return SimpleNamespace(st_mode=mode, **fields)


class IsLinkTest(unittest.TestCase):
    def test_plain_files_folders_and_missing_names_are_not_links(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "folder"
            folder.mkdir()
            (folder / "file.txt").write_text("x", encoding="utf-8")
            for path in (folder, folder / "file.txt", Path(tmp) / "missing", folder / "file.txt" / "under-a-file"):
                with self.subTest(path=path.name):
                    self.assertFalse(bf._is_link(path))

    def test_the_reparse_attribute_alone_marks_a_link_when_the_kind_is_unknown_or_a_name_redirect(self):
        flagged = bf.REPARSE_POINT | 0x10
        cases = {
            "속성만(종류 모름)": (fake_lstat(st_file_attributes=flagged), True),
            "심볼릭 링크 종류": (fake_lstat(st_file_attributes=flagged, st_reparse_tag=IO_REPARSE_TAG_SYMLINK), True),
            "junction·마운트 지점 종류": (fake_lstat(st_file_attributes=flagged, st_reparse_tag=IO_REPARSE_TAG_MOUNT_POINT), True),
            "클라우드 파일 자리표시 종류": (fake_lstat(st_file_attributes=flagged, st_reparse_tag=IO_REPARSE_TAG_CLOUD), False),
            "reparse 속성 없음": (fake_lstat(st_file_attributes=0x10), False),
            "속성 칸 자체가 없음(윈도 아닌 곳)": (fake_lstat(), False),
            "모드가 심볼릭 링크": (fake_lstat(mode=stat.S_IFLNK | 0o777), True),
        }
        for label, (info, expected) in cases.items():
            with self.subTest(label=label), mock.patch.object(os, "lstat", return_value=info):
                self.assertEqual(bf._is_link(Path("anything")), expected)

    def test_errors_reading_the_name_itself_are_decided_the_safe_way(self):
        for error, expected in ((FileNotFoundError(2, "x"), False), (NotADirectoryError(20, "x"), False), (PermissionError(13, "x"), True), (OSError(5, "x"), True)):
            with self.subTest(error=type(error).__name__), mock.patch.object(os, "lstat", side_effect=error):
                self.assertEqual(bf._is_link(Path("anything")), expected)

    def test_a_real_folder_link_is_a_link_and_its_target_is_not(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            link = Path(tmp) / "link"
            make_dir_link(link, target)
            self.addCleanup(remove_link, link)
            self.assertTrue(bf._is_link(link))
            self.assertFalse(bf._is_link(target))
            remove_link(link)

    def test_a_real_file_symlink_is_a_link_and_its_target_is_not(self):
        """폴더 링크 시험과 나눴다(AS2 시험 렌즈 Q 참고-4, D-619) — 파일 심볼릭 링크를 못 만드는 환경(윈도의 일반 계정)에서 폴더 링크 쪽 성공이 '건너뜀' 개수에 묻히지 않는다."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            file_target = Path(tmp) / "file.txt"
            file_target.write_text("x", encoding="utf-8")
            file_link = Path(tmp) / "file-link.txt"
            make_file_symlink(file_link, file_target)
            self.addCleanup(remove_link, file_link)
            self.assertTrue(bf._is_link(file_link))
            self.assertFalse(bf._is_link(file_target))


class FolderLinksTest(tr.Base):
    def setUp(self):
        super().setUp()
        self.victim = Path(self.tmp.name) / "victim_outside"
        self.victim.mkdir()
        self.backups = self.ctx.workspace.backups_dir
        self.backups.mkdir(parents=True, exist_ok=True)

    def plant_victim(self, names=("chanceblog.db", "settings.json", "seeds.json", "chanceblog.db-wal")):
        for name in names:
            (self.victim / name).write_text("VICTIM-" + name, encoding="utf-8")
        return {name: (self.victim / name).read_text(encoding="utf-8") for name in names}

    def link_as(self, name):
        link = self.backups / name
        kind = make_dir_link(link, self.victim)
        self.addCleanup(remove_link, link)
        return link, kind

    def victim_state(self):
        return {path.name: path.read_text(encoding="utf-8") for path in sorted(self.victim.iterdir())}

    def test_listing_the_backups_does_not_sweep_a_link_named_like_a_stale_temp_folder(self):
        """감사 탐침 p3b — 목록 보기만 해도 목적지가 비던 길."""
        planted = self.plant_victim()
        link, _kind = self.link_as("full-20190101-000000.tmp")
        listing = bf.list_full_backups(self.ctx)
        self.assertEqual(self.victim_state(), planted, "목적지의 파일이 지워졌다")
        self.assertTrue(os.path.lexists(link), "링크 자체도 그대로다")
        self.assertEqual(listing.rows, ())

    def test_creating_a_backup_does_not_sweep_or_prune_through_a_link(self):
        """감사 탐침 p3 — 정리(`_prune`)가 낡은 백업 이름의 링크를 따라가던 길(탐침에서만 남길 개수를 1 로 낮춰 정리 대상이 되게 했다)."""
        planted = self.plant_victim(("settings.json", "seeds.json"))
        old, _kind = self.link_as("full-20190101-000000")
        sweepable, _kind = self.link_as("full-20190102-000000.tmp")
        with mock.patch.object(bf, "KEEP_BACKUPS", 1):
            outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        self.assertEqual(self.victim_state(), planted, "정리가 링크를 따라가 목적지의 파일을 지웠다")
        self.assertTrue(os.path.lexists(old) and os.path.lexists(sweepable))

    def test_a_link_is_not_listed_as_a_backup_and_is_not_a_restore_source_by_name_or_by_path(self):
        planted = self.plant_victim()
        link, _kind = self.link_as("full-20200101-000000")
        self.assertEqual([row.name for row in bf.list_full_backups(self.ctx).rows], [])
        before = tr.state_of(self.world)
        for source in (link.name, link):
            with self.subTest(source=str(type(source).__name__)):
                error = bs.code_of(bf.restore_full_backup, self.ctx, source, confirmed=True)
                self.assertIsNotNone(error)
                self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "missing"))
        self.assertEqual(tr.state_of(self.world), before)
        self.assertEqual(self.victim_state(), planted)

    def test_a_link_is_never_a_safety_copy_source_either(self):
        shelf = self.backups / bf.SAFETY_FOLDER
        shelf.mkdir(parents=True)
        planted = self.plant_victim()
        link = shelf / "before-20200101-000000"
        make_dir_link(link, self.victim)
        self.addCleanup(remove_link, link)
        self.assertEqual([row.name for row in bf.list_full_backups(self.ctx).rows], [])
        error = bs.code_of(bf.restore_full_backup, self.ctx, link.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "missing"))
        self.assertEqual(self.victim_state(), planted)

    def test_the_known_folder_remover_refuses_a_link_folder_and_leaves_its_target_alone(self):
        planted = self.plant_victim()
        link, _kind = self.link_as("full-20190101-000000.tmp")
        self.assertFalse(bf._remove_known_folder(link, bf.TEMP_FILES))
        self.assertEqual(self.victim_state(), planted)
        self.assertTrue(os.path.lexists(link))

    def test_the_known_folder_remover_refuses_a_folder_with_a_link_entry_and_leaves_its_target_alone(self):
        """폴더 링크 시험과 나눴다(AS2 시험 렌즈 Q 참고-4, D-619) — 파일 심볼릭 링크를 못 만드는 환경에서는 이 시험만 건너뛴다."""
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("OUTSIDE", encoding="utf-8")
        folder = self.backups / "full-20190103-000000.tmp"
        folder.mkdir()
        make_file_symlink(folder / "settings.json", outside)
        self.assertFalse(bf._remove_known_folder(folder, bf.TEMP_FILES), "링크인 항목이 든 폴더는 그대로 둔다")
        self.assertEqual(outside.read_text(encoding="utf-8"), "OUTSIDE")
        self.assertTrue(os.path.lexists(folder / "settings.json"))

    def test_a_backup_folder_that_is_itself_a_link_is_refused_by_the_verification(self):
        self.plant_victim()
        link, _kind = self.link_as("full-20200202-000000")
        error = bs.code_of(bf._verify_folder, link)
        self.assertIsNotNone(error)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "files"))

    def test_a_real_backup_next_to_a_link_is_still_listed_and_restorable(self):
        outcome = self.world.backup()
        self.plant_victim()
        self.link_as("full-20180101-000000")
        rows = bf.list_full_backups(self.ctx).rows
        self.assertEqual([row.name for row in rows], [outcome.row.name])
        tr.change_everything(self.world)
        result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)


@contextlib.contextmanager
def looks_like_a_link(path):
    """그 경로 하나만 윈도의 마운트 지점(reparse 속성 + 이름을 돌리는 종류)으로 보이게 한다 — 링크를 만들 수 없는 곳(권한 없는 계정·리눅스 CI 의 윈도 속성)에서도 속성 흉내로 같은 길을 돌린다. 다른 경로는 진짜로 묻는다."""
    target = os.path.normcase(os.fspath(path))
    real = os.lstat

    def fake(candidate, *args, **kwargs):
        if os.path.normcase(os.fspath(candidate)) == target:
            return fake_lstat(st_file_attributes=bf.REPARSE_POINT | 0x10, st_reparse_tag=IO_REPARSE_TAG_MOUNT_POINT)
        return real(candidate, *args, **kwargs)

    with mock.patch.object(os, "lstat", fake):
        yield


class RootLinkTest(tr.Base):
    """AS-S1 2차(안전 검증 S) 권고-2(D-618) — 링크 검사가 '마지막 이름'만 보던 틈. 안전 사본 폴더(`backups/before-restore`)나 백업 폴더(`backups`) **자신**이 링크이면 항목마다만 검사하던 옛 코드는 그 링크를 따라가
    목적지 안의 `before-날짜-시각.tmp` 폴더(앱 이름 파일만 든)를 목록을 한 번 보는 것만으로 지웠다(감사 권고-1 의 되풀이 — 한 칸 위에서). 이제 목록·임시 폴더 치우기·옛 사본 정리·이름으로 되돌릴 사본 찾기가 그 폴더 자신도 `_is_link` 로 보고,
    링크이면 빈 목록·치우지 않음·찾지 못함이다. 그 위(데이터 폴더 등)가 링크인 경우는 같은 사용자의 선택이라 따라간다(알려진 한계 — `docs/SECURITY.md`)."""

    def setUp(self):
        super().setUp()
        self.victim = Path(self.tmp.name) / "victim_outside"
        self.victim.mkdir()
        self.backups = self.ctx.workspace.backups_dir
        self.backups.mkdir(parents=True, exist_ok=True)

    def plant(self, prefix):
        """목적지에 앱 이름 파일만 든 낡은 임시 폴더 하나와 옛 사본처럼 보이는 폴더 둘을 둔다 → 이름과 내용의 표."""
        planted = {}
        for name in (prefix + "-20190101-000000.tmp", prefix + "-20190102-000000", prefix + "-20190103-000000"):
            folder = self.victim / name
            folder.mkdir()
            for entry in ("chanceblog.db", "settings.json", "MANIFEST.json"):
                (folder / entry).write_text("VICTIM-" + name + "-" + entry, encoding="utf-8")
            planted[name] = sorted(entry.name for entry in folder.iterdir())
        return planted

    def victim_state(self):
        return {folder.name: sorted(entry.name for entry in folder.iterdir()) for folder in sorted(self.victim.iterdir())}

    def test_a_safety_folder_that_is_itself_a_link_is_not_listed_swept_or_pruned_and_its_target_stays(self):
        planted = self.plant("before")
        link = self.backups / bf.SAFETY_FOLDER
        make_dir_link(link, self.victim)
        self.addCleanup(remove_link, link)
        listing = bf.list_full_backups(self.ctx)
        self.assertEqual(listing.rows, ())
        self.assertEqual(self.victim_state(), planted, "목록을 보기만 해도 링크 목적지의 폴더가 지워졌다")
        self.assertEqual(bf._temp_folders(self.ctx), [])
        self.assertEqual(bf._folders(link, bf.SAFETY_NAME), [])
        bf._prune(link, 1, bf.SAFETY_NAME)
        self.assertEqual(self.victim_state(), planted, "정리가 링크 목적지의 폴더를 지웠다")

    def test_a_backup_folder_that_is_itself_a_link_is_not_listed_swept_or_pruned_and_its_target_stays(self):
        planted = self.plant("full")
        os.rmdir(self.backups)                                           # 빈 폴더였다 — 그 자리에 링크를 둔다
        make_dir_link(self.backups, self.victim)
        self.addCleanup(remove_link, self.backups)
        self.assertEqual(bf.list_full_backups(self.ctx).rows, ())
        self.assertEqual(self.victim_state(), planted)
        self.assertEqual(bf._folders(self.backups), [])
        bf._prune(self.backups, 1)
        self.assertEqual(self.victim_state(), planted)

    def test_a_folder_in_a_link_root_is_not_a_restore_source_by_name(self):
        self.plant("before")
        link = self.backups / bf.SAFETY_FOLDER
        make_dir_link(link, self.victim)
        self.addCleanup(remove_link, link)
        before = self.victim_state()
        error = bs.code_of(bf.restore_full_backup, self.ctx, "before-20190102-000000", confirmed=True)
        self.assertIsNotNone(error)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "missing"))
        self.assertEqual(self.victim_state(), before)

    def test_the_same_holds_when_only_the_attribute_says_the_root_is_a_link(self):
        """링크를 만들 수 없는 곳에서도 도는 흉내 — 진짜 폴더 하나를 마운트 지점 속성으로 보이게 한다. 대조: 링크가 아니면 같은 호출이 낡은 임시 폴더를 치운다."""
        shelf = self.backups / bf.SAFETY_FOLDER
        stale = shelf / "before-20190101-000000.tmp"
        stale.mkdir(parents=True)
        (stale / "chanceblog.db").write_text("STALE", encoding="utf-8")
        copy = shelf / "before-20190102-000000"
        copy.mkdir()
        with looks_like_a_link(shelf):
            self.assertEqual(bf._temp_folders(self.ctx), [])
            self.assertEqual(bf._folders(shelf, bf.SAFETY_NAME), [])
            bf.list_full_backups(self.ctx)
            bf._prune(shelf, 1, bf.SAFETY_NAME)
            error = bs.code_of(bf._resolve, self.ctx, copy.name)
            self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "missing"), "링크처럼 보이는 폴더 안의 이름을 되돌릴 사본으로 받았다")
        self.assertTrue((stale / "chanceblog.db").exists(), "링크처럼 보이는 폴더 안을 치웠다")
        self.assertEqual(bf._resolve(self.ctx, copy.name), copy, "대조 — 링크가 아니면 그 이름을 찾는다")
        bf.list_full_backups(self.ctx)
        self.assertFalse(stale.exists(), "대조 — 링크가 아니면 같은 목록 호출이 낡은 임시 폴더를 치운다")

    def test_a_real_safety_folder_and_a_real_backup_folder_are_still_listed_swept_and_restorable(self):
        outcome = self.world.backup()
        tr.change_everything(self.world)
        self.assertEqual([row.name for row in bf.list_full_backups(self.ctx).rows], [outcome.row.name])
        result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(len(bf.list_full_backups(self.ctx).rows), 2, "복원 직전 안전 사본도 목록에 있다")
        safety = bf.list_full_backups(self.ctx).rows[0]
        self.assertEqual(bf._resolve(self.ctx, safety.name).name, safety.name)


class StageLinkTest(tr.Base):
    """복원 임시 파일의 고정 이름(`<이름>.restoring`) 자리에 미리 심은 링크(AS-S1 참고-3)."""

    def test_a_symlink_planted_at_the_staging_name_is_removed_and_the_target_is_never_written(self):
        outcome = self.world.backup()
        tr.change_everything(self.world)
        outside = Path(self.tmp.name) / "outside_of_the_data_folder.txt"
        outside.write_text("OUTSIDE-CONTENT", encoding="utf-8")
        stage = self.world.path("settings.json").with_name("settings.json.restoring")
        make_file_symlink(stage, outside)
        self.addCleanup(remove_link, stage)
        result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual(outside.read_text(encoding="utf-8"), "OUTSIDE-CONTENT", "링크를 따라가 그 목적지에 복원 내용을 썼다")
        self.assertFalse(os.path.lexists(stage), "임시 파일 자리가 비워졌다")
        saved_settings = (self.ctx.workspace.backups_dir / outcome.row.name / "settings.json").read_bytes()
        self.assertEqual(self.world.path("settings.json").read_bytes(), saved_settings)

    @unittest.skipUnless(os.name == "nt", "junction 은 윈도에서만 만든다")
    def test_a_junction_planted_at_the_staging_name_is_removed_by_name_and_its_target_is_never_written(self):
        outcome = self.world.backup()
        tr.change_everything(self.world)
        victim = Path(self.tmp.name) / "stage_victim"
        victim.mkdir()
        (victim / "settings.json").write_text("VICTIM", encoding="utf-8")
        stage = self.world.path("settings.json").with_name("settings.json.restoring")
        make_dir_link(stage, victim)
        self.addCleanup(remove_link, stage)
        result = bf.restore_full_backup(self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertEqual((victim / "settings.json").read_text(encoding="utf-8"), "VICTIM", "junction 을 따라가 목적지에 썼다")
        self.assertFalse(os.path.lexists(stage))

    def test_clearing_a_stage_name_that_has_nothing_or_a_plain_leftover_is_quiet(self):
        stage = self.world.path("settings.json").with_name("settings.json.restoring")
        bf._clear_stage(stage)
        stage.write_bytes(b"leftover")
        bf._clear_stage(stage)
        self.assertFalse(stage.exists())

    def test_a_stage_name_that_stays_a_link_is_refused_with_an_os_error_the_flow_already_translates(self):
        stage = self.world.path("settings.json").with_name("settings.json.restoring")
        with mock.patch.object(bf, "_remove_quietly", return_value=False), mock.patch.object(bf, "_is_link", return_value=True):
            with self.assertRaises(OSError):
                bf._clear_stage(stage)


class SourceShapeTest(unittest.TestCase):
    """옛 반쪽 검사(`is_symlink()` — 윈도 junction 은 거짓)가 돌아오지 않는다."""

    def tree(self):
        return ast.parse(SOURCE.read_text(encoding="utf-8"))

    def function(self, name):
        return next(node for node in ast.walk(self.tree()) if isinstance(node, ast.FunctionDef) and node.name == name)

    def test_no_half_check_is_left_in_the_backup_flow(self):
        """심볼릭 링크를 직접 묻는 `is_symlink()` 는 `_is_link` 안에만 있다 — 다른 곳의 반쪽 검사(윈도 junction 은 거짓)가 돌아오지 않는다."""
        tree = self.tree()
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_is_link")
        inside = {id(node) for node in ast.walk(function)}
        outside = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "is_symlink" and id(node) not in inside]
        self.assertEqual(outside, [], "링크 검사는 `_is_link` 하나다")
        self.assertIn("is_symlink", {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)})

    def test_every_place_that_walks_backup_folders_uses_the_one_function(self):
        for name in ("_folders", "_temp_folders", "_remove_known_folder", "_resolve", "_verify_folder", "_quick_row", "_clear_stage"):
            with self.subTest(function=name):
                called = {node.func.id for node in ast.walk(self.function(name)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
                self.assertTrue({"_is_link"} & called, f"{name} 이 `_is_link` 를 부르지 않는다")

    def test_the_folders_that_hold_backups_are_checked_themselves_not_only_their_entries(self):
        """AS-S1 2차 권고-2(D-618) — 항목마다만 `_is_link` 를 걸던 옛 모양이 돌아오지 않는다: 목록·임시 폴더 치우기·이름 찾기가 `root` 자신도 본다. 정리(`_prune`)는 후보를 `_folders` 로 구하므로 같은 검사를 거친다(아래 호출 시험)."""
        for name in ("_folders", "_temp_folders", "_resolve"):
            with self.subTest(function=name):
                roots = [node for node in ast.walk(self.function(name)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_is_link"
                         and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "root"]
                self.assertTrue(roots, f"{name} 이 `_is_link(root)` 로 폴더 자신을 보지 않는다")
        called = {node.func.id for node in ast.walk(self.function("_prune")) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("_folders", called, "정리는 후보를 `_folders` 로 구한다 — 폴더 자신의 링크 검사를 거친다")

    def test_the_link_check_looks_at_the_name_itself_never_through_it(self):
        called = {ast.unparse(node.func) for node in ast.walk(self.function("_is_link")) if isinstance(node, ast.Call)}
        self.assertIn("os.lstat", called)
        self.assertNotIn("os.stat", called)
        self.assertEqual(bf.REPARSE_POINT, 0x400)
        self.assertEqual(bf.LINK_TAGS, {IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT}, "이름을 돌리는 reparse 종류는 심볼릭 링크와 junction·마운트 지점뿐이다")

    def test_no_windows_only_stat_name_is_used_by_the_backup_flow_or_by_this_test_file(self):
        """AS2 시험 렌즈 Q 필수-2(D-619) — `stat.IO_REPARSE_TAG_*` 는 윈도 C 모듈에만 있는 이름이라 리눅스에서 `AttributeError` 가 난다(`stat.FILE_ATTRIBUTE_*` 는 `stat.py` 가 정의해 어디서나 된다). 제품 코드와 이 시험 파일은 그 값을 숫자로만 쓴다."""
        for path in (SOURCE, Path(__file__)):
            with self.subTest(file=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                used = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "stat" and node.attr.startswith("IO_REPARSE_TAG_")]
                self.assertEqual(used, [], "윈도에만 있는 stat 이름을 쓰지 않는다 — 숫자로 둔다")


if __name__ == "__main__":
    unittest.main()
