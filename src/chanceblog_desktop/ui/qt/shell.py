"""앱 틀(AppShell) — 상단 앱 바(`topbar.py`) + 왼쪽 사이드바(`sidebar.py` — 홈·설정 메뉴와 '다음 단계' 목록) + 본문(스크롤) + 겹쳐 뜨는 서랍·대화상자·토스트.

화면 이동·동작은 `AppState`(`ui/core/app_state.py`)가 하고 여기서는 그 결과를 다시 그리기만 한다. 후보 불러오기 같은 긴 일은 작업 스레드(`ui/core/jobs.py`)에서 돌고,
진행·완료·실패·취소는 시그널로 화면 스레드에 넘어온다 — 일하는 중에도 창이 반응한다.
서랍·대화상자가 열려 있는 동안 Tab 은 그 안에서만 돌고, Esc 로 닫으며(대화상자 먼저), 닫으면 열었던 곳으로 포커스가 돌아온다.
어느 메뉴가 어느 화면인지는 `screens.SCREEN_BUILDERS` 표가 정하고 `render()` 는 그 표만 거친다. 설정 화면의 연결 정보도 작업 스레드(`settings-load`)에서 읽고 시그널로 받는다 — 홈 불러오기와 따로다.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QHBoxLayout, QMainWindow, QScrollArea, QVBoxLayout, QWidget

from ..core import tokens as K
from ..core.app_state import AppState, report_unexpected
from ..core.blogs_view import WRITE_KEY as BLOGS_WRITE_KEY
from ..core.clock import SystemClock
from ..core.text import T
from ..core.version import read_version
from . import components as UI
from . import screens as S
from .sidebar import Sidebar
from .topbar import TopBar
from .workers import JobBridge


RELAYOUT_AFTER_RESIZE_MS = 30                                                     # 창 크기가 바뀐 뒤 배치를 다시 계산하기까지 기다리는 시간 — 끌어 바꾸는 동안 계속 미루어진다
WRITE_CLOSE_WAIT = 10.0                                                           # 창을 닫을 때 저장·복제·삭제가 돌고 있으면 끝나기를 기다리는 최대 시간(초) — 쓰기는 중간에 끊을 수 없다
IMAGE_FILTER = "(*.png *.jpg *.jpeg *.webp)"                                       # 이미지 고르기 대화상자의 파일 종류(JPG·JPEG·PNG·WebP)


def qt_clipboard_set(text):
    """복사 — Qt 가 시스템 클립보드를 다룬다(줄바꿈은 알아서 윈도 방식으로)."""
    QGuiApplication.clipboard().setText(text)
    return True


def qt_file_picker(parent, title, filter_text):
    """이미지 파일 하나를 고르는 윈도 대화상자 — 고른 파일의 **위치**(고르지 않으면 빈 글). 파일을 읽거나 복사하지 않는다(시험은 이 대화상자 대신 가짜 선택기를 넣는다)."""
    path, _selected = QFileDialog.getOpenFileName(parent, title, "", filter_text)
    return path


class AppShell(QMainWindow):
    def __init__(self, provider=None, *, connections=None, clipboard=None, runner=None, clock=None, version_info=None, autoload=True, blogs=None, file_picker=None):
        super().__init__()
        self.version_info = version_info or read_version()                                # 사이드바 아래에 보일 버전(`v0.0.0` 또는 `개발 버전`)
        self.clock = clock or SystemClock()                                              # 시계는 주입한다(시험·사진은 가짜 시계) — 위젯이 `datetime.now()` 를 직접 부르지 않는다
        self._relayout_timer = QTimer(self)                                              # 다시 그린 뒤·창 크기를 바꾼 뒤 한 번, 화면의 배치를 처음부터 다시 계산한다(굳어 버린 행 높이를 푼다 — `screens.relayout_screen`)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._relayout)
        self.state = AppState(provider, runner=runner, connections=connections, version=self.version_info, blogs=blogs)           # 설정 화면의 '정보' 묶음이 사이드바와 같은 버전을 보인다
        self._clipboard = clipboard or qt_clipboard_set
        self._file_picker = file_picker or qt_file_picker                                 # 이미지 위치를 고르는 대화상자(시험·사진은 가짜 선택기를 주입한다)
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
        self._cancel_released = False                                                   # 취소를 눌러 화면을 먼저 풀고 안내했다 — 돌고 있던 일이 나중에 끝나며 보낼 신호 하나를 무시하려고(그 일의 끝 신호가 오면 꺼진다)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.escape)
        self.bridge = JobBridge(self)
        self.bridge.loaded.connect(self._on_loaded)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.cancelled.connect(self._on_cancelled)
        self.conn_bridge = JobBridge(self)                                              # 설정 화면(연결 관리)을 읽는 작업의 다리 — 홈 불러오기와 따로 돈다
        self.conn_bridge.loaded.connect(self._on_conn_loaded)
        self.conn_bridge.failed.connect(self._on_conn_failed)
        self.conn_bridge.cancelled.connect(self._on_conn_cancelled)
        self.blogs_bridge = JobBridge(self)                                             # 블로그 관리 화면을 읽는 작업의 다리(P4b) — 홈·설정 읽기와 따로 돈다
        self.blogs_bridge.loaded.connect(self._on_blogs_loaded)
        self.blogs_bridge.failed.connect(self._on_blogs_failed)
        self.blogs_bridge.cancelled.connect(self._on_blogs_cancelled)
        self.blogs_write_bridge = JobBridge(self)                                       # 저장·복제·삭제(파일에 쓰는 일)의 다리 — 사용자가 단추를 눌렀을 때만 시작한다
        self.blogs_write_bridge.loaded.connect(self._on_blogs_written)
        self.blogs_write_bridge.failed.connect(self._on_blogs_write_failed)
        self.blogs_write_bridge.cancelled.connect(self._on_blogs_write_cancelled)
        self.setMinimumSize(*K.LAYOUT["window_min"])
        self.resize(*self.default_size())
        self.render()
        if autoload:
            QTimer.singleShot(0, self.reload)
            QTimer.singleShot(0, self.read_connections)                                       # 앱이 열릴 때 홈의 `연결 상태` 한 줄이 값을 갖도록 설정 화면과 같은 읽기를 한 번 한다(UI-C1d, D-203)

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
        """상단 앱 바 — 잎·이름·한 줄 소개·날짜·시간(`qt/topbar.py`). 설정 아이콘은 없다(사이드바 '설정' 과 겹친다)."""
        self.topbar = TopBar(self.clock)
        return self.topbar

    def _sidebar(self):
        """왼쪽 사이드바 — 묶음 메뉴(홈·설정)·'다음 단계' 목록·브랜드와 버전(`qt/sidebar.py`). 화면으로 가는 길은 `self.go` 하나뿐이다."""
        self.sidebar = Sidebar(self.go, self.version_info)
        self.nav_buttons = self.sidebar.nav_buttons
        return self.sidebar

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
        widget = S.SCREEN_BUILDERS[state.page](self)                          # 메뉴 → 화면 만드는 함수 표(`screens.SCREEN_BUILDERS`)
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
        self._relayout_timer.start(0)                                         # 새 위젯이 보이고 글꼴이 입혀진 다음 한 번 더 배치를 맞춘다

    def _relayout(self):
        S.relayout_screen(self.scroll.widget())

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

    def show_dialog(self, title, body, ok=None, cancel=None, on_ok=None, danger=False, safe_focus=False):
        """가운데 대화상자 — 제목·본문·단추. 처음 포커스는 기본 단추에 있고 Esc·취소로 닫는다. `danger` 면 확인 단추가 위험 단추(최종 삭제 확인 — 빨간 배경)이고, `safe_focus` 면 처음 포커스가 취소에 있다(Enter 를 잘못 눌러도 지워지지 않는다)."""
        self.dialog.clear()
        self.dialog.setAccessibleName(title)
        self.dialog.layout_.addWidget(UI.label(title, "h2", wrap=True))
        self.dialog.layout_.addWidget(UI.label(body, "body", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        no = None
        if cancel:
            no = UI.Button("secondary", cancel, focus_key="dialog-cancel")
            no.clicked.connect(self.close_dialog)
            row.addWidget(no)
        yes = UI.Button("danger" if danger else "primary", ok or T["ok"], focus_key="dialog-ok")
        yes.clicked.connect(lambda: (self.close_dialog(), on_ok() if on_ok else None))
        row.addWidget(yes)
        self.dialog.layout_.addLayout(row)
        self._dialog_return = QApplication.focusWidget()
        self.dialog.present()
        self._trap_focus(True, self.dialog)
        first = no if (safe_focus and no is not None) else yes
        first.setFocus(Qt.OtherFocusReason)
        self.dialog_default = first

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

    def show_sample_info(self, screen="home"):
        """'예시 데이터' 설명 — 화면마다 보이는 것이 달라 설명도 그 화면 것이다(홈은 주제·숫자, 설정은 키 이름·사용량 숫자)."""
        self.show_dialog(T["sample_dialog_title"], {"settings": T["conn_sample_dialog_body"], "blogs": T["blogs_sample_dialog_body"]}.get(screen, T["sample_dialog_body"]))

    def escape(self):
        if self.dialog.is_open:
            self.close_dialog()
        else:
            self.close_drawer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_timer.start(RELAYOUT_AFTER_RESIZE_MS)                  # 끌어 바꾸는 동안은 미루고 멈춘 뒤 한 번만
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
            if key == "settings":                                                     # 설정 화면은 열 때마다 읽는다(이미 읽는 중이면 그대로 둔다) — 읽기는 작업 스레드에서
                self.state.start_conn_load(**self.conn_bridge.callbacks())
            elif key == "blogs":                                                      # 블로그 관리 화면도 열 때마다 읽는다(읽기만 — 파일도 폴더도 만들지 않는다). 쓰는 중이면 읽지 않는다
                self.state.blogs.start_load(**self.blogs_bridge.callbacks())
            self.render()

    def close_drawer_silently(self):
        self.state.close_drawer()
        self.drawer.dismiss()
        self._trap_focus(False)

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
        """불러오기를 취소한다 — 서비스 호출 하나가 도는 동안은 끊을 수 없어 일은 끝까지 가지만(늦게 끝난 결과는 작업 쪽이 버린다), 화면은 **바로** 보이던 모습으로 돌아간다(몇 초 동안 '불러오는 중' 에 멈춰 있지 않게).
        그렇게 먼저 풀고 안내했으면 일이 나중에 끝나며 보내는 취소 신호는 무시한다(`_on_cancelled`) — 안 그러면 몇 초 뒤에 같은 안내가 다시 뜨고 화면이 한 번 더 그려진다. 같은 일에 또 눌러도 안내는 한 번뿐이다."""
        self.state.cancel_load()
        if self.state.loading and not self._cancel_released:
            self._cancel_released = True
            self._guarded(self._show_cancelled)

    # 작업 스레드가 보내 온 결과를 받는 화면 스레드 슬롯 셋 — 안에서 예외가 나도(이상한 데이터 …) '불러오는 중' 에 멈추지 않고 오류 상태로 바꾼다(`_guarded`)
    def _on_loaded(self, data):
        self._cancel_released = False                                                  # 일이 끝났다(취소 신호는 이제 오지 않는다)
        self._guarded(self._show_loaded, data)

    def _on_failed(self, failure):
        self._cancel_released = False
        self._guarded(self._show_failed, failure)

    def _on_cancelled(self):
        released, self._cancel_released = self._cancel_released, False
        if not released:                                                               # 취소를 눌렀을 때 이미 화면을 풀고 안내했으면 늦게 끝난 일의 취소 신호는 무시한다(안내·다시 그리기를 두 번 하지 않는다)
            self._guarded(self._show_cancelled)

    def _show_loaded(self, data):
        self.state.apply_home(data)
        self.render()

    def _show_failed(self, failure):
        self.state.apply_failure(failure, self.clock.now())
        self.render()

    def _show_cancelled(self):
        self.state.apply_cancelled()
        self.render()
        self.notify(T["load_cancelled"])

    # ---- 설정 화면(연결 관리) 읽기 — 홈 불러오기와 같은 틀(작업 스레드·시그널·슬롯 보호), 이름만 따로다 ----
    def read_connections(self):
        """앱이 열릴 때(`autoload`) **한 번** — 설정 화면이 쓰는 것과 같은 읽기(`ConnectionsProvider.load_connections`, 읽기 전용: 모든 보관함 상태에서 전후 파일이 같다 — `test_ui_c1d_core`)를 작업 스레드에서 해
        홈의 `연결 상태` 한 줄이 값을 갖게 한다. 이미 읽는 중이면 아무것도 하지 않고 안내도 하지 않는다. 읽지 못하면 그 한 줄만 `연결 상태를 읽지 못했어요.` 가 되고 홈의 나머지는 그대로다.
        홈의 다시 불러오기는 연결 정보를 다시 읽지 않는다(설정 화면을 열 때마다 새로 읽는다 — 한계는 D-203)."""
        return self.state.start_conn_load(**self.conn_bridge.callbacks()) is not None

    def reload_connections(self, *_):
        """설정 화면의 연결 정보를 다시 읽는다(작업 스레드 — 보관소 읽기도 거기서). 이미 읽는 중이면(중복 클릭) 안내만 한다."""
        job = self.state.start_conn_load(**self.conn_bridge.callbacks())
        if job is None:
            self.notify(T["load_busy"])
            return False
        self.render()
        return True

    def set_group_open(self, key, opened):
        """접이식을 펴고 접은 것을 기억한다(파일에는 쓰지 않는다). 화면은 이미 바뀌었으므로 다시 그리지 않는다."""
        self.state.set_group_open(key, opened)

    def _on_conn_loaded(self, data):
        self._guarded(self._show_conn_loaded, data, recover=self._recover_conn)

    def _on_conn_failed(self, failure):
        self._guarded(self._show_conn_failed, failure, recover=self._recover_conn)

    def _on_conn_cancelled(self):
        self._guarded(self._show_conn_cancelled, recover=self._recover_conn)

    def _render_connections(self):
        """연결 정보를 받은 뒤 다시 그린다 — 그 값을 쓰는 화면(설정, 그리고 홈의 `연결 상태` 한 줄 — UI-C1d)을 보는 중일 때만. 설정 화면에서 홈으로 빨리 돌아와도 읽는 중이던 홈의 한 줄이 '읽고 있어요' 에 멈추지 않는다."""
        if self.state.page in ("settings", "home"):
            self.render()

    def _show_conn_loaded(self, data):
        self.state.apply_connections(data, self.clock.now())
        self._render_connections()

    def _show_conn_failed(self, failure):
        self.state.apply_conn_failure(failure, self.clock.now())
        self._render_connections()

    def _show_conn_cancelled(self):
        self.state.apply_conn_cancelled()
        self._render_connections()

    def _recover_conn(self, error):
        """설정 화면의 슬롯에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)
        self.state.apply_conn_unexpected(error, self.clock.now())
        try:
            self._render_connections()
        except Exception:
            self.notify(T["job_failed"])

    # ---- 블로그 관리 화면(P4b) — 읽기는 작업 스레드, 쓰기(저장·복제·삭제)는 사용자가 눌렀을 때만 따로 시작하는 작업. 고르기·고치기는 파일에 닿지 않는다 ----
    def reload_blogs(self, *_):
        """프로필을 다시 읽는다(읽기만). 이미 읽는 중이거나 쓰는 중이면 안내만 한다."""
        job = self.state.blogs.start_load(**self.blogs_bridge.callbacks())
        if job is None:
            self.notify(T["load_busy"])
            return False
        self.render()
        return True

    def _render_blogs(self):
        if self.state.page == "blogs":                                               # 다른 화면을 보는 중이면 값만 받아 두고 다시 그리지 않는다
            self.render()

    def _live_blogs(self):
        """칸을 고친 뒤 — 화면을 다시 그리지 않고 오류 글·단추·카드 표시만 바꾼다(입력 중이던 커서·한글 조합이 사라지지 않게)."""
        if self.state.page == "blogs" and self.screen_widget is not None:
            from .blog_screen import update_blogs_live
            update_blogs_live(self.screen_widget, self.state.blogs_view())

    def blog_select(self, key):
        if self.state.blogs.select(key):
            self.render()
            self._restore_focus("slot:" + key)

    def blog_edit(self, name, value):
        if self.state.blogs.edit(name, value):
            self._live_blogs()

    def blog_toggle_tag(self, tag):
        if self.state.blogs.toggle_tag(tag):
            self._live_blogs()

    def blog_pick_image(self, name):
        """이미지 위치 고르기 — 선택기가 준 **위치**만 칸에 넣는다(파일을 읽거나 복사하거나 올리지 않는다)."""
        path = self._file_picker(self, T["bf_pick_title"].format(label=T["bf_label_" + name]), f"{T['bf_pick_filter']} {IMAGE_FILTER}")
        if path:
            self.blog_edit(name, str(path))

    def blog_action(self, key):
        {"save": self.blog_save, "revert": self.blog_revert, "clone": self.blog_clone, "delete": self.blog_delete}.get(key, lambda: None)()

    def _focus_first_blog_error(self):
        ui = getattr(self.screen_widget, "blogs_ui", None)
        view = ui.fields.get(ui.first_error) if ui is not None and ui.first_error else None
        if view is not None and view.controls:
            view.controls[0].setFocus(Qt.OtherFocusReason)
            if ui.form_scroll is not None:                                           # 칸 이름·입력·안내·오류 문장이 한 덩어리로 보이게(배치가 끝난 다음 차례에) — 작은 창에서 오류 문장이 행동 줄 뒤로 반쯤 숨지 않게
                QTimer.singleShot(0, lambda scroll=ui.form_scroll, target=view: self._reveal_blog_field(scroll, target))

    @staticmethod
    def _reveal_blog_field(scroll, view):
        try:
            scroll.ensureWidgetVisible(view, 0, 12)
        except RuntimeError:                                                         # 그 사이 화면이 다시 그려져 부품이 사라졌다
            pass

    def blog_save(self):
        """저장 — 칸에 문제가 있으면 서비스를 부르지 않고 문제 칸을 보인다. 아니면 쓰기 작업을 시작한다(쓰는 동안 칸·단추는 꺼진다)."""
        status, _detail = self.state.blogs.start_save(**self.blogs_write_bridge.callbacks())
        if status == "started":
            self.render()
        elif status == "invalid":
            self.render()
            self._focus_first_blog_error()
        elif status == "nothing":
            self.notify(T["blogs_save_nothing"])
        else:
            self.notify(T["load_busy"])

    def blog_revert(self):
        if self.state.blogs.revert():
            self.render()

    def blog_clone(self):
        status, _detail = self.state.blogs.start_clone(**self.blogs_write_bridge.callbacks())
        if status == "started":
            self.render()
        elif status == "unavailable":
            self.notify(self.state.blogs.clone_info()[1] or T["blogs_clone_no_target"])
        else:
            self.notify(T["load_busy"])

    def blog_delete(self):
        """삭제 — 확인창이 먼저다(무엇이 지워지는지·되돌릴 수 없다는 것·후보·초안·발행 기록은 지워지지 않는다는 것). '지우기' 를 눌러야 쓰기가 시작된다(처음 포커스는 취소)."""
        blogs = self.state.blogs
        if blogs.busy or not blogs.can_clear():
            self.notify(T["load_busy"] if blogs.busy else T["blogs_delete_empty"])
            return
        dialog = blogs.delete_dialog()
        self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=self.blog_delete_confirmed, danger=True, safe_focus=True)

    def blog_delete_confirmed(self):
        status, _detail = self.state.blogs.start_clear(**self.blogs_write_bridge.callbacks())
        if status == "started":
            self.render()

    def _on_blogs_loaded(self, data):
        self._guarded(self._show_blogs_loaded, data, recover=self._recover_blogs)

    def _on_blogs_failed(self, failure):
        self._guarded(self._show_blogs_failed, failure, recover=self._recover_blogs)

    def _on_blogs_cancelled(self):
        self._guarded(self._show_blogs_cancelled, recover=self._recover_blogs)

    def _show_blogs_loaded(self, data):
        self.state.blogs.apply_loaded(data)
        self._render_blogs()

    def _show_blogs_failed(self, failure):
        self.state.blogs.apply_load_failed(failure, self.clock.now())
        self._render_blogs()

    def _show_blogs_cancelled(self):
        self.state.blogs.apply_cancelled()
        self._render_blogs()

    def _on_blogs_written(self, outcome):
        self._guarded(self._show_blogs_written, outcome, recover=self._recover_blogs_write)

    def _on_blogs_write_failed(self, failure):
        self._guarded(self._show_blogs_write_failed, failure, recover=self._recover_blogs_write)

    def _on_blogs_write_cancelled(self):
        self._guarded(self._show_blogs_write_failed, None, recover=self._recover_blogs_write)

    def _show_blogs_written(self, outcome):
        self.state.blogs.apply_write_ok(outcome)
        self._render_blogs()
        self._restore_focus("slot:" + self.state.blogs.selected)

    def _show_blogs_write_failed(self, failure):
        reload = self.state.blogs.apply_write_failed(failure)
        self._render_blogs()
        if reload:                                                                   # 다른 곳이 먼저 바꿨다 — 최신 내용을 다시 읽는다(읽기만, 입력은 그대로)
            self.reload_blogs()
        else:
            self._focus_first_blog_error()

    def _recover_blogs(self, error):
        """블로그 관리 슬롯에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)
        self.state.blogs.apply_unexpected(error, self.clock.now())
        try:
            self._render_blogs()
        except Exception:
            self.notify(T["job_failed"])

    def _recover_blogs_write(self, error):
        report_unexpected(type(error), error)
        self.state.blogs.apply_write_unexpected(error)
        try:
            self._render_blogs()
        except Exception:
            self.notify(T["job_failed"])

    def _guarded(self, work, *args, recover=None):
        try:
            work(*args)
        except Exception as error:
            (recover or self._recover)(error)

    def _recover(self, error):
        """화면 스레드에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에, 내용·경로는 싣지 않는다). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)                                           # 원인은 한 줄(예외 이름 + 가리고 경로를 지운 글)로 표준 오류에 남긴다 — 화면에는 쉬운 문장뿐이라 조용한 실패가 되지 않게
        self.state.apply_unexpected(error, self.clock.now())
        try:
            self.render()
        except Exception:
            self.notify(T["job_failed"])

    def closeEvent(self, event):
        self.hide()                                                               # 창은 바로 사라지게 — 끝나지 않은 작업을 잠깐(최대 1초) 기다리는 동안 멈춘 창처럼 보이지 않게
        if self.state.blogs.busy:                                                 # 저장·복제·삭제는 중간에 끊을 수 없다 — 끝나기를 기다린다(파일은 이름 바꾸기 한 번이라 온전하지만 사본·잠금 정리까지 마치게)
            job = self.state.runner.job(BLOGS_WRITE_KEY)
            if job is not None:
                job.join(WRITE_CLOSE_WAIT)
        self.state.runner.cancel_all()
        self.state.runner.join_all(1.0)
        super().closeEvent(event)
