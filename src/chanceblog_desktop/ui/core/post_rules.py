"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)의 순수 규칙 — 미리보기 만들기·건강 효과 단정 판정·비밀 모양 찾기·검사 코드의 쉬운 문장·Pages 검토 값 검사·승인 조건. PySide6 도 파일도 서비스도 시계도 모른다.

가장 큰 위험은 **검토 결과를 읽지 않았거나 막힌 글이 승인되는 것**과 **미리보기·목록에서 키 모양 글이 그대로 나가는 것**이다. 그래서 규칙을 작게 쪼개 시험이 하나씩 못박는다:
  · `build_preview` — 서비스의 안전 변환(`render/markdown.py` — 허용 태그만 남기는 정화를 한 번 더 거친 블록)에서 **글자만** 뽑아 블록 종류별로 나눈다. 모든 글은 **가린 뒤에 줄인다**(`display_text`). 앞 80블록·20,000자까지만 담고 나머지는 개수로 알린다.
  · `secret_spots`·`health_of` — 저장 때와 같은 비밀 모양 검사기(`security/scan.py`)와 초안 복사 관문과 같은 건강 효과 단정 판정(`drafts.review_health`). 가짜 공급자와 실제 어댑터가 **같은 함수**를 쓴다.
  · `gate_sentence` — 서비스 관문의 `[코드]` 마다 쉬운 한 문장(모르는 코드는 일반 문장).
  · `review_blocks`·`approval_state` — 승인 조건 한 곳: 이 글·이 플랫폼·이 판의 검토 결과를 받았고, 상태가 '검토 중' 이고, 막힘이 없어야 한다(막힘 판단이 비어 있는 결과는 믿지 않는다 — fail closed).
  · `pages_problems`·`pages_values_of` — Pages 검토 값 칸의 검사(분야·언어·대표 이미지 주소·태그·한 줄 설명) — 한도는 렌더러의 값(`render/pages.py`)을 그대로 가져온다.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from ...content import status as st
from ...render.pages import MAX_CATEGORY, MAX_DESCRIPTION, MAX_TAG, MAX_TAGS
from .draft_rules import HEALTH_STOP, HealthReview, health_units
from .drafts import review_health
from .posts import PLATFORMS, PagesValues, PostPreview, PreviewBlock
from .text import T, display_text

PREVIEW_BLOCKS = 80                                          # 미리보기에 그리는 최대 블록(문단) 수
PREVIEW_CHARS = 20_000                                       # 미리보기에 그리는 최대 글자 수(합계)
BLOCK_LIMIT = 3_000                                          # 블록 하나의 최대 글자 수(넘으면 줄인다)
PAGE = 50                                                    # 목록에 한 번에 그리는 글 수 — `더 보기` 로 늘린다
TITLE_SHOWN = 120                                            # 목록·머리에 보이는 제목의 최대 글자 수(가린 뒤에 줄인다)
KST = timezone(timedelta(hours=9))
KIND_OF_TAG = {"h2": "heading", "h3": "heading", "h4": "heading", "ul": "list", "ol": "list", "blockquote": "quote", "p": "paragraph"}
KIND_LABEL = {"heading": "post_block_heading", "list": "post_block_list", "quote": "post_block_quote", "paragraph": "post_block_paragraph"}
REVIEWABLE = frozenset({st.NOT_STARTED, st.DRAFT_GENERATED, st.REVIEW_REQUIRED, st.APPROVED, st.READY_TO_COPY, st.PUBLISH_FAILED})          # 이 화면이 '검토 시작·다시 검토' 를 켜는 상태 — 올라간·복사 마친·공개된 글은 1a 가 바꾸지 않는다
APPROVED_NOW = frozenset({st.APPROVED, st.READY_TO_COPY})   # 승인 취소가 켜지는 상태
COPYABLE = frozenset({st.READY_TO_COPY, st.COPY_COMPLETED})   # 복사용 패키지 카드가 보이고 복사 단추가 켜지는 상태(글 흐름 1b)
MAX_URL = 500                                                # 발행 주소 칸의 최대 글자 수(글 흐름 1b)
NAVER_HOSTS = ("blog.naver.com", "m.blog.naver.com")         # 발행 주소로 받는 네이버 블로그 주소(서비스 `content/model.py` 와 같다 — 시험이 견준다)
_TAG = re.compile(r"^<([a-z0-9]+)")
_NON_ASCII = re.compile(r"[^\x20-\x7e]")                     # 보이는 ASCII 가 아닌 모든 글자 — 엔진이 지우는 눈에 안 보이는 글자는 전부 여기 든다(그보다 넓다). 이것을 모두 지운 글에 BEGIN·END 낱말이 없으면 엔진도 머리·꼬리를 볼 수 없다
_PROBE_LIMIT = 150_000                                       # 엔진에 한 번에 묻는 글의 최대 길이 — 엔진은 20만 자에서 글을 자르므로(끝 표지가 잘려 나가 '열려 있다' 로 잘못 읽힌다) 그 아래로 잡는다
_PROBE_MARKS = ("ZQJ", "QJZ", "JZQ", "XQV", "VQX", "KQZ", "ZKQ", "QZK")      # 글 뒤에 붙여 엔진에 묻는 세 글자 표지 후보 — 글에 없는 것을 쓴다(네 글자부터는 '값' 으로 읽혀 가려질 수 있다)
_FAKE_HEAD = "-----BEGIN " + "PRIVATE KEY-----"                # 이미 열린 채 들어오는 조각 앞에 붙이는 가짜 머리 줄 — 엔진이 머리부터 읽게 한다(조립한 글자 — 키 모양을 소스에 그대로 두지 않는다)
_INVISIBLE_RANGES = ((0xAD, 0xAD), (0x34F, 0x34F), (0x61C, 0x61C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x2800, 0x2800), (0x3164, 0x3164),
                     (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFFB), (0xE0000, 0xE0FFF))          # 가리기 엔진(`security/mask.py`)이 비밀을 찾기 전에 지우는 눈에 안 보이는 글자 구간 — 범주(아래)와 함께 엔진과 같은 눈이다
