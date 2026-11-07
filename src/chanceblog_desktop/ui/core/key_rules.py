"""키 입력 칸의 규칙(P4f) — 순수 파이썬(화면 도구·서비스 층을 모른다). **받은 글을 되풀이하거나 보관하지 않는다**: 글을 검사해 '문제 이름'(짧은 글자 몇 개) 만 돌려주고, 문제 이름·문장에는 입력한 글이 들어 있지 않다.

운영자 확정 답변(2026-11-06)의 느슨한 검사 — 키의 정확한 길이·모양을 강제하지 않고 다음만 거른다: 빈 값 · 앞뒤 공백(지운다) · 복사하다 섞인 줄바꿈(지운다) · 제어 문자·눈에 안 보이는 글자·가운데 공백 · 비정상적으로 짧은 값.
용도마다 정해진 최소 길이·글자 종류는 서비스(`service/connections.py`)가 한 번 더 본다 — 그 거절도 이유만(입력 없이) 알려진다.

별칭은 비밀이 아닌 글이지만 키를 잘못 붙여 넣는 일이 있어 키처럼 보이는 글을 거절한다(서비스도 같은 검사를 한다).
"""
from __future__ import annotations

SECRET_MIN = 8                              # 이보다 짧은 값은 키가 끝까지 복사되지 않은 것으로 본다 — 길이를 강제하는 규칙이 아니라 '비정상적으로 짧은 값' 의 경계다
ALIAS_MAX = 40                              # 서비스의 `MAX_NAME_CHARS` 와 같다(시험이 견준다)
DEFAULT_ALIAS = "기본"
SECRET_PROBLEMS = ("empty", "hidden", "short")
ALIAS_PROBLEMS = ("empty", "long", "hidden", "keyish")


def clean_secret(text):
    """붙여 넣다 섞인 줄바꿈을 모두 지우고 앞뒤 공백을 걷어낸 새 글 — 입력 칸에서 곧바로 이 함수로 다듬어 서비스에 넘긴다(다듬은 글을 다른 곳에 두지 않는다)."""
    return "".join(str(text).splitlines()).strip()


def secret_problem(text):
    """다듬은 키 글의 문제 이름 — '' 이면 문제 없음. empty(비어 있음) · hidden(가운데 공백·제어 문자·눈에 안 보이는 글자) · short(비정상적으로 짧음)."""
    from ...security import shape
    if not text:
        return "empty"
    if shape.has_hidden_char(text):
        return "hidden"
    if len(text) < SECRET_MIN:
        return "short"
    return ""


def normalize_alias(text):
    """별칭의 앞뒤·연속 공백을 한 칸으로 줄인다(서비스는 연속 공백을 거절한다)."""
    return " ".join(str(text).split())


def alias_problem(text):
    """별칭의 문제 이름 — '' 이면 문제 없음. 다듬은 뒤의 글을 본다. empty · long · hidden(줄바꿈·눈에 안 보이는 글자) · keyish(키처럼 보임)."""
    from ...security import shape
    value = normalize_alias(text)
    if not value:
        return "empty"
    if len(value) > ALIAS_MAX:
        return "long"
    if shape.looks_secret(value):
        return "keyish"
    if shape.label_problem(value, max_len=ALIAS_MAX):                      # 키 모양도 길이도 아닌데 거절되는 것은 줄바꿈·눈에 안 보이는 글자뿐이다
        return "hidden"
    return ""
