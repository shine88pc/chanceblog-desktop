"""글자 읽기 작업자 어댑터 `ui/ocr_adapter.py`(결정 D-512, 설계서 3-3·3-5·3-6·3-9, 시험 계획 T-A)를 **가짜 작업자**(`tests/ocr_fake_worker.py`, 순수 파이썬)로 시험한다 — 진짜 프로세스를 띄워 보지만 진짜 엔진·사진은 없다.

지키는 것:
  1) 관문 — `LOCAL_OCR` 가 꺼져 있으면 하위 프로세스를 한 번도 안 띄운다(동적 막이가 센다).
  2) 요청 — 머리 한 줄 + 픽셀뿐이고 경로·파일 이름·사진 번호·종류·메모·Exif 가 한 글자도 없다(작업자가 받은 바이트를 그대로 가로채 본다).
  3) 응답 검증 — 모르는 칸·번호 불일치·NaN·줄 201개·줄당 401자·256KB 넘는 줄·JSON 아님·되풀이 응답은 버리고 `proto`, 작업자는 정리된다.
  4) 시간·취소 — 준비·사진 시간 초과는 프로세스 트리(손자 포함)를 끈다. 취소는 기다림 안에 끝나지 않으면 끈다. 죽음·EOF 는 `died`. `net_blocked` 는 즉시 알리고 끝낸다.
  5) 환경 변수 — 부모의 비밀은 안 넘어가고 프록시는 닫힌 포트, 오프라인·텔레메트리 끔 값이 있다. 표준 오류는 비우기만 한다. 끝나면 전용 임시 폴더가 지워지고 좀비 프로세스가 없다.
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
import ntpath
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
WORKER_PATH = os.path.abspath(os.path.join(tempfile.gettempdir(), "ocr", "ocr_worker.exe"))      # 절대 경로(운영의 작업자 실행 파일 자리 흉내 — 실제로 띄우지는 않는다)
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


def wait_dead(pid, seconds=30.0):
    """프로세스가 끝나길 기다린다. 마지막 판정은 늘 '기한이 지난 뒤에 시작한 확인' 이다 — CPU 가 아주 바쁜 PC 에서는 확인(tasklist) 한 번이 기한보다 오래 걸려, 확인 도중 끝난 프로세스를 '남았다' 고 잘못 판정하던 틈(3.10 전체 훑기에서 한 번)을 막는다."""
    end = time.monotonic() + seconds
    while True:
        expired = time.monotonic() >= end
        if not pid_alive(pid):
            return True
        if expired:
            return False
        time.sleep(0.1)


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
        options.setdefault("verify", None)                          # 시험은 해시 확인 없이 띄우기를 일부러 고른다(운영은 verify 를 꼭 준다 — 필수 인자)
        adapter = oa.OcrAdapter(command(*extra, mode=mode), **options)
        self.adapters.append(adapter)
        self.addCleanup(adapter.shutdown)
        return adapter

    def read(self, adapter):
        return adapter.read_rgb(16, 16, PIXELS, "960")


class GateTest(unittest.TestCase):
    def test_when_the_gate_is_off_no_process_is_ever_started(self):
        adapter = oa.OcrAdapter(command(), verify=None)
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
        adapter = oa.OcrAdapter(command(), verify=None, prepare_timeout=60, read_timeout=60)
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
        self.assertEqual(seen["TEMP"], adapter.temp_dir, "작업자가 본 TEMP 는 어댑터가 만든 전용 폴더다")
        self.assertTrue(os.path.basename(adapter.temp_dir).startswith("cbd-ocr-"))
        self.assertEqual(os.path.normcase(os.path.dirname(adapter.temp_dir)), os.path.normcase(os.path.abspath(tempfile.gettempdir())), "전용 폴더는 시스템 임시 폴더 바로 아래")
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

    def test_a_result_that_arrives_after_the_cancel_is_discarded_by_the_adapter_and_the_finished_worker_lives_on(self):
        """검증 Q QP-9 (나) — 취소했는데 작업자가 기다림 안에 끝낸 결과는 어댑터가 버린다(컨트롤러 쪽 _live 가 한 번 더 버리지만 방어는 두 겹이다). 끝낸 작업자는 죽이지 않는다."""
        adapter = self.make("--delay", "1.5", mode="slow", cancel_wait=30, read_timeout=60)
        results = []
        worker = threading.Thread(target=lambda: results.append(self.read(adapter)))
        worker.start()
        self.assertTrue(wait_until_write_started(adapter), "읽기 단계에 들어가야 한다(준비를 기다리다 취소하면 이 시험의 뜻이 사라진다)")
        adapter.cancel()
        worker.join(90)
        self.assertFalse(worker.is_alive())
        self.assertEqual((results[0].error, results[0].lines), ("cancelled", ()), "취소했으면 끝난 결과도 쓰지 않는다")
        self.assertIsNotNone(adapter.process, "기다림 안에 끝낸 작업자는 죽이지 않는다")
        self.assertEqual((self.read(adapter).error, adapter.launches), ("", 1), "다음 읽기는 같은 작업자로 된다")

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
        adapter = oa.OcrAdapter([str(HERE / "no_such_worker_program.exe")], verify=None)
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


    def test_a_worker_that_dies_leaving_a_grandchild_that_holds_the_pipe_does_not_hang_the_cleanup(self):
        """검증 S SP-3 — 작업자만 죽고 손자(표준 입출력 파이프를 쥠)가 남아도 정리·읽기가 매달리지 않고 died 로 끝나며 손자도 끝난다(Job 개체를 핸들 닫기보다 먼저 닫는 순서)."""
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder, "grandchild.pid")
            adapter = self.make("--pidfile", str(pidfile), mode="die_with_grandchild", read_timeout=60)
            outcome = read_within(adapter, 100, 16, 16, PIXELS, "960")
            grandchild = int(pidfile.read_text(encoding="utf-8")) if pidfile.exists() else None
        if grandchild:
            self.addCleanup(kill_pid, grandchild)
        self.assertIsNotNone(outcome, "작업자가 죽었는데 읽기가 끝나지 않는다 — 손자가 쥔 파이프에 정리가 매달렸다")
        self.assertEqual(outcome.error, "died")
        self.assertIsNone(adapter.process)
        self.assertTrue(wait_dead(grandchild), "손자 프로세스까지 끝나야 한다")
        started = time.monotonic()
        adapter.shutdown()
        self.assertLess(time.monotonic() - started, 30, "그 뒤 앱 종료도 매달리지 않는다")

    def test_a_worker_that_floods_unrequested_lines_cannot_grow_the_app_queue_and_the_next_read_is_a_violation(self):
        """검증 S SP-4 — 정상 응답 뒤 쉬는 동안 줄을 쏟아내도 앱 쪽 대기열은 한도에서 멈추고(앱 메모리가 안 늘고), 다음 읽기는 약속 위반으로 끝나 정리되며 읽기 스레드는 그만둔다."""
        adapter = self.make(mode="flood_after_result")
        self.assertEqual(self.read(adapter).error, "")
        stop = adapter.pump_stop
        end = time.monotonic() + 90
        while adapter.lines.qsize() < oa.LINE_QUEUE_MAX and time.monotonic() < end:
            time.sleep(0.05)
        self.assertEqual(adapter.lines.qsize(), oa.LINE_QUEUE_MAX, "대기열이 한도까지 찬다")
        time.sleep(1.0)
        self.assertEqual(adapter.lines.qsize(), oa.LINE_QUEUE_MAX, "한도를 넘어 늘지 않는다")
        outcome = read_within(adapter, 90, 16, 16, PIXELS, "960")
        self.assertIsNotNone(outcome)
        self.assertEqual((outcome.error, adapter.process), ("proto", None))
        self.assertTrue(stop.is_set(), "정리되면 읽기 스레드에 그만하라고 알린다")


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

    def test_the_forced_environment_values_are_pinned_literally(self):
        """오프라인·텔레메트리 끔 값(검증 S SP-17 — 상수를 시험이 따라가지 않게 글자 그대로)."""
        self.assertEqual(dict(oa.FIXED_ENVIRONMENT), {"HF_HUB_OFFLINE": "1", "DO_NOT_TRACK": "1", "ORT_DISABLE_TELEMETRY": "1", "OPENCV_OPENCL_RUNTIME": "disabled", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})

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
        keep = ("SystemRoot", "SYSTEMROOT", "windir", "WINDIR", "ComSpec", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS")
        self.assertEqual(tuple(oa.KEEP_WINDOWS), keep, "부모에서 옮기는 윈도 시스템 변수는 이 열 개뿐이다 — 늘리면(사용자 이름·컴퓨터 이름·로컬 앱 폴더 위치 등) 시험이 걸린다(검증 S SP-17)")
        private = ("SECRET_FOR_TEST", "USERPROFILE", "APPDATA", "HOME", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "HF_TOKEN", "OPENAI_API_KEY", "GITHUB_TOKEN",
                   "USERNAME", "COMPUTERNAME", "USERDOMAIN", "USERDNSDOMAIN", "LOCALAPPDATA", "HOMEPATH", "HOMEDRIVE", "LOGONSERVER", "SESSIONNAME", "ProgramData", "ALLUSERSPROFILE", "PUBLIC",
                   "USER", "LOGNAME", "SHELL", "TERM")
        parent = {name: "v" for name in private + ("PATH", "TEMP", "TMP")}
        parent.update({name: "k" for name in keep})
        parent.update({"SystemRoot": "C:" + chr(92) + "Windows", "SYSTEMROOT": "C:" + chr(92) + "Windows", "windir": "C:" + chr(92) + "Windows", "WINDIR": "C:" + chr(92) + "Windows", "my_PROXY": "p", "Http_Proxy": "q"})
        env = oa.build_environment(parent, "/tmp/w")
        allowed = set(keep) | {"HF_HUB_OFFLINE", "DO_NOT_TRACK", "ORT_DISABLE_TELEMETRY", "OPENCV_OPENCL_RUNTIME", "PYTHONDONTWRITEBYTECODE", "PYTHONUTF8"} | {
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "TEMP", "TMP", "PATH", "my_PROXY", "Http_Proxy"}
        self.assertEqual(set(env) - allowed, set(), "허용 집합은 상수 이름이 아니라 글자 그대로다 — 부모의 사용자·컴퓨터 이름이 새면 걸린다")
        for name in private:
            self.assertNotIn(name, env, name)
        for name in keep:
            self.assertEqual(env[name], parent[name], name)
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

    def test_the_adapter_records_whether_the_worker_went_into_the_job(self):
        """검증 S SP-15 + 감사 OCR-S1 R2(결정 D-585) — Job 개체에 넣었는지 남기고, 윈도에서 못 넣었으면 그 작업자로는 읽지 않는다(예전에는 못 넣어도 읽기가 됐다 — 메모리 한도도 앱이 죽어도 따라 끝남도 없는 채로)."""
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        adapter = oa.OcrAdapter(command(), verify=None, prepare_timeout=60, read_timeout=60, priority_class=0)
        self.addCleanup(adapter.shutdown)
        self.assertFalse(adapter.job_assigned)
        self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "")
        self.assertIs(adapter.job_assigned, True)
        adapter.shutdown()
        with mock.patch.object(oa.JobObject, "assign", autospec=True, return_value=False):
            outcome = adapter.read_rgb(16, 16, PIXELS, "960")
        self.assertEqual(outcome.error, "blocked", "윈도에서 Job 개체에 못 넣으면 읽지 않고 blocked 로 끝낸다")
        self.assertIs(adapter.job_assigned, False, "못 넣었으면 못 넣었다고 남긴다")
        self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "", "고장이 사라지면 같은 어댑터가 새 작업자로 다시 읽는다")
        self.assertIs(adapter.job_assigned, True)

    def test_the_default_limit_is_one_gigabyte_and_the_adapter_puts_the_worker_in_a_job(self):
        self.assertEqual(oa.MEMORY_LIMIT_BYTES, 1024 * 1024 * 1024)
        with mock.patch.object(oa.JobObject, "assign", autospec=True, return_value=True) as assign:
            local_ocr_on()
            self.addCleanup(local_ocr_off)
            adapter = oa.OcrAdapter(command(), verify=None, prepare_timeout=60, read_timeout=60, priority_class=0)
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
        """감사 OCR-S1 R3(결정 D-586) — 예전에는 `["taskkill", …]` 이름만 부르는 호출이라 현재 폴더·앱 폴더의 같은 이름 실행 파일이 대신 실행될 수 있었다. 이제는 시스템 폴더(`SystemRoot`, 환경에서 읽는다)의 `System32` 아래 `taskkill.exe` **절대 경로**이고 나머지 인자는 그대로다."""
        process = mock.Mock(pid=77)
        root = "D:" + chr(92) + "WinTest"
        with mock.patch.object(os, "name", "nt"), mock.patch.object(os, "environ", {"SystemRoot": root, "PATH": "C:" + chr(92) + "Evil"}), mock.patch.object(oa.winroot, "windows_directory", return_value=None), mock.patch.object(subprocess, "run") as run:
            oa.kill_tree(process)
        args, kwargs = run.call_args
        self.assertEqual(args[0], [root + chr(92) + "System32" + chr(92) + "taskkill.exe", "/PID", "77", "/T", "/F"], "이름만이 아니라 시스템 폴더의 절대 경로로 부른다")
        self.assertNotEqual(args[0][0].lower(), "taskkill", "이름만 부르는 호출이 다시 생기면 빨강이다")
        self.assertEqual(kwargs["creationflags"], oa.NO_WINDOW)
        self.assertEqual(run.call_count, 1, "이름만 부르는 대체 호출을 한 번 더 하지 않는다")

    def test_the_launch_on_other_systems_starts_a_new_session_and_never_passes_windows_only_flags(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        process = mock.Mock(pid=5, stdout=io.BytesIO(b""), stderr=io.BytesIO(b""), stdin=io.BytesIO())
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None, work_dir=tempfile.gettempdir())
        with mock.patch.object(os, "name", "posix"), mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            adapter._launch()
        adapter._remove_temp()
        self.assertIs(adapter.job_assigned, False, "윈도가 아니면 Job 개체가 없다")
        _, kwargs = popen.call_args
        for stream in ("stdin", "stdout", "stderr"):
            self.assertIs(kwargs[stream], subprocess.PIPE, f"{stream}: 작업자의 표준 입출력은 모두 앱이 받는 파이프다(표준 오류를 앱 콘솔로 흘리면 안 된다 — 검증 Q QP-3)")
        self.assertTrue(kwargs["start_new_session"])
        self.assertNotIn("creationflags", kwargs)
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["cwd"], tempfile.gettempdir())

    def test_the_launch_on_windows_hides_the_window_lowers_the_priority_and_has_no_shell(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        process = mock.Mock(pid=5, stdout=io.BytesIO(b""), stderr=io.BytesIO(b""), stdin=io.BytesIO())
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None)
        with mock.patch.object(os, "name", "nt"), mock.patch.object(oa, "JobObject", return_value=mock.Mock()), mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            adapter._launch()
        adapter._remove_temp()
        args, kwargs = popen.call_args
        for stream in ("stdin", "stdout", "stderr"):
            self.assertIs(kwargs[stream], subprocess.PIPE, f"{stream}: 작업자의 표준 입출력은 모두 앱이 받는 파이프다(검증 Q QP-3)")
        self.assertEqual(kwargs["creationflags"], oa.NO_WINDOW | oa.BELOW_NORMAL)
        self.assertNotIn("start_new_session", kwargs)
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(args[0], [WORKER_PATH], "인자는 고정이다")

    def test_the_priority_class_defaults_to_below_normal_and_a_given_value_reaches_the_launch_flags(self):
        self.assertEqual(oa.OcrAdapter([WORKER_PATH], verify=None).priority_class, oa.BELOW_NORMAL)
        self.assertEqual(oa.OcrAdapter([WORKER_PATH], verify=None, priority_class=0).priority_class, 0)
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        process = mock.Mock(pid=5, stdout=io.BytesIO(b""), stderr=io.BytesIO(b""), stdin=io.BytesIO())
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None, priority_class=0x20)
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


class ConstructionTest(unittest.TestCase):
    """검증 S SP-5 — 해시 확인(verify)을 빠뜨리면 조용히 안 걸리는 길이 없고, 상대 경로 작업자는 받지 않는다."""

    def test_verify_is_a_required_argument_so_a_forgotten_hash_check_is_a_type_error(self):
        with self.assertRaises(TypeError):
            oa.OcrAdapter(command())
        self.assertIsNone(oa.OcrAdapter(command(), verify=None).verify, "'확인 없음' 을 일부러 고르는 길(시험)은 남는다")
        check = lambda: None  # noqa: E731
        self.assertIs(oa.OcrAdapter(command(), verify=check).verify, check)

    def test_a_relative_or_empty_command_is_refused_when_the_adapter_is_made(self):
        for bad in ([], [""], ["worker.exe"], ["." + os.sep + "worker"], ["bin" + os.sep + "worker"], ["C:worker.exe"], [None]):
            with self.subTest(command=repr(bad)):
                with self.assertRaises((ValueError, TypeError)):
                    oa.OcrAdapter(bad, verify=None)
        self.assertEqual(oa.OcrAdapter([WORKER_PATH], verify=None).command, [WORKER_PATH])

    def test_the_adapter_defaults_are_the_numbers_of_the_design(self):
        """운영은 어댑터의 기본값을 쓴다 — 컨트롤러 상수와 따로 글자 그대로 못박는다(검증 S SP-8)."""
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None)
        self.assertEqual((adapter.prepare_timeout, adapter.read_timeout, adapter.cancel_wait, adapter.idle_exit), (150, 90, 3, 300))
        self.assertEqual(adapter.priority_class, oa.BELOW_NORMAL)
        self.assertEqual((oa.MEMORY_LIMIT_BYTES, oa.LINE_QUEUE_MAX, oa.CLOSE_WAIT), (1024 * 1024 * 1024, 16, 3.0))
        self.assertEqual(oa.PROXY_TRAP, "127.0.0.1:9")


class FakeClock:
    """부를 때마다 step 초씩 가는 가짜 시계 — 한도(limit)를 넘기면 시험이 바로 실패한다. 실제 시간이 아니라 시계 값으로 시간 경계를 잡으므로 CPU 가 바빠도 흔들리지 않는다."""

    def __init__(self, step=1.0, limit=None):
        self.now, self.step, self.limit = 0.0, step, limit

    def __call__(self):
        self.now += self.step
        if self.limit is not None and self.now > self.limit:
            raise AssertionError("시계가 한도(%s)를 넘어 갔다 — 시간 초과가 너무 늦게 걸린다" % self.limit)
        return self.now


class StubProcess:
    """아무것도 안 보내는 살아 있는 작업자 흉내(표준 입력은 받아 버린다) — 진짜 프로세스 없이 시간 경계만 본다."""
    pid = 4242

    def __init__(self):
        self.stdin, self.stdout, self.stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()

    def poll(self):
        return None

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


class TimeValuesTest(unittest.TestCase):
    """검증 S SP-8 — 준비·사진·취소 대기가 주어진 값 그대로(너무 늦지도 이르지도 않게) 걸리는지 가짜 시계로 본다."""

    def adapter(self, **options):
        options.setdefault("prepare_timeout", 10 ** 6)
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None, **options)
        adapter.process = StubProcess()
        return adapter

    def test_the_prepare_time_out_comes_after_exactly_the_given_clock_seconds(self):
        clock = FakeClock(step=1.0, limit=5 + 12)
        adapter = self.adapter(clock=clock, prepare_timeout=5)
        with self.assertRaises(oa.AdapterError) as caught:
            adapter._wait_ready()
        self.assertEqual(caught.exception.name, "timeout")
        self.assertGreaterEqual(clock.now, 5 + 1, "주어진 시간이 지나기 전에는 시간 초과가 나지 않는다")

    def test_the_photo_read_time_out_comes_after_exactly_the_given_clock_seconds(self):
        clock = FakeClock(step=1.0, limit=5 + 12)
        adapter = self.adapter(clock=clock, read_timeout=5)
        with mock.patch.object(oa, "kill_tree"):
            outcome = adapter.read_rgb(16, 16, PIXELS, "960")
        self.assertEqual(outcome.error, "timeout")
        self.assertGreaterEqual(clock.now, 5 + 1, "주어진 시간이 지나기 전에는 시간 초과가 나지 않는다")
        self.assertIsNone(adapter.process)

    def test_a_cancel_waits_exactly_the_cancel_wait_in_clock_seconds_and_then_gives_up(self):
        clock = FakeClock(step=1.0, limit=3 + 10)
        adapter = self.adapter(clock=clock, cancel_wait=3)
        adapter.cancel_event.set()
        self.assertIsNone(adapter._next(10 ** 9))
        self.assertGreaterEqual(clock.now, 1 + 3, "취소 뒤 기다림 안에는 포기하지 않는다")

    def test_the_idle_exit_waits_exactly_the_idle_seconds(self):
        clock = FakeClock(step=0.0)
        adapter = self.adapter(clock=clock, idle_exit=300)
        adapter.last_activity = 1000.0
        with mock.patch.object(oa, "kill_tree"):
            clock.now = 1000.0 + 299.9
            self.assertFalse(adapter.maybe_idle_exit())
            clock.now = 1000.0 + 300.0
            self.assertTrue(adapter.maybe_idle_exit())


class StopOrderTest(unittest.TestCase):
    """검증 S SP-3 — 정리(`_stop`)의 순서와 매달림 방지를 가짜 프로세스로 본다(진짜 taskkill 은 부르지 않는다)."""

    def process(self, order, block=None):
        def handle(name):
            item = mock.Mock()

            def close():
                order.append("close:" + name)
                if block is not None and name == "stdout":
                    block.wait(30)
            item.close.side_effect = close
            return item
        process = mock.Mock(pid=4242)
        process.poll.return_value = None
        process.stdin, process.stdout, process.stderr = handle("stdin"), handle("stdout"), handle("stderr")
        return process

    def test_the_job_is_closed_right_after_the_tree_kill_and_before_any_pipe_handle_is_closed(self):
        order = []
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None)
        adapter.process = self.process(order)
        job = mock.Mock()
        job.close.side_effect = lambda: order.append("job_close")
        adapter.job = job
        with mock.patch.object(oa, "kill_tree", side_effect=lambda process: order.append("kill_tree")):
            adapter._stop(kill=True)
        self.assertEqual(order[:2], ["kill_tree", "job_close"], "Job 닫기가 트리 종료 바로 뒤, 핸들 닫기보다 먼저다")
        self.assertEqual(sorted(order[2:]), ["close:stderr", "close:stdin", "close:stdout"])
        self.assertEqual(order.count("job_close"), 1, "Job 은 한 번만 닫는다")
        self.assertTrue(adapter.job is None and adapter.process is None)
        self.assertTrue(adapter.pump_stop.is_set(), "읽기 스레드에 그만하라고 알린다")

    def test_a_pipe_handle_that_will_not_close_does_not_hang_the_cleanup(self):
        order = []
        release = threading.Event()
        self.addCleanup(release.set)
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None)
        adapter.process = self.process(order, block=release)
        with mock.patch.object(oa, "kill_tree"), mock.patch.object(oa, "CLOSE_WAIT", 0.3):
            started = time.monotonic()
            adapter._stop(kill=True)
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10, "핸들 닫기가 막혀도 CLOSE_WAIT 만 기다리고 돌아온다")
        self.assertIsNone(adapter.process)

    def test_stopping_politely_asks_the_worker_to_leave_with_a_bye_line_and_a_kill_never_does(self):
        """검증 Q QP-9 (다) — 유휴 종료(kill 이 거짓)는 먼저 bye 한 줄을 부탁하고, 이미 끝났다면 트리를 끄지 않는다. kill 이 참이면 부탁 없이 바로 끈다."""
        for kill, asks in ((False, True), (True, False)):
            with self.subTest(kill=kill):
                adapter = oa.OcrAdapter([WORKER_PATH], verify=None)
                process = mock.Mock(pid=4242)
                process.poll.return_value = 0
                adapter.process = process
                with mock.patch.object(oa, "kill_tree") as kill_tree:
                    adapter._stop(kill=kill)
                if asks:
                    process.stdin.write.assert_called_once_with(proto.dumps_line({"t": "bye"}))
                else:
                    process.stdin.write.assert_not_called()
                self.assertEqual(kill_tree.called, kill, "이미 끝난 작업자는 정중하게 끝낼 때 다시 끄지 않고, kill 이면 끈다")

    def test_a_worker_that_is_still_alive_after_the_polite_bye_is_killed_as_a_tree(self):
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None)
        process = mock.Mock(pid=4242)
        process.poll.return_value = None
        adapter.process = process
        with mock.patch.object(oa, "kill_tree") as kill_tree:
            adapter._stop(kill=False)
        process.stdin.write.assert_called_once_with(proto.dumps_line({"t": "bye"}))
        kill_tree.assert_called_once_with(process)

    def test_stopping_twice_or_with_nothing_started_is_harmless(self):
        adapter = oa.OcrAdapter([WORKER_PATH], verify=None)
        adapter._stop(kill=True)
        adapter._stop(kill=False)
        self.assertTrue(adapter.pump_stop.is_set())
        self.assertIsNone(adapter.process)


class LineQueueTest(unittest.TestCase):
    """검증 S SP-4 — 표준 출력 읽기(`_pump_stdout`)가 한도 있는 대기열에서 멈추고, 멈추라고 하면 그만둔다."""
    LINE = b'{"t":"alive"}' + chr(10).encode("ascii")

    def test_a_reader_facing_a_flood_stops_at_the_queue_limit_and_leaves_when_told_to_stop(self):
        stream = io.BytesIO(self.LINE * 400)
        sink = queue.Queue(maxsize=5)
        stop = threading.Event()
        thread = threading.Thread(target=oa.OcrAdapter._pump_stdout, args=(mock.Mock(stdout=stream), sink, stop), daemon=True)
        thread.start()
        end = time.monotonic() + 30
        while sink.qsize() < 5 and time.monotonic() < end:
            time.sleep(0.02)
        time.sleep(0.5)
        self.assertEqual(sink.qsize(), 5)
        self.assertTrue(thread.is_alive(), "가득 차면 읽기를 멈추고 기다린다")
        self.assertLessEqual(stream.tell(), 7 * len(self.LINE), "가득 찬 뒤에는 더 읽지 않는다(손에 든 한 줄까지만)")
        stop.set()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "멈추라고 하면 나온다")

    def test_a_few_lines_and_the_end_marker_pass_through_in_order(self):
        sink = queue.Queue(maxsize=oa.LINE_QUEUE_MAX)
        oa.OcrAdapter._pump_stdout(mock.Mock(stdout=io.BytesIO(self.LINE * 3)), sink)
        items = [sink.get_nowait() for _ in range(4)]
        self.assertEqual(items, [self.LINE, self.LINE, self.LINE, oa._EOF])
        self.assertTrue(sink.empty())

    def test_the_end_marker_waits_for_room_and_gives_up_when_told_to_stop(self):
        sink = queue.Queue(maxsize=1)
        sink.put(b"x")
        stop = threading.Event()
        thread = threading.Thread(target=oa.OcrAdapter._pump_stdout, args=(mock.Mock(stdout=io.BytesIO(b"")), sink, stop), daemon=True)
        thread.start()
        thread.join(1.0)
        self.assertTrue(thread.is_alive(), "자리가 없으면 끝 표지도 기다린다")
        stop.set()
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(sink.qsize(), 1)


def process_reach(source):
    """소스 한 덩이가 하위 프로세스·실행에 닿는 길을 모은다(검증 Q QP-2) -> (문제 목록, 찾은 이름들). 문제: 하위 프로세스 모듈 가져오기·별칭·from 가져오기·모듈을 이름만 따로 쓰는 것.
    찾은 이름: `subprocess.이름`·`os.이름`·`ctypes.이름` 사용 횟수, kernel32 에서 부르는 이름, WinDLL 로 여는 라이브러리, 동적 이름 찾기(getattr·eval 등)."""
    tree = ast.parse(source)
    parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    process_modules = ("_winapi", "_posixsubprocess", "pty", "popen2", "commands", "importlib")
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in process_modules:
                    problems.append("가져옴 " + alias.name)
                if root in ("subprocess", "os", "ctypes") and alias.asname is not None:
                    problems.append(f"별칭 {alias.name} as {alias.asname}")
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            root = (node.module or "").split(".")[0]
            if root in process_modules + ("subprocess", "os"):
                problems.append(f"from {node.module} import …")
            if root == "ctypes" and [alias.name for alias in node.names] != ["wintypes"]:
                problems.append("from ctypes import …")
    found = {}
    for module_name in ("subprocess", "os", "ctypes"):
        seen = found.setdefault(module_name, {})
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == module_name:
                holder = parent[node]
                if isinstance(holder, ast.Attribute) and holder.value is node:
                    seen[holder.attr] = seen.get(holder.attr, 0) + 1
                elif (module_name == "subprocess" and isinstance(holder, ast.Call) and isinstance(holder.func, ast.Name) and holder.func.id == "getattr" and len(holder.args) == 3
                      and holder.args[0] is node and isinstance(holder.args[1], ast.Constant) and holder.args[1].value in ("CREATE_NO_WINDOW", "BELOW_NORMAL_PRIORITY_CLASS")):
                    pass                                              # 창 숨김·우선순위 상수를 상수 이름으로 찾는 두 줄
                else:
                    problems.append(f"{module_name} 를 이름만 따로 씀(줄 {node.lineno})")
    kernel = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            holder = node.value
            if (isinstance(holder, ast.Name) and holder.id == "kernel") or (isinstance(holder, ast.Attribute) and holder.attr == "_kernel" and isinstance(holder.value, ast.Name) and holder.value.id == "self"):
                kernel.add(node.attr)
    found["kernel"] = kernel - {"restype", "argtypes"}
    found["windll"] = [ast.unparse(node.args[0]) for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "WinDLL" and node.args]
    dynamic = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in ("eval", "exec", "compile", "__import__", "globals", "vars", "setattr", "delattr", "getattr", "importlib"):
            dynamic[node.id] = dynamic.get(node.id, 0) + 1
    found["dynamic"] = dynamic
    return problems, found


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

    def test_every_way_the_adapter_reaches_a_process_is_a_closed_set(self):
        """검증 Q QP-2 — 안전 규칙(test_source_rules_outgoing)은 이 파일에 subprocess 를 파일 단위로 열어 두고 부르는 이름 목록만 거른다. 이름을 바꿔 가져오거나(`from subprocess import Popen as P`)
        목록 밖 이름(`getoutput`·`getstatusoutput` 은 셸 명령을 그대로 돌린다)을 쓰는 길은 그 규칙들에 안 걸리므로, 이 파일이 하위 프로세스에 닿는 모든 길을 여기서 닫힌 집합으로 못박는다 —
        새 길을 더하면 이 시험이 빨개져 사람이 그 길이 관문 안(_launch 의 첫 문장)인지 본다. 이름을 조립하는 길(`getattr(subprocess, 'Pop' + 'en')`)은 getattr 자체를 상수 두 개로만 열어 막는다."""
        problems, found = process_reach((ROOT / "src" / "chanceblog_desktop" / "ui" / "ocr_adapter.py").read_text(encoding="utf-8"))
        self.assertEqual(problems, [])
        self.assertEqual(found["subprocess"], {"Popen": 1, "run": 1, "PIPE": 3}, "하위 프로세스 이름은 Popen(_launch 한 곳)·run(taskkill 한 곳)·PIPE 뿐이다")
        self.assertEqual(set(found["os"]), {"name", "path", "pathsep", "environ", "killpg"}, "os 에서 쓰는 것은 이 다섯 이름뿐(system·popen·spawn*·exec*·startfile 은 없다)")
        self.assertEqual(set(found["ctypes"]), {"Structure", "c_int64", "c_size_t", "c_uint64", "c_void_p", "c_int", "WinDLL", "byref", "sizeof"}, "ctypes 로는 Job 개체에 필요한 이름만")
        self.assertEqual(found["kernel"], {"CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject", "CloseHandle"}, "kernel32 에서 부르는 것은 Job 개체 넷뿐(CreateProcess·WinExec 없음)")
        self.assertEqual(found["windll"], ["'kernel32'"])
        self.assertEqual(found["dynamic"], {"getattr": 2}, "동적 이름 찾기는 상수 두 개(창 숨김·우선순위 상수)뿐")

    def test_the_closed_set_rule_sees_a_new_way_in(self):
        """위 규칙의 눈 — 같은 규칙(process_reach)을 가짜 소스에 적용했을 때 getoutput·별칭·조립·이름만 따로 쓰기가 걸리는지(규칙이 아무것도 못 보는 빈 시험이 되지 않게)."""
        def reach(body):
            return process_reach("import subprocess\nimport os\n" + body)
        problems, found = reach("x = subprocess.getoutput('a')")
        self.assertEqual((problems, found["subprocess"]), ([], {"getoutput": 1}), "getoutput 은 이름 집합 비교에서 걸린다")
        self.assertTrue(reach("from subprocess import Popen as P")[0])
        self.assertTrue(reach("import subprocess as sp")[0])
        self.assertTrue(reach("x = getattr(subprocess, 'Pop' + 'en')")[0], "이름을 조립하는 길")
        self.assertEqual(reach("x = getattr(os, 'sys' + 'tem')")[1]["dynamic"], {"getattr": 1})
        self.assertTrue(reach("run = subprocess\nrun.getoutput('a')")[0], "이름만 따로 쓰기")
        self.assertTrue(reach("from os import system")[0])
        self.assertTrue(reach("import _winapi")[0])
        self.assertEqual(reach("os.system('a')")[1]["os"], {"system": 1})
        self.assertEqual(reach("kernel.CreateProcessW(0)")[1]["kernel"], {"CreateProcessW"})

    def test_the_fake_worker_and_the_real_protocol_agree_on_the_shapes(self):
        self.assertEqual(proto.PROTO, 1)
        self.assertTrue(HERE.joinpath("ocr_fake_worker.py").exists())


def docstring_nodes(tree):
    """모듈·함수·클래스의 설명 글 노드(글자 상수 하나) — 소스 속 '낱말 찾기' 가 설명 글을 코드로 세지 않게."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


