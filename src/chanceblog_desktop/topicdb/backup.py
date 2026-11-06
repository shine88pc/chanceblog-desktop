"""주제 엔진 데이터의 점검한 백업·복원 — `topic_engine.db` 와 JSON 셋(`channel_profiles.json`·`seeds.json`·`calendar.json`)을 한 묶음(폴더)으로 다룬다(P3, 계획 4.5, 결정 D-63).
기존 `backup` 명령(`chanceblog.db` 백업 — 동작과 출력은 그대로)과 **따로** 두는 것이 기본값이다(열린 항목 6): 이 묶음은 `backups/topic_engine/topic-YYYYMMDD-HHMMSS/` 폴더에 들어간다.

백업(`make_backup`): 있는 파일만 담는다(없는 파일은 '없음' 으로 기록). SQLite 는 SQLite 백업 방식으로 점검한 사본(이름표·판·표 모양·구조 점검)을 만들고, JSON 은 모양을 엄격하게 읽어 본 뒤(`*_from_dict`) 그대로 복사한다.
**키·자격 증명은 어디에도 없다** — 이 코드는 키 보관소를 읽지 않고, 복사하기 전에 모든 파일 내용에 키·토큰 모양이 있는지 훑어 있으면 백업을 만들지 않는다(`TOPIC_BACKUP_BLOCKED`). 임시 폴더에서 다 만들고 해시를 다시 확인한 뒤 이름을 바꿔 둔다 —
도중에 죽거나 실패해도 반쯤 쓴 백업은 보이지 않는다. 오래된 백업은 `keep` 개만 남긴다(앱이 만든 모양의 폴더만 지우고 낯선 파일이 든 폴더는 건드리지 않는다).
복원(`restore_backup`): 바꾸기 **전에** 백업의 모든 파일을 확인한다(묶음 목록의 파일 이름·크기·해시, SQLite 의 이름표·판·모양·점검, JSON 의 모양, 키 모양). 하나라도 틀리면 아무것도 바꾸지 않는다(`TOPIC_BACKUP_INVALID`).
그다음 **바뀌는 지금 파일**을 하나씩 읽어 본다(읽기만): 멀쩡하면 `before-restore` 백업에 담을 것, 읽을 수 없거나 모양이 틀리면(깨진 SQLite·깨진 JSON) 지우지 않고 `.bad-…` 이름으로 옆에 옮겨 둘 것, 키·토큰 모양이 들어 있으면
백업에 담을 수 없으므로 **복원을 시작하지 않고 멈춘다**(`TOPIC_BACKUP_BLOCKED`, 아무것도 바꾸지 않음 — 직전 상태를 남기지 못한 채 덮어쓰지 않는다, D-65). 직전 상태 백업을 마친 뒤에야 깨진 파일을 옮기고 JSON 을 바꾼 뒤
SQLite 를 한 트랜잭션으로 바꾼다 — 어느 단계에서 실패해도 JSON 은 원래 내용으로, 옮긴 파일은 제자리로 되돌리고 SQLite 는 바뀌지 않은 채다. 백업에 없는 파일은 지금 것을 그대로 둔다.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import NamedTuple

from ..content.store import _read_only_uri
from ..echo import shown_topic_backup
from ..errors import AppError
from ..security.mask import has_key_shape
from ..topics import layout
from ..topics.channels import profiles_from_dict
from ..topics.schedule import entries_from_dict
from ..topics.seeds import seeds_from_dict
from .file import detail_of
from .store import TopicStore

MANIFEST_NAME = "MANIFEST.json"
MANIFEST_SCHEMA = 1
KEEP_BACKUPS = 10
SAFETY_FOLDER = "before-restore"
BACKUP_NAME = re.compile(r"topic-[0-9]{8}-[0-9]{6}(?:-[0-9]{1,3})?")
JSON_LOADERS = {layout.CHANNEL_PROFILES_FILE: profiles_from_dict, layout.SEEDS_FILE: seeds_from_dict, layout.CALENDAR_FILE: entries_from_dict}
BACKUP_FILES = layout.USER_DATA_FILES                           # 백업에 들어갈 수 있는 파일 이름 넷(그 밖의 이름은 거절)
MAX_JSON_BYTES = 8 * 1024 * 1024                                 # JSON 한 파일의 상한(실수로 거대한 파일을 읽지 않게)
MAX_NAMES = 99                                                   # 같은 초에 만든 백업 이름 번호(-2 … -99)


class BackupResult(NamedTuple):
    path: Path                                                   # 만든 백업 폴더
    files: tuple                                                 # 담은 파일 이름들(`BACKUP_FILES` 순서)
    missing: tuple                                               # 지금 없어서 담지 못한 파일 이름들


class RestoreResult(NamedTuple):
    source: Path                                                 # 되돌린 백업 폴더
    restored: tuple                                              # 바꾼 파일 이름들
    kept: tuple                                                  # 백업에 없어서 지금 것을 그대로 둔 파일 이름들
    safety: Path | None                                          # 바꾸기 직전 상태의 백업 폴더(바뀌는 지금 파일 중 담을 것이 하나도 없었으면 None)
    moved_aside: Path | None                                     # 깨져 있던 지금 SQLite 를 옆으로 옮긴 곳(없으면 None)
    moved_json: tuple = ()                                       # 읽을 수 없던 지금 JSON 을 옆으로 옮긴 곳들(없으면 빈 튜플)


def _blocked(reason, *, detail=""):
    return AppError("TOPIC_BACKUP_BLOCKED", {"이유": reason}, detail=detail or reason)


def _invalid(path, reason, *, detail=""):
    return AppError("TOPIC_BACKUP_INVALID", {"파일": shown_topic_backup(Path(path).name), "이유": reason}, detail=detail or reason)


def _write_bytes(path, data):
    """파일을 다 쓰고 디스크까지 내려보낸(`fsync`) 뒤에 닫는다."""
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _remove_file(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    return True


def _io_error(error, name):
    """파일을 읽거나 쓰다 난 OS 오류(권한·읽기 전용 속성·디스크 가득·다른 프로그램이 잡고 있음·경로 길이 …) → 쉬운 오류. 화면에는 파일 이름만 나가고 경로·예외 이름은 개발자용 세부에만 있다."""
    number, winerror = getattr(error, "errno", None), getattr(error, "winerror", None)
    if number == errno.ENOSPC or winerror == 112:
        code, slots = "DISK_FULL", None
    elif number == errno.ENAMETOOLONG or winerror == 206:
        code, slots = "FILE_PATH_TOO_LONG", None
    elif winerror in (32, 33):
        code, slots = "FILE_IN_USE", {"경로": name}
    else:
        code, slots = "FILE_WRITE_FAILED", {"경로": name}
    return AppError(code, slots, detail=f"{type(error).__name__}: {detail_of(error)}")


def _missing_folders(folder):
    """아직 없는 폴더들(깊은 것 먼저) — 이 백업이 새로 만들 폴더. 실패하면 빈 채로 남기지 않으려고 기억해 둔다."""
    found = []
    while not folder.exists() and folder != folder.parent:
        found.append(folder)
        folder = folder.parent
    return found


def _remove_empty(folders):
    """`_missing_folders` 가 기억한 폴더 중 아직 비어 있는 것을 치운다(깊은 것부터)."""
    for folder in folders:
        try:
            os.rmdir(folder)
        except OSError:
            break                                                # 비어 있지 않거나(다른 곳에서 쓰는 중) 이미 없으면 더 위 폴더는 건드리지 않는다


def check_json_bytes(name, data):
    """JSON 셋 한 파일의 내용이 엄격한 모양인지 읽어 본다(`seeds_from_dict` 같은 것). 틀리면 AppError(CONTENT_INVALID 등 — 어느 칸이 왜 안 되는지)이고, 읽을 수 없는 글자·JSON 이 아니면 TOPIC_FILE_INVALID."""
    if name not in JSON_LOADERS:
        raise ValueError("모르는 JSON 파일 이름이다")
    if len(data) > MAX_JSON_BYTES:
        raise AppError("TOPIC_FILE_INVALID", {"파일": name}, detail=f"파일이 너무 크다(최대 {MAX_JSON_BYTES // (1024 * 1024)}MB)")
    try:
        parsed = json.loads(data.decode("utf-8-sig"))                    # 메모장·PowerShell 5.1 이 붙이는 UTF-8 BOM 은 받는다(쓸 때는 BOM 없이 — 기존 원고 읽기와 같은 관례, D-72)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AppError("TOPIC_FILE_INVALID", {"파일": name}, detail="UTF-8 JSON 으로 읽을 수 없다") from None
    return JSON_LOADERS[name](parsed)


_KEY_WINDOW = 150_000                                            # 한 번에 훑는 글자 수 — `has_key_shape` 은 입력의 앞 20만 자만 보므로 그보다 작게 잘라 끝까지 훑는다
_KEY_OVERLAP = 4_096                                             # 창이 겹치는 글자 수 — 키·토큰 모양은 이보다 짧아 창 경계에서 놓치지 않는다


def scan_key_shape(text):
    """글 **전체**에 키·토큰 모양이 있는가. `has_key_shape` 의 20만 자 상한은 가리기용(그 뒤는 내보내지 않는다)이라 여기서는 겹친 창으로 끝까지 훑는다(8MB 도 몇 초 안, 창마다 같은 선형 정규식)."""
    if len(text) <= _KEY_WINDOW:
        return has_key_shape(text)
    step = _KEY_WINDOW - _KEY_OVERLAP
    for start in range(0, len(text), step):
        if has_key_shape(text[start:start + _KEY_WINDOW]):
            return True
        if start + _KEY_WINDOW >= len(text):
            break
    return False


def _scan_json(name, data):
    check_json_bytes(name, data)
    if scan_key_shape(data.decode("utf-8", errors="replace")):
        raise _blocked(f"{name} 안에 키·토큰처럼 보이는 글이 있어 백업하지 않았습니다 — 그 글을 지운 뒤 다시 만들어 주세요", detail=f"{name}: 키 모양")


_PUBLIC_ROWS = ('INSERT INTO "history_ledger" ',)                # 발행 이력 장부의 행 — 이미 공개된 블로그 글의 제목·키워드·주소라 키 모양 검사에서 뺀다(D-75)


def _database_key_shaped(path):
    """SQLite 파일의 행 글에 키·토큰 모양이 있는가(읽기 전용 — 파일을 바꾸지 않는다). 씨앗·후보처럼 사용자가 쓴 값은 모두 훑고, 이미 공개된 블로그 글을 읽어 둔 발행 이력 장부(`history_ledger`)는 훑지 않는다 —
    장부 행은 지울 길이 없어 거기서 막히면 백업이 영구히 막히는데, 그 값은 공개된 글에서 온 것이라 백업에 담아도 새로 드러나는 비밀이 없다(D-75)."""
    with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as connection:
        return any(scan_key_shape(line) for line in connection.iterdump() if not line.startswith(_PUBLIC_ROWS))


def _scan_database(path):
    """SQLite 사본의 모든 행 글에 키·토큰 모양이 있는지 훑는다(있으면 백업을 막는다)."""
    if _database_key_shaped(path):
        raise _blocked("주제 엔진 보관함 안에 키·토큰처럼 보이는 글이 있어 백업하지 않았습니다 — 그 글이 든 씨앗·후보는 `topics check` 로 찾을 수 있습니다", detail="topic_engine.db: 키 모양")


def _database_problem(path):
    """SQLite 파일이 이 프로그램의 주제 엔진 보관함으로 온전한가(이름표·판·모양·구조 점검·자료 점검) — 문제 문장, 온전하면 None. 파일을 바꾸지 않는다."""
    try:
        with TopicStore.open(path, migrate=False) as store:
            if store.needs_migration:
                return None                                       # 옛 판이면 구조는 맞다 — 자료 점검은 지금 판의 표를 기준으로 하므로 건너뛴다
            problems = store.check()
    except AppError as error:
        return error.detail or error.code
    return problems[0] if problems else None


def list_backups(folder):
    """백업 폴더들(이름이 앱이 만드는 모양인 것만, 새 것이 먼저)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted((entry for entry in folder.iterdir() if entry.is_dir() and BACKUP_NAME.fullmatch(entry.name)), key=lambda entry: entry.name, reverse=True)


