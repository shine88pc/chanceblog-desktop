"""백업·복원 카드(설정 화면)의 상태·동작·뷰모델 — 순수 파이썬(화면 도구·서비스 층을 모른다). Qt 화면은 여기서 만든 딕셔너리를 그리기만 한다: 어느 단추를 켤지·어떤 문장을 보일지·진행이 어디까지인지는 여기서 정한다(BACKUPUI, D-391).

규칙(모두 시험이 지킨다):
  · **쓰기는 사용자가 단추를 눌렀을 때만**: 목록 읽기(설정 화면 열기·다시 읽기)는 파일을 바꾸지 않는다. 쓰는 일은 `start_create`(지금 백업)와 `start_restore`(복원 — **확인(`confirmed=True`)이 먼저**) 둘뿐이고 한 번에 하나다(돌고 있으면 두 번째는 아무 일도 하지 않는다).
  · 쓰는 공급자(`BackupsWriter`)가 아닌 공급자(읽기 전용)에서는 단추가 모두 꺼지고 까닭이 보인다. 깨진 백업(`broken`)은 복원 단추가 꺼진다.
  · 실패 문장은 종류별로 정해진 쉬운 말뿐이다 — 서비스 오류의 세부·경로·입력한 값은 화면 글에 없다(코드는 진단 정보에만). 키 모양이 발견된 위치는 '어느 칸·몇 번째 줄·유형' 글(서비스가 만든 고정 이름)만 보이고 키 글자는 어디에도 없다.
  · 모든 줄에 `Credential 제외됨` 표시가 있고 상태(완료·부분·깨짐)는 색이 아니라 글자로도 말한다. 안전 사본('복원 직전 사본')도 같은 줄이고 같은 방법으로 복원한다.
  · 진행은 작업 스레드가 알려 주는 값(0에서 1 사이 비율과 짧은 글)뿐이다 — 화면은 멈추지 않는다.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .backups import BackupFailure, BackupsWriter
from .jobs import JobFailure
from .text import T, display_text

WRITE_KEY = "backups-write"                              # 백업·복원 쓰기 작업의 이름 — 한 번에 하나(중복 클릭은 아무 일도 하지 않는다)
READ_KEY = "backups-load"                                # 목록 읽기 작업의 이름 — 다른 화면의 읽기와 따로 돈다
KST = timezone(timedelta(hours=9), "KST")
STATE_TONE = {"complete": "ok", "partial": "warning", "broken": "danger"}
KIND_TONE = {"backup": "info", "safety": "muted"}
UNREADABLE = frozenset({"STORE_CORRUPT", "TOPIC_STORE_CORRUPT", "TOPIC_FILE_INVALID", "SETTINGS_INVALID", "CONTENT_INVALID", "FILE_WRITE_FAILED"})
NEWER = frozenset({"STORE_VERSION_UNSUPPORTED", "TOPIC_STORE_VERSION_UNSUPPORTED"})
BUSY = frozenset({"STORE_LOCKED", "TOPIC_STORE_LOCKED"})
PENDING = frozenset({"STORE_RECOVERY_PENDING", "TOPIC_STORE_RECOVERY_PENDING"})
# 파일 하나의 '담긴 것' 글 — (칸 이름, 문구 열쇠) 순서. 서비스가 모르는 칸은 보이지 않는다(목록 파일에는 그대로 있다).
CONTENT_PARTS = {"chanceblog.db": (("projects", "backup_item_projects"), ("drafts", "backup_item_drafts"), ("candidates", "backup_item_candidates")),
                 "topic_engine.db": (("candidates", "backup_item_engine"),), "channel_profiles.json": (("count", "backup_item_profiles"),), "seeds.json": (("count", "backup_item_seeds"),),
                 "calendar.json": (("count", "backup_item_calendar"),), "settings.json": ()}


def _shown(value, limit=300):
    return display_text(value, limit)                                          # 화면에 나가는 외부 글은 가린 뒤에 줄인다 — PCSEC1 H1 의 한 지점(`display_text`)을 지난다(이 파일이 `security.mask` 를 직접 부르지 않는다)


def when_text(stamp):
    """UTC `YYYY-MM-DDTHH:MM:SSZ` → 한국 시간 `YYYY-MM-DD HH:MM`. 모르거나 모양이 틀리면 ''."""
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


def size_text(size):
    """바이트 수 → `12 KB`·`3.4 MB` 같은 짧은 글(숫자가 아니거나 음수면 ''). 반올림은 한 곳이다."""
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB" if size >= 100 * 1024 else f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB" if size < 1024 ** 3 else f"{size / 1024 ** 3:.1f} GB"


def reason_text(code):
    """담지 못한 이유의 오류 코드 → 짧은 쉬운 말(모르는 코드는 '담지 못했어요' — 영문 코드는 보이지 않는다)."""
    if code in UNREADABLE:
        return T["backup_why_unreadable"]
    if code in NEWER:
        return T["backup_why_newer"]
    if code in BUSY:
        return T["backup_why_busy"]
    if code in PENDING:
        return T["backup_why_pending"]
    return T["backup_why_other"]


def count_of(info, name):
    for key, number in info.items:
        if key == name:
            return number if isinstance(number, int) and not isinstance(number, bool) and number >= 0 else None
    return None


def file_parts(info):
    """담긴 파일 하나의 '담긴 것' 조각들 — `글 12개` 같은 글. 설정은 늘 `설정` 이 있고 옛 네이버 프로필·연결한 폴더가 있으면 그 말을 더한다."""
    parts = []
    for key, text_key in CONTENT_PARTS.get(info.name, ()):
        number = count_of(info, key)
        if number is not None:
            parts.append(T[text_key].format(n=f"{number:,}"))
    if info.name == "settings.json":
        parts.append(T["backup_item_settings"])
        profiles = count_of(info, "profiles")
        if profiles:
            parts.append(T["backup_item_naver"].format(n=profiles))
        if count_of(info, "repo"):
            parts.append(T["backup_item_repo"])
    return parts


def contents_text(files):
    parts = [part for info in files if info.state in ("saved", "restored") for part in file_parts(info)]
    return " · ".join(parts)


def labelled(files, states):
    """상태가 `states` 중 하나인 파일들의 쉬운 이름 목록 — 가린 이름을 쓴다."""
    return [_shown(info.label, 40) for info in files if info.state in states]


def skipped_text(files):
    return " · ".join(f"{_shown(info.label, 40)}({reason_text(info.reason)})" for info in files if info.state == "skipped")


def kind_of(row):
    """줄의 종류 — 백업 · 복원 직전 사본(모르는 종류는 백업으로)."""
    return row.kind if row.kind in ("backup", "safety") else "backup"


def status_of(row):
    """줄의 상태 — 완료 · 부분 · 깨짐(모르는 상태는 읽을 수 없는 것으로 보고 복원하지 않는다)."""
    return row.status if row.status in ("complete", "partial", "broken") else "broken"


def row_title(row):
    when, kind = when_text(row.created_at), kind_of(row)
    return T["backup_row_" + kind].format(when=when) if when else T["backup_row_unknown"].format(kind=T["backup_kind_" + kind])


def broken_text(problem):
    reason = T.get("backup_broken_" + problem, T["backup_broken_other"])
    return f"{reason} — {T['backup_broken_tail']}"


class BackupController:
    def __init__(self, provider, runner):
        self.provider, self.runner = provider, runner
        self.data = None                                     # 읽은 목록(`BackupsData`)
        self.state = "loading"                               # loading · normal · empty · error
        self.failure = None
        self.failed_at = None
        self.notice = None                                   # (수준, 글, 줄들) — 마지막 동작의 결과
        self.pending = None                                  # 돌고 있는 쓰기: {"kind": "create"|"restore", "name"}
        self.progress = (0.0, "")                            # 돌고 있는 일의 (비율, 글)
        self.reload_wanted = False                           # 쓰기가 끝났으니 목록을 다시 읽어야 한다(읽기 작업은 화면이 시작한다)
        self.focus_after = False                             # 다시 그린 뒤 '지금 백업' 단추에 포커스를 돌려준다
        self.load_count = 0
        self.write_count = 0

    # ---- 상태 ----
    @property
    def writable(self):
        return isinstance(self.provider, BackupsWriter) and bool(getattr(self.provider, "can_write", False))

    @property
    def busy(self):
        """쓰는 중이다(백업·복원) — 단추가 꺼진다."""
        return self.runner.running(WRITE_KEY)

    @property
    def loading(self):
        return self.runner.running(READ_KEY)

    def row(self, name):
        data = self.data
        return next((item for item in data.rows if item.name == name), None) if data is not None else None

    # ---- 읽기(작업 스레드) ----
    def start_load(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """목록을 작업 스레드에서 읽는다 — 파일을 바꾸지 않는다. 이미 읽는 중이거나 쓰는 중이면(쓰는 도중의 폴더를 읽어 낡은 목록이 남지 않게) None."""
        if self.busy:
            return None
        job = self.runner.start(READ_KEY, self.provider.load_backups, on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.load_count += 1
        if self.data is None or self.state == "error":
            self.state = "loading"
        return job

    def apply_loaded(self, data):
        self.data, self.failure, self.failed_at = data, None, None
        self.state = "normal" if data is not None and data.rows else "empty"

    def apply_load_failed(self, failure, when=None):
        """읽기가 실패했다 — 이전에 보이던 목록은 지우지 않는다. 상태에는 **비밀 모양을 가린 글**만 남긴다."""
        self.failure = JobFailure(_shown(getattr(failure, "user_message", "") or T["job_failed"], 200), code=_shown(getattr(failure, "code", "") or "", 80))
        self.failed_at = when
        self.state = "error"

    def apply_load_cancelled(self):
        self.state = "normal" if self.data is not None and self.data.rows else ("empty" if self.data is not None else "loading")

    # ---- 쓰기(사용자가 눌렀을 때만) ----
    def _start(self, kind, name, work, callbacks):
        job = self.runner.start(WRITE_KEY, work, **callbacks)
        if job is None:
            return "busy", None
        self.pending = {"kind": kind, "name": name}
        self.progress = (0.0, "")
        self.notice = None
        self.reload_wanted = False
        self.write_count += 1
        return "started", job

    def start_create(self, **callbacks):
        """지금 백업 — `(상태, 작업)`: `("unavailable", None)`(읽기 전용 공급자) · `("busy", None)` · `("started", 작업)`."""
        if not self.writable:
            return "unavailable", None
        if self.busy:
            return "busy", None
        writer = self.provider
        return self._start("create", "", lambda progress, cancelled: writer.create_backup(progress, cancelled), callbacks)

    def can_restore(self, name):
        row = self.row(name)
        return bool(self.writable and not self.busy and row is not None and status_of(row) != "broken")

    def restore_dialog(self, name):
        """복원 확인창의 글 — 무엇이 바뀌는지·안전 사본 위치·되돌리는 법(처음 포커스는 취소). 복원할 수 없는 줄이면 None."""
        row = self.row(name)
        if row is None or not self.can_restore(name):
            return None
        what = "·".join(labelled(row.files, ("saved",))) or T["backup_item_nothing"]
        when = when_text(row.created_at) or T["backup_restore_unknown_when"]
        body = T["backup_restore_body"].format(what=what, when=when, where=self.location_text())
        if status_of(row) == "partial":
            body += T["backup_restore_partial"]
        return {"title": T["backup_restore_title"], "body": body, "ok": T["backup_restore_ok"], "cancel": T["backup_restore_cancel"]}

    def start_restore(self, name, *, confirmed, **callbacks):
        """복원 — **확인(`confirmed is True`)이 먼저**다. `(상태, 작업)`: `("unconfirmed", None)` · `("unavailable", None)`(없는 줄·깨진 백업·읽기 전용) · `("busy", None)` · `("started", 작업)`."""
        if confirmed is not True:
            return "unconfirmed", None
        if self.busy:
            return "busy", None
        if not self.can_restore(name):
            return "unavailable", None
        writer = self.provider
        return self._start("restore", name, lambda progress, cancelled: writer.restore_backup(name, progress, cancelled), callbacks)

    # ---- 멈춘 복원(D-463) ----
    @property
    def interrupted(self):
        """복원이 중간에 멈춘 흔적(`InterruptedData`) — 없으면 None."""
        data = self.data
        return getattr(data, "interrupted", None) if data is not None else None

    def can_revert(self):
        pending = self.interrupted
        return bool(self.writable and not self.busy and pending is not None and pending.can_revert)

    def revert_dialog(self):
        """`안전 사본으로 되돌리기` 확인창의 글 — 무엇이 바뀌는지·안전 사본 위치(처음 포커스는 취소). 되돌릴 수 없으면 None."""
        if not self.can_revert():
            return None
        row = self.row(self.interrupted.safety)
        when = (when_text(row.created_at) if row is not None else "") or T["backup_restore_unknown_when"]
        return {"title": T["backup_revert_title"], "body": T["backup_revert_body"].format(when=when, where=self.location_text()), "ok": T["backup_revert_ok"], "cancel": T["backup_restore_cancel"]}

    def start_revert(self, *, confirmed, **callbacks):
        """멈춘 복원을 안전 사본으로 되돌린다 — 복원처럼 **확인(`confirmed is True`)이 먼저**다. `(상태, 작업)`: `("unconfirmed", None)` · `("busy", None)` · `("unavailable", None)`(흔적·안전 사본 없음·읽기 전용) · `("started", 작업)`."""
        if confirmed is not True:
            return "unconfirmed", None
        if self.busy:
            return "busy", None
        if not self.can_revert():
            return "unavailable", None
        writer, name = self.provider, self.interrupted.safety
        return self._start("restore", name, lambda progress, cancelled: writer.revert_interrupted(progress, cancelled), callbacks)

    def apply_progress(self, fraction, text=""):
        """작업 스레드가 알려 준 진행(시그널로 화면 스레드에 온다) — 0에서 1 사이로 자르고 글은 가린 뒤 줄인다."""
        try:
            number = float(fraction)
        except (TypeError, ValueError):
            number = 0.0
        if not math.isfinite(number):
            number = 0.0                                         # 숫자가 아닌 값(NaN·무한대)은 0 으로 — 막대가 깨지지 않게
        self.progress = (min(max(number, 0.0), 1.0), _shown(text, 80) if isinstance(text, str) else "")

    def apply_write_ok(self, result):
        """백업·복원이 끝났다 — 결과 안내를 정하고 목록을 다시 읽게 한다."""
        self.pending = None
        files = tuple(getattr(result, "files", ()))
        if getattr(result, "action", "") == "restored":
            if result.status == "partial":
                text = T["backup_ok_restored_partial"]
            else:
                text = T["backup_ok_restored" if getattr(result, "safety", "") else "backup_ok_restored_nosafety"]
            self.notice = ("warning" if result.status == "partial" else "ok", text, tuple(_shown(note, 200) for note in getattr(result, "notes", ())))
        else:
            when = when_text(getattr(result, "created_at", ""))
            if result.status == "partial":
                self.notice = ("warning", T["backup_ok_partial"].format(text=skipped_text(files) or T["backup_why_other"]), ())
            else:
                self.notice = ("ok", T["backup_ok_created"].format(when=when or T["backup_restore_unknown_when"]), ())
        self.reload_wanted = True
        self.focus_after = True

    def apply_write_failed(self, failure):
        """쓰기가 실패했다 — 문장은 종류별로 정해진 쉬운 말뿐이다. 키 모양이 발견됐으면 위치(유형 포함)를 줄로 붙인다. 되돌리지 못한 것이 있으면 그 이름을 붙인다."""
        work, self.pending = self.pending or {"kind": "", "name": ""}, None
        kind = failure.kind if isinstance(failure, BackupFailure) else "other"
        lines, left = (), ()
        if isinstance(failure, BackupFailure):
            left = tuple(_shown(line, 240) for line in failure.notes) if kind == "restore" else ()
            reason = (T["backup_restore_reason_" + failure.reason],) if kind == "restore" and failure.reason in ("disk", "io", "corrupt", "busy", "other") else ()
            lines = tuple(_shown(line, 240) for line in failure.summary) if kind == "blocked" else reason + left
        text = T["backup_fail_restore_left" if kind == "restore" and left else "backup_fail_" + kind] if kind in ("blocked", "nothing", "busy", "invalid", "newer", "disk", "io", "restore", "other") else T["backup_fail_other"]
        self.notice = ("error", text, lines)
        self.reload_wanted = kind in ("invalid", "restore", "other") or work.get("kind") == "restore"
        self.focus_after = True
        return kind

    def apply_unexpected(self, error):
        """화면 스레드의 슬롯에서 예상하지 못한 예외가 났다 — 쉬운 문장만(예외 이름도 화면에 두지 않는다)."""
        self.pending = None
        self.notice = ("error", T["backup_fail_other"], ())
        return type(error).__name__

    # ---- 뷰모델 ----
    def location_text(self):
        data = self.data
        return _shown(data.location, 260) if data is not None and data.location else ""

    def create_vm(self):
        reason = ""
        if not self.writable:
            reason = T["backup_no_write"]
        elif self.busy:
            reason = T["backup_busy_restore" if (self.pending or {}).get("kind") == "restore" else "backup_busy_create"]
        return {"text": T["backup_now"], "enabled": not reason, "reason": reason, "a11y": T["backup_now_a11y"]}

    def restore_vm(self, row, title):
        reason = ""
        if not self.writable:
            reason = T["backup_no_write"]
        elif self.busy:
            reason = T["backup_busy"]
        elif status_of(row) == "broken":
            reason = T["backup_restore_broken"]
        return {"text": T["backup_restore"], "enabled": not reason, "reason": reason, "a11y": T["backup_restore_a11y"].format(title=title), "name": row.name}

    def row_vm(self, row):
        title, state = row_title(row), status_of(row)
        kind = {"text": T["backup_kind_" + kind_of(row)], "tone": KIND_TONE[kind_of(row)]}
        status = {"text": T["backup_status_" + state], "tone": STATE_TONE[state]}
        size = size_text(row.size)
        lines = []
        if state == "broken":
            lines.append(broken_text(row.problem))
        contents = contents_text(row.files)
        if contents:
            lines.append(T["backup_contents"].format(text=contents))
        skipped = skipped_text(row.files)
        if skipped:
            lines.append(T["backup_skipped"].format(text=skipped))
        missing = " · ".join(labelled(row.files, ("missing",)))
        if missing and state != "broken":
            lines.append(T["backup_missing"].format(text=missing))
        meta = [T["backup_size"].format(size=size)] if size and state != "broken" else []
        credential = {"text": T["backup_credential_badge"], "a11y": T["backup_credential_a11y"]} if state != "broken" else None
        spoken = [title, kind["text"], status["text"]] + meta + ([T["backup_credential_a11y"]] if credential else [])
        return {"name": row.name, "title": title, "kind": kind, "status": status, "meta": " · ".join(meta), "lines": lines, "credential": credential, "restore": self.restore_vm(row, title),
                "a11y": ", ".join(spoken), "key": row.name}

    def interrupted_vm(self):
        """멈춘 복원의 안내 — 쉬운 문장(+ 시작한 때)과 `안전 사본으로 되돌리기` 단추(되돌릴 안전 사본이 있을 때만). 흔적이 없으면 None."""
        pending = self.interrupted
        if pending is None:
            return None
        reason = T["backup_no_write"] if not self.writable else (T["backup_busy"] if self.busy else "")
        revert = {"text": T["backup_revert"], "enabled": not reason, "reason": reason, "a11y": T["backup_revert_a11y"]} if pending.can_revert else None
        when = when_text(pending.started_at)
        return {"level": "warning", "text": T["backup_interrupted_can" if pending.can_revert else "backup_interrupted_cannot"], "lines": [T["backup_interrupted_when"].format(when=when)] if when else [], "revert": revert}

    def progress_vm(self):
        if self.pending is None:
            return None
        fraction, step = self.progress
        percent = int(round(fraction * 100))
        head = T["backup_progress_restore" if self.pending["kind"] == "restore" else "backup_progress_create"].format(percent=percent)
        text = f"{head} — {step}" if step else head
        return {"fraction": fraction, "percent": percent, "text": text, "a11y": T["backup_progress_a11y"].format(text=text)}

    def view(self, diag=""):
        data, state = self.data, self.state
        rows = [self.row_vm(row) for row in data.rows] if data is not None else []
        sample = bool(data is not None and data.sample)
        keep = data.keep if data is not None else 10
        notice = {"level": self.notice[0], "text": self.notice[1], "lines": list(self.notice[2])} if self.notice else None
        from ...security.backup_note import EXCLUDED                          # 담지 않는 것의 이름과 이유 — 백업 목록 파일에 적히는 글과 같다
        return {
            "title": T["backup_title"], "desc": T["backup_desc"], "sample": sample, "sample_tag": T["backup_sample_tag"], "sample_note": T["backup_sample_note"] if sample else "", "state": state,
            "writable": self.writable, "busy": self.busy, "create": self.create_vm(), "progress": self.progress_vm(), "notice": notice, "interrupted": self.interrupted_vm(),
            "location": T["backup_location"].format(path=self.location_text()) if self.location_text() else "", "copy_tip": T["backup_copy_tip"], "keep": T["backup_keep"].format(n=keep),
            "credential_line": T["backup_credential_line"],
            "excluded": {"show": T["backup_excluded_show"], "hide": T["backup_excluded_hide"], "intro": T["backup_excluded_intro"], "lines": [f"{name} — {reason}" for name, reason in EXCLUDED]},
            "list_title": T["backup_list_title"], "list_note": T["backup_list_note"], "rows": rows,
            "loading": {"text": T["backup_loading"], "a11y": T["backup_loading_a11y"]},
            "empty": {"title": T["backup_empty_title"], "desc": T["backup_empty_desc"]},
            "error": {"title": T["backup_error_title"], "desc": T["backup_error_desc"], "button": T["backup_reload"], "diag": diag, "user": getattr(self.failure, "user_message", "") if self.failure else ""},
            "a11y": T["backup_a11y"].format(n=len(rows)),
        }


__all__ = ["BackupController", "READ_KEY", "WRITE_KEY", "contents_text", "size_text", "when_text"]
