"""브랜드 단독 판정 · 유형 확인 · 하위 후보 최대 3개 — 브랜드 이름만 있는 씨앗(Gemini·NVIDIA·삼성 …)은 협찬이나 안전 위험이 아니라 **구체화 대상**이다(P2b 보완, D-55 — 순수 계산: 파일·네트워크·시계·난수·AI 없음).

흐름: 씨앗 낱말이 '표에 있는 브랜드 이름뿐'인지 판정(`find_brands`) → 제품·서비스 유형 확인(`resolve_type` — 브랜드 표의 유형 → 씨앗의 분류·협찬 태그 → 채널의 주제 묶음 → 주력, 모호하면 보류) →
채널별 허용 확장 적용(`expand.expand` 의 방향 낱말만 쓴다) → 하위 후보 **최대 3개**(`MAX_SUBTOPICS`, 틀 표의 순서가 우선순위) → 작성 가능성 검사(`feasibility`) → 구체화에 실패하면 후보 없이 보류('주제 구체화 필요' 또는 '작성 기반 부족').
보류는 후보를 만들지 않고 이유를 알리는 것이다 — 씨앗·후보의 상태를 바꾸거나 저장하는 일은 엔진이 하지 않는다(P3·운영자의 몫).

**이 모듈의 표(브랜드 64개·별칭·제품 유형 9개·하위 후보 틀 22개·유형 확인 표)는 모두 초기값 — 전략 원문 확인 전이다.** 표만 고치고 시험(`test_topics_brand` 의 값 못박기)을 의식적으로 함께 고친다.
브랜드·회사 이름은 안전·협찬 표시의 입력이 아니다 — 이 모듈은 `safety`·`concepts`·`notice`·`generate` 를 가져오지 않고 `model.SAFETY_FLAGS` 도 읽지 않는다(`BRAND_ONLY` 는 표시 값이 아니라 이 모듈의 상태 이름이다).
모르는 이름은 브랜드가 아니다(일반 씨앗 — 오탐보다 미탐이 되돌리기 쉽다). 영문 채널에서는 `assess` 가 '해당 없음' 을 돌려 지금 동작을 그대로 둔다(영어 틀·영문 이름은 다음 몫).
"""
from __future__ import annotations

import re
import unicodedata
from types import MappingProxyType
from typing import NamedTuple

from ..content.candidates import MAX_KEYWORD, MAX_TOPIC, keyword_key
from . import expand, feasibility, wording
from .channels import ChannelProfile
from .dedupe import PARTICLES
from .seeds import Seed

STATE_NOT_BRAND, STATE_BRAND_ONLY = "NOT_BRAND", "BRAND_ONLY"                      # 요청서 §5 의 상태 이름 그대로
NONE, READY, NEEDS_TOPIC, LOW_FOUNDATION = "none", "ready", "needs_topic", "low_foundation"      # 구체화 결과(outcome)
MAX_SUBTOPICS = 3                                                                 # 하위 후보의 최대 수(요청서 §5)
MAX_BRANDS = 4                                                                    # 한 글에서 알아보는 브랜드의 최대 수(나열)
MAX_TEXT = 60                                                                     # 판정하는 글(압축한 뒤)의 최대 길이
KEEP_ALL = True                                                                   # 브랜드 씨앗은 하위 후보를 3개 모두 남긴다(씨앗 유형의 남길 수보다 우선) — False 로 하면 씨앗 유형의 값을 따른다
REASON_UNFEASIBLE = "brand_unfeasible"

# ---- 제품·서비스 유형 9개(초기값) ----------------------------------------------------------------------------------------------------------
BRAND_TYPES = ("ai_service", "gpu", "pc_parts", "pc_peripheral", "appliance", "smartphone", "platform", "software", "travel")
TYPE_KO = MappingProxyType({"ai_service": "AI 서비스", "gpu": "그래픽카드(GPU)", "pc_parts": "PC 부품", "pc_peripheral": "PC 주변기기", "appliance": "가전", "smartphone": "스마트폰",
                            "platform": "플랫폼·서비스", "software": "소프트웨어·업무 도구", "travel": "숙박·여행"})
BASIS_KO = MappingProxyType({"single": "브랜드 표에 유형이 하나뿐이라", "seed": "씨앗의 분류나 협찬 태그를 보고", "channel": "채널이 다루는 분야를 보고", "primary": "브랜드의 주력 유형으로"})

