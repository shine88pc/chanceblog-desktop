"""블로그 관리 화면의 실제 공급자(P4b) — 서비스(`service/blog_profiles.py`)를 화면이 아는 모양(`ui/core/blogs.py`)으로 맞추는 얇은 어댑터다. **이 앱에서 처음으로 파일에 쓰는 어댑터**이고, 쓰는 길은 이 파일의 세 메서드(`save_blog`·`clone_blog`·`clear_blog`)가
부르는 서비스 함수 셋(`save_slot`·`clone_slot`·`clear_slot`)뿐이다 — 화면 코드(`ui/qt`·`ui/core`)에는 파일을 쓰는 호출이 없다(시험이 소스를 훑는다). 홈·설정 어댑터(`ui/adapters.py`)는 그대로 읽기만 한다.

읽기(`load_blogs`)는 서비스의 `read_snapshot` 하나 — 파일도 폴더도 만들지 않는다. 쓰기 전에는 늘 먼저 읽어 본다(읽을 수 없거나 모양이 틀린 파일 위에는 쓰지 않고 쉬운 안내로 멈춘다 — 파일은 고치거나 지우지 않는다).
서비스 오류(`AppError`)는 **종류**(낡은 판·잠금·칸 값·디스크·쓰기 실패·읽을 수 없음)로만 나눠 화면에 알린다 — 화면 문장은 `ui/core/text.py` 의 정해진 말이고 오류의 세부(경로·예외 이름)는 화면에 나가지 않는다.
키·자격 증명은 읽지도 쓰지도 않는다. 이 모듈은 PySide6 를 모른다.
"""
from __future__ import annotations

from ..errors import AppError
from ..service import blog_profiles as service
from ..service.context import make_context
from .adapters import is_folder
from .core.blogs import BlogFailure, BlogsData, BlogsOutcome, BlogsProvider, slot_from_profile
from .core.jobs import JobCancelled
from .core.text import T

KIND_OF_CODE = {"STORE_CONFLICT": "conflict", "TOPIC_STORE_LOCKED": "busy", "DISK_FULL": "disk", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io", "FILE_PATH_TOO_LONG": "io", "DATA_DIR_UNSAFE": "io",
                "TOPIC_FILE_INVALID": "corrupt", "CONTENT_INVALID": "invalid"}      # 서비스 오류 코드 → 화면이 다르게 다룰 종류(나머지는 `other`). 읽다가 나온 `CONTENT_INVALID` 는 파일의 칸이 틀린 것이라 `corrupt`


def failure_of(error, *, reading=False):
    """서비스 오류 → 화면용 실패(종류 + 진단 코드). 문장은 종류별 정해진 말이라 오류의 세부·경로·입력한 값이 화면에 나가지 않는다."""
    kind = KIND_OF_CODE.get(error.code, "other")
    if error.code == "CONTENT_INVALID" and reading:
        kind = "corrupt"                                                                  # 읽다가 값이 틀리다고 나온 것 = 파일의 칸이 틀림
    return BlogFailure(T["blogs_error_desc"] if reading else T["blogs_fail_" + kind], code=error.code, kind=kind)


def data_of(snapshot):
    return BlogsData(tuple(slot_from_profile(profile) for profile in snapshot.profiles), snapshot.version, snapshot.state, False)


class ServiceBlogsProvider(BlogsProvider):
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context

    def _context(self):
        if self._data_dir is not None and not is_folder(self._data_dir):                  # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(홈·설정과 같다)
            raise BlogFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", kind="io")
        return self._factory(data_dir=self._data_dir)

    def load_blogs(self, progress, cancelled):
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
        except service.ProfileProblems as error:
            raise BlogFailure(T["blogs_fail_invalid"], code=error.code, kind="invalid", problems=error.problems) from None
        except AppError as error:
            raise failure_of(error) from None
        return BlogsOutcome(saved.kind, data_of(saved.snapshot), saved.changed)

    def save_blog(self, key, fields, version, progress, cancelled):
        return self._write(lambda ctx: service.save_slot(ctx, key, fields, expected_version=version))

    def clone_blog(self, source, target, version, progress, cancelled):
        return self._write(lambda ctx: service.clone_slot(ctx, source, target, expected_version=version))

    def clear_blog(self, key, version, progress, cancelled):
        return self._write(lambda ctx: service.clear_slot(ctx, key, confirmed=True, expected_version=version))
