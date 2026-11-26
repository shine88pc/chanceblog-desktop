"""앱에 내장하는 서명 공개키 목록과 폐기 목록(UPDATE 설계서 3-1, 질문 Q3 — 현재 키 하나 + 예비 키 하나, 폐기 목록). 상수와 순수 함수뿐이다.

**출하 키 자리는 지금 비어 있다**(`SHIPPED_KEYS` = 빈 목록). 개인키는 이 갈래가 만들지도 다루지도 않는다 — 운영자가 오프라인에서 키 쌍을 만들고 **공개키만** 이 목록에 넣는 변경이 따로 있다
(RELEASE 갈래 설계의 순서표 3번, 운영자 확인 E-2: 요청 글의 지문과 대조). 목록이 비어 있는 동안 모든 서명 확인은 '모르는 키' 로 거절된다(fail closed) — 키가 없는 빌드로 업데이트가 열리지 않는다.
키 하나의 이름표(`key_id`)는 공개키 32바이트의 SHA-256 앞 8바이트를 16진수 16글자로 쓴 값이고, 매니페스트의 `key_id` 칸이 어느 키로 확인할지 고르는 데만 쓰인다(서명 확인 전에는 다른 칸을 믿지 않는다).
폐기 목록(`REVOKED_KEY_IDS`)에 오른 이름표는 목록에 키가 남아 있어도 쓰이지 않는다. 이 파일의 값을 바꾸는 것은 서명 코드의 신뢰 뿌리를 바꾸는 일이라 T3 다.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re

from . import ed25519

ROLE_CURRENT = "current"
ROLE_SPARE = "spare"
ROLES = (ROLE_CURRENT, ROLE_SPARE)
MAX_KEYS = 2                                   # 현재 키 하나 + 예비 키 하나(예비 키는 오프라인에만 두고 공개키만 내장한다)
KEY_ID_PATTERN = re.compile(r"[0-9a-f]{16}", re.ASCII)

# 출하 키 자리 — (역할, 공개키 32바이트를 base64 로 쓴 글). 지금은 비어 있다. 운영자가 만든 공개키를 넣는 변경(확인 E-2)이 따로 온다.
SHIPPED_KEYS = ()
# 폐기한 키 이름표 목록(16자리 16진수)
REVOKED_KEY_IDS = ()


def key_id_of(public_key):
    """공개키 32바이트 → 이름표(16자리 16진수 소문자)."""
    return hashlib.sha256(bytes(public_key)).hexdigest()[:16]


class KeyringError(ValueError):
    """키 목록 자체가 틀렸다(프로그램 실수·시험) — 사용자 화면의 오류가 아니다."""


class Keyring:
    """이름표 → 공개키. 폐기된 이름표와 모르는 이름표는 찾아지지 않는다(None)."""

    def __init__(self, entries=(), revoked=()):
        found = {}
        roles = {}
        for role, public_key in entries:
            if role not in ROLES:
                raise KeyringError("키의 역할이 틀리다")
            if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != ed25519.PUBLIC_KEY_BYTES:
                raise KeyringError("공개키는 32바이트여야 한다")
            ident = key_id_of(public_key)
            if ident in found:
                raise KeyringError("같은 공개키가 두 번 있다")
            if role in roles.values():
                raise KeyringError("같은 역할의 키가 둘이다")
            found[ident] = bytes(public_key)
            roles[ident] = role
        if len(found) > MAX_KEYS:
            raise KeyringError("내장 키는 둘까지다")
        revoked = tuple(revoked)
        if any(not isinstance(item, str) or KEY_ID_PATTERN.fullmatch(item) is None for item in revoked):
            raise KeyringError("폐기 이름표의 모양이 틀리다")
        self._keys = found
        self._roles = roles
        self._revoked = frozenset(revoked)

    def lookup(self, key_id):
        """이름표에 맞는 공개키 32바이트. 폐기됐거나 모르는 이름표·모양이 틀린 값은 None."""
        if not isinstance(key_id, str) or KEY_ID_PATTERN.fullmatch(key_id) is None or key_id in self._revoked:
            return None
        return self._keys.get(key_id)

    def ids(self):
        return tuple(sorted(self._keys))

    def role_of(self, key_id):
        return self._roles.get(key_id)

    def is_revoked(self, key_id):
        return key_id in self._revoked

    def __len__(self):
        return len(self._keys)


def decode_entries(shipped):
    """`SHIPPED_KEYS` 모양((역할, base64 글) 목록) → `Keyring` 의 entries. 모양이 틀리면 KeyringError."""
    entries = []
    for item in shipped:
        if not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], str)):
            raise KeyringError("출하 키 항목의 모양이 틀리다")
        try:
            raw = base64.b64decode(item[1].encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError, ValueError):
            raise KeyringError("공개키 글이 base64 가 아니다") from None
        entries.append((item[0], raw))
    return entries


def shipped_keyring():
    """앱에 내장한 키 목록(지금은 비어 있다 — 모든 확인이 '모르는 키' 로 거절된다)."""
    return Keyring(decode_entries(SHIPPED_KEYS), REVOKED_KEY_IDS)


__all__ = ["KEY_ID_PATTERN", "Keyring", "KeyringError", "MAX_KEYS", "REVOKED_KEY_IDS", "ROLES", "ROLE_CURRENT", "ROLE_SPARE", "SHIPPED_KEYS", "decode_entries", "key_id_of", "shipped_keyring"]
