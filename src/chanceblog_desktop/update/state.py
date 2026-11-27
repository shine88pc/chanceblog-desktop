"""업데이트 상태 파일(`<데이터 폴더>/update/state.json`)의 읽기·원자적 쓰기와 시작 때 부팅 횟수 세기(UPDATE 설계서 3-5·3-6).

이 파일에 적히는 것: 적용한 가장 높은 `seq`(`last_seq` — **내려받기 전에는 올리지 않는다**: 실패한 확인이 시퀀스를 태우지 않게, 설치 도구에 넘기는 데 성공한 순간에만), 본 가장 늦은 시각(`last_seen_utc` — 시계가 크게 뒤로 간 것을 알아본다),
마지막 확인 결과, 진행 중인 적용(`pending` — 설치 도구에 넘기기 **전에** 기록한다), 정상으로 확인된 가장 최근 판, 다음에 한 번 보일 안내(`notice`). 키·토큰·글·경로·사용자 이름은 없다(시험이 카나리로 지킨다).
모든 쓰기는 같은 폴더의 임시 파일에 다 쓰고 디스크까지 내린 뒤 이름을 바꿔 넣는다 — 어느 단계에서 프로세스가 죽어도 옛 파일이거나 새 파일이지 반쪽 파일이 아니다.

`note_boot()` 는 앱이 켜질 때 가장 먼저(무거운 모듈을 불러오기 전에) 한 번 부르는 후크다(`packaging/gui_entry.py` 의 한 줄). **꺼진 채 출하한다**: 스위치 `UPDATE_APPLY` 가 꺼져 있으면 아무것도 읽지도 쓰지도 않는다
(적용이 없으면 진행 중인 적용도 없다). 켜져 있어도 어떤 실패(파일 없음·깨짐·권한)든 조용히 None 을 돌려줄 뿐 앱을 못 켜게 만들지 않는다. 하는 일: `pending.to` 가 지금 버전이면 시작 **전** 횟수가 기준(2) 미만이면 횟수를 하나 올려
저장하고(`first_boot`), 기준 이상이면 복구를 안내한다(`recovery_offered` — 연속 두 번 정상 표식이 없었다). `pending.from` 이 지금 버전이면 적용되지 않은 것이라 표식을 지우고 안내만 남긴다(`not_applied`).
**복구도 '띄웠다' 와 '됐다' 를 가른다**(독립 검증 S R4): 복구가 이전 판 Setup 을 띄운 직후에는 `notice` 를 `rollback_launched` 로만 적고 `pending` 은 지우지 않는다(복구 Setup 이 조용히 안 돌아도 연속 두 번 안전망이 남는다).
다음 시작에서 실행 중인 판이 `pending.from`(되돌릴 판)이면 그때 비로소 `rolled_back` 으로 확정하고 `pending` 을 지우며 `last_good` 을 적는다(`rolled_back`). 새 판 `pending.to` 가 그대로 켜지면 표식이 남아 있으므로 위의 규칙대로 복구 안내가 다시 뜬다.
읽은 파일이 깨졌으면 `.bak` 으로 옮겨 두고 처음 상태로 시작한다(알려진 한계: 이때 `last_seq` 가 0 으로 돌아가 재전송 방어가 약해진다 — 같은 사용자 권한의 변조는 앱 파일도 바꿀 수 있어 새 권한이 아니다).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .. import capabilities
from . import versions

DIR_NAME = "update"
FILE_NAME = "state.json"
APP_DIR_NAME = "ChanceblogDesktop"                    # `service/context.py` 의 데이터 폴더 이름과 같다(시험이 같음을 지킨다) — 이 모듈은 가볍게 두려고 그쪽을 가져오지 않는다
ENV_DATA_DIR = "CHANCEBLOG_DESKTOP_DATA"
SCHEMA = 1
MAX_STATE_BYTES = 64 * 1024
RECOVERY_AFTER_FAILED_BOOTS = 2                       # 정상 표식 없이 이만큼 시작했으면 다음 시작에서 복구를 안내한다(설계 질문 Q6, RELEASE 7: 연속 2회)
HEALTHY_AFTER_SECONDS = 15                            # 창이 뜬 뒤 이만큼 처리 못 한 예외 없이 지나면 '정상'(Q6)
SHARING_VIOLATIONS = (5, 32)
REPLACE_WAITS = (0.03, 0.06, 0.09, 0.12, 0.15)
STATE_KEYS = frozenset({"schema", "last_seq", "last_seen_utc", "last_check", "pending", "last_good", "notice"})
PENDING_KEYS = frozenset({"from_version", "to_version", "seq", "backup_name", "started", "boot_attempts", "kind"})
CHECK_KEYS = frozenset({"at", "result", "version", "code"})
CHECK_RESULTS = ("UP_TO_DATE", "AVAILABLE", "CHECK_FAILED")
NOTICE_ROLLBACK_LAUNCHED = "rollback_launched"        # 복구가 이전 판 Setup 을 띄웠다 — 되돌려졌다는 확정은 다음 시작이 한다(`pending` 은 그대로 남는다)
NOTICES = ("", "not_applied", "pending_stale", "rolled_back", "rollback_failed", NOTICE_ROLLBACK_LAUNCHED)
KINDS = ("velopack", "inno")
BOOT_NONE = "none"
BOOT_FIRST = "first_boot"
BOOT_RECOVERY = "recovery_offered"
BOOT_NOT_APPLIED = "not_applied"
BOOT_STALE = "stale_cleared"
BOOT_ROLLED_BACK = "rolled_back"                      # 복구가 띄운 이전 판이 실제로 켜졌다 — 표식을 지우고 `rolled_back` 안내로 확정

_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", re.ASCII)
_BACKUP = re.compile(r"full-[0-9]{8}-[0-9]{6}(?:-[0-9]{1,2})?", re.ASCII)
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,60}", re.ASCII)
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


class StateError(Exception):
    """상태 파일을 읽을 수 없다 — `reason` 은 고정 낱말(`unreadable`·`corrupt`·`write`)이고 파일의 글은 담지 않는다."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Pending:
    from_version: str
    to_version: str
    seq: int
    backup_name: str
    started: str
    boot_attempts: int
    kind: str


