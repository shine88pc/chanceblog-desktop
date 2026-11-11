"""내 글 문체 참고값(N-3a)의 **순수 계산** — 운영자가 직접 고른 본인 글(마크다운·텍스트·붙여 넣은 글) 하나를 세어 **숫자·참/거짓·없음(None)뿐인 불변 값**으로 돌려준다(결정 D-330–D-339).
표준 라이브러리와 N-2 의 보이지 않는 글자 목록(`check/garbage.py`)만 쓴다. 파일·네트워크·시계·무작위·전역 상태·저장·로그가 없고 프로필·설정·보관함 모듈은 가져오지 않는다 — 그래서 작업 스레드에서 안전하게 돌고,
**결과에는 글의 문장·낱말이 한 글자도 담기지 않는다**(값의 모든 칸이 숫자·참/거짓·None 이고 시험이 타입으로 확인한다). 읽은 글은 이 함수 안의 지역 변수로만 있다가 돌려주면서 사라진다.
N-3b(승인한 숫자를 프로필에 저장하고 초안 생성기에 적용)가 이 값을 그대로 받아 쓸 수 있게 모양을 두었지만 저장하는 칸·길은 없다.

**세는 것은 운영자가 정한 여섯 가지**(2026-11-10): ① 평균 문장 길이(산문 문장의 공백 뺀 글자 수) ② 문단당 문장 수 ③ 소제목 수 ④ 문장 끝 모양 네 부류의 비율 ⑤ 질문형 문장 비율 ⑥ 목록 사용 비율.
형태소 분석이 아니라 **겉모양 규칙**이라 오차가 있다 — 그 사실을 화면이 말한다(신뢰 안내는 `StyleStats` 의 `short`·`low_hangul` 같은 참/거짓 값이다). 판정 라벨(`전문적`·`격식체`)은 만들지 않는다.

전처리(세기 전에): 줄 끝(CRLF·CR·U+2028·U+2029 …)을 줄바꿈 하나로 통일 → 제어 문자와 N-2 의 보이지 않는 글자 목록의 글자를 지움 → NFC 로 합침(공백 자리에서 512자 조각으로 나눠 — 결합 글자가 긴 글에서 제곱 시간이 되는 N-2 의 교훈, D-322) →
마크다운의 머리말(맨 앞 `---` 두 줄 사이)·코드 블록·표·그림·링크 주소(글자만 남김)·HTML 표시를 걷어 내고, 모든 형식에서 인용 줄(`>`)·굵게/코드 표시·인터넷 주소·해시태그만 있는 줄·글자가 하나도 없는 장식 줄을 산문에서 뺀다.
  · 문단은 **빈 줄로 가른 덩어리**다. 마크다운은 문단 안의 줄바꿈을 공백으로 이어(부드러운 줄바꿈 — 글을 어떻게 줄바꿈했든 같은 값) 문장을 가른다. 텍스트·붙여 넣은 글은 줄바꿈의 뜻을 알 수 없어 **하드랩 감지**로 정한다 —
    문단 안에서 마지막 줄을 뺀 줄 가운데 문장 끝 부호로 끝나는 줄이 절반(`HARDWRAP_END_PERCENT`) 이상이면 줄바꿈마다 문장 경계로, 아니면 억지 줄바꿈으로 보고 잇는다. 두 방식의 문장 수를 모두 세어 30% 넘게 다르면
    `wrap_unstable`(줄바꿈 습관 때문에 숫자가 달라질 수 있다)이 켜진다. 줄마다 문장 경계로 읽었는데 문장 끝 부호로 끝나지 않은 줄이 섞여 두 방식의 문장 수가 조금이라도 다를 때도 켜진다 —
    억지 줄바꿈을 줄마다 한 문장으로 잘못 읽었을 수 있는 글(안쪽 줄의 절반을 겨우 넘는 글)이라, 숫자가 틀려도 안내가 없던 빈틈을 닫는다(D-430).
  · 문장 나누기는 `check/claims.split_sentences` 와 같은 규칙 — 마침표·물음표·느낌표·말줄임표(뒤에 닫는 따옴표·괄호가 와도 됨) 뒤가 공백이거나 끝일 때 자른다(소수점 3.5 는 자르지 않는다). 영문 글자 하나와 끝 부호뿐인 조각(`Q.`·`A.` 라벨)은 문장으로 세지 않는다(D-433).
  · 소제목은 마크다운의 제목 줄(`#`–`######`)이고 글 맨 앞 1단계 제목 하나는 글 제목이라 뺀다. 텍스트·붙여 넣은 글은 제목 표시가 없어 **0 이 아니라 None(알 수 없음)** 이다.
  · 문장 끝 네 부류(겉모양 그대로): `…니다`·`…니까`·`…십시오` / `…요`·`…죠` / `…다`(앞의 것 제외 — `…아니다` 는 `…니다` 로 끝나도 여기다, D-433) / 그 밖 — 끝의 부호·닫는 따옴표·물결·공백은 떼고 본다. 이모지·`ㅋㅋ` 로 끝나면 그 밖이다.
  · 질문형은 끝 부호에 물음표가 있거나 `…니까`·`…까요` 로 끝나는 문장이다(`…나요`·`…ㄴ가요` 는 물음표가 있을 때만 — 평서문 `만나요`·`생각나요` 를 질문으로 세지 않으려고 뺐다, D-431). 목록 사용 비율은 목록 덩어리 ÷ (목록 덩어리 + 산문 문단)이다.
글이 둘이면 `summarize` 가 문장·문단을 **모아서** 합산 값을 만든다(평균의 평균이 아니다). 운영자가 정한 네 기준(평균 문장 길이 40% 초과·소제목 수 3 초과·문단당 문장 수 2배 초과·질문형 비율 15%p 초과) 중 하나라도 넘으면
합산 값을 쓰지 않고 범위만 보이게 한다(`StyleSummary.range_only`). 비교는 분수(`Fraction`)로 해서 경계가 어긋나지 않는다.

**정규식은 모두 선형 시간**이다 — 글자 모음이 다음 시작 글자를 빼서 지나간 자리를 다시 훑지 않고, 정규화(NFC)는 공백 자리에서 512자 조각으로 나눠 부른다(10만 자가 어떤 입력에서도 2초 안 — `tests/test_content_style_stats_perf.py`).
소스에는 물결 글자·웹 주소를 날것으로 쓰지 않는다(글자는 코드 숫자로, 주소 머리는 조각으로).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, fields
from fractions import Fraction

from ..check import garbage as _garbage

FORMS = ("md", "txt", "pasted")                     # 입력 형식 — 마크다운 파일·텍스트 파일·직접 붙여 넣은 글(텍스트와 붙여 넣은 글은 세는 법이 같다)
MAX_CHARS = 100_000                                 # 글 하나의 상한(운영자 확정 — `service/own_posts.MAX_TEXT_CHARS` 와 같은 값, 시험이 견준다)
MIN_SENTENCES = 10                                  # 산문 문장이 이만큼 미만이면 짧은 글(숫자가 흔들린다)
MIN_CHARS = 600                                     # 산문 글자(공백 뺀)가 이만큼 미만이어도 짧은 글
LOW_HANGUL_PERCENT = 50                             # 한글이 글자(문자 종류 L) 중 이 값(%) 미만이면 한글이 적은 글
WRAP_GAP_PERCENT = 30                               # 줄을 이을 때와 줄마다 가를 때의 문장 수가 이 값(%) 넘게 다르면 줄바꿈 습관 안내
QUOTE_PERCENT = 30                                  # 인용 줄(`>`)의 글자가 (산문 + 인용 줄) 글자의 이 값(%) 이상이면 인용이 많은 글
CASUAL_PERCENT = 20                                 # 이모지·`ㅋㅋ` 같은 것으로 끝나는 문장이 이 값(%) 이상이면 문장 끝 비율이 맞지 않을 수 있다
HARDWRAP_END_PERCENT = 50                           # (텍스트·붙여 넣은 글) 마지막 줄을 뺀 줄 중 문장 끝 부호로 끝나는 줄이 이 값(%) 이상이면 줄바꿈마다 문장 경계, 미만이면 억지 줄바꿈이라 이어 센다
# 글 둘을 평균 내지 않고 범위만 보이는 기준 네 개 — 운영자가 정했다(2026-11-10 P023 답). 한 곳에 모아 두고 시험이 경계를 본다.
DIFF_SENTENCE_LENGTH = Fraction(7, 5)               # 평균 문장 길이: 큰 쪽이 작은 쪽의 1.4배 초과(= 40% 초과)
DIFF_HEADINGS = 3                                   # 소제목 수: 차이가 3 초과
DIFF_PER_PARAGRAPH = Fraction(2)                    # 문단당 문장 수: 큰 쪽이 작은 쪽의 2배 초과
DIFF_QUESTION = Fraction(3, 20)                     # 질문형 비율: 차이가 15%p 초과
NFC_CHUNK = 512                                     # NFC 정규화를 이만큼씩 나눠 부른다(공백 자리에서 끊는다 — 같은 글자 이음 10만 개를 한 번에 부르면 제곱 시간이다, D-322)
_NFC_SLACK = 8                                      # 공백 없이 긴 글을 억지로 끊을 때 결합 글자 앞에서 끊지 않으려고 늦추는 최대 글자 수

METRICS = ("sentence_length", "per_paragraph", "headings", "end_formal", "end_polite", "end_plain", "end_other", "question", "list")      # 화면에 보이는 숫자들(여섯 항목, 문장 끝은 네 부류)
NOTICES = ("empty", "short", "quote", "low_hangul", "casual", "wrap")                                                                      # 신뢰 안내의 열쇠 — 화면이 열쇠마다 고정 문장을 붙인다
_ENDINGS = ("end_formal", "end_polite", "end_plain", "end_other")


def _cls(*items):
    """코드 숫자(또는 (처음, 끝) 구간)들 → 정규식 글자 모음의 안쪽 글 — 소스에 눈에 안 보이는 글자·물결을 날것으로 쓰지 않으려고 숫자로 쓴다."""
    return "".join(chr(item) if isinstance(item, int) else chr(item[0]) + "-" + chr(item[1]) for item in items)


TILDE = chr(0x7E)                                   # 물결 글자는 소스에 직접 쓰지 않는다
_SCHEME = "https?" + ":" + "//"                     # 인터넷 주소 머리(날것의 웹 주소 글을 소스에 두지 않으려고 조각을 잇는다)
_TERM_CHARS = ".!?…。！？"                                      # 문장 끝 부호(`check/claims` 와 같은 글자)
_TERM_TUPLE = tuple(_TERM_CHARS)
_TERMINATORS = re.compile("[" + _TERM_CHARS + "]+")
_CLOSER_CHARS = "\"')]”’」』"                                 # 문장 끝 부호 뒤에 와도 되는 닫는 따옴표·괄호
_CLOSERS = frozenset(_CLOSER_CHARS)
_TRIM = _CLOSER_CHARS + TILDE                                                    # 문장 끝을 볼 때 부호와 함께 떼는 글자(공백은 따로)
_TAIL = _TRIM + _TERM_CHARS + " \t"                                              # 끝 모양을 보려고 모두 떼는 글자 — 부호·닫는 따옴표·물결·공백
_NEWLINES = {**{ord(char): "\n" for char in (chr(0x2028), chr(0x85), chr(0x0B), chr(0x0C), chr(0x1C), chr(0x1D), chr(0x1E))}, 0x2029: "\n\n"}      # CRLF·CR 말고 줄 구분으로 읽는 글자 — 줄바꿈 하나로, 문단 구분(U+2029)은 빈 줄이 되게 줄바꿈 둘로
_NOISE = re.compile("[" + _garbage._INVISIBLE_CLASS + _cls((0x00, 0x08), (0x0E, 0x1F), (0x7F, 0x9F)) + "]")       # 보이지 않는 글자(N-2 목록 재사용)와 줄바꿈·탭이 아닌 제어 문자
_WS = re.compile(r"\s+")
_HANGUL = re.compile("[" + _cls((0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7A3), (0xD7B0, 0xD7FF)) + "]+")
_FENCE = re.compile(" {0,3}(`{3,}|" + TILDE + "{3,})")
_QUOTE = re.compile(" {0,3}>")
_ATX = re.compile(" {0,3}(#{1,6})(?:[ \\t]|$)")
_BULLET = re.compile(" {0,3}(?:[-*+•ㆍ▪○●□■▶✔①-⑳]|[0-9]{1,3}[.)])[ \\t]+\\S")      # `-` `*` `+` 숫자. 숫자) 와 • ㆍ ▪ ○ ● □ ■ ▶ ✔ ①–⑳ 다음에 공백
_TABLE_START = re.compile(" {0,3}\\|")
_TABLE_SEP = re.compile(" {0,3}\\|?[ \\t]*:?-+:?[ \\t]*(?:\\|[ \\t]*:?-+:?[ \\t]*)*\\|?[ \\t]*")
_IMAGE = re.compile("!\\[[^\\[\\]\\n]*\\]\\([^()\\n]*\\)")                                                 # 그림 — 글자 모음이 `[`·`]`·괄호를 빼서 지나간 자리를 다시 훑지 않는다(선형)
_LINK = re.compile("\\[([^\\[\\]\\n]*)\\]\\([^()\\n]*\\)")                                                  # 링크 — 글자만 남긴다
_TAG = re.compile("</?(?:br|p|div|span|a|b|i|u|s|em|strong|img|h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|blockquote|hr|code|pre|center|font|sup|sub|small|big|figure|figcaption|details|summary|iframe|video|audio|source|section|article|header|footer|nav|aside|main|mark|strike|del|ins|dl|dt|dd|label|input|button)\\b[^<>]*>", re.IGNORECASE)
_AUTOLINK = re.compile("<(?:" + _SCHEME + "|www\\.)[^\\s<>]*>")                                              # 꺾쇠로 감싼 인터넷 주소 — 꺾쇠째 지운다
_URL = re.compile("(?:" + _SCHEME + "|www\\.)[\\x21-\\x3b\\x3d\\x3f-\\x7e]*")                                   # 인터넷 주소 — 주소에 쓰는 ASCII 글자까지만(주소 바로 뒤에 붙은 조사('…)로')는 지우지 않는다). `<`·`>` 는 뺀다
_URL_TAIL = ".,;:!?)]}'\""                                                                                   # 주소 끝에 붙은 문장 부호는 주소가 아니라 글의 부호다 — 지우지 않고 남긴다
_MARKS = re.compile("\\*+|_{2,}|`+")                                                                          # 굵게·기울임·코드 표시
_MAYBE_MARKED = re.compile("[*_`<\\[&]|http|www[.]")                                                          # 표시를 벗길 글자가 하나도 없는 글(아래 정규식이 맞을 수 있는 글자를 모두 덮는다) — 건드리지 않는다
_YAML_KEY = re.compile("[A-Za-z_][\\w-]*[ \\t]*:")                                                           # 머리말의 첫 줄(`layout:` 처럼 `이름:`) — 맨 앞의 가로줄 두 개 사이 글을 머리말로 잘못 지우지 않으려고 본다

_FORMAL_ENDS = ("니다", "니까", "십시오")           # 니다 니까 십시오
_NOT_FORMAL = "아니다"                                                   # 아니다 — `…니다` 로 끝나지만 합쇼가 아니라 평서다(D-433)
_YO_ENDS = ("요", "죠")                                                  # 요 죠
_PLAIN_END = "다"                                                            # 다
_QUESTION_ENDS = ("니까", "까요")                                        # 니까 까요 — 물음표가 없어도 질문이다. `…나요`·`…ㄴ가요` 는 평서문(만나요·생각나요·안 가요)이 많아 물음표가 있을 때만 질문이다(D-431)


def _ends_casual(core):
    """끝(부호·닫는 따옴표·물결을 뗀 글)이 이모지·기호(`So`·`Sk`)·낱자 자모(`ㅋ`·`ㅎ`·`ㅠ` …)로 끝나는가."""
    if not core:
        return False
    last = core[-1]
    return 0x3131 <= ord(last) <= 0x318E or unicodedata.category(last) in ("So", "Sk")


# ---- 결과 값 ----------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class StyleStats:
    """글 하나를 센 결과 — **모든 칸이 숫자·참/거짓·None** 이다(글·낱말·문장은 없다). 비율·평균은 칸에서 `Fraction` 으로 계산하는 속성이고 칸 자체는 센 개수다.
    `headings` 가 None 이면 제목 표시가 없는 형식이라 알 수 없다(0 이 아니다). 글이 둘일 때의 합산 값(`summarize` 의 `pooled`)도 같은 모양이고 개수는 두 글의 합이다(`headings` 도 합 — 한 글이라도 모르면 None)."""
    sentences: int                  # 센 산문 문장 수
    chars: int                      # 그 문장들의 글자 수(공백 뺀) 합
    paragraphs: int                 # 문장이 하나 이상 든 산문 문단 수
    list_blocks: int                # 목록 덩어리 수
    headings: int | None            # 소제목 수(마크다운만, 아니면 None)
    end_formal: int                 # …니다·…니까·…십시오 로 끝난 문장
    end_polite: int                 # …요·…죠
    end_plain: int                  # …다(위의 것 제외)
    end_other: int                  # 그 밖
    questions: int                  # 질문형 문장
    letters: int                    # 문장 속 글자(문자 종류 L)의 수
    hangul: int                     # 그중 한글
    quote_chars: int                # 인용 줄(`>`)에서 뺀 글자 수(공백 뺀)
    casual_ends: int                # 이모지·`ㅋㅋ` 같은 것으로 끝난 문장
    joined_sentences: int           # 문단 안 줄을 이어 문장을 갈랐을 때의 문장 수
    lined_sentences: int            # 줄바꿈마다 문장을 갈랐을 때의 문장 수(마크다운은 이은 값과 같다)
    line_mode: bool                 # 줄바꿈마다 문장 경계로 셌나(마크다운은 늘 False — 줄을 이어 센다)

    def __post_init__(self):
        for item in fields(self):
            number = getattr(self, item.name)
            if item.name == "line_mode":
                ok = isinstance(number, bool)
            elif item.name == "headings":
                ok = number is None or (isinstance(number, int) and not isinstance(number, bool) and number >= 0)
            else:
                ok = isinstance(number, int) and not isinstance(number, bool) and number >= 0
            if not ok:
                raise ValueError("셈 값의 칸은 0 이상의 정수와 참/거짓 하나뿐이다")

    # ---- 여섯 항목(분수 또는 None — 센 문장이 없으면 None, 0 이 아니다) ----
    @property
    def sentence_length(self):
        return Fraction(self.chars, self.sentences) if self.sentences else None

    @property
    def per_paragraph(self):
        return Fraction(self.sentences, self.paragraphs) if self.paragraphs else None

    @property
    def end_shares(self):
        """문장 끝 네 부류의 비율 4개(`_ENDINGS` 순서) 또는 None."""
        return tuple(Fraction(getattr(self, name), self.sentences) for name in _ENDINGS) if self.sentences else None

    @property
    def question_share(self):
        return Fraction(self.questions, self.sentences) if self.sentences else None

    @property
    def list_share(self):
        total = self.list_blocks + self.paragraphs
        return Fraction(self.list_blocks, total) if total else None

    @property
    def hangul_share(self):
        return Fraction(self.hangul, self.letters) if self.letters else None

    # ---- 신뢰 안내(참/거짓) ----
    @property
    def no_sentences(self):
        """세어 볼 산문 문장이 없다(표·그림·코드뿐인 글 …) — 숫자는 0 이 아니라 알 수 없음."""
        return self.sentences == 0

    @property
    def short(self):
        """짧은 글 — 문장 10개 미만이거나 산문 600자 미만이라 한두 문장이 숫자를 흔든다(문장이 하나도 없으면 `no_sentences` 가 말한다)."""
        return self.sentences > 0 and (self.sentences < MIN_SENTENCES or self.chars < MIN_CHARS)

    @property
    def low_hangul(self):
        """한글이 글자의 절반 미만 — 영문 문장이 많아 문장 끝 비율이 맞지 않는다."""
        return self.letters > 0 and self.hangul * 100 < LOW_HANGUL_PERCENT * self.letters

    @property
    def quote_heavy(self):
        """인용 줄(`>`)이 글의 30% 이상 — 본인 글의 숫자가 아닐 수 있다(큰따옴표 속 남의 말은 구별하지 못한다)."""
        return self.quote_chars > 0 and self.quote_chars * 100 >= QUOTE_PERCENT * (self.quote_chars + self.chars)

    @property
    def casual_heavy(self):
        """이모지·`ㅋㅋ` 같은 것으로 끝나는 문장이 20% 이상 — 문장 끝 부류가 `그 밖` 으로 몰린다."""
        return self.sentences > 0 and self.casual_ends * 100 >= CASUAL_PERCENT * self.sentences

    @property
    def wrap_unstable(self):
        """줄바꿈 습관 안내 — 줄을 이을 때와 줄마다 가를 때의 문장 수가 30% 넘게 다르거나(숫자가 크게 달라진다), 줄마다 문장 경계로 읽었는데 문장 끝 부호로 끝나지 않은 줄이 섞여
        두 방식의 문장 수가 조금이라도 다르다(억지 줄바꿈을 줄마다 한 문장으로 잘못 읽었을 수 있다 — 안쪽 줄의 절반을 겨우 넘는 글이 흔한 모양이다, D-430). 마크다운은 두 값이 같아 켜지지 않는다."""
        big = max(self.joined_sentences, self.lined_sentences)
        gap = abs(self.joined_sentences - self.lined_sentences)
        return big > 0 and (gap * 100 > WRAP_GAP_PERCENT * big or (self.line_mode and gap > 0))

    def notices(self):
        """켜진 신뢰 안내의 열쇠들(`NOTICES` 순서)."""
        flags = {"empty": self.no_sentences, "short": self.short, "quote": self.quote_heavy, "low_hangul": self.low_hangul, "casual": self.casual_heavy, "wrap": self.wrap_unstable}
        return tuple(name for name in NOTICES if flags[name])


@dataclass(frozen=True)
class StyleSummary:
    """글 1–2개의 결과 묶음 — 글별 값(`items`, 입력 순서)·문장·문단을 모아 센 합산 값(`pooled`, 글이 하나면 그 글 자신)·글 사이 차이 기준 넷을 넘었는가(`differs`, 한 글이거나 비교할 수 없으면 거짓).
    `range_only` 면 평균을 내지 않고 범위만 보인다. 모두 숫자·참/거짓이다."""
    items: tuple
    pooled: StyleStats
    differs: tuple

    @property
    def range_only(self):
        return any(self.differs)


def _pool(items):
    if len(items) == 1:
        return items[0]
    total = {}
    for item in fields(StyleStats):
        name = item.name
        if name == "line_mode":
            total[name] = any(stats.line_mode for stats in items)
        elif name == "headings":
            known = [stats.headings for stats in items]
            total[name] = None if any(count is None for count in known) else sum(known)
        else:
            total[name] = sum(getattr(stats, name) for stats in items)
    return StyleStats(**total)


def _differs(first, second):
    """운영자가 정한 네 기준 — (평균 문장 길이, 소제목 수, 문단당 문장 수, 질문형 비율)을 넘었는가. 한쪽이라도 값이 없으면(세어 볼 문장이 없거나 제목을 알 수 없음) 그 기준은 비교하지 않는다."""
    flags = []
    a, b = first.sentence_length, second.sentence_length
    flags.append(a is not None and b is not None and max(a, b) > min(a, b) * DIFF_SENTENCE_LENGTH)
    flags.append(first.headings is not None and second.headings is not None and abs(first.headings - second.headings) > DIFF_HEADINGS)
    a, b = first.per_paragraph, second.per_paragraph
    flags.append(a is not None and b is not None and max(a, b) > min(a, b) * DIFF_PER_PARAGRAPH)
    a, b = first.question_share, second.question_share
    flags.append(a is not None and b is not None and abs(a - b) > DIFF_QUESTION)
    return tuple(flags)


def summarize(items):
    """글 하나나 둘의 결과를 묶는다 — 합산 값은 문장·문단을 모은 값이고 평균의 평균이 아니다. 개수가 맞지 않거나 `StyleStats` 가 아니면 `ValueError`."""
    items = tuple(items)
    if not 1 <= len(items) <= 2 or not all(isinstance(stats, StyleStats) for stats in items):
        raise ValueError("글은 한 개나 두 개의 셈 값이어야 한다")
    return StyleSummary(items, _pool(items), _differs(*items) if len(items) == 2 else (False, False, False, False))


def value(stats, metric):
    """항목 하나의 값 — 분수·정수·None(알 수 없음). `METRICS` 의 열쇠."""
    if metric == "sentence_length":
        return stats.sentence_length
    if metric == "per_paragraph":
        return stats.per_paragraph
    if metric == "headings":
        return stats.headings
    if metric in _ENDINGS:
        shares = stats.end_shares
        return None if shares is None else shares[_ENDINGS.index(metric)]
    if metric == "question":
        return stats.question_share
    if metric == "list":
        return stats.list_share
    raise ValueError("알 수 없는 항목이다")


def span(items, metric):
    """여러 글의 한 항목 범위 (최소, 최대) — 값을 아는 글이 없으면 None. 글이 하나면 (값, 값)."""
    known = [found for found in (value(stats, metric) for stats in items) if found is not None]
    return (min(known), max(known)) if known else None


# ---- 전처리 ----------------------------------------------------------------------------------------------------------------------
def _nfc(text):
    """NFC 로 합친다 — 공백 자리에서 `NFC_CHUNK` 글자 안팎으로 나눠 부른다(공백은 합쳐지지 않으므로 보통 글에서는 한 번에 부른 것과 같다. 공백 없이 긴 글만 `NFC_CHUNK` 마다 끊는다)."""
    if text.isascii():
        return text
    pieces, start, size = [], 0, len(text)
    while start < size:
        end = min(start + NFC_CHUNK, size)
        if end < size:
            cut = end
            while cut > start + NFC_CHUNK // 2 and not text[cut - 1].isspace():
                cut -= 1
            if text[cut - 1].isspace():
                end = cut
            else:                                                                   # 공백 없이 긴 글의 억지 끊기 — 다음 글자가 결합 글자(결합 부호·한글 모음·받침 자모)면 최대 8자까지 늦춰 한 글자가 둘로 갈리지 않게 한다
                limit = min(end + _NFC_SLACK, size)
                while end < limit and (unicodedata.combining(text[end]) or 0x1161 <= ord(text[end]) <= 0x11FF):
                    end += 1
        pieces.append(unicodedata.normalize("NFC", text[start:end]))
        start = end
    return "".join(pieces)


def _prepare(text):
    """줄 끝을 `\\n` 하나로 통일하고 제어 문자·보이지 않는 글자를 지우고 NFC 로 합친다 → 줄 목록(CRLF 파일도 문단이 있는 글로 읽힌다)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_NEWLINES)
    return _nfc(_NOISE.sub("", text)).split("\n")


