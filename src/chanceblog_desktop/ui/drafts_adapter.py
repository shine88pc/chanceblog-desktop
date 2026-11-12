"""초안 작성 화면의 실제 공급자 — 서비스(`service/draft_engine.py`·`service/draft_store.py`)를 화면이 아는 모양(`ui/core/drafts.py`)으로 맞추는 얇은 어댑터다. **초안 만들기는 읽기뿐이다**: 부르는 서비스 함수는 `make_body_for_engine` 하나이고
(보관함·설정·채널 프로필 파일을 읽기 전용으로 읽는다) 후보 상태를 바꾸는 길은 없다. 저장한 초안(D-361)은 사용자가 `저장`·`열기`·`지우기` 를 눌렀을 때만 서비스(`draft_store`)를 부르는 넷(`save_draft`·`list_saved`·`open_saved`·`delete_saved`)이 한다 —
화면 코드(이 파일 포함)에는 파일을 직접 쓰는 호출이 없고 모든 쓰기는 서비스를 거친다(시험이 소스를 훑는다). 홈·설정·블로그 관리·Seed 관리·주제 후보 어댑터는 그대로다.

초안은 **후보 번호(엔진 번호 전체)로 서비스가 보관함에서 다시 읽어** 만든다 — 화면이 후보의 값을 넘기는 길이 없고, 옛 후보 보관함의 순번과 섞이는 길도 없다. 서비스 오류(`AppError`)는 **종류**(안전 판정 중지·네이버가 아닌 채널·후보 없음·선택 입력의 틀린 칸·
읽기 오류)로만 나눠 화면에 알린다 — 화면 문장은 `ui/core/text.py` 의 정해진 말이고 오류의 세부(경로·예외 이름·입력한 값)는 화면에 나가지 않는다(선택 입력의 틀린 칸은 서비스가 정한 칸 이름과 고정 이유만 보인다).
이 모듈은 PySide6 를 모른다. 무거운 모듈(`service/draft_engine`·`content/draft_body`)은 쓰는 함수 안에서 늦게 가져온다(앱이 열릴 때 정규식을 한꺼번에 만들지 않게).
"""
from __future__ import annotations

from ..errors import AppError
from ..service.context import make_context
from .adapters import is_folder
from .core.draft_rules import build_options, shown
from .core.drafts import DraftFailure, DraftResult, DraftsProvider, OpenedResult, SavedListing, SavedOutcome, SavedRow, option_failure, restored_result, save_failure
from .core.jobs import JobCancelled
from .core.text import T

