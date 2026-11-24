"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)의 실제 공급자 — 서비스를 화면이 아는 모양(`ui/core/posts.py`)으로 맞추는 얇은 어댑터다. **화면 층이 글 서비스를 부르는 곳은 이 파일 한 곳뿐**이다(D-622).

부르는 서비스 함수는 정확히 아홉이다(시험이 소스를 훑어 이 목록과 같음을 못박는다):
  · 읽기 넷 — `projects.list_projects`·`projects.show_project`(읽기 전용 컨텍스트 — 파일도 폴더도 만들지 않는다)·`own_posts.read_own_files`(고른 파일 읽기)·`own_posts.check_pasted_text`(붙여 넣은 글의 한도 검사)
  · 쓰기 다섯 — `projects.new_project`·`projects.import_html`(가져오기)·`review.request_review`(검토 시작)·`review.grant_approval`(승인)·`review.revoke_approval`(승인 취소) — 모두 글 저장소(데이터 폴더의 `chanceblog.db`)에 한 트랜잭션으로 쓰는 기존 함수이고
    사용자가 단추를 눌렀을 때만 불린다. **외부로 쓰는 길은 하나도 없다**: Pages 올리기·공개 확인·네이버 복사 패키지·발행 주소 기록(`pages_flow`·`naver_flow`·`issue_naver_package`·`record_naver_published`)·git·네트워크·`capabilities`·`external` 은 가져오지도 않는다.
