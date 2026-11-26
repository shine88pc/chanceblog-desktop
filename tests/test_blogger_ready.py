"""Blogger 켜기 준비(B5) 시험 — 스위치 세 개의 출하 표(켜지 않는다)·점검(`doctor`) 줄·진입점 관문·등록 (BLOGGER 설계서 3.3·7장 B5, 결정 D-777).

지키는 것:
  1) **지금 출하 표는 비어 있고 어느 Blogger 스위치도 켜져 있지 않다.** 켜는 변경은 상수 한 줄 + 출하 표 한 줄이고 단계마다 따로 번호를 받는다: 1단계(`BLOGGER_OAUTH_INPUT`·`NET_BLOGGER_OAUTH`)·2단계(`EXTERNAL_WRITE`·`NET_BLOGGER_DRAFT`).
     묶음 점검(`gui_entry.check_capabilities`)은 켜진 상수의 집합이 출하 표와 **정확히 같을 때만** 통과한다 — 그 표를 시험 안에서 임시로 바꿔 두 단계의 모양을 미리 확인한다(실제 상수는 건드리지 않는다).
  2) Blogger 의 접속 용도 셋은 자리표시자가 아니다(`PLACEHOLDER_USES` 밖) — 켤 수 있다.
  3) `doctor` 의 Blogger 줄은 읽기만 한다(접속·파일 만들기 없음) · 스위치가 하나라도 열려 있으면 경고로 보인다.
  4) 새 외부 쓰기 진입점은 첫 문장이 옛 관문이고 둘째 문장이 좁은 관문이다(BT-80) · 등록은 `wiring.py` 한 곳의 스위치 `if` 안뿐이고 켜진 로그인 스위치에서만 Blogger 어댑터가 꽂힌다.
"""
import ast
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "packaging"))
import outgoing_support as og  # noqa: E402
import packaging_support as ps  # noqa: E402
import service_support as ss  # noqa: E402
import test_external_write_gate as gate  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.net import endpoints  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.service import cli, doctor, external, wiring  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402

