"""Seed 관리 화면이 아는 값과 공급자의 모양 + 가짜 공급자 — 화면은 이 모양만 안다. 실제 서비스(`service/seed_manage.py`)는 얇은 어댑터(`ui/seeds_adapter.py`)가 같은 모양으로 맞춘다.

이 화면은 **사용자가 승인·바꾸기·저장·등록·불러오기를 눌렀을 때만** `seeds.json` 에 쓴다: 쓰는 일은 공급자의 `set_state`·`set_states`·`edit_seed`·`create_seed`·`apply_import` 다섯뿐이다(읽기 `load_seeds` 와 미리 보기 `preview_import` 는 파일도 폴더도 만들지 않는다).
가짜 공급자(`FakeSeedsProvider` — `--sample`·시험·사진)는 **메모리에서만** 일한다: 파일·보관소·서비스를 부르지 않으므로 바꿔도 이 PC 에 아무것도 남지 않는다. 낱말·분류는 모두 지어낸 예시다(실제 Seed 가 아니다).
규칙은 서비스와 같은 `Seed` 생성자·`TRANSITIONS`·`change_state` 가 심판이다(시험이 같은 일을 둘에 해 보고 견준다). PySide6 도 파일도 모른다.
"""
from __future__ import annotations

import dataclasses
import re
import time
from dataclasses import dataclass

from ...content.candidates import keyword_key
from ...errors import AppError
from ...topics import channels as ch
from ...topics import seeds as sd
from .jobs import JobCancelled, JobFailure
from .text import T

KINDS_OF_FAILURE = ("conflict", "busy", "invalid", "disk", "io", "corrupt", "other")
SCENARIOS = ("normal", "empty", "error", "many")
IMPORT_MODES = ("ok", "blocked", "none", "unreadable")
VERSION_MISSING = "missing"                                  # Seed 파일이 아직 없을 때의 판(서비스의 `VERSION_MISSING` 과 같다)
SAMPLE_DAY = "2026-11-02"                                    # 예시 데이터의 '오늘'
MANUAL_PREFIX = "M"
DEFAULT_GENERATION = tuple((code, code in ("naver_a", "naver_b")) for code in ch.CHANNELS)      # 처음 PC 의 채널별 후보 생성(네이버 A·B 만 켜짐)


class SeedFailure(JobFailure):
    """Seed 관리의 실패 — 쉬운 문장(`user_message`)과 진단용 코드, 그리고 화면이 다르게 다룰 종류(`kind`: `conflict` 낡은 판 · `busy` 다른 창이 잠금 · `invalid` 칸 값 · `disk` · `io` · `corrupt` · `other`).
    `problems` 는 `{칸 이름: 문제 이름}`(`invalid` 일 때 어느 칸이 왜 안 되는지 — 칸 옆에 문장으로 보인다)."""

    def __init__(self, user_message, code="", *, kind="other", problems=None, retryable=True):
        super().__init__(user_message, code, retryable)
        self.kind = kind if kind in KINDS_OF_FAILURE else "other"
        self.problems = dict(problems or {})


@dataclass(frozen=True)
class SeedsData:
    seeds: tuple = ()                                        # `topics.seeds.Seed` — 파일 순서
    version: str = VERSION_MISSING                           # 읽은 때의 판 — 쓸 때 되돌려 준다(다른 곳이 먼저 바꿨는지 보려고)
    state: str = "missing"                                   # missing(파일이 없음 — 빈 목록) · ok
    today: str = ""                                          # 기준일(YYYY-MM-DD) — '쉬게 할까요' 계산에 쓴 날
    idle: tuple = ()                                         # ((씨앗 번호, 안 쓴 날수), …) — 180일 넘게 선택하지 않은 사용 중 씨앗(계절형 제외). 제안뿐이다
    generation: tuple = DEFAULT_GENERATION                   # ((채널, 켜짐·꺼짐·None(읽지 못함)), …)
    sample: bool = False

    def by_id(self):
        return {seed.seed_id: seed for seed in self.seeds}

    def idle_days(self):
        return dict(self.idle)

    def generation_map(self):
        return dict(self.generation)


