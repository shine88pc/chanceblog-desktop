"""설치 도구 시험(spike)의 작은 앱 둘(`packaging/spike/spike_app.py`·`spike_app_sdk.py`)과 Inno 스크립트(`ChanceBlogSpike.iss`)의 시험(결정 D-704·D-705) — 설치 도구·윈도 없이 돈다.

지키는 것: ① 훅 인자는 '정확히 둘, 첫째는 소문자 그대로 훅 넷 중 하나, 둘째는 버전 모양에 통째로 맞음' 일 때만 열리고 그때는 아무것도 쓰지 않고 종료 코드 0(설계서 G-A 의 좁은 허용)이며 근접 오답은 모두 거절(2)
② BROKEN 표지가 있으면 시작하자마자 종료 코드 3 ③ 쓰는 것은 SPIKE_LOG 한 줄씩뿐이고 표준 라이브러리만(네트워크·하위 프로세스·표준 출력 0) ④ SDK 앱은 맨 앞에서 자동 적용을 끄고 run 한다(콜백 등록 0)
⑤ Inno 스크립트는 사용자 권한·한국어·데이터 보존·시작 메뉴만이고 코드 줄이 모두 ASCII 이며 run_spike.py 가 넘기는 /D 정의 이름과 맞는다.
"""
import ast
import contextlib
import io
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_spike_support as support  # noqa: E402

sys.path.insert(0, str(support.ROOT / "packaging"))
import pkgcommon  # noqa: E402

HOOKS = ("--veloapp-install", "--veloapp-updated", "--veloapp-obsolete", "--veloapp-uninstall")


def load_app():
    return support.load("spike_app")


class FakeSdk:
    """Velopack 파이썬 SDK 흉내 — 부른 순서를 events 에 쌓는다."""

    def __init__(self, update=True, fail=False):
        self.events, self.update, self.fail = [], update, fail
        outer = self

        class UpdateManager:
            def __init__(self, source):
                outer.events.append(("manager", source))

            def check_for_updates(self):
                outer.events.append(("check",))
                if outer.fail:
                    raise RuntimeError("boom")
                return {"version": "0.0.2"} if outer.update else None

            def download_updates(self, info):
                outer.events.append(("download", info["version"]))

            def apply_updates_and_exit(self, info):
                outer.events.append(("apply_exit", info["version"]))

        self.UpdateManager = UpdateManager


class HookRuleTest(unittest.TestCase):
    def setUp(self):
        self.app = load_app()

    def test_the_four_hooks_with_a_version_open_and_exit_zero(self):
        for hook in HOOKS:
            for version in ("0.0.1", "1.2.161", "0.1.0-preview.1", "10.20.30+build.5"):
                with self.subTest(hook=hook, version=version):
                    self.assertTrue(self.app.is_hook([hook, version]))

    def test_every_near_miss_stays_closed(self):
        for argv in ([], ["--veloapp-install"], ["--veloapp-install", "0.0.1", "extra"], ["--VELOAPP-INSTALL", "0.0.1"], ["--Veloapp-install", "0.0.1"], ["--veloapp-install", "not-a-version"],
                     ["--veloapp-unknown", "0.0.1"], ["--veloapp-install=0.0.1"], ["--veloapp-install", "1.0"], ["--veloapp-install", "1.0.0 "], ["--veloapp-install", " 1.0.0"], ["--veloapp-install", "1.0.0\n"],
                     ["--veloapp-install", "v1.0.0"], ["--veloapp-install", "1.0.0;x"], ["0.0.1", "--veloapp-install"], ["--veloapp-install", ""], ["--veloapp-", "0.0.1"], ["-veloapp-install", "0.0.1"]):
            with self.subTest(argv=argv):
                self.assertFalse(self.app.is_hook(argv))

    def test_the_version_shape_is_the_same_one_the_real_entry_uses(self):
        self.assertEqual(self.app.VERSION_PATTERN.pattern, pkgcommon.VERSION_PATTERN)
        self.assertEqual(self.app.HOOKS, HOOKS)

    def test_a_hook_writes_nothing_prints_nothing_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "spike.log"
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                for hook in HOOKS:
                    self.assertEqual(self.app.main([hook, "0.0.2"], {"SPIKE_LOG": str(log)}, directory=tmp), 0)
            self.assertFalse(log.exists())
            self.assertEqual(out.getvalue() + err.getvalue(), "")
            self.assertEqual(sorted(path.name for path in Path(tmp).iterdir()), [])

    def test_a_hook_exits_zero_even_when_the_version_is_the_broken_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "BROKEN").write_text("x", encoding="utf-8")
            self.assertEqual(self.app.main(["--veloapp-updated", "0.0.3"], {}, directory=tmp), 0)


