"""로그·오류 보고서에 나가는 글에서 비밀로 보이는 것을 가린다(docs/SECURITY.md §2).

규칙의 정본은 chanceblog 의 `pipeline/secret_patterns.py` 이고(`vendor/` 로 원본 그대로 가져온 것), 여기서는 그 패턴을 그대로 써서 글 속 비밀 모양을
`[가림: <이름>]` 으로 바꾼다. 거기에 이 앱이 다루는 글에서 더 필요한 세 가지를 더한다: 주소 속 `사용자:토큰@`(비밀번호에 `@` 가 들어 있어도),
주소의 `?access_token=…` 같은 인자, `Bearer <토큰>`. 정본의 `sk-` 패턴이 못 알아보는 붙임표·밑줄이 든 새 키 모양(OpenAI `sk-proj-…`·Anthropic `sk-ant-api03-…`·OpenRouter `sk-or-v1-…`과 그 밖의 `sk-` 긴 모양)도 가린다. 어떤 입력이 와도 예외를 내지 않고(없는 값은 빈 글), 이미 가린 글을 다시 가려도 같다.
PCSEC1 H1 로 더한 것: 이름 목록 확장(serviceKey·authKey·appKey·secretKey·clientSecret·X-Api-Key·Ocp-Apim-Subscription-Key …), `Authorization`·`Proxy-Authorization`·`Cookie`·`Set-Cookie` 줄(쿠키는 이름 불문 모든 값), 전각·키릴 동형 문자·퍼센트로 쓴 이름과 이스케이프 JSON, XML 태그·`--옵션 값`·`Key=값`, base64 로 감싼 값, 쪼갠 값 — 아래 `_hidden_forms` 에 모였다(원문 규칙 뒤에 돈다).
"""
from __future__ import annotations

import base64
import bisect
import re
import unicodedata

from ..core import use_vendored_core

use_vendored_core()
from pipeline.secret_patterns import SECRET_PATTERNS  # noqa: E402  (vendor/ 경로를 먼저 올려야 한다)

MAX_LOG_CHARS = 2000
MAX_MASK_INPUT = 200_000           # 이보다 긴 글은 앞부분만 가린다(나머지는 내보내지 않는다 — 아주 긴 글에서 오래 걸리지 않게)
_HIDDEN = frozenset({"Cf", "Cc", "Cs", "Co", "Zl", "Zp"})     # 서식·제어·대용·사용자 지정·줄/문단 구분 문자 — 눈에 안 보이거나 글자 방향을 바꾼다
# 눈에 안 보이는 글자(폭 없는 글자·방향 제어·태그·변형 선택자·채움 글자 …) — 비밀을 이 글자로 쪼개 패턴을 피하는 것을 막으려고 먼저 지운다.
# 서식 문자(Cf)는 아래 범주 검사로도 지워지지만 범위로도 적어 둔다: 아직 글자가 배정되지 않은 빈 자리(U+2065·U+E0000 …)와 파이썬의 유니코드 버전 차이까지 같은 결과가 되게
_INVISIBLE = re.compile(r"[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb\U000e0000-\U000e0fff]")
# `//` 바로 뒤에서 '/' 나 공백 전까지 가장 긴 `…@`(비밀번호에 @ 가 있어도 마지막 @ 까지). JSON 에서 `/` 를 `\/` 로 쓴 주소(`https:\/\/사용자:비밀@…`)도
_USERINFO = re.compile(r"(?<=//)[^/\s]*@")
_USERINFO_ESCAPED = re.compile(r"(?<=\\/\\/)[^\\/\s]*@")
# 비밀 이름 조각 — 질의(`_QUERY_SECRET`)·대입(`_ASSIGNMENT`)과 아래의 추가 규칙(XML·옵션·눈속임)이 같은 목록을 쓴다(PCSEC1 H1: serviceKey·authKey·appKey·secretKey·clientSecret·X-Api-Key·Ocp-Apim-Subscription-Key 계열).
# `…key` 이름은 앞 낱말(api·service·auth …)이 붙은 것만 본다 — `monkey`·`keyword` 같은 평범한 낱말은 이름이 아니다. `pwd` 는 대입 이름이 아니다(`PWD=C:/…` 는 작업 폴더 환경 변수).
_KEY_PREFIXES = "api|service|auth|app|crtfc|access|private|subscription|consumer|license|signing|encryption|master|secret|client"
# 앞 낱말과 `key` 사이는 없어도·`_`·`-`·`.`·한 칸 공백 어느 것이든 이름이다(`API key: x`·`secret key = x`·`api.key=x` — 자연어 문장에서 흔한 모양, PCSEC1 D4).
_NAME_WORDS = "password|passwd|secret|token|credential|sessionid|session_id|(?:" + _KEY_PREFIXES + ")[ _.-]?key"
_COMPOUND_WORDS = "(?:" + _KEY_PREFIXES + ")[_-]?(?:key|token)|(?:access|refresh|id)[_-]?token|(?:client|api|app)[_-]?secret"
_QUERY_NAMES = ("(?:access|refresh|id)[_-]?token|token|(?:" + _KEY_PREFIXES + ")[_-]?key|x-api-key|x-naver-client-secret|ocp-apim-subscription-key|key|(?:client|api)[_-]?secret|secret|password|passwd|pwd|sig|signature|auth|authorization|bearer|cookies?|"
                 "private_token|x-amz-signature|x-amz-credential|session|sessionid|session_id|jwt")
