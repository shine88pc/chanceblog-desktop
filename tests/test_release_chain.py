"""`packaging/release_chain.py`(릴리스 버전 사슬, RELEASE 설계서 3-6·3-3 단계 10, V1REL12·R-2) 시험 — 가짜 `release/` 폴더로 사슬을 만들고 확인한다.

사슬: `VERSION` → 태그 `v<버전>` → 매니페스트 `version`·`tag` → `PACKAGE_INFO.version` → 설치 파일·압축 파일 이름 → 릴리스 제목 → 본문 → 변경 이력 절 → 앱 정보 카드.

지키는 것:
  1) 버전 글: 정식(`X.Y.Z`)·후보(`X.Y.Z-rc.N`)만 — 앱의 매니페스트 규칙과 같은 판정이다(앱이 받아들이는 글만 통과). 이름 함수는 앱이 요구하는 이름과 같다.
  2) 일관된 폴더는 문제가 없고, 이름 오타·자산 하나 더·빠진 파일·링크·버전이 한 곳만 다름(`VERSION`·태그·후보 기록·묶음 정보·설치 파일·압축 파일·매니페스트·변경 이력)·해시 목록(`SHA256SUMS`)의 줄 어긋남·
     다시 해시한 값이 후보 기록과 다름·묶음 정보의 커밋·압축 파일 해시·`artifacts` 어긋남·정식에 사전판 글자·후보 기록의 모양을 각각 거절한다.
  3) 서명한 뒤(`final`)의 폴더: 매니페스트가 앱의 규칙을 지키고 후보 기록과 같다(버전·태그·채널·커밋·설치 도구·파일 표).
  4) 모으기(`assemble`): 원본 폴더들에서 정해진 파일만 모아 해시 목록·후보 기록을 쓰고 사슬을 확인한다 — 낡은 산출물·충돌·빈 폴더가 아닌 출력·틀린 커밋을 거절하고 실패하면 후보 기록을 지운다.
  5) 명령줄과 소스 모양(표준 라이브러리만·앱은 함수 안에서만·하위 프로세스는 `git rev-parse` 한 곳).
네트워크 없이 돈다(가짜 폴더·가짜 글만).
"""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import release_tools_support as rts
import update_support as us

from chanceblog_desktop.ui.core import version as app_version
from chanceblog_desktop.update import manifest

import pkgcommon as pc
import release_chain as rc

ROOT = rts.ROOT
SCRIPT = ROOT / "packaging" / "release_chain.py"
STABLE, RC = "1.0.0", "1.0.0-rc.1"
FAKE_COMMIT, OTHER_COMMIT = rts.FAKE_COMMIT, rts.OTHER_COMMIT
run_tool = rts.Capture(rc.main)


def codes(problems):
    return sorted({item.code for item in problems})


def pairs(problems):
    return sorted((item.code, item.detail) for item in problems)


def new_release(case, version=STABLE, **kwargs):
    holder = rts.temp_dir()
    case.addCleanup(holder.cleanup)
    return rts.fake_release(Path(holder.name) / "release", version, **kwargs)


def check(folder, version=STABLE, **kwargs):
    kwargs.setdefault("commit", FAKE_COMMIT)
    kwargs.setdefault("changelog_text", rts.changelog_text(version))
    return rc.check_chain(folder, version, **kwargs)


def edit_json(path, change):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    change(data)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def refresh(folder, version=STABLE, *, sums=True, candidate=True):
    """바꾼 파일에 맞춰 해시 목록과 후보 기록을 다시 쓴다(시험이 한 가지만 틀리게 하려고)."""
    folder = Path(folder)
    if sums:
        names = [item.name for item in folder.iterdir() if item.is_file() and item.name not in ("SHA256SUMS", "release_candidate.json")]
        rts.write(folder / "SHA256SUMS", rts.sums_text([(name, hashlib.sha256((folder / name).read_bytes()).hexdigest()) for name in names]))
    if candidate:
        rts.write_candidate(folder, version)


def make_final(folder, version=STABLE, *, change=None, signature=None):
    """서명한 뒤의 폴더 — 매니페스트(앱 규칙을 지키는 값)와 모양만 맞는 서명 파일을 더하고 해시 목록을 다시 쓴다."""
    folder = Path(folder)
    data = json.loads((folder / "release_candidate.json").read_text(encoding="utf-8"))
    kind = "rc" if "-rc." in version else "stable"
    files = [{"role": item["role"], "name": item["name"], "size": item["size"], "sha256": item["sha256"]} for item in data["assets"] if item["role"] in ("setup", "portable")]
    obj = us.manifest_dict(version=version, tag="v" + version, channel=kind, min_version="0.0.0", commit=FAKE_COMMIT, installer={"kind": "inno", "pack_id": "ChanceBlogDesktop"}, files=files)
    if change:
        change(obj)
    rts.write(folder / "update-manifest.json", us.encode_manifest(obj))
    rts.write(folder / "update-manifest.json.sig", signature if signature is not None else b"A" * 86 + b"==\n")
    refresh(folder, version, candidate=False)
    return obj


class VersionRulesTest(unittest.TestCase):
    ACCEPTED = {"0.0.0": "stable", "1.0.0": "stable", "10.20.30": "stable", "1.0.0-rc.1": "rc", "0.9.0-rc.12": "rc", "2.0.0-rc.100": "rc"}
    REFUSED = ("1.0", "1.0.0-rc.0", "1.0.0-rc.01", "1.0.0-rc", "1.0.0-rc.", "1.0.0-preview.1", "1.0.0-beta.1", "1.0.0-alpha", "1.0.0+3", "01.0.0", "1.00.0", "1.0.0-rc.1-x", "v1.0.0",
               "1.0.0 ", " 1.0.0", "1.0.0\n", "", "1.0.0-RC.1", "1.0.0-rc.1.2", "1.0.0-0.3.7", "１.0.0", "1.0.0-TESTBUILD", "0.1.0-preview.1")

    def test_only_a_plain_release_or_a_numbered_candidate_is_a_version(self):
        for text, kind in self.ACCEPTED.items():
            self.assertEqual(rc.version_kind(text), kind, text)
        for text in self.REFUSED:
            with self.subTest(text=text):
                self.assertIsNone(rc.version_kind(text))
        for value in (None, 1, 1.0, b"1.0.0", ["1.0.0"]):
            self.assertIsNone(rc.version_kind(value))

    def test_every_accepted_version_is_accepted_by_the_apps_manifest_rules_for_its_channel(self):
        for text, kind in self.ACCEPTED.items():
            with self.subTest(text=text):
                data = us.manifest_dict(version=text, tag="v" + text, channel=kind, min_version="0.0.0")
                data["files"] = [{"role": "setup", "name": rc.setup_name(text), "size": 10, "sha256": us.HASH_A}, {"role": "portable", "name": rc.portable_name(text), "size": 10, "sha256": us.HASH_B}]
                found = manifest.validate_fields(data, "0" * 64, channels=manifest.CHANNELS_OFFLINE)
                self.assertEqual((found.version, found.channel), (text, kind))

    def test_every_refused_version_is_refused_by_the_app_for_both_channels(self):
        for text in self.REFUSED:
            for channel in ("stable", "rc"):
                with self.subTest(text=text, channel=channel):
                    data = us.manifest_dict(version="1.0.1", tag="v1.0.1", channel=channel, min_version="0.0.0")
                    data["version"], data["tag"] = text, "v" + text
                    with self.assertRaises(manifest.ManifestError):
                        manifest.validate_fields(data, "0" * 64, channels=manifest.CHANNELS_OFFLINE)

    def test_the_version_file_reader_accepts_the_two_shapes_and_keeps_the_package_tool_rules(self):
        for raw, want in (("1.0.0\n", "1.0.0"), (chr(0xFEFF) + "1.0.0-rc.2\r\n", "1.0.0-rc.2"), ("  1.0.0  ", "1.0.0"), ("0.1.0-preview.1\n", None), ("1.0\n", None), ("", None), (None, None), ("1.0.0\n2.0.0\n", None)):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(rc.read_version_file(raw), want)

    def test_the_real_version_file_is_read_by_the_package_tools_rule(self):
        raw = (ROOT / "VERSION").read_text(encoding="utf-8")
        self.assertEqual(pc.parse_version_text(raw), raw.strip())


