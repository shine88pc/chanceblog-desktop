"""핵심 코드 가져오기(vendor) 시험 — vendor/ 가 원본 그대로이고(해시), 이 파이썬에서 동작하며, 가져오기·확인 스크립트가 어긋남을 잡는다.

지키는 것:
  1) vendor/ 의 파일이 VENDOR.json 에 적힌 해시와 같고, 가져오는 파일 목록(FILES)이 정해진 4개다 — 이 저장소에서 vendor/ 를 고치면 실패한다.
  2) 가져온 코드(검사 gates·비밀 패턴 secret_patterns·console)가 이 저장소에서 import 되고 기본 동작이 맞다.
  3) 가져오기 스크립트는 원본 커밋의 바이트를 그대로 쓰고(줄바꿈 변환 없음), 읽기에 실패하면 아무것도 쓰지 않으며, 확인은 어긋난 곳을 모두 짚는다.
네트워크 없이 돈다(원본은 시험 안에서 만든 임시 git 저장소).
"""
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop import core  # noqa: E402


def load_script():
    spec = importlib.util.spec_from_file_location("sync_core_under_test", ROOT / "scripts" / "sync_core.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SYNC = load_script()
SOURCE_URL = "https://github.com/shine88pc/chanceblog.git"
EXPECTED_FILES = ("pipeline/__init__.py", "pipeline/console.py", "pipeline/gates.py", "pipeline/secret_patterns.py")
CRLF_CONSOLE = b"a = 1\r\nb = '\xed\x95\x9c'\r\n"      # 줄바꿈(CRLF)과 한글이 그대로 와야 한다


PLAIN_PYC = bytes(16) + b"cache"            # 타임스탬프 방식 .pyc 처럼 보이는 표본(머리글 16바이트, flags 0)


def make_link(test, link, target):
    """link 를 target 폴더로 가는 링크로 만든다(Windows 는 정션, 그 밖은 심볼릭 링크). 만들 수 없는 환경이면 시험을 건너뛰고, 끝나면 링크만 지운다."""
    if os.name == "nt":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if made.returncode != 0:
            test.skipTest("이 환경에서는 연결 폴더(junction)를 만들 수 없다")
        test.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
    else:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            test.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        test.addCleanup(lambda: os.path.lexists(link) and os.unlink(link))


class VendoredFilesTest(unittest.TestCase):
    def test_the_vendored_files_match_the_manifest_hashes(self):
        self.assertEqual(SYNC.check(ROOT), [], "vendor/ 를 고치지 말고 chanceblog 에서 고쳐 다시 가져온다(scripts/sync_core.py)")

    def test_the_manifest_names_the_public_repository_a_full_commit_and_exactly_the_allowed_files(self):
        manifest = json.loads((ROOT / "vendor" / "VENDOR.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"], "https://github.com/shine88pc/chanceblog")
        self.assertRegex(manifest["ref"], r"^[0-9a-f]{40}$")
        self.assertEqual(tuple(sorted(manifest["files"])), EXPECTED_FILES)
        self.assertEqual(tuple(sorted(SYNC.FILES)), EXPECTED_FILES)

    def test_git_is_told_not_to_convert_line_endings_inside_vendor(self):
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        self.assertIn("vendor/** -text", [line.strip() for line in rules])

    def test_nothing_else_lives_in_the_vendored_package(self):
        self.assertEqual(sorted(SYNC._managed_files(ROOT / "vendor")), sorted(EXPECTED_FILES))


class VendoredCodeWorksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = core.use_vendored_core()
        from pipeline import console, gates, secret_patterns
        cls.console, cls.gates, cls.secret_patterns = console, gates, secret_patterns

    def test_use_vendored_core_puts_vendor_first_once(self):
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))
        vendor = ROOT / "vendor"
        sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != vendor.resolve()]
        self.assertEqual(Path(core.use_vendored_core()), vendor)
        self.assertEqual(Path(sys.path[0]), vendor)
        once = list(sys.path)
        core.use_vendored_core()
        self.assertEqual(sys.path, once, "두 번 불러도 한 번만 올라간다")
        self.assertEqual(core.vendor_dir(), vendor)
        self.assertTrue(vendor.is_dir())

    def test_the_vendored_modules_come_from_vendor_not_from_somewhere_else(self):
        vendor = (ROOT / "vendor").resolve()
        for module in (self.console, self.gates, self.secret_patterns):
            self.assertIn(vendor, Path(module.__file__).resolve().parents, module.__name__)

    def test_the_secret_scan_finds_a_planted_key_and_never_returns_the_whole_value(self):
        key = "AI" + "za" + "A" * 35
        found = self.secret_patterns.find_secrets(f"설정 = {key}")
        self.assertEqual([label for label, _ in found], ["Google API 키"])
        self.assertNotIn(key, repr(found))
        self.assertEqual(self.secret_patterns.find_secrets("키 없는 평범한 글입니다."), [])

    def test_the_html_sanitizer_drops_scripts_and_event_handlers_but_keeps_basic_markup(self):
        clean, _stats = self.gates.sanitize_html('<p onclick="x()">안녕</p><script>alert(1)</script><h2>소제목</h2>')
        self.assertIn("<p>안녕</p>", clean)
        self.assertIn("<h2>소제목</h2>", clean)
        self.assertNotIn("script", clean)
        self.assertNotIn("onclick", clean)

    def test_the_labeled_post_parser_reads_title_labels_and_body(self):
        parsed = self.gates.parse_labeled_post("제목: 테스트 제목입니다\n라벨: 수면, 생활습관, 수면\n내용:\n<p>본문</p>")
        self.assertEqual(parsed["title"], "테스트 제목입니다")
        self.assertEqual(parsed["labels"], ["수면", "생활습관"])
        self.assertEqual(parsed["content"], "<p>본문</p>")
        with self.assertRaises(self.gates.GateError):
            self.gates.parse_labeled_post("제목: 라벨이 없다\n내용:\n<p>x</p>")

    def test_similarity_is_one_for_the_same_text_and_low_for_different_text(self):
        self.assertEqual(self.gates.similarity("같은 글입니다", "같은 글입니다"), 1.0)
        self.assertLess(self.gates.similarity("아침 루틴으로 몸 깨우기", "전혀 다른 주제의 긴 문장입니다"), 0.5)