_QUERY_SECRET = re.compile(r"(?i)([?&;](?:" + _QUERY_NAMES + r")=)(?!\[가림: 주소 인자\])[^&\s#\"']+")
_QUERY_CODE = re.compile(r"(?i)([?&;]code=)(?!\[가림: 주소 인자\])[^&\s#\"']{8,}")           # `?code=200` 같은 짧은 값은 상태 번호라 두고, OAuth 인증 코드처럼 긴 것만
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{16,}")
_BASIC = re.compile(r"(?i)\b(basic\s+)(?-i:(?![A-Za-z0-9+/]*=[A-Za-z0-9+/])(?=[a-z0-9+/]*[A-Z0-9+/=])[A-Za-z0-9+/=]{16,})")        # 대문자·숫자·`+/=` 가 하나도 없으면(`Basic internationalization`) 글이다
_SPACED_VALUE = re.compile(r"(?i)\b((?:" + _NAME_WORDS + r")s?[ \t]+)(?=[A-Za-z0-9._~+/=-]*[0-9])(?=[A-Za-z0-9._~+/=-]*[A-Za-z])[A-Za-z0-9._~+/=-]{16,}")        # 이름 바로 뒤에 구분자 없이 값만 오는 글(`auth token Zq8…`·`Your API key Zq8… is not valid`) — 자연어에서 이름 다음 낱말은 값이 아닌 경우가 대부분이라 값이 '모양을 갖춘 것'(16자 이상·숫자와 글자가 모두 있음)일 때만 가린다(PCSEC1V D4)
_JWT = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")       # 시작을 덩어리 맨 앞으로 한정 — 같은 글자들이 길게 이어져도 제곱으로 느려지지 않는다
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)")        # 머리글 줄만이 아니라 본문까지(끝이 없으면 글 끝까지). PGP 는 `… PRIVATE KEY BLOCK-----`
_SLACK_HOOK = re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+")
_NPM_TOKEN = re.compile(r"\bnpm_[A-Za-z0-9]{30,}")
_AWS_SECRET = re.compile(r"(?i)(aws_secret_access_key\s*[=:]\s*[\"']?)[A-Za-z0-9/+=]{20,}")
# 정본의 `sk-` 패턴(`\bsk-[A-Za-z0-9]{32,}\b`)은 영숫자만 받아서, 붙임표·밑줄이 든 새 키 모양을 못 알아본다: OpenAI 프로젝트 키(`sk-proj-…`)·Anthropic 키(`sk-ant-api03-…`)·OpenRouter 키(`sk-or-v1-…`).
# 앞 셋은 접두사가 종류를 정하므로 낱말(`sk-project`·`sk-ant-colony`)과 섞이지 않고, 꼬리는 영숫자·`-`·`_` 20자 이상이다(실제 키는 64~160자). 앞 글자는 ASCII 영숫자가 아니면 된다(한글 바로 옆·밑줄 뒤의 키도 가린다 — 정본의 ASCII 경계 판과 같다).
# 넷째는 그 밖의 `sk-` 긴 모양(`sk-svcacct-…`·`sk-admin-…`) — 꼬리가 40자 이상이고 앞 60자 안에 대문자와 숫자가 모두 있을 때만이다(소문자 낱말을 붙임표로 이은 주소 조각 `sk-hynix-…` 는 대문자가 없어 글이다).
# 앞내다보기는 60자로 막아 두었다(입력 길이에 선형 — `sk-aa-sk-aa-…` 같은 입력에서도 제곱으로 느려지지 않는다).
_NEW_SK_PATTERNS = (
    ("OpenAI 프로젝트 키", re.compile(r"(?<![A-Za-z0-9])sk-proj-[A-Za-z0-9_-]{20,}")),
    ("Anthropic 키", re.compile(r"(?<![A-Za-z0-9])sk-ant-[a-z]{2,8}[0-9]{2}-[A-Za-z0-9_-]{20,}")),
    ("OpenRouter 키", re.compile(r"(?<![A-Za-z0-9])sk-or-v[0-9]{1,2}-[A-Za-z0-9_-]{20,}")),
    ("sk- 형식 API 키(긴 모양)", re.compile(r"(?<![A-Za-z0-9])sk-(?=[A-Za-z0-9_-]{0,60}[A-Z])(?=[A-Za-z0-9_-]{0,60}[0-9])[A-Za-z0-9_-]{40,}")),
)
# `password: 값`·`token=값`, 환경 변수식 `DB_PASSWORD=값`·`MY_SERVICE_TOKEN=값`·쿠키 `csrftoken=값`, JSON `"password": "값"`·짧은 따옴표 값 `secret = "x"`. 이름은 그 자리에서 바로 찾는다(앞 덩어리를 끝까지 먹고 되돌아가지 않는다 — 제곱으로 느려지지 않게)
_ASSIGNMENT = re.compile(
    r"(?i)((?:" + _NAME_WORDS + r")s?[\"']?\s*[:=]\s*)"
    r"(?![\"']?\[가림)(\"[^\"\n]+\"|'[^'\n]+'|[^\s\"',;&]{4,})")


_WORD_B = chr(92) + "b"                                         # 정규식의 단어 경계
_NOT_AFTER = "(?<![A-Za-z0-9])"                                  # 바로 앞이 ASCII 영숫자가 아니다(밑줄은 괜찮다 — 정본의 `AQ.` 패턴과 같다: `KEY_AKIA…` 도 가린다)
_NOT_BEFORE = "(?![A-Za-z0-9])"                                  # 바로 뒤가 ASCII 영숫자가 아니다


