"""화면 '정보' 카드의 버전·커밋 앞 7자리·'개인 PC 제한 시험용, 미서명 Package' 한 줄(`ui/core/version.py` 의 `PACKAGE_INFO.json` 읽기와 `settings_view.info_vm`) 시험 — PySide6 없이 돈다.

지키는 것: ① 묶음의 정보 파일이 있고 모양이 맞을 때만 더한다(없거나 틀리면 개발 화면과 한 글자도 다르지 않다) ② 파일 안의 글을 그대로 보이지 않는다(커밋은 40자리 16진수일 때만 앞 7자리,
안내 문장은 코드의 고정 문장) ③ 빌드 도구가 만든 진짜 정보 파일이 이 읽기를 통과한다(생성기와 읽개의 약속) ④ 기존 시험이 못박은 `{label, text}` 두 칸 모양은 그대로다.
"""
import json
import unittest
from pathlib import Path

import packaging_support as ps
from chanceblog_desktop.ui.core import settings_view as sv
from chanceblog_desktop.ui.core import version as app_version

VersionInfo = app_version.VersionInfo
NUMBER = ps.VERSION
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def info_text(**changes):
    data = {"version": NUMBER, "channel": "personal-pc-preview", "git": {"commit": COMMIT, "clean": True}, "signing": {"signed": False}, "files": {}}
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return json.dumps(data)