@dataclass(frozen=True)
class LastCheck:
    at: str
    result: str
    version: str = ""
    code: str = ""


@dataclass(frozen=True)
class State:
    last_seq: int = 0
    last_seen_utc: str = ""
    last_check: object = None                         # LastCheck 또는 None
    pending: object = None                            # Pending 또는 None
    last_good: str = ""
    notice: str = ""


@dataclass(frozen=True)
class BootNote:
    action: str                                       # BOOT_*
    pending: object                                   # 그 시점의 Pending(없으면 None)
    attempts_before: int = 0                          # 시작 전의 횟수(`first_boot`·`recovery_offered` 에서)


# ---- 위치 ----------------------------------------------------------------------------------------------------------------------------------------
def default_data_dir(environ=None):
    """데이터 폴더(`service/context.py` 의 `default_data_dir` 와 같은 규칙: 환경 변수 `CHANCEBLOG_DESKTOP_DATA` > `%LOCALAPPDATA%/ChanceblogDesktop`, 그 밖은 XDG)."""
    env = os.environ if environ is None else environ
    chosen = env.get(ENV_DATA_DIR)
    if chosen:
        return Path(os.path.expanduser(str(chosen)))
    if os.name == "nt":
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def update_folder(data_dir=None, environ=None):
    return Path(data_dir if data_dir is not None else default_data_dir(environ)) / DIR_NAME


def read_current_version(root=None):
    """앱 버전 글(저장소 또는 묶음 폴더 맨 위 `VERSION`) — 읽지 못하거나 모양이 번호가 아니면 빈 글."""
    path = Path(root) / "VERSION" if root is not None else Path(__file__).resolve().parents[3] / "VERSION"
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
    except (OSError, ValueError):
        return ""
    return text if versions.parse_version(text) is not None else ""


