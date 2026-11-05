"""Seed(씨앗) — 후보 주제를 만들어 내는 출발 낱말의 모양과 검증, `seeds.json` 의 JSON 모양, '180일 미선택 씨앗 쉬게 하기 제안' 계산(순수 계산 — 파일·네트워크·시계·난수 없음, 날짜는 인자로 받는다).

씨앗 하나 = 대분류 › 중분류 › 씨앗 낱말 + 유형(후보를 만드는 방식) + 소속(공통 또는 한 채널) + 우선 표시 + 제외 키워드 + 협찬 태그 + 상태 + 등록일·마지막 선택일.
  · 유형 키 다섯(`general·priority·seasonal·realtime·sponsorable`)은 P1 `channels.PER_SEED` 의 이름 그대로이고, 씨앗 하나에서 처음 만들 후보 수·남길 후보 수는 그 표를 따른다(`quota_of`).
  · 협찬은 별도 저장소가 없다 — 협찬 후보가 될 수 있는 씨앗은 같은 목록에서 **협찬 태그 하나**(`sponsor_tag`, 영문 소문자·숫자·밑줄)로 표시하고, 유형이 `sponsorable` 이면 태그가 꼭 있어야 한다.
  · 상태는 셋이다: `proposed`(자동으로 제안된 씨앗 — **운영자가 승인하기 전**이라 후보 생성에 쓰지 않는다)·`active`(사용 중)·`inactive`(쉬는 중). 바꿀 수 있는 길은 `TRANSITIONS` 뿐이다(`change_state`).
  · '마지막 선택일' 은 이 씨앗에서 나온 후보를 운영자가 고른 날이다. 한 번도 고르지 않았으면 None 이고, 그때의 기준은 등록일(`registered_on`)이다 — 날짜가 없는 씨앗을 '오래 안 쓴 씨앗' 으로 치지 않는다(모름 ≠ 0).
  · **180일 이상 선택하지 않은 사용 중 씨앗은 '쉬게 할지' 제안만 한다**(`idle_proposals`) — 이 모듈이 스스로 상태를 바꾸지 않는다. 운영자가 승인한 뒤에야 호출하는 쪽이 `change_state` 로 바꾼다.
  · 처음 목록의 크기(공통 30개 + 채널마다 20개)는 한도가 아니라 **처음 크기**다(`INITIAL_COMMON`·`INITIAL_PER_CHANNEL`). 파일 전체의 안전 한도는 `MAX_SEEDS` 이다.
**실제 씨앗 목록은 이 저장소에 두지 않는다** — 스키마·빈 틀(`seeds_to_dict(())`)·시험용 예시만 두고, 실제 목록은 이 PC 의 사용자 데이터(`seeds.json`)에만 둔다. 읽고 쓰기는 사전(dict)까지만 하고 파일은 다음 묶음(저장)의 몫이다.
JSON 모양은 `channels.profiles_from_dict` 처럼 엄격하다 — `schema` 1·정확한 칸·모르는 칸·잘못된 타입·같은 씨앗 두 번은 `CONTENT_INVALID` 로 거절하고 어느 칸이 왜 안 되는지 쉬운 한국어로 알린다.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from types import MappingProxyType
from typing import NamedTuple

from ..content.candidates import _ID, forbidden_claim, keyword_key
from ..content.profiles import _no_markup, _text, _words
from ..errors import AppError
from .channels import CHANNELS, MAX_NAME, PER_SEED, at_entry, canonical, explain, invalid_in, is_tag
from .history import valid_day

SCHEMA = 1
SUBJECT = "씨앗"

SEED_TYPES = tuple(PER_SEED)                                         # general·priority·seasonal·realtime·sponsorable — `channels.PER_SEED` 의 이름과 순서 그대로
SCOPE_COMMON = "common"
SCOPES = (SCOPE_COMMON, *CHANNELS)                                    # 공통 또는 코드의 채널 키 하나(입력 별칭은 저장하지 않는다)
STATE_PROPOSED, STATE_ACTIVE, STATE_INACTIVE = "proposed", "active", "inactive"
STATES = (STATE_PROPOSED, STATE_ACTIVE, STATE_INACTIVE)
STATE_KO = MappingProxyType({STATE_PROPOSED: "제안(승인 전)", STATE_ACTIVE: "사용 중", STATE_INACTIVE: "쉬는 중"})
TRANSITIONS = MappingProxyType({STATE_PROPOSED: (STATE_ACTIVE, STATE_INACTIVE), STATE_ACTIVE: (STATE_INACTIVE,), STATE_INACTIVE: (STATE_ACTIVE,)})

IDLE_DAYS = 180                                                      # 이만큼(포함) 선택하지 않은 사용 중 씨앗은 쉬게 할지 제안한다
INITIAL_COMMON, INITIAL_PER_CHANNEL = 30, 20                         # 처음 목록의 크기(공통 30 + 채널마다 20) — 한도가 아니다
MAX_SEEDS = 1000
MAX_EXCLUDED = 20
MAX_EXCLUDED_WORD = 30
MAX_KEYWORD = 60

_KEYS = ("seed_id", "major", "minor", "keyword", "seed_type", "scope", "priority", "excluded_keywords", "sponsor_tag", "state", "registered_on", "last_selected_on")


def _invalid(item, detail=""):
    return invalid_in(SUBJECT, item, detail)


def _flag(value, item):
    if not isinstance(value, bool):
        raise _invalid(item, "예·아니오(true·false) 중 하나여야 한다")
    return value


def _choice(value, allowed, item):
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(item, "다음 중 하나여야 한다: " + ", ".join(allowed))
    return value


def _day(value, item, *, optional=False):
    if value is None and optional:
        return None
    if valid_day(value) is None:
        raise _invalid(item, "2026-11-05 같은 모양의 달력에 있는 날짜(2000년 이후)여야 한다")
    return value


@dataclass(frozen=True, kw_only=True)
class Seed:
    seed_id: str                                    # 씨앗 번호(영문·숫자·밑줄·붙임표 1~64자) — 만드는 쪽이 정한다(여기서 난수를 쓰지 않는다)
    major: str                                      # 대분류
    minor: str                                      # 중분류
    keyword: str                                    # 씨앗 낱말
    seed_type: str                                  # general·priority·seasonal·realtime·sponsorable
    scope: str                                      # common(공통) 또는 채널 코드 키
    registered_on: str                              # 등록일 YYYY-MM-DD
    state: str                                      # proposed·active·inactive — 일부러 기본값이 없다(자동 제안이 사용 중으로 만들어지는 실수를 막는다)
    priority: bool = False                          # 우선 표시 — 유형과 독립이다(목록에서 앞에 둔다)
    excluded_keywords: tuple = ()                   # 제외 키워드(이 씨앗에서 만든 후보에 들어가면 안 되는 낱말)
    sponsor_tag: str | None = None                  # 협찬 태그(영문 소문자·숫자·밑줄) — 유형이 sponsorable 이면 필수
    last_selected_on: str | None = None             # 마지막 선택일 YYYY-MM-DD — 한 번도 안 골랐으면 None

    def __post_init__(self):
        try:
            self._check()
        except AppError as error:
            raise explain(SUBJECT, error) from None

    def _check(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        if not isinstance(self.seed_id, str) or not _ID.fullmatch(self.seed_id):
            raise _invalid("씨앗 번호", "영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 한다")
        for name, label in (("major", "대분류"), ("minor", "중분류")):
            put(name, _no_markup(_text(getattr(self, name), label, low=1, high=MAX_NAME), label))
        word = _no_markup(_text(self.keyword, "씨앗 낱말", low=1, high=MAX_KEYWORD), "씨앗 낱말")
        if not keyword_key(word):
            raise _invalid("씨앗 낱말", "글자나 숫자가 하나도 없다")
        claim = forbidden_claim(word)
        if claim:
            raise _invalid("씨앗 낱말", f"‘{claim[0]}’ 같은 결과를 약속하는 표현은 쓸 수 없다")
        put("keyword", word)
        _choice(self.seed_type, SEED_TYPES, "씨앗 유형")
        _choice(self.scope, SCOPES, "소속(공통 또는 채널)")
        _flag(self.priority, "우선 표시")
        put("excluded_keywords", _words(self.excluded_keywords, "제외 키워드", count=MAX_EXCLUDED, high=MAX_EXCLUDED_WORD, sequence_only=True, markup_free=True))
        if self.sponsor_tag is not None and not is_tag(self.sponsor_tag):
            raise _invalid("협찬 태그", "영문 소문자·숫자·밑줄(_)로 된 태그(예: pc_parts)이거나 비워 두어야 한다")
        if self.seed_type == "sponsorable" and self.sponsor_tag is None:
            raise _invalid("협찬 태그", "유형이 협찬 가능(sponsorable)이면 협찬 태그가 꼭 있어야 한다")
        _choice(self.state, STATES, "상태")
        _day(self.registered_on, "등록일")
        _day(self.last_selected_on, "마지막 선택일", optional=True)
        if self.last_selected_on is not None and self.last_selected_on < self.registered_on:
            raise _invalid("마지막 선택일", "등록일보다 앞설 수 없다")
        if self.state == STATE_PROPOSED and self.last_selected_on is not None:
            raise _invalid("마지막 선택일", "승인 전(제안) 씨앗은 한 번도 선택될 수 없다")

    def to_dict(self):
        return {"seed_id": self.seed_id, "major": self.major, "minor": self.minor, "keyword": self.keyword, "seed_type": self.seed_type, "scope": self.scope, "priority": self.priority,
                "excluded_keywords": list(self.excluded_keywords), "sponsor_tag": self.sponsor_tag, "state": self.state, "registered_on": self.registered_on,
                "last_selected_on": self.last_selected_on}

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 정확히 이 칸들이어야 하고(모르는 칸·빠진 칸 거절) 값은 `__post_init__` 이 검사한다."""
        if not isinstance(data, dict):
            raise _invalid("모양", "칸이 있는 묶음(JSON 객체)이어야 한다")
        unknown, missing = sorted(map(str, set(data) - set(_KEYS))), sorted(set(_KEYS) - set(data))
        if unknown or missing:
            raise _invalid("모양", f"모르는 칸 {unknown}, 빠진 칸 {missing}")
        return cls(**data)


