"""Package 빌드 도구(`packaging/build_package.py`) 시험 — PyInstaller 자리에 가짜 단계를 끼워, 순서·거절·결정적 zip·자가 점검 판정·산출물 구성을 CI(PyInstaller 없음)에서 확인한다.
진짜 빌드(PyInstaller)는 개발 PC 에서 돌려 결과를 작업 보고서에 남긴다. 네트워크·진짜 Windows Defender·진짜 자격 증명 관리자는 쓰지 않는다.
"""
import ast
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import unittest
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest import mock

import packaging_support as ps
from chanceblog_desktop.ui.core import version as app_version

bp = ps.build_package
mm = ps.make_manifest
pc = ps.pkgcommon
KEY_SAMPLE = "AI" + "za" + "A" * 35                                   # 구글 키 모양의 가짜 값(런타임에 조립 — 저장소에 키 문자열이 없다)


class ZipDateTest(unittest.TestCase):
    def test_commit_time_becomes_an_even_second_dos_time_in_utc(self):
        self.assertEqual(bp.zip_date_time(ps.COMMIT_EPOCH), (2026, 11, 11, 1, 0, 0))
        self.assertEqual(bp.zip_date_time(ps.COMMIT_EPOCH + 1), (2026, 11, 11, 1, 0, 0))
        self.assertEqual(bp.zip_date_time(ps.COMMIT_EPOCH + 3), (2026, 11, 11, 1, 0, 2))

    def test_times_before_1980_are_clamped(self):
        self.assertEqual(bp.zip_date_time(0), (1980, 1, 1, 0, 0, 0))
        self.assertEqual(bp.zip_date_time(315532800 - 1), (1980, 1, 1, 0, 0, 0))
        self.assertEqual(bp.zip_date_time(315532800), (1980, 1, 1, 0, 0, 0))

    def test_the_result_is_always_a_valid_zip_time(self):
        for epoch in (ps.COMMIT_EPOCH, ps.COMMIT_EPOCH + 59, 1_900_000_001, 4_000_000_000):
            year, month, day, hour, minute, second = bp.zip_date_time(epoch)
            self.assertTrue(1980 <= year <= 2107 and 1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60 and second < 60 and second % 2 == 0)


class VersionFileTest(unittest.TestCase):
    class Stub:
        """PyInstaller 의 버전 정보 만들개를 흉내 — 같은 이름으로 호출하면 (이름, 인자)를 돌려준다."""

        def __init__(self, name):
            self.name = name

        def __call__(self, *args, **kwargs):
            return (self.name, args, kwargs)

    def evaluate(self, text):
        names = ("VSVersionInfo", "FixedFileInfo", "StringFileInfo", "StringTable", "StringStruct", "VarFileInfo", "VarStruct")
        return eval(text, {name: self.Stub(name) for name in names})            # noqa: S307 - 이 파일이 만든 글만 평가한다

    def test_the_text_is_a_single_constructor_call_with_the_numbers_and_strings(self):
        result = self.evaluate(bp.version_file_text("0.1.0-preview.1"))
        self.assertEqual(result[0], "VSVersionInfo")
        fixed = result[2]["ffi"][2]
        self.assertEqual((fixed["filevers"], fixed["prodvers"]), ((0, 1, 0, 0), (0, 1, 0, 0)))
        self.assertEqual(fixed["flags"], 0xA)                                      # 시험판(PRERELEASE) + 개인 빌드(PRIVATEBUILD)
        table = result[2]["kids"][0][1][0][0][1][1]                                # StringFileInfo([StringTable(lang, [StringStruct…])])
        strings = {entry[1][0]: entry[1][1] for entry in table}
        self.assertEqual(strings["ProductName"], "ChanceBlog Desktop")
        self.assertEqual((strings["FileVersion"], strings["ProductVersion"]), ("0.1.0-preview.1", "0.1.0-preview.1"))
        self.assertEqual((strings["InternalName"], strings["OriginalFilename"]), ("ChanceBlogDesktop", "ChanceBlogDesktop.exe"))
        self.assertIn(pc.NOTICE, strings["FileDescription"])

    def test_a_trial_build_says_so_in_the_file_description_and_a_normal_one_does_not(self):
        strings = {}
        for trial in (False, True):
            table = self.evaluate(bp.version_file_text("0.1.0-preview.1", trial))[2]["kids"][0][1][0][0][1][1]
            strings[trial] = {entry[1][0]: entry[1][1] for entry in table}["FileDescription"]
        self.assertNotIn("시험 빌드", strings[False])
        self.assertIn("시험 빌드 TESTBUILD", strings[True])
        self.assertIn(pc.NOTICE, strings[True])
        self.assertEqual(bp.version_file_text("0.1.0-preview.1"), bp.version_file_text("0.1.0-preview.1", False))

    def test_the_numbers_follow_the_version_for_other_shapes(self):
        for version, expected in (("1.2.3", (1, 2, 3, 0)), ("10.20.30+4", (10, 20, 30, 0)), ("0.1.0-beta.2", (0, 1, 0, 0))):
            result = self.evaluate(bp.version_file_text(version))
            self.assertEqual(result[2]["ffi"][2]["filevers"], expected, version)

    def test_the_text_is_ascii_safe_to_save_in_utf8_and_has_no_tilde_or_link(self):
        text = bp.version_file_text("0.1.0-preview.1")
        text.encode("utf-8")
        self.assertNotIn(chr(0x7E), text)
        self.assertNotRegex(text, r"(?i)https?://")


class HiddenImportsTest(unittest.TestCase):
    def test_vendor_standard_modules_are_listed_sorted_and_third_party_ones_are_not(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp)
            ps.write(repo / "vendor" / "pipeline" / "a.py", "import json, requests\nfrom urllib.request import urlopen\n")
            ps.write(repo / "vendor" / "scripts" / "b.py", "import re\nimport yaml\ndef f():\n    import html.parser\n")
            ps.write(repo / "vendor" / "VENDOR.json", "{}")
            self.assertEqual(bp.hidden_imports(repo), ["html.parser", "json", "re", "urllib.request"])

    def test_the_capabilities_module_is_added_only_when_the_source_has_it(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp)
            ps.write(repo / "vendor" / "a.py", "import os\n")
            self.assertNotIn("chanceblog_desktop.capabilities", bp.hidden_imports(repo))
            ps.write(repo / "src" / "chanceblog_desktop" / "capabilities.py", "EXTERNAL_WRITE = False\n")
            self.assertIn("chanceblog_desktop.capabilities", bp.hidden_imports(repo))

    def test_the_real_vendor_files_yield_the_modules_the_trial_build_needed(self):
        names = bp.hidden_imports(ps.ROOT)
        for needed in ("json", "re", "urllib.request", "http.client"):
            self.assertIn(needed, names)
        self.assertEqual(names, sorted(set(names)))


