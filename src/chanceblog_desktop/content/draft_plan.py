"""작성 기반(`DraftPlan`) — 후보 하나와 대상 블로그의 프로필, (선택) 사용자 입력으로 **초안의 뼈대**(제목 후보 3개·권장 목차와 소제목·포함할 핵심 내용·주의사항·태그·확인 권장)를 규칙으로 만든다
(요구서 v0.3.1 §5·§6·§8·§9). 초안 본문 문장은 만들지 않고, AI·네트워크·파일도 쓰지 않으며, 무작위도 없다 — 같은 입력은 늘 같은 계획이다.

**값 적용 순서**(§5.3): 사용자 입력 → 블로그 프로필 → 글 유형 틀 → 후보(키워드 분석) → 공통 기본값. 계획의 각 값이 어느 층에서 왔는지 `sources` 에 남긴다(시험·화면 설명용).
  · 글 유형만 순서가 다르다: 사용자가 정한 유형 → 후보의 추천 유형 → 프로필의 기본 글 유형 → '정보형'(`post_types.resolve_post_type`).
  · 프로필의 글 길이(800~6,000자)·후보/프로필의 글 유형(정보형)이 클래스 기본값이면 '정하지 않은 것' 으로 본다(기본값과 직접 정한 값을 가릴 수 없다).
**안전 대체**(§6.2): 후기·방문·체험처럼 경험을 전제한 후보가 경험 입력 없이 오면 경험담을 지어내지 않고 정보형 안내 글로 바꾸고, 바꿨다는 사실을 확인 권장에 적는다. 확인 권장이 있어도 계획은 늘 완성 상태다(§9.3).
**두 블로그**(§8): 블로그마다 말씨(`post_types.VOICE` — naver_a 0, naver_b 1)가 있어 제목·소제목·핵심 내용 문구, 도입 방향, 설명 방식, 마무리, 소제목을 묶는 방식, 태그 조합이 다르다. 프로필이 정한 도입부 스타일·설명 난이도·마무리 방식이
있으면 그것이 말씨의 기본값을 덮는다. 같은 후보로 만든 두 계획이 너무 비슷하면 `compare_plans` 가 경고한다(`check/similarity.py` 재사용).
**지어내지 않기**: 계획의 문장은 모두 경험·가격·날짜·통계를 단정하지 않는 안내 문장이고(시험이 `check/claims.py` 로 전수 확인한다), 후보의 글을 끌어 쓸 때도 경험을 단정하는 말이 들어 있으면 쓰지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import datetime

from ..check import claims as claim_check
from ..check import similarity
from ..errors import AppError
from . import post_types as pt
from . import status as st
from .candidates import Candidate
from .draft_options import DraftOptions, LengthWish, squash
from .profiles import KEYS as NAVER_KEYS
from .profiles import POST_TYPES, NaverProfile

LAYER_USER, LAYER_PROFILE, LAYER_TYPE, LAYER_CANDIDATE, LAYER_DEFAULT = "user", "profile", "post_type", "candidate", "default"
LAYERS = (LAYER_USER, LAYER_PROFILE, LAYER_TYPE, LAYER_CANDIDATE, LAYER_DEFAULT)
LAYER_KO = {LAYER_USER: "사용자 입력", LAYER_PROFILE: "블로그 프로필", LAYER_TYPE: "글 유형 틀", LAYER_CANDIDATE: "후보(키워드 분석)", LAYER_DEFAULT: "공통 기본값"}
TYPE_ORDER = (LAYER_USER, LAYER_CANDIDATE, LAYER_PROFILE, LAYER_DEFAULT)         # 글 유형만의 순서(후보의 추천이 프로필의 기본 유형보다 앞선다)

DEFAULT_AUDIENCE = "이 주제를 처음 접하는 일반 사용자"
DEFAULT_TONE = "쉬운 존댓말 설명체"
DEFAULT_LENGTH = (1500, 2000)
DEFAULT_SUBHEADINGS = (3, 5)
DEFAULT_TITLE_LIMIT = 60
DEFAULT_TAG_LIMIT = 10
DEFAULT_PARAGRAPH = 180
TITLE_COUNT = 3
MIN_TITLE_LIMIT = 8                        # 제목 길이 상한이 이보다 작아도 이만큼은 쓴다(그보다 짧으면 서로 다른 제목 셋을 만들 수 없다)
STALE_DAYS = 30                            # 후보의 데이터 조회일이 오늘보다 이만큼보다 오래됐으면 확인 권장
MAX_CHECK_WORDS = 10                       # 문장에 나열하는 낱말(금지 표현·제외 낱말)의 최대 개수
PROFILE_TEXT_LABELS = {"tone": "말투", "audience": "대상 독자", "intro_style": "도입부 스타일", "difficulty": "설명 난이도", "ending_style": "마무리 방식"}      # 계획 문장에 그대로 옮겨 쓰는 프로필 글
_PROFILE_DEFAULTS = {item.name: item.default for item in fields(NaverProfile)}      # 프로필 칸의 기본값(정하지 않은 것을 가리는 데 쓴다)
_PROFILE_LENGTH_DEFAULT = (_PROFILE_DEFAULTS["min_chars"], _PROFILE_DEFAULTS["max_chars"])

# ---- 스타일(프로필의 안내 글을 규칙으로 읽는다) ------------------------------------------------------------------------------------------
INTRO_STYLES = (("problem", ("고민", "문제", "질문", "궁금", "공감")), ("purpose", ("요약", "결론", "핵심", "두괄", "목적", "먼저")), ("context", ("배경", "상황", "최근", "계절", "시기", "이슈")))
DIFFICULTY_STYLES = (("beginner", ("쉬운", "처음", "초보", "입문", "누구나", "기초")), ("practical", ("실무", "실용", "실전", "적용", "활용")), ("expert", ("전문", "심화", "깊", "고급", "자세", "상세")))
ENDING_STYLES = (("summary", ("요약", "정리", "핵심")), ("checklist", ("체크", "점검표", "확인표", "리스트")), ("next", ("다음", "이어", "후속", "예고")))
DEFAULT_INTRO = {0: "problem", 1: "purpose"}                 # 프로필이 정하지 않았을 때 말씨별 기본 도입 방식(공통 기본값의 '문제와 글의 목적' 을 문제 먼저·목적 먼저로 나눈 것)
DEFAULT_DIFFICULTY = "beginner"
DEFAULT_ENDING = "summary"
INTRO_LINES = {
    "problem": ("독자가 궁금해할 문제를 질문으로 던지고 이 글이 답하는 범위를 밝히며 시작합니다", "독자가 겪을 만한 고민을 먼저 짚고 이 글에서 다룰 내용을 이어 알려 줍니다"),
    "purpose": ("글의 목적과 핵심 결론을 먼저 밝히고 이유는 뒤에서 풀어 줍니다", "먼저 이 글에서 얻을 수 있는 것을 알리고 세부 내용은 차례로 이어 갑니다"),
    "context": ("이 주제가 지금 왜 필요한지 배경과 상황을 짧게 짚으며 시작합니다", "주제가 나온 배경과 독자의 상황을 먼저 설명하고 본문으로 들어갑니다"),
}
DIFFICULTY_LINES = {
    "beginner": ("용어는 처음 나올 때 한 번 풀어 쓰고 어려운 말은 쉬운 말로 바꿔 설명합니다", "전문 용어를 줄이고 꼭 필요한 용어만 쉬운 설명과 함께 씁니다"),
    "practical": ("기준과 순서를 앞세워 바로 따라 할 수 있게 설명합니다", "실제로 적용하는 순서를 중심으로 필요한 설명만 덧붙입니다"),
    "expert": ("정의와 근거를 갖춘 자세한 설명으로 깊이 있게 풀어 씁니다", "배경과 원리까지 차근차근 짚어 상세히 설명합니다"),
}
ENDING_LINES = {
    "summary": ("핵심만 과장 없이 다시 정리하며 마무리합니다", "중요한 내용을 한 번 더 짚고 담백하게 마무리합니다"),
    "checklist": ("확인할 항목을 체크리스트로 묶어 마무리합니다", "다시 확인하기 쉽도록 점검 항목 목록으로 끝맺습니다"),
    "next": ("다음에 확인하면 좋을 것을 알려 주며 마무리합니다", "이어서 살펴볼 내용을 안내하며 끝맺습니다"),
}
EXAMPLE_LINES = ("예시는 가상의 상황임을 밝히고 실제 사례처럼 쓰지 않습니다", "예시를 들 때는 일반적인 상황을 가정한 것이라고 분명히 적습니다")
READER_LINES = ("{audience}의 눈높이에서 설명합니다", "독자({audience})가 궁금해할 순서대로 풀어 갑니다")
TONE_LINES = ("{tone:으로/로} 씁니다", "{tone:을/를} 바탕으로 읽기 편하게 씁니다")                 # `{값:받침 뒤/받침 없는 뒤}` — 값의 마지막 글자에 맞춰 조사를 고른다(`_fill`)
LENGTH_LINES = ("{length:을/를} 목표로 합니다", "분량은 {length} 안에서 맞춥니다")
PARAGRAPH_LINES = ("한 문단은 {size}자 안팎으로 짧게 나눕니다", "문단마다 {size}자 안팎에서 끊어 읽기 쉽게 합니다")
GENERAL_CAUTIONS = ("확인하지 않은 가격·날짜·수치는 적지 않고 공식 자료에서 확인한 값만 씁니다", "경험하지 않은 일을 경험한 것처럼 쓰지 않습니다", "결과를 장담하거나 과장하는 표현은 쓰지 않습니다")
DIRECTION_TITLES = (                                          # (제목 방향에서 찾을 낱말, (말씨 0 의 제목, 말씨 1 의 제목))
    (("질문", "궁금", "물음"), ("{kw}, 무엇이 궁금하세요?", "{kw}, 이런 점이 궁금하다면?")), (("짧", "간결", "담백"), ("{kw} 정리", "{kw} 한 줄 정리")),
    (("결론", "정답", "한줄"), ("{kw}: 결론부터 정리", "결론부터 보는 {kw}")), (("비교",), ("{kw} 비교", "{kw}, 비교해 보면")),
    (("순서", "방법", "단계"), ("{kw}, 순서대로 따라가기", "{kw} 단계별 정리")), (("초보", "입문", "쉽", "처음"), ("{kw}, 처음이어도 쉽게", "처음 보는 분을 위한 {kw}")),
)
VERBATIM_DIRECTION = ("{kw}, {text}", "{text}: {kw}")           # 낱말로 읽지 못한 제목 방향은 입력한 글 그대로 제목에 넣는다
CONCLUSION_TITLES = ("{kw}: {text}", "{text}: {kw}")
GENERIC_SUBJECT = "이 주제"
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _invalid(item, reason, *, detail=""):
    return AppError("DRAFT_OPTION_INVALID", {"항목": item, "이유": reason}, detail=detail or reason)


def _given(value):
    return value is not None and value != "" and value != () and value != []


def apply_priority(layers, order=LAYERS):
    """값 적용 순서 — `layers`({층 이름: 값})에서 `order` 의 앞 층부터 보아 처음으로 값이 있는(None·''·빈 목록이 아닌) 것을 (값, 층 이름) 으로 돌려준다. 어느 층에도 없으면 CONTENT_INVALID."""
    for layer in order:
        value = layers.get(layer)
        if _given(value):
            return value, layer
    raise AppError("CONTENT_INVALID", {"항목": "값 적용 순서"}, detail="어느 층에도 값이 없다")


def style_of(text, table):
    """프로필의 안내 글(예: '독자의 고민으로 시작') → 스타일 열쇠. 낱말 규칙으로 읽고, 못 읽으면 None."""
    plain = squash(text)
    if not plain:
        return None
    for style, words in table:
        if any(word in plain for word in words):
            return style
    return None


def group_sizes(count, groups, voice):
    """`count` 개 단계를 `groups` 개 소제목으로 묶을 때 소제목마다 단계가 몇 개씩인지(앞에서부터). 같게 나누고 남는 것은 말씨 0 이면 가운데부터, 1 이면 뒤에서부터 한 개씩 더 얹는다."""
    base, extra = divmod(count, groups)
    sizes = [base] * groups
    order = sorted(range(groups), key=lambda index: (abs(index - (groups - 1) / 2), index)) if voice == 0 else list(range(groups - 1, -1, -1))
    for index in order[:extra]:
        sizes[index] += 1
    return sizes


def length_korean(length):
    low, high = length
    return f"{low:,}자 이상" if high is None else f"{low:,}~{high:,}자"


def _tag(text):
    """태그 하나 — 공백·`#` 를 걷어 한 낱말로(네이버 복사 패키지의 태그 규칙과 같다), 30자 이하. 못 쓰면 ''."""
    cleaned = "".join(str(text).split()).replace("#", "").strip(",;")
    return cleaned if 0 < len(cleaned) <= 30 else ""


def _collapse(text):
    """바로 이어진 같은 낱말을 하나로('노트북 비교' + ' 비교 가이드' → '노트북 비교 가이드', '점검 점검법' → '점검법')."""
    words = []
    for word in text.split(" "):
        plain = word.rstrip(",.:;?!")
        previous = words[-1].rstrip(",.:;?!") if words else ""
        if words and word and (plain == previous or (len(previous) >= 2 and plain.startswith(previous))):
            words[-1] = word                                                              # 뒤의 것(쉼표가 붙었거나 더 긴 낱말)을 남긴다
        else:
            words.append(word)
    return " ".join(words)


_FINAL = {"0": 21, "1": 8, "2": 0, "3": 16, "4": 0, "5": 0, "6": 1, "7": 8, "8": 8, "9": 0}       # 숫자를 읽는 소리의 받침(영·일·이·삼·사·오·육·칠·팔·구) — 종성 번호
_SLOT = re.compile(r"\{(\w+)(?::([^{}/]+)/([^{}/]+))?\}")


def _final(text):
    """글의 마지막 글자의 받침(종성 번호, 없으면 0 — ㄹ 받침은 8). 한글은 받침, 숫자는 읽는 소리, 영문은 글자 이름(엘·엠·엔·알)을 본다."""
    for char in reversed(text.rstrip(" )」』’”\"'.,·…")):
        if "가" <= char <= "힣":
            return (ord(char) - 0xAC00) % 28
        if char in _FINAL:
            return _FINAL[char]
        if char.isalpha():
            return {"l": 8, "m": 16, "n": 4, "r": 8}.get(char.casefold(), 0)
        return 0
    return 0


def particle(text, with_final, without_final):
    """`text` 뒤에 붙일 조사 — 마지막 글자에 받침이 있으면 `with_final`, 없으면 `without_final`('으로/로' 는 ㄹ 받침도 '로')."""
    final = _final(text)
    return without_final if final == 0 or (with_final == "으로" and final == 8) else with_final


def _fill(template, **values):
    """`{이름}` 자리에 값을 넣고 `{이름:을/를}` 자리에는 값을 넣은 뒤 받침에 맞는 조사(을/를·이/가·은/는·으로/로)를 붙인다."""
    def put(match):
        value = str(values[match.group(1)])
        if match.group(2) is None:
            return value
        return value + particle(value, match.group(2), match.group(3))
    return _SLOT.sub(put, template)


def _day(value):
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        raise _invalid("기준 날짜", "2026-11-02 같은 모양이어야 합니다")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise _invalid("기준 날짜", "2026-11-02 같은 모양의 달력에 있는 날짜여야 합니다") from None
    return value


class _Excluder:
    """제외할 낱말(사용자의 '제외할 내용' + 프로필의 제외 주제) — 띄어쓰기·대소문자·전각을 무시하고 낱말이 글에 들어 있는지 본다."""

    def __init__(self, user_terms, profile_terms):
        self.terms = tuple((squash(term), term, who) for who, group in (("user", user_terms), ("profile", profile_terms)) for term in group if squash(term))

    def hit(self, text):
        plain = squash(text)
        for squashed, term, who in self.terms:
            if squashed in plain:
                return term, who
        return None

    def __bool__(self):
        return bool(self.terms)


def _forbidden_hit(text, phrases):
    plain = squash(text)
    return next((phrase for phrase in phrases if squash(phrase) and squash(phrase) in plain), None)


@dataclass(frozen=True)
class DraftPlan:
    blog: str                       # 대상 블로그 구분(github_pages·blogger_en·blogger_ko·naver_a·naver_b)
    topic: str                      # 추천 포스팅 주제(경험을 단정하는 말을 걷어 낸 모양)
    keyword: str                    # 핵심 키워드(같음)
    sub_keywords: tuple             # 보조 키워드
    intent: str                     # 예상 검색 의도
    audience: str                   # 대상 독자
    post_type: str                  # 적용한 글 유형(안전 대체를 했다면 바뀐 뒤의 것)
    titles: tuple                   # 제목 후보 3개
    direction: tuple                # 본문 작성 방향 — ((이름, 문장), …)
    outline: tuple                  # 권장 목차 — 소제목마다 그 소제목이 맡은 틀의 단계 이름(여럿이면 ' + ' 로 잇는다)
    subheadings: tuple              # 소제목(목차와 같은 개수·순서)
    key_points: tuple               # 포함할 핵심 내용
    cautions: tuple                 # 주의사항
    category: str                   # 추천 카테고리('' 이면 정하지 못했다)
    tags: tuple                     # 추천 태그
    base_date: str                  # 기준 날짜(YYYY-MM-DD)
    references: tuple               # 참고할 수 있는 공개 자료 — 사용자가 준 주소만(자동 검색 없음, 열어 보지도 않는다)
    checks: tuple                   # 확인 권장 — 있어도 계획은 완성이다
    length: tuple                   # 글 길이 (하한, 상한) — 상한이 None 이면 '이상'
    sources: tuple                  # ((항목, 층), …) — 각 값이 어느 층에서 왔나
    replaced: object = None         # 안전 대체를 했으면 (후보가 전제한 형식, 바꾼 안내 글) — 아니면 None

    @property
    def complete(self):
        """확인 권장이 있어도 계획은 완성이다(§9.3)."""
        return True

    def source_of(self, item):
        """그 항목의 값이 온 층 이름(`LAYERS`). 모르는 항목은 None."""
        return dict(self.sources).get(item)

    def texts(self):
        """계획의 모든 문장 — '지어내지 않기' 검사를 돌릴 때 쓴다."""
        return (*self.titles, self.intent, self.audience, *(text for _label, text in self.direction), *self.outline, *self.subheadings, *self.key_points, *self.cautions, *self.checks)

    def intro_text(self):
        return next((text for label, text in self.direction if label == "도입부"), "")

    def frame(self, text):
        """글에서 주제 낱말(핵심 키워드·주제)과 사용자가 입력한 제목 방향·결론을 뺀 것 — 같은 주제를 다루고 같은 입력을 받는 것은 당연하니 규칙이 만든 문구의 틀이 얼마나 비슷한지만 본다."""
        given = [value for label, value in self.direction if "(입력" in label]
        for word in sorted({self.keyword, self.topic, *given}, key=lambda word: (-len(word), word)):
            if word:
                text = text.replace(word, "")
        return text

    def comparable_body(self):
        """두 계획을 견줄 때 쓰는 글 — 사용자가 입력한 내용(두 블로그가 똑같이 받는다)과 주제 낱말은 빼고 규칙이 만든 부분만."""
        generated = [self.intent, *(text for _label, text in self.direction), *self.outline, *self.subheadings, *(point for point in self.key_points if "(입력" not in point)]
        return self.frame("\n\n".join(generated))

    def to_dict(self):
        return {
            "blog": self.blog, "topic": self.topic, "keyword": self.keyword, "sub_keywords": list(self.sub_keywords), "intent": self.intent, "audience": self.audience, "post_type": self.post_type,
            "titles": list(self.titles), "direction": [{"label": label, "text": text} for label, text in self.direction], "outline": list(self.outline), "subheadings": list(self.subheadings),
            "key_points": list(self.key_points), "cautions": list(self.cautions), "category": self.category, "tags": list(self.tags), "base_date": self.base_date, "references": list(self.references),
            "checks": list(self.checks), "length": {"min": self.length[0], "max": self.length[1]}, "complete": self.complete, "sources": dict(self.sources),
            "replaced": None if self.replaced is None else {"from": self.replaced[0], "to": self.replaced[1]},
        }


class _Planner:
    def __init__(self, candidate, profile, options, today, blog, user_type):
        self.candidate, self.profile, self.options, self.today, self.blog = candidate, profile, options, today, blog
        self.voice = pt.VOICE[blog]
        self.experience = options.has_experience
        self.checks, self.sources = [], {}
        self.excluder = _Excluder(options.exclude, profile.excluded_topics if profile is not None else ())
        self.forbidden = tuple(profile.forbidden_phrases) if profile is not None else ()
        self.user_type = user_type
        self.skipped = set()                                    # 경험을 단정하는 표현이 있어 쓰지 않은 프로필 칸

    # ---- 층 고르기 ---------------------------------------------------------------------------------------------------------
    def pick(self, item, *, order=LAYERS, **layers):
        value, layer = apply_priority(layers, order)
        self.sources[item] = layer
        return value

    def profile_value(self, name, *, unset=None):
        """프로필의 값(없거나 기본값이면 None — 기본값은 정하지 않은 것으로 본다). 말투·안내 글에 경험을 단정하는 표현이 있으면 계획에 옮기지 않고(None) 확인 권장으로 알린다."""
        if self.profile is None:
            return None
        value = getattr(self.profile, name)
        if (unset is not None and value == unset) or value == "":
            return None
        if isinstance(value, str) and name in PROFILE_TEXT_LABELS and claim_check.find_violations([value]):
            if name not in self.skipped:
                self.skipped.add(name)
                self.checks.append(f"블로그 프로필의 ‘{PROFILE_TEXT_LABELS[name]}’ 에 직접 겪은 일을 단정하는 표현이 있어 계획에 쓰지 않았습니다 — 프로필을 확인해 주세요.")
            return None
        return value

    # ---- 주제 글 다듬기 ------------------------------------------------------------------------------------------------------
    def clean_subject(self, text, strip):
        """제목·소제목에 쓸 후보의 글 — 경험 낱말을 걷고(`strip`), 그래도 경험을 단정하는 말이 있으면 쓰지 않는다(''). """
        cleaned = (pt.strip_premise(text) if strip else text) or text
        if claim_check.find_violations([cleaned]):
            stripped = pt.strip_premise(cleaned)
            if stripped and not claim_check.find_violations([stripped]):
                return stripped
            return ""
        return cleaned

    def safe(self, text):
        """태그·보조 키워드처럼 짧은 글 — 경험을 단정하는 말이 있으면 ''."""
        return "" if claim_check.find_violations([text]) else text

    @staticmethod
    def quotable(word):
        """안내 문장에 옮겨 적을 낱말 — 경험을 단정하는 말이 들어 있으면 그대로 옮기지 않는다."""
        return "(경험 표현이라 적지 않음)" if claim_check.find_violations([word]) else word

    # ---- 계획 만들기 ---------------------------------------------------------------------------------------------------------
    def build(self):
        candidate, options, profile, voice = self.candidate, self.options, self.profile, self.voice
        # 글 유형과 안전 대체
        asked = self.user_type or None
        chosen = self.pick("post_type", order=TYPE_ORDER, user=asked, candidate=candidate.post_type if candidate.post_type != POST_TYPES[0] else None,
                           profile=self.profile_value("post_type", unset=POST_TYPES[0]), default=POST_TYPES[0])
        premise = pt.premise_of(candidate.topic, candidate.keyword, *candidate.sub_keywords)
        replaced = None
        if premise is not None and not self.experience:
            if premise.post_type and not asked and premise.post_type != chosen:            # 사용자가 정한 유형은 존중한다 — 그때는 후기 형식만 쓰지 않는다
                chosen = premise.post_type
                self.sources["post_type"] = LAYER_TYPE
            replaced = (premise.label_from, premise.label_to if premise.post_type and not asked else f"{chosen} 안내 글")
            self.checks.append(f"후보가 ‘{premise.label_from}’ 형식이지만 직접 겪은 내용이 입력되지 않아 경험담 없이 바꿔 만들었습니다(바꾼 안내 글: {replaced[1]}) — 직접 겪은 경험이 있다면 ‘실제 사용 경험’ 칸에 적어 주세요.")
        post_type = chosen
        strip = replaced is not None
        keyword = self.clean_subject(candidate.keyword, strip)
        if not keyword:
            keyword = GENERIC_SUBJECT
            self.checks.append("후보의 핵심 키워드에 경험을 단정하는 표현이 있어 제목·소제목에는 ‘이 주제’ 로 적었습니다 — 후보의 키워드를 확인해 주세요.")
        topic = self.clean_subject(candidate.topic, strip) or keyword
        subs = tuple(dict.fromkeys(item for item in (self.safe(self.clean_subject(sub, strip)) for sub in candidate.sub_keywords) if item and squash(item) != squash(keyword)))
        dropped = [sub for sub in subs if self.excluder.hit(sub)]
        if dropped:                                                                                  # 제외할 말이 든 보조 키워드는 핵심 내용·태그·카테고리 어디에도 쓰지 않는다
            subs = tuple(sub for sub in subs if sub not in dropped)
            self.checks.append("제외할 내용에 걸려 뺀 보조 키워드: " + ", ".join(self.quotable(sub) for sub in dropped[:MAX_CHECK_WORDS]))
        # 값 적용 순서
        audience = self.pick("audience", user=options.audience, profile=self.profile_value("audience"), post_type=pt.AUDIENCES.get(post_type), default=DEFAULT_AUDIENCE)
        tone = self.pick("tone", profile=self.profile_value("tone"), default=DEFAULT_TONE)
        length = self.pick_length()
        pair = (profile.subheading_min, profile.subheading_max) if profile is not None else None
        low, high = self.pick("subheadings", profile=None if pair == DEFAULT_SUBHEADINGS else pair, default=DEFAULT_SUBHEADINGS)           # 프로필 값이 클래스 기본값이면 정하지 않은 것으로 본다(글 길이와 같은 규칙)
        title_limit = self.pick("title_limit", profile=self.profile_value("max_title_chars", unset=DEFAULT_TITLE_LIMIT), default=DEFAULT_TITLE_LIMIT)
        tag_limit = self.pick("tag_limit", profile=self.profile_value("max_tags", unset=DEFAULT_TAG_LIMIT), default=DEFAULT_TAG_LIMIT)
        paragraph = self.pick("paragraph", profile=self.profile_value("paragraph_max_chars", unset=DEFAULT_PARAGRAPH), default=DEFAULT_PARAGRAPH)
        intro_text = self.profile_value("intro_style")
        intro = self.pick("intro_style", profile=style_of(intro_text, INTRO_STYLES) if intro_text else None, default=DEFAULT_INTRO[voice])
        diff_text = self.profile_value("difficulty")
        difficulty = self.pick("difficulty", profile=style_of(diff_text, DIFFICULTY_STYLES) if diff_text else None, default=DEFAULT_DIFFICULTY)
        end_text = self.profile_value("ending_style")
        ending = self.pick("ending_style", profile=style_of(end_text, ENDING_STYLES) if end_text else None, default=DEFAULT_ENDING)
        if title_limit < MIN_TITLE_LIMIT:
            self.checks.append(f"이 블로그의 제목 길이 상한({title_limit}자)이 너무 짧아 {MIN_TITLE_LIMIT}자까지로 만들었습니다 — 프로필의 제목 길이 상한을 확인해 주세요.")
            title_limit = MIN_TITLE_LIMIT
        # 구조
        outline, subheadings, step_points = self.structure(post_type, keyword, intro, low, high)
        titles = self.titles(post_type, keyword, topic, title_limit)
        direction = self.direction(tone, intro, difficulty, ending, audience, length, paragraph)
        key_points = self.key_points(keyword, subs, step_points)
        cautions = self.cautions(post_type)
        category = self.category(keyword, topic, subs)
        tags = self.tags(post_type, keyword, subs, tag_limit)
        self.notes(post_type, keyword, topic, replaced is not None)
        if options.title_direction:
            self.sources["title_direction"] = LAYER_USER
        if options.conclusion:
            self.sources["conclusion"] = LAYER_USER
        intent = pt.INTENTS[post_type][voice]
        for item in ("intent", "outline", "titles", "cautions"):                    # 글 유형 틀이 정하는 것(단계 이름·순서, 검색 의도, 제목 문구, 틀의 주의사항)
            self.sources[item] = LAYER_TYPE
        for item in ("topic", "keyword", "sub_keywords"):                           # 후보(키워드 분석)가 주는 것
            self.sources[item] = LAYER_CANDIDATE
        return DraftPlan(self.blog, topic, keyword, subs, intent, audience, post_type, titles, direction, outline, subheadings, key_points, cautions, category, tags, self.today, options.urls,
                         tuple(self.checks), length, tuple(self.sources.items()), replaced)

    def pick_length(self):
        wish = self.options.length
        user = wish.to_range() if isinstance(wish, LengthWish) else None
        profile = None
        if self.profile is not None and (self.profile.min_chars, self.profile.max_chars) != _PROFILE_LENGTH_DEFAULT:
            profile = (self.profile.min_chars, self.profile.max_chars)
        chosen = self.pick("length", user=user, profile=profile, default=DEFAULT_LENGTH)
        if user is not None and self.profile is not None:
            limit_low, limit_high = self.profile.min_chars, self.profile.max_chars
            if chosen[0] < limit_low or (chosen[1] or chosen[0]) > limit_high:
                self.checks.append(f"원하는 글 길이({length_korean(chosen)})가 이 블로그 프로필의 글 길이 기준({length_korean((limit_low, limit_high))})을 벗어납니다 — 입력한 길이를 그대로 따랐고, 복사 패키지 점검에서 주의가 나올 수 있습니다.")
        return chosen

    # ---- 목차·소제목·핵심 내용 -------------------------------------------------------------------------------------------------
    def structure(self, post_type, keyword, intro, low, high):
        voice = self.voice
        steps = list(pt.template_steps(post_type, experience=self.experience))
        if intro == "purpose":
            steps.insert(0, pt.LEAD_STEP)
        kept = [step for step in steps if not self.excluder.hit(step.name)]
        dropped = [step.name for step in steps if self.excluder.hit(step.name)]
        if dropped:
            self.checks.append("제외할 내용에 걸려 목차에서 뺀 단계: " + ", ".join(dropped))
        if not kept:
            kept = [steps[0]]
            self.checks.append("제외할 내용 때문에 목차가 비어 첫 단계만 남겼습니다 — 제외할 내용을 확인해 주세요.")
        count = min(max(len(kept), low), high)
        if count > len(kept):
            extras = [step for step in pt.EXTRA_STEPS if not self.excluder.hit(step.name)][:count - len(kept)]
            closing = kept[-1:] if len(kept) > 1 else []                          # 마무리 단계가 따로 있으면 그 앞에, 단계가 하나뿐이면 그 뒤에 더한다
            kept = kept[:-1] + extras + closing if closing else kept + extras
            count = min(count, len(kept))
            if count < low:
                self.checks.append(f"소제목을 {count}개로 만들었습니다 — 이 블로그 프로필의 소제목 수({low}~{high}개)보다 적습니다.")
        sizes = group_sizes(len(kept), count, voice)
        outline, subheadings, position = [], [], 0
        for size in sizes:
            group = kept[position:position + size]
            position += size
            outline.append(" + ".join(step.name for step in group))
            subheadings.append(self.heading(group[0], keyword) if size == 1 else f"{keyword}: " + ", ".join(step.name for step in group))
        points = []
        for step in kept:
            text = self.variant(step.points, "")
            if text:
                points.append(text)
        return tuple(outline), tuple(subheadings), tuple(points)

    def usable(self, bare):
        """제목·소제목 문구의 틀(주제 낱말 `{kw}` 와 사용자 글 `{text}` 자리를 뺀 것)이 제외할 말·금지 표현에 걸리지 않는가 — 제목 후보가 모두 지나야 하는 관문."""
        return not self.excluder.hit(bare) and not _forbidden_hit(bare, self.forbidden)

    def variant(self, pair, subject):
        """말씨의 문구, 제외할 말이 걸리면 다른 말씨의 문구. 둘 다 걸리면 ''. (소제목의 `{kw}` 자리는 걸러 보지 않는다 — 주제 낱말은 막을 수 없다.)"""
        for voice in (self.voice, 1 - self.voice):
            text = pair[voice]
            if self.usable(text.replace("{kw}", "")):
                return _collapse(text.replace("{kw}", subject)) if subject else text
        return ""

    def heading(self, step, keyword):
        return self.variant(step.heads, keyword) or step.name

    # ---- 제목 ----------------------------------------------------------------------------------------------------------------
    def titles(self, post_type, keyword, topic, limit):
        options, voice = self.options, self.voice
        user, library = [], []                                                              # user: 사용자가 정한 방향·결론으로 만든 제목 · library: 틀의 제목 문구 — 둘 다 같은 관문(`usable`)을 지난다
        direction = squash(options.title_direction)
        if direction:
            templates = [pair[voice] for words, pair in DIRECTION_TITLES if any(word in direction for word in words)] or [VERBATIM_DIRECTION[voice]]
            user += [template.replace("{text}", options.title_direction).replace("{kw}", keyword) for template in templates if self.usable(template.replace("{kw}", "").replace("{text}", ""))]
        if options.conclusion and self.usable(CONCLUSION_TITLES[voice].replace("{kw}", "").replace("{text}", "")):
            user.append(CONCLUSION_TITLES[voice].replace("{text}", options.conclusion).replace("{kw}", keyword))
        own, other = pt.TITLES[post_type][voice], pt.TITLES[post_type][1 - voice]
        topic_pattern = [] if topic == keyword else [topic.replace("{", "").replace("}", "")]
        library += (topic_pattern + list(own) + list(other)) if voice == 0 else (list(own) + list(other) + topic_pattern)
        library += list(pt.SHORT_TITLES)
        found, seen = [], set()

        def add(text):
            key = squash(text)
            if text and len(text) <= limit and key not in seen and not claim_check.find_violations([text]):
                seen.add(key)
                found.append(text)

        for text in user:
            add(text)
        for pattern in library:
            if self.usable(pattern.replace("{kw}", "")):
                add(_collapse(pattern.replace("{kw}", keyword)))
        add(keyword)
        for trim in range(TITLE_COUNT * 3):                                                 # 제목 길이 상한이 아주 짧을 때 — 키워드를 줄여서라도 서로 다른 제목 셋을 만든다
            add(keyword[:max(limit - 1 - trim, 1)].rstrip() + "…")
        return tuple(found[:TITLE_COUNT])

    # ---- 본문 작성 방향 --------------------------------------------------------------------------------------------------------
    def direction(self, tone, intro, difficulty, ending, audience, length, paragraph):
        voice, options = self.voice, self.options
        notes = {}
        for name, table in (("intro_style", INTRO_STYLES), ("difficulty", DIFFICULTY_STYLES), ("ending_style", ENDING_STYLES)):      # 프로필의 안내 글을 규칙으로 읽지 못했으면 그 글을 그대로 덧붙인다(운영자가 쓴 안내를 버리지 않는다)
            text = self.profile_value(name)
            notes[name] = f" (프로필의 안내: {text})" if text and style_of(text, table) is None else ""
        lines = [("문체", _fill(TONE_LINES[voice], tone=tone) if self.sources["tone"] == LAYER_DEFAULT else tone + " — 블로그 프로필의 말투"),
                 ("도입부", INTRO_LINES[intro][voice] + notes["intro_style"]), ("설명 방식", DIFFICULTY_LINES[difficulty][voice] + notes["difficulty"]),
                 ("독자 관점", READER_LINES[voice].replace("{audience}", audience)), ("예시", EXAMPLE_LINES[voice]), ("마무리", ENDING_LINES[ending][voice] + notes["ending_style"]),
                 ("글 길이", _fill(LENGTH_LINES[voice], length=length_korean(length))), ("문단", PARAGRAPH_LINES[voice].replace("{size}", str(paragraph)))]
        if options.title_direction:
            lines.insert(0, ("제목 방향(입력)", options.title_direction))
        if options.conclusion:
            lines.append(("결론(입력)", options.conclusion))
        return tuple(lines)

    # ---- 포함할 핵심 내용·주의사항 ------------------------------------------------------------------------------------------------
    def key_points(self, keyword, subs, step_points):
        options, found = self.options, []
        if options.message:
            found.append(f"전하고 싶은 내용(입력): {options.message}")
        if options.experience:
            found.append(f"실제 경험(입력): {options.experience}")
        if options.opinion:
            found.append(f"개인 의견(입력): {options.opinion}")
        found += [f"반드시 넣을 문장(입력): {sentence}" for sentence in options.must_include]
        found += [f"가격·날짜(입력): {item}" for item in options.price_date]
        if options.conclusion:
            found.append(f"마무리에 넣을 결론(입력): {options.conclusion}")
        found.append(f"핵심 키워드 ‘{keyword}’ — 제목·첫 문단·소제목에 자연스럽게 넣고 억지로 반복하지 않습니다")
        if subs:
            found.append(f"보조 키워드({', '.join(subs)}) — 소제목과 본문에 나누어 씁니다")
        found += step_points
        months = self.candidate.seasonality
        if months:
            found.append("관심이 몰리는 달(" + "·".join(str(month) for month in months) + "월)에 맞춰 올리고 기준 날짜를 글에 적어 둡니다")
        return tuple(found)

    def cautions(self, post_type):
        found = [*GENERAL_CAUTIONS, *pt.CAUTIONS[post_type]]
        phrases = [phrase for phrase in self.forbidden if not claim_check.find_violations([phrase])][:MAX_CHECK_WORDS]
        if phrases:
            found.append("이 블로그의 금지 표현은 쓰지 않습니다: " + ", ".join(phrases))
        if self.options.exclude:
            shown = [word for word in self.options.exclude if not claim_check.find_violations([word])][:MAX_CHECK_WORDS]       # 경험을 단정하는 말이 든 제외어는 그대로 옮겨 적지 않는다
            rest = len(self.options.exclude) - len(shown)
            found.append("제외하기로 한 내용은 목차·소제목·핵심 내용에 넣지 않습니다" + (": " + ", ".join(shown) if shown else "") + (f"{' 외' if shown else ' — 모두'} {rest}개" if rest else ""))
        return tuple(found)

    # ---- 카테고리·태그 ------------------------------------------------------------------------------------------------------------
    def category(self, keyword, topic, subs):
        profile = self.profile
        if profile is None or not profile.categories:
            self.sources["category"] = LAYER_DEFAULT
            return ""
        plain = squash(" ".join((topic, keyword, *subs)))
        for source, target in profile.categories:
            if squash(source) in plain or squash(target) in plain:
                self.sources["category"] = LAYER_PROFILE
                return target
        if len(profile.categories) == 1:
            self.sources["category"] = LAYER_PROFILE
            return profile.categories[0][1]
        self.sources["category"] = LAYER_DEFAULT
        self.checks.append("프로필의 카테고리 매핑에서 어울리는 카테고리를 정하지 못했습니다 — 직접 골라 주세요.")
        return ""

    def tags(self, post_type, keyword, subs, limit):
        voice = self.voice
        head = _tag(keyword)
        tails = pt.TAG_TAILS[post_type][voice]
        combos = [_tag(head + tail) for tail in tails if head and not head.endswith(tail)]
        defaults = [_tag(tag) for tag in (self.profile.default_tags if self.profile is not None else ())]
        parts = [[head], [_tag(sub) for sub in subs], defaults, combos] if voice == 0 else [[head], combos, [_tag(sub) for sub in subs], defaults]
        subject = {squash(keyword), *(squash(sub) for sub in subs)}
        found, seen = [], set()
        for tag in (tag for part in parts for tag in part):
            key = squash(tag)
            from_subject = any(key.startswith(word) for word in subject if word)               # 후보의 낱말로 만든 태그
            hit = self.excluder.hit(tag.replace(head, "")) if from_subject and head else self.excluder.hit(tag)
            if not tag or key in seen or hit or _forbidden_hit(tag.replace(head, "") if from_subject and head else tag, self.forbidden) or self.safe(tag) != tag:
                continue
            seen.add(key)
            found.append(tag)
        final = found[:limit]
        profile_tags = {squash(tag) for tag in defaults if tag}
        self.sources["tags"] = LAYER_PROFILE if any(squash(tag) in profile_tags for tag in final) else LAYER_CANDIDATE      # 프로필 태그가 실제로 남았을 때만 프로필이 준 것이다
        return tuple(final)

    # ---- 확인 권장 -------------------------------------------------------------------------------------------------------------------
    def notes(self, post_type, keyword, topic, replaced):
        candidate, options, checks = self.candidate, self.options, self.checks
        if self.profile is None and self.blog in NAVER_KEYS:
            checks.append("이 네이버 블로그의 프로필이 아직 없어 공통 기본값으로 만들었습니다 — `naver-profile set` 으로 프로필을 정하면 그 값이 먼저 적용됩니다.")
        if self.blog == "blogger_en":
            checks.append("영문 블로그용 제목 틀은 아직 없어 한국어 틀로 만들었습니다 — 제목은 영어로 직접 고쳐 주세요.")
        if not self.experience and not replaced:
            if post_type == POST_TYPES[4]:
                checks.append("실제 방문 정보가 입력되지 않아 방문 후기 형식 없이 위치·이용 정보 중심으로 구성했습니다 — 직접 다녀왔다면 ‘실제 사용 경험’ 칸에 적어 주세요.")
            elif post_type == POST_TYPES[3]:
                checks.append("이 제품을 직접 이용해 본 경험이 있다면 ‘실제 사용 경험’ 칸에 적어 주세요 — 사용 경험 단락이 목차에 더해집니다(적지 않아도 계획은 만들어집니다).")
            else:
                checks.append("직접 겪은 경험이 있으면 ‘실제 사용 경험’ 칸에 적어 경험 단락을 더할 수 있습니다(입력하지 않아도 초안은 만들어집니다).")
        if options.price_date:
            checks.append("입력하신 가격·날짜는 그대로 넣었습니다 — 올리는 날에 값이 바뀌지 않았는지 한 번 더 살펴 주세요.")
        else:
            checks.append("가격·날짜 같은 수치는 계획에 넣지 않았습니다 — 필요하면 공식 자료에서 확인한 값만 직접 적고, 글을 올리는 날 한 번 더 맞는지 살펴 주세요.")
        if options.urls:
            checks.append("입력하신 참고 주소는 열어 보거나 가져오지 않고 그대로 적었습니다 — 내용은 직접 확인해 주세요.")
        else:
            checks.append("참고 자료를 입력하지 않았습니다 — 사실 관계는 공식·공개 자료로 확인한 뒤 주소를 적어 두면 좋습니다(앱은 자료를 자동으로 찾거나 열지 않습니다).")
        if not self.experience:
            for label, text in (("직접 전달하고 싶은 내용", options.message), ("개인 의견", options.opinion), ("반드시 포함할 문장", " ".join(options.must_include)), ("최종 결론", options.conclusion),
                                ("원하는 제목 방향", options.title_direction)):
                if text and claim_check.find_violations([text]):
                    checks.append(f"‘{label}’ 칸에 직접 겪은 일을 말하는 표현이 있습니다 — 실제 경험이면 ‘실제 사용 경험’ 칸에 적어 주세요(경험 단락이 들어갑니다).")
        hits = {}
        for what, text in (("핵심 키워드", candidate.keyword), ("주제", candidate.topic)):
            found = self.excluder.hit(text)
            if found:
                hits.setdefault(found, []).append(what)
        for (term, who), places in hits.items():
            where = "이 블로그 프로필의 제외 주제" if who == "profile" else "제외할 내용"
            checks.append(f"{where} 「{self.quotable(term)}」 이(가) 후보의 {'·'.join(places)}에 있습니다 — " + ("이 블로그에 맞는 후보인지 확인해 주세요." if who == "profile" else "제목에는 그대로 두었습니다."))
        for label, text in (("직접 전달하고 싶은 내용", options.message), ("개인 의견", options.opinion), ("실제 사용 경험", options.experience), ("최종 결론", options.conclusion), ("반드시 포함할 문장", " ".join(options.must_include))):
            found = self.excluder.hit(text) if text else None
            if found:
                checks.append(f"제외할 내용 「{self.quotable(found[0])}」 이(가) 입력하신 ‘{label}’ 에 들어 있습니다 — 입력하신 내용은 그대로 두었습니다.")
        if self.forbidden:
            for what, text in (("핵심 키워드", keyword), ("주제", topic)):
                hit = _forbidden_hit(text, self.forbidden)
                if hit:
                    checks.append(f"이 블로그의 금지 표현 「{self.quotable(hit)}」 이(가) 후보의 {what}에 있습니다 — 제목에 쓰기 전에 확인해 주세요.")
        if candidate.duplicate:
            checks.append("후보에 ‘기존 글과 겹칠 수 있음’ 으로 표시되어 있습니다 — 이미 쓴 글과 겹치지 않는지 확인해 주세요.")
        if candidate.data_date:
            age = (datetime.strptime(self.today, "%Y-%m-%d") - datetime.strptime(candidate.data_date, "%Y-%m-%d")).days
            if age > STALE_DAYS:
                checks.append(f"후보 지표의 조회일({candidate.data_date})이 {age}일 전입니다 — 최신 값인지 확인해 주세요.")


def _blog(candidate, profile, blog):
    if blog is None:
        blog = profile.key if profile is not None else candidate.blogs[0]
    if not isinstance(blog, str) or blog not in st.PLATFORMS:
        raise _invalid("블로그", "다음 중 하나여야 합니다: " + ", ".join(st.PLATFORMS))
    if profile is not None and profile.key != blog:
        raise _invalid("블로그", f"프로필({profile.key})과 대상 블로그({blog})가 다릅니다")
    return blog


def build_plan(candidate, profile, options=None, *, today, blog=None, post_type=None):
    """후보 하나·대상 블로그의 프로필(없으면 None)·(선택) 사용자 입력으로 작성 기반을 만든다 — 순수 함수(파일·네트워크·무작위 없음, 같은 입력은 같은 결과).
    `blog` 를 주지 않으면 프로필의 블로그, 프로필도 없으면 후보의 첫 추천 블로그다. `post_type` 은 사용자가 정한 글 유형(없으면 None). 사용자 입력이 비어 있어도 계획은 만들어진다.
    틀린 값(모르는 유형·블로그·날짜)은 DRAFT_OPTION_INVALID."""
    if not isinstance(candidate, Candidate):
        raise AppError("CONTENT_INVALID", {"항목": "주제 후보"}, detail="Candidate 가 아니다")
    if profile is not None and not isinstance(profile, NaverProfile):
        raise AppError("CONTENT_INVALID", {"항목": "블로그 프로필"}, detail="NaverProfile 이 아니다")
    if options is not None and not isinstance(options, DraftOptions):
        raise AppError("CONTENT_INVALID", {"항목": "선택 입력"}, detail="DraftOptions 가 아니다")
    if post_type is not None and post_type != "" and (not isinstance(post_type, str) or post_type not in POST_TYPES):
        raise _invalid("글 유형", "다음 중 하나여야 합니다: " + ", ".join(POST_TYPES))
    return _Planner(candidate, profile, options or DraftOptions(), _day(today), _blog(candidate, profile, blog), post_type or None).build()


# ---- 두 블로그의 계획 견주기 ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanComparison:
    report: object                  # similarity.SimilarityReport
    warnings: tuple                 # 너무 비슷할 때의 한국어 경고(비슷하지 않으면 빈 튜플)

    @property
    def level(self):
        return self.report.level


def compare_plans(first, second, thresholds=None):
    """같은 후보로 만든 두 계획(`DraftPlan`)의 제목·도입 방향·소제목·핵심 내용·태그가 얼마나 비슷한지 `check/similarity.py` 로 잰다. 경고 단계 이상이면 한국어 경고를 담는다."""
    for plan in (first, second):
        if not isinstance(plan, DraftPlan):
            raise AppError("CONTENT_INVALID", {"항목": "비교할 작성 기반"})
    def comparable(plan):
        tags = tuple(tag for tag in (plan.frame(tag) for tag in plan.tags) if tag)                    # 키워드 태그는 두 블로그가 같은 것이 당연하니 뺀다
        title = " ".join(plan.frame(text) for text in plan.titles) or plan.titles[0]                   # 제목 셋을 모두 본다(하나만 같아도 다른 둘이 다르면 전체로는 다르다)
        return similarity.Comparable(title=title, body=plan.comparable_body(), tags=tags, images=(), date="", intro=plan.frame(plan.intro_text()))

    report = similarity.compare(comparable(first), comparable(second), thresholds or similarity.Thresholds())
    warnings = ()
    if report.level != "ok":
        warnings = (f"두 블로그의 작성 기반이 많이 비슷합니다(전체 {report.overall:.0%}) — 제목·목차·소제목을 서로 다르게 고쳐 주세요.", *report.reasons)
    return PlanComparison(report, warnings)


__all__ = [
    "DEFAULT_AUDIENCE", "DEFAULT_LENGTH", "DEFAULT_TONE", "DraftPlan", "LAYERS", "LAYER_KO", "PlanComparison", "apply_priority", "build_plan", "compare_plans", "group_sizes", "length_korean", "style_of",
]
