"""키 연결(P4f)의 상태·동작·뷰모델 — 순수 파이썬(화면 도구·서비스 층을 모른다). Qt 화면은 여기서 만든 딕셔너리를 그리기만 한다: 어느 단추를 켤지·어떤 문장을 보일지·입력 칸에 문제가 있는지는 여기서 정한다.

규칙(모두 시험이 지킨다):
  · **키 원문은 이 모듈의 어떤 값에도 들어가지 않는다.** 입력 칸의 글은 `SecretBox` 로만 서비스 인자까지 가고(`start_add` 가 받는 것은 통이다), 컨트롤러·초안(`RegisterDraft`)·뷰모델·알림·행 안내에는 키도 키의 일부도 길이도 없다.
    일감(작업 스레드에 넘기는 함수)은 통만 쥐고, 일이 시작되지 않으면 통을 바로 비운다.
  · **쓰기는 사용자가 단추를 눌렀을 때만**: 읽기(설정 화면 열기·다시 읽기)는 이 컨트롤러를 부르지 않는다. 쓰는 일은 `start_add`·`start_remove`·`start_state`·`start_rename`·`start_move`·`start_test` 여섯뿐이고 한 번에 하나다(돌고 있으면 두 번째는 아무 일도 하지 않는다).
  · 쓰는 공급자(`KeysWriter`)가 아닌 공급자(읽기 전용)에서는 키 행동이 하나도 없다 — 카드는 이전과 같다(`writable` 이 거짓이면 `card_keys` 는 None).
  · 키 저장소(Windows 자격 증명 관리자)를 못 쓰는 환경은 오류가 아니라 상태다: 등록·삭제·별칭·시험 단추가 꺼지고 '이 컴퓨터에서는 키 저장소를 쓸 수 없어요' 가 보인다.
  · 연결 시험은 호출 코드가 있는 용도에서만 켜진다(`can_test`) — 없으면 '아직 시험할 수 없어요(준비 중)' 로 꺼 두고 까닭을 보인다. 이용 약관을 확인하기 전 용도(`test_blocked`)는 호출하지 않는다.
  · 오류 문장은 종류별로 정해진 쉬운 말뿐이다 — 서비스 오류의 세부·경로·오류 코드·입력한 값은 화면 글에 없다(코드는 진단 정보에만).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import key_rules as rules
from . import settings_view as sv
from .jobs import JobFailure
from .keys import KeyFailure, KeysWriter, SecretBox
from .text import T

WRITE_KEY = "keys-write"                                    # 키 쓰기 작업의 이름 — 한 번에 하나(중복 클릭은 아무 일도 하지 않는다)
ACTIONS = ("test", "state", "up", "down", "rename", "delete")
KST = timezone(timedelta(hours=9), "KST")
OUTCOME_TEXT = {"added": "keys_ok_added", "removed": "keys_ok_removed", "state": "keys_ok_state", "renamed": "keys_ok_renamed", "moved": "keys_ok_moved", "unchanged": "keys_ok_unchanged"}
TEST_TEXT = {"ok": ("ok", "keys_test_ok"), "auth_failed": ("error", "keys_test_auth"), "rate_limited": ("warning", "keys_test_limit"), "error": ("error", "keys_test_error"),
             "not_ready": ("info", "keys_test_notready"), "no_value": ("error", "keys_test_novalue")}
CHECK_TEXT = {"ok": "keys_check_ok", "auth_failed": "keys_check_auth", "error": "keys_check_error"}
STATE_TARGETS = {"active": ("standby", "off"), "standby": ("active", "off"), "off": ("active", "standby")}      # 지금 상태에서 바꿀 수 있는 다른 상태들
UNSURE_AFTER_REMOVE = ("io", "disk")                          # 삭제 도중의 저장 실패 종류 — 키 저장소의 키가 이미 지워졌는지 오류 종류만으로는 알 수 없다(독립 검증 M1, `KeysController.apply_write_failed`)


def _shown(value, limit=40):
    from ...security.mask import safe_detail                                   # 화면에 나가는 사용자 글은 가린 뒤에 줄인다(키를 별칭에 잘못 붙인 파일을 읽었을 때도 앞부분이 남지 않게)
    return safe_detail(value, limit)


def when_text(stamp):
    """UTC `YYYY-MM-DDTHH:MM:SSZ` → 한국 시간 `YYYY-MM-DD HH:MM`. 모르거나 모양이 틀리면 ''."""
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


# ---- 제공자·상한(순수 규칙 — 서비스 표와 같은 값이다) -----------------------------------------------------------------------------------
def provider_of(info, key):
    return next((item for item in info.providers if item.key == key), None)


def provider_label(info, key):
    found = provider_of(info, key)
    return found.label if found is not None else ""


def in_provider(info, key):
    return [item for item in info.entries if item.provider == key]


def has_room(info, provider):
    """그 제공자에 키를 하나 더할 자리가 있나 — 제공자 상한과 용도의 읽을 때 천장을 모두 본다(서비스의 `check_room` 과 같다)."""
    return len(in_provider(info, provider.key)) < provider.cap and len(info.entries) < info.max_entries


def room_providers(info):
    return [item for item in info.providers if has_room(info, item)]


def effective_cap(info):
    """키를 새로 더할 수 있는 최대 개수 — 제공자별 상한의 합(읽을 때 천장 `max_entries` 를 넘지 않는다). 제공자 표가 없으면 천장 그대로다. 카드의 '용도당 최대 N개' 안내가 이 숫자를 쓴다('모든 서비스에 공통 3개' 규칙은 쓰지 않는다)."""
    caps = [item.cap for item in info.providers if item.cap]
    return min(info.max_entries, sum(caps)) if caps else info.max_entries


def needs_terms(info, provider_key):
    """같은 제공자의 둘째 키부터 약관 확인이 필요한가."""
    found = provider_of(info, provider_key)
    return bool(found is not None and found.needs_terms and in_provider(info, provider_key))


def cap_text(info):
    one = [item for item in info.providers]
    if len(one) == 1:
        return T["keys_full_one"].format(service=_shown(info.label, 60), n=one[0].cap)
    return T["keys_full_many"].format(service=_shown(info.label, 60))


# ---- 입력 문제 문장 -------------------------------------------------------------------------------------------------------------------
def problem_text(field_label, code):
    """입력 칸 문제 이름 → 칸 옆 문장(입력한 글 없음). `min:16` 처럼 숫자가 달린 이름도 받는다."""
    name, _, number = str(code).partition(":")
    label = _shown(field_label, 30)
    if name == "min" and number.isdigit():
        return T["keys_problem_min"].format(field=label, n=int(number))
    return T.get("keys_problem_" + name, T["keys_problem_other"]).format(field=label)


def alias_text(code):
    name, _, number = str(code).partition(":")
    template = T.get("keys_alias_" + name, T["keys_alias_other"])
    return template.format(n=rules.ALIAS_MAX) if "{n}" in template else template


def action_a11y(action_text, name):
    return T["keys_act_a11y"].format(action=action_text, name=name)


# ---- 등록 대화상자의 비밀이 아닌 상태 -------------------------------------------------------------------------------------------------
class RegisterDraft:
    """등록 대화상자가 들고 있는 **비밀이 아닌** 값 — 서비스·제공자·별칭·약관 확인·단계·칸 문제. 키 글은 여기에 없다(입력 칸에서 `SecretBox` 로 곧바로 간다).
    입력 단계(`input`) → 확인 단계(`confirm` — 요약에는 서비스·제공자·별칭만, 키는 안 보인다) → 저장. 실패하면 별칭 같은 입력은 남고 키만 다시 입력한다."""

    def __init__(self, info):
        self.info = info
        rooms = room_providers(info)
        self.provider = rooms[0].key if rooms else (info.providers[0].key if info.providers else "")
        self.alias = rules.DEFAULT_ALIAS
        self.terms = False
        self.step = "input"
        self.problems = {}                                  # {칸 이름: 문제 이름} — 별칭은 `name`
        self.submitted = False                              # 저장으로 넘어간 초안인가 — 대화상자가 닫혀도 컨트롤러가 들고 있어야 한다(저장이 끝나거나 못 시작하면 버려진다). 그냥 닫힌(Esc·X·취소) 초안은 버려진다

    @property
    def purpose(self):
        return self.info.key

    def set_provider(self, key):
        found = provider_of(self.info, key)
        if found is None or not has_room(self.info, found):
            return False
        if found.key != self.provider:
            self.provider, self.terms = found.key, False
            self.problems.pop("provider", None)
        return True

    def set_alias(self, text):
        self.alias = str(text)
        self.problems.pop("name", None)

    def set_terms(self, checked):
        self.terms = bool(checked)

    def needs_terms(self):
        return needs_terms(self.info, self.provider)

    def check_alias(self):
        """별칭의 문제 이름('' 이면 없음) — 모양 검사 + 이 서비스에 같은 별칭이 이미 있는지."""
        code = rules.alias_problem(self.alias)
        if not code and any(item.name == rules.normalize_alias(self.alias) for item in self.info.entries):
            return "duplicate"
        return code

    def go_confirm(self, secret_problems):
        """'다음' — 별칭 검사와 입력 칸 검사(`secret_problems` = {칸 이름: 문제 이름}, 입력 칸에서 키 글을 직접 검사해 문제 이름만 넘긴 것)에 문제가 없으면 확인 단계로 간다. 문제가 있으면 입력 단계에 남고 칸 옆에 문장이 보인다."""
        problems = dict(secret_problems)
        alias = self.check_alias()
        if alias == "keyish":
            self.alias = ""                                  # 키를 별칭 칸에 잘못 붙여 넣었다 — '입력 유지' 대상이 아니다(키가 이 상태·화면에 남지 않게 비운다)
        if alias:
            problems["name"] = alias
        found = provider_of(self.info, self.provider)
        if found is None or not has_room(self.info, found):
            problems["provider"] = "full"
        self.problems = problems
        if problems:
            self.step = "input"
            return False
        self.step = "confirm"
        return True

    def back(self):
        self.step = "input"
        self.terms = False

    def can_save(self):
        return self.step == "confirm" and (not self.needs_terms() or self.terms)

    def apply_failure(self, failure):
        """저장이 실패했다 — 입력(별칭·제공자)은 남기고 키는 다시 입력한다. 서비스가 알려 준 칸 문제는 칸 옆에 보인다."""
        self.step = "input"
        self.terms = False
        self.problems = dict(failure.problems) if isinstance(failure, KeyFailure) else {}

    def vm(self):
        info = self.info
        service = _shown(info.label, 60)
        provider = provider_of(info, self.provider)
        providers = [{"key": item.key, "label": _shown(item.label, 40), "selected": item.key == self.provider, "enabled": has_room(info, item),
                      "reason": "" if has_room(info, item) else T["keys_reg_provider_full"]} for item in info.providers] if len(info.providers) > 1 else []
        fields = [{"name": item.name, "label": _shown(item.label, 30), "hint": T["keys_reg_field_hint"], "a11y": T["keys_reg_secret_a11y"].format(field=_shown(item.label, 30)),
                   "error": problem_text(item.label, self.problems[item.name]) if item.name in self.problems else ""} for item in info.fields]
        alias_error = alias_text(self.problems["name"]) if "name" in self.problems else ""
        asks_terms = self.needs_terms()
        save_ok = self.can_save()
        return {
            "title": T["keys_reg_title"].format(service=service), "intro": T["keys_reg_intro"], "step": self.step, "service": service,
            "a11y": T["keys_reg_a11y"].format(service=service, step=T["keys_reg_step_confirm" if self.step == "confirm" else "keys_reg_step_input"]),
            "alias": {"label": T["keys_alias_label"], "hint": T["keys_reg_alias_hint"], "value": self.alias, "error": alias_error, "a11y": T["keys_reg_alias_a11y"], "max": rules.ALIAS_MAX},
            "provider_label": T["keys_reg_provider"], "providers": providers, "provider_error": T["keys_reg_provider_full"] if "provider" in self.problems else "",
            "fields": fields, "clipboard": T["keys_reg_clipboard"],
            "confirm": {"title": T["keys_reg_confirm_title"], "lines": [T["keys_reg_confirm_service"].format(name=service), T["keys_reg_confirm_provider"].format(name=_shown(provider.label, 40) if provider else ""),
                                                                     T["keys_reg_confirm_alias"].format(name=_shown(rules.normalize_alias(self.alias), rules.ALIAS_MAX))],
                        "note": T["keys_reg_confirm_note"], "terms": {"show": asks_terms, "text": T["keys_reg_terms"], "check": T["keys_reg_terms_check"], "checked": self.terms}},
            "buttons": {"cancel": T["keys_reg_cancel"], "next": T["keys_reg_next"], "back": T["keys_reg_back"],
                        "save": {"text": T["keys_reg_save"], "enabled": save_ok, "reason": "" if save_ok else (T["keys_fail_terms"] if asks_terms and self.step == "confirm" else "")}},
        }


# ---- 컨트롤러 -------------------------------------------------------------------------------------------------------------------------
class KeysController:
    def __init__(self, provider, runner, data=None):
        self.provider, self.runner = provider, runner
        self._data = data or (lambda: None)                  # 지금 화면이 가진 연결 정보를 돌려주는 함수(AppState 가 준다)
        self.notice = None                                   # (수준, 글) — 마지막 동작의 결과(키를 저장했어요·실패 이유 …)
        self.row_notes = {}                                  # 항목 번호 → (수준, 글) — 연결 시험 결과처럼 그 줄에만 붙는 안내
        self.pending = None                                  # 돌고 있는 쓰기: {"kind", "purpose", "ref"}
        self.draft = None                                    # 열려 있는 등록 대화상자의 비밀 아닌 값(`RegisterDraft`)
        self.reload_wanted = False                           # 쓰기가 끝났으니 연결 정보를 다시 읽어야 한다(읽기 작업은 화면이 시작한다)
        self.reloading = False                               # 쓰기가 끝나고 새 값을 읽는 중 — 읽는 동안에도 단추는 꺼져 있다(낡은 목록의 행을 또 눌러 이미 지워진 항목을 다시 건드리지 않게). 새 값을 받으면 꺼진다
        self.focus_after = None                              # 다시 그린 뒤 포커스를 돌려줄 곳의 열쇠(항목 번호 + 행동)
        self.write_count = 0

    # ---- 상태 ----
    def effective_cap(self, info):
        return effective_cap(info)

    @property
    def writable(self):
        return isinstance(self.provider, KeysWriter) and bool(getattr(self.provider, "can_write", False))

    @property
    def busy(self):
        """쓰는 중이거나(작업이 돌고 있다) 쓴 뒤 새 값을 읽는 중이다 — 둘 다 단추가 꺼진다."""
        return self.runner.running(WRITE_KEY) or self.reloading

    def data(self):
        return self._data()

    def store_ready(self):
        """키 저장소를 쓸 수 있다고 공급자가 알려 줬나 — 모르면(None) 못 쓰는 것으로 본다(알려 주지 않은 공급자는 키 행동을 켜지 않는다)."""
        data = self.data()
        return bool(data is not None and data.store_ready is True)

    def info(self, purpose):
        data = self.data()
        return next((item for item in data.purposes if item.key == purpose), None) if data is not None else None

    def entry(self, purpose, ref):
        info = self.info(purpose)
        return next((item for item in info.entries if item.ref == ref), None) if info is not None and ref else None

    # ---- 행동 가능 여부(순수) ----
    def action(self, info, entry, key, *, count=1, index=0, target=""):
        """행 하나의 행동 하나 → `{key, text, enabled, reason, kind, a11y}`. 꺼진 행동은 까닭을 `reason` 에 문장으로 둔다."""
        name = _shown(entry.name, 40) or T["entry_unnamed"]
        busy, ready = self.busy, self.store_ready()
        reason = ""
        if key == "test":
            text, kind = T["keys_act_test"], "secondary"
            if busy:
                reason = T["keys_busy"]
            elif not ready:
                reason = T["keys_store_missing"]
            elif not info.can_test:
                reason = T["keys_why_terms"] if info.test_blocked == "terms" else T["keys_why_prep"]
            elif entry.key_found is False:
                reason = T["keys_why_nokey"]
        elif key == "state":
            text, kind = (T["keys_act_turn_on"] if entry.state == "off" and target == "active" else T["keys_act_to_" + target]), "secondary"
            reason = T["keys_busy"] if busy else ""
        elif key in ("up", "down"):
            text, kind = T["keys_act_" + key], "ghost"
            if busy:
                reason = T["keys_busy"]
            elif key == "up" and index <= 0:
                reason = T["keys_why_first"]
            elif key == "down" and index >= count - 1:
                reason = T["keys_why_last"]
        elif key == "rename":
            text, kind = T["keys_act_rename"], "secondary"
            reason = T["keys_busy"] if busy else (T["keys_store_missing"] if not ready else "")
        else:
            text, kind = T["keys_act_delete"], "danger_ghost"
            reason = T["keys_busy"] if busy else (T["keys_store_missing"] if not ready else "")
        return {"key": key if key != "state" else f"state:{target}", "text": text, "enabled": not reason, "reason": reason, "kind": kind, "a11y": action_a11y(text, name)}

    def row_vm(self, info, entry, index, count, sample=False):
        name = _shown(entry.name, 40) or T["entry_unnamed"]
        shown_state = sv.entry_state(info, entry)
        tones = {"active": "ok", "standby": "info", "off": "muted"}
        badges = [{"text": T["keys_state_badge_" + shown_state], "tone": tones[shown_state]}]
        if count > 1:
            badges.append({"text": T["keys_row_priority"].format(n=index + 1), "tone": "muted"})
        lines = []
        label = provider_label(info, entry.provider)
        if label and len(info.providers) > 1:
            lines.append(T["keys_row_provider"].format(name=_shown(label, 40)))
        when = when_text(entry.last_ok)
        lines.append(T["keys_row_last_ok"].format(when=when) if when else T["keys_row_no_ok"])
        if entry.check in CHECK_TEXT:
            lines.append(T[CHECK_TEXT[entry.check]])
        if entry.key_found is False:
            lines.append(T["keys_row_missing"])
        actions = [self.action(info, entry, "test")]
        choices = sv.state_choices(info)
        for target in STATE_TARGETS.get(shown_state, ()):
            if target in choices:
                actions.append(self.action(info, entry, "state", target=target))
        if count > 1:
            actions += [self.action(info, entry, "up", count=count, index=index), self.action(info, entry, "down", count=count, index=index)]
        actions += [self.action(info, entry, "rename"), self.action(info, entry, "delete")]
        if info.legacy:                                        # 옛 항목은 지울 수만 있다(새 키는 새 용도에 넣는다 — 시험·순서·상태는 의미가 없다)
            actions = [item for item in actions if item["key"] == "delete"]
        note = self.row_notes.get(entry.ref)
        busy_here = bool(self.pending and self.pending.get("ref") == entry.ref and self.pending["kind"] == "test")
        return {"ref": entry.ref, "name": name, "badges": badges, "lines": lines, "actions": actions, "sample": sample,
                "note": {"level": "info", "text": T["keys_testing"]} if busy_here else ({"level": note[0], "text": note[1]} if note else None),
                "a11y": T["keys_row_a11y"].format(name=name, state=T["state_" + shown_state])}

    def register_vm(self, info):
        """카드 아래 '키 등록' 단추 — `{text, enabled, reason, a11y}` 또는 None(키를 받지 않거나 옛 용도·제공자가 없는 카드)."""
        if not info.takes_keys or info.legacy or not info.providers:
            return None
        text = T["keys_register"]
        reason = ""
        if self.busy:
            reason = T["keys_busy"]
        elif not self.store_ready():
            reason = T["keys_store_missing"]
        elif not room_providers(info):
            reason = cap_text(info)
        return {"text": text, "enabled": not reason, "reason": reason, "a11y": T["keys_register_a11y"].format(service=_shown(info.label, 60))}

    def card_keys(self, info, sample=False):
        """용도 카드의 키 구역 — 쓰는 공급자가 아니면 None(카드는 읽기 전용 그대로). 키를 받지 않는 용도(GitHub)도 None(안내 문장은 기존 카드 글이 한다)."""
        if not self.writable or not info.takes_keys:
            return None
        entries = list(info.entries)
        ready = self.store_ready()
        return {"title": T["entries_title"], "none": T["keys_none"] if not entries and not info.legacy else "",
                "rows": [self.row_vm(info, entry, index, len(entries), sample) for index, entry in enumerate(entries)], "register": self.register_vm(info),
                "store_note": {"title": T["keys_store_missing"], "why": T["keys_store_missing_why"]} if not ready else None, "busy": self.busy}

    def delete_dialog(self, info, entry):
        """삭제 확인창의 글 — 무엇이 지워지는지·되돌릴 수 없다는 것(처음 포커스는 취소)."""
        name = _shown(entry.name, 40) or T["keys_del_unnamed"]
        return {"title": T["keys_del_title"], "body": T["keys_del_body"].format(name=name), "ok": T["keys_del_ok"], "cancel": T["keys_del_cancel"]}

    def rename_dialog(self, info, entry):
        name = _shown(entry.name, 40) or T["keys_del_unnamed"]
        return {"title": T["keys_ren_title"], "body": T["keys_ren_body"].format(name=name), "label": T["keys_ren_label"], "ok": T["keys_ren_ok"], "cancel": T["keys_ren_cancel"],
                "value": entry.name, "a11y": T["keys_ren_a11y"], "max": rules.ALIAS_MAX}

    # ---- 등록 대화상자 ----
    def open_register(self, purpose):
        """등록 대화상자를 연다 — 쓸 수 없거나 자리가 없으면 None. 이미 열려 있으면 그대로 돌려준다(입력 유지)."""
        info = self.info(purpose)
        if not self.writable or info is None or self.busy or self.register_vm(info) is None or not self.register_vm(info)["enabled"]:
            return None
        if self.draft is None or self.draft.info.key != purpose:
            self.draft = RegisterDraft(info)
        else:
            self.draft.info = info
        return self.draft

    def close_register(self):
        self.draft = None

    # ---- 쓰기(사용자가 눌렀을 때만) ----
    def _guard(self, purpose, ref=None, *, needs_store=True):
        """쓰기를 시작해도 되는지 — `(상태, 용도 정보, 항목)`. 상태: ok · unavailable(쓸 수 없는 공급자·저장소·없는 대상) · busy."""
        info = self.info(purpose)
        if not self.writable or info is None:
            return "unavailable", None, None
        if self.busy:
            return "busy", info, None
        if needs_store and not self.store_ready():
            return "unavailable", info, None
        entry = None
        if ref is not None:
            entry = self.entry(purpose, ref)
            if entry is None:
                return "unavailable", info, None
        return "ok", info, entry

    def _start(self, kind, purpose, ref, work, callbacks):
        job = self.runner.start(WRITE_KEY, work, **callbacks)
        if job is None:
            return "busy", None
        self.pending = {"kind": kind, "purpose": purpose, "ref": ref or ""}
        self.notice = None
        self.reload_wanted = False
        self.write_count += 1
        if ref:
            self.row_notes.pop(ref, None)
        return "started", job

    def start_add(self, purpose, provider, name, box, terms_ack, **callbacks):
        """키 등록 — `(상태, 내용)`: `("busy", None)` · `("unavailable", None)` · `("invalid", 문제들)`(별칭·제공자·자리·약관 — 서비스를 부르지 않는다) · `("started", 작업)`.
        어떤 길로 끝나도 시작되지 않으면 통은 비워진다(키가 통에 남지 않는다)."""
        status, info, _entry = self._guard(purpose)
        if status != "ok":
            box.discard()
            return status, None
        problems = {}
        chosen = provider_of(info, provider)
        if chosen is None or not has_room(info, chosen):
            problems["provider"] = "full"
        alias_code = rules.alias_problem(name)
        if not alias_code and any(item.name == rules.normalize_alias(name) for item in info.entries):
            alias_code = "duplicate"
        if alias_code:
            problems["name"] = alias_code
            if alias_code == "keyish" and self.draft is not None:
                self.draft.alias = ""                        # 키처럼 보이는 글은 초안에 남기지 않는다
        if chosen is not None and needs_terms(info, provider) and not terms_ack:
            problems["terms"] = "required"
        if problems:
            box.discard()
            if self.draft is not None and self.draft.info.key == purpose:
                self.draft.problems = dict(problems)         # 열려 있는 대화상자가 칸 옆에 문제를 보인다(입력은 남는다 — 키처럼 보이는 별칭만 위에서 비웠다)
            return "invalid", problems
        alias = rules.normalize_alias(name)
        writer = self.provider

        def work(progress, cancelled):
            try:
                return writer.add_key(purpose, provider, alias, box, bool(terms_ack), progress, cancelled)
            finally:
                box.discard()                                # 공급자가 통을 비우지 않고 끝나도(오류·취소) 일이 끝난 뒤의 일 기록에 키가 남지 않는다
        status, job = self._start("add", purpose, "", work, callbacks)
        if job is None:
            box.discard()
        return status, job

    def start_remove(self, purpose, ref, **callbacks):
        status, _info, _entry = self._guard(purpose, ref)
        if status != "ok":
            return status, None
        writer = self.provider
        return self._start("remove", purpose, ref, lambda progress, cancelled: writer.remove_key(purpose, ref, progress, cancelled), callbacks)

    def start_state(self, purpose, ref, state, **callbacks):
        status, info, entry = self._guard(purpose, ref, needs_store=False)
        if status != "ok":
            return status, None
        if state not in sv.state_choices(info) or state == sv.entry_state(info, entry):
            return "unavailable", None
        writer = self.provider
        return self._start("state", purpose, ref, lambda progress, cancelled: writer.set_key_state(purpose, ref, state, progress, cancelled), callbacks)

    def start_rename(self, purpose, ref, name, **callbacks):
        status, info, entry = self._guard(purpose, ref)
        if status != "ok":
            return status, None
        code = rules.alias_problem(name)
        alias = rules.normalize_alias(name)
        if not code and any(item.name == alias and item.ref != ref for item in info.entries):
            code = "duplicate"
        if code:
            return "invalid", {"name": code}
        if alias == entry.name:
            self.notice = ("info", T["keys_ok_unchanged"])
            return "nothing", None
        writer = self.provider
        return self._start("rename", purpose, ref, lambda progress, cancelled: writer.rename_key(purpose, ref, alias, progress, cancelled), callbacks)

    def start_move(self, purpose, ref, direction, **callbacks):
        status, info, entry = self._guard(purpose, ref, needs_store=False)
        if status != "ok":
            return status, None
        position = info.entries.index(entry)
        if not 0 <= position + (-1 if direction < 0 else 1) < len(info.entries):
            return "unavailable", None
        writer = self.provider
        return self._start("move", purpose, ref, lambda progress, cancelled: writer.move_key(purpose, ref, -1 if direction < 0 else 1, progress, cancelled), callbacks)

    def start_test(self, purpose, ref, **callbacks):
        """연결 시험 — 호출 코드가 있는 용도(`can_test`)에서만. 시험에서 실제 네트워크를 부르는 일은 공급자가 정한다(이 컨트롤러는 시험할 수 있는지 먼저 본다)."""
        status, info, entry = self._guard(purpose, ref)
        if status != "ok":
            return status, None
        if not info.can_test or entry.key_found is False:
            return "unavailable", None
        writer = self.provider
        return self._start("test", purpose, ref, lambda progress, cancelled: writer.test_key(purpose, ref, progress, cancelled), callbacks)

    # ---- 끝난 일 받기 ----
    def apply_write_ok(self, outcome):
        """쓰기·시험이 끝났다 — 결과 안내를 정하고 연결 정보를 다시 읽게 한다. 등록이 끝나면 대화상자 상태를 닫는다."""
        work, self.pending = self.pending or {"kind": "", "purpose": "", "ref": ""}, None
        ref = getattr(outcome, "ref", "") or work.get("ref", "")
        if outcome.kind == "tested":
            level, key = TEST_TEXT.get(outcome.result, ("info", "keys_test_error"))
            text = T["keys_test_soon"].format(n=max(1, int(outcome.wait))) if outcome.result == "too_soon" else T[key]
            self.row_notes[ref] = ("info" if outcome.result == "too_soon" else level, text)
            self.notice = None
        else:
            self.notice = ("info" if outcome.kind == "unchanged" else "ok", T[OUTCOME_TEXT.get(outcome.kind, "keys_ok_unchanged")])
        if work["kind"] == "add":
            self.draft = None
        if work["kind"] == "remove":
            self.row_notes.pop(work.get("ref", ""), None)
        self.reload_wanted = outcome.kind != "unchanged" and not (outcome.kind == "tested" and outcome.result in ("not_ready", "too_soon", "no_value"))        # 파일이 바뀐 일만 다시 읽는다
        if work["kind"] in ("state", "move", "rename", "test") and ref:
            self.focus_after = ref
        return self.reload_wanted

    def apply_write_failed(self, failure):
        """쓰기가 실패했다 — 입력(등록의 별칭·제공자)은 남고 키는 다시 입력한다. 문장은 종류별로 정해진 쉬운 말뿐이다. 이미 지워졌거나 파일이 이상하면 다시 읽게 한다.
        **삭제 도중의 저장 실패(`io`·`disk`)**: 서비스는 키 저장소의 키를 먼저 지우고 파일에서 항목을 지운다 — 파일 쓰기에서 실패했다면 키는 이미 지워졌고 항목만 남았다(그 앞 단계에서 실패했다면 아무것도 안 바뀌었다).
        오류 종류만으로는 둘을 구별할 수 없어 '바뀐 것은 없어요' 라고 하지 않고(거짓일 수 있다) 어느 쪽이어도 참인 문장을 보이며 목록을 바로 다시 읽는다 — 키가 이미 지워졌으면 그 행에 '보관소에서 이 키를 찾지 못했어요' 가 보이고
        그 행에서 다시 지우면 정리된다(독립 검증 M1). 다른 쓰기(등록·상태·별칭·순서·시험)의 저장 실패는 사실대로 '바뀐 것은 없어요' 이고 다시 읽지 않는다."""
        work, self.pending = self.pending or {"kind": "", "purpose": "", "ref": ""}, None
        kind = failure.kind if isinstance(failure, KeyFailure) else "other"
        text = failure.user_message if isinstance(failure, KeyFailure) else T["keys_fail_other"]
        if isinstance(failure, JobFailure) and not isinstance(failure, KeyFailure):
            text = T["keys_fail_other"]
        unsure = work["kind"] == "remove" and kind in UNSURE_AFTER_REMOVE
        if unsure:
            text = T["keys_fail_remove_" + kind]               # 키가 이미 지워졌는지 모른다 — '바뀐 것은 없어요' 를 쓰지 않는다(독립 검증 M1)
        elif work["kind"] != "add" and kind in ("io", "invalid") and not (isinstance(failure, KeyFailure) and failure.leftover):
            text = T["keys_fail_" + kind + "_edit"]            # 키를 새로 넣는 일이 아니면 '키는 다시 입력해 주세요' 가 맞지 않는다
        self.notice = ("error", text)
        if work["kind"] == "add" and self.draft is not None:
            self.draft.apply_failure(failure)
        if work["kind"] == "test" and work.get("ref"):
            self.row_notes[work["ref"]] = ("error", text)
        self.reload_wanted = kind in ("notfound", "corrupt") or unsure           # 지우기가 저장 도중 실패했다면 목록의 행이 낡았을 수 있다 — 바로 다시 읽는다
        return kind

    def apply_unexpected(self, error):
        """화면 스레드의 슬롯에서 예상하지 못한 예외가 났다 — 쉬운 문장만(예외 이름도 화면에 두지 않는다). 등록 대화상자의 입력은 남긴다."""
        self.pending = None
        self.reloading = False                               # 새 값을 기다리다 슬롯이 죽어도 단추가 영영 꺼져 있지 않게
        self.notice = ("error", T["keys_fail_other"])
        if self.draft is not None:
            self.draft.step = "input"
        return type(error).__name__


__all__ = ["KeysController", "RegisterDraft", "SecretBox", "alias_text", "problem_text", "when_text"]
