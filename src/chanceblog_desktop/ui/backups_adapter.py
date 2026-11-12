"""백업·복원 카드의 실제 공급자(BACKUPUI) — 서비스(`service/backup_flow.py`)를 화면이 아는 모양(`ui/core/backups.py`)으로 맞추는 얇은 어댑터다. **이 앱에서 전체 백업을 만들고 되돌리는 유일한 어댑터**이고,
쓰는 길은 이 파일의 두 메서드(`create_backup`·`restore_backup`)가 부르는 서비스 함수(`create_full_backup`·`restore_full_backup`)뿐이다 — 화면 코드(`ui/qt`·`ui/core`)에는 파일을 쓰거나 지우거나 하위 프로세스를 부르는 호출이 없다(시험이 소스를 훑는다).
읽기(`load_backups`)는 목록만 읽는다(`list_full_backups` — 폴더도 파일도 만들지 않는다).

**복원의 확인**: 서비스의 `restore_full_backup` 은 `confirmed=True` 가 있어야 하는데 이 어댑터가 그것을 넘기는 것은 컨트롤러(`BackupController.start_restore`)가 **확인창에서 '복원하기' 를 누른 뒤에만** 이 메서드를 부르기 때문이다(`confirmed is True` 가 아니면 컨트롤러가 일을 시작하지 않는다).
**오류 문구**: 서비스 오류(`AppError`)는 **종류**(키 모양 발견·담을 것 없음·다른 작업 중·백업이 깨짐·더 새로운 프로그램·저장 공간·쓰기 실패·복원 중 문제)로만 바꿔 화면에 알린다 — 화면 문장은 `ui/core/backup_text.py` 의 정해진 말이고 오류의 세부·경로·입력한 값은 화면에 나가지 않는다.
키 모양이 발견된 위치는 서비스가 만든 '어느 칸·몇 번째 줄·유형' 글(`FlowError.summary`)만 그대로 싣는다(글 내용이 없다). 이 모듈은 PySide6 를 모른다.
"""
from __future__ import annotations

from ..errors import AppError
from ..service import backup_flow as flow
from ..service.context import make_context
from .adapters import ServiceFailure, is_folder, settings_failure
from .core.backups import BackupFailure, BackupResult, BackupRowData, BackupsData, BackupsProvider, BackupsWriter, FileInfo, InterruptedData, make_failure
from .core.jobs import JobCancelled
from .core.text import T

KIND_OF_CODE = {"FULL_BACKUP_BLOCKED": "blocked", "CONTENT_NOT_FOUND": "nothing", "BACKUP_IN_PROGRESS": "busy", "FULL_BACKUP_INVALID": "invalid", "STORE_VERSION_UNSUPPORTED": "newer",
                "TOPIC_STORE_VERSION_UNSUPPORTED": "newer", "STORE_LOCKED": "busy", "TOPIC_STORE_LOCKED": "busy", "DISK_FULL": "disk", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io",
                "FILE_PATH_TOO_LONG": "io", "DATA_DIR_UNSAFE": "io", "RESTORE_FAILED": "restore"}      # 서비스 오류 코드 → 화면이 다르게 다룰 종류(나머지는 `other`)
RESTORE_REASONS = ("disk", "io", "corrupt", "busy", "other")                                   # 복원 중 문제의 이유 이름 — 문장은 `ui/core/backup_text.py` 의 `backup_restore_reason_…`


def file_info(line):
    return FileInfo(line.name, line.label, line.state, line.size, tuple(line.items), line.reason)


def row_data(row):
    return BackupRowData(row.name, row.kind, row.created_at, row.status, row.size, tuple(file_info(line) for line in row.files), row.problem, row.app_version)


def interrupted_data(pending):
    """서비스의 멈춘 복원 흔적 → 화면이 아는 모양(이름·시각·되돌릴 수 있는가뿐)."""
    return None if pending is None else InterruptedData(pending.started_at, pending.backup, pending.safety, bool(pending.can_revert))