ge, pc = ps.gui_entry, ps.pkgcommon
SRC = ROOT / "src" / "chanceblog_desktop"
BLOGGER_SWITCHES = ("BLOGGER_OAUTH_INPUT", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT")
STAGE_ONE = ("BLOGGER_OAUTH_INPUT", "NET_BLOGGER_OAUTH")
STAGE_TWO = STAGE_ONE + ("EXTERNAL_WRITE", "NET_BLOGGER_DRAFT")


class ShippedTableTest(unittest.TestCase):
    ALL_OFF = {name: False for name in pc.GATE_CONSTANTS if name not in pc.INFORMATIONAL_SWITCHES}

    def module(self, **opened):
        import types
        module = types.SimpleNamespace(**{**self.ALL_OFF, **{name: True for name in opened}})
        return lambda name: module

    def test_nothing_is_open_and_the_table_is_empty_in_this_build(self):
        self.assertEqual(pc.SHIPPED_OPEN_SWITCHES, ())
        for name in BLOGGER_SWITCHES + ("EXTERNAL_WRITE",):
            self.assertIs(getattr(capabilities, name), False, name)
            self.assertIn(name, capabilities.SWITCH_NAMES)
            self.assertIn(name, pc.GATE_CONSTANTS)
        self.assertEqual(capabilities.open_switch_names(), ())

    def test_the_two_stages_pass_the_package_check_only_with_exactly_their_switches_open(self):
        """켜는 변경은 상수 한 줄 + 출하 표 한 줄 — 둘이 어긋나면 묶음이 만들어지지 않는다. 1단계와 2단계의 모양을 표를 임시로 바꿔 확인한다."""
        for stage, name in ((STAGE_ONE, "1단계"), (STAGE_TWO, "2단계")):
            with mock.patch.object(pc, "SHIPPED_OPEN_SWITCHES", stage):
                self.assertEqual(ge.check_capabilities(import_module=self.module(**{item: True for item in stage})).status, "ok", name)
                for left_out in stage:
                    rest = {item: True for item in stage if item != left_out}
                    closed = ge.check_capabilities(import_module=self.module(**rest))
                    self.assertEqual(closed.status, "fail", f"{name}: 표에 있는데 꺼진 것 {left_out}")
                    self.assertIn(left_out, closed.text)
                for extra in ("NET_PAGES_SITE", "PAGES_BRANCH_PUSH", "NET_UPDATE_CHECK") + tuple(item for item in STAGE_TWO if item not in stage):
                    over = ge.check_capabilities(import_module=self.module(**{item: True for item in (*stage, extra)}))
                    self.assertEqual(over.status, "fail", f"{name}: 표 밖이 켜짐 {extra}")
                    self.assertIn(extra, over.text)
        self.assertEqual(ge.check_capabilities(import_module=self.module(NET_BLOGGER_OAUTH=True)).status, "fail", "지금의 빈 표에서는 하나만 켜져도 실패")

    def test_the_three_blogger_uses_are_not_placeholders_so_their_switches_can_be_shipped_later(self):
        self.assertTrue(set(endpoints.PLACEHOLDER_USES).isdisjoint({"blogger_oauth", "blogger_read", "blogger_draft"}))
        for use in ("blogger_oauth", "blogger_read", "blogger_draft"):
            self.assertIn(use, capabilities.NET_USES)
            self.assertIn(use, endpoints.ENDPOINTS)

    def test_the_switch_names_appear_nowhere_outside_capabilities_and_the_packaging_table(self):
        for path in sorted(SRC.rglob("*.py")):
            if path.name == "capabilities.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotIn(node.value, BLOGGER_SWITCHES, f"{path.name}: 스위치 이름을 글자로 쓰지 않는다 — 읽는 함수만 부른다")


class DoctorLineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.ctx = ss.make_ctx(Path(tmp.name), repo=None)
        self.ctx.keystore = MemoryStore()

    def test_the_blogger_line_is_ok_and_read_only_when_everything_is_closed(self):
        before = ss.tree_snapshot(Path(self.ctx.workspace.root).parent)
        with og.Tripwire() as wire:
            results = doctor.run_doctor(self.ctx)
        line = next(item for item in results if item.name == "Blogger")
        self.assertEqual((line.status, line.code), ("ok", ""))
        self.assertIn("닫혀 있어요", line.message)
        self.assertIn("연결 항목은 0개" if "연결 항목은" in line.message else "항목은 0개", line.message)
        self.assertEqual((wire.calls, ss.tree_snapshot(Path(self.ctx.workspace.root).parent)), ([], before), "점검은 접속하지도 파일을 만들지도 않는다")
        names = [item.name for item in results]
        self.assertLess(names.index("인터넷 접속"), names.index("Blogger"))

    def test_any_open_blogger_switch_is_a_warning_naming_what_is_open(self):
        for patches, word in (({"BLOGGER_OAUTH_INPUT": True}, "입력 칸"), ({"NET_BLOGGER_OAUTH": True}, "로그인·읽기"), ({"NET_BLOGGER_DRAFT": True}, "초안 저장")):
            with mock.patch.multiple(capabilities, **patches):
                line = doctor._check_blogger(self.ctx)
            self.assertEqual(line.status, "warn", patches)
            self.assertIn(word, line.message)
            self.assertIn("개발·시험용 빌드", line.message)

    def test_the_line_counts_saved_entries_without_reading_any_key(self):
        with mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True):
            cn.add_entry(self.ctx, "blogger", name="영문", fields={"client_id": "BloggerClient0001.apps.example", "client_secret": "S3cretValue" + "ForTheTest0001"}, keystore=self.ctx.keystore)
        gets = []
        real = MemoryStore.get
        with mock.patch.object(MemoryStore, "get", lambda store, ref: gets.append(ref) or real(store, ref)):
            line = doctor._check_blogger(self.ctx)
        self.assertEqual(gets, [], "값 묶음을 꺼내지 않는다")
        self.assertIn("1개", line.message)


