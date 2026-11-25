"""발행 기록 화면(글 흐름 1b, 결정 D-649·D-650)의 앱 틀 쪽 동작 — `AppShell` 에 섞어 쓰는 묶음(`HistoryFlowMixin`). 눌림을 컨트롤러(`HistoryController`)로 넘기고 작업 스레드의 읽기 결과를 받아 화면을 다시 그린다.
**읽기뿐이다**: 목록(`history-load`)과 작업 로그(`history-log`)는 따로 읽는 두 작업이고, 쓰는 일은 하나도 없다(주소 복사는 셸의 기존 복사 길 — 클립보드뿐). 이 파일에는 파일을 만지는 호출·네트워크·하위 프로세스·표준 출력이 없다 —
서비스는 어댑터(`ui/posts_adapter.py`)만 부른다.
"""
from __future__ import annotations

from ..core.app_state import report_unexpected
from ..core.text import T
from .workers import JobBridge


class HistoryFlowMixin:
    # ---- 만들기 ----
    def _init_history(self):
        """발행 기록의 작업 다리 둘 — 목록 읽기와 작업 로그 읽기가 따로 돈다(글 검토·홈·설정의 읽기와도 따로다)."""
        for name, loaded, failed, cancelled in (("history_bridge", self._on_history_loaded, self._on_history_failed, self._on_history_cancelled),
                                                ("history_log_bridge", self._on_history_log_loaded, self._on_history_log_failed, self._on_history_log_cancelled)):
            bridge = JobBridge(self)
            bridge.loaded.connect(loaded)
            bridge.failed.connect(failed)
            bridge.cancelled.connect(cancelled)
            setattr(self, name, bridge)

    # ---- 화면 ----
    def _render_history(self):
        if self.state.page == "history":                                              # 다른 화면을 보는 중이면 값만 받아 두고 다시 그리지 않는다
            self.render()

    def _history_opened(self):
        """발행 기록 화면을 열 때마다 목록(과 펼쳐 둔 작업 로그)을 읽는다(읽기만 — 파일도 폴더도 만들지 않는다)."""
        history = self.state.history
        history.start_load(**self.history_bridge.callbacks())
        if history.log_open:
            history.start_log(**self.history_log_bridge.callbacks())

    def reload_history(self, *_):
        job = self.state.history.start_load(**self.history_bridge.callbacks())
        if job is None:
            self.notify(T["load_busy"])
            return False
        self.render()
        return True

    def history_toggle_order(self):
        """정렬 바꾸기 — 이미 받은 목록을 다시 늘어놓을 뿐 다시 읽지 않는다."""
        self.state.history.toggle_order()
        self.render()
        self._restore_focus("hist:order")

    def history_more(self):
        self.state.history.show_more()
        self.render()
        self._restore_focus("hist:more")

    def history_go_posts(self, *_):
        """빈 화면의 `글 검토로 가기` — 글 검토 화면으로 간다(메뉴와 같은 길 `go`)."""
        self.go("posts")

    def history_toggle_log(self):
        """작업 로그 카드를 펴고 접는다 — 처음 펼칠 때(또는 지난 읽기가 실패했을 때)만 읽는다."""
        history = self.state.history
        if history.set_log_open(not history.log_open):
            history.start_log(**self.history_log_bridge.callbacks())
        self.render()
        self._restore_focus("hist:log-toggle")

    def history_reload_log(self):
        job = self.state.history.start_log(**self.history_log_bridge.callbacks())
        if job is None:
            self.notify(T["load_busy"])
            return False
        self.render()
        return True

    def history_copy_url(self, key):
        """`주소 복사` — 컨트롤러가 정한 주소를 셸의 기존 복사 길(클립보드뿐)로 보낸다. 키·토큰 모양이 든 주소는 복사하지 않는다 → 복사했으면 True."""
        text, why = self.state.history.copy_payload(key)
        if text is None:
            self.notify(T[why], "error")
            return False
        if not self.copy(text):
            self.notify(T["hist_copy_failed"], "error")
            return False
        self.notify(T["hist_copied"])
        return True

    # ---- 읽기 결과 받기(목록) ----
    def _on_history_loaded(self, data):
        self._guarded(self._show_history_loaded, data, recover=self._recover_history)

    def _on_history_failed(self, failure):
        self._guarded(self._show_history_failed, failure, recover=self._recover_history)

    def _on_history_cancelled(self):
        self._guarded(self._show_history_cancelled, recover=self._recover_history)

    def _show_history_loaded(self, data):
        self.state.history.apply_loaded(data)
        self._render_history()

    def _show_history_failed(self, failure):
        self.state.history.apply_load_failed(failure, self.clock.now())
        self._render_history()

    def _show_history_cancelled(self):
        self.state.history.apply_cancelled()
        self._render_history()

    # ---- 읽기 결과 받기(작업 로그) ----
    def _on_history_log_loaded(self, data):
        self._guarded(self._show_history_log_loaded, data, recover=self._recover_history_log)

    def _on_history_log_failed(self, failure):
        self._guarded(self._show_history_log_failed, failure, recover=self._recover_history_log)

    def _on_history_log_cancelled(self):
        self._guarded(self._show_history_log_cancelled, recover=self._recover_history_log)

    def _show_history_log_loaded(self, data):
        self.state.history.apply_log(data)
        self._render_history()

    def _show_history_log_failed(self, failure):
        self.state.history.apply_log_failed(failure, self.clock.now())
        self._render_history()

    def _show_history_log_cancelled(self):
        self.state.history.apply_log_cancelled()
        self._render_history()

    def _recover_history(self, error):
        """발행 기록 슬롯에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)
        self.state.history.apply_unexpected(error, self.clock.now())
        try:
            self._render_history()
        except Exception:
            self.notify(T["job_failed"])

    def _recover_history_log(self, error):
        report_unexpected(type(error), error)
        self.state.history.apply_log_unexpected(error, self.clock.now())
        try:
            self._render_history()
        except Exception:
            self.notify(T["job_failed"])
