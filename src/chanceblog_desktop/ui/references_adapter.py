"""'참고 글 보관함'의 실제 공급자(결정 D-490) — 서비스(`service/references.py`)를 화면이 아는 모양(`ui/core/references_view.py`)으로 맞추는 얇은 어댑터다. **이 앱에서 참고 글 보관함을 만들고 고치고 지우는 유일한 어댑터**이고,
쓰는 길은 이 파일의 메서드(`add`·`add_file`·`save`·`delete`)가 부르는 서비스 함수뿐이다 — 화면 코드(`ui/qt`·`ui/core`)에는 파일을 쓰거나 지우거나 하위 프로세스를 부르는 호출이 없다(시험이 소스를 훑는다).
지우기의 확인(`confirmed=True`)을 넘기는 것은 화면 규칙(`ReferenceLibrary.advance_delete`)이 **두 번째 확인을 받은 뒤에만** 이 메서드를 부르기 때문이다.

**오류 문구**: 서비스 오류(`AppError`)는 고정 문장(`rendered().message`)만 `ReferencesRefusal` 로 바꿔 화면에 알린다 — 오류의 세부·경로·글은 화면에 나가지 않는다. `AppError` 를 잡으면 `error.__traceback__ = None` 으로
호출 흔적(글·경로를 쥔 지역 변수)을 끊고 `except` 밖에서 새로 낸다(앞 오류가 따라붙지 않게). 글은 이 어댑터의 지역 변수로만 있다가 서비스로 넘어가면 버려진다. 이 모듈은 PySide6 를 모른다.
"""
from __future__ import annotations

from ..errors import AppError
from ..service import references as service
from ..service.context import make_context
from .core.references_view import OpenedRef, RefListing, RefRow, ReferencesProvider, ReferencesRefusal
from .core.text import T


SERVICE_CODES = frozenset({"CONTENT_INVALID", "CONTENT_NOT_FOUND", "CONFIRMATION_REQUIRED", "FILE_WRITE_FAILED", "DISK_FULL"})      # 서비스(`service/references.py`)가 내는 오류 — 문장이 고정이라 그대로 알린다
FOLDER_CODES = frozenset({"DATA_DIR_UNSAFE", "FILE_PATH_TOO_LONG"})                                                                 # 데이터 폴더를 정하지 못하는 오류 — 문구에 폴더 경로가 들어 있어 고정 안내문으로 바꾼다


def _row(entry):
    return RefRow(entry.ref_id, entry.title, entry.chars, entry.updated_at)


def sentence_of(error):
    """서비스 오류 → 화면에 나가는 고정 문장. 서비스가 낸 고정 문장의 오류만 그대로이고, 폴더를 못 정한 오류와 그 밖의 오류는 경로·세부 없는 고정 안내문이다."""
    if error.code in SERVICE_CODES:
        return error.rendered().message
    return T["ref_fail_folder"] if error.code in FOLDER_CODES else T["ref_fail_other"]


class ServiceReferencesProvider(ReferencesProvider):
    """서비스를 화면이 아는 모양으로 맞춘다. 거절은 고정 문장(`rendered().message`)뿐이다."""
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context      # 데이터 폴더는 홈과 같은 `--data-dir` 이다 — 만드는 것은 일할 때다(여는 것만으로는 아무것도 만들지 않는다)

    def _run(self, work):
        """서비스 일 하나 — 서비스 오류를 고정 문장의 `ReferencesRefusal` 로 바꾼다. 거절은 `except` 밖에서 낸다(앞 오류가 `__context__` 로 따라붙어 호출 흔적이 남지 않게)."""
        message, result = None, None
        try:
            result = work(self._factory(data_dir=self._data_dir))
        except AppError as error:
            message = sentence_of(error)
            error.__traceback__ = None
        if message is not None:
            raise ReferencesRefusal(message)
        return result

    def list_rows(self):
        listing = self._run(service.list_references)
        return RefListing(tuple(_row(entry) for entry in listing.entries), listing.skipped)

    def open(self, ref_id):
        found = self._run(lambda ctx: service.open_reference(ctx, ref_id))
        return OpenedRef(found.ref_id, found.title, found.body)

    def add(self, title, body):
        try:
            return _row(self._run(lambda ctx: service.add_reference(ctx, title=title, body=body)))
        finally:
            title = body = None                                                          # 어느 길로 끝나든(오류 포함) 이 틀의 글을 놓는다

    def add_file(self, path, title):
        try:
            added = self._run(lambda ctx: service.add_from_file(ctx, path, title=title or None))
        finally:
            path = None
        return _row(added.reference), added.encoding == "cp949"

    def save(self, ref_id, title, body):
        try:
            return _row(self._run(lambda ctx: service.update_reference(ctx, ref_id, title=title, body=body)))
        finally:
            title = body = None

    def delete(self, ref_id):
        self._run(lambda ctx: service.delete_reference(ctx, ref_id, confirmed=True))      # 화면 규칙이 두 단계 확인을 마친 뒤에만 부른다

    def folder_text(self):
        """보관함 폴더 위치 글 — 폴더를 만들지도 읽지도 않는다. 데이터 폴더를 정할 수 없으면(저장소 안 등) 고정 안내문이다."""
        message, text = None, ""
        try:
            text = str(service.folder_path(self._factory(data_dir=self._data_dir)))
        except AppError as error:
            message = sentence_of(error)
            error.__traceback__ = None
        if message is not None:
            return message
        return text


__all__ = ["ServiceReferencesProvider"]
