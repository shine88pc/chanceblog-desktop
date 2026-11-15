"""참고 글 보관함(래퍼런스 글 보관함, 결정 D-489) — 운영자가 올려 둔 참고 글을 사용자 데이터 폴더 안 `references/` 폴더에 **글 하나당 파일 하나**로 보관하는 서비스(화면 없음).
프로그램을 닫았다 열어도 남고, 목록·열기·고치기·지우기를 한다. 이 보관함은 글을 모아 두고 고쳐 쓰는 곳일 뿐이다 — 글을 AI 나 네트워크로 보내는 길이 없고, 첫 판은 전체 백업에도 담지 않는다.

규칙(모두 fail closed — 의심스러우면 쓰지도 읽지도 않고 고정 문장으로 거절한다):
  · **위치** — `ctx.workspace.root`(= `Workspace.resolve` 가 정한 사용자 데이터 폴더, 새 경로 계산을 만들지 않았다) 아래 `references/ref-<번호>.json`. 글 하나 = 파일 하나(UTF-8, BOM 없음, 내용은
    `schema`·`id`·`title`·`body`·`created_at`·`updated_at` 여섯 칸뿐). 읽기만 하는 길(목록·열기)은 폴더가 없으면 빈 목록이고 아무것도 만들지 않는다.
  · **번호는 앱이 만든다** — 영문 소문자·숫자 8자(`new_id`, 운영체제의 무작위 값). **사용자가 준 글자는 어떤 경우에도 파일 이름이나 경로가 되지 않는다.** 열기·고치기·지우기가 받은 번호도 `[a-z0-9]{8}` 모양일 때만
    쓰고 아니면 파일을 만지지 않고 거절한다(`../`·경로 구분자·빈 글·긴 글·글자 아닌 값 모두). 파일 이름에서 번호를 읽는 것은 정확한 이름 모양(`ref-` + 번호 + `.json`)일 때뿐이고 그 밖의 파일은 없는 것으로 본다.
  · **한도** — 보관 개수 최대 `MAX_REFERENCES`(50, 모양이 맞는 파일은 깨진 것도 센다), 제목 1–80자(앞뒤 공백은 걷고, 공백이나 눈에 안 보이는 글자뿐이거나 줄 바꿈 같은 제어 문자가 있으면 거절),
    본문 1–100,000자(`own_posts.MAX_TEXT_CHARS` 와 같은 값 — 넘으면 잘라 쓰지 않고 거절). 본문은 글자 하나도 바꾸지 않고 그대로 둔다(줄 끝·공백·정규화 없음).
  · **파일에서 올리기** 는 `own_posts.read_own_files` 를 그대로 쓴다 — 경로 안전·크기(2MB)·링크·글자표(UTF-8 → CP949)·빈 글 규칙을 새로 만들지 않았다. 거절 문장도 같다. 제목을 안 주면 파일 이름(확장자 뺀 것)에서 만든다.
  · **저장은 원자적이다** — `context.write_json`(임시 파일에 다 쓰고 디스크에 내려보낸 뒤 이름을 바꿔 넣는다)이 한다. 쓰다 멈추거나 전원이 나가도 옛 파일이 그대로 남고 반쯤 쓴 파일이 자리를 차지하지 않는다. 쓰기 실패(`FILE_WRITE_FAILED`·`DISK_FULL`)의 문장에는
    실제 경로 대신 고정 이름 `참고 글 보관함 폴더` 를 쓴다.
  · **지우기는 파일 하나만 정확히 지운다** — 확인(`confirmed=True`)이 있어야 하고(아니면 아무것도 하지 않고 `CONFIRMATION_REQUIRED`), 번호가 정한 파일 하나의 `unlink` 뿐이다(폴더·다른 글·다른 파일은 그대로, 링크나 폴더는 거절).
    지운 글은 되돌릴 수 없다(보관함은 백업에 들지 않는다).
  · **깨진 파일은 건너뛴다** — 목록은 읽을 수 없는 파일(JSON 불량·칸 모양 틀림·한도 초과·1MB 초과·파일 이름과 `id` 가 다름·링크·폴더)을 빼고 건너뛴 개수(`skipped`)만 알린다. 앱을 멈추지 않고 깨진 파일을 고치거나 지우거나 덮어쓰지 않는다.
  · **글·제목·경로는 오류·로그·예외에 되풀이하지 않는다** — 오류는 기존 오류 체계의 `CONTENT_INVALID`·`CONTENT_NOT_FOUND`·`CONFIRMATION_REQUIRED`·`FILE_WRITE_FAILED`·`DISK_FULL` 이고 문장은 고정이다(`Reference`·`Entry` 의 `repr` 에도 글·제목이 없다).
    OS 오류는 잡아서 버리고 오류는 `except` 밖에서 내며, 거절 직전에 이 모듈의 틀이 쥔 글을 비운다(호출 흔적이 글을 붙들지 않게). 이 모듈을 부르는 쪽이 쥔 글은 부른 쪽 몫이다 — 쓰고 버린다.
  · 표준 라이브러리와 기존 서비스 함수만 쓴다: 네트워크·하위 프로세스·AI·표준 출력·로그 0. 새 시계를 읽지 않는다(`ctx.stamp()`).
알려 둔 한계: 보관함은 글을 암호화하지 않는다(이 PC 의 사용자 데이터 폴더에 평문 JSON 이다 — 다른 사용자가 읽을 수 있는 폴더를 데이터 폴더로 고르면 그 사용자도 읽는다). 같은 번호의 동시 저장을 막는 잠금은 없다(앱은 한 번에 하나만 열린다).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import AppError
from . import own_posts
from .context import write_json
from .projects import require_confirmation

SUBJECT = "참고 글 보관함"
FOLDER = "references"                                    # 사용자 데이터 폴더 아래 폴더 이름
FILE_PREFIX, FILE_SUFFIX = "ref-", ".json"
SCHEMA = 1
ID_CHARS = 8
ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
MAX_REFERENCES = 50                                      # 보관할 글의 개수 상한
TITLE_MIN, TITLE_MAX = 1, 80                             # 제목 글자 수(앞뒤 공백을 걷은 뒤)
MAX_BODY_CHARS = 100_000                                 # 본문 글자 수의 상한 — `own_posts.MAX_TEXT_CHARS` 와 같은 값(시험이 견준다)
MAX_FILE_BYTES = 1024 * 1024                             # 보관 파일 하나의 상한(본문 10만 자가 모두 3바이트 글자이거나 제어 문자로 풀려도 들어간다)
DEFAULT_TITLE = "가져온 글"                              # 파일 이름에서 쓸 만한 제목을 못 얻을 때
ID_TRIES = 50                                            # 번호가 겹칠 때 다시 만드는 횟수

_KEYS = frozenset({"schema", "id", "title", "body", "created_at", "updated_at"})
_ID = re.compile(r"[a-z0-9]{8}")
_NAME = re.compile(r"ref-([a-z0-9]{8})\.json")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_BAD_TITLE_CATEGORIES = frozenset({"Cc", "Cs", "Zl", "Zp"})      # 제어 문자·짝 없는 대리 문자·줄·문단 구분 문자
_WHERE = "참고 글 보관함 폴더"                            # 쓰기 실패 문장에 실제 경로 대신 쓰는 고정 이름

# 거절 사유 — 사용자에게 보이는 고정 문장이다(글·제목·경로·번호는 어떤 문장에도 없다).
_R_ID = "참고 글 번호가 올바르지 않아요"
_R_TITLE_EMPTY = "제목을 적어 주세요"
_R_TITLE_LONG = f"제목은 {TITLE_MAX}자까지만 적을 수 있어요"
_R_TITLE_CHARS = "제목에는 줄 바꿈 같은 제어 문자를 쓸 수 없어요"
_R_FORM = "글자를 저장할 수 없는 모양이에요. 글을 다시 붙여 넣어 주세요"
_R_FULL = f"참고 글은 {MAX_REFERENCES}개까지만 보관할 수 있어요. 쓰지 않는 글을 지운 뒤 다시 올려 주세요"
_R_FOLDER = "참고 글 보관함 폴더가 올바르지 않아요. 바로 가기나 파일이 아닌 폴더여야 해요"
_R_FOLDER_READ = "참고 글 보관함 폴더를 읽을 수 없어요"
_R_BROKEN = "보관된 글 파일이 올바르지 않아 열지 않았어요"
_R_NO_ID = "새 글 번호를 만들지 못했어요. 잠시 뒤 다시 해 주세요"
_NOT_FOUND = "참고 글"


@dataclass(frozen=True)
class Reference:
    """보관한 글 하나 — 번호·제목·본문·만든 때·고친 때(`2026-11-15T13:00:00Z` 꼴의 UTC). 불변이고 제목과 본문은 `repr` 에 나오지 않는다."""
    ref_id: str
    title: str = field(repr=False)
    body: str = field(repr=False)
    created_at: str
    updated_at: str

    @property
    def chars(self):
        return len(self.body)


@dataclass(frozen=True)
class Entry:
    """목록 한 줄 — 번호·제목·본문 글자 수·만든 때·고친 때. 본문은 없고 제목은 `repr` 에 나오지 않는다."""
    ref_id: str
    title: str = field(repr=False)
    chars: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Listing:
    """보관한 글들(고친 때가 늦은 것부터) + 읽을 수 없어 건너뛴 파일의 개수."""
    entries: tuple
    skipped: int = 0

    @property
    def total(self):
        return len(self.entries) + self.skipped


@dataclass(frozen=True)
class FileAdded:
    """파일에서 올린 결과 — 보관한 글과 읽은 글자표 이름(`utf-8`·`cp949`, `cp949` 면 글자가 깨져 보일 수 있다)."""
    reference: Reference
    encoding: str


def _refuse(reason):
    """기존 오류 체계(`CONTENT_INVALID`)의 고정 문장 오류 — 글·제목·경로·번호는 문장에도 세부에도 없다."""
    return AppError("CONTENT_INVALID", {"항목": f"{SUBJECT} — {reason}"}, detail=reason)


def _not_found():
    return AppError("CONTENT_NOT_FOUND", {"항목": _NOT_FOUND}, detail="없는 참고 글")


def new_id():
    """새 글 번호 — 영문 소문자·숫자 8자(운영체제의 무작위 값). 사용자 입력에서 오지 않는다(시험이 바꿔 끼우는 자리이기도 하다)."""
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_CHARS))


def is_id(ref_id):
    """번호 모양(`[a-z0-9]{8}` 의 글)인가 — 파일 이름이 되어도 되는 값은 이것뿐이다."""
    return isinstance(ref_id, str) and _ID.fullmatch(ref_id) is not None


def folder_path(ctx):
    """보관함 폴더의 위치(`<사용자 데이터 폴더>/references`) — 화면의 위치 안내용이다. 폴더를 만들지도 읽지도 않는다."""
    return ctx.workspace.root / FOLDER


def _file_of(ctx, ref_id):
    """번호(`is_id` 를 통과한 것만 — 부르는 쪽이 먼저 확인한다) → 파일 위치. 사용자가 준 글자가 경로가 되는 곳은 없다."""
    return folder_path(ctx) / f"{FILE_PREFIX}{ref_id}{FILE_SUFFIX}"


def _lstat(path):
    """링크를 따라가지 않는 상태 정보 또는 None(없음·권한·잘못된 글자 …). OS 오류의 글에는 경로가 들어 있으므로 버린다."""
    try:
        return os.lstat(path)
    except (OSError, ValueError):
        return None


def _scan(folder):
    """보관함 폴더 안에서 정확한 이름 모양(`ref-` + 번호 + `.json`)인 파일들의 번호(정렬) → `(번호들, None)` 또는 `(None, 오류 객체)` — 폴더가 없으면 빈 목록이고 아무것도 만들지 않는다.
    폴더가 링크이거나 폴더가 아니거나 읽을 수 없으면 **아직 내지 않은** 오류 객체를 돌려준다(부른 쪽이 글을 비운 뒤에 낸다 — 호출 흔적이 글을 붙들지 않게)."""
    info = _lstat(folder)
    if info is None:
        return [], None
    if not stat.S_ISDIR(info.st_mode) or own_posts._link_like(info):
        return None, _refuse(_R_FOLDER)
    names = None
    try:
        with os.scandir(folder) as entries:
            names = [entry.name for entry in entries]
    except OSError:
        names = None
    if names is None:                                      # `except` 밖에서 만든다 — OS 오류(경로가 든 글)가 따라붙지 않게
        return None, _refuse(_R_FOLDER_READ)
    return sorted(found.group(1) for found in (_NAME.fullmatch(name) for name in names) if found), None


# ---- 검사 -----------------------------------------------------------------------------------------------------------------------------
def _encodable(text):
    """UTF-8 로 저장할 수 있는 글인가(짝 없는 대리 문자가 없다) — 저장 길이 글이 든 예외로 터지지 않게 미리 본다."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _title_reason(title):
    """이미 앞뒤 공백을 걷은 제목의 거절 사유 또는 None."""
    if not isinstance(title, str) or not own_posts._has_visible(title) or len(title) < TITLE_MIN:
        return _R_TITLE_EMPTY
    if len(title) > TITLE_MAX:
        return _R_TITLE_LONG
    if any(unicodedata.category(ch) in _BAD_TITLE_CATEGORIES for ch in title):
        return _R_TITLE_CHARS
    return None


