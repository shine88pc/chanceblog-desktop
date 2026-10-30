"""핵심 코드 가져오기(vendor) 시험 — vendor/ 가 원본 그대로이고(해시), 이 파이썬에서 동작하며, 가져오기·확인 스크립트가 어긋남을 잡는다.

지키는 것:
  1) vendor/ 의 파일이 VENDOR.json 에 적힌 해시와 같고, 가져오는 파일 목록(FILES)이 정해진 4개다 — 이 저장소에서 vendor/ 를 고치면 실패한다.
  2) 가져온 코드(검사 gates·비밀 패턴 secret_patterns·console)가 이 저장소에서 import 되고 기본 동작이 맞다.
  3) 가져오기 스크립트는 원본 커밋의 바이트를 그대로 쓰고(줄바꿈 변환 없음), 읽기에 실패하면 아무것도 쓰지 않으며, 확인은 어긋난 곳을 모두 짚는다.
네트워크 없이 돈다(원본은 시험 안에서 만든 임시 git 저장소).
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
EXPECTED_FILES = ("pipeline/__init__.py", "pipeline/console.py", "pipeline/gates.py", "pipeline/secret_patterns.py")
CRLF_CONSOLE = b"a = 1\r\nb = '\xed\x95\x9c'\r\n"      # 줄바꿈(CRLF)과 한글이 그대로 와야 한다


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
    done = subprocess.run(["git", "-C", str(source), *args], capture_output=True)
    if done.returncode != 0:
        raise AssertionError(done.stderr.decode("utf-8", "replace"))
    return done.stdout.decode("utf-8").strip()


def commit(source, contents, message="x"):
    for rel, data in contents.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git(source, "add", "-A")
    git(source, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
    return git(source, "rev-parse", "HEAD")


def make_source(path, contents=None):
    """임시 git 저장소를 만들고 (경로, 커밋 SHA) 를 돌려준다. 기본 내용은 가져오는 파일 4개 + 가져오지 않는 파일 1개."""
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "core.autocrlf", "false")
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

    def test_check_reports_every_kind_of_drift(self):
        root = self.fresh_copy()
        vendor = root / "vendor"
        self.assertEqual(SYNC.check(root), [])
        (vendor / "pipeline" / "__pycache__").mkdir()
        (vendor / "pipeline" / "__pycache__" / "gates.cpython-312.pyc").write_bytes(b"cache")
        self.assertEqual(SYNC.check(root), [], "캐시 파일은 어긋남이 아니다")

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

    def test_check_reports_a_bad_manifest(self):
        cases = {
            "출처가 다름": lambda m: m.update(source="https://example.com/other"),
            "짧은 SHA": lambda m: m.update(ref="a5af962"),
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
