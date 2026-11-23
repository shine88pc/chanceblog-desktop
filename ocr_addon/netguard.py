# -*- coding: utf-8 -*-
"""netguard.py - 작업자 안의 소켓 수준 네트워크 시도 가드(설계서 3-6 의 2겹). 시제품 photolab\\guard\\netguard.py 를 가져와 정리한 것: 로그 파일을 쓰지 않고 횟수만 센다.

작업자 진입 파일(worker_main.py)의 첫 줄에서 rapidocr·onnxruntime·cv2 를 가져오기 전에 install() 한다. 설치에 실패하면 작업자가 시작하지 않는다(fail closed).
막는 것: socket.socket.connect / connect_ex / sendto, socket.create_connection, socket.getaddrinfo / gethostbyname / gethostbyname_ex / gethostbyaddr / getnameinfo / getfqdn.
감사 훅 한 겹(결정 D-587): sys.addaudithook 이 `_socket`(C 모듈)을 곧바로 쓰는 호출까지 본다 — socket.connect(connect_ex 포함)·bind·sendto·sendmsg·getaddrinfo·gethostbyname(_ex 포함)·gethostbyaddr·getnameinfo 이벤트에서
  루프백 밖이면 같은 방식으로 세고 막는다(위 래퍼를 지난 호출은 래퍼가 먼저 막으므로 두 번 세지 않는다). 훅은 한 번 걸면 못 빼므로 **켜짐 표시로만** 일한다 — 꺼져 있는 동안 훅은 아무것도 하지 않는다(enable_audit·disable_audit).
통과: 루프백(127.0.0.0/8, ::1, localhost)만 — 센 값은 'loopback' 으로만 센다(시도로 세지 않는다).
시도가 있으면: 횟수(attempts)를 올리고 대상은 메모리의 작은 목록(recent)에만 남긴다(파일·표준 출력에 쓰지 않는다. 응답에는 횟수만 싣는다).
한계: ctypes·네이티브 확장이 운영체제 API(WinSock·WinINet 등)를 직접 부르는 연결은 파이썬 소켓 모듈도 감사 훅도 거치지 않아 못 본다 -> 빌드의 가져오기 표 점검(WS2_32·WinINet·WinHTTP 등)과 연결 표본이 보완한다. 윈도 asyncio(ProactorEventLoop)의 연결도 같은 길이라 못 보지만 배포 묶음은 asyncio 를 빼므로 풀린 소스에서만 열려 있다(결정 D-593). 빈 주소 bind 는 통과하고 listen 은 보지 않는다. install 은 enable_audit 의 거짓 반환(소켓 모듈에 `_socket` 없음 — 가짜 소켓 모듈)을 무시한다.
표준 라이브러리만 쓴다.
"""
import errno
import ipaddress
import socket
import sys
import threading

ACTIVE = False
_lock = threading.Lock()
_stats = {"attempts": 0, "loopback": 0}
_recent = []                 # (api, target) 최근 20개 — 메모리에만
_orig = {}
_AUDIT_CONNECTS = frozenset(("socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"))        # 인자 (소켓, 주소)
_AUDIT_NAMES = frozenset(("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"))   # 인자 (이름 …) · getnameinfo 는 (주소 튜플)
_AUDIT_EVENTS = _AUDIT_CONNECTS | _AUDIT_NAMES
_AUDIT_CHECK = "netguard.hookcheck"        # 훅이 실제로 걸렸는지 enable_audit 가 한 번 확인하는 이벤트 이름(소켓과 무관)
_audit_hooked = False        # 이 모듈 사본이 훅을 이미 걸었는가(훅은 한 번 걸면 못 뺀다)
_audit_on = False            # 훅이 일하는 중인가 — 꺼져 있으면 훅은 아무것도 하지 않는다
_audit_seen = False          # enable_audit 의 확인 이벤트를 훅이 받았는가


def _host_of(address):
    if isinstance(address, (tuple, list)):
        address = address[0] if address else ""
    if isinstance(address, bytes):
        address = address.decode("ascii", "replace")
    return address


def _t(address):
    if isinstance(address, (tuple, list)) and address:
        return "%s:%s" % (_host_of(address), address[1]) if len(address) > 1 else str(_host_of(address))
    return str(_host_of(address))


def _is_loopback(host):
    host = _host_of(host)
    if host in (None, ""):
        return True                                   # 주소 없이 열기/묶기는 연결이 아니다
    h = str(host).strip("[]").lower()
    if h in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(h.split("%")[0]).is_loopback
    except ValueError:
        return False


def _record(blocked, api, target):
    with _lock:
        if blocked:
            _stats["attempts"] += 1
            _recent.append((api, str(target)[:80]))
            del _recent[:-20]
        else:
            _stats["loopback"] += 1


def _deny(api, target, exc="perm"):
    _record(True, api, target)
    if exc == "gai":
        raise socket.gaierror(getattr(socket, "EAI_NONAME", 11001), "netguard: 이름 풀이 차단 (%s)" % api)
    raise PermissionError(errno.EACCES, "netguard: 네트워크 연결 차단 (%s)" % api)


def _audit_target(event, args):
    """감사 이벤트에서 대상(주소 또는 이름)을 꺼낸다 — connect·bind·sendto·sendmsg 는 (소켓, 주소), getnameinfo 는 (주소 튜플), 나머지는 (이름 …)."""
    if event in _AUDIT_CONNECTS:
        return args[1]
    if event == "socket.getnameinfo":
        return args[0][0] if isinstance(args[0], (tuple, list)) and args[0] else args[0]
    return args[0]


