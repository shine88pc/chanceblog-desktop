"""글자 읽기 작업자 관문 `capabilities.LOCAL_OCR`(결정 D-512, 운영자 확인 026 ②·028 ②, 설계서 3-8 (4))의 시험 — `test_external_write_gate.py` 와 같은 모양이다.

지키는 것:
  1) 소스 상수 `LOCAL_OCR` 는 False 이고 글자 그대로 True 일 때만 열린다. 외부 쓰기 관문(`EXTERNAL_WRITE`)과 서로 영향이 없다. 꺼진 채 부르면 고정 오류 `OCR_UNAVAILABLE` 이다.
  2) 켜는 길이 없다 — `src/` 어디서도 이 상수에 값을 넣는 곳은 `capabilities.py` 의 `LOCAL_OCR = False` 하나뿐이고, 다른 모듈은 이름도 쓰지 않는다. 설정 칸·환경 변수·명령줄·화면에 켜는 길이 없고 시험만 patch 로 켠다.
  3) 하위 프로세스를 띄우는 곳(`ui/ocr_adapter.py`)은 그것을 띄우는 모든 함수의 첫 문장이 `require_local_ocr` 이다(파일이 있을 때).
"""
import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402
from capability_support import local_ocr_off, local_ocr_on  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service.context import Settings  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
ADAPTER = SRC / "ui" / "ocr_adapter.py"
GATE_NAMES = ("capabilities.require_local_ocr", "require_local_ocr")
LAUNCH_CALLS = ("subprocess.Popen",)
OTHER_CALLS = ("subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "os.system", "os.popen")


def src_files():
    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)


def statements(function):
    return [node for node in function.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]


def is_gate_call(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) in GATE_NAMES


class ConstantTest(unittest.TestCase):
    def test_the_shipped_constant_is_off_and_independent_of_the_other_gates(self):
        self.assertIs(capabilities.LOCAL_OCR, False)
        self.assertFalse(capabilities.local_ocr_enabled())
        with mock.patch.object(capabilities, "LOCAL_OCR", True):
            self.assertTrue(capabilities.local_ocr_enabled())
            self.assertFalse(capabilities.external_write_enabled(), "글자 읽기를 켜도 외부 쓰기는 안 열린다")
            self.assertFalse(capabilities.blogger_oauth_input_enabled())
        with mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
            self.assertFalse(capabilities.local_ocr_enabled(), "외부 쓰기를 켜도 글자 읽기는 안 열린다")

    def test_the_gate_refuses_with_the_catalog_code_and_names_the_operation(self):
        with self.assertRaises(AppError) as caught:
            capabilities.require_local_ocr("시험 작업")
        error = caught.exception
        self.assertEqual((error.code, error.slots), ("OCR_UNAVAILABLE", {"작업": "시험 작업"}))
        shown = error.rendered()
        self.assertIn("시험 작업", shown.message)
        self.assertEqual(shown.retry_kind, "no")

    def test_only_the_literal_true_opens_the_gate(self):
        for value in (1, "yes", "True", [1], object(), 2, "1"):
            with self.subTest(value=repr(value)[:20]), mock.patch.object(capabilities, "LOCAL_OCR", value):
                self.assertFalse(capabilities.local_ocr_enabled())
                with self.assertRaises(AppError):
                    capabilities.require_local_ocr("x")
        with mock.patch.object(capabilities, "LOCAL_OCR", True):
            capabilities.require_local_ocr("x")                              # 예외 없음
        self.assertIs(capabilities.LOCAL_OCR, False, "시험의 임시 켜기는 끝나면 원래대로다")

    def test_the_test_helper_opens_and_closes_it_and_never_leaks(self):
        local_ocr_on()
        try:
            self.assertTrue(capabilities.local_ocr_enabled())
        finally:
            local_ocr_off()
        self.assertFalse(capabilities.local_ocr_enabled())

    def test_every_catalog_code_for_the_feature_has_every_column(self):
        for code in ("OCR_UNAVAILABLE", "OCR_FAILED", "OCR_TIMEOUT", "OCR_TOO_BIG", "OCR_ADDON_INVALID", "OCR_BLOCKED", "OCR_UNEXPECTED"):
            info = CATALOG[code]
            self.assertTrue(info.when and info.message and info.action, code)
        self.assertEqual(CATALOG["OCR_UNAVAILABLE"].slots, ("작업",))
        for code in ("OCR_FAILED", "OCR_TIMEOUT", "OCR_TOO_BIG", "OCR_ADDON_INVALID", "OCR_BLOCKED", "OCR_UNEXPECTED"):
            self.assertEqual(CATALOG[code].slots, (), code)

    def test_the_screen_sentences_the_design_fixes_are_in_the_catalog_word_for_word(self):
        sentences = {"OCR_FAILED": "글자 읽기를 하지 못했어요. 잠시 뒤 다시 해 보세요. 계속 안 되면 직접 적어 주세요",
                     "OCR_TIMEOUT": "너무 오래 걸려서 멈췄어요. PC 가 바쁜 것 같아요. 다른 프로그램을 닫고 다시 해 보세요",
                     "OCR_TOO_BIG": "사진이 너무 커서 글자를 읽을 수 없어요. 사진 크기를 줄여서 다시 넣어 주세요",
                     "OCR_ADDON_INVALID": "글자 읽기 도구 파일이 달라졌어요. 도구를 다시 풀어 주세요",
                     "OCR_BLOCKED": "이 PC 의 보안 프로그램이 글자 읽기 도구를 막은 것 같아요",
                     "OCR_UNEXPECTED": "글자 읽기 도구가 예상 밖의 일을 해서 멈췄어요. 이번 실행에서는 글자 읽기를 끌게요"}
        for code, sentence in sentences.items():
            self.assertIn(sentence, CATALOG[code].message, code)


