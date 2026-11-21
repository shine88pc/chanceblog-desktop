"""T-G(1) — 진짜 작업자 소스(`ocr_addon/worker_main.py`·`netguard.py`·`protocol.py`)에 소켓을 여는 가짜 엔진을 끼워 막히고 `net_blocked` 로 보고되는지 본다(결정 D-512, 설계서 3-6 2겹, 시험 계획 T-G).

방법 — `tests/ocr_worker_probe.py`(시험 전용 실행기, 동결본에는 없다)가 진짜 `worker_main` 을 가져오고(소켓 가드는 이때 첫 문장에서 켜진다) 엔진 만들기·모델 파일 확인 이름만 바꿔 끼운 뒤 `worker_main.main` 을 그대로 부른다.
시험이 만드는 '바깥 연결 시도'는 모두 패킷이 나갈 수 없는 주소(`0.0.0.1`)와 숫자 주소만 쓴다 — 가드가 망가져도 실제 연결은 일어나지 않는다. 루프백은 `127.0.0.1` 닫힌 포트다.

지키는 것:
  1) 바깥 시도(connect·connect_ex·create_connection·getaddrinfo·gethostbyname·sendto)는 막히고, 작업자는 그 응답을 버리고 `net_blocked` 오류와 종료 코드 5 로 끝난다(결과 줄은 나가지 않는다).
  2) 루프백은 통과하고 횟수로 세지 않는다. 가드는 바깥 시도와 루프백을 따로 세고 대상 이름만 메모리에 둔다.
  3) 라이브러리가 가져오는 도중에 하는 바깥 시도도 잡힌다(가드가 가져오기보다 먼저다) — 준비 신호 대신 `net_blocked` 시작 오류와 종료 코드 5. 시작 실패는 `engine` 과 종료 코드 6.
  4) 가드를 못 켜면(설치가 예외·켜지지 않음) 작업자는 시작하지 않는다(종료 코드 70). 가드는 `worker_main.py` 의 첫 문장이고 엔진 라이브러리는 함수 안에서만 가져온다(소스 규칙).
  5) 진짜 `serve` 의 약속 처리 — 나쁜 머리·모르는 칸·`opts`·너무 긴 머리는 `proto` 와 종료 코드 2, 크기가 안 맞거나 너무 크면 오류 응답 뒤 계속 일하고, 본문 도중에 입력이 닫히면 종료 코드 3, `bye`·EOF 는 `bye` 와 0.
  6) 진짜 작업자의 응답(줄 200개로 줄임·`dropped`·`trunc`·글 400자 자름)이 앱의 응답 검사를 모두 통과하고, 어댑터가 `net_blocked`·`engine` 을 이름으로 알리며 컨트롤러가 끈다.
"""
import ast
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from capability_support import local_ocr_off, local_ocr_on  # noqa: E402

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.content import photo_ocr as po  # noqa: E402
from chanceblog_desktop.ui import ocr_adapter as oa  # noqa: E402
from chanceblog_desktop.ui.core import ocr_protocol as proto  # noqa: E402
from chanceblog_desktop.ui.core import photo_ocr_view as pov  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402

PROBE = str(HERE / "ocr_worker_probe.py")
ADDON = ROOT / "ocr_addon"
WORKER_MAIN = ADDON / "worker_main.py"
PIXELS = bytes(range(256)) * 3                       # 16 x 16 RGB
BLOCKED_KINDS = ("connect", "connect_ex", "create_connection", "getaddrinfo", "gethostbyname", "sendto")
FAKE_ONNXRUNTIME = '''import socket
try:
    socket.create_connection(("0.0.0.1", 9), timeout=0.2)
except OSError:
    pass
__version__ = "fake"


def disable_telemetry_events():
    pass
'''
FAKE_RAPIDOCR_MAIN = '''import types


class RapidOCR:
    def __init__(self, params=None):
        self.params = params

    def __call__(self, array, **options):
        return types.SimpleNamespace(txts=["가짜"], boxes=[[[0, 0], [10, 0], [10, 5], [0, 5]]], scores=[0.9], elapse_list=[0.0, 0.0, 0.0])
'''