class ParsePackageInfoTest(unittest.TestCase):
    def test_a_good_file_gives_the_first_seven_commit_characters_and_the_fixed_notice(self):
        self.assertEqual(app_version.parse_package_info(info_text(), NUMBER), (COMMIT[:7], "개인 PC 제한 시험용, 미서명 Package"))

    def test_the_notice_comes_from_the_code_never_from_the_file(self):
        text = info_text(notice="전혀 다른 글 <b>x</b>", smartscreen="무엇이든")
        self.assertEqual(app_version.parse_package_info(text, NUMBER)[1], app_version.PACKAGE_NOTICE)
        self.assertNotIn("전혀 다른 글", " ".join(app_version.parse_package_info(text, NUMBER)))

    def test_anything_wrong_gives_nothing(self):
        bad = {
            "not json": "banana",
            "empty": "",
            "list": "[1, 2]",
            "text json": '"x"',
            "number json": "3",
            "null": "null",
            "other version": info_text(version="9.9.9"),
            "no version": info_text(version=None),
            "version as number": info_text(version=1),
        }
        for name, raw in bad.items():
            with self.subTest(name=name):
                self.assertEqual(app_version.parse_package_info(raw, NUMBER), ("", ""), name)
        for raw in (None, 5, b"bytes", ["x"]):
            self.assertEqual(app_version.parse_package_info(raw, NUMBER), ("", ""), repr(raw))

    def test_a_bad_commit_hides_only_the_commit_and_a_bad_channel_or_signature_hides_only_the_notice(self):
        for name, commit in (("short", COMMIT[:7]), ("uppercase", COMMIT.upper()), ("not hex", "g" * 40), ("long", COMMIT + "0"), ("number", 12345), ("empty", ""), ("spaces", " " + COMMIT[1:])):
            with self.subTest(commit=name):
                self.assertEqual(app_version.parse_package_info(info_text(git={"commit": commit}), NUMBER), ("", app_version.PACKAGE_NOTICE), name)
        for name, git in (("not a dict", "x"), ("none", None), ("list", [COMMIT])):
            self.assertEqual(app_version.parse_package_info(info_text(git=git), NUMBER)[0], "", name)
        for name, changes in (("other channel", dict(channel="stable")), ("no channel", dict(channel=None)), ("signed", dict(signing={"signed": True})), ("signed as text", dict(signing={"signed": "false"})),
                              ("signed zero", dict(signing={"signed": 0})), ("no signed", dict(signing={})), ("signing not a dict", dict(signing="x")), ("no signing", dict(signing=None))):
            with self.subTest(name=name):
                self.assertEqual(app_version.parse_package_info(info_text(**changes), NUMBER), (COMMIT[:7], ""), name)

    def test_a_deeply_nested_or_huge_text_is_ignored_without_an_exception(self):
        deep = "[" * 100000 + "]" * 100000
        self.assertEqual(app_version.parse_package_info(deep, NUMBER), ("", ""))
        huge = info_text(files={"a": "b" * (app_version.INFO_READ_LIMIT + 1)})
        self.assertEqual(app_version.parse_package_info(huge, NUMBER), ("", ""))

    def test_the_real_json_the_build_tool_writes_is_accepted_for_both_copies(self):
        for variant in ("inner", "outer"):
            with self.subTest(variant=variant):
                raw = ps.make_manifest.render_json(ps.sample_info(variant))
                self.assertEqual(app_version.parse_package_info(raw, NUMBER), (ps.FAKE_COMMIT[:7], app_version.PACKAGE_NOTICE))

    def test_a_signed_bundle_would_not_carry_the_unsigned_notice(self):
        raw = ps.make_manifest.render_json(ps.sample_info("inner", signed=True))
        self.assertEqual(app_version.parse_package_info(raw, NUMBER), (ps.FAKE_COMMIT[:7], ""))

    def test_a_trial_build_adds_the_fixed_trial_sentence_after_the_notice(self):
        commit, notice = app_version.parse_package_info(info_text(trial=True), NUMBER)
        self.assertEqual(commit, COMMIT[:7])
        self.assertEqual(notice, f"{app_version.PACKAGE_NOTICE} · {app_version.PACKAGE_TRIAL_NOTICE}")
        self.assertEqual(app_version.PACKAGE_TRIAL_NOTICE, "시험 빌드 — 개인 PC 로 보내지 않는 빌드예요")

    def test_only_a_real_true_makes_it_a_trial_build(self):
        for name, value in (("false", False), ("text true", "true"), ("one", 1), ("list", [True]), ("text yes", "yes"), ("absent", None)):
            with self.subTest(name=name):
                self.assertEqual(app_version.parse_package_info(info_text(trial=value), NUMBER), (COMMIT[:7], app_version.PACKAGE_NOTICE), name)

    def test_the_trial_sentence_needs_the_unsigned_preview_channel_too_and_never_comes_from_the_file(self):
        self.assertEqual(app_version.parse_package_info(info_text(trial=True, channel="stable"), NUMBER), (COMMIT[:7], ""))
        self.assertEqual(app_version.parse_package_info(info_text(trial=True, signing={"signed": True}), NUMBER), (COMMIT[:7], ""))
        text = info_text(trial=True, notice="다른 글", trial_text="다른 시험 글")
        self.assertNotIn("다른", " ".join(app_version.parse_package_info(text, NUMBER)))

    def test_the_real_json_of_a_trial_build_gets_the_trial_sentence_and_a_normal_build_does_not(self):
        for variant in ("inner", "outer"):
            with self.subTest(variant=variant):
                trial = ps.make_manifest.render_json(ps.sample_info(variant, trial=True))
                normal = ps.make_manifest.render_json(ps.sample_info(variant))
                self.assertIn(app_version.PACKAGE_TRIAL_NOTICE, app_version.parse_package_info(trial, NUMBER)[1])
                self.assertNotIn(app_version.PACKAGE_TRIAL_NOTICE, app_version.parse_package_info(normal, NUMBER)[1])


class ReadVersionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = ps.temp_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ps.write(self.root / "VERSION", NUMBER + "\n")

    def test_without_an_info_file_the_result_is_the_old_two_field_value(self):
        info = app_version.read_version(self.root / "VERSION")
        self.assertEqual(info, VersionInfo("v" + NUMBER, "file"))
        self.assertEqual((info.commit, info.notice, info.known), ("", "", True))

    def test_with_a_good_info_file_beside_the_version_file_the_commit_and_notice_are_added_and_the_text_is_unchanged(self):
        ps.write(self.root / "PACKAGE_INFO.json", info_text())
        info = app_version.read_version(self.root / "VERSION")
        self.assertEqual((info.text, info.source, info.commit, info.notice), ("v" + NUMBER, "file", COMMIT[:7], app_version.PACKAGE_NOTICE))

    def test_a_trial_info_file_beside_the_version_file_adds_the_trial_sentence(self):
        ps.write(self.root / "PACKAGE_INFO.json", info_text(trial=True))
        info = app_version.read_version(self.root / "VERSION")
        self.assertEqual((info.commit, info.notice), (COMMIT[:7], f"{app_version.PACKAGE_NOTICE} · {app_version.PACKAGE_TRIAL_NOTICE}"))

    def test_a_bom_in_front_of_the_info_file_is_fine(self):
        ps.write(self.root / "PACKAGE_INFO.json", (chr(0xFEFF) + info_text()).encode("utf-8"), binary=True)
        self.assertEqual(app_version.read_version(self.root / "VERSION").commit, COMMIT[:7])

    def test_an_info_file_of_another_version_adds_nothing(self):
        ps.write(self.root / "PACKAGE_INFO.json", info_text(version="0.2.0"))
        self.assertEqual(app_version.read_version(self.root / "VERSION"), VersionInfo("v" + NUMBER, "file"))

    def test_an_unreadable_or_oversized_info_file_adds_nothing_and_does_not_raise(self):
        ps.write(self.root / "PACKAGE_INFO.json", b"\xff\xfe\x00 not utf-8 \x80", binary=True)
        self.assertEqual(app_version.read_version(self.root / "VERSION"), VersionInfo("v" + NUMBER, "file"))
        ps.write(self.root / "PACKAGE_INFO.json", " " * (app_version.INFO_READ_LIMIT + 5))
        self.assertEqual(app_version.read_version(self.root / "VERSION"), VersionInfo("v" + NUMBER, "file"))
        (self.root / "PACKAGE_INFO.json").unlink()
        (self.root / "PACKAGE_INFO.json").mkdir()                                       # 파일 자리에 폴더 — 읽기 실패
        self.assertEqual(app_version.read_version(self.root / "VERSION"), VersionInfo("v" + NUMBER, "file"))

    def test_a_missing_or_malformed_version_file_is_still_the_dev_text_whatever_the_info_says(self):
        ps.write(self.root / "VERSION", "banana\n")
        ps.write(self.root / "PACKAGE_INFO.json", info_text())
        info = app_version.read_version(self.root / "VERSION")
        self.assertEqual((info.source, info.commit, info.notice), ("dev", "", ""))
        self.assertFalse(info.known)

    def test_the_injected_reader_reads_both_files_and_garbage_from_it_adds_nothing(self):
        texts = {"VERSION": NUMBER + "\n", "PACKAGE_INFO.json": info_text()}
        info = app_version.read_version(self.root / "VERSION", reader=lambda path: texts[Path(path).name])
        self.assertEqual((info.commit, info.notice), (COMMIT[:7], app_version.PACKAGE_NOTICE))
        same = app_version.read_version(self.root / "VERSION", reader=lambda path: NUMBER + "\n")
        self.assertEqual(same, VersionInfo("v" + NUMBER, "file"))
        def failing(path):
            if Path(path).name == "PACKAGE_INFO.json":
                raise OSError("no")
            return NUMBER + "\n"
        self.assertEqual(app_version.read_version(self.root / "VERSION", reader=failing), VersionInfo("v" + NUMBER, "file"))

    def test_the_repository_itself_has_no_info_file_so_the_dev_screen_is_unchanged(self):
        self.assertFalse((ps.ROOT / "PACKAGE_INFO.json").exists())
        info = app_version.read_version()
        self.assertEqual((info.commit, info.notice, info.source), ("", "", "file"))
        self.assertEqual(app_version.default_path(), ps.ROOT / "VERSION")
        self.assertRegex(info.text, r"^v0\.1\.0-preview\.\d+$")

    def test_version_info_keeps_its_equality_with_the_old_two_field_value_and_is_hashable(self):
        self.assertEqual(VersionInfo("v1", "file"), VersionInfo("v1", "file", "", ""))
        self.assertNotEqual(VersionInfo("v1", "file"), VersionInfo("v1", "file", "abcdefg", ""))
        self.assertEqual(len({VersionInfo("v1", "file"), VersionInfo("v1", "file", "", "")}), 1)