class NamesTest(unittest.TestCase):
    def test_the_names_are_functions_of_the_version(self):
        self.assertEqual(rc.tag_of("1.0.0"), "v1.0.0")
        self.assertEqual(rc.tag_of("1.0.0-rc.1"), "v1.0.0-rc.1")
        self.assertEqual(rc.title_of("1.0.0"), "ChanceBlog Desktop 1.0.0")
        self.assertEqual(rc.setup_name("1.0.0"), "ChanceBlogDesktop-1.0.0-Setup.exe")
        self.assertEqual(rc.portable_name("1.0.0-rc.1"), "ChanceBlogDesktop-1.0.0-rc.1-win64.zip")
        self.assertEqual(rc.card_text("1.0.0"), "v1.0.0")
        self.assertEqual((rc.channel_of("1.0.0"), rc.channel_of("1.0.0-rc.1")), ("stable", "rc"))

    def test_the_portable_name_is_the_package_tools_zip_name_and_the_title_uses_the_product_name(self):
        for version in ("1.0.0", "1.0.0-rc.3", "0.1.0-preview.1"):
            self.assertEqual(rc.portable_name(version), pc.zip_name(version))
        self.assertEqual(rc.title_of("1.0.0"), pc.PRODUCT + " 1.0.0")
        self.assertTrue(rc.setup_name("1.0.0").startswith(pc.EXE_NAME + "-"))

    def test_the_names_are_the_ones_the_apps_manifest_rules_require_for_the_setup_and_portable_roles(self):
        for version, kind in (("1.0.0", "stable"), ("1.0.0-rc.2", "rc")):
            with self.subTest(version=version):
                data = us.manifest_dict(version=version, tag="v" + version, channel=kind, min_version="0.0.0")
                data["files"] = [{"role": "setup", "name": rc.setup_name(version), "size": 10, "sha256": us.HASH_A}, {"role": "portable", "name": rc.portable_name(version), "size": 10, "sha256": us.HASH_B}]
                manifest.validate_fields(data, "0" * 64, channels=manifest.CHANNELS_OFFLINE)
                for role, other in (("setup", rc.portable_name(version)), ("portable", rc.setup_name(version)), ("setup", rc.setup_name(version).replace("Setup", "Setpu"))):
                    broken = json.loads(json.dumps(data))
                    next(item for item in broken["files"] if item["role"] == role)["name"] = other
                    with self.assertRaises(manifest.ManifestError):
                        manifest.validate_fields(broken, "0" * 64, channels=manifest.CHANNELS_OFFLINE)

    def test_the_card_text_is_what_the_app_shows_for_the_version_file(self):
        for version in ("1.0.0", "1.0.0-rc.1", "2.10.3"):
            self.assertEqual(rc.app_card_text(version), rc.card_text(version))
        self.assertEqual(app_version.read_version(Path("VERSION"), reader=lambda path: "1.0.0\n").text, "v1.0.0")

    def test_asset_and_published_names(self):
        names = rc.asset_names("1.0.0")
        self.assertEqual(names, {"setup": "ChanceBlogDesktop-1.0.0-Setup.exe", "portable": "ChanceBlogDesktop-1.0.0-win64.zip", "sums": "SHA256SUMS", "info_json": "PACKAGE_INFO.json",
                                 "info_md": "PACKAGE_INFO.md"})
        self.assertEqual(rc.published_names("1.0.0"), tuple(names.values()) + ("update-manifest.json", "update-manifest.json.sig"))
        self.assertNotIn("release_candidate.json", rc.published_names("1.0.0"), "후보 기록은 릴리스에 올리지 않는다")

    def test_constants_that_the_app_also_defines_are_equal(self):
        self.assertEqual((rc.MANIFEST_NAME, rc.SIGNATURE_NAME), (manifest.MANIFEST_NAME, manifest.SIGNATURE_NAME))
        self.assertEqual((rc.DEFAULT_LIMITS.file, rc.DEFAULT_LIMITS.total), (manifest.MAX_FILE_BYTES, manifest.MAX_TOTAL_BYTES))
        self.assertEqual(set(rc.MANIFEST_ROLES), {"setup", "portable"})
        self.assertTrue(set(rc.MANIFEST_ROLES) <= set(manifest.FILE_ROLES))
        self.assertIn(rc.INSTALLER_KIND, manifest.INSTALLER_KINDS)


class GoodFolderTest(unittest.TestCase):
    def test_a_consistent_stable_folder_and_a_consistent_candidate_folder_have_no_problem(self):
        for version in (STABLE, RC):
            with self.subTest(version=version):
                folder = new_release(self, version)
                self.assertEqual(check(folder, version), [])

    def test_the_check_without_a_changelog_or_a_commit_skips_only_those_parts(self):
        folder = new_release(self)
        self.assertEqual(rc.check_chain(folder, STABLE), [])
        self.assertEqual(rc.check_chain(folder, STABLE, commit=FAKE_COMMIT), [])
        self.assertEqual(codes(rc.check_chain(folder, STABLE, commit=OTHER_COMMIT)), ["commit_mismatch"])

    def test_a_version_that_is_not_stable_or_rc_stops_at_once(self):
        folder = new_release(self)
        for version in ("1.0.0-preview.1", "1.0", "", None, "v1.0.0"):
            self.assertEqual(codes(check(folder, version, changelog_text=None)), ["version_shape"], version)


