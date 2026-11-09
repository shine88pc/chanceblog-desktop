"""초안 작성 화면이 아는 값과 공급자의 모양 + 가짜 공급자 — 화면은 이 모양만 안다. 실제 서비스(`service/draft_engine.py`)는 얇은 어댑터(`ui/drafts_adapter.py`)가 같은 모양으로 맞춘다.

이 화면은 **아무것도 저장하지 않는다**(파일·보관함·엔진 DB·글 보관함 어디에도) — 공급자는 읽기 하나(`make_draft`)뿐이고 복사는 화면 틀이 클립보드에 넣는다. 초안은 메모리에만 있다.
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
from .text import T

KINDS_OF_FAILURE = ("stopped", "channel", "notfound", "option", "invalid", "io", "newer", "corrupt", "other")
SAMPLE_DAY = "2026-11-05"                                                          # 가짜 공급자가 쓰는 '오늘'(시계를 읽지 않는다 — 같은 입력은 늘 같은 초안)
SAMPLE_BLOGS = (("naver_a", "예시 블로그 가", "https://blog.naver.com/example-blog-a"), ("naver_b", "예시 블로그 나", "https://blog.naver.com/example-blog-b"))


class DraftFailure(JobFailure):
    """초안 만들기의 실패 — 쉬운 문장(`user_message`)과 진단용 코드, 그리고 화면이 다르게 다룰 종류: `stopped` 자동 초안 중지 후보 · `channel` 네이버가 아닌 채널 · `notfound` 후보가 보관함에 없다 · `option` 선택 입력의 한 칸이 틀렸다(`field` 가 그 칸) ·
    `invalid` 후보의 글을 초안에 쓸 수 없다 · `io`·`newer`·`corrupt` 읽기 오류 · `other`."""

    def __init__(self, user_message, code="", *, kind="other", field="", retryable=True):
        super().__init__(user_message, code, retryable)
        self.kind = kind if kind in KINDS_OF_FAILURE else "other"
        self.field = field if isinstance(field, str) else ""


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


class DraftsProvider:
    """초안 작성 화면 데이터 공급자 공통 모양 — 모든 메서드는 작업 스레드에서 불린다(화면 스레드가 아니다). **읽기 하나뿐이다**(쓰기·저장·후보 상태 바꾸기 없음)."""
    sample = False

    def make_draft(self, request, progress, cancelled):
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

    def __init__(self, source=None, delay=0.0, *, fail=None):
        self._source, self.delay, self.fail = source or (lambda: ()), delay, fail
        self.calls = []

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


__all__ = ["DraftFailure", "DraftRequest", "DraftResult", "DraftTarget", "DraftsProvider", "FakeDraftsProvider", "KINDS_OF_FAILURE", "option_failure", "review_health"]
