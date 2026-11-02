"""GitHub Pages(Chance 블로그) 글 만들기 — 원고를 chanceblog 저장소에 넣을 파일(경로와 내용)로 만든다. 순수 함수라 파일을 쓰지 않는다
(쓰기·commit·push 는 발행 묶음이 한다). docs/ARCHITECTURE.md §3.

형식은 chanceblog 의 글 생성기(`generator.py`)가 지금 쓰는 모양과 같다: `_posts/<분야>/YYYY-MM-DD-KR|EN-HHMMSS.md`(한국 시각), 머리말은
layout → title → category → tags → lang → image → (description) → (source_name·source_url·source_domain) 순서의 한 줄 한 키이고,
title·category·tags·image·description·source_* 는 한 줄 JSON, 본문에는 대표 이미지(`![Thumbnail](…)`)가 한 번은 있다. 시험이 실제 글 두 편(한글·영어)과
글자 단위로 같은지 확인한다. chanceblog 쪽 규칙이 바뀌면 이쪽도 같은 PR 에서 맞춘다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from ..errors import AppError

KST = timezone(timedelta(hours=9))
LANG_PREFIX = {"ko": "KR", "en": "EN"}
MAX_CATEGORY = 100
MAX_TAGS = 10
MAX_TAG = 40
MAX_DESCRIPTION = 300
AUTO_DESCRIPTION_CHARS = 155
MAX_HEADER_LINE = 2000

# YAML 이 줄바꿈으로 읽는 U+0085·U+2028·U+2029 는 한 줄 JSON 안에서도 \uXXXX 로 쓴다(generator._json_line 과 같다)
_LINE_BREAKS = {0x85: "\\u0085", 0x2028: "\\u2028", 0x2029: "\\u2029"}
# YAML 이 읽지 못하는 글자(제어 문자, U+0085·U+2028·U+2029 포함). 탭과 줄바꿈은 허용(CR 은 먼저 줄바꿈으로 바꾼다)
_UNPRINTABLE = re.compile(r"[^\x09\x0a\x20-\x7e\xa0-\U00002027\U0000202a-퟿\ue000-�\U00010000-\U0010ffff]")
# 한 줄 값(제목·분야·태그·설명·출처)에 넣을 수 있는 글자: 탭과 U+0085·U+2028·U+2029 는 한 줄 JSON 이 \uXXXX 로 이스케이프하므로 받고, 줄바꿈과 나머지 제어 문자는 거절한다
_VALUE_UNSAFE = re.compile(r"[^\x09\x20-\x7e\xa0-\U00002027\U0000202a-퟿\ue000-�\U00010000-\U0010ffff\u0085\u2028\u2029]")
_HEADER_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]|\Z)")
_FENCE = re.compile(r"-{3,}[ \t]*")
_BODY_RESIDUE = re.compile(r"(?:layout|title|category|tags|lang|image|description|published|date|permalink|slug|source_name|source_url|source_domain)[ \t]*:")
_IMAGE_LINE = re.compile(r"(?m)^!\[[^\]]*\]\(")
_WINDOWS_RESERVED = re.compile(r'[<>:"|?*]')
REQUIRED_KEYS = ("layout", "title", "category", "lang", "image")


@dataclass(frozen=True)
class PagesPost:
    path: str        # 저장소 루트 기준 경로(/ 구분): _posts/<분야>/YYYY-MM-DD-KR-HHMMSS.md
    text: str        # 파일 내용(머리말 + 본문, LF, 끝에 줄바꿈 하나)
    category: str
    lang: str


def _invalid(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": item}, detail=detail)


def json_line(value):
    """한 줄 JSON(한글은 그대로, YAML 이 줄바꿈으로 읽는 글자는 이스케이프)."""
    return json.dumps(value, ensure_ascii=False).translate(_LINE_BREAKS)


def _one_line(value, item, *, limit, required=True):
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit or _VALUE_UNSAFE.search(value):
        raise _invalid(item)
    return value.strip()


def _https_url(value, item, *, schemes=("https",)):
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value) or _UNPRINTABLE.search(value):
        raise _invalid(item)
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        raise _invalid(item) from None
    if parts.scheme not in schemes or not host or parts.username or parts.password:
        raise _invalid(item)
    return value


def category_dir(category, lang):
    """분야 → 폴더 이름. chanceblog 생성기의 `safe_category_dir` 규칙 + Windows 에서 만들 수 없는 글자(`<>:"|?*`)와 끝의 점·공백 정리."""
    name = re.sub(r"[\x00-\x1f/\\]+", "-", str(category).strip())
    name = re.sub(r"\.\.+", ".", name)
    name = _WINDOWS_RESERVED.sub("-", name).strip(" .")
    return name or f"{LANG_PREFIX[lang]} - Uncategorized"


def post_path(category, lang, now):
    """`_posts/<분야 폴더>/YYYY-MM-DD-KR-HHMMSS.md` — 시각은 한국 시각이고, 시각 정보가 있는 datetime 이어야 한다."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise _invalid("시각")
    stamp = now.astimezone(KST)
    return f"_posts/{category_dir(category, lang)}/{stamp:%Y-%m-%d}-{LANG_PREFIX[lang]}-{stamp:%H%M%S}.md"


