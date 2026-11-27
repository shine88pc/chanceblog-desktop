"""릴리스 서명 도구 — 서명 매니페스트(`update-manifest.json`)에 Ed25519 서명(`update-manifest.json.sig`)을 만든다(RELEASE 설계서 3-5, V1REL12·R-1).

쓰는 법(저장소 맨 위 폴더에서, 비밀 값은 **환경 변수 `UPDATE_SIGNING_KEY` 로만** 받는다 — 인자·파일·표준 입력으로 받지 않는다):
    python -X utf8 scripts/update_sign.py --manifest release/update-manifest.json [--sig-out 파일] [--overwrite] [--require-shipped-key] [--require-openssl]

비밀 값의 모양은 둘이다 — 32바이트 씨앗을 base64 로 쓴 한 줄(44글자)이거나 OpenSSL 이 만든 PKCS#8 개인키 PEM. 서명 대상은 앱(`chanceblog_desktop.update.manifest`)이 정한 **고정 접두어 + 매니페스트 파일의 바이트 그대로**다.

이 도구가 하지 않는 것(시험이 지킨다):
  · 개인키 값을 인자·파일·로그·표준 출력·오류 문구·예외 글·`openssl` 인자에 넣지 않는다. 오류는 모두 **고정 문장**이고, 예상하지 못한 예외는 종류 이름만 보인다. 이 파일은 `logging`·`traceback` 을 가져오지 않는다.
  · 키를 임시 파일로 쓰지 않는다 — 그래서 `openssl` 로 서명하지 않고 표준 라이브러리 서명기(아래)를 쓰고, `openssl` 은 **공개 값(공개키·메시지·서명)만** 확인한다.
  · 앱 번들에 서명 코드를 넣지 않는다 — 앱의 `update/ed25519.py` 는 검증 전용 그대로이고 서명하는 코드는 이 파일에만 있다.

서명기: RFC 8032 5.1.6 의 Ed25519 서명을 `hashlib.sha512` 와 파이썬 큰 정수로 구현했다(확장 좌표, 비트마다 같은 일을 하는 고정 반복 사다리). 파이썬의 큰 정수는 일정한 시간에 계산되지 않으므로 **시간 측면 채널 방어를 약속하지 않는다** —
이 서명은 한 번 도는 일회용 러너 또는 운영자의 오프라인 PC 에서만 한다. RFC 8032 7.1 의 공개 시험 벡터·시험 안의 따로 쓴 참고 서명기·`openssl` 의 서명과 같은 값을 내는지 시험이 본다.

서명하기 전에 앱과 같은 코드(`manifest.read_structure`·`validate_fields`)로 매니페스트를 검사하고(앱이 거절할 매니페스트에 서명하면 그 릴리스는 쓸 수 없다), 키 이름표(`key_id`)가 서명 키의 것과 같은지 본다.
서명한 뒤 자체 검증 둘을 하고 하나라도 실패하면 종료 코드로 멈추며 서명 파일을 남기지 않는다:
  1 앱과 같은 검증기로 확인 — ① 이 서명 키의 공개키 ② 앱에 내장된 공개키 목록(`keys.shipped_keyring()`). 내장 목록에 이 키가 없으면(지금은 목록이 비어 있다) '앱이 이 서명을 아직 받지 않는다' 는 고정 문장 경고이고 `--require-shipped-key` 를 주면 실패다.
  2 `openssl pkeyutl -verify -rawin` 독립 확인(공개 파일만 임시 폴더에 쓴다). `openssl` 을 찾지 못하면 건너뛴다고 말하고 `--require-openssl` 을 주면 실패다. 검증이 실패했을 때만 `openssl version` 을 한 번 더 불러
    그 `openssl` 이 OpenSSL 3.x 가 아니라고(낡았거나 다른 제품 — `-rawin` 을 모른다) 스스로 밝히면 '서명기나 키가 틀렸다' 고 오진하지 않고 '낡아서 쓸 수 없다' 고 건너뛴다(`--require-openssl` 이면 이유가 다른 고정 문장으로 실패 — 재작업 1·Q 의 R8).
    이 하위 프로세스는 키가 든 프로세스의 자식이라 다음을 지킨다(재작업 1·S-1, 시험이 지킨다): ① 환경은 **허용 목록**(`CHILD_ENV_ALLOWED` — `PATH`·`SystemRoot`·임시 폴더·로케일·`OPENSSL_*` 설정)의 변수만 넘긴다 — 서명 키 변수와 비밀처럼 보이는 이름은 가지 않는다
    ② 실행 파일은 `PATH` 의 **절대 경로 항목**에서만 찾는다(현재 폴더·빈 항목·상대 경로 항목은 보지 않고 윈도에서는 `openssl.exe` 만 — `.cmd`·`.bat` 은 쓰지 않는다) ③ 공개 파일만 든 새 임시 폴더에서 표준 입력 없이 돈다.
    남는 한계: `PATH` 의 절대 경로 항목에 가짜 `openssl.exe` 가 있으면 이 독립 확인을 속일 수 있다(단순 환경 덤프로는 키가 안 보이지만 같은 사용자 권한의 악의적 실행 파일은 부모의 환경을 직접 읽을 수 있다 — 걸러내기는 격리가 아니다) — 믿는 PC 에서만 서명한다. 앱의 검증기(자체 검증 1)는 이것과 따로 서명을 거절한다.
종료 코드: 0 성공 · 1 자체 검증 실패·예상 못 한 오류 · 2 사용법·파일 오류 · 3 서명 키가 없거나 형식이 틀림 · 4 앱이 받아들이지 않을 매니페스트(또는 키 이름표가 다름) ·
5 서명 파일은 만들었고 모든 확인을 지났지만 결과를 화면에 쓰지 못함(재작업 1·Q 의 R2 — 출력 인코딩이 한글·긴 줄표를 못 쓰면 못 쓰는 글자만 물음표로 바꿔 쓰므로 보통은 0 이고, 닫힌 파이프처럼 아예 못 쓸 때만 5 와 ASCII 고정 문장).
결과 글은 파일을 쓰기 전에 만들어 두고 파일을 쓴 뒤에 쓴다 — 파일 쓰기 실패(코드 1, '서명 파일을 만들지 않았다')와 출력 실패(코드 5)가 서로 다른 코드·문장이다.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.update import keys as app_keys  # noqa: E402
from chanceblog_desktop.update import manifest as app_manifest  # noqa: E402

ENV_NAME = "UPDATE_SIGNING_KEY"
SEED_BYTES = 32
SIGN_PREFIX = app_manifest.SIGN_PREFIX                      # 앱과 같은 객체 — 접두어를 두 곳에 적지 않는다
PKCS8_PREFIX = bytes.fromhex("302e020100300506032b657004220420")     # OpenSSL 의 Ed25519 개인키(PKCS#8) DER 의 고정 머리 16바이트 — 뒤의 32바이트가 씨앗
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")             # Ed25519 공개키(SubjectPublicKeyInfo) DER 의 고정 머리 12바이트 — 뒤의 32바이트가 공개키
PEM_BEGIN = "-----BEGIN " + "PRIVATE KEY" + "-----"                 # 완성된 머리 줄을 소스에 한 덩어리로 적지 않는다(저장소 비밀 모양 검사)
PEM_END = "-----END " + "PRIVATE KEY" + "-----"
MAX_KEY_TEXT = 4096
OPENSSL_TIMEOUT = 60
# `openssl` 하위 프로세스에 넘기는 환경 변수 이름의 **허용 목록**(대문자 — 비교는 대소문자를 가리지 않는다). 서명 키 변수와 비밀처럼 보이는 이름은 여기에 넣지 않는다(시험이 지킨다).
CHILD_ENV_ALLOWED = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "OPENSSL_CONF", "OPENSSL_MODULES", "OPENSSL_ENGINES"})

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_KEY, EXIT_MANIFEST, EXIT_OUTPUT = 0, 1, 2, 3, 4, 5

OPENSSL_OK, OPENSSL_SKIPPED, OPENSSL_FAILED, OPENSSL_OLD = "ok", "skipped", "failed", "old"
_OPENSSL_BANNER = re.compile(rb"OpenSSL ([0-9]+)[.]")

KEY_FORMAT_MESSAGE = "서명 키의 형식을 알아볼 수 없다"
MSG_USAGE = ("사용법 오류: 인자를 알아볼 수 없다. 쓰는 법은 --manifest 파일 [--sig-out 파일] [--overwrite] [--require-shipped-key] [--require-openssl] 이다 — "
             "비밀 값은 인자로 받지 않고 환경 변수 UPDATE_SIGNING_KEY 로만 받는다.")
MSG_SIG_EXISTS = "서명 파일이 이미 있어 쓰지 않았다(덮어쓰려면 --overwrite)."
MSG_SIG_IS_MANIFEST = "서명하지 않았다: 서명 파일 경로가 매니페스트 파일과 같다."
MSG_NO_KEY = "서명하지 않았다: 환경 변수 UPDATE_SIGNING_KEY 가 없거나 비어 있다."
MSG_BAD_KEY = "서명하지 않았다: 서명 키의 형식을 알아볼 수 없다(씨앗 base64 한 줄 44글자 또는 OpenSSL 개인키 PEM 만 읽는다)."
MSG_NO_MANIFEST = "서명하지 않았다: 매니페스트 파일을 읽지 못했다."
MSG_REFUSED = "서명하지 않았다: 앱이 받아들이지 않을 매니페스트다(이유 이름표: %s)."
MSG_KEY_ID = "서명하지 않았다: 매니페스트의 key_id 가 서명 키의 이름표와 다르다 — 키를 잘못 넣었거나 매니페스트를 다른 키 기준으로 만들었다."
MSG_APP_REJECTS = "서명하지 않았다: 앱과 같은 검증기가 방금 만든 서명을 받지 않는다 — 서명기나 키가 틀렸다."
MSG_SHIPPED_REQUIRED = "서명하지 않았다: 앱에 내장된 공개키 목록이 이 서명을 받지 않는다(--require-shipped-key)."
MSG_SHIPPED_HARD = "서명하지 않았다: 앱에 내장된 공개키로 확인하면 서명이 맞지 않는다 — 내장 키와 서명 키가 다르다."
MSG_OPENSSL_REQUIRED = "서명하지 않았다: openssl 을 찾지 못해 독립 확인을 할 수 없다(--require-openssl)."
MSG_OPENSSL_OLD_REQUIRED = "서명하지 않았다: 찾은 openssl 이 OpenSSL 3.x 보다 낡았거나 다른 제품이라 독립 확인을 할 수 없다(--require-openssl)."
MSG_OUTPUT_FAILED = ("signed: the signature file was written and passed every check, but the result could not be printed "
                     "(output encoding or a closed pipe) - run with PYTHONUTF8=1 and a UTF-8 console.")      # ASCII 고정 문장 — 어떤 출력 인코딩으로도 쓸 수 있다
MSG_OPENSSL_REJECTS = "서명하지 않았다: openssl 독립 확인이 이 서명을 받지 않는다 — 서명기나 키가 틀렸다."
MSG_UNEXPECTED = "예상하지 못한 오류로 멈췄다(종류: %s). 서명 파일을 만들지 않았다."
LINE_SIGNED = "서명했다: %s"
LINE_KEY_ID = "키 이름표(지문): %s"
LINE_APP_THIS_KEY = "자체 검증 1 · 앱과 같은 검증기, 이 서명 키의 공개키: 통과"
LINE_SHIPPED = "자체 검증 1 · 앱에 내장된 공개키 목록: %s"
LINE_OPENSSL = "자체 검증 2 · openssl 독립 확인: %s"
WARN_SHIPPED_EMPTY = "경고 — 내장된 공개키 목록이 비어 있어 지금의 앱은 이 서명을 아직 받지 않는다"
WARN_SHIPPED_MISSING = "경고 — 내장된 공개키 목록에 이 키가 없어 지금의 앱은 이 서명을 아직 받지 않는다"
WARN_SHIPPED_REVOKED = "경고 — 내장된 공개키 목록에서 폐기된 키라 지금의 앱은 이 서명을 받지 않는다"
SKIP_OPENSSL = "건너뜀 — openssl 을 찾지 못했다"
SKIP_OPENSSL_OLD = "건너뜀 — 찾은 openssl 이 OpenSSL 3.x 보다 낡았거나 다른 제품이라 독립 확인에 쓸 수 없다"


class SigningKeyError(ValueError):
    """서명 키의 형식이 틀렸다 — 메시지는 고정 문장이고 값(또는 값의 일부)을 담지 않는다."""

    def __init__(self):
        super().__init__(KEY_FORMAT_MESSAGE)


# ---- Ed25519 서명(RFC 8032 5.1.5·5.1.6) ------------------------------------------------------------------------------------------------------------
P = 2 ** 255 - 19                                          # 바탕 소수
L = 2 ** 252 + 27742317777372353535851937790883648493       # 기본점이 만드는 군의 위수
_D = (-121665 * pow(121666, P - 2, P)) % P                 # 곡선 상수 d = -121665/121666
_SQRT_M1 = pow(2, (P - 1) // 4, P)                         # -1 의 제곱근
_BASE_Y = 4 * pow(5, P - 2, P) % P                         # 기본점의 y = 4/5(x 는 짝수인 쪽)
_IDENTITY = (0, 1, 1, 0)                                   # 확장 좌표 (X, Y, Z, T): x = X/Z, y = Y/Z, T = X*Y/Z


def _recover_x(y, sign):
    """y 와 부호 비트로 x 를 구한다(RFC 8032 5.1.3) — 곡선 위의 점이 아니면 None."""
    if y >= P:
        return None
    square = (y * y - 1) * pow(_D * y * y + 1, P - 2, P) % P
    if square == 0:
        return None if sign else 0
    x = pow(square, (P + 3) // 8, P)
    if (x * x - square) % P != 0:
        x = x * _SQRT_M1 % P
    if (x * x - square) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_BASE_X = _recover_x(_BASE_Y, 0)
_BASE = (_BASE_X, _BASE_Y, 1, _BASE_X * _BASE_Y % P)


def _add(first, second):
    """확장 좌표의 완전한 덧셈(RFC 8032 5.1.4) — 두 배·항등원에도 같은 식이다."""
    x1, y1, z1, t1 = first
    x2, y2, z2, t2 = second
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = 2 * t1 * t2 * _D % P
    d = 2 * z1 * z2 % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _multiply(scalar, point):
    """`scalar` 배 — 256비트를 모두 같은 일(덧셈 하나·두 배 하나)로 도는 사다리. 비트마다 둘 다 계산한다."""
    if not 0 <= scalar < 1 << 256:
        raise ValueError("스칼라 범위")
    low, high = _IDENTITY, point                           # 늘 high = low + point
    for shift in range(255, -1, -1):
        if (scalar >> shift) & 1:
            low, high = _add(low, high), _add(high, high)
        else:
            high, low = _add(low, high), _add(low, low)
    return low


def _encode(point):
    x, y, z, _t = point
    inverse = pow(z, P - 2, P)
    x, y = x * inverse % P, y * inverse % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _expand(seed):
    """씨앗 → (비밀 스칼라, 접두 32바이트) — RFC 8032 5.1.5."""
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def public_key(seed):
    """씨앗 32바이트 → 공개키 32바이트."""
    scalar, _prefix = _expand(seed)
    return _encode(_multiply(scalar, _BASE))


def sign(seed, message):
    """RFC 8032 5.1.6 — 씨앗과 메시지 → 서명 64바이트(결정적)."""
    scalar, prefix = _expand(seed)
    public = _encode(_multiply(scalar, _BASE))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % L
    r_encoded = _encode(_multiply(r, _BASE))
    k = int.from_bytes(hashlib.sha512(r_encoded + public + message).digest(), "little") % L
    return r_encoded + ((r + k * scalar) % L).to_bytes(32, "little")


def key_id_of(public):
    """공개키 → 이름표(SHA-256 앞 8바이트의 16진수 16글자) — 앱의 `keys.key_id_of` 와 같다(시험이 지킨다)."""
    return hashlib.sha256(public).hexdigest()[:16]


# ---- 서명 키 읽기 ------------------------------------------------------------------------------------------------------------------------------------
_RAW_SHAPE = re.compile(r"[A-Za-z0-9+/]{43}=")
_BODY_SHAPE = re.compile(r"[A-Za-z0-9+/]+={0,2}")


def _decode_exact(encoded):
    """엄격하고 정규 형태인 base64 → 바이트, 아니면 None."""
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeError):
        return None
    return raw if base64.b64encode(raw).decode("ascii") == encoded else None


def _seed_from_raw(stripped):
    if _RAW_SHAPE.fullmatch(stripped) is None:
        return None
    raw = _decode_exact(stripped)
    return raw if raw is not None and len(raw) == SEED_BYTES else None


def _seed_from_pem(stripped):
    lines = [line.strip(" \t") for line in stripped.replace("\r\n", "\n").split("\n")]
    if len(lines) < 3 or lines[0] != PEM_BEGIN or lines[-1] != PEM_END:
        return None
    body = "".join(lines[1:-1])
    if _BODY_SHAPE.fullmatch(body) is None:
        return None
    der = _decode_exact(body)
    if der is None or len(der) != len(PKCS8_PREFIX) + SEED_BYTES or not der.startswith(PKCS8_PREFIX):
        return None
    return der[len(PKCS8_PREFIX):]


def parse_signing_key(text):
    """환경 변수 값 → 씨앗 32바이트. 모양이 틀리면 `SigningKeyError`(고정 문장, 값의 흔적 없음)."""
    if isinstance(text, str) and len(text) <= MAX_KEY_TEXT:
        stripped = text.strip()
        seed = _seed_from_raw(stripped)
        if seed is None:
            seed = _seed_from_pem(stripped)
        if seed is not None:
            return seed
    raise SigningKeyError() from None


# ---- 서명 전 검사와 자체 검증 -----------------------------------------------------------------------------------------------------------------------
def signing_message(manifest_bytes):
    """서명 대상 바이트 = 앱의 고정 접두어 + 매니페스트 파일의 바이트 그대로."""
    return SIGN_PREFIX + manifest_bytes


def signature_file(signature):
    """서명 64바이트 → `.sig` 파일 바이트(base64 한 줄 88글자 + LF)."""
    return base64.b64encode(signature) + b"\n"


def pre_sign_check(manifest_bytes):
    """앱과 같은 코드로 매니페스트를 서명 전에 검사한다 → 앱의 `Manifest`. 앱이 거절할 것이면 `ManifestError`(고정 이유 이름표)."""
    obj = app_manifest.read_structure(manifest_bytes)
    return app_manifest.validate_fields(obj, hashlib.sha256(manifest_bytes).hexdigest(), channels=app_manifest.CHANNELS_OFFLINE)


def app_accepts(manifest_bytes, signature_bytes, keyring):
    """앱의 `read_and_verify` 가 이 키 목록으로 이 매니페스트와 서명을 받아들이는가 → (참거짓, 이유 이름표)."""
    try:
        app_manifest.read_and_verify(manifest_bytes, signature_bytes, keyring=keyring, channels=app_manifest.CHANNELS_OFFLINE)
    except app_manifest.ManifestError as error:
        return False, error.reason
    return True, ""


def child_environment(environ):
    """`openssl` 하위 프로세스에 넘길 환경 — 허용 목록(`CHILD_ENV_ALLOWED`)의 변수만(이름의 대소문자는 가리지 않는다). 서명 키 변수와 비밀처럼 보이는 이름·그 밖의 모든 변수는 가지 않는다."""
    return {name: value for name, value in environ.items() if isinstance(name, str) and isinstance(value, str) and name.upper() in CHILD_ENV_ALLOWED}


def find_openssl(environ=None, *, windows=None):
    """`openssl` 실행 파일을 `PATH` 의 **절대 경로 항목**에서만 찾는다 → 경로 또는 None. 현재 폴더·빈 항목·상대 경로 항목은 보지 않고(윈도의 `shutil.which` 는 현재 폴더를 먼저 본다),
    윈도에서는 `openssl.exe` 만 쓴다(`.cmd`·`.bat` 같은 배치 파일은 쓰지 않는다). POSIX 는 실행 권한이 있는 `openssl` 파일이다. `windows` 는 시험이 바꿔 끼운다(기본은 이 운영체제)."""
    env = os.environ if environ is None else environ
    windows = os.name == "nt" if windows is None else windows
    path_text = ""
    for name, value in env.items():
        if isinstance(name, str) and name.upper() == "PATH" and isinstance(value, str):
            path_text = value
            break
    program = "openssl.exe" if windows else "openssl"
    for entry in path_text.split(";" if windows else ":"):
        folder = entry.strip().strip('"') if windows else entry
        if not folder or not os.path.isabs(folder):
            continue
        candidate = os.path.join(folder, program)
        if os.path.isfile(candidate) and (windows or os.access(candidate, os.X_OK)):
            return candidate
    return None


def openssl_verify(public, message, signature, *, which=None, run=subprocess.run, environ=None):
    """`openssl pkeyutl -verify -rawin` 독립 확인 → `OPENSSL_OK`·`OPENSSL_SKIPPED`(openssl 없음)·`OPENSSL_FAILED`. 공개키·메시지·서명(모두 공개 값)만 임시 폴더에 쓴다.
    하위 프로세스는 허용 목록의 환경만 받고(키 변수 없음) 그 임시 폴더에서 표준 입력 없이 돈다. `which` 를 안 주면 `find_openssl(환경)` 으로 찾는다."""
    env = os.environ if environ is None else environ
    exe = which("openssl") if which is not None else find_openssl(env)
    if not exe:
        return OPENSSL_SKIPPED
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            key_path, data_path, sig_path = (os.path.join(folder, name) for name in ("public.der", "message.bin", "signature.bin"))
            for path, data in ((key_path, SPKI_PREFIX + public), (data_path, message), (sig_path, signature)):
                with open(path, "wb") as handle:
                    handle.write(data)
            options = dict(capture_output=True, timeout=OPENSSL_TIMEOUT, env=child_environment(env), cwd=folder, stdin=subprocess.DEVNULL)
            done = run([exe, "pkeyutl", "-verify", "-pubin", "-inkey", key_path, "-keyform", "DER", "-rawin", "-in", data_path, "-sigfile", sig_path], **options)
            if done.returncode == 0:
                return OPENSSL_OK
            return OPENSSL_OLD if _is_not_openssl_3(run, exe, options) else OPENSSL_FAILED
    except (OSError, subprocess.SubprocessError):
        return OPENSSL_FAILED


def _is_not_openssl_3(run, exe, options):
    """검증이 실패한 그 `openssl` 이 `openssl version` 으로 스스로 'OpenSSL 3.x 가 아니다'(낡았거나 다른 제품)라고 밝히는가 — 그렇다면 그 실패는 서명이 틀렸다는 뜻이 아니라 `-rawin` 을 몰라서다.
    같은 환경·같은 빈 임시 폴더·같은 시간 한도로 부르고, 버전을 못 읽으면(실행 실패·시간 초과·종료 코드 0 아님) 거짓이다(진짜 거절로 본다)."""
    try:
        done = run([exe, "version"], **options)
    except (OSError, subprocess.SubprocessError):
        return False
    if done.returncode != 0:
        return False
    shown = done.stdout if isinstance(done.stdout, (bytes, bytearray)) else str(done.stdout or "").encode("utf-8", "replace")
    found = _OPENSSL_BANNER.match(bytes(shown).lstrip())
    return found is None or int(found.group(1)) < 3


def shipped_verdict(manifest_bytes, signature_bytes, shipped):
    """앱에 내장된 공개키 목록의 판정 → ('ok'·'warn'·'hard', 경고 문장). 키가 목록에 없거나 폐기된 것은 경고, 목록의 키로 확인했는데 서명이 틀리면 'hard'."""
    accepted, reason = app_accepts(manifest_bytes, signature_bytes, shipped)
    if accepted:
        return "ok", ""
    if reason == "revoked_key":
        return "warn", WARN_SHIPPED_REVOKED
    if reason == "unknown_key":
        return "warn", WARN_SHIPPED_EMPTY if len(shipped) == 0 else WARN_SHIPPED_MISSING
    return "hard", ""


# ---- 명령줄 -----------------------------------------------------------------------------------------------------------------------------------------
class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError()                                # 모르는 인자 글을 되풀이하지 않는다 — 비밀을 인자로 잘못 넘겨도 화면에 나오지 않게


def _parser():
    parser = _Parser(add_help=False, allow_abbrev=False)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--sig-out", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--require-shipped-key", action="store_true")
    parser.add_argument("--require-openssl", action="store_true")
    return parser


def _read_manifest(path):
    """매니페스트 파일 → 바이트(상한보다 한 바이트 더 읽어 큰 파일은 크기 검사가 거절하게 한다). 못 읽으면 None."""
    try:
        with open(path, "rb") as handle:
            return handle.read(app_manifest.MAX_MANIFEST_BYTES + 1)
    except OSError:
        return None


def _write_signature(path, data, *, exclusive=True):
    """서명 파일을 쓴다. `exclusive`(덮어쓰기를 요청하지 않았을 때)면 **배타적으로**(`O_EXCL`) 만들어 이미 있으면 `FileExistsError` 다(검사와 쓰기 사이에 파일이 생겨도 덮어쓰지 않는다).
    아니면 같은 폴더의 임시 파일에 쓰고 바꿔 넣는다. 어느 쪽이든 쓰다 멈춘 서명 파일이 남지 않게 한다."""
    if exclusive:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return
    folder = os.path.dirname(os.path.abspath(path))
    handle, temp = tempfile.mkstemp(prefix=".sig-", dir=folder)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def say(stream, text):
    """`stream` 에 글을 쓴다 → 썼으면 True. 출력 인코딩이 글자(한글·긴 줄표)를 못 쓰면 못 쓰는 글자만 물음표로 바꿔 다시 쓰고, 그래도(또는 닫힌 파이프 등으로) 못 쓰면 False — 예외를 내보내지 않는다.
    인코딩 오류는 글을 통째로 바꾸기 전에 나므로 반쯤 쓴 글이 남지 않는다. 오류·결과 문장을 쓰는 모든 곳이 이것을 쓴다(재작업 1·Q 의 R2: 출력이 실패해도 종료 코드·문구가 실제와 어긋나지 않게)."""
    shown = getattr(stream, "encoding", None) or "ascii"
    try:
        narrowed = text.encode(shown, "replace").decode(shown, "replace")
    except LookupError:
        narrowed = text.encode("ascii", "replace").decode("ascii")
    for candidate in (text, narrowed):
        try:
            stream.write(candidate)
            flush = getattr(stream, "flush", None)
            if flush is not None:
                flush()                                # 이미 닫힌 파이프는 쓰는 순간이 아니라 비울 때 오류가 난다 — 여기서 잡아야 '썼다' 가 거짓이 되지 않는다
            return True
        except UnicodeError:
            continue
        except (OSError, ValueError):
            return False
    return False


def entry(run_main):
    """명령줄 진입 — `run_main()` 의 종료 코드를 돌려주기 전에 표준 출력을 한 번 비운다. 닫힌 파이프라서 비우기가 실패하면 표준 출력을 빈 장치로 돌려 둔다 —
    그렇지 않으면 파이썬이 끝날 때 다시 비우다 실패해 종료 코드가 120 으로 바뀐다(서명 5·키 생성 4 같은 코드가 지켜지지 않는다)."""
    code = run_main()
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
    return code


def _fail(err, code, message):
    say(err, message + "\n")
    return code


def _run(argv, environ, out, err, which, run, shipped, signer):
    try:
        args = _parser().parse_args(argv)
    except _UsageError:
        return _fail(err, EXIT_USAGE, MSG_USAGE)
    sig_path = args.sig_out if args.sig_out else args.manifest + ".sig"
    if os.path.normcase(os.path.abspath(sig_path)) == os.path.normcase(os.path.abspath(args.manifest)):
        return _fail(err, EXIT_USAGE, MSG_SIG_IS_MANIFEST)
    if os.path.exists(sig_path) and not args.overwrite:
        return _fail(err, EXIT_USAGE, MSG_SIG_EXISTS)
    key_text = environ.get(ENV_NAME, "")
    if not isinstance(key_text, str) or not key_text.strip():
        return _fail(err, EXIT_KEY, MSG_NO_KEY)
    try:
        seed = parse_signing_key(key_text)
    except SigningKeyError:
        return _fail(err, EXIT_KEY, MSG_BAD_KEY)
    data = _read_manifest(args.manifest)
    if data is None:
        return _fail(err, EXIT_USAGE, MSG_NO_MANIFEST)
    try:
        found = pre_sign_check(data)
    except app_manifest.ManifestError as error:
        return _fail(err, EXIT_MANIFEST, MSG_REFUSED % error.reason)
    public = public_key(seed)
    if found.key_id != key_id_of(public):
        return _fail(err, EXIT_MANIFEST, MSG_KEY_ID)
    message = signing_message(data)
    signature = signer(seed, message)
    sig_bytes = signature_file(signature) if isinstance(signature, (bytes, bytearray)) else b""
    accepted, _reason = app_accepts(data, sig_bytes, app_keys.Keyring([(app_keys.ROLE_CURRENT, public)]))
    if not accepted:
        return _fail(err, EXIT_FAILED, MSG_APP_REJECTS)
    lines = [LINE_KEY_ID % key_id_of(public), LINE_APP_THIS_KEY]
    verdict, warning = shipped_verdict(data, sig_bytes, shipped if shipped is not None else app_keys.shipped_keyring())
    if verdict == "hard":
        return _fail(err, EXIT_FAILED, MSG_SHIPPED_HARD)
    if verdict == "warn" and args.require_shipped_key:
        return _fail(err, EXIT_FAILED, MSG_SHIPPED_REQUIRED)
    lines.append(LINE_SHIPPED % ("통과" if verdict == "ok" else warning))
    status = openssl_verify(public, message, bytes(signature), which=which, run=run, environ=environ)
    if status == OPENSSL_FAILED:
        return _fail(err, EXIT_FAILED, MSG_OPENSSL_REJECTS)
    if status == OPENSSL_SKIPPED and args.require_openssl:
        return _fail(err, EXIT_FAILED, MSG_OPENSSL_REQUIRED)
    if status == OPENSSL_OLD and args.require_openssl:
        return _fail(err, EXIT_FAILED, MSG_OPENSSL_OLD_REQUIRED)
    lines.append(LINE_OPENSSL % {OPENSSL_OK: "통과", OPENSSL_SKIPPED: SKIP_OPENSSL}.get(status, SKIP_OPENSSL_OLD))
    report = "\n".join([LINE_SIGNED % os.path.basename(sig_path)] + lines) + "\n"          # 결과 글은 파일을 쓰기 전에 만들어 둔다
    try:
        _write_signature(sig_path, sig_bytes, exclusive=not args.overwrite)
    except FileExistsError:
        return _fail(err, EXIT_USAGE, MSG_SIG_EXISTS)
    if not say(out, report):                                                                  # 서명 파일은 이미 있고 모든 확인을 지났다 — 결과를 못 쓴 것은 파일 쓰기 실패와 다른 코드·ASCII 문장으로 알린다
        say(err, MSG_OUTPUT_FAILED + "\n")
        return EXIT_OUTPUT
    return EXIT_OK


def main(argv=None, *, environ=None, stdout=None, stderr=None, which=None, run=subprocess.run, shipped=None, signer=None):
    """명령줄 진입점. 시험이 `environ`·`stdout`·`stderr`·`which`(이름 → 실행 파일 경로, 안 주면 `find_openssl`)·`run`·`shipped`(내장 키 목록)·`signer` 를 바꿔 끼운다. 어떤 예외도 밖으로 내보내지 않는다."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        return _run(sys.argv[1:] if argv is None else list(argv), os.environ if environ is None else environ, out, err, which, run, shipped, signer if signer is not None else sign)
    except Exception as error:      # noqa: BLE001 - 무슨 일이든 종류 이름만 알리고 멈춘다(예외 글에는 값이 들 수 있다)
        say(err, MSG_UNEXPECTED % type(error).__name__ + "\n")
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(entry(main))
