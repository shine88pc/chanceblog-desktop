"""서명 매니페스트(schema 1)의 엄격한 읽기·서명 확인·규칙 검사(UPDATE 설계서 3-2) — 순수 함수다(접속·파일·시계를 직접 부르지 않는다. 지금 시각·저장된 값은 호출하는 쪽이 넘긴다).

파일 둘: `update-manifest.json`(UTF-8, BOM 없음, 줄 끝 LF, 마지막 줄바꿈 정확히 한 개)과 `update-manifest.json.sig`(서명 64바이트를 base64 로 쓴 한 줄 88글자 + LF). **서명 대상 바이트 = 고정 접두어와
매니페스트 파일의 바이트 그대로**다(JSON 을 다시 쓰지 않는다 — 같은 글인데 바이트가 다른 틈이 없고, 접두어는 같은 키로 다른 것에 서명했을 때 뒤섞이지 않게 하는 도메인 분리다).

검사 순서(앞에서 하나라도 틀리면 거기서 끝 — 서명을 확인하기 **전에는 값을 믿지 않는다**):
  1 크기·줄 끝·끝의 줄바꿈 → 2 서명 파일 모양 → 3 엄격한 JSON 읽기(같은 키·깊이 4 초과·소수·모르는 글자 거절)로 `key_id` 만 읽어 내장 키와 맞춤(폐기·모르는 키는 거절) →
  4 **서명 확인**(접두어 + 바이트) → 5 그 뒤에야 나머지 칸의 모양·범위 검사 → 6 만료 → 7 버전 비교 → 8 `seq` → 9 최소 버전 → 10 설치 종류.
7 과 8 의 순서는 설계서 표(8 이 먼저)와 다르다: **같은 버전이면 `seq` 를 보지 않고 '최신' 으로 끝낸다**(적용한 직후에 같은 최신 매니페스트를 다시 받으면 `seq` 가 저장된 값과 같아 '낮은 판' 이라고 거절하는 틈을 막는다).
`seq` 는 더 높은 버전을 제안받았을 때만 견준다 — 저장된 값보다 **커야** 한다(같으면 거절: 같은 `seq` 로 다른 판을 내미는 재전송·되돌림).

복구 모드(`recovery_target`)는 낮은 판을 허용하는 유일한 길이다 — 제안된 버전이 `pending.from` 하나와 정확히 같을 때만, 서명·칸 규칙·설치 종류는 똑같이 확인하고 만료·`seq` 는 보지 않는다
(이전 릴리스의 매니페스트는 이미 오래돼 만료됐을 수 있고, 되돌릴 판이 정확히 하나로 못박혀 있어 재전송 위험이 없다).
오류는 모두 `ManifestError`(오류 코드 + 이유 이름표)다 — 이유 이름표는 매니페스트의 글을 담지 않는 고정 낱말이다.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..errors import AppError
from ..net import parse as netparse
from . import ed25519, versions
from .keys import KEY_ID_PATTERN

SCHEMA = 1
PRODUCT = "ChanceBlogDesktop"
SIGN_PREFIX = b"ChanceBlogDesktop-update-manifest-v1\n"
MANIFEST_NAME = "update-manifest.json"
SIGNATURE_NAME = "update-manifest.json.sig"
MAX_MANIFEST_BYTES = 64 * 1024
SIGNATURE_FILE_BYTES = 89                      # base64 88글자 + LF
MAX_DEPTH = 4                                  # 묶음(객체·목록)이 겹친 깊이의 상한 — 정상 매니페스트는 3
MAX_FILES = 12
MIN_FILE_BYTES = 1
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 400 * 1024 * 1024
MAX_NOTES_CHARS = 500
MAX_NOTES_LINES = 10
MAX_SEQ = 2 ** 53
MAX_VALID_DAYS = 200                           # 발행에서 만료까지의 상한(설계의 180일에 여유) — 실수로 아주 긴 유효 기간을 서명하지 않게
CLOCK_BEHIND_LIMIT = timedelta(days=2)         # 전에 본 시각보다 이만큼 이상 시계가 뒤로 가 있으면 유효 기간을 믿지 않는다
CHANNELS_ONLINE = ("stable",)
CHANNELS_OFFLINE = ("stable", "rc")            # 후보(rc)는 폴더에서 업데이트(오프라인 적용)에서만
INSTALLER_KINDS = ("velopack", "inno")
INSTALL_KINDS = INSTALLER_KINDS + ("portable", "source")     # 지금 앱의 설치 종류(휴대용·소스 실행은 적용하지 않는다)
FILE_ROLES = ("setup", "package", "feed", "portable")
TOP_KEYS = frozenset({"schema", "product", "channel", "version", "tag", "seq", "issued_utc", "expires_utc", "min_version", "key_id", "commit", "installer", "notes", "files"})
INSTALLER_KEYS = frozenset({"kind", "pack_id"})
FILE_KEYS = frozenset({"role", "name", "size", "sha256"})
NOTES_KEYS = frozenset({"summary"})

CODE_INVALID = "UPDATE_MANIFEST_INVALID"
CODE_SIGNATURE = "UPDATE_SIGNATURE_INVALID"
CODE_EXPIRED = "UPDATE_MANIFEST_EXPIRED"
CODE_DOWNGRADE = "UPDATE_DOWNGRADE_BLOCKED"
CODE_MANUAL = "UPDATE_NEEDS_MANUAL_INSTALL"
CODE_CHECK = "UPDATE_CHECK_FAILED"

STATUS_UP_TO_DATE = "UP_TO_DATE"
STATUS_AVAILABLE = "AVAILABLE"

_SIG_TEXT = re.compile(rb"[A-Za-z0-9+/]{86}==")
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z", re.ASCII)
_COMMIT = re.compile(r"[0-9a-f]{40}", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", re.ASCII)
_PACK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", re.ASCII)
_STABLE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+", re.ASCII)
_RC_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-rc\.[1-9][0-9]*", re.ASCII)
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL"} | {f"COM{number}" for number in range(1, 10)} | {f"LPT{number}" for number in range(1, 10)})
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})


class ManifestError(AppError):
    """매니페스트를 받아들이지 않는 이유 — 오류 코드와 이유 이름표(`reason`: 고정 낱말, 매니페스트의 글 없음)."""

    def __init__(self, code, reason):
        super().__init__(code, detail=f"manifest:{reason}")
        self.reason = reason


def _invalid(reason):
    return ManifestError(CODE_INVALID, reason)


def _bad_signature(reason):
    return ManifestError(CODE_SIGNATURE, reason)


@dataclass(frozen=True)
class FileEntry:
    role: str
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    channel: str
    version: str
    tag: str
    seq: int
    issued: datetime
    expires: datetime
    min_version: str
    key_id: str
    commit: str
    installer_kind: str
    pack_id: str
    summary: str
    files: tuple
    digest: str                                    # 매니페스트 바이트의 SHA-256(기록·확인용)

    def file(self, role):
        """역할로 파일 항목 하나(없으면 None)."""
        return next((item for item in self.files if item.role == role), None)

    def total_bytes(self):
        return sum(item.size for item in self.files)


@dataclass(frozen=True)
class Verdict:
    status: str                                    # STATUS_UP_TO_DATE · STATUS_AVAILABLE
    manifest: Manifest
    apply_possible: bool                           # 지금 설치 종류가 매니페스트의 설치 종류와 같아 이 앱이 바꿀 수 있는가


# ---- 1–3 엄격한 읽기 --------------------------------------------------------------------------------------------------------------------------------
def _unsafe_text(text, *, allow_newline=False):
    """제어 문자·보이지 않는 서식 문자·줄/문단 구분자가 든 글인가(줄바꿈 하나만 허용할 수 있다)."""
    for char in text:
        if char == "\n" and allow_newline:
            continue
        if unicodedata.category(char) in _HIDDEN_CATEGORIES:
            return True
    return False


def _check_tree(root):
    """깊이·글자·형을 반복으로 훑는다(재귀 없음): 묶음 깊이 4 초과 없음, 소수·불리언·null 없음, 글에 제어 문자 없음(줄바꿈은 안내 글 한 곳에서만 나중에 따로 허용한다)."""
    stack = [(root, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, (dict, list)):
            if depth > MAX_DEPTH:
                raise _invalid("depth")
            if isinstance(value, dict):
                for key, item in value.items():
                    if not isinstance(key, str) or _unsafe_text(key):
                        raise _invalid("key_text")
                    stack.append((item, depth + 1))
            else:
                stack.extend((item, depth + 1) for item in value)
        elif isinstance(value, bool) or value is None or isinstance(value, float):
            raise _invalid("value_type")
        elif isinstance(value, str):
            if _unsafe_text(value, allow_newline=True):
                raise _invalid("control_char")
        elif not isinstance(value, int):
            raise _invalid("value_type")


def read_structure(manifest_bytes):
    """바이트 → 엄격하게 읽은 사전. 값은 아직 **믿지 않는다**(서명 확인 전). 틀리면 `ManifestError`(UPDATE_MANIFEST_INVALID)."""
    if not isinstance(manifest_bytes, (bytes, bytearray)):
        raise _invalid("type")
    data = bytes(manifest_bytes)
    if not data or len(data) > MAX_MANIFEST_BYTES:
        raise _invalid("size")
    if b"\r" in data:
        raise _invalid("line_ending")
    if not data.endswith(b"\n") or data.endswith(b"\n\n"):
        raise _invalid("final_newline")
    try:
        value = netparse.read_json(data)
    except netparse.ParseError as error:
        raise _invalid("json_" + error.reason) from None
    if not isinstance(value, dict):
        raise _invalid("not_object")
    _check_tree(value)
    return value


def read_signature(signature_bytes):
    """서명 파일 → 64바이트. 한 줄 88글자(base64, 정규 형태) + LF 가 아니면 `UPDATE_SIGNATURE_INVALID`."""
    if not isinstance(signature_bytes, (bytes, bytearray)):
        raise _bad_signature("sig_type")
    data = bytes(signature_bytes)
    if len(data) != SIGNATURE_FILE_BYTES or not data.endswith(b"\n") or _SIG_TEXT.fullmatch(data[:-1]) is None:
        raise _bad_signature("sig_shape")
    try:
        raw = base64.b64decode(data[:-1], validate=True)
    except (binascii.Error, ValueError):
        raise _bad_signature("sig_base64") from None
    if len(raw) != ed25519.SIGNATURE_BYTES or base64.b64encode(raw) != data[:-1]:
        raise _bad_signature("sig_base64")
    return raw


# ---- 5 서명을 확인한 뒤의 칸 검사 ---------------------------------------------------------------------------------------------------------------------
def parse_time(text):
    """`YYYY-MM-DDThh:mm:ssZ` 만(ASCII 숫자·실제 있는 날짜) → UTC 시각 또는 None."""
    found = _TIME.fullmatch(text) if isinstance(text, str) else None
    if found is None:
        return None
    try:
        return datetime(*(int(part) for part in found.groups()), tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def reserved_name(name):
    """윈도 예약 이름인가(`CON`·`NUL.txt` 처럼 첫 점 앞이 예약 낱말)."""
    return name.split(".", 1)[0].upper() in _RESERVED


def valid_file_name(name):
    """파일 이름 규칙(설계서 3-2): 글자·숫자로 시작하는 ASCII 이름 100자 이하, `..` 없음, 끝의 점 없음, 윈도 예약 이름 아님. 경로 구분자는 허용 글자에 없다."""
    return isinstance(name, str) and _FILE_NAME.fullmatch(name) is not None and ".." not in name and not name.endswith(".") and not reserved_name(name)


def _text_of(item, key, reason):
    value = item.get(key)
    if not isinstance(value, str):
        raise _invalid(reason)
    return value


def _check_files(version, raw_files):
    if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= MAX_FILES:
        raise _invalid("files_count")
    entries, names, roles, total = [], set(), set(), 0
    for item in raw_files:
        if not isinstance(item, dict) or set(item) != FILE_KEYS:
            raise _invalid("file_keys")
        role, name, size, sha = _text_of(item, "role", "file_role"), _text_of(item, "name", "file_name"), item["size"], _text_of(item, "sha256", "file_sha256")
        if role not in FILE_ROLES or role in roles:
            raise _invalid("file_role")
        if not valid_file_name(name) or name.lower() in names:
            raise _invalid("file_name")
        if not _is_int(size) or not MIN_FILE_BYTES <= size <= MAX_FILE_BYTES:
            raise _invalid("file_size")
        if _SHA256.fullmatch(sha) is None:
            raise _invalid("file_sha256")
        if role == "setup" and name != f"ChanceBlogDesktop-{version}-Setup.exe":
            raise _invalid("file_name_setup")
        if role == "portable" and name != f"ChanceBlogDesktop-{version}-win64.zip":
            raise _invalid("file_name_portable")
        if role == "package" and not name.endswith(".nupkg"):
            raise _invalid("file_name_package")
        if role == "feed" and not name.endswith(".json"):
            raise _invalid("file_name_feed")
        roles.add(role)
        names.add(name.lower())
        total += size
        entries.append(FileEntry(role, name, size, sha))
    if total > MAX_TOTAL_BYTES:
        raise _invalid("files_total")
    return tuple(entries)


def _check_summary(summary):
    if not isinstance(summary, str) or not 1 <= len(summary) <= MAX_NOTES_CHARS or len(summary.split("\n")) > MAX_NOTES_LINES or _unsafe_text(summary, allow_newline=True):
        raise _invalid("notes")
    return summary


def validate_fields(obj, digest, *, channels=CHANNELS_ONLINE):
    """서명을 확인한 **뒤에만** 부른다 — 칸 이름·형·범위·서로의 관계를 모두 검사해 `Manifest` 를 만든다. 틀리면 `ManifestError`(UPDATE_MANIFEST_INVALID)."""
    if set(obj) != TOP_KEYS:
        raise _invalid("keys")
    if not _is_int(obj["schema"]) or obj["schema"] != SCHEMA:
        raise _invalid("schema")
    if obj["product"] != PRODUCT:
        raise _invalid("product")
    channel, version = obj["channel"], obj["version"]
    if not isinstance(channel, str) or channel not in channels:
        raise _invalid("channel")
    if not isinstance(version, str) or versions.parse_version(version) is None:
        raise _invalid("version")
    if channel == "stable" and _STABLE_VERSION.fullmatch(version) is None:
        raise _invalid("version_channel")
    if channel == "rc" and _RC_VERSION.fullmatch(version) is None:
        raise _invalid("version_channel")
    if obj["tag"] != "v" + version:
        raise _invalid("tag")
    issued_text, expires_text = obj["issued_utc"], obj["expires_utc"]
    issued, expires = parse_time(issued_text), parse_time(expires_text)
    if issued is None or expires is None:
        raise _invalid("time_format")
    if not issued < expires or expires - issued > timedelta(days=MAX_VALID_DAYS):
        raise _invalid("time_span")
    seq = obj["seq"]
    if not _is_int(seq) or not 1 <= seq < MAX_SEQ or seq != int(issued.strftime("%Y%m%d%H%M%S")):
        raise _invalid("seq")
    min_version = obj["min_version"]
    if not isinstance(min_version, str) or versions.parse_version(min_version) is None or versions.compare(min_version, version) > 0:
        raise _invalid("min_version")
    key_id, commit = obj["key_id"], obj["commit"]
    if not isinstance(key_id, str) or KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise _invalid("key_id")
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise _invalid("commit")
    installer = obj["installer"]
    if not isinstance(installer, dict) or set(installer) != INSTALLER_KEYS:
        raise _invalid("installer")
    kind, pack_id = installer["kind"], installer["pack_id"]
    if not isinstance(kind, str) or kind not in INSTALLER_KINDS or not isinstance(pack_id, str) or _PACK_ID.fullmatch(pack_id) is None:
        raise _invalid("installer")
    notes = obj["notes"]
    if not isinstance(notes, dict) or set(notes) != NOTES_KEYS:
        raise _invalid("notes")
    summary = _check_summary(notes["summary"])
    files = _check_files(version, obj["files"])
    return Manifest(channel, version, "v" + version, seq, issued, expires, min_version, key_id, commit, kind, pack_id, summary, files, digest)


# ---- 1–5 읽기와 서명 확인 -------------------------------------------------------------------------------------------------------------------------
def read_and_verify(manifest_bytes, signature_bytes, *, keyring, channels=CHANNELS_ONLINE):
    """서명이 맞는 매니페스트만 `Manifest` 로 돌려준다(1–5 단계). 서명 전에는 `key_id` 칸만 본다."""
    if not isinstance(manifest_bytes, (bytes, bytearray)):
        raise _invalid("type")
    data = bytes(manifest_bytes)
    if not data or len(data) > MAX_MANIFEST_BYTES:
        raise _invalid("size")
    signature = read_signature(signature_bytes)
    obj = read_structure(data)
    key_id = obj.get("key_id")
    if not isinstance(key_id, str) or KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise _invalid("key_id")
    public_key = keyring.lookup(key_id)
    if public_key is None:
        raise _bad_signature("revoked_key" if keyring.is_revoked(key_id) else "unknown_key")
    if not ed25519.verify(public_key, SIGN_PREFIX + data, signature):
        raise _bad_signature("bad_signature")
    return validate_fields(obj, hashlib.sha256(data).hexdigest(), channels=channels)


# ---- 6–10 지금의 상태와 견주기 ---------------------------------------------------------------------------------------------------------------------
def evaluate(manifest, *, now, current_version, last_seq=0, last_seen=None, install_kind="", recovery_target=""):
    """서명이 맞는 매니페스트를 지금 상태와 견준다 → `Verdict`. `now`·`last_seen` 은 시간대가 있는 UTC 시각, `last_seq` 는 저장된 적용한 가장 높은 `seq`,
    `install_kind` 는 지금 설치 종류(`INSTALL_KINDS` 또는 모르면 빈 글)다. `recovery_target` 이 있으면 복구 모드(위 머리글)."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 한다")
    if last_seen is not None and (not isinstance(last_seen, datetime) or last_seen.tzinfo is None):
        raise ValueError("last_seen 은 시간대가 있는 시각이어야 한다")
    if versions.parse_version(current_version) is None:
        raise ManifestError(CODE_CHECK, "current_version")
    if recovery_target:
        if versions.parse_version(recovery_target) is None or versions.compare(manifest.version, recovery_target) != 0:
            raise ManifestError(CODE_DOWNGRADE, "recovery_target")
    else:
        if last_seen is not None and now < last_seen - CLOCK_BEHIND_LIMIT:
            raise ManifestError(CODE_EXPIRED, "clock_behind")
        if now > manifest.expires:
            raise ManifestError(CODE_EXPIRED, "expired")
        order = versions.compare(manifest.version, current_version)
        if order < 0:
            raise ManifestError(CODE_DOWNGRADE, "lower_version")
        if order == 0:
            return Verdict(STATUS_UP_TO_DATE, manifest, False)
        if manifest.seq <= last_seq:
            raise ManifestError(CODE_DOWNGRADE, "seq")
        if versions.compare(current_version, manifest.min_version) < 0:
            raise ManifestError(CODE_MANUAL, "min_version")
    if install_kind in INSTALLER_KINDS and install_kind != manifest.installer_kind:
        raise ManifestError(CODE_MANUAL, "installer_kind")
    return Verdict(STATUS_AVAILABLE, manifest, install_kind == manifest.installer_kind)


