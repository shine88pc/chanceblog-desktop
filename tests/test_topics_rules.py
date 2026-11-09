"""주제 엔진(`topics/`)의 순수성 규칙을 소스에서 직접 확인하는 시험(AST 검사) — 서비스 층 안전 시험(`test_service_safety`)과 같은 정신이다. 규칙을 어기는 코드가 몰래 들어오면 여기서 걸린다.

지키는 것:
  1) 의존은 표준 라이브러리 몇 개와 `content`(채널 키·후보 검증 도구)·`errors`·같은 패키지뿐이다 — `service`·`ui`·`publish`·`render` 를 가져오지 않는다.
  2) 파일·네트워크·시계·난수·`sqlite3`·`subprocess`·`ctypes` 를 쓰지 않는다(날짜는 인자로 받고 같은 입력은 늘 같은 결과다). `print`·`open`·환경 변수도 쓰지 않는다.
  3) 오류를 삼키지 않고(맨 except·pass 뿐인 except 금지) 코드는 파이썬 3.10 문법이다. 보이지 않는 글자·BOM·이 PC 의 절대경로·키 낱말이 없다.
  4) `__init__.py` 는 설명뿐이고 `layout.py` 는 이름 상수뿐이다. 이 패키지를 쓰는 곳이 아직 없다(기존 동작은 하나도 바뀌지 않았다).
  5) 위 검사기 자신도 합성 소스로 시험한다 — 어긴 소스를 실제로 잡는다.
  6) P2a 가 더한 모듈(`seeds`·`schedule`·`dedupe`·`history`·`hold`)과 P2b 가 더한 모듈(`expand`·`feasibility`·`safety`·`generate`)에도 같은 검사가 그대로 걸린다. 모듈 목록 시험은 모듈을 더하거나 빼면 일부러 고쳐야 하는 시험이다.
  7) 기존 부품 중 이 패키지가 가져올 수 있는 것은 `content` 의 세 모듈·`errors` 와 **`check.claims` 하나**다(P2b — 계획 3.2 가 처음부터 허용한 순수 부품이고 `safety.py` 가 경험 단정 검사를 읽기만 하려고 쓴다). `check` 의 다른 모듈은 여전히 거절한다.
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
# 모듈을 더하거나 빼면 이 두 목록과 `docs/ARCHITECTURE.md` §5 의 `topics/` 행을 의식적으로 함께 고친다(P1 → P2a 에서 `dedupe`·`history`·`hold`·`schedule`·`seeds` 를, P2a → P2b 에서 `expand`·`feasibility`·`generate`·`safety` 를,
# P2b 보완에서 `wording`·`concepts`·`notice`·`brand` 를, P3 에서 `slots`·`trend` 를 더했다).
EXPECTED_FILES = ["__init__.py", "brand.py", "channels.py", "concepts.py", "dedupe.py", "expand.py", "feasibility.py", "generate.py", "history.py", "hold.py", "layout.py", "link.py", "model.py", "notice.py",
                  "safety.py", "schedule.py", "score.py", "seeds.py", "select.py", "slots.py", "trend.py", "wording.py"]
TOPIC_MODULES = {"brand", "channels", "concepts", "dedupe", "expand", "feasibility", "generate", "history", "hold", "layout", "link", "model", "notice", "safety", "schedule", "score", "seeds", "select", "slots", "trend",
                 "wording"}
P2A_MODULES = ("seeds.py", "schedule.py", "dedupe.py", "history.py", "hold.py")
P2B_MODULES = ("expand.py", "feasibility.py", "safety.py", "generate.py")
P2B_FIX_MODULES = ("wording.py", "concepts.py", "notice.py", "brand.py")
P3_MODULES = ("slots.py", "trend.py")
# P3b-1 의도적 갱신(D-120): `hashlib` 을 더했다 — 보류 후보 정리 확인 번호(`hold.cleanup_token`, SHA-256 앞 12자리)와 재생성 후보 번호(`hold.next_recreated_id`)를 만드는 데만 쓴다. 입출력·시계·난수가 없는 결정적인 계산이라 순수 규칙에 어긋나지 않는다.
ALLOWED_STDLIB = {"__future__", "collections", "dataclasses", "datetime", "enum", "fractions", "functools", "hashlib", "itertools", "math", "re", "types", "typing", "unicodedata"}
ALLOWED_INTERNAL = {"content.status", "content.candidates", "content.profiles", "errors", "check.claims"}
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

    def test_the_p2b_modules_are_in_the_list_the_checks_run_over_too(self):
        for name in P2B_MODULES:
            with self.subTest(module=name):
                self.assertIn(name, [path.name for path in FILES])
                self.assertIn(name[:-3], TOPIC_MODULES)

    def test_the_p2b_fix_modules_are_in_the_list_the_checks_run_over_too(self):
        for name in P2B_FIX_MODULES:
            with self.subTest(module=name):
                self.assertIn(name, [path.name for path in FILES])
                self.assertIn(name[:-3], TOPIC_MODULES)

    def test_the_p3_modules_are_in_the_list_the_checks_run_over_too(self):
        for name in P3_MODULES:
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
                if isinstance(node, ast.ImportFrom) and node.module != "check.claims":              # P2b 의도적 갱신: `check` 중 `check.claims` 하나만 허용한다(위 7번)
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
        self.assertIn("check.claims", used, "safety.py 가 경험 단정 검사를 읽는다")
        for path in FILES:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level == 2 and node.module == "check.claims":
                    with self.subTest(module=path.name):
                        self.assertEqual(path.name, "safety.py", "check.claims 를 읽는 곳은 안전 표시 하나뿐이다")

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
                       "from ..content.store import Store", "from ..content.suggest import suggest", "from ... import x", "from .. import service", "from .other import x", "from . import other",
                       "from ..check.similarity import similarity", "from ..check.profile_options import x", "from ..check import similarity", "from ...check.claims import find_violations"):
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
                       "from ..check.claims import find_violations", "from ..check.claims import LABELS as CLAIM_LABELS", "from .expand import stable_id", "from .safety import mark", "from . import generate, expand",
                       "from .feasibility import assess",
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

    def test_only_the_p3_storage_and_service_layers_use_the_package_so_no_other_behaviour_changed(self):
        # P3 의도적 갱신: 예전에는 쓰는 곳이 0 이었다(P1~P2b). P3 가 저장 계층(`topicdb/`)과 서비스·명령줄에 처음 이었다 — 그 밖의 곳(화면·글·발행·검사·보안…)은 여전히 이 패키지를 모른다.
        # 의도적 갱신(P4b, D-218): 블로그 관리 화면이 **상수만** 가져온다 — 서비스 `service/blog_profiles.py`(채널 프로필 읽기·쓰기)와 화면의 순수 규칙 `ui/core/blog_form.py`·`ui/core/blogs.py` 가 폼 칸의 길이·개수 상한과 허용 값(언어·색 프리셋)을
        # `topics.channels` 에서 가져온다(화면이 따로 베낀 숫자가 서비스 생성자의 판정과 어긋나 '화면은 통과시키는데 서비스는 거절' 하는 사고를 막으려고 — 시험이 수백 가지 입력으로 둘의 판정을 견준다). 저장·계산은 쓰지 않는다. 나머지 화면 코드(Qt 쪽 포함)는 여전히 이 패키지를 모른다.
        # 의도적 갱신(P4d, D-270): 주제 후보 화면의 실제 공급자 `ui/candidates_adapter.py`(서비스 읽기 결과를 화면 값으로 맞추고 점수·안전 평가의 순수 함수를 부른다)와 화면의 순수 규칙 `ui/core/candidates.py`·`candidate_rules.py`·`candidates_view.py` 가 이 패키지를 쓴다 —
        # 후보(`TopicCandidate`)·점수 구간·알림(`notice`)·한국어 이름 표(`wording`)를 화면이 따로 베끼지 않고 가져온다(홈과 같은 점수·구간·같은 문장이 나오게). 저장·후보 계산은 쓰지 않는다 — 쓰는 길은 서비스 함수 `generate_candidates` 하나다. Qt 쪽 코드는 여전히 이 패키지를 모른다.
        # 의도적 갱신(Seed 관리, D-231): 서비스 `service/seed_manage.py`(씨앗 읽기·쓰기 — `Seed` 생성자가 저장 직전의 진짜 심판이다)와 화면의 순수 규칙 `ui/core/seed_form.py`·`seed_rules.py`·`seeds.py`·`seeds_view.py` 가 이 패키지를 쓴다 —
        # 폼 칸의 길이·개수 상한과 허용 값(상태·소속·중요도·대상 유형·채널·협찬 분야 이름)을 화면이 따로 베끼지 않고 `topics.seeds`·`topics.channels`·`topics.wording` 에서 가져오고, 가짜 공급자가 서비스와 같은 `Seed` 생성자·`change_state` 를 심판으로 쓴다(시험이 둘의 판정을 견준다). Qt 쪽 코드는 여전히 이 패키지를 모른다.
        pattern = re.compile(r"(?m)^\s*(?:from\s+(?:[.\w]*\.)?topics\b|import\s+(?:[\w.]*\.)?topics\b|from\s+\.+\s+import\s+[^#\n]*\btopics\b)")
        # 의도적 갱신(규칙 기반 초안 본문 독립 검증 H2, D-260 ⑥): 서비스 `service/draft_body.py` 가 후보의 제목·키워드로 주제 엔진의 안전 판정(`topics.safety.check_text`)을 **불러 쓴다** — 자동 초안 중지(`stop`) 후보는 본문 전체에 같은 말이 되풀이되므로 만들지 않고 거절하려는 것이다.
        # 읽기만 하고 `topics/` 는 바꾸지 않으며(콘텐츠 층 `content/draft_body.py` 는 이 패키지를 가져오지 않고 결과의 속성만 읽는다) 저장·계산은 하지 않는다.
        users = sorted(path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py") if TOPICS not in path.parents and pattern.search(path.read_text(encoding="utf-8")))
        self.assertEqual(users, ["service/blog_profiles.py", "service/cli.py", "service/draft_body.py", "service/seed_manage.py", "service/topic_files.py", "service/topic_format.py", "service/topics.py", "topicdb/backup.py", "topicdb/store.py", "ui/candidates_adapter.py", "ui/core/blog_form.py", "ui/core/blogs.py", "ui/core/candidate_rules.py", "ui/core/candidates.py", "ui/core/candidates_view.py", "ui/core/seed_form.py", "ui/core/seed_rules.py", "ui/core/seeds.py", "ui/core/seeds_view.py"],
                         "이 패키지를 쓰는 곳을 늘리는 것은 의식적인 변경이다 — 이 목록과 결정 기록을 함께 고친다")

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

    def test_the_changelog_mentions_p2b_and_its_four_new_modules_and_says_the_tables_are_initial_values(self):
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("'P2b'", log)
        for name in P2B_MODULES:
            with self.subTest(module=name):
                self.assertIn(f"`{name}`", log)
        self.assertIn("초기값 — 전략 원문 확인 전", log)

    def test_the_changelog_mentions_the_p2b_fix_and_its_four_new_modules(self):
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("**P2b 보완**", log)
        for name in P2B_FIX_MODULES:
            with self.subTest(module=name):
                self.assertIn(f"`{name}`", log)
        self.assertIn("ExistingCount", log)

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
        for stage in ("P1 (병합됨, PR #23)", "| P2a (병합됨, PR #24) |", "| P2b (병합됨, PR #25) |", "| **P3** (지금) |"):                  # P3 의도적 갱신: P2a·P2b 는 병합됐고 지금은 P3
            with self.subTest(stage=stage):
                self.assertIn(stage, plan)

    def test_the_decisions_d42_to_d80_exist_once_each_in_order(self):                       # P3 수정 5차 의도적 갱신: 결정 D-80 이 이어 붙었다(수정 2차: D-75~D-79)
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        found = re.findall(r"^\| (D-\d{2}) \|", text, re.M)
        start = found.index("D-42")                    # 의도적 갱신(P3+P4a 병합): D-42~D-80 이 연달아 한 번씩 있다는 것만 본다 — 그 뒤에 붙는 다른 묶음의 번호(화면 묶음 D-90~ 등)는 이 시험이 보지 않는다
        self.assertEqual(found[start:start + 39], [f"D-{number}" for number in range(42, 81)])
        self.assertEqual(len(found), len(set(found)))
        rows = {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| D-4")}
        self.assertIn("search_count_source", rows["D-43"])
        self.assertIn("180일", rows["D-44"])
        self.assertIn("숫자만으로 지우거나 제외하지 않는다", rows["D-45"])
        for needle in ("active_since", "compared", "Mapping", "CONTENT_INVALID", "안내 틀"):                   # P2b: D-46 은 P2a 독립 검증의 중간 지적 인수
            self.assertIn(needle, rows["D-46"])
        for needle in ("safety_flags", "표시", "check.claims"):
            self.assertIn(needle, rows["D-47"])
        for needle in ("ALLOWED_FAMILIES", "초기값", "BASE_OUTLINES"):
            self.assertIn(needle, rows["D-48"])
        for needle in ("route_targets", "B=1", "C=0", "D=0", "E=4", "RealtimeItem"):
            self.assertIn(needle, rows["D-49"])
        fix = {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| D-5")}
        for number, needles in (("D-50", ("개념군", "HEALTH_MATRIX", "product_brand", "SafetyReport.stop", "forbidden_claim")), ("D-51", ("monetization_opportunity", "economic_relationship", "Campaign", "campaigns")),
                                ("D-52", ("hands-on", "my experience", "EXPERIENCE_PHRASES_EN", "토큰")), ("D-53", ("Notice", "INFO", "WARNING", "ERROR", "leaks", "BRAND_ONLY")),
                                ("D-54", ("EVIDENCE_PENALTY", "health_check", "experience_claim")),
                                ("D-55", ("brand_only", "brand_unfeasible", "최대 3", "초기값", "safety", "나열", "후속", "실시간", "모호")), ("D-56", ("remaining_slots", "expectedFailure", "11.1", "normalized_topic_hash")),
                                ("D-57", ("wording", "invalid_in", "dev", "PROBES")), ("D-58", ("compact_marked", "reads_as_one_word", "설치 매뉴얼", "맞바꿈", "_issue_key"))):          # 보완 1차: 낱말 경계·이슈 처리 순서
            for needle in needles:
                with self.subTest(decision=number, needle=needle):
                    self.assertIn(needle, fix[number])

    def test_the_p3_decisions_say_what_they_decided_in_words_the_code_and_tests_use(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        rows = {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| D-59 |") or line.startswith("| D-6")}
        for number, needles in (("D-59", ("slots", "remaining_slots", "draft_states", "ExistingCountP3Test", "UNRATED", "route_targets", "같은 후보")), ("D-60", ("TrendProvider", "NoTrend", "FakeTrend", "unavailable", "느린 응답", "interest_outage")),
                                ("D-61", ("topicdb", "application_id", "test_topicdb_rules", "FILE_WRITERS", "topic_engine", "한 바이트도")), ("D-62", ("처음 보류함에 든 때", "re_evaluate", "hold_box", "90일")),
                                ("D-63", ("MANIFEST", "before-restore", "has_key_shape", "TOPIC_BACKUP_INVALID")), ("D-64", ("--yes", "campaigns", "detail", "history_ledger", "TOPIC_STORE_CORRUPT"))):
            for needle in needles:
                with self.subTest(decision=number, needle=needle):
                    self.assertIn(needle, rows[number])

    def test_the_changelog_and_the_architecture_name_the_p3_modules_and_the_storage_package(self):
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("'P3'", log)
        for name in (*P3_MODULES, "topicdb/", "topics.py", "topic_files.py", "topic_format.py"):
            with self.subTest(name=name):
                self.assertIn(name, log)
        row = next(line for line in self.ARCH.splitlines() if line.startswith("| `topicdb/` |"))
        for name in ("file.py", "store.py", "backup.py"):
            self.assertIn(f"`{name}`", row)
        self.assertEqual(sum(line.startswith("| `topicdb/` |") for line in self.ARCH.splitlines()), 1)
        service_row = next(line for line in self.ARCH.splitlines() if line.startswith("| `service/` |"))
        for name in ("topics.py", "topic_files.py", "topic_format.py"):
            self.assertIn(f"`{name}`", service_row)

    def test_the_plan_has_the_p3_todo_section_with_the_counting_rule_and_the_same_candidate_rule(self):
        plan = (ts.ROOT / "docs" / "TOPIC_ENGINE_PLAN.md").read_text(encoding="utf-8")
        self.assertIn("### 11.1 P3 TODO", plan)
        section = plan.split("### 11.1 P3 TODO", 1)[1].split("## 12.", 1)[0]
        for needle in ("remaining_slots", "active_existing_count", "pending_review_count", "normalized_topic_hash", "work_status", "recommendation_band", "FOLLOW_ON", "hold.is_expired", "seed_id", "search_intent", "topic_angle",
                       "ExistingCountTodayTest", "ExistingCountP3Test", "expectedFailure"):
            with self.subTest(needle=needle):
                self.assertIn(needle, section)

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
