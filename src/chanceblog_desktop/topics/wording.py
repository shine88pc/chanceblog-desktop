"""쉬운 말 도우미와 값 이름 표 — 사용자에게 보일 수 있는 오류·진단 문장에서 파이썬 목록 꼴(`['a', 'b']`)·영문 값 이름·내부 식별자를 없앤다(P2b 보완, D-57 — 순수 계산: 파일·네트워크·시계·난수·AI 없음).

이 모듈은 `topics/` 의 맨 아래다 — 표준 라이브러리(`unicodedata`·`types`)만 가져오고 `topics` 의 다른 모듈은 가져오지 않는다(시험이 지킨다). 새 문장은 모두 이 도우미나 `notice.py` 의 카탈로그로만 만든다:
  · `quote`·`quoted`·`one_of`·`unknown_and_missing` 은 운영자가 적은 값을 `‘ ’` 로 감싸 되돌려 보이고(곡선 따옴표가 든 값은 그 따옴표를 지운다), 닫힌 목록의 값은 아래 **값 이름 표**의 쉬운 한국어 이름으로 바꾼다.
  · `object_particle` 은 마지막 글자에 받침이 있는지 보고 '을/를' 을 고른다.
값 이름 표는 닫힌 목록의 **모든 값**에 이름이 있다(시험이 빠짐·남음·겹침을 본다). **표의 이름은 모두 초기값 — 전략 원문 확인 전이다**(원문이 오면 이 파일의 표만 고친다).
"""
from __future__ import annotations

import unicodedata
from types import MappingProxyType

_CURLY = ("‘", "’")                                    # ‘ ’ — 바깥 따옴표와 섞이지 않게 입력 안의 것은 지운다


def clean_word(text, limit=20):
    """운영자가 적은 낱말을 되돌려 보이기 전에 정리한다 — 제어·서식 글자와 곡선 따옴표를 지우고 공백을 하나로 접고, `limit` 자를 넘으면 `…` 로 줄인다(끝 글자 포함 `limit` 자)."""
    kept = []
    for char in str(text):
        if char.isspace():
            kept.append(" ")
        elif unicodedata.category(char) not in ("Cc", "Cf") and char not in _CURLY:
            kept.append(char)
    shown = " ".join("".join(kept).split())
    return shown if len(shown) <= limit else shown[:max(0, limit - 1)] + "…"


def quote(text, limit=20):
    """`‘낱말’` — 운영자가 적은 값은 이렇게 감싸서만 화면 글에 나온다."""
    return _CURLY[0] + clean_word(text, limit) + _CURLY[1]


def quoted(values, *, names=None, limit=None):
    """`‘가’, ‘나’` — `names`(값 → 쉬운 한국어 이름)가 있으면 값을 이름으로 바꾸고 표에 없는 값(운영자가 적은 것)은 `quote(원문)` 이다. `limit` 을 넘으면 `‘가’, ‘나’ 외 2개`."""
    shown = [quote(names[value]) if names is not None and isinstance(value, str) and value in names else quote(value) for value in values]
    if limit is not None and len(shown) > limit:
        return ", ".join(shown[:limit]) + f" 외 {len(shown) - limit}개"
    return ", ".join(shown)


def one_of(allowed, names):
    """`다음 중 하나여야 합니다: ‘가’, ‘나’` — `names` 는 필수다(원시 값만 나열하는 길이 없다)."""
    return "다음 중 하나여야 합니다: " + quoted(allowed, names=names)


def unknown_and_missing(unknown, missing, labels, *, limit=6):
    """`모르는 칸이 있습니다: ‘zzz’ · 빠진 칸이 있습니다: ‘채널당 후보 수’` — 없는 쪽은 줄이고 둘 다 없으면 빈 글. 빠진 칸 이름은 `labels`(칸 이름 → 한국어)로 바꾸고 모르는 칸은 `quote(원문)` 이다. `limit` 개를 넘으면 `외 N개`."""
    parts = []
    if unknown:
        parts.append("모르는 칸이 있습니다: " + quoted([str(item) for item in unknown], limit=limit))
    if missing:
        parts.append("빠진 칸이 있습니다: " + quoted(list(missing), names=labels, limit=limit))
    return " · ".join(parts)


def object_particle(text):
    """마지막 한글 음절에 받침이 있으면 `을`, 없으면 `를`(한글이 아니면 `를`)."""
    last = str(text).rstrip()[-1:]
    if last and "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0:
        return "을"
    return "를"


