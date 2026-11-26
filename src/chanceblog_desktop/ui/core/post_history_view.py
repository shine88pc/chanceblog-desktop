"""발행 기록 화면(글 흐름 1b, 결정 D-649·D-650)의 상태·동작·뷰모델 — 순수 파이썬(화면 도구를 모른다). Qt 화면은 `view()` 가 만든 딕셔너리를 그리기만 한다.

**읽기뿐이다**: 이 컨트롤러에는 파일에 쓰는 일이 하나도 없다. 목록(`history-load`)과 작업 로그(`history-log`)는 따로 읽는 두 작업이고 각자 여섯 상태 틀을 가진다 — 작업 로그를 못 읽어도 목록은 그대로다.
  · 목록: 승인 이후 단계의 (글, 플랫폼) 쌍(`post_history.HistoryData`). 정렬은 **오래된 순서가 기본**이고 `최신 순서로 보기` 로 바꾼다. 한 번에 앞 50줄만 그리고 `더 보기` 로 늘린다.
    모든 글(제목·주소)은 **가린 뒤에 줄인다**. 모르는 상태는 `알 수 없음` 으로 보인다(닫힌 목록이 아니다 — D-653). `주소 복사` 는 클립보드뿐이다.
  · 작업 로그: 접어 두었다가 펼칠 때 읽는다. 서비스가 칸으로 쪼개 글자표를 통과한 줄만 주고(키·토큰 모양이 든 줄은 오지 않는다) 화면은 칸마다 다시 가린 뒤 줄인다(D-93). 지우기·고치기·내보내기·복사가 없다.
오류 코드는 접힌 진단 정보에만 있고 문장은 정해진 쉬운 말이다.
"""
from __future__ import annotations

from . import post_rules as rules
from .jobs import JobFailure
from .post_history import LOG_SOURCES, ORDERS, sort_rows
from .text import T

LOAD_KEY = "history-load"                                    # 발행 기록 목록을 읽는 작업의 이름(다른 화면의 읽기와 따로 돈다)
LOG_KEY = "history-log"                                      # 작업 로그를 읽는 작업
LIST_STATES = ("loading", "normal", "empty", "error", "partial", "offline")
LOG_STATES = ("none", "loading", "normal", "empty", "error")
PLATFORM_TEXT = {"github_pages": "post_platform_github_pages", "naver_a": "post_platform_naver_a", "naver_b": "post_platform_naver_b", "blogger_en": "hist_platform_blogger_en", "blogger_ko": "hist_platform_blogger_ko"}
LOG_SOURCE_TEXT = {"main": "hist_log_source_main", "thread": "hist_log_source_thread", "unraisable": "hist_log_source_unraisable", "slot": "hist_log_source_slot", "qt": "hist_log_source_qt"}


def platform_name(platform):
    """플랫폼 열쇠 → 이름(모르는 열쇠는 `알 수 없는 플랫폼`)."""
    return T[PLATFORM_TEXT.get(platform, "hist_platform_unknown")]


