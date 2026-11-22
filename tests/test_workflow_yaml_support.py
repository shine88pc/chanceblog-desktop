"""`tests/workflow_yaml_support.py`(워크플로 글을 구조로 읽는 작은 읽개)의 시험 — 독립 검증 S 의 SP-2·Q 의 QP-3 반영: 워크플로 규칙 검사가 금지 낱말 찾기만 하면 한 줄 흐름식·키 끼워 넣기 같은 다른 표기로 피해 간다.
그래서 시험이 글을 '구조'로 읽는데 PyYAML 이 앱 CI 에 없으므로 이 읽개를 쓴다. 지키는 것: 쓰는 표기(블록 매핑·목록·따옴표·블록 글·주석)는 바르게 읽고, **읽지 않는 표기는 모두 거절**한다(거절이 숨는 길을 막는다)."""
import sys
import time
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_yaml_support as yamlsub  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "package-ocr.yml"


def load(text):
    return yamlsub.load(text)


class ReadsWhatTheWorkflowsUseTest(unittest.TestCase):
    def test_blocks_scalars_comments_and_nested_lists_are_read(self):
        text = """# 머리 주석
name: "이름 — 따옴표"
on:
  workflow_dispatch:

permissions:
  contents: read   # 뒤쪽 주석
jobs:
  one:
    steps:
      # 단계 앞 주석
      - uses: a/b@0123456789012345678901234567890123456789  # v1
        with:
          flag: false
      - name: 둘째 단계(괄호·쉼표, 가운데점·포함)
        run: echo "hi" && echo $env:X
"""
        self.assertEqual(load(text), {"name": "이름 — 따옴표", "on": {"workflow_dispatch": None}, "permissions": {"contents": "read"},
                                      "jobs": {"one": {"steps": [{"uses": "a/b@0123456789012345678901234567890123456789", "with": {"flag": "false"}},
                                                                 {"name": "둘째 단계(괄호·쉼표, 가운데점·포함)", "run": 'echo "hi" && echo $env:X'}]}}})

    def test_values_are_always_text_and_an_empty_value_is_none(self):
        self.assertEqual(load("a: true\nb: 45\nc:\nd: ''\ne: '1'\nf: 3.12\n"), {"a": "true", "b": "45", "c": None, "d": "", "e": "1", "f": "3.12"})

    def test_a_list_at_the_same_indent_as_its_key_is_read_and_a_scalar_list_too(self):
        self.assertEqual(load("a:\n- x\n- y: 1\n  z: 2\nb:\n  - p\n  - q\n"), {"a": ["x", {"y": "1", "z": "2"}], "b": ["p", "q"]})

    def test_quoted_values_and_keys(self):
        self.assertEqual(load("""'on': 1\n"k": 'it''s'\nm: "tab\\tquote\\"slash\\\\"\nn: "a # b"\no: 'x' # 주석\n"""),
                         {"on": "1", "k": "it's", "m": 'tab\tquote"slash\\', "n": "a # b", "o": "x"})

    def test_block_text_keeps_lines_comments_inside_it_and_obeys_the_chomp_marks(self):
        text = "a: |\n  one\n  # not a comment\n    deeper\n\n  two\n\nb: |-\n  x\nc: |+\n  y\n\nd: z\n"
        tree = load(text)
        self.assertEqual(tree["a"], "one\n# not a comment\n  deeper\n\ntwo\n")
        self.assertEqual(tree["b"], "x")
        self.assertEqual(tree["c"], "y\n\n")
        self.assertEqual(tree["d"], "z")

    def test_crlf_and_trailing_spaces_do_not_change_the_result(self):
        text = "a:\n  b: c   \n  d:\n    - e\n"
        self.assertEqual(load(text.replace("\n", "\r\n")), load(text))

    def test_an_empty_document_and_a_comment_only_document_are_none(self):
        self.assertIsNone(load(""))
        self.assertIsNone(load("# 주석뿐\n\n"))

    def test_the_real_workflow_is_read_into_the_expected_shape(self):
        tree = load(WORKFLOW.read_text(encoding="utf-8"))
        self.assertEqual(list(tree), ["name", "on", "permissions", "concurrency", "jobs"])
        self.assertEqual((tree["on"], tree["permissions"]), ({"workflow_dispatch": None}, {"contents": "read"}))
        steps = tree["jobs"]["package-ocr"]["steps"]
        self.assertEqual(len(steps), 11)
        self.assertEqual([("uses" in step) for step in steps], [True, True] + [False] * 8 + [True])
        self.assertEqual(steps[-1]["with"]["path"].count("\n"), 3, "블록 글 세 줄")


