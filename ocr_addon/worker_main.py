# -*- coding: utf-8 -*-
"""worker_main.py - 글자 읽기 작업자(추가 도구)의 진입 파일(설계서 3절). 표준 입출력 프로토콜은 protocol.py.

첫 문장은 소켓 가드(netguard) 설치다 — rapidocr·onnxruntime·cv2 를 가져오기 전에, 설치에 실패하면 시작하지 않는다(fail closed).
그다음: 표준 출력을 따로 복제한 핸들로 옮기고 sys.stdout 은 버린다(라이브러리의 print 가 JSON 줄을 오염시키지 못하게) -> 모델 두 개를 미리 올림 -> ready -> 요청을 한 장씩 처리.
경로·EXIF 는 받지 않는다(픽셀 RGB 와 크기뿐). 파일을 쓰지 않는다. 네트워크 시도(가드가 센 횟수)가 한 번이라도 생기면 error net_blocked 를 보내고 끝낸다.
옵션(앱은 쓰지 않는다): --home DIR(동결 안 한 시험 실행에서만 모델 위치를 정한다. 동결본은 실행 파일 폴더 고정) · --threads N(기본 2) · --eval(응답 줄에 score·box 를 더하고 opts 를 받는다) ·
                     --selftest(가드 음성 대조·가져오기·모델/사전 크기 확인·합성 점검 이미지 읽기를 하고 JSON 한 줄을 낸다) · --version.
"""
# ── 소켓 가드: 반드시 첫 문장(다른 가져오기보다 먼저) ───────────────────────────────────────────────
try:
    import netguard as _netguard
    _netguard.install()
    if not _netguard.ACTIVE:
        raise RuntimeError("netguard 가 켜지지 않았다")
except BaseException as _e:                            # fail closed — 가드 없이는 시작하지 않는다
    import os as _os
    import sys as _sys
    try:
        _sys.stderr.write("ocr_worker: 소켓 가드 적재 실패 (%s)\n" % type(_e).__name__)
    except Exception:
        pass
    _os._exit(70)

import hashlib
import json
import os
import sys
import time

# 라이브러리 환경(가져오기 전에): 오프라인·텔레메트리 끄기·OpenCL 끄기. 앱도 같은 값을 환경 변수로 주지만 작업자 스스로도 건다.
for _k, _v in (("HF_HUB_OFFLINE", "1"), ("DO_NOT_TRACK", "1"), ("ORT_DISABLE_TELEMETRY", "1"), ("OPENCV_OPENCL_RUNTIME", "disabled"),
               ("PYTHONDONTWRITEBYTECODE", "1"), ("PYTHONUTF8", "1")):
    os.environ[_k] = _v

import protocol  # noqa: E402  (표준 라이브러리만)

EXIT_PROTO, EXIT_IO, EXIT_BIG, EXIT_NET, EXIT_START = 2, 3, 4, 5, 6
MODEL_REL = {"det": os.path.join("models", "det", "inference.onnx"), "rec": os.path.join("models", "rec", "inference.onnx"),
             "dict": os.path.join("data", "ppocrv5_korean_dict.txt")}
# 모델·사전의 기대 크기(설계서 5-3·5-4 — 앱은 SHA-256 도 소스 상수로 박는다. 작업자는 selftest 에서 둘 다 확인).
EXPECT = {"det": (4826518, "a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d"),
          "rec": (13418787, "92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08"),
          "dict": (47451, "a88071c68c01707489baa79ebe0405b7beb5cca229f4fc94cc3ef992328802d7")}


def addon_home(home_arg):
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))       # 동결본은 실행 파일 폴더 고정(위치를 바꾸는 길 없음)
    return os.path.abspath(home_arg) if home_arg else os.path.dirname(os.path.abspath(__file__))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def files_ok(home, check_hash):
    """모델 2개·사전의 존재·크기(·해시) 확인. 반환 (통과 여부, 자세한 dict)."""
    res, ok = {}, True
    for k, rel in MODEL_REL.items():
        p = os.path.join(home, rel)
        size_ok = os.path.isfile(p) and os.path.getsize(p) == EXPECT[k][0]
        hash_ok = None
        if check_hash and size_ok:
            hash_ok = (sha256_file(p) == EXPECT[k][1])
        res[k] = {"size_ok": bool(size_ok), "sha256_ok": hash_ok}
        ok = ok and size_ok and (hash_ok in (None, True))
    return ok, res


