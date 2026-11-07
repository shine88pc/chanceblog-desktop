"""키 연결(P4f)이 아는 값과 쓰기 공급자의 모양 + 가짜 공급자 — 화면은 이 모양만 안다. 실제 서비스(`service/connections.py`)는 얇은 어댑터(`ui/keys_adapter.py`)가 같은 모양으로 맞춘다. PySide6 도 파일도 보관소도 모른다.

**키 원문이 지나가는 길은 `SecretBox` 하나다.** 입력 칸의 글은 `SecretBox` 에 담겨 서비스 함수의 인자로 곧바로 넘어가고(`take()` 하면 통이 비워진다), 뷰모델·상태·값 클래스(`dataclass`)·결과·로그·예외 문구·진단 정보 어디에도 들어가지 않는다.
이 모양의 어떤 값(`KeyFailure`·`KeyOutcome`·`EntryInfo`)에도 키·키의 일부·길이·문자 구성을 담는 칸이 없다 — 시험이 칸 이름과 값을 훑는다.

가짜 공급자(`FakeKeysProvider` — `--sample`·시험·사진)는 **메모리에서만** 일하고 **키를 보관하지도 않는다**(받은 글은 검사한 뒤 바로 버린다) — 키를 등록·지워도 이 PC 에 아무것도 남지 않는다. 이름은 모두 지어낸 예시다.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

from . import key_rules as rules
from .jobs import JobCancelled, JobFailure
from .services import _FIELD_TABLE, _PROVIDER_TABLE, EntryInfo, FakeConnectionsProvider, sample_connections
from .text import T

KINDS_OF_FAILURE = ("limit", "duplicate", "invalid", "terms", "store", "notfound", "busy", "io", "disk", "corrupt", "other")
TEST_RESULTS = ("ok", "auth_failed", "rate_limited", "error", "not_ready", "too_soon", "no_value")
OUTCOME_KINDS = ("added", "removed", "state", "renamed", "moved", "tested", "unchanged")
SAMPLE_STAMP = "2026-11-07T05:20:00Z"                       # 예시 공급자가 '마지막 성공' 에 적는 고정 시각(예시일 뿐이다)


class KeyFailure(JobFailure):
    """키 연결의 실패 — 쉬운 문장(`user_message`)과 진단용 코드, 그리고 화면이 다르게 다룰 종류(`kind`)다. 문장은 종류별로 정해진 말이라 서비스 오류의 세부·경로·입력한 값이 들어가지 않는다.
    `problems` 는 `{입력 칸 이름: 문제 이름}`(`invalid`·`duplicate` 일 때 — 별칭 칸은 `name`, 숫자가 필요한 문제는 `min:16` 처럼 숫자를 단다; 입력한 글은 없다), `leftover` 는 등록 도중 실패해 보관소에 넣은 키를 지우지도 못한 때다."""

    def __init__(self, user_message, code="", *, kind="other", problems=None, leftover=False, retryable=True):
        super().__init__(user_message, code, retryable)
        self.kind = kind if kind in KINDS_OF_FAILURE else "other"
        self.problems = dict(problems or {})
        self.leftover = bool(leftover)


def failure_text(kind, *, leftover=False, problems=None):
    """실패 종류 → 정해진 쉬운 문장(입력한 글 없음)."""
    if leftover:
        return T["keys_fail_leftover"]
    if kind == "duplicate":
        return T["keys_fail_duplicate_value" if (problems or {}).get("value") else "keys_fail_duplicate_name"]
    return T.get("keys_fail_" + kind, T["keys_fail_other"])


def make_failure(kind, code="", *, problems=None, leftover=False):
    return KeyFailure(failure_text(kind, leftover=leftover, problems=problems), code, kind=kind, problems=problems, leftover=leftover)


@dataclass(frozen=True)
class KeyOutcome:
    """쓰기·시험이 끝난 결과 — 어느 일이 어떻게 됐는지뿐이다(이름·키 없음)."""
    kind: str                         # `OUTCOME_KINDS`
    result: str = ""                  # tested 일 때 `TEST_RESULTS` 중 하나
    wait: int = 0                     # too_soon 일 때 다시 시험할 수 있기까지 남은 초
    ref: str = ""                     # 행동의 대상 항목 번호(글이 아니다)


class SecretBox:
    """입력 칸에서 서비스 함수로 가는 동안만 키 글을 들고 있는 **일회용 통** — 칸 이름 → 글. `take()` 로 꺼내면 통이 비워지고(`discard()` 도 같다), `repr`·`str`·`format` 은 글을 보이지 않으며 복사·직렬화는 거절한다.
    작업 스레드에 넘기는 일감(클로저)은 이 통만 쥔다 — 일이 끝난 뒤에도 일감이 남아 있어도 키는 거기 없다."""

    __slots__ = ("_fields",)

    def __init__(self):
        object.__setattr__(self, "_fields", {})

    def __setattr__(self, name, value):
        raise AttributeError("통의 칸은 바꿀 수 없다")

    def put(self, name, text):
        """칸 하나의 글을 담는다(이미 있으면 바꾼다)."""
        self._fields[str(name)] = str(text)
        return self

    def names(self):
        """담긴 칸 이름들(글은 보이지 않는다)."""
        return tuple(self._fields)

    def take(self):
        """담긴 글 전부를 새 dict 로 꺼내고 통을 비운다 — 받은 쪽이 쓰고 곧 비워야 한다."""
        found = dict(self._fields)
        self._fields.clear()
        return found

    def discard(self):
        self._fields.clear()

    def __len__(self):
        return len(self._fields)

    def __bool__(self):
        return bool(self._fields)

    def __repr__(self):
        return f"<SecretBox 칸 {len(self._fields)}개 — 값은 가려져 있음>"

    __str__ = __repr__

    def __format__(self, spec):
        return repr(self)

    def __reduce__(self):
        raise TypeError("비밀 값 통은 직렬화하지 않는다")

    def __copy__(self):
        raise TypeError("비밀 값 통은 복사하지 않는다")

    def __deepcopy__(self, memo):
        raise TypeError("비밀 값 통은 복사하지 않는다")

    def __eq__(self, other):
        return self is other

    __hash__ = object.__hash__


class KeysWriter:
    """연결 공급자에 더하는 **쓰기** 메서드 — 모두 작업 스레드에서 불리고 사용자가 단추를 눌렀을 때만 불린다(읽기 `load_connections` 는 파일도 보관소도 바꾸지 않는다). 이 모양을 가진 공급자만 설정 화면에 키 행동 단추가 생긴다.
    `secret` 은 `SecretBox` 다(받은 쪽이 `take()` 로 꺼내 쓰고 곧 비운다). 실패는 `KeyFailure` 로 알린다."""

    can_write = True

    def add_key(self, purpose, provider, name, secret, terms_ack, progress, cancelled):
        raise NotImplementedError

    def remove_key(self, purpose, ref, progress, cancelled):
        raise NotImplementedError

    def set_key_state(self, purpose, ref, state, progress, cancelled):
        raise NotImplementedError

    def rename_key(self, purpose, ref, name, progress, cancelled):
        raise NotImplementedError

    def move_key(self, purpose, ref, direction, progress, cancelled):
        raise NotImplementedError

    def test_key(self, purpose, ref, progress, cancelled):
        raise NotImplementedError


def _field_code(text, min_len):
    """키 글 하나의 문제 이름('' 이면 문제 없음) — 글은 이 함수 안에서만 쓰고 돌려주지 않는다(예외가 날 때 호출 흔적에 글이 남지 않게 별도 함수로 둔다)."""
    code = rules.secret_problem(rules.clean_secret(text))
    if not code and len(rules.clean_secret(text)) < min_len:
        return f"min:{min_len}"
    return code


def _pause(seconds, cancelled):
    end = time.monotonic() + seconds
    while seconds and time.monotonic() < end:
        if cancelled():
            raise JobCancelled()
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


class FakeKeysProvider(FakeConnectionsProvider, KeysWriter):
    """메모리에서만 일하는 가짜 공급자 — 키 등록·지우기·상태·별칭·순서·시험이 모두 메모리 안에서만 바뀐다(파일·보관소·서비스를 부르지 않고 **받은 키는 검사한 뒤 바로 버린다**). 규칙은 서비스와 같다(시험이 같은 일을 둘에 해 보고 견준다).
    `store_ready=False` 는 키 저장소를 못 쓰는 환경 흉내, `test_result` 는 연결 시험이 돌려줄 결과를 정한다(`ok`·`auth_failed`·`rate_limited`·`error`)."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0, *, store_ready=True, test_result="ok"):
        super().__init__(scenario, delay)
        self.store_ready, self.test_result = store_ready, test_result
        self.writes = []                                     # 부른 쓰기 이름들(시험이 본다)
        self._lock = threading.Lock()
        self._entries = None                                 # 용도 → [EntryInfo] — 처음 읽을 때 예시로 채우고 이후 메모리에서만 바뀐다
        self._touched = set()
        self._counter = 0

    # ---- 읽기 ----
    def _purposes(self):
        return () if self.scenario == "empty" else sample_connections(self.scenario)

    def _ensure(self):
        """처음 한 번 예시 항목으로 메모리 표를 채운다(잠금 안에서 부른다)."""
        if self._entries is None:
            self._entries = {info.key: list(info.entries) for info in self._purposes()}

    def load_connections(self, progress, cancelled):
        data = super().load_connections(progress, cancelled)
        with self._lock:
            self._ensure()
            infos = tuple(self._merged(info) for info in data.purposes)
        return replace(data, purposes=infos, store_ready=bool(self.store_ready) and data.store_ready is not False)

    def _merged(self, info):
        entries = tuple(self._entries.get(info.key, info.entries))
        status = info.status
        if info.key in self._touched and info.takes_keys:
            status = self._derived_status(info, entries)
        return replace(info, entries=entries, status=status)

    @staticmethod
    def _derived_status(info, entries):
        if not entries:
            return "not_connected"
        if any(item.check == "auth_failed" and item.state != "off" for item in entries):
            return "auth_error"
        if info.implemented and any(item.check == "ok" and item.state == "active" for item in entries):
            return "connected"
        return "needs_check"

    def _info(self, purpose):
        found = next((info for info in self._purposes() if info.key == purpose), None)
        if found is None:
            raise make_failure("notfound", "SAMPLE_NOT_FOUND")
        return found

    # ---- 쓰기(모두 메모리 안에서만) ----
    def _enter(self, name, cancelled):
        self.writes.append(name)
        _pause(self.delay, cancelled)
        if cancelled():
            raise JobCancelled()
        with self._lock:
            self._ensure()

    def _find(self, purpose, ref):
        entries = self._entries.get(purpose, [])
        for index, item in enumerate(entries):
            if item.ref == ref:
                return entries, index
        raise make_failure("notfound", "SAMPLE_NOT_FOUND")

    def _renumber(self, purpose):
        self._entries[purpose] = [replace(item, order=number) for number, item in enumerate(self._entries[purpose], start=1)]

    def add_key(self, purpose, provider, name, secret, terms_ack, progress, cancelled):
        fields = secret.take()
        try:
            self._enter("add", cancelled)
            info = self._info(purpose)
            table = _PROVIDER_TABLE.get(purpose, ())
            chosen = next((row for row in table if row[0] == (provider or (table[0][0] if table else ""))), None)
            if not info.takes_keys or info.legacy or chosen is None:
                raise make_failure("invalid", "SAMPLE_INVALID", problems={"name": "other"})
            problems = {}
            alias_code = rules.alias_problem(name)
            if alias_code:
                problems["name"] = alias_code
            for field_name, _label, min_len in _FIELD_TABLE.get(purpose, ()):
                code = _field_code(fields.get(field_name, ""), min_len)
                if code:
                    problems[field_name] = code
            if problems:
                raise make_failure("invalid", "SAMPLE_INVALID", problems=problems)
            with self._lock:
                mine = self._entries.setdefault(purpose, [])
                same = [item for item in mine if item.provider == chosen[0]]
                if len(same) >= chosen[2] or len(mine) >= info.max_entries:
                    raise make_failure("limit", "SAMPLE_ENTRY_LIMIT")
                if same and chosen[3] and not terms_ack:
                    raise make_failure("terms", "SAMPLE_TERMS_REQUIRED")
                alias = rules.normalize_alias(name)
                if any(item.name == alias for item in mine):
                    raise make_failure("duplicate", "SAMPLE_DUPLICATE", problems={"name": "duplicate"})
                self._counter += 1
                ref = f"sample-new-{self._counter}"
                mine.append(self._new_entry(alias, ref, chosen[0], len(mine) + 1))
                self._touched.add(purpose)
            return KeyOutcome("added", ref=ref)
        finally:
            fields.clear()                                   # 받은 글은 검사한 뒤 바로 버린다 — 이 공급자는 키를 보관하지 않는다

    @staticmethod
    def _new_entry(name, ref, provider, order):
        return EntryInfo(name, "active", True, ref, provider, "", "", order)

    def remove_key(self, purpose, ref, progress, cancelled):
        self._enter("remove", cancelled)
        with self._lock:
            entries, index = self._find(purpose, ref)
            del entries[index]
            self._renumber(purpose)
            self._touched.add(purpose)
        return KeyOutcome("removed", ref=ref)

    def set_key_state(self, purpose, ref, state, progress, cancelled):
        self._enter("state", cancelled)
        if state not in ("active", "standby", "off"):
            raise make_failure("invalid", "SAMPLE_INVALID")
        with self._lock:
            entries, index = self._find(purpose, ref)
            if entries[index].state == state:
                return KeyOutcome("unchanged", ref=ref)
            entries[index] = replace(entries[index], state=state)
            self._touched.add(purpose)
        return KeyOutcome("state", ref=ref)

    def rename_key(self, purpose, ref, name, progress, cancelled):
        self._enter("rename", cancelled)
        alias_code = rules.alias_problem(name)
        if alias_code:
            raise make_failure("invalid", "SAMPLE_INVALID", problems={"name": alias_code})
        alias = rules.normalize_alias(name)
        with self._lock:
            entries, index = self._find(purpose, ref)
            if entries[index].name == alias:
                return KeyOutcome("unchanged", ref=ref)
            if any(item.name == alias for other, item in enumerate(entries) if other != index):
                raise make_failure("duplicate", "SAMPLE_DUPLICATE", problems={"name": "duplicate"})
            entries[index] = replace(entries[index], name=alias)
        return KeyOutcome("renamed", ref=ref)

    def move_key(self, purpose, ref, direction, progress, cancelled):
        self._enter("move", cancelled)
        with self._lock:
            entries, index = self._find(purpose, ref)
            target = index + (-1 if direction < 0 else 1)
            if not 0 <= target < len(entries):
                return KeyOutcome("unchanged", ref=ref)
            entries[index], entries[target] = entries[target], entries[index]
            self._renumber(purpose)
        return KeyOutcome("moved", ref=ref)

    def test_key(self, purpose, ref, progress, cancelled):
        self._enter("test", cancelled)
        info = self._info(purpose)
        with self._lock:
            entries, index = self._find(purpose, ref)
            if not info.can_test:
                return KeyOutcome("tested", "not_ready", ref=ref)
            result = self.test_result if self.test_result in ("ok", "auth_failed", "rate_limited", "error") else "error"
            check = {"ok": "ok", "auth_failed": "auth_failed"}.get(result, "error")
            entries[index] = replace(entries[index], check=check, last_ok=SAMPLE_STAMP if result == "ok" else entries[index].last_ok)
            self._touched.add(purpose)
        return KeyOutcome("tested", result, ref=ref)


__all__ = ["FakeKeysProvider", "KeyFailure", "KeyOutcome", "KeysWriter", "SecretBox", "failure_text", "make_failure"]