class TaskkillPathTest(unittest.TestCase):
    """감사 OCR-S1 R3(결정 D-586) — 프로세스 트리를 끄는 `taskkill.exe` 는 이름만이 아니라 윈도 시스템 폴더의 절대 경로로 부른다(이름만 부르면 윈도가 앱 폴더·현재 폴더의 같은 이름 실행 파일을 먼저 찾는다)."""

    SYSTEM32 = chr(92) + "System32" + chr(92) + "taskkill.exe"

    def setUp(self):
        """이 묶음은 환경 값으로 가는 길(윈도에 물을 수 없을 때 — 윈도가 아니거나 호출이 실패)을 본다. 진짜 윈도에서는 윈도가 알려 주는 폴더가 먼저라서(결정 D-593) 그 길을 '물을 수 없음' 으로 고정한다 — 윈도에 물을 수 있을 때의 길은 `TaskkillApiPathTest`·`TaskkillOnWindowsTest`."""
        patcher = mock.patch.object(oa.winroot, "windows_directory", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_path_is_system32_under_the_system_root_found_in_the_same_three_names_in_the_same_order(self):
        for name in ("SystemRoot", "SYSTEMROOT", "windir"):
            with self.subTest(name=name):
                parent = {name: "D:" + chr(92) + "Win"}
                self.assertEqual(oa.system_root(parent), "D:" + chr(92) + "Win")
                self.assertEqual(oa.taskkill_path(parent), "D:" + chr(92) + "Win" + self.SYSTEM32)
        order = {"SystemRoot": "E:" + chr(92) + "A", "SYSTEMROOT": "E:" + chr(92) + "B", "windir": "E:" + chr(92) + "C"}
        self.assertEqual(oa.taskkill_path(order), "E:" + chr(92) + "A" + self.SYSTEM32, "SystemRoot 가 먼저")
        del order["SystemRoot"]
        self.assertEqual(oa.taskkill_path(order), "E:" + chr(92) + "B" + self.SYSTEM32, "그다음 SYSTEMROOT")
        del order["SYSTEMROOT"]
        self.assertEqual(oa.taskkill_path(order), "E:" + chr(92) + "C" + self.SYSTEM32, "마지막이 windir")

    def test_the_environment_builder_and_the_taskkill_path_ask_the_one_same_function_for_the_system_root(self):
        """'build_environment 가 이미 계산하는 값과 같은 출처' — 두 곳이 같은 함수 하나를 부른다(따로 읽는 두 번째 길이 생기면 걸린다)."""
        parent = {"SystemRoot": "D:" + chr(92) + "Win"}
        with mock.patch.object(oa, "system_root", wraps=oa.system_root) as source:
            oa.build_environment(parent, "/tmp/w")
            oa.taskkill_path(parent)
        self.assertEqual([call.args[0] for call in source.call_args_list], [parent, parent])

    def test_a_missing_or_unusable_system_root_gives_the_default_windows_folder_never_a_relative_or_network_path(self):
        self.assertEqual(oa.DEFAULT_SYSTEM_ROOT, "C:" + chr(92) + "Windows")
        default = "C:" + chr(92) + "Windows" + self.SYSTEM32
        unusable = (None, "", " ", ".", "Windows", "Windows" + chr(92) + "x", "..", chr(92) + "Windows", "C:Windows", "C:", "1:" + chr(92) + "Windows", "/usr/bin", chr(92) * 2 + "server" + chr(92) + "share" + chr(92) + "Windows",
                    chr(92) * 2 + "?" + chr(92) + "C:" + chr(92) + "Windows", chr(92) * 2 + "." + chr(92) + "C:", 5, 0, ["C:" + chr(92) + "Windows"], ("C:" + chr(92) + "Windows").encode("ascii"))
        for value in unusable:
            for key in ("SystemRoot", "SYSTEMROOT", "windir"):
                with self.subTest(value=repr(value), key=key):
                    self.assertEqual(oa.taskkill_path({key: value}), default)
        self.assertEqual(oa.taskkill_path({}), default)

    def test_a_forward_slash_root_is_fine_and_no_other_environment_value_reaches_the_result(self):
        self.assertEqual(oa.taskkill_path({"SystemRoot": "C:/Windows"}), "C:/Windows" + self.SYSTEM32)
        for parent in ({"SystemRoot": "evil", "PATH": "C:" + chr(92) + "Evil", "PWD": "x", "TEMP": "y"}, {"windir": ""}, {"PATH": "C:" + chr(92) + "Evil"}, {}):
            with self.subTest(parent=sorted(parent)):
                result = oa.taskkill_path(parent)
                drive, rest = ntpath.splitdrive(result)
                self.assertTrue(len(drive) == 2 and drive[1] == ":" and rest[:1] in (chr(92), "/"), "드라이브 글자로 시작하는 절대 경로다: " + result)
                self.assertEqual(ntpath.basename(result), "taskkill.exe")
                self.assertEqual(ntpath.basename(ntpath.dirname(result)), "System32")
                self.assertNotIn("Evil", result)

    def test_without_an_argument_it_reads_the_real_environment(self):
        root = "D:" + chr(92) + "FromTheEnvironment"
        with mock.patch.object(os, "environ", {"SystemRoot": root}):
            self.assertEqual(oa.taskkill_path(), root + self.SYSTEM32)
        with mock.patch.object(os, "environ", {}):
            self.assertEqual(oa.taskkill_path(), oa.DEFAULT_SYSTEM_ROOT + self.SYSTEM32)

    def test_a_taskkill_file_that_is_missing_is_never_answered_with_a_call_by_bare_name(self):
        process = mock.Mock(pid=5)
        with mock.patch.object(os, "name", "nt"), mock.patch.object(subprocess, "run", side_effect=FileNotFoundError("없다")) as run:
            oa.kill_tree(process)
        self.assertEqual(run.call_count, 1, "실패해도 이름만 부르는 대체 호출을 하지 않는다")
        self.assertTrue(ntpath.isabs(run.call_args[0][0][0]))
        process.kill.assert_called_once()                                  # 작업자 하나는 그래도 끈다(손자는 Job 개체가 끈다)

    def test_the_adapter_source_has_no_bare_taskkill_name_only_the_file_name_inside_the_path_function(self):
        """소스를 읽어 못박는다 — 설명 글 밖의 글자 상수 가운데 `taskkill` 이 든 것은 `taskkill_path` 안의 `taskkill.exe` 하나뿐이고, 프로세스를 끄는 호출의 첫 칸은 `taskkill_path()` 다."""
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "ocr_adapter.py").read_text(encoding="utf-8"))
        skip = docstring_nodes(tree)
        exported = next(node.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets))
        skip |= {id(node) for node in ast.walk(exported)}                    # `__all__` 의 내보내는 이름 목록(`taskkill_path` 라는 이름)은 호출이 아니다
        found = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and "taskkill" in node.value.lower() and id(node) not in skip]
        self.assertEqual(found, ["taskkill.exe"])
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertIn("taskkill.exe", [node.value for node in ast.walk(functions["taskkill_path"]) if isinstance(node, ast.Constant)])
        runs = [node for node in ast.walk(functions["kill_tree"]) if isinstance(node, ast.Call) and ast.unparse(node.func) == "subprocess.run"]
        self.assertEqual([ast.unparse(call.args[0].elts[0]) for call in runs], ["taskkill_path()"])


