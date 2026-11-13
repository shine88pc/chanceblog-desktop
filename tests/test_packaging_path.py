"""PCFIX1 — 빌드가 PyInstaller 를 부를 때 PATH 를 좁히는 것(D-468)과 묶음 점검 실패 문장의 건수·출처 폴더별 요약 시험.

왜: 운영자가 GitHub 호스트 러너에서 처음 돌린 시험용 Package 빌드가 묶음 점검(허용 뿌리 밖 DLL 거절)에서 멈췄다 — 러너의 PATH 앞에 자바(Temurin JDK 17) bin 폴더가 있어서 PyInstaller 의 DLL 찾기가
UCRT·VC 런타임 DLL(`api-ms-win-core-*.dll` 등)을 그 폴더 것으로 모았다. 이 PC 에서는 같은 실패를 가짜 자바 폴더를 PATH 맨 앞에 넣어 재현했다. 시험은 PyInstaller 없이 돈다(CI 에는 없다 — D-32):
순수 함수(`narrowed_path_folders`·`pyinstaller_env`·`problem_message` 등)와, PyInstaller 자리에 가짜 단계를 끼운 `build` 흐름만 본다. 시험 글에는 역슬래시를 쓰지 않고(슬래시로 적고 `ntpath.normpath` 로 바꾼다)
어느 운영체제에서나 같은 결과가 나오게 폴더 존재 여부는 `isdir` 로 넣는다. 허용 뿌리 검사(`allowed_roots`·`binary_origin_problems`)는 완화하지 않았다는 것도 여기서 지킨다.
"""
import ntpath
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import packaging_support as ps

bp = ps.build_package
mm = ps.make_manifest
pc = ps.pkgcommon

TILDE = chr(0x7E)
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
JAVA_BIN = "C:/hostedtoolcache/windows/Java_Temurin-Hotspot_jdk/17.0.21-9/x64/bin"          # 러너 로그에 나온 자바 폴더
OTHER_JAVA = "C:/Program Files/Java/jdk-17/bin"
SENTINEL = "C:/pcfix1-foreign-sentinel/bin"                                                    # 어느 PC 의 진짜 폴더 이름과도 겹치지 않을 글
RUNNER_PATH = ";".join([JAVA_BIN, OTHER_JAVA, SENTINEL, "C:/Program Files/Git/mingw64/bin", "C:/Windows/system32", "C:/Windows", "C:/hostedtoolcache/windows/Python/3.12.10/x64"])
VENV, BASE = "C:/ccgui/v", "C:/Users/me/AppData/Local/Programs/Python/Python312"
RUNNER_PYTHON = "C:/hostedtoolcache/windows/Python/3.12.10/x64"
LOG_NAMES = ["api-ms-win-core-console-l1-1-0.dll", "api-ms-win-core-datetime-l1-1-0.dll", "api-ms-win-core-debug-l1-1-0.dll", "api-ms-win-core-errorhandling-l1-1-0.dll",
             "api-ms-win-core-fibers-l1-1-0.dll", "api-ms-win-core-fibers-l1-1-1.dll"]       # 운영자가 붙여 준 로그의 앞 여섯 개 이름 그대로


def w(text):
    """슬래시로 적은 경로를 윈도 모양(역슬래시)으로 — 시험 글에 역슬래시를 직접 쓰지 않으려는 것."""
    return ntpath.normpath(text)


def yes(_folder):
    return True


def toc_of(rows):
    return repr(([tuple(row) for row in rows],))


def java_problems(count, roots=None):
    """러너와 같은 모양의 문제 글 — 자바 폴더의 DLL `count` 개(앞 여섯은 로그의 이름)를 진짜 `binary_origin_problems` 로 만든다."""
    names = LOG_NAMES + [f"api-ms-win-core-extra{number:02d}-l1-1-0.dll" for number in range(count)]
    rows = [(name, JAVA_BIN + "/" + name, "BINARY") for name in names[:count]]
    return bp.binary_origin_problems(toc_of(rows), roots or [w(RUNNER_PYTHON), w(RUNNER_PYTHON), "C:/Windows"])