def git(source, *args):
    done = subprocess.run(["git", "-c", "core.longpaths=true", "-C", str(source), *args], capture_output=True)
    if done.returncode != 0:
        raise AssertionError(done.stderr.decode("utf-8", "replace"))
    return done.stdout.decode("utf-8").strip()


def commit(source, contents, message="x", merged=True):
    """커밋을 만든다. merged 이면 chanceblog 의 main 에 병합된 것처럼 origin/main 도 그 커밋으로 맞춘다."""
    for rel, data in contents.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git(source, "add", "-A")
    git(source, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
    sha = git(source, "rev-parse", "HEAD")
    if merged:
        git(source, "update-ref", "refs/remotes/origin/main", sha)
    return sha


def make_source(path, contents=None, origin=SOURCE_URL):
    """임시 git 저장소를 만들고 (경로, 커밋 SHA) 를 돌려준다. 기본 내용은 가져오는 파일 4개 + 가져오지 않는 파일 1개."""
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "core.autocrlf", "false")
    if origin:
        git(path, "remote", "add", "origin", origin)
    if contents is None:
        contents = {rel: f"# {rel}\nvalue = {index}\n".encode("utf-8") for index, rel in enumerate(SYNC.FILES)}
        contents["pipeline/console.py"] = CRLF_CONSOLE
        contents["pipeline/not_vendored.py"] = b"ignored = True\n"
    return path, commit(path, contents)


