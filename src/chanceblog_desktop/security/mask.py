"""로그·오류 보고서에 나가는 글에서 비밀로 보이는 것을 가린다(docs/SECURITY.md §2).

규칙의 정본은 chanceblog 의 `pipeline/secret_patterns.py` 이고(`vendor/` 로 원본 그대로 가져온 것), 여기서는 그 패턴을 그대로 써서 글 속 비밀 모양을
`[가림: <이름>]` 으로 바꾼다. 거기에 이 앱이 다루는 글에서 더 필요한 세 가지를 더한다: 주소 속 `사용자:토큰@`(비밀번호에 `@` 가 들어 있어도),
주소의 `?access_token=…` 같은 인자, `Bearer <토큰>`. 어떤 입력이 와도 예외를 내지 않고(없는 값은 빈 글), 이미 가린 글을 다시 가려도 같다.
"""
from __future__ import annotations

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
_QUERY_SECRET = re.compile(r"(?i)([?&;](?:access_token|refresh_token|id_token|token|api[_-]?key|x-api-key|key|client_secret|secret|password|passwd|pwd|sig|signature|auth|private_token|x-amz-signature|x-amz-credential|session|sessionid|session_id|jwt)=)(?!\[가림: 주소 인자\])[^&\s#\"']+")
_QUERY_CODE = re.compile(r"(?i)([?&;]code=)(?!\[가림: 주소 인자\])[^&\s#\"']{8,}")           # `?code=200` 같은 짧은 값은 상태 번호라 두고, OAuth 인증 코드처럼 긴 것만
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{16,}")
_BASIC = re.compile(r"(?i)\b(basic\s+)(?-i:(?=[a-z0-9+/]*[A-Z0-9+/=])[A-Za-z0-9+/=]{16,})")        # 대문자·숫자·`+/=` 가 하나도 없으면(`Basic internationalization`) 글이다
_JWT = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")       # 시작을 덩어리 맨 앞으로 한정 — 같은 글자들이 길게 이어져도 제곱으로 느려지지 않는다
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)")        # 머리글 줄만이 아니라 본문까지(끝이 없으면 글 끝까지). PGP 는 `… PRIVATE KEY BLOCK-----`
_SLACK_HOOK = re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+")
_NPM_TOKEN = re.compile(r"\bnpm_[A-Za-z0-9]{30,}")
_AWS_SECRET = re.compile(r"(?i)(aws_secret_access_key\s*[=:]\s*[\"']?)[A-Za-z0-9/+=]{20,}")
# `password: 값`·`token=값`, 환경 변수식 `DB_PASSWORD=값`·`MY_SERVICE_TOKEN=값`·쿠키 `csrftoken=값`, JSON `"password": "값"`·짧은 따옴표 값 `secret = "x"`. 시작을 덩어리 맨 앞으로 한정한다(제곱으로 느려지지 않게)
_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|credential|sessionid|session_id)s?[\"']?\s*[:=]\s*)"
    r"(?![\"']?\[가림)(\"[^\"\n]+\"|'[^'\n]+'|[^\s\"',;&]{4,})")


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


def _strip_invisible(text):
    """눈에 안 보이는 글자(폭 없는 글자·방향 제어·태그·변형 선택자·채움 글자 …)를 지운다 — 비밀을 이 글자로 쪼개 패턴을 피하는 것을 막는다. 줄바꿈·탭은 둔다."""
    text = _INVISIBLE.sub("", text)
    return "".join(ch for ch in text if ch in "\n\r\t" or unicodedata.category(ch) not in _HIDDEN)


def _mask_once(text):
    text = _strip_invisible(text)
    text = _PEM.sub("[가림: 개인 키 블록]", text)
    text = _USERINFO.sub("***@", text)
    text = _USERINFO_ESCAPED.sub("***@", text)
    text = _QUERY_SECRET.sub(r"\1[가림: 주소 인자]", text)
    text = _QUERY_CODE.sub(r"\1[가림: 주소 인자]", text)
    text = _BEARER.sub(r"\1[가림: 토큰]", text)
    text = _BASIC.sub(r"\1[가림: 토큰]", text)
    text = _JWT.sub("[가림: JWT]", text)
    text = _SLACK_HOOK.sub("[가림: Slack 웹훅]", text)
    text = _NPM_TOKEN.sub("[가림: npm 토큰]", text)
    text = _AWS_SECRET.sub(r"\1[가림: AWS 비밀 키]", text)
    for label, pattern in SECRET_PATTERNS:                                     # 이름이 있는 정본 패턴이 먼저(어떤 종류인지 남긴다) — 아래의 일반 대입 규칙은 그 나머지를 가린다
        text = pattern.sub(f"[가림: {label}]", text)
    text = _ASSIGNMENT.sub(r"\1[가림: 값]", text)
    return text


def safe_detail(value, limit=MAX_LOG_CHARS):
    """로그에 쓸 한 줄 글 — 가리고, 줄바꿈·연속 공백을 한 칸으로 줄이고, limit 글자를 넘으면 자르고 '…' 를 붙인다."""
    text = " ".join(mask(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
