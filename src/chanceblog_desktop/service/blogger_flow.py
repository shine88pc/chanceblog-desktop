"""Blogger 초안 저장 흐름 — 로그인·연결 확인·**초안 저장**·연결 해제·재인증(BLOGGER 설계서 3.6–3.8·3.11–3.12, 결정 D-774, 운영자 확인 038 ③ — 스위치는 모두 꺼진 채 구현·검증 준비까지).

사용자가 단추를 눌렀을 때만 일어나는 일 다섯 가지이고 공개 함수의 첫 문장은 모두 관문이다:
  · `login` — 시스템 브라우저 + 루프백 창구(`net/loopback.py`) + PKCE 로 구글 로그인을 하고 받은 **갱신용 값을 자격 증명 관리자에만** 보관한다(파일 폴백 없음 — 보관소가 없으면 시작하지 않는다). `require_net("blogger_oauth")`.
  · `check` — 블로그 번호로 이름·주소를 읽어 **사람이 맞는지 보게** 한다. 맞다고 확인하면(`confirmed`) 항목에 '연결됨(시각)' 을 적는다. `require_net("blogger_read")`.
  · `save_draft` — 승인한 글 하나를 Blogger **초안으로만** 저장한다. 첫 두 문장이 `require_external_write` 와 `require_net("blogger_draft")` 이고 확인(`--yes`)이 없으면 아무것도 하지 않는다.
  · `disconnect` — 구글에 토큰 취소를 **먼저** 요청하고 성공해야 보관소의 갱신용 값을 지운다(오프라인이면 아무것도 지우지 않고 오류로 알린다 — '이 PC 의 값만 지움' 은 두 번 확인해야 한다). `require_net("blogger_oauth")`.
  · `status` — 읽기만 한다(접속 없음): 항목이 있나·로그인했나·마지막 연결 확인.

**초안 저장은 요청 한 건이다**(설계 3.7): 점검 → 렌더·검사 → 한도(`QuotaGuard`) → **저널을 먼저 쓴다**(`publish/blogger/<글번호>-<슬롯>.json` — 본문·토큰·제목 글자 없이 해시만) → 접근 토큰 → **B 요청 한 번** → 응답 검사 → 초안인지 확인(D) → 상태 `DRAFT_SAVED`(글번호를 `remote_id` 에) → 저널 삭제.
쓰기는 **자동으로 다시 보내지 않는다** — 401(접근 토큰 만료) 뒤 갱신해 한 번 다시 보내는 것이 유일한 예외다(처리되지 않은 요청이라 안전하다). 보낸 뒤에 끊기거나 5xx 면 서버가 저장했을 수 있으므로 같은 제목의 초안을 먼저 찾아(C) 정확히 하나면 이어받고 아니면
`BLOGGER_DRAFT_UNKNOWN` 으로 멈춘다(사람이 Blogger 에서 확인). 앱이 꺼졌다 켜졌을 때 저널이 남아 있으면 새로 보내기 전에 같은 확인을 먼저 한다. 공개(LIVE) 같은 초안이 아닌 답은 즉시 멈추고(`BLOGGER_NOT_DRAFT`, 상태는 `PUBLISH_FAILED`) 더 하지 않는다.
영문·한글은 **다른 블로그**다 — 슬롯은 항목 이름(`영문`·`한글`)으로 찾고 항목의 토큰·클라이언트·블로그 번호는 섞이지 않으며 한쪽이 막혀도 다른 쪽으로 넘기지 않는다(제공자 `ROTATION_NEVER`). 모든 요청은 `QuotaGuard.acquire_entry` 로 받는다.
토큰·인증 코드·검증기·`state` 는 오류·로그·접속 기록·저널 어디에도 쓰지 않는다(접근 토큰은 메모리에만, 값 객체는 `repr` 에 값이 없다).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .. import capabilities
from ..content import status as st
from ..errors import AppError
from ..net import loopback
from ..net.errors import NetError
from ..publish import blogger as api
from ..publish import blogger_auth as auth
from ..render import blogger as render
from ..security import refuse
from . import blog_profiles, external, gate, quota
from . import connections as cn
from .context import write_json
from .lock import PublishLock
from .projects import require_confirmation, resolve_id

SLOT_NAME = {"blogger_en": "영문", "blogger_ko": "한글"}
SLOT_LANG = {"blogger_en": "en", "blogger_ko": "ko"}
SLOTS = tuple(SLOT_NAME)
_ALIAS = {"blogger_en": "blogger_en", "en": "blogger_en", "영문": "blogger_en", "blogger_ko": "blogger_ko", "ko": "blogger_ko", "한글": "blogger_ko"}
JOURNAL_FOLDER = "blogger"
WINDOW_BEFORE = timedelta(minutes=5)                 # 서버 시계와 이 PC 시계가 조금 달라도 같은 제목 초안을 알아본다
WINDOW_AFTER = timedelta(minutes=15)                 # 저널을 쓴 때부터 이 시간 안에 고쳐진 같은 제목의 초안만 '방금 보낸 것' 으로 이어받는다(설계 3.7)
STATE_NOT_CONNECTED, STATE_LOGIN_NEEDED, STATE_NEEDS_CHECK, STATE_CONNECTED = "not_connected", "login_needed", "needs_check", "connected"
STATE_TEXT = {STATE_NOT_CONNECTED: "연결 안 됨", STATE_LOGIN_NEEDED: "로그인 필요", STATE_NEEDS_CHECK: "연결 확인 필요", STATE_CONNECTED: "연결됨"}      # 슬롯의 상태 말(항목 상태 다섯 가지와 따로 — 로그인 전후를 가른다)
STAGE_SENDING, STAGE_UNKNOWN = "sending", "unknown"
STAGES = (STAGE_SENDING, STAGE_UNKNOWN)
JOURNAL_SCHEMA = 1
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HASH = re.compile(r"[0-9a-f]{64}")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_NUMBER = re.compile(r"[0-9]{1,25}")

_ACCESS = {}                                         # 항목 번호 → 접근 토큰(메모리만 — 연결 해제·새 로그인·앱 종료 때 사라진다)
_LOGIN_LOCK = threading.Lock()                       # 로그인은 앱 안에서 하나만(L12)


def forget(entry_id=None):
    """메모리의 접근 토큰을 버린다(하나 또는 모두)."""
    if entry_id is None:
        _ACCESS.clear()
    else:
        _ACCESS.pop(entry_id, None)


# ---- 슬롯·항목·자격 ------------------------------------------------------------------------------------------------------------------------
def slot_key(text):
    """`영문`·`한글`·`en`·`ko`·`blogger_en`·`blogger_ko` → 슬롯 열쇠. 그 밖은 CONTENT_INVALID(입력한 글은 싣지 않는다)."""
    key = _ALIAS.get(text.strip()) if isinstance(text, str) else None
    if key is None:
        raise AppError("CONTENT_INVALID", {"항목": "Blogger 구분(영문 또는 한글)"})
    return key


def find_entry(ctx, slot, registry=cn.PURPOSES):
    """슬롯의 연결 항목(이름이 `영문`·`한글` 인 Blogger 항목) 또는 None."""
    data = cn.load(ctx, registry)
    return next((item for item in data.of_purpose(cn.BLOGGER_PURPOSE) if item.name == SLOT_NAME[slot]), None)


def _require_entry(ctx, slot):
    entry = find_entry(ctx, slot)
    if entry is None:
        raise AppError("BLOGGER_NOT_CONNECTED")
    return entry


def _credentials(entry, keystore, *, need_refresh):
    """보관소의 값 묶음(`SecretFields`) — 클라이언트 두 칸이 있어야 하고, 필요하면 갱신용 값도 있어야 한다. 없으면 BLOGGER_NOT_CONNECTED."""
    found = keystore.get(entry.ref)
    if found is None or "client_id" not in found or "client_secret" not in found or (need_refresh and "refresh_token" not in found):
        raise AppError("BLOGGER_NOT_CONNECTED")
    return found


def _blog_id(ctx, slot):
    """채널 프로필의 블로그 번호(`blog_ref`) — **숫자만**(주소는 받지 않는다 — 설계 Q3). 아니면 CONTENT_INVALID."""
    profile = next((item for item in blog_profiles.read_snapshot(ctx).profiles if item.key == slot), None)
    ref = (profile.blog_ref if profile is not None else str()).strip()
    if _NUMBER.fullmatch(ref) is None:
        raise AppError("CONTENT_INVALID", {"항목": "블로그 번호(숫자)"}, detail="블로그 관리의 'Blogger 블로그 번호' 칸에 Blogger 대시보드 주소의 숫자를 넣어 주세요")
    return ref


def make_blogger_adapter(**parts):
    """`blogger` 어댑터 공장 — 접속 클라이언트를 만드는 **유일한 곳**이다(스위치가 꺼진 기본 빌드에서는 부르는 코드도 등록도 없다). 접속 틀은 여기서만 불러온다."""
    from ..net.client import NetClient
    from ..net.endpoints import app_version
    return api.BloggerAdapter(NetClient(version=app_version()))


# ---- 한도 -----------------------------------------------------------------------------------------------------------------------------------
def _outcome_of(error):
    code = getattr(error, "code", "")
    if code == "API_RATE_LIMITED":
        return quota.RATE_LIMITED
    if code == "NETWORK_TIMEOUT":
        return quota.TIMEOUT
    if code in ("BLOGGER_SERVER_ERROR", "API_SERVER_ERROR"):
        return quota.TRANSIENT
    if code == "REQUEST_INVALID":
        return quota.BAD_REQUEST
    return quota.OTHER_ERROR           # 인증 거절(401·`invalid_grant`)도 여기다 — '인증 실패' 로 적으면 그 항목이 멈춰 다시 로그인하는 길까지 막힌다


def _denied(denied):
    """`QuotaGuard` 가 막은 이유 → 오류(한도라서 쉬는 시각이 있으면 그것을 알린다)."""
    if denied.code == "busy":
        return AppError("KEYS_BUSY")
    if denied.code == "unavailable":
        return AppError("QUOTA_STATE_INVALID")
    when = quota.QuotaGuard._retry_text(denied.retry_at) if denied.retry_at is not None else str()
    return AppError("API_RATE_LIMITED", {"재시도 가능 시각": when})


class _Meter:
    """요청 하나마다 한도를 잡고(`acquire_entry` — **항목을 콕 집어**, 다른 항목으로 넘기지 않는다) 결과를 알린다."""

    def __init__(self, ctx, entry):
        self.guard = quota.QuotaGuard(ctx)
        self.entry = entry
        self.notes = []

    def call(self, kind, function):
        lease = self.guard.acquire_entry(self.entry, calls=1, priority=quota.CRITICAL, kind=kind)
        if isinstance(lease, quota.Denied):
            raise _denied(lease)
        try:
            result = function()
        except NetError as error:
            self._report(lease, _outcome_of(error), getattr(error, "retry_after", None))
            raise
        except BaseException:
            self._report(lease, quota.OTHER_ERROR, None)
            raise
        self._report(lease, quota.OK, None)
        return result

    def _report(self, lease, outcome, retry_after):
        try:
            self.guard.report(lease, outcome, retry_after=retry_after)
        except AppError:
            note = "사용량 기록을 마저 쓰지 못했어요"
            if note not in self.notes:
                self.notes.append(note)


def _access(ctx, entry, secrets, adapter, meter, *, force=False):
    """메모리의 접근 토큰 — 유효한 것이 없으면(또는 `force`) 갱신 요청(E)을 한다. 갱신이 거절되면 `BLOGGER_AUTH_EXPIRED` — 자동으로 다시 로그인하지 않는다."""
    now = ctx.now().timestamp()
    cached = _ACCESS.get(entry.entry_id)
    if cached is not None and not force and cached.usable(now):
        return cached
    forget(entry.entry_id)
    token = meter.call("blogger_refresh", lambda: adapter.refresh(secrets, now=now))
    _ACCESS[entry.entry_id] = token
    return token


def _api(ctx, entry, secrets, adapter, meter, kind, call):
    """API 요청 하나 — 접근 토큰으로 `call(값)`. 서버가 401(토큰 만료·취소)이라고 하면 토큰을 **한 번** 갱신해 같은 요청을 **한 번** 다시 보낸다(처리되지 않은 요청이라 안전하다 — 유일한 자동 재전송)."""
    token = _access(ctx, entry, secrets, adapter, meter)
    try:
        return meter.call(kind, lambda: call(token))
    except NetError as error:
        if error.code != "BLOGGER_AUTH_EXPIRED":
            raise
    token = _access(ctx, entry, secrets, adapter, meter, force=True)
    return meter.call(kind + "_again", lambda: call(token))


# ---- 상태 -----------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SlotStatus:
    slot: str
    name: str
    has_entry: bool
    logged_in: bool
    state: str
    state_text: str
    checked_at: str
    last_ok_at: str
    blog_id_ok: bool
    store_ok: bool

    def to_dict(self):
        return {"slot": self.slot, "name": self.name, "has_entry": self.has_entry, "logged_in": self.logged_in, "state": self.state, "state_text": self.state_text,
                "checked_at": self.checked_at, "last_ok_at": self.last_ok_at, "blog_id_ok": self.blog_id_ok, "store_ok": self.store_ok}


def status(ctx, slot, *, keystore=None):
    """슬롯의 상태 — 읽기만 한다(접속 없음, 값은 꺼내 쓰지 않고 칸 이름만 본다). 보관소를 못 열면 `store_ok` 가 거짓이고 '연결 확인 필요' 다."""
    slot = slot_key(slot)
    entry = find_entry(ctx, slot)
    try:
        profile = next((item for item in blog_profiles.read_snapshot(ctx).profiles if item.key == slot), None)
        blog_id_ok = profile is not None and _NUMBER.fullmatch(profile.blog_ref.strip()) is not None
    except AppError:
        blog_id_ok = False
    if entry is None:
        return SlotStatus(slot, SLOT_NAME[slot], False, False, STATE_NOT_CONNECTED, STATE_TEXT[STATE_NOT_CONNECTED], str(), str(), blog_id_ok, True)
    try:
        keystore = ctx.get_keystore() if keystore is None else keystore
        logged_in = cn.has_refresh_token(ctx, entry, keystore=keystore)
    except AppError:
        return SlotStatus(slot, entry.name, True, False, STATE_NEEDS_CHECK, STATE_TEXT[STATE_NEEDS_CHECK], entry.checked_at, entry.last_ok_at, blog_id_ok, False)
    if not logged_in:
        state = STATE_LOGIN_NEEDED
    else:
        state = STATE_CONNECTED if cn.entry_status(entry, cn.PURPOSES[cn.BLOGGER_PURPOSE], now=ctx.now(), secret_present=True) == cn.CONNECTED else STATE_NEEDS_CHECK
    return SlotStatus(slot, entry.name, True, bool(logged_in), state, STATE_TEXT[state], entry.checked_at, entry.last_ok_at, blog_id_ok, True)


# ---- 로그인 ---------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LoginResult:
    slot: str
    replaced: bool             # 이미 로그인돼 있던 것을 새로 받은 값으로 바꿨다
    notes: tuple

    def to_dict(self):
        return {"slot": self.slot, "replaced": self.replaced, "notes": list(self.notes)}


def login(ctx, slot, *, open_url, cancelled=None, keystore=None, adapter=None, seconds=loopback.TOTAL_SECONDS):
    """구글 로그인 한 번 — 창구를 열고(바깥 주소로 나가는 연결 없음) 로그인 주소를 `open_url` 로 시스템 브라우저에 열게 하고(주소는 **한 번 더 모양을 본다**) 돌아온 코드를 PKCE 로 교환해 갱신용 값을 보관소에 쓴다.
    이미 로그인돼 있으면 새 값을 받은 **뒤에** 이전 갱신 값을 구글에서 취소해 보고(실패해도 알림만) 덮어쓴다. 어떤 실패도 아무것도 저장하지 않는다."""
    capabilities.require_net("blogger_oauth", "Blogger 로그인")
    slot = slot_key(slot)
    keystore = ctx.get_keystore() if keystore is None else keystore                 # 못 열면 KEY_STORE_UNAVAILABLE — 파일로 대신하지 않고 시작하지 않는다
    entry = _require_entry(ctx, slot)
    secrets = _credentials(entry, keystore, need_refresh=False)
    adapter = external.blogger_adapter() if adapter is None else adapter
    if not _LOGIN_LOCK.acquire(blocking=False):
        raise auth.login_failed(auth.REASON_BUSY)
    try:
        return _login(ctx, slot, entry, secrets, keystore, adapter, open_url, cancelled, seconds)
    finally:
        _LOGIN_LOCK.release()


def _login(ctx, slot, entry, secrets, keystore, adapter, open_url, cancelled, seconds):
    from ..ui.core import open_url as shapes                                       # 열 수 있는 주소 모양 표(순수) — 늦게 가져온다
    try:
        listener = loopback.open_listener()
    except loopback.LoginWindowError as error:
        raise auth.login_failed(auth.LISTENER_REASON[error.reason]) from None
    with listener:
        request = adapter.begin_login(secrets, listener.port)
        if shapes.check_open_url(request.url) != shapes.KIND_LOGIN:                # 만든 주소가 열기 함수가 받는 모양과 다르면 열지 않는다
            raise auth.login_failed(auth.REASON_NO_WINDOW)
        try:
            open_url(request.url)
        except Exception:                                                          # noqa: BLE001 - 브라우저를 못 열었다 — 어떤 예외든 이유 낱말 하나로 바꾼다(예외 문장·주소는 버린다)
            raise auth.login_failed(auth.REASON_NO_WINDOW) from None
        try:
            callback = listener.wait(request.state, cancelled=cancelled, seconds=seconds)
        except loopback.LoginWindowError as error:
            raise auth.login_failed(auth.LISTENER_REASON[error.reason]) from None
    if callback.error or not callback.code:
        raise auth.login_failed(auth.REASON_DENIED if callback.error == "access_denied" else auth.REASON_NO_VALUE)
    meter = _Meter(ctx, entry)
    now = ctx.now().timestamp()
    tokens = meter.call("blogger_login", lambda: adapter.exchange(secrets, callback.code, request.verifier, request.redirect_uri, now=now))
    notes = list(meter.notes)
    previous = "refresh_token" in secrets
    if previous:                                                                   # 새 갱신 값을 받았으니 이전 것을 먼저 취소해 본다(계정·클라이언트당 100개 한도에서 오래된 것이 조용히 무효가 되는 일을 줄인다)
        try:
            meter.call("blogger_revoke_old", lambda: adapter.revoke(secrets))
        except AppError:
            notes.append("이전 로그인 값을 구글에서 취소하지 못했어요 — 구글 계정의 보안 설정에서 앱 접근을 확인할 수 있어요")
    cn.attach_refresh_token(ctx, entry, tokens.refresh, keystore=keystore)
    forget(entry.entry_id)
    _ACCESS[entry.entry_id] = tokens.access
    return LoginResult(slot, bool(previous), tuple(notes + meter.notes))


# ---- 연결 확인 ------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CheckResult:
    slot: str
    blog_id: str
    name: str                  # 태그를 지운 글자 — 사람이 보고 맞는 블로그인지 정한다
    url: str
    confirmed: bool            # 맞다고 확인해 항목에 '연결됨(시각)' 을 적었다

    def to_dict(self):
        return {"slot": self.slot, "blog_id": self.blog_id, "name": self.name, "url": self.url, "confirmed": self.confirmed}


def check(ctx, slot, *, confirmed=False, keystore=None, adapter=None):
    """블로그 번호로 이름·주소를 읽는다(A 요청). 응답의 번호가 같아야 하고, 사람이 맞는다고 `confirmed` 하면 항목에 '연결됨(시각)' 을 적는다. 읽기 실패는 항목에 '확인 필요' 로 적는다(인증 실패로 멈추지 않는다)."""
    capabilities.require_net("blogger_read", "Blogger 연결 확인")
    slot = slot_key(slot)
    keystore = ctx.get_keystore() if keystore is None else keystore
    entry = _require_entry(ctx, slot)
    secrets = _credentials(entry, keystore, need_refresh=True)
    blog_id = _blog_id(ctx, slot)
    adapter = external.blogger_adapter() if adapter is None else adapter
    meter = _Meter(ctx, entry)
    try:
        info = _api(ctx, entry, secrets, adapter, meter, "blogger_blog", lambda token: adapter.get_blog(token, blog_id))
    except AppError:
        _mark(ctx, entry, cn.CHECK_ERROR)
        raise
    if confirmed:
        cn.mark_check(ctx, entry.entry_id, cn.CHECK_OK)
    return CheckResult(slot, info.blog_id, info.name, info.url, bool(confirmed))


def _mark(ctx, entry, result):
    try:
        cn.mark_check(ctx, entry.entry_id, result)
    except AppError:
        return None                                                                # 표시를 못 남겨도 원래 오류가 우선이다(그 오류가 곧 사용자에게 알려진다)


# ---- 연결 해제 ------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DisconnectResult:
    slot: str
    was_logged_in: bool
    revoked: bool              # 구글에 취소를 요청해 성공했다(이미 무효여도 성공으로 본다)
    notes: tuple

    def to_dict(self):
        return {"slot": self.slot, "was_logged_in": self.was_logged_in, "revoked": self.revoked, "notes": list(self.notes)}


def disconnect(ctx, slot, *, confirmed, this_pc_only=False, understood=False, keystore=None, adapter=None):
    """연결 해제 — **구글에 취소를 먼저 요청**하고 성공해야 보관소의 갱신용 값 한 칸을 지운다(클라이언트 정보는 남는다 — 항목은 '로그인 필요'). 취소가 안 되면(오프라인·서버 오류) **아무것도 지우지 않고** 그 오류를 낸다.
    `this_pc_only` 는 '구글 쪽 취소는 구글 계정의 보안 설정에서 직접 하기로 하고 이 PC 의 값만 지움' — 되돌릴 수 없으니 `understood` 를 한 번 더 받아야 한다."""
    capabilities.require_net("blogger_oauth", "Blogger 연결 해제")
    require_confirmation(confirmed, "Blogger 연결 해제 — 다시 쓰려면 새로 로그인해야 해요(되돌릴 수 없어요)")
    slot = slot_key(slot)
    if this_pc_only:
        require_confirmation(understood, "구글 쪽 취소 없이 이 PC 의 값만 지우기 — 구글에는 로그인 값이 그대로 남아요(되돌릴 수 없어요)")
    keystore = ctx.get_keystore() if keystore is None else keystore
    entry = _require_entry(ctx, slot)
    secrets = _credentials(entry, keystore, need_refresh=False)
    if "refresh_token" not in secrets:
        forget(entry.entry_id)
        return DisconnectResult(slot, False, False, ("로그인돼 있지 않아서 지울 것이 없었어요",))
    revoked = False
    notes = []
    if not this_pc_only:
        adapter = external.blogger_adapter() if adapter is None else adapter
        meter = _Meter(ctx, entry)
        revoked = bool(meter.call("blogger_revoke", lambda: adapter.revoke(secrets)))
        notes += meter.notes
    else:
        notes.append("구글 쪽 취소는 하지 않았어요 — 구글 계정의 보안 설정에서 앱 접근을 직접 지워 주세요")
    cn.detach_refresh_token(ctx, entry, keystore=keystore)
    forget(entry.entry_id)
    return DisconnectResult(slot, True, revoked, tuple(notes))


# ---- 저널 -----------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class JournalRecord:
    project_id: str
    slot: str
    title_sha256: str
    content_sha256: str
    stage: str
    started_at: str

    def started(self):
        return datetime.strptime(self.started_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class BloggerJournal:
    """초안을 보내는 중인 글의 기록 — **보내기 전에** 쓴다. 제목·본문의 해시와 단계·시각뿐이다(본문·토큰·블로그 번호·제목 글자 없음). 깨졌으면 읽지 않고 SETTINGS_INVALID 로 멈춘다."""

    KEYS = {"schema", "project_id", "slot", "title_sha256", "content_sha256", "stage", "started_at"}

    def __init__(self, folder):
        self.folder = folder

    def _file(self, project_id, slot):
        if not isinstance(project_id, str) or _ID.fullmatch(project_id) is None or slot not in SLOT_NAME:
            raise AppError("CONTENT_INVALID", {"항목": "프로젝트 번호"})
        return self.folder / f"{project_id}-{slot}.json"

    def read(self, project_id, slot):
        target = self._file(project_id, slot)
        if not target.exists():
            return None

        def bad(why):
            return AppError("SETTINGS_INVALID", {"파일": target.name}, detail=why)

        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as error:
            raise bad(f"읽을 수 없다: {type(error).__name__}") from None
        if not isinstance(raw, dict) or set(raw) != self.KEYS or raw["schema"] != JOURNAL_SCHEMA or raw["project_id"] != project_id or raw["slot"] != slot:
            raise bad("칸이 올바르지 않다")
        if (not isinstance(raw["title_sha256"], str) or _HASH.fullmatch(raw["title_sha256"]) is None or not isinstance(raw["content_sha256"], str) or _HASH.fullmatch(raw["content_sha256"]) is None
                or raw["stage"] not in STAGES or not isinstance(raw["started_at"], str) or _STAMP.fullmatch(raw["started_at"]) is None):
            raise bad("값이 올바르지 않다")
        return JournalRecord(project_id, slot, raw["title_sha256"], raw["content_sha256"], raw["stage"], raw["started_at"])

    def write(self, record):
        if not isinstance(record, JournalRecord) or record.stage not in STAGES:
            raise AppError("CONTENT_INVALID", {"항목": "발행 기록"})
        write_json(self._file(record.project_id, record.slot), {"schema": JOURNAL_SCHEMA, "project_id": record.project_id, "slot": record.slot, "title_sha256": record.title_sha256,
                                                                  "content_sha256": record.content_sha256, "stage": record.stage, "started_at": record.started_at})

    def remove(self, project_id, slot):
        try:
            self._file(project_id, slot).unlink()
        except FileNotFoundError:
            return str()                                                           # 원래 없었다 — 지울 것도 알릴 것도 없다
        except OSError as error:
            return f"발행 기록 파일을 지우지 못했다({type(error).__name__})"
        return str()


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 보내기 전 검사 -------------------------------------------------------------------------------------------------------------------------
def html_problems(post, project, local_paths=()):
    """보낼 글(`BloggerPost`)의 검사 사유들 — 발행 전 검사를 **만든 HTML 에도** 다시 한다: 제목 모양·원고의 위험한 표기·이 PC 의 폴더 경로(제목·HTML·라벨 모두). 걸리면 보내지 않는다."""
    reasons = list(gate.title_problems(post.title)) + list(gate.raw_markdown_problems(project.source_content))
    text = "\n".join([post.title, post.html, *post.labels])
    if gate.local_path_problem(text, local_paths):
        reasons.append("[LOCAL_PATH] 글에 이 PC 의 폴더 경로가 들어 있다(Blogger 로 보내지 않는다)")
    return reasons


def check_post(post, project, local_paths=()):
    """키·토큰 모양(`SECRET_SHAPE_FOUND`)과 위 사유(`CHECK_FAILED`)를 보내기 **전에** 거절로 바꾼다 — 걸리면 아무것도 보내지 않는다."""
    refuse.refuse_secret_shapes({"제목": post.title, "본문": post.html, "라벨": ", ".join(post.labels)}, "Blogger 초안 저장")
    reasons = html_problems(post, project, local_paths)
    if reasons:
        codes = list(dict.fromkeys(reason.split("]", 1)[0].lstrip("[") for reason in reasons if reason.startswith("[")))
        raise AppError("CHECK_FAILED", {"걸린 항목 목록": ", ".join(codes) or "알 수 없음"}, detail="; ".join(reasons))


# ---- 초안 저장 -----------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SaveResult:
    project_id: str
    slot: str
    post_id: str
    url: str
    adopted: bool              # 방금 보낸 것이 아니라 Blogger 에 이미 있던 같은 제목의 초안을 이어받았다
    verified: bool             # Blogger 가 '초안' 이라고 확인해 줬다(상태를 알려 주지 않았으면 거짓 — 초안함에서 직접 확인)
    notes: tuple

    def to_dict(self):
        return {"project_id": self.project_id, "slot": self.slot, "post_id": self.post_id, "url": self.url, "adopted": self.adopted, "verified": self.verified, "notes": list(self.notes)}


def _slot_lock(ctx, project_id, slot):
    import contextlib

    @contextlib.contextmanager
    def held():
        lock = PublishLock(ctx.workspace.journal_dir / JOURNAL_FOLDER, f"{project_id}-{slot}", now=ctx.now)
        lock.acquire()
        try:
            yield lock
        finally:
            lock.release()
    return held()


def save_draft(ctx, project_text, slot, *, confirmed, hero=None, tags=(), keystore=None, adapter=None):
    """승인한 글 하나를 Blogger **초안으로만** 저장한다. 확인(`confirmed`)이 없으면 아무것도 하지 않는다. 같은 글·같은 슬롯의 두 번째 요청은 진행 중이면 거절한다(`PUBLISH_IN_PROGRESS`)."""
    capabilities.require_external_write("Blogger 초안 저장")
    capabilities.require_net("blogger_draft", "Blogger 초안 저장")
    slot = slot_key(slot)                                                          # 틀린 구분·없는 글 번호는 확인을 묻기 전에 알린다(읽기뿐 — 다른 명령도 번호를 먼저 풀어 '찾을 수 없습니다' 를 말한다)
    with ctx.store() as store:
        project_id = resolve_id(store, project_text)
    require_confirmation(confirmed, "Blogger 초안 저장 — 글 한 편이 Blogger 에 초안으로 올라가요(공개는 하지 않아요)")
    keystore = ctx.get_keystore() if keystore is None else keystore
    with _slot_lock(ctx, project_id, slot):
        return _save(ctx, project_id, slot, hero, tags, keystore, external.blogger_adapter() if adapter is None else adapter)


def _save(ctx, project_id, slot, hero, tags, keystore, adapter):
    with ctx.store() as store:
        project = store.load(project_id)
    variant = project.variant(slot)
    if variant.status != st.APPROVED:
        raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.DRAFT_SAVED})
    if not variant.rendered or variant.rendered_revision != project.revision:
        raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.DRAFT_SAVED}, detail="렌더링이 현재 원고의 판과 다르다")
    entry = _require_entry(ctx, slot)
    secrets = _credentials(entry, keystore, need_refresh=True)
    blog_id = _blog_id(ctx, slot)
    post = render.render_blogger_post(project, SLOT_LANG[slot], hero=hero, tags=tags)
    check_post(post, project, ctx.local_paths())
    notes = list(post.notes)
    meter = _Meter(ctx, entry)
    journal = BloggerJournal(ctx.workspace.journal_dir / JOURNAL_FOLDER)
    previous = journal.read(project_id, slot)
    if previous is not None:                                                       # 앱이 꺼졌거나 확인 중 실패했다 — 새로 보내기 전에 같은 제목의 초안부터 찾는다
        found = _same_title(ctx, entry, secrets, adapter, meter, blog_id, post.title, previous)
        if len(found) == 1:
            return _finish(ctx, journal, project_id, slot, project.revision, found[0].post_id, str(), adopted=True, verified=True, notes=notes + ["이전에 보내다 멈춘 글이 Blogger 에 이미 초안으로 있어서 그것을 이어받았어요"] + meter.notes)
        if len(found) > 1:
            raise AppError("BLOGGER_DRAFT_UNKNOWN")
        notes.append("이전에 보내다 멈춘 글이 Blogger 의 초안 목록에 없어서 새로 보냈어요")
    started = ctx.stamp()
    record = JournalRecord(project_id, slot, _sha(post.title), _sha(post.html), STAGE_SENDING, started)
    journal.write(record)                                                          # 저널을 못 쓰면 보내지 않는다(FILE_WRITE_FAILED)
    try:
        inserted = _api(ctx, entry, secrets, adapter, meter, "blogger_insert", lambda token: adapter.insert_draft(token, blog_id, post))
    except NetError as error:
        if error.outcome_unknown:
            return _after_unknown(ctx, journal, record, entry, secrets, adapter, meter, blog_id, post, project, slot, notes)
        journal.remove(project_id, slot)
        raise
    except AppError as error:
        journal.remove(project_id, slot)
        if error.code == "BLOGGER_NOT_DRAFT":
            _fail(ctx, project_id, slot, error.code)
        raise
    verified = inserted.status == api.DRAFT
    try:
        seen = _api(ctx, entry, secrets, adapter, meter, "blogger_check", lambda token: adapter.get_post(token, blog_id, inserted.post_id))
    except AppError as error:
        if error.code == "BLOGGER_NOT_DRAFT":
            journal.remove(project_id, slot)
            _fail(ctx, project_id, slot, error.code)
            raise
        if not verified:                                                           # 저장 답에도 상태가 없고 확인도 못 했다 — 초안인지 모른다: 저널을 남기고 사람이 확인한다
            journal.write(JournalRecord(project_id, slot, record.title_sha256, record.content_sha256, STAGE_UNKNOWN, started))
            raise AppError("BLOGGER_DRAFT_UNKNOWN") from None
        notes.append("초안인지 다시 확인하는 요청이 끝나지 못했어요 — 저장 답에는 초안으로 적혀 있었어요")
    else:
        verified = verified or seen.status == api.DRAFT
        if not verified:
            notes.append("Blogger 가 초안인지 알려 주지 않았어요 — Blogger 의 초안 목록에서 확인해 주세요")
    return _finish(ctx, journal, project_id, slot, project.revision, inserted.post_id, inserted.url, adopted=False, verified=verified, notes=notes + meter.notes)


def _same_title(ctx, entry, secrets, adapter, meter, blog_id, title, record):
    """C 요청 — 최근 초안 가운데 **제목이 같고** 저널을 쓴 때 앞뒤 시간 창 안에 고쳐진 것."""
    items = _api(ctx, entry, secrets, adapter, meter, "blogger_find", lambda token: adapter.find_drafts(token, blog_id))
    started = record.started()
    low, high = started - WINDOW_BEFORE, started + WINDOW_AFTER
    return [item for item in items if item.status in (api.DRAFT, str()) and item.title == title and low <= item.updated <= high]


def _after_unknown(ctx, journal, record, entry, secrets, adapter, meter, blog_id, post, project, slot, notes):
    """보낸 뒤 결과를 모른다 — 저널을 `unknown` 으로 바꾸고 같은 제목의 초안을 먼저 찾는다. **정확히 하나**면 이어받고, 없거나 둘 이상이면 사람이 확인하게 멈춘다(자동으로 다시 보내지 않는다)."""
    journal.write(JournalRecord(record.project_id, slot, record.title_sha256, record.content_sha256, STAGE_UNKNOWN, record.started_at))
    try:
        found = _same_title(ctx, entry, secrets, adapter, meter, blog_id, post.title, record)
    except AppError:
        raise AppError("BLOGGER_DRAFT_UNKNOWN") from None
    if len(found) == 1:
        return _finish(ctx, journal, record.project_id, slot, project.revision, found[0].post_id, str(), adopted=True, verified=True, notes=notes + ["응답은 못 받았지만 Blogger 에 같은 제목의 초안이 하나 있어서 그것을 이어받았어요"] + meter.notes)
    raise AppError("BLOGGER_DRAFT_UNKNOWN")


def _fail(ctx, project_id, slot, code):
    """공개 같은 '초안이 아닌 답' 이 왔다 — 글 상태를 실패로 바꿔 다시 검토·승인해야 하게 한다(앱은 Blogger 의 글을 고치거나 지우지 않는다)."""
    try:
        with ctx.store() as store:
            project = store.load(project_id)
            project.transition(slot, st.PUBLISH_FAILED, error_code=code)
            store.save(project)
    except AppError:
        return None                                                                # 상태를 못 바꿔도 원래 오류(`BLOGGER_NOT_DRAFT`)가 곧 사용자에게 알려진다


def _finish(ctx, journal, project_id, slot, revision, post_id, url, *, adopted, verified, notes):
    """상태를 `DRAFT_SAVED`(글번호를 `remote_id` 에)로 바꾸고 저널을 지운다. 상태를 못 저장하면 저널을 `unknown` 으로 남겨 다음 실행이 먼저 확인하게 한다."""
    try:
        with ctx.store() as store:
            project = store.load(project_id)
            project.transition(slot, st.DRAFT_SAVED, remote_id=post_id)
            store.save(project)
    except AppError:
        record = journal.read(project_id, slot)
        if record is not None and record.stage != STAGE_UNKNOWN:
            journal.write(JournalRecord(project_id, slot, record.title_sha256, record.content_sha256, STAGE_UNKNOWN, record.started_at))
        raise
    leftover = journal.remove(project_id, slot)
    return SaveResult(project_id, slot, post_id, url, adopted, verified, tuple(notes + ([leftover] if leftover else [])))


save_blogger_draft = save_draft            # 같은 함수 — 명령줄은 이 이름으로 부른다. 저장한 초안(`draft_store.save_draft`)과 이름이 같으면 '초안을 보관함에 쓰는 함수' 를 찾는 안전 시험(`test_service_safety`)이 원격 Blogger 저장을 보관함 쓰기로 오해한다


__all__ = ["BloggerJournal", "CheckResult", "DisconnectResult", "JournalRecord", "LoginResult", "SLOTS", "SaveResult", "SlotStatus", "check", "check_post", "disconnect", "find_entry",
           "forget", "html_problems", "login", "make_blogger_adapter", "save_blogger_draft", "save_draft", "slot_key", "status"]
