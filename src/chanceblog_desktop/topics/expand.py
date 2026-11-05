"""씨앗 → 확장 키워드 — 씨앗 한 건과 채널 프로필로 '이 씨앗에 어떤 방향의 글을 붙일 수 있나' 를 규칙으로 정한다(P2b — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).

확장 하나 = 씨앗 낱말 + 방향 낱말(예: ‘로봇청소기’ + ‘구매 기준’ → ‘로봇청소기 구매 기준’). 방향 낱말은 ① 그 채널 프로필의 `expansion_directions`(채널별 확장어, 프로필 순서) 다음에 ② 모든 채널이
함께 쓰는 공통 확장어(`COMMON_DIRECTIONS`)가 이어진다. 각 방향은 **계열**(고르기·하는 법·문제 해결·배경·장소·습관·사례·알아 두기)과 검색 의도·글 종류·관점 식별자를 가진다(`DIRECTIONS` 표).
씨앗 유형(`general·priority·seasonal·realtime·sponsorable`)마다 붙일 수 있는 계열이 정해져 있다(`ALLOWED_FAMILIES` — **허용 조합표**) — 뜻이 안 맞는 조합(예: 실시간 씨앗에 '관리 방법')은 후보로 만들지 않고
**차단 사유를 값으로 돌려준다**(`Blocked`). 그 밖에 씨앗의 제외 키워드가 들어가는 확장·키워드가 너무 긴 확장·영문 채널에 한글 씨앗을 붙이는 확장도 막고, 씨앗 하나에서 만드는 확장 수는
`channels.PER_SEED` 표의 '처음 만들 후보 수'(`seeds.quota_of`)를 상한으로 한다(넘는 것은 `capped` 로 세기만 한다).

**표의 낱말과 조합은 모두 초기값 — 전략 원문 확인 전이다.** 전략 원문의 확장어·허용 조합 표가 이 PC 에 없어서 요약·계획 문서의 방향 낱말(`channels.DEFAULT_PROFILES`)을 계열로 묶고 상식으로 조합을 정했다.
원문에 맞춰 고칠 때는 이 파일의 표(`DIRECTIONS`·`COMMON_DIRECTIONS`·`ALLOWED_FAMILIES`·`CLUSTER_LABELS`) 한 곳만 고치고 시험(`test_topics_expand` 의 '초기값' 시험)을 의식적으로 함께 고친다.
운영자가 프로필에 적은 새 방향 낱말(표에 없는 말)은 계열 '알아 두기'(`info`)의 일반 설명 글로 읽는다 — 모든 씨앗 유형이 받아들인다.
"""
from __future__ import annotations

import re
from types import MappingProxyType
from typing import NamedTuple

from ..content.candidates import MAX_KEYWORD, keyword_key
from . import wording
from .channels import PER_SEED, ChannelProfile
from .seeds import Seed

FAMILY_CHOOSE, FAMILY_HOWTO, FAMILY_FIX, FAMILY_CONTEXT, FAMILY_PLACE, FAMILY_HABIT, FAMILY_CASE, FAMILY_INFO = "choose", "howto", "fix", "context", "place", "habit", "case", "info"
FAMILIES = (FAMILY_CHOOSE, FAMILY_HOWTO, FAMILY_FIX, FAMILY_CONTEXT, FAMILY_PLACE, FAMILY_HABIT, FAMILY_CASE, FAMILY_INFO)
FAMILY_KO = MappingProxyType({FAMILY_CHOOSE: "고르기·비교", FAMILY_HOWTO: "하는 법", FAMILY_FIX: "문제 해결", FAMILY_CONTEXT: "배경·영향", FAMILY_PLACE: "장소·방문", FAMILY_HABIT: "습관·정리",
                              FAMILY_CASE: "사례", FAMILY_INFO: "알아 두기"})
SEED_TYPE_KO = wording.SEED_TYPE_KO                 # 표의 주인은 `wording`(쉬운 말 표를 한 곳에 — 순환을 막는다). 이름·값은 그대로다

