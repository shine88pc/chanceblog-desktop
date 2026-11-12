"""본문 속 Secret 형태 검사기 — 글에 붙여 넣은 키·토큰 모양을 찾아 '어디에 어떤 유형이 있는지'만 돌려준다(docs/SECURITY.md '본문 속 Secret 형태 검사', 설계 D-420–D-429).

운영자 결정(2026-11-11): 초안을 저장하기 전과 백업하기 전에 Secret 형태 여섯 가지(Google API 키·GitHub 토큰·Bearer 토큰·OAuth 토큰·AWS 액세스 키·PEM 개인 키)를 검사하고,
발견하면 토큰을 다시 보이지 않고 위치와 유형만 알린 뒤 저장·백업을 멈춘다. 앱은 글을 자동으로 지우거나 바꾸지 않고, '무시하고 저장'도 없다 — 이 모듈에는 발견을 끄는 인자도 길도 없다.

지키는 것:
  · 결과(`SecretFinding`)에는 칸 이름·줄·열·유형 이름뿐 글 내용이 없다 — `repr`·`str`·`dataclasses.asdict`·피클·예외 문구·`describe`·`summarize` 어디에도 토큰 글자나 길이 힌트가 나오지 않는다.
  · 표준 라이브러리만 쓴다. 파일·네트워크·하위 프로세스·시계·무작위·전역에 남는 상태가 없다(같은 입력은 늘 같은 출력).
  · 모든 정규식은 선형 시간이다(큰 반복 안에 반복·대안을 두지 않고, 접두어로 시작하는 후보는 앞 글자 검사로 시작 자리를 제한한다). 10만 자 병적 입력도 0.5초 안에 끝난다.
  · 위치는 원문 기준이다. 글자 모양 맞추기(전각·수학 글자 같은 호환 글자 → 영문·숫자 하나)는 글자 하나를 글자 하나로만 바꿔 길이가 그대로이므로 위치가 밀리지 않는다.

위치의 뜻: 줄은 1부터이고 줄바꿈은 CRLF·LF·CR 이다(그 밖의 유니코드 줄 구분자는 보통 글자). 열은 그 줄 안에서 파이썬 글자(코드 포인트) 기준 1부터이고 `col_end` 는 마지막 글자의 열(포함)이다.
그래서 `줄 글[col_start - 1:col_end]` 가 발견한 글이다(결합 글자도 한 글자로 센다).
"""
import bisect
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

__all__ = ("KINDS", "KIND_LABELS", "MAX_WHERE_CHARS", "SecretFinding", "describe", "has_secret", "scan_fields", "scan_secrets", "summarize")

KINDS = ("google_api_key", "github_token", "bearer_token", "oauth_token", "aws_access_key", "pem_private_key")
KIND_LABELS = MappingProxyType({
    "google_api_key": "Google API 키",
    "github_token": "GitHub 토큰",
    "bearer_token": "Bearer 토큰",
    "oauth_token": "OAuth 토큰",
    "aws_access_key": "AWS 액세스 키",
    "pem_private_key": "개인 키(PEM)",
})
MAX_WHERE_CHARS = 80              # 칸 이름의 가장 긴 길이 — 칸 이름은 '본문'·'제목' 같은 짧은 이름이다
MAX_ACTION_CHARS = 20             # `summarize` 의 동작 이름('저장'·'백업')의 가장 긴 길이
MAX_LINES_SHOWN = 5               # `summarize` 가 칸 하나에 줄 번호를 보여 주는 가장 많은 수(넘으면 '외 N줄')

# 여러 유형이 같은 자리에 겹치면 더 구체적인 모양이 이긴다(예: `Bearer` 뒤의 GitHub 토큰은 GitHub 토큰 한 건).
_SPECIFIC_FIRST = ("pem_private_key", "aws_access_key", "github_token", "google_api_key", "oauth_token", "bearer_token")
_RANK = MappingProxyType({kind: number for number, kind in enumerate(_SPECIFIC_FIRST)})

# 앞 글자가 영문·숫자가 아닐 것(한글·기호·줄 처음은 괜찮다. 주소에 퍼센트로 적은 구분자 `%3D`·`%20` 바로 뒤도 괜찮다) — 긴 글 한가운데의 우연한 일치를 줄이고,
# 같은 글자가 이어진 병적 입력에서 시작 자리가 늘어나지 않게 한다.
_ESCAPED = r"(?<=%[0-9A-Fa-f]{2})"
_EDGE = r"(?:(?<![A-Za-z0-9])|" + _ESCAPED + r")"