# 묶음 식별자(`expand.CLUSTER_LABELS` 의 열쇠) → 제품 유형. 표에 없는 묶음(지역·생활 문제 해결·산업 영향·에너지와 인프라·가계부·영문 생활 묶음)은 '유형 없음'(초기값)
CLUSTER_TYPES = MappingProxyType({
    "small-appliances": ("appliance",), "pc-peripherals": ("pc_peripheral",), "lodging-and-travel": ("travel",), "ai-services": ("ai_service",), "api-and-limits": ("ai_service",),
    "github-and-deploy": ("software",), "local-ai": ("gpu", "ai_service"), "pc-parts": ("pc_parts", "gpu"), "work-automation": ("software", "ai_service"), "desktop-app-log": ("software",),
    "ai-and-compute": ("gpu", "ai_service"), "privacy-and-data": ("platform",), "platform-policy": ("platform",), "api-transition": ("platform", "software"),
    "digital-organization": ("software",), "schedule-management": ("software",), "memo-and-information": ("software",), "time-management": ("software",), "personal-productivity": ("software",),
    "smartphone-settings": ("smartphone",), "shopping-habits": ("platform",)})
TYPELESS_CLUSTERS = ("local-places", "daily-problem-solving", "industry-impact", "energy-and-infrastructure", "household-budget", "simple-habits", "daily-routines", "meal-planning",
                     "home-organization", "digital-wellbeing", "weekly-reset", "evening-routine")
TAG_TYPES = MappingProxyType({"small_appliance": ("appliance",), "pc_peripheral": ("pc_peripheral",), "lodging_travel": ("travel",), "ai_service": ("ai_service",),
                              "pc_parts": ("pc_parts", "gpu"), "work_automation": ("software", "ai_service")})