# 씨앗 유형별로 붙일 수 있는 계열 — 허용 조합표(초기값 — 전략 원문 확인 전). 일반·우선은 모두, 나머지는 뜻이 맞는 계열만이다.
ALLOWED_FAMILIES = MappingProxyType({
    "general": FAMILIES,
    "priority": FAMILIES,
    "seasonal": (FAMILY_CHOOSE, FAMILY_HOWTO, FAMILY_PLACE, FAMILY_HABIT, FAMILY_INFO),
    "realtime": (FAMILY_CHOOSE, FAMILY_FIX, FAMILY_CONTEXT, FAMILY_INFO),
    "sponsorable": (FAMILY_CHOOSE, FAMILY_HOWTO, FAMILY_PLACE, FAMILY_CASE, FAMILY_INFO),
})

# (방향 낱말, 계열, 검색 의도, 글 종류, 관점 식별자) — 채널 프로필의 기본 방향 낱말과 공통 확장어(초기값 — 전략 원문 확인 전)
_DIRECTION_ROWS = (
    ("구매 기준", FAMILY_CHOOSE, "selection_guide", "buying_guide", "buying-criteria"),
    ("제품 비교", FAMILY_CHOOSE, "comparison", "comparison", "product-comparison"),
    ("성능", FAMILY_CHOOSE, "comparison", "comparison", "performance"),
    ("호환성", FAMILY_CHOOSE, "selection_guide", "checklist", "compatibility"),
    ("설치", FAMILY_HOWTO, "how_to", "how_to_guide", "installation"),
    ("설정", FAMILY_HOWTO, "how_to", "how_to_guide", "settings"),
    ("API 연동", FAMILY_HOWTO, "how_to", "how_to_guide", "api-integration"),
    ("관리 방법", FAMILY_HOWTO, "how_to", "how_to_guide", "care-method"),
    ("정보 관리", FAMILY_HOWTO, "how_to", "how_to_guide", "info-management"),
    ("오류 해결", FAMILY_FIX, "problem_solving", "troubleshooting", "troubleshooting"),
    ("변화", FAMILY_CONTEXT, "context_explainer", "news_analysis", "what-changed"),
    ("영향", FAMILY_CONTEXT, "context_explainer", "news_analysis", "impact"),
    ("배경", FAMILY_CONTEXT, "context_explainer", "explainer", "background"),
    ("산업·경제·사회적 맥락", FAMILY_CONTEXT, "context_explainer", "news_analysis", "wider-context"),
    ("분야 연결", FAMILY_CONTEXT, "context_explainer", "explainer", "cross-field"),
    ("방문 전 확인", FAMILY_PLACE, "local_info", "place_guide", "before-visit"),
    ("지역·계절 체험", FAMILY_PLACE, "local_info", "place_guide", "local-season"),
    ("정리", FAMILY_HABIT, "routine_building", "routine_plan", "organizing"),
    ("습관", FAMILY_HABIT, "routine_building", "routine_plan", "habit-building"),
    ("반복 관리", FAMILY_HABIT, "routine_building", "checklist", "recurring-care"),
    ("생활 부담 줄이기", FAMILY_HABIT, "routine_building", "routine_plan", "lighten-load"),
    ("simple routine", FAMILY_HABIT, "routine_building", "routine_plan", "simple-routine"),
    ("gentle reset", FAMILY_HABIT, "routine_building", "routine_plan", "gentle-reset"),
    ("low-pressure habit", FAMILY_HABIT, "routine_building", "routine_plan", "low-pressure-habit"),
    ("everyday checklist", FAMILY_HABIT, "routine_building", "checklist", "everyday-checklist"),
    ("자동화 사례", FAMILY_CASE, "information", "dev_log", "automation-case"),
    ("방법", FAMILY_HOWTO, "how_to", "how_to_guide", "method"),
    ("체크리스트", FAMILY_HOWTO, "how_to", "checklist", "checklist"),
    ("비교", FAMILY_CHOOSE, "comparison", "comparison", "comparison"),
    ("비용", FAMILY_CHOOSE, "selection_guide", "buying_guide", "cost"),
    ("주의할 점", FAMILY_INFO, "information", "explainer", "cautions"),
    ("자주 묻는 질문", FAMILY_INFO, "information", "explainer", "faq"),
)
COMMON_DIRECTIONS = ("방법", "체크리스트", "비교", "주의할 점", "자주 묻는 질문", "비용")        # 모든 채널이 함께 쓰는 공통 확장어(초기값) — 채널 방향 다음에 이 순서로 붙는다

