"""비밀 보관소 — API 키·시크릿·토큰은 **Windows 자격 증명 관리자**(OS 보안 저장소)에만 둔다(docs/SECURITY.md §7).

규약(`KeyStore`): `put(ref, fields)`·`get(ref)`·`delete(ref)`·`exists(ref)`·`list_refs(prefix)`. `ref` 는 `<용도>:<항목번호>` 한 줄 글이다.
구현은 셋이다.
  · `WindowsCredentialStore` — `ctypes` 로 `advapi32` 의 `CredWriteW`·`CredReadW`·`CredDeleteW`·`CredEnumerateW`·`CredFree` 를 부른다(표준 라이브러리만). 대상 이름은 `ChanceBlogDesktop:<용도>:<항목번호>`,
    값은 필드들을 JSON 한 덩어리로 묶어 UTF-16 으로 적는다(자격 증명 값 한도 2,560바이트 — 넘으면 `KEY_TOO_LONG`). 지속성은 `CRED_PERSIST_LOCAL_MACHINE`(재부팅 뒤에도 남는다).
  · `MemoryStore` — 시험용(프로그램 안에서만 산다).
  · `FileFakeStore` — **시험 전용** 가짜 JSON 파일 보관소(프로세스 경계를 넘는 명령줄 시험용). 환경 변수 `CHANCEBLOG_KEYSTORE=memory-file` 과 시험용 임시 폴더 표시가 모두 맞을 때만 열리고,
    설치본(`sys.frozen`)에서는 환경 변수를 무시하며, 프로그램의 기본 경로(`default_keystore`)는 환경 변수가 없으면 언제나 진짜 보관소만 연다.

규칙: 파일·환경 변수·설정 JSON·`.env`·로그·저장소에 비밀을 쓰지 않는다. 읽은 값은 필요한 순간에만 꺼내 쓰고 버린다. `__repr__`·`__str__`·예외·오류 세부에는 **값을 넣지 않는다**.
한계(파이썬의 한계라 숨기지 않는다): 파이썬 문자열은 바꿀 수 없어 값을 메모리에서 지울 수 없다 — 자격 증명 관리자가 돌려준 원본 메모리와 보관소로 넘긴 사본은 바로 0 으로 덮지만,
파이썬 쪽 사본은 가비지 수집 때까지 남는다. 같은 Windows 사용자로 도는 악성 프로그램은 자격 증명 관리자의 값을 읽을 수 있다(OS 가 같은 사용자의 프로그램을 구분하지 않는다).
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from ..errors import AppError

TARGET_PREFIX = "ChanceBlogDesktop"
MAX_BLOB_BYTES = 2560            # 자격 증명 값의 한도(CRED_MAX_CREDENTIAL_BLOB_SIZE = 5 * 512)
MAX_FIELDS = 8
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2   # 재부팅 뒤에도 남는다(이 PC 에서만 — 다른 PC 로 따라가지 않는다)
ERROR_NOT_FOUND = 1168
USER_NAME = "ChanceBlogDesktop"
ENV_KEYSTORE = "CHANCEBLOG_KEYSTORE"
ENV_KEYSTORE_DIR = "CHANCEBLOG_KEYSTORE_DIR"
TEST_STORE_VALUE = "memory-file"
TEST_DIR_PREFIX = "chanceblog-fake-keystore-"
TEST_MARKER = "FAKE_KEYSTORE_ONLY.marker"
TEST_FILE = "fake-keystore.json"

_REF = re.compile(r"[a-z_][a-z0-9_]{0,39}:[A-Za-z0-9_-]{1,64}")
_PREFIX = re.compile(r"(?:[a-z_][a-z0-9_]{0,39}(?::[A-Za-z0-9_-]{0,64})?)?")      # 목록 거르기용 앞부분 — 와일드카드(`*`)가 섞일 수 없다
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,31}")


def _unavailable(detail):
    return AppError("KEY_STORE_UNAVAILABLE", detail=detail)


def check_ref(ref):
    """`용도:항목번호` 모양이 아니면 ValueError(프로그램이 만든 값이라 사용자 입력 오류가 아니다 — 값을 넣지 않는다)."""
    if not isinstance(ref, str) or not _REF.fullmatch(ref):
        raise ValueError("보관소 번호의 모양이 올바르지 않다(용도:항목번호)")
    return ref


class SecretFields:
    """보관소에서 꺼낸 값 묶음 — `repr`·`str`·`format` 은 값을 보이지 않고 직렬화(pickle·copy)는 거절한다. 값은 `reveal(이름)` 으로만 꺼낸다(필요한 순간에만 꺼내 쓰고 버린다)."""

    __slots__ = ("_data",)

    def __init__(self, data):
        object.__setattr__(self, "_data", dict(data))

    def __setattr__(self, name, value):
        raise AttributeError("값 묶음은 바꿀 수 없다")

    def __delattr__(self, name):
        raise AttributeError("값 묶음은 바꿀 수 없다")

    def names(self):
        return tuple(sorted(self._data))

    def reveal(self, name):
        """그 칸의 값. 없는 칸은 KeyError(이름만 담긴다)."""
        return self._data[name]

    def to_dict(self):
        """모든 값을 새 dict 로(제공자 시험 함수에 넘길 때와 같은 값이 이미 있는지 견줄 때(`connections._same_value`)만 쓴다 — 받은 쪽도 짧게 쓰고 버려야 한다)."""
        return dict(self._data)

    def __len__(self):
        return len(self._data)

    def __contains__(self, name):
        return name in self._data

    def __repr__(self):
        return f"<SecretFields 칸 {len(self._data)}개 — 값은 가려져 있음>"

    __str__ = __repr__

    def __format__(self, spec):
        return repr(self)

    def __reduce__(self):
        raise TypeError("비밀 값 묶음은 직렬화하지 않는다")

    def __eq__(self, other):
        return self is other

    __hash__ = object.__hash__


def encode_fields(fields):
    """필드들 → JSON 한 덩어리의 UTF-16 바이트. 모양이 틀리면 TypeError(값 없이), 한도(2,560바이트)를 넘으면 KEY_TOO_LONG, 표현할 수 없는 글자가 있으면 KEY_INVALID_SHAPE — 어느 오류에도 값은 없다."""
    if not hasattr(fields, "items"):
        raise TypeError("fields 는 {이름: 글} 이어야 한다")
    clean = {}
    for name, value in fields.items():
        if not isinstance(name, str) or not _FIELD.fullmatch(name) or not isinstance(value, str):
            raise TypeError("fields 는 {이름: 글} 이어야 한다(이름은 영문 소문자·숫자·밑줄)")
        clean[name] = value
    if not clean or len(clean) > MAX_FIELDS:
        raise TypeError(f"fields 의 칸은 1~{MAX_FIELDS}개여야 한다")
    text = json.dumps(clean, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    try:
        raw = text.encode("utf-16-le")
    except UnicodeEncodeError:                                           # 짝 없는 대용 문자 — 예외 문구에 그 글자가 담기므로 우리 말로 바꾼다
        raise AppError("KEY_INVALID_SHAPE", {"항목": "값", "이유": "표시할 수 없는 글자가 들어 있습니다"}) from None
    if len(raw) > MAX_BLOB_BYTES:
        raise AppError("KEY_TOO_LONG", {"허용 용량": f"{MAX_BLOB_BYTES:,}바이트"}, detail=f"{len(raw):,}바이트(UTF-16)")
    return raw


def decode_fields(raw):
    """보관된 바이트 → `SecretFields`. 모양이 틀리면(다른 프로그램이 건드렸다 등) KEY_STORE_UNAVAILABLE — 내용은 담지 않는다."""
    try:
        data = json.loads(bytes(raw).decode("utf-16-le"))
    except (UnicodeDecodeError, ValueError) as error:
        raise _unavailable(f"보관된 값을 해석하지 못했다({type(error).__name__})") from None
    if (not isinstance(data, dict) or not data or len(data) > MAX_FIELDS
            or not all(isinstance(name, str) and _FIELD.fullmatch(name) and isinstance(value, str) for name, value in data.items())):
        raise _unavailable("보관된 값의 모양이 올바르지 않다")
    return SecretFields(data)


class KeyStore:
    """보관소 규약. 구현은 바이트 단위 네 가지(`_write`·`_read`·`_delete`·`_enumerate`)만 하고, 이름 검사·JSON 묶기·한도·오류 모양은 여기서 한 곳에서 한다."""

    is_fake = False

    def put(self, ref, fields):
        """값을 보관한다(이미 있으면 덮어쓴다)."""
        check_ref(ref)
        self._write(ref, encode_fields(fields))

    def get(self, ref):
        """`SecretFields`, 없으면 None."""
        check_ref(ref)
        raw = self._read(ref)
        return None if raw is None else decode_fields(raw)

    def delete(self, ref):
        """지웠으면 True, 원래 없었으면 False(멱등)."""
        check_ref(ref)
        return bool(self._delete(ref))

    def exists(self, ref):
        check_ref(ref)
        return self._read(ref) is not None

    def list_refs(self, prefix=""):
        """이 앱이 만든 항목의 ref 들(정렬). `prefix` 는 `용도:` 같은 앞부분(와일드카드 없음)."""
        if not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix):
            raise ValueError("목록 앞부분의 모양이 올바르지 않다")
        return sorted({ref for ref in self._enumerate(prefix) if _REF.fullmatch(ref) and ref.startswith(prefix)})

    # 구현이 채우는 바이트 단위 연산
    def _write(self, ref, raw):
        raise NotImplementedError

    def _read(self, ref):
        raise NotImplementedError

    def _delete(self, ref):
        raise NotImplementedError

    def _enumerate(self, prefix):
        raise NotImplementedError


class MemoryStore(KeyStore):
    """시험용 — 프로그램 안에서만 산다. 진짜 보관소와 같은 JSON·UTF-16·2,560바이트 규칙을 지난다."""

    def __init__(self):
        self._blobs = {}

    def __repr__(self):
        return f"<MemoryStore 항목 {len(self._blobs)}개>"

    def _write(self, ref, raw):
        self._blobs[ref] = bytes(raw)

    def _read(self, ref):
        return self._blobs.get(ref)

    def _delete(self, ref):
        return self._blobs.pop(ref, None) is not None

    def _enumerate(self, prefix):
        return [ref for ref in self._blobs if ref.startswith(prefix)]


# ---- Windows 자격 증명 관리자(ctypes) -----------------------------------------------------------------------------------------------
class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.c_uint32),
        ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


def _load_advapi32():
    """진짜 `advapi32` 를 불러 함수 모양을 정한다(Windows 에서만 — `WinDLL` 이 없으면 AttributeError)."""
    dll = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = ctypes.POINTER(_CREDENTIALW)
    dll.CredWriteW.argtypes = [pointer, ctypes.c_uint32]
    dll.CredWriteW.restype = ctypes.c_int
    dll.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(pointer)]
    dll.CredReadW.restype = ctypes.c_int
    dll.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    dll.CredDeleteW.restype = ctypes.c_int
    dll.CredEnumerateW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.POINTER(pointer))]
    dll.CredEnumerateW.restype = ctypes.c_int
    dll.CredFree.argtypes = [ctypes.c_void_p]
    dll.CredFree.restype = None
    return dll


class Win32CredApi:
    """`advapi32` 의 `Cred*` 함수를 파이썬 값으로 감싼 얇은 층. 오류 번호는 0 이면 성공이다. 시험은 `dll`·`get_last_error` 를 가짜로 바꿔 끼워 `CredFree`·메모리 정리까지 확인한다.
    넘겨받은 메모리는 읽은 뒤 바로 0 으로 덮고 어떤 길로 끝나도(예외 포함) `CredFree` 로 돌려준다."""

    def __init__(self, dll=None, get_last_error=None):
        self._dll = _load_advapi32() if dll is None else dll
        self._last_error = ctypes.get_last_error if get_last_error is None else get_last_error

    def _error(self):
        return int(self._last_error() or 0) or 1             # 실패했는데 번호가 0 이어도 성공으로 오해하지 않는다

    def write(self, target, raw):
        buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        try:
            credential = _CREDENTIALW()
            credential.Type = CRED_TYPE_GENERIC
            credential.TargetName = target
            credential.CredentialBlobSize = len(raw)
            credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            credential.Persist = CRED_PERSIST_LOCAL_MACHINE
            credential.UserName = USER_NAME
            return 0 if self._dll.CredWriteW(ctypes.byref(credential), 0) else self._error()
        finally:
            ctypes.memset(buffer, 0, len(raw))               # 넘긴 사본을 바로 지운다

    def read(self, target):
        """(오류 번호, 바이트 또는 None)."""
        found = ctypes.POINTER(_CREDENTIALW)()
        if not self._dll.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
            return self._error(), None
        if not found:                                             # 성공이라는데 돌려준 것이 없다 — 있을 수 없는 일이지만 널 포인터를 읽지 않는다
            return self._error(), None
        try:
            credential = found.contents
            size = int(credential.CredentialBlobSize)
            if not size or not credential.CredentialBlob:
                return 0, b""
            raw = ctypes.string_at(credential.CredentialBlob, size)
            ctypes.memset(credential.CredentialBlob, 0, size)         # 관리자가 돌려준 원본 메모리를 지운다
            return 0, raw
        finally:
            self._dll.CredFree(found)

    def delete(self, target):
        return 0 if self._dll.CredDeleteW(target, CRED_TYPE_GENERIC, 0) else self._error()

    def enumerate(self, pattern):
        """(오류 번호, 대상 이름들)."""
        count = ctypes.c_uint32(0)
        found = ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))()
        if not self._dll.CredEnumerateW(pattern, 0, ctypes.byref(count), ctypes.byref(found)):
            return self._error(), []
        try:
            names = []
            for index in range(int(count.value)):
                credential = found[index].contents
                names.append(credential.TargetName or "")
                if credential.CredentialBlobSize and credential.CredentialBlob:
                    ctypes.memset(credential.CredentialBlob, 0, int(credential.CredentialBlobSize))
            return 0, names
        finally:
            self._dll.CredFree(found)


class WindowsCredentialStore(KeyStore):
    """Windows 자격 증명 관리자 보관소. Windows 가 아니면(`api` 를 직접 넘기지 않은 한) 만들 수 없다 — `KEY_STORE_UNAVAILABLE`."""

    def __init__(self, api=None, *, windows=None):
        if api is None:
            if not ((os.name == "nt") if windows is None else windows):
                raise _unavailable("Windows 가 아닌 환경이라 자격 증명 관리자를 쓸 수 없다")
            try:
                api = Win32CredApi()
            except (AttributeError, OSError) as error:
                raise _unavailable(f"advapi32 를 불러오지 못했다({type(error).__name__})") from None
        self._api = api

    def __repr__(self):
        return "<WindowsCredentialStore>"

    @staticmethod
    def _target(ref):
        return f"{TARGET_PREFIX}:{ref}"

    def _write(self, ref, raw):
        number = self._api.write(self._target(ref), raw)
        if number:
            raise _unavailable(f"CredWriteW 실패(오류 번호 {number})")

    def _read(self, ref):
        number, raw = self._api.read(self._target(ref))
        if number == ERROR_NOT_FOUND:
            return None
        if number:
            raise _unavailable(f"CredReadW 실패(오류 번호 {number})")
        return raw

    def _delete(self, ref):
        number = self._api.delete(self._target(ref))
        if number == ERROR_NOT_FOUND:
            return False
        if number:
            raise _unavailable(f"CredDeleteW 실패(오류 번호 {number})")
        return True

    def _enumerate(self, prefix):
        head = TARGET_PREFIX + ":"
        number, names = self._api.enumerate(f"{head}{prefix}*")
        if number == ERROR_NOT_FOUND:
            return []
        if number:
            raise _unavailable(f"CredEnumerateW 실패(오류 번호 {number})")
        return [name[len(head):] for name in names if isinstance(name, str) and name.startswith(head)]


# ---- 시험 전용 가짜 파일 보관소 ----------------------------------------------------------------------------------------------------
class FileFakeStore(KeyStore):
    """**시험 전용** — 임시 폴더의 JSON 파일에 (가짜) 값을 적는 보관소. 진짜 키를 넣으면 평문 파일에 남으므로 `open_test_dir` 의 안전장치를 모두 통과해야만 열린다."""

    is_fake = True

    def __init__(self, folder):
        self._path = Path(folder) / TEST_FILE

    def __repr__(self):
        return "<FileFakeStore 시험 전용>"

    def _load(self):
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            raise _unavailable(f"시험용 보관 파일을 읽지 못했다({type(error).__name__})") from None
        if not isinstance(data, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in data.items()):
            raise _unavailable("시험용 보관 파일의 모양이 올바르지 않다")
        return data

    def _save(self, data):
        temp = self._path.with_name(TEST_FILE + ".tmp")
        try:
            temp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8", newline="\n")
            os.replace(temp, self._path)
        except OSError as error:
            leftover = ""
            try:
                temp.unlink(missing_ok=True)
            except OSError as stuck:                              # 못 지운 임시 파일도 숨기지 않고 오류 세부에 적는다
                leftover = f" | 임시 파일도 지우지 못했다({type(stuck).__name__})"
            raise _unavailable(f"시험용 보관 파일을 쓰지 못했다({type(error).__name__}){leftover}") from None

    def _write(self, ref, raw):
        data = self._load()
        data[ref] = bytes(raw).hex()
        self._save(data)

    def _read(self, ref):
        value = self._load().get(ref)
        if value is None:
            return None
        try:
            return bytes.fromhex(value)
        except ValueError:
            raise _unavailable("시험용 보관 파일의 값 모양이 올바르지 않다") from None

    def _delete(self, ref):
        data = self._load()
        if ref not in data:
            return False
        del data[ref]
        self._save(data)
        return True

    def _enumerate(self, prefix):
        return [ref for ref in self._load() if ref.startswith(prefix)]


def open_test_dir(env, *, temp_root=None):
    """시험 전용 보관소 폴더를 정한다 — 환경 변수가 정확히 `memory-file` 이고, 폴더가 **운영체제 임시 폴더 안**·이름이 `chanceblog-fake-keystore-` 로 시작·표시 파일이 있을 때만. 하나라도 틀리면 KEY_STORE_UNAVAILABLE."""
    if env.get(ENV_KEYSTORE, "") != TEST_STORE_VALUE:
        raise _unavailable(f"{ENV_KEYSTORE} 는 시험 전용이다(값은 {TEST_STORE_VALUE} 만 쓸 수 있다)")
    raw = env.get(ENV_KEYSTORE_DIR, "")
    if not isinstance(raw, str) or not raw or not os.path.isabs(raw):
        raise _unavailable("시험 전용 보관소의 폴더가 정해지지 않았다")
    try:
        folder = Path(os.path.realpath(raw))
        root = Path(os.path.realpath(temp_root if temp_root is not None else tempfile.gettempdir()))
        inside = root in folder.parents
        marked = inside and folder.name.startswith(TEST_DIR_PREFIX) and (folder / TEST_MARKER).is_file()
    except OSError as error:
        raise _unavailable(f"시험 전용 보관소 폴더를 확인하지 못했다({type(error).__name__})") from None
    if not marked:
        raise _unavailable("시험 전용 보관소의 폴더가 안전장치(임시 폴더 안·이름·표시 파일)를 통과하지 못했다")
    return folder


def default_keystore(env=None, *, windows=None, api=None, temp_root=None):
    """프로그램의 보관소. **환경 변수가 없으면 언제나 Windows 자격 증명 관리자**(Windows 가 아니면 KEY_STORE_UNAVAILABLE)다.
    `CHANCEBLOG_KEYSTORE` 가 있으면 시험 전용 가짜 파일 보관소를 안전장치를 모두 통과할 때만 연다(설치본 `sys.frozen` 에서는 환경 변수를 아예 무시한다)."""
    env = os.environ if env is None else env
    if env.get(ENV_KEYSTORE, "") != "" and not getattr(sys, "frozen", False):
        return FileFakeStore(open_test_dir(env, temp_root=temp_root))
    return WindowsCredentialStore(api, windows=windows)
