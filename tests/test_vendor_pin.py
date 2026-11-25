"""vendor/ 총 요약값(`PINNED_DIGEST`)·앱 시작 확인 시험 — AS-S2 권고-6(결정 D-692).

틈(감사 공급망 탐침 3·4·6단계): `vendor/VENDOR.json` 의 해시는 같은 폴더의 파일과만 견주는 '자기 일관성'이라 `gates.py` 를 고치고 목록의 해시도 다시 계산해 넣으면 `sync_core.check` 가 [] 로 통과하고(시험도 통과),
`ref` 를 아무 40자리로 바꿔도 통과하며, 설치본의 자가 점검(`--selftest`)은 목록 밖 `json.py` 가 있어도 `ok` 였다 — 설치본은 열 때 vendor 를 아예 확인하지 않는다.
고침: 소스(`src/chanceblog_desktop/vendor_pin.py`)에 총 요약값 한 개를 고정하고(`sync_core.py` 가 가져올 때만 바꾼다) CI 확인·자가 점검·앱 시작이 같은 값으로 견준다(자기참조의 높이를 한 단 올림 —
완전한 해결인 '원본 저장소의 같은 커밋과 대조하는 CI' 는 새 외부 접속이라 T3 제안으로 남긴다).

지키는 것:
  1) 진짜 저장소는 정상이다 — 실제 파일에서 다시 센 값과 고정값이 같고, 앱 시작 확인은 조용하고 몇 ms 안에 끝난다. 값을 만드는 방법(`total_digest`)은 독립 계산과 같고 이름·해시·커밋 어느 하나가 바뀌어도 값이 달라진다.
  2) 파일과 목록을 **같이** 고친 사본·`ref` 만 바꾼 사본·고정값만 바꾼 사본은 CI 확인(`sync_core.check`)·`problems`·앱 시작·자가 점검(`check_vendor`) 모두에서 거절된다.
  3) 목록 밖 파일(`json.py`·`__pycache__`·링크)은 엄격한 확인(설치본 시작·자가 점검)에서 걸리고 소스 실행의 시작 확인은 건너뛴다. 하드 링크·링크 파일은 어디서나 걸리고, OneDrive 같은 클라우드 자리표시 파일(링크 종류가 아닌 재해석 지점)은 걸리지 않는다.
  4) 가져오기(`sync_core.sync`)가 vendor/ 와 같은 때에 고정값도 다시 쓴다(줄 끝 그대로) — 쓴 뒤 `check` 가 []. 고정값 파일이 없거나 링크인 소스 나무는 아무것도 쓰기 전에 멈춘다.
  5) 앱 시작(`ui/launcher.py`)이 PySide6 확인보다 먼저 이 확인을 하고, 어긋나면 화면을 열지 않고 경로·값 없는 쉬운 한 문장으로 끝낸다(종료 코드 1). 같은 이름의 칸이 두 번 나오는 VENDOR.json(참고 SC-13)도 거절한다.
네트워크·실제 시계 없이 돈다(가져오기 시험의 원본은 시험 안에서 만든 임시 git 저장소).
"""
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import packaging_support as ps  # noqa: E402
import secret_support as sec  # noqa: E402
import test_vendor_core as tvc  # noqa: E402
from chanceblog_desktop import core, vendor_pin as vp  # noqa: E402
from chanceblog_desktop.ui import launcher  # noqa: E402

SYNC = tvc.SYNC
ge = ps.gui_entry
PIN_SOURCE = ROOT / "src" / "chanceblog_desktop" / "vendor_pin.py"
HEX = "0123456789abcdef"
IO_REPARSE_TAG_CLOUD = 0x9000001A


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def expected_digest(ref, files):
    """고정값을 만드는 방법을 이 파일에서 따로 적은 독립 계산 — `vendor_pin.total_digest` 가 몰래 바뀌어도(그리고 값을 다시 계산해 넣어도) 여기서 걸린다."""
    lines = ["ref " + ref] + [f"{name} {files[name]}" for name in sorted(files)]
    return sha256_hex(("\n".join(lines) + "\n").encode("utf-8"))