@unittest.skipUnless(os.name == "nt", "taskkill 은 윈도 전용이다")
class TaskkillOnWindowsTest(unittest.TestCase):
    def test_the_path_points_at_the_real_system_tool_and_that_tool_really_ends_a_process(self):
        path = oa.taskkill_path()
        self.assertTrue(ntpath.isabs(path) and os.path.isfile(path), "이 PC 의 시스템 폴더에 실제로 있는 파일이다")
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"], creationflags=oa.NO_WINDOW)
        self.addCleanup(kill_and_reap, child)
        stand_in = mock.Mock(pid=child.pid)                                # 직접 끄기(kill)는 아무 일도 안 하는 대역 — 끝낸 것이 절대 경로의 taskkill 임을 보인다
        stand_in.kill.side_effect = lambda: None
        stand_in.wait.side_effect = lambda timeout=None: None
        oa.kill_tree(stand_in)
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("절대 경로로 부른 taskkill 이 프로세스를 끝내지 못했다")

    def test_a_hostile_system_root_in_the_environment_no_longer_decides_which_taskkill_runs(self):
        """검증 SQ 참고 4(결정 D-593) — 환경의 SystemRoot 가 `D:` + `evil` 같은 아무 폴더여도 윈도에 직접 물은 값을 쓰므로 진짜 시스템 taskkill 이 프로세스를 끝낸다(옛 코드는 그 폴더의 경로로 불러 실패했다)."""
        real = oa.winroot.windows_directory()
        self.assertTrue(real and os.path.isdir(real), "윈도가 알려 주는 윈도 폴더")
        expected = ntpath.join(real, "System32", "taskkill.exe")
        for hostile in ("D:" + chr(92) + "evil", "C:" + chr(92) + "Windows" + chr(92) + ".." + chr(92) + "Users", chr(92) * 2 + "server" + chr(92) + "share", ""):
            with self.subTest(hostile=hostile), mock.patch.object(os, "environ", {"SystemRoot": hostile}):
                self.assertEqual(oa.taskkill_path(), expected)
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"], creationflags=oa.NO_WINDOW)
        self.addCleanup(kill_and_reap, child)
        stand_in = mock.Mock(pid=child.pid)
        stand_in.kill.side_effect = lambda: None
        stand_in.wait.side_effect = lambda timeout=None: None
        with mock.patch.object(os, "environ", {"SystemRoot": "D:" + chr(92) + "evil"}):
            oa.kill_tree(stand_in)
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("환경 값이 아니라 윈도가 알려 준 폴더의 taskkill 로 불러야 프로세스가 끝난다")


