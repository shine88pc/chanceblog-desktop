"""후보 조립 — 씨앗·캘린더·기존 글 이력·(선택) 관심도로 엔진 후보(`TopicCandidate`)를 **규칙만으로** 만들어 점수·구간·보류 만료일·중복·안전 표시까지 채운다(P2b — 순수 계산: 파일·네트워크·시계·난수·AI 없음,
같은 입력은 늘 같은 후보와 같은 후보 번호). AI 가 없어도 이 함수만으로 후보가 나온다(운영자 R-131 조건).

경로 다섯(`channels.SOURCE_MIX`: 씨앗 30·후속 20·계절 20·실시간 15·협찬 15 — `model.SOURCE_TYPES` 와 같은 이름):
  · seed      — 사용 중인 일반·우선 씨앗(`seeds.usable_seeds`)을 `expand.expand` 로 넓힌 후보(씨앗 하나에서 처음 `PER_SEED.first` 개를 만들고 점수 뒤 `keep` 개만 남긴다).
  · seasonal  — 계절 씨앗 중 캘린더(`schedule`)에서 **발행 기간 안(`due`)** 인 것.
  · follow_up — 같은 채널의 기존 글(`HistoryRecord`)마다 최대 `FOLLOW_UP_PER_POST`(3)개, 템플릿 문장(AI 아님).
  · sponsor   — 협찬 태그(`sponsor_tag`)가 있는 씨앗 → 협찬 준비형 후보(협업 **가능성**일 뿐이라 표시를 붙이지 않는다 — 확정된 협찬 정보(`campaigns`)가 있을 때만 표시를 강제한다. 고지 문구는 만들지 않는다 — P6).
  · realtime  — **운영자가 넣은** 이슈(`RealtimeItem`)뿐이다. 엔진은 후보를 지어내지 않고 출처 조건(공식 1 또는 서로 독립인 둘)과 48시간 안정화만 검사한다(`check_realtime`, 결정 H).
**총 후보 수 목표를 경로별 개수로 나누는 결정적 함수**(`route_targets` — 가장 큰 나머지 방식, 같으면 경로 순서)가 있고, 모자란 경로의 자리는 다른 경로가 가져가지 않는다(진단에 '부족' 으로 적는다).
협찬 몫(15%)은 후보 생성이 켜진 네이버 A·B 에만 적용한다(운영자 R-149 의 기본값 B=1) — 다른 채널은 협찬을 뺀 나머지 경로의 비율로 나눈다.

각 후보의 6항목(`score.Factors`)은 아래 **문서화된 초기 규칙**으로 채우고 알 수 없는 항목은 `None` 으로 둔다(점수 계산이 빼고 다시 나눈다 — 0점이 아니다). **초기값 — 전략 원문 확인 전.**
  · 채널 적합도: 60 + 20(씨앗이 이 채널 전용) + 15(주제 묶음이 채널 프로필의 묶음) + 10(채널 프로필의 방향 낱말) + 5(우선 씨앗) — 기존 글의 후속은 70, 운영자가 넣은 이슈는 60(+15 묶음).
  · 작성 가능성: `feasibility.assess_candidate` 의 점수.
  · 차별성: 같은 채널의 기존 글과 가장 비슷한 정도(%)를 100 에서 뺀 값 — **견줄 기존 글이 없으면 None**(0점·100점이 아니라 모름).
  · 시기: 캘린더 상태(`schedule.state_of`)와 관심도 상태로 `score.timing_score`(채널의 관심도 사용 정도를 따른다). '시기 도달 + 관심도 하락' 도 보류 구간으로 강제하지 않고 점수만 낮춘다(R-149 의 C=0).
  · 근거: 글 종류별 기본 점수(`EVIDENCE_BASE`) − 건강 20(**근거가 필요한 주장 — 건강 판정 B 근거 확인 필요·C 의료·효과 단정 위험 — 이면서 근거가 없을 때만**, A 표시만은 0, D-106)·경험 단정 표시 10(두 가지뿐 — 일반 낱말·글 종류로는 깎지 않는다)
    + 기존 글의 후속 10, 운영자가 넣은 이슈는 공식 출처가 있으면 90·독립 출처 둘이면 75(근거 있음 — 감점하지 않는다). 씨앗·후속·계절·협찬 경로는 아직 근거 자료 칸이 없어 B·C 에서 감점된다(알려진 한계).
  · 수익화: 채널이 우선 수익화 분야를 정하지 않았으면 None, 협찬 태그가 채널 분야에 있으면 100(없으면 60), 태그가 없으면 주제 묶음이 채널 분야와 이어질 때 70(아니면 30).
점수·추천 구간(`score.band_of`)·보류 만료일(`hold.expiry_for`)·중복 표시(`dedupe.marked`)·안전 표시(`safety.mark`)는 모두 기존 부품이 정한다 — 이 모듈은 숫자만으로 후보를 지우거나 제외하지 않는다(경로별 상한을 넘는 것만 세어서 뺀다).

후보 번호는 `tc-<채널>-<경로>-<16자리 16진수>` 이고 16진수는 (채널·경로·씨앗 또는 글 번호·방향)의 안정된 해시(`expand.stable_id`)다 — 날짜를 넣지 않아 같은 출처의 후보는 며칠이 지나도 같은 번호다(그래서 `existing` 에 있는 번호는 다시 만들지 않는다).
원천 주제 번호 `src-…` 는 채널을 넣지 않고 씨앗 낱말·방향(또는 글 번호·이슈 주제)으로만 정해서 같은 주제를 두 채널에 쓰면 같은 번호가 된다(`dedupe.check_topic_spread`). 만든 시각(`created_at`)은 기준일의 0시(UTC)이고 호출하는 쪽이 따로 줄 수 있다.
"""
from __future__ import annotations

import dataclasses
import re
from datetime import timedelta
from types import MappingProxyType
from typing import NamedTuple

from ..content.candidates import keyword_key, parse_stamp
from ..errors import AppError
from . import brand, dedupe, expand, feasibility, hold, safety, schedule, score, wording
from .channels import CHANNELS, FOLLOW_UP_PER_POST, PER_SEED, SOURCE_MIX, USE_NONE, ChannelProfile
from .history import HistoryRecord, valid_day
from .model import TopicCandidate, check_candidate_expiry, check_candidate_score
from .schedule import CalendarEntry
from .seeds import Seed, usable_seeds, with_region

ROUTES = tuple(SOURCE_MIX)                                        # seed·follow_up·seasonal·realtime·sponsor — 경로 순서(나눌 때의 동점 순서)
ROUTE_TYPES = MappingProxyType({"seed": ("seed", "evergreen"), "follow_up": ("follow_up", "follow_up"), "seasonal": ("seasonal", "seasonal"), "realtime": ("realtime", "realtime"),
                                "sponsor": ("sponsor", "sponsor_prep")})        # 경로 → (후보가 생긴 경로 `source_type`, 후보 종류 `candidate_type`)