def _ascii_bounded(pattern):
    """단어 경계 기호(단어 경계)가 든 패턴을 ASCII 기준 앞뒤 확인으로 바꾼 같은 패턴 — 단어 경계 기호 는 한글 같은 유니코드 글자도 단어로 봐서 `키는AKIA…를` 처럼 한글에 붙은 키를 못 알아본다.
    패턴 맨 앞(또는 `(`·`|`·`(?i)` 바로 뒤)의 단어 경계 기호 는 '바로 앞이 ASCII 영숫자·밑줄이 아니다', 그 밖의 단어 경계 기호 는 '바로 뒤가 아니다'. 단어 경계 기호 가 없으면 None."""
    source = pattern.pattern
    if _WORD_B not in source:
        return None
    pieces, last = [], 0
    while True:
        found = source.find(_WORD_B, last)
        if found < 0:
            break
        before = source[:found]
        flags = before.rfind("(?")
        starts = before == "" or before.endswith(("(", "|")) or (before.endswith(")") and flags >= 0 and before[flags:].strip("(?)").isalpha())
        pieces.append(source[last:found] + (_NOT_AFTER if starts else _NOT_BEFORE))
        last = found + len(_WORD_B)
    pieces.append(source[last:])
    return re.compile("".join(pieces), pattern.flags)


# 이 모듈 안의 단어 경계 기호 패턴도 같은 경계로(정본이 아니라 여기서 만든 것들)
_BEARER, _BASIC, _SPACED_VALUE, _NPM_TOKEN = (_ascii_bounded(item) or item for item in (_BEARER, _BASIC, _SPACED_VALUE, _NPM_TOKEN))
# 정본 패턴 중 단어 경계 기호 가 든 것(GitHub 토큰·Slack 토큰·AWS 액세스 키·sk- 키·Google 토큰 …)의 ASCII 경계 판 — 정본(vendor/)은 그대로 두고 여기서 더 돌린다
_BOUNDED_PATTERNS = tuple((label, bounded) for label, pattern in SECRET_PATTERNS for bounded in (_ascii_bounded(pattern),) if bounded is not None)
_SHAPE_PATTERNS = (_PEM, _JWT, _SLACK_HOOK, _NPM_TOKEN, _BEARER, *(pattern for _label, pattern in SECRET_PATTERNS), *(pattern for _label, pattern in _BOUNDED_PATTERNS), *(pattern for _label, pattern in _NEW_SK_PATTERNS))


_CUT_WINDOW = 400                  # 상한에서 이만큼 안쪽까지 공백을 찾아 거기서 자른다


def _cut_point(text):
    """상한에서 자를 자리 — 비밀이 반쪽으로 잘려 앞부분이 그대로 남지 않게(비밀에는 공백이 없다) 상한 가까이의 마지막 공백·줄바꿈에서 자른다. 없으면 상한 그대로."""
    window = text[MAX_MASK_INPUT - _CUT_WINDOW:MAX_MASK_INPUT]
    best = max(window.rfind(" "), window.rfind("\n"), window.rfind("\t"))
    return MAX_MASK_INPUT - _CUT_WINDOW + best if best >= 0 else MAX_MASK_INPUT


def mask(value):
    """value 안의 비밀 모양을 가린 글(문자열이 아니면 str() 로 바꾼 뒤). None 은 빈 글."""
    if value is None:
        return ""
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:                                # 문자열로 바꿀 수 없는 객체 — 오류를 안내하다 또 오류가 나지 않게
        return "(표시할 수 없는 값)"
    if len(text) > MAX_MASK_INPUT:
        text = text[:_cut_point(text)] + "…(이하 생략)"
    for _ in range(3):                                # 붙어 있는 비밀은 한 번에 다 못 가릴 수 있어 달라지지 않을 때까지(다시 가려도 같게)
        masked = _mask_once(text)
        if masked == text:
            break
        text = masked
    return text


def has_key_shape(value):
    """글에 키·토큰 모양(정본 패턴과 그 ASCII 경계 판·이 모듈의 JWT·Bearer·npm·Slack 웹훅·개인 키 블록)이 들어 있는가. `이름=값` 꼴(주소 인자·대입)은 보지 않는다 — 어떤 입력에도 예외를 내지 않는다."""
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        return False
    text = _strip_invisible(text[:MAX_MASK_INPUT])
    return any(pattern.search(text) for pattern in _SHAPE_PATTERNS)


def _strip_invisible(text):
    """눈에 안 보이는 글자(폭 없는 글자·방향 제어·태그·변형 선택자·채움 글자 …)를 지운다 — 비밀을 이 글자로 쪼개 패턴을 피하는 것을 막는다. 줄바꿈·탭은 둔다."""
    text = _INVISIBLE.sub("", text)
    if text.replace("\n", "").replace("\r", "").replace("\t", "").isprintable():                                  # 보이는 글자(와 줄바꿈·탭)뿐이면 지울 것이 없다 — 글자마다 범주를 묻는 길은 20만 자에서 약 45ms
        return text
    return "".join(ch for ch in text if ch in "\n\r\t" or unicodedata.category(ch) not in _HIDDEN)


