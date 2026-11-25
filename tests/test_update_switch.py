"""`UPDATE_APPLY` 스위치와 시작 파일의 꺼진 후크 시험(UPDATE 설계서 3-5·3-9, 운영자 확인 038 ①, v1update U-2).

지키는 것:
  1) `UPDATE_APPLY` 는 소스에서 글자 그대로 `False` 이고 `capabilities.py` 에만 값이 있다(출하 표는 비어 있다). 읽는 함수는 글자 그대로 `True` 일 때만 참이다(참 비슷한 값 거절).
     관문 `require_update_apply(작업)` 은 꺼져 있으면 `UPDATE_DISABLED`(작업 이름이 문구에 들어간다)이고 켜져 있으면 지난다.
  2) **두 스위치는 따로 켜진다** — `NET_UPDATE_CHECK`(확인·내려받기)를 켜도 설치는 열리지 않고, `UPDATE_APPLY` 를 켜도 어떤 접속 용도(`require_net`)도 열리지 않는다(확인만 켜고 설치는 꺼 두는 단계).
  3) 시작 파일 후크(`gui_entry.note_update_boot`)는 **꺼진 채**다 — 스위치가 꺼져 있으면 데이터 폴더의 상태 파일을 읽지도 쓰지도 않고, 켜져 있어도 후크의 어떤 실패도 화면 시작을 막지 않는다. `start_gui` 에서 호출은 정확히 한 곳이고 화면 모듈을 불러오기 전이다.
네트워크·실제 시크릿 없이 돈다(스위치는 시험이 임시로만 켠다).
"""
import ast
import contextlib
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))

import capability_support as cap  # noqa: E402
import gui_entry  # noqa: E402
import pkgcommon  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.update import state  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"
PENDING = state.Pending("1.0.0", "1.0.1", 20261201030000, "full-20261201-040000", "2026-12-01T04:00:00Z", 0, "velopack")


def switches(**values):
    stack = contextlib.ExitStack()
    for name, value in values.items():
        stack.enter_context(mock.patch.object(capabilities, name, value))
    return stack


class SwitchTest(unittest.TestCase):
    def test_it_ships_off_and_only_a_literal_true_opens_it(self):
        self.assertIs(capabilities.UPDATE_APPLY, False)
        self.assertIs(capabilities.update_apply_enabled(), False)
        self.assertNotIn("UPDATE_APPLY", pkgcommon.SHIPPED_OPEN_SWITCHES)
        self.assertIn("UPDATE_APPLY", pkgcommon.GATE_CONSTANTS)
        self.assertIn("UPDATE_APPLY", capabilities.SWITCH_NAMES)
        self.assertNotIn("UPDATE_APPLY", capabilities.NET_USES)
        for value in (1, "yes", "True", [1], object(), 2, "1"):
            with switches(UPDATE_APPLY=value):
                self.assertIs(capabilities.update_apply_enabled(), False, repr(value))
                self.assertEqual(capabilities.open_switch_names(), ())
                with self.assertRaises(AppError):
                    capabilities.require_update_apply("업데이트 설치")
        with switches(UPDATE_APPLY=True):
            self.assertIs(capabilities.update_apply_enabled(), True)
            self.assertEqual(capabilities.open_switch_names(), ("UPDATE_APPLY",))
            capabilities.require_update_apply("업데이트 설치")

    def test_the_gate_refuses_with_the_catalog_code_and_names_the_operation(self):
        with self.assertRaises(AppError) as caught:
            capabilities.require_update_apply("업데이트 설치")
        error = caught.exception
        self.assertEqual((error.code, error.slots), ("UPDATE_DISABLED", {"작업": "업데이트 설치"}))
        shown = error.rendered()
        self.assertIn("업데이트 설치", shown.message)
        self.assertIn("꺼져", shown.message)
        self.assertEqual(shown.retry_kind, "no")
        self.assertIn("릴리스 페이지", shown.action)

    def test_the_constant_is_assigned_once_in_capabilities_and_named_nowhere_else(self):
        stores, outside = [], []
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(SRC).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "UPDATE_APPLY":
                            stores.append((rel, ast.unparse(node.value)))
                if rel != "capabilities.py" and ((isinstance(node, ast.Name) and node.id == "UPDATE_APPLY") or (isinstance(node, ast.Attribute) and node.attr == "UPDATE_APPLY")
                                                or (isinstance(node, ast.Constant) and node.value == "UPDATE_APPLY")):
                    outside.append(rel)
        self.assertEqual(stores, [("capabilities.py", "False")])
        self.assertEqual(outside, [], "다른 모듈은 읽는 함수와 관문만 부른다")

    def test_the_security_doc_table_lists_it_as_shipped_off(self):
        text = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
        section = text.split("### 스위치 표", 1)[1].split("\n### ", 1)[0]
        row = next(line for line in section.splitlines() if line.startswith("| `UPDATE_APPLY` |"))
        self.assertIn("False", row)
        self.assertIn("update_apply_enabled()", row)