ROUTE_KO = MappingProxyType({"seed": "씨앗", "follow_up": "후속", "seasonal": "계절", "realtime": "실시간", "sponsor": "협찬"})
# 계절 씨앗이 가진 일정의 그날 상태(`schedule.seasonal_state`) → 시기 점수에 넘기는 캘린더 상태(P3b-1, 운영자 결정 6): 발행 기간 안이면 우선 추천 평가(`due`), 준비 시작일에 닿으면 일반 우선순위로 돌아와 시기가 가산도
# 감점도 하지 않고(`unknown` — 점수 계산이 빼고 다시 나눈다), 시즌 밖이면 활성은 그대로 두고 우선순위만 낮춘다(`out_of_range`). 점수 표는 그대로다 — 어느 경우에도 씨앗을 쉬게 하거나 후보 생성에서 빼지 않는다.
SEASON_CALENDAR = MappingProxyType({schedule.SEASON_PUBLISHING: score.CALENDAR_DUE, schedule.SEASON_PREPARING: score.CALENDAR_UNKNOWN, schedule.SEASON_OFF: score.CALENDAR_OUT_OF_RANGE})
# 관심도(Trend)가 없어 시기를 캘린더만으로 봤을 때 계절 후보의 선정 이유에 붙는 말(운영자 2026-11-06 지시 3: 관심도 값이 없으면 캘린더 점수를 유지하고 데이터 부족 상태를 표시한다 — 글만 더하고 점수는 바뀌지 않는다).
# 관심도를 아예 쓰지 않는 채널(`trend_use` 가 none)은 부족한 것이 아니라 쓰지 않는 것이라 붙이지 않는다. 자료 상태 `insufficient`(값 없음·부족)와 `unavailable`(조회 불가)만 말한다.
TREND_SHORTAGE_NOTES = MappingProxyType({score.DATA_INSUFFICIENT: "관심도 데이터가 부족해 시기는 캘린더만으로 봤습니다", score.DATA_UNAVAILABLE: "관심도를 조회할 수 없어 시기는 캘린더만으로 봤습니다"})
SPONSOR_CHANNELS = ("naver_a", "naver_b")                         # 협찬 몫(15%)을 적용하는 채널 — 후보 생성이 켜진 네이버 A·B 뿐이다(R-149 B=1)
DEFAULT_TARGET, MAX_TARGET = 20, 200                              # 채널당 후보 수 목표(초기값)와 상한
REALTIME_STABLE_HOURS = 48                                        # 이슈가 처음 알려진 뒤 이만큼(포함) 지나야 쓴다(48시간 안정화 — 결정 H)
MIN_OFFICIAL, MIN_INDEPENDENT = 1, 2                              # 출처 조건: 공식 출처 1개 또는 서로 독립인 출처 2곳
MAX_SOURCES = 10
TWO_LEVEL_SUFFIXES = ("co.kr", "or.kr", "go.kr", "ne.kr", "re.kr", "ac.kr", "pe.kr", "co.jp", "co.uk", "com.au", "com.cn", "com.tw")        # 사이트 구분에서 세 마디로 보는 끝말(초기값)

# 주제 문장 틀(글 종류 → 틀, 초기값) — `{kw}` 는 씨앗 낱말, `{dir}` 는 방향 낱말. 발행 제목이 아니다(추천 포스팅 주제).
TOPIC_TEMPLATES_KO = MappingProxyType({
    "buying_guide": "{kw} {dir}, 고르기 전에 확인할 것", "comparison": "{kw} {dir}, 무엇이 다른지 한눈에 보기", "checklist": "{kw} {dir}, 빠뜨리기 쉬운 것 점검하기",
    "how_to_guide": "{kw} {dir}, 처음부터 차근차근 따라 하기", "troubleshooting": "{kw} {dir}, 원인을 찾아 순서대로 풀기", "place_guide": "{kw} {dir}, 가기 전에 알아 두면 좋은 것",
    "news_analysis": "{kw} {dir}, 무슨 일이고 왜 중요한지 정리", "explainer": "{kw} {dir}, 알아 두면 좋은 내용 정리", "routine_plan": "{kw} {dir}, 부담 없이 이어 가는 방법",
    "dev_log": "{kw} {dir}, 과정과 결과 정리", "service_intro": "{kw} {dir}, 어떤 서비스인지 쉽게 소개",
})
TOPIC_TEMPLATE_EN = "{kw} {dir}: a simple note on what to know"
TARGET_READERS = MappingProxyType({
    "github_pages": "기술과 산업의 변화를 쉽게 이해하고 싶은 일반 독자", "blogger_ko": "생활 습관과 정리를 가볍게 시작하려는 독자", "blogger_en": "readers who want a simple, low-pressure everyday routine",
    "naver_a": "집에서 쓸 제품이나 가볼 곳을 고르려는 생활 독자", "naver_b": "AI·PC·자동화 도구를 직접 써 보려는 일반 사용자",
})
# 기존 글의 후속 후보 템플릿 세 가지(초기값): (식별자, 한국어 주제 틀, 한국어 키워드 덧붙임, 영어 주제 틀, 영어 키워드 덧붙임, 글 종류, 검색 의도, 관점 식별자) — `{kw}` 는 그 글의 첫 키워드
FOLLOW_UP_TEMPLATES = (
    ("revisit", "{kw}, 시간이 지난 뒤 다시 확인할 것", "점검", "{kw}: what to check again later", "check-in", "checklist", "information", "follow-up-revisit"),
    ("faq", "{kw}, 자주 묻는 질문 정리", "자주 묻는 질문", "{kw}: frequently asked questions", "faq", "explainer", "information", "follow-up-faq"),
    ("deeper", "{kw}, 상황별로 나눠 더 자세히 보기", "상황별 정리", "{kw}: a closer look by situation", "by situation", "explainer", "information", "follow-up-deeper"),
)
EVIDENCE_BASE = MappingProxyType({
    "explainer": 70, "how_to_guide": 80, "checklist": 80, "troubleshooting": 75, "buying_guide": 60, "comparison": 60, "place_guide": 60, "news_analysis": 50, "routine_plan": 85, "dev_log": 85,
    "service_intro": 65,
})
EVIDENCE_PENALTY = MappingProxyType({"health_check": 20, "experience_claim": 10})        # 근거 감점은 이 둘뿐이다(P2b 보완 D-54 — 일반 낱말·글 종류로는 감점하지 않는다). 건강 20 은 B·C 단계에서 근거가 없을 때만(D-106)
EVIDENCE_OWN_POST_BONUS = 10
EVIDENCE_OFFICIAL, EVIDENCE_INDEPENDENT = 90, 75
CLUSTER_MONETIZATION = MappingProxyType({
    "small-appliances": "small_appliance", "pc-peripherals": "pc_peripheral", "lodging-and-travel": "lodging_travel", "ai-services": "ai_service", "pc-parts": "pc_parts",
    "work-automation": "work_automation",
})
FIT_BASE, FIT_OWN_SCOPE, FIT_CLUSTER, FIT_DIRECTION, FIT_PRIORITY, FIT_FOLLOW_UP = 60, 20, 15, 10, 5, 70
MONETIZATION_TAG_IN_FOCUS, MONETIZATION_TAG_OUTSIDE, MONETIZATION_CLUSTER_IN_FOCUS, MONETIZATION_NONE = 100, 60, 70, 30

DROP_NO_SEED, DROP_NOT_DUE, DROP_NO_KEYWORD, DROP_INVALID, DROP_PROMISE, DROP_EXISTS, DROP_OVER_TARGET, DROP_KEEP, DROP_OTHER_CHANNEL, DROP_SOURCES, DROP_UNSTABLE = (
    "no_seed", "not_due", "no_keyword", "invalid", "result_promise", "already_exists", "over_target", "per_seed_keep", "other_channel", "sources", "unstable")
DROP_BRAND_ONLY, DROP_BRAND_UNFEASIBLE = "brand_only", "brand_unfeasible"            # 브랜드 이름만 있는 씨앗을 구체화하지 못해 후보 없이 보류한 이유(P2b 보완 D-55)
DROP_REASONS = (*expand.BLOCK_REASONS, DROP_NO_SEED, DROP_NOT_DUE, DROP_NO_KEYWORD, DROP_INVALID, DROP_PROMISE, DROP_EXISTS, DROP_OVER_TARGET, DROP_KEEP, DROP_OTHER_CHANNEL, DROP_SOURCES,
                DROP_UNSTABLE, DROP_BRAND_ONLY, DROP_BRAND_UNFEASIBLE)

_URL = re.compile(r"https?://([A-Za-z0-9.-]+)(?::[0-9]{1,5})?(?:[/?#]\S*)?", re.IGNORECASE)


# ---- 경로별 개수 ----------------------------------------------------------------------------------------------------------------------
def mix_for(profile):
    """채널의 후보 경로 비율(%) — `SOURCE_MIX` 에서 협찬은 후보 생성이 켜진 네이버 A·B 에만 둔다(R-149 B=1). 경로 순서 그대로의 사전이다."""
    if not isinstance(profile, ChannelProfile):
        raise TypeError("mix_for(채널 프로필) 로 불러야 한다")
    sponsor_on = profile.generation_enabled and profile.key in SPONSOR_CHANNELS
    return {route: SOURCE_MIX[route] for route in ROUTES if route != "sponsor" or sponsor_on}