_MAX_REF_CHARS = 260                                             # 친 백업 참조의 전체 길이 상한 — 윈도 `_COPY_PATH_LIMIT` 와 같은 기준(진짜 백업 이름은 22자 안팎이고 경로로 준 것도 이보다 짧다)
_MAX_NAME_BYTES = 255                                            # 이름 한 마디의 상한(리눅스 NAME_MAX — 윈도의 한 마디 상한도 255 글자)


def _ref_has_a_path_shape(text):
    """친 글이 파일 시스템에 물어볼 만한 모양인가 — 제어 문자(줄바꿈·NUL …)가 없고, 이름 한 마디가 255바이트·전체가 260자를 넘지 않는다. 아니면 OS 에 묻지 않고 '찾을 수 없음' 으로 본다:
    리눅스는 이름이 길면 `OSError(ENAMETOOLONG, '…: <그 글>')` 를 내는데 그 문구가 오류 세부로 올라가 친 글이 화면에 되풀이되기 때문이다(D-80). 어느 OS 에서나 같은 길을 탄다."""
    if len(text) > _MAX_REF_CHARS or any(ord(char) < 32 or ord(char) == 127 for char in text):
        return False
    return all(len(part.encode("utf-8", "surrogatepass")) <= _MAX_NAME_BYTES for part in re.split(r"[\\/]", text))       # `/` 와 `\` 둘 다 마디 구분으로 본다 — 어느 OS 에서 쳐도 같은 판정