class NameAndFileMutationTest(unittest.TestCase):
    def test_a_typo_in_an_asset_name_is_both_unexpected_and_missing(self):
        folder = new_release(self)
        (folder / rc.setup_name(STABLE)).rename(folder / rc.setup_name(STABLE).replace("Setup", "Setpu"))
        found = pairs(check(folder))
        self.assertIn(("file_unexpected", "ChanceBlogDesktop-1.0.0-Setpu.exe"), found)
        self.assertIn(("file_missing", "ChanceBlogDesktop-1.0.0-Setup.exe"), found)

    def test_one_more_asset_is_unexpected(self):
        folder = new_release(self)
        rts.write(folder / "extra.zip", b"x")
        self.assertIn(("file_unexpected", "extra.zip"), pairs(check(folder)))
        self.assertIn(("sums_missing_line", "extra.zip"), pairs(check(folder)), "해시 목록에도 줄이 없다")

    def test_a_missing_file_is_named_for_every_one_of_the_five_assets_and_the_candidate_record(self):
        for name in list(rc.asset_names(STABLE).values()) + ["release_candidate.json"]:
            with self.subTest(name=name):
                folder = new_release(self)
                (folder / name).unlink()
                self.assertIn("file_missing" if name != "release_candidate.json" else "candidate_unreadable", codes(check(folder)))

    def test_a_subfolder_or_a_link_is_not_a_regular_file(self):
        folder = new_release(self)
        (folder / "sub").mkdir()
        self.assertIn(("file_not_regular", "sub"), pairs(check(folder)))
        link = folder / "link.bin"
        try:
            os.symlink(str(folder / rc.setup_name(STABLE)), str(link))
        except (OSError, NotImplementedError):
            self.skipTest("건너뜀: 이 PC 는 심볼릭 링크를 만들 수 없다")
        self.assertIn(("file_not_regular", "link.bin"), pairs(check(folder)))

    def test_a_stable_folder_with_a_candidate_name_or_a_trial_marker_is_refused_with_the_prerelease_word_problem(self):
        for extra in ("ChanceBlogDesktop-1.0.0-rc.1-Setup.exe", "ChanceBlogDesktop-1.0.0-TESTBUILD-win64.zip", "notes-preview.txt"):
            with self.subTest(extra=extra):
                folder = new_release(self)
                rts.write(folder / extra, b"x")
                self.assertIn("prerelease_word", codes(check(folder)))

    def test_every_prerelease_word_in_a_file_name_stops_a_stable_folder_and_none_stops_a_plain_name(self):
        """QC08·QC09(Q 의 R6) — 사전판 글자 여섯(`-rc`·`-preview`·`-beta`·`-alpha`·`-dev`·`TESTBUILD`)이 각각 따로 정식 폴더를 막는다(하나를 목록에서 지워도 위 시험이 안 잡던 틈)."""
        self.assertEqual(sorted(rc.PRERELEASE_WORDS), sorted(("-rc", "-preview", "-beta", "-alpha", "-dev", "TESTBUILD")))
        for word in rc.PRERELEASE_WORDS:
            with self.subTest(word=word):
                folder = new_release(self)
                rts.write(folder / ("notes" + word + ".txt"), b"x")
                self.assertIn("prerelease_word", codes(check(folder)))
        folder = new_release(self)
        rts.write(folder / "notes.txt", b"x")
        self.assertNotIn("prerelease_word", codes(check(folder)), "사전판 글자가 없는 이름은 이 문제가 아니다(알 수 없는 파일 문제만)")

    def test_a_candidate_folder_may_carry_its_own_rc_name_but_not_the_stable_names(self):
        folder = new_release(self, RC)
        self.assertEqual(check(folder, RC), [])
        for stable_name in ("ChanceBlogDesktop-1.0.0-Setup.exe", "ChanceBlogDesktop-1.0.0-win64.zip"):
            rts.write(folder / stable_name, b"x")
        self.assertIn(("version_mismatch", "ChanceBlogDesktop-1.0.0-Setup.exe"), pairs(check(folder, RC)))


class VersionDiffersInOnePlaceTest(unittest.TestCase):
    """버전이 **한 곳만** 다르면 거절한다 — 곳마다 하나씩."""

    def test_the_version_argument_differs_from_everything_in_the_folder(self):
        folder = new_release(self)
        found = pairs(check(folder, "1.0.1", changelog_text=rts.changelog_text("1.0.1")))
        for place in ("release_candidate.json", rc.setup_name(STABLE), rc.portable_name(STABLE)):
            self.assertIn(("version_mismatch", place), found)

    def test_the_package_info_version_differs(self):
        folder = new_release(self)
        edit_json(folder / "PACKAGE_INFO.json", lambda data: data.update(version="1.0.1"))
        refresh(folder)
        self.assertIn(("version_mismatch", "PACKAGE_INFO.json"), pairs(check(folder)))

    def test_the_package_info_text_does_not_say_the_version(self):
        folder = new_release(self)
        rts.write(folder / "PACKAGE_INFO.md", "# 묶음 정보\n\n- 버전: `1.0.1`\n")
        refresh(folder)
        self.assertIn(("version_mismatch", "PACKAGE_INFO.md"), pairs(check(folder)))

    def test_the_candidate_record_names_another_version(self):
        folder = new_release(self)
        edit_json(folder / "release_candidate.json", lambda data: data.update(version="1.0.1", tag="v1.0.1"))
        found = codes(check(folder))
        self.assertTrue(found, "후보 기록의 버전이 다르면 거절한다")
        self.assertTrue({"asset_name", "candidate_assets"} & set(found), found)

    def test_the_candidate_tag_differs_from_the_version(self):
        folder = new_release(self)
        edit_json(folder / "release_candidate.json", lambda data: data.update(tag="v1.0.1"))
        self.assertIn("candidate_tag", codes(check(folder)))

    def test_the_changelog_top_section_names_another_version(self):
        folder = new_release(self)
        self.assertIn(("changelog_top", "1.0.1"), pairs(check(folder, changelog_text=rts.changelog_text("1.0.1"))))
        self.assertIn("changelog_section", codes(check(folder, changelog_text=rts.changelog_text("1.0.1"))), "그 버전의 절이 없다")

    def test_the_changelog_has_the_version_but_not_at_the_top(self):
        text = rts.changelog_text("1.0.0") + "\n" + rts.notes_section("1.1.0", date="2027-01-01")
        folder = new_release(self)
        self.assertEqual(check(folder, changelog_text=text), [])                                     # 맨 위는 1.0.0
        higher = rts.changelog_text("1.1.0").replace("## [0.1.0-preview.1]", rts.notes_section("1.0.0") + "\n## [0.1.0-preview.1]")
        self.assertIn(("changelog_top", "1.1.0"), pairs(check(folder, changelog_text=higher)))

    def test_the_setup_name_or_the_zip_name_carries_another_version(self):
        for name in (rc.setup_name(STABLE), rc.portable_name(STABLE)):
            with self.subTest(name=name):
                folder = new_release(self)
                (folder / name).rename(folder / name.replace("1.0.0", "1.0.1"))
                self.assertIn(("version_mismatch", name.replace("1.0.0", "1.0.1")), pairs(check(folder)))

    def test_the_manifest_of_the_final_phase_differs_in_version_tag_channel_or_commit(self):
        for label, change, expected in (
            ("version", lambda obj: obj.update(version="1.0.1", tag="v1.0.1", files=[{"role": "setup", "name": "ChanceBlogDesktop-1.0.1-Setup.exe", "size": 5, "sha256": us.HASH_A}]), "version_mismatch"),
            ("tag", lambda obj: obj.update(tag="v1.0.1"), "manifest_rejected"),
            ("commit", lambda obj: obj.update(commit=OTHER_COMMIT), "manifest_commit"),
            ("installer", lambda obj: obj.update(installer={"kind": "velopack", "pack_id": "ChanceBlogDesktop"}), "manifest_installer"),
            ("pack", lambda obj: obj.update(installer={"kind": "inno", "pack_id": "Other"}), "manifest_installer"),
            ("files", lambda obj: obj["files"].pop(), "manifest_files"),
        ):
            with self.subTest(label=label):
                folder = new_release(self)
                make_final(folder, change=change)
                self.assertIn(expected, codes(check(folder, phase="final")), label)

    def test_the_manifest_channel_must_match_the_version_kind(self):
        folder = new_release(self, RC)
        make_final(folder, RC, change=lambda obj: obj.update(channel="stable", version="1.0.0", tag="v1.0.0", files=[
            {"role": "setup", "name": "ChanceBlogDesktop-1.0.0-Setup.exe", "size": 5, "sha256": us.HASH_A}]))
        self.assertTrue({"version_mismatch", "channel_mismatch"} <= set(codes(check(folder, RC, phase="final"))))


