"""묶음의 화면 전용 시작 파일(`packaging/gui_entry.py`) 시험 — 인자를 하나도 열지 않는다(명령줄 부명령·`--yes` 계열 거절·입력값 되풀이 0), 숨은 `--selftest` 는 정확히 그 한 단어일 때만,
점검 항목마다 통과·실패 판정, 점검이 데이터 폴더를 만들지 않는다. PyInstaller·PySide6 없이 돈다(Qt 점검은 PySide6 가 없으면 건너뜀으로 센다).
"""
import ast
import importlib.util
import io
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import packaging_support as ps

ge = ps.gui_entry
mm = ps.make_manifest
pc = ps.pkgcommon
KEY_SAMPLE = "AI" + "za" + "A" * 35
GATE_PRESENT = importlib.util.find_spec("chanceblog_desktop.capabilities") is not None


def collect_say():
    spoken = []
    return spoken, (lambda text, error=False: spoken.append(text))


class EntrySourceTest(unittest.TestCase):
    """화면 전용 시작 파일이 외부로 나가는 길·명령줄 모듈을 코드로 열지 않았다는 소스 규칙."""

    def setUp(self):
        self.text = (ps.PACKAGING / "gui_entry.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def imported_names(self):
        names = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names.append(("." * node.level) + (node.module or ""))
        return names

    def test_no_network_process_browser_or_argument_parsing_module_is_imported_anywhere(self):
        forbidden = {"subprocess", "socket", "ssl", "urllib", "http", "webbrowser", "requests", "argparse", "ftplib", "smtplib", "xmlrpc", "asyncio", "multiprocessing", "shlex", "getopt", "optparse"}
        for name in self.imported_names():
            self.assertNotIn(name.split(".")[0], forbidden, name)

    def test_the_command_line_module_of_the_app_is_never_imported(self):
        for name in self.imported_names():
            self.assertFalse(name.startswith("chanceblog_desktop.service"), name)
            self.assertNotEqual(name, "chanceblog_desktop.__main__")
        self.assertEqual(self.text.count("chanceblog_desktop.service.cli"), 1)          # CLI_MODULES 목록의 이름뿐

    def test_no_process_start_or_exec_call_exists(self):
        calls = {ast.unparse(node.func) for node in ast.walk(self.tree) if isinstance(node, ast.Call)}
        for name in calls:
            self.assertFalse(name.startswith(("os.system", "os.startfile", "os.popen", "os.spawn", "os.exec", "subprocess.", "webbrowser.")), name)
        self.assertIn("os._exit", calls)                                                # 자가 점검이 글을 다 내보낸 뒤 끝내는 한 곳

    def test_ctypes_is_only_inside_the_two_windows_only_helpers(self):
        allowed = {"attach_parent_console", "message_box"}
        for function in [node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef)]:
            inner = [node for node in ast.walk(function) if isinstance(node, ast.Import) and any(alias.name == "ctypes" for alias in node.names)]
            if inner:
                self.assertIn(function.name, allowed, function.name)
        top_level = [node for node in self.tree.body if isinstance(node, ast.Import) and any(alias.name == "ctypes" for alias in node.names)]
        self.assertEqual(top_level, [])

    def code_strings(self):
        """문서 글(모듈·함수 설명)을 뺀 코드 속 글 상수 — 명령 이름이 코드에서 어디에 쓰이는지 본다."""
        docstrings = set()
        for node in [self.tree] + [n for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))]:
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
        return [node.value for node in ast.walk(self.tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]

    def test_the_publish_command_name_appears_in_code_only_in_the_list_of_refused_samples(self):
        strings = self.code_strings()
        self.assertEqual(strings.count("publish-pages"), 1)
        self.assertEqual(strings.count("--yes"), 1)
        self.assertNotIn("--data-dir", strings)
        sample_line = next(line for line in self.text.splitlines() if line.startswith("REFUSED_ARGUMENT_SAMPLES"))
        self.assertIn('"publish-pages", "--yes"', sample_line)

    def test_the_app_is_imported_only_inside_functions(self):
        for node in self.tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name in ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]):
                    self.assertFalse(name.startswith(("chanceblog_desktop", "PySide6")), name)

    def test_the_refusal_sentence_has_no_placeholder_that_could_echo_input(self):
        self.assertNotIn("{", ge.REFUSED)
        self.assertNotIn("%", ge.REFUSED)
        self.assertEqual(ge.START_FAILED.count("{"), 1)
        self.assertIn("{kind}", ge.START_FAILED)


