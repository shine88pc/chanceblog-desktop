"""블로그 관리 화면의 상태·동작·뷰모델(P4b) — 순수 파이썬(화면 도구를 모른다). Qt 화면은 `view()` 가 만든 딕셔너리를 그리기만 한다: 어떤 칸이 비었는지·무엇이 바뀌었는지·어느 단추를 켤지·어떤 문장을 보일지는 여기서 정한다.

흐름과 규칙:
  · **읽기와 쓰기를 가른다**: 화면을 열고(`start_load`) 슬롯을 고르고 칸을 고치는 것은 파일에 닿지 않는다. 파일에 쓰는 일은 `start_save`·`start_clone`·`start_clear` 셋뿐이고 사용자가 저장·복제·삭제(확인창)를 눌렀을 때만 불린다(공급자의 쓰기 메서드 — 작업 스레드에서).
  · **입력은 지워지지 않는다**: 고친 값(초안)은 슬롯마다 이 상태가 들고 있다 — 저장이 실패해도(낡은 판·잠금·읽기 전용·디스크 가득·칸 오류) 그대로이고, 슬롯을 옮겼다 돌아와도 남는다. 성공하면 그 슬롯의 초안만 비운다.
  · 칸 옆 오류는 **고친 칸이나 저장을 시도한 뒤에만** 보인다(처음 보는 빈 등록 칸이 빨갛게 시작하지 않는다). 저장 단추는 바뀐 것이 있을 때 켜지고, 칸에 문제가 있으면 서비스를 부르지 않고 문제 칸을 알린다.
  · 다른 곳이 먼저 바꿔(낡은 판) 저장이 거절되면 최신 내용을 다시 읽고(읽기만) 초안은 그대로 둔다 — 확인한 뒤 다시 저장한다. 초안은 **고친 칸만** 들고 있어 안 고친 칸은 다시 읽은 최신 값을 따른다(다른 곳이 바꾼 칸을 낡은 값으로 되돌려 쓰지 않는다).
  · 오류 문장은 쉬운 말뿐이다(파이썬 목록·내부 예외·오류 코드·경로 없음). 코드는 읽기 오류의 접힌 '진단 정보'에만 있다.
실제 블로그 이름·아이디는 이 코드에 없다(저장된 값을 보이기만 하고, 보일 때는 비밀 모양을 가린 뒤 줄인다).
"""
from __future__ import annotations

from . import blog_form as bf
from .blogs import BlogFailure
from .jobs import JobFailure
from .text import T

LOAD_KEY = "blogs-load"                                      # 프로필을 읽는 작업의 이름(홈·설정 읽기와 따로 돈다)
WRITE_KEY = "blogs-write"                                    # 저장·복제·삭제 작업의 이름 — 한 번에 하나(중복 클릭은 거절)
DEFAULT_SELECTED = "naver_a"
LIST_STATES = ("loading", "normal", "error")
FAILURE_TEXT = {"conflict": "blogs_fail_conflict", "busy": "blogs_fail_busy", "invalid": "blogs_fail_invalid", "disk": "blogs_fail_disk", "io": "blogs_fail_io", "corrupt": "blogs_fail_corrupt",
                "other": "blogs_fail_other"}


