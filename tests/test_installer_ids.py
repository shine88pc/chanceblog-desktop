"""설치 파일(Inno Setup) 이름·ID·폴더 겹침 시험(V1INSTALL, 결정 D-830 이후) — `packaging/pkgcommon.py` 의 Inno 쪽 상수와 순수 함수를 못박는다.
PyInstaller·Inno Setup·네트워크 없이 돈다(표준 라이브러리와 앱의 이름 상수만 읽는다).

지키는 것:
  1) 설치 파일 이름 `ChanceBlogDesktop-<버전>-Setup.exe` 와 '시험 빌드(TESTBUILD)에는 설치 파일을 만들지 않는다' 는 규칙, 버전 모양이 틀리면 이름을 만들지 않는 것.
  2) Inno `AppId`(이 갈래가 한 번 만들어 영구 고정한 GUID)의 값·모양·'여는 중괄호를 두 번 쓰는' 규칙, 그리고 `.iss` 의 AppId 줄과 같음.
  3) 설치 폴더와 데이터 폴더가 겹치지 않음(기본 위치)과 겹침 검사 `install_dir_problem` 의 규칙(대소문자·끝의 점·공백·슬래시·`..`·유니코드 정규화를 무시하고 같거나 한쪽이 다른 쪽 안이면 문제 글).
  4) 이름 네 가지(제품 이름·실행 파일·데이터 폴더·자격 증명 접두어)가 바뀌지 않음, 게시자에 개인 이름이 없음.
  5) 무음 설치·제거 인자 상수의 값. 이 상수는 `packaging/` 쪽 단일 출처이고, 앱 쪽(`src/`)에 같은 값을 두고 **같음을 지키는 시험**을 더하는 일은 UPDATE U-4(설치 도구 어댑터)가 한다 —
     이 갈래는 `src/` 를 건드리지 않으므로 그 시험을 만들지 않았다(`docs/PACKAGE.md` 의 '설치 파일(Inno Setup)' 절에 적었다).
소스에도 이중 중괄호를 글자 그대로 적지 않는다(`"{" * 2` 로 만든다 — 문서·주석 규칙과 같은 방식).
"""
import re
import unicodedata
import unittest

import packaging_support as ps
from chanceblog_desktop.security import keystore
from chanceblog_desktop.service.context import APP_DIR_NAME

pc = ps.pkgcommon
OPEN2, CLOSE1 = "{" * 2, "}"
GUID_SHAPE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$")
FIXED_GUID = "CF5B18A9-6CBC-4916-9978-7729E88B70C8"            # 영구 고정 — 바꾸면 '같은 앱의 새 판' 이 아니라 별개 앱이 된다(설계서 이름 표). 바꾸려면 이 줄과 `.iss`·상수를 함께 바꾸고 결정을 적는다
LOCAL = "C:\\Users\\Example\\AppData\\Local"                   # 가짜 사용자 폴더(실제 계정 이름이 아니다)


def iss_text():
    return (ps.PACKAGING / "ChanceBlogDesktop.iss").read_text(encoding="utf-8")


