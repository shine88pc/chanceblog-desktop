"""주제 엔진(`topics/`)의 순수성 규칙을 소스에서 직접 확인하는 시험(AST 검사) — 서비스 층 안전 시험(`test_service_safety`)과 같은 정신이다. 규칙을 어기는 코드가 몰래 들어오면 여기서 걸린다.

지키는 것:
  1) 의존은 표준 라이브러리 몇 개와 `content`(채널 키·후보 검증 도구)·`errors`·같은 패키지뿐이다 — `service`·`ui`·`publish`·`render` 를 가져오지 않는다.
  2) 파일·네트워크·시계·난수·`sqlite3`·`subprocess`·`ctypes` 를 쓰지 않는다(날짜는 인자로 받고 같은 입력은 늘 같은 결과다). `print`·`open`·환경 변수도 쓰지 않는다.
  3) 오류를 삼키지 않고(맨 except·pass 뿐인 except 금지) 코드는 파이썬 3.10 문법이다. 보이지 않는 글자·BOM·이 PC 의 절대경로·키 낱말이 없다.
  4) `__init__.py` 는 설명뿐이고 `layout.py` 는 이름 상수뿐이다. 이 패키지를 쓰는 곳이 아직 없다(기존 동작은 하나도 바뀌지 않았다).
  5) 위 검사기 자신도 합성 소스로 시험한다 — 어긴 소스를 실제로 잡는다.
  6) P2a 가 더한 모듈(`seeds`·`schedule`·`dedupe`·`history`·`hold`)에도 같은 검사가 그대로 걸린다. 모듈 목록 시험은 모듈을 더하거나 빼면 일부러 고쳐야 하는 시험이다.
검사기는 **이름 기반**이다 — 인자로 받은 객체의 메서드 이름까지 다 막지는 못한다(사고 방지용이지 악의 방지가 아니다, 독립 검증 L6). 파일 열기·목록 훑기 같은 흔한 메서드 이름을 막는 목록(`FORBIDDEN_METHODS`)을 P2a 에서 넓혔다.
네트워크·파일 쓰기·실제 시계 없이 돈다.
"""
import ast
import re
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import CATALOG  # noqa: E402

TOPICS = ts.TOPICS
SRC = ts.ROOT / "src" / "chanceblog_desktop"
FILES = sorted(TOPICS.glob("*.py"))
# 모듈을 더하거나 빼면 이 두 목록과 `docs/ARCHITECTURE.md` §5 의 `topics/` 행을 의식적으로 함께 고친다(P1 → P2a 에서 `dedupe`·`history`·`hold`·`schedule`·`seeds` 를 더했다).
EXPECTED_FILES = ["__init__.py", "channels.py", "dedupe.py", "history.py", "hold.py", "layout.py", "link.py", "model.py", "schedule.py", "score.py", "seeds.py", "select.py"]
TOPIC_MODULES = {"channels", "dedupe", "history", "hold", "layout", "link", "model", "schedule", "score", "seeds", "select"}
P2A_MODULES = ("seeds.py", "schedule.py", "dedupe.py", "history.py", "hold.py")
ALLOWED_STDLIB = {"__future__", "collections", "dataclasses", "datetime", "enum", "fractions", "functools", "itertools", "math", "re", "types", "typing", "unicodedata"}
ALLOWED_INTERNAL = {"content.status", "content.candidates", "content.profiles", "errors"}
FORBIDDEN_CALLS = {"open", "print", "input", "exec", "eval", "compile", "__import__", "breakpoint", "exit", "quit"}
FORBIDDEN_METHODS = {"now", "utcnow", "today", "monotonic", "perf_counter", "sleep", "random", "randint", "randrange", "choice", "shuffle", "uuid1", "uuid4", "urandom", "token_hex",
                     "read_text", "write_text", "read_bytes", "write_bytes", "mkdir", "unlink", "rmtree", "touch", "connect", "system", "popen", "Popen", "getenv", "urlopen",
                     "open", "exists", "is_file", "is_dir", "iterdir", "glob", "rglob", "listdir", "scandir"}
