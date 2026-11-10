"""앱 틀(AppShell) — 상단 앱 바(`topbar.py`) + 왼쪽 사이드바(`sidebar.py` — 홈·설정 메뉴와 '다음 단계' 목록) + 본문(스크롤) + 겹쳐 뜨는 서랍·대화상자·토스트.

화면 이동·동작은 `AppState`(`ui/core/app_state.py`)가 하고 여기서는 그 결과를 다시 그리기만 한다. 후보 불러오기 같은 긴 일은 작업 스레드(`ui/core/jobs.py`)에서 돌고,
진행·완료·실패·취소는 시그널로 화면 스레드에 넘어온다 — 일하는 중에도 창이 반응한다.
서랍·대화상자가 열려 있는 동안 Tab 은 그 안에서만 돌고, Esc 로 닫으며(대화상자 먼저), 닫으면 열었던 곳으로 포커스가 돌아온다.
어느 메뉴가 어느 화면인지는 `screens.SCREEN_BUILDERS` 표가 정하고 `render()` 는 그 표만 거친다. 설정 화면의 연결 정보도 작업 스레드(`settings-load`)에서 읽고 시그널로 받는다 — 홈 불러오기와 따로다.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QHBoxLayout, QMainWindow, QScrollArea, QVBoxLayout, QWidget

from ..core import draft_rules, part_rules
from ..core import tokens as K
from ..core.app_state import AppState, report_unexpected
from ..core.blogs_view import WRITE_KEY as BLOGS_WRITE_KEY
from ..core.candidates import MakePreview
from ..core.candidates_view import WRITE_KEY as CANDIDATES_WRITE_KEY
from ..core.seeds_view import WRITE_KEY as SEEDS_WRITE_KEY
from ..core.keys_view import WRITE_KEY as KEYS_WRITE_KEY
from ..core.clock import SystemClock
from ..core.text import T
from ..core.version import read_version
from . import components as UI
from . import screens as S
from .key_parts import KeyDialog, RenameForm
from .candidate_parts import DetailPane
from .sidebar import Sidebar
from .topbar import TopBar
from .workers import JobBridge


RELAYOUT_AFTER_RESIZE_MS = 30                                                     # 창 크기가 바뀐 뒤 배치를 다시 계산하기까지 기다리는 시간 — 끌어 바꾸는 동안 계속 미루어진다
WRITE_CLOSE_WAIT = 10.0                                                           # 창을 닫을 때 저장·복제·삭제가 돌고 있으면 끝나기를 기다리는 최대 시간(초) — 쓰기는 중간에 끊을 수 없다
IMAGE_FILTER = "(*.png *.jpg *.jpeg *.webp)"                                       # 이미지 고르기 대화상자의 파일 종류(JPG·JPEG·PNG·WebP)


def _same_clipboard_text(read, wanted):
    """클립보드에서 읽은 글이 넣으려던 글과 같은가 — 줄바꿈·공백 차이(윈도 줄바꿈 방식 등)는 같은 글로 본다."""
    return isinstance(read, str) and "".join(read.split()) == "".join(wanted.split())


def qt_clipboard_set(text):
    """복사 — Qt 가 시스템 클립보드를 다룬다(줄바꿈은 알아서 윈도 방식으로). **쓴 뒤 다시 읽어 같은지 본다**: 다른 프로그램이 클립보드를 잡고 있어 쓰지 못했으면 False 라서
    화면이 '복사됨' 이 아니라 '복사하지 못했어요' 를 보인다(독립 검증 V7 — 예전에는 쓰지 못해도 늘 True 였다). 실제 윈도 클립보드의 실패 모습은 운영자 PC 에서 확인한다."""
    clipboard = QGuiApplication.clipboard()
    clipboard.setText(text)
    return _same_clipboard_text(clipboard.text(), text)


def qt_clipboard_wipe(texts):
    """클립보드의 글이 `texts` 중 하나와 (줄바꿈·앞뒤 공백을 뺀 뒤) 같으면 클립보드를 비운다 → 비웠으면 True. **붙여 넣은 키가 클립보드에 그대로 남지 않게** 하려는 것이다 — 다른 글(사용자가 따로 복사한 것)은 건드리지 않고 앱이 클립보드에 글을 넣는 일은 없다."""
    clipboard = QGuiApplication.clipboard()
    current = "".join(clipboard.text().splitlines()).strip()
    if current and any(current == "".join(text.splitlines()).strip() for text in texts):
        clipboard.clear()
        return True
    return False


def qt_open_url(url):
    """주소를 기본 브라우저로 연다(`네이버 글쓰기 열기`) — **주소만 연다**(로그인·입력·발행은 하지 않는다). 열었으면 True. 시험·사진은 이 함수 대신 가짜 열기 함수를 넣는다."""
    return bool(QDesktopServices.openUrl(QUrl(url)))


def qt_file_picker(parent, title, filter_text):
    """이미지 파일 하나를 고르는 윈도 대화상자 — 고른 파일의 **위치**(고르지 않으면 빈 글). 파일을 읽거나 복사하지 않는다(시험은 이 대화상자 대신 가짜 선택기를 넣는다)."""
    path, _selected = QFileDialog.getOpenFileName(parent, title, "", filter_text)
    return path


class AppShell(QMainWindow):
    def __init__(self, provider=None, *, connections=None, clipboard=None, runner=None, clock=None, version_info=None, autoload=True, blogs=None, file_picker=None, seeds=None, clipboard_wipe=None, candidates=None, drafts=None, url_opener=None):
        super().__init__()
        self.version_info = version_info or read_version()                                # 사이드바 아래에 보일 버전(`v0.0.0` 또는 `개발 버전`)
        self.clock = clock or SystemClock()                                              # 시계는 주입한다(시험·사진은 가짜 시계) — 위젯이 `datetime.now()` 를 직접 부르지 않는다
        self._relayout_timer = QTimer(self)                                              # 다시 그린 뒤·창 크기를 바꾼 뒤 한 번, 화면의 배치를 처음부터 다시 계산한다(굳어 버린 행 높이를 푼다 — `screens.relayout_screen`)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._relayout)
        self.state = AppState(provider, runner=runner, connections=connections, version=self.version_info, blogs=blogs, seeds=seeds, candidates=candidates, drafts=drafts)           # 설정 화면의 '정보' 묶음이 사이드바와 같은 버전을 보인다
        self._clipboard = clipboard or qt_clipboard_set
        self._url_opener = url_opener or qt_open_url                                     # 네이버 글쓰기 주소를 여는 함수(시험·사진은 가짜 열기 함수를 주입한다 — 주소만 연다)
        self._copy_timers = {}                                                           # 복사 단추의 `✓ … 복사됨` 모양을 되돌리는 시간 재개(복사한 항목마다 하나)
        self._close_confirmed = False                                                    # 앱을 닫을 때 고친 내용이 사라진다는 확인창에서 `그래도 닫기` 를 눌렀다
        self._drafts_side = None                                                         # 초안 화면을 그릴 때의 두 칸 배치 여부(창 논리 폭이 문턱을 넘으면 다시 그린다)
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
        self.detail_pane = DetailPane()                                                  # 주제 후보 화면의 고정 상세 창 — 본문 오른쪽에 붙고 논리 폭 1366 이상일 때만 보인다(그보다 좁으면 서랍)
        middle.addWidget(self.detail_pane)
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
        self._detail_layout = None                                                      # 주제 후보 화면을 그릴 때의 상세 창 방식·열 수(창 폭이 문턱을 넘으면 다시 그린다)
        self.detail_close = None
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
        self.cand_bridge = JobBridge(self)                                              # 주제 후보를 읽는 작업의 다리 — 홈·설정·블로그·Seed 읽기와 따로 돈다
        self.cand_bridge.loaded.connect(self._on_cand_loaded)
        self.cand_bridge.failed.connect(self._on_cand_failed)
        self.cand_bridge.cancelled.connect(self._on_cand_cancelled)
        self.cand_write_bridge = JobBridge(self)                                        # 만들 후보 미리 보기(읽기뿐)와 후보 만들기(파일에 쓰는 일 하나)의 다리 — 사용자가 단추를 눌렀을 때만 시작한다
        self.cand_write_bridge.loaded.connect(self._on_cand_written)
        self.cand_write_bridge.failed.connect(self._on_cand_write_failed)
        self.cand_write_bridge.cancelled.connect(self._on_cand_write_cancelled)
        self.drafts_bridge = JobBridge(self)                                            # 초안 만들기(읽기뿐 — 아무것도 저장하지 않는다)의 다리 — 후보 화면의 `이 주제로 만들기` 와 `다시 만들기` 를 눌렀을 때만 시작한다
        self.drafts_bridge.loaded.connect(self._on_drafts_made)
        self.drafts_bridge.failed.connect(self._on_drafts_failed)
        self.drafts_bridge.cancelled.connect(self._on_drafts_cancelled)
        self.garbage_bridge = JobBridge(self)                                           # 글 모양 점검(N-2)의 다리 — 작업 스레드가 돌려준 결과 값(걸린 글 없음)을 화면 스레드로 넘긴다. 초안 만들기와 따로 돈다
        self.garbage_bridge.loaded.connect(self._drf_garbage_arrived)
        self.garbage_bridge.failed.connect(self._drf_garbage_failed)
        self.garbage_bridge.cancelled.connect(self._drf_garbage_cancelled)
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
        self._detail_layout = self.detail_layout() if state.page == "topics" else None   # 주제 후보 화면은 창의 논리 폭이 상세 창 방식(고정·서랍)과 카드 열 수를 정한다 — 고른 후보는 방식이 바뀌어도 컨트롤러에 그대로 있다
        if self._detail_layout is not None:
            state.candidates.set_layout(self._detail_layout.mode)
        self._drafts_side = draft_rules.side_by_side(self.width()) if state.page == "drafts" else None        # 초안 화면은 창의 논리 폭이 오른쪽 칸을 옆에 둘지 아래로 내릴지 정한다
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
        self._sync_detail()
        self._sync_overlays(key)
        if key and self._modal() is None:
            self._restore_focus(key)
        self._relayout_timer.start(0)                                         # 새 위젯이 보이고 글꼴이 입혀진 다음 한 번 더 배치를 맞춘다

    def _relayout(self):
        S.relayout_screen(self.scroll.widget())

    def detail_layout(self):
        """창의 **논리 폭**(Qt 가 윈도 배율을 이미 나눈 값 — 물리 해상도가 아니다)이 정하는 상세 창 방식(고정·서랍)과 카드 열 수 — 규칙은 `part_rules.detail_layout`(운영자 결정 2026-11-06 확인 요청 004)."""
        return part_rules.detail_layout(max(1, self.width()))

    def _sync_detail(self):
        """주제 후보 화면의 고정 상세 창 — 고정 방식일 때만 보이고(고른 후보의 상세 또는 비었을 때의 안내), 서랍 방식이거나 다른 화면이면 숨는다."""
        layout = self._detail_layout
        if self.state.page != "topics" or layout is None or layout.mode != "fixed" or not self.state.candidates.pane_visible():
            self.detail_pane.dismiss()
            self.detail_close = None
            return
        from .candidate_screen import detail_content, detail_footer, pane_placeholder
        view = self.state.candidates.detail_view()
        if view is None:
            self.detail_pane.set_content(pane_placeholder(self.state.candidates.pane_empty()), focusable=False)
            self.detail_close = None
        else:
            content, self.detail_close = detail_content(self, view)
            self.detail_pane.set_content(content, footer=detail_footer(self, view))                    # 아래 고정 행동 줄(P4e) — `이 주제로 만들기`
        self.detail_pane.present(layout.detail_width)
        ui = getattr(self.screen_widget, "cand_ui", None)                          # Tab 순서: 본문(거르기 → 카드) 다음에 상세 창(스크롤 → 닫기 → 번호 복사)
        body = ui.grid.stops() if ui is not None and ui.grid is not None else []
        last = body[-1] if body else (ui.reset if ui is not None else None)
        chain = [widget for widget in (last, *self.detail_pane.stops()) if widget is not None]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

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
        cand_view = state.candidates_drawer_view()                                # 주제 후보의 서랍 방식 상세(창 논리 폭 1366 미만) — 그 화면에서만 있다
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
        elif cand_view is not None and view is None and seed_view is None and not self.dialog.is_open:
            from .candidate_screen import detail_content, detail_footer
            content, self.drawer_close = detail_content(self, cand_view)
            self.drawer.set_content(content, detail_footer(self, cand_view))                              # 서랍 방식에도 같은 아래 고정 행동 줄(P4e)
            self.drawer.setAccessibleName(cand_view["a11y"])                       # 서랍 틀의 읽기용 이름도 이 내용의 것이다
            self.drawer.scroll.setAccessibleName(cand_view["a11y"])
            if not self.drawer.is_open:
                self._drawer_return = self._drawer_return or QApplication.focusWidget()
                self.drawer.open()
            self._trap_focus(True, self.drawer)
            if not self.drawer.scroll.isAncestorOf(QApplication.focusWidget()):
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
        elif view is None and seed_view is None and cand_view is None and self.drawer.is_open:
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
        self._restore_focus(opened if opened.startswith(("seed:", "cand:")) else "detail:" + opened)
        if QApplication.focusWidget() is None and target is not None:
            target.setFocus(Qt.OtherFocusReason)

    def open_drawer(self, topic_id):
        if self.state.open_drawer(topic_id):
            self._drawer_return = QApplication.focusWidget()
            self.render()

    def show_dialog(self, title, body, ok=None, cancel=None, on_ok=None, danger=False, safe_focus=False, on_cancel=None):
        """가운데 대화상자 — 제목·본문·단추. 처음 포커스는 기본 단추에 있고 Esc·취소로 닫는다. `danger` 면 확인 단추가 위험 단추(최종 삭제 확인 — 빨간 배경)이고, `safe_focus` 면 처음 포커스가 취소에 있다(Enter 를 잘못 눌러도 지워지지 않는다).
        열린 확인창을 다른 대화상자로 **바꿀 때**는 옛 확인창이 확인 없이 닫힌 셈이라 옛 `on_cancel` 을 먼저 부른다('확인창을 보였다' 표시를 거둔다 — 안 그러면 표시가 남아 확인 없이 쓰기가 시작될 수 있다). 새 대화상자가 같은 `on_cancel`(같은 표시)을 이어받으면 부르지 않는다 — 방금 켠 표시를 거두지 않으려고."""
        previous, self._dialog_on_cancel = self._dialog_on_cancel, None
        if previous is not None and previous != on_cancel:
            previous()
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
        self.show_dialog(T["sample_dialog_title"], {"settings": T["conn_sample_dialog_body"], "blogs": T["blogs_sample_dialog_body"], "seed": T["seeds_sample_dialog_body"], "topics": T["cand_sample_dialog_body"], "drafts": T["drf_sample_dialog_body"]}.get(screen, T["sample_dialog_body"]))

    def escape(self):
        if self.dialog.is_open:
            self.close_dialog()
        else:
            self.close_drawer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_timer.start(RELAYOUT_AFTER_RESIZE_MS)                  # 끌어 바꾸는 동안은 미루고 멈춘 뒤 한 번만
        if self.state.page == "topics" and self._detail_layout is not None and self.detail_layout() != self._detail_layout:
            self.render()                                                      # 상세 창 방식·카드 열 수가 바뀌는 문턱(논리 폭 1600·1366)을 넘었다 — 고른 후보는 컨트롤러가 들고 있어 그대로다
        elif self.state.page == "drafts" and self._drafts_side is not None and draft_rules.side_by_side(self.width()) != self._drafts_side:
            self.render()                                                      # 오른쪽 칸을 옆에 둘지 아래로 내릴지 바뀌는 문턱(논리 폭 1280)을 넘었다 — 제목·본문·고친 내용은 컨트롤러가 들고 있어 그대로 다시 놓인다
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

    def _sync_nav_checks(self):
        """사이드바 메뉴 단추의 눌림 표시를 지금 화면에 맞춘다(눌렀지만 확인창에서 막혔을 때 누른 단추가 눌린 채로 남지 않게)."""
        for nav_key, button in self.nav_buttons.items():
            button.setChecked(nav_key == self.state.page)

    def go(self, key, force=False):
        """화면을 옮긴다. 초안 작성 화면에서 고친 내용이 사라지는 이동이면 확인창이 먼저다(처음 포커스는 취소 — `그래도 이동` 을 눌러야 `force` 로 옮긴다). 고친 곳이 없으면 바로 옮기고 초안은 메모리에서 지운다."""
        dialog = None if force else self.state.leave_guard(key)
        if dialog is not None:
            self._sync_nav_checks()
            self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=lambda: self.go(key, force=True), safe_focus=True, on_cancel=self.state.drafts.discard_leave)
            return
        if self.state.nav(key, force=force):
            self.close_drawer_silently()
            if key == "settings":                                                     # 설정 화면은 열 때마다 읽는다(이미 읽는 중이면 그대로 둔다) — 읽기는 작업 스레드에서
                self.state.start_conn_load(**self.conn_bridge.callbacks())
            elif key == "blogs":                                                      # 블로그 관리 화면도 열 때마다 읽는다(읽기만 — 파일도 폴더도 만들지 않는다). 쓰는 중이면 읽지 않는다
                self.state.blogs.start_load(**self.blogs_bridge.callbacks())
            elif key == "seed":                                                       # Seed 관리 화면도 열 때마다 읽는다(읽기만). 쓰는 중이면 읽지 않는다
                self.state.seeds.start_load(**self.seeds_bridge.callbacks())
            elif key == "topics":                                                     # 주제 후보 화면도 열 때마다 읽는다(읽기만 — 열기만으로는 아무것도 만들지 않는다). 만드는 중이면 읽지 않는다
                self.state.candidates.start_load(**self.cand_bridge.callbacks())
            self.render()

    def close_drawer_silently(self):
        self.state.close_drawer(silent=True)
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

    # ---- 주제 후보 화면 — 읽기는 작업 스레드, 쓰기(후보 만들기)는 확인창에서 `만들기` 를 눌렀을 때만 따로 시작하는 작업 하나. 거르기·찾기·고르기·상세·창 크기 바꾸기는 파일에 닿지 않는다 ----
    def reload_candidates(self, *_):
        """후보를 다시 읽는다(읽기만). 이미 읽는 중이거나 만드는 중이면 안내만 한다."""
        job = self.state.candidates.start_load(**self.cand_bridge.callbacks())
        if job is None:
            self.notify(T["load_busy"])
            return False
        self.render()
        return True

    def _render_candidates(self):
        if self.state.page == "topics":                                          # 다른 화면을 보는 중이면 값만 받아 두고 다시 그리지 않는다
            self.render()

    def cand_channel(self, key):
        if self.state.candidates.set_channel(key):
            self.render()

    def cand_status(self, key):
        if self.state.candidates.set_status(key):
            self.render()

    def cand_band(self, key):
        if self.state.candidates.set_band(key):
            self.render()

    def cand_cluster(self, key):
        if self.state.candidates.set_cluster(key):
            self.render()

    def cand_query(self, text):
        """글 검색 — 카드 격자만 새로 놓는다(검색 칸은 그대로라 커서·한글 조합이 안 튄다). 친 글은 메모리에만 있다."""
        if self.state.candidates.set_query(text) and self.state.page == "topics" and self.screen_widget is not None:
            from .candidate_screen import refilter_candidates_live
            refilter_candidates_live(self.screen_widget, self.state.candidates_view())

    def cand_toggle_filters(self):
        self.state.candidates.toggle_more_filters()
        self.render()

    def cand_reset_filters(self):
        self.state.candidates.reset_filters()
        self.render()

    def cand_more(self):
        self.state.candidates.show_more()
        self.render()

    def cand_open(self, candidate_id):
        """카드를 눌러 상세를 연다(읽기뿐) — 고정 방식이면 오른쪽 창에, 서랍 방식이면 서랍에. 서랍을 닫으면 이 카드로 포커스가 돌아온다."""
        returning = QApplication.focusWidget()
        if self.state.candidates.select(candidate_id):
            self._drawer_return = returning
            self.render()

    def cand_copy(self, number):
        """후보 번호(짧은 번호만)를 클립보드에 복사하고 안내한다 — 클립보드에는 번호만 간다."""
        self.notify(number["copied"] if self.copy(number["ref"]) else number["failed"])

    def cand_make(self):
        """`후보 만들기` — 먼저 만들 후보를 미리 본다(읽기뿐). 미리 보기가 끝나면 새 후보가 있을 때만 확인창이 뜬다(`_show_cand_written`). 이 단계에서는 아무것도 쓰지 않는다."""
        status, _detail = self.state.candidates.start_preview(**self.cand_write_bridge.callbacks())
        if status == "started":
            self.render()
        elif status == "busy":
            self.notify(T["load_busy"])
        else:
            self.notify(self.state.candidates.make_info()[1])

    def _show_make_dialog(self):
        """미리 본 결과의 확인창 — 처음 포커스는 취소(Enter 를 잘못 눌러도 만들지 않는다). `만들기` 를 눌러야 쓰기가 시작되고, 취소·Esc 로 닫으면 '확인창을 보였다' 표시도 거둔다."""
        candidates = self.state.candidates
        dialog = candidates.make_dialog()
        if dialog is None:
            return
        self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=self.cand_make_confirmed, safe_focus=True, on_cancel=candidates.discard_make)

    def cand_make_confirmed(self):
        status, _detail = self.state.candidates.start_make(**self.cand_write_bridge.callbacks())
        if status == "started":
            self.render()

    def cand_prep_action(self, key):
        """준비 안내 카드의 단추 — 이미 있는 화면(Seed 관리·블로그 관리)으로 가거나 카드를 닫는다. 새 화면·쓰기는 없다."""
        if key == "close":
            self.state.candidates.close_preview()
            self.render()
        elif key in ("seed", "blogs"):
            self.state.candidates.close_preview()
            self.go(key)

    def _on_cand_loaded(self, data):
        self._guarded(self._show_cand_loaded, data, recover=self._recover_cand)

    def _on_cand_failed(self, failure):
        self._guarded(self._show_cand_failed, failure, recover=self._recover_cand)

    def _on_cand_cancelled(self):
        self._guarded(self._show_cand_cancelled, recover=self._recover_cand)

    def _show_cand_loaded(self, data):
        self.state.candidates.apply_loaded(data)
        self._render_candidates()

    def _show_cand_failed(self, failure):
        self.state.candidates.apply_load_failed(failure, self.clock.now())
        self._render_candidates()

    def _show_cand_cancelled(self):
        self.state.candidates.apply_cancelled()
        self._render_candidates()

    def _on_cand_written(self, result):
        self._guarded(self._show_cand_written, result, recover=self._recover_cand_write)

    def _on_cand_write_failed(self, failure):
        self._guarded(self._show_cand_write_failed, failure, recover=self._recover_cand_write)

    def _on_cand_write_cancelled(self):
        self._guarded(self._show_cand_write_failed, None, recover=self._recover_cand_write)

    def _show_cand_written(self, result):
        self.state.candidates.apply_write_ok(result)
        self._render_candidates()
        if isinstance(result, MakePreview):
            self._show_make_dialog()                                              # 미리 보기가 끝났다 — 새 후보가 있으면 확인창(없으면 준비 안내 카드가 이미 그려졌다)
        else:
            self.reload_candidates()                                              # 만들었다 — 목록을 다시 읽는다(읽기만)

    def _show_cand_write_failed(self, failure):
        self.state.candidates.apply_write_failed(failure)
        self._render_candidates()

    def _recover_cand(self, error):
        """주제 후보 슬롯에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)
        self.state.candidates.apply_unexpected(error, self.clock.now())
        try:
            self._render_candidates()
        except Exception:
            self.notify(T["job_failed"])

    def _recover_cand_write(self, error):
        report_unexpected(type(error), error)
        self.state.candidates.apply_write_unexpected(error)
        try:
            self._render_candidates()
        except Exception:
            self.notify(T["job_failed"])

    # ---- 초안 작성 화면(P4e) — **아무것도 저장하지 않는다**(읽기·고치기·복사뿐). 초안 만들기는 작업 스레드에서 읽기만 하고, 클립보드에는 사용자가 단추를 눌러 복사 전 관문(`copy_decision`)을 지났을 때만 쓴다. 글을 칠 때는 화면 전체를 다시 그리지 않는다 ----
    def cand_make_draft(self):
        """후보 상세의 `이 주제로 만들기` — 고른 후보로 초안 화면을 열고 초안을 만든다(읽기뿐 — 후보 상태·보관함은 바뀌지 않는다). 안전 판정 중지 후보는 단추가 꺼져 있고 이 길에서도 화면 상태가 공급자를 부르지 않고 거절한다."""
        view = self.state.candidates.detail_view()
        if view is None:
            return
        if not view["draft"]["enabled"]:                                             # 꺼 둔 단추(중지 후보·네이버가 아닌 채널·만드는 중)를 코드로 불러도 초안 화면을 열지 않는다 — 까닭만 알린다
            self.notify(view["draft"]["reason"])
            return
        target = self.state.candidates.draft_target()
        if target is None:
            return
        self.state.drafts.open_target(target)
        self.go("drafts")
        self._start_draft()

    def _start_draft(self):
        status, _job = self.state.drafts.start_make(**self.drafts_bridge.callbacks())
        if status == "busy":
            self.notify(T["load_busy"])
        self.render()                                                              # 읽는 중(또는 거절) 모습으로 다시 그린다

    def drf_retry(self):
        """오류 화면의 `다시 만들기` — 같은 후보로 처음부터 다시 만든다."""
        self._start_draft()

    def drf_to_topics(self):
        """초안 화면의 `← 주제 후보`·`주제 후보로 가기` — 이미 있는 주제 후보 화면으로 간다(고친 내용이 있으면 `go` 가 확인창을 먼저 띄운다). 화면 부품은 화면 이동을 직접 부르지 않고 이 함수로 요청한다."""
        self.go("topics")

    def _render_drafts(self):
        if self.state.page == "drafts":                                          # 다른 화면을 보는 중이면 값만 받아 둔다(떠난 뒤에 온 답은 컨트롤러가 버린다)
            self.render()

    def _on_drafts_made(self, result):
        self._guarded(self._show_drafts_made, result, recover=self._recover_drafts)

    def _on_drafts_failed(self, failure):
        self._guarded(self._show_drafts_failed, failure, recover=self._recover_drafts)

    def _on_drafts_cancelled(self):
        self._guarded(self._show_drafts_cancelled, recover=self._recover_drafts)

    def _show_drafts_made(self, result):
        self.state.drafts.apply_made(result)
        self._render_drafts()

    def _show_drafts_failed(self, failure):
        self.state.drafts.apply_make_failed(failure, self.clock.now())
        self._render_drafts()

    def _show_drafts_cancelled(self):
        self.state.drafts.apply_cancelled()
        self._render_drafts()

    def _recover_drafts(self, error):
        """초안 슬롯에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)
        self.state.drafts.apply_unexpected(error, self.clock.now())
        try:
            self._render_drafts()
        except Exception:
            self.notify(T["job_failed"])

    def _drafts_screen(self):
        """지금 그려진 초안 화면(그 자리에서 고칠 부품을 들고 있는 것) — 다른 화면이면 None."""
        page = self.screen_widget
        return page if self.state.page == "drafts" and page is not None and hasattr(page, "drf_ui") else None

    def _live_drafts(self, *, picks=False, status=False, inspect=False, options=False, garbage=False):
        """글을 고친 뒤 — 화면을 다시 그리지 않고 글자 수·고친 정도·제목 후보 표시·검사 카드·글 모양 점검 카드(`본문이 변경됨`)·만드는 방법 칸만 그 자리에서 바꾼다(입력 중이던 커서·한글 조합이 사라지지 않게)."""
        page = self._drafts_screen()
        if page is None:
            return
        from . import draft_screen as ds
        controller = self.state.drafts
        if status:
            ds.refresh_editor_status(page, controller.editor_status())
        if picks:
            ds.refresh_picks(page, controller.title_picks())
        if inspect:
            ds.refresh_inspection(page, controller.inspect_card())
        if garbage:
            ds.refresh_garbage(page, controller.garbage_card())
        if options:
            ds.refresh_options(page, controller.options_vm())

    def drf_title_edited(self, text):
        self.state.drafts.set_title(text)
        self._live_drafts(picks=True, status=True, inspect=True, garbage=True)

    def drf_body_edited(self, text):
        self.state.drafts.set_body(text)
        self._live_drafts(status=True, inspect=True, garbage=True)

    def drf_option_edited(self, name, text):
        if self.state.drafts.set_option(name, text):
            self._live_drafts(options=True)

    def drf_pick(self, index):
        """제목 후보를 고른다 — 고친 제목이 있으면 사라지므로 확인창이 먼저다(처음 포커스는 취소)."""
        controller = self.state.drafts
        status = controller.pick_title(index)
        if status == "ok":
            self._show_picked_title()
        elif status == "confirm":
            dialog = controller.pick_dialog()
            self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=self.drf_pick_confirmed, safe_focus=True, on_cancel=controller.discard_pick)

    def drf_pick_confirmed(self):
        if self.state.drafts.confirm_pick():
            self._show_picked_title()

    def _show_picked_title(self):
        page = self._drafts_screen()
        if page is not None:
            from . import draft_screen as ds
            ds.show_title(page, self.state.drafts.title)
        self._live_drafts(picks=True, status=True, inspect=True)

    def drf_inspect(self):
        """`검사하기` — 편집기의 제목·본문을 훑는다(읽기뿐). 결과는 검사 카드에 보이고 파일·클립보드는 바뀌지 않는다. 글 모양 점검도 이 단추로만 시작한다(**글 모양 점검은** 작업 스레드 — 결과는 따로 선 카드에 나중에 채워지고
        그동안 이 단추는 `검사 중…` 으로 꺼진다). 글을 치는 동안이나 복사할 때는 부르지 않는다. 같은 단추의 기존 검사(`inspect()`)는 아직 화면 스레드에서 동기로 돈다 — 수천 자는 순식간이지만 10만 자는 4초 안팎이다(M036 부터 있던 것, 같은 길로 옮기는 일은 후속 — D-320)."""
        controller = self.state.drafts
        controller.inspect()
        controller.start_garbage(**self.garbage_bridge.callbacks())
        self._live_drafts(inspect=True, garbage=True)

    def _drf_garbage_arrived(self, result):
        self._guarded(self._drf_garbage_show, result, recover=self._drf_garbage_recover)

    def _drf_garbage_show(self, result):
        if self.state.drafts.apply_garbage(result):                                  # 세대가 다른(새 초안·떠난 뒤의) 결과는 받지 않는다
            self._live_drafts(garbage=True)

    def _drf_garbage_failed(self, failure):
        self._guarded(self._drf_garbage_fail_show, failure, recover=self._drf_garbage_recover)

    def _drf_garbage_fail_show(self, failure):
        if self.state.drafts.apply_garbage_failed(failure):
            self._live_drafts(garbage=True)

    def _drf_garbage_cancelled(self):
        self.state.drafts.apply_garbage_cancelled()

    def _drf_garbage_recover(self, error):
        """결과를 그리다 예외가 났다 — 먼저 한 번 다시 그려 본다(한 번만 난 예외면 결과가 그대로 보인다). 또 실패하면 이 카드만 `점검을 끝내지 못했어요` 로 두고(`abandon()` — 도는 중으로 남지 않는다) 초안 화면은 그대로다(글 모양 점검은 경고뿐이라 다른 것을 멈추지 않는다).
        실패 카드를 그리는 코드까지 예외를 내면 안내 한 줄만 띄운다."""
        report_unexpected(type(error), error)
        try:
            self._live_drafts(garbage=True)
        except Exception:
            self.state.drafts.garbage.abandon()
            try:
                self._live_drafts(garbage=True)
            except Exception:
                self.notify(T["job_failed"])

    def drf_garbage_ignore(self, key):
        """`무시` — 그 경고(같은 지문은 모두)를 이 화면의 메모리에서만 숨긴다. 글·복사·파일은 바뀌지 않는다."""
        page = self._drafts_screen()
        from . import draft_screen as ds
        index = ds.garbage_button_index(page, key) if page is not None else -1
        if self.state.drafts.ignore_garbage(key):
            self._live_drafts(garbage=True)
            if page is not None:
                ds.focus_garbage(page, index)

    def drf_garbage_ignore_all(self):
        if self.state.drafts.ignore_all_garbage():
            self._live_drafts(garbage=True)
            page = self._drafts_screen()
            if page is not None:
                from . import draft_screen as ds
                ds.focus_garbage(page, 0)

    def drf_garbage_restore(self):
        if self.state.drafts.restore_garbage():
            self._live_drafts(garbage=True)
            page = self._drafts_screen()
            if page is not None:
                from . import draft_screen as ds
                ds.focus_garbage(page, 0)

    def drf_toggle_options(self):
        self.state.drafts.toggle_options()
        self._live_drafts(options=True)

    def drf_blog(self, key):
        if self.state.drafts.set_blog(key):
            self._live_drafts(options=True)

    def drf_post_type(self, key):
        if self.state.drafts.set_post_type(key):
            self._live_drafts(options=True)

    def drf_toggle_image(self):
        self.state.drafts.toggle_image()
        page = self._drafts_screen()
        if page is not None:
            from . import draft_screen as ds
            ds.refresh_image(page, self.state.drafts.view()["normal"]["side"]["image"])

    def drf_checks_toggled(self, key, opened):
        """확인 권장의 펼침·접힘을 기억만 한다(다시 그리지 않는다) — 모든 글 공통 묶음만 기억한다."""
        if key == "common":
            self.state.drafts.set_common_open(opened)

    def drf_remake(self):
        """`다시 만들기` — 고친 제목·본문이 사라지면 확인창이 먼저다(처음 포커스는 취소). 바꾼 블로그·글 유형·선택 입력으로 새 초안을 만든다(읽기뿐)."""
        controller = self.state.drafts
        dialog = controller.regen_dialog()
        if dialog is not None:
            self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=self.drf_remake_confirmed, safe_focus=True, on_cancel=controller.discard_regen)
            return
        self.drf_remake_confirmed()

    def drf_remake_confirmed(self):
        status, _job = self.state.drafts.start_regenerate(**self.drafts_bridge.callbacks())
        if status == "started":
            self.render()
        elif status == "busy":
            self.notify(T["load_busy"])

    def drf_action(self, key):
        """아래 고정 행동 줄의 단추(`더보기 ⋮` 로 접힌 것 포함) — `네이버 글쓰기 열기` 는 주소만 열고 나머지는 복사다."""
        if key == "open":
            self.drf_open()
        else:
            self.drf_copy(key)

    def drf_copy(self, item):
        """복사 단추 — **복사 전 관문**을 지난 글만 클립보드에 쓴다: 키·토큰 모양이면 막고(안내창), 이 글에만 해당하는 확인 권장·분야 못 읽음·점검 걸림·거의 안 고침이 있으면 확인창이 먼저다(처음 포커스는 취소).
        클립보드에 쓰는 곳은 `_drf_do_copy` 하나이고 그곳은 관문이 '복사해도 된다' 고 한 글이나 확인창의 `그래도 복사` 를 거친 글만 받는다."""
        controller = self.state.drafts
        kind, payload = controller.copy_decision(item)
        if kind == "copy":
            self._drf_do_copy(item, payload)
        elif kind == "blocked":
            self.show_dialog(payload["title"], payload["body"], ok=payload["ok"], cancel=None)
        elif kind == "confirm":
            self.show_dialog(payload["title"], payload["body"], ok=payload["ok"], cancel=payload["cancel"], on_ok=lambda: self.drf_copy_confirmed(item), safe_focus=True, on_cancel=controller.discard_copy)

    def drf_copy_confirmed(self, item):
        text = self.state.drafts.confirm_copy(item)
        if text is None:
            self.notify(T["drf_copy_failed"])
            return
        self._drf_do_copy(item, text)

    def _drf_do_copy(self, item, text):
        if not self.copy(text):
            self.notify(T["drf_copy_failed"])
            return
        controller = self.state.drafts
        controller.mark_copied(item)
        self._show_copy_look(item, True)
        timer = self._copy_timers.get(item)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda item=item: self._clear_copy_look(item))
            self._copy_timers[item] = timer
        timer.start(K.COPY_FEEDBACK_MS)                                              # 1.5~2초(C-Type §10.6) 동안 `✓ 본문 복사됨` — 성공색과 글자가 함께 바뀐다

    def _show_copy_look(self, item, copied):
        page = self._drafts_screen()
        if page is not None:
            from . import draft_screen as ds
            ds.show_copy(page, item, self.state.drafts.copied_text(item), copied)

    def _clear_copy_look(self, item):
        self.state.drafts.clear_copied(item)
        self._show_copy_look(item, False)

    def drf_open(self):
        """`네이버 글쓰기 열기` — **주소만 연다**(자동 로그인·입력·발행 없음). 프로필의 블로그 주소가 `https://blog.naver.com/<아이디>` 모양이 아니면 단추가 꺼져 있고 이 길에서도 열지 않는다."""
        url, why = self.state.drafts.open_info()
        if not url.startswith("https://blog.naver.com/"):
            self.notify(why or T["drf_open_why_profile"])
            return
        try:
            opened = self._url_opener(url)
        except Exception:                                                            # 브라우저를 못 여는 환경 — 주소는 오류에 담지 않는다
            opened = False
        if not opened:
            self.notify(T["drf_open_failed"])

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

    def _close_after_confirm(self):
        self._close_confirmed = True
        self.close()

    def closeEvent(self, event):
        # 윈도가 종료·로그오프 중이면 확인창으로 붙잡지 않는다(고친 내용은 사라진다 — 저장하지 않는 화면이다, D-281). 참고(독립 검증 V10): 실제 윈도 Qt 6.12 는 종료 질의에 `commitDataRequest` 만 내고 곧바로 종료를 허용해서
        # 이 `closeEvent` 는 종료 때 아예 불리지 않는다 — 확인창이 종료를 붙잡지 않는 결과는 같고, 아래 분기는 세션 종료 중에 창 닫기가 오는 다른 길(플랫폼·Qt 판 차이)을 위한 보험이다. 동작은 그대로다.
        if not self._close_confirmed and not QGuiApplication.instance().isSavingSession():
            dialog = self.state.close_guard()                                     # 초안의 고친 내용은 저장하지 않아 앱을 닫으면 사라진다 — 확인창이 먼저다(처음 포커스는 취소)
            if dialog is not None:
                event.ignore()
                self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=self._close_after_confirm, safe_focus=True, on_cancel=self.state.drafts.discard_leave)
                return
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
        if self.state.candidates.busy:                                            # 후보 만들기도 중간에 끊을 수 없다(한 트랜잭션) — 끝나기를 기다린다
            job = self.state.runner.job(CANDIDATES_WRITE_KEY)
            if job is not None:
                job.join(WRITE_CLOSE_WAIT)
        self.state.drafts.shutdown()                                              # 도는 글 모양 점검의 답은 버린다 — 작업자 종료를 기다리지 않는다(끝난 스레드의 답은 어디에도 보이지 않는다)
        self.state.runner.cancel_all()
        self.state.runner.join_all(1.0)
        super().closeEvent(event)
