"""사진 정리 창의 글자 읽기 화면 규칙(결정 D-513, 설계서 2-2·2-3·2-4·2-5·2-9) — 글자 읽기 컨트롤러(`photo_ocr_view.OcrBoard`) 위에서 화면이 부르는 일과, 사진 한 줄에 보일 글자 읽기 칸의 뷰모델을 정한다.
PySide6·파일·네트워크·프로세스·시계를 모른다(그래서 CI 에서 시험한다) — 시간이 필요한 곳은 호출하는 쪽이 지금 시각(초)을 준다. 읽는 일 자체(작업 스레드·작업자)는 `ui/qt/ocr_runner.py` 가 하고, 이 파일은 그 앞뒤의 규칙만 한다.

**사진 줄에 글자 읽기 칸이 있느냐는 `view` 가 정한다** — 컨트롤러가 없으면(도구가 없거나 `LOCAL_OCR` 꺼짐) 이 파일의 `OcrPanel` 도 만들어지지 않고 화면은 지금과 한 글자도 다르지 않다. 컨트롤러가 있어도 읽을 수 없는 상태(꺼짐·이번 실행에서 끔)이고 보일 것(읽은 글·실패·멈춤)이 없으면 `view` 가 `None` 을 돌려줘 그 줄에는 칸이 없다.
이 파일이 더하는 규칙은 둘이다: ① **줄 확인·고침·빼기·합치기·모두 맞아요가 사진의 '확인했어요' 를 풀면 줄에 한 번 안내를 남긴다**(글 칸을 고칠 때와 같은 `pho_unconfirmed_note` — 컨트롤러는 안내를 지우기만 한다) ② **받아들여지지 않은 일의 이유 한 줄**(`error` — 고친 글이 입구 검사에 걸림·비운 칸·이은 글이 너무 김)을 다음 일이 시작될 때까지 들고 있는다.
읽은 글은 이 파일의 어떤 상태·오류·문구에도 되풀이되지 않는다 — 줄 글은 뷰모델의 `items` 에만 있고(목록 줄이 그린다) 확신도 숫자는 아예 없다(설계 2-9 (5): 확신도 0.9 대의 오독이 있어 숫자가 믿음을 만들 수 있다). 사진 경로·파일 이름은 이 파일에 없다.
"""
from __future__ import annotations

from ...content import photo_ocr
from . import photo_ocr_view as pov
from .text import T

ERROR_TEXT = {"OCR_FAILED": "pho_ocr_err_failed", "OCR_TIMEOUT": "pho_ocr_err_timeout", "OCR_TOO_BIG": "pho_ocr_err_toobig", "OCR_ADDON_INVALID": "pho_ocr_err_addon",
              "OCR_BLOCKED": "pho_ocr_err_blocked", "OCR_UNEXPECTED": "pho_ocr_err_unexpected", "OCR_UNAVAILABLE": "pho_ocr_err_unavailable"}      # 오류 카탈로그 코드 -> 고정 문장 키(여섯은 카탈로그의 사용자 문장과 같다)
SELF_EXPLAINING = frozenset({"OCR_UNEXPECTED", "OCR_UNAVAILABLE"})                # 문장이 이미 '이번 실행에서는 끌게요·쓸 수 없어요' 라고 말한다 — 끈 뒤 한 줄(`pho_ocr_off_note`)을 또 붙이지 않는다
WORKER_GONE = frozenset({"died", "timeout", "proto", "net_blocked", "blocked", "addon_invalid", "unavailable", "cancelled"})    # 이 오류 뒤에는 작업자가 없다 — 다음 읽기는 준비부터 다시 한다(`decode`·`engine`·`too_big` 은 작업자가 살아 있다)
NO_CONFIRM = "pho_unconfirmed_note"                                                # 사진의 '확인했어요' 가 풀렸을 때의 안내(글 칸을 고칠 때와 같은 문구)