class BehaviourTest(unittest.TestCase):
    def setUp(self):
        self.app = load_app()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "VERSION").write_text("0.0.2\n", encoding="utf-8")
        self.log = self.dir.parent / (self.dir.name + "-spike.log")
        self.env = {"SPIKE_LOG": str(self.log)}
        self.addCleanup(lambda: self.log.unlink() if self.log.exists() else None)

    def lines(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def test_a_normal_start_logs_the_version_and_exits_zero(self):
        self.assertEqual(self.app.main([], self.env, directory=self.dir), 0)
        self.assertEqual(self.lines(), ["started 0.0.2"])

    def test_without_a_log_variable_it_writes_nothing_at_all(self):
        self.assertEqual(self.app.main([], {}, directory=self.dir), 0)
        self.assertFalse(self.log.exists())
        self.assertEqual(self.app.main([], {"SPIKE_LOG": ""}, directory=self.dir), 0)

    def test_the_version_comes_from_the_file_and_a_bad_file_reads_unknown(self):
        self.assertEqual(self.app.read_version(self.dir), "0.0.2")
        (self.dir / "VERSION").write_text("not a version", encoding="utf-8")
        self.assertEqual(self.app.read_version(self.dir), "unknown")
        (self.dir / "VERSION").unlink()
        self.assertEqual(self.app.read_version(self.dir), "unknown")

    def test_the_broken_marker_exits_three_right_away(self):
        (self.dir / "BROKEN").write_text("x", encoding="utf-8")
        self.assertEqual(self.app.main([], self.env, directory=self.dir), 3)
        self.assertEqual(self.lines(), ["broken 0.0.2 exit 3"])

    def test_unknown_or_malformed_arguments_are_refused_with_two_and_the_value_is_not_repeated(self):
        for argv in (["--foo"], ["--hold"], ["--hold", "abc"], ["--hold", "601"], ["--hold", "-1"], ["--hold", "1", "--hold", "2"], ["--update-from"], ["extra"], ["--hold", "5", "extra"], ["--selftest"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.app.main(argv, self.env, directory=self.dir), 2)
        for line in self.lines():
            self.assertNotIn("foo", line)
            self.assertNotIn("abc", line)

    def test_update_from_is_refused_when_there_is_no_sdk(self):
        self.assertEqual(self.app.main(["--update-from", "somewhere"], self.env, directory=self.dir), 2)
        self.assertTrue(any("refused" in line for line in self.lines()))

    def test_hold_keeps_the_app_alive_for_the_given_seconds_and_then_exits_zero(self):
        ticks = {"now": 0.0}
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            ticks["now"] += seconds

        code = self.app.main(["--hold", "3"], self.env, directory=self.dir, clock=lambda: ticks["now"], sleep=sleep)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(sum(sleeps), 3)
        self.assertEqual(self.lines(), ["started 0.0.2", "holding 0.0.2 3s", "released 0.0.2"])

    def test_the_sdk_update_checks_downloads_then_applies_and_exits_in_that_order(self):
        sdk = FakeSdk()
        self.assertEqual(self.app.main(["--update-from", "feed-folder"], self.env, directory=self.dir, sdk=sdk), 0)
        self.assertEqual(sdk.events, [("manager", "feed-folder"), ("check",), ("download", "0.0.2"), ("apply_exit", "0.0.2")])

    def test_no_update_available_downloads_nothing(self):
        sdk = FakeSdk(update=False)
        self.assertEqual(self.app.main(["--update-from", "feed-folder"], self.env, directory=self.dir, sdk=sdk), 0)
        self.assertEqual([event[0] for event in sdk.events], ["manager", "check"])
        self.assertIn("no update", self.lines())

    def test_a_failing_sdk_exits_four_and_logs_only_the_error_kind(self):
        self.assertEqual(self.app.main(["--update-from", "feed-folder"], self.env, directory=self.dir, sdk=FakeSdk(fail=True)), 4)
        self.assertIn("update failed: RuntimeError", self.lines())
        for line in self.lines():
            self.assertNotIn("boom", line)

    def test_an_unwritable_log_is_swallowed(self):
        self.assertEqual(self.app.main([], {"SPIKE_LOG": str(self.dir / "no" / "such" / "folder" / "x.log")}, directory=self.dir), 0)


class SourceRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (support.SPIKE / "spike_app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_only_a_few_standard_modules_and_no_network_process_or_output(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported, {"os", "re", "sys", "time", "pathlib"})
        calls = {node.func.id for node in ast.walk(self.tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        for forbidden in ("print", "input", "exec", "eval", "open_url"):
            self.assertNotIn(forbidden, calls)
        for word in ("socket", "subprocess", "urllib", "http", "ctypes", "MessageBox", "webbrowser", "os.system", "AppData", "LOCALAPPDATA", "ChanceblogDesktop", "settings.json", "chanceblog.db"):
            self.assertNotIn(word, self.source, word)

    def test_the_only_file_it_opens_is_the_log_in_append_mode(self):
        opens = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"]
        self.assertEqual(len(opens), 1)
        self.assertEqual(ast.literal_eval(opens[0].args[1]), "a")

    def test_comments_and_docstrings_have_no_address_scheme_tilde_or_double_brace(self):
        text = ast.get_docstring(self.tree) + "\n" + "\n".join(line.split("#", 1)[1] for line in self.source.splitlines() if "#" in line and not line.lstrip().startswith(('"', "'")))
        self.assertIsNone(re.search(r"(?i)(https?|ftp)://|www[.]", text))
        self.assertNotIn(chr(0x7E), text)
        self.assertNotIn("{{", text)


class SdkAppTest(unittest.TestCase):
    def test_it_turns_auto_apply_off_and_runs_before_the_app_logic_and_registers_no_callback(self):
        events = []

        class App:
            def __init__(self):
                events.append("App()")

            def set_auto_apply_on_startup(self, value):
                events.append("set_auto_apply_on_startup(%r)" % (value,))
                return self

            def run(self):
                events.append("run()")
                return self

        stub = types.ModuleType("velopack")
        stub.App = App
        previous = sys.modules.get("velopack")
        sys.modules["velopack"] = stub
        try:
            module = support.load("spike_app_sdk")
            module.velopack = stub
            original = module.spike_app.main
            module.spike_app.main = lambda **kwargs: events.append("app main sdk=%s" % (kwargs.get("sdk") is stub)) or 0
            try:
                self.assertEqual(module.main(), 0)
            finally:
                module.spike_app.main = original
        finally:
            if previous is None:
                sys.modules.pop("velopack", None)
            else:
                sys.modules["velopack"] = previous
        self.assertEqual(events, ["App()", "set_auto_apply_on_startup(False)", "run()", "app main sdk=True"])

    def test_the_source_never_registers_callbacks_or_turns_auto_apply_on(self):
        source = (support.SPIKE / "spike_app_sdk.py").read_text(encoding="utf-8")
        self.assertIn("velopack.App().set_auto_apply_on_startup(False).run()", source)
        for word in ("on_first_run", "on_restarted", "on_after_install", "on_after_update", "on_before_update", "on_before_uninstall", "set_auto_apply_on_startup(True)"):
            self.assertNotIn(word, source, word)


class InnoScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (support.SPIKE / "ChanceBlogSpike.iss").read_bytes()
        cls.text = raw.decode("utf-8").replace("\r\n", "\n")
        cls.code = [line for line in cls.text.splitlines() if line.strip() and not line.lstrip().startswith(";")]

    def test_the_required_user_level_korean_and_data_keeping_lines_are_there(self):
        for needle in ("PrivilegesRequired=lowest", "CloseApplications=yes", 'MessagesFile: "compiler:Languages\\Korean.isl"', "DefaultDirName={autopf}\\{#AppDirName}", "Compression=lzma2/max",
                       "OutputBaseFilename={#OutBase}", "recursesubdirs", "skipifsilent", "DisableProgramGroupPage=yes", "Name: \"{autoprograms}\\ChanceBlog Spike C\""):
            self.assertIn(needle, self.text, needle)

    def test_nothing_that_deletes_data_or_starts_by_itself_or_needs_admin(self):
        lowered = self.text.lower()
        for word in ("[uninstalldelete]", "[uninstallrun]", "[registry]", "[tasks]", "[installdelete]", "hklm", "privilegesrequired=admin", "poweruser", "{commonpf", "{sys}", "runonce", "{userstartup}", "{commonstartup}",
                     "{autodesktop}", "{userdesktop}", "{commondesktop}", "desktopicon", "schtasks", "http", "~"):
            self.assertNotIn(word, lowered, word)
        self.assertEqual(self.text.count("[Run]"), 1)

    def test_every_code_line_is_ascii_so_the_script_compiles_without_a_byte_order_mark(self):
        for line in self.code:
            self.assertTrue(all(ord(char) < 128 for char in line), line)

    def test_the_app_id_is_a_fixed_plain_text_without_braces(self):
        self.assertIn('#define AppIdText "ChanceBlogSpikeInnoV1"', self.text)
        self.assertIn("AppId={#AppIdText}", self.text)
        self.assertIsNone(re.search(r'#define AppIdText "[^"]*[{}]', self.text))

    def test_the_defines_run_spike_passes_are_exactly_the_ones_the_script_takes(self):
        script_names = set(re.findall(r"#ifndef (\w+)", self.text))
        run = support.load("run_spike")
        args = run.iscc_args("ISCC.exe", "x.iss", version="1.0.0", source_dir="src", app_exe="a.exe", app_dir_name="d", out_dir="o", out_base="b", app_id="id")
        passed = {item[2:].split("=")[0] for item in args if item.startswith("/D")}
        # 출력 폴더와 설치 파일 이름은 ISCC 의 /O·/F 가 [Setup] 의 값을 덮어쓴다(저장소 안 Output 폴더가 생기지 않게 항상 준다)
        self.assertEqual(passed | {"OutputDir", "OutBase"}, script_names)
        self.assertTrue(any(item.startswith("/Oo") for item in args) and any(item.startswith("/Fb") for item in args))
        self.assertIn("#error", self.text)                                       # SourceDir 가 없으면 컴파일이 멈춘다(조용히 빈 설치 파일을 만들지 않는다)

    def test_the_log_tokens_the_korean_check_reads_are_written_by_the_script(self):
        for token in ("SPIKE_LANG=", "SPIKE_NEXT=", "ActiveLanguage", "SetupMessage(msgButtonNext)"):
            self.assertIn(token, self.text, token)
        source = (support.SPIKE / "measure.py").read_text(encoding="utf-8")
        for token in ("SPIKE_LANG=", "SPIKE_NEXT="):
            self.assertIn(token, source, token)

    def test_the_comments_have_no_double_brace_tilde_or_address(self):
        comments = "\n".join(line for line in self.text.splitlines() if line.lstrip().startswith(";"))
        self.assertNotIn("{{", comments)
        self.assertNotIn(chr(0x7E), comments)
        self.assertIsNone(re.search(r"(?i)(https?|ftp)://|www[.]", comments))


if __name__ == "__main__":
    unittest.main()