# ---- 눈속임을 푼 '보기(view)' 위에서 도는 추가 규칙(PCSEC1 H1) -------------------------------------------------------------------------------------
# 위의 규칙들은 원문 위에서 돈다. 아래는 그 규칙이 놓치던 것을 잡는다: ① 이름·구분 글자를 전각·키릴/그리스 동형 문자·퍼센트로 바꿔 쓴 눈속임 ② 이스케이프된 JSON 속 값
# ③ `Authorization`·`Proxy-Authorization`·`Cookie`·`Set-Cookie` 줄(스킴 불문·쿠키는 이름 불문 모든 값) ④ XML 태그·`--옵션 값`·본문 속 `Key=값` ⑤ base64 로 감싼 값
# ⑥ 한 칸·줄바꿈으로 쪼갠 값. 새 규칙은 항상 위 규칙 **뒤에** 돌고, `[가림` 표지가 이미 있는 값은 정규식 안에서 건너뛴다(두 번째 패스에서 같은 글이 다시 바뀌지 않는다).
# 이름 목록은 위 `_QUERY_SECRET`·`_ASSIGNMENT` 와 같은 조각(`_NAME_WORDS`)을 쓴다. 모든 정규식은 입력 길이에 선형이다(일치마다 값을 따로 찾는 곳은 4096자·1000자·300자 상한).
_HOMOGLYPH_SPEC = (
    "430:a 410:A 441:c 421:C 435:e 415:E 43e:o 41e:O 440:p 420:P 445:x 425:X 443:y 423:Y 456:i 406:I 458:j 408:J 455:s 405:S 501:d 51b:q 51d:w 4bb:h 43a:k 41a:K 43c:m 41c:M "
    "442:t 422:T 412:B 41d:H 4cf:l 3b1:a 391:A 392:B 395:E 396:Z 397:H 399:I 39a:K 39c:M 39d:N 39f:O 3a1:P 3a4:T 3a5:Y 3a7:X 3b9:i 3ba:k 3bd:v 3bf:o 3c1:p 3c4:t 3c5:u 3c7:x "
    "130:I 131:i 261:g 578:n 57d:u 585:o 581:g 2010:- 2011:- 2012:- 2013:- 2014:- 2015:- 2212:- fe63:- 2018:' 2019:' 201a:' 201c:\" 201d:\" 201e:\""
)                                                                                                    # 키릴·그리스·아르메니아 문자 중 영문 이름 글자처럼 보이는 것(코드:영문) + 붙임표처럼 보이는 줄표·둥근 따옴표 — NFKC 가 못 접는 것들
_FOLD_RANGES = ((0xA0, 0xBA), (0x2000, 0x200A), (0x202F, 0x202F), (0x205F, 0x2071), (0x2074, 0x209F), (0x2100, 0x218F), (0x2460, 0x24FF), (0x2C7C, 0x2C7D), (0x3000, 0x3000), (0xA69C, 0xA69D),
                (0xA770, 0xA7FF), (0x1D2C, 0x1DBF), (0xFE30, 0xFE6B), (0xFF01, 0xFF5E), (0x1D400, 0x1D7FF), (0x1F100, 0x1F1FF))       # NFKC 가 한 글자를 영문·숫자·기호 한 글자로 바꾸는 구역(전각·원문자·수학 글자·위아래 첨자·공백 종류)
_FOLD_TABLE = None


def _fold_table():
    """눈속임 글자 → 영문 한 글자(1:1) 표 — 처음 비ASCII 글을 볼 때 한 번만 만든다(약 3천 번의 NFKC)."""
    global _FOLD_TABLE
    table = _FOLD_TABLE
    if table is None:
        table = {}
        for low, high in _FOLD_RANGES:
            for code in range(low, high + 1):
                try:
                    folded = unicodedata.normalize("NFKC", chr(code))
                except ValueError:
                    continue
                if len(folded) == 1 and folded != chr(code):
                    table[code] = folded
        for item in _HOMOGLYPH_SPEC.split():
            code, _colon, letter = item.partition(":")
            table[int(code, 16)] = letter
        _FOLD_TABLE = table
    return table


_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")


def _decode_percent(view):
    """`%5F` 같은 퍼센트 글자를 풀어 쓴 글과 위치 대응표(보기 위치 → 원문 위치) — 풀린 것이 없으면 (view, None). 풀 수 있는 것은 줄 구분·탭과 보이는 ASCII 뿐이다."""
    pieces, view_pos, orig_pos = [], [], []
    last = shown = 0
    found = False
    for match in _PERCENT.finditer(view):
        code = int(match.group(1), 16)
        if not (code in (9, 10, 13) or 32 <= code < 127):
            continue
        found = True
        start = match.start()
        if start > last:
            view_pos.append(shown)
            orig_pos.append(last)
            pieces.append(view[last:start])
            shown += start - last
        view_pos.append(shown)
        orig_pos.append(start)
        pieces.append(chr(code))
        shown += 1
        last = match.end()
    if not found:
        return view, None
    if last < len(view):
        view_pos.append(shown)
        orig_pos.append(last)
        pieces.append(view[last:])
        shown += len(view) - last
    return "".join(pieces), (view_pos, orig_pos, len(view), shown)


def _view_of(text):
    """탐지용 글(view)과 위치 대응표 — 눈속임 글자(전각·동형 문자·공백 종류)를 영문 한 글자로 접고(1:1) `%XX` 를 푼다. 바뀐 것이 없으면 (text, None)."""
    view = text
    if not text.isascii():
        folded = text.translate(_fold_table())                                                           # 정규식으로 먼저 찾는 것보다 빠르다(20만 자 한글에서 약 25ms — 3천 글자 집합 검색은 약 200ms)
        if folded != text:
            view = folded
    if "%" in view:
        return _decode_percent(view)
    return view, None


def _origin(anchors, index):
    """보기 위치 → 원문 위치(그 글자가 시작한 곳). 보기 끝이면 원문 끝."""
    if anchors is None:
        return index
    view_pos, orig_pos, orig_len, view_len = anchors
    if index >= view_len:
        return orig_len
    found = bisect.bisect_right(view_pos, index) - 1
    next_view = view_pos[found + 1] if found + 1 < len(view_pos) else view_len
    next_orig = orig_pos[found + 1] if found + 1 < len(orig_pos) else orig_len
    if next_view - view_pos[found] == next_orig - orig_pos[found]:
        return orig_pos[found] + (index - view_pos[found])                                              # 바뀌지 않은 구간
    return orig_pos[found]                                                                                # 풀린 글자 하나(원문 세 글자)