class OcrPanel:
    """사진 정리 창 하나(= 사진 목록 하나)의 글자 읽기 화면 규칙 — 만들면 컨트롤러(`OcrBoard`)를 감싼다. 모든 일은 값을 받아 상태를 바꾸고 짧은 상태 이름을 돌려준다(컨트롤러의 이름 그대로). 저장하지 않는다."""

    def __init__(self, ocr):
        self.ocr = ocr
        self.error = None                  # (사진 번호, 줄 위치, 고정 문장) — 방금 한 일이 받아들여지지 않은 이유(다음 일이 시작되면 지운다)
        self._asked = None                 # (사진 번호, 그때의 읽은 줄들) — '읽은 글 모두 맞아요' 질문을 띄운 순간의 줄(질문이 낡았는지 보는 기준)

    @property
    def board(self):
        return self.ocr.board

    @property
    def available(self):
        return self.ocr.available

    def intro(self):
        """사진 정리 창 위의 안내 — 글자 읽기를 쓸 수 있을 때만(아니면 빈 글이라 안내도 없다)."""
        return T["pho_ocr_intro"] if self.ocr.available else ""

    def _file_ok(self, photo_id):
        """사진 파일이 지금 쓸 만한가(없음·링크·내려받지 않음·지원하지 않는 형식 …이면 아니다) — 아니면 읽기 단추를 보이지 않는다(설계 2-3 '사진 파일 문제'). 이미 읽은 글은 그대로 보인다."""
        state = self.board.states.get(photo_id)
        return state is not None and state.ok

    # ---- 읽기·취소 ----
    def read(self, photo_id, size=pov.SIZE_NORMAL):
        """`글자 읽기`·`다시 읽기`·`더 크게 다시 읽기` → `queued` · `ask_replace`(이미 읽은 글이 있다 — 확인 줄이 뜬다) · `busy` · `unavailable` · `refused`."""
        self.error = None
        if not self._file_ok(photo_id):
            return "refused"                                                       # 파일이 없거나 쓸 수 없는 사진은 읽지 않는다(단추도 안 보이지만 직접 불러도 같다)
        return self.ocr.request_read(photo_id, size)

    def confirm_reread(self, photo_id):
        self.error = None
        status = self.ocr.confirm_reread(photo_id)
        if status == "queued":
            self._close_all_right(photo_id)                                        # 다시 읽기를 시작했다 — 지금 보는 줄에 대한 '모두 맞아요' 질문은 새로 읽은 줄의 것이 아니다(읽은 글이 있는 사진의 읽기는 이 길로만 시작한다)
        return status

    def cancel_reread(self, photo_id=None):
        self.ocr.cancel_reread()

    def cancel(self, photo_id, now):
        """`취소` → `cancelled`(기다리던 것을 뺐다) · `cancelling`(읽는 중인 것을 취소했다) · `refused`(취소할 것이 없다)."""
        return self.ocr.cancel(photo_id, now)

    def escape(self, photo_id, now):
        """Esc — 이 사진의 확인 줄(모두 맞아요·다시 읽기)이 떠 있으면 그것을 그만두고, 없으면 기다리는·읽는 중인 요청을 취소한다 → 한 일의 이름(`all_right`·`reread`·`cancel`), 할 일이 없으면 빈 글."""
        ocr = self.ocr
        if ocr.all_right_asked[0] == photo_id:
            self._close_all_right()
            return "all_right"
        if ocr.reread_asked is not None and ocr.reread_asked[0] == photo_id:
            ocr.cancel_reread()
            return "reread"
        if ocr.is_busy(photo_id):
            ocr.cancel(photo_id, now)
            return "cancel"
        return ""

    def ready(self, now):
        """작업자가 준비됐다(`ready`) — 준비 중이던 요청이 읽는 중이 된다."""
        self.ocr.mark_ready(now)

    def finish(self, token, outcome, now):
        """작업이 끝났다(`OcrOutcome`) → 컨트롤러의 결과 이름(`applied`·`late`·`failed`·`disabled`). 새로 읽은 글이 사진의 '확인했어요' 를 풀었으면 줄에 안내를 남긴다. 작업자가 사라진 오류면 다음 읽기는 준비부터 한다. 취소를 모르는 채 온 `cancelled` 는 `died` 로 센다(꺼 버리지 않는다)."""
        ocr = self.ocr
        job = ocr.active
        photo_id = job.photo_id if job is not None and job.token == token else ""
        was = self._confirmed(photo_id)
        if outcome.error:
            status = ocr.on_error(token, "died" if outcome.error == "cancelled" else outcome.error, now)
            if outcome.error in WORKER_GONE:
                ocr.worker_stopped()
        else:
            status = ocr.on_result(token, outcome.lines, now)
        if status == "applied":
            self._note_loss(photo_id, was)
        return status

    # ---- 줄 ----
    def _confirmed(self, photo_id):
        photo = self.board.photo(photo_id) if photo_id else None
        return photo is not None and photo.confirmed_by_user

    def _note_loss(self, photo_id, was):
        """사진의 '확인했어요' 가 이 일로 풀렸으면 줄에 한 번 안내를 남긴다(`pho_unconfirmed_note`)."""
        if was and photo_id and self.board.photo(photo_id) is not None and not self._confirmed(photo_id):
            self.board.notes[photo_id] = T[NO_CONFIRM]

    def _changed(self, photo_id, call):
        was = self._confirmed(photo_id)
        self.error = None
        status = call()
        self._note_loss(photo_id, was)
        return status

    def confirm_line(self, photo_id, index, on=True):
        """줄 하나를 '맞아요' 로 표시하거나 푼다 → 컨트롤러의 이름(`ok`·`unchanged`·`busy`·`refused`)."""
        return self._changed(photo_id, lambda: self.ocr.confirm_line(photo_id, index, on))

    def edit_line(self, photo_id, index, text):
        """줄의 글을 고친다 → `ok`·`unchanged`·`invalid`(이유는 `error`)·`busy`·`refused`. 칸을 비우면 같은 입구 검사에 보내지 않고 '비워 둘 수 없어요(빼려면 빼기)' 로 거절한다 — 줄은 그대로다."""
        if not isinstance(text, str) or not " ".join(text.split()):
            self.error = (photo_id, index, T["pho_ocr_line_empty"])
            return "invalid"
        status = self._changed(photo_id, lambda: self.ocr.edit_line(photo_id, index, text))
        if status == "invalid":
            self.error = (photo_id, index, self.ocr.line_error(photo_id, index))
        return status

    def remove_line(self, photo_id, index):
        """줄 하나를 뺀다(한 번 되돌릴 수 있다) → `ok`·`busy`·`refused`."""
        return self._changed(photo_id, lambda: self.ocr.remove_line(photo_id, index))

    def undo_remove(self, photo_id=None):
        """방금 뺀 줄을 되돌린다 → `ok`·`refused`(그 뒤에 목록이 바뀌었거나 뺀 줄이 없다). 어느 사진인지는 컨트롤러가 안다(`photo_id` 는 부르는 모양을 맞추려고 받을 뿐이다)."""
        undo = self.ocr.undo_line
        return self._changed(undo[0] if undo is not None else "", self.ocr.undo_remove_line)

    def merge_line(self, photo_id, index):
        """줄과 바로 아래 줄을 이어 새 확인 전 줄로 만든다 → `ok`·`invalid`(이유는 `error`)·`busy`·`refused`."""
        status = self._changed(photo_id, lambda: self.ocr.merge_line(photo_id, index))
        if status == "invalid":
            self.error = (photo_id, index, self.ocr.line_error(photo_id, index))
        return status

    def ask_all_right(self, photo_id):
        """'읽은 글 모두 맞아요' 1단계 → `ask`·`none`·`busy`·`refused`(바꾸지 않는다). 질문을 띄운 순간의 읽은 줄을 기억해 둔다."""
        self.error = None
        status = self.ocr.ask_all_right(photo_id)
        if status == "ask":
            self._asked = (photo_id, self.ocr.lines(photo_id))
        return status

    def all_right(self, photo_id):
        """2단계 — 확인 줄에서 눌렀을 때만 이 사진의 확인 전 줄을 모두 '맞아요' 로 표시한다. 질문을 띄운 뒤 읽은 줄이 달라졌으면(낡은 질문) 질문을 거두고 이 '네' 는 받지 않는다(`refused`)."""
        self._drop_stale_ask()
        return self._changed(photo_id, lambda: self.ocr.all_right(photo_id))

    def cancel_all_right(self, photo_id=None):
        self._close_all_right()

    def _close_all_right(self, photo_id=None):
        """`모두 맞아요` 질문을 거둔다 — `photo_id` 를 주면 그 사진의 질문일 때만."""
        if photo_id is None or self.ocr.all_right_asked[0] == photo_id:
            self.ocr.cancel_all_right()
            self._asked = None

    def _drop_stale_ask(self):
        """질문을 띄운 뒤 그 사진의 읽은 줄이 달라졌으면(다시 읽어 새로 온 줄 …) 질문을 거둔다 — 질문은 '그때 본 줄' 에 대한 것이라 낡은 '네' 가 보지도 못한 줄까지 확인하지 않는다(컨트롤러는 새 결과가 와도 질문을 안 지운다 — 독립 검증 S SP-1)."""
        photo_id = self.ocr.all_right_asked[0]
        if photo_id is None:
            self._asked = None
            return
        now = (photo_id, self.ocr.lines(photo_id))
        if self._asked is None:
            self._asked = now                                                      # 이 화면 규칙을 거치지 않고 띄운 질문 — 지금 줄을 기준으로 삼는다
        elif self._asked != now:
            self._close_all_right()

    def clear_error(self, photo_id=None):
        """받아들여지지 않은 일의 이유 문장을 지운다(고치기를 그만둘 때)."""
        self.error = None
        return "ok"

    # ---- 뷰모델 ----
    def status(self, photo_id, now):
        """상태 줄 `{"state", "text", "tone", "a11y"}` — 읽는 중의 글은 몇 초째인지가 매초 바뀐다. 접근 이름에는 초를 넣지 않는다(읽는 프로그램이 매초 읽지 않게 — 상태가 바뀔 때만 이름이 바뀐다)."""
        ocr = self.ocr
        photo = self.board.photo(photo_id)
        state = ocr.state_of(photo_id)
        job = ocr.active if ocr.active is not None and ocr.active.photo_id == photo_id and not ocr.active.cancelled else None
        text, spoken, tone = "", "", "slate"
        if state == pov.QUEUED:
            ahead = ocr.queue_ahead(photo_id)
            text = spoken = T["pho_ocr_queued"].format(n=ahead) if ahead else T["pho_ocr_queued_soon"]          # 앞의 읽기를 취소하고 마무리하는 동안에는 앞에 기다리는 장이 없다 — '앞에 0장' 대신 곧 시작한다고 말한다
        elif state in (pov.PREPARING, pov.READING) and job is not None:
            reading = state == pov.READING
            since = (job.started if reading else job.began)
            since = now if since is None else since
            text = T["pho_ocr_reading"].format(s=max(0, int(now - since))) if reading else T["pho_ocr_preparing"]
            spoken = T["pho_ocr_reading_a11y"] if reading else T["pho_ocr_preparing"]
            if now - since > pov.SLOW_HINT_S:
                text, spoken = f"{text}\n{T['pho_ocr_slow']}", f"{spoken}. {T['pho_ocr_slow']}"
        elif state == pov.FAILED:
            code = pov.code_of(ocr.error_of(photo_id))
            text = T[ERROR_TEXT.get(code, "pho_ocr_err_failed")]
            if ocr.disabled_code and code not in SELF_EXPLAINING:
                text = f"{text}\n{T['pho_ocr_off_note']}"                         # 계속 안 돼서 끈 때 — 이유를 한 줄 더 알린다(설계 2-7)
            spoken, tone = text.replace("\n", " "), "red"
        elif state == pov.CANCELLED:
            text = spoken = T["pho_ocr_cancelled"]
        number = photo.number if photo is not None else 0
        return {"state": state, "text": text, "tone": tone, "a11y": T["pho_ocr_status_a11y"].format(n=number, text=spoken) if text else ""}

    def _items(self, number, lines):
        total = len(lines)
        items = []
        for index, (text, done) in enumerate(lines):
            state = T["pho_ocr_line_done" if done else "pho_ocr_line_pending"]
            items.append({"index": index, "text": text, "confirmed": done, "state_text": state, "a11y": T["pho_ocr_line_a11y"].format(n=number, total=total, m=index + 1, state=state),
                          "text_a11y": T["pho_ocr_line_text_a11y"].format(n=number, m=index + 1), "check_a11y": T["pho_ocr_line_check_a11y"].format(n=number, m=index + 1),
                          "edit": T["pho_ocr_line_edit"], "edit_a11y": T["pho_ocr_line_edit_a11y"].format(n=number, m=index + 1), "remove": T["pho_ocr_line_remove"],
                          "remove_a11y": T["pho_ocr_line_remove_a11y"].format(n=number, m=index + 1)})
        return items

    def _lines_vm(self, photo, lines, busy, ask):
        ocr = self.ocr
        number, total = photo.number, len(lines)
        done = sum(1 for _text, confirmed in lines if confirmed)
        found, hidden, over = ocr.summary_of(photo.photo_id)
        undo = ocr.undo_line
        can_undo = undo is not None and undo[0] == photo.photo_id and undo[2] == self.board.manifest and not busy                    # 되돌릴 수 있을 때만 단추를 보인다(그 뒤에 목록이 바뀌었으면 컨트롤러가 거절한다)
        notes = ([T["pho_ocr_hidden"].format(m=hidden)] if hidden else []) + ([T["pho_ocr_more"].format(limit=photo_ocr.MAX_LINES)] if over else [])
        error = self.error if self.error is not None and self.error[0] == photo.photo_id else None
        return {"visible": True, "enabled": not busy, "total": total, "confirmed": done,
                "title": T["pho_ocr_summary"].format(n=total, k=done) if done else T["pho_ocr_title"].format(n=total), "guide": T["pho_ocr_guide"],
                "digits": T["pho_ocr_digits"] if photo_ocr.has_digits([text for text, _confirmed in lines]) else "", "notes": notes, "items": self._items(number, lines),
                "list_a11y": T["pho_ocr_list_a11y"].format(n=number, total=total), "keys": T["pho_ocr_keys"],
                "all": {"text": T["pho_ocr_all"], "a11y": T["pho_ocr_all_a11y"].format(n=number), "enabled": done < total and ask is None and not busy},
                "merge": {"text": T["pho_ocr_merge"], "a11y": T["pho_ocr_merge_a11y"].format(n=number, m="{m}")},                   # `{m}` 는 지금 고른 줄의 번호가 들어갈 자리(화면이 채운다)
                "undo": {"text": T["pho_ocr_undo"], "a11y": T["pho_ocr_undo_a11y"].format(n=number)} if can_undo else None, "removed": T["pho_ocr_removed"] if can_undo else "",
                "ask_all": {"text": T["pho_ocr_all_ask"].format(n=ask[1]), "yes": T["pho_ocr_all_yes"], "yes_a11y": T["pho_ocr_all_yes_a11y"].format(n=number, k=ask[1]), "no": T["pho_ocr_all_no"],
                            "no_a11y": T["pho_ocr_all_no_a11y"].format(n=number)} if ask is not None else None,
                "error": {"index": error[1], "text": error[2]} if error is not None else None}

    def view(self, photo_id, now):
        """사진 한 줄의 글자 읽기 칸 — 없으면 `None`(이 줄에는 칸이 없다). 단추·상태 줄·읽은 글 목록과 두 확인 줄의 글이 모두 들어 있다."""
        ocr = self.ocr
        photo = self.board.photo(photo_id)
        if photo is None:
            return None
        self._drop_stale_ask()                                                     # 낡은 질문은 그리기 전에 거둔다
        state, lines = ocr.state_of(photo_id), ocr.lines(photo_id)
        usable = ocr.available and self._file_ok(photo_id)
        if not usable and state == pov.IDLE and not lines:
            return None                                                            # 읽을 수 없고(꺼짐·이번 실행에서 끔·파일 문제) 보일 것도 없다 — 이 줄은 지금과 같다
        number, total = photo.number, len(lines)
        busy = state in pov.BUSY_STATES
        read_visible = usable and not busy
        reread = ocr.reread_asked is not None and ocr.reread_asked[0] == photo_id
        ask = ocr.all_right_asked if ocr.all_right_asked[0] == photo_id else None
        found = ocr.summary_of(photo_id)[0]
        again = bool(total)
        return {
            "photo_id": photo_id, "number": number, "state": state, "busy": busy, "label": T["pho_ocr_label"], "hint": T["pho_ocr_hint"],
            "read": {"visible": read_visible, "text": T["pho_ocr_again" if again else "pho_ocr_btn"], "a11y": T["pho_ocr_again_a11y" if again else "pho_ocr_btn_a11y"].format(n=number), "size": pov.SIZE_NORMAL},
            "bigger": {"visible": read_visible and state == pov.DONE, "text": T["pho_ocr_bigger"], "a11y": T["pho_ocr_bigger_a11y"].format(n=number), "size": pov.SIZE_BIG},
            "cancel": {"visible": busy, "text": T["pho_ocr_cancel"], "a11y": T["pho_ocr_cancel_a11y"].format(n=number)},
            "status": self.status(photo_id, now),
            "none": T["pho_ocr_all_removed" if found else "pho_ocr_none"] if state == pov.DONE and not total else "",
            "ask_reread": {"text": T["pho_ocr_reread_ask"], "yes": T["pho_ocr_reread_yes"], "yes_a11y": T["pho_ocr_reread_yes_a11y"].format(n=number), "no": T["pho_ocr_reread_no"],
                           "no_a11y": T["pho_ocr_reread_no_a11y"].format(n=number)} if reread else None,
            "lines": self._lines_vm(photo, lines, busy, ask) if total else None,
        }

    def views(self, now):
        """모든 사진의 칸 `{사진 번호: 뷰모델 또는 None}`."""
        return {photo.photo_id: self.view(photo.photo_id, now) for photo in self.board.manifest.photos}


__all__ = ["ERROR_TEXT", "OcrPanel", "SELF_EXPLAINING", "WORKER_GONE"]