class TaskkillApiPathTest(unittest.TestCase):
    """검증 SQ 참고 4(결정 D-593) — 윈도에서는 환경의 `SystemRoot` 가 아니라 윈도에 직접 물은 폴더(`winroot.windows_directory`)를 믿는다. 환경 값은 그 폴더와 같을 때만 쓰고 아니면 윈도가 알려 준 값이다.
    윈도에 묻는 일을 가짜로 바꿔 어느 운영체제에서나 도는 시험이다(진짜 호출은 `TaskkillOnWindowsTest`·`test_ui_winroot`)."""

    REAL = "E:" + chr(92) + "RealWin"
    SYSTEM32 = chr(92) + "System32" + chr(92) + "taskkill.exe"

    def setUp(self):
        patcher = mock.patch.object(oa.winroot, "windows_directory", return_value=self.REAL)
        self.ask = patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_environment_value_that_is_not_the_folder_windows_reports_is_ignored_whatever_its_shape(self):
        """SQ 탐침 r3 구역 D 의 입력들(`D:` + `evil`·`C:` + `Windows` + `..` + `Users`)과 그 밖의 쓸 수 없는 값 — 모두 윈도가 알려 준 값."""
        b = chr(92)
        hostile = ("D:" + b + "evil", "C:" + b + "Windows" + b + ".." + b + "Users", "E:" + b + "RealWin" + b + ".." + b + "Users", "E:" + b + "RealWinX", "E:" + b + "Other", b * 2 + "server" + b + "share" + b + "RealWin",
                   b * 2 + "?" + b + "E:" + b + "RealWin", "C:Windows", "E:RealWin", "RealWin", "..", ".", "", " ", None, 5, 0, ["E:" + b + "RealWin"], ("E:" + b + "RealWin").encode("ascii"))
        for value in hostile:
            for key in ("SystemRoot", "SYSTEMROOT", "windir"):
                with self.subTest(value=repr(value), key=key):
                    self.assertEqual(oa.taskkill_path({key: value}), self.REAL + self.SYSTEM32)
        self.assertEqual(oa.taskkill_path({}), self.REAL + self.SYSTEM32, "환경에 값이 없어도")

    def test_an_environment_value_that_names_the_same_folder_is_used_in_the_spelling_it_came_in(self):
        b = chr(92)
        for value in ("E:" + b + "RealWin", "e:" + b + "realwin", "E:/RealWin", "E:" + b + "RealWin" + b, "E:/RealWin/", "E:" + b + "RealWin" + b + "x" + b + ".."):
            with self.subTest(value=value):
                result = oa.taskkill_path({"SystemRoot": value})
                self.assertTrue(result.startswith(value), "같은 폴더면 환경 값 그대로 쓴다")
                self.assertEqual(ntpath.normcase(ntpath.normpath(result)), ntpath.normcase(self.REAL + self.SYSTEM32))

    def test_the_folder_windows_reports_wins_over_the_other_two_names_too(self):
        parent = {"SystemRoot": "D:" + chr(92) + "A", "SYSTEMROOT": "D:" + chr(92) + "B", "windir": self.REAL}
        self.assertEqual(oa.taskkill_path(parent), self.REAL + self.SYSTEM32, "SystemRoot 가 다르면 windir 가 맞아도 윈도가 알려 준 값을 쓴다 — 어느 쪽이든 결과는 그 값")

    def test_the_tree_kill_runs_the_path_under_the_folder_windows_reports_even_with_a_hostile_environment(self):
        process = mock.Mock(pid=77)
        with mock.patch.object(os, "name", "nt"), mock.patch.object(os, "environ", {"SystemRoot": "D:" + chr(92) + "evil"}), mock.patch.object(subprocess, "run") as run:
            oa.kill_tree(process)
        self.assertEqual(run.call_args[0][0], [self.REAL + self.SYSTEM32, "/PID", "77", "/T", "/F"])
        self.assertEqual(run.call_count, 1)

    def test_windows_is_asked_once_per_call_and_only_through_the_one_helper(self):
        oa.taskkill_path({"SystemRoot": self.REAL})
        self.assertEqual(self.ask.call_count, 1)
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "ocr_adapter.py").read_text(encoding="utf-8"))
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call) and "windows_directory" in ast.unparse(node.func)]
        self.assertEqual(calls, ["winroot.windows_directory"], "어댑터가 윈도 폴더를 묻는 곳은 이 도우미 한 줄뿐이다(ctypes 는 어댑터에 없다)")


