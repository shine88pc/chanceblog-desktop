"""chanceblog 핵심 코드(vendor/pipeline)를 import 할 수 있게 한다.

`vendor/` 는 chanceblog 의 파일을 원본 그대로 가져온 것이라(scripts/sync_core.py, docs/ARCHITECTURE.md §4) 이 저장소에서 고치지 않는다.
앱은 시작할 때 `use_vendored_core()` 를 한 번 부르고, 그 뒤 `from pipeline import gates` 처럼 쓴다.
소스에서 실행할 때의 경로다. 설치본은 PyInstaller 가 `vendor/` 를 함께 묶는다(릴리스 묶음에서 다룬다).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def vendor_dir():
    return Path(__file__).resolve().parents[2] / "vendor"


def _cache_prefix():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "ChanceblogDesktop", "pycache")


def use_vendored_core():
    """vendor/ 를 import 경로 맨 앞에 올리고(이미 뒤쪽에 있어도 맨 앞으로 옮긴다) 그 경로를 돌려준다.

    같은 이름(`pipeline`)의 다른 코드가 이미 불려 와 있으면 가져온 코드와 다른 코드가 도는 것이라 RuntimeError 로 멈춘다.
    컴파일 캐시(.pyc)는 vendor/ 안이 아닌 사용자 폴더로 돌린다(`sys.pycache_prefix`) — 소스와 수정 시각·크기만 맞춰 만든 .pyc 가 소스 대신 실행되지 않고,
    vendor/ 안에는 캐시가 생기지 않는다(사용자가 이미 `PYTHONPYCACHEPREFIX` 로 정했으면 그대로 둔다).
    """
    if getattr(sys, "pycache_prefix", None) is None:
        sys.pycache_prefix = _cache_prefix()
    vendor = vendor_dir()
    path = str(vendor)
    if not sys.path or sys.path[0] != path:
        sys.path[:] = [path] + [entry for entry in sys.path if entry != path]
    loaded = sys.modules.get("pipeline")
    if loaded is not None:
        origin = getattr(loaded, "__file__", None)
        try:
            inside = origin is not None and vendor.resolve() in Path(origin).resolve().parents
        except OSError:
            inside = False
        if not inside:
            raise RuntimeError(f"vendor/ 가 아닌 곳의 pipeline 이 이미 불려 와 있다: {origin}")
    return path
