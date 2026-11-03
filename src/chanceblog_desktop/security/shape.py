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


def value_problem(value, *, min_len, max_len):
    """키·ID 한 칸의 모양이 올바르지 않은 이유(쉬운 한국어, **값을 넣지 않는다**). 올바르면 ''."""
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


TAIL_MIN_LEN = 16               # 이 길이 이상일 때만 끝 4자를 보인다(짧은 값은 끝 4자가 전체의 큰 부분이라 아무것도 보이지 않는다)
TAIL_SHOWN = 4


def tail_hint(value):
    """목록에 보이는 `****끝4자` — 값이 16자 이상일 때만, 아니면 ''."""
    if isinstance(value, str) and len(value) >= TAIL_MIN_LEN:
        return "****" + value[-TAIL_SHOWN:]
    return ""
