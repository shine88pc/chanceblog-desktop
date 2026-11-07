"""Seed 관리 화면의 상태·동작·뷰모델 — 순수 파이썬(화면 도구를 모른다). Qt 화면은 `view()`·`drawer_view()` 가 만든 딕셔너리를 그리기만 한다: 어떤 칸이 비었는지·무엇이 바뀌었는지·어느 단추를 켤지·어떤 문장을 보일지는 여기서 정한다.

흐름과 규칙:
  · **읽기와 쓰기를 가른다**: 화면을 열고(`start_load`) 거르고 찾고 고르고 서랍을 열고 칸을 고치는 것은 파일에 닿지 않는다. 파일에 쓰는 일은 `start_state`·`start_bulk`·`start_save`·`start_create`·`start_import_apply` 다섯뿐이고
    사용자가 승인·바꾸기·저장·등록·불러오기를 눌렀을 때만 불린다(공급자의 쓰기 메서드 — 작업 스레드에서). 제안 파일을 읽어 보는 `start_import_preview` 는 읽기뿐이다.
  · **여러 개를 한꺼번에 바꾸거나 제안 파일을 등록하는 일은 확인창이 먼저다**: `bulk_dialog`·`import_dialog` 를 부르지 않고(= 확인창을 보이지 않고) `start_bulk`·`start_import_apply` 를 부르면 아무것도 하지 않는다(`unconfirmed`) —
    확인창을 건너뛰는 코드 실수를 구조로 막는다. 한 씨앗의 상태 바꾸기·고치기는 확인창 없이 저장한다(일반 저장).
  · **입력은 지워지지 않는다**: 고친 값(초안)은 씨앗마다 이 상태가 들고 있다 — 저장이 실패해도(낡은 판·잠금·읽기 전용·디스크 가득·칸 오류) 그대로이고, 서랍을 닫았다 열어도 남는다. 성공하면 그 씨앗의 초안만 비운다.
  · 칸 옆 오류는 **고친 칸이나 저장을 시도한 뒤에만** 보인다. 저장 단추는 바뀐 것이 있을 때 켜지고, 칸에 문제가 있으면 서비스를 부르지 않고 문제 칸을 알린다. 저장하지 않은 변경이 있으면 상태를 바꾸는 단추는 꺼진다(무엇을 승인하는지 헷갈리지 않게).
  · 다른 곳이 먼저 바꿔(낡은 판) 거절되면 최신 내용을 다시 읽고(읽기만) 초안은 그대로 둔다. 오류 문장은 쉬운 말뿐이다(파이썬 목록·내부 예외·오류 코드·경로 없음). 코드는 읽기 오류의 접힌 '진단 정보'에만 있다.
  · **180일 '쉬게 할까요'** 는 목록·서랍에 제안으로 보일 뿐 자동으로 바뀌지 않는다 — 사용자가 '쉬게 하기' 를 눌러야 쉬게 한다.
실제 Seed 낱말·분류는 이 코드에 없다(저장된 값을 보이기만 하고, 보일 때는 비밀 모양을 가린 뒤 줄인다).
"""
from __future__ import annotations

from ...errors import AppError
from ...topics import schedule
from ...topics import seeds as sd
from ...topics import wording
from . import seed_form as sf
from . import seed_rules as rules
from .jobs import JobFailure
from .seeds import SeedFailure
from .text import T

LOAD_KEY = "seeds-load"                                      # Seed 를 읽는 작업의 이름(홈·설정·블로그 읽기와 따로 돈다)
WRITE_KEY = "seeds-write"                                    # 바꾸기·저장·등록·불러오기 작업 — 한 번에 하나(중복 클릭은 거절)
LIST_STATES = ("loading", "normal", "error")
FAILURE_TEXT = {"conflict": "seeds_fail_conflict", "busy": "seeds_fail_busy", "invalid": "seeds_fail_invalid", "disk": "seeds_fail_disk", "io": "seeds_fail_io", "corrupt": "seeds_fail_corrupt",
                "other": "seeds_fail_other"}
STATE_ACTIONS = {"approve": ("proposed", "active"), "rest": ("proposed", "inactive"), "resume": ("inactive", "active")}      # 행동 → (어디서, 어디로) — `rest` 는 사용 중에서도 된다(아래)
SINGLE_DONE = {"approve": "seeds_approved", "rest": "seeds_rested", "resume": "seeds_resumed"}
STATE_TONE = {sd.STATE_PROPOSED: "warning", sd.STATE_ACTIVE: "ok", sd.STATE_INACTIVE: "muted"}                              # 상태 배지의 바탕 — 색만이 아니라 늘 글자가 함께 있다


def _target_of(action, seed):
    """`approve`(승인 전 → 사용 중)·`rest`(승인 전·사용 중 → 쉬는 중)·`resume`(쉬는 중 → 사용 중) 가 그 씨앗에서 갈 상태 — 서비스의 `TRANSITIONS` 가 허용하지 않으면 None."""
    target = {"approve": sd.STATE_ACTIVE, "rest": sd.STATE_INACTIVE, "resume": sd.STATE_ACTIVE}[action]
    return target if target in sd.TRANSITIONS[seed.state] and (action != "approve" or seed.state == sd.STATE_PROPOSED) and (action != "resume" or seed.state == sd.STATE_INACTIVE) else None