_INVISIBLE = re.compile("[" + "".join(chr(low) + ("-" + chr(high) if high != low else "") for low, high in _INVISIBLE_RANGES) + "]")
_HIDDEN_CATEGORIES = frozenset({"Cf", "Cc", "Cs", "Co", "Zl", "Zp"})      # 서식·제어·대용·사용자 지정·줄/문단 구분 문자 — 엔진이 범주로도 지운다. 어긋나도 안전한 쪽이다(견줄 때 같지 않으면 가렸다고 센다)
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,39}")
_STAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$")


def shown(value, limit=300):
    """화면에 나가는 동적 글을 비밀 모양을 가린 한 줄로 줄인다(가리기가 먼저, 줄이기가 나중이다)."""
    return display_text(value, limit)


def _without_invisible(value):
    """가리기 엔진이 비밀을 찾기 전에 지우는 눈에 안 보이는 글자(폭 없는 글자·방향 제어·태그·변형 선택자·채움 글자·제어·줄/문단 구분 …)를 뺀 글 — 줄바꿈·탭은 둔다.
    엔진과 구간 목록이 어긋나도 안전한 쪽이다: 이 글을 엔진이 낸 글과 견줄 때 같지 않으면 가렸다고 세므로 기억을 덜 할 뿐 더 하지는 않는다."""
    text = _INVISIBLE.sub("", value)
    if text.replace("\n", "").replace("\r", "").replace("\t", "").isprintable():
        return text
    return "".join(char for char in text if char in "\n\r\t" or unicodedata.category(char) not in _HIDDEN_CATEGORIES)


def would_be_masked(value):
    """가리기 엔진이 이 글에서 **비밀 모양을** 가리는가 — 저장 검사기(`secret_spots`)가 아는 여섯 유형뿐 아니라 엔진이 아는 모든 모양(Slack·Stripe·OpenAI·Anthropic 키·주소 속 사용자 정보 …)을 본다.
    이 앱을 연 동안 기억해 칸에 다시 채울 값처럼 '키 모양이 하나라도 있으면 내보내지 않을 글' 을 가릴 때 쓴다(독립 검증 S 참고-2). 엔진은 먼저 눈에 안 보이는 글자를 지우므로
    **그것만 지운 글**과 견준다(독립 검증 S 2차 참고 I1 — ZWJ 이모지·변형 선택자가 든 평범한 값을 가렸다고 세지 않는다. 키를 그 글자로 쪼갠 값은 엔진이 지우고 알아봐 가린다). 글이 아니거나 가릴 글이 없으면 False."""
    if not isinstance(value, str):
        return False
    flat = " ".join(_without_invisible(value).split())
    return bool(flat) and display_text(flat, len(flat) + 64) != flat