# ---- 브랜드 표 64개(초기값) -------------------------------------------------------------------------------------------------------------------
# (표시, 영문 또는 None, 읽기 또는 None, 별칭, 유형(맨 앞이 주력), 모호, api). 표시가 한글이면 읽기=표시. 읽기는 2음절 이상이면 한글 별칭이기도 하다(`NO_READING_ALIAS` 의 이름만 예외).
_BRAND_ROWS = (
    ("Gemini", None, "제미나이", ("제미니", "구글 제미나이", "Google Gemini"), ("ai_service",), False, True),
    ("Claude", None, "클로드", ("앤트로픽 클로드", "Anthropic Claude"), ("ai_service",), False, True),
    ("ChatGPT", None, "챗지피티", ("챗GPT", "챗 지피티", "Chat GPT"), ("ai_service",), False, True),
    ("Copilot", None, "코파일럿", ("마이크로소프트 코파일럿", "Microsoft Copilot", "깃허브 코파일럿", "GitHub Copilot"), ("ai_service",), False, False),
    ("Perplexity", None, "퍼플렉시티", (), ("ai_service",), False, True),
    ("Midjourney", None, "미드저니", ("Mid Journey",), ("ai_service",), False, False),
    ("DeepSeek", None, "딥시크", ("Deep Seek",), ("ai_service",), False, True),
    ("Grok", None, "그록", (), ("ai_service",), False, True),
    ("OpenAI", None, "오픈에이아이", ("오픈AI", "Open AI"), ("ai_service",), False, True),
    ("Anthropic", None, "앤트로픽", (), ("ai_service",), False, True),
    ("NVIDIA", None, "엔비디아", (), ("gpu",), False, False),
    ("AMD", None, "에이엠디", (), ("gpu", "pc_parts"), False, False),
    ("Intel", None, "인텔", (), ("pc_parts", "gpu"), False, False),
    ("ASUS", None, "에이수스", ("아수스",), ("pc_parts", "pc_peripheral"), False, False),
    ("MSI", None, "엠에스아이", (), ("pc_parts", "pc_peripheral"), False, False),
    ("GIGABYTE", None, "기가바이트", (), ("pc_parts",), False, False),
    ("Corsair", None, "커세어", (), ("pc_parts", "pc_peripheral"), False, False),
    ("Seagate", None, "씨게이트", ("시게이트",), ("pc_parts",), False, False),
    ("Western Digital", None, "웨스턴디지털", (), ("pc_parts",), False, False),
    ("Kingston", None, "킹스톤", (), ("pc_parts",), False, False),
    ("SK hynix", None, "에스케이하이닉스", ("SK하이닉스", "하이닉스"), ("pc_parts",), False, False),
    ("ASRock", None, "애즈락", (), ("pc_parts",), False, False),
    ("Cooler Master", None, "쿨러마스터", (), ("pc_parts",), False, False),
    ("Logitech", None, "로지텍", (), ("pc_peripheral",), False, False),
    ("Razer", None, "레이저", (), ("pc_peripheral",), False, False),
    ("Keychron", None, "키크론", (), ("pc_peripheral",), False, False),
    ("BenQ", None, "벤큐", (), ("pc_peripheral",), False, False),
    ("Dell", None, "델", ("델컴퓨터",), ("pc_peripheral",), False, False),
    ("Lenovo", None, "레노버", (), ("pc_peripheral",), False, False),
    ("Acer", None, "에이서", (), ("pc_peripheral",), False, False),
    ("Dyson", None, "다이슨", (), ("appliance",), False, False),
    ("쿠쿠", "Cuckoo", None, ("쿠쿠전자",), ("appliance",), False, False),
    ("쿠첸", "Cuchen", None, (), ("appliance",), False, False),
    ("위닉스", "Winix", None, (), ("appliance",), False, False),
    ("코웨이", "Coway", None, (), ("appliance",), False, False),
    ("발뮤다", "Balmuda", None, (), ("appliance",), False, False),
    ("필립스", "Philips", None, (), ("appliance",), False, False),
    ("일렉트로룩스", "Electrolux", None, (), ("appliance",), False, False),
    ("로보락", "Roborock", None, (), ("appliance",), False, False),
    ("삼성", "Samsung", None, ("삼성전자",), ("appliance", "smartphone", "pc_parts", "pc_peripheral"), True, False),
    ("LG", None, "엘지", ("LG전자", "엘지전자", "LG Electronics"), ("appliance", "pc_peripheral"), True, False),
    ("Apple", None, "애플", (), ("smartphone", "pc_peripheral"), False, False),
    ("샤오미", "Xiaomi", None, (), ("smartphone", "appliance"), True, False),
    ("Google", None, "구글", (), ("platform", "ai_service", "software"), True, False),
    ("네이버", "Naver", None, (), ("platform",), False, False),
    ("카카오", "Kakao", None, ("카카오톡", "KakaoTalk"), ("platform",), False, False),
    ("쿠팡", "Coupang", None, (), ("platform",), False, False),
    ("YouTube", None, "유튜브", (), ("platform",), False, False),
    ("Instagram", None, "인스타그램", (), ("platform",), False, False),
    ("Telegram", None, "텔레그램", (), ("platform",), False, False),
    ("Discord", None, "디스코드", (), ("platform",), False, False),
    ("Microsoft", None, "마이크로소프트", (), ("software", "ai_service", "pc_peripheral"), False, False),
    ("Notion", None, "노션", (), ("software",), False, False),
    ("Obsidian", None, "옵시디언", (), ("software",), False, False),
    ("Slack", None, "슬랙", (), ("software",), False, False),
    ("Figma", None, "피그마", (), ("software",), False, False),
    ("GitHub", None, "깃허브", (), ("software",), False, False),
    ("Adobe", None, "어도비", (), ("software",), False, False),
    ("Canva", None, "캔바", (), ("software",), False, False),
    ("Docker", None, "도커", (), ("software",), False, False),
    ("VS Code", None, "브이에스코드", ("VSCode", "Visual Studio Code", "비주얼 스튜디오 코드"), ("software",), False, False),
    ("야놀자", "Yanolja", None, (), ("travel",), False, False),
    ("Airbnb", None, "에어비앤비", (), ("travel",), False, False),
    ("Agoda", None, "아고다", (), ("travel",), False, False),
)
NO_READING_ALIAS = ("Razer",)                                                     # 읽기('레이저')가 일반 낱말이라 한글 별칭으로 쓰지 않는 이름
NOT_ALIASES = ("모델", "프로", "맥스", "에어", "원", "엣지", "줌", "커서", "고", "메타", "레이저", "델", "HP", "WD", "MS", "토스", "당근")      # 별칭으로 쓰지 않는 말(오탐 방지 — 일부러 뺌)
CONNECTORS = ("and", "or", "및", "그리고", "또는", "와", "과", "랑", "이랑", "하고")          # 홀로 선 이음 낱말(지운다). `vs`·`대`·`비교` 는 목적을 말하는 낱말이라 이음 낱말이 아니다
_CONNECTOR = re.compile("(?<![0-9a-z가-힣])(?:" + "|".join(sorted(CONNECTORS, key=lambda word: (-len(word), word))) + ")(?![0-9a-z가-힣])")
_HANGUL = re.compile(r"[가-힣]+")


