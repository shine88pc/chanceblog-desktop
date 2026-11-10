"""'글 모양 점검' 규칙(N-2) — 글에 섞여 들어온 쓰레기 모양(가비지 텍스트)을 **경고만 하려고** 찾는다. 글을 고치거나 지우거나 바꿔 쓰지 않는다. 표준 라이브러리만 쓰고 파일·네트워크·시계·무작위·전역 상태가 없다(그래서 작업 스레드에서 안전하게 돈다).

찾는 것은 운영자가 정한 일곱 항목이다(2026-11-10). 화면 순서는 아래 `KINDS` 와 같다.
  · `broken` 깨진 문자 — 대체 문자(U+FFFD)·UTF-8 을 다른 글자표로 잘못 읽은 모양·사용자 정의 영역 글자·글자가 아닌 코드와 짝 없는 서로게이트·낱개 한글 자모 이음
  · `invisible` 보이지 않는 글자(Zero-width) — 폭 없는 공백·이음·소프트 하이픈·한글 채움·변형 선택자 …(이모지 이음·하트 이모지 뒤의 변형 선택자처럼 정상으로 쓰는 문맥은 거른다). **같은 글자는 한 건으로 묶는다**
  · `control` 제어 문자 — 줄바꿈·탭·CR 이 아닌 것
  · `entity` HTML 표시 — 세미콜론이 있고 HTML 표준 이름표에 있는 `&nbsp;` 꼴·숫자 꼴
  · `fence` 코드 블록 표시 — 줄 앞 공백 세 칸까지 뒤에 역따옴표 세 개 이상으로 시작하는 줄(물결 세 개 줄은 닫는 줄이 짝으로 있을 때만). 한 건으로 묶는다
  · `placeholder` 자리표시 — 중괄호 두 겹·`{% %}`·`{# #}`·`${ }`·한 겹 중괄호 낱말·정해 둔 대괄호 낱말
  · `dup_word`·`dup_sentence` 중복 단어·문장 — 한글 어절은 3번 연속부터, 영문 두 글자 이상은 2번부터. 문장은 10글자 이상이 2번 이상

**돌려주는 것은 위치와 종류뿐이다** — (종류·하위 종류·지문·위치 구간). 걸린 글을 결과에 담지 않는다(화면 쪽이 위치로 다시 잘라 가려서 보인다). 지문은 종류와 걸린 글의 정규화한 모양을 해시한 짧은 값이라
**같은 지문은 같은 것으로 보고 한 번에 무시**할 수 있다(위치로 기억하면 글을 고칠 때 밀린다). 같은 종류에서 겹치는 자리는 가장 긴 하나로 합친다(`{{이름}}` 은 두 규칙이 겹쳐 찾는다).

**코드 예시 영역**(의도한 코드로 보는 곳) 안의 HTML 표시·자리표시는 걸지 않는다: 짝이 맞는 코드 블록 줄 사이·한 줄 안 역따옴표 한 쌍(안쪽 200자까지)·`>` 로 시작하는 인용 줄(운영자 2026-11-10 — 코드 블록 표시 자체는 알린다).
**정규식은 모두 길이가 정해진 것이라 선형 시간**이다. 문장 지문의 정규화(NFKC)는 길이가 크게 늘어나는 글자·긴 결합 글자 이음에서 제곱 시간이라 `NFKC_CHUNK` 글자씩 나눠 부른다 — 그래서 시험한 병적 입력(10만 자)도 2초 안이다(`tests/test_check_garbage_perf.py`). 한 글이 `MAX_SCAN_CHARS`(복사 관문의 키 모양 검사와 같은 상한)를 넘으면 점검하지 않고 건너뛰었다고 알린다(`Report.skipped`).
소스에는 눈에 안 보이는 글자를 날것으로 쓰지 않는다 — 글자 모음은 코드 숫자로 쓰고 `_cls` 가 정규식 글을 만든다.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass
from html.entities import html5

MAX_SCAN_CHARS = 100_000                        # 한 글(제목·본문 각각)이 이 길이를 넘으면 점검을 건너뛴다 — `security/shape.MAX_SCAN_CHARS` 와 같은 값(시험이 견준다)
KINDS = ("broken", "invisible", "control", "entity", "fence", "placeholder", "dup_word", "dup_sentence")     # 화면에 보이는 고정 순서
FIELDS = ("title", "body")
HANGUL_REPEAT = 3                               # 한글(숫자 포함) 어절이 이만큼 붙어서 되풀이되면 건다 — 두 번 강조('정말 정말 좋아요')는 걸지 않는다
LATIN_REPEAT = 2                                # 영문 글자만인 두 글자 이상 어절은 두 번부터('the the')
MIN_WORD_CORE = 2                               # 앞뒤 기호를 뗀 어절이 이보다 짧으면(한 글자) 세지 않는다
MIN_SENTENCE_KEY = 10                           # 글자·숫자만 남긴 문장이 이만큼 이상일 때만 같은 문장으로 센다('감사합니다.' 두 번은 아니다)
CODE_SPAN_MAX = 200                             # 한 줄 안 역따옴표 한 쌍 사이의 글자 수 상한(병적 입력에서도 선형 시간)
FENCE_MIN = 3                                   # 코드 블록 표시의 글자 수
FENCE_INDENT = 3                                # 줄 앞 공백 칸 수 상한
FLAG_LOOKBACK = 8                               # 깃발 이모지 뒤 태그 글자를 찾는 거리
ENTITY_MAX = 0x10FFFF
NFKC_CHUNK = 512                                # 문장 지문의 NFKC 정규화를 이만큼씩 나눠 부른다 — 한 번에 부르면 U+0F73 10만 개에 19초(제곱 시간)였다(D-322)

_KIND_RANK = {kind: rank for rank, kind in enumerate(KINDS)}
_FIELD_RANK = {"title": 0, "body": 1}


def _cls(*items):
    """코드 숫자(또는 (처음, 끝) 구간)들 → 정규식 글자 모음의 안쪽 글 — 눈에 안 보이는 글자를 소스에 날것으로 쓰지 않으려고 숫자로 쓴다."""
    return "".join(chr(item) if isinstance(item, int) else (chr(item[0]) if item[0] == item[1] else chr(item[0]) + "-" + chr(item[1])) for item in items)


def _chars(*items):
    """코드 숫자(또는 (처음, 끝) 구간)들 → 그 글자들을 늘어놓은 문자열 — `str.strip` 이나 `in` 에 쓴다(`_cls` 는 정규식 글이다)."""
    return "".join(chr(code) for item in items for code in ((item,) if isinstance(item, int) else range(item[0], item[1] + 1)))


@dataclass(frozen=True)
class Finding:
    """한 건 — 걸린 글은 담지 않는다. `spans` 는 ((칸, 시작, 끝), …) 이고 칸은 `title`·`body`, 시작·끝은 그 칸 글의 글자 번호(0부터, 끝은 포함하지 않는다)다."""
    kind: str
    sub: str                                    # 하위 종류 — 깨진 문자의 갈래·보이지 않는 글자의 코드(`U+200B`)·자리표시의 모양 …
    fingerprint: str                            # 종류 + 걸린 글의 정규화한 모양을 해시한 짧은 값(같은 것은 한 번에 무시)
    spans: tuple
    repeats: int = 0                            # 같은 낱말이 붙어서 되풀이된 횟수(`dup_word`)·같은 문장이 나온 횟수(`dup_sentence`)
    adjacent: bool = False                      # `dup_sentence` 가 바로 이어서 되풀이됨(붙여 넣다 겹친 흔적)


@dataclass(frozen=True)
class Report:
    findings: tuple = ()
    skipped: bool = False                       # 너무 길어 점검하지 않았다 — 조용히 건너뛰지 않고 화면이 말한다


# ---- 글자 모음 ----------------------------------------------------------------------------------------------------------------------------
# 보이지 않는 글자: 소프트 하이픈·결합 글자 이음·아랍 글자 표시·한글 채움 둘·몽골 변형 표시·폭 없는 글자와 방향 표시(200B-200F)·단어 이음과 보이지 않는 연산(2060-2064)·쓰지 않는 서식 글자(206A-206F)·
# 한글 채움 글자·변형 선택자·글머리 표시(BOM)·반각 한글 채움·태그 글자
_INVISIBLE_CODES = (0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, (0x180B, 0x180E), (0x200B, 0x200F), (0x2060, 0x2064), (0x206A, 0x206F), 0x3164, (0xFE00, 0xFE0F), 0xFEFF, 0xFFA0, 0xE0001, (0xE0020, 0xE007F))
_INVISIBLE_CLASS = _cls(*_INVISIBLE_CODES)
_INVISIBLE_CHARS = _chars(*_INVISIBLE_CODES)                # `str.strip` 에 줄 글자 문자열(정규식 글이 아니다)
_INVISIBLE = re.compile("[" + _INVISIBLE_CLASS + "]")
_BLANK = re.compile("[\\s" + _INVISIBLE_CLASS + "]*")       # 공백이나 보이지 않는 글자뿐인 줄 — 눈에는 빈 줄이다
# 화면에 그대로 보이면 안 보이거나 깨져 보이는 글자(제어 문자·보이지 않는 글자·줄 구분 글자·대체 문자·사용자 정의 영역) — 화면 쪽이 조각을 보일 때 네모로 바꾼다
HIDDEN = re.compile("[" + _cls((0x00, 0x08), 0x0B, 0x0C, (0x0E, 0x1F), (0x7F, 0x9F), 0x2028, 0x2029, 0xFFFD, (0xE000, 0xF8FF)) + _INVISIBLE_CLASS + "]")
_EOL = re.compile("\r\n|\r|\n")


def _lines(text):
    """글의 줄들 → [(시작, 줄 글의 끝, 다음 줄의 시작)]. 줄바꿈은 CR+LF·CR·LF 셋이고 마지막 줄바꿈 뒤의 빈 줄도 한 줄이다."""
    spans, position, size = [], 0, len(text)
    while True:
        found = _EOL.search(text, position)
        if found is None:
            spans.append((position, size, size))
            return spans
        spans.append((position, found.start(), found.end()))
        position = found.end()


def is_blank(line):
    return _BLANK.fullmatch(line) is not None


class LineIndex:
    """글 한 덩어리의 문단·줄 구조 — 글자 번호를 `(문단, 줄, 글자)` 로 바꾼다. 문단은 **빈 줄(공백이나 보이지 않는 글자뿐인 줄)로 가른 덩어리**이고 번호는 첫 글이 있는 문단부터 1 이다.
    줄은 그 문단 안의 줄 번호, 글자는 줄 안의 순번(1부터)이다. 빈 줄 위의 글자는 줄 번호가 0 이고 문단은 그 앞의 마지막 문단 번호다(맨 앞 빈 줄이면 0)."""

    def __init__(self, text):
        self.starts, self.paragraphs, self.numbers = [], [], []
        paragraph, number, blank_before = 0, 0, True
        for start, stop, _next in _lines(text):
            self.starts.append(start)
            if _BLANK.fullmatch(text, start, stop):
                blank_before = True
                self.paragraphs.append(paragraph)
                self.numbers.append(0)
                continue
            if blank_before:
                paragraph, number = paragraph + 1, 0
            number += 1
            blank_before = False
            self.paragraphs.append(paragraph)
            self.numbers.append(number)

    def locate(self, index):
        row = max(0, bisect_right(self.starts, max(0, index)) - 1)
        return self.paragraphs[row], self.numbers[row], max(0, index) - self.starts[row] + 1

    def line_start(self, index):
        return self.starts[max(0, bisect_right(self.starts, max(0, index)) - 1)]


def locate(text, index):
    """글자 번호 → (문단, 줄, 글자) — `LineIndex` 한 번짜리 도우미."""
    return LineIndex(text).locate(index)


# ---- 코드 예시 영역 --------------------------------------------------------------------------------------------------------------------
_FENCE_LINE = re.compile("[ ]{0,%d}(`{%d,}|\\x7e{%d,})" % (FENCE_INDENT, FENCE_MIN, FENCE_MIN))       # 물결 글자는 소스에 직접 쓰지 않는다(\x7e)
_QUOTE_LINE = re.compile("[ ]{0,%d}>" % FENCE_INDENT)
_TICKS = re.compile("`+")
TILDE = chr(0x7E)                                           # 물결 글자는 소스에 직접 쓰지 않는다


def _fence_candidates(text, lines):
    """코드 블록 표시처럼 보이는 줄들 → [(줄 번호, 표시 시작, 표시 끝, 글자, 길이, 뒤에 다른 글이 없는가)]. 역따옴표 줄은 뒤에 역따옴표가 있으면(한 줄 안의 코드 조각) 표시가 아니다."""
    found = []
    for number, (start, stop, _next) in enumerate(lines):
        match = _FENCE_LINE.match(text, start, stop)
        if match is None:
            continue
        marker = match.group(1)
        rest = text[match.end():stop]
        if marker[0] == "`" and "`" in rest:
            continue
        if marker[0] == TILDE and TILDE in rest:                 # '물결 세 개 + 일기 + 물결 세 개' 는 장식 줄이지 코드 블록 표시가 아니다(D-316 ⑦)
            continue
        found.append((number, match.start(1), match.end(1), marker[0], len(marker), not rest.strip()))
    return found


def _pair_fences(candidates):
    """같은 글자로 열고 닫는 한 쌍(닫는 줄은 열린 줄 길이 이상이고 뒤에 다른 글이 없다) → [(여는 후보 번호, 닫는 후보 번호)]. 짝이 없는 열림은 코드 영역이 아니다."""
    pairs, opened = [], None
    for index, (_number, _start, _end, char, size, bare) in enumerate(candidates):
        if opened is None:
            opened = index
        elif char == candidates[opened][3] and size >= candidates[opened][4] and bare:
            pairs.append((opened, index))
            opened = None
    return pairs


def _inline_spans(text, start, stop, regions):
    """한 줄 안의 역따옴표 한 쌍(같은 길이의 역따옴표 묶음 둘) 사이를 코드 영역에 더한다 — 안쪽이 `CODE_SPAN_MAX` 글자 이하일 때만. 가장 가까운 같은 길이 묶음과 짝을 짓고 짝이 없으면 글자 그대로다."""
    runs = [(match.start(), match.end()) for match in _TICKS.finditer(text, start, stop)]
    if len(runs) < 2:
        return
    following, last = [-1] * len(runs), {}
    for number in range(len(runs) - 1, -1, -1):
        size = runs[number][1] - runs[number][0]
        following[number] = last.get(size, -1)
        last[size] = number
    number = 0
    while number < len(runs):
        partner = following[number]
        if partner != -1 and runs[partner][0] - runs[number][1] <= CODE_SPAN_MAX:
            regions.append((runs[number][0], runs[partner][1]))
            number = partner + 1
        else:
            number += 1


def _structure(text):
    """(코드 영역의 시작들, 끝들, {`backtick`·`tilde`: [표시 구간]}) — 코드 영역은 짝이 맞는 코드 블록·인용 줄(`>`)·한 줄 안 역따옴표 한 쌍이고 겹치면 합친다. 표시 구간은 알릴 코드 블록 표시 줄의 표시 글자 구간이다."""
    lines = _lines(text)
    regions, marks = [], {"backtick": [], "tilde": []}
    candidates = _fence_candidates(text, lines)
    paired = set()
    for opening, closing in _pair_fences(candidates):
        paired.update((opening, closing))
        regions.append((lines[candidates[opening][0]][0], lines[candidates[closing][0]][1]))
    for index, (_number, start, end, char, _size, _bare) in enumerate(candidates):
        if char == "`":
            marks["backtick"].append((start, end))
        elif index in paired:
            marks["tilde"].append((start, end))
    for start, stop, _next in lines:
        if _QUOTE_LINE.match(text, start, stop):
            regions.append((start, stop))
        if text.find("`", start, stop) != -1:
            _inline_spans(text, start, stop, regions)
    regions.sort()
    starts, ends = [], []
    for start, end in regions:
        if end <= start:
            continue
        if ends and start <= ends[-1]:
            ends[-1] = max(ends[-1], end)
        else:
            starts.append(start)
            ends.append(end)
    return starts, ends, marks


def _inside(starts, ends, position):
    row = bisect_right(starts, position) - 1
    return row >= 0 and position < ends[row]


# ---- 지문 --------------------------------------------------------------------------------------------------------------------------------
def _fingerprint(kind, sub, token, cache):
    key = (kind, sub, token)
    found = cache.get(key)
    if found is None:
        digest = hashlib.sha256(("chanceblog-desktop:garbage:1\0" + kind + "\0" + sub + "\0" + token).encode("utf-8", "surrogatepass")).hexdigest()
        found = cache[key] = f"{kind}:{digest[:12]}"
    return found


def _collapsed(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


# ---- ② 깨진 문자 -------------------------------------------------------------------------------------------------------------------------
# UTF-8 글자를 다른 글자표로 읽은 흔적은 '앞 글자 + 이어진 기호' 의 조합일 때만 건다(프랑스어·스페인어 낱말은 걸리지 않는다). 윈도 글자표(cp1252)의 0x80-0x9F 자리에 오는 기호들이 꼬리다.
_MOJIBAKE_TAIL = _cls((0x80, 0xBF), 0x0152, 0x0153, 0x0160, 0x0161, 0x0178, 0x017D, 0x017E, 0x0192, 0x02C6, 0x02DC, (0x2013, 0x203A), 0x20AC, 0x2122)
_MOJIBAKE = re.compile(
    "(?:[" + _cls(0xC2, 0xC3) + "][" + _cls((0x80, 0xBF)) + "]"                                                  # 모음 위에 점이 붙은 글자 꼴
    "|" + chr(0xE2) + chr(0x20AC) + "[" + _cls(0x2122, 0x0153, 0x009D, 0x201C, 0x201D, 0x00A6, 0x02DC, 0x00A2, 0x2013, 0x2014) + "]"      # 따옴표·줄표·말줄임이 세 글자로 깨진 꼴
    "|[" + _cls(0xEA, 0xEB, 0xEC, 0xED) + "][" + _MOJIBAKE_TAIL + "]{2}"                                         # 한글이 앞 글자 하나와 기호 둘로 깨진 꼴
    "|" + chr(0xEF) + chr(0xBF) + chr(0xBD) + ")+")                                                           # 대체 문자 자체가 깨진 꼴
_BROKEN = (
    ("replacement", re.compile(chr(0xFFFD) + "+")),                                                       # 읽다가 실패한 자리에 들어가는 대체 문자
    ("mojibake", _MOJIBAKE),
    ("private_use", re.compile("[" + _cls((0xE000, 0xF8FF)) + "]+")),                                     # 한컴 문서 등에서 복사하면 네모로 보이는 글자
    ("noncharacter", re.compile("[" + _cls((0xFDD0, 0xFDEF), 0xFFFE, 0xFFFF, (0xD800, 0xDFFF)) + "]+")),   # 글자가 아닌 코드·짝 없는 서로게이트
    ("jamo_run", re.compile("[" + _cls((0x1100, 0x11FF), (0xA960, 0xA97F), (0xD7B0, 0xD7FF)) + "]{2,}")),  # 맥에서 복사한 분리형 한글(낱개 자모 이음) — 화면에는 정상으로 보일 수 있다
)


# ---- ④ 제어 문자 -------------------------------------------------------------------------------------------------------------------------
_CONTROL_RUN = re.compile("([" + _cls((0x00, 0x08), 0x0B, 0x0C, (0x0E, 0x1F), (0x7F, 0x9F)) + "])\\1*")      # 탭(09)·줄바꿈(0A)·CR(0D) 은 뺀다 — 윈도 줄바꿈·표 복사본을 오탐하지 않는다


# ---- ③ 보이지 않는 글자 ------------------------------------------------------------------------------------------------------------------
_EMOJI_CODES = frozenset((0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299, 0xFE0F, 0x20E3))
_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2190, 0x21FF), (0x2300, 0x23FF), (0x2460, 0x24FF), (0x25A0, 0x27BF), (0x2900, 0x297F), (0x2B00, 0x2BFF))
_BLACK_FLAG = chr(0x1F3F4)


def _emojiish(char):
    if not char:
        return False
    code = ord(char)
    return code in _EMOJI_CODES or any(low <= code <= high for low, high in _EMOJI_RANGES)


def _wordish(char):
    """영문·숫자·한글·한자 한 글자인가 — 폭 없는 비이음(U+200C)이 이런 글자 곁에 있을 때만 건다(페르시아·인도 문자의 정상 쓰임은 거른다)."""
    if not char:
        return False
    code = ord(char)
    return (char.isascii() and char.isalnum()) or 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F or 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF


def _normal_use(text, index, code):
    """보이지 않는 글자가 정상으로 쓰이는 문맥인가 — 이모지 이음(가족·직업)·이모지/기호/숫자 뒤의 변형 선택자(하트·키캡)·깃발 뒤 태그 글자·한글·영문·숫자·한자 곁이 아닌 비이음."""
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    if code == 0x200D:
        return _emojiish(before) and _emojiish(after)
    if code in (0xFE0F, 0xFE0E):
        return _emojiish(before) or before.isdigit() or before in ("#", "*")
    if 0xE0020 <= code <= 0xE007F:
        return _BLACK_FLAG in text[max(0, index - FLAG_LOOKBACK):index]
    if code == 0x200C:
        return not (_wordish(before) or _wordish(after))
    return False


def _invisible(field, text, grouped):
    for match in _INVISIBLE.finditer(text):
        code = ord(match.group())
        if _normal_use(text, match.start(), code):
            continue
        grouped.setdefault(("invisible", f"U+{code:04X}", match.group()), []).append((field, match.start(), match.end()))


# ---- ⑤ HTML 엔티티 -----------------------------------------------------------------------------------------------------------------------
_ENTITY = re.compile("&(#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")


def _entities(field, text, starts, ends, hits):
    for match in _ENTITY.finditer(text):
        body = match.group(1)
        if body[0] == "#":
            hexadecimal = body[1] in "xX"
            if not 1 <= int(body[2:] if hexadecimal else body[1:], 16 if hexadecimal else 10) <= ENTITY_MAX:
                continue
            sub = "numeric"
        elif body + ";" in html5:
            sub = "named"
        else:
            continue
        if not _inside(starts, ends, match.start()):
            hits.append(("entity", sub, field, match.start(), match.end(), match.group(), 0))


# ---- ⑦ 자리표시 --------------------------------------------------------------------------------------------------------------------------
_PLACEHOLDERS = (
    ("double_brace", re.compile("\\{\\{.{0,80}?\\}\\}")),
    ("percent_brace", re.compile("\\{%.{0,80}?%\\}")),
    ("hash_brace", re.compile("\\{#.{0,80}?#\\}")),
    ("dollar_brace", re.compile("\\$\\{[^{}\\n]{1,60}\\}")),
    ("brace", re.compile("\\{\\w{1,40}(?::[^{}/\\n]{1,20}/[^{}/\\n]{1,20})?\\}")),                     # 이 앱의 초안 틀이 쓰는 조사 슬롯(`{낱말:을/를}`)도 남아 있으면 덜 채워진 것이다
    ("bracket", re.compile(
        "\\[(?:이름|제목|내용|대상[^\\]\\n]{0,20}|키워드|주제|링크|여기에[^\\]\\n]{0,20}|입력[^\\]\\n]{0,10}|삽입[^\\]\\n]{0,10}|todo|your [a-z ]{1,20}|insert [a-z ]{1,20})\\]", re.IGNORECASE)),
)


def _placeholders(field, text, starts, ends, hits):
    for sub, pattern in _PLACEHOLDERS:
        for match in pattern.finditer(text):
            if not _inside(starts, ends, match.start()):
                hits.append(("placeholder", sub, field, match.start(), match.end(), _collapsed(match.group()), 0))


# ---- ① 중복 단어 -------------------------------------------------------------------------------------------------------------------------
_TOKEN = re.compile("\\S+")
_BLANK_GAP = re.compile("(?:\r\n|\r|\n)[^\\S\r\n]*(?:\r\n|\r|\n)")              # 빈 줄 — 문단 경계(같은 낱말 반복을 끊는다)
_JAMO_ONLY = re.compile("[" + _cls((0x3130, 0x318F)) + "]+")                  # 자모만 있는 어절(웃음·울음 표시)
# 낱말 사이에 문장부호·괄호가 끼면 같은 낱말을 되풀이해 쓴 것이 아니라 문장·목록·인용의 짜임이다('Credit: ESA. ESA operates'·'NASA, [NASA Explores'·'No, no, no') — D-323.
# 앞 낱말이 끝맺는 부호·말줄임표·닫는 괄호로 끝나거나 다음 낱말이 여는 괄호로 시작하면 이어 붙이지 않는다. 굵은 표시·따옴표·보이지 않는 글자는 건너뛰고 본다.
_RUN_BREAK_END = frozenset(".!?:;," + _chars(0x2026, 0x3001, 0x3002, 0xFF01, 0xFF1F, 0xFF1A, 0xFF1B, 0xFF0C) + ")]}" + _chars(0xFF09, 0xFF3D, 0xFF5D, 0x300D, 0x300F, 0x300B, 0x3009, 0x3011, 0x3015))
_RUN_BREAK_OPEN = frozenset("([{" + _chars(0xFF08, 0xFF3B, 0xFF5B, 0x300C, 0x300E, 0x300A, 0x3008, 0x3010, 0x3014))
_RUN_SKIP = "*_`\"'" + TILDE + _chars(0x2018, 0x2019, 0x201C, 0x201D, 0xAB, 0xBB, 0x2039, 0x203A) + _INVISIBLE_CHARS         # 부호 검사에서 건너뛰는 글자(굵은 표시·따옴표·보이지 않는 글자)


def _core(token):
    """어절에서 앞뒤의 글자·숫자가 아닌 것(문장부호·따옴표·기호·이모지)과 보이지 않는 글자를 떼고 소문자로 맞춘 모양."""
    token = _INVISIBLE.sub("", token)
    low, high = 0, len(token)
    while low < high and not token[low].isalnum():
        low += 1
    while high > low and not token[high - 1].isalnum():
        high -= 1
    return token[low:high].casefold()


def _repeat_needed(core):
    """이 낱말이 몇 번 붙어서 되풀이되면 거는가 — 건너뛸 낱말이면 0. 한 글자·자모뿐·숫자뿐은 세지 않는다."""
    if len(core) < MIN_WORD_CORE or _JAMO_ONLY.fullmatch(core) or core.replace(",", "").replace(".", "").isdigit():
        return 0
    return LATIN_REPEAT if core.isascii() and core.isalpha() else HANGUL_REPEAT


def _run_breaks(previous, current):
    """앞 낱말(`previous`)과 다음 낱말(`current`) 사이에 문장부호·괄호가 끼었나 → 끼었으면 같은 낱말의 되풀이가 아니다."""
    tail = previous.rstrip(_RUN_SKIP)
    if tail and tail[-1] in _RUN_BREAK_END:
        return True
    head = current.lstrip(_RUN_SKIP)
    return bool(head) and head[0] in _RUN_BREAK_OPEN


def _dup_words(field, text, hits):
    breaks = [match.start() for match in _BLANK_GAP.finditer(text)]
    run_core, run_start, run_end, run_count, run_paragraph, run_last = "", 0, 0, 0, -1, ""

    def flush():
        if run_count >= LATIN_REPEAT:
            needed = _repeat_needed(run_core)
            if needed and run_count >= needed:
                hits.append(("dup_word", "latin" if needed == LATIN_REPEAT else "hangul", field, run_start, run_end, f"{run_core}\0{run_count}", run_count))

    for match in _TOKEN.finditer(text):
        raw = match.group()
        core = _core(raw)
        paragraph = bisect_right(breaks, match.start())
        if run_count and core and core == run_core and paragraph == run_paragraph and not _run_breaks(run_last, raw):
            run_count += 1
            run_end = match.end()
            run_last = raw
            continue
        flush()
        run_core, run_start, run_end, run_count, run_paragraph, run_last = core, match.start(), match.end(), 1, paragraph, raw
    flush()


# ---- ① 중복 문장 -------------------------------------------------------------------------------------------------------------------------
# 문장 나누기는 `check/claims.split_sentences` 와 같은 규칙이다(마침표·물음표·느낌표·말줄임표 뒤에 닫는 따옴표·괄호가 붙어도 되고, 줄바꿈에서도 자른다). 이쪽은 **위치**도 알아야 해서 같은 규칙을 위치와 함께 쓴다 — 시험이 두 결과가 같은지 견준다.
_BREAK_RUN = re.compile("[" + _cls(0x0A, 0x0D, 0x2028, 0x2029) + "]+")
_TERMINATOR_RUN = re.compile("[.!?" + _cls(0x2026, 0x3002, 0xFF01, 0xFF1F) + "]+")
_CLOSERS = frozenset("\"')]" + _cls(0x201D, 0x2019, 0x300D, 0x300F))
_NOT_ALNUM = re.compile("[\\W_]+")


def sentence_spans(text):
    """글을 문장으로 나눈 구간들 → [(시작, 끝)] (앞뒤 공백을 뗀 글의 자리, 빈 문장은 뺀다)."""
    pieces, position = [], 0
    ends = [match.span() for match in _BREAK_RUN.finditer(text)] + [(len(text), len(text))]
    for break_start, break_end in ends:
        start = position
        for match in _TERMINATOR_RUN.finditer(text, position, break_start):
            end = match.end()
            while end < break_start and text[end] in _CLOSERS:
                end += 1
            if end >= break_start or text[end].isspace():
                pieces.append((start, end))
                while end < break_start and text[end].isspace():
                    end += 1
                start = end
        pieces.append((start, break_start))
        position = break_end
    spans = []
    for start, end in pieces:
        piece = text[start:end]
        stripped = piece.strip()
        if stripped:
            begin = start + len(piece) - len(piece.lstrip())
            spans.append((begin, begin + len(stripped)))
    return spans


def _nfkc(text):
    """호환 문자를 푼다(NFKC) — **`NFKC_CHUNK` 글자씩 나눠** 부른다. 한 번에 부르면 길이가 크게 늘어나는 글자(U+FDFA 는 18글자로)와 긴 결합 글자 이음(U+0F73 은 둘로 풀려 정렬이 제곱)에서 느려진다(10만 개에 19초 — GIL 을 쥔 채라 화면 스레드도 같은 시간 멈춘다).
    같은 글은 늘 같은 자리에서 잘려 같은 모양이 되고, 조각 경계에서 결합 글자 하나가 못 합쳐지는 것은 같은 문장을 못 알아보는 쪽(경고 한 건 덜)일 뿐 거짓 경고를 만들지 않는다."""
    return "".join(unicodedata.normalize("NFKC", text[start:start + NFKC_CHUNK]) for start in range(0, len(text), NFKC_CHUNK))        # 짧은 글은 조각 하나다


def sentence_key(sentence):
    """같은 문장인지 견주는 모양 — 보이지 않는 글자를 지우고 호환 문자를 풀고(NFKC, 조각으로) 소문자로 하고 글자·숫자만 남긴 글."""
    return _NOT_ALNUM.sub("", _nfkc(_INVISIBLE.sub("", sentence)).casefold())


def _dup_sentences(text, cache):
    spans = sentence_spans(text)
    seen = {}
    for order, (start, end) in enumerate(spans):
        key = sentence_key(text[start:end])
        if len(key) >= MIN_SENTENCE_KEY:
            seen.setdefault(key, []).append((order, start, end))
    found = []
    for key, items in seen.items():
        if len(items) < 2:
            continue
        adjacent = any(second[0] == first[0] + 1 for first, second in zip(items, items[1:]))
        found.append(Finding("dup_sentence", "sentence", _fingerprint("dup_sentence", "sentence", key, cache), tuple(("body", start, end) for _order, start, end in items), len(items), adjacent))
    return found


# ---- 모아서 ------------------------------------------------------------------------------------------------------------------------------
def _without_overlaps(hits):
    """같은 종류의 겹치는 자리는 가장 긴 하나만 남긴다 — 앞에서 시작한 것이 이기고 같은 시작이면 긴 것이 이긴다."""
    kept, last = [], {}
    for hit in sorted(hits, key=lambda item: (_KIND_RANK[item[0]], _FIELD_RANK[item[2]], item[3], -item[4])):
        group = (hit[0], hit[2])
        if last.get(group, -1) > hit[3]:
            continue
        kept.append(hit)
        last[group] = hit[4]
    return kept


def _order(finding):
    field, start = finding.spans[0][0], finding.spans[0][1]
    return (_KIND_RANK[finding.kind], finding.kind == "dup_sentence" and not finding.adjacent, _FIELD_RANK[field], start)


def scan(title, body):
    """제목과 본문을 한 번에 훑어 `Report` 를 돌려준다. 글을 바꾸지 않고 읽기만 한다 — 같은 글이면 늘 같은 결과다. 글이 아니면 빈 글로 본다. 제목·본문 중 하나가 `MAX_SCAN_CHARS` 를 넘으면 `skipped` 다."""
    title = title if isinstance(title, str) else ""
    body = body if isinstance(body, str) else ""
    if len(title) > MAX_SCAN_CHARS or len(body) > MAX_SCAN_CHARS:
        return Report((), True)
    cache, hits, grouped = {}, [], {}
    for field, text in (("title", title), ("body", body)):
        if not text:
            continue
        starts, ends, marks = _structure(text)
        for sub, pattern in _BROKEN:
            hits += [("broken", sub, field, match.start(), match.end(), "".join(sorted(set(match.group()))), 0) for match in pattern.finditer(text)]    # 지문 = 하위 종류 + 걸린 글자들(U+FFFD 는 몇 개가 이어졌든 같고 모지바케는 글자가 다르면 다르다)
        hits += [("control", f"U+{ord(match.group(1)):04X}", field, match.start(), match.end(), match.group(1), 0) for match in _CONTROL_RUN.finditer(text)]
        _invisible(field, text, grouped)
        _entities(field, text, starts, ends, hits)
        for sub, spans in marks.items():
            if spans:
                grouped.setdefault(("fence", sub, sub), []).extend((field, start, end) for start, end in spans)
        _placeholders(field, text, starts, ends, hits)
        _dup_words(field, text, hits)
    findings = [Finding(kind, sub, _fingerprint(kind, sub, token, cache), ((field, start, end),), repeats) for kind, sub, field, start, end, token, repeats in _without_overlaps(hits)]
    findings += [Finding(kind, sub, _fingerprint(kind, sub, token, cache), tuple(sorted(spans, key=lambda span: (_FIELD_RANK[span[0]], span[1])))) for (kind, sub, token), spans in grouped.items()]
    findings += _dup_sentences(body, cache)
    findings.sort(key=_order)
    return Report(tuple(findings))