# ---- 값 이름 표(초기값 — 전략 원문 확인 전) -------------------------------------------------------------------------------------------------
SEED_TYPE_KO = MappingProxyType({"general": "일반", "priority": "우선", "seasonal": "계절", "realtime": "실시간", "sponsorable": "협찬 가능"})
SOURCE_TYPE_KO = MappingProxyType({"seed": "씨앗", "follow_up": "후속", "seasonal": "계절", "realtime": "실시간", "sponsor": "협찬"})
CHANNEL_KO = MappingProxyType({"github_pages": "GitHub Pages", "blogger_en": "Blogger 영문", "blogger_ko": "Blogger 한글", "naver_a": "네이버 A", "naver_b": "네이버 B"})
SCOPE_KO = MappingProxyType({"common": "공통", **CHANNEL_KO})
CHANNEL_ALIAS_KO = MappingProxyType({"blogger_a": "Blogger A(한글)", "blogger_b": "Blogger B(영문)"})
LANGUAGE_KO = MappingProxyType({"ko": "한국어", "en": "영어"})
TREND_USE_KO = MappingProxyType({"primary": "주된 근거로 씀", "supporting": "보조로 씀", "reference": "참고만 함", "none": "쓰지 않음"})
CANDIDATE_TYPE_KO = MappingProxyType({"evergreen": "지속형", "seasonal": "계절형", "realtime": "실시간", "follow_up": "후속", "sponsor_prep": "협찬 준비형"})
SEARCH_INTENT_KO = MappingProxyType({
    "information": "정보 찾기", "how_to": "하는 법 찾기", "problem_solving": "문제 해결", "selection_guide": "고르기", "comparison": "비교", "local_info": "지역 정보", "context_explainer": "배경 이해",
    "routine_building": "습관 만들기"})
CONTENT_TYPE_KO = MappingProxyType({
    "explainer": "설명글", "how_to_guide": "따라 하기 안내", "checklist": "점검표", "troubleshooting": "문제 해결", "buying_guide": "구매 안내", "comparison": "비교", "place_guide": "장소 안내",
    "news_analysis": "소식 분석", "routine_plan": "습관 계획", "dev_log": "개발 기록", "service_intro": "서비스 소개"})
DATA_STATUS_KO = MappingProxyType({"sufficient": "충분", "partial": "일부만 있음", "insufficient": "모자람", "unavailable": "조회 불가"})
DUPLICATE_STATUS_KO = MappingProxyType({"different_topic": "다른 주제", "similar_elements": "비슷한 요소 있음", "different_angle_needed": "다른 관점이 필요", "duplicate_or_update": "중복 또는 기존 글 업데이트 후보"})
SAFETY_FLAG_KO = MappingProxyType({"health_check": "건강 표현", "product_brand": "제품·브랜드", "experience_claim": "경험 단정", "sponsor_disclosure": "협찬 고지", "result_promise": "결과 약속 표현"})
TAG_KO = MappingProxyType({"small_appliance": "소형가전", "pc_peripheral": "PC 주변기기", "lodging_travel": "숙박·여행", "ai_service": "AI 서비스", "pc_parts": "PC 부품", "work_automation": "업무 자동화"})
CLUSTER_KO = MappingProxyType({
    "small-appliances": "소형가전", "pc-peripherals": "PC 주변기기", "lodging-and-travel": "숙박", "local-places": "지역", "daily-problem-solving": "생활 문제 해결", "ai-services": "AI 서비스",
    "api-and-limits": "API 한도", "github-and-deploy": "배포", "local-ai": "로컬 AI", "pc-parts": "PC 부품", "work-automation": "업무 자동화", "desktop-app-log": "데스크톱 앱 기록",
    "industry-impact": "산업 영향", "ai-and-compute": "AI와 컴퓨팅", "energy-and-infrastructure": "에너지와 인프라", "privacy-and-data": "개인정보와 데이터", "platform-policy": "플랫폼 정책",
    "api-transition": "API 전환", "digital-organization": "디지털 정리", "schedule-management": "일정 관리", "memo-and-information": "메모와 정보", "smartphone-settings": "스마트폰 설정",
    "shopping-habits": "쇼핑 습관", "time-management": "시간 관리", "household-budget": "가계부", "personal-productivity": "생산성"})
FILE_KEY_KO = MappingProxyType({"schema": "저장 형식 번호", "profiles": "채널 프로필 목록", "seeds": "씨앗 목록", "entries": "캘린더 항목 목록"})


def tag_name(tag):
    """협찬 태그 → `‘소형가전’` 꼴의 한국어 이름. 표에 없는 태그(운영자가 적은 것)는 `quote(원문)` 이다 — 어느 쪽이든 `‘ ’` 로 감싸서 나온다."""
    return quote(TAG_KO[tag]) if isinstance(tag, str) and tag in TAG_KO else quote(tag)


__all__ = [
    "CANDIDATE_TYPE_KO", "CHANNEL_ALIAS_KO", "CHANNEL_KO", "CLUSTER_KO", "CONTENT_TYPE_KO", "DATA_STATUS_KO", "DUPLICATE_STATUS_KO", "FILE_KEY_KO", "LANGUAGE_KO", "SAFETY_FLAG_KO", "SCOPE_KO",
    "SEARCH_INTENT_KO", "SEED_TYPE_KO", "SOURCE_TYPE_KO", "TAG_KO", "TREND_USE_KO", "clean_word", "object_particle", "one_of", "quote", "quoted", "tag_name", "unknown_and_missing",
]
