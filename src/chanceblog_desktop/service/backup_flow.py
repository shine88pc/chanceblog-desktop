"""전체 백업·복원 — 글 보관함·주제 엔진·설정 파일을 폴더 하나(`backups/full-날짜-시각/`)에 점검한 채로 담고, 목록(`MANIFEST.json`)의 크기·해시로 확인한 뒤 되돌린다(BACKUPUI, 결정 D-380–D-399).

담는 것: 글 보관함(`chanceblog.db` — 글·판 기록·저장한 초안·주제 후보) · 주제 엔진(`topic_engine.db`·`channel_profiles.json`·`seeds.json`·`calendar.json`) · 설정(`settings.json` — 옛 네이버 프로필·연결한 폴더).
담지 않는 것: 키·토큰·쿠키·세션(앱은 이것을 파일에 두지 않는다 — 이 코드는 키 보관소를 읽지도 않는다)·`connections.json`·`quota_state.json`·`publish/`·`locks/`·로그·임시·복구용 사본(이유는 `security/backup_note.py`, 목록에도 그대로 적힌다).

백업(`create_full_backup`): 지금 데이터는 한 바이트도 바꾸지 않는다(읽기 전용으로 열어 SQLite 백업 방식으로 **메모리에** 복사). **사본은 디스크에 쓰기 전에 메모리에서 훑고**(JSON·설정은 읽은 바이트에서) 키·토큰 모양(여섯 가지 — `security/scan.py`)이 하나라도 있으면
어떤 사본도 쓰지 않고(폴더를 남기지 않는다 — 앱이 죽어도 키 모양이 든 파일이 디스크에 있었던 적이 없다, D-461) 어느 칸·몇 번째 줄·어떤 유형인지만 알린다 — 글을 자동으로 지우거나 바꾸지 않고, '무시하고 백업' 도 없다. 이상 없으면 목록을 쓰고 다시 읽어 확인한 뒤 폴더 이름을 바꿔 둔다(반쯤 만든 백업은 보이지 않는다).
앱이 갑자기 꺼져 남은 임시 폴더와 낡은 잠금은 다음 백업·복원 때(그리고 목록을 보여 줄 때 치울 흔적이 보이면) 치운다 — 살아 있는 다른 백업·복원의 것은 건드리지 않는다.
결과는 **완료**(지금 있는 것을 모두 담았다) · **부분**(일부는 담지 못했다 — 이유가 파일마다 있다) · **실패**(만들지 않았다 — 오류) 한 가지다.

복원(`restore_full_backup`): ① 확인 표시가 있어야 하고 ② 바꾸기 전에 백업을 읽기만 해서 모두 확인한다(목록 모양·파일 이름·크기·해시·보관함 이름표·판·점검·JSON 모양·키 모양 — 틀리면 아무것도 바꾸지 않는다, 더 새로운 앱의 백업은 거절)
③ 이 PC 의 지금 데이터를 `before-restore/` 에 같은 모양의 안전 사본으로 먼저 남기고(남길 수 없으면 시작하지 않는다 — 안전 사본도 같은 방법으로 되돌릴 수 있다) ④ 설정·JSON 은 임시 이름으로 쓴 뒤 제자리로, 보관함은 SQLite 백업 방식으로 한 번에 바꾸며
⑤ 어느 단계에서 실패해도 지금까지 바꾼 것을 안전 사본으로 원래대로 돌린다(되돌리지 못한 것은 이름을 알린다). 깨져 있던 지금 파일은 지우지 않고 옆(`.bad-날짜-시각`)으로 옮긴다. 키·`connections.json` 은 건드리지 않는다.
백업과 복원은 같은 잠금(`locks/full-backup.lock`)을 써서 한 번에 하나만 돈다.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..content.store import Store, _read_only_uri
from ..errors import AppError
from ..security import scan
from ..security.backup_note import CREDENTIAL_NOTE, EXCLUDED, RESTORE_NOTE
from ..topicdb.backup import MAX_JSON_BYTES, check_json_bytes
from ..topicdb.store import open_for_write, open_read_only
from ..topics import layout
from . import topic_files as tf
from .context import Settings, _write_durably
from .lock import LOCK_SUFFIX, PublishLock
from .projects import require_confirmation

MANIFEST_NAME = "MANIFEST.json"
MANIFEST_SCHEMA = 1
KIND = "full-backup"
FULL_NAME = re.compile(r"full-[0-9]{8}-[0-9]{6}(?:-[0-9]{1,2})?")        # 앱이 만드는 백업 폴더 이름 — 같은 초에 또 만들면 `-2`…`-99`
SAFETY_NAME = re.compile(r"before-[0-9]{8}-[0-9]{6}(?:-[0-9]{1,2})?")     # 복원 직전 안전 사본 폴더 이름 — 백업 이름과 앞부분이 달라 같은 초에 만들어도 이름이 겹치지 않는다(이름만으로 어느 쪽인지 안다)
STAMP_IN_NAME = re.compile(r"[0-9]{8}-[0-9]{6}")
KEEP_BACKUPS = 10                                                        # 남기는 백업 수(백업·안전 사본 각각 가장 새 것부터)
SAFETY_FOLDER = "before-restore"                                         # 복원 직전 안전 사본을 두는 폴더(`backups/` 아래)
RESTORE_MARKER = "restore-in-progress.json"                              # 복원이 도는 동안 `backups/` 에 있는 표지 — 복원이 끝나거나 원래대로 돌리면 지워진다. 남아 있으면 복원이 중간에 멈춘 것이다(D-463)
MARKER_KEYS = frozenset({"schema", "started", "backup", "safety", "files"})
LOCK_NAME = "full-backup"                                                # 백업·복원이 함께 쓰는 잠금 파일 이름(`locks/full-backup.lock`)
MAX_NAMES = 99
MAX_SHOWN_PLACES = 15                                                    # 키·토큰 모양을 알릴 때 보이는 위치(칸) 수의 상한 — 넘으면 '그 밖에 N곳'
MAX_WHERE_CHARS = scan.MAX_WHERE_CHARS
BUSY_SECONDS = 5.0
RETRY_TRIES = 5                                                          # 다른 프로그램(바이러스 검사·검색 색인 …)이 잠깐 붙잡은 폴더·파일의 이름 바꾸기를 해 보는 횟수 — 한 곳에서만 정한다(D-464)
RETRY_WAIT = 0.2                                                         # 다시 하기 전에 쉬는 시간(초)
COPY_SECONDS = 30.0                                                       # 지금 보관함을 복사하는 동안 계속 잠겨 있어도 기다리는 가장 긴 시간
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_NOTE_CHARS = 2000                                                     # 목록의 자유 글 칸(`credential_excluded_note`·담지 않은 것의 이유) 하나의 가장 긴 길이
STATUS_COMPLETE, STATUS_PARTIAL, STATUS_BROKEN = "complete", "partial", "broken"
LINE_SAVED, LINE_MISSING, LINE_SKIPPED = "saved", "missing", "skipped"        # 백업 파일 줄의 상태: 담았다 · 아직 없다 · 담지 못했다
LINE_RESTORED, LINE_KEPT, LINE_FAILED = "restored", "kept", "failed"          # 복원 파일 줄의 상태: 바꿨다 · 백업에 없어 그대로 뒀다 · 못 바꿨다

STORE, ENGINE, JSON_FILE, SETTINGS = "store", "engine", "json", "settings"
SIDE_STAMP = "%Y%m%d-%H%M%S"
INVALID_REASONS = {
    "missing": "백업 폴더에서 찾을 수 없어요",
    "manifest": "백업의 목록 파일(MANIFEST.json)을 읽을 수 없거나 모양이 달라요",
    "files": "백업 폴더의 파일이 목록과 달라요(빠졌거나 모르는 파일이 있어요)",
    "hash": "파일의 크기나 해시가 목록과 달라요(바뀌었거나 깨졌어요)",
    "content": "안의 보관함이나 설정 파일이 온전하지 않아요",
}
DAMAGED_CODE = {STORE: "STORE_CORRUPT", ENGINE: "TOPIC_STORE_CORRUPT", JSON_FILE: "TOPIC_FILE_INVALID", SETTINGS: "SETTINGS_INVALID"}      # 읽을 수 없는 지금 파일을 '깨짐' 으로 알릴 때의 코드
STORE_NEWER = frozenset({"STORE_VERSION_UNSUPPORTED", "TOPIC_STORE_VERSION_UNSUPPORTED"})
STORE_BUSY = frozenset({"STORE_LOCKED", "TOPIC_STORE_LOCKED"})
STORE_DAMAGED = frozenset({"STORE_CORRUPT", "TOPIC_STORE_CORRUPT"})
_SAFE_KEY = re.compile(r"[A-Za-z0-9_]{1,40}")
_ROW_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_VERSION = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:-([0-9A-Za-z][0-9A-Za-z.-]{0,30}))?(?:\+[0-9A-Za-z.-]{1,30})?")
_SHA = re.compile(r"[0-9a-f]{64}")
_STAMP_TEXT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Component:
    name: str                       # 백업 폴더 안의 파일 이름이자 이 PC 의 파일 이름
    label: str                      # 쉬운 이름
    kind: str                       # STORE · ENGINE · JSON_FILE · SETTINGS


COMPONENTS = (
    Component("chanceblog.db", "글 보관함", STORE),
    Component(layout.ENGINE_DB_FILE, "주제 보관함", ENGINE),
    Component(layout.CHANNEL_PROFILES_FILE, "채널 프로필", JSON_FILE),
    Component(layout.SEEDS_FILE, "Seed", JSON_FILE),
    Component(layout.CALENDAR_FILE, "캘린더", JSON_FILE),
    Component("settings.json", "설정(옛 네이버 프로필·연결한 폴더)", SETTINGS),
)
BY_NAME = {item.name: item for item in COMPONENTS}
KNOWN_FILES = frozenset(BY_NAME) | {MANIFEST_NAME}
SIDE_FILES = frozenset(name + suffix for name, item in BY_NAME.items() if item.kind in (STORE, ENGINE) for suffix in ("-journal", "-wal", "-shm"))        # SQLite 가 파일을 쓰는 동안 곁에 두는 짝 파일 — 쓰다 멈춘 임시 폴더에만 남는다
TEMP_FILES = KNOWN_FILES | SIDE_FILES                                      # 임시 폴더 안에 있어도 되는(앱이 만드는) 파일 이름
STALE_TEMP = re.compile(r"(?:full|before)-[0-9]{8}-[0-9]{6}(?:-[0-9]{1,2})?\.tmp")      # 만들다 멈춘 임시 폴더의 이름(백업 `full-….tmp` · 안전 사본 `before-….tmp`)
AREA = {"chanceblog.db": "글 보관함", layout.ENGINE_DB_FILE: "주제 보관함", layout.CHANNEL_PROFILES_FILE: "채널 프로필", layout.SEEDS_FILE: "Seed", layout.CALENDAR_FILE: "캘린더", "settings.json": "설정"}
ROW_LABEL = {"projects": "글", "revisions": "글", "drafts": "글", "candidates": "후보"}                # 표의 첫 칸이 그 행의 번호인 표
FIELD_LABEL = {("projects", "title"): "원고 제목", ("drafts", "text"): "저장한 초안", ("projects", "data"): "원고", ("revisions", "data"): "원고 판 기록", ("candidates", "data"): "후보 자료"}
KEY_LABEL = {"title": "제목", "source_content": "본문", "references": "출처", "assets": "이미지", "rendered": "변환한 글", "topic": "주제", "keyword": "키워드", "sub_keywords": "보조 키워드", "reason": "추천 이유",
             "display_name": "표시 이름", "blog_url": "블로그 주소", "repo_path": "연결한 폴더", "naver_profiles": "네이버 프로필", "intro": "소개글", "alias": "별칭"}
SKIPPED_TABLES = {layout.ENGINE_DB_FILE: frozenset({"history_ledger"})}        # 이미 공개된 블로그 글을 읽어 둔 발행 이력 장부는 훑지 않는다(D-75 와 같은 이유 — 지울 길이 없어 거기서 막히면 백업이 영구히 막힌다)


class FlowError(AppError):
    """백업·복원의 실패 — 오류 코드와 쉬운 문구는 `AppError` 그대로이고, 화면이 쓸 구조화된 사실을 더한다: `reason`(짧은 이름) · `findings`(키·토큰 모양의 위치와 유형 — 글 내용 없음) · `summary`(그것을 풀어 쓴 쉬운 글) ·
    `skipped`(담지 못한 파일 → 이유 코드) · `notes`(되돌리지 못한 것처럼 덧붙일 말들)."""

    def __init__(self, code, slots=None, *, detail="", reason="", findings=(), summary="", more=0, skipped=None, notes=()):
        super().__init__(code, slots, detail=detail)
        self.reason = reason
        self.findings = tuple(findings)
        self.summary = summary
        self.more = more
        self.skipped = dict(skipped or {})
        self.notes = tuple(notes)


class _Skip(Exception):
    """그 파일 하나를 담지 못한다(나머지는 계속) — `code` 는 이유를 알리는 오류 코드다."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FileLine:
    """백업 안의(또는 복원이 바꾼) 파일 하나의 상태 — 화면이 한 줄로 그린다."""
    name: str
    label: str
    state: str                      # LINE_*
    size: int = 0
    items: tuple = ()               # ((칸 이름, 개수), …) — 표 이름·`count` 같은 고정 이름이고 글 내용이 아니다
    reason: str = ""                # 못 담았거나 못 바꾼 이유의 오류 코드