SECRET_WORDS = re.compile(r"(?i)\b(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?\b")
LOCAL_PATH = re.compile(r"(?i)[a-z]:[\\/]+users[\\/]|/users/[a-z]|/home/[a-z]")


def violations(source):
    """소스 하나에서 규칙을 어긴 곳을 글로 모은다(없으면 빈 목록)."""
    found = []
    for node in ast.walk(ast.parse(source, feature_version=(3, 10))):
        if isinstance(node, ast.Import):
            found += [f"import {alias.name}" for alias in node.names if alias.name.split(".")[0] not in ALLOWED_STDLIB]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0:
                allowed = module.split(".")[0] in ALLOWED_STDLIB
            elif node.level == 1:
                allowed = module in TOPIC_MODULES or (not module and all(alias.name in TOPIC_MODULES for alias in node.names))
            else:
                allowed = node.level == 2 and module in ALLOWED_INTERNAL
            if not allowed:
                found.append(f"from {'.' * node.level}{module} import …")
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if (isinstance(node.func, ast.Name) and name in FORBIDDEN_CALLS) or (isinstance(node.func, ast.Attribute) and name in FORBIDDEN_METHODS):
                found.append(f"호출 {name}()")
        elif isinstance(node, ast.Attribute) and node.attr in ("environ", "argv", "stdin", "stdout", "stderr"):
            found.append(f"속성 {node.attr}")
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                found.append("맨 except:")
            elif all(isinstance(item, ast.Pass) for item in node.body):
                found.append("본문이 pass 뿐인 except")
    return found


def strings(tree):
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


class PackageFilesTest(unittest.TestCase):
    def test_the_package_has_exactly_the_expected_modules_so_adding_or_removing_one_is_a_conscious_change(self):
        # P1 의 `test_the_package_has_exactly_the_expected_modules` 를 P2a 에서 의식적으로 바꿨다(독립 검증 L10): 이름에 '의식적' 이 보이게 하고 실패 메시지에 고칠 곳을 적었다.
        self.assertEqual([path.name for path in FILES], EXPECTED_FILES, "모듈을 더하거나 뺐다면 EXPECTED_FILES·TOPIC_MODULES 와 docs/ARCHITECTURE.md §5 의 topics/ 행을 의식적으로 함께 고친다")

    def test_the_p2a_modules_are_in_the_list_the_checks_run_over(self):
        for name in P2A_MODULES:
            with self.subTest(module=name):
                self.assertIn(name, [path.name for path in FILES])
                self.assertIn(name[:-3], TOPIC_MODULES)

    def test_every_module_starts_with_an_explanation(self):
        for path in FILES:
            with self.subTest(module=path.name):
                doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
                self.assertTrue(doc and len(doc) > 40)

    def test_the_package_init_is_only_an_explanation(self):
        body = ast.parse((TOPICS / "__init__.py").read_text(encoding="utf-8")).body
        self.assertEqual(len(body), 1)
        self.assertTrue(isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str))

    def test_the_layout_module_holds_names_and_nothing_else(self):
        body = ast.parse((TOPICS / "layout.py").read_text(encoding="utf-8")).body
        self.assertTrue(isinstance(body[0], ast.Expr))
        for node in body[1:]:
            with self.subTest(line=node.lineno):
                self.assertIsInstance(node, ast.Assign)
                self.assertFalse(any(isinstance(inner, (ast.Call, ast.Lambda, ast.Attribute)) for inner in ast.walk(node)), "이름 상수뿐이다 — 호출·파일 열기가 없다")

    def test_the_source_is_python_3_10_grammar(self):
        for path in FILES:
            with self.subTest(module=path.name):
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))

    def test_no_invisible_characters_no_bom_no_tabs_in_the_source(self):
        for path in FILES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(module=path.name):
                self.assertFalse(text.startswith(chr(0xFEFF)))
                self.assertNotIn("\t", text)
                self.assertEqual([ch for ch in text if unicodedata.category(ch) in ("Cf", "Cc") and ch not in "\n\r"], [])
                self.assertNotIn("\r", text.replace("\r\n", ""), "줄바꿈이 섞이지 않았다")