def _front_matter_end(lines):
    """마크다운 머리말(맨 앞 `---` 줄과 다음 `---`·`...` 줄 사이, 첫 줄이 `이름:` 모양)이 끝나는 줄 번호 + 1 — 머리말이 아니거나 닫는 줄이 없으면 0."""
    first = next((number for number, line in enumerate(lines) if line.strip()), None)
    if first is None or lines[first].strip() != "---":
        return 0
    body = next((number for number in range(first + 1, len(lines)) if lines[number].strip()), None)
    if body is None or not (_YAML_KEY.match(lines[body].strip()) or lines[body].strip() in ("---", "...")):
        return 0
    for number in range(first + 1, len(lines)):
        if lines[number].strip() in ("---", "..."):
            return number + 1
    return 0


def _fence_opens(line):
    """코드 블록을 여는 줄이면 (글자, 길이) — 역따옴표 줄은 뒤에 역따옴표가 있으면(한 줄 안 코드 조각) 코드 블록이 아니다."""
    found = _FENCE.match(line)
    if found is None:
        return None
    marker = found.group(1)
    if marker[0] == "`" and "`" in line[found.end():]:
        return None
    return marker[0], len(marker)


def _fence_closes(line, opened):
    """열린 코드 블록(`opened`)을 닫는 줄인가 — 같은 글자로 열린 길이 이상이고 뒤에 다른 글이 없다."""
    found = _FENCE.match(line)
    return found is not None and found.group(1)[0] == opened[0] and len(found.group(1)) >= opened[1] and not line[found.end():].strip()