def _check(title, body):
    """제목·본문 검사 → `(정리한 제목, 본문, None)` 또는 `(None, None, 사유)`. 본문은 하나도 바꾸지 않고 한도(10만 자·NUL·빈 글)는 파일 읽기와 같은 검사(`own_posts._check_text`)다."""
    clean = title.strip() if isinstance(title, str) else title
    reason = _title_reason(clean)
    if reason is None:
        if not isinstance(body, str):
            reason = own_posts._R_EMPTY
        elif len(body) > MAX_BODY_CHARS:                   # 이 모듈의 한도도 직접 지킨다(파일 읽기 쪽 한도와 같은 값 — 시험이 견준다)
            reason = own_posts._R_LONG
        else:
            reason = own_posts._check_text(body)
    if reason is None and not (_encodable(clean) and _encodable(body)):
        reason = _R_FORM
    if reason is not None:
        return None, None, reason
    return clean, body, None


def _from_raw(raw, ref_id):
    """읽은 JSON → `Reference` 또는 None(칸이 틀렸다 — 깨진 파일). 칸 이름이 정확히 여섯 개여야 하고 `id` 는 파일 이름의 번호와 같아야 한다."""
    if not isinstance(raw, dict) or set(raw) != _KEYS or type(raw["schema"]) is not int or raw["schema"] != SCHEMA or raw["id"] != ref_id:
        return None
    title, body, created, updated = raw["title"], raw["body"], raw["created_at"], raw["updated_at"]
    if not all(isinstance(value, str) for value in (title, body, created, updated)):
        return None
    if title != title.strip() or _title_reason(title) is not None or own_posts._check_text(body) is not None:
        return None
    if _STAMP.fullmatch(created) is None or _STAMP.fullmatch(updated) is None:
        return None
    return Reference(ref_id, title, body, created, updated)