class SumsTest(unittest.TestCase):
    def sums_path(self, folder):
        return folder / "SHA256SUMS"

    def test_a_wrong_hash_a_missing_line_an_extra_line_and_a_duplicate_are_each_named(self):
        folder = new_release(self)
        lines = self.sums_path(folder).read_text(encoding="utf-8").splitlines()
        digest, name = lines[0].split("  ")
        cases = {
            "sums_mismatch": "\n".join([f"{'0' * 64}  {name}"] + lines[1:]) + "\n",
            "sums_missing_line": "\n".join(lines[1:]) + "\n",
            "sums_extra_line": "\n".join(lines + [f"{digest}  ghost.bin"]) + "\n",
            "sums_duplicate": "\n".join(lines + [lines[0]]) + "\n",
        }
        for code, text in cases.items():
            with self.subTest(code=code):
                rts.write(self.sums_path(folder), text)
                self.assertIn(code, codes(check(folder)))

    def test_a_malformed_list_is_refused_by_shape(self):
        folder = new_release(self)
        good = self.sums_path(folder).read_text(encoding="utf-8")
        for label, text in {"crlf": good.replace("\n", "\r\n"), "single space": good.replace("  ", " ", 1), "uppercase": good.upper(), "no final newline": good.rstrip("\n"), "blank line": good + "\n",
                            "empty": "", "path in name": good.replace("PACKAGE_INFO.md", "sub/PACKAGE_INFO.md")}.items():
            with self.subTest(label=label):
                rts.write(self.sums_path(folder), text)
                self.assertTrue({"sums_shape", "sums_mismatch", "sums_extra_line", "sums_missing_line"} & set(codes(check(folder))), label)
        rts.write(self.sums_path(folder), good.replace("\n", "\r\n"))
        self.assertIn("sums_shape", codes(check(folder)))

    def test_a_line_for_the_candidate_record_itself_is_not_allowed(self):
        folder = new_release(self)
        digest = hashlib.sha256((folder / "release_candidate.json").read_bytes()).hexdigest()
        rts.write(self.sums_path(folder), self.sums_path(folder).read_text(encoding="utf-8") + f"{digest}  release_candidate.json\n")
        self.assertIn(("sums_extra_line", "release_candidate.json"), pairs(check(folder)))

    def test_the_list_covers_every_file_except_itself_and_the_candidate_record(self):
        folder = new_release(self)
        names = [line.split("  ")[1] for line in self.sums_path(folder).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(names), sorted(item.name for item in folder.iterdir() if item.name not in ("SHA256SUMS", "release_candidate.json")))

    def test_write_sums_renders_sorted_lines_with_lf_and_skips_itself_and_the_candidate(self):
        folder = new_release(self)
        text = rc.write_sums(folder)
        data = (folder / "SHA256SUMS").read_bytes()
        self.assertEqual(data, text.encode("utf-8"))
        self.assertNotIn(b"\r", data)
        names = [line.split("  ")[1] for line in text.splitlines()]
        self.assertEqual(names, sorted(names))
        self.assertNotIn("SHA256SUMS", names)
        self.assertNotIn("release_candidate.json", names)
        for line in text.splitlines():
            digest, name = line.split("  ")
            self.assertEqual(digest, hashlib.sha256((folder / name).read_bytes()).hexdigest())

    def test_parse_sums_reads_only_the_exact_format(self):
        good = f"{'a' * 64}  one.bin\n{'b' * 64}  two.bin\n"
        self.assertEqual(rc.parse_sums(good.encode()), ([("one.bin", "a" * 64), ("two.bin", "b" * 64)], []))
        for bad in (b"", b"\n", good.encode() + b"\n", good.replace("\n", "\r\n").encode(), good.encode().rstrip(b"\n"), b"\xff\xfe", (f"{'A' * 64}  one.bin\n").encode(), (f"{'a' * 63}  one.bin\n").encode()):
            self.assertEqual(rc.parse_sums(bad)[0], [], bad[:12])
            self.assertTrue(rc.parse_sums(bad)[1], bad[:12])