class BrandHit(NamedTuple):
    key: str                                        # 브랜드를 가리키는 열쇠(표시를 압축한 글)
    display: str                                    # 한국어 채널 문장에 쓰는 이름
    latin: str | None                               # 영문 이름
    reading: str                                    # 한글 읽기(조사 '을/를' 을 고르는 데 쓴다)
    types: tuple                                    # 제품 유형 — 맨 앞이 주력
    ambiguous: bool                                 # 주력을 정하기 어려워 맥락을 요구하는가
    traits: tuple                                   # 특성(`api` — API 가 있는 서비스)


class Subtopic(NamedTuple):
    template: str                                   # 틀 식별자
    direction: str                                  # 방향 낱말(`expand.DIRECTIONS` 에 있는 낱말)
    source: str                                     # channel·common — 이 채널에서 그 방향이 어디서 왔나
    family: str
    topic: str                                      # 한국어 주제 문장
    keyword: str                                    # 핵심 키워드
    search_intent: str
    content_type: str
    angle: str                                      # 관점 식별자
    brand_free: bool                                # 문장에 브랜드가 없는 유형 수준 틀인가


class Skipped(NamedTuple):
    reason: str                                     # `expand.BLOCK_REASONS` 의 값 또는 `brand_unfeasible`
    detail: str                                     # 씨앗 접두 없는 쉬운 말
    count: int


class BrandView(NamedTuple):
    state: str                                      # STATE_NOT_BRAND | STATE_BRAND_ONLY — 구체화가 되든 안 되든 브랜드 단독이면 BRAND_ONLY
    outcome: str                                    # NONE | READY | NEEDS_TOPIC | LOW_FOUNDATION
    hits: tuple                                     # BrandHit 1~4개(단독이 아니면 ())
    brand_type: str | None                          # 정한 유형(못 정했으면 None)
    basis: str | None                               # single | seed | channel | primary
    subtopics: tuple                                # Subtopic ≤ 3 — 이미 허용·순서·중복 제거·작성 가능성을 통과한 것
    skipped: tuple                                  # Skipped — 막힌 틀과 작성 가능성에서 떨어진 틀
    detail: str                                     # NEEDS_TOPIC 일 때 첫 사례 문장(씨앗 접두 없음 — `generate` 가 `씨앗 ‘낱말’: ` 를 붙인다)
    notes: tuple                                    # 사용자 알림용 고정 줄 — 브랜드 표시·유형 이름·원인(입력 글이 아니다)
    count: int                                      # len(subtopics)

    @property
    def applies(self):
        return self.state == STATE_BRAND_ONLY


NOT_BRAND_VIEW = BrandView(STATE_NOT_BRAND, NONE, (), None, None, (), (), "", (), 0)


def _make_brands():
    brands = []
    for display, latin, reading, _aliases, types, ambiguous, api in _BRAND_ROWS:
        shown_reading = reading or display
        brands.append(BrandHit(keyword_key(display), display, latin if latin else (display if not _HANGUL.search(display) else None), shown_reading, types, ambiguous, ("api",) if api else ()))
    return tuple(brands)


BRANDS = _make_brands()


def _alias_keys():
    """(열쇠, 브랜드 번호) 목록 — 표시·영문·(조건을 채운) 읽기·적어 둔 별칭. 같은 열쇠는 한 브랜드에만 속한다(시험이 지킨다)."""
    rows = []
    for number, (display, latin, reading, aliases, _types, _ambiguous, _api) in enumerate(_BRAND_ROWS):
        words = [display]
        if latin:
            words.append(latin)
        if reading and display not in NO_READING_ALIAS and len(reading) >= 2 and _HANGUL.fullmatch(reading):
            words.append(reading)
        words.extend(aliases)
        for word in words:
            key = keyword_key(word)
            if len(key) >= 2 and (key, number) not in rows:
                rows.append((key, number))
    return tuple(rows)