class NarrowedPathFoldersTest(unittest.TestCase):
    def folders(self, environ=None, **kwargs):
        kwargs.setdefault("prefix", VENV)
        kwargs.setdefault("base_prefix", BASE)
        kwargs.setdefault("isdir", yes)
        return bp.narrowed_path_folders({} if environ is None else environ, **kwargs)

    def test_the_folders_are_the_venv_the_base_python_and_the_windows_folders_in_that_order(self):
        expected = [w(item) for item in (VENV, VENV + "/Scripts", BASE, BASE + "/DLLs", BASE + "/Scripts", "C:/Windows/System32", "C:/Windows", "C:/Windows/System32/Wbem")]
        self.assertEqual(self.folders({"SystemRoot": "C:/Windows"}), expected)

    def test_a_runner_path_with_java_git_and_other_folders_in_front_leaves_none_of_them(self):
        found = self.folders({"Path": RUNNER_PATH, "SystemRoot": "C:/Windows"}, prefix=RUNNER_PYTHON, base_prefix=RUNNER_PYTHON)
        self.assertEqual(found, [w(item) for item in (RUNNER_PYTHON, RUNNER_PYTHON + "/Scripts", RUNNER_PYTHON + "/DLLs", "C:/Windows/System32", "C:/Windows", "C:/Windows/System32/Wbem")])
        for foreign in (JAVA_BIN, OTHER_JAVA, SENTINEL, "C:/Program Files/Git/mingw64/bin"):
            self.assertNotIn(w(foreign).lower(), [item.lower() for item in found], foreign)

    def test_without_a_virtual_environment_the_one_python_folder_is_listed_once(self):
        found = self.folders({"SystemRoot": "C:/Windows"}, prefix=BASE, base_prefix=BASE)
        self.assertEqual(found, [w(item) for item in (BASE, BASE + "/Scripts", BASE + "/DLLs", "C:/Windows/System32", "C:/Windows", "C:/Windows/System32/Wbem")])
        self.assertEqual(len({ntpath.normcase(item) for item in found}), len(found))

    def test_a_folder_that_does_not_exist_is_left_out_and_the_rest_keep_their_order(self):
        existing = {w(item) for item in (VENV, BASE, BASE + "/DLLs", "C:/Windows/System32", "C:/Windows")}
        found = self.folders({"SystemRoot": "C:/Windows"}, isdir=existing.__contains__)
        self.assertEqual(found, [w(item) for item in (VENV, BASE, BASE + "/DLLs", "C:/Windows/System32", "C:/Windows")])
        self.assertEqual(self.folders({"SystemRoot": "C:/Windows"}, isdir=lambda folder: False), [])

    def test_the_existence_check_gets_each_folder_once_in_normal_form(self):
        asked = []
        self.folders({"SystemRoot": "C:/Windows/"}, prefix=VENV + "/", base_prefix=VENV + "/", isdir=lambda folder: asked.append(folder) or True)
        self.assertEqual(len(asked), len(set(asked)), asked)                                                         # 같은 폴더를 두 번 묻지 않는다
        self.assertTrue(all(folder == w(folder) for folder in asked), asked)

    def test_the_same_folder_spelled_differently_is_listed_once(self):
        found = self.folders({"SystemRoot": "c:/WINDOWS/"}, prefix="C:/py/", base_prefix="c:/PY")
        self.assertEqual(found[0], w("C:/py"))
        self.assertEqual([item for item in found if item.lower() == w("c:/py").lower()], [w("C:/py")])
        self.assertEqual([ntpath.normcase(item) for item in found if ntpath.normcase(item).endswith("windows")], [w("c:/windows")])
        self.assertEqual(len({ntpath.normcase(item) for item in found}), len(found))

    def test_the_windows_folder_comes_from_systemroot_then_windir_then_the_default_whatever_the_letter_case(self):
        for key in ("SystemRoot", "SYSTEMROOT", "systemroot", "SySteMrOOt"):
            with self.subTest(key=key):
                self.assertIn(w("D:/Win/System32"), self.folders({key: "D:/Win"}))
        self.assertIn(w("E:/W/System32"), self.folders({"windir": "E:/W"}))
        self.assertIn(w("E:/W/System32"), self.folders({"WINDIR": "E:/W"}))
        both = self.folders({"SystemRoot": "D:/Win", "windir": "E:/W"})
        self.assertIn(w("D:/Win/System32"), both)
        self.assertNotIn(w("E:/W/System32"), both)
        self.assertIn(w("C:/Windows/System32"), self.folders({}))
        self.assertIn(w("C:/Windows/System32"), self.folders({"SystemRoot": ""}))

    def test_the_input_path_is_never_read_whatever_it_holds(self):
        base = self.folders({"SystemRoot": "C:/Windows"})
        for value in (RUNNER_PATH, "", None, 5, ["a", "b"], SENTINEL):
            with self.subTest(value=value):
                self.assertEqual(self.folders({"SystemRoot": "C:/Windows", "PATH": value}), base)

    def test_a_folder_name_with_the_path_separator_is_refused_and_never_silently_dropped(self):
        with self.assertRaises(mm.BuildRefused) as caught:
            self.folders({"SystemRoot": "C:/Windows"}, prefix="C:/a;b/v")
        self.assertIn("세미콜론", str(caught.exception))
        self.assertNotIn(TILDE, str(caught.exception))
        self.assertEqual(len(self.folders({"SystemRoot": "C:/Windows"}, prefix="C:/a;b/v", isdir=lambda folder: ";" not in folder)), 6)        # 없는 폴더면 거절할 일이 없다
        with self.assertRaises(mm.BuildRefused):
            self.folders({"SystemRoot": "C:/Win;dows"})

    def test_the_refusal_sentence_hides_the_user_name_in_the_folder(self):
        with self.assertRaises(mm.BuildRefused) as caught:
            self.folders({"SystemRoot": "C:/Windows"}, prefix="C:/Users/alice/a;b")
        self.assertNotIn("alice", str(caught.exception))


