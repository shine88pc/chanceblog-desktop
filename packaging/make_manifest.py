"""Package 정보 파일 만들기 — `PACKAGE_INFO.md`·`PACKAGE_INFO.json`·`SHA256SUMS` (운영자 2026-11-11 결정 8항의 여덟 가지를 한곳에).

여덟 가지: Version · Git Commit · SHA-256 · Dependency 목록 · Build 방법 · Malware 검사 결과 · 서명 여부 · SmartScreen 예상 동작.
맨 위에 굵게 '개인 PC 제한 시험용, 미서명 Package — 공개 배포용이 아닙니다' 를 둔다.

정보 파일은 두 갈래다(같은 입력이면 같은 바이트가 나오는 빌드를 지키려고):
  · inner — 묶음 폴더 안에 들어가는 사본(`PACKAGE_INFO.json`·`.md`). 시계·압축 파일 해시·검사 결과를 담지 않는다(압축 파일을 만들기 전에 만들고, 자기 자신은 해시 목록에서 뺀다).
    묶음 안의 화면 '정보' 카드와 `--selftest` 가 이것을 읽는다.
  · outer — 압축 파일 옆에 두는 완전한 사본(+ `SHA256SUMS`). 압축 파일의 SHA-256·크기·악성코드 검사 결과·만든 시각·자가 점검 결과가 더해진다.

사용: python packaging/make_manifest.py inner --bundle 묶음폴더 [--repo 저장소]
      python packaging/make_manifest.py outer --bundle 묶음폴더 --zip 압축파일 --out 폴더 [--no-scan]
보통은 `build_package.py` 가 부른다. 표준 라이브러리만 쓰고, 시스템·보안 설정을 바꾸지 않는다(검사는 읽기 전용 옵션만).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import pkgcommon as pc

REPOSITORY = "shine88pc/chanceblog-desktop"
LOCK_RELATIVE = "packaging/requirements-package.txt"
INPUT_FOLDERS = ("src", "vendor", "packaging")                 # 묶음의 재료가 되는 폴더 — 출력 폴더를 이 안에 둘 수 없고, 이 안의 '무시되는 파일'도 깨끗하지 않은 것으로 본다(D-417)
INPUT_PATHS = INPUT_FOLDERS + ("VERSION",)
ROLES = ("runtime", "build")
HOW_TO_BUILD = (
    "Windows 10/11 64비트에서 Python 3.12(64비트)를 준비하고 가상환경을 저장소 밖에 만듭니다(저장소 안에 만들면 '깨끗한 작업 트리' 검사에 걸립니다).",
    "그 가상환경에 잠금 파일의 도구를 정확한 버전으로 설치합니다: python -m pip install -r packaging/requirements-package.txt",
    "깨끗하게 내려받은(커밋되지 않은 변경이 없고 src·vendor·packaging 안에 git 이 무시하는 파일도 없는) 이 저장소의 커밋으로 이동합니다 — 깨끗하지 않으면 빌드가 거절됩니다.",
    "저장소 맨 위 폴더에서 실행합니다: python packaging/build_package.py",
    "결과는 dist/package/release 폴더(압축 파일·SHA256SUMS·PACKAGE_INFO.md·PACKAGE_INFO.json)에 생깁니다. 자가 점검(--selftest)이 실패하면 아무것도 만들지 않습니다.",
)
SMARTSCREEN_TEXT = (
    "서명이 없는 프로그램이라 Windows 가 게시자를 '알 수 없음'으로 봅니다. 인터넷(브라우저·메신저 등)으로 받은 압축 파일을 풀어 처음 실행하면 "
    "파란색 'Windows의 PC 보호'(SmartScreen) 창이 뜰 수 있습니다. 그때 '추가 정보'를 누르면 아래에 '실행' 단추가 나타나고, 그것을 눌러야 시작됩니다"
    "(PC 를 지키는 창이라 처음 한 번 사람이 확인하라는 뜻이며 앱 오류가 아닙니다). 평판이 쌓인 서명된 프로그램이 아니므로 새 버전마다 다시 뜰 수 있습니다. "
    "'스마트 앱 컨트롤'(Smart App Control)이 켜져 있는 PC 에서는 서명 없는 프로그램의 실행 자체를 막을 수 있고, 이때는 '추가 정보→실행'이 나오지 않을 수 있습니다. "
    "이 묶음을 만든 PC 와 운영자 개인 PC 의 SmartScreen·스마트 앱 컨트롤 설정은 확인하지 못했습니다. 설정을 바꾸는 것은 이 묶음이 권하지 않으며, 막히면 막힌 사실만 보고해 주세요."
)
SIGNING_TEXT = (
    "미서명 — 실행 파일(ChanceBlogDesktop.exe)에 코드 서명(Authenticode)이 없습니다. 유료 인증서를 쓰지 않았고(D-05) 서명 서비스에도 가입하지 않았습니다. "
    "묶음 안의 Python·Microsoft 런타임 DLL 일부는 각 공급자가 서명한 것이며 이 앱의 서명이 아닙니다."
)
LIMITS = (
    "이 묶음을 만든 PC 와 운영자 개인 PC 의 SmartScreen·스마트 앱 컨트롤 상태는 확인하지 못했습니다.",
    "Qt(PySide6) 안에 들어 있는 제3자 구성 요소(libpng·FreeType·HarfBuzz·zlib 등)의 고지는 Qt 공식 문서를 따르며, 이 묶음의 LICENSES 폴더가 그 전문을 모두 담았다고 보장하지 않습니다(법률 판단이 아닙니다).",
    "의존성 잠금 파일은 정확한 버전을 못박았지만 배포 파일(wheel)의 해시는 담지 못했습니다(빌드 PC 의 네트워크 금지) — 대신 설치된 파일 내용의 지문(RECORD 해시 요약)을 기록했습니다.",
    "같은 커밋·같은 잠금 파일의 도구·같은 Python 이고 묶음에 들어가는 DLL 이 같은 곳(가상환경·기본 Python·Windows 폴더)에서 오면 같은 압축 파일이 나오도록 만들었습니다 — 그 밖의 폴더(빌드 PC 의 PATH 에 있는 다른 프로그램 등)에서 온 DLL 이 있으면 빌드가 거절합니다. 다른 PC 에서 같은 해시가 나오는지는 시험하지 못했습니다(Windows 시스템 DLL 의 버전·zlib·Python 패치 버전이 다르면 달라질 수 있습니다).",
    "공개 배포용이 아닙니다. 앱 자체의 라이선스는 아직 정해지지 않았습니다(D-13).",
)
_REQ_LINE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[0-9A-Za-z.+!_-]+)(?P<hashes>(?:\s+--hash=sha256:[0-9a-f]{64})*)\s*$")
_ROLE_LINE = re.compile(r"^#\s*\[(?P<role>[a-z]+)\]")
_RECORD_SKIP_SUFFIXES = (".pyc",)
_RECORD_SKIP_NAMES = ("RECORD", "INSTALLER", "REQUESTED", "direct_url.json")
DEFENDER_ARGS = ("-Scan", "-ScanType", "3", "-File")                          # 사용자 지정 검사(파일·폴더 하나) — 보안 설정을 바꾸는 옵션은 쓰지 않는다
DEFENDER_READONLY = "-DisableRemediation"                                     # 치료·격리·삭제를 끈다(읽기 전용 검사)


class BuildRefused(Exception):
    """빌드를 계속할 수 없는 이유 — 깨끗하지 않은 작업 트리·잠금 파일과 다른 설치·빠진 라이선스 등. 메시지는 쉬운 한국어."""


# ---- git ----------------------------------------------------------------

def git_output(repo, *args, runner=subprocess.run):
    try:
        result = runner(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        raise BuildRefused(f"git 을 실행하지 못했어요({type(error).__name__}).") from None
    if result.returncode != 0:
        raise BuildRefused("git 이 실패했어요 — 이 폴더가 git 저장소가 맞는지 확인해 주세요.")
    return result.stdout


def ignored_inputs(repo, *, runner=subprocess.run):
    """빌드 입력(`src`·`vendor`·`packaging`·`VERSION`) 안의 '무시되는' 파일 — `.gitignore` 가 가려서 `git status` 에 안 보이지만 묶음으로 복사될 수 있는 것(D-417).
    바이트코드 캐시(`__pycache__`·`.pyc`)는 묶음에 들어가지 않으므로 뺀다."""
    found = git_output(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", *INPUT_PATHS, runner=runner)
    names = [name for name in found.split(chr(0)) if name]
    return sorted(name for name in names if "__pycache__" not in name.split("/") and not name.endswith(".pyc"))


def git_hidden_changes(repo, *, runner=subprocess.run):
    """빌드 입력 폴더에서 `git status` 에 안 보이게 가려진 변경 — git 표시(`skip-worktree`·`assume-unchanged`)와, 디스크의 실제 파일 목록이 `git ls-files` 와 다른 곳(D-441). 문제 글 목록(없으면 빈 목록).
    `git status` 는 설정(`status.showUntrackedFiles=no`)과 이 표시에 흔들리므로 설정과 상관없이 같은 답이 나오는 것만 믿는다. 한계: 파일의 크기·시각을 같게 맞춰 git 의 상태 캐시를 속이는 수정은 보지 않는다."""
    listing = git_output(repo, "ls-files", "-v", "-z", "--", *INPUT_PATHS, runner=runner)
    problems, tracked = [], set()
    for entry in listing.split(chr(0)):
        if len(entry) < 3:
            continue
        tag, name = entry[0], entry[2:]
        tracked.add(name)
        if tag == "S" or tag.islower():
            problems.append(f"{name}(git 표시: {'skip-worktree' if tag in 'Ss' else 'assume-unchanged'})")
    root = Path(repo)
    actual = set()
    for folder in INPUT_FOLDERS:
        for current, directories, names in os.walk(root / folder):
            directories[:] = sorted(item for item in directories if item != "__pycache__")
            for item in directories:
                if (Path(current) / item).is_symlink():
                    actual.add((Path(current) / item).relative_to(root).as_posix())                 # 폴더를 가리키는 추적 링크는 파일 하나로 센다
            for name in names:
                relative = (Path(current) / name).relative_to(root).as_posix()
                if not relative.endswith(".pyc"):
                    actual.add(relative)
    if (root / "VERSION").is_file():
        actual.add("VERSION")
    problems += [f"{name}(git 이 모르는 파일)" for name in sorted(actual - tracked)]
    problems += [f"{name}(추적 파일이 디스크에 없음)" for name in sorted(tracked - actual)]
    return problems


def git_state(repo, *, runner=subprocess.run):
    """커밋(전체 해시)·트리 해시·작업 트리가 깨끗한지·커밋 시각. 커밋되지 않은 변경이나 새 파일(무시 목록 밖)이 하나라도 있거나, 빌드 입력 폴더 안에 무시되는 파일이나 git 표시로 가려진 변경이 있으면 깨끗하지 않다."""
    commit = git_output(repo, "rev-parse", "HEAD", runner=runner).strip()
    tree = git_output(repo, "rev-parse", "HEAD^{tree}", runner=runner).strip()
    epoch = int(git_output(repo, "show", "-s", "--format=%ct", "HEAD", runner=runner).strip())
    porcelain = git_output(repo, "status", "--porcelain", "--untracked-files=all", runner=runner)         # 명령줄 옵션이 설정(`status.showUntrackedFiles`)보다 앞선다
    dirty = [line for line in porcelain.splitlines() if line.strip()]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise BuildRefused("git 이 돌려준 커밋·트리 해시의 모양이 이상해요.")
    ignored = ignored_inputs(repo, runner=runner)
    hidden = git_hidden_changes(repo, runner=runner)
    return {"commit": commit, "tree": tree, "clean": not dirty and not ignored and not hidden, "dirty_count": len(dirty), "ignored_inputs": ignored, "hidden_changes": hidden,
            "committed_epoch": epoch, "committed_utc": utc_text(epoch)}


def require_clean(state):
    """깨끗하지 않으면 빌드를 거절한다(커밋 해시가 묶음의 내용을 대표하게)."""
    if state["clean"]:
        return state
    if state.get("dirty_count"):
        raise BuildRefused(f"작업 트리가 깨끗하지 않아요(커밋되지 않은 변경·새 파일 {state['dirty_count']}개). 모두 커밋한 뒤 다시 빌드해 주세요 — 커밋 해시가 묶음 내용을 대표해야 해요"
                           "(가상환경을 저장소 안에 만들었다면 저장소 밖으로 옮겨 주세요).")
    ignored = list(state.get("ignored_inputs") or [])
    if ignored:
        more = f" 외 {len(ignored) - 5}개" if len(ignored) > 5 else ""
        raise BuildRefused(f"빌드 입력 폴더({', '.join(INPUT_PATHS)})에 git 이 무시하는 파일이 있어요: {', '.join(ignored[:5])}{more}. 지우거나 저장소 밖으로 옮긴 뒤 다시 빌드해 주세요 — 커밋에 없는 파일이 묶음에 섞이면 안 돼요.")
    hidden = list(state.get("hidden_changes") or [])
    if hidden:
        more = f" 외 {len(hidden) - 5}개" if len(hidden) > 5 else ""
        raise BuildRefused(f"빌드 입력 폴더({', '.join(INPUT_PATHS)})에 git 상태에 안 보이게 가려진 변경이 있어요: {', '.join(hidden[:5])}{more}. git 의 skip-worktree·assume-unchanged 표시를 풀고 "
                           "(`git update-index --no-skip-worktree`·`--no-assume-unchanged`) 커밋하거나 되돌린 뒤 다시 빌드해 주세요 — 커밋 해시가 묶음 내용을 대표해야 해요.")
    raise BuildRefused("작업 트리가 깨끗하지 않아요.")


def utc_text(epoch):
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- 의존성 -----------------------------------------------------------

def normalize_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(text):
    """잠금 파일 → [{name, version, hashes, role}] — 정확한 `==` 고정만 받는다(범위·URL·옵션 줄·중복은 거절). `# [runtime]`·`# [build]` 줄이 뒤따르는 항목의 역할을 정한다."""
    role = None
    found = []
    seen = set()
    text = re.sub(r"\\\r?\n[ \t]*", " ", text)                 # pip 의 줄 이음(역슬래시로 끝난 줄 + `--hash=` 줄)을 한 줄로 합친다
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        marker = _ROLE_LINE.match(line)
        if marker:
            if marker.group("role") not in ROLES:
                raise BuildRefused(f"잠금 파일 {number}행: 모르는 역할 표시예요.")
            role = marker.group("role")
            continue
        if line.startswith("#"):
            continue
        match = _REQ_LINE.match(line)
        if match is None:
            raise BuildRefused(f"잠금 파일 {number}행: 'name==version' 꼴이 아니에요(범위·URL·옵션은 쓰지 않아요).")
        if role is None:
            raise BuildRefused(f"잠금 파일 {number}행: 앞에 '# [runtime]' 또는 '# [build]' 줄이 필요해요.")
        key = normalize_name(match.group("name"))
        if key in seen:
            raise BuildRefused(f"잠금 파일 {number}행: 같은 패키지가 두 번 있어요.")
        seen.add(key)
        hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", match.group("hashes"))
        found.append({"name": match.group("name"), "version": match.group("version"), "hashes": hashes, "role": role})
    if not found:
        raise BuildRefused("잠금 파일에 항목이 없어요.")
    return found


def installed_version(name, *, lookup=metadata.version):
    try:
        return lookup(name)
    except metadata.PackageNotFoundError:
        return None


def check_installed(requirements, *, lookup=metadata.version):
    """설치된 버전이 잠금 파일과 정확히 같은지 — 다르면 거절(재현 가능한 빌드)."""
    problems = []
    for item in requirements:
        have = installed_version(item["name"], lookup=lookup)
        if have is None:
            problems.append(f"{item['name']}: 설치 안 됨(잠금 {item['version']})")
        elif have != item["version"]:
            problems.append(f"{item['name']}: 설치 {have} ≠ 잠금 {item['version']}")
    if problems:
        raise BuildRefused("설치된 도구가 잠금 파일과 달라요 — " + " · ".join(problems))
    return True


def record_fingerprint(record_text):
    """설치된 배포본의 `RECORD`(파일 경로와 해시 목록)에서 환경마다 다른 줄(스크립트·캐시·설치 기록)을 빼고 요약한 지문과 줄 수."""
    rows = []
    for row in csv.reader(io.StringIO(record_text)):
        if len(row) < 2 or not row[0]:
            continue
        path = row[0].replace("\\", "/")
        if path.startswith("..") or "__pycache__" in path or path.endswith(_RECORD_SKIP_SUFFIXES) or path.rsplit("/", 1)[-1] in _RECORD_SKIP_NAMES:
            continue
        rows.append(f"{path},{row[1]}")
    rows.sort()
    return "sha256:" + pc.sha256_bytes("\n".join(rows).encode("utf-8")), len(rows)


def package_license(meta):
    """배포본 메타데이터의 라이선스 표기(짧게). 긴 전문이 `License` 칸에 들어 있으면 첫 줄만."""
    value = meta.get("License-Expression") or meta.get("License") or ""
    value = value.strip().splitlines()[0][:120] if value.strip() else ""
    if not value:
        classifiers = [item.split("::")[-1].strip() for item in (meta.get_all("Classifier") or []) if item.startswith("License ::")]
        value = " / ".join(classifiers)[:120]
    return value or "표기 없음"


def dependency_entries(requirements, *, distribution=metadata.distribution):
    entries = []
    for item in requirements:
        entry = {"name": item["name"], "version": item["version"], "role": item["role"], "license": "", "fingerprint": "", "files": 0}
        try:
            dist = distribution(item["name"])
            entry["license"] = package_license(dist.metadata)
            record = dist.read_text("RECORD")
            if record:
                entry["fingerprint"], entry["files"] = record_fingerprint(record)
        except metadata.PackageNotFoundError:
            pass
        entries.append(entry)
    return entries


# ---- 파일 목록·서명 --------------------------------------------------------

def collect_files(root, *, skip_root=pc.FILES_EXCLUDED_FROM_LIST):
    """묶음 폴더 안 모든 파일의 {`/` 로 나눈 상대 경로: SHA-256}(경로 순). 맨 위 폴더의 `PACKAGE_INFO.*` 는 자기 자신이라 뺀다."""
    root = Path(root)
    found = {}
    for current, directories, names in os.walk(root):
        directories.sort()
        for name in sorted(names):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if relative in skip_root:
                continue
            found[relative] = pc.sha256_file(path)
    return dict(sorted(found.items()))


def authenticode_state(path):
    """PE 파일의 보안 디렉터리(IMAGE_DIRECTORY_ENTRY_SECURITY) 크기로 서명 여부를 읽는다 — 'signed' · 'unsigned' · 'not_pe'. 서명을 검증하지는 않는다(있는지만)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
            if len(head) < 64 or head[:2] != b"MZ":
                return "not_pe"
            offset = struct.unpack_from("<I", head, 0x3C)[0]
            handle.seek(offset)
            block = handle.read(24 + 240)
    except OSError:
        return "not_pe"
    if len(block) < 26 or block[:4] != b"PE\0\0":
        return "not_pe"
    magic = struct.unpack_from("<H", block, 24)[0]
    directories = 24 + (112 if magic == 0x20B else 96 if magic == 0x10B else -1)
    if directories < 24 or len(block) < directories + 8 * 5:
        return "not_pe"
    size = struct.unpack_from("<I", block, directories + 8 * 4 + 4)[0]
    return "signed" if size else "unsigned"