def failure_of(error):
    """서비스 오류 → 화면용 실패(종류 + 진단 코드 + 키 모양 위치 줄 + 되돌리지 못한 것). 문장은 종류별 정해진 말이다."""
    reason = getattr(error, "reason", "")
    kind = KIND_OF_CODE.get(error.code, "other")
    if error.code == "BACKUP_FAILED" and reason == "nothing":
        kind = "nothing"
    summary = tuple(line for line in getattr(error, "summary", "").split("\n") if line) if kind == "blocked" else ()
    notes = tuple(getattr(error, "notes", ())) if kind == "restore" else ()
    return make_failure(kind, error.code, summary=summary, notes=notes, reason=reason if kind == "restore" and reason in RESTORE_REASONS else "")


class ServiceBackupsProvider(BackupsProvider, BackupsWriter):
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context

    def _step(self, progress, cancelled):
        """서비스가 단계마다 부르는 함수 — 취소 신호를 먼저 보고(취소하면 임시 폴더를 치우고 멈춘다), 진행을 알린다."""
        def step(fraction, text=""):
            if cancelled():
                raise JobCancelled()
            progress(fraction, text)
        return step

    def _context(self):
        return self._factory(data_dir=self._data_dir)

    def _run(self, work):
        """서비스 함수 하나 — 서비스 오류를 종류별 `BackupFailure` 로 바꾼다. 실패 객체는 `except` 밖에서 낸다(앞의 오류가 `__context__` 로 따라붙어 호출 흔적이 남지 않게) — 서비스 오류의 `__traceback__` 도 끊는다."""
        failure = None
        try:
            return work()
        except JobCancelled:
            raise
        except AppError as error:
            failure = failure_of(error)
            error.__traceback__ = None
        except Exception as error:                                                    # 예상하지 못한 오류 — 쉬운 문장 + 예외 이름(진단용)만, 내용은 싣지 않는다
            failure = make_failure("other", type(error).__name__)
            error.__traceback__ = None
        raise failure

    # ---- 읽기 ----
    def load_backups(self, progress, cancelled):
        if self._data_dir is not None and not is_folder(self._data_dir):               # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(홈·설정과 같다)
            raise ServiceFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", retryable=True)
        try:
            ctx = self._context()
            listing = flow.list_full_backups(ctx)
        except AppError as error:
            raise settings_failure(error) from None
        if cancelled():
            raise JobCancelled()
        return BackupsData(tuple(row_data(row) for row in listing.rows), listing.location, listing.keep, False, interrupted_data(listing.interrupted))

    # ---- 쓰기(사용자가 눌렀을 때만) ----
    def create_backup(self, progress, cancelled):
        if cancelled():
            raise JobCancelled()
        outcome = self._run(lambda: flow.create_full_backup(self._context(), step=self._step(progress, cancelled)))
        return BackupResult("created", outcome.row.status, outcome.row.name, outcome.row.created_at, files=tuple(file_info(line) for line in outcome.row.files), notes=tuple(outcome.notes))

    def restore_backup(self, name, progress, cancelled):
        if cancelled():
            raise JobCancelled()
        outcome = self._run(lambda: flow.restore_full_backup(self._context(), name, confirmed=True, step=self._step(progress, cancelled)))      # 확인은 컨트롤러가 이미 받았다(확인창에서 '복원하기')
        return BackupResult("restored", outcome.status, outcome.source, "", outcome.safety, tuple(file_info(line) for line in outcome.files), tuple(outcome.notes))

    def revert_interrupted(self, progress, cancelled):
        if cancelled():
            raise JobCancelled()
        outcome = self._run(lambda: flow.revert_interrupted_restore(self._context(), confirmed=True, step=self._step(progress, cancelled)))      # 확인은 컨트롤러가 이미 받았다(확인창에서 '되돌리기')
        return BackupResult("restored", outcome.status, outcome.source, "", outcome.safety, tuple(file_info(line) for line in outcome.files), tuple(outcome.notes))
