"""설치 파일(Inno Setup) 만들기 규칙 시험(V1INSTALL, 결정 D-830 이후) — `packaging/build_installer.py` 와 `packaging/ChanceBlogDesktop.iss` 를 못박는다.
PyInstaller·Inno Setup·네트워크 없이 돈다. 진짜 Inno 가 있는 윈도(GitHub 러너 이미지에는 6.7.1 이 미리 깔려 있다)에서만 도는 **진짜 컴파일 시험 하나**(`RealCompileTest`)가 있다 —
이 PC 에는 Inno 가 없고 설치·내려받기는 금지라 여기서는 건너뛰고, 앱 검사(CI)의 윈도 칸이 생산 `.iss` 를 **처음 진짜로** 컴파일한다(러너에서 처음 확인).

지키는 것:
  1) `.iss` 의 필수 줄(사용자 권한·한국어·설치 폴더·압축·앱 닫기)과 **있으면 안 되는 것**(`[UninstallDelete]`·`[Registry]`·`[Tasks]`·`[Code]`·바탕화면·시작 자동 실행·예약 작업) — 점검 함수 `iss_problems` 가 같은 규칙을 빌드 때도 건다.
  2) ISCC 인자 목록(서명 인자 0·AppId 정의 0·따옴표 0)과 하위 프로세스가 ISCC 한 곳뿐임.
  3) 판 읽기 순서(컴파일 출력 → 레지스트리 → 제품 판 → 파일 판)와 **읽지 못하거나 6.5.0 보다 낮으면 거절**(위협 T11).
  4) 입력 폴더 바이트가 압축 파일과 같음을 해시로 확인(`SHA256SUMS`·`PACKAGE_INFO`·`verify_zip`)하고, 시험 빌드(`TESTBUILD`)에는 설치 파일을 만들지 않음.
  5) 흐름 전체(가짜 ISCC): 설치 파일 이름·크기·바깥 정보의 `installer`·`artifacts` 칸·`SHA256SUMS` 두 줄, 압축 파일과 안쪽 정보는 한 바이트도 안 바뀜.
  6) 제3자 고지문에 'Inno Setup 으로 만든 설치 파일' 사실만(법률 판단 없음).
"""
import ast
import hashlib
import json
import os
import re
import sys
import unittest
import zipfile
from pathlib import Path

import installer_build_support as bs
import packaging_support as ps

bi, mm, pc, bp = bs.bi, bs.mm, bs.pc, bs.bp
OPEN2 = "{" * 2
TILDE = chr(0x7E)
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
ISS_LINES = {                                                         # 시험이 직접 적은 필수 줄 — 점검 함수의 목록과 따로다(둘이 함께 약해지지 않게)
    "Setup": ("AppId=" + OPEN2 + "CF5B18A9-6CBC-4916-9978-7729E88B70C8}", "AppName=ChanceBlog Desktop", "AppVersion={#AppVersion}", "AppPublisher=ChanceBlog", "DefaultDirName={autopf}\\ChanceBlogDesktop",
              "DisableProgramGroupPage=yes", "PrivilegesRequired=lowest", "OutputDir={#OutputDir}", "OutputBaseFilename={#OutBase}", "Compression=lzma2/max", "SolidCompression=yes",
              "CloseApplications=yes", "RestartApplications=yes", "WizardStyle=modern", "UninstallDisplayIcon={app}\\ChanceBlogDesktop.exe", "ArchitecturesInstallIn64BitMode=x64compatible"),
    "Languages": ('Name: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"',),
    "Files": ('Source: "{#SourceDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs',),
    "Icons": ('Name: "{autoprograms}\\ChanceBlog Desktop"; Filename: "{app}\\ChanceBlogDesktop.exe"',),
    "Run": ('Filename: "{app}\\ChanceBlogDesktop.exe"; Flags: nowait postinstall skipifsilent',),
}


def iss_text():
    return bs.ISS_PATH.read_text(encoding="utf-8")


def sections_of(text):
    """`.iss` 를 구역별 코드 줄(주석·빈 줄 뺀)로 나눈다 — 시험이 점검 함수와 따로 읽는다."""
    found, current = {}, None
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        match = re.fullmatch(r"\[([A-Za-z]+)\]", line)
        if match:
            current = match.group(1)
            found.setdefault(current, [])
        elif current is not None:
            found[current].append(line)
    return found


class IssFileTest(unittest.TestCase):
    def setUp(self):
        self.text = iss_text()
        self.sections = sections_of(self.text)

    def test_the_script_is_a_utf8_file_without_bom_and_every_code_line_is_ascii(self):
        raw = bs.ISS_PATH.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        raw.decode("utf-8")
        for number, line in enumerate(self.text.splitlines(), 1):
            if line.strip() and not line.lstrip().startswith(";"):
                self.assertTrue(line.isascii(), f"{number}행: 코드 줄에 한글이나 ASCII 가 아닌 글자가 있다(한글은 주석뿐 — 한국어 화면은 Korean.isl)")
        self.assertTrue(any(not line.isascii() for line in self.text.splitlines() if line.lstrip().startswith(";")), "주석에는 한글 설명이 있다")

    def test_no_tilde_no_web_address_and_the_double_brace_is_only_in_the_app_id_line(self):
        self.assertNotIn(TILDE, self.text)
        self.assertIsNone(URL.search(self.text))
        for line in self.text.splitlines():
            if OPEN2 in line:
                self.assertTrue(line.startswith("AppId="), line)

    def test_only_the_five_allowed_sections_exist_in_this_order(self):
        order = re.findall(r"(?m)^\[([A-Za-z]+)\]\s*$", self.text)
        self.assertEqual(order, ["Setup", "Languages", "Files", "Icons", "Run"])

    def test_the_required_lines_are_there_exactly_once_and_nothing_else_is_in_those_sections(self):
        for name, wanted in ISS_LINES.items():
            lines = [line for line in self.sections[name] if not line.startswith("#") and line != "SetupIconFile={#IconFile}"]
            self.assertEqual(sorted(lines), sorted(wanted), name)
        self.assertEqual(sum(1 for line in self.sections["Setup"] if line == "SetupIconFile={#IconFile}"), 1)

    def test_the_icon_directive_is_inside_an_ifdef_guard_so_a_missing_icon_means_the_default_icon(self):
        lines = self.sections["Setup"]
        start = lines.index("#ifdef IconFile")
        self.assertEqual(lines[start:start + 3], ["#ifdef IconFile", "SetupIconFile={#IconFile}", "#endif"])
        self.assertEqual(sum(1 for line in lines if line.startswith("SetupIconFile")), 1)

    def test_none_of_the_forbidden_sections_or_constants_are_in_the_script(self):
        lowered = self.text.lower()
        code = "\n".join(line for line in lowered.splitlines() if not line.lstrip().startswith(";"))
        for section in ("uninstalldelete", "uninstallrun", "installdelete", "registry", "tasks", "code", "ini", "dirs", "components", "types", "custommessages", "messages", "langoptions"):
            self.assertNotIn(f"[{section}]", code, section)
        for token in ("{autodesktop}", "{userdesktop}", "{commondesktop}", "{userstartup}", "{commonstartup}", "{autostartup}", "{localappdata}", "{userappdata}", "{commonappdata}", "{userdocs}",
                      "{commondocs}", "{%", "{reg:", "{code:", "{cmd", "schtasks", "powershell", "cmd.exe", "taskkill", "reg.exe", "runonce", "hkcu", "hklm", "type: filesandordirs"):
            self.assertNotIn(token, code, token)

    def test_the_user_permission_install_folder_korean_and_close_applications_lines_are_the_ones_the_design_asks_for(self):
        setup = self.sections["Setup"]
        for line in ("PrivilegesRequired=lowest", "DefaultDirName={autopf}\\ChanceBlogDesktop", "CloseApplications=yes", "RestartApplications=yes", "DisableProgramGroupPage=yes",
                     "Compression=lzma2/max", "SolidCompression=yes", "ArchitecturesInstallIn64BitMode=x64compatible", "UninstallDisplayIcon={app}\\ChanceBlogDesktop.exe"):
            self.assertIn(line, setup, line)
        self.assertEqual(self.sections["Languages"], ['Name: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"'])
        self.assertNotIn("PrivilegesRequiredOverridesAllowed", self.text)
        self.assertNotIn("DisableReadyPage", self.text, "마지막 확인 쪽(설치 위치를 보여 주는)은 끄지 않는다")

    def test_one_start_menu_shortcut_and_no_desktop_icon_and_the_run_line_skips_a_silent_install(self):
        self.assertEqual(self.sections["Icons"], ['Name: "{autoprograms}\\ChanceBlog Desktop"; Filename: "{app}\\ChanceBlogDesktop.exe"'])
        run = self.sections["Run"]
        self.assertEqual(len(run), 1)
        self.assertIn("postinstall", run[0])
        self.assertIn("skipifsilent", run[0])
        self.assertIn("nowait", run[0])

    def test_the_files_section_copies_the_bundle_folder_and_nothing_is_deleted_by_the_script(self):
        self.assertEqual(self.sections["Files"], ['Source: "{#SourceDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs'])
        for word in ("deleteafterinstall", "external", "restartreplace", "uninsneveruninstall", "onlyifdoesntexist"):
            self.assertNotIn(word, self.text.lower())

    def test_the_names_in_the_script_are_the_constants(self):
        setup = self.sections["Setup"]
        self.assertIn("AppName=" + pc.PRODUCT, setup)
        self.assertIn("AppPublisher=" + pc.INNO_PUBLISHER, setup)
        self.assertIn("AppId=" + pc.INNO_APP_ID, setup)
        self.assertIn("DefaultDirName={autopf}\\" + pc.INSTALL_DIR_NAME, setup)
        self.assertIn("UninstallDisplayIcon={app}\\" + pc.EXE_NAME + ".exe", setup)
        self.assertIn('Filename: "{app}\\' + pc.EXE_NAME + '.exe"; Flags: nowait postinstall skipifsilent', self.sections["Run"])

    def test_the_default_output_name_define_is_the_setup_name_pattern(self):
        self.assertIn('#define OutBase "ChanceBlogDesktop-" + AppVersion + "-Setup"', self.text)
        self.assertEqual(pc.setup_name("9.9.9")[:-len(".exe")], "ChanceBlogDesktop-9.9.9-Setup")

    def test_the_script_has_no_personal_value_and_no_license_or_info_file_pages(self):
        for word in ("\\Users\\", "/Users/", "@", "LicenseFile", "InfoBeforeFile", "InfoAfterFile", "AppPublisherURL", "AppSupportURL", "AppUpdatesURL"):
            self.assertNotIn(word, self.text, word)

    def test_the_point_checker_finds_nothing_in_the_real_script(self):
        self.assertEqual(bi.iss_problems(self.text), [])
        self.assertEqual(bi.iss_problems(self.text.replace("\n", "\r\n")), [])


