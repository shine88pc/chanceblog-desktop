"""보안 접속(TLS) 클라이언트 — 앱의 **새 인터넷 접속이 나가는 유일한 문**(NET 설계서 3.2–3.10, 결정 D-728에서 D-731). `http`·`ssl` 을 가져오는 **유일한 파일**이다.

요청 한 건은 정해진 단계로만 간다(실패하면 그 단계에서 끝나고 다음 단계로 가지 않는다):
  1 관문(`capabilities.require_net`, 공개 함수의 **첫 문장**) → 2 쿨다운·진행 중 거절(`usage.py`) → 3 모양 검사(표와 비교: 주소·방법·길·질의·머리글·본문 크기 — 접속 **전에** 거절) →
  신뢰 설정 점검(환경 변수가 신뢰 저장소를 바꿔 놓았으면 접속하지 않는다) → 4 연결(이름 풀이 + 연결) → 5 보안 확인(TLS 1.2 이상·인증서·호스트 이름 — 끄는 길 없음) → 6 보내기(머리글을 우리가 한 줄씩 쓴다) →
  7 머리글 읽기 → 8 이동(3xx) 판정(기본 거절) → 9 본문 읽기(크기·시간을 지키며 `identity` 만) → 10 데이터로 읽기(호출하는 쪽이 `parse.py` 로) → 11 마무리(연결 닫기·접속 기록·쿨다운 계수).

지키는 것: 자체 재시도 0(재시도는 호출하는 쪽 규칙이다) · 쓰기 요청의 '보낸 뒤 실패' 는 `outcome_unknown=True` 로 알리고 자동으로 다시 보내지 않는다 · 표에 있는 머리글 말고는 한 글자도 더하지 않는다
(`Cookie`·`Referer`·사용자 이름·경로 없음 — `User-Agent` 의 버전 번호가 앱에서 나가는 유일한 값) · 프록시·쿠키·자동 이동 없음 · 요청 하나의 총 시간은 **마감 감시**가 강제한다(아래).

**총 시간 감시(T-04·Q10)**: 설계서는 '다른 스레드가 연결을 닫는 감시 타이머' 를 가정했지만 윈도에서 실측하니(`evidence/q10_experiment_win.txt`) `http.client` 처럼 `makefile` 이 열려 있으면 `close()` 가 막힌 읽기를 깨우지 못하고
(`shutdown` 도 깨우지 못했다) 깨우려면 `socket` 가져오기가 필요해 허용 표가 늘 판이었다. 그래서 감시를 **읽는 쪽 안**에 넣었다 — 연결 위에 마감을 아는 껍데기(`_DeadlineSocket`)를 씌워 보내기·읽기마다 남은 시간을 보고
`min(작업 제한, 남은 시간)` 으로 소켓 제한을 줄여 두므로 찔끔 보내는 서버도 마감을 넘기지 못한다(스레드·`socket` 가져오기 없음). 이름 풀이만은 운영체제가 끝낼 때까지 끊을 수 없다(풀이가 돌아온 뒤 마감을 넘겼으면 곧바로 끝낸다).

시험 훅: 생산 코드에는 컨텍스트나 전송기를 바깥에서 넣는 매개변수가 **없다**. 시험은 모듈 함수 `_make_context`·`_resolve`·`_dial`·`_secure`·`_clock` 을 `mock.patch.object` 로 바꾼다(`capabilities` 의 '켜기 훅 없음' 원칙과 같다).
"""
from __future__ import annotations

import hashlib
import http.client
import io
import os
import re
import ssl
import time
from dataclasses import dataclass, field, replace
from urllib.parse import parse_qsl, urljoin, urlsplit

from .. import capabilities
from . import parse as parsing
from .endpoints import CONNECT_TIMEOUT, ENDPOINTS, IO_TIMEOUT, MAX_BEARER_CHARS, MAX_HEADER_BYTES, MAX_URL_CHARS, user_agent
from .errors import (REASON_ENCODING, REASON_HASH, REASON_HEADERS, REASON_LENGTH, REASON_REDIRECT, REASON_SHAPE, REASON_TOO_LARGE, NetError, code_for_status, from_exception, invalid, program_error,
                     status_error)
from .usage import SESSION