@unittest.skipUnless(shutil.which("git"), "git 이 필요하다(GIT_NOT_INSTALLED 상황)")
class SyncMechanicsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shared = tempfile.TemporaryDirectory()
        cls.addClassCleanup(shared.cleanup)
        cls.shared = Path(shared.name)
        cls.source, cls.sha = make_source(cls.shared / "source")          # 읽기만 한다
        cls.synced = cls.shared / "synced"                                  # 가져온 뒤의 정상 사본(읽기만 한다)
        cls.synced.mkdir()
        SYNC.sync(cls.source, "HEAD", cls.synced)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.dest = self.tmp / "dest"

    def fresh_copy(self):
        shutil.copytree(self.synced, self.dest)
        return self.dest

    def test_sync_copies_only_the_allowed_files_byte_for_byte_and_records_the_commit(self):
        root = self.synced
        self.assertEqual(SYNC.check(root), [])
        vendored = sorted(path.relative_to(root / "vendor").as_posix() for path in (root / "vendor").rglob("*") if path.is_file())
        self.assertEqual(vendored, sorted(list(SYNC.FILES) + ["VENDOR.json"]))
        self.assertEqual((root / "vendor" / "pipeline" / "console.py").read_bytes(), CRLF_CONSOLE)
        manifest = json.loads((root / "vendor" / "VENDOR.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["ref"], self.sha)
        self.assertEqual(manifest["files"]["pipeline/console.py"], SYNC.sha256(CRLF_CONSOLE))

    def test_running_it_again_picks_up_a_new_commit_and_drops_files_no_longer_managed(self):
        source = self.tmp / "source2"
        shutil.copytree(self.source, source)
        root = self.fresh_copy()
        (root / "vendor" / "pipeline" / "old_module.py").write_text("x = 1\n", encoding="utf-8")
        second = commit(source, {"pipeline/gates.py": b"# changed\n"}, "second")
        self.assertNotEqual(self.sha, second)
        SYNC.sync(source, "HEAD", root)
        self.assertEqual(SYNC.check(root), [])
        self.assertFalse((root / "vendor" / "pipeline" / "old_module.py").exists())
        self.assertEqual((root / "vendor" / "pipeline" / "gates.py").read_bytes(), b"# changed\n")
        self.assertEqual(json.loads((root / "vendor" / "VENDOR.json").read_text(encoding="utf-8"))["ref"], second)

    def test_a_ref_can_be_a_tag_and_is_recorded_as_a_full_sha(self):
        source = self.tmp / "source3"
        shutil.copytree(self.source, source)
        git(source, "tag", "v-test")
        self.assertEqual(SYNC.sync(source, "v-test", self.dest), self.sha)
        self.assertEqual(SYNC.check(self.dest), [])

    def test_a_file_missing_from_the_source_commit_fails_before_anything_is_written(self):
        contents = {rel: b"x = 1\n" for rel in SYNC.FILES if rel != "pipeline/gates.py"}
        source, _sha = make_source(self.tmp / "source4", contents)
        with self.assertRaises(RuntimeError):
            SYNC.sync(source, "HEAD", self.dest)
        self.assertFalse(self.dest.exists(), "읽기에 실패하면 아무것도 쓰지 않는다")

    def test_an_unknown_ref_fails(self):
        with self.assertRaises(RuntimeError):
            SYNC.sync(self.source, "no-such-ref", self.dest)
        self.assertFalse(self.dest.exists())

    def test_a_source_folder_whose_origin_is_not_chanceblog_is_refused_and_nothing_is_written(self):
        secret = "gh" + "p_" + "q" * 36
        for index, origin in enumerate(("https://github.com/someone-else/chanceblog.git", "https://evil.example/shine88pc/chanceblog.git",
                                        "https://github.com/shine88pc/chanceblog-desktop.git", f"https://user:{secret}@github.com/other/x.git", None,
                                        "https://githubXcom/shine88pc/chanceblog.git", "https://g\u0131thub.com/shine88pc/chanceblog.git",
                                        "https://github.com/shine88pc/chanceblog.git.evil")):
            with self.subTest(origin=str(origin)[:40]):
                source, _sha = make_source(self.tmp / f"origin{index}", origin=origin)
                with self.assertRaises(RuntimeError) as caught:
                    SYNC.sync(source, "HEAD", self.dest)
                self.assertIn("origin", str(caught.exception))
                self.assertNotIn(secret, str(caught.exception), "주소 속 로그인 정보는 메시지에도 나가지 않는다")
                self.assertFalse(self.dest.exists())

    def test_a_second_origin_address_pointing_elsewhere_is_refused_too(self):
        source, _sha = make_source(self.tmp / "two-origins")
        git(source, "remote", "set-url", "--add", "origin", "https://evil.example/shine88pc/chanceblog.git")
        with self.assertRaises(RuntimeError):
            SYNC.sync(source, "HEAD", self.dest)
        self.assertFalse(self.dest.exists())

    def test_the_usual_chanceblog_addresses_are_accepted_as_the_source_origin(self):
        for index, origin in enumerate(("https://github.com/shine88pc/chanceblog", "git@github.com:shine88pc/chanceblog.git", "ssh://git@github.com/shine88pc/chanceblog.git",
                                        "https://someone@github.com/shine88pc/chanceblog.git")):
            with self.subTest(origin=origin):
                source, sha = make_source(self.tmp / f"ok{index}", origin=origin)
                self.assertEqual(SYNC.sync(source, "HEAD", self.tmp / f"dest{index}"), sha)

    def test_a_commit_that_is_not_merged_into_origin_main_is_refused(self):
        source = self.tmp / "unmerged"
        shutil.copytree(self.source, source)
        second = commit(source, {"pipeline/gates.py": b"# not merged\n"}, "second", merged=False)
        with self.assertRaises(RuntimeError) as caught:
            SYNC.sync(source, second, self.dest)
        self.assertIn("병합", str(caught.exception))
        self.assertFalse(self.dest.exists())
        self.assertEqual(SYNC.sync(source, self.sha, self.dest), self.sha, "병합된 이전 커밋은 가져올 수 있다")

    def test_a_link_a_submodule_or_a_folder_in_place_of_a_file_is_refused(self):
        def object_id(source, data):
            done = subprocess.run(["git", "-C", str(source), "hash-object", "-w", "--stdin"], input=data, capture_output=True)
            return done.stdout.decode("ascii").strip()

        for index, (mode, data) in enumerate((("120000", b"../elsewhere"), ("160000", None))):
            with self.subTest(mode=mode):
                source, _sha = make_source(self.tmp / f"special{index}")
                target = object_id(source, data) if data is not None else "1" * 40
                git(source, "update-index", "--add", "--cacheinfo", f"{mode},{target},pipeline/gates.py")
                git(source, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "special")
                git(source, "update-ref", "refs/remotes/origin/main", "HEAD")
                with self.assertRaises(RuntimeError) as caught:
                    SYNC.sync(source, "HEAD", self.tmp / f"d{index}")
                self.assertIn("일반 파일이 아니다", str(caught.exception))
                self.assertFalse((self.tmp / f"d{index}").exists())
        contents = {rel: b"x = 1\n" for rel in SYNC.FILES if rel != "pipeline/gates.py"}
        contents["pipeline/gates.py/inner.py"] = b"x = 2\n"                       # gates.py 가 파일이 아니라 폴더
        folder_source, _sha = make_source(self.tmp / "folder", contents)
        with self.assertRaises(RuntimeError) as caught:
            SYNC.sync(folder_source, "HEAD", self.dest)
        self.assertIn("일반 파일이 아니다", str(caught.exception))
        self.assertFalse(self.dest.exists())

    def test_an_executable_file_is_fine_and_a_git_environment_variable_cannot_redirect_the_source(self):
        source, sha = make_source(self.tmp / "exec")
        git(source, "update-index", "--chmod=+x", "pipeline/gates.py")
        git(source, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "exec")
        git(source, "update-ref", "refs/remotes/origin/main", "HEAD")
        other = self.tmp / "other-repo"
        other.mkdir()
        git(other, "init", "-q")
        old = os.environ.get("GIT_DIR")
        os.environ["GIT_DIR"] = str(other / ".git")
        try:
            commit_sha = SYNC.sync(source, "HEAD", self.dest)
        finally:
            if old is None:
                os.environ.pop("GIT_DIR", None)
            else:
                os.environ["GIT_DIR"] = old
        self.assertEqual(commit_sha, git(source, "rev-parse", "HEAD"))
        self.assertEqual(SYNC.check(self.dest), [])

    def test_any_compiled_cache_file_in_vendor_is_a_stray_whatever_kind_it_is(self):
        """PEP 552: 소스를 보지 않고 실행되는 해시 기반 .pyc 는 물론, 소스와 수정 시각·크기만 맞춰 만든 타임스탬프 방식 .pyc 도 파이썬이 소스 대신 실행한다 — 모두 어긋남이다."""
        import py_compile
        root = self.fresh_copy()
        pipeline = root / "vendor" / "pipeline"
        cache = pipeline / "__pycache__"
        cache.mkdir(exist_ok=True)
        self.assertEqual(SYNC.check(root), [])
        for mode in (py_compile.PycInvalidationMode.TIMESTAMP, py_compile.PycInvalidationMode.UNCHECKED_HASH, py_compile.PycInvalidationMode.CHECKED_HASH):
            with self.subTest(mode=mode.name):
                bad = cache / "gates.cpython-310.pyc"
                py_compile.compile(str(pipeline / "gates.py"), cfile=str(bad), doraise=True, invalidation_mode=mode)
                problems = SYNC.check(root)
                self.assertTrue(any("gates.cpython-310.pyc" in problem and "컴파일 캐시" in problem for problem in problems), problems)
                bad.unlink()
                self.assertEqual(SYNC.check(root), [])
        broken = cache / "x.cpython-310.pyc"
        broken.write_bytes(b"abc")
        self.assertTrue(any("x.cpython-310.pyc" in problem for problem in SYNC.check(root)), "머리글이 모자란 .pyc")

    def test_sync_removes_compiled_caches_from_vendor(self):
        root = self.fresh_copy()
        cache = root / "vendor" / "pipeline" / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "gates.cpython-310.pyc").write_bytes(PLAIN_PYC)
        self.assertTrue(SYNC.check(root))
        SYNC.sync(self.source, "HEAD", root)
        self.assertFalse((cache / "gates.cpython-310.pyc").exists())
        self.assertEqual(SYNC.check(root), [])

    def test_a_vendored_file_that_is_a_link_or_a_hard_link_is_reported_and_never_written_through(self):
        """목록에 있는 파일 자리에 링크가 있으면 가져오기가 링크 너머(vendor/ 밖)의 파일을 덮어쓴다(3차 검토 M5) — 쓰기 전에 멈추고, check 가 알린다."""
        for rel in ("pipeline/gates.py", "VENDOR.json"):
            for kind in ("hard", "symbolic"):
                with self.subTest(rel=rel, kind=kind):
                    root = self.tmp / f"{kind}-{rel.replace('/', '-')}"
                    shutil.copytree(self.synced, root)
                    target = root / "vendor" / rel
                    outside = self.tmp / f"outside-{kind}-{rel.replace('/', '-')}"
                    outside.write_bytes(target.read_bytes())
                    target.unlink()
                    try:
                        os.link(outside, target) if kind == "hard" else os.symlink(outside, target)
                    except (OSError, NotImplementedError):
                        self.skipTest(f"이 환경에서는 {kind} 링크를 만들 수 없다")
                    if rel != "VENDOR.json":
                        problems = SYNC.check(root)
                        self.assertTrue(any(rel in problem and "링크" in problem for problem in problems), problems)
                    before = outside.read_bytes()
                    with self.assertRaises(RuntimeError) as caught:
                        SYNC.sync(self.source, "HEAD", root)
                    self.assertIn("링크", str(caught.exception))
                    self.assertEqual(outside.read_bytes(), before, "링크 너머의 파일이 덮어써졌다")

    def test_a_failure_while_replacing_a_file_keeps_the_old_file_and_leaves_no_temporary_file(self):
        root = self.fresh_copy()
        gates = root / "vendor" / "pipeline" / "gates.py"
        before = gates.read_bytes()
        source = self.tmp / "source-changed"
        shutil.copytree(self.source, source)
        commit(source, {"pipeline/gates.py": b"# new content\n"}, "changed")
        with mock.patch.object(SYNC.os, "replace", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                SYNC.sync(source, "HEAD", root)
        self.assertEqual(gates.read_bytes(), before, "바꿔 넣기가 실패하면 옛 파일이 반쯤 써진 채 남지 않는다")
        self.assertEqual([path.name for path in gates.parent.iterdir() if path.name.endswith(".sync-tmp")], [], "임시 파일이 남았다")

    def test_a_target_that_cannot_be_changed_stops_the_import_before_any_file_is_replaced(self):
        root = self.fresh_copy()
        vendor = root / "vendor"
        source = self.tmp / "source-changed-two"
        shutil.copytree(self.source, source)
        commit(source, {"pipeline/gates.py": b"# new gates\n", "pipeline/console.py": b"# new console\n"}, "changed")
        locked = vendor / "pipeline" / "console.py"
        locked.chmod(stat.S_IREAD)
        self.addCleanup(lambda: locked.chmod(stat.S_IWRITE | stat.S_IREAD))
        if os.access(locked, os.W_OK):
            self.skipTest("이 환경에서는 읽기 전용 표시가 쓰기를 막지 않는다(관리자 권한 등)")
        before = {path.name: path.read_bytes() for path in (vendor / "pipeline").glob("*.py")}
        manifest = (vendor / "VENDOR.json").read_bytes()
        with self.assertRaises(RuntimeError) as caught:
            SYNC.sync(source, "HEAD", root)
        self.assertIn("console.py", str(caught.exception))
        self.assertEqual({path.name: path.read_bytes() for path in (vendor / "pipeline").glob("*.py")}, before, "파일 하나 때문에 일부만 갱신됐다")
        self.assertEqual((vendor / "VENDOR.json").read_bytes(), manifest)
        self.assertEqual([path.name for path in vendor.rglob("*.sync-tmp")], [])

    def test_a_failure_in_the_middle_of_replacing_is_reported_in_one_line_by_the_command_line(self):
        root = self.fresh_copy()
        with mock.patch.object(SYNC, "sync", side_effect=PermissionError(13, "Permission denied", "x")):
            with mock.patch.object(sys, "stderr", io.StringIO()) as err:
                self.assertEqual(SYNC.main(["--source", str(self.source), "--ref", "HEAD"]), 1)
        self.assertIn("Permission denied", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_the_files_are_replaced_not_written_in_place_so_a_stale_temporary_file_never_stays(self):
        root = self.fresh_copy()
        vendor = root / "vendor"
        (vendor / "pipeline" / "gates.py.sync-tmp").write_bytes(b"old leftover")
        SYNC.sync(self.source, "HEAD", root)
        self.assertEqual(sorted(path.name for path in vendor.rglob("*") if path.is_file()), sorted([Path(rel).name for rel in SYNC.FILES] + ["VENDOR.json"]))

    def test_a_link_or_junction_inside_vendor_is_reported_and_never_followed_and_sync_refuses_before_writing(self):
        root = self.fresh_copy()
        vendor = root / "vendor"
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "json.py").write_text("x = 1\n", encoding="utf-8")
        (outside / "precious.txt").write_text("지키는 파일\n", encoding="utf-8")
        make_link(self, vendor / "junc", outside)
        problems = SYNC.check(root)
        self.assertTrue(any("junc" in problem and "링크" in problem for problem in problems), problems)
        self.assertFalse(any("precious" in problem or "json.py" in problem for problem in problems), "링크 안으로 들어가 세지 않는다")
        before = (vendor / "pipeline" / "gates.py").read_bytes()
        with self.assertRaises(RuntimeError) as caught:
            SYNC.sync(self.source, "HEAD", root)
        self.assertIn("링크", str(caught.exception))
        self.assertEqual(sorted(path.name for path in outside.iterdir()), ["json.py", "precious.txt"], "링크 너머의 파일은 하나도 지워지지 않았다")
        self.assertEqual((vendor / "pipeline" / "gates.py").read_bytes(), before, "아무것도 쓰기 전에 멈춘다")

    def test_vendor_pipeline_as_a_link_to_another_folder_is_refused_before_anything_is_written_through_it(self):
        """개발 편의로 vendor/pipeline 을 chanceblog 의 pipeline 폴더로 정션을 걸어 둔 경우 — 가져오기가 그 폴더에 쓰지 않는다."""
        root = self.fresh_copy()
        vendor = root / "vendor"
        real = self.tmp / "other-pipeline"
        shutil.copytree(vendor / "pipeline", real)
        shutil.rmtree(vendor / "pipeline")
        make_link(self, vendor / "pipeline", real)
        snapshot = {path.name: path.read_bytes() for path in real.iterdir() if path.is_file()}
        with self.assertRaises(RuntimeError):
            SYNC.sync(self.source, "HEAD", root)
        self.assertEqual({path.name: path.read_bytes() for path in real.iterdir() if path.is_file()}, snapshot)
        self.assertTrue(any("pipeline" in problem for problem in SYNC.check(root)))

    def test_vendor_itself_being_a_link_is_refused(self):
        root = self.fresh_copy()
        moved = self.tmp / "moved-vendor"
        shutil.move(str(root / "vendor"), str(moved))
        make_link(self, root / "vendor", moved)
        self.assertTrue(any("링크" in problem for problem in SYNC.check(root)))
        with self.assertRaises(RuntimeError):
            SYNC.sync(self.source, "HEAD", root)

    def test_check_reports_every_kind_of_drift(self):
        root = self.fresh_copy()
        vendor = root / "vendor"
        self.assertEqual(SYNC.check(root), [])
        gates = vendor / "pipeline" / "gates.py"
        original = gates.read_bytes()
        gates.write_bytes(original + b"# edited here\n")
        self.assertTrue(any("gates.py" in problem and "해시" in problem for problem in SYNC.check(root)))
        gates.write_bytes(original)
        gates.unlink()
        self.assertTrue(any("gates.py" in problem and "없다" in problem for problem in SYNC.check(root)))
        gates.write_bytes(original)
        (vendor / "pipeline" / "extra.py").write_text("x = 1\n", encoding="utf-8")
        self.assertTrue(any("extra.py" in problem for problem in SYNC.check(root)))
        (vendor / "pipeline" / "extra.py").unlink()
        self.assertEqual(SYNC.check(root), [])

    def test_check_reports_stray_files_anywhere_in_vendor_including_compiled_caches(self):
        """vendor/ 는 import 경로 맨 앞이라, 어느 자리의 파일이든(표준 모듈을 가리는 json.py·sitecustomize.py·소스 없는 .pyc) 앱이 불러올 수 있다."""
        root = self.fresh_copy()
        vendor = root / "vendor"
        for rel in ("json.py", "sitecustomize.py", "extra.pth", "pipeline/hidden.pyc", "pipeline/sub/deep.py", "other/pkg/__init__.py", "pipeline/__pycache__/notcode.py", "README.md"):
            with self.subTest(rel=rel):
                path = vendor / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(PLAIN_PYC if (rel.endswith(".pyc") or "__pycache__" in rel) else b"x = 1\n")        # 캐시 폴더 밖의 .pyc, 그리고 .pyc 가 아닌 파일은 내용이 평범한 캐시처럼 보여도 목록 밖 파일이다
                self.assertTrue(any(rel in problem for problem in SYNC.check(root)), rel)
                path.unlink()
                self.assertEqual(SYNC.check(root), [], "지우면 다시 정상")
        for cache in (vendor / "__pycache__", vendor / "pipeline" / "__pycache__"):
            cache.mkdir(exist_ok=True)
            (cache / "x.cpython-310.pyc").write_bytes(PLAIN_PYC)
        self.assertEqual(sum("x.cpython-310.pyc" in problem for problem in SYNC.check(root)), 2, "어느 캐시 폴더의 .pyc 든 어긋남이다")

    def test_check_does_not_crash_on_a_manifest_of_the_wrong_shape(self):
        for index, text in enumerate(("[]", "null", '"x"', "5", '{"files": [], "ref": 5, "source": 7}')):
            with self.subTest(text=text):
                work = self.tmp / f"shape{index}"
                shutil.copytree(self.synced, work)
                (work / "vendor" / "VENDOR.json").write_text(text, encoding="utf-8")
                self.assertTrue(SYNC.check(work))

    def test_check_reports_a_bad_manifest(self):
        cases = {
            "출처가 다름": lambda m: m.update(source="https://example.com/other"),
            "짧은 SHA": lambda m: m.update(ref="a5af962"),
            "SHA 끝에 줄바꿈": lambda m: m.update(ref=m["ref"] + "\n"),
            "SHA 가 글이 아님": lambda m: m.update(ref=12345),
            "해시가 글이 아님": lambda m: m["files"].update({"pipeline/console.py": 5}),
            "해시 모양이 아님": lambda m: m["files"].update({"pipeline/console.py": "ABC"}),
            "해시를 고침": lambda m: m["files"].update({"pipeline/console.py": "0" * 64}),
            "파일 목록이 다름": lambda m: m["files"].pop("pipeline/console.py"),
            "파일 목록이 없음": lambda m: m.pop("files"),
        }
        for index, (name, change) in enumerate(cases.items()):
            with self.subTest(name):
                work = self.tmp / f"case{index}"
                shutil.copytree(self.synced, work)
                path = work / "vendor" / "VENDOR.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                change(manifest)
                path.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertTrue(SYNC.check(work), name)

    def test_check_reports_a_missing_or_broken_manifest(self):
        root = self.fresh_copy()
        manifest = root / "vendor" / "VENDOR.json"
        manifest.write_text("{ not json", encoding="utf-8")
        self.assertTrue(any("읽을 수 없다" in problem for problem in SYNC.check(root)))
        manifest.unlink()
        self.assertTrue(any("없다" in problem for problem in SYNC.check(root)))
        self.assertTrue(SYNC.check(self.tmp / "empty"))


class ImportPathTest(unittest.TestCase):
    """같은 이름(`pipeline`)의 다른 코드가 가져온 코드를 가리지 못하게 — 새 파이썬 프로세스에서 실제로 import 해 본다."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fake = Path(tmp.name) / "fake"
        (self.fake / "pipeline").mkdir(parents=True)
        (self.fake / "pipeline" / "__init__.py").write_text("IMPOSTOR = True\n", encoding="utf-8")
        self.vendor = ROOT / "vendor"

    def run_python(self, lines, env=None):
        env_all = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        env_all.update(env or {})
        env = env_all
        env["PYTHONUTF8"] = "1"
        return subprocess.run([sys.executable, "-X", "utf8", "-c", "\n".join(lines)], capture_output=True, text=True, encoding="utf-8", env=env)

    def test_vendor_already_on_the_path_but_not_first_is_moved_to_the_front(self):
        done = self.run_python([
            "import sys",
            f"sys.path.insert(0, {str(ROOT / 'src')!r})",
            f"sys.path.append({str(self.vendor)!r})",
            f"sys.path.insert(0, {str(self.fake)!r})",
            "from chanceblog_desktop import core",
            "core.use_vendored_core()",
            "import pipeline",
            "print(pipeline.__file__)",
        ])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(self.vendor.resolve(), Path(done.stdout.strip()).resolve().parents)

    def test_a_same_named_package_that_is_already_imported_stops_the_app_instead_of_running_other_code(self):
        done = self.run_python([
            "import sys",
            f"sys.path.insert(0, {str(ROOT / 'src')!r})",
            f"sys.path.insert(0, {str(self.fake)!r})",
            "import pipeline",
            "assert hasattr(pipeline, 'IMPOSTOR')",
            "from chanceblog_desktop import core",
            "try:",
            "    core.use_vendored_core()",
            "except RuntimeError as error:",
            "    print('STOPPED')",
        ])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "STOPPED")

    def test_a_same_named_namespace_package_that_is_already_imported_also_stops_the_app(self):
        (self.fake / "pipeline" / "__init__.py").unlink()                   # __init__ 이 없으면 네임스페이스 패키지(__file__ 이 없다)
        done = self.run_python([
            "import sys",
            f"sys.path.insert(0, {str(ROOT / 'src')!r})",
            f"sys.path.insert(0, {str(self.fake)!r})",
            "import pipeline",
            "assert getattr(pipeline, '__file__', None) is None",
            "from chanceblog_desktop import core",
            "try:",
            "    core.use_vendored_core()",
            "except RuntimeError:",
            "    print('STOPPED')",
        ])
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "STOPPED"), done.stderr)

    def make_copy_of_the_loader(self):
        """core.py 와 가짜 vendor/pipeline 을 임시 폴더에 놓는다 — vendor_dir() 이 그 가짜를 가리키게(진짜 vendor/ 를 건드리지 않고 시험한다)."""
        root = self.fake.parent / "app"
        (root / "src" / "chanceblog_desktop").mkdir(parents=True)
        for name in ("__init__.py", "core.py"):
            shutil.copy2(ROOT / "src" / "chanceblog_desktop" / name, root / "src" / "chanceblog_desktop" / name)
        package = root / "vendor" / "pipeline"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('VALUE = "real"\n', encoding="utf-8")
        return root, package / "__init__.py"

    def plant_a_cache(self, source):
        """소스의 수정 시각·크기를 그대로 머리글에 적고 다른 코드를 담은 타임스탬프 방식 .pyc 를 소스 옆 __pycache__ 에 둔다."""
        import importlib.util
        import marshal
        import struct
        stat = source.stat()
        code = compile('VALUE = "evil"\n', str(source), "exec")
        data = importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, int(stat.st_mtime) & 0xFFFFFFFF, stat.st_size & 0xFFFFFFFF) + marshal.dumps(code)
        cache = source.parent / "__pycache__" / f"{source.stem}.{sys.implementation.cache_tag}.pyc"        # 이 시험 프로세스가 이미 캐시 폴더를 돌려 놓았을 수 있어 cache_from_source 는 쓰지 않는다
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
        return cache

    def test_a_cache_planted_next_to_the_vendored_source_is_not_run_in_place_of_it(self):
        root, source = self.make_copy_of_the_loader()
        cache = self.plant_a_cache(source)
        control = self.run_python(["import sys", f"sys.path.insert(0, {str(root / 'vendor')!r})", "import pipeline", "print(pipeline.VALUE)"])
        self.assertEqual(control.stdout.strip(), "evil", "시험 준비 확인: 심어 둔 캐시가 정말 소스 대신 실행되는 모양이어야 이 시험이 뜻이 있다")
        done = self.run_python(["import sys", f"sys.path.insert(0, {str(root / 'src')!r})", "from chanceblog_desktop import core", "core.use_vendored_core()", "import pipeline", "print(pipeline.VALUE)"])
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "real"), done.stderr)
        self.assertTrue(cache.is_file(), "심어 둔 캐시를 앱이 지우지는 않는다(점검이 알린다)")

    def test_the_compiled_cache_goes_outside_vendor_and_the_users_own_choice_is_kept(self):
        root, _source = self.make_copy_of_the_loader()
        home = self.fake.parent / "home"
        longest = len(str(home / "ChanceblogDesktop" / "pycache")) + len(str(root / "vendor" / "pipeline" / "__pycache__" / "secret_patterns.cpython-312.pyc"))
        if os.name == "nt" and longest > 255:
            self.skipTest("시험 폴더 이름이 길어 컴파일 캐시 경로가 Windows 경로 한도(260자)를 넘는다")
        run = ["import sys", f"sys.path.insert(0, {str(root / 'src')!r})", "from chanceblog_desktop import core", "core.use_vendored_core()", "import pipeline", "print(sys.pycache_prefix)"]
        env_local = {"LOCALAPPDATA": str(home), "PYTHONPYCACHEPREFIX": "", "PYTHONDONTWRITEBYTECODE": ""}      # 캐시를 쓰도록(이 시험 환경이 끄고 있어도)
        done = self.run_python(run, env=env_local)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(Path(done.stdout.strip()), home / "ChanceblogDesktop" / "pycache")
        self.assertFalse((root / "vendor" / "pipeline" / "__pycache__").exists(), "vendor/ 안에는 캐시가 생기지 않는다")
        self.assertTrue(any((home / "ChanceblogDesktop" / "pycache").rglob("*.pyc")), "캐시는 사용자 폴더에 만들어진다")
        mine = self.fake.parent / "mine"
        kept = self.run_python(run, env={"LOCALAPPDATA": str(home), "PYTHONPYCACHEPREFIX": str(mine), "PYTHONDONTWRITEBYTECODE": ""})
        self.assertEqual(Path(kept.stdout.strip()), mine, "사용자가 정한 캐시 폴더는 바꾸지 않는다")

    def test_the_vendored_package_itself_being_imported_is_fine_to_ask_again(self):
        done = self.run_python([
            "import sys",
            f"sys.path.insert(0, {str(ROOT / 'src')!r})",
            "from chanceblog_desktop import core",
            "core.use_vendored_core()",
            "import pipeline",
            "core.use_vendored_core()",
            "print('FINE')",
        ])
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "FINE"), done.stderr)


class CommandLineTest(unittest.TestCase):
    def run_script(self, *args):
        env = dict(os.environ, PYTHONUTF8="1")
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "sync_core.py"), *args], capture_output=True, text=True, encoding="utf-8", env=env)

    def test_check_passes_on_the_repository(self):
        done = self.run_script("--check")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_syncing_without_a_source_and_ref_is_a_usage_error(self):
        done = self.run_script()
        self.assertEqual(done.returncode, 2)
        self.assertIn("--source", done.stderr)

    @unittest.skipUnless(shutil.which("git"), "git 이 필요하다(GIT_NOT_INSTALLED 상황)")
    def test_a_missing_source_folder_fails_with_a_message_and_no_traceback(self):
        done = self.run_script("--source", str(ROOT / "no-such-folder"), "--ref", "main")
        self.assertEqual(done.returncode, 1)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
