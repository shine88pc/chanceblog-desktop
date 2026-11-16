"""블로그 프로필 폼의 순수 규칙(P4b) — 칸 표·값을 다듬는 방법·칸마다 쉬운 오류 문장·변경 감지·복제 가능 여부·확인창 글. PySide6 도 파일도 모른다.

**서비스가 이미 가진 칸·검증 규칙을 그대로 쓴다**: 칸의 한도는 `topics/channels.py` 의 상수(`MAX_ALIAS` …)를 그대로 가져오고, 글을 한 줄로 다듬는 `clean_line`·위험한 표기를 찾는 `find_markup`·블로그 ID/주소 검사(`_blog_ref`)도 서비스의 것을 부른다.
이 모듈은 어떤 규칙에 걸렸는지(`required`·`too_long`·`too_many`·`item_too_long`·`duplicate`·`markup`·`bad_ref`·`bad_choice`·`bad_path`·`overlap`)를 가려 칸 옆에 보일 **쉬운 문장**을 만들 뿐이다 — 판정은 서비스 생성자와 같다(시험이 수백 가지 입력으로 둘의 판정을 견준다).
**주제 설정 칸(P4c)**: 우선 키워드·제외 키워드(낱말 목록 — 주요 주제와 같은 `words` 종류)와 선호 글 유형(`multi` 칩 — 협찬 분야와 같은 종류)이다. 우선·제외에 **같은 낱말(대소문자 구분 없이)이 있으면 두 칸 모두** `overlap` 이다(`overlap_names` — 칸 하나만 보면 알 수 없고 두 칸의 최종 값을 견준다).
`multi` 는 칸마다 고를 수 있는 값(`options`)·최대 개수(`count`)·목록에 없는 저장된 값 보존 여부(`keep_extra` — 협찬 분야만)를 가진다. 글 유형의 이름은 서비스의 `POST_TYPES` 값 자체가 한글 이름이라 그대로 쓴다(이름표를 따로 베끼지 않는다).
저장 직전의 진짜 심판은 서비스(`ChannelProfile` 생성자)이고, 키·토큰 모양 글(`key_shape`)은 서비스가 저장 전에 거른다.

값의 모양: 폼이 들고 있는 **입력값**(raw)은 칸마다 글(`line`·`ref`·`words`·`path`·`choice`)·켜짐 여부(`flag`)·고른 분야들(`multi`)이고, 서비스로 보낼 **값**(typed)은 다듬은 글·낱말 목록(tuple)·`None`(색 없음)이다.
실제 블로그 이름·아이디는 이 코드에 없다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...content.profiles import POST_TYPES
from ...content.profiles import clean_line as _service_clean_line
from ...content.profiles import find_markup
from ...errors import AppError
from ...topics import channels as ch
from ...topics import wording
from . import blog_options as bo
from .text import T, display_text

SLOTS = ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b")                 # 서비스 슬롯과 같다(시험이 견준다)
GENERATION_SLOTS = ("naver_a", "naver_b")                                                   # 후보 만들기를 켜고 끌 수 있는 슬롯
SLOT_KINDS = (("naver_a", "naver_b"), ("blogger_ko", "blogger_en"), ("github_pages",))      # 복제는 같은 종류끼리만
KIND_KEY = {"naver_a": "naver", "naver_b": "naver", "blogger_ko": "blogger", "blogger_en": "blogger", "github_pages": "github"}
KINDS = tuple(KIND_KEY[slots[0]] for slots in SLOT_KINDS)                                  # 블로그 종류(사용자가 '블로그 추가' 에서 고르는 것) — 화면에 보이는 순서: 네이버·Blogger·GitHub Pages
KIND_SLOTS = {KIND_KEY[slots[0]]: slots for slots in SLOT_KINDS}                            # 종류 → 그 종류가 속에서 쓰는 슬롯들(채우는 순서 — 네이버 2·Blogger 2·GitHub 1)
SECTIONS = ("basic", "more", "topic", "look")                                               # 기본 정보 → 자세한 정보 → 주제 설정(P4c) → 모양
KEYWORD_FIELDS = ("priority_keywords", "exclude_keywords")                                  # 서로 같은 낱말이 없어야 하는 두 칸(서비스의 `KEYWORD_FIELDS` 와 같다 — 시험이 견준다)
TAG_ORDER = tuple(wording.TAG_KO)                                                           # 협찬 가능 분야 여섯(서비스의 이름표가 있는 것) — 고르는 순서
PRESET_ORDER = ("", *ch.COLOR_PRESETS)                                                      # 색 프리셋 — 빈 글은 '정하지 않음'
WORD_SEPARATORS = (",", "，", "、", ";", "\n")                                              # 낱말 칸에서 낱말을 나누는 글자(가운뎃점은 낱말 안에 쓰이므로 나누지 않는다)
DATA_PREFIXES = ("data:", "javascript:", "vbscript:")


@dataclass(frozen=True)
class FieldSpec:
    name: str                       # 서비스 칸 이름
    kind: str                       # line · ref · words · path · choice · multi · flag
    section: str                    # basic · more · topic · look
    limit: int = 0                  # line·ref·path 의 글자 수 상한 / words 의 낱말 하나 상한
    count: int = 0                  # words 의 낱말 수 상한 / multi 의 고를 수 있는 최대 개수
    required: bool = False
    options: tuple = ()             # multi 의 고를 수 있는 값들(보여 줄 순서) — 칸마다 다르다
    keep_extra: bool = False        # multi: 목록에 없는 저장된 값(손으로 고친 파일의 것)을 그대로 보존한다 — 협찬 분야만(글 유형은 서비스가 목록 밖 값을 거절한다)
    texts: str = ""                 # multi: 칩 이름을 `T` 에서 찾는 열쇠의 앞머리(예: `bf_tag_`) — 없으면 값이 곧 한글 이름이다(글 유형)
    choices: tuple = ()             # line: 하나만 고르는 보기(대상 독자·문체·채널 역할) — 보기 밖의 글은 '직접 입력' 이고 지우지 않는다
    suggest: tuple = ()             # words: 프로그램이 제안하는 낱말(여러 개 고르는 칩) — 직접 추가는 보조로 남는다
    assist: str = ""                # line: 제안 문장을 보이는 칸(`alias` 종류+번호 · `intro` 고른 값으로 만든 소개글)

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
    FieldSpec("alias", "line", "more", ch.MAX_ALIAS, assist="alias"),
    FieldSpec("channel_role", "line", "more", ch.MAX_ROLE, choices=bo.ROLE_CHOICES),
    FieldSpec("main_topics", "words", "more", ch.MAX_TOPIC_WORD, ch.MAX_MAIN_TOPICS, suggest=bo.WORD_SUGGESTIONS["main_topics"]),
    FieldSpec("audience", "line", "more", ch.MAX_AUDIENCE, choices=bo.AUDIENCE_CHOICES),
    FieldSpec("tone", "line", "more", ch.MAX_TONE, choices=bo.TONE_CHOICES),
    FieldSpec("categories", "words", "more", ch.MAX_CATEGORY_WORD, ch.MAX_CATEGORIES, suggest=bo.WORD_SUGGESTIONS["categories"]),
    FieldSpec("intro", "line", "more", ch.MAX_INTRO, assist="intro"),
    FieldSpec("monetization_focus", "multi", "more", count=ch.MAX_FOCUS, options=TAG_ORDER, keep_extra=True, texts="bf_tag_"),
    FieldSpec("priority_keywords", "words", "topic", ch.MAX_KEYWORD_WORD, ch.MAX_KEYWORDS, suggest=bo.WORD_SUGGESTIONS["priority_keywords"]),
    FieldSpec("exclude_keywords", "words", "topic", ch.MAX_KEYWORD_WORD, ch.MAX_KEYWORDS, suggest=bo.WORD_SUGGESTIONS["exclude_keywords"]),
    FieldSpec("preferred_post_types", "multi", "topic", count=len(POST_TYPES), options=POST_TYPES),
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
        picked = (raw,) if isinstance(raw, str) else tuple(raw or ())
        return tuple(value for value in spec.options if value in picked) + tuple(value for value in picked if value not in spec.options)      # 아는 값은 정해진 순서로, 모르는 값은 뒤에 그대로(문제인지는 `problem_of` 가 본다)
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
        allowed = set(spec.options) | (set(extra_tags) if spec.keep_extra else set())
        return "" if len(typed) <= spec.count and len(set(typed)) == len(typed) and all(value in allowed for value in typed) else "bad_choice"
    return ""


def overlap_names(typed):
    """우선·제외 키워드에 같은 낱말(대소문자 구분 없이 — 서비스 생성자와 같은 규칙)이 있으면 두 칸의 이름, 없으면 빈 튜플. 두 칸의 값이 모두 있어야 견준다(칸 하나만으로는 알 수 없다)."""
    first, second = (typed.get(name) for name in KEYWORD_FIELDS)
    if not isinstance(first, (tuple, list)) or not isinstance(second, (tuple, list)):
        return ()
    same = {word.casefold() for word in first if isinstance(word, str)} & {word.casefold() for word in second if isinstance(word, str)}
    return KEYWORD_FIELDS if same else ()


def check_fields(key, typed, extra_tags=()):
    """칸마다 따로(서비스가 칸을 하나씩 보는 것과 같다) — 서비스로 보낼 값(칸 이름 → 값)의 문제들 `{칸 이름: 문제 이름}`. 없으면 빈 사전, 모르는 칸은 건너뛴다. 칸 사이 규칙은 보지 않는다(`check_typed`)."""
    found = {}
    for spec in fields_for(key):
        if spec.name in typed:
            problem = problem_of(spec, typed[spec.name], extra_tags)
            if problem:
                found[spec.name] = problem
    return found


def check_typed(key, typed, extra_tags=()):
    """서비스로 보낼 값(칸 이름 → 값)의 문제들 `{칸 이름: 문제 이름}` — 칸마다의 문제 + 칸 사이 규칙(우선·제외 키워드에 같은 낱말 → 두 칸 모두 `overlap`, 그 칸에 다른 문제가 이미 있으면 그 문제가 먼저다). 없으면 빈 사전."""
    found = check_fields(key, typed, extra_tags)
    for name in overlap_names(typed):
        found.setdefault(name, "overlap")
    return found


def check_all(key, raw_values, extra_tags=()):
    """폼 입력값 전체의 문제들 `{칸 이름: 문제 이름}`."""
    return check_typed(key, typed_values(key, raw_values), extra_tags)


OVERLAP_TEXT = {"priority_keywords": "bf_err_overlap_priority_keywords", "exclude_keywords": "bf_err_overlap_exclude_keywords"}


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
    if problem == "overlap":
        return T[OVERLAP_TEXT.get(spec.name, "bf_err_invalid")]                                          # 어느 칸이 문제인지 — 그 칸 기준으로 '다른 칸에도 있는 낱말이 있어요'(입력한 낱말은 되풀이하지 않는다)
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


def clone_state(slots, key, reserved=()):
    """`key` 를 복제할 수 있나 → `(가능한가, 안 되는 이유 글, 복제해 넣을 슬롯 열쇠 또는 None)`. `slots` 는 `{열쇠: 입력값}`. `reserved` 는 지금 새 블로그로 열어 둔 슬롯들 — 비어 있어도 복제해 넣지 않는다(입력 중인 것을 덮지 않는다)."""
    if not slots[key].get("blog_ref"):
        return False, T["blogs_clone_no_source"], None
    for other in kind_of(key):
        if other != key and other in slots and other not in reserved and is_empty_values(other, slots[other]):
            return True, "", other
    return False, T["blogs_clone_no_target"], None


# ---- 등록한 블로그만 카드로 · 종류로 빈 슬롯 찾기(P4b 의 다섯 슬롯은 그대로 — 사용자 눈에서만 숨는다) ----------------------------------------------------
def is_registered(raw_values):
    """등록된 블로그 — 블로그 ID 또는 주소가 있다(서비스 `blog_profiles.is_registered` 와 같다 — 시험이 견준다)."""
    return bool(raw_values.get("blog_ref"))


def is_listed(key, raw_values, adding=False):
    """카드로 보이는 슬롯 — ① 등록됐거나 ② (손으로 고친 파일처럼) 주소 없이 내용이 있거나 ③ 지금 새 블로그로 열어 둔 것. 안 보이는 슬롯은 폼 칸이 모두 기본값인 빈 슬롯이라 '블로그 추가' 에서만 쓰인다 — 내용이 있는 슬롯이 숨어 덮어써지는 일이 없다."""
    return bool(adding) or is_registered(raw_values) or not is_empty_values(key, raw_values)


def free_slot(kind, slots, adding=()):
    """그 종류에서 새 블로그를 넣을 빈 슬롯 — 카드로 보이지 않는 첫 슬롯(`KIND_SLOTS` 의 채우는 순서). 없으면 None. `slots` 는 `{열쇠: 입력값}`, `adding` 은 지금 새 블로그로 열어 둔 슬롯들."""
    return next((key for key in KIND_SLOTS[kind] if key in slots and not is_listed(key, slots[key], key in adding)), None)


def free_count(kind, slots, adding=()):
    """그 종류에 남은 빈 슬롯의 수(네이버 2·Blogger 2·GitHub Pages 1 이 끝이다)."""
    return sum(1 for key in KIND_SLOTS[kind] if key in slots and not is_listed(key, slots[key], key in adding))


def form_base(key, stored_raw):
    """폼의 바탕값 — 저장된 값이다. 단 폼 칸이 모두 기본값인 빈 슬롯은 이름 칸이 빈 글이다(기본 프로필의 이름은 슬롯 이름이라 사용자에게 보이지 않는 말이고, 새 블로그의 이름은 사용자만 안다)."""
    return {**stored_raw, "display_name": ""} if is_empty_values(key, stored_raw) else stored_raw


def suggest_alias(key):
    """별명 제안 — 블로그 종류 + 그 종류 안의 번호(`네이버 블로그 1`). 슬롯 이름(`네이버 A`)이 아니라 사용자가 알아볼 말이다."""
    return f"{T['blogs_kind_' + KIND_KEY[key]]} {KIND_SLOTS[KIND_KEY[key]].index(key) + 1}"


def card_title(key, alias=""):
    """카드·폼 머리의 이름 — 별명이 있으면 별명(키·토큰 모양은 가린다), 없으면 종류 + 번호 제안."""
    alias = clean_line(alias)
    return shown(alias, ch.MAX_ALIAS) if alias else suggest_alias(key)


def suggest_intro(raw_values):
    """소개글 제안 — 폼의 지금 입력값(채널 역할·대상 독자·문체·주요 주제, 주요 주제가 없으면 카테고리)으로 만든 문장. 만들 재료가 없으면 빈 글."""
    topics = split_words(raw_values.get("main_topics")) or split_words(raw_values.get("categories"))
    return bo.suggest_intro(clean_line(raw_values.get("channel_role")), clean_line(raw_values.get("audience")), clean_line(raw_values.get("tone")), topics)


def picked_words(text):
    """낱말 칸의 글에서 고른 낱말들 — 대소문자 구분 없는 비교 열쇠(서비스의 중복·겹침 규칙과 같은 `casefold`)."""
    return frozenset(word.casefold() for word in split_words(text))


def toggle_word(text, word):
    """낱말 칸의 글에서 낱말 하나를 켜고 끈 새 글 — 있으면(대소문자 구분 없이) 모두 빼고 없으면 맨 뒤에 붙인다. 나머지 낱말과 순서는 그대로라 켰다 끄면 같은 낱말 목록으로 돌아온다."""
    words = split_words(text)
    if word.casefold() in {item.casefold() for item in words}:
        words = tuple(item for item in words if item.casefold() != word.casefold())
    else:
        words += (word,)
    return ", ".join(words)


def line_choice_state(spec, raw, custom_opened=False):
    """보기가 있는 한 줄 칸의 모습 → `(직접 입력인가, 고른 보기 또는 빈 글)`. 직접 입력 = '직접 입력' 을 눌렀거나 입력한 글이 보기에 없다(손으로 쓴 값은 지우지 않고 입력 칸에 그대로 보인다)."""
    typed = clean_line(raw)
    custom = bool(custom_opened) or (bool(typed) and typed not in spec.choices)
    return custom, "" if custom else typed


def option_label(spec, value):
    """칩 하나의 이름 — 협찬 분야는 쉬운 이름표(`texts` 앞머리의 문구), 글 유형은 서비스가 정한 값이 곧 한글 이름이다."""
    return T[spec.texts + value] if spec.texts and (spec.texts + value) in T else value


def options_of(spec):
    """`multi` 칸의 칩 선택지 `[{"value", "label"}]`(보여 줄 순서)."""
    return [{"value": value, "label": option_label(spec, value)} for value in spec.options]


def shown(value, limit):
    """화면에 나가는 사용자 글 — 키·토큰 모양을 가린 뒤 줄인다(가리기가 먼저, 자르기가 나중이다)."""
    return display_text(value, limit)


def preset_name(preset):
    return T["bf_preset_" + preset] if preset else T["bf_preset_none"]
