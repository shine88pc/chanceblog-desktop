"""작성 가능성 — 후보 한 건의 글 종류·검색 의도로 소제목 뼈대를 정하고, 채널의 '소제목 최소 수'(`subheading_min`, 기본 4)에 못 미치면 **자동 보완 순서**대로 더해 보고, 그래도 못 채우면
'작성 가능성 낮음' 으로 점수를 낮춘다(P2b — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).

순서: ① 글 종류(`model.CONTENT_TYPES`)의 기본 뼈대(`BASE_OUTLINES`) ② 검색 의도(`model.SEARCH_INTENTS`)가 더하는 소제목(`INTENT_EXTRAS` — 이미 있으면 더하지 않는다) ③ 소제목이 `subheading_min` 개에 못 미치면
`SUPPLEMENT_ORDER`(자주 묻는 질문 → 체크리스트 → 비교표 → 주의할 점)대로 하나씩 더한다(이미 있는 것·그 글 종류에 안 맞는 것(`SUPPLEMENT_NOT_FOR`)은 건너뛴다) ④ 다 더해도 모자라면 '낮음'.
**'모름 ≠ 0'**: 글 종류나 검색 의도를 모르면(None) 점수도 None 이다(재분배). '낮음' 은 0점이 아니라 낮춘 점수(`LOW_SCORE`)다 — 숫자만으로 후보를 지우지 않는다.
점수(`SCORES_BY_ADDED`): 보완 없이 충분 90 · 하나 더해 충분 80 · 둘 70 · 셋 60 · 넷 50 · 못 채움 `LOW_SCORE`. 점수는 6항목 중 `Factors.feasibility`(작성 가능성)의 입력으로 쓴다.

**표(소제목·순서·점수)는 모두 초기값 — 전략 원문 확인 전이다.** 전략 원문의 보완 순서·소제목 표가 이 PC 에 없어서 요약('소제목 4개 이상·자동 보완 순서')과 계획 문서의 예(자주 묻는 질문 → 체크리스트 → 비교표 →
주의할 점)를 따르고 나머지는 상식으로 정했다. 원문에 맞춰 고칠 때는 이 파일의 표(`SECTIONS`·`BASE_OUTLINES`·`INTENT_EXTRAS`·`SUPPLEMENT_ORDER`·`SUPPLEMENT_NOT_FOR`·`SCORES_BY_ADDED`·`LOW_SCORE`) 한 곳만 고친다.
소제목의 실제 문장은 만들지 않는다 — 뼈대의 이름(식별자와 쉬운 한국어 이름)만 정한다.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import NamedTuple

from .channels import ChannelProfile
from .model import CONTENT_TYPES, SEARCH_INTENTS, TopicCandidate

# 소제목 뼈대의 이름(식별자 → 쉬운 한국어 이름) — 초기값
SECTIONS = MappingProxyType({
    "overview": "한눈에 보기", "details": "자세히 보기", "example": "예시로 보기", "wrap_up": "정리",
    "prepare": "준비물과 준비", "steps": "단계별 방법", "stuck_points": "자주 막히는 부분",
    "before_start": "시작 전 점검", "checklist": "체크리스트", "easy_to_miss": "빠뜨리기 쉬운 것", "next_check": "다음 점검 시기",
    "symptoms": "증상 확인", "causes": "원인 후보", "fix_order": "해결 순서", "still_failing": "그래도 안 될 때",
    "criteria": "고르는 기준", "by_situation": "상황별 선택", "cautions": "주의할 점", "differences": "항목별 차이", "comparison_table": "비교표",
    "before_visit": "가기 전에 확인할 것", "how_to_get": "가는 방법", "highlights": "둘러볼 곳",
    "what_happened": "무슨 일이 있었나", "why_it_matters": "왜 중요한가", "impact": "영향",
    "goal": "목표 정하기", "daily_flow": "하루 흐름", "keep_going": "꾸준히 하는 요령",
    "situation": "상황", "tried": "시도한 것", "result": "결과",
    "what_it_is": "무엇인가", "how_to_use": "쓰는 방법", "pros_cons": "장단점", "who_for": "누구에게 맞나", "faq": "자주 묻는 질문",
})

# 글 종류별 기본 뼈대(초기값) — 모든 `CONTENT_TYPES` 에 있다
BASE_OUTLINES = MappingProxyType({
    "explainer": ("overview", "details", "example", "wrap_up"),
    "how_to_guide": ("prepare", "steps", "stuck_points", "wrap_up"),
    "checklist": ("before_start", "checklist", "easy_to_miss", "next_check"),
    "troubleshooting": ("symptoms", "causes", "fix_order", "still_failing"),
    "buying_guide": ("criteria", "by_situation", "cautions"),
    "comparison": ("criteria", "differences", "by_situation"),
    "place_guide": ("before_visit", "how_to_get", "highlights"),
    "news_analysis": ("what_happened", "why_it_matters", "impact"),
    "routine_plan": ("goal", "daily_flow", "keep_going"),
    "dev_log": ("situation", "tried", "result"),
    "service_intro": ("what_it_is", "how_to_use", "pros_cons", "who_for"),
})

# 검색 의도가 더하는 소제목(초기값) — 이미 있는 것은 더하지 않는다. 모든 `SEARCH_INTENTS` 에 있다.
INTENT_EXTRAS = MappingProxyType({
    "information": ("overview",), "how_to": ("steps",), "problem_solving": ("fix_order",), "selection_guide": ("by_situation",), "comparison": ("comparison_table",),
    "local_info": ("before_visit",), "context_explainer": ("impact",), "routine_building": ("keep_going",),
})

SUPPLEMENT_ORDER = ("faq", "checklist", "comparison_table", "cautions")             # 자동 보완 순서(초기값 — 계획 문서의 예와 같다)
SUPPLEMENT_NOT_FOR = MappingProxyType({"comparison_table": ("news_analysis", "routine_plan", "dev_log")})        # 이 글 종류에는 더하지 않는 보완(초기값)
SCORES_BY_ADDED = MappingProxyType({0: 90, 1: 80, 2: 70, 3: 60, 4: 50})            # 보완으로 더한 소제목 수 → 작성 가능성 점수(초기값)
LOW_SCORE = 30                                                                    # 다 더해도 소제목 최소 수를 못 채울 때의 점수 — 0점이 아니라 낮춘 점수(초기값)

LEVEL_READY, LEVEL_SUPPLEMENTED, LEVEL_LOW, LEVEL_UNKNOWN = "ready", "supplemented", "low", "unknown"
LEVELS = (LEVEL_READY, LEVEL_SUPPLEMENTED, LEVEL_LOW, LEVEL_UNKNOWN)
MAX_SUBHEADING_MIN = 20


class Outline(NamedTuple):
    sections: tuple                                 # 소제목 뼈대 식별자 — 기본 뼈대 → 검색 의도가 더한 것 → 보완한 것 순서
    labels: tuple                                   # 같은 순서의 쉬운 한국어 이름
    base: tuple                                     # 글 종류와 검색 의도로 정한 처음 뼈대(보완 전)
    added: tuple                                    # 자동 보완으로 더한 소제목(순서대로)
    minimum: int                                    # 이 채널의 소제목 최소 수


class Feasibility(NamedTuple):
    level: str                                      # `LEVELS` 중 하나
    score: int | None                               # 작성 가능성 점수(0~100) — 모르면 None
    outline: Outline | None                         # 뼈대 — 글 종류나 검색 의도를 모르면 None
    reasons: tuple                                  # 쉬운 한국어 이유


def _check(content_type, search_intent, minimum):
    for value, allowed, name in ((content_type, CONTENT_TYPES, "글 종류"), (search_intent, SEARCH_INTENTS, "검색 의도")):
        if value is not None and (not isinstance(value, str) or value not in allowed):
            raise ValueError(f"{name}는 다음 중 하나이거나 None 이어야 한다: " + ", ".join(allowed))
    if not isinstance(minimum, int) or isinstance(minimum, bool) or not 1 <= minimum <= MAX_SUBHEADING_MIN:
        raise ValueError(f"소제목 최소 수는 1~{MAX_SUBHEADING_MIN} 사이의 정수여야 한다")


def assess(content_type, search_intent, *, subheading_min=4):
    """글 종류와 검색 의도(둘 다 `model` 의 닫힌 목록 또는 None)로 소제목 뼈대와 작성 가능성을 정한다. 모르는 값(None)이 있으면 점수도 None(모름)이다. 모양이 틀린 값은 `ValueError`."""
    _check(content_type, search_intent, subheading_min)
    if content_type is None or search_intent is None:
        return Feasibility(LEVEL_UNKNOWN, None, None, ("글 종류나 검색 의도를 몰라 작성 가능성을 평가하지 못했습니다 — 모르는 값은 0점으로 치지 않고 계산에서 뺍니다",))
    base = list(BASE_OUTLINES[content_type])
    for section in INTENT_EXTRAS[search_intent]:
        if section not in base:
            base.append(section)
    sections, added = list(base), []
    for section in SUPPLEMENT_ORDER:
        if len(sections) >= subheading_min:
            break
        if section in sections or content_type in SUPPLEMENT_NOT_FOR.get(section, ()):
            continue
        sections.append(section)
        added.append(section)
    outline = Outline(tuple(sections), tuple(SECTIONS[name] for name in sections), tuple(base), tuple(added), subheading_min)
    if len(sections) < subheading_min:
        reason = f"소제목 뼈대가 {len(sections)}개뿐이라 최소 {subheading_min}개를 채우지 못했습니다(자동 보완 {len(added)}개를 더해도 모자랍니다) — 작성 가능성을 낮게 봅니다"
        return Feasibility(LEVEL_LOW, LOW_SCORE, outline, (reason,))
    if not added:
        return Feasibility(LEVEL_READY, SCORES_BY_ADDED[0], outline, (f"글 종류와 검색 의도만으로 소제목 뼈대 {len(sections)}개가 나와 최소 {subheading_min}개를 채웁니다",))
    names = ", ".join(SECTIONS[name] for name in added)
    return Feasibility(LEVEL_SUPPLEMENTED, SCORES_BY_ADDED[len(added)], outline, (f"소제목 뼈대 {len(base)}개에 자동 보완 {len(added)}개({names})를 더해 최소 {subheading_min}개를 채웠습니다",))


def assess_candidate(candidate, profile):
    """엔진 후보의 글 종류·검색 의도와 채널 프로필의 소제목 최소 수로 `assess` 한다 — 후보의 채널과 프로필의 채널이 같아야 한다."""
    if not isinstance(candidate, TopicCandidate) or not isinstance(profile, ChannelProfile):
        raise TypeError("assess_candidate(엔진 후보, 채널 프로필) 로 불러야 한다")
    if candidate.channel != profile.key:
        raise ValueError(f"후보의 채널({candidate.channel})과 채널 프로필({profile.key})이 다르다")
    return assess(candidate.content_type, candidate.search_intent, subheading_min=profile.subheading_min)


__all__ = [
    "BASE_OUTLINES", "Feasibility", "INTENT_EXTRAS", "LEVELS", "LEVEL_LOW", "LEVEL_READY", "LEVEL_SUPPLEMENTED", "LEVEL_UNKNOWN", "LOW_SCORE", "MAX_SUBHEADING_MIN", "Outline", "SCORES_BY_ADDED",
    "SECTIONS", "SUPPLEMENT_NOT_FOR", "SUPPLEMENT_ORDER", "assess", "assess_candidate",
]
