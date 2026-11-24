"""주제 엔진 백업(`topicdb/backup.py`)이 링크·정션을 따라가지 않는 시험 — AS-S2 권고-2(결정 D-690).

위협(감사 탐침 09): 전체 백업(`service/backup_flow.py`)은 AS-S1 에서 링크 검사(`_is_link`)를 받았지만 주제 엔진 백업의 목록·정리는 `is_dir()`(링크를 따라간다)만 믿었다.
`backups/topic_engine/` 안에 가장 낡은 백업 이름(`topic-YYYYMMDD-HHMMSS`)의 정션(윈도의 폴더 링크)이 있으면 다음 백업이 끝날 때 도는 정리(`_prune`)가 그 정션을 '낡은 백업' 으로 보고
목적지 폴더(살아 있는 데이터 폴더일 수 있다)의 앱 이름 파일 넷을 지웠다. 임시 이름(`….tmp`)·복원 임시 이름(`<이름>.restoring`)·읽을 백업 폴더 자리에 링크를 놓는 같은 계열의 길도 있었다.

지키는 것:
  1) `_is_link` 가 전체 백업의 같은 이름 함수와 **같은 기준**이다(심볼릭 링크·윈도 재해석 지점 중 링크 종류, 클라우드 파일 자리표시는 링크가 아니다, 없는 경로는 거짓, 읽을 수 없으면 참) — 표를 두 함수에 함께 먹여 못박는다.
  2) 목록(`list_backups`)은 링크인 항목을 빼고 폴더 자신이 링크이면 비어 있다 · 정리(`_prune`·`_clear_known`)는 링크인 폴더·링크 항목이 든 폴더를 건드리지 않고 목적지의 파일은 그대로다.
  3) 백업을 만들 때 임시 이름 자리의 링크는 따라가지 않고 **만들지 않는다**(BACKUP_FAILED) — 목적지는 그대로다.
  4) 읽을 백업 폴더가 링크이면 쉬운 오류(TOPIC_BACKUP_INVALID, 이유에 '링크')로 거절하고 아무것도 바꾸지 않는다 · 폴더 안의 파일이 링크여도 같다.
  5) 복원의 임시 이름(`<이름>.restoring`) 자리에 미리 심은 링크는 그 이름만 지우고 목적지에는 쓰지 않으며, 치우지 못하면 쓰지 않고 멈춘다.
  6) 소스 시험 — 링크를 직접 묻는 `is_symlink()` 는 `_is_link` 안에만 있고 위 길마다 `_is_link` 를 부른다.
junction 은 윈도에서만 만들 수 있다 — 진짜 링크 시험은 윈도에서는 junction, 그 밖에서는 심볼릭 링크로 돌고 만들 수 없으면(권한이 없는 윈도 계정의 파일 링크 …) 그 시험만 건너뛴다.
**링크를 만들 수 없는 곳에서도** 같은 길이 돌도록 폴더·파일 하나를 '링크처럼 보이게'(윈도의 재해석 속성 흉내) 하는 시험을 따로 둔다. 네트워크·실제 시계 없이 돈다.
"""
import ast
import contextlib
import datetime
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_topicdb_backup as base  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop import fslink  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topicdb import backup as bk  # noqa: E402
from chanceblog_desktop.topics import layout, seeds  # noqa: E402

SOURCE = Path(bk.__file__)
FSLINK_SOURCE = Path(fslink.__file__)                            # 링크 판정 한 곳(`fslink.py`) — 주제 엔진 백업은 그 함수를 가져다 쓴다
REPARSE_POINT = 0x400                                            # 윈도 파일 속성 FILE_ATTRIBUTE_REPARSE_POINT(제품 상수와 같은 값인지는 아래 시험이 못박는다)
IO_REPARSE_TAG_CLOUD = 0x9000001A                                # OneDrive 같은 클라우드 파일 자리표시 — 이름을 돌리는 링크가 아니다
IO_REPARSE_TAG_SYMLINK = 0xA000000C                              # `stat.IO_REPARSE_TAG_*` 는 윈도 C 모듈에만 있어 숫자로 둔다(리눅스에서 AttributeError)
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
LATER = base.NOW + datetime.timedelta(minutes=5)


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


