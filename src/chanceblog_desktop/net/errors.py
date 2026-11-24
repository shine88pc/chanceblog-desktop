"""접속 틀의 오류 변환 — 예외와 HTTP 상태를 **오류 코드 한 줄**로 바꾼다(NET 설계서 3.4·R5·T-06·T-17, D-725).

규칙: 예외 문장·주소·머리글·서버가 보낸 글은 **버리고** 예외 **종류 이름**과 단계 이름만 남긴다. 사용자 문구의 `「이유」` 칸에는 아래 고정 낱말만 들어간다 — 서버의 글(`error.message`·`error_description`)은 들어가지 않는다.
이 모듈은 `http`·`ssl` 을 가져오지 않는다(예외는 클래스 이름으로 가른다 — 그 모듈을 가져오는 유일한 파일은 `client.py` 다).
"""
from __future__ import annotations

from ..errors import AppError

# NET_RESPONSE_INVALID 의 「이유」 — 우리가 정한 낱말이다(서버의 글이 아니다)
REASON_TOO_LARGE = "답이 정한 크기보다 커요"
REASON_SHAPE = "답의 모양이 달라요"
REASON_REDIRECT = "허용하지 않는 이동 안내가 왔어요"
REASON_ENCODING = "압축된 답이 왔어요"
REASON_HEADERS = "머리글이 너무 많거나 커요"
REASON_TEXT = "글자가 깨져 있어요"
REASON_STATUS = "예상하지 못한 상태 번호예요"
REASON_LENGTH = "받은 길이가 약속과 달라요"
REASON_HASH = "받은 파일이 약속한 내용과 달라요"
REASONS = (REASON_TOO_LARGE, REASON_SHAPE, REASON_REDIRECT, REASON_ENCODING, REASON_HEADERS, REASON_TEXT, REASON_STATUS, REASON_LENGTH, REASON_HASH)

# 호출 한도를 뜻하는 403 의 사유 코드(Google API 의 `reason` 값) — 이 목록의 것만 `API_RATE_LIMITED`, 그 밖의 403 은 `KEY_AUTH_FAILED`
RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded", "sharedRateLimitExceeded"})

# 예외 클래스 이름(상속 사슬 포함) → 갈래. 이름으로 가르는 까닭: 이 모듈이 `ssl`·`http` 를 가져오지 않게 하려는 것이다.
_TLS_NAMES = frozenset({"SSLError", "SSLCertVerificationError", "CertificateError", "SSLZeroReturnError", "SSLEOFError", "SSLSyscallError", "SSLWantReadError", "SSLWantWriteError"})
_INVALID_NAMES = frozenset({"BadStatusLine", "LineTooLong", "InvalidURL", "UnknownProtocol", "ImproperConnectionState", "ResponseNotReady", "CannotSendHeader", "CannotSendRequest", "IncompleteRead", "NotConnected"})
_TIMEOUT_NAMES = frozenset({"TimeoutError", "timeout", "DeadlineExceeded"})


class NetError(AppError):
    """접속 틀이 올리는 오류 — 오류 코드 한 줄 + 두 가지 사실: 요청이 서버에 닿았을 수 있는가(`outcome_unknown`)와 어느 용도였는가(`use`).
    `detail` 은 용도·단계·예외 종류 이름뿐이다(주소·머리글·서버 글 없음)."""

    def __init__(self, code, slots=None, *, detail="", outcome_unknown=False, use=""):
        super().__init__(code, slots, detail=detail)
        self.outcome_unknown = bool(outcome_unknown)
        self.use = use


def invalid(use, reason, *, phase="", outcome_unknown=False):
    """모양이 틀린 답 — `NET_RESPONSE_INVALID`."""
    return NetError("NET_RESPONSE_INVALID", {"이유": reason}, detail=f"{use}:{phase}", outcome_unknown=outcome_unknown, use=use)


def program_error(use, what):
    """표 모양 검사 실패 같은 프로그램 오류 — `UNEXPECTED_ERROR`(세부에 용도와 짧은 이름만)."""
    return NetError("UNEXPECTED_ERROR", {}, detail=f"{use}:{what}", use=use)


