"""주제 후보 화면이 아는 값과 공급자의 모양 + 가짜 공급자 — 화면은 이 모양만 안다. 실제 서비스(`service/topics.py`)는 얇은 어댑터(`ui/candidates_adapter.py`)가 같은 모양으로 맞춘다.

이 화면은 **`후보 만들기` 확인창에서 `만들기` 를 눌렀을 때만** 후보 보관함에 쓴다 — 쓰는 길은 공급자의 `make_candidates` 하나뿐이다(읽기 `load_candidates` 와 미리 보기 `preview_make` 는 파일도 폴더도 만들지 않는다).
가짜 공급자(`FakeCandidatesProvider` — `--sample`·시험·사진)는 **메모리에서만** 일한다: 파일·보관소·서비스를 부르지 않으므로 만들어도 이 PC 에 아무것도 남지 않는다. 제목·키워드·이름은 모두 지어낸 예시다(실제 후보·블로그가 아니다).
후보 한 건은 엔진의 `TopicCandidate` 그대로다 — 점수·구간·안전 표시는 엔진이 정한 값이고 이 화면은 새 점수·새 구간 규칙을 만들지 않는다. PySide6 도 파일도 모른다.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from ...topics import channels as ch
from ...topics import hold, model, safety
from ...topics import score as sc
from .jobs import JobCancelled, JobFailure
from .text import T

KINDS_OF_FAILURE = ("busy", "disk", "io", "newer", "corrupt", "invalid", "other")
SCENARIOS = ("normal", "empty", "no_store", "old_structure", "error", "many", "lacking")
LACKS = ("no_channel", "no_seed", "full", "none")                       # 후보를 만들 수 없는 까닭 — 일하는 채널이 없다·승인한 Seed 가 없다·남은 자리가 없다·그 밖에 새로 만들 것이 없다
STORE_STATES = ("missing", "empty", "ready", "old_structure")            # 서비스의 보관함 상태(`service/topics.py` 의 `STORE_*` 와 같은 이름)
SAMPLE_STAMP = "2026-11-05T09:00:00Z"
FAKE_MAKE = 4                                                            # 가짜 공급자가 `만들기` 때 더하는 후보 수


class CandidateFailure(JobFailure):
    """주제 후보의 실패 — 쉬운 문장(`user_message`)과 진단용 코드, 그리고 화면이 다르게 다룰 종류(`kind`: `busy` 다른 창이 씀 · `disk` · `io` 읽기 전용·쓰기 실패 · `newer` 더 새 판 · `corrupt` · `invalid` 설정 파일 · `other`)."""

    def __init__(self, user_message, code="", *, kind="other", retryable=True):
        super().__init__(user_message, code, retryable)
        self.kind = kind if kind in KINDS_OF_FAILURE else "other"


@dataclass(frozen=True)
class ChannelInfo:
    """채널 하나 — 이름은 채널 프로필의 표시 이름(런타임에 읽는다)이고 코드·시험·문서에 실제 이름이 없다."""
    key: str                                                 # 엔진의 채널 이름(`naver_a` …)
    name: str = ""                                           # 표시 이름
    preset: object = None                                    # 색 프리셋 이름 또는 None(채널 배지·아바타에만 쓴다)
    enabled: object = None                                   # 후보 생성이 켜져 있나(True·False, 읽지 못했으면 None)
    weights: tuple = ()                                      # ((항목 이름, 가중치), …) — 점수 구성의 작은 글


@dataclass(frozen=True)
class SeedInfo:
    keyword: str
    major: str = ""
    minor: str = ""
    state: str = ""


@dataclass(frozen=True)
class CandidateRow:
    ordinal: int                                             # 보관함의 저장 순서(1부터)
    candidate: object                                        # `topics.model.TopicCandidate`
    stop: bool = False                                       # 자동 초안 중지(서비스가 계산한 값)


@dataclass(frozen=True)
class CandidatesData:
    rows: tuple = ()                                         # CandidateRow — 점수가 가중치로 다시 계산한 값과 같은 후보만(저장한 순서)
    store: str = "missing"                                   # `STORE_STATES`
    channels: tuple = ()                                     # ChannelInfo — 채널 순서
    seeds: tuple = ()                                        # ((Seed 번호, SeedInfo), …) — 후보가 가리키는 Seed
    skipped: int = 0                                         # 점수를 확인할 수 없어 뺀 후보 수(홈의 `점수를 확인할 수 없어 뺀 후보` 와 같은 규칙)
    total: int = 0                                           # 보관함의 전체 후보 수(뺀 것 포함)
    sample: bool = False

    def channel_map(self):
        return {item.key: item for item in self.channels}

    def seed_map(self):
        return dict(self.seeds)


@dataclass(frozen=True)
class ChannelPreview:
    """후보 만들기 미리 보기의 채널 한 줄 — 후보 생성이 켜진 채널만 있다."""
    key: str
    name: str
    new: int                                                 # 새로 만들 후보 수
    remaining: object = None                                 # 남은 자리(모르면 None)
    target: int = 0
    duplicates: int = 0                                      # 이미 있는 후보와 같아서 안 만든 수
    reasons: tuple = ()                                      # 건너뛰는 까닭의 이름들(서비스의 고정 문장 제목)


@dataclass(frozen=True)
class MakePreview:
    """후보 만들기 미리 보기 — **아무것도 쓰지 않았다**. 새 후보가 하나 이상이면(`can_make`) 확인창 뒤에 만들 수 있고, 아니면 `lacks` 가 무엇이 모자란지 말한다."""
    store: str = "missing"
    channels: tuple = ()                                     # ChannelPreview — 후보 생성이 켜진 채널
    total_new: int = 0
    seeds_used: int = 0                                      # 새 후보가 나온 Seed 수
    seeds_proposed: int = 0                                  # 승인 전이라 쓰이지 않는 Seed 수
    lacks: tuple = ()                                        # `LACKS` 중
    sample: bool = False

    @property
    def can_make(self):
        return self.total_new > 0

    @property
    def duplicates(self):
        return sum(item.duplicates for item in self.channels)


@dataclass(frozen=True)
class MakeOutcome:
    made: int = 0                                            # 새로 저장한 후보 수
    duplicates: int = 0                                      # 같은 후보라 건너뛴 수
    withheld: int = 0                                        # 키·토큰 모양 글이 들어 있어 저장하지 않은 후보 수


class CandidatesProvider:
    """주제 후보 화면 데이터 공급자 공통 모양 — 모든 메서드는 작업 스레드에서 불린다(화면 스레드가 아니다). 읽기는 `load_candidates`·`preview_make`, **쓰기는 `make_candidates` 하나**(사용자가 확인창에서 `만들기` 를 눌렀을 때만)."""
    sample = False

    def load_candidates(self, progress, cancelled):
        raise NotImplementedError

    def preview_make(self, progress, cancelled):
        raise NotImplementedError

    def make_candidates(self, preview, progress, cancelled):
        raise NotImplementedError


def _pause(seconds, cancelled):
    end = time.monotonic() + seconds
    while seconds and time.monotonic() < end:
        if cancelled():
            raise JobCancelled()
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


# ---- 가짜 후보(예시) — 제목·키워드·이름은 모두 지어낸 것이다 --------------------------------------------------------------------------------
PROFILES = {profile.key: profile for profile in ch.default_profiles()}
SAMPLE_NAMES = {"naver_a": ("예시 블로그 가", "warm_lifestyle"), "naver_b": ("예시 블로그 나", "cool_technology")}
FACTOR_ROWS = {                       # (채널 적합도·작성 가능성·차별성·시기·근거·수익화) — 평가하지 못한 항목은 None(0점이 아니다)
    "top": (95, 92, 88, 90, 90, 92), "high": (88, 90, 80, 84, 82, 85), "edge": (85, 90, None, None, 80, 70), "good": (75, 80, 70, 70, 74, 76), "low_good": (70, 72, 66, 66, 68, 70),
    "hold": (62, 66, 58, 60, 60, 58), "hold_low": (52, 55, 50, 50, 52, 52), "excluded": (40, 45, 35, 30, 40, 35), "none": (None,) * 6,
}


def build_candidate(number, topic, channel, factors, *, cluster="small-appliances", status="NEW", keywords=("예시 낱말 가",), reasons=None, seed_id=None, source="seed", kind="evergreen", **extra):
    """검증을 모두 통과하는 예시 후보 하나 — 점수는 그 채널의 가중치로 계산한 값이라 서비스의 점수 확인(`check_candidate_score`)을 통과한다."""
    profile = PROFILES[channel]
    card = sc.score(profile, sc.Factors(**dict(zip(ch.FACTOR_NAMES, FACTOR_ROWS[factors], strict=True)))).card
    expires = hold.expiry_for(card.band, SAMPLE_STAMP)
    values = dict(candidate_id=f"tc-{channel}-seed-{hashlib.sha256(f'예시 후보 {number}'.encode()).hexdigest()[:16]}", source_type=source, candidate_type=kind, channel=channel, language=profile.language, topic=topic, primary_keyword=keywords[0],
                  secondary_keywords=tuple(keywords[1:]), search_intent="how_to", content_type="how_to_guide", topic_cluster=cluster, topic_angle="care-method", target_reader="예시 독자 한 명",
                  created_at=SAMPLE_STAMP, seed_id=seed_id, scores=card, selection_reasons=("예시 이유 하나 — 시기가 맞고 쓸 거리가 충분해요", "예시 이유 둘") if reasons is None else tuple(reasons),
                  work_status=status, review_expires_at=expires)
    values.update(extra)
    return model.TopicCandidate(**values)


def _sample_candidates(scenario):
    """가짜 후보 — `normal` 은 열네 개(구간 넷과 점수 계산 전·작업 상태 다섯·주의·자동 초안 중지·관심도 있음·키워드 많음·이유 없음·Seed 없음 포함), `many` 는 130개, `empty`·`no_store`·`old_structure`·`error`·`lacking` 은 없다."""
    if scenario != "normal" and scenario != "many":
        return []
    if scenario == "many":
        rows = []
        bands = ("top", "high", "good", "low_good", "hold", "excluded", "none")
        channels = ("naver_a", "naver_b", "naver_a", "naver_b", "blogger_ko", "github_pages")
        for number in range(1, 131):
            rows.append(build_candidate(number, f"예시 후보 {number:03d}", channels[number % len(channels)], bands[number % len(bands)], cluster=f"cluster-{number % 7}", keywords=(f"예시 낱말 {number:03d}", "예시 보조 가")))
        return rows
    trend = dict(trend_status="rising", trend_ratio=73, trend_period="최근 30일", trend_compared_group=("예시 낱말 가", "예시 비교 나"), trend_queried_on="2026-11-04", data_status="sufficient")
    return [
        build_candidate(1, "예시 후보 가 — 순서대로 따라 하는 안내", "naver_a", "top", seed_id="EX001", keywords=("예시 낱말 가", "예시 보조 가", "예시 보조 나", "예시 보조 다", "예시 보조 라"), **trend),
        build_candidate(2, "예시 후보 나 — 고르는 기준 정리", "naver_a", "high", cluster="pc-parts", seed_id="EX002", keywords=("예시 낱말 나", "예시 보조 가"), monetization_tags=("pc_parts",)),
        build_candidate(3, "예시 영양제 고르는 기준", "naver_a", "edge", cluster="daily-problem-solving", seed_id="EX003", keywords=("예시 영양제",), safety_flags=("health_check",)),
        build_candidate(4, "예시 영양제 먹으면 바로 낫는 방법", "naver_b", "good", cluster="daily-problem-solving", seed_id="EX003", status="REVIEW", keywords=("예시 영양제", "예시 보조 가"), safety_flags=("health_check",)),
        build_candidate(5, "예시 후보 다 — 자주 묻는 것 모음", "naver_b", "high", cluster="local-ai", seed_id="EX004", status="SELECTED", keywords=("예시 낱말 다", "예시 보조 나")),
        build_candidate(6, "예시 후보 라 — 비교해서 보는 방법", "naver_b", "low_good", cluster="local-ai", seed_id="EX004", keywords=("예시 낱말 라",)),
        build_candidate(7, "예시 후보 마 — 처음 시작하는 순서", "naver_a", "good", seed_id="EX001", keywords=("예시 낱말 마", "예시 보조 가")),
        build_candidate(8, "예시 후보 바 — 한눈에 보는 정리", "naver_b", "hold", cluster="pc-parts", seed_id="EX002", keywords=("예시 낱말 바",)),
        build_candidate(9, "예시 후보 사 — 점수가 낮은 예", "naver_b", "excluded", cluster="local-ai", status="REJECTED", seed_id="EX004", keywords=("예시 낱말 사",)),
        build_candidate(10, "예시 후보 아 — 점수 계산 전인 예", "naver_a", "none", seed_id="EX001", keywords=("예시 낱말 아",), reasons=()),
        build_candidate(11, "예시 후보 자 — 보류 구간의 예", "naver_a", "hold_low", status="HOLD", seed_id="EX001", keywords=("예시 낱말 자", "예시 보조 가")),
        build_candidate(12, "예시 후보 차 — 글 하나에서 이어 쓰는 후보", "naver_a", "good", source="follow_up", kind="follow_up", keywords=("예시 낱말 차", "예시 보조 나")),
        build_candidate(13, "예시 후보 카 — 다른 채널의 예", "blogger_ko", "high", cluster="platform-policy", seed_id="EX002", keywords=("예시 낱말 카",)),
        build_candidate(14, "예시 후보 타 — 또 다른 채널의 예", "github_pages", "good", cluster="platform-policy", seed_id="EX002", keywords=("예시 낱말 타",)),
    ]


def _sample_channels(enabled=("naver_a", "naver_b")):
    out = []
    for key in ch.CHANNELS:
        name, preset = SAMPLE_NAMES.get(key, (PROFILES[key].display_name, None))
        out.append(ChannelInfo(key, name, preset, key in enabled, tuple((factor, PROFILES[key].weights[factor]) for factor in ch.FACTOR_NAMES)))
    return tuple(out)


SAMPLE_SEEDS = (("EX001", SeedInfo("예시 낱말 가", "예시 대분류 하나", "예시 중분류 하나", "active")), ("EX002", SeedInfo("예시 낱말 나", "예시 대분류 둘", "예시 중분류 둘", "active")),
                ("EX003", SeedInfo("예시 영양제", "예시 대분류 셋", "예시 중분류 셋", "active")), ("EX004", SeedInfo("예시 낱말 라", "예시 대분류 하나", "예시 중분류 셋", "active")))


class FakeCandidatesProvider(CandidatesProvider):
    """메모리에서만 일하는 가짜 공급자 — 후보 만들기도 메모리 안에서만 바뀐다(파일·서비스를 부르지 않는다). `fail` 은 `{메서드 이름: 실패}` 로 그 메서드를 정해 둔 실패로 끝나게 한다(시험)."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0, *, fail=None, lacks=None):
        if scenario not in SCENARIOS:
            raise ValueError(scenario)
        self.scenario, self.delay, self.fail, self.forced_lacks = scenario, delay, dict(fail or {}), lacks
        self.candidates = _sample_candidates(scenario)
        self.store = {"no_store": "missing", "old_structure": "old_structure"}.get(scenario, "ready")
        self.calls = []
        self.made_batches = 0

    def _data(self):
        rows = tuple(CandidateRow(number, item, safety.assess(item).stop) for number, item in enumerate(self.candidates, start=1))      # 자동 초안 중지는 서비스(`list_candidates`)와 같은 순수 함수가 정한다
        return CandidatesData(rows, self.store, _sample_channels(), SAMPLE_SEEDS, 0, len(rows), True)

    def _enter(self, name, cancelled):
        self.calls.append(name)
        _pause(self.delay, cancelled)
        if name in self.fail:
            raise self.fail[name]

    def load_candidates(self, progress, cancelled):
        self._enter("load", cancelled)
        if self.scenario == "error":
            raise CandidateFailure(T["cand_error_desc"], code="SAMPLE_CANDIDATES_UNREADABLE", kind="corrupt")
        return self._data()

    def preview_make(self, progress, cancelled):
        self._enter("preview", cancelled)
        lacks = self.forced_lacks if self.forced_lacks is not None else (("no_seed",) if self.scenario == "lacking" else ())
        if lacks:
            return MakePreview(self.store, (), 0, 0, 2 if "no_seed" in lacks else 0, tuple(lacks), True)
        rows = tuple(ChannelPreview(key, SAMPLE_NAMES[key][0], 2, 18, 20, 0, ("조합 제외", "목표 개수 초과")) for key in ("naver_a", "naver_b"))
        return MakePreview(self.store, rows, FAKE_MAKE, 3, 1, (), True)

    def make_candidates(self, preview, progress, cancelled):
        self._enter("make", cancelled)
        if not preview.can_make:
            raise CandidateFailure(T["cand_fail_other"], code="CONTENT_INVALID", kind="invalid")
        self.made_batches += 1
        start = 100 * self.made_batches
        added = [build_candidate(start + number, f"예시 새 후보 {self.made_batches}-{number}", "naver_a" if number % 2 else "naver_b", "high", seed_id="EX001", keywords=(f"예시 새 낱말 {number}",)) for number in range(1, FAKE_MAKE + 1)]
        self.candidates = [*self.candidates, *added]
        self.store = "ready"
        return MakeOutcome(len(added), 0, 0)


__all__ = ["CandidateFailure", "CandidateRow", "CandidatesData", "CandidatesProvider", "ChannelInfo", "ChannelPreview", "FakeCandidatesProvider", "MakeOutcome", "MakePreview", "SeedInfo", "build_candidate"]