class HashAndRecordTest(unittest.TestCase):
    def test_a_changed_byte_in_any_asset_is_found_by_the_rehash(self):
        for role in ("setup", "portable", "info_json", "info_md"):
            with self.subTest(role=role):
                folder = new_release(self)
                path = folder / rc.asset_names(STABLE)[role]
                data = bytearray(path.read_bytes())
                data[len(data) // 2] ^= 1
                path.write_bytes(bytes(data))
                self.assertIn(("asset_hash_differs", path.name), pairs(check(folder)))

    def test_a_size_change_is_found_before_hashing(self):
        folder = new_release(self)
        with open(folder / rc.setup_name(STABLE), "ab") as handle:
            handle.write(b"x")
        self.assertIn(("asset_size_differs", rc.setup_name(STABLE)), pairs(check(folder)))

    def test_the_candidate_record_is_compared_not_trusted_so_a_matching_edit_of_sums_alone_does_not_hide_a_changed_file(self):
        folder = new_release(self)
        rts.write(folder / rc.portable_name(STABLE), b"swapped-bytes")
        refresh(folder, candidate=False)                          # 해시 목록은 새 파일에 맞췄지만 후보 기록은 그대로
        self.assertIn(("asset_size_differs", rc.portable_name(STABLE)), pairs(check(folder)))

    def test_record_shape_problems_are_each_named(self):
        cases = {
            "candidate_keys": lambda d: d.update(extra=1),
            "candidate_schema": lambda d: d.update(candidate_schema=2),
            "candidate_product": lambda d: d.update(product="Other"),
            "candidate_version": lambda d: d.update(version="1.0.0-preview.1", tag="v1.0.0-preview.1"),
            "candidate_channel": lambda d: d.update(channel="rc"),
            "candidate_commit": lambda d: d.update(commit="XYZ"),
            "candidate_image": lambda d: d.update(image={"name": "has space", "version": "1"}),
            "candidate_installer": lambda d: d.update(installer={"kind": "velopack", "pack_id": "ChanceBlogDesktop"}),
            "candidate_assets": lambda d: d["assets"].pop(),
            "asset_name": lambda d: d["assets"][0].update(name="Other.exe"),
            "asset_size": lambda d: d["assets"][0].update(size=0),
            "asset_sha256": lambda d: d["assets"][0].update(sha256="Z" * 64),
        }
        for code, change in cases.items():
            with self.subTest(code=code):
                folder = new_release(self)
                edit_json(folder / "release_candidate.json", change)
                self.assertIn(code, codes(check(folder)))

    def test_a_duplicate_key_or_a_bom_or_garbage_in_the_record_is_refused(self):
        folder = new_release(self)
        good = (folder / "release_candidate.json").read_bytes()
        for label, data in {"duplicate": good.replace(b'"product"', b'"version": "1.0.0",\n  "product"', 1), "bom": b"\xef\xbb\xbf" + good, "garbage": b"not json", "array": b"[]\n",
                            "nan": good.replace(b'"size": ', b'"size": NaN, "x": ', 1)}.items():
            with self.subTest(label=label):
                (folder / "release_candidate.json").write_bytes(data)
                self.assertTrue({"candidate_json", "candidate_keys"} & set(codes(check(folder))), label)

    def test_a_record_over_64_kib_is_refused_without_reading_it_all(self):
        folder = new_release(self)
        (folder / "release_candidate.json").write_bytes(b" " * (rc.MAX_CANDIDATE_BYTES + 1))
        self.assertIn("candidate_unreadable", codes(check(folder)))

    def test_the_size_caps_follow_the_limits_argument_and_default_to_the_apps(self):
        folder = new_release(self)
        small = rc.Limits(file=len(rts.SETUP_BYTES) - 1, total=rc.DEFAULT_LIMITS.total, support=rc.DEFAULT_LIMITS.support)
        self.assertIn("asset_size", codes(check(folder, limits=small)))
        total = rc.Limits(file=rc.DEFAULT_LIMITS.file, total=len(rts.SETUP_BYTES) + len(rts.ZIP_BYTES) - 1, support=rc.DEFAULT_LIMITS.support)
        self.assertIn("assets_total", codes(check(folder, limits=total)))
        support = rc.Limits(file=rc.DEFAULT_LIMITS.file, total=rc.DEFAULT_LIMITS.total, support=5)
        self.assertIn("asset_size", codes(check(folder, limits=support)))
        at_cap = rc.Limits(file=len(rts.ZIP_BYTES) if len(rts.ZIP_BYTES) > len(rts.SETUP_BYTES) else len(rts.SETUP_BYTES), total=len(rts.SETUP_BYTES) + len(rts.ZIP_BYTES), support=rc.DEFAULT_LIMITS.support)
        self.assertEqual(check(folder, limits=at_cap), [], "한도와 같으면 통과")

    def test_build_and_render_make_a_valid_deterministic_record(self):
        folder = new_release(self, with_candidate=False)
        record = rc.build_candidate(folder, STABLE, commit=FAKE_COMMIT, image=("win25", "20261101.1.0"))
        self.assertEqual(rc.validate_candidate(record), [])
        self.assertEqual(rc.render_candidate(record), rc.render_candidate(rc.build_candidate(folder, STABLE, commit=FAKE_COMMIT, image=("win25", "20261101.1.0"))))
        data = rc.render_candidate(record)
        self.assertTrue(data.endswith(b"\n") and not data.endswith(b"\n\n"))
        self.assertNotIn(b"\r", data)
        self.assertEqual(json.loads(data)["assets"][0]["name"], rc.setup_name(STABLE))
        self.assertEqual([item["role"] for item in record["assets"]], list(rc.ASSET_ROLES))

    def test_verify_candidate_alone_is_what_the_signing_job_runs(self):
        folder = new_release(self)
        record, problems = rc.verify_candidate(folder)
        self.assertEqual((problems, record["version"], record["commit"]), ([], STABLE, FAKE_COMMIT))
        rts.write(folder / "stray.txt", b"x")
        self.assertEqual(pairs(rc.verify_candidate(folder)[1]), [("file_unexpected", "stray.txt")])


class PackageInfoTest(unittest.TestCase):
    def change(self, **updates):
        folder = new_release(self)
        edit_json(folder / "PACKAGE_INFO.json", lambda data: data.update(updates))
        refresh(folder)
        return folder

    def test_each_wrong_value_is_named(self):
        for code, updates in {
            "info_variant": {"variant": "inner"},
            "info_commit": dict(git=dict(commit=OTHER_COMMIT)),
            "info_package": dict(package=dict(name="Other.zip", sha256="0" * 64, bytes=1)),
            "info_package_hash": dict(package=dict(name=rc.portable_name(STABLE), sha256="0" * 64, bytes=len(rts.ZIP_BYTES))),
            "info_trial": {"trial": True},
            "info_not_eligible": {"release_eligible": False},
            "info_channel": {"channel": "rc"},
        }.items():
            with self.subTest(code=code):
                self.assertIn(code, codes(check(self.change(**updates))))

    def test_a_candidate_with_the_rc_channel_in_its_package_info_is_fine_and_a_stable_one_with_stable_too(self):
        folder = new_release(self, RC, info_extra={"channel": "rc"})
        self.assertEqual(check(folder, RC), [])
        folder = new_release(self, STABLE, info_extra={"channel": "stable"})
        self.assertEqual(check(folder, STABLE), [])
        folder = new_release(self, STABLE, info_extra={"channel": "personal-pc-preview"})
        self.assertEqual(check(folder, STABLE), [], "옛 채널 이름은 사슬이 판정하지 않는다(다른 갈래가 정한다)")

    def test_artifacts_when_present_must_equal_the_candidate_record(self):
        folder = new_release(self)
        record = json.loads((folder / "release_candidate.json").read_text(encoding="utf-8"))
        wanted = {item["role"]: {"name": item["name"], "sha256": item["sha256"], "bytes": item["size"]} for item in record["assets"] if item["role"] in ("setup", "portable")}
        edit_json(folder / "PACKAGE_INFO.json", lambda data: data.update(artifacts=wanted))
        refresh(folder)
        self.assertEqual(check(folder), [])
        for label, damage in (("name", lambda a: a["setup"].update(name="x.exe")), ("hash", lambda a: a["portable"].update(sha256="0" * 64)), ("bytes", lambda a: a["setup"].update(bytes=1)),
                              ("role", lambda a: a.pop("portable")), ("extra role", lambda a: a.update(feed={"name": "f", "sha256": "0" * 64, "bytes": 1}))):
            with self.subTest(label=label):
                folder = new_release(self)
                bad = json.loads(json.dumps(wanted))
                damage(bad)
                edit_json(folder / "PACKAGE_INFO.json", lambda data: data.update(artifacts=bad))
                refresh(folder)
                self.assertIn("info_artifacts", codes(check(folder)))

    def test_an_unreadable_package_info_is_a_problem(self):
        folder = new_release(self)
        rts.write(folder / "PACKAGE_INFO.json", b"{not json")
        refresh(folder)
        self.assertIn("info_unreadable", codes(check(folder)))


class FinalPhaseTest(unittest.TestCase):
    def test_a_signed_folder_whose_manifest_obeys_the_apps_rules_and_matches_the_record_passes(self):
        for version in (STABLE, RC):
            with self.subTest(version=version):
                folder = new_release(self, version)
                make_final(folder, version)
                self.assertEqual(check(folder, version, phase="final"), [])

    def test_the_candidate_phase_refuses_the_manifest_files_as_unexpected_and_the_final_phase_needs_them(self):
        folder = new_release(self)
        make_final(folder)
        self.assertIn("file_unexpected", codes(check(folder, phase="candidate")))
        for name in ("update-manifest.json", "update-manifest.json.sig"):
            other = new_release(self)
            make_final(other)
            (other / name).unlink()
            refresh(other, candidate=False)
            self.assertIn(("file_missing", name), pairs(check(other, phase="final")))

    def test_the_sums_after_signing_must_list_the_manifest_and_the_signature(self):
        folder = new_release(self)
        make_final(folder)
        lines = [line for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if "update-manifest" not in line]
        rts.write(folder / "SHA256SUMS", "\n".join(lines) + "\n")
        found = pairs(check(folder, phase="final"))
        self.assertIn(("sums_missing_line", "update-manifest.json"), found)
        self.assertIn(("sums_missing_line", "update-manifest.json.sig"), found)

    def test_the_old_sums_from_the_candidate_phase_do_not_pass_after_signing(self):
        folder = new_release(self)
        old = (folder / "SHA256SUMS").read_bytes()
        make_final(folder)
        rts.write(folder / "SHA256SUMS", old)
        self.assertIn("sums_missing_line", codes(check(folder, phase="final")))

    def test_a_manifest_the_app_would_refuse_is_named_with_its_reason(self):
        folder = new_release(self)
        make_final(folder, change=lambda obj: obj.update(seq=1))
        self.assertIn(("manifest_rejected", "seq"), pairs(check(folder, phase="final")))
        folder = new_release(self)
        make_final(folder, signature=b"short\n")
        self.assertIn(("manifest_rejected", "sig_shape"), pairs(check(folder, phase="final")))

    def test_the_candidate_hash_of_the_changed_sums_file_is_not_compared_after_signing_but_other_assets_still_are(self):
        folder = new_release(self)
        make_final(folder)
        path = folder / rc.setup_name(STABLE)
        path.write_bytes(path.read_bytes() + b"x")
        refresh(folder, candidate=False)
        self.assertIn("asset_size_differs", codes(check(folder, phase="final")))


class AssembleTest(unittest.TestCase):
    def sources(self, version=STABLE, *, split=False):
        holder = rts.temp_dir()
        self.addCleanup(holder.cleanup)
        base = Path(holder.name)
        folder = rts.fake_release(base / "all", version, with_candidate=False)
        (folder / "SHA256SUMS").unlink()                    # 묶음 빌드의 옛 해시 목록은 쓰지 않는다
        if not split:
            return base, [folder]
        one, two = base / "package", base / "installer"
        one.mkdir()
        two.mkdir()
        for item in folder.iterdir():
            shutil.move(str(item), str((two if item.name.endswith("Setup.exe") else one) / item.name))
        return base, [one, two]

    def run_assemble(self, base, sources, version=STABLE, **kwargs):
        kwargs.setdefault("commit", FAKE_COMMIT)
        kwargs.setdefault("image", ("win25", "20261101.1.0"))
        kwargs.setdefault("changelog_text", rts.changelog_text(version))
        return rc.assemble(version, sources, base / "release", **kwargs)

    def test_assemble_collects_the_named_files_writes_sums_and_the_record_and_the_chain_holds(self):
        for version in (STABLE, RC):
            for split in (False, True):
                with self.subTest(version=version, split=split):
                    base, sources = self.sources(version, split=split)
                    record = self.run_assemble(base, sources, version)
                    out = base / "release"
                    self.assertEqual(sorted(item.name for item in out.iterdir()), sorted(list(rc.asset_names(version).values()) + ["release_candidate.json"]))
                    self.assertEqual(check(out, version), [])
                    self.assertEqual(record, json.loads((out / "release_candidate.json").read_text(encoding="utf-8")))
                    self.assertEqual((record["version"], record["tag"], record["channel"], record["commit"]), (version, "v" + version, rc.channel_of(version), FAKE_COMMIT))
                    self.assertEqual(record["image"], {"name": "win25", "version": "20261101.1.0"})
                    self.assertEqual(record["installer"], {"kind": "inno", "pack_id": "ChanceBlogDesktop"})
                    for item in record["assets"]:
                        data = (out / item["name"]).read_bytes()
                        self.assertEqual((item["size"], item["sha256"]), (len(data), hashlib.sha256(data).hexdigest()))

    def test_the_sums_the_assemble_wrote_have_one_sorted_line_per_collected_file(self):
        base, sources = self.sources()
        self.run_assemble(base, sources)
        lines = (base / "release" / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        self.assertEqual([line.split("  ")[1] for line in lines], sorted(["PACKAGE_INFO.json", "PACKAGE_INFO.md", rc.portable_name(STABLE), rc.setup_name(STABLE)]))

    def test_a_stale_asset_of_another_version_in_a_source_folder_is_refused(self):
        for stale in ("ChanceBlogDesktop-0.9.0-Setup.exe", "ChanceBlogDesktop-1.0.0-TESTBUILD-win64.zip"):
            with self.subTest(stale=stale):
                base, sources = self.sources()
                rts.write(sources[0] / stale, b"old")
                with self.assertRaises(rc.ChainError) as raised:
                    self.run_assemble(base, sources)
                self.assertIn(("stale_asset", stale), pairs(raised.exception.problems))
                self.assertFalse((base / "release").exists(), "거절했으면 출력 폴더를 만들지 않는다")

    def test_a_missing_source_file_names_it(self):
        base, sources = self.sources()
        (sources[0] / rc.setup_name(STABLE)).unlink()
        with self.assertRaises(rc.ChainError) as raised:
            self.run_assemble(base, sources)
        self.assertEqual(pairs(raised.exception.problems), [("file_missing", rc.setup_name(STABLE))])

    def test_the_same_file_in_two_sources_must_be_identical(self):
        base, sources = self.sources(split=True)
        rts.write(sources[0] / rc.setup_name(STABLE), b"first")
        rts.write(sources[1] / rc.setup_name(STABLE), b"second")
        with self.assertRaises(rc.ChainError) as raised:
            self.run_assemble(base, sources)
        self.assertIn(("source_conflict", rc.setup_name(STABLE)), pairs(raised.exception.problems))

    def test_the_output_folder_must_be_new_or_empty(self):
        base, sources = self.sources()
        (base / "release").mkdir()
        self.run_assemble(base, sources)                       # 빈 폴더는 된다
        with self.assertRaises(rc.ChainError) as raised:
            self.run_assemble(base, sources)                   # 방금 채운 폴더는 안 된다
        self.assertEqual(codes(raised.exception.problems), ["out_not_empty"])

    def test_a_wrong_commit_shape_or_version_stops_before_anything_is_written(self):
        base, sources = self.sources()
        with self.assertRaises(rc.ChainError):
            self.run_assemble(base, sources, commit="abc")
        with self.assertRaises(rc.ChainError):
            self.run_assemble(base, sources, "1.0.0-preview.1")
        self.assertFalse((base / "release").exists())

    def test_a_package_info_that_disagrees_with_the_zip_or_the_changelog_removes_the_record(self):
        base, sources = self.sources()
        edit_json(sources[0] / "PACKAGE_INFO.json", lambda data: data["package"].update(sha256="0" * 64))
        with self.assertRaises(rc.ChainError) as raised:
            self.run_assemble(base, sources)
        self.assertIn("info_package_hash", codes(raised.exception.problems))
        self.assertFalse((base / "release" / "release_candidate.json").exists(), "확인에서 걸리면 후보 기록을 남기지 않는다")
        base, sources = self.sources()
        with self.assertRaises(rc.ChainError) as raised:
            self.run_assemble(base, sources, changelog_text=rts.changelog_text("1.0.1"))
        self.assertIn("changelog_top", codes(raised.exception.problems))
        self.assertFalse((base / "release" / "release_candidate.json").exists())

    def test_the_commit_in_the_package_info_must_be_the_assembled_commit(self):
        base, sources = self.sources()
        with self.assertRaises(rc.ChainError) as raised:
            self.run_assemble(base, sources, commit=OTHER_COMMIT)
        self.assertIn("info_commit", codes(raised.exception.problems))


class CommandLineTest(unittest.TestCase):
    def prepare(self, version=STABLE):
        holder = rts.temp_dir()
        self.addCleanup(holder.cleanup)
        base = Path(holder.name)
        folder = rts.fake_release(base / "src", version, with_candidate=False)
        (folder / "SHA256SUMS").unlink()
        rts.write(base / "VERSION", version + "\n")
        rts.write(base / "CHANGELOG.md", rts.changelog_text(version))
        return base

    def test_assemble_check_and_names_through_main(self):
        base = self.prepare()
        common = ["--version-file", str(base / "VERSION"), "--changelog", str(base / "CHANGELOG.md")]
        code, out, err = run_tool(["assemble", "--source", str(base / "src"), "--out", str(base / "release"), "--commit", FAKE_COMMIT, "--image-name", "win25", "--image-version", "1"] + common)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("모았다: 버전 1.0.0 · 태그 v1.0.0 · 파일 5개 + 후보 기록\n"))
        for name in rc.asset_names(STABLE).values():
            self.assertIn(f"- {name} ", out)
        code, out, err = run_tool(["check", "--dir", str(base / "release"), "--commit", FAKE_COMMIT] + common)
        self.assertEqual((code, err, out), (0, "", "사슬이 맞다: 버전 1.0.0 · 태그 v1.0.0 · 단계 candidate\n"))
        code, out, err = run_tool(["names", "--version-file", str(base / "VERSION")])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "tag=v1.0.0\ntitle=ChanceBlog Desktop 1.0.0\nchannel=stable\nprerelease=false\nsetup=ChanceBlogDesktop-1.0.0-Setup.exe\nportable=ChanceBlogDesktop-1.0.0-win64.zip\n")

    def test_names_of_a_candidate_says_prerelease_true(self):
        base = self.prepare(RC)
        code, out, _err = run_tool(["names", "--version-file", str(base / "VERSION")])
        self.assertEqual(code, 0)
        self.assertIn("prerelease=true\n", out)
        self.assertIn("channel=rc\n", out)
        self.assertIn("tag=v1.0.0-rc.1\n", out)

    def test_check_reports_each_problem_on_its_own_line_and_exits_one(self):
        base = self.prepare()
        common = ["--version-file", str(base / "VERSION"), "--changelog", str(base / "CHANGELOG.md")]
        run_tool(["assemble", "--source", str(base / "src"), "--out", str(base / "release"), "--commit", FAKE_COMMIT] + common)
        rts.write(base / "release" / "stray.txt", b"x")
        code, out, err = run_tool(["check", "--dir", str(base / "release")] + common)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("사슬에 문제가 있다.\n", err)
        self.assertIn("문제: file_unexpected — stray.txt\n", err)
        self.assertIn("문제: sums_missing_line — stray.txt\n", err)

    def test_final_phase_check_and_the_sums_command_after_signing(self):
        base = self.prepare()
        common = ["--version-file", str(base / "VERSION"), "--changelog", str(base / "CHANGELOG.md")]
        run_tool(["assemble", "--source", str(base / "src"), "--out", str(base / "release"), "--commit", FAKE_COMMIT] + common)
        make_final(base / "release")
        (base / "release" / "SHA256SUMS").write_bytes(b"stale\n")                                      # 서명 뒤에는 해시 목록을 다시 써야 한다 — 아래 명령이 쓴다
        self.assertIn("sums_shape", codes(rc.check_chain(base / "release", STABLE, phase="final")))
        code, out, err = run_tool(["sums", "--dir", str(base / "release")])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("SHA256SUMS 를 다시 썼다: 파일 6개", out)
        code, out, err = run_tool(["check", "--dir", str(base / "release"), "--phase", "final", "--commit", FAKE_COMMIT] + common)
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("단계 final", out)

    def test_the_commit_comes_from_the_environment_or_from_git_and_a_missing_one_stops(self):
        base = self.prepare()
        common = ["--version-file", str(base / "VERSION"), "--changelog", str(base / "CHANGELOG.md"), "--source", str(base / "src"), "--out", str(base / "release")]
        code, _out, err = run_tool(["assemble"] + common, environ={}, run=lambda command, **kwargs: rts.FakeProcess(1, b"", b""))
        self.assertEqual(code, 2)
        self.assertFalse((base / "release").exists())
        code, _out, err = run_tool(["assemble"] + common, environ={"GITHUB_SHA": FAKE_COMMIT, "ImageOS": "win25", "ImageVersion": "20261101.1.0"})
        self.assertEqual((code, err), (0, ""))
        record = json.loads((base / "release" / "release_candidate.json").read_text(encoding="utf-8"))
        self.assertEqual((record["commit"], record["image"]), (FAKE_COMMIT, {"name": "win25", "version": "20261101.1.0"}))
        shutil.rmtree(base / "release")
        seen = []

        def fake_git(command, **kwargs):
            seen.append(command)
            return type("Done", (), {"returncode": 0, "stdout": FAKE_COMMIT + "\n", "stderr": ""})()
        code, _out, err = run_tool(["assemble"] + common, environ={}, run=fake_git)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(seen[0][0], "git")
        self.assertEqual(seen[0][-2:], ["rev-parse", "HEAD"])
        record = json.loads((base / "release" / "release_candidate.json").read_text(encoding="utf-8"))
        self.assertEqual(record["image"], {"name": "unknown", "version": "unknown"}, "러너 밖에서는 이미지 이름을 모른다고 적는다")

    def test_a_bad_version_file_or_arguments_print_the_fixed_sentences(self):
        base = self.prepare()
        rts.write(base / "VERSION", "0.1.0-preview.1\n")
        code, _out, err = run_tool(["names", "--version-file", str(base / "VERSION")])
        self.assertEqual((code, err), (2, "보이지 못했다: VERSION 을 읽지 못했거나 버전 글이 정식·후보 모양이 아니다.\n"))
        for argv in ([], ["bogus"], ["check"], ["assemble"], ["sums"], ["notes"], ["check", "--dir"]):
            code, out, err = run_tool(argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertEqual(err, "사용법 오류: assemble --source 폴더 [--out 폴더] · check --dir 폴더 · sums --dir 폴더 · notes --out 파일 · names 중 하나를 쓴다.\n")

    def test_the_parser_defaults_are_the_repository_root_files_and_a_folder_named_release(self):
        """R7(Q) — R-3 워크플로가 인자 없이(기본값으로) 부르는 길의 기본값: `VERSION`·`CHANGELOG.md` 는 저장소 맨 위 폴더의 것이고 모으기의 출력은 `release` 폴더다(문서의 호출 순서와 같다)."""
        parser = rc._build_parser()
        for argv in (["assemble", "--source", "x"], ["check", "--dir", "x"], ["notes", "--out", "x"], ["names"]):
            with self.subTest(argv=argv):
                parsed = parser.parse_args(argv)
                self.assertEqual(parsed.version_file, str(rc.ROOT / "VERSION"))
                if hasattr(parsed, "changelog"):
                    self.assertEqual(parsed.changelog, str(rc.ROOT / "CHANGELOG.md"))
        self.assertEqual(parser.parse_args(["assemble", "--source", "x"]).out, "release")
        self.assertEqual((rc.ROOT / "VERSION").name, "VERSION")
        self.assertEqual((rc.ROOT / "CHANGELOG.md").name, "CHANGELOG.md")

    def test_with_no_path_arguments_the_whole_flow_reads_the_repository_root_by_default(self):
        """R7(Q) — 기본값으로 부른 결과가 실제로 맞다: `ROOT` 를 임시 폴더로 바꾸고 `--version-file`·`--changelog` 없이 `assemble`·`check`·`names`·`notes` 를 부른다(기본 경로의 글자 하나가 틀리면 빨개진다)."""
        base = self.prepare()
        body = base / "body.md"
        with mock.patch.object(rc, "ROOT", base):
            code, out, err = run_tool(["assemble", "--source", str(base / "src"), "--out", str(base / "release"), "--commit", FAKE_COMMIT, "--image-name", "win25", "--image-version", "1"])
            self.assertEqual((code, err), (0, ""), out)
            code, out, err = run_tool(["check", "--dir", str(base / "release"), "--commit", FAKE_COMMIT])
            self.assertEqual((code, err, out), (0, "", "사슬이 맞다: 버전 1.0.0 · 태그 v1.0.0 · 단계 candidate\n"))
            code, out, err = run_tool(["names"])
            self.assertEqual((code, err), (0, ""))
            self.assertIn("tag=v1.0.0\n", out)
            code, _out, err = run_tool(["notes", "--out", str(body)])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(body.read_bytes().decode("utf-8").replace(chr(13) + chr(10), chr(10)), rc.release_body(rts.changelog_text(STABLE), STABLE))

    def test_the_script_file_runs_as_a_program(self):
        base = self.prepare()
        environ = {key: value for key, value in os.environ.items() if key not in ("GITHUB_SHA", "ImageOS", "ImageVersion")}
        environ.pop("PYTHONPATH", None)
        environ["PYTHONUTF8"] = "1"
        environ["PYTHONIOENCODING"] = "utf-8"            # 부모 환경(예: cp949)에 흔들리지 않게 자식의 입출력 인코딩을 못박는다(Q 의 R3)
        done = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "names", "--version-file", str(base / "VERSION")], capture_output=True, env=environ, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("tag=v1.0.0", done.stdout.decode("utf-8").replace("\r\n", "\n"))


class SourceShapeTest(unittest.TestCase):
    def test_standard_library_only_and_the_only_child_process_is_git_rev_parse(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        top = {alias.name.split(".")[0] for node in tree.body if isinstance(node, ast.Import) for alias in node.names}
        top |= {(node.module or "").split(".")[0] for node in tree.body if isinstance(node, ast.ImportFrom)}
        self.assertFalse(top & {"socket", "urllib", "http", "ssl", "requests", "chanceblog_desktop"}, top)
        literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertIn("rev-parse", literals)
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertEqual([name for name in calls if name in ("run", "subprocess.run", "Popen", "subprocess.Popen", "os.system")], ["run"], "하위 프로세스를 띄우는 곳은 `git rev-parse` 한 곳")
        self.assertNotIn("print", calls)


if __name__ == "__main__":
    unittest.main()
