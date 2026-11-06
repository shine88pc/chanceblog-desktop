"""주제 엔진의 설정 파일 셋 — 채널 프로필(`channel_profiles.json`)·씨앗(`seeds.json`)·캘린더(`calendar.json`)를 읽고 만든다(P3, 계획 4.4, 결정 D-59).

모두 사용자 데이터 폴더 아래 `topic_engine\\` 에 둔다(열린 항목 2 의 기본값). **읽기·쓰기는 `topics/` 의 `to_dict`·`from_dict`(엄격한 모양 — `schema` 숫자·정확한 칸·모르는 칸 거절)와 `context.write_json` 만 거친다.**
  · 읽기: 파일이 없으면 '기본값/빈 목록' 으로 읽고 **파일을 만들지 않는다**(만들기는 `topics init --yes` 뿐이다). 파일이 있으면 엄격하게 읽고, 틀리면 읽지 않고 오류로 멈춘다 — 글자나 JSON 이 아니면
    `TOPIC_FILE_INVALID`, 칸의 값이 틀리면 `CONTENT_INVALID`(어느 칸이 왜 안 되는지). 틀린 파일을 고쳐 읽거나 덮어쓰지 않는다.
  · 만들기(`init_files`): 없는 파일만 만든다 — 채널 프로필은 기본 다섯 개, 씨앗과 캘린더는 빈 틀. **이미 있는 파일은 읽을 수 없는 것이어도 덮어쓰지 않는다** — 단 0바이트 파일은 만들다 멈춘 흔적이라
    잃을 내용이 없으므로 '아직 없음' 으로 보고 기본 틀로 채운다(D-78).
실제 씨앗·고친 프로필·고친 캘린더는 이 PC 에만 있고 저장소에는 올라가지 않는다(저장소에는 모양과 시험용 예시뿐).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from ..errors import AppError
from ..topicdb.backup import check_json_bytes
from ..topics import layout
from ..topics.channels import default_profiles, profiles_to_dict
from ..topics.schedule import entries_to_dict
from ..topics.seeds import seeds_to_dict
from .context import write_json

TOPIC_DIR_NAME = "topic_engine"
MAX_FILE_BYTES = 8 * 1024 * 1024
STATE_MISSING, STATE_OK = "missing", "ok"
DEFAULT_VALUES = {layout.CHANNEL_PROFILES_FILE: default_profiles, layout.SEEDS_FILE: tuple, layout.CALENDAR_FILE: tuple}      # 파일이 없을 때 읽히는 값(채널 프로필 다섯 개 / 빈 씨앗 / 빈 캘린더)
DEFAULTS = {layout.CHANNEL_PROFILES_FILE: lambda: profiles_to_dict(default_profiles()), layout.SEEDS_FILE: lambda: seeds_to_dict(()), layout.CALENDAR_FILE: lambda: entries_to_dict(())}


class TopicPaths(NamedTuple):
    folder: Path
    database: Path
    profiles: Path
    seeds: Path
    calendar: Path

    def json_files(self):
        return ((layout.CHANNEL_PROFILES_FILE, self.profiles), (layout.SEEDS_FILE, self.seeds), (layout.CALENDAR_FILE, self.calendar))


class Loaded(NamedTuple):
    value: object                    # 채널 프로필 다섯 개 / 씨앗들 / 캘린더 항목들(파일이 없으면 기본값 또는 빈 목록)
    state: str                       # 'missing'(파일 없음 — 기본값) · 'ok'(파일을 읽음)


def topic_paths(workspace):
    """주제 엔진 파일들의 자리 — 사용자 데이터 폴더 아래 `topic_engine\\`(이름은 `topics/layout.py` 의 상수)."""
    folder = Path(workspace.root) / TOPIC_DIR_NAME
    return TopicPaths(folder, folder / layout.ENGINE_DB_FILE, folder / layout.CHANNEL_PROFILES_FILE, folder / layout.SEEDS_FILE, folder / layout.CALENDAR_FILE)


def _read_bytes(path):
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail=f"파일이 너무 크다(최대 {MAX_FILE_BYTES // (1024 * 1024)}MB)")
        return path.read_bytes()
    except OSError as error:
        raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail=f"읽을 수 없다: {type(error).__name__}") from None


def load_json_set(name, path):
    """설정 파일 하나를 엄격하게 읽는다 → `Loaded`. 없으면 기본값(파일은 만들지 않는다), 틀리면 AppError(`TOPIC_FILE_INVALID`·`CONTENT_INVALID`)."""
    path = Path(path)
    if not path.is_file():
        if path.exists():
            raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail="파일이 아니라 폴더 같은 것이다")
        return Loaded(_default_value(name), STATE_MISSING)
    return Loaded(check_json_bytes(name, _read_bytes(path)), STATE_OK)


def _default_value(name):
    return DEFAULT_VALUES[name]()


def load_profiles(paths):
    return load_json_set(layout.CHANNEL_PROFILES_FILE, paths.profiles)


def load_seeds(paths):
    return load_json_set(layout.SEEDS_FILE, paths.seeds)


def load_calendar(paths):
    return load_json_set(layout.CALENDAR_FILE, paths.calendar)


MAX_COPY_NAMES = 20                                          # 옛 판 사본 이름(.v1.bak → .v1.2.bak …)을 이만큼까지 찾아본다


def _same_json(path, data):
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8-sig")) == data
    except (OSError, ValueError, RecursionError):
        return False


def _keep_old_copy(path):
    """`seeds.json` 이 판 1 모양이면 판 2 로 올려 쓰기 전에 옛 모양 그대로의 사본(`seeds.json.v1.bak`)을 남긴다 → 사본의 파일 이름(남길 것이 없으면 None). 이미 있는 사본은 덮어쓰지 않는다 —
    같은 내용이면 그것을 쓰고 다르면 다음 이름(`.v1.2.bak` …)으로 새로 만든다. 읽을 수 없는 파일은 여기서 만들지 않고 부른 쪽이 먼저 막았다."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        old = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail="사본을 남기려고 읽었지만 읽을 수 없다") from None
    if not isinstance(old, dict) or old.get("schema") != 1:
        return None
    for number in range(1, MAX_COPY_NAMES + 1):
        target = path.with_name(f"{path.name}.v1.bak" if number == 1 else f"{path.name}.v1.{number}.bak")
        if not target.exists():
            write_json(target, old)
            return target.name
        if _same_json(target, old):
            return target.name
    raise AppError("TOPIC_FILE_INVALID", {"파일": path.name}, detail=f"옛 판 사본 이름 {MAX_COPY_NAMES}개가 모두 쓰이고 있다")