class SetupNameTest(unittest.TestCase):
    def test_the_setup_name_follows_the_version(self):
        self.assertEqual(pc.setup_name("0.1.0-preview.1"), "ChanceBlogDesktop-0.1.0-preview.1-Setup.exe")
        self.assertEqual(pc.setup_name("1.2.3"), "ChanceBlogDesktop-1.2.3-Setup.exe")
        self.assertEqual(pc.setup_name("1.0.0-rc.1"), "ChanceBlogDesktop-1.0.0-rc.1-Setup.exe")
        self.assertEqual(pc.setup_name("1.2.3", False), pc.setup_name("1.2.3"))

    def test_the_setup_name_and_the_zip_name_share_the_same_front_part(self):
        for version in ("0.1.0-preview.1", "1.2.3", "10.20.30+3"):
            front = pc.setup_name(version)[:-len("-Setup.exe")]
            self.assertEqual(front, pc.top_folder(version))
            self.assertEqual(pc.zip_name(version)[:-len("-win64.zip")], front)
            self.assertTrue(pc.setup_name(version).endswith("-Setup.exe"))
            self.assertNotIn(pc.TRIAL_TAG, pc.setup_name(version))

    def test_a_trial_build_never_gets_a_setup_name(self):
        for version in ("0.1.0-preview.1", "1.2.3"):
            with self.assertRaises(ValueError):
                pc.setup_name(version, True)
            with self.assertRaises(ValueError):
                pc.setup_name(version, trial=True)

    def test_a_version_that_is_not_the_version_shape_gets_no_name(self):
        for bad in ("", " ", "1.2", "v1.2.3", "1.2.3 /Ssigntool", "1.2.3\"", "..\\1.2.3", "1.2.3/../x", "1.2.3\n4", "abc", None, 3, "1.2.3-" + "x" * 80):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    pc.setup_name(bad)

    def test_the_setup_suffix_constants_are_these(self):
        self.assertEqual(pc.SETUP_SUFFIX, "-Setup.exe")
        self.assertEqual(pc.INSTALLER_TOOL, "inno-setup")
        self.assertEqual(pc.INNO_UNINSTALLER_NAME, "unins000.exe")


class AppIdTest(unittest.TestCase):
    def test_the_guid_is_the_one_fixed_forever_and_has_the_random_guid_shape(self):
        self.assertEqual(pc.INNO_APP_GUID, FIXED_GUID)
        self.assertRegex(pc.INNO_APP_GUID, GUID_SHAPE)
        self.assertEqual(len(set(pc.INNO_APP_GUID.replace("-", ""))) > 6, True, "같은 글자만 되풀이하는 가짜 GUID 가 아니다")

    def test_the_app_id_text_opens_with_two_braces_and_closes_with_one(self):
        """Inno 는 `AppId` 안의 여는 중괄호를 두 번 써야 글자 하나로 읽는다 — 한 번만 쓰면 상수 식으로 읽혀 컴파일이 깨지거나 다른 ID 가 된다."""
        self.assertEqual(pc.INNO_APP_ID, OPEN2 + FIXED_GUID + CLOSE1)
        self.assertTrue(pc.INNO_APP_ID.startswith(OPEN2))
        self.assertFalse(pc.INNO_APP_ID.startswith("{" * 3))
        self.assertEqual(pc.INNO_APP_ID.count("{"), 2)
        self.assertEqual(pc.INNO_APP_ID.count("}"), 1)
        self.assertTrue(pc.INNO_APP_ID.endswith(CLOSE1) and not pc.INNO_APP_ID.endswith("}" * 2))

    def test_the_script_has_exactly_one_app_id_line_and_it_is_the_constant_with_the_escape(self):
        lines = [line.strip() for line in iss_text().splitlines() if line.strip().lower().startswith("appid=")]
        self.assertEqual(lines, ["AppId=" + pc.INNO_APP_ID])
        self.assertRegex(lines[0], r"^AppId=\{\{[0-9A-F-]{36}\}$")

    def test_the_script_never_writes_the_double_open_brace_anywhere_else(self):
        """문서·주석에 이중 중괄호를 쓰지 않는 규칙 — 스크립트에서는 AppId 줄 하나만 예외다."""
        text = iss_text()
        self.assertEqual(text.count(OPEN2), 1)
        self.assertEqual(text.count("}" * 2), 0)
        self.assertIn("AppId=" + OPEN2, text)

    def test_the_guid_is_not_used_by_the_installer_spike_and_is_not_a_placeholder(self):
        for spike_id in ("ChanceBlogSpikeInnoV1", "ChanceBlogSpikeInnoReal"):
            self.assertNotIn(spike_id, pc.INNO_APP_ID)
        self.assertNotRegex(pc.INNO_APP_GUID, r"^0{8}-|^F{8}-|^(.)\1{7}-")


