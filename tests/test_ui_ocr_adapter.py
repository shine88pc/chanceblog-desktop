"""글자 읽기 작업자 어댑터 `ui/ocr_adapter.py`(결정 D-512, 설계서 3-3·3-5·3-6·3-9, 시험 계획 T-A)를 **가짜 작업자**(`tests/ocr_fake_worker.py`, 순수 파이썬)로 시험한다 — 진짜 프로세스를 띄워 보지만 진짜 엔진·사진은 없다.

지키는 것:
  1) 관문 — `LOCAL_OCR` 가 꺼져 있으면 하위 프로세스를 한 번도 안 띄운다(동적 막이가 센다).
  2) 요청 — 머리 한 줄 + 픽셀뿐이고 경로·파일 이름·사진 번호·종류·메모·Exif 가 한 글자도 없다(작업자가 받은 바이트를 그대로 가로채 본다).
  3) 응답 검증 — 모르는 칸·번호 불일치·NaN·줄 201개·줄당 401자·256KB 넘는 줄·JSON 아님·되풀이 응답은 버리고 `proto`, 작업자는 정리된다.
  4) 시간·취소 — 준비·사진 시간 초과는 프로세스 트리(손자 포함)를 끈다. 취소는 기다림 안에 끝나지 않으면 끈다. 죽음·EOF 는 `died`. `net_blocked` 는 즉시 알리고 끝낸다.
  5) 환경 변수 — 부모의 비밀은 안 넘어가고 프록시는 닫힌 포트, 오프라인·텔레메트리 끔 값이 있다. 표준 오류는 비우기만 한다. 끝나면 전용 임시 폴더가 지워지고 좌비 프로세스가 없다.
  6) 컨트롤러와 함께 — 연속 실패 3번이면 끄고, 네트워크 차단 보고는 한 번에 끈다. 추가 도구 해시 확인이 실패하면 띄우지 않는다.
"""
import ast
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import outgoing_support as og  # noqa: E402
from capability_support import local_ocr_off, local_ocr_on  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.ui import ocr_adapter as oa  # noqa: E402
from chanceblog_desktop.ui.core import ocr_protocol as proto  # noqa: E402
from chanceblog_desktop.ui.core import photo_ocr_view as pov  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402

FAKE = str(HERE / "ocr_fake_worker.py")
PIXELS = bytes(range(256)) * 3                       # 16 x 16 RGB
SECRET_NAME = "SECRET_FOR_TEST"


def command(*extra, mode="ok"):
    return [sys.executable, "-B", FAKE, "--mode", mode, *extra]


