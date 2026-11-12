"""초안 작성 화면이 아는 값과 공급자의 모양 + 가짜 공급자 — 화면은 이 모양만 안다. 실제 서비스(`service/draft_engine.py`)는 얇은 어댑터(`ui/drafts_adapter.py`)가 같은 모양으로 맞춘다.

초안을 만들고 고치고 복사하는 것은 **아무것도 저장하지 않는다**(복사는 화면 틀이 클립보드에 넣고, 초안은 메모리에만 있다). 저장은 사용자가 `저장` 을 눌렀을 때뿐이다(결정 D-361 — 저장한 초안):
공급자는 읽기 하나(`make_draft`)에 저장 넷(`save_draft`·`list_saved`·`open_saved`·`delete_saved` — 저장 기능이 있는 공급자만 `saving` 이 참이다)을 더했고, 저장은 모두 작업 스레드에서 서비스(`service/draft_store.py`)가 한다.
가짜 공급자(`FakeDraftsProvider` — `--sample`·시험·사진)는 파일·서비스를 부르지 않고 **메모리에서만** 일한다. 가짜 후보(제목·키워드·블로그 이름은 모두 지어낸 예시)로 서비스와 **같은 순수 생성기**(`content/draft_body.build_body`)를 돌려 같은 모양의 초안을 만든다.
`review_health` 는 화면의 **두 번째 방어선**이다 — 후보의 제목·키워드는 서비스가 이미 판정해 '자동 초안 중지' 로 막지만, 서비스가 만든 글·사용자가 적은 선택 입력·고친 글에 건강 효과 단정이 있는지는 아무도 보지 않던 틈(독립 검증 V1·V3)을
메우려고 주제 엔진의 판정기(`topics.safety`)를 글 조각마다 한 번 더 부른다(읽기·계산뿐 — 이 파일이 엔진 패키지를 읽는 이유는 가짜 공급자와 이것이다).
PySide6 도 파일도 모른다. 무거운 모듈(`content/draft_body`·`topics`)은 쓰는 함수 안에서 늦게 가져온다(앱이 열릴 때 정규식을 한꺼번에 만들지 않게).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

from .candidates import PROFILES
from .draft_rules import BLOG_NAMES, HEALTH_STAGES, HEALTH_STOP, PREVIEW, SPOT_LIMIT, HealthReview, build_options, option_labels, shown
from .jobs import JobCancelled, JobFailure
from .text import T, display_text

KINDS_OF_FAILURE = ("stopped", "channel", "notfound", "option", "invalid", "io", "newer", "corrupt", "other", "keyshape", "limit", "conflict", "locked", "record")
SAMPLE_DAY = "2026-11-05"                                                          # 가짜 공급자가 쓰는 '오늘'(시계를 읽지 않는다 — 같은 입력은 늘 같은 초안)
SAMPLE_BLOGS = (("naver_a", "예시 블로그 가", "https://blog.naver.com/example-blog-a"), ("naver_b", "예시 블로그 나", "https://blog.naver.com/example-blog-b"))


class DraftFailure(JobFailure):
    """초안 만들기의 실패 — 쉬운 문장(`user_message`)과 진단용 코드, 그리고 화면이 다르게 다룰 종류: `stopped` 자동 초안 중지 후보 · `channel` 네이버가 아닌 채널 · `notfound` 후보가 보관함에 없다 · `option` 선택 입력의 한 칸이 틀렸다(`field` 가 그 칸) ·
    `invalid` 후보의 글을 초안에 쓸 수 없다 · `io`·`newer`·`corrupt` 읽기 오류 · `other`."""

    def __init__(self, user_message, code="", *, kind="other", field="", retryable=True, reason="", advice=""):
        super().__init__(user_message, code, retryable)
        self.kind = kind if kind in KINDS_OF_FAILURE else "other"
        self.field = field if isinstance(field, str) else ""
        self.reason = reason if isinstance(reason, str) else ""                       # 저장 한도 실패의 이유 한 구절(서비스가 정한 고정 문장)
        self.advice = advice if isinstance(advice, str) else ""                       # 비밀 모양을 찾았을 때의 안내(위치·종류와 고치는 법 — 찾은 글은 없다)


def option_failure(error):
    """서비스의 `DRAFT_OPTION_INVALID`(칸 이름과 이유가 슬롯에 있다 — 고정 문장이고 입력한 글은 되풀이하지 않는다)를 화면의 한 문장으로 — 어느 칸이 왜 안 되는지. 가린 뒤 줄인다."""
    slots = getattr(error, "slots", None) or {}
    label = str(slots.get("항목", ""))
    found = {text: name for name, text in option_labels().items()}
    reason = shown(str(slots.get("이유", "")), 160)
    where = shown(label, 30)
    message = T["drf_fail_option"].format(field=where, reason=reason) if where and reason else T["drf_fail_option_plain"]
    return DraftFailure(message, code=str(getattr(error, "code", "") or "DRAFT_OPTION_INVALID"), kind="option", field=found.get(label, ""))


@dataclass(frozen=True)
class DraftTarget:
    """초안을 만들 후보 — 번호(엔진 번호 전체)와 보이는 값뿐이다. 초안 내용은 공급자가 번호로 다시 읽어 만든다(화면이 후보 값을 넘기는 길은 없다)."""
    candidate_id: str
    title: str = ""                                          # 보이는 한 줄(비밀 모양을 가린 뒤 줄였다)
    channel: str = ""                                        # 후보의 채널(엔진 이름)
    channel_name: str = ""                                   # 채널의 표시 이름
    stop: bool = False                                       # 자동 초안 중지 후보 — 서비스를 부르지 않고 거절 화면만
    sample: bool = False


@dataclass(frozen=True)
class DraftRequest:
    candidate_id: str
    blog: object = None                                      # `naver_a`·`naver_b` 또는 None(후보 기준)
    post_type: object = None                                 # 다섯 글 유형 중 하나 또는 None(후보 기준)
    options: dict = None                                     # {칸 이름: 글} — 비어 있는 칸은 없다(`draft_rules.options_dict`)


@dataclass(frozen=True)
class DraftResult:
    """공급자가 돌려주는 초안 — `body` 는 서비스의 `DraftBody` 그대로(제목 후보 셋·본문·키워드·태그·카테고리·요약·확인 권장·복사용 글)."""
    candidate_id: str
    body: object
    blog: str                                                # 만든 네이버 블로그
    post_type: str
    options: dict                                            # 이번에 반영한 선택 입력
    blog_names: tuple = ()                                   # ((`naver_a`, 표시 이름), (`naver_b`, 표시 이름))
    blog_url: str = ""                                       # 프로필의 블로그 주소('' 이면 프로필 없음)
    rejected: bool = False                                   # 후보가 '제외' 상태다(상태는 바꾸지 않았다)
    profile_found: bool = False
    channel_found: bool = False
    sample: bool = False
    address: str = "none"                                    # `blog_url` 의 출처: `profile`·`channel`·`unusable`·`none`(서비스 `EngineBody.address`)


@dataclass(frozen=True)
class SaveRequest:
    """`저장` 을 눌렀을 때 화면이 서비스에 넘기는 것 — 지금 편집기의 제목·본문과 만든 방법. `draft_id`·`expected_revision` 은 이미 저장한 초안을 고쳐 쓸 때만 있다. 처음 만든 초안(`base`)은 다시 열 때 고친 정도·제목 후보·확인 권장을 되살리는 바탕이다."""
    title: str
    body: str
    core_keywords: tuple = ()
    sub_keywords: tuple = ()
    tags: tuple = ()
    category: str = ""
    summary: str = ""
    candidate_id: str = ""
    topic: str = ""
    blog: str = ""
    post_type_choice: object = None
    post_type: str = ""
    options: dict = None
    base: object = None                                      # {"title", "titles", "body", "checks", "domain", "replaced"} 또는 None
    draft_id: object = None
    expected_revision: object = None


@dataclass(frozen=True)
class SavedOutcome:
    """저장이 끝났다 — 저장한 초안의 번호·저장 횟수·고친 시각."""
    draft_id: str
    revision: int
    updated_at: str


@dataclass(frozen=True)
class SavedRow:
    """저장한 초안 목록의 한 줄."""
    draft_id: str
    title: str
    topic: str
    blog: str
    updated_at: str
    chars: int
    revision: int = 1


@dataclass(frozen=True)
class SavedListing:
    """저장한 초안 목록 — 줄들(고친 때가 늦은 것부터)과 읽을 수 없는 초안의 번호들."""
    rows: tuple = ()
    unreadable: tuple = ()                                   # 읽을 수 없는 초안의 번호들

    @property
    def total(self):
        return len(self.rows) + len(self.unreadable)


@dataclass(frozen=True)
class OpenedResult:
    """저장한 초안을 다시 열었다 — 화면이 그릴 초안(`result`)과 저장한 판(번호·저장 횟수·시각), 이어진 후보가 있나(`found`·`missing`·`none`·`unknown`)."""
    result: object
    draft_id: str
    revision: int
    updated_at: str
    candidate: str = "none"
    context_problem: bool = False
    topic: str = ""
    title: str = ""                                          # 저장한 제목(편집기에 그대로 들어간다)
    body: str = ""                                           # 저장한 본문
    post_type_choice: object = None                          # 저장할 때 화면에서 고른 글 유형(None = 후보 기준)


@dataclass(frozen=True)
class RestoredBody:
    """저장한 초안을 다시 열었을 때 화면이 읽는 `DraftBody` 의 칸들만 가진 값(블록 구조는 없다) — 저장할 때 함께 둔 '만든 초안' 이 있으면 제목 후보·확인 권장·분야·고친 정도의 바탕이 그것이고, 없으면 저장한 글이 바탕이다."""
    blog: str
    topic: str
    post_type: str
    titles: tuple
    selected_title: str
    body_text: str
    core_keywords: tuple
    sub_keywords: tuple
    tags: tuple
    category: str
    summary: str
    checks: tuple
    domain: str
    replaced: object = None

    @property
    def tags_text(self):
        return " ".join("#" + tag for tag in self.tags)


def restored_result(draft, *, names=(), blog_url="", address="none", profile_found=False, channel_found=False, sample=False):
    """저장한 기록(`SavedDraft`)과 블로그 정보 → 화면이 그리는 `DraftResult`. 화면의 제목·본문은 컨트롤러가 저장한 글을 따로 넣는다(`apply_loaded`) — 여기의 `body` 는 '만든 초안' 쪽(바탕)이다."""
    base = draft.base
    if base is None:
        titles, selected, body_text, checks, domain, replaced = (draft.title,), draft.title, draft.body, (), "", None
    else:
        titles, selected, body_text, checks, domain, replaced = tuple(base.titles), base.title, base.body, tuple(base.checks), base.domain, base.replaced
    body = RestoredBody(draft.blog, draft.topic, draft.post_type, titles, selected, body_text, tuple(draft.core_keywords), tuple(draft.sub_keywords), tuple(draft.tags), draft.category, draft.summary,
                        checks, domain, replaced)
    return DraftResult(draft.candidate_id, body, draft.blog, draft.post_type, dict(draft.options), tuple(names), blog_url, False, profile_found, channel_found, sample, address)


def save_failure(error):
    """저장·목록·열기·지우기에서 난 서비스 오류(`AppError` — 코드와 칸만 읽는다) → 화면용 실패. 문장은 종류별로 정해진 쉬운 말이고 오류의 세부·경로·입력한 글은 화면에 나가지 않는다.
    키·토큰 모양을 찾은 실패(`DRAFT_SECRET_FOUND`)는 위치·종류와 고치는 법만 `advice` 에 담는다(찾은 글은 어디에도 없다)."""
    code = str(getattr(error, "code", "") or "")
    slots = getattr(error, "slots", None) or {}
    if code == "DRAFT_SECRET_FOUND":
        findings = tuple(getattr(error, "findings", ()) or ())
        return secret_failure(findings, code)
    kind = SAVE_KIND_OF_CODE.get(code, "other")
    reason = shown_reason(slots.get("이유", "")) if kind == "limit" else ""
    return DraftFailure(T[SAVE_SENTENCE_OF_KIND[kind]].format(reason=reason) if kind == "limit" else T[SAVE_SENTENCE_OF_KIND[kind]], code=code, kind=kind, reason=reason)


def secret_failure(findings, code="DRAFT_SECRET_FOUND"):
    """키·토큰 모양을 찾았다는 실패 — 안내는 위치(칸·줄)와 종류와 고치는 법뿐이다('만든 초안' 칸에서 찾았으면 전용 문구 — 서비스와 같은 `saved_draft.secret_advice`)."""
    from ...content import saved_draft as sd
    advice = sd.secret_advice(tuple(findings)) if findings else ""
    return DraftFailure(T["drf_savefail_secret_head"], code=code, kind="keyshape", advice=advice)


def shown_reason(value):
    """저장 한도 실패의 이유(서비스가 정한 고정 문장) — 가린 뒤 줄인다(화면 글이 지나가는 한 지점 `display_text` — PCSEC1 H1, D-374)."""
    return display_text(str(value), 120)


SAVE_KIND_OF_CODE = {"DRAFT_LIMIT": "limit", "STORE_CONFLICT": "conflict", "STORE_CORRUPT": "corrupt", "DRAFT_CORRUPT": "record", "STORE_VERSION_UNSUPPORTED": "newer", "STORE_LOCKED": "locked",
                     "DISK_FULL": "io", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io", "FILE_PATH_TOO_LONG": "io", "DATA_DIR_UNSAFE": "io", "MIGRATION_BLOCKED": "io", "BACKUP_FAILED": "io",
                     "STORE_RECOVERY_PENDING": "io", "CONTENT_NOT_FOUND": "notfound", "CONTENT_INVALID": "invalid", "CONFIRMATION_REQUIRED": "other"}
SAVE_SENTENCE_OF_KIND = {"io": "drf_savefail_io", "corrupt": "drf_savefail_corrupt", "newer": "drf_savefail_newer", "limit": "drf_savefail_limit", "conflict": "drf_savefail_conflict", "locked": "drf_savefail_locked", "record": "drf_savefail_record",
                         "notfound": "drf_savefail_notfound", "invalid": "drf_savefail_invalid", "other": "drf_savefail_other"}


class DraftsProvider:
    """초안 작성 화면 데이터 공급자 공통 모양 — 모든 메서드는 작업 스레드에서 불린다(화면 스레드가 아니다). 초안 만들기(`make_draft`)는 **읽기뿐이다**(쓰기·저장·후보 상태 바꾸기 없음).
    저장 기능이 있는 공급자(`saving` 이 참)는 사용자가 `저장`·`열기`·`지우기` 를 눌렀을 때만 부르는 넷을 더 가진다 — 목록(`list_saved`)과 열기(`open_saved`)는 읽기뿐이고 쓰는 것은 저장(`save_draft`)·지우기(`delete_saved`)뿐이다."""
    sample = False
    saving = False

    def make_draft(self, request, progress, cancelled):
        raise NotImplementedError

    def save_draft(self, request, progress, cancelled):
        raise NotImplementedError

    def list_saved(self, progress, cancelled):
        raise NotImplementedError

    def open_saved(self, draft_id, progress, cancelled):
        raise NotImplementedError

    def delete_saved(self, draft_id, progress, cancelled):
        raise NotImplementedError


@lru_cache(maxsize=4096)
def _stage_of(unit):
    """글 조각 하나의 건강 판정 단계 — 주제 엔진의 판정기 `topics.safety.check_text([조각])` 의 단계(같은 조각은 한 번만 계산한다). 읽기·계산뿐이다."""
    from ...topics import safety
    return safety.check_text([unit]).stage


def review_health(*named_units):
    """((이름, 조각들), …) → `HealthReview` — 조각마다 엔진 판정기를 **따로** 불러(글 전체를 한 덩어리로 넣으면 서로 먼 문장의 낱말이 섞여 정상 글이 중지로 읽힌다) 가장 높은 단계와,
    중지(C) 단계인 조각의 앞부분 미리보기(`이름 — …`, 비밀 모양은 가렸다, 최대 `SPOT_LIMIT` 개)를 돌려준다. 후보의 제목·키워드는 서비스가 이미 판정했고(자동 초안 중지) 이것은 **두 번째 방어선**이다:
    초안 서비스가 만든 글·사용자가 적은 선택 입력·고친 글에 건강 효과 단정이 있으면 복사를 막는다. 파일·네트워크·시계를 쓰지 않는다. 판정기의 낱말·표현 한계는 판정기 쪽 몫이다(여기서 고치지 않는다)."""
    top, places = HEALTH_STAGES[0], []
    for name, units in named_units:
        for unit in units:
            if not isinstance(unit, str) or not unit.strip():
                continue
            stage = _stage_of(unit)
            if HEALTH_STAGES.index(stage) > HEALTH_STAGES.index(top):
                top = stage
            if stage == HEALTH_STOP and len(places) < SPOT_LIMIT:
                places.append(f"{name} — {shown(unit, PREVIEW)}")
    return HealthReview(top, tuple(places))


def _pause(seconds, cancelled):
    end = time.monotonic() + seconds
    while seconds and time.monotonic() < end:
        if cancelled():
            raise JobCancelled()
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


class FakeDraftsProvider(DraftsProvider):
    """메모리에서만 일하는 가짜 공급자 — 파일·서비스를 부르지 않는다. 후보는 `source`(가짜 후보 공급자가 가진 엔진 후보 `TopicCandidate` 들을 돌려주는 함수)에서 번호 전체가 같은 것을 찾고,
    서비스(`service/draft_engine.py`)와 같은 순서(안전 판정 중지 거절 → 블로그 정하기 → 생성기)로 초안을 만든다. `fail` 은 만들 때 그대로 던질 실패(시험)."""
    sample = True

    def __init__(self, source=None, delay=0.0, *, fail=None, saving=False, save_fail=None, saved=None):
        self._source, self.delay, self.fail = source or (lambda: ()), delay, fail
        self.calls = []
        self.saving = bool(saving)                                                   # 참이면 `저장`·`저장한 초안` 이 켜진다(메모리에서만 — 앱을 닫으면 사라진다). 기본은 꺼짐
        self.save_fail, self.save_calls, self.saved, self.ticks = save_fail, [], dict(saved or {}), 0

    def make_draft(self, request, progress, cancelled):
        from ...content import candidates as legacy
        from ...content import draft_body as generator
        from ...errors import AppError
        from ...topics import model, safety
        self.calls.append(request)
        _pause(self.delay, cancelled)
        if self.fail is not None:
            raise self.fail
        engine = next((item for item in self._source() if item.candidate_id == request.candidate_id), None)
        if engine is None:
            raise DraftFailure(T["drf_fail_notfound"], code="TOPIC_CANDIDATE_NOT_FOUND", kind="notfound")
        try:
            options = build_options(request.options or {})
        except AppError as error:
            raise option_failure(error) from None
        try:
            old = legacy.Candidate.new(engine.topic, engine.primary_keyword, (engine.channel,), candidate_id=engine.candidate_id, now=engine.created_at, sub_keywords=tuple(engine.secondary_keywords),
                                       post_type=model.to_post_type(engine.content_type), status=engine.work_status)
        except AppError as error:
            raise DraftFailure(T["drf_fail_invalid"], code=error.code, kind="invalid") from None
        report = safety.check_text([old.topic, old.keyword, *old.sub_keywords])
        if report.stop or safety.assess(engine).stop:
            raise DraftFailure(T["drf_refused_desc"], code="CONTENT_INVALID", kind="stopped")
        blog = request.blog or engine.channel
        if blog not in BLOG_NAMES:
            raise DraftFailure(T["drf_channel_desc"], code="DRAFT_OPTION_INVALID", kind="channel")
        try:
            body = generator.build_body(old, None, options, today=SAMPLE_DAY, blog=blog, post_type=request.post_type, channel=PROFILES[blog], safety=report)       # 서비스와 같게: 프로필 파일이 없을 때의 기본 채널 프로필
        except AppError as error:
            raise (option_failure(error) if error.code == "DRAFT_OPTION_INVALID" else DraftFailure(T["drf_fail_invalid"], code=error.code, kind="invalid")) from None
        urls = {key: url for key, _name, url in SAMPLE_BLOGS}
        return DraftResult(engine.candidate_id, body, blog, body.post_type, dict(request.options or {}), tuple((key, name) for key, name, _url in SAMPLE_BLOGS), urls[blog], engine.work_status == legacy.REJECTED, False, False, True)

    # ---- 저장한 초안(메모리에서만) — 서비스(`service/draft_store.py`)와 같은 기록·같은 검사·같은 한도를 쓴다 ----
    def _stamp(self):
        """예시 시각 — 시계를 읽지 않고 저장할 때마다 1분씩 흐른다(같은 입력은 늘 같은 결과)."""
        self.ticks += 1
        return f"{SAMPLE_DAY}T{9 + self.ticks // 60:02d}:{self.ticks % 60:02d}:00Z"

    def save_draft(self, request, progress, cancelled):
        import dataclasses
        from ...content import saved_draft as sd
        from ...errors import AppError
        from ...security import scan
        self.save_calls.append(request)
        _pause(self.delay, cancelled)
        if self.save_fail is not None:
            raise self.save_fail
        stamp = self._stamp()
        try:
            draft_id = request.draft_id or sd.make_draft_id(stamp, request.candidate_id, request.blog, request.title, request.body)
            base = sd.BaseDraft.build(**request.base) if request.base else None
            draft = sd.SavedDraft.build(draft_id=draft_id, revision=1, created_at=stamp, updated_at=stamp, title=request.title, body=request.body, core_keywords=request.core_keywords,
                                        sub_keywords=request.sub_keywords, tags=request.tags, category=request.category, summary=request.summary, candidate_id=request.candidate_id, topic=request.topic,
                                        blog=request.blog, post_type_choice=request.post_type_choice, post_type=request.post_type, options=request.options, base=base)
            found = scan.scan_fields(draft.text_fields()) + scan.scan_fields(draft.base_fields())        # 고친 칸과 만든 초안 칸 어디서든 — 서비스와 같다(D-368)
            if found:
                raise secret_failure(found)
            draft.to_text()
            previous = self.saved.get(draft_id)
            if previous is None and len(self.saved) >= sd.MAX_SAVED:
                raise AppError("DRAFT_LIMIT", {"이유": f"저장한 초안이 {sd.MAX_SAVED}편이에요"})
            if previous is not None and request.expected_revision is not None and previous.revision != request.expected_revision:
                raise AppError("STORE_CONFLICT", {"항목": "저장한 초안"})
            if previous is not None:
                final = dataclasses.replace(draft, revision=previous.revision + 1, created_at=previous.created_at)
                if dataclasses.replace(final, revision=previous.revision, updated_at=previous.updated_at) == previous:
                    final = previous
            elif request.expected_revision is not None:
                final = dataclasses.replace(draft, revision=request.expected_revision + 1)
            else:
                final = draft
        except AppError as error:
            raise save_failure(error) from None
        self.saved[draft_id] = final
        return SavedOutcome(final.draft_id, final.revision, final.updated_at)

    def list_saved(self, progress, cancelled):
        from ...content import saved_draft as sd
        _pause(self.delay, cancelled)
        ordered = sorted(self.saved.values(), key=lambda item: (item.updated_at, item.draft_id), reverse=True)
        return SavedListing(tuple(SavedRow(item.draft_id, item.title, item.topic, item.blog, item.updated_at, sd.body_chars(item.body), item.revision) for item in ordered), ())

    def open_saved(self, draft_id, progress, cancelled):
        from ...errors import AppError
        _pause(self.delay, cancelled)
        draft = self.saved.get(draft_id)
        if draft is None:
            raise save_failure(AppError("CONTENT_NOT_FOUND", {"항목": "저장한 초안"}))
        found = bool(draft.candidate_id) and any(item.candidate_id == draft.candidate_id for item in self._source())
        candidate = "none" if not draft.candidate_id else ("found" if found else "missing")
        urls = {key: url for key, _name, url in SAMPLE_BLOGS}
        result = restored_result(draft, names=tuple((key, name) for key, name, _url in SAMPLE_BLOGS), blog_url=urls.get(draft.blog, ""), address="profile", sample=True)
        return OpenedResult(result, draft.draft_id, draft.revision, draft.updated_at, candidate, False, draft.topic, draft.title, draft.body, draft.post_type_choice)

    def delete_saved(self, draft_id, progress, cancelled):
        from ...errors import AppError
        _pause(self.delay, cancelled)
        if draft_id not in self.saved:
            raise save_failure(AppError("CONTENT_NOT_FOUND", {"항목": "저장한 초안"}))
        del self.saved[draft_id]
        return draft_id


__all__ = ["DraftFailure", "DraftRequest", "DraftResult", "DraftTarget", "DraftsProvider", "FakeDraftsProvider", "KINDS_OF_FAILURE", "OpenedResult", "RestoredBody", "SaveRequest", "SavedListing",
           "SavedOutcome", "SavedRow", "option_failure", "restored_result", "review_health", "save_failure", "secret_failure"]