class IndependenceTest(unittest.TestCase):
    NET_ALL = ("EXTERNAL_WRITE", "NET_UPDATE_CHECK", "NET_PAGES_SITE", "PAGES_BRANCH_PUSH", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT")

    def verdict_net(self, use):
        try:
            capabilities.require_net(use, "시험")
        except AppError as error:
            return error.code
        return None

    def verdict_apply(self):
        try:
            capabilities.require_update_apply("시험")
        except AppError as error:
            return error.code
        return None

    def test_the_apply_switch_alone_opens_no_net_use_and_no_net_switch_opens_apply(self):
        with switches(UPDATE_APPLY=True):
            for use in capabilities.NET_USES:
                self.assertIsNotNone(self.verdict_net(use), use)
        with switches(**{name: True for name in self.NET_ALL}):
            self.assertEqual(self.verdict_apply(), "UPDATE_DISABLED")
            self.assertIsNone(self.verdict_net("update_check"))

    def test_all_sixty_four_combinations_of_the_net_switches_leave_apply_closed_and_the_reverse_holds(self):
        for bits in itertools.product((False, True), repeat=len(self.NET_ALL)):
            with switches(**dict(zip(self.NET_ALL, bits))):
                self.assertEqual(self.verdict_apply(), "UPDATE_DISABLED", bits)
            with switches(**dict(zip(self.NET_ALL, bits)), UPDATE_APPLY=True):
                self.assertIsNone(self.verdict_apply())
                expected_update_check = None if dict(zip(self.NET_ALL, bits))["NET_UPDATE_CHECK"] else "NETWORK_DISABLED"
                self.assertEqual(self.verdict_net("update_check"), expected_update_check, bits)

    def test_check_on_and_apply_off_is_a_reachable_stage(self):
        with switches(NET_UPDATE_CHECK=True):
            self.assertIsNone(self.verdict_net("update_check"))
            self.assertEqual(self.verdict_apply(), "UPDATE_DISABLED")


class HookTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.data = Path(holder.name)
        self.folder = self.data / "update"
        state.write_state(self.folder, state.State(pending=PENDING))
        self.addCleanup(cap.switch_off, "UPDATE_APPLY")
        env = mock.patch.dict(os.environ, {"CHANCEBLOG_DESKTOP_DATA": str(self.data)})
        env.start()
        self.addCleanup(env.stop)
        version = mock.patch.object(state, "read_current_version", return_value="1.0.1")
        version.start()
        self.addCleanup(version.stop)

    def attempts(self):
        return state.read_state(self.folder).pending.boot_attempts

    def test_off_means_the_hook_touches_nothing(self):
        before = (self.folder / "state.json").read_bytes()
        names = sorted(path.name for path in self.data.rglob("*"))
        self.assertIsNone(gui_entry.note_update_boot())
        self.assertEqual((self.folder / "state.json").read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.data.rglob("*")), names)

    def test_on_it_counts_the_start_and_the_third_start_offers_recovery(self):
        cap.switch_on("UPDATE_APPLY")
        self.assertEqual(gui_entry.note_update_boot().action, "first_boot")
        self.assertEqual(self.attempts(), 1)
        gui_entry.note_update_boot()
        self.assertEqual(gui_entry.note_update_boot().action, "recovery_offered")

    def test_a_failing_hook_never_stops_the_start(self):
        cap.switch_on("UPDATE_APPLY")
        with mock.patch.object(state, "note_boot", side_effect=RuntimeError("secret C:/Users/someone")):
            self.assertIsNone(gui_entry.note_update_boot())
        with mock.patch.dict(sys.modules, {"chanceblog_desktop.update": None}):
            self.assertIsNone(gui_entry.note_update_boot())

    def test_start_gui_calls_the_hook_exactly_once_before_the_launcher_is_imported(self):
        tree = ast.parse((ROOT / "packaging" / "gui_entry.py").read_text(encoding="utf-8"))
        start = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "start_gui")
        calls = [node for node in ast.walk(start) if isinstance(node, ast.Call) and ast.unparse(node.func) == "note_update_boot"]
        self.assertEqual(len(calls), 1)
        launcher_import = next(node for node in ast.walk(start) if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("ui.launcher"))
        self.assertLess(calls[0].lineno, launcher_import.lineno)
        everywhere = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) in ("note_update_boot", "update_state.note_boot")]
        self.assertEqual(sorted(ast.unparse(node.func) for node in everywhere), ["note_update_boot", "update_state.note_boot"], "시작 파일 전체에서 후크는 이 두 줄뿐이다")

    def test_the_selftest_and_the_refused_argument_paths_do_not_run_the_hook(self):
        with mock.patch.object(gui_entry, "note_update_boot", side_effect=AssertionError("부르면 안 된다")):
            spoken = []
            self.assertEqual(gui_entry.main(["--bad"], say=lambda text, error=False: spoken.append(text)), gui_entry.EXIT_USAGE)
        self.assertEqual(spoken, [gui_entry.REFUSED])

    def test_start_gui_with_the_switch_off_leaves_the_state_file_alone(self):
        before = (self.folder / "state.json").read_bytes()
        with mock.patch("chanceblog_desktop.ui.launcher.main", return_value=0):
            self.assertEqual(gui_entry.start_gui(), 0)
        self.assertEqual((self.folder / "state.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
