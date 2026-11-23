"""AS2-B 묶음(결정 D-605에서 D-619)의 작은 것들과 문서 사실을 지키는 시험 — 백업 설정 경로 안내 한 줄·`--noupx`·'업데이트 경로 없음' 두 줄·결정 행·SECURITY.md 새 절·CHANGELOG(AS-S1 참고-11·20·21).

지키는 것:
  1) `INCLUDED_PATH_NOTE` — 백업의 설정 파일에 연결한 폴더의 전체 경로가 들어간다는 안내 한 줄. '담지 않는 것' 목록(`EXCLUDED`)·백업 목록의 칸은 그대로다(그 모양은 다른 시험이 못박는다).
  2) `pyinstaller_args` 가 `--noupx` 를 명시한다 — UPX 는 PATH 에 있을 때만 쓰이던 것(결정적 빌드). 동작은 UPX 를 쓰지 않는 쪽뿐이다.
  3) `docs/SECURITY.md` §1 과 §3 에 '이 시험 버전에는 업데이트 경로가 없다(미구현 설계)' 가 한 번씩 덧붙었고 **기존 줄은 한 글자도 안 바뀌었다**. 새 절은 파일 끝에 하나뿐이다.
  4) 결정 행 D-605에서 D-619 가 번호 순서대로 한 줄씩(앞 묶음의 D-594 행 바로 뒤에 빈 줄 없이) 있고, 새 글에 ASCII 물결표·http 링크가 없다. CHANGELOG 에 한 줄이 있다.
"""
import re
import sys
import unittest
from pathlib import Path

import packaging_support as ps

from chanceblog_desktop.security import backup_note

ROOT = ps.ROOT
bp = ps.build_package
NEW_HEADING = "## 백업·복원·키·시험 훑기 감사(AS-S1) 필수·권고 처리 — 허용 목록·되돌리기·링크·WAL (D-605에서 D-619, 2026-11-23)"
UPDATE_SENTENCE = "이 시험 버전에는 업데이트 경로가 없다"
# 이 묶음 앞의 SECURITY.md §1 다섯째 표 줄과 §3 본문 — 바뀌지 않았다.
OLD_SECTION1_ROW = "| 업데이트 서명 개인키 | GitHub Environment 시크릿 `UPDATE_SIGNING_KEY` + 운영자의 오프라인 백업 2곳 | 없음(공개키는 앱에 내장·저장소에 있음) |"
OLD_SECTION3_TEXT = "[`RELEASE.md`](RELEASE.md) 의 서명 매니페스트·해시 검증·다운그레이드 거부·불변 릴리스·백업/롤백이 핵심이다. 업데이트 경로는 HTTPS 와 고정 저장소 주소만 쓰고, 서명이 없거나 어긋나면 업데이트를 거부한다."


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class IncludedPathNoteTest(unittest.TestCase):
    def test_the_note_tells_that_the_settings_file_holds_the_connected_folder_path_and_that_it_is_personal_not_secret(self):
        note = backup_note.INCLUDED_PATH_NOTE
        for word in ("settings.json", "연결한", "전체 경로", "사용자 이름", "비밀은 아니지만"):
            self.assertIn(word, note)
        self.assertNotIn(chr(126), note)
        self.assertNotRegex(note, r"(?i)https?://")
        self.assertIn("INCLUDED_PATH_NOTE", backup_note.__all__)

    def test_the_excluded_list_and_the_manifest_shape_did_not_change(self):
        names = [name for name, _ in backup_note.EXCLUDED]
        self.assertEqual(names, ["키·토큰·쿠키·세션·자격 증명", "connections.json", "quota_state.json", "publish/", "locks/", "backups/", "logs/", "임시·복구용 사본", "외부에서 가져온 원본 자료"])
        self.assertNotIn(backup_note.INCLUDED_PATH_NOTE, [reason for _name, reason in backup_note.EXCLUDED])
        from chanceblog_desktop.service import backup_flow
        self.assertEqual(backup_flow.MANIFEST_KEYS, frozenset({"schema", "kind", "app_version", "created_at", "status", "credential_excluded", "credential_excluded_note", "secret_scan", "files", "missing", "skipped", "excluded"}))
        self.assertEqual(backup_flow.CREDENTIAL_NOTE, backup_note.CREDENTIAL_NOTE)


class NoUpxTest(unittest.TestCase):
    def args(self):
        return bp.pyinstaller_args(Path("R"), Path("O"), Path("O/v.txt"), ("json",))

    def test_upx_is_never_used_and_the_flag_says_so(self):
        args = self.args()
        self.assertIn("--noupx", args)
        self.assertEqual(args.count("--noupx"), 1)
        self.assertLess(args.index("--noupx"), args.index("--name"), "옵션은 시작 파일(맨 끝) 앞에 있다")
        self.assertEqual(args[-1], str(Path("R") / "packaging" / "gui_entry.py"))
        for flag in ("--upx-dir", "--upx-exclude"):
            self.assertNotIn(flag, args)

    def test_the_recorded_command_shows_it_and_the_other_checked_flags_are_unchanged(self):
        shown = bp.recorded_command(self.args(), Path("R"), Path("O"))
        self.assertIn("--noupx", shown)
        for flag in ("--noconfirm", "--clean", "--onedir", "--windowed"):
            self.assertIn(flag, shown)
        for flag in ("--onefile", "--uac-admin", "--console"):
            self.assertNotIn(flag, shown)


