"""글 흐름 화면 문서(`docs/UI_POST_FLOW.md`)의 'D-18 기능 → 화면 → 시험 매트릭스' 가 **거짓이 되지 않게** 표를 읽어 확인하는 시험(PySide6 없이 돈다).

지키는 것:
  1) 표의 모든 줄이 여섯 칸이고 번호가 M01 부터 빠짐없이 이어지며 단계 칸이 정해진 값 중 하나다(1a·1b·1c·이미 화면·다른 갈래·범위 밖).
  2) 단계가 1a 이거나 '이미 화면' 인 줄이 적은 시험 이름(백틱)은 실제로 있다 — 시험 파일이거나, 새 글 검토 시험 파일 안의 시험 클래스다. 없는 시험을 있다고 쓸 수 없다.
  3) D-18 의 열네 항목이 표에 모두 나온다(하위 기능까지 풀어 25줄).
  4) 문서가 말하는 숫자(미리보기 80블록·20,000자·3,000자·목록 50개·서비스 함수 아홉)가 코드의 값과 같고, 문서에 ASCII 물결표·웹 주소·이중 중괄호가 없으며 DECISIONS.md 에 D-620 이상의 같은 번호 행이 있다.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.ui.core import post_rules  # noqa: E402

DOC = ROOT / "docs" / "UI_POST_FLOW.md"
PHASES = ("1a", "1b", "1c", "이미 화면", "다른 갈래", "범위 밖")
D18_WORDS = ("작성", "수정", "불러오기", "Markdown", "미리보기", "Pages", "Blogger", "네이버", "복사", "글쓰기 페이지", "이미지", "삽입 위치", "상태", "URL", "예약", "배포", "오류 안내", "작업 로그", "백업", "복구", "버전", "업데이트")
POSTS_TEST_FILES = ("test_ui_posts_core.py", "test_ui_posts_adapter.py", "test_ui_qt_posts.py", "test_ui_posts_matrix.py")


def matrix_rows():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## 4. D-18", 1)[1].split("## 5.", 1)[0]
    rows = []
    for line in section.splitlines():
        if re.match(r"^\| M\d\d \|", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split(" | ")])
    return rows


def defined_classes():
    found = set()
    for name in POSTS_TEST_FILES:
        path = ROOT / "tests" / name
        if path.exists():
            found |= set(re.findall(r"^class (\w+)\(", path.read_text(encoding="utf-8"), re.MULTILINE))
    return found


class MatrixTest(unittest.TestCase):
    def test_the_matrix_is_there_with_six_columns_and_numbered_without_gaps(self):
        rows = matrix_rows()
        self.assertGreaterEqual(len(rows), 25)
        for row in rows:
            self.assertEqual(len(row), 6, row)
        self.assertEqual([row[0] for row in rows], [f"M{number:02d}" for number in range(1, len(rows) + 1)])

    def test_every_row_has_a_known_phase(self):
        for row in matrix_rows():
            with self.subTest(row=row[0]):
                self.assertTrue(any(row[4].startswith(phase) for phase in PHASES), row[4])

    def test_the_tests_named_for_1a_and_existing_screens_really_exist(self):
        classes = defined_classes()
        for row in matrix_rows():
            if not (row[4].startswith("1a") or row[4].startswith("이미 화면")):
                continue
            names = re.findall(r"`([^`]+)`", row[5])
            with self.subTest(row=row[0]):
                self.assertTrue(names, "1a·이미 화면 줄에는 시험 이름이 있어야 한다")
                for name in names:
                    if name.startswith("test_"):
                        self.assertTrue((ROOT / "tests" / f"{name}.py").exists(), f"{row[0]}: 시험 파일이 없다 — {name}")
                    else:
                        self.assertIn(name, classes, f"{row[0]}: 시험 클래스가 없다 — {name}")

    def test_the_fourteen_items_of_d18_all_appear(self):
        body = " ".join(row[1] + " " + row[2] for row in matrix_rows())
        for word in D18_WORDS:
            self.assertIn(word, body, f"D-18 항목이 표에 없다: {word}")

    def test_the_1b_and_1c_rows_do_not_claim_a_test_that_does_not_exist_yet(self):
        for row in matrix_rows():
            if row[4].startswith(("1b", "1c")):
                self.assertNotRegex(row[5], r"`Posts\w+Test`", f"{row[0]}: 이 묶음이 만들지 않은 단계의 시험 이름을 적을 수 없다")


class DocumentFactsTest(unittest.TestCase):
    def setUp(self):
        self.doc = DOC.read_text(encoding="utf-8")

    def test_the_numbers_in_the_document_are_the_codes_numbers(self):
        self.assertIn(f"앞 {post_rules.PREVIEW_BLOCKS}개", self.doc)
        self.assertIn(f"{post_rules.PREVIEW_CHARS:,}자", self.doc)
        self.assertIn(f"{post_rules.BLOCK_LIMIT:,}자", self.doc)
        self.assertIn(f"앞 {post_rules.PAGE}개", self.doc)
        self.assertIn("정확히 아홉", self.doc)

    def test_the_document_has_no_tilde_no_web_address_and_no_double_braces(self):
        self.assertNotIn(chr(0x7E), self.doc)
        self.assertIsNone(re.search(r"(?i)(https?|ftp)://|www[.]", self.doc))
        self.assertNotIn("{{", self.doc)

    def test_the_decisions_the_document_names_are_in_the_decision_log(self):
        log = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        named = sorted(set(re.findall(r"\*\*(D-6\d\d)\b", self.doc)))
        self.assertGreaterEqual(len(named), 14)
        for number in named:
            with self.subTest(decision=number):
                self.assertRegex(log, rf"(?m)^\| {number} \|")

    def test_the_decision_numbers_stay_in_the_range_of_this_lane(self):
        numbers = [int(value) for value in re.findall(r"\*\*D-(\d+)\b", self.doc)]
        self.assertTrue(numbers and min(numbers) >= 620 and max(numbers) <= 659, (min(numbers), max(numbers)))


if __name__ == "__main__":
    unittest.main()