def verify_manifest(manifest_bytes, signature_bytes, *, keyring, now, current_version, last_seq=0, last_seen=None, install_kind="", channels=CHANNELS_ONLINE, recovery_target=""):
    """읽기·서명 확인·견주기를 한 번에 → `Verdict`(`read_and_verify` + `evaluate`)."""
    manifest = read_and_verify(manifest_bytes, signature_bytes, keyring=keyring, channels=channels)
    return evaluate(manifest, now=now, current_version=current_version, last_seq=last_seq, last_seen=last_seen, install_kind=install_kind, recovery_target=recovery_target)


__all__ = ["CHANNELS_OFFLINE", "CHANNELS_ONLINE", "CLOCK_BEHIND_LIMIT", "CODE_DOWNGRADE", "CODE_EXPIRED", "CODE_INVALID", "CODE_MANUAL", "CODE_SIGNATURE", "FILE_ROLES", "FileEntry", "INSTALLER_KINDS",
           "INSTALL_KINDS", "MANIFEST_NAME", "MAX_MANIFEST_BYTES", "Manifest", "ManifestError", "SIGNATURE_NAME", "SIGN_PREFIX", "STATUS_AVAILABLE", "STATUS_UP_TO_DATE", "Verdict", "evaluate",
           "parse_time", "read_and_verify", "read_signature", "read_structure", "reserved_name", "valid_file_name", "validate_fields", "verify_manifest"]