def drop(*needles):
    return lambda text: "\n".join(line for line in text.split("\n") if not any(needle in line for needle in needles))


def replace(old, new):
    def change(text):
        assert text.count(old) == 1, old                                                  # 변이가 정확히 한 곳만 바꾸는지 시험 자신이 확인한다
        return text.replace(old, new)
    return change


def append(more):
    return lambda text: text.rstrip("\n") + "\n" + more + "\n"


def insert_after(line, more):
    return replace(line, line + "\n" + more)


ISS_MUTANTS = {
    "PrivilegesRequired 삭제": drop("PrivilegesRequired"),
    "PrivilegesRequired 를 관리자로": replace("PrivilegesRequired=lowest", "PrivilegesRequired=admin"),
    "PrivilegesRequiredOverridesAllowed 더하기": insert_after("PrivilegesRequired=lowest", "PrivilegesRequiredOverridesAllowed=commandline dialog"),
    "UninstallDelete 에 데이터 폴더": append('[UninstallDelete]\nType: filesandordirs; Name: "{localappdata}\\ChanceblogDesktop"'),
    "UninstallRun 구역": append('[UninstallRun]\nFilename: "{app}\\ChanceBlogDesktop.exe"'),
    "InstallDelete 구역": append('[InstallDelete]\nType: filesandordirs; Name: "{app}\\old"'),
    "Registry 구역": append('[Registry]\nRoot: HKCU; Subkey: "Software\\ChanceBlog"; ValueType: string; ValueName: "x"; ValueData: "y"'),
    "Tasks 구역과 바탕화면 아이콘": append('[Tasks]\nName: "desktopicon"; Description: "x"'),
    "Code 구역": append("[Code]\nprocedure Nothing;\nbegin\nend;"),
    "바탕화면 아이콘 더하기": insert_after('Name: "{autoprograms}\\ChanceBlog Desktop"; Filename: "{app}\\ChanceBlogDesktop.exe"', 'Name: "{autodesktop}\\ChanceBlog Desktop"; Filename: "{app}\\ChanceBlogDesktop.exe"'),
    "시작 자동 실행 아이콘 더하기": insert_after('Name: "{autoprograms}\\ChanceBlog Desktop"; Filename: "{app}\\ChanceBlogDesktop.exe"', 'Name: "{userstartup}\\ChanceBlog Desktop"; Filename: "{app}\\ChanceBlogDesktop.exe"'),
    "skipifsilent 삭제": replace(" skipifsilent", ""),
    "postinstall 삭제": replace(" postinstall", ""),
    "AppId 이스케이프 제거": replace("AppId=" + OPEN2, "AppId={"),
    "AppId 를 다른 GUID 로": replace("CF5B18A9-6CBC-4916-9978-7729E88B70C8", "CF5B18A9-6CBC-4916-9978-7729E88B70C9"),
    "AppId 가 두 줄": insert_after("AppName=ChanceBlog Desktop", "AppId=other"),
    "CloseApplications 삭제": drop("CloseApplications=yes"),
    "RestartApplications 삭제": drop("RestartApplications=yes"),
    "DefaultDirName 을 데이터 폴더로": replace("DefaultDirName={autopf}\\ChanceBlogDesktop", "DefaultDirName={localappdata}\\ChanceblogDesktop"),
    "DefaultDirName 을 Program Files 고정으로": replace("DefaultDirName={autopf}\\ChanceBlogDesktop", "DefaultDirName=C:\\Program Files\\ChanceBlogDesktop"),
    "한국어 삭제": drop("MessagesFile"),
    "영어 안내 더하기": insert_after('Name: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"', 'Name: "english"; MessagesFile: "compiler:Default.isl"'),
    "압축 없음": replace("Compression=lzma2/max", "Compression=none"),
    "게시자에 개인 이름": replace("AppPublisher=ChanceBlog", "AppPublisher=Some Person"),
    "출력 이름 고정": replace("OutputBaseFilename={#OutBase}", "OutputBaseFilename=Setup"),
    "원본 폴더를 다른 곳으로": replace('Source: "{#SourceDir}\\*"', 'Source: "{userdocs}\\*"'),
    "파일 복사에 삭제 플래그": replace("createallsubdirs", "createallsubdirs deleteafterinstall"),
    "코드 줄에 한글": insert_after("AppName=ChanceBlog Desktop", "AppComments=한글 설명"),
    "전처리 include": insert_after("#ifndef SourceDir", '#include "other.iss"'),
    "아이콘 정의를 조건 밖으로": replace("#ifdef IconFile\nSetupIconFile={#IconFile}\n#endif\n", "SetupIconFile={#IconFile}\n"),
    "아이콘 파일 고정 경로": replace("SetupIconFile={#IconFile}", "SetupIconFile=C:\\x.ico"),
    "레지스트리 상수": insert_after("AppName=ChanceBlog Desktop", "AppComments={reg:HKCU\\Software\\x,y}"),
    "예약 작업 실행": append('[Run]\nFilename: "schtasks.exe"; Parameters: "/create"'),
}


class IssPointCheckerTest(unittest.TestCase):
    def test_every_mutated_script_is_refused_by_the_checker(self):
        text = iss_text()
        self.assertGreaterEqual(len(ISS_MUTANTS), 30)
        for name, change in ISS_MUTANTS.items():
            with self.subTest(mutant=name):
                self.assertNotEqual(change(text), text, name)
                self.assertTrue(bi.iss_problems(change(text)), name)

    def test_the_problem_texts_name_what_is_wrong(self):
        text = iss_text()
        joined = lambda change: "\n".join(bi.iss_problems(change(text)))      # noqa: E731
        self.assertIn("UninstallDelete", joined(ISS_MUTANTS["UninstallDelete 에 데이터 폴더"]))
        self.assertIn("바탕화면", joined(ISS_MUTANTS["바탕화면 아이콘 더하기"]))
        self.assertIn("시작", joined(ISS_MUTANTS["시작 자동 실행 아이콘 더하기"]))
        self.assertIn("PrivilegesRequired=lowest", joined(ISS_MUTANTS["PrivilegesRequired 삭제"]))
        self.assertIn("AppId", joined(ISS_MUTANTS["AppId 이스케이프 제거"]))
        self.assertIn("skipifsilent", joined(ISS_MUTANTS["skipifsilent 삭제"]))

    def test_comments_blank_lines_and_line_endings_do_not_matter(self):
        text = iss_text()
        self.assertEqual(bi.iss_problems("; 맨 앞 주석\n\n" + text.replace("\n", "\r\n") + "\n; 끝 주석\n"), [])
        self.assertEqual(bi.iss_problems(text.replace("AppName=ChanceBlog Desktop", "  AppName=ChanceBlog Desktop   ")), [])
        self.assertEqual(bi.iss_problems(text.replace("[Setup]", "[setup]")), [])

    def test_a_section_name_in_another_letter_case_is_still_a_forbidden_section(self):
        self.assertTrue(bi.iss_problems(append("[uninstalldelete]\nType: files; Name: x")(iss_text())))
        self.assertTrue(bi.iss_problems(append("[REGISTRY]\nRoot: HKCU")(iss_text())))

    def test_not_a_text_or_an_empty_text_is_refused(self):
        for bad in (None, 3, "", "   \n", b"bytes"):
            with self.subTest(bad=bad):
                self.assertTrue(bi.iss_problems(bad))


