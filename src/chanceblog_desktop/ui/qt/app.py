"""PySide6 앱을 만들고 돌린다 — 화면 배율(High DPI)은 Qt6 가 알아서 처리하므로 여기서 배율을 곱하거나 고정하지 않는다."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ..core.app_state import report_unexpected
from ..core.text import T
from . import theme
from .shell import AppShell


def make_app(argv=None):
    """QApplication 하나(이미 있으면 그것)에 시스템 글꼴과 스타일시트를 입힌다."""
    app = QApplication.instance() or QApplication(list(argv) if argv else [sys.argv[0] if sys.argv else "chanceblog-desktop"])
    theme.apply(app)
    return app


def make_excepthook(window=None, stream=None):
    """처리하지 못한 예외(화면 슬롯·이벤트 처리 안에서 난 것 — PySide6 가 `sys.excepthook` 으로 넘긴다)를 받는 훅.
    추적(traceback)에는 경로와 값이 들어 있어 그대로 내지 않고 **한 줄**(예외 이름 + 비밀 모양을 가리고 경로를 지운 짧은 글)만 표준 오류에 남기며, 창이 있으면 쉬운 안내(토스트)를 보인다.
    Ctrl+C 는 그대로 둔다. 이 훅 안에서는 어떤 오류도 다시 내지 않는다."""
    def hook(kind, value, trace):
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, trace)
            return
        report_unexpected(kind, value, stream)
        try:
            if window is not None:
                window.notify(T["job_failed"])
        except Exception:                                                              # 창이 이미 닫혔으면 안내만 못 보인다 — 줄은 위에서 이미 남겼다
            pass
    return hook


def run(provider, argv=None):
    """창을 띄우고 이벤트 루프를 돈다(종료 코드를 돌려준다)."""
    app = make_app(argv)
    window = AppShell(provider)
    sys.excepthook = make_excepthook(window)
    window.show()
    return app.exec()
