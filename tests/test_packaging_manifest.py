"""Package 정보 파일 생성기(`packaging/make_manifest.py`) 시험 — 운영자가 요구한 여덟 가지(Version·Git Commit·SHA-256·Dependency 목록·Build 방법·Malware 검사 결과·서명 여부·SmartScreen 예상 동작)가
`PACKAGE_INFO.md`·`PACKAGE_INFO.json`·`SHA256SUMS` 에 빠짐없이 있고, 깨끗하지 않은 작업 트리를 거절하고, 같은 입력이면 같은 바이트가 나오는지 본다.
PyInstaller·PySide6·네트워크·진짜 Windows Defender 없이 돈다(검사 도구와 설치 정보는 가짜를 끼운다).
"""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import packaging_support as ps

mm = ps.make_manifest
pc = ps.pkgcommon
TILDE = chr(0x7E)
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
FIRST_LINE = "**개인 PC 제한 시험용, 미서명 Package — 공개 배포용이 아닙니다**"


sample_info = ps.sample_info


@unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
class GitStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.commit = ps.init_repo(self.repo, {"VERSION": "0.1.0-preview.1\n", "a.txt": "a\n"}, ignore="dist/\n")

    def test_a_clean_repository_reports_the_full_hashes_and_the_commit_time(self):
        state = mm.git_state(self.repo)
        self.assertEqual(state["commit"], self.commit)
        self.assertRegex(state["tree"], r"^[0-9a-f]{40}$")
        self.assertEqual((state["clean"], state["dirty_count"]), (True, 0))
        self.assertEqual(state["committed_epoch"], ps.COMMIT_EPOCH)
        self.assertEqual(state["committed_utc"], "2026-11-11T01:00:00Z")
        self.assertIs(mm.require_clean(state), state)

    def test_untracked_modified_and_staged_changes_all_make_it_dirty(self):
        cases = {
            "untracked": lambda: ps.write(self.repo / "new.txt", "n"),
            "modified": lambda: ps.write(self.repo / "a.txt", "changed\n"),
            "staged": lambda: (ps.write(self.repo / "b.txt", "b"), ps.git(self.repo, "add", "b.txt")),
            "deleted": lambda: (self.repo / "a.txt").unlink(),
        }
        for name, change in cases.items():
            with self.subTest(name=name):
                ps.git(self.repo, "reset", "-q", "--hard")
                ps.git(self.repo, "clean", "-fdq")
                change()
                state = mm.git_state(self.repo)
                self.assertFalse(state["clean"], name)
                self.assertGreaterEqual(state["dirty_count"], 1)
                with self.assertRaises(mm.BuildRefused) as caught:
                    mm.require_clean(state)
                self.assertIn("깨끗하지 않아요", str(caught.exception))

    def test_ignored_files_do_not_make_it_dirty(self):
        ps.write(self.repo / "dist" / "package" / "x.zip", b"1", binary=True)
        self.assertTrue(mm.git_state(self.repo)["clean"])

    def test_ignored_files_inside_the_build_input_folders_make_it_not_clean_but_caches_and_other_folders_do_not(self):
        repo = Path(self.tmp.name) / "repo2"
        ps.init_repo(repo, {"VERSION": "0.1.0-preview.1\n", "vendor/a.py": "a\n", "src/m.py": "m\n"}, ignore="dist/\n*.log\n__pycache__/\n*.pyc\n")
        ps.write(repo / "dist" / "package" / "release" / "x.zip", b"1", binary=True)        # 출력 폴더는 입력이 아니다
        ps.write(repo / "docs" / "note.log", "x")                                           # 입력 폴더 밖의 무시되는 파일
        ps.write(repo / "vendor" / "__pycache__" / "a.cpython-312.pyc", b"c", binary=True)  # 바이트코드 캐시는 묶음에 들어가지 않는다
        ps.write(repo / "src" / "chanceblog_desktop" / "m.pyc", b"c", binary=True)
        self.assertEqual(mm.ignored_inputs(repo), [])
        self.assertTrue(mm.git_state(repo)["clean"])
        ps.write(repo / "vendor" / "pipeline" / "debug.log", "나중에 묶음에 섞일 수 있는 파일")
        ps.write(repo / "src" / "local.log", "x")
        ps.write(repo / "vendor" / "한글 이름.log", "x")
        found = mm.ignored_inputs(repo)
        self.assertEqual(found, ["src/local.log", "vendor/pipeline/debug.log", "vendor/한글 이름.log"])
        state = mm.git_state(repo)
        self.assertEqual((state["clean"], state["dirty_count"], state["ignored_inputs"]), (False, 0, found))
        with self.assertRaises(mm.BuildRefused) as caught:
            mm.require_clean(state)
        message = str(caught.exception)
        self.assertIn("무시하는 파일", message)
        self.assertIn("vendor/pipeline/debug.log", message)
        self.assertNotIn("커밋되지 않은 변경", message)

    def test_the_refusal_for_ignored_files_names_the_first_five_and_counts_the_rest(self):
        state = {"clean": False, "dirty_count": 0, "ignored_inputs": [f"vendor/f{number}.log" for number in range(7)]}
        with self.assertRaises(mm.BuildRefused) as caught:
            mm.require_clean(state)
        message = str(caught.exception)
        self.assertIn("vendor/f4.log", message)
        self.assertNotIn("vendor/f5.log", message)
        self.assertIn("외 2개", message)

    def test_a_dirty_tree_message_says_to_keep_the_virtual_environment_outside_the_repository(self):
        ps.write(self.repo / ".venv-package" / "pyvenv.cfg", "home = x")
        state = mm.git_state(self.repo)
        self.assertFalse(state["clean"])
        with self.assertRaises(mm.BuildRefused) as caught:
            mm.require_clean(state)
        self.assertIn("저장소 밖", str(caught.exception))

    def make_input_repo(self, name):
        repo = Path(self.tmp.name) / name
        ps.init_repo(repo, {"VERSION": "0.1.0-preview.1\n", "vendor/a.py": "a\n", "src/m.py": "m\n", "docs/x.md": "x\n"}, ignore="dist/\n")
        return repo

    def test_an_untracked_file_in_an_input_folder_is_seen_even_when_git_is_told_not_to_show_untracked_files(self):
        repo = self.make_input_repo("repo_untracked")
        self.assertTrue(mm.git_state(repo)["clean"])
        ps.git(repo, "config", "status.showUntrackedFiles", "no")
        for relative in ("vendor/pipeline/note.txt", "src/chanceblog_desktop/new_module.py", "packaging/extra_tool.py"):
            ps.write(repo / relative, "새 파일")
        self.assertEqual(ps.git(repo, "status", "--porcelain"), "")                       # 설정 때문에 git status 는 아무것도 안 보여 준다
        state = mm.git_state(repo)
        self.assertFalse(state["clean"])
        self.assertEqual(state["dirty_count"], 3)                                         # 명령줄 옵션이 설정보다 앞서 새 파일 셋이 모두 보인다
        self.assertEqual(sorted(item.split("(")[0] for item in state["hidden_changes"]), ["packaging/extra_tool.py", "src/chanceblog_desktop/new_module.py", "vendor/pipeline/note.txt"])
        with self.assertRaises(mm.BuildRefused) as caught:
            mm.require_clean(state)
        self.assertIn("깨끗하지 않아요", str(caught.exception))

    def test_a_file_changed_behind_skip_worktree_or_assume_unchanged_is_not_clean(self):
        for flag in ("--skip-worktree", "--assume-unchanged"):
            label = flag[2:]
            repo = self.make_input_repo("repo_" + label)
            self.assertTrue(mm.git_state(repo)["clean"])
            for relative in ("vendor/a.py", "src/m.py", "VERSION"):                       # 입력 폴더 둘과 VERSION 모두
                with self.subTest(flag=flag, relative=relative):
                    self.assertEqual(mm.git_hidden_changes(repo), [])
                    ps.git(repo, "update-index", flag, relative)
                    ps.write(repo / relative, "몰래 고친 글\n")
                    self.assertEqual(ps.git(repo, "status", "--porcelain"), "")            # git status 에는 안 보인다
                    state = mm.git_state(repo)
                    self.assertFalse(state["clean"])
                    self.assertEqual((state["dirty_count"], state["ignored_inputs"]), (0, []))
                    self.assertEqual(len(state["hidden_changes"]), 1)
                    self.assertIn(relative, state["hidden_changes"][0])
                    self.assertIn(label, state["hidden_changes"][0])
                    with self.assertRaises(mm.BuildRefused) as caught:
                        mm.require_clean(state)
                    self.assertIn("가려진 변경", str(caught.exception))
                    self.assertIn(relative, str(caught.exception))
                    ps.git(repo, "update-index", "--no-" + label, relative)
                    ps.git(repo, "checkout", "--", relative)
                    self.assertEqual(mm.git_hidden_changes(repo), [])                    # 표시를 풀고 되돌리면 다시 깨끗하다
            self.assertTrue(mm.git_state(repo)["clean"])

    def test_a_hidden_mark_outside_the_build_inputs_does_not_matter(self):
        repo = self.make_input_repo("repo_docs")
        ps.git(repo, "update-index", "--skip-worktree", "docs/x.md")
        ps.write(repo / "docs" / "x.md", "입력 밖이라 묶음에 닿지 않는다\n")
        self.assertTrue(mm.git_state(repo)["clean"])

    def test_the_file_list_on_disk_is_compared_with_the_tracked_list(self):
        root = Path(self.tmp.name) / "fake_repo"
        ps.write(root / "vendor" / "tracked.py", "t\n")
        ps.write(root / "vendor" / "extra.txt", "e\n")
        ps.write(root / "vendor" / "__pycache__" / "x.cpython-312.pyc", b"c", binary=True)       # 캐시는 묶음에 안 들어가니 세지 않는다
        ps.write(root / "src" / "chanceblog_desktop" / "m.pyc", b"c", binary=True)
        ps.write(root / "VERSION", "0.1.0-preview.1\n")
        answer = lambda text: (lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=text, stderr=""))        # noqa: E731
        listing = "H VERSION\0H vendor/tracked.py\0H vendor/gone.py\0"
        self.assertEqual(mm.git_hidden_changes(root, runner=answer(listing)), ["vendor/extra.txt(git 이 모르는 파일)", "vendor/gone.py(추적 파일이 디스크에 없음)"])
        complete = "H VERSION\0H vendor/tracked.py\0H vendor/extra.txt\0"
        self.assertEqual(mm.git_hidden_changes(root, runner=answer(complete)), [])
        marked = "H VERSION\0S vendor/tracked.py\0h vendor/extra.txt\0"
        found = mm.git_hidden_changes(root, runner=answer(marked))
        self.assertEqual([item.split("(")[0] for item in found], ["vendor/tracked.py", "vendor/extra.txt"])
        self.assertIn("skip-worktree", found[0])
        self.assertIn("assume-unchanged", found[1])

    def test_the_refusal_for_hidden_changes_names_the_first_five_and_counts_the_rest(self):
        state = {"clean": False, "dirty_count": 0, "ignored_inputs": [], "hidden_changes": [f"vendor/f{number}.py(git 표시: skip-worktree)" for number in range(7)]}
        with self.assertRaises(mm.BuildRefused) as caught:
            mm.require_clean(state)
        message = str(caught.exception)
        self.assertIn("vendor/f4.py", message)
        self.assertNotIn("vendor/f5.py", message)
        self.assertIn("외 2개", message)
        self.assertIn("no-skip-worktree", message)

    def test_each_of_the_three_findings_alone_makes_the_tree_not_clean(self):
        """깨끗함 = '커밋 안 된 변경 없음' 이고 '무시되는 입력 파일 없음' 이고 '가려진 변경 없음' — 가짜 git 으로 한 항씩만 거짓으로 만들어 본다(진짜 git 에서는 무시되는 파일이 가려진 변경 목록에도 들어가 한 항이 가려진다)."""
        root = Path(self.tmp.name) / "formula_repo"
        ps.write(root / "VERSION", "0.1.0-preview.1\n")
        ps.write(root / "vendor" / "tracked.py", "t\n")

        def runner_for(*, status="", ignored="", listing="H VERSION\0H vendor/tracked.py\0"):
            def run(command, **kwargs):
                args = command[3:]                                                            # ["git", "-C", 저장소] 다음의 인자
                if args[0] == "rev-parse":
                    out = "a" * 40
                elif args[0] == "show":
                    out = str(ps.COMMIT_EPOCH)
                elif args[0] == "status":
                    out = status
                elif args[0] == "ls-files" and "--ignored" in args:
                    out = ignored
                else:
                    out = listing
                return subprocess.CompletedProcess(command, 0, stdout=out, stderr="")
            return run
        base = mm.git_state(root, runner=runner_for())
        self.assertEqual((base["clean"], base["dirty_count"], base["ignored_inputs"], base["hidden_changes"]), (True, 0, [], []))
        dirty = mm.git_state(root, runner=runner_for(status=" M vendor/tracked.py\n"))
        self.assertEqual((dirty["clean"], dirty["dirty_count"], dirty["ignored_inputs"], dirty["hidden_changes"]), (False, 1, [], []))
        ignored = mm.git_state(root, runner=runner_for(ignored="vendor/leftover.log\0"))
        self.assertEqual((ignored["clean"], ignored["dirty_count"], ignored["ignored_inputs"], ignored["hidden_changes"]), (False, 0, ["vendor/leftover.log"], []))
        hidden = mm.git_state(root, runner=runner_for(listing="H VERSION\0S vendor/tracked.py\0"))
        self.assertEqual((hidden["clean"], hidden["dirty_count"], hidden["ignored_inputs"], len(hidden["hidden_changes"])), (False, 0, [], 1))

    def test_a_folder_that_is_not_a_repository_is_refused_with_a_plain_sentence(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(Path(self.tmp.name))}):
            with self.assertRaises(mm.BuildRefused) as caught:
                mm.git_state(plain)
        self.assertIn("git", str(caught.exception))

    def test_a_runner_that_returns_odd_hashes_is_refused(self):
        outputs = iter(["not-a-hash\n", "x\n", "123\n", ""])
        runner = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=next(outputs), stderr="")      # noqa: E731
        with self.assertRaises((mm.BuildRefused, ValueError)):
            mm.git_state(self.repo, runner=runner)

    def test_a_missing_git_program_is_refused_not_raised(self):
        def runner(*a, **k):
            raise FileNotFoundError("git")
        with self.assertRaises(mm.BuildRefused):
            mm.git_state(self.repo, runner=runner)