# 씨앗의 대분류·중분류 이름 → 채널 프로필의 주제 묶음(`topic_clusters`) 식별자. 표에 없는 이름은 씨앗마다 정해진 임시 식별자(`seed-…`)가 된다(초기값 — 전략 원문 확인 전).
CLUSTER_LABELS = MappingProxyType({
    "small-appliances": ("소형가전", "가전"), "pc-peripherals": ("PC 주변기기", "주변기기"), "lodging-and-travel": ("숙박", "여행", "숙박·여행", "숙박/여행"), "local-places": ("지역", "지역 정보", "맛집"),
    "daily-problem-solving": ("생활 문제 해결", "생활 문제"), "ai-services": ("AI 서비스", "AI"), "api-and-limits": ("API", "API 한도"), "github-and-deploy": ("GitHub", "배포"), "local-ai": ("로컬 AI",),
    "pc-parts": ("PC 부품", "부품"), "work-automation": ("업무 자동화", "자동화"), "desktop-app-log": ("데스크톱 앱 기록", "개발 기록"), "industry-impact": ("산업 영향", "산업"),
    "ai-and-compute": ("AI와 컴퓨팅", "컴퓨팅"), "energy-and-infrastructure": ("에너지와 인프라", "에너지"), "privacy-and-data": ("개인정보와 데이터", "개인정보"), "platform-policy": ("플랫폼 정책", "정책"),
    "api-transition": ("API 전환",), "digital-organization": ("디지털 정리",), "schedule-management": ("일정 관리",), "memo-and-information": ("메모와 정보", "메모"),
    "smartphone-settings": ("스마트폰 설정",), "shopping-habits": ("쇼핑 습관",), "time-management": ("시간 관리",), "household-budget": ("가계부", "생활비"), "personal-productivity": ("생산성",),
    "simple-habits": ("simple habits",), "daily-routines": ("daily routines",), "meal-planning": ("meal planning",), "home-organization": ("home organization",),
    "digital-wellbeing": ("digital wellbeing",), "weekly-reset": ("weekly reset",), "evening-routine": ("evening routine",),
})

# '장소·방문' 계열은 장소를 다루는 묶음에서만 붙인다(‘로봇청소기 방문 전 확인’ 같은 뜻 안 맞는 말을 막는다) — 알려진 다른 묶음의 씨앗에는 붙이지 않고, 묶음을 모르는 씨앗(`seed-…`)에는 붙인다(초기값).
PLACE_CLUSTERS = ("lodging-and-travel", "local-places")

REASON_COMBINATION, REASON_EXCLUDED, REASON_TOO_LONG, REASON_LANGUAGE = "combination", "excluded_keyword", "too_long", "language"
BLOCK_REASONS = (REASON_COMBINATION, REASON_EXCLUDED, REASON_TOO_LONG, REASON_LANGUAGE)
MAX_LIMIT = 20
_HANGUL = re.compile("[가-힣]")


class Direction(NamedTuple):
    word: str                                       # 방향 낱말
    family: str                                     # `FAMILIES` 중 하나
    search_intent: str                              # `model.SEARCH_INTENTS` 중 하나
    content_type: str                               # `model.CONTENT_TYPES` 중 하나
    angle: str                                      # 관점 식별자(영문 소문자-붙임표)
    known: bool = True                              # 표에 있는 낱말인가(False 면 운영자가 프로필에 적은 새 낱말)


DIRECTIONS = MappingProxyType({keyword_key(row[0]): Direction(*row) for row in _DIRECTION_ROWS})