class EntryPointsAndRegistrationTest(unittest.TestCase):
    def statements(self, rel, name):
        return [ast.unparse(node) for node in gate.statements(gate.function_node(gate.parse(rel), name))]

    def test_every_new_write_entry_point_passes_the_old_gate_then_the_narrow_gate(self):
        """BT-80 — 쓰기(초안 저장) 셋: 첫 문장 옛 관문, 둘째 문장 `require_net("blogger_draft")`."""
        for rel, name in (("service/blogger_flow.py", "save_draft"), ("publish/blogger.py", "insert_draft"), ("service/cli.py", "cmd_blogger_save_draft")):
            with self.subTest(entry=f"{rel}:{name}"):
                body = self.statements(rel, name)
                self.assertTrue(body[0].startswith("capabilities.require_external_write("), body[0][:60])
                self.assertTrue(body[1].startswith("capabilities.require_net(") and ("'blogger_draft'" in body[1] or "USE_DRAFT" in body[1]), body[1][:60])
                self.assertIn((rel, name), gate.ENTRY_POINTS)

    def test_every_new_read_and_login_entry_point_passes_its_narrow_gate_first(self):
        table = {("service/blogger_flow.py", "login"): "'blogger_oauth'", ("service/blogger_flow.py", "check"): "'blogger_read'", ("service/blogger_flow.py", "disconnect"): "'blogger_oauth'",
                 ("service/cli.py", "cmd_blogger_login"): "'blogger_oauth'", ("service/cli.py", "cmd_blogger_check"): "'blogger_read'", ("service/cli.py", "cmd_blogger_disconnect"): "'blogger_oauth'",
                 ("net/loopback.py", "open_listener"): "'blogger_oauth'", ("net/loopback.py", "LoopbackListener.wait"): "'blogger_oauth'"}
        for (rel, name), use in table.items():
            with self.subTest(entry=f"{rel}:{name}"):
                self.assertTrue(self.statements(rel, name)[0].startswith(f"capabilities.require_net({use},"))

    def test_the_status_command_has_no_gate_because_it_never_connects(self):
        body = self.statements("service/cli.py", "cmd_blogger_status")
        self.assertFalse(any("require_" in line for line in body))
        flow_body = self.statements("service/blogger_flow.py", "status")
        self.assertFalse(any("require_net" in line or "require_external_write" in line for line in flow_body))

    def test_the_blogger_adapter_is_registered_only_when_the_login_switch_is_open_and_the_factory_is_the_real_one(self):
        self.assertEqual(external.registered_kinds(), ())
        with mock.patch.object(capabilities, "NET_BLOGGER_DRAFT", True), mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
            self.assertEqual(wiring.register_enabled(), (), "쓰기 스위치만으로는 아무것도 꽂히지 않는다")
        try:
            with mock.patch.object(capabilities, "NET_BLOGGER_OAUTH", True):
                self.assertEqual(wiring.register_enabled(), ("blogger",))
                adapter = external.blogger_adapter()
                from chanceblog_desktop.publish.blogger import BloggerAdapter
                self.assertIsInstance(adapter, BloggerAdapter)
        finally:
            external.unregister(external.KIND_BLOGGER)
        self.assertEqual(external.registered_kinds(), ())
        with self.assertRaises(Exception) as caught:
            external.blogger_adapter()
        self.assertEqual(getattr(caught.exception, "code", ""), "NETWORK_DISABLED", "꽂힌 것이 없으면 접속이 꺼져 있다고 거절한다")

    def test_importing_the_command_line_does_not_load_the_connection_frame_or_the_blogger_flow(self):
        import json
        import os
        import subprocess
        code = ("import json, sys\nsys.path.insert(0, %r)\nimport chanceblog_desktop.service.cli, chanceblog_desktop.service.wiring, chanceblog_desktop.service.doctor\n"
                "print(json.dumps([name for name in ('ssl', '_ssl', 'http.client', 'chanceblog_desktop.net.client', 'chanceblog_desktop.service.blogger_flow', 'chanceblog_desktop.net.loopback') if name in sys.modules]))\n" % str(SRC.parent))
        done = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code], capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT), env=dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1"), timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1]), [], "기본 모듈이 가져오는 순간 접속 부품·Blogger 흐름·창구를 불러오지 않는다")


if __name__ == "__main__":
    unittest.main()
