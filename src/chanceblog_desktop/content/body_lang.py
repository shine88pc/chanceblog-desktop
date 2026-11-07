"""규칙 기반 본문 생성의 한국어 도우미(순수 계산 — 파일·네트워크·시계·난수 없음, 같은 입력은 늘 같은 결과).

· **받침에 맞는 조사**(`particle`·`fill`): 낱말의 마지막 글자를 읽어 은/는·이/가·을/를·과/와·으로/로 를 고른다. 한글은 받침, 숫자는 읽는 소리(영·일·삼·육·칠·팔은 받침 있음), 영문 약어는 글자 이름
  (엘·엠·엔·알 만 받침), 영문 낱말은 알려 둔 낱말과 끝글자 규칙으로 읽는다. **확실하게 읽을 수 없으면 틀린 조사를 붙이지 않고 `은(는)`·`(으)로` 꼴로 둔다** — 읽는 사람이 한 글자만 고치면 된다.
· **목록 잇기**(`listing`): 한 개는 그대로, 두 개는 `A와 B`(받침에 맞춰), 세 개 이상은 `A, B, C`.
· **해요체 → 합니다체**(`to_hapsyo`): 틀은 해요체로 쓰고 말투가 격식이면 문장 끝의 서술어만 정해 둔 표(`ENDINGS`)대로 바꾼다. 표에 없는 서술어로 끝나는 틀은 시험이 찾아낸다(그래서 틀의 서술어는 닫힌 목록이다).
· **말투 읽기**(`style_of_tone`): 프로필의 말투 글에서 '합니다·격식·정중' 같은 낱말이 있으면 합니다체, 아니면(없어도) 해요체. `clashes_with_style` 은 한 줄 글(소제목)의 끝이 글 전체의 말투와 어긋나는지 본다.
· **글 정리**(`plain_text`): 후보의 글에서 마크다운 표시와 HTML 엔티티를 걷어 낸다(풀지 않고 지운다).
네트워크·파일은 쓰지 않는다. 소스에 백슬래시 이스케이프를 쓰지 않는다(편집 도구 함정) — 글자 부류는 `[...]` 로 적는다.
"""
from __future__ import annotations

import re
import unicodedata

STYLE_HAEYO, STYLE_HAPSYO = "haeyo", "hapsyo"
STYLES = (STYLE_HAEYO, STYLE_HAPSYO)

_HANGUL_FIRST, _HANGUL_LAST = 0xAC00, 0xD7A3
_DIGIT_FINAL = {"0": 21, "1": 8, "2": 0, "3": 16, "4": 0, "5": 0, "6": 1, "7": 8, "8": 8, "9": 0}       # 영(ㅇ)·일(ㄹ)·이·삼(ㅁ)·사·오·육(ㄱ)·칠(ㄹ)·팔(ㄹ)·구 — 종성 번호
_LETTER_FINAL = {"l": 8, "m": 16, "n": 4, "r": 8}                                                         # 영문 글자 이름: 엘(ㄹ)·엠(ㅁ)·엔(ㄴ)·알(ㄹ) 만 받침이 있다
RIEUL = 8
_TRAILING = " )]}」』’”" + chr(34) + "'.,·…!?:;~"
_LATIN_RUN = re.compile("[A-Za-z]+$")
# 영문 낱말 가운데 끝글자 규칙이 틀리거나 모르는 것 — 한국어로 읽은 소리의 받침(종성 번호). 모르는 낱말은 아래 규칙으로 읽는다.
_LEXICON = {
    "git": 19, "github": 0, "gitlab": 17, "chatgpt": 0, "copilot": 19, "macbook": 1, "outlook": 1, "facebook": 1, "youtube": 0, "linkedin": 4, "notebook": 1, "wifi": 0, "bluetooth": 0, "hub": 0, "web": 17,
    "ipad": 0, "pad": 0, "excel": 8, "word": 0, "cloud": 0, "android": 0, "skype": 0, "type": 17, "set": 0, "check": 0, "link": 0, "network": 0, "disk": 0, "tablet": 19, "laptop": 17, "desktop": 17,
}


