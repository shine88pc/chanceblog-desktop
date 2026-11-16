"""블로그 관리 화면의 상태·동작·뷰모델(P4b) — 순수 파이썬(화면 도구를 모른다). Qt 화면은 `view()` 가 만든 딕셔너리를 그리기만 한다: 어떤 칸이 비었는지·무엇이 바뀌었는지·어느 단추를 켤지·어떤 문장을 보일지는 여기서 정한다.

흐름과 규칙:
  · **읽기와 쓰기를 가른다**: 화면을 열고(`start_load`) 슬롯을 고르고 칸을 고치는 것은 파일에 닿지 않는다. 파일에 쓰는 일은 `start_save`·`start_clone`·`start_clear` 셋뿐이고 사용자가 저장·복제·삭제(확인창)를 눌렀을 때만 불린다(공급자의 쓰기 메서드 — 작업 스레드에서).
  · **입력은 지워지지 않는다**: 고친 값(초안)은 슬롯마다 이 상태가 들고 있다 — 저장이 실패해도(낡은 판·잠금·읽기 전용·디스크 가득·칸 오류) 그대로이고, 슬롯을 옮겼다 돌아와도 남는다. 성공하면 그 슬롯의 초안만 비운다.
  · 칸 옆 오류는 **고친 칸이나 저장을 시도한 뒤에만** 보인다(처음 보는 빈 등록 칸이 빨갛게 시작하지 않는다). 저장 단추는 바뀐 것이 있을 때 켜지고, 칸에 문제가 있으면 서비스를 부르지 않고 문제 칸을 알린다.
  · 다른 곳이 먼저 바꿔(낡은 판) 저장이 거절되면 최신 내용을 다시 읽고(읽기만) 초안은 그대로 둔다 — 확인한 뒤 다시 저장한다. 초안은 **고친 칸만** 들고 있어 안 고친 칸은 다시 읽은 최신 값을 따른다(다른 곳이 바꾼 칸을 낡은 값으로 되돌려 쓰지 않는다).
  · 오류 문장은 쉬운 말뿐이다(파이썬 목록·내부 예외·오류 코드·경로 없음). 코드는 읽기 오류의 접힌 '진단 정보'에만 있다.
  · **등록한 블로그만 카드로 보이고 맨 끝에 '블로그 추가' 카드가 있다**(저장 형식의 다섯 슬롯은 그대로 — 사용자 눈에서만 숨는다): 카드는 `blog_form.is_listed`(등록됐거나 내용이 있거나 새로 연결하는 중)인 슬롯뿐이고,
    '블로그 추가' 는 종류(네이버·Blogger·GitHub Pages)를 고르게 한 뒤 **같은 종류의 빈 슬롯**을 속에서 쓴다(`start_adding` — 사용자에게 슬롯 이름은 보이지 않는다). 새로 연결하는 슬롯의 이름 칸은 빈 글이고
    별명은 종류 + 번호로 제안해 미리 넣어 둔다(고칠 수 있다). 빈 슬롯은 이 흐름에서만 열리고, 이미 내용이 있는 슬롯은 덮어쓰지 않는다.
  · **직접 입력은 보기로 고른다**: 낱말 칸(주요 주제·카테고리·우선·제외 키워드)은 제안 칩을 켜고 끄며(`toggle_choice` — 한도와 우선·제외 겹침 금지는 그대로), 한 줄 칸 셋(채널 역할·대상 독자·문체)은 보기 하나를 고르거나
    '직접 입력' 을 눌러 적고(`choose_option`·`open_custom`), 별명·소개글은 제안 문장을 눌러 쓴다(`apply_suggestion`). 저장하는 값은 기존과 같은 글이다.
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
        self.selected = DEFAULT_SELECTED                     # 폼에 열린 슬롯 — 카드로 보이는 슬롯이 하나도 없으면 None(종류 고르기가 열린다)
        self.adding = set()                                  # 새 블로그로 열어 둔 빈 슬롯들 — 저장하기 전까지 카드에 '등록 전' 으로 보인다
        self.picking = False                                 # '블로그 추가' 의 종류 고르기가 열려 있나
        self.return_to = None                                # 새 블로그 폼을 열기 전에 폼에 열려 있던 카드 — 새 블로그 '취소' 뒤에 돌아가는 자리(없거나 사라졌으면 첫 카드)
        self.custom_open = set()                             # (슬롯, 칸 이름) — '직접 입력' 을 눌러 입력 칸을 연 보기 칸들
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
        stale = self._adopt(data)
        self.failure = None
        self.state = "normal"
        self._normalize_selection()
        if self.reload_after_conflict:
            self.reload_after_conflict = False
            self.notice = stale or ("warning", T["blogs_stale_reloaded"])              # 입력을 옮겼거나 버렸다면 '입력한 내용은 그대로 두었어요' 가 사실이 아니라 그 이유를 알린다
        elif stale:
            self.notice = stale
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
        """저장된 값 그대로 — 복제·삭제·'비어 있나' 판단은 이 값으로 한다."""
        return self.slot_map()[key].raw()

    def form_base(self, key):
        """폼의 바탕값 — 저장된 값이고, 단 비어 있는 슬롯은 이름 칸이 빈 글이다(`blog_form.form_base`)."""
        return bf.form_base(key, self.base_raw(key))

    def values(self, key):
        """그 슬롯의 지금 입력값 — 저장된(가장 최근에 읽은) 값 위에 고친 칸만 덮어쓴다. 안 고친 칸은 다시 읽어 온 최신 값을 따른다."""
        draft = self.drafts.get(key)
        return {**self.form_base(key), **draft} if draft else self.form_base(key)

    def dirty_names(self, key):
        return bf.dirty_names(key, self.form_base(key), self.values(key)) if self.data is not None and key in self.slot_map() else ()

    # ---- 카드로 보이는 슬롯 · 새 블로그 연결 ----
    def listed_keys(self):
        """카드로 보이는 슬롯들(슬롯 순서) — 등록됐거나 내용이 있거나 새로 연결하는 중인 것(`blog_form.is_listed`)."""
        if self.data is None:
            return ()
        return tuple(slot.key for slot in self.data.slots if bf.is_listed(slot.key, slot.raw(), slot.key in self.adding))

    def _normalize_selection(self, prefer=None):
        """폼에 열린 슬롯이 카드로 보이는 슬롯이 아니면 `prefer`(새 블로그 폼을 열기 전의 카드 — 아직 카드면)로, 아니면 첫 카드로 옮기고(없으면 None — 종류 고르기가 열린다)."""
        keys = self.listed_keys()
        if self.selected not in keys:
            self.selected = prefer if prefer in keys else (keys[0] if keys else None)

    def picker_shown(self):
        """종류 고르기가 보이나 — 사용자가 '블로그 추가' 로 열었거나, 폼에 열린 카드가 없어(카드가 하나도 없는 처음) 처음부터 열려 있다."""
        return self.data is not None and self.state == "normal" and (self.picking or self.selected not in self.listed_keys())

    def has_unsaved(self):
        """저장하지 않은 입력이 있나 — 고쳐서 저장 전인 카드가 있거나, 새 블로그 폼에 미리 넣은 제안 별명 말고 입력한 것이 있다. 쓰는 중이면 없다(앱을 닫아도 쓰기를 마칠 때까지 기다린다)."""
        if self.data is None or self.state != "normal" or self.busy:
            return False
        for key in self.listed_keys():
            names = set(self.dirty_names(key))
            if self._is_fresh(key) and bf.clean_line(self.values(key).get("alias")) == bf.suggest_alias(key):
                names.discard("alias")
            if names:
                return True
        return False

    def close_dialog(self):
        """앱 닫기 확인창의 글(없으면 None) — 저장하지 않은 입력이 있을 때만이다. 처음 포커스는 취소(삭제 확인창과 같은 원칙)."""
        if not self.has_unsaved():
            return None
        return {"title": T["blogs_close_title"], "body": T["blogs_close_body"], "ok": T["blogs_close_ok"], "cancel": T["blogs_close_cancel"], "blogs": True}      # `blogs` 표시 — 셸이 초안 확인(뒤에 이 확인이 이어질 수 있다)과 이 확인을 가른다

    def _pop_input(self, key):
        """그 슬롯에 대한 입력 상태(초안·고친 칸·저장 시도·직접 입력 칸·서비스가 알린 문제)를 꺼내 지운다 → 꺼낸 것(옮길 때 쓴다)."""
        taken = {"touched": self.touched.pop(key, None), "problems": self.service_problems.pop(key, None), "submitted": key in self.submitted,
                 "custom": {name for slot, name in self.custom_open if slot == key}}
        self.drafts.pop(key, None)
        self.submitted.discard(key)
        self.custom_open = {item for item in self.custom_open if item[0] != key}
        return taken

    def _carry_input(self, old, target, effective, taken):
        """새 블로그 폼의 입력을 `old` 슬롯에서 같은 종류의 `target` 슬롯으로 옮긴다 — 사용자가 본 값 그대로(`effective`)이고, 그 슬롯의 바탕값과 같은 칸은 초안에서 뺀다. 제안 별명을 그대로 두었다면 새 슬롯의 번호로 다시 제안한다."""
        effective = dict(effective)
        if bf.clean_line(effective.get("alias")) == bf.suggest_alias(old):
            effective["alias"] = bf.suggest_alias(target)
        base = self.form_base(target)
        self.adding.add(target)
        self.drafts[target] = {name: effective[name] for name in bf.dirty_names(target, base, {**base, **effective})}
        if taken["touched"]:
            self.touched[target] = taken["touched"]
        if taken["problems"]:
            self.service_problems[target] = taken["problems"]
        if taken["submitted"]:
            self.submitted.add(target)
        self.custom_open |= {(target, name) for name in taken["custom"]}
        if self.selected == old:
            self.selected = target

    def _adopt(self, data):
        """새로 읽은(또는 쓴 뒤 받은) 자료로 바꾸고, 화면이 들고 있던 입력을 그 자료에 맞게 다시 정리한다 → 알릴 말 `(수준, 글)` 또는 None.
        ① 새 블로그로 열어 둔 슬롯이 그 사이 다른 곳에서 채워졌으면(`_is_fresh` 가 아니다) 그 입력을 남의 블로그에 얹지 않는다 — 같은 종류의 다른 빈 슬롯이 있으면 입력을 그대로 옮겨 그 슬롯으로 폼을 다시 열고, 없으면 버린다(둘 다 이유를 알린다).
        ② 카드로 보이지도 않고 새 블로그로 열어 둔 것도 아닌 슬롯의 낡은 입력은 지운다 — 그 슬롯이 다른 곳에서 비워졌다면 다음 '블로그 추가' 에서 되살아나지 않게(고치던 입력을 버렸으면 알린다)."""
        before = {key: self.values(key) if self.data is not None else {**bf.form_base(key, bf.default_values(key)), **self.drafts.get(key, {})} for key in self.adding}     # 읽기 오류로 자료를 비운 뒤에도 입력은 남아 있다
        self.data = data
        moved, dropped = False, []
        for key in [slot for slot in bf.SLOTS if slot in self.adding]:
            if self._is_fresh(key):
                continue
            taken = self._pop_input(key)
            self.adding.discard(key)
            target = bf.free_slot(bf.KIND_KEY[key], self.slot_raws(), self.adding)
            if target is None:
                dropped.append(key)
            else:
                self._carry_input(key, target, before[key], taken)
                moved = True
        if self.selected in dropped:
            self.selected = None
            self._normalize_selection(self.return_to)
        listed = set(self.listed_keys())
        gone = {key for key in (*self.drafts, *self.touched, *self.service_problems, *self.submitted, *(slot for slot, _ in self.custom_open)) if key not in listed}
        lost = any(self.drafts.get(key) for key in gone)
        for key in gone:
            self._pop_input(key)
        if dropped:
            return "warning", T["blogs_taken_dropped"]
        if moved:
            return "warning", T["blogs_taken_moved"]
        return ("warning", T["blogs_edit_gone"]) if lost else None

    def _is_fresh(self, key):
        """새로 연결하는 중이고 저장된 것이 아직 없는 슬롯."""
        return key in self.adding and bf.is_empty_values(key, self.base_raw(key))

    def slot_raws(self):
        return {key: slot.raw() for key, slot in self.slot_map().items()}

    def kind_free(self, kind):
        """그 종류에 새 블로그를 넣을 수 있는 빈 슬롯의 수."""
        return bf.free_count(kind, self.slot_raws(), self.adding) if self.data is not None else 0

    def open_picker(self):
        """'블로그 추가' 카드를 눌렀다 — 종류 고르기를 연다(고치던 내용은 그대로 남는다)."""
        if self.data is None or self.busy:
            return False
        self.picking, self.notice = True, None
        return True

    def close_picker(self):
        """종류 고르기를 닫고 카드로 돌아간다(카드가 하나도 없으면 닫아도 종류 고르기가 보인다)."""
        if self.busy or not self.picking:
            return False
        self.picking = False
        self._normalize_selection()
        return True

    def start_adding(self, kind):
        """종류를 골랐다 → 같은 종류의 빈 슬롯을 새 블로그로 열고 그 슬롯 열쇠를 돌려준다(없으면 None). 슬롯 이름은 사용자에게 보이지 않고, 별명은 종류 + 번호로 제안해 미리 넣는다."""
        if self.data is None or self.busy or kind not in bf.KINDS or not self.picker_shown():                  # 종류 고르기가 열려 있을 때만 — 신호가 겹쳐 두 번 와도 슬롯 둘이 잡히지 않는다
            return None
        key = bf.free_slot(kind, self.slot_raws(), self.adding)
        if key is None:
            return None
        self.return_to = self.selected if self.selected in self.listed_keys() else None                       # 새 블로그 '취소' 뒤에 돌아갈 카드
        self._pop_input(key)                                                                                  # 이 자리에 낡은 입력이 남아 있어도 되살리지 않는다
        self.adding.add(key)
        self.drafts[key] = {"alias": bf.suggest_alias(key)}
        self.selected, self.picking, self.notice = key, False, None
        return key

    def is_dirty(self, key):
        return bool(self.dirty_names(key))

    def extra_tags(self, key):
        """저장된 협찬 분야 중 이름표가 없는 값(손으로 고친 파일에서 온 것) — 화면이 못 바꾸므로 저장해도 그대로 보관된다."""
        return tuple(tag for tag in self.slot_map()[key].monetization_focus if tag not in bf.TAG_ORDER)

    # ---- 선택·편집(파일에 닿지 않는다) ----
    def select(self, key):
        """카드를 눌러 그 슬롯의 폼을 연다. 카드가 없는 빈 슬롯을 열면 새 블로그를 연결하는 일이 된다(화면은 카드가 있는 슬롯만 누르게 하므로 시험·도구용 길)."""
        if key not in bf.SLOTS or self.busy:
            return False
        if self.data is not None and key in self.slot_map() and key not in self.listed_keys():
            self.adding.add(key)
        if key in self.adding and key != self.selected and self.selected in self.listed_keys():
            self.return_to = self.selected                                                                    # 입력 중인 새 블로그 카드로 옮겨 오면, 취소할 때 돌아갈 곳은 방금 있던 카드다
        self.selected, self.notice, self.picking = key, None, False
        return True

    def edit(self, name, value):
        """선택한 슬롯의 칸 하나를 고친다. 초안에는 고친 칸만 남기고, 저장된 값과 같아진 칸(다듬은 뜻이 같은 것)은 뺀다 — 모두 빠지면 그 슬롯의 초안을 비운다."""
        key = self.selected
        if self.data is None or self.busy or key is None or name not in {spec.name for spec in bf.fields_for(key)}:
            return False
        base = self.form_base(key)
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

    def toggle_choice(self, name, value):
        """여럿 고르는 칩의 값 하나를 켜고 끈다 — 협찬 가능 분야·선호 글 유형(`multi`)과 낱말 칸의 제안 칩(`words` — 주요 주제·카테고리·우선·제외 키워드). 그 칸이 아는 값만이다(목록에 없는 값은 칩으로 만들 수 없다).
        낱말 칸은 한도(`count`)를 넘겨 켤 수 없고, 우선·제외 키워드는 다른 칸에서 이미 고른 낱말을 켤 수 없다(저장 때의 겹침 오류를 칩으로는 만들지 않는다) — 켠 낱말을 끄는 것은 늘 된다."""
        spec = bf.SPEC.get(name)
        if spec is None or self.data is None or self.selected is None:
            return False
        if spec.kind == "multi":
            if value not in spec.options:
                return False
            current = set(self.values(self.selected).get(name, ()))
            current.symmetric_difference_update({value})
            return self.edit(name, tuple(current))
        if spec.kind != "words" or value not in spec.suggest:
            return False
        values = self.values(self.selected)
        text = values.get(name, "")
        if value.casefold() not in bf.picked_words(text):                                      # 새로 켜는 경우만 막는다
            if len(bf.split_words(text)) >= spec.count:
                return False
            if name in bf.KEYWORD_FIELDS:
                other = next(field for field in bf.KEYWORD_FIELDS if field != name)
                if value.casefold() in bf.picked_words(values.get(other, "")):
                    return False
        return self.edit(name, bf.toggle_word(text, value))

    def choose_option(self, name, value):
        """보기가 있는 한 줄 칸(채널 역할·대상 독자·문체)에서 보기 하나를 고른다 — 이미 고른 보기를 다시 누르면 비운다. '직접 입력' 이 열려 있었다면 닫고 그 보기를 고른다."""
        spec = bf.SPEC.get(name)
        if spec is None or not spec.choices or value not in spec.choices or self.data is None or self.busy or self.selected is None:
            return False
        key = self.selected
        was_custom = (key, name) in self.custom_open
        self.custom_open.discard((key, name))
        same = bf.clean_line(self.values(key).get(name)) == value
        return self.edit(name, "" if same and not was_custom else value)

    def open_custom(self, name):
        """'직접 입력' 을 눌렀다 — 그 보기 칸의 입력 칸을 연다(쓴 글은 그대로 두고 입력 칸만 보인다)."""
        spec = bf.SPEC.get(name)
        if spec is None or not spec.choices or self.data is None or self.busy or self.selected is None:
            return False
        self.custom_open.add((self.selected, name))
        return True

    def suggestion_text(self, name, key=None):
        """그 칸의 제안 문장(없으면 빈 글) — 별명은 종류 + 번호, 소개글은 지금 고른 값으로 만든 문장. 입력 칸에 넣는 글 그대로다(보이는 글은 따로 가려서 보인다)."""
        key = key or self.selected
        spec = bf.SPEC.get(name)
        if spec is None or not spec.assist or key is None or self.data is None or key not in self.slot_map():
            return ""
        return bf.suggest_alias(key) if spec.assist == "alias" else bf.suggest_intro(self.values(key))

    def apply_suggestion(self, name):
        """제안 문장을 입력 칸에 넣는다 — 사용자가 고쳐서 저장한다(넣는 것만으로는 저장되지 않는다)."""
        text = self.suggestion_text(name)
        return bool(text) and self.edit(name, text)

    def toggle_tag(self, tag):
        """협찬 가능 분야 하나를 켜고 끈다(이름표가 있는 여섯 가지만) — `toggle_choice` 의 협찬 분야 칸."""
        return self.toggle_choice("monetization_focus", tag)

    def revert(self):
        """되돌리기 — 그 슬롯의 초안을 버린다. 새로 연결하던 슬롯이면 연결을 취소하는 일이다(카드가 사라지고 다른 카드로 옮겨 간다)."""
        key = self.selected
        if self.busy or key is None:
            return False
        fresh = self._is_fresh(key)
        self._pop_input(key)
        if fresh:
            self.adding.discard(key)
            self._normalize_selection(self.return_to)                                                         # 취소하면 새 블로그를 열기 전의 카드로 돌아간다(없거나 사라졌으면 첫 카드)
            self.return_to = None
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
        if self.data is None or self.busy or key is None:
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
        if self.data is None or key is None:
            return False, "", None
        allowed, reason, target = bf.clone_state(self.slot_raws(), key, self.adding)
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
        named = bf.user_name(slot.key, slot.display_name) if slot is not None else ""                    # 사용자가 정한 이름만 보인다 — 기본 프로필의 이름(슬롯 이름 `네이버 A`)이 저장돼 있어도 이 글에 나가지 않는다
        who = T["blogs_del_named"].format(name=bf.shown(named, 30)) if named else T["blogs_del_unnamed"]        # 이름이 없으면 `이 블로그` — `‘이름 없는 블로그’ 블로그` 처럼 '블로그' 가 두 번 읽히지 않는다
        return {"title": T["blogs_del_title"], "body": T["blogs_del_body"].format(who=who), "ok": T["blogs_del_ok"], "cancel": T["blogs_del_cancel"]}

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
        for key in (work["key"], work["target"]):
            if key is not None:
                self._pop_input(key)
                self.adding.discard(key)
        stale = self._adopt(outcome.data)                                                           # 쓴 뒤 받은 자료에 다른 곳의 바뀐 내용이 있으면 다른 입력도 그에 맞게 정리한다
        if outcome.kind == "unchanged":
            self.notice = ("info", T["blogs_unchanged"])
        elif work["kind"] == "clone":
            self.selected = work["target"]
            self.notice = ("ok", T["blogs_cloned"])
        else:
            self.notice = ("ok", T["blogs_cleared"] if work["kind"] == "clear" else T["blogs_saved"])
        if stale:
            self.notice = ("warning", f"{self.notice[1]} {stale[1]}")
        self.picking = False
        self._normalize_selection()                                                                 # 지운 슬롯은 더 카드가 아니다 — 다른 카드로 옮겨 가고(없으면 종류 고르기)

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
    def _field(self, key, spec, values, dirty_names, shown):
        problem = shown.get(spec.name, "")
        raw = values.get(spec.name)
        view = {"name": spec.name, "kind": spec.kind, "label": spec.label, "required": spec.required, "required_text": T["blogs_required"] if spec.required else "", "value": raw, "hint": spec.hint(),
                "error": bf.problem_text(spec, problem, raw) if problem else "", "warning": "", "options": [], "extra": "", "disabled": self.busy, "disabled_reason": "", "placeholder": "",
                "changed": spec.name in dirty_names, "custom": False, "suggestion": None, "assist": spec.assist, "readonly": spec.kind == "path"}
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
            view["options"] = bf.options_of(spec)                                              # 칸마다 다른 선택지(협찬 분야·선호 글 유형)
            extra = self.extra_tags(key) if spec.keep_extra else ()                            # 목록 밖 값 보존은 협찬 분야만(글 유형은 서비스가 목록 밖 값을 거절한다)
            view["extra"] = T["bf_extra_tags"].format(n=len(extra)) if extra else ""
        if spec.kind == "line" and spec.choices:                                               # 보기 하나를 고르거나 '직접 입력' — 보기 밖의 저장된 값은 입력 칸에 그대로 보인다
            custom, picked = bf.line_choice_state(spec, raw, (key, spec.name) in self.custom_open)
            view["options"] = [{"value": choice, "label": choice, "checked": choice == picked} for choice in spec.choices]
            view["custom"] = custom
            view["placeholder"] = T["bf_input_custom"]
        if spec.kind == "words" and spec.suggest:                                              # 제안 칩(여러 개) + 직접 추가 — 한도·우선/제외 겹침은 칩이 만들지 못한다
            words, on = bf.split_words(raw), bf.picked_words(raw)
            other = bf.picked_words(values.get(next(field for field in bf.KEYWORD_FIELDS if field != spec.name), "")) if spec.name in bf.KEYWORD_FIELDS else frozenset()
            full = len(words) >= spec.count
            options = []
            for word in spec.suggest:
                folded = word.casefold()
                reason = "" if folded in on else T["bf_chip_other"] if folded in other else T["bf_chip_full"] if full else ""
                options.append({"value": word, "label": word, "checked": folded in on, "disabled": bool(reason), "reason": reason})
            view["options"] = options
            view["extra"] = T["bf_note_full"].format(count=spec.count) if full else ""
        if spec.assist:                                                                        # 제안 문장(별명 — 종류 + 번호 / 소개글 — 고른 값으로 만든 문장): 이미 그 글을 쓰고 있으면 보이지 않는다
            suggestion = self.suggestion_text(spec.name, key)
            if suggestion and bf.clean_line(raw) != suggestion:
                view["suggestion"] = {"label": T["bf_suggest_label"], "text": bf.shown(suggestion, 300), "button": T["bf_suggest_use"], "a11y": T["bf_suggest_a11y"].format(label=spec.label)}
        if spec.name == "blog_ref":
            view["hint"] = T["bf_ref_help_naver" if bf.KIND_KEY[key] == "naver" else "bf_ref_help_web"]      # 주소는 사용자만 안다 — 종류마다 모양 도움말(예시는 가짜 아이디)
            if not problem:
                same = bf.normalize(spec, raw).casefold()
                if same and any(other != key and slot.blog_ref.casefold() == same for other, slot in self.slot_map().items()):
                    view["warning"] = T["bf_warn_same_ref"]
        return view

    def _form(self, key):
        slot = self.slot_map()[key]
        values = self.values(key)
        dirty_names = self.dirty_names(key)                                                    # 칸마다 다시 계산하지 않는다(칸 열여덟 × 값 다듬기 둘)
        computed = self.problems(key)
        reveal = key in self.submitted
        touched = self.touched.get(key, set())
        shown = {name: problem for name, problem in computed.items() if reveal or name in touched or name in self.service_problems.get(key, {})}
        dirty = bool(dirty_names)
        fresh = self._is_fresh(key)
        sections = []
        for section in bf.SECTIONS:
            fields = [self._field(key, spec, values, dirty_names, shown) for spec in bf.fields_for(key) if spec.section == section]
            if section == "basic" and key not in bf.GENERATION_SLOTS:                           # 후보 만들기는 네이버 블로그만 — 나머지는 꺼진 스위치와 이유(죽은 스위치가 아니라 이유가 있는 꺼짐)
                fields.append({"name": "generation_enabled", "kind": "flag", "label": T["bf_label_generation_enabled"], "required": False, "required_text": "", "value": bool(slot.generation_enabled),
                               "hint": T["bf_hint_generation_off"], "error": "", "warning": "", "options": [], "extra": "", "disabled": True, "disabled_reason": T["bf_hint_generation_off"],
                               "placeholder": "", "changed": False, "custom": False, "suggestion": None, "assist": "", "readonly": False})
            sections.append({"key": section, "title": T["blogs_sec_" + section], "desc": T["blogs_sec_" + section + "_desc"], "fields": fields})
        clone_ok, clone_reason, clone_target = self.clone_info(key)
        can_clear = self.can_clear(key)
        busy = self.busy
        kind_name = T["blogs_kind_" + bf.KIND_KEY[key]]
        save = {"key": "save", "text": T["blogs_save"], "kind": "primary", "enabled": dirty and not busy, "reason": "" if dirty and not busy else (T["blogs_working"] if busy else T["blogs_save_nothing"])}
        if fresh:                                                                              # 새로 연결하는 블로그 — 저장과 취소뿐이다(복제할 것도 지울 것도 아직 없다). 취소는 연결을 그만두는 일이다
            actions = [save, {"key": "revert", "text": T["blogs_cancel"], "kind": "secondary", "enabled": not busy, "reason": T["blogs_working"] if busy else ""}]
        else:
            actions = [
                save,
                {"key": "revert", "text": T["blogs_revert"], "kind": "secondary", "enabled": dirty and not busy, "reason": "" if dirty and not busy else (T["blogs_working"] if busy else T["blogs_revert_nothing"])},
                {"key": "clone", "text": T["blogs_clone"], "kind": "secondary", "enabled": clone_ok and not busy, "reason": T["blogs_working"] if busy else clone_reason,
                 "hint": T["blogs_clone_hint"].format(kind=kind_name) if clone_ok and clone_target else ""},
                {"key": "delete", "text": T["blogs_delete"], "kind": "danger", "enabled": can_clear and not busy, "reason": T["blogs_working"] if busy else ("" if can_clear else T["blogs_delete_empty"])},
            ]
        title = bf.card_title(key, slot.alias)
        preset = values.get("color_preset") or ""
        if fresh:
            head, caption = T["blogs_form_new"].format(kind=kind_name), T["blogs_form_new_desc"]
        else:
            head, caption = T["blogs_form_edit" if slot.registered else "blogs_form_unfinished"].format(slot=title), kind_name
        return {"key": key, "title": head, "a11y": T["blogs_form_a11y"].format(slot=title if not fresh else kind_name),
                "registered": slot.registered, "fresh": fresh, "kind": caption, "preset_text": T["blogs_card_preset"].format(name=bf.preset_name(preset)) if preset else "",
                "status": {"tone": "ok" if slot.registered else "muted", "text": T["blogs_status_registered" if slot.registered else "blogs_status_new"]},
                "unsaved": {"tone": "warning", "text": T["blogs_status_unsaved"]} if dirty and not fresh else None,
                "sections": sections, "actions": actions, "dirty": dirty, "dirty_names": dirty_names, "saving": busy, "saving_text": T["blogs_saving"],
                "preset": preset, "actions_a11y": T["blogs_actions_a11y"]}

    def _card(self, slot):
        key = slot.key
        registered = slot.registered
        fresh = self._is_fresh(key)
        unsaved = self.is_dirty(key) and not fresh                                              # 새로 연결하는 카드는 늘 저장 전이라 따로 '저장 전 변경' 을 붙이지 않는다(상태가 '등록 전' 이다)
        title = bf.card_title(key, slot.alias)                                                  # 별명(없으면 종류 + 번호) — 슬롯 이름은 사용자에게 보이지 않는다
        kind = T["blogs_kind_" + bf.KIND_KEY[key]]
        named = bf.user_name(key, slot.display_name)                                            # 저장된 이름이 그 슬롯의 기본 이름(슬롯 이름)이면 카드에는 종류 이름을 보인다 — 저장된 값은 그대로다
        name = bf.shown(named, 30) if named else kind
        if registered:
            headline, sub = name, T["blogs_card_ref"].format(ref=bf.shown(slot.blog_ref, 40))
        elif fresh:
            headline, sub = T["blogs_card_new_title"], T["blogs_card_new_desc"]
        else:                                                                                   # 주소 없이 내용만 있는 슬롯(손으로 고친 파일) — 숨기지 않고 주소를 넣으라고 알린다
            headline, sub = name, T["blogs_card_unfinished_desc"]
        role = bf.shown(slot.channel_role, 60) if slot.channel_role else bf.shown(" · ".join(slot.main_topics[:3]), 60) if slot.main_topics else ""
        chips = [{"tone": "muted", "text": T["blogs_lang_" + slot.language]}] if registered else []
        if key in bf.GENERATION_SLOTS:
            chips.append({"tone": "ok" if slot.generation_enabled else "muted", "text": T["blogs_gen_on" if slot.generation_enabled else "blogs_gen_off"]})
        else:
            chips.append({"tone": "muted", "text": T["blogs_gen_none"]})
        if unsaved:
            chips.append({"tone": "warning", "text": T["blogs_status_unsaved"]})
        base = T["blogs_card_a11y"].format(slot=title, state=T["blogs_status_registered"], name=headline) if registered else T["blogs_card_a11y_new"].format(slot=title, name=headline)
        selected = key == self.selected and not self.picking
        meta = " · ".join([kind] + [chip["text"] for chip in chips if chip["tone"] != "warning"]) if registered else kind                  # 카드의 마지막 줄 — 종류 · 언어 · 후보 만들기 상태(저장 전 변경은 카드 윗줄의 배지)
        return {"key": key, "title": title, "kind": kind, "registered": registered, "fresh": fresh, "headline": headline, "sub": sub, "role": role if registered else "", "chips": chips, "meta": meta,
                "status": {"tone": "ok" if registered else "muted", "text": T["blogs_status_registered" if registered else "blogs_status_new"]}, "unsaved": unsaved,
                "preset": (slot.color_preset or "") if registered else "", "preset_text": T["blogs_card_preset"].format(name=bf.preset_name(slot.color_preset)) if registered and slot.color_preset else "",
                "selected": selected, "sample": slot.sample, "a11y": T["blogs_card_selected"].format(base=base) if selected else base}

    def _add_card(self, picker_open):
        """목록 맨 끝의 '블로그 추가' 카드 — 눌러서 종류 고르기를 연다."""
        return {"key": "add", "title": T["blogs_add_title"], "desc": T["blogs_add_desc"], "a11y": T["blogs_add_a11y"], "selected": picker_open}

    def _picker(self, listed):
        """종류 고르기 — 네이버·Blogger·GitHub Pages 각각 연결해 둔 수와 남은 자리, 자리가 없으면 이유. 카드가 있으면 닫을 수 있다."""
        kinds = []
        for kind in bf.KINDS:
            total, left = len(bf.KIND_SLOTS[kind]), self.kind_free(kind)
            name, count = T["blogs_kind_" + kind], T["blogs_pick_count"].format(used=total - left, left=left)
            kinds.append({"kind": kind, "title": name, "desc": T["blogs_kinddesc_" + kind], "count": count, "left": left, "enabled": left > 0, "reason": "" if left else T["blogs_pick_full"],
                          "a11y": T["blogs_pick_kind_a11y" if left else "blogs_pick_kind_full_a11y"].format(kind=name, count=count)})
        return {"title": T["blogs_pick_title"], "desc": T["blogs_pick_desc"], "a11y": T["blogs_pick_a11y"], "kinds": kinds, "close": T["blogs_pick_close"] if listed else "", "busy": self.busy}

    def view(self, diag_text=""):
        data = self.data
        state = self.state
        banners = []
        if data is not None and data.state == "missing" and not data.sample:
            banners.append(("info", T["blogs_missing_note"]))
        normal = state == "normal" and data is not None
        listed = self.listed_keys() if normal else ()
        picker_open = self.picker_shown()                                                        # 카드가 하나도 없으면(처음) 종류 고르기가 폼 자리에 열려 있다
        by_key = data.by_key() if normal else {}
        return {
            "title": T["blogs_title"], "sub": T["blogs_sub"], "refresh": T["blogs_refresh"], "sample": bool(data and data.sample), "sample_tag": T["sample_tag"], "sample_tip": T["blogs_sample_tip"],
            "state": state, "busy": self.busy, "loading": {"text": T["blogs_loading"], "a11y": T["blogs_loading_a11y"]},
            "error": {"title": T["blogs_error_title"], "desc": T["blogs_error_desc"], "button": T["blogs_error_btn"], "diag": diag_text, "user": ""},
            "banners": banners, "notice": {"level": self.notice[0], "text": self.notice[1]} if self.notice else None,
            "list": {"title": T["blogs_list_title"], "desc": T["blogs_list_desc"], "a11y": T["blogs_list_a11y"], "cards": [self._card(by_key[key]) for key in listed] if normal else [],
                     "add": self._add_card(picker_open) if normal else None},
            "selected": self.selected, "picker": self._picker(listed) if picker_open else None,
            "form": self._form(self.selected) if normal and not picker_open else None,
        }