def _audit_hook(event, args):
    """sys.addaudithook 에 건 한 겹 — `_socket` 을 곧바로 쓰는 호출도 같은 규칙으로 본다. 켜짐 표시(_audit_on)가 꺼져 있으면 아무것도 하지 않는다. 대상을 읽지 못하면 막는 쪽으로 간다."""
    if not _audit_on:
        return
    if event not in _AUDIT_EVENTS:
        if event == _AUDIT_CHECK:
            _mark_seen()
        return
    try:
        target = _audit_target(event, args)
        outside = not _is_loopback(target)
    except Exception:
        target, outside = "?", True
    if outside:
        _deny(event, _t(target) if event in _AUDIT_CONNECTS else _host_of(target), "perm" if event in _AUDIT_CONNECTS else "gai")


def _mark_seen():
    global _audit_seen
    _audit_seen = True


def enable_audit():
    """감사 훅 한 겹을 켠다(install 이 부른다) — 훅은 이 사본에서 한 번만 걸고 그 뒤로는 켜짐 표시만 올린다. 소켓 모듈에 `_socket` 이 없으면(시험의 가짜 소켓 모듈) 걸지 않고 False 를 돌려준다
    (훅은 못 빼므로 가짜 위에서 도는 시험이 프로세스에 훅을 남기지 않게). 훅이 실제로 걸렸는지 확인 이벤트로 한 번 보고, 안 걸렸으면 예외 — 앞서 걸린 다른 훅이 예외를 내면 새 훅이 조용히 안 걸릴 수 있다(fail closed)."""
    global _audit_hooked, _audit_on, _audit_seen
    if getattr(socket, "_socket", None) is None:
        return False
    if not _audit_hooked:
        sys.addaudithook(_audit_hook)
    _audit_on, _audit_seen = True, False
    try:
        sys.audit(_AUDIT_CHECK)
    except BaseException:
        _audit_on = False
        raise
    if not _audit_seen:
        _audit_on = False
        raise RuntimeError("netguard: 감사 훅이 걸리지 않았다")
    _audit_hooked = True                              # 확인이 끝난 뒤에야 '걸었다' 로 적는다(안 걸린 채로 걸렸다고 믿지 않게)
    return True


def disable_audit():
    """감사 훅의 일을 끈다 — 켜짐 표시만 내린다(건 훅은 못 뺀다). 시험이 같은 프로세스에서 켰다 끄기 위한 것이고 작업자(worker_main.py)는 부르지 않는다(시험이 소스에서 확인한다)."""
    global _audit_on
    _audit_on = False


def _wrap_method(name):
    orig = getattr(socket.socket, name)
    _orig["socket." + name] = orig

    def wrapper(self, *a, **kw):
        addr = a[-1] if name == "sendto" and a else (a[0] if a else kw.get("address"))
        if _is_loopback(addr) or addr is None:
            _record(False, "socket." + name, addr)
            return orig(self, *a, **kw)
        if name == "connect_ex":
            _record(True, "socket." + name, _t(addr))
            return errno.EACCES
        _deny("socket." + name, _t(addr))

    wrapper.__name__ = name
    setattr(socket.socket, name, wrapper)


def _wrap_func(name, exc="gai"):
    if not hasattr(socket, name):
        return
    orig = getattr(socket, name)
    _orig["socket." + name] = orig

    def wrapper(*a, **kw):
        host = a[0] if a else (kw.get("host") or kw.get("address") or kw.get("ip_address"))
        if name == "getfqdn" and not (a or kw):
            host = "localhost"
        if name == "getnameinfo" and a:
            host = a[0][0] if isinstance(a[0], (tuple, list)) else a[0]
        if _is_loopback(host):
            _record(False, "socket." + name, host)
            return orig(*a, **kw)
        _deny("socket." + name, _host_of(host), exc)

    wrapper.__name__ = name
    setattr(socket, name, wrapper)


def install():
    """한 번만 설치한다. 성공하면 True, 못 하면 예외(호출자는 시작하지 않는다)."""
    global ACTIVE
    if ACTIVE:
        return True
    for n in ("connect", "connect_ex", "sendto"):
        _wrap_method(n)
    orig_cc = socket.create_connection
    _orig["socket.create_connection"] = orig_cc

    def create_connection(address, *a, **kw):
        if _is_loopback(address):
            _record(False, "socket.create_connection", address)
            return orig_cc(address, *a, **kw)
        _deny("socket.create_connection", _t(address))

    socket.create_connection = create_connection
    for n in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo", "getfqdn"):
        _wrap_func(n)
    enable_audit()                                    # 래퍼 위에 감사 훅 한 겹 — 켜지지 않으면 예외라 ACTIVE 가 오르지 않고 작업자는 시작하지 않는다
    ACTIVE = True
    return True


def verify_installed():
    """실제로 막히는지 한 번 확인(문서화된 TEST-NET 주소는 어디로도 나가지 않는다 — 가드가 막기 전에는 시도 자체를 하지 않으므로 패킷도 없다). 반환: 막힘 여부."""
    before = _stats["attempts"]
    try:
        socket.create_connection(("192.0.2.1", 9), timeout=0.2)
    except (PermissionError, OSError):
        pass
    return _stats["attempts"] == before + 1


def attempts():
    return _stats["attempts"]


def reset_counts():
    with _lock:
        _stats["attempts"] = 0
        _stats["loopback"] = 0
        del _recent[:]


def stats():
    with _lock:
        return {"active": ACTIVE, "audit": _audit_on, "attempts": _stats["attempts"], "loopback": _stats["loopback"], "recent": list(_recent)}
