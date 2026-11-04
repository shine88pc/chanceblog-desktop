"""앱 틀(AppShell) — 상단바 + 왼쪽 사이드바(메뉴 6개) + 본문(스크롤) + 오른쪽 패널(홈 안에서 좁으면 아래로) + 겹쳐 뜨는 서랍·대화상자·토스트.

화면 이동·동작은 `AppState`(`ui/core/app_state.py`)가 하고 여기서는 그 결과를 다시 그리기만 한다. 후보 불러오기 같은 긴 일은 작업 스레드(`ui/core/jobs.py`)에서 돌고,
진행·완료·실패·취소는 시그널로 화면 스레드에 넘어온다 — 일하는 중에도 창이 반응한다.
서랍·대화상자가 열려 있는 동안 Tab 은 그 안에서만 돌고, Esc 로 닫으며(대화상자 먼저), 닫으면 열었던 곳으로 포커스가 돌아온다.
"""
from __future__ import annotations

import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMainWindow, QScrollArea, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.app_state import NAV, AppState, report_unexpected
from ..core.text import T
from . import components as UI
from . import screens as S
from . import theme
from .workers import JobBridge


def qt_clipboard_set(text):
    """복사 — Qt 가 시스템 클립보드를 다룬다(줄바꿈은 알아서 윈도 방식으로)."""
    QGuiApplication.clipboard().setText(text)
    return True