def _read_file(path, ref_id):
    """보관 파일 하나를 읽는다 → `(Reference, "")` · `(None, "missing")`(없다) · `(None, "broken")`(읽을 수 없다 — 모양·크기·링크·글자·칸 어느 것이든). 글자 하나도 오류로 내보내지 않는다."""
    info = _lstat(path)
    if info is None:
        return None, "missing"
    if not stat.S_ISREG(info.st_mode) or own_posts._link_like(info) or info.st_size > MAX_FILE_BYTES:
        return None, "broken"
    data, reason = own_posts._read_prefix(path, MAX_FILE_BYTES + 1, info)       # 읽기 전용 `rb` 로 상한 + 1 바이트까지만, 검사 때와 같은 파일인지 확인한다(`own_posts` 의 읽기 규칙 그대로)
    if reason is not None or len(data) > MAX_FILE_BYTES:
        return None, "broken"
    try:
        raw = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):                  # UnicodeDecodeError 와 BOM·문법 오류는 ValueError 다
        return None, "broken"
    found = _from_raw(raw, ref_id)
    return (found, "") if found is not None else (None, "broken")


def _save(ctx, ref):
    """보관 파일 하나를 원자적으로 쓴다(`context.write_json` — 임시 파일 → 디스크에 내려보냄 → 이름 바꾸기) → 성공이면 None, 실패면 **아직 내지 않은** 오류 객체(경로 없는 고정 이름의 `FILE_WRITE_FAILED`·`DISK_FULL`).
    오류를 내는 일은 부른 쪽이 글을 비운 뒤에 한다 — 이 틀과 부른 틀의 호출 흔적이 글을 붙들지 않게."""
    data = {"schema": SCHEMA, "id": ref.ref_id, "title": ref.title, "body": ref.body, "created_at": ref.created_at, "updated_at": ref.updated_at}
    failure = None
    try:
        write_json(_file_of(ctx, ref.ref_id), data)
    except AppError as error:
        failure = error.code
        error.__traceback__ = None                         # 호출 흔적이 붙드는 글·경로를 놓는다
    finally:
        data = None
    if failure is None:
        return None
    return AppError("DISK_FULL" if failure == "DISK_FULL" else "FILE_WRITE_FAILED", {"경로": _WHERE}, detail="참고 글 파일을 쓰지 못했다")      # 앞 오류(경로가 든 글)는 따라붙지 않는다 — `except` 밖에서 새로 만든다


