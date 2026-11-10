"""기존 글 읽기 기반(화면 없음) — 운영자가 파일 선택 창에서 직접 고른 본인 글 파일 1–2개를 **읽기만** 하는 서비스 함수(결정 D-325–D-329).
다음 묶음(N-3a, 본인 글의 문체 수치를 화면에 보여 주는 분석)이 쓸 읽기 길만 만든다. 이 모듈은 파일을 읽어 글(문자열)과 글자 수를 돌려줄 뿐이다.

규칙(모두 fail closed — 의심스러우면 읽지 않고 고정 문장으로 거절한다):
  · 한 번에 파일 1–2개(`MAX_FILES`), 파일 하나 2MB 이하(`MAX_FILE_BYTES`), 읽은 글 10만 자 이하(`MAX_TEXT_CHARS`), 형식은 `.txt`·`.md` 둘뿐(`ALLOWED_SUFFIXES`, 대소문자 무시).
    글이 10만 자를 넘으면 앞부분만 잘라 쓰지 않고 거절한다 — 조용히 일부만 분석하지 않는다.
  · 같은 파일을 두 번 고르면 거절한다(경로를 정리해 비교하고 윈도의 대소문자 차이·하드 링크도 같은 파일로 본다).
  · 경로는 문자열이나 `Path` 의 **절대 경로**만 받는다. 인터넷 주소 모양·네트워크 위치(`\\\\서버\\공유` 와 `//서버/공유`)·와일드카드(`*`·`?`)·제어 문자(NUL 포함)·빈 글·
    폴더·없는 파일·`..` 이 든 경로·윈도 장치 이름(`CON.txt`·`NUL.md` 같은 예약 이름 — 어느 운영체제에서나 같게 거절)·`:` 가 드라이브 문자 자리가 아닌 곳에 든 경로(대체 데이터 스트림)는 거절한다.
  · 심볼릭 링크·정션(윈도의 폴더 링크)은 따라가지 않고 거절한다 — 파일 자신뿐 아니라 경로 위의 모든 폴더를 확인한다. 클라우드 동기 폴더(OneDrive 등)의 파일은 링크가 아니라서 읽지만,
    이 PC 에 내려받지 않은 파일(윈도의 '오프라인' 표시)은 읽으면 내려받기가 일어나므로 거절한다(네트워크 접근 0). 이 '내려받지 않음' 표시는 파일 자신만 본다 — 경로 위 폴더는 링크 여부만 본다
    (폴더까지 넓히면 정상 OneDrive 폴더를 거짓으로 거절할 수 있어 운영자 PC 에서 확인한 뒤로 미뤘다).
  · 읽기 전에 `lstat` 으로 2MB 초과를 거절하고, 읽을 때도 최대 `MAX_FILE_BYTES + 1` 바이트까지만 읽어 그 사이 커진 파일도 거절한다. 읽기 모드는 `rb` 하나뿐이다. 연 파일 핸들의 상태(`fstat`)가
    검사 때의 상태와 같은 일반 파일인지도 확인한다 — 검사와 열기 사이에 같은 이름이 링크나 다른 파일로 바뀌면 읽지 않고 거절한다 — 열기는 이미 일어난 뒤다(파일 번호를 못 주는 파일 시스템은 일반 파일인지만 본다).
  · 글자표는 UTF-8(앞의 BOM 허용) → 안 되면 CP949(한국어 윈도 메모장의 옛 저장 방식) → 안 되면 거절한다. 어느 글자표로 읽었는지는 값의 `encoding`(`utf-8`·`cp949`)에 담는다 — 화면이
    'CP949 로 읽었어요, 글자가 깨져 보이면 UTF-8 로 저장해 다시 골라 주세요' 를 보일 수 있게. NUL 바이트(UTF-16 으로 저장했거나 그림·압축 파일)·빈 파일·공백이나 눈에 안 보이는 글자만 있는 글도
    거절한다. 줄 끝은 바꾸지 않는다(CRLF 는 두 글자로 센다 — 정리는 계산하는 쪽의 몫이다).
  · 반환값 말고는 아무것도 남기지 않는다: 파일을 만들거나 고치거나 지우지 않고(임시 파일·캐시 0), 로그·보관함·설정·클립보드·네트워크를 쓰지 않는다. 표준 라이브러리만 쓴다.
  · 오류는 기존 오류 체계의 `CONTENT_INVALID` 하나이고 문장은 고정이다 — **경로·파일 이름·글 내용을 오류·예외·로그에 되풀이하지 않는다**(OS 오류는 잡아서 버리고, 오류 객체에 앞 오류가 달라붙지 않게
    `except` 밖에서 낸다. `topics.import_seeds` 의 읽기 규칙과 같은 원칙이다). 읽은 뒤 거절하는 길(너무 긺·NUL·글자표·빈 글·읽다가 커짐)은 거절 직전에 읽은 바이트와 글을 비워, 오류의 호출 흔적이
    붙드는 지역 변수에 글이 남지 않게 한다.

알려 둔 한계: ① 윈도의 연결된 네트워크 드라이브(예: Z:)는 글자 모양만으로 알 수 없고 운영체제 질의 없이 판별할 수 없어 막지 못한다 — 파일 상태를 읽는 것이 곧 그 드라이브에 닿는 일이다.
리눅스·맥의 네트워크 마운트도 글자 모양으로 알아볼 수 없다(이 앱은 윈도 프로그램이라 영향은 CI 환경뿐이다). 드라이브 종류 조회(`GetDriveTypeW`)는 표준 라이브러리에 없고 서비스 층은 `ctypes` 를
쓰지 않으므로(`liveness.py` 한 곳만 예외) 쓰지 않았고, 진짜 매핑 드라이브에서의 동작은 확인하지 못했다.
② 검사와 읽기 사이의 바꿔치기는 열린 핸들의 상태 확인으로 읽지 않고 거절한다(열기 자체는 일어난 뒤다). 막지 못하는 것: 열기 자체가 내려받기를 일으키는 클라우드 파일(OneDrive 의 온라인 전용 파일 — 열기 전 표시로만 거른다)·파일 번호를
못 주는 파일 시스템(번호 0 — 일반 파일인지만 본다).
③ CP949 로 읽는 것은 'UTF-8 이 아니면' 이라는 기본값이라 다른 글자표의 글은 깨져 읽힐 수 있다 — EUC-JP·EUC-CN 으로 저장한 글은 한글 더미로 읽힐 수 있고(일본어 EUC-JP 표본 하나가 CP949 로 통과하는 것을
확인했다) ESC 같은 제어 문자가 든 7비트 글(ISO-2022-JP)은 거르지 않는다(NUL 만 거른다). 한자 비율로 거르는 방식은 쓰지 않았다.
④ 읽은 글을 이 모듈은 지우지 못한다 — 쥐고 있는 쪽이 쓰고 버려야 한다. 오류를 잡는 쪽은 `rendered().message` 만 꺼내고 `error.__traceback__ = None` 으로 비운다.
"""
from __future__ import annotations

