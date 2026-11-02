"""네이버 블로그 발행 패키지 만들기(docs/PLATFORM_POLICY.md '네이버 블로그 A·B') — 원고 하나를 한 블로그(프로필)에 맞는 '복사 패키지'로 만든다.

네이버에는 공식 글쓰기 수단이 없어 **복사 패키지**를 쓴다: 제목·본문('서식 있는 글' 미리보기와 평문)·태그·이미지 자리 표시·발행 전 체크리스트를 만들어 주고,
사람이 네이버 글쓰기 화면에 붙여 넣어 직접 발행한 뒤 주소를 입력한다. 자동 로그인·자동 발행·쿠키·비공식 API 는 쓰지 않는다. 글을 AI 로 다시 쓰지도 않는다 —
블로그마다 말투·도입부를 맞추는 것은 사람이 원고(블로그별 변형)를 고치는 일이고, 여기서는 **같은 규칙으로 글을 다듬고 점검만** 한다:
  · 제목: 한 줄로 정리하고 프로필의 길이 상한을 넘으면 줄인다. 본문: Markdown 을 허용 태그만 있는 HTML 로 바꾸고(`render/markdown.py`) 긴 문단은 문장 끝에서 나눈다(짧은 문단 구성).
  · 이미지: 원고의 이미지(`Asset`)와 본문 속 `![](주소)` 를 제자리에 `[이미지 N] …` 표시로 둔다. 이미지는 직접 올린다. · 태그: 블로그 기본 태그 + 글의 태그를 정리·중복 제거해 상한까지.
  · AI 활용 고지문(프로필)을 글 끝에 붙인다. · 점검(warnings): 금지 표현·글 길이·제목 길이·빠진 이미지 설명·카테고리 매핑 없음.
결과는 값만 담은 `NaverPackage` 다(파일을 쓰지 않고 네트워크도 쓰지 않는다). 두 블로그의 글이 너무 비슷한지는 `check/similarity.py` 가 비교한다.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

from ..content.model import Asset
from ..content.profiles import NaverProfile, clean_line
from ..errors import AppError
from .markdown import html_to_text, markdown_blocks

MAX_IMAGES = 100
MAX_TAG_CHARS = 30
LABEL_CHARS = 80
_TAG_TEXT = re.compile(r"<[^>]*>")
_TOKEN = re.compile(r"<(/?)([A-Za-z0-9]+)[^>]*>|[^<]+")
_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s)")
_INLINE = frozenset({"strong", "em", "b", "i", "a"})
_PARAGRAPH = re.compile(r"^<p>(.*)</p>$", re.S)
_HTTPS = re.compile(r"^https://[^\s<>\"'`]{1,500}$")


@dataclass(frozen=True)
class NaverImage:
    number: int            # 1 부터(글 속 `[이미지 N]` 표시와 같다)
    label: str             # 표시에 쓰는 이름(설명 → 파일 이름 → 주소 순)
    filename: str          # 올릴 파일 이름('' 이면 주소로 된 이미지)
    url: str               # 원고에 주소로 쓴 이미지의 주소('' 이면 파일)
    alt: str
    position: int          # 그 앞에 오는 문단(블록) 수 — 0 이면 글 맨 앞


@dataclass(frozen=True)
class NaverPackage:
    profile_key: str
    title: str
    category: str                  # 이 블로그의 카테고리('' 이면 매핑 없음)
    tags: tuple
    body_html: str                 # '서식 있는 글' — 미리보기로 보이고 선택해 복사한다(허용 태그만)
    body_text: str                 # 평문(이미지 표시·고지문 포함)
    core_text: str                 # 이미지 표시·고지문을 뺀 본문 평문(비교용)
    intro: str                     # 도입부 — 본문의 첫 문단(제목·목록이 아니라 문단)
    images: tuple                  # NaverImage
    chars: int                     # 본문 글자 수(공백 제외, 이미지 표시·고지문 제외)
    paragraphs: int                # 문단 수(이미지 표시·고지문 제외)
    warnings: tuple
    checklist: tuple

    @property
    def tags_text(self):
        return " ".join("#" + tag for tag in self.tags)


def _incomplete(item, detail=""):
    return AppError("NAVER_PACKAGE_INCOMPLETE", {"항목": item}, detail=detail)


def _visible_length(inner):
    return len(html_lib.unescape(_TAG_TEXT.sub("", inner)))


def _split_paragraph(inner, limit):
    """긴 문단(<p> 안쪽 HTML)을 문장 끝에서 나눠 `limit` 글자 이하의 조각들로. 굵게·기울임·링크가 열려 있는 곳에서는 나누지 않고, 줄바꿈(`<br>`)이 든 문단은 나누지 않는다.
    한 문장이 `limit` 보다 길면 그 문장은 그대로 한 조각이다(글을 자르지 않는다)."""
    if "<br" in inner or _visible_length(inner) <= limit:
        return [inner]
    sentences, depth, start = [], 0, 0
    for match in _TOKEN.finditer(inner):
        tag = match.group(2)
        if tag:
            if tag.lower() in _INLINE:
                depth = max(depth + (-1 if match.group(1) else 1), 0)
            continue
        if depth:
            continue
        for end in _SENTENCE_END.finditer(match.group(0)):
            cut = match.start() + end.end()
            sentences.append(inner[start:cut].strip())
            start = cut
    sentences.append(inner[start:].strip())
    chunks, current = [], ""
    for sentence in (item for item in sentences if item):
        if current and _visible_length(current) + 1 + _visible_length(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks or [inner]


def _clean_tag(raw):
    """태그 하나를 정리한다: `#`·공백·앞뒤 구두점을 걷어 한 낱말로. 못 쓰면 None."""
    if not isinstance(raw, str):
        return None
    text = re.sub(r"\s+", "", clean_line(raw)).strip(",;#")
    return text if text and len(text) <= MAX_TAG_CHARS else None


def _merge_tags(profile, tags, warnings):
    merged, seen, dropped = [], set(), 0
    for raw in (*profile.default_tags, *tags):
        tag = _clean_tag(raw)
        if tag is None:
            if isinstance(raw, str) and clean_line(raw).lstrip("#").strip():
                dropped += 1
            continue
        if tag.casefold() not in seen:
            seen.add(tag.casefold())
            merged.append(tag)
    if dropped:
        warnings.append(f"쓸 수 없는 태그 {dropped}개를 뺐습니다(길이는 {MAX_TAG_CHARS}자 이하여야 합니다).")
    if len(merged) > profile.max_tags:
        warnings.append(f"태그가 {len(merged)}개라 앞의 {profile.max_tags}개만 남겼습니다.")
        merged = merged[:profile.max_tags]
    return tuple(merged)


def _short(text, limit=LABEL_CHARS):
    text = clean_line(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _images(assets, found, block_count, warnings):
    """원고의 이미지(Asset)와 본문 속 주소 이미지를 자리 순으로 번호를 매긴다. 같은 자리면 원고의 이미지가 먼저."""
    try:
        assets = None if isinstance(assets, (str, bytes)) else tuple(assets)
    except TypeError:
        assets = None
    if assets is None or len(assets) + len(found) > MAX_IMAGES or not all(isinstance(asset, Asset) for asset in assets):
        raise AppError("CONTENT_INVALID", {"항목": "이미지"})
    items = []
    for asset in assets:
        place = asset.position
        if place > block_count:
            warnings.append(f"이미지 「{_short(asset.filename)}」 의 자리(문단 {place})가 글 끝을 넘어 맨 뒤로 옮겼습니다.")
            place = block_count
        items.append((place, asset.filename, "", asset.alt))
    for alt, url, place in found:
        if not _HTTPS.match(url):
            warnings.append(f"본문의 이미지 주소가 https 가 아니라 뺐습니다: {_short(url, 40)}")
            continue
        items.append((place, "", url, alt))
    items.sort(key=lambda item: item[0])                  # 같은 자리면 처음 줄 세운 순서(원고의 이미지가 먼저)가 그대로다 — sort 는 순서를 지킨다
    images = []
    for number, (place, filename, url, alt) in enumerate(items, start=1):
        images.append(NaverImage(number, _short(alt or filename or url), filename, url, clean_line(alt), place))
        if not alt:
            warnings.append(f"이미지 {number}번(「{_short(filename or url, 40)}」)에 설명이 없습니다.")
    return tuple(images)


def _marker(image):
    where = f"파일 {image.filename}" if image.filename else f"주소 {image.url}"
    detail = f" — {image.alt}" if image.alt else ""
    return f"<p>[이미지 {image.number}] {html_lib.escape(where)}{html_lib.escape(detail)}</p>"


def build_package(profile, *, title, body, tags=(), assets=(), category="", ai_assisted=True):
    """원고 하나를 `profile`(네이버 A 또는 B)에 맞는 복사 패키지로. 제목·본문·태그가 비면 NAVER_PACKAGE_INCOMPLETE, 이미지 자료의 모양이 틀리면 CONTENT_INVALID."""
    if not isinstance(profile, NaverProfile):
        raise AppError("CONTENT_INVALID", {"항목": "블로그 프로필"})
    title_text = clean_line(title) if isinstance(title, str) else ""
    if not title_text:
        raise _incomplete("제목")
    if not isinstance(body, str) or not body.strip():
        raise _incomplete("본문")
    warnings = []
    blocks, found = markdown_blocks(body)
    if not blocks:
        raise _incomplete("본문", "글자가 하나도 남지 않았다")
    if len(title_text) > profile.max_title_chars:
        cut = title_text[:profile.max_title_chars - 1].rstrip() + "…"
        warnings.append(f"제목이 {len(title_text)}자라 {profile.max_title_chars}자로 줄였습니다. 직접 고쳐 쓰세요.")
        title_text = cut
    tag_tuple = _merge_tags(profile, tags, warnings)
    if not tag_tuple:
        raise _incomplete("태그")
    images = _images(assets, found, len(blocks), warnings)

    shaped, origin = [], []                                # 짧은 문단으로 나눈 블록과, 각 조각이 원고의 몇 번째 블록에서 왔는가
    for index, block in enumerate(blocks, start=1):
        paragraph = _PARAGRAPH.match(block)
        pieces = [f"<p>{part}</p>" for part in _split_paragraph(paragraph.group(1), profile.paragraph_max_chars)] if paragraph else [block]
        shaped.extend(pieces)
        origin.extend([index] * len(pieces))
    core_html = "".join(shaped)
    core_text = html_to_text(core_html)
    intro = next((html_to_text(piece).strip() for piece in shaped if piece.startswith("<p>")), "")
    chars = len("".join(core_text.split()))

    out = []
    placed = 0
    for index, piece in zip(origin, shaped):                # 이미지는 원고의 블록 사이(그 앞에 오는 블록 수)에 둔다
        while placed < len(images) and images[placed].position < index:
            out.append(_marker(images[placed]))
            placed += 1
        out.append(piece)
    out.extend(_marker(image) for image in images[placed:])
    if ai_assisted:
        disclosure = profile.disclosure_text()
        if disclosure not in core_text:
            out.append(f"<p>{html_lib.escape(disclosure)}</p>")
    body_html = "".join(out)

    for phrase in profile.forbidden_phrases:
        for where, text in (("제목", title_text), ("본문", core_text)):
            if phrase.casefold() in text.casefold():
                warnings.append(f"금지 표현 「{phrase}」 이(가) {where}에 있습니다.")
    if chars < profile.min_chars:
        warnings.append(f"본문이 {chars}자로 이 블로그 기준({profile.min_chars}~{profile.max_chars}자)보다 짧습니다.")
    if chars > profile.max_chars:
        warnings.append(f"본문이 {chars}자로 이 블로그 기준({profile.min_chars}~{profile.max_chars}자)보다 깁니다.")
    mapped = profile.category_for(category) if category else ""
    if category and not mapped:
        warnings.append(f"분류 「{_short(category, 40)}」 에 맞는 이 블로그의 카테고리가 없습니다. 직접 고르세요.")

    checklist = [
        "- [ ] 미리보기에서 제목과 본문을 처음부터 끝까지 읽습니다",
        "- [ ] 사실·수치·고유명사는 직접 확인합니다(앱은 사실 확인을 하지 않습니다)",
    ]
    if images:
        spec = f" — 대표 이미지 규격: {profile.image_spec}" if profile.image_spec else ""
        checklist.append(f"- [ ] 이미지 {len(images)}장을 올려 `[이미지 N]` 표시 자리에 놓고 표시 글을 지웁니다{spec}")
    checklist.append(f"- [ ] 태그 {len(tag_tuple)}개를 입력합니다")
    if mapped:
        checklist.append(f"- [ ] 카테고리 「{mapped}」 을(를) 고릅니다")
    if ai_assisted:
        checklist.append("- [ ] AI 활용 고지문을 확인합니다(이미지·영상을 AI 로 만들었거나 고쳤다면 그것도 표기하는 것을 권장합니다)")
    checklist.append("- [ ] 다른 네이버 블로그와 글이 겹치지 않는지 비교 결과를 확인합니다(많이 비슷하면 직접 승인해야 합니다)")
    checklist.append(f"- [ ] 「{profile.display_name}」 에 글쓰기 화면을 열어 붙여 넣고 직접 발행한 뒤, 발행한 글의 주소를 입력합니다")

    return NaverPackage(
        profile.key, title_text, mapped, tag_tuple, body_html, html_to_text(body_html), core_text, intro, images, chars, sum(1 for piece in shaped if piece.startswith("<p>")),
        tuple(warnings), tuple(checklist))
