"""글자 읽기 작업자 어댑터 `ui/ocr_adapter.py`(결정 D-512, 설계서 3-3·3-5·3-6·3-9, 시험 계획 T-A)를 **가짜 작업자**(`tests/ocr_fake_worker.py`, 순수 파이썬)로 시험한다 — 진짜 프로세스를 띄워 보지만 진짜 엔진·사진은 없다.

지키는 것:
  1) 관문 — `LOCAL_OCR` 가 꺼져 있으면 하위 프로세스를 한 번도 안 띄운다(동적 막이가 센다).
  2) 요청 — 머리 한 줄 + 픽셀뿐이고 경로·파일 이름·사진 번호·종류·메모·Exif 가 한 글자도 없다(작업자가 받은 바이트를 그대로 가로채 본다).
  3) 응답 검증 — 모르는 칸·번호 불일치·NaN·줄 201개·줄당 401자·256KB 넘는 줄·JSON 아님·되풀이 응답은 버리고 `proto`, 작업자는 정리된다.
  4) 시간·취소 — 준비·사진 시간 초과는 프로세스 트리(손자 포함)를 끈다. 취소는 기다림 안에 끝나지 않으면 끈다. 죽음·EOF 는 `died`. `net_blocked` 는 즉시 알리고 끝낸다.
  5) 환경 변수 — 부모의 비밀은 안 넘어가고 프록시는 닫힌 포트, 오프라인·텔레메트리 끔 값이 있다. 표준 오류는 비우기만 한다. 끝나면 전용 임시 폴더가 지워지고 좌비 프로세스가 없다.
  6) 컨트롤러와 함께 — 연속 실패 3번이면 끄고, 네트워크 차단 보고는 한 번에 끈다. 추가 도구 해시 확인이 실패하면 띄우지 않는다.
  라운드 2 보강(HardeningTest·EnvironmentRound2Test·JobObjectTest·PosixBranchTest) —
  7) 응답 검증 목록 일곱(설계 3-5)과 너무 깊은 JSON 이 모두 어댑터까지 올라와 버려지고, 한 줄 256KB 경계(정확히 262144바이트는 통과·한 바이트 넘으면 거절)가 지켜진다. 시작 때의 오류 줄은 이름(`net_blocked`·`engine`)으로 알린다.
  8) 시간 — 요청을 쓰다가 막혀도(작업자가 안 읽음) 사진 한 장의 시간 초과·취소·앱 종료가 지켜진다. 읽는 중에는 유휴 확인이 기다리지 않는다. 시험은 `read_within` 으로 매달리지 않고 단언으로 빨개진다.
  9) 환경·작업 폴더 — 작업 폴더는 작업자 폴더가 기본이고 PATH 는 시스템 폴더만이다. 표준 오류 글은 결과·기록·화면·임시 폴더 어디에도 없다. 어떤 끝남(죽음·위반·시간 초과·네트워크 보고)에도 남은 프로세스가 없다.
  10) 윈도 Job 개체(만들기·넣기·핸들을 닫으면 끝남·메모리 한도)와 리눅스 갈래(`os.name` 을 좁게 흉내 — 프로세스 그룹 종료·새 세션·윈도 전용 인자 없음)의 안전.
"""
import ast
import contextlib
import io
import logging
import os
import queue
import signal
import subprocess
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
    base = [sys.executable, "-B", FAKE, "--mode", mode, *extra]
    if os.name != "nt":
        # 어댑터는 환경 변수를 새로 짜서 LD_LIBRARY_PATH 도 없앤다 — 공유 라이브러리로 만든 파이썬(깃허브 러너의 파이썬 포함)이 뜨려면 시험에서만 /usr/bin/env 로 그 한 변수를 되살려 준다(작업자 쪽 환경 정리는 그대로 시험한다).
        return ["/usr/bin/env", "LD_LIBRARY_PATH=" + os.environ.get("LD_LIBRARY_PATH", ""), *base]
    return base


def pid_alive(pid):
    if os.name == "nt":
        done = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True)
        return str(pid).encode("ascii") in (done.stdout or b"")
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            state = handle.read().rsplit(b")", 1)[1].split()[0]
        return state != b"Z"                              # 좀비(끝났지만 거두어 가지 않은 것)는 죽은 것으로 본다
    except (OSError, IndexError):
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def hard_kill(process):
    """시험의 마지막 안전망 — 어댑터의 정리 코드(변이로 망가질 수 있는)를 거치지 않고, 이 시험이 띄운 작업자와 그 자식을 PID 로 끝낸다(남은 프로세스를 흘리지 않는다)."""
    if process is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30, creationflags=0x08000000)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass


def kill_and_reap(process):
    """시험이 직접 띄운 보조 프로세스를 끝내고 거둔다(wait) — kill 만 하고 거두지 않으면 객체가 사라질 때 '아직 돌고 있다' 는 경고가 난다."""
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=30)
    except Exception:
        pass


