# -*- coding: utf-8 -*-
"""protocol.py - 글자 읽기 작업자와 앱이 주고받는 표준 입출력 프로토콜(설계서 3-4·3-5). 표준 라이브러리만 쓰고 3.10 문법만 쓴다(앱과 작업자가 같은 글자를 쓰는지 시험이 두 쪽에서 가져와 견준다).

요청(앱 -> 작업자, 표준 입력, 바이트):
    한 줄 머리(JSON 한 개, UTF-8, 끝에 \\n)  +  픽셀 바이트 n 개(머리의 n)
    머리: {"t":"ocr","id":7,"w":960,"h":720,"fmt":"rgb24","n":2073600,"size":"960"}   n 은 반드시 w*h*3
    - 사진 경로·파일 이름·사진 번호·종류·메모·EXIF 는 한 글자도 넣지 않는다(픽셀과 크기뿐).
    - 픽셀은 앱이 메모리에서 방향을 적용해 긴 변 960(또는 1600) 이하로 줄인 RGB 24비트(줄 끝 패딩 없이 이어 붙임).
    - {"t":"bye"} 한 줄이면 작업자가 정리하고 끝낸다. 표준 입력이 닫혀도(EOF) 끝낸다.
    - 평가용(--eval 로 띄운 작업자만): 머리에 "opts":{"text_score":0.5,"box_thresh":0.5,"unclip_ratio":1.6} 를 더할 수 있다(범위 검사).
응답(작업자 -> 앱, 표준 출력, 한 줄에 JSON 하나, UTF-8):
    {"t":"ready","proto":1,"engine":"rapidocr-3.10.0+ort-1.31.1","load_s":2.1}
    {"t":"result","id":7,"lines":[{"text":"…","cx":0.31,"cy":0.22,"h":0.04}],"ms":{"det":340,"rec":860},"net_attempts":0}
    {"t":"error","id":7,"code":"decode|too_big|engine|net_blocked|proto"}
    {"t":"bye"}
    - 좌표(cx·cy·h)는 0–1 로 정규화한 숫자뿐이고 줄 합치기·정렬에만 쓴다. 확신도 점수는 보내지 않는다(--eval 일 때만 line 에 score·box 를 더한다).
    - 응답 한 줄은 256KB 이하·줄 200개 이하·줄당 400자 이하. 표준 출력은 이 JSON 줄 전용이고 표준 오류 내용은 앱이 버린다.
앱은 응답 전체를 '데이터' 로만 다룬다: validate_result() 가 알려진 칸만·형식·NaN/Infinity 거절·한도·요청 번호 일치를 본다. 어긋나면 응답 전체를 버리고 '예상 밖' 으로 처리한다.
"""
import json
import math

PROTO = 1
FMT_RGB24 = "rgb24"
MAX_LONG_SIDE = 1600                                  # 작업자가 받는 긴 변 상한(앱은 960 또는 1600 을 보낸다)
MAX_REQUEST_BYTES = MAX_LONG_SIDE * MAX_LONG_SIDE * 3
MAX_HEADER_BYTES = 2048
DRAIN_LIMIT_BYTES = 64 * 1024 * 1024                  # 거절할 요청의 본문을 읽어 버릴 상한(넘으면 작업자가 끝낸다 — 스트림을 다시 맞출 수 없다)
MAX_LINES = 200
MAX_LINE_CHARS = 400
MAX_RESPONSE_BYTES = 256 * 1024
ERROR_CODES = ("decode", "too_big", "engine", "net_blocked", "proto")
OPT_RANGES = {"text_score": (0.0, 1.0), "box_thresh": (0.0, 1.0), "unclip_ratio": (0.5, 4.0)}

_RESULT_KEYS = {"t", "id", "lines", "ms", "net_attempts", "trunc", "dropped"}
_LINE_KEYS = {"text", "cx", "cy", "h", "score", "box"}
_READY_KEYS = {"t", "proto", "engine", "load_s", "import_s", "pid", "eval", "home_ok"}


class ProtocolError(Exception):
    def __init__(self, code, detail=""):
        super().__init__("%s: %s" % (code, detail))
        self.code = code
        self.detail = detail


def _bad_constant(name):
    raise ValueError("JSON 에 %s 는 쓸 수 없다" % name)


def loads_strict(raw):
    """바이트/문자열 -> JSON 값. NaN·Infinity·-Infinity 는 거절한다."""
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")
    try:
        return json.loads(raw, parse_constant=_bad_constant)
    except RecursionError:
        raise ValueError("JSON 이 너무 깊게 겹쳐 있다") from None


def _num_default(o):
    """넘파이 숫자처럼 float 로 바꿀 수 있는 것만 숫자로 쓴다(그 밖의 형식은 거절)."""
    if hasattr(o, "__float__"):
        return float(o)
    raise TypeError("JSON 으로 쓸 수 없는 형식: %s" % type(o).__name__)


def dumps_line(obj):
    """한 줄 JSON(끝에 \\n) 바이트. 한글은 그대로(UTF-8), NaN 은 허용하지 않는다."""
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=_num_default) + "\n").encode("utf-8")


