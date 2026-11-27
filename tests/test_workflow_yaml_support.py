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

    def test_each_refusal_names_its_own_reason(self):
        """독립 검증 Q 의 R04·R06·R07·R08: 거절 검사 하나를 꺼도 뒤의 다른 검사(키 모양·보이지 않는 글자 범주)가 같은 글을 거절해서 시험이 통과했다 — 거절 문장이 그 검사의 이유를 말하는지까지 못박는다."""
        bs = chr(0x5C)
        cases = (("a:\n  <<: x\n", "병합 키"), ("a: &x 1\n", "앵커·별칭·태그"), ("a: *x\n", "앵커·별칭·태그"), ("a: !!str 1\n", "앵커·별칭·태그"), ("a:\n\tb: 1\n", "탭 들여쓰기"), (chr(0xFEFF) + "a: 1\n", "BOM"), ("a: 1\x00\n", "NUL"),
                 ("a: 1\rb: 2\n", "홀로 CR"), ("a: 1\na: 2\n", "같은 키"), ("a:\n  b: 1\n  b: 2\n", "같은 키"), ("a: >\n  x\n", "접은 글"), ("a: {b: c}\n", "흐름식"), ("a: |2\n  x\n", "들여쓰기 숫자"), ("a: 'x\n", "닫히지 않는다"),
                 ("a:\n  - - 1\n", "목록 안의 목록"), ("a: b: c\n", "키: 값"), ("a: - b\n", "목록 표시"), ("a: " + "x" * 1001 + "\n", "너무 길다"), ("a:\n  - |\n    x\n", "블록 글"), ('a: "' + bs + 'x41"\n', "이스케이프"),
                 ("a: b" + bs + " \n", "역슬래시"))
        for text, reason in cases:
            with self.subTest(reason=reason, text=text[:20]):
                with self.assertRaises(yamlsub.YamlSubsetError) as caught:
                    load(text)
                self.assertIn(reason, str(caught.exception))

    def test_a_folded_block_marker_is_refused_even_with_nothing_or_a_sibling_key_after_it(self):
        """독립 검증 Q 의 R10: `a: >` 는 뒤에 들여쓴 줄이 이어지면 들여쓰기 오류로도 거절돼서 `>` 거절 자체를 꺼도 시험이 통과했다 — 이어지는 글이 없거나 같은 층 키가 이어져 YAML 에서는 빈 접은 글이 되는 모양도 읽개는 거절한다."""
        for text in ("a: >\n", "a: >\nb: 1\n", "a: >-\n  x\n", "a: >+\nb: 1\n", "a: > x\n", "a: >2\n  x\n", "a:\n  b: >\n  c: 1\n"):
            with self.subTest(text=text):
                with self.assertRaises(yamlsub.YamlSubsetError) as caught:
                    load(text)
                self.assertIn("접은 글", str(caught.exception))

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


