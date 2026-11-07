"""Seed 관리 화면의 실제 공급자 — 서비스(`service/seed_manage.py`)를 화면이 아는 모양(`ui/core/seeds.py`)으로 맞추는 얇은 어댑터다. 쓰는 길은 이 파일의 다섯 메서드(`set_state`·`set_states`·`edit_seed`·`create_seed`·`apply_import`)가
부르는 서비스 함수뿐이다 — 화면 코드(`ui/qt`·`ui/core`)에는 파일을 쓰는 호출이 없다(시험이 소스를 훑는다). 홈·설정·블로그 관리 어댑터는 그대로다.

읽기(`load_seeds`)는 서비스의 `read_snapshot` 하나, 제안 파일 미리 보기(`preview_import`)는 서비스의 `preview_import` 하나 — 둘 다 파일도 폴더도 만들지 않는다. 쓰기 전에는 늘 먼저 읽어 본다(읽을 수 없거나 모양이 틀린 파일 위에는 쓰지 않고
쉬운 안내로 멈춘다 — 파일은 고치거나 지우지 않는다). **여러 개를 한꺼번에 바꾸는 서비스 호출에는 확인 표시가 진짜 `True` 로, 확인한 개수는 번호 수로 간다**(확인창이 먼저 떴다는 것은 화면 상태가 지킨다).
서비스 오류(`AppError`)는 **종류**(낡은 판·잠금·칸 값·디스크·쓰기 실패·읽을 수 없음)로만 나눠 화면에 알린다 — 화면 문장은 `ui/core/text.py` 의 정해진 말이고 오류의 세부(경로·예외 이름)는 화면에 나가지 않는다.
키·자격 증명은 읽지도 쓰지도 않는다. 이 모듈은 PySide6 를 모른다.
"""
from __future__ import annotations

from ..errors import AppError
from ..service import seed_manage as service
from ..service.context import make_context
from .adapters import is_folder
from .core.jobs import JobCancelled
from .core.seeds import ImportInfo, SeedFailure, SeedsData, SeedsOutcome, SeedsProvider
from .core.text import T

KIND_OF_CODE = {"STORE_CONFLICT": "conflict", "TOPIC_STORE_LOCKED": "busy", "DISK_FULL": "disk", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io", "FILE_PATH_TOO_LONG": "io", "DATA_DIR_UNSAFE": "io",
                "TOPIC_FILE_INVALID": "corrupt", "CONTENT_INVALID": "invalid", "CONFIRMATION_REQUIRED": "invalid"}      # 서비스 오류 코드 → 화면이 다르게 다룰 종류(나머지는 `other`). 읽다가 나온 `CONTENT_INVALID` 는 파일의 칸이 틀린 것이라 `corrupt`


def failure_of(error, *, reading=False):
    """서비스 오류 → 화면용 실패(종류 + 진단 코드). 문장은 종류별 정해진 말이라 오류의 세부·경로·입력한 값이 화면에 나가지 않는다."""
    kind = KIND_OF_CODE.get(error.code, "other")
    if error.code == "CONTENT_INVALID" and reading:
        kind = "corrupt"                                                                  # 읽다가 값이 틀리다고 나온 것 = 파일의 칸이 틀림
    return SeedFailure(T["seeds_error_desc"] if reading else T["seeds_fail_" + kind], code=error.code, kind=kind)


def data_of(snapshot):
    return SeedsData(tuple(snapshot.seeds), snapshot.version, snapshot.state, snapshot.today, tuple((item.seed_id, item.idle_days) for item in snapshot.idle), tuple(snapshot.generation), False)


def info_of(preview):
    result = preview.result
    return ImportInfo(result.total, len(result.new), result.existing, tuple(result.skipped), tuple(result.rejected), tuple(result.notes), tuple(result.per_channel), bool(result.kept_copy), preview.version, tuple(result.new), False)


class ServiceSeedsProvider(SeedsProvider):
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context

    def _context(self):
        if self._data_dir is not None and not is_folder(self._data_dir):                  # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(홈·설정·블로그 관리와 같다)
            raise SeedFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", kind="io")
        return self._factory(data_dir=self._data_dir)

    def load_seeds(self, progress, cancelled):
        try:
            snapshot = service.read_snapshot(self._context())
        except AppError as error:
            raise failure_of(error, reading=True) from None
        if cancelled():
            raise JobCancelled()
        return data_of(snapshot)

    def _write(self, call):
        """쓰기 하나 — 먼저 지금 파일을 읽어 보고(읽을 수 없는 파일 위에는 쓰지 않는다) 서비스 함수를 부른다. 서비스 함수 하나는 중간에 끊을 수 없어(취소 신호를 보지 않는다) 끝까지 간다."""
        try:
            ctx = self._context()
            service.read_snapshot(ctx)
        except AppError as error:
            raise failure_of(error, reading=True) from None
        try:
            saved = call(ctx)
        except service.SeedProblems as error:
            raise SeedFailure(T["seeds_fail_invalid"], code=error.code, kind="invalid", problems=error.problems) from None
        except AppError as error:
            raise failure_of(error) from None
        return SeedsOutcome(saved.kind, data_of(saved.snapshot), saved.changed)

    def set_state(self, seed_id, state, version, progress, cancelled):
        return self._write(lambda ctx: service.set_state(ctx, seed_id, state, expected_version=version))

    def set_states(self, seed_ids, state, version, progress, cancelled):
        ids = tuple(seed_ids)
        return self._write(lambda ctx: service.set_states(ctx, ids, state, confirmed=True, expected_count=len(ids), expected_version=version))

    def edit_seed(self, seed_id, fields, version, progress, cancelled):
        return self._write(lambda ctx: service.edit_seed(ctx, seed_id, fields, expected_version=version))

    def create_seed(self, fields, version, progress, cancelled):
        return self._write(lambda ctx: service.create_seed(ctx, fields, expected_version=version))

    def preview_import(self, path, progress, cancelled):
        """제안 파일 미리 보기 — 읽기뿐이다(파일도 폴더도 만들지 않는다). 파일을 읽을 수 없거나 제안 파일 모양이 아니면 쉬운 안내로 멈춘다."""
        try:
            preview = service.preview_import(self._context(), path)
        except AppError as error:
            raise failure_of(error) from None
        if cancelled():
            raise JobCancelled()
        return SeedsOutcome("preview", None, (), info_of(preview))

    def apply_import(self, info, progress, cancelled):
        return self._write(lambda ctx: service.apply_import(ctx, info.handle, expected_version=info.version))
