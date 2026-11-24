"""인터넷 접속 스위치 다섯과 관문 `require_net` 시험(NET 설계서 NT-01–NT-07 — 운영자 확인 038 ①, 결정 D-720–D-723).

지키는 것:
  1) 스위치 여덟(기존 셋 + 새 다섯)은 소스에서 글자 그대로 `False` 이고, **글자 그대로 `True` 일 때만** 열린다(참 비슷한 값 일곱 가지는 못 연다).
  2) 상수에 값을 넣는 곳은 `capabilities.py` 의 `= False` 한 번씩뿐이고 다른 모듈은 이름도 글자로도 쓰지 않는다 — 켜는 길이 설정·환경 변수·명령줄·화면에 없다.
  3) `capabilities.py` 는 바깥(환경 변수·파일·인자)을 읽지 않는다.
  4) `require_net(용도, 작업)` 은 `EXTERNAL_WRITE` + 새 상수 다섯의 64가지 조합 전부에서 설계서 3.3 의 진리표와 같게 지나거나 거절한다(시험은 표를 코드와 따로 적는다).
  5) `SWITCH_NAMES` = 소스의 대문자 상수 = 점검 도구의 표 = 출하 표 안의 이름 = 문서 표. 출하 표는 지금 비어 있다(켜진 것 0).
  6) 모르는 용도 이름은 거절한다. 한 스위치를 켜도 그 스위치의 용도만 열린다.
네트워크·실제 시크릿 없이 돈다(스위치는 `mock.patch.object` 로 임시로만 연다).
"""
import ast
import contextlib
import itertools
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))

import pkgcommon  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"
NEW_SWITCHES = ("NET_UPDATE_CHECK", "NET_PAGES_SITE", "PAGES_BRANCH_PUSH", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT")
OLD_SWITCHES = ("EXTERNAL_WRITE", "BLOGGER_OAUTH_INPUT", "LOCAL_OCR")
ALL_SWITCHES = OLD_SWITCHES + NEW_SWITCHES
READERS = {"EXTERNAL_WRITE": "external_write_enabled", "BLOGGER_OAUTH_INPUT": "blogger_oauth_input_enabled", "LOCAL_OCR": "local_ocr_enabled", "NET_UPDATE_CHECK": "net_update_check_enabled",
           "NET_PAGES_SITE": "net_pages_site_enabled", "PAGES_BRANCH_PUSH": "pages_branch_push_enabled", "NET_BLOGGER_OAUTH": "net_blogger_oauth_enabled", "NET_BLOGGER_DRAFT": "net_blogger_draft_enabled"}
LOOK_ALIKES = (1, "yes", "True", [1], object(), 2, "1")

# 설계서 3.3 의 진리표 — 코드(`require_net`)와 따로 적은 값이다. 용도 → (윗 스위치 `EXTERNAL_WRITE` 가 필요한가, 켜져 있어야 하는 새 상수들)
TRUTH = {
    "update_check": (False, ("NET_UPDATE_CHECK",)),
    "pages_site": (True, ("NET_PAGES_SITE",)),
    "pages_branch": (True, ("PAGES_BRANCH_PUSH",)),
    "blogger_oauth": (False, ("NET_BLOGGER_OAUTH",)),
    "blogger_read": (False, ("NET_BLOGGER_OAUTH",)),
    "blogger_draft": (True, ("NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT")),
}


def src_files():
    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)


def set_switches(**values):
    """여러 상수를 한꺼번에 임시로 바꾼다(`with` 로 쓴다)."""
    stack = contextlib.ExitStack()
    for name, value in values.items():
        stack.enter_context(mock.patch.object(capabilities, name, value))
    return stack


def verdict(use):
    """`require_net(use, ...)` 의 결과 — 통과면 None, 거절이면 오류 코드."""
    try:
        capabilities.require_net(use, "시험 작업")
    except AppError as error:
        return error.code
    return None


def expected(use, on):
    """진리표에서 기대하는 결과. `on` 은 켜진 상수 이름들의 집합."""
    needs_write, needed = TRUTH[use]
    if needs_write and "EXTERNAL_WRITE" not in on:
        return "EXTERNAL_WRITE_DISABLED"
    if not all(name in on for name in needed):
        return "NETWORK_DISABLED"
    return None


