"""릴리스 노트 규칙(`docs/RELEASE.md` '릴리스 노트 규칙' — DOCS 갈래가 정한 위치와 틀, V1REL12·R-2) 시험 — 가짜 변경 이력으로 `packaging/release_chain.py` 의 노트 부품을 본다.

정해진 것: 정본은 `CHANGELOG.md` 의 `## [X.Y.Z] — YYYY-MM-DD` 절이다(별도 노트 파일을 두지 않는다). 새 절의 머리 줄은 괄호 설명 없이 정확히 이 꼴이고 `### 요약`·`### 자세히`·`### 이관 노트` 가 한 번씩 이 차례로 있다.
요약은 3–10줄·500글자 이하(매니페스트 `notes.summary` 가 그대로 쓴다), 절 전체는 20,000자 이하이며 물결표·웹 주소·이중 중괄호·키 모양이 없다. 릴리스 본문 = 그 절의 본문(글자 그대로) + 고정 안내 꼬리.

지키는 것:
  1) 절 고르기: 마지막 절·중간 절·없는 버전·같은 버전이 둘·후보 이름·옛 모양(괄호 설명)·날짜 없는 머리 줄(`tests/test_v1_docs.py` 의 참고 구현과 같은 결과).
  2) 모양 검사: 버전 불일치·필수 절 삭제·중복·차례·빈 절·요약 줄 수·요약 길이(500)·절 길이(20,000)·금지 표기(물결표·웹 주소·이중 중괄호·키 모양·CR·BOM)·보이지 않는 글자 —
     요약은 앱의 규칙대로 줄바꿈 말고는 모두 거절하고, 절 전체(머리 줄·자세히·이관 노트 포함)는 줄바꿈·탭·이모지 조합용 ZWJ 만 빼고 거절한다(재작업 1·S-6). 머리 줄의 날짜는 ASCII 숫자만.
  3) 요약은 앱이 받아들이는 `notes.summary` 가 된다. 4) 본문은 절과 글자 그대로 같고 한 글자만 바꾸면 달라진다.
네트워크 없이 돈다(가짜 폴더·가짜 글만).
"""
import re
import unittest
from pathlib import Path

import release_tools_support as rts
import update_support as us

from chanceblog_desktop.update import manifest

import release_chain as rc

ROOT = rts.ROOT
TILDE = chr(126)
URL = "ht" + "tp://" + "example.invalid"
BRACES = "{" * 2 + "x" + "}" * 2
GOOGLE_KEY = "AI" + "za" + "A" * 35                                  # 키 모양 — 소스에 완성된 키 글을 적지 않고 조립한다

SAMPLE_CHANGELOG = """# 변경 이력

## [1.0.0-rc.1] — 2026-12-01

### 요약
- 다음 후보.

## [1.0.0] — 2026-12-10

### 요약
- 첫 정식 판.

### 자세히
- 둘째 줄.

## [0.9.0] — 2026-11-30 (옛 모양의 괄호 설명)

- 옛 절이다.

## [0.8.0] 날짜가 없는 머리 줄

- 읽지 않는다.

## [0.7.0] — 2026-10-01

## [0.7.0] — 2026-10-02
"""


def problems_of(text, version="1.0.0"):
    heading, body = rc.notes_section(text, version)
    return rc.notes_problems(heading, body, version)


def codes_of(text, version="1.0.0"):
    return sorted({item.code for item in problems_of(text, version)})


def details_of(text, version="1.0.0"):
    return sorted((item.code, item.detail) for item in problems_of(text, version))