def setup_io():
    """프로토콜 출력용 핸들(표준 출력의 복제)을 만들고 fd 1·sys.stdout 은 NUL 로 돌린다. 반환: 쓰기 파일 객체(바이너리, 버퍼 없음)."""
    fd_out = os.dup(1)
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(fd_out, os.O_BINARY)
        msvcrt.setmode(0, os.O_BINARY)
    nul = os.open(os.devnull, os.O_WRONLY)
    os.dup2(nul, 1)
    os.close(nul)
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    return os.fdopen(fd_out, "wb", buffering=0)


def build_engine(home, threads):
    """모델·사전은 항상 home 아래 로컬 파일. 스레드는 intra 2·inter 1(기본 -1 은 코어를 다 쓰려 해서 오히려 느리다 — 2단계 M 보충)."""
    t0 = time.perf_counter()
    import onnxruntime as ort
    ort.disable_telemetry_events()                         # 윈도 이벤트 추적(ETW) 텔레메트리를 끄는 문서화된 호출(효과는 OS 쪽에서 증명 못 함)
    import numpy  # noqa: F401
    import cv2  # noqa: F401
    from rapidocr.main import RapidOCR                     # rapidocr/__init__ 의 지연 가져오기를 거치지 않는 정적 가져오기(동결 때 분석에 보이게)
    import_s = time.perf_counter() - t0
    params = {
        "Global.use_cls": False,                           # 방향 분류 끔(U16)
        "Global.max_side_len": 8192,                       # 엔진이 먼저 줄이지 않게(검출 상한은 아래 Det.limit_*)
        "Global.log_level": "error",                       # 라이브러리 로그(표준 오류)를 줄인다
        "EngineConfig.onnxruntime.intra_op_num_threads": int(threads),
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Det.model_path": os.path.join(home, MODEL_REL["det"]),
        "Det.limit_type": "max",
        "Det.limit_side_len": protocol.MAX_LONG_SIDE,      # 앱이 960(또는 1600)으로 줄여 보내므로 엔진은 더 줄이지 않는다
        "Rec.model_path": os.path.join(home, MODEL_REL["rec"]),
        "Rec.rec_keys_path": os.path.join(home, MODEL_REL["dict"]),
    }
    eng = RapidOCR(params=params)
    for name in ("_load_det_model", "_load_rec_model"):     # 게으른 불러오기를 앞당긴다(ready 전에 모델 2개를 올린다)
        fn = getattr(eng, name, None)
        if fn is not None:
            fn()
    return eng, import_s, ort.__version__


def engine_label(ort_version):
    try:
        import buildinfo
        rv = buildinfo.VERSIONS.get("rapidocr", "?")
    except Exception:
        rv = "?"
    return "rapidocr-%s+ort-%s" % (rv, ort_version)


def lines_from_output(res, w, h, eval_mode):
    """RapidOCR 출력 -> 프로토콜 줄 목록(정규화 좌표 cx·cy·h). 글자가 하나도 없으면 빈 목록."""
    txts = getattr(res, "txts", None)
    if not txts:
        return [], 0
    boxes = getattr(res, "boxes", None)
    scores = getattr(res, "scores", None)
    out, dropped = [], 0
    for i, t in enumerate(txts):
        t = (t or "").strip()
        if not t:
            dropped += 1
            continue
        if len(t) > protocol.MAX_LINE_CHARS:
            t = t[:protocol.MAX_LINE_CHARS]
        b = boxes[i] if boxes is not None and i < len(boxes) else None
        cx = cy = hh = 0.0
        if b is not None:
            xs = [float(p[0]) for p in b]
            ys = [float(p[1]) for p in b]
            cx = min(max(sum(xs) / len(xs) / w, 0.0), 1.0)
            cy = min(max(sum(ys) / len(ys) / h, 0.0), 1.0)
            # 줄 높이 = 왼쪽·오른쪽 변 길이의 평균(기울어진 상자도 높이로). 넘파이 숫자가 JSON 에 섞이지 않게 파이썬 float 로 바꾼다.
            left = ((xs[0] - xs[3]) ** 2 + (ys[0] - ys[3]) ** 2) ** 0.5
            right = ((xs[1] - xs[2]) ** 2 + (ys[1] - ys[2]) ** 2) ** 0.5
            hh = min(max((left + right) / 2.0 / h, 0.0), 1.0)
        ln = {"text": t, "cx": round(float(cx), 4), "cy": round(float(cy), 4), "h": round(float(hh), 4)}
        if eval_mode:
            ln["score"] = round(float(scores[i]), 4) if scores is not None and i < len(scores) else None
            ln["box"] = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in b] if b is not None else None
        out.append(ln)
        if len(out) >= protocol.MAX_LINES:
            dropped += len(txts) - i - 1
            break
    return out, dropped