def _refusal_kind(error):
    """OS 가 묻기를 거절한 종류(예외 이름·`errno`·OS 설명) — 파일 이름은 뺀다(친 글일 수 있다)."""
    if isinstance(error, OSError):
        return f"{type(error).__name__} errno={error.errno} {' '.join(str(error.strerror or '').split())}".strip()
    return type(error).__name__


def _is_directory(path, refusals):
    """사용자가 친 글이 낀 경로를 파일 시스템에 묻는다 — OS 가 거절하는 글(이름이 너무 김·고리·폴더가 아님·권한 …)은 '폴더가 아니다' 와 같게 본다. 그 OS 오류의 문구는 친 글을 품고 있어
    화면에 나가면 안 되므로 거절한 종류만(`_refusal_kind`) `refusals` 에 남겨 오류 세부에 붙인다 — 원인을 숨기지 않되 이름은 담지 않는다(D-80)."""
    try:
        return path.is_dir()
    except (OSError, ValueError) as error:
        refusals.append(_refusal_kind(error))
        return False


def resolve_backup(folder, ref=None, *, latest=False):
    """어느 백업으로 되돌릴지 — 가장 최근 것이거나 이름(`topic-20261106-075500`)이나 폴더로 준 것. 파일을 열지 않고 이름만 정한다. 없으면 TOPIC_BACKUP_INVALID(글 보관함용 'CONTENT_NOT_FOUND' 문구가 아니라 백업에 맞는 쉬운 말 — D-73)."""
    if latest:
        found = list_backups(folder)
        if not found:
            raise AppError("TOPIC_BACKUP_INVALID", {"파일": "(최근 백업)", "이유": "만들어 둔 주제 엔진 백업이 아직 없습니다(`topics backup` 으로 먼저 만듭니다)"}, detail="백업 폴더에 주제 엔진 백업이 없다")
        return found[0]
    if not ref:
        raise AppError("TOPIC_BACKUP_INVALID", {"파일": "(이름 없음)", "이유": "백업 이름(`topic-날짜-시각`)이나 `--latest` 가 필요합니다"}, detail="백업 이름이나 --latest 가 필요하다")
    text = str(ref)
    name, refusals = "", []
    if _ref_has_a_path_shape(text):                                # 모양이 이상한 글(너무 김·제어 문자)은 파일 시스템에 묻지 않고 곧바로 '찾을 수 없음'(친 글은 되풀이하지 않는다)
        candidate = Path(text)
        name = candidate.name
        if BACKUP_NAME.fullmatch(name) and _is_directory(candidate, refusals):          # 백업 이름 모양일 때만 묻는다
            return candidate
        if ".." not in candidate.parts and not candidate.is_absolute():
            inner = Path(folder) / candidate                       # backups 폴더 안의 이름(`topic-…` 이나 `before-restore/topic-…`)
            if BACKUP_NAME.fullmatch(name) and _is_directory(inner, refusals):
                return inner
    raise AppError("TOPIC_BACKUP_INVALID", {"파일": shown_topic_backup(name), "이유": "백업 폴더에서 찾을 수 없습니다(`topics backup` 이 만든 `topic-날짜-시각` 폴더 이름을 확인하세요)"},
                   detail="백업 폴더에서 찾을 수 없다" + (f"(OS 가 묻기를 거절했다: {'; '.join(dict.fromkeys(refusals))})" if refusals else ""))


