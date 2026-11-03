"""글 저장소(`content/store.py`)의 읽기 전용 열기·구조 올리기·복구가 **네트워크 경로(UNC)·확장 경로**에서도 되는가(독립 검증 'a' 2차 낮음 1).

배경: 읽기 전용으로 여는 곳은 `Path.resolve().as_uri() + "?mode=ro"` 로 SQLite 주소를 만들었다. 매핑한 네트워크 드라이브(`Z:\\`)를 `resolve()` 하면 UNC(`\\\\서버\\공유\\…`)가 되는데
`as_uri()` 는 `file://서버/공유/…` 를 내고 SQLite 는 authority(`file://` 바로 뒤)가 비었거나 localhost 가 아니면 `invalid uri authority` 로 거절한다 — 점검(`doctor`)은 UNEXPECTED_ERROR, 올리기(`_migrate`)는 MIGRATION_FAILED
(옛 코드는 보통 경로로 열어 됐다. 데이터는 그대로). 확장 경로(`\\\\?\\C:\\…`)도 authority 가 `?` 가 되어 같다.

고친 방법: `_read_only_uri` 가 UNC 는 `file:////서버/공유/…`(authority 를 비우고 `//서버/공유/…` 를 경로로)로, 확장 경로는 접두사를 걷어 일반 주소로 만든다. 일반 경로의 주소는 예전과 같다.
`mode=ro` 를 그대로 둬서 오래된 저널을 정리하지 못하고 파일을 한 바이트도 바꾸지 않는 읽기 전용 열기의 약속이 그대로다(보통 경로로 열어 `PRAGMA query_only` 를 거는 방법은 연결이 쓰기 가능이라 옛 저널을 되돌려
파일을 바꿀 수 있어 쓰지 않았다).

지키는 것:
  1) 경로 모양마다 만들어지는 주소(일반·한글·공백·UNC·`$` 공유·확장·확장 UNC·POSIX)와, 일반 경로의 주소가 예전(`as_uri()`)과 같다는 것.
  2) SQLite 가 예전 UNC 주소는 `invalid uri authority` 로 거절하고 새 주소는 받아들여 열기를 시도한다(없는 서버라 '열 수 없음' 으로 끝난다) — 네트워크를 쓰지 않는 문법 검사만이 아니다: 진짜 열기 시도까지 가는지 본다.
  3) UNC 로 풀리는 경로의 시뮬레이션(Windows 의 관리 공유는 관리자 권한이 필요해 진짜 UNC 는 시험하지 못한다): 읽기 전용 열기·구조 올리기(사본 만들기·점검 포함)·백업 복구가 모두 새 주소로 SQLite 를 부르고 끝까지 된다 —
     읽기 전용 열기는 파일을 한 바이트도 바꾸지 않는다.
  4) Windows 에서 진짜 확장 경로(`\\\\?\\C:\\…`)로 열 수 있다(예전에는 `invalid uri authority: %3F`).
"""
import hashlib
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path, PureWindowsPath
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from chanceblog_desktop.content import ContentProject  # noqa: E402
from chanceblog_desktop.content import store as store_module  # noqa: E402
from chanceblog_desktop.content.store import SCHEMA_VERSION, Store, _read_only_uri  # noqa: E402
from store_v1 import make_v1_file  # noqa: E402

NOW = "2026-11-02T03:00:00Z"
FAKE_UNC = "\\\\fileserver\\home\\user\\"                 # 매핑한 네트워크 드라이브를 resolve() 하면 나오는 모양
FAKE_URI = "file:////fileserver/home/user/"


def project(project_id):
    return ContentProject.new("주제가 분명한 제목", "본문 첫 문단입니다.\n\n둘째 문단입니다.", project_id=project_id, now=NOW)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolving_to(raw):
    """`Path.resolve()` 가 그 경로(Windows 모양)를 돌려주게 한다."""
    return mock.patch.object(Path, "resolve", lambda self, strict=False: PureWindowsPath(raw))


