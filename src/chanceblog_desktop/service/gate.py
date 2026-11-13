"""발행 전 검사(게이트) — 승인한 글 한 편이 올라가도 되는지 본다. 하나라도 걸리면 올리지 않는다(fail closed, AGENTS.md 규칙 4).

여덟 가지를 함께 본다:
  1) 파일 모양과 키 모양 문자열 — `publish.pages.check_post`(머리말·제어 문자·크기·키 모양 문자열). 이것이 걸리면 어떤 것도 고치기 전에는 못 하므로 그 오류 코드 그대로 낸다.
  2) 핵심 코드의 검사 — `pipeline/gates.py`(vendor/)의 `check_post`: 글자 수·언어 비율·태그 수·AI 메타 문구 같은 잔여물. 글을 허용 태그만 있는 HTML 로 바꿔 넣는다(chanceblog 가 Blogger 글에 하는 것과 같은 방식).
  3) 최소 본문 분량 — chanceblog 생성기(`generator.py` 의 `_validate_editorial_body`)와 **같은 계산에 더 엄격한 규칙을 더한 것**: 출처 목록(`## 출처`·`## Sources`) 앞의 글에서 이미지·링크 표시·태그·Markdown 기호와 공백을 모두 뺀 글자 수가
     한글 1000자·영문 1500자 이상이어야 한다. 눈에 안 보이는 글자(폭 없는 공백·채움 글자·점자 빈칸 …)는 글자로 세지 않는다(그것으로 길이 기준을 채우지 못하게). 그런 글자가 비정상적으로 많으면(50개 초과 또는 본문의 5% 초과) 그 자체로 막는다.
  4) 이 PC 의 폴더 경로(`C:/Users/…`·`\\\\서버\\공유`·`file:///…`·8.3 짧은 이름·데이터 폴더·연결한 저장소 폴더 — 대소문자·슬래시 모양이 달라도)가 글에 들어 있지 않은가 — 로컬 절대경로를 저장소에 올리지 않는다(AGENTS.md 규칙 2).
  5) **올라가는 글 그대로(Markdown 원문)** 에 HTML 태그·`javascript:` 같은 주소·`{% %}`/`{{ }}` 템플릿 표기·`{: }` 속성 붙이기·광고 스크립트가 없는가 — 위 2 는 원문이 아니라 HTML 로 바꾼 결과를 보는데 그 과정에서 원시 HTML 은 글자로 바뀌고
     위험한 주소는 사라지지만, 저장소에 올라가는 것은 원문이고 사이트(Jekyll)는 원시 HTML 을 그대로 내보내며 `{% %}`·`{{ }}` 는 글을 만들 때 실행한다(광고 사이트에서 스크립트가 끼어들거나 사이트 빌드가 깨질 수 있다).
  6) **머리말 값 전부**(제목·분야·태그·대표 이미지 주소·설명·출처 이름·주소·도메인)에도 같은 검사를 한다 — 머리말 값은 사이트의 글 목록(`posts.json`)·카드·`<title>`·`<meta>` 에 들어가고, 첫 화면의 카드는 제목·분야·태그·이미지 주소를
     이스케이프 없이 HTML 에 넣는 곳이 있다(chanceblog `index.html`). 그래서 HTML 태그·템플릿 표기·위험한 주소는 본문과 똑같이 막고, 줄바꿈·제어 문자·너무 긴 값·https 가 아닌 이미지 주소·따옴표/꺾쇠가 든 주소·모르는 머리말 키(`published`·`permalink` 같은 것)도
     막는다(`HEADER_VALUE`). 글을 만들거나 고칠 때의 **제목**도 같은 검사를 거친다(`title_problems`). 글자의 표시 방향을 바꾸는 제어 문자(U+202A–202E·U+2066–2069)는 본문·머리말 값(제목 포함) 어디에 몇 개가 있든 막는다(`INVISIBLE`).

**검사 기준은 기본값이다**: chanceblog 의 Chance 블로그에는 `gates.check_post` 용 프로필이 없다(`pipeline/blogs.json` 의 `profile: null`). 그래서 여기서는 chanceblog 생성기가 글을 받을 때 쓰는
최소 본문 분량(위 3)과 객관적인 잔여물·위험 표기 점검만 쓰고(핵심 코드 쪽의 글자 수 기준에도 같은 숫자를 건다 — 그쪽은 공백을 한 칸씩 세므로 더 느슨해 위 3 이 실제로 막는다), 금지 낱말·주제 같은 **정책은 새로 만들지 않는다**(정책·톤을 바꾸는 일은 T3 — 운영자 결정이 필요하다).
"""
from __future__ import annotations