class NoWayToTurnItOnTest(unittest.TestCase):
    def test_nothing_in_src_stores_to_the_constant_except_the_one_false_in_capabilities(self):
        stores = []
        for path in src_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for target in targets:
                    for item in ast.walk(target):
                        if (isinstance(item, ast.Name) and item.id == "LOCAL_OCR") or (isinstance(item, ast.Attribute) and item.attr == "LOCAL_OCR"):
                            stores.append((path.relative_to(SRC).as_posix(), ast.unparse(node.value) if getattr(node, "value", None) is not None else ""))
        self.assertEqual(stores, [("capabilities.py", "False")], "소스 상수에 값을 넣는 곳은 capabilities.py 의 `LOCAL_OCR = False` 하나뿐이다")

    def test_no_other_module_even_names_the_constant_and_no_code_sets_it_by_string(self):
        found = []
        for path in src_files():
            if path.name == "capabilities.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Name) and node.id == "LOCAL_OCR") or (isinstance(node, ast.Attribute) and node.attr == "LOCAL_OCR") or (isinstance(node, ast.Constant) and node.value == "LOCAL_OCR"):
                    found.append((path.relative_to(SRC).as_posix(), getattr(node, "lineno", 0)))
        self.assertEqual(found, [], "capabilities.py 밖에서는 상수 이름을 쓰지 않는다 — 부르는 것은 관문 함수뿐이다")

    def test_the_capabilities_module_reads_nothing_from_outside(self):
        text = (SRC / "capabilities.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        body = "\n".join(ast.unparse(node) for node in tree.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)))
        for word in ("environ", "getenv", "argv", "settings", "json", "open(", "read_text", "import os", "import sys", "argparse", "subprocess"):
            self.assertNotIn(word, body, f"capabilities.py 는 바깥에서 값을 읽지 않는다: {word}")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        self.assertIn("LOCAL_OCR = False", code)
        self.assertNotRegex(code, r"LOCAL_OCR\s*=\s*True")

    def test_the_settings_file_has_no_field_for_it_and_still_refuses_unknown_fields(self):
        text = (SRC / "service" / "context.py").read_text(encoding="utf-8")
        for word in ("local_ocr", "LOCAL_OCR", "ocr_enabled", "글자 읽기"):
            self.assertNotIn(word, text, word)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"schema": 1, "repo_path": "", "naver_profiles": {}, "local_ocr": true}', encoding="utf-8")
            with self.assertRaises(AppError) as caught:
                Settings(path).repo_path()
            self.assertEqual(caught.exception.code, "SETTINGS_INVALID", "설정 파일에 그런 칸을 넣어도 읽지 않는다 — 켜지지 않는다")

    def test_the_command_line_has_no_switch_or_settings_command_for_it(self):
        parser = cli.build_parser()
        words, stack = set(), [parser]
        while stack:
            current = stack.pop()
            for action in current._actions:
                words.update(action.option_strings)
                choices = getattr(action, "choices", None)
                if isinstance(choices, dict):
                    for name, child in choices.items():
                        words.add(name)
                        stack.append(child)
        for word in words:
            self.assertIsNone(re.search(r"(?i)ocr|local", word), f"켜는 길처럼 보이는 명령·옵션: {word}")

    def test_no_environment_variable_name_with_ocr_is_read_anywhere_in_src(self):
        reads = []
        for path in src_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                call = ast.unparse(node.func) if isinstance(node, ast.Call) else ""
                strings = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)] if isinstance(node, ast.Call) else []
                if call in ("os.getenv", "os.environ.get", "os.environ.setdefault") and any("OCR" in value.upper() for value in strings):
                    reads.append((path.relative_to(SRC).as_posix(), node.lineno))
                if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ" and isinstance(node.slice, ast.Constant) and "OCR" in str(node.slice.value).upper():
                    reads.append((path.relative_to(SRC).as_posix(), node.lineno))
        self.assertEqual(reads, [], "글자 읽기를 켜는 환경 변수는 없다")

    def test_the_constant_is_never_true_in_any_committed_source_or_test_file_text(self):
        """소스에는 `LOCAL_OCR = True` 가 없다(시험은 patch 로만 켠다) — 켜는 것은 별도 승인 변경이다."""
        for path in src_files():
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"LOCAL_OCR\s*=\s*True", path.name)