def stable_id(*parts, digits=16):
    """글 조각들 → 늘 같은 16진수 글(기본 16자). 파이썬의 `hash()`(실행마다 달라진다)·난수·`hashlib` 를 쓰지 않고 FNV-1a 64비트를 손으로 계산한다 — 같은 입력은 늘 같은 번호가 되게 하려는 것이다."""
    value = 0xCBF29CE484222325
    for byte in chr(0x1F).join(str(part) for part in parts).encode("utf-8"):
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"[:digits]


def direction_of(word):
    """방향 낱말 → `Direction`. 표에 없는 낱말(운영자가 프로필에 새로 적은 말)은 계열 '알아 두기'의 일반 설명 글이고 관점 식별자는 낱말에서 정한 `custom-…` 이다."""
    key = keyword_key(word)
    found = DIRECTIONS.get(key)
    if found is not None:
        return found._replace(word=word)
    return Direction(word, FAMILY_INFO, "information", "explainer", "custom-" + stable_id("direction", key, digits=8), False)


class Expansion(NamedTuple):
    seed_id: str
    direction: str                                  # 방향 낱말(프로필에 적힌 모양)
    source: str                                     # channel(채널 프로필의 방향)·common(공통 확장어)
    family: str
    keyword: str                                    # 확장한 키워드 — 씨앗 낱말 + 방향 낱말
    search_intent: str
    content_type: str
    angle: str


class Blocked(NamedTuple):
    seed_id: str
    direction: str
    reason: str                                     # `BLOCK_REASONS` 중 하나
    detail: str                                     # 쉬운 한국어 이유


class Expanded(NamedTuple):
    items: tuple                                    # `Expansion` — 방향 순서대로(채널 방향 → 공통 확장어), 상한까지
    blocked: tuple                                  # `Blocked` — 막은 확장과 이유(같은 순서)
    capped: int                                     # 상한을 넘어서 쓰지 않은 확장의 수


def _directions(profile):
    """채널 프로필의 방향 낱말 → 공통 확장어 순서로, 같은 낱말은 한 번만 — (낱말, 출처) 목록."""
    seen, out = set(), []
    for source, words in (("channel", profile.expansion_directions), ("common", COMMON_DIRECTIONS)):
        for word in words:
            key = keyword_key(word)
            if key and key not in seen:
                seen.add(key)
                out.append((word, source))
    return out


