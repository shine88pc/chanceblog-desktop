"""오류 코드 카탈로그 시험 — 문서(정본)와 코드가 같고, 안내 문구 만들기가 안전하게 동작한다. 네트워크·시크릿 없이 돈다.

지키는 것:
  1) `errors/catalog.py` 는 docs/TROUBLESHOOTING.md 의 표에서 만든 것과 글자까지 같다(문서만 고치고 다시 만들지 않으면 실패).
  2) 운영자가 예로 든 규칙 기반 안내(Blogger 401·Git push 실패·Actions 실패·파일 생성 실패·호출 한도)가 정해진 자리표시자와 하실 일을 가진다.
  3) '재시도' 칸은 정해진 문구만 해석되고, 모르는 문구는 만드는 단계에서 실패한다.
  4) 문구 만들기: 자리표시자만 채우고, 값은 한 줄로 정리하며, 모르는 코드·빠진 값에도 예외 없이 안내한다.
  5) 코드는 Python 3.10 문법만 쓴다.
"""
import ast
import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import (  # noqa: E402
    CATALOG, RETRY_AFTER, RETRY_AUTO, RETRY_KINDS, RETRY_NO, RETRY_OPTIONAL, UNEXPECTED, AppError, clean_slot, lookup, parse_retry, render,
)
from chanceblog_desktop.errors.render import MAX_SLOT_CHARS, UNKNOWN_SLOT  # noqa: E402


def load_script():
    spec = importlib.util.spec_from_file_location("sync_errors_under_test", ROOT / "scripts" / "sync_errors.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SYNC = load_script()
DOC_TEXT = (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
GOOD_DOC = """# 제목

## 1. 영역

| 코드 | 언제 | 사용자 문구 | 하실 일 | 재시도 |
|---|---|---|---|---|
| `A_ONE` | 언제 | 문구 **「값」** | 하실 일 | 예(최대 2회) |
| `B_TWO` | 언제 | 문구 | 하실 일 | 아니오 |
"""


class CatalogMatchesDocTest(unittest.TestCase):
    def test_the_committed_catalog_is_exactly_what_the_doc_produces(self):
        committed = (ROOT / "src" / "chanceblog_desktop" / "errors" / "catalog.py").read_text(encoding="utf-8")
        self.assertEqual(committed, SYNC.expected_source(), "문서를 고쳤다면 `python scripts/sync_errors.py` 로 다시 만든다")

    def test_the_codes_in_the_doc_and_in_the_catalog_are_the_same_set(self):
        doc_codes = [row[1] for row in SYNC.parse(DOC_TEXT)]
        self.assertEqual(len(doc_codes), len(set(doc_codes)))
        self.assertEqual(set(doc_codes), set(CATALOG))
        self.assertGreaterEqual(len(CATALOG), 25)

    def test_the_script_check_mode_passes_on_the_repository(self):
        env = dict(os.environ, PYTHONUTF8="1")
        done = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "sync_errors.py"), "--check"], capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_every_entry_is_filled_and_has_a_known_retry_kind(self):
        for code, info in CATALOG.items():
            with self.subTest(code=code):
                self.assertEqual(info.code, code)
                for field in (info.area, info.when, info.message, info.action, info.retry):
                    self.assertTrue(field.strip())
                self.assertIn(info.retry_kind, RETRY_KINDS)
                if info.retry_max is not None:
                    self.assertEqual(info.retry_kind, RETRY_AUTO)
                    self.assertGreaterEqual(info.retry_max, 1)

    def test_the_catch_all_code_exists(self):
        self.assertIn(UNEXPECTED, CATALOG)
        self.assertEqual(CATALOG[UNEXPECTED].retry_kind, RETRY_NO)