def _letters_final(letters):
    """영문 글자만 있는 낱말의 읽은 소리 받침(종성 번호) — 모르면 None."""
    word = letters.lower()
    if word in _LEXICON:
        return _LEXICON[word]
    if len(word) <= 5 and (letters.isupper() or not any(ch in "aeiouy" for ch in word)):
        return _LETTER_FINAL.get(word[-1], 0)                                  # 약어는 글자 이름으로 읽는다(GPU·SSD·API·VPN·LLM)
    if word.endswith("ng"):
        return 21
    if word.endswith("ck"):
        return 1
    last = word[-1]
    if last in "aiouy":
        return 0
    if last == "e":
        return {"l": 8, "n": 4, "m": 16}.get(word[-2:-1], 0)                   # google·apple(ㄹ)·phone·line(ㄴ)·chrome·game(ㅁ) — 그 밖의 -e 는 받침 없음
    if last == "n":
        return 4
    if last == "m":
        return 16
    if last == "l":
        return 8
    if last == "p":
        return 17
    if last in "rdsxzhfvgwj":
        return 0
    if last == "c" and word.endswith("ic"):
        return 1
    return None


def final_of(text):
    """낱말(구)의 마지막 글자를 읽은 받침 — 종성 번호(0 이면 받침 없음, ㄹ 은 8), 확실하게 읽을 수 없으면 None."""
    plain = unicodedata.normalize("NFKC", str(text)).rstrip(_TRAILING)
    if not plain:
        return None
    last = plain[-1]
    if _HANGUL_FIRST <= ord(last) <= _HANGUL_LAST:
        return (ord(last) - _HANGUL_FIRST) % 28
    if last in _DIGIT_FINAL:
        return _DIGIT_FINAL[last]
    found = _LATIN_RUN.search(plain)
    if found:
        return _letters_final(found.group(0))
    return None


# 조사 한 쌍(받침 있을 때, 없을 때) — 모를 때의 모양
_UNSURE = {("으로", "로"): "(으)로", ("이라", "라"): "(이)라", ("이나", "나"): "(이)나", ("이랑", "랑"): "(이)랑", ("이에요", "예요"): "(이)에요", ("이라는", "라는"): "(이)라는", ("이라도", "라도"): "(이)라도", ("이라면", "라면"): "(이)라면"}


def particle(text, with_final, without_final):
    """`text` 뒤에 붙일 조사. 받침이 있으면 `with_final`, 없으면 `without_final`('으로/로' 는 ㄹ 받침도 '로'). 확실하게 읽을 수 없으면 `은(는)`·`(으)로` 꼴."""
    final = final_of(text)
    if final is None:
        return _UNSURE.get((with_final, without_final), f"{with_final}({without_final})")
    if final == 0 or (with_final == "으로" and final == RIEUL):
        return without_final
    return with_final


_SLOT = re.compile("[{]([A-Za-z0-9_]+)(?::([^{}/:]+)/([^{}/:]+))?[}]")


def slots_of(template):
    """틀 속 `{이름}` 자리들의 이름(나온 순서, 중복 포함)."""
    return [found.group(1) for found in _SLOT.finditer(template)]


def fill(template, values):
    """`{이름}` 자리에 값을 넣고 `{이름:을/를}` 자리에는 값을 넣은 뒤 받침에 맞는 조사를 붙인다. 값이 없는 이름은 KeyError(틀을 쓰는 쪽이 먼저 `slots_of` 로 확인한다)."""
    def put(found):
        value = str(values[found.group(1)])
        if found.group(2) is None:
            return value
        return value + particle(value, found.group(2), found.group(3))

    return _SLOT.sub(put, template)