class IsccArgsTest(unittest.TestCase):
    ARGS = dict(version="0.1.0-preview.1", source_dir="C:/out/bundle/ChanceBlogDesktop-0.1.0-preview.1", out_dir="C:/out/work/installer", out_base="ChanceBlogDesktop-0.1.0-preview.1-Setup")

    def make(self, **change):
        return bi.iscc_args("C:/x/ISCC.exe", "C:/repo/packaging/ChanceBlogDesktop.iss", **dict(self.ARGS, **change))

    def test_the_argument_list_is_exactly_this(self):
        self.assertEqual(self.make(), ["C:/x/ISCC.exe", "/OC:/out/work/installer", "/FChanceBlogDesktop-0.1.0-preview.1-Setup", "/DAppVersion=0.1.0-preview.1",
                                       "/DSourceDir=C:/out/bundle/ChanceBlogDesktop-0.1.0-preview.1", "C:/repo/packaging/ChanceBlogDesktop.iss"])

    def test_an_icon_adds_one_define_and_no_icon_adds_none(self):
        self.assertNotIn("IconFile", " ".join(self.make()))
        with_icon = self.make(icon="C:/repo/packaging/ChanceBlogDesktop.ico")
        self.assertEqual([arg for arg in with_icon if "IconFile" in arg], ["/DIconFile=C:/repo/packaging/ChanceBlogDesktop.ico"])
        self.assertEqual(with_icon[-1], "C:/repo/packaging/ChanceBlogDesktop.iss")

    def test_no_signing_switch_no_app_id_define_no_quote_and_the_script_is_last(self):
        for args in (self.make(), self.make(icon="C:/i.ico")):
            self.assertFalse([arg for arg in args[1:] if arg.upper().startswith(("/S", "/DAPPID", "/DOUTPUTDIR", "/DOUTBASE"))], args)       # `/S<이름>=<명령>` 은 서명 도구를 부르는 길이다 — 이 갈래는 서명하지 않는다
            self.assertFalse([arg for arg in args if '"' in arg or "\n" in arg or "\0" in arg], args)
            self.assertTrue(args[-1].endswith(".iss"))
            self.assertEqual(args[0], "C:/x/ISCC.exe")
            self.assertTrue(all(isinstance(arg, str) for arg in args))

    def test_values_with_a_quote_a_control_character_or_a_bad_version_are_refused(self):
        for bad in ({"version": '0.1.0" /Ssigntool'}, {"version": "0.1"}, {"version": "x"}, {"source_dir": 'C:/a"b'}, {"source_dir": "C:/a\nb"}, {"out_dir": 'C:/a"b'}, {"out_dir": "C:/a\0b"},
                    {"out_base": 'x"y'}, {"out_base": ""}, {"icon": 'C:/a"b.ico'}):
            with self.subTest(bad=bad):
                with self.assertRaises(mm.BuildRefused):
                    self.make(**bad)

    def test_the_out_base_must_be_the_setup_name_of_the_version(self):
        with self.assertRaises(mm.BuildRefused):
            self.make(out_base="ChanceBlogDesktop-9.9.9-Setup")
        with self.assertRaises(mm.BuildRefused):
            self.make(out_base="Other-0.1.0-preview.1-Setup")


class VersionTextTest(unittest.TestCase):
    def test_numbers_are_read_from_text(self):
        self.assertEqual(bi.version_numbers("Inno Setup 6.7.1"), (6, 7, 1))
        self.assertEqual(bi.version_numbers("6.7"), (6, 7))
        self.assertEqual(bi.version_numbers("6.7.1.0"), (6, 7, 1, 0))
        self.assertIsNone(bi.version_numbers("no digits"))
        self.assertIsNone(bi.version_numbers(""))
        self.assertIsNone(bi.version_numbers(None))

    def test_all_zero_and_single_number_versions_are_not_a_reading(self):
        for numbers in ((0, 0, 0, 0), (0, 0), (6,), (), None):
            self.assertIsNone(bi.real_version(numbers), numbers)
        self.assertEqual(bi.real_version((6, 7, 1)), (6, 7, 1))
        self.assertEqual(bi.real_version((0, 1)), (0, 1))

    def test_the_compiler_text_gives_the_engine_version_only_from_the_engine_line(self):
        self.assertEqual(bi.inno_text_version(bs.compile_text("6.7.1")), (6, 7, 1))
        self.assertEqual(bi.inno_text_version("compiler ENGINE version:   inno setup 6.5.0\n"), (6, 5, 0))
        self.assertEqual(bi.inno_text_version("a\r\nCompiler engine version: Inno Setup 7.0\r\nb"), (7, 0))
        for text in ("Inno Setup 6 Command-Line Compiler\nCopyright", "Inno Setup 6.7.1 mentioned elsewhere", "Compiler engine version: unknown", "", None, "Compiler engine version: Inno Setup 0.0.0.0"):
            with self.subTest(text=text):
                self.assertIsNone(bi.inno_text_version(text))

    def test_the_registry_entry_of_the_folder_the_compiler_is_in_is_the_one_read(self):
        entries = [("Inno Setup 5", "5.6.1", "C:\\Program Files (x86)\\Inno Setup 5\\"), ("Inno Setup version 6.7.1", "6.7.1", "C:\\Program Files (x86)\\Inno Setup 6\\"),
                   ("Other Tool", "9.9.9", "C:\\Program Files (x86)\\Inno Setup 6\\")]
        self.assertEqual(bi.registry_version(entries, "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"), (6, 7, 1))
        self.assertEqual(bi.registry_version(entries, "c:\\program files (x86)\\inno setup 6\\iscc.exe"), (6, 7, 1))
        self.assertEqual(bi.registry_version(entries, "C:/Program Files (x86)/Inno Setup 5/ISCC.exe"), (5, 6, 1))

    def test_a_registry_entry_for_another_folder_or_without_a_real_version_is_not_a_reading(self):
        path = "D:/tools/inno/ISCC.exe"
        for entries in ([("Inno Setup version 6.7.1", "6.7.1", "C:\\Program Files (x86)\\Inno Setup 6\\")], [("Inno Setup 6", "0.0.0.0", "D:\\tools\\inno\\")], [("Inno Setup 6", "", "D:\\tools\\inno\\")],
                        [("Inno Setup 6", "6.7.1", "")], [("Inno Setup 6", "6.7.1", "D:\\tools\\inno2\\")], [("Unrelated", "6.7.1", "D:\\tools\\inno\\")], [], None):
            with self.subTest(entries=entries):
                self.assertIsNone(bi.registry_version(entries, path))
        self.assertEqual(bi.registry_version([("Inno Setup 6", "6.7.1", "D:\\tools\\inno\\")], path), (6, 7, 1))


class ReadOrderTest(unittest.TestCase):
    PATH = bs.ISCC_PATH
    REGISTRY = [("Inno Setup version 6.6.0", "6.6.0", "C:\\Program Files (x86)\\Inno Setup 6\\")]

    def read(self, *, compile_output="", registry=REGISTRY, versions=("6.4.0.0", "6.3.0.0")):
        host = bs.FakeHost(registry=registry, file_versions=versions)
        return bi.read_inno_version(host, self.PATH, compile_output)

    def test_the_order_is_compile_output_then_registry_then_product_then_file(self):
        first = self.read(compile_output=bs.compile_text("6.7.1"))
        self.assertEqual((first["numbers"], first["source"]), ((6, 7, 1), "컴파일 출력"))
        second = self.read()
        self.assertEqual((second["numbers"], second["source"]), ((6, 6, 0), "레지스트리"))
        third = self.read(registry=())
        self.assertEqual((third["numbers"], third["source"]), ((6, 4, 0, 0), "파일 제품 판"))
        fourth = self.read(registry=(), versions=("0.0.0.0", "6.3.0.0"))
        self.assertEqual((fourth["numbers"], fourth["source"]), ((6, 3, 0, 0), "파일 판"))

    def test_an_empty_all_zero_reading_is_passed_over_to_the_next_source(self):
        result = self.read(compile_output="Compiler engine version: Inno Setup 0.0.0.0", registry=[("Inno Setup 6", "0.0.0.0", "C:\\Program Files (x86)\\Inno Setup 6\\")], versions=("0.0.0.0", "6.3.0.0"))
        self.assertEqual((result["numbers"], result["source"]), ((6, 3, 0, 0), "파일 판"))

    def test_when_nothing_is_readable_the_numbers_are_empty_and_the_reasons_are_listed(self):
        result = self.read(registry=(), versions=("0.0.0.0", "0.0.0.0"))
        self.assertIsNone(result["numbers"])
        self.assertEqual(result["source"], "")
        for word in ("컴파일 출력", "레지스트리", "파일 제품 판", "파일 판"):
            self.assertIn(word, result["reason"])
        self.assertEqual(set(result["reads"]), {"compile", "registry", "product", "file"})

    def test_all_four_readings_are_kept_even_when_the_first_one_wins(self):
        result = self.read(compile_output=bs.compile_text("6.7.1"))
        self.assertEqual(result["reads"], {"compile": "6.7.1", "registry": "6.6.0", "product": "6.4.0.0", "file": "6.3.0.0"})