def quota_of(seed):
    """씨앗 하나에서 처음 만들 후보 수와 남길 후보 수(`channels.PER_SEED` 표의 그 유형 칸 — `SeedQuota(first, keep)`)."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    return PER_SEED[seed.seed_type]


# ---- 상태와 선택일 --------------------------------------------------------------------------------------------------------------------
def change_state(seed, new_state):
    """씨앗의 상태를 `TRANSITIONS` 가 허용하는 길로만 바꾼 새 씨앗을 돌려준다(제안 → 사용 중·쉬는 중, 사용 중 → 쉬는 중, 쉬는 중 → 사용 중). 이 함수는 운영자가 승인한 뒤에 부른다 — 승인을 확인하지는 않는다."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    if not isinstance(new_state, str) or new_state not in STATES:
        raise _invalid("상태", "다음 중 하나여야 한다: " + ", ".join(STATES))
    if new_state not in TRANSITIONS[seed.state]:
        raise _invalid("상태", f"‘{STATE_KO[seed.state]}’ 에서 ‘{STATE_KO[new_state]}’ 로는 바꿀 수 없다")
    return replace(seed, state=new_state)


def selected(seed, on):
    """이 씨앗에서 나온 후보를 `on`(YYYY-MM-DD)에 골랐다고 마지막 선택일을 적은 새 씨앗. 사용 중인 씨앗만, 그리고 등록일·이전 선택일보다 앞서지 않는 날짜만 받는다."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    _day(on, "선택일")
    if seed.state != STATE_ACTIVE:
        raise _invalid("선택일", f"‘{STATE_KO[seed.state]}’ 씨앗은 선택할 수 없다 — 사용 중인 씨앗만 후보를 만든다")
    if seed.last_selected_on is not None and on < seed.last_selected_on:
        raise _invalid("선택일", "이전 선택일보다 앞설 수 없다")
    return replace(seed, last_selected_on=on)


# ---- 180일 미선택 제안 ---------------------------------------------------------------------------------------------------------------
class IdleProposal(NamedTuple):
    seed_id: str
    keyword: str
    since: str                                      # 기준 날짜 — 마지막 선택일, 한 번도 안 골랐으면 등록일
    idle_days: int                                  # `since` 부터 오늘까지의 날수
    never_selected: bool                            # 등록한 뒤 한 번도 선택되지 않았다

    def message(self):
        how = "등록한 뒤 한 번도 선택하지 않았고" if self.never_selected else "마지막으로 선택한 뒤"
        return f"씨앗 ‘{self.keyword}’ 은(는) {how} {self.idle_days}일이 지났습니다 — 쉬게 할지 운영자가 정합니다(승인 전에는 바뀌지 않습니다)"


def idle_days(seed, today):
    """기준 날짜(마지막 선택일, 없으면 등록일)부터 `today`(YYYY-MM-DD)까지의 날수. 오늘이 기준보다 앞이면 0 이다."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    _day(today, "오늘 날짜")
    basis = seed.last_selected_on or seed.registered_on
    return max(0, (date.fromisoformat(today) - date.fromisoformat(basis)).days)


