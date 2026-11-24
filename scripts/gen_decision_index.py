"""docs/DECISIONS.md 에서 결정 색인 docs/DECISIONS_INDEX.md 를 만든다 — 번호·날짜·변경 등급·한 줄 요약을 한 줄씩 모은 표다.

정본은 `DECISIONS.md`(한 행이 1천 자를 넘는 것이 많아 1.4MB 가 넘는다)이고 색인은 거기서 만든 길라잡이다(직접 고치지 않는다). 읽기만 하는 도구다 — `DECISIONS.md` 를 읽고 색인 한 파일만 쓰며
네트워크·하위 프로세스·다른 파일 쓰기가 없다(표준 라이브러리만). 결정 행을 더하거나 고친 뒤 실행한다:

    python scripts/gen_decision_index.py          # docs/DECISIONS_INDEX.md 를 다시 쓴다
    python scripts/gen_decision_index.py --check  # 쓰지 않고 색인이 낡았으면 종료 코드 1 (시험이 같은 검사를 한다)

한 줄 요약은 사람이 쓰지 않고 자동으로 만든다: 행의 결정 칸이 굵은 글(별표 둘로 싼 글)로 시작하면 그 첫머리를(거의 모든 행이 그렇다), 아니면 첫 문장을 쓴다. 링크는 글자만 남기고
굵은 표시·물결표·웹 주소·이중 중괄호·세로줄은 문서 규칙에 맞게 바꾼다. 100자를 넘으면 **글자 사이가 아니라 띄어쓰기에서만** 자르고 끝에 줄임표(…)를 붙인다 —
따옴표·괄호·코드(백틱) 안에서는 자르지 않는다(자른 곳이 안전한지는 `tests/test_decision_index.py` 가 모든 행에서 확인한다).
변경 등급은 행에 적힌 첫 표기(`변경 등급 T2` 우선, 없으면 `등급 T2`·상태 칸의 `T2`)를 읽은 힌트일 뿐이고 적혀 있지 않으면 `—` 이다.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "DECISIONS.md"
OUT = ROOT / "docs" / "DECISIONS_INDEX.md"

SUMMARY_LIMIT = 100          # 한 줄 요약의 바람직한 길이(글자) — 넘으면 안전한 띄어쓰기에서 자른다
SUMMARY_HARD_MAX = 140       # 안전하게 자를 곳이 100자 안에 없을 때 늘려 주는 한계 — 그 안에도 없으면 자르지 않는다
SUMMARY_MIN_CUT = 24         # 너무 짧게 잘라 뜻이 사라지는 것을 막는 바닥
SHORT_LEAD = 16              # 굵은 첫머리가 이보다 짧으면(예: '잠금'·'버전 규칙') 이름표일 뿐이라 첫 문장 전체를 요약 재료로 쓴다
ELLIPSIS = "…"
NO_GRADE = "—"
TILDE = chr(0x7E)            # 소스에도 물결표·이중 중괄호를 글자 그대로 적지 않는다(문서 규칙 — 시험도 같은 방식)
DOUBLE_OPEN, DOUBLE_CLOSE = "{" * 2, "}" * 2

ROW_START = re.compile(r"^\| (D-\d+) \|")
ROW = re.compile(r"^\| (D-\d+) \| (\d{4}-\d{2}-\d{2}) \| (.*)$")
FENCE = re.compile(r"^\s*(```|" + re.escape(TILDE * 3) + ")")
BOLD_LEAD = re.compile(r"^\*\*(.+?)\*\*")
LINK = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")
URL_SCHEME = re.compile(r"(?i)\b(?:https?|ftp)://")
GRADE_PATTERNS = (re.compile(r"변경 등급 (T[0-3])"), re.compile(r"등급 (T[0-3])"))
GRADE_TOKEN = re.compile(r"(?<![\w-])(T[0-3])(?![\w-])")
GRADE_HEAD = re.compile(r"(?:[,(]\s?|\s·\s)(T[0-3])(?=[)\s,·.—])")          # 결정 칸 첫머리의 `(…, T2)`·` · T2` 꼴 — 등급을 말하는 낱말 없이 **괄호 안**에 적은 경우(문장 속의 `T2 는 …` 은 읽지 않는다)
GRADE_HEAD_CHARS = 300

OPENERS = {"(": ")", "[": "]", "{": "}", "「": "」", "『": "』", "‘": "’", "“": "”"}
CLOSERS = {value: key for key, value in OPENERS.items()}
TRAILING_JUNK = " ,·—-–:;/"
CUT_BEFORE = " ·("          # 자를 수 있는 자리 — 띄어쓰기, 목록 구분점(·), 여는 괄호의 바로 앞(그 글자는 요약에 넣지 않는다)


class IndexProblem(ValueError):
    """결정 기록의 줄 모양이 틀렸을 때(조용히 빠뜨리지 않고 알린다)."""


# ---- 읽기 -----------------------------------------------------------------------------------

def split_cells(rest):
    """`결정 | 상태·근거 |`(맨 끝 세로줄은 없을 수도 있다) → (결정, 상태). 결정 칸 속의 세로줄이 있어도 맨 뒤 하나만 칸 나눔으로 본다."""
    text = rest.rstrip()
    if text.endswith("|"):
        text = text[:-1].rstrip()
    if " | " in text:
        decision, status = text.rsplit(" | ", 1)
        return decision.strip(), status.strip()
    return text.strip(), ""


def parse(text, name="DECISIONS.md"):
    """결정 기록 글 → [(번호 문자열, 번호 정수, 날짜, 결정 칸, 상태 칸), …] (파일에 나온 순서). 잘못된 줄이 있으면 IndexProblem."""
    rows, seen, fenced = [], {}, None
    for number, line in enumerate(text.splitlines(), 1):
        fence = FENCE.match(line)
        if fence:
            fenced = None if fenced == fence.group(1) else (fenced or fence.group(1))
            continue
        if fenced or not ROW_START.match(line):
            continue
        match = ROW.match(line)
        if not match:
            raise IndexProblem(f"{name}:{number}: 결정 행의 모양이 틀렸다(`| D-번호 | 날짜 | 결정 | 상태·근거 |`): {line[:60]}")
        label, day, rest = match.groups()
        try:
            datetime.date.fromisoformat(day)
        except ValueError:
            raise IndexProblem(f"{name}:{number} {label}: 날짜가 올바르지 않다({day})") from None
        decision, status = split_cells(rest)
        if not decision:
            raise IndexProblem(f"{name}:{number} {label}: 결정 칸이 비었다")
        if label in seen:
            raise IndexProblem(f"{name}:{number} {label}: 번호가 겹친다(앞의 줄 {seen[label]})")
        seen[label] = number
        rows.append((label, int(label[2:]), day, decision, status))
    if fenced:
        raise IndexProblem(f"{name}: 코드 블록({fenced})이 닫히지 않았다")
    if not rows:
        raise IndexProblem(f"{name} 에서 결정 행을 찾지 못했다")
    return rows


# ---- 한 줄 요약 -----------------------------------------------------------------------------

def first_sentence(text):
    """첫 문장 — 백틱·괄호 밖의 `. `(마침표와 띄어쓰기)에서 끝낸다. 없으면 전체."""
    in_code, depth = False, 0
    for index, char in enumerate(text):
        if char == "`":
            in_code = not in_code
        elif not in_code:
            if char in OPENERS:
                depth += 1
            elif char in CLOSERS:
                depth = max(0, depth - 1)
            elif char == "." and depth == 0 and text[index + 1: index + 2] == " ":
                return text[:index]
    return text


def tidy(text):
    """마크다운 꾸밈을 걷고 문서 규칙에 맞게 바꾼다 — 링크는 글자만·굵은 표시 제거·물결표는 en dash·웹 주소의 앞 부분 제거·이중 중괄호는 낫표·세로줄은 슬래시·공백은 하나로."""
    text = LINK.sub(r"\1", text)
    text = text.replace("**", "")
    text = URL_SCHEME.sub("", text)
    text = text.replace(TILDE, "–").replace(DOUBLE_OPEN, "「").replace(DOUBLE_CLOSE, "」").replace("|", "/")
    return re.sub(r"\s+", " ", text).strip().rstrip(".").strip()


def lead_of(decision):
    """결정 칸에서 요약 재료 — 굵은 첫머리가 있고 16자 이상이면 그것, 아니면(없거나 이름표처럼 짧으면) 첫 문장. 아직 줄이지 않은 글."""
    bold = BOLD_LEAD.match(decision)
    if bold:
        lead = tidy(bold.group(1))
        if len(lead) >= SHORT_LEAD:
            return lead
    return tidy(first_sentence(decision))


def safe_cut(text, limit=SUMMARY_LIMIT, hard_max=SUMMARY_HARD_MAX, min_cut=SUMMARY_MIN_CUT):
    """`text` 를 자를 안전한 위치(글자 번호)를 돌려준다 — 띄어쓰기·구분점(·)·여는 괄호의 바로 앞이고, 백틱·괄호·따옴표 안이 아니고, 앞에 min_cut 글자 이상이 남는 곳 가운데 limit 안에서 가장 늦은 곳.
    없으면 limit 뒤 hard_max 안의 가장 이른 곳. 그것도 없으면 None(자르지 않는다)."""
    paired = {char: text.count(char) % 2 == 0 for char in ("'", '"')}              # 개수가 짝수인 직선 따옴표만 짝으로 센다(아포스트로피 하나가 섞인 글은 따옴표로 보지 않는다)
    in_code, depth, quote = False, 0, None
    before, after = None, None
    for index, char in enumerate(text):
        if index > hard_max:
            break
        if char in CUT_BEFORE and not in_code and depth == 0 and quote is None and index >= min_cut:
            if index <= limit:
                before = index
            elif after is None:
                after = index
        if char == "`":
            in_code = not in_code
        elif in_code:
            continue
        elif paired.get(char):
            quote = None if quote == char else (quote or char)
        elif quote is None:
            if char in OPENERS:
                depth += 1
            elif char in CLOSERS:
                depth = max(0, depth - 1)
    return before if before is not None else after


def shorten(text, limit=SUMMARY_LIMIT, hard_max=SUMMARY_HARD_MAX, min_cut=SUMMARY_MIN_CUT):
    """요약이 limit 글자를 넘으면 안전한 띄어쓰기에서 자르고 줄임표를 붙인다. 안전한 곳이 없으면 그대로 둔다."""
    if len(text) <= limit:
        return text
    cut = safe_cut(text, limit, hard_max, min_cut)
    if cut is None:
        return text
    head = text[:cut].rstrip(TRAILING_JUNK)
    return head + ELLIPSIS if head else text


def summary_of(decision):
    return shorten(lead_of(decision))


def grade_of(decision, status):
    """행에 적힌 첫 변경 등급(`T0`–`T3`) — 없으면 `—`. 순서: `변경 등급 T2` → `등급 T2`(결정 칸·상태 칸) → 상태 칸의 `T2` 낱말 → 결정 칸 첫머리(처음 300자)의 `(…, T2)` 꼴."""
    for pattern in GRADE_PATTERNS:
        for cell in (decision, status):
            match = pattern.search(cell)
            if match:
                return match.group(1)
    match = GRADE_TOKEN.search(status)
    if match:
        return match.group(1)
    head = decision[:GRADE_HEAD_CHARS]
    for match in GRADE_HEAD.finditer(head):
        if head.count("(", 0, match.start(1)) > head.count(")", 0, match.start(1)):      # 괄호 안일 때만
            return match.group(1)
    return NO_GRADE


# ---- 쓰기 -----------------------------------------------------------------------------------

HEAD = """# 결정 색인 (자동 생성 — 직접 고치지 않는다)

