# -*- coding: utf-8 -*-
"""워크플로 글을 '구조'로 읽는 작은 읽개 — 표준 라이브러리만(앱 CI 네 칸에 PyYAML 이 없다), 파이썬 3.10 문법.

블록 모양(들여쓰기)의 매핑·목록·글 값(따옴표·블록 `|`·한 줄 글)만 읽는다. 다른 표기는 **읽을 수 없다고 거절한다**(YamlSubsetError) — 흐름식 `{…}`·`[…]`(단 **값 자리의 정확히 `{}`·`[]` 만** 빈 매핑·빈 목록으로 읽는다 — 릴리스 워크플로의 최상위 `permissions: {}`, 결정 D-880), 앵커 `&`·별칭 `*`·태그 `!`,
병합 키 `<<`, 여러 문서 `---`, 탭 들여쓰기, 같은 키가 두 번 나오는 매핑, 접은 글 `>`, 한 줄을 넘는 글 값, 목록 안의 목록. 거절은 일부러다: 승인 조건(수동 실행·읽기 권한·비밀 0·액션 SHA 고정)을
지키는지 보는 시험이 낱말 찾기가 아니라 '실제 구조'를 읽도록 하되, 읽개가 모르는 표기로 숨기는 길(한 줄 흐름식 단계 등)이 없게 한다. 거절되면 시험이 빨개지므로 워크플로 파일을 고칠 때는
표기를 그대로 두거나 이 읽개와 시험을 같이 고친다. 값은 모두 글(str)이고(`false`·`45` 도 글) 빈 값은 None 이다(정확히 `{}`·`[]` 만 빈 매핑 dict·빈 목록 list).
줄 나눔처럼 읽힐 수 있거나 보이지 않는 글자(줄 바꿈 말고 U+000B·U+000C·U+001C에서 U+001F·U+0085·U+2028·U+2029 와 유니코드 범주 Cc·Cf·Zl·Zp·Co)는 **주석·name 값·키·따옴표 글·블록 글 어디에 있든 거절한다** —
YAML 1.1 계열 파서(libyaml·PyYAML)는 U+0085·U+2028·U+2029 를 줄 나눔으로 읽어서, 이 글자와 함께 주석이나 name 칸에 숨긴 단계가 규칙 검사에는 안 보이고 파서에는 보일 수 있다(독립 검증 S 의 SP-6).
입력이 너무 길거나 너무 깊어도 거절한다(MAX_TEXT·MAX_LINE·MAX_DEPTH — 독립 검증 S 의 SN-16: 긴 공백 줄의 제곱 시간·깊은 중첩의 RecursionError).
**줄 끝과 값 앞뒤에서는 ASCII 공백(U+0020)만 자른다** — NBSP(U+00A0)·U+2003·U+3000·U+202F 같은 유니코드 공백(범주 Zs)은 YAML 에서 공백이 아니라 값의 일부인데 파이썬 `str.strip()` 은 이것까지 잘라서, 모든 못박은 값이 보이지 않는 글자 하나로 시험을 통과했다
(독립 검증 S 의 S-1, 결정 D-887). 그래서 값에 남기거나(`environment: release` 뒤의 NBSP 는 값이 `release` 가 아니게 된다) 읽을 수 없는 줄로 거절한다. 줄 끝의 역슬래시 뒤 ASCII 공백도 거절한다 — 셸에서는 줄 이음이 아닌데(역슬래시와 공백은 공백 글자를 이스케이프할 뿐 다음 줄은 새 명령이다)
줄 끝 공백을 지우는 읽개와 규칙 검사에는 줄 이음으로 보여 다음 줄의 명령이 앞 명령의 인자로 가려졌다.
사용: load(text) -> dict | list | str | None
"""
import re
import unicodedata

