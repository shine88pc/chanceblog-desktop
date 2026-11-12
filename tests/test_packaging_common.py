"""Package 도구의 공통 상수·작은 부품(`packaging/pkgcommon.py`) 시험 — 이름·문구·버전 규칙이 앱(`ui/core/version.py`)과 어긋나지 않게 못박고,
`packaging/` 안 글(스크립트·문서)이 운영자 표기 규칙(물결표·주소 링크 없음)과 3.10 문법을 지키는지 본다. PyInstaller·PySide6·네트워크 없이 돈다.
"""
import ast
import hashlib
import re
import unittest
from pathlib import Path

import packaging_support as ps
from chanceblog_desktop.service.context import APP_DIR_NAME
from chanceblog_desktop.ui.core import version as app_version

pc = ps.pkgcommon
BOM = chr(0xFEFF)
TILDE = chr(0x7E)
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")


class NamesTest(unittest.TestCase):
    def test_the_names_and_the_notice_are_exactly_these(self):
        self.assertEqual((pc.PRODUCT, pc.EXE_NAME, pc.CHANNEL), ("ChanceBlog Desktop", "ChanceBlogDesktop", "personal-pc-preview"))
        self.assertEqual(pc.NOTICE, "개인 PC 제한 시험용, 미서명 Package")
        self.assertEqual(pc.NOTICE_LONG, "개인 PC 제한 시험용, 미서명 Package — 공개 배포용이 아닙니다")
        self.assertEqual((pc.INFO_JSON, pc.INFO_MD, pc.SUMS_NAME, pc.LICENSES_DIR), ("PACKAGE_INFO.json", "PACKAGE_INFO.md", "SHA256SUMS", "LICENSES"))
        self.assertEqual(pc.LICENSE_FILES, ("LGPL-3.0.txt", "GPL-3.0.txt", "PYTHON-LICENSE.txt", "PYINSTALLER-COPYING.txt", "THIRD_PARTY_NOTICES.md"))
        self.assertEqual(pc.FILES_EXCLUDED_FROM_LIST, ("PACKAGE_INFO.json", "PACKAGE_INFO.md"))

    def test_the_zip_and_the_top_folder_names_follow_the_version(self):
        self.assertEqual(pc.zip_name("0.1.0-preview.1"), "ChanceBlogDesktop-0.1.0-preview.1-win64.zip")
        self.assertEqual(pc.top_folder("0.1.0-preview.1"), "ChanceBlogDesktop-0.1.0-preview.1")
        self.assertEqual(pc.zip_name("1.2.3"), "ChanceBlogDesktop-1.2.3-win64.zip")

    def test_a_trial_build_carries_testbuild_in_the_zip_and_the_top_folder_name_and_a_normal_one_never_does(self):
        self.assertEqual(pc.TRIAL_TAG, "TESTBUILD")
        self.assertEqual(pc.zip_name("0.1.0-preview.1", True), "ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD-win64.zip")
        self.assertEqual(pc.top_folder("0.1.0-preview.1", True), "ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD")
        self.assertEqual(pc.zip_name("0.1.0-preview.1", False), pc.zip_name("0.1.0-preview.1"))
        for version in ("0.1.0-preview.1", "1.2.3", "0.9.0-beta"):
            self.assertNotIn(pc.TRIAL_TAG, pc.zip_name(version))
            self.assertNotIn(pc.TRIAL_TAG, pc.top_folder(version))
            self.assertTrue(pc.zip_name(version, True).endswith("-TESTBUILD-win64.zip"))
            self.assertEqual(pc.zip_name(version, True)[:-len("-win64.zip")], pc.top_folder(version, True))

    def test_the_trial_and_the_gate_texts_are_these(self):
        self.assertEqual(pc.TRIAL_NOTICE, "시험 빌드 — 개인 PC 로 보내지 않는 빌드예요")
        self.assertEqual(pc.GATE_MISSING_TEXT, "외부 쓰기 관문(capabilities) 모듈이 없어요")

    def test_no_app_or_zip_folder_name_collides_with_the_data_folder_even_on_a_case_insensitive_disk(self):
        """압축을 풀면 생기는 폴더(버전이 붙은 이름)와 실행 파일 이름(`.exe` 가 붙는다)은 데이터 폴더 `ChanceblogDesktop` 과 대소문자를 무시해도 다르다.
        실행 파일 이름 자체(`ChanceBlogDesktop`)는 글자만 보면 같아서 **폴더 이름으로 쓰지 않는다** — 그래서 압축 안 맨 위 폴더에 버전이 붙는다."""
        for name in (pc.top_folder(ps.VERSION), pc.top_folder("0.1.0"), pc.top_folder(ps.VERSION, True), f"{pc.EXE_NAME}.exe"):
            self.assertNotEqual(name.lower(), APP_DIR_NAME.lower(), name)
        self.assertEqual(pc.EXE_NAME.lower(), APP_DIR_NAME.lower())                  # 같다는 사실을 못박는다 — 그러니 실행 파일 이름으로만 쓰고 폴더 이름으로 쓰지 않는다
        self.assertEqual(APP_DIR_NAME, "ChanceblogDesktop")                       # 데이터 폴더 이름은 운영자 결정으로 유지(바뀌면 이 시험이 알린다)

    def test_the_repo_version_is_a_preview_of_the_first_installable_release(self):
        number = pc.parse_version_text((ps.ROOT / "VERSION").read_text(encoding="utf-8"))
        self.assertRegex(number or "", r"^0\.1\.0-preview\.\d+$")


