"""글자 읽기 작업자를 띄우는 **유일한 곳**(결정 D-512, 운영자 확인 026 ②·028 ②, 설계서 3-3·3-5·3-6·3-8·3-9) — 이 PC 안에서만 계산하는 별도 프로세스를 표준 입출력으로 부린다.
바깥에 쓰는 곳이 아니다(소켓·인터넷 코드 없음). 이 파일이 하위 프로세스를 띄우는 길은 `_launch` 하나뿐이고 그 첫 문장이 `capabilities.require_local_ocr` 라서 `LOCAL_OCR`(기본 False)가 꺼져 있으면 한 번도 안 뜬다.

작업자를 지키는 겹(설계 3-6 의 1겹과 3-3):
  · 인자는 고정이고 셸을 쓰지 않는다(`shell` 없음). 윈도에서는 창이 안 뜨게(`CREATE_NO_WINDOW`) 낮은 우선순위(`BELOW_NORMAL`)로 띄우고, Job 개체(`KILL_ON_JOB_CLOSE` + 프로세스 메모리 1GB)에 넣어 앱이 죽어도 작업자가 남지 않게 한다.
  · 환경 변수는 새로 짠다(`build_environment`) — 부모의 것을 그대로 넘기지 않는다: 이름에 PROXY 가 든 것은 모두 닫힌 로컬 포트로, NO_PROXY 는 없애고(우회 못 하게), `HF_HUB_OFFLINE`·`DO_NOT_TRACK`·`ORT_DISABLE_TELEMETRY`·`OPENCV_OPENCL_RUNTIME`·`PYTHONDONTWRITEBYTECODE`·`PYTHONUTF8` 을 정하고,
    `TEMP`·`TMP` 는 작업자 전용 빈 폴더(끝나면 지운다), `PATH` 는 시스템 폴더만 둔다. 그 밖의 부모 변수(비밀이 든 것 포함)는 하나도 넘기지 않는다.
  · 요청은 `ocr_protocol.encode_request` 가 만든 머리 한 줄 + 픽셀뿐이다 — 사진 경로·파일 이름·사진 번호·종류·메모·`Exif` 가 들어갈 자리가 없다(이 파일은 경로를 받지도 않는다).
  · 응답은 모두 데이터로만 본다 — 한 줄 256KB·JSON 이 아니면·알려진 칸이 아니면·형식·NaN·줄 200개·줄당 400자·요청 번호가 다르면 응답 전체를 버리고 작업자를 끝낸 뒤 `proto` 로 알린다. 좌표 칸은 버리고 글만 넘긴다.
  · 표준 오류는 비우기만 하고 내용은 어디에도 두지 않는다. 시간 초과(준비 150초·사진 90초)와 취소 뒤 3초 안에 못 끝낸 작업자는 프로세스 트리를 끈다. 유휴 5분이면 끝낸다. 시작 전에 추가 도구 파일 해시를 확인한다(`verify`).
  · 작업자가 네트워크 시도 차단을 보고하면(`net_blocked`) 즉시 끝내고 알린다(컨트롤러가 이번 실행 동안 끈다).
이 어댑터는 이미 준비된 RGB 바이트(`read_rgb`)를 받는다 — 사진 읽기·줄이기(Qt)는 화면 쪽(`prepare`)이 한다.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time

from .. import capabilities
from ..errors import AppError
from .core import ocr_protocol as proto
from .core import photo_ocr_view as pov

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
PROXY_TRAP = "127.0.0.1:9"                       # 닫힌 로컬 포트 — 어떤 라이브러리가 프록시를 따라가도 연결이 거절된다
FIXED_ENVIRONMENT = {"HF_HUB_OFFLINE": "1", "DO_NOT_TRACK": "1", "ORT_DISABLE_TELEMETRY": "1", "OPENCV_OPENCL_RUNTIME": "disabled", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
KEEP_WINDOWS = ("SystemRoot", "SYSTEMROOT", "windir", "WINDIR", "ComSpec", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS")
_EOF = object()
_OVERSIZE = object()


def build_environment(parent, temp_dir, work_dir=None):
    """작업자에게 줄 환경 변수 — 부모 것은 아래 몇 가지(윈도 시스템 변수)만 옮기고 나머지는 버린다(순수 함수: 파일을 만지지 않는다)."""
    env = {name: parent[name] for name in KEEP_WINDOWS if name in parent}
    for name in parent:
        if "PROXY" in name.upper():
            env[name] = PROXY_TRAP
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[name] = PROXY_TRAP
    env.pop("NO_PROXY", None)
    env.pop("no_proxy", None)
    env.update(FIXED_ENVIRONMENT)
    env["TEMP"] = env["TMP"] = str(temp_dir)
    root = parent.get("SystemRoot") or parent.get("SYSTEMROOT") or parent.get("windir")
    if os.name == "nt" and root:
        env["PATH"] = os.pathsep.join([os.path.join(root, "System32"), root])
    else:
        env["PATH"] = os.pathsep.join(["/usr/bin", "/bin"])
    if work_dir:
        env["PWD"] = str(work_dir)
    return env


class AdapterError(Exception):
    """작업자를 띄우거나 읽다가 난 일 — `name` 은 `photo_ocr_view.ERROR_CODE` 의 이름이다(글·경로 없음)."""

    def __init__(self, name):
        super().__init__(name)
        self.name = name


class JobObject:
    """윈도 Job 개체 — `KILL_ON_JOB_CLOSE`(앱이 죽으면 작업자도 끝난다)와 프로세스 메모리 한도. 윈도가 아니거나 만들지 못하면 `ok` 가 거짓이고 아무것도 하지 않는다(트리 종료와 유휴 종료가 따로 있다)."""

    def __init__(self, memory_limit=MEMORY_LIMIT_BYTES):
        self.handle, self.ok = None, False
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

            class Counters(ctypes.Structure):
                _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class Extended(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Counters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.restype = ctypes.c_void_p
            kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.CreateJobObjectW(None, None)
            if not handle:
                return
            info = Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000 | 0x100                  # KILL_ON_JOB_CLOSE | PROCESS_MEMORY
            info.ProcessMemoryLimit = int(memory_limit)
            if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                kernel.CloseHandle(handle)
                return
            self._kernel, self.handle, self.ok = kernel, handle, True
        except Exception:
            self.handle, self.ok = None, False

    def assign(self, process):
        if not self.ok:
            return False
        try:
            return bool(self._kernel.AssignProcessToJobObject(self.handle, int(process._handle)))
        except Exception:
            return False

    def close(self):
        if self.ok and self.handle:
            try:
                self._kernel.CloseHandle(self.handle)
            except Exception:
                pass
        self.handle, self.ok = None, False


def kill_tree(process):
    """작업자와 그 자식(손자) 프로세스까지 끈다 — 윈도는 `taskkill /T /F`, 그 밖은 프로세스 그룹. 어떤 오류도 밖으로 내지 않는다."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15, creationflags=NO_WINDOW)
        else:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=5)
    except Exception:
        pass