@dataclass(frozen=True)
class BackupRow:
    name: str                       # 폴더 이름 `full-날짜-시각`
    kind: str                       # backup · safety(복원 직전 안전 사본)
    created_at: str                 # 만든 때(UTC `YYYY-MM-DDTHH:MM:SSZ`) — 목록을 읽을 수 없으면 폴더 이름의 시각
    status: str                     # STATUS_*
    size: int                       # 담긴 파일 크기의 합(바이트)
    files: tuple                    # FileLine
    credential_excluded: bool
    app_version: str = ""
    problem: str = ""               # STATUS_BROKEN 일 때 `INVALID_REASONS` 의 이름


@dataclass(frozen=True)
class InterruptedRestore:
    """중간에 멈춘 복원의 흔적(D-463) — 화면이 쉬운 안내와 '안전 사본으로 되돌리기' 를 보여 준다. 이름과 시각뿐이고 글 내용·이 PC 의 경로는 없다."""
    started_at: str                 # 복원을 시작한 때(UTC `YYYY-MM-DDTHH:MM:SSZ`) — 흔적을 읽을 수 없으면 빈 글
    backup: str                     # 되돌리던 백업 폴더 이름(모양이 다르거나 알 수 없으면 빈 글)
    safety: str                     # 복원 직전에 남긴 안전 사본 폴더 이름(남길 것이 없었거나 알 수 없으면 빈 글)
    can_revert: bool                # 그 안전 사본이 지금 있어 되돌릴 수 있는가


@dataclass(frozen=True)
class BackupList:
    rows: tuple                     # 새 것이 먼저
    location: str                   # 백업 폴더 경로(글자로만 보인다)
    keep: int
    interrupted: object = None      # `InterruptedRestore` — 복원이 중간에 멈춘 흔적이 있을 때만(없으면 None)


@dataclass(frozen=True)
class BackupOutcome:
    row: BackupRow
    notes: tuple = ()


@dataclass(frozen=True)
class RestoreOutcome:
    status: str                     # STATUS_COMPLETE · STATUS_PARTIAL
    source: str                     # 되돌린 백업 폴더 이름
    safety: str                     # 안전 사본 폴더 이름('' 이면 남길 것이 없었다)
    files: tuple                    # FileLine
    notes: tuple = ()


# ---- 작은 도구 -----------------------------------------------------------------------------------------------------------------------
def read_app_version():
    """이 프로그램의 버전(`0.0.0` 꼴) — 읽지 못하면 빈 글. 시험은 이 함수를 바꿔 끼운다."""
    try:
        return (Path(__file__).resolve().parents[3] / "VERSION").read_text(encoding="utf-8-sig").strip()
    except (OSError, ValueError):
        return ""


def _version_key(text):
    found = _VERSION.fullmatch(text) if isinstance(text, str) else None
    if found is None:
        return None
    return (int(found.group(1)), int(found.group(2)), int(found.group(3)), 0 if found.group(4) else 1, found.group(4) or "")


def _no_step(fraction, text=""):
    return None


def _utc_text(moment):
    return moment.astimezone(timezone.utc).strftime(_STAMP_TEXT)


def _name_stamp(name):
    """폴더 이름 `full-20261111-053010` 의 시각(UTC 글) — 읽지 못하면 빈 글."""
    try:
        return datetime.strptime(_stamp_of(name), SIDE_STAMP).strftime(_STAMP_TEXT)
    except ValueError:
        return ""


def _stamp_of(name):
    """폴더 이름 속 시각 글(`20261111-053010`) — 없으면 빈 글. 목록을 시각 순으로 줄 세우는 열쇠다."""
    found = STAMP_IN_NAME.search(name)
    return found.group(0) if found else ""


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()           # 보관함도 수십 MB 안쪽이라 통째로 읽는다(서비스는 파일을 직접 열지 않는다 — 안전 시험)


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _shown_name(text):
    """오류 문구에 되풀이해도 되는 백업 이름 — 앱이 만드는 이름 모양일 때만 그대로, 아니면 고정 말."""
    return text if isinstance(text, str) and (FULL_NAME.fullmatch(text) or SAFETY_NAME.fullmatch(text)) else "(입력한 이름)"


def _io_failure(error, what):
    """파일·SQLite 를 쓰다 난 OS 오류 → 쉬운 오류. 화면에는 `what`(이름)만 나가고 경로는 세부에만 있다."""
    number, winerror = getattr(error, "errno", None), getattr(error, "winerror", None)
    text = str(error).lower()
    if number == errno.ENOSPC or winerror == 112 or "disk is full" in text:
        return AppError("DISK_FULL", detail=f"{type(error).__name__}: 저장 공간이 부족하다")
    if number == errno.ENAMETOOLONG or winerror == 206:
        return AppError("FILE_PATH_TOO_LONG", detail=f"{type(error).__name__}: 경로가 너무 길다")
    if winerror in (32, 33):
        return AppError("FILE_IN_USE", {"경로": what}, detail=f"{type(error).__name__}: 다른 프로그램이 쓰고 있다")
    return AppError("FILE_WRITE_FAILED", {"경로": what}, detail=f"{type(error).__name__}: {' '.join(str(error.args[-1] if error.args else error).split())[:150]}")


# 파일을 만들고 지우고 옮기는 곳은 아래 몇 함수뿐이다 — `tests/test_service_safety.py` 가 (파일, 함수) 단위로 허용한다.
def _make_folder(path):
    path.mkdir(parents=True, exist_ok=True)