@contextlib.contextmanager
def looks_like_a_link(*paths):
    """그 경로들만 윈도의 마운트 지점(재해석 속성 + 이름을 돌리는 종류)으로 보이게 한다 — 링크를 만들 수 없는 곳에서도 속성 흉내로 같은 길을 돌린다. 다른 경로는 진짜로 묻는다."""
    targets = {os.path.normcase(os.fspath(path)) for path in paths}
    real = os.lstat

    def fake(candidate, *args, **kwargs):
        if os.path.normcase(os.fspath(candidate)) in targets:
            return fake_lstat(st_file_attributes=REPARSE_POINT | 0x10, st_reparse_tag=IO_REPARSE_TAG_MOUNT_POINT)
        return real(candidate, *args, **kwargs)

    with mock.patch.object(os, "lstat", fake):
        yield


def code_and_reason(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code, str((error.slots or {}).get("이유", ""))
    return None, ""


class IsLinkTest(unittest.TestCase):
    CASES = {
        "속성만(종류 모름)": (fake_lstat(st_file_attributes=REPARSE_POINT | 0x10), True),
        "심볼릭 링크 종류": (fake_lstat(st_file_attributes=REPARSE_POINT | 0x10, st_reparse_tag=IO_REPARSE_TAG_SYMLINK), True),
        "junction·마운트 지점 종류": (fake_lstat(st_file_attributes=REPARSE_POINT | 0x10, st_reparse_tag=IO_REPARSE_TAG_MOUNT_POINT), True),
        "클라우드 파일 자리표시 종류": (fake_lstat(st_file_attributes=REPARSE_POINT | 0x10, st_reparse_tag=IO_REPARSE_TAG_CLOUD), False),
        "재해석 속성 없음": (fake_lstat(st_file_attributes=0x10), False),
        "속성 칸 자체가 없음(윈도 아닌 곳)": (fake_lstat(), False),
        "모드가 심볼릭 링크": (fake_lstat(mode=stat.S_IFLNK | 0o777), True),
    }
    ERRORS = ((FileNotFoundError(2, "x"), False), (NotADirectoryError(20, "x"), False), (PermissionError(13, "x"), True), (OSError(5, "x"), True))

    def test_plain_files_folders_and_missing_names_are_not_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "folder"
            folder.mkdir()
            (folder / "file.txt").write_text("x", encoding="utf-8")
            for path in (folder, folder / "file.txt", Path(tmp) / "missing", folder / "file.txt" / "under-a-file"):
                with self.subTest(path=path.name):
                    self.assertFalse(bk._is_link(path))

    def test_the_reparse_attribute_and_its_kind_decide_exactly_like_the_full_backups_check(self):
        for label, (info, expected) in self.CASES.items():
            with self.subTest(label=label), mock.patch.object(os, "lstat", return_value=info):
                self.assertEqual(bk._is_link(Path("anything")), expected)

    def test_errors_reading_the_name_itself_are_decided_the_safe_way(self):
        for error, expected in self.ERRORS:
            with self.subTest(error=type(error).__name__), mock.patch.object(os, "lstat", side_effect=error):
                self.assertEqual(bk._is_link(Path("anything")), expected)

    def test_the_topic_backup_uses_the_one_shared_function(self):
        self.assertIs(bk._is_link, fslink.is_link)
        self.assertEqual((bk.REPARSE_POINT, bk.LINK_TAGS), (fslink.REPARSE_POINT, fslink.LINK_TAGS))

    def test_the_two_checks_agree_on_every_case_and_share_their_constants(self):
        """'전체 백업과 같은 기준' 을 말이 아니라 표로 못박는다 — 한쪽 기준만 바뀌면 여기서 빨개진다."""
        self.assertEqual((bk.REPARSE_POINT, bk.LINK_TAGS), (bf.REPARSE_POINT, bf.LINK_TAGS))
        for label, (info, _expected) in self.CASES.items():
            with self.subTest(label=label), mock.patch.object(os, "lstat", return_value=info):
                self.assertEqual(bk._is_link(Path("anything")), bf._is_link(Path("anything")))
        for error, _expected in self.ERRORS:
            with self.subTest(error=type(error).__name__), mock.patch.object(os, "lstat", side_effect=error):
                self.assertEqual(bk._is_link(Path("anything")), bf._is_link(Path("anything")))

    def test_a_real_folder_link_is_a_link_and_its_target_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            link = Path(tmp) / "link"
            make_dir_link(link, target)
            self.addCleanup(remove_link, link)
            self.assertTrue(bk._is_link(link))
            self.assertFalse(bk._is_link(target))
            self.assertEqual(bk._is_link(link), bf._is_link(link))
            remove_link(link)

    def test_a_real_file_symlink_is_a_link_and_its_target_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_target = Path(tmp) / "file.txt"
            file_target.write_text("x", encoding="utf-8")
            file_link = Path(tmp) / "file-link.txt"
            make_file_symlink(file_link, file_target)
            self.addCleanup(remove_link, file_link)
            self.assertTrue(bk._is_link(file_link))
            self.assertFalse(bk._is_link(file_target))


class LinkBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = base.World(self.tmp.name)
        self.root = self.world.backups
        self.root.mkdir(parents=True, exist_ok=True)
        self.victim = Path(self.tmp.name) / "victim_outside"
        self.victim.mkdir()

    def plant_victim(self, names=None):
        """링크 목적지에 앱 이름 파일을 둔다(살아 있는 데이터 폴더처럼) → 이름과 내용의 표."""
        names = tuple(names or bk.BACKUP_FILES)
        for name in names:
            (self.victim / name).write_text("VICTIM-" + name, encoding="utf-8")
        return {name: (self.victim / name).read_text(encoding="utf-8") for name in names}

    def victim_state(self):
        return {path.name: path.read_text(encoding="utf-8") for path in sorted(self.victim.iterdir())}

    def link_as(self, name, parent=None):
        link = (parent or self.root) / name
        kind = make_dir_link(link, self.victim)
        self.addCleanup(remove_link, link)
        return link, kind

    def real_backup(self, seconds=0):
        return self.world.backup(now=base.NOW + datetime.timedelta(seconds=seconds)).path

    def stale_folder(self, parent, name, files=None):
        """앱 이름 파일만 든 낡은 백업 모양의 진짜 폴더(링크처럼 보이게 하는 시험의 대상)."""
        folder = Path(parent) / name
        folder.mkdir(parents=True)
        for entry in files or (*bk.BACKUP_FILES, bk.MANIFEST_NAME):
            (folder / entry).write_text("STALE-" + entry, encoding="utf-8")
        return folder


class ListAndPruneTest(LinkBase):
    def test_a_link_named_like_a_backup_is_not_listed_and_the_prune_leaves_its_target_alone(self):
        """감사 탐침 09 — 가장 낡은 백업 이름의 정션 하나가 정리 때 목적지의 앱 이름 파일 넷을 지웠다."""
        planted = self.plant_victim()
        real = self.real_backup()
        link, _kind = self.link_as("topic-20200101-000000")
        self.assertEqual(bk.list_backups(self.root), [real], "링크는 백업 목록에 없다")
        bk._prune(self.root, 1)
        self.assertEqual(self.victim_state(), planted, "정리가 링크를 따라가 목적지의 파일을 지웠다")
        self.assertTrue(os.path.lexists(link), "링크 자체도 그대로다")
        self.assertTrue(real.is_dir())

    def test_making_a_backup_prunes_real_old_backups_but_never_walks_through_a_link(self):
        planted = self.plant_victim()
        oldest = self.real_backup(seconds=-3600)
        middle = self.real_backup(seconds=-1800)
        link, _kind = self.link_as("topic-20200101-000000")
        made = self.world.backup(keep=2).path                                 # 새 백업이 끝날 때 도는 정리 — 진짜 가장 낡은 것은 지워지고 링크는 목록에 없다
        self.assertEqual(self.victim_state(), planted, "새 백업의 정리가 링크 목적지의 파일을 지웠다")
        self.assertTrue(os.path.lexists(link))
        self.assertFalse(oldest.exists(), "대조 — 진짜 낡은 백업은 개수를 넘으면 지워진다")
        self.assertTrue(middle.exists() and made.exists())

    def test_a_folder_that_only_looks_like_a_link_is_skipped_by_the_listing_and_the_prune_even_where_no_link_can_be_made(self):
        """링크를 만들 수 없는 곳에서도 도는 흉내 — 진짜 폴더 하나를 재해석 속성으로 보이게 한다. 대조: 링크가 아니면 같은 호출이 그 폴더를 낡은 백업으로 치운다."""
        real = self.real_backup()
        stale = self.stale_folder(self.root, "topic-20200101-000000")
        with looks_like_a_link(stale):
            self.assertEqual(bk.list_backups(self.root), [real])
            bk._prune(self.root, 1)
            self.assertFalse(bk._clear_known(stale), "링크처럼 보이는 폴더는 앱 이름 파일뿐이어도 치우지 않는다")
        self.assertEqual(sorted(entry.name for entry in stale.iterdir()), sorted((*bk.BACKUP_FILES, bk.MANIFEST_NAME)), "링크처럼 보이는 폴더 안을 지웠다")
        self.assertEqual(bk.list_backups(self.root), [real, stale], "대조 — 링크가 아니면 목록에 든다")
        bk._prune(self.root, 1)
        self.assertFalse(stale.exists(), "대조 — 링크가 아니면 같은 정리가 낡은 백업을 치운다")

    def test_a_backups_folder_that_is_itself_a_link_is_not_listed_or_pruned_and_its_target_stays(self):
        planted_old = {}
        for name in ("topic-20190101-000000", "topic-20190102-000000", "topic-20190103-000000"):
            folder = self.stale_folder(self.victim, name)
            planted_old[name] = sorted(entry.name for entry in folder.iterdir())
        os.rmdir(self.root)                                                    # 빈 폴더였다 — 그 자리에 링크를 둔다
        make_dir_link(self.root, self.victim)
        self.addCleanup(remove_link, self.root)
        self.assertEqual(bk.list_backups(self.root), [])
        bk._prune(self.root, 1)
        self.assertEqual({folder.name: sorted(entry.name for entry in folder.iterdir()) for folder in sorted(self.victim.iterdir())}, planted_old, "정리가 링크 목적지의 백업 폴더를 지웠다")
        self.assertEqual(base.code_of(bk.resolve_backup, self.root, latest=True), "TOPIC_BACKUP_INVALID", "링크 폴더에서는 '가장 최근 백업' 도 찾지 않는다")

    def test_the_root_folder_that_only_looks_like_a_link_is_not_listed_either(self):
        self.real_backup()
        with looks_like_a_link(self.root):
            self.assertEqual(bk.list_backups(self.root), [])
        self.assertEqual(len(bk.list_backups(self.root)), 1, "대조 — 링크가 아니면 목록에 든다")

    def test_latest_skips_a_link_even_when_its_name_is_the_newest(self):
        self.plant_victim()
        real = self.real_backup()
        self.link_as("topic-20990101-000000")
        self.assertEqual(bk.resolve_backup(self.root, latest=True), real)

    def test_the_known_folder_remover_refuses_a_link_folder_and_a_folder_with_a_link_entry(self):
        planted = self.plant_victim()
        link, _kind = self.link_as("topic-20190101-000000.tmp")
        self.assertFalse(bk._clear_known(link))
        self.assertEqual(self.victim_state(), planted)
        self.assertTrue(os.path.lexists(link))
        folder = self.stale_folder(self.root, "topic-20190102-000000.tmp")
        with looks_like_a_link(folder / bk.BACKUP_FILES[0]):
            self.assertFalse(bk._clear_known(folder), "링크인 항목이 든 폴더는 그대로 둔다")
        self.assertEqual(len(list(folder.iterdir())), len(bk.BACKUP_FILES) + 1)
        self.assertTrue(bk._clear_known(folder), "대조 — 링크가 없으면 앱 이름 파일뿐인 폴더를 치운다")
        self.assertFalse(folder.exists())

    @unittest.skipUnless(os.name == "nt", "junction 은 윈도에서만 만든다")
    def test_the_audit_probe_on_windows_a_real_junction_in_the_oldest_name_slot(self):
        planted = self.plant_victim()
        self.real_backup()
        link, kind = self.link_as("topic-20200101-000000")
        self.assertEqual(kind, "junction")
        self.assertFalse(link.is_symlink(), "윈도 junction 의 is_symlink() 는 거짓이다 — 옛 반쪽 검사가 못 거르던 이유")
        self.assertTrue(link.is_dir())
        bk._prune(self.root, 1)
        self.assertEqual(self.victim_state(), planted)
        self.assertTrue(os.path.lexists(link))


class MakeBackupTest(LinkBase):
    def test_a_link_in_the_temporary_name_slot_is_not_followed_and_no_backup_is_made(self):
        planted = self.plant_victim()
        link, _kind = self.link_as("topic-20261106-080000.tmp")                  # NOW 의 임시 이름 자리
        with self.assertRaises(AppError) as caught:
            self.world.backup()
        self.assertEqual(caught.exception.code, "BACKUP_FAILED")
        self.assertIn("링크", str(caught.exception.detail), "'이미 있다' 같은 우연한 실패가 아니라 링크라서 멈췄다고 말한다")
        self.assertEqual(self.victim_state(), planted, "임시 폴더 치우기가 링크를 따라가 목적지의 파일을 지웠다")
        self.assertTrue(os.path.lexists(link))
        self.assertEqual(bk.list_backups(self.root), [], "만든 백업이 없다")

    def test_a_temporary_name_slot_that_only_looks_like_a_link_stops_the_backup_the_same_way(self):
        stale = self.stale_folder(self.root, "topic-20261106-080000.tmp")
        with looks_like_a_link(stale):
            with self.assertRaises(AppError) as caught:
                self.world.backup()
        self.assertEqual(caught.exception.code, "BACKUP_FAILED")
        self.assertIn("링크", str(caught.exception.detail))
        self.assertEqual(len(list(stale.iterdir())), len(bk.BACKUP_FILES) + 1, "링크처럼 보이는 임시 폴더 안을 지웠다")
        self.assertEqual(bk.list_backups(self.root), [])
        self.assertEqual(self.world.backup().path.name, "topic-20261106-080000", "대조 — 링크가 아니면 낡은 임시 폴더를 치우고 백업이 만들어진다")


class ReadAndRestoreTest(LinkBase):
    def setUp(self):
        super().setUp()
        self.backup = self.real_backup()

    def change_live(self):
        base.put_json(self.world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(seed_id="changed-1", keyword="예시 바뀐 씨앗")]))

    def restore(self, source, **kwargs):
        return bk.restore_backup(source, self.world.data, self.world.backups, now=LATER, **kwargs)

    def test_a_backup_folder_that_is_a_link_to_a_perfectly_good_backup_is_still_refused(self):
        link = Path(self.tmp.name) / "linked" / "topic-20300101-000000"
        link.parent.mkdir()
        make_dir_link(link, self.backup)
        self.addCleanup(remove_link, link)
        self.change_live()
        live_before = base.digests(self.world.data)
        for call in (bk.read_backup, self.restore):
            with self.subTest(call=getattr(call, "__name__", "restore")):
                code, reason = code_and_reason(call, link)
                self.assertEqual(code, "TOPIC_BACKUP_INVALID")
                self.assertIn("링크", reason, "이유를 쉬운 말로 알린다")
        self.assertEqual(base.digests(self.world.data), live_before, "지금 데이터는 한 바이트도 바뀌지 않았다")
        self.assertFalse((self.world.backups / bk.SAFETY_FOLDER).exists(), "거절한 복원은 안전 백업도 만들지 않는다")

    def test_a_backup_folder_that_only_looks_like_a_link_is_refused_and_the_same_folder_is_fine_otherwise(self):
        with looks_like_a_link(self.backup):
            code, reason = code_and_reason(bk.read_backup, self.backup)
            self.assertEqual(code, "TOPIC_BACKUP_INVALID")
            self.assertIn("링크", reason)
            self.assertEqual(code_and_reason(self.restore, self.backup)[0], "TOPIC_BACKUP_INVALID")
        manifest, contents = bk.read_backup(self.backup)
        self.assertEqual(set(contents), set(layout.USER_DATA_FILES), "대조 — 링크가 아니면 같은 폴더를 읽는다")
        self.assertEqual(manifest["schema"], bk.MANIFEST_SCHEMA)

    def test_a_file_that_is_a_link_inside_a_backup_is_refused_even_when_the_content_matches(self):
        outside = Path(self.tmp.name) / "outside_copy.json"
        outside.write_bytes((self.backup / layout.SEEDS_FILE).read_bytes())
        os.unlink(self.backup / layout.SEEDS_FILE)
        make_file_symlink(self.backup / layout.SEEDS_FILE, outside)
        self.addCleanup(remove_link, self.backup / layout.SEEDS_FILE)
        code, reason = code_and_reason(bk.read_backup, self.backup)
        self.assertEqual(code, "TOPIC_BACKUP_INVALID")
        self.assertIn("링크", reason)

    def test_a_file_that_only_looks_like_a_link_inside_a_backup_is_refused_where_no_link_can_be_made(self):
        for name in (*layout.USER_DATA_FILES, bk.MANIFEST_NAME):
            with self.subTest(name=name), looks_like_a_link(self.backup / name):
                code, reason = code_and_reason(bk.read_backup, self.backup)
                self.assertEqual(code, "TOPIC_BACKUP_INVALID")
                self.assertIn("링크", reason)
        self.assertEqual(set(bk.read_backup(self.backup)[1]), set(layout.USER_DATA_FILES))

    def test_a_symlink_planted_at_the_restore_staging_name_is_removed_and_its_target_is_never_written(self):
        """복원의 임시 이름(`<이름>.restoring`)은 고정이라 미리 심은 링크로 쓰기를 돌릴 수 있었다(전체 백업의 AS-S1 참고-3 과 같은 길)."""
        self.change_live()
        outside = Path(self.tmp.name) / "outside_of_the_data_folder.txt"
        outside.write_text("OUTSIDE-CONTENT", encoding="utf-8")
        stage = self.world.data / (layout.SEEDS_FILE + ".restoring")
        make_file_symlink(stage, outside)
        self.addCleanup(remove_link, stage)
        original = (self.backup / layout.SEEDS_FILE).read_bytes()
        result = self.restore(self.backup)
        self.assertEqual(layout.SEEDS_FILE in result.restored, True)
        self.assertEqual(outside.read_text(encoding="utf-8"), "OUTSIDE-CONTENT", "링크를 따라가 그 목적지에 복원 내용을 썼다")
        self.assertFalse(os.path.lexists(stage), "임시 이름 자리가 비워졌다")
        self.assertEqual((self.world.data / layout.SEEDS_FILE).read_bytes(), original)

    @unittest.skipUnless(os.name == "nt", "junction 은 윈도에서만 만든다")
    def test_a_junction_planted_at_the_restore_staging_name_is_removed_by_name_and_its_target_is_never_written(self):
        self.change_live()
        (self.victim / layout.SEEDS_FILE).write_text("VICTIM", encoding="utf-8")
        stage = self.world.data / (layout.SEEDS_FILE + ".restoring")
        make_dir_link(stage, self.victim)
        self.addCleanup(remove_link, stage)
        self.restore(self.backup)
        self.assertEqual((self.victim / layout.SEEDS_FILE).read_text(encoding="utf-8"), "VICTIM", "junction 을 따라가 목적지에 썼다")
        self.assertFalse(os.path.lexists(stage))

    def test_a_staging_name_that_stays_a_link_stops_the_restore_before_the_live_files_change(self):
        self.change_live()
        live_before = base.digests(self.world.data)
        with mock.patch.object(bk, "_remove_quietly", return_value=False), mock.patch.object(bk, "_is_link", side_effect=lambda path: Path(path).name.endswith(".restoring")):
            code, _reason = code_and_reason(self.restore, self.backup)
        self.assertEqual(code, "FILE_WRITE_FAILED", "치우지 못한 임시 링크 자리는 쉬운 쓰기 오류로 멈춘다")
        self.assertEqual(base.digests(self.world.data), live_before, "멈춘 복원은 지금 파일을 바꾸지 않았다")
        self.assertEqual([entry for entry in os.listdir(self.world.data) if entry.endswith(".restoring")], [])


