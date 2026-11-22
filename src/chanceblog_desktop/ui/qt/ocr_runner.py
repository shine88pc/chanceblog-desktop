"""글자 읽기 진행자(결정 D-513, 설계서 3-2·3-3·2-7) — 사진 정리 창의 글자 읽기 요청을 **작업 스레드**(`ui/core/jobs.py`)에 한 장씩 맡기고 결과를 시그널로 화면 스레드에 되돌린다.
흐름: [화면 스레드: 단추] → `read` → 컨트롤러 대기열 → `pump` 가 한 장을 `begin_next` 로 꺼내 작업 스레드를 시작 → [작업 스레드: `provider.read` — 사진을 메모리에서 읽고 줄이고(`ocr_input`) 작업자에 보내 결과를 기다린다]
→ 시그널 → [화면 스레드: `OcrPanel.finish` → `OcrBoard.on_result/on_error` → 다음 장 → `changed`]. **컨트롤러(`OcrBoard`)·사진 목록은 화면 스레드에서만 만진다** — 작업 스레드는 요청(`OcrJob`)과 화면 스레드가 미리 건넨 사진 위치 값만 본다.

이 파일이 하는 일:
  · 한 번에 한 장 — `begin_next` 가 읽는 중이거나 취소를 마무리하는 중이면 아무것도 안 한다. 취소·창 닫기·사진 지우기·초안 떠나기(컨트롤러가 취소 번호를 모은다)는 **지금 읽는 요청일 때만** 공급자(어댑터)에 알린다 — 이미 끝난 요청의 취소가 다음 요청을 멈추지 않게.
  · 1초 시계(`tick`) — 읽는 중의 초 글(`ticked`)·시간 초과와 취소 3초 규칙의 감시(`OcrBoard.expire` — 넘기면 어댑터가 프로세스 트리를 끈다)·유휴 5분이면 작업자 종료. 일이 없고 작업자도 없으면 멈춘다.
  · 앱 종료(`shutdown`) — 모든 요청을 취소하고 작업자를 끝낸다(오래 걸려도 화면을 붙잡지 않게 별도 스레드에서, 마지막 안전망은 Job 개체의 `KILL_ON_JOB_CLOSE`).
공급자가 '준비 소식'(`on_ready`)을 알려 주지 않는 가짜(시험)면 읽기를 시작하는 것과 함께 준비된 것으로 본다. 사진을 읽는 함수(`reader`)와 시계(`monotonic`)는 시험이 바꿔 끼운다.
사진 위치는 `_paths`(요청 번호 → 위치)에 읽는 동안만 있고 어디에도 적거나 되풀이하지 않는다.
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ...errors import AppError
from ..core import photo_ocr_view as pov
from ..core.jobs import JobRunner
from . import ocr_input

TICK_MS = 1000                  # 읽는 중의 시계 — 초 글을 바꾸고 시간 초과·취소 3초를 본다
IDLE_CHECK_MS = 15_000          # 일이 없고 작업자만 떠 있을 때 유휴 종료(5분)를 확인하는 간격
SHUTDOWN_WAIT_S = 4.0           # 앱을 닫을 때 작업자 정리를 기다리는 최대 시간(그 뒤는 Job 개체가 끝낸다)


class OcrRunner(QObject):
    """글자 읽기 진행자 — `OcrPanel`(컨트롤러를 감싼 화면 규칙) 하나를 맡는다. 화면은 `changed`(다시 그리기)·`ticked`(초 글 바꾸기) 시그널을 듣는다."""
    changed = Signal()
    ticked = Signal()
    _outcome = Signal(int, object)
    _became_ready = Signal()

    def __init__(self, panel, *, monotonic=time.monotonic, reader=ocr_input.prepare, tick_ms=TICK_MS, idle_ms=IDLE_CHECK_MS, parent=None):
        super().__init__(parent)
        self.panel, self.ocr, self.provider = panel, panel.ocr, panel.ocr.provider
        self.monotonic, self.reader, self.tick_ms, self.idle_ms = monotonic, reader, tick_ms, idle_ms
        self.jobs = JobRunner()
        self._paths = {}                                           # 요청 번호 → 사진 위치(읽는 동안만) — 작업 스레드가 읽는 값이다
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._outcome.connect(self._on_outcome)
        self._became_ready.connect(self._on_ready)
        if getattr(self.provider, "prepare", False) is None:       # 어댑터가 사진을 읽고 줄이는 훅을 기다리고 있다
            self.provider.prepare = self._prepare
        self._reports_ready = hasattr(self.provider, "on_ready")
        if self._reports_ready:
            self.provider.on_ready = self._became_ready.emit        # 작업 스레드에서 불린다 — 시그널이라 화면 스레드로 넘어온다

    def now(self):
        return self.monotonic()

    # ---- 화면이 부르는 일(화면 스레드) ----
    def read(self, photo_id, size=pov.SIZE_NORMAL):
        """`글자 읽기`·`다시 읽기`·`더 크게` → 컨트롤러의 이름(`queued`·`ask_replace`·`busy`·`unavailable`·`refused`). 대기열에 들어갔으면 곧바로 시작한다."""
        status = self.panel.read(photo_id, size)
        if status == "queued":
            self.sync()
        return status

    def confirm_reread(self, photo_id):
        status = self.panel.confirm_reread(photo_id)
        if status == "queued":
            self.sync()
        return status

    def cancel_reread(self, photo_id=None):
        self.panel.cancel_reread()
        return "ok"

    def cancel(self, photo_id):
        status = self.panel.cancel(photo_id, self.now())
        self.sync()
        return status

    def escape(self, photo_id):
        kind = self.panel.escape(photo_id, self.now())
        if kind == "cancel":
            self.sync()
        return kind

    def busy(self):
        return self.ocr.active is not None or bool(self.ocr.queue)

    def sync(self):
        """상태가 바뀐 뒤 — 취소를 공급자에 알리고, 자리가 비었으면 다음 장을 시작하고, 시계를 맞춘다."""
        self._flush_cancels()
        self.pump()
        self._sync_timer()

    # ---- 시작·끝 ----
    def pump(self):
        """대기열 맨 앞 한 장을 작업 스레드에 맡긴다 → 시작한 `OcrJob` 또는 None."""
        job = self.ocr.begin_next(self.now())
        if job is None:
            return None
        if not self._reports_ready:
            self.ocr.mark_ready(self.now())                        # 준비 소식을 못 주는 가짜 — 시작과 함께 준비된 것으로 본다
        token = job.token
        self._paths[token] = self.ocr.board.local_path(job.photo_id)
        self.jobs.start(f"ocr-{token}", lambda progress, cancelled: self.provider.read(job),
                        on_done=lambda result, _payload: self._outcome.emit(token, result), on_error=lambda failure, _payload: self._outcome.emit(token, pov.OcrOutcome(error="engine")))
        return job

    def _prepare(self, job):
        """어댑터가 작업 스레드에서 부르는 훅 — 이 요청의 사진을 읽고 줄여 `(너비, 높이, RGB 바이트)` 로 준다. 읽는 사이에 취소됐으면 작업자에 보내지 않는다."""
        path = self._paths.get(job.token, "")
        if not path:
            raise AppError("OCR_FAILED")
        result = self.reader(path, job.size)
        if job.cancelled:
            raise AppError("OCR_FAILED")
        return result

    def _on_outcome(self, token, outcome):
        self._paths.pop(token, None)
        self._flush_cancels()
        self.panel.finish(token, outcome, self.now())
        self.sync()
        self.changed.emit()

    def _on_ready(self):
        self.panel.ready(self.now())
        self.changed.emit()

    def _flush_cancels(self):
        """컨트롤러가 모은 취소 번호 가운데 **지금 읽는 요청**만 공급자에 알린다(이미 끝난 요청의 취소는 버린다)."""
        taken = self.ocr.take_cancels()
        active = self.ocr.active
        cancel = getattr(self.provider, "cancel", None)
        if cancel is not None and active is not None and active.token in taken:
            cancel(active.token)

    # ---- 시계 ----
    def tick(self):
        """1초마다 — 취소를 알리고, 시간 초과·취소 뒤 3초를 넘긴 요청을 끝내고(어댑터가 프로세스 트리를 끈다), 오래 쉰 작업자를 끝낸다."""
        now = self.now()
        self._flush_cancels()
        expired = self.ocr.expire(now)
        if expired is not None:
            self._terminate()
            self.sync()
            self.changed.emit()
            return
        if self.ocr.idle_exit_due(now):
            self._idle_exit()
        self._sync_timer()
        self.ticked.emit()

    def _terminate(self):
        terminate = getattr(self.provider, "terminate", None)
        if terminate is not None:
            threading.Thread(target=terminate, daemon=True).start()   # 트리 종료는 오래 걸릴 수 있다 — 화면을 붙잡지 않는다

    def _idle_exit(self):
        self.ocr.worker_stopped()
        leave = getattr(self.provider, "maybe_idle_exit", None)
        if leave is not None:
            threading.Thread(target=leave, daemon=True).start()

    def _sync_timer(self):
        wanted = self.tick_ms if self.busy() else (self.idle_ms if self.ocr.worker_ready else 0)
        if wanted and (not self._timer.isActive() or self._timer.interval() != wanted):
            self._timer.start(wanted)
        elif not wanted and self._timer.isActive():
            self._timer.stop()

    # ---- 앱 종료 ----
    def shutdown(self, wait=SHUTDOWN_WAIT_S):
        """앱을 닫는다 — 모든 요청을 취소하고 작업자를 끝낸다. 작업자 정리는 별도 스레드에서 하고 `wait` 초까지만 기다린다. 여러 번 불러도 같다."""
        self._timer.stop()
        self.ocr.reset()
        self._flush_cancels()
        cleaner = threading.Thread(target=self.provider.shutdown, daemon=True)
        cleaner.start()
        cleaner.join(wait)
        self.ocr.worker_stopped()
        self._paths.clear()


__all__ = ["IDLE_CHECK_MS", "OcrRunner", "SHUTDOWN_WAIT_S", "TICK_MS"]
