"""글자 읽기 추가 도구 빌드 시험 도우미(시험이 아니다) — `ocr_addon/` 의 빌드 쪽 파일(`build_rules`·`fetch_models`·`build_ocr_addon`)을 파일 경로로 불러온다(결정 D-528).

`ocr_addon/` 은 앱 묶음 밖 폴더라 import 경로에 없다. 이 도우미는 불러오는 동안에만 그 폴더를 `sys.path` 맨 앞에 두고(형제 파일 가져오기용) 곧 뺀다 — `protocol`·`netguard` 같은 흔한 이름이
다른 시험에 새지 않게, 형제 가져오기가 남긴 `build_rules` 이름도 `sys.modules` 에서 치운다. 시험은 표준 라이브러리만 쓰고 pefile·PyInstaller 없이 돈다(있을 때만 도는 시험은 건너뛰기 표시).
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "ocr_addon"
_LOADED = {}


def load(name):
    """`ocr_addon/<name>.py` 를 한 번만 불러와 돌려준다(모듈 이름은 `ocr_addon_<name>`)."""
    if name not in _LOADED:
        sys.path.insert(0, str(ADDON))
        try:
            spec = importlib.util.spec_from_file_location("ocr_addon_" + name, str(ADDON / (name + ".py")))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(ADDON))
            sys.modules.pop("build_rules", None)
        _LOADED[name] = module
    return _LOADED[name]


def read(rel):
    """저장소 안 글 파일을 줄 끝(CRLF·LF)과 상관없이 읽는다."""
    return (ROOT / rel).read_text(encoding="utf-8")
