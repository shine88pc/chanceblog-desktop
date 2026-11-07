"""키 연결 화면의 실제 공급자(P4f) — 서비스(`service/connections.py`)를 화면이 아는 모양(`ui/core/keys.py`)으로 맞추는 얇은 어댑터다. **이 앱에서 키를 Windows 자격 증명 관리자에 쓰고 지우는 유일한 어댑터**이고,
쓰는 길은 이 파일의 여섯 메서드(`add_key`·`remove_key`·`set_key_state`·`rename_key`·`move_key`·`test_key`)가 부르는 서비스 함수(`add_entry`·`remove_entry`·`set_state`·`rename_entry`·`reorder`·`test_entry`)뿐이다 —
화면 코드(`ui/qt`·`ui/core`)에는 파일을 쓰거나 보관소를 부르는 호출이 없다(시험이 소스를 훑는다). 읽기(`load_connections`)는 부모(`ui/adapters.py`)의 읽기 전용 그대로다.

**키가 새지 않게**: 키 글은 `SecretBox` 로 들어와 `take()` 로 꺼내 서비스 인자로 곧바로 넘기고, 어떤 길로 끝나도(`finally`) 꺼낸 글을 담은 dict 를 비운다. 서비스 오류(`AppError`)는 **종류**(한도·중복·입력 모양·약관·보관소·없음·잠금·디스크·쓰기 실패·파일 이상)와
**칸 문제 이름**(짧음·글자·키처럼 보임 …)으로만 바꿔 화면에 알린다 — 화면 문장은 `ui/core/text.py` 의 정해진 말이고 오류의 세부·경로·입력한 값은 화면에 나가지 않는다. 바꾼 뒤에는 서비스 오류의 호출 흔적(`__traceback__`)을 끊어
키가 들어 있었을 수 있는 서비스 함수의 지역 변수가 실패 객체를 통해 오래 남지 않게 한다. 이 모듈은 PySide6 를 모른다.

**연결 시험**: 호출 코드가 있는(`implemented`) 용도에 시험 함수(`tester`)를 넣었을 때만 시험하고, 이용 약관을 확인하기 전 용도(`TERMS_PENDING` — NAVER API HUB)는 시험 함수가 있어도 **호출하지 않는다**. 지금은 어느 용도도 호출 코드가 없어 늘 '준비 중' 이다.
"""
from __future__ import annotations

import re

from ..errors import AppError
from ..service import connections as service
from ..service import quota as quota_service
from .adapters import ServiceConnectionsProvider, is_folder
from .core.jobs import JobCancelled
from .core.keys import KeyFailure, KeyOutcome, KeysWriter, make_failure
from .core.services import TERMS_PENDING
from .core.text import T

KIND_OF_CODE = {"KEY_ENTRY_LIMIT": "limit", "KEY_DUPLICATE": "duplicate", "KEY_INVALID_SHAPE": "invalid", "KEY_TOO_LONG": "invalid", "KEY_FAILOVER_TERMS_REQUIRED": "terms", "KEY_STORE_UNAVAILABLE": "store",
                "CONNECTION_NOT_FOUND": "notfound", "KEYS_BUSY": "busy", "DISK_FULL": "disk", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io", "FILE_PATH_TOO_LONG": "io", "DATA_DIR_UNSAFE": "io",
                "CONNECTIONS_FILE_INVALID": "corrupt"}      # 서비스 오류 코드 → 화면이 다르게 다룰 종류(나머지는 `other`)
ITEM_ALIAS = ("이름", "소속 프로젝트")                                   # 서비스가 이름 칸을 가리키는 말 — 화면의 별칭 칸(`name`)
MIN_LEN = re.compile(r"너무 짧습니다\(최소 ([0-9]{1,4})자\)")


def reason_code(reason):
    """서비스가 알린 칸 문제의 이유 문장 → 문제 이름. 서비스의 이유 문장에는 입력한 값이 없고(시험이 지킨다) 여기서도 값을 읽지 않는다. 모르는 문장은 `other`."""
    text = str(reason)
    found = MIN_LEN.match(text)
    if found:
        return f"min:{found.group(1)}"
    for start, code in (("비어 있", "empty"), ("너무 깁니다", "long"), ("키나 토큰처럼", "keyish"), ("키 값이 이름", "value"), ("표시할 수 없는 글자", "unprintable"), ("영문·숫자", "chars"),
                        ("공백·줄바꿈", "hidden"), ("줄바꿈·눈에", "hidden"), ("앞뒤 공백", "hidden")):
        if text.startswith(start):
            return code
    return "other"


def problems_of(error, spec):
    """서비스 오류 → `{입력 칸 이름: 문제 이름}`(없으면 빈 dict). 칸은 서비스가 알려 준 항목 이름('이름'·칸 화면 이름)으로 찾는다."""
    slots = error.slots or {}
    if error.code == "KEY_TOO_LONG":
        return {item.name: "long" for item in spec.fields}
    if error.code == "KEY_DUPLICATE":
        return {"value": "duplicate"} if slots.get("항목") == "같은 값" else {"name": "duplicate"}
    if error.code != "KEY_INVALID_SHAPE":
        return {}
    item, code = slots.get("항목", ""), reason_code(slots.get("이유", ""))
    if item in ITEM_ALIAS:
        return {"name": code}
    named = {field.label: field.name for field in spec.fields}
    return {named[item]: code} if item in named else {}


