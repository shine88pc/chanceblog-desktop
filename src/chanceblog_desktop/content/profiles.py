"""네이버 블로그 프로필 — A·B 두 블로그를 각자 독립으로 관리하는 설정(docs/PLATFORM_POLICY.md '공통').

두 블로그는 표시명·주소·주제·대상 독자·말투·카테고리 매핑·기본 태그·금지 표현·대표 이미지 규격·글 길이·발행 주기를 **각자** 가진다.
이 프로필은 '그 블로그에 맞는 변환과 점검'의 기준일 뿐이고, 글을 AI 로 다시 쓰지 않는다(말투·주제·대상 독자는 사람이 원고를 고칠 때 보는 안내다).
모든 값은 엄격하게 검사하고(모양이 다르면 CONTENT_INVALID), JSON 으로 저장·불러온다. 로그인 정보·쿠키·토큰은 두지 않는다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ..errors import AppError
from .model import NAVER_HOSTS

KEYS = ("naver_a", "naver_b")
DEFAULT_DISCLOSURE = "이 글은 AI 도구의 도움을 받아 초안을 만들고, 사람이 읽고 고쳐서 올렸습니다."
MAX_TEXT = 200
MAX_NAME = 60
MAX_CATEGORIES = 50
MAX_DEFAULT_TAGS = 30
MAX_FORBIDDEN = 100
MAX_PHRASE = 60
MAX_CHARS_LIMIT = 100_000
_KEYS = {"key", "display_name", "blog_url", "topic", "audience", "tone", "categories", "default_tags", "forbidden_phrases", "image_spec",
         "min_chars", "max_chars", "max_title_chars", "paragraph_max_chars", "max_tags", "disclosure", "publish_cycle"}


def _invalid(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": item}, detail=detail)


def clean_line(value):
    """한 줄 글로: 제어·서식 문자(글자 방향 바꾸기·보이지 않는 글자 등)를 지우고 공백을 하나로 접는다."""
    kept = "".join(" " if ch in "\t\n\r\u2028\u2029" else ch for ch in str(value) if unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co") or ch in "\t\n\r")
    return " ".join(kept.split())


def _text(value, item, *, low=0, high=MAX_TEXT):
    if not isinstance(value, str):
        raise _invalid(item)
    text = clean_line(value)
    if not low <= len(text) <= high or text != value.strip():
        raise _invalid(item, detail=f"{low}~{high}자 한 줄이어야 한다")
    return text


def _number(value, item, low, high):
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise _invalid(item, detail=f"{low}~{high} 사이의 정수여야 한다")
    return value


def _words(values, item, *, count, high):
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise _invalid(item)
    words = tuple(values)
    if len(words) > count:
        raise _invalid(item)
    seen, out = set(), []
    for word in words:
        text = _text(word, item, low=1, high=high)
        if text.casefold() in seen:
            raise _invalid(item, detail="같은 낱말이 두 번 들어 있다")
        seen.add(text.casefold())
        out.append(text)
    return tuple(out)


def _blog_url(value):
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value) or len(value) > 200:
        raise _invalid("블로그 주소")
    try:
        parts = urlsplit(value)
        host, path = parts.hostname, parts.path.strip("/")
    except ValueError:
        raise _invalid("블로그 주소") from None
    if parts.scheme != "https" or host not in NAVER_HOSTS or parts.username or parts.password or not path or parts.query or parts.fragment:
        raise _invalid("블로그 주소", detail="https://blog.naver.com/<블로그 아이디> 모양이어야 한다")
    return value


@dataclass(frozen=True)
class NaverProfile:
    key: str
    display_name: str
    blog_url: str
    topic: str = ""
    audience: str = ""
    tone: str = ""
    categories: tuple = ()                    # ((원고 분류, 네이버 카테고리 이름), …) — dict 로 넘겨도 된다
    default_tags: tuple = ()
    forbidden_phrases: tuple = ()
    image_spec: str = ""                      # 대표 이미지 규격 안내(예: '가로 800px 이상')
    min_chars: int = 800                       # 글 길이 기준(기본값 — 운영자가 블로그마다 정한다)
    max_chars: int = 6000
    max_title_chars: int = 60
    paragraph_max_chars: int = 180             # 이보다 긴 문단은 문장 끝에서 나눈다(짧은 문단 구성)
    max_tags: int = 10
    disclosure: str = ""                       # AI 활용 고지문. 비우면 기본 문구
    publish_cycle: str = ""                    # 발행 주기 안내(예: '주 2회')

    def __post_init__(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        if self.key not in KEYS:
            raise _invalid("블로그 구분")
        put("display_name", _text(self.display_name, "블로그 표시명", low=1, high=MAX_NAME))
        _blog_url(self.blog_url)
        for name, item in (("topic", "주제"), ("audience", "대상 독자"), ("tone", "말투"), ("image_spec", "대표 이미지 규격"), ("publish_cycle", "발행 주기")):
            put(name, _text(getattr(self, name), item))
        put("disclosure", _text(self.disclosure, "AI 활용 고지문", high=300))
        put("categories", self._categories(self.categories))
        put("default_tags", _words(self.default_tags, "기본 태그", count=MAX_DEFAULT_TAGS, high=30))
        put("forbidden_phrases", _words(self.forbidden_phrases, "금지 표현", count=MAX_FORBIDDEN, high=MAX_PHRASE))
        _number(self.min_chars, "글 길이 하한", 0, MAX_CHARS_LIMIT)
        _number(self.max_chars, "글 길이 상한", max(self.min_chars, 1), MAX_CHARS_LIMIT)
        _number(self.max_title_chars, "제목 길이 상한", 1, 200)
        _number(self.paragraph_max_chars, "문단 길이 상한", 40, 2000)
        _number(self.max_tags, "태그 수 상한", 1, 30)

    @staticmethod
    def _categories(value):
        pairs = tuple(value.items()) if isinstance(value, dict) else value
        if isinstance(pairs, (str, bytes)) or len(pairs) > MAX_CATEGORIES:
            raise _invalid("카테고리 매핑")
        out, seen = [], set()
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise _invalid("카테고리 매핑")
            source, target = _text(pair[0], "카테고리 매핑", low=1, high=MAX_NAME), _text(pair[1], "카테고리 매핑", low=1, high=MAX_NAME)
            if source.casefold() in seen:
                raise _invalid("카테고리 매핑", detail="같은 분류가 두 번 들어 있다")
            seen.add(source.casefold())
            out.append((source, target))
        return tuple(out)

    def category_for(self, source):
        """원고의 분류 이름에 맞는 이 블로그의 카테고리(대소문자 무시). 매핑이 없으면 빈 글."""
        wanted = clean_line(source).casefold()
        for name, target in self.categories:
            if name.casefold() == wanted:
                return target
        return ""

    def disclosure_text(self):
        return self.disclosure or DEFAULT_DISCLOSURE

    def to_dict(self):
        return {
            "key": self.key, "display_name": self.display_name, "blog_url": self.blog_url, "topic": self.topic, "audience": self.audience, "tone": self.tone,
            "categories": [list(pair) for pair in self.categories], "default_tags": list(self.default_tags), "forbidden_phrases": list(self.forbidden_phrases),
            "image_spec": self.image_spec, "min_chars": self.min_chars, "max_chars": self.max_chars, "max_title_chars": self.max_title_chars,
            "paragraph_max_chars": self.paragraph_max_chars, "max_tags": self.max_tags, "disclosure": self.disclosure, "publish_cycle": self.publish_cycle,
        }

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 모르는 칸은 거절하고, 빠진 칸은 기본값이다(key·display_name·blog_url 은 꼭 있어야 한다)."""
        if not isinstance(data, dict) or not set(data) <= _KEYS or not {"key", "display_name", "blog_url"} <= set(data):
            raise _invalid("블로그 프로필", detail="칸이 올바르지 않다")
        return cls(**data)
