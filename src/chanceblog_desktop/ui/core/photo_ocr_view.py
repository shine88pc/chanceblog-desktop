"""글자 읽기(사진 속 글자 읽기, 결정 D-512, 설계서 2-3·2-5·2-7·3-3·3-10)의 화면 쪽 규칙 — 사진 한 장의 상태 기계·대기열·세대 번호·시간 초과 값·줄 확인·고침·빼기·합치기·'모두 맞아요' 두 단계.
PySide6·파일·네트워크·프로세스·시계를 모른다(그래서 CI 에서 시험한다). 실제로 읽는 쪽(작업자 프로세스)은 공급자(`OcrProvider` — 어댑터 `ui/ocr_adapter.py`)가 하고, 이 파일은 `FakeOcrProvider` 로 시험한다.
시계는 쓰지 않는다 — 시간이 필요한 곳은 호출하는 쪽이 지금 시각(초)을 준다. 사진 경로·파일 이름은 이 파일에 없다(요청은 사진 번호와 읽는 크기 이름뿐이다).

사진 한 장의 상태(`state_of`): `idle`(쉼)·`queued`(기다림)·`preparing`(준비 중)·`reading`(읽는 중)·`done`(완료 — 줄이 0개여도)·`failed`(실패, 오류 이름 `error_of`)·`cancelled`(취소됨).
  · 한 번에 한 장만 읽는다 — 대기열은 먼저 누른 순서(FIFO)다. 읽는 중·기다리는 사진은 `PhotoBoard` 의 '확인했어요'·'모두 확인했어요' 가 건너뛰고(결과가 와서 확정이 풀리는 놀람을 막는다) 줄 고치기도 막힌다.
  · 늦게 온 결과는 버린다 — 새 초안·화면 떠남·저장한 초안 열기(`reset`)에서 세대 번호가 올라가고, 사진 지우기·다시 찾기(`on_photo_changed`)에서는 그 사진의 요청이 사라진다. 번호(token)가 모르는 것이거나 취소한 것이거나 세대가 다른 결과는 `late` 로 버리고 목록은 안 바뀐다.
  · 취소: 기다리는 것은 바로 뺀다. 읽는 중인 것은 취소 표시를 하고 결과는 버리며, 작업자가 `CANCEL_WAIT_S`(3초) 안에 끝내지 못하면 `expire` 가 `kill` 을 알린다(공급자가 프로세스 트리를 끈다).
  · 시간 초과: 준비 `PREPARE_TIMEOUT_S`(150초)·사진 한 장 `READ_TIMEOUT_S`(90초) — `expire` 가 `timeout` 을 알리고 실패로 센다.
  · 연속 실패 `FAILURE_LIMIT`(3)번이면 이번 실행 동안 끈다(`disabled_code`). 네트워크 시도 차단 보고·약속 위반·시작 막힘·도구 파일 이상은 한 번이면 끈다. 큰 사진은 사용자의 사진 문제라 실패로 세지 않는다. 성공하면 연속 횟수를 0 으로 되돌린다.
  · 줄이 이미 있는 사진을 다시 읽으려면 확인을 한 번 거친다(`request_read` -> `ask_replace` -> `confirm_reread`) — 지금 읽은 글(고친 것·확인한 것 포함)이 새로 읽은 글로 바뀌기 때문이다.
  · 줄 확인과 사진 확정은 따로다 — 줄을 확인해도 사진은 확정되지 않고(오히려 풀린다), '모두 맞아요' 도 줄만 확인한다. '모두 맞아요' 는 확인 줄(수)을 먼저 보이고(`ask_all_right`) 한 번 더 눌러야(`all_right`) 표시하며 사진 한 장 단위다.
  · 줄 빼기는 한 번 되돌릴 수 있다(`undo_remove_line` — 그 사이에 다른 고침이 있으면 되돌릴 수 없다).
이 파일의 어떤 상태·오류·결과 값에도 읽은 글을 되풀이하지 않는다(개수와 상태 이름뿐 — 글은 사진 목록(`PhotoManifest`)에만 있다).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...content import photo_manifest as pm
from ...content import photo_ocr
from ...errors import AppError
from .photo_view import reason_of

IDLE, QUEUED, PREPARING, READING, DONE, FAILED, CANCELLED = "idle", "queued", "preparing", "reading", "done", "failed", "cancelled"
STATES = (IDLE, QUEUED, PREPARING, READING, DONE, FAILED, CANCELLED)
BUSY_STATES = frozenset({QUEUED, PREPARING, READING})

PREPARE_TIMEOUT_S = 150          # 읽기 도구 준비(모델 올리기) 시간 초과 — PC 가 아주 바쁘면 134초가 걸린 사례가 있어 넉넉히 둔다
READ_TIMEOUT_S = 90              # 사진 한 장 시간 초과
CANCEL_WAIT_S = 3                # 취소한 뒤 작업자가 한 장을 마무리하도록 기다리는 시간 — 넘으면 프로세스 트리를 끈다
IDLE_EXIT_S = 300                # 마지막 결과 뒤 이만큼 쉬면 앱이 작업자 종료를 요청한다(5분)
SLOW_HINT_S = 15                 # 읽는 중이 이보다 길면 'PC 가 바쁘면 더 걸려요' 보조 문구를 보인다
FAILURE_LIMIT = 3                # 연속 실패가 이만큼이면 이번 실행 동안 끈다
SIZE_NORMAL, SIZE_BIG = "960", "1600"
SIZES = (SIZE_NORMAL, SIZE_BIG)  # 읽는 크기 이름(긴 변) — '작은 글씨라면 더 크게 다시 읽기' 가 1600

ERROR_CODE = {"decode": "OCR_FAILED", "engine": "OCR_FAILED", "died": "OCR_FAILED", "timeout": "OCR_TIMEOUT", "too_big": "OCR_TOO_BIG", "net_blocked": "OCR_UNEXPECTED", "proto": "OCR_UNEXPECTED",
              "blocked": "OCR_BLOCKED", "addon_invalid": "OCR_ADDON_INVALID", "unavailable": "OCR_UNAVAILABLE"}      # 작업자·어댑터가 알리는 이름 -> 오류 카탈로그 코드(고정 문장은 카탈로그에 있다)
COUNTED = frozenset({"decode", "engine", "died", "timeout"})                  # 연속 실패로 세는 것
DISABLING = frozenset({"net_blocked", "proto", "blocked", "addon_invalid", "unavailable"})   # 한 번이면 이번 실행 동안 끄는 것(모르는 이름도 '예상 밖' 으로 끈다)


def code_of(name):
    """오류 이름 -> 카탈로그 코드(모르는 이름은 `OCR_UNEXPECTED`)."""
    return ERROR_CODE.get(name, "OCR_UNEXPECTED")


class OcrJob:
    """읽기 요청 하나 — 번호(token)·사진 번호·읽는 크기 이름·만든 세대. 사진 경로·글은 없다."""
    __slots__ = ("token", "photo_id", "size", "generation", "began", "started", "cancelled", "cancel_at")

    def __init__(self, token, photo_id, size, generation):
        self.token, self.photo_id, self.size, self.generation = token, photo_id, size, generation
        self.began = self.started = self.cancel_at = None
        self.cancelled = False

    def __repr__(self):
        return f"OcrJob(token={self.token}, photo_id={self.photo_id!r}, size={self.size!r})"


@dataclass(frozen=True)
class OcrOutcome:
    """공급자가 한 장을 읽은 결과 — 줄들(글은 `repr` 에 안 나온다) 또는 오류 이름(`ERROR_CODE` 의 키). `error` 가 빈 글이면 성공."""
    lines: tuple = field(default=(), repr=False)
    error: str = ""


class OcrProvider:
    """실제로 읽는 쪽(어댑터 `ui/ocr_adapter.py`)이 따르는 모양 — 요청에는 사진 번호와 크기 이름뿐(경로 없음)."""

    def available(self):
        return False

    def read(self, job):
        raise NotImplementedError

    def cancel(self, token):
        """진행 중인 요청을 취소한다 — 없는 번호면 아무 일도 안 한다."""

    def shutdown(self):
        """작업자를 끝낸다 — 여러 번 불러도 같다."""


class FakeOcrProvider(OcrProvider):
    """시험용 가짜 공급자 — 사진 번호마다 정해 둔 결과(`OcrOutcome`)를 순서대로 준다(없으면 `default`). 부른 것은 `calls` 에 번호·사진 번호·크기만 남긴다(글 없음)."""

    def __init__(self, outcomes=None, default=None, is_available=True):
        self.outcomes = {key: (list(value) if isinstance(value, (list, tuple)) else [value]) for key, value in (outcomes or {}).items()}
        self.default = default if default is not None else OcrOutcome(("가짜 줄",))
        self.is_available = is_available
        self.calls, self.cancelled, self.shut_down = [], [], 0

    def available(self):
        return self.is_available

    def read(self, job):
        self.calls.append((job.token, job.photo_id, job.size))
        queue = self.outcomes.get(job.photo_id)
        return queue.pop(0) if queue else self.default

    def cancel(self, token):
        self.cancelled.append(token)

    def shutdown(self):
        self.shut_down += 1


class OcrBoard:
    """사진 목록(`PhotoBoard`)에 붙는 글자 읽기 컨트롤러 — 만들면 `board.ocr` 에 스스로를 단다(한 보드에 하나). 모든 일은 값을 받아 상태를 바꾸고 짧은 상태 이름을 돌려준다. 저장하지 않는다."""

    def __init__(self, board, provider=None):
        self.board = board
        self.provider = provider if provider is not None else FakeOcrProvider()
        board.ocr = self
        self.disabled_code = ""            # 이번 실행 동안 끈 이유(오류 카탈로그 코드) — 빈 글이면 켜져 있다
        self.failures = 0                  # 연속 실패 횟수
        self.generation = 0
        self.worker_ready = False
        self.last_activity = None
        self.reset()

    # ---- 비우기·훅(PhotoBoard 가 부른다) ----
    def _clear_state(self):
        self.states, self.summary, self.errors, self.line_errors = {}, {}, {}, {}
        self.queue, self.active, self.cancels = [], None, []
        self.reread_asked, self.all_right_asked, self.undo_line, self.last_all_right = None, (None, 0), None, 0
        self._token = getattr(self, "_token", 0)

    def reset(self):
        """새 초안·화면 떠남·저장한 초안 열기 — 상태·대기열을 비우고 진행 중 요청은 취소한다(늦게 온 결과는 세대 번호가 달라 버려진다). 끈 상태와 연속 실패 횟수는 이번 실행 동안 그대로다."""
        running = getattr(self, "active", None)
        if running is not None and not running.cancelled:
            running.cancelled = True
            pending = [running.token]
        else:
            pending = []
        keep = running
        self._clear_state()
        self.generation += 1
        self.cancels = pending
        self.active = keep if keep is not None else None            # 작업자가 마무리하거나 `expire` 가 끌 때까지 자리를 쥔다(다음 요청은 그 뒤에)

    def on_close(self):
        """'사진 정리' 창을 닫는다 — 기다리는 것은 빼고 읽는 중인 것은 취소한다(이미 읽은 글·실패 표시는 그대로)."""
        for job in self.queue:
            self.states.pop(job.photo_id, None)
        self.queue = []
        if self.active is not None and not self.active.cancelled:
            self._cancel_active()
        self.reread_asked, self.all_right_asked = None, (None, 0)

    def on_photo_changed(self, photo_id):
        """사진을 지웠거나 다른 파일로 이어 붙였다 — 그 사진의 요청을 취소하고 상태를 비운다(읽은 글은 목록이 정한다)."""
        self.queue = [job for job in self.queue if job.photo_id != photo_id]
        if self.active is not None and self.active.photo_id == photo_id and not self.active.cancelled:
            self._cancel_active()
        for table in (self.states, self.summary, self.errors):
            table.pop(photo_id, None)
        for key in [key for key in self.line_errors if key[0] == photo_id]:
            self.line_errors.pop(key)
        if self.reread_asked == photo_id:
            self.reread_asked = None
        if self.all_right_asked[0] == photo_id:
            self.all_right_asked = (None, 0)
        if self.undo_line is not None and self.undo_line[0] == photo_id:
            self.undo_line = None

    # ---- 읽기 ----
    @property
    def available(self):
        return self.disabled_code == "" and bool(self.provider.available())

    def state_of(self, photo_id):
        stored = self.states.get(photo_id)
        if stored is not None:
            return stored
        photo = self.board.photo(photo_id)
        return DONE if photo is not None and photo.analysis_method == photo_ocr.METHOD else IDLE

    def is_busy(self, photo_id):
        return self.states.get(photo_id) in BUSY_STATES

    def error_of(self, photo_id):
        return self.errors.get(photo_id, "")

    def queue_ahead(self, photo_id):
        """이 사진 앞에서 기다리는 장 수(읽는 중인 한 장 포함) — 기다리는 중이 아니면 0."""
        ahead = 1 if self.active is not None and not self.active.cancelled else 0
        for job in self.queue:
            if job.photo_id == photo_id:
                return ahead
            ahead += 1
        return 0

    def _enqueue(self, photo_id, size):
        self._token += 1
        self.queue.append(OcrJob(self._token, photo_id, size, self.generation))
        self.states[photo_id] = QUEUED
        self.errors.pop(photo_id, None)
        self.summary.pop(photo_id, None)
        self.reread_asked = None
        return "queued"

    def request_read(self, photo_id, size=SIZE_NORMAL):
        """'글자 읽기' 를 누른다 → `queued`·`ask_replace`(이미 읽은 글이 있다 — 확인을 거친다)·`busy`·`unavailable`·`refused`."""
        photo = self.board.photo(photo_id)
        if photo is None or size not in SIZES:
            return "refused"
        if not self.available:
            return "unavailable"
        if self.is_busy(photo_id):
            return "busy"
        if photo.visible_text:
            self.reread_asked = (photo_id, size)
            return "ask_replace"
        return self._enqueue(photo_id, size)

    def confirm_reread(self, photo_id):
        """다시 읽기 확인에서 [다시 읽기] — 먼저 `request_read` 가 `ask_replace` 를 돌려준 사진에서만 된다."""
        asked = self.reread_asked
        if asked is None or asked[0] != photo_id or self.board.photo(photo_id) is None:
            return "refused"
        if not self.available:
            self.reread_asked = None
            return "unavailable"
        if self.is_busy(photo_id):
            self.reread_asked = None
            return "busy"
        return self._enqueue(photo_id, asked[1])

    def cancel_reread(self):
        self.reread_asked = None

    def begin_next(self, now=0.0):
        """대기열 맨 앞 요청을 시작한다(한 번에 한 장 — 읽는 중이거나 취소를 마무리하는 중이면 아무것도 안 한다) → `OcrJob` 또는 None. 작업자가 아직 준비 안 됐으면 `preparing`, 됐으면 `reading`."""
        if self.active is not None or not self.queue or not self.available:
            return None
        job = self.queue.pop(0)
        job.began = now
        self.active = job
        if self.worker_ready:
            job.started = now
            self.states[job.photo_id] = READING
        else:
            self.states[job.photo_id] = PREPARING
        return job

    def mark_ready(self, now=0.0):
        """작업자가 준비됐다(ready) — 준비 중이던 요청이 읽는 중이 된다."""
        self.worker_ready = True
        job = self.active
        if job is not None and not job.cancelled and self.states.get(job.photo_id) == PREPARING:
            job.started = now
            self.states[job.photo_id] = READING

    def worker_stopped(self):
        """작업자가 끝났다(유휴 종료·죽음·종료) — 다음 읽기는 준비부터 다시 한다."""
        self.worker_ready = False

    def idle_exit_due(self, now):
        """작업자가 `IDLE_EXIT_S` 넘게 쉬고 있어서 종료를 요청할 때인가."""
        return self.worker_ready and self.active is None and not self.queue and self.last_activity is not None and now - self.last_activity >= IDLE_EXIT_S

    def _live(self, token):
        """결과·오류를 받을 수 있는 요청 — 지금 읽는 중이고 취소하지 않았고 세대가 같은 것."""
        job = self.active
        if job is None or job.token != token:
            return None
        return None if job.cancelled or job.generation != self.generation else job

    def _release(self, token):
        """작업자가 그 요청을 끝냈다 — 취소한 요청이면 자리를 비운다."""
        if self.active is not None and self.active.token == token:
            self.active = None

    def on_result(self, token, lines, now=None):
        """작업자가 읽은 줄을 보냈다(검증은 어댑터가 이미 했다) → `applied` 또는 `late`(버림 — 목록은 안 바뀐다)."""
        job = self._live(token)
        if job is None:
            self._release(token)
            return "late"
        self.active = None
        self.last_activity = now
        try:
            updated, found = photo_ocr.apply(self.board.manifest, job.photo_id, lines)
        except AppError:
            return self._fail(job, "engine")
        self.board.manifest = updated
        self.board.undo, self.board.confirm_all_asked = None, 0
        self.board.notes.pop(job.photo_id, None)
        self.states[job.photo_id] = DONE
        self.summary[job.photo_id] = (found.found, found.hidden, found.over_limit)
        self.failures = 0
        return "applied"

    def summary_of(self, photo_id):
        """읽은 결과의 개수 `(보이는 줄 수, 보여 드리지 않은 줄 수, 줄 수 한도로 잘린 수)` — 글은 없다. 없으면 `(0, 0, 0)`."""
        return self.summary.get(photo_id, (0, 0, 0))

    def _fail(self, job, name):
        self.states[job.photo_id] = FAILED
        self.errors[job.photo_id] = name
        if name in DISABLING or name not in ERROR_CODE:
            self.disable(code_of(name))
            return "disabled"
        if name in COUNTED:
            self.failures += 1
            if self.failures >= FAILURE_LIMIT:
                self.disable("OCR_UNAVAILABLE")
                return "disabled"
        return "failed"

    def on_error(self, token, name, now=None):
        """작업자·어댑터가 실패를 알렸다(`ERROR_CODE` 의 이름) → `failed`·`disabled`(이번 실행 동안 끔) 또는 `late`."""
        job = self._live(token)
        if job is None:
            self._release(token)
            return "late"
        self.active = None
        self.last_activity = now
        return self._fail(job, name)

    def disable(self, code):
        """이번 실행 동안 글자 읽기를 끈다 — 기다리는 요청은 비우고 읽는 중인 것은 취소한다."""
        self.disabled_code = code
        for job in self.queue:
            self.states.pop(job.photo_id, None)
        self.queue = []
        if self.active is not None and not self.active.cancelled:
            self._cancel_active()

    # ---- 취소·시간 ----
    def _cancel_active(self, now=None):
        """읽는 중인 요청에 취소 표시를 한다 — 시각을 모르는 곳(훅)에서는 `now` 가 없고, 그러면 3초 기다림은 `expire` 를 처음 부른 시각부터 센다."""
        job = self.active
        job.cancelled, job.cancel_at = True, now
        self.states[job.photo_id] = CANCELLED
        self.cancels.append(job.token)

    def cancel(self, photo_id, now=None):
        """[취소]·Esc → `cancelled`(기다리던 것을 뺐다)·`cancelling`(읽는 중인 것을 취소했다 — 작업자가 마무리하거나 `expire` 가 끌 때까지)·`refused`(취소할 것이 없다)."""
        for job in self.queue:
            if job.photo_id == photo_id:
                self.queue.remove(job)
                self.states[photo_id] = CANCELLED
                return "cancelled"
        if self.active is not None and self.active.photo_id == photo_id and not self.active.cancelled:
            self._cancel_active(now)
            return "cancelling"
        return "refused"

    def take_cancels(self):
        """공급자에게 취소를 알릴 요청 번호들(한 번 가져가면 비운다)."""
        taken, self.cancels = self.cancels, []
        return taken

    def expire(self, now):
        """시간이 지났는지 본다 → None 또는 `(종류, 요청 번호)`. `timeout` 은 준비 150초·사진 90초를 넘긴 것(실패로 세고 공급자가 프로세스 트리를 끈다), `kill` 은 취소한 뒤 3초가 지나도 작업자가 못 끝낸 것(공급자가 끈다)."""
        job = self.active
        if job is None:
            return None
        if job.cancelled:
            if job.cancel_at is None:
                job.cancel_at = now                                     # 취소한 시각을 모르면 처음 확인한 때부터 3초를 센다
                return None
            if now - job.cancel_at > CANCEL_WAIT_S:
                self.active = None
                self.worker_ready = False
                return ("kill", job.token)
            return None
        if self.states.get(job.photo_id) == PREPARING and job.began is not None and now - job.began > PREPARE_TIMEOUT_S:
            token = job.token
            self.worker_ready = False
            self.on_error(token, "timeout", now)
            return ("timeout", token)
        if self.states.get(job.photo_id) == READING and job.started is not None and now - job.started > READ_TIMEOUT_S:
            token = job.token
            self.worker_ready = False
            self.on_error(token, "timeout", now)
            return ("timeout", token)
        return None

    def slow(self, photo_id, now):
        """읽는 중이 `SLOW_HINT_S` 를 넘었나 — 'PC 가 바쁘면 더 걸려요' 보조 문구를 보일지."""
        job = self.active
        return job is not None and job.photo_id == photo_id and not job.cancelled and job.started is not None and now - job.started > SLOW_HINT_S

    def run_pending(self, now=0.0):
        """대기열을 공급자에게 차례로 맡긴다(동기 — 시험과 단순한 흐름용. 화면은 Job 스레드에서 같은 순서로 `begin_next`·`mark_ready`·`provider.read`·`on_result` 를 부른다) → `[(사진 번호, 상태 이름), …]`."""
        done = []
        while True:
            job = self.begin_next(now)
            if job is None:
                return done
            self.mark_ready(now)
            outcome = self.provider.read(job)
            status = self.on_error(job.token, outcome.error, now) if outcome.error else self.on_result(job.token, outcome.lines, now)
            done.append((job.photo_id, status))

    # ---- 줄 ----
    def lines(self, photo_id):
        """읽은 줄들 `((글, 확인했나), …)` — 화면이 목록을 그릴 때 쓴다."""
        photo = self.board.photo(photo_id)
        return tuple((item.text, item.confirmed) for item in photo.visible_text) if photo is not None else ()

    def _line_guard(self, photo_id):
        if self.board.photo(photo_id) is None:
            return "refused"
        return "busy" if self.is_busy(photo_id) else ""

    def _after_line_change(self, photo_id):
        self.board.undo, self.board.confirm_all_asked = None, 0
        self.board.notes.pop(photo_id, None)
        self.all_right_asked = (None, 0)

    def confirm_line(self, photo_id, index, on=True):
        """줄 하나를 '맞아요' 로 표시하거나 푼다 → `ok`·`unchanged`·`busy`·`refused`. 사진의 확정은 풀린다(줄 확인과 사진 확정은 따로다)."""
        guard = self._line_guard(photo_id)
        if guard or not isinstance(on, bool):
            return guard or "refused"
        try:
            updated = pm.confirm_item(self.board.manifest, photo_id, pm.TEXTS, index, on)
        except AppError:
            return "refused"
        if updated == self.board.manifest:
            return "unchanged"
        self.board.manifest = updated
        self._after_line_change(photo_id)
        self.undo_line = None
        return "ok"

    def edit_line(self, photo_id, index, text):
        """줄의 글을 고친다 → `ok`·`unchanged`·`invalid`(같은 입구 검사에 걸림 — 이유 문장은 `line_error`)·`busy`·`refused`. 고친 줄은 다시 확인 전이 된다."""
        guard = self._line_guard(photo_id)
        if guard:
            return guard
        clean, reason = pm.check_text("observation", text if isinstance(text, str) else "")
        if reason is not None:
            self.line_errors[(photo_id, index)] = reason
            return "invalid"
        self.line_errors.pop((photo_id, index), None)
        try:
            updated = pm.edit_item(self.board.manifest, photo_id, pm.TEXTS, index, clean)
        except AppError:
            return "refused"
        if updated == self.board.manifest:
            return "unchanged"
        self.board.manifest = updated
        self._after_line_change(photo_id)
        self.undo_line = None
        return "ok"

    def line_error(self, photo_id, index):
        return self.line_errors.get((photo_id, index), "")

    def remove_line(self, photo_id, index):
        """줄 하나를 뺀다(한 번 되돌릴 수 있다) → `ok`·`busy`·`refused`."""
        guard = self._line_guard(photo_id)
        if guard:
            return guard
        before = self.board.manifest
        try:
            after = pm.remove_item(before, photo_id, pm.TEXTS, index)
        except AppError:
            return "refused"
        self.board.manifest = after
        self._after_line_change(photo_id)
        self.undo_line = (photo_id, before, after)
        return "ok"

    def undo_remove_line(self):
        """방금 뺀 줄을 되돌린다 — 그 뒤에 목록이 바뀌었으면 되돌릴 수 없다(`refused`)."""
        if self.undo_line is None:
            return "refused"
        photo_id, before, after = self.undo_line
        self.undo_line = None
        if self.board.manifest != after or self.is_busy(photo_id):
            return "refused"
        self.board.manifest = before
        self._after_line_change(photo_id)
        return "ok"

    def merge_line(self, photo_id, index):
        """줄과 바로 아래 줄을 이어 새 확인 전 줄 하나로 만든다 → `ok`·`invalid`(이은 글이 입구 검사에 걸림 — 이유는 `line_error`)·`busy`·`refused`."""
        guard = self._line_guard(photo_id)
        if guard:
            return guard
        try:
            updated = pm.merge_items(self.board.manifest, photo_id, pm.TEXTS, index)
        except AppError as error:
            self.line_errors[(photo_id, index)] = reason_of(error)
            error.__traceback__ = None
            return "invalid"
        self.line_errors.pop((photo_id, index), None)
        self.board.manifest = updated
        self._after_line_change(photo_id)
        self.undo_line = None
        return "ok"

    def ask_all_right(self, photo_id):
        """'읽은 글 모두 맞아요' 1단계 — 확인하지 않은 줄 수를 확인 줄에 보인다(바꾸지 않는다) → `ask`·`none`·`busy`·`refused`."""
        guard = self._line_guard(photo_id)
        if guard:
            return guard
        waiting = sum(1 for _text, confirmed in self.lines(photo_id) if not confirmed)
        if not waiting:
            self.all_right_asked = (None, 0)
            return "none"
        self.all_right_asked = (photo_id, waiting)
        return "ask"

    def all_right(self, photo_id):
        """2단계 — 확인 줄에서 눌렀을 때만 이 사진의 확인 전 줄을 모두 '맞아요' 로 표시한다(1단계를 건너뛰고 부르면 아무것도 하지 않는다). 사진은 확정하지 않는다 → `ok`·`refused`·`busy`."""
        guard = self._line_guard(photo_id)
        if guard:
            return guard
        if self.all_right_asked[0] != photo_id or not self.all_right_asked[1]:
            return "refused"
        done = 0
        for index, (_text, confirmed) in enumerate(self.lines(photo_id)):
            if not confirmed:
                self.board.manifest = pm.confirm_item(self.board.manifest, photo_id, pm.TEXTS, index, True)
                done += 1
        self.last_all_right = done
        self._after_line_change(photo_id)
        self.undo_line = None
        return "ok"

    def cancel_all_right(self):
        self.all_right_asked = (None, 0)

    def confirmed_line_count(self, photo_id):
        return sum(1 for _text, confirmed in self.lines(photo_id) if confirmed)

    def shutdown(self):
        """앱 종료 — 모든 요청을 취소하고 공급자(작업자)를 끝낸다. 여러 번 불러도 같다."""
        self.reset()
        self.provider.shutdown()
        self.worker_ready = False


__all__ = ["BUSY_STATES", "CANCELLED", "CANCEL_WAIT_S", "COUNTED", "DISABLING", "DONE", "ERROR_CODE", "FAILED", "FAILURE_LIMIT", "FakeOcrProvider", "IDLE", "IDLE_EXIT_S", "OcrBoard", "OcrJob", "OcrOutcome",
           "OcrProvider", "PREPARE_TIMEOUT_S", "PREPARING", "QUEUED", "READING", "READ_TIMEOUT_S", "SIZES", "SIZE_BIG", "SIZE_NORMAL", "SLOW_HINT_S", "STATES", "code_of"]