import os
import re
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import AppError

SUBJECT = "기존 글 파일"
MAX_FILES = 2                                            # 한 번에 읽을 파일 수의 상한(운영자 확정)
MAX_FILE_BYTES = 2 * 1024 * 1024                         # 파일 하나의 상한(`topics.MAX_POST_BYTES` 와 같은 값 — 시험이 지킨다)
MAX_TEXT_CHARS = 100_000                                 # 읽은 글 글자 수의 상한(넘으면 잘라 쓰지 않고 거절)
ALLOWED_SUFFIXES = (".txt", ".md")                       # 소문자 — 비교는 대소문자를 무시한다
MAX_PATH_CHARS = 4096                                    # 경로 글의 상한(병적인 입력이 시간을 쓰지 않게)
ENCODINGS = ("utf-8", "cp949")                           # `OwnText.encoding` 이 가질 수 있는 값 — 읽은 글자표 이름

_CODECS = (("utf-8-sig", "utf-8"), ("cp949", "cp949"))   # (파이썬 글자표 이름, 돌려줄 이름) — 앞에서부터 시도한다(UTF-8 은 앞의 BOM 을 벗긴다)
_NAME_SURROGATE = 0x20000000                             # 윈도 재해석 지점 표(tag)의 '다른 이름을 가리킨다' 비트 — 심볼릭 링크·정션 등 링크 종류만 켜져 있다(OneDrive 같은 클라우드 표는 꺼져 있다)
_NOT_LOCAL = stat.FILE_ATTRIBUTE_OFFLINE | 0x00040000 | 0x00400000   # 오프라인·열 때 내려받기(RECALL_ON_OPEN)·데이터 접근 때 내려받기(RECALL_ON_DATA_ACCESS)
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]+:")      # 인터넷 주소 모양의 머리 — 두 글자 이상(한 글자는 드라이브 문자)
_DRIVE = re.compile(r"[A-Za-z]:")
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{name}{digit}" for name in ("COM", "LPT") for digit in "123456789¹²³"})   # 윈도가 장치로 읽는 이름(확장자가 붙어도)

