"""Seed(씨앗) — 후보 주제를 만들어 내는 출발 낱말의 모양과 검증, `seeds.json` 의 JSON 모양(판 1·2), 씨앗 제안 파일 읽기, '180일 미선택 씨앗 쉬게 하기 제안' 계산(순수 계산 — 파일·네트워크·시계·난수 없음, 날짜는 인자로 받는다).

씨앗 하나 = 대분류 › 중분류 › 씨앗 낱말 + 중요도(후보를 만드는 방식) + 대상 유형(어떤 확장이 어울리나) + 소속(공통 또는 한 채널)·허용 채널 + 우선 표시·우선 키워드·제외 키워드 + 협찬 태그 + 상태 + 등록일·마지막 선택일.
  · **중요도**(`seed_type`: `general·priority·seasonal·realtime·sponsorable` 다섯)는 P1 `channels.PER_SEED` 의 이름 그대로이고, 씨앗 하나에서 처음 만들 후보 수·남길 후보 수는 그 표를 따른다(`quota_of`). 원문의 '월별' 은
    중요도를 따로 두지 않고 계절 씨앗의 반복(`recurrence` = `monthly`)이 맡는다.
  · **대상 유형**(`target_type`: 제품·장소·숙박·서비스·SaaS·PC 부품·문제·생활 습관·실시간 이슈·정책·API 열한 가지와, 원문 §10.3 표의 묶음 행 셋 `place_lodging·service_saas·policy_api`)은 **허용 확장어**를 정한다(`expand.py`).
    중요도와 대상 유형은 서로 다른 축이다 — 하나가 다른 하나를 대신하지 않는다. 대상 유형이 없는 씨앗(`None` — 판 1 의 씨앗)은 옛 규칙(중요도별 허용 계열)으로 확장한다.
  · 협찬은 별도 저장소가 없다 — 협찬 후보가 될 수 있는 씨앗은 같은 목록에서 **협찬 태그 하나**(`sponsor_tag`, 영문 소문자·숫자·밑줄)로 표시하고, 유형이 `sponsorable` 이면 태그가 꼭 있어야 한다.
  · 상태는 셋이다: `proposed`(자동으로 제안된 씨앗 — **운영자가 승인하기 전**이라 후보 생성에 쓰지 않는다)·`active`(사용 중)·`inactive`(쉬는 중). 바꿀 수 있는 길은 `TRANSITIONS` 뿐이다(`change_state`).
  · '마지막 선택일' 은 이 씨앗에서 나온 후보를 운영자가 고른 날이다. 한 번도 고르지 않았으면 None 이다. '사용 시작일'(`active_since`)은 씨앗이 **사용 중으로 바뀐 가장 최근 날**이다(제안을 승인했거나 쉬게 했다가 다시 켠 날 —
    처음부터 사용 중으로 등록했으면 None). 쉬는 동안 시계가 흐르지 않게, 180일의 기준은 **마지막 선택일·사용 시작일·등록일 중 가장 늦은 날**이다 — 날짜가 없는 씨앗을 '오래 안 쓴 씨앗' 으로 치지 않는다(모름 ≠ 0, P2b 독립 검증 M4).
  · **180일 이상 선택하지 않은 사용 중 씨앗은 '쉬게 할지' 제안만 한다**(`idle_proposals`) — 이 모듈이 스스로 상태를 바꾸지 않는다. 운영자가 승인한 뒤에야 호출하는 쪽이 `change_state` 로 바꾼다.
    **단, 계절형(`seasonal`)은 제안 대상이 아니다**(원문 §8.4, D-103) — 비수기라는 이유로 쉬게 하지 않는다. 계절 씨앗은 자기 일정(`prepare_from`·`publish_from`·`publish_until`·`peak_period`·`recurrence`)을 가질 수 있고 그날의 상태는
    `schedule.seasonal_state` 가 계산한다(시즌 밖이면 활성을 유지한 채 우선순위만 낮추고, 준비 시작일에 일반 우선순위로 돌아오고, 발행 기간에 우선 추천 평가 — D-114). `seasonal_priority_state` 칸에는 마지막으로 계산한 값을 적어 둘 수 있다.
  · 처음 목록의 크기(공통 30개 + 채널마다 20개)는 한도가 아니라 **처음 크기**다(`INITIAL_COMMON`·`INITIAL_PER_CHANNEL`). 파일 전체의 안전 한도는 `MAX_SEEDS` 이다.
  · **허용 채널**(`allowed_channels`): 공통 씨앗은 1개 이상(칸을 안 적으면 다섯 채널 모두 — 판 1 의 공통 씨앗이 모든 채널에서 쓰이던 동작 그대로), 채널 전용 씨앗은 그 채널 하나. `usable_seeds` 는 사용 중이고 허용 채널에 그 채널이 들어 있고
    그 채널의 후보 생성이 켜져 있을 때만 쓴다(채널 프로필을 넘겼을 때 — 첫 버전은 네이버 A·B 만 켜짐).
**실제 씨앗 목록은 이 저장소에 두지 않는다** — 스키마·빈 틀(`seeds_to_dict(())`)·시험용 예시만 두고, 실제 목록은 이 PC 의 사용자 데이터(`seeds.json`)에만 둔다. 읽고 쓰기는 사전(dict)까지만 하고 파일은 서비스(`service/topic_files.py`)의 몫이다.
JSON 모양은 `channels.profiles_from_dict` 처럼 엄격하다 — `schema` 는 **2 로 쓰고 1·2 를 모두 읽는다**(판 1 은 새 칸을 기본값으로 채우고 파일을 다시 쓰지 않는다. 더 새로운 판은 거절). 정확한 칸·모르는 칸·잘못된 타입·같은 씨앗 두 번은
`CONTENT_INVALID` 로 거절하고 어느 칸이 왜 안 되는지 쉬운 한국어로 알린다. 씨앗 제안 파일(`parse_proposals`)은 읽은 씨앗을 **모두 승인 전(`proposed`)** 으로만 만든다 — 파일이 다른 상태를 적었어도 무시한다.
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
from . import schedule, wording
from .channels import CHANNELS, MAX_NAME, PER_SEED, ChannelProfile, at_entry, canonical, explain, invalid_in, is_tag
from .history import valid_day

SCHEMA = 2                                                           # 쓰는 판 — 1 도 읽는다(`SCHEMAS`)
SCHEMAS = (1, 2)
SUBJECT = "씨앗"

SEED_TYPES = tuple(PER_SEED)                                         # general·priority·seasonal·realtime·sponsorable — `channels.PER_SEED` 의 이름과 순서 그대로
SEED_SEASONAL = "seasonal"                                           # 계절형 — 180일 '쉬게 할까요' 제안(`idle_proposals`)에서 제외한다(D-103)
SCOPE_COMMON = "common"
SCOPES = (SCOPE_COMMON, *CHANNELS)                                    # 공통 또는 코드의 채널 키 하나(입력 별칭은 저장하지 않는다)
STATE_PROPOSED, STATE_ACTIVE, STATE_INACTIVE = "proposed", "active", "inactive"
STATES = (STATE_PROPOSED, STATE_ACTIVE, STATE_INACTIVE)
STATE_KO = MappingProxyType({STATE_PROPOSED: "제안(승인 전)", STATE_ACTIVE: "사용 중", STATE_INACTIVE: "쉬는 중"})
TRANSITIONS = MappingProxyType({STATE_PROPOSED: (STATE_ACTIVE, STATE_INACTIVE), STATE_ACTIVE: (STATE_INACTIVE,), STATE_INACTIVE: (STATE_ACTIVE,)})

# 대상 유형 — 운영자가 정한 열한 가지(2026-11-06)와 원문 §10.3 표의 묶음 행 셋(씨앗 제안 파일이 이 이름을 쓴다). 묶음 행은 낱개 둘과 같은 허용 확장어를 갖는다(`expand.py`).
TARGET_TYPES = ("product", "place", "lodging", "service", "saas", "pc_part", "problem", "life_habit", "realtime_issue", "policy", "api")
TARGET_BUNDLES = ("place_lodging", "service_saas", "policy_api")
ALL_TARGET_TYPES = (*TARGET_TYPES, *TARGET_BUNDLES)
RECURRENCES = schedule.RECURRENCES                                   # yearly(매년)·monthly(매월 — 원문 '월별')
SEASON_STATES = schedule.SEASON_STATES

IDLE_DAYS = schedule.SEED_INACTIVE_REVIEW_DAYS                       # 이만큼(포함) 선택하지 않은 사용 중 씨앗은 쉬게 할지 제안한다 — 점검 주기 상수 하나가 이 이름의 주인이다(숫자가 두 곳에 흩어지지 않게)
INITIAL_COMMON, INITIAL_PER_CHANNEL = 30, 20                         # 처음 목록의 크기(공통 30 + 채널마다 20) — 한도가 아니다
MAX_SEEDS = 1000
MAX_EXCLUDED = 20
MAX_EXCLUDED_WORD = 30
MAX_PRIORITY_KEYWORDS = 10
MAX_KEYWORD = 60
MAX_REASON = 200
REGION_PLACEHOLDER = "{기준 지역}"                                   # 지역 값이 필요한 씨앗의 자리표시 — 채널 프로필의 지역 값으로 채운다(`with_region`)

_KEYS_V1 = ("seed_id", "major", "minor", "keyword", "seed_type", "scope", "priority", "excluded_keywords", "sponsor_tag", "state", "registered_on", "last_selected_on", "active_since")
_NEW_KEYS = ("target_type", "allowed_channels", "priority_keywords", "reason", "needs_region", "brand_case", "prepare_from", "publish_from", "publish_until", "peak_period", "recurrence", "seasonal_priority_state")
_KEYS = _KEYS_V1 + _NEW_KEYS                                         # 지금 판(2)의 칸 — 판 1 은 앞의 열세 칸이다
SEED_FIELD_KO = MappingProxyType({"seed_id": "씨앗 번호", "major": "대분류", "minor": "중분류", "keyword": "씨앗 낱말", "seed_type": "씨앗 유형", "scope": "소속(공통 또는 채널)", "priority": "우선 표시",
                                  "excluded_keywords": "제외 키워드", "sponsor_tag": "협찬 태그", "state": "상태", "registered_on": "등록일", "last_selected_on": "마지막 선택일",
                                  "active_since": "사용 시작일", "target_type": "대상 유형", "allowed_channels": "허용 채널", "priority_keywords": "우선 키워드", "reason": "제안 이유",
                                  "needs_region": "지역 값 필요", "brand_case": "브랜드 예외", "prepare_from": "준비 시작일", "publish_from": "발행 시작일", "publish_until": "발행 종료일",
                                  "peak_period": "피크 기간", "recurrence": "반복", "seasonal_priority_state": "계절 우선순위 상태"})        # 칸 이름 → 쉬운 한국어(오류 안내용)


def _invalid(item, detail="", *, dev=""):
    return invalid_in(SUBJECT, item, detail, dev=dev)


def _flag(value, item):
    if not isinstance(value, bool):
        raise _invalid(item, "예·아니오(true·false) 중 하나여야 한다")
    return value


def _choice(value, allowed, item, names):
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(item, wording.one_of(allowed, names), dev="값: " + ", ".join(allowed))
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
    seed_type: str                                  # 중요도 — general·priority·seasonal·realtime·sponsorable
    scope: str                                      # common(공통) 또는 채널 코드 키
    registered_on: str                              # 등록일 YYYY-MM-DD
    state: str                                      # proposed·active·inactive — 일부러 기본값이 없다(자동 제안이 사용 중으로 만들어지는 실수를 막는다)
    priority: bool = False                          # 우선 표시 — 유형과 독립이다(목록에서 앞에 둔다)
    excluded_keywords: tuple = ()                   # 제외 키워드(이 씨앗에서 만든 후보에 들어가면 안 되는 낱말)
    sponsor_tag: str | None = None                  # 협찬 태그(영문 소문자·숫자·밑줄) — 유형이 sponsorable 이면 필수
    last_selected_on: str | None = None             # 마지막 선택일 YYYY-MM-DD — 한 번도 안 골랐으면 None
    active_since: str | None = None                 # 사용 시작일 YYYY-MM-DD — 사용 중으로 바뀐 가장 최근 날(처음부터 사용 중으로 등록했으면 None)
    # ---- 판 2 에서 더한 칸(모두 기본값이 있어 판 1 파일이 그대로 읽힌다) ----
    target_type: str | None = None                  # 대상 유형(허용 확장어를 정한다) — None 이면 판 1 씨앗(옛 규칙)
    allowed_channels: tuple | None = None           # 허용 채널(코드 순서로 정리해 저장) — None 이면 기본: 공통은 다섯 채널 모두·채널 전용은 그 채널
    priority_keywords: tuple = ()                   # 우선 키워드(후보를 만들 때 먼저 붙이고 싶은 구체화 낱말) — 우선 표시(`priority`)와 다른 칸이다
    reason: str = ""                                # 제안 이유(200자까지 한 줄)
    needs_region: bool = False                      # 낱말의 `{기준 지역}` 자리를 채널 프로필의 지역 값으로 채워야 한다
    brand_case: bool = False                        # 브랜드 이름이 든 예외 씨앗 — 참이면 허용 사유를 제안 이유(`reason`)에 적어야 한다
    prepare_from: str | None = None                 # 계절 씨앗: 준비 시작일(매년 MM-DD·매월 DD)
    publish_from: str | None = None                 # 계절 씨앗: 추천 발행 시작일
    publish_until: str | None = None                # 계절 씨앗: 추천 발행 종료일(시작보다 앞서면 해(달)를 넘긴다)
    peak_period: tuple | None = None                # 계절 씨앗: 피크 기간 (시작, 끝) — 발행 기간 안
    recurrence: str | None = None                   # 계절 씨앗: yearly(매년)·monthly(매월 — 원문 '월별'). 일정이 있으면 기본 yearly
    seasonal_priority_state: str | None = None      # 계절 씨앗: 마지막으로 계산한 계절 상태(`schedule.seasonal_state` — 읽을 때는 그날 다시 계산한다)

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
        _choice(self.seed_type, SEED_TYPES, "씨앗 유형", wording.SEED_TYPE_KO)
        _choice(self.scope, SCOPES, "소속(공통 또는 채널)", wording.SCOPE_KO)
        _flag(self.priority, "우선 표시")
        put("excluded_keywords", _words(self.excluded_keywords, "제외 키워드", count=MAX_EXCLUDED, high=MAX_EXCLUDED_WORD, sequence_only=True, markup_free=True))
        if self.sponsor_tag is not None and not is_tag(self.sponsor_tag):
            raise _invalid("협찬 태그", "영문 소문자·숫자·밑줄(_)로 된 태그(예: ‘pc_parts’)이거나 비워 두어야 한다")
        if self.seed_type == "sponsorable" and self.sponsor_tag is None:
            raise _invalid("협찬 태그", f"씨앗 유형이 {wording.quote(wording.SEED_TYPE_KO['sponsorable'])} 이면 협찬 태그가 꼭 있어야 합니다", dev="유형이 sponsorable 이면 sponsor_tag 필수")
        _choice(self.state, STATES, "상태", STATE_KO)
        _day(self.registered_on, "등록일")
        _day(self.last_selected_on, "마지막 선택일", optional=True)
        if self.last_selected_on is not None and self.last_selected_on < self.registered_on:
            raise _invalid("마지막 선택일", "등록일보다 앞설 수 없다")
        if self.state == STATE_PROPOSED and self.last_selected_on is not None:
            raise _invalid("마지막 선택일", "승인 전(제안) 씨앗은 한 번도 선택될 수 없다")
        _day(self.active_since, "사용 시작일", optional=True)
        if self.active_since is not None and self.active_since < self.registered_on:
            raise _invalid("사용 시작일", "등록일보다 앞설 수 없다")
        if self.state == STATE_PROPOSED and self.active_since is not None:
            raise _invalid("사용 시작일", "승인 전(제안) 씨앗은 사용을 시작한 적이 없다")
        self._check_v2(put)

    def _check_v2(self, put):
        if self.target_type is not None:
            _choice(self.target_type, ALL_TARGET_TYPES, "대상 유형", wording.TARGET_TYPE_KO)
        put("allowed_channels", self._channels())
        put("priority_keywords", _words(self.priority_keywords, "우선 키워드", count=MAX_PRIORITY_KEYWORDS, high=MAX_EXCLUDED_WORD, sequence_only=True, markup_free=True))
        excluded = {keyword_key(item) for item in self.excluded_keywords}
        if any(keyword_key(item) in excluded for item in self.priority_keywords):
            raise _invalid("우선 키워드", "제외 키워드에 있는 낱말은 우선 키워드로 쓸 수 없다")
        put("reason", _no_markup(_text(self.reason, "제안 이유", low=0, high=MAX_REASON), "제안 이유"))
        _flag(self.needs_region, "지역 값 필요")
        _flag(self.brand_case, "브랜드 예외")
        if self.brand_case and not self.reason:
            raise _invalid("브랜드 예외", "브랜드 예외 씨앗은 허용 사유를 제안 이유 칸에 적어야 한다")
        has_placeholder = REGION_PLACEHOLDER in self.keyword
        if has_placeholder != self.needs_region:
            raise _invalid("지역 값 필요", f"씨앗 낱말에 {REGION_PLACEHOLDER} 자리표시가 있으면 ‘지역 값 필요’ 를 켜고, 없으면 꺼야 한다")
        self._check_season(put)

    def _channels(self):
        allowed = self.allowed_channels
        if allowed is None:
            return tuple(CHANNELS) if self.scope == SCOPE_COMMON else (self.scope,)
        if not isinstance(allowed, (list, tuple)) or not allowed or not all(isinstance(code, str) and code in CHANNELS for code in allowed) or len(set(allowed)) != len(allowed):
            raise _invalid("허용 채널", "채널은 " + wording.quoted(CHANNELS, names=wording.CHANNEL_KO) + " 중에서 한 번씩만, 1개 이상 적어야 합니다", dev="코드의 채널 이름: " + ", ".join(CHANNELS))
        ordered = tuple(code for code in CHANNELS if code in allowed)
        if self.scope != SCOPE_COMMON and ordered != (self.scope,):
            raise _invalid("허용 채널", "채널 전용 씨앗은 그 채널만 허용합니다 — 여러 채널에 쓰려면 소속을 ‘공통’ 으로 하세요")
        return ordered

    def _check_season(self, put):
        dates = (self.prepare_from, self.publish_from, self.publish_until)
        has_any = any(value is not None for value in dates) or self.peak_period is not None or self.recurrence is not None or self.seasonal_priority_state is not None
        if not has_any:
            return
        if self.seed_type != SEED_SEASONAL:
            raise _invalid("계절 일정", f"준비 시작일·발행 기간·피크·반복 칸은 씨앗 유형이 {wording.quote(wording.SEED_TYPE_KO[SEED_SEASONAL])} 일 때만 쓸 수 있습니다")
        if self.recurrence is not None:
            _choice(self.recurrence, RECURRENCES, "반복", wording.RECURRENCE_KO)
        if not all(value is not None for value in dates):
            raise _invalid("계절 일정", "준비 시작일·발행 시작일·발행 종료일은 셋 다 적어야 합니다(계절 일정을 쓰지 않으려면 모두 비워 두세요)")
        recurrence = self.recurrence or schedule.RECURRENCE_YEARLY
        peak = self._peak()
        problem = schedule.season_problem(recurrence, *dates, peak)
        if problem is not None:
            raise _invalid(problem[0], problem[1])
        put("recurrence", recurrence)
        put("peak_period", peak)
        if self.seasonal_priority_state is not None:
            _choice(self.seasonal_priority_state, SEASON_STATES, "계절 우선순위 상태", wording.SEASONAL_STATE_KO)

    def _peak(self):
        peak = self.peak_period
        if peak is None:
            return None
        if not isinstance(peak, (list, tuple)) or len(peak) != 2 or not all(isinstance(item, str) for item in peak):
            raise _invalid("피크 기간", "시작과 끝 두 날짜여야 한다")
        return tuple(peak)

    def to_dict(self):
        return {"seed_id": self.seed_id, "major": self.major, "minor": self.minor, "keyword": self.keyword, "seed_type": self.seed_type, "scope": self.scope, "priority": self.priority,
                "excluded_keywords": list(self.excluded_keywords), "sponsor_tag": self.sponsor_tag, "state": self.state, "registered_on": self.registered_on,
                "last_selected_on": self.last_selected_on, "active_since": self.active_since,
                "target_type": self.target_type, "allowed_channels": list(self.allowed_channels), "priority_keywords": list(self.priority_keywords), "reason": self.reason,
                "needs_region": self.needs_region, "brand_case": self.brand_case, "prepare_from": self.prepare_from, "publish_from": self.publish_from, "publish_until": self.publish_until,
                "peak_period": None if self.peak_period is None else list(self.peak_period), "recurrence": self.recurrence, "seasonal_priority_state": self.seasonal_priority_state}

    @classmethod
    def from_dict(cls, data, *, schema=None):
        """저장된 모양을 엄격하게 읽는다 — 정확히 이 칸들이어야 하고(모르는 칸·빠진 칸 거절) 값은 `__post_init__` 이 검사한다. `schema` 를 주면 그 판의 칸(1 은 열세 칸·2 는 스물다섯 칸)이어야 하고,
        안 주면 둘 중 하나의 모양이면 된다(판 1 칸 묶음은 새 칸이 기본값이다)."""
        if not isinstance(data, dict):
            raise _invalid("모양", "칸이 있는 묶음(JSON 객체)이어야 한다")
        keys = set(data)
        if schema == 1:
            expected = _KEYS_V1
        elif schema == 2:
            expected = _KEYS
        else:
            expected = _KEYS_V1 if keys <= set(_KEYS_V1) else _KEYS
        unknown, missing = sorted(map(str, keys - set(expected))), sorted(set(expected) - keys)
        if unknown or missing:
            raise _invalid("모양", wording.unknown_and_missing(unknown, missing, SEED_FIELD_KO), dev=f"모르는 칸 {unknown}, 빠진 칸 {missing}")
        return cls(**data)


def quota_of(seed):
    """씨앗 하나에서 처음 만들 후보 수와 남길 후보 수(`channels.PER_SEED` 표의 그 유형 칸 — `SeedQuota(first, keep)`)."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    return PER_SEED[seed.seed_type]