class AppDriftTest(unittest.TestCase):
    """빌드 도구와 앱이 같은 규칙·같은 문구를 따로 적었다 — 한쪽만 바뀌면 여기서 빨개진다."""

    def test_version_pattern_notice_channel_and_file_name_are_the_apps(self):
        self.assertEqual(pc.VERSION_PATTERN, app_version._NUMBER.pattern)
        self.assertEqual(pc.NOTICE, app_version.PACKAGE_NOTICE)
        self.assertEqual(pc.TRIAL_NOTICE, app_version.PACKAGE_TRIAL_NOTICE)
        self.assertEqual(pc.CHANNEL, app_version.PACKAGE_CHANNEL)
        self.assertEqual(pc.INFO_JSON, app_version.PACKAGE_INFO_NAME)

    def test_the_version_parsers_agree_on_many_inputs(self):
        samples = ("0.0.0", "0.1.0-preview.1", " 1.2.3\n", BOM + "0.0.0\r\n", BOM + " 1.2.3 ", "10.20.30", "0.9.0-beta", "1.0.0+3", "", "   ", "abc", "0.0", "v0.0.0",
                   "0.0.0\n1.2.3", "0.0.0 beta", "0.0.0" + chr(0), "1.0.0" + BOM, "-1.0.0", "1.0.0-", "1.0.0-" + "x" * 80, "<b>1.0.0</b>", None, 3)
        for raw in samples:
            with self.subTest(raw=raw):
                self.assertEqual(pc.parse_version_text(raw), app_version.parse_version(raw))

    def test_the_key_shapes_are_the_repo_layout_tests_list(self):
        tree = ast.parse((ps.ROOT / "tests" / "test_repo_layout.py").read_text(encoding="utf-8"))
        listed = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "KEY_SHAPES" for t in node.targets))
        self.assertEqual(tuple(listed), pc.KEY_SHAPES)

    def test_every_key_shape_matches_a_sample_assembled_at_runtime(self):
        samples = ("AI" + "za" + "A" * 35, "gh" + "p_" + "A" * 36, "1234567890:" + "AA" + "b" * 33, "GOC" + "SPX-" + "a" * 24, "-----BEGIN " + "RSA PRIVATE KEY-----", "sk" + "-" + "a" * 40)
        for pattern in pc.KEY_SHAPES:
            self.assertTrue(any(re.search(pattern, sample) for sample in samples), pattern)
        joined = re.compile("|".join(pc.KEY_SHAPES))
        for sample in samples:
            self.assertIsNotNone(joined.search(sample))
        self.assertIsNone(joined.search("평범한 한글 문장과 token secret 낱말 그리고 " + "a" * 30))


