"""저장한 초안 — 저장·목록·불러오기·지우기(초안 작성 화면의 `저장`·`저장한 초안`, 결정 D-360 이후). 초안 한 편 = 글 보관함(`chanceblog.db`)의 `drafts` 표 한 행이고(기록 모양은 `content/saved_draft.py`),
표를 새로 만들지 않으므로 글 보관함 백업(`Store.backup`)과 되돌리기(`restore_from`)가 저장한 초안을 그대로 함께 옮긴다.

규칙:
  · **모든 쓰기는 `Store` 의 트랜잭션 하나다**(`Store.update_draft` — `BEGIN IMMEDIATE … COMMIT`, 실패하면 되돌린다). 쓰는 도중 끊기거나 디스크가 가득 차도 이전에 저장한 판이 그대로 남고 반쯤 쓴 기록이 없다.
    **확인(저장 횟수 비교·한도)과 쓰기가 같은 트랜잭션 안**이라 여러 창·프로세스가 같은 초안을 동시에 저장해도 갱신이 조용히 사라지지 않는다(D-369 — `expected_revision` 을 주면 먼저 저장된 판을 덮어쓰지 않고
    `STORE_CONFLICT`, 안 주면 줄을 서서 저장 횟수가 하나씩 오른다. 다른 초안은 모두 남는다).
  · **저장 직전에 키·토큰 모양을 검사한다**(`security/scan.py` — Google API 키·GitHub 토큰·Bearer 토큰·OAuth 토큰·AWS 액세스 키·개인 키). 제목·본문·키워드·태그·카테고리·요약·후보 주제·후보 번호·선택 입력과
    '처음 만든 초안'(`base` — 제목·제목 후보·본문·확인 권장·분야·바꾼 형식) 어느 칸에서든 찾으면 **아무것도 쓰지 않고**(보관함 파일을 열지도 않는다) `DRAFT_SECRET_FOUND` 로 멈춘다 — 위치(칸·줄)와 종류만 알리고
    찾은 글은 다시 보이지 않으며, 앱은 글을 자동으로 지우거나 바꾸지 않는다. **이 검사를 건너뛰고 저장하는 인자·길은 없다**('무시하고 저장' 없음 — 시험이 함수 서명과 소스를 훑는다). 만든 초안 칸에서 찾았다고 그 칸만 빼고
    저장하는 길도 없다(D-368 — 예전에 있던 그 길을 운영자 결정에 따라 없앴다: 화면에서 못 고치는 칸이라 전용 안내가 후보·블로그 프로필·선택 입력을 고쳐 다시 만들라고 알린다).
  · 저장은 복사가 아니다 — 복사 관문(건강 효과 단정·확인 권장·글 모양 점검)은 저장을 막지 않는다. 저장 실패는 이 함수의 오류로만 알리고 복사·편집 같은 다른 기능은 그대로 쓸 수 있다.
  · 지우기는 확인(`confirmed=True`)이 있어야 하고 지우기 직전 상태를 `backups/before-delete` 에 먼저 백업한다(글 지우기와 같다) — 백업이 안 되면 지우지 않는다.
  · 읽기(`list_drafts`·`load_draft`·`open_saved`)는 보관함을 읽기 전용으로 연다 — 파일을 만들거나 구조를 올리지 않는다(앱이 쓰다가 갑자기 꺼져 끝내지 못한 저장이 남은 보관함만 한 번 보통 열기로 정리한 뒤 읽는다 — D-370).
    읽을 수 없는 초안 한 편은 그 초안만 막고(`unreadable`) 다른 초안은 그대로 보인다.
  · 네트워크·하위 프로세스·AI 를 쓰지 않는다. 새 시계를 읽지 않는다(`ctx.stamp()`).
"""
from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from dataclasses import dataclass

from ..content import saved_draft as sd
from ..errors import AppError
from ..security import scan
from . import draft_engine
from .projects import _free_moment, require_confirmation

MAX_PLACES = 3                                   # 안내에 보이는 위치 수(나머지는 `외 N곳`)


