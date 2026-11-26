"""Ed25519 서명 **검증**(RFC 8032, 5.1.7) — 표준 라이브러리만 쓴다(`hashlib.sha512` 와 파이썬의 큰 정수). 서명 만들기는 이 앱에 없다(릴리스 도구 몫).

수제 암호 코드라서 규칙을 좁게 잡았다(UPDATE 설계서 3-3). RFC 6절의 참고 구현을 베끼지 않고 같은 수식을 새로 썼으며, 시험(`tests/test_update_ed25519.py`)이 RFC 7.1 의 시험 벡터·바이트 하나씩 바꾼 변조·
`openssl` 과의 교차 확인·적대적 입력으로 지킨다. 검증은 공개 값만 다루므로 실행 시간이 입력에 따라 달라도 비밀이 새지 않는다(시간 측면 채널은 서명하는 쪽의 문제이고 이 앱에는 서명이 없다 — 문서의 알려진 한계).

`verify(공개키32, 메시지, 서명64)` 는 참·거짓만 돌려준다. 어떤 입력(길이가 틀림·글자·None·깨진 점·터무니없이 큰 값)이 와도 예외를 내지 않고 거짓이다(fail closed).
거짓이어야 하는 것:
  · 길이: 공개키 32바이트·서명 64바이트가 아니다.
  · 점 인코딩: R 과 A 의 y 가 소수 p 이상(비정규)이거나, 곡선 위의 점이 아니거나, x 가 0 인데 부호 비트가 1 이다.
  · 비정규 스칼라: S 가 군의 위수 L 이상이다(S 에 L 을 더한 변조 거절 — RFC 8.4).
  · 작은 위수: R 이나 A 가 위수 8 이하의 점이다(`[8]점` 이 항등원). 공개키가 내장 고정이라 위조에는 쓸 수 없지만 깊이 방어로 거절한다.
  · 식: [8][S]B = [8]R + [8][k]A 가 아니다(여덟 배 — 구현마다 다른 판정을 맞춘다, RFC 5.1.7 · 8.8). k = SHA-512(R, A, 메시지)를 작은 쪽 우선 정수로 읽어 L 로 나눈 나머지.
점 계산은 확장 좌표의 하나의 완전한 덧셈 공식(RFC 5.1.4)만 쓴다 — 두 배도 같은 공식이라 특수한 경우가 없다. 스칼라 곱은 단순한 두 배·더하기 반복이다(공개 값만 다루므로 일정한 시간이 필요 없다).
"""
from __future__ import annotations

import hashlib

P = 2 ** 255 - 19                                          # 바탕 소수
L = 2 ** 252 + 27742317777372353535851937790883648493       # 기본점이 만드는 군의 위수
_D = (-121665 * pow(121666, P - 2, P)) % P                 # 곡선 상수 d = -121665/121666
_D2 = (2 * _D) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)                         # -1 의 제곱근(p 가 8 로 나눈 나머지 5 이므로 2 의 거듭제곱)
_BASE_ENCODED = bytes.fromhex("58" + "66" * 31)            # 기본점 B 의 압축 인코딩(y = 4/5, x 는 짝수)
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
_COFACTOR = 8

_IDENTITY = (0, 1, 1, 0)                                   # (X, Y, Z, T) — 확장 좌표, x = X/Z, y = Y/Z, T = X*Y/Z


def _add(first, second):
    """RFC 8032 5.1.4 의 완전한 덧셈(두 배·항등원 포함)."""
    x1, y1, z1, t1 = first
    x2, y2, z2, t2 = second
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = t1 * _D2 % P * t2 % P
    d = 2 * z1 * z2 % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _multiply(scalar, point):
    """`scalar` 배(0 이상의 정수) — 단순한 두 배·더하기 반복."""
    result = _IDENTITY
    addend = point
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        scalar >>= 1
    return result


def _equal(first, second):
    """두 점이 같은 점인가(확장 좌표의 비율 비교)."""
    return (first[0] * second[2] - second[0] * first[2]) % P == 0 and (first[1] * second[2] - second[1] * first[2]) % P == 0


def _is_identity(point):
    return point[0] % P == 0 and (point[1] - point[2]) % P == 0


def _small_order(point):
    """위수가 8 이하인 점인가 — 항등원·위수 2·4·8 의 점(`[8]점` 이 항등원)."""
    return _is_identity(_multiply(_COFACTOR, point))


def _decode(data):
    """32바이트 압축 인코딩 → 점 또는 None(RFC 8032 5.1.3). 비정규 y(≥ p)·곡선 밖의 y·x 가 0 인데 부호 비트 1 은 None."""
    if len(data) != PUBLIC_KEY_BYTES:
        return None
    value = int.from_bytes(data, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    if y >= P:
        return None
    y2 = y * y % P
    u = (y2 - 1) % P
    v = (_D * y2 + 1) % P
    v3 = v * v % P * v % P
    v7 = v3 * v3 % P * v % P
    x = u * v3 % P * pow(u * v7 % P, (P - 5) // 8, P) % P
    check = v * x % P * x % P
    if check != u:
        if check != (-u) % P:
            return None                                    # 제곱근이 없다 — 곡선 위의 점이 아니다
        x = x * _SQRT_M1 % P
    if x == 0 and sign == 1:
        return None
    if (x & 1) != sign:
        x = (P - x) % P
    return (x, y, 1, x * y % P)


_BASE = _decode(_BASE_ENCODED)


def _is_bytes(value):
    return isinstance(value, (bytes, bytearray))


def _verify(public_key, message, signature):
    if not (_is_bytes(public_key) and _is_bytes(message) and _is_bytes(signature)):
        return False
    public_key, message, signature = bytes(public_key), bytes(message), bytes(signature)
    if len(public_key) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:
        return False
    a_point = _decode(public_key)
    r_point = _decode(signature[:32])
    if a_point is None or r_point is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False                                       # 비정규 스칼라(S + L 같은 변조)
    if _small_order(a_point) or _small_order(r_point):
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % L
    left = _multiply(_COFACTOR, _multiply(s, _BASE))
    right = _multiply(_COFACTOR, _add(r_point, _multiply(k, a_point)))
    return _equal(left, right)


def verify(public_key, message, signature):
    """서명이 이 공개키와 메시지에 맞는가 → True 또는 False. 어떤 입력도 예외를 내지 않는다."""
    try:
        return _verify(public_key, message, signature) is True
    except Exception:          # noqa: BLE001 - 어떤 이상한 입력이든 '틀린 서명' 으로 닫는다(fail closed)
        return False


__all__ = ["L", "P", "PUBLIC_KEY_BYTES", "SIGNATURE_BYTES", "verify"]