# 거절 사유 — 사용자에게 보이는 고정 문장이다(경로·파일 이름·글은 어떤 문장에도 없다).
_R_COUNT = f"파일은 한 번에 1개에서 {MAX_FILES}개까지만 고를 수 있어요"
_R_LIST = "고른 파일 목록의 모양이 올바르지 않아요"
_R_SAME = "같은 파일을 두 번 골랐어요. 서로 다른 파일을 골라 주세요"
_R_PATH = "파일 위치가 올바르지 않아요. 이 PC 에 저장된 파일을 파일 선택 창에서 직접 골라 주세요"
_R_NETWORK = "인터넷 주소나 네트워크 위치의 파일은 읽지 않아요. 이 PC 에 저장된 파일을 골라 주세요"
_R_SUFFIX = f"이 형식은 아직 읽지 않아요. {' 와 '.join(ALLOWED_SUFFIXES)} 파일만 골라 주세요"
_R_RESERVED = "윈도에서 장치 이름으로 쓰이는 파일 이름은 읽지 않아요. 파일 이름을 바꾼 뒤 골라 주세요"
_R_MISSING = "파일을 읽을 수 없어요. 파일이 있는지, 열 수 있는 파일인지 확인해 주세요"
_R_CHANGED = "고른 뒤에 파일이 바뀐 것 같아요. 파일을 다시 골라 주세요"
_R_NOT_FILE = "글 파일이 아니에요. 폴더나 장치가 아니라 파일을 골라 주세요"
_R_LINK = "바로 가기나 링크로 연결된 파일은 읽지 않아요. 원래 파일을 직접 골라 주세요"
_R_CLOUD = "이 PC 에 내려받지 않은 파일이에요. 먼저 내려받은 뒤 다시 골라 주세요"
_R_BIG = f"파일이 너무 커요. {MAX_FILE_BYTES // (1024 * 1024)}MB 이하 파일만 읽어요"
_R_BINARY = "글 파일이 아닌 것 같아요. 그림·압축 파일이거나 UTF-16 으로 저장한 파일일 수 있어요(UTF-8 로 저장한 파일을 골라 주세요)"
_R_ENCODING = "글자 모양을 읽을 수 없어요. 메모장의 '다른 이름으로 저장' 에서 UTF-8 로 저장한 뒤 다시 골라 주세요"
_R_EMPTY = "읽을 글이 없어요"
_R_LONG = f"글이 너무 길어요. {MAX_TEXT_CHARS:,}자 이하만 읽어요(일부만 잘라서 쓰지는 않아요)"


@dataclass(frozen=True)
class OwnText:
    """파일 하나에서 읽은 글과 글자 수(파이썬 글자 기준 — 줄 끝 글자도 센다)와 읽은 글자표 이름(`utf-8` 또는 `cp949` — `cp949` 면 UTF-8 이 아니라서 옛 메모장 글자표로 읽은 것이라 글자가 깨져 보일 수 있다).
    불변이고, 글은 `repr` 에 나오지 않는다(오류·로그에 글이 새지 않게)."""
    text: str = field(repr=False)
    chars: int
    encoding: str = "utf-8"

    def __post_init__(self):
        if not isinstance(self.text, str) or isinstance(self.chars, bool) or self.chars != len(self.text) or self.encoding not in ENCODINGS:
            raise ValueError("글자 수나 글자표 이름이 글과 맞지 않는다")