# ---- 읽기 ----------------------------------------------------------------------------------------------------------------------------------------
def _int(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _time_text(value, *, allow_empty=False):
    if value == "" and allow_empty:
        return True
    return isinstance(value, str) and _TIME.fullmatch(value) is not None and _parses(value)


def _parses(value):
    try:
        datetime.strptime(value, _STAMP)
    except ValueError:
        return False
    return True


def _pending_from(data):
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) != PENDING_KEYS:
        raise StateError("corrupt")
    if (not isinstance(data["from_version"], str) or versions.parse_version(data["from_version"]) is None or not isinstance(data["to_version"], str) or versions.parse_version(data["to_version"]) is None
            or not _int(data["seq"], 1, 2 ** 53) or not isinstance(data["backup_name"], str) or _BACKUP.fullmatch(data["backup_name"]) is None or not _time_text(data["started"])
            or not _int(data["boot_attempts"], 0, 1000) or data["kind"] not in KINDS):
        raise StateError("corrupt")
    return Pending(data["from_version"], data["to_version"], data["seq"], data["backup_name"], data["started"], data["boot_attempts"], data["kind"])


def _check_from(data):
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) != CHECK_KEYS:
        raise StateError("corrupt")
    version, code = data["version"], data["code"]
    if (not _time_text(data["at"]) or data["result"] not in CHECK_RESULTS or not isinstance(version, str) or (version and versions.parse_version(version) is None)
            or not isinstance(code, str) or (code and _CODE.fullmatch(code) is None)):
        raise StateError("corrupt")
    return LastCheck(data["at"], data["result"], version, code)


def parse_state(raw):
    """바이트 → `State`. 모양이 틀리면 `StateError("corrupt")`."""
    from ..net import parse as netparse
    try:
        data = netparse.read_json(raw)
    except netparse.ParseError:
        raise StateError("corrupt") from None
    if not isinstance(data, dict) or set(data) != STATE_KEYS or data["schema"] != SCHEMA or isinstance(data["schema"], bool):
        raise StateError("corrupt")
    if (not _int(data["last_seq"], 0, 2 ** 53) or not _time_text(data["last_seen_utc"], allow_empty=True) or not isinstance(data["last_good"], str)
            or (data["last_good"] and versions.parse_version(data["last_good"]) is None) or data["notice"] not in NOTICES):
        raise StateError("corrupt")
    return State(data["last_seq"], data["last_seen_utc"], _check_from(data["last_check"]), _pending_from(data["pending"]), data["last_good"], data["notice"])


def read_state(folder):
    """폴더의 `state.json` → `State`. 파일이 없으면 처음 상태. 읽을 수 없으면 `StateError("unreadable")`, 모양이 틀리면 `StateError("corrupt")`."""
    path = Path(folder) / FILE_NAME
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            raise StateError("corrupt")
        raw = path.read_bytes()
    except FileNotFoundError:
        return State()
    except OSError:
        raise StateError("unreadable") from None
    return parse_state(raw)


def keep_bad_copy(folder):
    """깨진 상태 파일을 지우지 않고 `.bak` 으로 옮긴다(처음 상태로 다시 시작하기 전에). 옮겼으면 True."""
    path = Path(folder) / FILE_NAME
    try:
        os.replace(path, path.with_name(FILE_NAME + ".bak"))
    except FileNotFoundError:
        return False
    except OSError:
        raise StateError("write") from None
    return True


def load_state(folder):
    """읽되, 깨진 파일은 `.bak` 으로 옮기고 처음 상태를 돌려준다. 읽을 수 없는(권한 등) 파일은 `StateError("unreadable")` 그대로."""
    try:
        return read_state(folder)
    except StateError as error:
        if error.reason != "corrupt":
            raise
        keep_bad_copy(folder)
        return State()


# ---- 쓰기 ----------------------------------------------------------------------------------------------------------------------------------------
def state_to_dict(state):
    pending = state.pending
    check = state.last_check
    return {
        "schema": SCHEMA, "last_seq": state.last_seq, "last_seen_utc": state.last_seen_utc,
        "last_check": None if check is None else {"at": check.at, "result": check.result, "version": check.version, "code": check.code},
        "pending": None if pending is None else {"from_version": pending.from_version, "to_version": pending.to_version, "seq": pending.seq, "backup_name": pending.backup_name,
                                                 "started": pending.started, "boot_attempts": pending.boot_attempts, "kind": pending.kind},
        "last_good": state.last_good, "notice": state.notice,
    }