def make_tree(tmp):
    """vendor/ 와 vendor_pin.py 를 임시 나무로 복사한다(소스 나무가 있어야 `sync_core.check` 가 총 요약값을 견준다)."""
    tree = Path(tmp)
    shutil.copytree(ROOT / "vendor", tree / "vendor", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (tree / "src" / "chanceblog_desktop").mkdir(parents=True)
    shutil.copyfile(PIN_SOURCE, tree / "src" / "chanceblog_desktop" / "vendor_pin.py")
    return tree


def rewrite_manifest(tree, *, ref=None):
    """변조한 쪽이 하는 일 — 파일을 고친 뒤 목록의 해시를 실제 파일에서 다시 계산해 넣는다(`ref` 도 바꿀 수 있다)."""
    vendor = Path(tree) / "vendor"
    manifest = json.loads((vendor / "VENDOR.json").read_text(encoding="utf-8"))
    manifest["files"] = {name: sha256_hex((vendor / name).read_bytes()) for name in manifest["files"]}
    if ref is not None:
        manifest["ref"] = ref
    (vendor / "VENDOR.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fake_core(vendor):
    return types.SimpleNamespace(vendor_dir=lambda: Path(vendor), use_vendored_core=lambda: None)


def fake_lstat(mode=stat.S_IFREG | 0o644, **fields):
    fields.setdefault("st_nlink", 1)
    return types.SimpleNamespace(st_mode=mode, **fields)


class RealRepositoryTest(unittest.TestCase):
    def test_the_real_vendor_passes_every_check_and_the_start_check_is_silent(self):
        self.assertEqual(vp.problems(ROOT / "vendor", strict=True), [])
        for frozen in (True, False):
            with self.subTest(frozen=frozen):
                self.assertIsNone(vp.start_problem(vendor=ROOT / "vendor", frozen=frozen))
        self.assertIsNone(vp.start_problem(), "앱이 쓰는 진짜 vendor 자리(`core.vendor_dir()`)")
        self.assertEqual(SYNC.check(ROOT), [])
        self.assertEqual(ge.check_vendor(ROOT, core).status, "ok")

    def test_the_pin_is_one_line_in_the_source_and_sync_core_reads_the_same_value(self):
        lines = re.findall(r'^PINNED_DIGEST = "([0-9a-f]{64})"', PIN_SOURCE.read_text(encoding="utf-8"), re.M)
        self.assertEqual(lines, [vp.PINNED_DIGEST])
        self.assertEqual(SYNC._load_pin(ROOT).PINNED_DIGEST, vp.PINNED_DIGEST)

    def test_the_pin_equals_an_independent_computation_over_the_real_files(self):
        manifest = json.loads((ROOT / "vendor" / "VENDOR.json").read_text(encoding="utf-8"))
        actual = {name: sha256_hex((ROOT / "vendor" / name).read_bytes()) for name in manifest["files"]}
        self.assertEqual(actual, manifest["files"])
        self.assertEqual(vp.PINNED_DIGEST, expected_digest(manifest["ref"], actual))
        self.assertEqual(vp.total_digest(manifest["ref"], actual), expected_digest(manifest["ref"], actual))

    def test_the_digest_changes_with_the_commit_every_name_every_hash_and_every_added_or_removed_file_but_not_with_the_order(self):
        base = {"pipeline/a.py": "a" * 64, "pipeline/b.py": "b" * 64}
        ref = "1" * 40
        digest = vp.total_digest(ref, base)
        self.assertEqual(digest, vp.total_digest(ref, dict(reversed(list(base.items())))), "넣은 순서는 값에 영향이 없다")
        variants = {
            "다른 커밋": (("2" * 40), base),
            "이름 하나 다름": (ref, {"pipeline/a.py": "a" * 64, "pipeline/c.py": "b" * 64}),
            "해시 하나 다름": (ref, {"pipeline/a.py": "a" * 64, "pipeline/b.py": "c" * 64}),
            "파일 하나 더함": (ref, {**base, "pipeline/c.py": "c" * 64}),
            "파일 하나 뺌": (ref, {"pipeline/a.py": "a" * 64}),
            "이름과 해시를 맞바꿈": (ref, {"pipeline/a.py": "b" * 64, "pipeline/b.py": "a" * 64}),
        }
        for label, (other_ref, other_files) in variants.items():
            with self.subTest(change=label):
                self.assertNotEqual(vp.total_digest(other_ref, other_files), digest)

    def test_the_manifest_reader_refuses_duplicate_keys_odd_names_and_bad_shapes(self):
        good_hash = "a" * 64
        cases = {
            "같은 칸 ref 두 번": '{"ref": "' + "1" * 40 + '", "ref": "' + "2" * 40 + '", "files": {"pipeline/a.py": "' + good_hash + '"}}',
            "같은 파일 이름 두 번": '{"ref": "' + "1" * 40 + '", "files": {"pipeline/a.py": "' + good_hash + '", "pipeline/a.py": "' + "b" * 64 + '"}}',
            "절대 경로": '{"ref": "' + "1" * 40 + '", "files": {"/etc/x.py": "' + good_hash + '"}}',
            "위쪽 폴더": '{"ref": "' + "1" * 40 + '", "files": {"../x.py": "' + good_hash + '"}}',
            "역슬래시": '{"ref": "' + "1" * 40 + '", "files": {"pipeline\\\\a.py": "' + good_hash + '"}}',
            "드라이브 글자": '{"ref": "' + "1" * 40 + '", "files": {"C:x.py": "' + good_hash + '"}}',
            "고르지 않은 경로 모양": '{"ref": "' + "1" * 40 + '", "files": {"pipeline//a.py": "' + good_hash + '"}}',
            "짧은 해시": '{"ref": "' + "1" * 40 + '", "files": {"pipeline/a.py": "abc"}}',
            "대문자 해시": '{"ref": "' + "1" * 40 + '", "files": {"pipeline/a.py": "' + "A" * 64 + '"}}',
            "빈 목록": '{"ref": "' + "1" * 40 + '", "files": {}}',
            "ref 없음": '{"files": {"pipeline/a.py": "' + good_hash + '"}}',
            "맨 위가 목록": "[1, 2]",
            "JSON 아님": "{abc",
        }
        for label, text in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "VENDOR.json").write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    vp.read_manifest(tmp)
                self.assertTrue(vp.problems(tmp), "문제 글이 있어야 한다")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "VENDOR.json").write_text('{"ref": "' + "1" * 40 + '", "files": {"pipeline/a.py": "' + good_hash + '"}}', encoding="utf-8")
            self.assertEqual(vp.read_manifest(tmp), ("1" * 40, {"pipeline/a.py": good_hash}))

    def test_sync_core_check_also_refuses_a_manifest_with_a_repeated_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            text = (tree / "vendor" / "VENDOR.json").read_text(encoding="utf-8")
            (tree / "vendor" / "VENDOR.json").write_text(text.replace('"source"', '"ref": "' + "1" * 40 + '",\n  "source"', 1), encoding="utf-8")
            self.assertTrue(any("두 번" in problem for problem in SYNC.check(tree)), SYNC.check(tree))

    def test_the_start_check_takes_milliseconds_and_never_raises(self):
        started = time.perf_counter()
        for _ in range(10):
            vp.start_problem(vendor=ROOT / "vendor", frozen=True)
        self.assertLess((time.perf_counter() - started) / 10, 0.25, "앱을 열 때 한 번 도는 확인은 수 ms 다 — 시작 시간에 영향이 없다")
        with mock.patch.object(vp, "problems", side_effect=RuntimeError("boom")):
            self.assertEqual(vp.start_problem(vendor=ROOT / "vendor"), vp.START_MESSAGE, "확인 자체가 실패하면 열지 않는다")
        self.assertEqual(vp.start_problem(vendor=ROOT / "no-such-folder"), vp.START_MESSAGE)
        for word in ("Traceback", "C:\\", "/", "해시", "sha"):
            self.assertNotIn(word, vp.START_MESSAGE, "시작 문구에는 경로·값·전문 낱말이 없다")


class TamperTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tree = make_tree(tmp.name)
        self.vendor = self.tree / "vendor"
        self.gates = self.vendor / "pipeline" / "gates.py"

    def weaken_gates_and_fix_the_manifest(self):
        self.gates.write_bytes(self.gates.read_bytes() + b"\n# CANARY_WEAKENED\n")
        rewrite_manifest(self.tree)

    def assert_refused_everywhere(self, label):
        with self.subTest(where=label + " / sync_core.check"):
            problems = SYNC.check(self.tree)
            self.assertTrue(any("총 요약값" in problem for problem in problems), problems)
        with self.subTest(where=label + " / problems"):
            self.assertTrue(any("총 요약값" in problem for problem in vp.problems(self.vendor, strict=False)))
        for frozen in (True, False):
            with self.subTest(where=label + f" / start frozen={frozen}"):
                self.assertEqual(vp.start_problem(vendor=self.vendor, frozen=frozen), vp.START_MESSAGE)
        with self.subTest(where=label + " / selftest"):
            result = ge.check_vendor(self.tree, fake_core(self.vendor))
            self.assertEqual(result.status, "fail", result.text)
            self.assertIn("고정", result.text)

    def test_the_tampered_files_with_a_recomputed_manifest_pass_the_old_self_consistency_check_but_not_the_pin(self):
        """감사 3단계: 파일을 고치고 목록의 해시도 다시 계산해 넣으면 옛 확인은 통과한다 — 이제 총 요약값이 막는다."""
        self.weaken_gates_and_fix_the_manifest()
        manifest = json.loads((self.vendor / "VENDOR.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["files"]["pipeline/gates.py"], sha256_hex(self.gates.read_bytes()), "시험의 전제 — 목록과 파일은 서로 맞다")
        self.assert_refused_everywhere("파일+목록")

    def test_changing_only_the_ref_to_any_forty_hex_characters_is_refused(self):
        """감사 4단계: ref 를 아무 40자리로 바꿔도 통과하던 것."""
        manifest_path = self.vendor / "VENDOR.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertNotEqual(manifest["ref"], "a" * 40)
        manifest["ref"] = "a" * 40
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assert_refused_everywhere("ref 만")

    def test_a_pin_changed_alone_is_refused_too(self):
        pin = self.tree / "src" / "chanceblog_desktop" / "vendor_pin.py"
        pin.write_bytes(pin.read_bytes().replace(vp.PINNED_DIGEST.encode("ascii"), ("0" * 64).encode("ascii"), 1))
        problems = SYNC.check(self.tree)
        self.assertTrue(any("총 요약값" in problem for problem in problems), problems)
        self.assertTrue(any("총 요약값" in problem for problem in vp.problems(self.vendor, strict=True, pinned="0" * 64)), "같은 함수에 고쳐진 고정값을 주어도 같은 이유로 거절한다")

    def test_a_changed_file_with_an_untouched_manifest_is_still_refused_by_the_old_per_file_check(self):
        self.gates.write_bytes(self.gates.read_bytes() + b"\n#x\n")
        found = vp.problems(self.vendor, strict=False)
        self.assertTrue(any("pipeline/gates.py" in problem and "해시" in problem for problem in found), found)
        self.assertEqual(vp.start_problem(vendor=self.vendor, frozen=False), vp.START_MESSAGE)

    def test_a_listed_file_that_is_missing_is_named(self):
        self.gates.unlink()
        self.assertTrue(any("pipeline/gates.py" in problem for problem in vp.problems(self.vendor, strict=False)))

    def test_the_unpacked_vendor_with_extra_files_is_refused_when_strict_and_ignored_otherwise(self):
        """감사 6단계: 목록 밖 `json.py` 가 있어도 자가 점검이 ok 였다. vendor/ 는 import 경로 맨 앞이라 표준 모듈을 가린다."""
        (self.vendor / "json.py").write_text("x = 1\n", encoding="utf-8")
        cache = self.vendor / "pipeline" / "__pycache__"
        cache.mkdir()
        (cache / "gates.cpython-312.pyc").write_bytes(b"cache")
        strict = vp.problems(self.vendor, strict=True)
        self.assertTrue(any(item.startswith("json.py") for item in strict), strict)
        self.assertTrue(any("__pycache__" in item for item in strict), strict)
        self.assertEqual(vp.problems(self.vendor, strict=False), [], "소스 실행의 시작 확인은 목록 밖 파일을 보지 않는다 — 개발 PC 의 캐시 같은 것으로 화면이 안 열리지 않게")
        self.assertEqual(vp.start_problem(vendor=self.vendor, frozen=True), vp.START_MESSAGE)
        self.assertIsNone(vp.start_problem(vendor=self.vendor, frozen=False))
        result = ge.check_vendor(self.tree, fake_core(self.vendor))
        self.assertEqual(result.status, "fail", "자가 점검은 늘 엄격하다")
        self.assertIn("json.py", result.text)

    def test_files_the_operating_system_makes_are_not_strangers(self):
        core.use_vendored_core()      # check_vendor 가 vendor 모듈(pipeline)을 불러 보므로 진짜 vendor 가 경로에 있어야 한다 — 혼자 돌려도·순서를 거꾸로 해도 통과(독립 시험 검증 Q 권고-6)
        for name in sorted(vp.IGNORED_NAMES):
            (self.vendor / name).write_text("", encoding="utf-8")
            (self.vendor / "pipeline" / name).write_text("", encoding="utf-8")
        self.assertEqual(vp.problems(self.vendor, strict=True), [])
        self.assertEqual(ge.check_vendor(self.tree, fake_core(self.vendor)).status, "ok")

    def test_a_link_inside_vendor_is_reported_and_never_followed(self):
        outside = self.tree / "outside"
        outside.mkdir()
        (outside / "json.py").write_text("x = 1\n", encoding="utf-8")
        link = self.vendor / "junc"
        tvc.make_link(self, link, outside)
        strict = vp.problems(self.vendor, strict=True)
        self.assertTrue(any("junc" in item and "링크" in item for item in strict), strict)
        self.assertFalse(any("json.py" in item for item in strict), "링크 안으로 들어가 세지 않는다")

    def test_a_listed_file_that_is_a_symlink_or_a_hard_link_is_refused_everywhere(self):
        for kind in ("symbolic", "hard"):
            with self.subTest(kind=kind):
                copy = self.tree / f"copy-{kind}"
                shutil.copytree(self.vendor, copy / "vendor")
                target = copy / "vendor" / "pipeline" / "gates.py"
                outside = self.tree / f"outside-{kind}.py"
                outside.write_bytes(target.read_bytes())
                target.unlink()
                try:
                    os.symlink(outside, target) if kind == "symbolic" else os.link(outside, target)
                except (OSError, NotImplementedError):
                    self.skipTest(f"이 환경에서는 {kind} 링크를 만들 수 없다")
                found = vp.problems(copy / "vendor", strict=False)
                self.assertTrue(any("pipeline/gates.py" in item and "링크" in item for item in found), found)

    def test_the_link_rule_is_the_one_the_backup_uses_so_cloud_placeholders_are_fine(self):
        """OneDrive 로 동기화되는 폴더에 풀어도(파일이 '온라인 전용' 으로 바뀌어도) 앱이 안 열리면 안 된다 — 링크 종류가 아닌 재해석 지점은 보통 파일이다. 링크 종류(심볼릭·마운트 지점)는 거절한다."""
        target = os.path.normcase(os.fspath(self.gates))
        real = os.lstat
        for label, tag, expected_refused in (("클라우드 자리표시", IO_REPARSE_TAG_CLOUD, False), ("심볼릭 링크 종류", 0xA000000C, True), ("마운트 지점 종류", 0xA0000003, True)):
            def fake(candidate, *args, _tag=tag, **kwargs):
                if os.path.normcase(os.fspath(candidate)) == target:
                    return fake_lstat(st_file_attributes=0x400 | 0x20, st_reparse_tag=_tag)
                return real(candidate, *args, **kwargs)
            with self.subTest(case=label), mock.patch.object(os, "lstat", fake):
                found = [item for item in vp.problems(self.vendor, strict=False) if item.startswith("pipeline/gates.py")]
                self.assertEqual(bool(found), expected_refused, found)


@unittest.skipUnless(shutil.which("git"), "git 이 필요하다(GIT_NOT_INSTALLED 상황)")
class SyncWritesThePinTest(unittest.TestCase):
    """가져오기가 vendor/ 와 같은 때에 고정값도 다시 쓴다 — 쓰고 나면 `check` 가 []."""

    @classmethod
    def setUpClass(cls):
        shared = tempfile.TemporaryDirectory()
        cls.addClassCleanup(shared.cleanup)
        cls.shared = Path(shared.name)
        cls.source, cls.sha = tvc.make_source(cls.shared / "source")
        cls.new_sha = tvc.commit(cls.source, {"pipeline/gates.py": b"# a changed gates\n"}, "changed")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "root"
        (self.root / "src" / "chanceblog_desktop").mkdir(parents=True)
        shutil.copyfile(PIN_SOURCE, self.root / "src" / "chanceblog_desktop" / "vendor_pin.py")
        self.pin = self.root / "src" / "chanceblog_desktop" / "vendor_pin.py"

    def test_a_sync_into_a_source_tree_rewrites_the_pin_and_the_check_then_passes(self):
        before = self.pin.read_bytes()
        commit = SYNC.sync(self.source, self.sha, self.root)
        manifest = json.loads((self.root / "vendor" / "VENDOR.json").read_text(encoding="utf-8"))
        after = self.pin.read_bytes()
        self.assertNotEqual(after, before)
        self.assertEqual(re.findall(rb'^PINNED_DIGEST = "([0-9a-f]{64})"', after, re.M), [expected_digest(commit, manifest["files"]).encode("ascii")])
        self.assertEqual(SYNC.check(self.root), [])
        self.assertEqual(after.replace(re.search(rb'PINNED_DIGEST = "[0-9a-f]{64}"', after).group(0), b""), before.replace(re.search(rb'PINNED_DIGEST = "[0-9a-f]{64}"', before).group(0), b""), "그 한 줄 밖은 한 바이트도 바뀌지 않았다")
        self.assertEqual(vp.problems(self.root / "vendor", strict=True, pinned=SYNC._load_pin(self.root).PINNED_DIGEST), [])

    def test_a_second_sync_to_a_newer_commit_moves_the_pin_again(self):
        SYNC.sync(self.source, self.sha, self.root)
        first = SYNC._load_pin(self.root).PINNED_DIGEST
        SYNC.sync(self.source, self.new_sha, self.root)
        second = SYNC._load_pin(self.root).PINNED_DIGEST
        self.assertNotEqual(first, second)
        self.assertEqual(SYNC.check(self.root), [])

    def test_the_line_ending_of_the_pin_file_is_kept(self):
        for newline in (b"\r\n", b"\n"):
            with self.subTest(newline=newline):
                text = self.pin.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
                self.pin.write_bytes(text)
                SYNC.sync(self.source, self.sha, self.root)
                after = self.pin.read_bytes()
                self.assertEqual(after.count(b"\r\n"), after.count(b"\n") if newline == b"\r\n" else 0)

    def test_a_tree_without_the_source_folder_is_synced_and_checked_as_before(self):
        plain = self.root.parent / "plain"
        SYNC.sync(self.source, self.sha, plain)
        self.assertEqual(SYNC.check(plain), [])
        self.assertFalse((plain / "src").exists(), "소스 나무가 없는 사본에는 고정값 파일을 만들지 않는다")

    def test_a_source_tree_whose_pin_file_is_missing_stops_before_anything_is_written(self):
        self.pin.unlink()
        with self.assertRaises(RuntimeError) as caught:
            SYNC.sync(self.source, self.sha, self.root)
        self.assertIn("vendor_pin.py", str(caught.exception))
        self.assertFalse((self.root / "vendor").exists())

    def test_a_pin_file_that_is_a_link_stops_the_sync_before_anything_is_written(self):
        outside = self.root.parent / "outside_pin.py"
        outside.write_bytes(self.pin.read_bytes())
        self.pin.unlink()
        try:
            os.symlink(outside, self.pin)
        except (OSError, NotImplementedError):
            self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        before = outside.read_bytes()
        with self.assertRaises(RuntimeError):
            SYNC.sync(self.source, self.sha, self.root)
        self.assertEqual(outside.read_bytes(), before, "링크 너머의 파일을 덮어쓰지 않는다")
        self.assertFalse((self.root / "vendor").exists())

    def test_a_pin_file_with_two_digest_lines_cannot_be_rewritten_and_stops_before_writing(self):
        self.pin.write_bytes(self.pin.read_bytes() + b'\nPINNED_DIGEST = "' + b"1" * 64 + b'"\n')
        with self.assertRaises(RuntimeError):
            SYNC.sync(self.source, self.sha, self.root)
        self.assertFalse((self.root / "vendor").exists())

    def test_a_failed_import_leaves_the_pin_alone(self):
        contents = {rel: b"x = 1\n" for rel in SYNC.FILES if rel != "pipeline/gates.py"}
        broken, _sha = tvc.make_source(self.root.parent / "broken", contents)
        before = self.pin.read_bytes()
        with self.assertRaises(RuntimeError):
            SYNC.sync(broken, "HEAD", self.root)
        self.assertEqual(self.pin.read_bytes(), before)

    def test_a_failure_while_replacing_leaves_no_temporary_file_next_to_the_pin(self):
        with mock.patch.object(SYNC.os, "replace", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                SYNC.sync(self.source, self.sha, self.root)
        self.assertEqual([path.name for path in self.pin.parent.iterdir() if path.name.endswith(".sync-tmp")], [])


class StartCheckTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(sec.uninstall_boundary)                    # `launcher.main` 이 맨 앞에서 공통 출력 경계를 깐다 — 같은 프로세스에서 부른 시험이 경계를 남기지 않게

    def test_the_launcher_refuses_to_open_before_it_even_looks_for_pyside6(self):
        out = io.StringIO()
        with mock.patch.object(vp, "start_problem", return_value="MSG-FROM-THE-START-CHECK"), \
                mock.patch.object(launcher, "has_pyside6", side_effect=AssertionError("PySide6 확인까지 갔다")), \
                mock.patch.object(launcher.single_instance, "claim", side_effect=AssertionError("창을 만들려 했다")):
            self.assertEqual(launcher.main(["--sample"], out=out), 1)
        self.assertEqual(out.getvalue().strip(), "MSG-FROM-THE-START-CHECK")

    def test_a_tampered_real_vendor_makes_the_launcher_refuse_with_the_easy_sentence_and_no_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = make_tree(tmp)
            gates = tree / "vendor" / "pipeline" / "gates.py"
            gates.write_bytes(gates.read_bytes() + b"\n# CANARY_WEAKENED\n")
            rewrite_manifest(tree)
            out = io.StringIO()
            real_check = vp.start_problem                                                 # 진짜 확인을 그대로 쓰되 변조한 사본의 vendor/ 를 보게 한다(`core.vendor_dir` 를 바꾸면 이미 불려 온 `pipeline` 의 자리와 달라 다른 확인이 먼저 멈춘다)
            with mock.patch.object(vp, "start_problem", lambda: real_check(vendor=tree / "vendor")), mock.patch.object(launcher, "has_pyside6", side_effect=AssertionError("PySide6 확인까지 갔다")):
                self.assertEqual(launcher.main(["--sample"], out=out), 1)
        self.assertEqual(out.getvalue().strip(), vp.START_MESSAGE)
        self.assertNotIn(tmp, out.getvalue())

    def test_the_real_vendor_does_not_stop_the_launcher(self):
        out = io.StringIO()
        with mock.patch.object(launcher, "has_pyside6", return_value=False):
            self.assertEqual(launcher.main(["--sample"], out=out), 1)
        self.assertEqual(out.getvalue().strip(), launcher.NEEDS_PYSIDE6, "진짜 vendor 는 통과하고 그 다음 확인(PySide6)으로 간다")


class SourceShapeTest(unittest.TestCase):
    def tree_of(self, path):
        return ast.parse(Path(path).read_text(encoding="utf-8"))

    def function(self, path, name):
        return next(node for node in ast.walk(self.tree_of(path)) if isinstance(node, ast.FunctionDef) and node.name == name)

    def calls(self, node):
        return [ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)]

    def test_the_launcher_asks_the_start_check_before_the_pyside6_check(self):
        main = self.function(ROOT / "src" / "chanceblog_desktop" / "ui" / "launcher.py", "main")
        calls = self.calls(main)
        self.assertIn("vendor_pin.start_problem", calls)
        self.assertLess(calls.index("vendor_pin.start_problem"), calls.index("has_pyside6"))

    def test_the_selftest_vendor_item_asks_the_pin_module_for_the_strict_check(self):
        function = self.function(ps.PACKAGING / "gui_entry.py", "check_vendor")
        strict = [item for item in ast.walk(function) if isinstance(item, ast.Call) and ast.unparse(item.func) == "pinned.problems"]
        self.assertEqual(len(strict), 1)
        self.assertEqual([(keyword.arg, ast.unparse(keyword.value)) for keyword in strict[0].keywords], [("strict", "True")], "자가 점검은 늘 엄격하다")

    def test_the_pin_module_imports_only_the_standard_library_at_the_top_so_sync_core_can_load_it_by_path(self):
        allowed = {"__future__", "hashlib", "json", "os", "stat", "sys", "pathlib"}
        tree = self.tree_of(PIN_SOURCE)
        for node in tree.body:
            if isinstance(node, ast.Import):
                self.assertTrue({alias.name.split(".")[0] for alias in node.names} <= allowed, ast.unparse(node))
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, ast.unparse(node))
                self.assertIn((node.module or "").split(".")[0], allowed, ast.unparse(node))
        text = PIN_SOURCE.read_text(encoding="utf-8")
        for word in ("socket", "urllib", "http", "subprocess", "eval(", "exec(", "pickle", "ctypes", "environ", "getenv"):
            self.assertNotIn(word, text, word)

    def test_sync_core_writes_the_pin_through_the_same_staged_replace_path_as_the_vendor_files(self):
        sync = self.function(ROOT / "scripts" / "sync_core.py", "sync")
        names = {node.id for node in ast.walk(sync) if isinstance(node, ast.Name)}
        for needed in ("PIN_RELATIVE", "PIN_LINE", "pin", "planned", "staged"):
            self.assertIn(needed, names, needed)
        check = self.function(ROOT / "scripts" / "sync_core.py", "check")
        self.assertIn("_pin_problems", self.calls(check))


if __name__ == "__main__":
    unittest.main()