class ReadsOnlyTheExactEmptyFlowValuesTest(unittest.TestCase):
    """릴리스 워크플로(R-3, 운영자 확인 048 ①, 결정 D-880)의 최상위 `permissions: {}`(전부 차단)를 읽으려고 **값 자리의 정확히 `{}` 와 `[]`** 만 빈 매핑·빈 목록으로 읽는다 — 이것이 읽개를 약하게 하지 않도록
    그 밖의 흐름식(`{a: 1}`·`[1]`·`{ }`·`{}x` …)은 위 거절 목록과 똑같이 그대로 거절하고, 목록 항목 자리의 `- {}`·`- []`·키 자리·문서 맨 위의 `{}` 도 계속 거절한다."""

    def test_an_exact_empty_mapping_and_an_exact_empty_list_are_read_in_a_value_place(self):
        self.assertEqual(load("a: {}\n"), {"a": {}})
        self.assertEqual(load("a: []\n"), {"a": []})
        self.assertEqual(load("permissions: {}\njobs:\n  one: x\n"), {"permissions": {}, "jobs": {"one": "x"}})
        self.assertEqual(load("outer:\n  b: {}\n  c: []\n  d: z\n"), {"outer": {"b": {}, "c": [], "d": "z"}})
        self.assertEqual(load("a:\n  - k: {}\n    m: []\n"), {"a": [{"k": {}, "m": []}]}, "목록 항목 안의 매핑에서도 값 자리다")

    def test_the_results_are_a_mapping_and_a_list_and_not_the_none_or_text_an_empty_value_gives(self):
        tree = load("a: {}\nb: []\nc:\nd: ''\ne: '{}'\nf: '[]'\n")
        self.assertEqual(tree["a"], {})
        self.assertIsInstance(tree["a"], dict)
        self.assertEqual(tree["b"], [])
        self.assertIsInstance(tree["b"], list)
        self.assertIsNone(tree["c"])
        self.assertEqual((tree["d"], tree["e"], tree["f"]), ("", "{}", "[]"), "따옴표 글 '{}' 은 글 그대로다")
        self.assertIsNot(load("a: {}\n")["a"], load("a: {}\n")["a"], "읽을 때마다 새 객체다(공유되어 고쳐지지 않는다)")

    def test_a_comment_after_a_space_may_follow_but_nothing_else_may(self):
        self.assertEqual(load("a: {}   # 전부 차단\n"), {"a": {}})
        self.assertEqual(load("a: []  # 비었다\n"), {"a": []})
        for text in ("a: {}#x\n", "a: []#x\n", "a: {} x\n", "a: [] x\n", "a: {}x\n", "a: []x\n", "a: {}}\n", "a: []]\n", "a: {}{}\n", "a: [][]\n", "a: {},\n", "a: [],\n", "a: {}:\n", "a: {} : 1\n"):
            with self.subTest(text=text):
                with self.assertRaises(yamlsub.YamlSubsetError):
                    load(text)

    def test_every_other_flow_expression_is_still_refused(self):
        cases = (("안이 있는 매핑", "a: {a: 1}\n"), ("안이 있는 목록", "a: [1]\n"), ("공백이 든 빈 매핑", "a: { }\n"), ("공백이 든 빈 목록", "a: [ ]\n"), ("빈 매핑 뒤 글", "a: {}x\n"), ("빈 목록 뒤 글", "a: []x\n"),
                 ("겹친 빈 목록", "a: [[]]\n"), ("겹친 빈 매핑", "a: {{}}\n"), ("빈 매핑 속 빈 목록", "a: {[]}\n"), ("한 줄 목록", "on: [push, workflow_dispatch]\n"), ("닫히지 않은 매핑", "a: {\n"), ("닫히지 않은 목록", "a: [\n"),
                 ("키 자리의 빈 매핑", "{}: 1\n"), ("문서 맨 위의 빈 매핑", "{}\n"), ("문서 맨 위의 빈 목록", "[]\n"), ("목록 항목의 빈 매핑", "a:\n  - {}\n"), ("목록 항목의 빈 목록", "a:\n  - []\n"),
                 ("목록 항목 안 매핑의 흐름식 값", "a:\n  - k: {x: 1}\n"), ("흐름식 단계", "steps:\n  - {run: x}\n"))
        for label, text in cases:
            with self.subTest(case=label):
                with self.assertRaises(yamlsub.YamlSubsetError):
                    load(text)

    def test_the_refusal_message_still_names_the_line_and_the_flow_expression(self):
        with self.assertRaises(yamlsub.YamlSubsetError) as caught:
            load("a: {}\nb: {c: d}\n")
        self.assertIn("2번째 줄", str(caught.exception))
        self.assertIn("흐름식", str(caught.exception))

    def test_a_block_text_and_a_comment_that_merely_contain_braces_are_untouched(self):
        self.assertEqual(load("run: |\n  echo {}\n  echo []\n"), {"run": "echo {}\necho []\n"})
        self.assertEqual(load("a: 1  # {}\n"), {"a": "1"})
        self.assertEqual(load("a: x{}\nb: y[]\n"), {"a": "x{}", "b": "y[]"}, "글 한가운데의 중괄호는 흐름식이 아니라 평범한 글이다 — 값의 맨 앞 글자만 흐름식 표시다")

    def test_a_workflow_shaped_text_with_the_blocking_top_level_permissions_is_read_into_the_expected_shape(self):
        text = "name: x\non:\n  workflow_dispatch:\npermissions: {}\njobs:\n  one:\n    permissions:\n      contents: read\n    steps:\n      - run: echo hi\n"
        tree = load(text)
        self.assertEqual(tree["permissions"], {})
        self.assertEqual(tree["jobs"]["one"]["permissions"], {"contents": "read"})
        self.assertEqual(tree["on"], {"workflow_dispatch": None})


ZS_CHARACTERS = [chr(code) for code in range(0x110000) if unicodedata.category(chr(code)) == "Zs" and code != 0x20]      # NBSP·U+1680·U+2000에서 U+200A·U+202F·U+205F·U+3000 — YAML 에서는 공백이 아니라 값의 일부인 글자들


