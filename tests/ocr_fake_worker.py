"""가짜 글자 읽기 작업자(시험 도우미 — 시험이 아니다, 결정 D-512, 시험 계획 T-A) — 순수 파이썬(표준 라이브러리만)이고 3.10·3.12 x 윈도·우분투에서 돈다. 진짜 작업자(`ocr_addon/worker_main.py`)와 같은 표준 입출력 약속을 흉내 낸다.

실행: `python ocr_fake_worker.py --mode 이름 [--delay 초] [--dump 파일] [--pidfile 파일]`
방식(mode): ok(정상) · slow(응답 전에 delay 초 쉼) · noready(준비 신호를 안 보내고 잠) · die(준비 뒤 첫 요청에서 응답 없이 종료 코드 9) · garbage(JSON 이 아닌 줄) · huge(256KB 넘는 줄) ·
net_blocked(오류 net_blocked 를 보내고 종료 코드 5) · eof(준비 신호 직후 종료 코드 3) · stderr_flood(표준 오류에 5MB 를 쏟고 정상 응답) · badfield(모르는 칸이 든 응답) · badid(요청 번호가 다른 응답) ·
nan(응답에 NaN) · manylines(줄 201개) · longline(줄 하나가 401자) · spawn(손자 프로세스를 만들어 pidfile 에 번호를 적고 잠 — 프로세스 트리 종료 시험) · env(응답 줄로 환경 변수 값과 작업 폴더 CWD 를 알려 줌) · deepjson(너무 깊게 겹친 JSON 한 줄) · nostdin(준비 뒤 표준 입력을 읽지 않고 잠 — 큰 요청의 쓰기가 막히는 경우) · stderr_secret(표준 오류에 비밀 닮은 글과 경로를 씀) · net_attempts(정상 모양이지만 net_attempts 가 0 이 아닌 응답) · bigvalid(올바른 JSON 이지만 256KB 가 넘는 응답) · badtype(줄의 글이 숫자) · badrange(좌표가 0-1 밖) · scorefield(평가용 score 칸이 든 줄) · linefield(줄 안에 모르는 칸이 든 줄) · nan_extra(허용된 칸 trunc 에 NaN) · early_answer(요청 머리만 읽고 본문은 안 읽은 채 응답) · edge_ok(올바른 응답이 줄바꿈까지 정확히 262144바이트) · edge_over(262145바이트 — 한 바이트 넘음) · startup_engine(준비 대신 시작 실패 오류를 보내고 종료 코드 6) · badready(준비 줄에 모르는 칸) · badproto(준비 줄의 약속 번호가 다름) · twice(응답을 두 번 보냄) · die_with_grandchild(손자를 만들어 pidfile 에 번호를 적고 준비 신호 뒤 첫 요청에서 응답 없이 죽음 — 손자가 파이프를 쥐고 남는 경우) · flood_after_result(정상 응답 뒤 요청하지 않은 줄을 끝없이 쏟아냄).
`--dump 파일` 이면 받은 요청 바이트(머리 한 줄 + 픽셀)를 그 파일에 그대로 이어 쓴다(요청에 경로·Exif 가 없는지 시험이 본다). 정말 아무것도 읽지 않는다(글은 가짜).
"""
import json
import os
import subprocess
import sys
import time