def _names(error):
    return {cls.__name__ for cls in type(error).__mro__}


def from_exception(error, *, use, stage, sent):
    """전송 중 터진 예외 → `NetError`. `stage` 는 'connect'(이름 풀이·연결)·'tls'(보안 확인)·'send'·'headers'·'body' 중 하나, `sent` 는 요청 바이트를 보내기 시작했는가.
    **서버가 요청을 못 봤을 수 있는가**(보내기 전 실패)와 **봤을 수 있는가**(보낸 뒤 실패)를 가른다 — 후자는 `outcome_unknown=True` 다(쓰기 요청을 자동으로 다시 보내지 않는 근거)."""
    if isinstance(error, NetError):
        return error
    names = _names(error)
    detail = f"{use}:{stage}:{type(error).__name__}"
    unknown = bool(sent)
    if names & _TIMEOUT_NAMES:
        return NetError("NETWORK_TIMEOUT", {}, detail=detail, outcome_unknown=unknown, use=use)
    if names & _TLS_NAMES and stage == "tls":
        return NetError("NET_TLS_FAILED", {}, detail=detail, use=use)
    if "RemoteDisconnected" in names or "ConnectionError" in names:            # 답 없이 끊김 — 서버가 요청을 봤을 수도 있다
        return NetError("NETWORK_OFFLINE", {}, detail=detail, outcome_unknown=unknown, use=use)
    if names & _INVALID_NAMES:
        return NetError("NET_RESPONSE_INVALID", {"이유": REASON_LENGTH if "IncompleteRead" in names else REASON_SHAPE}, detail=detail, outcome_unknown=unknown, use=use)
    if "HTTPException" in names and "RemoteDisconnected" not in names:
        return NetError("NET_RESPONSE_INVALID", {"이유": REASON_SHAPE}, detail=detail, outcome_unknown=unknown, use=use)
    if isinstance(error, (OSError, EOFError)) or names & _TLS_NAMES:          # 이름 풀이 실패·연결 거부·끊김·보안 연결이 중간에 끊김 — 인터넷이 없거나 서버가 끊었다
        return NetError("NETWORK_OFFLINE", {}, detail=detail, outcome_unknown=unknown, use=use)
    return NetError("UNEXPECTED_ERROR", {}, detail=detail, outcome_unknown=unknown, use=use)


def code_for_status(status, reason=""):
    """HTTP 상태 → 기본 오류 코드(2xx 는 None). 호출하는 쪽이 더 정확한 코드로 바꿀 수 있다(`NetResponse.raise_for_status` 의 `overrides`)."""
    if 200 <= status <= 299:
        return None
    if status in (400, 422):
        return "REQUEST_INVALID"
    if status == 401:
        return "KEY_AUTH_FAILED"
    if status == 403:
        return "API_RATE_LIMITED" if reason in RATE_LIMIT_REASONS else "KEY_AUTH_FAILED"
    if status == 429:
        return "API_RATE_LIMITED"
    if status in (500, 502, 503, 504):
        return "API_SERVER_ERROR"
    return "NET_RESPONSE_INVALID"                     # 404·그 밖 — 용도별 매핑이 없으면 모양이 틀린 답으로 본다


def counts_as_failure(status):
    """연속 실패 계수에 넣는 상태인가 — 2xx 는 성공이고, 사용자 실수(400·422)와 한도 안내(429)는 넣지 않는다(3.4)."""
    return not (200 <= status <= 299 or status in (400, 422, 429))


def status_error(status, *, use, reason="", overrides=None):
    """상태가 2xx 가 아니면 `NetError`, 맞으면 None. `overrides` 는 {상태: 오류 코드}(예: Blogger 의 401 → `BLOGGER_AUTH_EXPIRED`)."""
    code = (overrides or {}).get(status) or code_for_status(status, reason)
    if code is None:
        return None
    slots = {"이유": REASON_STATUS} if code == "NET_RESPONSE_INVALID" else {}
    return NetError(code, slots, detail=f"{use}:status:{status}", use=use)


__all__ = ["NetError", "RATE_LIMIT_REASONS", "REASONS", "code_for_status", "counts_as_failure", "from_exception", "invalid", "program_error", "status_error"]
