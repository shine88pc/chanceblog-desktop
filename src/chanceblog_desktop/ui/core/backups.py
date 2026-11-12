"""백업·복원 카드(설정 화면)가 아는 값과 공급자의 모양 + 가짜 공급자 — 화면은 이 모양만 안다. 실제 서비스(`service/backup_flow.py`)는 얇은 어댑터(`ui/backups_adapter.py`)가 같은 모양으로 맞춘다. PySide6 도 파일도 서비스도 모른다(BACKUPUI, D-391).

이 모양의 어떤 값(`BackupRowData`·`BackupResult`·`BackupFailure`)에도 키·키의 일부·글 내용을 담는 칸이 없다 — 칸은 이름·시각·크기·개수·상태 이름·고정 이유 이름뿐이고 키 모양이 발견된 위치도 '어느 칸·몇 번째 줄·유형' 글(서비스가 만든 고정 이름)뿐이다.
가짜 공급자(`FakeBackupsProvider` — `--sample`·시험·사진)는 **메모리에서만** 일한다: 백업을 만들어도 되돌려도 이 PC 에 아무것도 남지 않고, 이름·시각·개수는 모두 지어낸 예시다.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

from .jobs import JobCancelled, JobFailure
from .text import T

KINDS_OF_FAILURE = ("blocked", "nothing", "busy", "invalid", "newer", "disk", "io", "restore", "other")
ROW_KINDS = ("backup", "safety")                                  # 백업 · 복원 직전 안전 사본
ROW_STATUSES = ("complete", "partial", "broken")                  # 완료 · 부분 · 깨짐(복원할 수 없는 폴더)
FILE_STATES = ("saved", "missing", "skipped", "restored", "kept", "failed")
SAMPLE_LOCATION = "예시 폴더(이 PC 에는 만들어지지 않아요)"
FILE_ORDER = ("chanceblog.db", "topic_engine.db", "channel_profiles.json", "seeds.json", "calendar.json", "settings.json")
FILE_LABELS = {"chanceblog.db": "글 보관함", "topic_engine.db": "주제 보관함", "channel_profiles.json": "채널 프로필", "seeds.json": "Seed", "calendar.json": "캘린더", "settings.json": "설정"}      # 예시 공급자가 쓰는 이름 — 실제 이름은 서비스가 준다


class BackupFailure(JobFailure):
    """백업·복원의 실패 — 쉬운 문장(`user_message`)과 진단용 코드(`code`), 화면이 다르게 다룰 종류(`kind`)다. 문장은 종류별로 정해진 말이라 서비스 오류의 세부·경로·입력한 값이 들어가지 않는다.
    `summary` 는 키 모양이 발견된 **위치와 유형**을 풀어 쓴 줄들(`blocked` 일 때 — 글 내용 없음), `notes` 는 되돌리지 못한 것처럼 덧붙일 말들이다."""

    def __init__(self, user_message, code="", *, kind="other", summary=(), notes=(), reason="", retryable=True):
        super().__init__(user_message, code, retryable)
        self.kind = kind if kind in KINDS_OF_FAILURE else "other"
        self.summary = tuple(str(line) for line in summary)
        self.notes = tuple(str(line) for line in notes)
        self.reason = str(reason)                                  # 복원 중 문제의 이유 이름(`disk`·`io`·`corrupt`·`busy`·`other`) — 문장은 정해진 말이다


def failure_text(kind):
    """실패 종류 → 정해진 쉬운 문장(입력한 글·경로 없음)."""
    return T.get("backup_fail_" + kind, T["backup_fail_other"])


def make_failure(kind, code="", *, summary=(), notes=(), reason=""):
    return BackupFailure(failure_text(kind), code, kind=kind, summary=summary, notes=notes, reason=reason)


@dataclass(frozen=True)
class FileInfo:
    """백업 안의 파일 하나(또는 복원이 바꾼 파일 하나)의 상태 줄."""
    name: str
    label: str
    state: str                        # `FILE_STATES`
    size: int = 0
    items: tuple = ()                 # ((칸 이름, 개수), …) — `projects`·`drafts`·`count` 같은 고정 이름
    reason: str = ""                  # 못 담았거나 못 바꾼 이유의 오류 코드


@dataclass(frozen=True)
class BackupRowData:
    name: str                         # 폴더 이름 — 누르는 줄을 가리키는 열쇠이고 글자로도 보이지 않는다(보이는 이름은 시각)
    kind: str                         # `ROW_KINDS`
    created_at: str                   # UTC `YYYY-MM-DDTHH:MM:SSZ` — 모르면 ''
    status: str                       # `ROW_STATUSES`
    size: int = 0
    files: tuple = ()                 # FileInfo
    problem: str = ""                 # status == broken 일 때 이유 이름(`manifest`·`files`)
    app_version: str = ""


@dataclass(frozen=True)
class InterruptedData:
    """중간에 멈춘 복원의 흔적(D-463) — 이름과 시각뿐이다(글 내용·경로 없음). 화면이 쉬운 안내와 `안전 사본으로 되돌리기` 를 보여 준다."""
    started_at: str = ""              # 복원을 시작한 때(UTC `YYYY-MM-DDTHH:MM:SSZ`) — 모르면 ''
    backup: str = ""                  # 되돌리던 백업 폴더 이름('' 이면 모른다)
    safety: str = ""                  # 복원 직전에 남긴 안전 사본 폴더 이름('' 이면 없다)
    can_revert: bool = False          # 그 안전 사본이 지금 있어 되돌릴 수 있는가


@dataclass(frozen=True)
class BackupsData:
    rows: tuple = ()                  # BackupRowData — 새 것이 먼저
    location: str = ""                # 백업 폴더 경로(글자로만 보인다 — 폴더 열기 단추는 없다)
    keep: int = 10
    sample: bool = False
    interrupted: object = None        # `InterruptedData` — 복원이 중간에 멈춘 흔적이 있을 때만(없으면 None)


@dataclass(frozen=True)
class BackupResult:
    """백업을 만들었거나 되돌린 결과 — 어느 일이 어떻게(완료·부분) 됐는지와 파일 줄·알림뿐이다."""
    action: str                       # created · restored
    status: str                       # complete · partial
    name: str = ""                    # 만든 백업 / 되돌린 백업의 폴더 이름
    created_at: str = ""              # 만든 백업의 만든 때(UTC `YYYY-MM-DDTHH:MM:SSZ`) — 목록을 다시 읽기 전에도 결과 안내에 시각을 쓰려고 담는다(되돌린 결과는 '')
    safety: str = ""                  # 되돌리기 직전 안전 사본의 폴더 이름('' 이면 남길 것이 없었다)
    files: tuple = ()                 # FileInfo
    notes: tuple = ()                 # 복원 뒤 알릴 말들(고정 문장)


class BackupsProvider:
    """읽기만 하는 공급자 모양 — `load_backups` 는 작업 스레드에서 불린다. 쓰는 공급자(`BackupsWriter`)만 카드에 단추가 생긴다."""
    sample = False

    def load_backups(self, progress, cancelled):
        raise NotImplementedError


class BackupsWriter:
    """공급자에 더하는 **쓰기** 메서드 — 모두 작업 스레드에서 불리고 사용자가 단추를 눌렀을 때만 불린다(읽기 `load_backups` 는 파일을 바꾸지 않는다). 실패는 `BackupFailure`."""
    can_write = True

    def create_backup(self, progress, cancelled):
        raise NotImplementedError

    def restore_backup(self, name, progress, cancelled):
        raise NotImplementedError

    def revert_interrupted(self, progress, cancelled):
        """중간에 멈춘 복원을 안전 사본으로 되돌린다 — 결과는 복원과 같은 `BackupResult`."""
        raise NotImplementedError


def _pause(seconds, cancelled):
    end = time.monotonic() + seconds
    while seconds and time.monotonic() < end:
        if cancelled():
            raise JobCancelled()
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


def _line(name, state, *items, size=0, reason=""):
    return FileInfo(name, FILE_LABELS[name], state, size, tuple(items), reason)


def sample_files(partial=False):
    """예시 백업 하나의 파일 줄들 — 개수·크기는 지어낸 값이다."""
    lines = [_line("chanceblog.db", "saved", ("projects", 12), ("drafts", 3), ("candidates", 5), ("revisions", 20), size=3_400_000),
             _line("topic_engine.db", "saved", ("candidates", 40), size=1_200_000), _line("channel_profiles.json", "saved", ("count", 5), size=9_000), _line("seeds.json", "saved", ("count", 130), size=60_000),
             _line("calendar.json", "saved", ("count", 6), size=2_000), _line("settings.json", "saved", ("profiles", 2), ("repo", 0), size=1_200)]
    if partial:
        lines[3] = _line("seeds.json", "skipped", reason="TOPIC_FILE_INVALID")
    return tuple(lines)


def sample_rows(scenario="normal"):
    """예시 목록 — 시각은 고정이다(같은 입력은 같은 모양)."""
    if scenario == "empty":
        return ()
    rows = [BackupRowData("full-20261110-210500", "backup", "2026-11-10T12:05:00Z", "complete", 4_670_000, sample_files()),
            BackupRowData("before-20261110-100300", "safety", "2026-11-10T01:03:00Z", "complete", 4_100_000, sample_files()),
            BackupRowData("full-20261108-083000", "backup", "2026-11-08T08:30:00Z", "partial", 4_050_000, sample_files(partial=True))]
    if scenario == "broken":
        rows.append(BackupRowData("full-20261101-120000", "backup", "2026-11-01T03:00:00Z", "broken", 0, (), "manifest"))
    return tuple(rows)


class FakeBackupsProvider(BackupsProvider, BackupsWriter):
    """메모리에서만 일하는 가짜 공급자 — 백업을 만들고 되돌리는 일이 모두 메모리 안에서만 바뀐다(파일·서비스를 부르지 않는다). 규칙은 서비스와 같다(시험이 같은 일을 둘에 해 보고 견준다).
    `scenario`: `normal`·`empty`·`error`(읽기 실패)·`broken`(깨진 백업이 하나 있음). `create_failure`·`restore_failure` 는 일이 일으킬 실패 종류, `delay` 는 일마다 기다리는 초(단추가 꺼진 모습을 볼 때)다."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0, *, create_failure="", restore_failure="", create_status="complete"):
        self.scenario, self.delay = scenario, delay
        self.create_failure, self.restore_failure, self.create_status = create_failure, restore_failure, create_status
        self.writes = []                                         # 부른 쓰기 이름들(시험이 본다)
        self._rows = None
        self._lock = threading.Lock()
        self._counter = 0
        self._interrupted = InterruptedData("2026-11-10T12:20:00Z", "full-20261110-210500", "before-20261110-100300", True) if scenario == "interrupted" else None      # 멈춘 복원 예시(`interrupted` 장면)

    def _ensure(self):
        if self._rows is None:
            self._rows = list(sample_rows(self.scenario))

    def load_backups(self, progress, cancelled):
        _pause(self.delay, cancelled)
        if cancelled():
            raise JobCancelled()
        if self.scenario == "error":
            raise JobFailure(T["backup_load_failed"], "SAMPLE_ERROR")
        with self._lock:
            self._ensure()
            return BackupsData(tuple(self._rows), SAMPLE_LOCATION, 10, True, self._interrupted)

    def create_backup(self, progress, cancelled):
        self.writes.append("create")
        for fraction, text in ((0.1, T["backup_step_start"]), (0.5, T["backup_step_save"]), (0.9, T["backup_step_check"])):
            _pause(self.delay / 3, cancelled)
            if cancelled():
                raise JobCancelled()
            progress(fraction, text)
        if self.create_failure:
            raise make_failure(self.create_failure, "SAMPLE_FAILURE")
        with self._lock:
            self._ensure()
            self._counter += 1
            name = f"full-20261111-1200{self._counter:02d}"
            files = sample_files(partial=self.create_status == "partial")
            created = f"2026-11-11T03:00:{self._counter:02d}Z"
            self._rows.insert(0, BackupRowData(name, "backup", created, self.create_status, sum(item.size for item in files), files))
        return BackupResult("created", self.create_status, name, created, files=files)

    def restore_backup(self, name, progress, cancelled):
        self.writes.append("restore:" + name)
        return self._restore(name, progress, cancelled)

    def revert_interrupted(self, progress, cancelled):
        with self._lock:
            self._ensure()
            pending = self._interrupted
        if pending is None or not pending.can_revert:
            raise make_failure("invalid", "SAMPLE_INVALID")
        self.writes.append("revert")
        return self._restore(pending.safety, progress, cancelled)

    def _restore(self, name, progress, cancelled):
        for fraction, text in ((0.2, T["backup_step_keep"]), (0.6, T["backup_step_change"]), (0.9, T["backup_step_read"])):
            _pause(self.delay / 3, cancelled)
            if cancelled():
                raise JobCancelled()
            progress(fraction, text)
        with self._lock:
            self._ensure()
            row = next((item for item in self._rows if item.name == name), None)
            if row is None or row.status == "broken":
                raise make_failure("invalid", "SAMPLE_INVALID")
            if self.restore_failure:
                raise make_failure(self.restore_failure, "SAMPLE_FAILURE", notes=(T["backup_fail_notes_sample"],) if self.restore_failure == "restore" else ())
            self._counter += 1
            safety = f"before-20261111-1300{self._counter:02d}"
            self._rows.insert(0, BackupRowData(safety, "safety", f"2026-11-11T04:00:{self._counter:02d}Z", "complete", row.size, sample_files()))
            self._interrupted = None                                 # 복원이 끝나면 멈춘 흔적은 사라진다(서비스가 표지를 지우는 것과 같다)
        files = tuple(replace(item, state="restored") if item.state == "saved" else replace(item, state="kept") for item in row.files)
        return BackupResult("restored", "complete" if row.status == "complete" else "partial", name, "", safety, files, (T["backup_note_keys"],))


__all__ = ["BackupFailure", "BackupResult", "BackupRowData", "BackupsData", "BackupsProvider", "BackupsWriter", "FakeBackupsProvider", "FileInfo", "InterruptedData", "failure_text", "make_failure", "sample_files", "sample_rows"]