def skeleton(template):
    """틀에서 `{…}` 자리를 뺀 고정 글 — 제외할 낱말·금지 표현이 틀 자체에 걸리는지 볼 때 쓴다(후보의 낱말은 막을 수 없다)."""
    return _SLOT.sub("", template)


def collapse(text):
    """바로 이어진 같은 낱말을 하나로('노트북 비교' + ' 비교라면' → '노트북 비교라면', '점검 점검법' → '점검법'). 앞 낱말 끝에 부호가 있으면 합치지 않는다."""
    words = []
    for word in text.split(" "):
        plain = word.rstrip(",.:;?!")
        previous = words[-1] if words else ""                                      # 앞 낱말에 쉼표 같은 부호가 붙어 있으면 목록의 칸 구분이라 합치지 않는다('설치 공간이, 공간이 좁은 …')
        if words and word and (plain == previous or (len(previous) >= 2 and plain.startswith(previous))):
            words[-1] = word                                                      # 뒤의 것(쉼표가 붙었거나 더 긴 낱말)을 남긴다
        else:
            words.append(word)
    return " ".join(words)


def listing(items):
    """낱말들을 문장 속에 잇는다 — 하나는 그대로, 둘은 `A와 B`(받침에 맞춰), 셋 이상은 `A, B, C`."""
    items = [str(item) for item in items if str(item)]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return items[0] + particle(items[0], "과", "와") + " " + items[1]
    return ", ".join(items)


# ---- 말투 ---------------------------------------------------------------------------------------------------------------------------
_HAPSYO_WORDS = ("합니다", "합쇼", "하십시오", "격식", "정중", "공식적", "전문적", "논리적", "신뢰", "차분", "존댓말 설명체", "설명체", "~습니다")
_HAEYO_WORDS = ("해요", "친근", "부드러", "다정", "편안", "캐주얼", "대화", "이웃", "구어", "가볍")


def style_of_tone(*texts):
    """프로필의 말투 글들 → `STYLE_HAEYO`·`STYLE_HAPSYO`. 앞의 글부터 보고 처음으로 낱말이 읽히는 글을 따른다(해요 낱말이 합니다 낱말보다 먼저 본다 — '친근하지만 정중한' 은 해요체). 아무것도 못 읽으면 해요체."""
    for text in texts:
        plain = " ".join(str(text or "").split())
        if not plain:
            continue
        if any(word in plain for word in _HAEYO_WORDS):
            return STYLE_HAEYO
        if any(word in plain for word in _HAPSYO_WORDS):
            return STYLE_HAPSYO
    return STYLE_HAEYO


