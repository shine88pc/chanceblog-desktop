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
from ..core.seeds_view import WRITE_KEY as SEEDS_WRITE_KEY
from ..core.keys_view import WRITE_KEY as KEYS_WRITE_KEY
from ..core.clock import SystemClock
from ..core.text import T
from ..core.version import read_version
from . import components as UI
from . import screens as S
from .key_parts import KeyDialog, RenameForm
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


def qt_clipboard_wipe(texts):
    """클립보드의 글이 `texts` 중 하나와 (줄바꿈·앞뒤 공백을 뺀 뒤) 같으면 클립보드를 비운다 → 비웠으면 True. **붙여 넣은 키가 클립보드에 그대로 남지 않게** 하려는 것이다 — 다른 글(사용자가 따로 복사한 것)은 건드리지 않고 앱이 클립보드에 글을 넣는 일은 없다."""
    clipboard = QGuiApplication.clipboard()
    current = "".join(clipboard.text().splitlines()).strip()
    if current and any(current == "".join(text.splitlines()).strip() for text in texts):
        clipboard.clear()
        return True
    return False


def qt_file_picker(parent, title, filter_text):
    """이미지 파일 하나를 고르는 윈도 대화상자 — 고른 파일의 **위치**(고르지 않으면 빈 글). 파일을 읽거나 복사하지 않는다(시험은 이 대화상자 대신 가짜 선택기를 넣는다)."""
    path, _selected = QFileDialog.getOpenFileName(parent, title, "", filter_text)
    return path


