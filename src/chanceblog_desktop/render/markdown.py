"""Markdown ↔ 안전한 HTML 변환(docs/ARCHITECTURE.md §5 `render/`). Blogger HTML·네이버 서식 있는 글·미리보기가 같은 변환을 쓴다.

지원하는 Markdown: 제목(`#`~`######`), 문단, 줄바꿈(줄 끝의 공백 둘·역슬래시), 목록(`-`·`*`·`+`·`1.`·`1)`, 4단계 중첩까지), 인용(`>`), 굵게(`**`·`__`)·기울임(`*`·`_`),
코드 조각·코드 블록(글자 그대로 보이게 일반 글로), 링크, 이미지, 가로줄. 나머지(표·각주·HTML 조각 등)는 글자 그대로 둔다 — 원고 속 `<script>` 같은 HTML 은 해석하지 않고 글자로 보인다.
결과 HTML 은 `pipeline.gates.sanitize_html`(허용 태그 p·h2~h4·ul·ol·li·strong·b·em·i·br·blockquote 만)을 한 번 더 거친다 — 변환기에 틈이 있어도 허용 밖 태그·속성은 나갈 수 없다.
이미지는 HTML 에 넣지 않고(`markdown_images` 로 따로 뽑는다 — 플랫폼마다 올리는 방법이 다르다), 링크는 `allow_links` 이고 https 이며 `allowed_hosts` 에 든 주소만 남긴다.
어떤 입력에도 예외 없이 끝난다(너무 큰 입력만 CONTENT_INVALID). 한 문단이 8000자를 넘으면 그 문단은 굵게·링크·코드 조각을 해석하지 않고 글로만 둔다(최악의 경우 시간이 폭증하지 않게).
"""
from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from ..core import use_vendored_core
from ..errors import AppError

use_vendored_core()
from pipeline.gates import sanitize_html  # noqa: E402  (vendor/ 경로를 먼저 올려야 한다)

MAX_CHARS = 2_000_000
INLINE_LIMIT = 8000
MAX_DEPTH = 5            # 인용 안의 인용 깊이
MAX_LIST_DEPTH = 4       # 목록 중첩 깊이(더 깊은 것은 같은 단계로 본다)

_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PRIVATE = re.compile("[\ue000-\uf8ff]")           # 이 변환기가 내부 표지로 쓰는 글자 — 입력에서 먼저 지운다
_HARD = "\ue010"                                    # 강제 줄바꿈 표지

_BLANK = re.compile(r"^[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[^\n]*$")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_QUOTE = re.compile(r"^ {0,3}>[ ]?(.*)$")
_BULLET = re.compile(r"^( *)([-*+])[ \t]+(.*)$")
_ORDERED = re.compile(r"^( *)(\d{1,9})[.)][ \t]+(.*)$")

