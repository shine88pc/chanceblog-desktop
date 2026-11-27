"""지금 앱이 어떤 설치 종류인지 가린다(UPDATE 설계서 3-8) — **파일이 있는지만** 본다(레지스트리·하위 프로세스·접속 0).

종류: `inno`(실행 파일 폴더에 `unins000.exe` — Inno Setup 이 깐 앱) · `portable`(묶음이지만 위 표식이 없음 — 압축을 풀어 쓰는 판) · `source`(묶음이 아님 — 소스 실행).
설치 도구는 Inno Setup 으로 정해졌다(결정 D-811) — 예전의 Velopack 감지(`Update.exe`·`sq.version`)는 지웠다: 그 표식이 있어도 설치형이 아니라 휴대용으로 닫힌다(모르면 적용하지 않는 쪽).
어떤 입력에도 예외를 내지 않고 모르면 적용하지 않는 쪽(`portable`/`source`)으로 닫는다.
"""
from __future__ import annotations

from pathlib import Path

INNO_MARKERS = ((".", "unins000.exe"),)


def detect(app_dir, *, frozen, exists=None):
    """`app_dir` 은 실행 파일이 있는 폴더, `frozen` 은 묶음 실행 여부, `exists` 는 시험이 바꿔 끼우는 파일 확인 함수."""
    if not frozen:
        return "source"
    check = exists if exists is not None else (lambda path: Path(path).is_file())
    try:
        base = Path(app_dir)
        if all(check(base / relative / name) for relative, name in INNO_MARKERS):
            return "inno"
    except (OSError, TypeError, ValueError):
        return "portable"
    return "portable"


__all__ = ["INNO_MARKERS", "detect"]
