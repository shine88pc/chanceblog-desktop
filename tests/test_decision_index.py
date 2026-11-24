"""결정 색인 시험(V1DOCS) — `scripts/gen_decision_index.py` 가 결정 기록(`docs/DECISIONS.md`)에서 만든 `docs/DECISIONS_INDEX.md` 를 지킨다. 네트워크·키 없이 돈다.

지키는 것:
  1) 색인이 낡지 않았다 — 지금 결정 기록에서 다시 만든 글과 올려 둔 색인이 한 글자도 다르지 않다(결정 행을 더하고 색인을 다시 만들지 않은 갈래는 여기서 빨개진다 — 고치는 법은 실패 글에 있다).
  2) 모든 결정 행이 색인에 한 줄씩 있다 — 번호 빠짐·겹침 없음, 번호 순, 날짜가 같다.
  3) 자동으로 만든 한 줄 요약을 **모든 행에서** 점검한다 — 비어 있지 않고, 길이 한계 안이고, 세로줄·물결표·웹 주소·이중 중괄호·마크다운 링크·굵은 표시가 없다.
  4) **자른 곳**이 안전하다 — 줄임표로 끝나는 모든 요약은 원래 요약의 앞부분이고, 띄어쓰기·구분점·여는 괄호 바로 앞에서 끊겼고, 백틱·괄호·따옴표가 열린 채 끊기지 않았다(도구의 자르는 코드와 따로 다시 센다).
  5) 만드는 규칙(굵은 첫머리·짧은 첫머리는 첫 문장·링크 걷기·문서 규칙 글자 바꾸기·등급 읽기·자르기)을 만든 입력으로 확인한다.
  6) 도구가 읽기 전용이다 — 표준 라이브러리만 가져오고, `--check` 는 아무것도 쓰지 않으며, 낡으면 종료 코드 1·결정 기록이 깨졌으면 2, 쓸 때도 색인 한 파일뿐이고 결정 기록은 한 바이트도 안 바뀐다.
  7) 문서가 도구를 안내한다 — README 문서 표·새 PC 안내의 도구 표·AGENTS.md 한 줄.
  8) 출력 가드(재작업 — 검증 S 권고-1·Q R7) — `--out` 이 결정 기록과 같은 파일이면(상대·절대·`..`·링크 이름) 두 모드 다, 이 도구가 만든 색인이 아닌 기존 파일이면 쓸 때 거절하고(종료 코드 2·결정 기록은 한 바이트도
     안 바뀐다), 폴더가 없거나 폴더·없는 파일이어도 오류 글 한 줄로 끝난다(트레이스백 없음).
  9) 만드는 규칙의 경계(재작업 — Q R6·I1) — 헤더의 '가장 최근 날짜'·건너뛴 번호의 시작과 '없음'·등급을 읽는 칸 순서·등급을 읽는 범위·코드 블록 울타리 종류·늘려 주는 한계·자르기 바닥·빈 머리·대괄호 같은 짝·
     대문자 웹 주소·홀수 따옴표를 입력을 만들어 확인한다.
"""
import ast
import contextlib
import hashlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "gen_decision_index.py"
DECISIONS = ROOT / "docs" / "DECISIONS.md"
INDEX = ROOT / "docs" / "DECISIONS_INDEX.md"

TILDE = chr(0x7E)
DOUBLE_OPEN, DOUBLE_CLOSE = "{" * 2, "}" * 2
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
SCHEME = "ht" + "tps://"                  # 소스에도 웹 주소를 글자 그대로 적지 않는다
TABLE_LINE = re.compile(r"^\| (D-\d+) \| (\d{4}-\d{2}-\d{2}) \| (—|T[0-3]) \| (.+) \|$")
DECISION_ROW = re.compile(r"(?m)^\| (D-\d+) \| (\d{4}-\d{2}-\d{2}) \| ")