# 규칙마다 괄호 한 쌍이 '발견한 글'이다(찾은 글 전체가 아니라 비밀 값 자리만 — 예: Bearer 는 낱말과 공백을 뺀 값).
_GOOGLE = re.compile(_EDGE + r"(AIza[A-Za-z0-9_-]{35,})")
_GITHUB = re.compile(_EDGE + r"(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")
_BEARER = re.compile(r"(?:(?<![A-Za-z])|" + _ESCAPED + r")(?i:bearer)(?:[ \t]+|%20|\+)([A-Za-z0-9._\x7e+/-]{19,}[A-Za-z0-9_\x7e+/-]={0,2})")
_OAUTH = re.compile(
    _EDGE + r"(ya29\.[A-Za-z0-9_-]{20,})"                                                         # Google 액세스 토큰
    + r"|" + _EDGE + r"(1//[A-Za-z0-9_-]{20,})"                                                   # Google 갱신 토큰
    + r"|" + _EDGE + r"(GOCSPX-[A-Za-z0-9_-]{20,})"                                               # Google OAuth 클라이언트 비밀(이 앱이 쓸 Blogger 연동의 값)
    + r"|" + _EDGE + r"(eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{8,})"          # JWT 세 덩어리
    + r"|(?i:(?:access|refresh)[_-]?token)[\"']?[ \t]*(?:=>|[=:])[ \t]*[\"']?([A-Za-z0-9_+/%.-]{19,}[A-Za-z0-9_+/%-]={0,3})"   # 이름이 붙은 값
)
_AWS = re.compile(_EDGE + r"((?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[A-Z0-9]{16})(?![A-Za-z0-9])")
_PEM = re.compile(r"(?i)(-----BEGIN[ \t]+(?:[A-Z0-9]+[ \t]+){0,3}PRIVATE[ \t]+KEY(?:[ \t]+BLOCK)?[ \t]*-----)")
_RULES = (("google_api_key", _GOOGLE), ("github_token", _GITHUB), ("bearer_token", _BEARER), ("oauth_token", _OAUTH), ("aws_access_key", _AWS), ("pem_private_key", _PEM))

_NEWLINE = re.compile(r"\r\n|\n|\r")

_NOT_TEXT = "검사할 수 있는 것은 글(str)뿐이에요"
_BAD_WHERE = "칸 이름은 짧은 한 줄 이름이어야 해요(글 내용을 넣지 마세요)"
_SECRET_WHERE = "칸 이름에 키·토큰처럼 보이는 글이 들어 있어요(글 내용을 칸 이름으로 쓰지 마세요)"
_BAD_ACTION = "동작 이름은 짧은 한 줄 이름이어야 해요(예: 저장·백업)"
_NOT_FINDING = "발견 결과(SecretFinding)만 설명할 수 있어요"


def _plain_label(value, limit):
    return isinstance(value, str) and len(value) <= limit and value.isprintable()


@dataclass(frozen=True, slots=True)
class SecretFinding:
    """발견 한 건 — 유형(`KINDS` 중 하나)·칸 이름·줄·열 범위뿐이다(글 내용은 어디에도 없다)."""
    kind: str
    where: str
    line: int
    col_start: int
    col_end: int

    def __post_init__(self):
        if self.kind not in KIND_LABELS:
            raise ValueError("알 수 없는 유형이에요")
        problem = _where_problem(self.where)
        if problem:
            raise ValueError(problem)
        numbers = (self.line, self.col_start, self.col_end)
        if not all(type(number) is int and number >= 1 for number in numbers) or self.col_end < self.col_start:
            raise ValueError("줄과 열은 1 이상의 정수이고 끝 열이 시작 열보다 앞서면 안 돼요")


def _fold(text):
    """호환 글자(전각 영문·숫자·기호, 수학 글자, 동그라미 글자, 위·아래 첨자 숫자, NBSP·전각 공백 같은 특수 공백 …)를 영문·숫자·기호·공백 하나로 맞춘 글. 글자 하나를 글자 하나로만 바꿔 길이가 그대로다."""
    if text.isascii():
        return text
    table = {}
    for ch in set(text):
        if ch < "\x80":
            continue
        folded = unicodedata.normalize("NFKC", ch)
        if len(folded) == 1 and " " <= folded <= "\x7e":
            table[ord(ch)] = folded
    return text.translate(table) if table else text


def _find(text):
    """겹침을 정리한 발견 자리 `(유형, 시작, 끝)` 목록(시작 순, 끝은 포함하지 않는 위치)."""
    view = _fold(text)
    ranked = []
    for kind, rule in _RULES:
        for match in rule.finditer(view):
            start, end = match.span(match.lastindex)
            ranked.append((_RANK[kind], start, -end, kind))
    ranked.sort()
    starts, kept = [], []
    for _, start, negative_end, kind in ranked:
        end = -negative_end
        at = bisect.bisect_left(starts, start)
        if at > 0 and kept[at - 1][2] > start:
            continue
        if at < len(kept) and kept[at][1] < end:
            continue
        starts.insert(at, start)
        kept.insert(at, (kind, start, end))
    return kept


