"""네이버 A·B 두 블로그 글의 유사도 비교(docs/PLATFORM_POLICY.md — 제목·첫 문단·본문·문단 구성·이미지·태그·발행일).

같은 원고를 그대로 두 블로그에 올리지 않게 막는 점검이다. 기준을 넘으면 `NAVER_SIMILARITY_HIGH` — 운영자가 **직접 승인**해야 복사 단계로 넘어갈 수 있다.
AI 없이 규칙만 쓴다: 글을 `NFKC` 로 정규화하고 구두점·공백을 지운 뒤 글자 3개씩 묶음(3-gram)의 겹침(Jaccard)으로 본문·첫 문단을, 편집 거리 비율(SequenceMatcher)로 제목을,
문단 길이의 흐름으로 문단 구성을, 파일 이름·주소의 겹침으로 이미지를, 낱말의 겹침으로 태그를 잰다. 한국어는 조사가 붙어 낱말 단위 비교가 어긋나므로 글자 묶음을 쓴다.
점수는 0~1 이고 두 글의 순서를 바꿔도 같다. 기준(`Thresholds`)은 **기본값**이다 — 운영자가 값을 바꿀 수 있게 인자로 받는다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..errors import AppError

GRAM = 3
MAX_COMPARE_CHARS = 200_000            # 이보다 긴 글은 앞부분만 비교한다(아주 긴 글에서 오래 걸리지 않게)
BUCKET_CHARS = 40                      # 문단 길이를 이 글자 수 단위의 칸으로 센다
MAX_BUCKET = 9
_DROP = re.compile(r"[^\w]|_", re.UNICODE)

WEIGHTS = {"title": 0.20, "intro": 0.15, "body": 0.35, "structure": 0.10, "images": 0.05, "tags": 0.15}


@dataclass(frozen=True)
class Thresholds:
    """유사도 기준(기본값). `high` 이상이면 직접 승인이 필요하고, `warn` 이상이면 경고만 한다. 항목 하나라도 넘으면 그 단계다."""
    high_overall: float = 0.60
    high_body: float = 0.60
    high_title: float = 0.85
    high_intro: float = 0.75
    warn_overall: float = 0.40
    warn_body: float = 0.35
    warn_title: float = 0.60
    warn_intro: float = 0.50


@dataclass(frozen=True)
class Comparable:
    """비교할 글 하나의 재료. `from_package` 로 패키지에서 만들거나 직접 채운다."""
    title: str
    body: str
    tags: tuple = ()
    images: tuple = ()          # 이미지 식별(파일 이름 또는 주소)
    date: str = ""              # 발행(예정) 날짜 YYYY-MM-DD
    intro: str = ""             # 도입부(첫 문단). 비워 두면 본문의 첫 문단

    @classmethod
    def from_package(cls, package, date=""):
        return cls(package.title, package.core_text, tuple(package.tags), tuple((image.filename or image.url) for image in package.images), date, package.intro)


@dataclass(frozen=True)
class SimilarityReport:
    title: float
    intro: float
    body: float
    structure: float
    images: float
    tags: float
    overall: float
    same_day: bool
    level: str                  # "ok" · "warn" · "high"
    reasons: tuple              # 사람이 읽는 이유(화면에 그대로 보인다)

    @property
    def needs_approval(self):
        return self.level == "high"


def normalize(text):
    """비교용으로 정규화: NFKC → 소문자 비슷하게(casefold) → 글자·숫자만 남기고(공백·구두점·기호 제거) 이어 붙인다."""
    return _DROP.sub("", unicodedata.normalize("NFKC", str(text or "")).casefold())


def _grams(text):
    return {text[index:index + GRAM] for index in range(len(text) - GRAM + 1)} if len(text) >= GRAM else ({text} if text else set())


def _jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _ratio(left, right):
    """편집 거리 비율. SequenceMatcher 는 순서를 바꾸면 값이 조금 달라질 수 있어 양쪽의 평균을 쓴다(두 글의 순서를 바꿔도 점수가 같게)."""
    if not left or not right:
        return 0.0
    return (SequenceMatcher(None, left, right, autojunk=False).ratio() + SequenceMatcher(None, right, left, autojunk=False).ratio()) / 2


def _paragraphs(body):
    return [part for part in re.split(r"\n\s*\n", str(body or "")) if normalize(part)]


def _shape(body):
    return [min(len(normalize(part)) // BUCKET_CHARS, MAX_BUCKET) for part in _paragraphs(body)]


def _identities(items):
    return {str(item).strip().casefold() for item in items if str(item).strip()}


def _tags(items):
    return {normalize(item) for item in items if normalize(item)}


def compare(first, second, thresholds=Thresholds()):
    """두 글(`Comparable`)의 유사도. 항목별 점수·가중 평균·단계·이유를 담은 SimilarityReport."""
    for item in (first, second):
        if not isinstance(item, Comparable):
            raise AppError("CONTENT_INVALID", {"항목": "비교할 글"})
    body_a, body_b = normalize(first.body)[:MAX_COMPARE_CHARS], normalize(second.body)[:MAX_COMPARE_CHARS]
    intro_a, intro_b = normalize(first.intro or (_paragraphs(first.body) or [""])[0]), normalize(second.intro or (_paragraphs(second.body) or [""])[0])
    scores = {
        "title": _ratio(normalize(first.title)[:500], normalize(second.title)[:500]),
        "intro": _jaccard(_grams(intro_a[:MAX_COMPARE_CHARS]), _grams(intro_b[:MAX_COMPARE_CHARS])),
        "body": _jaccard(_grams(body_a), _grams(body_b)),
        "structure": _ratio(_shape(first.body), _shape(second.body)),
        "images": _jaccard(_identities(first.images), _identities(second.images)),
        "tags": _jaccard(_tags(first.tags), _tags(second.tags)),
    }
    overall = sum(WEIGHTS[name] * value for name, value in scores.items())
    same_day = bool(first.date) and first.date == second.date
    reasons, level = [], "ok"
    for name, value, high, warn in (("전체", overall, thresholds.high_overall, thresholds.warn_overall), ("본문", scores["body"], thresholds.high_body, thresholds.warn_body),
                                    ("제목", scores["title"], thresholds.high_title, thresholds.warn_title), ("도입부", scores["intro"], thresholds.high_intro, thresholds.warn_intro)):
        if value >= high:
            level = "high"
            reasons.append(f"{name} 유사도 {value:.0%} — 기준({high:.0%}) 이상이라 직접 승인이 필요합니다.")
        elif value >= warn:
            level = "high" if level == "high" else "warn"
            reasons.append(f"{name} 유사도 {value:.0%} — 경고 기준({warn:.0%}) 이상입니다.")
    if scores["tags"] >= 0.8:
        reasons.append(f"태그가 {scores['tags']:.0%} 같습니다. 블로그에 맞게 바꾸세요.")
    if scores["images"] >= 0.8:
        reasons.append("이미지가 거의 같습니다.")
    if same_day:
        reasons.append(f"두 글의 발행일이 같습니다({first.date}).")
    return SimilarityReport(*(round(scores[name], 3) for name in WEIGHTS), round(overall, 3), same_day, level, tuple(reasons))


def check_pair(first, second, *, approved=False, thresholds=Thresholds()):
    """비교해서 보고서를 돌려준다. 기준(`high`)을 넘었는데 운영자가 직접 승인하지 않았으면(`approved=False`) NAVER_SIMILARITY_HIGH."""
    report = compare(first, second, thresholds)
    if report.needs_approval and not approved:
        raise AppError("NAVER_SIMILARITY_HIGH", detail="; ".join(report.reasons))
    return report
