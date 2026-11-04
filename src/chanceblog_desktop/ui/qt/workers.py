"""작업 스레드 ↔ 화면 스레드 다리 — `ui/core/jobs.py` 의 콜백은 작업 스레드에서 불리므로, Qt 시그널로 바꿔 화면 스레드에서 받는다(시그널은 스레드 사이에서 자동으로 줄 세워 전달된다)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class JobBridge(QObject):
    progress = Signal(float, str)
    loaded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()

    def callbacks(self):
        """`AppState.start_load` 에 넘길 콜백 — 모두 작업 스레드에서 불리고 시그널만 내보낸다(화면을 직접 건드리지 않는다)."""
        return {
            "on_progress": lambda fraction, text: self.progress.emit(float(fraction), str(text)),
            "on_done": lambda result, _payload: self.loaded.emit(result),
            "on_error": lambda failure, _payload: self.failed.emit(failure),
            "on_cancel": lambda _payload: self.cancelled.emit(),
        }