class SectionPickTest(unittest.TestCase):
    """`docs/RELEASE.md` 릴리스 노트 규칙 3 의 1·2 — 머리 줄이 정확히 하나, 다음 `## [` 줄 앞까지, 머리 줄을 뺀 앞뒤 빈 줄 없는 글."""

    def test_the_section_is_picked_by_exact_version_and_ends_at_the_next_section_not_at_a_subheading(self):
        head, body = rc.notes_section(SAMPLE_CHANGELOG, "1.0.0")
        self.assertEqual(head, "## [1.0.0] — 2026-12-10")
        self.assertEqual(body, "### 요약\n- 첫 정식 판.\n\n### 자세히\n- 둘째 줄.")
        self.assertEqual(rc.notes_section(SAMPLE_CHANGELOG, "1.0.0-rc.1")[1], "### 요약\n- 다음 후보.", "후보 이름은 정식과 따로다")
        self.assertEqual(rc.notes_section(SAMPLE_CHANGELOG, "0.9.0")[1], "- 옛 절이다.", "옛 모양(괄호 설명)도 읽는다")
        self.assertEqual(rc.notes_section(SAMPLE_CHANGELOG.replace("\n", "\r\n"), "1.0.0")[0], "## [1.0.0] — 2026-12-10", "줄 끝이 CRLF 여도 같다")

    def test_missing_duplicate_and_dateless_headings_are_refused(self):
        for version in ("9.9.9", "0.8.0", "0.7.0", "1.0", ""):
            with self.subTest(version=version):
                with self.assertRaises(rc.NotesError):
                    rc.notes_section(SAMPLE_CHANGELOG, version)
        self.assertEqual(rc.notes_section("## [1.0.0] — 2026-12-10\n", "1.0.0")[1], "", "내용이 빈 절도 하나로 읽힌다(모양 검사가 따로 거절한다)")

    def test_the_result_equals_the_reference_implementation_of_the_docs_tests_on_every_sample_version(self):
        """같은 규칙을 `tests/test_v1_docs.py` 가 다르게 적은 참고 구현으로 견준다(두 구현이 같은 절을 고른다)."""
        heading = re.compile(r"^## \[([^\]]+)\] — (\d{4}-\d{2}-\d{2})(?: \(.+\))?$")

        def reference(changelog, version):
            lines = changelog.replace("\r\n", "\n").split("\n")
            heads = [index for index, line in enumerate(lines) if heading.match(line) and heading.match(line).group(1) == version]
            if len(heads) != 1:
                raise ValueError("count")
            start = heads[0]
            end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## [")), len(lines))
            return lines[start], "\n".join(lines[start + 1:end]).strip("\n")
        for version in ("1.0.0", "1.0.0-rc.1", "0.9.0", "0.8.0", "0.7.0", "9.9.9"):
            with self.subTest(version=version):
                try:
                    expected = reference(SAMPLE_CHANGELOG, version)
                except ValueError:
                    with self.assertRaises(rc.NotesError):
                        rc.notes_section(SAMPLE_CHANGELOG, version)
                else:
                    self.assertEqual(rc.notes_section(SAMPLE_CHANGELOG, version), expected)

    def test_the_top_version_is_the_first_section_in_the_file(self):
        self.assertEqual(rc.top_changelog_version(SAMPLE_CHANGELOG), "1.0.0-rc.1")
        self.assertEqual(rc.top_changelog_version("# x\n\n- nothing\n"), None)
        self.assertEqual(rc.top_changelog_version(rts.changelog_text("1.2.3")), "1.2.3")

    def test_the_real_changelog_top_section_can_be_read_by_its_version_and_matches_the_version_file(self):
        """실제 변경 이력은 옛 모양이라(괄호 설명) 노트 모양 검사 대상이 아니다 — 맨 위 절이 `VERSION` 과 같고 그 절을 하나로 읽을 수 있다는 것만 본다(겹치는 확인은 `test_repo_layout` 이 한다)."""
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(rc.top_changelog_version(changelog), version)
        heading, body = rc.notes_section(changelog, version)
        self.assertTrue(heading.startswith(f"## [{version}] — "))
        self.assertTrue(body)