class RequirementsTest(unittest.TestCase):
    LOCK = (ps.PACKAGING / "requirements-package.txt").read_text(encoding="utf-8")

    def test_the_real_lock_file_pins_exact_versions_with_roles(self):
        found = mm.parse_requirements(self.LOCK)
        table = {item["name"]: (item["version"], item["role"]) for item in found}
        self.assertEqual(table["PySide6_Essentials"][1], "runtime")
        self.assertEqual(table["shiboken6"][1], "runtime")
        self.assertEqual(table["pyinstaller"][1], "build")
        self.assertEqual(table["PySide6_Essentials"][0], table["shiboken6"][0], "PySide6 와 shiboken6 는 같은 버전이어야 한다")
        for item in found:
            self.assertRegex(item["version"], r"^[0-9][0-9A-Za-z.+!_-]*$")
        self.assertEqual(len({mm.normalize_name(item["name"]) for item in found}), len(found))

    def test_ranges_urls_options_duplicates_and_missing_roles_are_refused(self):
        bad = {
            "range": "# [runtime]\nfoo>=1.0\n",
            "no version": "# [runtime]\nfoo\n",
            "option": "# [runtime]\n-r other.txt\n",
            "url": "# [runtime]\nfoo @ file:///x.whl\n",
            "duplicate": "# [runtime]\nfoo==1.0\nFoo==1.0\n",
            "duplicate underscore": "# [runtime]\nfoo_bar==1.0\nfoo-bar==1.0\n",
            "no role": "foo==1.0\n",
            "unknown role": "# [other]\nfoo==1.0\n",
            "empty": "# only a comment\n\n",
            "compatible": "# [build]\nfoo~=1.0\n",
        }
        for name, text in bad.items():
            with self.subTest(name=name):
                with self.assertRaises(mm.BuildRefused):
                    mm.parse_requirements(text)

    def test_hash_lines_continued_with_a_backslash_are_read(self):
        text = "# [runtime]\nfoo==1.0 " + chr(92) + "\n    --hash=sha256:" + "a" * 64 + " " + chr(92) + "\n    --hash=sha256:" + "b" * 64 + "\nbar==2.0\n"
        found = mm.parse_requirements(text)
        self.assertEqual([item["name"] for item in found], ["foo", "bar"])
        self.assertEqual(found[0]["hashes"], ["a" * 64, "b" * 64])
        self.assertEqual(found[1]["hashes"], [])

    def test_installed_versions_must_equal_the_lock(self):
        found = mm.parse_requirements(self.LOCK)
        self.assertTrue(mm.check_installed(found, lookup=ps.fake_lookup()))
        versions = ps.lock_versions()
        for key in ("pyinstaller", "pyside6-essentials"):
            wrong = dict(versions, **{key: versions[key] + ".1"})
            with self.subTest(key=key):
                with self.assertRaises(mm.BuildRefused) as caught:
                    mm.check_installed(found, lookup=ps.fake_lookup(wrong))
                self.assertIn("잠금", str(caught.exception))
        missing = {key: value for key, value in versions.items() if key != "altgraph"}
        with self.assertRaises(mm.BuildRefused) as caught:
            mm.check_installed(found, lookup=ps.fake_lookup(missing))
        self.assertIn("altgraph", str(caught.exception))

    def test_name_normalization_matches_pip(self):
        self.assertEqual(mm.normalize_name("PySide6_Essentials"), "pyside6-essentials")
        self.assertEqual(mm.normalize_name("pyinstaller.hooks__contrib"), "pyinstaller-hooks-contrib")


