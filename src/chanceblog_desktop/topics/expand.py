"""씨앗 → 확장 키워드 — 씨앗 한 건과 채널 프로필로 '이 씨앗에 어떤 방향의 글을 붙일 수 있나' 를 규칙으로 정한다(P2b — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).

확장 하나 = 씨앗 낱말 + 방향 낱말(예: ‘로봇청소기’ + ‘구매 기준’ → ‘로봇청소기 구매 기준’). 방향 낱말은 ① 그 채널 프로필의 `expansion_directions`(채널별 확장어, 프로필 순서 — 원문 §10.2 표와 같은 값) 다음에 ② 모든 채널이
함께 쓰는 공통 확장어가 이어진다. 각 방향은 **계열**(고르기·하는 법·문제 해결·배경·장소·습관·사례·알아 두기)과 검색 의도·글 종류·관점 식별자를 가진다(`DIRECTIONS` 표). 뜻이 안 맞는 조합은 후보로 만들지 않고
**차단 사유를 값으로 돌려준다**(`Blocked`). 그 밖에 씨앗의 제외 키워드가 들어가는 확장·키워드가 너무 긴 확장·영문 채널에 한글 씨앗을 붙이는 확장도 막고, 씨앗 하나에서 만드는 확장 수는
`channels.PER_SEED` 표의 '처음 만들 후보 수'(`seeds.quota_of` — 씨앗의 **중요도**)를 상한으로 한다(넘는 것은 `capped` 로 세기만 한다).

**규칙이 둘이다 — 씨앗의 대상 유형(`target_type`)이 있으면 새 규칙, 없으면 옛 규칙**(2026-11-06 운영자 결정 2, P3b-1):
  · **새 규칙(대상 유형이 있는 씨앗)** — 공통 확장어는 원문 §10.1 의 열 가지(`STRATEGY_COMMON_DIRECTIONS`: 방법·순서·기준·비교·원인·해결·주의사항·체크리스트·관리·예방, 그 순서 그대로)이고, **허용 확장은 대상 유형이 정한다**
    (`TARGET_EXPANSION_WORDS` — 원문 §10.3 표의 낱말을 그대로 옮긴 것, `TARGET_ALLOWED_FAMILIES` — 그 낱말들의 계열). 원문이 정하지 않은 것 둘은 **구현자 초기값**이다: ① §10.3 의 낱말 하나하나가 어느 계열인가(`TARGET_WORD_FAMILY`)
    ② 알아 두기(`info`) 계열은 모든 대상 유형이 받는다(원문 표에 없는 보조 계열 — 운영자가 프로필에 적은 새 낱말과 ‘주의사항’ 이 막히지 않게). 중요도별 허용 계열은 쓰지 않는다 — 중요도는 후보 수만 정한다.
    뜻이 안 맞는 조합(예: 숙박 × API 연동 · 정책·API × 방문 후기 · PC 부품 × 맛집 비교)은 이유와 함께 막는다. 막는다는 것은 후보를 만들지 않는다는 뜻일 뿐 씨앗을 지우거나 바꾸지 않는다.
    이 차단은 뜻(대상 유형 × 방향)만 본다 — 건강·브랜드·협찬 표시 같은 안전 판정(`safety.py`·`brand.py`)은 후보가 만들어진 **뒤에** 따로 걸리고 역할이 겹치지 않는다.
  · **옛 규칙(대상 유형이 없는 판 1 씨앗)** — P3 병합 시점의 표 그대로다(`LEGACY_COMMON_DIRECTIONS` 6개·`LEGACY_ALLOWED_FAMILIES` 중요도별 허용 계열 — 옛 이름 `COMMON_DIRECTIONS`·`ALLOWED_FAMILIES` 도 같은 값으로 남아 있다).
    이 표의 낱말과 조합은 **구현자 초기값**이고 결과는 한 글자도 바뀌지 않았다(시험이 지문으로 못박는다). 운영자가 씨앗에 대상 유형을 적으면 그 씨앗부터 새 규칙을 쓴다.
운영자가 프로필에 적은 새 방향 낱말(표에 없는 말)은 계열 '알아 두기'(`info`)의 일반 설명 글로 읽는다 — 모든 씨앗이 받아들인다.
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

# **옛 규칙**(대상 유형이 없는 판 1 씨앗) — 씨앗 중요도별로 붙일 수 있는 계열, 허용 조합표(구현자 초기값). 일반·우선은 모두, 나머지는 뜻이 맞는 계열만이다.
LEGACY_ALLOWED_FAMILIES = MappingProxyType({
    "general": FAMILIES,
    "priority": FAMILIES,
    "seasonal": (FAMILY_CHOOSE, FAMILY_HOWTO, FAMILY_PLACE, FAMILY_HABIT, FAMILY_INFO),
    "realtime": (FAMILY_CHOOSE, FAMILY_FIX, FAMILY_CONTEXT, FAMILY_INFO),
    "sponsorable": (FAMILY_CHOOSE, FAMILY_HOWTO, FAMILY_PLACE, FAMILY_CASE, FAMILY_INFO),
})
ALLOWED_FAMILIES = LEGACY_ALLOWED_FAMILIES                 # 호환 이름(옛 규칙) — 새 코드는 `LEGACY_ALLOWED_FAMILIES`(옛 규칙)나 `TARGET_ALLOWED_FAMILIES`(새 규칙)를 쓴다

# (방향 낱말, 계열, 검색 의도, 글 종류, 관점 식별자) — 채널 프로필의 기본 방향 낱말과 옛 규칙의 공통 확장어(구현자 초기값 — 채널 방향 낱말은 원문 §10.2 와 같고 새 규칙의 공통 확장어는 아래 `STRATEGY_*` 표다)
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
LEGACY_COMMON_DIRECTIONS = ("방법", "체크리스트", "비교", "주의할 점", "자주 묻는 질문", "비용")        # **옛 규칙**의 공통 확장어(구현자 초기값) — 채널 방향 다음에 이 순서로 붙는다
COMMON_DIRECTIONS = LEGACY_COMMON_DIRECTIONS                                                  # 호환 이름(옛 규칙)

# ---- 새 규칙(대상 유형이 있는 씨앗) — 원문 §10.1 공통 확장어·§10.3 대상 유형별 허용 확장 -----------------------------------------------------------------
STRATEGY_COMMON_DIRECTIONS = ("방법", "순서", "기준", "비교", "원인", "해결", "주의사항", "체크리스트", "관리", "예방")      # 원문 §10.1 — 낱말·순서·표시 그대로
# 원문 §10.3 — 대상 유형 행(낱말은 원문 그대로, 구현자가 고친 것이 없다). 원문의 행은 여덟 개이고 '장소·숙박'·'서비스·SaaS'·'정책·API' 는 낱개 둘이 한 행을 나눠 쓴다(`TARGET_ROW`).
TARGET_EXPANSION_WORDS = MappingProxyType({
    "product": ("선택 기준", "비교", "호환성", "관리", "구매 전 확인"),
    "place_lodging": ("이동", "예약", "방문 전 확인", "계절", "숙박 조건", "주변 이용 정보"),
    "service_saas": ("요금", "기능", "무료·유료 비교", "설정", "연동", "해지·이관"),
    "pc_part": ("성능", "호환성", "소비전력", "가격", "설치", "업그레이드"),
    "problem": ("원인", "점검", "해결", "예방", "지원이 필요한 조건"),
    "life_habit": ("단순화", "반복 루틴", "체크리스트", "유지 방법"),
    "realtime_issue": ("변화", "영향", "대응", "대안", "종료·이관"),
    "policy_api": ("적용 일정", "변경사항", "무료 한도", "인증", "마이그레이션"),
})
# 대상 유형(`seeds.ALL_TARGET_TYPES` 열네 개) → 원문 §10.3 의 행. 낱개와 묶음은 같은 행을 쓴다(원문이 장소·숙박, 서비스·SaaS, 정책·API 를 한 행으로 적었다).
TARGET_ROW = MappingProxyType({
    "product": "product", "place": "place_lodging", "lodging": "place_lodging", "place_lodging": "place_lodging", "service": "service_saas", "saas": "service_saas", "service_saas": "service_saas",
    "pc_part": "pc_part", "problem": "problem", "life_habit": "life_habit", "realtime_issue": "realtime_issue", "policy": "policy_api", "api": "policy_api", "policy_api": "policy_api"})
# **구현자 초기값** — §10.3 낱말 하나하나가 어느 계열인가. 같은 낱말이 다른 행에서 다른 계열이 되지 않게 한 표로 둔다(예: ‘체크리스트’ 는 어느 행에서든 하는 법 계열 — 방향 표의 ‘체크리스트’ 와 같다).
TARGET_WORD_FAMILY = MappingProxyType({
    "선택 기준": FAMILY_CHOOSE, "비교": FAMILY_CHOOSE, "호환성": FAMILY_CHOOSE, "관리": FAMILY_HOWTO, "구매 전 확인": FAMILY_CHOOSE,
    "이동": FAMILY_PLACE, "예약": FAMILY_PLACE, "방문 전 확인": FAMILY_PLACE, "계절": FAMILY_PLACE, "숙박 조건": FAMILY_PLACE, "주변 이용 정보": FAMILY_PLACE,
    "요금": FAMILY_CHOOSE, "기능": FAMILY_CHOOSE, "무료·유료 비교": FAMILY_CHOOSE, "설정": FAMILY_HOWTO, "연동": FAMILY_HOWTO, "해지·이관": FAMILY_HOWTO,
    "성능": FAMILY_CHOOSE, "소비전력": FAMILY_CHOOSE, "가격": FAMILY_CHOOSE, "설치": FAMILY_HOWTO, "업그레이드": FAMILY_HOWTO,
    "원인": FAMILY_FIX, "점검": FAMILY_FIX, "해결": FAMILY_FIX, "예방": FAMILY_FIX, "지원이 필요한 조건": FAMILY_FIX,
    "단순화": FAMILY_HABIT, "반복 루틴": FAMILY_HABIT, "체크리스트": FAMILY_HOWTO, "유지 방법": FAMILY_HABIT,
    "변화": FAMILY_CONTEXT, "영향": FAMILY_CONTEXT, "대응": FAMILY_FIX, "대안": FAMILY_CHOOSE, "종료·이관": FAMILY_CONTEXT,
    "적용 일정": FAMILY_CONTEXT, "변경사항": FAMILY_CONTEXT, "무료 한도": FAMILY_INFO, "인증": FAMILY_HOWTO, "마이그레이션": FAMILY_HOWTO})


def _row_families(row):
    families = []
    for word in TARGET_EXPANSION_WORDS[row]:
        if TARGET_WORD_FAMILY[word] not in families:
            families.append(TARGET_WORD_FAMILY[word])
    if FAMILY_INFO not in families:                                       # 알아 두기는 모든 대상 유형이 받는다(구현자 초기값)
        families.append(FAMILY_INFO)
    return tuple(families)


TARGET_ALLOWED_FAMILIES = MappingProxyType({target: _row_families(row) for target, row in TARGET_ROW.items()})     # 대상 유형 → 붙일 수 있는 계열(계열 표시 순서는 원문 낱말 순서)

# ---- 확장 차단의 예외 규칙(P3b-1 fix1-G, 운영자 2026-11-06 지시 4) ---------------------------------------------------------------------------------------
# 차단의 기본은 **계열 단위**다(`TARGET_ALLOWED_FAMILIES` — 낱말이 아니라 계열로 막고, 같은 계열의 다른 낱말은 통과한다 — 운영자가 받아들였다). 다만 차단은 (대상 유형 × 채널 × Recipe × 확장어) 네 가지를 함께 보고 평가한다:
# 아래 `FAMILY_EXCEPTIONS` 표에 적힌 조합만 기본 허용표에 **더해서 허용**한다(허용을 더하는 예외만 있다 — '차단이 기본'). 표 밖의 모든 칸은 예외 규칙이 생기기 전과 같다(시험이 칸마다 못박는다).
# 예외를 더하는 방법: 이 표에 한 줄을 적고 `tests/test_topics_expand_exceptions.py` 의 예외 기대 표에도 한 줄을 적는다(두 표가 다르면 시험이 빨개진다).
# **Recipe**(조합 방식 — 예: ‘TourAPI 연동 글’)는 공공데이터 주제 조합 프로젝트(PD)의 개념이다 — 이 엔진의 씨앗에는 Recipe 칸이 없고(씨앗 판 2 의 칸은 바꾸지 않았다) `expand(…, recipe=…)` 인자로만 받는다.
# Recipe 값의 씨앗 쪽 출처는 그 프로젝트(PD0)가 정한다(`DEFERRED`). 지금 부르는 쪽(`generate.py`·`brand.py`)은 recipe 를 넘기지 않으므로 실제 생성 결과는 예외 규칙이 생기기 전과 같다.
RECIPE_TOURAPI_INTEGRATION = "tourapi_integration"


class FamilyException(NamedTuple):
    name: str                                       # 예외 이름(영문 식별자 — 결정 기록과 시험이 이름으로 부른다)
    target_types: tuple                             # 적용되는 대상 유형 코드들(`seeds.ALL_TARGET_TYPES` 중)
    channels: tuple                                 # 적용되는 채널 코드들(`channels.CHANNELS` 중)
    recipes: tuple                                  # 적용되는 Recipe 값들(글)
    families: tuple                                 # 이 조합에서 기본 허용표에 더해 허용하는 방향 계열(`FAMILIES` 중)
    words: tuple                                    # 그 계열 안에서 실제로 여는 확장어(방향 낱말) — 비워 두면(`()`) 그 계열 전체를 연다
    reason: str                                     # 왜 허용하는가(쉬운 한국어 — 결정 기록용)


FAMILY_EXCEPTIONS = (
    FamilyException("place_lodging_tourapi_integration", ("place", "lodging", "place_lodging"), ("naver_b",), (RECIPE_TOURAPI_INTEGRATION,), (FAMILY_HOWTO,), ("API 연동",),
                    "장소·숙박 대상이라도 네이버 B 의 TourAPI 연동 글에는 ‘API 연동’ 을 붙일 수 있다 — 같은 하는 법 계열의 설치·설정·방법은 계속 막고, 네이버 A 의 여행 글과 Recipe 가 없는 호출에도 계속 막는다"),
)
BASIS_FAMILY, BASIS_EXCEPTION, BASIS_BLOCKED = "family", "exception", "blocked"


class FamilyDecision(NamedTuple):
    allowed: bool                                   # 이 방향을 붙일 수 있는가
    basis: str                                      # family(기본 허용표가 허용)·exception(예외 표가 허용)·blocked(차단)
    exception: str | None                           # 허용한 예외의 이름(`basis` 가 exception 일 때만)


def clean_recipe(recipe):
    """`recipe` 인자 정리 — None 과 빈 글(공백뿐인 글 포함)은 '없음'(None), 그 밖의 글은 그대로(모르는 값도 예외가 아니다 — 예외 표에 없으면 그냥 맞는 예외가 없는 것). 글이 아니면 TypeError."""
    if recipe is None:
        return None
    if not isinstance(recipe, str):
        raise TypeError("recipe 는 글(str)이거나 None 이어야 한다")
    return recipe if recipe.strip() else None


def family_decision(target_type, channel, recipe, direction):
    """(대상 유형 × 채널 × Recipe × 확장어) → 이 방향(`Direction`)을 붙일 수 있는가(`FamilyDecision`). 순수 함수 — 시계·난수·파일이 없다.
    기본은 계열 단위 허용표(`TARGET_ALLOWED_FAMILIES`)이고, `FAMILY_EXCEPTIONS` 의 한 줄이 대상 유형·채널·Recipe·계열(과 그 줄이 낱말을 정했다면 그 확장어)을 모두 맞게 가리킬 때만 추가로 허용한다. 그 밖은 막는다."""
    if not isinstance(target_type, str) or target_type not in TARGET_ALLOWED_FAMILIES:
        raise ValueError("target_type 은 대상 유형(" + ", ".join(TARGET_ALLOWED_FAMILIES) + ") 중 하나여야 한다")
    if not isinstance(channel, str) or not isinstance(direction, Direction):
        raise TypeError("family_decision(대상 유형, 채널 코드, recipe, 방향) 으로 불러야 한다")
    recipe = clean_recipe(recipe)
    if direction.family in TARGET_ALLOWED_FAMILIES[target_type]:
        return FamilyDecision(True, BASIS_FAMILY, None)
    if recipe is not None:
        for rule in FAMILY_EXCEPTIONS:
            if target_type in rule.target_types and channel in rule.channels and recipe in rule.recipes and direction.family in rule.families and (
                    not rule.words or keyword_key(direction.word) in {keyword_key(word) for word in rule.words}):
                return FamilyDecision(True, BASIS_EXCEPTION, rule.name)
    return FamilyDecision(False, BASIS_BLOCKED, None)


# 새 규칙에서만 아는 방향 낱말(옛 `DIRECTIONS` 표에 없는 것) — 원문 §10.1 의 새 낱말 일곱과, 뜻이 안 맞는 조합 시험용으로 운영자가 든 두 낱말(‘방문 후기’·‘맛집 비교’ — 장소·방문 계열)
_STRATEGY_ROWS = (
    ("순서", FAMILY_HOWTO, "how_to", "how_to_guide", "step-order"),
    ("기준", FAMILY_CHOOSE, "selection_guide", "buying_guide", "criteria"),
    ("원인", FAMILY_FIX, "problem_solving", "troubleshooting", "cause"),
    ("해결", FAMILY_FIX, "problem_solving", "troubleshooting", "solution"),
    ("주의사항", FAMILY_INFO, "information", "explainer", "precautions"),
    ("관리", FAMILY_HOWTO, "how_to", "how_to_guide", "care"),
    ("예방", FAMILY_FIX, "problem_solving", "checklist", "prevention"),
    ("방문 후기", FAMILY_PLACE, "local_info", "place_guide", "visit-review"),
    ("맛집 비교", FAMILY_PLACE, "local_info", "place_guide", "restaurant-comparison"),
)

# 씨앗의 대분류·중분류 이름 → 채널 프로필의 주제 묶음(`topic_clusters`) 식별자. 표에 없는 이름은 씨앗마다 정해진 임시 식별자(`seed-…`)가 된다(구현자 초기값 — 원문은 묶음 이름표를 정하지 않는다).
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


DIRECTIONS = MappingProxyType({keyword_key(row[0]): Direction(*row) for row in _DIRECTION_ROWS})        # 옛 규칙의 방향 표(채널 방향과 옛 공통 확장어) — 새 규칙도 채널 방향의 계열은 이 표에서 읽는다
STRATEGY_DIRECTIONS = MappingProxyType({keyword_key(row[0]): Direction(*row) for row in _STRATEGY_ROWS})   # 새 규칙에서만 아는 낱말(옛 규칙에는 이 낱말이 표에 없는 새 낱말이라 알아 두기로 읽혔다 — 그대로 둔다)


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


def strategy_direction_of(word):
    """새 규칙의 방향 낱말 → `Direction`. 새 규칙 표(`STRATEGY_DIRECTIONS`)를 먼저 보고, 없으면 옛 방향 표(채널 방향 낱말들), 그래도 없으면 알아 두기 계열의 일반 설명 글이다."""
    found = STRATEGY_DIRECTIONS.get(keyword_key(word))
    return found._replace(word=word) if found is not None else direction_of(word)


RULE_LEGACY, RULE_TARGET = "legacy", "target"
RULE_KO = MappingProxyType({RULE_LEGACY: "옛 규칙(대상 유형 없음)", RULE_TARGET: "대상 유형 규칙"})


def rule_of(seed):
    """이 씨앗이 어느 규칙으로 확장되나 — 대상 유형이 없으면 `legacy`(옛 규칙 — 중요도별 허용 계열), 있으면 `target`(원문 §10.1·§10.3)."""
    if not isinstance(seed, Seed):
        raise TypeError("rule_of(씨앗) 으로 불러야 한다")
    return RULE_LEGACY if seed.target_type is None else RULE_TARGET


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


def _directions(profile, common):
    """채널 프로필의 방향 낱말 → 공통 확장어(`common`) 순서로, 같은 낱말은 한 번만 — (낱말, 출처) 목록."""
    seen, out = set(), []
    for source, words in (("channel", profile.expansion_directions), ("common", common)):
        for word in words:
            key = keyword_key(word)
            if key and key not in seen:
                seen.add(key)
                out.append((word, source))
    return out


def _target_reason(seed, direction, word, channel, recipe):
    """새 규칙 — 이 방향이 씨앗의 대상 유형에 맞지 않으면 쉬운 한국어 이유, 맞으면 None. 맞는지는 `family_decision`(기본 허용표 + 예외 표)이 정한다 — 이유 글은 예외 규칙이 생기기 전과 한 글자도 같다."""
    if family_decision(seed.target_type, channel, recipe, direction).allowed:
        return None
    row = TARGET_ROW[seed.target_type]
    return (f"‘{wording.TARGET_TYPE_KO[seed.target_type]}’ 대상에는 ‘{word}’({FAMILY_KO[direction.family]} 계열)을 붙이지 않습니다 — 뜻이 맞지 않는 조합입니다"
            f"(이 대상에 어울리는 방향: {', '.join(TARGET_EXPANSION_WORDS[row])})")


def expand(seed, profile, *, limit=None, as_type=None, recipe=None):
    """씨앗 한 건 → 그 채널에서 쓸 수 있는 확장(`Expanded`). `limit`(1~20)을 안 주면 그 씨앗 유형의 '처음 만들 후보 수'(`channels.PER_SEED`)가 상한이다. `as_type` 을 주면 씨앗을 그 유형으로 보고
    상한(과 옛 규칙의 허용 계열)을 정한다(예: 협찬 태그가 있는 일반 씨앗을 협찬 가능 씨앗으로 넓힐 때).
    **씨앗에 대상 유형이 있으면 새 규칙**(원문 §10.1 공통 확장어 열 가지 + §10.3 대상 유형별 허용 확장), **없으면 옛 규칙**(P3 의 표 그대로 — 결과가 한 글자도 안 바뀐다)이다(`rule_of`).
    `recipe`(글 또는 None — 조합 방식, 공공데이터 프로젝트의 개념)는 **새 규칙의 예외 표**(`FAMILY_EXCEPTIONS`)만 본다 — 대상 유형·채널(`profile.key`)·Recipe·확장어가 모두 맞는 조합만 추가로 허용하고, 안 주면(None·빈 글) 예외 없이 지금까지와 같다.
    옛 규칙은 recipe 를 보지 않는다(글이 아니면 TypeError 는 어느 규칙에서나 같다).
    막는 것: ① 이 씨앗(대상 유형 또는 옛 규칙의 중요도)에 맞지 않는 방향 ② (옛 규칙만) 장소를 다루지 않는 묶음의 장소·방문 계열 ③ 영문 채널에 한글 씨앗 ④ 씨앗의 제외 키워드가 들어가는 확장 ⑤ 키워드가 60자를 넘는 확장.
    막은 것은 이유와 함께 `blocked` 에 담는다. 씨앗의 상태는 보지 않는다(쓸 수 있는 씨앗은 부르는 쪽이 `seeds.usable_seeds` 로 가린다)."""
    if not isinstance(seed, Seed) or not isinstance(profile, ChannelProfile):
        raise TypeError("expand(씨앗, 채널 프로필) 로 불러야 한다")
    recipe = clean_recipe(recipe)
    type_name = seed.seed_type if as_type is None else as_type
    if not isinstance(type_name, str) or type_name not in LEGACY_ALLOWED_FAMILIES:
        raise ValueError("as_type 은 씨앗 유형(" + ", ".join(LEGACY_ALLOWED_FAMILIES) + ") 중 하나이거나 None 이어야 한다")
    if limit is None:
        limit = PER_SEED[type_name].first
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit 은 1~{MAX_LIMIT} 사이의 정수여야 한다")
    if rule_of(seed) == RULE_TARGET:
        common, lookup = STRATEGY_COMMON_DIRECTIONS, strategy_direction_of

        def mismatch(direction, word):
            return _target_reason(seed, direction, word, profile.key, recipe)
    else:                                                                       # 옛 규칙 — P3 병합 시점의 동작 그대로
        common, lookup = LEGACY_COMMON_DIRECTIONS, direction_of
        allowed = LEGACY_ALLOWED_FAMILIES[type_name]
        cluster = cluster_of(seed, profile)
        place_ok = cluster.startswith("seed-") or cluster in PLACE_CLUSTERS

        def mismatch(direction, word):
            if direction.family not in allowed:
                return f"‘{SEED_TYPE_KO[type_name]}’ 씨앗에는 ‘{word}’({FAMILY_KO[direction.family]} 계열)을 붙이지 않습니다 — 뜻이 맞지 않는 조합입니다"
            if direction.family == FAMILY_PLACE and not place_ok:
                where = f"‘{wording.CLUSTER_KO[cluster]}’ 묶음입니다" if cluster in wording.CLUSTER_KO else "장소가 아닌 다른 묶음입니다"
                return f"‘{word}’({FAMILY_KO[direction.family]} 계열)는 장소를 다루는 묶음의 씨앗에만 붙입니다 — 이 씨앗은 {where}"
            return None
    excluded = [(word, keyword_key(word)) for word in seed.excluded_keywords if keyword_key(word)]
    items, blocked, capped = [], [], 0
    for word, source in _directions(profile, common):
        direction = lookup(word)
        phrase = f"{seed.keyword} {word}"
        detail = mismatch(direction, word)
        if detail is not None:
            blocked.append(Blocked(seed.seed_id, word, REASON_COMBINATION, detail))
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
    "ALLOWED_FAMILIES", "BASIS_BLOCKED", "BASIS_EXCEPTION", "BASIS_FAMILY", "BLOCK_REASONS", "Blocked", "CLUSTER_LABELS", "COMMON_DIRECTIONS", "DIRECTIONS", "Direction", "Expanded",
    "Expansion", "FAMILIES", "FAMILY_EXCEPTIONS", "FAMILY_KO", "FamilyDecision", "FamilyException", "LEGACY_ALLOWED_FAMILIES", "LEGACY_COMMON_DIRECTIONS", "MAX_LIMIT", "PLACE_CLUSTERS",
    "REASON_COMBINATION", "REASON_EXCLUDED", "REASON_LANGUAGE", "REASON_TOO_LONG", "RECIPE_TOURAPI_INTEGRATION", "RULE_KO", "RULE_LEGACY", "RULE_TARGET", "SEED_TYPE_KO",
    "STRATEGY_COMMON_DIRECTIONS", "STRATEGY_DIRECTIONS", "TARGET_ALLOWED_FAMILIES", "TARGET_EXPANSION_WORDS", "TARGET_ROW", "TARGET_WORD_FAMILY", "clean_recipe", "cluster_of",
    "direction_of", "expand", "family_decision", "rule_of", "stable_id", "strategy_direction_of",
]