KIND_OF_CODE = {"TOPIC_CANDIDATE_NOT_FOUND": "notfound", "CANDIDATE_INVALID": "invalid", "TOPIC_STORE_VERSION_UNSUPPORTED": "newer",
                "TOPIC_STORE_CORRUPT": "corrupt", "TOPIC_STORE_RECOVERY_PENDING": "corrupt", "TOPIC_FILE_INVALID": "corrupt", "SETTINGS_INVALID": "corrupt", "NAVER_PROFILE_INVALID": "corrupt",
                "TOPIC_STORE_LOCKED": "io", "DISK_FULL": "io", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io", "FILE_PATH_TOO_LONG": "io", "DATA_DIR_UNSAFE": "io"}      # 서비스 오류 코드 → 화면이 다르게 다룰 종류(나머지는 `other`)
SENTENCE_OF_KIND = {"stopped": "drf_refused_desc", "channel": "drf_channel_desc", "notfound": "drf_fail_notfound", "invalid": "drf_fail_invalid", "io": "drf_fail_io", "newer": "drf_fail_newer",
                    "corrupt": "drf_fail_corrupt", "other": "drf_fail_other"}


def failure_of(error):
    """서비스 오류 → 화면용 실패(종류 + 진단 코드). 문장은 종류별로 정해진 쉬운 말이고 오류의 세부·경로·입력한 값은 화면에 나가지 않는다. 선택 입력의 틀린 칸만 칸 이름과 고정 이유를 보인다."""
    from ..content import draft_body as generator
    slots = getattr(error, "slots", None) or {}
    code = str(getattr(error, "code", "") or "")
    if code == "CONTENT_INVALID":
        kind = "stopped" if slots.get("항목") == generator.STOP_ITEM else "invalid"
    elif code == "DRAFT_OPTION_INVALID":
        if slots.get("항목") == "블로그":
            kind = "channel"
        else:
            return option_failure(error)
    else:
        kind = KIND_OF_CODE.get(code, "other")
    return DraftFailure(T[SENTENCE_OF_KIND[kind]], code=code, kind=kind)


class ServiceDraftsProvider(DraftsProvider):
    sample = False
    saving = True                                                                        # 저장한 초안(D-361) — 서비스 `draft_store` 가 한다

    def __init__(self, data_dir=None, *, context_factory=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context

    def _context(self):
        if self._data_dir is not None and not is_folder(self._data_dir):                  # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(홈·설정·블로그·Seed·후보와 같다)
            raise DraftFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", kind="io")
        return self._factory(data_dir=self._data_dir)

    def make_draft(self, request, progress, cancelled):
        """초안을 만든다 — 읽기뿐이다(보관함·설정·채널 프로필 파일을 만들지도 올리지도 바꾸지도 않는다). 서비스 함수 하나(`make_body_for_engine`)를 부른다."""
        from ..service import draft_engine
        ctx = self._context()
        try:
            options = build_options(request.options or {})
            made = draft_engine.make_body_for_engine(ctx, request.candidate_id, blog=request.blog, post_type=request.post_type, options=options)
        except AppError as error:
            raise failure_of(error) from None
        if cancelled():
            raise JobCancelled()
        names = tuple((key, shown(name, 30)) for key, name in made.blog_names)
        return DraftResult(made.candidate_id, made.body, made.blog, made.post_type, dict(request.options or {}), names, made.blog_url, made.rejected, made.profile_found, made.channel_found, False, made.address)

    # ---- 저장한 초안 — 사용자가 눌렀을 때만 불린다. 서비스 오류는 종류별 쉬운 문장으로만 알린다(`save_failure` — 세부·경로·글은 화면에 나가지 않는다) ----
    def save_draft(self, request, progress, cancelled):
        """초안을 저장한다 — 서비스가 저장 직전에 키·토큰 모양을 검사해 있으면 저장하지 않는다(`DRAFT_SECRET_FOUND` → 위치·종류만). 글은 글자 그대로 넘긴다."""
        from ..content import saved_draft
        from ..service import draft_store
        ctx = self._context()
        try:
            base = saved_draft.BaseDraft.build(**request.base) if request.base else None
            saved = draft_store.save_draft(ctx, title=request.title, body=request.body, core_keywords=request.core_keywords, sub_keywords=request.sub_keywords, tags=request.tags, category=request.category,
                                           summary=request.summary, candidate_id=request.candidate_id, topic=request.topic, blog=request.blog, post_type_choice=request.post_type_choice,
                                           post_type=request.post_type, options=request.options, base=base, draft_id=request.draft_id, expected_revision=request.expected_revision)
        except AppError as error:
            raise save_failure(error) from None
        return SavedOutcome(saved.draft_id, saved.revision, saved.updated_at)

    def list_saved(self, progress, cancelled):
        """저장한 초안 목록 — 읽기뿐이다(보관함이 없으면 빈 목록이고 파일을 만들지 않는다)."""
        from ..service import draft_store
        ctx = self._context()
        try:
            listing = draft_store.list_drafts(ctx)
        except AppError as error:
            raise save_failure(error) from None
        rows = tuple(SavedRow(entry.draft_id, entry.title, entry.topic, entry.blog, entry.updated_at, entry.chars, entry.revision) for entry in listing.entries)
        return SavedListing(rows, tuple(draft_id for draft_id, _code in listing.unreadable))

    def open_saved(self, draft_id, progress, cancelled):
        """저장한 초안을 다시 연다 — 읽기뿐이다. 후보가 지워졌거나 프로필 슬롯이 비어 있어도 열린다(이어진 후보가 있나는 `candidate` 로 알린다)."""
        from ..service import draft_store
        ctx = self._context()
        try:
            opened = draft_store.open_saved(ctx, draft_id)
        except AppError as error:
            raise save_failure(error) from None
        if cancelled():
            raise JobCancelled()
        draft, context = opened.draft, opened.context
        result = restored_result(draft, names=tuple((key, shown(name, 30)) for key, name in context.blog_names), blog_url=context.blog_url, address=context.address, profile_found=context.profile_found,
                                 channel_found=context.channel_found)
        return OpenedResult(result, draft.draft_id, draft.revision, draft.updated_at, opened.candidate, opened.context_problem, draft.topic, draft.title, draft.body, draft.post_type_choice)

    def delete_saved(self, draft_id, progress, cancelled):
        """저장한 초안을 지운다 — 확인창을 거친 뒤에만 불린다. 서비스가 지우기 직전 상태를 백업해 둔다(안 되면 지우지 않는다)."""
        from ..service import draft_store
        ctx = self._context()
        try:
            draft_store.delete_draft(ctx, draft_id, confirmed=True)
        except AppError as error:
            raise save_failure(error) from None
        return draft_id


__all__ = ["KIND_OF_CODE", "ServiceDraftsProvider", "failure_of"]