def failure_of(error, spec=None):
    """서비스 오류 → 화면용 실패(종류 + 진단 코드 + 칸 문제). 문장은 종류별 정해진 말이다."""
    kind = KIND_OF_CODE.get(error.code, "other")
    problems = problems_of(error, spec) if spec is not None else {}
    leftover = error.code == "KEY_STORE_UNAVAILABLE" and str(error.detail).startswith(service.ROLLBACK_FAILED_DETAIL)
    return make_failure(kind, error.code, problems=problems, leftover=leftover)


class ServiceKeysProvider(ServiceConnectionsProvider, KeysWriter):
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None, registry=None, keystore=None, tester=None):
        super().__init__(data_dir, context_factory=context_factory, registry=registry, keystore=keystore)
        self._tester = tester                                                          # 연결 시험 함수 `(용도, 항목, 값) → ProviderResult` — 시험이 가짜를 끼운다(지금 실제 함수는 없다)

    def _can_test(self, spec):
        return bool(self._tester is not None and spec.implemented and spec.takes_keys and spec.key not in TERMS_PENDING)

    def _context(self):
        if self._data_dir is not None and not is_folder(self._data_dir):                  # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(홈·설정과 같다)
            raise KeyFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", kind="io")
        return self._factory(data_dir=self._data_dir)

    def _registry_of(self):
        return self._registry or service.PURPOSES

    def _run(self, purpose, cancelled, work):
        """쓰기 하나 — 취소 신호를 먼저 보고, 서비스 함수가 낸 오류를 종류별 `KeyFailure` 로 바꾼다. 서비스 함수 하나는 중간에 끊을 수 없어(취소 신호를 보지 않는다) 끝까지 간다.
        실패 객체는 `except` 밖에서 낸다(앞의 오류가 `__context__` 로 따라붙어 호출 흔적이 남지 않게) — 서비스 오류의 `__traceback__` 도 끊는다."""
        if cancelled():
            raise JobCancelled()
        spec = self._registry_of().get(purpose)
        failure = None
        try:
            result = work(self._context())
        except KeyFailure:                                                            # 데이터 폴더가 없다는 안내처럼 이미 쉬운 문장인 실패는 그대로
            raise
        except AppError as error:
            failure = failure_of(error, spec)
            error.__traceback__ = None
        except Exception as error:                                                    # 예상하지 못한 오류 — 쉬운 문장 + 예외 이름(진단용)만, 내용은 싣지 않는다
            failure = make_failure("other", type(error).__name__)
            error.__traceback__ = None
        if failure is not None:
            raise failure
        return result

    def add_key(self, purpose, provider, name, secret, terms_ack, progress, cancelled):
        if cancelled():
            secret.discard()
            raise JobCancelled()
        fields = secret.take()
        try:
            self._run(purpose, lambda: False, lambda ctx: service.add_entry(ctx, purpose, name=name, fields=fields, provider=provider, terms_ack=bool(terms_ack), keystore=self._keystore,
                                                                           registry=self._registry_of()))
        finally:
            fields.clear()                                                             # 어떤 길로 끝나도 꺼낸 글을 담은 dict 를 비운다
        return KeyOutcome("added")

    def remove_key(self, purpose, ref, progress, cancelled):
        self._run(purpose, cancelled, lambda ctx: service.remove_entry(ctx, ref, confirmed=True, keystore=self._keystore, registry=self._registry_of()))
        return KeyOutcome("removed", ref=ref)

    def set_key_state(self, purpose, ref, state, progress, cancelled):
        entry, before = self._run(purpose, cancelled, lambda ctx: service.set_state(ctx, ref, state, registry=self._registry_of()))
        return KeyOutcome("state" if entry.state != before else "unchanged", ref=ref)

    def rename_key(self, purpose, ref, name, progress, cancelled):
        entry, before = self._run(purpose, cancelled, lambda ctx: service.rename_entry(ctx, ref, name, keystore=self._keystore, registry=self._registry_of()))
        return KeyOutcome("renamed" if entry.name != before else "unchanged", ref=ref)

    def move_key(self, purpose, ref, direction, progress, cancelled):
        def reorder(ctx):
            registry = self._registry_of()
            ids = [item.entry_id for item in service.load(ctx, registry).of_purpose(purpose)]
            if ref not in ids:
                raise AppError("CONNECTION_NOT_FOUND", {"항목": "항목 번호"})
            position = ids.index(ref)
            target = position + (-1 if direction < 0 else 1)
            if not 0 <= target < len(ids):
                return False
            ids[position], ids[target] = ids[target], ids[position]
            service.reorder(ctx, purpose, ids, registry=registry)
            return True
        moved = self._run(purpose, cancelled, reorder)
        return KeyOutcome("moved" if moved else "unchanged", ref=ref)

    def test_key(self, purpose, ref, progress, cancelled):
        """연결 시험 — 시험 함수가 없거나 호출 코드가 없는 용도·이용 약관 확인 전 용도는 아무것도 부르지 않고 '준비 중' 으로 답한다."""
        def check(ctx):
            registry = self._registry_of()
            spec = registry[purpose]
            tester = self._tester if self._can_test(spec) else None
            guard = quota_service.QuotaGuard(ctx, registry=registry) if tester is not None else None
            return service.test_entry(ctx, ref, tester, keystore=self._keystore, guard=guard, registry=registry)
        found = self._run(purpose, cancelled, check)
        if not found.ran:
            return KeyOutcome("tested", {"too_soon": "too_soon", "no_value": "no_value"}.get(found.reason, "not_ready"), wait=int(found.wait_seconds or 0), ref=ref)
        return KeyOutcome("tested", found.outcome if found.outcome in ("ok", "auth_failed", "rate_limited") else "error", ref=ref)
