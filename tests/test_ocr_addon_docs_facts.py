"""`docs/PACKAGE_OCR.md` 가 코드·워크플로와 어긋나지 않게 못박는 시험(N1, 2026-11-23 — 독립 점검 W1 의 M1·R1–R4 문서 정정이 다시 낡아지지 않게). 글이 말하는 사실 중 코드·워크플로에서 읽을 수 있는 것만 본다.

지키는 것:
  1) 2-1절의 액션 해시 대조 표(해시·버전·워크플로 줄 번호)가 `package-ocr.yml` 의 실제 `uses:` 줄과 같고, 글에 적힌 '31·35·65줄' 도 실제 줄 번호다 — 워크플로를 고치면 표도 같이 고치게 된다.
  2) 글이 말하는 제한 시간(45분)·보관 기간(14일)·워크플로 이름이 워크플로의 값과 같다.
  3) 5단계의 압축 파일 이름 예시가 지금 `VERSION` 으로 만들어지는 이름이다 — 버전을 올리면 글도 고치게 된다.
  4) 합치기 전의 값(205.7MB·84.6MB·106개·107개)은 '합치기 전' 이라고 적힌 줄에만 있다(W1 의 M1 — 합치기 전 실측을 합친 스크립트의 결과처럼 읽히지 않게).
  5) 정확한 SHA-256(64자리 16진수)과 7자리 이상의 바이트 수를 문서에 적지 않는다(총괄 2026-11-23 — 추가 도구 안의 파일이 바뀌면 달라지는 값이라 보고서·증거 파일에만 둔다).
  6) 11절 '켜기 전에 정할 일' 에 질문 후보 다섯 개가 있다.
표준 라이브러리만 쓰고 파일을 읽기만 한다.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_build_support as support  # noqa: E402

DOC = support.read("docs/PACKAGE_OCR.md")
WORKFLOW = support.read(".github/workflows/package-ocr.yml")
RULES = support.load("build_rules")
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<action>[\w.-]+/[\w.-]+)@(?P<sha>[0-9a-f]{40})\s*#\s*(?P<version>v[\w.]+)\s*$")
HASH64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", re.I)                                     # 정확한 SHA-256 모양(PowerShell Get-FileHash 는 대문자로 찍으므로 대소문자를 가리지 않는다 — 독립 검증 S 의 SR4)
BIG_NUMBER = re.compile(r"\d{1,3}(?:[,._ ]\d{3}){2,}|(?<![0-9A-Za-z])\d{7,}(?![0-9A-Za-z])")        # 정확한 바이트 수 모양(쉼표·점·밑줄·공백으로 끊어 적어도 잡고, 숫자 뒤에 한글이 바로 붙어도 잡고, 16진수 해시 속 숫자 덩어리는 잡지 않는다)
STALE = ("205.7MB", "84.6MB", "106개", "107개", "205,693,909")                                          # 합치기 전(D 갈래 단독 빌드)의 값 — '합치기 전' 이라는 말 뒤에서만 나올 수 있다
STALE_TIMES = ("147–199초", "147에서 199초")                                                             # 합치기 전(바쁜 PC)의 빌드 시간 — 이것도 '합치기 전' 이라는 말 뒤에서만(SR5)


def workflow_uses():
    """워크플로의 `uses:` 줄들 -> [(줄 번호, 액션, 40자리 해시, 주석의 버전)]."""
    found = []
    for number, line in enumerate(WORKFLOW.splitlines(), 1):
        match = USES.match(line)
        if match:
            found.append((number, match["action"], match["sha"], match["version"]))
    return found


class ActionTableTest(unittest.TestCase):
    def table_rows(self):
        rows = []
        for line in DOC.splitlines():
            if line.startswith("| `actions/"):
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                rows.append((int(cells[1]), cells[0].strip("`"), cells[2].strip("`"), cells[3]))
        return rows

    def test_the_table_lists_exactly_the_workflow_uses_lines_with_their_hash_version_and_line_number(self):
        actual = workflow_uses()
        self.assertEqual(len(actual), 3, "워크플로의 uses 줄은 셋뿐이다")
        self.assertEqual(self.table_rows(), actual)

    def test_the_prose_names_the_same_three_line_numbers_twice(self):
        cited = "·".join(str(item[0]) for item in workflow_uses()) + "줄"
        self.assertGreaterEqual(DOC.count(cited), 2, "표 앞 설명과 운영자 대조 문장 둘 다 실제 줄 번호를 말한다: " + cited)

    def test_the_table_says_it_is_a_preliminary_ai_check_that_does_not_replace_the_operator(self):
        for needle in ("AI 예비 대조", "운영자 대조를 대신하지 않습니다", "한 글자도 다르지 않은지 눈으로 봅니다"):
            self.assertIn(needle, DOC, needle)
        self.assertIsNone(re.search(r"(?i)(?:https?|ftp):|://", DOC), "웹 주소는 앞머리(스킴) 없이 호스트·경로만 적는다(WinHTTP 같은 DLL 이름은 주소가 아니다)")


class StatedFactsTest(unittest.TestCase):
    def test_the_stated_time_limit_the_retention_and_the_workflow_name_are_the_workflows(self):
        timeout = int(re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", WORKFLOW, re.M).group(1))
        retention = int(re.search(r"^\s*retention-days:\s*(\d+)\s*$", WORKFLOW, re.M).group(1))
        name = re.match(r'name:\s*"(.+)"', WORKFLOW).group(1)
        self.assertIn("%d분이 지나도 끝나지 않으면 GitHub 가 알아서 멈춥니다" % timeout, DOC)
        self.assertIn("올려 둔 파일은 %d일만 보관됩니다" % retention, DOC)
        self.assertIn("`%s`" % name, DOC, "3절 1단계가 부르는 워크플로 이름이 글자까지 같다")

    def test_the_example_zip_name_is_the_one_the_build_would_make_now_and_the_autocomplete_hint_is_there(self):
        name = RULES.zip_name(support.read("VERSION").lstrip(chr(0xFEFF)).strip())
        self.assertIn("`%s`" % name, DOC)
        self.assertIn("Get-FileHash .\\ChanceBlogDesktop-OCR-` 까지 쓴 뒤 Tab 키", DOC)

    def test_the_values_from_before_the_merge_only_stand_on_lines_that_say_so(self):
        lines = DOC.splitlines()
        stale = ("205.7MB", "84.6MB", "106개", "107개", "205,693,909")
        hits = [(number, word) for number, line in enumerate(lines, 1) for word in stale if word in line and "합치기 전" not in line]
        self.assertEqual(hits, [], "합치기 전의 값이 '합치기 전' 표지 없이 남았다")
        self.assertGreaterEqual(sum(1 for line in lines if "합치기 전" in line), 5)

    def test_no_exact_hash_or_byte_count_of_a_build_is_written_in_the_doc(self):
        self.assertEqual(HASH64.findall(DOC), [], "정확한 SHA-256 은 보고서·증거 파일에만 둔다")
        self.assertEqual(BIG_NUMBER.findall(DOC), [], "7자리 이상의 정확한 바이트 수는 보고서·증거 파일에만 둔다")

    def test_the_two_scanners_catch_what_they_are_meant_to_and_leave_the_ordinary_numbers_alone(self):
        self.assertTrue(HASH64.search("값 " + "a" * 64 + " 끝"))
        self.assertTrue(HASH64.search("Hash : " + "AB" * 32), "PowerShell 의 Get-FileHash 는 대문자 64자리를 찍는다")
        self.assertTrue(HASH64.search("값 " + "aB" * 32 + " 끝"))
        self.assertFalse(HASH64.search("a" * 40) or HASH64.search("a" * 65) or HASH64.search("A" * 63) or HASH64.search("g" * 64))
        for text in ("압축 파일 84798380바이트", "84,798,380바이트", "약 12345678 바이트", "크기 1,234,567", "84 798 380바이트", "84.798.380바이트", "84_798_380바이트", "압축 파일 84 798 380 바이트"):
            self.assertTrue(BIG_NUMBER.search(text), text)
        for text in ("11d5960a326750d5838078e36cf38b85af677262", "11,945줄·47,451바이트", "파일 144개", "약 207MB", "147–199초", "SHA-256 `f62699f6`", "0.1.0-preview.1", "Python 3.12.0", "v4.4.0 · v5.6.0 · v4.6.2",
                     "2026-11-23 10시대", "1–2 단계", "10–20분", "205.7MB(파일 106개)", "47 451바이트 한 개", "버전 3.14.1"):
            self.assertFalse(BIG_NUMBER.search(text), text)

    def test_a_value_from_before_the_merge_always_comes_after_the_words_before_the_merge_on_its_line(self):
        """SR4(다) — 한 줄에 합친 값과 합치기 전 값이 같이 있어도 합치기 전 값은 '합치기 전' 이라는 말 뒤에만 있다. 앞에 있으면 합친 값 자리가 옛 값으로 되돌아간 것이다(W1 의 M1 이 한 줄 안에서 되살아남)."""
        seen = 0
        for number, line in enumerate(DOC.splitlines(), 1):
            for word in STALE + STALE_TIMES:
                if word in line:
                    seen += 1
                    self.assertIn("합치기 전", line, (number, word))
                    self.assertLess(line.index("합치기 전"), line.index(word), "합치기 전 표지가 값보다 앞서야 한다: 줄 %d %s" % (number, word))
        self.assertGreaterEqual(seen, 8, "옛 값이 문서에 남아 있어야(표지와 함께) 이 시험이 의미가 있다")

    def test_the_size_line_has_the_merged_counts_ahead_of_the_marker_and_no_value_from_before_the_merge(self):
        line = next(item for item in DOC.splitlines() if item.startswith("크기(이 PC 시제품 실측"))
        head = line.split("합치기 전", 1)[0]
        for needle in ("파일 144개", "145개", "약 207MB", "약 85MB"):
            self.assertIn(needle, head, needle)
        for word in STALE:
            self.assertNotIn(word, head, word)
        self.assertIn("106개", line, "합치기 전 값은 같은 줄 뒤쪽에 표지와 함께 남아 있다")

    def test_the_merged_build_numbers_are_there_as_file_counts_and_rounded_sizes(self):
        for needle in ("파일 144개", "압축 파일의 항목은 정보 파일까지 145개", "약 207MB", "약 85MB", "정확한 값은 만들 때마다"):
            self.assertIn(needle, DOC, needle)


class QuestionCandidatesTest(unittest.TestCase):
    def test_the_section_has_the_five_topics_each_with_facts_and_a_question_candidate(self):
        part = DOC[DOC.index("## 11. 켜기 전에 정할 일"):]
        topics = ((1, "GEOS 소스 제공 방식"), (2, "바꿔 끼우기와 앱의 파일 확인"), (3, "앱 약관·라이선스 문구"), (4, "'개인 PC 제한'"), (5, "모델 고지"))
        for number, topic in topics:
            self.assertRegex(part, r"(?m)^%d\. \*\*[^\n]*%s" % (number, re.escape(topic)), topic)
        self.assertEqual(len(re.findall(r"사실:", part)), 5)
        self.assertEqual(len(re.findall(r"질문 후보:", part)), 5)
        self.assertIn("질문을 운영자에게 보내는 일은 총괄 몫", part)
        self.assertIn("법률 자문이 아닙니다", part)


if __name__ == "__main__":
    unittest.main()