> `python scripts/gen_decision_index.py` 가 [`DECISIONS.md`](DECISIONS.md) 에서 만든 길라잡이다. **정본은 `DECISIONS.md` 이고 다르면 거기가 이긴다.** 한 줄 요약은 사람이 쓴 것이 아니라 각 결정 행의 굵은 첫머리(없으면 첫 문장)를 {limit}자 안팎으로 줄인 것이고, 등급은 행에 적힌 첫 변경 등급 표기를 읽은 힌트다(`—` 는 적혀 있지 않다는 뜻). 결정 행을 더하거나 고친 갈래는 `python scripts/gen_decision_index.py` 를 다시 실행해 이 파일을 함께 올린다(`tests/test_decision_index.py` 가 낡았는지 본다).

- 행 {count}개 · 가장 앞 번호 {first} · 가장 큰 번호 {last} · 가장 최근 날짜 {latest}
- 결정 기록에 행이 없는 번호(건너뛴 구간, 'D-' 없이 숫자만): {gaps}

## 쓰는 법

- **번호를 알 때** — 그 행 전문(한 행이 아주 길 수 있다)은 PowerShell 에서 `Select-String -Encoding utf8 -Path docs/DECISIONS.md -Pattern '^\\| D-343 \\|' | ForEach-Object {open}$_.Line{close}`, 다른 쉘에서는 `grep -n '^| D-343 |' docs/DECISIONS.md`. 앞 160자만 보려면 AGENTS.md 의 마지막 10행 명령처럼 `Substring` 으로 자른다.
- **주제만 알 때** — 이 파일에서 낱말로 찾는다(`Select-String -Path docs/DECISIONS_INDEX.md -Pattern '백업'`). 요약에 없으면 `DECISIONS.md` 전체 검색이 필요하다.
- **가장 최근** — 맨 아래 표가 가장 큰 번호들이다. 지금 진행 중인 일은 이 색인이 아니라 `AGENTS.md` §0 이 알려 주는 곳에서 읽는다.