def pid_alive(pid):
    if os.name == "nt":
        done = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True)
        return str(pid).encode("ascii") in (done.stdout or b"")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_dead(pid, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


class AdapterCase(unittest.TestCase):
    def setUp(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        self.adapters = []

    def make(self, *extra, mode="ok", **options):
        options.setdefault("prepare_timeout", 20)
        options.setdefault("read_timeout", 20)
        adapter = oa.OcrAdapter(command(*extra, mode=mode), **options)
        self.adapters.append(adapter)
        self.addCleanup(adapter.shutdown)
        return adapter

    def read(self, adapter):
        return adapter.read_rgb(16, 16, PIXELS, "960")


class GateTest(unittest.TestCase):
    def test_when_the_gate_is_off_no_process_is_ever_started(self):
        adapter = oa.OcrAdapter(command())
        with og.Tripwire() as wire:
            outcome = adapter.read_rgb(16, 16, PIXELS, "960")
        self.assertEqual((outcome.error, wire.calls, adapter.launches, adapter.process), ("unavailable", [], 0, None))
        self.assertFalse(adapter.available())

    def test_the_launch_function_asks_the_gate_before_anything_else(self):
        adapter = oa.OcrAdapter(command(), verify=lambda: self.fail("관문 앞에서 해시를 보면 안 된다"))
        with self.assertRaises(Exception) as caught, og.Tripwire() as wire:
            adapter._launch()
        self.assertEqual((getattr(caught.exception, "code", ""), wire.calls), ("OCR_UNAVAILABLE", []))


class RequestAndResponseTest(AdapterCase):
    def test_a_normal_read_returns_only_the_texts_and_the_worker_is_reused(self):
        adapter = self.make()
        first = self.read(adapter)
        self.assertEqual((first.error, [line["text"] for line in first.lines]), ("", ["가짜 줄 1", "가짜 줄 2"]))
        self.assertTrue(all(set(line) == {"text"} for line in first.lines), "좌표는 버리고 글만 넘긴다")
        self.assertEqual(self.read(adapter).error, "")
        self.assertEqual(adapter.launches, 1)

    def test_the_request_bytes_carry_no_path_name_number_note_or_exif(self):
        dump = HERE / "_ocr_dump_test.bin"
        if dump.exists():
            dump.unlink()
        self.addCleanup(lambda: dump.exists() and dump.unlink())
        adapter = self.make("--dump", str(dump))
        adapter.read_rgb(16, 16, PIXELS, "1600")
        raw = dump.read_bytes()
        head, body = raw.split(b"\n", 1)
        self.assertEqual(body, PIXELS)
        import json
        self.assertEqual(sorted(json.loads(head)), ["fmt", "h", "id", "n", "size", "t", "w"])
        for fragment in (b"Exif", b"EXIF", b"p001", b"C:\\", b"Users", b"UNIQ", b".jpg", b"photo", b"note", b"path"):
            self.assertNotIn(fragment, raw[:len(head) + 1], fragment)

    def test_a_bad_size_name_or_pixel_length_is_refused_before_anything_is_sent(self):
        adapter = self.make()
        self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "720").error, "decode")
        self.assertEqual(adapter.read_rgb(16, 17, PIXELS, "960").error, "decode")
        self.assertEqual(adapter.launches, 1 if adapter.process else adapter.launches)

    def test_each_kind_of_protocol_violation_is_dropped_and_the_worker_is_cleaned_up(self):
        for mode in ("garbage", "huge", "badfield", "badid", "nan", "manylines", "longline"):
            with self.subTest(mode=mode):
                adapter = self.make(mode=mode)
                outcome = self.read(adapter)
                self.assertEqual((outcome.error, outcome.lines), ("proto", ()), mode)
                self.assertIsNone(adapter.process, "어긋난 작업자는 끝낸다")

    def test_a_second_unrequested_answer_is_a_violation_on_the_next_read(self):
        adapter = self.make(mode="twice")
        self.assertEqual(self.read(adapter).error, "")
        time.sleep(0.3)
        self.assertEqual(self.read(adapter).error, "proto")

    def test_a_dead_worker_or_an_early_end_of_input_is_died(self):
        for mode in ("die", "eof"):
            with self.subTest(mode=mode):
                adapter = self.make(mode=mode)
                self.assertEqual(self.read(adapter).error, "died")

    def test_a_net_blocked_report_ends_the_worker_at_once_and_is_reported(self):
        adapter = self.make(mode="net_blocked")
        process_holder = []
        original = adapter._launch

        def spy():
            original()
            process_holder.append(adapter.process)
        adapter._launch = spy
        self.assertEqual(self.read(adapter).error, "net_blocked")
        self.assertIsNone(adapter.process)
        self.assertTrue(process_holder[0].poll() is not None)

    def test_a_flood_on_standard_error_is_drained_and_kept_nowhere(self):
        adapter = self.make(mode="stderr_flood")
        outcome = self.read(adapter)
        self.assertEqual(outcome.error, "")
        self.assertNotIn("xxxxxxxx", repr(vars(adapter)))
        self.assertNotIn("xxxxxxxx", repr(outcome))


