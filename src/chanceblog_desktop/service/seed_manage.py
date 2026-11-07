"""씨앗(Seed) 관리 쓰기(Seed 관리 화면, 변경 등급 T2) — 새 화면 `Seed 관리` 가 `topic_engine/seeds.json` 을 고치는 **서비스 함수 한 곳**이다(블로그 프로필 쓰기 `blog_profiles.py` 와 같은 틀을 본떴다).

화면(`ui/`)은 이 모듈의 함수만 부르고 파일을 직접 쓰지 않는다(시험이 소스를 훑는다). 명령줄 `topics seeds import` 가 부르는 `topics.import_seeds` 는 그대로이고(미리 보기만 이 모듈이 부른다) 그 쓰기에는 잠금·사본·판 확인이 없다 — 화면은 이 모듈의 쓰기 길만 쓴다.
  · `read_snapshot` — 읽기만 한다(파일도 폴더도 만들지 않는다). 씨앗들과 **판**(내용 지문 — 파일이 없으면 `missing`)·기준일·'쉬게 할까요' 제안(180일 — 제안만 한다)·채널별 후보 생성 켜짐 여부를 돌려준다.
    파일이 없거나 0바이트면 빈 목록에서 시작한다. 읽을 수 없거나 모양이 틀린 파일은 읽지 않고 오류로 멈춘다(`TOPIC_FILE_INVALID`·`CONTENT_INVALID`) — **틀린 파일을 고쳐 읽거나 덮어쓰지 않는다**.
  · `set_state` — 씨앗 하나의 상태를 `TRANSITIONS` 가 허용하는 길로만 바꾼다(승인 전 → 사용 중·쉬는 중, 사용 중 ↔ 쉬는 중). 사용 중이 되면 사용 시작일이 기준일이 된다(180일 시계).
    `set_states` — 여러 개를 **한꺼번에**(전부 바꾸거나 하나도 안 바꾼다 — 한 번의 쓰기). `confirmed=True`(진짜 `True`)와 확인한 개수(`expected_count`)가 있어야 하고, 하나라도 바꿀 수 없으면 아무것도 쓰지 않는다.
  · `edit_seed` — 우선 표시·제외 키워드·우선 키워드·허용 채널·제안 이유만 고친다(낱말·대분류·중분류·소속·중요도·대상 유형·상태·계절 일정은 못 바꾼다).
  · `create_seed` — 수동 등록. **처음 상태는 늘 승인 전**이다(사용 중으로 등록하는 길이 없다). 번호는 서비스가 `M001` 처럼 다음 숫자로 정한다(난수 없음). 같은 소속의 같은 낱말은 거절한다.
  · `preview_import`(읽기만) · `apply_import` — 씨앗 제안 파일: 미리 본 씨앗을 **모두 승인 전**으로만 한 번에 더한다(이미 있는 씨앗은 건너뜀 — 미리 보기 규칙은 `topics.import_seeds` 와 같다).
  · 씨앗이 파일에서 **사라지는 길은 없다**(삭제 없음 — 쉬게 둘 뿐이다).

쓰기 안전(다섯 쓰기 함수가 같은 길 `_commit` 을 지난다):
  1. 쓸 것이 없는 경우(낡은 판·틀린 값·바뀐 것 없음)는 **잠금도 파일도 만들지 않고** 끝난다(미리 계획해 본다).
  2. 잠금(`locks/seeds.lock`)을 잡는다 — 쥔 곳이 있으면 몇 초 기다린 뒤 아무것도 바꾸지 않고 물러난다(`TOPIC_STORE_LOCKED`).
  3. 잠금 안에서 다시 읽고 **판을 확인**한다 — 화면이 읽은 뒤 다른 곳(창 둘·명령줄·손 편집)이 파일을 바꿨으면 아무것도 쓰지 않는다(`STORE_CONFLICT`).
  4. 새 목록은 `Seed` 생성자로 검사하고(`seeds_to_dict` — 같은 번호·같은 낱말 두 번·개수 상한), 읽을 때와 **같은** `check_json_bytes` 로 쓸 바이트를 먼저 검사한다. **바뀌거나 새로 생긴 씨앗의 글**에 키·토큰 모양이 있으면 쓰지 않는다(백업이 막히지 않게).
  5. **안전망 `_guard`**: 옛 목록과 새 목록을 견준다 — 상태가 바뀐 씨앗은 부른 쪽이 말한 번호뿐이고 `TRANSITIONS` 를 지킨다 · 새 씨앗은 모두 승인 전이다 · 옛 씨앗이 하나도 사라지지 않는다 · 바뀐 칸은 그 함수가 바꿀 수 있는 칸뿐이다. 어기면 아무것도 쓰지 않는다.
  6. **백업 먼저**: 지금 파일의 직전 내용을 `seeds.json.bak` 에(판 1 파일이면 옛 모양 사본 `.v1.bak` 도) 원자적으로 쓴다 — **백업이 실패하면 본 파일은 쓰지 않는다**(원본 유지).
  7. 본 파일은 `context.write_json`(임시 파일 → `fsync` → 이름 바꾸기)으로만 쓴다 — 이 모듈에는 낮은 수준의 쓰기 호출이 없다(`test_service_safety`). 한 번의 이름 바꾸기라 '일부만 저장' 이 없다.
  8. 쓴 뒤 파일을 **다시 읽어** 방금 만든 내용과 같은지 확인한다(독립 검증). 다르면 직전 내용으로 되돌리고 실패로 알린다.
쓰기가 닿는 파일은 `seeds.json`·`.bak`·(`.v1.bak`)·잠금 파일과 처음 저장할 때의 `topic_engine/` 폴더뿐이다 — 보관함·채널 프로필·캘린더·글 보관함·설정·연결 설정·후보·초안·발행 기록과 키 보관소는 건드리지 않는다.
실제 씨앗 목록은 이 코드에 없다 — 사용자가 화면에서 넣거나 불러온 값이 이 PC 의 데이터 폴더에만 저장된다.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import re
from pathlib import Path
from typing import NamedTuple

from ..content.candidates import keyword_key
from ..errors import AppError
from ..topicdb import backup as tbackup
from ..topics import channels, layout
from ..topics import seeds as sd
from . import topic_files as tf
from . import topics as topic_service
from .context import write_json
from .lock import PublishLock

FILE_NAME = layout.SEEDS_FILE
BACKUP_NAME = FILE_NAME + ".bak"
LOCK_NAME = "seeds"                                          # 잠금 파일 `locks/seeds.lock`
LOCK_WAIT = 5.0                                              # 다른 곳이 쥐고 있으면 이만큼(초) 기다리고 그래도 안 풀리면 물러난다
VERSION_MISSING = "missing"                                  # 파일이 없을 때의 판
EDITABLE = ("priority", "excluded_keywords", "priority_keywords", "allowed_channels", "reason")           # 고칠 수 있는 칸 — 그 밖의 칸은 이 화면이 바꾸지 않는다
CREATE_REQUIRED = ("keyword", "major", "minor", "seed_type", "target_type", "scope")                       # 수동 등록에 꼭 있어야 하는 칸
CREATE_OPTIONAL = ("allowed_channels", "excluded_keywords", "priority_keywords", "sponsor_tag", "reason")  # 없으면 기본값
CREATE_SEED_TYPES = tuple(item for item in sd.SEED_TYPES if item != sd.SEED_SEASONAL)                      # 수동 등록은 계절형을 만들지 않는다(일정 칸이 있는 고급 편집은 범위 밖)
TEXT_FIELDS = ("major", "minor", "keyword", "reason", "excluded_keywords", "priority_keywords", "sponsor_tag")            # 사용자가 쓰는 글 칸 — 키 모양 검사 대상
MANUAL_PREFIX = "M"                                          # 수동 등록 씨앗 번호의 머리 — `M001`, `M002` …
_MANUAL = re.compile(r"M([0-9]+)")


class Snapshot(NamedTuple):
    seeds: tuple             # 씨앗들(파일 순서)
    version: str             # 판 — 파일 내용의 지문(sha256) 또는 `missing`. 쓸 때 `expected_version` 으로 되돌려 준다
    state: str               # `tf.STATE_MISSING`(파일이 없거나 0바이트 — 빈 목록) · `tf.STATE_OK`(파일을 읽음)
    today: str               # 기준일(한국 시간 YYYY-MM-DD) — 180일 계산과 사용 시작일에 쓴 날
    idle: tuple              # `IdleProposal` — 180일 넘게 선택하지 않은 사용 중 씨앗(계절형 제외). **제안만이다** — 아무것도 바꾸지 않았다
    generation: tuple        # ((채널, 켜짐 True·꺼짐 False·읽지 못함 None), …) — 채널 프로필의 후보 생성 칸(읽기만)


class Saved(NamedTuple):
    kind: str                # `saved`(썼다) · `unchanged`(바뀐 것이 없어 아무것도 쓰지 않았다)
    snapshot: Snapshot       # 이 일이 끝난 뒤의 상태(`saved` 면 방금 쓴 파일을 다시 읽은 것)
    changed: tuple           # 바뀌었거나 새로 생긴 씨앗 번호들
    backed_up: bool          # 직전 내용을 `.bak` 으로 남겼나


class ImportPreview(NamedTuple):
    result: object           # `topics.SeedImport`(미리 보기 — 아무것도 쓰지 않았다)
    version: str             # 미리 본 때의 `seeds.json` 판 — 등록할 때 되돌려 준다(그 사이 바뀌었으면 등록하지 않는다)
    today: str               # 등록일로 쓴 기준일


class SeedProblems(AppError):
    """칸의 값이 틀려서 저장하지 않았다(`CONTENT_INVALID`) — `problems` 는 `{칸 이름: 이유 낱말}`(`invalid`: 서비스 검사에 걸림 · `duplicate`: 같은 소속에 같은 낱말 · `key_shape`: 키처럼 보이는 글). 아무것도 쓰지 않았다."""

    def __init__(self, problems, *, detail=""):
        super().__init__("CONTENT_INVALID", {"항목": "씨앗 — " + ", ".join(sd.SEED_FIELD_KO.get(name) or "값" for name in problems)}, detail=detail or "칸의 값이 올바르지 않다")
        self.problems = dict(problems)


class SeedsLock(PublishLock):
    busy_code = "TOPIC_STORE_LOCKED"
    what = "씨앗 목록을 저장하다"


class _Read(NamedTuple):
    raw: object              # 지금 파일의 바이트(없으면 None)
    seeds: tuple
    version: str
    state: str


class _Rules(NamedTuple):
    """한 쓰기 함수가 바꿀 수 있는 것 — `_guard` 가 쓰기 직전에 견준다."""
    state_ids: frozenset     # 상태(와 사용 시작일)가 바뀔 수 있는 씨앗 번호
    field_ids: frozenset     # 칸을 고칠 수 있는 씨앗 번호
    fields: frozenset        # 고칠 수 있는 칸 이름
    add: bool                # 새 씨앗을 더해도 되는가


class _Plan(NamedTuple):
    read: _Read
    seeds: object            # 새 목록(바뀐 것이 없으면 None)
    payload: object
    changed: tuple


def _conflict():
    return AppError("STORE_CONFLICT", {"항목": "씨앗 목록"}, detail="화면이 읽은 뒤 씨앗 파일이 다른 곳에서 바뀌었다")


def _invalid(reason, *, detail=""):
    return AppError("CONTENT_INVALID", {"항목": "씨앗 — " + reason}, detail=detail or reason)


# ---- 읽기 ----------------------------------------------------------------------------------------------------------------------
def _version_of(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(paths):
    """아무것도 만들지 않고 지금 파일을 읽는다 — 파일이 없거나 0바이트면 빈 목록, 읽을 수 없거나 모양이 틀리면 오류(파일은 그대로)."""
    path = paths.seeds
    try:
        present = path.exists()
    except OSError:
        raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail="파일이 있는지 확인할 수 없다") from None
    if not present:
        return _Read(None, (), VERSION_MISSING, tf.STATE_MISSING)
    if not path.is_file():
        raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail="파일이 아니라 폴더 같은 것이다")
    raw = tf._read_bytes(path)
    if not raw:                                              # 0바이트 — 만들다 멈춘 흔적이라 잃을 내용이 없다(D-78): '아직 없음'
        return _Read(raw, (), _version_of(raw), tf.STATE_MISSING)
    return _Read(raw, tbackup.check_json_bytes(FILE_NAME, raw), _version_of(raw), tf.STATE_OK)


def _generation(paths):
    """채널마다 후보 생성이 켜져 있나 — 채널 프로필 파일을 읽기만 한다. 읽을 수 없으면 모른다(None) — 켜져 있다고 짐작하지 않는다."""
    try:
        profiles = tf.load_profiles(paths).value
    except AppError:
        return tuple((channel, None) for channel in channels.CHANNELS)
    return tuple((profile.key, bool(profile.generation_enabled)) for profile in profiles)


def _snapshot(paths, read, today):
    return Snapshot(read.seeds, read.version, read.state, today, sd.idle_proposals(read.seeds, today), _generation(paths))


def read_snapshot(ctx, *, today=None):
    """지금의 씨앗들과 판 — 읽기만 한다(파일도 폴더도 만들지 않는다). `today` 를 안 주면 지금(한국 시간)의 날짜다."""
    paths = tf.topic_paths(ctx.workspace)
    return _snapshot(paths, _read(paths), topic_service.today_of(ctx, today))


# ---- 규칙(순수) ----------------------------------------------------------------------------------------------------------------
def find(seeds, seed_id):
    """번호로 씨앗 하나 — 없으면 `CONTENT_INVALID`."""
    if isinstance(seed_id, str):
        for seed in seeds:
            if seed.seed_id == seed_id:
                return seed
    raise _invalid("그 번호의 씨앗이 목록에 없다")


def _replace(seeds, updated):
    return tuple(updated if seed.seed_id == updated.seed_id else seed for seed in seeds)


def next_id(seeds):
    """수동 등록 씨앗의 다음 번호 — `M` + 지금 있는 가장 큰 `M` 번호 + 1(세 자리 이상). 난수를 쓰지 않는다. 지우는 길이 없어 한 번 쓴 번호는 다시 쓰이지 않는다."""
    taken = {seed.seed_id for seed in seeds}
    found = [int(match.group(1)) for seed in seeds if (match := _MANUAL.fullmatch(seed.seed_id))]
    number = max(found, default=0) + 1
    while f"{MANUAL_PREFIX}{number:03d}" in taken:
        number += 1
    return f"{MANUAL_PREFIX}{number:03d}"


def _bad_field(error):
    """`Seed` 생성자가 낸 오류가 가리키는 첫 칸의 이름(모르면 빈 글)."""
    label = str(error.slots.get("항목", "")).split(" — ", 1)[0]
    if label.startswith(sd.SUBJECT + "의 "):
        label = label[len(sd.SUBJECT) + 2:]
    return next((name for name, korean in sd.SEED_FIELD_KO.items() if korean == label), "")


def apply_fields(seed, fields):
    """고칠 수 있는 칸의 값을 넣은 새 씨앗 — 칸마다 따로 검사해 틀린 칸을 모두 `SeedProblems` 로 알린다(`Seed` 생성자가 곧 심판이다). 고칠 수 없는 칸 이름은 코드 실수라 `ValueError`."""
    unknown = sorted(set(fields) - set(EDITABLE))
    if unknown or not fields:
        raise ValueError("이 화면이 고칠 수 있는 칸이 아니다: " + ", ".join(unknown))
    bad = {}
    for name, value in fields.items():
        try:
            dataclasses.replace(seed, **{name: value})
        except AppError as error:
            if error.requested_code != "CONTENT_INVALID":
                raise
            bad[name] = "invalid"
    if bad:
        raise SeedProblems(bad)
    try:
        return dataclasses.replace(seed, **fields)
    except AppError as error:                                # 칸 하나씩은 맞지만 함께는 안 되는 경우(우선 키워드 ↔ 제외 키워드)
        if error.requested_code != "CONTENT_INVALID":
            raise
        both = {name: "invalid" for name in fields if name in ("priority_keywords", "excluded_keywords")}
        raise SeedProblems(both or {"": "invalid"}) from None


def new_seed(seeds, fields, today):
    """수동 등록 씨앗 하나 — **상태는 늘 승인 전**이고 번호는 `next_id`, 우선 표시는 중요도가 우선일 때만 켠다(제안 파일을 읽을 때와 같다), 지역 자리표시가 낱말에 있으면 '지역 값 필요' 를 켠다."""
    missing = [name for name in CREATE_REQUIRED if name not in fields]
    unknown = sorted(set(fields) - set(CREATE_REQUIRED) - set(CREATE_OPTIONAL))
    if missing or unknown:
        raise ValueError("등록 칸이 맞지 않다: 빠진 칸 " + ", ".join(missing) + " · 모르는 칸 " + ", ".join(unknown))
    if fields["seed_type"] not in CREATE_SEED_TYPES:
        raise SeedProblems({"seed_type": "invalid"})
    if fields["target_type"] is None:
        raise SeedProblems({"target_type": "invalid"})
    keyword = fields["keyword"]
    values = dict(seed_id=next_id(seeds), major=fields["major"], minor=fields["minor"], keyword=keyword, seed_type=fields["seed_type"], scope=fields["scope"], registered_on=today, state=sd.STATE_PROPOSED,
                  priority=fields["seed_type"] == "priority", excluded_keywords=fields.get("excluded_keywords", ()), sponsor_tag=fields.get("sponsor_tag"), target_type=fields["target_type"],
                  allowed_channels=fields.get("allowed_channels"), priority_keywords=fields.get("priority_keywords", ()), reason=fields.get("reason", ""),
                  needs_region=isinstance(keyword, str) and sd.REGION_PLACEHOLDER in keyword, brand_case=False)
    try:
        made = sd.Seed(**values)
    except AppError as error:
        if error.requested_code != "CONTENT_INVALID":
            raise
        raise SeedProblems({_bad_field(error): "invalid"}) from None
    word = (made.scope, keyword_key(made.keyword))
    if any((seed.scope, keyword_key(seed.keyword)) == word for seed in seeds):
        raise SeedProblems({"keyword": "duplicate"})
    return made


# ---- 안전망 ----------------------------------------------------------------------------------------------------------------------
def _differences(before, after):
    old, new = before.to_dict(), after.to_dict()
    return {name for name in old if old[name] != new[name]}


def _guard(before, after, rules):
    """쓰기 직전의 마지막 점검 → 바뀌었거나 새로 생긴 씨앗 번호들. 코드 실수로 **승인하지 않은 씨앗의 상태가 바뀌거나·승인 전이 아닌 새 씨앗이 생기거나·씨앗이 사라지거나·허락되지 않은 칸이 바뀌는 일**을 막는다 —
    어기면 아무것도 쓰지 않고 `CONTENT_INVALID`."""
    kept = len(before)
    if len(after) < kept or [seed.seed_id for seed in after[:kept]] != [seed.seed_id for seed in before]:
        raise _invalid("씨앗이 사라지거나 순서가 바뀌는 변경은 하지 않는다", detail="안전망: 옛 씨앗이 모두 같은 자리에 있어야 한다")
    changed = []
    for old, new in zip(before, after[:kept], strict=True):
        if old == new:
            continue
        allowed = set()
        if old.seed_id in rules.state_ids:
            allowed |= {"state", "active_since"}
        if old.seed_id in rules.field_ids:
            allowed |= set(rules.fields)
        outside = _differences(old, new) - allowed
        if outside:
            raise _invalid("이 일이 바꿀 수 없는 칸이 바뀌려 했다", detail="안전망: 허락되지 않은 칸 " + ", ".join(sorted(outside)))
        if new.state != old.state and new.state not in sd.TRANSITIONS[old.state]:
            raise _invalid("바꿀 수 없는 상태 전환이다", detail="안전망: TRANSITIONS 밖의 전환")
        changed.append(old.seed_id)
    added = after[kept:]
    if added and not rules.add:
        raise _invalid("이 일은 새 씨앗을 더하지 않는다", detail="안전망: 새 씨앗이 생겼다")
    for seed in added:
        if seed.state != sd.STATE_PROPOSED or seed.active_since is not None or seed.last_selected_on is not None:
            raise _invalid("새 씨앗은 모두 승인 전이어야 한다", detail="안전망: 승인 전이 아닌 새 씨앗")
        changed.append(seed.seed_id)
    return tuple(changed)


def _refuse_key_shape(after, changed):
    """바뀌었거나 새로 생긴 씨앗의 글에 키·토큰 모양이 있으면 쓰지 않는다 — 백업이 막히지 않게(읽을 때와 같은 모양 검사). 글은 되풀이하지 않고 칸 이름만 알린다."""
    wanted = set(changed)
    found = {}
    for seed in after:
        if seed.seed_id in wanted:
            data = seed.to_dict()
            for name in TEXT_FIELDS:
                if tbackup.scan_key_shape(json.dumps(data[name], ensure_ascii=False)):
                    found[name] = "key_shape"
            if not found and tbackup.scan_key_shape(json.dumps(data, ensure_ascii=False)):
                found[""] = "key_shape"
    if found:
        raise SeedProblems(found, detail="키·토큰처럼 보이는 글이 들어 있다")


def _file_bytes(payload):
    """`write_json` 이 쓰는 바이트와 같은 모양(저장 전 검사용)."""
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _plan(paths, mutate, rules, expected_version):
    """쓰지 않고 계획만 세운다 — 판 확인·새 목록 검사·안전망·키 모양 검사. 낡은 판이면 `STORE_CONFLICT`, 틀린 값이면 `SeedProblems`/`CONTENT_INVALID`, 바뀐 것이 없으면 `seeds` 가 None 이다."""
    read = _read(paths)
    if read.version != expected_version:
        raise _conflict()
    new = tuple(mutate(read.seeds))
    if new == read.seeds:
        return _Plan(read, None, None, ())
    changed = _guard(read.seeds, new, rules)
    _refuse_key_shape(new, changed)
    payload = sd.seeds_to_dict(new)
    tbackup.check_json_bytes(FILE_NAME, _file_bytes(payload))        # 읽을 때와 같은 엄격한 검사를 쓰기 전에 한 번 더
    return _Plan(read, new, payload, changed)


# ---- 쓰기 틀 -----------------------------------------------------------------------------------------------------------------------
@contextlib.contextmanager
def _locked(ctx, wait):
    lock = SeedsLock(ctx.workspace.locks_dir, LOCK_NAME, now=ctx.now)
    lock.acquire_waiting(wait)
    try:
        yield lock
    finally:
        lock.release()


def _backup(paths, raw):
    """지금 파일의 직전 내용을 `.bak` 으로 먼저 남긴다 — 판 1 파일이면 옛 모양 사본(`.v1.bak`)도. 남길 것이 없으면(파일이 없거나 0바이트) False. 실패하면 오류 — 부른 쪽은 그때 본 파일을 쓰지 않는다."""
    if not raw:
        return False
    tf._keep_old_copy(paths.seeds)
    write_json(paths.seeds.with_name(BACKUP_NAME), json.loads(raw.decode("utf-8-sig")))
    return True


def _read_old_backup(paths):
    """지금 있는 사본(`.bak`)의 내용 — 본 파일 쓰기가 실패하면 사본도 이 내용으로 되돌려 쓰기 전과 같게 한다. 사본이 없거나 읽을 수 없으면 None(되돌릴 것이 없다)."""
    path = paths.seeds.with_name(BACKUP_NAME)
    try:
        return json.loads(tf._read_bytes(path).decode("utf-8-sig")) if path.is_file() else None
    except (AppError, ValueError):
        return None


def _undo_backup(paths, old):
    """실패한 저장이 먼저 덮어쓴 사본을 쓰기 전 내용으로 되돌린다 → 되돌렸으면(또는 되돌릴 사본이 없었으면) True. 새로 만든 사본은 현재 내용의 복사라 그대로 둔다(지우는 길은 서비스에 없다)."""
    if old is None:
        return True
    try:
        write_json(paths.seeds.with_name(BACKUP_NAME), old)
    except AppError:
        return False
    return True


def _restore(paths, plan):
    """쓴 내용이 검증에서 다르게 읽혔을 때 직전 내용으로 되돌린다 → 되돌렸으면 True, 못 되돌렸으면 False(직전 내용은 `.bak` 에 남아 있다). 파일이 없던 경우는 지울 길이 없어 빈 틀로 쓴다."""
    try:
        if plan.read.raw:
            write_json(paths.seeds, json.loads(plan.read.raw.decode("utf-8-sig")))
        else:
            write_json(paths.seeds, sd.seeds_to_dict(()))
    except AppError:
        return False
    return True


def _verify(ctx, paths, plan, backed_up, today):
    """쓴 파일을 다시 읽어 방금 만든 내용과 같은지 본다 → `Saved`. 다르면 되돌리고 `FILE_WRITE_FAILED`."""
    try:
        raw_after = tf._read_bytes(paths.seeds)
        after = tbackup.check_json_bytes(FILE_NAME, raw_after)
    except AppError:
        raw_after, after = None, None
    if after != plan.seeds:
        restored = _restore(paths, plan)
        problem = AppError("FILE_WRITE_FAILED", {"경로": FILE_NAME}, detail="쓴 뒤에 다시 읽어 보니 내용이 달랐다 — " + ("직전 내용으로 되돌렸다" if restored else "되돌리지도 못했다(직전 내용은 사본 파일에 남아 있다)"))
        problem.restored = restored
        raise problem
    return Saved("saved", _snapshot(paths, _Read(raw_after, after, _version_of(raw_after), tf.STATE_OK), today), plan.changed, backed_up)


def _commit(ctx, mutate, rules, expected_version, today, *, wait=LOCK_WAIT):
    paths = tf.topic_paths(ctx.workspace)
    early = _plan(paths, mutate, rules, expected_version)           # 잠금도 파일도 만들기 전에 — 낡은 판·틀린 값·바뀐 것 없음은 여기서 끝난다
    if early.seeds is None:
        return Saved("unchanged", _snapshot(paths, early.read, today), (), False)
    with _locked(ctx, wait):
        plan = _plan(paths, mutate, rules, expected_version)        # 잠금 안에서 다시 — 이 판이 진짜 심판이다
        if plan.seeds is None:
            return Saved("unchanged", _snapshot(paths, plan.read, today), (), False)
        old_backup = _read_old_backup(paths)
        backed_up = _backup(paths, plan.read.raw)                   # 실패하면 여기서 끝 — 본 파일은 쓰지 않았다
        try:
            write_json(paths.seeds, plan.payload)                   # 임시 파일 → fsync → 이름 바꾸기. 실패하면 옛 파일은 그대로
            return _verify(ctx, paths, plan, backed_up, today)
        except AppError as error:                                   # 쓰기·검증이 실패했다 — 본 파일은 직전 내용이고(되돌리지 못한 경우만 사본이 유일한 사본이라 건드리지 않는다), 사본도 쓰기 전 내용으로
            if backed_up and getattr(error, "restored", True) and not _undo_backup(paths, old_backup):
                error.detail = f"{error.detail} | 사본(.bak)을 쓰기 전 내용으로 되돌리지 못했다".strip(" |")
            raise


# ---- 쓰기 함수 ---------------------------------------------------------------------------------------------------------------------
def set_state(ctx, seed_id, new_state, *, expected_version, today=None, wait=LOCK_WAIT):
    """씨앗 하나의 상태를 바꾼다 — `TRANSITIONS` 가 허용하는 전환만(승인 전 → 사용 중·쉬는 중, 사용 중 ↔ 쉬는 중). 사용 중이 되면 사용 시작일이 기준일이다. 안 되는 전환은 아무것도 쓰지 않고 `CONTENT_INVALID`."""
    day = topic_service.today_of(ctx, today)

    def mutate(seeds):
        return _replace(seeds, sd.change_state(find(seeds, seed_id), new_state, on=day))

    rules = _Rules(frozenset((seed_id,)), frozenset(), frozenset(), False)
    return _commit(ctx, mutate, rules, expected_version, day, wait=wait)


def set_states(ctx, seed_ids, new_state, *, confirmed, expected_count, expected_version, today=None, wait=LOCK_WAIT):
    """씨앗 여러 개의 상태를 **한꺼번에** 바꾼다 — 전부 바뀌거나 하나도 안 바뀐다(한 번의 쓰기). `confirmed` 가 진짜 `True` 가 아니면(`1`·`"yes"` 도 안 된다) 읽지도 않고 `CONFIRMATION_REQUIRED`,
    `expected_count`(확인창이 보인 개수)가 번호 수와 다르면 아무것도 쓰지 않고 `CONFIRMATION_REQUIRED`. 번호가 겹치거나 없거나 하나라도 바꿀 수 없는 전환이면 아무것도 쓰지 않고 `CONTENT_INVALID`."""
    if confirmed is not True:
        raise AppError("CONFIRMATION_REQUIRED", {"항목": "씨앗 여러 개의 상태 바꾸기 — 승인 전 씨앗이 사용 중이 되면 그때부터 후보 생성에 쓰입니다(나중에 쉬는 중으로 되돌릴 수 있습니다)"},
                       detail="여러 개를 바꾸는 일은 확인 표시(confirmed=True)가 있을 때만 한다")
    ids = tuple(seed_ids)
    if not ids or not all(isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("씨앗 번호는 겹치지 않는 글 하나 이상이어야 한다")
    if expected_count != len(ids) or isinstance(expected_count, bool):
        raise AppError("CONFIRMATION_REQUIRED", {"항목": "씨앗 여러 개의 상태 바꾸기 — 확인한 개수와 바꾸려는 개수가 다릅니다"}, detail="확인창이 보인 개수와 번호 수가 다르다")
    day = topic_service.today_of(ctx, today)

    def mutate(seeds):
        current = seeds
        for seed_id in ids:
            current = _replace(current, sd.change_state(find(current, seed_id), new_state, on=day))
        return current

    rules = _Rules(frozenset(ids), frozenset(), frozenset(), False)
    return _commit(ctx, mutate, rules, expected_version, day, wait=wait)


def edit_seed(ctx, seed_id, fields, *, expected_version, wait=LOCK_WAIT):
    """씨앗 하나의 칸을 고친다 — `EDITABLE` 칸만. 상태는 바뀌지 않는다. 틀린 값은 칸마다 알리고(`SeedProblems`) 아무것도 쓰지 않는다. `fields` 는 `{칸 이름: 값}`(낱말 칸은 목록, 우선 표시는 True·False)."""
    day = topic_service.today_of(ctx, None)

    def mutate(seeds):
        return _replace(seeds, apply_fields(find(seeds, seed_id), fields))

    rules = _Rules(frozenset(), frozenset((seed_id,)), frozenset(EDITABLE), False)
    return _commit(ctx, mutate, rules, expected_version, day, wait=wait)


def create_seed(ctx, fields, *, expected_version, today=None, wait=LOCK_WAIT):
    """수동 등록 — **승인 전**으로 목록 끝에 더한다(사용 중으로 등록하는 길이 없다). 칸은 `CREATE_REQUIRED`·`CREATE_OPTIONAL`, 같은 소속의 같은 낱말은 `SeedProblems({"keyword": "duplicate"})`."""
    day = topic_service.today_of(ctx, today)

    def mutate(seeds):
        return (*seeds, new_seed(seeds, fields, day))

    rules = _Rules(frozenset(), frozenset(), frozenset(), True)
    return _commit(ctx, mutate, rules, expected_version, day, wait=wait)


def preview_import(ctx, source, *, today=None):
    """씨앗 제안 파일(경로)의 미리 보기 — **읽기만 한다**(`topics.import_seeds(apply=False)`). 지금 파일이 깨졌으면 그 위에 등록하지 않도록 여기서 오류로 멈춘다. 돌려준 판을 `apply_import` 에 되돌려 준다."""
    day = topic_service.today_of(ctx, today)
    paths = tf.topic_paths(ctx.workspace)
    version = _read(paths).version                           # 파일을 읽기 전에 판을 먼저 — 그 사이 바뀌면 판이 낡아 등록이 거절된다
    result = topic_service.import_seeds(ctx, Path(source), apply=False, today=day)
    return ImportPreview(result, version, day)


def apply_import(ctx, new_seeds, *, expected_version, wait=LOCK_WAIT):
    """미리 본 새 씨앗(`ImportPreview.result.new`)을 **모두 승인 전**으로 한 번에 더한다 — 승인 전이 아닌 씨앗은 받지 않는다. 이미 있는 번호·같은 소속의 같은 낱말이 생겼으면 아무것도 쓰지 않는다."""
    added = tuple(new_seeds)
    if not all(isinstance(seed, sd.Seed) for seed in added):
        raise ValueError("씨앗(Seed)만 더할 수 있다")
    day = topic_service.today_of(ctx, None)

    def mutate(seeds):
        ids = {seed.seed_id for seed in seeds}
        words = {(seed.scope, keyword_key(seed.keyword)) for seed in seeds}
        for seed in added:
            if seed.seed_id in ids or (seed.scope, keyword_key(seed.keyword)) in words:
                raise _invalid("미리 본 뒤에 같은 번호나 같은 낱말이 생겼다 — 다시 미리 보기를 해 주세요")
        return (*seeds, *added)

    rules = _Rules(frozenset(), frozenset(), frozenset(), True)
    return _commit(ctx, mutate, rules, expected_version, day, wait=wait)