def idle_proposals(seeds, today, days=IDLE_DAYS):
    """사용 중(`active`) 씨앗 중 마지막 선택일(없으면 등록일)로부터 `days`일(기본 180, 포함) 이상 지난 것을 **쉬게 할지 제안**으로 돌려준다 — 오래된 순, 같으면 씨앗 번호순.
    제안만 돌려준다: 씨앗은 하나도 바뀌지 않는다(운영자가 승인한 뒤에야 `change_state`). 제안 상태·쉬는 중 씨앗은 대상이 아니다."""
    pool = tuple(seeds)
    if not all(isinstance(seed, Seed) for seed in pool):
        raise TypeError("씨앗(Seed)만 넘길 수 있다")
    _day(today, "오늘 날짜")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 3650:
        raise _invalid("미선택 날수", "1~3650 사이의 정수여야 한다")
    found = []
    for seed in pool:
        if seed.state != STATE_ACTIVE:
            continue
        idle = idle_days(seed, today)
        if idle >= days:
            found.append(IdleProposal(seed.seed_id, seed.keyword, seed.last_selected_on or seed.registered_on, idle, seed.last_selected_on is None))
    return tuple(sorted(found, key=lambda proposal: (-proposal.idle_days, proposal.seed_id)))


# ---- 쓸 수 있는 씨앗 -----------------------------------------------------------------------------------------------------------------
def usable_seeds(seeds, channel):
    """`channel` 의 후보를 만드는 데 쓸 수 있는 씨앗 — 상태가 사용 중(`active`)이고 소속이 공통이거나 그 채널인 것. 제안·쉬는 중 씨앗은 쓰지 않는다.
    우선 표시한 씨앗이 앞이고 그다음은 대분류·중분류·씨앗 낱말·씨앗 번호 순이다(결정적). 채널은 코드 키나 입력 별칭(blogger_a·blogger_b)이다."""
    code = canonical(channel)
    pool = tuple(seeds)
    if not all(isinstance(seed, Seed) for seed in pool):
        raise TypeError("씨앗(Seed)만 넘길 수 있다")
    chosen = [seed for seed in pool if seed.state == STATE_ACTIVE and seed.scope in (SCOPE_COMMON, code)]
    return tuple(sorted(chosen, key=lambda seed: (not seed.priority, seed.major, seed.minor, keyword_key(seed.keyword), seed.seed_id)))