import html
import json
import re
from collections import namedtuple
from dataclasses import dataclass

from ..content.model import MAX_TITLE
from ..core import use_vendored_core
from ..errors import AppError
from ..publish.pages import check_post as check_post_file
from ..render.markdown import markdown_to_html
from ..render.pages import LANG_PREFIX, MAX_CATEGORY, MAX_DESCRIPTION, MAX_TAG, MAX_TAGS, front_matter_problems
from ..security.mask import _INVISIBLE, _strip_invisible

use_vendored_core()
from pipeline import gates as core_gates  # noqa: E402  (vendor/ 경로를 먼저 올려야 한다)

LENGTH_MIN = {"ko": 1000, "en": 1500}                   # chanceblog 생성기의 MIN_BODY_CHARS(kr 1000·en 1500)와 같은 숫자
MAX_INVISIBLE = 50                                       # 눈에 안 보이는 글자가 이보다 많거나
INVISIBLE_RATIO = 0.05                                   # 본문의 이 비율을 넘으면 막는다(이모지에 붙는 ZWJ·변형 선택자는 세지 않는다)
_SOURCES_HEADING = re.compile(r"(?im)^##\s*(?:출처|참고 자료|sources)\s*$")
LABELS = {"min": 0, "max": 10, "max_chars": 40}          # render.pages 의 태그 상한(10개·40자)과 같다
# AI 가 글에 흘린 자기 소개·템플릿 잔여물. 일반 글에도 나올 수 있는 낱말(`language model`·`todo`)은 넣지 않는다.
LEAK_PATTERNS = (
    r"AI\s*(?:로서|언어\s*모델|어시스턴트)", r"\bas an ai (?:language model|assistant|model)\b", r"lorem ipsum", r"\{topic\}", r"\[대상", r"(?m)^\s*(?:제목|라벨|내용)\s*:",
)
# 이 PC 의 경로 모양 — 드라이브 사용자 폴더(`C:\Users\`·`C:/users/`·`file:///C:/Users/`·`\\?\C:\Users\`) · WSL·Cygwin 의 같은 폴더 · UNC(`\\서버\공유`, JSON 이스케이프 `\\\\서버\\공유` 포함) ·
# 8.3 짧은 이름(`C:\PROGRA~1`·`\FAKE_U~1` — 글 속 `1~10` 같은 표기는 앞에 `\` 나 드라이브가 없어 걸리지 않는다) · `file:` 주소(어느 것이든)
_LOCAL_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]", re.IGNORECASE)
_WSL_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:mnt|cygdrive)/[A-Za-z]/Users/", re.IGNORECASE)
_UNC_PATH = re.compile(r"(?<![\\\w])\\{2,}[^\\/\s\"'<>|]{1,200}\\+[^\\/\s\"'<>|]{1,200}")
_SHORT_NAME = re.compile(r"(?:\\|(?<![A-Za-z0-9])[A-Za-z]:[\\/]+)[A-Za-z0-9_$!#%&'()@^`{}-]{1,8}~[0-9]{1,4}(?![A-Za-z0-9~])")
_FILE_URL = re.compile(r"(?<![A-Za-z0-9])file:/{2,}", re.IGNORECASE)
# 올라가는 Markdown 원문의 위험한 표기
_HTML_TAG = re.compile(r"<(/?[A-Za-z][A-Za-z0-9-]{0,40}(?::[A-Za-z][A-Za-z0-9-]{0,40})?)(?=[\s/>])[^<>]{0,2000}>|<([!?])")      # `<https://…>` 같은 자동 링크는 이름 뒤가 `:/` 라 태그가 아니다
_TEMPLATE = re.compile(r"\{[%{#]")
_ATTRIBUTE_LIST = re.compile(r"\{:")
_AD_SCRIPT = re.compile(r"adsbygoogle|googlesyndication", re.IGNORECASE)
_SCHEME = r"(?:j\s*a\s*v\s*a\s*s\s*c\s*r\s*i\s*p\s*t|v\s*b\s*s\s*c\s*r\s*i\s*p\s*t|d\s*a\s*t\s*a)\s*:"
# 주소 앞의 공백에는 **길이 상한을 두지 않는다**(CommonMark 의 링크 목적지 앞 공백은 길이 제한이 없어서, 상한을 두면 공백을 길게 넣은 `javascript:` 링크가 검사를 빠져나간다).
# 대신 정규식이 모호하지 않게 쓴다 — `\s*<?\s*`·`\s*["']?\s*` 는 공백 n 개를 두 `\s*` 에 나누는 방법이 n 가지라 맞지 않을 때 O(n²) 로 되돌아갔다(공백 6만 개에 88초).
# `\s*(?:<\s*)?`·`\s*(?:["']\s*)?` 는 같은 뜻이면서 나누는 방법이 하나뿐이라 공백이 아무리 길어도 선형 시간이다.
_UNSAFE_URL = re.compile(
    r"(?is)(?:\]\(\s*(?:<\s*)?|^[ \t]{0,3}\[[^\]\n]{0,200}\][ \t]*:\s*(?:<\s*)?|<\s*|\b(?:href|src|action|formaction|srcdoc|poster|background)\s*=\s*(?:[\"']\s*)?)" + _SCHEME, re.MULTILINE)
