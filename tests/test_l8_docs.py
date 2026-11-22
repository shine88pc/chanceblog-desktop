"""L8 묶음(조작한 백업의 구조 검사 · 올리기 직전 관문의 비밀 모양 목록)의 문서 시험 — `docs/SECURITY.md` 의 새 절·`docs/DECISIONS.md` 의 D-554–D-558·`CHANGELOG.md` 의 마지막 항목이 코드와 어긋나지 않게 못박는다.

지키는 것:
  1) 결정 기록 D-554–D-558 이 번호마다 정확히 한 줄이고(표의 한 행은 칸이 다섯 개의 `|`) 번호 순서이며, 앞 줄이 표의 행이라 표가 끊기지 않고, 행마다 있어야 하는 낱말을 가졌다. 물결표·웹 주소·채우지 않은 자리표시자가 없다.
  2) 보안 문서의 새 절이 코드의 사실과 같다 — 구조 검사의 고정 이름 열이 모두 적혀 있고, 새 모양 표의 이름이 `_RECENT_PATTERNS` 와 정확히 같으며(모양 하나를 더하거나 빼면 문서도 고쳐야 한다), 거절 이유 문구·지시서의 예가 이미 막혀 있었다는 사실과 한계가 적혀 있다.
  3) 가림 규칙의 '알려 둔 한계' 목록(`UI_DESIGN_SPEC.md` 9절·`D-32` (o))이 L8 이 닫은 네 모양을 더는 한계로 적지 않는다(시험 `test_ui_core` 가 코드와 맞는지 따로 본다).
  4) 변경 이력의 마지막 항목이 이 묶음을 알린다.
  5) 한 번 잰 탐침의 숫자(모양 서른세 가지 중 옛 코드가 막은 수와 고친 코드가 막은 수)가 보안 문서·결정 D-556·D-558·변경 이력 네 곳에서 같다.
네트워크·실제 비밀 없이 돈다.
"""
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from chanceblog_desktop.content import schema_guard  # noqa: E402
from chanceblog_desktop.security import mask  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402

ROOT = HERE.parent
NUMBERS = ("D-554", "D-555", "D-556", "D-557", "D-558")
HEADING = "## 조작된 백업의 구조 검사와 올리기 직전 관문의 비밀 모양 목록(L8 — 설계 D-554–D-558)"
# 행마다 있어야 하는 말 — 그 행이 말해야 하는 사실의 낱말
REQUIRED = {
    "D-554": ("content/schema_guard.py", "트리거", "뷰", "Store.restore_from", "EngineFile.restore_from", "FULL_BACKUP_INVALID", "structure", "고정 이름 열", "복원 전체", "SCHEMA_STATEMENTS", "SECURITY.md", "탐침"),
    "D-555": ("새 시험", "변이", "바뀐 기존 시험", "test_topicdb_rules", "고치기 전 코드", "숫자"),
    "D-556": ("secret_labels", "check_post", "has_key_shape_anywhere", "vendor/", "7개", "33개", "github_pat_", "ghs_", "gho_", "텔레그램", "AIza", "xox", "개인 키 머리말", "M067"),
    "D-557": ("_RECENT_PATTERNS", "열여덟", "UI_DESIGN_SPEC.md", "D-32", "ASIA", "sk_live_", "glpat-", "xapp-", "test_ui_core", "CANARY"),
    "D-558": ("새 시험", "변이", "오탐", "실제 글", "64편", "바뀐 기존 시험", "test_ui_core", "숫자"),
}


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def own_section(text):
    """보안 문서에서 이 묶음의 절만 — 뒤에 다른 갈래의 절이 덧붙어도 같다(병합 순서에 약하지 않게, 독립 검증 Q 의 QP-5)."""
    rest = text[text.index(HEADING):]
    return rest.split("\n## ", 1)[0]


ENTRY_MARK = "(자체 개선 L8 — "                                                       # 이 묶음의 변경 이력 줄이 여는 말 — 다른 갈래(이 묶음의 후속 `L8b` 포함)의 줄은 이렇게 열지 않는다