def _remove_file(path):
    """파일 하나를 지운다 — 이미 없으면 False."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    return True


def _remove_quietly(path):
    """파일을 치우되 실패해도 멈추지 않는다 → 치웠는가(임시 이름의 파일일 뿐이다)."""
    try:
        return _remove_file(path)
    except OSError:
        return False


def _remove_known_folder(folder, allowed=KNOWN_FILES):
    """앱이 만드는 이름(`allowed`)의 파일만 지우고 비면 폴더를 없앤다 → 없앴는가. 낯선 파일(사용자가 넣은 것)이 있으면 그 폴더는 그대로 둔다."""
    folder = Path(folder)
    try:
        if not folder.is_dir():
            return True
        entries = list(folder.iterdir())
        if any(entry.name not in allowed or entry.is_symlink() or not entry.is_file() for entry in entries):
            return False
        for entry in entries:
            os.unlink(entry)
        os.rmdir(folder)
    except OSError:
        return False
    return True


def _remove_empty(folders):
    """이번 백업이 새로 만든 폴더 중 아직 비어 있는 것을 치운다(깊은 것부터)."""
    for folder in folders:
        try:
            os.rmdir(folder)
        except OSError:
            break


_sleep = time.sleep                                                      # 시험이 기다림 없이 돌도록 바꿔 끼우는 자리


def _held_for_a_moment(error):
    """이름 바꾸기가 막힌 까닭이 '다른 프로그램이 잠깐 쓰는 중' 일 수 있는가 — 권한 거부·공유 위반·잠금 위반·사용 중만(저장 공간 부족·이미 있음·경로 오류·없음은 다시 해도 같다)."""
    return isinstance(error, PermissionError) or getattr(error, "winerror", None) in (5, 32, 33) or getattr(error, "errno", None) in (errno.EACCES, errno.EBUSY)


def _retrying(action):
    """`action()` 을 부른다 — 다른 프로그램이 잠깐 붙잡아 막히면 `RETRY_WAIT` 초 쉬고 모두 `RETRY_TRIES` 번까지 다시 한다. 그래도 안 되거나 다시 해도 소용없는 오류면 마지막 오류를 그대로 올린다(D-464)."""
    for attempt in range(1, RETRY_TRIES + 1):
        try:
            return action()
        except OSError as error:
            if attempt == RETRY_TRIES or not _held_for_a_moment(error):
                raise
            _sleep(RETRY_WAIT)


def _finish_folder(temp, final):
    """다 만든 임시 폴더의 이름을 바꿔 자리에 둔다(Windows 는 이미 있으면 실패한다 — 덮어쓰지 않는다). 다른 프로그램이 잠깐 붙잡고 있으면 짧게 다시 해 본다."""
    _retrying(lambda: os.rename(temp, final))


def _swap_in(stage, target):
    """임시 이름으로 다 쓴 파일을 제자리로 바꾼다(같은 폴더 안의 이름 바꾸기 — 한 번에 바뀐다). 다른 프로그램이 잠깐 붙잡고 있으면 짧게 다시 해 본다."""
    _retrying(lambda: os.replace(stage, target))


def _move_aside(path, moment):
    """읽을 수 없는 지금 파일을 지우지 않고 `이름.bad-날짜-시각` 으로 옆에 옮겨 둔다 → 옮긴 곳(파일이 없으면 None). 보관함은 정리 못 한 저장 파일(`-journal`)도 함께 치운다(새 파일에 잘못 적용되지 않게)."""
    if not path.is_file():
        return None
    stamp = moment.strftime(SIDE_STAMP)
    for number in range(1, MAX_NAMES + 1):
        candidate = path.with_name(f"{path.name}.bad-{stamp}" if number == 1 else f"{path.name}.bad-{stamp}-{number}")
        if not candidate.exists():
            os.replace(path, candidate)
            if path.suffix == ".db":
                _remove_file(str(path) + "-journal")
            return candidate
    raise AppError("BACKUP_FAILED", detail="옮겨 둘 이름이 모두 쓰이고 있다")


def _put_back(aside, path):
    """옆으로 옮겨 둔 파일을 제자리로 되돌린다."""
    os.replace(aside, path)


def _missing_folders(folder):
    found = []
    while not folder.exists() and folder != folder.parent:
        found.append(folder)
        folder = folder.parent
    return found


class _FlowLock(PublishLock):
    """백업·복원이 함께 쓰는 잠금 — 한 번에 하나만 돈다(두 번째는 아무것도 바꾸지 않고 `BACKUP_IN_PROGRESS`). 방식·낡은 잠금 넘겨받기는 글 잠금(`PublishLock`)과 같다."""
    busy_code = "BACKUP_IN_PROGRESS"
    what = "백업이나 복원을 하다"


@contextmanager
def _flow_lock(ctx):
    lock = _FlowLock(ctx.workspace.locks_dir, LOCK_NAME, now=ctx.now, host="")        # PC 이름을 읽지 않는다 — 윈도 첫 호출이 하위 프로세스를 불러 느리고 '하위 프로세스 0' 약속에도 어긋난다
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


def _temp_folders(ctx):
    """만들다 멈춘 임시 폴더들(`full-….tmp`·`before-….tmp`) — 백업 폴더와 안전 사본 폴더 안에서 앱이 만든 이름의 진짜 폴더만(링크는 따라가지 않는다). 읽기만 한다."""
    found = []
    for root in (ctx.workspace.backups_dir, _safety_root(ctx)):
        try:
            found += [entry for entry in Path(root).iterdir() if STALE_TEMP.fullmatch(entry.name) and entry.is_dir() and not entry.is_symlink()]
        except OSError:
            continue
    return found


def _sweep_locked(ctx):
    """잠금을 쥔 채로 — 앱이 갑자기 꺼져 남은 임시 폴더를 모두 치운다 → 치운 개수(D-461). 잠금을 쥔 동안에는 만드는 중인 다른 백업이 없으므로 모두 낡은 것이다. 낯선 파일(사용자가 넣은 것)이 든 폴더는 그대로 둔다.
    임시 폴더에는 훑어서 이상 없는 내용만 쓰이므로(키·토큰 모양은 디스크에 닿기 전에 걸러진다) 치우기는 정리일 뿐 비밀을 지우는 일이 아니다."""
    return sum(1 for folder in _temp_folders(ctx) if _remove_known_folder(folder, TEMP_FILES))


def _sweep_if_stale(ctx):
    """목록을 보여 줄 때 — 치울 흔적(임시 폴더·잠금 파일)이 눈에 보일 때만 잠금을 잡아 본다. 다른 백업·복원이 살아서 돌고 있으면(잠금을 못 잡으면) 아무것도 건드리지 않는다.
    낡은 잠금은 잡는 순간 넘겨받아 지워지고, 흔적이 없는 평소의 목록은 한 글자도 쓰지 않는다."""
    try:
        if not (_temp_folders(ctx) or (ctx.workspace.locks_dir / (LOCK_NAME + LOCK_SUFFIX)).exists()):
            return
        with _flow_lock(ctx):
            _sweep_locked(ctx)
    except (AppError, OSError):
        return


def _component_path(ctx, component):
    paths = tf.topic_paths(ctx.workspace)
    return {"chanceblog.db": ctx.workspace.store_path, layout.ENGINE_DB_FILE: paths.database, layout.CHANNEL_PROFILES_FILE: paths.profiles, layout.SEEDS_FILE: paths.seeds,
            layout.CALENDAR_FILE: paths.calendar, "settings.json": ctx.workspace.settings_path}[component.name]


def _safety_root(ctx):
    return ctx.workspace.backups_dir / SAFETY_FOLDER


# ---- 복원이 중간에 멈춘 흔적(D-463) ---------------------------------------------------------------------------------------------------------
def _marker_path(ctx):
    return ctx.workspace.backups_dir / RESTORE_MARKER


def _write_marker(ctx, folder, safety_name, names, moment):
    """복원이 지금 데이터를 바꾸기 **직전에** 표지를 쓴다 — 시작한 때·되돌리던 백업 이름·안전 사본 이름·바꿀 파일 이름뿐(글 내용·경로 없음)."""
    data = {"schema": 1, "started": _utc_text(moment), "backup": folder.name, "safety": safety_name, "files": [component.name for component in names]}
    _make_folder(_marker_path(ctx).parent)                                                              # 데이터 폴더를 통째로 잃은 PC 의 복원은 `backups/` 도 아직 없다
    _write_durably(_marker_path(ctx), (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _clear_marker(ctx):
    """복원이 끝났거나 원래대로 돌렸을 때 표지를 지운다 — 못 지워도 복원 결과는 그대로다(다음에 표지가 보이면 안내가 뜰 뿐이다)."""
    _remove_quietly(_marker_path(ctx))


def _read_marker(ctx):
    """표지 → dict(모양이 맞을 때) · {}(있는데 읽을 수 없거나 모양이 다르다) · None(없다)."""
    try:
        raw = _marker_path(ctx).read_bytes()[:4096]
    except FileNotFoundError:
        return None
    except OSError:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
        datetime.strptime(data["started"], _STAMP_TEXT)
    except (UnicodeDecodeError, ValueError, RecursionError, KeyError, TypeError):
        return {}
    if (not isinstance(data, dict) or set(data) != MARKER_KEYS or isinstance(data["schema"], bool) or data["schema"] != 1 or not isinstance(data["backup"], str) or not isinstance(data["safety"], str)
            or not isinstance(data["files"], list) or not all(isinstance(item, str) and item in BY_NAME for item in data["files"])):
        return {}
    return data


def interrupted_restore(ctx):
    """복원이 중간에 멈춘 흔적이 있으면 `InterruptedRestore`, 없으면 None — 읽기만 한다. 표지를 읽을 수 없어도 '멈췄다' 는 사실은 알린다(되돌릴 수는 없다)."""
    data = _read_marker(ctx)
    if data is None:
        return None
    if not data:
        return InterruptedRestore("", "", "", False)
    backup = data["backup"] if (FULL_NAME.fullmatch(data["backup"]) or SAFETY_NAME.fullmatch(data["backup"])) else ""
    safety = data["safety"] if SAFETY_NAME.fullmatch(data["safety"]) else ""
    return InterruptedRestore(data["started"], backup, safety, bool(safety) and (_safety_root(ctx) / safety).is_dir())


def _interrupted_when_idle(ctx):
    """멈춘 복원의 흔적(`InterruptedRestore`) — **돌고 있는 백업·복원이 없을 때만**(복원이 도는 동안에도 표지는 있다 — 다른 창이 목록을 읽을 때 도는 복원을 멈춘 것으로 알리지 않게). 잠금을 잡아 보고 못 잡으면(다른 곳에서 돌고 있다) None,
    잡으면 곧 푼다(죽은 프로세스의 낡은 잠금은 넘겨받는다). 흔적이 없으면 잠금을 건드리지 않는다."""
    pending = interrupted_restore(ctx)
    if pending is None:
        return None
    try:
        with _flow_lock(ctx):
            return pending
    except AppError:
        return None
    except OSError:
        return pending


def revert_interrupted_restore(ctx, *, confirmed, step=None):
    """중간에 멈춘 복원을 안전 사본으로 원래대로 돌린다 → `RestoreOutcome`. 확인(`confirmed=True`)이 없으면 CONFIRMATION_REQUIRED, 멈춘 흔적이 없으면 CONTENT_NOT_FOUND, 되돌릴 안전 사본이 없으면 FULL_BACKUP_INVALID.
    따로 만든 길이 아니라 **보통 복원(`restore_full_backup`)으로 그 안전 사본을 되돌리는 것**이라 확인·훑기·안전 사본·되돌리기가 모두 같다 — 앱이 시작할 때 혼자 되돌리지는 않는다(D-463: 쓰기는 늘 사용자의 확인 뒤에)."""
    require_confirmation(confirmed, "멈춘 복원을 안전 사본으로 되돌리기")
    pending = interrupted_restore(ctx)
    if pending is None:
        raise AppError("CONTENT_NOT_FOUND", {"항목": "멈춘 복원"}, detail="멈춘 복원의 흔적이 없다")
    return restore_full_backup(ctx, pending.safety, confirmed=True, step=step)                      # 안전 사본 이름이 없거나 폴더가 없으면 보통 복원이 FULL_BACKUP_INVALID(missing) 로 거절한다


# ---- 보관함·JSON 사본 만들기와 점검 ---------------------------------------------------------------------------------------------------------
def _table_counts(path):
    """보관함 파일의 표마다 행 수 — 목록에 '글 몇 개' 를 적는 데 쓴다(표 이름은 앱이 정한 고정 이름)."""
    with closing(sqlite3.connect(_read_only_uri(path), uri=True, timeout=BUSY_SECONDS)) as db:
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: db.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in names}


def _check_database(kind, path):
    """사본(보관함 파일)이 이 프로그램의 온전한 보관함인지 읽기 전용으로 확인한다(이름표·판·모양·구조 점검·자료 점검) → 표마다 행 수. 틀리면 AppError(원래 코드 — 깨짐·더 새로운 판 …)."""
    opener = (lambda target: Store.open(target, migrate=False)) if kind == STORE else open_read_only
    with opener(path) as database:
        if not (kind == ENGINE and database.needs_migration):                        # 옛 판 주제 보관함은 구조는 맞지만 자료 점검이 지금 판의 표를 기준으로 하므로 건너뛴다
            problems = database.check()
            if problems:
                raise AppError(DAMAGED_CODE[kind], {"파일": path.name} if kind == STORE else None, detail=str(problems[0])[:200])
    return _table_counts(path)


def _stage_sqlite(source, locked_code):
    """보관함 파일의 일관된 사본을 SQLite 백업 방식으로 **메모리에** 만들어 `vacuum` 으로 정리하고 그 연결을 돌려준다(부른 쪽이 닫는다) — 지금 파일은 읽기 전용 연결로만 읽는다. 키·토큰 모양을 훑기 **전에는** 사본을 디스크에 쓰지 않으려는 것이다(D-461):
    메모리의 사본을 훑어 이상 없을 때만 `_write_sqlite` 가 파일로 쓴다. 다른 곳이 계속 쓰고 있어 `COPY_SECONDS` 가 넘도록 못 나아가면 멈추고 알린다(끝없이 기다리지 않는다).
    `Store.backup` 은 짝 파일을 더해 이 폴더를 어지럽힐 수 있어 쓰지 않고 같은 방식(백업 API)을 직접 쓴다(D-383). **사본은 `vacuum` 으로 정리한다** — 지운 글의 조각이 지금 파일의 빈 쪽에 남아 있어도(앱 밖의 도구가 쓴 파일·옛 파일) 백업에는 실리지 않는다(D-398).
    메모리 사본은 `-wal` 같은 짝 파일을 쓰는 저장 방식 표시도 떼어 일반 방식으로 쓰이므로 앱 밖의 도구가 바꾼 보관함도 백업된다(D-462)."""
    stuck = []

    def watch(status, remaining, total):
        if status not in (5, 6):                                                      # SQLITE_BUSY·SQLITE_LOCKED 가 아니면 나아가는 중이다
            stuck.clear()
            return
        if not stuck:
            stuck.append(time.monotonic())
        if time.monotonic() - stuck[0] > COPY_SECONDS:
            raise AppError(locked_code, detail=f"사본을 만드는 동안 {COPY_SECONDS:g}초가 넘도록 파일이 계속 잠겨 있다")

    memory = sqlite3.connect(":memory:")
    try:
        with closing(sqlite3.connect(_read_only_uri(source), uri=True, timeout=BUSY_SECONDS)) as reader:
            reader.backup(memory, progress=watch)
        memory.execute("pragma temp_store = memory")                                  # 정리하는 동안의 임시 사본도 시스템 임시 폴더가 아니라 메모리에 둔다(데이터 폴더 밖에 파일로 남지 않게)
        memory.execute("vacuum")                                                      # 사본의 빈 쪽을 정리한다(지금 파일은 건드리지 않는다) — 이름표(`application_id`·`user_version`)는 그대로 옮겨진다
    except BaseException:
        memory.close()
        raise
    return memory


def _write_sqlite(memory, target):
    """훑어서 이상 없는 메모리 사본을 파일로 쓴다(SQLite 백업 방식) — 디스크에 보관함 내용이 닿는 곳은 여기뿐이고, 여기까지 온 내용은 이미 훑어 이상이 없다."""
    with closing(sqlite3.connect(str(target))) as writer:
        memory.backup(writer)


def _snapshot_database(component, source, target, found):
    """보관함 하나: 읽기 전용으로 열어 보고 → 메모리에 사본 → **메모리에서 훑기** → 이상 없을 때만 파일로 쓰고 → 쓴 파일을 점검한다 → 표마다 행 수. 키·토큰 모양이 있으면(이번 것이든 앞선 파일의 것이든) 쓰지 않고 None 을 돌려준다(위치는 `found` 에 모인다)."""
    if component.kind == STORE:
        with Store.open(source, migrate=False):                                      # 읽기 전용으로 열어 보기만 한다 — 깨짐·더 새로운 판·정리 못 한 저장·잠김은 여기서 AppError(지금 파일을 만들지도 바꾸지도 않는다)
            pass
    else:
        with open_read_only(source):
            pass
    memory = _stage_sqlite(source, "STORE_LOCKED" if component.kind == STORE else "TOPIC_STORE_LOCKED")
    try:
        try:
            _scan_connection(found, memory, component.name)
        except sqlite3.Error:
            raise AppError(DAMAGED_CODE[component.kind], {"파일": component.name} if component.kind == STORE else None, detail="사본을 훑다가 읽을 수 없었다") from None
        if found:
            return None
        _write_sqlite(memory, target)
    finally:
        memory.close()
    return _check_database(component.kind, target)


def _read_source(path):
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail=f"파일이 너무 크다(최대 {MAX_JSON_BYTES // (1024 * 1024)}MB)")
        return path.read_bytes()
    except OSError as error:
        raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail=f"읽을 수 없다: {type(error).__name__}") from None


def _settings_items(raw):
    return {"profiles": len(raw["naver_profiles"]), "repo": 1 if raw["repo_path"] else 0}


def _snapshot_file(component, source, target, found):
    """JSON·설정 파일 하나: 읽은 바이트를 **먼저 훑고**(디스크에 쓰기 전) → 모양을 엄격하게 읽어 보고 → 키·토큰 모양이 없을 때만 그대로 쓴다 → 항목 수(있으면 None — 위치는 `found` 에 모인다). 읽을 수 없거나 모양이 틀리면 AppError.
    엄격한 읽기가 키 모양 글을 '틀린 모양' 으로 거절해도 훑기가 먼저라서, 그 파일이 몰래 빠진 부분 백업이 되지 않고 '키 모양이 있어 백업하지 않음' 으로 알린다."""
    data = _read_source(source)
    _scan_json_leniently(found, data, component.name)                                # JSON 으로 읽을 수 없는 파일은 훑지 못한 채 아래의 엄격한 읽기가 거절한다(그 파일은 담지 않는다)
    if component.kind == SETTINGS:
        items = _settings_items(Settings(source)._read())                            # 모르는 칸·틀린 모양은 SETTINGS_INVALID — 읽어 보기만 한다
    else:
        items = {"count": len(check_json_bytes(component.name, data))}
    if found:
        return None
    _write_durably(target, data)
    return items


def _snapshot(component, source, target, found):
    """파일 하나의 점검한 사본을 `target` 에 만든다 → 항목 수(키·토큰 모양이 있어 쓰지 않았으면 None — 위치는 `found` 에 모인다). **훑기 전에는 디스크에 쓰지 않는다**(D-461): 보관함은 메모리에서, JSON·설정은 읽은 바이트에서 먼저 훑는다.
    지금 파일을 읽을 수 없으면 `_Skip`(그 파일만 건너뛴다 — 쓴 사본이 있으면 치운다, 훑어서 이상 없는 내용이다), 사본을 쓰다 난 OS 오류는 그대로 올려 백업 전체를 멈춘다."""
    try:
        if component.kind in (STORE, ENGINE):
            return _snapshot_database(component, source, target, found)
        return _snapshot_file(component, source, target, found)
    except AppError as error:
        _remove_quietly(target)
        raise _Skip(error.code) from None


# ---- 키·토큰 모양 훑기(만든 사본을 훑는다) ----------------------------------------------------------------------------------------------------
def _clip(where):
    return where if len(where) <= MAX_WHERE_CHARS else where[:MAX_WHERE_CHARS - 1] + "…"


def _scan_text(sink, text, where, fallback):
    """글 하나를 훑어 위치·유형을 `sink` 에 모은다. 칸 이름이 키 모양처럼 보여 검사기가 받지 않으면(JSON 칸 이름이 키 글인 경우) 고정 이름으로 다시 훑는다."""
    try:
        sink.extend(scan.scan_secrets(text, _clip(where)))
    except ValueError:
        sink.extend(scan.scan_secrets(text, fallback))


def _key_text(token):
    """JSON 칸 이름 하나를 사람이 읽는 말로 — 앱이 아는 이름이거나 영문·숫자·밑줄 40자 안의 이름이 아니면 `…`(칸 이름이 글 내용일 수 없게)."""
    return KEY_LABEL.get(token) or (token if _SAFE_KEY.fullmatch(token) else "…")


def _path_text(path):
    parts = [f"{token + 1}번째 항목" if isinstance(token, int) else _key_text(token) for token in path[-3:]]
    return " › ".join(parts)


def _walk(value, path, emit):
    """JSON 값의 모든 글(칸 이름 포함)을 `emit(경로, 글, 칸이름인가)` 로 건넨다. 경로는 칸 이름(글)과 목록 위치(정수)의 튜플이다."""
    if isinstance(value, str):
        emit(path, value, False)
    elif isinstance(value, dict):
        for key, item in value.items():
            emit(path, str(key), True)
            _walk(item, path + (str(key),), emit)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, path + (index,), emit)


def _scan_json_value(sink, value, area, field="", row=""):
    fallback = _clip(area)

    def emit(path, text, is_key):
        place = (_path_text(path) + " › 칸 이름" if path else "칸 이름") if is_key else _path_text(path)
        _scan_text(sink, text, " · ".join(part for part in (area, field, place, row) if part), fallback)

    _walk(value, (), emit)


def _scan_database(sink, path, name):
    """보관함 파일의 모든 표·모든 글 칸을 훑는다 — 읽기 전용으로 열어서(백업 폴더의 사본·복원할 백업을 훑을 때)."""
    with closing(sqlite3.connect(_read_only_uri(path), uri=True, timeout=BUSY_SECONDS)) as db:
        _scan_connection(sink, db, name)


def _scan_connection(sink, db, name):
    """열린 보관함 연결(디스크에 쓰기 전의 메모리 사본이거나 읽기 전용으로 연 파일)의 모든 표·모든 글 칸을 훑는다(JSON 으로 된 칸은 풀어서 칸마다). 발행 이력 장부는 훑지 않는다(D-75)."""
    area, skipped = AREA[name], SKIPPED_TABLES.get(name, frozenset())
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        if table in skipped:
            continue
        columns = [row[1] for row in db.execute("SELECT * FROM pragma_table_info(?)", (table,))]
        quoted = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
        cursor = db.execute(f'SELECT {quoted} FROM "' + table.replace('"', '""') + '"')
        while True:
            rows = cursor.fetchmany(500)
            if not rows:
                break
            for values in rows:
                ref = ""
                first = values[0] if values else None
                if table in ROW_LABEL and isinstance(first, str) and _ROW_ID.fullmatch(first):
                    ref = f"{ROW_LABEL[table]} {first[:8]}"
                for column, value in zip(columns, values):
                    _scan_cell(sink, value, area, table, column, ref)


def _scan_cell(sink, value, area, table, column, ref):
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str) or not value:
        return
    field = FIELD_LABEL.get((table, column)) or (f"{table}.{column}" if _SAFE_KEY.fullmatch(table) and _SAFE_KEY.fullmatch(column) else "표 안의 글")
    if value[:1] in "{[":
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            parsed = None
        if parsed is not None:
            _scan_json_value(sink, parsed, area, field, ref)
            return
    _scan_text(sink, value, " · ".join(part for part in (area, field, ref) if part), _clip(area))


def _scan_json_bytes(sink, data, name):
    """JSON 파일의 바이트(디스크에 쓰기 전의 것이거나 읽어 온 것)를 훑는다. JSON 으로 읽을 수 없으면 AppError."""
    try:
        parsed = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AppError("TOPIC_FILE_INVALID", {"파일": name}, detail="훑으려고 읽었지만 읽을 수 없다") from None
    _scan_json_value(sink, parsed, AREA[name])


def _scan_json_leniently(sink, data, name):
    """`_scan_json_bytes` 인데 JSON 으로 읽을 수 없으면 오류 대신 False(훑지 못했다) — 읽을 수 없는 파일은 엄격한 읽기가 따로 거절한다."""
    try:
        _scan_json_bytes(sink, data, name)
    except AppError:
        return False
    return True


def _scan_json_file(sink, path, name):
    try:
        data = path.read_bytes()
    except OSError:
        raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail="훑으려고 읽었지만 읽을 수 없다") from None
    _scan_json_bytes(sink, data, name)


def scan_folder(folder, names, lenient=frozenset()):
    """백업 폴더 안의 `names` 파일들을 훑어 키·토큰 모양의 위치·유형 목록을 돌려준다(글 내용은 없다). 없으면 빈 목록. `lenient` 에 든 파일은 읽을 수 없으면(깨짐 — 어차피 담지 않을 복사본) 훑지 못한 채 넘어간다."""
    folder = Path(folder)
    found = []
    for name in names:
        try:
            if BY_NAME[name].kind in (STORE, ENGINE):
                _scan_database(found, folder / name, name)
            else:
                _scan_json_file(found, folder / name, name)
        except (AppError, sqlite3.Error):
            if name not in lenient:
                raise
    return found


def _blocked(findings, action, *, inside_backup=False):
    """훑어 낸 위치들 → `FULL_BACKUP_BLOCKED`(위치·유형만 — 글 내용이 없다). 위치가 많으면 처음 `MAX_SHOWN_PLACES` 곳만 풀어 쓴다. `action` 은 '백업'(백업을 만들다 찾았다)이거나 '복원'(되돌리기 직전에 남길 지금 데이터에서 찾았다)이고,
    `inside_backup` 은 되돌릴 **백업 안**에서 찾았다는 뜻이다 — 그 글은 앱이 고칠 수 없으므로 '지운 뒤 다시' 대신 그 백업은 쓰지 않았다고 말한다."""
    places = []
    for item in findings:
        if item.where not in places:
            places.append(item.where)
    shown_places = set(places[:MAX_SHOWN_PLACES])
    shown = [item for item in findings if item.where in shown_places]
    lines = scan.summarize(shown, action).split("\n")
    more = len(places) - len(shown_places)
    if more > 0:
        lines.insert(len(lines) - 1, f"그 밖에 {more}곳에서도 찾았어요")
    if inside_backup:
        lines[-1] = "이 백업 안의 글이라 앱이 고치지 않아요 — 이 백업으로는 복원하지 않았어요"
    summary = "\n".join(lines)
    return FlowError("FULL_BACKUP_BLOCKED", {"위치": " / ".join(lines[:-1])}, detail=f"키·토큰 모양 {len(findings)}건 — {len(places)}곳", reason="blocked", findings=shown, summary=summary, more=max(more, 0))


# ---- 목록 파일 -----------------------------------------------------------------------------------------------------------------------
def _manifest_dict(moment, version, saved, missing, skipped):
    status = STATUS_PARTIAL if skipped else STATUS_COMPLETE
    files = {name: {"size": info["size"], "sha256": info["sha256"], "items": dict(info["items"])} for name, info in saved.items()}
    return {"schema": MANIFEST_SCHEMA, "kind": KIND, "app_version": version, "created_at": _utc_text(moment), "status": status, "credential_excluded": True, "credential_excluded_note": CREDENTIAL_NOTE,
            "secret_scan": {"checked": True, "kinds": list(scan.KINDS), "found": 0}, "files": files, "missing": list(missing), "skipped": dict(skipped),
            "excluded": [{"name": name, "reason": reason} for name, reason in EXCLUDED]}


def _manifest_bytes(manifest):
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


MANIFEST_KEYS = frozenset({"schema", "kind", "app_version", "created_at", "status", "credential_excluded", "credential_excluded_note", "secret_scan", "files", "missing", "skipped", "excluded"})


def _invalid(folder, reason, *, detail=""):
    return FlowError("FULL_BACKUP_INVALID", {"파일": _shown_name(Path(folder).name), "이유": INVALID_REASONS[reason]}, detail=detail or INVALID_REASONS[reason], reason=reason)


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parse_manifest(folder):
    """폴더의 `MANIFEST.json` 을 엄격하게 읽는다(모르는 칸·틀린 모양·모르는 파일 이름은 거절). 모양이 맞으면 dict, 아니면 FULL_BACKUP_INVALID. 더 새로운 목록 판은 STORE_VERSION_UNSUPPORTED."""
    try:
        path = Path(folder) / MANIFEST_NAME
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise _invalid(folder, "manifest", detail="목록 파일이 너무 크다")
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise _invalid(folder, "manifest") from None
    if isinstance(data, dict) and isinstance(data.get("schema"), int) and not isinstance(data.get("schema"), bool) and data["schema"] > MANIFEST_SCHEMA:
        raise FlowError("STORE_VERSION_UNSUPPORTED", {"파일": _shown_name(Path(folder).name)}, detail=f"목록 판 {data['schema']} > 지원 {MANIFEST_SCHEMA}", reason="newer")
    problem = _manifest_problem(data)
    if problem:
        raise _invalid(folder, "manifest", detail=problem)
    return data


def _manifest_problem(data):
    """목록 dict 의 모양이 틀린 첫 곳을 설명하는 글(맞으면 빈 글) — 값은 되풀이하지 않는다."""
    if not isinstance(data, dict) or set(data) != MANIFEST_KEYS:
        return "칸이 다르다"
    if isinstance(data["schema"], bool) or data["schema"] != MANIFEST_SCHEMA or data["kind"] != KIND or data["status"] not in (STATUS_COMPLETE, STATUS_PARTIAL):        # `True == 1` 이라 불리언 `true` 를 1 로 받지 않는다(D9)
        return "판·종류·상태가 다르다"
    if data["credential_excluded"] is not True or not isinstance(data["credential_excluded_note"], str) or len(data["credential_excluded_note"]) > MAX_NOTE_CHARS:
        return "자격 증명 제외 표시가 다르다"
    if not isinstance(data["app_version"], str) or (data["app_version"] and _version_key(data["app_version"]) is None):
        return "앱 버전 모양이 다르다"
    try:
        datetime.strptime(data["created_at"], _STAMP_TEXT)
    except (TypeError, ValueError):
        return "만든 때 모양이 다르다"
    files, missing, skipped = data["files"], data["missing"], data["skipped"]
    if not isinstance(files, dict) or not files or not set(files) <= set(BY_NAME):
        return "파일 목록이 다르다"
    for info in files.values():
        if (not isinstance(info, dict) or set(info) != {"size", "sha256", "items"} or not _is_count(info["size"]) or not isinstance(info["sha256"], str) or not _SHA.fullmatch(info["sha256"])
                or not isinstance(info["items"], dict) or not all(isinstance(key, str) and _is_count(number) for key, number in info["items"].items())):
            return "파일 한 줄의 모양이 다르다"
    if not isinstance(missing, list) or not all(isinstance(item, str) and item in BY_NAME for item in missing) or len(set(missing)) != len(missing):
        return "없는 파일 목록이 다르다"
    if not isinstance(skipped, dict) or not all(isinstance(key, str) and key in BY_NAME and isinstance(value, str) and len(value) <= 60 for key, value in skipped.items()):
        return "담지 못한 파일 목록이 다르다"
    if set(files) & set(missing) or set(files) & set(skipped) or set(missing) & set(skipped):
        return "한 파일이 두 곳에 적혔다"
    if data["status"] == STATUS_COMPLETE and skipped:
        return "완료인데 담지 못한 파일이 있다"
    if data["status"] == STATUS_PARTIAL and not skipped:
        return "부분인데 담지 못한 파일이 없다"
    if not _scan_note_ok(data["secret_scan"]) or not _excluded_ok(data["excluded"]):
        return "검사·제외 목록이 다르다"
    return ""


def _scan_note_ok(note):
    """목록의 훑기 기록 모양 — 훑었고(`checked`) 찾은 것이 없다(`found` 0, 있었다면 백업이 만들어지지 않았다)는 기록뿐이다. 글 내용 칸은 없다(D9)."""
    return (isinstance(note, dict) and set(note) == {"checked", "kinds", "found"} and note["checked"] is True and not isinstance(note["found"], bool) and note["found"] == 0
            and isinstance(note["kinds"], list) and len(note["kinds"]) <= 20 and all(isinstance(kind, str) and len(kind) <= 40 for kind in note["kinds"]))


def _excluded_ok(items):
    """목록의 '담지 않은 것' 모양 — 이름과 이유 글뿐인 항목들(D9)."""
    return isinstance(items, list) and len(items) <= 50 and all(isinstance(item, dict) and set(item) == {"name", "reason"} and all(isinstance(item[key], str) and len(item[key]) <= MAX_NOTE_CHARS for key in item) for item in items)


def _check_version(folder, manifest):
    """더 새로운 앱이 만든 백업은 거절한다 — 이 프로그램이 모르는 데이터일 수 있다."""
    mine, theirs = _version_key(read_app_version()), _version_key(manifest["app_version"])
    if mine is not None and theirs is not None and theirs > mine:
        raise FlowError("STORE_VERSION_UNSUPPORTED", {"파일": _shown_name(Path(folder).name)}, detail=f"백업 앱 버전 {manifest['app_version']} > 이 앱 {read_app_version()}", reason="newer")


def _file_lines(manifest):
    """목록 → 파일 줄들(모든 칸을 정해진 순서로 — 담았다·아직 없다·담지 못했다)."""
    lines = []
    for component in COMPONENTS:
        info = manifest["files"].get(component.name)
        if info is not None:
            lines.append(FileLine(component.name, component.label, LINE_SAVED, info["size"], tuple(info["items"].items())))
        elif component.name in manifest["skipped"]:
            lines.append(FileLine(component.name, component.label, LINE_SKIPPED, reason=manifest["skipped"][component.name]))
        else:
            lines.append(FileLine(component.name, component.label, LINE_MISSING))
    return tuple(lines)


def _row_of(folder, manifest, kind):
    size = sum(info["size"] for info in manifest["files"].values())
    return BackupRow(Path(folder).name, kind, manifest["created_at"], manifest["status"], size, _file_lines(manifest), True, manifest["app_version"])


# ---- 확인 -----------------------------------------------------------------------------------------------------------------------------
def _verify_folder(folder):
    """백업 폴더를 읽기만 해서 확인한다 → 목록. 목록 모양·폴더 안의 파일(이름·종류)·크기·해시를 본다(안의 보관함·JSON·설정이 온전한지는 `_verify_backup` 이 이어서 이 프로그램이 읽는 방법 그대로 읽어 본다).
    틀리면 FULL_BACKUP_INVALID(이유 `manifest`·`files`·`hash`·`content`) — 더 새로운 앱의 백업은 STORE_VERSION_UNSUPPORTED. 아무것도 쓰지 않는다."""
    folder = Path(folder)
    manifest = _parse_manifest(folder)
    _check_version(folder, manifest)
    try:
        entries = {entry.name: entry for entry in folder.iterdir()}
    except OSError:
        raise _invalid(folder, "files") from None
    if set(entries) != set(manifest["files"]) | {MANIFEST_NAME} or any(entry.is_symlink() or not entry.is_file() for entry in entries.values()):
        raise _invalid(folder, "files")
    for name, info in manifest["files"].items():
        try:
            same = entries[name].stat().st_size == info["size"] and _sha256_file(entries[name]) == info["sha256"]
        except OSError:
            raise _invalid(folder, "files", detail=f"{name} 을 읽을 수 없다") from None
        if not same:
            raise _invalid(folder, "hash", detail=f"{name} 의 크기나 해시가 목록과 다르다")
    return manifest


def _verify_backup(folder):
    """되돌릴 백업을 읽기만 해서 끝까지 확인한다 → 목록. ① 목록 모양·파일·크기·해시 ② **키·토큰 모양 훑기**(엄격한 읽기보다 먼저 — 그 읽기가 키 모양 글을 '틀린 모양' 으로 거절해도 이유가 '키 모양' 으로 알려지게. 읽을 수 없는 파일은
    훑지 못한 채 ③ 으로 넘어간다) ③ 안의 보관함·JSON·설정이 이 프로그램이 읽는 방법 그대로 온전한가."""
    manifest = _verify_folder(folder)
    found = scan_folder(folder, list(manifest["files"]), lenient=frozenset(manifest["files"]))
    if found:
        raise _blocked(found, "복원", inside_backup=True)
    for name in manifest["files"]:
        _check_content(folder, name)
    return manifest


def _check_content(folder, name):
    component = BY_NAME[name]
    path = folder / name
    try:
        if component.kind in (STORE, ENGINE):
            _check_database(component.kind, path)
        elif component.kind == SETTINGS:
            Settings(path)._read()
        else:
            check_json_bytes(name, path.read_bytes())
    except AppError as error:
        if error.code in STORE_NEWER:
            raise FlowError("STORE_VERSION_UNSUPPORTED", {"파일": _shown_name(folder.name)}, detail=f"{name}: 이 앱보다 새로운 판", reason="newer") from None
        raise _invalid(folder, "content", detail=f"{name}: {error.code}") from None
    except OSError as error:
        raise _invalid(folder, "content", detail=f"{name}: {type(error).__name__}") from None


def _folders(root, pattern=FULL_NAME):
    """폴더 안의 앱이 만든 모양(`pattern`)의 백업 폴더들(새 것이 먼저)."""
    try:
        found = [entry for entry in Path(root).iterdir() if entry.is_dir() and pattern.fullmatch(entry.name)]
    except OSError:
        return []
    return sorted(found, key=lambda entry: (_stamp_of(entry.name), len(entry.name), entry.name), reverse=True)


def _quick_row(folder, kind):
    """목록의 한 줄 — 목록 모양과 파일 존재·크기만 본다(해시는 복원할 때 본다). 읽을 수 없으면 `broken` 줄이다."""
    folder = Path(folder)
    try:
        manifest = _parse_manifest(folder)
        sizes = {entry.name: entry.stat().st_size for entry in folder.iterdir() if entry.is_file() and not entry.is_symlink()}
    except FlowError as error:
        return _broken_row(folder, kind, error.reason or "manifest")
    except OSError:
        return _broken_row(folder, kind, "files")
    if set(sizes) != set(manifest["files"]) | {MANIFEST_NAME} or any(sizes[name] != info["size"] for name, info in manifest["files"].items()):
        return _broken_row(folder, kind, "files", manifest=manifest)
    return _row_of(folder, manifest, kind)


def _broken_row(folder, kind, problem, manifest=None):
    name = folder.name
    if problem == "newer":
        problem = "manifest"
    lines = _file_lines(manifest) if manifest is not None else ()
    size = sum(info["size"] for info in manifest["files"].values()) if manifest is not None else 0
    return BackupRow(name, kind, _name_stamp(name), STATUS_BROKEN, size, lines, bool(manifest), manifest["app_version"] if manifest is not None else "", problem)


def list_full_backups(ctx):
    """화면의 백업 목록 — `backups/` 의 백업과 `backups/before-restore/` 의 복원 직전 안전 사본(새 것이 먼저). 읽기만 한다(없는 폴더를 만들지 않는다) — 다만 앱이 갑자기 꺼져 남은 임시 폴더·낡은 잠금이 보이면
    살아 있는 백업·복원이 없을 때에 한해 그것을 치운다(D-461)."""
    _sweep_if_stale(ctx)
    rows = [_quick_row(folder, "backup") for folder in _folders(ctx.workspace.backups_dir)]
    rows += [_quick_row(folder, "safety") for folder in _folders(_safety_root(ctx), SAFETY_NAME)]
    rows.sort(key=lambda row: (_stamp_of(row.name), row.kind == "backup", row.name), reverse=True)
    return BackupList(tuple(rows), str(ctx.workspace.backups_dir), KEEP_BACKUPS, _interrupted_when_idle(ctx))


# ---- 백업 만들기 -----------------------------------------------------------------------------------------------------------------------
def _free_name(root, name):
    for number in range(1, MAX_NAMES + 1):
        candidate = root / (name if number == 1 else f"{name}-{number}")
        if not candidate.exists():
            return candidate
    raise AppError("BACKUP_FAILED", detail=f"같은 초에 만든 백업 이름이 {MAX_NAMES}개를 넘었다")


def _prune(root, keep, pattern=FULL_NAME, protect=(), moment=None):
    """가장 새 `keep` 개만 남기고 지운다. `protect` 의 이름(방금 만든 것·되돌리는 데 쓰는 것)은 절대 지우지 않고 가장 새 것으로 센다. **시계가 거꾸로 갔거나 다른 PC 에서 가져와 `moment`(지금)보다 미래 날짜인 폴더는 가장 낡은 것으로 센다** —
    미래 날짜의 옛 백업이 지금 만든 백업보다 앞서 서서 방금 만든 것을 지우는 일이 없다(D-460)."""
    limit = moment.strftime(SIDE_STAMP) if moment is not None else ""

    def rank(entry):
        stamp = _stamp_of(entry.name)
        return (entry.name in protect, not (limit and stamp > limit), stamp, len(entry.name), entry.name)

    for old in sorted(_folders(root, pattern), key=rank, reverse=True)[max(keep, 1):]:
        if old.name not in protect:
            _remove_known_folder(old)                                   # 못 지워도(낯선 파일이 있거나 쓰는 중) 백업 자체는 성공이다


def _plan(ctx, only):
    """담을 후보 → (있는 것들 `[(Component, 경로)]`, 아직 없는 것들의 이름, 파일이 아닌 것들의 이름). 0바이트 파일은 만들다 멈춘 흔적이라 '아직 없음' 이다."""
    present, missing, odd = [], [], []
    for component in COMPONENTS:
        if only is not None and component.name not in only:
            continue
        path = _component_path(ctx, component)
        try:
            if not path.exists():
                missing.append(component.name)
            elif not path.is_file():
                odd.append(component.name)
            elif path.stat().st_size == 0:
                missing.append(component.name)
            else:
                present.append((component, path))
        except OSError:
            odd.append(component.name)
    return present, missing, odd


def _build(ctx, root, moment, *, only=None, step=_no_step, action="백업", prefix="full"):
    """`root` 안에 새 백업 폴더를 만든다 → `BackupOutcome`. 잠금은 부른 쪽이 쥐고 있다. 임시 폴더에는 **메모리에서 훑어 이상 없는 내용만** 쓰고(D-461), 다 만든 뒤 다시 훑고 확인한 다음에야 이름을 바꾼다 — 실패·중단하면 아무것도 남기지 않는다."""
    present, missing, odd = _plan(ctx, only)
    if not present and not odd:
        raise AppError("CONTENT_NOT_FOUND", {"항목": "백업할 데이터"}, detail="담을 파일이 하나도 없다")
    stamp = moment.strftime(SIDE_STAMP)
    name = f"{prefix}-{stamp}"
    temp = root / (name + ".tmp")
    created = _missing_folders(root)
    saved, skipped, found = {}, {item: DAMAGED_CODE[BY_NAME[item].kind] for item in odd}, []
    try:
        _make_folder(root)
        if temp.exists() and not _remove_known_folder(temp, TEMP_FILES):
            raise AppError("FILE_WRITE_FAILED", {"경로": temp.name}, detail="지난번에 멈춘 임시 폴더를 치우지 못했다")
        _make_folder(temp)
        total = max(len(present), 1)
        for index, (component, source) in enumerate(present):
            step(0.1 + 0.6 * index / total, f"{component.label} 담는 중")
            target = temp / component.name
            try:
                items = _snapshot(component, source, target, found)
            except _Skip as skip:
                skipped[component.name] = skip.code
                continue
            if items is not None:                                       # None — 키·토큰 모양이 있어 쓰지 않았다(위치는 `found`)
                saved[component.name] = {"size": target.stat().st_size, "sha256": _sha256_file(target), "items": items}
        step(0.75, "키·토큰 모양이 없는지 훑는 중")
        if found:
            raise _blocked(found, action)
        found = scan_folder(temp, list(saved))                          # 쓴 파일을 한 번 더 훑는다(메모리에서 훑은 것과 같아야 한다 — 이중 확인)
        if found:
            raise _blocked(found, action)
        if not saved:
            raise FlowError("BACKUP_FAILED", detail="담을 수 있는 파일이 하나도 없다: " + ", ".join(f"{key}={value}" for key, value in skipped.items()), reason="nothing", skipped=skipped)
        step(0.88, "백업을 확인하는 중")
        manifest = _manifest_dict(moment, read_app_version(), saved, [item for item in missing if item not in skipped], skipped)
        _write_durably(temp / MANIFEST_NAME, _manifest_bytes(manifest))
        _verify_folder(temp)                                           # 다 만든 것을 다시 읽어 확인한 뒤에야 이름을 바꾼다
        step(0.95, "백업을 마무리하는 중")
        final = _free_name(root, name)
        _finish_folder(temp, final)
    except (OSError, sqlite3.Error) as error:
        _remove_known_folder(temp, TEMP_FILES)                          # SQLite 가 쓰다 남긴 짝 파일(`-journal`…)도 함께 치운다
        _remove_empty(created)
        raise _io_failure(error, temp.name) from None
    except BaseException:
        _remove_known_folder(temp, TEMP_FILES)
        _remove_empty(created)
        raise
    return BackupOutcome(_row_of(final, manifest, "safety" if root.name == SAFETY_FOLDER else "backup"))


def create_full_backup(ctx, *, step=None):
    """전체 백업 한 번 — 글 보관함·주제 엔진·설정을 `backups/full-날짜-시각/` 에 담는다 → `BackupOutcome`(완료 또는 부분). 담을 데이터가 없으면 CONTENT_NOT_FOUND, 키·토큰 모양이 있으면 FULL_BACKUP_BLOCKED(폴더를 남기지 않는다),
    다른 백업·복원이 도는 중이면 BACKUP_IN_PROGRESS(아무것도 바꾸지 않는다). `step(비율, 글)` 은 진행을 알리고(취소하려면 거기서 예외를 낸다 — 임시 폴더는 치워진다) 안 줘도 된다."""
    step = step or _no_step
    if not ctx.workspace.root.is_dir():
        raise AppError("CONTENT_NOT_FOUND", {"항목": "백업할 데이터"}, detail="데이터 폴더가 아직 없다")
    with _flow_lock(ctx):
        step(0.02, "백업을 시작하는 중")
        _sweep_locked(ctx)                                              # 앱이 갑자기 꺼져 남은 임시 폴더를 먼저 치운다
        moment = ctx.now()
        outcome = _build(ctx, ctx.workspace.backups_dir, moment, step=step)
        _prune(ctx.workspace.backups_dir, KEEP_BACKUPS, protect=(outcome.row.name,), moment=moment)
        step(1.0, "백업을 마쳤어요")
    return outcome


# ---- 되돌리기 -------------------------------------------------------------------------------------------------------------------------
def _resolve(ctx, source):
    """되돌릴 백업 폴더 — 이름(`full-날짜-시각`, 백업 폴더나 안전 사본 폴더 안)이거나 폴더 경로(`Path`). 없으면 FULL_BACKUP_INVALID. 이름이 아닌 글(경로 모양)은 이름으로 받지 않는다."""
    if isinstance(source, Path):
        if source.is_dir():
            return source
        raise _invalid(source, "missing")
    if isinstance(source, str):
        root = ctx.workspace.backups_dir if FULL_NAME.fullmatch(source) else (_safety_root(ctx) if SAFETY_NAME.fullmatch(source) else None)
        if root is not None and (root / source).is_dir():
            return root / source
    raise FlowError("FULL_BACKUP_INVALID", {"파일": _shown_name(source), "이유": INVALID_REASONS["missing"]}, detail="백업 폴더에서 찾을 수 없다", reason="missing")


def _live_state(ctx, component, healed=False):
    """지금 파일 하나의 상태(읽기만) — `missing`(없음·0바이트)·`blank`(0바이트)·`ok`(안전 사본에 담을 수 있음)·`damaged`(읽을 수 없거나 모양이 틀림 — 지우지 않고 옆으로 옮겨 둔다).
    더 새로운 앱의 데이터·다른 곳이 쓰는 중인 파일은 덮어쓰면 안 되므로 그대로 멈춘다(FlowError)."""
    path = _component_path(ctx, component)
    try:
        if not path.exists():
            return "missing"
        if not path.is_file():
            raise AppError("FILE_WRITE_FAILED", {"경로": path.name}, detail="파일이 아니라 폴더 같은 것이다")
        if path.stat().st_size == 0:
            return "blank"
    except OSError as error:
        raise _io_failure(error, path.name) from None
    try:
        if component.kind in (STORE, ENGINE):
            opener = (lambda target: Store.open(target, migrate=False)) if component.kind == STORE else open_read_only
            try:
                with opener(path) as database:
                    problems = [] if (component.kind == ENGINE and database.needs_migration) else database.check()
            except AppError as error:
                if not healed and error.code in ("STORE_RECOVERY_PENDING", "TOPIC_STORE_RECOVERY_PENDING"):    # 정리 못 한 저장 — 보관함을 한 번 열면 되돌려 정리된다(복원은 어차피 쓰는 일이다)
                    with (Store.open(path) if component.kind == STORE else open_for_write(path)):
                        pass
                    return _live_state(ctx, component, healed=True)
                raise
            return "damaged" if problems else "ok"
        if component.kind == SETTINGS:
            Settings(path)._read()
        else:
            check_json_bytes(component.name, _read_source(path))
        return "ok"
    except AppError as error:
        if error.code in STORE_NEWER:
            raise FlowError("STORE_VERSION_UNSUPPORTED", {"파일": component.label}, detail=f"{component.name}: 이 앱보다 새로운 판", reason="newer") from None
        if error.code in STORE_BUSY:
            raise FlowError(error.code, error.slots, detail=error.detail, reason="busy") from None
        if error.code in STORE_DAMAGED or error.code in ("TOPIC_FILE_INVALID", "SETTINGS_INVALID", "CONTENT_INVALID"):
            return "damaged"
        raise


def _restore_database(component, path, source):
    """보관함 하나를 백업 파일의 내용으로 한 번에 바꾼다(SQLite 백업 방식 — 도중에 실패하면 지금 보관함은 그대로다)."""
    with (Store.open(path) if component.kind == STORE else open_for_write(path)) as database:
        database.restore_from(source)


def _after_check(ctx, component, manifest):
    """바꾼 뒤 다시 읽어 확인한다 — JSON·설정은 해시가 목록과 같고 보관함은 구조·자료 점검이 통과해야 한다. 틀리면 AppError(복원을 원래대로 돌린다)."""
    path = _component_path(ctx, component)
    if component.kind in (STORE, ENGINE):
        _check_database(component.kind, path)
    elif _sha256_bytes(path.read_bytes()) != manifest["files"][component.name]["sha256"]:
        raise AppError("FILE_WRITE_FAILED", {"경로": path.name}, detail="바꾼 파일의 해시가 백업과 다르다")


RESTORE_REASON = {"disk": "저장 공간이 부족해요", "io": "파일을 쓰지 못했어요(읽기 전용이거나 다른 프로그램이 쓰고 있을 수 있어요)", "corrupt": "바꾼 뒤 다시 읽어 보니 온전하지 않았어요", "busy": "다른 곳에서 데이터를 쓰고 있어요",
                  "other": "예상하지 못한 문제가 생겼어요"}
RESTORE_KIND = {"DISK_FULL": "disk", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io", "FILE_PATH_TOO_LONG": "io", "STORE_CORRUPT": "corrupt", "TOPIC_STORE_CORRUPT": "corrupt", "STORE_LOCKED": "busy", "TOPIC_STORE_LOCKED": "busy"}


def _restore_failure(error, left):
    """복원 도중의 실패 → `RESTORE_FAILED`(원래대로 돌렸다는 말 + 종류 `reason` + 되돌리지 못한 것 `notes`). 이미 `FlowError` 인 것(안전 사본을 못 남김 등)은 그대로 두되 되돌리지 못한 것을 덧붙인다."""
    if isinstance(error, FlowError):
        error.notes = (*error.notes, *left)
        return error
    if isinstance(error, (OSError, sqlite3.Error)):
        error = _io_failure(error, "복원할 파일")
    code = error.code if isinstance(error, AppError) else "UNEXPECTED_ERROR"
    kind = RESTORE_KIND.get(code, "other")
    return FlowError("RESTORE_FAILED", {"이유": RESTORE_REASON[kind]}, detail=f"{code}: {getattr(error, 'detail', '') or type(error).__name__}"[:300], reason=kind, notes=left)


def restore_full_backup(ctx, source, *, confirmed, step=None):
    """백업 폴더의 내용으로 이 PC 의 데이터를 바꾼다 → `RestoreOutcome`(완료 또는 부분). 확인(`confirmed=True`)이 없으면 아무것도 하지 않고 CONFIRMATION_REQUIRED.
    바꾸기 전에 백업을 모두 확인하고(틀리면 FULL_BACKUP_INVALID·더 새로우면 STORE_VERSION_UNSUPPORTED — 아무것도 바뀌지 않는다), 안에 키·토큰 모양이 있으면 쓰지 않는다(FULL_BACKUP_BLOCKED).
    이 PC 의 지금 데이터는 `before-restore/` 에 안전 사본으로 먼저 남기고(키·토큰 모양이 있어 남길 수 없으면 시작하지 않는다), 도중에 실패하면 안전 사본으로 원래대로 돌린다(RESTORE_FAILED — 되돌리지 못한 것은 `notes`)."""
    require_confirmation(confirmed, "백업으로 되돌리기")
    step = step or _no_step
    folder = _resolve(ctx, source)
    step(0.05, "백업을 확인하는 중")
    first = _verify_backup(folder)                                       # 잠금·폴더 만들기 전의 첫 확인 — 틀린 백업이면 아무 흔적도 남기지 않는다
    ctx.workspace.ensure()
    with _flow_lock(ctx):
        _sweep_locked(ctx)                                              # 앱이 갑자기 꺼져 남은 임시 폴더를 먼저 치운다
        manifest = _verify_folder(folder)                               # 잠금 안에서 한 번 더 — 그 사이 파일이 바뀌지 않았는지(해시가 같으면 훑은 결과·내용 점검도 그대로다)
        if manifest != first:
            raise _invalid(folder, "manifest", detail="확인하는 사이에 목록이 바뀌었다")
        return _restore_locked(ctx, folder, manifest, step)


def _restore_locked(ctx, folder, manifest, step):
    moment = ctx.now()
    names = [component for component in COMPONENTS if component.name in manifest["files"]]
    live = {component.name: _live_state(ctx, component) for component in names}
    safe = [component.name for component in names if live[component.name] == "ok"]
    safety = None
    if safe:
        step(0.2, "지금 데이터를 안전 사본으로 남기는 중")
        safety = _build(ctx, _safety_root(ctx), moment, only=set(safe), step=lambda fraction, text="": step(0.2 + 0.2 * fraction, text), action="복원", prefix="before")
        if not set(safe) <= {line.name for line in safety.row.files if line.state == LINE_SAVED}:
            raise FlowError("RESTORE_FAILED", {"이유": "지금 데이터를 안전 사본으로 남기지 못해 시작하지 않았어요"}, detail="안전 사본에 빠진 파일이 있다", reason="safety")
    safety_folder = _safety_root(ctx) / safety.row.name if safety is not None else None
    state = {"originals": {}, "staged": [], "swapped": [], "moves": [], "db_done": [], "new_db": {}}
    try:
        _write_marker(ctx, folder, safety.row.name if safety is not None else "", names, moment)          # 지금 데이터를 바꾸기 직전에 '복원 진행 중' 표지를 남긴다(D-463)
    except (OSError, sqlite3.Error) as error:
        raise _restore_failure(error, ()) from None
    try:
        _apply(ctx, folder, manifest, names, live, safety_folder, state, moment, step)
    except BaseException as error:
        left = _roll_back(ctx, names, live, safety_folder, state)
        if not left:
            _clear_marker(ctx)                                                                           # 원래대로 돌렸으면 표지도 지운다 — 못 돌린 것이 있으면 표지가 남아 안내가 뜬다
        if isinstance(error, (AppError, OSError, sqlite3.Error)):
            raise _restore_failure(error, left) from None
        raise
    _prune(_safety_root(ctx), KEEP_BACKUPS, SAFETY_NAME, protect=(folder.name, safety.row.name if safety is not None else ""), moment=moment)
    _clear_marker(ctx)
    step(1.0, "복원을 마쳤어요")
    return _outcome(ctx, folder, manifest, names, live, safety)


def _apply(ctx, folder, manifest, names, live, safety_folder, state, moment, step):
    for component in names:
        if live[component.name] == "damaged":
            step(0.45, "깨진 파일을 옆으로 옮기는 중")
            aside = _move_aside(_component_path(ctx, component), moment)
            if aside is not None:
                state["moves"].append((component, aside))
    plain = [component for component in names if component.kind in (JSON_FILE, SETTINGS)]
    databases = [component for component in names if component.kind in (STORE, ENGINE)]
    step(0.5, "설정과 목록 파일을 바꾸는 중")
    for component in plain:
        target = _component_path(ctx, component)
        _make_folder(target.parent)
        state["originals"][component.name] = target.read_bytes() if target.is_file() else None
        stage = target.with_name(target.name + ".restoring")
        _write_durably(stage, (folder / component.name).read_bytes())
        state["staged"].append(stage)
    for component in plain:
        target = _component_path(ctx, component)
        _swap_in(target.with_name(target.name + ".restoring"), target)
        state["swapped"].append(component.name)
    for index, component in enumerate(databases):
        step(0.6 + 0.25 * index / max(len(databases), 1), f"{component.label}을 바꾸는 중")
        target = _component_path(ctx, component)
        if live[component.name] in ("missing", "blank", "damaged"):
            state["new_db"][component.name] = "blank" if live[component.name] == "blank" else "absent"
        _restore_database(component, target, folder / component.name)
        state["db_done"].append(component.name)
    step(0.9, "바뀐 것을 다시 읽어 확인하는 중")
    for component in names:
        _after_check(ctx, component, manifest)


def _roll_back(ctx, names, live, safety_folder, state):
    """복원이 도중에 실패했을 때 지금까지 바꾼 것을 안전 사본으로 되돌린다 → 되돌리지 못한 것을 말하는 쉬운 글 줄들(모두 되돌렸으면 빈 튜플). 단계마다 따로 시도해 한 단계가 또 실패해도 다음 단계를 막지 않는다."""
    left = []
    for stage in state["staged"]:
        _remove_quietly(stage)                                           # 임시 이름(`.restoring`)의 파일일 뿐이다 — 못 치워도 제자리 파일에는 영향이 없고 다음 복원이 덮어쓴다
    by_name = {component.name: component for component in names}
    pending = state["db_done"] + [item for item in state["new_db"] if item not in state["db_done"]]
    for name in reversed(pending):
        component, path = by_name[name], _component_path(ctx, by_name[name])
        try:
            if name in state["new_db"]:                                  # 복원 전에 없던(0바이트였던·깨져 옆으로 옮긴) 보관함 — 복원이 만든 것을 치운다
                _remove_file(path)
                _remove_file(str(path) + "-journal")
                if state["new_db"][name] == "blank":
                    _write_durably(path, b"")
            elif name in state["db_done"] and safety_folder is not None:
                _restore_database(component, path, safety_folder / name)
        except (AppError, OSError, sqlite3.Error):
            left.append(f"{component.label}은(는) 원래대로 돌리지 못했어요 — 원래 내용은 안전 사본({safety_folder.name if safety_folder else '없음'})에 있어요")
    for name in reversed(state["swapped"]):
        target = _component_path(ctx, by_name[name])
        original = state["originals"].get(name)
        try:
            if original is None:
                _remove_file(target)
            else:
                temp = target.with_name(target.name + ".restoring")
                _write_durably(temp, original)
                _swap_in(temp, target)
        except OSError:
            left.append(f"{by_name[name].label}은(는) 원래 내용으로 돌리지 못했어요 — 원래 내용은 안전 사본에 있어요")
    for component, aside in reversed(state["moves"]):
        try:
            _put_back(aside, _component_path(ctx, component))
        except OSError:
            left.append(f"{component.label}은(는) 제자리로 돌리지 못했어요 — 그 내용은 옆에 `{aside.name}` 으로 그대로 남아 있어요")
    return tuple(left)


def _outcome(ctx, folder, manifest, names, live, safety):
    lines = []
    for component in COMPONENTS:
        info = manifest["files"].get(component.name)
        if info is not None:
            lines.append(FileLine(component.name, component.label, LINE_RESTORED, info["size"], tuple(info["items"].items())))
        else:
            lines.append(FileLine(component.name, component.label, LINE_KEPT, reason=manifest["skipped"].get(component.name, "")))
    notes = [RESTORE_NOTE]
    moved = [component.label for component in names if live[component.name] == "damaged"]
    if moved:
        notes.append("깨져 있던 " + "·".join(moved) + "은(는) 지우지 않고 옆(.bad-날짜-시각)에 옮겨 뒀어요")
    if manifest["status"] == STATUS_PARTIAL:
        notes.append("이 백업은 '부분' 백업이라 담기지 않은 항목은 지금 것을 그대로 뒀어요")
    if "settings.json" in manifest["files"]:
        try:
            repo = Settings(ctx.workspace.settings_path).repo_path()
        except AppError:
            repo = ""
        if repo and not Path(os.path.expanduser(repo)).is_dir():
            notes.append("연결해 둔 chanceblog 폴더를 이 PC 에서 찾지 못했어요 — 필요하면 설정에서 다시 연결해 주세요")
    status = STATUS_COMPLETE if manifest["status"] == STATUS_COMPLETE else STATUS_PARTIAL
    return RestoreOutcome(status, folder.name, safety.row.name if safety is not None else "", tuple(lines), tuple(notes))
