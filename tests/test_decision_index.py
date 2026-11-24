"""결정 색인 시험(V1DOCS) — `scripts/gen_decision_index.py` 가 결정 기록(`docs/DECISIONS.md`)에서 만든 `docs/DECISIONS_INDEX.md` 를 지킨다. 네트워크·키 없이 돈다.

지키는 것:
  1) 색인이 낡지 않았다 — 지금 결정 기록에서 다시 만든 글과 올려 둔 색인이 한 글자도 다르지 않다(결정 행을 더하고 색인을 다시 만들지 않은 갈래는 여기서 빨개진다 — 고치는 법은 실패 글에 있다).
  2) 모든 결정 행이 색인에 한 줄씩 있다 — 번호 빠짐·겹침 없음, 번호 순, 날짜가 같다.
  3) 자동으로 만든 한 줄 요약을 **모든 행에서** 점검한다 — 비어 있지 않고, 길이 한계 안이고, 세로줄·물결표·웹 주소·이중 중괄호·마크다운 링크·굵은 표시가 없다.
  4) **자른 곳**이 안전하다 — 줄임표로 끝나는 모든 요약은 원래 요약의 앞부분이고, 띄어쓰기·구분점·여는 괄호 바로 앞에서 끊겼고, 백틱·괄호·따옴표가 열린 채 끊기지 않았다(도구의 자르는 코드와 따로 다시 센다).
  5) 만드는 규칙(굵은 첫머리·짧은 첫머리는 첫 문장·링크 걷기·문서 규칙 글자 바꾸기·등급 읽기·자르기)을 만든 입력으로 확인한다.
  6) 도구가 읽기 전용이다 — 표준 라이브러리만 가져오고, `--check` 는 아무것도 쓰지 않으며, 낡으면 종료 코드 1·결정 기록이 깨졌으면 2, 쓸 때도 색인 한 파일뿐이고 결정 기록은 한 바이트도 안 바뀐다.
  7) 문서가 도구를 안내한다 — README 문서 표·새 PC 안내의 도구 표·AGENTS.md 한 줄.
"""
import ast
import hashlib
import importlib.util
import re
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
        for needle in ("scripts/gen_decision_index.py", "정본은 `docs/DECISIONS.md`"):
            self.assertIn(needle, lines[0], needle)
        self.assertNotIn(TILDE, lines[0])
        self.assertIsNone(URL.search(lines[0]))


if __name__ == "__main__":
    unittest.main()
