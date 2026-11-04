"""작업 스레드 — 오래 걸리는 일(후보 불러오기·초안 만들기 …)을 화면 스레드 밖에서 돌려 창이 '응답 없음' 이 되지 않게 한다. PySide6 를 모른다(시험이 창 없이 돈다).

규칙:
  · 시작(`start`)은 곧바로 돌아온다. 같은 이름(key)의 작업이 이미 돌고 있으면 새로 시작하지 않고 None 을 돌려준다(중복 클릭 방지).
  · 취소는 협조적이다 — 작업 함수가 `cancelled()` 를 보고 스스로 멈춘다(`JobCancelled`). 취소를 눌렀는데 일이 이미 끝났어도 결과는 버리고 '취소'로 알린다(사용자의 뜻을 따른다).
  · 작업이 실패해도 **입력(payload)은 그대로** 돌려준다 — 화면이 입력 칸을 비우지 않고 다시 시도할 수 있다.
  · 콜백(진행·완료·실패·취소)은 **작업 스레드에서** 불린다. 화면 도구는 자기 화면 스레드로 넘겨서 쓴다(Qt: 시그널). 콜백이 예외를 내도 작업은 멈추지 않고 예외 이름만 `callback_error` 에 남긴다(내용은 남기지 않는다).
  · 예기치 못한 오류는 기술 문구를 그대로 내보내지 않고 쉬운 안내(`job_failed`)와 예외 이름(진단 정보용)으로 바꾼다. 작업이 `SystemExit` 로 끝나도 '실패'로 알리고 끝난 것으로 친다(영원히 running 으로 남지 않는다).
"""
from __future__ import annotations

import threading

from .text import T


class JobCancelled(Exception):
    """작업 함수가 취소를 알아차려 스스로 멈출 때 낸다."""


class JobFailure(Exception):
    """작업이 실패했을 때 — `user_message`(기술 용어 없는 한두 문장)는 기본 화면에, `code`(영문 코드)는 진단 정보 영역에만 나간다."""

    def __init__(self, user_message, code="", retryable=True):
        super().__init__(user_message)
        self.user_message = str(user_message)
        self.code = str(code)
        self.retryable = bool(retryable)


class Job:
    """작업 스레드 하나. `work(progress, cancelled)` 를 돌린다 — `progress(fraction, text)`·`cancelled()`."""

    READY, RUNNING, DONE, FAILED, CANCELLED = "ready", "running", "done", "failed", "cancelled"

    def __init__(self, key, work, *, payload=None, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        self.key, self.work, self.payload = key, work, payload
        self._callbacks = {"progress": on_progress, "done": on_done, "error": on_error, "cancel": on_cancel}
        self._cancel = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.state = self.READY
        self.callback_error = ""

    @property
    def running(self):
        return self.state == self.RUNNING

    @property
    def cancel_requested(self):
        return self._cancel.is_set()

    def start(self):
        with self._lock:
            if self.state != self.READY:
                return False
            self.state = self.RUNNING
        self._thread = threading.Thread(target=self._run, name=f"job-{self.key}", daemon=True)
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)
        return not (self._thread is not None and self._thread.is_alive())

    def _emit(self, name, *args):
        callback = self._callbacks.get(name)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as error:                                # 화면 쪽 콜백의 실수가 작업 스레드를 죽이지 않게 — 내용(글)은 남기지 않고 이름만
            self.callback_error = type(error).__name__

    def _progress(self, fraction, text=""):
        if not self._cancel.is_set():
            self._emit("progress", fraction, text)

    def _finish(self, state, name, *args):
        with self._lock:
            self.state = state                                    # 콜백이 불리기 전에 '더 이상 돌지 않음' 으로 — 콜백 안에서 같은 작업을 다시 시작할 수 있다
        self._emit(name, *args)

    def _run(self):
        try:
            result = self.work(self._progress, self._cancel.is_set)
        except JobCancelled:
            self._finish(self.CANCELLED, "cancel", self.payload)
        except JobFailure as failure:
            self._finish(self.FAILED, "error", failure, self.payload)
        except BaseException as error:                            # 어떤 오류도 기술 문구를 그대로 내보내지 않는다 — 쉬운 안내 + 예외 이름(진단용). `SystemExit` 같은 것도 '끝남'으로 알린다(안 그러면 영원히 running 이라 다시 불러오기가 막힌다)
            self._finish(self.FAILED, "error", JobFailure(T["job_failed"], code=type(error).__name__), self.payload)
        else:
            if self._cancel.is_set():
                self._finish(self.CANCELLED, "cancel", self.payload)
            else:
                self._finish(self.DONE, "done", result, self.payload)


class JobRunner:
    """이름(key)마다 작업을 하나씩만 돌린다."""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def start(self, key, work, **callbacks):
        with self._lock:
            current = self._jobs.get(key)
            if current is not None and current.running:
                return None
            job = Job(key, work, **callbacks)
            self._jobs[key] = job
        job.start()
        return job

    def job(self, key):
        return self._jobs.get(key)

    def running(self, key=None):
        if key is not None:
            job = self._jobs.get(key)
            return bool(job and job.running)
        return any(job.running for job in list(self._jobs.values()))

    def cancel(self, key):
        job = self._jobs.get(key)
        if job is not None:
            job.cancel()

    def cancel_all(self):
        for job in list(self._jobs.values()):
            job.cancel()

    def join_all(self, timeout=2.0):
        return all(job.join(timeout) for job in list(self._jobs.values()))
