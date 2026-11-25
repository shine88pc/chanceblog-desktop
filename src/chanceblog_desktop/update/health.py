"""새 판 첫 시작의 점검과 '정상' 표식, 정상이 된 뒤의 정리(UPDATE 설계서 3-5).

점검의 내용(`startup_checks`): 지금 버전이 `pending.to` 와 같고, 데이터 폴더에 닿을 수 있고, 글 보관함이 열리고 구조가 맞다(주입한 점검 함수들 — 화면 쪽이 기존 이관 경로로 채운다). 하나라도 실패하면 **정상 표식을 쓰지 않는다**
(다음 시작이 횟수를 센다). `HealthMonitor` 는 창이 뜬 뒤 처리 못 한 예외 없이 15초가 지나면 정상으로 본다(시계는 주입한다). 정상이면 `mark_healthy` 가 `pending` 을 지우고 정상 판을 기록한다.
정리: 정상이 된 뒤 임시 내려받기 폴더(`staging/`)를 치우고 복구용 보관(`keep/<버전>/` — 정상 확인된 판의 검증된 설치 파일, 최대 둘)을 다듬는다. 이 모듈은 접속·하위 프로세스가 없다.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from . import state as state_module
from . import versions

STAGING = "staging"
KEEP = "keep"
MAX_KEEP = 2
PROBE_NAMES = ("data_folder", "store")
WAITING = "waiting"
HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
_KEEP_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,40}", re.ASCII)
REPARSE_POINT = 0x400                              # 윈도 FILE_ATTRIBUTE_REPARSE_POINT — 심볼릭 링크·정션(junction)이 가진다


def _is_link(path):
    """링크(심볼릭 링크·윈도 정션)인가 — 링크는 따라가지도 지우지도 않는다."""
    path = Path(path)
    try:
        return path.is_symlink() or bool(getattr(os.lstat(path), "st_file_attributes", 0) & REPARSE_POINT)
    except OSError:
        return True


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    failed: tuple                                  # 실패한 점검 이름들(고정 낱말)


def startup_checks(pending, *, current_version, probes):
    """새 판의 첫 시작 점검. `probes` 는 {이름: 함수(참·거짓)} — `PROBE_NAMES` 가 모두 있어야 하고 하나라도 거짓이거나 예외를 내거나 없으면 실패다."""
    failed = []
    try:
        same = pending is not None and versions.compare(current_version, pending.to_version) == 0
    except ValueError:
        same = False
    if not same:
        failed.append("version")
    for name in PROBE_NAMES:
        probe = (probes or {}).get(name)
        try:
            good = probe is not None and probe() is True
        except Exception:          # noqa: BLE001 - 점검이 터지면 그 점검은 실패다(정상 표식을 쓰지 않는다)
            good = False
        if not good:
            failed.append(name)
    return HealthResult(not failed, tuple(failed))


class HealthMonitor:
    """창이 뜬 뒤 `seconds` 동안 처리 못 한 예외가 없으면 정상. `clock()` 은 단조 시계(초)를 낸다. 정상·비정상이 정해지면 더는 바뀌지 않는다."""

    def __init__(self, clock, seconds=state_module.HEALTHY_AFTER_SECONDS):
        self._clock = clock
        self._seconds = seconds
        self._visible_at = None
        self._exceptions = 0
        self._verdict = None

    def report_window_visible(self):
        if self._visible_at is None and self._verdict is None:
            self._visible_at = self._clock()

    def report_exception(self):
        if self._verdict is None:
            self._exceptions += 1
            self._verdict = UNHEALTHY

    def poll(self):
        if self._verdict is not None:
            return self._verdict
        if self._visible_at is not None and self._clock() - self._visible_at >= self._seconds:
            self._verdict = HEALTHY
            return HEALTHY
        return WAITING


def mark_healthy(folder, state=None):
    """정상 표식 — `pending` 을 지우고 정상 판을 기록하고 안내를 비운다 → 새 `State`. `pending` 이 없으면 그대로(이미 정상)."""
    current = state if state is not None else state_module.load_state(folder)
    if current.pending is None:
        return current
    done = replace(current, pending=None, last_good=current.pending.to_version, notice="")
    state_module.write_state(folder, done)
    return done


def staging_root(folder):
    return Path(folder) / STAGING


def keep_root(folder):
    return Path(folder) / KEEP


def keep_dir(folder, version):
    """그 판의 복구용 보관 폴더(이름이 안전한 버전 글일 때만 — 아니면 ValueError)."""
    if versions.parse_version(version) is None or _KEEP_NAME.fullmatch(version) is None:
        raise ValueError("보관 폴더 이름이 안전하지 않다")
    return keep_root(folder) / version


def promote_to_keep(source, folder, version):
    """정상이 된 판의 검증된 설치 파일 폴더(`source`)를 `keep/<버전>/` 으로 옮긴다(이미 있으면 먼저 지운다). 옮겼으면 그 폴더."""
    target = keep_dir(folder, version)
    source = Path(source)
    if not source.is_dir() or _is_link(source):
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(source), str(target))
    return target


def prune_keep(folder, keep_versions=(), *, limit=MAX_KEEP):
    """보관 폴더를 정리한다 — `keep_versions`(지금 판·바로 전 판)는 남기고, 그 밖에는 가장 높은 판부터 `limit` 개까지만 남긴다. 지운 폴더 이름들."""
    root = keep_root(folder)
    if not root.is_dir() or _is_link(root):
        return ()
    found = []
    for entry in root.iterdir():
        if entry.is_dir() and not _is_link(entry) and versions.parse_version(entry.name) is not None:
            found.append(entry)
    found.sort(key=lambda item: versions.parse_version(item.name).key(), reverse=True)
    protected = {name for name in keep_versions if isinstance(name, str)}
    kept = [item for item in found if item.name in protected]
    for item in found:
        if item.name not in protected and len(kept) < limit:
            kept.append(item)
    removed = []
    for item in found:
        if item not in kept:
            shutil.rmtree(item, ignore_errors=True)
            removed.append(item.name)
    return tuple(sorted(removed))


def clear_staging(folder):
    """임시 내려받기 폴더를 모두 치운다(정상이 된 뒤·낡은 내려받기 정리). 치운 폴더 수."""
    root = staging_root(folder)
    if not root.is_dir() or _is_link(root):
        return 0
    count = 0
    for entry in list(root.iterdir()):
        if _is_link(entry):
            continue                                   # 링크는 따라가지도 지우지도 않는다(목적지를 건드리지 않는다)
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
        count += 1
    return count


__all__ = ["HEALTHY", "HealthMonitor", "HealthResult", "KEEP", "MAX_KEEP", "PROBE_NAMES", "STAGING", "UNHEALTHY", "WAITING", "clear_staging", "keep_dir", "keep_root", "mark_healthy", "promote_to_keep",
           "prune_keep", "staging_root", "startup_checks"]