def when_text(stamp, seconds=False):
    """글에 적힌 UTC 시각(`2026-11-24T05:30:12Z`) → 한국 시각 `2026-11-24 14:30`(`seconds` 면 `2026-11-24 14:30:12` — 작업 로그 줄). 모양이 다르면 빈 글(지어내지 않는다). 시계를 읽지 않는다."""
    found = _STAMP.match(stamp) if isinstance(stamp, str) else None
    if found is None:
        return ""
    try:
        moment = datetime(*(int(part) for part in found.groups()), tzinfo=timezone.utc).astimezone(KST)
    except ValueError:
        return ""
    return moment.strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")


def status_text(status):
    key = f"post_status_{status}" if isinstance(status, str) and _CODE.fullmatch(status) else ""
    return T.get(key) or T["post_status_unknown"]


def platform_text(platform):
    return T.get(f"post_platform_{platform}", "") if platform in PLATFORMS else ""


# ---- 미리보기 --------------------------------------------------------------------------------------------------------------------------
def _safe_block(plain):
    """블록 글 → 가린 글. 한 줄로 펴서 가려 보고(여러 줄에 걸친 키 모양도 잡는다) 바뀐 곳이 없을 때만 줄 나눔을 살린다(줄마다 한 번 더 가린다)."""
    flat = " ".join(plain.split())
    masked = display_text(flat, BLOCK_LIMIT)
    if masked != flat:
        return masked                                        # 가렸거나 줄였다 — 한 줄로 보인다
    lines = []
    for line in plain.split("\n"):
        indent = len(line) - len(line.lstrip(" "))
        lines.append(" " * min(indent, 8) + display_text(line.strip(), BLOCK_LIMIT))
    return "\n".join(lines)


def _has_edge(line):
    """이 줄에 머리·꼬리 낱말(BEGIN·END)이 있을 수 있나 — 눈에 안 보이는 글자로 쪼개 쓴 것까지 놓치지 않게 보이는 ASCII 만 남기고 본다(엔진이 지우는 글자는 모두 지워지므로 이 거름이 엔진보다 느슨하다)."""
    flat = _NON_ASCII.sub("", line)
    return "BEGIN" in flat or "END" in flat


def _ask_engine(plain, inside):
    """엔진에 글 한 조각을 묻는다 → (엔진이 가린 글, 이 조각을 읽고 난 뒤 열려 있나). `plain` 은 한 번에 물을 수 있는 크기(`_PROBE_LIMIT` 이하)다. 글 뒤에 글에 없는 표지 후보를 붙여 `display_text` 에 넣고
    표지가 사라졌으면 열려 있는 것이다(가린 글에는 표지가 없다). 표지 후보가 모두 글에 들어 있으면 물을 수 없으니 (None, True) — 열려 있다고 본다. `inside` 면 앞에 가짜 머리 줄을 붙인다(가린 글이 표지로 시작한다)."""
    flat = _NON_ASCII.sub("", plain)
    mark = next((item for item in _PROBE_MARKS if item not in flat), None)
    if mark is None:
        return None, True
    probe = (_FAKE_HEAD + "\n" if inside else "") + plain + "\n" + mark
    seen = display_text(probe, 4 * len(probe) + 256)
    if mark in seen:
        return seen[:seen.rindex(mark)].rstrip(), False
    return seen, True


def _key_open_after(plain, inside):
    """이 글 조각을 읽고 난 뒤에도 개인 키 블록(PEM·PGP)이 **열려 있나** — 머리를 만나면 가장 가까운 개인 키 꼬리까지, 꼬리가 없으면 글 끝까지가 한 덩어리다.
    **판정은 가리기 엔진(`security/mask.py`)에 맡긴다**(독립 검증 S 2차 필수 N1): 조각 뒤에 표지(엔진이 건드리지 않는 세 글자)를 붙여 `display_text` 에 넣고 표지가 사라졌으면(머리부터 글 끝까지 가렸다) 아직 열려 있는 것이다.
    눈에 안 보이는 글자로 쪼갠 머리·길이 한도 없는 라벨·앞으로 엔진이 바뀌는 것까지 구성상 같다 — 이 파일에 머리·꼬리 정규식이 없다. `inside` 는 이 조각에 들어올 때 이미 열려 있었는가: 열린 채 들어오는 조각은
    앞에 가짜 머리 줄을 붙여 엔진이 머리부터 읽게 한다. 비용: 머리(닫힌 채일 때)·꼬리(열린 채일 때) 낱말이 있을 수 없는 조각은 묻지 않는다. 15만 자가 넘는 조각은 머리·꼬리가 있을 수 있는 줄만 모아 묻고(엔진은 20만 자에서 글을
    자른다), 그래도 15만 자가 넘는 한 줄이면 물을 수 없으니 열려 있다고 본다(더 많이 가리는 쪽). 표지 후보가 모두 글에 들어 있으면 마찬가지로 열려 있다고 본다."""
    if ("END" if inside else "BEGIN") not in _NON_ASCII.sub("", plain):
        return inside
    if len(plain) > _PROBE_LIMIT:
        plain = "\n".join(line for line in plain.split("\n") if _has_edge(line))
        if len(plain) > _PROBE_LIMIT:
            return True
    return _ask_engine(plain, inside)[1]