ALIASES = _alias_keys()
_PARTICLE_LIST = ("",) + tuple(sorted(PARTICLES, key=lambda word: (-len(word), word)))
_BY_FIRST = {}
for _key, _number in sorted(ALIASES, key=lambda row: (-len(row[0]), ALIASES.index(row))):
    _BY_FIRST.setdefault(_key[0], []).append((_key, _number))


def _split(text, position, found):
    if position == len(text):
        return found
    if len(found) >= MAX_BRANDS:
        return None
    for key, number in _BY_FIRST.get(text[position], ()):
        if not text.startswith(key, position):
            continue
        end = position + len(key)
        for tail in _PARTICLE_LIST:
            if text.startswith(tail, end):
                result = _split(text, end + len(tail), found + [number])
                if result is not None:
                    return result
    return None


def find_brands(text):
    """씨앗 낱말 하나 → 브랜드 1~4개(`BrandHit` 튜플 — 글에 나온 순서, 같은 브랜드는 한 번)이거나, 브랜드 이름'만'이 아니면 None. 이음 낱말(and·및·와 …)과 기호는 무시하고, 별칭 바로 뒤의 조사 하나를 허용하며,
    숫자·버전·일반 낱말(비교·추천·API·블로그 …)·모르는 이름이 하나라도 남으면 None 이다."""
    if not isinstance(text, str):
        return None
    folded = unicodedata.normalize("NFKC", text).casefold().replace("+", " ")
    compact = keyword_key(_CONNECTOR.sub(" ", folded))
    if not compact or len(compact) > MAX_TEXT:
        return None
    found = _split(compact, 0, [])
    if not found:
        return None
    return tuple(BRANDS[number] for number in dict.fromkeys(found))


# ---- 유형 확인 -------------------------------------------------------------------------------------------------------------------------
def _types_of(clusters):
    return tuple(dict.fromkeys(kind for slug in clusters for kind in CLUSTER_TYPES.get(slug, ())))


def _narrow(hit, seed, profile):
    """(유형 또는 None, 근거 또는 "", 남은 유형 목록) — `resolve_type` 의 본체."""
    candidates = list(hit.types)
    if len(candidates) == 1:
        return candidates[0], "single", tuple(candidates)
    context = _types_of((expand.cluster_of(seed, profile),)) + TAG_TYPES.get(seed.sponsor_tag, ())
    narrowed = [kind for kind in candidates if kind in context]
    if narrowed:
        candidates = narrowed
        if len(candidates) == 1:
            return candidates[0], "seed", tuple(candidates)
    narrowed = [kind for kind in candidates if kind in _types_of(profile.topic_clusters)]
    if narrowed:
        candidates = narrowed
        if len(candidates) == 1:
            return candidates[0], "channel", tuple(candidates)
    if not hit.ambiguous:
        return candidates[0], "primary", tuple(candidates)
    return None, "", tuple(candidates)


def resolve_type(hit, seed, profile):
    """브랜드의 제품·서비스 유형을 정한다 — (유형 또는 None, 근거). 근거는 `single`(유형이 하나뿐)·`seed`(씨앗의 분류·협찬 태그)·`channel`(채널의 주제 묶음)·`primary`(주력) 중 하나이고, 모호한 브랜드는
    맥락으로도 하나로 좁히지 못하면 (None, "") 이다."""
    if not isinstance(hit, BrandHit) or not isinstance(seed, Seed) or not isinstance(profile, ChannelProfile):
        raise TypeError("resolve_type(브랜드, 씨앗, 채널 프로필) 로 불러야 한다")
    kind, basis, _rest = _narrow(hit, seed, profile)
    return kind, basis