class ShapeTest(unittest.TestCase):
    def test_the_standard_note_has_no_problem(self):
        self.assertEqual(problems_of(rts.changelog_text("1.0.0")), [])
        self.assertEqual(problems_of(rts.changelog_text("1.0.0-rc.1"), "1.0.0-rc.1"), [])

    def test_a_heading_that_names_another_version_or_has_a_note_is_refused_and_a_dateless_one_is_not_picked_at_all(self):
        body = rts.notes_section("1.0.0").split("\n", 1)[1].strip("\n")
        for name, heading in {"another version": "## [1.0.1] — 2026-12-10", "parenthesis": "## [1.0.0] — 2026-12-10 (설명)", "no space": "## [1.0.0] —2026-12-10", "single digit month": "## [1.0.0] — 2026-1-10"}.items():
            with self.subTest(name=name):
                self.assertIn(("notes_heading", heading), [(item.code, item.detail) for item in rc.notes_problems(heading, body, "1.0.0")])
        with self.assertRaises(rc.NotesError):
            rc.notes_section(rts.changelog_text("1.0.0", heading="## [1.0.0] 2026-12-10"), "1.0.0")

    def test_each_required_section_missing_is_named(self):
        for section in rc.REQUIRED_SECTIONS:
            with self.subTest(section=section):
                text = rts.changelog_text("1.0.0").replace(section + "\n", "")
                self.assertIn(("notes_section_missing", section), details_of(text))

    def test_a_duplicate_section_and_a_wrong_order_are_refused(self):
        base = rts.changelog_text("1.0.0")
        twice = base.replace("### 자세히\n", "### 자세히\n- 하나.\n\n### 자세히\n", 1)
        self.assertIn(("notes_section_missing", "### 자세히"), details_of(twice))
        swapped = rts.notes_section("1.0.0", summary=("- 가", "- 나", "- 다")).replace("### 요약", "### @@").replace("### 자세히", "### 요약").replace("### @@", "### 자세히")
        self.assertIn("notes_section_order", codes_of("# t\n\n" + swapped))

    def test_an_empty_section_is_refused(self):
        for kwargs, section in (({"details": ("",)}, "### 자세히"), ({"migration": ("  ",)}, "### 이관 노트"), ({"summary": ("",)}, "### 요약")):
            with self.subTest(section=section):
                self.assertIn(("notes_section_empty", section), details_of(rts.changelog_text("1.0.0", **kwargs)))

    def test_the_summary_must_have_three_to_ten_lines(self):
        for count, ok in ((2, False), (3, True), (10, True), (11, False)):
            with self.subTest(lines=count):
                text = rts.changelog_text("1.0.0", summary=tuple(f"- 줄 {number}" for number in range(count)))
                self.assertEqual("summary_lines" in codes_of(text), not ok)
                if not ok:
                    self.assertIn(("summary_lines", str(count)), details_of(text))

    def test_blank_lines_between_summary_bullets_are_not_counted_as_lines(self):
        text = rts.changelog_text("1.0.0", summary=("- 하나", "", "- 둘", "", "- 셋"))
        self.assertEqual(problems_of(text), [])

    def test_the_summary_may_be_500_characters_and_not_501(self):
        for length, ok in ((500, True), (501, False)):
            with self.subTest(length=length):
                lines = ["- " + "가" * 100, "- " + "나" * 100, "- " + "다" * (length - 4 - 2 * 102 - 0)]
                joined = "\n".join(lines)
                self.assertEqual(len(joined), length)
                self.assertEqual("summary_length" in codes_of(rts.changelog_text("1.0.0", summary=tuple(lines))), not ok)

    def test_the_section_may_be_20000_characters_and_not_more(self):
        self.assertEqual(rc.MAX_NOTES_SECTION_CHARS, 20000, "docs/RELEASE.md 릴리스 노트 규칙의 한도 — 손으로 적은 값이다(상수에서 경계를 계산하면 상수를 바꿔도 시험이 따라 바뀐다)")
        base = rts.changelog_text("1.0.0")
        heading, body = rc.notes_section(base, "1.0.0")
        room = 20000 - (len(heading) + len(body) + 2)
        self.assertGreater(room, 100)
        ok_text = base.replace("- 자세한 변화 한 가지.", "- 자세한 변화 한 가지." + "가" * room)
        self.assertEqual(problems_of(ok_text), [], "정확히 한도")
        self.assertIn("notes_length", codes_of(ok_text.replace("가" * room, "가" * (room + 1))))

    def test_forbidden_notation_and_key_shapes_are_refused_anywhere_in_the_section(self):
        cases = {"tilde": TILDE, "url": URL, "braces": BRACES, "key_shape": GOOGLE_KEY, "cr": "\r", "bom": chr(0xFEFF)}
        heading, body = rc.notes_section(rts.changelog_text("1.0.0"), "1.0.0")
        for kind, extra in cases.items():
            for where in ("- 자세한 변화 한 가지.", "- 달라지는 것 없음.", "- 첫 정식 판이에요."):
                with self.subTest(kind=kind, where=where[:6]):
                    self.assertIn(where, body)
                    found = rc.notes_problems(heading, body.replace(where, where + " " + extra, 1), "1.0.0")
                    self.assertIn(("notes_forbidden", kind), [(item.code, item.detail) for item in found])
        self.assertIn(("notes_forbidden", "tilde"), [(item.code, item.detail) for item in rc.notes_problems(heading + " " + TILDE, body, "1.0.0")], "머리 줄도 훑는다")

    def test_a_hidden_character_in_the_summary_is_refused_but_not_in_the_details(self):
        zwj = chr(0x200D)
        text = rts.changelog_text("1.0.0", summary=("- 하나" + zwj + "둘", "- 둘", "- 셋"))
        self.assertIn("summary_chars", codes_of(text))
        details_only = rts.changelog_text("1.0.0", details=("- 자세히" + zwj + "한 줄",))
        self.assertNotIn("summary_chars", codes_of(details_only))

    def test_double_closing_braces_alone_and_double_opening_braces_alone_are_each_forbidden(self):
        """QC06(Q 의 R6) — 시험의 `BRACES` 는 여는 쪽과 닫는 쪽이 함께 있는 글이라 앞 가지가 뒤 가지를 가렸다: 닫는 쪽만 있는 글도 여는 쪽만 있는 글도 따로 거절한다."""
        heading, body = rc.notes_section(rts.changelog_text("1.0.0"), "1.0.0")
        for label, extra in {"closing only": "}" * 2, "opening only": "{" * 2}.items():
            with self.subTest(case=label):
                found = rc.notes_problems(heading, body.replace("- 달라지는 것 없음.", "- 달라지는 것 없음. " + extra, 1), "1.0.0")
                self.assertIn(("notes_forbidden", "braces"), [(item.code, item.detail) for item in found])

    def test_a_www_address_without_a_scheme_is_forbidden(self):
        """QC07(Q 의 R6) — 스킴 없이 `www` 와 점으로 시작하는 주소도 웹 주소다(소스에는 완성된 주소 글을 적지 않고 조립한다)."""
        heading, body = rc.notes_section(rts.changelog_text("1.0.0"), "1.0.0")
        for address in ("www" + chr(46) + "example" + chr(46) + "invalid", "WWW" + chr(46) + "Example" + chr(46) + "invalid"):
            with self.subTest(address=address):
                found = rc.notes_problems(heading, body.replace("- 달라지는 것 없음.", "- 달라지는 것 없음. " + address, 1), "1.0.0")
                self.assertIn(("notes_forbidden", "url"), [(item.code, item.detail) for item in found])

    def test_a_required_heading_with_a_trailing_space_is_still_the_heading(self):
        """QC10(Q 의 R6) — 소제목 줄 끝의 공백은 소제목을 바꾸지 않는다(끝 공백을 못 보면 필수 절이 없는 것으로 오판한다)."""
        base = rts.changelog_text("1.0.0")
        text = base.replace("### 요약\n", "### 요약 \n").replace("### 이관 노트\n", "### 이관 노트\t\n")
        self.assertNotEqual(text, base)
        heading, body = rc.notes_section(text, "1.0.0")
        self.assertEqual(rc.notes_problems(heading, body, "1.0.0"), [])

    def test_a_section_runs_to_the_next_bracketed_heading_only(self):
        """QC11(Q 의 R6) — 절은 다음 `## [` 줄 앞까지다: `## 기타 안내` 같은 다른 이름의 두 단계 제목은 절의 내용이다(아무 `## ` 줄에서 끊으면 뒤의 글이 사라진다)."""
        text = rts.changelog_text("1.0.0").replace("- 달라지는 것 없음.", "- 달라지는 것 없음.\n\n## 기타 안내\n- 덧붙임")
        _heading, body = rc.notes_section(text, "1.0.0")
        self.assertIn("## 기타 안내", body)
        self.assertTrue(body.endswith("- 덧붙임"))

    def test_the_footer_tells_how_to_get_past_the_smartscreen_warning(self):
        """QC27(Q 의 R6) — 설계서 3-6 이 본문에 넣으라고 한 안내의 나머지 문장(경고가 뜰 때 하는 일)도 못박는다."""
        self.assertIn("추가 정보를 누른 뒤 실행을 누르면 시작돼요.", rc.FOOTER)
        self.assertIn(rc.FOOTER, rc.compose_body("본문"))

    def test_dangerous_hidden_characters_are_refused_anywhere_in_the_section_but_newline_tab_and_zwj_are_fine(self):
        """재작업 1(S-6) — 요약뿐 아니라 절 전체(머리 줄·요약·자세히·이관 노트)에서 제어 글자·방향 제어·폭 없는 공백·줄 구분 글자·사용자 영역 글자는 거절한다 —
        공개 릴리스 본문에 보이지 않는 글자가 가는 길을 막는다. 줄바꿈·탭·이모지 조합용 ZWJ 만 절 전체에서 허용한다(요약은 앱의 규칙대로 ZWJ·탭도 거절 — 위 시험)."""
        base = rts.changelog_text("1.0.0")
        heading, body = rc.notes_section(base, "1.0.0")
        refused = {"nul": 0x00, "bell": 0x07, "escape": 0x1B, "delete": 0x7F, "c1 control": 0x85, "line separator": 0x2028, "paragraph separator": 0x2029, "zero width space": 0x200B,
                   "zero width non joiner": 0x200C, "left to right mark": 0x200E, "right to left mark": 0x200F, "embedding": 0x202A, "override": 0x202E, "word joiner": 0x2060,
                   "invisible times": 0x2062, "isolate": 0x2066, "pop isolate": 0x2069, "soft hyphen": 0x00AD, "arabic letter mark": 0x061C, "interlinear anchor": 0xFFF9,
                   "tag character": 0xE0041, "private use": 0xE000, "lone surrogate": 0xD800}
        places = ("- 자세한 변화 한 가지.", "- 달라지는 것 없음.", "- 첫 정식 판이에요.")
        for label, code_point in refused.items():
            for where in places:
                with self.subTest(char=label, where=where[:6]):
                    changed = body.replace(where, where + chr(code_point), 1)
                    self.assertNotEqual(changed, body)
                    self.assertIn(("notes_forbidden", "hidden_char"), [(item.code, item.detail) for item in rc.notes_problems(heading, changed, "1.0.0")])
            with self.subTest(char=label, where="heading"):
                found = rc.notes_problems(heading + chr(code_point), body, "1.0.0")
                self.assertIn(("notes_forbidden", "hidden_char"), [(item.code, item.detail) for item in found])
        for label, allowed in {"tab": "\t", "zero width joiner": chr(0x200D), "emoji with joiner": chr(0x1F468) + chr(0x200D) + chr(0x1F469), "korean": "가나다라", "nbsp": chr(0xA0), "variation selector": chr(0xFE0F)}.items():
            for where in places[:2]:
                with self.subTest(allowed=label, where=where[:6]):
                    changed = body.replace(where, where + allowed, 1)
                    self.assertEqual(rc.notes_problems(heading, changed, "1.0.0"), [], "자세히·이관 노트에서는 허용한다")

    def test_the_summary_keeps_the_apps_stricter_rule_and_a_dangerous_character_there_is_reported_twice(self):
        for char in (chr(0x200D), "\t", chr(0x202E), chr(0x200B)):
            with self.subTest(char=hex(ord(char))):
                found = details_of(rts.changelog_text("1.0.0", summary=("- 하나" + char + "둘", "- 둘", "- 셋")))
                self.assertIn(("summary_chars", ""), found, "요약은 앱의 규칙(ZWJ·탭도 거절)")
        found = details_of(rts.changelog_text("1.0.0", summary=("- 하나" + chr(0x202E) + "둘", "- 둘", "- 셋")))
        self.assertIn(("notes_forbidden", "hidden_char"), found, "방향 제어 글자는 절 전체 검사도 걸린다")

    def test_the_release_body_and_the_manifest_summary_never_carry_a_dangerous_hidden_character(self):
        for char in (chr(0x202E), chr(0x1B), chr(0x200B), chr(0x2028)):
            with self.subTest(char=hex(ord(char))):
                text = rts.changelog_text("1.0.0", details=("- 자세히" + char + "한 줄",))
                with self.assertRaises(rc.ChainError):
                    rc.release_body(text, "1.0.0")

    def test_a_heading_date_must_be_ascii_digits(self):
        """재작업 1(S-6 곁가지) — `\\d` 는 아라비아 인도 숫자 같은 다른 글자 숫자도 받는다 — 새 절의 머리 줄 날짜는 ASCII 숫자만이다."""
        arabic = "".join(chr(0x660 + int(digit)) if digit.isdigit() else digit for digit in "2026-12-10")
        text = rts.changelog_text("1.0.0", date=arabic)
        self.assertIn(("notes_heading", "## [1.0.0] — " + arabic), details_of(text))
        self.assertEqual(problems_of(rts.changelog_text("1.0.0", date="2026-12-10")), [])

    def test_extra_subheadings_inside_a_section_are_content_not_new_sections(self):
        text = rts.changelog_text("1.0.0", details=("### 새 기능", "- 하나", "### 고친 것", "- 둘"))
        self.assertEqual(problems_of(text), [])
        text = rts.changelog_text("1.0.0", details=("### 새 기능",))
        self.assertEqual(problems_of(text), [], "소제목만 있어도 내용으로 센다(비어 있다고 거절하지 않는다)")

    def test_a_note_without_any_of_the_sections_names_all_three(self):
        found = rc.notes_problems("## [1.0.0] — 2026-12-10", "- 그냥 글", "1.0.0")
        self.assertEqual(sorted(item.detail for item in found if item.code == "notes_section_missing"), sorted(rc.REQUIRED_SECTIONS))