class HistoryController:
    def __init__(self, provider, runner):
        self.provider, self.runner = provider, runner
        # 목록
        self.state = "loading"
        self.data = None
        self.failure = None
        self.failed_at = None
        self.order = ORDERS[0]
        self.limit = rules.PAGE
        self.load_count = 0
        # 작업 로그
        self.log_open = False
        self.log_state = "none"
        self.log = None
        self.log_failure = None
        self.log_failed_at = None
        self.log_count = 0

    # ---- 목록 읽기(파일·폴더를 만들지 않는다) ----
    @property
    def loading(self):
        return self.runner.running(LOAD_KEY)

    @property
    def log_loading(self):
        return self.runner.running(LOG_KEY)

    def start_load(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """발행 기록 목록을 작업 스레드에서 읽는다 — 이미 읽는 중이면 None. 처음이거나 오류 뒤에는 '읽는 중' 모습이 되고, 보이는 내용이 있으면 그대로 둔 채 새 값이 오면 바꾼다."""
        job = self.runner.start(LOAD_KEY, lambda progress, cancelled: self.provider.load_history(progress, cancelled), on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.load_count += 1
        if self.data is None or self.state == "error":
            self.state = "loading"
        return job

    @staticmethod
    def _state_for(data):
        if data is None:
            return "empty"
        if data.offline:
            return "offline"
        if data.unreadable:
            return "partial"
        return "normal" if data.rows else "empty"

    def apply_loaded(self, data):
        """읽은 목록을 받는다."""
        self.data, self.failure = data, None
        self.state = self._state_for(data)
        return True

    def apply_load_failed(self, failure, when=None):
        """읽기가 실패했다 — 이전에 보이던 내용은 지우지 않는다. 상태에는 비밀 모양을 가린 글만 남긴다."""
        from .app_state import clean_failure
        self.failure, self.failed_at = clean_failure(failure), when
        self.state = "error"

    def apply_unexpected(self, error, when=None):
        """화면 스레드의 슬롯에서 예상하지 못한 예외가 났다 — 받아 둔 값을 버리고 오류 상태로(쉬운 문장 + 예외 이름만 진단 정보에)."""
        from .app_state import clean_failure
        self.data = None
        self.failure, self.failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.state = "error"

    def apply_cancelled(self):
        self.state = self._state_for(self.data) if self.data is not None else "error"

    def set_order(self, order):
        """정렬을 바꾼다(`oldest`·`newest`) → 바꿨으면 True. 목록은 다시 읽지 않는다(이미 받은 값을 다시 늘어놓는다)."""
        if order not in ORDERS:
            return False
        self.order, self.limit = order, rules.PAGE
        return True

    def toggle_order(self):
        return self.set_order(ORDERS[1] if self.order == ORDERS[0] else ORDERS[0])

    def show_more(self):
        self.limit += rules.PAGE
        return True

    def entry(self, key):
        return next((item for item in (self.data.rows if self.data is not None else ()) if item.key == key), None)

    def copy_payload(self, key):
        """`주소 복사` 를 눌렀을 때 클립보드에 쓸 주소 → (주소, 이유 열쇠). 키·토큰 모양이 든 주소는 내지 않는다. 아무 상태도 바꾸지 않는다."""
        found = self.entry(key)
        if found is None or not found.published_url:
            return None, "hist_copy_none"
        if rules.copy_blocked(found.published_url):
            return None, "hist_copy_blocked"
        return found.published_url, ""

    # ---- 작업 로그 읽기 ----
    def set_log_open(self, opened):
        """작업 로그 카드를 펴거나 접는다 → 지금 읽어야 하면(펼쳤고 아직 읽지 않았거나 지난 읽기가 실패했다) True — 부른 쪽이 `start_log` 를 부른다. 이미 읽은 로그는 접었다 펴도 다시 읽지 않는다."""
        self.log_open = bool(opened)
        return self.log_open and self.log_state in ("none", "error")

    def start_log(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """작업 로그를 작업 스레드에서 읽는다(읽기뿐) — 이미 읽는 중이면 None."""
        job = self.runner.start(LOG_KEY, lambda progress, cancelled: self.provider.load_work_log(progress, cancelled), on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.log_count += 1
        if self.log is None or self.log_state == "error":
            self.log_state = "loading"
        return job

    def apply_log(self, data):
        self.log, self.log_failure = data, None
        self.log_state = "normal" if data is not None and (data.lines or data.skipped or data.older) else "empty"
        return True

    def apply_log_failed(self, failure, when=None):
        from .app_state import clean_failure
        self.log_failure, self.log_failed_at = clean_failure(failure), when
        self.log_state = "error"

    def apply_log_unexpected(self, error, when=None):
        from .app_state import clean_failure
        self.log = None
        self.log_failure, self.log_failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.log_state = "error"

    def apply_log_cancelled(self):
        self.log_state = "normal" if self.log is not None else "none"

    # ---- 뷰모델 ----
    def _row_view(self, entry):
        title = rules.shown(entry.title, rules.TITLE_SHOWN) or T["post_untitled"]
        when = rules.when_text(entry.when) or T["hist_when_unknown"]
        meta = T["hist_row_meta"].format(platform=platform_name(entry.platform), status=rules.status_text(entry.status), when=when)
        url = rules.shown(entry.published_url, 300) if entry.published_url else ""
        copy = None
        if url:
            copy = {"text": T["hist_copy_url"], "a11y": T["hist_copy_url_a11y"].format(title=title), "enabled": not rules.copy_blocked(entry.published_url), "focus_key": f"hist:copy:{entry.key}"}
        return {"key": entry.key, "title": title, "meta": meta, "url": T["hist_row_url"].format(url=url) if url else "", "copy": copy, "a11y": T["hist_row_a11y"].format(title=title, meta=meta)}

    def _list_view(self):
        rows = sort_rows(self.data.rows if self.data is not None else (), self.order)
        shown_rows = rows[:self.limit]
        return {"count": T["hist_count"].format(n=len(rows)) if rows else "", "rows": [self._row_view(entry) for entry in shown_rows], "a11y": T["hist_list_a11y"],
                "more": {"text": T["hist_more"], "a11y": T["hist_more_a11y"]} if len(rows) > len(shown_rows) else None,
                "empty": {"title": T["hist_empty_title"], "desc": T["hist_empty_desc"], "button": T["hist_empty_button"], "a11y": T["hist_empty_button_a11y"]}}

    @staticmethod
    def _log_line(line):
        places = " < ".join(line.places)
        text = T["hist_log_line"].format(when=rules.when_text(line.at, seconds=True) or T["hist_when_unknown"], source=T[LOG_SOURCE_TEXT[line.source]] if line.source in LOG_SOURCES else T["hist_log_source_unknown"],
                                         name=rules.shown(line.name, 80), places=rules.shown(places, 240) if places else T["hist_log_places_none"])
        return rules.shown(text, 400)                         # 칸마다 가린 위에 한 줄 전체도 한 번 더 가린다(엔진이 아는 키·토큰 모양은 끝 4자도 안 보인다)

    def _log_view(self, diag=""):
        opened = self.log_open
        view = {"title": T["hist_log_title"], "sub": T["hist_log_sub"], "a11y": T["hist_log_a11y"], "open": opened, "state": "closed" if not opened else self.log_state if self.log_state != "none" else "loading",
                "toggle": {"text": T["hist_log_hide"] if opened else T["hist_log_show"], "a11y": T["hist_log_hide_a11y"] if opened else T["hist_log_show_a11y"]},
                "loading": T["hist_log_loading"], "empty": T["hist_log_empty"], "lines": [], "notes": [], "retry": None, "error": None}
        if not opened:
            return view
        if self.log_state == "error":
            view["error"] = {"text": T["hist_log_error"], "diag": diag}
            view["retry"] = {"text": T["hist_log_retry"], "a11y": T["hist_log_retry_a11y"], "enabled": not self.log_loading}
        elif self.log is not None and self.log_state in ("normal", "empty"):
            view["lines"] = [self._log_line(line) for line in self.log.lines]
            view["notes"] = ([T["hist_log_count"].format(n=len(self.log.lines))] if self.log.lines else []) + ([T["hist_log_skipped"].format(n=self.log.skipped)] if self.log.skipped else []) \
                + ([T["hist_log_older"].format(n=self.log.older)] if self.log.older else [])
            view["retry"] = {"text": T["hist_log_retry"], "a11y": T["hist_log_retry_a11y"], "enabled": not self.log_loading}
        return view

    def view(self, diag="", log_diag=""):
        """화면 뷰모델 — 머리·상태·안내·목록·작업 로그 카드. 한 번 그리는 데 필요한 값이 모두 있다(Qt 화면은 이 값을 그리기만 한다)."""
        data, state = self.data, self.state
        sample = bool(data is not None and data.sample)
        banner = None
        if data is not None and state not in ("loading", "error"):
            if data.offline:
                banner = ("cloud_off", T["hist_offline"])
            elif data.unreadable:
                banner = ("alert", T["hist_partial"].format(n=data.unreadable))
        listing = data is not None and bool(data.rows) and state not in ("loading", "error")
        newest = self.order == ORDERS[1]
        return {
            "title": T["hist_title"], "sub": T["hist_sub"], "sample": sample, "sample_tag": T["sample_tag"], "sample_tip": T["hist_sample_tip"], "state": state,
            "reload": {"text": T["hist_reload"], "a11y": T["hist_reload_a11y"], "enabled": state != "loading" and not self.loading},
            "order": {"current": self.order, "visible": listing, "text": T["hist_order_to_oldest"] if newest else T["hist_order_to_newest"], "now": T["hist_order_now_newest"] if newest else T["hist_order_now_oldest"],
                      "a11y": T["hist_order_a11y_newest"] if newest else T["hist_order_a11y_oldest"]},
            "banner": banner, "loading": {"text": T["hist_loading"], "a11y": T["hist_loading_a11y"]},
            "error": {"title": T["hist_error_title"], "desc": T["hist_error_desc"], "button": T["hist_retry"], "diag": diag, "user": getattr(self.failure, "user_message", "") if self.failure else ""},
            "list": self._list_view(), "log": self._log_view(log_diag),
        }


__all__ = ["HistoryController", "LIST_STATES", "LOAD_KEY", "LOG_KEY", "LOG_STATES", "platform_name"]