@lru_cache(maxsize=1)
def _key_marker():
    """엔진이 개인 키 블록 자리에 쓰는 표지 글 — 엔진에게 물어 얻는다(이 파일에 표지 글을 적지 않는다 — 표지가 바뀌어도 어긋나지 않는다)."""
    return display_text(_FAKE_HEAD, 200)


def _converted_open(line, was):
    """변환기가 이 줄만 변환해 보여 주는 글에서도 개인 키 블록이 열려 있나. 원문 엔진이 이 줄에서 닫혔다고 해도 변환기가 그 꼬리를 버리거나 깨면(이미지 설명·제목·울타리 이름 줄에 든 꼬리, 줄 구분 글자로 쪼개진 꼬리)
    화면에 나가는 글에서는 닫히지 않는다 — 그런 줄은 닫는 줄로 치지 않는다(원문 쪽과 변환된 글 쪽 **둘 다** 닫혔을 때만 닫힌다). 변환이 예외를 내면 열려 있다고 본다."""
    from ...render.markdown import markdown_blocks
    try:
        blocks, _images = markdown_blocks(line)
        plain = "\n\n".join(text for _kind, text in _entries_of(blocks))
    except Exception:
        return True
    return _key_open_after(plain, was)


def _line_step(line, was):
    """원문 한 줄 → (엔진 눈에 보이는 줄, 이 줄을 읽고 난 뒤 열려 있나). `was`: 이 줄에 열린 채 들어왔나. 보이는 줄은 개인 키 블록이 덮은 곳을 표지로 바꾼 글이다 —
    닫힌 채 들어온 줄은 머리가 없으면 줄 그대로, 머리가 있으면 엔진이 가린 글(머리 앞 글·표지·꼬리 뒤 글). 열린 채 들어온 줄은 꼬리 뒤에 남는 글만(없으면 빈 글 — 줄을 지운다).
    원문 엔진이 닫혔다고 해도 변환된 글에서 안 닫히면(`_converted_open`) 열린 채로 둔다 — 닫힌 채 들어온 줄은 표지까지만 남기고, 열린 채 들어온 줄은 지운다.
    줄 하나가 엔진에 물을 수 없을 만큼 길면 닫힌 채 들어온 줄은 표지 하나로, 열린 채 들어온 줄은 빈 글로, 둘 다 열려 있다고 본다."""
    marker = _key_marker()
    if len(line) > _PROBE_LIMIT:
        return ("" if was else marker), True
    seen, now = _ask_engine(line, was)
    if seen is None:
        return ("" if was else marker), True                 # 표지 후보가 모두 줄에 있어 물을 수 없다 — 열려 있다고 본다(더 많이 가리는 쪽)
    if was:
        shown = seen[len(marker):].strip() if seen.startswith(marker) else ""
    elif marker not in seen:
        return line, False                                   # 머리 낱말이 있을 뿐 엔진이 머리로 읽지 않는 줄 — 줄 그대로
    else:
        shown = seen
    if not now and _converted_open(line, was):
        now = True
        shown = "" if was else shown[:shown.index(marker) + len(marker)]
    return shown, now


