"""글자 읽기 작업자를 띄우는 **유일한 곳**(결정 D-512, 운영자 확인 026 ②·028 ②, 설계서 3-3·3-5·3-6·3-8·3-9) — 이 PC 안에서만 계산하는 별도 프로세스를 표준 입출력으로 부린다.
바깥에 쓰는 곳이 아니다(소켓·인터넷 코드 없음). 이 파일이 하위 프로세스를 띄우는 길은 `_launch` 하나뿐이고 그 첫 문장이 `capabilities.require_local_ocr` 라서 `LOCAL_OCR`(기본 False)가 꺼져 있으면 한 번도 안 뜬다.

작업자를 지키는 겹(설계 3-6 의 1겹과 3-3):
  · 인자는 고정이고 셸을 쓰지 않는다(`shell` 없음). 윈도에서는 창이 안 뜨게(`CREATE_NO_WINDOW`) 낮은 우선순위(`BELOW_NORMAL`)로 띄우고, Job 개체(`KILL_ON_JOB_CLOSE` + 프로세스 메모리 1GB)에 넣어 앱이 죽어도 작업자가 남지 않게 한다.
    윈도에서 Job 개체를 만들지 못하거나 작업자를 넣지 못하면(메모리 한도도 '앱이 죽으면 따라 끝남' 도 없는 채로 돌게 되므로) 방금 띄운 트리를 끝내고 임시 폴더를 지운 뒤 `blocked` 로 끝낸다 — 윈도가 아닌 곳은 Job 개체가 없어 이 규칙이 없다(결정 D-585). 띄우자마자 끝난 작업자도 이미 끝난 프로세스는 Job 개체에 넣을 수 없어 이 길로 `blocked` 가 된다(예전에는 `died`).
    프로세스 트리를 끌 때의 `taskkill` 도 이름만 부르지 않고 윈도 시스템 폴더의 절대 경로로 부른다(`taskkill_path` — 앱 폴더나 현재 폴더에 놓은 같은 이름의 실행 파일이 대신 실행되지 않게, 결정 D-586. 윈도에서는 환경 변수가 아니라 윈도에 직접 물은 폴더를 믿는다 — 결정 D-593).
  · 환경 변수는 새로 짠다(`build_environment`) — 부모의 것을 그대로 넘기지 않는다: 이름에 PROXY 가 든 것은 모두 닫힌 로컬 포트로, NO_PROXY 는 없애고(우회 못 하게), `HF_HUB_OFFLINE`·`DO_NOT_TRACK`·`ORT_DISABLE_TELEMETRY`·`OPENCV_OPENCL_RUNTIME`·`PYTHONDONTWRITEBYTECODE`·`PYTHONUTF8` 을 정하고,
    `TEMP`·`TMP` 는 작업자 전용 빈 폴더(끝나면 지운다), `PATH` 는 시스템 폴더만 둔다. 그 밖의 부모 변수(비밀이 든 것 포함)는 하나도 넘기지 않는다.
  · 요청은 `ocr_protocol.encode_request` 가 만든 머리 한 줄 + 픽셀뿐이다 — 사진 경로·파일 이름·사진 번호·종류·메모·`Exif` 가 들어갈 자리가 없다(이 파일은 경로를 받지도 않는다).
  · 응답은 모두 데이터로만 본다 — 한 줄 256KB·JSON 이 아니면·알려진 칸이 아니면·형식·NaN·줄 200개·줄당 400자·요청 번호가 다르면 응답 전체를 버리고 작업자를 끝낸 뒤 `proto` 로 알린다. 좌표 칸은 버리고 글만 넘긴다.
  · 표준 오류는 비우기만 하고 내용은 어디에도 두지 않는다. 시간 초과(준비 150초·사진 90초)와 취소 뒤 3초 안에 못 끝낸 작업자는 프로세스 트리를 끈다. 유휴 5분이면 끝낸다. 시작 전에 추가 도구 파일 해시를 확인한다(`verify`).
  · 작업자가 네트워크 시도 차단을 보고하면(`net_blocked`) 즉시 끝내고 알린다(컨트롤러가 이번 실행 동안 끈다).
이 어댑터는 이미 준비된 RGB 바이트(`read_rgb`)를 받는다 — 사진 읽기·줄이기(Qt)는 화면 쪽(`prepare`)이 한다.
"""
from __future__ import annotations