class OperatorExamplesTest(unittest.TestCase):
    """운영자가 예로 든 규칙 기반 안내(2026-10-30) — 코드마다 플랫폼에 맞는 문구와 하실 일이 있다."""

    def test_blogger_401_tells_the_user_to_log_in_again(self):
        info = CATALOG["BLOGGER_AUTH_EXPIRED"]
        self.assertIn("401", info.when)
        self.assertIn("만료", info.message)
        self.assertIn("다시 로그인", info.action)
        self.assertEqual(info.retry_kind, RETRY_AFTER)

    def test_git_push_failures_split_into_auth_network_and_rejected(self):
        auth, network, rejected = CATALOG["GIT_PUSH_AUTH"], CATALOG["GIT_PUSH_NETWORK"], CATALOG["GIT_PUSH_REJECTED"]
        self.assertIn("권한", auth.message)
        self.assertIn("git push", auth.action)
        self.assertEqual(auth.retry_kind, RETRY_AFTER)
        self.assertIn("인터넷", network.message)
        self.assertEqual((network.retry_kind, network.retry_max), (RETRY_AUTO, 3))
        self.assertIn("최신", rejected.action)
        self.assertEqual((rejected.retry_kind, rejected.retry_max), (RETRY_AUTO, 1))

    def test_an_actions_failure_names_the_failed_workflow_and_job(self):
        info = CATALOG["ACTIONS_RUN_FAILED"]
        self.assertEqual(info.slots, ("워크플로 이름", "잡 이름"))
        self.assertIn("링크", info.action)

    def test_a_file_creation_failure_asks_to_check_the_path_and_permission(self):
        info = CATALOG["FILE_WRITE_FAILED"]
        self.assertEqual(info.slots, ("경로",))
        self.assertIn("권한", info.action)

    def test_an_api_limit_shows_when_to_try_again_and_never_asks_to_bypass_it(self):
        info = CATALOG["API_RATE_LIMITED"]
        self.assertEqual(info.slots, ("재시도 가능 시각",))
        self.assertIn("429", info.when)
        self.assertIn("우회하지 않습니다", info.action)
        self.assertEqual(info.retry_kind, RETRY_AFTER)

    def test_a_failed_optional_assistant_never_stops_the_program(self):
        info = CATALOG["ASSIST_UNAVAILABLE"]
        self.assertEqual(info.retry_kind, RETRY_OPTIONAL)
        self.assertIn("나머지 기능은 그대로", info.action)


