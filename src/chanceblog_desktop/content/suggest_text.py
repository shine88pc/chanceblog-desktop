"""제안(`suggest`)에 쓰는 한국어 글 다루기 — 받침으로 조사 고르기·낱말(어근) 나누기·같은 낱말 접기·낱말 집합 닮은 정도. 표준 라이브러리만 쓰고 파일·네트워크·현재 시각을 쓰지 않는다.

규칙: ① 조사(을/를·이/가·은/는·으로/로·과/와)는 앞 글의 **받침**으로 고른다 — 한글은 마지막 글자의 받침, 숫자·영문은 읽는 소리의 끝(1 일·2 이·3 삼, L·M·N·R 만 받침). 으로/로 는 ㄹ 받침도 '로'.
② 글은 **글자가 아니라 낱말(공백·기호로 나눈 덩어리, 끝의 조사를 뗀 어근)** 단위로 비교하고 자른다 — 글자 단위로 자르면 키워드가 깨진다.
③ 같은 낱말이 바로 이어 나오면('비교 비교') 하나로 접는다(조사가 붙은 쪽을 남긴다).
"""
from __future__ import annotations

import re
import unicodedata

HANGUL_FIRST, HANGUL_LAST = 0xAC00, 0xD7A3
FINALS = 28                                      # 한글 음절의 받침(종성) 가짓수 — 받침 없음 포함
RIEUL = 8                                        # 종성 ㄹ 의 번호
MIN_STEM = 2                                     # 조사를 떼고 남는 어근의 최소 글자 수(한 글자만 남으면 떼지 않는다 — '아이' 를 '아' 로 만들지 않는다)
NONE, PLAIN, RIEUL_SOUND = "none", "batchim", "rieul"    # 마지막 소리: 받침 없음 · ㄹ 아닌 받침 · ㄹ 받침
PARTICLES = {"을": ("을", "를"), "이": ("이", "가"), "은": ("은", "는"), "으로": ("으로", "로"), "과": ("과", "와")}
_DIGIT_SOUND = {"0": PLAIN, "1": RIEUL_SOUND, "2": NONE, "3": PLAIN, "4": NONE, "5": NONE, "6": PLAIN, "7": RIEUL_SOUND, "8": RIEUL_SOUND, "9": NONE}      # 영·일·이·삼·사·오·육·칠·팔·구
_LETTER_SOUND = {"l": RIEUL_SOUND, "m": PLAIN, "n": PLAIN, "r": RIEUL_SOUND}                                                                  # 엘·엠·엔·알 — 나머지 알파벳 이름은 모음으로 끝난다
# 어근 뒤에 붙는 조사·어미(긴 것부터). 어근이 MIN_STEM 글자 아래가 되면 떼지 않는다.
_ENDINGS = tuple(sorted(("으로서", "으로써", "에서는", "에서도", "까지", "부터", "에게", "으로", "에서", "처럼", "보다", "마다", "이나", "이랑", "하고", "에는", "에도", "이란", "이라", "이며",
                         "께서", "한테", "조차", "밖에", "라도", "을", "를", "은", "는", "이", "가", "과", "와", "도", "로", "만", "에", "의", "나", "랑"), key=lambda item: (-len(item), item)))
_WORD = re.compile(r"[^\W_]+")


def _is_hangul(char):
    return HANGUL_FIRST <= ord(char) <= HANGUL_LAST


def final_sound(text):
    """글의 마지막 소리 — `NONE`(모음으로 끝)·`PLAIN`(ㄹ 아닌 받침)·`RIEUL_SOUND`(ㄹ 받침). 마지막 글자·숫자를 보고 기호·공백은 건너뛴다. 알 수 없는 글자(한자 등)는 받침 없음으로 본다."""
    for char in reversed(unicodedata.normalize("NFKC", str(text))):
        if _is_hangul(char):
            final = (ord(char) - HANGUL_FIRST) % FINALS
            return NONE if final == 0 else RIEUL_SOUND if final == RIEUL else PLAIN
        if char in _DIGIT_SOUND:
            return _DIGIT_SOUND[char]
        if char.isalnum():
            return _LETTER_SOUND.get(char.casefold(), NONE)
    return NONE


STUCK_KINDS = ("을", "은")           # 씨앗에 이미 붙어 있는 걸 알아보는 조사 — 이/가·으로/로·과/와 는 낱말의 끝이기도 해서(고양이·전문가·도로·사과) 건드리지 않는다