def with_region(seed, region):
    """지역 값이 필요한 씨앗(`needs_region`)의 `{기준 지역}` 자리를 `region`(채널 프로필의 지역 낱말)으로 채운 새 씨앗 — 자리표시가 없으면 같은 씨앗을 돌려준다. 채운 낱말이 씨앗 규칙(길이·표현)에 안 맞으면 `CONTENT_INVALID`."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    if not seed.needs_region:
        return seed
    if not isinstance(region, str) or not region.strip():
        raise _invalid("지역 값", "지역 낱말이 있어야 한다")
    return replace(seed, keyword=seed.keyword.replace(REGION_PLACEHOLDER, region.strip()), needs_region=False)


# ---- 상태와 선택일 --------------------------------------------------------------------------------------------------------------------
def change_state(seed, new_state, on=None):
    """씨앗의 상태를 `TRANSITIONS` 가 허용하는 길로만 바꾼 새 씨앗을 돌려준다(제안 → 사용 중·쉬는 중, 사용 중 → 쉬는 중, 쉬는 중 → 사용 중). 이 함수는 운영자가 승인한 뒤에 부른다 — 승인을 확인하지는 않는다.
    **사용 중으로 바꿀 때는 그 날짜(`on`, YYYY-MM-DD)가 꼭 있어야 한다** — 사용 시작일(`active_since`)로 적혀 180일 시계가 그날부터 다시 시작한다(쉬게 했다 다시 켜기·제안 승인, P2b 독립 검증 M4).
    등록일·이전 선택일·이전 사용 시작일보다 앞선 날짜는 거절한다. 쉬는 중으로 바꿀 때의 `on` 은 쓰지 않는다(사용 시작일은 그대로 남는다)."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    if not isinstance(new_state, str) or new_state not in STATES:
        raise _invalid("상태", wording.one_of(STATES, STATE_KO), dev="값: " + ", ".join(STATES))
    if new_state not in TRANSITIONS[seed.state]:
        raise _invalid("상태", f"‘{STATE_KO[seed.state]}’ 에서 ‘{STATE_KO[new_state]}’ 로는 바꿀 수 없다")
    if new_state != STATE_ACTIVE:
        return replace(seed, state=new_state)
    if valid_day(on) is None:
        raise _invalid("사용 시작일", "사용 중으로 바꿀 때는 2026-11-05 같은 모양의 날짜(2000년 이후)가 꼭 있어야 한다")
    if on < max(day for day in (seed.registered_on, seed.last_selected_on, seed.active_since) if day):
        raise _invalid("사용 시작일", "등록일·이전 선택일·이전 사용 시작일보다 앞설 수 없다")
    return replace(seed, state=new_state, active_since=on)


