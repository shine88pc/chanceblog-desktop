"""네이버 블로그 프로필 — A·B 두 블로그를 각자 독립으로 관리하는 설정(docs/PLATFORM_POLICY.md '공통').

두 블로그는 표시명·주소·주제·대상 독자·말투·카테고리 매핑·기본 태그·금지 표현·대표 이미지 규격·글 길이·발행 주기를 **각자** 가진다.
글을 만들 때 쓰는 선택 항목(도입부 스타일·소제목 수·설명 난이도·마무리 방식·제외 주제·같은 주제 재사용 기준·기본 글 유형)도 각자 가지며, 모두 기본값이 있어 비워 둬도 된다.
이 프로필은 '그 블로그에 맞는 변환과 점검'의 기준일 뿐이고, 글을 AI 로 다시 쓰지 않는다(말투·주제·대상 독자는 사람이 원고를 고칠 때 보는 안내다).
모든 값은 엄격하게 검사하고(모양이 다르면 CONTENT_INVALID), JSON 으로 저장·불러온다. 로그인 정보·쿠키·토큰은 두지 않는다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, fields
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
# 글 유형 다섯(후보의 '추천 글 유형'과 블로그의 '기본 글 유형'이 같은 목록을 쓴다). 경험담·후기는 글 유형이 아니다 — 경험 정보가 없으면 정보형으로 쓴다.
POST_TYPES = ("정보형", "비교형", "문제 해결형", "제품·서비스 소개형", "장소·업체 정보형")
DEFAULT_POST_TYPE = POST_TYPES[0]
DEFAULT_TOPIC_REUSE_DAYS = 90
MAX_REUSE_DAYS = 3650                      # 같은 주제 재사용 기준의 상한(10년)
MAX_SUBHEADINGS = 20
MAX_EXCLUDED = 100
# 글을 만들 때 쓰는 선택 항목 — 옛 프로필(이 항목이 없는 JSON)도 그대로 읽히고, 값이 기본값이면 저장 모양에 나타나지 않는다(`to_dict`)
_NEW_KEYS = ("intro_style", "subheading_min", "subheading_max", "difficulty", "ending_style", "excluded_topics", "topic_reuse_days", "post_type")
_KEYS = {"key", "display_name", "blog_url", "topic", "audience", "tone", "categories", "default_tags", "forbidden_phrases", "image_spec",
         "min_chars", "max_chars", "max_title_chars", "paragraph_max_chars", "max_tags", "disclosure", "publish_cycle", *_NEW_KEYS}


def _invalid(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": item}, detail=detail)


# ---- 원시 HTML·스크립트·템플릿 표기 찾기(주제 후보의 모든 글칸과 프로필의 새 글칸이 같은 규칙을 쓴다) ------------------------------------------------------------------
# 위험한 태그는 `>` 가 없어도 걸러 낸다(`<script` 만 있어도). 그 밖의 흔한 HTML 태그는 `<b>`·`<br/>`·`</p>` 처럼 닫힌 모양일 때만 걸러서, `Map<String, List<Integer>>` 같은 제네릭·
# `a<b 비교`·`3 < 5` 같은 부등호 글은 지나가게 한다.
_DANGEROUS_TAGS = ("script", "iframe", "img", "style", "form", "object", "embed", "link", "meta", "svg", "base", "frame", "frameset", "applet", "input", "textarea", "button", "select", "option",
                   "body", "html", "head", "title", "math", "template", "video", "audio", "source", "track", "canvas", "portal", "dialog", "noscript", "xml", "marquee")
_PLAIN_TAGS = ("a", "abbr", "b", "big", "blockquote", "br", "center", "cite", "code", "dd", "del", "dfn", "div", "dl", "dt", "em", "font", "h[1-6]", "hr", "i", "ins", "kbd", "li", "mark", "nav", "ol",
               "p", "pre", "q", "s", "samp", "section", "small", "span", "strike", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "tt", "u", "ul", "var", "wbr",
               "article", "aside", "footer", "header", "main", "figure", "figcaption", "details", "summary", "label", "fieldset", "legend", "caption", "col", "colgroup", "hgroup", "address", "bdi",
               "bdo", "data", "dir", "menu", "nobr", "rb", "rp", "rt", "ruby", "time", "xmp")
_EVENT_NAMES = (r"abort|animation\w*|auxclick|before\w+|blur|cancel|canplay\w*|change|click|close|contextmenu|copy|cut|dblclick|drag\w*|drop|durationchange|emptied|ended|error|focus\w*|hashchange|"
                r"input|invalid|key\w+|load\w*|message|mouse\w+|page\w+|paste|pause|play\w*|pointer\w+|popstate|progress|ratechange|readystatechange|reset|resize|scroll\w*|search|seek\w+|select\w*|show|"
                r"stalled|storage|submit|suspend|timeupdate|toggle|touch\w+|transition\w+|unload|volumechange|waiting|wheel")
_MARKUP_RULES = (
    ("HTML 태그는 쓸 수 없습니다", re.compile(rf"</?(?:{'|'.join(_DANGEROUS_TAGS)})\b|</?(?:{'|'.join(_PLAIN_TAGS)})(?:\s[^<>]*)?/?>|<[!?]", re.IGNORECASE)),
    ("onclick= 같은 이벤트 속성은 쓸 수 없습니다", re.compile(rf"\bon(?:{_EVENT_NAMES})\s*=", re.IGNORECASE)),
    ("javascript: 같은 스크립트 주소는 쓸 수 없습니다", re.compile(r"\b(?:javascript|vbscript|data)\s*:(?=\S)", re.IGNORECASE)),       # 콜론 바로 뒤가 공백이면(`JavaScript: 비동기`) 주소가 아니라 제목이다
    ("{% · {{ 같은 템플릿 표기는 쓸 수 없습니다", re.compile(r"\{%|%\}|\{\{|\}\}|\{#|#\}")),
)


def find_markup(text):
    """글 속의 원시 HTML 태그·이벤트 속성·스크립트 주소·템플릿(Liquid) 표기를 찾아 사용자에게 보일 사유 문장을, 없으면 None."""
    for reason, rule in _MARKUP_RULES:
        if rule.search(text):
            return reason
    return None


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


def _no_markup(text, item):
    """글칸에 원시 HTML·스크립트·템플릿 표기를 두지 않는다(후보의 모든 글칸과 같은 규칙 — `find_markup`)."""
    reason = find_markup(text)
    if reason:
        raise _invalid(item, detail=reason)
    return text


def _words(values, item, *, count, high, sequence_only=False, markup_free=False):
    """낱말 목록. `sequence_only` 면 list·tuple 만 받는다(dict·set 은 순서가 정해지지 않아 거절). `markup_free` 면 위험한 표기가 든 낱말도 거절한다."""
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__") or (sequence_only and not isinstance(values, (list, tuple))):
        raise _invalid(item)
    words = tuple(values)
    if len(words) > count:
        raise _invalid(item)
    seen, out = set(), []
    for word in words:
        text = _text(word, item, low=1, high=high)
        if markup_free:
            _no_markup(text, item)
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
    # ---- 글을 만들 때 쓰는 선택 항목(모두 기본값이 있다 — 비워 두면 프로그램 공통 기본값을 따른다) ----
    intro_style: str = ""                      # 도입부 스타일 안내(예: '독자의 고민으로 시작'). 비우면 정하지 않음 — 글 유형 틀·공통 기본값을 따른다
    subheading_min: int = 3                    # 소제목 수 범위(기본값 — 운영자가 블로그마다 정한다)
    subheading_max: int = 5
    difficulty: str = ""                       # 설명 난이도 안내(예: '처음 접하는 사람도 이해'). 비우면 공통 기본값
    ending_style: str = ""                     # 마무리 방식 안내(예: '핵심 세 줄 요약'). 비우면 공통 기본값
    excluded_topics: tuple = ()                # 이 블로그에서 다루지 않을 주제(낱말·구)
    topic_reuse_days: int = DEFAULT_TOPIC_REUSE_DAYS   # 같은 핵심 키워드를 다시 고르기 전에 기다리는 날수(0 이면 경고하지 않는다)
    post_type: str = DEFAULT_POST_TYPE         # 기본 글 유형(POST_TYPES 중 하나)

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
        for name, item in (("intro_style", "도입부 스타일"), ("difficulty", "설명 난이도"), ("ending_style", "마무리 방식")):
            put(name, _no_markup(_text(getattr(self, name), item), item))      # 새 글칸은 위험한 HTML·스크립트·템플릿 표기를 거절한다(예전 칸은 그대로 — 옛 프로필이 그대로 읽혀야 한다)
        put("excluded_topics", _words(self.excluded_topics, "제외 주제", count=MAX_EXCLUDED, high=MAX_PHRASE, sequence_only=True, markup_free=True))
        _number(self.subheading_min, "소제목 수 하한", 1, MAX_SUBHEADINGS)
        _number(self.subheading_max, "소제목 수 상한", self.subheading_min, MAX_SUBHEADINGS)
        _number(self.topic_reuse_days, "같은 주제 재사용 기준", 0, MAX_REUSE_DAYS)
        if not isinstance(self.post_type, str) or self.post_type not in POST_TYPES:
            raise _invalid("기본 글 유형", detail="글 유형: " + ", ".join(POST_TYPES))

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
        """저장 모양. 글을 만들 때 쓰는 선택 항목은 기본값에서 벗어난 것만 적는다 — 그 항목을 쓰지 않는 프로필의 저장 모양은 예전과 한 글자도 다르지 않다."""
        data = {
            "key": self.key, "display_name": self.display_name, "blog_url": self.blog_url, "topic": self.topic, "audience": self.audience, "tone": self.tone,
            "categories": [list(pair) for pair in self.categories], "default_tags": list(self.default_tags), "forbidden_phrases": list(self.forbidden_phrases),
            "image_spec": self.image_spec, "min_chars": self.min_chars, "max_chars": self.max_chars, "max_title_chars": self.max_title_chars,
            "paragraph_max_chars": self.paragraph_max_chars, "max_tags": self.max_tags, "disclosure": self.disclosure, "publish_cycle": self.publish_cycle,
        }
        for name in _NEW_KEYS:
            value = getattr(self, name)
            if value != _NEW_DEFAULTS[name]:
                data[name] = list(value) if isinstance(value, tuple) else value
        return data

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 모르는 칸은 거절하고, 빠진 칸은 기본값이다(key·display_name·blog_url 은 꼭 있어야 한다)."""
        if not isinstance(data, dict) or not set(data) <= _KEYS or not {"key", "display_name", "blog_url"} <= set(data):
            raise _invalid("블로그 프로필", detail="칸이 올바르지 않다")
        return cls(**data)


_NEW_DEFAULTS = {item.name: item.default for item in fields(NaverProfile) if item.name in _NEW_KEYS}
