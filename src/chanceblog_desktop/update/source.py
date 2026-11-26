"""받을 주소 만들기와 내려받기(UPDATE 설계서 3-4) — **접속은 `net/` 틀을 지난다**. 이 파일은 `http`·`ssl`·소켓·하위 프로세스를 가져오지 않고, 접속 틀(`NetClient`)은 호출하는 쪽이 넘긴 개체로만 쓴다(주소를 이 파일이 만들 뿐이다).

주소는 앱이 상수로 만든다 — 호스트·저장소는 `net/endpoints.py` 의 표 상수이고 태그·이름은 매니페스트의 검사를 통과한 값뿐이라 **매니페스트가 임의 주소를 가리키는 길이 없다**(응답에서 읽은 주소·경로를 요청에 쓰지 않는다 — 이동 안내의 주소도 접속 틀이 표와 견준다).
처음 읽는 것: 최신 릴리스의 `update-manifest.json` 과 `.sig`. 파일은 `releases/download/<태그>/<이름>` 으로 받는다(최신 포인터가 아니라 서명된 매니페스트가 말하는 그 판).
받는 것은 크기·해시를 서명된 매니페스트와 정확히 맞춰 본다: 임시 폴더(`update/staging/<무작위>/`)에 `<이름>.part` 로 쓰고(응답이 정한 이름·경로는 쓰지 않는다) 크기와 SHA-256 이 같을 때만 이름을 바꾸며, 하나라도 틀리면 폴더째 지운다.
디스크 여유는 받기 전에 본다(파일 합계 × 3 + 백업 예상 크기). 이어받기는 없다(처음부터). 이 파일은 데이터 폴더 밖에 쓰지 않는다.
폴더에서 업데이트(설계서 3-11, 접속 없음): 사용자가 고른 폴더에서 같은 두 파일과 필요한 파일을 읽어(`read_folder_manifest`·`stage_from_folder`) 같은 임시 폴더에 **복사하며 해시**한다 — 고른 폴더는 읽기만 하고 아무것도 쓰거나 옮기지 않으며,
링크·정션·폴더·보통 파일이 아닌 것은 따라가지 않고 거절하고, 크기·SHA-256 이 서명된 값과 다르면 폴더째 지운다. 오류의 이유 이름표에는 폴더 경로·파일 이름을 담지 않는다.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from ..errors import AppError
from ..net import endpoints
from . import health
from . import manifest as manifest_module

USE = "update_check"
SIGNATURE_LIMIT = 4096                                  # 서명 파일은 89바이트다 — 넉넉한 읽기 상한
TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[1-9][0-9]*)?", re.ASCII)
MANIFEST_COPY = manifest_module.MANIFEST_NAME           # 검증된 매니페스트·서명의 사본 이름(받은 폴더에 함께 둔다 — 복구 때 같은 검사를 다시 한다)
SIGNATURE_COPY = manifest_module.SIGNATURE_NAME
DISK_MULTIPLIER = 3
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class StagedUpdate:
    """내려받아 크기·해시를 확인한 파일들 — `files` 는 역할(`setup`·`package`·`feed`·`portable`) → 경로."""
    folder: Path
    files: dict
    manifest: object


def _url(path):
    return endpoints.url_for(USE, "GET", path)


def latest_url(name):
    """최신 릴리스의 매니페스트·서명 파일 주소(`name` 은 두 이름 중 하나)."""
    if name not in (manifest_module.MANIFEST_NAME, manifest_module.SIGNATURE_NAME):
        raise ValueError("최신 릴리스에서 받을 수 있는 파일이 아니다")
    return _url(f"{endpoints.RELEASE_BASE}/latest/download/{name}")


def asset_url(tag, name):
    """태그가 정해진 릴리스의 자산 주소 — 태그와 이름은 규칙을 지킨 값만(그 밖은 ValueError, 접속 전에 거절된다)."""
    if not isinstance(tag, str) or TAG_PATTERN.fullmatch(tag) is None or not manifest_module.valid_file_name(name):
        raise ValueError("태그나 파일 이름이 규칙에 맞지 않는다")
    return _url(f"{endpoints.RELEASE_BASE}/download/{tag}/{name}")


def _get(client, url, limit):
    response = client.request(USE, "GET", url, limit=limit)
    response.raise_for_status()
    return response.body


def fetch_manifest(client, *, tag=""):
    """서명된 매니페스트와 서명 파일의 바이트 → `(매니페스트, 서명)`. `tag` 가 없으면 최신 릴리스, 있으면 그 태그의 릴리스(복구 모드에서 이전 판의 것을 다시 받을 때)."""
    if tag:
        manifest_url, signature_url = asset_url(tag, manifest_module.MANIFEST_NAME), asset_url(tag, manifest_module.SIGNATURE_NAME)
    else:
        manifest_url, signature_url = latest_url(manifest_module.MANIFEST_NAME), latest_url(manifest_module.SIGNATURE_NAME)
    return _get(client, manifest_url, manifest_module.MAX_MANIFEST_BYTES), _get(client, signature_url, SIGNATURE_LIMIT)


def _sha256_of(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_disk(folder, sizes, backup_estimate, free_bytes):
    """받기 전 디스크 여유 점검 — 모자라면 `DISK_FULL`(아무것도 받지 않았다). `free_bytes(폴더)` 는 시험이 바꿔 끼운다."""
    needed = sum(sizes) * DISK_MULTIPLIER + max(0, int(backup_estimate))
    if free_bytes(folder) < needed:
        raise AppError("DISK_FULL", {"경로": "업데이트를 받아 둘 곳"}, detail=f"need:{needed}")
    return needed


def default_free_bytes(folder):
    probe = Path(folder)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _new_run_folder(update_folder):
    root = health.staging_root(update_folder)
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        run = root / secrets.token_hex(8)
        try:
            run.mkdir()
            return run
        except FileExistsError:
            continue
    raise AppError("FILE_WRITE_FAILED", {"경로": "업데이트를 받아 둘 곳"}, detail="staging:name")


def _discard(run):
    shutil.rmtree(run, ignore_errors=True)


def download_files(client, manifest, manifest_bytes, signature_bytes, update_folder, *, backup_estimate=0, free_bytes=default_free_bytes, progress=None, roles=None):
    """매니페스트가 말한 파일(`roles` 로 좁힐 수 있다)을 받아 크기·해시를 확인한다 → `StagedUpdate`. 틀리면 폴더째 지우고 `UPDATE_SIGNATURE_INVALID`, 끊김·시간·크기 초과는 접속 틀의 오류가 그대로 나가고(호출하는 쪽이 바꾼다) 폴더는 지운다.
    검증된 매니페스트와 서명의 사본을 같은 폴더에 둔다(나중에 복구 보관에 함께 옮겨져 같은 검사를 다시 할 수 있게)."""
    chosen = [entry for entry in manifest.files if roles is None or entry.role in roles]
    if not chosen:
        raise AppError("UPDATE_MANIFEST_INVALID", detail="manifest:no_files")
    check_disk(update_folder, [entry.size for entry in chosen], backup_estimate, free_bytes)
    run = _new_run_folder(update_folder)
    saved = {}
    try:
        (run / MANIFEST_COPY).write_bytes(manifest_bytes)
        (run / SIGNATURE_COPY).write_bytes(signature_bytes)
        total = len(chosen)
        for index, entry in enumerate(chosen):
            if progress is not None:
                progress(index / total, f"{index + 1}/{total}")
            part = run / (entry.name + ".part")
            final = run / entry.name
            if part.parent != run or final.parent != run or part.exists() or final.exists():
                raise AppError("UPDATE_SIGNATURE_INVALID", detail="staging:name")
            response = client.request_to_file(USE, "GET", asset_url(manifest.tag, entry.name), part, max_bytes=entry.size)
            response.raise_for_status()
            if response.file_size != entry.size or response.file_sha256 != entry.sha256:
                raise AppError("UPDATE_SIGNATURE_INVALID", detail=f"download:{entry.role}:mismatch")
            os.replace(part, final)
            saved[entry.role] = final
        if progress is not None:
            progress(1.0, f"{total}/{total}")
    except BaseException:
        _discard(run)
        raise
    return StagedUpdate(run, saved, manifest)


def _regular_size(path):
    """링크·정션이 아닌 보통 파일이면 그 크기, 아니면 None — 링크는 따라가지 않고 그 자리 자체를 본다(읽을 수 없어도 None)."""
    try:
        if health._is_link(path):
            return None
        info = os.lstat(path)
    except OSError:
        return None
    return info.st_size if stat.S_ISREG(info.st_mode) else None


def read_folder_manifest(folder):
    """사용자가 고른 폴더의 `update-manifest.json` 과 `.sig` 의 바이트 → `(매니페스트, 서명)`. 폴더와 두 파일은 링크가 아닌 것이어야 하고 크기는 상한 이하다 — 아니면
    `UPDATE_MANIFEST_INVALID`(이유는 고정 낱말, 경로 없음). 읽기만 한다."""
    folder = Path(folder)
    if health._is_link(folder) or not folder.is_dir():
        raise AppError("UPDATE_MANIFEST_INVALID", detail="folder:not_a_folder")
    found = []
    for name, label, limit in ((MANIFEST_COPY, "manifest", manifest_module.MAX_MANIFEST_BYTES), (SIGNATURE_COPY, "signature", SIGNATURE_LIMIT)):
        path = folder / name
        size = _regular_size(path)
        if size is None:
            raise AppError("UPDATE_MANIFEST_INVALID", detail=f"folder:{label}_missing")
        if size > limit:
            raise AppError("UPDATE_MANIFEST_INVALID", detail=f"folder:{label}_too_large")
        try:
            with path.open("rb") as handle:
                data = handle.read(limit + 1)
        except OSError:
            raise AppError("UPDATE_MANIFEST_INVALID", detail=f"folder:{label}_unreadable") from None
        if len(data) > limit:
            raise AppError("UPDATE_MANIFEST_INVALID", detail=f"folder:{label}_too_large")
        found.append(data)
    return found[0], found[1]


def stage_from_folder(folder, manifest, manifest_bytes, signature_bytes, update_folder, *, backup_estimate=0, free_bytes=default_free_bytes, progress=None, roles=None):
    """고른 폴더의 파일(`roles` 로 좁힐 수 있다)을 임시 폴더에 복사하며 해시해 크기·SHA-256 을 서명된 매니페스트와 정확히 맞춘다 → `StagedUpdate`(온라인 받기와 같은 모양).
    파일이 없거나 보통 파일이 아니면 `UPDATE_MANIFEST_INVALID`, 크기·해시가 다르면 `UPDATE_SIGNATURE_INVALID`(디스크를 쓰기 전에 크기부터 본다), 디스크가 모자라면 `DISK_FULL`. 틀리면 폴더째 지운다."""
    folder = Path(folder)
    chosen = [entry for entry in manifest.files if roles is None or entry.role in roles]
    if not chosen:
        raise AppError("UPDATE_MANIFEST_INVALID", detail="manifest:no_files")
    if health._is_link(folder) or not folder.is_dir():
        raise AppError("UPDATE_MANIFEST_INVALID", detail="folder:not_a_folder")
    for entry in chosen:
        size = _regular_size(folder / entry.name)
        if size is None:
            raise AppError("UPDATE_MANIFEST_INVALID", detail=f"folder:file_missing:{entry.role}")
        if size != entry.size:
            raise AppError("UPDATE_SIGNATURE_INVALID", detail=f"folder:{entry.role}:size")
    check_disk(update_folder, [entry.size for entry in chosen], backup_estimate, free_bytes)
    run = _new_run_folder(update_folder)
    saved = {}
    try:
        (run / MANIFEST_COPY).write_bytes(manifest_bytes)
        (run / SIGNATURE_COPY).write_bytes(signature_bytes)
        total = len(chosen)
        for index, entry in enumerate(chosen):
            if progress is not None:
                progress(index / total, f"{index + 1}/{total}")
            part = run / (entry.name + ".part")
            final = run / entry.name
            if part.parent != run or final.parent != run or part.exists() or final.exists():
                raise AppError("UPDATE_SIGNATURE_INVALID", detail="staging:name")
            digest = hashlib.sha256()
            copied = 0
            try:
                with (folder / entry.name).open("rb") as reader, part.open("xb") as writer:
                    while True:
                        chunk = reader.read(CHUNK)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > entry.size:
                            break                                   # 읽는 사이 늘어난 파일 — 서명된 크기를 넘으면 더 읽지 않는다
                        digest.update(chunk)
                        writer.write(chunk)
            except OSError:
                raise AppError("UPDATE_MANIFEST_INVALID", detail=f"folder:read:{entry.role}") from None
            if copied != entry.size or digest.hexdigest() != entry.sha256:
                raise AppError("UPDATE_SIGNATURE_INVALID", detail=f"folder:{entry.role}:mismatch")
            os.replace(part, final)
            saved[entry.role] = final
        if progress is not None:
            progress(1.0, f"{total}/{total}")
    except BaseException:
        _discard(run)
        raise
    return StagedUpdate(run, saved, manifest)


def find_staged_run(update_folder, version):
    """받아 둔 임시 폴더 가운데 **그 버전의 검증된 매니페스트 사본**이 든 것(정상이 된 뒤 복구용 보관으로 옮길 폴더) — 없으면 None. 사본은 서명을 다시 확인하지 않고 모양과 버전만 본다(옮긴 뒤 쓸 때 다시 확인한다)."""
    root = health.staging_root(update_folder)
    try:
        if not root.is_dir() or health._is_link(root):
            return None
        for run in sorted(root.iterdir()):
            copy = run / MANIFEST_COPY
            if run.is_dir() and not health._is_link(run) and copy.is_file():
                try:
                    found = manifest_module.read_structure(copy.read_bytes())
                except (AppError, OSError):
                    continue
                if found.get("version") == version:
                    return run
    except OSError:
        return None
    return None


def verify_staged(staged):
    """적용 직전의 재확인 — 파일마다 크기와 SHA-256 을 디스크에서 다시 읽어 서명된 매니페스트의 값과 견준다(검증 뒤 파일이 바뀌었는지, 설계서 U3·U4). 하나라도 다르거나 없으면 `UPDATE_SIGNATURE_INVALID`."""
    for entry in staged.manifest.files:
        path = staged.files.get(entry.role)
        if path is None:
            continue
        try:
            same = Path(path).stat().st_size == entry.size and _sha256_of(path) == entry.sha256
        except OSError:
            same = False
        if not same:
            raise AppError("UPDATE_SIGNATURE_INVALID", detail=f"restage:{entry.role}")
    return True


__all__ = ["CHUNK", "DISK_MULTIPLIER", "MANIFEST_COPY", "SIGNATURE_COPY", "SIGNATURE_LIMIT", "StagedUpdate", "TAG_PATTERN", "USE", "asset_url", "check_disk", "default_free_bytes", "download_files",
           "fetch_manifest", "find_staged_run", "latest_url", "read_folder_manifest", "stage_from_folder", "verify_staged"]