class SecurityDocTest(unittest.TestCase):
    def setUp(self):
        self.text = read("docs/SECURITY.md")

    def test_the_two_old_lines_are_unchanged_and_each_got_one_new_line_about_the_missing_update_path(self):
        self.assertEqual(self.text.count(OLD_SECTION1_ROW), 1, "§1 다섯째 표 줄은 한 글자도 안 바뀌었다")
        self.assertEqual(self.text.count(OLD_SECTION3_TEXT), 1, "§3 본문은 한 글자도 안 바뀌었다")
        lines = [line for line in self.text.splitlines() if UPDATE_SENTENCE in line]
        self.assertEqual(len([line for line in lines if line.startswith("- ")]), 1, "§1 의 덧붙인 글머리표")
        self.assertEqual(len([line for line in lines if line.startswith("**" + UPDATE_SENTENCE)]), 1, "§3 의 덧붙인 문단")
        for line in lines:
            self.assertIn("미구현 설계", line)
            self.assertIn("D-614", line)

    def test_the_new_lines_sit_in_the_right_sections(self):
        section1 = self.text[self.text.index("## 1. 키와 비밀"):self.text.index("## 2. 로그")]
        section3 = self.text[self.text.index("## 3. 업데이트 보안"):self.text.index("## 4. 공급망")]
        self.assertEqual(section1.count(UPDATE_SENTENCE), 1)
        self.assertEqual(section3.count(UPDATE_SENTENCE), 1)
        self.assertLess(section1.index(OLD_SECTION1_ROW), section1.index(UPDATE_SENTENCE), "표 줄 뒤에 덧붙였다")
        self.assertLess(section3.index("서명이 없거나 어긋나면 업데이트를 거부한다."), section3.index(UPDATE_SENTENCE))

    def section_text(self):
        """이 묶음의 새 절 하나만(뒤에 다른 갈래의 절이 덧붙어도 그 앞까지만)."""
        section = self.text[self.text.index(NEW_HEADING):]
        following = section.find("\n## ", len(NEW_HEADING))
        return section if following < 0 else section[:following]

    def test_the_new_section_exists_exactly_once_after_the_old_ones(self):
        self.assertEqual(self.text.count(NEW_HEADING), 1)
        headings = [line for line in self.text.splitlines() if line.startswith("## ")]
        self.assertGreater(headings.index(NEW_HEADING), headings.index("## 3. 업데이트 보안"), "새 절은 기존 절 뒤에 덧붙었다")
        section = self.section_text()
        for word in ("정정", "_plain_local_shape", "restore_from", "`_is_link`", "WAL", "Win32CredApi.exists", "client_id", "ctypes", "vendor/", "RecursionError", "D-605", "D-615", "D-616", "D-617", "D-618", "D-619", "_opened_text", "journal_mode=DELETE", "HONEST_LIMITS", "정직한 코드의 회귀 그물"):
            self.assertIn(word, section, word)

    def test_the_limit_eight_supplement_is_a_new_line_after_the_old_limits_paragraph(self):
        lines = self.text.splitlines()
        old = next(number for number, line in enumerate(lines) if line.startswith("**한계(사실대로)**: ① **이름 표지가 없는 값**"))
        self.assertEqual(lines[old + 1], "")
        self.assertTrue(lines[old + 2].startswith("**한계 ⑧ 보충(AS-S1 참고-9, D-612):**"))
        self.assertIn("값도 가려지지 않은 채", lines[old + 2])
        self.assertIn("이름이 먼저 나간다", lines[old], "기존 줄은 그대로다")

    def test_the_new_text_has_no_ascii_tilde_no_link_and_nothing_unfinished(self):
        section = self.section_text()
        extra ="\n".join(line for line in self.text.splitlines() if UPDATE_SENTENCE in line or line.startswith("**한계 ⑧ 보충"))
        for text in (section, extra):
            self.assertNotIn(chr(126), text)
            self.assertNotRegex(text, r"(?i)(https?|ftp)://|www[.]")
            for unfinished in ("@@", "TODO", "XXX", "{{", "}}", "미정", "채울"):
                self.assertNotIn(unfinished, text)