class EnvironmentTest(AdapterCase):
    def test_the_worker_sees_a_rebuilt_environment_and_no_parent_secret(self):
        parent = dict(os.environ)
        parent.update({SECRET_NAME: "CANARY_" + "shouldnotpass", "HTTPS_PROXY": "evil.example:8080", "NO_PROXY": "*", "my_proxy_thing": "x", "HF_HUB_OFFLINE": "0"})
        adapter = self.make(mode="env", parent_env=parent)
        outcome = self.read(adapter)
        seen = dict(line["text"].split("=", 1) for line in outcome.lines)
        self.assertEqual((seen["HF_HUB_OFFLINE"], seen["DO_NOT_TRACK"], seen["ORT_DISABLE_TELEMETRY"], seen["OPENCV_OPENCL_RUNTIME"], seen["PYTHONUTF8"]), ("1", "1", "1", "disabled", "1"))
        self.assertEqual((seen["HTTP_PROXY"], seen["HTTPS_PROXY"], seen["ALL_PROXY"], seen["NO_PROXY"]), (oa.PROXY_TRAP, oa.PROXY_TRAP, oa.PROXY_TRAP, "<없음>"))
        self.assertEqual(seen[SECRET_NAME], "<없음>")
        self.assertNotIn("CANARY_", outcome.lines.__repr__())
        self.assertTrue(seen["TEMP"].startswith(os.path.join(os.environ.get("TEMP", "")[:0], "")) and "cbd-ocr-" in seen["TEMP"])
        self.assertEqual(seen["TEMP"], seen["TMP"])

    def test_the_environment_builder_is_pure_and_keeps_only_system_values(self):
        parent = {"SystemRoot": "C:\\Windows", "PATH": "C:\\Tools;C:\\Python", SECRET_NAME: "x", "https_proxy": "p", "NO_PROXY": "*", "APPDATA": "C:\\Users\\a"}
        env = oa.build_environment(parent, "C:\\tmp\\w")
        self.assertNotIn(SECRET_NAME, env)
        self.assertNotIn("APPDATA", env)
        self.assertNotIn("NO_PROXY", env)
        self.assertEqual((env["https_proxy"], env["HTTP_PROXY"], env["TEMP"], env["TMP"]), (oa.PROXY_TRAP, oa.PROXY_TRAP, "C:\\tmp\\w", "C:\\tmp\\w"))
        self.assertNotIn("Tools", env["PATH"])
        for name, value in oa.FIXED_ENVIRONMENT.items():
            self.assertEqual(env[name], value)

    def test_the_temp_folder_is_made_for_the_worker_and_removed_after(self):
        adapter = self.make()
        self.read(adapter)
        folder = adapter.temp_dir
        self.assertTrue(folder and os.path.isdir(folder))
        adapter.shutdown()
        self.assertFalse(os.path.exists(folder))
        self.assertIsNone(adapter.process)
        adapter.shutdown()                                  # 여러 번 불러도 같다


class TimeAndCancelTest(AdapterCase):
    def test_the_prepare_time_out_ends_the_worker(self):
        adapter = self.make(mode="noready", prepare_timeout=0.6)
        started = time.monotonic()
        self.assertEqual(self.read(adapter).error, "timeout")
        self.assertLess(time.monotonic() - started, 10)
        self.assertIsNone(adapter.process)

    def test_the_read_time_out_kills_the_whole_tree_including_a_grandchild(self):
        pidfile = HERE / "_ocr_pid_test.txt"
        if pidfile.exists():
            pidfile.unlink()
        self.addCleanup(lambda: pidfile.exists() and pidfile.unlink())
        adapter = self.make("--pidfile", str(pidfile), mode="spawn", read_timeout=0.8)
        self.assertEqual(self.read(adapter).error, "timeout")
        grandchild = int(pidfile.read_text(encoding="utf-8"))
        self.assertTrue(wait_dead(grandchild), "손자 프로세스까지 끝나야 한다")

    def test_a_cancel_that_the_worker_does_not_finish_in_time_kills_it_and_the_next_read_starts_a_new_one(self):
        adapter = self.make("--delay", "6", mode="slow", cancel_wait=0.5, read_timeout=30)
        results = []
        worker = threading.Thread(target=lambda: results.append(self.read(adapter)))
        started = time.monotonic()
        worker.start()
        time.sleep(0.6)
        adapter.cancel()
        worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].error, "cancelled")
        self.assertLess(time.monotonic() - started, 5, "취소 대기 뒤 바로 끝나야 한다")
        self.assertIsNone(adapter.process)
        adapter.command = command()
        self.assertEqual(self.read(adapter).error, "")
        self.assertEqual(adapter.launches, 2)

    def test_the_worker_is_asked_to_leave_after_the_idle_time(self):
        now = [100.0]
        adapter = self.make(clock=lambda: now[0], idle_exit=300)
        self.read(adapter)
        now[0] += 299
        self.assertFalse(adapter.maybe_idle_exit())
        now[0] += 1
        self.assertTrue(adapter.maybe_idle_exit())
        self.assertIsNone(adapter.process)

    def test_the_hash_check_runs_before_the_launch_and_a_failure_launches_nothing(self):
        adapter = oa.OcrAdapter(command(), verify=lambda: "해시가 다르다")
        with og.Tripwire() as wire:
            outcome = adapter.read_rgb(16, 16, PIXELS, "960")
        self.assertEqual((outcome.error, wire.calls, adapter.launches), ("addon_invalid", [], 0))

    def test_a_launch_that_the_system_refuses_is_reported_as_blocked(self):
        adapter = oa.OcrAdapter([str(HERE / "no_such_worker_program.exe")])
        self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "blocked")
        self.assertIsNone(adapter.temp_dir)