_ESCAPABLE = re.compile(r"\\([!-/:-@\[-`{-~])")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
_URL = r"((?:[^\s()]|\([^\s()]*\))*)"                # 주소: 공백 없음, 한 단계의 괄호 쌍은 허용(`javascript:alert(1)`·위키 주소)
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(\s*" + _URL + r"(?:\s+\"[^\"]*\")?\s*\)")
_LINK = re.compile(r"\[((?:[^\[\]\\\n]|\\.)*)\]\(\s*" + _URL + r"(?:\s+\"[^\"]*\")?\s*\)")
_AUTOLINK = re.compile(r"<(https?://[^\s<>]+)>")
_STRONG_STAR = re.compile(r"\*\*(?=[^\s*])(.+?)(?<=[^\s*])\*\*")
_STRONG_UND = re.compile(r"(?<!\w)__(?=[^\s_])(.+?)(?<=[^\s_])__(?!\w)")
_EM_STAR = re.compile(r"\*(?=[^\s*])(.+?)(?<=[^\s*])\*")
_EM_UND = re.compile(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)")
_SLOT = re.compile("\ue000(\\d+)\ue001")


def _escape(text):
    return html_lib.escape(text, quote=False)


def _normalize(text):
    text = "" if text is None else (text if isinstance(text, str) else str(text))
    if len(text) > MAX_CHARS:
        raise AppError("CONTENT_INVALID", {"항목": "본문"}, detail=f"{MAX_CHARS}자를 넘는다")
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    return _PRIVATE.sub("", _CONTROL.sub("", text)).expandtabs(4)


# ----------------------------------------------------------------------------------------------------------------------------
# Markdown → HTML
# ----------------------------------------------------------------------------------------------------------------------------
class _Context:
    def __init__(self, allow_links, allowed_hosts):
        self.allow_links = allow_links
        self.allowed_hosts = tuple(host.lower() for host in allowed_hosts)
        self.images = []
        self.positions = []                              # 이미지마다, 그 앞에 나온 최상위 블록 수(이미지의 자리 — 0 이면 글 맨 앞)
        self.emitted = 0                                 # 지금까지 내보낸 최상위 블록 수


def _emphasis(text):
    text = _STRONG_STAR.sub(r"<strong>\1</strong>", text)
    text = _STRONG_UND.sub(r"<strong>\1</strong>", text)
    text = _EM_STAR.sub(r"<em>\1</em>", text)
    return _EM_UND.sub(r"<em>\1</em>", text)


def _link_ok(url, context):
    if not context.allow_links or not url or re.search(r"[\s\x00-\x1f]", url):
        return False
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    return not context.allowed_hosts or any(host == allowed or host.endswith("." + allowed) for allowed in context.allowed_hosts)


def _inline(text, context):
    """한 문단의 글 → 안전한 HTML 조각(허용 태그는 strong·em·br·a 뿐). 너무 긴 문단은 글로만 둔다."""
    if len(text) > INLINE_LIMIT:
        return _escape(text)
    stash = []
    html = _inline_parts(text, context, stash)
    for _ in range(12):                                  # 표지를 되돌린다(링크 글 안의 표지처럼 겹친 것은 여러 번 풀어야 한다)
        html, count = _SLOT.subn(lambda match: stash[int(match.group(1))], html)
        if not count:
            break
    return re.sub(r" {2,}", " ", html).strip()           # 이미지·코드 조각을 걷어 낸 자리의 겹친 공백과 앞뒤 공백은 정리한다(문단·제목·목록 항목 모두 같게)


def _inline_parts(text, context, stash):
    """표지(스태시 번호)가 든 HTML 조각. 링크 글 안에서도 같은 스태시를 써야 부모가 만든 표지가 그 안에서도 풀린다."""

    def keep(html):
        stash.append(html)
        return f"\ue000{len(stash) - 1}\ue001"

    text = _ESCAPABLE.sub(lambda match: keep(_escape(match.group(1))), text)
    text = _CODE_SPAN.sub(lambda match: keep(_escape(match.group(2).strip())), text)

    def image(match):
        context.images.append((match.group(1).strip(), match.group(2)))
        context.positions.append(context.emitted)
        return ""

    text = _IMAGE.sub(image, text)

    def link(match):
        inner = _inline_parts(match.group(1), context, stash)        # 링크 글에는 대괄호가 없어(`_LINK`) 그 안에 또 링크가 들 수 없다 — 재귀는 한 단계뿐
        url = match.group(2)
        if _link_ok(url, context):
            return keep(f'<a href="{html_lib.escape(url, quote=True)}">{inner}</a>')
        return keep(inner)

    def autolink(match):
        url = match.group(1)
        if _link_ok(url, context):
            return keep(f'<a href="{html_lib.escape(url, quote=True)}">{_escape(url)}</a>')
        return keep(_escape(url))

    text = _LINK.sub(link, text)
    text = _AUTOLINK.sub(autolink, text)
    return _emphasis(_escape(text))


def _ordered_start(line):
    """번호 목록을 '시작'하는 줄인가 — 번호가 1 일 때만(목록 안에서 이어지는 줄은 번호가 무엇이든 된다). "2026. 10. 30 에 시작" 같은 글이 목록이 돼 숫자가 사라지지 않게 한다."""
    match = _ORDERED.match(line)
    return bool(match and match.group(2) == "1")


def _starts_block(line):
    return bool(_FENCE.match(line) or _ATX.match(line) or _RULE.match(line) or _QUOTE.match(line) or _BULLET.match(line) or _ordered_start(line))


def _heading_tag(level):
    return "h2" if level <= 2 else "h3" if level == 3 else "h4"


def _paragraph_html(lines, context):
    parts = []
    for index, line in enumerate(lines):
        last = index == len(lines) - 1
        hard = not last and (line.endswith("  ") or line.endswith("\\"))
        piece = line.strip()
        if hard and line.endswith("\\"):
            piece = piece[:-1].rstrip()
        parts.append(piece)
        if not last:
            parts.append(_HARD if hard else " ")
    return _inline("".join(parts), context).replace(_HARD, "<br>")


def _new_list(ordered, indent):
    return {"ordered": ordered, "indent": indent, "items": []}


def _list_html(region, context):
    """목록 줄들 → 중첩 <ul>/<ol>. 들여쓰기가 같은 항목끼리 한 목록이고, 더 깊어지면 직전 항목의 하위 목록이다."""
    items = []                                           # [들여쓴 칸 수, 번호 목록인가, 글]
    for line in region:
        bullet, ordered = _BULLET.match(line), _ORDERED.match(line)
        match = bullet or ordered
        if match and not _RULE.match(line):
            items.append([len(match.group(1)), bool(ordered and not bullet), match.group(3).strip()])
        elif items and not _BLANK.match(line):
            items[-1][2] += " " + line.strip()
    lists, stack = [], []
    for indent, ordered, text in items:
        while stack and indent < stack[-1]["indent"]:
            stack.pop()
        if not stack:
            node = _new_list(ordered, indent)
            lists.append(node)
            stack.append(node)
        elif indent > stack[-1]["indent"] and len(stack) < MAX_LIST_DEPTH:
            node = _new_list(ordered, indent)
            stack[-1]["items"][-1]["children"].append(node)
            stack.append(node)
        elif indent == stack[-1]["indent"] and ordered != stack[-1]["ordered"]:      # 같은 단계에서 점 ↔ 번호가 바뀌면 새 목록(깊이 상한에서 더 깊은 것은 지금 목록에 이어 붙인다)
            node = _new_list(ordered, stack[-1]["indent"])
            if len(stack) == 1:
                lists.append(node)
            else:
                stack[-2]["items"][-1]["children"].append(node)
            stack[-1] = node
        stack[-1]["items"].append({"text": text, "children": []})

    def render(node):
        tag = "ol" if node["ordered"] else "ul"
        body = "".join("<li>" + _inline(item["text"], context) + "".join(render(child) for child in item["children"]) + "</li>" for item in node["items"])
        return f"<{tag}>{body}</{tag}>"

    return "".join(render(node) for node in lists)


def _blocks(lines, context, depth):
    out, i, count = [], 0, len(lines)

    def emit(html):
        out.append(html)
        if depth == 0:
            context.emitted += 1
    while i < count:
        line = lines[i]
        if _BLANK.match(line):
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            char, size = fence.group(1)[0], len(fence.group(1))
            j, body = i + 1, []
            while j < count and not (set(lines[j].strip()) == {char} and len(lines[j].strip()) >= size):
                body.append(lines[j])
                j += 1
            if body:
                emit("<p>" + "<br>".join(_escape(row.rstrip()) for row in body) + "</p>")
            i = j + 1
            continue
        if _RULE.match(line):
            i += 1
            continue
        atx = _ATX.match(line)
        if atx:
            content = (atx.group(2) or "").strip()
            if content:
                tag = _heading_tag(len(atx.group(1)))
                emit(f"<{tag}>{_inline(content, context)}</{tag}>")
            i += 1
            continue
        if _QUOTE.match(line):
            j, inner = i, []
            while j < count and _QUOTE.match(lines[j]):
                inner.append(_QUOTE.match(lines[j]).group(1))
                j += 1
            body = _blocks(inner, context, depth + 1) if depth < MAX_DEPTH else [_paragraph_html(inner, context)]
            if body:
                emit("<blockquote>" + "".join(body) + "</blockquote>")
            i = j
            continue
        if _BULLET.match(line) or _ordered_start(line):
            j, region = i, []
            while j < count:
                row = lines[j]
                if _BLANK.match(row):
                    k = j
                    while k < count and _BLANK.match(lines[k]):
                        k += 1
                    if k < count and (_BULLET.match(lines[k]) or _ORDERED.match(lines[k]) or lines[k].startswith("  ")) and not _RULE.match(lines[k]):
                        j = k
                        continue
                    break
                if (_BULLET.match(row) or _ORDERED.match(row) or row.startswith("  ")) and not (_RULE.match(row) and not row.startswith("  ")):
                    region.append(row)
                    j += 1
                    continue
                break
            emit(_list_html(region, context))
            i = j
            continue
        j, paragraph = i + 1, [line]
        while j < count and not _BLANK.match(lines[j]) and not _starts_block(lines[j]):
            paragraph.append(lines[j])
            j += 1
        html = _paragraph_html(paragraph, context).strip()
        if html:
            emit(f"<p>{html}</p>")
        i = j
    return out


_EMPHASIS_TAG = re.compile(r"<(/?)(strong|em)>")


def _flatten_emphasis(html):
    """같은 강조 안의 같은 강조(`<em>가 <em>나</em> 다</em>`)는 하나로 합친다. 글자 모양은 그대로이고, 합쳐 둬야 되돌린 마크다운이 같은 HTML 로 돌아온다."""
    out, last, open_kinds, stack = [], 0, [], []
    for match in _EMPHASIS_TAG.finditer(html):
        out.append(html[last:match.start()])
        last = match.end()
        kind = match.group(2)
        if match.group(1):
            if not stack or stack[-1][0] != kind:                # 정화기가 늘 짝을 맞춰 주지만 어긋나 있으면 손대지 않고 그대로 돌려준다
                return html
            redundant = stack.pop()[1]
            open_kinds.pop()
        else:
            redundant = kind in open_kinds
            stack.append((kind, redundant))
            open_kinds.append(kind)
        out.append("" if redundant else match.group(0))
    out.append(html[last:])
    return html if stack else "".join(out)


def _convert(text, allow_links=False, allowed_hosts=()):
    context = _Context(allow_links, allowed_hosts)
    return _blocks(_normalize(text).split("\n"), context, 0), context


def _clean(html, allow_links, allowed_hosts):
    clean, _stats = sanitize_html(html, allow_links=allow_links, allowed_hosts=tuple(allowed_hosts))
    return _flatten_emphasis(clean)


def markdown_to_html(text, *, allow_links=False, allowed_hosts=()):
    """Markdown → 허용 태그만 있는 HTML. 링크는 allow_links 이고 https·allowed_hosts 인 것만 남는다. 이미지는 넣지 않는다(markdown_images 로 따로)."""
    blocks, _context = _convert(text, allow_links, allowed_hosts)
    return _clean("".join(blocks), allow_links, allowed_hosts)


def markdown_images(text):
    """글 속 이미지 [(설명, 주소), …] — 코드 안의 것은 제외, 나타난 순서대로. 주소가 안전한지는 부르는 쪽이 따로 검사한다."""
    return _convert(text)[1].images


def markdown_blocks(text, *, allow_links=False, allowed_hosts=()):
    """Markdown → (최상위 블록마다 정화한 HTML 목록, 이미지 [(설명, 주소, 자리)]). 블록을 이어 붙이면 `markdown_to_html` 과 같다.
    자리는 그 이미지 앞에 나온 블록 수다(0 이면 글 맨 앞, 블록 수와 같으면 글 맨 뒤) — 플랫폼 글에서 이미지를 제자리에 놓을 때 쓴다."""
    blocks, context = _convert(text, allow_links, allowed_hosts)
    cleaned = [_clean(block, allow_links, allowed_hosts) for block in blocks]
    kept = [index for index, block in enumerate(cleaned) if block]
    images = [(alt, url, sum(1 for index in kept if index < position)) for (alt, url), position in zip(context.images, context.positions)]
    return [cleaned[index] for index in kept], images


# ----------------------------------------------------------------------------------------------------------------------------
# HTML → Markdown (기존 글 불러오기)
# ----------------------------------------------------------------------------------------------------------------------------
class _Node:
    def __init__(self, tag):
        self.tag = tag
        self.children = []                               # _Node 또는 글(str)
        self.href = None


MAX_TREE_DEPTH = 100                                     # 이보다 깊이 중첩된 태그는 무시하고 글만 남긴다(재귀가 한없이 깊어지지 않게)


class _TreeReader(HTMLParser):
    """정화된 HTML(허용 태그·링크뿐)을 나무로 읽는다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if len(self.stack) > MAX_TREE_DEPTH and tag != "br":
            return
        node = _Node(tag)
        if tag == "a":
            node.href = dict(attrs).get("href")
        self.stack[-1].children.append(node)
        if tag != "br":
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag == "br":
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>])")
_PROTECT = (
    (re.compile(r"^(\s*)(#{1,6})(?=\s|$)"), r"\1\\\2"),         # `# 제목`
    (re.compile(r"^(\s*)([-+])(?=\s|$)"), r"\1\\\2"),            # `- 목록`·`+ 목록`
    (re.compile(r"^(\s*)(-{3,}|={3,})\s*$"), r"\1\\\2"),         # `---`(가로줄)·`===`
    (re.compile(r"^(\s*)(\d{1,9})([.)])(?=\s|$)"), r"\1\2\\\3"),  # `1. 번호 목록`
)


def _md_escape(text):
    return _MD_SPECIAL.sub(r"\\\1", text)


def _protect(line):
    """줄 맨 앞의 `#`·`-`·`+`·`1.`·`---` 가 제목·목록·가로줄로 읽히지 않게 역슬래시를 붙인다(`*`·`>` 는 이미 어디서나 이스케이프한다)."""
    for pattern, replacement in _PROTECT:
        line, count = pattern.subn(replacement, line, count=1)
        if count:
            break
    return line


def _inline_md(nodes, allow_links, active=()):
    """글 속 태그 → Markdown. 이미 굵게/기울임 안이면 같은 표시를 겹쳐 쓰지 않는다(`**굵게 **굵게****` 같은 모호한 글이 되지 않게)."""
    out = []
    for node in nodes:
        if isinstance(node, str):
            out.append(_md_escape(re.sub(r"\s+", " ", node)))
        elif node.tag == "br":
            out.append("  \n")
        elif node.tag in ("strong", "b", "em", "i"):
            kind = "strong" if node.tag in ("strong", "b") else "em"
            only = [child for child in node.children if not (isinstance(child, str) and not child.strip())]
            if kind == "strong" and kind not in active and len(only) == 1 and not isinstance(only[0], str) and only[0].tag in ("em", "i") and "em" not in active:
                inner = _inline_md(only[0].children, allow_links, active + ("strong", "em")).strip()      # 굵게 안의 기울임만 있는 글 → `**_글_**`(`***글***` 은 기울임이 바깥으로 읽힌다)
                out.append(f"**_{inner}_**" if inner else "")
                continue
            inner = _inline_md(node.children, allow_links, active + (kind,)).strip()
            mark = "**" if kind == "strong" else "*"
            out.append(inner if kind in active or not inner else f"{mark}{inner}{mark}")
        elif node.tag == "a":
            inner = _inline_md(node.children, allow_links, active).strip()
            href = node.href or ""
            out.append(f"[{inner}]({href})" if inner and allow_links and href else inner)
        else:
            out.append(_inline_md(node.children, allow_links, active))
    return "".join(out)


def _paragraph_md(text):
    rows = []
    for row in text.split("\n"):
        stripped = row.strip(" ")
        if stripped:
            rows.append(_protect(stripped) + ("  " if row.endswith("  ") else ""))
    return "\n".join(rows)


def _list_md(node, allow_links, level):
    out, number = [], 1
    for item in node.children:
        if isinstance(item, str):                                       # 항목 밖에 떨어진 글도 잃지 않고 항목으로 둔다
            text = _md_escape(" ".join(item.split()))
            if text:
                out.append("    " * level + (f"{number}. " if node.tag == "ol" else "- ") + _protect(text))
                number += 1
            continue
        if item.tag in ("ul", "ol"):                                    # 항목 없이 목록 안에 바로 들어간 목록도 한 단계 안쪽 목록으로 읽는다
            out.extend(_list_md(item, allow_links, level + 1))
            continue
        if item.tag != "li":
            continue
        inline = [child for child in item.children if isinstance(child, str) or child.tag not in ("ul", "ol")]
        nested = [child for child in item.children if not isinstance(child, str) and child.tag in ("ul", "ol")]
        text = " ".join(_inline_md(inline, allow_links).replace("  \n", " ").split())
        marker = f"{number}. " if node.tag == "ol" else "- "
        out.append("    " * level + marker + _protect(text))
        for child in nested:
            out.extend(_list_md(child, allow_links, level + 1))
        number += 1
    return out


def _blocks_md(nodes, allow_links):
    blocks, loose = [], []

    def flush():
        if loose:
            text = _inline_md(loose, allow_links).strip()
            if text:
                blocks.append(_paragraph_md(text))
            loose.clear()

    for node in nodes:
        if isinstance(node, str) or node.tag in ("strong", "b", "em", "i", "br", "a"):
            loose.append(node)
            continue
        flush()
        if node.tag == "p":
            text = _inline_md(node.children, allow_links).strip()
            if text:
                blocks.append(_paragraph_md(text))
        elif node.tag in ("h2", "h3", "h4"):
            text = " ".join(_inline_md(node.children, allow_links).replace("  \n", " ").split())
            if text:
                blocks.append("#" * int(node.tag[1]) + " " + text)
        elif node.tag in ("ul", "ol"):
            lines = _list_md(node, allow_links, 0)
            if lines:
                blocks.append("\n".join(lines))
        elif node.tag == "blockquote":
            inner = "\n\n".join(_blocks_md(node.children, allow_links))
            if inner:
                blocks.append("\n".join(("> " + row) if row else ">" for row in inner.split("\n")))
        else:                                            # 목록 밖의 li 같은 것은 글로 푼다
            loose.extend(node.children)
    flush()
    return blocks


def html_to_markdown(html, *, allow_links=False, allowed_hosts=()):
    """HTML → Markdown(기존 Blogger·네이버 글 불러오기). 먼저 허용 태그만 남기고 정화한 뒤 바꾼다. 글 속 Markdown 기호는 역슬래시로 지킨다."""
    clean, _stats = sanitize_html(_normalize(html), allow_links=allow_links, allowed_hosts=tuple(allowed_hosts))
    reader = _TreeReader()
    reader.feed(clean)
    reader.close()
    blocks = _blocks_md(reader.root.children, allow_links)
    return "\n\n".join(blocks) + ("\n" if blocks else "")


# ----------------------------------------------------------------------------------------------------------------------------
# HTML → 평문 (서식 없는 칸에 붙여넣을 글 — 네이버 평문 복사)
# ----------------------------------------------------------------------------------------------------------------------------
def _text_inline(nodes):
    out = []
    for node in nodes:
        if isinstance(node, str):
            out.append(re.sub(r"\s+", " ", node))
        elif node.tag == "br":
            out.append("\n")
        else:
            out.append(_text_inline(node.children))
    return "".join(out)


def _text_lines(text):
    return "\n".join(line.strip() for line in text.strip().split("\n")).strip()


def _text_list(node, level):
    out, number = [], 1
    for item in node.children:
        if isinstance(item, str):
            text = _text_lines(_text_inline([item]))
            if text:
                out.append("  " * level + (f"{number}. " if node.tag == "ol" else "- ") + text.replace("\n", " "))
                number += 1
            continue
        if item.tag in ("ul", "ol"):
            out.extend(_text_list(item, level + 1))
            continue
        if item.tag != "li":
            continue
        inline = [child for child in item.children if isinstance(child, str) or child.tag not in ("ul", "ol")]
        nested = [child for child in item.children if not isinstance(child, str) and child.tag in ("ul", "ol")]
        text = " ".join(_text_inline(inline).split())
        out.append("  " * level + (f"{number}. " if node.tag == "ol" else "- ") + text)
        for child in nested:
            out.extend(_text_list(child, level + 1))
        number += 1
    return out


def _text_blocks(nodes):
    blocks, loose = [], []

    def flush():
        text = _text_lines(_text_inline(loose))
        if text:
            blocks.append(text)
        loose.clear()

    for node in nodes:
        if isinstance(node, str) or node.tag in ("strong", "b", "em", "i", "br", "a"):
            loose.append(node)
            continue
        flush()
        if node.tag in ("ul", "ol"):
            lines = _text_list(node, 0)
            if lines:
                blocks.append("\n".join(lines))
        elif node.tag == "blockquote":
            inner = "\n\n".join(_text_blocks(node.children))
            if inner:
                blocks.append("\n".join(("> " + row) if row else ">" for row in inner.split("\n")))
        else:                                            # p·h2~h4 와 목록 밖의 li 같은 것은 글만 문단으로
            loose.extend(node.children)
            flush()
    flush()
    return blocks


def html_to_text(html, *, allow_links=False, allowed_hosts=()):
    """HTML → 평문. 먼저 허용 태그만 남기고 정화한 뒤 글자만 옮긴다: 블록 사이는 빈 줄, 소제목은 한 줄, 목록은 `- `·`1. `(중첩은 두 칸씩 안으로),
    인용은 `> `, `<br>` 는 줄바꿈. 굵게·기울임·링크 표시는 없고(링크 글자만 남는다) Markdown 기호를 이스케이프하지 않는다."""
    clean, _stats = sanitize_html(_normalize(html), allow_links=allow_links, allowed_hosts=tuple(allowed_hosts))
    reader = _TreeReader()
    reader.feed(clean)
    reader.close()
    blocks = _text_blocks(reader.root.children)
    return "\n\n".join(blocks) + ("\n" if blocks else "")