class SecondRoundDocsTest(unittest.TestCase):
    """2차(안전 검증 S·시험 렌즈 Q 지적, D-616에서 D-619) — 문서가 고친 것과 하지 않은 것을 사실대로 적는다."""

    def setUp(self):
        self.text = read("docs/SECURITY.md")
        self.section = self.text[self.text.index(NEW_HEADING):]
        following = self.section.find("\n## ", len(NEW_HEADING))
        self.section = self.section if following < 0 else self.section[:following]

    def test_each_second_round_fix_is_marked_in_the_section_with_its_limit(self):
        for marker in ("**2차(D-616):**", "**2차(D-617):**", "**2차(D-618): 폴더 자신과 그 바로 아래 항목까지**", "**2차(D-619)**"):
            with self.subTest(marker=marker):
                self.assertEqual(self.section.count(marker), 1)
        self.assertIn("`Context.repo_path`", self.section, "사용자가 정한 경로에는 가드를 걸지 않았다는 한계")
        self.assertIn("그 위(데이터 폴더·`backups` 의 윗 폴더)가 링크인 경우는 같은 사용자의 선택이라 따라간다", self.section)
        self.assertIn("링크인 폴더에 새 사본을 쓰는 쪽(백업 만들기)은 막지 않는다", self.section)
        self.assertIn("이 수정 전에 만든 사본이 WAL 머리면 앱 밖 도구로 열어야 한다", self.section)

    def test_the_source_scan_is_called_a_regression_net_for_honest_code_in_both_places_and_its_limits_are_kept(self):
        self.assertGreaterEqual(self.text.count("정직한 코드의 회귀 그물"), 2, "L135 의 한계 줄과 새 절 둘 다")
        self.assertIn("**의도적** 우회는 막지 못하고", self.text, "옛 한계(D-359)는 그대로 남는다")
        for limit in ("timeit", "cProfile", "pdb", "operator.attrgetter", "compile", "module_from_spec", "ATTACH"):
            with self.subTest(limit=limit):
                self.assertIn(limit, self.section)

    def test_the_carried_over_second_round_notes_are_listed_as_limits(self):
        for note in ("`same_database` 는 두 보관함의 판이 다르면 표마다 행 수만 견준다", "`.restoring` 을 O_EXCL 로 만들지 않는다", "name surrogate", "`INCLUDED_PATH_NOTE`", "한계 ⑦ 과 같은 부류"):
            with self.subTest(note=note):
                self.assertIn(note, self.section)


class DecisionRowsTest(unittest.TestCase):
    def rows(self):
        lines = read("docs/DECISIONS.md").splitlines()
        return lines, [number for number, line in enumerate(lines) if re.match(r"\| D-6(0[5-9]|1[0-9]) \|", line)]

    def test_rows_605_to_619_are_in_order_on_one_line_each_right_after_the_previous_rows(self):
        lines, found = self.rows()
        self.assertEqual(len(found), 15)
        self.assertEqual(found, list(range(found[0], found[0] + 15)), "빈 줄 없이 이어 붙인다")
        for offset, number in enumerate(found):
            self.assertTrue(lines[number].startswith(f"| D-{605 + offset} | 2026-11-23 | **"), lines[number][:30])
            self.assertEqual(lines[number].count(" | "), 3, "번호 · 날짜 · 결정 · 상태 — 네 칸")
            self.assertTrue(lines[number].rstrip().endswith("|"))
        self.assertTrue(lines[found[0] - 1].startswith("| D-594 |") or re.match(r"\| D-(59[5-9]|60[0-4]) \|", lines[found[0] - 1]), "앞 묶음의 행 바로 뒤에 이어진다")

    def test_each_row_names_its_audit_item_and_the_new_text_has_no_tilde_or_link(self):
        lines, found = self.rows()
        text = "\n".join(lines[number] for number in found)
        self.assertIn("AS-S1", text)
        self.assertIn("이월", text)
        for kind, numbers in (("필수", (3, 4)), ("권고", (1, 2, 3, 6)), ("참고", (1, 2, 3, 7, 8, 9, 11, 18, 20, 21))):
            for number in numbers:
                with self.subTest(item=f"{kind}-{number}"):
                    self.assertRegex(text, kind + r"-(?:[0-9]+·)*" + str(number) + r"(?![0-9])")
        for needle in ("안전 검증 S 필수-1", "S 권고-1", "S 권고-2", "S 권고-3", "시험 렌즈 Q 필수-2·3·4·권고-1·참고-2·3·4", "Q 필수-2", "Q 필수-3", "Q 필수-4", "Q 참고"):
            with self.subTest(item=needle):
                self.assertIn(needle, text)
        self.assertNotIn(chr(126), text)
        self.assertNotRegex(text, r"(?i)(https?|ftp)://|www[.]")

    def test_changelog_has_the_one_line(self):
        lines = [line for line in read("CHANGELOG.md").splitlines() if "D-605 에서 D-619" in line]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("- 백업·복원·키·시험 훑기 독립 감사(AS-S1)"))
        self.assertNotIn(chr(126), lines[0])
        self.assertNotRegex(lines[0], r"(?i)https?://")


if __name__ == "__main__":
    unittest.main()