class JudgeTest(unittest.TestCase):
    def judge(self, numbers):
        return bi.judge_inno_version({"numbers": numbers, "source": "시험", "reads": {}, "reason": "읽지 못함"})

    def test_a_readable_version_at_or_above_the_minimum_passes(self):
        for numbers in ((6, 5, 0), (6, 5, 0, 0), (6, 5), (6, 7, 1), (7, 0, 0), (7, 1, 1), (10, 0, 0), (6, 5, 1)):
            with self.subTest(numbers=numbers):
                self.assertEqual(self.judge(numbers), numbers)

    def test_a_lower_version_is_refused_and_the_text_says_which_one(self):
        for numbers in ((6, 4, 3), (6, 4, 99), (6, 0, 0), (5, 6, 1), (6, 4), (0, 9, 9)):
            with self.subTest(numbers=numbers):
                with self.assertRaises(mm.BuildRefused) as caught:
                    self.judge(numbers)
                self.assertIn("6.5.0", str(caught.exception))
                self.assertIn(".".join(str(item) for item in numbers), str(caught.exception))

    def test_an_unreadable_version_is_refused_not_waved_through(self):
        for numbers in (None, (), (0, 0, 0, 0)):
            with self.subTest(numbers=numbers):
                with self.assertRaises(mm.BuildRefused) as caught:
                    self.judge(numbers)
                self.assertIn("읽지 못했어요", str(caught.exception))
                self.assertIn("읽지 못함", str(caught.exception))                       # 읽은 곳별 이유가 문장에 실린다

    def test_the_minimum_comes_from_the_shared_constant(self):
        self.assertEqual(pc.INNO_MIN_VERSION, (6, 5, 0))
        self.assertEqual(self.judge(pc.INNO_MIN_VERSION), pc.INNO_MIN_VERSION)


class FindIsccTest(unittest.TestCase):
    ENV = {"ProgramFiles(x86)": "C:\\Program Files (x86)", "ProgramFiles": "C:\\Program Files", "LOCALAPPDATA": "C:\\Users\\Example\\AppData\\Local"}

    def test_an_explicit_path_wins_then_the_environment_variable_then_the_path_then_the_known_folders(self):
        explicit, from_env, on_path = "D:/a/ISCC.exe", "D:/b/ISCC.exe", "D:/c/ISCC.exe"
        host = bs.FakeHost(found=(on_path, explicit, from_env, bs.ISCC_PATH), environ=dict(self.ENV, CHANCEBLOG_ISCC=from_env))
        self.assertEqual(bi.find_iscc(host, explicit), explicit)
        self.assertEqual(bi.find_iscc(host), from_env)
        host = bs.FakeHost(found=(on_path, bs.ISCC_PATH), environ=dict(self.ENV))
        self.assertEqual(bi.find_iscc(host), on_path)
        host = bs.FakeHost(found=(bs.ISCC_PATH,), on_path=False, environ=dict(self.ENV))
        self.assertEqual(bi.find_iscc(host), bs.ISCC_PATH.replace("/", "\\"))

    def test_the_known_folders_are_the_inno_6_install_folders_of_both_program_files_and_the_user_programs(self):
        for found in ("C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe", "C:\\Program Files\\Inno Setup 6\\ISCC.exe", "C:\\Users\\Example\\AppData\\Local\\Programs\\Inno Setup 6\\ISCC.exe"):
            with self.subTest(found=found):
                host = bs.FakeHost(found=(found,), on_path=False, environ=dict(self.ENV))
                self.assertEqual(norm(bi.find_iscc(host)), norm(found))

    def test_without_environment_values_the_standard_c_drive_folders_are_tried(self):
        host = bs.FakeHost(found=("C:/Program Files (x86)/Inno Setup 6/ISCC.exe",), on_path=False, environ={})
        self.assertEqual(norm(bi.find_iscc(host)), norm("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"))

    def test_environment_names_are_matched_without_regard_to_letter_case(self):
        host = bs.FakeHost(found=("D:/x/ISCC.exe",), on_path=False, environ={"chanceblog_iscc": "D:/x/ISCC.exe"})
        self.assertEqual(bi.find_iscc(host), "D:/x/ISCC.exe")

    def test_a_missing_compiler_is_refused_with_a_plain_sentence(self):
        with self.assertRaises(mm.BuildRefused) as caught:
            bi.find_iscc(bs.FakeHost(found=(), on_path=False, environ=dict(self.ENV)))
        self.assertIn("ISCC.exe", str(caught.exception))
        self.assertIn("CHANCEBLOG_ISCC", str(caught.exception))

    def test_an_explicit_path_that_is_not_there_or_not_the_compiler_is_refused_and_not_replaced_by_another(self):
        host = bs.FakeHost(found=(bs.ISCC_PATH, "D:/a/other.exe"), environ=dict(self.ENV))
        for explicit in ("D:/nowhere/ISCC.exe", "D:/a/other.exe", ""):
            with self.subTest(explicit=explicit):
                if explicit == "":
                    self.assertEqual(norm(bi.find_iscc(host, explicit or None)), norm(bs.ISCC_PATH))
                    continue
                with self.assertRaises(mm.BuildRefused):
                    bi.find_iscc(host, explicit)


def norm(path):
    return bs.norm(path)


class HostTest(unittest.TestCase):
    def test_the_child_environment_drops_names_that_look_like_secrets_and_keeps_the_rest(self):
        environment = {"PATH": "x", "SystemRoot": "C:\\Windows", "TEMP": "t", "UPDATE_SIGNING_KEY": "v", "GITHUB_TOKEN": "v", "MY_PASSWORD": "v", "AWS_SECRET_ACCESS_KEY": "v", "CLIENT_CREDENTIALS": "v",
                       "PRIVATE_THING": "v", "OPENAI_API_KEY": "v", "SOME_API_KEY": "v", "ImageOS": "win25", "HOME": "h"}
        kept = bi.Host(environ=environment).child_env()
        self.assertEqual(sorted(kept), ["HOME", "ImageOS", "PATH", "SystemRoot", "TEMP"])

    def test_only_the_compiler_can_be_run_and_nothing_goes_through_a_shell(self):
        host = bi.Host(environ={})
        for program in ("cmd.exe", "powershell", "C:/Windows/System32/cmd.exe", "git", "", "ISCC.exe.bat", "C:/x/iscc.exe.exe"):
            with self.subTest(program=program):
                with self.assertRaises(mm.BuildRefused):
                    host.run_iscc([program, "/Q"], timeout=5)

    def test_the_real_registry_reading_returns_a_list_of_three_text_tuples(self):
        entries = bi.Host().registry_entries()
        self.assertIsInstance(entries, list)
        for entry in entries:
            self.assertEqual(len(entry), 3)
            self.assertTrue(all(isinstance(item, str) for item in entry))
            self.assertTrue(entry[0].lower().startswith("inno setup"))
        if sys.platform != "win32":
            self.assertEqual(entries, [])

    @unittest.skipUnless(sys.platform == "win32", "파일 버전 자원은 윈도 파일에만 있다")
    def test_the_real_file_versions_are_read_from_a_windows_file_and_a_missing_file_gives_empty_texts(self):
        kernel = os.path.join(os.environ.get("SystemRoot") or "C:\\Windows", "System32", "kernel32.dll")
        product, file_version = bi.Host().file_versions(kernel)
        for text in (product, file_version):
            numbers = bi.real_version(bi.version_numbers(text))
            self.assertIsNotNone(numbers, text)
            self.assertGreaterEqual(numbers[0], 6)
        self.assertEqual(bi.Host().file_versions(os.path.join(os.environ.get("SystemRoot") or "C:\\Windows", "System32", "no_such_file_here.dll")), ("", ""))

    def test_the_file_versions_of_a_folder_or_a_file_without_a_version_resource_are_empty_texts(self):
        with bs.temp_dir() as tmp:
            plain = ps.write(Path(tmp) / "plain.bin", b"MZ" + bytes(200), binary=True)
            self.assertEqual(bi.Host().file_versions(str(plain)), ("", ""))
            self.assertEqual(bi.Host().file_versions(tmp), ("", ""))

    def test_the_real_sha256_is_the_file_hash(self):
        with bs.temp_dir() as tmp:
            data = ps.write(Path(tmp) / "a.bin", b"abc", binary=True)
            self.assertEqual(bi.Host().sha256(str(data)), hashlib.sha256(b"abc").hexdigest())

    def test_which_finds_a_file_on_the_given_path_only(self):
        with bs.temp_dir() as tmp:
            os.chmod(ps.write(Path(tmp) / "ISCC.exe", b"MZ", binary=True), 0o755)             # 리눅스의 which 는 실행 권한이 있는 파일만 찾는다
            self.assertTrue(bi.Host(environ={"PATH": tmp}).which("ISCC.exe"))
            self.assertIsNone(bi.Host(environ={"PATH": ""}).which("ISCC.exe"))