def encode_request(req_id, w, h, pixels, size_name=None, opts=None):
    """앱 쪽: 요청 바이트(머리 한 줄 + 픽셀)."""
    if len(pixels) != w * h * 3:
        raise ValueError("픽셀 길이가 w*h*3 과 다르다")
    head = {"t": "ocr", "id": int(req_id), "w": int(w), "h": int(h), "fmt": FMT_RGB24, "n": len(pixels)}
    if size_name is not None:
        head["size"] = str(size_name)
    if opts:
        head["opts"] = dict(opts)
    return dumps_line(head) + bytes(pixels)


def parse_header(line):
    """작업자 쪽: 머리 한 줄(바이트) -> dict. 형식이 어긋나면 ProtocolError('proto'). 크기 검사는 check_dims 가 따로(거절 코드가 다르다)."""
    if len(line) > MAX_HEADER_BYTES:
        raise ProtocolError("proto", "머리가 너무 길다")
    try:
        msg = loads_strict(line)
    except (ValueError, UnicodeDecodeError) as e:
        raise ProtocolError("proto", "JSON 아님: %s" % type(e).__name__)
    if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
        raise ProtocolError("proto", "머리는 t 가 있는 객체여야 한다")
    if msg["t"] == "bye":
        return msg
    if msg["t"] != "ocr":
        raise ProtocolError("proto", "모르는 t")
    for k in ("id", "w", "h", "n"):
        v = msg.get(k)
        if isinstance(v, bool) or not isinstance(v, int):
            raise ProtocolError("proto", "%s 는 정수여야 한다" % k)
    if msg.get("fmt") != FMT_RGB24:
        raise ProtocolError("proto", "fmt 는 rgb24 만")
    allowed = {"t", "id", "w", "h", "n", "fmt", "size", "opts"}
    if set(msg) - allowed:
        raise ProtocolError("proto", "모르는 칸")
    opts = msg.get("opts")
    if opts is not None:
        if not isinstance(opts, dict):
            raise ProtocolError("proto", "opts 는 객체")
        for k, v in opts.items():
            rng = OPT_RANGES.get(k)
            if rng is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not (rng[0] <= v <= rng[1]):
                raise ProtocolError("proto", "opts 칸·값이 맞지 않는다")
    return msg


def check_dims(msg):
    """작업자 쪽: 크기 검사. 반환 None(통과) 또는 오류 코드('decode'|'too_big')."""
    w, h, n = msg["w"], msg["h"], msg["n"]
    if w <= 0 or h <= 0 or n != w * h * 3:
        return "decode"
    if max(w, h) > MAX_LONG_SIDE or n > MAX_REQUEST_BYTES:
        return "too_big"
    return None


def _num01(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0.0 <= v <= 1.0


def validate_result(msg, expected_id, allow_eval=False):
    """앱 쪽: 작업자 응답(dict) 검증. 통과하면 그대로, 어긋나면 ProtocolError('proto'). 응답 한 줄의 바이트 한도는 호출자가 readline 때 본다."""
    if not isinstance(msg, dict) or "t" not in msg:
        raise ProtocolError("proto", "객체가 아님")
    t = msg["t"]
    if t == "error":
        if msg.get("code") not in ERROR_CODES or set(msg) - {"t", "id", "code"}:
            raise ProtocolError("proto", "오류 응답 모양")
        return msg
    if t != "result":
        raise ProtocolError("proto", "모르는 t")
    if set(msg) - _RESULT_KEYS or msg.get("id") != expected_id:
        raise ProtocolError("proto", "칸 또는 요청 번호 불일치")
    lines = msg.get("lines")
    if not isinstance(lines, list) or len(lines) > MAX_LINES:
        raise ProtocolError("proto", "lines 한도")
    for ln in lines:
        if not isinstance(ln, dict) or set(ln) - _LINE_KEYS or not isinstance(ln.get("text"), str) or len(ln["text"]) > MAX_LINE_CHARS:
            raise ProtocolError("proto", "줄 모양·길이")
        if not allow_eval and set(ln) & {"score", "box"}:
            raise ProtocolError("proto", "평가용 칸이 왔다")
        for k in ("cx", "cy", "h"):
            if not _num01(ln.get(k)):
                raise ProtocolError("proto", "좌표는 0–1 숫자")
    ms = msg.get("ms")
    if not isinstance(ms, dict) or any((not isinstance(v, int)) or isinstance(v, bool) or v < 0 for v in ms.values()):
        raise ProtocolError("proto", "ms 모양")
    na = msg.get("net_attempts")
    if isinstance(na, bool) or not isinstance(na, int) or na < 0:
        raise ProtocolError("proto", "net_attempts 모양")
    return msg


def validate_ready(msg):
    if not isinstance(msg, dict) or msg.get("t") != "ready" or set(msg) - _READY_KEYS:
        raise ProtocolError("proto", "ready 모양")
    if msg.get("proto") != PROTO:
        raise ProtocolError("proto", "프로토콜 번호가 다르다")
    return msg
