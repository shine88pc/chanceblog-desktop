"""채널(블로그 슬롯)이 다른 화면에 보이는 이름 — Seed 관리의 소속 선택·주제 후보·초안 작성·홈이 `네이버 A`·`Blogger 한글` 같은 고정 이름 대신 쓰는 **순수 규칙**(blogsel-2, D-510).

규칙(블로그 관리 화면의 카드 윗줄과 같은 말이다):
  · 카드로 보이는 슬롯(등록했거나 내용이 있거나 새로 연결 중 — `blog_form.is_listed`)은 **사용자가 정한 별명**, 별명이 없으면 종류 + 번호 제안(`네이버 블로그 1`).
  · 카드가 아닌 슬롯(아직 연결하지 않은 자리)은 **종류 이름**(`네이버 블로그 1` 처럼 번호가 있는 종류는 번호까지 — 같은 종류 두 자리를 가르려면 필요하다. 한 자리뿐인 `GitHub Pages` 는 종류 이름 그대로).
  · 별명은 키·토큰 모양을 가리고 길면 자른다(`blog_form.shown` — 서비스의 별명 한도 30자). 같은 글이 둘 이상이면 각각 `(종류 + 번호)` 를 덧붙여 가른다.
화면에 보이는 글만 바꾼다 — 엔진·저장 파일·채널 열쇠(`naver_a` 등)는 그대로다. 이 모듈은 PySide6 도 파일도 시계도 모른다.

화면 틀이 쓰는 방법: `AppState` 가 블로그 관리가 읽은 자료로 `labels(...)` 를 만들어 `use(...)` 로 켜 두면, 다른 화면의 뷰모델이 `label(열쇠)` 를 부른다(켜 둔 것이 없으면 별명 없는 기본 이름 — 옛 고정 이름이 아니다).
"""
from __future__ import annotations

from . import blog_form as bf
from .text import T

LIMIT = 30                                                   # 화면 이름 길이 상한 — 서비스의 별명 한도(`ch.MAX_ALIAS`)와 같다
DRAWER_LIMIT = 12                                            # 서랍처럼 좁은 자리(폭 420)에 보이는 이름의 길이 상한 — 한글 열두 자면 배지·단추·칩이 서랍 안에 든다(검증 Q2-1: 별명이 길면 서랍이 넘쳤다). 전체 이름은 툴팁·접근 이름에 둔다
ORDER = bf.DISPLAY_ORDER                                     # 종류별 채움 순서: naver_a·naver_b·blogger_ko·blogger_en·github_pages
HOME_KEYS = {"A": "naver_a", "B": "naver_b"}                 # 홈의 채널 열쇠(A·B)가 가리키는 슬롯


def _kind_name(key):
    """카드가 아닌 슬롯의 이름 — 번호가 있는 종류(자리가 둘)는 `네이버 블로그 1`, 한 자리뿐이면 종류 이름 그대로."""
    return bf.suggest_alias(key) if len(bf.KIND_SLOTS[bf.KIND_KEY[key]]) > 1 else T["blogs_kind_" + bf.KIND_KEY[key]]


def entries(data, adding=()):
    """블로그 관리가 읽은 자료(`BlogsData`) → `{열쇠: (별명, 카드인가)}` — 자료가 없으면 None(아직 못 읽었다)."""
    if data is None:
        return None
    return {slot.key: (slot.alias, bf.is_listed(slot.key, slot.raw(), slot.key in adding)) for slot in data.slots}


def labels(items=None, limit=LIMIT):
    """다섯 채널의 화면 이름 `{열쇠: 글}` — `items` 는 `entries(...)` 의 값(`{열쇠: (별명, 카드인가)}`)이고 None 이면 별명 없는 기본 이름이다."""
    items = items or {}
    out = {}
    for key in ORDER:
        alias, listed = items.get(key, ("", False))
        out[key] = bf.shown(bf.card_title(key, alias) if listed else _kind_name(key), limit)
    seen = {}
    for key in ORDER:
        seen.setdefault(out[key].casefold(), []).append(key)
    for group in seen.values():
        if len(group) > 1:                                    # 같은 이름이 둘 이상이면 (종류 + 번호) 를 덧붙여 가른다 — 이미 그 슬롯의 제안 이름이면 그대로 둔다
            for key in group:
                if out[key] != bf.suggest_alias(key):
                    out[key] = bf.shown(f"{out[key]} ({bf.suggest_alias(key)})", limit + 20)
    again = {}
    for key in ORDER:
        again.setdefault(out[key].casefold(), []).append(key)
    for group in again.values():
        for number, key in enumerate(group[1:], start=2):     # 그래도 겹치면(제안 이름과 같은 별명을 일부러 지은 경우) 번호를 붙인다
            out[key] = f"{out[key]} #{number}"
    return out


