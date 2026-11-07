"""블로그 프로필 폼의 순수 규칙(P4b) — 칸 표·값을 다듬는 방법·칸마다 쉬운 오류 문장·변경 감지·복제 가능 여부·확인창 글. PySide6 도 파일도 모른다.

**서비스가 이미 가진 칸·검증 규칙을 그대로 쓴다**: 칸의 한도는 `topics/channels.py` 의 상수(`MAX_ALIAS` …)를 그대로 가져오고, 글을 한 줄로 다듬는 `clean_line`·위험한 표기를 찾는 `find_markup`·블로그 ID/주소 검사(`_blog_ref`)도 서비스의 것을 부른다.
이 모듈은 어떤 규칙에 걸렸는지(`required`·`too_long`·`too_many`·`item_too_long`·`duplicate`·`markup`·`bad_ref`·`bad_choice`·`bad_path`)를 가려 칸 옆에 보일 **쉬운 문장**을 만들 뿐이다 — 판정은 서비스 생성자와 같다(시험이 수백 가지 입력으로 둘의 판정을 견준다).
저장 직전의 진짜 심판은 서비스(`ChannelProfile` 생성자)이고, 키·토큰 모양 글(`key_shape`)은 서비스가 저장 전에 거른다.

값의 모양: 폼이 들고 있는 **입력값**(raw)은 칸마다 글(`line`·`ref`·`words`·`path`·`choice`)·켜짐 여부(`flag`)·고른 분야들(`multi`)이고, 서비스로 보낼 **값**(typed)은 다듬은 글·낱말 목록(tuple)·`None`(색 없음)이다.
실제 블로그 이름·아이디는 이 코드에 없다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...content.profiles import clean_line as _service_clean_line
from ...content.profiles import find_markup
from ...errors import AppError
from ...topics import channels as ch
from ...topics import wording
from .text import T

SLOTS = ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b")                 # 서비스 슬롯과 같다(시험이 견준다)
GENERATION_SLOTS = ("naver_a", "naver_b")                                                   # 후보 만들기를 켜고 끌 수 있는 슬롯
SLOT_KINDS = (("naver_a", "naver_b"), ("blogger_ko", "blogger_en"), ("github_pages",))      # 복제는 같은 종류끼리만
KIND_KEY = {"naver_a": "naver", "naver_b": "naver", "blogger_ko": "blogger", "blogger_en": "blogger", "github_pages": "github"}
SECTIONS = ("basic", "more", "look")
TAG_ORDER = tuple(wording.TAG_KO)                                                           # 협찬 가능 분야 여섯(서비스의 이름표가 있는 것) — 고르는 순서
PRESET_ORDER = ("", *ch.COLOR_PRESETS)                                                      # 색 프리셋 — 빈 글은 '정하지 않음'
WORD_SEPARATORS = (",", "，", "、", ";", "\n")                                              # 낱말 칸에서 낱말을 나누는 글자(가운뎃점은 낱말 안에 쓰이므로 나누지 않는다)
DATA_PREFIXES = ("data:", "javascript:", "vbscript:")


@dataclass(frozen=True)
class FieldSpec:
    name: str                       # 서비스 칸 이름
    kind: str                       # line · ref · words · path · choice · multi · flag
    section: str                    # basic · more · look
    limit: int = 0                  # line·ref·path 의 글자 수 상한 / words 의 낱말 하나 상한
    count: int = 0                  # words 의 낱말 수 상한
    required: bool = False

    @property
    def label(self):
        return T["bf_label_" + self.name]

    def hint(self):
        key = "bf_hint_" + self.name
        return T[key].format(limit=self.limit, count=self.count) if key in T else ""


FIELDS = (
    FieldSpec("display_name", "line", "basic", ch.MAX_NAME, required=True),
    FieldSpec("blog_ref", "ref", "basic", ch.MAX_BLOG_REF, required=True),
    FieldSpec("language", "choice", "basic", required=True),
    FieldSpec("generation_enabled", "flag", "basic", required=True),                              # 필수 넷의 넷째(사용 여부) — 스위치라 늘 값이 있어 '비었다' 는 문제는 없고 '필수' 표시만 붙는다
    FieldSpec("alias", "line", "more", ch.MAX_ALIAS),
    FieldSpec("channel_role", "line", "more", ch.MAX_ROLE),
    FieldSpec("main_topics", "words", "more", ch.MAX_TOPIC_WORD, ch.MAX_MAIN_TOPICS),
    FieldSpec("audience", "line", "more", ch.MAX_AUDIENCE),
    FieldSpec("tone", "line", "more", ch.MAX_TONE),
    FieldSpec("categories", "words", "more", ch.MAX_CATEGORY_WORD, ch.MAX_CATEGORIES),
    FieldSpec("intro", "line", "more", ch.MAX_INTRO),
    FieldSpec("monetization_focus", "multi", "more"),
    FieldSpec("color_preset", "choice", "look"),
    FieldSpec("profile_image", "path", "look", ch.MAX_IMAGE_PATH),
    FieldSpec("cover_image", "path", "look", ch.MAX_IMAGE_PATH),
)
SPEC = {spec.name: spec for spec in FIELDS}


def fields_for(key):
    """그 슬롯의 폼 칸들(순서대로). 후보 만들기 칸은 네이버 A·B 만 가진다(그 밖의 슬롯은 이 화면이 그 값을 바꾸지 않는다)."""
    return tuple(spec for spec in FIELDS if spec.name != "generation_enabled" or key in GENERATION_SLOTS)


def kind_of(key):
    return next(kind for kind in SLOT_KINDS if key in kind)


# ---- 값 다듬기 --------------------------------------------------------------------------------------------------------------------
def clean_line(value):
    """한 줄 글로 — 서비스의 `content.profiles.clean_line` 과 같다(제어·서식 문자를 지우고 공백을 하나로 접는다). 순수 계산이라 서비스 것을 그대로 쓴다."""
    return _service_clean_line(value if isinstance(value, str) else "")


def split_words(text):
    """낱말 칸의 글 → 낱말들(쉼표·세미콜론·줄바꿈으로 나누고 각각 한 줄로 다듬고 빈 것은 뺀다)."""
    text = text if isinstance(text, str) else ""
    for separator in WORD_SEPARATORS[1:]:
        text = text.replace(separator, WORD_SEPARATORS[0])
    return tuple(word for word in (clean_line(piece) for piece in text.split(WORD_SEPARATORS[0])) if word)


def normalize(spec, raw):
    """입력값(raw) → 서비스로 보낼 값(typed). 글 칸은 한 줄로 다듬고 낱말 칸은 목록으로, 색 프리셋은 빈 글이면 None 이다."""
    if spec.kind in ("line", "path"):
        return clean_line(raw)
    if spec.kind == "ref":
        return raw.strip() if isinstance(raw, str) else ""
    if spec.kind == "words":
        return split_words(raw)
    if spec.kind == "multi":
        picked = set(raw or ())
        return tuple(tag for tag in TAG_ORDER if tag in picked) + tuple(tag for tag in (raw or ()) if tag not in TAG_ORDER)
    if spec.kind == "flag":
        return bool(raw)
    if spec.name == "color_preset":
        return raw or None
    return raw if isinstance(raw, str) else ""


def typed_values(key, raw_values):
    """슬롯의 폼 칸 전부의 서비스용 값."""
    return {spec.name: normalize(spec, raw_values.get(spec.name)) for spec in fields_for(key)}


def same_value(spec, first, second):
    """두 값이 같은 뜻인가 — 분야는 고른 순서와 상관없이, 나머지는 다듬은 값 그대로 견준다."""
    return set(first) == set(second) if spec.kind == "multi" else first == second


def dirty_names(key, base_raw, raw):
    """바뀐 칸의 이름들(순서대로) — 다듬은 값이 저장된 값과 다른 칸만이다(앞뒤 공백만 바꾼 것은 바뀐 것이 아니다)."""
    before, after = typed_values(key, base_raw), typed_values(key, raw)
    return tuple(spec.name for spec in fields_for(key) if not same_value(spec, before[spec.name], after[spec.name]))


# ---- 검사(서비스 생성자와 같은 판정, 이유만 더 잘게) ------------------------------------------------------------------------------------
def _ref_problem(value):
    if not value:
        return "required"
    if any(char.isspace() for char in value):
        return "bad_ref"
    if len(value) > ch.MAX_BLOG_REF:
        return "too_long"
    if find_markup(value):
        return "markup"
    try:
        ch._blog_ref(value)
    except AppError:
        return "bad_ref"
    return ""


def problem_of(spec, typed, extra_tags=()):
    """칸 하나의 문제 이름(`required`·`too_long`·`too_many`·`item_too_long`·`duplicate`·`markup`·`bad_ref`·`bad_choice`·`bad_path`) — 문제가 없으면 빈 글. 입력값이 아니라 **다듬은 값**을 본다."""
    if spec.kind == "ref":
        return _ref_problem(typed)
    if spec.kind in ("line", "path"):
        if spec.required and not typed:
            return "required"
        if len(typed) > spec.limit:
            return "too_long"
        if spec.kind == "path" and typed.lower().startswith(DATA_PREFIXES):                      # `data:` 는 위험한 표기이기도 하지만 이 칸에서는 '내용을 직접 넣을 수 없다' 가 더 알맞은 말이다
            return "bad_path"
        if find_markup(typed):
            return "markup"
        return ""
    if spec.kind == "words":
        if len(typed) > spec.count:
            return "too_many"
        if any(len(word) > spec.limit for word in typed):
            return "item_too_long"
        if len({word.casefold() for word in typed}) != len(typed):
            return "duplicate"
        return "markup" if any(find_markup(word) for word in typed) else ""
    if spec.name == "language":
        return "" if typed in ch.LANGUAGES else "bad_choice"
    if spec.name == "color_preset":
        return "" if typed is None or typed in ch.COLOR_PRESETS else "bad_choice"
    if spec.kind == "multi":
        allowed = set(TAG_ORDER) | set(extra_tags)
        return "" if len(typed) <= ch.MAX_FOCUS and all(tag in allowed for tag in typed) else "bad_choice"
    return ""


def check_typed(key, typed, extra_tags=()):
    """서비스로 보낼 값(칸 이름 → 값)의 문제들 `{칸 이름: 문제 이름}` — 없으면 빈 사전. 모르는 칸은 건너뛴다."""
    found = {}
    for spec in fields_for(key):
        if spec.name in typed:
            problem = problem_of(spec, typed[spec.name], extra_tags)
            if problem:
                found[spec.name] = problem
    return found


def check_all(key, raw_values, extra_tags=()):
    """폼 입력값 전체의 문제들 `{칸 이름: 문제 이름}`."""
    return check_typed(key, typed_values(key, raw_values), extra_tags)


def problem_text(spec, problem, raw=None):
    """문제 이름 → 칸 옆에 보일 쉬운 문장. `raw` 는 입력한 글(길이를 알려 주려고만 쓰고 문장에 되풀이하지 않는다)."""
    if not problem:
        return ""
    typed = normalize(spec, raw) if raw is not None else None
    if problem == "too_long":
        return T["bf_err_too_long"].format(limit=spec.limit, now=len(typed) if isinstance(typed, str) else 0)
    if problem == "too_many":
        return T["bf_err_too_many"].format(limit=spec.count, now=len(typed) if isinstance(typed, tuple) else 0)
    if problem == "item_too_long":
        return T["bf_err_item_too_long"].format(limit=spec.limit)
    key = {"required": "bf_err_required", "duplicate": "bf_err_duplicate", "markup": "bf_err_markup", "bad_ref": "bf_err_ref", "bad_choice": "bf_err_choice", "bad_path": "bf_err_path",
           "key_shape": "bf_err_key_shape", "invalid": "bf_err_invalid"}.get(problem, "bf_err_invalid")
    return T[key]


# ---- 슬롯 규칙(서비스와 같다) --------------------------------------------------------------------------------------------------------
def default_values(key):
    """그 슬롯의 기본 입력값(기본 프로필 — 새로 쓰는 PC 의 모습). 서비스의 `default_profile` 과 같은 값이다."""
    profile = next(item for item in ch.default_profiles() if item.key == key)
    return raw_from_profile(profile)


def raw_from_profile(profile):
    """채널 프로필(또는 같은 이름의 칸을 가진 값) → 그 슬롯 폼의 입력값."""
    values = {}
    for spec in fields_for(profile.key):
        value = getattr(profile, spec.name)
        if spec.kind == "words":
            values[spec.name] = ", ".join(value)
        elif spec.kind == "multi":
            values[spec.name] = tuple(value)
        elif spec.name == "color_preset":
            values[spec.name] = value or ""
        else:
            values[spec.name] = value
    return values


def is_empty_values(key, raw_values):
    """비어 있는 슬롯 — 폼 칸이 모두 기본값이다(이름 하나만 바꿔도 비어 있지 않다: 덮어써서 지우는 일이 없게 보존이 우선이다)."""
    return not dirty_names(key, default_values(key), raw_values)


def clone_state(slots, key):
    """`key` 를 복제할 수 있나 → `(가능한가, 안 되는 이유 글, 복제해 넣을 슬롯 열쇠 또는 None)`. `slots` 는 `{열쇠: 입력값}`."""
    if not slots[key].get("blog_ref"):
        return False, T["blogs_clone_no_source"], None
    for other in kind_of(key):
        if other != key and other in slots and is_empty_values(other, slots[other]):
            return True, "", other
    return False, T["blogs_clone_no_target"], None


def shown(value, limit):
    """화면에 나가는 사용자 글 — 키·토큰 모양을 가린 뒤 줄인다(가리기가 먼저, 자르기가 나중이다)."""
    from ...security.mask import safe_detail
    return safe_detail(value, limit)


def slot_title(key):
    return T["blogs_slot_" + key]


def preset_name(preset):
    return T["bf_preset_" + preset] if preset else T["bf_preset_none"]