class PyInstallerArgsTest(unittest.TestCase):
    def args(self, imports=("json",)):
        return bp.pyinstaller_args(Path("R"), Path("O"), Path("O/v.txt"), imports)

    def test_one_folder_windowed_clean_utf8_and_the_gui_only_entry_last(self):
        args = self.args()
        for flag in ("--noconfirm", "--clean", "--onedir", "--windowed"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--name") + 1], "ChanceBlogDesktop")
        index = args.index("--python-option")
        self.assertEqual(args[index + 1], "X utf8")
        self.assertEqual(args[args.index("--version-file") + 1], str(Path("O/v.txt")))
        self.assertEqual(args[args.index("--paths") + 1], str(Path("R") / "src"))
        self.assertEqual(args[-1], str(Path("R") / "packaging" / "gui_entry.py"))
        for folder in ("--distpath", "--workpath", "--specpath"):
            self.assertTrue(args[args.index(folder) + 1].startswith("O"), folder)

    def test_the_qt_network_module_is_excluded_so_no_openssl_is_collected_from_the_path(self):
        args = self.args(("json", "re"))
        pairs = [(args[index], args[index + 1]) for index in range(len(args) - 1) if args[index] == "--exclude-module"]
        self.assertEqual(pairs, [("--exclude-module", "PySide6.QtNetwork")])
        self.assertEqual(bp.EXCLUDED_MODULES, ("PySide6.QtNetwork",))
        self.assertLess(args.index("--exclude-module"), args.index("--hidden-import"))
        self.assertNotIn("PySide6.QtNetwork", [args[index + 1] for index in range(len(args) - 1) if args[index] == "--hidden-import"])
        self.assertEqual(args[-1], str(Path("R") / "packaging" / "gui_entry.py"))

    def test_the_app_never_imports_qt_network_so_excluding_it_cannot_break_the_screens(self):
        found = []
        for source in sorted((ps.ROOT / "src").rglob("*.py")) + [ps.PACKAGING / "gui_entry.py"]:
            if "QtNetwork" in source.read_text(encoding="utf-8"):
                found.append(source.name)
        self.assertEqual(found, [])

    def test_no_option_that_changes_the_privilege_or_the_shape_is_used(self):
        args = self.args()
        for flag in ("--onefile", "-F", "--uac-admin", "--uac-uiaccess", "--debug", "-d", "--console", "-c", "--runtime-tmpdir", "--upx-dir", "--strip", "--key", "--hide-console"):
            self.assertNotIn(flag, args)
        self.assertNotIn("hash_seed=0", args)                                       # 앱이 실행할 때의 해시 무작위화는 끄지 않는다(빌드 쪽 환경 변수만 쓴다)

    def test_every_hidden_import_follows_its_flag_in_the_given_order(self):
        args = self.args(("a.b", "c", "d"))
        pairs = [(args[i], args[i + 1]) for i in range(len(args) - 1) if args[i] == "--hidden-import"]
        self.assertEqual([value for _flag, value in pairs], ["a.b", "c", "d"])
        self.assertEqual(self.args(("a.b", "c", "d")), args)

    def test_the_recorded_command_swaps_this_pcs_paths_for_placeholders_and_uses_forward_slashes(self):
        repo, out = Path("C:/Users/x/repo"), Path("C:/Users/x/repo/dist/package")
        args = bp.pyinstaller_args(repo, out, out / "version_info.txt", ("json",))
        shown = bp.recorded_command(args, repo, out)
        text = " ".join(shown)
        self.assertEqual(shown[:3], ["python", "-m", "PyInstaller"])
        self.assertNotIn("Users", text)
        self.assertNotIn("C:", text)
        self.assertNotIn(chr(92), text)
        self.assertIn("<출력>/dist", text)
        self.assertIn("<저장소>/packaging/gui_entry.py", text)
        self.assertIn("<저장소>/src", text)

    def test_the_build_environment_is_deterministic_and_clean(self):
        before = {"PATH": "p", "PYTHONPATH": "x", "PYTHONHOME": "h", "PYTHONSTARTUP": "s", "PYTHONOPTIMIZE": "2", "PYTHONINSPECT": "1", "KEEP": "1"}
        env = bp.pyinstaller_env(1794361921, before, prefix="C:/ccgui/v", base_prefix="C:/ccgui/base", isdir=lambda folder: True)
        self.assertEqual(env["PYTHONHASHSEED"], "0")
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(env["SOURCE_DATE_EPOCH"], "1794361921")
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONOPTIMIZE", "PYTHONINSPECT"):
            self.assertNotIn(name, env)
        self.assertEqual(env["KEEP"], "1")
        self.assertNotEqual(env["PATH"], "p")                                        # PATH 는 좁힌 것으로 바뀐다(D-468 — 자세한 시험은 test_packaging_path.py)
        self.assertEqual(env["PATH"].split(";")[0], str(PureWindowsPath("C:/ccgui/v")))
        self.assertEqual(before["PATH"], "p")
        self.assertIn("PYTHONPATH", before)                                          # 받은 사전은 바꾸지 않는다
        self.assertEqual(bp.bundle_environment_record(5), {"PYTHONHASHSEED": "0", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "SOURCE_DATE_EPOCH": "5", "PATH_POLICY": "narrow-v1"})


class OutDirTest(unittest.TestCase):
    def test_the_repository_its_parents_and_the_drive_root_are_refused(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            for bad in (repo, repo.parent, Path(repo.anchor)):
                with self.subTest(bad=str(bad)):
                    with self.assertRaises(mm.BuildRefused):
                        bp.safe_out_dir(bad, repo)
            self.assertEqual(bp.safe_out_dir(repo / "dist" / "package", repo, ignores=lambda r, p: True), (repo / "dist" / "package").resolve())
            self.assertEqual(bp.safe_out_dir(Path(tmp) / "elsewhere", repo), (Path(tmp) / "elsewhere").resolve())

    def test_names_that_windows_changes_silently_or_cannot_make_are_refused_with_a_sentence(self):
        bad = {
            "trailing space": "C:/x/src /out", "trailing dot": "C:/x/src./out", "last part trailing space": "C:/x/out ", "two spaces": "C:/x/src  /out", "space dot space": "C:/x/src . /out",
            "quote": 'C:/x/a"b', "pipe": "C:/x/a|b", "star": "C:/x/a*b", "question": "C:/x/a?b", "less": "C:/x/a<b", "greater": "C:/x/a>b", "tab": "C:/x/a\tb", "colon": "C:/x/a:b", "newline": "C:/x/a\nb",
            "CON": "C:/x/CON", "con lower": "C:/x/con", "aux with extension": "C:/x/aux.txt", "nul": "C:/x/NUL", "con space before the extension": "C:/x/CON .txt", "com1": "C:/x/COM1", "com9": "C:/x/COM9", "lpt1": "C:/x/LPT1", "lpt9": "C:/x/lpt9.log", "device in the middle": "C:/x/prn/out",
        }
        for label, text in bad.items():
            with self.subTest(label=label):
                self.assertTrue(bp.out_path_problem(text), text)
        good = ("C:/x/out", "C:/x/내 폴더/출력 (1)", "C:/x/$(calc)", "C:/x/%TEMP%", "C:/x/a&b^c!d", "C:/x/it's", "C:/x/x..y", "C:/x/a.b.c", "C:/x/tmp/a/../o", "C:/x/console", "C:/x/com0", "C:/x/com10",
                "C:/x/lpt", "C:/x/c;d", "dist/package", "..", ".", "D:/", "C:/x/" + chr(0x3000), "//server/share/out")
        for text in good:
            with self.subTest(good=text):
                self.assertEqual(bp.out_path_problem(text), "", text)

    def test_the_sentence_names_the_bad_part_of_the_path(self):
        self.assertIn("'src '", bp.out_path_problem("C:/x/src /out"))
        self.assertIn("공백이나 점으로 끝나요", bp.out_path_problem("C:/x/src /out"))
        self.assertIn("쓸 수 없는 글자", bp.out_path_problem('C:/x/a"b'))
        self.assertIn("예약 이름", bp.out_path_problem("C:/x/con"))
        self.assertIn("'a\\tb'", bp.out_path_problem("C:/x/a\tb"))                          # 제어 문자는 글자 그대로가 아니라 이스케이프로 보여 준다

    def test_a_trailing_space_cannot_slip_an_output_folder_into_an_input_folder(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            for relative in ("src /out", "packaging /x", "vendor /x", ".git /x", "src  /out", "src . /out", "src./out"):
                with self.subTest(relative=relative):
                    with self.assertRaises(mm.BuildRefused) as caught:
                        bp.safe_out_dir(repo / relative, repo, ignores=lambda root, path: True)
                    self.assertIn("공백이나 점으로 끝나요", str(caught.exception))
            self.assertEqual(list(repo.iterdir()), [])                                       # 아무것도 만들지 않는다

    def test_a_path_the_operating_system_cannot_read_is_refused_with_a_sentence_not_a_traceback(self):
        with ps.temp_dir() as tmp:
            for error in (OSError("boom"), ValueError("embedded null byte"), RuntimeError("Symlink loop")):
                with self.subTest(error=type(error).__name__):
                    with mock.patch.object(Path, "resolve", side_effect=error):
                        with self.assertRaises(mm.BuildRefused) as caught:
                            bp.safe_out_dir(Path(tmp) / "x", Path(tmp) / "repo")
                    self.assertIn("읽지 못했어요", str(caught.exception))
                    self.assertIn(type(error).__name__, str(caught.exception))

    def test_a_reserved_or_too_long_output_path_is_refused_before_anything_is_made(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            for name in ("con", "CON", "nul", "Com1", "lpt3", "aux.txt"):
                with self.subTest(name=name):
                    with self.assertRaises(mm.BuildRefused) as caught:
                        bp.safe_out_dir(Path(tmp) / name, repo)
                    self.assertIn("예약 이름", str(caught.exception))
            with self.assertRaises(mm.BuildRefused) as caught:
                bp.safe_out_dir(Path(tmp) / ("x" * 200), repo)
            self.assertIn(f"{bp.OUT_PATH_LIMIT}자를 넘어요", str(caught.exception))
            self.assertEqual(bp.safe_out_dir(Path(tmp) / "short", repo), (Path(tmp) / "short").resolve())
        self.assertLess(bp.OUT_PATH_LIMIT + 1 + 110, 260)                                    # 출력 폴더 아래 가장 긴 경로(약 110자 — 마지막 확인 빌드의 실제 최장 경로로 다시 잰다)가 더해져도 윈도 경로 한계 안이다

    def test_the_extended_path_prefix_is_removed_so_repo_and_output_compare_the_same_way(self):
        back = chr(92)
        cases = ((back * 2 + "?" + back + "C:" + back + "x", "C:" + back + "x"),
                 (back * 2 + "?" + back + "UNC" + back + "srv" + back + "sh" + back + "o", back * 2 + "srv" + back + "sh" + back + "o"),
                 (back * 2 + "?" + back + "unc" + back + "srv" + back + "sh", back * 2 + "srv" + back + "sh"),
                 ("C:" + back + "x", "C:" + back + "x"), (back * 2 + "srv" + back + "sh", back * 2 + "srv" + back + "sh"), ("/tmp/x", "/tmp/x"), ("", ""))
        for before, after in cases:
            with self.subTest(before=before):
                self.assertEqual(bp.plain_text(before), after)
        self.assertEqual(bp.plain_path(Path("x")), Path("x"))

    @unittest.skipUnless(os.name == "nt", "확장 경로 접두어는 윈도에만 있다")
    def test_an_output_path_that_resolves_with_the_extended_prefix_still_cannot_slip_into_an_input_folder(self):
        back = chr(92)
        real = Path.resolve

        def prefixed(self, *args, **kwargs):
            done = real(self, *args, **kwargs)
            return done if self.name == "repo" else Path(back * 2 + "?" + back + str(done))          # 출력 쪽 경로만 접두어가 붙어 돌아온다
        with ps.temp_dir() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            with mock.patch.object(Path, "resolve", prefixed):
                for relative in ("src/out", "packaging/x", ".git/x", "vendor"):
                    with self.subTest(relative=relative):
                        with self.assertRaises(mm.BuildRefused):
                            bp.safe_out_dir(repo / relative, repo, ignores=lambda root, path: True)
                self.assertEqual(bp.safe_out_dir(Path(tmp) / "elsewhere", repo), real(Path(tmp) / "elsewhere"))            # 접두어를 뗀 보통 경로로 돌려준다

    def test_is_root_is_true_only_for_the_top_of_a_drive_or_a_filesystem_whatever_the_path_kind(self):
        for top in (PureWindowsPath("D:/"), PureWindowsPath("C:/"), PurePosixPath("/"), PureWindowsPath("//server/share/")):
            with self.subTest(top=str(top)):
                self.assertTrue(bp.is_root(top))
        for inside in (PureWindowsPath("D:/x"), PurePosixPath("/x"), PureWindowsPath("C:/Users/x/out"), PurePosixPath("/tmp/out")):
            with self.subTest(inside=str(inside)):
                self.assertFalse(bp.is_root(inside))

    @unittest.skipUnless(os.name == "nt", "드라이브 글자는 윈도에만 있다")
    def test_the_top_of_another_drive_is_refused_even_though_it_is_not_a_parent_of_the_repository(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            own = repo.resolve().drive[:1].upper()
            other = next(letter for letter in "ZYXW" if letter != own)
            with self.assertRaises(mm.BuildRefused):
                bp.safe_out_dir(Path(f"{other}:/"), repo)

    def test_inside_the_repository_the_output_folder_must_be_a_git_ignored_place_and_never_an_input_folder_or_dot_git(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            ignores = lambda root, path: "dist" in path.relative_to(root.resolve()).parts          # noqa: E731
            for relative in ("src/out", "vendor", "vendor/pipeline/out", "packaging/out", ".git/out", "src"):
                with self.subTest(relative=relative):
                    with self.assertRaises(mm.BuildRefused):
                        bp.safe_out_dir(repo / relative, repo, ignores=lambda root, path: True)       # 무시되는 곳이라고 해도 입력 폴더·.git 안은 안 된다
            for relative in ("docs/out", "out", "tests/x"):
                with self.subTest(relative=relative):
                    with self.assertRaises(mm.BuildRefused) as caught:
                        bp.safe_out_dir(repo / relative, repo, ignores=ignores)
                    self.assertIn("무시하는 곳이 아니에요", str(caught.exception))
            self.assertEqual(bp.safe_out_dir(repo / "dist" / "package", repo, ignores=ignores), (repo / "dist" / "package").resolve())
            self.assertEqual(bp.safe_out_dir(Path(tmp) / "outside", repo, ignores=lambda root, path: self.fail("저장소 밖은 git 에 묻지 않는다")), (Path(tmp) / "outside").resolve())

    @unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
    def test_git_ignores_follows_the_real_gitignore_even_for_a_folder_that_does_not_exist_yet(self):
        with ps.temp_dir() as tmp:
            repo = Path(tmp) / "repo"
            ps.init_repo(repo, {"a.txt": "a\n"}, ignore="dist/\n")
            self.assertTrue(bp.git_ignores(repo, repo / "dist" / "package"))
            self.assertTrue(bp.git_ignores(repo, repo / "dist"))
            self.assertFalse(bp.git_ignores(repo, repo / "docs"))
            self.assertFalse(bp.git_ignores(repo, repo / "src" / "out"))
            self.assertFalse(bp.git_ignores(repo, Path(tmp) / "elsewhere"))                       # 저장소 밖
            plain = Path(tmp) / "plain"
            plain.mkdir()
            with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(Path(tmp))}):
                self.assertFalse(bp.git_ignores(plain, plain / "dist"))                           # git 저장소가 아니면 무시되는 곳이 아니다

    def test_clean_removes_only_the_five_work_folders_and_keeps_everything_else_in_a_folder_this_tool_made(self):
        with ps.temp_dir() as tmp:
            out = Path(tmp) / "out"
            for name in bp.OUT_SUBFOLDERS:
                ps.write(out / name / "a" / "file.txt", "x")
            ps.write(out / bp.OUT_MARKER, "표지")
            ps.write(out / "keep.txt", "keep")
            ps.write(out / "other" / "keep2.txt", "keep")
            readonly = ps.write(out / "work" / "ro.txt", "ro")
            os.chmod(readonly, stat.S_IREAD)
            bp.clean_out_dir(out)
            self.assertEqual(sorted(path.name for path in out.iterdir()), [bp.OUT_MARKER, "keep.txt", "other"])
            self.assertEqual((out / "other" / "keep2.txt").read_text(encoding="utf-8"), "keep")

    def test_clean_creates_a_missing_out_folder_with_the_marker_and_accepts_an_empty_one(self):
        with ps.temp_dir() as tmp:
            bp.clean_out_dir(Path(tmp) / "new" / "out")
            self.assertTrue((Path(tmp) / "new" / "out" / bp.OUT_MARKER).is_file())
            empty = Path(tmp) / "empty"
            empty.mkdir()
            bp.clean_out_dir(empty)
            self.assertEqual([path.name for path in empty.iterdir()], [bp.OUT_MARKER])
            bp.clean_out_dir(empty)                                                              # 두 번째에는 표지가 있어서 그대로 된다

    def test_a_folder_with_other_files_and_no_marker_is_refused_and_nothing_in_it_is_deleted(self):
        with ps.temp_dir() as tmp:
            out = Path(tmp) / "mine"
            ps.write(out / "release" / "my_document.txt", "내 글")
            ps.write(out / "work" / "notes.txt", "내 메모")
            ps.write(out / "keep.txt", "keep")
            with self.assertRaises(mm.BuildRefused) as caught:
                bp.clean_out_dir(out)
            self.assertIn(bp.OUT_MARKER, str(caught.exception))
            self.assertEqual(sorted(path.name for path in out.iterdir()), ["keep.txt", "release", "work"])
            self.assertEqual((out / "release" / "my_document.txt").read_text(encoding="utf-8"), "내 글")
            self.assertEqual((out / "work" / "notes.txt").read_text(encoding="utf-8"), "내 메모")
            self.assertFalse((out / bp.OUT_MARKER).exists())

    def test_a_file_where_a_work_folder_should_be_is_refused_and_nothing_is_deleted(self):
        with ps.temp_dir() as tmp:
            out = Path(tmp) / "out"
            ps.write(out / bp.OUT_MARKER, "표지")
            ps.write(out / "release", "폴더가 아니라 파일")
            ps.write(out / "work" / "keep.txt", "work 안의 글")
            with self.assertRaises(mm.BuildRefused) as caught:
                bp.clean_out_dir(out)
            self.assertIn("release", str(caught.exception))
            self.assertIn("파일", str(caught.exception))
            self.assertEqual((out / "work" / "keep.txt").read_text(encoding="utf-8"), "work 안의 글")      # 아무것도 지우지 않았다
            self.assertEqual((out / "release").read_text(encoding="utf-8"), "폴더가 아니라 파일")

    def test_an_output_path_that_is_an_existing_file_is_refused_with_a_plain_sentence_not_a_traceback(self):
        with ps.temp_dir() as tmp:
            target = ps.write(Path(tmp) / "afile", "x")
            with self.assertRaises(mm.BuildRefused) as caught:
                bp.clean_out_dir(target)
            self.assertIn("파일", str(caught.exception))
            self.assertEqual(target.read_text(encoding="utf-8"), "x")

    def test_an_unreadable_or_missing_version_file_is_refused_with_a_plain_sentence(self):
        with ps.temp_dir() as tmp:
            with self.assertRaises(mm.BuildRefused) as caught:
                bp.read_version(tmp)
            self.assertIn("VERSION", str(caught.exception))
            ps.write(Path(tmp) / "VERSION", b"\xff\xfe not utf-8", binary=True)
            with self.assertRaises(mm.BuildRefused):
                bp.read_version(tmp)
            (Path(tmp) / "VERSION").unlink()
            (Path(tmp) / "VERSION").mkdir()                                                      # 파일 자리에 폴더
            with self.assertRaises(mm.BuildRefused):
                bp.read_version(tmp)


class VendorAndLicenseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_vendor_is_copied_byte_for_byte_without_caches(self):
        repo = self.root / "repo"
        shutil.copytree(ps.ROOT / "vendor", repo / "vendor")
        ps.write(repo / "vendor" / "pipeline" / "__pycache__" / "x.pyc", b"c", binary=True)
        bundle = self.root / "bundle"
        bundle.mkdir()
        bp.copy_vendor(repo, bundle)
        for path in (ps.ROOT / "vendor").rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                self.assertEqual((bundle / "vendor" / path.relative_to(ps.ROOT / "vendor")).read_bytes(), path.read_bytes(), path.name)
        self.assertFalse((bundle / "vendor" / "pipeline" / "__pycache__").exists())

    def test_a_vendor_file_that_differs_from_vendor_json_is_refused(self):
        repo = self.root / "repo"
        shutil.copytree(ps.ROOT / "vendor", repo / "vendor")
        target = repo / "vendor" / "pipeline" / "gates.py"
        target.write_bytes(target.read_bytes() + b"\n# changed\n")
        bundle = self.root / "bundle"
        bundle.mkdir()
        with self.assertRaises(mm.BuildRefused) as caught:
            bp.copy_vendor(repo, bundle)
        self.assertIn("pipeline/gates.py", str(caught.exception))

    def test_a_missing_vendor_file_is_refused(self):
        repo = self.root / "repo"
        shutil.copytree(ps.ROOT / "vendor", repo / "vendor")
        (repo / "vendor" / "pipeline" / "console.py").unlink()
        bundle = self.root / "bundle"
        bundle.mkdir()
        with self.assertRaises(mm.BuildRefused):
            bp.copy_vendor(repo, bundle)

    def test_the_pyinstaller_license_is_found_in_the_licenses_folder_of_the_distribution(self):
        factory = ps.fake_distribution_factory(self.root / "d")
        found = bp.find_pyinstaller_license(factory)
        self.assertTrue(found.is_file())
        self.assertEqual(found.name, "COPYING.txt")

    def test_a_distribution_without_the_license_is_refused(self):
        class Bare:
            files = [ps.FakePath("pyinstaller-1/METADATA")]
        with self.assertRaises(mm.BuildRefused):
            bp.find_pyinstaller_license(lambda name: Bare())

    def collect(self, repo=None, base_prefix=None):
        repo = repo or ps.ROOT
        bundle = self.root / "bundle"
        bundle.mkdir(exist_ok=True)
        base = base_prefix or ps.write(self.root / "base" / "LICENSE.txt", "PSF text\n").parent
        factory = ps.fake_distribution_factory(self.root / "d")
        deps = mm.dependency_entries(mm.parse_requirements((ps.PACKAGING / "requirements-package.txt").read_text(encoding="utf-8")), distribution=factory)
        bp.collect_licenses(repo, bundle, ps.VERSION, deps, ps.FAKE_COMMIT, distribution=factory, base_prefix=base)
        return bundle / "LICENSES"

    def test_the_licenses_folder_gets_the_five_files_and_the_two_full_texts_are_copied_exactly(self):
        folder = self.collect()
        self.assertEqual(sorted(path.name for path in folder.iterdir()), sorted(pc.LICENSE_FILES))
        for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
            self.assertEqual((folder / name).read_bytes(), (ps.PACKAGING / "LICENSES" / name).read_bytes())
        self.assertEqual((folder / "PYTHON-LICENSE.txt").read_text(encoding="utf-8"), "PSF text\n")
        self.assertEqual((folder / "PYINSTALLER-COPYING.txt").read_text(encoding="utf-8"), "GPL with exception\n")

    def test_a_missing_full_text_in_the_repository_is_refused(self):
        repo = self.root / "repo"
        ps.write(repo / "packaging" / "LICENSES" / "LGPL-3.0.txt", "x")
        with self.assertRaises(mm.BuildRefused) as caught:
            self.collect(repo)
        self.assertIn("GPL-3.0.txt", str(caught.exception))

    def test_a_missing_python_license_is_refused(self):
        with self.assertRaises(mm.BuildRefused):
            self.collect(base_prefix=self.root / "nowhere")

    def test_the_notices_name_the_components_the_lgpl_duties_and_the_limits(self):
        deps = [{"name": "PySide6_Essentials", "version": "6.12.0", "role": "runtime", "license": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"},
                {"name": "shiboken6", "version": "6.12.0", "role": "runtime", "license": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"},
                {"name": "pyinstaller", "version": "6.22.3", "role": "build", "license": "GPL"}]
        text = bp.notices_text(ps.VERSION, deps, ps.FAKE_COMMIT)
        for needle in (pc.NOTICE_LONG, "법률 판단이 아닙니다", "Qt for Python", "6.12.0", "LGPL-3.0", "동적 링크", "바꿔 끼우기", "code.qt.io", "pyside.org", "GPL-3.0.txt", ps.FAKE_COMMIT,
                       "PSF License", "PyInstaller 부트로더", "OpenSSL", "Mesa", "Microsoft Visual C++", "알려진 한계", "D-13", "packaging/LICENSES/SOURCES.txt", "Qt6Network.dll", "qtuiotouchplugin.dll"):
            self.assertIn(needle, text, needle)
        self.assertNotIn(chr(0x7E), text)
        self.assertNotRegex(text, r"(?i)https?://|www[.]")
        self.assertEqual(text, bp.notices_text(ps.VERSION, deps, ps.FAKE_COMMIT))


class BundleProblemsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = ps.fake_dist_dir(Path(self.tmp.name) / "b")
        ps.write(self.bundle / "VERSION", ps.VERSION + "\n")
        for name in ("vendor/VENDOR.json", "vendor/pipeline/gates.py"):
            ps.write(self.bundle / name, "{}")

    def test_a_complete_bundle_has_no_problems(self):
        self.assertEqual(bp.bundle_problems(self.bundle), [])

    def test_each_missing_required_part_is_reported(self):
        cases = [f"{pc.EXE_NAME}.exe", "VERSION", "vendor/VENDOR.json", "vendor/pipeline/gates.py", "_internal/" + ps.PYTHON_DLL, *("_internal/" + name for name in bp.QT_FILES)]
        for relative in cases:
            with self.subTest(relative=relative):
                backup = (self.bundle / relative).read_bytes()
                (self.bundle / relative).unlink()
                try:
                    problems = bp.bundle_problems(self.bundle)
                    self.assertTrue(any(Path(relative).name in item for item in problems), (relative, problems))
                finally:
                    (self.bundle / relative).write_bytes(backup)

    def test_a_missing_internal_folder_is_reported(self):
        shutil.rmtree(self.bundle / "_internal")
        self.assertTrue(any("_internal" in item for item in bp.bundle_problems(self.bundle)))

    def test_user_data_and_secret_file_names_inside_the_bundle_are_refused(self):
        for relative in ("settings.json", "x/connections.json", "a/chanceblog.db", "cacert.pem", ".env", "token.json", "id_rsa"):
            with self.subTest(relative=relative):
                path = ps.write(self.bundle / relative, "x")
                try:
                    self.assertTrue(any(relative in item and "있으면 안 되는" in item for item in bp.bundle_problems(self.bundle)), relative)
                finally:
                    path.unlink()

    def test_code_files_that_only_look_like_secrets_are_not_refused(self):
        ps.write(self.bundle / "vendor" / "pipeline" / "secret_patterns.py", "PATTERNS = []\n")
        ps.write(self.bundle / "_internal" / "tokenizer.py", "x = 1\n")
        self.assertEqual(bp.bundle_problems(self.bundle), [])

    def test_a_key_shaped_text_in_any_text_file_is_refused(self):
        for name in ("notes.txt", "x/data.json", "y/code.py", "z/readme.md"):
            with self.subTest(name=name):
                path = ps.write(self.bundle / name, f"value = {KEY_SAMPLE}\n")
                try:
                    problems = bp.bundle_problems(self.bundle)
                    self.assertTrue(any("키 모양" in item and name in item for item in problems), problems)
                    self.assertNotIn(KEY_SAMPLE, " ".join(problems))
                finally:
                    path.unlink()

    def test_a_text_file_over_the_limit_is_not_read(self):
        path = ps.write(self.bundle / "big.txt", KEY_SAMPLE + " " * (bp.TEXT_SCAN_LIMIT + 10))
        self.assertEqual(bp.bundle_problems(self.bundle), [])
        path.unlink()

    def test_packages_from_the_development_environment_that_leaked_in_are_refused(self):
        for name in bp.UNEXPECTED_BUNDLED:
            with self.subTest(name=name):
                target = self.bundle / "_internal" / name
                (target.parent).mkdir(exist_ok=True)
                target.mkdir() if "." not in name else target.write_bytes(b"x")
                try:
                    self.assertTrue(any(name in item for item in bp.bundle_problems(self.bundle)), name)
                finally:
                    shutil.rmtree(target) if target.is_dir() else target.unlink()


class UnwantedNetworkPartsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = ps.fake_dist_dir(Path(self.tmp.name) / "b")
        ps.write(self.bundle / "VERSION", ps.VERSION + "\n")
        for name in ("vendor/VENDOR.json", "vendor/pipeline/gates.py"):
            ps.write(self.bundle / name, "{}")

    def test_the_openssl_pair_from_the_path_and_the_qt_network_parts_are_refused_each_by_name(self):
        self.assertEqual(set(bp.UNWANTED_BUNDLED), {"libssl-3-x64.dll", "libcrypto-3-x64.dll", "PySide6/QtNetwork.pyd", "PySide6/plugins/tls", "PySide6/plugins/networkinformation"})
        for name in bp.UNWANTED_BUNDLED:
            with self.subTest(name=name):
                target = self.bundle / "_internal" / name
                if "plugins" in name:
                    target.mkdir(parents=True)
                else:
                    ps.write(target, b"x", binary=True)
                try:
                    problems = bp.bundle_problems(self.bundle)
                    self.assertTrue(any(name in item and "네트워크 구성 요소" in item for item in problems), (name, problems))
                finally:
                    shutil.rmtree(target) if target.is_dir() else target.unlink()
        self.assertEqual(bp.bundle_problems(self.bundle), [])

    def test_the_openssl_x64_pair_is_refused_in_any_folder_in_any_generation_and_any_case(self):
        for relative in ("PySide6/libssl-3-x64.dll", "libssl-1_1-x64.dll", "libcrypto-1_1-x64.dll", "x/y/LIBCRYPTO-3-X64.DLL", "libssl-3-x64.dll", "PySide6/plugins/libcrypto-3-x64.dll"):
            with self.subTest(relative=relative):
                target = self.bundle / "_internal" / relative
                ps.write(target, b"x", binary=True)
                try:
                    problems = bp.bundle_problems(self.bundle)
                    self.assertTrue(any(Path(relative).name.lower() in item.lower() and "네트워크 구성 요소" in item for item in problems), (relative, problems))
                    self.assertEqual(len([item for item in problems if Path(relative).name.lower() in item.lower()]), 1, problems)            # 같은 파일을 두 번 알리지 않는다
                finally:
                    target.unlink()
        self.assertEqual(bp.bundle_problems(self.bundle), [])

    def test_the_pythons_own_openssl_dlls_and_the_qt_network_library_that_the_touch_plugin_pulls_in_are_not_refused(self):
        """Python 이 싣는 `libssl-3.dll`·`libcrypto-3.dll` 과, `qtuiotouchplugin.dll`(Qt 의 TUIO 터치 플러그인)이 정적으로 가져와 제외 뒤에도 남는 `Qt6Network.dll` 은 막지 않는다."""
        for name in ("libssl-3.dll", "libcrypto-3.dll", "PySide6/Qt6Network.dll"):
            ps.write(self.bundle / "_internal" / name, b"x", binary=True)
        self.assertEqual(bp.bundle_problems(self.bundle), [])


class BinaryOriginTest(unittest.TestCase):
    ROOTS = ["C:/ccgui/v", "C:/Users/me/AppData/Local/Programs/Python/Python312", "C:/Windows"]

    def toc(self, *rows):
        return repr(([tuple(row) for row in rows],))

    def test_binaries_from_the_environment_the_python_and_windows_are_accepted_whatever_the_slash_or_case(self):
        text = self.toc(("python312.dll", "C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312\\python312.dll", "BINARY"),
                        ("PySide6\\QtCore.pyd", "c:/CCGUI/v/Lib/site-packages/PySide6/QtCore.pyd", "EXTENSION"),
                        ("msvcp140.dll", "C:\\Windows\\System32\\msvcp140.dll", "BINARY"),
                        ("x.exe", "C:\\somewhere\\x.exe", "EXECUTABLE"), ("data.txt", "D:\\elsewhere\\data.txt", "DATA"))
        self.assertEqual(bp.binary_origin_problems(text, self.ROOTS), [])

    def test_a_dll_that_came_from_another_program_on_the_path_is_named_with_its_origin(self):
        text = self.toc(("python312.dll", "C:/Users/me/AppData/Local/Programs/Python/Python312/python312.dll", "BINARY"),
                        ("libcrypto-3-x64.dll", "C:\\Program Files\\Git\\mingw64\\bin\\libcrypto-3-x64.dll", "BINARY"),
                        ("libssl-3-x64.dll", "C:\\Other App\\libssl-3-x64.dll", "BINARY"),
                        ("lookalike.pyd", "C:/ccgui/v2/lookalike.pyd", "EXTENSION"))
        problems = bp.binary_origin_problems(text, self.ROOTS)
        self.assertEqual(len(problems), 3)
        for needle in ("libcrypto-3-x64.dll", "Program Files", "libssl-3-x64.dll", "Other App", "lookalike.pyd"):
            self.assertTrue(any(needle in item for item in problems), needle)

    def test_dot_dot_is_resolved_so_a_line_that_only_looks_like_it_is_inside_the_root_is_refused(self):
        text = self.toc(("evil.dll", "C:/ccgui/v/../evil/evil.dll", "BINARY"), ("ok.dll", "C:/ccgui/v/Lib/../Lib/ok.dll", "BINARY"), ("up.pyd", "C:/ccgui/v/x/../../up.pyd", "EXTENSION"),
                        ("rel.dll", "evil.dll", "BINARY"), ("deep.dll", "C:/ccgui/v/a/b/../../c/deep.dll", "BINARY"))
        problems = bp.binary_origin_problems(text, self.ROOTS)
        self.assertEqual(sorted(item.split("(")[0] for item in problems), ["evil.dll", "rel.dll", "up.pyd"])
        self.assertEqual(bp.binary_origin_problems(self.toc(("a.dll", "C:/ccgui/v/Lib/x.dll", "BINARY")), ["C:/ccgui/v/Lib/../"]), [])        # 허용 뿌리도 풀어서 견준다

    def test_a_data_row_that_is_really_a_dll_is_checked_and_the_start_file_and_plain_data_are_not(self):
        text = self.toc(("sneaky.dll", "C:/Program Files/Git/x/sneaky.dll", "DATA"), ("sneaky.PYD", "C:/OtherApp/sneaky.PYD", "DATA"), ("data.exe", "C:/elsewhere/data.exe", "DATA"),
                        ("readme.txt", "C:/elsewhere/readme.txt", "DATA"), ("ChanceBlogDesktop.exe", "C:/out/work/ChanceBlogDesktop.exe", "EXECUTABLE"), ("base_library.zip", "C:/out/work/base_library.zip", "DATA"))
        problems = bp.binary_origin_problems(text, self.ROOTS)
        self.assertEqual(sorted(item.split("(")[0] for item in problems), ["data.exe", "sneaky.PYD", "sneaky.dll"])

    def test_a_folder_that_only_starts_with_the_same_letters_is_not_inside_the_root(self):
        self.assertEqual(len(bp.binary_origin_problems(self.toc(("a.dll", "C:/ccgui/venv-other/a.dll", "BINARY"), ("b.dll", "C:/WindowsOld/b.dll", "BINARY")), self.ROOTS)), 2)

    def test_a_list_that_cannot_be_read_is_a_problem_because_the_origin_would_be_unknown(self):
        for text in ("", "not python", "[]", "()", "([('a',)],)", "([('a', 'b')],)", "([1, 2, 3],)", "3"):
            with self.subTest(text=text):
                self.assertTrue(bp.binary_origin_problems(text, self.ROOTS), text)

    def test_a_missing_list_file_is_a_problem_and_a_real_file_is_read(self):
        with ps.temp_dir() as tmp:
            self.assertTrue(bp.check_binary_origins(Path(tmp) / "none.toc", self.ROOTS))
            good = ps.write(Path(tmp) / "good.toc", self.toc(("a.dll", "C:/ccgui/v/a.dll", "BINARY")))
            self.assertEqual(bp.check_binary_origins(good, self.ROOTS), [])
            bad = ps.write(Path(tmp) / "bad.toc", self.toc(("a.dll", "C:/other/a.dll", "BINARY")))
            self.assertEqual(len(bp.check_binary_origins(bad, self.ROOTS)), 1)

    def test_the_default_roots_are_this_environment_the_base_python_and_the_windows_folder(self):
        roots = bp.allowed_roots({"SystemRoot": "D:\\Win"})
        self.assertEqual(roots, [sys.prefix, sys.base_prefix, "D:\\Win"])
        self.assertEqual(bp.allowed_roots({"windir": "E:\\W"})[2], "E:\\W")
        self.assertEqual(bp.allowed_roots({})[2], "C:/Windows")

    def test_the_real_bundle_list_the_trial_builds_wrote_would_have_caught_the_path_dll(self):
        """독립 검증이 찾은 사실 — 같은 소스인데 PATH 에 따라 OpenSSL `-x64` 쌍이 Git for Windows 나 다른 프로그램 폴더에서 들어왔다."""
        text = self.toc(("libcrypto-3-x64.dll", "C:\\Program Files\\Git\\mingw64\\bin\\libcrypto-3-x64.dll", "BINARY"), ("libssl-3-x64.dll", "C:\\Program Files\\Git\\mingw64\\bin\\libssl-3-x64.dll", "BINARY"))
        self.assertEqual(len(bp.binary_origin_problems(text, bp.allowed_roots())), 2)


class WriteZipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make(self, name, order, *, mtime):
        folder = self.root / name
        contents = {"b/second.txt": b"second" * 100, "a/first.bin": bytes(range(256)) * 40, "ChanceBlogDesktop.exe": ps.pe_bytes(), "한글 이름/파일.txt": "내용".encode("utf-8"), "z.dll": b"dll" * 50}
        for relative in order:
            path = ps.write(folder / relative, contents[relative], binary=True)
            os.utime(path, (mtime, mtime))
        return folder

    def test_the_same_files_give_the_same_bytes_whatever_the_creation_order_and_file_times(self):
        names = ["b/second.txt", "a/first.bin", "ChanceBlogDesktop.exe", "한글 이름/파일.txt", "z.dll"]
        first = self.make("one", names, mtime=1_600_000_000)
        second = self.make("two", list(reversed(names)), mtime=1_700_000_000)
        date_time = bp.zip_date_time(ps.COMMIT_EPOCH)
        bp.write_zip(first, self.root / "1.zip", "Top-1", date_time)
        time.sleep(0.05)
        bp.write_zip(second, self.root / "2.zip", "Top-1", date_time)
        self.assertEqual((self.root / "1.zip").read_bytes(), (self.root / "2.zip").read_bytes())
        self.assertEqual(pc.sha256_file(self.root / "1.zip"), pc.sha256_file(self.root / "2.zip"))

    def test_entries_are_sorted_under_one_top_folder_with_fixed_time_attributes_and_deflate(self):
        folder = self.make("f", ["b/second.txt", "a/first.bin", "ChanceBlogDesktop.exe", "z.dll"], mtime=1_600_000_000)
        names = bp.write_zip(folder, self.root / "x.zip", "Top-1", (2026, 11, 11, 1, 0, 0))
        self.assertEqual(names, sorted(names))
        with zipfile.ZipFile(self.root / "x.zip") as archive:
            infos = archive.infolist()
            self.assertEqual([item.filename for item in infos], [f"Top-1/{name}" for name in names])
            for item in infos:
                self.assertEqual(item.date_time, (2026, 11, 11, 1, 0, 0))
                self.assertEqual(item.compress_type, zipfile.ZIP_DEFLATED)
                self.assertEqual(item.create_system, 3)
                expected = 0o100755 if item.filename.endswith((".exe", ".dll")) else 0o100644
                self.assertEqual(item.external_attr >> 16, expected, item.filename)
                self.assertNotIn(chr(92), item.filename)
                self.assertFalse(item.filename.endswith("/"))
            self.assertIsNone(archive.testzip())

    def test_every_entry_is_compressed_at_level_9_exactly(self):
        import random
        import zlib
        words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo",
                 "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu", "가나다", "라마바", "사아자", "차카타", "파하", "시험", "묶음", "설치"]
        rng = random.Random(1)                                                           # 같은 글이 늘 만들어진다(이 글은 압축 수준마다 크기가 다르다)
        text = " ".join(rng.choice(words) + str(rng.randrange(1000)) for _ in range(4000)).encode("utf-8")
        folder = self.root / "lvl"
        ps.write(folder / "t.txt", text, binary=True)
        bp.write_zip(folder, self.root / "lvl.zip", "T", (2026, 11, 11, 1, 0, 0))
        sizes = {}
        for level in (1, 6, 9):
            compressor = zlib.compressobj(level, zlib.DEFLATED, -15)
            sizes[level] = len(compressor.compress(text) + compressor.flush())
        self.assertNotEqual(sizes[1], sizes[9], sizes)                                    # 시험이 수준을 알아볼 수 있는 글이다
        with zipfile.ZipFile(self.root / "lvl.zip") as archive:
            self.assertEqual(archive.getinfo("T/t.txt").compress_size, sizes[9])

    def test_different_content_or_a_different_time_gives_different_bytes(self):
        folder = self.make("f", ["b/second.txt"], mtime=1_600_000_000)
        bp.write_zip(folder, self.root / "a.zip", "T", (2026, 11, 11, 1, 0, 0))
        bp.write_zip(folder, self.root / "b.zip", "T", (2026, 11, 11, 1, 0, 2))
        ps.write(folder / "b/second.txt", b"changed", binary=True)
        bp.write_zip(folder, self.root / "c.zip", "T", (2026, 11, 11, 1, 0, 0))
        hashes = {pc.sha256_file(self.root / name) for name in ("a.zip", "b.zip", "c.zip")}
        self.assertEqual(len(hashes), 3)

    def test_verify_zip_accepts_a_matching_archive_and_rejects_tampering_extras_and_other_roots(self):
        folder = self.make("f", ["b/second.txt", "a/first.bin"], mtime=1_600_000_000)
        bp.write_zip(folder, self.root / "ok.zip", "Top", (2026, 11, 11, 1, 0, 0))
        files = mm.collect_files(folder)
        bp.verify_zip(self.root / "ok.zip", "Top", files)
        with self.assertRaises(mm.BuildRefused):                                    # 목록과 다른 해시
            bp.verify_zip(self.root / "ok.zip", "Top", dict(files, **{"a/first.bin": "0" * 64}))
        with self.assertRaises(mm.BuildRefused):                                    # 목록에 없는 항목이 들어 있음
            bp.verify_zip(self.root / "ok.zip", "Top", {"b/second.txt": files["b/second.txt"]})
        with self.assertRaises(mm.BuildRefused):                                    # 맨 위 폴더가 다름
            bp.verify_zip(self.root / "ok.zip", "Other", files)
        with zipfile.ZipFile(self.root / "ok.zip", "a") as archive:
            archive.writestr("Elsewhere/x.txt", "x")
        with self.assertRaises(mm.BuildRefused):
            bp.verify_zip(self.root / "ok.zip", "Top", files)


class SelftestParsingTest(unittest.TestCase):
    def test_lines_are_sorted_into_passed_failed_skipped_with_the_failure_text(self):
        text = ps.selftest_text(overrides={"capabilities": ("fail", "외부 쓰기 관문(capabilities) 모듈이 없어요"), "uac_manifest": ("skip", "건너뜀")})
        parsed = bp.parse_selftest(text)
        self.assertEqual(parsed["failed"], ["capabilities"])
        self.assertEqual(parsed["skipped"], ["uac_manifest"])
        self.assertEqual(len(parsed["passed"]), len(ps.SELFTEST_KEYS) - 2)
        self.assertIn("모듈이 없어요", parsed["failed_text"]["capabilities"])

    def test_header_and_summary_lines_and_noise_are_ignored(self):
        parsed = bp.parse_selftest("ChanceBlog Desktop 0.1.0 자가 점검\n결과: 통과 1 · 실패 0\n[통과] utf8_mode: 정상\n  [실패] gui_only_entry: x \nrandom [통과] noise\n")
        self.assertEqual((parsed["passed"], parsed["failed"]), (["utf8_mode"], ["gui_only_entry"]))

    def judge(self, **kwargs):
        allow = kwargs.pop("allow", False)
        return bp.judge_selftest(bp.parse_selftest(ps.selftest_text(**kwargs)), allow_missing_gate=allow)

    def test_all_passed_is_ok_and_the_gate_counts_as_present(self):
        ok, gate, override, bad = self.judge()
        self.assertEqual((ok, gate, override, bad), (True, True, False, []))

    def test_any_failed_check_fails_the_build(self):
        for key in ps.SELFTEST_KEYS:
            with self.subTest(key=key):
                ok, _gate, _override, bad = self.judge(overrides={key: ("fail", "x")})
                self.assertFalse(ok)
                self.assertIn(key, bad)

    def test_a_skipped_check_fails_the_build_because_the_bundle_may_not_skip(self):
        ok, *_ = self.judge(overrides={"qt_screens": ("skip", "x")})
        self.assertFalse(ok)

    def test_an_extra_check_the_build_does_not_require_still_counts_when_it_skips_or_fails(self):
        for label, expected in (("건너뜀", False), ("실패", False), ("통과", True)):
            with self.subTest(label=label):
                text = ps.selftest_text() + f"[{label}] extra_check: 설명\n"
                ok, _gate, _override, bad = bp.judge_selftest(bp.parse_selftest(text), allow_missing_gate=False)
                self.assertEqual(ok, expected)
                self.assertEqual("extra_check" in bad, label == "실패")

    def test_a_required_check_that_never_printed_fails_the_build(self):
        for key in ps.SELFTEST_KEYS:
            with self.subTest(key=key):
                ok, _gate, _override, bad = self.judge(drop=(key,))
                self.assertFalse(ok)
                self.assertIn(key, bad)

    def test_only_a_missing_gate_module_can_be_waved_through_and_it_is_recorded(self):
        missing = {"capabilities": ("fail", "외부 쓰기 관문(capabilities) 모듈이 없어요 — 이 소스에는 아직 없어요")}
        self.assertFalse(self.judge(overrides=missing)[0])
        ok, gate, override, bad = self.judge(overrides=missing, allow=True)
        self.assertEqual((ok, gate, override, bad), (True, False, True, []))
        open_gate = {"capabilities": ("fail", "관문 상수 EXTERNAL_WRITE 이 False 가 아니에요 — 외부 쓰기가 열려 있어요")}
        ok, gate, override, bad = self.judge(overrides=open_gate, allow=True)
        self.assertFalse(ok)
        self.assertEqual(bad, ["capabilities"])
        self.assertFalse(override)

    def test_a_gate_module_that_exists_but_fails_to_import_is_never_waved_through(self):
        """`--allow-missing-gate` 는 '모듈이 없음' 만 넘긴다 — 모듈은 있는데 안에서 가져오기가 실패하면 시험 빌드로도 넘기지 않는다(D-419)."""
        broken = ("외부 쓰기 관문 모듈 안에서 필요한 다른 모듈을 불러오지 못했어요(오류 종류: ModuleNotFoundError)", "외부 쓰기 관문 모듈을 불러오지 못했어요(오류 종류: ImportError)",
                  "점검 중 오류(SyntaxError)", "다른 모듈이 없어요 — 외부 쓰기 관문(capabilities) 모듈이 없어요")
        for sentence in broken:
            with self.subTest(sentence=sentence):
                ok, gate, override, bad = self.judge(overrides={"capabilities": ("fail", sentence)}, allow=True)
                self.assertFalse(ok)
                self.assertFalse(override)
                self.assertEqual(bad, ["capabilities"])
        ok, _gate, override, _bad = self.judge(overrides={"capabilities": ("fail", pc.GATE_MISSING_TEXT + " — 이 소스에는 아직 없어요")}, allow=True)
        self.assertTrue(ok and override)

    def test_the_override_flag_alone_changes_nothing_when_the_gate_is_there(self):
        ok, gate, override, bad = self.judge(allow=True)
        self.assertEqual((ok, gate, override, bad), (True, True, False, []))

    def test_the_override_does_not_hide_other_failures(self):
        missing = {"capabilities": ("fail", "외부 쓰기 관문(capabilities) 모듈이 없어요"), "file_hashes": ("fail", "다름")}
        ok, _gate, override, bad = self.judge(overrides=missing, allow=True)
        self.assertFalse(ok)
        self.assertEqual(bad, ["file_hashes"])
        self.assertTrue(override)


class RunFrozenSelftestTest(unittest.TestCase):
    def test_the_exe_is_run_with_only_the_selftest_flag_in_its_own_folder_without_utf8_env(self):
        seen = {}

        def runner(command, **kwargs):
            seen.update(command=command, **kwargs)
            return subprocess.CompletedProcess(command, 0, stdout="[통과] utf8_mode: 정상\n".encode("utf-8"), stderr=b"")
        with mock.patch.dict(os.environ, {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "windows", "PYTHONPATH": "x", "KEEP_ME": "1", "PATH": "C:/a;C:/b"}):
            code, text = bp.run_frozen_selftest(Path("C:/b/ChanceBlogDesktop.exe"), runner=runner)
        self.assertEqual((code, text), (0, "[통과] utf8_mode: 정상\n"))
        self.assertEqual(seen["command"], [str(Path("C:/b/ChanceBlogDesktop.exe")), "--selftest"])
        self.assertEqual(seen["cwd"], str(Path("C:/b")))
        for name in ("PYTHONUTF8", "PYTHONIOENCODING", "QT_QPA_PLATFORM", "PYTHONPATH"):
            self.assertNotIn(name, seen["env"])
        self.assertEqual(seen["env"]["KEEP_ME"], "1")
        self.assertEqual(seen["env"]["PATH"], "C:/a;C:/b")                              # 자가 점검은 PATH 를 좁히지 않은 보통 환경에서 돈다(좁히는 것은 PyInstaller 를 부를 때뿐이다 — D-468)

    def test_output_that_is_not_utf8_is_refused(self):
        runner = lambda command, **k: subprocess.CompletedProcess(command, 1, stdout="[통과] x: 한글".encode("cp949"), stderr=b"")      # noqa: E731
        with self.assertRaises(mm.BuildRefused) as caught:
            bp.run_frozen_selftest(Path("x.exe"), runner=runner)
        self.assertIn("UTF-8", str(caught.exception))

    def test_stderr_is_read_too(self):
        runner = lambda command, **k: subprocess.CompletedProcess(command, 1, stdout=b"", stderr="[실패] gui_only_entry: x".encode("utf-8"))      # noqa: E731
        code, text = bp.run_frozen_selftest(Path("x.exe"), runner=runner)
        self.assertEqual(code, 1)
        self.assertIn("gui_only_entry", text)


@unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
class BuildFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = ps.make_build_repo(self.root / "repo")
        self.out = self.root / "out"
        self.lines = []

    def run_build(self, fake=None, **options):
        fake = fake or ps.FakeBuild(self.root, self.repo)
        result = bp.build(bp.Options(repo=self.repo, out_dir=self.out, **options), steps=fake.steps, say=self.lines.append)
        return fake, result

    def test_the_whole_flow_makes_the_four_release_files_and_calls_the_steps_in_order(self):
        fake, result = self.run_build()
        self.assertEqual([call[0] for call in fake.calls], ["pyinstaller", "selftest", "scan"])
        self.assertEqual(sorted(path.name for path in (self.out / "release").iterdir()), sorted([pc.zip_name(ps.VERSION), "PACKAGE_INFO.json", "PACKAGE_INFO.md", "SHA256SUMS"]))
        self.assertEqual(result["zip"].name, "ChanceBlogDesktop-0.1.0-preview.1-win64.zip")
        sums = (self.out / "release" / "SHA256SUMS").read_text(encoding="utf-8")
        self.assertEqual(sums, f"{pc.sha256_file(result['zip'])}  {pc.zip_name(ps.VERSION)}\n")
        self.assertEqual(len(self.lines), 8)
        self.assertTrue(self.lines[0].startswith("[1/8]") and self.lines[-1].startswith("[8/8]"))

    def test_the_zip_holds_one_top_folder_with_the_bundle_the_license_folder_and_both_info_files(self):
        _fake, result = self.run_build()
        with zipfile.ZipFile(result["zip"]) as archive:
            names = archive.namelist()
        top = pc.top_folder(ps.VERSION) + "/"
        self.assertTrue(all(name.startswith(top) for name in names))
        for needed in (f"{pc.EXE_NAME}.exe", "VERSION", "PACKAGE_INFO.json", "PACKAGE_INFO.md", "vendor/VENDOR.json", "vendor/pipeline/gates.py", "LICENSES/LGPL-3.0.txt", "LICENSES/GPL-3.0.txt",
                       "LICENSES/THIRD_PARTY_NOTICES.md", "LICENSES/PYTHON-LICENSE.txt", "LICENSES/PYINSTALLER-COPYING.txt", f"_internal/{ps.PYTHON_DLL}"):
            self.assertIn(top + needed, names)
        self.assertNotIn(top + "_internal/../", names)

    def test_the_version_file_is_written_with_lf_and_the_pyinstaller_args_are_the_checked_ones(self):
        fake, _result = self.run_build()
        args = fake.calls[0][1]
        self.assertIn("--onedir", args)
        self.assertEqual(args[args.index("--python-option") + 1], "X utf8")
        self.assertEqual((self.out / "version_info.txt").read_bytes(), bp.version_file_text(ps.VERSION).encode("utf-8"))
        env = fake.calls[0][2]
        self.assertEqual((env["PYTHONHASHSEED"], env["SOURCE_DATE_EPOCH"]), ("0", str(ps.COMMIT_EPOCH)))
        self.assertEqual((self.repo / "VERSION").read_text(encoding="utf-8").strip(), ps.VERSION)

    def test_the_bundle_version_file_is_lf_only_and_the_info_files_have_no_clock_in_the_inner_copy(self):
        _fake, result = self.run_build()
        bundle = result["bundle"]
        self.assertEqual((bundle / "VERSION").read_bytes(), (ps.VERSION + "\n").encode("utf-8"))
        inner = json.loads((bundle / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        outer = json.loads((self.out / "release" / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertEqual(inner["variant"], "inner")
        self.assertEqual(outer["variant"], "outer")
        for key in ("built_utc", "package", "malware_scan", "selftest", "host"):
            self.assertNotIn(key, inner)
            self.assertIn(key, outer)
        self.assertEqual(inner["files"], outer["files"])
        self.assertEqual(outer["package"]["sha256"], pc.sha256_file(result["zip"]))
        self.assertEqual(inner["git"]["commit"], ps.git(self.repo, "rev-parse", "HEAD"))

    def test_the_same_input_twice_gives_the_same_zip(self):
        first = self.run_build()[1]["sha256"]
        second = self.run_build()[1]["sha256"]
        self.assertEqual(first, second)

    def test_a_failed_selftest_stops_the_build_and_leaves_no_release_files(self):
        fake = ps.FakeBuild(self.root, self.repo, selftest=ps.selftest_text(overrides={"qt_screens": ("fail", "화면이 안 열렸어요")}))
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("qt_screens", str(caught.exception))
        self.assertFalse((self.out / "release").exists())
        self.assertEqual([call[0] for call in fake.calls], ["pyinstaller", "selftest"])

    def test_a_dirty_work_tree_is_refused_before_pyinstaller_runs(self):
        ps.write(self.repo / "stray.txt", "x")
        fake = ps.FakeBuild(self.root, self.repo)
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("깨끗하지 않아요", str(caught.exception))
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.out.exists())

    def test_tools_that_differ_from_the_lock_are_refused_before_pyinstaller_runs(self):
        fake = ps.FakeBuild(self.root, self.repo)
        fake.steps["lookup"] = ps.fake_lookup(dict(ps.lock_versions(), pyinstaller="0.0.1"))
        with self.assertRaises(mm.BuildRefused):
            self.run_build(fake)
        self.assertEqual(fake.calls, [])

    def test_a_bad_version_file_is_refused_first(self):
        ps.write(self.repo / "VERSION", "banana\n")
        ps.git(self.repo, "commit", "-qam", "v")
        fake = ps.FakeBuild(self.root, self.repo)
        with self.assertRaises(mm.BuildRefused):
            self.run_build(fake)
        self.assertEqual(fake.calls, [])

    def test_a_pc_that_is_not_windows_is_refused_before_anything_happens(self):
        fake = ps.FakeBuild(self.root, self.repo)
        fake.steps["platform"] = "linux"
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("Windows", str(caught.exception))
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.out.exists())
        self.assertEqual(self.lines, [])
        fake.steps["platform"] = "win32"
        self.run_build(fake)                                                              # 윈도라고 알리면 같은 저장소에서 그대로 만들어진다

    def test_an_unsafe_out_dir_is_refused_and_nothing_is_deleted(self):
        keep = ps.write(self.repo / "keep.txt", "keep")
        with self.assertRaises(mm.BuildRefused):
            bp.build(bp.Options(repo=self.repo, out_dir=self.repo), steps=ps.FakeBuild(self.root, self.repo).steps, say=lambda text: None)
        self.assertTrue(keep.exists())

    def test_a_missing_gate_module_stops_the_build_unless_the_trial_flag_is_given_and_then_it_is_marked_everywhere(self):
        missing = ps.selftest_text(overrides={"capabilities": ("fail", pc.GATE_MISSING_TEXT)})
        with self.assertRaises(mm.BuildRefused):
            self.run_build(ps.FakeBuild(self.root, self.repo, selftest=missing))
        self.assertFalse((self.out / "release").exists())
        fake, result = self.run_build(ps.FakeBuild(self.root, self.repo, selftest=missing), allow_missing_gate=True)
        self.assertTrue(result["gate_override"])
        self.assertTrue(result["trial"])
        self.assertFalse(result["gate_present"])
        outer = json.loads((self.out / "release" / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertFalse(outer["release_eligible"])
        self.assertTrue(outer["build"]["gate_override"])
        self.assertIs(outer["trial"], True)
        markdown = (self.out / "release" / "PACKAGE_INFO.md").read_text(encoding="utf-8")
        self.assertIn("시험 빌드(TESTBUILD)입니다", markdown)
        self.assertIn("허용된 관문 실패 1", markdown)
        # 이름 — 압축 파일·묶음 폴더·압축 안 맨 위 폴더에 TESTBUILD 가 들어 있어 개인 PC 로 못 가게 이름만 봐도 알아본다
        zip_name = "ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD-win64.zip"
        self.assertEqual(result["zip"].name, zip_name)
        self.assertEqual(sorted(path.name for path in (self.out / "release").iterdir()), sorted([zip_name, "PACKAGE_INFO.json", "PACKAGE_INFO.md", "SHA256SUMS"]))
        self.assertEqual((self.out / "release" / "SHA256SUMS").read_text(encoding="utf-8"), f"{pc.sha256_file(result['zip'])}  {zip_name}\n")
        self.assertEqual(result["bundle"].name, "ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD")
        with zipfile.ZipFile(result["zip"]) as archive:
            self.assertTrue(all(name.startswith("ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD/") for name in archive.namelist()))
        # 묶음 안 정보 파일·윈도 버전 정보에도 시험 빌드가 적힌다
        inner = json.loads((result["bundle"] / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertIs(inner["trial"], True)
        self.assertIn("시험 빌드(TESTBUILD)입니다", (result["bundle"] / "PACKAGE_INFO.md").read_text(encoding="utf-8"))
        self.assertIn("시험 빌드 TESTBUILD", (self.out / "version_info.txt").read_text(encoding="utf-8"))
        # 화면 '정보' 카드가 읽는 바로 그 파일에서 시험 빌드 문장이 나온다
        shown = app_version.read_version(result["bundle"] / "VERSION")
        self.assertIn(pc.TRIAL_NOTICE, shown.notice)

    def test_a_normal_build_has_no_testbuild_anywhere(self):
        _fake, result = self.run_build()
        self.assertFalse(result["trial"])
        self.assertNotIn("TESTBUILD", result["zip"].name)
        self.assertNotIn("TESTBUILD", result["bundle"].name)
        self.assertIs(json.loads((result["bundle"] / "PACKAGE_INFO.json").read_text(encoding="utf-8"))["trial"], False)
        self.assertNotIn("TESTBUILD", (self.out / "version_info.txt").read_text(encoding="utf-8"))
        self.assertNotIn(pc.TRIAL_NOTICE, app_version.read_version(result["bundle"] / "VERSION").notice)

    def test_the_override_flag_is_not_a_trial_build_when_the_source_has_the_gate_module(self):
        repo = ps.make_build_repo(self.root / "repo_gate", extra={"src/chanceblog_desktop/capabilities.py": "EXTERNAL_WRITE = False\nBLOGGER_OAUTH_INPUT = False\n"})
        fake = ps.FakeBuild(self.root, repo)
        result = bp.build(bp.Options(repo=repo, out_dir=self.root / "out_gate", allow_missing_gate=True), steps=fake.steps, say=lambda text: None)
        self.assertFalse(result["trial"])
        self.assertFalse(result["gate_override"])
        self.assertTrue(result["gate_present"])
        self.assertNotIn("TESTBUILD", result["zip"].name)
        info = json.loads((self.root / "out_gate" / "release" / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertTrue(info["release_eligible"])
        self.assertIs(info["trial"], False)
        self.assertIs(info["build"]["gate_override"], False)                                    # 옵션을 붙였어도 관문 소스가 있으면 '관문 없이 만든 시험 빌드' 가 아니다
        self.assertNotIn("시험 빌드(TESTBUILD)입니다", (self.root / "out_gate" / "release" / "PACKAGE_INFO.md").read_text(encoding="utf-8"))
        self.assertIn("chanceblog_desktop.capabilities", fake.calls[0][1])

    def test_a_gate_module_that_fails_to_import_is_not_waved_through_even_with_the_flag(self):
        broken = ps.selftest_text(overrides={"capabilities": ("fail", "외부 쓰기 관문 모듈 안에서 필요한 다른 모듈을 불러오지 못했어요(오류 종류: ModuleNotFoundError)")})
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(ps.FakeBuild(self.root, self.repo, selftest=broken), allow_missing_gate=True)
        self.assertIn("capabilities", str(caught.exception))
        self.assertFalse((self.out / "release").exists())

    def test_a_trial_flag_without_a_gate_source_but_a_passing_gate_check_is_refused_as_inconsistent(self):
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(ps.FakeBuild(self.root, self.repo), allow_missing_gate=True)                    # 소스에는 관문이 없는데 점검은 통과라고 한다 — 이상하다
        self.assertIn("시험 빌드 표시와 달라요", str(caught.exception))
        self.assertFalse((self.out / "release").exists())

    def test_a_dll_from_outside_the_allowed_folders_stops_the_build_before_the_bundle_is_trusted(self):
        fake = ps.FakeBuild(self.root, self.repo)
        fake.toc_rows = [(f"{pc.EXE_NAME}.exe", "C:/out/x.exe", "EXECUTABLE"), ("libssl-3-x64.dll", "C:/Program Files/Git/mingw64/bin/libssl-3-x64.dll", "BINARY")]
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("libssl-3-x64.dll", str(caught.exception))
        self.assertFalse((self.out / "release").exists())
        self.assertEqual([call[0] for call in fake.calls], ["pyinstaller"])                                 # 자가 점검까지 가지 않는다

    def test_an_ignored_file_in_an_input_folder_stops_the_build_before_pyinstaller_runs(self):
        ps.write(self.repo / "vendor" / "pipeline" / "leftover.zip", b"z", binary=True)                       # 템플릿의 .gitignore 가 *.zip 을 가린다 — git status 에는 안 보인다
        self.assertEqual(ps.git(self.repo, "status", "--porcelain"), "")
        fake = ps.FakeBuild(self.root, self.repo)
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("vendor/pipeline/leftover.zip", str(caught.exception))
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.out.exists())

    def test_a_new_file_in_vendor_stops_the_build_even_when_git_is_set_not_to_show_untracked_files(self):
        ps.git(self.repo, "config", "status.showUntrackedFiles", "no")
        ps.write(self.repo / "vendor" / "pipeline" / "untracked_note.txt", "x")                                 # 독립 검증이 재현한 길 — 이 파일이 압축 파일에 들어갔다
        self.assertEqual(ps.git(self.repo, "status", "--porcelain"), "")
        fake = ps.FakeBuild(self.root, self.repo)
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("깨끗하지 않아요", str(caught.exception))
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.out.exists())

    def test_a_tracked_input_file_changed_behind_skip_worktree_stops_the_build_before_pyinstaller_runs(self):
        ps.git(self.repo, "update-index", "--skip-worktree", "packaging/gui_entry.py")
        ps.write(self.repo / "packaging" / "gui_entry.py", "# 몰래 고침\n")                                       # 독립 검증이 재현한 길 — 고친 시작 파일이 그대로 묶였다
        self.assertEqual(ps.git(self.repo, "status", "--porcelain"), "")
        fake = ps.FakeBuild(self.root, self.repo)
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("packaging/gui_entry.py", str(caught.exception))
        self.assertIn("가려진 변경", str(caught.exception))
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.out.exists())

    def test_an_output_name_windows_would_rewrite_or_reserve_is_refused_before_anything_happens(self):
        fake = ps.FakeBuild(self.root, self.repo)
        for target in (self.repo / "src " / "out", self.repo / "vendor " / "o", self.repo / ".git " / "o", self.root / "out ", self.root / "con", self.root / "a|b"):
            with self.subTest(target=str(target)):
                with self.assertRaises(mm.BuildRefused) as caught:
                    bp.build(bp.Options(repo=self.repo, out_dir=target), steps=fake.steps, say=lambda text: None)
                self.assertIn("출력 폴더 경로의 이름", str(caught.exception))
        self.assertEqual(ps.git(self.repo, "status", "--porcelain"), "")                      # 저장소는 더러워지지 않았다
        self.assertEqual(fake.calls, [])

    def test_an_output_folder_with_other_files_and_no_marker_is_refused_and_keeps_them(self):
        keep = ps.write(self.out / "release" / "mine.txt", "내 파일")
        fake = ps.FakeBuild(self.root, self.repo)
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn(bp.OUT_MARKER, str(caught.exception))
        self.assertEqual(keep.read_text(encoding="utf-8"), "내 파일")
        self.assertEqual(fake.calls, [])

    def test_a_second_build_into_the_same_output_folder_is_fine_because_the_first_left_the_marker(self):
        self.run_build()
        self.assertTrue((self.out / bp.OUT_MARKER).is_file())
        self.run_build()
        self.assertEqual(sorted(path.name for path in (self.out / "release").iterdir()), sorted([pc.zip_name(ps.VERSION), "PACKAGE_INFO.json", "PACKAGE_INFO.md", "SHA256SUMS"]))

    def test_an_output_folder_inside_the_source_is_refused_and_the_repository_stays_clean(self):
        fake = ps.FakeBuild(self.root, self.repo)
        for relative in ("src/out", "vendor/out", "packaging/out"):
            with self.subTest(relative=relative):
                with self.assertRaises(mm.BuildRefused):
                    bp.build(bp.Options(repo=self.repo, out_dir=self.repo / relative), steps=fake.steps, say=lambda text: None)
        self.assertEqual(ps.git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(fake.calls, [])

    def test_a_deleted_version_file_is_refused_with_a_plain_sentence(self):
        (self.repo / "VERSION").unlink()
        fake = ps.FakeBuild(self.root, self.repo)
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("VERSION", str(caught.exception))
        self.assertEqual(fake.calls, [])

    def test_a_build_with_the_gate_present_is_release_eligible(self):
        _fake, result = self.run_build()
        outer = json.loads((self.out / "release" / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertTrue(outer["release_eligible"])
        self.assertTrue(result["gate_present"])
        self.assertNotIn("시험 빌드입니다", (self.out / "release" / "PACKAGE_INFO.md").read_text(encoding="utf-8"))

    def test_the_scan_runs_on_the_zip_and_the_bundle_and_can_be_skipped(self):
        fake, _result = self.run_build()
        targets = fake.calls[-1][1]
        self.assertTrue(targets[0].endswith(pc.zip_name(ps.VERSION)))
        self.assertTrue(targets[1].endswith(pc.top_folder(ps.VERSION)))
        fake2 = ps.FakeBuild(self.root, self.repo)
        _f, result = self.run_build(fake2, skip_scan=True)
        self.assertNotIn("scan", [call[0] for call in fake2.calls])
        self.assertIsNone(result["scan"])
        self.assertIn("검사 안 함", (self.out / "release" / "PACKAGE_INFO.md").read_text(encoding="utf-8"))

    def test_the_scan_result_is_written_into_the_outer_info(self):
        scan = {"status": "clean", "tool": "T", "reason": "위협이 발견되지 않았어요.", "targets": ["a.zip"], "exit_codes": [0], "engine_version": "1.1", "signature_version": "2.2"}
        _fake, _result = self.run_build(ps.FakeBuild(self.root, self.repo, scan=scan))
        outer = json.loads((self.out / "release" / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertEqual(outer["malware_scan"]["status"], "clean")
        self.assertIn("엔진 1.1", (self.out / "release" / "PACKAGE_INFO.md").read_text(encoding="utf-8"))

    def test_a_secret_shaped_file_in_the_bundle_stops_the_build(self):
        fake = ps.FakeBuild(self.root, self.repo)
        original = fake.pyinstaller

        def leaky(args, env, cwd, log_path):
            code = original(args, env, cwd, log_path)
            ps.write(Path(args[args.index("--distpath") + 1]) / pc.EXE_NAME / "_internal" / "notes.txt", f"x = {KEY_SAMPLE}\n")
            return code
        fake.steps["pyinstaller"] = leaky
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("키 모양", str(caught.exception))
        self.assertNotIn(KEY_SAMPLE, str(caught.exception))
        self.assertFalse((self.out / "release").exists())

    def test_a_pyinstaller_failure_is_reported_with_the_log_path(self):
        fake = ps.FakeBuild(self.root, self.repo)
        fake.steps["pyinstaller"] = lambda args, env, cwd, log_path: 1
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        self.assertIn("build.log", str(caught.exception))

    def test_the_recorded_command_in_the_info_has_no_absolute_path_of_this_pc(self):
        self.run_build()
        outer = json.loads((self.out / "release" / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        text = " ".join(outer["build"]["command"])
        self.assertNotIn(str(self.root).replace(chr(92), "/"), text)
        self.assertIn("<저장소>", text)
        self.assertEqual(outer["build"]["tool"], "PyInstaller 6.22.3")

    def test_main_turns_an_operating_system_error_into_a_sentence_and_exit_code_2(self):
        captured = mock.MagicMock()
        with mock.patch.object(bp, "build", side_effect=FileNotFoundError(2, "No such file or directory", "x")), mock.patch.object(bp.sys, "stderr", captured):
            self.assertEqual(bp.main(["--out-dir", str(self.out), "--skip-scan"]), 2)
        text = "".join(call.args[0] for call in captured.write.call_args_list)
        self.assertIn("빌드를 멈췄어요", text)
        self.assertIn("FileNotFoundError", text)
        self.assertNotIn("Traceback", text)

    def test_main_returns_2_with_a_plain_sentence_when_the_tree_is_dirty(self):
        ps.write(self.repo / "stray.txt", "x")
        captured = mock.MagicMock()
        with mock.patch.object(bp, "REPO", self.repo), mock.patch.object(bp, "build", side_effect=mm.BuildRefused("작업 트리가 깨끗하지 않아요")), mock.patch.object(bp.sys, "stderr", captured):
            self.assertEqual(bp.main(["--out-dir", str(self.out), "--skip-scan"]), 2)
        self.assertIn("깨끗하지 않아요", "".join(call.args[0] for call in captured.write.call_args_list))


class ScriptShapeTest(unittest.TestCase):
    def test_the_build_script_never_touches_security_or_system_settings(self):
        text = (ps.PACKAGING / "build_package.py").read_text(encoding="utf-8") + (ps.PACKAGING / "make_manifest.py").read_text(encoding="utf-8")
        for word in ("Set-MpPreference", "Add-MpPreference", "reg add", "reg delete", "icacls", "takeown", "netsh", "schtasks", "sc.exe", "setx", "pip download", "urlopen", "requests."):
            self.assertNotIn(word, text, word)

    def test_the_only_deletions_are_inside_the_output_folder_helper(self):
        tree = ast.parse((ps.PACKAGING / "build_package.py").read_text(encoding="utf-8"))
        callers = []
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for call in [node for node in ast.walk(function) if isinstance(node, ast.Call)]:
                name = ast.unparse(call.func)
                if name in ("shutil.rmtree", "os.remove", "os.unlink", "Path.unlink") or name.endswith(".unlink"):
                    callers.append((function.name, name))
        self.assertEqual(callers, [("clean_out_dir", "shutil.rmtree")])

    def test_the_default_out_dir_is_a_git_ignored_folder(self):
        ignored = {line.strip() for line in (ps.ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
        self.assertIn("dist/", ignored)
        self.assertEqual(bp.DEFAULT_OUT, ps.ROOT / "dist" / "package")
        for pattern in ("*.zip", "*.exe"):
            self.assertIn(pattern, ignored)


if __name__ == "__main__":
    unittest.main()
