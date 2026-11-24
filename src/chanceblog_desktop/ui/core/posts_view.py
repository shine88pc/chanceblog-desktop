"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)의 상태·동작·뷰모델 — 순수 파이썬(화면 도구를 모른다). Qt 화면은 `view()` 가 만든 딕셔너리를 그리기만 한다: 어떤 상태인지·어느 단추를 켤지·어떤 문장을 보일지는 여기서 정한다.

흐름과 규칙:
  · **읽기와 쓰기를 가른다**: 화면을 열고(`start_load`) 글을 열고(`start_open`) 파일을 읽고(`start_read_file`) 플랫폼을 고르고 대화상자를 여닫는 것은 파일에 닿지 않는다. 파일에 쓰는 일은 `start_import`·`start_review`·`start_approve`·`start_revoke` 넷뿐이고
    사용자가 가져오기·검토 시작·승인·승인 취소를 눌렀을 때만 불린다(공급자의 쓰기 메서드 — 작업 스레드에서). 쓰기는 **한 번에 하나**(`posts-write`)이고 복원이 도는 동안은 시작하지 않는다(`save_gate.py`).
  · **승인은 구조로 막는다**(`approval`): 이 앱을 연 뒤 **이 글·이 플랫폼·이 판**의 검토 결과를 받았고, 그 플랫폼 상태가 '검토 중' 이고, 막힘(발행 전 검사·건강 효과 단정·비밀 모양·네이버 유사도)이 없을 때만 켜진다.
    켜져도 **확인창이 먼저**다 — `approve_dialog` 를 부르지 않고(= 확인창을 보이지 않고) `start_approve` 를 부르면 아무것도 하지 않는다(`unconfirmed`).
  · **입력은 지워지지 않는다**: 가져오기·Pages 값 대화의 글은 칸(위젯)에만 있다. 실패해도 대화는 그대로 열려 있고 칸의 글도 그대로다(이유만 대화 안에 보인다). 컨트롤러는 '입력이 있나' 만 안다.
  · 목록은 한 번에 `PAGE` 개만 그린다(`더 보기`). 모든 동적 글(제목·사유)은 **가린 뒤에 줄인다**. 오류 코드는 접힌 진단 정보에만 있고 문장은 종류별로 정해진 쉬운 말이다.
  · **앱을 닫을 때** 가져오기 대화에 입력이 있으면 같은 대화 안의 확인 줄이 먼저다(`request_quit`). 화면을 옮겨도 열린 글·고른 플랫폼은 컨트롤러에 남는다.
  · **낡은 읽기 결과는 받지 않는다**: 쓰기가 끝날 때마다 세대 번호(`epoch`)가 오르고, 그 전에 시작한 읽기의 결과는 쓰기 전 모습이라 버린다(`is_stale` — 셸이 다시 읽는다). 낡은 읽기의 실패도 다른 글·닫은 글에는 닿지 않는다.
  · **Pages 값**: 대화를 닫으면(어느 길로든) 칸의 값을 이 앱을 연 동안만 기억해 다시 열 때 채워 준다. 키·토큰 모양이 든 값은 기억하지 않는다(`remember_pages`).