class MainTest(unittest.TestCase):
    ARGUMENT_SETS = (["publish-pages", "--yes"], ["doctor"], ["gui"], ["gui", "--sample"], ["--sample"], ["--data-dir", "X"], ["--help"], ["-h"], ["/?"], ["--yes"], [""], [" "],
                     ["--selftest", "extra"], ["--SELFTEST"], ["--selftest="], ["-selftest"], ["selftest"], ["keys", "add", "--stdin"], ["backup"], ["topics", "restore"], ["--version"],
                     ["--selftest", "--selftest"], ["--", "--selftest"], [KEY_SAMPLE], ["--api-key", KEY_SAMPLE])

    def test_every_argument_set_is_refused_with_the_fixed_sentence_and_exit_code_2(self):
        for args in self.ARGUMENT_SETS:
            with self.subTest(args=args):
                spoken, say = collect_say()
                code = ge.main(list(args), say=say, start=lambda: self.fail("화면을 시작하면 안 된다"))
                self.assertEqual(code, 2)
                self.assertEqual(spoken, [ge.REFUSED])

    def test_a_key_shaped_argument_is_never_echoed(self):
        spoken, say = collect_say()
        ge.main(["--api-key", KEY_SAMPLE], say=say, start=lambda: None)
        self.assertNotIn(KEY_SAMPLE, "".join(spoken))
        self.assertNotIn("api-key", "".join(spoken))

    def test_no_argument_starts_the_screen_and_returns_its_code(self):
        spoken, say = collect_say()
        self.assertEqual(ge.main([], say=say, start=lambda: 7), 7)
        self.assertEqual(spoken, [])

    def test_exactly_the_selftest_word_runs_the_selftest(self):
        with mock.patch.object(ge, "selftest_main", return_value=5) as selftest:
            self.assertEqual(ge.main(["--selftest"], start=lambda: self.fail("화면을 시작하면 안 된다")), 5)
        selftest.assert_called_once_with()

    def test_the_arguments_come_from_sys_argv_when_not_given(self):
        spoken, say = collect_say()
        with mock.patch.object(sys, "argv", ["exe", "publish-pages", "--yes"]):
            self.assertEqual(ge.main(say=say, start=lambda: self.fail("x")), 2)
        self.assertEqual(spoken, [ge.REFUSED])

    def test_the_default_say_function_is_the_module_one(self):
        with mock.patch.object(ge, "has_output", return_value=True), mock.patch("builtins.print") as printed:
            self.assertEqual(ge.main(["x"]), 2)
        self.assertEqual(printed.call_args.args[0], ge.REFUSED)
        self.assertIs(printed.call_args.kwargs["file"], sys.stderr)

    def test_the_refusal_sentence_says_what_to_do_in_plain_korean(self):
        for needle in ("화면(GUI)만 엽니다", "명령이나 옵션을 받지 않아요", "입력한 값은 보이지 않습니다", "두 번 눌러"):
            self.assertIn(needle, ge.REFUSED)

    def test_the_selftest_samples_cover_the_dangerous_commands(self):
        flat = [word for sample in ge.REFUSED_ARGUMENT_SAMPLES for word in sample]
        for word in ("publish-pages", "--yes", "doctor", "gui", "--sample", "--help", "--selftest", "--SELFTEST"):
            self.assertIn(word, flat)