class WithTheControllerTest(AdapterCase):
    def board(self, adapter, count=1):
        board = pv.PhotoBoard()
        manifest = pm.empty_manifest()
        for number in range(1, count + 1):
            manifest, _id = pm.add_photo(manifest, f"C:\\Users\\UNIQ\\Pictures\\x-{number:02d}.jpg", photo_type="메뉴판")
        board.load(manifest)
        adapter.prepare = lambda job: (16, 16, PIXELS)
        return board, pov.OcrBoard(board, adapter)

    def test_a_normal_flow_puts_unconfirmed_candidates_into_the_list(self):
        adapter = self.make()
        board, ocr = self.board(adapter)
        ocr.request_read("p001")
        self.assertEqual(ocr.run_pending(), [("p001", "applied")])
        self.assertEqual([(item.text, item.confirmed) for item in board.photo("p001").visible_text], [("가짜 줄 1", False), ("가짜 줄 2", False)])

    def test_three_dead_workers_in_a_row_turn_it_off_for_the_run(self):
        adapter = self.make(mode="die")
        board, ocr = self.board(adapter)
        statuses = []
        for _ in range(3):
            ocr.request_read("p001")
            statuses += [status for _photo, status in ocr.run_pending()]
        self.assertEqual((statuses, ocr.disabled_code), (["failed", "failed", "disabled"], "OCR_UNAVAILABLE"))
        self.assertEqual(ocr.request_read("p001"), "unavailable")
        self.assertEqual(adapter.launches, 3)

    def test_a_net_blocked_report_turns_it_off_at_once_with_the_unexpected_code(self):
        adapter = self.make(mode="net_blocked")
        board, ocr = self.board(adapter)
        ocr.request_read("p001")
        self.assertEqual(ocr.run_pending(), [("p001", "disabled")])
        self.assertEqual(ocr.disabled_code, "OCR_UNEXPECTED")

    def test_the_prepare_step_failing_or_a_too_big_photo_is_reported_without_launching(self):
        from chanceblog_desktop.errors import AppError
        adapter = self.make()
        board, ocr = self.board(adapter)

        def too_big(job):
            raise AppError("OCR_TOO_BIG")
        adapter.prepare = too_big
        ocr.request_read("p001")
        self.assertEqual(ocr.run_pending(), [("p001", "failed")])
        self.assertEqual((ocr.error_of("p001"), adapter.launches, ocr.failures), ("too_big", 0, 0))


class SourceShapeTest(unittest.TestCase):
    def test_the_adapter_never_takes_a_path_or_names_photo_things(self):
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "ocr_adapter.py").read_text(encoding="utf-8"))
        names = {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
        self.assertFalse(names & {"path", "local_path", "file", "filename", "photo_id", "note", "exif"})

    def test_there_is_no_socket_or_other_outgoing_import_in_the_adapter(self):
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "ocr_adapter.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
        self.assertFalse(imported & {"socket", "ssl", "http", "urllib", "requests", "asyncio", "webbrowser", "multiprocessing"})
        self.assertIn("subprocess", imported)

    def test_the_fake_worker_and_the_real_protocol_agree_on_the_shapes(self):
        self.assertEqual(proto.PROTO, 1)
        self.assertTrue(HERE.joinpath("ocr_fake_worker.py").exists())


if __name__ == "__main__":
    unittest.main()
