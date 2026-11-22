"""L8b 묶음(복원 시작 때 지금 보관함 보기 · L8 시험 틈 보강 · 문서 시험의 찾는 방법)의 문서 시험 — `docs/DECISIONS.md` 의 D-570–D-573·`docs/SECURITY.md` 의 새 절·`CHANGELOG.md` 의 항목·`docs/TROUBLESHOOTING.md` 의 RESTORE_FAILED 행이
코드와 어긋나지 않게 못박는다.

지키는 것:
  1) 결정 기록 D-570–D-573 이 번호마다 정확히 한 줄이고(표의 한 행은 칸이 다섯 개의 `|`) 번호 순서이며, 앞 줄이 표의 행이라 표가 끊기지 않고, 행마다 있어야 하는 낱말을 가졌다. 물결표·웹 주소·채우지 않은 자리표시자가 없고 이 갈래의 번호 범위(D-570–D-579) 안이다.
  2) 보안 문서의 새 절이 코드의 사실과 같다 — 화면 문장 둘을 글자 그대로 싣고, 이유 이름·함수 이름·오류 코드·한계 넷이 적혀 있다. 앞 절(L8)의 한계 ④ 는 더는 '복원이 끝난 뒤의 되돌리기가 거절된다' 고 하지 않고 새 절을 가리킨다.
  3) 변경 이력의 이 묶음 항목이 정확히 하나이고 다른 갈래의 줄과 섞이지 않는다.
  4) 오류 표(`TROUBLESHOOTING.md`)의 RESTORE_FAILED 행이 새 이유를 말하고 만든 파일(`errors/catalog.py`)과 같다.
  5) 결정 D-573 의 시험 개수 합이 맞고 이 묶음이 새로 만든 시험 모듈의 개수가 실제와 같다(다른 갈래가 같이 고치는 모듈의 개수는 못박지 않는다).
네트워크·실제 비밀 없이 돈다.
"""
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

ROOT = HERE.parent
NUMBERS = ("D-570", "D-571", "D-572", "D-573", "D-574")
LANE = {f"D-{number}" for number in range(570, 580)}
EARLIER = {"D-554", "D-555", "D-556", "D-557", "D-558"}                              # 앞 묶음(L8)의 번호 — 이 묶음의 글이 되짚을 수 있다
HEADING = "## 복원은 지금 보관함이 복원 직전 사본으로 되돌릴 수 있을 때만 시작한다(L8b — 설계 D-570–D-574)"
L8_HEADING = "## 조작된 백업의 구조 검사와 올리기 직전 관문의 비밀 모양 목록(L8 — 설계 D-554–D-558)"
ENTRY_MARK = "(자체 개선 L8b — "
NEW_MODULES = ("test_service_backup_live_structure", "test_ui_backup_live_structure", "test_ui_qt_backup_live_structure", "test_l8b_docs")
REQUIRED = {
    "D-570": ("_refuse_if_undo_impossible", "RESTORE_FAILED", "live_structure", "D-387", "D-393", "D-554", "복원 직전 사본", "시작하지 않", "읽기 전용", "막는다", "위임 규칙", "추천안", "QP-1", "SP-5", "네트워크 경로", "restore", "경쟁"),
    "D-571": ("QG1", "QG2", "QG3", "QG4", "QR1", "QR2", "QP1", "QP2", "QP3", "QP4", "QP-3", "QP-4", "변이", "제품 코드", "sqlite_", "NVIDIA", "Stripe", "Slack", "DigitalOcean"),
    "D-572": ("QP-5", "test_l8_docs", "changelog_entry", "own_section", "자체 개선 L8 — ", "L4", "강화", "완화", "FindersStayStableTest"),
    "D-574": ("QL-1", "QL-2", "QL-3", "QL-4", "SP-1", "SP-2", "SP-3", "ReadOnlyTest", "읽기 전용", "진단 정보 복사", "schema_guard.py", "하지 않은 것", "오류 표", "독립 검증"),
    "D-573": ("새 시험", "변이", "바뀐 기존 시험", "test_l8_docs", "test_content_schema_guard", "test_security_recent_shapes", "고치기 전 코드", "숫자", "운영자", "알려 둔 한계"),
}


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def decision_lines():
    return read("docs/DECISIONS.md").splitlines()


def row_of(number):
    return [(index, line) for index, line in enumerate(decision_lines()) if line.startswith(f"| {number} |")]


def section(text, heading):
    """보안 문서에서 `heading` 으로 열리는 절만 — 다음 `## ` 절이나 파일 끝까지."""
    rest = text[text.index(heading):]
    return rest.split("\n## ", 1)[0]