class StreamsTest(unittest.TestCase):
    def test_missing_streams_get_a_null_writer_so_that_writers_do_not_crash(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            ge.prepare_streams()
            self.assertIsInstance(sys.stdout, ge._NullWriter)
            self.assertIsInstance(sys.stderr, ge._NullWriter)
            self.assertEqual(sys.stdout.write("abc"), 3)
            sys.stdout.flush()
            self.assertFalse(sys.stdout.isatty())
            self.assertFalse(ge.has_output())

    def test_real_streams_are_switched_to_utf8_with_replacement(self):
        class Fake:
            def __init__(self):
                self.calls = []

            def reconfigure(self, **kwargs):
                self.calls.append(kwargs)
        out, err = Fake(), Fake()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            ge.prepare_streams()
            self.assertTrue(ge.has_output())
        self.assertEqual(out.calls, [{"encoding": "utf-8", "errors": "replace"}])
        self.assertEqual(err.calls, [{"encoding": "utf-8", "errors": "replace"}])

    def test_a_stream_that_cannot_be_reconfigured_is_left_alone(self):
        class Stubborn:
            def reconfigure(self, **kwargs):
                raise ValueError("no")
        with mock.patch.object(sys, "stdout", Stubborn()), mock.patch.object(sys, "stderr", Stubborn()):
            ge.prepare_streams()

    def test_a_korean_line_survives_a_cp949_pipe_after_the_switch(self):
        raw = io.BytesIO()
        wrapper = io.TextIOWrapper(raw, encoding="cp949", errors="strict")
        with mock.patch.object(sys, "stdout", wrapper), mock.patch.object(sys, "stderr", io.StringIO()):
            ge.prepare_streams()
            print("이모지 😀 와 한글")
            sys.stdout.flush()
        self.assertEqual(raw.getvalue().decode("utf-8").strip(), "이모지 😀 와 한글")

    def test_say_prints_to_stdout_or_stderr_when_there_is_output_and_shows_a_box_otherwise(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            ge.say("안녕")
            ge.say("오류", error=True)
        self.assertEqual((out.getvalue(), err.getvalue()), ("안녕\n", "오류\n"))
        with mock.patch.object(sys, "stdout", ge._NullWriter()), mock.patch.object(ge, "message_box") as box:
            ge.say("창으로", error=True)
            box.assert_called_once_with("창으로", True)


class RootAndInfoTest(unittest.TestCase):
    def test_the_app_root_is_the_exe_folder_when_frozen_and_the_repo_top_otherwise(self):
        self.assertEqual(ge.app_root(), ps.ROOT)
        self.assertFalse(ge.is_frozen())
        with ps.temp_dir() as tmp:
            exe = Path(tmp) / "x" / "ChanceBlogDesktop.exe"
            exe.parent.mkdir()
            exe.write_bytes(b"")
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(exe)):
                self.assertTrue(ge.is_frozen())
                self.assertEqual(ge.app_root(), exe.parent.resolve())

    def test_read_info_reads_a_json_object_or_nothing(self):
        with ps.temp_dir() as tmp:
            root = Path(tmp)
            self.assertIsNone(ge.read_info(root))
            for text in ("not json", "[1, 2]", '"text"', "", "{"):
                ps.write(root / "PACKAGE_INFO.json", text)
                self.assertIsNone(ge.read_info(root), text)
            ps.write(root / "PACKAGE_INFO.json", '{"a": 1}')
            self.assertEqual(ge.read_info(root), {"a": 1})


class Utf8CheckTest(unittest.TestCase):
    def test_utf8_mode_with_utf8_encoding_passes_in_every_spelling(self):
        for encoding in ("utf-8", "UTF-8", "utf_8", "UTF8"):
            self.assertEqual(ge.check_utf8(1, encoding, True).status, "ok", encoding)

    def test_a_frozen_bundle_without_utf8_mode_or_with_another_encoding_fails(self):
        self.assertEqual(ge.check_utf8(0, "utf-8", True).status, "fail")
        self.assertEqual(ge.check_utf8(1, "cp949", True).status, "fail")
        self.assertEqual(ge.check_utf8(0, "cp949", True).status, "fail")
        self.assertIn("X utf8", ge.check_utf8(0, "cp949", True).text)

    def test_source_runs_only_skip(self):
        self.assertEqual(ge.check_utf8(0, "cp949", False).status, "skip")
        self.assertEqual(ge.check_utf8(1, "utf-8", False).status, "ok")


class VersionFileCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_version_in_the_place_the_app_looks_passes(self):
        ps.write(self.root / "VERSION", ps.VERSION + "\n")
        result = ge.check_version_file(self.root, self.root / "VERSION", None, True)
        self.assertEqual(result.status, "ok")
        self.assertIn(ps.VERSION, result.text)

    def test_a_different_place_the_app_looks_is_a_failure_because_the_path_assumption_broke(self):
        ps.write(self.root / "VERSION", ps.VERSION + "\n")
        other = self.root / "deeper" / "VERSION"
        result = ge.check_version_file(self.root, other, None, True)
        self.assertEqual(result.status, "fail")
        self.assertIn("경로 가정", result.text)

    def test_a_missing_or_malformed_version_fails_when_frozen_and_skips_in_source(self):
        for text in (None, "banana", "v1.0.0", ""):
            if text is not None:
                ps.write(self.root / "VERSION", text)
            elif (self.root / "VERSION").exists():
                (self.root / "VERSION").unlink()
            self.assertEqual(ge.check_version_file(self.root, self.root / "VERSION", None, True).status, "fail", text)
            self.assertEqual(ge.check_version_file(self.root, self.root / "VERSION", None, False).status, "skip", text)

    def test_a_version_that_differs_from_the_info_file_fails(self):
        ps.write(self.root / "VERSION", ps.VERSION + "\n")
        self.assertEqual(ge.check_version_file(self.root, self.root / "VERSION", {"version": "9.9.9"}, True).status, "fail")
        self.assertEqual(ge.check_version_file(self.root, self.root / "VERSION", {"version": ps.VERSION}, True).status, "ok")


class PackageInfoCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ps.write(self.root / "PACKAGE_INFO.md", "x")

    def info(self):
        return json.loads(mm.render_json(ps.sample_info("inner")))

    def test_a_valid_inner_info_passes_and_shows_version_commit_and_the_notice(self):
        result = ge.check_package_info(self.root, self.info(), True)
        self.assertEqual(result.status, "ok")
        for needle in (ps.VERSION, ps.FAKE_COMMIT[:7], pc.NOTICE):
            self.assertIn(needle, result.text)

    def test_each_wrong_field_is_caught(self):
        mutations = {
            "trial missing": lambda d: d.pop("trial"),
            "trial as text": lambda d: d.update(trial="false"),
            "trial as number": lambda d: d.update(trial=0),
            "schema": lambda d: d.update(schema=2),
            "channel": lambda d: d.update(channel="stable"),
            "variant": lambda d: d.update(variant="outer"),
            "short commit": lambda d: d["git"].update(commit=ps.FAKE_COMMIT[:7]),
            "uppercase commit": lambda d: d["git"].update(commit=ps.FAKE_COMMIT.upper()),
            "dirty": lambda d: d["git"].update(clean=False),
            "clean as text": lambda d: d["git"].update(clean="true"),
            "signed": lambda d: d["signing"].update(signed=True),
            "signed missing": lambda d: d["signing"].pop("signed"),
            "notice": lambda d: d.update(notice="공개 배포용"),
            "no files": lambda d: d.update(files={}),
            "files not a dict": lambda d: d.update(files=[1]),
            "git not a dict": lambda d: d.update(git="x"),
        }
        for name, mutate in mutations.items():
            info = self.info()
            mutate(info)
            with self.subTest(name=name):
                self.assertEqual(ge.check_package_info(self.root, info, True).status, "fail", name)

    def test_a_trial_build_is_named_in_the_passing_text(self):
        info = self.info()
        self.assertNotIn(pc.TRIAL_NOTICE, ge.check_package_info(self.root, info, True).text)
        info["trial"] = True
        result = ge.check_package_info(self.root, info, True)
        self.assertEqual(result.status, "ok")
        self.assertIn(pc.TRIAL_NOTICE, result.text)

    def test_a_missing_markdown_copy_is_caught(self):
        (self.root / "PACKAGE_INFO.md").unlink()
        self.assertEqual(ge.check_package_info(self.root, self.info(), True).status, "fail")

    def test_no_info_file_fails_when_frozen_and_skips_in_source(self):
        self.assertEqual(ge.check_package_info(self.root, None, True).status, "fail")
        self.assertEqual(ge.check_package_info(self.root, None, False).status, "skip")


class FileHashCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ps.write(self.root / "a.txt", "aaa")
        ps.write(self.root / "sub" / "b.bin", b"bbb", binary=True)
        self.info = {"files": mm.collect_files(self.root)}
        ps.write(self.root / "PACKAGE_INFO.json", "{}")
        ps.write(self.root / "PACKAGE_INFO.md", "x")

    def test_matching_files_pass_and_the_info_files_themselves_are_not_extras(self):
        result = ge.check_file_hashes(self.root, self.info, True)
        self.assertEqual(result.status, "ok")
        self.assertIn("2", result.text)
        self.assertNotIn("목록에 없는", result.text)

    def test_a_missing_file_or_a_changed_byte_fails_and_names_the_file(self):
        (self.root / "a.txt").unlink()
        result = ge.check_file_hashes(self.root, self.info, True)
        self.assertEqual(result.status, "fail")
        self.assertIn("없음 a.txt", result.text)
        ps.write(self.root / "a.txt", "aaa")
        ps.write(self.root / "sub" / "b.bin", b"bbX", binary=True)
        result = ge.check_file_hashes(self.root, self.info, True)
        self.assertEqual(result.status, "fail")
        self.assertIn("다름 sub/b.bin", result.text)

    def test_an_extra_file_is_only_noted_not_failed(self):
        ps.write(self.root / "extra.txt", "e")
        result = ge.check_file_hashes(self.root, self.info, True)
        self.assertEqual(result.status, "ok")
        self.assertIn("extra.txt", result.text)

    def test_many_problems_are_cut_to_five_per_kind(self):
        many = {"files": {f"f{n}.txt": "0" * 64 for n in range(9)}}
        text = ge.check_file_hashes(self.root, many, True).text
        self.assertIn("없음 9", text)
        self.assertEqual(text.count("없음 f"), 5)

    def test_no_list_fails_when_frozen_and_skips_in_source(self):
        for info in (None, {}, {"files": [1]}):
            self.assertEqual(ge.check_file_hashes(self.root, info, True).status, "fail")
            self.assertEqual(ge.check_file_hashes(self.root, info, False).status, "skip")


class LicensesCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        folder = self.root / "LICENSES"
        for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
            ps.write(folder / name, (ps.PACKAGING / "LICENSES" / name).read_bytes(), binary=True)
        ps.write(folder / "PYTHON-LICENSE.txt", "PSF")
        ps.write(folder / "PYINSTALLER-COPYING.txt", "GPL")
        ps.write(folder / "THIRD_PARTY_NOTICES.md", "PySide6 은 LGPL 입니다")

    def test_a_complete_folder_passes(self):
        self.assertEqual(ge.check_licenses(self.root, True).status, "ok")

    def test_each_missing_or_empty_file_fails_and_is_named(self):
        for name in pc.LICENSE_FILES:
            path = self.root / "LICENSES" / name
            data = path.read_bytes()
            for how in ("missing", "empty"):
                with self.subTest(name=name, how=how):
                    path.unlink() if how == "missing" else path.write_bytes(b"")
                    result = ge.check_licenses(self.root, True)
                    self.assertEqual(result.status, "fail")
                    self.assertIn(name, result.text)
                    path.write_bytes(data)

    def test_a_text_that_is_not_the_license_fails(self):
        ps.write(self.root / "LICENSES" / "LGPL-3.0.txt", "something else Version 3")
        self.assertIn("LGPL-3.0.txt 내용", ge.check_licenses(self.root, True).text)
        ps.write(self.root / "LICENSES" / "LGPL-3.0.txt", (ps.PACKAGING / "LICENSES" / "LGPL-3.0.txt").read_bytes(), binary=True)
        ps.write(self.root / "LICENSES" / "GPL-3.0.txt", "nope")
        self.assertIn("GPL-3.0.txt 내용", ge.check_licenses(self.root, True).text)
        ps.write(self.root / "LICENSES" / "GPL-3.0.txt", (ps.PACKAGING / "LICENSES" / "GPL-3.0.txt").read_bytes(), binary=True)
        ps.write(self.root / "LICENSES" / "THIRD_PARTY_NOTICES.md", "빈 고지")
        self.assertIn("THIRD_PARTY_NOTICES.md 내용", ge.check_licenses(self.root, True).text)

    def test_no_folder_fails_when_frozen_and_skips_in_source(self):
        empty = self.root / "none"
        empty.mkdir()
        self.assertEqual(ge.check_licenses(empty, True).status, "fail")
        self.assertEqual(ge.check_licenses(empty, False).status, "skip")


class VendorCheckTest(unittest.TestCase):
    def test_the_real_repository_vendor_passes(self):
        from chanceblog_desktop import core
        result = ge.check_vendor(ps.ROOT, core)
        self.assertEqual(result.status, "ok", result.text)
        self.assertIn("5", result.text)

    def make_core(self, folder):
        return types.SimpleNamespace(vendor_dir=lambda: Path(folder), use_vendored_core=lambda: None)

    def test_a_vendor_folder_in_another_place_than_the_one_next_to_the_exe_fails(self):
        with ps.temp_dir() as tmp:
            root = Path(tmp) / "app"
            root.mkdir()
            result = ge.check_vendor(root, self.make_core(ps.ROOT / "vendor"))
            self.assertEqual(result.status, "fail")
            self.assertIn("경로 가정", result.text)

    def test_a_changed_vendor_file_fails_and_is_named(self):
        with ps.temp_dir() as tmp:
            root = Path(tmp)
            import shutil
            shutil.copytree(ps.ROOT / "vendor", root / "vendor")
            target = root / "vendor" / "pipeline" / "gates.py"
            target.write_bytes(target.read_bytes() + b"\n#x\n")
            result = ge.check_vendor(root, self.make_core(root / "vendor"))
            self.assertEqual(result.status, "fail")
            self.assertIn("pipeline/gates.py", result.text)

    def test_an_unreadable_manifest_fails(self):
        with ps.temp_dir() as tmp:
            root = Path(tmp)
            ps.write(root / "vendor" / "VENDOR.json", "not json")
            result = ge.check_vendor(root, self.make_core(root / "vendor"))
            self.assertEqual(result.status, "fail")
            self.assertIn("VENDOR.json", result.text)

    def test_a_standard_module_the_bundle_lacks_is_found_out(self):
        from chanceblog_desktop import core
        result = ge.check_vendor(ps.ROOT, core, find_spec=lambda name: None if name == "urllib.request" else importlib.util.find_spec(name))
        self.assertEqual(result.status, "fail")
        self.assertIn("urllib.request", result.text)

    def test_a_vendor_module_that_cannot_be_imported_fails_without_the_message(self):
        from chanceblog_desktop import core
        real = ge.importlib.import_module

        def broken(name, *a, **k):
            if name == "pipeline.gates":
                raise ImportError("secret path C:/hidden/dir")
            return real(name, *a, **k)
        with mock.patch.object(ge.importlib, "import_module", broken):
            result = ge.check_vendor(ps.ROOT, core)
        self.assertEqual(result.status, "fail")
        self.assertIn("ImportError", result.text)
        self.assertNotIn("hidden", result.text)


class CapabilitiesCheckTest(unittest.TestCase):
    def fake(self, **values):
        module = types.SimpleNamespace(**values)
        return lambda name: module

    def test_both_gates_false_passes(self):
        self.assertEqual(ge.check_capabilities(import_module=self.fake(EXTERNAL_WRITE=False, BLOGGER_OAUTH_INPUT=False)).status, "ok")

    def test_a_missing_module_fails_with_the_sentence_the_build_looks_for(self):
        def missing(name):
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        result = ge.check_capabilities(import_module=missing)
        self.assertEqual(result.status, "fail")
        self.assertTrue(result.text.startswith(pc.GATE_MISSING_TEXT), result.text)
        self.assertIn("모듈이 없어요", result.text)

    def test_a_module_that_exists_but_fails_inside_is_not_the_missing_module_sentence(self):
        """`--allow-missing-gate` 는 '모듈이 없음' 만 넘긴다 — 모듈은 있는데 안에서 다른 모듈을 못 불러오거나 가져오기가 실패하면 넘기지 않는다(D-419)."""
        def inner_missing(name):
            raise ModuleNotFoundError("No module named 'some_dependency'", name="some_dependency")

        def parent_missing(name):
            raise ModuleNotFoundError("No module named 'chanceblog_desktop'", name="chanceblog_desktop")

        def plain_import_error(name):
            raise ImportError("cannot import name 'x'")
        for label, function in (("inner dependency missing", inner_missing), ("parent package missing", parent_missing), ("plain import error", plain_import_error)):
            with self.subTest(label=label):
                result = ge.check_capabilities(import_module=function)
                self.assertEqual(result.status, "fail")
                self.assertNotIn("모듈이 없어요", result.text)
                self.assertFalse(result.text.startswith(pc.GATE_MISSING_TEXT))
                self.assertIn("오류 종류", result.text)
                self.assertNotIn("some_dependency", result.text)                            # 입력·경로 값은 되풀이하지 않는다 — 오류 종류 이름만

    def test_the_missing_sentence_is_the_one_the_build_waves_through_and_only_that(self):
        missing = ge.check_capabilities(import_module=lambda name: (_ for _ in ()).throw(ModuleNotFoundError(name, name=name)))
        broken = ge.check_capabilities(import_module=lambda name: (_ for _ in ()).throw(ImportError("x")))
        for result, allowed in ((missing, True), (broken, False)):
            parsed = ps.build_package.parse_selftest(f"[실패] capabilities: {result.text}\n")
            ok, _gate, override, _bad = ps.build_package.judge_selftest(parsed, allow_missing_gate=True)
            self.assertEqual(override, allowed)

    def test_an_open_gate_or_a_missing_or_non_boolean_value_fails_and_is_not_the_missing_module_sentence(self):
        cases = {
            "external true": dict(EXTERNAL_WRITE=True, BLOGGER_OAUTH_INPUT=False),
            "blogger true": dict(EXTERNAL_WRITE=False, BLOGGER_OAUTH_INPUT=True),
            "external missing": dict(BLOGGER_OAUTH_INPUT=False),
            "blogger missing": dict(EXTERNAL_WRITE=False),
            "external zero": dict(EXTERNAL_WRITE=0, BLOGGER_OAUTH_INPUT=False),
            "external none": dict(EXTERNAL_WRITE=None, BLOGGER_OAUTH_INPUT=False),
            "blogger empty text": dict(EXTERNAL_WRITE=False, BLOGGER_OAUTH_INPUT=""),
        }
        for name, values in cases.items():
            with self.subTest(name=name):
                result = ge.check_capabilities(import_module=self.fake(**values))
                self.assertEqual(result.status, "fail", name)
                self.assertNotIn("모듈이 없어요", result.text)

    def test_the_real_repository_state_matches_whether_the_module_exists(self):
        result = ge.check_capabilities()
        if GATE_PRESENT:
            self.assertEqual(result.status, "ok", result.text)
        else:
            self.assertEqual(result.status, "fail")
            self.assertIn("모듈이 없어요", result.text)


class UacCheckTest(unittest.TestCase):
    def manifest(self, level):
        return (b"MZ\0\0 binary \0 <assembly><trustInfo><security><requestedPrivileges>"
                b'<requestedExecutionLevel level="' + level.encode("ascii") + b'" uiAccess="false"/></requestedPrivileges></security></trustInfo></assembly> tail')

    def test_as_invoker_passes_and_everything_else_fails(self):
        with ps.temp_dir() as tmp:
            exe = Path(tmp) / "x.exe"
            for level, status in (("asInvoker", "ok"), ("requireAdministrator", "fail"), ("highestAvailable", "fail")):
                exe.write_bytes(self.manifest(level))
                with self.subTest(level=level):
                    result = ge.check_uac_manifest(exe, True)
                    self.assertEqual(result.status, status)
                    if status == "fail":
                        self.assertIn(level, result.text)

    def test_a_missing_manifest_or_unreadable_exe_fails_and_source_runs_skip(self):
        with ps.temp_dir() as tmp:
            exe = Path(tmp) / "x.exe"
            exe.write_bytes(b"MZ no manifest here")
            self.assertEqual(ge.check_uac_manifest(exe, True).status, "fail")
            self.assertEqual(ge.check_uac_manifest(Path(tmp) / "nothing.exe", True).status, "fail")
            self.assertEqual(ge.check_uac_manifest(exe, False).status, "skip")

    def test_the_level_attribute_can_have_spaces_around_the_equals_sign(self):
        with ps.temp_dir() as tmp:
            exe = Path(tmp) / "x.exe"
            exe.write_bytes(b'<requestedExecutionLevel  level = "requireAdministrator"/>')
            self.assertEqual(ge.check_uac_manifest(exe, True).status, "fail")


class GuiOnlyAndDataDirCheckTest(unittest.TestCase):
    def test_the_real_main_passes_with_a_clean_module_table(self):
        self.assertEqual(ge.check_gui_only(ge.main, modules={}).status, "ok")

    def test_a_main_that_accepts_an_argument_or_speaks_more_than_the_fixed_sentence_fails(self):
        def accepting(argv, say=None):
            return 0
        self.assertEqual(ge.check_gui_only(accepting, modules={}).status, "fail")

        def echoing(argv, say=None):
            say(ge.REFUSED + " " + " ".join(argv), error=True)
            return 2
        self.assertEqual(ge.check_gui_only(echoing, modules={}).status, "fail")

        def chatty(argv, say=None):
            say(ge.REFUSED, error=True)
            say("한 번 더", error=True)
            return 2
        self.assertEqual(ge.check_gui_only(chatty, modules={}).status, "fail")

        def wrong_code(argv, say=None):
            say(ge.REFUSED, error=True)
            return 1
        self.assertEqual(ge.check_gui_only(wrong_code, modules={}).status, "fail")

    def test_a_loaded_command_line_module_fails(self):
        for name in ge.CLI_MODULES:
            result = ge.check_gui_only(ge.main, modules={name: object()})
            self.assertEqual(result.status, "fail")
            self.assertIn(name, result.text)

    def test_the_data_dir_check_fails_when_anything_was_created(self):
        with ps.temp_dir() as tmp:
            self.assertEqual(ge.check_data_dir(tmp).status, "ok")
            ps.write(Path(tmp) / "ChanceblogDesktop" / "pycache" / "x.pyc", b"c", binary=True)
            result = ge.check_data_dir(tmp)
            self.assertEqual(result.status, "fail")
            self.assertIn("ChanceblogDesktop", result.text)


class FrozenStrictnessTest(unittest.TestCase):
    RESULTS = [ge.Result("a", "ok", "좋아요"), ge.Result("b", "skip", "건너뛰어요"), ge.Result("c", "fail", "나빠요")]

    def test_a_bundle_cannot_skip_so_every_skip_becomes_a_named_failure(self):
        strict = ge.apply_frozen_strictness(self.RESULTS, True)
        self.assertEqual([item.status for item in strict], ["ok", "fail", "fail"])
        self.assertEqual(strict[1].key, "b")
        self.assertIn("건너뛸 수 없는 점검", strict[1].text)
        self.assertIn("건너뛰어요", strict[1].text)
        self.assertEqual(strict[0], self.RESULTS[0])
        self.assertEqual(strict[2], self.RESULTS[2])

    def test_a_source_run_keeps_its_skips_and_returns_a_copy(self):
        loose = ge.apply_frozen_strictness(self.RESULTS, False)
        self.assertEqual(loose, self.RESULTS)
        self.assertIsNot(loose, self.RESULTS)

    def test_the_exit_code_of_a_strict_bundle_run_is_1_for_a_skip(self):
        self.assertEqual(ge.selftest_exit_code(ge.apply_frozen_strictness([ge.Result("a", "skip", "x")], True)), 1)
        self.assertEqual(ge.selftest_exit_code(ge.apply_frozen_strictness([ge.Result("a", "skip", "x")], False)), 0)


class GuardedAndFormatTest(unittest.TestCase):
    def test_an_unexpected_exception_becomes_a_failure_of_that_check_only(self):
        def boom():
            raise RuntimeError("secret detail C:/x")
        result = ge.guarded(boom, "some_check")
        self.assertEqual((result.key, result.status), ("some_check", "fail"))
        self.assertIn("RuntimeError", result.text)
        self.assertNotIn("secret", result.text)
        self.assertEqual(ge.guarded(lambda: ge.Result("k", "ok", "t"), "k"), ge.Result("k", "ok", "t"))

    def test_results_are_printed_one_line_each_with_the_korean_status_and_a_summary(self):
        results = [ge.Result("a", "ok", "좋아요"), ge.Result("b", "fail", "나빠요"), ge.Result("c", "skip", "건너")]
        lines = ge.format_results(results, "1.2.3")
        self.assertEqual(lines[0], f"ChanceBlog Desktop 1.2.3 자가 점검 — {pc.NOTICE}")
        self.assertEqual(lines[1:4], ["[통과] a: 좋아요", "[실패] b: 나빠요", "[건너뜀] c: 건너"])
        self.assertEqual(lines[4], "결과: 통과 1 · 실패 1 · 건너뜀 1 — 점검 실패")
        self.assertTrue(ge.format_results([ge.Result("a", "ok", "x")], "1")[-1].endswith("모두 정상"))

    def test_the_exit_code_is_1_only_when_something_failed(self):
        self.assertEqual(ge.selftest_exit_code([ge.Result("a", "ok", "x"), ge.Result("b", "skip", "y")]), 0)
        self.assertEqual(ge.selftest_exit_code([ge.Result("a", "ok", "x"), ge.Result("b", "fail", "y")]), 1)

    def test_the_build_can_parse_every_line_the_selftest_prints(self):
        import build_package
        results = [ge.Result("utf8_mode", "ok", "정상 한글"), ge.Result("capabilities", "fail", "모듈이 없어요"), ge.Result("uac_manifest", "skip", "x")]
        parsed = build_package.parse_selftest("\n".join(ge.format_results(results, "0.1.0")))
        self.assertEqual((parsed["passed"], parsed["failed"], parsed["skipped"]), (["utf8_mode"], ["capabilities"], ["uac_manifest"]))

    def test_every_check_name_the_build_requires_is_printed_by_the_entry_as_a_result_key(self):
        tree = ast.parse((ps.PACKAGING / "gui_entry.py").read_text(encoding="utf-8"))
        keys = {node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "Result" and node.args and isinstance(node.args[0], ast.Constant)}
        keys |= {node.args[1].value for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "guarded" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)}
        self.assertEqual(keys, set(ps.SELFTEST_KEYS) | {"app_import"})