def load_script():
    spec = importlib.util.spec_from_file_location("gen_decision_index_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GEN = load_script()


def read(path):
    return Path(path).read_text(encoding="utf-8")


def index_lines():
    """색인 표의 줄 → [(번호, 날짜, 등급, 요약), …] (파일에 적힌 순서). 표 모양이 아닌 줄이 끼면 시험이 실패한다."""
    text = read(INDEX)
    assert "\n| 번호 | 날짜 | 등급 | 한 줄 요약 |\n|---|---|---|---|\n" in text, "표 머리가 없다"
    table = text.split("\n| 번호 | 날짜 | 등급 | 한 줄 요약 |\n|---|---|---|---|\n", 1)[1]
    rows = []
    for number, line in enumerate(table.splitlines(), 1):
        match = TABLE_LINE.match(line)
        if not match:
            raise AssertionError(f"색인 표 {number}번째 줄의 모양이 틀렸다: {line[:80]!r}")
        rows.append(match.groups())
    return rows


def balanced(text):
    """백틱이 짝수이고 (), [], 「」, 『』, ‘’, “” 가 모두 짝이 맞고 겹침 순서가 맞는다. (도구의 자르는 코드와 따로 만든 점검이다.)"""
    if text.count("`") % 2:
        return False
    stack, in_code = [], False
    pairs = {")": "(", "]": "[", "」": "「", "』": "『", "’": "‘", "”": "“"}
    for char in text:
        if char == "`":
            in_code = not in_code
        elif in_code:
            continue
        elif char in "([「『‘“":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False
    return not stack


SAMPLE = """# 설계 결정 기록

| 번호 | 날짜 | 결정 | 상태·근거 |
|---|---|---|---|
| D-02 | 2026-10-30 | **둘째 결정은 굵은 첫머리가 충분히 길다.** 뒤따르는 글이다. 변경 등급 T2 로 한다 | 확정 |
| D-01 | 2026-10-29 | **짧다.** 이 행은 첫 문장이 요약이 된다. 둘째 문장이다. | 기본값(운영자 결정 시 변경). T1 — 독립 검증 |
| D-04 | 2026-10-31 | 굵은 첫머리 없이 시작하는 결정이다. 둘째 문장. | 확정 |
| D-05 | 2026-11-01 | **다섯째 결정의 굵은 첫머리도 충분히 길다**(AS-S1 필수-4, T3)이다 | 확정 |

표 밖의 글은 읽지 않는다.
"""


class FreshnessTest(unittest.TestCase):
    def test_the_committed_index_is_exactly_what_the_decision_log_produces(self):
        self.assertEqual(read(INDEX), GEN.expected_text(DECISIONS),
                         "결정 기록(docs/DECISIONS.md)을 고쳤다면 `python scripts/gen_decision_index.py` 로 색인을 다시 만들어 함께 올린다")

    def test_every_decision_row_has_exactly_one_index_line_in_number_order_with_the_same_date(self):
        wanted = sorted(((label, day) for label, day in DECISION_ROW.findall(read(DECISIONS))), key=lambda item: int(item[0][2:]))
        got = [(label, day) for label, day, _grade, _summary in index_lines()]
        self.assertGreater(len(wanted), 500)
        self.assertEqual(len({label for label, _ in wanted}), len(wanted), "결정 기록에 겹치는 번호가 있다")
        self.assertEqual(got, wanted)

    def test_the_head_numbers_match_the_log(self):
        text = read(INDEX)
        labels = [label for label, _day in DECISION_ROW.findall(read(DECISIONS))]
        biggest = max(labels, key=lambda label: int(label[2:]))
        self.assertIn(f"행 {len(labels)}개", text)
        self.assertIn(f"가장 큰 번호 {biggest}", text)
        self.assertTrue(text.startswith("# 결정 색인 (자동 생성 — 직접 고치지 않는다)"))
        self.assertIn("정본은 `DECISIONS.md` 이고 다르면 거기가 이긴다", text)

    def test_the_gap_list_names_exactly_the_missing_numbers(self):
        labels = {int(label[2:]) for label, _day in DECISION_ROW.findall(read(DECISIONS))}
        line = next(row for row in read(INDEX).splitlines() if row.startswith("- 결정 기록에 행이 없는 번호"))
        listed = set()
        self.assertNotIn("D-", line.split(": ", 1)[1], "건너뛴 번호를 'D-81' 꼴로 적으면 문서 시험이 정의되지 않은 결정 번호로 본다")
        for part in line.split(": ", 1)[1].split(", "):
            if part == "없음":
                continue
            first, _dash, last = part.partition("–")
            listed |= set(range(int(first), int(last or first) + 1))
        self.assertEqual(listed, set(range(min(labels), max(labels) + 1)) - labels)


class SummariesOnTheRealLogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = GEN.parse(read(DECISIONS))
        cls.indexed = {label: (grade, summary) for label, _day, grade, summary in index_lines()}

    def test_every_summary_is_filled_short_and_free_of_the_forbidden_characters(self):
        for label, _number, _day, _decision, _status in self.rows:
            summary = self.indexed[label][1]
            with self.subTest(row=label):
                self.assertGreaterEqual(len(summary), 4)
                self.assertLessEqual(len(summary), GEN.SUMMARY_HARD_MAX + 1, "한계를 넘는 요약 — 굵은 첫머리를 줄이거나 도구의 자르는 규칙을 고친다")
                self.assertNotIn(TILDE, summary)
                self.assertIsNone(URL.search(summary))
                self.assertNotIn(DOUBLE_OPEN, summary)
                self.assertNotIn(DOUBLE_CLOSE, summary)
                self.assertNotIn("|", summary)
                self.assertNotIn("**", summary)
                self.assertIsNone(re.search(r"\]\(", summary), "마크다운 링크가 남았다")

    def test_every_cut_summary_was_cut_at_a_safe_place(self):
        cut = 0
        for label, _number, _day, decision, _status in self.rows:
            lead = GEN.lead_of(decision)
            summary = self.indexed[label][1]
            if summary == lead:
                self.assertLessEqual(len(lead), GEN.SUMMARY_HARD_MAX, f"{label}: 자를 안전한 곳이 없어 그대로 둔 긴 요약")
                continue
            cut += 1
            with self.subTest(row=label):
                self.assertTrue(summary.endswith(GEN.ELLIPSIS), "줄였다면 줄임표로 끝난다")
                head = summary[:-1]
                self.assertTrue(lead.startswith(head), "자른 요약은 원래 요약의 앞부분이다")
                self.assertGreater(len(lead), GEN.SUMMARY_LIMIT, "짧은 요약은 자르지 않는다")
                self.assertGreaterEqual(len(head), GEN.SUMMARY_MIN_CUT)
                self.assertLessEqual(len(head), GEN.SUMMARY_HARD_MAX)
                follower = lead[len(head)]
                self.assertTrue(follower in GEN.TRAILING_JUNK + "(", f"낱말 한가운데에서 잘렸다: {head[-12:]!r} + {lead[len(head):len(head) + 6]!r}")
                self.assertNotIn(head[-1], GEN.TRAILING_JUNK, "구분 기호로 끝나게 자르지 않는다")
                self.assertTrue(balanced(head), f"백틱·괄호·따옴표가 열린 채 잘렸다: {head[-30:]!r}")
                for quote in ("'", '"'):
                    if lead.count(quote) % 2 == 0:
                        self.assertEqual(head.count(quote) % 2, 0, f"{quote} 따옴표가 열린 채 잘렸다")
        self.assertGreater(cut, 20, "자르는 경우를 실제로 시험한다")
        self.assertLess(cut, len(self.rows) * 0.25, "너무 많은 요약이 잘린다 — 한계를 점검한다")

    def test_the_grade_column_is_what_the_row_says_and_the_known_rows_are_read(self):
        grades = {label: grade for label, (grade, _summary) in self.indexed.items()}
        self.assertEqual(set(grades.values()) - {"—", "T0", "T1", "T2", "T3"}, set())
        for label, _number, _day, decision, status in self.rows:
            self.assertEqual(grades[label], GEN.grade_of(decision, status), label)
        for label, wanted in (("D-02", "T3"), ("D-28", "T2"), ("D-36", "T0"), ("D-606", "T2"), ("D-611", "T1"), ("D-01", "—"), ("D-20", "—")):
            self.assertEqual(grades[label], wanted, label)
        self.assertGreater(sum(1 for value in grades.values() if value != "—"), 250, "등급을 읽는 행이 줄었다")

    def test_the_summaries_give_a_reader_something_to_search_for(self):
        for label, word in (("D-01", "티스토리"), ("D-11", "핵심 코드"), ("D-343", "PUBPR"), ("D-380", "백업")):
            summary = self.indexed.get(label)
            if summary is not None:
                self.assertIn(word, summary[1], label)
        self.assertIn("D-619", self.indexed)


class RuleTest(unittest.TestCase):
    def test_parse_reads_rows_with_and_without_the_closing_bar_and_skips_the_rest(self):
        rows = GEN.parse(SAMPLE)
        self.assertEqual([row[0] for row in rows], ["D-02", "D-01", "D-04", "D-05"], "파일에 나온 순서 그대로")
        self.assertEqual([row[1] for row in rows], [2, 1, 4, 5])
        self.assertEqual(rows[0][4], "확정")
        self.assertEqual(rows[1][4], "기본값(운영자 결정 시 변경). T1 — 독립 검증", "맨 끝 세로줄이 없어도 같다")

    def test_parse_refuses_broken_logs_instead_of_dropping_rows_silently(self):
        for broken, word in (
            ("| D-1 | 2026-01-01 | **가** | 확정 |\n| D-1 | 2026-01-02 | **나** | 확정 |\n", "겹친"),
            ("| D-1 | 2026-13-45 | **가** | 확정 |\n", "날짜"),
            ("| D-1 | **가** | 확정 |\n", "모양이 틀렸다"),
            ("| D-1 | 2026-01-01 |  | 확정 |\n", "비었다"),
            ("| D-1 | 2026-01-01 | **가** | 확정 |\n```\n| D-2 | 2026-01-01 | **나** | 확정 |\n", "닫히지"),
            ("글만 있다\n", "찾지 못했다"),
        ):
            with self.subTest(broken=broken[:30]):
                with self.assertRaises(GEN.IndexProblem) as caught:
                    GEN.parse(broken)
                self.assertIn(word, str(caught.exception))

    def test_a_row_inside_a_code_block_is_an_example_and_is_not_read(self):
        text = "| D-1 | 2026-01-01 | **진짜 결정이다** | 확정 |\n```text\n| D-2 | 2026-01-01 | **예시** | 확정 |\n```\n"
        self.assertEqual([row[0] for row in GEN.parse(text)], ["D-1"])

    def test_the_last_bar_splits_the_status_and_bars_inside_the_decision_stay_in_the_decision(self):
        self.assertEqual(GEN.split_cells("결정 `a | b` 글 | 확정 |"), ("결정 `a | b` 글", "확정"))
        self.assertEqual(GEN.split_cells("결정만 있다"), ("결정만 있다", ""))

    def test_the_lead_is_the_bold_head_when_it_is_long_enough_otherwise_the_first_sentence(self):
        rows = {row[0]: row for row in GEN.parse(SAMPLE)}
        self.assertEqual(GEN.lead_of(rows["D-02"][3]), "둘째 결정은 굵은 첫머리가 충분히 길다")
        self.assertEqual(GEN.lead_of(rows["D-01"][3]), "짧다. 이 행은 첫 문장이 요약이 된다", "굵은 첫머리가 16자보다 짧으면 이름표일 뿐이라 첫 문장 전체")
        self.assertEqual(GEN.lead_of(rows["D-04"][3]), "굵은 첫머리 없이 시작하는 결정이다")
        self.assertEqual(GEN.lead_of(rows["D-05"][3]), "다섯째 결정의 굵은 첫머리도 충분히 길다")

    def test_the_first_sentence_does_not_end_inside_code_or_brackets(self):
        self.assertEqual(GEN.first_sentence("`a. b` 와 (c. d) 를 본다. 둘째"), "`a. b` 와 (c. d) 를 본다")
        self.assertEqual(GEN.first_sentence("마침표가 없다"), "마침표가 없다")
        self.assertEqual(GEN.first_sentence("버전 3.12 를 쓴다. 다음"), "버전 3.12 를 쓴다")

    def test_tidy_applies_the_document_rules(self):
        raw = f"**굵게** [링크 글자]({SCHEME}example.org/x) 와 5{TILDE}6 과 {SCHEME}example.org/a 그리고 {DOUBLE_OPEN}사진 N{DOUBLE_CLOSE} 와 a|b  끝."
        got = GEN.tidy(raw)
        self.assertEqual(got, "굵게 링크 글자 와 5–6 과 example.org/a 그리고 「사진 N」 와 a/b 끝")
        self.assertNotIn(TILDE, got)
        self.assertIsNone(URL.search(got))
        self.assertNotIn(DOUBLE_OPEN, got)

    def test_shorten_leaves_short_text_alone_and_cuts_long_text_at_the_last_safe_space_inside_the_limit(self):
        short = "가나다 " * 10
        self.assertEqual(GEN.shorten(short.strip()), short.strip())
        long_text = " ".join(["여덟글자낱말입니다"] * 30)
        got = GEN.shorten(long_text)
        self.assertTrue(got.endswith(GEN.ELLIPSIS))
        head = got[:-1]
        self.assertLessEqual(len(head), GEN.SUMMARY_LIMIT)
        self.assertGreater(len(head), GEN.SUMMARY_LIMIT - 12, "한계 안에서 가장 늦은 곳에서 자른다")
        self.assertTrue(long_text.startswith(head) and long_text[len(head)] == " ")

    def test_shorten_never_cuts_inside_code_brackets_or_quotes(self):
        filler = "가" * 30
        for inside in (f"`{filler} {filler} {filler}`", f"({filler} {filler} {filler})", f"「{filler} {filler} {filler}」", f"'{filler} {filler} {filler}'", f'"{filler} {filler} {filler}"'):
            text = f"앞 글 스물네 글자가 넘게 이어지는 첫 부분입니다 {inside} 뒤 글 {filler} 끝"
            got = GEN.shorten(text, limit=60, hard_max=90)
            with self.subTest(inside=inside[:6]):
                head = got[:-1] if got.endswith(GEN.ELLIPSIS) else got
                self.assertTrue(balanced(head), got)
                self.assertTrue(text.startswith(head))
                if got != text:
                    self.assertEqual(head, "앞 글 스물네 글자가 넘게 이어지는 첫 부분입니다", "안쪽 띄어쓰기에서 자르지 않고 그 앞에서 끊는다")

    def test_shorten_can_cut_before_a_bar_dot_or_an_opening_bracket_when_there_is_no_space(self):
        dotted = "·".join(["가나다라마바"] * 20)
        got = GEN.shorten(dotted)
        self.assertTrue(got.endswith(GEN.ELLIPSIS) and not got[:-1].endswith("·"))
        self.assertIn(dotted[len(got) - 1], "·", "구분점 바로 앞에서 끊었다")
        unbreakable = "가" * 200
        self.assertEqual(GEN.shorten(unbreakable), unbreakable, "자를 안전한 곳이 없으면 그대로 둔다(시험이 그런 행을 잡는다)")

    def test_shorten_does_not_leave_a_too_short_head(self):
        text = "가 " + "나" * 150
        self.assertEqual(GEN.shorten(text), text, "앞에 24글자 이상이 남는 곳이 없으면 자르지 않는다")

    def test_the_grade_is_the_first_one_the_row_writes(self):
        self.assertEqual(GEN.grade_of("**가** 변경 등급 T2 — T3 의 일은 따로", ""), "T2")
        self.assertEqual(GEN.grade_of("**가**", "구현·시험 완료(변경 등급 T1)"), "T1")
        self.assertEqual(GEN.grade_of("**가**", "확정. T0 문서 — 구현은 P6(T2)"), "T0")
        self.assertEqual(GEN.grade_of("**나**(AS-S1 필수-4, T2) 이 글", "확정"), "T2")
        self.assertEqual(GEN.grade_of("**나** 설명 · T1 시험만) 끝", "확정"), "—", "괄호 밖의 낱말은 읽지 않는다")
        self.assertEqual(GEN.grade_of("**다** 무료 AI 는 **T0·T1 작은 수정만 직접, T2 는 초안까지**", "확정"), "—", "문장 속에서 등급 낱말을 늘어놓은 글은 읽지 않는다")
        self.assertEqual(GEN.grade_of("**라** 별도 T2 묶음에서", "확정"), "—")
        self.assertEqual(GEN.grade_of("**마** UI-T1 은 이름이다", "UI-T1"), "—", "이름 속의 T1 은 등급이 아니다")
        self.assertEqual(GEN.grade_of("**바**", ""), "—")

    def test_number_ranges_use_en_dashes_and_join_runs(self):
        self.assertEqual(GEN.number_ranges([81, 82, 83, 107, 109, 110]), "81–83, 107, 109–110")
        self.assertEqual(GEN.number_ranges([]), "")
        self.assertNotIn(TILDE, GEN.number_ranges([1, 2, 3]))

    def test_render_orders_by_number_and_is_deterministic(self):
        first = GEN.render(GEN.parse(SAMPLE))
        again = GEN.render(list(reversed(GEN.parse(SAMPLE))))
        self.assertEqual(first, again)
        order = re.findall(r"(?m)^\| (D-\d+) \| \d{4}", first)
        self.assertEqual(order, ["D-01", "D-02", "D-04", "D-05"])
        self.assertIn("행 4개 · 가장 앞 번호 D-01 · 가장 큰 번호 D-05 · 가장 최근 날짜 2026-11-01", first)
        self.assertEqual(first.split("숫자만): ", 1)[1].split("\n", 1)[0], "3")
        self.assertTrue(first.endswith("\n") and not first.endswith("\n\n"))
        self.assertNotIn("\r", first)


class ToolIsReadOnlyTest(unittest.TestCase):
    def test_the_script_imports_only_the_standard_modules_it_needs_and_nothing_that_talks_to_the_outside(self):
        tree = ast.parse(read(SCRIPT), filename=str(SCRIPT), feature_version=(3, 10))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"__future__", "argparse", "datetime", "re", "sys", "pathlib"})
        body = read(SCRIPT)
        for word in ("subprocess", "socket", "urllib", "os.system", "shutil", "remove(", "unlink(", "rmdir"):
            self.assertNotIn(word, body, word)

    def run_main(self, *args):
        completed = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")
        return completed.returncode, completed.stdout, completed.stderr

    def test_check_mode_passes_on_the_repository_and_changes_nothing(self):
        before = (hashlib.sha256(INDEX.read_bytes()).hexdigest(), hashlib.sha256(DECISIONS.read_bytes()).hexdigest())
        code, out, err = self.run_main("--check")
        self.assertEqual(code, 0, err)
        self.assertIn("결정 기록과 같다", out)
        after = (hashlib.sha256(INDEX.read_bytes()).hexdigest(), hashlib.sha256(DECISIONS.read_bytes()).hexdigest())
        self.assertEqual(before, after)

    def test_check_mode_exits_1_on_a_stale_or_missing_index_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            source, out = Path(folder, "DECISIONS.md"), Path(folder, "INDEX.md")
            source.write_text(SAMPLE, encoding="utf-8", newline="\n")
            code, _out, err = self.run_main("--check", "--source", str(source), "--out", str(out))
            self.assertEqual(code, 1, "색인 파일이 없으면 낡은 것이다")
            self.assertIn("다시 만든다", err)
            self.assertFalse(out.exists(), "--check 는 파일을 만들지 않는다")
            out.write_text("낡은 색인\n", encoding="utf-8")
            code, _out, _err = self.run_main("--check", "--source", str(source), "--out", str(out))
            self.assertEqual((code, out.read_text(encoding="utf-8")), (1, "낡은 색인\n"))

    def test_writing_makes_only_the_index_and_a_second_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            source, out = Path(folder, "DECISIONS.md"), Path(folder, "INDEX.md")
            source.write_text(SAMPLE, encoding="utf-8", newline="\n")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            code, stdout, err = self.run_main("--source", str(source), "--out", str(out))
            self.assertEqual(code, 0, err)
            self.assertIn("다시 썼다(4행)", stdout)
            self.assertEqual(sorted(path.name for path in Path(folder).iterdir()), ["DECISIONS.md", "INDEX.md"])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest, "결정 기록은 한 바이트도 바뀌지 않는다")
            self.assertEqual(out.read_text(encoding="utf-8"), GEN.render(GEN.parse(SAMPLE)))
            self.assertNotIn(b"\r", out.read_bytes(), "줄 끝은 LF 로 쓴다")
            code, stdout, _err = self.run_main("--source", str(source), "--out", str(out))
            self.assertEqual((code, stdout.strip()), (0, "바뀐 것이 없다."))
            code, _out, _err = self.run_main("--check", "--source", str(source), "--out", str(out))
            self.assertEqual(code, 0)

    def test_a_broken_decision_log_stops_with_exit_2_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            source, out = Path(folder, "DECISIONS.md"), Path(folder, "INDEX.md")
            source.write_text("| D-1 | 날짜가 아님 | **가** | 확정 |\n", encoding="utf-8")
            code, _out, err = self.run_main("--source", str(source), "--out", str(out))
            self.assertEqual(code, 2)
            self.assertIn("색인을 만들지 못했다", err)
            self.assertFalse(out.exists())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_tool(*args, cwd=None):
    """도구를 새 프로세스로 부른다(실제 명령줄 그대로) → (종료 코드, 표준 출력, 표준 오류)."""
    completed = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8", cwd=cwd)
    return completed.returncode, completed.stdout, completed.stderr


