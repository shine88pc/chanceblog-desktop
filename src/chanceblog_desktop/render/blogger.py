"""Blogger 글 만들기(순수 변환) — 승인한 원고를 Blogger 초안으로 보낼 **제목·HTML·라벨** 로 바꾼다(BLOGGER 설계서 3.10, 결정 D-770). 접속도 파일 쓰기도 없다.

기본은 기존 변환기(`render/markdown.py` — 허용 태그 `p`·`h2`–`h4`·`ul`·`ol`·`li`·`strong`·`b`·`em`·`i`·`br`·`blockquote` 와 https 링크만)이고, 여기서 더하는 것은 **고정된 모양의 블록 둘**뿐이다:
  · 대표 사진 블록 — 가운데 정렬 `div` 안에 `img` 와 사진작가 출처 한 줄(블로그 저장소 `pipeline/main_image.py` 의 사진 블록과 같은 모양 — 사이트 글과 Blogger 글의 형식이 같다)
  · 본문 사진 블록 — 가운데 정렬 `div` 안의 `img` 하나
두 블록의 값은 모두 이스케이프하고 `style` 은 상수 글 하나뿐이다(광고 코드·스크립트·`iframe`·`embed`·템플릿은 만들지도 않는다).

**사진은 이 PC 를 떠나지 않는다**(운영자 확인 018): 이 PC 의 사진 파일(`Asset`)이나 인터넷 주소가 아닌 사진 표기(`C:\\…`·`file:`·상대 경로·`data:` 등)가 하나라도 있으면 `BLOGGER_IMAGE_UNSUPPORTED` 로 **멈춘다**.
파일 이름·경로는 HTML·오류·로그 어디에도 쓰지 않는다(오류에는 사진 **개수**뿐). 인터넷 주소의 사진은 허용 호스트 표(`ALLOWED_IMAGE_HOSTS`)에 있는 https 주소만 `img` 로 넣고, 그 밖은 넣지 않고 알림(`notes`)만 남긴다.
링크는 글의 출처 주소(`project.references`)의 호스트로만 열어 둔다 — 출처가 없으면 링크는 모두 글자로만 남는다(`allow_links=True` 에 호스트 표가 비면 아무 https 주소나 열리므로 표가 비면 아예 닫는다).

결과는 같은 입력이면 같은 출력이다(저널의 해시·중복 확인이 이것에 기댄다). 마지막에 **만든 HTML 을 한 번 더 훑어**(`check_markup`) 허용한 태그·속성·값 모양 밖이면 보내지 않는다(변환기에 틈이 있어도 나가지 않는 마지막 방어).
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

from ..errors import AppError
from .markdown import markdown_blocks

MAX_TITLE = 200                       # `content.model.MAX_TITLE` 와 같다(승인한 글의 제목 상한)
MAX_LABELS = 10                       # `render.pages.MAX_TAGS` 와 같다
MAX_LABEL = 40                        # `render.pages.MAX_TAG` 와 같다
MAX_ALT = 300
MAX_IMAGE_URL = 500
MAX_HTML_BYTES = 500_000              # 승인한 글의 HTML 상한(요청 본문 1 MiB 안에 여유 있게 들어간다 — 따옴표 이스케이프가 두 배가 돼도)
ALLOWED_IMAGE_HOSTS = ("images.unsplash.com",)     # 글에 넣을 수 있는 사진 호스트(소스 상수 표 — 설정으로 더하지 않는다)
LANGS = ("ko", "en")
DEFAULT_ALT = {"ko": "대표 사진", "en": "Featured photo"}
BLOCK_STYLE = "text-align:center;margin:0 0 1.5em;"
IMAGE_STYLE = "max-width:100%;height:auto;"
LINK_REL = "noopener nofollow"
LINK_TARGET = "_blank"
ALLOWED_TAGS = ("p", "h2", "h3", "h4", "ul", "ol", "li", "strong", "b", "em", "i", "br", "blockquote", "a", "div", "img", "small")
VOID_TAGS = ("br", "img")
BODY_REL = ("nofollow noopener", "noopener nofollow")            # 변환기가 본문 링크에 붙이는 `rel`(순서는 소독기가 정한다)

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
_SPACES = re.compile(r"\s+")
_LABEL_SEPARATORS = re.compile(r"[,，、;；]")
_HOST = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")


def _invalid(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": item}, detail=detail)


@dataclass(frozen=True)
class BloggerPost:
    """Blogger 로 보낼 글 — `title`(글자 그대로, 이스케이프하지 않는다 — API 가 글자로 받는다)·`html`·`labels`(최대 10개)·`notes`(변환 중의 알림, 화면에 보인다)."""
    title: str
    html: str
    labels: tuple
    notes: tuple = ()


@dataclass(frozen=True)
class HeroImage:
    """대표 사진 — `url` 은 허용 호스트의 https 주소, `credit` 은 `ui.core.attribution.PhotoCredit` 같은 값(`photographer_name`·`profile_link()`·`photo_link()`)이다."""
    url: str
    credit: object
    alt: str = ""


# ---- 제목·라벨 -----------------------------------------------------------------------------------------------------------------------
def clean_title(value):
    """제목 → 앞뒤 공백을 뗀 한 줄. 비었거나 200자를 넘거나 `<`·`>`·줄바꿈·제어 문자가 있으면 CONTENT_INVALID(발행 전 검사가 이미 막는 것을 한 번 더 지킨다)."""
    if not isinstance(value, str):
        raise _invalid("제목")
    text = value.strip()
    if not text or len(text) > MAX_TITLE or _CONTROL.search(text) or "<" in text or ">" in text:
        raise _invalid("제목")
    return text


def clean_labels(tags):
    """태그 → 라벨 튜플(쉼표류·제어 문자를 공백으로 바꾸고 공백을 줄여 중복을 뺀다). 10개를 넘거나 40자를 넘는 라벨이 있으면 CONTENT_INVALID — 승인한 글의 라벨을 몰래 자르지 않는다."""
    if isinstance(tags, (str, bytes)) or tags is None:
        raise _invalid("라벨")
    labels, seen = [], set()
    for tag in tags:
        if not isinstance(tag, str):
            raise _invalid("라벨")
        text = _SPACES.sub(" ", _LABEL_SEPARATORS.sub(" ", _CONTROL.sub(" ", tag))).strip()
        if not text:
            continue
        if len(text) > MAX_LABEL or "<" in text or ">" in text:
            raise _invalid("라벨")
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            labels.append(text)
    if len(labels) > MAX_LABELS:
        raise _invalid("라벨")
    return tuple(labels)


# ---- 사진 -----------------------------------------------------------------------------------------------------------------------------
def classify_image(url, hosts=ALLOWED_IMAGE_HOSTS):
    """사진 주소 하나 → 'ok'(허용 호스트의 https 인터넷 주소) · 'blocked'(인터넷 주소지만 쓸 수 없다 — http·허용하지 않은 호스트·로그인 정보·포트·너무 긴 주소) · 'local'(인터넷 주소가 아니다 — 이 PC 의 파일·상대 경로·`file:`·`data:`·드라이브 글자 등).
    판정은 글자만 본다(파일 시스템을 읽지 않고 이름을 되풀이하지도 않는다)."""
    if not isinstance(url, str) or not url.strip():
        return "local"
    text = url.strip()
    if "\\" in text or _CONTROL.search(text) or re.match(r"^[A-Za-z]:", text):
        return "local"                                         # 윈도 경로·드라이브 글자(`C:`)·제어 문자 — 인터넷 주소가 아니다
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return "local"
    if parts.scheme.lower() not in ("http", "https") or not host:
        return "local"                                         # 상대 경로·`file:`·`data:`·`javascript:`·`//호스트` 모두 여기서 '이 PC 의 것' 으로 본다(보내지 않는 쪽)
    if (parts.scheme.lower() != "https" or parts.username or parts.password or port not in (None, 443) or parts.fragment or len(text) > MAX_IMAGE_URL
            or any(ch.isspace() for ch in text) or not text.isascii() or host not in {item.lower() for item in hosts} or _HOST.fullmatch(host) is None):
        return "blocked"
    return "ok"


def _escape(value):
    return html_lib.escape(value, quote=True)


def _alt_text(value, lang):
    text = _SPACES.sub(" ", _CONTROL.sub(" ", value or "")).strip()[:MAX_ALT]
    return text or DEFAULT_ALT[lang]


def image_block(url, alt, lang):
    """본문 사진 블록(고정 모양)."""
    return f'<div style="{BLOCK_STYLE}"><img src="{_escape(url)}" alt="{_escape(_alt_text(alt, lang))}" style="{IMAGE_STYLE}"></div>'


def hero_block(hero, lang, hosts=ALLOWED_IMAGE_HOSTS):
    """대표 사진 블록(고정 모양) — 사진 + `Photo by <작가> on Unsplash` 한 줄(두 링크는 Unsplash 주소 + 앱 이름 `utm`, 값은 `PhotoCredit` 이 이미 검사했다)."""
    if classify_image(getattr(hero, "url", ""), hosts) != "ok":
        raise _invalid("대표 사진 주소")
    credit = hero.credit
    try:
        name, profile, photo = credit.photographer_name, credit.profile_link(), credit.photo_link()
    except (AttributeError, ValueError) as error:
        raise _invalid("사진 출처", detail=type(error).__name__) from None
    if not all(isinstance(value, str) and value for value in (name, profile, photo)):
        raise _invalid("사진 출처")
    link = f'rel="{LINK_REL}" target="{LINK_TARGET}"'
    return (f'<div style="{BLOCK_STYLE}"><img src="{_escape(hero.url)}" alt="{_escape(_alt_text(hero.alt, lang))}" style="{IMAGE_STYLE}">'
            f'<br><small>Photo by <a href="{_escape(profile)}" {link}>{_escape(name)}</a> on <a href="{_escape(photo)}" {link}>Unsplash</a></small></div>')


# ---- 만든 HTML 을 한 번 더 훑기 ------------------------------------------------------------------------------------------------------------
def _https_host(value):
    try:
        parts = urlsplit(value)
        return parts.scheme == "https" and bool(parts.hostname) and not parts.username and not parts.password and parts.port in (None, 443)
    except ValueError:
        return False


class _MarkupChecker(HTMLParser):
    """허용한 태그·속성·값 모양만 남았는지 훑는다 — 태그마다 속성 규칙이 정해져 있고(아래 `_attribute_problem`) 주석·선언·처리 명령은 하나도 없어야 한다."""

    def __init__(self, hosts):
        super().__init__(convert_charrefs=True)
        self.hosts = {item.lower() for item in hosts}
        self.problems = []

    def _note(self, label):
        if label not in self.problems:
            self.problems.append(label)

    def _attribute_problem(self, tag, name, value):
        if tag == "a" and name == "href":
            return not _https_host(value or "")
        if tag == "a" and name == "rel":
            return value not in BODY_REL
        if tag == "a" and name == "target":
            return value != LINK_TARGET
        if tag == "div" and name == "style":
            return value != BLOCK_STYLE
        if tag == "img" and name == "style":
            return value != IMAGE_STYLE
        if tag == "img" and name == "src":
            return classify_image(value or "", self.hosts) != "ok"
        if tag == "img" and name == "alt":
            return value is None or len(value) > MAX_ALT
        return True

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self._note(f"태그 {tag}")
            return
        seen = set()
        for name, value in attrs:
            if name in seen or self._attribute_problem(tag, name, value):
                self._note(f"{tag} 의 속성 {name}")
            seen.add(name)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            self._note(f"닫는 태그 {tag}")

    def handle_comment(self, data):
        self._note("주석")

    def handle_decl(self, decl):
        self._note("선언")

    def handle_pi(self, data):
        self._note("처리 명령")

    def unknown_decl(self, data):
        self._note("선언")


def check_markup(html, hosts=ALLOWED_IMAGE_HOSTS):
    """HTML → 허용 밖인 것의 이름 목록(없으면 빈 목록). 이름은 태그·속성 이름뿐이고 값은 담지 않는다."""
    checker = _MarkupChecker(hosts)
    try:
        checker.feed(html)
        checker.close()
    except Exception:                                          # noqa: BLE001 - 읽을 수 없는 HTML 은 '허용 밖' 이다(fail closed)
        checker._note("읽을 수 없는 HTML")
    return checker.problems


# ---- 변환 ------------------------------------------------------------------------------------------------------------------------------
def _reference_hosts(references):
    hosts = []
    for url in references or ():
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
        except ValueError:
            continue
        if parts.scheme == "https" and host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def render_blogger_post(project, lang, *, hero=None, tags=(), image_hosts=ALLOWED_IMAGE_HOSTS):
    """승인한 글 → `BloggerPost`. `project` 는 `ContentProject`(제목 `title`·원고 `source_content`·출처 `references`·이 PC 의 사진 `assets`)처럼 생긴 값이다.
    이 PC 의 사진이 있으면 `BLOGGER_IMAGE_UNSUPPORTED`, 제목·라벨·크기가 한도 밖이거나 만든 HTML 이 허용 밖이면 `CONTENT_INVALID` — 어느 오류에도 사진 이름·경로·본문 글은 없다."""
    if lang not in LANGS:
        raise _invalid("언어")
    title = clean_title(getattr(project, "title", None))
    labels = clean_labels(tags)
    source = getattr(project, "source_content", None)
    if not isinstance(source, str) or not source.strip():
        raise _invalid("본문")
    hosts = _reference_hosts(getattr(project, "references", ()))
    blocks, found = markdown_blocks(source, allow_links=bool(hosts), allowed_hosts=hosts)
    notes = []
    kept, local = [], len(getattr(project, "assets", ()) or ())
    for alt, url, position in found:
        verdict = classify_image(url, image_hosts)
        if verdict == "local":
            local += 1
        elif verdict == "ok":
            kept.append((image_block(url.strip(), alt, lang), position))
        else:
            notes.append("글 속 사진 하나는 허용한 사진 주소가 아니라서 넣지 않았어요.")
    if local:
        raise AppError("BLOGGER_IMAGE_UNSUPPORTED", {"사진 수": str(local)})            # 이 PC 의 사진 — 여기서 멈춘다(이름·경로는 어디에도 쓰지 않는다)
    everything = "".join(markdown_blocks(source, allow_links=True)[0]).count("<a ")          # 호스트 표를 비우면 모든 https 링크가 열린다 — 우리가 닫은 만큼이 '글자로만 남긴' 링크다
    shown = "".join(blocks).count("<a ")
    if everything > shown:
        notes.append(f"링크 {everything - shown}개는 출처 주소가 아니라서 글자로만 남겼어요.")
    pieces = []
    if hero is not None:
        pieces.append(hero_block(hero, lang, image_hosts))
    kept.sort(key=lambda item: item[1])
    cursor = 0
    for index, block in enumerate(blocks):
        while cursor < len(kept) and kept[cursor][1] <= index:
            pieces.append(kept[cursor][0])
            cursor += 1
        pieces.append(block)
    pieces.extend(item[0] for item in kept[cursor:])
    html = "".join(pieces)
    if not html.strip() or len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise _invalid("본문 크기")
    problems = check_markup(html, image_hosts)
    if problems:
        raise _invalid("Blogger 글", detail="허용하지 않은 모양: " + ", ".join(problems[:5]))
    return BloggerPost(title, html, labels, tuple(dict.fromkeys(notes)))


__all__ = ["ALLOWED_IMAGE_HOSTS", "ALLOWED_TAGS", "BLOCK_STYLE", "BloggerPost", "HeroImage", "IMAGE_STYLE", "MAX_HTML_BYTES", "MAX_LABEL", "MAX_LABELS", "MAX_TITLE", "check_markup", "classify_image",
           "clean_labels", "clean_title", "hero_block", "image_block", "render_blogger_post"]