def _visible(text):
    return len(_WS.sub("", text))


def _url_gone(found):
    """인터넷 주소를 지우되 끝에 붙은 문장 부호는 남긴다('…주소.' 의 마침표가 문장 끝 부호이므로)."""
    text = found.group(0)
    return text[len(text.rstrip(_URL_TAIL)):]


def _clean(text, markdown):
    """산문 한 덩어리(한 줄 또는 이은 문단)의 표시를 벗긴다 — 마크다운의 그림·링크(글자만 남김)·HTML 표시, 모든 형식의 인터넷 주소·굵게/코드 표시."""
    if _MAYBE_MARKED.search(text) is None:
        return text.strip()
    if markdown:
        text = _IMAGE.sub("", text)
        text = _LINK.sub("\\1", text)
        text = _TAG.sub(" ", text)
        text = text.replace("&nbsp;", " ")
    return _MARKS.sub("", _URL.sub(_url_gone, _AUTOLINK.sub("", text))).strip()


def _join(lines):
    """문단의 줄들을 공백으로 잇는다 — 낱말 가운데(영문 하이픈 뒤)에서 억지로 줄바꿈된 것은 공백 없이 이어 하이픈 낱말·주소가 둘로 갈리지 않게 한다."""
    return "".join(line if len(line) > 1 and line.endswith("-") and line[-2].isalnum() else line + " " for line in lines).strip()