class StartGuiTest(unittest.TestCase):
    def test_the_launcher_is_called_without_arguments_and_its_message_is_said_with_its_code(self):
        spoken = []
        with mock.patch("chanceblog_desktop.ui.launcher.main", side_effect=lambda argv, out: (out.write("안내 글\n"), 1)[1]) as launcher, mock.patch.object(ge, "say", lambda text, error=False: spoken.append((text, error))):
            code = ge.start_gui()
        self.assertEqual(code, 1)
        self.assertEqual(launcher.call_args.args[0], [])
        self.assertEqual(spoken, [("안내 글", True)])

    def test_a_clean_exit_says_nothing(self):
        spoken = []
        with mock.patch("chanceblog_desktop.ui.launcher.main", return_value=0), mock.patch.object(ge, "say", lambda text, error=False: spoken.append(text)):
            self.assertEqual(ge.start_gui(), 0)
        self.assertEqual(spoken, [])

    def test_an_exception_shows_only_its_class_name_never_its_message(self):
        spoken = []
        with mock.patch("chanceblog_desktop.ui.launcher.main", side_effect=KeyError("secret " + KEY_SAMPLE)), mock.patch.object(ge, "say", lambda text, error=False: spoken.append((text, error))):
            self.assertEqual(ge.start_gui(), 1)
        self.assertEqual(spoken, [(ge.START_FAILED.format(kind="KeyError"), True)])
        self.assertNotIn(KEY_SAMPLE, spoken[0][0])

    def test_a_system_exit_is_not_swallowed(self):
        with mock.patch("chanceblog_desktop.ui.launcher.main", side_effect=SystemExit(3)):
            with self.assertRaises(SystemExit):
                ge.start_gui()