def selected(seed, on):
    """이 씨앗에서 나온 후보를 `on`(YYYY-MM-DD)에 골랐다고 마지막 선택일을 적은 새 씨앗. 사용 중인 씨앗만, 그리고 등록일·이전 선택일보다 앞서지 않는 날짜만 받는다."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    _day(on, "선택일")
    if seed.state != STATE_ACTIVE:
        raise _invalid("선택일", f"‘{STATE_KO[seed.state]}’ 씨앗은 선택할 수 없다 — 사용 중인 씨앗만 후보를 만든다")
    if seed.last_selected_on is not None and on < seed.last_selected_on:
        raise _invalid("선택일", "이전 선택일보다 앞설 수 없다")
    if seed.active_since is not None and on < seed.active_since:
        raise _invalid("선택일", "사용 시작일보다 앞설 수 없다 — 사용 중이던 때에 고른 것이 아니다")
    return replace(seed, last_selected_on=on)


# ---- 180일 미선택 제안 ---------------------------------------------------------------------------------------------------------------
BASIS_SELECTED, BASIS_STARTED, BASIS_REGISTERED = "selected", "started", "registered"        # 기준 날짜가 마지막 선택일·사용 시작일·등록일 중 무엇인가


class IdleProposal(NamedTuple):
    seed_id: str
    keyword: str
    since: str                                      # 기준 날짜 — 마지막 선택일·사용 시작일·등록일 중 가장 늦은 날
    idle_days: int                                  # `since` 부터 오늘까지의 날수
    never_selected: bool                            # 등록한 뒤 한 번도 선택되지 않았다
    basis: str = BASIS_REGISTERED                   # `since` 가 어느 날짜인가: selected·started·registered(날짜가 같으면 선택일 → 사용 시작일 → 등록일 순으로 본다)

    def message(self):
        if self.basis == BASIS_SELECTED:
            how = "마지막으로 선택한 뒤"
        elif self.basis == BASIS_STARTED:
            how = "사용을 다시 켠(시작한) 뒤 한 번도 선택하지 않았고"
        else:
            how = "등록한 뒤 한 번도 선택하지 않았고"
        return f"씨앗 ‘{self.keyword}’ 은(는) {how} {self.idle_days}일이 지났습니다 — 쉬게 할지 운영자가 정합니다(승인 전에는 바뀌지 않습니다)"


def basis_of(seed):
    """180일 시계의 기준 — 마지막 선택일·사용 시작일·등록일 중 **가장 늦은 날**과 그 이름(`selected`·`started`·`registered`). 같은 날이면 선택일 → 사용 시작일 → 등록일 순이다."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    options = ((seed.last_selected_on, BASIS_SELECTED), (seed.active_since, BASIS_STARTED), (seed.registered_on, BASIS_REGISTERED))
    day = max(day for day, _kind in options if day)
    return day, next(kind for found, kind in options if found == day)