class SumsTest(unittest.TestCase):
    def test_a_sums_text_is_read_into_names_and_digests(self):
        good = "a" * 64 + "  one.zip\n" + "b" * 64 + "  two.exe\n"
        self.assertEqual(bi.parse_sums(good), {"one.zip": "a" * 64, "two.exe": "b" * 64})

    def test_a_sums_text_with_a_bad_line_a_duplicate_or_a_wrong_length_is_refused(self):
        for bad in ("a" * 63 + "  one.zip\n", "A" * 64 + "  one.zip\n", "a" * 64 + " one.zip\n", "a" * 64 + "  one.zip\n" + "b" * 64 + "  one.zip\n", "a" * 64 + "  sub/one.zip\n",
                    "a" * 64 + "  one.zip extra\n", "\n", "", "text"):
            with self.subTest(bad=bad):
                with self.assertRaises(mm.BuildRefused):
                    bi.parse_sums(bad)


@unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
class ReleaseInputsTest(unittest.TestCase):
    """진짜 `build_package.build`(가짜 PyInstaller)가 만든 출력 폴더를 입력으로 — 입력 확인이 어디서 거절하는지."""

    @classmethod
    def setUpClass(cls):
        cls.good, cls.trial = bs.shared_outs()

    def setUp(self):
        self.work = bs.temp_dir()
        self.addCleanup(self.work.cleanup)
        self.out = bs.copy_out(self.good, Path(self.work.name) / "out")
        self.release = self.out / "release"
        self.zip = self.release / pc.zip_name(ps.VERSION)

    def refused(self, *needles):
        with self.assertRaises(mm.BuildRefused) as caught:
            bi.read_release(self.out)
        for needle in needles:
            self.assertIn(needle, str(caught.exception))
        return str(caught.exception)

    def edit_info(self, change):
        path = self.release / "PACKAGE_INFO.json"
        info = json.loads(path.read_text(encoding="utf-8"))
        change(info)
        path.write_bytes(mm.render_json(info).encode("utf-8"))

    def test_a_good_output_folder_is_read_into_what_the_build_needs(self):
        found = bi.read_release(self.out)
        self.assertEqual(found["version"], ps.VERSION)
        self.assertEqual(found["top"], pc.top_folder(ps.VERSION))
        self.assertEqual(Path(found["bundle"]).name, pc.top_folder(ps.VERSION))
        self.assertEqual(Path(found["zip"]).name, pc.zip_name(ps.VERSION))
        self.assertEqual(found["info"]["variant"], "outer")
        self.assertEqual(found["package"], {"name": pc.zip_name(ps.VERSION), "sha256": pc.sha256_file(self.zip), "bytes": self.zip.stat().st_size})

    def test_a_folder_that_build_package_did_not_make_is_refused_before_anything_is_read(self):
        (self.out / bp.OUT_MARKER).unlink()
        self.refused("표지")
        with bs.temp_dir() as empty:
            with self.assertRaises(mm.BuildRefused):
                bi.read_release(Path(empty))
        with self.assertRaises(mm.BuildRefused):
            bi.read_release(self.out / "does-not-exist")

    def test_a_missing_sums_file_is_refused(self):
        (self.release / "SHA256SUMS").unlink()
        self.refused("SHA256SUMS")

    def test_a_missing_or_broken_info_file_is_refused(self):
        (self.release / "PACKAGE_INFO.json").write_bytes(b"{ not json")
        self.refused("정보 파일")
        (self.release / "PACKAGE_INFO.json").unlink()
        self.refused("정보 파일")

    def test_a_missing_zip_or_a_missing_bundle_folder_is_refused(self):
        self.zip.unlink()
        self.refused("압축 파일")

    def test_a_missing_bundle_folder_is_refused(self):
        import shutil
        shutil.rmtree(self.out / "bundle")
        self.refused("묶음 폴더")

    def test_a_trial_build_never_gets_a_setup_file(self):
        self.out = bs.copy_out(self.trial, Path(self.work.name) / "trial_out")
        message = self.refused("시험 빌드")
        self.assertIn(pc.TRIAL_TAG, message)

    def test_a_trial_flag_in_the_info_alone_is_enough_to_refuse(self):
        self.edit_info(lambda info: info.__setitem__("trial", True))
        self.refused("시험 빌드")

    def test_a_build_that_is_not_release_eligible_is_refused(self):
        self.edit_info(lambda info: info.__setitem__("release_eligible", False))
        self.refused("관문")

    def test_an_inner_info_file_or_a_wrong_schema_or_product_is_refused(self):
        for change in (lambda info: info.__setitem__("variant", "inner"), lambda info: info.__setitem__("schema", 2), lambda info: info.__setitem__("product", "Other"),
                       lambda info: info.__setitem__("version", "not-a-version")):
            with self.subTest(change=change):
                good = (self.release / "PACKAGE_INFO.json").read_bytes()
                self.edit_info(change)
                with self.assertRaises(mm.BuildRefused):
                    bi.read_release(self.out)
                (self.release / "PACKAGE_INFO.json").write_bytes(good)

    def test_a_zip_whose_hash_differs_from_the_info_or_the_sums_is_refused(self):
        self.edit_info(lambda info: info["package"].__setitem__("sha256", "0" * 64))
        self.refused("해시")

    def test_a_zip_whose_size_differs_from_the_info_is_refused(self):
        self.edit_info(lambda info: info["package"].__setitem__("bytes", info["package"]["bytes"] + 1))
        self.refused("크기")

    def test_a_sums_file_that_does_not_list_the_zip_or_lists_another_digest_is_refused(self):
        (self.release / "SHA256SUMS").write_bytes(("0" * 64 + "  " + pc.zip_name(ps.VERSION) + "\n").encode("utf-8"))
        self.refused("SHA256SUMS")
        (self.release / "SHA256SUMS").write_bytes((pc.sha256_file(self.zip) + "  other.zip\n").encode("utf-8"))
        self.refused("SHA256SUMS")

    def test_a_bundle_file_changed_after_the_zip_was_made_is_refused(self):
        target = self.out / "bundle" / pc.top_folder(ps.VERSION) / "vendor" / "VENDOR.json"
        target.write_bytes(target.read_bytes() + b" ")
        self.refused("달라요")

    def test_an_extra_bundle_file_is_refused(self):
        ps.write(self.out / "bundle" / pc.top_folder(ps.VERSION) / "extra.txt", "x")
        self.refused("달라요")

    def test_a_bundle_file_missing_from_the_folder_is_refused(self):
        (self.out / "bundle" / pc.top_folder(ps.VERSION) / "VERSION").unlink()
        self.refused()

    def test_a_zip_with_a_changed_member_is_refused_by_the_zip_check(self):
        bundle = self.out / "bundle" / pc.top_folder(ps.VERSION)
        with zipfile.ZipFile(self.zip) as archive:
            members = [(item, archive.read(item)) for item in archive.infolist()]
        with zipfile.ZipFile(self.zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item, data in members:
                archive.writestr(item, data + b"!" if item.filename.endswith("VERSION") else data)
        info = json.loads((self.release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        info["package"] = {"name": self.zip.name, "sha256": pc.sha256_file(self.zip), "bytes": self.zip.stat().st_size}
        (self.release / "PACKAGE_INFO.json").write_bytes(mm.render_json(info).encode("utf-8"))
        (self.release / "SHA256SUMS").write_bytes(mm.render_sums([(self.zip.name, info["package"]["sha256"])]).encode("utf-8"))
        self.assertTrue(bundle.is_dir())
        self.refused("달라요")

    def test_the_bundle_version_file_must_match_the_info_version(self):
        target = self.out / "bundle" / pc.top_folder(ps.VERSION) / "VERSION"
        target.write_bytes(b"9.9.9\n")
        self.refused()

    def test_the_bundle_and_zip_check_is_the_one_in_build_package_and_it_is_called(self):
        source = (ps.PACKAGING / "build_installer.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertIn("bp.verify_zip", calls)
        self.assertIn("mm.collect_files", calls)


class FlowBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good, cls.trial = bs.shared_outs()

    def setUp(self):
        self.work = bs.temp_dir()
        self.addCleanup(self.work.cleanup)
        self.out = bs.copy_out(self.good, Path(self.work.name) / "out")
        self.release = self.out / "release"
        self.lines = []

    def run_build(self, host=None, **options):
        host = host or bs.FakeHost()
        result = bi.build(bi.Options(out_dir=self.out, **options), host=host, say=self.lines.append)
        return host, result

    def snapshot(self):
        """출력 폴더의 모든 파일의 {상대 경로: 해시} — 흐름이 건드리면 안 되는 것을 견주는 데 쓴다."""
        return {path.relative_to(self.out).as_posix(): pc.sha256_file(path) for path in sorted(self.out.rglob("*")) if path.is_file()}


@unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
class BuildFlowTest(FlowBase):
    def test_the_whole_flow_makes_the_setup_file_next_to_the_zip_and_calls_the_compiler_once(self):
        host, result = self.run_build()
        self.assertEqual(len(host.calls), 1)
        setup = self.release / pc.setup_name(ps.VERSION)
        self.assertTrue(setup.is_file())
        self.assertEqual(result["setup"], setup)
        self.assertEqual(result["name"], "ChanceBlogDesktop-0.1.0-preview.1-Setup.exe")
        self.assertEqual(result["bytes"], setup.stat().st_size)
        self.assertEqual(result["sha256"], pc.sha256_file(setup))
        self.assertEqual(sorted(path.name for path in self.release.iterdir()), sorted([pc.zip_name(ps.VERSION), pc.setup_name(ps.VERSION), "PACKAGE_INFO.json", "PACKAGE_INFO.md", "SHA256SUMS"]))
        self.assertEqual(len(self.lines), 7)
        self.assertTrue(self.lines[0].startswith("[1/7]") and self.lines[-1].startswith("[7/7]"))

    def test_the_compiler_gets_the_checked_arguments_from_the_real_script_and_the_bundle_folder(self):
        host, _result = self.run_build()
        args = host.calls[0]["args"]
        bundle = (self.out / "bundle" / pc.top_folder(ps.VERSION))
        self.assertEqual(args[0], bs.ISCC_PATH)
        self.assertEqual(Path(args[-1]), bs.ISS_PATH)
        self.assertIn("/DAppVersion=" + ps.VERSION, args)
        self.assertEqual(Path(next(arg for arg in args if arg.startswith("/DSourceDir="))[len("/DSourceDir="):]), bundle)
        self.assertEqual(next(arg for arg in args if arg.startswith("/F"))[2:], pc.setup_name(ps.VERSION)[:-4])
        stage = Path(next(arg for arg in args if arg.startswith("/O"))[2:])
        self.assertEqual(stage, self.out / "work" / "installer")
        self.assertFalse([arg for arg in args if arg.upper().startswith("/S") or "IconFile" in arg])
        self.assertEqual(Path(host.calls[0]["cwd"]), bs.ISS_PATH.parent)
        self.assertGreaterEqual(host.calls[0]["timeout"], 600)

    def test_the_zip_the_bundle_and_the_inner_info_are_not_changed_by_a_single_byte(self):
        before = self.snapshot()
        self.run_build()
        after = self.snapshot()
        for name, digest in before.items():
            if name.startswith("release/PACKAGE_INFO") or name == "release/SHA256SUMS":
                continue
            self.assertEqual(after[name], digest, name)
        self.assertEqual(after["release/" + pc.zip_name(ps.VERSION)], before["release/" + pc.zip_name(ps.VERSION)])
        added = sorted(set(after) - set(before))
        self.assertEqual(added, ["release/" + pc.setup_name(ps.VERSION)], "만든 설치 파일 하나만 늘고 임시 폴더의 사본은 치운다")

    def test_the_outer_info_gets_the_installer_and_artifacts_columns_and_nothing_else_changes(self):
        before = json.loads((self.release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertNotIn("installer", before)
        self.assertNotIn("artifacts", before)
        _host, result = self.run_build(host=bs.FakeHost())
        after = json.loads((self.release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        for key, value in before.items():
            self.assertEqual(after[key], value, key)
        self.assertEqual(set(after) - set(before), {"installer", "artifacts"})
        self.assertEqual(after["schema"], 1)
        self.assertEqual(set(after["installer"]), {"tool", "tool_version", "iscc_sha256", "built_on"})
        self.assertEqual(after["installer"]["tool"], "inno-setup")
        self.assertEqual(after["installer"]["tool_version"], "6.7.1")
        self.assertEqual(after["installer"]["iscc_sha256"], pc.sha256_bytes(("fake-iscc:" + bs.norm(bs.ISCC_PATH)).encode("utf-8")))
        self.assertRegex(after["installer"]["iscc_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(after["artifacts"], {"setup": {"name": pc.setup_name(ps.VERSION), "sha256": result["sha256"], "bytes": result["bytes"]},
                                              "portable": {"name": pc.zip_name(ps.VERSION), "sha256": pc.sha256_file(self.release / pc.zip_name(ps.VERSION)), "bytes": (self.release / pc.zip_name(ps.VERSION)).stat().st_size}})
        self.assertEqual(after["artifacts"]["portable"], after["package"])

    def test_the_sums_file_lists_both_files_and_checks_out_like_sha256sum(self):
        self.run_build()
        text = (self.release / "SHA256SUMS").read_text(encoding="utf-8")
        found = bi.parse_sums(text)
        self.assertEqual(sorted(found), sorted([pc.zip_name(ps.VERSION), pc.setup_name(ps.VERSION)]))
        for name, digest in found.items():
            self.assertEqual(pc.sha256_file(self.release / name), digest, name)
        self.assertEqual(text, "".join(f"{found[name]}  {name}\n" for name in sorted(found)))
        self.assertNotIn("\r", text)

    def test_the_markdown_copy_shows_the_installer_section_and_the_json_markdown_pair_agrees(self):
        self.run_build()
        markdown = (self.release / "PACKAGE_INFO.md").read_text(encoding="utf-8")
        self.assertIn("## 설치 파일(Inno Setup)", markdown)
        self.assertIn(pc.setup_name(ps.VERSION), markdown)
        self.assertIn("6.7.1", markdown)
        self.assertNotIn(TILDE, markdown)
        self.assertIsNone(URL.search(markdown))
        info = json.loads((self.release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertEqual(markdown, mm.render_markdown(info))

    def test_the_built_on_is_the_runner_image_when_the_environment_names_it_and_local_otherwise(self):
        self.run_build(host=bs.FakeHost(environ={"ImageOS": "win25-vs2026", "ImageVersion": "20261116.315.1"}))
        self.assertEqual(json.loads((self.release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))["installer"]["built_on"], "win25-vs2026 20261116.315.1")
        self.out = bs.copy_out(self.good, Path(self.work.name) / "out2")
        self.release = self.out / "release"
        self.run_build(host=bs.FakeHost(environ={}))
        self.assertEqual(json.loads((self.release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))["installer"]["built_on"], "local")
        self.out = bs.copy_out(self.good, Path(self.work.name) / "out3")
        self.release = self.out / "release"
        self.run_build(host=bs.FakeHost(environ={"IMAGEOS": "win25-vs2026", "IMAGEVERSION": "1.2"}))                 # 윈도는 환경 변수 이름의 대소문자를 가리지 않는다
        self.assertEqual(json.loads((self.release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))["installer"]["built_on"], "win25-vs2026 1.2")

    def test_no_path_of_this_pc_and_no_user_name_goes_into_the_info_files(self):
        self.run_build()
        for name in ("PACKAGE_INFO.json", "PACKAGE_INFO.md", "SHA256SUMS"):
            text = (self.release / name).read_text(encoding="utf-8")
            self.assertNotIn(str(self.out), text)
            self.assertNotIn(self.work.name, text)
            self.assertNotIn("Program Files", text)

    def test_an_icon_that_exists_is_passed_and_one_that_does_not_is_refused(self):
        icon = ps.write(Path(self.work.name) / "mine.ico", b"icon-bytes", binary=True)
        host, _ = self.run_build(host=bs.FakeHost(found=(bs.ISCC_PATH, str(icon))), icon=str(icon))
        self.assertIn("/DIconFile=" + str(icon), host.calls[0]["args"])
        self.out = bs.copy_out(self.good, Path(self.work.name) / "out2")
        with self.assertRaises(mm.BuildRefused):
            bi.build(bi.Options(out_dir=self.out, icon=str(Path(self.work.name) / "none.ico")), host=bs.FakeHost(), say=self.lines.append)

    def test_running_twice_replaces_the_installer_columns_instead_of_stacking_them(self):
        self.run_build()
        first = (self.release / "PACKAGE_INFO.json").read_bytes()
        self.run_build()
        second = (self.release / "PACKAGE_INFO.json").read_bytes()
        info = json.loads(second.decode("utf-8"))
        self.assertEqual(sorted(k for k in info if k in ("installer", "artifacts")), ["artifacts", "installer"])
        self.assertEqual(first, second)
        self.assertEqual(len(bi.parse_sums((self.release / "SHA256SUMS").read_text(encoding="utf-8"))), 2)


@unittest.skipUnless(ps.HAVE_GIT, "git 이 있어야 한다")
class RefusalFlowTest(FlowBase):
    def refused(self, host, *needles, **options):
        before = self.snapshot()
        with self.assertRaises(mm.BuildRefused) as caught:
            bi.build(bi.Options(out_dir=self.out, **options), host=host, say=self.lines.append)
        for needle in needles:
            self.assertIn(needle, str(caught.exception))
        after = self.snapshot()
        self.assertEqual({k: v for k, v in after.items() if not k.startswith("work/installer/")}, before, "거절하면 출력 폴더의 기존 파일은 한 바이트도 바뀌지 않는다")
        self.assertFalse((self.release / pc.setup_name(ps.VERSION)).exists(), "거절한 빌드는 설치 파일을 release 에 내놓지 않는다")
        return str(caught.exception)

    def test_a_trial_build_is_refused_before_the_compiler_is_even_looked_for(self):
        self.out = bs.copy_out(self.trial, Path(self.work.name) / "trial_out")
        self.release = self.out / "release"
        host = bs.FakeHost()
        self.refused(host, "시험 빌드")
        self.assertEqual(host.calls, [])
        self.assertEqual(host.hashed, [])

    def test_a_system_that_is_not_windows_is_refused_first(self):
        host = bs.FakeHost(platform="linux")
        self.refused(host, "Windows")
        self.assertEqual(host.calls, [])

    def test_a_missing_compiler_is_refused(self):
        host = bs.FakeHost(found=(), on_path=False, environ={})
        self.refused(host, "ISCC.exe")
        self.assertEqual(host.calls, [])

    def test_a_compiler_known_to_be_too_old_is_refused_before_it_runs(self):
        host = bs.FakeHost(registry=[("Inno Setup version 6.4.3", "6.4.3", "C:\\Program Files (x86)\\Inno Setup 6\\")])
        self.refused(host, "6.4.3", "6.5.0")
        self.assertEqual(host.calls, [], "읽을 수 있는 낮은 판이면 컴파일하지 않는다")

    def test_a_compiler_that_says_it_is_too_old_in_its_own_output_is_refused_and_leaves_no_setup(self):
        host = bs.FakeHost(compile_text=bs.compile_text("6.4.0"), registry=[("Inno Setup version 6.7.1", "6.7.1", "C:\\Program Files (x86)\\Inno Setup 6\\")])
        self.refused(host, "6.4.0")
        self.assertEqual(len(host.calls), 1)
        self.assertFalse(list((self.out / "work").glob("installer/*.exe")), "낮은 판이 만든 설치 파일은 지운다")

    def test_a_compiler_whose_version_cannot_be_read_anywhere_is_refused_and_leaves_no_setup(self):
        host = bs.FakeHost(compile_text="", registry=(), file_versions=("0.0.0.0", "0.0.0.0"))
        message = self.refused(host, "읽지 못했어요")
        self.assertIn("레지스트리", message)
        self.assertEqual(len(host.calls), 1)
        self.assertFalse(list((self.out / "work").glob("installer/*.exe")))

    def test_a_failing_compile_is_refused_with_the_tail_of_its_output_and_the_exit_code(self):
        host = bs.FakeHost(exit_code=2, compile_text="Compiler engine version: Inno Setup 6.7.1\nError on line 12: boom\n")
        message = self.refused(host, "종료 코드 2", "boom")
        self.assertNotIn(str(self.out), message.replace(str(self.out / "work" / "installer"), ""))

    def test_a_compile_that_runs_too_long_is_refused(self):
        self.refused(bs.FakeHost(timed_out=True), "시간")

    def test_a_compile_that_makes_no_setup_file_is_refused(self):
        self.refused(bs.FakeHost(make_setup=False), "설치 파일")

    def test_a_setup_file_that_is_not_an_executable_or_too_big_is_refused(self):
        class NotPe(bs.FakeHost):
            def run_iscc(self, args, *, timeout, cwd=None):
                result = super().run_iscc(args, timeout=timeout, cwd=cwd)
                target = Path(next(a for a in args if a.startswith("/O"))[2:]) / (next(a for a in args if a.startswith("/F"))[2:] + ".exe")
                target.write_bytes(b"not an executable at all")
                return result
        self.refused(NotPe(), "실행 파일")
        self.refused(bs.FakeHost(setup_bytes=bi.MAX_SETUP_BYTES + 1), "너무 커요")

    def test_a_setup_that_is_empty_is_refused(self):
        self.refused(bs.FakeHost(setup_bytes=0), "설치 파일")

    def test_a_script_that_breaks_the_rules_is_refused_before_the_compiler_runs(self):
        bad = Path(self.work.name) / "Bad.iss"
        bad.write_bytes((iss_text() + "\n[UninstallDelete]\nType: filesandordirs; Name: x\n").encode("utf-8"))
        host = bs.FakeHost()
        with self.assertRaises(mm.BuildRefused) as caught:
            bi.build(bi.Options(out_dir=self.out), host=host, say=self.lines.append, iss_path=bad)
        self.assertIn("UninstallDelete", str(caught.exception))
        self.assertEqual(host.calls, [])

    def test_the_zip_and_bundle_check_runs_before_the_compiler(self):
        target = self.out / "bundle" / pc.top_folder(ps.VERSION) / "VERSION"
        target.write_bytes(target.read_bytes() + b"x")
        host = bs.FakeHost()
        with self.assertRaises(mm.BuildRefused):
            bi.build(bi.Options(out_dir=self.out), host=host, say=self.lines.append)
        self.assertEqual(host.calls, [])
        self.assertEqual(host.hashed, [])

    def test_a_missing_script_file_is_refused(self):
        with self.assertRaises(mm.BuildRefused):
            bi.build(bi.Options(out_dir=self.out), host=bs.FakeHost(), say=self.lines.append, iss_path=Path(self.work.name) / "missing.iss")


class WithInstallerTest(unittest.TestCase):
    RECORD = {"tool": "inno-setup", "tool_version": "6.7.1", "iscc_sha256": "a" * 64, "built_on": "local"}
    ARTIFACTS = {"setup": {"name": pc.setup_name(ps.VERSION), "sha256": "b" * 64, "bytes": 10}, "portable": {"name": pc.zip_name(ps.VERSION), "sha256": "f" * 64, "bytes": 12345}}

    def test_the_two_columns_are_added_to_an_outer_info_without_touching_the_old_ones(self):
        info = ps.sample_info("outer")
        newer = mm.with_installer(info, self.RECORD, self.ARTIFACTS)
        self.assertEqual({key: value for key, value in newer.items() if key not in ("installer", "artifacts")}, info)
        self.assertEqual(newer["installer"], self.RECORD)
        self.assertEqual(newer["artifacts"], self.ARTIFACTS)
        self.assertNotIn("installer", info)
        self.assertEqual(newer["schema"], 1)

    def test_an_inner_info_is_refused_and_the_inner_build_never_carries_the_columns(self):
        with self.assertRaises(ValueError):
            mm.with_installer(ps.sample_info("inner"), self.RECORD, self.ARTIFACTS)
        self.assertNotIn("installer", ps.sample_info("inner"))
        self.assertNotIn("artifacts", ps.sample_info("inner"))
        self.assertNotIn("installer", ps.sample_info("outer"))

    def test_an_old_info_without_the_columns_is_still_read_and_written_the_same_way(self):
        info = ps.sample_info("outer")
        text = mm.render_json(info)
        self.assertEqual(mm.render_json(json.loads(text)), text)
        self.assertNotIn("installer", text)
        self.assertEqual(mm.render_markdown(info), mm.render_markdown(json.loads(text)))
        self.assertNotIn("## 설치 파일(Inno Setup)", mm.render_markdown(info))

    def test_a_second_call_replaces_the_columns(self):
        once = mm.with_installer(ps.sample_info("outer"), self.RECORD, self.ARTIFACTS)
        again = mm.with_installer(once, dict(self.RECORD, tool_version="6.8.0"), self.ARTIFACTS)
        self.assertEqual(again["installer"]["tool_version"], "6.8.0")
        self.assertEqual(list(again).count("installer"), 1)

    def test_the_columns_are_the_last_keys_so_old_readers_see_the_same_front(self):
        info = ps.sample_info("outer")
        newer = mm.with_installer(info, self.RECORD, self.ARTIFACTS)
        self.assertEqual(list(newer)[:len(info)], list(info))
        self.assertEqual(list(newer)[-2:], ["installer", "artifacts"])

    def test_the_markdown_has_the_installer_facts_and_the_check_command_and_stays_clean(self):
        markdown = mm.render_markdown(mm.with_installer(ps.sample_info("outer"), self.RECORD, self.ARTIFACTS))
        for needle in ("## 설치 파일(Inno Setup)", pc.setup_name(ps.VERSION), "b" * 64, "Inno Setup 6.7.1", "a" * 64, "Get-FileHash", "서명이 없는"):
            self.assertIn(needle, markdown, needle)
        self.assertNotIn(TILDE, markdown)
        self.assertIsNone(URL.search(markdown))
        self.assertNotIn(OPEN2, markdown)

    def test_the_sums_file_lists_every_artifact_when_the_info_has_them_and_only_the_zip_when_it_has_not(self):
        with bs.temp_dir() as tmp:
            zip_path = Path(tmp) / pc.zip_name(ps.VERSION)
            zip_path.write_bytes(b"zip")
            plain = ps.sample_info("outer")
            mm.write_outer(tmp, plain, zip_path)
            self.assertEqual((Path(tmp) / "SHA256SUMS").read_text(encoding="utf-8"), f"{plain['package']['sha256']}  {pc.zip_name(ps.VERSION)}\n")
            newer = mm.with_installer(plain, self.RECORD, self.ARTIFACTS)
            mm.write_outer(tmp, newer, zip_path)
            self.assertEqual(bi.parse_sums((Path(tmp) / "SHA256SUMS").read_text(encoding="utf-8")),
                             {pc.setup_name(ps.VERSION): "b" * 64, pc.zip_name(ps.VERSION): plain["package"]["sha256"]})


class SourceRulesTest(unittest.TestCase):
    def setUp(self):
        self.path = ps.PACKAGING / "build_installer.py"
        self.source = self.path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_the_script_exists_parses_with_python_3_10_grammar_and_is_clean(self):
        ast.parse(self.source, feature_version=(3, 10))
        self.assertNotIn(TILDE, self.source)
        self.assertIsNone(URL.search(self.source))
        self.assertNotIn(OPEN2, self.source)
        self.assertNotIn(pc.BOM, self.source)

    def test_exactly_one_place_starts_a_process_and_it_is_the_compiler_run(self):
        spawners = []
        for function in [node for node in ast.walk(self.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and ast.unparse(node.func) in ("subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "os.system", "os.popen", "os.startfile"):
                    spawners.append((function.name, ast.unparse(node.func)))
        self.assertEqual(spawners, [("run_iscc", "subprocess.run")])

    def test_no_shell_no_network_no_dynamic_code_and_no_other_process_module(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for name in ("socket", "ssl", "urllib", "http", "ftplib", "smtplib", "requests", "asyncio", "multiprocessing", "webbrowser", "telnetlib", "xmlrpc", "shlex", "pty"):
            self.assertNotIn(name, imported, name)
        self.assertNotIn("shell=True", self.source)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ("eval", "exec", "compile", "__import__"), node.func.id)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                self.fail("shell 인자는 쓰지 않는다")

    def test_the_arguments_of_the_process_call_are_a_list_and_stdin_is_closed(self):
        calls = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "subprocess.run"]
        self.assertEqual(len(calls), 1)
        keywords = {item.arg for item in calls[0].keywords}
        self.assertIn("stdin", keywords)
        self.assertIn("timeout", keywords)
        self.assertIn("env", keywords)
        self.assertNotIn("shell", keywords)

    def test_the_silent_install_constants_come_from_the_shared_module_and_are_not_written_again(self):
        for word in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/NORESTART"):
            self.assertNotIn(word, self.source, "무음 설치·제거 인자는 pkgcommon 한 곳에만 쓴다(단일 출처)")
        self.assertIn("import pkgcommon as pc", self.source)

    def test_the_script_does_not_import_the_app_or_the_spike(self):
        for node in self.tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    self.assertFalse(name.startswith("chanceblog_desktop"), name)
                    self.assertNotIn("spike", name)
        self.assertNotIn("packaging/spike", self.source)
        self.assertNotIn("measure", " ".join(alias.name for node in self.tree.body if isinstance(node, ast.Import) for alias in node.names))

    def test_the_script_is_listed_among_the_packaging_scripts(self):
        self.assertIn("build_installer.py", [path.name for path in ps.PACKAGING.glob("*.py")])


class NoticesTest(unittest.TestCase):
    def notices(self):
        packages = [{"name": "PySide6_Essentials", "version": "6.0", "license": "LGPL", "role": "runtime"}, {"name": "shiboken6", "version": "6.0", "license": "LGPL", "role": "runtime"}]
        return bp.notices_text("1.0.0", packages, "0" * 40)

    def test_the_notices_say_the_setup_file_is_made_with_inno_setup_and_that_the_licence_text_is_not_here_yet(self):
        text = self.notices()
        row = next(line for line in text.splitlines() if line.startswith("| Inno Setup"))
        self.assertIn("설치 파일", row)
        self.assertIn("Inno Setup", row)
        self.assertIn("저작권자", row)
        self.assertIn("전문", row)
        self.assertIn("릴리스", row)
        self.assertEqual(row.count("|"), 5, "표의 칸은 넷이다")

    def test_the_notices_make_no_legal_claim_about_inno_setup_and_have_no_address(self):
        text = self.notices()
        part = "\n".join(line for line in text.splitlines() if "Inno" in line)
        for word in ("무료", "허용", "문제없", "문제 없", "보장", "위반", "요구한다", "의무"):
            self.assertNotIn(word, part, word)
        self.assertNotIn(TILDE, text)
        self.assertIsNone(URL.search(text))
        self.assertNotIn(OPEN2, text)

    def test_the_old_rows_are_still_there(self):
        text = self.notices()
        for needle in ("| Qt for Python", "| OpenSSL 3", "| PyInstaller 부트로더", "| Python 런타임", "## LGPL(Qt·PySide6) 안내", "## 알려진 한계"):
            self.assertIn(needle, text, needle)


@unittest.skipUnless(sys.platform == "win32" and ps.HAVE_GIT, "진짜 컴파일은 윈도와 git 이 있을 때만")
class RealCompileTest(unittest.TestCase):
    """윈도에서 ISCC 를 찾을 수 있을 때만 돈다(GitHub 러너 이미지에는 Inno Setup 6.7.1 이 미리 깔려 있다) — 작은 가짜 묶음을 **진짜 `.iss`** 로 컴파일해 설치 파일이 생기고 이름·크기·판 기록이 맞는지 본다.
    이 PC 에는 Inno 가 없고 설치·내려받기는 금지라 로컬에서는 건너뛴다 — 앱 검사(CI)의 윈도 칸이 생산 `.iss` 를 처음 진짜로 컴파일한다. 만든 설치 파일은 실행하지 않는다(설치 0)."""

    def test_the_real_script_compiles_a_small_fake_bundle_and_the_records_are_right(self):
        host = bi.Host()
        try:
            iscc = bi.find_iscc(host)
        except mm.BuildRefused:
            self.skipTest("이 PC 에는 Inno Setup 컴파일러(ISCC.exe)가 없다 — 러너에서 처음 확인")
        with bs.temp_dir() as tmp:
            out, _result = bs.make_out(Path(tmp) / "fake")
            result = bi.build(bi.Options(out_dir=out), host=host, say=lambda text: None)
            setup = out / "release" / pc.setup_name(ps.VERSION)
            self.assertEqual(result["setup"], setup)
            self.assertTrue(setup.is_file())
            self.assertGreater(setup.stat().st_size, 100_000)
            self.assertEqual(setup.read_bytes()[:2], b"MZ")
            info = json.loads((out / "release" / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
            self.assertEqual(info["installer"]["tool"], "inno-setup")
            numbers = bi.real_version(bi.version_numbers(info["installer"]["tool_version"]))
            self.assertIsNotNone(numbers)
            self.assertGreaterEqual(tuple(numbers[:3]), pc.INNO_MIN_VERSION)
            self.assertEqual(info["installer"]["iscc_sha256"], pc.sha256_file(iscc))
            self.assertEqual(info["artifacts"]["setup"], {"name": setup.name, "sha256": pc.sha256_file(setup), "bytes": setup.stat().st_size})
            self.assertEqual(bi.parse_sums((out / "release" / "SHA256SUMS").read_text(encoding="utf-8"))[setup.name], pc.sha256_file(setup))


if __name__ == "__main__":
    unittest.main()