class FinishTest(unittest.TestCase):
    def test_a_normal_finish_exits_the_usual_way(self):
        with self.assertRaises(SystemExit) as caught:
            ge.finish(4, selftest=False)
        self.assertEqual(caught.exception.code, 4)

    def test_a_selftest_finish_flushes_both_streams_and_exits_hard_with_the_code(self):
        out, err = mock.MagicMock(), mock.MagicMock()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err), mock.patch.object(ge.os, "_exit") as hard:
            ge.finish(1, selftest=True)
        out.flush.assert_called_once_with()
        err.flush.assert_called_once_with()
        hard.assert_called_once_with(1)


class SelftestProcessTest(unittest.TestCase):
    """진짜 새 프로세스로 소스 실행 자가 점검과 인자 거절을 확인한다(묶음에만 있는 것은 '건너뜀')."""

    def run_entry(self, *args, local=None, temp=None):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        env.pop("QT_QPA_PLATFORM", None)
        if local:
            env["LOCALAPPDATA"] = env["XDG_DATA_HOME"] = local
        if temp:
            env["TEMP"] = env["TMP"] = env["TMPDIR"] = temp
        return subprocess.run([sys.executable, "-X", "utf8", str(ps.PACKAGING / "gui_entry.py"), *args], capture_output=True, cwd=str(ps.ROOT), env=env, timeout=300)

    def test_the_source_selftest_prints_korean_utf8_lines_and_fails_only_where_the_gate_is_missing(self):
        with ps.temp_dir() as local, ps.temp_dir() as temp:
            done = self.run_entry("--selftest", local=local, temp=temp)
            self.assertEqual(sorted(path.name for path in Path(local).iterdir()), [], "점검이 진짜 LOCALAPPDATA 자리에 무언가를 만들었다")
            self.assertEqual(sorted(path.name for path in Path(temp).iterdir()), [], "점검이 자기 임시 폴더를 치우지 않았다")
        text = done.stdout.decode("utf-8") + done.stderr.decode("utf-8")
        import build_package
        parsed = build_package.parse_selftest(text)
        self.assertIn(f"ChanceBlog Desktop {(ps.ROOT / 'VERSION').read_text(encoding='utf-8').strip()} 자가 점검", text)
        self.assertEqual(set(parsed["passed"]) | set(parsed["failed"]) | set(parsed["skipped"]), set(ps.SELFTEST_KEYS), text)
        self.assertEqual(len(parsed["passed"]) + len(parsed["failed"]) + len(parsed["skipped"]), len(ps.SELFTEST_KEYS), "같은 점검이 두 번 찍혔다")
        expected_failed = [] if GATE_PRESENT else ["capabilities"]
        self.assertEqual(parsed["failed"], expected_failed, text)
        for key in ("utf8_mode", "version_file", "vendor_core", "gui_only_entry", "data_dir_untouched"):
            self.assertIn(key, parsed["passed"], text)
        for key in ("package_info", "file_hashes", "licenses", "uac_manifest"):
            self.assertIn(key, parsed["skipped"], text)
        self.assertEqual(done.returncode, 1 if expected_failed else 0, text)

    def test_arguments_are_refused_by_a_real_process_with_exit_code_2_and_only_the_fixed_sentence(self):
        for args in (("publish-pages", "--yes"), ("--selftest", "x"), ("doctor",), (KEY_SAMPLE,)):
            with self.subTest(args=args):
                done = self.run_entry(*args)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, b"")
                self.assertEqual(done.stderr.decode("utf-8").replace("\r\n", "\n").strip(), ge.REFUSED)
                self.assertNotIn(KEY_SAMPLE, done.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
