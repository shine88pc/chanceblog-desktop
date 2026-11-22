# -*- coding: utf-8 -*-
"""netguard.py - 작업자 안의 소켓 수준 네트워크 시도 가드(설계서 3-6 의 2겹). 시제품 photolab\\guard\\netguard.py 를 가져와 정리한 것: 로그 파일을 쓰지 않고 횟수만 센다.

작업자 진입 파일(worker_main.py)의 첫 줄에서 rapidocr·onnxruntime·cv2 를 가져오기 전에 install() 한다. 설치에 실패하면 작업자가 시작하지 않는다(fail closed).
막는 것: socket.socket.connect / connect_ex / sendto, socket.create_connection, socket.getaddrinfo / gethostbyname / gethostbyname_ex / gethostbyaddr / getnameinfo / getfqdn.
통과: 루프백(127.0.0.0/8, ::1, localhost)만 — 센 값은 'loopback' 으로만 센다(시도로 세지 않는다).
시도가 있으면: 횟수(attempts)를 올리고 대상은 메모리의 작은 목록(recent)에만 남긴다(파일·표준 출력에 쓰지 않는다. 응답에는 횟수만 싣는다).
한계: 파이썬 소켓 모듈을 거치지 않는 네이티브 확장이 직접 여는 연결은 못 본다 -> 빌드의 가져오기 표 점검(WS2_32·WinINet·WinHTTP 등)과 연결 표본이 보완한다.
표준 라이브러리만 쓴다.
"""
import errno
import ipaddress
import socket
import threading

ACTIVE = False
_lock = threading.Lock()
_stats = {"attempts": 0, "loopback": 0}
_recent = []                 # (api, target) 최근 20개 — 메모리에만
_orig = {}


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
        return {"active": ACTIVE, "attempts": _stats["attempts"], "loopback": _stats["loopback"], "recent": list(_recent)}