def test_count(module):
    return len(re.findall(r"(?m)^    def test_", (HERE / f"{module}.py").read_text(encoding="utf-8")))


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
        for number in NUMBERS:
            for found in set(re.findall(r"D-5\d\d", row_of(number)[0][1])):
                with self.subTest(number=number, found=found):
                    self.assertIn(found, LANE | EARLIER, "이 갈래의 번호 범위(D-570–D-579)와 앞 묶음(L8) 번호만 쓴다")
        for found in set(re.findall(r"D-5\d\d", section(read("docs/SECURITY.md"), HEADING))):
            self.assertIn(found, LANE | EARLIER)

    def test_the_decision_about_blocking_or_only_telling_is_recorded_with_its_reasons(self):
        line = row_of("D-570")[0][1]
        for word in ("막을지", "알리기만", "데이터 보존", "되돌릴 수 있는 안전한 기본값", "화면 계층은 데이터를 읽지 않", "검사를 끄는"):
            self.assertIn(word, line)


class SecuritySectionTest(unittest.TestCase):
    def own(self):
        text = read("docs/SECURITY.md")
        self.assertEqual(text.count(HEADING), 1)
        return section(text, HEADING)

    def test_the_section_has_its_parts_and_the_three_screen_sentences_word_for_word(self):
        text = self.own()
        self.assertTrue(text.startswith(HEADING))
        for part in ("### 문제(검증자 둘이 따로 재현)", "### 고친 것 — 되돌릴 수 없는 보관함이면 복원을 시작하지 않는다", "### 막을지 알리기만 할지(D-570 ③)", "### 보는 범위", "### 한계(사실대로)", "### 시험 틈과 문서 시험", "### 독립 검증 권고 반영(D-574)"):
            self.assertIn(part, text)
        self.assertIn(T["backup_fail_restore_unstarted"], text, "첫 문장이 화면과 같다")
        self.assertIn(T["backup_restore_live_structure"], text, "이유 줄이 화면과 같다")
        self.assertIn(T["backup_restore_live_structure_help"], text, "다음에 할 일 줄이 화면과 같다(독립 검증 S 의 SP-1)")

    def test_the_names_the_code_uses_are_written(self):
        text = self.own()
        for word in ("_refuse_if_undo_impossible", "_foreign_in", "RESTORE_FAILED", bf.LIVE_STRUCTURE, "새 오류 코드", "검사를 끄는 인자·설정은 없다", "D-387", "읽기 전용"):
            self.assertIn(word, text)

    def test_the_four_limits_are_written_in_plain_words(self):
        text = self.own()
        limits = text[text.index("### 한계(사실대로)"):text.index("### 시험 틈과 문서 시험")]
        for word in ("① 같은 부류가 하나 더 있다", "네트워크 경로", "② 옛 `restore` 명령과 주제 엔진의 `topics restore`", "③ 검사와 안전 사본 사이", "경쟁", "④ 백업을 **만드는** 쪽은 그대로다"):
            self.assertIn(word, limits)

    def test_the_promise_sentences_carry_their_exception_and_the_read_only_claim_its_scope(self):
        """독립 검증의 참고 QL-4·SP-3 와 권고 SP-2 — '시작하는 복원마다 지켜진다' 에는 네트워크 경로 설정의 예외가, '아무것도 쓰지 않고' 에는 앱이 만드는 저장 방식이라는 범위가 붙고, 앞 절과 개체 검사 모듈의 머리 설명에 있던
        '지금 열려 있는 보관함은 이 검사를 받지 않는다' 는 백업을 만들 때로 좁혀졌다(복원을 시작할 때는 받는다)."""
        text = self.own()
        self.assertIn("이제 복원이 시작하는 경우마다 지켜진다(아래 한계 ① 의 네트워크 경로 설정은 제외)", text)
        self.assertIn("앱이 만드는 삭제 저널 방식의 보관함 기준", text)
        self.assertIn("한계 ⑥ 의 네트워크 경로 설정은 제외한다", row_of("D-570")[0][1])
        earlier = section(read("docs/SECURITY.md"), L8_HEADING)
        self.assertIn("백업을 만들 때 지금 열려 있는 보관함은 이 검사를 받지 않는다. 복원을 시작할 때는 받는다 — 아래 L8b 절", earlier)
        self.assertNotIn("(지금 파일을 그대로 담는다 — 지금 열려 있는 보관함은 이 검사를 받지 않는다)", earlier, "고치기 전의 옛 구절")
        schema = read("src/chanceblog_desktop/content/schema_guard.py")
        self.assertNotIn("지금 열려 있는 보관함은 이 검사를 받지 않는다", schema, "고치기 전의 옛 설명")
        self.assertIn("복원을 시작할 때 그 복원이 바꿀", schema)
        self.assertIn("_refuse_if_undo_impossible", schema)

    def test_the_section_has_no_tilde_no_link_and_nothing_unfinished(self):
        text = self.own()
        self.assertNotIn(chr(126), text)
        self.assertNotIn("http" + "://", text)
        self.assertNotIn("http" + "s://", text)
        for unfinished in ("@@", "TODO", "XXX", "{{", "}}", "미정", "채울"):
            self.assertNotIn(unfinished, text)

    def test_the_earlier_section_no_longer_says_the_undo_is_refused_and_points_here(self):
        """앞 절(L8)의 한계 ④ 는 '복원이 끝난 뒤 되돌리기가 거절된다' 고 하던 문장을 이제 '복원이 시작하지 않는다' 로 고쳤다 — 앞 절은 이 절 앞에서 끝난다."""
        text = read("docs/SECURITY.md")
        earlier = section(text, L8_HEADING)
        self.assertNotIn(HEADING, earlier, "앞 절은 이 절에서 끝난다")
        self.assertIn("이제 복원은 지금 보관함에 그런 개체가 있으면 시작하지 않으므로 이 경우는 생기지 않는다", earlier)
        self.assertNotIn("그 되돌리기가 거절된다(자료는 사본 폴더", earlier, "고치기 전의 옛 문장")
        self.assertIn("앱 밖의 도구", earlier)
        self.assertLess(text.index(L8_HEADING), text.index(HEADING), "이 절이 앞 절 뒤에 덧붙었다")