def _hide_key_lines(raw):
    """원문(Markdown)에서 **엔진이 개인 키 블록으로 가리는 줄**을 변환 전에 먼저 가린 글(독립 검증 S 2차 권고 R1). 변환기(`render/markdown.py`)는 이미지 설명·이미지와 링크 제목·울타리 이름 줄의 글을 버리고
    강조·링크·이미지로 꼬리를 흉내 낼 수 있고 줄 구분 글자로 줄을 나눠서, 변환된 글에서 머리·꼬리를 찾으면 엔진이 원문에서 가리는 곳과 어긋난다 — 줄바꿈 글자 기준으로 줄마다 엔진에게 묻는다:
    머리가 든 줄은 엔진이 가린 한 줄(앞 글·표지·꼬리 뒤 글)로 바꾸고, 열려 있는 동안의 줄은 지우고, 꼬리가 든 줄은 꼬리 뒤 글만 남긴다. 꼬리는 원문 엔진과 변환된 글 **둘 다** 닫혔을 때만 닫는다(`_line_step`).
    머리 낱말이 글 어디에도 없으면 글 그대로다(거의 모든 글)."""
    if "BEGIN" not in _NON_ASCII.sub("", raw):
        return raw
    out, inside = [], False
    for line in raw.split("\n"):
        if ("END" if inside else "BEGIN") not in _NON_ASCII.sub("", line):
            if not inside:
                out.append(line)
            continue
        shown, now = _line_step(line, inside)
        if not inside or shown:
            out.append(shown)
        inside = now
    return "\n".join(out)


def _key_groups(entries):
    """(종류, 글) 목록 → 개인 키 블록을 **한 덩어리로 묶은** (종류, 글) 목록. 블록은 빈 줄마다 나뉘는데 실제 PGP 키는 머리 줄 뒤에 빈 줄이 있어, 블록마다 따로 가리면 머리 줄만 가려지고 본문 줄이
    그대로 나간다 — 머리가 열린 블록부터 꼬리가 든 블록까지(사이에 빈 줄·소제목·목록·인용이 끼어도, 꼬리가 없으면 글 끝까지)를 한 글로 이어 붙여 엔진이 머리부터 꼬리까지 한 번에 가리게 한다.
    묶인 덩어리의 종류는 머리가 든 블록의 종류다. 꼬리 뒤에 이어지는 같은 블록의 글은 그대로 남는다. 변환기가 **만드는** 머리(역슬래시로 쓴 붙임표·강조로 쓴 라벨)는 원문 가리기(`_hide_key_lines`)가 못 보므로 이 묶기가 맡는다."""
    groups, inside = [], False
    for kind, plain in entries:
        if inside:
            groups[-1][1].append(plain)
        else:
            groups.append((kind, [plain]))
        inside = _key_open_after(plain, inside)
    return [(kind, "\n\n".join(parts)) for kind, parts in groups]


def _entries_of(html_blocks):
    """변환된 HTML 블록들 → (종류, 글) 목록 — 글자만 뽑고(태그는 버린다) 빈 블록은 건너뛴다. 인용 블록은 줄 앞의 인용 기호를 뗀다."""
    from ...render.markdown import html_to_text
    entries = []
    for block in html_blocks:
        tag = _TAG.match(block)
        plain = html_to_text(block).strip()
        if not plain:
            continue
        kind = KIND_OF_TAG.get(tag.group(1) if tag else "", "paragraph")
        if kind == "quote":
            plain = "\n".join(re.sub(r"^> ?", "", line) for line in plain.split("\n"))
        entries.append((kind, plain))
    return entries


def build_preview(markdown, *, refs=0, assets=0):
    """원고(Markdown) → `PostPreview`. 서비스의 안전 변환이 만든 블록에서 글자만 뽑는다 — 글 속의 HTML 태그·스크립트는 변환기가 글자로 바꾸고, 여기서는 그 글자를 그대로(가려서) 내보낼 뿐 해석하지 않는다.
    이미지·링크는 내보내지 않는다(이미지는 개수만). 개인 키 블록은 두 단계로 가린다 — ① 변환 전에 엔진이 원문에서 개인 키 블록으로 가리는 줄을 먼저 가리고(`_hide_key_lines`) ② 변환된 글에서 머리가 열린 블록부터
    꼬리까지를 한 덩어리로 가린다(`_key_groups`). 열림 판정은 둘 다 엔진에게 묻는다. 글자 수·이미지 수는 가리기 전 글 그대로 센다. 변환이 거절하는 아주 큰 글(2,000,000자 초과)은 빈 미리보기다.
    아주 병적인 글(인용 기호만 2MB 가까이 같은 글)은 글자 뽑기에서 예외가 날 수 있다 — 저장된 글에서는 화면의 10만 자 한도 안에서 만들어지지 않고, 나면 화면이 오류 상태로 안전하게 닫는다(빈 미리보기로 속이지 않는다)."""
    from ...render.markdown import markdown_blocks
    text = markdown if isinstance(markdown, str) else ""
    try:
        html_blocks, images = markdown_blocks(text)
    except Exception:                                        # 변환이 받지 않는 글(2,000,000자 초과) — 저장된 글에는 없지만 변환기가 받지 않는 값은 빈 미리보기다
        return PostPreview((), 0, 0, 0, int(refs), False)
    entries = _entries_of(html_blocks)
    chars = sum(len(re.sub(r"\s+", "", plain)) for _kind, plain in entries)         # 글자 수는 글 그대로의 크기다(가린 줄도 센다)
    hidden = _hide_key_lines(text)
    if hidden != text:
        try:
            hidden_blocks, _hidden_images = markdown_blocks(hidden)
        except Exception:                                    # 줄을 가린 글이 변환기 한도를 넘는 경우 — 내보내지 않는 쪽(빈 미리보기)
            return PostPreview((), 0, 0, 0, int(refs), False)
        entries = _entries_of(hidden_blocks)
    kept, total, used = [], 0, 0
    for kind, plain in _key_groups(entries):
        total += 1
        if len(kept) < PREVIEW_BLOCKS and used < PREVIEW_CHARS:
            block_text = _safe_block(plain)
            used += len(block_text)
            kept.append(PreviewBlock(kind, block_text))
    return PostPreview(tuple(kept), total, chars, len(images) + int(assets), int(refs), len(kept) < total)


