"""오류 코드·안내 문구(규칙 기반, AI 없이). 정본은 docs/TROUBLESHOOTING.md 이고 catalog.py 는 거기서 만든다."""
from .model import RETRY_AFTER, RETRY_AUTO, RETRY_KINDS, RETRY_NO, RETRY_OPTIONAL, ErrorInfo, parse_retry
from .render import AppError, Rendered, clean_slot, render
from .table import CATALOG, UNEXPECTED, lookup

__all__ = [
    "AppError", "CATALOG", "ErrorInfo", "RETRY_AFTER", "RETRY_AUTO", "RETRY_KINDS", "RETRY_NO", "RETRY_OPTIONAL",
    "Rendered", "UNEXPECTED", "clean_slot", "lookup", "parse_retry", "render",
]