def _refuse(reason):
    """기존 오류 체계(`CONTENT_INVALID`)의 고정 문장 오류 — 경로·파일 이름·글은 문장에도 세부에도 없다."""
    return AppError("CONTENT_INVALID", {"항목": f"{SUBJECT} — {reason}"}, detail=reason)


# ---- 1) 경로 모양 검사(파일을 만지지 않는다) ------------------------------------------------------------------------------------------
def _shape(path):
    """경로 하나의 모양 검사 → (정리한 Path, None) 또는 (None, 사유). 운영체제 질의를 하지 않으므로 어느 운영체제에서나 같은 결과다."""
    if not isinstance(path, (str, Path)):
        return None, _R_PATH
    text = os.fspath(path)
    if not text.strip() or len(text) > MAX_PATH_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return None, _R_PATH
    plain = text.lstrip()
    if plain.replace("/", "\\").startswith("\\\\") or _SCHEME.match(plain):
        return None, _R_NETWORK
    if "*" in text or "?" in text or (text[2:] if _DRIVE.match(text) else text).count(":") or text[-1] in "/\\":
        return None, _R_PATH
    pure = Path(text)
    if not pure.is_absolute() or ".." in pure.parts:
        return None, _R_PATH
    if pure.suffix.lower() not in ALLOWED_SUFFIXES:
        return None, _R_SUFFIX
    if pure.name.split(".", 1)[0].rstrip(" ").upper() in _RESERVED:
        return None, _R_RESERVED
    return pure, None


# ---- 2) 파일 상태 검사(읽지 않고 상태만 본다) -----------------------------------------------------------------------------------------
def _lstat(path):
    """링크를 따라가지 않는 상태 정보 또는 None(없음·권한·잘못된 글자 …). OS 오류의 글에는 경로가 들어 있으므로 버린다."""
    try:
        return os.lstat(path)
    except (OSError, ValueError):
        return None


def _link_like(info):
    """심볼릭 링크이거나 윈도의 이름을 가리키는 재해석 지점(정션 등)인가."""
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT) and bool(getattr(info, "st_reparse_tag", 0) & _NAME_SURROGATE)


def _inspect(pure):
    """링크 없는 경로 위의 일반 파일이고 읽을 수 있는 크기인지 본다 → (상태 정보, None) 또는 (None, 사유)."""
    parts = pure.parts
    current, info = Path(parts[0]), None
    for part in parts[1:]:
        current = current / part
        info = _lstat(current)
        if info is None:
            return None, _R_MISSING
        if _link_like(info):
            return None, _R_LINK
    if info is None:
        return None, _R_MISSING
    if not stat.S_ISREG(info.st_mode):
        return None, _R_NOT_FILE
    if getattr(info, "st_file_attributes", 0) & _NOT_LOCAL:
        return None, _R_CLOUD
    if info.st_size > MAX_FILE_BYTES:
        return None, _R_BIG
    return info, None


def _same(first, second):
    """같은 파일인가 — 장치·파일 번호가 같고 번호가 0 이 아닐 때(번호를 못 주는 파일 시스템의 우연한 일치를 같은 파일로 보지 않는다)."""
    return bool(first.st_ino) and os.path.samestat(first, second)


