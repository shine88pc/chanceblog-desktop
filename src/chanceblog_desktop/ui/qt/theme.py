"""Qt 테마 — 토큰(`ui/core/tokens.py`)으로 스타일시트(QSS)를 만들고, 글꼴(시스템 기본)·SVG 아이콘을 준비한다. 색·크기·글자 값을 여기서 새로 정하지 않는다.

- 글꼴: `QFontDatabase.systemFont()` — 일반 글자는 `GeneralFont`, 로그·경로·개발 정보만 `FixedFont`. **글꼴 이름을 코드에 쓰지 않는다**(Family 는 시스템을 따르고, 크기·굵기는 Typography Token).
- 배율: Qt6 의 High DPI 자동 처리를 그대로 쓴다. 논리 픽셀(px)만 쓰고 배율을 곱하거나 고정하지 않는다.
- 아이콘: SVG 를 `QSvgRenderer` 로 **그릴 때마다** 그려서(`SvgIconEngine`·`IconWidget`) 어느 배율·크기에서도 선명하다(그림 파일로 구워 두지 않는다).
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from ..core import icons, tokens as K

WEIGHTS = {400: QFont.Normal, 500: QFont.Medium, 600: QFont.DemiBold, 700: QFont.Bold}
_THEME = [K.DEFAULT_THEME]


def theme_name():
    return _THEME[0]


def colors():
    return K.palette(theme_name())


# ---- 글꼴 --------------------------------------------------------------------------------------------------------------------
_FONT_SOURCE = {"general": None, "fixed": None}


def use_font_source(general=None, fixed=None):
    """**화면 없는(offscreen) 점검·사진 도구 전용** — 이 Qt 는 운영체제의 글꼴을 몰라 시스템 글꼴을 'Sans Serif' 로 돌려주므로, 점검 도구가 윈도가 알려 준 시스템 글꼴을 대신 알려 줄 때만 쓴다.
    앱 코드(`ui/`)는 이 함수를 부르지 않는다 — 실제 앱은 늘 `QFontDatabase.systemFont()` 를 쓴다(시험이 지킨다)."""
    _FONT_SOURCE["general"], _FONT_SOURCE["fixed"] = general, fixed


def general_font():
    return _FONT_SOURCE["general"]() if _FONT_SOURCE["general"] else QFontDatabase.systemFont(QFontDatabase.GeneralFont)


def fixed_font():
    return _FONT_SOURCE["fixed"]() if _FONT_SOURCE["fixed"] else QFontDatabase.systemFont(QFontDatabase.FixedFont)


def font_for(role, fixed=False):
    """역할(Typography Token)의 글꼴 — 시스템 글꼴 Family 에 토큰의 크기·굵기를 얹는다."""
    style = K.type_style(role)
    font = QFont(fixed_font() if fixed else general_font())
    font.setPixelSize(style.size)
    font.setWeight(WEIGHTS[style.weight])
    return font


def app_font():
    return font_for("body")


# ---- 아이콘(SVG) ---------------------------------------------------------------------------------------------------------------
_RENDERERS = {}


def renderer(name, color):
    key = (name, color)
    if key not in _RENDERERS:
        _RENDERERS[key] = QSvgRenderer(QByteArray(icons.svg(name, 24, color).encode("utf-8")))
    return _RENDERERS[key]


class SvgIconEngine(QIconEngine):
    """요청된 크기·배율에 맞춰 SVG 를 그린다 — 상태(보통·눌림 `On`·꺼짐 `Disabled`)마다 색이 다르다."""

    def __init__(self, name, color, on_color=None, disabled_color=None):
        super().__init__()
        self._args = (name, color, on_color or color, disabled_color)

    def paint(self, painter, rect, mode, state):
        name, normal, on_color, disabled = self._args
        color = disabled if (mode == QIcon.Disabled and disabled) else (on_color if state == QIcon.On else normal)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        renderer(name, color).render(painter, QRectF(rect))
        painter.restore()

    def pixmap(self, size, mode, state):
        image = QPixmap(size)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        self.paint(painter, image.rect(), mode, state)
        painter.end()
        return image

    def clone(self):
        return SvgIconEngine(*self._args)


def icon(name, color, on_color=None, disabled_color=None):
    return QIcon(SvgIconEngine(name, color, on_color, disabled_color))


class IconWidget(QWidget):
    """아이콘 하나를 크기에 맞게 그리는 칸 — 이미지 파일이 아니라 SVG 를 그리므로 배율이 바뀌어도 선명하다."""

    def __init__(self, name, color, size):
        super().__init__()
        self._name, self._color = name, color
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_icon(self, name, color=None):
        self._name, self._color = name, color or self._color
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer(self._name, self._color).render(painter, QRectF(self.rect()))


# ---- 스타일시트 ----------------------------------------------------------------------------------------------------------------
def _roles(c):
    lines = []
    for role in K.ROLE_TEXT:
        style = K.type_style(role)
        lines.append(f'QLabel[role="{role}"] {{ font-size: {style.size}px; font-weight: {style.weight}; color: {K.role_color(c, role)}; }}')
    return "\n".join(lines)


def _tones(c):
    return "\n".join(f'QLabel[tone="{name}"] {{ color: {c[keys[2]]}; }}' for name, keys in K.TONES.items())


def build_qss(c):
    """토큰의 색 사전 `c` 로 앱 전체 스타일시트를 만든다. 색은 모두 `c` 에서만 온다(여기에 `#rrggbb` 를 쓰지 않는다 — 시험이 지킨다)."""
    r, S, ty = K.RADIUS, K.SIZE, K.TYPE
    px = lambda name: ty[name].size                                           # noqa: E731
    chip_r = S["chip_h"] // 2
    scrim = K.rgba(c["scrim"], K.SCRIM_ALPHA)
    return f"""
