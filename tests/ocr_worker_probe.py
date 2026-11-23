"""진짜 작업자 소스(`ocr_addon/worker_main.py`·`netguard.py`·`protocol.py`)를 파이썬으로 띄우되 **엔진 자리에만 가짜를 끼우는 시험 전용 실행기**(시험이 아니다 — 결정 D-512, 시험 계획 T-G(1)). 순수 파이썬(표준 라이브러리만)이다.

왜 안전한가(가장 위험이 작은 길로 골랐다):
  · 이 파일은 `tests/` 에만 있고 앱 묶음·동결 작업자에는 들어가지 않는다 — 동결본에는 가짜를 끼울 길이 없다(`worker_main.py` 는 이 시험 때문에 한 글자도 바뀌지 않았다. 여기서는 불러온 모듈의 `build_engine`·`files_ok` 이름만 바꿔 끼운다).
  · 소켓 가드는 진짜와 똑같이 `worker_main` 을 가져오는 순간(첫 문장) 켜진다. 시험이 일부러 만드는 '바깥 연결 시도'는 모두 **패킷이 나갈 수 없는 주소**(`0.0.0.1` — '이 네트워크' 대역의 잘못된 목적지라 운영체제가 즉시 거절한다)이고,
    이름 풀이도 이름이 아니라 숫자 주소만 쓴다(DNS 질의가 나가지 않는다). 가드가 막기 전에는 시도 자체를 하지 않으므로, 가드를 일부러 망가뜨린 변이 시험에서도 실제 연결은 일어나지 않는다.
  · 루프백은 `127.0.0.1` 닫힌 포트 9 로만 시도한다(연결 거절 — 가드는 통과시키되 횟수로 세지 않는다).

실행: `python ocr_worker_probe.py --probe 방식 [--fakelib 폴더]`
방식(probe): 엔진을 가짜로 바꾸는 방식 — ok(글 두 줄) · raise(엔진이 예외) · many(300줄) · longline(1000자 한 줄) · emoji_big(4바이트 글자 200줄 x 400자 — 응답이 256KB 를 넘어 줄여 보내는 길) ·
  net_connect·net_connect_ex·net_create_connection·net_getaddrinfo·net_gethostbyname·net_sendto(바깥 시도 하나 — 막혀서 `net_blocked` 가 되어야 한다) · net_loopback(루프백만 — 통과하고 횟수에 안 잡힌다) ·
  net_raw_connect·net_raw_connect_ex·net_raw_sendto·net_raw_bind·net_raw_getaddrinfo·net_raw_gethostbyname(`_socket` 을 곧바로 쓰는 바깥 시도 하나 — 파이썬 래퍼는 못 보고 감사 훅이 막아 `net_blocked` 가 되어야 한다, 결정 D-587) · net_raw_count(그 여섯을 한꺼번에 시도하고 가드의 횟수를 글 한 줄로 알린다) ·
  stdout_noise(엔진이 fd 1 과 print 로 표준 출력에 글을 씀 — 프로토콜 줄이 안 더럽혀지는지) · net_count(바깥 셋·루프백 둘을 시도하고 가드의 횟수를 글 한 줄로 알려 준 뒤 횟수를 비운다) · startup_raise(엔진 만들기가 예외 — 시작 실패) ·
  import_time(엔진 자리를 안 바꾸고 진짜 `build_engine` 이 `--fakelib` 폴더의 가짜 라이브러리를 가져오게 한다 — 가짜 `onnxruntime` 이 가져오는 순간 바깥 시도를 한다: 가드를 첫 줄에서 켰는지 본다).
`worker_main.main` 은 그대로 부른다(표준 입출력 약속·종료 코드도 진짜 그대로다). 숫자 배열 라이브러리가 없어도 돌도록 `serve` 가 쓰는 만큼만 흉내 낸 가짜 `numpy` 를 끼운다.
"""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HERE), "ocr_addon")
sys.path.insert(0, ADDON)


def arg(name, default=None):
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


PROBE = arg("--probe", "ok")
FAKELIB = arg("--fakelib")

import worker_main as wm  # noqa: E402  (진짜 작업자 — 이 가져오기에서 소켓 가드가 켜진다. 실패하면 종료 코드 70)

BAD_HOST = "0.0.0.1"               # 패킷이 나갈 수 없는 잘못된 목적지(숫자 주소 — 이름 풀이도 안 한다)


class FakeArray:
    def __init__(self, size):
        self.size = size

    def reshape(self, *shape):
        return self

    def __getitem__(self, item):
        return self


fake_numpy = types.ModuleType("numpy")
fake_numpy.uint8 = "uint8"
fake_numpy.frombuffer = lambda buffer, dtype=None: FakeArray(len(buffer))
fake_numpy.ascontiguousarray = lambda array: array


def output(lines):
    box = [[0, 0], [100, 0], [100, 20], [0, 20]]
    return types.SimpleNamespace(txts=list(lines), boxes=[box for _ in lines], scores=[0.9 for _ in lines], elapse_list=[0.01, 0.0, 0.02])


def attempt(call):
    try:
        call()
    except Exception:                              # 막혀서 나는 PermissionError·gaierror·운영체제의 거절 — 무엇이든 삼킨다(세는 것은 가드의 몫)
        pass