def _check_text(text):
    if not isinstance(text, str):
        raise TypeError(_NOT_TEXT)


def _where_problem(where):
    """칸 이름이 나쁜 이유를 말하는 고정 문장(괜찮으면 None) — 짧은 한 줄이어야 하고 키·토큰처럼 보이면 글 내용을 칸 이름으로 쓴 것이다."""
    if not _plain_label(where, MAX_WHERE_CHARS):
        return _BAD_WHERE
    if where and _find(where):
        return _SECRET_WHERE
    return None


def _check_where(where):
    if not isinstance(where, str):
        raise TypeError(_BAD_WHERE)
    problem = _where_problem(where)
    if problem:
        raise ValueError(problem)


def scan_secrets(text, where=""):
    """글 한 편에서 Secret 형태 여섯 가지를 찾아 위치 순 `SecretFinding` 튜플로 돌려준다. 없으면 빈 튜플.

    `where` 는 호출한 쪽이 붙이는 칸 이름('본문'·'제목' 등 — 글 내용이 아니다)이고 결과에 그대로 실린다. 길거나 줄바꿈 같은 제어 글자가 있거나 키·토큰처럼 보이면 `ValueError` 다.
    글이 `str` 이 아니면 `TypeError` 다(예외 문구에도 글 내용은 없다)."""
    _check_text(text)
    _check_where(where)
    spans = _find(text)
    if not spans:
        return ()
    starts = [0]
    starts.extend(match.end() for match in _NEWLINE.finditer(text))
    found = []
    for kind, start, end in spans:
        index = bisect.bisect_right(starts, start) - 1
        base = starts[index]
        found.append(SecretFinding(kind, where, index + 1, start - base + 1, end - base))
    return tuple(found)


def scan_fields(mapping):
    """칸 이름 → 글 로 된 여러 칸을 한꺼번에 검사한다(칸은 건넨 순서, 칸 안은 위치 순). 값이 `None` 인 칸은 비어 있는 것으로 건너뛰고, 글이 아닌 값은 `TypeError` 다."""
    if not isinstance(mapping, Mapping):
        raise TypeError("칸 이름과 글을 짝지은 것(dict)이 필요해요")
    found = []
    for name, text in mapping.items():
        if text is None:
            continue
        found.extend(scan_secrets(text, name))
    return tuple(found)


def has_secret(text):
    """글에 Secret 형태가 하나라도 있으면 True(`bool(scan_secrets(text))` 와 같다)."""
    _check_text(text)
    view = _fold(text)
    return any(rule.search(view) for _, rule in _RULES)


def describe(finding):
    """발견 한 건을 쉬운 한국어 한 문장으로: '본문 3번째 줄에 GitHub 토큰처럼 보이는 글이 있어요'. 토큰 조각(앞뒤 글자·길이)은 넣지 않는다."""
    if not isinstance(finding, SecretFinding):
        raise TypeError(_NOT_FINDING)
    head = f"{finding.where} " if finding.where else ""
    return f"{head}{finding.line}번째 줄에 {KIND_LABELS[finding.kind]}처럼 보이는 글이 있어요"


def summarize(findings, action="저장"):
    """여러 건을 칸·유형별로 묶은 안내문(없으면 빈 글). 마지막 줄은 고치는 법이다 — 앱은 자동으로 지우거나 바꾸지 않는다. `action` 은 '저장'·'백업' 같은 짧은 동작 이름이다."""
    if not _plain_label(action, MAX_ACTION_CHARS) or not action:
        raise ValueError(_BAD_ACTION)
    items = tuple(findings)
    if not all(isinstance(item, SecretFinding) for item in items):
        raise TypeError(_NOT_FINDING)
    if not items:
        return ""
    groups = {}
    for item in items:
        counts, lines = groups.setdefault(item.where, ({}, set()))
        counts[item.kind] = counts.get(item.kind, 0) + 1
        lines.add(item.line)
    rows = []
    for where, (counts, lines) in groups.items():
        kinds = "·".join(f"{KIND_LABELS[kind]} {count}" for kind, count in counts.items())
        ordered = sorted(lines)
        shown = "·".join(f"{number}번째 줄" for number in ordered[:MAX_LINES_SHOWN])
        more = f" 외 {len(ordered) - MAX_LINES_SHOWN}줄" if len(ordered) > MAX_LINES_SHOWN else ""
        rows.append(f"{where or '글'}에서 {sum(counts.values())}건({kinds}) — {shown}{more}")
    target = f"{next(iter(groups)) or '글'}에서" if len(groups) == 1 else "각 칸에서"
    rows.append(f"해당 줄을 {target} 지운 뒤 다시 {action}해 주세요 — 앱은 자동으로 지우거나 바꾸지 않아요")
    return "\n".join(rows)
