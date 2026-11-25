"""키 값·이름의 '모양' 검사 — 이 모듈은 비밀이 입력 오류 문구·로그·출력에 새지 않게 하려고 **값을 돌려주거나 문구에 넣지 않는다**(docs/SECURITY.md §7).

이 검사는 `security.mask`(출력 마지막 관문)와 별개의 **자기 검사**다. 비밀 모양을 낱말 경계(`\\b`)에 기대어 찾지 않고 어디에 붙어 있어도(한글·괄호·따옴표·줄바꿈 바로 옆) 찾는다.
모든 정규식은 길이가 정해진 글자 종류의 반복뿐이라 입력 길이에 선형으로 걸린다(30만 자도 1초 안).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# 보이지 않거나 글자 방향을 바꾸는 글자의 범주 — 값에 섞이면 화면·로그에서 다른 값처럼 보인다
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs"})
# 눈에 안 보이는 채움·서식 글자(한글 채움 U+3164·점자 빈칸 U+2800·변형 선택자 …) — 범주만으로는 걸리지 않는 것들(security/mask.py 의 목록과 같은 범위)
_FILLERS = re.compile(r"[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb\U000e0000-\U000e0fff]")
_ALLOWED_VALUE = re.compile(r"[A-Za-z0-9_\-+/=.~:]+")        # 키·ID·토큰에 쓰이는 글자(영문·숫자와 `_ - + / = . ~ :`) — 따옴표·괄호·공백·한글은 붙여 넣기 실수다
_ALNUM_VALUE = re.compile(r"[A-Za-z0-9_\-]+")                  # 공식 문서에 모양이 없는 값(NAVER API HUB 의 Client ID·Secret)을 느슨하게 보는 글자 — 영문·숫자와 `_ -` 만
MAX_SCAN_CHARS = 100_000                                       # 이 길이를 넘는 글은 비밀을 찾을 것도 없이 모양이 틀린 것으로 본다(실패 열림 금지)

# 알려진 비밀 접두사 — 접두사 바로 뒤에 짧게라도 이어지면 비밀 모양으로 본다(앞 글자는 따지지 않는다)
_PREFIXED = re.compile(
    r"AIza[0-9A-Za-z_\-]{10,}"
    r"|AQ\.[0-9A-Za-z_\-]{10,}"
    r"|GOCSPX-[0-9A-Za-z_\-]{8,}"
    r"|1//0[0-9A-Za-z_\-]{10,}"
    r"|ya29\.[0-9A-Za-z_\-]{10,}"
    r"|gh[pousr]_[0-9A-Za-z]{10,}"
    r"|github_pat_[0-9A-Za-z_]{10,}"
    r"|xox[baprs]-[0-9A-Za-z\-]{6,}"
    r"|AKIA[0-9A-Z]{8,}"
    r"|sk-[0-9A-Za-z_\-]{12,}"
    r"|eyJ[0-9A-Za-z_\-]{8,}\.[0-9A-Za-z_\-]{4,}"
    r"|-----BEGIN"
    r"|[0-9]{6,12}:[0-9A-Za-z_\-]{20,}"
)
_TOKEN_RUN = re.compile(r"[A-Za-z0-9_\-+/=.~]{24,}")           # 24자 이상 이어진 영문·숫자 덩어리 — 영문자와 숫자가 함께 있으면 토큰처럼 생겼다


def has_hidden_char(text):
    """제어 문자·눈에 안 보이는 글자·공백(보통 공백 포함)이 하나라도 있나."""
    return bool(_FILLERS.search(text)) or any(unicodedata.category(ch) in _HIDDEN_CATEGORIES for ch in text)


def looks_secret(text):
    """글 어딘가에 비밀 모양(알려진 접두사·긴 영문 숫자 덩어리)이 있나. 값 자체는 돌려주지 않는다. 너무 긴 글은 못 믿어 참(True)이다."""
    if not isinstance(text, str):
        return True
    if len(text) > MAX_SCAN_CHARS:
        return True
    if _PREFIXED.search(text):
        return True
    for found in _TOKEN_RUN.finditer(text):
        run = found.group()
        if any(ch.isalpha() for ch in run) and any(ch.isdigit() for ch in run):
            return True
    return False


def value_problem(value, *, min_len, max_len, charset=""):
    """키·ID 한 칸의 모양이 올바르지 않은 이유(쉬운 한국어, **값을 넣지 않는다**). 올바르면 ''. `charset="alnum"` 이면 영문·숫자와 `_ -` 만 허용한다(그 밖의 글자는 이유만 알린다)."""
    if not isinstance(value, str):
        return "글이 아닙니다"
    if len(value) > MAX_SCAN_CHARS:
        return f"너무 깁니다(최대 {max_len}자)"                       # 아주 긴 값은 아래 검사를 돌리지 않고 바로 거절
    if has_hidden_char(value):
        return "공백·줄바꿈·눈에 안 보이는 글자가 들어 있습니다(앞뒤 공백도 안 됩니다)"
    if len(value) < min_len:
        return f"너무 짧습니다(최소 {min_len}자)"
    if len(value) > max_len:
        return f"너무 깁니다(최대 {max_len}자)"
    if charset == "alnum":
        if not _ALNUM_VALUE.fullmatch(value):
            return "영문·숫자와 _ - 만 쓸 수 있습니다(따옴표·괄호·한글·붙여 넣은 설명 글이 섞이지 않았는지 확인합니다)"
        return ""
    if not _ALLOWED_VALUE.fullmatch(value):
        return "영문·숫자와 _ - + / = . ~ : 만 쓸 수 있습니다(따옴표·괄호·한글·붙여 넣은 설명 글이 섞이지 않았는지 확인합니다)"
    return ""


def label_problem(value, *, max_len):
    """이름·소속 프로젝트처럼 **비밀이 아닌** 글자 칸의 모양 오류(없으면 ''). 비밀이 파일에 남지 않게 키처럼 생긴 글은 거절한다(값은 문구에 넣지 않는다)."""
    if not isinstance(value, str):
        return "글이 아닙니다"
    if len(value) > MAX_SCAN_CHARS:
        return f"너무 깁니다(최대 {max_len}자)"
    if _FILLERS.search(value) or any(unicodedata.category(ch) in _HIDDEN_CATEGORIES - {"Zs"} for ch in value):
        return "줄바꿈·눈에 안 보이는 글자가 들어 있습니다"
    if value != " ".join(value.split()):
        return "앞뒤 공백이나 연속된 공백이 있습니다"
    if len(value) > max_len:
        return f"너무 깁니다(최대 {max_len}자)"
    if looks_secret(value):
        return "키나 토큰처럼 보이는 글이 들어 있습니다(이름에는 키를 적지 않습니다)"
    return ""


def short_digest(text):
    """한도 묶음 이름에 쓰는 짧은 해시(SHA-256 앞 8자) — 클라이언트 ID 같은 **비밀이 아닌** 칸의 값을 파일에 그대로 적지 않으려고. 비밀 칸의 값에는 쓰지 않는다(약한 값은 해시만으로 대입해 알아낼 수 있다 —
    같은 값을 두 번 넣는 것은 지문이 아니라 보관소의 값을 직접 비교해 막는다)."""
    return hashlib.sha256(("chanceblog-desktop:bucket:1\0" + text).encode("utf-8", "surrogatepass")).hexdigest()[:8]


# ---- 이름 붙은 값(`password: …`·`secret=…` — 결정 D-682) -----------------------------------------------------------------------------------
# 복사 전 관문이 접두사 모양·긴 영숫자 덩어리만 봐서 `password: Hunter2xyz`·`secret=Ab12Cd34` 같은 메모가 막힘도 확인창도 없이 클립보드로 갔다(앱 2차 감사 AS-S2 권고-1). 가리기 규칙(`mask`)은 이런 글을 가리지만
# 복사 관문은 그 규칙을 쓰지 않았다. 이름 낱말은 가리기 규칙과 **같은 목록**(`mask._NAME_WORDS` — password·secret·token·credential·sessionid·api key 계열)에 한국어 이름 다섯(비밀번호·비번·패스워드·시크릿·인증키)을 더한 것이다.
# 값이 키·비밀번호처럼 생겼을 때**만** 걸린 자리로 센다 — 글에서 이름 뒤에 값처럼 보이는 낱말이 오는 일은 흔해서(`비밀번호: 8자 이상`·`token = get_token(user1)`) 전부 막으면 쓸 수 없는 관문이 된다:
#   · 값 머리(따옴표를 뺀 뒤 키·토큰에 쓰이는 글자 — 영문·숫자와 `_ - + / = . : ! @ # $ % ^ *`·물결표 — 로 이어진 부분)가 6자 이상 200자 이하이고 영문자와 숫자가 함께 있다(`Hunter2xyz`·`Ab12Cd34`·`sk_test_1234…`).
#   · 숫자뿐인 값(`1234`)·글자뿐인 값(`strong`)·짧은 값·자리 표시(`<your password>`·`YOUR_API_KEY`·`********`)·변수 꼴(`$TOKEN_1`)·코드(`req.body.password1`·`get_token(user1)` — 점으로 이은 소문자 이름, 값 머리가 괄호 앞에서 끊긴다)는 아니다.
#   · 주소 인자(`?token=…`·`&secret=…` — 이름 앞이 `? & ; #`)는 이 규칙이 아니라 주소 규칙이 본다(`draft_rules._address_hit` — 그쪽의 한계는 D-312).
# 안전한 기본값(위임 규칙)은 '막고 수정을 요청한다'이다 — 예시 값이 비밀번호처럼 생겼으면 예시여도 막는다(안내 문구가 값을 지우거나 문장으로 바꿔 쓰라고 알려 준다). 한계: 값이 숫자뿐이거나 글자뿐이거나 여섯 글자 미만인 비밀번호, 공백이 든 값은 못 본다.
MIN_NAMED_VALUE, MAX_NAMED_VALUE = 6, 200
_KO_NAMES = "비밀번호|비번|패스워드|시크릿|인증키"
_NAMED_NEEDLES = ("password", "passwd", "secret", "token", "credential", "sessionid", "session_id", "key", "비밀번호", "비번", "패스워드", "시크릿", "인증키")        # 이름 낱말이 하나도 없는 글은 정규식을 돌리지 않는다
_FULLWIDTH_SEPARATORS = chr(0xFF1A) + chr(0xFF1D)                                                      # 전각 `：`·`＝`
_VALUE_HEAD = re.compile(r"[A-Za-z0-9_\-+/=.\x7e:!@#$%^*]+")
_CODE_PATH = re.compile(r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+")                                      # `req.body.password1` — 점으로 이은 소문자 이름은 코드다
_CURLY_QUOTES = "".join(chr(code) for code in (0x201C, 0x201D, 0x2018, 0x2019))
_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")
_NAMED_PATTERN = None


def _named_pattern():
    """이름 낱말 + `:`·`=` + 값을 찾는 정규식(처음 부를 때 한 번 만든다 — 가리기 모듈의 이름 목록을 쓰려고 늦게 가져온다). 값은 따옴표로 묶은 글(300자까지)이거나 공백·따옴표·쉼표·세미콜론·`&` 전까지의 덩어리(4–300자)다."""
    global _NAMED_PATTERN
    if _NAMED_PATTERN is None:
        from .mask import _NAME_WORDS
        _NAMED_PATTERN = re.compile(r"(?i)(?:" + _NAME_WORDS + "|" + _KO_NAMES + r")s?[\"']?[ \t]*[:=" + _FULLWIDTH_SEPARATORS + r"][ \t]*(?P<value>\"[^\"\n]{1,300}\"|'[^'\n]{1,300}'|[^\s\"',;&]{4,300})")
    return _NAMED_PATTERN


def is_secret_like_value(raw):
    """`이름: 값` 의 값(따옴표로 묶었어도 된다)이 키·비밀번호처럼 생겼는가 — 위 설명의 규칙. 값을 돌려주거나 어디에도 적지 않는다."""
    if not isinstance(raw, str):
        return False
    value = raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0] else raw
    head = _VALUE_HEAD.match(value.strip(_CURLY_QUOTES))
    if head is None:
        return False
    token = head.group().rstrip(".:!")
    if not MIN_NAMED_VALUE <= len(token) <= MAX_NAMED_VALUE or token[0] in "$%" or _CODE_PATH.fullmatch(token):
        return False
    return any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token)


def _after_address_mark(text, start):
    """이름이 주소 인자(`?이름=…`·`&이름=…`·`;이름=…`·`#이름=…`)의 이름인가 — 이름 앞의 이름 글자(`x_`·`api.`)를 거슬러 올라가 그 앞이 `? & ; #` 이면 주소 인자다(최대 80글자까지만 본다)."""
    index = start
    for _ in range(80):
        if index == 0 or text[index - 1] not in _NAME_CHARS:
            break
        index -= 1
    return index > 0 and text[index - 1] in "?&;#"


def named_secret_spans(text):
    """글 속 '이름: 값' 가운데 값이 키·비밀번호처럼 생긴 것의 자리 → ((시작, 끝), …) 글자 번호(끝은 포함하지 않는다, 따옴표로 묶은 값은 따옴표까지). 값은 돌려주지 않는다.
    글이 아니거나 너무 길면(`MAX_SCAN_CHARS` 초과 — 그쪽은 길이 한도가 막는다) 빈 튜플이다. 입력 길이에 선형이다(이름 낱말이 없는 글은 정규식을 돌리지 않는다)."""
    if not isinstance(text, str) or len(text) > MAX_SCAN_CHARS:
        return ()
    low = text.lower()
    if not any(needle in low for needle in _NAMED_NEEDLES):
        return ()
    spans = []
    for found in _named_pattern().finditer(text):
        if is_secret_like_value(found.group("value")) and not _after_address_mark(text, found.start()):
            spans.append(found.span("value"))
    return tuple(spans)