def idle_days(seed, today):
    """기준 날짜(마지막 선택일·사용 시작일·등록일 중 가장 늦은 날 — `basis_of`)부터 `today`(YYYY-MM-DD)까지의 날수. 오늘이 기준보다 앞이면 0 이다."""
    if not isinstance(seed, Seed):
        raise TypeError("씨앗(Seed)이어야 한다")
    _day(today, "오늘 날짜")
    return max(0, (date.fromisoformat(today) - date.fromisoformat(basis_of(seed)[0])).days)


def idle_proposals(seeds, today, days=IDLE_DAYS):
    """사용 중(`active`) 씨앗 중 마지막 선택일(없으면 등록일)로부터 `days`일(기본 180, 포함) 이상 지난 것을 **쉬게 할지 제안**으로 돌려준다 — 오래된 순, 같으면 씨앗 번호순.
    제안만 돌려준다: 씨앗은 하나도 바뀌지 않는다(운영자가 승인한 뒤에야 `change_state`). 제안 상태·쉬는 중 씨앗은 대상이 아니다.
    **계절형(`seed_type == "seasonal"`)은 얼마나 묵었어도 제안하지 않는다** — 비수기라는 이유로 쉬게 하지 않는다(원문 §8.4, D-103). 사용자가 직접 쉬게 한 씨앗만 후보 생성에서 빠지는 지금 동작은 그대로다.
    계절 우선순위(시즌 밖 하향·준비 시작일 복원 등)는 이 함수의 일이 아니라 `schedule.seasonal_state` 와 후보 조립(`generate`)이 한다."""
    pool = tuple(seeds)
    if not all(isinstance(seed, Seed) for seed in pool):
        raise TypeError("씨앗(Seed)만 넘길 수 있다")
    _day(today, "오늘 날짜")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 3650:
        raise _invalid("미선택 날수", "1~3650 사이의 정수여야 한다")
    found = []
    for seed in pool:
        if seed.state != STATE_ACTIVE or seed.seed_type == SEED_SEASONAL:           # 계절형은 비수기라는 이유로 쉬게 하자고 제안하지 않는다(원문 §8.4, D-103)
            continue
        idle = idle_days(seed, today)
        if idle >= days:
            since, kind = basis_of(seed)
            found.append(IdleProposal(seed.seed_id, seed.keyword, since, idle, seed.last_selected_on is None, kind))
    return tuple(sorted(found, key=lambda proposal: (-proposal.idle_days, proposal.seed_id)))


