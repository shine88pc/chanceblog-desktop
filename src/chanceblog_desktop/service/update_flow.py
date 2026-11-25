"""업데이트 서비스(UPDATE 설계서 3-1·3-5·3-6·3-9) — 화면·명령줄이 부르는 단계: **확인 → 내려받기 → 적용 → (복구)**. 모든 실패를 `UPDATE_*` 오류 코드로 바꾼다.

규칙(안전 순서):
  · 확인·내려받기의 진입점은 첫 문장이 `capabilities.require_net("update_check", …)`, 적용·복구의 진입점은 첫 문장이 `capabilities.require_update_apply(…)` 다 — 스위치가 꺼져 있으면 접속·하위 프로세스·파일 쓰기 전에 끝난다.
    접속 클라이언트는 `external` 등록부에 꽂힌 공장(`update` 종류 — 스위치 `NET_UPDATE_CHECK` 가 켜져야 꽂힌다)에서만 얻는다.
  · 확인은 `update-manifest.json` 과 `.sig` 를 받아 **서명을 확인한 뒤에** 값을 믿는다(`update/manifest.py`). 확인만으로는 `last_seq`(적용한 가장 높은 시퀀스)를 올리지 않는다 — 실패한 확인이 시퀀스를 태우지 않게.
  · 적용은 ① 확인 표시가 있어야 하고 ② 받은 파일을 다시 해시해 서명된 값과 같을 때만 ③ **백업이 완료(`complete`)일 때만**(부분·막힘·실패면 시작하지 않는다 — `UPDATE_BACKUP_FAILED`) ④ `pending` 을 기록한 **뒤에** 설치 도구에 넘기고 ⑤ 넘김이 성공한 순간에만 `last_seq` 를 올린다.
    넘기기가 실패하면 `pending` 을 지우고(지금 판 그대로) `UPDATE_APPLY_FAILED`. 어느 단계에서 프로세스가 죽어도 다음 시작(`update/state.note_boot`)이 `pending` 을 보고 이어간다.
  · 복구는 사용자가 '복구' 를 눌렀을 때만(`confirmed`), 순서와 실패 처리는 `update/recovery.py` 가 정한다 — 낮은 판은 `pending.from` 하나만.
  · 요청은 고정 주소 읽기뿐이고 사진·글·경로·사용자 이름·키는 어디에도 실리지 않는다(접속 틀이 표의 머리글만 보낸다 — 시험 `test_update_privacy` 가 가로채 확인한다).
폴더에서 업데이트(설계서 3-11, 질문 Q4 추천 '포함' — `check_from_folder`·`stage_update_from_folder`): 사용자가 고른 폴더(예: 공개 전 후보의 자산을 받아 둔 곳·인터넷이 막힌 PC)의 매니페스트·서명·파일을 **온라인과 똑같은 규칙**으로 확인하고
(서명·칸 규칙·만료·시계·버전·`seq`·설치 종류·크기·SHA-256 — 후보 채널 `rc` 도 읽는다) 같은 적용 흐름(`apply_update`)으로 넘긴다. **접속이 없어** 접속 스위치와 무관하고 진입점의 첫 문장은 `capabilities.require_update_apply` 다. 고른 폴더는 읽기만 한다.
`UpdateSession` 은 상태 기계(`update/machine.py`)를 쥐고 위 단계를 순서대로만 부르게 한다(순서가 틀린 호출은 아무것도 하지 않고 `IllegalTransition`). 이 파일은 `http`·`ssl`·소켓·하위 프로세스를 가져오지 않는다.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .. import capabilities
from ..errors import AppError
from ..update import apply as apply_module
from ..update import health, keys, machine, recovery, source
from ..update import manifest as manifest_module
from ..update import state as state_module
from ..update import versions
from . import backup_flow, external
from .lock import PublishLock
from .projects import require_confirmation

LOCK_NAME = "update"                                   # locks/update.lock
AUTO_CHECK = False                                     # 자동 확인(창이 뜬 뒤 하루 한 번 이하·작업 스레드·조용히·자동으로 내려받거나 적용하지 않음)의 **설계 자리**일 뿐 아무도 읽지 않는다 — 켜는 변경은 별도 번호 승인(설계서 3-7)
PASS_THROUGH = frozenset({"NET_COOLDOWN", "NET_TLS_FAILED", "DISK_FULL", "NETWORK_DISABLED", "EXTERNAL_WRITE_DISABLED"})   # 그대로 알리는 오류(시계·쉬는 중·디스크·꺼짐)
STALE_STAGING_SECONDS = 24 * 3600                      # 이보다 오래된 임시 내려받기 폴더는 죽은 것으로 보고 치운다(정상이 되기를 기다리는 폴더는 아직 낡지 않았다)
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


class _UpdateLock(PublishLock):
    """업데이트·복구가 함께 쓰는 잠금(`locks/update.lock`) — 한 번에 하나만(두 번째는 아무것도 바꾸지 않고 `UPDATE_IN_PROGRESS`). 방식·낡은 잠금 넘겨받기는 `PublishLock` 과 같다."""
    busy_code = "UPDATE_IN_PROGRESS"
    what = "업데이트나 복구를 하다"


@contextmanager
def _update_lock(ctx):
    lock = _UpdateLock(ctx.workspace.locks_dir, LOCK_NAME, now=ctx.now, host="")      # PC 이름을 읽지 않는다(백업·복원의 잠금과 같은 이유 — 하위 프로세스 0)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


@dataclass(frozen=True)
class CheckResult:
    status: str                                        # UP_TO_DATE · AVAILABLE
    manifest: object                                   # 서명을 확인한 `Manifest`
    apply_possible: bool
    current_version: str
    manifest_bytes: bytes = b""
    signature_bytes: bytes = b""
    source: str = "online"                            # online · folder(폴더에서 업데이트)
    folder: str = ""                                  # source 가 folder 일 때 고른 폴더(메모리에만 — 기록·오류에는 싣지 않는다)


@dataclass(frozen=True)
class ApplyResult:
    handed_off: bool
    backup_name: str
    to_version: str


def update_folder(ctx):
    return ctx.workspace.root / state_module.DIR_NAME


def _stamp(moment):
    return moment.astimezone(timezone.utc).strftime(_STAMP)


def _parse_stamp(text):
    return manifest_module.parse_time(text) if text else None


def _client(version):
    """접속 클라이언트 — 꽂힌 `update` 공장에서만 얻는다(꽂히지 않았으면 스위치가 꺼진 것이다)."""
    factory = external.adapter_factory(external.KIND_UPDATE)
    if factory is None:
        raise AppError("NETWORK_DISABLED", {"작업": "업데이트 확인"}, detail="update:not_registered")
    return factory(version=version)


def _as_update_error(error, code):
    """어떤 실패든 오류 코드 하나로 — `PASS_THROUGH` 와 이미 `UPDATE_*` 인 것은 그대로, 나머지는 `code` 로 바꾸고 세부에는 원래 코드(또는 예외 이름)만 남긴다(서버·파일의 글은 담지 않는다)."""
    if isinstance(error, AppError):
        if error.code in PASS_THROUGH or error.code.startswith("UPDATE_"):
            return error
        return AppError(code, detail=f"cause:{error.code}:{str(error.detail)[:80]}")
    return AppError(code, detail=f"cause:{type(error).__name__}")


def _load_state(folder, code):
    try:
        return state_module.load_state(folder)
    except state_module.StateError as error:
        raise AppError(code, detail=f"state:{error.reason}") from None


def _save_state(folder, new_state, code):
    try:
        state_module.write_state(folder, new_state)
    except state_module.StateError as error:
        raise AppError(code, detail=f"state:{error.reason}") from None


def _current_version(current_version):
    version = current_version if current_version is not None else state_module.read_current_version()
    if versions.parse_version(version) is None:
        raise AppError("UPDATE_CHECK_FAILED", detail="current_version")
    return version


def estimate_backup_bytes(ctx):
    """업데이트 전 백업이 차지할 크기의 어림(담는 파일 여섯의 크기 합) — 읽지 못하는 것은 0 으로 센다."""
    total = 0
    for component in backup_flow.COMPONENTS:
        try:
            total += Path(backup_flow._component_path(ctx, component)).stat().st_size
        except (OSError, KeyError, ValueError):
            continue
    return total


def _record_check(folder, state, now, result, version, code):
    seen = _parse_stamp(state.last_seen_utc)
    newest = now if seen is None or now > seen else seen
    _save_state(folder, replace(state, last_seen_utc=_stamp(newest), last_check=state_module.LastCheck(_stamp(now), result, version, code)), "UPDATE_CHECK_FAILED")


def _fetch_and_verify(client, ring, now, version, state, kind, channels):
    """서명 불일치가 나오면 한 번만 처음부터 다시 받는다 — 릴리스가 공개되는 순간에는 두 파일이 서로 다른 릴리스의 것일 수 있다(그 밖의 거절은 다시 받지 않는다)."""
    last_error = None
    for _attempt in range(2):
        data, signature = source.fetch_manifest(client)
        try:
            verdict = manifest_module.verify_manifest(data, signature, keyring=ring, now=now, current_version=version, last_seq=state.last_seq, last_seen=_parse_stamp(state.last_seen_utc),
                                                      install_kind=kind, channels=channels)
        except manifest_module.ManifestError as error:
            last_error = error
            if error.code == manifest_module.CODE_SIGNATURE and error.reason == "bad_signature":
                continue
            raise
        return verdict, data, signature
    raise last_error


def check_for_update(ctx, *, current_version=None, install_kind=None, keyring=None, channels=manifest_module.CHANNELS_ONLINE):
    """'지금 확인'(사용자가 단추를 누를 때만) → `CheckResult`. 읽기뿐이다 — 아무것도 내려받아 두지 않고 `last_seq` 도 올리지 않는다. 마지막 확인 결과와 본 가장 늦은 시각만 상태 파일에 적는다."""
    capabilities.require_net("update_check", "업데이트 확인")
    folder = update_folder(ctx)
    now = ctx.now()
    state = _load_state(folder, "UPDATE_CHECK_FAILED")
    version = _current_version(current_version)
    ring = keyring if keyring is not None else keys.shipped_keyring()
    kind = install_kind if install_kind is not None else ""
    try:
        health.sweep_stale_staging(folder, max_age_seconds=STALE_STAGING_SECONDS, now=now)         # 죽은 내려받기의 임시 폴더 정리 — 정리가 안 돼도 확인은 계속한다(정리 함수가 파일 오류를 삼킨다)
        client = _client(version)
        verdict, data, signature = _fetch_and_verify(client, ring, now, version, state, kind, channels)
    except Exception as error:       # noqa: BLE001 - 어떤 실패든 오류 코드 하나로(기록은 쓰되 원래 오류를 숨기지 않는다)
        failure = _as_update_error(error, "UPDATE_CHECK_FAILED")
        if failure.code != "NETWORK_DISABLED":
            try:
                _record_check(folder, state, now, "CHECK_FAILED", "", failure.code)
            except AppError:
                pass
        raise failure from None
    _record_check(folder, state, now, verdict.status, verdict.manifest.version, "")
    return CheckResult(verdict.status, verdict.manifest, verdict.apply_possible, version, data, signature)


def check_from_folder(ctx, chosen_folder, *, current_version=None, install_kind=None, keyring=None):
    """'파일에서 업데이트…'(설계 3-11)의 앞 절반 — 고른 폴더의 매니페스트·서명을 온라인과 같은 규칙으로 확인한다(후보 채널 `rc` 도 읽는다) → `CheckResult`(`source="folder"`). 접속이 없다 — 첫 문장은 적용 스위치 관문이다.
    본 가장 늦은 시각만 기록하고(`last_check` 는 온라인 확인의 기록이라 건드리지 않는다) `last_seq` 는 올리지 않는다. 어떤 실패든 `UPDATE_*` 코드 하나(이유 이름표에 폴더 경로·파일 이름 없음)."""
    capabilities.require_update_apply("폴더에서 업데이트")
    folder = update_folder(ctx)
    now = ctx.now()
    state = _load_state(folder, "UPDATE_CHECK_FAILED")
    version = _current_version(current_version)
    ring = keyring if keyring is not None else keys.shipped_keyring()
    kind = install_kind if install_kind is not None else ""
    try:
        data, signature = source.read_folder_manifest(chosen_folder)
        verdict = manifest_module.verify_manifest(data, signature, keyring=ring, now=now, current_version=version, last_seq=state.last_seq, last_seen=_parse_stamp(state.last_seen_utc),
                                                  install_kind=kind, channels=manifest_module.CHANNELS_OFFLINE)
    except Exception as error:       # noqa: BLE001 - 어떤 실패든 오류 코드 하나로
        raise _as_update_error(error, "UPDATE_MANIFEST_INVALID") from None
    seen = _parse_stamp(state.last_seen_utc)
    _save_state(folder, replace(state, last_seen_utc=_stamp(now if seen is None or now > seen else seen)), "UPDATE_CHECK_FAILED")
    return CheckResult(verdict.status, verdict.manifest, verdict.apply_possible, version, data, signature, "folder", str(chosen_folder))


def stage_update_from_folder(ctx, check, *, progress=None, free_bytes=None):
    """'파일에서 업데이트…' 의 가운데 — 고른 폴더의 필요한 파일을 임시 폴더에 복사하며 크기·SHA-256 을 서명된 값과 맞춘다 → `source.StagedUpdate`. 접속이 없다 — 첫 문장은 적용 스위치 관문이다."""
    capabilities.require_update_apply("업데이트 준비")
    if getattr(check, "source", "") != "folder":
        raise AppError("UPDATE_CHECK_FAILED", detail="stage:not_folder")
    if check.status != manifest_module.STATUS_AVAILABLE:
        raise AppError("UPDATE_CHECK_FAILED", detail="stage:not_available")
    if not check.apply_possible:
        raise AppError("UPDATE_NOT_INSTALLED_KIND", detail="stage")
    kind = check.manifest.installer_kind
    roles = apply_module.REQUIRED_ROLES.get(kind, ())
    if not roles or any(check.manifest.file(role) is None for role in roles):
        raise AppError("UPDATE_MANIFEST_INVALID", detail="manifest:missing_role")
    folder = update_folder(ctx)
    try:
        return source.stage_from_folder(check.folder, check.manifest, check.manifest_bytes, check.signature_bytes, folder, backup_estimate=estimate_backup_bytes(ctx),
                                        free_bytes=free_bytes or source.default_free_bytes, progress=progress, roles=roles)
    except Exception as error:       # noqa: BLE001 - 어떤 실패든 오류 코드 하나로
        raise _as_update_error(error, "UPDATE_MANIFEST_INVALID") from None


def download_update(ctx, check, *, progress=None, free_bytes=None):
    """'내려받고 설치' 의 앞 절반 — 서명된 매니페스트가 말한 필요한 파일만 받아 크기·해시를 확인한다 → `source.StagedUpdate`. 휴대용·소스 실행은 받지 않는다(`UPDATE_NOT_INSTALLED_KIND`).
    실패하면 받은 폴더를 지운다. 끊김·시간·크기 초과는 `UPDATE_DOWNLOAD_FAILED`, 크기·해시 불일치는 `UPDATE_SIGNATURE_INVALID`, 디스크 모자람은 `DISK_FULL`."""
    capabilities.require_net("update_check", "업데이트 내려받기")
    if check.status != manifest_module.STATUS_AVAILABLE:
        raise AppError("UPDATE_CHECK_FAILED", detail="download:not_available")
    if not check.apply_possible:
        raise AppError("UPDATE_NOT_INSTALLED_KIND", detail="download")
    kind = check.manifest.installer_kind
    roles = apply_module.REQUIRED_ROLES.get(kind, ())
    if not roles or any(check.manifest.file(role) is None for role in roles):
        raise AppError("UPDATE_MANIFEST_INVALID", detail="manifest:missing_role")
    folder = update_folder(ctx)
    try:
        client = _client(check.current_version)
        return source.download_files(client, check.manifest, check.manifest_bytes, check.signature_bytes, folder, backup_estimate=estimate_backup_bytes(ctx),
                                     free_bytes=free_bytes or source.default_free_bytes, progress=progress, roles=roles)
    except Exception as error:       # noqa: BLE001 - 어떤 실패든 오류 코드 하나로
        raise _as_update_error(error, "UPDATE_DOWNLOAD_FAILED") from None


def apply_update(ctx, check, staged, *, adapter=None, confirmed=False, step=None, hooks=None):
    """'내려받고 설치' 의 뒤 절반 — 위 머리글의 순서대로: 확인 표시 → 잠금 → 다시 해시 → 백업(완료만) → `pending` 기록 → 설치 도구에 넘기기 → `last_seq` 올리기. `hooks` 는 상태 기계가 단계 경계를 알아채는 자리다."""
    capabilities.require_update_apply("업데이트 설치")
    require_confirmation(confirmed, "업데이트 설치")
    hooks = hooks or {}
    manifest = staged.manifest
    version = check.current_version
    adapter = adapter if adapter is not None else apply_module.adapter_for(manifest.installer_kind if check.apply_possible else "")
    folder = update_folder(ctx)
    with _update_lock(ctx):
        source.verify_staged(staged)
        try:
            outcome = backup_flow.create_full_backup(ctx, step=step)
        except AppError as error:
            raise _as_update_error(error, "UPDATE_BACKUP_FAILED") from None
        if outcome.row.status != backup_flow.STATUS_COMPLETE:
            raise AppError("UPDATE_BACKUP_FAILED", detail=f"backup:{outcome.row.status}")       # 부분·깨짐은 통과가 아니다(설계 Q8) — 아무것도 바꾸지 않았다
        if hooks.get("backup_done"):
            hooks["backup_done"]()
        state = _load_state(folder, "UPDATE_APPLY_FAILED")
        pending = state_module.Pending(version, manifest.version, manifest.seq, outcome.row.name, _stamp(ctx.now()), 0, manifest.installer_kind)
        _save_state(folder, replace(state, pending=pending, notice=""), "UPDATE_APPLY_FAILED")        # 넘기기 **전에** 기록한다
        try:
            adapter.apply(staged, from_version=version, to_version=manifest.version, recovery=False)
        except Exception as error:   # noqa: BLE001 - 넘기기가 실패하면 표식을 지우고(지금 판 그대로) 오류 코드로 알린다
            try:
                _save_state(folder, state, "UPDATE_APPLY_FAILED")
            except AppError:
                pass
            raise _as_update_error(error, "UPDATE_APPLY_FAILED") from None
        done = replace(state, pending=pending, last_seq=max(state.last_seq, manifest.seq), notice="")
        try:
            state_module.write_state(folder, done)                                                         # 넘김이 성공한 순간에만 올린다(쓰기가 실패해도 이미 넘겼으니 알리지 않는다 — 정상 표식이 같은 값을 다시 올린다)
        except state_module.StateError:
            pass
    return ApplyResult(True, outcome.row.name, manifest.version)


def _previous_installer(ctx, folder, pending, state, ring, kind, adapter_roles):
    """복구용 이전 판의 검증된 설치 파일 — ① 보관해 둔 것(`keep/<버전>/`)이 있으면 그것(오프라인, 서명·해시를 똑같이 다시 확인) ② 없으면 이전 릴리스의 서명된 매니페스트와 파일을 다시 받는다(복구에서만)."""
    now = ctx.now()
    keep = health.keep_dir(folder, pending.from_version)
    data_path, sig_path = keep / source.MANIFEST_COPY, keep / source.SIGNATURE_COPY
    if data_path.is_file() and sig_path.is_file():
        try:                                                    # 보관한 것이 틀렸거나 모자라면 없는 것으로 보고 다시 받아 본다(서명·해시 검사는 어느 쪽이든 같다)
            data, signature = data_path.read_bytes(), sig_path.read_bytes()
            verdict = manifest_module.verify_manifest(data, signature, keyring=ring, now=now, current_version=pending.to_version, last_seq=state.last_seq, install_kind=kind,
                                                      channels=manifest_module.CHANNELS_OFFLINE, recovery_target=pending.from_version)
            files = {entry.role: keep / entry.name for entry in verdict.manifest.files if (keep / entry.name).is_file()}
            staged = source.StagedUpdate(keep, files, verdict.manifest)
            if all(role in files for role in adapter_roles):
                source.verify_staged(staged)
                return staged
        except (AppError, OSError, ValueError):
            pass
    capabilities.require_net("update_check", "이전 버전 받기")
    client = _client(pending.to_version)
    data, signature = source.fetch_manifest(client, tag="v" + pending.from_version)
    verdict = manifest_module.verify_manifest(data, signature, keyring=ring, now=now, current_version=pending.to_version, last_seq=state.last_seq, install_kind=kind,
                                              channels=manifest_module.CHANNELS_OFFLINE, recovery_target=pending.from_version)
    return source.download_files(client, verdict.manifest, data, signature, folder, backup_estimate=estimate_backup_bytes(ctx), roles=adapter_roles)


def recover_update(ctx, *, adapter=None, confirmed=False, keyring=None):
    """'복구'(사용자가 눌렀을 때만) — `update/recovery.run_recovery` 의 순서: 잠금 → 데이터(이관됐거나 모를 때 업데이트 직전 백업 복원) → 이전 판 구하기 → 적용 → 기록. 실패하면 `UPDATE_ROLLBACK_FAILED`(단계 이름·원인 코드)."""
    capabilities.require_update_apply("업데이트 복구")
    require_confirmation(confirmed, "이전 버전으로 되돌리기")
    folder = update_folder(ctx)
    state = _load_state(folder, "UPDATE_ROLLBACK_FAILED")
    pending = state.pending
    if pending is None:
        raise recovery.RollbackFailure(recovery.STEP_LOCK, "no_pending")
    ring = keyring if keyring is not None else keys.shipped_keyring()
    chosen = adapter if adapter is not None else apply_module.adapter_for(pending.kind)
    roles = apply_module.REQUIRED_ROLES.get(pending.kind, ())

    def acquire():
        lock = _UpdateLock(ctx.workspace.locks_dir, LOCK_NAME, now=ctx.now, host="")
        lock.acquire()
        return lock

    def restore(name):
        backup_flow.restore_full_backup(ctx, name, confirmed=True)

    def obtain(version):
        return _previous_installer(ctx, folder, pending, state, ring, pending.kind, roles)

    def apply_previous(package, version):
        chosen.apply(package, from_version=pending.to_version, to_version=version, recovery=True)

    def record(result, restored):
        current = state_module.load_state(folder)
        if result == recovery.RESULT_ROLLED_BACK:
            state_module.write_state(folder, replace(current, pending=None, notice="rolled_back", last_good=pending.from_version))
        else:
            state_module.write_state(folder, replace(current, notice="rollback_failed"))

    return recovery.run_recovery(pending, acquire_lock=acquire, data_migrated=lambda: None, restore_backup=restore, obtain_previous=obtain, apply_previous=apply_previous, record=record)


class UpdateSession:
    """상태 기계를 쥐고 위 단계를 순서대로만 부른다 — 순서가 틀린 호출은 아무것도 하지 않고 `IllegalTransition`. 화면이 한 번의 업데이트 흐름 동안 하나를 들고 있는다.
    `machine.state` 가 카드의 상태다. 오류는 `error`(마지막 `AppError`)에 남는다."""

    def __init__(self, ctx, *, install_kind="", current_version=None, keyring=None, adapter=None, free_bytes=None):
        self.ctx = ctx
        self.machine = machine.Machine()
        self.install_kind = install_kind
        self.current_version = current_version
        self.keyring = keyring
        self.adapter = adapter
        self.free_bytes = free_bytes
        self.check_result = None
        self.staged = None
        self.error = None

    @property
    def state(self):
        return self.machine.state

    def on_boot(self, note):
        """시작 후크의 결과(`state.BootNote`)를 상태 기계에 알린다 — 첫 시작·복구 안내·적용 안 됨."""
        event = {state_module.BOOT_FIRST: machine.BOOT_PENDING_MATCHES, state_module.BOOT_RECOVERY: machine.BOOT_RECOVERY_NEEDED, state_module.BOOT_NOT_APPLIED: machine.BOOT_NOT_APPLIED}.get(getattr(note, "action", ""))
        if event is not None:
            self.machine.send(event)
        return self.state

    def report_health(self, healthy, *, probes_ok=True):
        """새 판의 점검·감시 결과를 알린다 — 정상이면 `pending` 을 지우고 받아 둔 검증된 설치 파일을 복구용 보관으로 옮기고 임시를 정리하며, 아니면 비정상 → 복구 안내 상태로."""
        capabilities.require_update_apply("업데이트 점검")
        self.machine.send(machine.START_HEALTH_CHECK)
        if healthy and probes_ok:
            folder = update_folder(self.ctx)
            self.machine.send(machine.HEALTH_OK)
            try:
                before = state_module.load_state(folder)
                health.mark_healthy(folder, before)
            except (state_module.StateError, AppError):
                return self.state                               # 표식을 못 지웠다 — 다음 시작이 같은 일을 다시 한다
            if before.pending is not None:
                run = source.find_staged_run(folder, before.pending.to_version)
                if run is not None:
                    health.promote_to_keep(run, folder, before.pending.to_version)
                health.clear_staging(folder)
                health.prune_keep(folder, keep_versions=(before.pending.to_version, before.pending.from_version))
            return self.state
        self.machine.send(machine.HEALTH_FAILED)
        self.machine.send(machine.OFFER_RECOVERY)
        return self.state

    def check(self):
        capabilities.require_net("update_check", "업데이트 확인")
        self.error = None
        self.machine.send(machine.CLICK_CHECK)
        try:
            result = check_for_update(self.ctx, current_version=self.current_version, install_kind=self.install_kind, keyring=self.keyring)
        except AppError as error:
            self.error = error
            self.machine.send(machine.CHECK_ERROR)
            raise
        self.check_result = result
        self.machine.send(machine.CHECK_AVAILABLE if result.status == manifest_module.STATUS_AVAILABLE else machine.CHECK_UP_TO_DATE)
        return result

    def check_folder(self, chosen_folder):
        """폴더에서 업데이트의 확인 — 접속이 없고 적용 스위치만 필요하다(`check` 와 같은 상태 흐름)."""
        capabilities.require_update_apply("폴더에서 업데이트")
        self.error = None
        self.machine.send(machine.CLICK_CHECK)
        try:
            result = check_from_folder(self.ctx, chosen_folder, current_version=self.current_version, install_kind=self.install_kind, keyring=self.keyring)
        except AppError as error:
            self.error = error
            self.machine.send(machine.CHECK_ERROR)
            raise
        self.check_result = result
        self.machine.send(machine.CHECK_AVAILABLE if result.status == manifest_module.STATUS_AVAILABLE else machine.CHECK_UP_TO_DATE)
        return result

    def prepare_from_folder(self, progress=None):
        """폴더에서 업데이트의 '내려받기' 자리 — 고른 폴더에서 복사하며 확인한다(`download` 와 같은 상태 흐름, 접속 없음)."""
        capabilities.require_update_apply("업데이트 준비")
        self.error = None
        self.machine.send(machine.CLICK_INSTALL)
        try:
            staged = stage_update_from_folder(self.ctx, self.check_result, progress=progress, free_bytes=self.free_bytes)
        except AppError as error:
            self.error = error
            self.machine.send(machine.STEP_FAILED)
            raise
        self.machine.send(machine.DOWNLOAD_DONE)
        self.machine.send(machine.VERIFY_OK)
        self.staged = staged
        return staged

    def download(self, progress=None):
        capabilities.require_net("update_check", "업데이트 내려받기")
        if self.check_result is not None and getattr(self.check_result, "source", "online") != "online":
            raise AppError("UPDATE_CHECK_FAILED", detail="download:folder_source")        # 폴더에서 확인한 결과는 인터넷으로 받지 않는다 — `prepare_from_folder` 로 간다
        self.error = None
        self.machine.send(machine.CLICK_INSTALL)
        try:
            staged = download_update(self.ctx, self.check_result, progress=progress, free_bytes=self.free_bytes)
        except AppError as error:
            self.error = error
            self.machine.send(machine.STEP_FAILED)
            raise
        self.machine.send(machine.DOWNLOAD_DONE)
        self.machine.send(machine.VERIFY_OK)
        self.staged = staged
        return staged

    def apply(self, *, confirmed=False, step=None):
        capabilities.require_update_apply("업데이트 설치")
        self.error = None
        self.machine.send(machine.PROCEED)
        hooks = {"backup_done": lambda: self.machine.send(machine.BACKUP_COMPLETE)}
        try:
            result = apply_update(self.ctx, self.check_result, self.staged, adapter=self.adapter, confirmed=confirmed, step=step, hooks=hooks)
        except Exception as error:     # noqa: BLE001 - 어느 단계의 실패든 상태 기계를 맞는 곳(IDLE)으로 돌린다
            self.error = error if isinstance(error, AppError) else AppError("UPDATE_APPLY_FAILED", detail=f"cause:{type(error).__name__}")
            self.machine.send(machine.HANDOFF_FAILED if self.state == machine.APPLYING else machine.STEP_FAILED)
            raise
        self.machine.send(machine.HANDED_OFF_OK)
        return result

    def recover(self, *, confirmed=False):
        capabilities.require_update_apply("업데이트 복구")
        self.error = None
        self.machine.send(machine.CLICK_RECOVER)
        try:
            outcome = recover_update(self.ctx, adapter=self.adapter, confirmed=confirmed, keyring=self.keyring)
        except AppError as error:
            self.error = error
            self.machine.send(machine.ROLLBACK_FAILED_EVENT)
            raise
        self.machine.send(machine.ROLLBACK_DONE)
        return outcome

    def cancel(self):
        self.machine.send(machine.CANCEL)
        return self.state


__all__ = ["AUTO_CHECK", "ApplyResult", "CheckResult", "LOCK_NAME", "PASS_THROUGH", "STALE_STAGING_SECONDS", "UpdateSession", "apply_update", "check_for_update", "check_from_folder", "download_update", "estimate_backup_bytes",
           "recover_update", "stage_update_from_folder", "update_folder"]