class NamesUnchangedTest(unittest.TestCase):
    def test_product_executable_data_folder_and_credential_prefix_are_the_same_as_before(self):
        self.assertEqual((pc.PRODUCT, pc.EXE_NAME, APP_DIR_NAME, keystore.TARGET_PREFIX), ("ChanceBlog Desktop", "ChanceBlogDesktop", "ChanceblogDesktop", "ChanceBlogDesktop"))
        self.assertEqual(pc.DATA_DIR_NAME, APP_DIR_NAME)
        self.assertEqual(pc.INSTALL_DIR_NAME, pc.EXE_NAME)

    def test_the_publisher_is_the_product_name_family_and_never_a_person(self):
        self.assertEqual(pc.INNO_PUBLISHER, "ChanceBlog")
        for word in ("@", " ", "\\", "/"):
            self.assertNotIn(word, pc.INNO_PUBLISHER)

    def test_the_minimum_inno_version_is_the_first_one_with_the_korean_message_file(self):
        self.assertEqual(pc.INNO_MIN_VERSION, (6, 5, 0))


class SilentArgsTest(unittest.TestCase):
    def test_the_silent_install_and_uninstall_arguments_are_the_measured_ones(self):
        self.assertEqual(pc.INNO_SILENT_INSTALL_ARGS, ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"))
        self.assertEqual(pc.INNO_SILENT_UNINSTALL_ARGS, ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"))
        self.assertEqual(pc.INNO_UPDATE_EXTRA_ARGS, ("/CLOSEAPPLICATIONS",))
        self.assertEqual(pc.INNO_SILENT_UPDATE_ARGS, pc.INNO_SILENT_INSTALL_ARGS + pc.INNO_UPDATE_EXTRA_ARGS)

    def test_every_silent_argument_is_a_plain_ascii_switch_without_a_value_or_a_path(self):
        for name in ("INNO_SILENT_INSTALL_ARGS", "INNO_SILENT_UNINSTALL_ARGS", "INNO_UPDATE_EXTRA_ARGS", "INNO_SILENT_UPDATE_ARGS"):
            args = getattr(pc, name)
            self.assertIsInstance(args, tuple, name)
            for arg in args:
                self.assertRegex(arg, r"^/[A-Z-]+$", f"{name}: {arg}")                  # `=` 값·경로·로그 위치는 부르는 쪽이 따로 붙인다(`/DIR=`·`/LOG=`)
            self.assertEqual(len(set(args)), len(args), name)

    def test_the_uninstall_arguments_never_ask_to_remove_the_data_and_the_install_ones_never_restart(self):
        for arg in pc.INNO_SILENT_UNINSTALL_ARGS + pc.INNO_SILENT_INSTALL_ARGS:
            self.assertNotIn("DELETE", arg.upper())
        self.assertIn("/NORESTART", pc.INNO_SILENT_INSTALL_ARGS)
        self.assertIn("/NORESTART", pc.INNO_SILENT_UNINSTALL_ARGS)
        self.assertIn("/SUPPRESSMSGBOXES", pc.INNO_SILENT_INSTALL_ARGS)
        self.assertIn("/SUPPRESSMSGBOXES", pc.INNO_SILENT_UNINSTALL_ARGS)


class DefaultFoldersTest(unittest.TestCase):
    def test_the_default_install_folder_is_under_programs_and_the_data_folder_is_one_level_up(self):
        self.assertEqual(pc.default_install_dir(LOCAL), LOCAL + "\\Programs\\ChanceBlogDesktop")
        self.assertEqual(pc.default_data_dir(LOCAL), LOCAL + "\\ChanceblogDesktop")
        self.assertEqual(pc.default_install_dir(LOCAL + "\\"), LOCAL + "\\Programs\\ChanceBlogDesktop")

    def test_the_default_folders_do_not_overlap(self):
        for base in (LOCAL, "D:\\Local", "C:\\Users\\한글 이름\\AppData\\Local", "C:\\a\\b\\c\\d\\e"):
            with self.subTest(base=base):
                self.assertEqual(pc.install_dir_problem(pc.default_install_dir(base), pc.default_data_dir(base)), "")
                self.assertEqual(pc.install_dir_problem(pc.default_data_dir(base), pc.default_install_dir(base)), "")

    def test_the_script_default_folder_is_the_programs_folder_name_of_the_constant(self):
        lines = [line.strip() for line in iss_text().splitlines() if line.strip().startswith("DefaultDirName=")]
        self.assertEqual(lines, ["DefaultDirName={autopf}\\" + pc.INSTALL_DIR_NAME])
        self.assertEqual(lines[0].split("\\")[-1], pc.INSTALL_DIR_NAME)


class InstallDirProblemTest(unittest.TestCase):
    DATA = LOCAL + "\\ChanceblogDesktop"

    def problem(self, install, data=None):
        return pc.install_dir_problem(install, self.DATA if data is None else data)

    def test_the_same_folder_in_every_disguise_is_a_problem(self):
        disguises = {
            "같은 글": self.DATA, "소문자": self.DATA.lower(), "대문자": self.DATA.upper(), "끝 구분자": self.DATA + "\\", "슬래시": self.DATA.replace("\\", "/"), "끝의 점": self.DATA + ".",
            "끝의 점 여럿": self.DATA + "...", "끝의 공백": self.DATA + " ", "점과 공백": self.DATA + " . ", "한 점 이름": self.DATA + "\\.", "위로 갔다 오기": LOCAL + "\\Programs\\..\\ChanceblogDesktop",
            "겹친 구분자": LOCAL + "\\\\ChanceblogDesktop", "확장 경로 접두어": "\\\\?\\" + self.DATA, "드라이브 글자 소문자": "c" + self.DATA[1:], "중간 이름 끝의 점": "C:\\Users.\\Example\\AppData\\Local\\ChanceblogDesktop",
            "전각 글자": "ＣｈａｎｃｅｂｌｏｇＤｅｓｋｔｏｐ".join([LOCAL + "\\", ""]),
        }
        for label, install in disguises.items():
            with self.subTest(label=label):
                self.assertNotEqual(self.problem(install), "", install)
                self.assertNotEqual(self.problem(self.DATA, install), "", install)

    def test_one_folder_inside_the_other_is_a_problem_in_both_directions(self):
        inside = [self.DATA + "\\app", self.DATA + "\\a\\b\\c", self.DATA.upper() + "\\APP", self.DATA + ".\\app", self.DATA + "\\..\\ChanceblogDesktop\\app"]
        for child in inside:
            with self.subTest(child=child):
                self.assertNotEqual(self.problem(child), "")                           # 설치 폴더가 데이터 폴더 안
                self.assertNotEqual(self.problem(self.DATA, child), "")                # 데이터 폴더가 설치 폴더 안
        self.assertNotEqual(self.problem(LOCAL), "")                                   # 설치 폴더가 데이터 폴더의 부모(데이터가 설치 폴더 안)
        self.assertNotEqual(self.problem("C:\\"), "")                                  # 드라이브 맨 위도 데이터를 품는다

    def test_the_two_directions_say_different_things(self):
        inside_data = self.problem(self.DATA + "\\app")
        inside_install = self.problem(LOCAL)
        same = self.problem(self.DATA)
        self.assertEqual(len({inside_data, inside_install, same}), 3)
        self.assertIn("같은 폴더", same)
        self.assertIn("데이터 폴더 안", inside_data)
        self.assertIn("설치 폴더 안", inside_install)

    def test_neighbours_that_only_share_a_name_prefix_do_not_collide(self):
        for install in (self.DATA + "2", self.DATA + "App", LOCAL + "\\ChanceblogDesktopX\\app", LOCAL + "\\Programs\\ChanceBlogDesktop", LOCAL + "\\Chanceblog", "D:\\ChanceblogDesktop", "C:\\Program Files\\ChanceBlogDesktop",
                        LOCAL + "\\Programs\\ChanceBlogDesktop\\ChanceblogDesktop2"):
            with self.subTest(install=install):
                self.assertEqual(self.problem(install), "", install)
                self.assertEqual(self.problem(self.DATA, install), "", install)

    def test_korean_names_collide_whatever_their_unicode_normal_form_is(self):
        data = "C:\\Users\\Example\\AppData\\Local\\한글 앱 데이터"
        for form in ("NFC", "NFD", "NFKC", "NFKD"):
            with self.subTest(form=form):
                self.assertNotEqual(pc.install_dir_problem(unicodedata.normalize(form, data), unicodedata.normalize("NFC", data)), "")
                self.assertNotEqual(pc.install_dir_problem(unicodedata.normalize("NFD", data) + "\\app", unicodedata.normalize(form, data)), "")
        self.assertEqual(pc.install_dir_problem("C:\\Users\\Example\\AppData\\Local\\Programs\\한글 앱", data), "")

    def test_letter_case_is_ignored_for_other_alphabets_too(self):
        self.assertNotEqual(pc.install_dir_problem("C:\\Données\\Ünï", "c:\\DONNÉES\\ÜNÏ"), "")
        self.assertNotEqual(pc.install_dir_problem("C:\\Straße", "C:\\STRASSE"), "")                 # 윈도는 달리 볼 수 있으나 겹침은 넓게(안전한 쪽으로) 본다

    def test_different_drives_do_not_collide(self):
        self.assertEqual(pc.install_dir_problem("D:\\ChanceblogDesktop", "C:\\ChanceblogDesktop"), "")
        self.assertEqual(pc.install_dir_problem("E:\\x", "C:\\x\\y"), "")

    def test_inputs_that_cannot_be_compared_are_problems_and_the_text_never_repeats_them(self):
        secret_like = "C:\\Users\\Example\\CANARY_" + "folder_name_that_must_not_be_echoed"
        for bad in ("", "   ", None, 3, [], "relative\\folder", "folder", "\\just\\root", "C:", "C:\\\0x", "\\\\server", "..\\x"):
            with self.subTest(bad=bad):
                text = self.problem(bad)
                self.assertNotEqual(text, "")
                self.assertNotEqual(pc.install_dir_problem(self.DATA, bad), "")
        self.assertNotIn("CANARY_", self.problem(secret_like + "\\" + "\0"))
        self.assertNotIn(secret_like, pc.install_dir_problem(secret_like, secret_like))
        self.assertNotIn("Example", pc.install_dir_problem(self.DATA, self.DATA))

    def test_the_answer_is_an_empty_text_or_a_plain_korean_sentence(self):
        good = self.problem(LOCAL + "\\Programs\\ChanceBlogDesktop")
        self.assertIs(type(good), str)
        self.assertEqual(good, "")
        bad = self.problem(self.DATA)
        self.assertIs(type(bad), str)
        self.assertRegex(bad, r"[가-힣]")
        for word in ("\\", "/", "C:"):
            self.assertNotIn(word, bad)

    def test_a_data_folder_named_like_the_install_folder_is_caught_when_the_parents_match(self):
        """설치 폴더 이름과 데이터 폴더 이름은 대소문자만 다르다(`ChanceBlogDesktop` 대 `ChanceblogDesktop`) — 부모 폴더가 같으면 같은 폴더가 된다. 기본값은 부모가 달라 안전하다."""
        self.assertEqual(pc.INSTALL_DIR_NAME.lower(), pc.DATA_DIR_NAME.lower())
        self.assertNotEqual(pc.install_dir_problem(LOCAL + "\\" + pc.INSTALL_DIR_NAME, LOCAL + "\\" + pc.DATA_DIR_NAME), "")
        self.assertEqual(pc.install_dir_problem(pc.default_install_dir(LOCAL), pc.default_data_dir(LOCAL)), "")


if __name__ == "__main__":
    unittest.main()