class AppShell(QMainWindow):
    def __init__(self, provider=None, *, connections=None, clipboard=None, runner=None, clock=None, version_info=None, autoload=True, blogs=None, file_picker=None, seeds=None, clipboard_wipe=None):
        super().__init__()
        self.version_info = version_info or read_version()                                # 사이드바 아래에 보일 버전(`v0.0.0` 또는 `개발 버전`)
        self.clock = clock or SystemClock()                                              # 시계는 주입한다(시험·사진은 가짜 시계) — 위젯이 `datetime.now()` 를 직접 부르지 않는다
        self._relayout_timer = QTimer(self)                                              # 다시 그린 뒤·창 크기를 바꾼 뒤 한 번, 화면의 배치를 처음부터 다시 계산한다(굳어 버린 행 높이를 푼다 — `screens.relayout_screen`)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._relayout)
        self.state = AppState(provider, runner=runner, connections=connections, version=self.version_info, blogs=blogs, seeds=seeds)           # 설정 화면의 '정보' 묶음이 사이드바와 같은 버전을 보인다
        self._clipboard = clipboard or qt_clipboard_set
        self._file_picker = file_picker or qt_file_picker                                 # 이미지 위치를 고르는 대화상자(시험·사진은 가짜 선택기를 주입한다)
        self._clipboard_wipe = clipboard_wipe or qt_clipboard_wipe                        # 붙여 넣은 키가 클립보드에 남지 않게 비우는 함수(시험은 가짜를 주입한다)
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
        self._dialog_on_cancel = None                                                   # 대화상자를 확인 없이 닫을 때(취소·Esc) 부를 함수 — 일괄 변경·제안 파일의 '확인창을 보였다' 표시를 거둔다
        self._key_click = (None, "")                                                     # 마지막으로 누른 키 행 단추(항목 번호, 행동) — 쓰기가 끝나 다시 그린 뒤 포커스를 돌려줄 곳
        self._key_focus_wanted = None                                                    # 쓰기가 끝났고 새 값을 받으면 포커스를 돌려줘야 한다: (일 종류, 용도, 누른 단추)
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
        self.seeds_bridge = JobBridge(self)                                             # Seed 관리 화면을 읽는 작업의 다리 — 홈·설정·블로그 읽기와 따로 돈다
        self.seeds_bridge.loaded.connect(self._on_seeds_loaded)
        self.seeds_bridge.failed.connect(self._on_seeds_failed)
        self.seeds_bridge.cancelled.connect(self._on_seeds_cancelled)
        self.seeds_write_bridge = JobBridge(self)                                       # 승인·바꾸기·저장·등록·불러오기(파일에 쓰는 일)와 제안 파일 미리 보기의 다리 — 사용자가 단추를 눌렀을 때만 시작한다
        self.seeds_write_bridge.loaded.connect(self._on_seeds_written)
        self.seeds_write_bridge.failed.connect(self._on_seeds_write_failed)
        self.seeds_write_bridge.cancelled.connect(self._on_seeds_write_cancelled)
        self.keys_bridge = JobBridge(self)                                              # 키 등록·삭제·상태·별칭·순서·시험(P4f)의 다리 — 사용자가 단추를 눌렀을 때만 시작한다
        self.keys_bridge.loaded.connect(self._on_keys_written)
        self.keys_bridge.failed.connect(self._on_keys_failed)
        self.keys_bridge.cancelled.connect(self._on_keys_cancelled)
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
        self._sync_overlays(key)
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

    def _sync_overlays(self, key=None):
        state = self.state
        view = state.drawer_view() if state.page == "home" else None
        seed_view = state.seeds_drawer_view()                                     # Seed 관리 화면의 서랍(상세·새 Seed) — 그 화면에서만 있다
        if seed_view is not None and view is None and not self.dialog.is_open:
            from .seed_screen import seed_drawer
            content, self.drawer_close, footer, self.seeds_drawer_ui = seed_drawer(self, seed_view)
            self.drawer.set_content(content, footer)
            self.drawer.setAccessibleName(seed_view["a11y"])                       # 서랍 틀의 읽기용 이름도 이 내용의 것이다(공통 틀의 '주제 상세' 가 아니다)
            self.drawer.scroll.setAccessibleName(seed_view["a11y"])                # 스크롤 영역도 Tab 정거장이라 이름이 있어야 한다
            if not self.drawer.is_open:
                self._drawer_return = self._drawer_return or QApplication.focusWidget()
                self.drawer.open()
            self._trap_focus(True, self.drawer)
            if key:
                self._restore_focus(key)                                           # 다시 그리기 전에 포커스가 있던 칸·단추(열쇠가 같으면)로 돌아간다
            if not self.drawer.isAncestorOf(QApplication.focusWidget()):
                self.drawer_close.setFocus(Qt.OtherFocusReason)
        elif view is not None and not self.dialog.is_open:
            content, self.drawer_close = S.drawer_content(self, view)
            self.drawer.set_content(content)
            self.drawer.setAccessibleName(T["drawer_title"])                       # 홈의 주제 상세로 돌아오면 공통 이름으로 되돌린다(Seed 서랍이 바꿔 둔 이름을 남기지 않는다)
            self.drawer.scroll.setAccessibleName(T["drawer_title"])
            if not self.drawer.is_open:
                self._drawer_return = self._drawer_return or QApplication.focusWidget()
                self.drawer.open()
            self._trap_focus(True, self.drawer)
            if not self.drawer.scroll.isAncestorOf(QApplication.focusWidget()):
                self.drawer_close.setFocus(Qt.OtherFocusReason)
        elif view is None and seed_view is None and self.drawer.is_open:
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
        self._restore_focus(opened if opened.startswith("seed:") else "detail:" + opened)
        if QApplication.focusWidget() is None and target is not None:
            target.setFocus(Qt.OtherFocusReason)

    def open_drawer(self, topic_id):
        if self.state.open_drawer(topic_id):
            self._drawer_return = QApplication.focusWidget()
            self.render()

    def show_dialog(self, title, body, ok=None, cancel=None, on_ok=None, danger=False, safe_focus=False, on_cancel=None):
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
            no.clicked.connect(lambda _=False: self.close_dialog())
            row.addWidget(no)
        self._dialog_on_cancel = on_cancel
        yes = UI.Button("danger" if danger else "primary", ok or T["ok"], focus_key="dialog-ok")
        yes.clicked.connect(lambda: (self.close_dialog(confirmed=True), on_ok() if on_ok else None))
        row.addWidget(yes)
        self.dialog.layout_.addLayout(row)
        self._dialog_return = QApplication.focusWidget()
        self.dialog.present()
        self._trap_focus(True, self.dialog)
        first = no if (safe_focus and no is not None) else yes
        first.setFocus(Qt.OtherFocusReason)
        self.dialog_default = first

    def close_dialog(self, confirmed=False):
        if not self.dialog.is_open:
            return
        callback, self._dialog_on_cancel = self._dialog_on_cancel, None
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
        if callback is not None and not confirmed:                                    # 취소·Esc 로 닫았다 — 확인 없이 닫았음을 알린다
            callback()

    def show_sample_info(self, screen="home"):
        """'예시 데이터' 설명 — 화면마다 보이는 것이 달라 설명도 그 화면 것이다(홈은 주제·숫자, 설정은 키 이름·사용량 숫자)."""
        self.show_dialog(T["sample_dialog_title"], {"settings": T["conn_sample_dialog_body"], "blogs": T["blogs_sample_dialog_body"], "seed": T["seeds_sample_dialog_body"]}.get(screen, T["sample_dialog_body"]))

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
            elif key == "seed":                                                       # Seed 관리 화면도 열 때마다 읽는다(읽기만). 쓰는 중이면 읽지 않는다
                self.state.seeds.start_load(**self.seeds_bridge.callbacks())
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
        """설정 화면의 연결 정보를 다시 읽는다(작업 스레드 — 보관소 읽기도 거기서). 이미 읽는 중이면(중복 클릭) 안내만 한다. 키를 쓰는 중에는 읽지 않는다(쓰는 도중의 파일을 읽어 낡은 값이 남지 않게)."""
        if self.state.keys.busy:
            self.notify(T["keys_busy"])
            return False
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
        self._reload_after_keys()                                                     # 쓰기가 끝났을 때 이미 돌고 있던 읽기였다면 그 읽기는 쓰기 전 값일 수 있어 한 번 더 읽는다
        self._render_connections()
        self._give_key_focus()

    def _show_conn_failed(self, failure):
        self.state.apply_conn_failure(failure, self.clock.now())
        self._reload_after_keys()
        self._render_connections()
        self._give_key_focus()

    def _show_conn_cancelled(self):
        self.state.apply_conn_cancelled()
        self._reload_after_keys()
        self._render_connections()
        self._give_key_focus()

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

    def blog_toggle_choice(self, name, value):
        """여럿 고르는 칩(협찬 가능 분야·선호 글 유형) 하나를 켜고 끈다 — 고치는 것뿐이라 파일에 닿지 않는다."""
        if self.state.blogs.toggle_choice(name, value):
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

    # ---- Seed 관리 화면 — 읽기는 작업 스레드, 쓰기(승인·바꾸기·저장·등록·불러오기)는 사용자가 눌렀을 때만 따로 시작하는 작업. 거르기·찾기·고르기·서랍 열기·칸 고치기는 파일에 닿지 않는다 ----
    def reload_seeds(self, *_):
        """Seed 를 다시 읽는다(읽기만). 이미 읽는 중이거나 쓰는 중이면 안내만 한다."""
        job = self.state.seeds.start_load(**self.seeds_bridge.callbacks())
        if job is None:
            self.notify(T["load_busy"])
            return False
        self.render()
        return True

    def _render_seeds(self):
        if self.state.page == "seed":                                                # 다른 화면을 보는 중이면 값만 받아 두고 다시 그리지 않는다
            self.render()

    def _live_seeds(self):
        """상자를 고른 뒤 — 화면을 다시 그리지 않고 줄의 고름 표시와 일괄 변경 줄만 바꾼다."""
        if self.state.page == "seed" and self.screen_widget is not None:
            from .seed_screen import update_seeds_live
            update_seeds_live(self.screen_widget, self.state.seeds_view())

    def _live_seed_drawer(self):
        """서랍의 칸을 고친 뒤 — 서랍을 다시 그리지 않고 오류 글·단추만 바꾼다(입력 중이던 커서·한글 조합이 사라지지 않게)."""
        ui, view = getattr(self, "seeds_drawer_ui", None), self.state.seeds_drawer_view()
        if ui is not None and view is not None:
            from .seed_screen import update_seed_drawer_live
            update_seed_drawer_live(ui, view)

    def seed_status(self, key):
        if self.state.seeds.set_status(key):
            self.render()

    def seed_scope(self, key):
        if self.state.seeds.set_scope(key):
            self.render()

    def seed_importance(self, key):
        if self.state.seeds.set_importance(key):
            self.render()

    def seed_query(self, text):
        """글 검색 — 줄 목록만 새로 짓는다(검색 칸은 그대로라 커서가 안 튄다)."""
        if self.state.seeds.set_query(text) and self.state.page == "seed" and self.screen_widget is not None:
            from .seed_screen import refilter_seeds_live
            refilter_seeds_live(self.screen_widget, self.state.seeds_view())

    def seed_toggle_filters(self):
        self.state.seeds.toggle_more_filters()
        self.render()

    def seed_reset_filters(self):
        self.state.seeds.reset_filters()
        self.render()

    def seed_more(self):
        self.state.seeds.show_more()
        self.render()

    def seed_check(self, seed_id):
        if self.state.seeds.toggle_check(seed_id):
            self._live_seeds()

    def seed_select_all(self):
        if self.state.seeds.select_found():
            self._live_seeds()

    def seed_clear_checks(self):
        if self.state.seeds.clear_checks():
            self._live_seeds()

    def seed_open(self, seed_id):
        """줄을 눌러 상세 서랍을 연다(읽기뿐). 닫으면 이 줄로 포커스가 돌아온다."""
        returning = QApplication.focusWidget()
        if self.state.seeds.open_detail(seed_id):
            self._drawer_return = returning
            self.render()

    def seed_open_new(self):
        returning = QApplication.focusWidget()
        if self.state.seeds.open_new():
            self._drawer_return = returning
            self.render()

    def _after_seed_edit(self, result):
        if result == "structural":                                                   # 칸 구성이 바뀌었다(소속·중요도) — 서랍을 다시 그린다
            self.render()
        elif result:
            self._live_seed_drawer()

    def seed_edit(self, name, value):
        self._after_seed_edit(self.state.seeds.edit(name, value))

    def seed_toggle_channel(self, code):
        self._after_seed_edit(self.state.seeds.toggle_channel(code))

    def seed_action(self, key):
        {"save": self.seed_save, "revert": self.seed_revert, "create": self.seed_create, "cancel": self.close_drawer,
         "approve": lambda: self.seed_state("approve"), "rest": lambda: self.seed_state("rest"), "resume": lambda: self.seed_state("resume")}.get(key, lambda: None)()

    def _focus_first_seed_error(self):
        ui = getattr(self, "seeds_drawer_ui", None)
        view = ui.fields.get(ui.first_error) if ui is not None and ui.first_error else None
        if view is not None and view.controls:
            view.controls[0].setFocus(Qt.OtherFocusReason)
            QTimer.singleShot(0, lambda scroll=self.drawer.scroll, target=view: self._reveal_blog_field(scroll, target))

    def seed_save(self):
        """저장 — 칸에 문제가 있으면 서비스를 부르지 않고 문제 칸을 보인다. 아니면 쓰기 작업을 시작한다(쓰는 동안 칸·단추는 꺼진다)."""
        status, _detail = self.state.seeds.start_save(**self.seeds_write_bridge.callbacks())
        if status == "started":
            self.render()
        elif status == "invalid":
            self.render()
            self._focus_first_seed_error()
        elif status == "nothing":
            self.notify(T["seeds_act_nothing"])
        else:
            self.notify(T["load_busy"])

    def seed_revert(self):
        if self.state.seeds.revert():
            self.render()

    def seed_state(self, action):
        """승인하기·쉬게 하기·다시 쓰기 — 씨앗 하나는 확인창 없이 저장한다(저장하지 않은 변경이 있으면 먼저 저장하게 한다)."""
        status, _detail = self.state.seeds.start_state(action, **self.seeds_write_bridge.callbacks())
        if status == "started":
            self.render()
        elif status == "unsaved":
            self.notify(T["seeds_act_unsaved"])
        elif status == "busy":
            self.notify(T["load_busy"])

    def seed_create(self):
        status, _detail = self.state.seeds.start_create(**self.seeds_write_bridge.callbacks())
        if status == "started":
            self.render()
        elif status == "invalid":
            self.render()
            self._focus_first_seed_error()
        elif status == "busy":
            self.notify(T["load_busy"])

    def seed_bulk(self, kind):
        """여러 개를 한꺼번에 바꾸기 — 확인창이 먼저다(개수·처음 몇 개 이름·되돌릴 수 있다는 것·바꾼 뒤 채널별 수). '바꾸기' 를 눌러야 쓰기가 시작된다(처음 포커스는 취소)."""
        seeds = self.state.seeds
        dialog = seeds.bulk_dialog(kind)
        if dialog is None:
            self.notify(T["load_busy"] if seeds.busy else seeds.bulk_info(kind)[1])
            return
        self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=lambda: self.seed_bulk_confirmed(kind), safe_focus=True, on_cancel=seeds.discard_bulk)

    def seed_bulk_confirmed(self, kind):
        status, _detail = self.state.seeds.start_bulk(kind, **self.seeds_write_bridge.callbacks())
        if status == "started":
            self.render()

    def seed_import(self):
        """제안 파일 불러오기 — 파일 고르기(위치만) → 읽어 보기(읽기뿐) → 확인창 → 등록. 고르지 않으면 아무 일도 없다."""
        path = self._file_picker(self, T["seeds_pick_title"], f"{T['seeds_pick_filter']} (*.json)")
        if not path:
            return
        status, _detail = self.state.seeds.start_import_preview(path, **self.seeds_write_bridge.callbacks())
        if status == "started":
            self.render()
        elif status == "busy":
            self.notify(T["load_busy"])

    def _show_import_dialog(self):
        seeds = self.state.seeds
        dialog = seeds.import_dialog()
        if dialog is None:
            return
        if dialog["can_apply"]:
            self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=self.seed_import_confirmed, safe_focus=True, on_cancel=seeds.discard_import)
        else:
            self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=None, on_ok=seeds.discard_import, on_cancel=seeds.discard_import)

    def seed_import_confirmed(self):
        status, _detail = self.state.seeds.start_import_apply(**self.seeds_write_bridge.callbacks())
        if status == "started":
            self.render()

    def _on_seeds_loaded(self, data):
        self._guarded(self._show_seeds_loaded, data, recover=self._recover_seeds)

    def _on_seeds_failed(self, failure):
        self._guarded(self._show_seeds_failed, failure, recover=self._recover_seeds)

    def _on_seeds_cancelled(self):
        self._guarded(self._show_seeds_cancelled, recover=self._recover_seeds)

    def _show_seeds_loaded(self, data):
        self.state.seeds.apply_loaded(data)
        self._render_seeds()

    def _show_seeds_failed(self, failure):
        self.state.seeds.apply_load_failed(failure, self.clock.now())
        self._render_seeds()

    def _show_seeds_cancelled(self):
        self.state.seeds.apply_cancelled()
        self._render_seeds()

    def _on_seeds_written(self, outcome):
        self._guarded(self._show_seeds_written, outcome, recover=self._recover_seeds_write)

    def _on_seeds_write_failed(self, failure):
        self._guarded(self._show_seeds_write_failed, failure, recover=self._recover_seeds_write)

    def _on_seeds_write_cancelled(self):
        self._guarded(self._show_seeds_write_failed, None, recover=self._recover_seeds_write)

    def _show_seeds_written(self, outcome):
        self.state.seeds.apply_write_ok(outcome)
        self._render_seeds()
        if outcome.kind == "preview":
            self._show_import_dialog()

    def _show_seeds_write_failed(self, failure):
        reload = self.state.seeds.apply_write_failed(failure)
        self._render_seeds()
        if reload:                                                                   # 다른 곳이 먼저 바꿨다 — 최신 내용을 다시 읽는다(읽기만, 입력은 그대로)
            self.reload_seeds()
        else:
            self._focus_first_seed_error()

    def _recover_seeds(self, error):
        """Seed 관리 슬롯에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)
        self.state.seeds.apply_unexpected(error, self.clock.now())
        try:
            self._render_seeds()
        except Exception:
            self.notify(T["job_failed"])

    def _recover_seeds_write(self, error):
        report_unexpected(type(error), error)
        self.state.seeds.apply_write_unexpected(error)
        try:
            self._render_seeds()
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

    # ---- 키 연결(P4f) — 설정 화면의 연결 카드. 읽기는 위의 연결 읽기 그대로, 쓰기는 사용자가 단추를 눌렀을 때만 시작하는 작업(작업 스레드)이다 ----
    def wipe_clipboard(self, texts):
        """붙여 넣은 키와 같은 글이 클립보드에 있으면 비운다(없으면 아무것도 안 한다). 클립보드를 못 다뤄도 앱은 계속된다."""
        try:
            return bool(self._clipboard_wipe(texts))
        except Exception:                                                         # 클립보드를 못 쓰는 환경 — 입력한 글은 오류에 담지 않는다
            return False

    def _keys(self):
        return self.state.keys

    def _after_key_start(self, status, detail=None):
        """쓰기를 시작한 결과 — 시작했으면 쓰는 동안 단추가 꺼진 모습으로 다시 그린다. 이미 쓰는 중이면 안내만(두 번째 클릭은 아무 일도 하지 않는다). 바뀐 것이 없으면 그 안내(위 띠)를 보인다."""
        if status == "started":
            self.render()
        elif status == "busy":
            self.notify(T["keys_busy"])
        elif status == "nothing":
            self.render()
        else:
            self.notify(T["keys_fail_other"])
        return status

    def key_register(self, purpose):
        """'키 등록' — 대화상자를 연다(쓰는 중이거나 저장소를 못 쓰거나 자리가 없으면 까닭을 알리고 열지 않는다)."""
        keys = self._keys()
        draft = keys.open_register(purpose)
        if draft is None:
            info = keys.info(purpose)
            register = keys.register_vm(info) if info is not None else None
            self.notify(register["reason"] if register and register["reason"] else T["keys_fail_other"])
            return None
        self.show_key_dialog(draft)
        return draft

    def show_key_dialog(self, draft):
        """키 등록 대화상자를 보인다 — 닫히거나 다른 대화상자로 바뀔 때 어느 길로든 입력 칸을 비우도록 정리 훅을 건다."""
        form = KeyDialog(draft, self)
        self.dialog.clear()
        draft.submitted = False
        self.dialog.cleanups.append(form.wipe)
        self.dialog.cleanups.append(lambda: self._drop_draft(draft))                    # 저장 말고 어느 길로든 닫히면(Esc·X·취소·다른 대화상자) 초안도 버린다 — 확인 단계에서 닫았다가 빈 칸으로 다시 열리지 않게
        self.dialog.setAccessibleName(draft.vm()["a11y"])
        self.dialog.layout_.addWidget(form)
        form.show()                                                                      # 이미 열려 있는 대화상자의 안쪽을 바꿔 끼울 때 새 부품은 다음 차례에야 보여서 높이 계산에서 빠진다 — 바로 보인다고 알려 둔다
        self._dialog_return = QApplication.focusWidget()
        self.dialog.present()
        self._trap_focus(True, self.dialog)
        form.focus_start()
        self.key_form = form
        return form

    def _drop_draft(self, draft):
        keys = self._keys()
        if keys.draft is draft and not draft.submitted:
            keys.close_register()

    def key_add(self, draft, box):
        """저장 — 키는 통(`SecretBox`)에 담겨 컨트롤러로 간다. 시작하지 못하면(문제·쓰는 중) 통은 비워지고 문제가 있으면 대화상자를 다시 열어 칸 옆에 보인다(별칭은 남고 키는 다시 입력)."""
        status, detail = self._keys().start_add(draft.purpose, draft.provider, draft.alias, box, draft.terms, **self.keys_bridge.callbacks())
        if status == "invalid":
            draft.step = "input"
            self.show_key_dialog(draft)
            return status
        if status != "started":
            self._keys().close_register()                                             # 시작하지 못했다(쓰는 중·쓸 수 없음) — 대화상자는 닫혔으니 초안도 버린다
        return self._after_key_start(status, detail)

    def key_cancel(self):
        """등록 취소·Esc·닫기 — 입력 칸을 비우고(정리 훅) 초안을 버린다."""
        self.close_dialog()
        self._keys().close_register()

    def key_action(self, purpose, ref, action):
        """행 단추 — 삭제·별칭은 먼저 대화상자, 나머지는 바로 쓰기 작업을 시작한다."""
        keys = self._keys()
        callbacks = self.keys_bridge.callbacks()
        self._key_click = (ref, action)                                           # 쓰기가 끝나 다시 그린 뒤 포커스를 돌려줄 곳
        if action == "delete":
            return self.key_delete(purpose, ref)
        if action == "rename":
            return self.key_rename_dialog(purpose, ref)
        if action == "test":
            return self._after_key_start(*keys.start_test(purpose, ref, **callbacks))
        if action in ("up", "down"):
            return self._after_key_start(*keys.start_move(purpose, ref, -1 if action == "up" else 1, **callbacks))
        if action.startswith("state:"):
            return self._after_key_start(*keys.start_state(purpose, ref, action.split(":", 1)[1], **callbacks))
        return None

    def key_delete(self, purpose, ref):
        """삭제 — 확인창이 먼저다(무엇이 지워지는지·되돌릴 수 없다는 것, 처음 포커스는 취소). '지우기' 를 눌러야 쓰기가 시작된다."""
        keys = self._keys()
        info, entry = keys.info(purpose), keys.entry(purpose, ref)
        if info is None or entry is None or keys.busy:
            self.notify(T["keys_busy"] if keys.busy else T["keys_fail_notfound"])
            return None
        dialog = keys.delete_dialog(info, entry)
        self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=lambda: self.key_delete_confirmed(purpose, ref), danger=True, safe_focus=True)
        return dialog

    def key_delete_confirmed(self, purpose, ref):
        return self._after_key_start(*self._keys().start_remove(purpose, ref, **self.keys_bridge.callbacks()))

    def key_rename_dialog(self, purpose, ref):
        keys = self._keys()
        info, entry = keys.info(purpose), keys.entry(purpose, ref)
        if info is None or entry is None or keys.busy:
            self.notify(T["keys_busy"] if keys.busy else T["keys_fail_notfound"])
            return None
        form = RenameForm(keys.rename_dialog(info, entry), purpose, ref, self)
        self.dialog.clear()
        self.dialog.setAccessibleName(T["keys_ren_title"])
        self.dialog.layout_.addWidget(form)
        form.show()
        self._dialog_return = QApplication.focusWidget()
        self.dialog.present()
        self._trap_focus(True, self.dialog)
        form.edit.setFocus(Qt.OtherFocusReason)
        self.key_rename_form = form
        return form

    def key_rename(self, purpose, ref, name):
        """별칭 바꾸기 '바꾸기' — 문제가 있으면 대화상자에 남아 칸 옆에 문장이 보이고(입력은 남는다), 아니면 대화상자를 닫고 쓰기를 시작한다."""
        status, detail = self._keys().start_rename(purpose, ref, name, **self.keys_bridge.callbacks())
        if status == "invalid":
            return status, detail
        self.close_dialog()
        self._after_key_start(status, detail)
        return status, detail

    def _on_keys_written(self, outcome):
        self._guarded(self._show_keys_written, outcome, recover=self._recover_keys)

    def _on_keys_failed(self, failure):
        self._guarded(self._show_keys_failed, failure, recover=self._recover_keys)

    def _on_keys_cancelled(self):
        self._guarded(self._show_keys_failed, None, recover=self._recover_keys)

    def _reload_after_keys(self):
        """키 쓰기가 끝나 파일이 바뀌었다 — 연결 정보를 다시 읽는다(읽기 작업, 작업 스레드). 이미 읽는 중이면 그 읽기가 끝난 뒤의 값이 새 값이라 안내 없이 둔다."""
        keys = self._keys()
        if not keys.reload_wanted:
            return
        if self.state.conn_loading:                                                   # 이미 읽는 중이다 — 쓰기 전에 시작했을 수 있다: 그 읽기가 끝난 뒤(`_show_conn_*`) 한 번 더 읽는다
            keys.reloading = True
            return
        keys.reload_wanted = False
        job = self.state.start_conn_load(**self.conn_bridge.callbacks())          # 시작하지 못하면 단추를 꺼 두지 않는다(켜 둘 새 값이 영영 안 온다)
        keys.reloading = job is not None                                             # 새 값을 받을 때까지 단추는 꺼져 있다(`apply_connections` 가 켠다)

    def _want_key_focus(self):
        work = self._keys().pending or {}
        self._key_focus_wanted = (work.get("kind", ""), work.get("purpose", ""), self._key_click)

    def _show_keys_written(self, outcome):
        keys = self._keys()
        self._want_key_focus()
        keys.apply_write_ok(outcome)
        self._reload_after_keys()
        if self.state.page in ("settings", "home"):
            self.render()
        self._give_key_focus()                                                        # 새 값을 읽는 중이면 아직 안 된다 — 받은 뒤(`_show_conn_loaded`)에 돌려준다
        keys.focus_after = None

    def _give_key_focus(self):
        """쓰기가 끝나고 새 값으로 다시 그린 뒤 포커스를 돌려준다 — 행 단추는 방금 누른 단추(없어졌거나 꺼졌으면 반대쪽·다른 단추), 등록·삭제는 그 카드의 '키 등록'(못 누르면 아무 데도 두지 않는다).
        아직 쓰는 중이거나 새 값을 읽는 중이면 나중에, 다른 대화상자가 열려 있거나 설정 화면이 아니면 하지 않는다(대화상자·다른 화면의 포커스를 뺏지 않는다)."""
        wanted = self._key_focus_wanted
        if wanted is None or self._keys().busy:
            return
        self._key_focus_wanted = None
        if self.state.page != "settings" or self.dialog.is_open:
            return
        kind, purpose, (ref, action) = wanted
        if kind in ("add", "remove") or not ref:
            self._restore_focus(f"key-register:{purpose}")
            return
        candidates = {"up": ("up", "down"), "down": ("down", "up")}.get(action, (action, "test", "rename"))
        for name in candidates:
            for widget in self.centralWidget().findChildren(QWidget):
                if widget.property("focus_key") == f"key:{ref}:{name}" and widget.isEnabled() and widget.isVisibleTo(self):
                    widget.setFocus(Qt.OtherFocusReason)
                    return

    def _show_keys_failed(self, failure):
        keys = self._keys()
        work = (keys.pending or {}).get("kind", "")
        self._want_key_focus()
        kind = keys.apply_write_failed(failure)
        draft = keys.draft if work == "add" else None                                  # 등록이 아닌 쓰기의 실패는 등록 대화상자와 상관없다
        self._reload_after_keys()
        if self.state.page in ("settings", "home"):
            self.render()
        if draft is not None and kind in ("invalid", "duplicate", "terms") and self.state.page == "settings":
            self._key_focus_wanted = None
            self.show_key_dialog(draft)                                               # 고칠 수 있는 입력 문제 — 별칭은 남고 키는 다시 입력, 문제는 칸 옆에
        else:
            self._give_key_focus()

    def _recover_keys(self, error):
        """키 쓰기 슬롯에서 예외가 났다 — 쉬운 문장만 알리고(예외 이름·내용은 화면에 없다) 화면은 그대로 둔다. 표준 오류에도 **예외 이름만** 남긴다(내용은 싣지 않는다 — 키 입력과 닿는 곳이라 어떤 글도 새지 않게)."""
        report_unexpected(type(error), "")
        self._key_focus_wanted = None
        self._keys().apply_unexpected(error)
        try:
            if self.state.page in ("settings", "home"):
                self.render()
        except Exception:
            self.notify(T["job_failed"])

    def closeEvent(self, event):
        self.hide()                                                               # 창은 바로 사라지게 — 끝나지 않은 작업을 잠깐(최대 1초) 기다리는 동안 멈춘 창처럼 보이지 않게
        self.dialog.dismiss()                                                     # 열려 있는 키 입력 대화상자의 칸을 비운다(정리 훅)
        if self.state.keys.busy:                                                  # 키 쓰기도 중간에 끊을 수 없다 — 끝나기를 기다린다(보관소·파일 쓰기를 마치게)
            job = self.state.runner.job(KEYS_WRITE_KEY)
            if job is not None:
                job.join(WRITE_CLOSE_WAIT)
        if self.state.blogs.busy:                                                 # 저장·복제·삭제는 중간에 끊을 수 없다 — 끝나기를 기다린다(파일은 이름 바꾸기 한 번이라 온전하지만 사본·잠금 정리까지 마치게)
            job = self.state.runner.job(BLOGS_WRITE_KEY)
            if job is not None:
                job.join(WRITE_CLOSE_WAIT)
        if self.state.seeds.busy:                                                 # 승인·바꾸기·저장·등록도 중간에 끊을 수 없다 — 끝나기를 기다린다
            job = self.state.runner.job(SEEDS_WRITE_KEY)
            if job is not None:
                job.join(WRITE_CLOSE_WAIT)
        self.state.runner.cancel_all()
        self.state.runner.join_all(1.0)
        super().closeEvent(event)
