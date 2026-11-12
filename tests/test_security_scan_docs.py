"""본문 속 Secret 형태 검사기의 문서 시험(D-420–D-429) — 이 묶음의 결정 행·보안 절·구조 줄·변경 이력 줄이 문서에 있고, 문서가 말하는 모양이 코드와 같다.

지키는 것:
  1) `docs/DECISIONS.md` 의 D-420–D-429 행이 번호마다 정확히 한 줄이고(표의 한 행은 칸이 다섯) 번호 순서이며, 행마다 있어야 하는 낱말을 가졌다. 물결표·웹 주소·채우지 않은 자리(`@@…@@`)가 없다.
  2) `docs/SECURITY.md` 의 '본문 속 Secret 형태 검사' 절, `docs/ARCHITECTURE.md`·`CHANGELOG.md` 의 이 묶음 줄이 필요한 낱말을 모두 가졌다.
  3) 문서가 든 예시 문장(`describe`·`summarize` 의 문장)과 접두어 목록(GitHub 다섯 글자·AWS 여덟 접두어·유형 키 여섯)이 코드와 한 글자도 다르지 않다.
다른 묶음의 행·줄이 같은 파일 이름을 언급해도 깨지지 않게 이 묶음의 행·줄은 **번호와 낱말**로 찾는다. 다른 묶음의 결정 번호나 전체 최댓값은 못박지 않는다.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]

from chanceblog_desktop.security import scan  # noqa: E402

TILDE = chr(126)
ROW_WORDS = {                     # 이 묶음의 행마다 있어야 하는 낱말
    "D-420": ("security/scan.py", "scan_secrets", "scan_fields", "has_secret", "describe", "summarize", "SecretFinding", "KIND_LABELS", "고정 영문 키", "무시하고 저장", "호출 규약", "TypeError", "ValueError", "T1"),
    "D-421": ("AIza", "ghp_", "github_pat_", "Bearer", "ya29.", "1//", "GOCSPX-", "JWT", "access_token", "AKIA", "PRIVATE KEY", "머리 줄", "모양만 본다"),
    "D-422": ("한 건", "PEM > AWS > GitHub > Google > OAuth > Bearer", "앞 글자", "맞닿기만", "제곱 시간"),
    "D-423": ("NFKC", "코드 포인트", "CRLF", "항등", "512자", "글자 하나씩", "col_end", "대응표"),
    "D-424": ("선형", "0.5초", "3.12", "3.10", "서로 다른 글자 10만 개", "{0,3}"),
    "D-425": ("카나리", "길이 힌트", "describe", "summarize", "고치는 법", "외 N줄", "약한 참조"),
    "D-426": ("오탐 표", "미탐 표", "알려 둔 한계", "쪼갠 토큰", "xghp_", "OpenAI", "PEM"),
    "D-427": ("호출 묶음", "LOCALSAVE", "BACKUPUI", "부분 폴더", "mask.py", "shape.py", "문자열만"),
    "D-428": ("test_security_scan.py", "test_security_scan_shapes.py", "test_security_scan_docs.py", "scan_samples.py", "변이", "sha256", "CI 모양"),
    "D-429": ("하지 않은 것", "원복", "D-420–D-429", "엔트로피", "운영자 판단"),
}
UNION_WORDS = ("무시하고 저장", "TOPIC_BACKUP_BLOCKED", "candidates add", "naver-profile set", "GOCSPX-", "NFKC", "카나리", "AKIA", "원복", "T1")
LINE_WORDS = {                    # 보안·구조·변경 이력에서 이 묶음의 줄이 가져야 하는 낱말
    "docs/ARCHITECTURE.md": ("security/scan.py", "D-420–D-429", "scan_secrets", "SecretFinding", "무시하고 저장", "문자열만", "NFKC", "mask.py"),
    "CHANGELOG.md": ("security/scan.py", "D-420–D-429", "scan_secrets", "무시하고 저장", "NFKC", "원복", "PEM"),
}
SECTION_WORDS = ("security/scan.py", "D-420–D-429", "무시하고 저장", "자동으로 지우거나 바꾸지 않아요", "한계", "초안 저장", "전체 백업", "옛 명령줄", "카나리", "NFKC", "mask.py", "shape.py", "AIza", "ghp_", "AKIA", "OpenAI", "쪼갠")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def rows():
    text = read("docs/DECISIONS.md")
    found = {}
    for number in ROW_WORDS:
        lines = [line for line in text.splitlines() if line.startswith(f"| {number} |")]
        found[number] = lines
    return found


def section():
    text = read("docs/SECURITY.md")
    start = text.find("## 본문 속 Secret 형태 검사")
    if start == -1:
        raise AssertionError("보안 문서에 '본문 속 Secret 형태 검사' 절이 없다")
    body = text[start:]
    end = body.find("\n## ", 5)
    return body if end == -1 else body[:end]


class DecisionRowsTest(unittest.TestCase):
    def test_each_decision_row_exists_once_in_order_and_has_five_cells(self):
        found = rows()
        text = read("docs/DECISIONS.md")
        for number, lines in found.items():
            self.assertEqual(len(lines), 1, f"{number} 행은 정확히 한 줄이어야 한다")
            self.assertEqual(len(lines[0].split("|")), 6, f"{number}: 표의 한 행은 칸이 다섯이어야 한다")
            self.assertTrue(lines[0].rstrip().endswith("|"))
        positions = [text.index(f"| {number} |") for number in ROW_WORDS]
        self.assertEqual(positions, sorted(positions), "행은 번호 순서로 있어야 한다")

    def test_each_row_carries_its_own_words(self):
        for number, lines in rows().items():
            for word in ROW_WORDS[number]:
                self.assertIn(word, lines[0], f"{number} 행에 '{word}' 가 없다")
        joined = "\n".join(lines[0] for lines in rows().values())
        for word in UNION_WORDS:
            self.assertIn(word, joined, word)

    def test_rows_have_no_tilde_no_web_address_and_no_unfilled_placeholder(self):
        joined = "\n".join(lines[0] for lines in rows().values())
        self.assertNotIn(TILDE, joined)
        self.assertNotRegex(joined, r"(?i)(https?|ftp)://|www[.]")
        self.assertNotIn("@@", joined)
        for number, lines in rows().items():
            self.assertIn("2026-11-11", lines[0].split("|")[2], number)
            self.assertIn("FIXING", lines[0].split("|")[4], number)

    def test_other_rows_may_mention_the_module_but_this_bundles_rows_are_found_by_number(self):
        text = read("docs/DECISIONS.md") + "\n| D-440 | 2026-11-12 | 다음 묶음이 `security/scan.py` 를 부른다 | 근거 |\n| D-441 | 2026-11-12 | 또 `security/scan.py` 를 말한다 | 근거 |\n"
        mine = [line for line in text.splitlines() if line.startswith("| D-") and "security/scan.py" in line and line.split("|")[1].strip() in ROW_WORDS]
        self.assertEqual([line.split("|")[1].strip() for line in mine], ["D-420", "D-429"], "이 파일 이름을 말하는 이 묶음의 행은 번호로 찾으면 D-420 과 D-429 다 — 다른 묶음의 행은 섞이지 않는다")
        for number in ROW_WORDS:
            self.assertEqual(len([line for line in text.splitlines() if line.startswith(f"| {number} |")]), 1)


class OtherDocsTest(unittest.TestCase):
    def test_the_security_document_has_the_section_with_its_words(self):
        body = section()
        for word in SECTION_WORDS:
            self.assertIn(word, body, word)
        self.assertNotIn(TILDE, body)
        self.assertNotRegex(body, r"(?i)(https?|ftp)://|www[.]")
        self.assertNotIn("@@", body)
        self.assertEqual(body.count("## 본문 속 Secret 형태 검사"), 1)

    def test_the_architecture_and_the_changelog_carry_a_line_of_this_bundle(self):
        for rel, words in LINE_WORDS.items():
            with self.subTest(file=rel):
                lines = [line for line in read(rel).splitlines() if "security/scan.py" in line]
                self.assertGreaterEqual(len(lines), 1, "이 파일 이름을 언급한 줄은 한 줄 이상이다(다른 묶음의 줄이 더 있어도 된다)")
                mine = [line for line in lines if all(word in line for word in words)]
                self.assertEqual(len(mine), 1, f"{rel}: 이 묶음의 줄은 낱말 {words} 를 모두 가진 한 줄이어야 한다")
                self.assertNotIn(TILDE, mine[0])
                self.assertNotRegex(mine[0], r"(?i)(https?|ftp)://|www[.]")
                self.assertNotIn("@@", mine[0])

    def test_the_architecture_line_stays_inside_the_code_layout_section(self):
        text = read("docs/ARCHITECTURE.md")
        mark = text.index("- **본문 속 Secret 형태 검사기**(")
        self.assertLess(text.index("\n## 5. "), mark)
        self.assertLess(mark, text.index("\n## 6. "))


class DocumentedShapesMatchCodeTest(unittest.TestCase):
    def test_the_example_sentences_in_the_documents_are_what_the_code_says(self):
        item = scan.SecretFinding("github_token", "본문", 3, 5, 44)
        sentence = scan.describe(item)
        self.assertEqual(sentence, "본문 3번째 줄에 GitHub 토큰처럼 보이는 글이 있어요")
        self.assertIn(sentence, read("docs/SECURITY.md"))
        fix = scan.summarize([item]).splitlines()[-1]
        self.assertEqual(fix, "해당 줄을 본문에서 지운 뒤 다시 저장해 주세요 — 앱은 자동으로 지우거나 바꾸지 않아요")
        self.assertIn(fix, section())
        self.assertIn("본문에서 2건(GitHub 토큰 1·Google API 키 1) — 3번째 줄·7번째 줄", rows()["D-425"][0])
        two = scan.summarize([scan.SecretFinding("github_token", "본문", 3, 1, 40), scan.SecretFinding("google_api_key", "본문", 7, 1, 39)]).splitlines()[0]
        self.assertEqual(two, "본문에서 2건(GitHub 토큰 1·Google API 키 1) — 3번째 줄·7번째 줄")

    def test_the_prefix_lists_in_the_decision_rows_are_the_prefixes_in_the_code(self):
        row = rows()["D-421"][0]
        aws = re.search(r"\(\?:([A-Z|]+)\)\[A-Z0-9\]\{16\}", scan._AWS.pattern)
        self.assertIsNotNone(aws)
        for prefix in aws.group(1).split("|"):
            self.assertIn(f"`{prefix}`", row, prefix)
        self.assertEqual(len(aws.group(1).split("|")), 8)
        letters = re.search(r"gh\[([a-z]+)\]_", scan._GITHUB.pattern).group(1)
        for letter in letters:
            self.assertIn(f"`gh{letter}_`", row, letter)
        self.assertEqual(len(letters), 5)
        for kind in scan.KINDS:
            self.assertIn(f"`{kind}`", rows()["D-420"][0], kind)

    def test_the_limits_the_security_section_names_are_really_not_found(self):
        import scan_samples as S
        token = S.github()
        for text in (token[:10] + " " + token[10:], token[:10] + "\n" + token[10:], token[:10] + chr(0x200B) + token[10:], "x" + token, "s" + "k-" + S.body(48, S.ALNUM)):
            self.assertEqual(scan.scan_secrets(text), ())
        body = section()
        for needle in ("`U+200B`", "소프트 하이픈", "접두어 앞에 영문·숫자가 붙은 토큰", "OpenAI", "텔레그램 봇", "AWS 비밀 키", "머리 줄만 본다"):
            self.assertIn(needle, body, needle)


if __name__ == "__main__":
    unittest.main()