class SwitchConstantsTest(unittest.TestCase):
    def test_every_switch_is_false_in_source_and_only_literal_true_opens_it(self):
        """NT-01 — 출하 값은 모두 False 이고(출하 표가 비어 있다), 참 비슷한 값 일곱 가지로는 읽는 함수도 관문도 열리지 않는다."""
        self.assertEqual(pkgcommon.SHIPPED_OPEN_SWITCHES, (), "지금 켜진 채 내보내도 되는 스위치는 0 이다 — 켜려면 갈래마다 새 번호를 받는다")
        for name in ALL_SWITCHES:
            with self.subTest(name=name):
                self.assertIs(getattr(capabilities, name), False)
                self.assertIs(getattr(capabilities, READERS[name])(), False)
        self.assertEqual(capabilities.open_switch_names(), ())
        for name in ALL_SWITCHES:
            for value in LOOK_ALIKES:
                with self.subTest(name=name, value=repr(value)[:20]), set_switches(**{name: value}):
                    self.assertIs(getattr(capabilities, READERS[name])(), False)
                    self.assertEqual(capabilities.open_switch_names(), ())
            with self.subTest(name=name, value="True"), set_switches(**{name: True}):
                self.assertIs(getattr(capabilities, READERS[name])(), True)
                self.assertEqual(capabilities.open_switch_names(), (name,))
        for name in ALL_SWITCHES:
            self.assertIs(getattr(capabilities, name), False, "시험의 임시 켜기는 끝나면 원래대로다")

    def test_look_alike_values_never_open_a_use_even_when_everything_else_is_open(self):
        """NT-01(참 비슷한 값) — 나머지가 모두 열려 있어도 한 상수만 참 비슷한 값이면 그 상수에 기대는 용도는 열리지 않는다(`is True` 를 `if 값:` 으로 바꾼 변이를 잡는다)."""
        everything = {name: True for name in ("EXTERNAL_WRITE",) + NEW_SWITCHES}
        with set_switches(**everything):
            for use in TRUTH:
                self.assertIsNone(verdict(use), use)
        for name in ("EXTERNAL_WRITE",) + NEW_SWITCHES:
            for value in LOOK_ALIKES:
                with self.subTest(name=name, value=repr(value)[:20]), set_switches(**{**everything, name: value}):
                    on = {key for key in everything if key != name}
                    for use in TRUTH:
                        self.assertEqual(verdict(use), expected(use, on), f"{use}: {name}={value!r}")

    def test_the_gate_refuses_with_the_catalog_codes_and_names_the_operation(self):
        with self.assertRaises(AppError) as caught:
            capabilities.require_net("update_check", "업데이트 확인")
        error = caught.exception
        self.assertEqual((error.code, error.slots), ("NETWORK_DISABLED", {"작업": "업데이트 확인"}))
        shown = error.rendered()
        self.assertIn("업데이트 확인", shown.message)
        self.assertIn("꺼져", shown.message)
        self.assertEqual(shown.retry_kind, "no")
        with self.assertRaises(AppError) as caught:
            capabilities.require_net("pages_site", "공개 주소 확인")
        self.assertEqual(caught.exception.code, "EXTERNAL_WRITE_DISABLED", "윗 스위치가 필요한 용도는 옛 문구 그대로 거절한다")