def _prose(line):
    """장식 줄(글자·숫자가 하나도 없다)과 해시태그만 있는 줄이 아니라 산문 줄인가(표시를 벗기기 전의 줄로 본다)."""
    if not any(map(str.isalnum, line)):
        return False
    if "#" not in line:                                                             # 해시 표시가 없으면 해시태그만 있는 줄일 수 없다
        return True
    return not all(word.startswith("#") for word in line.split())


def _parse(lines, markdown):
    """줄들 → (산문 문단들 — 각 문단은 줄 목록(마크다운은 원래 줄, 나머지는 표시를 벗긴 줄), 목록 덩어리 수, 소제목 수 또는 None, 인용 줄 글자 수). 문단은 빈 줄로 가른 덩어리이고 제목·목록·표·코드·인용·장식 줄이 끼면 거기서 끊긴다."""
    if markdown:
        lines = lines[_front_matter_end(lines):]
    paragraphs, current, lists, quote_chars = [], [], 0, 0
    headings = 0 if markdown else None
    in_list = in_table = started = False
    fence = None

    def close():
        nonlocal current
        if current:
            paragraphs.append(current)
            current = []

    for raw in lines:
        if fence is not None:                                                       # 코드 블록 안 — 닫는 줄까지 읽지 않는다(닫는 줄이 없으면 끝까지)
            if _fence_closes(raw, fence):
                fence = None
            continue
        line = raw.rstrip()
        if not line.strip():
            close()
            in_table = False                                                        # 빈 줄은 표를 끝낸다(목록은 빈 줄로 끝나지 않는다)
            continue
        if markdown:
            opened = _fence_opens(line)
            if opened is not None:
                close()
                fence, in_list, in_table, started = opened, False, False, True
                continue
        if _QUOTE.match(line):                                                      # 인용 줄 — 산문에서 빼고 글자만 센다(인용이 많은 글을 알리려고)
            close()
            quote_chars += _visible(line.replace(">", ""))
            in_list, in_table, started = False, False, True
            continue
        if markdown:
            if _TABLE_START.match(line) or (in_table and "|" in line):
                close()
                in_list, in_table, started = False, True, True
                continue
            if "|" in line and current and "|" in current[-1] and _TABLE_SEP.fullmatch(line):          # 첫 `|` 없이 시작하는 표 — 구분 줄을 보고 바로 위의 머리 줄까지 표로 본다
                current.pop()
                close()
                in_list, in_table, started = False, True, True
                continue
            heading = _ATX.match(line)
            if heading is not None:
                close()
                if not (len(heading.group(1)) == 1 and not started):                # 글 맨 앞 1단계 제목 하나는 글 제목이라 소제목이 아니다
                    headings += 1
                in_list, in_table, started = False, False, True
                continue
        in_table = False
        if _BULLET.match(line):
            close()
            if not in_list:
                lists += 1
                in_list = True
            started = True
            continue
        if in_list and line.startswith(("  ", "\t")):                              # 들여쓴 줄은 앞 목록 항목의 이어지는 글이다
            continue
        in_list = False
        started = True
        if not _prose(line):                                                        # 장식 줄·해시태그 줄은 문단을 끊기만 한다(그림·주소만 있는 줄은 문단에 두고 문단을 이은 뒤에 벗겨 낸다 — 문단 가운데 줄이 주소 하나뿐이어도 문단이 갈리지 않는다)
            close()
            continue
        current.append(line.strip())                                                # 원래 줄을 둔다 — 링크·그림·주소가 줄 사이에 걸칠 수 있어 문단을 이은 뒤에 한 번에 벗긴다(줄마다 세는 글만 줄 하나씩 벗긴다)
    close()
    return paragraphs, lists, headings, quote_chars