_JOINERS = re.compile("[\u200c\u200d\ufe0e\ufe0f\U000e0100-\U000e01ef]")      # 이모지·문자 이음에 쓰이는 보이지 않는 글자 — 길이에는 안 세고 '많음' 판단에서는 뺀다
# 글자가 화면에 보이는 방향·순서를 바꾸는 제어 문자 — U+202A–202E(LRE·RLE·PDF·LRO·RLO)·U+2066–2069(LRI·RLI·FSI·PDI). 제목·링크 글을 다르게 보이게 위장하는 데 쓸 수 있고 한글·영어 글에는 필요 없어서
# 몇 개든(개수·비율과 상관없이) 막는다. U+200E·U+200F(LRM·RLM)는 방향을 '표시' 할 뿐이라 이 규칙 밖이다(다른 보이지 않는 글자와 같이 개수로 센다).
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")
_HEADER_LINE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)")
_JSON_KEYS = ("title", "category", "image", "description", "source_name", "source_url", "source_domain")
_Sample = namedtuple("_Sample", "path text")
# 정규식이 길게 되돌아가며 제곱 시간이 걸리지 않게 하는 상한(`[a` 를 수만 번 되풀이한 글도 빨리 끝난다)
_IMAGE = re.compile(r"!\[[^\]\[]{0,2000}\]\([^)\n]{0,300}\)")
_LINK = re.compile(r"\[([^\]\[]{1,2000})\]\([^)\n]{0,300}\)")
_TAG_OR_MARK = re.compile(r"<[^<>]{1,2000}>|[`*_>#|~]")
# 머리말 값(제목·분야·태그·주소·설명·출처): 렌더링이 만드는 키뿐이고, 값의 길이는 렌더링의 한도와 같다
HEADER_KEYS = ("layout", "title", "category", "tags", "lang", "image", "description", "source_name", "source_url", "source_domain")
VALUE_LIMITS = {"title": MAX_TITLE, "category": MAX_CATEGORY, "description": MAX_DESCRIPTION, "source_name": 200, "image": 1500, "source_url": 1500, "source_domain": 253}
_VALUE_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f  ￾￿]")       # 줄바꿈·제어 문자(탭은 받는다) — 한 줄 값이 머리말 줄 구조를 깨거나 다른 키를 끼워 넣지 못하게
_URL_BAD = re.compile(r"[\"<>`\\\s\x00-\x1f\x7f-\x9f]")                                      # 주소에 있으면 안 되는 글자: 공백·따옴표·꺾쇠·역따옴표·역슬래시·제어 문자(HTML 속성·태그 밖으로 빠져나온다)
_URL_PARTS = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(?://([^/?#]*))?")
_SCHEME_START = re.compile(r"(?is)^[\s\x00-\x20]*" + _SCHEME)
_SCHEME_TEXT = re.compile(r"(?is)^[\s\x00-\x20]*" + _SCHEME + r"\S")        # 주소 칸이 아닌 글 값이 `javascript:alert(1)` 처럼 주소로 시작하는 것('JavaScript: 입문' 같은 제목은 콜론 뒤가 공백이라 아니다)


@dataclass(frozen=True)
class GateReport:
    ok: bool
    reasons: tuple          # 막는 사유 — "[코드] 설명"
    warnings: tuple         # 참고(막지 않는다)
    chars: int              # 본문 글자 수(핵심 코드가 세는 방식)
    blocking: object = None  # AppError — 파일 모양·키 모양 문자열처럼 그 오류 코드로 알려야 하는 문제

    def codes(self):
        return tuple(reason.split("]", 1)[0].lstrip("[") for reason in self.reasons if reason.startswith("["))

    def to_dict(self):
        return {"ok": self.ok, "reasons": list(self.reasons), "warnings": list(self.warnings), "chars": self.chars}


def readable_chars(body):
    """chanceblog 생성기(`_validate_editorial_body`)와 같은 계산 — 출처 목록 앞의 글에서 이미지·링크 표시·태그·Markdown 기호를 걷고 공백을 모두 뺀 글자 수.
    생성기보다 엄격한 점 둘: 눈에 안 보이는 글자(폭 없는 공백·채움 글자·점자 빈칸 …)는 세지 않고, 정규식에 길이 상한을 둬 아주 긴 이상한 입력에도 선형 시간에 끝난다."""
    story = _SOURCES_HEADING.split(body, maxsplit=1)[0]
    readable = _IMAGE.sub(" ", story)
    readable = _LINK.sub(r"\1", readable)
    readable = _TAG_OR_MARK.sub(" ", readable)
    readable = _strip_invisible(readable)
    return len(re.sub(r"\s+", "", readable))


def invisible_count(text):
    """길이 기준을 속이는 데 쓰이는 눈에 안 보이는 글자의 수(이모지·문자 이음용 ZWJ·ZWNJ·변형 선택자는 뺀다)."""
    return len(text) - len(_strip_invisible(text)) - len(_JOINERS.findall(text))


def gate_profile(lang):
    """핵심 코드 `check_post` 에 넘기는 기준(기본값)."""
    return {"name": "chance_pages_app_default", "language": lang, "length": {"min_chars": LENGTH_MIN[lang]}, "labels": dict(LABELS), "leak_patterns": list(LEAK_PATTERNS)}


def split_post(text):
    """글 한 편(머리말+본문) → (머리말 값들, 본문 Markdown). 머리말 모양이 올바르지 않으면 CONTENT_INVALID."""
    problems = front_matter_problems(text)
    if problems:
        raise AppError("CONTENT_INVALID", {"항목": "머리말"}, detail="; ".join(problems))
    lines = text.split("\n")
    end = lines.index("---", 1)
    header = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        found = _HEADER_LINE.match(line)
        if found is None:
            raise AppError("CONTENT_INVALID", {"항목": "머리말"}, detail="`키: 값` 모양이 아닌 줄이 있다")
        key, value = found.groups()
        try:
            header[key] = json.loads(value) if key in _JSON_KEYS or (key == "tags" and value) else value
        except ValueError:
            raise AppError("CONTENT_INVALID", {"항목": "머리말"}, detail=f"`{key}` 값이 한 줄 JSON 이 아니다") from None
    header.setdefault("tags", [])
    return header, "\n".join(lines[end + 1:]).strip("\n")


def _decoded(text):
    """엔티티(`&#106;`·`&Tab;` …)를 풀고 눈에 안 보이는 글자를 지운 글 — 주소의 `javascript:` 를 이렇게 숨긴 것까지 찾으려고."""
    for _ in range(3):
        step = html.unescape(text)
        if step == text:
            break
        text = step
    return _INVISIBLE.sub("", text)


def _raw_reasons(text, where, *, header):
    """글 한 덩어리(본문 또는 머리말 값 하나)의 위험한 표기 → ["[코드] 설명", …]. `where` 는 '원고에'·'머리말 `title` 에' 처럼 어디인지(조사까지)."""
    reasons = []
    stripped = _strip_invisible(text)
    tags = sorted({(found.group(1) or "!").lstrip("/").lower() for found in _HTML_TAG.finditer(stripped)})
    if tags:
        shown = ", ".join(f"<{name}>" for name in tags[:5]) + (" …" if len(tags) > 5 else "")
        why = ("사이트의 글 목록·카드·제목 줄에 그대로 들어가 스크립트가 끼어들 수 있으니 태그를 지운다" if header else
               "이 앱은 Markdown 글만 올린다. 사이트가 원시 HTML 을 그대로 내보내 스크립트·광고가 끼어들 수 있으니 태그를 지우거나 Markdown 으로 바꾼다")
        reasons.append(f"[RAW_HTML] {where} HTML 태그가 있다: {shown} — {why}")
    if _TEMPLATE.search(stripped):
        reasons.append(f"[LIQUID] {where} `{{% … %}}`·`{{{{ … }}}}`·`{{# … #}}` 같은 템플릿 표기가 있다 — 사이트(Jekyll)가 글을 만들 때 실행해 사이트 빌드가 깨질 수 있어 올리지 않는다"
                       + ("" if header else "(코드 예시 안이어도 같다)") + ". 지우거나 다른 말로 바꾼다")
    if _ATTRIBUTE_LIST.search(stripped):
        reasons.append(f"[KRAMDOWN] {where} `{{: … }}`(속성 붙이기) 표기가 있다 — 링크·이미지에 스크립트 속성을 붙일 수 있어 올리지 않는다. 지운다")
    view = _decoded(stripped)
    if _UNSAFE_URL.search(view):
        reasons.append(f"[UNSAFE_URL] {where} `javascript:`·`data:`·`vbscript:` 주소가 있다(공백·엔티티로 숨긴 것 포함) — 링크·이미지 주소는 https 만 쓴다. 지우거나 https 주소로 바꾼다")
    if _AD_SCRIPT.search(view):
        reasons.append(f"[AD_SCRIPT] {where} 광고 스크립트(adsbygoogle·googlesyndication)가 있다 — 광고는 사이트가 넣는다. 지운다")
    return reasons


def _bidi_reasons(text, where):
    """글자 방향을 바꾸는 보이지 않는 제어 문자(`_BIDI`)가 하나라도 있으면 사유 하나(`[INVISIBLE]`) — 개수·본문 길이와 상관없이 막는다. `where` 는 '원고에'·'머리말 `title` 에' 처럼 어디인지(조사까지)."""
    found = sorted({f"U+{ord(char):04X}" for char in _BIDI.findall(text)})
    if not found:
        return []
    shown = ", ".join(found[:4]) + (" …" if len(found) > 4 else "")
    return [f"[INVISIBLE] {where} 글자의 표시 방향을 바꾸는 보이지 않는 제어 문자가 있다({shown}) — 글이 화면에 다르게 보이도록 위장하는 데 쓰일 수 있어 개수와 상관없이 올리지 않는다. 지운다"]


def raw_markdown_problems(body):
    """저장소에 올라가는 Markdown 원문의 위험한 표기 → ["[코드] 설명", …]. 코드 블록 안이어도 같다(사이트가 코드 안의 `{{ }}` 도 실행하고, 코드 블록의 경계는 사이트마다 다르게 읽을 수 있다).
    글자 방향을 바꾸는 제어 문자(U+202A–202E·U+2066–2069)도 여기서 몇 개든 막는다."""
    return _raw_reasons(body, "원고에", header=False) + _bidi_reasons(body, "원고에")


def _split_url(value):
    """주소 → (소문자 스킴, 호스트(소문자), 로그인 정보가 있는가). 스킴이 없으면 None. 표준 라이브러리의 urllib 은 이 층에서 쓰지 않으므로 필요한 만큼만 직접 읽는다."""
    found = _URL_PARTS.match(value)
    if found is None:
        return None
    scheme, authority = found.group(1).lower(), found.group(2) or ""
    userinfo = "@" in authority
    hostport = authority.rsplit("@", 1)[-1]
    host = hostport[1:hostport.index("]")] if hostport.startswith("[") and "]" in hostport else hostport.split(":", 1)[0]
    return scheme, host.lower(), userinfo


def _url_reasons(key, value, schemes):
    """머리말의 주소 칸(image·source_url) 하나 → 사유. 정해진 스킴(https 등)의 평범한 주소만 받는다 — 공백·따옴표·꺾쇠가 든 주소는 HTML 속성 밖으로 빠져나온다."""
    reasons = []
    if _URL_BAD.search(value):
        reasons.append(f"[HEADER_VALUE] 머리말 `{key}` 주소에 공백·따옴표·꺾쇠·역따옴표·역슬래시·제어 문자가 있다 — 사이트가 이 주소를 HTML 속성에 그대로 넣으므로 올리지 않는다. 평범한 주소로 바꾼다")
    view = _decoded(_strip_invisible(value))
    if _SCHEME_START.match(view):
        reasons.append(f"[UNSAFE_URL] 머리말 `{key}` 에 `javascript:`·`data:`·`vbscript:` 주소가 있다 — https 주소만 쓴다. 지우거나 https 주소로 바꾼다")
    parts = _split_url(value)
    if parts is None or parts[0] not in schemes or not parts[1] or parts[2]:
        shown = "https" if schemes == ("https",) else "http 또는 https"
        reasons.append(f"[HEADER_VALUE] 머리말 `{key}` 가 {shown} 주소 모양이 아니다(호스트가 없거나 로그인 정보가 들어 있다) — {shown} 로 시작하는 평범한 주소를 쓴다")
    return reasons


def _value_reasons(key, value, *, limit=None, url_schemes=None):
    """머리말의 글 값(문자열) 하나 → 사유 — 길이·줄바꿈·제어 문자·눈에 안 보이는 글자와 본문과 같은 위험한 표기 검사(주소 칸이면 주소 모양도)."""
    reasons = []
    where = f"머리말 `{key}` 에"
    if not isinstance(value, str):
        return [f"[HEADER_VALUE] 머리말 `{key}` 값이 글자가 아니다"]
    if limit is not None and len(value) > limit:
        reasons.append(f"[HEADER_VALUE] 머리말 `{key}` 가 너무 길다({len(value)}자 — 최대 {limit}자)")
    if _VALUE_CONTROL.search(value):
        reasons.append(f"[HEADER_VALUE] 머리말 `{key}` 에 줄바꿈·제어 문자가 있다 — 머리말은 한 줄에 한 키라서 값의 줄바꿈은 다른 머리말 키를 끼워 넣는 데 쓰일 수 있다. 지운다")
    if key != "title" and invisible_count(value):
        reasons.append(f"[INVISIBLE] 머리말 `{key}` 에 눈에 안 보이는 글자가 있다 — 주소·태그·분야에 숨은 글자를 넣어 검사를 피할 수 있다. 지운다")
    reasons.extend(_bidi_reasons(value, where))                          # 제목은 보이지 않는 글자를 본문과 합쳐 센다(몇 개는 봐준다) — 그래도 글자 방향을 바꾸는 제어 문자는 어느 값에서든 몇 개든 막는다
    reasons.extend(_raw_reasons(value, where, header=True))
    if url_schemes is not None:
        reasons.extend(_url_reasons(key, value, url_schemes))
    elif _SCHEME_TEXT.match(_decoded(_strip_invisible(value))):
        reasons.append(f"[UNSAFE_URL] {where} `javascript:`·`data:`·`vbscript:` 주소로 시작하는 글이 있다 — 주소가 아니라 글이어야 한다. 지운다")
    return reasons


def title_problems(title):
    """글을 만들거나 고칠 때 제목이 머리말(`title`)에 들어가도 되는가 → 사유 목록(비어 있으면 괜찮다). 머리말 값과 같은 검사다(길이는 글 모델이 따로 본다 — CONTENT_INVALID)."""
    return _value_reasons("title", title)


def _refuse(reasons):
    """사유가 있으면 CHECK_FAILED(발행 전 검사와 같은 오류 코드·사유). 없으면 아무것도 하지 않는다."""
    if reasons:
        codes = []
        for reason in reasons:
            code = reason.split("]", 1)[0].lstrip("[")
            if code not in codes:
                codes.append(code)
        raise AppError("CHECK_FAILED", {"걸린 항목 목록": ", ".join(codes)}, detail="; ".join(reasons))


def require_clean_title(title):
    """제목이 `title_problems` 에 걸리면 CHECK_FAILED — 글에 넣기 전(만들 때·고칠 때)에 알린다."""
    _refuse(title_problems(title))


def require_clean_front_values(text):
    """이 글(머리말+본문)의 머리말 값이 `front_value_problems` 에 걸리면 CHECK_FAILED — 검토를 요청하거나 미리 볼 때 방금 준 값(분야·태그·이미지 주소·설명·출처)을 바로 알린다."""
    header, _body = split_post(text)
    _refuse(front_value_problems(header))


def front_value_problems(header):
    """`split_post` 가 읽은 머리말의 값 전부(제목·분야·태그·대표 이미지·설명·출처) → 사유 목록. 허용하는 키는 렌더링이 만드는 것뿐이다."""
    reasons = []
    unknown = sorted(set(header) - set(HEADER_KEYS))
    if unknown:
        shown = ", ".join(f"`{ascii(key)[1:-1]}`" for key in unknown[:5]) + (" …" if len(unknown) > 5 else "")
        reasons.append(f"[HEADER_VALUE] 머리말에 허용하지 않는 키가 있다: {shown} — 이 앱이 만드는 머리말은 {', '.join(HEADER_KEYS)} 뿐이다(`published`·`permalink` 같은 키는 글의 공개·주소를 바꾼다)")
    for key in ("title", "category", "description", "source_name"):
        if key in header:
            reasons.extend(_value_reasons(key, header[key], limit=VALUE_LIMITS[key]))
    for key, schemes in (("image", ("https",)), ("source_url", ("http", "https"))):
        if key in header:
            reasons.extend(_value_reasons(key, header[key], limit=VALUE_LIMITS[key], url_schemes=schemes))
    tags = header.get("tags", [])
    if not isinstance(tags, list):
        reasons.append("[HEADER_VALUE] 머리말 `tags` 가 목록이 아니다")
    else:
        if len(tags) > MAX_TAGS:
            reasons.append(f"[HEADER_VALUE] 머리말 `tags` 가 너무 많다({len(tags)}개 — 최대 {MAX_TAGS}개)")
        for tag in tags:
            reasons.extend(_value_reasons("tags", tag, limit=MAX_TAG))
    if "source_domain" in header:
        reasons.extend(_value_reasons("source_domain", header["source_domain"], limit=VALUE_LIMITS["source_domain"]))
    given = [key for key in ("source_name", "source_url", "source_domain") if key in header]
    if given and len(given) != 3:
        reasons.append("[HEADER_VALUE] 머리말의 출처 세 줄(`source_name`·`source_url`·`source_domain`)이 함께 있지 않다")
    elif given:
        parts = _split_url(header["source_url"]) if isinstance(header["source_url"], str) else None
        if parts is None or header["source_domain"] != parts[1]:
            reasons.append("[HEADER_VALUE] 머리말의 `source_domain` 이 `source_url` 의 호스트와 다르다")
    return reasons


_PERCENT = re.compile(r"(?:%[0-9A-Fa-f]{2}){1,64}")


def unquote(text):
    """`%EB%82%B4` 같은 주소 인코딩을 푼다(표준 라이브러리의 urllib 은 이 층에서 쓰지 않는다 — 안전 시험이 네트워크 모듈 사용을 막는다)."""
    return _PERCENT.sub(lambda found: bytes.fromhex(found.group(0).replace("%", "")).decode("utf-8", "replace"), text)


def _flat(value):
    """경로 비교용 — 보이지 않는 글자를 지우고 역슬래시를 슬래시로, 대소문자를 같게."""
    return _strip_invisible(value).replace("\\", "/").casefold()


def local_path_problem(text, local_paths=()):
    """글에 이 PC 의 폴더 경로가 들어 있으면 True — 정규식 모양(드라이브 사용자 폴더·UNC·8.3·file:)과 이 PC 의 실제 폴더(데이터 폴더·연결한 저장소)를 대소문자·슬래시 모양과 상관없이 찾는다."""
    clean = _strip_invisible(text)
    for form in (clean, unquote(clean)):
        if any(pattern.search(form) for pattern in (_LOCAL_PATH, _WSL_PATH, _UNC_PATH, _SHORT_NAME, _FILE_URL)):
            return True
    forms = (_flat(text), _flat(unquote(text)))
    for path in local_paths:
        wanted = _flat(str(path)).rstrip("/")
        if len(wanted) >= 4 and any(wanted in form for form in forms):
            return True
    return False


def run_gates(text, *, local_paths=()):
    """글 한 편을 검사해 GateReport 를 돌려준다(예외를 내지 않는다 — 막을지는 `require_gates` 가 정한다)."""
    try:
        header, body = split_post(text)
    except AppError as error:
        return GateReport(False, (f"[HEADER] 머리말이 올바르지 않다: {error.detail}",), (), 0, error)
    lang = header["lang"]
    reasons, warnings, blocking = [], [], None
    try:
        check_post_file(_Sample(f"_posts/gate/2000-01-01-{LANG_PREFIX[lang]}-000000.md", text))
    except AppError as error:
        blocking = error
        shown = error.rendered().message
        reasons.append(f"[{error.code}] {shown}" + (f" — {error.detail}" if error.detail else ""))
    reasons.extend(raw_markdown_problems(body))                  # 올라가는 것은 원문이다 — 아래 HTML 변환 결과가 아니라 원문을 본다
    reasons.extend(front_value_problems(header))                 # 머리말 값(제목·분야·태그·이미지 주소·설명·출처)도 사이트 화면에 들어간다 — 같은 검사
    chars = 0
    try:
        html_body = markdown_to_html(body)
    except AppError as error:
        return GateReport(False, tuple(reasons) + (f"[BODY] 본문을 바꿀 수 없다: {error.detail}",), (), 0, blocking or error)
    result = core_gates.check_post({"title": header["title"], "labels": list(header["tags"]), "content": html_body}, gate_profile(lang))
    reasons.extend(result.reasons)
    warnings.extend(result.warnings)
    chars = core_gates.text_length(core_gates.plain_text(html_body))
    readable = readable_chars(body)
    if readable < LENGTH_MIN[lang]:
        reasons.append(f"[LEN_BODY] 본문(출처 목록·공백·보이지 않는 글자 제외) {readable}자 (최소 {LENGTH_MIN[lang]}자 — chanceblog 생성기와 같은 계산)")
    hidden = invisible_count(body) + invisible_count(str(header.get("title", "")))
    if hidden > MAX_INVISIBLE or hidden > INVISIBLE_RATIO * len(body):
        reasons.append(f"[INVISIBLE] 눈에 안 보이는 글자가 {hidden}개 있다(본문 {len(body)}자) — 글자 수를 채우거나 글을 숨기는 데 쓰일 수 있다. 지운 뒤 다시 만든다")
    if local_path_problem(text, local_paths):
        reasons.append("[LOCAL_PATH] 글에 이 PC 의 폴더 경로가 들어 있다(저장소에 올리지 않는다)")
    return GateReport(not reasons, tuple(reasons), tuple(warnings), chars, blocking)


def require_gates(text, *, local_paths=()):
    """검사를 통과해야 한다 — 걸리면 AppError(키 모양 문자열·파일 모양은 그 코드, 나머지는 CHECK_FAILED). 통과하면 GateReport."""
    report = run_gates(text, local_paths=local_paths)
    if report.blocking is not None:
        raise report.blocking
    if not report.ok:
        raise AppError("CHECK_FAILED", {"걸린 항목 목록": ", ".join(report.codes()) or "알 수 없음"}, detail="; ".join(report.reasons))
    return report