class RetryParsingTest(unittest.TestCase):
    def test_the_phrases_the_doc_may_use_are_understood(self):
        cases = {
            "아니오": (RETRY_NO, None),
            "예": (RETRY_AUTO, None),
            "예(최대 3회)": (RETRY_AUTO, 3),
            "예(1회)": (RETRY_AUTO, 1),
            "예(자동 재확인)": (RETRY_AUTO, None),
            "예(자동)": (RETRY_AUTO, None),
            "예(연결되면)": (RETRY_AUTO, None),
            "로그인 뒤": (RETRY_AFTER, None),
            "고친 뒤": (RETRY_AFTER, None),
            "해결 뒤": (RETRY_AFTER, None),
            "시각 이후": (RETRY_AFTER, None),
            "선택": (RETRY_OPTIONAL, None),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_retry(text), expected)

    def test_unknown_or_sloppy_phrases_fail_instead_of_being_guessed(self):
        for text in ("", "아니요", "maybe", "예(최대 회)", "예(최대 x회)", "예 (최대 3회)", "예(최대 3회) 그리고", "로그인 후"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_retry(text)


class RenderTest(unittest.TestCase):
    def test_slot_values_are_put_in_corner_brackets_and_bold_marks_are_removed(self):
        shown = render("FILE_WRITE_FAILED", {"경로": "C:\\work\\글.md"})
        self.assertEqual(shown.message, "파일을 저장하지 못했습니다: 「C:\\work\\글.md」.")
        self.assertNotIn("**", shown.message + shown.action)
        self.assertEqual((shown.code, shown.retry_kind, shown.retry_text), ("FILE_WRITE_FAILED", RETRY_NO, "아니오"))

    def test_two_slots_in_one_message(self):
        shown = render("ACTIONS_RUN_FAILED", {"워크플로 이름": "Pages 배포", "잡 이름": "build"})
        self.assertEqual(shown.message, "배포 단계가 실패했습니다: 「Pages 배포」의 「build」.")

    def test_a_missing_slot_value_shows_unknown_instead_of_raising(self):
        shown = render("API_RATE_LIMITED", {})
        self.assertIn(f"「{UNKNOWN_SLOT}」", shown.message)
        self.assertIn(f"「{UNKNOWN_SLOT}」", render("API_RATE_LIMITED", {"재시도 가능 시각": ""}).message)
        self.assertIn(f"「{UNKNOWN_SLOT}」", render("API_RATE_LIMITED", {"재시도 가능 시각": None}).message)
        self.assertIn("11:20", render("API_RATE_LIMITED", {"재시도 가능 시각": "11:20"}).message)

    def test_values_for_slots_the_text_does_not_have_are_ignored(self):
        self.assertEqual(render("BLOGGER_AUTH_EXPIRED", {"경로": "무관"}).message, "Blogger 로그인이 만료되었습니다.")

    def test_a_value_is_one_short_line_without_control_characters_or_markup(self):
        self.assertEqual(clean_slot("a\nb\r\n\tc\x00d"), "a b c d")
        self.assertEqual(clean_slot("  앞뒤   공백  "), "앞뒤 공백")
        self.assertEqual(clean_slot("**굵게** 「괄호」"), "굵게 괄호")
        long = clean_slot("가" * 1000)
        self.assertEqual(len(long), MAX_SLOT_CHARS)
        self.assertTrue(long.endswith("…"))
        self.assertEqual(clean_slot(12), "12")
        self.assertEqual(clean_slot("a\x7fb\x85c"), "a b c", "DEL 과 C1 제어 문자도")
        self.assertEqual(clean_slot("줄\u2028바꿈\u2029끝"), "줄 바꿈 끝")

    def test_more_invisible_and_filler_characters_are_cleaned_too(self):
        for sneaky in ("\U000e0041", "\U000e0100", "\ufe0f", "\ufe00", "\u206a", "\u206f", "\u3164", "\u115f", "\u1160", "\u17b4", "\u034f", "\u2800", "\ufff9", "\u180b"):
            with self.subTest(char=hex(ord(sneaky))):
                self.assertEqual(clean_slot(f"가{sneaky}나"), "가 나")

    def test_text_direction_tricks_and_invisible_characters_cannot_disguise_a_value(self):
        self.assertEqual(clean_slot("report\u202egpj.exe"), "report gpj.exe", "오른쪽에서 왼쪽으로 뒤집는 제어 문자(확장자 위장)")
        for sneaky in ("\u202a", "\u202b", "\u202c", "\u202d", "\u2066", "\u2067", "\u2068", "\u2069", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u2060", "\ufeff", "\u00ad", "\u061c"):
            with self.subTest(char=hex(ord(sneaky))):
                self.assertEqual(clean_slot(f"가{sneaky}나"), "가 나")

    def test_a_value_cannot_forge_another_slot(self):
        shown = render("ACTIONS_RUN_FAILED", {"워크플로 이름": "「잡 이름」", "잡 이름": "build"})
        self.assertEqual(shown.message, "배포 단계가 실패했습니다: 「잡 이름」의 「build」.")

    def test_an_unknown_code_is_shown_as_the_catch_all(self):
        shown = render("NOT_A_CODE", {"경로": "x"})
        self.assertEqual(shown.code, UNEXPECTED)
        self.assertEqual(shown.message, CATALOG[UNEXPECTED].message)
        self.assertIs(lookup("NOT_A_CODE"), CATALOG[UNEXPECTED])

    def test_every_code_can_be_rendered_with_no_values_at_all(self):
        for code in CATALOG:
            with self.subTest(code=code):
                shown = render(code)
                self.assertTrue(shown.message and shown.action)
                self.assertNotIn("**", shown.message + shown.action)
                self.assertEqual(shown.message.count("「"), shown.message.count("」"))


class AppErrorTest(unittest.TestCase):
    def test_it_is_an_exception_that_carries_the_code_and_the_values(self):
        with self.assertRaises(AppError) as caught:
            raise AppError("GIT_PUSH_AUTH", detail="HTTP 403 from remote")
        error = caught.exception
        self.assertEqual((error.code, error.requested_code), ("GIT_PUSH_AUTH", "GIT_PUSH_AUTH"))
        self.assertIs(error.info, CATALOG["GIT_PUSH_AUTH"])
        self.assertEqual(error.rendered().code, "GIT_PUSH_AUTH")
        self.assertTrue(str(error).startswith("GIT_PUSH_AUTH: "))

    def test_the_developer_detail_is_kept_but_never_shown_to_the_user(self):
        error = AppError("FILE_WRITE_FAILED", {"경로": "C:\\x.md"}, detail="secret-ish internal text")
        self.assertEqual(error.detail, "secret-ish internal text")
        self.assertNotIn("secret-ish", str(error))
        self.assertNotIn("secret-ish", error.rendered().message + error.rendered().action)

    def test_an_unknown_code_becomes_the_catch_all_and_remembers_what_was_asked(self):
        error = AppError("MADE_UP")
        self.assertEqual((error.code, error.requested_code), (UNEXPECTED, "MADE_UP"))
        self.assertTrue(str(error).startswith(f"{UNEXPECTED}: "))


class GeneratorRulesTest(unittest.TestCase):
    def test_a_good_doc_is_parsed_into_rows_with_the_section_title(self):
        rows = SYNC.parse(GOOD_DOC)
        self.assertEqual([row[:2] for row in rows], [("영역", "A_ONE"), ("영역", "B_TWO")])
        self.assertEqual(rows[0][2:], ("언제", "문구 **「값」**", "하실 일", "예(최대 2회)"))

    def test_the_generated_source_is_valid_python_and_stable(self):
        rows = SYNC.parse(GOOD_DOC)
        source = SYNC.render_source(rows)
        self.assertEqual(source, SYNC.render_source(rows))
        namespace = {}
        exec(compile(source, "catalog_under_test.py", "exec"), namespace)
        self.assertEqual(list(namespace["ROWS"]), rows)

    def test_bad_tables_fail_with_a_message_that_names_the_line(self):
        bad = {
            "빈 칸": GOOD_DOC.replace("| 하실 일 | 아니오 |", "|  | 아니오 |"),
            "칸 부족": GOOD_DOC.replace("| 언제 | 문구 | 하실 일 | 아니오 |", "| 언제 | 문구 | 아니오 |"),
            "겹친 코드": GOOD_DOC.replace("B_TWO", "A_ONE"),
            "모르는 재시도": GOOD_DOC.replace("| 아니오 |", "| 아마도 |"),
            "절 제목 없음": GOOD_DOC.replace("## 1. 영역\n", ""),
            "코드 행 없음": "# 제목\n\n## 1. 영역\n\n표 없음\n",
        }
        for name, text in bad.items():
            with self.subTest(name):
                with self.assertRaises(ValueError) as caught:
                    SYNC.parse(text)
                self.assertTrue(str(caught.exception))

    def test_rows_inside_code_blocks_are_examples_and_are_not_read(self):
        doc = GOOD_DOC + "\n```\n| `FENCED_ONE` | 언제 | 문구 | 하실 일 | 아니오 |\n```\n\n~~~\n| `FENCED_TWO` | 언제 | 문구 | 하실 일 | 아니오 |\n~~~\n"
        self.assertEqual([row[1] for row in SYNC.parse(doc)], ["A_ONE", "B_TWO"])

    def test_a_row_that_does_not_look_like_a_row_is_an_error_not_silently_dropped(self):
        bad = {
            "소문자 코드": GOOD_DOC.replace("`B_TWO`", "`b_two`"),
            "하이픈 코드": GOOD_DOC.replace("`B_TWO`", "`B-TWO`"),
            "백틱 없음": GOOD_DOC.replace("`B_TWO`", "B_TWO"),
            "들여쓰기": GOOD_DOC.replace("| `B_TWO`", " | `B_TWO`"),
            "인용": GOOD_DOC.replace("| `B_TWO`", "> | `B_TWO`"),
            "머리글 없는 표": GOOD_DOC.replace("| 코드 | 언제 | 사용자 문구 | 하실 일 | 재시도 |\n|---|---|---|---|---|\n", ""),
            "닫히지 않은 코드 블록": GOOD_DOC + "\n```\n| `C_THREE` | 언제 | 문구 | 하실 일 | 아니오 |\n",
        }
        for name, text in bad.items():
            with self.subTest(name):
                with self.assertRaises(ValueError) as caught:
                    SYNC.parse(text)
                self.assertTrue(str(caught.exception))

    def test_an_indented_code_block_and_aligned_table_separators_are_handled(self):
        doc = GOOD_DOC.replace("|---|---|---|---|---|", "|:---|---:|:---:|---|:---:|") + "\n  ```\n  | `FENCED` | 언제 | 문구 | 하실 일 | 아니오 |\n  ```\n"
        self.assertEqual([row[1] for row in SYNC.parse(doc)], ["A_ONE", "B_TWO"])

    def test_other_tables_and_text_in_the_doc_are_left_alone(self):
        doc = GOOD_DOC + "\n\n## 2. 다른 표\n\n| 이름 | 뜻 |\n|---|---|\n| `abc` | 설명 |\n\n본문에 `CODE_IN_TEXT` 와 | 막대 | 가 있어도 된다.\n"
        self.assertEqual([row[1] for row in SYNC.parse(doc)], ["A_ONE", "B_TWO"])

    def test_check_mode_reports_a_stale_file_and_write_mode_repairs_it(self):
        original = SYNC.OUT
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            SYNC.OUT = Path(tmp) / "catalog.py"
            try:
                self.assertEqual(SYNC.main(["--check"]), 1, "파일이 없으면 어긋난 것")
                SYNC.OUT.write_text("ROWS = ()\n", encoding="utf-8")
                self.assertEqual(SYNC.main(["--check"]), 1, "내용이 다르면 어긋난 것")
                self.assertEqual(SYNC.main([]), 0)
                self.assertEqual(SYNC.OUT.read_text(encoding="utf-8"), SYNC.expected_source())
                self.assertEqual(SYNC.main(["--check"]), 0)
            finally:
                SYNC.OUT = original


class CodeUsageTest(unittest.TestCase):
    """코드가 쓰는 오류 코드가 표에 있는지 — 오타 난 코드는 조용히 UNEXPECTED_ERROR 로 바뀌어 원인 안내가 사라진다."""

    def test_every_error_code_named_in_the_source_is_in_the_catalog(self):
        pattern = re.compile(r'AppError\(\s*"([A-Z][A-Z0-9_]+)"')
        used = {}
        for path in (ROOT / "src").rglob("*.py"):
            for code in pattern.findall(path.read_text(encoding="utf-8")):
                used.setdefault(code, path.name)
        self.assertTrue({"PAGES_LOCAL_REPO_INVALID", "GIT_NOT_INSTALLED", "NETWORK_TIMEOUT"} <= set(used), "알려진 코드를 못 찾았다 — 이 시험의 찾기 규칙이 깨졌다")
        for code, where in sorted(used.items()):
            with self.subTest(code=code):
                self.assertIn(code, CATALOG, f"{where} 가 표에 없는 코드를 쓴다")

    def test_every_code_the_git_classifier_can_return_is_in_the_catalog(self):
        from chanceblog_desktop.publish import gitrepo
        for code, needles in gitrepo._RULES:
            with self.subTest(code=code):
                self.assertIn(code, CATALOG)
                self.assertTrue(needles)


class PythonSyntaxTest(unittest.TestCase):
    def test_sources_use_only_python_310_syntax(self):
        files = [path for folder in ("src", "scripts", "tests") for path in (ROOT / folder).rglob("*.py")]
        self.assertTrue(files)
        for path in files:
            with self.subTest(file=str(path.relative_to(ROOT))):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))


if __name__ == "__main__":
    unittest.main()