class BlogsController:
    def __init__(self, provider, runner):
        self.provider, self.runner = provider, runner
        self.state = "loading"
        self.data = None
        self.failure = None
        self.failed_at = None
        self.selected = DEFAULT_SELECTED
        self.drafts = {}                                     # 슬롯 → {고친 칸 이름: 입력값}(고친 칸만 — 안 고친 칸은 늘 저장된 최신 값을 따른다)
        self.touched = {}                                    # 슬롯 → 사용자가 고친 칸 이름들
        self.submitted = set()                               # 저장을 시도한 슬롯(그 슬롯은 모든 칸의 오류를 보인다)
        self.service_problems = {}                           # 슬롯 → {칸 이름: 문제 이름} — 서비스가 저장을 거절하며 알려 준 칸(그 칸을 다시 고치면 지운다)
        self.notice = None                                   # (수준, 글) — 마지막 동작의 결과(저장했어요·실패 이유 …)
        self.pending = None                                  # 돌고 있는 쓰기: {"kind", "key", "target"}
        self.reload_after_conflict = False
        self.load_count = 0

    # ---- 읽기(파일·폴더를 만들지 않는다) ----
    @property
    def loading(self):
        return self.runner.running(LOAD_KEY)

    @property
    def busy(self):
        return self.runner.running(WRITE_KEY)

    def start_load(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """프로필을 작업 스레드에서 읽는다 — 이미 읽는 중이면 None. 처음이거나 오류 뒤에는 '읽는 중' 모습이 되고, 보이는 내용이 있으면 그대로 둔 채 새 값이 오면 바꾼다. 쓰는 중에는 읽지 않는다."""
        if self.busy:
            return None
        job = self.runner.start(LOAD_KEY, self.provider.load_blogs, on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.load_count += 1
        if self.data is None or self.state == "error":
            self.state = "loading"
        return job

    def apply_loaded(self, data):
        self.data, self.failure = data, None
        self.state = "normal"
        by_key = data.by_key()
        if self.selected not in by_key:
            self.selected = DEFAULT_SELECTED
        if self.reload_after_conflict:
            self.reload_after_conflict = False
            self.notice = ("warning", T["blogs_stale_reloaded"])
        return True

    def apply_load_failed(self, failure, when=None):
        """읽기가 실패했다 — 이전에 보이던 내용은 지우지 않는다(다시 읽으면 이어서 쓴다). 상태에는 비밀 모양을 가린 글만 남긴다."""
        from .app_state import clean_failure
        self.failure, self.failed_at = clean_failure(failure), when
        self.reload_after_conflict = False
        self.state = "error"

    def apply_unexpected(self, error, when=None):
        """화면 스레드의 슬롯에서 예상하지 못한 예외가 났다 — 받아 둔 값을 버리고 오류 상태로(쉬운 문장 + 예외 이름만 진단 정보에). 입력한 초안은 남긴다."""
        from .app_state import clean_failure
        self.data, self.pending = None, None
        self.failure, self.failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.state = "error"

    def apply_cancelled(self):
        self.state = "normal" if self.data is not None else "error"

    # ---- 값 ----
    def slot_map(self):
        return self.data.by_key() if self.data is not None else {}

    def base_raw(self, key):
        return self.slot_map()[key].raw()

    def values(self, key):
        """그 슬롯의 지금 입력값 — 저장된(가장 최근에 읽은) 값 위에 고친 칸만 덮어쓴다. 안 고친 칸은 다시 읽어 온 최신 값을 따른다."""
        draft = self.drafts.get(key)
        return {**self.base_raw(key), **draft} if draft else self.base_raw(key)

    def dirty_names(self, key):
        return bf.dirty_names(key, self.base_raw(key), self.values(key)) if self.data is not None and key in self.slot_map() else ()

    def is_dirty(self, key):
        return bool(self.dirty_names(key))

    def extra_tags(self, key):
        """저장된 협찬 분야 중 이름표가 없는 값(손으로 고친 파일에서 온 것) — 화면이 못 바꾸므로 저장해도 그대로 보관된다."""
        return tuple(tag for tag in self.slot_map()[key].monetization_focus if tag not in bf.TAG_ORDER)

    # ---- 선택·편집(파일에 닿지 않는다) ----
    def select(self, key):
        if key not in bf.SLOTS or self.busy:
            return False
        self.selected, self.notice = key, None
        return True

    def edit(self, name, value):
        """선택한 슬롯의 칸 하나를 고친다. 초안에는 고친 칸만 남기고, 저장된 값과 같아진 칸(다듬은 뜻이 같은 것)은 뺀다 — 모두 빠지면 그 슬롯의 초안을 비운다."""
        key = self.selected
        if self.data is None or self.busy or name not in {spec.name for spec in bf.fields_for(key)}:
            return False
        base = self.base_raw(key)
        draft = dict(self.drafts.get(key, {}))                # 고친 칸만 들고 있는다 — 안 고친 칸은 늘 저장된(최신) 값을 따른다(독립 검증 F1)
        draft[name] = value
        draft = {field: item for field, item in draft.items() if bf.dirty_names(key, base, {**base, field: item})}      # 저장된 값과 같아진 칸은 뺀다
        self.touched.setdefault(key, set()).add(name)
        self.service_problems.get(key, {}).pop(name, None)
        self.notice = None
        if draft:
            self.drafts[key] = draft
        else:
            self.drafts.pop(key, None)
        return True

    def toggle_tag(self, tag):
        """협찬 가능 분야 하나를 켜고 끈다(이름표가 있는 여섯 가지만)."""
        if tag not in bf.TAG_ORDER:
            return False
        current = set(self.values(self.selected).get("monetization_focus", ()))
        current.symmetric_difference_update({tag})
        return self.edit("monetization_focus", tuple(current))

    def revert(self):
        key = self.selected
        if self.busy:
            return False
        for table in (self.drafts, self.touched, self.service_problems):
            table.pop(key, None)
        self.submitted.discard(key)
        self.notice = None
        return True

    # ---- 쓰기(사용자가 눌렀을 때만) ----
    def problems(self, key):
        """그 슬롯의 칸 문제들 `{칸 이름: 문제 이름}` — 입력값을 다듬은 값의 검사 + 서비스가 거절하며 알려 준 칸."""
        found = bf.check_all(key, self.values(key), self.extra_tags(key))
        for name, problem in self.service_problems.get(key, {}).items():
            found.setdefault(name, problem)
        return found

    def start_save(self, **callbacks):
        """저장 — `(상태, 내용)`: `("busy", None)` 이미 쓰는 중 · `("nothing", None)` 바뀐 것이 없음 · `("invalid", 문제들)` 칸에 문제가 있어 서비스를 부르지 않음(그 칸들을 보이게 한다) · `("started", 작업)`."""
        key = self.selected
        if self.data is None or self.busy:
            return "busy", None
        names = self.dirty_names(key)
        if not names:
            return "nothing", None
        problems = bf.check_all(key, self.values(key), self.extra_tags(key))
        if problems:
            self.submitted.add(key)
            self.notice = ("error", T["blogs_save_invalid"])
            return "invalid", problems
        typed = bf.typed_values(key, self.values(key))
        changes = {name: typed[name] for name in names}
        version = self.data.version
        provider = self.provider
        return self._start("save", key, None, lambda progress, cancelled: provider.save_blog(key, changes, version, progress, cancelled), callbacks)

    def clone_info(self, key=None):
        """복제 `(가능한가, 안 되는 이유, 복제해 넣을 슬롯)` — 저장된 값 기준이고, 저장하지 않은 변경이 있으면 먼저 저장하게 한다."""
        key = key or self.selected
        if self.data is None:
            return False, "", None
        allowed, reason, target = bf.clone_state({other: slot.raw() for other, slot in self.slot_map().items()}, key)
        if allowed and self.is_dirty(key):
            return False, T["blogs_clone_unsaved"], target
        return allowed, reason, target

    def start_clone(self, **callbacks):
        key = self.selected
        allowed, _reason, target = self.clone_info(key)
        if self.data is None or self.busy or not allowed:
            return "busy" if self.busy else "unavailable", None
        version, provider = self.data.version, self.provider
        return self._start("clone", key, target, lambda progress, cancelled: provider.clone_blog(key, target, version, progress, cancelled), callbacks)

    def can_clear(self, key=None):
        key = key or self.selected
        return self.data is not None and key in self.slot_map() and not bf.is_empty_values(key, self.base_raw(key))

    def delete_dialog(self):
        """삭제 확인창의 글 — 무엇이 지워지는지·되돌릴 수 없다는 것·후보·초안·발행 기록은 지워지지 않는다는 것(저장된 파일은 이 일이 건드리지 않는다)."""
        slot = self.slot_map().get(self.selected)
        name = bf.shown(slot.display_name, 30) if slot is not None and slot.display_name else T["blogs_del_unnamed"]
        return {"title": T["blogs_del_title"], "body": T["blogs_del_body"].format(name=name), "ok": T["blogs_del_ok"], "cancel": T["blogs_del_cancel"]}

    def start_clear(self, **callbacks):
        """삭제(슬롯 비우기) — 확인창에서 '지우기' 를 눌렀을 때만 불린다. 서비스에는 확인 표시가 진짜 `True` 로 간다."""
        key = self.selected
        if self.data is None or self.busy or not self.can_clear(key):
            return ("busy" if self.busy else "nothing"), None
        version, provider = self.data.version, self.provider
        return self._start("clear", key, None, lambda progress, cancelled: provider.clear_blog(key, version, progress, cancelled), callbacks)

    def _start(self, kind, key, target, work, callbacks):
        job = self.runner.start(WRITE_KEY, work, **callbacks)
        if job is None:
            return "busy", None
        self.pending = {"kind": kind, "key": key, "target": target}
        self.notice = None
        return "started", job

    def apply_write_ok(self, outcome):
        """쓰기가 끝났다 — 쓴 뒤의 상태를 받고 그 슬롯의 초안만 비운다."""
        work, self.pending = self.pending or {"kind": "save", "key": self.selected, "target": None}, None
        self.data = outcome.data
        for key in (work["key"], work["target"]):
            if key is not None:
                for table in (self.drafts, self.touched, self.service_problems):
                    table.pop(key, None)
                self.submitted.discard(key)
        if outcome.kind == "unchanged":
            self.notice = ("info", T["blogs_unchanged"])
        elif work["kind"] == "clone":
            self.selected = work["target"]
            self.notice = ("ok", T["blogs_cloned"])
        else:
            self.notice = ("ok", T["blogs_cleared"] if work["kind"] == "clear" else T["blogs_saved"])

    def apply_write_failed(self, failure):
        """쓰기가 실패했다 — 입력(초안)은 그대로다. 낡은 판이면 `True` 를 돌려줘 화면이 최신 내용을 다시 읽게 한다. 문장은 종류별로 정해진 쉬운 말뿐이다."""
        work, self.pending = self.pending or {"kind": "save", "key": self.selected, "target": None}, None
        kind = failure.kind if isinstance(failure, BlogFailure) else "other"
        problems = failure.problems if isinstance(failure, BlogFailure) else {}
        if problems:
            self.service_problems[work["key"]] = dict(problems)
            self.submitted.add(work["key"])
        self.notice = ("error", T[FAILURE_TEXT.get(kind, "blogs_fail_other")])
        if kind == "conflict":
            self.reload_after_conflict = True
        return kind == "conflict"

    def apply_write_unexpected(self, error):
        self.pending = None
        self.notice = ("error", T["blogs_fail_other"])

    # ---- 뷰모델 ----
    def _field(self, key, spec, values, base, shown):
        problem = shown.get(spec.name, "")
        raw = values.get(spec.name)
        view = {"name": spec.name, "kind": spec.kind, "label": spec.label, "required": spec.required, "required_text": T["blogs_required"] if spec.required else "", "value": raw, "hint": spec.hint(),
                "error": bf.problem_text(spec, problem, raw) if problem else "", "warning": "", "options": [], "extra": "", "disabled": self.busy, "disabled_reason": "", "placeholder": "",
                "changed": spec.name in self.dirty_names(key)}
        if spec.kind in ("line", "ref"):
            view["placeholder"] = T.get("bf_placeholder_" + spec.name, "")
        elif spec.kind == "words":
            view["placeholder"] = T["bf_placeholder_words"]
        elif spec.kind == "path":
            view["placeholder"] = T["bf_placeholder_path"]
        elif spec.name == "language":
            view["options"] = [{"value": code, "label": T["blogs_lang_" + code]} for code in ("ko", "en")]
        elif spec.name == "color_preset":
            view["options"] = [{"value": preset, "label": bf.preset_name(preset), "preset": preset} for preset in bf.PRESET_ORDER]
        elif spec.kind == "multi":
            view["options"] = [{"value": tag, "label": T["bf_tag_" + tag]} for tag in bf.TAG_ORDER]
            extra = self.extra_tags(key)
            view["extra"] = T["bf_extra_tags"].format(n=len(extra)) if extra else ""
        if spec.name == "blog_ref" and not problem:
            same = bf.normalize(spec, raw).casefold()
            if same and any(other != key and slot.blog_ref.casefold() == same for other, slot in self.slot_map().items()):
                view["warning"] = T["bf_warn_same_ref"]
        return view

    def _form(self, key):
        slot = self.slot_map()[key]
        values, base = self.values(key), self.base_raw(key)
        computed = self.problems(key)
        reveal = key in self.submitted
        touched = self.touched.get(key, set())
        shown = {name: problem for name, problem in computed.items() if reveal or name in touched or name in self.service_problems.get(key, {})}
        dirty = self.is_dirty(key)
        sections = []
        for section in bf.SECTIONS:
            fields = [self._field(key, spec, values, base, shown) for spec in bf.fields_for(key) if spec.section == section]
            if section == "basic" and key not in bf.GENERATION_SLOTS:                           # 후보 만들기는 네이버 A·B 만 — 나머지는 꺼진 스위치와 이유(죽은 스위치가 아니라 이유가 있는 꺼짐)
                fields.append({"name": "generation_enabled", "kind": "flag", "label": T["bf_label_generation_enabled"], "required": False, "required_text": "", "value": bool(slot.generation_enabled),
                               "hint": T["bf_hint_generation_off"], "error": "", "warning": "", "options": [], "extra": "", "disabled": True, "disabled_reason": T["bf_hint_generation_off"],
                               "placeholder": "", "changed": False})
            sections.append({"key": section, "title": T["blogs_sec_" + section], "desc": T["blogs_sec_" + section + "_desc"], "fields": fields})
        clone_ok, clone_reason, clone_target = self.clone_info(key)
        busy = self.busy
        actions = [
            {"key": "save", "text": T["blogs_save"], "kind": "primary", "enabled": dirty and not busy, "reason": "" if dirty and not busy else (T["blogs_working"] if busy else T["blogs_save_nothing"])},
            {"key": "revert", "text": T["blogs_revert"], "kind": "secondary", "enabled": dirty and not busy, "reason": "" if dirty and not busy else (T["blogs_working"] if busy else T["blogs_revert_nothing"])},
            {"key": "clone", "text": T["blogs_clone"], "kind": "secondary", "enabled": clone_ok and not busy, "reason": T["blogs_working"] if busy else clone_reason,
             "hint": T["blogs_clone_hint"].format(target=bf.slot_title(clone_target)) if clone_ok and clone_target else ""},
            {"key": "delete", "text": T["blogs_delete"], "kind": "danger", "enabled": self.can_clear(key) and not busy, "reason": T["blogs_working"] if busy else ("" if self.can_clear(key) else T["blogs_delete_empty"])},
        ]
        title = bf.slot_title(key)
        kind = T["blogs_kind_" + bf.KIND_KEY[key]]
        preset = values.get("color_preset") or ""
        return {"key": key, "title": T["blogs_form_edit" if slot.registered else "blogs_form_new"].format(slot=title), "a11y": T["blogs_form_a11y"].format(slot=title),
                "registered": slot.registered, "kind": "" if kind == title else kind, "slot_title": title, "preset_text": T["blogs_card_preset"].format(name=bf.preset_name(preset)) if preset else "",
                "status": {"tone": "ok" if slot.registered else "muted", "text": T["blogs_status_registered" if slot.registered else "blogs_status_empty"]},
                "unsaved": {"tone": "warning", "text": T["blogs_status_unsaved"]} if dirty else None,
                "sections": sections, "actions": actions, "dirty": dirty, "dirty_names": self.dirty_names(key), "saving": busy, "saving_text": T["blogs_saving"],
                "preset": preset, "actions_a11y": T["blogs_actions_a11y"]}

    def _card(self, slot):
        key = slot.key
        registered = slot.registered
        unsaved = self.is_dirty(key)
        title = bf.slot_title(key)
        headline = bf.shown(slot.display_name, 30) if registered else T["blogs_card_empty_title"]
        sub = T["blogs_card_ref"].format(ref=bf.shown(slot.blog_ref, 40)) if registered else T["blogs_card_empty_desc"]
        role = bf.shown(slot.channel_role, 60) if slot.channel_role else bf.shown(" · ".join(slot.main_topics[:3]), 60) if slot.main_topics else ""
        chips = [{"tone": "muted", "text": T["blogs_lang_" + slot.language]}] if registered else []
        if key in bf.GENERATION_SLOTS:
            chips.append({"tone": "ok" if slot.generation_enabled else "muted", "text": T["blogs_gen_on" if slot.generation_enabled else "blogs_gen_off"]})
        else:
            chips.append({"tone": "muted", "text": T["blogs_gen_none"]})
        if unsaved:
            chips.append({"tone": "warning", "text": T["blogs_status_unsaved"]})
        base = T["blogs_card_a11y"].format(slot=title, state=T["blogs_status_registered"], name=headline) if registered else T["blogs_card_a11y_empty"].format(slot=title)
        selected = key == self.selected
        meta = " · ".join(chip["text"] for chip in chips if chip["tone"] != "warning") if registered else ""                # 카드의 마지막 줄 — 언어 · 후보 만들기 상태(저장 전 변경은 카드 윗줄의 배지)
        return {"key": key, "title": title, "kind": T["blogs_kind_" + bf.KIND_KEY[key]], "registered": registered, "headline": headline, "sub": sub, "role": role if registered else "", "chips": chips, "meta": meta,
                "status": {"tone": "ok" if registered else "muted", "text": T["blogs_status_registered" if registered else "blogs_status_empty"]}, "unsaved": unsaved,
                "preset": (slot.color_preset or "") if registered else "", "preset_text": T["blogs_card_preset"].format(name=bf.preset_name(slot.color_preset)) if registered and slot.color_preset else "",
                "selected": selected, "sample": slot.sample, "a11y": T["blogs_card_selected"].format(base=base) if selected else base}

    def view(self, diag_text=""):
        data = self.data
        state = self.state
        banners = []
        if data is not None and data.state == "missing" and not data.sample:
            banners.append(("info", T["blogs_missing_note"]))
        normal = state == "normal" and data is not None
        return {
            "title": T["blogs_title"], "sub": T["blogs_sub"], "refresh": T["blogs_refresh"], "sample": bool(data and data.sample), "sample_tag": T["sample_tag"], "sample_tip": T["blogs_sample_tip"],
            "state": state, "busy": self.busy, "loading": {"text": T["blogs_loading"], "a11y": T["blogs_loading_a11y"]},
            "error": {"title": T["blogs_error_title"], "desc": T["blogs_error_desc"], "button": T["blogs_error_btn"], "diag": diag_text, "user": ""},
            "banners": banners, "notice": {"level": self.notice[0], "text": self.notice[1]} if self.notice else None,
            "list": {"title": T["blogs_list_title"], "desc": T["blogs_list_desc"], "a11y": T["blogs_list_a11y"], "cards": [self._card(slot) for slot in data.slots] if normal else []},
            "selected": self.selected, "form": self._form(self.selected) if normal and self.selected in self.slot_map() else None,
        }