class DraftSecretError(AppError):
    """저장 직전 검사가 키·토큰 모양을 찾았다(`DRAFT_SECRET_FOUND`) — `findings`(칸·줄·열·종류뿐, 글 내용 없음)를 들고 있다. 화면은 `advice()` 로 위치와 고치는 법을 보인다."""

    def __init__(self, findings):
        self.findings = tuple(findings)
        super().__init__("DRAFT_SECRET_FOUND", {"위치": places_text(self.findings)}, detail=f"{len(self.findings)}건")

    def advice(self):
        """위치·종류별 쉬운 안내(마지막이 고치는 법 — '만든 초안' 칸에서 찾았으면 전용 문구). 찾은 글은 어디에도 없다."""
        return sd.secret_advice(self.findings)


def places_text(findings):
    """위치 한 줄 — `본문 3번째 줄 · 제목 1번째 줄 외 2곳`. 칸 이름과 줄 번호뿐이다."""
    seen = []
    for item in findings:
        place = f"{item.where} {item.line}번째 줄"
        if place not in seen:
            seen.append(place)
    text = " · ".join(seen[:MAX_PLACES])
    return text + (f" 외 {len(seen) - MAX_PLACES}곳" if len(seen) > MAX_PLACES else "")


@dataclass(frozen=True)
class DraftEntry:
    """목록 한 줄 — 번호·제목·후보 주제·블로그·시각·본문 글자 수(공백 제외)."""
    draft_id: str
    title: str
    topic: str
    candidate_id: str
    blog: str
    created_at: str
    updated_at: str
    revision: int
    chars: int


@dataclass(frozen=True)
class DraftListing:
    """저장한 초안들(고친 때가 늦은 것부터) + 읽을 수 없는 초안의 번호들(`(번호, 오류 코드)`)."""
    entries: tuple
    unreadable: tuple = ()

    @property
    def total(self):
        return len(self.entries) + len(self.unreadable)


@dataclass(frozen=True)
class OpenedDraft:
    """다시 연 초안 — 저장한 기록 + 블로그 정보(이름·글쓰기 주소) + 이어진 후보가 있나(`found`·`missing`·`none`·`unknown`)."""
    draft: object
    context: object
    candidate: str
    context_problem: bool = False


def _stored_id(draft_id):
    if not sd.is_draft_id(draft_id):
        raise AppError("CONTENT_INVALID", {"항목": "저장한 초안 번호"}, detail="번호 모양이 아니다")
    return draft_id


def _check_secrets(draft):
    """저장 직전 검사 — 고친 글칸(제목·본문·키워드·태그·카테고리·요약·후보 주제·후보 번호·선택 입력)과 '처음 만든 초안'(`base` — 제목·제목 후보·본문·확인 권장·분야·바꾼 형식) **어느 칸에서든**
    키·토큰 모양을 찾으면 `DraftSecretError`(아무것도 쓰지 않는다). 만든 초안 칸에서 찾았다고 그 칸만 조용히 빼고 저장하지 않는다(D-368 — 운영자 결정: 발견 시 저장 중지·자동 삭제·치환 금지·위치와 유형만)."""
    found = scan.scan_fields(draft.text_fields()) + scan.scan_fields(draft.base_fields())
    if found:
        raise DraftSecretError(found)