@dataclass(frozen=True)
class ImportInfo:
    """제안 파일 미리 보기(아무것도 쓰지 않았다) — 개수·건너뜀·거절 사유·채널별 쓸 수 있게 될 수. `handle` 은 등록할 때 되돌려 주는 값(미리 본 새 씨앗들 — 화면은 열어 보지 않는다)."""
    total: int = 0
    new_count: int = 0
    existing: int = 0
    skipped: tuple = ()                                      # ((번호, 이유), …)
    rejected: tuple = ()
    notes: tuple = ()
    per_channel: tuple = ()                                  # ((채널, 수, 후보 생성 켜짐), …)
    kept_copy: bool = False                                  # 옛 모양(판 1) 파일의 사본을 남기게 되나(미리 보기에서는 모른다 — 늘 False)
    version: str = VERSION_MISSING                           # 미리 본 때의 판
    handle: object = ()
    sample: bool = False

    @property
    def blocked(self):
        return bool(self.rejected)


@dataclass(frozen=True)
class SeedsOutcome:
    kind: str                                                # saved · unchanged · preview
    data: object = None                                      # 쓴 뒤의 상태(`SeedsData`) — 미리 보기는 None
    changed: tuple = ()                                      # 바뀌었거나 새로 생긴 씨앗 번호들
    preview: object = None                                   # 미리 보기(`ImportInfo`)


class SeedsProvider:
    """Seed 관리 화면 데이터 공급자 공통 모양 — 모든 메서드는 작업 스레드에서 불린다(화면 스레드가 아니다). 읽기는 `load_seeds`·`preview_import`, 쓰기는 나머지 다섯(사용자가 눌렀을 때만)."""
    sample = False

    def load_seeds(self, progress, cancelled):
        raise NotImplementedError

    def set_state(self, seed_id, state, version, progress, cancelled):
        raise NotImplementedError

    def set_states(self, seed_ids, state, version, progress, cancelled):
        raise NotImplementedError

    def edit_seed(self, seed_id, fields, version, progress, cancelled):
        raise NotImplementedError

    def create_seed(self, fields, version, progress, cancelled):
        raise NotImplementedError

    def preview_import(self, path, progress, cancelled):
        raise NotImplementedError

    def apply_import(self, info, progress, cancelled):
        raise NotImplementedError


def _pause(seconds, cancelled):
    end = time.monotonic() + seconds
    while seconds and time.monotonic() < end:
        if cancelled():
            raise JobCancelled()
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


def _seed(seed_id, keyword, **changes):
    values = {"seed_id": seed_id, "major": "예시 대분류 하나", "minor": "예시 중분류 하나", "keyword": keyword, "seed_type": "general", "scope": "naver_a", "registered_on": "2026-10-20", "state": "proposed",
              "target_type": "product", "reason": "예시 이유 한 줄"}
    values.update(changes)
    return sd.Seed(**values)


def _sample_seeds(scenario):
    """가짜 Seed — 예시 낱말뿐이다. `normal` 은 승인 전·사용 중·쉬는 중이 섞인 열여섯 개(계절형·지역 값 필요·브랜드 예외·180일 제안 대상 포함), `many` 는 130개, `empty`·`error` 는 없다."""
    if scenario in ("empty", "error"):
        return []
    if scenario == "many":
        states = ("proposed", "proposed", "proposed", "active", "inactive")
        scopes = ("naver_a", "naver_b", "common", "github_pages", "blogger_ko", "blogger_en")
        items = []
        for number in range(1, 131):
            scope = scopes[number % len(scopes)]
            state = states[number % len(states)]
            extra = {"active_since": "2026-10-25"} if state != "proposed" else {}
            items.append(_seed(f"EXM{number:03d}", f"예시 낱말 {number:03d}", scope=scope, state=state, major=f"예시 대분류 {number % 5 + 1}", minor=f"예시 중분류 {number % 7 + 1}", **extra))
        return items
    two = {"scope": "common", "allowed_channels": ("naver_a", "naver_b")}
    return [
        _seed("EX001", "예시 낱말 가"), _seed("EX002", "예시 낱말 나", seed_type="priority", priority=True, minor="예시 중분류 둘", priority_keywords=("예시 우선 하나",)),
        _seed("EX003", "예시 낱말 다", scope="naver_b", target_type="saas", major="예시 대분류 둘", excluded_keywords=("예시 제외 하나",)),
        _seed("EX004", "예시 낱말 라", seed_type="sponsorable", sponsor_tag="pc_parts", target_type="pc_part", scope="naver_b", major="예시 대분류 둘"),
        _seed("EX005", "예시 낱말 마", **two, target_type="problem", minor="예시 중분류 둘"),
        _seed("EX006", sd.REGION_PLACEHOLDER + " 예시 장소", target_type="place", needs_region=True, minor="예시 중분류 셋"),
        _seed("EX007", "예시 낱말 바", brand_case=True, reason="예시 브랜드 허용 이유"),
        _seed("EX008", "예시 낱말 사", scope="github_pages", target_type="policy", major="예시 대분류 셋", reason="예시 이유 둘"),
        _seed("EX009", "예시 낱말 아", state="active", registered_on="2026-04-01", minor="예시 중분류 둘"),
        _seed("EX010", "예시 낱말 자", state="active", active_since="2026-10-25", scope="naver_b", target_type="saas", major="예시 대분류 둘"),
        _seed("EX011", "예시 낱말 차", state="active", active_since="2026-10-25", **two, target_type="life_habit"),
        _seed("EX012", "예시 계절 낱말", state="active", active_since="2026-10-25", seed_type="seasonal", prepare_from="12-05", publish_from="12-20", publish_until="01-20", peak_period=("12-28", "01-10"),
              recurrence="yearly", registered_on="2026-04-01", scope="common", allowed_channels=("naver_a",), target_type="place_lodging"),
        _seed("EX013", "예시 실시간 낱말", state="active", active_since="2026-10-25", seed_type="realtime", scope="naver_b", target_type="realtime_issue", major="예시 대분류 둘"),
        _seed("EX014", "예시 낱말 카", state="inactive", active_since="2026-09-01", registered_on="2026-08-01"),
        _seed("EX015", "예시 낱말 타", state="inactive", active_since="2026-09-01", registered_on="2026-08-01", scope="blogger_ko", target_type="life_habit", major="예시 대분류 셋"),
        _seed("EX016", "예시 낱말 파", scope="blogger_en", target_type="life_habit", major="예시 대분류 셋"),
    ]