class SummaryTest(unittest.TestCase):
    def test_the_summary_is_the_non_blank_lines_of_the_summary_section(self):
        text = rts.changelog_text("1.0.0", summary=("- 하나  ", "", "- 둘", "- 셋"))
        heading, body = rc.notes_section(text, "1.0.0")
        self.assertEqual(rc.summary_of(body), "- 하나\n- 둘\n- 셋")

    def test_a_missing_summary_section_is_an_error(self):
        with self.assertRaises(rc.NotesError):
            rc.summary_of("### 자세히\n- 글")

    def test_the_summary_is_accepted_as_the_notes_of_a_manifest_by_the_app(self):
        text = rts.changelog_text("1.0.0")
        summary = rc.summary_of(rc.notes_section(text, "1.0.0")[1])
        data = us.manifest_dict(notes={"summary": summary})
        found = manifest.validate_fields(data, "0" * 64, channels=manifest.CHANNELS_OFFLINE)
        self.assertEqual(found.summary, summary)

    def test_the_limits_equal_the_apps_limits(self):
        self.assertEqual((rc.MAX_SUMMARY_CHARS, rc.MAX_SUMMARY_LINES), (manifest.MAX_NOTES_CHARS, manifest.MAX_NOTES_LINES))
        self.assertEqual(rc.HIDDEN_CATEGORIES, manifest._HIDDEN_CATEGORIES)