class UriShapesTest(unittest.TestCase):
    CASES = (
        ("일반 드라이브 경로", "C:\\Users\\x\\chanceblog.db", "file:///C:/Users/x/chanceblog.db?mode=ro"),
        ("한글·공백", "C:\\Users\\x\\내 폴더\\a b.db", "file:///C:/Users/x/%EB%82%B4%20%ED%8F%B4%EB%8D%94/a%20b.db?mode=ro"),
        ("슬래시로 쓴 드라이브 경로", "D:/forward/slash.db", "file:///D:/forward/slash.db?mode=ro"),
        ("소문자 드라이브 글자", "c:\\users\\x\\a.db", "file:///c:/users/x/a.db?mode=ro"),
        ("UNC", FAKE_UNC + "chanceblog.db", FAKE_URI + "chanceblog.db?mode=ro"),
        ("UNC·한글·공백", "\\\\서버\\공유 폴더\\내 데이터\\a b.db", "file:////%EC%84%9C%EB%B2%84/%EA%B3%B5%EC%9C%A0%20%ED%8F%B4%EB%8D%94/%EB%82%B4%20%EB%8D%B0%EC%9D%B4%ED%84%B0/a%20b.db?mode=ro"),
        ("관리 공유($)", "\\\\localhost\\C$\\x\\chanceblog.db", "file:////localhost/C%24/x/chanceblog.db?mode=ro"),
        ("IP 서버", "\\\\192.0.2.1\\share\\chanceblog.db", "file:////192.0.2.1/share/chanceblog.db?mode=ro"),
        ("확장 경로", "\\\\?\\C:\\Users\\x\\a.db", "file:///C:/Users/x/a.db?mode=ro"),
        ("확장 UNC", "\\\\?\\UNC\\srv\\share\\a.db", "file:////srv/share/a.db?mode=ro"),
    )

    def test_each_shape_gets_the_address_sqlite_can_open(self):
        for label, raw, expected in self.CASES:
            with self.subTest(shape=label):
                with resolving_to(raw):
                    self.assertEqual(_read_only_uri("아무 경로"), expected)

    def test_no_address_has_an_authority_sqlite_would_refuse(self):
        for label, raw, _expected in self.CASES:
            with self.subTest(shape=label):
                with resolving_to(raw):
                    uri = _read_only_uri("x")
                self.assertRegex(uri, r"^file:(?:///|////)[^/]", "authority(`file://` 바로 뒤)는 늘 비어 있다")
                self.assertTrue(uri.endswith("?mode=ro"))

    def test_a_local_path_gets_exactly_the_address_it_always_got(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("chanceblog.db", "내 데이터 a#b%c.db"):
                path = Path(tmp) / name
                self.assertEqual(_read_only_uri(path), path.resolve().as_uri() + "?mode=ro", "예전 `as_uri()` 와 같다(일반 경로는 달라지지 않았다)")
            relative = Path(os.path.relpath(Path(tmp) / "x.db")) if os.path.splitdrive(tmp)[0] == os.path.splitdrive(os.getcwd())[0] else None
            if relative is not None:
                self.assertEqual(_read_only_uri(relative), (Path(tmp) / "x.db").resolve().as_uri() + "?mode=ro", "상대 경로도 resolve 한 뒤의 주소다")


class SqliteAcceptsTheNewFormTest(unittest.TestCase):
    """SQLite 의 주소 해석을 진짜로 거친다 — 없는 서버라 열리지는 않지만 '주소가 틀렸다' 와 '열 수 없다' 는 다르다."""

    def attempt(self, uri):
        try:
            sqlite3.connect(uri, uri=True, timeout=1).execute("SELECT 1")
        except sqlite3.Error as error:
            return str(error)
        return "열림"

    def test_the_old_form_is_refused_as_a_bad_address_and_the_new_one_is_a_normal_failure_to_open(self):
        old = PureWindowsPath("\\\\fileserver.invalid\\share\\x.db").as_uri() + "?mode=ro"
        self.assertEqual(old, "file://fileserver.invalid/share/x.db?mode=ro")
        self.assertIn("invalid uri authority", self.attempt(old), "예전 주소는 SQLite 가 주소 자체를 거절한다(이 시험이 의미 있는 이유)")
        with resolving_to("\\\\fileserver.invalid\\share\\x.db"):
            new = _read_only_uri("x")
        self.assertEqual(new, "file:////fileserver.invalid/share/x.db?mode=ro")
        found = self.attempt(new)
        self.assertNotIn("invalid uri authority", found, "새 주소는 SQLite 가 받아들여 열기를 시도한다")
        self.assertIn("unable to open database file", found, "없는 서버라 열 수 없을 뿐이다")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "data" / "chanceblog.db"
        self.path.parent.mkdir(parents=True)
        make_v1_file(self.path, [project(f"p{number}") for number in range(3)], [("p0", "초안 글", NOW)])
        self.real_resolve = Path.resolve
        self.real_connect = sqlite3.connect
        self.seen = []

    def unc_world(self):
        """모든 `Path.resolve()` 가 UNC 를 돌려주고, UNC 주소로 SQLite 를 부르면 같은 이름의 진짜 로컬 파일(self.dir 아래)을 읽기 전용으로 열어 준다 — 서버가 있는 척."""
        base, seen, real_resolve, real_connect = self.dir, self.seen, self.real_resolve, self.real_connect

        def find(name):
            hits = [item for item in base.rglob(name) if item.is_file()]
            return hits[0]

        def fake_resolve(self_, strict=False):
            return PureWindowsPath(FAKE_UNC + real_resolve(self_, strict=strict).name)

        def connect(target, *args, **kwargs):
            if isinstance(target, str) and target.startswith("file:"):
                seen.append(target)
                if not (target.startswith(FAKE_URI) and target.endswith("?mode=ro")):
                    raise sqlite3.OperationalError("invalid uri authority: 이 시험이 기대한 UNC 주소가 아니다 → " + target)
                name = target[len(FAKE_URI):-len("?mode=ro")]
                local = real_resolve(find(re.sub("%([0-9A-Fa-f]{2})", lambda found: chr(int(found.group(1), 16)), name)))
                return real_connect(local.as_uri() + "?mode=ro", *args, **kwargs)
            return real_connect(target, *args, **kwargs)

        patches = (mock.patch.object(Path, "resolve", fake_resolve), mock.patch.object(sqlite3, "connect", connect))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)