class FingerprintTest(unittest.TestCase):
    RECORD = "pkg/__init__.py,sha256=aaa,10\npkg/data.bin,sha256=bbb,20\n"

    def test_the_fingerprint_is_stable_order_free_and_counts_files(self):
        first, count = mm.record_fingerprint(self.RECORD)
        reordered, _ = mm.record_fingerprint("pkg/data.bin,sha256=bbb,20\npkg/__init__.py,sha256=aaa,10\n")
        self.assertEqual(first, reordered)
        self.assertEqual(count, 2)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")

    def test_environment_specific_lines_are_left_out(self):
        base, _ = mm.record_fingerprint(self.RECORD)
        noisy = self.RECORD + "pkg/__pycache__/x.cpython-312.pyc,sha256=ccc,1\npkg/mod.pyc,,\n../../Scripts/tool.exe,sha256=ddd,2\npkg-1.0.dist-info/RECORD,,\npkg-1.0.dist-info/INSTALLER,sha256=e,1\npkg-1.0.dist-info/REQUESTED,,\npkg-1.0.dist-info/direct_url.json,sha256=f,3\n"
        self.assertEqual(mm.record_fingerprint(noisy)[0], base)

    def test_a_changed_hash_or_path_changes_the_fingerprint(self):
        base, _ = mm.record_fingerprint(self.RECORD)
        self.assertNotEqual(mm.record_fingerprint(self.RECORD.replace("bbb", "bbc"))[0], base)
        self.assertNotEqual(mm.record_fingerprint(self.RECORD.replace("data.bin", "data2.bin"))[0], base)
        self.assertNotEqual(mm.record_fingerprint(self.RECORD + "pkg/extra.py,sha256=eee,5\n")[0], base)

    def test_quoted_paths_with_commas_and_backslashes_are_read(self):
        text = '"pkg/a,b.py",sha256=xyz,3\n' + "pkg" + chr(92) + "win.py,sha256=www,4\n"
        fingerprint, count = mm.record_fingerprint(text)
        self.assertEqual(count, 2)
        self.assertEqual(fingerprint, mm.record_fingerprint('"pkg/a,b.py",sha256=xyz,3\npkg/win.py,sha256=www,4\n')[0])

    def test_package_license_prefers_the_expression_and_cuts_long_texts(self):
        meta = ps.FakeMetadata({"License-Expression": "MIT", "License": "ignored"})
        self.assertEqual(mm.package_license(meta), "MIT")
        self.assertEqual(mm.package_license(ps.FakeMetadata({"License": "Line one\nline two"})), "Line one")
        self.assertEqual(len(mm.package_license(ps.FakeMetadata({"License": "x" * 500}))), 120)
        self.assertEqual(mm.package_license(ps.FakeMetadata({"Classifier": ["License :: OSI Approved :: MIT License", "Topic :: x"]})), "MIT License")
        self.assertEqual(mm.package_license(ps.FakeMetadata({})), "표기 없음")

    def test_dependency_entries_carry_version_role_license_and_fingerprint(self):
        found = mm.parse_requirements((ps.PACKAGING / "requirements-package.txt").read_text(encoding="utf-8"))
        with ps.temp_dir() as tmp:
            entries = mm.dependency_entries(found, distribution=ps.fake_distribution_factory(tmp))
        self.assertEqual([item["name"] for item in entries], [item["name"] for item in found])
        by_name = {item["name"]: item for item in entries}
        self.assertEqual(by_name["shiboken6"]["role"], "runtime")
        self.assertIn("LGPL-3.0-only", by_name["shiboken6"]["license"])
        self.assertRegex(by_name["pyinstaller"]["fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(by_name["pyinstaller"]["files"], 2)


class FilesAndSigningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_collect_files_lists_posix_paths_sorted_with_their_hashes_and_skips_only_the_top_info_files(self):
        ps.write(self.root / "b.txt", "b")
        ps.write(self.root / "a" / "z.bin", b"zz", binary=True)
        ps.write(self.root / "a" / "PACKAGE_INFO.json", "nested stays")
        ps.write(self.root / "PACKAGE_INFO.json", "top skipped")
        ps.write(self.root / "PACKAGE_INFO.md", "top skipped")
        (self.root / "empty_dir").mkdir()
        files = mm.collect_files(self.root)
        self.assertEqual(list(files), ["a/PACKAGE_INFO.json", "a/z.bin", "b.txt"])
        self.assertEqual(files["b.txt"], pc.sha256_bytes(b"b"))
        self.assertTrue(all("\\" not in name for name in files))

    def test_authenticode_state_reads_the_security_directory_for_both_pe_kinds(self):
        for plus in (True, False):
            for signed in (True, False):
                path = ps.write(self.root / f"x_{plus}_{signed}.exe", ps.pe_bytes(signed=signed, plus=plus), binary=True)
                with self.subTest(plus=plus, signed=signed):
                    self.assertEqual(mm.authenticode_state(path), "signed" if signed else "unsigned")

    def test_authenticode_state_treats_anything_else_as_not_pe(self):
        self.assertEqual(mm.authenticode_state(ps.write(self.root / "t.txt", "hello")), "not_pe")
        self.assertEqual(mm.authenticode_state(ps.write(self.root / "short.exe", b"MZ", binary=True)), "not_pe")
        self.assertEqual(mm.authenticode_state(self.root / "missing.exe"), "not_pe")
        bad_offset = bytearray(ps.pe_bytes())
        bad_offset[0x3C:0x40] = (10_000_000).to_bytes(4, "little")
        self.assertEqual(mm.authenticode_state(ps.write(self.root / "bad.exe", bytes(bad_offset), binary=True)), "not_pe")
        no_pe_sig = bytearray(ps.pe_bytes())
        no_pe_sig[0x80:0x84] = b"XXXX"
        self.assertEqual(mm.authenticode_state(ps.write(self.root / "nosig.exe", bytes(no_pe_sig), binary=True)), "not_pe")

    def test_signing_summary_reports_the_exe_as_unsigned_and_counts_signed_third_party_binaries(self):
        ps.write(self.root / f"{pc.EXE_NAME}.exe", ps.pe_bytes(), binary=True)
        ps.write(self.root / "_internal" / "python312.dll", ps.pe_bytes(signed=True), binary=True)
        ps.write(self.root / "_internal" / "Qt6Core.dll", ps.pe_bytes(signed=False), binary=True)
        ps.write(self.root / "_internal" / "x.pyd", ps.pe_bytes(signed=True), binary=True)
        ps.write(self.root / "_internal" / "readme.txt", "not a binary")
        summary = mm.signing_summary(self.root, f"{pc.EXE_NAME}.exe")
        self.assertEqual((summary["signed"], summary["exe"], summary["signed_third_party_binaries"]), (False, "unsigned", 2))
        self.assertIn("미서명", summary["summary"])

    def test_a_signed_exe_is_reported_as_signed_and_a_missing_exe_as_missing(self):
        ps.write(self.root / f"{pc.EXE_NAME}.exe", ps.pe_bytes(signed=True), binary=True)
        self.assertTrue(mm.signing_summary(self.root, f"{pc.EXE_NAME}.exe")["signed"])
        empty = self.root / "empty"
        empty.mkdir()
        summary = mm.signing_summary(empty, f"{pc.EXE_NAME}.exe")
        self.assertEqual((summary["signed"], summary["exe"]), (False, "missing"))


class DefenderTest(unittest.TestCase):
    def runner(self, codes, calls):
        iterator = iter(codes)

        def run(command, **kwargs):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, next(iterator), stdout="", stderr="")
        return run

    def scan(self, codes, *, status=None, targets=("a.zip", "b"), locate=lambda: "MpCmdRun.exe"):
        calls = []
        result = mm.scan_with_defender([Path(t) for t in targets], runner=self.runner(codes, calls), locate=locate, clock=iter(range(100, 200)).__next__,
                                       status=lambda: {"AMServiceEnabled": True, "AntivirusEnabled": True, "AMEngineVersion": "1.2", "AntivirusSignatureVersion": "3.4"} if status is None else status)
        return result, calls

    def test_a_clean_scan_records_exit_codes_versions_time_and_uses_only_read_only_flags(self):
        result, calls = self.scan([0, 0])
        self.assertEqual(result["status"], "clean")
        self.assertEqual(result["exit_codes"], [0, 0])
        self.assertEqual((result["engine_version"], result["signature_version"]), ("1.2", "3.4"))
        self.assertEqual(result["targets"], ["a.zip", "b"])
        self.assertIn("scanned_utc", result)
        self.assertEqual(len(calls), 2)
        for command in calls:
            self.assertEqual(command[:5], ["MpCmdRun.exe", "-Scan", "-ScanType", "3", "-File"])
            self.assertEqual(command[-1], "-DisableRemediation")
            joined = " ".join(command).lower()
            for forbidden in ("-remove", "-restore", "-signatureupdate", "-removedefinitions", "set-mppreference", "add-mppreference", "-reset", "-cancel", "-quarantine"):
                self.assertNotIn(forbidden, joined)

    def test_exit_code_2_means_threats_and_stops_scanning_the_rest(self):
        result, calls = self.scan([2, 0])
        self.assertEqual(result["status"], "threats_found")
        self.assertEqual(len(calls), 1)
        self.assertIn("쓰지 마세요", result["reason"])

    def test_any_other_exit_code_is_a_failed_scan(self):
        result, _ = self.scan([0, 7])
        self.assertEqual((result["status"], result["exit_codes"]), ("scan_failed", [0, 7]))

    def test_a_runner_error_is_a_failed_scan_with_only_the_error_kind(self):
        def runner(*a, **k):
            raise OSError("boom with a path C:/secret/dir")
        result = mm.scan_with_defender([Path("x.zip")], runner=runner, locate=lambda: "MpCmdRun.exe", clock=iter(range(50)).__next__,
                                       status=lambda: {"AMServiceEnabled": True, "AntivirusEnabled": True})
        self.assertEqual(result["status"], "scan_failed")
        self.assertNotIn("secret", json.dumps(result, ensure_ascii=False))

    def test_a_disabled_service_means_not_run_with_the_reason(self):
        result, calls = self.scan([0], status={"AMServiceEnabled": False, "AntivirusEnabled": False, "AMEngineVersion": "0.0.0.0"})
        self.assertEqual(result["status"], "not_run")
        self.assertIn("꺼져", result["reason"])
        self.assertEqual(calls, [])

    def test_no_defender_program_means_not_run(self):
        result, calls = self.scan([0], locate=lambda: None)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("MpCmdRun.exe", result["reason"])
        self.assertEqual(calls, [])

    def test_a_non_windows_pc_means_not_run_without_looking_for_the_program(self):
        with mock.patch.object(mm.sys, "platform", "linux"):
            result = mm.scan_with_defender([Path("x.zip")], runner=lambda *a, **k: self.fail("실행하면 안 된다"))
        self.assertEqual(result["status"], "not_run")

    def test_find_defender_prefers_the_path_then_the_newest_platform_folder_then_program_files(self):
        self.assertEqual(mm.find_defender(which=lambda name: "C:/x/MpCmdRun.exe"), "C:/x/MpCmdRun.exe")
        environ = {"ProgramData": "PD", "ProgramFiles": "PF"}
        existing = {os.path.join("PD", "Microsoft", "Windows Defender", "Platform", "4.18.2", "MpCmdRun.exe"), os.path.join("PF", "Windows Defender", "MpCmdRun.exe")}
        found = mm.find_defender(which=lambda name: None, environ=environ, exists=existing.__contains__, listing=lambda path: ["4.18.1", "4.18.2"])
        self.assertTrue(found.endswith(os.path.join("4.18.2", "MpCmdRun.exe")))
        found = mm.find_defender(which=lambda name: None, environ=environ, exists={os.path.join("PF", "Windows Defender", "MpCmdRun.exe")}.__contains__, listing=lambda path: [])
        self.assertTrue(found.endswith("MpCmdRun.exe") and "Platform" not in found)
        self.assertIsNone(mm.find_defender(which=lambda name: None, environ={}, exists=lambda path: True, listing=lambda path: []))

    def test_defender_status_reads_json_and_gives_up_quietly(self):
        good = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout='{"AMServiceEnabled": true}', stderr="")      # noqa: E731
        self.assertEqual(mm.defender_status(runner=good), {"AMServiceEnabled": True})
        for output in ("", "not json", "[1,2]"):
            runner = lambda *a, _o=output, **k: subprocess.CompletedProcess(a, 0, stdout=_o, stderr="")      # noqa: E731
            self.assertEqual(mm.defender_status(runner=runner), {}, output)
        failing = lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout='{"x": 1}', stderr="")      # noqa: E731
        self.assertEqual(mm.defender_status(runner=failing), {})

        def broken(*a, **k):
            raise subprocess.TimeoutExpired("powershell", 1)
        self.assertEqual(mm.defender_status(runner=broken), {})

    def test_the_status_query_is_a_read_only_cmdlet(self):
        seen = []
        mm.defender_status(runner=lambda command, **k: (seen.append(command), subprocess.CompletedProcess(command, 0, stdout="{}", stderr=""))[1])
        text = " ".join(seen[0])
        self.assertIn("Get-MpComputerStatus", text)
        self.assertNotIn("Set-", text)
        self.assertNotIn("Add-", text)

    def test_malware_text_is_honest_for_every_status(self):
        self.assertIn("검사 안 함", mm.malware_text(None))
        self.assertTrue(mm.malware_text({"status": "not_run", "reason": "서비스가 꺼져 있어요"}).startswith("검사 안 함 — 서비스가 꺼져 있어요"))
        clean = mm.malware_text({"status": "clean", "tool": "T", "reason": "위협이 발견되지 않았어요.", "targets": ["a.zip"], "exit_codes": [0], "engine_version": "1.2", "signature_version": "3.4", "scanned_utc": "2026-11-11T01:00:00Z", "seconds": 5.5})
        for word in ("위협이 발견되지 않았어요", "a.zip", "종료 코드: 0", "엔진 1.2", "서명 정의 3.4", "2026-11-11T01:00:00Z", "5.5초"):
            self.assertIn(word, clean)
        self.assertIn("쓰지 마세요", mm.malware_text({"status": "threats_found", "reason": "위협이 발견됐다고 보고했어요 — 이 묶음을 쓰지 마세요.", "targets": [], "exit_codes": [2]}))