class BodyTest(unittest.TestCase):
    def test_the_body_is_the_section_text_exactly_plus_the_fixed_footer(self):
        text = rts.changelog_text("1.0.0")
        body = rc.release_body(text, "1.0.0")
        notes = rc.notes_section(text, "1.0.0")[1]
        self.assertTrue(body.startswith(notes + "\n\n### 내려받은 파일 확인하기\n"))
        self.assertTrue(body.endswith("\n") and not body.endswith("\n\n"))
        self.assertNotIn("\r", body)
        self.assertEqual(rc.split_body(body), (notes, rc.FOOTER))
        self.assertEqual(body, notes + "\n\n" + rc.FOOTER + "\n")

    def test_the_footer_explains_the_hash_check_and_the_missing_signature_and_has_no_forbidden_notation(self):
        for word in ("SHA256SUMS", "Get-FileHash", "코드 서명이 없어요", "SmartScreen"):
            self.assertIn(word, rc.FOOTER)
        self.assertEqual(rc._forbidden_kind(rc.FOOTER, hidden=True), "")
        self.assertNotIn(TILDE, rc.FOOTER)

    def test_one_changed_character_or_a_changed_footer_makes_the_body_differ(self):
        text = rts.changelog_text("1.0.0")
        body = rc.release_body(text, "1.0.0")
        self.assertTrue(rc.body_matches_changelog(body, text, "1.0.0"))
        for needle, other in (("첫 정식 판이에요.", "첫 정식 판이에요!"), ("내려받은 파일 확인하기", "내려받은 파일 확인하기 "), ("SHA256SUMS", "SHA256SUM")):
            with self.subTest(needle=needle):
                self.assertFalse(rc.body_matches_changelog(body.replace(needle, other, 1), text, "1.0.0"))
        self.assertFalse(rc.body_matches_changelog(body + "\n", text, "1.0.0"))
        self.assertFalse(rc.body_matches_changelog("", text, "1.0.0"))
        self.assertFalse(rc.body_matches_changelog(body, text, "9.9.9"))
        self.assertFalse(rc.body_matches_changelog(body, text.replace("백업이 더 안전해졌어요.", "백업이 더 안전해졌어요 "), "1.0.0"))

    def test_a_note_that_fails_the_shape_check_makes_no_body(self):
        text = rts.changelog_text("1.0.0", summary=("- 하나",))
        with self.assertRaises(rc.ChainError) as raised:
            rc.release_body(text, "1.0.0")
        self.assertEqual([item.code for item in raised.exception.problems], ["summary_lines"])
        with self.assertRaises(rc.NotesError):
            rc.release_body(rts.changelog_text("1.0.0"), "2.0.0")

    def test_split_refuses_text_without_the_exact_footer(self):
        for text in ("그냥 글\n", "", rc.FOOTER, "x\n\n" + rc.FOOTER, None):
            with self.subTest(text=repr(text)[:10]):
                with self.assertRaises(rc.NotesError):
                    rc.split_body(text)