def call_main(*args):
    """같은 일을 이 프로세스 안에서(빠르게) → (종료 코드, 표준 출력, 표준 오류)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = GEN.main(list(args))
    return code, out.getvalue(), err.getvalue()


class OutputGuardTest(unittest.TestCase):
    """정본을 색인으로 덮어쓰지 못하게 막는 가드(검증 S 권고-1·Q R7 — 도구는 '읽기 전용' 이라고 약속하는데 `--out` 을 `--source` 와 같게 주면 1.4MB 정본이 색인으로 바뀌었다)."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.folder), True)
        self.source = self.folder / "DECISIONS.md"
        self.source.write_text(SAMPLE, encoding="utf-8", newline="\n")
        self.digest = digest(self.source)

    def assert_refused(self, code, err, word):
        self.assertEqual(code, 2, err)
        self.assertIn("색인을 만들지 못했다", err)
        self.assertIn(word, err)
        self.assertNotIn("Traceback", err, "처리하지 않은 예외가 아니라 오류 글 한 줄이어야 한다")
        self.assertEqual(digest(self.source), self.digest, "결정 기록은 한 바이트도 바뀌지 않는다")

    def test_the_same_path_is_refused_in_write_mode_and_in_check_mode_without_writing_anything(self):
        for mode in ([], ["--check"]):
            with self.subTest(mode=mode):
                code, out, err = call_main(*mode, "--source", str(self.source), "--out", str(self.source))
                self.assert_refused(code, err, "같은 파일")
                self.assertEqual(out, "", "거절하면서 성공 문구를 내지 않는다")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["DECISIONS.md"])

    def other_names_of_the_decision_log(self):
        """결정 기록을 가리키는 다른 이름들 — 만들 수 있는 것만(심볼릭 링크는 권한이 없으면 못 만든다)."""
        (self.folder / "sub").mkdir()
        names = {"dotdot": self.folder / "sub" / ".." / "DECISIONS.md"}
        for label, make in (("hardlink", os.link), ("symlink", os.symlink)):
            path = self.folder / f"{label}.md"
            try:
                make(str(self.source), str(path))
            except (OSError, NotImplementedError, AttributeError):
                continue
            names[label] = path
        if (self.folder / "decisions.md").exists():                         # 대소문자를 가리지 않는 파일 시스템(윈도·맥)
            names["case"] = self.folder / "decisions.md"
        return names

    def test_every_other_name_of_the_same_file_is_caught_in_both_directions(self):
        names = self.other_names_of_the_decision_log()
        self.assertGreaterEqual(len(names), 3, "별칭을 셋 이상 시험해야 한다(경로 풀기·하드 링크는 어느 환경에서도 만들 수 있다)")
        self.assertIn("dotdot", names)
        for label, alias in names.items():
            for source, out in ((self.source, alias), (alias, self.source)):
                with self.subTest(alias=label, source=source.name, out=out.name):
                    code, _stdout, err = call_main("--source", str(source), "--out", str(out))
                    self.assert_refused(code, err, "같은 파일")
                    code, _stdout, err = call_main("--check", "--source", str(source), "--out", str(out))
                    self.assert_refused(code, err, "같은 파일")
        self.assertEqual(digest(self.source), self.digest)

    def test_a_relative_name_through_the_real_command_line_is_caught_too(self):
        (self.folder / "sub").mkdir()
        code, stdout, err = run_tool("--source", "DECISIONS.md", "--out", "sub/../DECISIONS.md", cwd=str(self.folder))
        self.assert_refused(code, err, "같은 파일")
        self.assertEqual(stdout, "")

    def test_an_existing_file_that_is_not_an_index_is_never_overwritten(self):
        out = self.folder / "OUT.md"
        for label, data, word in (("직접 쓴 글", "내가 직접 쓴 글이다\n".encode("utf-8"), "덮어쓰지 않는다"), ("빈 파일", b"", "덮어쓰지 않는다"),
                                  ("다른 문서", "# 다른 문서\n\n본문\n".encode("utf-8"), "덮어쓰지 않는다"), ("글자가 깨진 파일", b"\xff\xfe\x00\x01", "글자")):
            out.write_bytes(data)
            with self.subTest(file=label):
                code, _stdout, err = call_main("--source", str(self.source), "--out", str(out))
                self.assert_refused(code, err, word)
                self.assertEqual(out.read_bytes(), data, "있던 파일은 한 바이트도 바뀌지 않는다")

    def test_a_missing_file_and_a_stale_index_made_by_the_tool_are_still_written(self):
        fresh = GEN.render(GEN.parse(SAMPLE))
        new_file = self.folder / "NEW.md"
        code, stdout, err = call_main("--source", str(self.source), "--out", str(new_file))
        self.assertEqual((code, new_file.read_text(encoding="utf-8")), (0, fresh), err)
        stale = self.folder / "STALE.md"
        stale.write_text(fresh.replace("D-05", "D-99"), encoding="utf-8", newline="\n")
        code, stdout, err = call_main("--source", str(self.source), "--out", str(stale))
        self.assertEqual((code, stale.read_text(encoding="utf-8")), (0, fresh), err)
        self.assertIn("다시 썼다", stdout)

    def test_a_missing_folder_a_folder_as_the_output_and_a_missing_source_end_with_one_line_not_a_traceback(self):
        cases = (("없는 폴더", ["--source", str(self.source), "--out", str(self.folder / "nope" / "INDEX.md")], "쓰지 못했다"),
                 ("폴더를 출력으로", ["--source", str(self.source), "--out", str(self.folder)], "읽지 못했다"),
                 ("없는 결정 기록", ["--source", str(self.folder / "NONE.md"), "--out", str(self.folder / "INDEX.md")], "읽지 못했다"))
        for label, args, word in cases:
            for mode in ([], ["--check"]):
                if label == "없는 폴더" and mode:
                    continue                                    # --check 는 쓰지 않으므로 없는 폴더는 '없는 색인' 일 뿐이다(종료 코드 1)
                with self.subTest(case=label, mode=mode):
                    code, _stdout, err = call_main(*mode, *args)
                    self.assert_refused(code, err, word)
        self.assertFalse((self.folder / "nope").exists())
        self.assertFalse((self.folder / "INDEX.md").exists())

    def test_the_title_the_guard_looks_for_is_what_the_tool_writes_and_what_is_committed(self):
        self.assertTrue(GEN.HEAD.startswith(GEN.INDEX_TITLE))
        self.assertTrue(GEN.render(GEN.parse(SAMPLE)).startswith(GEN.INDEX_TITLE))
        self.assertTrue(read(INDEX).startswith(GEN.INDEX_TITLE), "올려 둔 색인이 가드가 찾는 첫 줄로 시작하지 않으면 도구가 그 파일을 다시 쓰지 못한다")
        self.assertEqual(GEN.INDEX_TITLE, "# 결정 색인 (자동 생성")