READ_CHUNK = 64 * 1024
MAX_REDIRECT_URL_CHARS = 2000
_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?")     # `ui/core/version.py` 의 번호 모양과 같다
_BEARER = re.compile(r"[A-Za-z0-9._~+/=-]+")
_REDIRECT_PATH = re.compile(r"/[A-Za-z0-9._~%+/=:@!$&'()*,;-]{0,1990}")
_REDIRECT_QUERY = re.compile(r"[A-Za-z0-9._~%+/=:@!$&'()*,;?-]{0,1990}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TRUST_ENV = ("SSL_CERT_FILE", "SSL_CERT_DIR")                  # OpenSSL 이 기본 신뢰 경로를 바꾸는 환경 변수(C5)
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_NO_BODY_STATUSES = (204, 304)
_LABELS = {use: endpoint.label for use, endpoint in ENDPOINTS.items()}


class DeadlineExceeded(TimeoutError):
    """요청 하나의 총 시간(마감)을 넘겼다 — 어디서 잡히든 `NETWORK_TIMEOUT` 이 된다."""


# ---- 시험이 `mock.patch.object` 로 바꾸는 자리들(생산 코드의 매개변수가 아니다) ---------------------------------------------------------------
_clock = time.monotonic


def _make_context():
    """보안 환경 — 인증서 검증 필수·호스트 이름 확인(기본값)에 최소 TLS 1.2 를 **명시**한다(기본값이 더 엄격해져도 낮추지 않는다). 윈도에서는 `CA`·`ROOT` 저장소를 읽는다."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _resolve(host, port):
    """이름 풀이 자리 — 진짜는 그대로 돌려주고 `http.client` 가 풀이한다. 시험은 가짜 표(`용도 호스트 → 127.0.0.1:포트`)로 바꾼다."""
    return host, port


def _dial(connection, address):
    """TCP 연결 한 번(이름 풀이 포함) — 소켓은 `http.client` 가 만든다(`socket` 을 이 파일이 가져오지 않는다). 시험은 가짜 소켓을 돌려준다."""
    return connection._create_connection(address, connection.timeout, connection.source_address)


def _secure(connection, raw):
    """TLS 로 감싼다(인증서·호스트 이름 확인은 진짜 `ssl` 이 한다). 시험의 가짜 전송은 그대로 돌려준다."""
    return connection._context.wrap_socket(raw, server_hostname=connection.host)


def _check_context(context):
    """생산 코드의 마지막 방어 — 검증을 낮춘 보안 환경은 쓰지 않는다(시험이 바꿔 끼운 것도 마찬가지)."""
    if context.verify_mode != ssl.CERT_REQUIRED or context.check_hostname is not True or context.minimum_version < ssl.TLSVersion.TLSv1_2:
        raise NetError("NET_TLS_FAILED", {}, detail="context:weak")


def _trust_env_changed():
    """신뢰 저장소를 바꾸는 환경 변수가 설정돼 있는가(C5) — 설정돼 있으면 접속하지 않는다."""
    return any(os.environ.get(name) for name in _TRUST_ENV)


# ---- 마감을 아는 껍데기 ----------------------------------------------------------------------------------------------------------------
class _DeadlineReader(io.RawIOBase):
    """`makefile` 이 돌려주는 읽개 — 읽을 때마다 연결 껍데기에 맡겨 마감을 본다."""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def readable(self):
        return True

    def readinto(self, buffer):
        return self._owner.recv_into(buffer)


class _DeadlineSocket:
    """`http.client` 가 쓰는 소켓 모양(`sendall`·`makefile`·`close`)을 마감과 바이트 계수와 함께 감싼다 — 보내기·읽기 직전마다 남은 시간을 보고 소켓 제한을 `min(작업 제한, 남은 시간)` 으로 줄인다."""

    def __init__(self, sock, deadline, clock):
        self._sock = sock
        self._deadline = deadline
        self._clock = clock
        self.sent = 0
        self.received = 0

    def _budget(self):
        left = self._deadline - self._clock()
        if left <= 0:
            raise DeadlineExceeded("마감")
        self._sock.settimeout(min(IO_TIMEOUT, left))

    def sendall(self, data):
        self._budget()
        self._sock.sendall(data)
        self.sent += len(data)

    def recv_into(self, buffer):
        self._budget()
        count = self._sock.recv_into(buffer)
        self.received += count
        return count

    def makefile(self, mode="rb", buffering=None, **_unused):
        return io.BufferedReader(_DeadlineReader(self), buffer_size=8192)

    def settimeout(self, value):
        pass

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


class _Connection(http.client.HTTPSConnection):
    """우리가 정한 연결 — 풀이·연결·보안 확인·마감을 한곳에서 한다(`connect` 를 덮어쓴다). 자동 연결·프록시 터널·쿠키 없음."""

    def __init__(self, host, deadline, context, clock):
        super().__init__(host, 443, timeout=CONNECT_TIMEOUT, context=context)
        self._deadline = deadline
        self._clock = clock
        self.stage = "connect"

    def connect(self):
        left = self._deadline - self._clock()
        if left <= 0:
            raise DeadlineExceeded("마감")
        self.timeout = min(CONNECT_TIMEOUT, left)
        self.stage = "connect"
        raw = _dial(self, _resolve(self.host, self.port))
        self.stage = "tls"
        try:
            if self._deadline - self._clock() <= 0:
                raise DeadlineExceeded("마감")
            secure = _secure(self, raw)
        except BaseException:
            try:
                raw.close()
            except OSError:
                pass
            raise
        self.stage = "send"
        self.sock = _DeadlineSocket(secure, self._deadline, self._clock)


# ---- 요청 계획(3단계 — 접속 전 모양 검사) ------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class _Plan:
    host: str
    route: object
    method: str
    target: str                       # 요청 줄에 쓰는 길 + 질의
    body: object                      # bytes 또는 None
    bearer: str
    accept_encoding: str
    limit: int                        # 읽을 본문 상한(0 이면 상태만)
    accept: str                       # 표의 고정 Accept
    cache_control: str                # 표의 Cache-Control(없으면 빈 글)
    keep: tuple                       # 이 용도가 더 고르는 응답 머리글


@dataclass(frozen=True)
class NetResponse:
    """받은 답 — 쓸 머리글만 고르고 본문은 바이트로 둔다(글자로 바꾸는 것은 `parse` 가 엄격하게). 출력에 본문이 찍히지 않게 `repr` 에서 뺐다."""
    status: int
    use: str
    host: str
    headers: dict = field(repr=False, default_factory=dict)
    body: bytes = field(repr=False, default=b"")
    seconds: float = 0.0
    sent: int = 0
    received: int = 0
    file_size: int = 0                # `request_to_file` 로 받은 크기(메모리 요청이면 0)
    file_sha256: str = ""

    @property
    def ok(self):
        return 200 <= self.status <= 299

    @property
    def retry_after(self):
        return parsing.retry_after_seconds(self.headers)

    def json(self):
        """본문을 엄격한 JSON 으로 읽는다 — 틀리면 `NET_RESPONSE_INVALID`(이유 고정 낱말, 응답의 글 없음)."""
        try:
            return parsing.read_json(self.body)
        except parsing.ParseError as error:
            raise invalid(self.use, REASON_SHAPE, phase=f"json:{error.reason}") from None

    def raise_for_status(self, *, overrides=None, reason=""):
        """2xx 가 아니면 `NetError`(기본 표 — `net/errors.py`)를 올린다. `overrides` = {상태: 오류 코드}, `reason` = 403 의 사유 코드(호출 한도 판별)."""
        error = status_error(self.status, use=self.use, reason=reason, overrides=overrides)
        if error is not None:
            raise error


def _clean_url_text(url):
    return isinstance(url, str) and 0 < len(url) <= MAX_URL_CHARS and url.isascii() and not any(ch <= " " or ch == "\x7f" for ch in url)


def _plan(endpoint, method, url, body, bearer, accept_encoding, limit, *, download=False):
    """요청 한 건의 모양을 표와 견준다 — 틀리면 접속 전에 프로그램 오류(`UNEXPECTED_ERROR`, 세부에 용도와 짧은 이름뿐)로 끝낸다."""
    use = endpoint.use
    if not _clean_url_text(url):
        raise program_error(use, "url")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise program_error(use, "url") from None
    if parts.scheme != "https" or parts.fragment or port is not None or "@" in parts.netloc or parts.netloc.lower() != endpoint.host:
        raise program_error(use, "host")                     # 평문·포트·사용자 정보·숫자 IP·닮은 이름·끝의 점·표 밖 호스트 모두 여기서 끝난다
    route = next((item for item in endpoint.routes if item.method == method and item.matches(parts.path)), None)
    if route is None:
        raise program_error(use, "route")
    try:
        pairs = tuple(parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)) if parts.query else ()
    except ValueError:
        raise program_error(use, "query") from None
    if len(pairs) != len(route.query) or not all(key == wanted_key and (value == wanted if isinstance(wanted, str) else wanted.fullmatch(value) is not None)
                                                 for (key, value), (wanted_key, wanted) in zip(pairs, route.query)):
        raise program_error(use, "query")
    if download and not (route.download and endpoint.download_timeout > 0 and endpoint.max_download > 0):
        raise program_error(use, "download")
    if body is None:
        if route.max_body:
            raise program_error(use, "body")
    else:
        if not isinstance(body, (bytes, bytearray)) or not route.max_body or len(body) > route.max_body:
            raise program_error(use, "body")
        body = bytes(body)
    if bearer:
        if not route.bearer or not isinstance(bearer, str) or len(bearer) > MAX_BEARER_CHARS or _BEARER.fullmatch(bearer) is None:
            raise program_error(use, "bearer")
    else:
        bearer = ""
    if accept_encoding not in endpoint.accept_encodings:
        raise program_error(use, "encoding")
    cap = endpoint.max_download if download else endpoint.max_response
    if limit is None:
        limit = cap
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0 or limit > cap or (accept_encoding != "identity" and limit != 0):
        raise program_error(use, "limit")
    return _Plan(endpoint.host, route, method, parts.path + ("?" + parts.query if parts.query else ""), body, bearer, accept_encoding, limit, endpoint.accept, endpoint.cache_control, endpoint.keep_headers)


def _redirect_url(endpoint, current_url, location, hops):
    """3xx 의 `Location` 을 판정한다 → 다음 주소. 허용하지 않으면 `NET_RESPONSE_INVALID`(이유: 이동). 같은 호스트는 다음 단계가 표의 길·질의를 다시 견주고,
    다른 호스트는 `redirect_hosts` 에 있을 때만 https·ASCII·사용자 정보 없음·포트 없음·안전한 글자 검사를 지난다."""
    use = endpoint.use
    if hops >= endpoint.max_redirects or not isinstance(location, str) or not location.isascii() or any(ch <= " " or ch == "\x7f" for ch in location):
        raise invalid(use, REASON_REDIRECT, phase="redirect")
    target = urljoin(current_url, location)
    if len(target) > MAX_REDIRECT_URL_CHARS:
        raise invalid(use, REASON_REDIRECT, phase="redirect")
    try:
        parts = urlsplit(target)
        port = parts.port
    except ValueError:
        raise invalid(use, REASON_REDIRECT, phase="redirect") from None
    if parts.scheme != "https" or parts.fragment or port is not None or "@" in parts.netloc:
        raise invalid(use, REASON_REDIRECT, phase="redirect")
    host = parts.netloc.lower()
    if host != endpoint.host and (host not in endpoint.redirect_hosts or _REDIRECT_PATH.fullmatch(parts.path) is None or _REDIRECT_QUERY.fullmatch(parts.query) is None):
        raise invalid(use, REASON_REDIRECT, phase="redirect")
    return target


class _Trace:
    """요청 한 건이 어디까지 갔는지의 기록 — 쿨다운 계수와 접속 기록이 이것으로 정해진다."""

    def __init__(self, endpoint, method):
        self.host = endpoint.host
        self.method = method
        self.route = ""
        self.status = 0
        self.error = ""
        self.connecting = False           # 연결을 시도했는가(모양 검사·신뢰 설정에서 끝난 요청은 접속이 아니다)
        self.sent_started = False         # 요청 바이트를 보내기 시작했는가 — 이 뒤의 실패는 서버가 요청을 봤을 수 있다
        self.sent = 0
        self.received = 0


class _FileSink:
    """`request_to_file` 의 쓰는 곳 — 호출하는 쪽이 정한 새 파일 한 곳. 실패하면 지운다."""

    def __init__(self, dest, expected_sha256):
        self.dest = os.fspath(dest)
        self.expected = expected_sha256
        self.size = 0
        self.digest = hashlib.sha256()
        self._file = None
        self.done = False

    def open(self):
        """접속하기 **전에** 새 파일을 만든다 — 이미 있거나 만들 수 없으면 `OSError`(호출하는 쪽의 실수이지 인터넷 문제가 아니다)."""
        self._file = open(self.dest, "xb")

    def write(self, chunk):
        self._file.write(chunk)
        self.digest.update(chunk)
        self.size += len(chunk)

    def finish(self):
        self._file.close()
        self.done = True

    def discard(self):
        """성공하지 못했으면(끝까지 받아 해시까지 맞지 않았으면) 만든 파일을 지운다."""
        if self._file is None:
            return
        try:
            self._file.close()
        except OSError:
            pass
        if not self.done:
            try:
                os.unlink(self.dest)
            except OSError:
                pass


# ---- 클라이언트 ----------------------------------------------------------------------------------------------------------------------
class NetClient:
    """요청 한 건을 보내는 클라이언트 — 호출하는 쪽(어댑터의 공장 함수)이 만든다. 기본 빌드에서는 어떤 코드도 이 객체를 만들지 않는다(어댑터가 등록되지 않는다)."""

    def __init__(self, *, version, usage=None):
        if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
            raise program_error("client", "version")
        self._agent = user_agent(version)
        self.usage = SESSION if usage is None else usage

    # ---- 공개 함수 ---------------------------------------------------------------------------------------------------------------------
    def request(self, use, method, url, *, body=None, bearer=None, accept_encoding="identity", limit=None):
        """요청 한 건 → `NetResponse`(2xx 가 아니어도 돌려준다 — 호출하는 쪽이 `raise_for_status` 나 자기 코드로 바꾼다). 접속 전 실패·전송 실패·마감 초과는 `NetError`.
        `url` 은 표의 호스트·길·고정 질의를 가진 https 주소다(`endpoints.url_for` 가 만든다). `limit` 은 읽을 본문 상한(0 이면 상태만)."""
        capabilities.require_net(use, _LABELS.get(use, "인터넷 접속"))
        return self._run(use, method, url, body, bearer, accept_encoding, limit, None)

    def request_to_file(self, use, method, url, dest, *, max_bytes, expected_sha256=None, bearer=None):
        """큰 파일 내려받기(UPDATE 가 쓴다, 3.14) — 같은 관문·표·시간 규칙이고 본문은 메모리에 모으지 않고 `dest`(**호출하는 쪽이 정한 새 파일 한 곳**, 이미 있으면 거절)에 쓴다.
        응답이 정한 이름·경로는 쓰지 않는다. 크기가 `max_bytes` 를 넘거나 `expected_sha256` 이 다르거나 도중에 실패하면 파일을 지우고 오류를 올린다. 용도 표에 `download` 길과 내려받기 시간·크기가 있어야 한다."""
        capabilities.require_net(use, _LABELS.get(use, "인터넷 접속"))
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None):
            raise program_error(use if isinstance(use, str) else "?", "sha256")
        try:
            sink = _FileSink(dest, expected_sha256)
        except (TypeError, ValueError):
            raise program_error(use if isinstance(use, str) else "?", "dest") from None
        return self._run(use, method, url, None, bearer, "identity", max_bytes, sink)

    # ---- 안쪽 ----------------------------------------------------------------------------------------------------------------------------
    def _run(self, use, method, url, body, bearer, accept_encoding, limit, sink):
        endpoint = ENDPOINTS.get(use)
        if endpoint is None:
            raise program_error(use if isinstance(use, str) else "?", "use")
        self.usage.begin(use)                                                    # 2 쿨다운·진행 중 — 거절이면 접속하지 않는다
        trace = _Trace(endpoint, method)
        started = _clock()
        try:
            plan = _plan(endpoint, method, url, body, bearer, accept_encoding, limit, download=sink is not None)         # 3 모양 검사
            trace.route = plan.route.shown
            if _trust_env_changed():
                raise NetError("NET_TLS_FAILED", {}, detail=f"{use}:trust_env", use=use)
            try:
                context = _make_context()
            except Exception as error:                                          # noqa: BLE001 - 윈도 인증서 저장소를 못 읽는 등 — 접속하기 전에 끝난다
                raise from_exception(error, use=use, stage="tls", sent=False) from None
            _check_context(context)
            if sink is not None:
                try:
                    sink.open()
                except OSError:
                    raise program_error(use, "dest") from None
            deadline = started + (endpoint.download_timeout if sink is not None else endpoint.total_timeout)
            return self._follow(endpoint, plan, url, context, deadline, started, trace, sink)
        except NetError as error:
            trace.error = error.code
            raise
        finally:
            if sink is not None:
                sink.discard()                                                   # 끝까지 받아 해시까지 맞지 않았으면 만든 파일을 지운다
            self._close_out(use, trace, _clock() - started)

    def _close_out(self, use, trace, elapsed):
        """11 마무리 — 쿨다운 계수와 접속 기록. 접속하지 않고 끝난 요청(모양 검사·신뢰 설정)은 계수도 기록도 없다."""
        if not trace.connecting:
            self.usage.abort(use)
            return
        status, code = trace.status, trace.error
        endpoint = ENDPOINTS.get(use)
        quiet = endpoint.uncounted_statuses if endpoint is not None else (400, 422, 429)
        if code:
            ok, counts = False, True                                   # 전송 실패·모양이 틀린 답 — 연속 실패에 센다
        elif 200 <= status <= 299:
            ok, counts = True, False
        elif status:
            ok, counts = False, status not in quiet                    # 400·422·429(와 용도 표가 더한 상태)는 센다 안 함
            code = code_for_status(status) or ""
        else:
            self.usage.abort(use)                                      # 끊김(키보드 인터럽트 등) — 결과를 모른다
            return
        self.usage.finish(use, ok=ok, counts=counts)
        self.usage.record(at=self.usage.wall(), use=use, host=trace.host, method=trace.method, route=trace.route, status=status, error=code, sent=trace.sent, received=trace.received, seconds=round(elapsed, 3))

    def _follow(self, endpoint, plan, url, context, deadline, started, trace, sink):
        """4–9 단계를 이동(3xx) 횟수까지 되풀이한다 — 이동 때마다 새 연결, 주소는 매번 표와 견준다(같은 호스트) 또는 `redirect_hosts` 와 견준다(다른 호스트)."""
        seen = {url}
        current_url = url
        for hops in range(endpoint.max_redirects + 1):
            response, location = self._once(endpoint, plan, context, deadline, started, trace, sink)
            if location is None:
                return response
            if plan.method != "GET":
                raise invalid(endpoint.use, REASON_REDIRECT, phase="redirect")
            next_url = _redirect_url(endpoint, current_url, location, hops)
            if next_url in seen:
                raise invalid(endpoint.use, REASON_REDIRECT, phase="redirect")      # 같은 주소로 돌아오는 이동(끝없는 반복)
            seen.add(next_url)
            host = urlsplit(next_url).netloc.lower()
            if host == endpoint.host:
                try:
                    plan = _plan(endpoint, "GET", next_url, None, plan.bearer, plan.accept_encoding, plan.limit, download=sink is not None)
                except NetError:
                    raise invalid(endpoint.use, REASON_REDIRECT, phase="redirect") from None          # 서버가 알려 준 같은 호스트 주소가 표의 길·질의와 다르다 — 우리 쪽 프로그램 오류가 아니라 틀린 답이다
            else:
                parts = urlsplit(next_url)
                plan = replace(plan, host=host, target=parts.path + ("?" + parts.query if parts.query else ""), bearer="", body=None)       # 다른 호스트로는 토큰을 보내지 않는다
            current_url = next_url
            trace.host = host
        raise invalid(endpoint.use, REASON_REDIRECT, phase="redirect")

    def _headers(self, plan):
        """우리가 쓰는 머리글의 전부 — 표에 있는 것만(순서도 고정)."""
        headers = [("Host", plan.host), ("User-Agent", self._agent), ("Accept", plan.accept), ("Accept-Encoding", plan.accept_encoding), ("Connection", "close")]
        if plan.body is not None:
            headers += [("Content-Type", plan.route.content_type), ("Content-Length", str(len(plan.body)))]
        if plan.bearer:
            headers.append(("Authorization", "Bearer " + plan.bearer))
        if plan.cache_control:
            headers.append(("Cache-Control", plan.cache_control))
        return headers

    def _once(self, endpoint, plan, context, deadline, started, trace, sink):
        """연결 한 번 → (`NetResponse`, None) 또는 이동이면 (None, `Location` 글). 4–9 단계."""
        use = endpoint.use
        conn = _Connection(plan.host, deadline, context, _clock)
        stage = "connect"
        sock = None
        try:
            trace.connecting = True
            conn.connect()                                                       # 4 연결 · 5 보안 확인
            sock = conn.sock
            stage = "send"
            conn.putrequest(plan.method, plan.target, skip_host=True, skip_accept_encoding=True)                  # 6 보내기 — 머리글을 우리가 한 줄씩 쓴다
            for name, value in self._headers(plan):
                conn.putheader(name, value)
            trace.sent_started = True
            conn.endheaders(message_body=plan.body)
            stage = "headers"
            resp = conn.getresponse()                                            # 7 머리글 읽기
            trace.status = resp.status
            items = resp.getheaders()
            if len(items) > 100 or sum(len(str(name)) + len(str(value)) + 4 for name, value in items) > MAX_HEADER_BYTES:
                raise invalid(use, REASON_HEADERS, phase="headers", outcome_unknown=True)
            lengths = [value for name, value in items if str(name).lower() == "content-length"]
            if len(lengths) > 1:
                raise invalid(use, REASON_SHAPE, phase="headers", outcome_unknown=True)
            if resp.status in _REDIRECT_STATUSES:                                # 8 이동(3xx) 판정 — 본문은 읽지 않는다
                locations = [value for name, value in items if str(name).lower() == "location"]
                if len(locations) != 1:
                    raise invalid(use, REASON_REDIRECT, phase="redirect", outcome_unknown=True)
                return None, locations[0]
            stage = "body"
            body = self._read_body(use, resp, items, lengths, plan, sink)        # 9 본문 읽기
            picked = parsing.pick_headers(items, plan.keep)
            return NetResponse(status=resp.status, use=use, host=plan.host, headers=picked, body=body, seconds=round(_clock() - started, 3), sent=sock.sent, received=sock.received,
                               file_size=sink.size if sink is not None else 0, file_sha256=sink.digest.hexdigest() if sink is not None else ""), None
        except NetError:
            raise
        except Exception as error:                                              # noqa: BLE001 - 어떤 예외든 종류 이름만 남겨 오류 코드로 바꾼다(문장·주소·머리글은 버린다)
            raise from_exception(error, use=use, stage=conn.stage if stage == "connect" else stage, sent=trace.sent_started) from None
        finally:
            if isinstance(sock, _DeadlineSocket):
                trace.sent += sock.sent
                trace.received += sock.received
            conn.close()

    def _read_body(self, use, resp, items, lengths, plan, sink):
        """9 본문 읽기 — 선언된 크기를 먼저 보고, 읽는 동안 누적 크기를 보며(마감은 소켓 껍데기가 지킨다), 압축된 답은 거절한다."""
        status = resp.status
        limit = plan.limit
        success = 200 <= status <= 299
        if sink is not None and not success:
            limit = 0                                                            # 내려받기가 실패한 답은 본문을 읽지 않는다
        if limit == 0 or status in _NO_BODY_STATUSES:
            if sink is not None and success:
                sink.finish()
            return b""
        declared = None
        if lengths:
            text = lengths[0].strip()
            if not (text.isascii() and text.isdigit() and len(text) <= 15):
                raise invalid(use, REASON_SHAPE, phase="headers", outcome_unknown=True)
            declared = int(text)
            if declared > limit:
                raise invalid(use, REASON_TOO_LARGE, phase="headers", outcome_unknown=True)
        encodings = [str(value).strip().lower() for name, value in items if str(name).lower() == "content-encoding"]
        if any(value not in ("", "identity") for value in encodings):
            raise invalid(use, REASON_ENCODING, phase="headers", outcome_unknown=True)
        chunks, got = [], 0
        while True:
            chunk = resp.read1(min(READ_CHUNK, limit + 1 - got))
            if not chunk:
                break
            got += len(chunk)
            if got > limit:
                raise invalid(use, REASON_TOO_LARGE, phase="body", outcome_unknown=True)
            if sink is not None:
                try:
                    sink.write(chunk)
                except OSError as error:
                    raise NetError("DISK_FULL" if getattr(error, "errno", None) == 28 else "FILE_WRITE_FAILED", {"경로": "내려받는 임시 파일"}, detail=f"{use}:write", use=use) from None
            else:
                chunks.append(chunk)
        if declared is not None and got != declared:
            raise invalid(use, REASON_LENGTH, phase="body", outcome_unknown=True)
        if sink is not None:
            sink.finish()
            if sink.expected is not None and sink.digest.hexdigest() != sink.expected:
                sink.done = False                                                # 해시가 틀리면 지운다
                raise invalid(use, REASON_HASH, phase="hash", outcome_unknown=True)
            return b""
        return b"".join(chunks)


__all__ = ["DeadlineExceeded", "NetClient", "NetResponse"]