def short_names(full, limit=DRAWER_LIMIT):
    """좁은 자리(서랍)에 보일 이름 `{열쇠: 글}` — 화면 이름(`full`)을 `limit` 자로 줄이고(넘으면 …), 줄인 뒤 같아진 이름은 ` #번호` 로 가른다(서랍의 초안 단추 둘이 같은 글이 되지 않게). 순수 규칙이다."""
    out = {key: bf.shown(full[key], limit) for key in ORDER}
    groups = {}
    for key in ORDER:
        groups.setdefault(out[key].casefold(), []).append(key)
    for group in groups.values():
        for number, key in enumerate(group[1:], start=2):
            out[key] = f"{bf.shown(full[key], limit - 3)} #{number}"
    return out


DEFAULT = labels(None)                                       # 아직 블로그 관리를 읽지 못했을 때(또는 자료가 없을 때)의 이름
_current = None                                              # 지금 켜 둔 이름들(없으면 DEFAULT)


def use(mapping):
    """화면이 쓸 이름들을 켠다(None 이면 기본으로 되돌린다) → 바뀌었는가."""
    global _current
    new = dict(mapping) if mapping else None
    changed = (new or DEFAULT) != (_current or DEFAULT)
    _current = new
    return changed


def current():
    return dict(_current or DEFAULT)


def label(key):
    """채널 열쇠(`naver_a` 등) 하나의 화면 이름. 모르는 열쇠는 그대로 돌려준다(코드가 아는 다섯 밖은 쓰지 않는다)."""
    return (_current or DEFAULT).get(key, key)


def home_label(letter):
    """홈의 채널 열쇠(`A`·`B`)의 화면 이름 — 모르는 글자는 빈 글."""
    key = HOME_KEYS.get(letter)
    return label(key) if key else ""


def button_text(text):
    """단추·칩에 넣는 글 — Qt 는 단추 글의 `&` 를 Alt 단축키 표시로 읽어 별명의 `&` 가 사라지고 단축키가 생긴다(`A&B` → `AB`·Alt+B, `&lt;` → `lt;`). `&&` 로 써야 글자 그대로 보인다(검증 S2-3).
    접근 이름·툴팁은 이 글을 쓰지 않고 별명 그대로다. 표시 규칙은 이 한 곳이고 단추·칩을 만드는 `components` 가 부른다."""
    return str(text).replace("&", "&&")


def short_label(key, limit=DRAWER_LIMIT):
    """채널 열쇠(`naver_a` 등) 하나의 좁은 자리용 이름 — 모르는 열쇠는 그대로."""
    return short_names(current(), limit).get(key, key)


def short_home_label(letter, limit=DRAWER_LIMIT):
    """홈의 채널 열쇠(`A`·`B`)의 좁은 자리용 이름 — 모르는 글자는 빈 글."""
    key = HOME_KEYS.get(letter)
    return short_label(key, limit) if key else ""


def full_if_cut(key, short):
    """좁은 자리용 이름(`short`)이 줄인 글이면 전체 이름(툴팁·접근 이름용), 아니면 빈 글 — 줄이지 않았으면 뷰모델에 따로 싣지 않는다."""
    full = label(key)
    return full if short != full else ""


def avatar_letter(key):
    """채널 아바타 안의 글자 하나 — 별명이 있으면 별명의 첫 글자, 아직 별명이 없어 기본 이름(`네이버 블로그 1`)이면 그 번호(같은 종류 두 자리가 아바타에서도 가려진다)."""
    text = str(label(key))
    if text == bf.suggest_alias(key) and text[-1:].isdigit():
        return text[-1]
    for char in text:
        if not char.isspace():
            return char.upper()
    return "?"


__all__ = ["DEFAULT", "DRAWER_LIMIT", "button_text", "HOME_KEYS", "LIMIT", "ORDER", "avatar_letter", "current", "entries", "full_if_cut", "home_label", "label", "labels", "short_home_label", "short_label", "short_names", "use"]
