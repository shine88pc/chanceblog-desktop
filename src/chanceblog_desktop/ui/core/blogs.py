"""블로그 관리 화면(P4b)이 아는 값과 공급자의 모양 + 가짜 공급자 — 화면은 이 모양만 안다. 실제 서비스(`service/blog_profiles.py`)는 얇은 어댑터(`ui/blogs_adapter.py`)가 같은 모양으로 맞춘다.

이 화면은 **이 앱에서 처음으로 파일에 쓴다**: 쓰는 일은 공급자의 `save_blog`·`clone_blog`·`clear_blog` 셋뿐이고 사용자가 저장·복제·삭제를 눌렀을 때만 불린다(읽기 `load_blog` 는 파일도 폴더도 만들지 않는다).
가짜 공급자(`FakeBlogsProvider` — `--sample`·시험·사진)는 **메모리에서만** 일한다: 파일·보관소·서비스를 부르지 않으므로 저장해도 이 PC 에 아무것도 남지 않는다. 이름·아이디는 모두 지어낸 예시다(실제 블로그 이름·아이디가 아니다).
PySide6 도 파일도 모른다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace

from ...topics import channels as ch
from . import blog_form as bf
from .jobs import JobCancelled, JobFailure
from .text import T

KINDS_OF_FAILURE = ("conflict", "busy", "invalid", "disk", "io", "corrupt", "other")
SCENARIOS = ("normal", "empty", "error")
VERSION_MISSING = "missing"                                  # 프로필 파일이 아직 없을 때의 판(서비스의 `VERSION_MISSING` 과 같다)


class BlogFailure(JobFailure):
    """블로그 관리의 실패 — 쉬운 문장(`user_message`)과 진단용 코드, 그리고 화면이 다르게 다룰 종류(`kind`: `conflict` 낡은 판 · `busy` 다른 창이 잠금 · `invalid` 칸 값 · `disk` · `io` · `corrupt` · `other`).
    `problems` 는 `{칸 이름: 문제 이름}`(`invalid` 일 때 어느 칸이 왜 안 되는지 — 칸 옆에 문장으로 보인다)."""

    def __init__(self, user_message, code="", *, kind="other", problems=None, retryable=True):
        super().__init__(user_message, code, retryable)
        self.kind = kind if kind in KINDS_OF_FAILURE else "other"
        self.problems = dict(problems or {})


@dataclass(frozen=True)
class SlotRead:
    """슬롯 하나가 지금 가진 폼 칸의 값(저장된 값). 칸 이름은 서비스의 채널 프로필 칸과 같다 — 엔진 칸(점수 가중치 등)은 화면이 모르므로 없다."""
    key: str
    display_name: str = ""
    blog_ref: str = ""
    language: str = "ko"
    generation_enabled: bool = False
    alias: str = ""
    channel_role: str = ""
    main_topics: tuple = ()
    audience: str = ""
    tone: str = ""
    categories: tuple = ()
    intro: str = ""
    color_preset: object = None
    profile_image: str = ""
    cover_image: str = ""
    monetization_focus: tuple = ()
    sample: bool = False                                     # 가짜(예시) 값인가

    @property
    def registered(self):
        return bool(self.blog_ref)

    def raw(self):
        return bf.raw_from_profile(self)


def slot_from_profile(profile, *, sample=False):
    """채널 프로필(또는 같은 이름의 칸을 가진 값) → `SlotRead`."""
    names = {spec.name for spec in bf.FIELDS} | {"display_name"}
    return SlotRead(profile.key, sample=sample, **{name: getattr(profile, name) for name in names})


@dataclass(frozen=True)
class BlogsData:
    slots: tuple = ()                                        # SlotRead 다섯 개(슬롯 순서)
    version: str = VERSION_MISSING                           # 읽은 때의 판 — 쓸 때 되돌려 준다(다른 곳이 먼저 바꿨는지 보려고)
    state: str = "missing"                                   # missing(파일이 없음 — 기본 프로필) · ok
    sample: bool = False

    def by_key(self):
        return {slot.key: slot for slot in self.slots}


@dataclass(frozen=True)
class BlogsOutcome:
    kind: str                                                # saved · unchanged
    data: BlogsData                                          # 쓴 뒤의 상태
    changed: tuple = ()                                      # 바뀐 슬롯들


class BlogsProvider:
    """블로그 관리 화면 데이터 공급자 공통 모양 — 모든 메서드는 작업 스레드에서 불린다(화면 스레드가 아니다). 읽기는 `load_blogs`, 쓰기는 나머지 셋(사용자가 눌렀을 때만)."""
    sample = False

    def load_blogs(self, progress, cancelled):
        raise NotImplementedError

    def save_blog(self, key, fields, version, progress, cancelled):
        raise NotImplementedError

    def clone_blog(self, source, target, version, progress, cancelled):
        raise NotImplementedError

    def clear_blog(self, key, version, progress, cancelled):
        raise NotImplementedError


def _pause(seconds, cancelled):
    end = time.monotonic() + seconds
    while seconds and time.monotonic() < end:
        if cancelled():
            raise JobCancelled()
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


def _sample_slots(scenario):
    """가짜 슬롯 다섯 — 예시 이름뿐이다. `empty` 는 아무것도 등록하지 않은 처음 모습, `normal` 은 네이버 A·B 와 Blogger 한글이 등록된 모습."""
    base = {profile.key: slot_from_profile(profile, sample=True) for profile in ch.default_profiles()}
    if scenario == "empty":
        return base
    base["naver_a"] = replace(base["naver_a"], display_name="예시 블로그 가", blog_ref="example-blog-a", alias="예시 별명", channel_role="예시 역할 — 생활 정보", main_topics=("예시 주제 하나", "예시 주제 둘", "예시 주제 셋"),
                              audience="예시 독자", tone="친절한 설명체", categories=("예시 분류 1", "예시 분류 2"), intro="예시 소개글 한 줄이에요.", color_preset="warm_lifestyle")
    base["naver_b"] = replace(base["naver_b"], display_name="예시 블로그 나", blog_ref="example-blog-b", alias="", channel_role="예시 역할 — 기술 기록", main_topics=("예시 주제 넷",), audience="예시 독자 둘",
                              tone="", categories=("예시 분류 3",), intro="", color_preset="cool_technology")
    base["blogger_ko"] = replace(base["blogger_ko"], display_name="예시 블로그 다", blog_ref="example-blog-c")
    return base


class FakeBlogsProvider(BlogsProvider):
    """메모리에서만 일하는 가짜 공급자 — 저장·복제·삭제도 메모리 안에서만 바뀐다(파일·서비스를 부르지 않는다). 규칙은 서비스와 같다(시험이 같은 일을 둘에 해 보고 견준다)."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0):
        if scenario not in SCENARIOS:
            raise ValueError(scenario)
        self.scenario, self.delay = scenario, delay
        self.slots = _sample_slots(scenario)
        self.revision = 1
        self.calls = []

    def _data(self):
        return BlogsData(tuple(self.slots[key] for key in bf.SLOTS), str(self.revision), "ok", True)

    def _enter(self, name, version, cancelled):
        self.calls.append(name)
        _pause(self.delay, cancelled)
        if version is not None and str(self.revision) != version:
            raise BlogFailure(T["blogs_fail_conflict"], code="STORE_CONFLICT", kind="conflict")

    def _done(self, before):
        changed = tuple(key for key in bf.SLOTS if before[key] != self.slots[key])
        if changed:
            self.revision += 1
        return BlogsOutcome("saved" if changed else "unchanged", self._data(), changed)

    def load_blogs(self, progress, cancelled):
        self.calls.append("load")
        _pause(self.delay, cancelled)
        if self.scenario == "error":
            raise BlogFailure(T["blogs_error_desc"], code="SAMPLE_BLOGS_UNREADABLE", kind="corrupt")
        return self._data()

    def save_blog(self, key, fields, version, progress, cancelled):
        self._enter("save", version, cancelled)
        before = dict(self.slots)
        extra = tuple(tag for tag in before[key].monetization_focus if tag not in bf.TAG_ORDER)
        problems = bf.check_typed(key, fields, extra)
        if problems:
            raise BlogFailure(T["blogs_fail_invalid"], code="CONTENT_INVALID", kind="invalid", problems=problems)
        self.slots[key] = replace(before[key], **{name: value for name, value in fields.items() if name in {spec.name for spec in bf.fields_for(key)}})
        return self._done(before)

    def clone_blog(self, source, target, version, progress, cancelled):
        self._enter("clone", version, cancelled)
        before = dict(self.slots)
        allowed, _reason, found = bf.clone_state({key: slot.raw() for key, slot in before.items()}, source)
        if not allowed or found != target:
            raise BlogFailure(T["blogs_fail_invalid"], code="CONTENT_INVALID", kind="invalid")
        names = {spec.name for spec in bf.fields_for(target)}
        self.slots[target] = replace(before[target], **{name: getattr(before[source], name) for name in names})
        return self._done(before)

    def clear_blog(self, key, version, progress, cancelled):
        self._enter("clear", version, cancelled)
        before = dict(self.slots)
        base = next(slot_from_profile(profile, sample=True) for profile in ch.default_profiles() if profile.key == key)
        self.slots[key] = replace(before[key], **{spec.name: getattr(base, spec.name) for spec in bf.fields_for(key)})
        return self._done(before)


__all__ = ["BlogFailure", "BlogsData", "BlogsOutcome", "BlogsProvider", "FakeBlogsProvider", "SlotRead", "slot_from_profile"]