def kill_pid(pid):
    """손자 프로세스를 PID 로 직접 끝낸다 — 어댑터의 트리 종료가 망가진 변이에서도 시험이 프로세스를 흘리지 않게 하는 안전망."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30, creationflags=0x08000000)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


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
        self.launched = []
        original = oa.OcrAdapter._launch
        launched = self.launched

        def spy(self_):
            original(self_)
            launched.append(self_.process)
        patcher = mock.patch.object(oa.OcrAdapter, "_launch", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.reap)                                  # 가장 먼저 등록 = 가장 나중에 실행 — 어댑터 정리(shutdown) 뒤에도 남은 작업자가 있으면 PID 로 끝낸다

    def reap(self):
        for process in self.launched:
            hard_kill(process)

    def make(self, *extra, mode="ok", **options):
        options.setdefault("prepare_timeout", 20)
        options.setdefault("read_timeout", 20)
        options.setdefault("priority_class", 0)                    # 아주 바쁜 PC 에서 낮은 우선순위 작업자가 굶어 시험이 흔들리지 않게 — 우선순위 자체는 PosixBranchTest·기본 우선순위 시험이 따로 본다
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
        """작업자가 받은 바이트(덤프)와 어댑터가 표준 입력에 실제로 쓴 바이트(가로채기) 둘 다 머리 한 줄 + 픽셀뿐이다 — 덤프는 읽은 만큼만 보이므로 뒤에 덧붙인 글자도 가로채기로 잡는다."""
        import json
        with tempfile.TemporaryDirectory() as folder:
            dump = Path(folder, "request.bin")
            adapter = self.make("--dump", str(dump))
            written = []
            original = oa.OcrAdapter._launch

            def spy_launch(self_):
                original(self_)
                real = self_.process.stdin

                class Tap:
                    def write(self, data):
                        written.append(bytes(data))
                        return real.write(data)

                    def __getattr__(self, name):
                        return getattr(real, name)
                self_.process.stdin = Tap()
            with mock.patch.object(oa.OcrAdapter, "_launch", spy_launch):
                adapter.read_rgb(16, 16, PIXELS, "1600")
            raw = dump.read_bytes()
        head, body = raw.split(b"\n", 1)
        self.assertEqual(body, PIXELS)
        self.assertEqual(sorted(json.loads(head)), ["fmt", "h", "id", "n", "size", "t", "w"])
        sent = b"".join(written)
        self.assertEqual(sent, head + b"\n" + PIXELS, "어댑터가 쓴 바이트는 머리 한 줄 + 픽셀이 전부다(뒤에 덧붙인 글자가 없다)")
        for fragment in (b"Exif", b"EXIF", b"p001", b"C:\\", b"Users", b"UNIQ", b".jpg", b"photo", b"note", b"path"):
            self.assertNotIn(fragment, head, fragment)

    @unittest.skipUnless(os.name == "nt", "윈도 우선순위 등급은 윈도 전용이다")
    def test_a_launch_with_the_default_priority_really_runs_the_worker_at_below_normal(self):
        """기본값으로 실제로 띄운 작업자의 우선순위 등급을 윈도에 물어 본다(낮음 = BELOW_NORMAL 0x4000) — 읽기가 끝나길 기다리지 않으니 아주 바쁜 PC 에서 낮은 우선순위 작업자가 굶어도 시험이 흔들리지 않는다."""
        import ctypes
        adapter = oa.OcrAdapter(command(), prepare_timeout=60, read_timeout=60)
        self.adapters.append(adapter)
        self.addCleanup(adapter.shutdown)
        self.assertEqual(adapter.priority_class, oa.BELOW_NORMAL)
        adapter._launch()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.GetPriorityClass.restype = ctypes.c_uint32
        kernel.GetPriorityClass.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, 0, adapter.process.pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        self.assertTrue(handle, "띄운 작업자의 정보를 열 수 있어야 한다")
        try:
            self.assertEqual(kernel.GetPriorityClass(handle), 0x4000, "기본값으로 띄운 작업자는 낮은 우선순위(BELOW_NORMAL)여야 한다")
        finally:
            kernel.CloseHandle(handle)

    def test_a_bad_size_name_or_pixel_length_is_refused_before_anything_is_started_or_sent(self):
        """경계에서 먼저 거절한다 — 작업자를 띄우지도 않는다(예전에는 크기가 안 맞는 요청도 작업자를 띄운 뒤에야 거절했다)."""
        adapter = self.make()
        for args, error in (((16, 16, PIXELS, "720"), "decode"), ((16, 17, PIXELS, "960"), "decode"), ((0, 16, b"", "960"), "decode"), ((16, 0, b"", "960"), "decode"), ((-1, 16, b"", "960"), "decode"),
                            ((1601, 1, bytes(1601 * 3), "960"), "too_big"), ((1, 1601, bytes(1601 * 3), "960"), "too_big"), ((16.0, 16, PIXELS, "960"), "decode"), ((16, 16, None, "960"), "decode"),
                            ((16, 16, PIXELS.hex(), "960"), "decode")):
            with self.subTest(args=repr(args)[:40]):
                self.assertEqual(adapter.read_rgb(*args).error, error)
        self.assertEqual((adapter.launches, adapter.process), (0, None), "나쁜 요청은 작업자를 띄우지 않는다")
        self.assertEqual(adapter.read_rgb(1600, 1, bytes(1600 * 3), "960").error, "", "긴 변 1600 은 되는 값이다")

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
        outcome = read_within(adapter, 90, 16, 16, PIXELS, "960")
        self.assertIsNotNone(outcome, "준비 시간 초과가 지켜지지 않아 읽기가 끝나지 않는다")
        self.assertEqual(outcome.error, "timeout")
        self.assertLess(time.monotonic() - started, 80)
        self.assertIsNone(adapter.process)

    def test_the_read_time_out_kills_the_whole_tree_including_a_grandchild(self):
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder, "grandchild.pid")
            adapter = self.make("--pidfile", str(pidfile), mode="spawn", read_timeout=0.8)
            outcome = read_within(adapter, 90, 16, 16, PIXELS, "960")
            self.assertIsNotNone(outcome, "사진 시간 초과가 지켜지지 않아 읽기가 끝나지 않는다")
            self.assertEqual(outcome.error, "timeout")
            grandchild = int(pidfile.read_text(encoding="utf-8"))
        self.addCleanup(kill_pid, grandchild)
        self.assertTrue(wait_dead(grandchild), "손자 프로세스까지 끝나야 한다")

    def test_a_cancel_that_the_worker_does_not_finish_in_time_kills_it_and_the_next_read_starts_a_new_one(self):
        adapter = self.make("--delay", "6", mode="slow", cancel_wait=0.5, read_timeout=30)
        results = []
        worker = threading.Thread(target=lambda: results.append(self.read(adapter)))
        worker.start()
        self.assertTrue(wait_until_write_started(adapter), "읽기 단계에 들어가야 한다(준비를 기다리다 취소하면 이 시험의 뜻이 사라진다)")
        started = time.monotonic()
        time.sleep(0.3)
        adapter.cancel()
        worker.join(90)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].error, "cancelled")
        self.assertLess(time.monotonic() - started, 80, "취소 대기 뒤 바로 끝나야 한다")
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

    def test_a_verify_function_that_raises_counts_as_a_failed_check_and_launches_nothing(self):
        def boom():
            raise OSError("읽을 수 없다")
        adapter = oa.OcrAdapter(command(), verify=boom)
        with og.Tripwire() as wire:
            outcome = adapter.read_rgb(16, 16, PIXELS, "960")
        self.assertEqual((outcome.error, wire.calls, adapter.launches), ("addon_invalid", [], 0))

    def test_the_idle_check_never_waits_for_a_read_that_is_running(self):
        """화면 스레드의 타이머가 부르므로 읽는 중에는 기다리지 않고 바로 거짓이어야 한다(예전에는 읽기가 끝날 때까지 잠금을 기다렸다)."""
        adapter = self.make("--delay", "8", mode="slow", read_timeout=120)
        box = []
        thread = threading.Thread(target=lambda: box.append(self.read(adapter)), daemon=True)
        thread.start()
        self.assertTrue(wait_until_write_started(adapter), "읽는 중이어야 이 시험의 뜻이 있다")
        time.sleep(0.3)
        started = time.monotonic()
        self.assertFalse(adapter.maybe_idle_exit())
        self.assertLess(time.monotonic() - started, 4.0, "읽는 중에는 기다리지 않고 바로 거짓 — 예전처럼 읽기가 끝날 때까지(8초) 잠금을 기다리면 걸린다")
        thread.join(120)
        self.assertEqual(box[0].error, "")

    def test_a_temp_folder_that_cannot_be_made_stops_the_launch_with_an_engine_error(self):
        adapter = self.make()
        with mock.patch.object(tempfile, "mkdtemp", side_effect=OSError("disk full")):
            outcome = adapter.read_rgb(16, 16, PIXELS, "960")
        self.assertEqual((outcome.error, adapter.launches, adapter.temp_dir, adapter.process), ("engine", 0, None, None))

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


def read_within(adapter, seconds, *args):
    """다른 스레드에서 읽고 `seconds` 안에 안 끝나면 None 을 돌려준다 — 시간 초과·취소 시험이 매달리지 않고 단언으로 빨개지게."""
    box = []
    thread = threading.Thread(target=lambda: box.append(adapter.read_rgb(*args)), daemon=True)
    thread.start()
    thread.join(seconds)
    return box[0] if box else None


def wait_until_write_started(adapter, seconds=90.0):
    """읽는 스레드가 작업자를 띄우고 준비 신호까지 받은 뒤 요청을 쓰기 시작할 때(요청 번호가 매겨질 때)까지 기다린다 — CPU 가 바쁜 PC 에서는 시간(sleep)만으로는 아직 준비를 기다리는 중일 수 있어, 쓰기·읽기 단계의 시험이 그 단계에 들어갔는지 확인하고 시작한다."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if adapter.next_id >= 1:
            return True
        time.sleep(0.05)
    return False