# ---- 비밀 모양·건강 효과 단정 -----------------------------------------------------------------------------------------------------------------
def _asset_lines(assets):
    """이미지 자리들 → 파일 이름과 설명을 한 줄씩 적은 글(검사기에 넣을 글 — 저장 때도 이 둘을 훑는다)."""
    return "\n".join(f"{getattr(item, 'filename', '')} {getattr(item, 'alt', '')}".strip() for item in assets) if assets else ""


def secret_spots(title, body, references=(), assets=()):
    """제목·본문·출처·이미지 이름과 설명에서 키·토큰 모양을 찾는다 → ((칸 이름, 줄, 유형 이름), …) — 위치와 유형뿐이다(글은 어디에도 없다). 저장 때(`new_project`)와 같은 검사기라서 기준이 같다."""
    from ...security import scan
    fields = {}
    for name, value in ((T["drf_where_title"], title), (T["drf_where_body"], body), (T["post_where_refs"], "\n".join(str(item) for item in references) if references else ""), (T["post_where_assets"], _asset_lines(assets))):
        if isinstance(value, str) and value:
            fields[name] = value
    try:
        found = scan.scan_fields(fields) if fields else ()
    except (TypeError, ValueError):                          # 검사기가 받지 않는 입력 — 읽지 못한 것을 '없다' 고 말하지 않도록 막는 쪽으로 알린다
        return ((T["drf_where_body"], 1, scan.KIND_LABELS["pem_private_key"]),)
    return tuple((item.where, item.line, scan.KIND_LABELS[item.kind]) for item in found)


def health_of(title, body, extra=()):
    """제목·본문의 건강 효과 단정 판정 → `HealthReview` — 초안 작성 화면의 복사 관문과 **같은 함수**(`drafts.review_health`)를 글 조각(문장)마다 따로 건다.
    `extra` 는 더 걸 (이름, 조각들) 쌍들이다 — Pages 검토 값의 한 줄 설명·태그(`pages_health_extra`, 글 흐름 1b D-652). 가장 높은 단계와 막힘 조각의 앞부분이 모두 합쳐진다."""
    return review_health((T["drf_where_title"], (title,) if isinstance(title, str) else ()), (T["drf_where_body"], health_units(body)), *extra)


def pages_health_extra(values):
    """Pages 검토 값(`PagesValues`) → 건강 효과 단정 판정에 더 거는 (이름, 조각들) 쌍들 — 한 줄 설명은 문장마다, 태그는 하나씩이다. 값이 없으면(네이버·옛 요청) 빈 튜플(글 흐름 1b, D-652)."""
    if values is None:
        return ()
    description = values.description if isinstance(values.description, str) else ""
    tags = tuple(tag for tag in (values.tags or ()) if isinstance(tag, str))
    return ((T["post_where_description"], health_units(description)), (T["post_where_tags"], tags))


def copy_blocked(text):
    """복사할 글에 키·토큰 모양이 있나 — 저장 검사기(`secret_spots`)나 가리기 엔진(`would_be_masked`)이 하나라도 건드리면 참이다(그 글은 클립보드로 보내지 않는다). 작업 스레드에서 부른다(글 흐름 1b, D-643)."""
    return isinstance(text, str) and bool(text) and bool(secret_spots("", text) or would_be_masked(text))


