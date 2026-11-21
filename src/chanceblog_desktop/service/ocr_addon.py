"""글자 읽기 추가 도구 폴더를 **읽기만 해서** 설치 여부·버전·파일 해시를 확인한다(결정 D-512, 설계서 3-2·3-9·5-1) — 쓰기 0, 네트워크 0, 하위 프로세스 0.
추가 도구는 앱 본체와 따로 압축을 풀어 두는 선택 기능이고, 폴더 이름은 본체 옆의 `ocr` 다. 폴더 안에는 빌드가 만든 정보 파일 `OCR_INFO.json`(파일 목록과 해시·크기)과 작업자 `ocr_worker.exe` 가 있다.

확인 순서(모두 읽기):
  1) 폴더나 정보 파일이 없으면 `absent`(설치 안 함 — 글자 읽기 단추를 보이지 않는다, 오류 아님).
  2) 정보 파일이 너무 크거나(2MB 넘음)·JSON 이 아니거나·모양이 다르거나(이름·약속 번호·파일 목록) 위험한 경로(절대 경로·`..`·드라이브)가 있으면 `invalid`.
  3) **앱에 박은** 모델·글자 사전 해시(`EMBEDDED_FILES`)와 정보 파일의 값이 같아야 한다 — 정보 파일과 모델을 함께 바꿔도 통과하지 못한다(신뢰의 뿌리는 앱 소스다).
  4) 목록의 모든 파일이 있고 크기·SHA-256 이 같아야 하고, 목록에 없는 파일이 있어도 `invalid`(작업자 폴더에 낯선 파일이 섞이지 않게 — `thumbs.db`·`desktop.ini` 만 봐준다).
결과(`AddonStatus`)에는 상태 이름·버전 글·문제 개수·문제 종류 이름뿐이고 경로·파일 이름은 없다(화면의 정보 카드는 고정 문장만 보인다).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass

INFO_NAME = "OCR_INFO.json"
WORKER_NAME = "ocr_worker.exe"
FOLDER_NAME = "ocr"                      # 본체 옆의 추가 도구 폴더 이름
MAX_INFO_BYTES = 2 * 1024 * 1024
MAX_FILES = 2000
PROTO = 1
ABSENT, OK, INVALID = "absent", "ok", "invalid"
EMBEDDED_FILES = {"models/det/inference.onnx": (4826518, "a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d"),
                  "models/rec/inference.onnx": (13418787, "92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08"),
                  "data/ppocrv5_korean_dict.txt": (47451, "a88071c68c01707489baa79ebe0405b7beb5cca229f4fc94cc3ef992328802d7")}     # 앱에 박은 모델 2개·글자 사전의 크기와 SHA-256
IGNORED_EXTRA = frozenset({"thumbs.db", "desktop.ini"})
_HEX = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1 << 20


@dataclass(frozen=True)
class AddonStatus:
    state: str                  # absent · ok · invalid
    version: str = ""           # 예: `rapidocr 3.10.0 · onnxruntime 1.31.1`(정보 파일의 패키지 목록에서) — ok 일 때만
    problems: tuple = ()        # 문제 종류 이름들(`info`·`unsafe_path`·`model_hash`·`missing`·`size`·`hash`·`extra`·`worker`) — 경로·파일 이름은 없다

    @property
    def ok(self):
        return self.state == OK


def addon_folder(app_dir):
    """본체 옆 추가 도구 폴더 위치(만들지 않는다)."""
    return os.path.join(app_dir, FOLDER_NAME)


def worker_command(folder):
    """작업자를 띄우는 명령(인자 고정 — 추가 도구 폴더의 `ocr_worker.exe` 하나)."""
    return [os.path.join(folder, WORKER_NAME)]


def _open_read(path):
    """추가 도구 폴더의 파일을 **읽기 전용(`rb`)으로 여는 유일한 곳** — 이 서비스는 어떤 파일도 쓰지 않는다. `tests/test_service_safety.py` 의 `READ_OPENS` 가 이 함수 하나만 허용하고 열기 모드가 글자 `rb` 인지 소스에서 확인한다."""
    return open(path, "rb")


def _sha256(path):
    digest = hashlib.sha256()
    with _open_read(path) as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(path):
    if not isinstance(path, str) or not path or "\\" in path or path.startswith("/") or ":" in path or "\x00" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def _version(info):
    wanted = {}
    for package in info.get("packages", ()):
        if isinstance(package, dict) and package.get("name") in ("rapidocr", "onnxruntime") and isinstance(package.get("version"), str):
            wanted[package["name"]] = package["version"][:30]
    return " · ".join(f"{name} {wanted[name]}" for name in ("rapidocr", "onnxruntime") if name in wanted)


def read_info(folder):
    """정보 파일을 읽는다 -> dict 또는 None(없음). 너무 크거나 JSON 이 아니거나 객체가 아니면 `ValueError`."""
    path = os.path.join(folder, INFO_NAME)
    if not os.path.isfile(path):
        return None
    if os.path.getsize(path) > MAX_INFO_BYTES:
        raise ValueError("info too big")
    with _open_read(path) as handle:
        info = json.loads(handle.read().decode("utf-8"))
    if not isinstance(info, dict):
        raise ValueError("info shape")
    return info


def verify(folder, *, check_files=True):
    """추가 도구 폴더를 확인한다 -> `AddonStatus`. `check_files` 가 거짓이면 파일 목록·크기만 보고 해시는 건너뛴다(빠른 확인 — 띄우기 전에는 늘 해시까지 본다)."""
    if not isinstance(folder, str) or not os.path.isdir(folder):
        return AddonStatus(ABSENT)
    try:
        info = read_info(folder)
    except (OSError, ValueError, UnicodeDecodeError):
        return AddonStatus(INVALID, problems=("info",))
    if info is None:
        return AddonStatus(ABSENT)
    problems = []
    files = info.get("files")
    if info.get("name") != "ocr_addon" or info.get("proto") != PROTO or not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        return AddonStatus(INVALID, problems=("info",))
    listed = {}
    for entry in files:
        if not isinstance(entry, dict) or not _safe_relative(entry.get("path")) or type(entry.get("bytes")) is not int or entry["bytes"] < 0 or not _HEX.fullmatch(str(entry.get("sha256", ""))):
            return AddonStatus(INVALID, problems=("unsafe_path" if isinstance(entry, dict) and not _safe_relative(entry.get("path")) else "info",))
        if entry["path"] in listed:
            return AddonStatus(INVALID, problems=("info",))
        listed[entry["path"]] = (entry["bytes"], entry["sha256"])
    models = info.get("models_dict")
    for name, (size, digest) in EMBEDDED_FILES.items():
        stated = models.get(name) if isinstance(models, dict) else None
        if not isinstance(stated, dict) or stated.get("bytes") != size or stated.get("sha256") != digest or listed.get(name) != (size, digest):
            problems.append("model_hash")
            break
    if WORKER_NAME not in listed:
        problems.append("worker")
    for relative, (size, digest) in sorted(listed.items()):
        path = os.path.join(folder, *relative.split("/"))
        try:
            if not os.path.isfile(path) or os.path.islink(path):
                problems.append("missing")
                continue
            if os.path.getsize(path) != size:
                problems.append("size")
            elif check_files and _sha256(path) != digest:
                problems.append("hash")
        except OSError:
            problems.append("missing")
    for root, _dirs, names in os.walk(folder):
        for name in names:
            relative = os.path.relpath(os.path.join(root, name), folder).replace(os.sep, "/")
            if relative != INFO_NAME and relative not in listed and name.lower() not in IGNORED_EXTRA:
                problems.append("extra")
    if problems:
        return AddonStatus(INVALID, problems=tuple(sorted(set(problems))))
    return AddonStatus(OK, _version(info))


def verify_problem(folder):
    """어댑터가 띄우기 전에 부르는 확인 — 문제가 없으면 None, 있으면 문제 종류 글(글·경로 없음)."""
    status = verify(folder, check_files=True)
    return None if status.ok else (",".join(status.problems) or status.state)


__all__ = ["AddonStatus", "addon_folder", "read_info", "verify", "verify_problem", "worker_command"]       # 상수(ABSENT·OK·INVALID·EMBEDDED_FILES …)는 모듈 이름으로 쓴다 — 서비스 안전 시험이 대문자 글자 상수를 오류 코드나 허용 이름만 받기 때문이다
