"""블로그 프로필 쓰기(P4b, 변경 등급 T2) — 새 화면 `블로그 관리` 가 주제 엔진의 채널 프로필(`topic_engine/channel_profiles.json`)을 고치는 **서비스 함수 한 곳**이다.

화면(`ui/`)은 이 모듈의 함수만 부르고 파일을 직접 쓰지 않는다(시험이 소스를 훑는다). 읽기·쓰기는 모두 다섯 슬롯(`github_pages`·`blogger_en`·`blogger_ko`·`naver_a`·`naver_b`)을 한 묶음으로 다룬다:
  · `read_snapshot` — 읽기만 한다(파일도 폴더도 만들지 않는다). 프로필 다섯 개와 **판**(내용 지문 — 파일이 없으면 `missing`)을 돌려준다. 파일이 없거나 0바이트면 기본 프로필에서 시작한다.
    읽을 수 없거나 모양이 틀린 파일은 읽지 않고 오류로 멈춘다(`TOPIC_FILE_INVALID`·`CONTENT_INVALID`) — **틀린 파일을 고쳐 읽거나 덮어쓰지 않는다**.
  · `save_slot` — 한 슬롯의 **폼 칸만** 바꾼다(엔진 칸·다른 슬롯·화면이 모르는 칸은 그대로). `clone_slot` — 비어 있는 같은 종류 슬롯으로만 값을 복사한다(덮어쓰기 금지).
    `clear_slot` — 슬롯을 **비운다**(슬롯이 사라지지 않는다 — 다섯 슬롯은 늘 그대로이고 폼 칸이 기본 프로필의 값으로 돌아간다). 확인 표시(`confirmed=True`)가 없으면 읽지도 않고 멈춘다.

쓰기 안전(세 함수가 같은 길 `_commit` 을 지난다):
  1. 쓸 것이 없는 경우(낡은 판·틀린 값·바뀐 것 없음)는 **잠금도 파일도 만들지 않고** 끝난다(미리 계획해 본다).
  2. 잠금(`locks/blog-profiles.lock`)을 잡는다 — 쥔 곳이 있으면 몇 초 기다린 뒤 아무것도 바꾸지 않고 물러난다(`TOPIC_STORE_LOCKED`).
  3. 잠금 안에서 다시 읽고 **판을 확인**한다 — 화면이 읽은 뒤 다른 곳(창 둘·명령줄·손 편집)이 파일을 바꿨으면 아무것도 쓰지 않는다(`STORE_CONFLICT`).
  4. 새 내용은 `ChannelProfile` 생성자로 검사하고(칸마다 따로 — 어느 칸이 틀렸는지 `ProfileProblems.problems`), 읽을 때와 **같은** `check_json_bytes`(모양 + 글칸의 키 모양)로 쓸 바이트를 먼저 검사한다 — 이 화면이 저장한 파일을 이 앱이 못 읽게 되는 일이 없다.
  5. **백업 먼저**: 지금 파일의 직전 내용을 `channel_profiles.json.bak` 에(판 1 파일이면 옛 모양 사본 `.v1.bak` 도) 원자적으로 쓴다 — **백업이 실패하면 본 파일은 쓰지 않는다**(원본 유지).
  6. 본 파일은 `context.write_json`(임시 파일 → `fsync` → 이름 바꾸기)으로만 쓴다 — 이 모듈에는 낮은 수준의 쓰기 호출이 없다(`test_service_safety`). 한 번의 이름 바꾸기라 '일부만 저장' 이 없고, 실패하면 옛 파일은 한 바이트도 안 바뀐다.
  7. 쓴 뒤 파일을 **다시 읽어** 방금 만든 내용과 같은지 확인한다(독립 검증). 다르면 직전 내용으로 되돌리고 실패로 알린다.
쓰기가 닿는 파일은 `channel_profiles.json`·`.bak`·(`.v1.bak`)·잠금 파일과 처음 저장할 때의 `topic_engine/` 폴더뿐이다 — 보관함·씨앗·캘린더·글 보관함·설정·연결 설정·후보·초안·발행 기록과 키 보관소는 건드리지 않는다.
실제 블로그 이름·아이디·주소는 이 코드에 없다 — 사용자가 화면에서 넣은 값이 이 PC 의 데이터 폴더에만 저장된다.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
from typing import NamedTuple

from ..errors import AppError
from ..topicdb import backup as tbackup
from ..topics import channels, layout
from . import topic_files as tf
from .context import write_json
from .lock import PublishLock

FILE_NAME = layout.CHANNEL_PROFILES_FILE
BACKUP_NAME = FILE_NAME + ".bak"
LOCK_NAME = "blog-profiles"                                  # 잠금 파일 `locks/blog-profiles.lock`
LOCK_WAIT = 5.0                                              # 다른 곳이 쥐고 있으면 이만큼(초) 기다리고 그래도 안 풀리면 물러난다
VERSION_MISSING = "missing"                                  # 파일이 없을 때의 판
SLOTS = channels.CHANNELS                                    # 다섯 슬롯(코드의 채널 순서)
GENERATION_SLOTS = ("naver_a", "naver_b")                    # 후보 생성(사용 여부)을 이 화면에서 켜고 끌 수 있는 슬롯 — 나머지 셋의 후보 생성은 이 화면이 바꾸지 않는다(운영자 확정 답변 9)
SLOT_KINDS = (("naver_a", "naver_b"), ("blogger_ko", "blogger_en"), ("github_pages",))      # 복제는 같은 종류 슬롯끼리만
COMMON_FIELDS = ("display_name", "blog_ref", "language", "alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "color_preset", "profile_image", "cover_image",
                 "monetization_focus")                        # 폼이 가진 칸 — 모든 슬롯이 같다(후보 생성 칸은 네이버 슬롯만 더 가진다)
TEXT_FIELDS = ("display_name", "blog_ref", "alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "profile_image", "cover_image")      # 사용자가 쓰는 글 칸 — 키 모양 검사 대상


class Snapshot(NamedTuple):
    profiles: tuple          # 채널 프로필 다섯 개(코드의 채널 순서)
    version: str             # 판 — 파일 내용의 지문(sha256) 또는 `missing`. 쓸 때 `expected_version` 으로 되돌려 준다
    state: str               # `tf.STATE_MISSING`(파일이 없거나 0바이트 — 기본값) · `tf.STATE_OK`(파일을 읽음)


class Saved(NamedTuple):
    kind: str                # `saved`(썼다) · `unchanged`(바뀐 것이 없어 아무것도 쓰지 않았다)
    snapshot: Snapshot       # 이 일이 끝난 뒤의 상태(`saved` 면 방금 쓴 파일을 다시 읽은 것)
    changed: tuple           # 바뀐 슬롯들
    backed_up: bool          # 직전 내용을 `.bak` 으로 남겼나


class ProfileProblems(AppError):
    """칸의 값이 틀려서 저장하지 않았다(`CONTENT_INVALID`) — `problems` 는 `{칸 이름: 이유 낱말}`(`invalid`: 서비스 검사에 걸림 · `key_shape`: 키처럼 보이는 글). 아무것도 쓰지 않았다."""

    def __init__(self, problems, *, detail=""):
        super().__init__("CONTENT_INVALID", {"항목": "블로그 프로필 — " + ", ".join(channels.PROFILE_FIELD_KO.get(name, name) for name in problems)}, detail=detail or "칸의 값이 올바르지 않다")
        self.problems = dict(problems)


class ProfilesLock(PublishLock):
    busy_code = "TOPIC_STORE_LOCKED"
    what = "블로그 프로필을 저장하다"


# ---- 슬롯 규칙(순수) ------------------------------------------------------------------------------------------------------------
def check_slot(key):
    if not isinstance(key, str) or key not in SLOTS:
        raise ValueError("아는 슬롯 이름이 아니다")
    return key


def form_fields(key):
    """그 슬롯의 폼 칸 이름들. 네이버 A·B 는 후보 생성(`generation_enabled`)을 더 가진다."""
    return COMMON_FIELDS + (("generation_enabled",) if check_slot(key) in GENERATION_SLOTS else ())


def kind_of(key):
    """같은 종류의 슬롯들(자기 자신 포함) — 복제는 이 안에서만 한다."""
    check_slot(key)
    return next(kind for kind in SLOT_KINDS if key in kind)


def default_profile(key):
    check_slot(key)
    return next(profile for profile in channels.default_profiles() if profile.key == key)


def is_registered(profile):
    """등록된 슬롯 — 블로그 ID 또는 주소가 있다."""
    return bool(profile.blog_ref)


def is_empty(profile):
    """비어 있는 슬롯 — 폼 칸이 모두 기본 프로필의 값이다(새로 쓰는 PC 의 모습). 이름 하나만 바꿔도 비어 있지 않다 — 덮어써서 지우는 일이 없게 보존이 우선이다."""
    base = default_profile(profile.key)
    return all(getattr(profile, name) == getattr(base, name) for name in form_fields(profile.key))


def clone_target(profiles, key):
    """`key` 의 값을 복제해 넣을 수 있는 슬롯 — 같은 종류의 **비어 있는** 다른 슬롯(없으면 None)."""
    by_key = {profile.key: profile for profile in profiles}
    return next((other for other in kind_of(key) if other != key and is_empty(by_key[other])), None)


# ---- 읽기 --------------------------------------------------------------------------------------------------------------------
def _version_of(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(paths):
    """(읽은 바이트 또는 None, `Snapshot`) — 아무것도 만들지 않는다. 파일이 없거나 0바이트면 기본 프로필, 읽을 수 없거나 모양이 틀리면 오류(파일은 그대로)."""
    path = paths.profiles
    try:
        present = path.exists()
    except OSError:
        raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail="파일이 있는지 확인할 수 없다") from None
    if not present:
        return None, Snapshot(channels.default_profiles(), VERSION_MISSING, tf.STATE_MISSING)
    if not path.is_file():
        raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail="파일이 아니라 폴더 같은 것이다")
    raw = tf._read_bytes(path)
    if not raw:                                              # 0바이트 — 만들다 멈춘 흔적이라 잃을 내용이 없다(D-78): '아직 없음'
        return raw, Snapshot(channels.default_profiles(), _version_of(raw), tf.STATE_MISSING)
    return raw, Snapshot(tbackup.check_json_bytes(FILE_NAME, raw), _version_of(raw), tf.STATE_OK)


def read_snapshot(ctx):
    """지금의 채널 프로필 다섯 개와 판 — 읽기만 한다(파일도 폴더도 만들지 않는다)."""
    return _read(tf.topic_paths(ctx.workspace))[1]


# ---- 새 내용 만들기(순수) --------------------------------------------------------------------------------------------------------
def _by_key(profiles):
    return {profile.key: profile for profile in profiles}


def _with_slot(profiles, updated):
    return tuple(updated if profile.key == updated.key else profile for profile in profiles)


def apply_fields(profile, fields):
    """폼 칸의 값을 넣은 새 프로필 — 칸마다 따로 검사해 틀린 칸을 모두 `ProfileProblems` 로 알린다(생성자가 곧 심판이다). 모르는 칸 이름은 코드 실수라 `ValueError`."""
    allowed = form_fields(profile.key)
    unknown = sorted(set(fields) - set(allowed))
    if unknown:
        raise ValueError("이 슬롯의 폼 칸이 아니다: " + ", ".join(unknown))
    bad = {}
    for name, value in fields.items():
        try:
            dataclasses.replace(profile, **{name: value})
        except AppError as error:
            if error.requested_code != "CONTENT_INVALID":
                raise
            bad[name] = "invalid"
    if bad:
        raise ProfileProblems(bad)
    try:
        return dataclasses.replace(profile, **fields)
    except AppError as error:
        if error.requested_code != "CONTENT_INVALID":
            raise
        raise ProfileProblems({"": "invalid"}) from None


def _key_shaped(profile):
    """글 칸 중 키·토큰처럼 보이는 글이 든 칸의 이름들 — 읽을 때의 검사(`check_json_bytes`)와 백업의 검사(`scan_key_shape`)와 같은 규칙으로 저장 전에 거른다."""
    return tuple(name for name in TEXT_FIELDS if tbackup.scan_key_shape(json.dumps(getattr(profile, name), ensure_ascii=False)))


def _file_bytes(payload):
    """`write_json` 이 쓰는 바이트와 같은 모양(저장 전 검사용)."""
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


class _Plan(NamedTuple):
    snapshot: Snapshot
    raw: object              # 지금 파일의 바이트(없으면 None)
    profiles: object         # 새 프로필 다섯 개(바뀐 것이 없으면 None)
    payload: object
    changed: tuple


def _conflict():
    return AppError("STORE_CONFLICT", {"항목": "블로그 프로필"}, detail="화면이 읽은 뒤 프로필 파일이 다른 곳에서 바뀌었다")


def _plan(paths, mutate, expected_version):
    """쓰지 않고 계획만 세운다 — 판 확인·새 내용 검사·키 모양 검사. 낡은 판이면 `STORE_CONFLICT`, 틀린 값이면 `ProfileProblems`/`CONTENT_INVALID`, 바뀐 것이 없으면 `profiles` 가 None 이다."""
    raw, snapshot = _read(paths)
    if snapshot.version != expected_version:
        raise _conflict()
    new = mutate(snapshot.profiles)
    if new == snapshot.profiles:
        return _Plan(snapshot, raw, None, None, ())
    old_by_key, new_by_key = _by_key(snapshot.profiles), _by_key(new)
    changed = tuple(key for key in SLOTS if new_by_key[key] != old_by_key[key])
    shaped = {name: "key_shape" for key in changed for name in _key_shaped(new_by_key[key])}
    if shaped:
        raise ProfileProblems(shaped, detail="키·토큰처럼 보이는 글이 들어 있다")
    payload = channels.profiles_to_dict(new)
    tbackup.check_json_bytes(FILE_NAME, _file_bytes(payload))        # 읽을 때와 같은 엄격한 검사를 쓰기 전에 한 번 더(모양 + 글칸의 키 모양)
    return _Plan(snapshot, raw, new, payload, changed)


@contextlib.contextmanager
def _locked(ctx, wait):
    lock = ProfilesLock(ctx.workspace.locks_dir, LOCK_NAME, now=ctx.now)
    lock.acquire_waiting(wait)
    try:
        yield lock
    finally:
        lock.release()


def _backup(paths, raw):
    """지금 파일의 직전 내용을 `.bak` 으로 먼저 남긴다 — 판 1 파일이면 옛 모양 사본(`.v1.bak`)도. 남길 것이 없으면(파일이 없거나 0바이트) False. 실패하면 오류 — 부른 쪽은 그때 본 파일을 쓰지 않는다."""
    if not raw:
        return False
    tf._keep_old_copy(paths.profiles)
    write_json(paths.profiles.with_name(BACKUP_NAME), json.loads(raw.decode("utf-8-sig")))
    return True


def _read_old_backup(paths):
    """지금 있는 사본(`.bak`)의 내용 — 본 파일 쓰기가 실패하면 사본도 이 내용으로 되돌려 쓰기 전과 같게 한다. 사본이 없거나 읽을 수 없으면 None(되돌릴 것이 없다)."""
    path = paths.profiles.with_name(BACKUP_NAME)
    try:
        return json.loads(tf._read_bytes(path).decode("utf-8-sig")) if path.is_file() else None
    except (AppError, ValueError):
        return None


def _undo_backup(paths, old):
    """실패한 저장이 먼저 덮어쓴 사본을 쓰기 전 내용으로 되돌린다 → 되돌렸으면(또는 되돌릴 사본이 없었으면) True. 새로 만든 사본은 현재 내용의 복사라 그대로 둔다(지우는 길은 서비스에 없다)."""
    if old is None:
        return True
    try:
        write_json(paths.profiles.with_name(BACKUP_NAME), old)
    except AppError:
        return False
    return True


def _restore(paths, plan):
    """쓴 내용이 검증에서 다르게 읽혔을 때 직전 내용으로 되돌린다 → 되돌렸으면 True, 못 되돌렸으면 False(직전 내용은 `.bak` 에 남아 있다). 파일이 없던 경우는 지울 길이 없어 기본 틀로 쓴다."""
    try:
        if plan.raw:
            write_json(paths.profiles, json.loads(plan.raw.decode("utf-8-sig")))
        else:
            write_json(paths.profiles, channels.profiles_to_dict(channels.default_profiles()))
    except AppError:
        return False
    return True


def _verify(paths, plan, backed_up):
    """쓴 파일을 다시 읽어 방금 만든 내용과 같은지 본다 → `Saved`. 다르면 되돌리고 `FILE_WRITE_FAILED`."""
    try:
        raw_after = tf._read_bytes(paths.profiles)
        after = tbackup.check_json_bytes(FILE_NAME, raw_after)
    except AppError:
        raw_after, after = None, None
    if after != plan.profiles:
        restored = _restore(paths, plan)
        problem = AppError("FILE_WRITE_FAILED", {"경로": FILE_NAME}, detail="쓴 뒤에 다시 읽어 보니 내용이 달랐다 — " + ("직전 내용으로 되돌렸다" if restored else "되돌리지도 못했다(직전 내용은 사본 파일에 남아 있다)"))
        problem.restored = restored
        raise problem
    return Saved("saved", Snapshot(after, _version_of(raw_after), tf.STATE_OK), plan.changed, backed_up)


def _commit(ctx, mutate, expected_version, *, wait=LOCK_WAIT):
    paths = tf.topic_paths(ctx.workspace)
    early = _plan(paths, mutate, expected_version)                  # 잠금도 파일도 만들기 전에 — 낡은 판·틀린 값·바뀐 것 없음은 여기서 끝난다
    if early.profiles is None:
        return Saved("unchanged", early.snapshot, (), False)
    with _locked(ctx, wait):
        plan = _plan(paths, mutate, expected_version)               # 잠금 안에서 다시 — 이 판이 진짜 심판이다
        if plan.profiles is None:
            return Saved("unchanged", plan.snapshot, (), False)
        old_backup = _read_old_backup(paths)
        backed_up = _backup(paths, plan.raw)                        # 실패하면 여기서 끝 — 본 파일은 쓰지 않았다
        try:
            write_json(paths.profiles, plan.payload)                # 임시 파일 → fsync → 이름 바꾸기. 실패하면 옛 파일은 그대로
            return _verify(paths, plan, backed_up)
        except AppError as error:                                   # 쓰기·검증이 실패했다 — 본 파일은 직전 내용이고(되돌리지 못한 경우만 사본이 유일한 사본이라 건드리지 않는다), 사본도 쓰기 전 내용으로
            if backed_up and getattr(error, "restored", True) and not _undo_backup(paths, old_backup):
                error.detail = f"{error.detail} | 사본(.bak)을 쓰기 전 내용으로 되돌리지 못했다".strip(" |")
            raise


# ---- 쓰기 함수 셋 ------------------------------------------------------------------------------------------------------------
def save_slot(ctx, key, fields, *, expected_version, wait=LOCK_WAIT):
    """한 슬롯의 폼 칸만 바꿔 저장한다. `fields` 는 `{칸 이름: 값}`(글은 한 줄로 다듬은 값, 낱말 칸은 목록, 색 프리셋은 None 이나 이름, 후보 생성은 True·False) — 안 준 칸은 그대로다."""
    check_slot(key)

    def mutate(profiles):
        return _with_slot(profiles, apply_fields(_by_key(profiles)[key], fields))

    return _commit(ctx, mutate, expected_version, wait=wait)


def clone_slot(ctx, source, target, *, expected_version, wait=LOCK_WAIT):
    """`source` 슬롯의 폼 칸 값을 같은 종류의 **비어 있는** `target` 슬롯으로 복사한다 — 덮어쓰기는 하지 않는다(`target` 이 비어 있지 않으면 아무것도 쓰지 않고 `CONTENT_INVALID`)."""
    check_slot(source)
    check_slot(target)
    if source == target or target not in kind_of(source):
        raise ValueError("복제는 같은 종류의 다른 슬롯으로만 한다")

    def mutate(profiles):
        by_key = _by_key(profiles)
        if not is_registered(by_key[source]):
            raise AppError("CONTENT_INVALID", {"항목": "복제할 프로필 — 블로그가 등록된 슬롯이어야 한다"})
        if not is_empty(by_key[target]):
            raise AppError("CONTENT_INVALID", {"항목": "복제할 자리 — 비어 있는 슬롯이어야 한다(덮어쓰지 않는다)"})
        values = {name: getattr(by_key[source], name) for name in form_fields(target)}
        return _with_slot(profiles, apply_fields(by_key[target], values))

    return _commit(ctx, mutate, expected_version, wait=wait)


def clear_slot(ctx, key, *, confirmed, expected_version, wait=LOCK_WAIT):
    """슬롯을 비운다 — 폼 칸이 기본 프로필의 값으로 돌아가고(엔진 칸은 그대로) 슬롯은 사라지지 않는다. `confirmed` 가 진짜 `True` 가 아니면(`1`·`"yes"` 도 안 된다) 읽지도 않고 `CONFIRMATION_REQUIRED`."""
    check_slot(key)
    if confirmed is not True:
        raise AppError("CONFIRMATION_REQUIRED", {"항목": "블로그 프로필 지우기 — 이 슬롯에 넣은 이름·블로그 ID·주제 같은 내용이 비워집니다(이 프로필로 만든 후보·초안·발행 기록은 지워지지 않습니다)"},
                       detail="지우기는 확인 표시(confirmed=True)가 있을 때만 한다")
    base = default_profile(key)

    def mutate(profiles):
        return _with_slot(profiles, apply_fields(_by_key(profiles)[key], {name: getattr(base, name) for name in form_fields(key)}))

    return _commit(ctx, mutate, expected_version, wait=wait)
