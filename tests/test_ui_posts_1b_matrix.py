"""글 흐름 1b 문서(`docs/UI_POST_FLOW.md` 의 8-10 '시험 매트릭스 (1b)')와 문서가 말하는 숫자·결정 번호가 **거짓이 되지 않게** 읽어서 확인하는 시험(PySide6 없이 돈다).

지키는 것:
  1) 표의 모든 줄이 다섯 칸이고 번호가 B01 부터 빠짐없이 이어지며 단계 칸이 정해진 값(1b·1b-2·1c) 중 하나다.
  2) 단계가 1b 인 줄이 적은 시험 이름(백틱)은 실제로 있는 시험 클래스이고 그 클래스에 시험이 하나 이상 있다 — 없는 시험을 있다고 쓸 수 없다. 1b-2·1c 줄은 이 묶음이 만들지 않은 일이라 시험 이름을 적지 않는다.
  3) 1b 의 범위(복사 패키지·복사했어요·발행 주소·유사도·발행 기록·작업 로그·프로필·건강·사이드바)가 표에 모두 나온다.
  4) 문서가 말하는 숫자(어댑터가 부르는 서비스 함수 열다섯·작은 함수 여섯)가 코드와 같고, 이 갈래의 결정 D-642–D-656 이 문서와 결정 기록에 하나씩 있다.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

DOC = ROOT / "docs" / "UI_POST_FLOW.md"
LOG = ROOT / "docs" / "DECISIONS.md"
PHASES = ("1b", "1b-2", "1c")
TEST_FILES = ("test_service_naver_1b.py", "test_ui_posts_1b_core.py", "test_ui_posts_1b_adapter.py", "test_ui_qt_posts_1b.py")
SCOPE_WORDS = ("복사 패키지", "복사했어요", "발행 주소", "유사도", "발행 기록", "작업 로그", "프로필", "건강", "사이드바")
OWN_DECISIONS = tuple(range(642, 657))                                                      # 이 갈래가 정의한 결정 D-642–D-656


def matrix_rows():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("### 8-10.", 1)[1]
    rows = []
    for line in section.splitlines():
        if re.match(r"^\| B\d\d \|", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split(" | ")])
    return rows


def defined_classes():
    """시험 클래스 이름 → 그 안의 시험 함수 수."""
    found = {}
    for name in TEST_FILES:
        tree = ast.parse((ROOT / "tests" / name).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                found[node.name] = sum(1 for item in node.body if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"))
    return found


class MatrixTest(unittest.TestCase):
    def test_the_matrix_is_there_with_five_columns_and_numbered_without_gaps(self):
        rows = matrix_rows()
        self.assertGreaterEqual(len(rows), 24)
        for row in rows:
            self.assertEqual(len(row), 5, row)
        self.assertEqual([row[0] for row in rows], [f"B{number:02d}" for number in range(1, len(rows) + 1)])

    def test_every_row_has_a_known_phase(self):
        for row in matrix_rows():
            with self.subTest(row=row[0]):
                self.assertIn(row[3], PHASES)

    def test_the_tests_named_for_1b_really_exist_and_have_tests(self):
        classes = defined_classes()
        for row in matrix_rows():
            if row[3] != "1b":
                continue
            names = re.findall(r"`([^`]+)`", row[4])
            with self.subTest(row=row[0]):
                self.assertTrue(names, "1b 줄에는 시험 이름이 있어야 한다")
                for name in names:
                    self.assertIn(name, classes, f"{row[0]}: 시험 클래스가 없다 — {name}")
                    self.assertGreaterEqual(classes[name], 1, f"{row[0]}: 시험이 하나도 없는 클래스다 — {name}")

    def test_the_deferred_rows_claim_no_test(self):
        deferred = [row for row in matrix_rows() if row[3] in ("1b-2", "1c")]
        self.assertGreaterEqual(len(deferred), 4)
        for row in deferred:
            with self.subTest(row=row[0]):
                self.assertNotRegex(row[4], r"`\w+Test`", f"{row[0]}: 이 묶음이 만들지 않은 단계의 시험 이름을 적을 수 없다")

    def test_the_scope_of_1b_all_appears_in_the_matrix(self):
        body = " ".join(row[1] + " " + row[2] for row in matrix_rows() if row[3] == "1b")
        for word in SCOPE_WORDS:
            self.assertIn(word, body, f"1b 범위가 표에 없다: {word}")

    def test_every_test_class_of_the_four_1b_files_is_named_in_the_matrix(self):
        """표에 없는 시험 클래스가 새로 생기면(Base 같은 부품 클래스는 빼고) 표에 올리라고 알린다 — 표가 시험을 따라가게 한다."""
        named = {name for row in matrix_rows() for name in re.findall(r"`([^`]+)`", row[4])}
        missing = sorted(name for name, count in defined_classes().items() if count and name not in named)
        self.assertEqual(missing, [], "표(8-10)에 올리지 않은 시험 클래스")


class DocumentFacts1bTest(unittest.TestCase):
    def setUp(self):
        self.doc = DOC.read_text(encoding="utf-8")

    def test_the_adapter_calls_exactly_fifteen_service_functions_as_the_document_says(self):
        """어댑터 소스에서 서비스 모듈 별칭의 함수 호출을 세어 문서의 '열다섯' 과 견준다(허용 목록을 못박는 시험과 별개로 문서의 숫자가 코드와 같은지 본다)."""
        import test_ui_posts_core as core
        uses = {item for item in core.PostsSourceRulesTest.SERVICE_USES if not item.endswith(".SUBJECT")}
        self.assertEqual(len(uses), 15)
        self.assertIn("열다섯", self.doc)
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "posts_adapter.py").read_text(encoding="utf-8"))
        called = {f"{node.func.value.id}.{node.func.attr}" for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)}
        self.assertEqual(sorted(item for item in called if item.split(".")[0].endswith(("_service", "own_posts"))), sorted(uses))

    def test_the_new_service_code_is_six_small_functions_as_the_document_says(self):
        self.assertIn("작은 함수 여섯", self.doc)
        service = ROOT / "src" / "chanceblog_desktop" / "service"
        defined = {"review.read_naver_package": "def read_naver_package(", "review.mark_naver_copied": "def mark_naver_copied(", "history.list_history": "def list_history(", "worklog.read_work_log": "def read_work_log(",
                   "naver_profiles.profile_for": "def profile_for(", "naver_profiles.profile_keys": "def profile_keys("}
        for name, header in defined.items():
            with self.subTest(function=name):
                self.assertEqual((service / (name.split(".")[0] + ".py")).read_text(encoding="utf-8").count(header), 1)

    def test_the_decisions_of_this_lane_are_in_the_document_and_in_the_log_exactly_once(self):
        log = LOG.read_text(encoding="utf-8")
        for number in OWN_DECISIONS:
            with self.subTest(decision=number):
                self.assertEqual(len(re.findall(rf"(?m)^- \*\*D-{number} ", self.doc)), 1, f"문서에 D-{number} 정의가 한 번만 있어야 한다")
                self.assertEqual(len(re.findall(rf"(?m)^\| D-{number} \|", log)), 1, f"결정 기록에 D-{number} 행이 한 번만 있어야 한다")

    def test_the_decision_rows_say_the_facts_that_were_measured(self):
        """D-651 은 잰 사이드바 높이(493 에서 485)를, D-654 는 갱신한 기존 시험을, D-656 은 변이 점검을 적는다 — 구현 뒤에 채운 값이 문서에 남아 있어야 한다."""
        log = LOG.read_text(encoding="utf-8")
        row = {number: re.search(rf"(?m)^\| D-{number} \|[^\n]*", log).group(0) for number in (651, 654, 656)}
        for word in ("493", "485"):
            self.assertIn(word, row[651])
        self.assertIn("의도적", row[654])
        self.assertRegex(row[656], r"변이")


if __name__ == "__main__":
    unittest.main()
