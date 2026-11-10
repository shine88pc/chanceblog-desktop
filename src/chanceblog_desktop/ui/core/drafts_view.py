"""초안 작성 화면의 상태·동작·뷰모델 — 순수 파이썬(화면 도구를 모른다). Qt 화면은 `view()` 가 만든 딕셔너리를 그리기만 한다: 어떤 칸을 보일지·어느 단추를 켤지·어떤 문장을 보일지·복사 전에 무엇을 물을지는 여기서 정한다.

흐름과 규칙:
  · **아무것도 저장하지 않는다.** 초안은 메모리에만 있고(`result`·`title`·`body`) 파일·보관함·엔진 DB·글 보관함·후보 상태에 쓰는 길이 없다. 공급자는 읽기 하나(`make_draft`)뿐이고 초안을 만드는 것은 후보 번호로 서비스가 다시 읽어 하는 일이다.
  · **자동 실행은 없다**: 후보 화면에서 `이 주제로 만들기` 를 눌렀을 때만 만든다(`open_target` → `start_make`). 복사도 단추를 눌렀을 때만 — 초안을 만들거나 창을 열거나 검사해도 클립보드는 그대로다(클립보드에 쓰는 것은 화면 틀이고 이 파일은 복사할 **글**만 돌려준다).
  · **안전 판정이 '자동 초안 중지' 로 표시한 후보는 본문이 화면에 나오지 않는다** — 단추도 꺼 있고(후보 화면), `start_make` 도 공급자를 부르지 않고 거절하며, 공급자가 돌려준 초안의 후보 번호가 고른 후보와 다르면 버린다.
  · **복사 전 관문**(`copy_decision`): 키·토큰 모양이 있거나 **건강 효과를 단정하는 문장**(주제 엔진 판정기가 중지 단계로 본 것 — 서비스가 만든 글·선택 입력·고친 글 모두, `review_health`)이 있으면 복사하지 않고(막음 — 어느 부분이 걸렸는지 앞부분만 짚는다),
    이 글에만 해당하는 확인 권장·분야 못 읽음·편집기 글의 점검 걸림·거의 안 고침이 있으면 확인창을 먼저 띄운다(처음 포커스는 취소 — `confirm_copy` 만 글을 돌려준다).
    이미 확인한 것은 다시 묻지 않고 새로 생긴 것만 다시 묻는다. 복사할 글은 확인창 뒤에도 한 번 더 막을 이유를 본다(`final_text`).
  · **고친 내용은 확인 없이 사라지지 않는다**: 제목·본문을 고쳤거나 선택 입력을 적고 아직 반영하지 않았으면(`has_unsaved`) 다시 만들기·다른 제목 후보 고르기·화면 떠나기·앱 닫기 전에 확인창이 먼저다.
    다시 만드는 동안(`locked`)에는 제목·본문을 고칠 수 없다 — 새 초안이 오면 덮이므로 그 사이에 친 글이 조용히 사라지지 않게 편집기를 읽기 전용으로 둔다.
오류 문장은 쉬운 말뿐이다(파이썬 목록·내부 예외·오류 코드·경로 없음). 후보 제목·키워드는 이 코드에 없고(저장된 값을 보이기만 한다) 보일 때는 비밀 모양을 가린 뒤 줄인다.
"""
from __future__ import annotations

from ...content.profiles import POST_TYPES
from . import draft_garbage as garbage
from . import draft_rules as rules
from .drafts import DraftFailure, DraftRequest, review_health
from .jobs import Job, JobFailure
from .text import T

DRAFT_KEY = "drafts-make"                                    # 초안을 만드는 작업의 이름(후보·홈·설정 읽기와 따로 돈다)
STATES = ("empty", "loading", "normal", "refused", "notfound", "error")
FAILURE_TEXT = {"io": "drf_fail_io", "newer": "drf_fail_newer", "corrupt": "drf_fail_corrupt", "invalid": "drf_fail_invalid", "notfound": "drf_fail_notfound", "stopped": "drf_refused_desc", "channel": "drf_channel_desc", "other": "drf_fail_other"}
IMAGE_STATES = ("before", "skip")
KEYWORD_SEPARATOR = ", "


