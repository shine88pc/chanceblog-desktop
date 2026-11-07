"""Qt 테마 — 토큰(`ui/core/tokens.py`)으로 스타일시트(QSS)를 만들고, 글꼴(시스템 기본)·SVG 아이콘을 준비한다. 색·크기·글자 값을 여기서 새로 정하지 않는다.

- 글꼴: `QFontDatabase.systemFont()` — 일반 글자는 `GeneralFont`, 로그·경로·개발 정보만 `FixedFont`. **글꼴 이름을 코드에 쓰지 않는다**(Family 는 시스템을 따르고, 크기·굵기는 Typography Token).
- 배율: Qt6 의 High DPI 자동 처리를 그대로 쓴다. 논리 픽셀(px)만 쓰고 배율을 곱하거나 고정하지 않는다.
- 아이콘: SVG 를 `QSvgRenderer` 로 **그릴 때마다** 그려서(`SvgIconEngine`·`IconWidget`) 어느 배율·크기에서도 선명하다(그림 파일로 구워 두지 않는다).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from ..core import gauges, icons, tokens as K

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


def _semantic(c):
    """의미별 배지 11종 — 배경·글자 쌍은 토큰(`badge_<종류>_bg/_text`)에서만 온다."""
    return "\n".join(f'QLabel[semantic="{kind}"] {{ background: {c[f"badge_{kind}_bg"]}; color: {c[f"badge_{kind}_text"]}; }}' for kind in K.BADGE_KINDS)


def _scores(c):
    """점수 구간 이름(우선 추천·일반 후보·보류·제외)과 변화량(상승·하락·변화 없음)의 글자 색 — 색과 함께 늘 글자가 있다."""
    bands = "\n".join(f'QLabel[scoreband="{band.key}"] {{ color: {c[band.text_key]}; font-weight: 600; }}' for band in gauges.BANDS)
    deltas = "\n".join(f'QLabel[delta="{kind}"] {{ color: {c[key]}; font-weight: 600; }}' for kind, key in (("up", "success_text"), ("down", "danger_text"), ("flat", "text_secondary")))
    return bands + "\n" + deltas


def _card_states(c):
    """카드 3상태(기본·가리킴·선택) — 기본은 `QFrame[card="true"]` 자체이고, 상태는 `cardstate` 속성으로 테두리 두께·색만 바꾼다(`K.CARD_STATES`). 그림자는 `shadow_effect` 가 입힌다.
    **포커스는 상태보다 위다**(UI-C1d, D-200 — 독립 검증 UI-C0 의 M2): 상태 규칙(`[card][cardstate]`)은 기본 포커스 규칙(`[card]:focus`)과 구체성이 같고 뒤에 나와 이겨서, 가리킬 때 포커스를 받은 카드가 가리킴 테두리(1px)로 남아
    키보드 사용자가 포커스를 못 봤다. 그래서 상태마다 `[card][cardstate]:focus` 규칙(구체성이 더 높다)을 상태 규칙 뒤에 더해 어느 상태든 포커스를 받으면 2px 포커스 테두리가 보인다(선택됨은 선택 색과 포커스 색이 같아 테두리가 그대로 2px 파랑이다)."""
    states = [(state, width, color_key) for state, (width, color_key, _shadow) in K.CARD_STATES.items() if state != "default"]
    rules = [f'QFrame[card="true"][cardstate="{state}"] {{ border: {width}px solid {c[color_key]}; }}' for state, width, color_key in states]
    rules += [f'QFrame[card="true"][cardstate="{state}"]:focus {{ border: {K.FOCUS_RING_PX}px solid {c["border_focus"]}; }}' for state, _width, _color_key in states]
    return "\n".join(rules)


def build_qss(c):
    """토큰의 색 사전 `c` 로 앱 전체 스타일시트를 만든다. 색은 모두 `c` 에서만 온다(여기에 `#rrggbb` 를 쓰지 않는다 — 시험이 지킨다)."""
    r, S, ty = K.RADIUS, K.SIZE, K.TYPE
    px = lambda name: ty[name].size                                           # noqa: E731
    sp = lambda name: K.SPACE[name]                                           # noqa: E731
    chip_r = S["chip_h"] // 2
    scrim = K.rgba(c["scrim"], K.SCRIM_ALPHA)
    return f"""
