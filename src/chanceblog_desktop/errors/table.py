"""오류 코드 표 — `catalog.ROWS`(문서에서 만든 자료)를 `ErrorInfo` 로 바꿔 코드로 찾게 한다."""
from __future__ import annotations

from types import MappingProxyType

from .catalog import ROWS
from .model import ErrorInfo, parse_retry

UNEXPECTED = "UNEXPECTED_ERROR"   # 어느 코드에도 해당하지 않는 실패의 마지막 칸


def _build():
    table = {}
    for area, code, when, message, action, retry in ROWS:
        if code in table:
            raise ValueError(f"오류 코드가 겹친다: {code}")
        kind, maximum = parse_retry(retry)
        table[code] = ErrorInfo(code, area, when, message, action, retry, kind, maximum)
    if UNEXPECTED not in table:
        raise ValueError(f"{UNEXPECTED} 행이 docs/TROUBLESHOOTING.md 에 없다")
    return MappingProxyType(table)


CATALOG = _build()


def lookup(code):
    """코드 → ErrorInfo. 모르는 코드는 UNEXPECTED_ERROR 로 받는다(실패를 안내하다 또 실패하지 않게)."""
    return CATALOG.get(code) or CATALOG[UNEXPECTED]