class KeepsUnicodeSpacesAndRefusesBackslashSpaceAtLineEndTest(unittest.TestCase):
    """독립 검증 S 의 S-1(필수, 결정 D-887): 읽개가 줄 끝·값 앞뒤의 유니코드 공백(NBSP·U+2003·U+3000·U+202F …)까지 잘라서 모든 못박은 값이 보이지 않는 글자 하나로 시험을 통과했다 —
    YAML(과 PyYAML)에서 이 글자들은 값의 일부라 `environment: release` 뒤의 NBSP 는 GitHub 에서 다른 환경 이름이다. 줄 끝에서는 ASCII 공백만 자르고, 그러면 값에 남기거나 읽을 수 없는 줄로 거절한다.
    같은 뿌리의 둘째: 줄 끝의 역슬래시 뒤 ASCII 공백은 셸에서 줄 이음이 아닌데 공백을 지우는 읽개에는 줄 이음으로 보였다."""

    BS = chr(0x5C)

    def test_the_space_like_characters_the_reader_accepts_are_exactly_the_Zs_ones(self):
        """파이썬 `str.strip()` 이 자르는 글자 중 읽개가 따로 거절하지 않는 것은 범주 Zs 뿐이다 — 이 시험이 빠진 칸이 없음을 파이썬 자신의 기준으로 보인다."""
        gap = []
        for code in range(0x110000):
            ch = chr(code)
            if ch.isspace() and code not in (0x0A, 0x20) and ch not in yamlsub.LINE_BREAKS and unicodedata.category(ch) not in yamlsub.REFUSED_CATEGORIES and unicodedata.category(ch) != "Zs":
                gap.append(hex(code))
        self.assertEqual(gap, [])
        self.assertGreaterEqual(len(ZS_CHARACTERS), 16)

    def test_a_trailing_unicode_space_stays_in_a_plain_value_and_a_leading_one_too(self):
        for ch in ZS_CHARACTERS:
            with self.subTest(character=hex(ord(ch))):
                self.assertEqual(load("a: b" + ch + "\n"), {"a": "b" + ch})
                self.assertEqual(load("a: b" + ch + "\r\n"), {"a": "b" + ch})
                self.assertEqual(load("a: b" + ch + "  # 주석\n"), {"a": "b" + ch}, "주석 앞에 남은 유니코드 공백도 값의 일부다")
                self.assertEqual(load("a:\n  - b" + ch + "\n"), {"a": ["b" + ch]})
                self.assertEqual(load("a: " + ch + "b\n"), {"a": ch + "b"})
                self.assertEqual(load("environment: release\n"), {"environment": "release"})
                self.assertNotEqual(load("environment: release" + ch + "\n"), load("environment: release\n"), "값이 달라져야 정해진 값과의 견주기가 빨개진다")

    def test_a_unicode_space_where_only_an_ascii_space_may_end_the_line_is_refused(self):
        places = (("키 콜론 뒤", "a:{c}\n"), ("빈 매핑 뒤", "a: {}{c}\n"), ("빈 목록 뒤", "a: []{c}\n"), ("빈 매핑 뒤 주석", "a: {}{c} # x\n"), ("작은따옴표 글 뒤", "a: 'b'{c}\n"), ("큰따옴표 글 뒤", 'a: "b"{c}\n'),
                  ("블록 글 표시 뒤", "a: |{c}\n  x\n"), ("블록 글 표시 뒤(깎는 표시)", "a: |-{c}\n  x\n"), ("중첩 매핑 키 뒤", "a:\n  b:{c}\n"))
        for ch in ZS_CHARACTERS:
            for label, template in places:
                with self.subTest(character=hex(ord(ch)), place=label):
                    with self.assertRaises(yamlsub.YamlSubsetError):
                        load(template.replace("{c}", ch))
        for label, template in places:
            with self.subTest(place=label, character="ASCII 공백 둘"):
                load(template.replace("{c}", "  "))                                   # 같은 자리의 ASCII 공백은 예전처럼 읽힌다(거절하지 않는다)
        self.assertEqual(load("a: {}  \n"), {"a": {}}, "같은 자리의 ASCII 공백은 그대로 잘린다")
        self.assertEqual(load("a: []   # x\n"), {"a": []})
        self.assertEqual(load("a: 'b'  \n"), {"a": "b"})
        self.assertEqual(load("a: |  \n  x\n"), {"a": "x\n"})

    def test_a_unicode_space_after_a_colon_inside_a_list_item_is_plain_text_not_a_mapping(self):
        """`- b:` 뒤에 NBSP 가 붙으면 YAML 에서 콜론 뒤가 공백이 아니라 `b:` + NBSP 가 통째로 글이다(PyYAML 도 같다) — 읽개도 글 하나로 읽고 NBSP 를 값에 남긴다."""
        for ch in ZS_CHARACTERS:
            with self.subTest(character=hex(ord(ch))):
                self.assertEqual(load("a:\n  - b:" + ch + "\n"), {"a": ["b:" + ch]})

    def test_a_trailing_unicode_space_stays_in_every_line_of_a_block_text(self):
        for ch in ZS_CHARACTERS:
            with self.subTest(character=hex(ord(ch))):
                self.assertEqual(load("a: |\n  one" + ch + "\n  two\n"), {"a": "one" + ch + "\ntwo\n"})
                self.assertEqual(load("a: |\n  one\n  two" + ch + "\n"), {"a": "one\ntwo" + ch + "\n"})
                self.assertEqual(load("a: |\n  one\n  " + ch + "\n  two\n"), {"a": "one\n" + ch + "\ntwo\n"}, "유니코드 공백뿐인 줄은 빈 줄이 아니라 글 한 줄이다")
        self.assertEqual(load("a: |\n  one  \n  two\n"), {"a": "one\ntwo\n"}, "ASCII 공백은 그대로 잘린다")

    def test_a_unicode_space_is_never_dropped_anywhere_a_value_is_read(self):
        """모든 자리에서 '값에 남거나 거절' — 읽은 글에 그 글자가 없으면서 읽힌 경우가 없다."""
        templates = ("a: b{c}\n", "a: {c}b\n", "a:\n  c: d{c}\n", "a:\n  - x{c}\n  - y\n", "a: |\n  x{c}\n", "a: |\n  {c}\n  x\n", "a: 'p{c}q'\n", 'a: "p{c}q"\n', "a: b{c}  # 주석\n", "a: b  # 주석{c}\n")
        for ch in ZS_CHARACTERS:
            for template in templates:
                text = template.replace("{c}", ch)
                with self.subTest(character=hex(ord(ch)), template=template):
                    try:
                        tree = load(text)
                    except yamlsub.YamlSubsetError:
                        continue
                    if template == "a: b  # 주석{c}\n":
                        self.assertEqual(tree, {"a": "b"}, "주석 안의 글자는 값에 들어오지 않는다")
                        continue
                    seen = []

                    def walk(node):
                        if isinstance(node, dict):
                            for key, value in node.items():
                                seen.append(key)
                                walk(value)
                        elif isinstance(node, list):
                            for item in node:
                                walk(item)
                        elif isinstance(node, str):
                            seen.append(node)

                    walk(tree)
                    self.assertTrue(any(ch in piece for piece in seen), (text, tree))

    def test_a_backslash_and_ascii_spaces_at_the_end_of_a_line_are_refused_in_every_place(self):
        bs = self.BS
        cases = (("블록 글(한 칸)", "a: |\n  echo hi " + bs + " \n  rm x\n"), ("블록 글(두 칸)", "a: |\n  echo hi " + bs + "  \n  rm x\n"), ("블록 글 마지막 줄(줄바꿈 없음)", "a: |\n  echo hi " + bs + " "),
                 ("블록 글(CRLF)", "a: |\r\n  echo hi " + bs + " \r\n  rm x\r\n"), ("주석 줄", "# 설명 " + bs + " \na: 1\n"), ("한 줄 값", "a: b" + bs + " \n"), ("목록 항목", "a:\n  - x" + bs + " \n"),
                 ("역슬래시 둘", "a: |\n  echo hi " + bs + bs + " \n  rm x\n"), ("줄 끝 주석", "a: b  # c " + bs + " \n"))
        for label, text in cases:
            with self.subTest(case=label):
                with self.assertRaises(yamlsub.YamlSubsetError) as caught:
                    load(text)
                self.assertIn("역슬래시", str(caught.exception))
                self.assertIn("번째 줄", str(caught.exception))

    def test_a_backslash_at_the_very_end_of_a_line_is_a_normal_continuation_and_stays_in_the_text(self):
        bs = self.BS
        text = "a: |\n  echo a " + bs + "\n    b\n  echo c\n"
        self.assertEqual(load(text), {"a": "echo a " + bs + "\n  b\necho c\n"})
        self.assertEqual(load(text.replace("\n", "\r\n")), load(text))
        self.assertEqual(load("a: x" + bs + "y  \n"), {"a": "x" + bs + "y"}, "줄 끝이 아닌 역슬래시와 ASCII 공백 끝은 그대로 읽는다")
        self.assertEqual(load("a: |\n  echo " + bs + bs + "\n  rm x\n"), {"a": "echo " + bs + bs + "\nrm x\n"})

    def test_a_backslash_then_a_unicode_space_is_not_a_continuation_and_both_characters_stay(self):
        bs = self.BS
        for ch in ZS_CHARACTERS:
            with self.subTest(character=hex(ord(ch))):
                self.assertEqual(load("a: |\n  echo hi " + bs + ch + "\n  rm x\n"), {"a": "echo hi " + bs + ch + "\nrm x\n"})


if __name__ == "__main__":
    unittest.main()