class ChangelogTest(unittest.TestCase):
    def entry(self):
        found = [line for line in read("CHANGELOG.md").splitlines() if line.startswith("- ") and ENTRY_MARK in line]
        self.assertEqual(len(found), 1, "변경 이력에 이 묶음의 항목이 정확히 하나여야 한다")
        return found[0]

    def test_the_entry_announces_this_work_with_its_numbers_and_limits(self):
        line = self.entry()
        for word in ("L8b", "QP-1", "QP-3", "QP-4", "QP-5", "SP-5", "D-570", "D-574", "T2", "복원을 시작하지", "새 오류 코드", "원복", "독립 검증 권고"):
            with self.subTest(word=word):
                self.assertIn(word, line)
        for unfinished in ("집계 대기", "@@", "TODO", "{{"):
            self.assertNotIn(unfinished, line)
        self.assertNotIn(chr(126), line)
        self.assertNotIn("http" + "://", line)
        self.assertNotIn("http" + "s://", line)

    def test_the_earlier_entry_of_l8_is_still_found_on_its_own_and_is_a_different_line(self):
        earlier = [line for line in read("CHANGELOG.md").splitlines() if line.startswith("- ") and "(자체 개선 L8 — " in line]
        self.assertEqual(len(earlier), 1)
        self.assertNotEqual(earlier[0], self.entry())


class TroubleshootingTest(unittest.TestCase):
    def test_the_restore_failed_row_says_the_new_reason_and_the_catalog_has_the_same_words(self):
        row = next(line for line in read("docs/TROUBLESHOOTING.md").splitlines() if line.startswith("| `RESTORE_FAILED` |"))
        catalog = read("src/chanceblog_desktop/errors/catalog.py")
        for word in ("지금 보관함에 앱이 만들지 않는 구조", "복원 직전 사본으로 되돌릴 수 없어서 바꾸기 전에 시작하지 않음(이유 `live_structure`)", "앱 밖의 도구로 보관함에 더한 트리거·뷰·모르는 표·색인을 지운 뒤 다시 복원해 주세요",
                     "지우는 방법을 모르겠다면 설정 → 정보 → `진단 정보 복사` 를 누른 뒤 붙여 넣어 알려 주세요"):
            with self.subTest(word=word[:20]):
                self.assertIn(word, row)
                self.assertIn(word, catalog)
        self.assertEqual(row.count("|"), 6, "오류 표의 한 행은 `|` 여섯 개(코드·언제·문구·하실 일·재시도)")
        self.assertTrue(row.rstrip().endswith("| 고친 뒤 |"))
        self.assertIn(bf.LIVE_STRUCTURE, row)


class CountsTest(unittest.TestCase):
    def counts(self):
        line = row_of("D-573")[0][1]
        total = re.search(r"새 시험 (\d+)개 =", line)
        self.assertIsNotNone(total, "D-573 에 '새 시험 N개 =' 문장이 있다")
        return line, int(total.group(1))

    def test_the_new_modules_counts_in_the_decision_are_the_real_counts(self):
        line, _total = self.counts()
        for module in NEW_MODULES:
            with self.subTest(module=module):
                found = re.findall(rf"`tests/{module}\.py` (\d+)", line)
                self.assertEqual(len(found), 1, f"{module} 의 개수가 D-573 에 한 번 적혀 있다")
                self.assertEqual(int(found[0]), test_count(module), f"{module}: 적힌 개수가 실제 시험 함수의 수와 다르다")

    def test_the_total_is_the_sum_of_the_new_modules_and_the_tests_added_to_old_ones(self):
        line, total = self.counts()
        parts = [int(number) for number in re.findall(rf"`tests/(?:{'|'.join(NEW_MODULES)})\.py` (\d+)", line)]
        added = re.search(r"기존 모듈에 더한 것 ((?:`[a-z_0-9]+` \d+(?: · )?)+)", line)
        self.assertIsNotNone(added, "D-573 에 '기존 모듈에 더한 것 …' 이 있다")
        parts += [int(number) for number in re.findall(r"`[a-z_0-9]+` (\d+)", added.group(1))]
        self.assertEqual(sum(parts), total, "새 시험 개수의 합")
        self.assertEqual(len(parts), len(NEW_MODULES) + 3)


if __name__ == "__main__":
    unittest.main()