def hard_kill(process):
    """시험의 마지막 안전망 — 어댑터의 정리 코드(변이로 망가질 수 있는)를 거치지 않고 이 시험이 띄운 프로세스와 그 자식을 PID 로 끝낸다."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30, creationflags=0x08000000)
        else:
            process.kill()
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass


def probe_command(mode, *extra):
    base = [sys.executable, "-B", PROBE, "--probe", mode, *extra]
    if os.name != "nt":
        # 어댑터는 환경 변수를 새로 짜서 LD_LIBRARY_PATH 도 없앤다 — 공유 라이브러리로 만든 파이썬이 뜨려면 시험에서만 /usr/bin/env 로 그 한 변수를 되살려 준다.
        return ["/usr/bin/env", "LD_LIBRARY_PATH=" + os.environ.get("LD_LIBRARY_PATH", ""), *base]
    return base


def make_fakelib(folder):
    folder = Path(folder)
    (folder / "rapidocr").mkdir(parents=True, exist_ok=True)
    (folder / "onnxruntime.py").write_text(FAKE_ONNXRUNTIME, encoding="utf-8")
    (folder / "cv2.py").write_text("# 가짜 cv2\n", encoding="utf-8")
    (folder / "rapidocr" / "__init__.py").write_text("", encoding="utf-8")
    (folder / "rapidocr" / "main.py").write_text(FAKE_RAPIDOCR_MAIN, encoding="utf-8")
    return str(folder)


class Client:
    """작업자(probe)를 직접 띄워 표준 입출력으로 말해 보는 시험용 클라이언트 — 어댑터를 거치지 않고 진짜 작업자의 응답 줄과 종료 코드를 그대로 본다. 환경 변수는 어댑터와 같은 방식으로 새로 짠 것을 준다."""

    def __init__(self, mode, *extra, command=None):
        self.temp = tempfile.mkdtemp(prefix="cbd-ocr-test-")
        env = oa.build_environment(dict(os.environ), self.temp)
        self.process = subprocess.Popen(command or probe_command(mode, *extra), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(ROOT))
        self.stderr = []
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=lambda: self.stderr.append(self.process.stderr.read()), daemon=True).start()

    def _pump(self):
        try:
            for raw in iter(self.process.stdout.readline, b""):
                self.lines.put(raw)
        except Exception:
            pass
        self.lines.put(None)

    def line(self, timeout=30):
        """다음 응답 줄(JSON -> dict). 출력이 끝났으면 None. 시간 안에 안 오면 시험을 실패시킨다."""
        try:
            raw = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("작업자의 응답이 시간 안에 오지 않았다") from None
        return None if raw is None else json.loads(raw.decode("utf-8"))

    def send(self, head, body=b""):
        data = head if isinstance(head, bytes) else (json.dumps(head) + chr(10)).encode("utf-8")
        self.process.stdin.write(data + body)
        self.process.stdin.flush()

    def request(self, req_id=1, width=16, height=16, pixels=PIXELS, **extra):
        head = {"t": "ocr", "id": req_id, "w": width, "h": height, "fmt": "rgb24", "n": len(pixels)}
        head.update(extra)
        self.send(head, pixels)

    def finish(self, timeout=30):
        """출력이 끝날 때까지 읽고(남은 줄은 버린다) 종료 코드를 돌려준다."""
        while self.line(timeout) is not None:
            pass
        return self.process.wait(timeout=timeout)

    def close(self):
        hard_kill(self.process)
        for handle in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                handle.close()
            except Exception:
                pass
        import shutil
        shutil.rmtree(self.temp, ignore_errors=True)


class ClientCase(unittest.TestCase):
    def client(self, mode, *extra, **options):
        client = Client(mode, *extra, **options)
        self.addCleanup(client.close)
        return client

    def ready(self, client):
        message = client.line()
        proto.validate_ready(message)
        return message

    def answer(self, client, req_id=1, **request):
        client.request(req_id, **request)
        return client.line()


class GuardBlocksTest(ClientCase):
    def test_the_worker_says_ready_in_the_agreed_shape(self):
        client = self.client("ok")
        message = self.ready(client)
        self.assertEqual((message["t"], message["proto"], message["engine"]), ("ready", 1, "rapidocr-?+ort-fake-ort"))

    def test_each_outside_attempt_is_blocked_and_reported_as_net_blocked_and_the_worker_ends_with_code_five(self):
        for kind in BLOCKED_KINDS:
            with self.subTest(kind=kind):
                client = self.client("net_" + kind)
                self.ready(client)
                answer = self.answer(client, 7)
                self.assertEqual(answer, {"t": "error", "id": 7, "code": "net_blocked"}, kind)
                self.assertIsNone(client.line(), "결과 줄은 나가지 않는다")
                self.assertEqual(client.process.wait(timeout=30), 5, kind)

    def test_loopback_passes_and_is_not_counted_so_the_answer_is_a_normal_result_and_the_worker_keeps_working(self):
        client = self.client("net_loopback")
        self.ready(client)
        for req_id in (1, 2):
            answer = self.answer(client, req_id)
            proto.validate_result(answer, req_id)
            self.assertEqual((answer["t"], answer["net_attempts"], [line["text"] for line in answer["lines"]]), ("result", 0, ["루프백만 쓴 글"]))
        self.assertIsNone(client.process.poll(), "루프백은 시도로 안 세어 작업자는 계속 산다")

    def test_the_guard_counts_outside_attempts_and_loopback_separately_and_forgets_after_a_reset(self):
        client = self.client("net_count")
        self.ready(client)
        seen = []
        for req_id in (1, 2):
            answer = self.answer(client, req_id)
            stats = json.loads(answer["lines"][0]["text"])
            seen.append((stats["attempts"], stats["loopback"]))
            self.assertEqual(stats["attempts"], 3, "바깥 시도 셋(connect·getaddrinfo·sendto)만 시도로 센다 — 루프백 둘은 안 센다")
            self.assertGreaterEqual(stats["loopback"], 2, "루프백은 따로 센다(create_connection 하나가 안쪽에서 getaddrinfo·connect 를 또 불러 시도마다 한 번 넘게 센다)")
            self.assertTrue(any("0.0.0.1" in target for target in stats["targets"]), stats["targets"])
            self.assertTrue({"socket.connect", "socket.getaddrinfo", "socket.sendto"} <= set(stats["apis"]), stats["apis"])
            self.assertFalse(any("127.0.0.1" in target for target in stats["targets"]), "루프백은 시도 목록에 없다")
        self.assertEqual(seen[0], seen[1], "두 번째 요청의 횟수가 첫 번째와 같다 — 횟수를 비웠으므로 쌓이지 않는다")

    def test_a_library_that_tries_the_network_while_it_is_imported_is_caught_because_the_guard_comes_first(self):
        with tempfile.TemporaryDirectory() as folder:
            client = self.client("import_time", "--fakelib", make_fakelib(folder))
            self.assertEqual(client.line(), {"t": "error", "id": None, "code": "net_blocked"}, "준비 신호 대신 시작 오류")
            self.assertIsNone(client.line())
            self.assertEqual(client.process.wait(timeout=30), 5)

    def test_a_start_up_failure_is_reported_as_engine_and_the_worker_ends_with_code_six(self):
        client = self.client("startup_raise")
        self.assertEqual(client.line(), {"t": "error", "id": None, "code": "engine"})
        self.assertIsNone(client.line())
        self.assertEqual(client.process.wait(timeout=30), 6)

    def test_a_clean_import_with_the_fake_libraries_reaches_ready_and_reads(self):
        """대조 — 가져오는 도중 시도가 없는 가짜 라이브러리면 정상으로 준비되고 읽는다(위 시험의 빨강이 가짜 라이브러리 탓이 아님을 보인다)."""
        with tempfile.TemporaryDirectory() as folder:
            lib = Path(make_fakelib(folder))
            (lib / "onnxruntime.py").write_text("__version__ = 'fake'" + chr(10) + "def disable_telemetry_events():" + chr(10) + "    pass" + chr(10), encoding="utf-8")
            client = self.client("import_time", "--fakelib", str(lib))
            self.ready(client)
            answer = self.answer(client, 3)
            proto.validate_result(answer, 3)
            self.assertEqual([line["text"] for line in answer["lines"]], ["가짜"])
            client.close()                                          # 작업자가 가짜 라이브러리 폴더를 쥔 채로 폴더를 지우지 않게 먼저 끝낸다


class GuardIsFirstTest(unittest.TestCase):
    ENGINE_LIBS = {"rapidocr", "onnxruntime", "cv2", "numpy", "PIL", "yaml", "shapely", "pyclipper", "omegaconf", "colorlog", "tqdm", "requests"}

    def tree(self):
        return ast.parse(WORKER_MAIN.read_text(encoding="utf-8"))

    def test_the_guard_try_block_is_the_first_statement_after_the_docstring_and_fails_closed(self):
        body = self.tree().body
        self.assertTrue(isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant), "맨 위는 설명 글")
        first = body[1]
        self.assertIsInstance(first, ast.Try, "그다음 첫 문장이 가드를 켜는 try 다")
        text = ast.unparse(first)
        self.assertIn("import netguard as _netguard", text)
        self.assertIn("_netguard.install()", text)
        self.assertIn("_netguard.ACTIVE", text, "켜졌는지 확인한다")
        self.assertIn("_exit(70)", text, "실패하면 종료 코드 70 으로 바로 끝낸다")
        self.assertEqual([ast.unparse(handler.type) for handler in first.handlers], ["BaseException"], "무엇이든(BaseException) 실패로 본다")

    def test_no_engine_library_is_imported_at_module_level_only_inside_functions(self):
        tree = self.tree()
        top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = {(node.module or "").split(".")[0] if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0] for node in top for alias in getattr(node, "names", [None])}
        self.assertFalse(names & self.ENGINE_LIBS, "엔진 라이브러리는 모듈 맨 위에서 가져오지 않는다 — 함수(build_engine 등) 안에서만")
        inside = set()
        for function in (node for node in tree.body if isinstance(node, ast.FunctionDef)):
            for node in ast.walk(function):
                if isinstance(node, ast.Import):
                    inside |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    inside.add((node.module or "").split(".")[0])
        self.assertTrue({"onnxruntime", "cv2", "rapidocr", "numpy"} <= inside, "엔진 라이브러리를 가져오는 곳은 함수 안이다")
        guard_end = tree.body[1].end_lineno
        early = [node.lineno for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno > guard_end and (node.col_offset == 0)
                 and ({alias.name.split(".")[0] for alias in node.names} | {(getattr(node, "module", None) or "").split(".")[0]}) & self.ENGINE_LIBS]
        self.assertEqual(early, [])


class FrozenBuildCannotReachTheProbeTest(unittest.TestCase):
    """동결 작업자에는 가짜 엔진을 끼울 길이 없다 — 시험 전용 실행기는 `tests/` 에만 있고 작업자 소스·빌드 스크립트·앱 소스는 그것을 모른다(`worker_main.py` 는 환경 변수를 읽지 않고 모르는 인자는 거절한다)."""
    SOURCES = ("worker_main.py", "netguard.py", "protocol.py", "build_ocr_addon.py")

    def test_no_addon_source_names_the_probe_or_a_way_to_pick_a_fake_engine(self):
        for name in self.SOURCES:
            text = (ADDON / name).read_text(encoding="utf-8")
            for needle in ("ocr_worker_probe", "ocr_fake_worker", "--probe", "--fakelib", "fake_build_engine", "FAKELIB"):
                self.assertNotIn(needle, text, f"{name}: {needle}")
        self.assertNotIn("tests", (ADDON / "build_ocr_addon.py").read_text(encoding="utf-8"), "빌드 스크립트는 시험 폴더를 묶지 않는다")
        self.assertFalse((ADDON / "tests").exists())

    def test_neither_the_app_source_nor_the_packaging_folder_mentions_the_probe(self):
        for folder in (ROOT / "src", ROOT / "packaging"):
            for path in folder.rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                for needle in ("ocr_worker_probe", "ocr_fake_worker"):
                    self.assertNotIn(needle, text, f"{path.name}: {needle}")

    def test_the_worker_reads_no_environment_variable_so_nothing_outside_can_pick_an_engine(self):
        tree = ast.parse(WORKER_MAIN.read_text(encoding="utf-8"))
        loads = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func) in ("os.getenv", "os.environ.get", "_os.getenv", "_os.environ.get", "os.environ.setdefault"):
                loads.append(node.lineno)
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) in ("os.environ", "_os.environ") and isinstance(node.ctx, ast.Load):
                loads.append(node.lineno)
        self.assertEqual(loads, [], "작업자는 환경 변수를 읽지 않는다(쓰기만 한다)")

    def test_the_real_entry_file_refuses_the_probe_arguments_and_never_says_ready(self):
        command = [sys.executable, "-B", str(WORKER_MAIN), "--probe", "ok"]
        if os.name != "nt":
            command = ["/usr/bin/env", "LD_LIBRARY_PATH=" + os.environ.get("LD_LIBRARY_PATH", ""), *command]
        done = subprocess.run(command, capture_output=True, env=oa.build_environment(dict(os.environ), tempfile.gettempdir()), timeout=120, cwd=str(ROOT), input=b"")
        self.assertEqual(done.returncode, 2, "모르는 인자는 종료 코드 2 로 거절한다")
        self.assertEqual(done.stdout, b"", "준비 신호도 응답도 없다")
        self.assertIn("모르는 인자", done.stderr.decode("utf-8", "replace"))


class FailClosedTest(unittest.TestCase):
    def run_with_guard_source(self, source):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "netguard.py").write_text(source, encoding="utf-8")
            code = "import sys" + chr(10) + f"sys.path.insert(0, {folder!r})" + chr(10) + f"sys.path.insert(1, {str(ADDON)!r})" + chr(10) + "import worker_main" + chr(10) + "print('STARTED')" + chr(10)
            command = [sys.executable, "-B", "-c", code]
            if os.name != "nt":
                command = ["/usr/bin/env", "LD_LIBRARY_PATH=" + os.environ.get("LD_LIBRARY_PATH", ""), *command]
            env = oa.build_environment(dict(os.environ), folder)
            return subprocess.run(command, capture_output=True, env=env, timeout=60, cwd=str(ROOT))

    def test_if_the_guard_install_raises_the_worker_does_not_start_and_ends_with_code_seventy(self):
        done = self.run_with_guard_source("ACTIVE = False" + chr(10) + "def install():" + chr(10) + "    raise RuntimeError('install failed')" + chr(10))
        self.assertEqual(done.returncode, 70)
        self.assertNotIn(b"STARTED", done.stdout)
        self.assertIn("소켓 가드 적재 실패 (RuntimeError)", done.stderr.decode("utf-8", "replace"))

    def test_if_the_guard_installs_but_is_not_active_the_worker_does_not_start_either(self):
        done = self.run_with_guard_source("ACTIVE = False" + chr(10) + "def install():" + chr(10) + "    return True" + chr(10))
        self.assertEqual(done.returncode, 70)
        self.assertNotIn(b"STARTED", done.stdout)

    def test_with_a_working_guard_the_same_import_goes_on(self):
        done = self.run_with_guard_source("ACTIVE = False" + chr(10) + "def install():" + chr(10) + "    global ACTIVE" + chr(10) + "    ACTIVE = True" + chr(10) + "    return True" + chr(10))
        self.assertEqual(done.returncode, 0)
        self.assertIn(b"STARTED", done.stdout)


class RealServeProtocolTest(ClientCase):
    """진짜 `serve` 의 약속 처리 — 앱이 잘못 보냈을 때 작업자가 어떻게 끝나거나 계속하는가."""

    def test_a_header_that_is_not_json_ends_the_worker_with_proto_and_code_two(self):
        client = self.client("ok")
        self.ready(client)
        client.send(b"this is not json" + chr(10).encode("ascii"))
        self.assertEqual(client.line(), {"t": "error", "id": None, "code": "proto"})
        self.assertEqual(client.finish(), 2)

    def test_a_request_carrying_a_field_that_does_not_belong_in_it_is_refused_and_ends_the_worker(self):
        for extra in ({"path": "C:" + chr(92) + "x.jpg"}, {"photo_id": "p001"}, {"note": "메모"}, {"exif": {}}):
            with self.subTest(extra=sorted(extra)):
                client = self.client("ok")
                self.ready(client)
                client.request(1, **extra)
                self.assertEqual(client.line(), {"t": "error", "id": None, "code": "proto"})
                self.assertEqual(client.finish(), 2)

    def test_options_are_refused_unless_the_worker_was_started_for_evaluation(self):
        client = self.client("ok")
        self.ready(client)
        client.request(5, opts={"text_score": 0.5})
        self.assertEqual(client.line(), {"t": "error", "id": 5, "code": "proto"})
        self.assertEqual(client.finish(), 2)

    def test_a_header_line_that_is_too_long_ends_the_worker_with_proto(self):
        client = self.client("ok")
        self.ready(client)
        client.send(b"x" * 3000)
        self.assertEqual(client.line(), {"t": "error", "id": None, "code": "proto"})
        self.assertEqual(client.finish(), 2)

    def test_a_size_that_does_not_match_the_bytes_is_answered_with_decode_and_the_worker_carries_on(self):
        client = self.client("ok")
        self.ready(client)
        client.send({"t": "ocr", "id": 3, "w": 16, "h": 16, "fmt": "rgb24", "n": 100}, bytes(100))
        self.assertEqual(client.line(), {"t": "error", "id": 3, "code": "decode"})
        answer = self.answer(client, 4)
        proto.validate_result(answer, 4)
        self.assertEqual(answer["t"], "result")

    def test_a_long_side_over_the_limit_is_answered_with_too_big_and_the_worker_carries_on(self):
        client = self.client("ok")
        self.ready(client)
        pixels = bytes(1601 * 3)
        client.request(3, 1601, 1, pixels)
        self.assertEqual(client.line(), {"t": "error", "id": 3, "code": "too_big"})
        answer = self.answer(client, 4)
        self.assertEqual(answer["t"], "result")

    def test_input_that_closes_in_the_middle_of_a_body_ends_the_worker_with_code_three_and_no_answer(self):
        client = self.client("ok")
        self.ready(client)
        client.send({"t": "ocr", "id": 1, "w": 16, "h": 16, "fmt": "rgb24", "n": 768}, bytes(100))
        client.process.stdin.close()
        self.assertIsNone(client.line())
        self.assertEqual(client.process.wait(timeout=30), 3)

    def test_bye_and_the_end_of_input_both_end_the_worker_politely(self):
        client = self.client("ok")
        self.ready(client)
        client.send({"t": "bye"})
        self.assertEqual(client.line(), {"t": "bye"})
        self.assertEqual(client.finish(), 0)
        again = self.client("ok")
        self.ready(again)
        again.process.stdin.close()
        self.assertEqual(again.line(), {"t": "bye"})
        self.assertEqual(again.finish(), 0)

    def test_an_engine_that_raises_is_answered_with_engine_and_the_worker_keeps_serving(self):
        client = self.client("raise")
        self.ready(client)
        for req_id in (1, 2):
            self.assertEqual(self.answer(client, req_id), {"t": "error", "id": req_id, "code": "engine"})
        self.assertIsNone(client.process.poll())


class RealAnswersPassTheAppCheckTest(ClientCase):
    """진짜 작업자 코드가 만든 응답이 앱의 응답 검사(`validate_result`)를 그대로 통과하는가 — 두 쪽의 약속이 실제로 맞물리는지."""

    def test_a_normal_answer_has_the_agreed_keys_and_passes(self):
        client = self.client("ok")
        self.ready(client)
        answer = self.answer(client, 9)
        proto.validate_result(answer, 9)
        self.assertEqual(sorted(answer), ["id", "lines", "ms", "net_attempts", "t"])
        self.assertEqual([line["text"] for line in answer["lines"]], ["안녕 하세요", "12,000"])
        for line in answer["lines"]:
            self.assertEqual(sorted(line), ["cx", "cy", "h", "text"], "확신도·상자는 평가용(--eval)에서만 — 기본 응답에는 없다")

    def test_three_hundred_lines_are_cut_to_two_hundred_with_the_dropped_count_and_still_pass(self):
        client = self.client("many")
        self.ready(client)
        answer = self.answer(client, 1)
        proto.validate_result(answer, 1)
        self.assertEqual((len(answer["lines"]), answer["dropped"]), (200, 100))

    def test_a_line_longer_than_four_hundred_characters_is_cut_by_the_worker_and_passes(self):
        client = self.client("longline")
        self.ready(client)
        answer = self.answer(client, 1)
        proto.validate_result(answer, 1)
        self.assertEqual(len(answer["lines"][0]["text"]), 400)

    def test_an_answer_over_the_size_limit_is_shortened_by_the_worker_flags_trunc_and_passes(self):
        client = self.client("emoji_big")
        self.ready(client)
        client.request(1)
        raw = client.lines.get(timeout=30)
        self.assertLessEqual(len(raw), proto.MAX_RESPONSE_BYTES, "한 줄 256KB 한도를 지킨다")
        answer = json.loads(raw.decode("utf-8"))
        proto.validate_result(answer, 1)
        self.assertIs(answer["trunc"], True)
        self.assertLess(len(answer["lines"]), 200)

    def test_the_app_side_check_refuses_what_the_worker_never_sends_so_a_real_answer_is_not_mistaken_for_an_evaluation_one(self):
        client = self.client("ok")
        self.ready(client)
        answer = self.answer(client, 2)
        tampered = json.loads(json.dumps(answer))
        tampered["lines"][0]["score"] = 0.9
        with self.assertRaises(proto.ProtocolError):
            proto.validate_result(tampered, 2)


class AdapterWithTheRealWorkerTest(unittest.TestCase):
    def setUp(self):
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        self.launched = []
        original = oa.OcrAdapter._launch
        launched = self.launched

        def spy(self_):
            original(self_)
            launched.append(self_.process)
        patcher = mock.patch.object(oa.OcrAdapter, "_launch", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: [hard_kill(process) for process in self.launched])

    def adapter(self, mode, *extra):
        adapter = oa.OcrAdapter(probe_command(mode, *extra), prepare_timeout=60, read_timeout=60, priority_class=0)
        self.addCleanup(adapter.shutdown)
        return adapter

    def board(self, adapter):
        board = pv.PhotoBoard()
        manifest, _id = pm.add_photo(pm.empty_manifest(), "C:" + chr(92) + "Users" + chr(92) + "UNIQ" + chr(92) + "Pictures" + chr(92) + "x-01.jpg", photo_type="메뉴판")
        board.load(manifest)
        adapter.prepare = lambda job: (16, 16, PIXELS)
        return board, pov.OcrBoard(board, adapter)

    def test_a_normal_read_through_the_real_worker_code_returns_only_the_texts(self):
        outcome = self.adapter("ok").read_rgb(16, 16, PIXELS, "960")
        self.assertEqual((outcome.error, list(outcome.lines)), ("", [{"text": "안녕 하세요"}, {"text": "12,000"}]))

    def test_an_outside_attempt_inside_the_engine_comes_out_of_the_adapter_as_net_blocked_and_turns_the_reader_off(self):
        adapter = self.adapter("net_connect")
        board, ocr = self.board(adapter)
        ocr.request_read("p001")
        self.assertEqual(ocr.run_pending(), [("p001", "disabled")])
        self.assertEqual((ocr.disabled_code, ocr.error_of("p001"), adapter.process), ("OCR_UNEXPECTED", "net_blocked", None))
        self.assertEqual(ocr.request_read("p001"), "unavailable")

    def test_an_attempt_while_the_libraries_load_is_named_net_blocked_not_a_violation(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter = self.adapter("import_time", "--fakelib", make_fakelib(folder))
            outcome = adapter.read_rgb(16, 16, PIXELS, "960")
        self.assertEqual(outcome.error, "net_blocked")
        self.assertIsNone(adapter.process)

    def test_a_start_up_failure_of_the_engine_is_named_engine(self):
        adapter = self.adapter("startup_raise")
        self.assertEqual(adapter.read_rgb(16, 16, PIXELS, "960").error, "engine")

    def test_loopback_only_is_a_normal_result_through_the_adapter(self):
        outcome = self.adapter("net_loopback").read_rgb(16, 16, PIXELS, "960")
        self.assertEqual((outcome.error, list(outcome.lines)), ("", [{"text": "루프백만 쓴 글"}]))

    def test_two_hundred_real_lines_all_pass_the_adapter_and_the_rule_keeps_sixty_and_counts_the_rest(self):
        outcome = self.adapter("many").read_rgb(16, 16, PIXELS, "960")
        self.assertEqual((outcome.error, len(outcome.lines)), ("", 200))
        found = po.prepare(outcome.lines)
        self.assertEqual((found.found, found.over_limit, found.filtered), (60, 140, 0))

    def test_the_trunc_answer_passes_the_adapter_too(self):
        outcome = self.adapter("emoji_big").read_rgb(16, 16, PIXELS, "960")
        self.assertEqual(outcome.error, "")
        self.assertTrue(0 < len(outcome.lines) < 200)

    def test_a_normal_flow_with_the_controller_puts_unconfirmed_candidates_into_the_list(self):
        adapter = self.adapter("ok")
        board, ocr = self.board(adapter)
        ocr.request_read("p001")
        self.assertEqual(ocr.run_pending(), [("p001", "applied")])
        self.assertEqual([(item.text, item.confirmed) for item in board.photo("p001").visible_text], [("안녕 하세요", False), ("12,000", False)])


if __name__ == "__main__":
    unittest.main()
