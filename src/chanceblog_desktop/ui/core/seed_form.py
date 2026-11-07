"""Seed 관리 화면의 폼 순수 규칙 — 칸 표(고치는 칸·새로 등록하는 칸)·값을 다듬는 방법·칸마다 쉬운 오류 문장·변경 감지. PySide6 도 파일도 모른다.

**서비스가 이미 가진 칸·검증 규칙을 그대로 쓴다**: 칸의 한도는 `topics/seeds.py` 의 상수(`MAX_KEYWORD`·`MAX_EXCLUDED`·`MAX_REASON` …)를 그대로 가져오고, 글을 한 줄로 다듬는 방법·위험한 표기를 찾는 `find_markup`·같은 낱말 열쇠 `keyword_key`·결과를 약속하는
표현 `forbidden_claim` 도 서비스의 것을 부른다. 이 모듈은 어떤 규칙에 걸렸는지(`required`·`too_long`·`too_many`·`item_too_long`·`duplicate`·`markup`·`overlap`·`no_letters`·`claim`·`same_word`·`channels_none`·`tag_needed`·`brand_reason`·`bad_choice`)를
가려 칸 옆에 보일 **쉬운 문장**을 만들 뿐이다 — 판정은 `Seed` 생성자와 같다(시험이 수백 가지 입력으로 둘의 판정을 견준다). 저장 직전의 진짜 심판은 서비스(`Seed` 생성자)이고, 키·토큰 모양 글(`key_shape`)은 서비스가 저장 전에 거른다.

값의 모양: 폼이 들고 있는 **입력값**(raw)은 칸마다 글(`line`·`words`)·켜짐 여부(`flag`)·고른 값들(`multi`)·고른 하나(`choice`)이고, 서비스로 보낼 **값**(typed)은 다듬은 글·낱말 목록(tuple)·채널 목록(tuple)·`None`(고르지 않음)이다.
실제 Seed 낱말·분류는 이 코드에 없다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...content.candidates import forbidden_claim, keyword_key
from ...content.profiles import find_markup
from ...topics import channels as ch
from ...topics import seeds as sd
from ...topics import wording
from .blog_form import clean_line, shown, split_words  # noqa: F401  — 같은 글 다듬기(한 줄·쉼표 낱말)와 가리고 줄이기를 그대로 쓴다
from .text import T

CHANNEL_ORDER = ch.CHANNELS                                                                    # 허용 채널을 고르는 순서(코드의 채널 순서)
SCOPE_ORDER = sd.SCOPES                                                                         # 소속: 공통 + 다섯 채널
IMPORTANCE_CREATE = tuple(item for item in sd.SEED_TYPES if item != sd.SEED_SEASONAL)           # 수동 등록의 중요도 — 계절형은 일정 칸이 있는 고급 편집이라 뺀다
TARGET_ORDER = sd.TARGET_TYPES                                                                  # 대상 유형 열한 가지(묶음 행 셋은 제안 파일 이름이라 고르는 칸에 없다)
TAG_ORDER = tuple(wording.TAG_KO)                                                               # 협찬 가능 분야 여섯


@dataclass(frozen=True)
class FieldSpec:
    name: str                       # 서비스 칸 이름
    kind: str                       # line · words · choice · multi · flag
    limit: int = 0                  # line 의 글자 수 상한 / words 의 낱말 하나 상한
    count: int = 0                  # words 의 낱말 수 상한
    required: bool = False

    @property
    def label(self):
        return T["sf_label_" + self.name]

    def hint(self):
        key = "sf_hint_" + self.name
        return T[key].format(limit=self.limit, count=self.count) if key in T else ""


EDIT_FIELDS = (
    FieldSpec("priority", "flag"),
    FieldSpec("excluded_keywords", "words", sd.MAX_EXCLUDED_WORD, sd.MAX_EXCLUDED),
    FieldSpec("priority_keywords", "words", sd.MAX_EXCLUDED_WORD, sd.MAX_PRIORITY_KEYWORDS),
    FieldSpec("allowed_channels", "multi"),
    FieldSpec("reason", "line", sd.MAX_REASON),
)
CREATE_FIELDS = (
    FieldSpec("keyword", "line", sd.MAX_KEYWORD, required=True),
    FieldSpec("major", "line", ch.MAX_NAME, required=True),
    FieldSpec("minor", "line", ch.MAX_NAME, required=True),
    FieldSpec("seed_type", "choice", required=True),
    FieldSpec("target_type", "choice", required=True),
    FieldSpec("scope", "choice", required=True),
    FieldSpec("allowed_channels", "multi"),
    FieldSpec("excluded_keywords", "words", sd.MAX_EXCLUDED_WORD, sd.MAX_EXCLUDED),
    FieldSpec("priority_keywords", "words", sd.MAX_EXCLUDED_WORD, sd.MAX_PRIORITY_KEYWORDS),
    FieldSpec("sponsor_tag", "choice"),
    FieldSpec("reason", "line", sd.MAX_REASON),
)
EDIT_SPEC = {spec.name: spec for spec in EDIT_FIELDS}
CREATE_SPEC = {spec.name: spec for spec in CREATE_FIELDS}


def edit_fields_for(seed):
    """그 씨앗의 고치는 칸들 — 허용 채널은 공통 씨앗만 가진다(채널 전용 씨앗은 그 채널 하나로 정해져 있다)."""
    return tuple(spec for spec in EDIT_FIELDS if spec.name != "allowed_channels" or seed.scope == sd.SCOPE_COMMON)


def create_fields_for(raw):
    """새로 등록하는 칸들 — 허용 채널은 소속이 공통일 때만, 협찬 분야는 중요도가 협찬 가능일 때만 보인다."""
    scope, kind = raw.get("scope"), raw.get("seed_type")
    return tuple(spec for spec in CREATE_FIELDS if (spec.name != "allowed_channels" or scope == sd.SCOPE_COMMON) and (spec.name != "sponsor_tag" or kind == "sponsorable"))


# ---- 값 다듬기 --------------------------------------------------------------------------------------------------------------------
def normalize(spec, raw):
    """입력값(raw) → 서비스로 보낼 값(typed). 글 칸은 한 줄로 다듬고 낱말 칸은 목록으로, 채널 칸은 코드 순서로, 고르는 칸은 비면 None 이다."""
    if spec.kind == "line":
        return clean_line(raw)
    if spec.kind == "words":
        return split_words(raw)
    if spec.kind == "flag":
        return bool(raw)
    if spec.kind == "multi":
        picked = set(raw or ())
        return tuple(code for code in CHANNEL_ORDER if code in picked)
    value = raw if isinstance(raw, str) else ""
    return value or None


def typed_values(fields, raw_values):
    return {spec.name: normalize(spec, raw_values.get(spec.name)) for spec in fields}


def dirty_names(fields, base_raw, raw):
    """바뀐 칸의 이름들(순서대로) — 다듬은 값이 저장된 값과 다른 칸만이다(앞뒤 공백만 바꾼 것은 바뀐 것이 아니다)."""
    before, after = typed_values(fields, base_raw), typed_values(fields, raw)
    return tuple(spec.name for spec in fields if before[spec.name] != after[spec.name])


def raw_from_seed(seed):
    """씨앗 → 고치는 폼의 입력값."""
    return {"priority": bool(seed.priority), "excluded_keywords": ", ".join(seed.excluded_keywords), "priority_keywords": ", ".join(seed.priority_keywords),
            "allowed_channels": tuple(seed.allowed_channels), "reason": seed.reason}


def new_raw():
    """새로 등록하는 폼의 처음 입력값 — 중요도만 '일반' 이고 나머지는 비어 있다(소속·대상 유형은 일부러 골라야 한다)."""
    return {"keyword": "", "major": "", "minor": "", "seed_type": "general", "target_type": "", "scope": "", "allowed_channels": (), "excluded_keywords": "", "priority_keywords": "", "sponsor_tag": "", "reason": ""}


# ---- 검사(서비스 `Seed` 생성자와 같은 판정, 이유만 더 잘게) ---------------------------------------------------------------------------------
def _line_problem(spec, text):
    if spec.required and not text:
        return "required"
    if len(text) > spec.limit:
        return "too_long"
    return "markup" if find_markup(text) else ""


def _words_problem(spec, words):
    if len(words) > spec.count:
        return "too_many"
    if any(len(word) > spec.limit for word in words):
        return "item_too_long"
    if len({word.casefold() for word in words}) != len(words):
        return "duplicate"
    return "markup" if any(find_markup(word) for word in words) else ""


def _keyword_problem(spec, text, scope, existing):
    found = _line_problem(spec, text)
    if found:
        return found
    if not keyword_key(text):
        return "no_letters"
    if forbidden_claim(text):
        return "claim"
    if scope in SCOPE_ORDER and any((seed.scope, keyword_key(seed.keyword)) == (scope, keyword_key(text)) for seed in existing):
        return "same_word"
    return ""


def _overlap(typed):
    excluded = {keyword_key(item) for item in typed.get("excluded_keywords", ())}
    return any(keyword_key(item) in excluded for item in typed.get("priority_keywords", ()))


def _common_problems(found, spec_map, typed):
    for name in ("excluded_keywords", "priority_keywords"):
        if name in typed:
            problem = _words_problem(spec_map[name], typed[name])
            if problem:
                found[name] = problem
    if "priority_keywords" not in found and _overlap(typed):
        found["priority_keywords"] = "overlap"
    if "reason" in typed:
        problem = _line_problem(spec_map["reason"], typed["reason"])
        if problem:
            found["reason"] = problem


def edit_problems(seed, typed):
    """고치는 폼 값(typed)의 문제들 `{칸 이름: 문제 이름}` — 없으면 빈 사전. 서비스의 `Seed` 생성자가 통과시키는 값이면 문제가 없다."""
    found = {}
    _common_problems(found, EDIT_SPEC, typed)
    if seed.brand_case and "reason" in typed and not typed["reason"] and "reason" not in found:
        found["reason"] = "brand_reason"
    if "allowed_channels" in typed and not typed["allowed_channels"]:
        found["allowed_channels"] = "channels_none"
    return found


def create_problems(typed, existing=()):
    """새로 등록하는 폼 값(typed)의 문제들 — `existing` 은 지금 있는 씨앗들(같은 소속의 같은 낱말을 찾는다)."""
    found = {}
    keyword = _keyword_problem(CREATE_SPEC["keyword"], typed.get("keyword", ""), typed.get("scope"), existing)
    if keyword:
        found["keyword"] = keyword
    for name in ("major", "minor"):
        problem = _line_problem(CREATE_SPEC[name], typed.get(name, ""))
        if problem:
            found[name] = problem
    if typed.get("seed_type") not in IMPORTANCE_CREATE:
        found["seed_type"] = "required"
    if typed.get("target_type") is None:
        found["target_type"] = "required"
    elif typed["target_type"] not in TARGET_ORDER:
        found["target_type"] = "bad_choice"
    if typed.get("scope") is None:
        found["scope"] = "required"
    elif typed["scope"] not in SCOPE_ORDER:
        found["scope"] = "bad_choice"
    if typed.get("scope") == sd.SCOPE_COMMON and not typed.get("allowed_channels"):
        found["allowed_channels"] = "channels_none"
    if typed.get("seed_type") == "sponsorable":
        if typed.get("sponsor_tag") is None:
            found["sponsor_tag"] = "tag_needed"
        elif typed["sponsor_tag"] not in TAG_ORDER:
            found["sponsor_tag"] = "bad_choice"
    _common_problems(found, CREATE_SPEC, typed)
    return found


def service_values(fields, typed):
    """서비스 `create_seed` 에 보낼 값 — 지금 보이는 칸만, 채널 칸은 공통일 때만(채널 전용은 서비스가 그 채널 하나로 정한다), 협찬 분야는 협찬 가능일 때만."""
    names = {spec.name for spec in fields}
    return {name: value for name, value in typed.items() if name in names}


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
    key = {"required": "bf_err_required", "duplicate": "bf_err_duplicate", "markup": "bf_err_markup", "bad_choice": "bf_err_choice", "key_shape": "bf_err_key_shape", "invalid": "bf_err_invalid",
           "overlap": "sf_err_overlap", "no_letters": "sf_err_no_letters", "claim": "sf_err_claim", "same_word": "sf_err_same_word", "channels_none": "sf_err_channels_none",
           "tag_needed": "sf_err_tag_needed", "brand_reason": "sf_err_brand_reason"}.get(problem, "bf_err_invalid")
    return T[key]


# ---- 이름(서비스의 쉬운 이름 표를 그대로) -------------------------------------------------------------------------------------------------------
def state_name(state):
    return sd.STATE_KO[state]


def scope_name(scope):
    return wording.SCOPE_KO[scope]


def importance_name(kind):
    return wording.SEED_TYPE_KO[kind]


def target_name(target):
    return wording.TARGET_TYPE_KO[target] if target in wording.TARGET_TYPE_KO else T["seeds_target_none"]


def channel_name(code):
    return wording.CHANNEL_KO[code]


def tag_name(tag):
    return wording.TAG_KO.get(tag, tag)