def _apply_spans(text, anchors, spans):
    """보기 위의 (시작, 끝, 바꿀 글) 구간들을 원문 위치로 되돌려 text 를 바꾼다. 겹치는 구간은 먼저 시작한(같으면 더 긴) 것만 쓴다."""
    if not spans:
        return text
    spans.sort(key=lambda item: (item[0], -item[1]))
    out, last = [], 0
    for start, end, replacement in spans:
        begin = _origin(anchors, start)
        stop = _origin(anchors, end)
        if begin < last or stop < begin:
            continue
        out.append(text[last:begin])
        out.append(replacement)
        last = stop
    out.append(text[last:])
    return "".join(out)


_MARKED = r"\[가림"                                                                                          # 이미 가린 값(표지의 머리) — 앞내다보기로 건너뛴다
_SCHEME_MARKED = r"(?:\\*[\"'])?(?:[A-Za-z][A-Za-z0-9._-]{1,31}[ \t]+)?" + _MARKED                                         # `Bearer [가림: 토큰]`·`"Bearer [가림: 토큰]"` 처럼 따옴표·스킴 낱말 뒤에 표지가 온 값도 가린 것이다
_HEADER = re.compile(
    r"(?i)(?<![A-Za-z0-9_?&;-])(?:(?<=\")(?P<dq>))?(?:(?<=')(?P<sq>))?(?P<name>proxy-authorization|authorization|set-cookie|cookies?)(?P<gap>\\*[\"']?[ \t]*[:=][ \t]*)(?![ \t])"
    r"(?:(?P<oq>\\*[\"'])(?!" + _SCHEME_MARKED + r")(?P<qv>[^\"'\\\r\n]{1,4096})(?P<cq>\\*[\"'])"
    r"|(?!" + _SCHEME_MARKED + r")(?P<uv>(?(dq)[^\r\n\"]*|(?(sq)[^\r\n']*|[^\r\n]*(?:\r?\n[ \t]+[A-Za-z0-9._~+/=;,%-][A-Za-z0-9._~+/=;,% \t-]*(?=\r?\n|\Z))*))))")                               # 값: 따옴표로 묶음 | 줄 끝까지(셸 인자의 따옴표 안이면 그 따옴표까지, 접힌 줄 포함)
_COOKIE_OPTION = re.compile(r"(?<![A-Za-z0-9_-])(?:--cookie|-b)(?:[ \t]+|=)(?:(?P<oq>[\"'])(?!" + _MARKED + r")(?P<qv>[^\"'\r\n]{1,4096})(?P=oq)|(?!" + _MARKED + r")(?P<uv>[^\s\"']{1,4096}))")
_SCHEMES = frozenset({"bearer", "basic", "token", "apikey", "api-key", "digest", "oauth", "aws4-hmac-sha256", "googlelogin", "negotiate", "ntlm", "hawk", "mac", "jwt", "bot", "splunk"})
_SCHEME_SPLIT = re.compile(r"([A-Za-z][A-Za-z0-9._-]{1,31}) (\S.*)", re.S)
_COOKIE_ATTRS = frozenset({"path", "domain", "expires", "max-age", "samesite", "secure", "httponly", "partitioned", "priority", "version", "comment"})
_PAIR_SPLIT = re.compile(r"(;[ \t]*)")
_CONTAINER_VALUE = re.compile(r"(?P<key>[:=][ \t]*)(?P<quote>[\"'])(?!" + _MARKED + r")[^\"'\r\n]{1,300}(?P=quote)")
_ASSIGN_VIEW = re.compile(
    r"(?i)(?:" + _NAME_WORDS + r")s?(?:\\*[\"'])?[ \t]*[:=][ \t]*"
    r"(?:(?P<eq>\\+[\"'])(?!" + _MARKED + r")(?P<ev>(?:(?!\\+[\"']).){1,300}?)(?=\\+[\"'])"                       # \"값\"  (이스케이프된 JSON)
    r"|(?P<mq>[\"']{2,})(?!" + _MARKED + r")(?P<mv>[^\"'\s\\]+)"                                                  # ""값""  (따옴표 두 겹 이상)
    r"|(?!" + _MARKED + r")(?P<uv>(?:[^\s\"',;&<>\\]|\\(?![\"'])){4,}))")                                          # 값  (따옴표 없음 — 4자 이상, 위 `_ASSIGNMENT` 와 같다)
_ASSIGN_TAB = re.compile(r"(?i)(?:" + _COMPOUND_WORDS + r")s?\t+(?!" + _MARKED + r")(?P<uv>[^\s\"',;&<>\\]{4,})")                  # `api_key<탭>값`
_XML_VALUE = re.compile(r"(?i)<(?P<tag>[A-Za-z0-9_.:-]*(?:" + _NAME_WORDS + r")s?)(?:[ \t][^<>]{0,200})?>(?!" + _MARKED + r")(?P<v>[^<>\s][^<>]{0,1000}?)</(?P=tag)>")
_OPTION_VALUE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])--(?:[a-z0-9]+-)*(?:(?:" + _KEY_PREFIXES + r")-?key|(?:access|refresh|id)-?token|token|(?:client|api)-?secret|secret|password|passwd)(?![A-Za-z0-9_-])"
    r"[ \t]+(?!" + _MARKED + r")(?P<v>\"[^\"\r\n]{1,300}\"|'[^'\r\n]{1,300}'|[^\s\"'-][^\s\"']{0,300})")                                         # `--api-key 값`(공백 구분)