class DraftsController:
    def __init__(self, provider, runner):
        self.provider, self.runner = provider, runner
        self.target = None
        self.pending = None
        self.make_count = 0
        self.garbage = garbage.GarbageTracker()              # 글 모양 점검(N-2) — 복사 관문과 다른 결과 칸이다(경고만, `gate`·`copy_decision` 은 이 상태를 읽지 않는다)
        self._garbage_job = None
        self._clear_draft()
        self.state = "empty"

    def _clear_draft(self):
        self.result = None
        self.failure = None
        self.failed_at = None
        self.refusal = ""                                    # 거절 화면의 종류: `stopped`·`channel`
        self.title = ""
        self.body = ""
        self.fields = {}                                     # 선택 입력 칸에 적은 글(아직 반영하지 않은 것 포함)
        self.blog = None                                     # 화면에서 고른 블로그(None = 후보 기준)
        self.post_type = None
        self.options_open = False
        self.common_open = False
        self.image_state = "before"
        self.notice = None
        self.copied = set()
        self.ack = {}                                        # 묶음 이름 → 이미 확인한 항목들
        self.inspection = None
        self.inspected_for = None
        self.copy_asked = None
        self.pick_asked = None
        self.regen_asked = False
        self.leave_asked = None
        self._cancel_garbage()                               # 새 초안·떠남 — 도는 글 모양 점검의 답은 받지 않고 결과·무시 기억을 지운다(저장하지 않는다)

    # ---- 읽기(파일·폴더를 만들지 않는다) ----
    @property
    def busy(self):
        return self.runner.running(DRAFT_KEY)

    def draft_body(self):
        """서비스가 만든 초안(`DraftBody`) — 없으면 None."""
        return self.result.body if self.result is not None else None

    def generated_titles(self):
        body = self.draft_body()
        return tuple(body.titles) if body is not None else ()

    # ---- 후보를 고르고 초안을 만든다 ----
    def open_target(self, target):
        """후보를 골라 이 화면으로 왔다 — 이전 초안·고친 내용·선택은 모두 지운다(고친 내용이 있었다면 부른 쪽이 먼저 물었어야 한다: `leave_dialog`). 후보가 없으면 빈 화면."""
        self._clear_draft()
        self.target = target
        self.state = "loading" if target is not None else "empty"
        if target is not None and target.stop:
            self._refuse("stopped")
        elif target is not None and target.channel not in rules.BLOG_NAMES:
            self._refuse("channel")
        return self.state

    def _refuse(self, kind):
        self.result, self.title, self.body = None, "", ""
        self.refusal, self.state = kind, "refused"

    def start_make(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """초안을 작업 스레드에서 만든다(읽기뿐). `(상태, 작업)`: `unavailable`(고른 후보 없음)·`refused`(중지 후보·네이버가 아닌 채널 — 공급자를 부르지 않는다)·`busy`·`started`.
        이미 초안이 있으면(다시 만들기) 보이던 초안·고친 내용은 새 초안이 올 때까지 그대로다."""
        target = self.target
        if target is None:
            return "unavailable", None
        if target.stop:
            self._refuse("stopped")
            return "refused", None
        if target.channel not in rules.BLOG_NAMES:
            self._refuse("channel")
            return "refused", None
        if self.busy:
            return "busy", None
        request = DraftRequest(target.candidate_id, self.blog, self.post_type, rules.options_dict(self.fields))
        provider = self.provider
        job = self.runner.start(DRAFT_KEY, lambda progress, cancelled: provider.make_draft(request, progress, cancelled), on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return "busy", None
        self.pending = {"request": request}
        self.make_count += 1
        self.regen_asked = False
        if self.result is None:
            self.state = "loading"
        else:
            self.notice = ("info", T["drf_making"])
        return "started", job

    def apply_made(self, result):
        """초안이 왔다 — 고른 후보의 것이고 안전 판정이 중지한 후보가 아닐 때만 보인다(아니면 버리고 오류). 새 초안이 오면 고친 내용·확인·복사 표시는 모두 새로 시작한다."""
        pending, self.pending = self.pending, None
        target = self.target
        if target is None:                                   # 그 사이 화면을 떠났다 — 늦게 온 답은 어디에도 보이지 않는다
            return False
        request = (pending or {}).get("request")
        if request is None or target.stop or result is None or getattr(result, "candidate_id", None) != target.candidate_id or getattr(result, "body", None) is None:
            self.apply_make_failed(DraftFailure(T["job_failed"], code="DRAFT_MISMATCH", kind="other"))
            return False
        again = self.result is not None
        self.result = result
        self.title, self.body = result.body.selected_title, result.body.body_text
        self.blog, self.post_type = result.blog, request.post_type
        self.ack, self.copied, self.inspection, self.inspected_for = {}, set(), None, None
        self.copy_asked = self.pick_asked = self.leave_asked = None
        self.regen_asked = False
        self._cancel_garbage()                               # 새 초안이 오면 글 모양 점검의 결과·무시 기억도 새로 시작한다
        self.failure, self.state = None, "normal"
        notes = []
        if result.rejected:
            notes.append(T["drf_note_rejected"])
        names = dict(result.blog_names)
        if target.channel in rules.BLOG_NAMES and target.channel != result.blog:
            notes.append(T["drf_note_other_blog"].format(channel=rules.shown(names.get(target.channel) or target.channel_name, 30), blog=rules.shown(names.get(result.blog, ""), 30)))
        if again:
            notes.append(T["drf_made_again"])
        self.notice = ("ok" if again else "info", " ".join(notes)) if notes else None
        return True

    def apply_make_failed(self, failure, when=None):
        """만들지 못했다 — 중지 후보·네이버가 아닌 채널은 본문 없이 거절 화면, 후보가 없으면 그 안내, 그 밖의 실패는 이미 보이던 초안이 있으면 **그대로 두고** 알림만(고친 내용을 지우지 않는다), 없으면 오류 화면. 문장은 정해진 쉬운 말뿐이다."""
        from .app_state import clean_failure
        self.pending = None
        if self.target is None:                              # 그 사이 화면을 떠났다 — 늦게 온 실패는 어디에도 보이지 않는다
            return "left"
        kind = failure.kind if isinstance(failure, DraftFailure) else "other"
        # 화면에 나가는 문장은 종류별로 정해진 쉬운 말뿐이다(공급자가 준 글은 쓰지 않는다) — 선택 입력의 틀린 칸만 칸 이름과 고정 이유를 보인다
        text = getattr(failure, "user_message", "") if kind == "option" else T[FAILURE_TEXT.get(kind, "drf_fail_other")]
        self.failure, self.failed_at = clean_failure(JobFailure(text or T["drf_fail_option_plain"], code=getattr(failure, "code", ""))), when
        text = self.failure.user_message
        if kind in ("stopped", "channel"):
            self._refuse(kind)
            return kind
        if kind == "notfound" and self.result is None:
            self.state = "notfound"
            return kind
        if self.result is not None:
            self.notice, self.state = ("error", text), "normal"
            return kind
        self.state = "error"
        return kind

    def apply_unexpected(self, error, when=None):
        """화면 스레드의 슬롯에서 예상하지 못한 예외가 났다 — 받아 둔 값을 버리고 오류 상태로(쉬운 문장 + 예외 이름만 진단 정보에)."""
        from .app_state import clean_failure
        target = self.target
        self._clear_draft()
        self.pending, self.target = None, target
        self.failure, self.failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.state = "error"

    def apply_cancelled(self):
        self.pending = None
        self.state = "normal" if self.result is not None else ("error" if self.target is not None else "empty")
        if self.target is not None and self.result is None:
            from .app_state import clean_failure
            self.failure = clean_failure(JobFailure(T["drf_fail_other"], code="CANCELLED"))

    # ---- 고치기(파일·클립보드에 닿지 않는다) ----
    @property
    def locked(self):
        """새 초안을 만드는 중(다시 만들기)이라 제목·본문을 고칠 수 없다 — 새 초안이 오면 제목·본문이 덮이므로 그 사이에 친 글이 확인 없이 사라지지 않게 편집기를 잠근다(독립 검증 V5). 처음 만드는 중에는 편집기가 없다."""
        return self.result is not None and self.busy

    def set_title(self, text):
        """제목을 고친다 → 바꿨으면 True. 다시 만드는 동안(`locked`)에는 바꾸지 않는다."""
        if self.locked:
            return False
        self.title = text if isinstance(text, str) else ""
        return True

    def set_body(self, text):
        """본문을 고친다 → 바꿨으면 True. 다시 만드는 동안(`locked`)에는 바꾸지 않는다."""
        if self.locked:
            return False
        self.body = text if isinstance(text, str) else ""
        return True

    def set_option(self, name, text):
        if name in dict(rules.OPTION_FIELDS) and isinstance(text, str):
            self.fields[name] = text
            return True
        return False

    def set_blog(self, key):
        if key in rules.BLOG_NAMES:
            self.blog = key
            return True
        return False

    def set_post_type(self, key):
        if key is None or key in POST_TYPES:
            self.post_type = key
            return True
        return False

    def toggle_options(self):
        self.options_open = not self.options_open
        return self.options_open

    def set_common_open(self, opened):
        self.common_open = bool(opened)

    def toggle_image(self):
        self.image_state = "before" if self.image_state == "skip" else "skip"
        return self.image_state

    def title_edited(self):
        body = self.draft_body()
        if body is None:
            return False
        return " ".join(self.title.split()) not in {" ".join(item.split()) for item in body.titles}

    def body_edited(self):
        body = self.draft_body()
        return body is not None and self.body != body.body_text

    def options_pending(self):
        return self.result is not None and rules.options_dict(self.fields) != dict(self.result.options)

    def has_unsaved(self):
        """고친 내용이 있는가 — 제목·본문을 고쳤거나 선택 입력을 적고 아직 반영하지 않았다. 있으면 사라지는 일(다시 만들기·떠나기·닫기) 전에 확인창이 먼저다."""
        return self.result is not None and (self.title_edited() or self.body_edited() or self.options_pending())

    # ---- 제목 후보 고르기 ----
    def pick_title(self, index):
        """제목 후보를 골랐다 → `ok`(제목을 바꿨다)·`confirm`(고친 제목이 사라지므로 확인창이 먼저 — `pick_dialog`)·`unavailable`."""
        titles = self.generated_titles()
        if self.locked or not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(titles):
            return "unavailable"
        if self.title_edited():
            self.pick_asked = index
            return "confirm"
        self.title = titles[index]
        return "ok"

    def pick_dialog(self):
        if self.pick_asked is None:
            return None
        return {"title": T["drf_pick_title"], "body": T["drf_pick_body"], "ok": T["drf_pick_ok"], "cancel": T["drf_cancel"]}

    def confirm_pick(self):
        index, self.pick_asked = self.pick_asked, None
        titles = self.generated_titles()
        if self.locked or index is None or not 0 <= index < len(titles):
            return False
        self.title = titles[index]
        return True

    def discard_pick(self):
        self.pick_asked = None

    # ---- 다시 만들기 ----
    def regen_dialog(self):
        """고친 내용이 사라지면 확인창의 글, 아니면 None(바로 만들어도 된다)."""
        if not self.has_unsaved():
            return None
        self.regen_asked = True
        return {"title": T["drf_regen_title"], "body": T["drf_regen_body"], "ok": T["drf_regen_ok"], "cancel": T["drf_cancel"]}

    def discard_regen(self):
        self.regen_asked = False

    def start_regenerate(self, **callbacks):
        """다시 만들기 — 고친 내용이 있는데 확인창을 보이지 않았으면 아무것도 하지 않는다(`unconfirmed`)."""
        if self.result is None:
            return "unavailable", None
        if self.has_unsaved() and not self.regen_asked:
            return "unconfirmed", None
        return self.start_make(**callbacks)

    # ---- 화면을 떠나거나 앱을 닫기 ----
    def leave_dialog(self, kind="leave"):
        """고친 내용이 있으면 확인창의 글(`leave`: 다른 화면으로 · `close`: 앱 닫기), 없으면 None."""
        if not self.has_unsaved():
            return None
        self.leave_asked = kind
        closing = kind == "close"
        return {"title": T["drf_leave_title"], "body": T["drf_close_body"] if closing else T["drf_leave_body"], "ok": T["drf_close_ok"] if closing else T["drf_leave_ok"], "cancel": T["drf_cancel"]}

    def discard_leave(self):
        self.leave_asked = None

    def leave(self):
        """화면을 떠난다 — 초안은 메모리에서 지운다(저장하지 않는다. 고친 내용이 있으면 부른 쪽이 먼저 물었어야 한다). 돌고 있던 만들기는 취소하고 늦게 오는 답은 버린다."""
        self.runner.cancel(DRAFT_KEY)
        self._clear_draft()
        self.target, self.pending, self.state = None, None, "empty"

    # ---- 점검 ----
    def inspect(self):
        """`검사하기` — 편집기의 제목·본문을 훑는다(읽기뿐 — 파일·클립보드에 닿지 않는다). 결과는 `view()` 의 검사 카드에 보인다."""
        if self.result is None:
            return None
        self.inspection = self._inspect_now()
        self.inspected_for = (self.title, self.body)
        return self.inspection

    def _inspect_now(self):
        body = self.draft_body()
        return rules.inspect_text(self.title, self.body, generated_title=body.selected_title, generated_titles=body.titles, generated_body=body.body_text, options=dict(self.result.options), health=self.health_for("all"))

    def inspection_fresh(self):
        return self.inspection is not None and self.inspected_for == (self.title, self.body)

    # ---- 글 모양 점검(N-2) — 경고만 한다: 복사 관문(`gate`·`copy_decision` …)과 다른 결과 칸이고 그쪽은 이 상태를 읽지 않는다. 글을 바꾸지도 않는다 ----
    def start_garbage(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """`검사하기` 를 눌렀을 때만 — 글 모양 점검을 **작업 스레드**에서 시작한다(읽기뿐, 글을 치는 동안·복사할 때는 부르지 않는다). 글의 바뀌지 않는 복사본(문자열)만 넘기고 결과 값(걸린 글 없음)을 받는다.
        `(상태, 작업)`: `unavailable`(초안이 없다·새 초안을 만드는 중)·`busy`(도는 검사가 이미 있다 — 중복 실행 방지)·`started`. 화면 도구는 콜백을 자기 화면 스레드로 넘겨(Qt: 시그널) `apply_garbage`·`apply_garbage_failed` 를 부른다."""
        if self.result is None or self.state != "normal" or self.busy:
            return "unavailable", None
        title, body = self.title, self.body
        generation = self.garbage.begin(title, body)
        if generation is None:
            return "busy", None

        def failed(failure, payload):
            failure.generation = payload                         # 어느 검사의 실패인지(낡은 검사의 실패가 지금 검사를 실패로 만들지 않게)
            if on_error is not None:
                on_error(failure, payload)

        job = Job(garbage.GARBAGE_KEY, lambda progress, cancelled: garbage.run(generation, title, body), payload=generation, on_done=on_done, on_error=failed, on_cancel=on_cancel)
        self._garbage_job = job
        job.start()
        return "started", job

    def apply_garbage(self, result):
        """검사 결과가 왔다 → 받았으면 True. 세대 번호가 지금 도는 검사와 다르면(그 사이 새 초안·떠남) 버린다."""
        return self.garbage.deliver(result)

    def apply_garbage_failed(self, failure):
        """검사가 끝내 실패했다 → 지금 검사의 실패였으면 True(카드가 `점검을 끝내지 못했어요` 를 보인다)."""
        return self.garbage.fail(getattr(failure, "generation", None))

    def apply_garbage_cancelled(self):
        """취소된 검사의 알림 — 취소는 새 초안·떠남·닫기에서만 일어나고 그때 이미 모두 지웠으므로 할 일이 없다."""
        return False

    def _cancel_garbage(self):
        job, self._garbage_job = self._garbage_job, None
        if job is not None:
            job.cancel()                                         # 기다리지 않는다 — 끝난 스레드의 답은 세대가 달라 어디에도 보이지 않는다
        self.garbage.reset()

    def shutdown(self):
        """앱을 닫는다 — 도는 글 모양 점검의 답을 버린다(작업자 종료를 기다리지 않는다)."""
        self._cancel_garbage()

    def garbage_card(self):
        """글 모양 점검 카드의 글(검사 전·검사 중·결과 있음·결과 없음·본문이 변경됨·너무 길어 건너뜀) — 글을 칠 때마다 이것만 다시 만들어 보인다(결과는 지우지 않고 낡았음을 알린다)."""
        return self.garbage.card(self.title, self.body)

    def ignore_garbage(self, key):
        """항목 하나를 무시한다(이 화면의 메모리에만 기억 — 새 초안·떠남에서 지운다) → 바뀌었으면 True."""
        return self.garbage.ignore(key)

    def ignore_all_garbage(self):
        return self.garbage.ignore_all()

    def restore_garbage(self):
        return self.garbage.restore()

    # ---- 건강 판정(두 번째 방어선) ----
    def _health_units(self, item):
        """복사하거나 검사할 글의 건강 판정 조각들 — ((이름, 조각들), …). 제목·본문은 문장 단위, 키워드·태그는 하나씩, 요약은 문장 단위."""
        body = self.draft_body()
        if body is None:
            return ()
        where_title, where_body = T["drf_where_title"], T["drf_where_body"]
        if item == "title":
            return ((where_title, rules.health_units(self.title)),)
        if item == "body":
            return ((where_body, rules.health_units(self.body)),)
        if item == "all":
            return ((where_title, rules.health_units(self.title)), (where_body, rules.health_units(self.body)))
        if item == "keywords":
            return ((T["drf_side_keywords"], tuple((*body.core_keywords, *body.sub_keywords))),)
        if item == "tags":
            return ((T["drf_side_tags"], tuple(body.tags)),)
        if item == "summary":
            return ((T["drf_side_summary"], rules.health_units(body.summary)),)
        return ()

    def health_for(self, item):
        """`item`(복사 항목) 의 글에 건강 효과 단정이 있나 — `HealthReview`. 서비스가 만든 글·사용자가 적은 선택 입력·고친 글 어느 것이든 지금 복사할 글 자체를 본다."""
        return review_health(*self._health_units(item))

    def user_health(self):
        """**직접 쓴 글**(적용한 선택 입력·고친 제목·본문에 더한 문장)만의 건강 판정 — 후보의 제목·키워드에서 온 건강 낱말은 서비스가 이미 확인 권장 줄로 알려 주므로 뺀다(같은 말이 되풀이되지 않게)."""
        body = self.draft_body()
        if body is None:
            return review_health()
        own = []
        options = {name: value for name, value in dict(self.result.options).items() if name != "urls"}      # 참고 주소는 글이 아니다
        for text in rules.user_texts(options):
            own += rules.health_units(text)
        generated = set(rules.health_units(body.body_text))
        added = tuple(unit for unit in rules.health_units(self.body) if unit not in generated)
        title = rules.health_units(self.title) if self.title_edited() else ()
        return review_health((T["drf_where_body"], (*own, *added)), (T["drf_where_title"], title))

    def _user_health_lines(self):
        stage = self.user_health().stage
        key = {"mark": "drf_chk_health_mark", "evidence": "drf_chk_health_evidence"}.get(stage)
        return (T[key],) if key else ()

    # ---- 확인 권장 ----
    def checks(self):
        """(이 글에만 해당, 모든 글 공통, 관문에 쓰는 줄들, 분야를 못 읽었나) — 서비스의 줄을 화면 규칙으로 가른 것에 구조 칸에서 읽은 줄과 **직접 쓴 글의 건강 낱말 줄**을 더한 것."""
        body = self.draft_body()
        specific, common = rules.split_checks(body.checks)
        derived = (*rules.derived_lines(body), *self._user_health_lines())
        unknown = getattr(body, "domain", "") == rules.GENERIC_DOMAIN
        gate_lines = tuple(line for line in (*specific, *derived) if not (unknown and line == T["drf_chk_domain"]))
        return (*specific, *derived), common, gate_lines, unknown

    # ---- 복사 전 관문 ----
    def text_for(self, item):
        """복사할 글 — 제목·본문은 **고친 그대로**, 전체는 제목 + 빈 줄 하나 + 본문(서비스의 `plain_text` 와 같은 모양), 키워드·태그·요약은 초안의 값."""
        body = self.draft_body()
        if body is None:
            return None
        if item == "title":
            return self.title
        if item == "body":
            return self.body
        if item == "all":
            return self.title + chr(10) + chr(10) + self.body
        if item == "keywords":
            return KEYWORD_SEPARATOR.join((*body.core_keywords, *body.sub_keywords))
        if item == "tags":
            return body.tags_text
        if item == "summary":
            return body.summary
        return None

    def blocks_for(self, item):
        """`item` 을 복사하면 안 되는 이유와 그 자리 — ((`keyshape`·`health`, 미리보기들), …), 없으면 빈 튜플. 키·토큰 모양(제목·본문·복사할 글 어디든 — 예전과 같다)과 복사할 글의 건강 효과 단정."""
        own = () if item in rules.GATED else ((self._item_name(item), self.text_for(item) or ""),)           # 제목·본문·전체는 위 둘이 이미 그 글이다(같은 자리를 두 번 짚지 않는다)
        places = rules.secret_places((T["drf_where_title"], self.title), (T["drf_where_body"], self.body), *own)
        blocks = []
        if places:
            blocks.append(("keyshape", places))
        health = self.health_for(item)
        if health.stage == rules.HEALTH_STOP:
            blocks.append(("health", health.places))
        return tuple(blocks)

    def _item_name(self, item):
        return {"title": T["drf_where_title"], "body": T["drf_where_body"], "all": T["drf_where_body"], "keywords": T["drf_side_keywords"], "tags": T["drf_side_tags"], "summary": T["drf_side_summary"]}.get(item, "")

    def final_text(self, item):
        """클립보드에 넣을 글 — 복사 직전의 마지막 확인: 키·토큰 모양이나 건강 효과 단정이 있으면 None. 글이 비어 있어도 None(빈 글을 복사하지 않는다)."""
        text = self.text_for(item)
        if not text or not text.strip():
            return None
        if self.blocks_for(item):
            return None
        return text

    def gate(self, item):
        _specific, _common, gate_lines, unknown = self.checks()
        return rules.gate_for(item, self._inspect_now(), gate_lines, unknown, self.ack, health=self.health_for(item))

    def copy_decision(self, item):
        """복사 단추를 눌렀다 → `(결정, 내용)`: `unavailable`·`blocked`(키 모양·건강 효과 단정 — 내용은 안내창 글)·`confirm`(확인창 글 — 보인 뒤에만 `confirm_copy` 가 글을 준다)·`copy`(복사할 글). **이 함수는 클립보드에 쓰지 않는다.**"""
        if self.result is None or self.state != "normal" or item not in rules.COPY_ITEMS:
            return "unavailable", None
        if item in rules.SMALL_COPIES:
            blocks = self.blocks_for(item)
            if blocks:
                return "blocked", self.blocked_dialog(blocks)
            text = self.final_text(item)
            return ("copy", text) if text else ("unavailable", None)
        gate = self.gate(item)
        if gate.blocked:
            self.copy_asked = None
            return "blocked", self.blocked_dialog(gate.blocks)
        if gate.needs_dialog:
            self.copy_asked = item
            return "confirm", self.gate_dialog(item, gate)
        text = self.final_text(item)
        return ("copy", text) if text else ("unavailable", None)

    def confirm_copy(self, item):
        """확인창에서 `그래도 복사` 를 눌렀다 — 확인창을 보인 복사일 때만 글을 돌려준다(아니면 None). 그 사이 글이 바뀌어 키 모양이 생겼으면 막는다. 확인한 항목은 기억해 다시 묻지 않는다."""
        if self.copy_asked != item or self.result is None:
            return None
        gate = self.gate(item)
        if gate.blocked:
            self.copy_asked = None
            return None
        self.copy_asked = None
        for name, keys in gate.keys.items():
            self.ack.setdefault(name, set()).update(keys)
        return self.final_text(item)

    def discard_copy(self):
        """확인창을 확인 없이 닫았다(취소·Esc) — '확인창을 보였다' 표시를 거둔다."""
        self.copy_asked = None

    def blocked_dialog(self, blocks=()):
        """막음 안내창(확인만 있다) — 이유(키·토큰 모양 / 건강 효과 단정)마다 한 문장과, 어느 부분이 걸렸는지 앞부분만 짚은 줄들. 이유를 주지 않으면 키 모양 안내다."""
        kinds = [kind for kind, _places in blocks] or ["keyshape"]
        lines = [T["drf_health_body" if kind == "health" else "drf_secret_body"] for kind in dict.fromkeys(kinds)]
        places = list(dict.fromkeys(place for _kind, items in blocks for place in items))[:rules.SPOT_LIMIT]
        if places:
            lines.append(T["drf_where_head"])
            lines += [T["drf_gate_line"].format(text=place) for place in places]
        return {"title": T["drf_secret_title"], "body": chr(10).join(lines), "ok": T["drf_secret_ok"], "cancel": None}

    def gate_dialog(self, item, gate):
        """복사 전 확인창의 글 — 묶음마다 머리 한 줄과 항목(앞 셋까지, 나머지는 개수). 취소가 처음 포커스이고 `그래도 복사` 를 눌러야 복사한다."""
        if [name for name, _items in gate.reasons] == ["unchanged"]:                       # 부드러운 안내뿐이면 '확인 권장' 을 읽었나가 아니라 안내 하나만 — 막지 않는다
            return {"title": T["drf_soft_title"], "body": T["drf_soft_body"], "ok": T["drf_gate_ok"], "cancel": T["drf_cancel"], "count": gate.count}
        heads = {"check": T["drf_gate_checks"], "domain": T["drf_gate_domain"], "claims": T["drf_gate_claims"], "unchanged": T["drf_gate_unchanged_head"]}
        lines = []
        for name, items in gate.reasons:
            lines.append(heads[name].format(n=len(items)))
            shown = items[:3]
            lines += [T["drf_gate_line"].format(text=rules.shown(text, 120)) for text in shown]
            if len(items) > len(shown):
                lines.append(T["drf_gate_more"].format(n=len(items) - len(shown)))
        lines.append(T["drf_gate_tail"])
        return {"title": T["drf_gate_title"].format(n=gate.count), "body": chr(10).join(lines), "ok": T["drf_gate_ok"], "cancel": T["drf_cancel"], "count": gate.count}

    def mark_copied(self, item):
        """복사했다 — 그 단추를 잠깐 `✓ … 복사됨` 으로 보인다(`clear_copied` 가 지운다)."""
        if item in rules.COPY_ITEMS:
            self.copied.add(item)
            return True
        return False

    def clear_copied(self, item):
        self.copied.discard(item)

    def copied_text(self, item):
        return {"title": T["drf_copied_title"], "body": T["drf_copied_body"], "all": T["drf_copied_all"], "keywords": T["drf_copied_keywords"], "tags": T["drf_copied_tags"], "summary": T["drf_copied_summary"]}[item]

    # ---- 네이버 글쓰기 열기(주소만) ----
    def open_info(self):
        """`네이버 글쓰기 열기` — `(주소, 못 켜는 까닭)`. 프로필의 블로그 주소가 `https://blog.naver.com/<아이디>` 모양이 아니면 주소는 빈 글이고 단추는 꺼진다."""
        if self.result is None or self.state != "normal":
            return "", T["drf_open_why_wait"]
        url = rules.naver_write_url(self.result.blog_url)
        return (url, "") if url else ("", T["drf_open_why_profile"])

    # ---- 뷰모델 ----
    def _head(self):
        return {"title": T["drf_title"], "sub": T["drf_sub"], "back": {"text": T["drf_back"], "a11y": T["drf_back_a11y"]}}

    def _sample(self):
        sample = bool((self.result is not None and self.result.sample) or (self.target is not None and self.target.sample))
        return {"sample": sample, "sample_tag": T["sample_tag"], "sample_tip": T["drf_sample_tip"]}

    def _refused(self):
        stopped = self.refusal == "stopped"
        return {"title": T["drf_refused_title" if stopped else "drf_channel_title"], "desc": T["drf_refused_desc" if stopped else "drf_channel_desc"], "button": T["drf_to_topics"],
                "candidate": T["drf_ctx_candidate"].format(title=rules.shown(self.target.title, 80)) if self.target is not None and self.target.title else ""}

    def _empty(self):
        return {"title": T["drf_empty_title"], "button": T["drf_to_topics"]}

    def _fields(self):
        labels = rules.option_labels()
        rows = []
        for name, single in rules.OPTION_FIELDS:
            rows.append({"name": name, "label": labels[name], "hint": T["drf_hint_" + name], "value": self.fields.get(name, ""), "single": single, "a11y": T["drf_opt_a11y"].format(label=labels[name])})
        return rows

    def _options(self):
        result = self.result
        names = dict(result.blog_names)
        blogs = [{"key": key, "label": rules.shown(names.get(key) or key, 30), "active": key == (self.blog or result.blog), "a11y": T["drf_blog_a11y"].format(name=rules.shown(names.get(key) or key, 30))} for key in rules.BLOG_NAMES]
        kinds = [{"key": None, "label": T["drf_type_auto"], "active": self.post_type is None, "a11y": T["drf_type_a11y"].format(name=T["drf_type_auto"])},
                 *({"key": kind, "label": kind, "active": self.post_type == kind, "a11y": T["drf_type_a11y"].format(name=kind)} for kind in POST_TYPES)]
        pending = self.options_pending()
        return {"open": self.options_open, "toggle": T["drf_options_close" if self.options_open else "drf_options_open"], "title": T["drf_options_title"], "note": T["drf_options_note"],
                "blog_title": T["drf_blog_label"], "blogs": blogs, "type_title": T["drf_type_label"], "types": kinds, "fields": self._fields(),
                "apply": {"text": T["drf_remake"], "tip": T["drf_remake_tip"], "enabled": not self.busy}, "pending": pending, "pending_text": T["drf_options_pending"] if pending else ""}

    def title_picks(self):
        """제목 후보 셋의 줄 — 지금 제목 칸의 글과 같은 후보가 선택으로 보인다(글을 칠 때마다 이것만 다시 만들어 보인다)."""
        body = self.draft_body()
        if body is None:
            return []
        current = " ".join(self.title.split())
        return [{"index": number, "text": rules.shown(text, 80), "selected": current == " ".join(text.split()), "a11y": T["drf_title_pick_a11y"].format(n=number + 1, text=rules.shown(text, 80)),
                 "label": T["drf_title_pick"].format(n=number + 1)} for number, text in enumerate(body.titles)]

    def inspect_card(self):
        """검사 카드의 글(아직 안 했다·고친 뒤라 다시 해야 한다·결과) — 글을 칠 때마다 이것만 다시 만들어 보인다."""
        return self._inspect_card()

    def options_vm(self):
        """만드는 방법 칸의 뷰모델 — 펼침·고른 블로그/글 유형·적은 칸·반영하지 않은 글 안내."""
        return self._options()

    def _inspect_card(self):
        title = {"title": T["drf_side_inspect"], "button": T["drf_inspect_btn"], "button_a11y": T["drf_inspect_btn_a11y"], "hint": T["drf_inspect_hint"]}
        if self.inspection is None:
            return {**title, "tone": "muted", "status": T["drf_inspect_before"], "lines": []}
        if not self.inspection_fresh():
            return {**title, "tone": "info", "status": T["drf_inspect_stale"], "lines": []}
        found = self.inspection
        lines = [T["drf_gate_line"].format(text=f"{note.label}: {note.preview}") for note in found.claims[:rules.MAX_CLAIM_LINES]]
        if len(found.claims) > rules.MAX_CLAIM_LINES:
            lines.append(T["drf_gate_more"].format(n=len(found.claims) - rules.MAX_CLAIM_LINES))
        stopped = found.health is not None and found.health.stage == rules.HEALTH_STOP
        if found.secret:                                                   # 막은 자리(앞부분만)가 먼저 — 어디를 지울지 알 수 있게
            return {**title, "tone": "error", "status": T["drf_inspect_secret"], "lines": [T["drf_gate_line"].format(text=place) for place in found.places] + lines}
        if stopped:
            return {**title, "tone": "error", "status": T["drf_inspect_health_stop"], "lines": [T["drf_gate_line"].format(text=place) for place in found.health.places] + lines}
        careful = [T["drf_inspect_health_check"]] if self.user_health().stage in ("mark", "evidence") else []      # 직접 쓴 글에 건강 낱말이 있다 — 막지는 않지만 읽어 보라고 알린다
        unchanged = [T["drf_inspect_unchanged"].format(n=found.changed)] if found.unchanged else []
        if found.claims:
            return {**title, "tone": "warning", "status": T["drf_inspect_claims"].format(n=len(found.claims)), "lines": lines + careful + unchanged}
        if careful:
            return {**title, "tone": "warning", "status": careful[0], "lines": unchanged}
        if found.unchanged:
            return {**title, "tone": "info", "status": T["drf_inspect_unchanged"].format(n=found.changed), "lines": []}
        return {**title, "tone": "ok", "status": T["drf_inspect_ok"], "lines": []}

    def _side(self):
        body = self.result.body
        specific, common, _gate_lines, _unknown = self.checks()
        return {
            "inspect": self._inspect_card(),
            "garbage": self.garbage_card(),
            "keywords": {"title": T["drf_side_keywords"], "core_title": T["drf_kw_core"], "core": [rules.shown(item, 40) for item in body.core_keywords], "sub_title": T["drf_kw_sub"], "sub": [rules.shown(item, 40) for item in body.sub_keywords],
                         "copy": self._copy_button("keywords", T["drf_copy_keywords"])},
            "tags": {"title": T["drf_side_tags"], "items": [rules.shown(item, 40) for item in body.tags], "copy": self._copy_button("tags", T["drf_copy_tags"])},
            "category": {"title": T["drf_side_category"], "text": rules.shown(body.category, 60) if body.category else T["drf_category_none"], "missing": not body.category},
            "summary": {"title": T["drf_side_summary"], "text": rules.shown(body.summary, 200), "copy": self._copy_button("summary", T["drf_copy_summary"])},
            "image": {"title": T["drf_side_image"], "state": self.image_state, "state_text": T["drf_image_skip" if self.image_state == "skip" else "drf_image_before"], "desc": T["drf_image_desc"],
                      "button": T["drf_image_undo" if self.image_state == "skip" else "drf_image_btn"], "button_a11y": T["drf_image_undo_a11y" if self.image_state == "skip" else "drf_image_btn_a11y"]},
            "checks": {"title": T["drf_side_checks"], "status": self._source_status(specific, common), "open_text": T["conn_group_open"], "closed_text": T["conn_group_closed"], "specific": {"key": "specific", "title": T["drf_chk_specific"], "lines": list(specific), "open": True, "empty": T["drf_chk_specific_none"], "chip": T["drf_chk_count"].format(n=len(specific)), "tone": "warning" if specific else "muted"},
                       "common": {"key": "common", "title": T["drf_chk_common"], "lines": list(common), "open": self.common_open, "chip": T["drf_chk_count"].format(n=len(common)), "tone": "muted"}},
        }

    def _source_status(self, specific, common):
        """출처와 확인 필요 상태 한 줄(완료 조건 ⑭) — 이 초안은 규칙 기반이라 외부 자료를 읽지 않는다. 기대는 출처는 **사용자가 `참고 URL` 칸에 적어 반영한 주소**뿐이고(앱은 주소를 열지 않는다), 없으면 '사실·가격·날짜는 직접 확인' 을 말한다.
        확인 필요는 확인 권장의 줄 수(이 글에만 해당 + 모든 글 공통)와 그중 이 글에만 해당하는 수다."""
        urls = [line for line in str((self.result.options or {}).get("urls", "")).splitlines() if line.strip()]
        source = T["drf_chk_source_some"].format(n=len(urls)) if urls else T["drf_chk_source_none"]
        return T["drf_chk_status"].format(source=source, total=len(specific) + len(common), specific=len(specific))

    def _copy_button(self, key, text):
        done = key in self.copied
        return {"key": key, "text": self.copied_text(key) if done else text, "copied": done, "enabled": self.state == "normal" and not self.busy, "a11y": text}

    def _actions(self):
        enabled = self.state == "normal" and not self.busy
        url, why = self.open_info()
        buttons = []
        for key, text, kind in (("title", T["drf_copy_title"], "secondary"), ("body", T["drf_copy_body"], "secondary"), ("all", T["drf_copy_all"], "primary")):
            done = key in self.copied
            buttons.append({"key": key, "text": self.copied_text(key) if done else text, "kind": kind, "copied": done, "enabled": enabled, "a11y": text, "tip": T["drf_copy_tip_" + key]})
        buttons.append({"key": "open", "text": T["drf_open_naver"], "kind": "ghost", "copied": False, "enabled": enabled and bool(url), "a11y": T["drf_open_naver"], "tip": why or T["drf_open_tip"], "url": url})
        return {"a11y": T["drf_actions_a11y"], "buttons": buttons}

    def editor_status(self):
        """편집기 아래 줄 — 글자 수와 고친 정도. 글자를 칠 때마다 이것만 다시 만들어 보인다(화면 전체를 다시 그리지 않는다)."""
        body = self.draft_body()
        count = rules.count_text(self.body)
        edited = self.title_edited() or self.body_edited()
        changed = rules.changed_chars(body.selected_title, body.titles, self.title, body.body_text, self.body) if body is not None and edited else 0
        return {"count_text": T["drf_count"].format(n=count[0], m=count[1]), "edit_text": T["drf_edit_some"].format(n=changed) if edited else T["drf_edit_none"], "edited": edited}

    def _normal(self):
        result = self.result
        names = dict(result.blog_names)
        title_pick = self.title_picks()
        return {
            "context": {"candidate": T["drf_ctx_candidate"].format(title=rules.shown(self.target.title, 80)) if self.target is not None and self.target.title else "",
                        "made": T["drf_ctx_made"].format(blog=rules.shown(names.get(result.blog) or result.blog, 30), post_type=result.post_type), "a11y": T["drf_ctx_a11y"]},
            "options": self._options(),
            "title_box": {"label": T["drf_title_label"], "value": self.title, "a11y": T["drf_title_input_a11y"], "picks_title": T["drf_title_picks"], "picks": title_pick, "edited": self.title_edited(),
                          "editable": not self.locked, "locked_text": T["drf_edit_locked"] if self.locked else ""},
            "editor": {"label": T["drf_body_label"], "value": self.body, "a11y": T["drf_body_a11y"], "min_height": rules.EDITOR_MIN_HEIGHT, "editable": not self.locked, "locked_text": T["drf_edit_locked"] if self.locked else "", **self.editor_status()},
            "side": self._side(), "actions": self._actions(),
        }

    def view(self, diag_text=""):
        state = self.state
        vm = {"state": state, "busy": self.busy, **self._head(), **self._sample(), "notice": {"level": self.notice[0], "text": self.notice[1]} if self.notice else None,
              "loading": {"text": T["drf_loading"], "a11y": T["drf_loading_a11y"]},
              "error": {"title": T["drf_error_title"], "desc": T["drf_error_desc"], "button": T["drf_error_btn"], "diag": diag_text, "user": getattr(self.failure, "user_message", "") if self.failure else ""},
              "empty": self._empty(), "refused": self._refused(), "notfound": {"title": T["drf_notfound_title"], "desc": T["drf_notfound_desc"], "button": T["drf_to_topics"]},
              "normal": None}
        if state == "normal" and self.result is not None:
            vm["normal"] = self._normal()
        return vm