def save_seeds(paths, seeds):
    """씨앗 목록을 `seeds.json`(판 2)에 쓴다 — 쓰기는 `write_json`(임시 파일 → 디스크 → 이름 바꾸기)뿐이다. 옛 판 1 파일을 올려 쓰면 먼저 옛 모양 사본을 남기고 그 파일 이름을 돌려준다(아니면 None).
    모양은 `seeds_to_dict` 가 먼저 검사한다(같은 번호·같은 낱말 두 번 등 — 틀리면 아무것도 쓰지 않는다)."""
    payload = seeds_to_dict(seeds)
    kept = _keep_old_copy(paths.seeds)
    write_json(paths.seeds, payload)
    return kept


def is_blank_file(path):
    """0바이트 파일인가(만들다 멈춘 흔적 — 잃을 내용이 없다). 폴더·없는 파일·읽을 수 없는 파일은 아니다."""
    try:
        return Path(path).is_file() and Path(path).stat().st_size == 0
    except OSError:
        return False


def missing_files(paths):
    """아직 없는 설정 파일 이름들(만들기 전 미리 보기용 — 아무것도 만들지 않는다). 0바이트 파일도 '아직 없음' 이다(D-78)."""
    return tuple(name for name, path in paths.json_files() if not path.exists() or is_blank_file(path))


def init_files(paths):
    """없는(또는 0바이트인) 설정 파일을 기본 틀로 만든다 → (만든 이름들, 이미 있어서 그대로 둔 이름들). 내용이 있는 파일은 읽을 수 없는 것이어도 건드리지 않는다. 쓰기는 `write_json`(임시 파일 → 디스크 → 이름 바꾸기)뿐이다."""
    made, kept = [], []
    for name, path in paths.json_files():
        if path.exists() and not is_blank_file(path):
            kept.append(name)
            continue
        write_json(path, DEFAULTS[name]())
        made.append(name)
    return tuple(made), tuple(kept)