class FakeSeedsProvider(SeedsProvider):
    """메모리에서만 일하는 가짜 공급자 — 바꾸기·고치기·등록·불러오기도 메모리 안에서만 바뀐다(파일·서비스를 부르지 않는다). 규칙은 서비스와 같다(시험이 같은 일을 둘에 해 보고 견준다)."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0, *, today=SAMPLE_DAY, import_mode="ok"):
        if scenario not in SCENARIOS or import_mode not in IMPORT_MODES:
            raise ValueError((scenario, import_mode))
        self.scenario, self.delay, self.today, self.import_mode = scenario, delay, today, import_mode
        self.seeds = _sample_seeds(scenario)
        self.revision = 1
        self.calls = []

    def _data(self):
        idle = tuple((item.seed_id, item.idle_days) for item in sd.idle_proposals(self.seeds, self.today))
        return SeedsData(tuple(self.seeds), str(self.revision), "ok", self.today, idle, DEFAULT_GENERATION, True)

    def _enter(self, name, version, cancelled):
        self.calls.append(name)
        _pause(self.delay, cancelled)
        if version is not None and str(self.revision) != version:
            raise SeedFailure(T["seeds_fail_conflict"], code="STORE_CONFLICT", kind="conflict")

    def _done(self, before, changed_ids=None):
        changed = tuple(changed_ids) if changed_ids is not None else tuple(item.seed_id for item in self.seeds if item not in before)
        if changed:
            self.revision += 1
        return SeedsOutcome("saved" if changed else "unchanged", self._data(), changed)

    def _find(self, seed_id):
        found = next((item for item in self.seeds if item.seed_id == seed_id), None)
        if found is None:
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid")
        return found

    def _replace(self, updated):
        self.seeds = [updated if item.seed_id == updated.seed_id else item for item in self.seeds]

    def load_seeds(self, progress, cancelled):
        self.calls.append("load")
        _pause(self.delay, cancelled)
        if self.scenario == "error":
            raise SeedFailure(T["seeds_error_desc"], code="SAMPLE_SEEDS_UNREADABLE", kind="corrupt")
        return self._data()

    def set_state(self, seed_id, state, version, progress, cancelled):
        self._enter("set_state", version, cancelled)
        before = list(self.seeds)
        try:
            self._replace(sd.change_state(self._find(seed_id), state, on=self.today))
        except AppError:
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid") from None
        return self._done(before)

    def set_states(self, seed_ids, state, version, progress, cancelled):
        self._enter("set_states", version, cancelled)
        before = list(self.seeds)
        ids = tuple(seed_ids)
        if not ids or len(set(ids)) != len(ids):
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid")
        changed = {}
        try:
            for seed_id in ids:                                # 전부 계산해 본 뒤에 한꺼번에 바꾼다 — 하나라도 안 되면 하나도 안 바뀐다
                changed[seed_id] = sd.change_state(self._find(seed_id), state, on=self.today)
        except AppError:
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid") from None
        self.seeds = [changed.get(item.seed_id, item) for item in self.seeds]
        return self._done(before, ids)

    def edit_seed(self, seed_id, fields, version, progress, cancelled):
        self._enter("edit_seed", version, cancelled)
        before, seed = list(self.seeds), self._find(seed_id)
        bad = {}
        for name, value in fields.items():
            try:
                dataclasses.replace(seed, **{name: value})
            except AppError:
                bad[name] = "invalid"
        if not bad:
            try:
                self._replace(dataclasses.replace(seed, **fields))
            except AppError:
                bad = {name: "invalid" for name in fields if name in ("priority_keywords", "excluded_keywords")} or {"": "invalid"}
        if bad:
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid", problems=bad)
        return self._done(before)

    def _next_id(self):
        taken = {item.seed_id for item in self.seeds}
        found = [int(match.group(1)) for item in self.seeds if (match := re.fullmatch(MANUAL_PREFIX + r"([0-9]+)", item.seed_id))]
        number = max(found, default=0) + 1
        while f"{MANUAL_PREFIX}{number:03d}" in taken:
            number += 1
        return f"{MANUAL_PREFIX}{number:03d}"

    def create_seed(self, fields, version, progress, cancelled):
        self._enter("create_seed", version, cancelled)
        before = list(self.seeds)
        keyword = fields.get("keyword", "")
        values = dict(seed_id=self._next_id(), major=fields.get("major"), minor=fields.get("minor"), keyword=keyword, seed_type=fields.get("seed_type"), scope=fields.get("scope"), registered_on=self.today,
                      state=sd.STATE_PROPOSED, priority=fields.get("seed_type") == "priority", excluded_keywords=fields.get("excluded_keywords", ()), sponsor_tag=fields.get("sponsor_tag"),
                      target_type=fields.get("target_type"), allowed_channels=fields.get("allowed_channels"), priority_keywords=fields.get("priority_keywords", ()), reason=fields.get("reason", ""),
                      needs_region=isinstance(keyword, str) and sd.REGION_PLACEHOLDER in keyword, brand_case=False)
        if values["seed_type"] == sd.SEED_SEASONAL or values["target_type"] is None:
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid", problems={"seed_type" if values["seed_type"] == sd.SEED_SEASONAL else "target_type": "invalid"})
        try:
            made = sd.Seed(**values)
        except AppError:
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid", problems={"": "invalid"}) from None
        word = (made.scope, keyword_key(made.keyword))
        if any((item.scope, keyword_key(item.keyword)) == word for item in self.seeds):
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid", problems={"keyword": "duplicate"})
        self.seeds.append(made)
        return self._done(before, (made.seed_id,))

    def preview_import(self, path, progress, cancelled):
        self.calls.append("preview_import")
        _pause(self.delay, cancelled)
        if self.import_mode == "unreadable":
            raise SeedFailure(T["seeds_imp_failed"], code="CONTENT_INVALID", kind="invalid")
        have = {item.seed_id for item in self.seeds}
        fresh = tuple(_seed(f"EXI{number:03d}", f"예시 불러온 낱말 {number}", registered_on=self.today, scope="naver_a" if number % 2 else "naver_b") for number in (1, 2, 3))
        if self.import_mode == "none":
            fresh = ()
        fresh = tuple(item for item in fresh if item.seed_id not in have)
        skipped = ((self.seeds[0].seed_id, "같은 씨앗 번호가 이미 등록되어 있어 건너뜁니다(덮어쓰지 않습니다)"),) if self.seeds else ()           # 가짜 파일에는 이미 있는 번호(첫 씨앗)도 하나 들어 있다 — 덮어쓰지 않고 건너뛴다
        rejected = (("EXI900", "씨앗 낱말 — 글자나 숫자가 하나도 없다"),) if self.import_mode == "blocked" else ()
        per_channel = tuple((code, sum(1 for item in fresh if code in item.allowed_channels), enabled) for code, enabled in DEFAULT_GENERATION)
        return SeedsOutcome("preview", None, (), ImportInfo(len(fresh) + len(skipped) + len(rejected), len(fresh), len(self.seeds), skipped, rejected, (), per_channel, False,
                                                          str(self.revision), fresh, True))

    def apply_import(self, info, progress, cancelled):
        self._enter("apply_import", info.version, cancelled)
        before = list(self.seeds)
        added = tuple(info.handle)
        if any(item.state != sd.STATE_PROPOSED for item in added):
            raise SeedFailure(T["seeds_fail_invalid"], code="CONTENT_INVALID", kind="invalid")
        self.seeds.extend(added)
        return self._done(before, tuple(item.seed_id for item in added))


__all__ = ["FakeSeedsProvider", "ImportInfo", "SeedFailure", "SeedsData", "SeedsOutcome", "SeedsProvider"]