MAX_TEXT = 100000                                         # 글 전체 길이 상한(진짜 파일은 4천 글자 안팎)
MAX_LINE = 1000                                           # 한 줄 길이 상한(진짜 파일은 가장 긴 줄이 220글자 안팎)
MAX_DEPTH = 24                                            # 중첩 깊이 상한(진짜 파일은 일곱 단계 안팎)
REFUSED_CATEGORIES = ("Cc", "Cf", "Zl", "Zp", "Co")       # 제어·서식(제로폭·방향 제어)·줄/문단 구분·사설 영역 — 줄 바꿈(LF)만 빼고 모두 거절
LINE_BREAKS = "".join(chr(code) for code in (0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x1F, 0x85, 0x2028, 0x2029))      # 줄 나눔으로 읽힐 수 있는 글자(범주 표가 바뀌어도 거절하도록 따로 적는다)
BACKSLASH = chr(0x5C)                                     # 줄 끝의 역슬래시 + 공백 거절에 쓴다(소스에 역슬래시 글자를 직접 쓰지 않는다)


class YamlSubsetError(ValueError):
    """이 읽개가 읽지 않는 표기이거나 모양이 어긋난 글."""


EMPTY_FLOW = {"{}": dict, "[]": list}                         # 흐름식 중 읽는 것은 이 둘뿐이다 — `{ }`·`{}x`·`[1]`·`{a: 1}` 은 그대로 거절한다(목록 항목·키 자리·문서 맨 위의 `{}` 도 거절)
KEY = re.compile(r"""^(?P<key>[A-Za-z0-9_][A-Za-z0-9_.\-/]*|'(?:[^']|'')*'|"(?:[^"\\]|\\.)*")[ ]*:(?:[ ]+(?P<rest>.*))?$""")
BLOCK_SCALAR = re.compile(r"^\|(?P<chomp>[+-]?)(?:[ ]+#.*)?$")
SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t"}


def fail(number, message):
    raise YamlSubsetError("%d번째 줄: %s" % (number, message))


def strip_comment(rest):
    """한 줄 글 값에서 뒤쪽 주석(공백 + `#`부터)을 자른다 — 정규식 역추적 없이 찾아 선형이다(긴 공백 줄이 제곱 시간이 되던 것을 막는다)."""
    index = rest.find(" #")
    return (rest if index < 0 else rest[:index]).rstrip(" ")


def only_comment_follows(tail):
    """따옴표 글 뒤에 남은 글이 없거나 공백 + `#` 주석뿐인가."""
    stripped = tail.strip(" ")
    return stripped == "" or (tail.startswith(" ") and stripped.startswith("#"))


def unquote(text, number):
    """따옴표 글 하나를 풀어 (값, 남은 글)을 돌려준다 — 같은 줄 안에서 닫혀야 한다."""
    quote, out, i = text[0], [], 1
    while i < len(text):
        ch = text[i]
        if quote == "'":
            if ch == "'":
                if text[i + 1:i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), text[i + 1:]
            out.append(ch)
        else:
            if ch == "\\":
                following = text[i + 1:i + 2]
                if following not in SIMPLE_ESCAPES:
                    fail(number, "읽지 않는 이스케이프(역슬래시 + %s)" % following)
                out.append(SIMPLE_ESCAPES[following])
                i += 2
                continue
            if ch == '"':
                return "".join(out), text[i + 1:]
            out.append(ch)
        i += 1
    fail(number, "따옴표가 같은 줄에서 닫히지 않는다")