# ---- 쓸 수 있는 씨앗 -----------------------------------------------------------------------------------------------------------------
def usable_seeds(seeds, channel):
    """`channel` 의 후보를 만드는 데 쓸 수 있는 씨앗 — 상태가 사용 중(`active`)이고 **허용 채널(`allowed_channels`)에 그 채널이 들어 있는 것**. 제안·쉬는 중 씨앗은 쓰지 않는다.
    우선 표시한 씨앗이 앞이고 그다음은 대분류·중분류·씨앗 낱말·씨앗 번호 순이다(결정적). `channel` 은 코드 키나 입력 별칭(blogger_a·blogger_b)이거나 **채널 프로필(`ChannelProfile`)** 이다 —
    프로필을 주면 그 채널의 **후보 생성이 꺼져 있을 때(`generation_enabled` 가 아님) 쓸 수 있는 씨앗이 없다**(씨앗은 제안·등록·승인할 수 있지만 후보 생성은 채널을 켜기 전까지 꺼져 있다).
    이름만 주면 채널 켜짐은 보지 않는다(부른 쪽이 따로 본다). 판 1 씨앗은 허용 채널이 기본값(공통은 다섯 채널 모두·채널 전용은 그 채널)이라 예전과 같은 씨앗이 나온다."""
    profile = channel if isinstance(channel, ChannelProfile) else None
    code = canonical(profile.key if profile is not None else channel)
    pool = tuple(seeds)
    if not all(isinstance(seed, Seed) for seed in pool):
        raise TypeError("씨앗(Seed)만 넘길 수 있다")
    if profile is not None and not profile.generation_enabled:
        return ()
    chosen = [seed for seed in pool if seed.state == STATE_ACTIVE and code in seed.allowed_channels]
    return tuple(sorted(chosen, key=lambda seed: (not seed.priority, seed.major, seed.minor, keyword_key(seed.keyword), seed.seed_id)))