class PyInstallerEnvPathTest(unittest.TestCase):
    def env(self, environ, **kwargs):
        kwargs.setdefault("prefix", VENV)
        kwargs.setdefault("base_prefix", BASE)
        kwargs.setdefault("isdir", yes)
        return bp.pyinstaller_env(1794361921, environ, **kwargs)

    def narrowed(self):
        return ";".join(w(item) for item in (VENV, VENV + "/Scripts", BASE, BASE + "/DLLs", BASE + "/Scripts", "C:/Windows/System32", "C:/Windows", "C:/Windows/System32/Wbem"))

    def test_the_machines_path_is_replaced_by_the_narrowed_one(self):
        env = self.env({"PATH": RUNNER_PATH, "SystemRoot": "C:/Windows", "KEEP": "1"})
        self.assertEqual(env["PATH"], self.narrowed())
        for foreign in (JAVA_BIN, OTHER_JAVA, SENTINEL):
            self.assertNotIn(w(foreign).lower(), env["PATH"].lower().split(";"), foreign)
        self.assertEqual(env["KEEP"], "1")

    def test_whatever_the_case_of_the_input_name_exactly_one_path_key_named_path_is_left(self):
        for name in ("PATH", "Path", "path", "pAtH"):
            with self.subTest(name=name):
                env = self.env({name: RUNNER_PATH, "SystemRoot": "C:/Windows"})
                self.assertEqual([key for key in env if key.upper() == "PATH"], ["PATH"])
                self.assertEqual(env["PATH"], self.narrowed())
        both = self.env({"Path": "a", "PATH": "b", "path": "c", "SystemRoot": "C:/Windows"})
        self.assertEqual([key for key in both if key.upper() == "PATH"], ["PATH"])
        self.assertEqual(both["PATH"], self.narrowed())

    def test_an_input_without_any_path_or_without_anything_still_works(self):
        for environ in ({"SystemRoot": "C:/Windows"}, {"KEEP": "1"}, {}):
            with self.subTest(environ=environ):
                env = self.env(environ)
                self.assertEqual([key for key in env if key.upper() == "PATH"], ["PATH"])
                self.assertIn(w("C:/Windows/System32"), env["PATH"].split(";"))
                self.assertEqual(env["PYTHONHASHSEED"], "0")

    def test_no_entry_is_empty_and_none_contains_the_separator(self):
        entries = self.env({"PATH": RUNNER_PATH, "SystemRoot": "C:/Windows"})["PATH"].split(";")
        self.assertTrue(all(entries))
        self.assertEqual(len(entries), 8)
        self.assertEqual(self.env({}, isdir=lambda folder: False)["PATH"], "")

    def test_the_input_dictionary_and_the_real_environment_are_left_alone(self):
        given = {"PATH": RUNNER_PATH, "Path": "x", "PYTHONPATH": "p", "KEEP": "1", "SystemRoot": "C:/Windows"}
        copy = dict(given)
        real = dict(os.environ)
        self.env(given)
        bp.pyinstaller_env(7)
        self.assertEqual(given, copy)
        self.assertEqual(dict(os.environ), real)

    def test_the_other_variables_stay_and_the_older_clean_up_and_fixed_values_still_apply(self):
        env = self.env({"PATH": "p", "SystemRoot": "C:/Windows", "TEMP": "T", "KEEP": "1", "PYTHONPATH": "x", "PYTHONHOME": "h", "PYTHONSTARTUP": "s", "PYTHONOPTIMIZE": "2", "PYTHONINSPECT": "1"})
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONOPTIMIZE", "PYTHONINSPECT"):
            self.assertNotIn(name, env)
        self.assertEqual((env["SystemRoot"], env["TEMP"], env["KEEP"]), ("C:/Windows", "T", "1"))
        self.assertEqual((env["PYTHONHASHSEED"], env["PYTHONUTF8"], env["PYTHONDONTWRITEBYTECODE"], env["SOURCE_DATE_EPOCH"]), ("0", "1", "1", "1794361921"))

    def test_with_the_real_environment_a_foreign_path_never_reaches_the_child(self):
        machine = ";".join([SENTINEL, JAVA_BIN, os.environ.get("PATH", "")])
        with mock.patch.dict(os.environ, {"PATH": machine}):
            env = bp.pyinstaller_env(1)
        self.assertEqual([key for key in env if key.upper() == "PATH"], ["PATH"])
        self.assertNotIn(w(SENTINEL).lower(), env["PATH"].lower())
        self.assertNotIn(w(JAVA_BIN).lower(), env["PATH"].lower())

    @unittest.skipUnless(os.name == "nt", "윈도에서만 폴더 글이 진짜 폴더다")
    def test_on_windows_every_folder_is_a_real_one_of_the_three_allowed_kinds(self):
        env = bp.pyinstaller_env(1)
        entries = env["PATH"].split(";")
        self.assertTrue(entries)
        windows = ntpath.normcase(w(os.environ.get("SystemRoot", "C:/Windows")))
        roots = [ntpath.normcase(w(sys.prefix)), ntpath.normcase(w(sys.base_prefix)), windows]
        for entry in entries:
            self.assertTrue(os.path.isdir(entry), entry)
            self.assertTrue(any(ntpath.normcase(entry) == root or ntpath.normcase(entry).startswith(root + chr(92)) for root in roots), entry)
        self.assertIn(ntpath.normcase(w(sys.base_prefix)), [ntpath.normcase(item) for item in entries])
        self.assertIn(windows + chr(92) + "system32", [ntpath.normcase(item) for item in entries])

    def test_the_info_record_names_the_policy_and_carries_no_folder_or_machine_value(self):
        record = bp.bundle_environment_record(5)
        self.assertEqual(record, {"PYTHONHASHSEED": "0", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "SOURCE_DATE_EPOCH": "5", "PATH_POLICY": "narrow-v1"})
        self.assertEqual(bp.PATH_POLICY, "narrow-v1")
        self.assertNotIn("PATH", record)
        for value in record.values():
            self.assertNotIn(chr(92), value)
            self.assertNotIn(":", value)
        self.assertEqual(bp.bundle_environment_record(5), bp.bundle_environment_record(5))

    def test_the_selftest_and_the_other_children_keep_the_machines_environment(self):
        """좁히는 것은 PyInstaller 를 부르는 환경 하나뿐이다 — 묶음의 자가 점검은 보통 PC 의 PATH 그대로 돈다(PATH 에 기대는 묶음이 숨지 못하게 하자는 것은 아니고, 이 묶음 목적이 아니다)."""
        seen = {}

        def runner(command, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        with mock.patch.dict(os.environ, {"PATH": RUNNER_PATH}):
            bp.run_frozen_selftest(Path("C:/b/x.exe"), runner=runner)
        self.assertEqual(seen["env"]["PATH"], RUNNER_PATH)


class RunPyInstallerTest(unittest.TestCase):
    def test_the_environment_it_is_given_is_what_the_child_gets(self):
        with ps.temp_dir() as tmp:
            env = {"PATH": "narrow", "X": "1"}
            with mock.patch.object(bp.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                code = bp.run_pyinstaller(["--a", "b"], env, Path(tmp), Path(tmp) / "build.log")
            self.assertEqual(code, 0)
            args, kwargs = run.call_args
            self.assertEqual(args[0], [sys.executable, "-s", "-m", "PyInstaller", "--a", "b"])
            self.assertIs(kwargs["env"], env)
            self.assertEqual(kwargs["cwd"], str(Path(tmp)))
            self.assertTrue((Path(tmp) / "build.log").is_file())


class AllowedRootsStayStrictTest(unittest.TestCase):
    """PATH 를 좁혔다고 허용 뿌리 검사를 느슨하게 하지 않았다(완화 금지) — 러너 로그의 자바 폴더 DLL 은 여전히 거절된다."""
    ROOTS = [w(RUNNER_PYTHON), w(RUNNER_PYTHON), "C:/Windows"]

    def test_the_runner_java_folder_dlls_are_still_refused_with_their_origin(self):
        problems = java_problems(6)
        self.assertEqual(len(problems), 6)
        for name, problem in zip(LOG_NAMES, problems):
            self.assertEqual(problem, f"{name}(출처 {JAVA_BIN}/{name})")

    def test_the_python_site_packages_and_windows_folders_of_the_runner_are_still_accepted(self):
        rows = [("python312.dll", RUNNER_PYTHON + "/python312.dll", "BINARY"), ("PySide6/QtCore.pyd", RUNNER_PYTHON + "/Lib/site-packages/PySide6/QtCore.pyd", "EXTENSION"),
                ("msvcp140.dll", "C:/Windows/System32/msvcp140.dll", "BINARY"), ("vcruntime140.dll", RUNNER_PYTHON + "/vcruntime140.dll", "BINARY")]
        self.assertEqual(bp.binary_origin_problems(toc_of(rows), self.ROOTS), [])

    def test_the_allowed_roots_are_still_exactly_three_and_never_contain_a_path_folder(self):
        roots = bp.allowed_roots({"PATH": RUNNER_PATH, "Path": JAVA_BIN, "SystemRoot": "D:/Win"})
        self.assertEqual(roots, [sys.prefix, sys.base_prefix, "D:/Win"])
        for foreign in (JAVA_BIN, OTHER_JAVA, SENTINEL):
            self.assertFalse(any(foreign.lower() in str(root).lower() for root in roots), foreign)

    def test_a_dll_beside_the_python_folder_but_outside_the_roots_is_still_refused(self):
        rows = [("a.dll", RUNNER_PYTHON + "-other/a.dll", "BINARY"), ("b.dll", "C:/hostedtoolcache/windows/Python/3.12.10/b.dll", "BINARY"), ("c.dll", "C:/WindowsOld/c.dll", "BINARY")]
        self.assertEqual(len(bp.binary_origin_problems(toc_of(rows), self.ROOTS)), 3)


class OriginTextTest(unittest.TestCase):
    CASES = [("a.dll", "C:/x/a.dll"), ("PySide6/Qt6Core.dll", "C:/Program Files (x86)/Tool/Qt6Core.dll"), ("foo(1).dll", "C:/x/foo(1).dll"), ("b.pyd", "evil.pyd"),
             ("한글.dll", "D:/폴더 이름/한글.dll"), ("x.dll", "C:/a b/(출처 흉내)/x.dll")]

    def test_the_text_made_from_a_name_and_an_origin_reads_back_the_same(self):
        for name, source in self.CASES:
            with self.subTest(name=name):
                self.assertEqual(bp.origin_of(bp.origin_problem(name, source)), (name, source))

    def test_every_text_the_real_check_makes_reads_back_as_the_same_name_and_origin(self):
        rows = [(name, source, "BINARY") for name, source in self.CASES]
        problems = bp.binary_origin_problems(toc_of(rows), ["C:/ccgui/v"])
        self.assertEqual(len(problems), len(rows))
        for (name, source), problem in zip(self.CASES, problems):
            self.assertEqual(bp.origin_of(problem), (name, source))
            self.assertEqual(problem, f"{name}(출처 {source})")                                  # 예전과 같은 글이다 — 건수·요약을 더해도 앞 문제 글은 그대로

    def test_texts_of_the_other_bundle_checks_have_no_origin(self):
        for text in ("PyInstaller 의 묶음 목록(COLLECT-00.toc)을 읽지 못했어요", "PyInstaller 의 묶음 목록 파일(COLLECT-00.toc)이 없어요", "python312.dll 이 없어요",
                     "Qt 구성 요소가 빠졌어요: PySide6/plugins/platforms/qwindows.dll", "묶음에 있으면 안 되는 파일(사용자 데이터 파일 이름): x/settings.json", "키 모양 글이 든 파일: a.txt", "(출처 없음", ""):
            with self.subTest(text=text):
                self.assertIsNone(bp.origin_of(text))


class ShownFolderTest(unittest.TestCase):
    def test_a_folder_under_users_hides_the_user_name_whatever_the_case_or_slash(self):
        self.assertEqual(bp.shown_folder("C:/Users/alice/AppData/Local/Tool"), w("C:/Users/<사용자>/AppData/Local/Tool"))
        self.assertEqual(bp.shown_folder("c:/users/Alice/x"), w("c:/users/<사용자>/x"))
        self.assertEqual(bp.shown_folder("D:/USERS/bob"), w("D:/USERS/<사용자>"))
        self.assertNotIn("alice", bp.shown_folder("C:/Users/alice"))

    def test_the_profile_folder_of_the_environment_becomes_a_variable_name(self):
        self.assertEqual(bp.shown_folder("D:/Profiles/bob/x/y", "D:/Profiles/bob"), w("%USERPROFILE%/x/y"))
        self.assertEqual(bp.shown_folder("d:/profiles/BOB", "D:/Profiles/bob"), "%USERPROFILE%")
        self.assertEqual(bp.shown_folder("C:/Users/alice/x", "C:/Users/alice"), w("%USERPROFILE%/x"))
        self.assertEqual(bp.shown_folder("D:/Other/x", "D:/Profiles/bob"), w("D:/Other/x"))

    def test_a_drive_root_as_the_profile_folder_does_not_hide_the_whole_drive(self):
        self.assertEqual(bp.shown_folder(RUNNER_PYTHON, "C:/"), w(RUNNER_PYTHON))
        self.assertEqual(bp.shown_folder(RUNNER_PYTHON, "C:"), w(RUNNER_PYTHON))

    def test_runner_and_system_folders_are_shown_as_they_are(self):
        for folder in (RUNNER_PYTHON, JAVA_BIN, "C:/Windows/System32", "C:/Program Files/Git/mingw64/bin", "C:/Usersx/alice", "relative/dir"):
            with self.subTest(folder=folder):
                self.assertEqual(bp.shown_folder(folder), w(folder))


class OriginFolderCountsTest(unittest.TestCase):
    def test_counts_go_per_folder_most_first_then_by_folder_name(self):
        problems = [bp.origin_problem(f"{number}.dll", folder + f"/{number}.dll") for number, folder in enumerate(["C:/b", "C:/a", "C:/b", "C:/c", "C:/a", "C:/b"])]
        self.assertEqual(bp.origin_folder_counts(problems), [(w("C:/b"), 3), (w("C:/a"), 2), (w("C:/c"), 1)])
        tie = [bp.origin_problem("x.dll", "C:/z/x.dll"), bp.origin_problem("y.dll", "C:/Y/y.dll")]
        self.assertEqual([folder for folder, _count in bp.origin_folder_counts(tie)], [w("C:/Y"), w("C:/z")])

    def test_the_same_folder_spelled_with_other_case_slashes_or_dot_dot_is_one_folder(self):
        problems = [bp.origin_problem("a.dll", "C:/Tool/bin/a.dll"), bp.origin_problem("b.dll", "c:/tool/BIN/b.dll"), bp.origin_problem("c.dll", "C:/Tool/x/../bin/c.dll"),
                    bp.origin_problem("d.dll", "C:/Tool/bin/d.dll")]
        counts = bp.origin_folder_counts(problems)
        self.assertEqual(len(counts), 1)
        self.assertEqual(counts[0], (w("C:/Tool/bin"), 4))

    def test_a_relative_origin_has_no_folder_and_is_counted_under_the_unknown_label(self):
        self.assertEqual(bp.origin_folder_counts([bp.origin_problem("evil.dll", "evil.dll")]), [(bp.UNKNOWN_FOLDER, 1)])

    def test_texts_without_an_origin_are_not_counted(self):
        self.assertEqual(bp.origin_folder_counts(["PyInstaller 의 묶음 목록(COLLECT-00.toc)을 읽지 못했어요", "python312.dll 이 없어요"]), [])
        self.assertEqual(bp.origin_folder_counts([]), [])


class ProblemMessageTest(unittest.TestCase):
    def test_the_runner_case_is_counted_and_summarised_in_one_folder(self):
        problems = java_problems(40)
        self.assertEqual(len(problems), 40)
        message = bp.problem_message(problems, home="")
        self.assertTrue(message.startswith("묶음 점검에서 문제가 나왔어요(총 40건): "), message)
        self.assertIn(" / ".join(problems[:6]), message)
        self.assertNotIn(problems[6], message)
        self.assertIn(" / …외 34건", message)
        self.assertTrue(message.endswith(f" — 출처 폴더별 건수: {w(JAVA_BIN)} 40건"), message)
        for name in LOG_NAMES:
            self.assertIn(name, message)

    def test_the_whole_text_is_exactly_this_for_a_small_case(self):
        problems = [bp.origin_problem(f"{letter}.dll", f"C:/p/{letter}.dll") for letter in "abcdefgh"] + ["python312.dll 이 없어요"]
        expected = ("묶음 점검에서 문제가 나왔어요(총 9건): " + " / ".join(problems[:6]) + " / …외 3건 — 출처 폴더별 건수: " + w("C:/p") + " 8건 · 출처를 알 수 없는 문제 1건")
        self.assertEqual(bp.problem_message(problems, home=""), expected)

    def test_six_or_fewer_have_no_remainder_note_and_seven_say_one_more(self):
        six = [bp.origin_problem(f"{number}.dll", f"C:/p/{number}.dll") for number in range(6)]
        self.assertNotIn("…외", bp.problem_message(six, home=""))
        self.assertIn("(총 6건)", bp.problem_message(six, home=""))
        self.assertIn(" / …외 1건", bp.problem_message(six + [bp.origin_problem("6.dll", "C:/p/6.dll")], home=""))
        self.assertIn("(총 1건): 0.dll(출처 C:/p/0.dll) — 출처 폴더별 건수: " + w("C:/p") + " 1건", bp.problem_message(six[:1], home=""))
        self.assertEqual(bp.SHOWN_PROBLEMS, 6)

    def test_several_folders_are_listed_with_their_counts_and_extra_folders_are_rolled_up(self):
        folders = [f"C:/f{number:02d}" for number in range(11)]
        problems = []
        for index, folder in enumerate(folders):
            for copy in range(11 - index):                                                         # 11 건·10 건 … 1 건
                problems.append(bp.origin_problem(f"{index}_{copy}.dll", f"{folder}/{index}_{copy}.dll"))
        message = bp.problem_message(problems, home="")
        self.assertIn("(총 66건)", message)
        summary = message.split(" — 출처 폴더별 건수: ")[1]
        listed = summary.split(" · ")
        self.assertEqual(listed[:8], [f"{w(folders[index])} {11 - index}건" for index in range(8)])
        self.assertEqual(listed[8], "그 밖 3곳 6건")
        self.assertEqual(len(listed), 9)
        self.assertEqual(bp.SHOWN_FOLDERS, 8)

    def test_the_counts_add_up_and_texts_without_an_origin_are_counted_apart(self):
        problems = java_problems(10) + ["Qt 구성 요소가 빠졌어요: PySide6/plugins/platforms/qwindows.dll", "python312.dll 이 없어요"]
        message = bp.problem_message(problems, home="")
        self.assertIn("(총 12건)", message)
        self.assertTrue(message.endswith(f"{w(JAVA_BIN)} 10건 · 출처를 알 수 없는 문제 2건"), message)
        only_other = bp.problem_message(["python312.dll 이 없어요"], home="")
        self.assertEqual(only_other, "묶음 점검에서 문제가 나왔어요(총 1건): python312.dll 이 없어요 — 출처를 알 수 없는 문제 1건")

    def test_the_summary_hides_the_user_name_but_the_leading_problem_texts_stay_as_before(self):
        problems = [bp.origin_problem("first.dll", "C:/Users/alice/AppData/Local/Tool/first.dll")] + java_problems(8)[1:] + [bp.origin_problem("late.dll", "C:/Users/carol/Tool/late.dll")]
        message = bp.problem_message(problems, home="")
        head, summary = message.split(" — 출처 폴더별 건수: ")
        self.assertIn("C:/Users/alice/AppData/Local/Tool/first.dll", head)                        # 앞 문제 글은 예전 그대로
        self.assertNotIn("alice", summary)
        self.assertNotIn("carol", message)                                                       # 일곱 번째 너머의 사용자 폴더는 요약에도 이름이 나오지 않는다
        self.assertIn(w("C:/Users/<사용자>/AppData/Local/Tool") + " 1건", summary)
        self.assertIn(w("C:/Users/<사용자>/Tool") + " 1건", summary)

    def test_the_profile_folder_variable_is_used_for_the_summary_and_the_real_one_by_default(self):
        problems = [bp.origin_problem("a.dll", "D:/Profiles/bob/Tool/a.dll")] * 7
        message = bp.problem_message(problems, home="D:/Profiles/bob")
        self.assertIn("%USERPROFILE%" + chr(92) + "Tool 7건", message)
        with mock.patch.dict(os.environ, {"USERPROFILE": "D:/Profiles/bob"}):
            self.assertEqual(bp.problem_message(problems), message)
        self.assertNotIn("%USERPROFILE%", bp.problem_message(problems, home=""))

    def test_the_text_has_no_tilde_and_no_address(self):
        message = bp.problem_message(java_problems(40) + ["python312.dll 이 없어요"], home="")
        self.assertNotIn(TILDE, message)
        self.assertIsNone(URL.search(message))


@unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
class BuildPathFlowTest(unittest.TestCase):
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

    def test_the_pyinstaller_step_never_sees_the_machines_path(self):
        machine = ";".join([SENTINEL, JAVA_BIN, os.environ.get("PATH", "")])
        with mock.patch.dict(os.environ, {"PATH": machine}):
            fake, _result = self.run_build()
        env = fake.calls[0][2]
        self.assertEqual([key for key in env if key.upper() == "PATH"], ["PATH"])
        self.assertNotIn(w(SENTINEL).lower(), env["PATH"].lower())
        self.assertNotIn(w(JAVA_BIN).lower(), env["PATH"].lower())
        self.assertNotIn(machine, env["PATH"])

    def test_a_path_that_cannot_be_narrowed_is_refused_before_anything_in_the_output_folder_is_deleted(self):
        old = ps.write(self.out / "release" / "old.txt", "이전 빌드")
        ps.write(self.out / bp.OUT_MARKER, "표지")
        fake = ps.FakeBuild(self.root, self.repo)
        with mock.patch.object(bp, "narrowed_path_folders", side_effect=mm.BuildRefused("PATH 에 넣을 수 없어요")):
            with self.assertRaises(mm.BuildRefused):
                self.run_build(fake)
        self.assertEqual(old.read_text(encoding="utf-8"), "이전 빌드")                                       # 지우기 전에 거절했다
        self.assertEqual(fake.calls, [])
        self.assertFalse(any(line.startswith("[2/8]") for line in self.lines))

    def test_the_progress_line_says_the_path_was_narrowed_and_lists_the_folders(self):
        with mock.patch.dict(os.environ, {"PATH": SENTINEL + ";" + os.environ.get("PATH", "")}):                     # git 은 찾아져야 하므로 진짜 PATH 는 뒤에 둔다
            self.run_build()
        self.assertEqual(len(self.lines), 8)
        self.assertTrue(self.lines[1].startswith("[2/8] PyInstaller"), self.lines[1])
        self.assertRegex(self.lines[1], r"PATH 는 \d+곳으로 좁혀서 부름\(")
        self.assertNotIn("sentinel", self.lines[1])
        self.assertTrue(self.lines[1].endswith(")"))

    def test_the_info_files_record_the_policy_and_not_the_machines_path(self):
        _fake, result = self.run_build()
        for path in (self.out / "release" / "PACKAGE_INFO.json", result["bundle"] / "PACKAGE_INFO.json"):
            record = ps.read_json(path)["build"]["env"]
            self.assertEqual(record, bp.bundle_environment_record(ps.COMMIT_EPOCH))
            self.assertEqual(record["PATH_POLICY"], "narrow-v1")
            self.assertNotIn("PATH", record)
        for path in (self.out / "release" / "PACKAGE_INFO.md", result["bundle"] / "PACKAGE_INFO.md"):
            self.assertIn("PATH_POLICY=narrow-v1", path.read_text(encoding="utf-8"))

    def test_machines_with_different_paths_give_the_same_zip_and_the_same_info(self):
        shas, infos = [], []
        real = os.environ.get("PATH", "")                                                                         # git 은 찾아져야 하므로 진짜 PATH 는 늘 들어 있다
        for machine in (SENTINEL + ";" + JAVA_BIN + ";" + real, real, real + ";" + SENTINEL + ";" + JAVA_BIN):
            with mock.patch.dict(os.environ, {"PATH": machine}):
                _fake, result = self.run_build()
            shas.append(result["sha256"])
            infos.append((result["bundle"] / "PACKAGE_INFO.json").read_bytes())
        self.assertEqual(len(set(shas)), 1, shas)
        self.assertEqual(len(set(infos)), 1)

    def test_many_foreign_dlls_stop_the_build_with_the_total_and_the_folder_summary_and_no_release(self):
        fake = ps.FakeBuild(self.root, self.repo)
        fake.toc_rows = ([(f"{pc.EXE_NAME}.exe", "C:/out/x.exe", "EXECUTABLE")]
                         + [(name, JAVA_BIN + "/" + name, "BINARY") for name in LOG_NAMES + [f"api-ms-win-crt-x{number:02d}-l1-1-0.dll" for number in range(24)]]
                         + [("libssl-3-x64.dll", "C:/Program Files/Git/mingw64/bin/libssl-3-x64.dll", "BINARY"), ("libcrypto-3-x64.dll", "C:/Program Files/Git/mingw64/bin/libcrypto-3-x64.dll", "BINARY")])
        with mock.patch.dict(os.environ, {"USERPROFILE": "C:/Users/someone"}):
            with self.assertRaises(mm.BuildRefused) as caught:
                self.run_build(fake)
        message = str(caught.exception)
        self.assertIn("(총 32건)", message)
        self.assertIn(f"{LOG_NAMES[0]}(출처 {JAVA_BIN}/{LOG_NAMES[0]})", message)               # 앞 여섯은 예전 그대로
        self.assertIn(" / …외 26건", message)
        self.assertTrue(message.endswith(f" — 출처 폴더별 건수: {w(JAVA_BIN)} 30건 · {w('C:/Program Files/Git/mingw64/bin')} 2건"), message)
        self.assertFalse((self.out / "release").exists())
        self.assertEqual([call[0] for call in fake.calls], ["pyinstaller"])

    def test_the_bundle_problems_without_an_origin_are_counted_in_the_same_sentence(self):
        fake = ps.FakeBuild(self.root, self.repo)
        original = fake.pyinstaller

        def leaky(args, env, cwd, log_path):
            code = original(args, env, cwd, log_path)
            ps.write(Path(args[args.index("--distpath") + 1]) / pc.EXE_NAME / "_internal" / "libssl-3-x64.dll", b"x", binary=True)
            return code
        fake.steps["pyinstaller"] = leaky
        fake.toc_rows = [(f"{pc.EXE_NAME}.exe", "C:/out/x.exe", "EXECUTABLE"), ("a.dll", "C:/elsewhere/a.dll", "BINARY")]
        with self.assertRaises(mm.BuildRefused) as caught:
            self.run_build(fake)
        message = str(caught.exception)
        self.assertIn("(총 2건)", message)
        self.assertTrue(message.endswith(f" — 출처 폴더별 건수: {w('C:/elsewhere')} 1건 · 출처를 알 수 없는 문제 1건"), message)


def read(rel):
    return (ps.ROOT / rel).read_text(encoding="utf-8")


class DocsTest(unittest.TestCase):
    """문서가 이 묶음의 내용과 한계를 사실대로 적었는지 — 결정 번호는 다른 묶음과 합칠 때 바뀔 수 있으므로 번호를 못박지 않고 제목으로 행을 찾는다(문서끼리 같은 번호를 가리키는지만 본다)."""
    HEADING = re.compile(r"(?m)^## 빌드는 PATH 를 좁힌다 \((D-\d+)\)$")
    TITLES = {"path": "**PyInstaller 를 부를 때 PATH 를 결정적으로 좁힌다", "message": "**묶음 점검 실패 문장에 총 건수·출처 폴더별 건수를 더하고", "measure": "**PCFIX1 의 시험·변이·측정"}

    def section(self):
        text = read("docs/PACKAGE.md")
        found = list(self.HEADING.finditer(text))
        self.assertEqual(len(found), 1)
        return found[0].group(1), text[found[0].end():].split("\n## ")[0]

    def rows(self):
        found = {}
        for line in read("docs/DECISIONS.md").splitlines():
            match = re.match(r"^\| (D-\d+) \| [^|]*\| (\*\*[^|]*)", line)
            if match:
                for key, title in self.TITLES.items():
                    if match.group(2).startswith(title):
                        found[key] = (match.group(1), line)
        return found

    def test_the_package_document_has_the_section_after_the_numbered_ones_and_cites_the_decision_row(self):
        text = read("docs/PACKAGE.md")
        number, _section = self.section()
        self.assertGreater(self.HEADING.search(text).start(), text.index("\n## 10. 한계와 다음 일"))
        self.assertIsNone(re.search(r"(?m)^## \d+\. 빌드는 PATH", text))                              # 번호를 쓰지 않는다(다른 묶음의 절 번호와 겹치지 않게)
        self.assertEqual(self.rows()["path"][0], number)                                            # 절이 가리키는 결정 번호의 행이 바로 그 결정이다

    def test_the_section_names_the_cause_the_choice_the_measurement_and_the_limits_honestly(self):
        _number, section = self.section()
        for needle in ("이슈 #186", "Run workflow", "Java_Temurin", "api-ms-win-core", "_win_includes", "허용 뿌리 검사", "그대로", "narrow-v1", "PATH_POLICY", "Scripts", "DLLs", "Wbem",
                       "System32/downlevel", "46개", "198항목", "158항목", "SHA-256", "같았다", "168개", "가상환경이 없는 파이썬 사본", "셋 다 통과했고", "UPX", "같은 파일이 실제로 있으면", "(총 N건)", "출처 폴더별 건수", "사용자 폴더 이름", "[2/8]", "세미콜론",
                       "러너에서 다시 돌려 확인해야 한다", "여섯 개 너머", "병합 전 상태", "마지막 그물"):
            self.assertIn(needle, section, needle)

    def test_the_section_has_no_tilde_no_address_and_no_backslash(self):
        _number, section = self.section()
        self.assertNotIn(TILDE, section)
        self.assertNotIn(chr(92), section)
        self.assertIsNone(URL.search(section))
        for old_claim in ("같은 입력이면 같은 압축 파일", "같은 도구 버전·같은 Python 이면 같은 압축 파일"):
            self.assertNotIn(old_claim, section)

    def test_the_three_decision_rows_are_there_in_order_well_formed_and_say_their_own_topic(self):
        rows = self.rows()
        self.assertEqual(sorted(rows), ["measure", "message", "path"])
        numbers = [int(rows[key][0][2:]) for key in ("path", "message", "measure")]
        self.assertEqual(numbers, sorted(set(numbers)))
        lines = read("docs/DECISIONS.md").splitlines()
        self.assertEqual([lines.index(rows[key][1]) for key in ("path", "message", "measure")], sorted(lines.index(rows[key][1]) for key in rows))
        for key, (number, row) in rows.items():
            self.assertEqual(row.count(" | "), 3, f"표의 칸은 넷이다: {number}")
            self.assertTrue(row.rstrip().endswith("|"))
            self.assertTrue(row.split("|")[2].strip().startswith("2026-11-13"), number)
            self.assertNotIn(TILDE, row)
            self.assertIsNone(URL.search(row))
        topics = {"path": ("PATH", "narrow-v1", "api-ms-win-core", "허용 뿌리 검사", "#186", "270c7cc", "c6bd62c", "한계", "러너", "System32/downlevel", "198항목", "D-415"),
                  "message": ("problem_message", "origin_problem", "origin_of", "사용자 폴더 이름", "PATH_POLICY", "총 N건", "출처 폴더별 건수", "[2/8]"),
                  "measure": ("변이", "원복", "sha256", "3.12", "3.10", "시험")}
        for key, needles in topics.items():
            for needle in needles:
                self.assertIn(needle, rows[key][1], (key, needle))

    def test_the_changelog_first_section_tells_the_story_in_one_line(self):
        text = read("CHANGELOG.md")
        first = re.search(r"(?m)^## \[([^\]]+)\] — (.+)$", text)
        section = text.split(first.group(0))[1].split("\n## [")[0]
        for needle in ("narrow-v1", "PATH_POLICY", "묶음 점검", "총 건수", "#186", "러너에서 다시"):
            self.assertIn(needle, section, needle)
        self.assertIsNotNone(re.search(r"결정 D-\d+ 에서 D-\d+", section))
        self.assertNotIn(TILDE, section)
        self.assertIsNone(URL.search(section))


class SourceShapeTest(unittest.TestCase):
    def test_nothing_in_the_build_script_changes_the_real_path_or_the_real_environment(self):
        text = (ps.PACKAGING / "build_package.py").read_text(encoding="utf-8")
        for word in ("os.environ[", "os.environ.update", "os.environ.setdefault", "os.putenv", "os.unsetenv", "os.pathsep"):
            self.assertNotIn(word, text, word)

    def test_the_new_text_in_the_script_has_no_tilde_and_no_address(self):
        text = (ps.PACKAGING / "build_package.py").read_text(encoding="utf-8")
        self.assertNotIn(TILDE, text)
        self.assertIsNone(URL.search(text))


if __name__ == "__main__":
    unittest.main()