class NoWayToTurnThemOnTest(unittest.TestCase):
    """NT-02·NT-03 — 소스에서 직접 확인한다(설정 파일·환경 변수·명령줄·화면에 켜는 길이 없다)."""

    def test_each_switch_is_assigned_once_in_capabilities_and_named_nowhere_else(self):
        stores = {name: [] for name in ALL_SWITCHES}
        outside = []
        for path in src_files():
            rel = path.relative_to(SRC).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for target in targets:
                    for item in ast.walk(target):
                        name = item.id if isinstance(item, ast.Name) else item.attr if isinstance(item, ast.Attribute) else None
                        if name in stores:
                            stores[name].append((rel, node.lineno, ast.unparse(node.value) if getattr(node, "value", None) is not None else ""))
                if rel == "capabilities.py":
                    continue
                if (isinstance(node, ast.Name) and node.id in stores) or (isinstance(node, ast.Attribute) and node.attr in stores) or (isinstance(node, ast.Constant) and node.value in stores):
                    outside.append((rel, getattr(node, "lineno", 0)))           # 이름을 글자로 쓰는 길(setattr·환경 변수 이름)도 없다
        for name, found in stores.items():
            with self.subTest(name=name):
                self.assertEqual([(rel, value) for rel, _line, value in found], [("capabilities.py", "False")], f"{name}: 소스 상수에 값을 넣는 곳은 capabilities.py 의 `{name} = False` 하나뿐이다")
        self.assertEqual(outside, [], "capabilities.py 밖에서는 스위치 이름을 쓰지 않는다 — 부르는 것은 읽는 함수와 관문 함수뿐이다")

    def test_capabilities_still_reads_nothing_from_outside(self):
        text = (SRC / "capabilities.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        body = "\n".join(ast.unparse(node) for node in tree.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)))
        for word in ("environ", "getenv", "argv", "settings", "json", "open(", "read_text", "import os", "import sys", "argparse", "socket", "ssl", "http", "urllib", "subprocess"):
            self.assertNotIn(word, body, f"capabilities.py 는 바깥에서 값을 읽지 않고 접속하지도 않는다: {word}")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        for name in ALL_SWITCHES:
            self.assertIn(f"{name} = False", code, name)
        imports = [ast.unparse(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, ["from __future__ import annotations", "from .errors import AppError"], "capabilities.py 가 가져오는 것은 오류 클래스 하나뿐이다")

    def test_the_settings_file_and_the_command_line_have_no_way_to_set_a_switch(self):
        context = (SRC / "service" / "context.py").read_text(encoding="utf-8")
        for name in ALL_SWITCHES:
            self.assertNotIn(name, context, name)
            self.assertNotIn(name.lower(), context, name)
        from chanceblog_desktop.service import cli
        words = set()
        stack = [cli.build_parser()]
        import argparse
        while stack:
            current = stack.pop()
            for action in current._actions:
                words.update(action.option_strings)
                if isinstance(action, argparse._SubParsersAction):
                    words.update(action.choices)
                    stack.extend(action.choices.values())
        for word in words:
            self.assertIsNone(re.search(r"(?i)net-|network|internet|switch|enable|allow|unlock|external", word), f"켜는 길처럼 보이는 명령·옵션: {word}")


class UseTableTest(unittest.TestCase):
    def test_use_table_needs_exactly_the_documented_switches(self):
        """NT-04 — `EXTERNAL_WRITE` + 새 상수 다섯의 64가지 조합 전부에서 용도 여섯의 결과가 진리표와 같다."""
        self.assertEqual(sorted(capabilities.NET_USES), sorted(TRUTH))
        names = ("EXTERNAL_WRITE",) + NEW_SWITCHES
        ran = 0
        for bits in itertools.product((False, True), repeat=len(names)):
            on = {name for name, bit in zip(names, bits) if bit}
            with set_switches(**dict(zip(names, bits))):
                for use in TRUTH:
                    self.assertEqual(verdict(use), expected(use, on), f"{use} 켜진 것={sorted(on)}")
                    ran += 1
        self.assertEqual(ran, 64 * 6)

    def test_the_two_old_switches_that_are_not_net_uses_never_open_a_net_use(self):
        with set_switches(BLOGGER_OAUTH_INPUT=True, LOCAL_OCR=True):
            for use in TRUTH:
                self.assertEqual(verdict(use), expected(use, set()), use)

    def test_unknown_use_name_is_refused(self):
        """NT-06 — 모르는 용도 이름은 모든 스위치가 열려 있어도 `NETWORK_DISABLED` 로 거절한다."""
        everything = {name: True for name in ("EXTERNAL_WRITE",) + NEW_SWITCHES}
        with set_switches(**everything):
            for use in ("", "x", "Update_Check", "update_check ", " update_check", "update-check", "pages", "pages_site2", "blogger", "git", "naver_publish", "UPDATE_CHECK", None, 1, ("update_check",)):
                with self.subTest(use=repr(use)):
                    self.assertEqual(verdict(use), "NETWORK_DISABLED")

    def test_flipping_one_switch_changes_only_its_own_uses(self):
        """NT-07 — 한 스위치만 켜면 그 스위치에 기대는(그리고 나머지 조건이 이미 충족된) 용도만 열리고, 한 스위치만 끄면 그것에 기대는 용도만 닫힌다."""
        names = ("EXTERNAL_WRITE",) + NEW_SWITCHES
        for name in names:
            with self.subTest(only=name), set_switches(**{name: True}):
                opened = sorted(use for use in TRUTH if verdict(use) is None)
                self.assertEqual(opened, sorted(use for use in TRUTH if expected(use, {name}) is None))
        with set_switches(EXTERNAL_WRITE=True):
            self.assertEqual([use for use in TRUTH if verdict(use) is None], [], "`EXTERNAL_WRITE` 만 켜서는 아무것도 열리지 않는다 — 좁은 스위치가 함께 있어야 한다")
        everything = {name: True for name in names}
        for name in names:
            with self.subTest(all_but=name), set_switches(**{**everything, name: False}):
                closed = sorted(use for use in TRUTH if verdict(use) is not None)
                depends = sorted(use for use, (needs_write, needed) in TRUTH.items() if name in needed or (name == "EXTERNAL_WRITE" and needs_write))
                self.assertEqual(closed, depends)

    def test_the_gate_never_opens_with_no_open_switch_in_the_default_build(self):
        for use in TRUTH:
            self.assertIsNotNone(verdict(use), use)
        self.assertEqual({verdict(use) for use in TRUTH}, {"NETWORK_DISABLED", "EXTERNAL_WRITE_DISABLED"})


class SwitchTablesTest(unittest.TestCase):
    def source_constants(self):
        """`capabilities.py` 의 맨 위 대문자 상수 가운데 True/False 값을 가진 것(스위치) — 소스에서 직접 읽는다."""
        found = []
        for node in ast.parse((SRC / "capabilities.py").read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper():
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
                    found.append(node.targets[0].id)
        return found

    def doc_table_names(self):
        text = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
        section = text.split("### 스위치 표", 1)[1].split("\n### ", 1)[0]
        return [match.group(1) for match in re.finditer(r"(?m)^\| `([A-Z][A-Z_]+)` \|", section)]

    def test_switch_names_cover_every_constant_and_match_the_shipped_table_and_the_doc_table(self):
        """NT-05 — 새 상수를 `SWITCH_NAMES`·점검 도구의 표·문서 표에서 빼먹으면 빨개진다."""
        source = self.source_constants()
        self.assertEqual(sorted(capabilities.SWITCH_NAMES), sorted(source), "`SWITCH_NAMES` 가 소스의 대문자 상수와 다르다")
        self.assertEqual(len(set(capabilities.SWITCH_NAMES)), len(capabilities.SWITCH_NAMES))
        self.assertEqual(sorted(pkgcommon.GATE_CONSTANTS), sorted(capabilities.SWITCH_NAMES), "점검 도구(`pkgcommon.GATE_CONSTANTS`)의 표가 `SWITCH_NAMES` 와 다르다")
        self.assertEqual(sorted(capabilities.SWITCH_NAMES), sorted(ALL_SWITCHES))
        self.assertTrue(set(pkgcommon.SHIPPED_OPEN_SWITCHES) <= set(capabilities.SWITCH_NAMES))
        self.assertTrue(set(pkgcommon.INFORMATIONAL_SWITCHES) <= set(capabilities.SWITCH_NAMES))
        self.assertEqual(sorted(self.doc_table_names()), sorted(capabilities.SWITCH_NAMES), "docs/SECURITY.md 의 스위치 표가 `SWITCH_NAMES` 와 다르다")
        self.assertEqual(len(self.doc_table_names()), len(set(self.doc_table_names())))
        shipped_in_source = sorted(name for name in source if getattr(capabilities, name) is True)
        self.assertEqual(shipped_in_source, sorted(pkgcommon.SHIPPED_OPEN_SWITCHES), "소스에서 켜진 상수가 출하 표와 다르다")

    def test_every_reader_function_is_exported_and_matches_its_constant(self):
        for name, reader in READERS.items():
            self.assertIn(reader, capabilities.__all__, reader)
            self.assertIn(name, capabilities.__all__, name)
        self.assertIn("require_net", capabilities.__all__)
        self.assertIn("open_switch_names", capabilities.__all__)

    def test_the_doc_table_says_every_switch_ships_off_and_names_its_use(self):
        text = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
        section = text.split("### 스위치 표", 1)[1].split("\n### ", 1)[0]
        for name in ALL_SWITCHES:
            row = next(line for line in section.splitlines() if line.startswith(f"| `{name}` |"))
            self.assertIn("False", row, name)
        for use in TRUTH:
            self.assertIn(f"`{use}`", text.split("### 용도 표", 1)[1].split("\n### ", 1)[0], use)


if __name__ == "__main__":
    unittest.main()