## 색인

| 번호 | 날짜 | 등급 | 한 줄 요약 |
|---|---|---|---|
"""


def number_ranges(missing):
    """[81, 82, 83, 107] → '81–83, 107' (숫자 범위는 en dash). 'D-' 를 붙이지 않는다 — 결정 기록에 없는 번호를 'D-81' 꼴로 적으면 문서 시험이 '정의되지 않은 결정 번호' 로 본다."""
    def label(first, last):
        return str(first) if first == last else f"{first}–{last}"

    parts, start, previous = [], None, None
    for number in missing:
        if start is None:
            start = previous = number
        elif number == previous + 1:
            previous = number
        else:
            parts.append(label(start, previous))
            start = previous = number
    if start is not None:
        parts.append(label(start, previous))
    return ", ".join(parts)


def render(rows):
    """parse() 결과 → 색인 글. 번호 순으로 쓴다(같은 입력이면 늘 같은 글)."""
    ordered = sorted(rows, key=lambda row: row[1])
    present = {row[1] for row in ordered}
    missing = [number for number in range(ordered[0][1], ordered[-1][1] + 1) if number not in present]
    head = HEAD.format(limit=SUMMARY_LIMIT, count=len(ordered), first=ordered[0][0], last=ordered[-1][0], latest=max(row[2] for row in ordered), gaps=number_ranges(missing) or "없음",
                       open="{", close="}")
    lines = [f"| {label} | {day} | {grade_of(decision, status)} | {summary_of(decision)} |" for label, _number, day, decision, status in ordered]
    return head + "\n".join(lines) + "\n"


def expected_text(source=SOURCE):
    return render(parse(Path(source).read_text(encoding="utf-8"), Path(source).name))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="파일을 쓰지 않고 색인이 결정 기록과 같은지만 본다(다르면 종료 코드 1)")
    parser.add_argument("--source", default=str(SOURCE), help="결정 기록 파일(기본: docs/DECISIONS.md) — 시험이 임시 파일로 확인하려고 둔 옵션")
    parser.add_argument("--out", default=str(OUT), help="색인 파일(기본: docs/DECISIONS_INDEX.md)")
    args = parser.parse_args(argv)
    out = Path(args.out)
    try:
        rows = parse(Path(args.source).read_text(encoding="utf-8"), Path(args.source).name)
    except IndexProblem as error:
        print(f"색인을 만들지 못했다: {error}", file=sys.stderr)
        return 2
    wanted = render(rows)
    current = out.read_text(encoding="utf-8") if out.exists() else None
    if args.check:
        if current != wanted:
            print(f"{out.name} 가 {Path(args.source).name} 와 다르다 — `python scripts/gen_decision_index.py` 로 다시 만든다.", file=sys.stderr)
            return 1
        print(f"{out.name} 가 결정 기록과 같다({len(rows)}행).")
        return 0
    if current == wanted:
        print("바뀐 것이 없다.")
        return 0
    out.write_text(wanted, encoding="utf-8", newline="\n")
    print(f"{out.name} 를 다시 썼다({len(rows)}행).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