def _free_id(ctx, taken):
    """폴더에 없는 새 번호(`new_id`). 겹치면 `ID_TRIES` 번까지 다시 만들고 그래도 못 찾으면 None(부른 쪽이 거절한다)."""
    for _ in range(ID_TRIES):
        candidate = new_id()
        if is_id(candidate) and candidate not in taken and _lstat(_file_of(ctx, candidate)) is None:
            return candidate
    return None


# ---- 공개 함수 --------------------------------------------------------------------------------------------------------------------------
def _add(ctx, title, body):
    """검사 → 번호 정하기 → 저장 → `(Reference, None)` 또는 `(None, 아직 내지 않은 오류 객체)`. 오류를 내는 일(과 그 전에 글을 비우는 일)은 부른 쪽이 한다 — 이 틀이 돌아온 뒤에는 호출 흔적에 남지 않는다."""
    title, body, reason = _check(title, body)
    if reason is not None:
        return None, _refuse(reason)
    taken, problem = _scan(folder_path(ctx))
    if problem is not None:
        return None, problem
    if len(taken) >= MAX_REFERENCES:
        return None, _refuse(_R_FULL)
    ref_id = _free_id(ctx, taken)
    if ref_id is None:
        return None, _refuse(_R_NO_ID)
    stamp = ctx.stamp()
    ref = Reference(ref_id, title, body, stamp, stamp)
    problem = _save(ctx, ref)
    return (None, problem) if problem is not None else (ref, None)