_QUERY_VIEW = re.compile(r"(?i)([?&;](?:" + _QUERY_NAMES + r")=)(?!" + _MARKED + r")[^&\s#\"']+")                                                                    # 보기 위의 주소 인자 — 위 `_QUERY_SECRET` 과 같은 이름·값이고, 앞의 다른 규칙이 남긴 표지(`[가림: 값]`)는 어느 것이든 건너뛴다
_BARE_KEY = re.compile(r"(?i)(?<![A-Za-z0-9_.-])key=(?!" + _MARKED + r")(?P<v>[^\s\"',;&<>]{8,})")                                                                    # 본문 속 `Key=값`
_B64_RUN = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{24,}={0,2}(?![A-Za-z0-9+/_=-])")
_PRINTABLE = re.compile(rb"[\t\n\r\x20-\x7e]+")
_CONTINUATION = re.compile(r"(\[가림: (?:값|토큰|쿠키|주소 인자)\])(?:[ \t]|\r?\n)(?=[A-Za-z0-9._~+/=-]*[0-9])[A-Za-z0-9._~+/=-]{12,}(?![A-Za-z0-9._~+/=-])")        # 가림 표지 바로 뒤에 이어진 값 조각
MAX_ENCODED_DECODES = 64                                                                                  # base64 로 풀어 보는 덩어리의 상한(글 한 번에)
MAX_ENCODED_RUN = 8192                                                                                    # 풀어 볼 덩어리 하나의 최대 길이(4의 배수 — 더 긴 덩어리는 앞부분만)


def _authorization_value(value):
    """`Authorization` 줄의 값을 가린 글(바꿀 것이 없으면 None) — 알려진 스킴 낱말(Bearer·Basic·Token …)은 남기고 뒤를 가린다. 스킴이 없거나 모르는 스킴이면 값 전체."""
    collapsed = " ".join(value.split())
    if not collapsed or collapsed.startswith("[가림"):
        return None
    found = _SCHEME_SPLIT.fullmatch(collapsed)
    if found is not None and found.group(1).lower() in _SCHEMES:
        return None if found.group(2).startswith("[가림") else found.group(1) + " [가림: 토큰]"
    if collapsed.lower() in _SCHEMES:
        return None                                                                                      # 스킴 낱말만 있다 — 가릴 값이 없다
    return "[가림: 토큰]"


def _cookie_value(value, set_cookie):
    """`Cookie`·`Set-Cookie` 줄의 값을 가린 글(바꿀 것이 없으면 None) — 쿠키 이름은 남기고 **모든 쿠키 값**을 가린다(Set-Cookie 는 첫 쌍과 모르는 속성의 값). `{…}` 같은 묶음이면 그 안의 따옴표 값."""
    probe = value.lstrip()
    if probe[:1] in ("{", "[", "(") or probe[:5].lower() == "dict(":
        masked = _CONTAINER_VALUE.sub(r"\g<key>\g<quote>[가림: 쿠키]\g<quote>", value)
        return masked if masked != value else None
    parts = _PAIR_SPLIT.split(value)
    changed = False
    for index in range(0, len(parts), 2):
        piece = parts[index]
        body = piece.strip()
        if not body or body.startswith("[가림"):
            continue
        name, equal, rest = body.partition("=")
        lead = piece[:len(piece) - len(piece.lstrip())]
        if equal:
            rest = rest.strip()
            if not rest or rest.startswith("[가림"):
                continue
            if set_cookie and index and name.strip().lower() in _COOKIE_ATTRS:
                continue                                                                                 # Path=/ 같은 속성
            parts[index] = f"{lead}{name.strip()}=[가림: 쿠키]"
        elif set_cookie:
            continue                                                                                     # HttpOnly·Secure 같은 값 없는 속성
        else:
            parts[index] = f"{lead}[가림: 쿠키]"
        changed = True
    return "".join(parts) if changed else None


def _header_spans(view, spans):
    pos = 0
    search = _HEADER.search
    while True:
        found = search(view, pos)
        if found is None:
            return
        pos = max(found.end(), found.start() + 1)
        group = "qv" if found.group("qv") is not None else "uv"
        value = found.group(group)
        if not value or not value.strip():
            continue
        name = found.group("name").lower()
        replacement = _authorization_value(value) if name.endswith("authorization") else _cookie_value(value, name == "set-cookie")
        if replacement is not None and replacement != value:
            start, end = found.span(group)
            spans.append((start, end, replacement))


def _cookie_option_spans(view, spans):
    pos = 0
    while True:
        found = _COOKIE_OPTION.search(view, pos)
        if found is None:
            return
        pos = max(found.end(), found.start() + 1)
        group = "qv" if found.group("qv") is not None else "uv"
        value = found.group(group)
        if "=" in value:                                                                                 # `-b feature`(git 브랜치 만들기) 같은 것은 쿠키가 아니다
            replacement = _cookie_value(value, False)
            if replacement is not None and replacement != value:
                start, end = found.span(group)
                spans.append((start, end, replacement))


def _assignment_spans(view, spans):
    pos = 0
    while True:
        found = _ASSIGN_VIEW.search(view, pos)
        if found is None:
            return
        pos = max(found.end(), found.start() + 1)
        for group in ("ev", "mv", "uv"):
            if found.group(group) is not None:
                start, end = found.span(group)
                spans.append((start, end, "[가림: 값]"))
                break


def _tab_spans(view, spans):
    for found in _ASSIGN_TAB.finditer(view):
        start, end = found.span("uv")
        spans.append((start, end, "[가림: 값]"))


def _xml_spans(view, spans):
    for found in _XML_VALUE.finditer(view):
        start, end = found.span("v")
        spans.append((start, end, "[가림: 값]"))


def _option_spans(view, spans):
    for found in _OPTION_VALUE.finditer(view):
        start, end = found.span("v")
        spans.append((start, end, "[가림: 값]"))