class PurityRulesTest(unittest.TestCase):
    def test_the_real_modules_follow_every_rule(self):
        for path in FILES:
            with self.subTest(module=path.name):
                self.assertEqual(violations(path.read_text(encoding="utf-8")), [])

    def test_the_modules_import_nothing_from_the_service_ui_publish_or_render_layers(self):
        for path in FILES:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    with self.subTest(module=path.name, line=node.lineno):
                        self.assertNotIn((node.module or "").split(".")[0], {"service", "ui", "publish", "render", "update", "security", "jobs", "assist", "check"})

    def test_the_modules_use_only_the_documented_internal_imports(self):
        used = set()
        for path in FILES:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level == 2:
                    used.add(node.module)
        self.assertTrue(used <= ALLOWED_INTERNAL)
        self.assertTrue({"content.status", "content.candidates", "content.profiles"} <= used)

    def test_the_checker_catches_a_forbidden_import(self):
        for source in ("import os", "import sys", "import socket", "import subprocess", "import ctypes", "import sqlite3", "import random", "import secrets", "import uuid", "import time",
                       "import json", "import pathlib", "import shutil", "import tempfile", "import urllib.request", "import http.client", "import ssl", "import threading", "import asyncio",
                       "import logging", "from os import path", "from pathlib import Path", "from random import choice", "from time import time", "from sqlite3 import connect",
                       "from urllib import request", "from uuid import uuid4", "from subprocess import run", "from ctypes import windll", "import requests", "import csv", "import io"):
            with self.subTest(source=source):
                self.assertTrue(violations(source), source)

    def test_the_checker_catches_an_import_of_the_upper_layers(self):
        for source in ("from ..service import context", "from ..service.context import Context", "from ..ui import core", "from ..publish import pages", "from ..render import pages",
                       "from ..security import mask", "from ..update import x", "from ..jobs import x", "from ..assist import x", "from ..check import claims", "from ..content import store",
                       "from ..content.store import Store", "from ..content.suggest import suggest", "from ... import x", "from .. import service", "from .other import x", "from . import other"):
            with self.subTest(source=source):
                self.assertTrue(violations(source), source)

    def test_the_checker_catches_a_clock_read_a_random_number_and_file_access(self):
        for source in ("datetime.now()", "datetime.datetime.utcnow()", "date.today()", "time.monotonic()", "time.perf_counter()", "random.random()", "random.choice([1])", "uuid.uuid4()",
                       "os.urandom(4)", "open('x')", "open('x', 'w')", "Path('x').read_text()", "p.write_text('x')", "p.mkdir()", "p.unlink()", "shutil.rmtree(p)", "print('x')", "input()",
                       "exec('1')", "eval('1')", "__import__('os')", "os.getenv('A')", "socket.connect(1)", "request.urlopen(u)", "sqlite3.connect(':memory:')", "sys.argv", "os.environ",
                       "p.open()", "p.exists()", "p.is_file()", "p.is_dir()", "p.iterdir()", "p.glob('*')", "p.rglob('*')", "os.listdir('.')", "os.scandir('.')"):
            with self.subTest(source=source):
                self.assertTrue(violations(source), source)

    def test_the_checker_catches_a_silent_error(self):
        self.assertTrue(violations("try:\n    1\nexcept:\n    raise\n"))
        self.assertTrue(violations("try:\n    1\nexcept ValueError:\n    pass\n"))
        self.assertEqual(violations("try:\n    1\nexcept ValueError as error:\n    raise RuntimeError('x') from error\n"), [])

    def test_the_checker_lets_the_allowed_things_through(self):
        for source in ("import re", "from __future__ import annotations", "from dataclasses import dataclass, field", "from datetime import timedelta", "from types import MappingProxyType",
                       "from collections import Counter", "from datetime import date", "from fractions import Fraction", "from .dedupe import words_of", "from .history import valid_day", "from . import hold",
                       "from .schedule import CalendarEntry", "from .seeds import Seed", "from ..content.candidates import keyword_key, forbidden_claim", "from ..content.profiles import clean_line",
                       "from typing import NamedTuple", "from collections.abc import Mapping", "import unicodedata", "from fractions import Fraction", "import itertools",
                       "from ..content.status import PLATFORMS", "from ..content.candidates import STATUSES", "from ..content.profiles import _invalid", "from ..errors import AppError",
                       "from .channels import FACTOR_NAMES", "from .score import score", "from . import channels", "x = datetime.timedelta(hours=9)", "moment.strftime('%Y')",
                       "sorted(items, key=len)", "re.compile('x')"):
            with self.subTest(source=source):
                self.assertEqual(violations(source), [], source)

    def test_a_date_is_only_ever_an_argument_never_read_from_the_clock(self):
        text = "\n".join(path.read_text(encoding="utf-8") for path in FILES)
        for needle in (".now(", ".utcnow(", ".today(", "time.time(", "datetime.date.today"):
            self.assertNotIn(needle, text)