# ---- 문장 ------------------------------------------------------------------------------------------------------------------------
def _label_only(piece):
    """`Q.`·`A.` 처럼 영문 글자 하나와 끝 부호뿐인 조각인가 — 문장이 아니라 라벨이다(D-433). 한글 한 글자(`네.`)는 문장이다."""
    if len(piece) > 8:                                                              # 라벨은 짧다 — 긴 조각은 훑지 않는다(병적 입력에서 시간을 아낀다)
        return False
    letters = [char for char in piece if char.isalnum()]
    return len(letters) == 1 and letters[0].isascii() and letters[0].isalpha()


def _split(text):
    """글 한 덩어리를 문장으로 가른다 — 마침표·물음표·느낌표·말줄임표(뒤에 닫는 따옴표·괄호가 와도 됨) 뒤가 공백이거나 끝일 때(소수점 3.5 는 아니다). 글자·숫자가 하나도 없는 조각과 `Q.`·`A.` 같은 라벨 조각은 버린다."""
    pieces, start, size = [], 0, len(text)
    for match in _TERMINATORS.finditer(text):
        end = match.end()
        while end < size and text[end] in _CLOSERS:
            end += 1
        if end >= size or text[end].isspace():
            pieces.append(text[start:end])
            while end < size and text[end].isspace():
                end += 1
            start = end
    pieces.append(text[start:])
    return [piece.strip() for piece in pieces if any(map(str.isalnum, piece)) and not _label_only(piece)]