class JobRuleMockedTest(unittest.TestCase):
    """감사 OCR-S1 R2(결정 D-585) — 윈도에서 Job 개체에 못 넣으면(메모리 한도도 '앱이 죽으면 작업자도 끝남' 도 없다) 띄우지 않는다. 윈도 갈래를 `os.name` 만 좁게 흉내 내어 어느 운영체제에서나 본다(진짜 Job 개체는 `JobObjectTest`·`JobRuleOnWindowsTest`)."""

    def setUp(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        self.process = mock.Mock(pid=5, stdout=io.BytesIO(b""), stderr=io.BytesIO(b""), stdin=io.BytesIO())
        self.adapter = oa.OcrAdapter([WORKER_PATH], verify=None, work_dir=tempfile.gettempdir())
        self.addCleanup(self.adapter._remove_temp)

    def launch(self, system, job):
        made = []
        real = tempfile.mkdtemp

        def mkdtemp(*args, **kwargs):
            made.append(real(*args, **kwargs))
            return made[-1]
        with mock.patch.object(os, "name", system), mock.patch.object(oa, "JobObject", return_value=job), mock.patch.object(subprocess, "Popen", return_value=self.process), \
                mock.patch.object(tempfile, "mkdtemp", mkdtemp), mock.patch.object(oa, "kill_tree") as kill:
            try:
                self.adapter._launch()
                raised = None
            except oa.AdapterError as error:
                raised = error
        return raised, kill, made

    def test_on_windows_a_job_that_cannot_take_the_worker_ends_the_launch_as_blocked_and_cleans_up_at_once(self):
        job = mock.Mock()
        job.assign.return_value = False
        queue_before = self.adapter.lines
        raised, kill, made = self.launch("nt", job)
        self.assertIsNotNone(raised, "못 넣었는데 조용히 뜨면 안 된다")
        self.assertEqual(raised.name, "blocked")
        kill.assert_called_once_with(self.process)                          # 방금 띄운 프로세스 트리를 끝낸다
        job.close.assert_called()                                           # Job 개체도 닫는다
        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]), "임시 폴더를 치운다")
        self.assertTrue(self.process.stdin.closed and self.process.stdout.closed and self.process.stderr.closed, "파이프 핸들도 닫는다")
        self.assertEqual((self.adapter.process, self.adapter.job, self.adapter.temp_dir, self.adapter.job_assigned), (None, None, None, False))
        self.assertIs(self.adapter.lines, queue_before, "읽기 스레드를 시작하지도 않았다")

    def test_the_same_failure_through_a_read_is_reported_to_the_caller_as_blocked_without_asking_the_worker_anything(self):
        job = mock.Mock()
        job.assign.return_value = False
        self.process.stdin = mock.Mock()
        with mock.patch.object(os, "name", "nt"), mock.patch.object(oa, "JobObject", return_value=job), mock.patch.object(subprocess, "Popen", return_value=self.process), mock.patch.object(oa, "kill_tree"):
            outcome = self.adapter.read_rgb(16, 16, PIXELS, "960")
        self.assertEqual((outcome.error, outcome.lines), ("blocked", ()))
        self.process.stdin.write.assert_not_called()                        # 요청 한 바이트도 보내지 않았다 — 사진 픽셀이 한도 없는 작업자에게 가지 않는다

    def test_a_job_object_that_could_not_even_be_made_is_the_same_failure(self):
        job = mock.Mock(ok=False)
        job.assign.return_value = False
        raised, kill, _made = self.launch("nt", job)
        self.assertEqual(getattr(raised, "name", None), "blocked")
        kill.assert_called_once_with(self.process)

    def test_on_windows_a_job_that_took_the_worker_launches_normally(self):
        """대조 — 넣었으면 그대로 뜬다(위 시험의 빨강이 다른 원인이 아님)."""
        job = mock.Mock()
        job.assign.return_value = True
        raised, kill, made = self.launch("nt", job)
        self.assertIsNone(raised)
        kill.assert_not_called()
        self.assertEqual((self.adapter.process, self.adapter.job_assigned), (self.process, True))
        self.assertTrue(os.path.isdir(made[0]))

    def test_off_windows_there_is_no_job_object_so_the_rule_does_not_apply(self):
        """윈도가 아닌 곳(앱 CI 의 리눅스 칸)에는 Job 개체가 없다 — 작업자는 그대로 뜨고 `job_assigned` 만 거짓이다."""
        job = mock.Mock()
        job.assign.return_value = False
        raised, kill, made = self.launch("posix", job)
        self.assertIsNone(raised)
        kill.assert_not_called()
        self.assertEqual((self.adapter.process, self.adapter.job_assigned), (self.process, False))
        self.assertTrue(os.path.isdir(made[0]))