class GeneratorEdgeTest(unittest.TestCase):
    """만드는 규칙의 경계와 틈(재작업 — 검증 Q R6·I1: 실제 결정 기록으로는 드러나지 않고 앞으로 행이 더해지면 드러날 곳)을 입력을 만들어 못박는다."""

    def test_the_head_names_the_latest_date_not_the_date_of_the_biggest_number(self):
        text = ("| D-01 | 2026-12-01 | **번호는 작지만 날짜가 가장 늦은 결정이다** | 확정 |\n"
                "| D-02 | 2026-10-01 | **번호는 크지만 날짜가 이른 결정이다 둘째** | 확정 |\n")
        head = GEN.render(GEN.parse(text))
        self.assertIn("가장 앞 번호 D-01 · 가장 큰 번호 D-02 · 가장 최근 날짜 2026-12-01", head)

    def test_the_gap_list_starts_at_the_first_number_of_the_log_and_says_none_when_there_is_no_gap(self):
        def gaps(*numbers):
            rows = "".join(f"| D-{n:02d} | 2026-11-0{n % 9 + 1} | **{n}번째 결정의 굵은 첫머리가 충분히 길다** | 확정 |\n" for n in numbers)
            return GEN.render(GEN.parse(rows)).split("숫자만): ", 1)[1].split("\n", 1)[0]

        self.assertEqual(gaps(5, 7), "6", "건너뛴 번호는 가장 앞 번호부터 센다(1 부터가 아니다)")
        self.assertEqual(gaps(5, 6, 7), "없음")
        self.assertEqual(gaps(3, 4, 9, 12, 13), "5–8, 10–11")

    def test_the_decision_cell_is_read_before_the_status_cell_and_the_longer_phrase_before_the_shorter(self):
        self.assertEqual(GEN.grade_of("**가** 변경 등급 T1 로 한다", "확정 변경 등급 T2"), "T1", "같은 표기가 두 칸에 있으면 결정 칸이 먼저")
        self.assertEqual(GEN.grade_of("**가** 등급 T0 로 한다", "확정 등급 T3"), "T0")
        self.assertEqual(GEN.grade_of("**가** 등급 T3 로 본다", "확정 변경 등급 T1"), "T1", "'변경 등급' 표기가 칸에 상관없이 '등급' 표기보다 앞선다")
        self.assertEqual(GEN.grade_of("**가** 설명", "구현 완료. T2 — 독립 검증"), "T2", "표기 말이 없어도 상태 칸의 T 낱말은 읽는다")

    def test_the_grade_in_the_head_of_the_decision_is_read_only_inside_the_first_300_characters(self):
        for filler, wanted in ((250, "T2"), (320, "—")):
            with self.subTest(filler=filler):
                self.assertEqual(GEN.grade_of("**가**" + "가" * filler + "(AS-S1, T2) 끝", ""), wanted)
        self.assertEqual(GEN.grade_of("**가**(AS-S1, T2— 설명)", ""), "T2", "등급 바로 뒤의 줄표(—)도 끝 표시다")

    def test_a_fence_line_of_the_other_kind_inside_a_code_block_does_not_close_it(self):
        text = ("| D-1 | 2026-01-01 | **진짜 결정이다 첫째** | 확정 |\n```text\n" + TILDE * 3 + "\n| D-2 | 2026-01-01 | **예시이다 둘째** | 확정 |\n```\n"
                "| D-3 | 2026-01-01 | **진짜 결정이다 셋째** | 확정 |\n")
        self.assertEqual([row[0] for row in GEN.parse(text)], ["D-1", "D-3"], "``` 로 연 블록은 ``` 로만 닫는다")

    def test_the_cut_floor_is_exactly_24_characters_and_the_stretch_limit_exactly_140(self):
        self.assertEqual(GEN.shorten("가" * 24 + " " + "나" * 100), "가" * 24 + GEN.ELLIPSIS, "앞에 24글자가 남는 띄어쓰기는 자를 수 있다")
        self.assertEqual(GEN.shorten("가" * 23 + " " + "나" * 100), "가" * 23 + " " + "나" * 100, "23글자만 남기는 곳은 자르지 않는다")
        self.assertEqual(GEN.shorten("가" * 120 + " " + "나" * 30), "가" * 120 + GEN.ELLIPSIS, "100자 안에 안전한 곳이 없으면 140자 안의 가장 이른 곳까지 늘려 준다")
        self.assertEqual(GEN.shorten("가" * 141 + " " + "나" * 10), "가" * 141 + " " + "나" * 10, "140자 밖은 늘려 주지 않는다")

    def test_a_head_that_is_only_separators_is_not_turned_into_an_ellipsis(self):
        text = "·" * 30 + "가" * 100
        self.assertEqual(GEN.shorten(text), text)

    def test_shorten_never_cuts_inside_square_brackets_double_corners_curly_quotes_or_braces(self):
        filler = "가" * 30
        prefix = "앞 글 스물네 글자가 넘게 이어지는 첫 부분입니다"
        for opener, closer in (("[", "]"), ("『", "』"), ("‘", "’"), ("“", "”"), ("{", "}")):
            text = f"{prefix} {opener}{filler} {filler} {filler}{closer} 뒤 글 {filler} 끝"
            got = GEN.shorten(text, limit=60, hard_max=90)
            with self.subTest(opener=opener):
                self.assertEqual(got, prefix + GEN.ELLIPSIS, "안쪽 띄어쓰기에서 자르지 않고 그 앞에서 끊는다")

    def test_an_odd_number_of_straight_quotes_is_an_apostrophe_and_does_not_block_later_cuts(self):
        text = "첫 부분 글자가 스물네 글자를 넘는 설명이다 it's " + " ".join(["가나다라마"] * 30)
        got = GEN.shorten(text)
        self.assertTrue(got.endswith(GEN.ELLIPSIS))
        self.assertGreater(len(got), text.index("'") + 20, "아포스트로피 하나 때문에 그 앞에서 잘리면 안 된다")

    def test_a_capitalised_web_address_scheme_is_removed_like_the_lower_case_one(self):
        got = GEN.tidy(f"{SCHEME.upper()}Example.org/a 와 {SCHEME[:-3].capitalize()}://x.y")
        self.assertEqual(got, "Example.org/a 와 x.y")
        self.assertIsNone(URL.search(got))