def _bare_key_spans(view, spans):
    for found in _BARE_KEY.finditer(view):
        value = found.group("v")
        if len(value) >= 20 or any(ch.isdigit() for ch in value) or (any(ch.islower() for ch in value) and any(ch.isupper() for ch in value)):        # `key=value` 같은 평범한 글은 두고 키처럼 생긴 것만
            start, end = found.span("v")
            spans.append((start, end, "[가림: 값]"))


def _decoded_text(run):
    """base64(표준·urlsafe)로 읽히고 풀면 보이는 ASCII 글이면 그 글, 아니면 None(해시·이진 자료는 건너뛴다)."""
    body = run.rstrip("=")
    if len(body) % 4 == 1:
        return None
    padded = body + "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded) if ("-" in body or "_" in body) else base64.b64decode(padded)
    except ValueError:
        return None
    if len(raw) < 12 or _PRINTABLE.fullmatch(raw) is None:
        return None
    return raw.decode("ascii")


def _hide_encoded(text, depth):
    """base64 로 감싼 비밀 — 풀어서 가릴 것이 나오는 덩어리는 통째로 가린다(깊이 1 — 풀린 글 속 base64 는 다시 풀지 않는다). 아주 긴 덩어리는 앞 `MAX_ENCODED_RUN` 자만 풀어 본다.
    글로 읽히는 덩어리(풀면 보이는 ASCII)가 `MAX_ENCODED_DECODES` 개를 넘으면 그 뒤의 것은 풀어 보지 않고 가린다(실패하면 가리는 쪽) — 이진 자료(해시·그림)는 글로 읽히지 않아 어느 쪽이든 그대로다."""
    if depth:
        return text
    budget = MAX_ENCODED_DECODES
    out, last = [], 0
    for found in _B64_RUN.finditer(text):
        run = found.group()
        decoded = _decoded_text(run[:MAX_ENCODED_RUN] if len(run) > MAX_ENCODED_RUN else run)
        if decoded is None:
            continue
        if budget > 0:
            budget -= 1
            hidden = _mask_once(decoded, 1) != decoded
        else:
            hidden = True
        if hidden:
            out.append(text[last:found.start()])
            out.append("[가림: 인코딩된 비밀]")
            last = found.end()
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


_ODD_QUOTES = re.compile(r"\\[\"']|[\"'][\"']")                                                            # 이스케이프된 따옴표(`\"`)·따옴표 두 겹 — 위 `_ASSIGNMENT` 가 못 보는 따옴표 모양
_NAME_LITERALS = ("password", "passwd", "secret", "token", "credential", "sessionid", "session_id", "key")      # `_NAME_WORDS` 의 어느 이름이든 이 낱말 중 하나를 품는다(소문자판에서)
_SPACED_NEEDS = tuple(word + gap for word in _NAME_LITERALS for gap in (" ", "\t", "s ", "s\t"))        # `_SPACED_VALUE` 는 이름 낱말 바로 뒤에 공백이 있을 때만 뜻이 있다 — `?token=a&` 같은 글에서는 정규식을 돌리지 않는다(PCSEC1V D10)
_XML_NEEDLE, _OPTION_NEEDLE, _BARE_NEEDLE = "<", "--", "key="


def _hidden_forms(text, depth=0):
    """위 규칙 뒤에 도는 추가 규칙들(이 블록 첫머리 설명). 어떤 입력에도 예외를 내지 않는다. 각 규칙은 그 규칙이 쓰는 낱말이 글에 있을 때만 돈다(`_USE_PREFILTERS` 를 끄면 모두 늘 돈다 — 시험이 둘이 같은지 견준다)."""
    if len(text) < 8:
        return text
    view, anchors = _view_of(text)
    low = _lowered(view)
    pre = _USE_PREFILTERS
    spans = []
    if not pre or "authorization" in low or "cookie" in low:
        _header_spans(view, spans)
    if not pre or "-b" in low or "cookie" in low:
        _cookie_option_spans(view, spans)
    if not pre or ((":" in low or "=" in low) and any(word in low for word in _NAME_LITERALS)):
        if not pre or view is not text or _ODD_QUOTES.search(low) is not None:                              # 보기가 원문과 같고 따옴표가 평범하면 위 `_ASSIGNMENT` 가 이미 한 일이다
            _assignment_spans(view, spans)
    if not pre or ("\t" in low and any(word in low for word in ("key", "token", "secret"))):
        _tab_spans(view, spans)
    if not pre or _XML_NEEDLE in low:
        _xml_spans(view, spans)
    if not pre or _OPTION_NEEDLE in low:
        _option_spans(view, spans)
    if not pre or _BARE_NEEDLE in low:
        _bare_key_spans(view, spans)
    if view is not text and (not pre or "=" in low):                                                         # 눈속임을 푼 뒤에야 보이는 주소 인자(`service%4Bey=…`·전각·동형 문자 이름)
        for found in _QUERY_VIEW.finditer(view):
            spans.append((found.end(1), found.end(), "[가림: 주소 인자]"))
    text = _apply_spans(text, anchors, spans)
    text = _hide_encoded(text, depth)
    if "[가림: " in text:
        text = _CONTINUATION.sub(r"\1", text)
    return text