@unittest.skipUnless(os.name == "nt", "Job 개체는 윈도 전용이다")
class JobRuleOnWindowsTest(AdapterCase):
    """감사 OCR-S1 R2(결정 D-585) — 진짜 작업자 프로세스(가짜 작업자)로: Job 개체에 못 넣으면 띄운 프로세스가 끝나 있고 임시 폴더가 없고 요청은 한 바이트도 안 갔다."""

    def run_blocked(self, make_job_fail):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        dump = Path(folder.name, "request.bin")                             # 작업자가 요청을 받았다면 이 파일이 생긴다
        adapter = self.make("--dump", str(dump))
        created, made = [], []
        real_popen, real_mkdtemp = subprocess.Popen, tempfile.mkdtemp

        def popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            if args and list(args[0]) == adapter.command:                    # 작업자만 센다(트리를 끄는 taskkill 도 같은 Popen 을 지난다)
                created.append(process)
                self.addCleanup(hard_kill, process)
            return process

        def mkdtemp(*args, **kwargs):
            made.append(real_mkdtemp(*args, **kwargs))
            return made[-1]
        with mock.patch.object(subprocess, "Popen", popen), mock.patch.object(tempfile, "mkdtemp", mkdtemp), make_job_fail():
            outcome = adapter.read_rgb(16, 16, PIXELS, "960")
        return adapter, outcome, created, made, dump.exists()

    def check_blocked(self, adapter, outcome, created, made, sent):
        self.assertEqual(outcome.error, "blocked")
        self.assertEqual((len(created), len(made)), (1, 1))
        self.assertTrue(wait_dead(created[0].pid), "방금 띄운 작업자 프로세스가 남아 있다")
        self.assertFalse(os.path.exists(made[0]), "임시 폴더가 남아 있다")
        self.assertFalse(sent, "작업자는 요청을 받지 못했다")
        self.assertEqual((adapter.process, adapter.job, adapter.temp_dir, adapter.job_assigned, adapter.launches), (None, None, None, False, 1))

    def test_a_job_that_refuses_the_assignment_leaves_nothing_running_and_no_request_sent(self):
        self.check_blocked(*self.run_blocked(lambda: mock.patch.object(oa.JobObject, "assign", autospec=True, return_value=False)))

    def test_a_job_object_that_cannot_be_made_leaves_nothing_running_and_no_request_sent(self):
        def broken_init(self_, memory_limit=oa.MEMORY_LIMIT_BYTES):
            self_.handle, self_.ok = None, False
        self.check_blocked(*self.run_blocked(lambda: mock.patch.object(oa.JobObject, "__init__", broken_init)))

    def test_after_a_blocked_launch_the_next_read_starts_a_fresh_worker_in_a_job(self):
        adapter, outcome, created, made, sent = self.run_blocked(lambda: mock.patch.object(oa.JobObject, "assign", autospec=True, return_value=False))
        self.assertEqual(outcome.error, "blocked")
        again = self.read(adapter)
        self.assertEqual((again.error, adapter.launches, adapter.job_assigned), ("", 2, True))


if __name__ == "__main__":
    unittest.main()
