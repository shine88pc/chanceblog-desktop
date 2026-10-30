"""chanceblog 핵심 코드(vendor/pipeline)를 import 할 수 있게 한다.

`vendor/` 는 chanceblog 의 파일을 원본 그대로 가져온 것이라(scripts/sync_core.py, docs/ARCHITECTURE.md §4) 이 저장소에서 고치지 않는다.
앱은 시작할 때 `use_vendored_core()` 를 한 번 부르고, 그 뒤 `from pipeline import gates` 처럼 쓴다.
소스에서 실행할 때의 경로다. 설치본은 PyInstaller 가 `vendor/` 를 함께 묶는다(릴리스 묶음에서 다룬다).
"""
from __future__ import annotations

import sys
from pathlib import Path


def vendor_dir():
    return Path(__file__).resolve().parents[2] / "vendor"


def use_vendored_core():
    """vendor/ 를 import 경로 맨 앞에 한 번만 올리고 그 경로를 돌려준다."""
    path = str(vendor_dir())
    if path not in sys.path:
        sys.path.insert(0, path)
    return path