실제 글 제목·본문은 이 코드에 없다(받은 값을 가려서 보이기만 한다).
"""
from __future__ import annotations

from dataclasses import replace

from ...content import status as st
from . import post_rules as rules
from .jobs import JobFailure
from .posts import (KINDS, NAVER_PLATFORMS, PAGES, PLATFORMS, ApproveRequest, ImportRequest, ReviewRequest, RevokeRequest)
from .save_gate import blocked_while_restoring
from .text import T

LOAD_KEY = "posts-load"                                      # 글 목록을 읽는 작업의 이름(다른 화면의 읽기와 따로 돈다)
DETAIL_KEY = "posts-detail"                                  # 글 하나를 읽는 작업
FILE_KEY = "posts-file"                                      # 가져올 파일을 읽는 작업(읽기뿐)
WRITE_KEY = "posts-write"                                    # 가져오기·검토 시작·승인·승인 취소 — 한 번에 하나(중복 누름은 거절)
LIST_STATES = ("loading", "normal", "empty", "error", "partial", "offline")
DETAIL_STATES = ("none", "loading", "normal", "error")
RELOAD_KINDS = ("stale", "notfound", "state")                # 이 실패 뒤에는 화면이 글 상태를 다시 읽는다
BADGE = {"pass": ("ok", "post_badge_pass"), "block": ("danger", "post_badge_block"), "check": ("warning", "post_badge_check"), "info": ("muted", "post_badge_info")}
HEALTH_TEXT = {"general": "post_health_general", "mark": "post_health_mark", "evidence": "post_health_evidence", "stop": "post_health_stop"}
HEALTH_BADGE = {"general": "pass", "mark": "info", "evidence": "check", "stop": "block"}
SIMILARITY_TEXT = {"ok": "post_naver_similarity_ok", "warn": "post_naver_similarity_warn", "high": "post_naver_similarity_high"}
SIMILARITY_BADGE = {"ok": "pass", "warn": "check", "high": "block"}


PAGES_FIELDS = ("category", "lang", "image_url", "tags", "description")      # Pages 값 칸의 이름들
KEPT_OPEN_KINDS = ("input", "check", "secret", "other", "locked", "disk", "io")   # Pages 값 대화를 열어 둔 채 이유만 보이는 실패 종류(값은 칸에 그대로다)


def _failure_text(failure):
    """실패의 문장 — 어댑터·가짜가 종류별로 만든 고정 문장이고, 어떤 값이 와도 비밀 모양을 가린 뒤 줄여 낸다."""
    from .app_state import clean_failure
    return clean_failure(failure).user_message


def _stamped(item, epoch):
    """읽은 값에 세대 번호를 붙인다(값 객체는 바꿀 수 없어 새로 만든다) — 세대 번호 칸이 없는 값은 그대로 둔다."""
    return replace(item, epoch=epoch) if hasattr(item, "epoch") else item


class PostsController:
    save_gate = None                                         # 복원이 도는 중이면 참을 돌려주는 함수 — `AppState` 가 이어 준다(F030: 복원 중에는 쓰기를 시작하지 않는다)

    def __init__(self, provider, runner):
        self.provider, self.runner = provider, runner
        # 목록
        self.state = "loading"
        self.data = None
        self.failure = None
        self.failed_at = None
        self.limit = rules.PAGE
        self.load_count = 0
        # 열린 글
        self.open_id = None
        self.detail = None
        self.detail_state = "none"
        self.detail_failure = None
        self.detail_failed_at = None
        self.platform = PAGES
        self.review = None                                   # 이 앱을 연 뒤 받은 가장 최근 검토 결과(글 하나·플랫폼 하나) — 승인 조건의 한 축이다
        self.pages_raw = {}                                  # 글 번호 → Pages 값 칸 글(이 앱을 연 동안만 기억하고 파일에는 쓰지 않는다)
        self.notice = None                                   # (수준, 글) — 마지막 동작의 결과
        self.pending = None                                  # 돌고 있는 쓰기: {"kind", …}
        self.approve_asked = None                            # 확인창을 보인 승인 (글 번호, 플랫폼, 판) — 이것과 같은 승인만 시작한다
        self.epoch = 0                                       # 쓰기가 끝날 때마다 오른다 — 그 전에 시작한 읽기의 결과는 낡은 것이라 받지 않는다
        # 대화상자
        self.import_open = False
        self.import_kind = "markdown"
        self.import_dirty = False                            # 가져오기 칸에 입력이 있나(글은 칸에만 있다)
        self.import_message = ""
        self.import_note = ""
        self.import_ask = False                              # 닫기 전 '입력이 사라져요' 확인 줄을 보이는 중
        self.import_quit = False                             # 그 확인 줄이 앱 닫기(X)를 기다리는 중 — `그래도 닫기` 를 누르면 앱도 닫힌다(확인 줄이 거두어지면 함께 내려간다)
        self.pages_open = False
        self.pages_problems = {}
        self.pages_message = ""

    # ---- 읽기(파일·폴더를 만들지 않는다) ----
    @property
    def loading(self):
        return self.runner.running(LOAD_KEY)

    @property
    def busy(self):
        return self.runner.running(WRITE_KEY)

    @property
    def reading_file(self):
        return self.runner.running(FILE_KEY)

    def restoring(self):
        return self.save_gate is not None and bool(self.save_gate())

    def profiles(self):
        return tuple(self.data.profiles) if self.data is not None else ()

    def start_load(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """글 목록을 작업 스레드에서 읽는다 — 이미 읽는 중이거나 쓰는 중이면 None. 처음이거나 오류 뒤에는 '읽는 중' 모습이 되고, 보이는 내용이 있으면 그대로 둔 채 새 값이 오면 바꾼다."""
        if self.busy:
            return None
        epoch = self.epoch
        job = self.runner.start(LOAD_KEY, lambda progress, cancelled: _stamped(self.provider.load_posts(progress, cancelled), epoch), on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.load_count += 1
        if self.data is None or self.state == "error":
            self.state = "loading"
        return job

    @staticmethod
    def _state_for(data):
        if data is None or not data.rows:
            return "empty"
        if data.offline:
            return "offline"
        return "partial" if any(row.error for row in data.rows) else "normal"

    def is_stale(self, item):
        """읽는 동안 쓰기가 끝났나 — 세대 번호가 붙은 읽기 결과가 지금 세대와 다르면 쓰기 전 모습이다(번호가 없는 값은 낡았다고 보지 않는다)."""
        stamp = getattr(item, "epoch", None)
        return stamp is not None and stamp != self.epoch

    def apply_loaded(self, data):
        """읽은 목록을 받는다 → 받았으면 True. 읽는 동안 쓰기가 끝났으면(쓰기 전 목록이라) 버리고 False — 셸이 다시 읽는다."""
        if self.is_stale(data):
            return False
        self.data, self.failure = data, None
        self.state = self._state_for(data)                   # 열어 둔 글이 그 사이 사라졌는지는 목록이 아니라 그 글을 다시 읽을 때 안다(늦게 온 옛 목록이 방금 가져온 글을 닫지 않게)
        return True

    def apply_load_failed(self, failure, when=None):
        """읽기가 실패했다 — 이전에 보이던 내용은 지우지 않는다(다시 읽으면 이어서 쓴다). 상태에는 비밀 모양을 가린 글만 남긴다."""
        from .app_state import clean_failure
        self.failure, self.failed_at = clean_failure(failure), when
        self.state = "error"

    def apply_unexpected(self, error, when=None):
        """화면 스레드의 슬롯에서 예상하지 못한 예외가 났다 — 받아 둔 값을 버리고 오류 상태로(쉬운 문장 + 예외 이름만 진단 정보에). 대화상자의 입력은 칸에 남는다."""
        from .app_state import clean_failure
        self.data, self.pending = None, None
        self.epoch += 1                                      # 받아 둔 값을 모두 버렸다 — 아직 오고 있는 읽기 결과도 받지 않는다
        self.close_post()
        self.failure, self.failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.state = "error"

    def apply_cancelled(self):
        self.state = self._state_for(self.data) if self.data is not None else "error"

    def show_more(self):
        self.limit += rules.PAGE
        return True

    def row(self, project_id):
        return next((item for item in (self.data.rows if self.data is not None else ()) if item.project_id == project_id), None)

    # ---- 글 열기·닫기 ----
    def _default_platform(self, project_id):
        found = self.row(project_id)
        for key, status in (found.statuses if found is not None else ()):
            if status != st.NOT_STARTED:
                return key
        return PAGES

    def start_open(self, project_id, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """글을 열고 그 글을 작업 스레드에서 읽는다 → `(상태, 작업)`: `("unknown", None)` 목록에 없거나 읽을 수 없는 글 · `("busy", None)` 이미 읽는 중 · `("started", 작업)`."""
        found = self.row(project_id)
        if found is None or found.error:
            return "unknown", None
        if self.open_id != project_id:
            self.platform, self.review, self.approve_asked = self._default_platform(project_id), None, None
        return self._start_detail(project_id, {"on_progress": on_progress, "on_done": on_done, "on_error": on_error, "on_cancel": on_cancel})

    def _start_detail(self, project_id, callbacks, keep_notice=False):
        """그 글을 작업 스레드에서 읽는다 — 목록에 그 글이 있는지는 보지 않는다(방금 가져온 글은 목록이 아직 모른다). 읽기를 시작할 때의 세대 번호를 결과·실패에 붙인다.
        글을 새로 열 때는 지난 알림을 거두고, 실패·낡음 뒤 **같은 글을 다시 읽을 때는 알림을 남긴다**(왜 다시 읽는지 알리는 안내가 곧바로 사라지지 않게)."""
        epoch = self.epoch

        def work(progress, cancelled):
            try:
                return _stamped(self.provider.load_post(project_id, progress, cancelled), epoch)
            except JobFailure as failure:
                failure.read_of = (project_id, epoch)        # 어느 글을 어느 세대에 읽다가 실패했나 — 늦게 온 실패가 다른 글에 닿지 않게
                raise

        job = self.runner.start(DETAIL_KEY, work, **callbacks)
        if job is None:
            return "busy", None
        self.open_id = project_id
        if not keep_notice:
            self.notice = None
        if self.detail is None or self.detail.project_id != project_id or self.detail_state == "error":
            self.detail, self.detail_state = None, "loading"
        return "started", job

    def reload_detail(self, keep_notice=False, **callbacks):
        """열린 글을 다시 읽는다(쓰기 뒤·낡음 뒤). 열린 글이 없으면 None. `keep_notice` — 방금 실패·낡음을 알린 안내를 남긴 채 읽는다(그냥 다시 읽을 때는 지난 알림을 거둔다)."""
        if self.open_id is None:
            return None
        return self._start_detail(self.open_id, {"on_progress": None, "on_done": None, "on_error": None, "on_cancel": None} | callbacks, keep_notice)[1]

    def apply_detail(self, detail):
        """읽은 글을 받는다 — 그 사이 다른 글을 열었거나 닫았으면(늦게 온 결과) 버리고, 읽는 동안 쓰기가 끝났어도(쓰기 전 모습이라) 버린다."""
        if detail is None or detail.project_id != self.open_id or self.is_stale(detail):
            return False
        self.detail, self.detail_state, self.detail_failure = detail, "normal", None
        return True

    def apply_detail_failed(self, failure, when=None):
        """글 읽기가 실패했다 → `"gone"`(글이 없다 — 목록으로 돌아가 다시 읽어야 한다) · `"error"` · `"stale"`(읽는 동안 쓰기가 끝났다 — 셸이 그 글을 다시 읽는다) ·
        `"ignored"`(그 글을 이미 닫았거나 다른 글을 열었다 — 늦게 온 실패는 아무것도 바꾸지 않는다)."""
        from .app_state import clean_failure
        read_of = getattr(failure, "read_of", None)
        if self.open_id is None or (read_of is not None and read_of[0] != self.open_id):
            return "ignored"
        if read_of is not None and read_of[1] != self.epoch:
            return "stale"
        if getattr(failure, "kind", "") == "notfound":
            self.close_post()
            self.notice = ("warning", T["post_detail_gone"])
            return "gone"
        self.detail_failure, self.detail_failed_at = clean_failure(failure), when
        self.detail_state = "error"
        return "error"

    def close_post(self):
        """열린 글을 닫고 목록으로 — 닫은 글 번호(포커스를 돌려줄 곳)를 돌려준다. 검토 결과·승인 확인 표시는 버린다."""
        closed = self.open_id
        self.open_id, self.detail, self.detail_state, self.detail_failure = None, None, "none", None
        self.review, self.approve_asked = None, None
        return closed

    def select_platform(self, key):
        if key not in PLATFORMS:
            return False
        self.platform, self.approve_asked = key, None
        return True

    # ---- 가져오기 대화(칸의 글은 위젯에만 있다) ----
    def open_import(self):
        if self.busy or self.import_open:
            return False
        self.import_open, self.import_dirty, self.import_message, self.import_note, self.import_ask, self.import_quit = True, False, "", "", False, False
        self.import_kind = "markdown"
        return True

    def set_import_kind(self, kind):
        if kind not in KINDS or self.busy:
            return False
        self.import_kind = kind
        return True

    def import_edited(self, dirty):
        """칸을 고쳤다 — 입력이 있는지만 안다(글은 받지 않는다). 고치면 이전 거절 문장·확인 줄·앱 닫기 기다림은 거둔다."""
        self.import_dirty, self.import_message, self.import_ask, self.import_quit = bool(dirty), "", False, False
        return True

    def request_close_import(self):
        """대화를 닫으려 한다 → `"closed"`(닫았다) · `"ask"`(입력이 있어 확인 줄을 보인다 — **`그래도 닫기`(`close_import`) 를 눌러야 닫힌다**. 확인 줄이 떠 있을 때 `취소` 를 또 눌러도 닫지 않는다) · `"busy"`(가져오는 중에는 닫지 않는다).
        이 길은 대화만 닫으려는 뜻이라 앱 닫기를 기다리던 것이 있어도 거둔다."""
        if not self.import_open:
            return "closed"
        if self.busy:
            return "busy"
        if self.import_dirty:
            self.import_ask, self.import_quit = True, False
            return "ask"
        return self.close_import()

    def request_quit(self):
        """창 닫기(X·Alt+F4)가 왔다 → `"none"`(가져오는 글이 없어 그대로 닫는다) · `"busy"`(가져오는 중이라 닫지 않는다) · `"ask"`(같은 대화 안에 확인 줄을 보이고 앱 닫기를 기다린다 — `그래도 닫기` 가 앱도 닫는다).
        기다림 표시(`import_quit`)는 확인 줄이 거두어지는 모든 길(`계속 쓰기`·입력·`취소`·닫힘·새 가져오기)에서 함께 내려간다."""
        if not self.has_unsaved():
            return "none"
        if self.busy:
            return "busy"
        self.import_ask, self.import_quit = True, True
        return "ask"

    def close_import(self):
        self.import_open = self.import_dirty = self.import_ask = self.import_quit = False
        self.import_message = self.import_note = ""
        return "closed"

    def keep_import(self):
        """`계속 쓰기` — 확인 줄과 앱 닫기 기다림을 거둔다."""
        self.import_ask = self.import_quit = False
        return True

    def has_unsaved(self):
        return self.import_open and self.import_dirty

    def close_dialog(self):
        """앱 닫기 확인창의 글(없으면 None) — 가져오기 대화에 입력이 있을 때만이다. `posts` 표시 — 셸이 다른 확인과 가른다."""
        if not self.has_unsaved():
            return None
        return {"title": T["post_close_title"], "body": T["post_close_body"], "ok": T["post_close_ok"], "cancel": T["post_close_cancel"], "posts": True}

    def start_read_file(self, path, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """고른 파일을 작업 스레드에서 읽는다(읽기뿐) → `(상태, 작업)`: `("busy", None)` 쓰는 중이거나 이미 읽는 중 · `("started", 작업)`."""
        if self.busy or self.reading_file or not self.import_open or self.import_kind != "markdown":
            return "busy", None
        job = self.runner.start(FILE_KEY, lambda progress, cancelled: self.provider.read_import_file(path, progress, cancelled), on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return "busy", None
        self.import_message, self.import_note = "", ""
        return "started", job

    def apply_file(self, outcome, replaced=False):
        """읽은 파일을 받는다 → `ImportFile`(셸이 칸에 채우고 버린다). 글은 이 컨트롤러가 쥐지 않는다. `replaced` — 본문 칸에 글이 이미 있어 바꾸게 됐다(되돌리려면 Ctrl+Z 라고 알린다)."""
        file = outcome.file
        note = T["post_im_cp949"] if file.encoding == "cp949" else T["post_im_read_ok"]
        self.import_note = note + " " + T["post_im_replaced"] if replaced else note
        self.import_message = ""
        return file

    def apply_file_failed(self, failure):
        self.import_message, self.import_note = _failure_text(failure), ""

    @blocked_while_restoring
    def start_import(self, title, body, **callbacks):
        """`가져오기` — `(상태, 내용)`: `("busy", None)` · `("invalid", None)` 제목이나 본문이 비었다 · `("started", 작업)`."""
        if self.busy or not self.import_open:
            return "busy", None
        if not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not body.strip():
            self.import_message = T["post_fail_input_plain"]
            return "invalid", None
        request = ImportRequest(self.import_kind, title, body)
        self.import_message, self.import_note, self.import_ask, self.import_quit = "", "", False, False
        return self._start("import", {}, lambda progress, cancelled: self.provider.import_post(request, progress, cancelled), callbacks)

    # ---- Pages 검토 값 대화 ----
    def open_pages(self):
        """Pages 값 대화를 연다 → 처음 값(지난번에 쓴 칸 글, 없으면 빈 값 + 한국어) — 열 수 없으면 None."""
        if self.detail is None or self.busy or self.pages_open or self.restoring():
            return None
        self.pages_open, self.pages_problems, self.pages_message = True, {}, ""
        return dict(self.pages_raw.get(self.open_id) or rules.pages_raw_of(None))

    def close_pages(self, raw=None):
        """Pages 값 대화를 닫는다 — `raw`(닫을 때 칸에 있던 값)가 있으면 이 앱을 연 동안 다시 열 때 채워 주려고 기억한다(`remember_pages`)."""
        if raw is not None:
            self.remember_pages(raw)
        self.pages_open, self.pages_problems, self.pages_message = False, {}, ""
        return True

    def remember_pages(self, raw):
        """쓰던 Pages 값을 이 앱을 연 동안만 기억한다(파일에 쓰지 않는다) → 기억했으면 True. **키·토큰 모양이 든 값은 기억하지 않는다**(거절된 글이 다음에 열 때 칸에 다시 채워지지 않게). 열린 글이 없으면 기억하지 않는다."""
        if self.open_id is None or not isinstance(raw, dict):
            return False
        values = {name: str(raw.get(name) or "") for name in PAGES_FIELDS}
        if rules.secret_spots("", "\n".join(values[name] for name in ("category", "image_url", "tags", "description"))):
            return False
        self.pages_raw[self.open_id] = values
        return True

    # ---- 검토·승인·승인 취소(쓰기) ----
    def _start(self, kind, payload, work, callbacks):
        job = self.runner.start(WRITE_KEY, work, **callbacks)
        if job is None:
            return "busy", None
        self.pending = {"kind": kind, **payload}
        self.notice = None
        return "started", job

    @blocked_while_restoring
    def start_review(self, platform, raw=None, **callbacks):
        """`검토 시작`·`다시 검토` — `(상태, 내용)`: `("busy", None)` · `("state", None)` 이 상태에서는 시작하지 않는다(올라간 글 …) · `("profile", None)` 네이버 프로필이 없다 · `("invalid", 문제들)` Pages 값에 문제가 있어 서비스를 부르지 않음 · `("started", 작업)`.
        Pages 는 `raw`(분야·언어·대표 이미지 주소·태그·한 줄 설명 칸 글)가 있어야 한다."""
        detail = self.detail
        if detail is None or self.open_id is None or self.busy:
            return "busy", None
        state = detail.platform(platform) if platform in PLATFORMS else None
        if state is None or state.status not in rules.REVIEWABLE:
            return "state", None
        if platform in NAVER_PLATFORMS and platform not in self.profiles():
            return "profile", None
        pages = None
        if platform == PAGES:
            problems = rules.pages_problems(raw or {})
            self.pages_problems = problems
            if problems:
                return "invalid", problems
            pages = rules.pages_values_of(raw)
            self.remember_pages(raw)                         # 값은 칸에 그대로 있고, 컨트롤러는 키 모양이 없을 때만 다시 열 때 쓸 값을 기억한다
        request = ReviewRequest(detail.project_id, platform, pages)
        self.platform, self.approve_asked = platform, None
        self.pages_message = ""
        return self._start("review", {"id": detail.project_id, "platform": platform, "revision": detail.revision}, lambda progress, cancelled: self.provider.review_post(request, progress, cancelled), callbacks)

    def approval(self):
        """지금 고른 플랫폼의 `승인하기` 를 켤 수 있나 → (가능한가, 이유 문구 열쇠). 규칙은 `post_rules.approval_state` 한 곳이다."""
        return rules.approval_state(self.review, self.detail, self.platform, busy=self.busy, restoring=self.restoring())

    def approve_dialog(self):
        """승인 확인창의 글 — 승인할 수 있을 때만 있고(아니면 None), 이 글을 **보였다는 표시**를 남긴다. 이 표시가 없으면 `start_approve` 는 시작하지 않는다."""
        ok, _why = self.approval()
        if not ok:
            return None
        detail = self.detail
        self.approve_asked = (detail.project_id, self.platform, detail.revision)
        return {"title": T["post_confirm_title"], "body": T["post_confirm_body"].format(name=rules.platform_text(self.platform), revision=detail.revision), "ok": T["post_confirm_ok"], "cancel": T["post_confirm_cancel"]}

    def discard_approve(self):
        self.approve_asked = None

    @blocked_while_restoring
    def start_approve(self, **callbacks):
        """확인창에서 `승인` 을 눌렀다 — `(상태, 내용)`: `("refused", 이유 열쇠)` 승인할 수 없다 · `("unconfirmed", None)` 확인창을 보이지 않았다 · `("started", 작업)`."""
        ok, why = self.approval()
        if not ok:
            self.approve_asked = None
            return "refused", why
        detail = self.detail
        asked = (detail.project_id, self.platform, detail.revision)
        if self.approve_asked != asked:
            return "unconfirmed", None
        self.approve_asked = None
        request = ApproveRequest(*asked)
        return self._start("approve", {"id": asked[0], "platform": asked[1], "revision": asked[2]}, lambda progress, cancelled: self.provider.approve_post(request, progress, cancelled), callbacks)

    @blocked_while_restoring
    def start_revoke(self, **callbacks):
        """`승인 취소` — `(상태, 내용)`: `("busy", None)` · `("state", None)` 승인된 상태가 아니다 · `("started", 작업)`. 되돌릴 수 있는 일이라 확인창은 없다."""
        detail = self.detail
        state = detail.platform(self.platform) if detail is not None else None
        if self.busy:
            return "busy", None
        if state is None or state.status not in rules.APPROVED_NOW:
            return "state", None
        request = RevokeRequest(detail.project_id, self.platform)
        return self._start("revoke", {"id": detail.project_id, "platform": self.platform}, lambda progress, cancelled: self.provider.revoke_post(request, progress, cancelled), callbacks)

    def apply_write_ok(self, outcome):
        """쓰기가 끝났다 — 새 모습을 받는다 → 셸이 할 일(`{"reload_list": 참}` — 목록의 상태 글이 바뀌었다)."""
        work, self.pending = self.pending or {"kind": ""}, None
        self.epoch += 1                                      # 이제 이 쓰기 전에 시작한 읽기는 낡은 것이다
        detail = outcome.detail
        if outcome.kind == "imported":
            self.close_import()
            self.open_id, self.detail, self.detail_state, self.detail_failure = detail.project_id, detail, "normal", None
            self.platform, self.review, self.approve_asked = PAGES, None, None
            self.notice = ("ok", T["post_im_done"].format(title=rules.shown(detail.title, 60) or T["post_untitled"]))
            return {"reload_list": True}
        if detail is not None and detail.project_id == self.open_id:
            self.detail, self.detail_state = detail, "normal"
        if outcome.kind == "reviewed":
            self.close_pages()
            self.review = outcome.review
            self.notice = ("ok", T["post_done_review"])
        elif outcome.kind == "approved":
            self.notice = ("ok", T["post_done_approved"])
        elif outcome.kind == "revoked":
            self.notice = ("ok", T["post_done_revoked"])
        return {"reload_list": True}

    def apply_write_failed(self, failure):
        """쓰기가 실패했다 — 입력은 그대로다. 글이 바뀌었거나 사라졌거나 상태가 달라졌으면 `{"reload": 참}` 을 돌려줘 화면이 최신 상태를 다시 읽게 한다. 문장은 종류별로 정해진 쉬운 말뿐이다."""
        work, self.pending = self.pending or {"kind": ""}, None
        self.epoch += 1                                      # 실패해도 쓰기가 끝났다 — 그 전에 시작한 읽기 말고 지금부터 읽은 것만 믿는다
        kind = getattr(failure, "kind", "other")
        text = _failure_text(failure) if failure is not None else T["post_fail_other"]
        if work["kind"] == "import":
            self.import_message = text
            return {}
        if work["kind"] == "review" and self.pages_open and kind in KEPT_OPEN_KINDS:
            self.pages_message = text                        # Pages 값 대화는 열어 둔 채 이유만 보인다 — 값은 칸에 그대로다(키 모양이 든 값은 컨트롤러가 기억하지 않는다)
            return {}
        self.close_pages()
        self.notice = ("error", text)
        if kind in RELOAD_KINDS:
            self.review = None
            return {"reload": True}
        if work["kind"] == "approve" and kind in ("gate", "similarity"):
            self.review = None                               # 서비스가 승인 순간에 다시 검사해 거절했다 — 옛 검토 결과는 더 믿지 않는다(다시 검토해야 승인할 수 있다)
        return {}

    def apply_write_unexpected(self, error):
        self.pending = None
        self.epoch += 1
        self.close_pages()
        self.notice = ("error", T["post_fail_other"])

    # ---- 뷰모델 ----
    def _row_view(self, row):
        meta = T["post_row_meta"].format(revision=row.revision, when=rules.when_text(row.updated_at) or "-")
        title = rules.shown(row.title, rules.TITLE_SHOWN) or T["post_untitled"]
        if row.error:
            return {"id": row.project_id, "title": T["post_row_unreadable"], "meta": "", "status_lines": [], "unreadable": True, "a11y": T["post_row_unreadable"],
                    "open": None, "focus_key": f"post:row:{row.project_id}"}
        lines = [T["post_platform_line"].format(name=rules.platform_text(key), status=rules.status_text(status)) for key, status in row.statuses if status != st.NOT_STARTED]
        lines = lines or [T["post_row_none"]]
        return {"id": row.project_id, "title": title, "meta": meta, "status_lines": lines, "unreadable": False, "a11y": T["post_row_open_a11y"].format(title=title, meta=meta + ". " + " · ".join(lines)),
                "open": {"text": T["post_row_open"], "a11y": T["post_row_open_a11y"].format(title=title, meta=meta)}, "focus_key": f"post:row:{row.project_id}"}

    def _list_view(self):
        rows = list(self.data.rows) if self.data is not None else []
        shown_rows = rows[:self.limit]
        return {"count": T["post_count"].format(n=len(rows)) if rows else "", "rows": [self._row_view(row) for row in shown_rows], "a11y": T["post_list_a11y"],
                "more": {"text": T["post_more"], "a11y": T["post_more_a11y"]} if len(rows) > len(shown_rows) else None,
                "empty": {"title": T["post_empty_title"], "desc": T["post_empty_desc"], "button": T["post_import"]}}

    @staticmethod
    def _section(key, title, badge, lines=(), details=()):
        tone, text_key = BADGE[badge]
        return {"key": key, "title": title, "badge": {"tone": tone, "text": T[text_key]}, "lines": [rules.shown(line, 600) for line in lines], "details": [rules.shown(line, 400) for line in details],
                "a11y": T["post_section_a11y"].format(title=title, badge=T[text_key])}

    def _sections(self, review):
        sections = []
        if review.platform == PAGES:
            if review.gate_ok:
                sections.append(self._section("gates", T["post_sec_gates"], "pass", [T["post_gate_pass"]], review.gate_details if review.gate_details else ()))
            else:
                lines = [T["post_gate_blocked"].format(n=len(review.gate_codes))] + [rules.gate_sentence(code) for code in review.gate_codes]
                sections.append(self._section("gates", T["post_sec_gates"], "block", lines, review.gate_details))
        if review.warnings:
            sections.append(self._section("warnings", T["post_naver_warnings"] if review.platform in NAVER_PLATFORMS else T["post_gate_warn"], "info", review.warnings))
        health = review.health
        if health is not None:
            lines = [T[HEALTH_TEXT.get(health.stage, "post_health_general")]]
            if health.places:
                lines += [T["post_health_places"] + ": " + place for place in health.places]
            sections.append(self._section("health", T["post_sec_health"], HEALTH_BADGE.get(health.stage, "check"), lines))
        if review.spots:
            where = ", ".join(f"{name} {line}번째 줄" for name, line, _kind in review.spots[:3]) + (f" 외 {len(review.spots) - 3}건" if len(review.spots) > 3 else "")
            kinds = "·".join(dict.fromkeys(kind for _name, _line, kind in review.spots))
            sections.append(self._section("secret", T["post_sec_secret"], "block", [T["post_secret_found"].format(where=where, kinds=kinds)]))
        else:
            sections.append(self._section("secret", T["post_sec_secret"], "pass", [T["post_secret_none"]]))
        if review.platform in NAVER_PLATFORMS:
            info = review.similarity
            if info is None:
                sections.append(self._section("naver", T["post_sec_naver"], "info", [T["post_naver_similarity_none"]]))
            else:
                percent = f"{round(info.overall * 100)}"
                lines = [T[SIMILARITY_TEXT.get(info.level, "post_naver_similarity_warn")].format(percent=percent)] + list(info.reasons)
                sections.append(self._section("naver", T["post_sec_naver"], SIMILARITY_BADGE.get(info.level, "check"), lines))
        if review.summary:
            sections.append(self._section("summary", T["post_sec_summary"], "info", review.summary))
        return sections

    def _result_view(self, detail, state):
        review = self.review
        mine = review is not None and review.project_id == detail.project_id and review.platform == self.platform
        running = self.pending is not None and self.pending.get("kind") == "review" and self.pending.get("platform") == self.platform and self.busy
        if running:
            return {"state": "running", "text": T["post_res_running"], "sections": [], "title": T["post_res_title"], "a11y": T["post_res_a11y"]}
        if not mine:
            lost = state.status == st.REVIEW_REQUIRED
            return {"state": "lost" if lost else "none", "text": T["post_res_lost"] if lost else T["post_res_none"], "sections": [], "title": T["post_res_title"], "a11y": T["post_res_a11y"]}
        stale = review.revision != detail.revision
        return {"state": "stale" if stale else "ready", "text": T["post_res_stale"] if stale else T["post_res_for"].format(name=rules.platform_text(self.platform), revision=review.revision),
                "sections": [] if stale else self._sections(review), "title": T["post_res_title"], "a11y": T["post_res_a11y"]}

    def _panel_view(self, detail):
        platform = self.platform
        state = detail.platform(platform)
        name = rules.platform_text(platform)
        profile_missing = platform in NAVER_PLATFORMS and platform not in self.profiles()
        status = state.status if state is not None else st.NOT_STARTED
        reviewable = status in rules.REVIEWABLE
        revokable = status in rules.APPROVED_NOW
        restoring, busy = self.restoring(), self.busy
        can_approve, why = self.approval()
        again = status != st.NOT_STARTED and status != st.DRAFT_GENERATED
        review_enabled = reviewable and not busy and not restoring and not profile_missing
        approve_visible = status == st.REVIEW_REQUIRED
        primary = "approve" if (approve_visible and can_approve) else "review" if (reviewable and review_enabled and not revokable) else ""
        approve_why = "" if can_approve else T[why] if (approve_visible and why) else ""
        return {
            "platform": platform, "name": name, "status": status, "status_line": T["post_status_line"].format(status=rules.status_text(status)),
            "profile_missing": T["post_naver_profile_missing"] if profile_missing else "",
            "review": {"visible": reviewable, "enabled": review_enabled, "text": T["post_review_again"] if again else T["post_review_start"],
                       "a11y": (T["post_review_again_a11y"] if again else T["post_review_start_a11y"]).format(name=name), "note": T["post_review_again_note"] if revokable else "", "primary": primary == "review"},
            "approve": {"visible": approve_visible, "enabled": can_approve, "text": T["post_approve"], "a11y": T["post_approve_a11y"].format(name=name), "why": approve_why, "primary": primary == "approve"},
            "revoke": {"visible": revokable, "enabled": revokable and not busy and not restoring, "text": T["post_revoke"], "a11y": T["post_revoke_a11y"].format(name=name)},
            "after": T["post_review_after_note"] if (state is not None and status not in rules.REVIEWABLE and status not in (st.NOT_STARTED,)) else "",
            "result": self._result_view(detail, state if state is not None else None) if state is not None else None,
        }

    def _detail_view(self, diag):
        if self.detail_state == "loading":
            return {"state": "loading", "loading": {"text": T["post_detail_loading"], "a11y": T["post_detail_loading_a11y"]}, "back": self._back()}
        if self.detail_state == "error" or self.detail is None:
            return {"state": "error", "back": self._back(), "error": {"title": T["post_detail_error_title"], "desc": getattr(self.detail_failure, "user_message", "") or T["post_fail_read"], "button": T["post_retry"], "diag": diag}}
        detail = self.detail
        preview = detail.preview
        blocks = [{"kind": block.kind, "label": T[rules.KIND_LABEL.get(block.kind, "post_block_paragraph")], "text": block.text} for block in (preview.blocks if preview is not None else ())]
        chips = []
        for key in PLATFORMS:
            state = detail.platform(key)
            name, status = rules.platform_text(key), rules.status_text(state.status if state is not None else st.NOT_STARTED)
            chips.append({"key": key, "name": name, "text": T["post_chip"].format(name=name, status=status), "a11y": T["post_chip_a11y"].format(name=name, status=status), "selected": key == self.platform})
        return {
            "state": "normal", "back": self._back(), "title": rules.shown(detail.title, rules.TITLE_SHOWN) or T["post_untitled"],
            "meta": T["post_detail_meta"].format(revision=detail.revision, created=rules.when_text(detail.created_at) or "-", updated=rules.when_text(detail.updated_at) or "-"),
            "preview": {"title": T["post_preview_title"], "note": T["post_preview_note"], "a11y": T["post_preview_a11y"], "blocks": blocks, "empty": T["post_preview_empty"] if not blocks else "",
                        "info": T["post_preview_info"].format(chars=f"{preview.chars:,}", blocks=preview.total, images=preview.images, refs=preview.refs) if preview is not None else "",
                        "cut": T["post_preview_cut"].format(total=preview.total, shown=preview.shown) if preview is not None and preview.cut else ""},
            "review": {"title": T["post_review_title"], "sub": T["post_review_sub"], "pick_a11y": T["post_platform_pick_a11y"], "chips": chips, "panel": self._panel_view(detail)},
        }

    @staticmethod
    def _back():
        return {"text": T["post_back"], "a11y": T["post_back_a11y"]}

    def import_view(self, title_chars=0, body_chars=0):
        """가져오기 대화의 뷰모델 — 칸의 글자 수만 받는다(글은 받지 않는다)."""
        busy = self.busy or self.reading_file
        ready = title_chars > 0 and body_chars > 0 and not busy
        working = T["post_im_importing"] if self.busy else T["post_im_reading"] if self.reading_file else ""
        return {"title": T["post_im_title"], "intro": T["post_im_intro"], "a11y": T["post_im_a11y"], "kind": self.import_kind, "kind_label": T["post_im_kind"], "kind_a11y": T["post_im_kind_a11y"],
                "kinds": [{"key": key, "text": T["post_im_kind_" + key], "selected": key == self.import_kind} for key in KINDS], "kind_note": T["post_im_html_note"] if self.import_kind == "html" else "",
                "title_label": T["post_im_title_label"], "title_hint": T["post_im_title_hint"], "body_label": T["post_im_body_label"], "body_hint": T["post_im_body_hint"],
                "count": T["post_im_chars"].format(n=f"{body_chars:,}"), "count_a11y": T["post_im_chars_a11y"].format(n=f"{body_chars:,}"),
                "pick": {"text": T["post_im_pick"], "a11y": T["post_im_pick_a11y"], "visible": self.import_kind == "markdown", "enabled": not busy},
                "start": {"text": T["post_im_start"], "a11y": T["post_im_start_a11y"], "enabled": ready}, "cancel": {"text": T["post_im_cancel"], "a11y": T["post_im_cancel_a11y"], "enabled": not self.busy},
                "state": T["post_im_state_dirty"] if self.import_dirty and not working else "", "working": working, "message": self.import_message, "note": self.import_note,
                "discard": {"open": self.import_ask, "question": T["post_im_discard_q"], "yes": {"text": T["post_im_discard_yes"], "a11y": T["post_im_discard_yes_a11y"]},
                            "no": {"text": T["post_im_discard_no"], "a11y": T["post_im_discard_no_a11y"]}}}

    def pages_view(self):
        """Pages 값 대화의 뷰모델 — 칸 글은 위젯이 쥐고 있고 여기서는 문장·문제·단추만 정한다."""
        busy = self.busy
        return {"title": T["post_pv_title"], "intro": T["post_pv_intro"], "a11y": T["post_pv_title"], "message": self.pages_message,
                "fields": [{"name": "category", "label": T["post_pv_category"], "a11y": T["post_pv_category_a11y"], "hint": T["post_pv_category_hint"]},
                           {"name": "image_url", "label": T["post_pv_image"], "a11y": T["post_pv_image_a11y"], "hint": T["post_pv_image_hint"]},
                           {"name": "tags", "label": T["post_pv_tags"], "a11y": T["post_pv_tags_a11y"], "hint": T["post_pv_tags_hint"]},
                           {"name": "description", "label": T["post_pv_desc"], "a11y": T["post_pv_desc_a11y"], "hint": T["post_pv_desc_hint"]}],
                "lang": {"label": T["post_pv_lang"], "a11y": T["post_pv_lang_a11y"], "options": [{"key": "ko", "text": T["post_lang_ko"]}, {"key": "en", "text": T["post_lang_en"]}]},
                "problems": {name: T[key] for name, key in self.pages_problems.items()},
                "start": {"text": T["post_pv_start"], "a11y": T["post_pv_start_a11y"], "enabled": not busy}, "cancel": {"text": T["post_pv_cancel"], "a11y": T["post_pv_cancel_a11y"], "enabled": not busy},
                "working": T["post_res_running"] if busy else ""}

    def view(self, diag=""):
        """화면 뷰모델 — 머리·상태·안내·목록 또는 글 상세. 한 번 그리는 데 필요한 값이 모두 있다(Qt 화면은 이 값을 그리기만 한다)."""
        data, state = self.data, self.state
        sample = bool(data is not None and data.sample)
        banner = None
        if data is not None and state not in ("loading", "error"):
            if data.offline:
                banner = ("cloud_off", T["post_offline"])
            elif state == "partial":
                banner = ("alert", T["post_partial"].format(n=sum(1 for row in data.rows if row.error)))
        return {
            "title": T["post_title"], "sub": T["post_sub"], "sample": sample, "sample_tag": T["sample_tag"], "sample_tip": T["post_sample_tip"], "state": state, "mode": "detail" if self.open_id is not None else "list", "busy": self.busy,
            "import": {"text": T["post_import"], "a11y": T["post_import_a11y"], "enabled": not self.busy and not self.import_open}, "reload": {"text": T["post_reload"], "a11y": T["post_reload_a11y"], "enabled": state != "loading" and not self.busy},
            "banner": banner, "notice": {"level": self.notice[0], "text": self.notice[1]} if self.notice else None,
            "loading": {"text": T["post_loading"], "a11y": T["post_loading_a11y"]},
            "error": {"title": T["post_error_title"], "desc": T["post_error_desc"], "button": T["post_retry"], "diag": diag, "user": getattr(self.failure, "user_message", "") if self.failure else ""},
            "list": self._list_view(), "detail": self._detail_view(diag) if self.open_id is not None else None,
        }