def add_reference(ctx, *, title, body):
    """붙여 넣은 글을 보관한다 → `Reference`. 제목·본문이 한도(제목 1–80자·본문 1–100,000자)를 넘거나 보관함이 가득 차 있으면 아무것도 쓰지 않고 `CONTENT_INVALID`(고정 문장). 새 번호·만든 때는 이 함수가 정한다."""
    found, problem = _add(ctx, title, body)
    if problem is not None:
        title = body = None
        raise problem
    return found


def _title_from_path(path):
    """파일 이름(확장자 뺀 것)에서 제목을 만든다 — 쓸 수 없는 모양이면 `DEFAULT_TITLE`."""
    stem = " ".join(Path(os.fspath(path)).stem.split())[:TITLE_MAX].strip()
    return stem if _title_reason(stem) is None else DEFAULT_TITLE


def add_from_file(ctx, path, *, title=None):
    """운영자가 고른 txt·md 파일 하나를 보관한다 → `FileAdded`(보관한 글 + 읽은 글자표 이름). 읽기 규칙은 `own_posts.read_own_files` 그대로(경로·크기·링크·글자표·빈 글 — 거절 문장도 같고 경로·파일 이름은 없다).
    `title` 을 주지 않으면(또는 공백뿐이면) 파일 이름에서 만든다."""
    reason = None
    items = None
    try:
        items = own_posts.read_own_files([path])
    except AppError as error:
        reason = error.detail or own_posts._R_PATH
        error.__traceback__ = None
    if reason is not None:                                 # `except` 밖에서 낸다 — 경로가 든 앞 오류가 따라붙지 않게
        path = title = None
        raise _refuse(reason)
    chosen = title.strip() if isinstance(title, str) and title.strip() else _title_from_path(path)
    item, items = items[0], None
    found, problem = _add(ctx, chosen, item.text)
    if problem is not None:
        path = title = chosen = item = None
        raise problem
    return FileAdded(found, item.encoding)