def changelog_entry(text=None):
    """변경 이력에서 이 묶음의 항목('(자체 개선 L8 — ' 로 열리는 줄) — 맨 끝 줄이어야 하는 것이 아니고, 뒤에 덧붙은 다른 갈래의 줄이 D-554 나 L8 을 되풀이해 말해도(예: 이 묶음의 후속) 헷갈리지 않는다.
    정확히 하나여야 한다. `text` 를 주면 그 글에서 찾는다(찾는 방법 자체를 시험하려고 — `FindersStayStableTest`)."""
    lines = (read("CHANGELOG.md") if text is None else text).splitlines()
    found = [line for line in lines if line.startswith("- ") and ENTRY_MARK in line and "D-554" in line]
    if len(found) != 1:
        raise AssertionError(f"변경 이력에 이 묶음의 항목이 정확히 하나여야 한다: {len(found)}")
    return found[0]


def decision_lines():
    return read("docs/DECISIONS.md").splitlines()


def row_of(number):
    found = [(index, line) for index, line in enumerate(decision_lines()) if line.startswith(f"| {number} |")]
    return found


class DecisionRowsTest(unittest.TestCase):
    def test_every_row_exists_exactly_once_in_number_order(self):
        positions = []
        for number in NUMBERS:
            with self.subTest(number=number):
                found = row_of(number)
                self.assertEqual(len(found), 1, f"{number} 행은 정확히 한 줄이어야 한다")
                positions.append(found[0][0])
        self.assertEqual(positions, sorted(positions), "번호 순서")

    def test_each_row_is_a_proper_table_row_directly_after_another_table_row(self):
        lines = decision_lines()
        for number in NUMBERS:
            index, line = row_of(number)[0]
            with self.subTest(number=number):
                self.assertEqual(line.count("|"), 5, "표의 한 행은 `|` 다섯 개(번호·날짜·결정·상태 네 칸)")
                self.assertRegex(line, rf"^\| {number} \| 2026-11-22 \| \*\*")
                self.assertTrue(line.rstrip().endswith("|"))
                self.assertGreater(index, 0)
                self.assertTrue(lines[index - 1].startswith("| "), "앞 줄이 표의 행이라 표가 끊기지 않는다")

    def test_each_row_has_the_words_it_must_say_and_nothing_unfinished(self):
        for number in NUMBERS:
            line = row_of(number)[0][1]
            with self.subTest(number=number):
                for word in REQUIRED[number]:
                    self.assertIn(word, line)
                self.assertNotIn(chr(126), line)
                self.assertNotIn("http" + "://", line)
                self.assertNotIn("http" + "s://", line)
                for unfinished in ("@@", "TODO", "XXX", "{{", "}}", "미정", "채울", "집계 대기"):
                    self.assertNotIn(unfinished, line)
                self.assertTrue(line.rstrip().endswith("로컬 WIP). |"), "상태 칸 — 구현·시험 완료(…, 변경 등급 T2, 로컬 WIP)")

    def test_the_numbers_stay_inside_this_lanes_range(self):
        text = read("docs/SECURITY.md")
        section = own_section(text)
        for found in set(re.findall(r"D-5\d\d", section)):
            self.assertIn(found, NUMBERS, "이 갈래의 결정 번호 밖은 쓰지 않는다")
        for path in (ROOT / "src").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "L8" in source:
                for found in set(re.findall(r"D-55\d", source)):
                    self.assertIn(found, NUMBERS, path.name)