class DocsPointToTheToolTest(unittest.TestCase):
    def test_the_readme_documents_table_lists_the_index_and_the_links_resolve(self):
        readme = read(ROOT / "README.md")
        row = next(line for line in readme.splitlines() if "docs/DECISIONS_INDEX.md" in line and line.startswith("| "))
        self.assertTrue(row.rstrip().endswith("|") and row.count(" | ") == 1, row)
        self.assertNotIn(TILDE, row)
        self.assertIsNone(URL.search(row))
        self.assertTrue((ROOT / "docs" / "DECISIONS_INDEX.md").is_file())

    def test_the_new_pc_guide_tool_table_names_the_generator_and_agents_md_has_one_line_about_the_index(self):
        migration = read(ROOT / "docs" / "MIGRATION.md")
        tools = migration.split("### 6-4.")[1].split("### 6-5.")[0]
        self.assertIn("`scripts/gen_decision_index.py`", tools)
        self.assertIn("[`DECISIONS_INDEX.md`](DECISIONS_INDEX.md)", tools)
        agents = read(ROOT / "AGENTS.md")
        lines = [line for line in agents.splitlines() if "DECISIONS_INDEX.md" in line]
        self.assertEqual(len(lines), 1, "AGENTS.md 에는 결정 색인 안내 한 줄뿐이다")
        for needle in ("scripts/gen_decision_index.py", "정본은 `docs/DECISIONS.md`", "병합 충돌이 나면 색인 파일을 손으로 합치지 말고 한쪽을 고른 뒤 같은 명령으로 다시 만든다"):
            self.assertIn(needle, lines[0], needle)
        self.assertIn("같은 파일이거나 이 도구가 만든 색인이 아닌 기존 파일이면 쓰지 않고 거절한다", tools, "도구 표가 출력 가드를 알린다")
        self.assertNotIn(TILDE, lines[0])
        self.assertIsNone(URL.search(lines[0]))


if __name__ == "__main__":
    unittest.main()