_STORE_BLOCK_REASONS = {
    "TOPIC_STORE_CORRUPT": "주제 엔진 보관함 파일이 이 프로그램의 것이 아니거나 깨져서 백업하지 않았습니다 — `topics status` 의 안내를 따릅니다",
    "TOPIC_STORE_VERSION_UNSUPPORTED": "주제 엔진 보관함이 더 새로운 버전의 프로그램이 만든 것이라 백업하지 않았습니다 — 프로그램을 업데이트한 뒤 다시 만들어 주세요",
    "TOPIC_STORE_RECOVERY_PENDING": "주제 엔진 보관함에 앱이 갑자기 꺼지면서 남은 정리 안 된 저장이 있어 백업하지 않았습니다 — `topics init --yes` 로 정리한 뒤 다시 만들어 주세요",
}


def make_backup(data_dir, backups_dir, *, now, keep=KEEP_BACKUPS, names=None):
    """`data_dir`(주제 엔진 파일이 있는 폴더)의 있는 파일을 `backups_dir` 안 새 폴더 `topic-YYYYMMDD-HHMMSS` 에 점검해서 담는다 → `BackupResult`. 담을 파일이 하나도 없으면 CONTENT_NOT_FOUND.
    키 모양이 있거나 SQLite 가 이 프로그램의 것이 아니거나 깨졌으면 TOPIC_BACKUP_BLOCKED(아무것도 만들지 않는다 — 빈 폴더도 남기지 않는다). 다른 실패는 BACKUP_FAILED. `now` 는 시각(datetime).
    `names` 를 주면 그 파일만 담는다(되돌리기 직전 상태를 남길 때 — 바뀌는 파일만). 안 담은 파일은 '없음' 으로 적지도 않는다."""
    data_dir, backups_dir = Path(data_dir), Path(backups_dir)
    name = f"topic-{now.strftime('%Y%m%d-%H%M%S')}"
    present, missing = [], []
    for file_name in BACKUP_FILES if names is None else tuple(item for item in BACKUP_FILES if item in names):
        path = data_dir / file_name
        (present if path.is_file() and path.stat().st_size > 0 else missing).append(file_name)
    if not present:
        raise AppError("CONTENT_NOT_FOUND", {"항목": "백업할 주제 엔진 데이터"}, detail="주제 엔진 파일이 하나도 없다(init --yes 로 먼저 만든다)")
    contents = {}
    try:
        for file_name in present:
            if file_name in JSON_LOADERS:
                contents[file_name] = (data_dir / file_name).read_bytes()
                _scan_json(file_name, contents[file_name])
    except OSError as error:
        raise AppError("BACKUP_FAILED", detail=f"{type(error).__name__}: {detail_of(error)}") from None
    temp = backups_dir / (name + ".tmp")
    final = None
    created = _missing_folders(backups_dir)                       # 이 백업이 새로 만드는 폴더 — 막히거나 실패하면 빈 채로 남기지 않는다
    try:
        backups_dir.mkdir(parents=True, exist_ok=True)
        if temp.exists():
            _clear_known(temp)
        temp.mkdir(parents=True)
        recorded = {}
        for file_name in present:
            target = temp / file_name
            if file_name == layout.ENGINE_DB_FILE:
                try:
                    with TopicStore.open(data_dir / file_name, migrate=False) as store:
                        store.copy_to(target)
                except AppError as error:
                    if error.code in _STORE_BLOCK_REASONS:
                        raise _blocked(_STORE_BLOCK_REASONS[error.code], detail=error.detail or error.code) from None
                    raise
                problem = _database_problem(target)
                if problem:
                    raise _blocked("주제 엔진 보관함의 사본을 점검했더니 문제가 있어 백업하지 않았습니다", detail=problem)
                _scan_database(target)
                data = target.read_bytes()
            else:
                data = contents[file_name]
                _write_bytes(target, data)
            recorded[file_name] = {"size": len(data), "sha256": _sha256(data)}
        manifest = {"schema": MANIFEST_SCHEMA, "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "files": recorded, "missing": list(missing)}
        _write_bytes(temp / MANIFEST_NAME, (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        try:
            _verify_folder(temp)                                  # 다 만든 것을 다시 읽어 확인한 뒤에야 이름을 바꾼다
        except AppError as error:
            if error.code != "TOPIC_BACKUP_INVALID":
                raise
            raise AppError("BACKUP_FAILED", detail="방금 만든 백업을 다시 읽어 확인했더니 맞지 않았다: " + str(error.detail or "")[:150]) from None      # 만들 때의 실패는 '되돌릴 수 없는 백업' 이 아니라 '백업을 못 만듦' 이다
        final = _free_name(backups_dir, name)
        os.rename(temp, final)                                    # Windows 는 이미 있으면 실패한다(덮어쓰지 않는다)
    except (OSError, sqlite3.Error) as error:
        _clear_known(temp)
        _remove_empty(created)
        raise AppError("BACKUP_FAILED", detail=detail_of(error)) from None
    except BaseException:
        _clear_known(temp)
        _remove_empty(created)
        raise
    _prune(backups_dir, keep)
    return BackupResult(final, tuple(present), tuple(missing))


def _free_name(folder, name):
    for number in range(1, MAX_NAMES + 1):
        candidate = folder / (name if number == 1 else f"{name}-{number}")
        if not candidate.exists():
            return candidate
    raise AppError("BACKUP_FAILED", detail=f"같은 초에 만든 백업 이름이 {MAX_NAMES}개를 넘었다")


def _clear_known(folder):
    """앱이 만드는 파일 이름의 파일만 지우고 비면 폴더를 없앤다 — 낯선 파일이 있으면 그 폴더는 그대로 둔다."""
    folder = Path(folder)
    if not folder.is_dir():
        return False
    entries = list(folder.iterdir())
    if any(entry.name not in (*BACKUP_FILES, MANIFEST_NAME) or not entry.is_file() for entry in entries):
        return False
    for entry in entries:
        _remove_file(entry)
    try:
        os.rmdir(folder)
    except OSError:
        return False
    return True


def _prune(folder, keep):
    for old in list_backups(folder)[max(keep, 1):]:
        _clear_known(old)                                         # 못 지워도(낯선 파일이 있거나 쓰는 중) 백업 자체는 성공이다


def _verify_folder(folder):
    """묶음 폴더가 온전한가 — 목록 파일과 실제 파일이 같고(이름·크기·해시) 안의 SQLite·JSON 이 모양대로 읽힌다. 틀리면 AppError(TOPIC_BACKUP_INVALID) — 읽은 내용을 돌려준다(`{이름: 바이트}`).
    파일을 읽다 OS 오류가 나도(권한·목록의 파일 자리가 폴더 …) 같은 TOPIC_BACKUP_INVALID 로 쉽게 알린다."""
    try:
        return _verify_folder_files(folder)
    except OSError as error:
        raise _invalid(folder, "백업 안의 파일을 읽을 수 없습니다(파일이 폴더로 바뀌었거나 읽을 권한이 없습니다)", detail=f"{type(error).__name__}: {detail_of(error)}") from None


def _verify_folder_files(folder):
    folder = Path(folder)
    try:
        manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        raise _invalid(folder, "백업의 목록 파일(MANIFEST.json)을 읽을 수 없습니다") from None
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "created_at", "files", "missing"} or manifest["schema"] != MANIFEST_SCHEMA
            or not isinstance(manifest["files"], dict) or not isinstance(manifest["missing"], list)):
        raise _invalid(folder, "백업의 목록 파일 모양이 맞지 않습니다")
    names, found = set(manifest["files"]), {entry.name for entry in folder.iterdir()}
    if not names <= set(BACKUP_FILES) or not names or found != names | {MANIFEST_NAME}:
        raise _invalid(folder, "백업 폴더의 파일이 목록과 다릅니다(없거나 모르는 파일이 있습니다)")
    contents = {}
    for name in sorted(names):
        info = manifest["files"][name]
        if not isinstance(info, dict) or set(info) != {"size", "sha256"}:
            raise _invalid(folder, "백업의 목록 파일 모양이 맞지 않습니다")
        data = (folder / name).read_bytes()
        if len(data) != info["size"] or _sha256(data) != info["sha256"]:
            raise _invalid(folder, f"{name} 의 크기나 해시가 목록과 다릅니다(파일이 바뀌었거나 깨졌습니다)")
        contents[name] = data
    for name, data in contents.items():
        if name == layout.ENGINE_DB_FILE:
            problem = _database_problem(folder / name)
            if problem:
                raise _invalid(folder, "주제 엔진 보관함 사본이 온전하지 않습니다", detail=problem)
        else:
            try:
                check_json_bytes(name, data)
            except AppError as error:
                raise _invalid(folder, f"{name} 의 모양이 맞지 않습니다", detail=error.detail or error.code) from None
    return manifest, contents


def read_backup(folder):
    """백업 폴더를 열어 보지 않고(바꾸지 않고) 온전한지 확인한다 → (목록, {파일 이름: 바이트}). 틀리면 TOPIC_BACKUP_INVALID. 키 모양이 있어도 틀린 백업이다."""
    folder = Path(folder)
    if not folder.is_dir() or not BACKUP_NAME.fullmatch(folder.name):
        raise _invalid(folder, "주제 엔진 백업 폴더가 아닙니다")
    manifest, contents = _verify_folder(folder)
    for name, data in contents.items():
        if name == layout.ENGINE_DB_FILE:
            try:
                _scan_database(folder / name)
            except AppError:
                raise _invalid(folder, "백업 안에 키·토큰처럼 보이는 글이 있어 쓰지 않습니다") from None
            except sqlite3.Error as error:
                raise _invalid(folder, "백업 안의 보관함을 읽을 수 없습니다", detail=detail_of(error)) from None
        elif scan_key_shape(data.decode("utf-8", errors="replace")):
            raise _invalid(folder, "백업 안에 키·토큰처럼 보이는 글이 있어 쓰지 않습니다")
    return manifest, contents


_MISSING, _OK, _DAMAGED, _KEYED = "missing", "ok", "damaged", "keyed"


def _live_state(data_dir, name):
    """지금 파일 하나의 상태(읽기만 한다) — 'missing'(없음·0바이트) · 'ok'(직전 상태 백업에 담을 수 있음) · 'damaged'(읽을 수 없거나 모양이 틀림 — 지우지 않고 옆으로 옮겨 둔다) ·
    'keyed'(키·토큰 모양이 있어 백업에 담을 수 없음). 더 새로운 버전·잠김·정리 못 한 저장은 그대로 알리고 멈춘다(AppError)."""
    path = data_dir / name
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return _MISSING
        if name == layout.ENGINE_DB_FILE:
            try:
                with TopicStore.open(path, migrate=False) as store:
                    problems = [] if store.needs_migration else store.check()
            except AppError as error:
                if error.code == "TOPIC_STORE_CORRUPT":
                    return _DAMAGED
                raise                                            # 더 새로운 버전·잠김·정리 못 한 저장 같은 것은 그대로 알린다 — 깨진 것이 아닌 파일은 옮기지 않는다
            if problems:
                return _DAMAGED
            try:
                return _KEYED if _database_key_shaped(path) else _OK
            except sqlite3.Error:
                return _DAMAGED
        data = path.read_bytes()
    except OSError as error:
        raise _io_error(error, name) from None
    try:
        check_json_bytes(name, data)
    except AppError:
        return _DAMAGED
    return _KEYED if scan_key_shape(data.decode("utf-8", errors="replace")) else _OK


def restore_backup(backup, data_dir, backups_dir, *, now):
    """백업 폴더의 내용으로 `data_dir` 의 주제 엔진 파일을 바꾼다 → `RestoreResult`. 바꾸기 전에 백업 전체를 확인하고(틀리면 TOPIC_BACKUP_INVALID, 아무것도 바뀌지 않는다) 바뀌는 지금 파일을 읽어 본다:
    멀쩡한 것은 `before-restore` 백업에 남기고, 읽을 수 없는 것(깨진 SQLite·깨진 JSON)은 지우지 않고 `.bad-…` 로 옆에 옮겨 두며, 키·토큰 모양이 든 것이 있으면 직전 상태를 백업할 수 없으므로 **아무것도 바꾸지 않고**
    TOPIC_BACKUP_BLOCKED 로 멈춘다. 직전 상태 백업이 안 만들어지면 어떤 이유로든 시작하지 않는다. JSON 을 먼저 바꾸고 SQLite 를 마지막에(한 트랜잭션) 바꾸며 어느 단계에서 실패해도 JSON 은 원래대로,
    옮긴 파일은 제자리로 되돌리고 SQLite 는 바뀌지 않은 채다(복원 전에 없던 보관함을 만들다 실패하면 그 새 보관함도 치운다 — 되돌리다 또 실패한 파일은 오류의 `notes` 로 이름을 알린다). 백업에 없는 파일은 그대로 둔다. 파일을 쓰다 난 OS 오류는 쉬운 오류(FILE_WRITE_FAILED·DISK_FULL …)로 바꾼다."""
    backup, data_dir, backups_dir = Path(backup), Path(data_dir), Path(backups_dir)
    manifest, contents = read_backup(backup)
    names = [name for name in BACKUP_FILES if name in contents]                  # 이번에 바뀌는 파일
    live = {name: _live_state(data_dir, name) for name in names}
    keyed = [name for name in names if live[name] == _KEYED]
    if keyed:
        raise _blocked("되돌리기 직전의 상태를 따로 백업해 둔 뒤에 바꾸는데, 지금 " + ", ".join(keyed) + " 에 키·토큰처럼 보이는 글이 있어 그 백업을 만들 수 없습니다 — 아무것도 바꾸지 않았습니다. "
                       "그 글을 지운 뒤 다시 되돌려 주세요(후보 보관함 파일이라면 지우지 말고 이름만 바꿔 둔 뒤 되돌립니다)", detail="되돌릴 지금 파일에 키 모양: " + ", ".join(keyed))
    safe = [name for name in names if live[name] == _OK]
    damaged = [name for name in names if live[name] == _DAMAGED]
    safety = None
    if safe:
        safety = make_backup(data_dir, backups_dir / SAFETY_FOLDER, now=now, names=safe).path          # 못 만들면 여기서 멈춘다 — 아무것도 바꾸지 않은 채
    originals, staged, restored, moves = {}, [], [], []
    working = ""
    new_db = None                                                  # 복원이 새로 만들게 될 보관함의 원래 모습 — 없었으면 'absent', 0바이트였으면 'blank'(실패하면 그 모습으로 되돌린다)
    if live.get(layout.ENGINE_DB_FILE) == _MISSING:
        new_db = "blank" if (data_dir / layout.ENGINE_DB_FILE).is_file() else "absent"
    try:
        for name in damaged:
            working = name
            moved_to = _move_aside(data_dir, name, now)
            if moved_to is not None:
                moves.append((name, moved_to))                    # 읽을 수 없는 지금 파일은 지우지 않고 옆으로 옮겨 둔다
        data_dir.mkdir(parents=True, exist_ok=True)
        for name in BACKUP_FILES:
            if name == layout.ENGINE_DB_FILE or name not in contents:
                continue
            working = name
            target = data_dir / name
            originals[name] = target.read_bytes() if target.is_file() else None
            stage = data_dir / (name + ".restoring")
            _write_bytes(stage, contents[name])
            staged.append(stage)
        for name in list(originals):
            working = name
            os.replace(data_dir / (name + ".restoring"), data_dir / name)
            staged.remove(data_dir / (name + ".restoring"))
            restored.append(name)
        if layout.ENGINE_DB_FILE in contents:
            working = layout.ENGINE_DB_FILE
            with TopicStore.open(data_dir / layout.ENGINE_DB_FILE) as live_store:
                live_store.restore_from(backup / layout.ENGINE_DB_FILE)
            restored.append(layout.ENGINE_DB_FILE)
    except BaseException as error:
        left = _roll_back(data_dir, staged, restored, originals, moves, new_db if working == layout.ENGINE_DB_FILE else None)
        failure = _io_error(error, working or "주제 엔진 파일") if isinstance(error, OSError) else error
        if left and isinstance(failure, AppError):
            failure.notes = (*getattr(failure, "notes", ()), *left)        # 되돌리지 못한 것은 이름을 쉬운 말로 알린다 — 원래 오류 코드는 그대로(`service/cli.py::_error_text` 가 '참고:' 줄로 보인다, D-76)
        if failure is error:
            raise
        raise failure from None
    kept = tuple(name for name in BACKUP_FILES if name not in contents)
    moved_db = next((aside for name, aside in moves if name == layout.ENGINE_DB_FILE), None)
    moved_json = tuple(aside for name, aside in moves if name != layout.ENGINE_DB_FILE)
    return RestoreResult(backup, tuple(restored), kept, safety, moved_db, moved_json)


def _move_aside(data_dir, name, now):
    """읽을 수 없는 지금 파일을 지우지 않고 `이름.bad-날짜-시각` 으로 옆에 옮겨 둔다 → 옮긴 곳(파일이 없으면 None). SQLite 는 정리 못 한 저장 파일(`-journal`)도 함께 치운다(새 파일에 잘못 적용되지 않게)."""
    live = data_dir / name
    if not live.is_file():
        return None
    target = data_dir / f"{name}.bad-{now.strftime('%Y%m%d-%H%M%S')}"
    for number in range(1, MAX_NAMES + 1):
        candidate = target if number == 1 else data_dir / f"{target.name}-{number}"
        if not candidate.exists():
            os.replace(live, candidate)
            if name == layout.ENGINE_DB_FILE:
                _remove_file(str(live) + "-journal")
            return candidate
    raise AppError("BACKUP_FAILED", detail="옮겨 둘 이름이 모두 쓰이고 있다")


def _remove_quietly(path):
    """파일을 치우되 실패해도 되돌리기를 멈추지 않는다(임시 이름의 파일일 뿐이다) → 치웠는가."""
    try:
        return _remove_file(path)
    except OSError:
        return False


def _undo_moves(data_dir, moves):
    """복원이 도중에 실패했을 때 옆으로 옮겨 둔 파일을 제자리로 되돌린다 → 제자리로 돌리지 못한 파일마다 쉬운 말 한 줄(옮겨 둔 이름이 들어 있다 — 그 파일은 그 이름으로 그대로 남아 있다).
    한 파일이 실패해도 나머지는 계속 되돌린다."""
    left = []
    for name, aside in reversed(moves):
        try:
            os.replace(aside, data_dir / name)
        except OSError:
            left.append(f"{name} 은(는) 제자리로 돌리지 못했습니다 — 그 내용은 옆에 `{aside.name}` 으로 그대로 남아 있습니다")
    return left


def _roll_back(data_dir, staged, restored, originals, moves, new_db):
    """복원이 도중에 실패했을 때 지금까지 바꾼 것을 되돌린다 → 되돌리지 못한 것을 말하는 쉬운 말 줄들(모두 되돌렸으면 빈 튜플). 단계마다 따로 시도해 한 단계가 또 실패해도(디스크 가득 …) 다음 단계를 막지 않고
    옮겨 둔 파일을 제자리로 돌리는 `_undo_moves` 는 늘 부른다(D-76). 되돌리지 못해도 원본은 직전 상태 백업이나 옆으로 옮겨 둔 `.bad-…` 에 그대로 있다."""
    left = []
    for stage in staged:
        _remove_quietly(stage)                                   # 임시 이름(`.restoring`)의 파일일 뿐이다 — 못 치워도 실제 파일에는 영향이 없고 다음 복원이 덮어쓴다
    for name in [item for item in restored if item in originals]:      # 이미 바꾼 JSON 만 원래 내용으로 되돌린다(원래 없던 파일은 지운다) — 아직 안 바꾼 파일은 건드리지 않는다
        original, target = originals[name], data_dir / name
        temp = data_dir / (name + ".restoring")
        try:
            if original is None:
                _remove_file(target)
            else:
                _write_bytes(temp, original)
                os.replace(temp, target)
        except OSError:
            _remove_quietly(temp)
            left.append(f"{name} 은(는) 원래 내용으로 돌리지 못했습니다 — 원래 내용은 직전 상태 백업(`{SAFETY_FOLDER}`)에 있습니다")
    if new_db is not None:                                       # 복원 전에 없던(0바이트였던) 보관함 — 복원이 만든 새 보관함은 치워 복원 전의 모습으로 되돌린다
        database = data_dir / layout.ENGINE_DB_FILE
        try:
            _remove_file(database)
            _remove_file(str(database) + "-journal")
            if new_db == "blank":
                _write_bytes(database, b"")
        except OSError:
            left.append(f"{layout.ENGINE_DB_FILE} 은(는) 복원 전의 모습으로 돌리지 못했습니다 — 복원이 만든 새 보관함이 남아 있을 수 있습니다")
    left.extend(_undo_moves(data_dir, moves))
    return tuple(left)


__all__ = ["BACKUP_FILES", "BACKUP_NAME", "BackupResult", "JSON_LOADERS", "KEEP_BACKUPS", "MANIFEST_NAME", "RestoreResult", "SAFETY_FOLDER", "check_json_bytes", "list_backups", "make_backup", "read_backup",
           "resolve_backup", "restore_backup", "scan_key_shape"]