# ---- 하위 후보 틀 22개(초기값) --------------------------------------------------------------------------------------------------------------
class Template(NamedTuple):
    direction: str                                  # `expand.DIRECTIONS` 에 있는 방향 낱말
    content_type: str
    search_intent: str
    angle: str                                      # 관점 식별자 — 일반 확장의 관점과 겹치지 않는다
    condition: str                                  # "" · "api"(브랜드에 api 특성이 있을 때만) · "brand_free"(문장에 브랜드가 없다)
    topic: str                                      # `{brand}` = 브랜드 표시, `{eul}` = 을/를
    keyword: str


SUBTOPICS = MappingProxyType({
    "plan_compare": Template("비교", "comparison", "comparison", "plan-comparison", "", "{brand} 무료·유료 기능을 비교할 때 확인할 항목", "{brand} 무료 유료 기능 비교"),
    "api_usage": Template("API 연동", "how_to_guide", "how_to", "api-usage", "api", "{brand} API 사용량을 관리하는 방법", "{brand} API 사용량 관리"),
    "automation_security": Template("체크리스트", "checklist", "how_to", "automation-security", "", "업무 자동화에 {brand}{eul} 연결할 때 확인할 보안 설정", "{brand} 업무 자동화 보안 설정"),
    "usage_limits": Template("방법", "explainer", "information", "usage-limits", "", "{brand} 사용 한도와 요금 정책을 확인하는 방법", "{brand} 사용 한도 확인"),
    "gpu_vram": Template("성능", "comparison", "comparison", "vram-local-ai", "", "{brand} 그래픽카드의 VRAM을 로컬 AI 기준으로 비교하는 방법", "{brand} 그래픽카드 VRAM 비교"),
    "official_specs": Template("주의할 점", "checklist", "information", "official-specs", "", "{brand} 신제품 공식 사양을 확인할 때 볼 항목", "{brand} 신제품 공식 사양"),
    "gpu_generation": Template("비교", "buying_guide", "selection_guide", "gpu-generation-vram", "brand_free", "로컬 AI용 GPU를 선택할 때 세대와 VRAM을 비교하는 기준", "로컬 AI GPU 선택 기준"),
    "parts_compat": Template("호환성", "checklist", "selection_guide", "parts-compatibility", "", "{brand} 부품을 고를 때 호환성을 확인하는 기준", "{brand} 부품 호환성 확인"),
    "warranty": Template("방법", "explainer", "information", "warranty-service", "", "{brand} 제품의 보증과 서비스 조건을 확인하는 방법", "{brand} 보증 서비스 조건"),
    "purpose_criteria": Template("비교", "buying_guide", "selection_guide", "purpose-criteria", "", "{brand} 제품을 고를 때 사용 목적별로 비교하는 기준", "{brand} 제품 선택 기준"),
    "connection_compat": Template("호환성", "checklist", "selection_guide", "connection-compat", "", "{brand} 제품의 연결 방식과 호환 조건을 확인하는 방법", "{brand} 연결 호환 조건"),
    "care_check": Template("관리 방법", "how_to_guide", "how_to", "care-check", "", "{brand} 제품을 오래 쓰기 위한 관리와 점검 방법", "{brand} 제품 관리 점검"),
    "buying_criteria": Template("구매 기준", "buying_guide", "selection_guide", "purchase-checks", "", "{brand} 제품을 고를 때 확인할 구매 기준", "{brand} 구매 기준"),
    "running_cost": Template("비용", "checklist", "selection_guide", "running-cost", "", "{brand} 제품의 소모품과 유지 비용을 확인하는 방법", "{brand} 유지 비용"),
    "phone_security": Template("체크리스트", "checklist", "how_to", "phone-security", "", "{brand} 스마트폰의 보안과 개인정보 설정을 점검하는 방법", "{brand} 스마트폰 보안 설정"),
    "phone_storage": Template("방법", "how_to_guide", "how_to", "phone-storage-battery", "", "{brand} 스마트폰의 저장 공간과 배터리를 관리하는 방법", "{brand} 스마트폰 저장 공간 배터리"),
    "account_security": Template("체크리스트", "checklist", "how_to", "account-security", "", "{brand} 계정 보안과 개인정보 설정을 점검하는 방법", "{brand} 계정 보안 설정"),
    "policy_change": Template("주의할 점", "explainer", "context_explainer", "policy-change", "", "{brand} 서비스의 정책이나 기능이 바뀔 때 확인할 곳", "{brand} 정책 변경 확인"),
    "workflow_settings": Template("방법", "how_to_guide", "how_to", "workflow-settings", "", "{brand} 설정을 정리해 업무 흐름을 단순하게 만드는 방법", "{brand} 설정 정리"),
    "cancel_refund": Template("체크리스트", "checklist", "selection_guide", "cancel-refund", "", "{brand} 예약 전에 확인할 취소·환불 조건", "{brand} 취소 환불 조건"),
    "price_compare": Template("비교", "comparison", "comparison", "price-comparison", "", "{brand} 요금을 비교할 때 확인할 포함 항목", "{brand} 요금 비교"),
    "booking_organize": Template("방법", "how_to_guide", "how_to", "booking-organize", "", "{brand} 예약 내역과 일정을 정리하는 방법", "{brand} 예약 일정 정리"),
})
TYPE_SUBTOPICS = MappingProxyType({                                                # 유형 → 틀 순서(이 순서가 곧 우선순위)
    "ai_service": ("plan_compare", "api_usage", "automation_security", "usage_limits"),
    "gpu": ("gpu_vram", "official_specs", "gpu_generation", "warranty"),
    "pc_parts": ("parts_compat", "official_specs", "warranty", "purpose_criteria"),
    "pc_peripheral": ("purpose_criteria", "connection_compat", "care_check", "running_cost"),
    "appliance": ("buying_criteria", "care_check", "running_cost", "warranty"),
    "smartphone": ("purpose_criteria", "phone_security", "phone_storage"),
    "platform": ("account_security", "policy_change", "usage_limits"),
    "software": ("plan_compare", "automation_security", "workflow_settings"),
    "travel": ("cancel_refund", "price_compare", "booking_organize"),
})