def naver_url_problem(text):
    """발행 주소 칸의 글 → 문제 열쇠(`empty`·`space`·`long`·`secret`·`scheme`·`host`·`path`) 또는 ''(통과). **글은 되풀이하지 않는다.** 서비스(`content/model.py` 의 `_published_url`)가 한 번 더 보지만
    화면이 먼저 거른다(글 흐름 1b, D-645): 앞뒤 공백은 떼고 보고, 안에 공백이 있거나 500자를 넘으면 거절한다. 키·토큰 모양(저장 검사기 + 가리기 엔진)·`https` 아님·주소 앞쪽 계정 정보나 포트·네이버 블로그 주소 아님·글 주소(경로) 없음도 거절한다."""
    url = text.strip() if isinstance(text, str) else ""
    if not url:
        return "empty"
    if any(char.isspace() for char in url):
        return "space"
    if len(url) > MAX_URL:
        return "long"
    if secret_spots("", url) or would_be_masked(url):
        return "secret"
    if not url.lower().startswith("https://"):
        return "scheme"
    rest = url[len("https://"):]
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if authority.lower() not in NAVER_HOSTS:
        return "host"
    path = rest[len(authority):]
    if not path.startswith("/") or len(path) < 2 or path[1] in "/?#":
        return "path"
    return ""


def text_blocks(title, body, references=(), assets=(), extra=()):
    """글 자신(제목·본문·출처·이미지 이름과 설명)이 승인을 막는 이유들 → `("health",)`·`("secret",)` 같은 튜플(막는 것이 없으면 비어 있다). 컨트롤러의 검토 결과와 별개로 **공급자가 승인 직전에 글을 다시 읽어 한 번 더** 건다 — 화면 틀이 어긋나도 막힌 글이 승인되지 않게.
    `extra` 는 건강 효과 단정 판정에 더 거는 (이름, 조각들) 쌍들(Pages 한 줄 설명·태그 — `pages_health_extra`)이다."""
    found = []
    if health_of(title, body, extra).stage == HEALTH_STOP:
        found.append("health")
    if secret_spots(title, body, references, assets):
        found.append("secret")
    return tuple(found)


# ---- 발행 전 검사 코드 -------------------------------------------------------------------------------------------------------------------
def code_of(reason):
    """서비스 관문 사유 한 줄(`[LEN_BODY] 본문 …`) → 코드(`LEN_BODY`), 모양이 다르면 빈 글."""
    if isinstance(reason, str) and reason.startswith("["):
        code = reason[1:].split("]", 1)[0]
        return code if _CODE.fullmatch(code) else ""
    return ""


def gate_sentence(code):
    """검사 코드 → 쉬운 한 문장(무엇이 문제이고 어떻게 고치나). 모르는 코드는 일반 문장이다."""
    key = f"post_gate_{code.lower()}" if isinstance(code, str) and _CODE.fullmatch(code) else ""
    return T.get(key) or T["post_gate_other"]


def unique_codes(reasons):
    """사유 줄들 → 처음 나온 순서의 코드들(중복 없음, 코드가 없는 줄은 건너뛴다)."""
    found = []
    for reason in reasons:
        code = code_of(reason)
        if code and code not in found:
            found.append(code)
    return tuple(found)


# ---- 승인 조건 -------------------------------------------------------------------------------------------------------------------------------
def review_blocks(review):
    """검토 결과의 막힘 이유들 → 열쇠 튜플(`gate`·`health`·`secret`·`similarity`·`incomplete`). 비어 있으면 승인을 막는 것이 없다.
    **막힘 판단이 빠진 결과**(건강 판정이 없음 등)는 믿지 않는다 — `incomplete` 로 막는다."""
    blocks = []
    if review is None:
        return ("incomplete",)
    if not review.gate_ok:
        blocks.append("gate")
    if review.health is None:
        blocks.append("incomplete")
    elif review.health.stage == HEALTH_STOP:
        blocks.append("health")
    if review.spots:
        blocks.append("secret")
    if review.similarity is not None and review.similarity.blocks:
        blocks.append("similarity")
    return tuple(blocks)