def signing_summary(bundle, exe_name):
    """실행 파일의 서명 여부(읽은 사실)와 묶음 안 서명된 외부 구성 요소 수."""
    exe = Path(bundle) / exe_name
    own = authenticode_state(exe) if exe.is_file() else "missing"
    third = 0
    for current, _directories, names in os.walk(bundle):
        for name in names:
            if name.lower().endswith((".dll", ".pyd", ".exe")) and Path(current, name) != exe and authenticode_state(Path(current, name)) == "signed":
                third += 1
    return {"signed": own == "signed", "exe": own, "summary": SIGNING_TEXT, "signed_third_party_binaries": third}


# ---- 악성코드 검사(읽기 전용) --------------------------------------------------

def defender_status(*, runner=subprocess.run):
    """Windows Defender 의 상태(서비스 켜짐·엔진·서명 버전) — 읽기 전용 질의. 못 읽으면 {}."""
    command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "Get-MpComputerStatus | Select-Object AMServiceEnabled,AntivirusEnabled,AMEngineVersion,AntivirusSignatureVersion | ConvertTo-Json -Compress"]
    try:
        result = runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        data = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def find_defender(*, which=shutil.which, environ=None, exists=os.path.isfile, listing=os.listdir):
    environ = os.environ if environ is None else environ
    found = which("MpCmdRun.exe")
    if found:
        return found
    candidates = []
    program_data = environ.get("ProgramData") or environ.get("PROGRAMDATA")
    if program_data:
        platform_dir = os.path.join(program_data, "Microsoft", "Windows Defender", "Platform")
        try:
            versions = sorted(listing(platform_dir), reverse=True)
        except OSError:
            versions = []
        candidates += [os.path.join(platform_dir, version, "MpCmdRun.exe") for version in versions]
    program_files = environ.get("ProgramFiles") or environ.get("PROGRAMFILES")
    if program_files:
        candidates.append(os.path.join(program_files, "Windows Defender", "MpCmdRun.exe"))
    return next((path for path in candidates if exists(path)), None)