def route_targets(total, weights):
    """총 후보 수 목표(`total`)를 경로별 개수로 나눈다 — 비율(`weights`: 경로 → 정수 비율)에 맞춰 내림하고 남는 자리는 소수 부분이 큰 경로부터 하나씩 준다(같으면 경로 순서). 합은 늘 `total` 이다.
    비율에 없는 경로는 0 이다. 정수 계산이라 부동소수점 오차가 없고 같은 입력은 늘 같은 결과다."""
    if not isinstance(total, int) or isinstance(total, bool) or not 0 <= total <= MAX_TARGET:
        raise ValueError(f"총 후보 수 목표는 0~{MAX_TARGET} 사이의 정수여야 한다")
    if not isinstance(weights, dict) or not weights or not set(weights) <= set(ROUTES) or not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in weights.values()):
        raise ValueError("비율은 경로 이름(" + ", ".join(ROUTES) + ")별 0 이상의 정수 사전이어야 한다")
    whole = sum(weights.values())
    if whole <= 0:
        raise ValueError("비율의 합이 0 이면 나눌 수 없다")
    base = {route: total * weights.get(route, 0) // whole for route in ROUTES}
    rest = {route: total * weights.get(route, 0) % whole for route in ROUTES}
    spare = total - sum(base.values())
    for route in sorted(ROUTES, key=lambda name: (-rest[name], ROUTES.index(name)))[:spare]:
        base[route] += 1
    return base


# ---- 이슈(실시간) 입력과 출처 조건 ---------------------------------------------------------------------------------------------------------
def site_key(url):
    """주소 → 사이트를 가르는 열쇠(`www.` 를 뗀 마지막 두 마디, `co.kr` 같은 끝말은 세 마디). http·https 주소가 아니거나 모양이 이상하면 None. 서로 다른 열쇠의 출처만 '서로 독립' 으로 센다."""
    match = _URL.fullmatch(url) if isinstance(url, str) and len(url) <= 500 else None
    if match is None:
        return None
    labels = [label for label in match.group(1).lower().split(".") if label]
    if len(labels) < 2 or any(len(label) > 63 for label in labels):
        return None
    if all(label.isdigit() for label in labels):
        return ".".join(labels)
    if labels[0] == "www":
        labels = labels[1:]
    if len(labels) < 2:
        return None
    take = 3 if ".".join(labels[-2:]) in TWO_LEVEL_SUFFIXES and len(labels) >= 3 else 2
    return ".".join(labels[-take:])


@dataclasses.dataclass(frozen=True, kw_only=True)
class Source:
    url: str                                        # 출처 주소(http·https)
    official: bool = False                          # 공식 출처인가 — 운영자가 판단해서 적는다(엔진은 알 수 없다)

    def __post_init__(self):
        if site_key(self.url) is None:
            raise ValueError("출처 주소는 공백 없는 http·https 주소(예: https://example.org/글)여야 한다")
        if not isinstance(self.official, bool):
            raise ValueError("공식 출처 여부(official)는 참·거짓이어야 한다")


@dataclasses.dataclass(frozen=True, kw_only=True)
class RealtimeItem:
    """운영자가 넣은 실시간 이슈 후보 — 엔진은 이것을 지어내지 않고 출처 조건과 48시간 안정화만 검사한다. 칸은 엔진 후보의 같은 이름 칸과 같고, 후보로 바뀔 때 그쪽 규칙(한 줄·약속 표현 거절 …)이 다시 검사한다."""
    channel: str
    topic: str
    primary_keyword: str
    topic_cluster: str
    topic_angle: str
    search_intent: str
    content_type: str
    first_reported_at: str                          # 이슈가 처음 알려진 시각(UTC `YYYY-MM-DDTHH:MM:SSZ`) — 48시간 안정화의 기준
    sources: tuple                                  # `Source` 들(1~10개)
    secondary_keywords: tuple = ()
    target_reader: str | None = None                # 없으면 채널의 기본 독자

    def __post_init__(self):
        if not isinstance(self.channel, str) or self.channel not in CHANNELS:
            raise ValueError("채널은 코드의 채널 이름이어야 한다: " + ", ".join(CHANNELS))
        if not isinstance(self.sources, (list, tuple)) or not 1 <= len(self.sources) <= MAX_SOURCES or not all(isinstance(item, Source) for item in self.sources):
            raise ValueError(f"출처(sources)는 Source 가 1~{MAX_SOURCES}개 든 목록이어야 한다")
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "secondary_keywords", tuple(self.secondary_keywords) if isinstance(self.secondary_keywords, (list, tuple)) else self.secondary_keywords)
        parse_stamp(self.first_reported_at, "이슈가 처음 알려진 시각")
        for name in ("topic", "primary_keyword", "topic_cluster", "topic_angle", "search_intent", "content_type"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} 은(는) 글이어야 한다")
        if not isinstance(self.secondary_keywords, tuple) or not all(isinstance(word, str) for word in self.secondary_keywords):
            raise ValueError("secondary_keywords 는 글의 목록이어야 한다")
        if self.target_reader is not None and not isinstance(self.target_reader, str):
            raise ValueError("target_reader 는 글이거나 None 이어야 한다")


class RealtimeVerdict(NamedTuple):
    ok: bool                                        # 출처 조건과 48시간 안정화를 모두 통과했나
    sources_ok: bool                                # 출처 조건(공식 1 또는 독립 2)을 채웠나
    stable: bool                                    # 처음 알려진 뒤 48시간이 지났나
    official: int                                   # 공식 출처의 수
    independent: int                                # 서로 독립인 출처(서로 다른 사이트)의 수
    hours: int | None                               # 처음 알려진 뒤 지난 시간(내림) — 시각이 앞뒤가 안 맞으면 None
    reasons: tuple                                  # 못 쓰는 이유(통과하면 빈 튜플)