class NoteFilesTest(unittest.TestCase):
    """가짜 변경 이력 파일을 폴더에 두고 명령줄(`notes`)로 본문 파일을 만든다."""

    def test_the_notes_command_writes_the_body_file_as_lf_utf8_without_bom(self):
        with rts.temp_dir() as folder:
            folder = Path(folder)
            (folder / "VERSION").write_text("1.0.0\n", encoding="utf-8", newline="\n")
            (folder / "CHANGELOG.md").write_bytes(rts.changelog_text("1.0.0").encode("utf-8"))
            code, out, err = rts.Capture(rc.main)(["notes", "--version-file", str(folder / "VERSION"), "--changelog", str(folder / "CHANGELOG.md"), "--out", str(folder / "body.md")])
            data = (folder / "body.md").read_bytes()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(data.decode("utf-8"), rc.release_body(rts.changelog_text("1.0.0"), "1.0.0"))
        self.assertFalse(data.startswith(b"\xef\xbb\xbf") or b"\r" in data)
        self.assertIn("제목 ChanceBlog Desktop 1.0.0", out)

    def test_a_bad_note_writes_no_file_and_exits_with_the_problem_exit_code(self):
        with rts.temp_dir() as folder:
            folder = Path(folder)
            (folder / "VERSION").write_text("1.0.0\n", encoding="utf-8", newline="\n")
            (folder / "CHANGELOG.md").write_bytes(rts.changelog_text("1.0.0", summary=("- 하나",)).encode("utf-8"))
            code, out, err = rts.Capture(rc.main)(["notes", "--version-file", str(folder / "VERSION"), "--changelog", str(folder / "CHANGELOG.md"), "--out", str(folder / "body.md")])
            self.assertFalse((folder / "body.md").exists())
        self.assertEqual((code, out), (1, ""))
        self.assertIn("문제: summary_lines — 1", err)

    def test_a_missing_section_or_missing_files_write_no_file(self):
        with rts.temp_dir() as folder:
            folder = Path(folder)
            (folder / "VERSION").write_text("2.0.0\n", encoding="utf-8", newline="\n")
            (folder / "CHANGELOG.md").write_bytes(rts.changelog_text("1.0.0").encode("utf-8"))
            code, _out, err = rts.Capture(rc.main)(["notes", "--version-file", str(folder / "VERSION"), "--changelog", str(folder / "CHANGELOG.md"), "--out", str(folder / "body.md")])
            self.assertEqual(code, 1)
            self.assertIn("정확히 하나 찾지 못했다", err)
            code, _out, err = rts.Capture(rc.main)(["notes", "--version-file", str(folder / "none"), "--changelog", str(folder / "CHANGELOG.md"), "--out", str(folder / "body.md")])
            self.assertEqual(code, 2)
            self.assertFalse((folder / "body.md").exists())


if __name__ == "__main__":
    unittest.main()
