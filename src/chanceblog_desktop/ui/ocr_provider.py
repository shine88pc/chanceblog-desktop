"""글자 읽기 작업자 공급자의 **운영 조립**(결정 D-513) — 추가 도구가 설치돼 있고 확인을 통과하고 `LOCAL_OCR` 가 켜졌을 때만 작업자 어댑터를 만든다. 하나라도 아니면 `None` 이고 화면에는 글자 읽기 칸이 붙지 않는다(사진 정리 창은 지금과 같다).
PySide6 를 모른다 — 사진을 읽고 줄이는 일(`prepare`)은 화면 쪽(`ui/qt/ocr_runner.py`)이 어댑터에 달아 준다. 작업자를 띄우는 일은 이 파일이 아니라 `ui/ocr_adapter.py`(`_launch` — 첫 줄이 `LOCAL_OCR` 관문)가 한다 — 이 파일에는 하위 프로세스·소켓이 없다.

`WorkerAdapter` 는 어댑터(`OcrAdapter`)를 건드리지 않고 화면이 필요로 하는 둘을 덧붙인다: ① `on_ready` — 작업자가 준비됐다는 소식(준비 중 → 읽는 중 표시)을 읽는 쪽 스레드에서 알린다
② `terminate` — 다른 스레드(화면의 시간 감시)가 락을 잡지 않고 작업자 프로세스 트리를 끈다(읽는 쪽이 EOF 로 알아차리고 정리한다). 둘 다 어댑터의 공개 메서드(`_ensure_started`)와 `kill_tree` 만 쓴다.
"""
from __future__ import annotations

import os
import sys

from .. import capabilities
from ..service import ocr_addon
from .ocr_adapter import OcrAdapter, kill_tree


class WorkerAdapter(OcrAdapter):
    """작업자 어댑터 + 준비 소식(`on_ready`)·즉시 종료(`terminate`). `on_ready` 는 읽는 쪽 스레드에서 불린다(작업자가 이미 떠 있어도 읽기마다 한 번)."""

    def __init__(self, *args, on_ready=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_ready = on_ready

    def _ensure_started(self):
        super()._ensure_started()
        if self.on_ready is not None:
            self.on_ready()

    def terminate(self):
        """락 없이 작업자 프로세스 트리를 끈다(다른 스레드에서 불러도 된다) — 이미 끝났으면 아무 일도 안 한다."""
        process = self.process
        if process is not None:
            kill_tree(process)


def app_folder():
    """앱 본체가 있는 폴더 — 묶음 실행 파일이면 실행 파일 옆, 개발 중이면 저장소 최상위. 추가 도구는 그 옆의 `ocr` 폴더다."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.abspath(__file__)
    for _ in range(4):                                                         # ui/ocr_provider.py → ui → chanceblog_desktop → src → 저장소 최상위
        here = os.path.dirname(here)
    return here


def default_provider(app_dir=None):
    """운영 공급자 — `LOCAL_OCR` 가 꺼져 있거나 추가 도구 폴더가 없거나 파일 목록·크기 확인(`verify`)을 통과하지 못하면 `None`. 띄우기 직전에는 어댑터가 해시까지 다시 본다(`verify_problem`)."""
    if not capabilities.local_ocr_enabled():
        return None
    folder = ocr_addon.addon_folder(app_dir if app_dir is not None else app_folder())
    try:
        usable = ocr_addon.verify(folder, check_files=False).ok
    except Exception:                                                          # 정보 파일이 깊게 중첩된 JSON 이면 RecursionError 가 샌다 — 선택 기능의 도구 폴더 하나가 앱 시작을 막지 않게 '쓸 수 없음' 으로 본다(독립 검증 S SP-3)
        return None
    if not usable:
        return None
    return WorkerAdapter(ocr_addon.worker_command(folder), verify=lambda: ocr_addon.verify_problem(folder), work_dir=folder)


__all__ = ["WorkerAdapter", "app_folder", "default_provider"]