def _already_attached(text, kind):
    """`text` 가 이미 `kind` 의 맞는 조사로 끝나는가('김장을' — 앞 두 글자 이상에 받침 여부까지 맞아야 한다. '새마을' 의 '을' 은 앞 글자에 받침이 없어 조사가 아니다)."""
    if kind not in STUCK_KINDS:
        return False
    with_final, without = PARTICLES[kind]
    for form, needs_final in ((with_final, True), (without, False)):
        body = text[:-len(form)]
        if text.endswith(form) and len(body.strip()) >= 2 and (final_sound(body) != NONE) == needs_final:
            return True
    return False


def attach(text, kind):
    """`text` 뒤에 조사를 붙인다 — `kind` 는 `PARTICLES` 의 열쇠(을·이·은·으로·과). 받침 있으면 앞의 것, 없으면 뒤의 것(으로/로 는 ㄹ 받침도 '로').
    '을'·'은' 은 씨앗이 이미 맞는 조사를 달고 있으면('김장을') 다시 붙이지 않는다('김장을을' 방지)."""
    if kind not in PARTICLES:
        raise ValueError(f"모르는 조사 종류: {kind}")
    if _already_attached(text, kind):
        return text
    with_final, without = PARTICLES[kind]
    sound = final_sound(text)
    if kind == "으로":
        return text + (without if sound in (NONE, RIEUL_SOUND) else with_final)
    return text + (without if sound == NONE else with_final)


def stem(word):
    """낱말 하나의 어근 — 끝의 조사·어미를 하나 뗀다(남는 글자가 `MIN_STEM` 아래면 떼지 않는다). 한글로 끝나지 않는 낱말은 그대로. 소문자로 한다."""
    word = unicodedata.normalize("NFKC", str(word)).casefold()
    if not word or not _is_hangul(word[-1]):
        return word
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= MIN_STEM:
            return word[:-len(ending)]
    return word


def words(text):
    """글 → 낱말(글자·숫자 덩어리) 목록. 호환 문자를 풀고(NFKC) 소문자로 하며 공백·기호에서 나눈다."""
    return _WORD.findall(unicodedata.normalize("NFKC", str(text)).casefold())


def stems(text):
    """글 → 어근 목록(순서 유지, 겹침 포함)."""
    return [stem(word) for word in words(text)]


def stem_set(text):
    return frozenset(stems(text))


def jaccard(left, right):
    """두 집합이 얼마나 겹치는지(0~1) — 하나라도 비었으면 0."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def contains_all(whole, part):
    """`part` 의 낱말이 모두 `whole` 에 있다(둘 다 비어 있지 않아야 한다)."""
    return bool(part) and bool(whole) and part <= whole


def fold_repeats(text):
    """같은 낱말이 바로 이어 나오면('비교 비교'·'점검 점검을') 하나로 접는다 — 조사가 붙어 더 긴 쪽을 남긴다(같은 길이면 앞의 것). 공백은 하나로 정리한다."""
    kept = []
    for token in str(text).split():
        key = stem("".join(words(token)))
        if kept and key and key == kept[-1][0]:
            if len(token) > len(kept[-1][1]):
                kept[-1] = (key, token)
            continue
        kept.append((key, token))
    return " ".join(token for _key, token in kept)


def squash(text):
    """제외어·금지 표현을 견주는 모양 — 호환 문자를 풀고(NFKC) 모든 공백을 없애고 소문자로(`check/profile_options` 의 점검과 같다 — 전각·띄어 쓴/붙여 쓴 변형도 같은 낱말)."""
    return "".join(unicodedata.normalize("NFKC", str(text)).split()).casefold()


_SLOT = re.compile(r"\{(주제|계절)(?::([^{}]*))?\}")


def render(template, slots):
    """`{주제}`·`{계절}` 자리에 낱말을 넣고 `{주제:을}` 처럼 조사를 받침에 맞게 붙인다 → 같은 낱말이 이어 나오면 접은 글. 틀의 자리가 모르는 이름이거나 값이 없으면 ValueError(자료 오류 — 시험이 모든 틀을 확인한다)."""
    def fill(found):
        name, kind = found.group(1), found.group(2)
        value = slots.get(name)
        if not value:
            raise ValueError(f"틀의 자리 {{{name}}} 에 넣을 값이 없다")
        return value if kind is None else attach(value, kind)

    return fold_repeats(_SLOT.sub(fill, template))


__all__ = ["PARTICLES", "attach", "contains_all", "final_sound", "fold_repeats", "jaccard", "render", "squash", "stem", "stem_set", "stems", "words"]