서비스 오류(`AppError`)는 **종류**로만 나눠 고정 문장으로 알린다 — 오류의 세부·경로·입력한 글은 화면에 나가지 않는다(오류 코드는 접힌 진단 정보에만). 승인 직전에는 글의 판·상태를 다시 읽어 낡았으면 승인하지 않는다(서비스도 승인 순간에 관문을 다시 검사한다).
키·자격 증명은 읽지도 쓰지도 않는다. 이 모듈은 PySide6 를 모른다.
"""
from __future__ import annotations

from ..content import status as st
from ..errors import AppError
from ..service import own_posts
from ..service import projects as project_service
from ..service import review as review_service
from ..service.context import make_context
from ..service.previews import PagesParams
from .adapters import is_folder
from .core import post_rules as rules
from .core.jobs import JobCancelled
from .core.posts import (PAGES, PLATFORMS, ImportFile, PlatformStatus, PostDetail, PostFailure, PostOutcome, PostRow, PostsData, PostsProvider, ReviewReport, SimilarityInfo)
from .core.text import T

KIND_OF_CODE = {"CONTENT_INVALID": "input", "CONFIRMATION_REQUIRED": "input", "CHECK_FAILED": "check", "SECRET_SHAPE_FOUND": "secret", "CONTENT_NOT_FOUND": "notfound", "STATUS_TRANSITION_INVALID": "state",
                "NAVER_SIMILARITY_HIGH": "similarity", "NAVER_PROFILE_MISSING": "profile", "STORE_LOCKED": "locked", "STORE_CONFLICT": "stale", "DISK_FULL": "disk", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io",
                "FILE_PATH_TOO_LONG": "io", "DATA_DIR_UNSAFE": "io", "STORE_RECOVERY_PENDING": "io", "MIGRATION_BLOCKED": "io", "MIGRATION_FAILED": "io", "STORE_CORRUPT": "corrupt", "SETTINGS_INVALID": "corrupt",
                "STORE_VERSION_UNSUPPORTED": "newer"}                  # 서비스 오류 코드 → 화면이 다르게 다룰 종류(나머지는 `other`)
SENTENCE_OF_KIND = {"stale": "post_fail_stale", "notfound": "post_fail_notfound", "state": "post_fail_state", "gate": "post_fail_gate", "similarity": "post_fail_similarity", "profile": "post_fail_profile",
                    "locked": "post_fail_locked", "disk": "post_fail_disk", "io": "post_fail_io", "corrupt": "post_fail_corrupt", "newer": "post_fail_newer", "other": "post_fail_other"}


def failure_of(error, *, action="read"):
    """서비스 오류 → 화면용 실패(종류 + 고정 문장 + 진단 코드). `action` 은 어디서 났나(`read`·`import`·`review`·`approve`·`revoke`) — 같은 코드도 어디서 났느냐에 따라 문장이 다르다.
    문장에 들어가는 값은 **고정 이름**(칸 이름·위치·유형)뿐이고 입력한 글은 없다."""
    kind = KIND_OF_CODE.get(error.code, "other")
    if kind == "check" and action in ("approve", "revoke"):
        kind = "gate"
    if action == "read" and kind in ("input", "check", "state", "similarity", "profile", "stale"):
        kind = "corrupt" if kind == "input" else "other"
    if kind == "secret":
        where, kinds = error.slots.get("위치"), error.slots.get("유형")
        text = T["post_fail_secret"].format(where=rules.shown(where, 80), kinds=rules.shown(kinds, 80)) if where and kinds else T["post_fail_secret_plain"]
    elif kind == "input":
        field = rules.shown(error.slots.get("항목"), 80)
        text = T["post_fail_input"].format(field=field) if field else T["post_fail_input_plain"]
    elif kind == "check":
        text = T["post_fail_check"] if action == "import" else T["post_gate_header_value"]
    else:
        text = T[SENTENCE_OF_KIND[kind]]
    return PostFailure(text, code=error.code, kind=kind)


def _row(row):
    statuses = () if row.error else tuple((key, row.statuses.get(key, st.NOT_STARTED)) for key in PLATFORMS)
    return PostRow(row.project_id, row.title, row.revision, row.updated_at, statuses, row.error or "")


def detail_of(view):
    """서비스의 글 모습 → 화면의 글 모습(미리보기는 여기서 만든다 — 작업 스레드다)."""
    platforms = tuple(PlatformStatus(item.platform, item.status, item.rendered_revision, bool(item.has_rendering), item.error_code or "") for key in PLATFORMS for item in (view.variant(key),))
    return PostDetail(view.project_id, view.title, view.revision, view.created_at, view.updated_at, platforms,
                      rules.build_preview(view.source_content, refs=len(view.references), assets=len(view.assets)), False)


class ServicePostsProvider(PostsProvider):
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context

    def _context(self, action):
        """서비스 컨텍스트 — 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(홈·설정·블로그 관리와 같다). 만드는 것은 일할 때다(여는 것만으로는 아무것도 만들지 않는다)."""
        if self._data_dir is not None and not is_folder(self._data_dir):
            raise PostFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", kind="io")
        try:
            return self._factory(data_dir=self._data_dir)
        except AppError as error:
            raise failure_of(error, action=action) from None

    # ---- 읽기(파일도 폴더도 만들지 않는다) ----
    def _profiles(self, ctx):
        """설정 파일에 프로필이 있는 네이버 블로그들 — 못 읽으면 없는 것으로 둔다(네이버 검토가 꺼지고 안내가 보인다 — 글 목록은 막지 않는다)."""
        try:
            return tuple(key for key in ctx.settings.naver_profile_dicts() if key in ("naver_a", "naver_b"))
        except AppError:
            return ()

    def load_posts(self, progress, cancelled):
        ctx = self._context("read")
        state = "ok"
        try:
            rows = project_service.list_projects(ctx.reading_only())
        except AppError as error:
            if error.code != "CONTENT_NOT_FOUND":
                raise failure_of(error, action="read") from None
            rows, state = [], "missing"                                            # 글 저장소 파일이 아직 없다 — 빈 목록이다(읽기만 하므로 만들지 않는다)
        if cancelled():
            raise JobCancelled()
        ordered = sorted(rows, key=lambda row: (str(row.updated_at), row.project_id), reverse=True)
        return PostsData(tuple(_row(row) for row in ordered), self._profiles(ctx), state, False, False)

    def load_post(self, project_id, progress, cancelled):
        ctx = self._context("read")
        try:
            view = project_service.show_project(ctx.reading_only(), project_id)
        except AppError as error:
            raise failure_of(error, action="read") from None
        if cancelled():
            raise JobCancelled()
        return detail_of(view)

    def read_import_file(self, path, progress, cancelled):
        """고른 글 파일(.md·.txt)을 서비스의 안전한 읽기로 읽는다 — 읽기뿐이다. 거절은 서비스의 고정 문장(경로·파일 이름·글 없음)이다."""
        try:
            found = own_posts.read_own_files([path])[0]
        except AppError as error:
            raise PostFailure(T["post_fail_file"].format(why=rules.shown(error.detail, 200)), code=error.code, kind="file") from None
        if cancelled():
            raise JobCancelled()
        return PostOutcome("file", file=ImportFile(rules.title_of(path), found.text, found.chars, found.encoding))

    # ---- 쓰기(사용자가 눌렀을 때만 — 모두 글 저장소 한 곳) ----
    def _read_view(self, ctx, project_id, action):
        try:
            return project_service.show_project(ctx, project_id)
        except AppError as error:
            raise failure_of(error, action=action) from None

    def import_post(self, request, progress, cancelled):
        ctx = self._context("import")
        title = request.title.strip()
        try:
            own_posts.check_pasted_text(request.body)                              # 파일과 같은 한도(10만 자·NUL·빈 글) — 같은 고정 문장
            view = project_service.import_html(ctx, title, request.body) if request.kind == "html" else project_service.new_project(ctx, title, request.body)
        except AppError as error:
            if str(error.slots.get("항목", "")).startswith(own_posts.SUBJECT):
                raise PostFailure(T["post_fail_paste"].format(why=rules.shown(error.detail, 200)), code=error.code, kind="input") from None
            raise failure_of(error, action="import") from None
        return PostOutcome("imported", detail_of(view))

    def review_post(self, request, progress, cancelled):
        ctx = self._context("review")
        pages = None
        if request.platform == PAGES and request.pages is not None:
            values = request.pages
            pages = PagesParams(values.category, values.lang, values.image_url, tuple(values.tags), values.description or None)
        try:
            result = review_service.request_review(ctx, request.project_id, request.platform, pages=pages, naver_options=None)
        except AppError as error:
            raise failure_of(error, action="review") from None
        view = self._read_view(ctx, request.project_id, "review")
        return PostOutcome("reviewed", detail_of(view), self._report(result, view))

    def _report(self, result, view):
        """검토 요청의 결과 + 글에 건 두 점검(건강 효과 단정·비밀 모양) → `ReviewReport`. 점검은 가짜 공급자와 **같은 함수**(`post_rules`)이고 글 자신(제목·본문·출처)에 건다."""
        health = rules.health_of(view.title, view.source_content)
        secrets = rules.secret_spots(view.title, view.source_content, view.references)
        if result.platform == PAGES:
            preview, gates = result.pages, result.pages.gates
            summary = (T["post_summary_pages"].format(category=rules.shown(preview.category, 60), lang=T.get("post_lang_" + preview.lang, preview.lang), kb=max(1, round(preview.size_bytes / 1024))),)
            return ReviewReport(view.project_id, result.platform, view.revision, result.status, bool(gates.ok), rules.unique_codes(gates.reasons), tuple(rules.shown(item, 400) for item in gates.reasons),
                                tuple(rules.shown(item, 300) for item in gates.warnings), summary, None, health, secrets, False)
        package = result.naver.package
        similarity = None
        if result.similarity is not None:
            similarity = SimilarityInfo(result.similarity.level, float(result.similarity.overall), tuple(rules.shown(item, 300) for item in result.similarity.reasons))
        summary = (T["post_summary_naver"].format(title=rules.shown(package.title, 60), chars=f"{package.chars:,}", paragraphs=package.paragraphs),)
        return ReviewReport(view.project_id, result.platform, view.revision, result.status, True, (), (), tuple(rules.shown(item, 300) for item in package.warnings), summary, similarity, health, secrets, False)

    def approve_post(self, request, progress, cancelled):
        ctx = self._context("approve")
        current = self._read_view(ctx, request.project_id, "approve")
        state = current.variant(request.platform) if request.platform in PLATFORMS else None
        if state is None or current.revision != request.revision:
            raise PostFailure(T["post_fail_stale"], code="STALE", kind="stale")           # 검토 결과를 읽은 뒤 글이 바뀌었다 — 승인하지 않는다
        if state.status != st.REVIEW_REQUIRED:
            raise PostFailure(T["post_fail_state"], code="STATUS_TRANSITION_INVALID", kind="state")
        if state.rendered_revision != current.revision:
            raise PostFailure(T["post_fail_stale"], code="STALE", kind="stale")           # 저장된 렌더링이 지금 판의 것이 아니다
        if rules.text_blocks(current.title, current.source_content, current.references):
            raise PostFailure(T["post_fail_blocked"], code="REVIEW_BLOCKED", kind="gate")  # 건강 효과 단정·비밀 모양이 있는 글은 화면 규칙과 별개로 여기서도 승인하지 않는다
        try:
            review_service.grant_approval(ctx, request.project_id, request.platform, similarity_approved=False)       # 서비스가 승인 순간에 관문(Pages)·유사도(네이버)를 다시 검사한다 — 걸리면 승인하지 않는다
        except AppError as error:
            raise failure_of(error, action="approve") from None
        return PostOutcome("approved", detail_of(self._read_view(ctx, request.project_id, "approve")))

    def revoke_post(self, request, progress, cancelled):
        ctx = self._context("revoke")
        try:
            review_service.revoke_approval(ctx, request.project_id, request.platform)
        except AppError as error:
            raise failure_of(error, action="revoke") from None
        return PostOutcome("revoked", detail_of(self._read_view(ctx, request.project_id, "revoke")))


__all__ = ["ServicePostsProvider", "detail_of", "failure_of"]