class Reader:
    def __init__(self, text):
        if len(text) > MAX_TEXT:
            raise YamlSubsetError("글이 너무 길다(%d글자 상한)" % MAX_TEXT)
        if "\x00" in text or text.startswith(chr(0xFEFF)):
            raise YamlSubsetError("NUL 글자나 BOM 이 있다")
        normalized = text.replace("\r\n", "\n")
        if "\r" in normalized:
            raise YamlSubsetError("줄 끝에 홀로 CR 이 있다")
        self.lines = []
        self.depth = 0
        for number, line in enumerate(normalized.split("\n"), 1):
            if len(line) > MAX_LINE:
                fail(number, "줄이 너무 길다(%d글자 상한)" % MAX_LINE)
            stripped = line.lstrip(" ")
            if stripped.startswith("\t"):
                fail(number, "탭 들여쓰기는 읽지 않는다")
            for ch in line:
                if ch in LINE_BREAKS or unicodedata.category(ch) in REFUSED_CATEGORIES:
                    fail(number, "줄 나눔처럼 읽힐 수 있거나 보이지 않는 글자(U+%04X)는 주석·글 값 어디에도 읽지 않는다" % ord(ch))
            if line.endswith(" ") and line.rstrip(" ").endswith(BACKSLASH):
                fail(number, "줄 끝의 역슬래시 뒤 공백은 읽지 않는다(셸은 줄 이음으로 읽지 않는데 읽개가 줄 끝 공백을 지워 이음으로 보게 된다)")
            self.lines.append((number, len(line) - len(stripped), stripped.rstrip(" ")))                  # 줄 끝에서는 ASCII 공백만 자른다 — NBSP·U+3000 같은 유니코드 공백은 YAML 에서 값의 일부다(독립 검증 S 의 S-1)
        self.i = 0

    def skip(self):
        """빈 줄과 주석만 있는 줄을 건너뛴다(블록 글 안에서는 부르지 않는다 — 거기서는 `#` 줄도 글이다)."""
        while self.i < len(self.lines) and (not self.lines[self.i][2] or self.lines[self.i][2].startswith("#")):
            self.i += 1

    def document(self):
        self.skip()
        if self.i >= len(self.lines):
            return None
        number, indent, text = self.lines[self.i]
        if text in ("---", "...") or text.startswith(("--- ", "... ")):
            fail(number, "문서 표시(---)는 읽지 않는다")
        value = self.node(indent)
        self.skip()
        if self.i < len(self.lines):
            fail(self.lines[self.i][0], "읽다 만 줄이 남았다(들여쓰기가 어긋났거나 문서 표시가 있다)")
        return value

    def node(self, indent):
        self.skip()
        number, line_indent, text = self.lines[self.i]
        if line_indent != indent:
            fail(number, "들여쓰기가 맞지 않는다")
        if text == "-" or text.startswith("- "):
            return self.sequence(indent)
        return self.mapping(indent)

    def deeper(self, function, indent):
        self.depth += 1
        try:
            if self.depth > MAX_DEPTH:
                fail(self.lines[self.i][0] if self.i < len(self.lines) else len(self.lines), "중첩이 너무 깊다(%d단계 상한)" % MAX_DEPTH)
            return function(indent)
        finally:
            self.depth -= 1

    def mapping(self, indent):
        return self.deeper(self.read_mapping, indent)

    def sequence(self, indent):
        return self.deeper(self.read_sequence, indent)

    def read_mapping(self, indent):
        result = {}
        while True:
            self.skip()
            if self.i >= len(self.lines):
                break
            number, line_indent, text = self.lines[self.i]
            if line_indent < indent:
                break
            if line_indent > indent:
                fail(number, "들여쓰기가 맞지 않는다(앞 줄의 값이 한 줄을 넘는 글은 읽지 않는다)")
            if text == "-" or text.startswith("- "):
                break
            if text.startswith("<<"):
                fail(number, "병합 키(<<)는 읽지 않는다")
            match = KEY.match(text)
            if not match:
                fail(number, "읽을 수 없는 줄('키: 값' 모양이 아니다)")
            raw_key = match.group("key")
            key = unquote(raw_key, number)[0] if raw_key[0] in "'\"" else raw_key
            if key in result:
                fail(number, "같은 키가 두 번 나온다: " + key)
            self.i += 1
            result[key] = self.value(match.group("rest") or "", indent, number)
        return result

    def value(self, rest, key_indent, number):
        rest = rest.strip(" ")
        if rest == "" or rest.startswith("#"):
            self.skip()
            if self.i < len(self.lines):
                _number, next_indent, next_text = self.lines[self.i]
                if next_indent > key_indent:
                    return self.node(next_indent)
                if next_indent == key_indent and (next_text == "-" or next_text.startswith("- ")):
                    return self.sequence(key_indent)
            return None
        first = rest[0]
        if first in "{[":
            empty = EMPTY_FLOW.get(strip_comment(rest))                 # 값 자리의 정확히 `{}`·`[]`(뒤에 공백 + `#` 주석만 올 수 있다)만 빈 매핑·빈 목록 — 릴리스 워크플로의 최상위 `permissions: {}`(결정 D-880)
            if empty is None:
                fail(number, "흐름식 {…}·[…] 은 읽지 않는다(값 자리의 정확히 {} 와 [] 만 읽는다)")
            return empty()
        if first in "&*!@`%?":
            fail(number, "앵커·별칭·태그나 예약 글자(%s)로 시작하는 값은 읽지 않는다" % first)
        if first == ">":
            fail(number, "접은 글 블록(>)은 읽지 않는다")
        if first == "|":
            return self.block_scalar(rest, key_indent, number)
        if first in "'\"":
            text, tail = unquote(rest, number)
            if not only_comment_follows(tail):
                fail(number, "따옴표 글 뒤에 다른 글이 있다")
            return text
        value = strip_comment(rest)
        if ": " in value or value.endswith(":"):
            fail(number, "값 안에 '키: 값' 모양이 들어 있다")
        if value == "-" or value.startswith("- "):
            fail(number, "값 자리에 목록 표시(-)가 있다")
        return value

    def block_scalar(self, rest, key_indent, number):
        match = BLOCK_SCALAR.match(rest)
        if not match:
            fail(number, "블록 글(|) 표시 모양을 읽을 수 없다(들여쓰기 숫자는 읽지 않는다)")
        collected, content_indent = [], None
        while self.i < len(self.lines):
            line_number, indent, text = self.lines[self.i]
            if not text:
                collected.append(None)
                self.i += 1
                continue
            if indent <= key_indent:
                break
            if content_indent is None:
                content_indent = indent
            if indent < content_indent:
                fail(line_number, "블록 글의 들여쓰기가 앞 줄보다 얕다")
            collected.append(" " * (indent - content_indent) + text)
            self.i += 1
        trailing = 0
        while collected and collected[-1] is None:
            collected.pop()
            trailing += 1
        if content_indent is None:
            return ""
        body = "\n".join("" if line is None else line for line in collected)
        chomp = match.group("chomp")
        if chomp == "-":
            return body
        if chomp == "+":
            return body + "\n" * (1 + trailing)
        return body + "\n"

    def read_sequence(self, indent):
        items = []
        while True:
            self.skip()
            if self.i >= len(self.lines):
                break
            number, line_indent, text = self.lines[self.i]
            if line_indent < indent:
                break
            if line_indent > indent:
                fail(number, "들여쓰기가 맞지 않는다")
            if not (text == "-" or text.startswith("- ")):
                break
            after = text[1:]
            inner = after.lstrip(" ")
            offset = 1 + len(after) - len(inner)
            if inner == "" or inner.startswith("#"):
                self.i += 1
                self.skip()
                if self.i < len(self.lines) and self.lines[self.i][1] > indent:
                    items.append(self.node(self.lines[self.i][1]))
                else:
                    items.append(None)
                continue
            if inner[0] in "{[":
                fail(number, "흐름식 {…}·[…] 은 읽지 않는다")
            if inner == "-" or inner.startswith("- "):
                fail(number, "목록 안의 목록은 읽지 않는다")
            if inner[0] in "|>":
                fail(number, "목록 항목에 바로 붙은 블록 글은 읽지 않는다")
            if KEY.match(inner):
                self.lines[self.i] = (number, indent + offset, inner)
                items.append(self.mapping(indent + offset))
                continue
            self.i += 1
            items.append(self.value(inner, indent, number))
        return items


def load(text):
    return Reader(text).document()