def watch_process(adapter):
    """어댑터가 띄운 작업자 프로세스를 `seen` 에 모은다 — 끝난 뒤 좀비·남은 프로세스가 0 인지 보려고 `_launch` 를 감싼다."""
    seen = []
    original = oa.OcrAdapter._launch

    def spy(self_):
        original(self_)
        seen.append(self_.process)
    return seen, mock.patch.object(oa.OcrAdapter, "_launch", spy)


class HardeningTest(AdapterCase):
    """라운드 2 — 응답 검증 목록(설계 3-5)의 빠진 칸·시간 초과 시계·취소·표준 오류 비유출·남은 프로세스 0."""
    BIG = (800, 800, bytes(800 * 800 * 3), "960")                       # 1.9MB — 작업자가 안 읽으면 파이프가 차서 쓰기가 막힌다

    def violations_are_dropped(self, modes):
        """작업자 방식마다 — 그 응답은 버려지고(`proto`, 줄 없음) 작업자는 끝난다."""
        for mode in modes:
            with self.subTest(mode=mode):
                adapter = self.make(mode=mode)
                outcome = read_within(adapter, 90, 16, 16, PIXELS, "960")
                self.assertIsNotNone(outcome, f"{mode}: 읽기가 끝나지 않는다")
                self.assertEqual((outcome.error, outcome.lines), ("proto", ()), mode)
                self.assertIsNone(adapter.process, "어긋난 응답을 보낸 작업자는 끝낸다")

    # 설계 3-5 의 검증 목록 일곱(알려진 칸만·형식·NaN/Infinity·줄 200개·줄당 400자·응답 256KB·요청 번호 일치)과 너무 깊은 JSON 을 규칙마다 따로 어댑터까지 올려 본다.
    def test_rule_unknown_fields_are_refused(self):
        self.violations_are_dropped(("badfield", "scorefield", "linefield"))

    def test_rule_wrong_formats_are_refused(self):
        self.violations_are_dropped(("badtype", "badrange", "garbage"))

    def test_rule_nan_and_infinity_are_refused_even_in_a_field_nobody_checks(self):
        self.violations_are_dropped(("nan", "nan_extra"))

    def test_rule_more_than_two_hundred_lines_is_refused(self):
        self.violations_are_dropped(("manylines",))

    def test_rule_a_line_over_four_hundred_characters_is_refused(self):
        self.violations_are_dropped(("longline",))

    def test_rule_an_answer_over_the_size_limit_is_refused(self):
        self.violations_are_dropped(("huge", "bigvalid"))

    def test_rule_a_request_number_that_does_not_match_is_refused(self):
        self.violations_are_dropped(("badid",))

    def test_rule_a_too_deeply_nested_json_is_refused(self):
        self.violations_are_dropped(("deepjson",))

    def test_an_answer_that_comes_before_the_worker_read_the_whole_request_is_a_violation(self):
        """작업자가 요청 본문을 다 읽기도 전에 응답하면(쓰는 스레드가 아직 막혀 있다) 약속 위반으로 보고 작업자를 끝낸다 — 그 응답을 믿지 않는다."""
        adapter = self.make(mode="early_answer", read_timeout=30, cancel_wait=0.5)
        outcome = read_within(adapter, 90, *self.BIG)
        self.assertIsNotNone(outcome)
        self.assertEqual((outcome.error, outcome.lines, adapter.process), ("proto", (), None))

    def test_the_reader_never_takes_more_than_the_limit_plus_one_byte_of_one_line(self):
        """줄바꿈 없이 끝없이 이어지는 출력도 한도(256KB)+1 바이트까지만 읽고 넘침만 알린다 — 읽기 상한이 없으면 끝없는 줄이 메모리를 다 쓴다(바이트가 얼마나 읽혔는지를 직접 본다)."""
        limit = proto.MAX_RESPONSE_BYTES
        stream = io.BytesIO(b"a" * (3 * limit))
        sink = queue.Queue()
        oa.OcrAdapter._pump_stdout(mock.Mock(stdout=stream), sink)
        self.assertIs(sink.get_nowait(), oa._OVERSIZE)
        self.assertIs(sink.get_nowait(), oa._EOF)
        self.assertTrue(sink.empty())
        self.assertEqual(stream.tell(), limit + 1, "넘침을 알린 뒤에는 더 읽지 않는다")

    def test_an_answer_of_exactly_the_size_limit_is_accepted_and_one_byte_more_is_not(self):
        """한 줄 256KB(줄바꿈까지 262144바이트) 경계 — 한도 상수·한 줄 읽기 상한·넘음 판정의 어긋남을 함께 잡는다."""
        accepted = read_within(self.make(mode="edge_ok"), 90, 16, 16, PIXELS, "960")
        refused = read_within(self.make(mode="edge_over"), 90, 16, 16, PIXELS, "960")
        self.assertIsNotNone(accepted)
        self.assertIsNotNone(refused)
        self.assertEqual((accepted.error, accepted.lines), ("", ()))
        self.assertEqual((refused.error, refused.lines), ("proto", ()))

    def test_a_net_attempts_count_in_an_otherwise_good_answer_is_net_blocked_and_ends_the_worker(self):
        adapter = self.make(mode="net_attempts")
        seen, patch = watch_process(adapter)
        with patch:
            outcome = self.read(adapter)
        self.assertEqual((outcome.error, outcome.lines, adapter.process), ("net_blocked", (), None))
        self.assertTrue(wait_dead(seen[0].pid))

    def test_a_ready_line_with_an_unknown_field_or_another_protocol_number_is_a_violation(self):
        """준비 줄도 응답이다 — 모르는 칸이 있거나 약속 번호가 다르면 버리고 작업자를 끝낸다."""
        for mode in ("badready", "badproto"):
            with self.subTest(mode=mode):
                adapter = self.make(mode=mode)
                outcome = read_within(adapter, 90, 16, 16, PIXELS, "960")
                self.assertIsNotNone(outcome)
                self.assertEqual((outcome.error, adapter.process), ("proto", None))

    def test_a_start_up_failure_line_is_named_instead_of_being_called_a_violation(self):
        adapter = self.make(mode="startup_engine")
        self.assertEqual(self.read(adapter).error, "engine")
        self.assertIsNone(adapter.process)

    def test_a_request_the_worker_never_reads_is_cut_off_by_the_read_time_out_even_though_the_write_blocks(self):
        adapter = self.make(mode="nostdin", read_timeout=1.0, cancel_wait=0.5)
        started = time.monotonic()
        outcome = read_within(adapter, 90, *self.BIG)
        self.assertIsNotNone(outcome, "쓰기가 막혀도 사진 한 장의 시간 초과는 지켜져야 한다")
        self.assertEqual(outcome.error, "timeout")
        self.assertLess(time.monotonic() - started, 80)
        self.assertIsNone(adapter.process)

    def test_a_cancel_gets_through_a_blocked_write_and_the_worker_is_killed_after_the_wait(self):
        adapter = self.make(mode="nostdin", read_timeout=60, cancel_wait=0.5)
        box = []
        thread = threading.Thread(target=lambda: box.append(adapter.read_rgb(*self.BIG)), daemon=True)
        thread.start()
        self.assertTrue(wait_until_write_started(adapter), "요청을 쓰기 시작해야 이 시험의 뜻이 있다(준비를 기다리다 취소하면 막힌 쓰기를 시험하지 못한다)")
        started = time.monotonic()
        time.sleep(1.0)
        adapter.cancel()
        thread.join(90)
        self.assertFalse(thread.is_alive(), "취소가 막힌 쓰기를 뚫고 나와야 한다")
        self.assertEqual(box[0].error, "cancelled")
        self.assertLess(time.monotonic() - started, 80)
        self.assertIsNone(adapter.process)

    def test_shutdown_returns_even_when_a_read_is_stuck_on_a_worker_that_does_not_listen(self):
        adapter = self.make(mode="nostdin", read_timeout=60, cancel_wait=0.5)
        thread = threading.Thread(target=lambda: adapter.read_rgb(*self.BIG), daemon=True)
        thread.start()
        self.assertTrue(wait_until_write_started(adapter), "요청을 쓰기 시작해야 이 시험의 뜻이 있다(준비를 기다리다 닫으면 막힌 쓰기를 시험하지 못한다)")
        time.sleep(1.0)
        finished = []
        closer = threading.Thread(target=lambda: (adapter.shutdown(), finished.append(True)), daemon=True)
        closer.start()
        closer.join(90)
        self.assertTrue(finished, "앱을 닫을 때 작업자 정리가 매달리면 안 된다")
        thread.join(60)
        self.assertIsNone(adapter.process)

    def test_the_standard_error_text_goes_nowhere_not_the_outcome_not_the_log_not_the_console_not_the_temp_folder(self):
        adapter = self.make(mode="stderr_secret")
        console, errors = io.StringIO(), io.StringIO()
        handler_records = []

        class Catch(logging.Handler):
            def emit(self, record):
                handler_records.append(record.getMessage())
        catcher = Catch(level=logging.DEBUG)
        logging.getLogger().addHandler(catcher)
        self.addCleanup(logging.getLogger().removeHandler, catcher)
        with contextlib.redirect_stdout(console), contextlib.redirect_stderr(errors):
            outcome = self.read(adapter)
            time.sleep(0.4)
            folder = adapter.temp_dir
            leftovers = os.listdir(folder) if folder and os.path.isdir(folder) else []
            adapter.shutdown()
        everything = "|".join([console.getvalue(), errors.getvalue(), repr(outcome), repr(vars(adapter)), "|".join(handler_records), repr(leftovers)])
        for needle in ("CANARY_", "UNIQ-PRIVATE", "photo.jpg", "Traceback"):
            self.assertNotIn(needle, everything, needle)
        self.assertEqual((outcome.error, leftovers), ("", []), "읽기는 정상이고 임시 폴더에는 아무것도 안 쓰였다")

    def test_the_worker_folder_is_the_default_work_dir_and_the_worker_really_runs_there(self):
        adapter = self.make(mode="env")
        expected = os.path.dirname(os.path.abspath(adapter.command[0]))
        self.assertEqual(adapter.work_dir, expected)
        seen = dict(line["text"].split("=", 1) for line in self.read(adapter).lines)
        self.assertEqual(os.path.normcase(os.path.realpath(seen["CWD"])), os.path.normcase(os.path.realpath(expected)))

    def test_an_explicit_work_dir_is_honoured(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter = self.make(mode="env", work_dir=folder)
            seen = dict(line["text"].split("=", 1) for line in self.read(adapter).lines)
            self.assertEqual(os.path.normcase(os.path.realpath(seen["CWD"])), os.path.normcase(os.path.realpath(folder)))
            adapter.shutdown()                                      # 작업자가 그 폴더에 서 있으면 윈도에서는 폴더를 지울 수 없다 — 먼저 끝낸다

    def test_no_worker_process_is_left_behind_after_any_ending_and_each_adapter_can_be_shut_down_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ("ok", "die", "garbage", "net_blocked", "eof", "badid", "slow", "spawn", "nostdin"):
                with self.subTest(mode=mode):
                    pidfile = Path(folder, mode + ".pid")
                    extra = ("--delay", "30") if mode == "slow" else (("--pidfile", str(pidfile)) if mode == "spawn" else ())
                    adapter = self.make(*extra, mode=mode, read_timeout=1.0, cancel_wait=0.5)
                    seen, patch = watch_process(adapter)
                    with patch:
                        read_within(adapter, 90, *(self.BIG if mode == "nostdin" else (16, 16, PIXELS, "960")))
                    adapter.shutdown()
                    adapter.shutdown()
                    for process in seen:
                        self.assertTrue(wait_dead(process.pid), f"{mode}: 작업자가 남았다")
                    if mode == "spawn" and pidfile.exists():
                        grandchild = int(pidfile.read_text(encoding="utf-8"))
                        self.addCleanup(kill_pid, grandchild)
                        self.assertTrue(wait_dead(grandchild), "spawn: 손자 프로세스가 남았다")
                    self.assertIsNone(adapter.process)

    def test_a_worker_that_leaves_while_the_app_waits_is_seen_as_died_not_as_a_hang(self):
        adapter = self.make(mode="die", read_timeout=300)
        outcome = read_within(adapter, 100, 16, 16, PIXELS, "960")
        self.assertIsNotNone(outcome, "죽은 작업자를 시간 초과(300초)까지 기다리면 안 된다 — 죽음을 바로 알아야 한다")
        self.assertEqual(outcome.error, "died")


class EnvironmentRound2Test(unittest.TestCase):
    def test_the_path_holds_only_the_system_folders_under_the_system_root_on_windows(self):
        parent = {"SystemRoot": "C:" + chr(92) + "Windows", "PATH": "C:" + chr(92) + "Tools;C:" + chr(92) + "Program Files" + chr(92) + "Other;C:" + chr(92) + "Windows", "APPDATA": "x"}
        with mock.patch.object(os, "name", "nt"), mock.patch.object(os, "pathsep", ";"):
            env = oa.build_environment(parent, "C:" + chr(92) + "tmp", None)
        parts = env["PATH"].split(";")
        self.assertEqual(len(parts), 2)
        for part in parts:
            self.assertTrue(part.lower().startswith("c:" + chr(92) + "windows"), part)
        self.assertNotIn("Tools", env["PATH"])
        self.assertNotIn("Other", env["PATH"])

    def test_the_proxy_trap_is_the_closed_local_port_nine_and_every_proxy_name_points_there(self):
        """닫힌 로컬 포트(루프백의 discard 포트 9)를 글자 그대로 못박는다 — 상수 이름만 견주면 값이 바뀌어도 시험이 따라 바뀐다. 어떤 프록시 이름도 바깥 주소를 가리키지 않는다."""
        self.assertEqual(oa.PROXY_TRAP, "127.0.0.1:9")
        env = oa.build_environment({"https_proxy": "evil.example:8080", "ALL_PROXY": "x", "my_Proxy_Setting": "y"}, "/tmp/w")
        for name, value in env.items():
            if "PROXY" in name.upper():
                self.assertEqual(value, "127.0.0.1:9", name)

    def test_without_a_system_root_or_on_other_systems_the_path_is_the_two_fixed_system_folders(self):
        for name, parent in (("posix", {"PATH": "/opt/evil:/usr/local/bin", "HOME": "/home/x"}), ("nt", {"PATH": "C:" + chr(92) + "Tools"})):
            with self.subTest(os=name), mock.patch.object(os, "name", name), mock.patch.object(os, "pathsep", ":"):
                env = oa.build_environment(parent, "/tmp/w")
                self.assertEqual(env["PATH"], "/usr/bin:/bin")
                self.assertNotIn("HOME", env)

    def test_nothing_of_the_parent_comes_through_except_the_named_system_values_and_the_forced_ones(self):
        parent = {name: "v" for name in ("SECRET_FOR_TEST", "USERPROFILE", "APPDATA", "HOME", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "PATH", "TEMP", "TMP", "HF_TOKEN", "OPENAI_API_KEY", "GITHUB_TOKEN")}
        parent.update({"SystemRoot": "C:" + chr(92) + "Windows", "windir": "C:" + chr(92) + "Windows", "ComSpec": "x", "PATHEXT": "y", "NUMBER_OF_PROCESSORS": "4", "my_PROXY": "p", "Http_Proxy": "q"})
        env = oa.build_environment(parent, "/tmp/w")
        allowed = set(oa.KEEP_WINDOWS) | set(oa.FIXED_ENVIRONMENT) | {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "TEMP", "TMP", "PATH", "my_PROXY", "Http_Proxy"}
        self.assertEqual(set(env) - allowed, set())
        for name in ("SECRET_FOR_TEST", "USERPROFILE", "APPDATA", "HOME", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "HF_TOKEN", "OPENAI_API_KEY", "GITHUB_TOKEN"):
            self.assertNotIn(name, env, name)
        self.assertEqual((env["my_PROXY"], env["Http_Proxy"]), (oa.PROXY_TRAP, oa.PROXY_TRAP), "이름에 PROXY 가 든 것은 대소문자와 상관없이 모두 닫힌 포트로")
        self.assertEqual((env["TEMP"], env["TMP"]), ("/tmp/w", "/tmp/w"))


@unittest.skipUnless(os.name == "nt", "Job 개체는 윈도 전용이다")
class JobObjectTest(unittest.TestCase):
    def test_the_job_object_can_be_made_and_takes_a_process(self):
        job = oa.JobObject()
        self.addCleanup(job.close)
        self.assertTrue(job.ok)
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"], creationflags=oa.NO_WINDOW)
        self.addCleanup(kill_and_reap, child)
        self.assertTrue(job.assign(child))

    def test_closing_the_job_handle_ends_the_process_like_an_app_that_died(self):
        job = oa.JobObject()
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"], creationflags=oa.NO_WINDOW)
        self.addCleanup(kill_and_reap, child)
        self.assertTrue(job.assign(child))
        self.assertIsNone(child.poll())
        job.close()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.fail("앱이 죽어 핸들이 닫히면 작업자도 끝나야 한다(KILL_ON_JOB_CLOSE)")
        self.assertFalse(job.ok)
        job.close()                                                 # 두 번 닫아도 같다

    def test_the_process_memory_limit_is_really_applied(self):
        job = oa.JobObject(memory_limit=64 * 1024 * 1024)
        self.addCleanup(job.close)
        code = "try:" + chr(10) + "    bytearray(300 * 1024 * 1024)" + chr(10) + "    print('ALLOCATED')" + chr(10) + "except MemoryError:" + chr(10) + "    print('MEMORYERROR')" + chr(10)
        child = subprocess.Popen([sys.executable, "-B", "-c", code], stdout=subprocess.PIPE, creationflags=oa.NO_WINDOW)
        self.assertTrue(job.assign(child))
        out, _ = child.communicate(timeout=60)
        self.assertIn(b"MEMORYERROR", out, "한도를 넘는 메모리는 얻지 못해야 한다")

    def test_the_default_limit_is_one_gigabyte_and_the_adapter_puts_the_worker_in_a_job(self):
        self.assertEqual(oa.MEMORY_LIMIT_BYTES, 1024 * 1024 * 1024)
        with mock.patch.object(oa.JobObject, "assign", autospec=True, return_value=True) as assign:
            local_ocr_on()
            self.addCleanup(local_ocr_off)
            adapter = oa.OcrAdapter(command(), prepare_timeout=60, read_timeout=60, priority_class=0)
            self.addCleanup(adapter.shutdown)
            self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "")
        self.assertEqual(assign.call_count, 1, "작업자를 띄울 때마다 Job 개체에 넣는다")