def save_draft(ctx, *, title, body, core_keywords=(), sub_keywords=(), tags=(), category="", summary="", candidate_id="", topic="", blog="", post_type_choice=None, post_type="",
               options=None, base=None, draft_id=None, expected_revision=None):
    """초안을 저장하고 저장한 기록(`SavedDraft`)을 돌려준다. `draft_id` 가 없으면 새 초안(번호는 `dd-` + 지문), 있으면 그 초안을 고쳐 쓴다(저장한 횟수가 하나 오른다).
    `expected_revision`(그 초안을 불러왔을 때의 저장 횟수)을 주면 다른 곳에서 그 사이 다시 저장한 초안은 덮어쓰지 않는다(`STORE_CONFLICT`). 바뀐 것이 없으면 아무것도 쓰지 않고 있던 기록을 돌려준다.
    글칸은 글자 하나도 바꾸지 않는다(정규화·공백 다듬기·줄바꿈 바꾸기 없음). 비밀 모양이 있으면 `DraftSecretError`, 한도를 넘으면 `DRAFT_LIMIT`, 같은 번호의 기록이 깨졌으면 `DRAFT_CORRUPT`
    (덮어쓰지 않는다). 이 함수에는 검사를 건너뛰는 인자가 없다."""
    creating = draft_id is None
    if not creating:
        _stored_id(draft_id)
    if expected_revision is not None and (creating or not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1):
        raise AppError("CONTENT_INVALID", {"항목": "초안 저장 횟수"}, detail="이미 저장한 초안에만 1 이상의 정수로 줄 수 있다")
    stamp = ctx.stamp()
    if creating:
        if not isinstance(title, str) or not isinstance(body, str):
            raise AppError("CONTENT_INVALID", {"항목": "초안 제목·본문"}, detail="글이 아니다")
        draft_id = sd.make_draft_id(stamp, candidate_id, blog, title, body)
    draft = sd.SavedDraft.build(draft_id=draft_id, revision=1, created_at=stamp, updated_at=stamp, title=title, body=body, core_keywords=core_keywords, sub_keywords=sub_keywords, tags=tags,
                                category=category, summary=summary, candidate_id=candidate_id, topic=topic, blog=blog, post_type_choice=post_type_choice, post_type=post_type, options=options, base=base)
    _check_secrets(draft)                               # 보관함 파일을 열기 전 — 찾으면 아무것도 쓰지 않는다
    draft.to_text()                                     # 보관함 한 칸에 들어가는 크기인지도 파일을 열기 전에 본다(`DRAFT_LIMIT` — 한도 초과 저장이 빈 폴더에 보관함 파일을 만들지 않게)
    outcome = {}

    def decide(stored, count):
        """쓰기 잠금 안에서 불린다 — 지금 기록을 읽고 확인하고 새 글을 정한다(읽기·확인·쓰기가 한 트랜잭션이라 그 사이에 다른 프로세스의 저장이 끼어들 수 없다 — D-369)."""
        previous = sd.SavedDraft.from_text(stored, draft_id) if stored is not None else None      # 깨진 기록은 덮어쓰지 않고 DRAFT_CORRUPT 로 멈춘다
        if previous is None:
            if count >= sd.MAX_SAVED:                   # 새 행을 만드는 모든 저장에 한도가 걸린다(번호를 주고 부르든 아니든)
                raise AppError("DRAFT_LIMIT", {"이유": f"저장한 초안이 {sd.MAX_SAVED}편이에요"}, detail="저장한 초안 수가 한도에 이르렀다")
            final = draft if expected_revision is None else dataclasses.replace(draft, revision=expected_revision + 1)      # 그 사이 다른 곳에서 지웠다 — 고친 글을 잃지 않게 같은 번호로 다시 만든다
        else:
            if expected_revision is not None and previous.revision != expected_revision:
                raise AppError("STORE_CONFLICT", {"항목": f"저장한 초안 {sd.short_id(draft_id)}"}, detail=f"저장된 횟수 {previous.revision} / 이 화면이 불러온 횟수 {expected_revision}")
            final = dataclasses.replace(draft, revision=previous.revision + 1, created_at=previous.created_at)
            if dataclasses.replace(final, revision=previous.revision, updated_at=previous.updated_at) == previous:
                outcome["saved"] = previous
                return None                             # 바뀐 것이 없다 — 쓰지 않는다
        outcome["saved"] = final
        return final.to_text()

    with ctx.store() as store:
        store.update_draft(draft_id, decide, prefix=sd.ID_PREFIX, now=stamp)
    return outcome["saved"]


@contextmanager
def _reading(ctx):
    """글 보관함을 읽으려고 연다 — 읽기 전용(파일을 만들지도 구조를 올리지도 않는다). 앱이 쓰다가 갑자기 꺼져 끝내지 못한 저장(저널)이 남아 있으면 읽기 전용으로는 읽을 수 없어(`STORE_RECOVERY_PENDING`)
    그때만 보통 열기로 한 번 열어 되돌려 정리한 뒤 읽는다(D-370) — 정리는 저장하던 글을 쓰기 전 상태로 되돌리는 것이라 이전에 저장한 초안은 그대로이고, 다시 읽기로 풀리지 않던 목록·열기가 풀린다."""
    try:
        store = ctx.reading_only().store()
    except AppError as error:
        if error.code != "STORE_RECOVERY_PENDING":
            raise
        store = ctx.store()
    with store:
        yield store


