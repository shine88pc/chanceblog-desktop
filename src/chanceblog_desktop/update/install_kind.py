"""지금 앱이 어떤 설치 종류인지 가린다(UPDATE 설계서 3-8) — **파일이 있는지만** 본다(레지스트리·하위 프로세스·접속 0). 설치 도구 결정 전의 잠정 규칙이고 U-4 가 확정한다.

종류: `velopack`(실행 파일 폴더의 부모에 `Update.exe`, 그 폴더에 `sq.version`) · `inno`(실행 파일 폴더에 `unins000.exe`) · `portable`(묶음이지만 위 어느 것도 아님 — 압축을 풀어 쓰는 판) · `source`(묶음이 아님 — 소스 실행).
어떤 입력에도 예외를 내지 않고 모르면 적용하지 않는 쪽(`portable`/`source`)으로 닫는다.
"""
from __future__ import annotations

from pathlib import Path

VELOPACK_MARKERS = (("..", "Update.exe"), (".", "sq.version"))
INNO_MARKERS = ((".", "unins000.exe"),)


def detect(app_dir, *, frozen, exists=None):
    """`app_dir` 은 실행 파일이 있는 폴더, `frozen` 은 묶음 실행 여부, `exists` 는 시험이 바꿔 끼우는 파일 확인 함수."""
    if not frozen:
        return "source"
    check = exists if exists is not None else (lambda path: Path(path).is_file())
    try:
        base = Path(app_dir)
        if all(check(base / relative / name) for relative, name in VELOPACK_MARKERS):
            return "velopack"
        if all(check(base / relative / name) for relative, name in INNO_MARKERS):
            return "inno"
    except (OSError, TypeError, ValueError):
        return "portable"
    return "portable"


__all__ = ["INNO_MARKERS", "VELOPACK_MARKERS", "detect"]