def _version():
    from pathlib import Path
    try:
        return (Path(__file__).resolve().parents[4] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class AppShell(QMainWindow):
    def __init__(self, provider=None, *, clipboard=None, runner=None, today=None, autoload=True):
        super().__init__()
        self.state = AppState(provider, today=today, runner=runner)
        self._clipboard = clipboard or qt_clipboard_set
        self.setWindowTitle(T["window_title"])
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._topbar())
        middle = QHBoxLayout()
        middle.setSpacing(0)
        middle.addWidget(self._sidebar())
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)          # 가로 스크롤 없음 — 좁으면 배치를 바꾼다
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setFocusPolicy(Qt.NoFocus)                                      # Tab 정거장이 아니다 — 포커스가 간 단추가 보이도록 스크롤은 Qt 가 해 준다
        self.scroll.setAccessibleName(T["body_area"])
        middle.addWidget(self.scroll, 1)
        outer.addLayout(middle, 1)
        self.toast = UI.Toast(root)
        self.drawer = UI.Drawer(root)
        self.drawer.close_requested = self.close_drawer
        self.dialog = UI.Dialog(root)
        self.screen_widget = None
        self.refresh_button = self.cancel_button = self.drawer_close = None
        self._dialog_return = self._drawer_return = None
        self._outside_focus = {}
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.escape)
        self.bridge = JobBridge(self)
        self.bridge.loaded.connect(self._on_loaded)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.cancelled.connect(self._on_cancelled)
        self.setMinimumSize(*K.LAYOUT["window_min"])
        self.resize(*self.default_size())
        self.render()
        if autoload:
            QTimer.singleShot(0, self.reload)

    @staticmethod
    def default_size():
        """기본 창 크기 — 1440×900 근처, 화면이 작으면 화면에 맞춘다."""
        screen = QGuiApplication.primaryScreen()
        width, height = K.LAYOUT["window"]
        if screen is not None:
            area = screen.availableGeometry()
            width, height = min(width, int(area.width() * 0.96)), min(height, int(area.height() * 0.94))
        return max(width, K.LAYOUT["window_min"][0]), max(height, K.LAYOUT["window_min"][1])

    # ---- 틀 ----
    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setMinimumHeight(K.LAYOUT["topbar"])
        row = QHBoxLayout(bar)
        row.setContentsMargins(24, 0, 16, 0)
        row.setSpacing(12)
        row.addWidget(theme.IconWidget("leaf", theme.colors()["primary"], 26))
        row.addWidget(UI.label(T["app_name"], "h1"))
        row.addStretch(1)
        settings = UI.IconButton("settings", T["settings_btn"], focus_key="top-settings")
        settings.clicked.connect(lambda: self.go("settings"))
        row.addWidget(settings)
        return bar

    def _sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(K.LAYOUT["sidebar"])
        side.setAccessibleName(T["nav_menu"])
        layout = QVBoxLayout(side)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(4)
        self.nav_buttons = {}
        for key, label_key, icon_name in NAV:
            button = UI.NavButton(T[label_key], icon_name, T["nav_a11y"].format(name=T[label_key]))
            button.setProperty("focus_key", "nav:" + key)
            button.clicked.connect(lambda _=False, k=key: self.go(k))
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch(1)
        card = QFrame()
        card.setObjectName("brandcard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(16, 16, 16, 12)
        inner.setSpacing(8)
        sprout = theme.IconWidget("sprout", theme.colors()["success"], 28)
        inner.addWidget(sprout, 0, Qt.AlignHCenter)
        line = UI.label(T["brand_line"], "sub", wrap=True)
        line.setAlignment(Qt.AlignCenter)
        inner.addWidget(line)
        number = _version()
        version = UI.label(f"{T['brand_version']} v{number}" if number else T["brand_version"], "caption", wrap=True)
        version.setAlignment(Qt.AlignCenter)
        inner.addWidget(version)
        layout.addWidget(card)
        return side

    # ---- 그리기 ----
    def _focus_key(self):
        widget = QApplication.focusWidget()
        while widget is not None and not widget.property("focus_key"):
            widget = widget.parentWidget()
        return widget.property("focus_key") if widget is not None else None

    def _restore_focus(self, key):
        if not key:
            return
        for widget in self.centralWidget().findChildren(QWidget):
            if widget.property("focus_key") == key and widget.isVisibleTo(self) and widget.isEnabled() and widget.focusPolicy() != Qt.NoFocus:
                widget.setFocus(Qt.OtherFocusReason)
                return

    def render(self):
        """뷰모델로 본문을 다시 만든다. 포커스가 있던 곳(`focus_key`)과 스크롤 위치를 지켜서, 키보드로 칩을 눌러도 자리를 잃지 않는다."""
        state = self.state
        key, previous = self._focus_key(), self.scroll.verticalScrollBar().value()
        same_page = getattr(self, "_rendered_page", None) == state.page
        self.refresh_button = self.cancel_button = None
        widget = S.home_screen(self, state.home_view()) if state.page == "home" else S.placeholder_screen(self, state.page_view())
        self.screen_widget = widget
        holder = QWidget()                                                    # 넓은 창에서는 본문 폭을 제한하고 가운데에 둔다
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(widget, 1000)
        row.addStretch(1)
        widget.setMaximumWidth(K.LAYOUT["content_max"] + 2 * K.LAYOUT["page_margin"])
        old = self.scroll.takeWidget()                                        # 옛 화면은 바로 지우지 않고 다음 차례에 지운다 — 눌린 단추가 자기 눌림 처리 안에서 지워지면 안 된다
        self.scroll.setWidget(holder)
        if old is not None:
            old.deleteLater()
        self.scroll.verticalScrollBar().setValue(previous if same_page else 0)
        self._rendered_page = state.page
        for nav_key, button in self.nav_buttons.items():
            button.setChecked(nav_key == state.page)
        self._sync_overlays()
        if key and self._modal() is None:
            self._restore_focus(key)

    # ---- 겹쳐 뜨는 것(서랍·대화상자) ----
    def _modal(self):
        return self.dialog if self.dialog.is_open else self.drawer if self.drawer.is_open else None

    def _trap_focus(self, on, modal=None):
        """서랍·대화상자가 열려 있는 동안은 그 밖의 위젯에 Tab 이 가지 않게 한다. 다시 그려서 새로 생긴 위젯도 잡도록 여러 번 불러도 된다."""
        if on:
            for widget in self.centralWidget().findChildren(QWidget):
                if widget not in self._outside_focus and widget.focusPolicy() != Qt.NoFocus and widget is not modal and not modal.isAncestorOf(widget):
                    self._outside_focus[widget] = widget.focusPolicy()
                    widget.setFocusPolicy(Qt.NoFocus)
        else:
            for widget, policy in self._outside_focus.items():
                try:
                    widget.setFocusPolicy(policy)
                except RuntimeError:                                              # 다시 그리면서 이미 지워진 위젯
                    pass
            self._outside_focus.clear()

    def _sync_overlays(self):
        state = self.state
        view = state.drawer_view() if state.page == "home" else None
        if view is not None and not self.dialog.is_open:
            content, self.drawer_close = S.drawer_content(self, view)
            self.drawer.set_content(content)
            if not self.drawer.is_open:
                self._drawer_return = self._drawer_return or QApplication.focusWidget()
                self.drawer.open()
            self._trap_focus(True, self.drawer)
            if not self.drawer.scroll.isAncestorOf(QApplication.focusWidget()):
                self.drawer_close.setFocus(Qt.OtherFocusReason)
        elif view is None and self.drawer.is_open:
            self.drawer.dismiss()
            if not self.dialog.is_open:
                self._trap_focus(False)

    def close_drawer(self):
        opened = self.state.close_drawer()
        if opened is None:
            return
        self.render()
        target = self._drawer_return
        self._drawer_return = None
        self._restore_focus("detail:" + opened)
        if QApplication.focusWidget() is None and target is not None:
            target.setFocus(Qt.OtherFocusReason)

    def open_drawer(self, topic_id):
        if self.state.open_drawer(topic_id):
            self._drawer_return = QApplication.focusWidget()
            self.render()

    def show_dialog(self, title, body, ok=None, cancel=None, on_ok=None):
        """가운데 대화상자 — 제목·본문·단추. 처음 포커스는 기본 단추에 있고 Esc·취소로 닫는다."""
        self.dialog.clear()
        self.dialog.setAccessibleName(title)
        self.dialog.layout_.addWidget(UI.label(title, "h2", wrap=True))
        self.dialog.layout_.addWidget(UI.label(body, "body", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        if cancel:
            no = UI.Button("secondary", cancel, focus_key="dialog-cancel")
            no.clicked.connect(self.close_dialog)
            row.addWidget(no)
        yes = UI.Button("primary", ok or T["ok"], focus_key="dialog-ok")
        yes.clicked.connect(lambda: (self.close_dialog(), on_ok() if on_ok else None))
        row.addWidget(yes)
        self.dialog.layout_.addLayout(row)
        self._dialog_return = QApplication.focusWidget()
        self.dialog.present()
        self._trap_focus(True, self.dialog)
        yes.setFocus(Qt.OtherFocusReason)
        self.dialog_default = yes

    def close_dialog(self):
        if not self.dialog.is_open:
            return
        self.dialog.dismiss()
        self._trap_focus(False)
        if self.state.drawer_id and self.drawer.is_open:
            self._trap_focus(True, self.drawer)
        target, self._dialog_return = self._dialog_return, None
        if target is not None:
            try:
                target.setFocus(Qt.OtherFocusReason)
            except RuntimeError:
                pass

    def show_sample_info(self):
        self.show_dialog(T["sample_dialog_title"], T["sample_dialog_body"])

    def escape(self):
        if self.dialog.is_open:
            self.close_dialog()
        else:
            self.close_drawer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.drawer.place()
        if self.dialog.is_open:
            self.dialog.place()
        if self.toast.isVisible():
            self.toast.place()

    # ---- 동작 ----
    def notify(self, message):
        if message:
            self.toast.show_message(message)

    def notify_soon(self, name):
        self.notify(self.state.soon(name))

    def go(self, key):
        if self.state.nav(key):
            self.close_drawer_silently()
            self.render()

    def close_drawer_silently(self):
        self.state.close_drawer()
        self.drawer.dismiss()
        self._trap_focus(False)

    def chip_home(self, key):
        self.state.set_home_filter(key)
        self.render()

    def select_topic(self, topic_id):
        self.state.select_topic(topic_id)
        self.render()

    def tip_close(self):
        self.state.dismiss_tip()
        self.render()

    def quick(self, key):
        message = self.state.quick(key)
        self.render()
        self.notify(message)

    def draft(self, topic_id, blog):
        self.notify(self.state.draft_requested(topic_id, blog))

    def copy(self, text):
        """클립보드에 복사하고 성공 여부를 돌려준다(실패하면 안내만 하고 앱은 계속된다)."""
        try:
            return bool(self._clipboard(text))
        except Exception:                                                         # 클립보드를 못 쓰는 환경 — 입력한 글은 오류에 담지 않는다
            return False

    def copy_credit(self, credit):
        """사진 출처 두 줄 복사 + `출처 복사됨` 안내."""
        if self.copy(credit.copy_text()):
            self.notify(T["credit_copied"])
        else:
            self.notify(T["credit_failed"])

    # ---- 불러오기(작업 스레드) ----
    def reload(self, *_):
        job = self.state.start_load(**self.bridge.callbacks())
        if job is None:
            self.notify(T["load_busy"])
            return False
        self.render()
        return True

    def cancel_load(self):
        """불러오기를 취소한다 — 서비스 호출 하나가 도는 동안은 끊을 수 없어 일은 끝까지 가지만(늦게 끝난 결과는 작업 쪽이 버린다), 화면은 **바로** 보이던 모습으로 돌아간다(몇 초 동안 '불러오는 중' 에 멈춰 있지 않게)."""
        self.state.cancel_load()
        if self.state.loading:
            self._guarded(self._show_cancelled)

    # 작업 스레드가 보내 온 결과를 받는 화면 스레드 슬롯 셋 — 안에서 예외가 나도(이상한 데이터 …) '불러오는 중' 에 멈추지 않고 오류 상태로 바꾼다(`_guarded`)
    def _on_loaded(self, data):
        self._guarded(self._show_loaded, data)

    def _on_failed(self, failure):
        self._guarded(self._show_failed, failure)

    def _on_cancelled(self):
        self._guarded(self._show_cancelled)

    def _show_loaded(self, data):
        self.state.apply_home(data)
        self.render()

    def _show_failed(self, failure):
        self.state.apply_failure(failure, datetime.datetime.now())
        self.render()

    def _show_cancelled(self):
        self.state.apply_cancelled()
        self.render()
        self.notify(T["load_cancelled"])

    def _guarded(self, work, *args):
        try:
            work(*args)
        except Exception as error:
            self._recover(error)

    def _recover(self, error):
        """화면 스레드에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에, 내용·경로는 싣지 않는다). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)                                           # 원인은 한 줄(예외 이름 + 가리고 경로를 지운 글)로 표준 오류에 남긴다 — 화면에는 쉬운 문장뿐이라 조용한 실패가 되지 않게
        self.state.apply_unexpected(error, datetime.datetime.now())
        try:
            self.render()
        except Exception:
            self.notify(T["job_failed"])

    def closeEvent(self, event):
        self.hide()                                                               # 창은 바로 사라지게 — 끝나지 않은 작업을 잠깐(최대 1초) 기다리는 동안 멈춘 창처럼 보이지 않게
        self.state.runner.cancel_all()
        self.state.runner.join_all(1.0)
        super().closeEvent(event)