class InfoTest(unittest.TestCase):
    def test_inner_has_no_clock_hash_of_the_zip_scan_selftest_or_host(self):
        info = sample_info("inner")
        for key in ("package", "malware_scan", "built_utc", "selftest", "host", "release_eligible"):
            self.assertNotIn(key, info)
        text = mm.render_json(info)
        self.assertNotIn("2026-11-11T02:00:00Z", text)
        self.assertEqual(info["variant"], "inner")

    def test_outer_adds_the_zip_the_scan_the_time_the_selftest_and_the_host(self):
        info = sample_info("outer", scan={"status": "clean"})
        self.assertEqual(info["package"], {"name": pc.zip_name(ps.VERSION), "sha256": "f" * 64, "bytes": 12345})
        self.assertEqual(info["built_utc"], "2026-11-11T02:00:00Z")
        self.assertEqual(info["malware_scan"], {"status": "clean"})
        self.assertEqual(info["host"], {"python": "3.12.10"})
        self.assertTrue(info["release_eligible"])

    def test_release_eligible_needs_the_gate_and_no_failed_check(self):
        self.assertTrue(sample_info("outer", gate=True)["release_eligible"])
        self.assertFalse(sample_info("outer", gate=False)["release_eligible"])
        self.assertFalse(sample_info("outer", gate=True, failed=("qt_screens",))["release_eligible"])

    def test_the_trial_flag_is_in_both_copies_and_a_trial_build_is_never_release_eligible(self):
        for variant in ("inner", "outer"):
            with self.subTest(variant=variant):
                self.assertIs(sample_info(variant)["trial"], False)
                self.assertIs(sample_info(variant, trial=True)["trial"], True)
                self.assertIs(json.loads(mm.render_json(sample_info(variant, trial=True)))["trial"], True)
        self.assertFalse(sample_info("outer", gate=True, trial=True)["release_eligible"])
        self.assertTrue(sample_info("outer", gate=True, trial=False)["release_eligible"])

    def test_a_bad_variant_is_refused(self):
        with self.assertRaises(ValueError):
            sample_info("middle")

    def test_the_common_fields_are_the_eight_things_the_operator_asked_for(self):
        info = sample_info("inner")
        self.assertEqual((info["schema"], info["product"], info["channel"], info["notice"], info["version"]), (1, "ChanceBlog Desktop", "personal-pc-preview", pc.NOTICE_LONG, ps.VERSION))
        self.assertEqual(set(info["git"]), {"repository", "commit", "tree", "clean", "committed_utc"})
        self.assertEqual(info["git"]["commit"], ps.FAKE_COMMIT)
        self.assertEqual(set(info["dependencies"]), {"python", "lock_file", "lock_sha256", "wheel_hashes_in_lock", "packages"})
        self.assertFalse(info["dependencies"]["wheel_hashes_in_lock"])
        self.assertEqual(set(info["build"]), {"tool", "command", "env", "zlib", "gate_override"})
        self.assertEqual(set(info["signing"]), {"signed", "exe", "summary", "signed_third_party_binaries"})
        self.assertIn("SmartScreen", info["smartscreen"])
        self.assertEqual(info["file_count"], len(info["files"]))

    def test_the_json_is_utf8_with_lf_ends_and_round_trips(self):
        text = mm.render_json(sample_info("outer"))
        self.assertTrue(text.endswith("\n"))
        self.assertNotIn("\r", text)
        self.assertEqual(json.loads(text)["notice"], pc.NOTICE_LONG)
        self.assertEqual(mm.render_json(sample_info("outer")), text)

    def test_wheel_hashes_in_the_lock_are_reported(self):
        lock = "# [runtime]\nfoo==1.0 " + chr(92) + "\n  --hash=sha256:" + "a" * 64 + "\n"
        requirements = mm.parse_requirements(lock)
        info = mm.build_info(variant="inner", version=ps.VERSION, git={"commit": ps.FAKE_COMMIT, "tree": ps.FAKE_TREE, "clean": True, "committed_utc": "x"}, requirements=requirements,
                             python_version="3.12.10", lock_sha256="0" * 64, build={}, dependencies=[], files={}, signing={})
        self.assertTrue(info["dependencies"]["wheel_hashes_in_lock"])