class OcrAdapter(pov.OcrProvider):
    """글자 읽기 작업자 공급자 — 한 번에 한 요청(`read_rgb` 는 부르는 쪽이 한 스레드에서 차례로 부른다. `cancel`·`shutdown` 은 다른 스레드에서 불러도 된다)."""

    def __init__(self, command, *, prepare=None, verify=None, clock=time.monotonic, prepare_timeout=pov.PREPARE_TIMEOUT_S, read_timeout=pov.READ_TIMEOUT_S, cancel_wait=pov.CANCEL_WAIT_S,
                 idle_exit=pov.IDLE_EXIT_S, work_dir=None, parent_env=None):
        self.command, self.prepare, self.verify, self.clock = list(command), prepare, verify, clock
        self.prepare_timeout, self.read_timeout, self.cancel_wait, self.idle_exit = prepare_timeout, read_timeout, cancel_wait, idle_exit
        self.work_dir = work_dir
        self.parent_env = parent_env if parent_env is not None else dict(os.environ)
        self.process, self.job, self.temp_dir = None, None, None
        self.lines = queue.Queue()
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()
        self.next_id = 0
        self.last_activity = None
        self.launches = 0

    # ---- 공급자 모양 ----
    def available(self):
        return capabilities.local_ocr_enabled()

    def read(self, job):
        """컨트롤러의 요청(`OcrJob`) 하나를 읽는다 — 화면 쪽 `prepare(job)` 가 사진을 줄여 `(너비, 높이, RGB 바이트)` 를 준다(사진 경로는 이 어댑터에 오지 않는다)."""
        if self.prepare is None:
            return pov.OcrOutcome(error="decode")
        try:
            width, height, pixels = self.prepare(job)
        except AppError as error:
            return pov.OcrOutcome(error="too_big" if error.code == "OCR_TOO_BIG" else "decode")
        except Exception:
            return pov.OcrOutcome(error="decode")
        return self.read_rgb(width, height, pixels, job.size)

    # ---- 띄우기 ----
    def _launch(self):
        capabilities.require_local_ocr("글자 읽기 작업자 시작")
        if self.verify is not None:
            problem = self.verify()
            if problem:
                raise AdapterError("addon_invalid")
        self.temp_dir = tempfile.mkdtemp(prefix="cbd-ocr-")
        env = build_environment(self.parent_env, self.temp_dir, self.work_dir)
        options = {"creationflags": NO_WINDOW | BELOW_NORMAL} if os.name == "nt" else {"start_new_session": True}
        try:
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self.work_dir, shell=False, **options)
        except OSError:
            self._remove_temp()
            raise AdapterError("blocked") from None
        self.process, self.launches = process, self.launches + 1
        self.job = JobObject()
        self.job.assign(process)
        self.lines = queue.Queue()
        threading.Thread(target=self._pump_stdout, args=(process, self.lines), daemon=True).start()
        threading.Thread(target=self._drain_stderr, args=(process,), daemon=True).start()

    @staticmethod
    def _pump_stdout(process, sink):
        """표준 출력을 한 줄씩 모은다 — 한 줄이 한도(256KB)를 넘으면 그 사실만 알리고 읽기를 멈춘다(나머지는 버린다)."""
        try:
            while True:
                line = process.stdout.readline(proto.MAX_RESPONSE_BYTES + 1)
                if not line:
                    break
                if len(line) > proto.MAX_RESPONSE_BYTES:
                    sink.put(_OVERSIZE)
                    break
                sink.put(line)
        except Exception:
            pass
        sink.put(_EOF)

    @staticmethod
    def _drain_stderr(process):
        """표준 오류는 비우기만 한다 — 내용은 어디에도 두지 않는다(경로·글이 들 수 있다)."""
        try:
            while process.stderr.read(65536):
                pass
        except Exception:
            pass

    def _next(self, deadline):
        """다음 응답 한 줄 -> 바이트 또는 `_EOF`·`_OVERSIZE`·None(시간이 다 됨). 취소 표시가 있으면 `cancel_wait` 안에서만 기다린다."""
        cancel_deadline = None
        while True:
            if self.cancel_event.is_set() and cancel_deadline is None:
                cancel_deadline = self.clock() + self.cancel_wait
            limit = deadline if cancel_deadline is None else min(deadline, cancel_deadline)
            remaining = limit - self.clock()
            if remaining <= 0:
                return None
            try:
                return self.lines.get(timeout=min(0.05, remaining))
            except queue.Empty:
                if self.process is not None and self.process.poll() is not None and self.lines.empty():
                    return _EOF

    def _wait_ready(self):
        got = self._next(self.clock() + self.prepare_timeout)
        if got is None:
            raise AdapterError("timeout")
        if got is _EOF:
            raise AdapterError("died")
        if got is _OVERSIZE:
            raise AdapterError("proto")
        try:
            proto.validate_ready(proto.loads_strict(got))
        except (proto.ProtocolError, ValueError):
            raise AdapterError("proto") from None

    def _ensure_started(self):
        if self.process is not None and self.process.poll() is None and self.process.stdin is not None:
            return
        self._stop(kill=True)
        self._launch()
        self._wait_ready()

    # ---- 읽기 ----
    def read_rgb(self, width, height, pixels, size_name=pov.SIZE_NORMAL):
        """이미 준비된 RGB 바이트(w*h*3)로 한 장을 읽는다 -> `OcrOutcome`(줄들 또는 오류 이름). 작업자 쪽 어떤 이상도 예외로 내지 않고 오류 이름으로 알린다(작업자는 정리된다)."""
        with self.lock:
            try:
                return self._read_locked(width, height, pixels, size_name)
            except AdapterError as error:
                self._stop(kill=True)
                return pov.OcrOutcome(error=error.name)
            except AppError as error:
                self._stop(kill=True)
                return pov.OcrOutcome(error="unavailable" if error.code == "OCR_UNAVAILABLE" else "engine")

    def _read_locked(self, width, height, pixels, size_name):
        self.cancel_event.clear()
        if size_name not in pov.SIZES:
            raise AdapterError("decode")
        try:
            self._ensure_started()
        except AdapterError:
            self.cancel_event.clear()
            raise
        if not self.lines.empty():
            raise AdapterError("proto")                              # 요청하지 않은 줄이 쌓여 있다 — 약속 위반
        self.next_id += 1
        req_id = self.next_id
        try:
            data = proto.encode_request(req_id, width, height, pixels, size_name)
        except (ValueError, TypeError):
            raise AdapterError("decode") from None
        try:
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise AdapterError("died") from None
        got = self._next(self.clock() + self.read_timeout)
        self.last_activity = self.clock()
        if got is None:
            raise AdapterError("cancelled" if self.cancel_event.is_set() else "timeout")
        if got is _EOF:
            raise AdapterError("died")
        if got is _OVERSIZE:
            raise AdapterError("proto")
        if self.cancel_event.is_set():
            return pov.OcrOutcome(error="cancelled")                 # 취소했는데 끝났다 — 결과는 쓰지 않는다(작업자는 쉰다)
        try:
            message = proto.validate_result(proto.loads_strict(got), req_id)
        except (proto.ProtocolError, ValueError):
            raise AdapterError("proto") from None
        if message["t"] == "error":
            code = message["code"]
            if code in ("net_blocked", "proto"):
                raise AdapterError(code)
            return pov.OcrOutcome(error=code)
        if message["net_attempts"] > 0:
            raise AdapterError("net_blocked")
        return pov.OcrOutcome(tuple({"text": line["text"]} for line in message["lines"]))

    # ---- 멈추기 ----
    def cancel(self, token=None):
        """진행 중인 읽기를 취소한다 — 읽는 쪽이 `cancel_wait` 안에서 결과를 버리고, 못 끝나면 프로세스 트리를 끈다(다른 스레드에서 불러도 된다)."""
        self.cancel_event.set()

    def maybe_idle_exit(self):
        """마지막 읽기 뒤 `idle_exit` 초를 쉬었으면 작업자를 끝낸다 -> 끝냈으면 True(화면 쪽 타이머가 가끔 부른다)."""
        with self.lock:
            if self.process is not None and self.last_activity is not None and self.clock() - self.last_activity >= self.idle_exit:
                self._stop(kill=False)
                return True
            return False

    def _remove_temp(self):
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir = None

    def _stop(self, kill):
        """작업자를 끝내고 흔적을 지운다 — 여러 번 불러도 같다. `kill` 이 거짓이면 먼저 정중하게(bye) 부탁한다."""
        process = self.process
        self.process = None
        if process is not None:
            if not kill:
                try:
                    process.stdin.write(proto.dumps_line({"t": "bye"}))
                    process.stdin.flush()
                    process.wait(timeout=2)
                except Exception:
                    pass
            if process.poll() is None or kill:
                kill_tree(process)
            for handle in (process.stdin, process.stdout, process.stderr):
                try:
                    handle.close()
                except Exception:
                    pass
        if self.job is not None:
            self.job.close()
            self.job = None
        self._remove_temp()
        self.last_activity = None

    def shutdown(self):
        """앱 종료 — 작업자를 끝낸다(못 끝내면 트리를 끄고, Job 개체가 마지막 안전망). 여러 번 불러도 같다."""
        self.cancel_event.set()
        with self.lock:
            self._stop(kill=False)
        self.cancel_event.clear()


__all__ = ["AdapterError", "JobObject", "MEMORY_LIMIT_BYTES", "OcrAdapter", "PROXY_TRAP", "build_environment", "kill_tree"]
