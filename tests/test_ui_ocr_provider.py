"""글자 읽기 작업자 공급자의 운영 조립 `ui/ocr_provider.py`(결정 D-513)의 시험 — 순수 파이썬(PySide6 없음)이고 진짜 프로세스는 가짜 작업자(`tests/ocr_fake_worker.py`, 프로세스 트리 시험은 `tests/ocr_ui_worker.py`)뿐이다.

지키는 것:
  1) 조립 — `LOCAL_OCR` 가 꺼져 있으면 추가 도구가 멀쩡해도 `None`. 켜져 있어도 폴더가 없거나 확인(파일 목록·크기)을 통과하지 못하면 `None`. 모두 맞을 때만 어댑터를 돌려주고, 만드는 것만으로는 하위 프로세스를 띄우지 않는다.
  2) 어댑터에 덧붙인 둘 — 준비 소식(`on_ready`)이 읽는 쪽 스레드에서 찬 시작에도 이미 떠 있는 시작에도 불린다·시작에 실패하면 안 불린다 / 다른 스레드의 `terminate` 가 락 없이 작업자를 끝내고 읽는 쪽은 `died` 로 정리한다.
  3) 이 파일은 하위 프로세스·소켓·웹을 쓰지 않는다(작업자를 띄우는 곳은 `ocr_adapter` 하나).
"""
import ast
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import outgoing_support as og  # noqa: E402
import test_service_ocr_addon as ta  # noqa: E402     (가짜 추가 도구 폴더를 만드는 도구만 이어 쓴다)
from capability_support import local_ocr_off, local_ocr_on  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.service import ocr_addon as oa  # noqa: E402
from chanceblog_desktop.ui import ocr_adapter as oadapter  # noqa: E402
from chanceblog_desktop.ui import ocr_provider as op  # noqa: E402

FAKE = str(HERE / "ocr_fake_worker.py")
UI_WORKER = str(HERE / "ocr_ui_worker.py")                 # 손자 프로세스를 띄울 수 있는 가짜 작업자(프로세스 트리 종료 시험)
SOURCE = ROOT / "src" / "chanceblog_desktop" / "ui" / "ocr_provider.py"
PIXELS = bytes(range(256)) * 3                       # 16 x 16 RGB


def command(*extra, mode="ok"):
    return [sys.executable, "-B", FAKE, "--mode", mode, *extra]


class FactoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = self.tmp.name
        self.folder = os.path.join(self.app, "ocr")
        patcher = mock.patch.dict(oa.EMBEDDED_FILES, ta.EMBEDDED, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def good(self):
        os.makedirs(self.folder)
        ta.write_addon(self.folder)

    def test_while_the_gate_is_off_nothing_is_made_even_if_the_tool_folder_is_perfect(self):
        self.good()
        self.assertFalse(capabilities.local_ocr_enabled())
        self.assertIsNone(op.default_provider(self.app))

    def test_with_the_gate_on_a_missing_or_broken_tool_gives_nothing(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        self.assertIsNone(op.default_provider(self.app), "폴더가 없다")
        os.makedirs(self.folder)
        self.assertIsNone(op.default_provider(self.app), "정보 파일이 없다")
        ta.write_addon(self.folder)
        os.remove(os.path.join(self.folder, "_internal", "lib.dll"))
        self.assertIsNone(op.default_provider(self.app), "파일이 모자란다")

    def test_a_deeply_nested_info_file_is_a_tool_that_cannot_be_used_not_an_exception_that_stops_the_app(self):
        """독립 검증 S SP-3 — 정보 파일이 깊게 중첩된 JSON 이면 읽는 쪽에서 RecursionError 가 나온다(점검의 except 는 파일·값·글자 오류뿐). 선택 기능의 도구 폴더 하나가 앱 시작을 막으면 안 된다 — 쓸 수 없는 도구로 본다."""
        from chanceblog_desktop.ui.adapters import ServiceHomeProvider
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        os.makedirs(self.folder)
        with open(os.path.join(self.folder, oa.INFO_NAME), "w", encoding="utf-8") as handle:
            handle.write("[" * 60000 + "]" * 60000)
        self.assertIsNone(op.default_provider(self.app))
        with mock.patch.object(op, "app_folder", lambda: self.app):
            self.assertIsNone(ServiceHomeProvider("nowhere").ocr_provider(), "짝 공급자도 같다")
        with mock.patch.object(op, "default_provider", side_effect=RuntimeError("뜻밖의 예외")):
            self.assertIsNone(ServiceHomeProvider("nowhere").ocr_provider(), "조립 중 어떤 예외가 나도 글자 읽기 칸이 없는 앱으로 시작한다")

    def test_the_start_check_does_not_hash_the_tool_files_only_the_launch_check_does(self):
        """독립 검증 Q QP-16 — 앱을 켤 때는 추가 도구를 빠르게만 확인한다(`check_files=False` — 폴더와 정보 파일 정도). 파일 전체의 크기·해시 확인은 작업자를 띄우기 직전(`verify_problem`)에만 한다 — 추가 도구가 수백 MB 여도 첫 화면이 멈추지 않는다."""
        self.good()
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        calls = []
        real = oa.verify

        def spy(folder, **kwargs):
            calls.append(kwargs)
            return real(folder, **kwargs)

        with mock.patch.object(oa, "verify", spy):
            provider = op.default_provider(self.app)
        self.assertIsNotNone(provider)
        self.assertEqual(calls, [{"check_files": False}], "켤 때는 파일 전체를 읽지 않는다")

    def test_with_the_gate_on_and_a_good_tool_it_makes_an_adapter_that_is_not_started_yet(self):
        self.good()
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        with og.Tripwire() as wire:
            provider = op.default_provider(self.app)
        self.assertEqual(wire.calls, [], "만드는 것만으로는 하위 프로세스를 띄우지 않는다")
        self.assertIsInstance(provider, op.WorkerAdapter)
        self.assertIsInstance(provider, oadapter.OcrAdapter)
        self.assertEqual((provider.command, provider.work_dir, provider.prepare, provider.on_ready, provider.process, provider.launches), ([os.path.join(self.folder, "ocr_worker.exe")], self.folder, None, None, None, 0))
        self.assertTrue(provider.available())
        self.assertIsNone(provider.verify(), "띄우기 직전의 해시 확인이 멀쩡한 폴더에서는 문제가 없다")
        with open(os.path.join(self.folder, "_internal", "lib.dll"), "ab") as handle:
            handle.write(b"x")
        self.assertIn("size", provider.verify() or "", "그 사이 파일이 바뀌면 띄우기 전에 걸린다")

    def test_the_app_folder_is_beside_the_executable_when_frozen_and_the_repository_root_in_development(self):
        root = op.app_folder()
        self.assertTrue(os.path.isdir(os.path.join(root, "src", "chanceblog_desktop")), root)
        self.assertEqual(os.path.realpath(root), os.path.realpath(str(ROOT)))
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", os.path.join(self.app, "ChanceBlog.exe")):
            self.assertEqual(os.path.realpath(op.app_folder()), os.path.realpath(self.app))
        self.assertEqual(os.path.basename(oa.addon_folder(op.app_folder())), "ocr")

    def test_the_paired_home_provider_method_goes_through_the_same_factory(self):
        from chanceblog_desktop.ui.adapters import ServiceHomeProvider
        self.good()
        provider = ServiceHomeProvider("nowhere")
        self.assertIsNone(provider.ocr_provider(), "관문이 꺼져 있다")
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        with mock.patch.object(op, "app_folder", lambda: self.app):
            self.assertIsInstance(provider.ocr_provider(), op.WorkerAdapter)


class WorkerAdapterTest(unittest.TestCase):
    def setUp(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        patcher = mock.patch.object(oadapter, "BELOW_NORMAL", 0)                    # 시험에서는 낮은 우선순위를 끈다 — PC 가 바쁠 때 낮은 우선순위의 가짜 작업자가 굶어 시간 초과가 나는 것을 막는다(우선순위 자체는 이 시험이 보는 것이 아니다)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, *extra, mode="ok", **options):
        options.setdefault("prepare_timeout", 20)
        options.setdefault("read_timeout", 20)
        options.setdefault("verify", None)                                           # 확인 없음을 일부러 고른다(B1 어댑터는 verify 를 꼭 받는다)
        adapter = op.WorkerAdapter(command(*extra, mode=mode), **options)
        adapter.priority_class = 0                                                   # 아주 바쁜 PC 에서 낮은 우선순위 작업자가 굶지 않게(없는 속성이면 쓰이지 않는다)
        self.addCleanup(adapter.shutdown)
        return adapter

    def test_the_ready_news_comes_from_the_reading_thread_for_a_cold_start_and_a_warm_one(self):
        threads = []
        adapter = self.make(on_ready=lambda: threads.append(threading.current_thread()))
        reader = []

        def run():
            reader.append(threading.current_thread())
            self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "")
            self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "")

        worker = threading.Thread(target=run)
        worker.start()
        worker.join(30)
        self.assertEqual((len(threads), adapter.launches), (2, 1), "작업자는 한 번 떴고 소식은 읽기마다 한 번이다")
        self.assertTrue(all(thread is reader[0] for thread in threads))
        self.assertIsNot(reader[0], threading.current_thread())

    def test_no_ready_news_when_the_worker_never_gets_ready_or_cannot_start(self):
        news = []
        silent = self.make(mode="noready", prepare_timeout=0.6, on_ready=lambda: news.append(1))
        self.assertEqual(silent.read_rgb(16, 16, PIXELS, "960").error, "timeout")
        gone = op.WorkerAdapter([sys.executable, "-c", "raise SystemExit(4)"], prepare_timeout=40, verify=None, on_ready=lambda: news.append(2))        # 바쁜 PC 에서는 파이썬이 뜨는 데만 몇 초가 걸릴 수 있다
        self.addCleanup(gone.shutdown)
        self.assertIn(gone.read_rgb(16, 16, PIXELS, "960").error, ("died", "proto"))
        self.assertEqual(news, [])

    def test_terminate_from_another_thread_ends_a_read_that_is_waiting_and_the_reader_cleans_up(self):
        adapter = self.make("--delay", "30")
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(adapter.read_rgb(16, 16, PIXELS, "960")))
        worker.start()
        end = time.monotonic() + 15
        while time.monotonic() < end and adapter.process is None:
            time.sleep(0.05)
        time.sleep(1.0)                                                              # 준비를 마치고 요청을 보내 응답을 기다리는 중(준비 중이어도 끝나는 모습은 같다)
        process = adapter.process
        self.assertIsNotNone(process)
        started = time.monotonic()
        adapter.terminate()
        worker.join(28)                                                              # 작업자가 스스로 답할 30초보다 한참 앞서 풀려나면 된다 — 바쁜 PC 에서는 프로세스 트리 종료가 몇 초 걸린다
        self.assertFalse(worker.is_alive(), "읽는 쪽이 풀려났다")
        self.assertLess(time.monotonic() - started, 25)
        self.assertEqual(outcome[0].error, "died")
        self.assertIsNotNone(process.poll(), "프로세스가 끝났다")
        self.assertIsNone(adapter.process, "읽는 쪽이 정리했다")

    def test_terminate_ends_the_whole_process_tree_and_not_only_the_worker(self):
        """독립 검증 S Q9 — 작업자가 띄운 손자 프로세스까지 끈다(진짜 작업자는 엔진 하위 프로세스를 띄울 수 있다). 가짜 작업자가 박동 파일을 쓰는 손자를 하나 띄우고, 박동이 멈추는지 본다."""
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        beat = os.path.join(holder.name, "beat.txt")
        adapter = op.WorkerAdapter([sys.executable, "-B", UI_WORKER, "--delay", "30", "--child-heartbeat", beat], prepare_timeout=40, read_timeout=40, verify=None)
        adapter.priority_class = 0
        self.addCleanup(adapter.shutdown)
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(adapter.read_rgb(16, 16, PIXELS, "960")))
        worker.start()
        end = time.monotonic() + 30
        while time.monotonic() < end and not os.path.exists(beat):
            time.sleep(0.05)
        self.assertTrue(os.path.exists(beat), "손자가 떴다")
        time.sleep(1.0)                                                              # 준비를 마치고 요청을 보내 응답을 기다리는 중
        stamp = os.stat(beat).st_mtime_ns
        time.sleep(0.8)
        self.assertNotEqual(os.stat(beat).st_mtime_ns, stamp, "끄기 전에는 손자가 살아서 박동을 쓴다")
        adapter.terminate()
        worker.join(28)
        self.assertFalse(worker.is_alive(), "읽는 쪽이 풀려났다")
        time.sleep(0.8)
        stamp = os.stat(beat).st_mtime_ns
        time.sleep(1.2)
        self.assertEqual(os.stat(beat).st_mtime_ns, stamp, "손자도 끝났다 — 박동이 멈췄다")

    def test_terminate_with_no_worker_is_harmless_and_repeatable(self):
        adapter = self.make()
        adapter.terminate()
        adapter.terminate()
        self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "", "그 뒤에도 새로 띄워 읽는다")
        adapter.terminate()
        adapter.terminate()
        self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "", "끝난 작업자는 다음 읽기에서 새로 뜬다")
        self.assertEqual(adapter.launches, 2)


class SourceTest(unittest.TestCase):
    def test_the_assembly_file_has_no_process_socket_or_web_calls_and_only_the_expected_imports(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(("." * node.level) + (node.module or ""))
        self.assertEqual(imported, {"os", "sys", "..", "..service", ".ocr_adapter", "__future__"})
        names = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "") for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(names & {"Popen", "run", "system", "popen", "open", "print", "connect", "urlopen"}, names)

    def test_the_two_things_it_adds_to_the_adapter_use_only_its_public_pieces(self):
        source = SOURCE.read_text(encoding="utf-8")
        for needed in ("super()._ensure_started()", "kill_tree(process)", "capabilities.local_ocr_enabled()", "ocr_addon.verify(folder, check_files=False)", "ocr_addon.verify_problem(folder)"):
            self.assertIn(needed, source)
        self.assertLess(source.index("local_ocr_enabled()"), source.index("ocr_addon.addon_folder"), "관문이 폴더를 살피기 전에 먼저다")


if __name__ == "__main__":
    unittest.main()