RAW_KINDS = ("raw_connect", "raw_connect_ex", "raw_sendto", "raw_bind", "raw_getaddrinfo", "raw_gethostbyname")


def raw_attempt(kind):
    """`socket` 모듈의 래퍼를 거치지 않고 `_socket`(C 모듈)을 곧바로 쓰는 시도 — 파이썬 래퍼는 이 길을 못 보고 감사 훅 한 겹만 본다(감사 OCR-S1 R5, 결정 D-587). 주소는 모두 패킷이 나갈 수 없는 `0.0.0.1` 이다."""
    import _socket
    if kind == "raw_connect":
        attempt(lambda: _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM).connect((BAD_HOST, 9)))
    elif kind == "raw_connect_ex":
        attempt(lambda: _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM).connect_ex((BAD_HOST, 9)))
    elif kind == "raw_sendto":
        attempt(lambda: _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM).sendto(b"x", (BAD_HOST, 9)))
    elif kind == "raw_bind":
        attempt(lambda: _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM).bind((BAD_HOST, 0)))
    elif kind == "raw_getaddrinfo":
        attempt(lambda: _socket.getaddrinfo(BAD_HOST, 80))
    elif kind == "raw_gethostbyname":
        attempt(lambda: _socket.gethostbyname(BAD_HOST))


def blocked_attempt(kind):
    import socket
    if kind in RAW_KINDS:
        raw_attempt(kind)
    elif kind == "connect":
        attempt(lambda: socket.socket().connect((BAD_HOST, 9)))
    elif kind == "connect_ex":
        attempt(lambda: socket.socket().connect_ex((BAD_HOST, 9)))
    elif kind == "create_connection":
        attempt(lambda: socket.create_connection((BAD_HOST, 9), timeout=0.2))
    elif kind == "getaddrinfo":
        attempt(lambda: socket.getaddrinfo(BAD_HOST, 80))
    elif kind == "gethostbyname":
        attempt(lambda: socket.gethostbyname(BAD_HOST))
    elif kind == "sendto":
        attempt(lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", (BAD_HOST, 9)))


def loopback_attempt():
    import socket
    attempt(lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.3))


class Engine:
    def __init__(self, behavior):
        self.behavior = behavior

    def __call__(self, array, **options):
        behavior = self.behavior
        if behavior == "raise":
            raise RuntimeError("가짜 엔진 오류")
        if behavior == "many":
            return output(["줄 %d" % n for n in range(300)])
        if behavior == "longline":
            return output(["가" * 1000])
        if behavior == "emoji_big":
            return output([chr(0x1F600) * 400 for _ in range(200)])
        if behavior.startswith("net_") and behavior[4:] in ("connect", "connect_ex", "create_connection", "getaddrinfo", "gethostbyname", "sendto") + RAW_KINDS:
            blocked_attempt(behavior[4:])
            return output(["바깥 시도 뒤의 글"])
        if behavior == "net_raw_count":
            for kind in RAW_KINDS:
                raw_attempt(kind)
            stats = wm._netguard.stats()
            text = json.dumps({"attempts": stats["attempts"], "loopback": stats["loopback"], "audit": stats["audit"], "apis": sorted({api for api, _target in stats["recent"]})}, ensure_ascii=True)
            wm._netguard.reset_counts()
            return output([text])
        if behavior == "net_loopback":
            loopback_attempt()
            return output(["루프백만 쓴 글"])
        if behavior == "net_count":
            for kind in ("connect", "getaddrinfo", "sendto"):
                blocked_attempt(kind)
            loopback_attempt()
            loopback_attempt()
            stats = wm._netguard.stats()
            text = json.dumps({"attempts": stats["attempts"], "loopback": stats["loopback"], "audit": stats["audit"], "targets": sorted({target for _api, target in stats["recent"]}), "apis": sorted({api for api, _target in stats["recent"]})}, ensure_ascii=True)
            wm._netguard.reset_counts()
            return output([text])
        if behavior == "stdout_noise":
            os.write(1, b"NATIVE NOISE LINE" + chr(10).encode("ascii"))      # 네이티브 라이브러리가 fd 1 에 쓰는 글을 흉내 — 작업자가 fd 1 을 NUL 로 돌렸다면 프로토콜 줄을 못 더럽힌다
            print("PY NOISE LINE")                                            # 파이썬 print 는 sys.stdout(NUL)로 간다
            sys.stdout.flush()
            return output(["소음 뒤의 글"])
        return output(["안녕 하세요", "12,000"])


def fake_build_engine(home, threads):
    if PROBE == "startup_raise":
        raise RuntimeError("가짜 시작 실패")
    return Engine(PROBE), 0.0, "fake-ort"


def main():
    sys.modules["numpy"] = fake_numpy
    wm.files_ok = lambda home, check_hash: (True, {})            # 모델 파일 확인만 건너뛴다(이 시험에는 모델이 없다)
    if PROBE == "import_time":
        if not FAKELIB:
            raise SystemExit("import_time 에는 --fakelib 폴더가 필요하다")
        sys.path.insert(1, FAKELIB)                              # 진짜 build_engine 이 가져올 가짜 라이브러리 자리 — 작업자 폴더(0번) 뒤에 둔다
    else:
        wm.build_engine = fake_build_engine
    return wm.main([])


if __name__ == "__main__":
    sys.exit(main())