def check_realtime(item, now):
    """실시간 이슈가 쓸 수 있는지 **출처 조건과 48시간 안정화만** 본다 — ① 공식 출처 1개 이상이거나 서로 독립인(서로 다른 사이트) 출처 2곳 이상 ② 처음 알려진 뒤 48시간(포함) 지남. 내용은 평가하지 않는다.
    `now` 는 UTC 시각 글(`YYYY-MM-DDTHH:MM:SSZ`)이고 시계를 읽지 않는다."""
    if not isinstance(item, RealtimeItem):
        raise TypeError("check_realtime(이슈 RealtimeItem, 지금 시각) 로 불러야 한다")
    moment = parse_stamp(now, "지금 시각")
    official = sum(1 for source in item.sources if source.official)
    independent = len({site_key(source.url) for source in item.sources})
    reasons = []
    sources_ok = official >= MIN_OFFICIAL or independent >= MIN_INDEPENDENT
    if not sources_ok:
        reasons.append(f"출처 조건을 채우지 못했습니다 — 공식 출처 {MIN_OFFICIAL}개 이상이거나 서로 독립인 출처 {MIN_INDEPENDENT}곳 이상이어야 하는데 공식 {official}개·독립 {independent}곳입니다")
    gap = moment - parse_stamp(item.first_reported_at, "이슈가 처음 알려진 시각")
    hours = None
    if gap < timedelta(0):
        reasons.append("이슈가 처음 알려진 시각이 지금보다 뒤라 안정화 시간을 셀 수 없습니다")
    else:
        hours = int(gap.total_seconds() // 3600)
        if hours < REALTIME_STABLE_HOURS:
            reasons.append(f"처음 알려진 뒤 {hours}시간밖에 지나지 않았습니다 — {REALTIME_STABLE_HOURS}시간이 지난 뒤에 씁니다(안정화)")
    stable = hours is not None and hours >= REALTIME_STABLE_HOURS
    return RealtimeVerdict(sources_ok and stable, sources_ok, stable, official, independent, hours, tuple(reasons))


# ---- 관심도(선택 입력) ------------------------------------------------------------------------------------------------------------------
class InterestReading(NamedTuple):
    """키워드 하나의 최근 관심도(상대값) — `generate(interest=…)` 에 `{키워드 열쇠: InterestReading}` 로 준다(열쇠는 `keyword_key(키워드)`). 값은 후보의 관심도 칸 규칙(`model.check_trend`)으로 검사된다."""
    status: str                                     # rising·flat·falling·insufficient
    ratio: int | None = None
    period: str | None = None
    compared_group: tuple = ()
    queried_on: str | None = None


# ---- 결과 모양 -----------------------------------------------------------------------------------------------------------------------
class RouteReport(NamedTuple):
    route: str
    target: int                                     # 이 경로에 나눠 준 목표 개수
    available: int                                  # 만든(점수까지 채운) 후보의 수 — 목표를 넘으면 점수가 높은 것만 남긴다
    made: int                                       # 실제로 내놓은 후보의 수(`min(available, target)`)
    shortage: int                                   # 목표에 모자란 수(`target - made`) — 다른 경로가 대신 채우지 않는다


class Dropped(NamedTuple):
    route: str
    reason: str                                     # `DROP_REASONS` 중 하나
    count: int                                      # 이 이유로 쓰지 않은 수
    detail: str                                     # 쉬운 한국어 이유(첫 사례)


class Generated(NamedTuple):
    channel: str
    candidates: tuple                               # `TopicCandidate` — 점수 높은 순(점수 없음은 맨 뒤), 같으면 경로 순서·후보 번호순
    routes: tuple                                   # `RouteReport` 다섯 개(경로 순서)
    dropped: tuple                                  # `Dropped` — 경로·이유 순서
    notes: tuple                                    # 전체 안내(쉬운 한국어)
    region_missing: tuple = ()                      # 지역 값이 필요한데 채널 프로필에 지역이 없어 후보를 만들지 않은 씨앗 번호들(오류가 아니다 — 알림만 한다, P3b-1)

    def shortages(self):
        """모자란 경로의 이름과 모자란 수 — 진단용."""
        return {report.route: report.shortage for report in self.routes if report.shortage}


class _Drops:
    """쓰지 않은 것을 (경로, 이유) 별로 세고 첫 사례의 설명을 남긴다."""

    def __init__(self):
        self._rows = {}

    def add(self, route, reason, detail, count=1):
        row = self._rows.setdefault((route, reason), [0, detail])
        row[0] += count

    def rows(self):
        return tuple(Dropped(route, reason, count, detail) for (route, reason), (count, detail) in sorted(self._rows.items(), key=lambda item: (ROUTES.index(item[0][0]), DROP_REASONS.index(item[0][1]))))


class _Ctx(NamedTuple):
    profile: ChannelProfile
    entries: tuple
    records: tuple
    today: str
    created_at: str
    interest: dict
    outage: bool
    existing: frozenset
    campaigns: tuple = ()                           # 이 채널에 닿는 협찬 정보(`safety.Campaign`) — 확정이면 협찬 표시를 강제한다


class _Extra(NamedTuple):
    """후보 하나를 점수 매길 때 경로가 더 알려 주는 것."""
    season: str | None = None                       # 씨앗이 가진 계절 일정의 그날 상태(`schedule.SEASON_STATES`) — 일정이 없는 씨앗은 None(옛 규칙: 캘린더 항목으로만 시기를 본다)
    seed: Seed | None = None
    direction_source: str | None = None             # channel·common(씨앗 경로에서 방향이 어디서 왔나)
    own_post: bool = False                          # 같은 채널의 기존 글에서 나온 후보인가
    official: int = 0                               # 실시간 이슈의 공식 출처 수
    independent: int = 0
    lines: tuple = ()                               # 경로가 앞에 붙일 선정 이유 줄


# ---- 후보 만들기와 점수 --------------------------------------------------------------------------------------------------------------
def _topic_text(language, content_type, keyword, direction):
    if language == "en":
        return TOPIC_TEMPLATE_EN.format(kw=keyword, dir=direction)
    return TOPIC_TEMPLATES_KO[content_type].format(kw=keyword, dir=direction)


def _distinct(primary, words):
    seen, out = {keyword_key(primary)}, []
    for word in words:
        key = keyword_key(word)
        if key and key not in seen:
            seen.add(key)
            out.append(word)
    return tuple(out)


def _promised(*texts):
    """글에 결과를 약속하는 표현(`safety.FLAG_PROMISE`)이 있는가 — 후보를 만들기 **전에** 본다(후보의 글칸은 약속 표현을 오류로 거절하므로, 그 전에 가려야 '쓰지 않는 이유' 가 정확히 남는다)."""
    return safety.FLAG_PROMISE in safety.check_text(list(texts)).flags


def candidate_type_of(route, seed=None):
    """경로(와 씨앗) → 후보 종류(`candidate_type`) — 만들 때 정하고 **기록만** 한다(후보를 비율에 맞추려고 늘리거나 줄이지 않는다). 경로의 값은 `ROUTE_TYPES` 그대로(씨앗 → 지속형·후속·계절형·실시간·협찬 준비형)이고,
    계절 경로의 씨앗이 매월 반복(`recurrence == monthly` — 원문 '월별')이면 월별 반복형(`monthly_recurring`)이다."""
    kind = ROUTE_TYPES[route][1]
    if kind == "seasonal" and seed is not None and getattr(seed, "recurrence", None) == schedule.RECURRENCE_MONTHLY:
        return "monthly_recurring"
    return kind


def _candidate_id(channel, route, *parts):
    return f"tc-{channel}-{route}-{expand.stable_id(channel, route, *parts)}"


def _source_topic_id(*parts):
    return "src-" + expand.stable_id("source-topic", *parts)


def _channel_fit(profile, cluster, extra):
    if extra.seed is not None:
        points = FIT_BASE + (FIT_OWN_SCOPE if extra.seed.scope == profile.key else 0) + (FIT_CLUSTER if cluster in profile.topic_clusters else 0)
        points += FIT_DIRECTION if extra.direction_source == "channel" else 0
        return min(100, points + (FIT_PRIORITY if extra.seed.priority else 0))
    if extra.own_post:
        return FIT_FOLLOW_UP
    return min(100, FIT_BASE + (FIT_CLUSTER if cluster in profile.topic_clusters else 0))


def _evidence(candidate, flags, extra, stage=None):
    """근거 점수. '근거 있음'(공식 출처 1개 이상 → 90, 서로 독립인 출처 2곳 이상 → 75 — 운영자가 넣은 이슈뿐)이면 감점하지 않고 그 값이다. 근거가 없으면 글 종류별 기본 점수에서 경험 단정 10 을 빼고,
    건강 20 은 **근거가 필요한 주장일 때만** 뺀다 — `stage`(`SafetyReport.stage`)가 B 근거 확인 필요·C 의료·효과 단정 위험일 때(D-106). A 표시만·일반은 0 이다. `stage` 를 안 주면(`None`) 건강 표시가 있으면 뺀다(옛 호출과 같다)."""
    if extra.official >= MIN_OFFICIAL:
        return EVIDENCE_OFFICIAL
    if extra.independent >= MIN_INDEPENDENT:
        return EVIDENCE_INDEPENDENT
    cut = sum(EVIDENCE_PENALTY[flag] for flag in flags if flag in EVIDENCE_PENALTY and (flag != safety.FLAG_HEALTH or safety.needs_evidence(stage)))
    points = EVIDENCE_BASE[candidate.content_type] - cut + (EVIDENCE_OWN_POST_BONUS if extra.own_post else 0)
    return max(0, min(100, points))


def _monetization(profile, candidate, extra):
    focus = profile.monetization_focus
    if not focus:
        return None                                  # 이 채널은 우선 수익화 분야를 정하지 않았다 — 평가 불가(0점이 아니다)
    own_tags = candidate.monetization_tags or ((extra.seed.sponsor_tag,) if extra.seed is not None and extra.seed.sponsor_tag else ())
    if own_tags:
        return MONETIZATION_TAG_IN_FOCUS if any(tag in focus for tag in own_tags) else MONETIZATION_TAG_OUTSIDE
    return MONETIZATION_CLUSTER_IN_FOCUS if CLUSTER_MONETIZATION.get(candidate.topic_cluster) in focus else MONETIZATION_NONE


ORDER_FIX_NOTE = "관심도 데이터 부족으로 최소 순서 보정"           # 보정이 일어난 후보의 선정 이유 줄에 들어가는 말(운영자 2026-11-06 22시대 지시 — 낱말 그대로)


class OrderFix(NamedTuple):
    factors: score.Factors                          # 보정한(또는 그대로인) 여섯 항목 점수 — 최종 점수는 늘 이 항목들의 가중 평균이다
    note: str | None                                # 보정이 일어났을 때만 선정 이유 줄 글, 아니면 None


def minimum_order(profile, factors, calendar, trend_used):
    """관심도(Trend)가 없을 때 계절 후보의 **최소 순서** — 발행 기간 점수 ≥ 준비 기간 점수 > 시즌 밖 점수(운영자 지시). 승인된 점수표(`TIMING_*`·가중치·구간)는 그대로 두고 **계산 지점에서만** 고친다.
    ① 준비 기간 점수 = 이 후보에서 시기 항목을 뺀 나머지 항목의 가중 평균(준비 중은 시기 항목을 빼고 다시 나누므로 같은 값이다) ② 발행 기간(`due`)인데 점수가 준비 기간 점수보다 낮으면 **최종 점수를 덮어쓰지 않고**
    시기 항목 값을 `max(표의 값, 준비 기간 점수)` 로 올린다 — 준비 기간 점수(정수)를 시기 항목 값으로 쓰면 가중 평균이 [점수 − 0.5, 점수 + 0.5) 안에 있어 반올림 뒤 최종 점수가 준비 기간 점수와 정확히 같다(점수 묶음 일관성 `check_card` 통과)
    ③ 시즌 밖(`out_of_range`)인데 점수가 준비 기간 점수 이상이면 시기 항목 값을 최종 점수가 준비 기간 점수보다 낮아지는 가장 큰 값으로 낮춘다(다른 항목이 모두 아주 낮을 때만 생기는 극단 — 맞추는 값이 없으면 그대로).
    관심도를 썼거나(`trend_used`)·시기 항목이 없거나·준비 중이거나·평가할 항목이 없으면 아무것도 바꾸지 않는다(한 글자도 안 바뀐다). 순수 계산 — 시계·난수·파일 없음."""
    if trend_used or calendar not in (score.CALENDAR_DUE, score.CALENDAR_OUT_OF_RANGE) or factors.timing is None:
        return OrderFix(factors, None)
    prepared = score.score(profile, dataclasses.replace(factors, timing=None)).final
    now = score.score(profile, factors).final
    if prepared is None or now is None:
        return OrderFix(factors, None)
    if calendar == score.CALENDAR_DUE:
        if now >= prepared:
            return OrderFix(factors, None)
        raised = max(score.TIMING_CALENDAR_ONLY[score.CALENDAR_DUE], prepared)
        fixed = dataclasses.replace(factors, timing=raised)
        return OrderFix(fixed, f"{ORDER_FIX_NOTE}: 발행 기간의 시기 점수를 {factors.timing}점에서 {raised}점으로 올려 준비 기간 점수({prepared}점)보다 낮지 않게 했습니다(승인된 점수표는 그대로입니다)")
    if now < prepared:
        return OrderFix(factors, None)
    for value in range(factors.timing - 1, -1, -1):
        fixed = dataclasses.replace(factors, timing=value)
        if score.score(profile, fixed).final < prepared:
            return OrderFix(fixed, f"{ORDER_FIX_NOTE}: 시즌 밖의 시기 점수를 {factors.timing}점에서 {value}점으로 낮춰 준비 기간 점수({prepared}점)보다 높지 않게 했습니다(승인된 점수표는 그대로입니다)")
    return OrderFix(factors, None)


def _season_line(seed, season, data_status=score.DATA_SUFFICIENT, trend_use=None):
    names = {schedule.SEASON_PUBLISHING: "발행 기간 안이라 우선 추천으로 평가했습니다", schedule.SEASON_PREPARING: "준비 시작일이 지나 일반 우선순위로 평가했습니다", schedule.SEASON_OFF: "시즌 밖이라 우선순위를 낮췄습니다(씨앗은 그대로 사용 중입니다)"}
    line = f"계절 일정: 씨앗의 일정(준비 시작 {seed.prepare_from} · 발행 {seed.publish_from}~{seed.publish_until})으로 보면 {names[season]}"
    shortage = None if trend_use == USE_NONE else TREND_SHORTAGE_NOTES.get(data_status)
    return line if shortage is None else f"{line} — {shortage}"


def _calendar_line(state):
    if state.state == score.CALENDAR_DUE:
        names = ", ".join(item.name for item in state.matched if item.phase == schedule.PHASE_PUBLISHING)
        return f"시기: 캘린더의 ‘{names}’ 발행 기간 안입니다"
    if state.state == score.CALENDAR_OUT_OF_RANGE:
        return "시기: 이어지는 캘린더 항목이 있지만 발행 기간 밖입니다(준비 중이거나 지난·아직 안 온 시기)"
    return "시기: 이어지는 캘린더 항목이 없어 캘린더로는 알 수 없습니다(모름 — 0점이 아닙니다)"


def _finish(ctx, base, extra):
    """기본 후보(점수 없음)에 6항목 점수·구간·보류 만료일·중복·안전 표시·선정 이유를 채운 후보. 마지막에 저장된 점수·기한 확인(`check_candidate_score`·`check_candidate_expiry`)을 스스로 거친다."""
    profile = ctx.profile
    found = dedupe.find_duplicates(base, ctx.records, profile)
    marked = dedupe.marked(base, found.matches, compared=found.compared)
    state = schedule.state_of(base, ctx.entries, ctx.today)
    calendar = state.state
    if extra.season is not None and calendar != score.CALENDAR_DUE:                  # 캘린더 항목이 '발행 기간 안' 이라 하면 그쪽이 이긴다(위로만) — 아니면 씨앗 자신의 일정이 정한다
        calendar = SEASON_CALENDAR[extra.season]
    reading = ctx.interest.get(keyword_key(base.primary_keyword))
    if reading is None and extra.seed is not None:
        reading = ctx.interest.get(keyword_key(extra.seed.keyword))
    trend = reading if reading is not None else InterestReading(score.TREND_INSUFFICIENT)
    timing = score.timing_score(calendar, trend.status, trend_use=profile.trend_use, outage=ctx.outage)
    report = safety.assess(base, campaigns=ctx.campaigns)
    feasible = feasibility.assess_candidate(base, profile)
    factors = score.Factors(
        channel_fit=_channel_fit(profile, base.topic_cluster, extra), feasibility=feasible.score, differentiation=None if found.highest is None else 100 - found.highest,
        timing=timing.score, evidence=_evidence(base, report.flags, extra, report.stage), monetization=_monetization(profile, base, extra))
    fix = minimum_order(profile, factors, calendar, timing.trend_used) if extra.season is not None else OrderFix(factors, None)             # 계절 씨앗 경로 후보에만 — 관심도가 없을 때 발행 ≥ 준비 > 시즌 밖
    factors = fix.factors
    result = score.score(profile, factors)
    if found.compared == 0:
        similar = "견줄 기존 글이 없어 차별성은 모름으로 두었습니다(0점·100점이 아닙니다)"
    else:
        similar = f"차별성: 같은 채널의 기존 글 {found.compared}개와 견줬고 가장 비슷한 글은 {found.highest}% 입니다"
    season_lines = () if extra.season is None else (_season_line(extra.seed, extra.season, timing.data_status, profile.trend_use),)
    if fix.note is not None:
        season_lines = (*season_lines, fix.note)
    reasons = (*extra.lines, *safety.notes(report), _calendar_line(state), *season_lines, similar, *feasible.reasons)[:10]            # 안전 줄을 경로 줄 바로 다음에 둔다 — 10줄 한도에 가장 중요한 줄이 먼저 잘리지 않게
    trend_fields = ({"trend_status": trend.status, "trend_ratio": trend.ratio, "trend_period": trend.period, "trend_compared_group": tuple(trend.compared_group), "trend_queried_on": trend.queried_on}
                    if reading is not None else {})
    final = dataclasses.replace(
        marked, scores=result.card, data_status=timing.data_status, review_expires_at=hold.expiry_for(result.band, ctx.created_at), safety_flags=report.flags, selection_reasons=reasons, **trend_fields)
    try:
        check_candidate_score(final, profile)
        check_candidate_expiry(final)
    except AppError as error:
        raise RuntimeError("후보 조립 규칙의 오류 — 만든 후보의 점수나 검토 기한이 규칙과 다르다: " + str(error)) from error
    return final


def _base(ctx, route, *, seed=None, **values):
    source_type = ROUTE_TYPES[route][0]
    candidate_type = candidate_type_of(route, seed)
    profile = ctx.profile
    values.setdefault("target_reader", TARGET_READERS[profile.key])
    return TopicCandidate(source_type=source_type, candidate_type=candidate_type, channel=profile.key, language=profile.language, created_at=ctx.created_at, **values)


def _seed_candidates(ctx, route, seeds, drops, *, as_type=None):
    """씨앗들 → 후보. 씨앗 하나에서 처음 `first` 개를 만들고 점수 높은 `keep` 개만 남긴다(`channels.PER_SEED`)."""
    pool = []
    for order, seed in enumerate(seeds):
        view = brand.assess(seed, ctx.profile, as_type=as_type)             # 브랜드 이름만 있는 씨앗은 일반 확장 대신 하위 후보로 구체화한다(P2b 보완 D-55). 아니면 이 아래는 지금 그대로다
        if view.applies:
            pool.extend(_brand_candidates(ctx, route, seed, order, view, drops, as_type=as_type))
            continue
        quota = PER_SEED[as_type or seed.seed_type]
        opened = expand.expand(seed, ctx.profile, limit=quota.first, as_type=as_type)
        for blocked in opened.blocked:
            drops.add(route, blocked.reason, f"씨앗 ‘{seed.keyword}’: {blocked.detail}")
        made = []
        for item_order, item in enumerate(opened.items):
            tags = (seed.sponsor_tag,) if route == "sponsor" else ()
            topic = _topic_text(ctx.profile.language, item.content_type, seed.keyword, item.direction)
            if _promised(topic, item.keyword):
                drops.add(route, DROP_PROMISE, f"씨앗 ‘{seed.keyword}’ 의 ‘{item.direction}’: 결과를 약속하는 표현이 있어 쓰지 않습니다")
                continue
            try:
                candidate = _base(
                    ctx, route, seed=seed, candidate_id=_candidate_id(ctx.profile.key, route, seed.seed_id, item.angle, item.direction),
                    source_topic_id=_source_topic_id(keyword_key(seed.keyword), item.angle), seed_id=seed.seed_id,
                    topic=topic, primary_keyword=item.keyword,
                    secondary_keywords=_distinct(item.keyword, (seed.keyword, item.direction)), search_intent=item.search_intent, content_type=item.content_type,
                    topic_cluster=expand.cluster_of(seed, ctx.profile), topic_angle=item.angle, monetization_tags=tags)
                if candidate.candidate_id in ctx.existing:
                    drops.add(route, DROP_EXISTS, f"씨앗 ‘{seed.keyword}’ 의 ‘{item.direction}’ 후보는 이미 있습니다(같은 번호)")
                    continue
                lines = (f"씨앗 ‘{seed.keyword}’ 에서 ‘{item.direction}’({expand.FAMILY_KO[item.family]} 계열)로 넓힌 {ROUTE_KO[route]} 후보입니다" +
                         (f" — 협업 가능 유형 {wording.tag_name(seed.sponsor_tag)}(협찬이 확정된 것은 아닙니다)" if route == "sponsor" else ""),)
                made.append((_finish(ctx, candidate, _Extra(seed=seed, direction_source=item.source, lines=lines, season=schedule.seasonal_state(seed, ctx.today))), order, item_order))
            except AppError as error:
                drops.add(route, DROP_INVALID, f"씨앗 ‘{seed.keyword}’ 의 ‘{item.direction}’ 후보가 규칙에 맞지 않습니다: {_why(error)}")
        made.sort(key=lambda row: (row[0].scores.final is None, -(row[0].scores.final or 0), row[2]))
        if len(made) > quota.keep:
            drops.add(route, DROP_KEEP, f"씨앗 ‘{seed.keyword}’ 에서 점수가 낮은 후보는 씨앗당 {quota.keep}개까지만 남깁니다", len(made) - quota.keep)
        pool.extend((candidate, order, item_order) for candidate, order, item_order in made[:quota.keep])
    return pool


def _brand_candidates(ctx, route, seed, order, view, drops, *, as_type):
    """브랜드 이름만 있는 씨앗(`brand.assess` 가 `BRAND_ONLY` 로 본 것) → 하위 후보(최대 3개). 일반 후보와 같은 `_finish`(6항목·중복·안전 표시)를 거친다.
    구체화하지 못하면 후보 없이 진단만 남긴다 — 보류('주제 구체화 필요' = `brand_only`, '작성 기반 부족' = `brand_unfeasible`). 씨앗·후보의 상태를 바꾸거나 저장하지 않는다."""
    for skipped in view.skipped:                                              # 막힌 틀·작성 가능성 탈락 — 일반 경로와 같은 이유 코드·같은 모양의 진단 줄
        drops.add(route, skipped.reason, f"씨앗 ‘{seed.keyword}’: {skipped.detail}", skipped.count)
    if view.outcome == brand.NEEDS_TOPIC:
        drops.add(route, DROP_BRAND_ONLY, f"씨앗 ‘{seed.keyword}’: {view.detail}")
        return []
    if not view.subtopics:                                                    # 작성 기반 부족 — 위 skipped 의 줄이 보류 기록이다
        return []
    quota = PER_SEED[as_type or seed.seed_type]
    keep = max(quota.keep, brand.MAX_SUBTOPICS) if brand.KEEP_ALL else quota.keep
    made = []
    for item_order, sub in enumerate(view.subtopics):
        if sub.brand_free:                                                    # 문장에 브랜드가 없는 틀은 씨앗이 달라도 같은 문장이라 씨앗 번호를 넣지 않는다(같은 번호는 하나만 남는다)
            candidate_id = _candidate_id(ctx.profile.key, route, "brand-free", view.brand_type, sub.angle)
            source_topic = _source_topic_id("brand-free", view.brand_type, sub.angle)
        else:
            candidate_id = _candidate_id(ctx.profile.key, route, "brand", seed.seed_id, sub.angle, sub.direction)
            source_topic = _source_topic_id("brand", keyword_key(view.hits[0].display), sub.angle)
        try:
            candidate = _base(
                ctx, route, seed=seed, candidate_id=candidate_id, source_topic_id=source_topic, seed_id=seed.seed_id, topic=sub.topic, primary_keyword=sub.keyword,
                secondary_keywords=_distinct(sub.keyword, (seed.keyword, sub.direction)), search_intent=sub.search_intent, content_type=sub.content_type,
                topic_cluster=expand.cluster_of(seed, ctx.profile), topic_angle=sub.angle, monetization_tags=(seed.sponsor_tag,) if route == "sponsor" else ())
            if candidate.candidate_id in ctx.existing:
                drops.add(route, DROP_EXISTS, f"씨앗 ‘{seed.keyword}’ 의 ‘{sub.direction}’ 후보는 이미 있습니다(같은 번호)")
                continue
            lines = (f"브랜드 ‘{seed.keyword}’ 만 있던 씨앗을 ‘{brand.TYPE_KO[view.brand_type]}’ 유형으로 구체화한 {ROUTE_KO[route]} 후보입니다 — 유형은 {brand.BASIS_KO[view.basis]} 정했고 ‘{sub.direction}’ 방향입니다" +
                     (f" — 협업 가능 유형 {wording.tag_name(seed.sponsor_tag)}(협찬이 확정된 것은 아닙니다)" if route == "sponsor" else ""),)
            made.append((_finish(ctx, candidate, _Extra(seed=seed, direction_source=sub.source, lines=lines, season=schedule.seasonal_state(seed, ctx.today))), order, item_order))
        except AppError as error:
            drops.add(route, DROP_INVALID, f"씨앗 ‘{seed.keyword}’ 의 ‘{sub.direction}’ 후보가 규칙에 맞지 않습니다: {_why(error)}")
    made.sort(key=lambda row: (row[0].scores.final is None, -(row[0].scores.final or 0), row[2]))
    if len(made) > keep:                                                      # 남길 수가 3 이상이라 하위 후보 3개 이하에서는 생기지 않는다
        drops.add(route, DROP_KEEP, f"씨앗 ‘{seed.keyword}’ 에서 점수가 낮은 후보는 씨앗당 {keep}개까지만 남깁니다", len(made) - keep)
    return [(candidate, order, item_order) for candidate, order, item_order in made[:keep]]


def _why(error):
    shown = str(error.slots.get("항목", "")) + (" — " + str(error.slots["이유"]) if error.slots.get("이유") else "")
    return " ".join(shown.split())[:120]


def _follow_up_candidates(ctx, drops):
    pool = []
    records = sorted((record for record in ctx.records if record.channel == ctx.profile.key), key=lambda item: (item.date is None, "" if item.date is None else _flip(item.date), item.ref or "", item.title))
    for order, record in enumerate(records):
        if not record.keywords:
            drops.add("follow_up", DROP_NO_KEYWORD, "기존 글에 키워드가 없어 후속 주제를 만들 수 없습니다(제목에서 지어내지 않습니다)")
            continue
        keyword = record.keywords[0]
        for item_order, (kind, topic_ko, suffix_ko, topic_en, suffix_en, content_type, intent, angle) in enumerate(FOLLOW_UP_TEMPLATES[:FOLLOW_UP_PER_POST]):
            post_key = record.ref or keyword_key(record.title)
            english = ctx.profile.language == "en"
            phrase = f"{keyword} {suffix_en if english else suffix_ko}"
            topic = (topic_en if english else topic_ko).format(kw=keyword)
            if _promised(topic, phrase):
                drops.add("follow_up", DROP_PROMISE, "기존 글의 키워드에 결과를 약속하는 표현이 있어 쓰지 않습니다")
                continue
            try:
                candidate = _base(
                    ctx, "follow_up", candidate_id=_candidate_id(ctx.profile.key, "follow_up", post_key, kind), source_topic_id=_source_topic_id("post", post_key, kind),
                    topic=topic, primary_keyword=phrase,
                    secondary_keywords=_distinct(phrase, (keyword, *record.keywords[1:3])), search_intent=intent, content_type=content_type, topic_cluster="post-" + expand.stable_id("post", post_key, digits=8),
                    topic_angle=angle)
                if candidate.candidate_id in ctx.existing:
                    drops.add("follow_up", DROP_EXISTS, "같은 기존 글의 같은 후속 후보는 이미 있습니다(같은 번호)")
                    continue
                lines = (f"같은 채널의 기존 글{'(글 번호 ' + record.ref + ')' if record.ref else ''}의 후속 후보입니다 — 템플릿 문장이고 AI 가 쓴 것이 아닙니다",)
                pool.append((_finish(ctx, candidate, _Extra(own_post=True, lines=lines)), order, item_order))
            except AppError as error:
                drops.add("follow_up", DROP_INVALID, f"기존 글의 키워드로 만든 후속 후보가 규칙에 맞지 않습니다: {_why(error)}")
    return pool


def _flip(day):
    """날짜 글(YYYY-MM-DD)을 '최근 것이 앞' 이 되게 뒤집은 정렬 열쇠."""
    return "".join(str(9 - int(ch)) if ch.isdigit() else ch for ch in day)


def _issue_key(item):
    """이슈를 늘 같은 순서로 처리하는 열쇠(처음 알려진 때 → 키워드 → 주제 → 나머지 칸) — 넣은 순서와 상관없이 진단의 첫 사례 문장과, 점수가 같을 때 목표를 넘겨 남는 후보가 같아진다(D-58)."""
    return (item.first_reported_at, keyword_key(item.primary_keyword), item.topic, item.primary_keyword, item.channel, item.topic_cluster, item.topic_angle, item.search_intent, item.content_type,
            item.secondary_keywords, item.target_reader or "", tuple((source.url, source.official) for source in item.sources))


def _realtime_candidates(ctx, items, drops):
    pool = []
    for order, item in enumerate(sorted(items, key=_issue_key)):
        if item.channel != ctx.profile.key:
            drops.add("realtime", DROP_OTHER_CHANNEL, "다른 채널용으로 넣은 이슈는 이 채널의 후보로 쓰지 않습니다")
            continue
        verdict = check_realtime(item, ctx.created_at)
        if not verdict.ok:
            drops.add("realtime", DROP_SOURCES if not verdict.sources_ok else DROP_UNSTABLE, "이슈 ‘" + " ".join(item.primary_keyword.split())[:30] + "’: " + verdict.reasons[0])
            continue
        if _promised(item.topic, item.primary_keyword, *item.secondary_keywords):
            drops.add("realtime", DROP_PROMISE, "이슈 글에 결과를 약속하는 표현이 있어 쓰지 않습니다")
            continue
        try:
            candidate = _base(
                ctx, "realtime", candidate_id=_candidate_id(ctx.profile.key, "realtime", keyword_key(item.topic), item.first_reported_at), source_topic_id=_source_topic_id("issue", keyword_key(item.topic)),
                topic=item.topic, primary_keyword=item.primary_keyword, secondary_keywords=_distinct(item.primary_keyword, item.secondary_keywords), search_intent=item.search_intent,
                content_type=item.content_type, topic_cluster=item.topic_cluster, topic_angle=item.topic_angle, target_reader=item.target_reader or TARGET_READERS[ctx.profile.key])
            if candidate.candidate_id in ctx.existing:
                drops.add("realtime", DROP_EXISTS, "같은 이슈 후보는 이미 있습니다(같은 번호)")
                continue
            lines = (f"운영자가 넣은 이슈입니다 — 출처 조건을 통과했습니다(공식 {verdict.official}개·서로 독립인 출처 {verdict.independent}곳, 처음 알려진 뒤 {verdict.hours}시간 지남)",)
            pool.append((_finish(ctx, candidate, _Extra(official=verdict.official, independent=verdict.independent, lines=lines)), order, 0))
        except AppError as error:
            drops.add("realtime", DROP_INVALID, f"운영자가 넣은 이슈가 규칙에 맞지 않습니다: {_why(error)}")
    return pool


def _with_regions(profile, usable, drops):
    """지역 값이 필요한 씨앗(`needs_region` — 낱말의 `{기준 지역}` 자리표시)을 채널 프로필의 지역 값으로 채운다 → (쓸 씨앗들, 지역이 없어 뺀 씨앗 번호들). 지역은 상시 이동권 목록의 첫 낱말, 없으면 당일 이동권 목록의 첫 낱말이다
    (여러 지역을 돌려 쓰는 것은 P4b 이후 정한다). **지역이 하나도 없으면 후보를 만들지 않고 뺀 번호를 알린다 — 오류가 아니다.** 채운 낱말이 씨앗 규칙(길이·표현)에 안 맞으면 그 씨앗만 이유와 함께 뺀다."""
    needy = [seed for seed in usable if seed.needs_region]
    if not needy:
        return usable, ()
    regions = (*profile.home_regions, *profile.day_trip_regions)
    if not regions:
        return tuple(seed for seed in usable if not seed.needs_region), tuple(sorted(seed.seed_id for seed in needy))
    kept = []
    for seed in usable:
        if not seed.needs_region:
            kept.append(seed)
            continue
        try:
            kept.append(with_region(seed, regions[0]))
        except AppError as error:
            drops.add("seed", DROP_INVALID, f"씨앗 ‘{seed.seed_id}’ 에 지역 값을 넣으면 규칙에 맞지 않습니다: {_why(error)}")
    return tuple(kept), ()


def _check_inputs(profile, seeds, calendar, history, today, existing, interest, realtime, target, created_at, campaigns=()):
    if not isinstance(profile, ChannelProfile):
        raise TypeError("generate(채널 프로필, 씨앗들, 캘린더, 기존 글들, 기준일) 로 불러야 한다")
    pools = (("seeds", seeds, Seed), ("calendar", calendar, CalendarEntry), ("history", history, HistoryRecord), ("existing", existing, TopicCandidate), ("realtime", realtime, RealtimeItem),
             ("campaigns", campaigns, safety.Campaign))
    checked = []
    for name, values, kind in pools:
        if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
            raise TypeError(f"{name} 는 {kind.__name__} 의 목록이어야 한다")
        items = tuple(values)
        if not all(isinstance(item, kind) for item in items):
            raise TypeError(f"{name} 에는 {kind.__name__} 만 들어 있어야 한다")
        checked.append(items)
    if len(checked[5]) > safety.MAX_CAMPAIGNS:
        raise ValueError(f"campaigns 는 {safety.MAX_CAMPAIGNS}개까지 넣을 수 있다")
    if valid_day(today) is None or int(today[:4]) > schedule.MAX_YEAR:
        raise ValueError(f"기준일(today)은 2026-11-05 같은 모양의 달력에 있는 날짜(2000~{schedule.MAX_YEAR}년)여야 한다")
    if not isinstance(target, int) or isinstance(target, bool) or not 0 <= target <= MAX_TARGET:
        raise ValueError(f"target 은 0~{MAX_TARGET} 사이의 정수여야 한다")
    stamp = f"{today}T00:00:00Z" if created_at is None else created_at
    parse_stamp(stamp, "만든 시각")
    if interest is not None and (not isinstance(interest, dict) or not all(isinstance(key, str) and isinstance(value, InterestReading) for key, value in interest.items())):
        raise TypeError("interest 는 {키워드 열쇠: InterestReading} 사전이거나 None 이어야 한다")
    if interest is not None and any(value.status not in score.TREND_STATUSES for value in interest.values()):
        raise ValueError("관심도 상태(status)는 다음 중 하나여야 한다: " + ", ".join(score.TREND_STATUSES))
    return (*checked, stamp)                                            # 씨앗·캘린더·이력·기존 후보·이슈·협찬 정보·만든 시각


def generate(profile, seeds, calendar, history, today, *, existing=(), interest=None, interest_outage=False, realtime=(), campaigns=(), target=DEFAULT_TARGET, created_at=None):
    """한 채널의 후보를 만든다 — `profile` 이 후보 생성이 꺼진 채널이면(`generation_enabled` 가 아님) 후보 없이 이유만 돌려준다. 입력은 바꾸지 않고 시계·난수·파일을 쓰지 않는다.
    `seeds`·`calendar`·`history`·`existing`(이미 있는 후보 — 같은 번호만 건너뛴다. 목표를 줄이지는 않는다: 기존 후보 수를 반영한 생성량은 P3, 계획 11.1)·`realtime`(운영자가 넣은 이슈)은 각각 `Seed`·`CalendarEntry`·`HistoryRecord`·`TopicCandidate`·`RealtimeItem` 의 목록이고
    `today` 는 기준일(YYYY-MM-DD)이다. `interest` 는 {`keyword_key(키워드)`: `InterestReading`} 이고 `interest_outage` 가 참이면 관심도를 조회하지 못한 것(자료 상태 unavailable)으로 본다.
    `campaigns`(`safety.Campaign` 의 목록)는 실제로 확정·제안된 협찬 정보다 — 이 채널에 닿는 것만 쓰고 확정이면 협찬 표시를 강제한다(없으면 협찬 가능성만 INFO 로 알린다).
    `target` 은 이 채널의 총 후보 수 목표(`route_targets` 가 경로별로 나눈다). 결과의 `routes` 에 경로마다 목표·만든 수·모자란 수가, `dropped` 에 쓰지 않은 것과 이유가 있다."""
    seed_list, entries, records, known, items, campaign_list, stamp = _check_inputs(profile, seeds, calendar, history, today, existing, interest, realtime, target, created_at, campaigns)
    if not isinstance(interest_outage, bool):
        raise TypeError("interest_outage 는 참·거짓이어야 한다")
    weights = mix_for(profile)
    targets = route_targets(target, weights)
    drops, pools = _Drops(), {route: [] for route in ROUTES}
    notes = []
    if not profile.generation_enabled:
        notes.append(f"{profile.display_name} 은(는) 후보 생성이 꺼져 있어 후보를 만들지 않았습니다(이력 읽기·중복 검사만 합니다)")
        reports = tuple(RouteReport(route, 0, 0, 0, 0) for route in ROUTES)
        return Generated(profile.key, (), reports, (), tuple(notes))
    ctx = _Ctx(profile, entries, records, today, stamp, dict(interest or {}), interest_outage, frozenset(item.candidate_id for item in known),
               tuple(item for item in campaign_list if item.channel is None or item.channel == profile.key))
    usable = usable_seeds(seed_list, profile)                          # 사용 중이고 허용 채널에 이 채널이 든 씨앗(채널 켜짐도 본다 — 위에서 꺼진 채널은 이미 돌아갔다)
    usable, region_missing = _with_regions(profile, usable, drops)
    if not usable:
        drops.add("seed", DROP_NO_SEED, "이 채널에서 쓸 수 있는(사용 중이고 공통이거나 이 채널 전용인) 씨앗이 없습니다")
    pools["seed"] = _seed_candidates(ctx, "seed", [seed for seed in usable if seed.seed_type in ("general", "priority")], drops)
    seasonal = []
    for seed in (seed for seed in usable if seed.seed_type == "seasonal"):
        if schedule.seasonal_state(seed, today) is not None:                  # 자기 일정이 있는 씨앗 — 시즌 밖이어도 활성을 유지한다(후보 생성에서 빼지 않는다). 우선순위는 시기 점수가 낮춘다(`SEASON_CALENDAR`)
            seasonal.append(seed)
            continue
        found = schedule.calendar_state(entries, (seed.keyword,), today, profile.key)             # 일정이 없는 계절 씨앗(판 1) — 옛 규칙: 캘린더 항목이 발행 기간 안일 때만
        if found.state == score.CALENDAR_DUE:
            seasonal.append(seed)
        else:
            drops.add("seasonal", DROP_NOT_DUE, "계절 씨앗 ‘" + seed.keyword + ("’ 은(는) 이어지는 캘린더 항목이 없습니다" if found.state == score.CALENDAR_UNKNOWN else "’ 은(는) 아직(또는 이미) 발행 기간 밖입니다"))
    pools["seasonal"] = _seed_candidates(ctx, "seasonal", seasonal, drops)
    if "sponsor" in weights:
        pools["sponsor"] = _seed_candidates(ctx, "sponsor", [seed for seed in usable if seed.sponsor_tag and seed.seed_type != "realtime"], drops, as_type="sponsorable")
    pools["follow_up"] = _follow_up_candidates(ctx, drops)
    pools["realtime"] = _realtime_candidates(ctx, items, drops)
    chosen, reports, used = [], [], set()
    for route in ROUTES:
        ranked = sorted(pools[route], key=lambda row: (row[0].scores.final is None, -(row[0].scores.final or 0), row[1], row[2], row[0].candidate_id))
        unique = []
        for row in ranked:
            if row[0].candidate_id in used:
                drops.add(route, DROP_EXISTS, "같은 번호의 후보가 두 번 만들어져 하나만 씁니다(같은 씨앗이나 같은 이슈가 목록에 두 번 있습니다)")
                continue
            used.add(row[0].candidate_id)
            unique.append(row)
        ranked = unique
        kept = ranked[:targets[route]]
        if len(ranked) > len(kept):
            drops.add(route, DROP_OVER_TARGET, f"{ROUTE_KO[route]} 경로의 목표({targets[route]}개)를 넘어 점수가 낮은 후보는 쓰지 않습니다", len(ranked) - len(kept))
        chosen.extend((row[0], ROUTES.index(route)) for row in kept)
        reports.append(RouteReport(route, targets[route], len(ranked), len(kept), targets[route] - len(kept)))
    ordered = sorted(chosen, key=lambda row: (row[0].scores.final is None, -(row[0].scores.final or 0), row[1], row[0].candidate_id))
    short = [f"{ROUTE_KO[report.route]} {report.shortage}개" for report in reports if report.shortage]
    if short:
        notes.append("목표에 모자란 경로: " + ", ".join(short) + " — 모자란 자리는 다른 경로가 채우지 않았습니다")
    return Generated(profile.key, tuple(candidate for candidate, _route in ordered), tuple(reports), drops.rows(), tuple(notes), region_missing)


def generate_all(profiles, seeds, calendar, history, today, **options):
    """후보 생성이 켜진 채널마다 `generate` 를 부른 결과(채널 코드 순서). 꺼진 채널은 이유만 담은 빈 결과다. `options` 는 `generate` 의 선택 인자(`existing`·`interest`·`realtime`·`target`·`created_at`)이고 `existing`·`history`·`realtime` 은
    채널마다 그 채널의 것만 쓰인다. 채널 사이의 같은 주제 검사는 이 결과의 후보들을 `dedupe.check_topic_spread` 에 넘긴다."""
    ordered = tuple(sorted(profiles, key=lambda item: CHANNELS.index(item.key) if isinstance(item, ChannelProfile) else len(CHANNELS)))
    if not all(isinstance(item, ChannelProfile) for item in ordered):
        raise TypeError("profiles 는 ChannelProfile 의 목록이어야 한다")
    return tuple(generate(profile, seeds, calendar, history, today, **options) for profile in ordered)


__all__ = [
    "CLUSTER_MONETIZATION", "DEFAULT_TARGET", "DROP_BRAND_ONLY", "DROP_BRAND_UNFEASIBLE", "DROP_REASONS", "Dropped", "EVIDENCE_BASE", "FOLLOW_UP_TEMPLATES", "Generated", "InterestReading", "MAX_TARGET", "ORDER_FIX_NOTE", "OrderFix", "REALTIME_STABLE_HOURS", "ROUTES", "ROUTE_KO",
    "ROUTE_TYPES", "RealtimeItem", "RealtimeVerdict", "RouteReport", "SEASON_CALENDAR", "SPONSOR_CHANNELS", "Source", "TARGET_READERS", "TOPIC_TEMPLATES_KO", "TREND_SHORTAGE_NOTES", "candidate_type_of", "check_realtime", "generate", "generate_all", "minimum_order", "mix_for",
    "route_targets", "site_key",
]