# ---- 해요체 → 합니다체 ---------------------------------------------------------------------------------------------------------------
# (해요체 서술어, 합니다체 서술어) — 문장 끝의 이 서술어만 바꾼다. 긴 것이 먼저 맞도록 정렬해서 쓴다. '~세요'·'~까요?' 로 끝나는 문장은 두 말투에서 같다(바꾸지 않는다).
ENDINGS = (
    ("해요", "합니다"), ("돼요", "됩니다"), ("있어요", "있습니다"), ("없어요", "없습니다"), ("좋아요", "좋습니다"), ("이에요", "입니다"), ("예요", "입니다"), ("아니에요", "아닙니다"), ("져요", "집니다"),
    ("쉬워요", "쉽습니다"), ("어려워요", "어렵습니다"), ("많아요", "많습니다"), ("적어요", "적습니다"), ("같아요", "같습니다"), ("달라요", "다릅니다"), ("남아요", "남습니다"), ("커요", "큽니다"),
    ("걸려요", "걸립니다"), ("나와요", "나옵니다"), ("봐요", "봅니다"), ("알아요", "압니다"), ("몰라요", "모릅니다"), ("찾아요", "찾습니다"), ("읽어요", "읽습니다"), ("생겨요", "생깁니다"),
    ("쌓여요", "쌓입니다"), ("바뀌어요", "바뀝니다"), ("맞아요", "맞습니다"), ("맞춰요", "맞춥니다"), ("줘요", "줍니다"), ("가요", "갑니다"), ("와요", "옵니다"), ("얻어요", "얻습니다"),
    ("놓쳐요", "놓칩니다"), ("흔들려요", "흔들립니다"), ("느껴져요", "느껴집니다"), ("늘어요", "늘어납니다"), ("줄어요", "줄어듭니다"), ("높아요", "높습니다"), ("낮아요", "낮습니다"),
    ("편해요", "편합니다"), ("기울어요", "기웁니다"), ("모여요", "모입니다"), ("더해요", "더합니다"), ("빠져요", "빠집니다"), ("이어져요", "이어집니다"),
    ("써요", "씁니다"), ("빨라요", "빠릅니다"), ("읽혀요", "읽힙니다"), ("섞여요", "섞입니다"), ("잡혀요", "잡힙니다"), ("헷갈려요", "헷갈립니다"), ("떠올라요", "떠오릅니다"), ("살펴요", "살핍니다"),
    ("따라요", "따릅니다"), ("흐려요", "흐립니다"), ("보여요", "보입니다"), ("옮겨요", "옮깁니다"), ("끝나요", "끝납니다"), ("놓여요", "놓입니다"), ("어울려요", "어울립니다"), ("걸러져요", "걸러집니다"),
    ("끝내요", "끝냅니다"), ("지워요", "지웁니다"), ("줄여요", "줄입니다"), ("들여요", "들입니다"), ("남겨요", "남깁니다"), ("살려요", "살립니다"), ("물어요", "묻습니다"), ("나눠요", "나눕니다"),
    ("정해져요", "정해집니다"), ("해 줘요", "해 줍니다"), ("만들어요", "만듭니다"), ("고려해요", "고려합니다"), ("모아요", "모읍니다"), ("보태요", "보탭니다"), ("챙겨요", "챙깁니다"), ("밀려요", "밀립니다"),
)
_ENDING_BY_LENGTH = tuple(sorted(ENDINGS, key=lambda pair: -len(pair[0])))
_END_PUNCT = ".?!"


def split_ending(sentence):
    """문장 → (끝 부호를 뗀 글, 끝 부호). 끝 부호가 없으면 ''."""
    text = sentence.rstrip()
    stop = len(text)
    while stop and text[stop - 1] in _END_PUNCT:
        stop -= 1
    return text[:stop], text[stop:]


def ending_of(sentence):
    """문장 끝의 서술어가 `ENDINGS` 의 해요체 서술어이면 그 서술어, 아니면 None."""
    body, _punct = split_ending(sentence)
    return next((haeyo for haeyo, _hapsyo in _ENDING_BY_LENGTH if body.endswith(haeyo)), None)


def _tail_of(char):
    """한글 글자의 받침 번호(없거나 한글이 아니면 -1)."""
    return (ord(char) - _HANGUL_FIRST) % 28 if _HANGUL_FIRST <= ord(char) <= _HANGUL_LAST else -1


def to_hapsyo(sentence):
    """해요체로 쓴 문장의 끝 서술어를 합니다체로. ① 표(`ENDINGS`)에 있는 서술어 ② 받침 있는 글자(ㄹ 제외) 뒤의 `-아요·-어요`(않아요·삼아요·짚어요 → -습니다) — 규칙 활용만 바꾼다.
    그 밖의 끝(`~세요`·`~까요?` 같은 두 말투 공통 끝 포함)은 그대로 둔다 — 시험이 `~요` 로 남는 틀을 찾아낸다."""
    body, punct = split_ending(sentence)
    for haeyo, hapsyo in _ENDING_BY_LENGTH:
        if body.endswith(haeyo):
            return body[:len(body) - len(haeyo)] + hapsyo + punct
    if body.endswith(("아요", "어요")) and len(body) >= 3 and _tail_of(body[-3]) not in (-1, 0, RIEUL):
        return body[:-2] + "습니다" + punct
    return sentence


