"""docs/TROUBLESHOOTING.md 의 오류 코드 표에서 src/chanceblog_desktop/errors/catalog.py 를 만든다.

정본은 문서이고 catalog.py 는 거기서 만든 파일이다(직접 고치지 않는다). 문서의 표를 고친 뒤 실행한다:

    python scripts/sync_errors.py          # catalog.py 를 다시 쓴다
    python scripts/sync_errors.py --check  # 어긋나 있으면 종료 코드 1 (시험이 같은 검사를 한다)

표의 한 줄은 `| `코드` | 언제 | 사용자 문구 | 하실 일 | 재시도 |` 이고, 칸이 비었거나 코드가 겹치거나 재시도 칸이
정해진 문구가 아니면 여기서 실패한다. 머리글(`| 코드 | …`) 아래 표 안에서 이 모양이 아닌 줄(코드가 소문자·백틱 없음·들여쓰기 등)도
조용히 빠뜨리지 않고 실패한다. 코드 블록(```) 안의 표 모양은 예시라서 읽지 않는다.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "TROUBLESHOOTING.md"
ERRORS = ROOT / "src" / "chanceblog_desktop" / "errors"
OUT = ERRORS / "catalog.py"


def _load_model():
    """errors/model.py 만 파일 경로로 읽는다 — 패키지를 import 하면 아직 없거나 낡은 catalog.py 때문에 이 스크립트가 못 돈다."""
    name = "_chanceblog_errors_model"
    spec = importlib.util.spec_from_file_location(name, ERRORS / "model.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


parse_retry = _load_model().parse_retry

HEADING = re.compile(r"^## \d+\. (.+?)\s*$")
ROW = re.compile(r"^\| `([A-Z][A-Z0-9_]+)` \|(.*)\|\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
TABLE_HEADER = re.compile(r"^\|\s*코드\s*\|")
SEPARATOR = re.compile(r"^\|[\s:|-]+\|\s*$")

HEADER = '''"""오류 코드 카탈로그 — 직접 고치지 않는다.

docs/TROUBLESHOOTING.md 의 표에서 `python scripts/sync_errors.py` 가 만든 파일이다.
고칠 곳은 문서이고, 고친 뒤 위 명령을 다시 실행한다(시험이 둘이 같은지 확인한다).
"""

# (영역, 코드, 언제, 사용자 문구, 하실 일, 재시도)
ROWS = (
'''


def parse(doc_text):
    """문서 → [(영역, 코드, 언제, 사용자 문구, 하실 일, 재시도), …]. 잘못된 줄이 있으면 ValueError."""
    rows, seen, area, fenced, in_table = [], set(), None, None, False
    for number, line in enumerate(doc_text.splitlines(), 1):
        fence = FENCE.match(line)
        if fence:
            fenced = None if fenced == fence.group(1) else (fenced or fence.group(1))
            in_table = False
            continue
        if fenced:                                   # 코드 블록 안의 표 모양은 예시일 뿐이다
            continue
        heading = HEADING.match(line)
        if heading:
            area = heading.group(1)
            in_table = False
            continue
        if TABLE_HEADER.match(line):
            in_table = True
            continue
        match = ROW.match(line)
        if not match:
            if in_table and line.strip() and not SEPARATOR.match(line):
                raise ValueError(f"{DOC.name}:{number}: 오류 코드 표의 줄 모양이 틀렸다(`| `CODE` | 언제 | 사용자 문구 | 하실 일 | 재시도 |`): {line.strip()[:60]}")
            if not line.strip():
                in_table = False
            continue
        if not in_table:
            raise ValueError(f"{DOC.name}:{number} {match.group(1)}: 표 머리글(`| 코드 | …`) 아래에 있어야 한다")
        code = match.group(1)
        cells = [cell.strip() for cell in match.group(2).split("|")]
        if len(cells) != 4 or not all(cells):
            raise ValueError(f"{DOC.name}:{number} {code}: 언제·사용자 문구·하실 일·재시도 네 칸이 모두 있어야 한다")
        if code in seen:
            raise ValueError(f"{DOC.name}:{number} {code}: 오류 코드가 겹친다")
        if area is None:
            raise ValueError(f"{DOC.name}:{number} {code}: 절 제목(`## n. 이름`) 아래에 있어야 한다")
        try:
            parse_retry(cells[3])
        except ValueError as error:
            raise ValueError(f"{DOC.name}:{number} {code}: {error}") from None
        seen.add(code)
        rows.append((area, code, *cells))
    if fenced:
        raise ValueError(f"{DOC.name}: 코드 블록({fenced})이 닫히지 않았다")
    if not rows:
        raise ValueError(f"{DOC.name} 에서 오류 코드 행을 찾지 못했다")
    return rows


def render_source(rows):
    lines = [HEADER]
    for row in rows:
        lines.append("    (" + ", ".join(json.dumps(field, ensure_ascii=False) for field in row) + "),\n")
    lines.append(")\n")
    return "".join(lines)


def expected_source():
    return render_source(parse(DOC.read_text(encoding="utf-8")))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="파일을 쓰지 않고 문서와 같은지만 본다")
    args = parser.parse_args(argv)
    rows = parse(DOC.read_text(encoding="utf-8"))
    wanted = render_source(rows)
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    if args.check:
        if current != wanted:
            print("errors/catalog.py 가 docs/TROUBLESHOOTING.md 와 다르다 — `python scripts/sync_errors.py` 로 다시 만든다.", file=sys.stderr)
            return 1
        print("errors/catalog.py 가 문서와 같다.")
        return 0
    if current == wanted:
        print("바뀐 것이 없다.")
        return 0
    OUT.write_text(wanted, encoding="utf-8", newline="\n")
    shown = OUT.relative_to(ROOT) if ROOT in OUT.parents else OUT
    print(f"{shown} 를 다시 썼다({len(rows)}개 코드).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