class InfoViewModelTest(unittest.TestCase):
    def test_the_old_shape_is_exactly_label_and_text_when_there_is_no_package_info(self):
        for version in (None, VersionInfo("v1.2.3", "file"), VersionInfo("개발 버전", "dev")):
            with self.subTest(version=version):
                view = sv.info_vm(None, False, None, version)["version"]
                self.assertEqual(set(view), {"label", "text"})
        self.assertEqual(sv.info_vm(None, False, None, VersionInfo("v1.2.3", "file"))["version"], {"label": "버전", "text": "v1.2.3"})
        self.assertEqual(sv.info_vm(None, False, None, None)["version"]["text"], "개발 버전")

    def test_a_package_adds_the_commit_to_the_text_and_the_notice_as_its_own_key(self):
        view = sv.info_vm(None, False, None, VersionInfo("v" + NUMBER, "file", COMMIT[:7], app_version.PACKAGE_NOTICE))["version"]
        self.assertEqual(view["text"], f"v{NUMBER} · 커밋 {COMMIT[:7]}")
        self.assertEqual(view["notice"], "개인 PC 제한 시험용, 미서명 Package")
        self.assertEqual(set(view), {"label", "text", "notice"})

    def test_the_commit_and_the_notice_are_independent(self):
        only_commit = sv.info_vm(None, False, None, VersionInfo("v1", "file", "abcdef0", ""))["version"]
        self.assertEqual((only_commit["text"], "notice" in only_commit), ("v1 · 커밋 abcdef0", False))
        only_notice = sv.info_vm(None, False, None, VersionInfo("v1", "file", "", "알림"))["version"]
        self.assertEqual((only_notice["text"], only_notice["notice"]), ("v1", "알림"))

    def test_the_rest_of_the_info_group_is_unchanged(self):
        view = sv.info_vm(None, True, None, VersionInfo("v1", "file", "abcdef0", "알림"))
        self.assertEqual(set(view), {"key", "title", "open", "chips", "summary", "a11y", "version", "diag"})
        self.assertEqual((view["key"], view["title"], view["open"], view["chips"]), ("info", "정보", True, []))

    def test_the_view_never_contains_more_than_seven_commit_characters(self):
        raw = ps.make_manifest.render_json(ps.sample_info("inner"))
        info = VersionInfo("v" + NUMBER, "file", *app_version.parse_package_info(raw, NUMBER))
        text = json.dumps(sv.info_vm(None, False, None, info), ensure_ascii=False)
        self.assertIn(ps.FAKE_COMMIT[:7], text)
        self.assertNotIn(ps.FAKE_COMMIT[:8], text)
        self.assertNotIn(ps.FAKE_TREE[:7], text)

    def test_the_notice_text_has_no_forbidden_screen_wording(self):
        from chanceblog_desktop.ui.core.text import FORBIDDEN
        for word in FORBIDDEN:
            self.assertNotIn(word, app_version.PACKAGE_NOTICE)
            self.assertNotIn(word, app_version.PACKAGE_TRIAL_NOTICE)
            self.assertNotIn(word, app_version.COMMIT_LABEL)


if __name__ == "__main__":
    unittest.main()
