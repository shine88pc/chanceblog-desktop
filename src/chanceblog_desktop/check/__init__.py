"""발행 전 검사 — 앱 전용 검사(두 네이버 블로그 글이 너무 비슷한지 등). 핵심 코드의 검사(`pipeline/gates.py`)는 vendor 에 있다."""
from .similarity import Comparable, SimilarityReport, Thresholds, check_pair, compare

__all__ = ["Comparable", "SimilarityReport", "Thresholds", "check_pair", "compare"]