def scan_with_defender(paths, *, runner=subprocess.run, status=defender_status, locate=find_defender, clock=time.time):
    """Windows Defender 로 읽기 전용 검사(`-DisableRemediation` — 치료·격리·설정 변경 없음). 못 돌리면 이유를 정직하게 적는다."""
    base = {"tool": "Microsoft Defender (MpCmdRun.exe)", "targets": [Path(p).name for p in paths], "exit_codes": []}
    if sys.platform != "win32" and locate is find_defender:
        return {**base, "status": "not_run", "reason": "윈도가 아닌 PC 라 Windows Defender 를 쓸 수 없었어요."}
    program = locate()
    if not program:
        return {**base, "status": "not_run", "reason": "MpCmdRun.exe 를 이 PC 에서 찾지 못했어요."}
    state = status()
    engine = str(state.get("AMEngineVersion", "") or "")
    signatures = str(state.get("AntivirusSignatureVersion", "") or "")
    base.update({"engine_version": engine, "signature_version": signatures})
    if state and not (state.get("AMServiceEnabled") and state.get("AntivirusEnabled")):
        return {**base, "status": "not_run", "reason": "이 PC 의 Windows Defender 서비스가 꺼져 있어요(AMServiceEnabled=False 또는 AntivirusEnabled=False) — 회사 PC 의 다른 보안 프로그램이 따로 있어도 그 결과는 읽을 수 없어요."}
    began = clock()
    worst = "clean"
    for path in paths:
        try:
            result = runner([program, *DEFENDER_ARGS, str(path), DEFENDER_READONLY], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        except (OSError, subprocess.SubprocessError) as error:
            return {**base, "status": "scan_failed", "reason": f"검사를 시작하지 못했어요({type(error).__name__}).", "seconds": round(clock() - began, 1)}
        base["exit_codes"].append(result.returncode)
        if result.returncode == 0:
            continue
        worst = "threats_found" if result.returncode == 2 else "scan_failed"
        break
    reasons = {"clean": "위협이 발견되지 않았어요.", "threats_found": "위협이 발견됐다고 보고했어요 — 이 묶음을 쓰지 마세요.", "scan_failed": "검사가 끝나지 못했어요(종료 코드를 보세요)."}
    return {**base, "status": worst, "reason": reasons[worst], "seconds": round(clock() - began, 1), "scanned_utc": utc_text(clock())}


def malware_text(scan):
    if not scan:
        return "검사 안 함 — 이 정보 파일을 만들 때 검사를 요청하지 않았어요."
    status = scan.get("status")
    if status == "not_run":
        return f"검사 안 함 — {scan.get('reason', '이유를 읽지 못했어요.')}"
    parts = [f"{scan.get('tool', '검사 도구')}: {scan.get('reason', '')}".strip(),
             f"대상: {', '.join(scan.get('targets', []))}", f"종료 코드: {', '.join(str(code) for code in scan.get('exit_codes', []))}"]
    if scan.get("engine_version"):
        parts.append(f"엔진 {scan['engine_version']}")
    if scan.get("signature_version"):
        parts.append(f"서명 정의 {scan['signature_version']}")
    if scan.get("scanned_utc"):
        parts.append(f"검사 시각 {scan['scanned_utc']}(UTC)")
    if scan.get("seconds") is not None:
        parts.append(f"걸린 시간 {scan['seconds']}초")
    return " · ".join(part for part in parts if part)


# ---- 정보 만들기 -------------------------------------------------------------

def build_info(*, variant, version, git, requirements, python_version, lock_sha256, build, dependencies, files, signing,
               package=None, scan=None, built_utc=None, selftest=None, host=None, trial=False):
    """정보 사전 하나. `variant` 가 'inner' 이면 시계·압축 파일 해시·검사 결과·자가 점검·만든 PC 정보를 담지 않는다(같은 입력이면 같은 바이트).
    `trial` 은 시험 빌드(외부 쓰기 관문 모듈이 아직 없는 소스를 `--allow-missing-gate` 로 만든 것) 표시 — 개인 PC 로 보내지 않는 빌드다."""
    if variant not in ("inner", "outer"):
        raise ValueError("variant 는 inner 또는 outer")
    info = {
        "schema": pc.SCHEMA,
        "product": pc.PRODUCT,
        "channel": pc.CHANNEL,
        "notice": pc.NOTICE_LONG,
        "trial": bool(trial),
        "variant": variant,
        "version": version,
        "git": {"repository": REPOSITORY, "commit": git["commit"], "tree": git["tree"], "clean": bool(git["clean"]), "committed_utc": git["committed_utc"]},
        "dependencies": {"python": python_version, "lock_file": LOCK_RELATIVE, "lock_sha256": lock_sha256, "wheel_hashes_in_lock": any(item["hashes"] for item in requirements),
                         "packages": dependencies},
        "build": build,
        "signing": signing,
        "smartscreen": SMARTSCREEN_TEXT,
        "limits": list(LIMITS),
        "file_count": len(files),
        "files": files,
    }
    if variant == "outer":
        info["package"] = package
        info["malware_scan"] = scan
        info["built_utc"] = built_utc
        info["selftest"] = selftest
        info["host"] = host
        info["release_eligible"] = bool(selftest and selftest.get("gate_present") and not selftest.get("failed") and not trial)
    return info


def render_json(info):
    return json.dumps(info, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def render_sums(entries):
    """`sha256sum -c` 로 확인할 수 있는 모양 — `<해시>  <이름>` 한 줄씩(이름 순, 줄 끝 LF)."""
    return "".join(f"{digest}  {name}\n" for name, digest in sorted(entries))


def _hash_rows(files, names):
    return [f"| `{name}` | `{files[name]}` |" for name in names if name in files]


def render_markdown(info):
    version = info["version"]
    git = info["git"]
    deps = info["dependencies"]
    outer = info["variant"] == "outer"
    lines = [f"**{pc.NOTICE_LONG}**", "", f"# {pc.PRODUCT} {version} — Package 정보", ""]
    lines += ["운영자가 정한 여덟 가지(Version · Git Commit · SHA-256 · Dependency 목록 · Build 방법 · Malware 검사 결과 · 서명 여부 · SmartScreen 예상 동작)를 아래 1에서 8에 적었습니다.",
              ("이 문서는 압축 파일 옆에 두는 완전한 사본입니다." if outer else
               "이 문서는 묶음 폴더 안의 사본입니다 — 압축 파일 자체의 SHA-256 과 악성코드 검사 결과는 시계가 들어가므로 이 안에 담지 않고 압축 파일 옆의 PACKAGE_INFO.md 에 있습니다."), ""]
    if info.get("trial"):
        lines += [f"**이 빌드는 시험 빌드({pc.TRIAL_TAG})입니다 — 외부 쓰기 관문 모듈이 아직 없는 소스를 `--allow-missing-gate` 로 만들었습니다. 개인 PC 로 보내지 않습니다. 압축 파일 이름에도 {pc.TRIAL_TAG} 가 들어 있습니다.**", ""]
    elif outer and not info.get("release_eligible"):
        lines += ["**이 빌드는 시험 빌드입니다 — 외부 쓰기 관문 확인이 빠졌거나 자가 점검이 실패했습니다. 개인 PC 로 보내지 않습니다(아래 자가 점검 결과 참고).**", ""]
    lines += ["## 1. Version", "", f"- `{version}` (`preview` 는 시험판이라는 뜻이며 정식 0.1.0 이 아닙니다 — `VERSION` 파일과 같은 값)", ""]
    lines += ["## 2. Git Commit", "",
              f"- 저장소: `{git['repository']}`", f"- 커밋(전체 해시): `{git['commit']}`", f"- 트리 해시: `{git['tree']}`", f"- 작업 트리: {'깨끗함(커밋되지 않은 변경 0)' if git['clean'] else '깨끗하지 않음'}",
              f"- 커밋 시각(UTC): {git['committed_utc']}", ""]
    lines += ["## 3. SHA-256", ""]
    if outer and info.get("package"):
        package = info["package"]
        lines += [f"- 압축 파일 `{package['name']}`: `{package['sha256']}` (크기 {package['bytes']:,} 바이트)",
                  f"- 확인 방법: PowerShell 에서 `Get-FileHash .\\{package['name']} -Algorithm SHA256` 의 값이 위 값과 같아야 합니다(`SHA256SUMS` 파일에도 같은 값이 있습니다)."]
    else:
        lines += ["- 압축 파일의 SHA-256 은 압축 파일 옆의 `SHA256SUMS`·`PACKAGE_INFO.md` 에 있습니다(이 안에 적으면 자기 자신을 담는 순환이 됩니다)."]
    files = info["files"]
    lines += [f"- 묶음 안 모든 파일(`{info['file_count']:,}`개)의 SHA-256 은 `PACKAGE_INFO.json` 의 `files` 칸에 있습니다(상대 경로 → 해시, 이 정보 파일 자신은 뺌). 묶음 안 `--selftest` 가 이 목록과 실제 파일을 대조합니다.", "",
              "| 중요한 파일 | SHA-256 |", "|---|---|"]
    lines += _hash_rows(files, (f"{pc.EXE_NAME}.exe", "VERSION", "vendor/VENDOR.json", "vendor/pipeline/gates.py", "vendor/pipeline/secret_patterns.py"))
    lines += [""]
    lines += ["## 4. Dependency 목록", "", f"- 파이썬: `{deps['python']}` · 잠금 파일: `{deps['lock_file']}`(SHA-256 `{deps['lock_sha256']}`)",
              f"- 배포 파일(wheel) 해시가 잠금 파일에 있는가: {'예' if deps['wheel_hashes_in_lock'] else '아니요(정확한 버전 고정만 — 한계 참고)'}", "",
              "pip freeze 모양(정확한 버전):", "", "```text"]
    lines += [f"{item['name']}=={item['version']}" for item in deps["packages"]]
    lines += ["```", "", "| 패키지 | 버전 | 역할 | 라이선스 표기 | 설치 내용 지문(RECORD 요약) |", "|---|---|---|---|---|"]
    lines += [f"| {item['name']} | {item['version']} | {'묶음 안에 들어감' if item['role'] == 'runtime' else '묶음을 만드는 도구'} | {item['license']} | `{item['fingerprint'] or '없음'}` |" for item in deps["packages"]]
    lines += [""]
    build = info["build"]
    lines += ["## 5. Build 방법", ""]
    lines += [f"{number}. {step}" for number, step in enumerate(HOW_TO_BUILD, 1)]
    if info.get("trial"):
        lines += ["", f"- **이 빌드는 `python packaging/build_package.py --allow-missing-gate` 로 만든 시험 빌드입니다**(외부 쓰기 관문 모듈이 아직 없는 소스). 정식 빌드는 이 옵션 없이 만들고, 위 5단계의 압축 파일 이름에는 {pc.TRIAL_TAG} 가 없습니다."]
    lines += ["", f"실제로 실행한 PyInstaller 명령(경로는 `<저장소>`·`<출력>` 으로 줄임): `{' '.join(build['command'])}`", "",
              f"- 빌드 도구: {build['tool']} · 결정적 빌드 환경 변수: {', '.join(f'{k}={v}' for k, v in build['env'].items())} · zlib {build['zlib']}",
              f"- 외부 쓰기 관문(capabilities) 없이 만든 시험 빌드인가: {'예' if build.get('gate_override') else '아니요'}", ""]
    lines += ["## 6. Malware 검사 결과", ""]
    if outer:
        lines += [f"- {malware_text(info.get('malware_scan'))}"]
        if not (info.get("malware_scan") and info["malware_scan"].get("status") == "clean"):
            lines += ["- 운영자 개인 PC 에서는 압축을 풀기 전에 압축 파일을 마우스 오른쪽 단추로 눌러 Windows 보안(Microsoft Defender)으로 직접 검사해 주세요(시험지 0단계)."]
    else:
        lines += ["- 압축 파일을 만든 뒤에 검사하므로 결과는 압축 파일 옆의 `PACKAGE_INFO.md` 에 있습니다."]
    lines += [""]
    signing = info["signing"]
    lines += ["## 7. 서명 여부", "", f"- **{pc.NOTICE}**: " + ("서명 있음" if signing["signed"] else "미서명") + f" (실행 파일 서명 확인: {signing['exe']})", f"- {signing['summary']}",
              f"- 묶음 안 서명된 외부 구성 요소(DLL·pyd): {signing['signed_third_party_binaries']}개", ""]
    lines += ["## 8. SmartScreen 예상 동작", "", SMARTSCREEN_TEXT, ""]
    if outer and info.get("selftest"):
        check = info["selftest"]
        counts = f"- 통과 {len(check.get('passed', []))} · 실패 {len(check.get('failed', []))} · 건너뜀 {len(check.get('skipped', []))}"
        if check.get("gate_override"):
            counts += " · 허용된 관문 실패 1(시험 빌드 — capabilities 모듈이 없음)"
        lines += ["## 자가 점검 결과(`--selftest`)", "", counts,
                  f"- 외부 쓰기 관문(capabilities) 확인됨: {'예' if check.get('gate_present') else '아니요'}"]
        if check.get("failed"):
            lines += ["- 실패한 점검: " + ", ".join(check["failed"])]
        lines += [""]
    lines += ["## 확인하지 못한 것·한계", ""] + [f"- {item}" for item in info["limits"]] + [""]
    return "\n".join(lines)


# ---- 낱개 부품을 모아 정보 만들기(빌드가 부른다) ---------------------------------------

def gather(*, repo, bundle, variant, version, build, clock=time.time, runner=subprocess.run, lookup=metadata.version, distribution=metadata.distribution,
           python_version=None, package=None, scan=None, selftest=None, host=None, state=None, trial=False):
    repo = Path(repo)
    state = state or require_clean(git_state(repo, runner=runner))
    lock_text = (repo / LOCK_RELATIVE).read_text(encoding="utf-8")
    requirements = parse_requirements(lock_text)
    check_installed(requirements, lookup=lookup)
    files = collect_files(bundle)
    return build_info(
        variant=variant, version=version, git=state, requirements=requirements, python_version=python_version or ".".join(str(n) for n in sys.version_info[:3]),
        lock_sha256=pc.sha256_bytes(lock_text.replace("\r\n", "\n").encode("utf-8")), build=build, dependencies=dependency_entries(requirements, distribution=distribution),
        files=files, signing=signing_summary(bundle, f"{pc.EXE_NAME}.exe"), package=package, scan=scan,
        built_utc=utc_text(clock()) if variant == "outer" else None, selftest=selftest, host=host, trial=trial)


def write_inner(bundle, info):
    """묶음 폴더 안에 `PACKAGE_INFO.json`·`.md` 를 쓴다(줄 끝 LF, UTF-8)."""
    bundle = Path(bundle)
    (bundle / pc.INFO_JSON).write_bytes(render_json(info).encode("utf-8"))
    (bundle / pc.INFO_MD).write_bytes(render_markdown(info).encode("utf-8"))


def write_outer(out_dir, info, zip_path):
    """압축 파일 옆에 `PACKAGE_INFO.json`·`.md`·`SHA256SUMS` 를 쓴다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / pc.INFO_JSON).write_bytes(render_json(info).encode("utf-8"))
    (out_dir / pc.INFO_MD).write_bytes(render_markdown(info).encode("utf-8"))
    (out_dir / pc.SUMS_NAME).write_bytes(render_sums([(Path(zip_path).name, info["package"]["sha256"])]).encode("utf-8"))


def zlib_text():
    return getattr(zlib, "ZLIB_RUNTIME_VERSION", zlib.ZLIB_VERSION)


def default_build_record(command, *, tool, env, gate_override=False):
    return {"tool": tool, "command": list(command), "env": dict(env), "zlib": zlib_text(), "gate_override": bool(gate_override)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Package 정보 파일(PACKAGE_INFO.md·PACKAGE_INFO.json·SHA256SUMS)을 만든다.")
    parser.add_argument("variant", choices=("inner", "outer"))
    parser.add_argument("--bundle", required=True, help="묶음 폴더(실행 파일이 있는 폴더)")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--zip", help="outer: 압축 파일")
    parser.add_argument("--out", help="outer: 정보 파일을 둘 폴더")
    parser.add_argument("--no-scan", action="store_true", help="outer: 악성코드 검사를 하지 않는다")
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    try:
        version = pc.parse_version_text((repo / "VERSION").read_text(encoding="utf-8"))
    except OSError:
        version = None
    if not version:
        print("VERSION 을 읽지 못했어요.", file=sys.stderr)
        return 2
    build = default_build_record(["(build_package.py 가 실행한 명령은 빌드 도구가 채웁니다)"], tool="미기록", env={})
    try:
        if args.variant == "inner":
            write_inner(args.bundle, gather(repo=repo, bundle=args.bundle, variant="inner", version=version, build=build))
            return 0
        if not args.zip or not args.out:
            print("outer 는 --zip 과 --out 이 필요해요.", file=sys.stderr)
            return 2
        zip_path = Path(args.zip)
        package = {"name": zip_path.name, "sha256": pc.sha256_file(zip_path), "bytes": zip_path.stat().st_size}
        scan = None if args.no_scan else scan_with_defender([zip_path, Path(args.bundle)])
        info = gather(repo=repo, bundle=args.bundle, variant="outer", version=version, build=build, package=package, scan=scan,
                      selftest=None, host={"python": sys.version.split()[0]})
        write_outer(args.out, info, zip_path)
        return 0
    except BuildRefused as refused:
        print(str(refused), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