def _line_mode(cleaned):
    """(텍스트·붙여 넣은 글) 줄바꿈마다 문장 경계인 글인가 — 문단의 마지막 줄을 뺀 줄 중 문장 끝 부호로 끝나는 줄이 절반 이상이면 그렇다(한 줄 한 문장). 그런 줄이 하나도 없으면(문단마다 한 줄) 어느 쪽이든 같다."""
    inner = ended = 0
    for lines in cleaned:
        if lines is None:
            continue                                                                # 한 줄짜리 문단은 안쪽 줄이 없다
        for line in lines[:-1]:
            inner += 1
            if line.rstrip(_TRIM + " \t").endswith(_TERM_TUPLE):
                ended += 1
    return inner > 0 and ended * 100 >= HARDWRAP_END_PERCENT * inner


def _ending(sentence):
    """문장 하나 → (끝 부류 번호 0–3, 질문인가, 이모지 같은 끝인가). 끝의 부호·닫는 따옴표·물결·공백을 떼어 보고, 질문은 뗀 부호에 물음표가 있거나 질문 끝말이다."""
    core = sentence.rstrip(_TAIL)
    tail = sentence[len(core):]
    asked = "?" in tail or "？" in tail or core.endswith(_QUESTION_ENDS)
    if core.endswith(_FORMAL_ENDS) and not core.endswith(_NOT_FORMAL):
        kind = 0
    elif core.endswith(_YO_ENDS):
        kind = 1
    elif core.endswith(_PLAIN_END):
        kind = 2
    else:
        kind = 3
    return kind, asked, _ends_casual(core)


