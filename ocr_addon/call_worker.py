# -*- coding: utf-8 -*-
"""call_worker.py - 앱 없이 작업자(표준 입출력 프로토콜, protocol.py)를 불러 보는 간단한 호출 도구(a 단계 시험용 기록). 이 저장소에 들어 있지만 저장소 밖 작업 폴더의 도구(winproc·imgprep·netwatch 와 합성 시험 사진)를
가져와 쓰므로 저장소 안에서는 그대로 돌지 않는다 — 추가 도구 묶음(`build_ocr_addon.py` 는 `worker_main.py` 만 묶는다)에도 앱 묶음에도 들어가지 않는다.

사용: python -I -B -X utf8 call_worker.py <시나리오> [옵션] -- <작업자 실행 명령 …>
  시나리오
    normal    합성 시험 사진을 하나씩 프로토콜로 보내 읽는다(--dump 파일에 줄·확신도·상자를 남긴다. 작업자를 --eval 로 띄움)
    protocol  경계 시험 한 벌: 정상·빈 사진·아주 작은 사진·너무 큰 입력·크기 불일치·거대한 거짓 머리·잘못된 JSON·모르는 종류·잘못된 형식·EOF·bye·취소(프로세스 종료)·시간 초과·RGB/BGR 순서
    measure   (시작 시간·사진당 시간·최대 메모리) 작업자를 새로 띄워 같은 사진을 읽는 것을 --runs 번 반복해 JSON 으로 남긴다
  공통 옵션: --images 아이디,아이디…(기본 합성 27장, big_ 제외) --max-side 960 --timeout 90 --out JSON파일 --dump 파일 --watch(네트워크 가드+연결 표본) --label 이름 --eval
작업자 명령 예: ocr_addon\\ocr_worker.exe   또는   venv_pack\\Scripts\\python.exe -I -B -X utf8 …\\tools\\pyrun.py …\\worker_main.py --home …\\assets
이 도구는 사진 경로를 작업자에 보내지 않는다(픽셀만). 합성 사진만 읽는다(운영자 사진은 이 도구로 읽지 않는다).
"""
import argparse
import json
import os
import queue
import statistics
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STAGEA = os.path.dirname(HERE)
PHOTOLAB = os.path.dirname(STAGEA)
for _p in (HERE, os.path.join(PHOTOLAB, "harness"), os.path.join(STAGEA, "tools"), os.path.join(PHOTOLAB, "stage0b", "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import protocol  # noqa: E402
import winproc  # noqa: E402
import imgprep  # noqa: E402

CREATE_NO_WINDOW = 0x08000000
TESTSET = os.path.join(PHOTOLAB, "testset", "images")


def log(m):
    sys.stdout.write("[call %s] %s\n" % (time.strftime("%H:%M:%S"), m))
    sys.stdout.flush()


def testset_ids(spec):
    if spec:
        return [x for x in spec.split(",") if x]
    return sorted(os.path.splitext(f)[0] for f in os.listdir(TESTSET) if f.endswith(".jpg") and not f.startswith("big_"))


class Worker:
    def __init__(self, cmd, eval_mode, stderr_path):
        self.cmd = list(cmd) + (["--eval"] if eval_mode else [])
        os.makedirs(os.path.dirname(os.path.abspath(stderr_path)), exist_ok=True)
        self.err = open(stderr_path, "ab")
        self.t_spawn = time.perf_counter()
        self.p = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.err, creationflags=CREATE_NO_WINDOW)
        self.pid = self.p.pid
        self.q = queue.Queue()
        self.mon = winproc.ProcMonitor(self.pid, 0.1)
        self.mon.start()
        self.tree_seen = set()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        f = self.p.stdout
        while True:
            try:
                line = f.readline(protocol.MAX_RESPONSE_BYTES + 2)
            except (OSError, ValueError):
                line = b""
            if not line:
                self.q.put(None)
                return
            self.q.put((time.perf_counter(), line))

    def get(self, timeout):
        """-> ('line', 시각, dict) | ('badline', 시각, 바이트) | ('eof',) | ('timeout',)"""
        try:
            item = self.q.get(timeout=timeout)
        except queue.Empty:
            return ("timeout",)
        if item is None:
            return ("eof",)
        t, line = item
        if len(line) > protocol.MAX_RESPONSE_BYTES or not line.endswith(b"\n"):
            return ("badline", t, line[:80])
        try:
            return ("line", t, protocol.loads_strict(line.rstrip(b"\r\n")))
        except Exception:
            return ("badline", t, line[:80])

    def send(self, data):
        self.p.stdin.write(data)
        self.p.stdin.flush()

    def wait_ready(self, timeout=150):
        r = self.get(timeout)
        if r[0] != "line":
            return None, r[0]
        try:
            protocol.validate_ready(r[2])
        except protocol.ProtocolError as e:
            return None, "bad_ready:" + e.detail
        return dict(r[2], start_s=round(r[1] - self.t_spawn, 3)), "ok"

    def request(self, rid, w, h, pix, timeout, opts=None, allow_eval=False):
        t0 = time.perf_counter()
        self.send(protocol.encode_request(rid, w, h, pix, size_name=str(max(w, h)), opts=opts))
        r = self.get(timeout)
        if r[0] == "line":
            try:
                protocol.validate_result(r[2], rid, allow_eval=allow_eval)
            except protocol.ProtocolError as e:
                return None, "invalid:" + e.detail, r[1] - t0
            return r[2], "ok", r[1] - t0
        return None, r[0], time.perf_counter() - t0

    def kill_tree(self):
        self.tree_seen |= set(winproc.tree_pids(self.pid))
        t0 = time.perf_counter()
        subprocess.run(["taskkill", "/PID", str(self.pid), "/T", "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return time.perf_counter() - t0

    def alive_pids(self):
        alive = {pid for pid, _, _ in winproc.list_processes()}
        return sorted(p for p in self.tree_seen | {self.pid} if p in alive)

    def finish(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.kill_tree()
        self.mon.stop()
        summ = self.mon.summary()
        self.mon.close()
        try:
            self.err.close()
        except Exception:
            pass
        return self.p.returncode, summ


def img_path(i):
    return os.path.join(TESTSET, i + ".jpg")


def run_images(wk, ids, max_side, timeout, collect_lines=False, start_id=1):
    rows = []
    for k, i in enumerate(ids):
        w, h, pix, info = imgprep.prepare_rgb(img_path(i), max_side)
        msg, status, sec = wk.request(start_id + k, w, h, pix, timeout, allow_eval=True)
        row = {"id": i, "w": w, "h": h, "status": status, "seconds": round(sec, 4)}
        if msg is not None and msg.get("t") == "result":
            row["n_lines"] = len(msg["lines"])
            row["ms"] = msg["ms"]
            row["net_attempts"] = msg["net_attempts"]
            if collect_lines:
                row["lines"] = msg["lines"]
        elif msg is not None:
            row["error_code"] = msg.get("code")
        rows.append(row)
    return rows


def scenario_normal(a, cmd):
    ids = testset_ids(a.images)
    wk = Worker(cmd, True, os.path.join(STAGEA, "logs", "worker_stderr_%s.txt" % (a.label or "normal")))
    ready, st = wk.wait_ready()
    log("ready: %s %s" % (st, ready and {k: ready[k] for k in ("engine", "load_s", "start_s") if k in ready}))
    rows = run_images(wk, ids, a.max_side, a.timeout, collect_lines=True) if ready else []
    try:
        wk.send(b'{"t":"bye"}\n')
    except Exception:
        pass
    rc, summ = wk.finish()
    res = {"scenario": "normal", "ready": ready, "ready_status": st, "exit_code": rc, "images": rows, "monitor": {k: summ[k] for k in ("peak_ws_mb_max_process", "peak_ws_mb_sum_of_peaks", "peak_commit_mb_max_process", "cpu_total_s")}}
    ok_n = sum(1 for r in rows if r["status"] == "ok" and "n_lines" in r)
    log("normal: 이미지 %d장 중 정상 %d장, 종료 코드 %s, 최대 메모리 %s MB" % (len(rows), ok_n, rc, summ["peak_ws_mb_max_process"]))
    return res


def scenario_measure(a, cmd):
    ids = testset_ids(a.images)
    runs = []
    for n in range(a.runs):
        wk = Worker(cmd, False, os.path.join(STAGEA, "logs", "worker_stderr_%s.txt" % (a.label or "measure")))
        ready, st = wk.wait_ready()
        if not ready:
            runs.append({"run": n + 1, "error": st})
            wk.kill_tree()
            wk.finish()
            continue
        rows = run_images(wk, ids, a.max_side, a.timeout)
        try:
            wk.send(b'{"t":"bye"}\n')
        except Exception:
            pass
        rc, summ = wk.finish()
        secs = [r["seconds"] for r in rows if r["status"] == "ok"]
        runs.append({"run": n + 1, "start_s": ready["start_s"], "worker_load_s": ready.get("load_s"), "worker_import_s": ready.get("import_s"), "first_image_s": secs[0] if secs else None,
                     "per_image_median_s": round(statistics.median(secs), 4) if secs else None, "per_image_mean_s": round(statistics.mean(secs), 4) if secs else None,
                     "per_image_max_s": max(secs) if secs else None, "n_ok": len(secs), "n_images": len(rows), "exit_code": rc,
                     "peak_ws_mb_max_process": summ["peak_ws_mb_max_process"], "peak_ws_mb_sum_of_peaks": summ["peak_ws_mb_sum_of_peaks"],
                     "peak_commit_mb_max_process": summ["peak_commit_mb_max_process"], "cpu_total_s": summ["cpu_total_s"],
                     "net_attempts_sum": sum(r.get("net_attempts", 0) for r in rows), "processes": [(p["exe"], p["peak_ws_mb"]) for p in summ["processes"] if p["counted"]]})
        log("측정 %d/%d: 시작 %.2fs, 사진 중앙 %.3fs, 최대 메모리 %s MB" % (n + 1, a.runs, ready["start_s"], runs[-1]["per_image_median_s"] or -1, summ["peak_ws_mb_max_process"]))
    return {"scenario": "measure", "label": a.label, "cmd": cmd, "n_images": len(ids), "max_side": a.max_side, "runs": runs}


def white(w, h):
    return b"\xff" * (w * h * 3)


def scenario_protocol(a, cmd):
    out = {"scenario": "protocol", "tests": []}

    def rec(name, ok, detail=""):
        out["tests"].append({"test": name, "ok": bool(ok), "detail": detail})
        log("%-34s %s %s" % (name, "통과" if ok else "★실패", detail))

    ids = testset_ids(a.images)
    sample = ids[0]
    w0, h0, pix0, _ = imgprep.prepare_rgb(img_path(sample), a.max_side)

    def fresh(eval_mode=False, tag="p"):
        wk = Worker(cmd, eval_mode, os.path.join(STAGEA, "logs", "worker_stderr_protocol_%s.txt" % tag))
        ready, st = wk.wait_ready()
        return wk, ready, st

    # 1 정상
    wk, ready, st = fresh(False, "1")
    rec("ready 신호(proto 번호·엔진 이름)", ready is not None and ready.get("proto") == 1 and "rapidocr" in (ready.get("engine") or ""), "start_s=%s load_s=%s engine=%s" % (ready and ready.get("start_s"), ready and ready.get("load_s"), ready and ready.get("engine")))
    msg, status, sec = wk.request(1, w0, h0, pix0, a.timeout)
    rec("정상 사진 한 장", msg is not None and msg["t"] == "result" and len(msg["lines"]) > 0 and msg["net_attempts"] == 0, "줄 %s개, %.3f초, 응답 키 %s" % (msg and len(msg["lines"]), sec, msg and sorted(msg)))
    if msg:
        sc = [k for ln in msg["lines"] for k in ln if k in ("score", "box")]
        rec("확신도·상자 점수는 기본 응답에 없다(설계 3-5)", not sc, "평가용 칸 %d개" % len(sc))
    # 2 같은 작업자에 이어서: 빈(흰) 사진, 검은 사진, 아주 작은 사진
    msg, status, sec = wk.request(2, 960, 720, white(960, 720), a.timeout)
    rec("빈(흰) 사진 -> 줄 0개", msg is not None and msg["t"] == "result" and msg["lines"] == [], "상태 %s, %.3f초" % (status, sec))
    msg, status, sec = wk.request(3, 960, 720, b"\x00" * (960 * 720 * 3), a.timeout)
    rec("검은 사진 -> 줄 0개", msg is not None and msg["t"] == "result" and msg["lines"] == [], "상태 %s" % status)
    for rid, (tw, th) in ((4, (1, 1)), (5, (5, 5)), (6, (1600, 8))):
        msg, status, sec = wk.request(rid, tw, th, white(tw, th), a.timeout)
        rec("아주 작은·가는 사진 %dx%d" % (tw, th), msg is not None and (msg["t"] == "result" or msg.get("code") == "engine") and wk.p.poll() is None, "응답 %s, 작업자 살아 있음 %s" % (msg and (msg["t"] if msg["t"] == "result" else msg.get("code")), wk.p.poll() is None))
    # 3 너무 큰 입력(상한 1600 초과, 본문은 끝까지 읽어 버리고 계속)
    big_w, big_h = 3000, 2000
    msg, status, sec = wk.request(7, big_w, big_h, white(big_w, big_h), 60)
    rec("너무 큰 입력 3000x2000 -> too_big, 작업자 계속", msg is not None and msg["t"] == "error" and msg["code"] == "too_big" and wk.p.poll() is None, "응답 %s" % (msg,))
    msg, status, sec = wk.request(8, w0, h0, pix0, a.timeout)
    rec("거절 뒤 정상 요청이 이어서 된다(스트림 맞음)", msg is not None and msg["t"] == "result" and len(msg["lines"]) > 0, "상태 %s" % status)
    # 4 크기 불일치(머리의 n 이 w*h*3 과 다름): 본문 n 바이트를 보내면 decode 오류 뒤 계속
    head = protocol.dumps_line({"t": "ocr", "id": 9, "w": 100, "h": 100, "fmt": "rgb24", "n": 29999})
    wk.send(head + b"\x00" * 29999)
    r = wk.get(30)
    rec("크기 불일치(n != w*h*3) -> decode, 계속", r[0] == "line" and r[2].get("code") == "decode" and wk.p.poll() is None, "응답 %s" % (r[2] if r[0] == "line" else r[0]))
    msg, status, sec = wk.request(10, w0, h0, pix0, a.timeout)
    rec("불일치 뒤 정상 요청", msg is not None and msg["t"] == "result", "상태 %s" % status)
    # 5 opts 는 --eval 이 아닐 때 거절
    wk.send(protocol.dumps_line({"t": "ocr", "id": 11, "w": 8, "h": 8, "fmt": "rgb24", "n": 192, "opts": {"text_score": 0.5}}) + b"\x00" * 192)
    r = wk.get(30)
    code = r[2].get("code") if r[0] == "line" else r[0]
    t_exit0 = time.perf_counter()
    try:
        wk.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    rec("opts 는 평가 모드가 아니면 거절(proto) 후 끝", code == "proto" and wk.p.poll() == 2, "응답 %s, 종료 코드 %s" % (code, wk.p.poll()))
    wk.finish()
    # 6 거대한 거짓 머리(n 이 64MB 초과): 본문을 보내지 않고 오류 뒤 종료(코드 4)
    wk, ready, st = fresh(False, "6")
    wk.send(protocol.dumps_line({"t": "ocr", "id": 12, "w": 960, "h": 720, "fmt": "rgb24", "n": 100 * 1024 * 1024}))
    r = wk.get(30)
    try:
        wk.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    rec("거짓 머리 n=100MB -> 오류 후 종료(코드 4)", r[0] == "line" and r[2].get("t") == "error" and wk.p.poll() == 4, "응답 %s, 종료 코드 %s" % (r[2] if r[0] == "line" else r[0], wk.p.poll()))
    wk.finish()
    # 7 잘못된 JSON·모르는 종류·잘못된 형식·정수 아닌 칸·NaN
    for name, raw in (("잘못된 JSON(글자)", b"this is not json\n"), ("모르는 t", b'{"t":"zzz"}\n'),
                      ("잘못된 형식 fmt=bgr24", protocol.dumps_line({"t": "ocr", "id": 1, "w": 4, "h": 4, "fmt": "bgr24", "n": 48})),
                      ("id 가 문자열", b'{"t":"ocr","id":"x","w":4,"h":4,"fmt":"rgb24","n":48}\n'),
                      ("NaN 숫자", b'{"t":"ocr","id":1,"w":NaN,"h":4,"fmt":"rgb24","n":48}\n'),
                      ("모르는 칸 path(경로를 넘기려는 시도)", b'{"t":"ocr","id":1,"w":4,"h":4,"fmt":"rgb24","n":48,"path":"C:/x.jpg"}\n')):
        wk, ready, st = fresh(False, "7")
        wk.send(raw)
        r = wk.get(30)
        try:
            wk.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        rec("%s -> proto 오류 후 종료(코드 2)" % name, r[0] == "line" and r[2].get("code") == "proto" and wk.p.poll() == 2, "응답 %s, 종료 코드 %s" % (r[2] if r[0] == "line" else r[0], wk.p.poll()))
        wk.finish()
    # 8 너무 긴 머리 줄(2048 초과)
    wk, ready, st = fresh(False, "8")
    wk.send(b"{" + b" " * 5000 + b"}\n")
    r = wk.get(30)
    try:
        wk.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    rec("머리 줄이 너무 길다 -> proto 오류 후 종료", r[0] == "line" and r[2].get("code") == "proto" and wk.p.poll() == 2, "종료 코드 %s" % wk.p.poll())
    wk.finish()
    # 9 bye / EOF
    wk, ready, st = fresh(False, "9")
    wk.send(b'{"t":"bye"}\n')
    r = wk.get(10)
    try:
        wk.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    rec("bye -> bye 응답 후 정상 종료(0)", r[0] == "line" and r[2].get("t") == "bye" and wk.p.poll() == 0, "종료 코드 %s" % wk.p.poll())
    wk.finish()
    wk, ready, st = fresh(False, "9b")
    t0 = time.perf_counter()
    wk.p.stdin.close()
    r = wk.get(10)
    try:
        wk.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    rec("표준 입력 닫힘(EOF) -> 정상 종료(0)", wk.p.poll() == 0, "종료 코드 %s, %.2f초" % (wk.p.poll(), time.perf_counter() - t0))
    wk.finish()
    # 10 본문 도중 입력이 닫힘(취소 흉내): 응답 없이 끝, 코드 3
    wk, ready, st = fresh(False, "10")
    wk.send(protocol.dumps_line({"t": "ocr", "id": 13, "w": 960, "h": 720, "fmt": "rgb24", "n": 960 * 720 * 3}) + pix0[:1000])
    wk.p.stdin.close()
    try:
        wk.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    rec("본문 도중 입력 닫힘 -> 응답 없이 종료(3)", wk.p.poll() == 3, "종료 코드 %s" % wk.p.poll())
    wk.finish()
    # 11 취소(프로세스 나무 종료): 읽는 도중에 죽이고, 남는 프로세스 0·바로 새로 시작이 되는지
    wk, ready, st = fresh(False, "11")
    wk.send(protocol.encode_request(14, w0, h0, pix0))
    time.sleep(0.08)
    lat = wk.kill_tree()
    left = wk.alive_pids()
    rec("취소: 읽는 도중 프로세스 나무 종료, 남은 프로세스 0", wk.p.poll() is not None and not left, "종료까지 %.3f초, 종료 코드 %s, 남은 pid %s" % (lat, wk.p.poll(), left))
    r = wk.get(2)
    rec("취소 뒤 응답은 오지 않는다(파이프 닫힘)", r[0] in ("eof", "timeout"), "받은 것 %s" % (r[0],))
    wk.finish()
    wk, ready, st = fresh(False, "11b")
    msg, status, sec = wk.request(15, w0, h0, pix0, a.timeout)
    rec("취소 뒤 새 작업자가 바로 정상 동작", msg is not None and msg["t"] == "result", "시작 %.2fs, 상태 %s" % (ready["start_s"] if ready else -1, status))
    wk.send(b'{"t":"bye"}\n')
    wk.finish()
    # 12 시간 초과: 부모가 짧은 제한(0.12초)을 걸고 응답이 없으면 나무를 종료한다
    wk, ready, st = fresh(False, "12")
    msg, status, sec = wk.request(16, w0, h0, pix0, 0.12)
    timed_out = (status == "timeout")
    lat = wk.kill_tree() if timed_out else 0.0
    left = wk.alive_pids()
    rec("시간 초과(0.12초 제한) -> 나무 종료·남은 프로세스 0", timed_out and wk.p.poll() is not None and not left, "상태 %s, 종료까지 %.3f초, 남은 pid %s" % (status, lat, left))
    wk.finish()
    wk, ready, st = fresh(False, "12b")
    msg, status, sec = wk.request(17, w0, h0, pix0, a.timeout)
    rec("시간 초과 뒤 새 작업자가 정상 동작", msg is not None and msg["t"] == "result", "상태 %s" % status)
    wk.send(b'{"t":"bye"}\n')
    wk.finish()
    # 13 RGB/BGR: 같은 사진을 올바른 순서와 일부러 R<->B 를 바꾼 순서로 읽어 비교(평가 모드 — 확신도 포함)
    wk, ready, st = fresh(True, "13")
    ok_all, diffs = True, []
    probes = list(ids[:6]) + ["__color__"]
    for k, i in enumerate(probes):
        if i == "__color__":
            from PIL import Image, ImageDraw, ImageFont
            im = Image.new("RGB", (640, 220), (190, 30, 30))
            ImageDraw.Draw(im).text((30, 60), "COLOR TEST 777", fill=(30, 30, 190), font=ImageFont.load_default(size=60))
            w, h, pix = 640, 220, im.tobytes()
        else:
            w, h, pix, _ = imgprep.prepare_rgb(img_path(i), a.max_side)
        good, _, _ = wk.request(100 + k * 2, w, h, pix, a.timeout, allow_eval=True)
        sw = bytearray(pix)
        sw[0::3], sw[2::3] = pix[2::3], pix[0::3]                      # R<->B 교환(잘못된 순서)
        bad, _, _ = wk.request(101 + k * 2, w, h, bytes(sw), a.timeout, allow_eval=True)
        gt = [(l["text"], l.get("score")) for l in (good or {}).get("lines", [])]
        bt = [(l["text"], l.get("score")) for l in (bad or {}).get("lines", [])]
        diffs.append({"image": "(색 시험 그림)" if i == "__color__" else i, "same_text": [t for t, _ in gt] == [t for t, _ in bt], "same_text_and_score": gt == bt, "n_good": len(gt), "n_swapped": len(bt)})
    n_diff = sum(1 for d in diffs if not d["same_text_and_score"])
    rec("RGB/BGR: 올바른 순서 대 R<->B 교환 결과를 비교(교환하면 달라지는가)", True, "비교 %d장 중 확신도·글까지 같은 것 %d장(교환해도 같음), 다른 것 %d장 — %s" % (len(diffs), len(diffs) - n_diff, n_diff, [("색 시험 그림" if d["image"].startswith("(") else "합성") + (":다름" if not d["same_text_and_score"] else ":같음") for d in diffs]))
    out["rgb_bgr_probe"] = diffs
    wk.send(b'{"t":"bye"}\n')
    wk.finish()
    out["all_ok"] = all(t["ok"] for t in out["tests"])
    log("프로토콜 시험 %d건 중 통과 %d건" % (len(out["tests"]), sum(1 for t in out["tests"] if t["ok"])))
    return out


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        print(__doc__)
        return 2
    k = argv.index("--")
    cmd = argv[k + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=("normal", "protocol", "measure"))
    ap.add_argument("--images", default="")
    ap.add_argument("--max-side", type=int, default=960)
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dump", default=None)
    ap.add_argument("--label", default="")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--eval", action="store_true")
    a = ap.parse_args(argv[:k])
    watch = None
    if a.watch:
        import netwatch
        watch = netwatch.Watch("callworker_%s_%s" % (a.scenario, a.label or "x"), os.path.join(STAGEA, "logs", "netwatch"))
    res = {"normal": scenario_normal, "protocol": scenario_protocol, "measure": scenario_measure}[a.scenario](a, cmd)
    if watch:
        res["network"] = watch.finish()
        log("네트워크: %s" % res["network"])
    if a.dump and res.get("images"):
        with open(a.dump, "w", encoding="utf-8") as f:
            json.dump({"label": a.label, "ready": res.get("ready"), "images": [{"id": r["id"], "w": r["w"], "h": r["h"], "lines": r.get("lines", [])} for r in res["images"]]}, f, ensure_ascii=False)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return 0 if res.get("all_ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
