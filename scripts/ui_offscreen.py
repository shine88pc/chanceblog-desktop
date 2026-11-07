"""화면 없는(offscreen) 점검의 공통 준비 — 사진 도구(`ui_capture.py`)와 시험이 같이 쓴다. 창이 화면에 뜨지 않는다(`QT_QPA_PLATFORM=offscreen`).

이 Qt 의 offscreen 은 운영체제 글꼴을 몰라 시스템 글꼴을 'Sans Serif' 로 돌려주고 한글 글꼴도 못 찾으므로(없으면 한글이 네모/엉뚱한 글꼴), 이 도구에서만:
  · `QT_QPA_FONTDIR` 로 윈도 글꼴 폴더를 알려 주고,
  · 윈도가 알려 준 **시스템 글꼴(`SystemParametersInfo` 의 메시지 글꼴 — 한국어 윈도는 '맑은 고딕')** 을 `theme.use_font_source` 로 대신 건넨다(앱 코드는 이것을 쓰지 않는다 — 실제 앱은 `QFontDatabase.systemFont()` 를 그대로 쓴다).
화면 배율 흉내(`QT_SCALE_FACTOR`·`QT_FONT_DPI`)는 프로세스가 시작될 때 환경 변수로 정해야 하므로 이 모듈을 불러오기 전에(또는 자식 프로세스에) 둔다 — 앱 코드에는 넣지 않는다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FALLBACK_FAMILIES = ("Segoe UI", "Malgun Gothic")


def prepare_environment():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def windows_message_font():
    """윈도의 시스템 메시지 글꼴 이름(예: 맑은 고딕). 윈도가 아니거나 못 읽으면 None."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class LOGFONTW(ctypes.Structure):
        _fields_ = [("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG), ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG), ("lfWeight", wintypes.LONG),
                    ("lfItalic", wintypes.BYTE), ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE), ("lfCharSet", wintypes.BYTE), ("lfOutPrecision", wintypes.BYTE),
                    ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE), ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", ctypes.c_wchar * 32)]

    class NONCLIENTMETRICSW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("iBorderWidth", ctypes.c_int), ("iScrollWidth", ctypes.c_int), ("iScrollHeight", ctypes.c_int), ("iCaptionWidth", ctypes.c_int),
                    ("iCaptionHeight", ctypes.c_int), ("lfCaptionFont", LOGFONTW), ("iSmCaptionWidth", ctypes.c_int), ("iSmCaptionHeight", ctypes.c_int), ("lfSmCaptionFont", LOGFONTW),
                    ("iMenuWidth", ctypes.c_int), ("iMenuHeight", ctypes.c_int), ("lfMenuFont", LOGFONTW), ("lfStatusFont", LOGFONTW), ("lfMessageFont", LOGFONTW),
                    ("iPaddedBorderWidth", ctypes.c_int)]

    metrics = NONCLIENTMETRICSW()
    metrics.cbSize = ctypes.sizeof(NONCLIENTMETRICSW)
    if not ctypes.windll.user32.SystemParametersInfoW(41, metrics.cbSize, ctypes.byref(metrics), 0):      # SPI_GETNONCLIENTMETRICS
        return None
    return metrics.lfMessageFont.lfFaceName or None


def install_system_fonts():
    """offscreen 에서 윈도 시스템 글꼴을 흉내 낸다(사진·점검 전용). 돌려주는 값: (일반 글꼴 이름, 고정폭 글꼴 이름)."""
    from PySide6.QtGui import QFont
    from chanceblog_desktop.ui.qt import theme
    general = windows_message_font() or FALLBACK_FAMILIES[0]
    fixed = "Courier New"                                  # Qt 의 윈도 테마가 FixedFont 로 쓰는 글꼴
    theme.use_font_source(lambda: QFont([general, *FALLBACK_FAMILIES]), lambda: QFont([fixed, general]))
    return general, fixed


def find_clipping(window):
    """화면에 보이는 글자가 잘리는 곳을 찾는다(125%·150% 점검용) — 한 줄 글이 칸보다 길거나, 줄바꿈 글이 필요한 높이보다 낮은 칸, 단추 글자가 단추보다 긴 곳, 누르는 칸이 36px 보다 낮은 단추.
    일부러 줄임표(…)로 줄이는 `ElidedLabel` 은 뺀다. 돌려주는 값: 의심되는 곳의 설명 목록(비어 있으면 잘림 없음)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QLabel
    from chanceblog_desktop.ui.qt.components import ElidedLabel
    found = []
    for widget in window.findChildren(QLabel):
        if not widget.isVisible() or isinstance(widget, ElidedLabel) or not widget.text():
            continue
        if widget.wordWrap():
            need = widget.heightForWidth(widget.width())
            if need > widget.height() + 1:
                found.append(f"줄바꿈 글이 잘림(필요 {need}px > {widget.height()}px): {widget.accessibleName() or widget.text()[:30]!r}")
        elif widget.textFormat() != Qt.RichText:                             # 한 줄 평문만 길이를 잰다
            shown = widget.text()
            need = widget.fontMetrics().horizontalAdvance(shown)
            if need > widget.width():
                found.append(f"한 줄 글이 칸보다 김({need}px > {widget.width()}px): {shown[:30]!r}")
    for button in window.findChildren(QAbstractButton):
        if not button.isVisible():
            continue
        if button.text().strip():
            icon_width = button.iconSize().width() + 8 if not button.icon().isNull() else 0
            if button.fontMetrics().horizontalAdvance(button.text().strip()) + icon_width > button.width():
                found.append(f"단추 글자가 단추보다 김: {button.text().strip()[:30]!r}")
        if button.height() < 36:
            found.append(f"누르는 칸이 36px 보다 낮음({button.height()}px): {button.accessibleName()[:30]!r}")
    return found


def settle(app, times=6, pause=0.02):
    import time
    for _ in range(times):
        app.processEvents()
        time.sleep(pause)


def wait_until(app, condition, seconds=10):
    import time
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def find_squeezed(root):
    """바깥 칸이 안에 든 부품의 필요 높이·폭을 무시하고 더 작게 잡혀 부품이 반쯤 잘리는 곳을 찾는다(P4b — 배지·단추·글이 부모 칸 밖으로 삐져나온 채 잘린다).
    `find_clipping` 은 글 한 줄의 폭·줄바꿈 글의 높이·단추 글자 폭만 재서 이런 것은 못 본다. 보이는 글·단추·배지의 위치가 부모의 안쪽 영역을 1px 넘게 벗어났으면 그 설명을 돌려준다(없으면 빈 목록).
    스크롤 안쪽의 내용 칸 자체는 부모(보이는 창)보다 클 수 있으므로 글·단추만 본다."""
    from PySide6.QtWidgets import QAbstractButton, QLabel
    found = []
    for widget in root.findChildren(QLabel) + root.findChildren(QAbstractButton):
        parent = widget.parentWidget()
        if parent is None or not widget.isVisible() or not parent.isVisible():
            continue
        geometry, inner = widget.geometry(), parent.rect()
        if geometry.bottom() > inner.bottom() + 1 or geometry.right() > inner.right() + 1 or geometry.top() < inner.top() - 1 or geometry.left() < inner.left() - 1:
            name = widget.accessibleName() or (widget.text() if hasattr(widget, "text") else "") or type(widget).__name__
            found.append(f"부모 칸 밖으로 삐져나옴({geometry.x()},{geometry.y()} {geometry.width()}x{geometry.height()} > {inner.width()}x{inner.height()}): {name[:30]!r}")
    return found