class PosixBranchTest(unittest.TestCase):
    """윈도에서도 리눅스 쪽 갈래(`os.name` 이 nt 가 아닐 때)를 좁게 흉내 내어 본다 — 실제 리눅스 칸은 CI 가 돌린다."""

    def test_kill_tree_uses_the_process_group_and_then_the_process_itself_on_other_systems(self):
        process = mock.Mock(pid=4242)
        with mock.patch.object(os, "name", "posix"), mock.patch.object(os, "killpg", create=True) as killpg, mock.patch.object(signal, "SIGKILL", 9, create=True), mock.patch.object(subprocess, "run") as run:
            oa.kill_tree(process)
        killpg.assert_called_once_with(4242, 9)
        process.kill.assert_called_once()
        process.wait.assert_called()
        run.assert_not_called()

    def test_kill_tree_never_raises_even_when_everything_fails(self):
        process = mock.Mock(pid=1)
        process.kill.side_effect = OSError("x")
        process.wait.side_effect = OSError("y")
        with mock.patch.object(os, "name", "posix"), mock.patch.object(os, "killpg", create=True, side_effect=OSError("z")):
            oa.kill_tree(process)
        with mock.patch.object(os, "name", "nt"), mock.patch.object(subprocess, "run", side_effect=OSError("w")):
            oa.kill_tree(process)

    def test_on_windows_the_tree_is_ended_with_taskkill_and_a_hidden_window(self):
        process = mock.Mock(pid=77)
        with mock.patch.object(os, "name", "nt"), mock.patch.object(subprocess, "run") as run:
            oa.kill_tree(process)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["taskkill", "/PID", "77", "/T", "/F"])
        self.assertEqual(kwargs["creationflags"], oa.NO_WINDOW)

    def test_the_launch_on_other_systems_starts_a_new_session_and_never_passes_windows_only_flags(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        process = mock.Mock(pid=5, stdout=io.BytesIO(b""), stderr=io.BytesIO(b""), stdin=io.BytesIO())
        adapter = oa.OcrAdapter(["/bin/worker"], work_dir=tempfile.gettempdir())
        with mock.patch.object(os, "name", "posix"), mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            adapter._launch()
        adapter._remove_temp()
        _, kwargs = popen.call_args
        self.assertTrue(kwargs["start_new_session"])
        self.assertNotIn("creationflags", kwargs)
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["cwd"], tempfile.gettempdir())

    def test_the_launch_on_windows_hides_the_window_lowers_the_priority_and_has_no_shell(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        process = mock.Mock(pid=5, stdout=io.BytesIO(b""), stderr=io.BytesIO(b""), stdin=io.BytesIO())
        adapter = oa.OcrAdapter(["C:" + chr(92) + "ocr" + chr(92) + "ocr_worker.exe"])
        with mock.patch.object(os, "name", "nt"), mock.patch.object(oa, "JobObject", return_value=mock.Mock()), mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            adapter._launch()
        adapter._remove_temp()
        args, kwargs = popen.call_args
        self.assertEqual(kwargs["creationflags"], oa.NO_WINDOW | oa.BELOW_NORMAL)
        self.assertNotIn("start_new_session", kwargs)
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(args[0], ["C:" + chr(92) + "ocr" + chr(92) + "ocr_worker.exe"], "인자는 고정이다")

    def test_the_priority_class_defaults_to_below_normal_and_a_given_value_reaches_the_launch_flags(self):
        self.assertEqual(oa.OcrAdapter(["worker"]).priority_class, oa.BELOW_NORMAL)
        self.assertEqual(oa.OcrAdapter(["worker"], priority_class=0).priority_class, 0)
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        process = mock.Mock(pid=5, stdout=io.BytesIO(b""), stderr=io.BytesIO(b""), stdin=io.BytesIO())
        adapter = oa.OcrAdapter(["C:" + chr(92) + "ocr" + chr(92) + "ocr_worker.exe"], priority_class=0x20)
        with mock.patch.object(os, "name", "nt"), mock.patch.object(oa, "JobObject", return_value=mock.Mock()), mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            adapter._launch()
        adapter._remove_temp()
        self.assertEqual(popen.call_args[1]["creationflags"], oa.NO_WINDOW | 0x20, "건네 준 우선순위 값이 창 숨김과 함께 그대로 간다")

    def test_the_windows_priority_and_window_constants_are_zero_where_they_do_not_exist(self):
        for name, value in (("CREATE_NO_WINDOW", oa.NO_WINDOW), ("BELOW_NORMAL_PRIORITY_CLASS", oa.BELOW_NORMAL)):
            self.assertEqual(value, getattr(subprocess, name, 0), name)
        if os.name == "nt":
            self.assertEqual((oa.NO_WINDOW, oa.BELOW_NORMAL), (0x08000000, 0x00004000))

    def test_the_job_object_does_nothing_and_never_raises_off_windows(self):
        with mock.patch.object(os, "name", "posix"):
            job = oa.JobObject()
        self.assertFalse(job.ok)
        self.assertFalse(job.assign(mock.Mock()))
        job.close()


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