class SeedsController:
    def __init__(self, provider, runner):
        self.provider, self.runner = provider, runner
        self.state = "loading"
        self.data = None
        self.failure = None
        self.failed_at = None
        self.status, self.scope, self.importance, self.query = "all", "all", "all", ""
        self.limit = rules.PAGE
        self.more_filters = False
        self.checked = set()                                 # 일괄 변경에 고른 씨앗 번호들(파일에 쓰지 않는다)
        self.drawer = None                                   # None · ("seed", 번호) · ("new", None)
        self.drafts = {}                                     # 씨앗 → {고친 칸 이름: 입력값}(고친 칸만 — 안 고친 칸은 늘 저장된 최신 값을 따른다)
        self.touched = {}                                    # 씨앗 → 사용자가 고친 칸 이름들
        self.submitted = set()                               # 저장을 시도한 씨앗(그 씨앗은 모든 칸의 오류를 보인다)
        self.service_problems = {}                           # 씨앗 → {칸 이름: 문제 이름} — 서비스가 거절하며 알려 준 칸(그 칸을 다시 고치면 지운다)
        self.new_values = None                               # 새 Seed 폼의 입력값(서랍을 처음 열 때 만든다)
        self.new_touched = set()
        self.new_submitted = False
        self.new_problems = {}
        self.notice = None                                   # (수준, 글) — 마지막 동작의 결과
        self.pending = None                                  # 돌고 있는 쓰기: {"kind", …}
        self.reload_after_conflict = False
        self.load_count = 0
        self.bulk_asked = None                               # 확인창을 보인 일괄 변경 (종류, 번호들) — 이것과 같은 일만 쓴다
        self.import_info = None                              # 읽어 본 제안 파일(미리 보기) — 확인창을 보이고 나서야 등록한다
        self.import_asked = False

    # ---- 읽기(파일·폴더를 만들지 않는다) ----
    @property
    def loading(self):
        return self.runner.running(LOAD_KEY)

    @property
    def busy(self):
        return self.runner.running(WRITE_KEY)

    def start_load(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """Seed 를 작업 스레드에서 읽는다 — 이미 읽는 중이거나 쓰는 중이면 None. 처음이거나 오류 뒤에는 '읽는 중' 모습이 되고, 보이는 내용이 있으면 그대로 둔 채 새 값이 오면 바꾼다."""
        if self.busy:
            return None
        job = self.runner.start(LOAD_KEY, self.provider.load_seeds, on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.load_count += 1
        if self.data is None or self.state == "error":
            self.state = "loading"
        return job

    def apply_loaded(self, data):
        self.data, self.failure = data, None
        self.state = "normal"
        found = data.by_id()
        self.checked &= set(found)
        if self.drawer is not None and self.drawer[0] == "seed" and self.drawer[1] not in found:
            self.drawer = None
        for table in (self.drafts, self.touched, self.service_problems):
            for seed_id in [key for key in table if key not in found]:
                table.pop(seed_id)
        self._prune_drafts()
        if self.reload_after_conflict:
            self.reload_after_conflict = False
            self.notice = ("warning", T["seeds_stale_reloaded"])
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
        self.data, self.pending, self.drawer = None, None, None
        self.failure, self.failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.state = "error"

    def apply_cancelled(self):
        self.state = "normal" if self.data is not None else "error"

    # ---- 값 ----
    def seeds(self):
        return self.data.seeds if self.data is not None else ()

    def by_id(self):
        return self.data.by_id() if self.data is not None else {}

    def open_seed(self):
        """서랍이 열려 있는 씨앗(없으면 None)."""
        return self.by_id().get(self.drawer[1]) if self.drawer is not None and self.drawer[0] == "seed" else None

    def edit_fields(self, seed):
        return sf.edit_fields_for(seed)

    def values(self, seed):
        """그 씨앗의 지금 입력값 — 저장된(가장 최근에 읽은) 값 위에 고친 칸만 덮어쓴다. 안 고친 칸은 다시 읽어 온 최신 값을 따른다(독립 검증 F1 — 초안이 저장된 값 전체의 복사본이면
        다른 창·손 편집이 바꾼 '고치지 않은 칸'이 다시 읽은 뒤에도 낡은 값으로 보이고 저장하면 낡은 값으로 되돌려 쓴다)."""
        base, draft = sf.raw_from_seed(seed), self.drafts.get(seed.seed_id)
        return {**base, **draft} if draft else base

    def _prune_drafts(self):
        """다시 읽거나 쓴 뒤 — 초안에서 '저장된 값과 같아진 칸'(다른 창이 같은 값으로 저장했거나 더는 고칠 수 없는 칸)을 뺀다. 칸이 모두 빠지면 그 씨앗의 초안을 비운다.
        남겨 두면 그 칸이 나중에 다른 창에서 또 바뀐 뒤에도 옛 입력이 최신 값을 덮어 '저장 전 변경' 으로 보인다."""
        by_id = self.by_id()
        for seed_id in list(self.drafts):
            seed = by_id.get(seed_id)
            if seed is None:
                self.drafts.pop(seed_id)
                continue
            fields, base = self.edit_fields(seed), sf.raw_from_seed(seed)
            kept = {name: value for name, value in self.drafts[seed_id].items() if sf.dirty_names(fields, base, {**base, name: value})}
            if kept:
                self.drafts[seed_id] = kept
            else:
                self.drafts.pop(seed_id)

    def dirty_names(self, seed):
        return sf.dirty_names(self.edit_fields(seed), sf.raw_from_seed(seed), self.values(seed))

    def is_dirty(self, seed_id):
        seed = self.by_id().get(seed_id)
        return seed is not None and bool(self.dirty_names(seed))

    def problems(self, seed):
        """그 씨앗의 칸 문제들 `{칸 이름: 문제 이름}` — 입력값을 다듬은 값의 검사 + 서비스가 거절하며 알려 준 칸."""
        found = sf.edit_problems(seed, sf.typed_values(self.edit_fields(seed), self.values(seed)))
        for name, problem in self.service_problems.get(seed.seed_id, {}).items():
            found.setdefault(name, problem)
        return found

    def new_dirty(self):
        return self.new_values is not None and any(sf.normalize(sf.CREATE_SPEC[name], self.new_values.get(name)) != sf.normalize(sf.CREATE_SPEC[name], sf.new_raw()[name]) for name in sf.CREATE_SPEC)

    def new_problems_now(self):
        typed = sf.typed_values(sf.CREATE_FIELDS, self.new_values or sf.new_raw())
        found = sf.create_problems(typed, self.seeds())
        names = {spec.name for spec in sf.create_fields_for(self.new_values or sf.new_raw())}
        found = {name: problem for name, problem in found.items() if name in names}
        for name, problem in self.new_problems.items():
            if name in names:
                found.setdefault(name, problem)
        return found

    # ---- 거르기·찾기·고르기·서랍(파일에 닿지 않는다) ----
    def _reset_page(self):
        self.limit = rules.PAGE

    def set_status(self, key):
        if key not in rules.STATUS_KEYS:
            return False
        self.status = key
        self._reset_page()
        return True

    def set_scope(self, key):
        if key != "all" and key not in sf.SCOPE_ORDER:
            return False
        self.scope = key
        self._reset_page()
        return True

    def set_importance(self, key):
        if key != "all" and key not in sd.SEED_TYPES:
            return False
        self.importance = key
        self._reset_page()
        return True

    def set_query(self, text):
        self.query = text if isinstance(text, str) else ""
        self._reset_page()
        return True

    def toggle_more_filters(self):
        self.more_filters = not self.more_filters
        return True

    def reset_filters(self):
        self.status, self.scope, self.importance, self.query = "all", "all", "all", ""
        self._reset_page()
        return True

    def filters_active(self):
        return (self.status, self.scope, self.importance, bool(rules.query_words(self.query))) != ("all", "all", "all", False)

    def show_more(self):
        self.limit += rules.PAGE
        return True

    def found(self):
        """거르기 조건에 맞는 씨앗들(파일 순서)."""
        words = rules.query_words(self.query)
        return [seed for seed in self.seeds() if rules.matches(seed, self.status, self.scope, self.importance, words)]

    def toggle_check(self, seed_id):
        if seed_id not in self.by_id() or self.busy:
            return False
        self.checked.symmetric_difference_update({seed_id})
        return True

    def select_found(self):
        if self.busy:
            return False
        self.checked |= {seed.seed_id for seed in self.found()}
        return True

    def clear_checks(self):
        if self.busy:
            return False
        self.checked.clear()
        return True

    def open_detail(self, seed_id):
        if seed_id not in self.by_id() or self.busy:
            return False
        self.drawer, self.notice = ("seed", seed_id), None
        return True

    def open_new(self):
        if self.data is None or self.busy:
            return False
        if self.new_values is None:
            self.new_values = sf.new_raw()
        self.drawer, self.notice = ("new", None), None
        return True

    def close_drawer(self):
        """서랍을 닫는다(고친 값·새로 쓰던 값은 지우지 않는다). 닫은 서랍의 (종류, 번호)를 돌려준다."""
        opened, self.drawer = self.drawer, None
        return opened

    # ---- 고치기(파일에 닿지 않는다) ----
    def edit(self, name, value):
        """서랍의 칸 하나를 고친다 → `False`(안 됨)·`True`(칸 값만 바뀜 — 화면은 다시 그리지 않고 오류·단추만 바꾼다)·`"structural"`(칸 구성이 바뀜 — 서랍을 다시 그린다).
        씨앗 상세에서는 초안에 고친 칸만 남기고, 저장된 값과 같아진 칸(다듬은 뜻이 같은 것)은 뺀다 — 모두 빠지면 그 씨앗의 초안을 비운다."""
        if self.data is None or self.busy or self.drawer is None:
            return False
        if self.drawer[0] == "new":
            return self._edit_new(name, value)
        seed = self.open_seed()
        if seed is None or name not in {spec.name for spec in self.edit_fields(seed)}:
            return False
        fields, base = self.edit_fields(seed), sf.raw_from_seed(seed)
        draft = dict(self.drafts.get(seed.seed_id, {}))        # 고친 칸만 들고 있는다 — 안 고친 칸은 늘 저장된(최신) 값을 따른다(독립 검증 F1)
        draft[name] = value
        draft = {field: item for field, item in draft.items() if sf.dirty_names(fields, base, {**base, field: item})}      # 저장된 값과 같아진 칸은 뺀다
        self.touched.setdefault(seed.seed_id, set()).add(name)
        self.service_problems.get(seed.seed_id, {}).pop(name, None)
        self.notice = None
        if draft:
            self.drafts[seed.seed_id] = draft
        else:
            self.drafts.pop(seed.seed_id, None)
        return True

    def _edit_new(self, name, value):
        if name not in sf.CREATE_SPEC:
            return False
        before = [spec.name for spec in sf.create_fields_for(self.new_values)]
        self.new_values = {**self.new_values, name: value}
        self.new_touched.add(name)
        self.new_problems.pop(name, None)
        self.notice = None
        return "structural" if [spec.name for spec in sf.create_fields_for(self.new_values)] != before else True

    def toggle_channel(self, code):
        """허용 채널 하나를 켜고 끈다(씨앗 상세의 공통 씨앗, 새 Seed 폼의 소속이 공통일 때)."""
        if code not in sf.CHANNEL_ORDER:
            return False
        values = self.new_values if self.drawer is not None and self.drawer[0] == "new" else self.values(self.open_seed()) if self.open_seed() is not None else None
        if values is None:
            return False
        current = set(values.get("allowed_channels", ()))
        current.symmetric_difference_update({code})
        return self.edit("allowed_channels", tuple(current))

    def revert(self):
        seed = self.open_seed()
        if seed is None or self.busy:
            return False
        for table in (self.drafts, self.touched, self.service_problems):
            table.pop(seed.seed_id, None)
        self.submitted.discard(seed.seed_id)
        self.notice = None
        return True

    # ---- 쓰기(사용자가 눌렀을 때만) ----
    def _start(self, kind, payload, work, callbacks):
        job = self.runner.start(WRITE_KEY, work, **callbacks)
        if job is None:
            return "busy", None
        self.pending = {"kind": kind, **payload}
        self.notice = None
        return "started", job

    def start_save(self, **callbacks):
        """씨앗 상세의 저장 — `(상태, 내용)`: `("busy", None)` 쓰는 중 · `("nothing", None)` 바뀐 것이 없음 · `("invalid", 문제들)` 칸에 문제가 있어 서비스를 부르지 않음 · `("started", 작업)`."""
        seed = self.open_seed()
        if self.data is None or self.busy or seed is None:
            return "busy", None
        names = self.dirty_names(seed)
        if not names:
            return "nothing", None
        fields = self.edit_fields(seed)
        typed = sf.typed_values(fields, self.values(seed))
        problems = sf.edit_problems(seed, typed)
        if problems:
            self.submitted.add(seed.seed_id)
            self.notice = ("error", T["seeds_save_invalid"])
            return "invalid", problems
        changes = {name: typed[name] for name in names}
        version, provider, seed_id = self.data.version, self.provider, seed.seed_id
        return self._start("edit", {"id": seed_id}, lambda progress, cancelled: provider.edit_seed(seed_id, changes, version, progress, cancelled), callbacks)

    def state_info(self, action):
        """씨앗 상세의 상태 행동 `(가능한가, 안 되는 이유)` — 저장하지 않은 변경이 있으면 먼저 저장하게 한다."""
        seed = self.open_seed()
        if seed is None or _target_of(action, seed) is None:
            return False, ""
        if self.busy:
            return False, T["seeds_act_working"]
        if self.is_dirty(seed.seed_id):
            return False, T["seeds_act_unsaved"]
        return True, ""

    def start_state(self, action, **callbacks):
        """승인하기·쉬게 하기·다시 쓰기 — 확인창 없이 저장한다(씨앗 하나). `(상태, 내용)`: `busy`·`unavailable`·`unsaved`(저장하지 않은 변경이 있다)·`started`."""
        seed = self.open_seed()
        if self.data is None or seed is None or action not in STATE_ACTIONS:
            return "unavailable", None
        if self.busy:
            return "busy", None
        target = _target_of(action, seed)
        if target is None:
            return "unavailable", None
        if self.is_dirty(seed.seed_id):
            return "unsaved", None
        version, provider, seed_id = self.data.version, self.provider, seed.seed_id
        return self._start("state", {"id": seed_id, "action": action}, lambda progress, cancelled: provider.set_state(seed_id, target, version, progress, cancelled), callbacks)

    def bulk_info(self, kind):
        """일괄 변경 `(대상 수, 안 되는 이유)` — 고른 씨앗 중 그 일로 바꿀 수 있는 것의 수."""
        if self.data is None or not self.checked:
            return 0, T["seeds_bulk_no_pick"]
        count = len(rules.bulk_ids(self.seeds(), self.checked, kind))
        if self.busy:
            return count, T["seeds_bulk_working"]
        return count, "" if count else T["seeds_bulk_no_target"]

    def bulk_dialog(self, kind):
        """일괄 변경 확인창의 글 — 개수·처음 몇 개 이름·'승인 전 N개를 사용 중으로 바꿉니다'·되돌릴 수 있다는 것·바꾼 뒤 채널별 쓸 수 있는 수. 보인 뒤에만 `start_bulk` 가 쓴다. 바꿀 것이 없으면 None."""
        if self.data is None or kind not in rules.BULK_KINDS:
            return None
        plan = rules.bulk_preview(self.seeds(), self.checked, kind)
        if not plan["count"]:
            return None
        self.bulk_asked = (kind, plan["ids"])
        names = {"proposed": "seeds_bulk_part_proposed", "inactive": "seeds_bulk_part_inactive", "active": "seeds_bulk_part_active"}
        parts = ", ".join(T[names[state]].format(n=number) for state, number in plan["parts"].items() if number)
        lines = [T["seeds_bulk_dlg_" + kind].format(parts=parts)]
        if plan["names"]:
            shown = len(plan["names"])
            lines.append(T["seeds_bulk_names_more" if plan["rest"] else "seeds_bulk_names"].format(shown=shown, names=", ".join(f"‘{name}’" for name in plan["names"]), rest=plan["rest"]))
        lines.append(T["seeds_bulk_effect_" + kind])
        changed = [row for row in plan["channels"] if row["before"] != row["after"]]
        if changed:
            lines.append(T["seeds_bulk_counts"].format(rows=" · ".join(T["seeds_bulk_count_row"].format(name=row["name"], before=row["before"], after=row["after"]) for row in changed)))
        if plan["skipped"]:
            lines.append(T["seeds_bulk_skipped"].format(n=plan["skipped"]))
        lines.append(T["seeds_bulk_all_or_nothing"])
        return {"title": T["seeds_bulk_title"].format(n=plan["count"]), "body": "\n".join(lines), "ok": T["seeds_bulk_ok_" + kind], "cancel": T["seeds_bulk_cancel"], "count": plan["count"]}

    def discard_bulk(self):
        """확인창을 확인 없이 닫았다(취소·Esc) — '확인창을 보였다' 표시를 거둔다."""
        self.bulk_asked = None

    def start_bulk(self, kind, **callbacks):
        """확인창에서 확인을 눌렀을 때만 — 확인창을 보이지 않은(또는 그 뒤에 고른 씨앗이 달라진) 일괄 변경은 아무것도 하지 않는다(`unconfirmed`). 한 번의 쓰기로 전부 바꾸거나 하나도 안 바꾼다."""
        if self.data is None or kind not in rules.BULK_KINDS:
            return "unavailable", None
        if self.busy:
            return "busy", None
        ids = rules.bulk_ids(self.seeds(), self.checked, kind)
        if not ids:
            return "nothing", None
        if self.bulk_asked != (kind, ids):
            return "unconfirmed", None
        self.bulk_asked = None
        target, version, provider = rules.BULK_TARGET[kind], self.data.version, self.provider
        return self._start("bulk", {"kind_of": kind, "ids": ids}, lambda progress, cancelled: provider.set_states(ids, target, version, progress, cancelled), callbacks)

    def start_create(self, **callbacks):
        """새 Seed 등록 — `(상태, 내용)`: `busy`·`invalid`(칸에 문제 — 서비스를 부르지 않는다)·`started`. 등록한 Seed 는 늘 승인 전이다."""
        if self.data is None or self.drawer is None or self.drawer[0] != "new" or self.new_values is None:
            return "unavailable", None
        if self.busy:
            return "busy", None
        problems = self.new_problems_now()
        if problems:
            self.new_submitted = True
            self.notice = ("error", T["seeds_save_invalid"])
            return "invalid", problems
        fields = sf.create_fields_for(self.new_values)
        values = sf.service_values(fields, sf.typed_values(sf.CREATE_FIELDS, self.new_values))
        version, provider = self.data.version, self.provider
        return self._start("create", {}, lambda progress, cancelled: provider.create_seed(values, version, progress, cancelled), callbacks)

    # ---- 제안 파일 ----
    def start_import_preview(self, path, **callbacks):
        """제안 파일을 읽어 미리 본다(읽기뿐 — 아무것도 쓰지 않는다). 쓰는 작업과 같은 이름으로 돌아 한 번에 하나만 돈다."""
        if self.data is None or not path:
            return "unavailable", None
        if self.busy:
            return "busy", None
        provider, source = self.provider, str(path)
        self.import_info, self.import_asked = None, False
        started = self._start("import_preview", {}, lambda progress, cancelled: provider.preview_import(source, progress, cancelled), callbacks)
        if started[0] == "started":
            self.notice = ("info", T["seeds_imp_reading"])                 # 읽는 동안 알림 줄에 '읽는 중' 을 보인다(끝나면 확인창이 뜬다)
        return started

    def import_dialog(self):
        """제안 파일 확인창의 글 — 개수·건너뜀·거절 이유·채널별 쓸 수 있게 될 수. 등록할 수 있으면 `ok` 가 '승인 전으로 등록' 이고(`can_apply`), 읽을 수 없는 씨앗이 있거나 새 씨앗이 없으면 '닫기' 하나뿐이다."""
        info = self.import_info
        if info is None:
            return None
        names = lambda rows: "; ".join(T["seeds_imp_reason_row"].format(name=sf.shown(name, 30), reason=sf.shown(reason, 80)) for name, reason in rows[:rules.REASONS_SHOWN])    # noqa: E731
        lines = [T["seeds_imp_counts"].format(total=info.total, new=info.new_count, skipped=len(info.skipped), rejected=len(info.rejected), existing=info.existing)]
        for title, rows in ((T["seeds_imp_title_rejected"], info.rejected), (T["seeds_imp_title_skipped"], info.skipped)):
            if rows:
                more = len(rows) - rules.REASONS_SHOWN
                lines.append(T["seeds_imp_reasons"].format(title=title, rows=names(rows) + (" " + T["seeds_imp_more"].format(n=more) if more > 0 else "")))
        can = not info.blocked and info.new_count > 0
        if info.blocked:
            title, ok, cancel = T["seeds_imp_title_blocked"], T["seeds_imp_close"], None
            lines.append(T["seeds_imp_blocked"])
        elif not info.new_count:
            title, ok, cancel = T["seeds_imp_title_none"], T["seeds_imp_close"], None
            lines.append(T["seeds_imp_none"])
        else:
            title, ok, cancel = T["seeds_imp_title"], T["seeds_imp_ok"], T["seeds_imp_cancel"]
            lines.append(T["seeds_imp_all_proposed"])
            lines.append(T["seeds_imp_channels"].format(rows=" · ".join(T["seeds_imp_channel_row"].format(name=sf.channel_name(code), n=number, gen=rules.generation_text(enabled)) for code, number, enabled in info.per_channel)))
        self.import_asked = can
        return {"title": title, "body": "\n".join(lines), "ok": ok, "cancel": cancel, "can_apply": can}

    def discard_import(self):
        self.import_info, self.import_asked = None, False

    def start_import_apply(self, **callbacks):
        """확인창에서 '승인 전으로 등록' 을 눌렀을 때만 — 미리 본 새 씨앗을 모두 승인 전으로 한 번에 등록한다. 확인창을 보이지 않았거나 읽을 수 없는 씨앗이 있으면 아무것도 하지 않는다(`unconfirmed`)."""
        info = self.import_info
        if self.data is None or info is None or info.blocked or not info.new_count:
            return "nothing", None
        if self.busy:
            return "busy", None
        if not self.import_asked:
            return "unconfirmed", None
        self.import_asked = False
        provider = self.provider
        return self._start("import_apply", {"count": info.new_count}, lambda progress, cancelled: provider.apply_import(info, progress, cancelled), callbacks)

    # ---- 쓰기 결과 ----
    def apply_write_ok(self, outcome):
        """쓰기(또는 미리 보기)가 끝났다 — 쓴 뒤의 상태를 받고 그 씨앗의 초안만 비운다."""
        work, self.pending = self.pending or {"kind": "edit", "id": None}, None
        kind = work["kind"]
        if outcome.kind == "preview":
            self.import_info, self.import_asked, self.notice = outcome.preview, False, None
            return
        self.data = outcome.data
        if kind == "edit":
            for table in (self.drafts, self.touched, self.service_problems):
                table.pop(work["id"], None)
            self.submitted.discard(work["id"])
        elif kind == "bulk":
            self.checked -= set(work["ids"])
        elif kind == "create":
            self.new_values, self.new_touched, self.new_submitted, self.new_problems = None, set(), False, {}
            self.drawer = ("seed", outcome.changed[0]) if outcome.changed else None
        elif kind == "import_apply":
            self.import_info, self.import_asked = None, False
            self.status = "proposed"
            self._reset_page()
        found = self.by_id()
        self.checked &= set(found)
        self._prune_drafts()
        if outcome.kind == "unchanged":
            self.notice = ("info", T["seeds_unchanged"])
        elif kind == "state":
            self.notice = ("ok", T[SINGLE_DONE[work["action"]]])
        elif kind == "bulk":
            self.notice = ("ok", T["seeds_bulk_done_" + work["kind_of"]].format(n=len(outcome.changed)))
        elif kind == "create":
            self.notice = ("ok", T["seeds_created"])
        elif kind == "import_apply":
            self.notice = ("ok", T["seeds_imported"].format(n=len(outcome.changed)))
        else:
            self.notice = ("ok", T["seeds_saved"])

    def apply_write_failed(self, failure):
        """쓰기가 실패했다 — 입력(초안)은 그대로다. 낡은 판이면 `True` 를 돌려줘 화면이 최신 내용을 다시 읽게 한다. 문장은 종류별로 정해진 쉬운 말뿐이다."""
        work, self.pending = self.pending or {"kind": "edit", "id": None}, None
        kind = failure.kind if isinstance(failure, SeedFailure) else "other"
        problems = failure.problems if isinstance(failure, SeedFailure) else {}
        if work["kind"] == "import_preview":
            self.import_info, self.import_asked = None, False
            self.notice = ("error", T["seeds_imp_failed"] if kind in ("invalid", "corrupt", "other") else T[FAILURE_TEXT.get(kind, "seeds_fail_other")])
            return False
        if problems and work["kind"] == "edit" and work.get("id"):
            self.service_problems[work["id"]] = dict(problems)
            self.submitted.add(work["id"])
        elif problems and work["kind"] == "create":
            self.new_problems = dict(problems)
            self.new_submitted = True
        self.notice = ("error", T[FAILURE_TEXT.get(kind, "seeds_fail_other")])
        if kind == "conflict":
            self.reload_after_conflict = True
        return kind == "conflict"

    def apply_write_unexpected(self, error):
        self.pending = None
        self.notice = ("error", T["seeds_fail_other"])

    # ---- 뷰모델 ----
    def _field(self, spec, values, shown, *, changed, seed=None):
        problem = shown.get(spec.name, "")
        raw = values.get(spec.name)
        view = {"name": spec.name, "kind": spec.kind, "label": spec.label, "required": spec.required, "required_text": T["blogs_required"] if spec.required else "", "value": raw, "hint": spec.hint(),
                "error": sf.problem_text(spec, problem, raw) if problem else "", "warning": "", "options": [], "extra": "", "disabled": self.busy, "disabled_reason": "", "placeholder": "", "changed": changed}
        if spec.kind == "line":
            view["placeholder"] = T.get("sf_placeholder_" + spec.name, T["sf_placeholder_name"] if spec.name in ("major", "minor") else "")
        elif spec.kind == "words":
            view["placeholder"] = T["sf_placeholder_words"]
        elif spec.name == "seed_type":
            view["options"] = [{"value": kind, "label": sf.importance_name(kind)} for kind in sf.IMPORTANCE_CREATE]
        elif spec.name == "target_type":
            view["options"] = [{"value": kind, "label": sf.target_name(kind)} for kind in sf.TARGET_ORDER]
        elif spec.name == "scope":
            view["options"] = [{"value": scope, "label": sf.scope_name(scope)} for scope in sf.SCOPE_ORDER]
        elif spec.name == "sponsor_tag":
            view["options"] = [{"value": tag, "label": sf.tag_name(tag)} for tag in sf.TAG_ORDER]
        elif spec.name == "allowed_channels":
            view["options"] = [{"value": code, "label": sf.channel_name(code)} for code in sf.CHANNEL_ORDER]
            if seed is not None and seed.state == sd.STATE_ACTIVE and changed:
                view["warning"] = T["sf_warn_active_channels"]
        return view

    def _info_rows(self, seed):
        none = T["seeds_info_none"]
        channels_text = sf.channel_name(seed.scope) if seed.scope != sd.SCOPE_COMMON else ", ".join(sf.channel_name(code) for code in seed.allowed_channels)
        if seed.scope != sd.SCOPE_COMMON:
            channels_text = T["seeds_info_channel_only"].format(name=channels_text)
        rows = [(T["seeds_info_scope"], sf.scope_name(seed.scope)), (T["seeds_info_importance"], sf.importance_name(seed.seed_type) + (" · " + T["seeds_flag_priority"] if seed.priority else "")),
                (T["seeds_info_target"], sf.target_name(seed.target_type)), (T["seeds_info_channels"], channels_text),
                (T["seeds_info_tag"], sf.tag_name(seed.sponsor_tag) if seed.sponsor_tag else none), (T["seeds_info_registered"], seed.registered_on),
                (T["seeds_info_since"], seed.active_since or none), (T["seeds_info_selected"], seed.last_selected_on or T["seeds_info_unused"])]
        return [{"label": label, "value": value, "missing": value in (none, T["seeds_info_unused"])} for label, value in rows]

    @staticmethod
    def _day_text(text, recurrence):
        if not isinstance(text, str):
            return T["seeds_info_none"]
        parts = text.split("-")
        try:
            return f"매월 {int(parts[0])}일" if recurrence == schedule.RECURRENCE_MONTHLY else f"{int(parts[0])}월 {int(parts[1])}일"
        except (ValueError, IndexError):
            return sf.shown(text, 20)

    def _schedule(self, seed):
        """계절 Seed 의 일정 — 보여 주기만 하고 고치지 않는다. 일정이 없는 계절 Seed 는 None."""
        if seed.seed_type != sd.SEED_SEASONAL or seed.publish_from is None:
            return None
        day = lambda text: self._day_text(text, seed.recurrence)  # noqa: E731
        try:
            state = wording.SEASONAL_STATE_KO.get(schedule.seasonal_state(seed, self.data.today)) if self.data is not None and self.data.today else None
        except AppError:
            state = None
        peak = T["seeds_sched_range"].format(first=day(seed.peak_period[0]), last=day(seed.peak_period[1])) if seed.peak_period else T["seeds_info_none"]
        rows = [(T["seeds_sched_prepare"], day(seed.prepare_from)), (T["seeds_sched_publish"], T["seeds_sched_range"].format(first=day(seed.publish_from), last=day(seed.publish_until))),
                (T["seeds_sched_peak"], peak), (T["seeds_sched_repeat"], wording.RECURRENCE_KO.get(seed.recurrence, T["seeds_info_none"])), (T["seeds_sched_state"], state or T["seeds_info_none"])]
        return {"title": T["seeds_sched_title"], "rows": [{"label": label, "value": value, "missing": value == T["seeds_info_none"]} for label, value in rows], "note": T["seeds_sched_note"]}

    def _detail_actions(self, seed, dirty, saving):
        """행동 줄 — 주요 행동 하나(승인 전: 승인하기 · 사용 중: 저장 · 쉬는 중: 다시 쓰기)와 보조·3차 행동. 상태를 바꾸는 행동은 저장하지 않은 변경이 있으면 꺼진다."""
        def state_action(key, text, kind, hint=""):
            ok, reason = self.state_info(key)
            return {"key": key, "text": text, "kind": kind, "enabled": ok and not saving, "reason": "" if ok else reason, "hint": hint if ok else ""}

        save = {"key": "save", "text": T["seeds_act_save"], "kind": "primary" if seed.state == sd.STATE_ACTIVE else "secondary", "enabled": dirty and not saving,
                "reason": "" if dirty and not saving else (T["seeds_act_working"] if saving else T["seeds_act_nothing"])}
        revert = {"key": "revert", "text": T["seeds_act_revert"], "kind": "tertiary", "enabled": dirty and not saving, "reason": "" if dirty and not saving else (T["seeds_act_working"] if saving else T["seeds_act_revert_nothing"])}
        if seed.state == sd.STATE_PROPOSED:
            return [state_action("approve", T["seeds_act_approve"], "primary", T["seeds_act_approve_hint"]), state_action("rest", T["seeds_act_rest_proposed"], "secondary", T["seeds_act_rest_proposed_hint"]), save, revert]
        if seed.state == sd.STATE_ACTIVE:
            return [save, state_action("rest", T["seeds_act_rest"], "secondary"), revert]
        return [state_action("resume", T["seeds_act_resume"], "primary"), save, revert]

    def _detail_drawer(self, seed):
        values, saving = self.values(seed), self.busy
        computed = self.problems(seed)
        touched = self.touched.get(seed.seed_id, set())
        reveal = seed.seed_id in self.submitted
        shown = {name: problem for name, problem in computed.items() if reveal or name in touched or name in self.service_problems.get(seed.seed_id, {})}
        dirty_names = self.dirty_names(seed)
        dirty = bool(dirty_names)
        idle = self.data.idle_days().get(seed.seed_id) if self.data is not None else None
        notes = [T["seeds_stateline_" + seed.state]]
        if seed.needs_region:
            notes.append(T["seeds_info_region"])
        if seed.brand_case:
            notes.append(T["seeds_info_brand"])
        if idle is not None:
            notes.append(T["seeds_idle_note"].format(days=idle))
        fields = [self._field(spec, values, shown, changed=spec.name in dirty_names, seed=seed) for spec in self.edit_fields(seed)]
        title = sf.shown(seed.keyword, 60)
        return {"kind": "seed", "id": seed.seed_id, "title": T["seeds_detail_title"], "a11y": T["seeds_detail_a11y"], "close": T["drawer_close"], "heading": title,
                "path": T["seeds_row_path"].format(major=sf.shown(seed.major, 30), minor=sf.shown(seed.minor, 30)), "status": {"tone": STATE_TONE[seed.state], "text": sf.state_name(seed.state)},
                "unsaved": {"tone": "warning", "text": T["seeds_flag_unsaved"]} if dirty else None, "idle": idle is not None, "sample": bool(self.data and self.data.sample), "sample_tag": T["sample_tag"],
                "info": self._info_rows(seed), "notes": notes, "schedule": self._schedule(seed), "fields": fields, "actions": self._detail_actions(seed, dirty, saving), "dirty": dirty, "saving": saving,
                "saving_text": T["seeds_saving"], "actions_a11y": T["seeds_actions_a11y"], "reason_title": T["sf_label_reason"]}

    def _new_drawer(self):
        values = self.new_values or sf.new_raw()
        computed = self.new_problems_now()
        shown = {name: problem for name, problem in computed.items() if self.new_submitted or name in self.new_touched or name in self.new_problems}
        fields = [self._field(spec, values, shown, changed=False) for spec in sf.create_fields_for(values)]
        saving = self.busy
        actions = [{"key": "create", "text": T["seeds_act_create"], "kind": "primary", "enabled": not saving, "reason": T["seeds_act_working"] if saving else "", "hint": ""},
                   {"key": "cancel", "text": T["seeds_act_cancel"], "kind": "tertiary", "enabled": not saving, "reason": T["seeds_act_working"] if saving else "", "hint": ""}]
        return {"kind": "new", "id": "", "title": T["seeds_new_title"], "a11y": T["seeds_new_a11y"], "close": T["drawer_close"], "heading": "", "path": "", "status": None, "unsaved": None, "idle": False,
                "sample": bool(self.data and self.data.sample), "sample_tag": T["sample_tag"], "info": [], "notes": [T["seeds_new_note"]], "schedule": None, "fields": fields, "actions": actions,
                "dirty": self.new_dirty(), "saving": saving, "saving_text": T["seeds_saving"], "actions_a11y": T["seeds_actions_a11y"], "reason_title": ""}

    def drawer_view(self):
        """서랍(상세·새 Seed)의 뷰모델 — 열려 있지 않거나 읽은 내용이 없으면 None."""
        if self.data is None or self.drawer is None or self.state != "normal":
            return None
        if self.drawer[0] == "new":
            return self._new_drawer()
        seed = self.open_seed()
        return self._detail_drawer(seed) if seed is not None else None

    def _row(self, seed, idle):
        title = sf.shown(seed.keyword, 60)
        status = {"tone": STATE_TONE[seed.state], "text": sf.state_name(seed.state)}
        flags = []
        if seed.priority:
            flags.append(T["seeds_flag_priority"])
        if seed.needs_region:
            flags.append(T["seeds_flag_region"])
        if seed.brand_case:
            flags.append(T["seeds_flag_brand"])
        unsaved = self.is_dirty(seed.seed_id)
        base = T["seeds_row_a11y"].format(title=title, status=status["text"], scope=sf.scope_name(seed.scope), importance=sf.importance_name(seed.seed_type))
        a11y = T["seeds_row_a11y_idle"].format(base=base) if idle is not None else base
        if unsaved:
            a11y = T["seeds_row_a11y_unsaved"].format(base=a11y)
        names = ", ".join(sf.channel_name(code) for code in seed.allowed_channels)
        return {"id": seed.seed_id, "title": title, "path": T["seeds_row_path"].format(major=sf.shown(seed.major, 30), minor=sf.shown(seed.minor, 30)), "status": status,
                "meta": T["seeds_row_meta"].format(scope=sf.scope_name(seed.scope), importance=sf.importance_name(seed.seed_type), target=sf.target_name(seed.target_type)),
                "channels": T["seeds_row_channels"].format(names=names), "flags": flags, "idle": idle is not None, "idle_text": T["seeds_idle_badge"] if idle is not None else "", "unsaved": unsaved,
                "unsaved_text": T["seeds_flag_unsaved"], "checked": seed.seed_id in self.checked, "check_a11y": T["seeds_check_a11y"].format(title=title), "a11y": a11y,
                "selected": self.drawer == ("seed", seed.seed_id)}

    def _summary(self, data):
        counts = rules.status_counts(data.seeds)
        proposed = counts[sd.STATE_PROPOSED]
        generation = data.generation_map()
        rows = rules.channel_rows(data.seeds, data.generation)
        return {"a11y": T["seeds_sum_a11y"], "proposed": {"tone": "warning" if proposed else "muted", "text": T["seeds_sum_proposed"].format(n=proposed) if proposed else T["seeds_sum_no_proposed"], "count": proposed},
                "chips": [{"tone": "ok", "text": T["seeds_sum_active"].format(n=counts[sd.STATE_ACTIVE])}, {"tone": "muted", "text": T["seeds_sum_inactive"].format(n=counts[sd.STATE_INACTIVE])},
                          {"tone": "muted", "text": T["seeds_sum_total"].format(n=counts["all"])}], "counts": counts,
                "channels": {"caption": T["seeds_channels_caption"], "a11y": T["seeds_channels_a11y"], "unknown": T["seeds_profiles_unknown"] if any(flag is None for flag in generation.values()) else "",
                             "rows": [self._channel_chip(row) for row in rows]}}

    @staticmethod
    def _channel_chip(row):
        """채널 한 곳의 칩 — '네이버 A 3개 · 후보 생성 켜짐'(색은 바탕뿐이고 글자가 늘 함께 있다)."""
        gen = rules.generation_text(row["generation"])
        return {"key": row["key"], "count": row["count"], "generation": {"tone": "ok" if row["generation"] is True else "muted" if row["generation"] is False else "warning", "text": gen},
                "chip": {"tone": "ok" if row["generation"] is True else "muted" if row["generation"] is False else "warning", "text": T["seeds_channel_chip"].format(name=row["name"], n=row["count"], gen=gen)},
                "a11y": T["seeds_channel_a11y"].format(name=row["name"], n=row["count"], gen=gen)}

    def _filters(self, data, found):
        status_counts = rules.status_counts(data.seeds)
        scope_counts = rules.facet_counts(data.seeds, "scope", sf.SCOPE_ORDER)
        importance_counts = rules.facet_counts(data.seeds, "seed_type", sd.SEED_TYPES)
        status_labels = {"all": T["seeds_all"], "proposed": T["seeds_status_proposed"], "active": T["seeds_status_active"], "inactive": T["seeds_status_inactive"]}
        scope_labels = {"all": T["seeds_scope_all"], **{code: sf.scope_name(code) for code in sf.SCOPE_ORDER}}
        importance_labels = {"all": T["seeds_importance_all"], **{kind: sf.importance_name(kind) for kind in sd.SEED_TYPES}}
        chips = lambda keys, labels, counts, current: [{"key": key, "label": labels[key], "count": counts[key], "active": key == current} for key in keys]    # noqa: E731
        more_open = self.more_filters or self.scope != "all" or self.importance != "all"
        shown = min(len(found), self.limit)
        return {"a11y": T["seeds_filter_a11y"], "status_title": T["seeds_filter_status"], "status": chips(rules.STATUS_KEYS, status_labels, status_counts, self.status),
                "query": {"label": T["seeds_search_label"], "placeholder": T["seeds_search_placeholder"], "value": self.query},
                "more": {"text": T["seeds_filter_less" if more_open else "seeds_filter_more"], "open": more_open},
                "scope_title": T["seeds_filter_scope"], "scope": chips(("all", *sf.SCOPE_ORDER), scope_labels, scope_counts, self.scope),
                "importance_title": T["seeds_filter_importance"], "importance": chips(("all", *sd.SEED_TYPES), importance_labels, importance_counts, self.importance),
                "result": T["seeds_filter_result"].format(shown=shown, found=len(found), total=len(data.seeds)), "active": self.filters_active(), "reset": T["seeds_filter_reset"]}

    def _bulk(self, found):
        busy, count = self.busy, len(self.checked)
        actions = []
        for kind, key in (("activate", "seeds_bulk_activate"), ("rest", "seeds_bulk_rest")):
            number, reason = self.bulk_info(kind)
            actions.append({"key": kind, "text": T[key].format(n=number), "enabled": number > 0 and not busy, "reason": reason})
        return {"a11y": T["seeds_bulk_a11y"], "text": T["seeds_bulk_selected"].format(n=count) if count else T["seeds_bulk_none"], "count": count, "actions": actions,
                "select_all": {"text": T["seeds_bulk_select_all"].format(n=len(found)), "enabled": bool(found) and not busy}, "clear": {"text": T["seeds_bulk_clear"], "enabled": count > 0 and not busy}}

    def view(self, diag_text=""):
        data, state = self.data, self.state
        banners = []
        if data is not None and data.state == "missing" and not data.sample:
            banners.append(("info", T["seeds_missing_note"]))
        normal = state == "normal" and data is not None
        found = self.found() if normal else []
        shown = found[:self.limit]
        idle = data.idle_days() if data is not None else {}
        rest = len(found) - len(shown)
        if normal and not data.seeds:
            empty = {"title": T["seeds_empty_title"], "desc": T["seeds_empty_desc"]}
        elif normal and not found:
            empty = {"title": T["seeds_none_found"], "desc": ""}
        else:
            empty = None
        return {
            "title": T["seeds_title"], "sub": T["seeds_sub"], "refresh": T["seeds_refresh"], "import": T["seeds_import"], "new": T["seeds_new"], "sample": bool(data and data.sample), "sample_tag": T["sample_tag"],
            "sample_tip": T["seeds_sample_tip"], "state": state, "busy": self.busy, "loading": {"text": T["seeds_loading"], "a11y": T["seeds_loading_a11y"]},
            "error": {"title": T["seeds_error_title"], "desc": T["seeds_error_desc"], "button": T["seeds_error_btn"], "diag": diag_text, "user": ""},
            "banners": banners, "notice": {"level": self.notice[0], "text": self.notice[1]} if self.notice else None,
            "summary": self._summary(data) if normal else None, "filters": self._filters(data, found) if normal else None, "bulk": self._bulk(found) if normal else None,
            "list": {"a11y": T["seeds_list_a11y"], "rows": [self._row(seed, idle.get(seed.seed_id)) for seed in shown], "more": {"text": T["seeds_more"].format(n=min(rest, rules.PAGE)), "a11y": T["seeds_more_a11y"].format(n=min(rest, rules.PAGE))} if rest > 0 else None,
                     "empty": empty, "found": len(found), "total": len(data.seeds) if data is not None else 0},
        }