def in_style(sentence, style):
    """문장을 그 말투로 — 합니다체만 바꾼다."""
    return to_hapsyo(sentence) if style == STYLE_HAPSYO else sentence


def tidy(text):
    """공백을 하나로 접고 쉼표·마침표 앞 공백을 없앤다."""
    plain = " ".join(str(text).split())
    for mark in (",", ".", "?", "!"):
        plain = plain.replace(" " + mark, mark)
    return plain


def clashes_with_style(line, style):
    """소제목처럼 한 줄 글의 말투가 글 전체의 말투와 어긋나는가 — 합니다체 끝(`~니다`)이 해요체 글에 섞이거나, 해요체 서술어(`ENDINGS` 의 앞쪽 — `~해요`·`~예요` …)로 끝나는 줄이 합니다체 글에 섞이는 것.
    `~세요`·`~까요?` 와 명사로 끝나는 줄은 두 말투에 다 맞는다(독립 검증 낮음 — 소제목은 합니다체인데 본문은 해요체인 글)."""
    if style == STYLE_HAPSYO:
        return ending_of(line) is not None
    return split_ending(line)[0].endswith("니다")


# ---- 후보의 글을 본문에 되풀이하기 전의 정리 ------------------------------------------------------------------------------------------------
_ENTITY = re.compile("&(?:[A-Za-z][A-Za-z0-9]{1,15}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});")
_AMPERSAND = re.compile("&amp;", re.IGNORECASE)
_BRACKETS = (chr(91), chr(93))                                                                       # 대괄호 — 정규식 속의 `[`·`]` 를 소스에 백슬래시 없이 적으려고 글자 코드로
_MARKDOWN_LINK = re.compile(re.escape(_BRACKETS[0]) + "([^" + re.escape(_BRACKETS[1]) + "]*)" + re.escape(_BRACKETS[1] + "(") + "[^)]*" + re.escape(")"))
_MARKDOWN_MARKS = ("**", "__", "~~", "`")
_MARKDOWN_LEAD = re.compile("^(?:#+|>|[-*+])[ ]+")


def plain_text(text):
    """키워드·주제처럼 제목·소제목·문단에 그대로 되풀이되는 글에서 마크다운 표시(`**`·`__`·`~~`·백틱·`[글](주소)` 꼴의 주소·줄머리 `#`·`>`·`-`)와 HTML 엔티티(`&lt;` 꼴)를 걷어 낸다.
    엔티티는 풀지 않고(`&lt;` → `<`) 지운다 — 풀면 입력 단계가 거절한 HTML 모양이 되살아난다(`&amp;` 만 `&` 로 되돌린다: 'A &amp; B' 는 'A & B', 겹쳐 쓴 `&amp;lt;` 는 지워진다). 걷어 낼 것이 없으면 같은 글(앞뒤 공백만 정리)이다."""
    plain = str(text)
    for _round in range(5):                                                                            # '&amp;lt;' 처럼 겹쳐 쓴 것은 '&amp;' 를 '&' 로 되돌리는 것만 풀고(& 자체는 무해하다) 남은 엔티티를 지운다
        if not _AMPERSAND.search(plain):
            break
        plain = _AMPERSAND.sub("&", plain)
    plain = _ENTITY.sub(" ", plain)
    plain = _MARKDOWN_LINK.sub(lambda found: found.group(1), plain)
    for mark in _MARKDOWN_MARKS:
        plain = plain.replace(mark, "")
    return _MARKDOWN_LEAD.sub("", " ".join(plain.split()))


__all__ = ["ENDINGS", "STYLES", "STYLE_HAEYO", "STYLE_HAPSYO", "clashes_with_style", "collapse", "ending_of", "fill", "final_of", "in_style", "listing", "particle", "plain_text", "skeleton", "slots_of", "split_ending", "style_of_tone",
           "tidy", "to_hapsyo"]