QMainWindow, QWidget#root {{ background: {c['bg_app']}; }}
QWidget {{ background: transparent; color: {c['text_primary']}; }}
QToolTip {{ background: {c['inverse_bg']}; color: {c['inverse_text']}; border: 0; padding: 8px 12px; border-radius: {r['tooltip']}px; font-size: {px('small')}px; }}
{_roles(c)}
{_tones(c)}
QLabel[role="ok"] {{ color: {c['success_text']}; font-weight: 600; }}
QFrame#topbar {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
QFrame#sidebar {{ background: {c['bg_sidebar']}; border-right: 1px solid {c['sidebar_border']}; }}
QLabel[soon="true"] {{ color: {c['soon_text']}; }}
QFrame#brandcard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['card']}px; }}
QFrame[card="true"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['card']}px; }}
QFrame[card="true"]:focus {{ border: {K.FOCUS_RING_PX}px solid {c['border_focus']}; }}
{_card_states(c)}
QFrame[card="warm"] {{ background: {c['success_100']}; border: 1px solid {c['border']}; border-radius: {r['card']}px; }}
QFrame[card="plain"] {{ background: {c['surface_2']}; border: 1px solid {c['border']}; border-radius: {r['badge']}px; }}
QFrame[card="quiet"] {{ background: {c['disabled_bg']}; border: 1px solid {c['border']}; border-radius: {r['badge']}px; }}
QPushButton {{ font-size: {px('button')}px; font-weight: {ty['button'].weight}; outline: none; }}
QPushButton[nav="true"] {{ background: transparent; border: 2px solid transparent; border-radius: {r['nav']}px; text-align: left; padding: 0 12px; color: {c['text_secondary']}; font-weight: 600; }}
QPushButton[nav="true"]:hover {{ background: {c['surface_hover']}; }}
QPushButton[nav="true"]:checked {{ background: {c['nav_current_bg']}; color: {c['nav_current_text']}; }}
QPushButton[nav="true"]:focus {{ border: 2px solid {c['border_focus']}; }}
QPushButton[kind="secondary"] {{ background: {c['surface']}; color: {c['secondary_text']}; border: 1px solid {c['secondary_border']}; border-radius: {r['button']}px; padding: 0 16px; }}
QPushButton[kind="secondary"]:hover {{ background: {c['surface_hover']}; border-color: {c['primary']}; }}
QPushButton[kind="secondary"]:pressed {{ background: {c['primary_100']}; }}
QPushButton[kind="primary"] {{ background: {c['primary']}; color: {c['on_primary']}; border: 1px solid {c['primary']}; border-radius: {r['button']}px; padding: 0 20px; }}
QPushButton[kind="primary"]:hover {{ background: {c['primary_700']}; border-color: {c['primary_700']}; }}
QPushButton[kind="primary"]:pressed {{ background: {c['primary_pressed']}; border-color: {c['primary_pressed']}; }}
QPushButton[kind="primary"]:focus, QPushButton[kind="danger"]:focus {{ border: {K.FOCUS_RING_PX}px solid {c['inverse_bg']}; }}
QPushButton[kind="ghost"] {{ background: transparent; color: {c['primary_text']}; border: 1px solid transparent; border-radius: {r['button']}px; padding: 0 12px; }}
QPushButton[kind="ghost"]:hover {{ background: {c['primary_100']}; }}
QPushButton[kind="danger"] {{ background: {c['danger_fill']}; color: {c['on_primary']}; border: 1px solid {c['danger_fill']}; border-radius: {r['button']}px; padding: 0 20px; }}
QPushButton[kind="danger"]:hover, QPushButton[kind="danger"]:pressed {{ background: {c['danger_text']}; border-color: {c['danger_text']}; }}
QPushButton[kind="danger_ghost"] {{ background: transparent; color: {c['danger_text']}; border: 1px solid transparent; border-radius: {r['button']}px; padding: 0 12px; }}
QPushButton[kind="danger_ghost"]:hover {{ background: {c['danger_100']}; }}
QPushButton[kind="icon"] {{ background: transparent; border: 1px solid transparent; border-radius: {r['button']}px; padding: 0; }}
QPushButton[kind="icon"]:hover {{ background: {c['surface_hover']}; }}
QPushButton[size="sm"] {{ margin: 1px 0; padding: 0 14px; }}
QPushButton[copied="true"] {{ background: {c['success_100']}; border: 1px solid {c['success']}; color: {c['success_text']}; }}
QPushButton:focus {{ border: 2px solid {c['border_focus']}; }}
QPushButton:disabled {{ background: {c['disabled_bg']}; border-color: {c['disabled_bg']}; color: {c['text_disabled']}; }}
QPushButton[kind="icon"]:disabled {{ background: transparent; border-color: transparent; }}
QPushButton[kind="primary"]:disabled, QPushButton[kind="danger"]:disabled {{ background: {c['disabled_fill']}; border-color: {c['disabled_fill']}; color: {c['on_primary']}; }}
QPushButton[chip="true"] {{ background: {c['surface_2']}; color: {c['text_secondary']}; border: 1px solid {c['border']}; border-radius: {chip_r}px; padding: 0 14px; margin: 1px 0; font-weight: 600; }}
QPushButton[chip="true"]:hover {{ background: {c['surface_hover']}; border-color: {c['border_strong']}; }}
QPushButton[chip="true"]:checked {{ background: {c['primary']}; border-color: {c['primary']}; color: {c['on_primary']}; }}
QPushButton[chip="true"]:focus {{ border: 2px solid {c['border_focus']}; }}
QPushButton[chip="true"]:checked:focus {{ border: 2px solid {c['inverse_bg']}; }}
QFrame[quick] {{ background: {c['surface_2']}; border: 1px solid {c['border']}; border-radius: {r['badge']}px; }}
QFrame[quick]:hover {{ background: {c['surface_hover']}; border-color: {c['border_strong']}; }}
QFrame[quick="primary"] {{ background: {c['primary']}; border-color: {c['primary']}; }}
QFrame[quick="primary"]:hover {{ background: {c['primary_700']}; }}
QFrame[quick]:focus {{ border: 2px solid {c['border_focus']}; }}
QFrame[quick="primary"]:focus {{ border: 2px solid {c['inverse_bg']}; }}
QFrame[quick="primary"] QLabel {{ color: {c['on_primary']}; }}
QPushButton[acc="true"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['badge']}px; text-align: left; padding: 8px 14px; font-size: {px('h2')}px; font-weight: {ty['h2'].weight}; color: {c['text_strong']}; }}
QPushButton[acc="true"]:hover {{ background: {c['surface_hover']}; }}
QPushButton[acc="true"]:focus {{ border: 2px solid {c['border_focus']}; }}
QPushButton[link="true"] {{ background: transparent; border: 1px solid transparent; padding: 0 4px; color: {c['primary_text']}; text-decoration: underline; }}
QPushButton[link="true"]:focus {{ border: 2px solid {c['border_focus']}; }}
QLabel[badge] {{ border-radius: {r['badge']}px; padding: 0 10px; font-size: {px('caption')}px; font-weight: 700; }}
QLabel[badge="a"] {{ background: {c['blog_a_bg']}; color: {c['blog_a_text']}; }}
QLabel[badge="b"] {{ background: {c['blog_b_bg']}; color: {c['blog_b_text']}; }}
QLabel[badge="ok"] {{ background: {c['success_100']}; color: {c['success_text']}; }}
QLabel[badge="warning"] {{ background: {c['warning_100']}; color: {c['warning_text']}; }}
QLabel[badge="danger"] {{ background: {c['danger_100']}; color: {c['danger_text']}; }}
QLabel[badge="info"] {{ background: {c['info_100']}; color: {c['info_text']}; }}
QLabel[badge="muted"] {{ background: {c['surface_2']}; color: {c['text_secondary']}; border: 1px solid {c['border']}; }}
QLabel[badge][compact="true"] {{ padding: 0 {sp('2')}px; font-size: {px('micro')}px; }}
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
QLabel[semantic] {{ border-radius: {r['badge']}px; padding: 0 {sp('3')}px; font-size: {px('caption')}px; font-weight: 600; }}
{_semantic(c)}
{_scores(c)}
QLabel[usage="warn"] {{ color: {c['warning_text']}; font-weight: 600; }}
QLabel[usage="danger"] {{ color: {c['danger_text']}; font-weight: 600; }}
QFrame#tabbar {{ background: transparent; border-bottom: 1px solid {c['divider']}; }}
QPushButton[tab="true"] {{ background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 0 {sp('4')}px; color: {c['text_secondary']}; font-size: {px('body')}px; font-weight: 500; }}
QPushButton[tab="true"]:hover {{ background: {c['surface_hover']}; color: {c['text_primary']}; }}
QPushButton[tab="true"]:checked {{ color: {c['primary_700']}; border-bottom: 2px solid {c['primary_700']}; font-weight: 600; }}
QPushButton[tab="true"]:focus {{ border: {K.FOCUS_RING_PX}px solid {c['border_focus']}; border-radius: 6px; }}
QPushButton[tab="true"]:checked:focus {{ border: {K.FOCUS_RING_PX}px solid {c['border_focus']}; border-bottom-color: {c['primary_700']}; border-radius: 6px; }}
QFrame#actionbar {{ background: {c['surface']}; border-top: 1px solid {c['divider']}; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['tooltip']}px; padding: {sp('1')}px; }}
QMenu::item {{ padding: {sp('2')}px {sp('4')}px; border-radius: 6px; color: {c['text_primary']}; font-size: {px('body')}px; }}
QMenu::item:selected {{ background: {c['primary_100']}; color: {c['primary_700']}; }}
QMenu::separator {{ height: 1px; background: {c['divider']}; margin: {sp('1')}px {sp('2')}px; }}
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