def list_drafts(ctx):
    """저장한 초안 목록(고친 때가 늦은 것부터, 같으면 번호 순). 보관함 파일이 아직 없으면 빈 목록이고 파일을 만들지 않는다. 읽을 수 없는 초안 한 편은 `unreadable` 에 번호만 올리고 나머지는 그대로 보인다."""
    try:
        with _reading(ctx) as store:
            rows = [item for item in store.drafts() if sd.is_draft_id(item.project_id)]
    except AppError as error:
        if error.code == "CONTENT_NOT_FOUND":
            return DraftListing(())
        raise
    entries, unreadable = [], []
    for row in rows:
        try:
            draft = sd.SavedDraft.from_text(row.text, row.project_id)
        except AppError as error:
            unreadable.append((row.project_id, error.code))
            continue
        entries.append(DraftEntry(draft.draft_id, draft.title, draft.topic, draft.candidate_id, draft.blog, draft.created_at, draft.updated_at, draft.revision, sd.body_chars(draft.body)))
    entries.sort(key=lambda entry: (entry.updated_at, entry.draft_id), reverse=True)
    return DraftListing(tuple(entries), tuple(sorted(unreadable)))


def load_draft(ctx, draft_id):
    """저장한 초안 한 편(`SavedDraft`). 없으면 `CONTENT_NOT_FOUND`, 읽을 수 없으면 `DRAFT_CORRUPT`·`STORE_VERSION_UNSUPPORTED`(다른 초안은 그대로다)."""
    _stored_id(draft_id)
    try:
        with _reading(ctx) as store:
            row = store.load_draft(draft_id)
    except AppError as error:
        if error.code != "CONTENT_NOT_FOUND":
            raise
        row = None
    if row is None:
        raise AppError("CONTENT_NOT_FOUND", {"항목": "저장한 초안"}, detail=sd.short_id(draft_id))
    return sd.SavedDraft.from_text(row.text, draft_id)


def _candidate_state(ctx, candidate_id):
    """이어진 후보가 주제 엔진 보관함에 아직 있나 — `found`·`missing`(지워졌다)·`none`(처음부터 이어진 후보가 없다)·`unknown`(보관함을 읽지 못했다)."""
    if not candidate_id:
        return "none"
    try:
        draft_engine.find_row(ctx, candidate_id)
    except AppError as error:
        return "missing" if error.code == "TOPIC_CANDIDATE_NOT_FOUND" else "unknown"
    return "found"


def open_saved(ctx, draft_id):
    """저장한 초안을 화면에서 다시 열 때 필요한 것을 한꺼번에 읽는다(읽기만) — 기록 + 블로그 이름·글쓰기 주소(초안을 만들 때와 같은 규칙) + 이어진 후보가 있나. 후보가 지워졌거나 프로필 슬롯이 비어 있어도 열린다 —
    블로그 정보를 못 읽으면(설정 파일 문제 등) 이름·주소만 비우고(`context_problem`) 글은 그대로 연다."""
    draft = load_draft(ctx, draft_id)
    try:
        context = draft_engine.blog_context(ctx, draft.blog) if draft.blog else draft_engine.BlogContext("", (), "", "none", False, False)
        problem = False
    except AppError:
        context, problem = draft_engine.BlogContext(draft.blog, (), "", "none", False, False), True
    return OpenedDraft(draft, context, _candidate_state(ctx, draft.candidate_id), problem)


def delete_draft(ctx, draft_id, *, confirmed):
    """저장한 초안을 지운다(확인 `confirmed=True` 가 있어야 한다 — 아니면 아무것도 하지 않고 `CONFIRMATION_REQUIRED`). 지우기 직전 상태를 `backups/before-delete` 에 먼저 백업하고(안 되면 지우지 않는다)
    그 사본의 경로를 돌려준다. 읽을 수 없는(깨진) 초안도 지울 수 있다."""
    require_confirmation(confirmed, "저장한 초안 지우기")
    _stored_id(draft_id)
    if not ctx.workspace.store_path.exists():
        raise AppError("CONTENT_NOT_FOUND", {"항목": "저장한 초안"}, detail=sd.short_id(draft_id))
    with ctx.store() as store:
        if store.load_draft(draft_id) is None:
            raise AppError("CONTENT_NOT_FOUND", {"항목": "저장한 초안"}, detail=sd.short_id(draft_id))
        folder = ctx.workspace.backups_dir / "before-delete"
        saved = store.backup(folder, now=_free_moment(ctx, folder, store))
        store.discard_draft(draft_id)
    return saved


__all__ = ["DraftEntry", "DraftListing", "DraftSecretError", "OpenedDraft", "delete_draft", "list_drafts", "load_draft", "open_saved", "places_text", "save_draft"]