# ---- 원문 규칙의 사전 확인 ---------------------------------------------------------------------------------------------------
# 규칙마다 '이 규칙이 일치하려면 글에 반드시 있어야 하는 낱말·글자'를 적어 두고, 없으면 그 규칙의 검색을 건너뛴다(같은 결과 — 검색할 것이 없으니 바뀔 것도 없다). 20만 자 평범한 글에서 규칙 서른아홉 번의 훑기가 사라진다.
# 필요 조건은 (글에 이 낱말 중 하나, 소문자판에 이 낱말 중 하나, 글에 이 글자가 모두)이고 느슨해도 된다(꼭 필요한 것만). 모르는 규칙(정본에 새 패턴이 생겼을 때)은 조건이 없어 늘 돈다.
# 소문자판은 정규식의 대소문자 무시(`(?i)`)와 같은 눈으로 읽는다: 그것이 영문 글자와 같다고 보는 비ASCII 글자는 `İ`·`ı`(i), `ſ`(s), 켈빈 기호(k) 뿐이다(시험이 파이썬 판마다 확인한다).
_USE_PREFILTERS = True
_LOWER_FIX = {0x130: "i", 0x131: "i", 0x17F: "s", 0x212A: "k"}
_NO_NEED = ((), (), ())
_VENDOR_NEEDS = {
    "Google API 키": (("AIza",), (), ()), "Google API 키(새 형식)": (("AQ.",), (), ()), "Google OAuth 클라이언트 시크릿": (("GOCSPX-",), (), ()), "Google refresh token": (("1//0",), (), ()),
    "Google access token": (("ya29.",), (), ()), "GitHub 토큰": (("ghp_", "gho_", "ghu_", "ghs_", "ghr_"), (), ()), "GitHub PAT": (("github_pat_",), (), ()), "개인 키 블록": (("-----BEGIN",), (), ()),
    "Slack 토큰": (("xoxb-", "xoxa-", "xoxp-", "xoxr-", "xoxs-"), (), ()), "AWS 액세스 키": (("AKIA",), (), ()), "Telegram 봇 토큰": ((":",), (), ()), "sk- 형식 API 키": (("sk-",), (), ()),
    "client_secret JSON 값": ((chr(34) + "client_secret" + chr(34),), (), ()), "키/토큰 할당": (("'", '"'), ("key", "secret", "token", "passwd", "password"), ()),
}


_LOWER_FIX_CHARS = tuple(chr(code) for code in _LOWER_FIX)


def _lowered(text):
    if text.isascii() or not any(char in text for char in _LOWER_FIX_CHARS):
        return text.lower()                          # `translate` 는 긴 글이 ASCII 가 아니면(가림 표지의 한글 때문에 흔하다) 느리다 — 바꿀 글자(넷)가 없으면 건너뛴다(결과는 같다, PCSEC1V D10)
    return text.translate(_LOWER_FIX).lower()


def _applies(text, low, need):
    any_text, any_low, all_text = need
    if any_text and not any(piece in text for piece in any_text):
        return False
    if any_low and not any(piece in low for piece in any_low):
        return False
    return all(piece in text for piece in all_text)


_CHAIN = (
    (_PEM, "[가림: 개인 키 블록]", (("-----BEGIN",), (), ())),
    (_USERINFO, "***@", ((), (), ("//", "@"))),
    (_USERINFO_ESCAPED, "***@", ((), (), (chr(92) + "/", "@"))),
    (_QUERY_SECRET, r"\1[가림: 주소 인자]", (("?", "&", ";"), (), ("=",))),
    (_QUERY_CODE, r"\1[가림: 주소 인자]", ((), ("code=",), ())),
    (_BEARER, r"\1[가림: 토큰]", ((), ("bearer",), ())),
    (_BASIC, r"\1[가림: 토큰]", ((), ("basic",), ())),
    (_JWT, "[가림: JWT]", (("eyJ",), (), ())),
    (_SLACK_HOOK, "[가림: Slack 웹훅]", (("hooks.slack.com/services/",), (), ())),
    (_NPM_TOKEN, "[가림: npm 토큰]", (("npm_",), (), ())),
    (_AWS_SECRET, r"\1[가림: AWS 비밀 키]", ((), ("aws_secret_access_key",), ())),
    *((pattern, f"[가림: {label}]", _VENDOR_NEEDS.get(label, _NO_NEED)) for label, pattern in SECRET_PATTERNS),                       # 이름이 있는 정본 패턴이 먼저(어떤 종류인지 남긴다) — 아래의 일반 대입 규칙은 그 나머지를 가린다
    *((pattern, f"[가림: {label}]", _VENDOR_NEEDS.get(label, _NO_NEED)) for label, pattern in _BOUNDED_PATTERNS),                    # 한글 바로 옆의 키까지(정본이 먼저 돌았으니 이미 가려지던 글의 출력은 그대로다)
    *((pattern, f"[가림: {label}]", (("sk-",), (), ())) for label, pattern in _NEW_SK_PATTERNS),                                     # 붙임표·밑줄이 든 새 `sk-` 키 모양(정본이 못 알아보던 것)
    (_ASSIGNMENT, r"\1[가림: 값]", ((":", "="), _NAME_LITERALS, ())),
    (_SPACED_VALUE, r"\1[가림: 토큰]", ((), _SPACED_NEEDS, ())),                                    # 맨 끝 — `이름 key=값` 처럼 위 대입 규칙이 먼저 가려야 할 글을 이 규칙이 덩어리째 가로채지 않게
)


def _mask_once(text, _depth=0):
    text = _strip_invisible(text)
    low = _lowered(text) if _USE_PREFILTERS else None
    for pattern, replacement, need in _CHAIN:
        if low is not None and not _applies(text, low, need):
            continue
        changed = pattern.sub(replacement, text)
        if changed is not text:                                                                              # 바뀐 것이 없으면 `sub` 는 같은 글 객체를 돌려준다
            text = changed
            low = _lowered(text) if low is not None else None
    return _hidden_forms(text, _depth)


def safe_detail(value, limit=MAX_LOG_CHARS):
    """로그에 쓸 한 줄 글 — 가리고, 줄바꿈·연속 공백을 한 칸으로 줄이고, limit 글자를 넘으면 자르고 '…' 를 붙인다."""
    text = " ".join(mask(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