class RefusesWhatItDoesNotReadTest(unittest.TestCase):
    def test_every_notation_it_does_not_read_is_refused(self):
        cases = (
            ("흐름식 매핑 값", "a: {b: c}\n"), ("흐름식 목록 값", "on: [push, workflow_dispatch]\n"), ("흐름식 단계", "steps:\n  - {run: \"echo 1\"}\n"), ("흐름식 uses 단계", "steps:\n  - {uses: x/y@v1}\n"),
            ("흐름식 목록 항목", "a:\n  - [1, 2]\n"), ("앵커", "a: &x 1\n"), ("별칭", "a: *x\n"), ("태그", "a: !!str 1\n"), ("병합 키", "a:\n  <<: x\n"), ("물음표 복합 키", "? a\n: b\n"),
            ("여러 문서(처음)", "---\na: 1\n"), ("여러 문서(중간)", "a: 1\n---\nb: 2\n"), ("문서 끝 표시", "a: 1\n...\n"), ("탭 들여쓰기", "a:\n\tb: 1\n"), ("탭이 첫 글자", "a: 1\n\tb: 2\n"),
            ("겹친 키(위)", "a: 1\na: 2\n"), ("겹친 키(안)", "a:\n  b: 1\n  b: 2\n"), ("겹친 키(따옴표 키와 맨 키)", "a: 1\n'a': 2\n"), ("접은 글", "a: >\n  x\n"), ("들여쓰기 숫자 블록", "a: |2\n  x\n"),
            ("한 줄을 넘는 글 값", "a: first\n  second\n"), ("따옴표 안 닫힘", "a: 'x\n"), ("큰따옴표 안 닫힘", 'a: "x\n'), ("따옴표 뒤 다른 글", "a: 'x' y\n"), ("읽지 않는 이스케이프", 'a: "\\x41"\n'),
            ("목록 안의 목록", "a:\n  - - 1\n"), ("키 없는 글 줄", "a: 1\njust text\n"), ("값 안의 키: 값", "a: b: c\n"), ("값 끝의 콜론", "a: b:\n"), ("값 자리의 목록 표시", "a: - b\n"),
            ("들여쓰기 어긋남(깊어짐)", "a:\n  b: 1\n    c: 2\n"), ("들여쓰기 어긋남(얕아짐)", "a:\n    b: 1\n  c: 2\n"), ("예약 글자 시작", "a: @x\n"), ("백틱 시작", "a: `x\n"), ("퍼센트 시작", "a: %x\n"),
            ("BOM", "\ufeffa: 1\n"), ("NUL", "a: 1\x00\n"), ("홀로 CR", "a: 1\rb: 2\n"), ("목록 항목의 블록 글", "a:\n  - |\n    x\n"),
        )
        for label, text in cases:
            with self.subTest(case=label):
                with self.assertRaises(yamlsub.YamlSubsetError):
                    load(text)

    def test_the_error_message_names_the_line_and_the_reason(self):
        with self.assertRaises(yamlsub.YamlSubsetError) as caught:
            load("a: 1\nb: {c: d}\n")
        self.assertIn("2번째 줄", str(caught.exception))
        self.assertIn("흐름식", str(caught.exception))

    def test_a_flow_style_step_hidden_in_the_real_workflow_is_refused(self):
        text = WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")
        anchor = "      - uses: actions/setup-python@"
        self.assertEqual(text.count(anchor), 1)
        hidden = text.replace(anchor, '      - {run: "echo ${{ github.event.head_commit.message }}"}\n' + anchor)
        with self.assertRaises(yamlsub.YamlSubsetError):
            load(hidden)