def auto_description(markdown, max_chars=AUTO_DESCRIPTION_CHARS):
    """본문에서 뽑는 한 줄 설명 — 마크다운 표시를 걷어낸 첫 60자 이상 문단을 155자 안에서 단어 끝으로 자르고 '…' 를 붙인다(chanceblog 와 같은 규칙)."""
    for paragraph in re.split(r"\n\s*\n", markdown):
        paragraph = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", paragraph)
        paragraph = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", paragraph)
        paragraph = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s*|>\s*)", "", paragraph)
        paragraph = re.sub(r"[*_`~]", "", paragraph)
        paragraph = re.sub(r"<[^>]+>", " ", paragraph)
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if len(paragraph) >= 60:
            if len(paragraph) > max_chars:
                paragraph = paragraph[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
            return paragraph
    return ""


def _tags(values):
    if isinstance(values, (str, bytes)) or len(values) > MAX_TAGS * 4:
        raise _invalid("태그")
    seen = []
    for value in values:
        tag = _one_line(value, "태그", limit=MAX_TAG)
        if tag.lower() not in [item.lower() for item in seen]:
            seen.append(tag)
    if len(seen) > MAX_TAGS:
        raise _invalid("태그")
    return seen


def _body(text):
    body = str(text).lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if _UNPRINTABLE.search(body):
        raise _invalid("본문", detail="YAML 이 읽지 못하는 제어 문자가 있다")
    body = body.strip("\n").rstrip()
    first = [line for line in body.split("\n") if line.strip()][:3]
    if first and (_FENCE.fullmatch(first[0].rstrip()) or any(_BODY_RESIDUE.match(line) for line in first)):
        raise _invalid("본문 머리", detail="본문이 머리말처럼 시작한다")
    return body


def _source(source, lang, project_title):
    name = _one_line(source.get("name"), "출처 이름", limit=200)
    url = _https_url(source.get("url"), "출처 주소", schemes=("http", "https"))
    title = _one_line(source.get("title") or project_title, "출처 제목", limit=300)
    return name, url, urlsplit(url).hostname, title


def render_pages_post(project, *, category, lang, image_url, tags=(), description=None, source=None, now=None):
    """승인된 원고(ContentProject) → chanceblog 에 넣을 글 한 편. 모든 값 검사에 실패하면 CONTENT_INVALID(어느 항목인지 포함)로 거절한다.

    - category: 분야 이름(머리말에 그대로, 폴더 이름은 안전하게 고친 것). lang: ko|en. image_url: https 대표 이미지 주소.
    - description: 비우면 본문에서 뽑는다(뽑을 문단이 없으면 줄을 쓰지 않는다). source: {"name","url","title"?} — 있으면 출처 세 줄과 본문 끝 출처 목록.
    - now: 시각 정보가 있는 datetime(없으면 지금) — 파일 이름의 날짜·시각이 된다.
    """
    if lang not in LANG_PREFIX:
        raise _invalid("언어")
    category_text = _one_line(category, "분야", limit=MAX_CATEGORY)
    image = _https_url(image_url, "대표 이미지 주소")
    title = _one_line(project.title, "제목", limit=200)
    tag_list = _tags(tags)
    body = _body(project.source_content)
    path = post_path(category_text, lang, datetime.now(KST) if now is None else now)
    if description is None or description == "":
        description = auto_description(body)
    else:
        description = _one_line(description, "설명", limit=MAX_DESCRIPTION)
    src = _source(source, lang, project.title) if source else None

    if not _IMAGE_LINE.search(body):
        body += f"\n\n![Thumbnail]({image})"
    if src and src[1] not in body:
        heading = "## 출처" if lang == "ko" else "## Sources"
        body += f"\n\n{heading}\n- [{src[0]}: {src[3]}]({src[1]})"

    header = ["---", "layout: post", f"title: {json_line(title)}", f"category: {json_line(category_text)}", f"tags: {json_line(tag_list)}", f"lang: {lang}", f"image: {json_line(image)}"]
    if description:
        header.append(f"description: {json_line(description)}")
    if src:
        header += [f"source_name: {json_line(src[0])}", f"source_url: {json_line(src[1])}", f"source_domain: {json_line(src[2])}"]
    header.append("---")
    text = "\n".join(header) + "\n\n" + body + "\n"
    problems = front_matter_problems(text)
    if problems:
        raise _invalid("머리말", detail="; ".join(problems))
    return PagesPost(path, text, category_text, lang)


def front_matter_problems(text):
    """글 한 편의 머리말·본문 머리를 검사해 문제 문장 목록을 돌려준다(비어 있으면 정상). 값은 문장에 넣지 않는다. chanceblog 의 `front_matter_problems` 중 이 앱이 쓰는 부분."""
    text = str(text)
    if text.startswith("\ufeff"):
        return ["글이 BOM 으로 시작함"]
    lines = text.split("\n")
    if lines[0] != "---":
        return ["첫 줄이 정확히 `---` 가 아님"]
    end = next((i for i in range(1, len(lines)) if _FENCE.fullmatch(lines[i])), None)
    if end is None:
        return ["머리말을 닫는 `---` 줄이 없음"]
    problems = []
    if lines[end] != "---":
        problems.append("머리말을 닫는 줄이 정확히 `---` 가 아님")
    header, body = lines[1:end], lines[end + 1:]
    joined = "\n".join(header)
    if "\r" in joined:
        problems.append("머리말에 CR 줄바꿈이 섞여 있음")
    if _UNPRINTABLE.search(joined):
        problems.append("머리말에 YAML 이 읽지 못하는 글자가 있음")
    keys = {}
    for line in header:
        if not line.strip():
            continue
        found = _HEADER_KEY.match(line)
        if not found:
            problems.append("`키: 값` 한 줄 모양이 아닌 줄이 있음")
            continue
        key, value = found.group(1), line[found.end():].strip()
        if key in keys:
            problems.append(f"`{key}` 키가 두 번 나옴")
        keys[key] = value
        if len(line) > MAX_HEADER_LINE:
            problems.append(f"`{key}` 줄이 너무 김")
        if not value:
            problems.append(f"`{key}` 값이 비어 있음")
    problems += [f"필수 키 `{key}` 줄이 없음" for key in REQUIRED_KEYS if key not in keys]
    if keys.get("layout") not in (None, "post"):
        problems.append("`layout` 값이 post 가 아님")
    if keys.get("lang") not in (None, "ko", "en"):
        problems.append("`lang` 값이 ko·en 이 아님")
    for key in ("title", "category", "image", "description", "source_name", "source_url", "source_domain"):
        if key in keys and keys[key]:
            try:
                value = json.loads(keys[key])
            except ValueError:
                value = None
            if not isinstance(value, str) or not value.strip():
                problems.append(f"`{key}` 값이 한 줄 JSON 문자열이 아님")
    if keys.get("tags"):
        try:
            tags = json.loads(keys["tags"])
        except ValueError:
            tags = None
        if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
            problems.append("`tags` 값이 한 줄 JSON 목록이 아님")
    first = [line for line in body if line.strip()][:3]
    if first and (_FENCE.fullmatch(first[0].rstrip()) or any(_BODY_RESIDUE.match(line) for line in first)):
        problems.append("본문이 울타리 줄이나 머리말 줄로 시작함")
    return problems