class UncSimulationTest(Base):
    def test_a_read_only_open_works_and_changes_nothing(self):
        before = digest(self.path)
        names = sorted(item.name for item in self.path.parent.iterdir())
        self.unc_world()
        with Store.open(self.path, migrate=False) as store:
            self.assertEqual((store.read_only, store.needs_migration, store.schema_version), (True, True, 1))
            self.assertEqual(len(store.list()), 3)
            self.assertEqual(store.check(), [])
        self.assertTrue(self.seen and all(item.startswith(FAKE_URI) for item in self.seen), self.seen)
        self.assertEqual(digest(self.path), before, "한 바이트도 바뀌지 않았다")
        self.assertEqual(sorted(item.name for item in self.path.parent.iterdir()), names, "아무것도 만들지 않았다")

    def test_the_migration_makes_its_copy_checks_it_and_goes_through(self):
        before = digest(self.path)
        self.unc_world()
        with Store.open(self.path) as store:
            self.assertEqual(store.schema_version, SCHEMA_VERSION)
            self.assertEqual(len(store.list()), 3)
            self.assertEqual(store.check(), [])
        copy = self.path.with_name(self.path.name + ".v1.bak")
        self.assertTrue(copy.is_file(), "사본(.v1.bak)을 두었다")
        self.assertEqual(digest(copy) != "", True)
        with closing(sqlite3.connect(str(copy))) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1, "사본은 올리기 전 판이다")
        self.assertNotEqual(digest(self.path), before)
        self.assertTrue(any(item.endswith("a.bak.tmp?mode=ro") or ".bak.tmp?mode=ro" in item for item in self.seen), "사본을 점검하는 읽기도 새 주소를 쓴다: " + str(self.seen))
        self.assertTrue(all(item.startswith(FAKE_URI) for item in self.seen))

    def test_an_identical_copy_left_by_an_earlier_attempt_is_compared_through_the_new_address_and_reused(self):
        """올리기 도중 죽어 사본이 이미 있을 때 — 같은 내용인지 읽는 곳(`_same_content`)도 새 주소를 쓴다(사본을 새로 만들지 않고 그것을 쓴다)."""
        copy = self.path.with_name(self.path.name + ".v1.bak")
        with closing(sqlite3.connect(str(self.path))) as source, closing(sqlite3.connect(str(copy))) as target:
            source.backup(target)
        before = digest(copy)
        self.unc_world()
        with Store.open(self.path) as store:
            self.assertEqual(store.schema_version, SCHEMA_VERSION)
        self.assertEqual(digest(copy), before, "같은 내용이라 그 사본을 그대로 썼다")
        self.assertFalse(self.path.with_name(self.path.name + ".v1.2.bak").exists(), "다른 이름의 사본을 더 만들지 않았다")
        self.assertTrue(any(copy.name in item for item in self.seen), "사본을 읽을 때 새 주소를 썼다: " + str(self.seen))

    def test_a_second_open_that_finds_the_copy_compares_it_through_the_new_address_too(self):
        self.unc_world()
        Store.open(self.path).close()
        count = len(self.seen)
        copy = self.path.with_name(self.path.name + ".v1.bak")
        self.assertTrue(copy.is_file())
        before = digest(copy)
        with Store.open(self.path, migrate=False) as store:                           # 이미 올랐다 — 읽기 전용 열기도 된다
            self.assertEqual((store.needs_migration, len(store.list())), (False, 3))
        self.assertGreater(len(self.seen), count)
        self.assertEqual(digest(copy), before)

    def test_restoring_a_backup_reads_it_through_the_new_address(self):
        with Store.open(self.path) as store:
            backup = store.backup(self.dir / "backups")
        self.unc_world()
        with Store.open(self.path) as store:
            store.delete("p0")
            self.assertEqual(len(store.list()), 2)
            store.restore_from(backup)
            self.assertEqual(len(store.list()), 3)
        self.assertTrue(any(Path(backup).name in item for item in self.seen), self.seen)
        self.assertTrue(all(item.startswith(FAKE_URI) for item in self.seen))

    def test_without_the_simulation_everything_is_as_before(self):
        with Store.open(self.path, migrate=False) as store:
            self.assertEqual((store.needs_migration, len(store.list())), (True, 3))
        with Store.open(self.path) as store:
            self.assertEqual(store.schema_version, SCHEMA_VERSION)


@unittest.skipUnless(os.name == "nt", "확장 경로(`\\\\?\\`)는 Windows 의 것이다")
class ExtendedPathOnWindowsTest(Base):
    """진짜 Windows 확장 경로로 연다 — 예전에는 authority 가 `?` 라 `invalid uri authority: %3F` 로 실패했다(진짜 실행, 시뮬레이션이 아니다)."""

    def test_a_read_only_open_through_an_extended_length_path(self):
        extended = Path("\\\\?\\" + str(self.path.resolve()))
        before = digest(self.path)
        with Store.open(extended, migrate=False) as store:
            self.assertEqual((store.needs_migration, len(store.list())), (True, 3))
        self.assertEqual(digest(self.path), before)

    def test_the_migration_through_an_extended_length_path(self):
        extended = Path("\\\\?\\" + str(self.path.resolve()))
        with Store.open(extended) as store:
            self.assertEqual((store.schema_version, len(store.list())), (SCHEMA_VERSION, 3))
        self.assertTrue(self.path.with_name(self.path.name + ".v1.bak").is_file())


if __name__ == "__main__":
    unittest.main()