def list_references(ctx):
    """보관한 글 목록(고친 때가 늦은 것부터, 같으면 번호 순) — 읽기만 한다. 읽을 수 없는 파일은 건너뛰고 개수만 `skipped` 로 알린다. 보관함 폴더가 없으면 빈 목록이고 아무것도 만들지 않는다.
    모양이 맞는 파일이 `MAX_REFERENCES` 개를 넘으면(손으로 넣었다) 앞의 50개만 읽고 나머지는 건너뛴 것으로 센다."""
    found, problem = _scan(folder_path(ctx))
    if problem is not None:
        raise problem
    entries, skipped = [], max(0, len(found) - MAX_REFERENCES)
    for ref_id in found[:MAX_REFERENCES]:
        ref, _problem = _read_file(_file_of(ctx, ref_id), ref_id)
        if ref is None:
            skipped += 1
            continue
        entries.append(Entry(ref.ref_id, ref.title, ref.chars, ref.created_at, ref.updated_at))
    entries.sort(key=lambda entry: (entry.updated_at, entry.created_at, entry.ref_id), reverse=True)
    return Listing(tuple(entries), skipped)


def open_reference(ctx, ref_id):
    """보관한 글 한 편(`Reference`)을 읽는다. 번호 모양이 틀리면 `CONTENT_INVALID`, 없으면 `CONTENT_NOT_FOUND`, 읽을 수 없는 파일이면 `CONTENT_INVALID`(고치거나 지우지 않는다)."""
    if not is_id(ref_id):
        ref_id = None
        raise _refuse(_R_ID)
    ref, problem = _read_file(_file_of(ctx, ref_id), ref_id)
    if problem == "missing":
        raise _not_found()
    if ref is None:
        raise _refuse(_R_BROKEN)
    return ref


def _change(ctx, ref_id, title, body):
    """고치기의 일 → `(Reference, None)` 또는 `(None, 아직 내지 않은 오류 객체)`(`_add` 와 같은 까닭)."""
    title, body, reason = _check(title, body)
    if reason is not None:
        return None, _refuse(reason)
    old, problem = _read_file(_file_of(ctx, ref_id), ref_id)
    if problem == "missing":
        return None, _not_found()
    if old is None:
        return None, _refuse(_R_BROKEN)
    if old.title == title and old.body == body:
        return old, None                                   # 바뀐 것이 없다 — 쓰지 않는다
    ref = Reference(ref_id, title, body, old.created_at, ctx.stamp())
    problem = _save(ctx, ref)
    return (None, problem) if problem is not None else (ref, None)


def update_reference(ctx, ref_id, *, title, body):
    """보관한 글의 제목·본문을 덮어쓴다(원자적) → 고친 `Reference`(만든 때는 그대로, 고친 때만 바뀐다). 바뀐 것이 없으면 아무것도 쓰지 않고 있던 글을 돌려준다.
    한도를 넘으면 아무것도 쓰지 않는다(옛 글이 그대로). 없는 글은 `CONTENT_NOT_FOUND`, 깨진 파일은 덮어쓰지 않고 `CONTENT_INVALID`."""
    if not is_id(ref_id):
        ref_id = title = body = None
        raise _refuse(_R_ID)
    found, problem = _change(ctx, ref_id, title, body)
    if problem is not None:
        title = body = None
        raise problem
    return found


def delete_reference(ctx, ref_id, *, confirmed):
    """보관한 글 하나를 지운다 — 번호가 정한 **파일 하나만** 정확히 지운다(확인 `confirmed=True` 가 있어야 하고, 아니면 아무것도 하지 않고 `CONFIRMATION_REQUIRED`). 없는 글은 `CONTENT_NOT_FOUND`.
    파일이 아닌 것(링크·폴더)은 지우지 않고 거절한다. 읽을 수 없는(깨진) 파일도 지울 수 있다. 되돌릴 수 없다."""
    require_confirmation(confirmed, "참고 글 지우기")
    if not is_id(ref_id):
        ref_id = None
        raise _refuse(_R_ID)
    path = _file_of(ctx, ref_id)
    info = _lstat(path)
    if info is None:
        raise _not_found()
    if not stat.S_ISREG(info.st_mode) or own_posts._link_like(info):
        raise _refuse(_R_BROKEN)
    state = "gone"
    try:
        path.unlink()
        state = "done"
    except FileNotFoundError:
        state = "gone"
    except OSError:
        state = "failed"
    if state == "gone":                                    # `except` 밖에서 낸다
        raise _not_found()
    if state == "failed":
        raise AppError("FILE_WRITE_FAILED", {"경로": _WHERE}, detail="참고 글 파일을 지우지 못했다")


__all__ = ["Entry", "FileAdded", "Listing", "Reference", "add_from_file", "add_reference", "delete_reference", "folder_path", "is_id", "list_references", "new_id", "open_reference", "update_reference"]