def approval_state(review, detail, platform, *, busy=False, restoring=False, allow_similarity=False):
    """`승인하기` 를 켤 수 있나 → (가능한가, 이유 문구 열쇠 — 가능하면 빈 글). 규칙 전부가 여기 한 곳이다:
    ① 복원이 도는 중이 아니다 ② 쓰기가 돌고 있지 않다 ③ 그 플랫폼의 상태가 '검토 중' ④ 이 앱을 연 뒤 **이 글·이 플랫폼**의 검토 결과를 받았다 ⑤ 그 결과가 **지금 글의 판**의 것이다 ⑥ 막힘이 없다.
    `allow_similarity` 면(`그래도 승인하기` — 글 흐름 1b, D-646) ⑥ 이 바뀐다: 막힘이 **정확히 유사도 하나뿐**일 때만 가능하다(다른 막힘이 하나라도 있으면 그대로 막힌다)."""
    if restoring:
        return False, "post_approve_why_restoring"
    if busy:
        return False, "post_approve_why_busy"
    state = detail.platform(platform) if detail is not None else None
    if state is None or state.status != st.REVIEW_REQUIRED:
        return False, "post_approve_why_none" if state is None or state.status in (st.NOT_STARTED, st.DRAFT_GENERATED, st.PUBLISH_FAILED) else "post_approve_why_state"
    if review is None or review.project_id != detail.project_id or review.platform != platform:
        return False, "post_res_lost"
    if review.revision != detail.revision or state.rendered_revision != detail.revision:
        return False, "post_approve_why_stale"
    blocks = review_blocks(review)
    if allow_similarity:
        if blocks != ("similarity",):
            return False, "post_approve_why_blocked"
        return True, ""
    if blocks:
        return False, "post_approve_why_blocked"
    return True, ""


# ---- Pages 검토 값 ---------------------------------------------------------------------------------------------------------------------------
def split_tags(text):
    """쉼표(반각·전각)로 나눠 적은 태그 글 → 태그 튜플(빈 조각은 버린다)."""
    return tuple(part.strip() for part in re.split(r"[,，、]", text if isinstance(text, str) else "") if part.strip())


def pages_problems(raw):
    """Pages 검토 값 칸(`category`·`lang`·`image_url`·`tags`·`description` — 모두 글) → `{칸 이름: 문장 열쇠}`(문제가 없으면 비어 있다). 한도는 렌더러의 값이다. 서비스가 한 번 더 엄격히 본다."""
    problems = {}
    category = (raw.get("category") or "").strip()
    if not category or len(category) > MAX_CATEGORY or any(ord(char) < 32 for char in category):
        problems["category"] = "post_pv_p_category"
    if raw.get("lang") not in ("ko", "en"):
        problems["lang"] = "post_pv_p_lang"
    image = (raw.get("image_url") or "").strip()
    if not re.fullmatch(r"https://[^\s/?#]+[^\s]*", image) or len(image) > 1500:
        problems["image_url"] = "post_pv_p_image"
    tags = split_tags(raw.get("tags") or "")
    if len(tags) > MAX_TAGS or any(len(tag) > MAX_TAG for tag in tags):
        problems["tags"] = "post_pv_p_tags"
    if len((raw.get("description") or "").strip()) > MAX_DESCRIPTION:
        problems["description"] = "post_pv_p_desc"
    return problems


def pages_values_of(raw):
    """검사를 통과한 칸 → `PagesValues`."""
    return PagesValues((raw.get("category") or "").strip(), raw.get("lang") or "", (raw.get("image_url") or "").strip(), split_tags(raw.get("tags") or ""), (raw.get("description") or "").strip())


def pages_raw_of(values):
    """`PagesValues` → 칸 글(대화의 처음 값 — 지난번에 쓴 값을 다시 채울 때)."""
    if values is None:
        return {"category": "", "lang": "ko", "image_url": "", "tags": "", "description": ""}
    return {"category": values.category, "lang": values.lang or "ko", "image_url": values.image_url, "tags": ", ".join(values.tags), "description": values.description}


def title_of(name):
    """파일 이름 → 제목 칸의 제안(확장자를 뗀 이름). 이름이 없으면 빈 글."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return stem.strip()[:200]


__all__ = ["APPROVED_NOW", "COPYABLE", "MAX_URL", "NAVER_HOSTS", "text_blocks", "BLOCK_LIMIT", "HealthReview", "PAGE", "PREVIEW_BLOCKS", "PREVIEW_CHARS", "REVIEWABLE", "approval_state", "build_preview", "code_of", "copy_blocked",
           "gate_sentence", "health_of", "naver_url_problem", "pages_health_extra", "pages_problems", "pages_raw_of", "pages_values_of", "platform_text", "review_blocks", "secret_spots", "shown", "split_tags", "status_text",
           "title_of", "unique_codes", "when_text", "would_be_masked"]