# ---- seeds.json 모양 ------------------------------------------------------------------------------------------------------------------
def seeds_to_dict(seeds):
    """씨앗 목록 → 저장 모양(`schema` 1, 입력 순서 그대로). 빈 목록이 '빈 틀' 이다. 다시 `seeds_from_dict` 로 읽으면 같은 씨앗들이 된다."""
    pool = tuple(seeds)
    _check_all(pool)
    return {"schema": SCHEMA, "seeds": [seed.to_dict() for seed in pool]}


def seeds_from_dict(data):
    """저장된 모양 → 씨앗들(파일 순서). `schema`·정확한 칸을 요구하고 모르는 칸·틀린 값·같은 번호 두 번·같은 소속의 같은 낱말 두 번·`MAX_SEEDS` 초과는 `CONTENT_INVALID` 로 거절한다."""
    item = "씨앗 저장 형식"
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != SCHEMA:
        raise _invalid(item, "저장된 씨앗 목록의 모양(schema 1)이 아니다")
    if set(data) != {"schema", "seeds"}:
        raise _invalid(item, "schema 와 seeds 두 칸만 있어야 한다")
    entries = data["seeds"]
    if not isinstance(entries, list):
        raise _invalid(item, "seeds 는 목록이어야 한다")
    if len(entries) > MAX_SEEDS:
        raise _invalid(item, f"씨앗은 {MAX_SEEDS}개까지다")
    made = []
    for number, entry in enumerate(entries, start=1):
        try:
            made.append(Seed.from_dict(entry))
        except AppError as error:
            raise at_entry(SUBJECT, number, error) from None
    pool = tuple(made)
    _check_all(pool)
    return pool


def _check_all(pool):
    if not all(isinstance(seed, Seed) for seed in pool):
        raise _invalid("씨앗 목록", "씨앗(Seed)만 들어 있어야 한다")
    if len(pool) > MAX_SEEDS:
        raise _invalid("씨앗 목록", f"씨앗은 {MAX_SEEDS}개까지다")
    ids = Counter(seed.seed_id for seed in pool)
    twice = sorted(name for name, count in ids.items() if count > 1)
    if twice:
        raise _invalid("씨앗 목록", f"같은 씨앗 번호가 두 번 들어 있다: {twice}")
    keys = Counter((seed.scope, keyword_key(seed.keyword)) for seed in pool)
    again = sorted({seed.keyword for seed in pool if keys[(seed.scope, keyword_key(seed.keyword))] > 1})
    if again:
        raise _invalid("씨앗 목록", f"같은 소속에 같은 씨앗 낱말이 두 번 들어 있다: {again}")


__all__ = [
    "IDLE_DAYS", "INITIAL_COMMON", "INITIAL_PER_CHANNEL", "IdleProposal", "MAX_SEEDS", "SCHEMA", "SCOPES", "SCOPE_COMMON", "SEED_TYPES", "STATES", "STATE_ACTIVE", "STATE_INACTIVE", "STATE_KO",
    "STATE_PROPOSED", "Seed", "TRANSITIONS", "change_state", "idle_days", "idle_proposals", "quota_of", "seeds_from_dict", "seeds_to_dict", "selected", "usable_seeds",
]