class MarkdownTest(unittest.TestCase):
    def render(self, variant="outer", **kwargs):
        return mm.render_markdown(sample_info(variant, **kwargs))

    def test_the_first_line_is_the_bold_limited_unsigned_notice_for_both_variants(self):
        for variant in ("inner", "outer"):
            with self.subTest(variant=variant):
                self.assertEqual(self.render(variant).splitlines()[0], FIRST_LINE)

    def test_the_eight_sections_are_there_in_order(self):
        text = self.render(scan={"status": "not_run", "reason": "서비스가 꺼져 있어요"})
        headings = ["## 1. Version", "## 2. Git Commit", "## 3. SHA-256", "## 4. Dependency 목록", "## 5. Build 방법", "## 6. Malware 검사 결과", "## 7. 서명 여부", "## 8. SmartScreen 예상 동작"]
        positions = [text.index(item) for item in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("## 확인하지 못한 것·한계", text)

    def test_each_of_the_eight_things_carries_its_facts(self):
        text = self.render(scan={"status": "not_run", "reason": "서비스가 꺼져 있어요"})
        for needle in (ps.VERSION, ps.FAKE_COMMIT, ps.FAKE_TREE, "깨끗함", "f" * 64, "12,345 바이트", "Get-FileHash", "SHA256SUMS", "PySide6_Essentials==6.12.0", "shiboken6==6.12.0", "pyinstaller==6.22.3",
                       "python packaging/build_package.py", "python -m pip install -r packaging/requirements-package.txt", "검사 안 함 — 서비스가 꺼져 있어요", "미서명", "unsigned", "Authenticode",
                       "SmartScreen", "추가 정보", "실행", "스마트 앱 컨트롤", "Smart App Control", "확인하지 못했습니다"):
            self.assertIn(needle, text, needle)

    def test_the_trial_banner_shows_only_when_the_build_is_not_release_eligible(self):
        self.assertIn("시험 빌드입니다", self.render(gate=False))
        self.assertIn("시험 빌드입니다", self.render(failed=("x",)))
        self.assertNotIn("시험 빌드입니다", self.render(gate=True))
        self.assertIn("외부 쓰기 관문(capabilities) 없이 만든 시험 빌드인가: 예", self.render(gate=False))
        self.assertIn("외부 쓰기 관문(capabilities) 없이 만든 시험 빌드인가: 아니요", self.render(gate=True))

    def test_a_trial_build_says_so_at_the_top_of_both_copies_and_names_the_option_in_the_build_method(self):
        for variant in ("inner", "outer"):
            with self.subTest(variant=variant):
                lines = self.render(variant, gate=False, trial=True).splitlines()
                self.assertEqual(lines[0], FIRST_LINE)
                banner = [line for line in lines[:12] if line.startswith("**이 빌드는 시험 빌드(TESTBUILD)입니다")]
                self.assertEqual(len(banner), 1)
                self.assertIn("개인 PC 로 보내지 않습니다", banner[0])
                text = "\n".join(lines)
                self.assertIn("python packaging/build_package.py --allow-missing-gate", text)
                self.assertIn("압축 파일 이름에도 TESTBUILD", text)
                normal = self.render(variant, gate=True)
                self.assertNotIn("TESTBUILD", normal)
                self.assertNotIn("--allow-missing-gate", normal)

    def test_the_selftest_line_counts_the_waived_gate_failure_instead_of_hiding_it(self):
        waived = self.render("outer", gate=False, trial=True)
        self.assertIn("실패 0 · 건너뜀 0 · 허용된 관문 실패 1", waived)
        self.assertNotIn("허용된 관문 실패", self.render("outer", gate=True))

    def test_how_to_build_and_the_limits_say_the_things_the_independent_check_found(self):
        self.assertIn("저장소 밖", mm.HOW_TO_BUILD[0])
        self.assertIn("무시하는 파일", mm.HOW_TO_BUILD[2])
        limits = " ".join(mm.LIMITS)
        for needle in ("DLL", "PATH", "거절", "같은 곳"):
            self.assertIn(needle, limits)
        self.assertNotIn("같은 도구 버전·같은 Python 이면 같은 압축 파일", limits)               # 빌드 PC 의 PATH 에 달려 있던 옛 과장 문장

    def test_the_inner_copy_points_at_the_files_beside_the_zip_instead_of_writing_what_it_cannot_know(self):
        text = self.render("inner")
        self.assertIn("압축 파일 옆의 `SHA256SUMS`", text)
        self.assertIn("압축 파일 옆의 `PACKAGE_INFO.md`", text)
        self.assertNotIn("Get-FileHash", text)
        self.assertNotIn("f" * 64, text)

    def test_a_clean_scan_needs_no_manual_scan_hint_but_anything_else_asks_for_one(self):
        self.assertNotIn("직접 검사", self.render(scan={"status": "clean", "tool": "T", "reason": "위협이 발견되지 않았어요.", "targets": ["a"], "exit_codes": [0]}))
        for scan in (None, {"status": "not_run", "reason": "x"}, {"status": "scan_failed", "reason": "y", "targets": [], "exit_codes": [1]}):
            self.assertIn("직접 검사", self.render(scan=scan))

    def test_a_signed_exe_is_not_called_unsigned(self):
        text = self.render(signed=True)
        self.assertIn("서명 있음", text)

    def test_no_tilde_and_no_address_link_in_either_copy(self):
        for variant in ("inner", "outer"):
            for scan in (None, {"status": "clean", "tool": "Microsoft Defender (MpCmdRun.exe)", "reason": "위협이 발견되지 않았어요.", "targets": ["a.zip"], "exit_codes": [0]}):
                text = self.render(variant, scan=scan)
                self.assertNotIn(TILDE, text)
                self.assertIsNone(URL.search(text))

    def test_the_important_file_table_lists_only_files_that_exist(self):
        text = self.render(files={"VERSION": "b" * 64})
        self.assertIn("`VERSION`", text)
        self.assertNotIn(f"`{pc.EXE_NAME}.exe`", text.split("## 4.")[0])

    def test_the_fixed_texts_say_what_the_operator_must_be_told(self):
        for needle in ("추가 정보", "실행", "스마트 앱 컨트롤", "설정을 바꾸는 것은 이 묶음이 권하지 않으며"):
            self.assertIn(needle, mm.SMARTSCREEN_TEXT)
        self.assertIn("미서명", mm.SIGNING_TEXT)
        self.assertGreaterEqual(len(mm.LIMITS), 5)
        self.assertEqual(len(mm.HOW_TO_BUILD), 5)


class SumsAndWritingTest(unittest.TestCase):
    def test_sha256sums_is_the_sha256sum_check_format_sorted_with_lf(self):
        text = mm.render_sums([("b.zip", "b" * 64), ("a.zip", "a" * 64)])
        self.assertEqual(text, f"{'a' * 64}  a.zip\n{'b' * 64}  b.zip\n")
        for line in text.splitlines():
            self.assertRegex(line, r"^[0-9a-f]{64}  [^ ]+$")

    def test_write_inner_and_outer_create_the_expected_files_in_utf8_without_bom_or_cr(self):
        with ps.temp_dir() as tmp:
            bundle, out = Path(tmp) / "bundle", Path(tmp) / "out"
            bundle.mkdir()
            mm.write_inner(bundle, sample_info("inner"))
            self.assertEqual(sorted(path.name for path in bundle.iterdir()), ["PACKAGE_INFO.json", "PACKAGE_INFO.md"])
            zip_path = Path(tmp) / pc.zip_name(ps.VERSION)
            mm.write_outer(out, sample_info("outer"), zip_path)
            self.assertEqual(sorted(path.name for path in out.iterdir()), ["PACKAGE_INFO.json", "PACKAGE_INFO.md", "SHA256SUMS"])
            for path in list(bundle.iterdir()) + list(out.iterdir()):
                data = path.read_bytes()
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"), path.name)
                self.assertNotIn(b"\r", data, path.name)
                data.decode("utf-8")
            self.assertEqual((out / "SHA256SUMS").read_text(encoding="utf-8"), f"{'f' * 64}  {pc.zip_name(ps.VERSION)}\n")
            self.assertEqual(json.loads((out / "PACKAGE_INFO.json").read_text(encoding="utf-8"))["package"]["sha256"], "f" * 64)


@unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
class GatherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = ps.make_build_repo(root / "repo")
        self.bundle = ps.fake_dist_dir(root / "bundle")
        ps.write(self.bundle / "VERSION", ps.VERSION + "\n")
        self.common = dict(repo=self.repo, bundle=self.bundle, version=ps.VERSION, lookup=ps.fake_lookup(), distribution=ps.fake_distribution_factory(root / "dists"),
                           build=mm.default_build_record(["python"], tool="PyInstaller 6.22.3", env={}))

    def test_inner_is_byte_identical_for_the_same_input_whatever_the_clock(self):
        first = mm.render_json(mm.gather(variant="inner", clock=lambda: 1.0, **self.common))
        second = mm.render_json(mm.gather(variant="inner", clock=lambda: 99999.0, **self.common))
        self.assertEqual(first, second)

    def test_outer_differs_only_by_the_clock_for_the_same_input(self):
        package = {"name": "z.zip", "sha256": "1" * 64, "bytes": 1}
        selftest = {"passed": [], "failed": [], "skipped": [], "gate_present": True}
        first = mm.gather(variant="outer", clock=lambda: 1_700_000_000.0, package=package, selftest=selftest, **self.common)
        second = mm.gather(variant="outer", clock=lambda: 1_700_000_100.0, package=package, selftest=selftest, **self.common)
        self.assertNotEqual(first["built_utc"], second["built_utc"])
        first["built_utc"] = second["built_utc"]
        self.assertEqual(first, second)

    def test_the_info_names_the_head_commit_and_the_lock_hash_ignores_line_endings(self):
        info = mm.gather(variant="inner", **self.common)
        self.assertEqual(info["git"]["commit"], ps.git(self.repo, "rev-parse", "HEAD"))
        lock = (self.repo / "packaging" / "requirements-package.txt").read_bytes()
        lf = lock.replace(b"\r\n", b"\n")                                         # 윈도 새 체크아웃(core.autocrlf=true)은 이미 CRLF 다 — 먼저 LF 로 맞춰야 \r\r\n 이 안 생긴다(D5)
        self.assertEqual(info["dependencies"]["lock_sha256"], pc.sha256_bytes(lf))
        crlf = lf.replace(b"\n", b"\r\n")
        self.assertNotIn(b"\r\r", crlf)
        (self.repo / "packaging" / "requirements-package.txt").write_bytes(crlf)
        ps.git(self.repo, "-c", "core.autocrlf=false", "commit", "-qam", "crlf")
        again = mm.gather(variant="inner", **self.common)
        self.assertEqual(again["dependencies"]["lock_sha256"], info["dependencies"]["lock_sha256"])

    def test_a_dirty_tree_is_refused(self):
        ps.write(self.repo / "stray.txt", "x")
        with self.assertRaises(mm.BuildRefused):
            mm.gather(variant="inner", **self.common)

    def test_a_tool_that_differs_from_the_lock_is_refused(self):
        wrong = dict(ps.lock_versions(), pyinstaller="0.0.1")
        with self.assertRaises(mm.BuildRefused):
            mm.gather(variant="inner", **{**self.common, "lookup": ps.fake_lookup(wrong)})

    def test_the_file_list_covers_the_bundle_without_the_info_files_and_the_exe_is_unsigned(self):
        info = mm.gather(variant="inner", **self.common)
        self.assertIn(f"{pc.EXE_NAME}.exe", info["files"])
        self.assertIn("VERSION", info["files"])
        self.assertNotIn("PACKAGE_INFO.json", info["files"])
        self.assertEqual(info["signing"]["exe"], "unsigned")
        self.assertEqual(info["file_count"], len(info["files"]))


class CliTest(unittest.TestCase):
    def test_outer_needs_zip_and_out(self):
        with ps.temp_dir() as tmp:
            with mock.patch.object(sys, "stderr", new=mock.MagicMock()):
                self.assertEqual(mm.main(["outer", "--bundle", tmp, "--repo", tmp]), 2)

    def test_a_missing_version_file_is_refused(self):
        with ps.temp_dir() as tmp:
            ps.write(Path(tmp) / "VERSION", "not a version\n")
            with mock.patch.object(sys, "stderr", new=mock.MagicMock()):
                self.assertEqual(mm.main(["inner", "--bundle", tmp, "--repo", tmp]), 2)

    @unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
    def test_a_dirty_repository_is_refused_before_anything_is_written(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp) / "repo"
            ps.init_repo(repo, {"VERSION": ps.VERSION + "\n", "packaging/requirements-package.txt": (ps.PACKAGING / "requirements-package.txt").read_text(encoding="utf-8")})
            ps.write(repo / "stray.txt", "x")
            bundle = Path(tmp) / "bundle"
            bundle.mkdir()
            with mock.patch.object(sys, "stderr", new=mock.MagicMock()):
                self.assertEqual(mm.main(["inner", "--bundle", str(bundle), "--repo", str(repo)]), 2)
            self.assertEqual(list(bundle.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