def emit(obj_or_bytes):
    data = obj_or_bytes if isinstance(obj_or_bytes, bytes) else (json.dumps(obj_or_bytes, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def arg(name, default=None):
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def result(req_id, lines=None, **extra):
    base = {"t": "result", "id": req_id, "lines": lines if lines is not None else [{"text": "가짜 줄 1", "cx": 0.3, "cy": 0.2, "h": 0.04}, {"text": "가짜 줄 2", "cx": 0.3, "cy": 0.4, "h": 0.04}],
            "ms": {"det": 1, "rec": 1}, "net_attempts": 0}
    base.update(extra)
    return base


def main():
    mode = arg("--mode", "ok")
    delay = float(arg("--delay", "0"))
    dump = arg("--dump")
    pidfile = arg("--pidfile")
    if mode == "noready":
        time.sleep(3600)
        return 0
    if mode == "startup_engine":
        emit({"t": "error", "id": None, "code": "engine"})
        return 6
    if mode in ("badready", "badproto"):
        ready = {"t": "ready", "proto": 2 if mode == "badproto" else 1, "engine": "fake", "load_s": 0.0}
        if mode == "badready":
            ready["path"] = "C:" + chr(92) + "x"
        emit(ready)
        time.sleep(3600)
        return 0
    if mode == "die_with_grandchild":
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(3600)"])           # 손자는 표준 입출력 파이프를 물려받아 작업자가 죽어도 쥐고 있다
        if pidfile:
            with open(pidfile, "w", encoding="utf-8") as handle:
                handle.write(str(child.pid))
    if mode == "spawn":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])
        if pidfile:
            with open(pidfile, "w", encoding="utf-8") as handle:
                handle.write(str(child.pid))
        emit({"t": "ready", "proto": 1, "engine": "fake", "load_s": 0.0})
        time.sleep(3600)
        return 0
    emit({"t": "ready", "proto": 1, "engine": "fake", "load_s": 0.0})
    if mode == "eof":
        return 3
    if mode == "nostdin":
        time.sleep(3600)
        return 0
    if mode == "stderr_flood":
        sys.stderr.write("x" * (5 * 1024 * 1024))
        sys.stderr.flush()
    if mode == "stderr_secret":
        sys.stderr.write("CANARY_" + "stderrsecret C:" + chr(92) + "Users" + chr(92) + "UNIQ-PRIVATE" + chr(92) + "photo.jpg Traceback (most recent call last)" + chr(10))
        sys.stderr.flush()
    stdin = sys.stdin.buffer
    while True:
        line = stdin.readline()
        if not line:
            return 3
        head = json.loads(line.decode("utf-8"))
        if head.get("t") == "bye":
            emit({"t": "bye"})
            return 0
        if mode == "early_answer":
            emit(result(head["id"]))
            time.sleep(3600)
            return 0
        body = stdin.read(head["n"])
        if dump:
            with open(dump, "ab") as handle:
                handle.write(line + body)
        req_id = head["id"]
        if delay:
            time.sleep(delay)
        if mode in ("die", "die_with_grandchild"):
            return 9
        if mode == "garbage":
            emit(b"this is not json at all\n")
        elif mode == "huge":
            emit(b'{"t":"result","id":%d,"lines":[],"pad":"%s"}\n' % (req_id, b"x" * (300 * 1024)))
        elif mode == "net_blocked":
            emit({"t": "error", "id": req_id, "code": "net_blocked"})
            return 5
        elif mode == "badfield":
            emit(result(req_id, secret_path="C:\\x"))
        elif mode == "badid":
            emit(result(req_id + 1))
        elif mode == "nan":
            emit(b'{"t":"result","id":%d,"lines":[{"text":"a","cx":NaN,"cy":0.1,"h":0.1}],"ms":{},"net_attempts":0}\n' % req_id)
        elif mode == "manylines":
            emit(result(req_id, [{"text": "줄 %d" % n, "cx": 0.1, "cy": 0.1, "h": 0.1} for n in range(201)]))
        elif mode == "longline":
            emit(result(req_id, [{"text": "가" * 401, "cx": 0.1, "cy": 0.1, "h": 0.1}]))
        elif mode == "env":
            keys = ("HF_HUB_OFFLINE", "DO_NOT_TRACK", "ORT_DISABLE_TELEMETRY", "OPENCV_OPENCL_RUNTIME", "PYTHONUTF8", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "TEMP", "TMP", "SECRET_FOR_TEST", "PATH")
            rows = [{"text": "%s=%s" % (key, os.environ.get(key, "<없음>")), "cx": 0.1, "cy": 0.1, "h": 0.1} for key in keys]
            rows.append({"text": "CWD=%s" % os.getcwd(), "cx": 0.1, "cy": 0.1, "h": 0.1})
            emit(result(req_id, rows))
        elif mode == "deepjson":
            emit(b"[" * 100000 + chr(10).encode("ascii"))
        elif mode == "net_attempts":
            emit(result(req_id, net_attempts=2))
        elif mode == "bigvalid":
            emit(result(req_id, [], trunc="x" * (300 * 1024)))
        elif mode in ("edge_ok", "edge_over"):
            target = 262144 if mode == "edge_ok" else 262145
            base = json.dumps(result(req_id, [], trunc=""), ensure_ascii=False, separators=(",", ":")) + chr(10)
            emit(result(req_id, [], trunc="x" * (target - len(base.encode("utf-8")))))
        elif mode == "badtype":
            emit(result(req_id, [{"text": 5, "cx": 0.1, "cy": 0.1, "h": 0.1}]))
        elif mode == "badrange":
            emit(result(req_id, [{"text": "a", "cx": 1.5, "cy": 0.1, "h": 0.1}]))
        elif mode == "scorefield":
            emit(result(req_id, [{"text": "a", "cx": 0.1, "cy": 0.1, "h": 0.1, "score": 0.9}]))
        elif mode == "linefield":
            emit(result(req_id, [{"text": "a", "cx": 0.1, "cy": 0.1, "h": 0.1, "secret_path": "C:\\x"}]))
        elif mode == "nan_extra":
            emit(b'{"t":"result","id":%d,"lines":[],"ms":{},"net_attempts":0,"trunc":NaN}' % req_id + chr(10).encode("ascii"))
        elif mode == "twice":
            emit(result(req_id))
            emit(result(req_id))
        elif mode == "flood_after_result":
            emit(result(req_id))
            chunk = b'{"t":"alive"}' + chr(10).encode("ascii")
            while True:                                             # 쉬는 동안 요청하지 않은 줄을 끝없이 쏟아낸다(앱이 끝낼 때까지)
                sys.stdout.buffer.write(chunk * 500)
                sys.stdout.buffer.flush()
        else:
            emit(result(req_id))


if __name__ == "__main__":
    sys.exit(main())