class EntryPointGateTest(unittest.TestCase):
    @unittest.skipUnless(ADAPTER.exists(), "ui/ocr_adapter.py 가 아직 없다")
    def test_the_only_other_process_call_in_the_adapter_is_the_taskkill_that_ends_a_tree(self):
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
        others = [call for call in ast.walk(tree) if isinstance(call, ast.Call) and ast.unparse(call.func) in OTHER_CALLS]
        self.assertTrue(others)
        for call in others:
            first = call.args[0] if call.args else None
            self.assertTrue(isinstance(first, ast.List) and first.elts and isinstance(first.elts[0], ast.Constant) and first.elts[0].value == "taskkill", ast.unparse(call)[:80])

    @unittest.skipUnless(ADAPTER.exists(), "ui/ocr_adapter.py 가 아직 없다")
    def test_every_function_that_launches_a_process_in_the_adapter_starts_with_the_gate(self):
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
        launchers = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                own = [call for call in ast.walk(node) if isinstance(call, ast.Call) and ast.unparse(call.func) in LAUNCH_CALLS]
                if own:
                    launchers.append(node)
        self.assertTrue(launchers, "어댑터에 하위 프로세스를 띄우는 함수가 있어야 한다")
        for function in launchers:
            body = statements(function)
            self.assertTrue(body and is_gate_call(body[0]), f"{function.name} 의 첫 문장이 관문이 아니다 — {ast.unparse(body[0])[:70] if body else '(비었다)'}")


if __name__ == "__main__":
    unittest.main()