class SecuritySectionTest(unittest.TestCase):
    def section(self):
        text = read("docs/SECURITY.md")
        self.assertEqual(text.count(HEADING), 1)
        return own_section(text)

    def test_the_section_exists_once_and_has_both_halves(self):
        section = self.section()
        self.assertTrue(section.startswith(HEADING))
        self.assertNotIn("\n## ", section, "이 묶음의 절 하나뿐이다(다른 갈래의 절이 뒤에 덧붙어도 이 절만 본다)")
        self.assertIn("### 백업을 되돌릴 때 보관함의 구조를 본다(F074 — D-554·D-555)", section)
        self.assertIn("### 올리기 직전 관문이 앱의 모든 비밀 모양 목록을 끝까지 본다(F069 — D-556·D-557·D-558)", section)

    def test_every_fixed_kind_name_of_the_structure_check_is_written(self):
        section = self.section()
        self.assertEqual(len(schema_guard.KIND_TEXT), 10, "문서가 '열 가지' 라고 적었다")
        for kind, words in schema_guard.KIND_TEXT.items():
            with self.subTest(kind=kind):
                self.assertIn(words, section)
        self.assertIn("열 가지", section)

    def test_the_refusal_sentence_and_the_three_restore_roads_are_written(self):
        section = self.section()
        self.assertIn(bf.INVALID_REASONS["structure"], section)
        for road in ("service/backup_flow.py", "Store.restore_from", "topicdb/backup.read_backup", "EngineFile.restore_from"):
            self.assertIn(road, section)
        for limit in ("`CHECK`", "행의 값", "앱 밖의 도구", "안전 사본", "백업을 **만드는** 쪽"):
            self.assertIn(limit, section)

    def test_the_new_shape_table_has_exactly_the_names_in_the_code(self):
        section = self.section()
        table = section[section.index("| 이름 | 접두어와 꼬리 |"):]
        names = re.findall(r"(?m)^\| ([^|`]+?) \| ", table.split("\n\n", 1)[0])
        names = [name for name in names if name not in ("이름", "---")]
        self.assertEqual(sorted(names), sorted(label for label, _pattern, _need in mask._RECENT_PATTERNS))
        self.assertEqual(len(names), 18)

    def test_the_section_says_the_briefs_examples_were_already_blocked_and_the_limits(self):
        section = self.section()
        for word in ("github_pat_", "ghs_", "gho_", "텔레그램", "AIza", "xox", "개인 키 머리말", "이미 막는", "되풀이해 더하지 않았다", "7개", "33개", "64편", "오탐", "한계(사실대로)"):
            with self.subTest(word=word):
                self.assertIn(word, section)

    def test_the_probe_numbers_agree_in_every_place_that_states_them(self):
        """모양 서른세 가지를 진짜 `check_post` 에 넣어 본 탐침의 숫자(옛 코드가 막은 수·고친 코드가 막은 수)는 네 곳에 적혀 있다 —
        보안 문서·결정 D-556·결정 D-558·변경 이력. 한 곳만 고치면 어긋나므로 모두 같은 값인지 본다."""
        sentence = r"옛 코드는 (?:지시서의 예 )?(\d+)개만 막았고(?:\(나머지 (\d+)개는 통과\))? 고친 코드는 (\d+)개를 모두 막았다"
        places = {"보안 문서": self.section(), "D-556": row_of("D-556")[0][1], "D-558": row_of("D-558")[0][1]}
        old_values, total_values = set(), set()
        for name, text in places.items():
            with self.subTest(place=name):
                found = re.findall(sentence, text)
                self.assertEqual(len(found), 1, f"{name}: 탐침 문장은 정확히 하나")
                old, missed, total = found[0]
                old_values.add(int(old))
                total_values.add(int(total))
                if missed:
                    self.assertEqual(int(old) + int(missed), int(total), f"{name}: 막은 수 + 통과한 수 = 넣어 본 수")
        last = changelog_entry()
        found = re.findall(r"모양 (\d+)개 중 옛 (\d+)개 → (\d+)개", last)
        self.assertEqual(len(found), 1, "변경 이력의 탐침 문장은 정확히 하나")
        total, old, fixed = (int(number) for number in found[0])
        old_values.add(old)
        total_values.update((total, fixed))
        self.assertEqual(len(old_values), 1, f"옛 코드가 막은 수가 곳마다 다르다: {sorted(old_values)}")
        self.assertEqual(len(total_values), 1, f"넣어 본 모양의 수가 곳마다 다르다: {sorted(total_values)}")
        self.assertLess(min(old_values), min(total_values))

    def test_the_section_has_no_tilde_no_link_and_no_complete_key(self):
        section = self.section()
        self.assertNotIn(chr(126), section)
        self.assertNotIn("http" + "://", section)
        self.assertNotIn("http" + "s://", section)
        self.assertEqual([label for label, pattern, _need in mask._RECENT_PATTERNS if pattern.search(section)], [])


class LimitListTest(unittest.TestCase):
    def test_the_documented_limit_list_no_longer_lists_the_four_shapes_the_mask_now_knows(self):
        spec = read("docs/UI_DESIGN_SPEC.md")
        start = spec.index("**가리기 규칙의 한계**")
        bullet = spec[start:spec.index("\n", start)]
        head, _, rest = bullet.partition("가려지는 것은 규칙이 아는 모양")
        for word in ("ASIA", "sk_live_", "glpat-", "xapp-"):
            self.assertNotIn(word, head, f"{word}: 이제 가려지므로 한계 목록에 없다")
            self.assertIn(word, rest, f"{word}: 가려지는 것으로 적혀 있다")
        for word in ("16진", "영숫자", "base64", "접두어"):
            self.assertIn(word, head)
        self.assertIn("L8 묶음", rest)
        decision = next(line for line in decision_lines() if line.startswith("| D-32 |"))
        self.assertIn("L8 묶음", decision)