def analyze(text, form):
    """글 하나(`form` 은 `md`·`txt`·`pasted`)를 세어 `StyleStats` 로 돌려준다. 글이 문자열이 아니거나 10만 자를 넘거나 형식이 틀리면 `ValueError`(고정 문장 — 글은 오류에 없다). 결과에는 글이 없다."""
    if not isinstance(text, str):
        raise ValueError("글은 문자열이어야 한다")
    if len(text) > MAX_CHARS:
        raise ValueError("글이 너무 길다")
    if form not in FORMS:
        raise ValueError("알 수 없는 글 형식이다")
    markdown = form == "md"
    paragraphs, lists, headings, quote_chars = _parse(_prepare(text), markdown)
    cleaned = None if markdown else [[_clean(line, False) for line in lines] if len(lines) > 1 else None for lines in paragraphs]       # 줄마다 표시를 벗긴 글(줄이 둘 이상인 문단만) — 하드랩 판정과 줄마다 세기가 같이 쓴다
    lined_mode = False if markdown else _line_mode(cleaned)
    counts = [0, 0, 0, 0]                                                           # 끝 부류별 문장 수
    sentences = chars = paragraph_count = questions = letters = hangul = casual = joined_total = lined_total = 0
    for number, lines in enumerate(paragraphs):
        joined = _split(_clean(_join(lines), markdown))
        lined = joined if markdown or len(lines) == 1 else [piece for line in cleaned[number] for piece in _split(line)]
        joined_total += len(joined)
        lined_total += len(lined)
        chosen = lined if lined_mode else joined
        if not chosen:
            continue
        paragraph_count += 1
        for sentence in chosen:
            sentences += 1
            chars += _visible(sentence)
            kind, asked, light = _ending(sentence)
            counts[kind] += 1
            questions += int(asked)
            casual += int(light)
            letters += sum(map(str.isalpha, sentence))
            hangul += sum(len(found.group(0)) for found in _HANGUL.finditer(sentence))
    return StyleStats(sentences, chars, paragraph_count, lists, headings, counts[0], counts[1], counts[2], counts[3], questions, letters, hangul, quote_chars, casual, joined_total, lined_total, lined_mode)


__all__ = ["DIFF_HEADINGS", "DIFF_PER_PARAGRAPH", "DIFF_QUESTION", "DIFF_SENTENCE_LENGTH", "FORMS", "MAX_CHARS", "METRICS", "NOTICES", "StyleStats", "StyleSummary", "analyze", "span", "summarize", "value"]