QMainWindow, QWidget#root {{ background: {c['bg_app']}; }}
QWidget {{ background: transparent; color: {c['text_primary']}; }}
QToolTip {{ background: {c['inverse_bg']}; color: {c['inverse_text']}; border: 0; padding: 8px 12px; border-radius: {r['tooltip']}px; font-size: {px('small')}px; }}
{_roles(c)}
{_tones(c)}
QLabel[role="ok"] {{ color: {c['success_text']}; font-weight: 600; }}
QLabel#brandname {{ font-size: {px('h1')}px; font-weight: 700; color: {c['text_strong']}; }}
QFrame#topbar {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
QFrame#sidebar {{ background: {c['bg_sidebar']}; border-right: 1px solid {c['border']}; }}
QFrame#brandcard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['card']}px; }}
QFrame[card="true"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['card']}px; }}
QFrame[card="true"]:focus {{ border: 2px solid {c['border_focus']}; }}
QFrame[card="warm"] {{ background: {c['success_100']}; border: 1px solid {c['border']}; border-radius: {r['card']}px; }}
QFrame[card="plain"] {{ background: {c['surface_2']}; border: 1px solid {c['border']}; border-radius: {r['badge']}px; }}
QPushButton {{ font-size: {px('button')}px; font-weight: {ty['button'].weight}; outline: none; }}
QPushButton[nav="true"] {{ background: transparent; border: 2px solid transparent; border-radius: {r['button']}px; text-align: left; padding: 0 12px; color: {c['text_secondary']}; font-weight: 600; }}
QPushButton[nav="true"]:hover {{ background: {c['surface_hover']}; }}
QPushButton[nav="true"]:checked {{ background: {c['primary_100']}; color: {c['primary_text']}; }}
QPushButton[nav="true"]:focus {{ border: 2px solid {c['border_focus']}; }}
QPushButton[kind="secondary"] {{ background: {c['surface']}; color: {c['text_primary']}; border: 1px solid {c['border_strong']}; border-radius: {r['button']}px; padding: 0 16px; }}
QPushButton[kind="secondary"]:hover {{ background: {c['surface_hover']}; border-color: {c['primary']}; }}
QPushButton[kind="secondary"]:pressed {{ background: {c['primary_100']}; }}
QPushButton[kind="primary"] {{ background: {c['primary']}; color: {c['on_primary']}; border: 1px solid {c['primary']}; border-radius: {r['button']}px; padding: 0 20px; }}
QPushButton[kind="primary"]:hover, QPushButton[kind="primary"]:pressed {{ background: {c['primary_600']}; border-color: {c['primary_600']}; }}
QPushButton[kind="primary"]:focus, QPushButton[kind="danger"]:focus {{ border: 2px solid {c['inverse_bg']}; }}
QPushButton[kind="ghost"] {{ background: transparent; color: {c['primary_text']}; border: 1px solid transparent; border-radius: {r['button']}px; padding: 0 12px; }}
QPushButton[kind="ghost"]:hover {{ background: {c['primary_100']}; }}
QPushButton[kind="danger"] {{ background: {c['danger']}; color: {c['on_primary']}; border: 1px solid {c['danger']}; border-radius: {r['button']}px; padding: 0 20px; }}
QPushButton[kind="danger"]:hover, QPushButton[kind="danger"]:pressed {{ background: {c['danger_text']}; border-color: {c['danger_text']}; }}
QPushButton[kind="icon"] {{ background: transparent; border: 1px solid transparent; border-radius: {r['button']}px; padding: 0; }}
QPushButton[kind="icon"]:hover {{ background: {c['surface_hover']}; }}
QPushButton[size="sm"] {{ margin: 1px 0; padding: 0 14px; }}
QPushButton[copied="true"] {{ background: {c['success_100']}; border: 1px solid {c['success']}; color: {c['success_text']}; }}
QPushButton:focus {{ border: 2px solid {c['border_focus']}; }}
QPushButton:disabled {{ background: {c['disabled_bg']}; border-color: {c['disabled_bg']}; color: {c['text_disabled']}; }}
QPushButton[kind="icon"]:disabled {{ background: transparent; border-color: transparent; }}
QPushButton[chip="true"] {{ background: {c['surface_2']}; color: {c['text_secondary']}; border: 1px solid {c['border']}; border-radius: {chip_r}px; padding: 0 14px; margin: 1px 0; font-weight: 600; }}
QPushButton[chip="true"]:hover {{ background: {c['surface_hover']}; border-color: {c['border_strong']}; }}
QPushButton[chip="true"]:checked {{ background: {c['primary']}; border-color: {c['primary']}; color: {c['on_primary']}; }}
QPushButton[chip="true"]:focus {{ border: 2px solid {c['border_focus']}; }}
QPushButton[chip="true"]:checked:focus {{ border: 2px solid {c['inverse_bg']}; }}
QFrame[quick] {{ background: {c['surface_2']}; border: 1px solid {c['border']}; border-radius: {r['badge']}px; }}
QFrame[quick]:hover {{ background: {c['surface_hover']}; border-color: {c['border_strong']}; }}
QFrame[quick="primary"] {{ background: {c['primary']}; border-color: {c['primary']}; }}
QFrame[quick="primary"]:hover {{ background: {c['primary_600']}; }}
QFrame[quick]:focus {{ border: 2px solid {c['border_focus']}; }}
QFrame[quick="primary"]:focus {{ border: 2px solid {c['inverse_bg']}; }}
QFrame[quick="primary"] QLabel {{ color: {c['on_primary']}; }}
QPushButton[acc="true"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['badge']}px; text-align: left; padding: 8px 14px; font-weight: 600; }}
QPushButton[acc="true"]:hover {{ background: {c['surface_hover']}; }}
QPushButton[link="true"] {{ background: transparent; border: 1px solid transparent; padding: 0 4px; color: {c['primary_text']}; text-decoration: underline; }}
QPushButton[link="true"]:focus {{ border: 2px solid {c['border_focus']}; }}
QLabel[badge] {{ border-radius: {r['badge']}px; padding: 0 10px; font-size: {px('caption')}px; font-weight: 700; }}
QLabel[badge="a"] {{ background: {c['blog_a_bg']}; color: {c['blog_a_text']}; }}
QLabel[badge="b"] {{ background: {c['blog_b_bg']}; color: {c['blog_b_text']}; }}
QLabel[badge="ok"] {{ background: {c['success_100']}; color: {c['success_text']}; }}
QLabel[badge="info"] {{ background: {c['primary_100']}; color: {c['primary_text']}; }}
QLabel[badge="muted"] {{ background: {c['surface_2']}; color: {c['text_secondary']}; border: 1px solid {c['border']}; }}
QPushButton[badge="warning"] {{ background: {c['warning_100']}; color: {c['warning_text']}; border: 1px solid transparent; border-radius: {r['badge']}px; padding: 0 10px; font-size: {px('caption')}px; font-weight: 700; }}
QPushButton[badge="warning"]:hover {{ border-color: {c['warning']}; }}
QPushButton[badge="warning"]:focus {{ border: 2px solid {c['border_focus']}; }}
QLabel[kw="true"] {{ background: {c['surface_2']}; border: 1px solid {c['border']}; color: {c['text_secondary']}; border-radius: {r['badge']}px; padding: 0 10px; font-size: {px('caption')}px; }}
QLabel[trend="up"] {{ color: {c['success_text']}; font-weight: 600; }}
QLabel[trend="flat"] {{ color: {c['warning_text']}; font-weight: 600; }}
QLabel[trend="down"] {{ color: {c['danger_text']}; font-weight: 600; }}
QLabel[trend="none"] {{ color: {c['text_muted']}; }}
QFrame#row {{ background: {c['surface']}; border: 1.5px solid transparent; border-radius: {r['row']}px; }}
QFrame#row:hover {{ background: {c['surface_hover']}; }}
QFrame#row[selected="true"] {{ background: {c['surface_selected']}; border: 1.5px solid {c['primary']}; }}
QFrame#row[bordered="true"] {{ border: 1px solid {c['border']}; }}
QFrame#row:focus {{ border: 2px solid {c['border_focus']}; }}
QFrame#banner {{ background: {c['warning_100']}; border-radius: {r['badge']}px; }}
QFrame#banner QLabel {{ color: {c['warning_text']}; font-weight: 600; }}
QFrame#skel, QWidget#skel {{ background: {c['surface_2']}; border: 1px solid {c['border']}; border-radius: 8px; }}
QFrame#drawer {{ background: {c['surface']}; border-left: 1px solid {c['border']}; }}
QFrame#dhead {{ border-bottom: 1px solid {c['border']}; }}
QFrame#dfoot {{ border-top: 1px solid {c['border']}; }}
QWidget#scrim {{ background: {scrim}; }}
QFrame#dialog {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['card']}px; }}
QLineEdit {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: {r['input']}px; padding: 0 12px; selection-background-color: {c['primary']}; selection-color: {c['on_primary']}; }}
QLineEdit:focus {{ border: 2px solid {c['border_focus']}; }}
QLineEdit:disabled {{ background: {c['disabled_bg']}; color: {c['text_disabled']}; }}
QLabel#toast {{ background: {c['inverse_bg']}; color: {c['inverse_text']}; padding: 12px 18px; border-radius: {r['button']}px; font-weight: 600; font-size: {px('body')}px; }}
QPlainTextEdit[mono="true"], QLabel[mono="true"] {{ background: {c['surface_2']}; border: 1px solid {c['border']}; border-radius: {r['badge']}px; padding: 10px 12px; color: {c['text_primary']}; }}
QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border_strong']}; border-radius: 4px; min-height: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; width: 0; background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 4px; min-width: 36px; }}
"""


def apply(app, name=K.DEFAULT_THEME):
    """앱 전체에 글꼴과 스타일시트를 입힌다 — 화면 배율은 건드리지 않는다(Qt6 가 처리)."""
    _THEME[0] = name
    app.setFont(app_font())
    app.setStyleSheet(build_qss(colors()))


def text_color(role):
    return QColor(K.role_color(colors(), role))