class HashAndVersionTextTest(unittest.TestCase):
    def test_sha256_known_values(self):
        self.assertEqual(pc.sha256_bytes(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(pc.sha256_bytes(b""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_the_file_hash_is_the_same_whatever_the_chunk_size(self):
        data = bytes(range(256)) * 41
        with ps.temp_dir() as tmp:
            path = ps.write(Path(tmp) / "a.bin", data, binary=True)
            for chunk in (1, 7, 256, 1 << 20):
                self.assertEqual(pc.sha256_file(path, chunk), hashlib.sha256(data).hexdigest(), chunk)
            empty = ps.write(Path(tmp) / "empty", b"", binary=True)
            self.assertEqual(pc.sha256_file(empty), pc.sha256_bytes(b""))

    def test_the_bom_constant_is_the_invisible_character_and_the_source_has_no_literal_one(self):
        self.assertEqual(pc.BOM, BOM)
        for path in sorted(ps.PACKAGING.glob("*.py")):
            self.assertNotIn(BOM, path.read_text(encoding="utf-8"), path.name)


class ForbiddenNameTest(unittest.TestCase):
    def test_user_data_and_secret_file_names_are_refused(self):
        for relative in ("settings.json", "a/b/Settings.JSON", "connections.json", "quota_state.json", "chanceblog.db", "topic_engine.db", "x/cacert.pem", "k.key", "a.pfx", "b.p12",
                         "c.jks", "d.keystore", "e.sqlite", "e.sqlite3", "f.db-wal", "g.db-shm", ".env", ".env.local", "client_secret_123.json", "credentials.json", "token.json",
                         "secret.json", "id_rsa", "id_ed25519", ".netrc", ".git-credentials", "channel_profiles.json", "seeds.json"):
            with self.subTest(relative=relative):
                self.assertNotEqual(pc.forbidden_name(relative), "", relative)

    def test_every_user_data_file_name_the_app_itself_defines_is_refused_inside_the_bundle(self):
        """앱 코드가 정의한 데이터 파일 이름(주제 엔진 폴더 규칙·작업 공간·전체 백업의 표지)을 앱에서 읽어 와 하나도 빠지지 않았는지 본다 — 새 데이터 파일이 생겨도 이 시험이 알린다."""
        from chanceblog_desktop.service import backup_flow, context
        from chanceblog_desktop.topics import layout
        space = context.Workspace("data")
        names = {layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE, layout.CALENDAR_FILE, layout.ENGINE_DB_FILE, context.STORE_NAME, backup_flow.RESTORE_MARKER,
                 space.store_path.name, space.settings_path.name, space.connections_path.name, space.quota_path.name}
        self.assertGreaterEqual(len(names), 9)
        for name in sorted(names):
            for relative in (name, f"_internal/x/{name}", f"backups/full-20261111-120500/{name}"):
                with self.subTest(relative=relative):
                    self.assertNotEqual(pc.forbidden_name(relative), "", relative)

    def test_copies_and_temp_files_of_the_data_files_are_refused_too(self):
        for relative in ("settings.json.bak", "a/Connections.JSON.BAK", "chanceblog.db.v1.bak", "chanceblog.db.v1.2.bak", "x/seeds.json.tmp", "Calendar.json.tmp", "topic_engine.db.v10.bak",
                         "restore-in-progress.json.tmp"):
            with self.subTest(relative=relative):
                self.assertNotEqual(pc.forbidden_name(relative), "", relative)
        for relative in ("notes.bak", "x/readme.tmp", "calendar.py", "calendar.json5", "a/settings.jsonc", "vendor/VENDOR.json", "x/calendar.bak.py", "app.v1.bak"):
            with self.subTest(ordinary=relative):
                self.assertEqual(pc.forbidden_name(relative), "", relative)

    def test_code_files_with_similar_names_and_ordinary_files_pass(self):
        for relative in ("vendor/pipeline/secret_patterns.py", "a/tokenizer.py", "x/credentials_helper.py", "doc/secret_notes.md", "PySide6/Qt6Core.dll", "ChanceBlogDesktop.exe",
                         "VERSION", "vendor/VENDOR.json", "_internal/base_library.zip", "LICENSES/GPL-3.0.txt", "PACKAGE_INFO.json", "_internal/PySide6/QtCore.pyd", "x/tokens.pyi"):
            with self.subTest(relative=relative):
                self.assertEqual(pc.forbidden_name(relative), "", relative)


class StdlibImportsTest(unittest.TestCase):
    def test_only_standard_modules_with_their_dotted_names_are_collected(self):
        source = "import os, json\nimport urllib.request\nfrom urllib import error\nfrom html.parser import HTMLParser\nimport PySide6\nfrom . import sibling\nfrom .x import y\ndef f():\n    import threading\n    from pathlib import Path\n"
        self.assertEqual(pc.stdlib_imports(source), ["html.parser", "json", "os", "pathlib", "threading", "urllib", "urllib.request"])

    def test_a_syntax_error_is_not_swallowed(self):
        with self.assertRaises(SyntaxError):
            pc.stdlib_imports("def broken(:\n")

    def test_the_real_vendor_files_use_only_standard_modules_the_build_knows(self):
        names = set()
        for path in sorted((ps.ROOT / "vendor").rglob("*.py")):
            names.update(pc.stdlib_imports(path.read_text(encoding="utf-8")))
        self.assertTrue({"re", "json"} <= names, names)


class SourceHygieneTest(unittest.TestCase):
    """packaging/ 의 스크립트는 3.10 문법만, 물결표·주소 링크 없이, 앱 코드를 고치지 않고, 파이썬 패키지 이름 `packaging` 과 부딪치지 않는다."""

    def scripts(self):
        return sorted(ps.PACKAGING.glob("*.py"))

    def test_the_four_scripts_exist_and_the_folder_is_not_a_package(self):
        self.assertEqual([path.name for path in self.scripts()], ["build_package.py", "gui_entry.py", "make_manifest.py", "pkgcommon.py"])
        self.assertFalse((ps.PACKAGING / "__init__.py").exists(), "packaging/ 가 패키지가 되면 PyPI 의 packaging 라이브러리와 부딪친다")

    def test_every_script_parses_with_python_3_10_grammar(self):
        for path in self.scripts():
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))

    def test_no_tilde_and_no_address_link_in_the_scripts(self):
        for path in self.scripts():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(TILDE, text, path.name)
            self.assertIsNone(URL.search(text), path.name)

    def test_the_scripts_do_not_import_the_app_except_the_entry_and_only_inside_functions(self):
        for path in self.scripts():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
            for node in top_level:
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    self.assertFalse(name.startswith("chanceblog_desktop"), f"{path.name} 맨 위에서 앱을 불러온다: {name}")

    def test_the_license_texts_are_byte_for_byte_what_the_sources_file_says(self):
        sources = (ps.PACKAGING / "LICENSES" / "SOURCES.txt").read_text(encoding="utf-8")
        for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
            data = (ps.PACKAGING / "LICENSES" / name).read_bytes()
            self.assertIn(hashlib.sha256(data).hexdigest(), sources, name)
            self.assertIn(f"{len(data)} 바이트", sources, name)
            self.assertNotIn(b"\r", data, name)
        self.assertIn(b"GNU LESSER GENERAL PUBLIC LICENSE", (ps.PACKAGING / "LICENSES" / "LGPL-3.0.txt").read_bytes())
        self.assertIn(b"GNU GENERAL PUBLIC LICENSE", (ps.PACKAGING / "LICENSES" / "GPL-3.0.txt").read_bytes())
        self.assertNotIn(TILDE, sources)
        self.assertIsNone(URL.search(sources))

    def test_the_gitattributes_keep_the_license_texts_byte_exact(self):
        lines = {line.strip() for line in (ps.ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()}
        self.assertIn("packaging/LICENSES/** -text", lines)
        self.assertIn("vendor/** -text", lines)                                   # 기존 규칙은 그대로


if __name__ == "__main__":
    unittest.main()