class SourceShapeTest(unittest.TestCase):
    """옛 반쪽 검사(`is_dir()`·`is_symlink()` — 윈도 junction 은 따라가거나 거짓)가 돌아오지 않는다."""

    def tree(self):
        return ast.parse(SOURCE.read_text(encoding="utf-8"))

    def function(self, name):
        return next(node for node in ast.walk(self.tree()) if isinstance(node, ast.FunctionDef) and node.name == name)

    def called_names(self, name):
        return {node.func.id for node in ast.walk(self.function(name)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

    def test_no_half_check_is_left_in_the_topic_backup_and_the_shared_function_holds_the_whole_check(self):
        outside = [node.lineno for node in ast.walk(self.tree()) if isinstance(node, ast.Attribute) and node.attr == "is_symlink"]
        self.assertEqual(outside, [], "주제 엔진 백업 안에는 링크를 직접 묻는 반쪽 검사가 없다 — `fslink.is_link` 하나를 쓴다")
        shared = ast.parse(FSLINK_SOURCE.read_text(encoding="utf-8"))
        function = next(node for node in ast.walk(shared) if isinstance(node, ast.FunctionDef) and node.name == "is_link")
        inside = {id(node) for node in ast.walk(function)}
        elsewhere = [node.lineno for node in ast.walk(shared) if isinstance(node, ast.Attribute) and node.attr == "is_symlink" and id(node) not in inside]
        self.assertEqual(elsewhere, [], "링크 검사는 `is_link` 하나다")
        self.assertIn("is_symlink", {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)})

    def test_every_place_that_walks_or_deletes_backup_folders_asks_the_one_function(self):
        for name in ("list_backups", "_clear_known", "read_backup", "_verify_folder_files", "make_backup", "_write_staged"):
            with self.subTest(function=name):
                self.assertIn("_is_link", self.called_names(name), f"{name} 이 `_is_link` 를 부르지 않는다")

    def test_the_folder_that_holds_the_backups_is_checked_itself_and_the_prune_uses_the_listing(self):
        roots = [node for node in ast.walk(self.function("list_backups")) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_is_link"
                 and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "folder"]
        self.assertTrue(roots, "list_backups 가 `_is_link(folder)` 로 폴더 자신을 보지 않는다")
        self.assertIn("list_backups", self.called_names("_prune"), "정리는 후보를 목록으로 구한다 — 폴더 자신의 링크 검사를 거친다")

    def test_the_link_check_looks_at_the_name_itself_never_through_it_and_uses_numbers_for_the_windows_tags(self):
        shared = ast.parse(FSLINK_SOURCE.read_text(encoding="utf-8"))
        function = next(node for node in ast.walk(shared) if isinstance(node, ast.FunctionDef) and node.name == "is_link")
        called = {ast.unparse(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)}
        self.assertIn("os.lstat", called)
        self.assertNotIn("os.stat", called)
        self.assertEqual(bk.REPARSE_POINT, 0x400)
        self.assertEqual(bk.LINK_TAGS, {IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT}, "이름을 돌리는 재해석 종류는 심볼릭 링크와 junction·마운트 지점뿐이다")
        for source in (self.tree(), shared):
            used = [node.attr for node in ast.walk(source) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "stat" and node.attr.startswith("IO_REPARSE_TAG_")]
            self.assertEqual(used, [], "윈도에만 있는 stat 이름을 쓰지 않는다 — 숫자로 둔다")

    def test_the_public_names_do_not_grow(self):
        self.assertNotIn("_is_link", bk.__all__)
        self.assertNotIn("is_link", bk.__all__)


if __name__ == "__main__":
    unittest.main()