def expand(seed, profile, *, limit=None, as_type=None):
    """씨앗 한 건 → 그 채널에서 쓸 수 있는 확장(`Expanded`). `limit`(1~20)을 안 주면 그 씨앗 유형의 '처음 만들 후보 수'(`channels.PER_SEED`)가 상한이다. `as_type` 을 주면 씨앗을 그 유형으로 보고
    허용 계열·상한을 정한다(예: 협찬 태그가 있는 일반 씨앗을 협찬 가능 씨앗으로 넓힐 때).
    막는 것: ① 이 씨앗 유형의 허용 계열이 아닌 방향 ② 씨앗의 제외 키워드가 들어가는 확장 ③ 키워드가 60자를 넘는 확장 ④ 영문 채널에 한글 씨앗. 막은 것은 이유와 함께 `blocked` 에 담는다. 씨앗의 상태는 보지 않는다(쓸 수 있는 씨앗은 부르는 쪽이 `seeds.usable_seeds` 로 가린다)."""
    if not isinstance(seed, Seed) or not isinstance(profile, ChannelProfile):
        raise TypeError("expand(씨앗, 채널 프로필) 로 불러야 한다")
    type_name = seed.seed_type if as_type is None else as_type
    if not isinstance(type_name, str) or type_name not in ALLOWED_FAMILIES:
        raise ValueError("as_type 은 씨앗 유형(" + ", ".join(ALLOWED_FAMILIES) + ") 중 하나이거나 None 이어야 한다")
    if limit is None:
        limit = PER_SEED[type_name].first
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit 은 1~{MAX_LIMIT} 사이의 정수여야 한다")
    allowed = ALLOWED_FAMILIES[type_name]
    cluster = cluster_of(seed, profile)
    place_ok = cluster.startswith("seed-") or cluster in PLACE_CLUSTERS
    excluded = [(word, keyword_key(word)) for word in seed.excluded_keywords if keyword_key(word)]
    items, blocked, capped = [], [], 0
    for word, source in _directions(profile):
        direction = direction_of(word)
        phrase = f"{seed.keyword} {word}"
        if direction.family not in allowed:
            blocked.append(Blocked(seed.seed_id, word, REASON_COMBINATION, f"‘{SEED_TYPE_KO[type_name]}’ 씨앗에는 ‘{word}’({FAMILY_KO[direction.family]} 계열)을 붙이지 않습니다 — 뜻이 맞지 않는 조합입니다"))
            continue
        if direction.family == FAMILY_PLACE and not place_ok:
            where = f"‘{wording.CLUSTER_KO[cluster]}’ 묶음입니다" if cluster in wording.CLUSTER_KO else "장소가 아닌 다른 묶음입니다"
            blocked.append(Blocked(seed.seed_id, word, REASON_COMBINATION, f"‘{word}’({FAMILY_KO[direction.family]} 계열)는 장소를 다루는 묶음의 씨앗에만 붙입니다 — 이 씨앗은 {where}"))
            continue
        if profile.language == "en" and _HANGUL.search(seed.keyword):
            blocked.append(Blocked(seed.seed_id, word, REASON_LANGUAGE, f"영문 채널({profile.display_name})에는 한글 씨앗 낱말을 붙이지 않습니다"))
            continue
        hit = next((shown for shown, key in excluded if key in keyword_key(phrase)), None)
        if hit is not None:
            blocked.append(Blocked(seed.seed_id, word, REASON_EXCLUDED, f"씨앗의 제외 키워드 ‘{hit}’ 이(가) 들어 있어 쓰지 않습니다"))
            continue
        if len(phrase) > MAX_KEYWORD:
            blocked.append(Blocked(seed.seed_id, word, REASON_TOO_LONG, f"확장한 키워드가 {MAX_KEYWORD}자를 넘어 쓰지 않습니다"))
            continue
        if len(items) >= limit:
            capped += 1
            continue
        items.append(Expansion(seed.seed_id, word, source, direction.family, phrase, direction.search_intent, direction.content_type, direction.angle))
    return Expanded(tuple(items), tuple(blocked), capped)


def cluster_of(seed, profile):
    """씨앗 → 주제 묶음 식별자. 씨앗의 중분류(없으면 대분류) 이름이 `CLUSTER_LABELS` 의 이름과 같고 그 식별자가 이 채널 프로필의 주제 묶음에 있으면 그 식별자,
    아니면 중분류 이름에서 정한 임시 식별자 `seed-…` 이다(같은 중분류의 씨앗은 늘 같은 묶음이라 '같은 묶음 상한' 이 그 씨앗들을 한 묶음으로 센다)."""
    if not isinstance(seed, Seed) or not isinstance(profile, ChannelProfile):
        raise TypeError("cluster_of(씨앗, 채널 프로필) 로 불러야 한다")
    for name in (seed.minor, seed.major):
        key = keyword_key(name)
        for slug in profile.topic_clusters:
            if key and key in {keyword_key(label) for label in CLUSTER_LABELS.get(slug, ())}:
                return slug
    return "seed-" + stable_id("cluster", keyword_key(seed.minor) or keyword_key(seed.major), digits=8)


__all__ = [
    "ALLOWED_FAMILIES", "BLOCK_REASONS", "Blocked", "CLUSTER_LABELS", "COMMON_DIRECTIONS", "DIRECTIONS", "Direction", "Expanded", "Expansion", "FAMILIES", "FAMILY_KO", "MAX_LIMIT", "PLACE_CLUSTERS",
    "REASON_COMBINATION", "REASON_EXCLUDED", "REASON_LANGUAGE", "REASON_TOO_LONG", "SEED_TYPE_KO", "cluster_of", "direction_of", "expand", "stable_id",
]