# ---- seeds.json 모양 ------------------------------------------------------------------------------------------------------------------
def seeds_to_dict(seeds):
    """씨앗 목록 → 저장 모양(`schema` 2, 입력 순서 그대로). 빈 목록이 '빈 틀' 이다. 다시 `seeds_from_dict` 로 읽으면 같은 씨앗들이 된다."""
    pool = tuple(seeds)
    _check_all(pool)
    return {"schema": SCHEMA, "seeds": [seed.to_dict() for seed in pool]}


def seeds_from_dict(data):
    """저장된 모양 → 씨앗들(파일 순서). `schema`(1 이나 2)·정확한 칸을 요구하고 모르는 칸·틀린 값·같은 번호 두 번·같은 소속의 같은 낱말 두 번·`MAX_SEEDS` 초과는 `CONTENT_INVALID` 로 거절한다.
    판 1 의 씨앗은 새 칸이 기본값으로 채워진다(파일은 바뀌지 않는다). 더 새로운 판(3 이상)은 이 프로그램이 읽을 수 없어 거절한다."""
    item = "씨앗 저장 형식"
    version = data.get("schema") if isinstance(data, dict) else None
    if not isinstance(data, dict) or type(version) is not int or version not in SCHEMAS:
        newer = isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA
        raise _invalid(item, f"{wording.FILE_KEY_KO['schema']}가 1이나 2인 씨앗 목록 파일이 아닙니다" + (" — 더 새로운 프로그램이 만든 파일이면 프로그램을 업데이트하세요" if newer else ""),
                       dev="저장된 씨앗 목록의 모양(schema 1·2)이 아니다")
    if set(data) != {"schema", "seeds"}:
        raise _invalid(item, wording.quoted(("schema", "seeds"), names=wording.FILE_KEY_KO) + " 두 칸만 있어야 합니다", dev="schema 와 seeds 두 칸만 있어야 한다")
    entries = data["seeds"]
    if not isinstance(entries, list):
        raise _invalid(item, f"{wording.quote(wording.FILE_KEY_KO['seeds'])} 은 여러 개를 담는 목록이어야 합니다", dev="seeds 는 목록이어야 한다")
    if len(entries) > MAX_SEEDS:
        raise _invalid(item, f"씨앗은 {MAX_SEEDS}개까지다")
    made = []
    for number, entry in enumerate(entries, start=1):
        try:
            made.append(Seed.from_dict(entry, schema=version))
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
        raise _invalid("씨앗 목록", "같은 씨앗 번호가 두 번 들어 있습니다: " + wording.quoted(twice), dev=f"겹친 번호: {twice}")
    keys = Counter((seed.scope, keyword_key(seed.keyword)) for seed in pool)
    again = sorted({seed.keyword for seed in pool if keys[(seed.scope, keyword_key(seed.keyword))] > 1})
    if again:
        raise _invalid("씨앗 목록", "같은 소속에 같은 씨앗 낱말이 두 번 들어 있습니다: " + wording.quoted(again), dev=f"겹친 낱말: {again}")