class RefusesLineBreakLookAlikesAndInvisibleCharactersTest(unittest.TestCase):
    """독립 검증 S 의 SP-6(필수): U+0085·U+2028·U+2029 는 YAML 파서(PyYAML 같은 libyaml 계열)가 줄 나눔으로 읽는데 이 읽개는 줄 바꿈 글자만으로 줄을 나눠서, 주석 줄이나 name 칸에 이 글자와 함께 숨긴 단계를
    규칙 검사가 못 봤다. 줄 나눔처럼 읽힐 수 있거나 보이지 않는 글자는 글 어디에 있든(주석·name·키·따옴표 글·블록 글 안까지) 거절한다."""

    LINE_BREAKS = (0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x1F, 0x85, 0x2028, 0x2029)
    INVISIBLE = (0x09, 0x7F, 0xAD, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2060, 0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF, 0xE000, 0xF8FF)
    PLACES = (("주석 줄", "# 설명{c}숨긴 글\nname: x\n"), ("뒤쪽 주석", "name: x  # 주석{c}뒤\n"), ("name 값", "name: 가{c}나\n"), ("따옴표 값", "name: '가{c}나'\n"), ("큰따옴표 값", 'name: "가{c}나"\n'),
              ("키 안", "na{c}me: x\n"), ("블록 글", "a: |\n  줄{c}속\n"), ("목록 항목", "a:\n  - 가{c}나\n"), ("맨 앞", "{c}name: x\n"), ("끝 주석 줄", "name: x\n# 끝{c}\n"), ("들여쓴 주석", "a:\n  # 안쪽{c}주석\n  b: 1\n"))

    def test_line_break_look_alikes_and_invisible_characters_are_refused_in_every_place(self):
        for code in self.LINE_BREAKS + self.INVISIBLE:
            for label, template in self.PLACES:
                with self.subTest(character=hex(code), place=label):
                    with self.assertRaises(yamlsub.YamlSubsetError):
                        load(template.replace("{c}", chr(code)))

    def test_every_line_boundary_python_knows_is_refused_and_the_list_has_no_gap(self):
        """파이썬이 줄 나눔으로 보는 글자는 모두 거절한다(줄 바꿈 글자 하나만 빼고) — 목록에 빠진 글자가 없다는 것을 파이썬 자신의 기준으로 확인한다."""
        boundaries = [code for code in range(0x110000) if len(("a" + chr(code) + "b").splitlines()) == 2]
        self.assertEqual(boundaries, [0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029])
        for code in boundaries:
            if code == 0x0A:
                continue
            with self.subTest(character=hex(code)):
                with self.assertRaises(yamlsub.YamlSubsetError):
                    load("# x" + chr(code) + "- run: evil\nname: x\n")

    def test_every_control_format_separator_and_private_use_character_is_refused(self):
        refused = {"Cc", "Cf", "Zl", "Zp"}
        samples = [code for code in range(0x110000) if unicodedata.category(chr(code)) in refused and code != 0x0A]
        samples += [0xE000, 0xF8FF, 0xF0000, 0xFFFFD, 0x100000, 0x10FFFD]                     # 사설 영역(Co)은 범위의 처음과 끝
        self.assertGreater(len(samples), 200)
        for code in samples:
            try:
                load("# x" + chr(code) + "y\nname: z\n")
            except yamlsub.YamlSubsetError:
                continue
            self.fail("읽개가 거절하지 않은 글자 U+%04X" % code)

    def test_the_message_names_the_line_and_the_character_code(self):
        with self.assertRaises(yamlsub.YamlSubsetError) as caught:
            load("a: 1\n# 숨김" + chr(0x2028) + "끝\n")
        self.assertIn("2번째 줄", str(caught.exception))
        self.assertIn("U+2028", str(caught.exception))

    def test_ordinary_text_the_real_workflow_uses_is_still_read(self):
        text = "name: 한글 이름 — 줄표·가운뎃점·말줄임표…·화살표→·곱하기×\n# 주석 — 한글과 ·\nrun: 'x'\n"
        self.assertEqual(load(text), {"name": "한글 이름 — 줄표·가운뎃점·말줄임표…·화살표→·곱하기×", "run": "x"})
        self.assertEqual(load("name: a" + chr(0xA0) + "b\n"), {"name": "a" + chr(0xA0) + "b"}, "줄 나눔도 보이지 않는 글자도 아닌 보통 공백류는 막지 않는다")


class RefusesInputThatIsTooLongOrTooDeepTest(unittest.TestCase):
    """독립 검증 S 의 참고 SN-16: 값 안의 긴 공백 줄에서 제곱 시간이 걸리고(공백 8만 칸 11.8초) 깊은 중첩에서 RecursionError 가 났다 — 입력 길이·깊이에 상한을 두어 YamlSubsetError 로 빠르게 거절한다."""

    def refused_fast(self, text):
        started = time.time()
        with self.assertRaises(yamlsub.YamlSubsetError):
            load(text)
        self.assertLess(time.time() - started, 2.0, "빨리 거절해야 한다")

    def test_a_very_long_line_is_refused_fast_even_when_it_is_only_spaces(self):
        self.refused_fast("a: b" + " " * 80000 + "c\n")
        self.refused_fast("a: b" + " " * 80000 + "# c\n")
        self.refused_fast("# " + "x" * 5000 + "\na: 1\n")
        self.refused_fast("a: " + "y" * 5000 + "\n")

    def test_a_very_long_text_is_refused(self):
        self.refused_fast("\n".join("k%d: v" % number for number in range(30000)) + "\n")

    def test_deep_nesting_is_refused_with_the_reader_error_not_a_recursion_error(self):
        mapping = "".join(" " * level + "k%d:\n" % level for level in range(400)) + " " * 400 + "v: 1\n"
        self.refused_fast(mapping)
        sequence = "".join(" " * (2 * level) + "- k%d:\n" % level for level in range(200))
        self.refused_fast(sequence)

    def test_the_real_sizes_stay_far_below_the_limits(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        lines = text.replace("\r\n", "\n").split("\n")
        self.assertLess(max(len(line) for line in lines), yamlsub.MAX_LINE // 2)
        self.assertLess(len(text), yamlsub.MAX_TEXT // 10)
        self.assertGreaterEqual(yamlsub.MAX_DEPTH, 12)

    def test_the_comment_cutting_is_linear(self):
        started = time.time()
        self.assertEqual(yamlsub.strip_comment("value" + " " * 60000 + "tail"), "value" + " " * 60000 + "tail")      # 옛 정규식은 공백 6만 칸에 6초 넘게 걸렸다
        self.assertEqual(yamlsub.strip_comment("value   # note"), "value")
        self.assertEqual(yamlsub.strip_comment("a#b c"), "a#b c")
        self.assertLess(time.time() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