def _names(kinds):
    return "·".join(TYPE_KO[kind] for kind in kinds)


def _view(outcome, hits, kind, basis, subtopics, skipped, detail, notes):
    return BrandView(STATE_BRAND_ONLY, outcome, hits, kind, basis, tuple(subtopics), tuple(skipped), detail, tuple(notes), len(subtopics))


def _blocked_skips(opened):
    return {keyword_key(item.direction): item for item in opened.blocked}


def assess(seed, profile, *, as_type=None):
    """씨앗 한 건 → `BrandView`. 브랜드 이름만 있는 씨앗이면 `state` 가 `BRAND_ONLY` 이고 `outcome` 이 구체화 결과(`ready`·`needs_topic`·`low_foundation`)다. 아니면(또는 영문 채널이면) `NOT_BRAND_VIEW`.
    순수 계산이고 입력은 바꾸지 않는다."""
    if not isinstance(seed, Seed) or not isinstance(profile, ChannelProfile):
        raise TypeError("assess(씨앗, 채널 프로필) 로 불러야 한다")
    if profile.language == "en":
        return NOT_BRAND_VIEW
    hits = find_brands(seed.keyword)
    if hits is None:
        return NOT_BRAND_VIEW
    names = "·".join(hit.display for hit in hits)
    if len(hits) >= 2:
        return _view(NEEDS_TOPIC, hits, None, None, (), (), f"브랜드 이름이 둘 이상({names})이라 하나로 구체화하지 못해 보류했습니다 — 브랜드를 하나로 줄이거나 비교 목적을 덧붙여 주세요",
                     (f"브랜드가 둘 이상입니다: {names}",))
    hit = hits[0]
    kind, basis, rest = _narrow(hit, seed, profile)
    if kind is None:
        return _view(NEEDS_TOPIC, hits, None, None, (), (), f"브랜드 이름만 있고 제품 유형이 여럿({_names(rest)})이라 작성 방향을 정하지 못해 보류했습니다 — 씨앗의 중분류를 ‘소형가전’ 처럼 알려진 묶음 이름으로 적거나 협찬 태그를 붙여 제품 유형을 알려 주세요",
                     (f"제품 유형이 여럿입니다: {_names(rest)}",))
    opened = expand.expand(seed, profile, limit=expand.MAX_LIMIT, as_type=as_type)
    allowed = {keyword_key(item.direction): item for item in opened.items}
    blocked = _blocked_skips(opened)
    excluded = [(word, keyword_key(word)) for word in seed.excluded_keywords if keyword_key(word)]
    skipped, chosen = [], []
    for name in TYPE_SUBTOPICS[kind]:
        template = SUBTOPICS[name]
        if template.condition == "api" and "api" not in hit.traits:
            continue
        key = keyword_key(template.direction)
        if key in allowed:
            if len(chosen) < MAX_SUBTOPICS:
                chosen.append((name, template, allowed[key]))
        elif key in blocked:
            skipped.append(Skipped(blocked[key].reason, blocked[key].detail, 1))
    if not chosen:
        return _view(NEEDS_TOPIC, hits, kind, basis, (), skipped, "브랜드 이름만 있는데 이 채널에서 쓸 수 있는 하위 주제 틀이 없어 보류했습니다 — 채널의 확장 방향이나 씨앗의 제외 키워드를 확인해 주세요",
                     ("이 채널에서 쓸 수 있는 하위 주제 틀이 없습니다",))
    made, seen, unfeasible = [], set(), 0
    for name, template, item in chosen:
        values = {"brand": hit.display, "eul": wording.object_particle(hit.reading)}
        topic, keyword = template.topic.format(**values), template.keyword.format(**values)
        excluded_hit = next((shown for shown, word_key in excluded if word_key in keyword_key(topic) or word_key in keyword_key(keyword)), None)
        if excluded_hit is not None:
            skipped.append(Skipped("excluded_keyword", f"씨앗의 제외 키워드 {wording.quote(excluded_hit)} 이(가) 들어 있어 쓰지 않습니다", 1))
            continue
        if len(keyword) > MAX_KEYWORD or len(topic) > MAX_TOPIC:
            skipped.append(Skipped("too_long", f"확장한 키워드가 {MAX_KEYWORD}자를 넘어 쓰지 않습니다", 1))
            continue
        if feasibility.assess(template.content_type, template.search_intent, subheading_min=profile.subheading_min).level == feasibility.LEVEL_LOW:
            unfeasible += 1
            continue
        marker = (keyword_key(keyword), keyword_key(topic))
        if marker[0] in seen or marker[1] in seen:
            continue
        seen.update(marker)
        made.append(Subtopic(name, item.direction, item.source, item.family, topic, keyword, template.search_intent, template.content_type, template.angle, template.condition == "brand_free"))
    minimum = profile.subheading_min
    if unfeasible and not made:
        skipped.append(Skipped(REASON_UNFEASIBLE, f"구체화한 하위 주제 {unfeasible}개가 모두 소제목 최소 수({minimum}개)를 채우지 못해 ‘작성 기반 부족’ 으로 보류했습니다", unfeasible))
    elif unfeasible:
        skipped.append(Skipped(REASON_UNFEASIBLE, f"구체화한 하위 주제 {unfeasible}개는 소제목 최소 수({minimum}개)를 채우지 못해 쓰지 않습니다", unfeasible))
    if not made:                                    # 허용 틀은 있었으나 모두 떨어졌다 — 보류 기록은 skipped 의 줄들이다
        return _view(LOW_FOUNDATION, hits, kind, basis, (), skipped, "",
                     (f"소제목 최소 수를 채우지 못한 하위 주제: {unfeasible}개",) if unfeasible else ("제외 키워드나 길이 때문에 쓸 수 있는 하위 주제가 남지 않았습니다",))
    notes = (f"브랜드: {hit.display}", f"제품·서비스 유형: {TYPE_KO[kind]}", f"유형을 정한 근거: {BASIS_KO[basis]}")
    return _view(READY, hits, kind, basis, made, skipped, "", notes)


__all__ = [
    "ALIASES", "BASIS_KO", "BRANDS", "BRAND_TYPES", "BrandHit", "BrandView", "CLUSTER_TYPES", "CONNECTORS", "KEEP_ALL", "LOW_FOUNDATION", "MAX_BRANDS", "MAX_SUBTOPICS", "NEEDS_TOPIC", "NONE",
    "NOT_ALIASES", "NOT_BRAND_VIEW", "NO_READING_ALIAS", "READY", "REASON_UNFEASIBLE", "STATE_BRAND_ONLY", "STATE_NOT_BRAND", "SUBTOPICS", "Skipped", "Subtopic", "TAG_TYPES", "TYPELESS_CLUSTERS",
    "TYPE_KO", "TYPE_SUBTOPICS", "Template", "assess", "find_brands", "resolve_type",
]
