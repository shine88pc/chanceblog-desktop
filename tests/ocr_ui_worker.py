"""화면 흐름 시험용 가짜 글자 읽기 작업자(시험 도우미 — 시험이 아니다, 결정 D-513) — 순수 파이썬(표준 라이브러리만)이고 진짜 작업자(`ocr_addon/worker_main.py`)와 같은 표준 입출력 약속을 흉내 낸다.
`tests/ocr_fake_worker.py`(어댑터 시험용)와 달리 **준비가 늦는 것**(`--ready-delay`)과 **읽은 글을 정하는 것**(`--lines`)이 된다 — 준비 중 → 읽는 중 → 완료로 가는 화면 상태를 붙잡아 보려는 것이다.

실행: `python ocr_ui_worker.py [--mode ok|die|net_blocked] [--ready-delay 초] [--delay 초] [--lines 글|글|글] [--dump 파일] [--pidfile 파일] [--child-heartbeat 파일]`
  ok = 정상(요청마다 delay 초 쉬었다가 lines 를 준다) · die = 준비 뒤 첫 요청에서 응답 없이 종료 코드 9 · net_blocked = 오류 net_blocked 를 보내고 종료 코드 5.
`--child-heartbeat 파일` 이면 시작하면서 손자 프로세스 하나를 띄운다(0.2초마다 그 파일을 새로 쓴다 — 어댑터의 프로세스 트리 종료가 손자까지 끄는지 시험이 박동으로 본다, 파일 폴더가 사라지면 손자도 스스로 끝난다). `--dump 파일` 이면 받은 요청 바이트(머리 한 줄 + 픽셀)를 그대로 이어 쓰고, `--pidfile 파일` 이면 자기 프로세스 번호를 적는다(끝났는지 시험이 본다). 정말 아무것도 읽지 않는다(글은 가짜).
"""
import json
import os
import subprocess
import sys
import time

CHILD = """import sys, time
stop = time.time() + 30
while time.time() < stop:
    try:
        open(sys.argv[1], "w").write(str(time.time()))
    except OSError:
        break
    time.sleep(0.2)
"""


def emit(obj):
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def arg(name, default=None):
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def main():
    mode = arg("--mode", "ok")
    ready_delay = float(arg("--ready-delay", "0"))
    delay = float(arg("--delay", "0"))
    lines = [item for item in (arg("--lines", "가짜 줄 하나|가짜 줄 둘 1,000원") or "").split("|") if item]
    dump, pidfile = arg("--dump"), arg("--pidfile")
    heartbeat = arg("--child-heartbeat")
    if pidfile:
        with open(pidfile, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    if heartbeat:
        subprocess.Popen([sys.executable, "-B", "-c", CHILD, heartbeat])                  # 진짜 엔진의 하위 프로세스처럼 작업자의 파이프를 물려받는다 — 트리를 끄지 못하면 읽는 쪽이 끝을 못 보고 시험이 빨개진다(손자는 30초 뒤 스스로 끝나 시험이 영원히 걸리지는 않는다)
        end = time.monotonic() + 20
        while time.monotonic() < end and not os.path.exists(heartbeat):
            time.sleep(0.05)
    if ready_delay:
        time.sleep(ready_delay)
    emit({"t": "ready", "proto": 1, "engine": "fake-ui", "load_s": ready_delay})
    stdin = sys.stdin.buffer
    while True:
        line = stdin.readline()
        if not line:
            return 3
        head = json.loads(line.decode("utf-8"))
        if head.get("t") == "bye":
            emit({"t": "bye"})
            return 0
        body = stdin.read(head["n"])
        if dump:
            with open(dump, "ab") as handle:
                handle.write(line + body)
        if delay:
            time.sleep(delay)
        if mode == "die":
            return 9
        if mode == "net_blocked":
            emit({"t": "error", "id": head["id"], "code": "net_blocked"})
            return 5
        emit({"t": "result", "id": head["id"], "lines": [{"text": text, "cx": 0.2, "cy": 0.2 + 0.01 * number, "h": 0.04} for number, text in enumerate(lines)], "ms": {"det": 1, "rec": 1}, "net_attempts": 0})


if __name__ == "__main__":
    sys.exit(main())