def _write_durably(temp, payload):
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def write_state(folder, state):
    """임시 파일에 다 쓰고 디스크까지 내린 뒤 이름을 바꿔 넣는다(윈도 공유 위반은 짧게 다시). 실패하면 임시 파일을 지우고 `StateError("write")`."""
    path = Path(folder) / FILE_NAME
    payload = (json.dumps(state_to_dict(state), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp = path.with_name(f"{FILE_NAME}.{os.getpid()}-{secrets.token_hex(4)}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_durably(temp, payload)
        for wait in (*REPLACE_WAITS, None):
            try:
                os.replace(temp, path)
                break
            except PermissionError as error:
                if wait is None or getattr(error, "winerror", None) not in SHARING_VIOLATIONS:
                    raise
                time.sleep(wait)
    except BaseException as error:          # noqa: BLE001 - 어떤 끊김(Ctrl+C 포함)에서도 임시 파일을 치우고 원래 예외를 다시 올린다 — 옛 파일은 그대로다
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(error, OSError):
            raise StateError("write") from None
        raise


def utc_text(moment):
    return moment.astimezone(timezone.utc).strftime(_STAMP)


# ---- 부팅 후크 -------------------------------------------------------------------------------------------------------------------------------------
def _note_boot(folder, version):
    state = read_state(folder)
    pending = state.pending
    if pending is None:
        return BootNote(BOOT_NONE, None)
    if versions.compare(version, pending.to_version) == 0:
        if pending.boot_attempts >= RECOVERY_AFTER_FAILED_BOOTS:
            return BootNote(BOOT_RECOVERY, pending, pending.boot_attempts)
        bumped = replace(pending, boot_attempts=pending.boot_attempts + 1)
        write_state(folder, replace(state, pending=bumped))
        return BootNote(BOOT_FIRST, bumped, pending.boot_attempts)
    if versions.compare(version, pending.from_version) == 0:
        if state.notice == NOTICE_ROLLBACK_LAUNCHED:
            write_state(folder, replace(state, pending=None, notice="rolled_back", last_good=pending.from_version))
            return BootNote(BOOT_ROLLED_BACK, None)
        write_state(folder, replace(state, pending=None, notice="not_applied"))
        return BootNote(BOOT_NOT_APPLIED, None)
    write_state(folder, replace(state, pending=None, notice="pending_stale"))
    return BootNote(BOOT_STALE, None)


def note_boot(*, environ=None, version=None, data_dir=None, folder=None):
    """앱이 켜질 때 한 번(가장 먼저) — 위 머리글. 꺼진 채: `UPDATE_APPLY` 가 꺼져 있으면 파일을 읽지도 쓰지도 않고 None. 어떤 실패도 예외로 번지지 않는다(None)."""
    if not capabilities.update_apply_enabled():
        return None
    try:
        current = version if version is not None else read_current_version()
        if versions.parse_version(current) is None:
            return None
        return _note_boot(Path(folder) if folder is not None else update_folder(data_dir, environ), current)
    except Exception:          # noqa: BLE001 - 앱을 못 켜게 만들지 않는다: 읽기·쓰기·모양 어떤 실패든 조용히 넘어간다(다음 시작이 같은 일을 다시 한다)
        return None


__all__ = ["BOOT_FIRST", "BOOT_NONE", "BOOT_NOT_APPLIED", "BOOT_RECOVERY", "BOOT_ROLLED_BACK", "BOOT_STALE", "BootNote", "DIR_NAME", "FILE_NAME", "HEALTHY_AFTER_SECONDS", "KINDS", "LastCheck", "NOTICES",
           "NOTICE_ROLLBACK_LAUNCHED", "Pending",
           "RECOVERY_AFTER_FAILED_BOOTS", "State", "StateError", "default_data_dir", "keep_bad_copy", "load_state", "note_boot", "parse_state", "read_current_version", "read_state", "state_to_dict",
           "update_folder", "utc_text", "write_state"]