def read_exact(stream, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(min(n - len(buf), 1 << 20))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def drain(stream, n):
    left = n
    while left > 0:
        chunk = stream.read(min(left, 1 << 20))
        if not chunk:
            return False
        left -= len(chunk)
    return True


def serve(eng, out, eval_mode):
    import numpy as np
    inp = sys.stdin.buffer

    def emit(obj):
        raw = protocol.dumps_line(obj)
        if len(raw) > protocol.MAX_RESPONSE_BYTES and obj.get("t") == "result":    # 한도 안으로: 뒤의 줄부터 버린다
            lines = obj["lines"]
            while lines and len(raw) > protocol.MAX_RESPONSE_BYTES:
                del lines[max(1, len(lines) // 2):]
                obj["trunc"] = True
                raw = protocol.dumps_line(obj)
        out.write(raw)

    while True:
        line = inp.readline(protocol.MAX_HEADER_BYTES + 2)
        if not line:
            emit({"t": "bye"})                                                     # 표준 입력이 닫혔다(앱 종료) — 조용히 끝
            return 0
        if not line.endswith(b"\n"):
            emit({"t": "error", "id": None, "code": "proto"})
            return EXIT_PROTO
        try:
            msg = protocol.parse_header(line.rstrip(b"\r\n"))
        except protocol.ProtocolError:
            emit({"t": "error", "id": None, "code": "proto"})
            return EXIT_PROTO                                                      # 스트림을 믿을 수 없다 — 끝내고 앱이 새로 띄운다
        if msg["t"] == "bye":
            emit({"t": "bye"})
            return 0
        rid = msg["id"]
        if msg.get("opts") is not None and not eval_mode:
            emit({"t": "error", "id": rid, "code": "proto"})
            return EXIT_PROTO
        code = protocol.check_dims(msg)
        if code:
            n = msg["n"]
            if 0 <= n <= protocol.DRAIN_LIMIT_BYTES:
                if not drain(inp, n):
                    return EXIT_IO
                emit({"t": "error", "id": rid, "code": code})
                continue
            emit({"t": "error", "id": rid, "code": code})
            return EXIT_BIG
        pixels = read_exact(inp, msg["n"])
        if pixels is None:
            return EXIT_IO                                                         # 본문 도중에 닫힘(취소) — 응답 없이 끝
        w, h = msg["w"], msg["h"]
        t0 = time.perf_counter()
        try:
            arr = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 3)
            arr = np.ascontiguousarray(arr[:, :, ::-1])                            # RGB -> BGR (엔진은 OpenCV 순서)
            opts = msg.get("opts") or {}
            res = eng(arr, **{k: float(v) for k, v in opts.items()})
            lines, dropped = lines_from_output(res, w, h, eval_mode)
            el = getattr(res, "elapse_list", None) or []
        except Exception:
            emit({"t": "error", "id": rid, "code": "engine"})
            continue
        finally:
            pixels = None
            arr = None
        if _netguard.attempts() > 0:                                               # 네트워크 시도가 한 번이라도 있었다 — 이 응답은 버리고 끝낸다
            emit({"t": "error", "id": rid, "code": "net_blocked"})
            return EXIT_NET
        try:
            total_ms = int(round((time.perf_counter() - t0) * 1000))
            ms = {"det": int(round(float(el[0] or 0) * 1000)) if len(el) > 0 else 0,
                  "rec": int(round(float(el[2] or 0) * 1000)) if len(el) > 2 else 0, "total": total_ms}
            resp = {"t": "result", "id": rid, "lines": lines, "ms": ms, "net_attempts": 0}
            if dropped:
                resp["dropped"] = int(dropped)
            emit(resp)
        except (TypeError, ValueError):                                            # 응답을 만들 수 없는 값 — 죽지 말고 오류 응답
            emit({"t": "error", "id": rid, "code": "engine"})


def selftest(home, threads):
    """가드 음성 대조·가져오기·파일 크기/해시·합성 점검 이미지 읽기. JSON 한 줄을 표준 출력으로 낸다(프로토콜 모드가 아님)."""
    import socket
    rep = {"python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False)), "home_is_exe_dir": None}
    rep["guard_active"] = bool(_netguard.ACTIVE)
    # (1) 음성 대조: 가드가 켜진 채 일부러 네트워크 시도를 만든다 — 모두 막혀 횟수에 잡혀야 한다(문서화된 시험용 주소 192.0.2.1·198.51.100.7·203.0.113.9 와 .invalid 이름 — 패킷은 나가지 않는다)
    _netguard.reset_counts()
    probes = []
    for name, fn in (("getaddrinfo(.invalid 이름)", lambda: socket.getaddrinfo("ocr-selftest.invalid", 80)),
                     ("create_connection(TEST-NET-3)", lambda: socket.create_connection(("203.0.113.9", 80), timeout=0.3)),
                     ("socket.connect(TEST-NET-2)", lambda: socket.socket().connect(("198.51.100.7", 9))),
                     ("socket.connect_ex(TEST-NET-1)", lambda: socket.socket().connect_ex(("192.0.2.1", 9))),
                     ("gethostbyname(.invalid 이름)", lambda: socket.gethostbyname("ocr-selftest2.invalid"))):
        before = _netguard.attempts()
        try:
            r = fn()
            outcome = "반환 %r" % (r,)
        except BaseException as e:
            outcome = type(e).__name__
        probes.append({"probe": name, "blocked_and_counted": _netguard.attempts() == before + 1, "outcome": outcome})
    rep["negative_control"] = probes
    rep["negative_control_attempts"] = _netguard.attempts()
    st = _netguard.stats()
    rep["negative_control_recent_targets_only_test_addresses"] = all(("203.0.113." in t or "198.51.100." in t or "192.0.2." in t or ".invalid" in t) for _a, t in st["recent"])
    # 루프백은 통과(닫힌 포트 9 라 연결은 거절되지만 가드 횟수에는 안 잡힌다)
    before = _netguard.attempts()
    try:
        socket.create_connection(("127.0.0.1", 9), timeout=0.3)
    except OSError:
        pass
    rep["loopback_not_counted"] = (_netguard.attempts() == before)
    _netguard.reset_counts()
    # (2) 파일
    ok, det = files_ok(home, True)
    rep["files_ok"], rep["files"] = ok, det
    if not ok:
        rep["error"] = "모델·사전 파일 확인 실패"
        print(json.dumps(rep, ensure_ascii=True))
        return EXIT_START
    # (3) 가져오기(동결 때 빠진 모듈을 바로 알아내려고 쓰는 것을 불러 본다). 필수: 작업자가 실제로 쓰는 것. 선택: 휠 21개에는 있으나 작업자 경로에서 안 쓰여 묶이지 않아도 되는 것
    required = ("numpy", "cv2", "onnxruntime", "yaml", "shapely", "shapely.geometry", "pyclipper", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "omegaconf", "colorlog", "tqdm", "requests")
    optional = ("google.protobuf", "flatbuffers", "packaging", "six", "urllib3", "certifi", "idna", "charset_normalizer", "colorama", "ssl", "multiprocessing", "asyncio", "hashlib")
    mods, opt = {}, {}
    for m in required + optional:
        try:
            mod = __import__(m, fromlist=["_"])
            (mods if m in required else opt)[m] = getattr(mod, "__version__", "ok")
        except BaseException as e:
            (mods if m in required else opt)[m] = ("FAIL " if m in required else "없음(묶이지 않음) ") + "%s: %s" % (type(e).__name__, str(e)[:100])
    rep["imports"] = mods
    rep["imports_optional"] = opt
    rep["imports_failed"] = [k for k, v in mods.items() if str(v).startswith("FAIL")]
    # (4) 엔진 + 합성 점검 이미지(글꼴 파일 없이 Pillow 내장 글꼴로 그린 영문·숫자) — 정상 읽기에서는 가드 시도가 0 이어야 한다
    t0 = time.perf_counter()
    eng, import_s, ortv = build_engine(home, threads)
    rep["load_s"] = round(time.perf_counter() - t0, 2)
    rep["engine"] = engine_label(ortv)
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    im = Image.new("RGB", (640, 220), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=56)
    dr.text((30, 25), "TEST 12345", fill=(0, 0, 0), font=font)
    dr.text((30, 115), "OCR WORKER", fill=(0, 0, 0), font=font)
    arr = np.ascontiguousarray(np.asarray(im)[:, :, ::-1])
    t1 = time.perf_counter()
    res = eng(arr)
    rep["read_ms"] = int(round((time.perf_counter() - t1) * 1000))
    got = [(t or "") for t in (getattr(res, "txts", None) or [])]
    rep["selfcheck_lines"] = len(got)
    norm = "".join(got).replace(" ", "").upper()
    rep["selfcheck_ok"] = ("TEST12345" in norm and "OCRWORKER" in norm)
    rep["guard_attempts_during_normal_read"] = _netguard.attempts()
    rep["ok"] = bool(rep["guard_active"] and rep["negative_control_attempts"] == 5 and all(p["blocked_and_counted"] for p in probes) and rep["loopback_not_counted"]
                     and rep["files_ok"] and not rep["imports_failed"] and rep["selfcheck_ok"] and rep["guard_attempts_during_normal_read"] == 0)
    print(json.dumps(rep, ensure_ascii=True))
    return 0 if rep["ok"] else EXIT_START


def main(argv):
    args = {"home": None, "threads": 2, "eval": False, "selftest": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--home" and i + 1 < len(argv):
            args["home"] = argv[i + 1]
            i += 1
        elif a == "--threads" and i + 1 < len(argv):
            args["threads"] = int(argv[i + 1])
            i += 1
        elif a == "--eval":
            args["eval"] = True
        elif a == "--selftest":
            args["selftest"] = True
        elif a == "--version":
            try:
                import buildinfo
                print(json.dumps({"proto": protocol.PROTO, "versions": buildinfo.VERSIONS}, ensure_ascii=False))
            except Exception:
                print(json.dumps({"proto": protocol.PROTO}))
            return 0
        else:
            sys.stderr.write("ocr_worker: 모르는 인자\n")
            return EXIT_PROTO
        i += 1
    home = addon_home(args["home"])
    if args["selftest"]:
        return selftest(home, args["threads"])
    out = setup_io()
    t0 = time.perf_counter()
    ok, _ = files_ok(home, False)                          # 시작 때는 존재·크기만(해시는 앱이 띄우기 전에 확인한다)
    if not ok:
        out.write(protocol.dumps_line({"t": "error", "id": None, "code": "engine"}))
        return EXIT_START
    try:
        eng, import_s, ortv = build_engine(home, args["threads"])
    except BaseException:
        out.write(protocol.dumps_line({"t": "error", "id": None, "code": "engine"}))
        return EXIT_START
    if _netguard.attempts() > 0:                           # 불러오는 동안 네트워크 시도가 있었다
        out.write(protocol.dumps_line({"t": "error", "id": None, "code": "net_blocked"}))
        return EXIT_NET
    ready = {"t": "ready", "proto": protocol.PROTO, "engine": engine_label(ortv), "load_s": round(time.perf_counter() - t0, 2),
             "import_s": round(import_s, 2), "pid": os.getpid()}
    if args["eval"]:
        ready["eval"] = True
    out.write(protocol.dumps_line(ready))
    return serve(eng, out, args["eval"])


if __name__ == "__main__":
    try:
        _code = main(sys.argv[1:])
    except BrokenPipeError:
        _code = EXIT_IO
    sys.exit(_code)