class FindersStayStableTest(unittest.TestCase):
    """독립 검증 Q 의 QP-5 — 이 시험이 문서에서 '이 묶음의 것' 을 찾는 방법은 다른 갈래가 문서 끝에 덧붙여도(또는 앞에 끼워 넣어도) 흔들리지 않는다. 옛 시험은 '마지막 줄' 을 찾아 L4 가 뒤에 병합되면 빨개졌고,
    그 뒤 고친 '결정 번호와 L8 이 든 줄' 은 이 묶음의 후속이 D-554 와 L8 을 되풀이해 말하면 줄이 둘로 보여 빨개질 수 있었다 — 이제 이 묶음이 여는 말로 찾는다. 이 시험은 **찾는 방법**을 만든 글로 본다(진짜 문서는 건드리지 않는다)."""

    LATER = ("- 다른 갈래의 항목(L5 — 결정 D-549)", "- 이 묶음의 후속(자체 개선 L8b — 결정 D-570, 앞 묶음 L8 의 D-554 를 이어받음)", "- L8 과 D-554 만 적은 줄", "- (자체 개선 L8b — 결정 D-554 도 말하는 줄)",
             "- 자체 개선 L8 이라고만 적고 닫는 말이 없는 줄 D-554")

    def test_lines_appended_after_or_inserted_before_the_entry_never_change_which_line_is_found(self):
        base = read("CHANGELOG.md")
        found = changelog_entry(base)
        self.assertIn(ENTRY_MARK, found)
        self.assertEqual(changelog_entry(base.rstrip("\n") + "\n" + "\n".join(self.LATER) + "\n"), found, "뒤에 덧붙인 줄")
        self.assertEqual(changelog_entry("\n".join(self.LATER) + "\n" + base), found, "앞에 끼워 넣은 줄")
        for line in self.LATER:
            with self.subTest(line=line[:30]):
                self.assertEqual(changelog_entry(base + line + "\n"), found)

    def test_a_second_entry_of_this_work_or_a_missing_one_is_an_error(self):
        base = read("CHANGELOG.md")
        found = changelog_entry(base)
        with self.assertRaises(AssertionError):
            changelog_entry(base.rstrip("\n") + "\n" + found + "\n")
        with self.assertRaises(AssertionError):
            changelog_entry("- 아무 항목\n" + "\n".join(self.LATER))
        with self.assertRaises(AssertionError):
            changelog_entry(found.replace(ENTRY_MARK, "(자체 개선 L9 — ") + "\n")

    def test_a_section_appended_after_the_security_section_does_not_change_it(self):
        text = read("docs/SECURITY.md")
        section = own_section(text)
        later = "\n## 다른 갈래의 절(설계 D-570 과 D-999)\n\n본문에 D-570 이 있다. 물결표나 링크가 있어도 이 묶음의 절이 아니다\n\n### 소절\n\n더 있다\n"
        self.assertEqual(own_section(text.rstrip("\n") + "\n" + later), section)
        self.assertNotIn("D-999", section)
        self.assertTrue(section.startswith(HEADING))

    def test_the_decision_rows_are_found_by_their_numbers_wherever_other_rows_stand(self):
        """결정 기록 행은 번호로 찾는다 — 앞뒤에 다른 갈래의 행이 얼마나 있든 같다."""
        lines = decision_lines()
        for number in NUMBERS:
            found = row_of(number)
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0][1].startswith(f"| {number} |"))
        self.assertGreater(len(lines), 100)


class ChangelogTest(unittest.TestCase):
    def test_the_last_entry_announces_this_work_with_its_numbers_and_limits(self):
        last = changelog_entry()
        for word in ("L8", "F074", "F069", "D-554", "D-558", "T2", "백업 형식·저장 형식·설정 칸", "원복"):
            with self.subTest(word=word):
                self.assertIn(word, last)
        self.assertNotIn("집계 대기", last)
        self.assertNotIn("@@", last)
        self.assertNotIn(chr(126), last)
        self.assertNotIn("http" + "://", last)
        self.assertNotIn("http" + "s://", last)


if __name__ == "__main__":
    unittest.main()