# ---- 씨앗 제안 파일(승인 전 목록)을 읽기 -------------------------------------------------------------------------------------------------------
# 모양: {schema_note, proposal_version, default_status, seeds[]} — seeds 의 한 칸 묶음이 아래 열여섯 칸(계절 씨앗은 `season` 이 더해진다). 읽은 씨앗은 **모두 승인 전(`proposed`)** 이다:
# 파일의 `default_status` 가 무엇이든 무시한다(승인하기 전에는 후보 생성에 쓰지 않는다 — 운영자 결정). 이 모듈은 파일을 읽지 않는다 — 부르는 쪽이 읽어서 사전을 넘긴다.
PROPOSAL_VERSIONS = ("v1",)
PROPOSAL_TOP_KEYS = ("schema_note", "proposal_version", "default_status", "seeds")
PROPOSAL_REQUIRED = ("id", "scope", "allowed_channels", "language", "category_l1", "category_l2", "keyword", "target_type", "importance", "priority_keywords", "exclude_keywords", "monetization_tags",
                     "reason", "generation", "needs_region", "brand_case")
PROPOSAL_SEASON_KEYS = ("prepare_from", "publish_from", "publish_until", "peak_from", "peak_to", "recurrence")
PROPOSAL_LANGUAGES = ("ko", "en")
PROPOSAL_GENERATIONS = ("active_first", "default_off")
PROPOSAL_FIELD_KO = MappingProxyType({
    "id": "씨앗 번호", "scope": "소속", "allowed_channels": "허용 채널", "language": "언어", "category_l1": "대분류", "category_l2": "중분류", "keyword": "씨앗 낱말", "target_type": "대상 유형",
    "importance": "중요도", "priority_keywords": "우선 키워드", "exclude_keywords": "제외 키워드", "monetization_tags": "협찬 가능 분야 태그", "reason": "제안 이유", "generation": "후보 생성 구분",
    "needs_region": "지역 값 필요", "brand_case": "브랜드 예외", "season": "계절 일정"})


class ProposalRead(NamedTuple):
    total: int                                      # 파일에 있던 씨앗 수
    seeds: tuple                                    # `Seed` — 읽은 순서, 모두 승인 전(`proposed`)
    rejected: tuple                                 # (이름, 쉬운 말 이유) — 읽을 수 없어 뺀 씨앗(이름은 씨앗 번호, 없으면 'N번째 씨앗')
    notes: tuple                                    # 쉬운 말 안내(예: 파일이 적은 상태를 무시했다)


def _proposal_label(entry, number):
    found = entry.get("id") if isinstance(entry, dict) else None
    return found if isinstance(found, str) and _ID.fullmatch(found) else f"{number}번째 씨앗"


def _proposal_seed(entry, today):
    """제안 파일의 씨앗 한 건 → `Seed`(승인 전). 칸이 틀렸으면 `CONTENT_INVALID`."""
    if not isinstance(entry, dict):
        raise _invalid("제안 씨앗", "칸이 있는 묶음(JSON 객체)이어야 한다")
    keys = set(entry)
    allowed = {*PROPOSAL_REQUIRED, "season"}
    unknown, missing = sorted(map(str, keys - allowed)), sorted(set(PROPOSAL_REQUIRED) - keys)
    if unknown or missing:
        raise _invalid("제안 씨앗", wording.unknown_and_missing(unknown, missing, PROPOSAL_FIELD_KO), dev=f"모르는 칸 {unknown}, 빠진 칸 {missing}")
    _choice(entry["language"], PROPOSAL_LANGUAGES, "언어", wording.LANGUAGE_KO)
    _choice(entry["generation"], PROPOSAL_GENERATIONS, "후보 생성 구분", MappingProxyType({"active_first": "승인 뒤 바로 후보 생성", "default_off": "후보 생성 꺼짐"}))
    tags = entry["monetization_tags"]
    if not isinstance(tags, (list, tuple)) or len(tags) > 1:
        raise _invalid("협찬 가능 분야 태그", "한 씨앗에 하나까지만 쓸 수 있다(지금 구조는 협찬 태그가 하나다)")
    values = dict(seed_id=entry["id"], major=entry["category_l1"], minor=entry["category_l2"], keyword=entry["keyword"], seed_type=entry["importance"], scope=entry["scope"],
                  priority=entry["importance"] == "priority", excluded_keywords=entry["exclude_keywords"], sponsor_tag=tags[0] if tags else None, state=STATE_PROPOSED, registered_on=today,
                  target_type=entry["target_type"], allowed_channels=entry["allowed_channels"], priority_keywords=entry["priority_keywords"], reason=entry["reason"],
                  needs_region=entry["needs_region"], brand_case=entry["brand_case"])
    if "season" in entry:
        values.update(_proposal_season(entry["season"]))
    return Seed(**values)


