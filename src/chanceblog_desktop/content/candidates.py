"""주제 후보 — 키워드와 포스팅 주제를 후보로 모아 '검토 → 선택 → (초안)' 으로 나르는 자료(docs/ARCHITECTURE.md §9). 저장(SQLite)은 `store.py` 이고, 여기서는 자료의 모양·검증·상태 이동만 한다.
후보를 모으는 일(네이버 자료 수집·키워드 기회도 계산)과 초안 문장 만들기는 이 모듈의 일이 아니다 — 여기에는 그 결과를 담을 자리만 있다.

규칙: ① 지표(검색 수요·관련 블로그 검색 결과 수·최근 추세·모바일 비중·계절성·기존 글 중복 여부·적합도·우선도·기회도)는 모두 선택이다 — 없으면 비워 둔다('데이터 없음').
  다만 값이 하나라도 있으면 그 값을 조회한 날(`data_date`)도 있어야 한다(언제 것인지 모르는 수치를 두지 않는다).
② 결과를 부풀리는 표현(상위노출 보장·노출 확률·검색 1위 가능성·수익 보장 같은 것)은 주제·키워드·추천 이유 어디에도 쓸 수 없고, 지표는 `LABELS` 의 이름으로만 부른다.
③ 상태는 새 후보·검토 중·선택됨·보류·제외 다섯이고 `TRANSITIONS` 에 있는 이동만 한다. 초안 이후(작성 중·완료·복사·발행)는 새 상태를 만들지 않고 글(프로젝트)의 네이버 흐름 상태에 대응시킨다(`FOLLOW_ON`).
④ 후보는 바꿀 수 없는 값이다. 바꾸려면 `edited`·`moved` 로 새 후보를 만들어 저장한다(그때마다 판 번호 `revision` 이 오르고, 낮은 판으로는 덮어쓰지 못한다).
⑤ '선택'은 블로그마다 따로 기록한다(`selections`) — 같은 주제를 두 블로그에서 쓸 수 있고, 같은 블로그에서 다시 쓰는 것만 경고하려면 어느 블로그용으로 언제 골랐는지 알아야 한다.
모든 검증 실패는 AppError 로 낸다 — 칸 값이 틀렸으면 `CANDIDATE_INVALID`(사용자가 읽는 문구에 어느 칸이 왜 안 되는지 담긴다). 말은 모두 한 줄로 정리돼 있어야 하고(제어·보이지 않는 글자·겹친 공백이 있으면
고쳐 받지 않고 거절), 위험한 HTML 태그·이벤트 속성·스크립트 주소·템플릿(Liquid) 표기는 걸러진다(`profiles.find_markup` — `Map<String, List<Integer>>`·`JavaScript: 비동기` 같은 글은 지나간다).
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, replace
from datetime import datetime

from ..errors import AppError
from . import status as st
from .model import utc_now
from .profiles import DEFAULT_POST_TYPE, MAX_PHRASE, POST_TYPES, clean_line, find_markup

SCHEMA = 1
MAX_TOPIC = 200
MAX_KEYWORD = MAX_PHRASE
MAX_SUB_KEYWORDS = 20
MAX_REASON = 300
MAX_SEARCH_DEMAND = 1_000_000_000
MAX_RELATED_RESULTS = 10_000_000_000
MAX_REVISION = 1_000_000_000               # 판 번호의 상한(저장소의 정수 범위를 넘어 뜻밖의 오류가 나기 전에 알린다)
SHORT_ID = 8                               # 화면에 보일 후보 번호의 길이(32자 번호는 앞 8자만)
MIN_YEAR = 2000
STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DAY_FORMAT = "%Y-%m-%d"
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# 서식 문자(Cf)가 아니라서 `clean_line` 이 못 지우지만 화면에는 빈칸이나 깨진 글자로 보이는 글자: 한글 채움 문자·점자 빈칸·몽골 변형 선택자(U+180B~180F)·이모지 변형 선택자(U+FE00~FE0F)·
# 개체 대체 문자(U+FFFC)·깨진 글자 표시(U+FFFD)
_BLANK_LOOKALIKES = re.compile("[\u034f\u115f\u1160\u17b4\u17b5\u180b-\u180f\u2800\u3164\ufe00-\ufe0f\uffa0\ufffc\ufffd]")
# 결합 문자가 겹겹이 쌓이거나(3개 이상) 글머리·공백 바로 뒤에 홀로 붙은 것(글자를 가리거나 이웃 글자를 깨뜨린다)
_STACKED_MARKS = re.compile("[\u0300-\u036f]{3,}|(?:^|\\s)[\u0300-\u036f]")

# ---- 상태 -----------------------------------------------------------------------------------------------------------------
NEW, REVIEW, SELECTED, HOLD, REJECTED = "NEW", "REVIEW", "SELECTED", "HOLD", "REJECTED"
STATUSES = (NEW, REVIEW, SELECTED, HOLD, REJECTED)
# 갈 수 있는 다음 상태(문서 §9 의 표와 같고 시험이 확인한다). 제외한 후보는 '검토 중' 으로만 되살릴 수 있고, 새 후보로는 돌아가지 않는다.
TRANSITIONS = {
    NEW: (REVIEW, SELECTED, HOLD, REJECTED),
    REVIEW: (SELECTED, HOLD, REJECTED),
    HOLD: (REVIEW, SELECTED, REJECTED),
    REJECTED: (REVIEW,),
    SELECTED: (HOLD, REVIEW),
}
STATUS_KO = {NEW: "새 후보", REVIEW: "검토 중", SELECTED: "선택됨", HOLD: "보류", REJECTED: "제외"}
# 초안 이후의 상태는 후보 표에 새로 만들지 않는다 — 글(프로젝트)의 네이버 흐름(`content/status.py`) 상태가 곧 그 상태다(왼쪽: 요구서의 이름, 오른쪽: 기존 흐름의 상태).
# 사람이 읽고 승인하는 단계(REVIEW_REQUIRED)와 실패(PUBLISH_FAILED)는 대응시키지 않는다.
FOLLOW_ON = {"DRAFTING": st.DRAFT_GENERATED, "DRAFT_READY": st.READY_TO_COPY, "COPIED": st.COPY_COMPLETED, "PUBLISHED": st.PUBLISHED_MANUAL}
FOLLOW_ON_KO = {"DRAFTING": "초안 작성 중", "DRAFT_READY": "초안 완료", "COPIED": "복사 완료", "PUBLISHED": "발행 완료"}

# ---- 지표와 이름 ---------------------------------------------------------------------------------------------------------------
TRENDS = ("상승", "보합", "하락")
METRIC_FIELDS = ("search_demand", "related_blog_results", "trend", "mobile_share", "seasonality", "duplicate", "profile_fit", "priority", "keyword_opportunity")
# 화면에 보일 이름. 지표는 허용된 표현으로만 부른다(ALLOWED_TERMS) — 순위·노출·수익을 약속하는 말은 쓰지 않는다.
LABELS = {
    "candidate_id": "후보 번호", "topic": "추천 포스팅 주제", "keyword": "핵심 키워드", "sub_keywords": "보조 키워드", "blogs": "추천 대상 블로그", "post_type": "추천 글 유형",
    "search_demand": "월간 검색 수요", "related_blog_results": "관련 블로그 검색 결과 수", "trend": "최근 관심도 변화", "mobile_share": "모바일 비중", "seasonality": "계절성",
    "duplicate": "기존 글 중복 여부", "profile_fit": "블로그 프로필 적합도", "priority": "콘텐츠 작성 우선도", "keyword_opportunity": "키워드 기회도",
    "reason": "추천 이유", "data_date": "데이터 조회일", "status": "상태",
}
ALLOWED_TERMS = ("키워드 기회도", "콘텐츠 작성 우선도", "블로그 프로필 적합도", "최근 관심도 변화", "관련 블로그 검색 결과 수")

# ---- 쓸 수 없는 표현(결과를 약속하는 말) -------------------------------------------------------------------------------------------
# 글을 '글자·숫자만' 남긴 모양으로 바꿔서 찾는다 — 띄어쓰기·구두점·전각 글자·보이지 않는 글자·한글 자모 분해(NFD)·한자(上位露出保障 …)를 바꿔 끼워도 같은 말로 본다.
# 규칙은 낱말이 **바로 이어질 때**(사이에 조사·숫자(100%)만 낄 수 있다) 걸린다 — 먼 낱말끼리 짝지으면 '보험 수익자 지정과 보장 범위' 같은 보통 글이 걸린다.
# 걸리더라도 ① 뒤에 부정이 이어지거나('보장하지 않습니다'·'보장할 수 없다'·'보장은 불가능') ② 그런 약속을 경계하는 글('상위노출 보장 업체 피하는 법')이면 약속이 아니라서 지나간다.
_HANJA = str.maketrans({"上": "상", "位": "위", "露": "노", "出": "출", "保": "보", "障": "장", "確": "확", "率": "률", "可": "가", "能": "능", "性": "성", "收": "수", "益": "익", "證": "증",
                        "約": "약", "束": "속", "定": "정"})
_PARTICLE = r"(?:을|를|이|가|은|는|도|만|으로|로|의)?"                    # 낱말 사이에 끼는 조사 하나
_NUMBER = r"(?:[0-9]{1,3}(?:퍼센트|프로)?)?"                              # '100%' 는 글자·숫자만 남기면 100
_PROMISE = r"(?:보장|보증|확약|약속|장담|guarantee[ds]?)"
_SURE = rf"(?:{_PROMISE}|확정|책임)"                                      # 확정·책임은 '순위 확정'(경기)처럼 다른 뜻이 흔해 상위노출류(`_TOP`)에만 붙인다 — 나머지 낱말은 `_PROMISE` 하나가 두 규칙에 쓰인다
_TOP = r"(?:상위|검색)노출|첫페이지노출|1페이지노출|메인노출|상단노출|최상단노출|검색순위|상위순위|상위랭킹|상위권노출"
_ANY = r"(?:상위|검색)?(?:노출|순위|랭킹|랭크)|첫페이지|1페이지|일페이지|첫화면|최상단|최상위"
_ONE = r"(?:검색)?(?:1위|1등|일위|일등)"
_CLAIMS = (
    ("상위노출 보장", re.compile(rf"(?:{_TOP}){_PARTICLE}{_NUMBER}{_PARTICLE}{_SURE}")),
    ("노출·순위 보장", re.compile(rf"(?:{_ANY}){_PARTICLE}{_NUMBER}{_PARTICLE}{_PROMISE}")),
    ("노출 확률·가능성", re.compile(r"(?:상위|검색|블로그|포털|네이버|구글|첫페이지|메인|상단)노출(?:이|을|될|되는|할|하는|의)?(?:가능성|확률|가능)|노출(?:이|을|될|되는|할|하는|의)?확률")),
    ("검색 1위 보장·가능성", re.compile(rf"{_ONE}{_PARTICLE}{_NUMBER}{_PARTICLE}(?:{_SURE}|달성|가능성|가능|확률)")),
    ("수익 보장", re.compile(rf"수익(?:률|창출)?{_PARTICLE}{_NUMBER}{_PARTICLE}(?:{_PROMISE}|확정)")),
    ("상위노출 보장", re.compile(r"(?:보장|보증)(?:된|하는|형)?(?:상위노출|검색1위)|(?<![0-9])(?:100|백)(?:퍼센트|프로)?(?:상위노출|검색1위)|(?:무조건|반드시|확실한|확실히)(?:적으로)?(?:상위노출|검색1위|1위)")),
)
# 걸린 말 바로 뒤가 부정이면 '약속하지 않는다' 는 말이다
_NEGATION = re.compile(r"(?:은|는|이|가|도|을|를)?(?:하?지(?:는|도|를)?않|되지(?:는|도)?않|할수(?:는|가)?없|못|불가|안(?:합|함|해|하|돼|됩|되|된)|없|어렵|아닙|아니)")
# 약속을 하는 글이 아니라 그런 약속을 경계하는 글이라는 표지
_WARNING = re.compile(r"피하|피해|속지|속는|속아|속이|사기(?!업)|허위|과장|함정|조심|주의(?:사항|하|할|해|점)|위험성|믿어도|믿을수|낚시|거짓말")

# 영어(github_pages·blogger_en 용 후보) — 낱말 단위로 본다: 보장하는 말(guarantee)이 순위·노출·첫 쪽·수익 말 가까이(앞뒤 4낱말)에 있으면 걸리고, 순위·노출 뒤의 확률(probability·chance)도 걸린다.
_EN_GUARANTEE = frozenset({"guarantee", "guaranteed", "guarantees", "guaranteeing"})
_EN_RANKING = frozenset({"rank", "ranks", "ranked", "ranking", "rankings", "serp", "exposure", "traffic"})
_EN_INCOME = frozenset({"income", "profit", "profits", "earnings", "revenue"})
_EN_CHANCE = frozenset({"probability", "chance", "chances", "likelihood", "odds"})
_EN_NEGATIVE = frozenset({"not", "no", "never", "cannot", "without", "nobody", "nor", "neither", "impossible", "t"})
_EN_BOUNDARY = frozenset({".", ";", "!", "?", "but", "however", "yet", "although", "though"})
_EN_WARNING = frozenset({"myth", "myths", "scam", "scams", "avoid", "beware", "fake", "fraud", "misleading", "lie", "lies", "flag", "flags"})
_EN_TOP_PAIRS = frozenset({("first", "page"), ("page", "one"), ("page", "1"), ("number", "one"), ("no", "1"), ("top", "1"), ("1", "spot"), ("1", "position"), ("1", "result"), ("1", "results"),
                           ("one", "spot"), ("top", "spot"), ("top", "result"), ("top", "results"), ("top", "position"), ("top", "3"), ("top", "5"), ("top", "10"), ("top", "ten")})


def _flat(text):
    """띄어쓰기·구두점을 지우고(글자·숫자만) 호환 문자를 풀고(NFKC) 소문자로 하고 한자를 한글로 바꾼 글 — 표현 검사용."""
    text = unicodedata.normalize("NFKC", str(text).replace("Ⅰ", "1").replace("ⅰ", "1")).casefold().translate(_HANJA)
    return "".join(ch for ch in text if ch.isalnum())


def _korean_claim(text):
    plain = _flat(text)
    if _WARNING.search(plain):
        return None
    for label, rule in _CLAIMS:
        for found in rule.finditer(plain):
            if not _NEGATION.match(plain, found.end()):
                return label, found.group(0)
    return None


def _english_clause(words):
    spans = [(index, index + 1) for index, word in enumerate(words) if word in _EN_RANKING]                              # 순위·노출을 가리키는 말
    spans += [(index, index + 2) for index in range(len(words) - 1) if (words[index], words[index + 1]) in _EN_TOP_PAIRS]  # 첫 쪽·1위를 가리키는 말
    income = [(index, index + 1) for index, word in enumerate(words) if word in _EN_INCOME]
    for guarantee in (index for index, word in enumerate(words) if word in _EN_GUARANTEE):
        near = range(max(0, guarantee - 3), min(len(words), guarantee + 4))
        if any(words[i] in _EN_NEGATIVE and not (words[i] == "no" and words[i + 1:i + 2] in (["1"], ["one"])) for i in near if i != guarantee):
            continue                                                                                                      # 'not guaranteed'·'no guarantee' — 약속하지 않는다는 말
        for start, end in spans + income:
            if start >= guarantee - 4 and end <= guarantee + 5:
                return "순위·수익 보장", " ".join(words[min(start, guarantee):max(end, guarantee + 1)])
    for index, word in enumerate(words):
        if word in _EN_CHANCE and any(end <= index and index - end <= 2 for start, end in spans) and not any(words[i] in _EN_NEGATIVE for i in range(max(0, index - 4), index)):
            return "노출·순위 확률", " ".join(words[max(0, index - 3):index + 1])
    return None


def _english_claim(text):
    """영어 — 문장 끝(. ; ! ?)과 but·however 같은 낱말에서 절을 나누어 절마다 본다(앞 절의 'not guaranteed' 가 뒤 절의 'guaranteed income' 을 가리지 않는다)."""
    words = re.findall(r"[a-z0-9]+|[;!?]|\.(?=\s|$)", unicodedata.normalize("NFKC", str(text)).casefold())      # 'No.1' 의 점은 문장 끝이 아니다
    if not words or _EN_WARNING.intersection(words):
        return None
    clause = []
    for word in words + ["."]:
        if word in _EN_BOUNDARY:
            found = _english_clause(clause)
            if found:
                return found
            clause = []
        else:
            clause.append(word)
    return None


def forbidden_claim(text):
    """결과를 부풀리는 표현(상위노출 보장·노출 확률·검색 1위 가능성·수익 보장 같은 것, 영어 'guaranteed #1 ranking' 도)이 있으면 (사용자에게 보일 이름, 걸린 말), 없으면 None."""
    return _korean_claim(text) or _english_claim(text)


def find_forbidden_claim(text):
    """`forbidden_claim` 이 찾은 표현(한국어는 띄어쓰기를 지운 모양)을, 없으면 None."""
    claim = forbidden_claim(text)
    return claim[1] if claim else None


def keyword_key(text):
    """같은 키워드인지 비교하는 열쇠 — 호환 문자를 풀고(NFKC) 대소문자를 없애고 글자·숫자만 남기되, 뜻이 달라지는 기호는 남긴다: `+`·`#`(C++ ≠ C# ≠ C)와 숫자 사이의 소수점
    (1.5 ≠ 15·v1.2 ≠ v12). 그 밖의 띄어쓰기·기호 차이는 같은 키워드다(`보일러-점검` = `보일러 점검`·`1,000` = `1000`·`A.I.` = `AI`). 글자나 숫자가 하나도 없으면 빈 글."""
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    kept = []
    for index, ch in enumerate(normalized):
        if ch.isalnum() or ch in "+#":
            kept.append(ch)
        elif ch == "." and 0 < index < len(normalized) - 1 and normalized[index - 1].isdigit() and normalized[index + 1].isdigit():
            kept.append(ch)
    key = "".join(kept)
    return key if any(ch.isalnum() for ch in key) else ""


def can_transition(current, requested):
    return requested in TRANSITIONS.get(current, ())


def next_statuses(status):
    return TRANSITIONS.get(status, ())


def status_name(status):
    """화면에 보일 한국어 이름. 후보 상태(NEW …)와 요구서의 초안 이후 상태(DRAFTING …), 그에 대응하는 네이버 흐름 상태(DRAFT_GENERATED …)를 받는다. 모르는 값은 CANDIDATE_INVALID."""
    if isinstance(status, str):
        if status in STATUS_KO:
            return STATUS_KO[status]
        if status in FOLLOW_ON_KO:
            return FOLLOW_ON_KO[status]
        for name, flow_status in FOLLOW_ON.items():
            if flow_status == status:
                return FOLLOW_ON_KO[name]
    raise _invalid("상태", "아는 상태가 아닙니다", detail=f"모르는 상태: {str(status)[:40]}")


# ---- 값 검사 --------------------------------------------------------------------------------------------------------------
def _invalid(item, reason="", *, detail=""):
    """주제 후보의 칸 값이 틀렸을 때의 오류 — 사용자가 읽는 문구에 어느 칸(`item`)이 왜(`reason`) 안 되는지가 담긴다. `detail` 은 개발자용 메모."""
    return AppError("CANDIDATE_INVALID", {"항목": item, "이유": reason or "올바른 값이 아닙니다"}, detail=detail or reason)


def short_id(candidate_id):
    """화면에 보일 후보 번호 — 32자 번호는 앞 8자만 보인다(짧은 번호는 그대로). 사람이 못 읽는 긴 번호를 문구에 그대로 싣지 않으려는 것이다."""
    text = str(candidate_id)
    return text if len(text) <= SHORT_ID else text[:SHORT_ID]


def parse_stamp(value, item="시각"):
    """`2026-11-02T03:04:05Z` 모양이고 달력에 있는 시각만(2000년 이후). 아니면 CANDIDATE_INVALID. 시각(datetime, 협정세계시)을 돌려준다."""
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise _invalid(item, "2026-11-02T03:04:05Z 같은 모양이어야 합니다", detail="YYYY-MM-DDTHH:MM:SSZ 모양이어야 한다")
    try:
        moment = datetime.strptime(value, STAMP_FORMAT)
    except ValueError:
        raise _invalid(item, "달력에 없는 시각입니다", detail="달력에 없는 시각") from None
    if moment.year < MIN_YEAR:
        raise _invalid(item, f"{MIN_YEAR}년 이후여야 합니다", detail=f"{MIN_YEAR}년 이전")
    return moment


def _day(value, item):
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        raise _invalid(item, "2026-11-02 같은 모양이어야 합니다", detail="YYYY-MM-DD 모양이어야 한다")
    try:
        day = datetime.strptime(value, DAY_FORMAT)
    except ValueError:
        raise _invalid(item, "달력에 없는 날짜입니다", detail="달력에 없는 날짜") from None
    if day.year < MIN_YEAR:
        raise _invalid(item, f"{MIN_YEAR}년 이후여야 합니다", detail=f"{MIN_YEAR}년 이전")
    return value


def _length_words(low, high):
    if low == 0:
        return f"{high}자 이하여야 합니다"
    return f"비워 둘 수 없고 {high}자 이하여야 합니다" if low == 1 else f"{low}~{high}자여야 합니다"


def _one_line(value, item, *, low, high):
    """앞뒤 공백만 있는 것은 정리하고, 줄바꿈·탭·겹친 공백·제어·보이지 않는 글자가 있으면 고쳐 받지 않고 거절한다(프로필과 같은 규칙)."""
    if not isinstance(value, str):
        raise _invalid(item, "글이어야 합니다")
    text = clean_line(value)
    if text != value.strip():
        raise _invalid(item, "줄바꿈·탭·겹친 공백·눈에 안 보이는 글자 없이 한 줄이어야 합니다")
    if not low <= len(text) <= high:
        raise _invalid(item, _length_words(low, high))
    return text


def _line(value, item, *, low=0, high):
    """한 줄 글 + 눈에 안 보이거나 쌓인 글자·위험한 HTML·스크립트·템플릿 표기·결과를 약속하는 표현 거절."""
    text = _one_line(value, item, low=low, high=high)
    if _BLANK_LOOKALIKES.search(text):
        raise _invalid(item, "눈에 보이지 않거나 빈칸·깨진 글자처럼 보이는 글자가 들어 있습니다")
    if _STACKED_MARKS.search(text):
        raise _invalid(item, "겹쳐 쌓였거나 홀로 붙은 결합 문자가 들어 있습니다")
    markup = find_markup(text)
    if markup:
        raise _invalid(item, markup)
    claim = forbidden_claim(text)
    if claim:
        label, matched = claim
        raise _invalid(item, f"‘{label}’ 같은 결과를 약속하는 표현은 쓸 수 없습니다", detail=f"쓸 수 없는 표현: {matched}")
    return text


def _keyword(value, item):
    text = _line(value, item, low=1, high=MAX_KEYWORD)
    if not keyword_key(text):
        raise _invalid(item, "글자나 숫자가 하나도 없습니다")
    return text


def _lines(values, item, *, count):
    """list·tuple 만 받는다(dict·set 은 순서가 정해지지 않아 거절) — 각 낱말은 `_keyword` 가 따로 검사한다."""
    if not isinstance(values, (list, tuple)):
        raise _invalid(item, "목록(여러 개)이어야 합니다", detail=f"{type(values).__name__} 은 받지 않는다")
    if len(values) > count:
        raise _invalid(item, f"{count}개까지 쓸 수 있습니다")
    return tuple(values)


def _count(value, item, high):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= high:
        raise _invalid(item, f"0~{high:,} 사이의 정수여야 합니다", detail=f"0~{high} 사이의 정수여야 한다")
    return value


def _score(value, item):
    """0~100 사이의 수(정수나 소수). 문자·참거짓·무한대·NaN 은 거절."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:      # NaN·무한대는 이 비교에서 걸러진다
        raise _invalid(item, "0~100 사이의 수여야 합니다", detail="0~100 사이의 수여야 한다")
    return value


def _blogs(values):
    item = LABELS["blogs"]
    if not isinstance(values, (list, tuple)):
        raise _invalid(item, "목록(여러 개)이어야 합니다", detail=f"{type(values).__name__} 은 받지 않는다")
    blogs = tuple(values)
    if not 1 <= len(blogs) <= len(st.PLATFORMS) or not all(isinstance(blog, str) and blog in st.PLATFORMS for blog in blogs) or len(set(blogs)) != len(blogs):
        raise _invalid(item, "하나 이상, 겹치지 않게, 다음 중에서 골라야 합니다: " + ", ".join(st.PLATFORMS))
    return blogs


def _months(values):
    item = LABELS["seasonality"]
    if values is None:
        return None
    if isinstance(values, (str, bytes, dict)) or not hasattr(values, "__iter__"):
        raise _invalid(item, "달(1~12)의 목록이어야 합니다")
    months = tuple(values)
    if not 1 <= len(months) <= 12 or not all(isinstance(month, int) and not isinstance(month, bool) and 1 <= month <= 12 for month in months) or len(set(months)) != len(months):
        raise _invalid(item, "1~12 사이의 달을 겹치지 않게 하나 이상 골라야 합니다")
    return tuple(sorted(months))


def _selections(value):
    item = "선택 기록"
    pairs = tuple(value.items()) if isinstance(value, dict) else value
    if isinstance(pairs, (str, bytes)) or not hasattr(pairs, "__iter__"):
        raise _invalid(item, "(블로그, 선택한 시각) 쌍의 목록이어야 합니다")
    found = {}
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise _invalid(item, "(블로그, 선택한 시각) 쌍이어야 합니다")
        blog, stamp = pair
        if not isinstance(blog, str) or blog not in st.PLATFORMS or blog in found:
            raise _invalid(item, "블로그 구분이 올바르지 않거나 겹칩니다", detail="블로그 구분이 올바르지 않거나 겹친다")
        parse_stamp(stamp, "선택 시각")
        found[blog] = stamp
    return tuple((blog, found[blog]) for blog in st.PLATFORMS if blog in found)


_KEYS = ("schema", "candidate_id", "topic", "keyword", "sub_keywords", "blogs", "post_type", *METRIC_FIELDS, "reason", "data_date", "status", "selections", "project_id",
         "revision", "created_at", "updated_at")
_REQUIRED = frozenset({"schema", "candidate_id", "topic", "keyword", "blogs", "status", "revision", "created_at", "updated_at"})
_FIXED = frozenset({"candidate_id", "status", "selections", "revision", "created_at", "updated_at"})      # edited 로는 바꿀 수 없는 칸


@dataclass(frozen=True)
class Candidate:
    candidate_id: str                          # 후보 번호([A-Za-z0-9_-] 1~64자)
    topic: str                                 # 추천 포스팅 주제
    keyword: str                               # 핵심 키워드
    blogs: tuple                               # 추천 대상 블로그(github_pages·blogger_en·blogger_ko·naver_a·naver_b 중 하나 이상 — list·tuple 만)
    sub_keywords: tuple = ()                   # 보조 키워드(list·tuple 만)
    post_type: str = DEFAULT_POST_TYPE         # 추천 글 유형(POST_TYPES 중 하나)
    # ---- 지표(모두 선택 — None 이면 '데이터 없음') ----
    search_demand: int | None = None           # 월간 검색 수요(회)
    related_blog_results: int | None = None    # 관련 블로그 검색 결과 수(건)
    trend: str | None = None                   # 최근 관심도 변화: 상승·보합·하락
    mobile_share: float | None = None          # 모바일 비중(%)
    seasonality: tuple | None = None           # 계절성: 관심이 몰리는 달(1~12)
    duplicate: bool | None = None              # 기존 글 중복 여부
    profile_fit: float | None = None           # 블로그 프로필 적합도(0~100)
    priority: float | None = None              # 콘텐츠 작성 우선도(0~100)
    keyword_opportunity: float | None = None   # 키워드 기회도(0~100) — 계산은 이 모듈의 일이 아니다
    reason: str = ""                           # 추천 이유(한 줄)
    data_date: str | None = None               # 데이터 조회일(YYYY-MM-DD) — 지표가 하나라도 있으면 있어야 한다
    # ---- 진행 ----
    status: str = NEW
    selections: tuple = ()                     # ((블로그, 선택한 시각), …) — 블로그마다 따로 고른 기록(플랫폼 순서)
    project_id: str | None = None              # 연결된 글(프로젝트) 번호
    revision: int = 1                          # 판 번호 — 바뀔 때마다 오른다(1~MAX_REVISION)
    created_at: str = ""
    updated_at: str = ""                       # 만든 시각보다 앞설 수 없다

    def __post_init__(self):
        self._validate()

    def _validate(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        if not isinstance(self.candidate_id, str) or not _ID.fullmatch(self.candidate_id):
            raise _invalid(LABELS["candidate_id"], "영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 합니다")
        put("topic", _line(self.topic, LABELS["topic"], low=1, high=MAX_TOPIC))
        put("keyword", _keyword(self.keyword, LABELS["keyword"]))
        subs, seen = [], {keyword_key(self.keyword)}
        for word in _lines(self.sub_keywords, LABELS["sub_keywords"], count=MAX_SUB_KEYWORDS):
            text = _keyword(word, LABELS["sub_keywords"])
            key = keyword_key(text)
            if key in seen:
                raise _invalid(LABELS["sub_keywords"], f"‘{text}’ 이(가) 핵심 키워드나 다른 보조 키워드와 같습니다", detail="핵심 키워드나 다른 보조 키워드와 같다")
            seen.add(key)
            subs.append(text)
        put("sub_keywords", tuple(subs))
        put("blogs", _blogs(self.blogs))
        if not isinstance(self.post_type, str) or self.post_type not in POST_TYPES:
            raise _invalid(LABELS["post_type"], "다음 중 하나여야 합니다: " + ", ".join(POST_TYPES))
        _count(self.search_demand, LABELS["search_demand"], MAX_SEARCH_DEMAND)
        _count(self.related_blog_results, LABELS["related_blog_results"], MAX_RELATED_RESULTS)
        if self.trend is not None and (not isinstance(self.trend, str) or self.trend not in TRENDS):
            raise _invalid(LABELS["trend"], "다음 중 하나여야 합니다: " + ", ".join(TRENDS))
        _score(self.mobile_share, LABELS["mobile_share"])
        put("seasonality", _months(self.seasonality))
        if self.duplicate is not None and not isinstance(self.duplicate, bool):
            raise _invalid(LABELS["duplicate"], "예·아니오 중 하나이거나 비워 두어야 합니다")
        for name in ("profile_fit", "priority", "keyword_opportunity"):
            _score(getattr(self, name), LABELS[name])
        put("reason", _line(self.reason, LABELS["reason"], high=MAX_REASON))
        if self.data_date is not None:
            _day(self.data_date, LABELS["data_date"])
        elif any(getattr(self, name) is not None for name in METRIC_FIELDS):
            raise _invalid(LABELS["data_date"], "지표 값이 있으면 조회일도 있어야 합니다")
        if not isinstance(self.status, str) or self.status not in STATUSES:
            raise _invalid(LABELS["status"], "다음 중 하나여야 합니다: " + ", ".join(STATUS_KO[state] for state in STATUSES), detail="상태: " + ", ".join(STATUSES))
        put("selections", _selections(self.selections))
        if self.status == NEW and self.selections:
            raise _invalid("선택 기록", "아직 고르지 않은 새 후보에는 선택 기록이 있을 수 없습니다")
        if self.project_id is not None and (not isinstance(self.project_id, str) or not _ID.fullmatch(self.project_id)):
            raise _invalid("연결한 글 번호", "영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 합니다")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or not 1 <= self.revision <= MAX_REVISION:
            raise _invalid("판 번호", f"1~{MAX_REVISION:,} 사이의 정수여야 합니다")
        parse_stamp(self.created_at, "만든 시각")
        parse_stamp(self.updated_at, "고친 시각")
        if self.updated_at < self.created_at:                     # 같은 모양의 글이라 글자 순서가 곧 시간 순서다
            raise _invalid("고친 시각", "만든 시각보다 앞설 수 없습니다")

    # ---- 만들기 ----------------------------------------------------------------------------------------------------------
    @classmethod
    def new(cls, topic, keyword, blogs, *, candidate_id=None, now=None, **fields):
        """새 후보(판 1). 번호를 주지 않으면 만든다. 나머지 칸은 이름으로 준다(예: `search_demand=1200, data_date="2026-11-02"`)."""
        stamp = utc_now() if now is None else now
        return cls(uuid.uuid4().hex if candidate_id is None else candidate_id, topic, keyword, blogs, created_at=stamp, updated_at=stamp, **fields)

    def _stamp(self, now):
        """바꾼 시각 — 주지 않으면 지금(PC 시계가 뒤로 갔어도 고친 시각이 거꾸로 가지 않게 지난 시각보다 앞서지 않는다)."""
        return max(utc_now(), self.updated_at) if now is None else now

    # ---- 바꾸기(새 후보를 돌려준다) -------------------------------------------------------------------------------------------
    def edited(self, *, now=None, **changes):
        """주제·키워드·지표·추천 이유·연결한 글 같은 칸을 바꾼 새 후보. 바뀐 것이 없으면 자기 자신을 돌려주고, 바뀌었으면 판 번호가 오른다.
        번호·상태·선택 기록·판 번호·시각은 여기서 바꿀 수 없다(상태는 `moved`)."""
        unknown = set(changes) - (set(_KEYS) - _FIXED - {"schema"})
        if unknown:
            raise _invalid("후보의 칸", "바꿀 수 없는 칸: " + ", ".join(LABELS.get(name, name) for name in sorted(unknown)), detail=f"바꿀 수 없는 칸: {sorted(unknown)}")
        changed = replace(self, **changes)
        if changed == self:
            return self
        return replace(changed, revision=self.revision + 1, updated_at=self._stamp(now))

    def moved(self, status, *, blog=None, now=None):
        """`TRANSITIONS` 표대로 상태를 옮긴 새 후보(판 번호가 오른다). 표에 없는 이동은 CANDIDATE_TRANSITION_INVALID.
        '선택됨' 으로 옮길 때는 어느 블로그용으로 골랐는지 기록한다 — `blog` 를 주면 그 블로그, 안 주면 추천 대상 블로그 모두. 이미 '선택됨' 인 후보에
        `blog` 를 주면 상태는 그대로 두고 그 블로그를 더 골랐다고(또는 선택 시각을 새로) 기록한다. 보류·검토 중으로 물렸다가 다시 고르면 그때 고른 블로그만 기록에 남는다
        (물리기 전에 고른 것은 취소된 것이라, 다시 살아나 같은 주제 재선택 경고에 잡히지 않는다)."""
        if not isinstance(status, str) or status not in STATUSES:
            raise _invalid(LABELS["status"], "다음 중 하나여야 합니다: " + ", ".join(STATUS_KO[state] for state in STATUSES), detail="상태: " + ", ".join(STATUSES))
        if blog is not None and (status != SELECTED or not isinstance(blog, str) or blog not in st.PLATFORMS):
            raise _invalid("선택한 블로그", "'선택됨' 으로 옮길 때만, 알려진 블로그(" + ", ".join(st.PLATFORMS) + ") 중에서 줄 수 있습니다")
        again = status == self.status == SELECTED and blog is not None
        if not again and not can_transition(self.status, status):
            raise AppError("CANDIDATE_TRANSITION_INVALID", {"현재 상태": STATUS_KO[self.status], "요청 상태": STATUS_KO[status]})
        stamp = self._stamp(now)
        picked = self.selections
        if status == SELECTED:
            chosen = (blog,) if blog is not None else self.blogs
            kept = dict(self.selections) if self.status == SELECTED else {}
            picked = _selections({**kept, **{name: stamp for name in chosen}})
        return replace(self, status=status, selections=picked, revision=self.revision + 1, updated_at=stamp)

    # ---- 읽기 ------------------------------------------------------------------------------------------------------------
    @property
    def selected_blogs(self):
        return tuple(blog for blog, _stamp in self.selections)

    def selected_time(self, blog):
        """그 블로그용으로 마지막에 고른 시각(없으면 None)."""
        return dict(self.selections).get(blog)

    def has_data(self):
        """지표가 하나라도 있는가('데이터 없음' 이 아닌가)."""
        return any(getattr(self, name) is not None for name in METRIC_FIELDS)

    # ---- JSON 로 저장·불러오기 ---------------------------------------------------------------------------------------------
    def to_dict(self):
        return {
            "schema": SCHEMA, "candidate_id": self.candidate_id, "topic": self.topic, "keyword": self.keyword, "sub_keywords": list(self.sub_keywords),
            "blogs": list(self.blogs), "post_type": self.post_type, "search_demand": self.search_demand, "related_blog_results": self.related_blog_results,
            "trend": self.trend, "mobile_share": self.mobile_share, "seasonality": None if self.seasonality is None else list(self.seasonality),
            "duplicate": self.duplicate, "profile_fit": self.profile_fit, "priority": self.priority, "keyword_opportunity": self.keyword_opportunity,
            "reason": self.reason, "data_date": self.data_date, "status": self.status, "selections": dict(self.selections), "project_id": self.project_id,
            "revision": self.revision, "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 모르는 칸·어긋난 값은 CANDIDATE_INVALID 로 거절한다. 꼭 있어야 하는 칸 말고는 빠져 있으면 기본값이다(나중에 칸이 늘어도 옛 자료를 읽는다)."""
        if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != SCHEMA:
            raise _invalid("후보 저장 형식", "저장된 후보의 모양(schema 1)이 아닙니다")
        keys = set(data)
        unknown, missing = sorted(map(str, keys - set(_KEYS))), sorted(_REQUIRED - keys)
        if unknown or missing:
            raise _invalid("후보 저장 형식", "저장된 후보에 모르는 칸이 있거나 꼭 있어야 하는 칸이 없습니다", detail=f"모르는 칸 {unknown}, 빠진 칸 {missing}")
        return cls(**{name: value for name, value in data.items() if name != "schema"})


__all__ = [
    "ALLOWED_TERMS", "Candidate", "FOLLOW_ON", "FOLLOW_ON_KO", "HOLD", "LABELS", "MAX_REVISION", "METRIC_FIELDS", "NEW", "REJECTED", "REVIEW", "SELECTED", "SHORT_ID", "STATUSES", "STATUS_KO",
    "TRANSITIONS", "TRENDS", "can_transition", "find_forbidden_claim", "forbidden_claim", "keyword_key", "next_statuses", "parse_stamp", "short_id", "status_name",
]