# ---- 3) 읽기(rb 로 상한 + 1 바이트까지만) · 글자표 · 글 검사 -----------------------------------------------------------------------------
def _read_prefix(path, limit, expected):
    """파일 앞부분을 최대 `limit` 바이트까지만 읽는다(읽기 전용 `rb`) → (바이트, None) 또는 (None, 사유).
    연 파일 핸들의 상태(`fstat`)가 일반 파일이고 검사 때의 상태(`expected`)와 같은 파일일 때만 읽는다 — 검사와 열기 사이에 같은 이름이 링크나 다른 파일로 바뀌었으면 거절한다
    (파일 번호를 못 주는 파일 시스템 — 번호 0 — 은 일반 파일인지만 본다). 열 수 없으면 사유는 '읽을 수 없음' 이고 OS 오류의 글은 버린다."""
    try:
        with open(path, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or (expected.st_ino and not os.path.samestat(expected, opened)):
                return None, _R_CHANGED
            chunks, total = [], 0
            while total < limit:
                piece = handle.read(limit - total)
                if not piece:
                    break
                chunks.append(piece)
                total += len(piece)
    except (OSError, ValueError):
        return None, _R_MISSING
    return b"".join(chunks), None


def _decode(data):
    """바이트 → (글, 글자표 이름, None) 또는 (None, None, 사유). UTF-8(BOM 허용) → CP949 순이고 NUL 이 있으면 글 파일로 보지 않는다."""
    if b"\x00" in data:
        return None, None, _R_BINARY
    for codec, name in _CODECS:
        try:
            return data.decode(codec), name, None
        except UnicodeDecodeError:
            continue
    return None, None, _R_ENCODING


def _has_visible(text):
    """공백·제어·서식 글자(폭 없는 공백 등)가 아닌 글자가 하나라도 있는가."""
    return any(not ch.isspace() and unicodedata.category(ch)[0] != "C" for ch in text)


def _check_text(text):
    """읽은 글의 길이·내용 검사 → 사유 또는 None. 잘라 쓰지 않는다."""
    if len(text) > MAX_TEXT_CHARS:
        return _R_LONG
    if "\x00" in text:
        return _R_BINARY
    if not _has_visible(text):
        return _R_EMPTY
    return None


def _read_one(pure, expected):
    """검사를 마친 파일 하나를 읽어 `OwnText` 로(`expected` 는 검사 때의 상태). 열다가 바뀐 것을 안 파일·읽다가 커진 파일·글자표·길이·빈 글은 여기서 거절한다.
    읽은 뒤 거절할 때는 오류를 내기 직전에 읽은 바이트와 글을 비운다 — 오류의 호출 흔적이 이 함수의 지역 변수를 붙들기 때문이다."""
    data, reason = _read_prefix(pure, MAX_FILE_BYTES + 1, expected)
    if reason is not None:
        raise _refuse(reason)
    if len(data) > MAX_FILE_BYTES:
        data = None
        raise _refuse(_R_BIG)
    text, encoding, reason = _decode(data)
    data = None
    if reason is None:
        reason = _check_text(text)
    if reason is not None:
        text = None
        raise _refuse(reason)
    return OwnText(text, len(text), encoding)


# ---- 4) 공개 함수 ------------------------------------------------------------------------------------------------------------------
def _shapes(paths):
    """개수·모양·같은 경로 두 번을 파일을 만지지 않고 검사한다 → 정리한 Path 목록."""
    if not isinstance(paths, (list, tuple)):
        raise _refuse(_R_LIST)
    if not 1 <= len(paths) <= MAX_FILES:
        raise _refuse(_R_COUNT)
    pures = []
    for path in paths:
        pure, reason = _shape(path)
        if reason is not None:
            raise _refuse(reason)
        pures.append(pure)
    if len({os.path.normcase(str(pure)) for pure in pures}) < len(pures):
        raise _refuse(_R_SAME)
    return pures


def _inspect_all(pures):
    """모든 파일의 상태를 읽기 전에 확인한다(링크·종류·크기·같은 파일 두 번) — 하나라도 안 되면 아무것도 읽지 않는다. 확인한 상태를 파일 순서대로 돌려준다(읽을 때 같은 파일인지 견준다)."""
    infos = []
    for pure in pures:
        info, reason = _inspect(pure)
        if reason is not None:
            raise _refuse(reason)
        if any(_same(earlier, info) for earlier in infos):
            raise _refuse(_R_SAME)
        infos.append(info)
    return infos


def read_own_files(paths):
    """운영자가 고른 txt·md 파일 1–2개를 읽어 `OwnText`(글·글자 수·글자표 이름) 튜플을 **입력 순서대로** 돌려준다. 하나라도 거절되면 아무것도 돌려주지 않는다(일부만 읽지 않는다 — 몇 번째 파일인지도 알리지 않는다).
    `paths` 는 문자열·`Path` 의 목록(list·tuple)이다. 거절은 `AppError("CONTENT_INVALID")`(고정 문장 — 경로·파일 이름·글은 없다). 읽는 것 말고는 아무 일도 하지 않는다(쓰기·로그·캐시·네트워크 0)."""
    pures = _shapes(paths)
    infos = _inspect_all(pures)
    return tuple(_read_one(pure, info) for pure, info in zip(pures, infos, strict=True))


__all__ = ["OwnText", "read_own_files"]