import ntpath
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time

from .. import capabilities
from ..errors import AppError
from . import winroot
from .core import ocr_protocol as proto
from .core import photo_ocr_view as pov

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
LINE_QUEUE_MAX = 16                              # 작업자 표준 출력 줄 대기열의 한도 — 약속대로면 한 번에 한두 줄(응답 한 줄·끝 표지)뿐이다. 요청하지 않은 줄을 쏟아내도 앱 메모리가 늘지 않게 가득 차면 읽기를 멈춘다(작업자는 쓰다 막힌다 — 검증 S SP-4)
CLOSE_WAIT = 3.0                                 # 정리 때 파이프 핸들 닫기를 기다리는 시간(초) — 손자가 파이프를 쥐고 있어 닫기가 안 풀려도 여기서 매달리지 않는다(검증 S SP-3)
PROXY_TRAP = "127.0.0.1:9"                       # 닫힌 로컬 포트 — 어떤 라이브러리가 프록시를 따라가도 연결이 거절된다
FIXED_ENVIRONMENT = {"HF_HUB_OFFLINE": "1", "DO_NOT_TRACK": "1", "ORT_DISABLE_TELEMETRY": "1", "OPENCV_OPENCL_RUNTIME": "disabled", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
KEEP_WINDOWS = ("SystemRoot", "SYSTEMROOT", "windir", "WINDIR", "ComSpec", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS")
DEFAULT_SYSTEM_ROOT = "C:\\Windows"               # 환경 변수에 시스템 폴더가 없거나 쓸 수 없는 값일 때만 쓰는 윈도 기본 폴더(`taskkill_path`)
_EOF = object()
_OVERSIZE = object()


def system_root(parent):
    """윈도 시스템 폴더 값 — 부모 환경에서 `SystemRoot`·`SYSTEMROOT`·`windir` 순으로 읽는다(없으면 None). `build_environment` 가 PATH 를 짤 때와 `taskkill_path` 가 같은 출처를 읽게 한 곳에 둔다."""
    return parent.get("SystemRoot") or parent.get("SYSTEMROOT") or parent.get("windir")


def trusted_system_root(root):
    """환경에서 읽은 시스템 폴더 값(`root`, `system_root` 의 결과)을 **믿고 쓸 폴더**로 바꾼다 — `taskkill_path` 와 작업자의 PATH(`build_environment`)가 같은 이 함수 하나를 쓴다(감사 후속, 결정 D-600).
    윈도에서는 환경 변수가 아니라 윈도에 직접 물은 값(`winroot.windows_directory`)을 믿는다: 환경 값은 그 값과 같은 폴더일 때만 쓰고(쓴 철자 그대로) 다르면(`D:\\evil` 처럼 드라이브만 바뀐 값·`..` 를 낀 값·네트워크 위치) 윈도가 알려 준 값을 쓴다.
    윈도에 물을 수 없으면(윈도가 아니거나 호출이 실패) 예전 그대로다: 환경 값이 드라이브 글자로 시작하는 절대 경로가 아니면 윈도 기본 폴더(`DEFAULT_SYSTEM_ROOT`)이고 맞으면 그 값이다."""
    real = winroot.windows_directory()
    if real is not None:
        return root if isinstance(root, str) and winroot.same_folder(root, real) else real
    return root if winroot.is_drive_absolute(root) else DEFAULT_SYSTEM_ROOT


def taskkill_path(parent=None):
    """`taskkill.exe` 의 **절대 경로** — 시스템 폴더 아래 `System32` 의 것이다. 이름만 부르면 윈도가 앱이 불러온 폴더·현재 폴더에서 같은 이름의 실행 파일을 먼저 찾아 시간 초과·취소 때마다 그것이 실행될 수 있다(감사 OCR-S1 R3).
    **윈도에서는** 환경 변수(`system_root`)가 아니라 윈도에 직접 물은 값(`winroot.windows_directory`)을 믿는다 — 환경 값은 그 값과 같은 폴더일 때만 쓰고 다르면(`D:\\evil` 처럼 드라이브 글자 절대 경로이기만 한 아무 폴더·`..` 로 돌려 가리킨 폴더 포함) 윈도가 알려 준 값을 쓴다(결정 D-593).
    윈도에 물을 수 없으면(윈도가 아니거나 호출이 실패) 예전 그대로다: 환경 값이 드라이브 글자로 시작하는 절대 경로가 아니면(상대 경로·네트워크 위치·장치 경로) 윈도 기본 폴더를 쓴다. 그 자리에 파일이 없으면 부르기가 실패할 뿐이고 이름만 부르는 대체 호출은 없다(`kill_tree` 는 실패해도 작업자 하나는 끈다 — 손자는 Job 개체가 끈다)."""
    root = trusted_system_root(system_root(os.environ if parent is None else parent))
    return ntpath.join(root, "System32", "taskkill.exe")


def build_environment(parent, temp_dir, work_dir=None):
    """작업자에게 줄 환경 변수 — 부모 것은 아래 몇 가지(윈도 시스템 변수)만 옮기고 나머지는 버린다(파일을 만지지 않는다). PATH 의 시스템 폴더는 환경 값이 아니라 윈도에 직접 물은 값을 믿는다(`trusted_system_root` — 읽기 한 번뿐)."""
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
    root = system_root(parent)
    if os.name == "nt" and root:
        root = trusted_system_root(root)                                 # 환경 값이 아니라 윈도에 직접 물은 폴더로(`taskkill_path` 와 같은 함수 — 환경이 다른 폴더를 가리켜도 PATH 는 진짜 윈도 폴더 아래뿐)
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
    """작업자와 그 자식(손자) 프로세스까지 끈다 — 윈도는 시스템 폴더의 `taskkill /T /F`(절대 경로 — `taskkill_path`), 그 밖은 프로세스 그룹. 어떤 오류도 밖으로 내지 않는다."""
    try:
        if os.name == "nt":
            subprocess.run([taskkill_path(), "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15, creationflags=NO_WINDOW)
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

    def __init__(self, command, *, verify, prepare=None, clock=time.monotonic, prepare_timeout=pov.PREPARE_TIMEOUT_S, read_timeout=pov.READ_TIMEOUT_S, cancel_wait=pov.CANCEL_WAIT_S,
                 idle_exit=pov.IDLE_EXIT_S, work_dir=None, parent_env=None, priority_class=BELOW_NORMAL):
        """`verify` 는 **꼭 줘야 하는** 인자다(운영은 `lambda: service.ocr_addon.verify_problem(폴더)`, 시험은 `verify=None` 으로 '확인 없음' 을 일부러 고른다) — 빠뜨리면 TypeError 라 해시 확인 없이 조용히 뜨는 연결이 없다(검증 S SP-5).
        `command[0]` 은 절대 경로여야 한다(상대 경로면 현재 폴더 탐색 때문에 다른 곳의 같은 이름 실행 파일이 뜰 수 있다)."""
        self.command, self.prepare, self.verify, self.clock = list(command), prepare, verify, clock
        if not self.command or not os.path.isabs(str(self.command[0])):
            raise ValueError("작업자 실행 파일은 절대 경로로 줘야 한다")
        self.priority_class = priority_class                        # 윈도 우선순위 — 기본은 낮음(BELOW_NORMAL: 사용자가 읽는 동안 기다리고 앱 화면이 우선). 시험이 아주 바쁜 PC 에서 굶지 않게 0 을 줄 수 있다(값만 바꿀 뿐 다른 안전 장치와 무관)
        self.prepare_timeout, self.read_timeout, self.cancel_wait, self.idle_exit = prepare_timeout, read_timeout, cancel_wait, idle_exit
        self.work_dir = work_dir if work_dir is not None else os.path.dirname(os.path.abspath(self.command[0]))       # 작업 폴더는 작업자 폴더(설계 3-6 1겹 — 작업자 폴더의 DLL 이 먼저 잡히고 앱의 작업 폴더에 기대지 않게)
        self.parent_env = parent_env if parent_env is not None else dict(os.environ)
        self.process, self.job, self.temp_dir = None, None, None
        self.job_assigned = False                                   # 마지막으로 띄운 작업자를 Job 개체에 넣었는가(윈도 아닌 곳이면 False — Job 개체가 없어 메모리 한도·앱이 죽어도 따라 끝남은 없고 트리 종료·유휴 종료만 남는다. 윈도에서 False 가 되면 그 작업자는 쓰지 않고 `blocked` 로 끝낸다(D-585). 검증 S SP-15)
        self.lines = queue.Queue(maxsize=LINE_QUEUE_MAX)
        self.pump_stop = threading.Event()
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
            try:
                problem = self.verify()
            except Exception:                                       # 확인하다 터졌다 — 확인하지 못한 도구는 띄우지 않는다
                problem = "verify failed"
            if problem:
                raise AdapterError("addon_invalid")
        try:
            self.temp_dir = tempfile.mkdtemp(prefix="cbd-ocr-")
        except OSError:
            raise AdapterError("engine") from None                  # 전용 임시 폴더를 못 만들면 띄우지 않는다
        env = build_environment(self.parent_env, self.temp_dir, self.work_dir)
        options = {"creationflags": NO_WINDOW | self.priority_class} if os.name == "nt" else {"start_new_session": True}
        try:
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self.work_dir, shell=False, **options)
        except OSError:
            self._remove_temp()
            raise AdapterError("blocked") from None
        self.process, self.launches = process, self.launches + 1
        self.job = JobObject()
        self.job_assigned = bool(self.job.assign(process))
        if os.name == "nt" and not self.job_assigned:
            self._stop(kill=True)                                   # 윈도에서 Job 개체에 못 넣었다 — 메모리 1GB 한도도 '앱이 죽으면 작업자도 끝남' 도 없는 채로는 읽지 않는다: 방금 띄운 트리를 끝내고 임시 폴더를 지운 뒤 blocked 로 끝낸다(안전한 기본값, 결정 D-585). 윈도가 아닌 곳은 Job 개체가 없어 이 규칙이 없다
            raise AdapterError("blocked")
        self.lines = queue.Queue(maxsize=LINE_QUEUE_MAX)
        self.pump_stop = threading.Event()
        threading.Thread(target=self._pump_stdout, args=(process, self.lines, self.pump_stop), daemon=True).start()
        threading.Thread(target=self._drain_stderr, args=(process,), daemon=True).start()

    @staticmethod
    def _offer(sink, item, stop):
        """대기열에 넣는다 — 가득 차 있으면(요청하지 않은 줄이 쌓이는 중) 자리가 날 때까지 기다리되, 작업자가 정리되면(stop) 그만둔다 -> 넣었으면 True."""
        while True:
            try:
                sink.put(item, timeout=0.2)
                return True
            except queue.Full:
                if stop is not None and stop.is_set():
                    return False

    @staticmethod
    def _pump_stdout(process, sink, stop=None):
        """표준 출력을 한 줄씩 모은다 — 한 줄이 한도(256KB)를 넘으면 그 사실만 알리고 읽기를 멈춘다(나머지는 버린다). 대기열이 가득 차면 읽기도 멈춘다(앱 메모리를 지킨다)."""
        try:
            while True:
                line = process.stdout.readline(proto.MAX_RESPONSE_BYTES + 1)
                if not line:
                    break
                if len(line) > proto.MAX_RESPONSE_BYTES:
                    OcrAdapter._offer(sink, _OVERSIZE, stop)
                    break
                if not OcrAdapter._offer(sink, line, stop):
                    return
        except Exception:
            pass
        OcrAdapter._offer(sink, _EOF, stop)

    @staticmethod
    def _drain_stderr(process):
        """표준 오류는 비우기만 한다 — 내용은 어디에도 두지 않는다(경로·글이 들 수 있다)."""
        try:
            while process.stderr.read(65536):
                pass
        except Exception:
            pass

    def _next(self, deadline, failure=None):
        """다음 응답 한 줄 -> 바이트 또는 `_EOF`·`_OVERSIZE`·None(시간이 다 됨). 취소 표시가 있으면 `cancel_wait` 안에서만 기다린다. `failure`(요청을 쓰는 스레드의 실패 표시)가 차면 작업자가 떠난 것으로 본다."""
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
                process = self.process                              # 다른 스레드가 `_stop` 으로 비울 수 있어 한 번만 읽어 쓴다
                if failure or (process is not None and process.poll() is not None and self.lines.empty()):
                    return _EOF

    def _wait_ready(self):
        got = self._next(self.clock() + self.prepare_timeout)
        if got is None:
            raise AdapterError("cancelled" if self.cancel_event.is_set() else "timeout")
        if got is _EOF:
            raise AdapterError("died")
        if got is _OVERSIZE:
            raise AdapterError("proto")
        try:
            message = proto.loads_strict(got)
        except Exception:                                           # JSON 이 아니거나 NaN·너무 깊은 겹침 — 모두 약속 위반
            raise AdapterError("proto") from None
        if isinstance(message, dict) and message.get("t") == "error":
            code = message.get("code")                              # 시작 때 작업자가 준비 대신 보내는 오류 줄(모델 확인 실패·엔진 만들기 실패·불러오는 중 네트워크 시도)
            if set(message) <= {"t", "id", "code"} and message.get("id") is None and code in proto.ERROR_CODES:
                raise AdapterError(code if code in ("net_blocked", "proto") else "engine")
            raise AdapterError("proto")
        try:
            proto.validate_ready(message)
        except proto.ProtocolError:
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

    @staticmethod
    def _check_request(width, height, pixels, size_name):
        """요청을 만들기 전에 경계에서 먼저 거른다 — 크기 이름·너비·높이(정수·양수·긴 변 1600 이하)·픽셀 길이가 맞아야 작업자를 띄우고 보낸다(나쁜 요청 때문에 작업자를 띄우지 않는다)."""
        if size_name not in pov.SIZES or type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise AdapterError("decode")
        if max(width, height) > proto.MAX_LONG_SIDE:
            raise AdapterError("too_big")
        try:
            right_length = len(pixels) == width * height * 3
        except TypeError:
            right_length = False
        if not right_length or not isinstance(pixels, (bytes, bytearray, memoryview)):
            raise AdapterError("decode")

    @staticmethod
    def _write_request(process, data, failure):
        """요청 바이트를 작업자 표준 입력에 쓴다(별도 스레드) — 작업자가 안 읽으면 파이프가 차서 쓰기가 막히므로, 읽는 쪽이 사진 한 장의 시간 초과와 취소를 그대로 지킬 수 있게 따로 쓴다. 실패는 `failure` 에 표시만 한다."""
        try:
            process.stdin.write(data)
            process.stdin.flush()
        except (OSError, ValueError):
            failure.append(True)

    def _read_locked(self, width, height, pixels, size_name):
        self.cancel_event.clear()
        self._check_request(width, height, pixels, size_name)
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
        deadline = self.clock() + self.read_timeout                  # 사진 한 장의 시간은 쓰기 전부터 센다(쓰기가 막혀도 시간 초과는 지켜진다)
        failure = []
        writer = threading.Thread(target=self._write_request, args=(self.process, data, failure), daemon=True)
        writer.start()
        got = self._next(deadline, failure)
        self.last_activity = self.clock()
        if got is None:
            raise AdapterError("cancelled" if self.cancel_event.is_set() else "timeout")
        if got is _EOF:
            raise AdapterError("died")
        if got is _OVERSIZE:
            raise AdapterError("proto")
        writer.join(self.cancel_wait)
        if writer.is_alive():
            raise AdapterError("proto")                              # 요청을 다 읽기도 전에 응답했다 — 약속 위반
        if self.cancel_event.is_set():
            return pov.OcrOutcome(error="cancelled")                 # 취소했는데 끝났다 — 결과는 쓰지 않는다(작업자는 쉰다)
        try:
            message = proto.validate_result(proto.loads_strict(got), req_id)
        except Exception:                                            # 약속 위반(ProtocolError)·JSON 이 아님·NaN·너무 깊은 겹침 — 무엇이든 응답 전체를 버린다
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
        if not self.lock.acquire(blocking=False):
            return False                                            # 지금 읽는 중이다 — 쉬는 것이 아니다(화면 스레드의 타이머가 부르므로 기다리지 않는다)
        try:
            if self.process is not None and self.last_activity is not None and self.clock() - self.last_activity >= self.idle_exit:
                self._stop(kill=False)
                return True
            return False
        finally:
            self.lock.release()

    def _remove_temp(self):
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir = None

    def _stop(self, kill):
        """작업자를 끝내고 흔적을 지운다 — 여러 번 불러도 같다. `kill` 이 거짓이면 먼저 정중하게(bye) 부탁한다."""
        process = self.process
        self.process = None
        self.pump_stop.set()                                        # 표준 출력을 모으는 스레드에 그만하라고 알린다 — 대기열이 가득 차 기다리는 중이어도 나온다
        if process is not None:
            if not kill:
                def polite():
                    try:
                        process.stdin.write(proto.dumps_line({"t": "bye"}))
                        process.stdin.flush()
                        process.wait(timeout=2)
                    except Exception:
                        pass
                helper = threading.Thread(target=polite, daemon=True)         # 작업자가 안 읽어 파이프가 찼어도 여기서 매달리지 않는다
                helper.start()
                helper.join(3)
            if process.poll() is None or kill:
                kill_tree(process)
            if self.job is not None:                                # Job 개체를 핸들 닫기보다 먼저 닫는다 — 작업자가 손자를 남기고 죽어 손자가 표준 출력 파이프를 쥐고 있어도 KILL_ON_JOB_CLOSE 가 손자를 끝내
                self.job.close()                                    # 파이프가 풀리고, 아래 핸들 닫기(읽기 스레드가 파이프에서 막혀 있으면 닫기도 기다린다)가 영원히 매달리지 않는다(검증 S SP-3)
                self.job = None
            self._close_handles(process)
        if self.job is not None:
            self.job.close()
            self.job = None
        self._remove_temp()
        self.last_activity = None

    @staticmethod
    def _close_handles(process):
        """파이프 핸들을 닫는다 — 별도 스레드에서 `CLOSE_WAIT` 초만 기다린다(손자가 파이프를 쥐고 있으면 닫기가 안 풀릴 수 있다 — 그래도 정리·앱 종료가 매달리지 않는다. 못 닫은 스레드는 파이프가 풀릴 때 끝난다)."""
        def close():
            for handle in (process.stdin, process.stdout, process.stderr):
                try:
                    handle.close()
                except Exception:
                    pass
        helper = threading.Thread(target=close, daemon=True)
        helper.start()
        helper.join(CLOSE_WAIT)

    def shutdown(self):
        """앱 종료 — 작업자를 끝낸다(못 끝내면 트리를 끄고, Job 개체가 마지막 안전망). 여러 번 불러도 같다."""
        self.cancel_event.set()
        got = self.lock.acquire(timeout=self.cancel_wait + 3)       # 읽는 중이면 취소 표시를 보고 곧 나온다 — 그래도 못 잡으면 잠금 없이 트리를 끈다(앱 종료가 매달리지 않게)
        try:
            self._stop(kill=not got)
        finally:
            if got:
                self.lock.release()
        self.cancel_event.clear()


__all__ = ["AdapterError", "CLOSE_WAIT", "DEFAULT_SYSTEM_ROOT", "JobObject", "LINE_QUEUE_MAX", "MEMORY_LIMIT_BYTES", "OcrAdapter", "PROXY_TRAP", "build_environment", "kill_tree", "system_root", "taskkill_path"]