# ---- 카드 그림자·3상태(한 곳) ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CardLook:
    border_px: int
    border_color: str
    shadow: str


def card_look(state):
    """카드 상태(`default`·`hover`·`selected`) → 테두리 두께·색·그림자 이름. 값은 모두 토큰(`K.CARD_STATES`·팔레트)에서 온다 — 선택은 2px 파란 테두리."""
    if state not in K.CARD_STATES:
        raise ValueError(f"카드 상태가 아니에요: {state!r}")
    width, color_key, shadow = K.CARD_STATES[state]
    return CardLook(width, colors()[color_key], shadow)


def shadow_effect(kind, parent=None):
    """카드 그림자 3종(`card`·`hover`·`selected`) 중 하나의 `QGraphicsDropShadowEffect` — Qt 스타일시트로는 그림자를 못 그려서 **카드 틀에만** 이 효과를 입힌다(글자가 든 위젯 전체에 입히지 않는다).
    그림자는 위젯 밖으로 번지므로 효과를 입힌 카드의 부모에 번짐만큼(`blur` + 오프셋) 여백이 있어야 잘리지 않는다."""
    style = K.SHADOW[kind]
    effect = QGraphicsDropShadowEffect(parent)
    effect.setOffset(style.dx, style.dy)
    effect.setBlurRadius(style.blur)
    color = QColor(colors()[style.color_key])
    color.setAlphaF(style.alpha)
    effect.setColor(color)
    return effect
