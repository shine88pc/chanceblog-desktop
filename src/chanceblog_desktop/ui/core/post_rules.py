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
from datetime import datetime, timedelta, timezone

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
_TAG = re.compile(r"^<([a-z0-9]+)")
_KEY_HEAD = re.compile(r"-----BEGIN [A-Z ]{0,100}PRIVATE KEY(?: BLOCK)?-----")               # 개인 키 블록의 머리·꼬리 줄(엔진 `_PEM` 과 같은 모양 — PGP 는 `… PRIVATE KEY BLOCK-----`)
_KEY_TAIL = re.compile(r"-----END [A-Z ]{0,100}PRIVATE KEY(?: BLOCK)?-----")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,39}")
_STAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$")


def shown(value, limit=300):
    """화면에 나가는 동적 글을 비밀 모양을 가린 한 줄로 줄인다(가리기가 먼저, 줄이기가 나중이다)."""
    return display_text(value, limit)


def would_be_masked(value):
    """가리기 엔진이 이 글에서 무언가를 가리는가 — 저장 검사기(`secret_spots`)가 아는 여섯 유형뿐 아니라 엔진이 아는 모든 모양(Slack·Stripe·OpenAI·Anthropic 키·주소 속 사용자 정보 …)을 본다.
    이 앱을 연 동안 기억해 칸에 다시 채울 값처럼 '키 모양이 하나라도 있으면 내보내지 않을 글' 을 가릴 때 쓴다(독립 검증 S 참고-2). 글이 아니거나 비었으면 False."""
    if not isinstance(value, str) or not value.strip():
        return False
    flat = " ".join(value.split())
    return display_text(flat, len(flat) + 64) != flat


def when_text(stamp):
    """글에 적힌 UTC 시각(`2026-11-24T05:30:12Z`) → 한국 시각 `2026-11-24 14:30`. 모양이 다르면 빈 글(지어내지 않는다). 시계를 읽지 않는다."""
    found = _STAMP.match(stamp) if isinstance(stamp, str) else None
    if found is None:
        return ""
    try:
        moment = datetime(*(int(part) for part in found.groups()), tzinfo=timezone.utc).astimezone(KST)
    except ValueError:
        return ""
    return moment.strftime("%Y-%m-%d %H:%M")


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


def _key_open_after(plain, inside):
    """이 글 조각을 읽고 난 뒤에도 개인 키 블록(PEM·PGP)이 **열려 있나** — 머리(`-----BEGIN … PRIVATE KEY-----`)를 만나면 가장 가까운 꼬리(`-----END … PRIVATE KEY-----`)까지, 꼬리가 없으면 글 끝까지가 한 덩어리다
    (가리기 엔진 `security/mask.py` 의 개인 키 규칙과 같다 — 머리 줄만이 아니라 본문까지). `inside` 는 이 조각에 들어올 때 이미 열려 있었는가. 머리·꼬리의 라벨은 100자까지(되돌아가는 비용을 막는다)."""
    pos = 0
    while True:
        found = (_KEY_TAIL if inside else _KEY_HEAD).search(plain, pos)
        if found is None:
            return inside
        inside, pos = not inside, found.end()


def _key_groups(entries):
    """(종류, 글) 목록 → 개인 키 블록을 **한 덩어리로 묶은** (종류, 글) 목록. 블록은 빈 줄마다 나뉘는데 실제 PGP 키는 머리 줄 뒤에 빈 줄이 있어, 블록마다 따로 가리면 머리 줄만 가려지고 본문 줄이
    그대로 나간다 — 머리가 열린 블록부터 꼬리가 든 블록까지(사이에 빈 줄·소제목·목록·인용이 끼어도, 꼬리가 없으면 글 끝까지)를 한 글로 이어 붙여 엔진이 머리부터 꼬리까지 한 번에 가리게 한다.
    묶인 덩어리의 종류는 머리가 든 블록의 종류다. 꼬리 뒤에 이어지는 같은 블록의 글은 그대로 남는다."""
    groups, inside = [], False
    for kind, plain in entries:
        if inside:
            groups[-1][1].append(plain)
        else:
            groups.append((kind, [plain]))
        inside = _key_open_after(plain, inside)
    return [(kind, "\n\n".join(parts)) for kind, parts in groups]