class HygieneTest(unittest.TestCase):
    def test_no_error_is_swallowed_silently_in_the_real_modules(self):
        for path in FILES:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ExceptHandler):
                    with self.subTest(module=path.name, line=node.lineno):
                        self.assertIsNotNone(node.type)
                        self.assertFalse(all(isinstance(item, ast.Pass) for item in node.body))

    def test_no_secret_words_and_no_local_paths_in_the_strings(self):
        for path in FILES:
            for text in strings(ast.parse(path.read_text(encoding="utf-8"))):
                with self.subTest(module=path.name, text=text[:30]):
                    self.assertIsNone(SECRET_WORDS.search(text))
                    self.assertIsNone(LOCAL_PATH.search(text))

    def test_error_codes_the_package_raises_exist_in_the_catalog(self):
        pattern = re.compile(r'AppError\(\s*"([A-Z][A-Z0-9_]+)"')
        codes = {code for path in FILES for code in pattern.findall(path.read_text(encoding="utf-8"))}
        for code in sorted(codes):
            self.assertIn(code, CATALOG)
        self.assertIn("CONTENT_INVALID", CATALOG)
        self.assertIn("CANDIDATE_INVALID", CATALOG)

    def test_nothing_outside_the_package_uses_it_yet_so_no_existing_behaviour_changed(self):
        pattern = re.compile(r"(?m)^\s*(?:from\s+(?:[.\w]*\.)?topics\b|import\s+(?:[\w.]*\.)?topics\b|from\s+\.+\s+import\s+[^#\n]*\btopics\b)")
        users = [str(path.relative_to(SRC)) for path in SRC.rglob("*.py") if TOPICS not in path.parents and pattern.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(users, [], "P1 은 새 모듈뿐이다 — 이 패키지를 쓰는 연결은 다음 묶음에서 의식적으로 더한다(그때 이 시험을 고친다)")

    def test_the_pattern_that_looks_for_users_of_the_package_works(self):
        pattern = re.compile(r"(?m)^\s*(?:from\s+(?:[.\w]*\.)?topics\b|import\s+(?:[\w.]*\.)?topics\b|from\s+\.+\s+import\s+[^#\n]*\btopics\b)")
        for source in ("from ..topics import model", "from chanceblog_desktop.topics import score", "import chanceblog_desktop.topics.model", "from .. import topics", "    from ..topics.channels import x"):
            self.assertTrue(pattern.search(source), source)
        for source in ("from ..content import candidates", "topics = []", "# from ..topics import x", "from . import suggest_topics"):
            self.assertFalse(pattern.search(source), source)


class DocsAndScopeTest(unittest.TestCase):
    ARCH = (ts.ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    def row(self):
        return next(line for line in self.ARCH.splitlines() if line.startswith("| `topics/` |"))

    def test_the_architecture_table_has_one_row_that_names_every_module_and_the_dependency_line_follows(self):
        row = self.row()
        for path in FILES:
            if path.name != "__init__.py":
                with self.subTest(module=path.name):
                    self.assertIn(f"`{path.name}`", row)
        self.assertEqual(sum(line.startswith("| `topics/` |") for line in self.ARCH.splitlines()), 1)
        self.assertIn("**`topics/` 의존 방향**", self.ARCH)
        for needle in ("service", "ui", "publish", "render"):
            self.assertIn(f"`{needle}`", self.ARCH.split("**`topics/` 의존 방향**", 1)[1].splitlines()[0])

    def test_the_numbers_in_the_architecture_row_are_the_numbers_in_the_code(self):
        from chanceblog_desktop.topics import channels as ch
        row = self.row()
        profile = ch.default_profiles()[0]
        self.assertIn("/".join(str(number) for number in ch.GRADE_CUTOFFS), row)
        self.assertIn("/".join(str(number) for number in profile.dup_cutoffs), row)
        self.assertIn(f"채널당 우수 후보 수 {profile.top_n}", row)
        self.assertIn(f"같은 주제 묶음 상한 {profile.cluster_cap}", row)
        for name in ("channel_profiles.json", "seeds.json", "calendar.json", "topic_engine.db"):
            self.assertIn(name, row)

    def test_the_section_title_the_other_tests_read_is_unchanged(self):
        self.assertIn("## 5. 코드 구성(예정 — `src/chanceblog_desktop/`)", self.ARCH.splitlines())

    def test_the_changelog_mentions_the_new_package(self):
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("src/chanceblog_desktop/topics/", log)

    def test_the_changelog_mentions_p2a_and_its_five_new_modules(self):
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("'P2a'", log)
        for name in P2A_MODULES:
            with self.subTest(module=name):
                self.assertIn(f"`{name}`", log)

    def test_the_plan_names_every_module_and_keeps_the_month_table_relation_in_one_place(self):
        plan = (ts.ROOT / "docs" / "TOPIC_ENGINE_PLAN.md").read_text(encoding="utf-8")
        for path in FILES:
            if path.name != "__init__.py":
                with self.subTest(module=path.name):
                    self.assertIn(f"| `{path.name}` |", plan)
        row = next(line for line in plan.splitlines() if line.startswith("| `schedule.py` |"))
        for needle in ("SEASONS", "그대로 두고 읽지 않는다", "겹칠 수 있다"):
            self.assertIn(needle, row)
        self.assertNotIn("`bands.py` | 추천 구간", plan, "구간 계산은 score.py 에 있다 — bands.py 는 만들지 않았다")

    def test_the_plan_stays_within_400_lines_so_it_can_be_read_in_one_go(self):
        plan = (ts.ROOT / "docs" / "TOPIC_ENGINE_PLAN.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(plan.splitlines()), 400, "계획 문서가 400줄을 넘으면 다른 곳을 줄여 맞춘다")

    def test_the_plan_no_longer_says_the_package_does_not_exist_and_marks_the_stages(self):
        plan = (ts.ROOT / "docs" / "TOPIC_ENGINE_PLAN.md").read_text(encoding="utf-8")
        self.assertNotIn("**아직 코드에 없고** 해당 단계(P1~)", plan)
        self.assertNotIn("계획이다. `topics/`·`service/topics.py`", plan, "한계 첫 줄의 낡은 문장")
        for stage in ("P1 (병합됨, PR #23)", "**P2a** (지금)", "| P2b |"):
            with self.subTest(stage=stage):
                self.assertIn(stage, plan)

    def test_the_decisions_d43_to_d45_exist_once_each_in_order(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        found = re.findall(r"^\| (D-\d{2}) \|", text, re.M)
        self.assertEqual(found[-4:], ["D-42", "D-43", "D-44", "D-45"])
        self.assertEqual(len(found), len(set(found)))
        rows = {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| D-4")}
        self.assertIn("search_count_source", rows["D-43"])
        self.assertIn("180일", rows["D-44"])
        self.assertIn("숫자만으로 지우거나 제외하지 않는다", rows["D-45"])

    def test_the_package_does_not_turn_an_engine_candidate_into_an_existing_candidate_yet(self):
        for path in FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 2 and node.module == "content.candidates":
                    with self.subTest(module=path.name):
                        self.assertNotIn("Candidate", [alias.name for alias in node.names], "기존 후보로의 투영은 다음 묶음의 일이다")
            with self.subTest(module=path.name, what="calls"):
                self.assertFalse(any(isinstance(node, ast.Name) and node.id == "Candidate" for node in ast.walk(tree)))


if __name__ == "__main__":
    unittest.main()