def _proposal_season(season):
    if not isinstance(season, dict):
        raise _invalid("계절 일정", "칸이 있는 묶음(JSON 객체)이어야 한다")
    unknown, missing = sorted(map(str, set(season) - set(PROPOSAL_SEASON_KEYS))), sorted(set(PROPOSAL_SEASON_KEYS) - set(season))
    if unknown or missing:
        raise _invalid("계절 일정", "모르는 칸이나 빠진 칸이 있습니다(준비 시작일·발행 시작일·발행 종료일·피크 시작·피크 끝·반복)", dev=f"모르는 칸 {unknown}, 빠진 칸 {missing}")
    peaks = (season["peak_from"], season["peak_to"])
    if (peaks[0] is None) != (peaks[1] is None):
        raise _invalid("피크 기간", "시작과 끝을 함께 적거나 둘 다 비워야 한다")
    return {"prepare_from": season["prepare_from"], "publish_from": season["publish_from"], "publish_until": season["publish_until"], "peak_period": None if peaks[0] is None else peaks,
            "recurrence": season["recurrence"]}


def parse_proposals(data, today):
    """씨앗 제안 파일의 내용(사전) → `ProposalRead`. 파일 전체의 모양이 틀리면 `CONTENT_INVALID`, 씨앗 하나가 틀리면 그 씨앗만 (이름, 이유)로 `rejected` 에 담고 나머지는 계속 읽는다.
    읽은 씨앗은 모두 `proposed`(승인 전)·등록일 `today` 이다 — 파일이 다른 상태를 적었어도 무시한다(그 사실은 `notes` 로 알린다). 같은 파일 안에서 같은 번호·같은 소속의 같은 낱말이 다시 나오면 **뒤의 것을** 뺀다."""
    item = "씨앗 제안 파일"
    _day(today, "오늘 날짜")
    if not isinstance(data, dict):
        raise _invalid(item, "칸이 있는 묶음(JSON 객체)이어야 한다")
    unknown = sorted(map(str, set(data) - set(PROPOSAL_TOP_KEYS)))
    if unknown or "seeds" not in data:
        raise _invalid(item, "모르는 칸이 있거나 씨앗 목록(seeds)이 없습니다", dev=f"모르는 칸 {unknown}, seeds 있음: {'seeds' in data}")
    version = data.get("proposal_version")
    if "proposal_version" in data and (not isinstance(version, str) or version not in PROPOSAL_VERSIONS):
        raise _invalid(item, "제안 파일 형식 번호가 이 프로그램이 아는 것(v1)이 아닙니다 — 더 새로운 형식이면 프로그램을 업데이트하세요")
    entries = data["seeds"]
    if not isinstance(entries, list):
        raise _invalid(item, "씨앗 목록(seeds)은 여러 개를 담는 목록이어야 합니다")
    if len(entries) > MAX_SEEDS:
        raise _invalid(item, f"씨앗은 {MAX_SEEDS}개까지다")
    notes = []
    if data.get("default_status", STATE_PROPOSED) != STATE_PROPOSED:
        notes.append("파일이 승인 전이 아닌 상태를 적었지만 무시합니다 — 불러온 씨앗은 모두 승인 전으로만 등록되고 승인하기 전에는 후보 생성에 쓰이지 않습니다")
    seeds, rejected, seen_ids, seen_words = [], [], set(), set()
    for number, entry in enumerate(entries, start=1):
        label = _proposal_label(entry, number)
        try:
            seed = _proposal_seed(entry, today)
        except AppError as error:
            rejected.append((label, _reason_of(error)))
            continue
        word = (seed.scope, keyword_key(seed.keyword))
        if seed.seed_id in seen_ids:
            rejected.append((label, "같은 씨앗 번호가 파일 안에 이미 있습니다(앞의 것만 읽습니다)"))
        elif word in seen_words:
            rejected.append((label, "같은 소속에 같은 씨앗 낱말이 파일 안에 이미 있습니다(앞의 것만 읽습니다)"))
        else:
            seen_ids.add(seed.seed_id)
            seen_words.add(word)
            seeds.append(seed)
    return ProposalRead(len(entries), tuple(seeds), tuple(rejected), tuple(notes))


def _reason_of(error):
    """칸 오류 → 한 줄 쉬운 말('씨앗의 씨앗 낱말 — 글자나 숫자가 하나도 없다')."""
    shown = str(error.slots.get("항목", "")) if isinstance(error, AppError) else ""
    return " ".join(shown.split())[:200] or "값이 올바르지 않습니다"


__all__ = [
    "ALL_TARGET_TYPES", "BASIS_REGISTERED", "BASIS_SELECTED", "BASIS_STARTED", "IDLE_DAYS", "INITIAL_COMMON", "INITIAL_PER_CHANNEL", "IdleProposal", "MAX_SEEDS", "PROPOSAL_FIELD_KO", "PROPOSAL_REQUIRED", "PROPOSAL_VERSIONS",
    "ProposalRead", "REGION_PLACEHOLDER", "SCHEMA", "SCHEMAS", "SCOPES", "SCOPE_COMMON", "SEED_FIELD_KO", "SEED_SEASONAL", "SEED_TYPES", "STATES", "STATE_ACTIVE", "STATE_INACTIVE", "STATE_KO", "STATE_PROPOSED", "Seed",
    "TARGET_BUNDLES", "TARGET_TYPES", "TRANSITIONS", "basis_of", "change_state", "idle_days", "idle_proposals", "parse_proposals", "quota_of", "seeds_from_dict", "seeds_to_dict", "selected", "usable_seeds",
    "with_region",
]