def build_preview(markdown, *, refs=0, assets=0):
    """원고(Markdown) → `PostPreview`. 서비스의 안전 변환이 만든 블록에서 글자만 뽑는다 — 글 속의 HTML 태그·스크립트는 변환기가 글자로 바꾸고, 여기서는 그 글자를 그대로(가려서) 내보낼 뿐 해석하지 않는다.
    이미지·링크는 내보내지 않는다(이미지는 개수만). 개인 키 블록은 머리부터 꼬리까지 한 덩어리로 가린다(`_key_groups`). 변환이 거절하는 아주 큰 글(2,000,000자 초과)은 빈 미리보기다.
    아주 병적인 글(인용 기호만 2MB 가까이 같은 글)은 글자 뽑기에서 예외가 날 수 있다 — 저장된 글에서는 화면의 10만 자 한도 안에서 만들어지지 않고, 나면 화면이 오류 상태로 안전하게 닫는다(빈 미리보기로 속이지 않는다)."""
    from ...render.markdown import html_to_text, markdown_blocks
    text = markdown if isinstance(markdown, str) else ""
    try:
        html_blocks, images = markdown_blocks(text)
    except Exception:                                        # 변환이 받지 않는 글(2,000,000자 초과) — 저장된 글에는 없지만 변환기가 받지 않는 값은 빈 미리보기다
        return PostPreview((), 0, 0, 0, int(refs), False)
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
    kept, total, chars, used = [], 0, 0, 0
    for kind, plain in _key_groups(entries):
        total += 1
        chars += len(re.sub(r"\s+", "", plain))
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


def health_of(title, body):
    """제목·본문의 건강 효과 단정 판정 → `HealthReview` — 초안 작성 화면의 복사 관문과 **같은 함수**(`drafts.review_health`)를 글 조각(문장)마다 따로 건다."""
    return review_health((T["drf_where_title"], (title,) if isinstance(title, str) else ()), (T["drf_where_body"], health_units(body)))


def text_blocks(title, body, references=(), assets=()):
    """글 자신(제목·본문·출처·이미지 이름과 설명)이 승인을 막는 이유들 → `("health",)`·`("secret",)` 같은 튜플(막는 것이 없으면 비어 있다). 컨트롤러의 검토 결과와 별개로 **공급자가 승인 직전에 글을 다시 읽어 한 번 더** 건다 — 화면 틀이 어긋나도 막힌 글이 승인되지 않게."""
    found = []
    if health_of(title, body).stage == HEALTH_STOP:
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


def approval_state(review, detail, platform, *, busy=False, restoring=False):
    """`승인하기` 를 켤 수 있나 → (가능한가, 이유 문구 열쇠 — 가능하면 빈 글). 규칙 전부가 여기 한 곳이다:
    ① 복원이 도는 중이 아니다 ② 쓰기가 돌고 있지 않다 ③ 그 플랫폼의 상태가 '검토 중' ④ 이 앱을 연 뒤 **이 글·이 플랫폼**의 검토 결과를 받았다 ⑤ 그 결과가 **지금 글의 판**의 것이다 ⑥ 막힘이 없다."""
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
    if review_blocks(review):
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


__all__ = ["APPROVED_NOW", "text_blocks", "BLOCK_LIMIT", "HealthReview", "PAGE", "PREVIEW_BLOCKS", "PREVIEW_CHARS", "REVIEWABLE", "approval_state", "build_preview", "code_of", "gate_sentence", "health_of", "pages_problems",
           "pages_raw_of", "pages_values_of", "platform_text", "review_blocks", "secret_spots", "shown", "split_tags", "status_text", "title_of", "unique_codes", "when_text", "would_be_masked"]
