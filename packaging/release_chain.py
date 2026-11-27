"""릴리스 버전 사슬 — `VERSION` 한 곳에서 태그·설치 파일 이름·매니페스트·묶음 정보·릴리스 제목·본문(릴리스 노트)·변경 이력 절·앱 정보 카드가 모두 같은 글로 나오는지 만들고 확인한다(RELEASE 설계서 3-3·3-6, V1REL12·R-2).

표준 라이브러리만 쓴다(`pkgcommon` 의 이름·버전 규칙을 불러 쓴다). 순수 함수가 중심이고 명령줄은 얇다. 앱 코드는 **함수 안에서만** 불러온다(매니페스트·정보 카드를 앱의 규칙으로 견줄 때).

쓰는 법(저장소 맨 위 폴더에서):
    python -X utf8 packaging/release_chain.py assemble --source 폴더 [--source 폴더 ...] --out release   묶음 빌드·설치 파일 산출물을 `release/` 로 모으고 `release_candidate.json` 을 쓴 뒤 사슬을 확인한다
    python -X utf8 packaging/release_chain.py check --dir release [--phase candidate|final]                사슬만 다시 확인한다(서명한 뒤에는 `--phase final`)
    python -X utf8 packaging/release_chain.py sums --dir release                                           `SHA256SUMS` 를 폴더 안 모든 파일(자기 자신과 후보 기록 빼고)로 다시 쓴다
    python -X utf8 packaging/release_chain.py notes --out 파일                                             `CHANGELOG.md` 의 `VERSION` 절에서 릴리스 본문을 만들어 쓴다(모양이 틀리면 쓰지 않는다)
    python -X utf8 packaging/release_chain.py names                                                        태그·제목·채널·사전판 여부·설치 파일·압축 파일 이름을 `이름=값` 줄로 보인다

사슬(모두 `VERSION` 한 곳에서 나온다): `VERSION` → 태그 `v<버전>` → 매니페스트 `version`·`tag` → `PACKAGE_INFO.version` → 설치 파일·휴대용 압축 파일 이름 → 릴리스 제목 `ChanceBlog Desktop <버전>`
→ 본문(= `CHANGELOG.md` 의 그 버전 절 + 고정 안내 꼬리) → 변경 이력 절 → 앱 정보 카드 `v<버전>`. 버전 글은 정식(`X.Y.Z`)이나 후보(`X.Y.Z-rc.N`, N 은 1 이상) 둘뿐이고 그 밖의 사전판 글자는 거절한다.

`release/` 폴더의 파일은 정해진 이름뿐이다(설치 파일·휴대용 압축 파일·`SHA256SUMS`·`PACKAGE_INFO.json`·`PACKAGE_INFO.md`·`release_candidate.json`, 서명한 뒤에는 매니페스트와 서명 파일이 더해진다).
`release_candidate.json` 은 파일마다 이름·크기·SHA-256 과 버전·태그·커밋·러너 이미지를 담은 후보 기록이고, 서명 잡이 파일을 **다시 해시해** 이 기록과 견준다(`scripts/update_manifest.py verify-candidate`).
`SHA256SUMS` 는 폴더 안 모든 파일(자기 자신과 후보 기록 빼고)의 줄을 정확히 한 줄씩 가진다 — 줄이 모자라거나 남거나 해시가 다르면 사슬이 거절한다.
릴리스 노트의 위치와 틀은 `docs/RELEASE.md` 의 '릴리스 노트 규칙'(DOCS 갈래)이 정한 것을 따른다: 정본은 `CHANGELOG.md` 의 `## [X.Y.Z] — YYYY-MM-DD` 절이고 `### 요약`·`### 자세히`·`### 이관 노트` 가 있다.
요약은 3–10줄·500글자 이하(매니페스트 `notes.summary` 가 그대로 쓴다)다. 본문 파일 = 그 절의 본문 + 고정 안내 꼬리(SHA-256 확인법·서명 없음 안내).
종료 코드: 0 성공 · 1 사슬·노트 검사에서 문제가 있음 · 2 사용법·파일 오류.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import namedtuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pkgcommon as pc  # noqa: E402

KIND_STABLE, KIND_RC = "stable", "rc"
ROLE_SETUP, ROLE_PORTABLE, ROLE_SUMS, ROLE_INFO_JSON, ROLE_INFO_MD = "setup", "portable", "sums", "info_json", "info_md"
ASSET_ROLES = (ROLE_SETUP, ROLE_PORTABLE, ROLE_SUMS, ROLE_INFO_JSON, ROLE_INFO_MD)
MANIFEST_ROLES = (ROLE_SETUP, ROLE_PORTABLE)                  # 앱의 매니페스트 `files` 에 오르는 역할(앱이 받는 설치 파일과 휴대용 압축 파일)
CANDIDATE_NAME = "release_candidate.json"
MANIFEST_NAME = "update-manifest.json"                        # 앱 `manifest.MANIFEST_NAME` 과 같다(시험이 지킨다)
SIGNATURE_NAME = "update-manifest.json.sig"
CANDIDATE_SCHEMA = 1
PHASE_CANDIDATE, PHASE_FINAL = "candidate", "final"
INSTALLER_KIND = "inno"                                       # 설치 도구 결정 D-811
DEFAULT_PACK_ID = "ChanceBlogDesktop"
Limits = namedtuple("Limits", "file total support")
DEFAULT_LIMITS = Limits(file=200 * 1024 * 1024, total=400 * 1024 * 1024, support=4 * 1024 * 1024)      # 앞의 둘은 앱 `manifest.MAX_FILE_BYTES`·`MAX_TOTAL_BYTES` 와 같다(시험이 지킨다)
MAX_CANDIDATE_BYTES = 64 * 1024
MAX_INFO_BYTES = 4 * 1024 * 1024
MAX_NOTES_SECTION_CHARS = 20000                               # RELEASE.md 릴리스 노트 규칙의 한 절 길이 한도
MAX_SUMMARY_CHARS = 500                                       # 앱 `manifest.MAX_NOTES_CHARS`
MAX_SUMMARY_LINES = 10                                        # 앱 `manifest.MAX_NOTES_LINES`
MIN_SUMMARY_LINES = 3
HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})      # 앱 `manifest._HIDDEN_CATEGORIES` 와 같다(시험이 지킨다)
SUMMARY_HIDDEN_ALLOWED = frozenset({"\n"})                               # 요약 칸(앱의 규칙)에서 허용하는 보이지 않는 글자 — 줄바꿈뿐
NOTES_HIDDEN_ALLOWED = frozenset({"\n", "\t", chr(0x200D)})              # 절 전체(머리 줄·요약·자세히·이관 노트)에서 허용하는 것 — 줄바꿈·탭·이모지 조합용 ZWJ(재작업 1·S-6)
PRERELEASE_WORDS = ("-rc", "-preview", "-beta", "-alpha", "-dev", "TESTBUILD")
EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE = 0, 1, 2

_NUM = r"(?:0|[1-9][0-9]*)"
STABLE_RE = re.compile(_NUM + r"\." + _NUM + r"\." + _NUM, re.ASCII)
RC_RE = re.compile(_NUM + r"\." + _NUM + r"\." + _NUM + r"-rc\.[1-9][0-9]*", re.ASCII)
_COMMIT = re.compile(r"[0-9a-f]{40}", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_IMAGE_WORD = re.compile(r"[A-Za-z0-9._-]{1,64}", re.ASCII)
_PACK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", re.ASCII)
_SUMS_LINE = re.compile(r"([0-9a-f]{64})  ([^\s/\\]+)", re.ASCII)
_HEADING = re.compile(r"^## \[([^\]]+)\] — (\d{4}-\d{2}-\d{2})(?: \(.+\))?$")          # 옛 모양(뒤에 괄호 설명)도 읽는다 — `tests/test_v1_docs.py` 의 참고 구현과 같다
_NEW_HEADING = re.compile(r"^## \[([^\]]+)\] — (\d{4}-\d{2}-\d{2})$", re.ASCII)         # 새 절의 머리 줄은 괄호 설명 없이 정확히 이 꼴(날짜는 ASCII 숫자만 — 다른 글자의 숫자는 거절)
_STALE_ASSET = re.compile(r"^ChanceBlogDesktop-.+-(?:Setup\.exe|win64\.zip)$")
_URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
_KEY_SHAPES = tuple(re.compile(shape) for shape in pc.KEY_SHAPES)
SECTION_SUMMARY, SECTION_DETAILS, SECTION_MIGRATION = "### 요약", "### 자세히", "### 이관 노트"
REQUIRED_SECTIONS = (SECTION_SUMMARY, SECTION_DETAILS, SECTION_MIGRATION)
FOOTER = "\n".join((
    "### 내려받은 파일 확인하기",
    "",
    "- 설치 파일과 휴대용 압축 파일의 SHA-256 값은 이 릴리스의 SHA256SUMS 파일에 있어요. PowerShell 에서 Get-FileHash 로 구한 값이 같은지 견주어 보세요.",
    "- 이 설치 파일에는 코드 서명이 없어요(유료 인증서를 쓰지 않아요). 그래서 처음 설치할 때 Windows 가 SmartScreen 경고를 띄울 수 있어요. 추가 정보를 누른 뒤 실행을 누르면 시작돼요.",
))

Problem = namedtuple("Problem", "code detail")


class ChainError(Exception):
    """사슬 확인에서 걸린 문제들(`problems`)."""

    def __init__(self, problems):
        super().__init__("; ".join(describe(item) for item in problems))
        self.problems = list(problems)


class NotesError(ValueError):
    """변경 이력에서 그 버전의 절을 정확히 하나 고르지 못했다."""


def _plain(text, limit=80):
    shown = "".join(char if char.isprintable() else "?" for char in str(text))
    return shown if len(shown) <= limit else shown[:limit - 1] + "…"


def describe(problem):
    return problem.code + (" — " + problem.detail if problem.detail else "")


def _problem(code, detail=""):
    return Problem(code, _plain(detail) if detail else "")


# ---- 버전·이름 -----------------------------------------------------------------------------------------------------------------------------------
def version_kind(version):
    """`stable`(X.Y.Z)·`rc`(X.Y.Z-rc.N, N 은 1 이상·앞자리 0 없음)·None(그 밖의 모든 글 — 다른 사전판 글자·앞자리 0·글이 아님)."""
    if isinstance(version, str):
        if STABLE_RE.fullmatch(version):
            return KIND_STABLE
        if RC_RE.fullmatch(version):
            return KIND_RC
    return None


def read_version_file(raw):
    """`VERSION` 파일 내용 → 번호 또는 None(`pkgcommon` 의 읽기 규칙 + 정식·후보 모양만)."""
    number = pc.parse_version_text(raw)
    return number if version_kind(number) else None


def channel_of(version):
    return version_kind(version)


def tag_of(version):
    return "v" + version


def title_of(version):
    return f"{pc.PRODUCT} {version}"


def setup_name(version):
    return f"{pc.EXE_NAME}-{version}-Setup.exe"


def portable_name(version):
    return pc.zip_name(version)


def card_text(version):
    """앱 정보 카드에 보일 버전 글."""
    return "v" + version


def asset_names(version):
    """역할 → 파일 이름(후보 폴더에 있어야 하는 다섯 가지)."""
    return {ROLE_SETUP: setup_name(version), ROLE_PORTABLE: portable_name(version), ROLE_SUMS: pc.SUMS_NAME, ROLE_INFO_JSON: pc.INFO_JSON, ROLE_INFO_MD: pc.INFO_MD}


def published_names(version):
    """릴리스에 올리는 파일 이름들(서명한 뒤의 모양) — 후보 기록은 올리지 않는다."""
    return tuple(asset_names(version).values()) + (MANIFEST_NAME, SIGNATURE_NAME)


# ---- 읽기 도우미 ---------------------------------------------------------------------------------------------------------------------------------
def _read_limited(path, limit):
    """파일을 상한까지만 읽는다 → 바이트, 상한을 넘거나 못 읽으면 None."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        return None
    return data if len(data) <= limit else None


def _no_duplicates(pairs):
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate")
    return dict(pairs)


def _reject_constant(_name):
    raise ValueError("constant")


def _load_json(data):
    """엄격한 JSON 읽기(UTF-8·BOM 없음·같은 키 거절·NaN 거절) → 객체 또는 None."""
    try:
        text = data.decode("utf-8")
        if text.startswith(chr(0xFEFF)):
            return None
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        return None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def list_files(folder):
    """폴더 안 파일들 → ({이름: 경로}, 문제들). 하위 폴더·링크·일반 파일이 아닌 것은 문제다(따라가지 않는다)."""
    files, problems = {}, []
    try:
        with os.scandir(folder) as entries:
            found = sorted(entries, key=lambda entry: entry.name)
    except OSError:
        return {}, [_problem("folder_unreadable")]
    for entry in found:
        try:
            regular = entry.is_file(follow_symlinks=False) and not entry.is_symlink()
        except OSError:
            regular = False
        if regular:
            files[entry.name] = Path(entry.path)
        else:
            problems.append(_problem("file_not_regular", entry.name))
    return files, problems


# ---- 해시 목록(SHA256SUMS) -----------------------------------------------------------------------------------------------------------------------
def render_sums(entries):
    """`sha256sum -c` 로 확인할 수 있는 모양 — `<해시>  <이름>` 한 줄씩(이름 순, 줄 끝 LF)."""
    return "".join(f"{digest}  {name}\n" for name, digest in sorted(entries))


def sums_entries(folder):
    """폴더 안 모든 파일(`SHA256SUMS` 자기 자신과 후보 기록은 빼고)의 (이름, SHA-256)."""
    files, problems = list_files(folder)
    if problems:
        raise ChainError(problems)
    return [(name, pc.sha256_file(path)) for name, path in files.items() if name not in (pc.SUMS_NAME, CANDIDATE_NAME)]


def write_sums(folder):
    """`SHA256SUMS` 를 쓴다(바이트로 — 줄 끝은 늘 LF) → 쓴 글."""
    text = render_sums(sums_entries(folder))
    (Path(folder) / pc.SUMS_NAME).write_bytes(text.encode("utf-8"))
    return text


def parse_sums(data):
    """`SHA256SUMS` 바이트 → ([(이름, 해시)], 문제들). 모양: `<소문자 해시 64자리>` + 공백 둘 + 이름, 줄 끝 LF, 마지막 줄바꿈 하나, 같은 이름 없음."""
    problems = []
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        return [], [_problem("sums_shape")]
    if not text or "\r" in text or not text.endswith("\n") or text.endswith("\n\n"):
        return [], [_problem("sums_shape")]
    entries, names = [], set()
    for line in text[:-1].split("\n"):
        found = _SUMS_LINE.fullmatch(line)
        if found is None:
            return [], [_problem("sums_shape")]
        digest, name = found.groups()
        if name in names:
            problems.append(_problem("sums_duplicate", name))
        names.add(name)
        entries.append((name, digest))
    return entries, problems


# ---- 후보 기록(release_candidate.json) ------------------------------------------------------------------------------------------------------------
def candidate_asset(role, name, data_path):
    return {"role": role, "name": name, "size": Path(data_path).stat().st_size, "sha256": pc.sha256_file(data_path)}


def build_candidate(folder, version, *, commit, image, pack_id=DEFAULT_PACK_ID):
    """폴더의 다섯 파일을 해시해 후보 기록 사전을 만든다(쓰지는 않는다)."""
    names = asset_names(version)
    assets = [candidate_asset(role, names[role], Path(folder) / names[role]) for role in ASSET_ROLES]
    return {"candidate_schema": CANDIDATE_SCHEMA, "product": pc.EXE_NAME, "version": version, "tag": tag_of(version), "channel": channel_of(version), "commit": commit,
            "image": {"name": image[0], "version": image[1]}, "installer": {"kind": INSTALLER_KIND, "pack_id": pack_id}, "assets": assets}


def render_candidate(candidate):
    return (json.dumps(candidate, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


CANDIDATE_KEYS = frozenset({"candidate_schema", "product", "version", "tag", "channel", "commit", "image", "installer", "assets"})
ASSET_KEYS = frozenset({"role", "name", "size", "sha256"})


def validate_candidate(obj, *, limits=DEFAULT_LIMITS):
    """후보 기록의 모양·값 검사 → 문제들(없으면 빈 목록). 이름은 버전에서 계산한 값과 정확히 같아야 한다."""
    if not isinstance(obj, dict) or set(obj) != CANDIDATE_KEYS:
        return [_problem("candidate_keys")]
    version = obj["version"]
    kind = version_kind(version)
    checks = (
        (_is_int(obj["candidate_schema"]) and obj["candidate_schema"] == CANDIDATE_SCHEMA, "candidate_schema"),
        (obj["product"] == pc.EXE_NAME, "candidate_product"),
        (kind is not None, "candidate_version"),
        (kind is not None and obj["tag"] == tag_of(version), "candidate_tag"),
        (kind is not None and obj["channel"] == kind, "candidate_channel"),
        (isinstance(obj["commit"], str) and _COMMIT.fullmatch(obj["commit"]) is not None, "candidate_commit"),
    )
    for good, code in checks:
        if not good:
            return [_problem(code)]
    image, installer = obj["image"], obj["installer"]
    if not (isinstance(image, dict) and set(image) == {"name", "version"} and all(isinstance(image[key], str) and _IMAGE_WORD.fullmatch(image[key]) for key in image)):
        return [_problem("candidate_image")]
    if not (isinstance(installer, dict) and set(installer) == {"kind", "pack_id"} and installer["kind"] == INSTALLER_KIND and isinstance(installer["pack_id"], str)
            and _PACK_ID.fullmatch(installer["pack_id"])):
        return [_problem("candidate_installer")]
    assets = obj["assets"]
    names = asset_names(version)
    if not isinstance(assets, list) or len(assets) != len(ASSET_ROLES):
        return [_problem("candidate_assets")]
    seen = set()
    for item in assets:
        if not isinstance(item, dict) or set(item) != ASSET_KEYS or item["role"] not in names or item["role"] in seen:
            return [_problem("candidate_assets")]
        seen.add(item["role"])
        cap = limits.file if item["role"] in MANIFEST_ROLES else limits.support
        if item["name"] != names[item["role"]]:
            return [_problem("asset_name", item["name"] if isinstance(item["name"], str) else "")]
        if not _is_int(item["size"]) or not 1 <= item["size"] <= cap:
            return [_problem("asset_size", item["name"])]
        if not isinstance(item["sha256"], str) or _SHA256.fullmatch(item["sha256"]) is None:
            return [_problem("asset_sha256", item["name"])]
    if sum(item["size"] for item in assets if item["role"] in MANIFEST_ROLES) > limits.total:
        return [_problem("assets_total")]
    return []


def read_candidate(folder, *, limits=DEFAULT_LIMITS):
    """폴더의 후보 기록을 읽어 검사한다 → (기록 또는 None, 문제들)."""
    data = _read_limited(Path(folder) / CANDIDATE_NAME, MAX_CANDIDATE_BYTES)
    if data is None:
        return None, [_problem("candidate_unreadable")]
    obj = _load_json(data)
    if obj is None:
        return None, [_problem("candidate_json")]
    problems = validate_candidate(obj, limits=limits)
    return (None if problems else obj), problems


def verify_candidate(folder, *, phase=PHASE_CANDIDATE, limits=DEFAULT_LIMITS):
    """후보 폴더 검증(서명 잡의 `verify-candidate`) — 기록을 읽고, 폴더의 파일이 기록과 **정확히** 같은지(알 수 없는 파일 0·빠진 파일 0·크기·**다시 해시한 SHA-256**) 본다 → (기록 또는 None, 문제들).
    `phase` 가 `final` 이면 서명한 뒤의 폴더다: 매니페스트와 서명 파일이 더 있어도 되고, 해시 목록은 서명 뒤에 다시 쓰므로 기록과 견주지 않는다."""
    files, problems = list_files(folder)
    candidate, found = read_candidate(folder, limits=limits)
    problems += found
    if candidate is None:
        return None, problems
    allowed = {item["name"] for item in candidate["assets"]} | {CANDIDATE_NAME}
    if phase == PHASE_FINAL:
        allowed |= {MANIFEST_NAME, SIGNATURE_NAME}
    for name in files:
        if name not in allowed:
            problems.append(_problem("file_unexpected", name))
    for item in candidate["assets"]:
        path = files.get(item["name"])
        if path is None:
            problems.append(_problem("file_missing", item["name"]))
            continue
        if phase == PHASE_FINAL and item["role"] == ROLE_SUMS:
            continue
        size = path.stat().st_size
        if size != item["size"]:
            problems.append(_problem("asset_size_differs", item["name"]))
        elif pc.sha256_file(path) != item["sha256"]:
            problems.append(_problem("asset_hash_differs", item["name"]))
    return candidate, problems


# ---- 변경 이력·릴리스 노트(docs/RELEASE.md 릴리스 노트 규칙) ----------------------------------------------------------------------------------------------
def top_changelog_version(changelog):
    """`CHANGELOG.md` 맨 위 절의 버전(첫 `## [` 줄의 대괄호 안) 또는 None."""
    found = re.search(r"^## \[([^\]]+)\]", changelog, re.M)
    return found.group(1) if found else None


def notes_section(changelog, version):
    """그 버전의 절 → (머리 줄, 본문). 머리 줄이 정확히 하나여야 하고 절은 다음 `## [` 줄 앞까지다. 본문은 머리 줄을 뺀 글의 앞뒤 빈 줄을 지운 것(줄 끝 LF)."""
    lines = changelog.replace("\r\n", "\n").split("\n")
    heads = [index for index, line in enumerate(lines) if _HEADING.match(line) and _HEADING.match(line).group(1) == version]
    if len(heads) != 1:
        raise NotesError("heading_count")
    start = heads[0]
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## [")), len(lines))
    return lines[start], "\n".join(lines[start + 1:end]).strip("\n")


def _blocks(body):
    """본문을 필수 소제목(`### 요약`·`### 자세히`·`### 이관 노트`) 줄로 나눈다 → [(소제목, [그 아래 줄들])] — 다른 `### ` 줄은 앞 블록의 내용이다. 첫 필수 소제목 앞의 글은 소제목이 빈 글인 블록."""
    blocks, current = [], ("", [])
    for line in body.split("\n"):
        if line.rstrip() in REQUIRED_SECTIONS:
            blocks.append(current)
            current = (line.rstrip(), [])
        else:
            current[1].append(line)
    blocks.append(current)
    return [item for item in blocks if item[0] or any(text.strip() for text in item[1])]


def _filled(lines):
    return [line.rstrip() for line in lines if line.strip()]


def summary_of(body):
    """본문의 `### 요약` 블록 → 매니페스트 `notes.summary` 로 쓸 평문(빈 줄을 뺀 줄들을 LF 로 이은 글). 요약 블록이 없으면 NotesError."""
    for heading, lines in _blocks(body):
        if heading == SECTION_SUMMARY:
            return "\n".join(_filled(lines))
    raise NotesError("summary_missing")


def _forbidden_kind(text, *, hidden=False, allowed=SUMMARY_HIDDEN_ALLOWED):
    if chr(126) in text:
        return "tilde"
    if _URL.search(text):
        return "url"
    if "{" * 2 in text or "}" * 2 in text:
        return "braces"
    if "\r" in text:
        return "cr"
    if chr(0xFEFF) in text:
        return "bom"
    if any(shape.search(text) for shape in _KEY_SHAPES):
        return "key_shape"
    if hidden and any(unicodedata.category(char) in HIDDEN_CATEGORIES and char not in allowed for char in text):
        return "hidden_char"
    return ""


def notes_problems(heading, body, version):
    """릴리스 노트(변경 이력의 그 버전 절)의 모양 검사 → 문제들. 머리 줄은 정확히 `## [버전] — YYYY-MM-DD`, 소제목 `### 요약`·`### 자세히`·`### 이관 노트` 가 한 번씩 이 차례로 있고 비어 있지 않으며,
    요약은 3–10줄·500글자 이하, 절 전체는 20,000자 이하이고 물결표·웹 주소·이중 중괄호·키 모양·보이지 않는 글자가 없다. 보이지 않는 글자는 요약 칸에서는 앱의 규칙대로 줄바꿈만 빼고 모두 거절하고(`SUMMARY_HIDDEN_ALLOWED`),
    절 전체(머리 줄·자세히·이관 노트 포함)에서는 줄바꿈·탭·이모지 조합용 ZWJ 만 빼고 거절한다(`NOTES_HIDDEN_ALLOWED` — 제어 글자·방향 제어·폭 없는 공백·줄 구분 글자·사용자 영역 글자가 공개 릴리스 본문으로 가는 길을 막는다, 재작업 1·S-6)."""
    problems = []
    found = _NEW_HEADING.fullmatch(heading)
    if found is None or found.group(1) != version:
        problems.append(_problem("notes_heading", heading))
    if len(heading) + len(body) + 2 > MAX_NOTES_SECTION_CHARS:
        problems.append(_problem("notes_length"))
    kind = _forbidden_kind(heading + "\n" + body, hidden=True, allowed=NOTES_HIDDEN_ALLOWED)
    if kind:
        problems.append(_problem("notes_forbidden", kind))
    blocks = _blocks(body)
    order = [item[0] for item in blocks if item[0] in REQUIRED_SECTIONS]
    for section in REQUIRED_SECTIONS:
        if order.count(section) != 1:
            problems.append(_problem("notes_section_missing", section))
    if all(order.count(section) == 1 for section in REQUIRED_SECTIONS) and order != list(REQUIRED_SECTIONS):
        problems.append(_problem("notes_section_order"))
    for heading_line, lines in blocks:
        if heading_line in REQUIRED_SECTIONS and not _filled(lines):
            problems.append(_problem("notes_section_empty", heading_line))
    if order.count(SECTION_SUMMARY) == 1:
        lines = _filled(next(item[1] for item in blocks if item[0] == SECTION_SUMMARY))
        if not MIN_SUMMARY_LINES <= len(lines) <= MAX_SUMMARY_LINES:
            problems.append(_problem("summary_lines", str(len(lines))))
        if len("\n".join(lines)) > MAX_SUMMARY_CHARS:
            problems.append(_problem("summary_length"))
        if _forbidden_kind("\n".join(lines), hidden=True) == "hidden_char":
            problems.append(_problem("summary_chars"))
    return problems


def compose_body(notes):
    """릴리스 본문 = 변경 이력 절의 본문(글자 그대로) + 빈 줄 + 고정 안내 꼬리 + 줄바꿈 하나."""
    return notes + "\n\n" + FOOTER + "\n"


def split_body(text):
    """릴리스 본문 → (변경 이력 절의 본문, 꼬리). 꼬리가 고정 글과 다르거나 없으면 NotesError."""
    tail = "\n\n" + FOOTER + "\n"
    if not isinstance(text, str) or not text.endswith(tail):
        raise NotesError("footer")
    return text[:-len(tail)], FOOTER


def release_body(changelog, version):
    """변경 이력과 버전 → 릴리스 본문 글. 절을 못 고르거나 모양이 틀리면 `ChainError`/`NotesError`."""
    heading, notes = notes_section(changelog, version)
    problems = notes_problems(heading, notes, version)
    if problems:
        raise ChainError(problems)
    return compose_body(notes)


def body_matches_changelog(text, changelog, version):
    """릴리스 본문이 변경 이력의 그 버전 절에서 만든 글과 글자 그대로 같은가(공개 뒤 사후 확인에도 쓴다)."""
    try:
        notes, _tail = split_body(text)
        return notes == notes_section(changelog, version)[1]
    except NotesError:
        return False


# ---- 사슬 확인 -----------------------------------------------------------------------------------------------------------------------------------
def _app_modules():
    """앱의 매니페스트·정보 카드 코드(함수 안에서만 불러온다)."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from chanceblog_desktop.ui.core import version as app_version
    from chanceblog_desktop.update import manifest as app_manifest
    return app_manifest, app_version


def app_card_text(version):
    """앱이 `VERSION` 파일 내용에서 만드는 정보 카드의 버전 글 — 앱의 `read_version` 을 가짜 읽개로 부른다(다른 경로는 못 읽는다)."""
    _manifest, app_version = _app_modules()

    def reader(path):
        if Path(path).name == "VERSION":
            return version + "\n"
        raise OSError("not here")
    return app_version.read_version(Path("VERSION"), reader=reader).text


def _check_info(folder, version, candidate, files, problems):
    data = _read_limited(files[pc.INFO_JSON], MAX_INFO_BYTES) if pc.INFO_JSON in files else None
    info = _load_json(data) if data is not None else None
    if not isinstance(info, dict):
        problems.append(_problem("info_unreadable"))
        return
    if info.get("variant") != "outer":
        problems.append(_problem("info_variant"))
    if info.get("version") != version:
        problems.append(_problem("version_mismatch", "PACKAGE_INFO.json"))
    git = info.get("git")
    if not isinstance(git, dict) or git.get("commit") != candidate["commit"]:
        problems.append(_problem("info_commit"))
    package = info.get("package")
    zip_path = files.get(portable_name(version))
    if not isinstance(package, dict) or package.get("name") != portable_name(version):
        problems.append(_problem("info_package"))
    elif zip_path is not None and (package.get("sha256") != pc.sha256_file(zip_path) or package.get("bytes") != zip_path.stat().st_size):
        problems.append(_problem("info_package_hash"))
    if info.get("trial") is True:
        problems.append(_problem("info_trial"))
    if "release_eligible" in info and info["release_eligible"] is not True:
        problems.append(_problem("info_not_eligible"))
    channel = info.get("channel")
    if channel in (KIND_STABLE, KIND_RC) and channel != version_kind(version):
        problems.append(_problem("info_channel", str(channel)))
    if "artifacts" in info:
        _check_info_artifacts(info["artifacts"], candidate, problems)
    md = _read_limited(files[pc.INFO_MD], MAX_INFO_BYTES) if pc.INFO_MD in files else None
    if md is None or version not in md.decode("utf-8", "replace"):
        problems.append(_problem("version_mismatch", "PACKAGE_INFO.md"))


def _check_info_artifacts(artifacts, candidate, problems):
    """묶음 정보의 `artifacts`(설치 파일·휴대용 압축 파일의 이름·해시·크기)가 있으면 후보 기록과 같아야 한다."""
    wanted = {item["role"]: item for item in candidate["assets"] if item["role"] in MANIFEST_ROLES}
    if not isinstance(artifacts, dict) or set(artifacts) != set(wanted):
        problems.append(_problem("info_artifacts"))
        return
    for role, item in wanted.items():
        entry = artifacts[role]
        if not (isinstance(entry, dict) and entry.get("name") == item["name"] and entry.get("sha256") == item["sha256"] and entry.get("bytes") == item["size"]):
            problems.append(_problem("info_artifacts", role))


def _check_sums(files, problems):
    data = _read_limited(files[pc.SUMS_NAME], MAX_INFO_BYTES) if pc.SUMS_NAME in files else None
    if data is None:
        problems.append(_problem("sums_unreadable"))
        return
    entries, found = parse_sums(data)
    problems.extend(found)
    if found and not entries:
        return
    listed = {name: digest for name, digest in entries}
    expected = {name for name in files if name not in (pc.SUMS_NAME, CANDIDATE_NAME)}
    for name in sorted(expected - set(listed)):
        problems.append(_problem("sums_missing_line", name))
    for name in sorted(set(listed) - expected):
        problems.append(_problem("sums_extra_line", name))
    for name in sorted(expected & set(listed)):
        if pc.sha256_file(files[name]) != listed[name]:
            problems.append(_problem("sums_mismatch", name))


def _check_changelog(changelog_text, version, problems):
    if top_changelog_version(changelog_text) != version:
        problems.append(_problem("changelog_top", str(top_changelog_version(changelog_text))))
    try:
        heading, notes = notes_section(changelog_text, version)
    except NotesError:
        problems.append(_problem("changelog_section"))
        return
    problems.extend(notes_problems(heading, notes, version))


def _check_manifest(folder, version, candidate, files, problems):
    app_manifest, _app_version = _app_modules()
    data, sig = _read_limited(files[MANIFEST_NAME], app_manifest.MAX_MANIFEST_BYTES), _read_limited(files[SIGNATURE_NAME], 4096)
    if data is None or sig is None:
        problems.append(_problem("manifest_unreadable"))
        return
    try:
        found = app_manifest.validate_fields(app_manifest.read_structure(data), hashlib.sha256(data).hexdigest(), channels=app_manifest.CHANNELS_OFFLINE)
        app_manifest.read_signature(sig)
    except app_manifest.ManifestError as error:
        problems.append(_problem("manifest_rejected", error.reason))
        return
    if found.version != version:
        problems.append(_problem("version_mismatch", MANIFEST_NAME))
    if found.tag != tag_of(version):
        problems.append(_problem("tag_mismatch", MANIFEST_NAME))
    if found.channel != version_kind(version):
        problems.append(_problem("channel_mismatch", MANIFEST_NAME))
    if found.commit != candidate["commit"]:
        problems.append(_problem("manifest_commit"))
    if (found.installer_kind, found.pack_id) != (candidate["installer"]["kind"], candidate["installer"]["pack_id"]):
        problems.append(_problem("manifest_installer"))
    wanted = sorted((item["role"], item["name"], item["size"], item["sha256"]) for item in candidate["assets"] if item["role"] in MANIFEST_ROLES)
    if sorted((item.role, item.name, item.size, item.sha256) for item in found.files) != wanted:
        problems.append(_problem("manifest_files"))


def _loose_versions(files, version, problems):
    """설치 파일·압축 파일 이름에 든 버전이 다르면 '한 곳만 버전이 다름' 으로 알린다(이름이 틀린 것과 따로 보이게)."""
    for name in files:
        for pattern in (r"ChanceBlogDesktop-(.+)-Setup\.exe", r"ChanceBlogDesktop-(.+)-win64\.zip"):
            found = re.fullmatch(pattern, name)
            if found and found.group(1) != version:
                problems.append(_problem("version_mismatch", name))


def check_chain(folder, version, *, commit=None, changelog_text=None, phase=PHASE_CANDIDATE, limits=DEFAULT_LIMITS, check_card=True):
    """`release/` 폴더가 `version` 의 사슬을 지키는지 본다 → 문제들(빈 목록이면 통과).
    ① 버전 모양(정식·후보) ② 파일 이름과 개수(정해진 것만·빠진 것 없음·링크 없음) ③ 후보 기록(모양·태그·채널·커밋)과 파일의 **다시 해시한** 값 ④ `PACKAGE_INFO` 의 버전·커밋·압축 파일 이름과 해시(`artifacts` 가 있으면 같음)
    ⑤ `SHA256SUMS` 가 모든 파일을 한 줄씩 ⑥ 변경 이력 맨 위 절 = 버전이고 노트 모양이 맞음(`changelog_text` 를 주었을 때) ⑦ 서명한 뒤(`final`)에는 매니페스트가 앱의 규칙을 지키고 후보 기록과 같음 ⑧ 앱 정보 카드 글."""
    folder = Path(folder)
    kind = version_kind(version)
    if kind is None:
        return [_problem("version_shape", version if isinstance(version, str) else "")]
    files, _listed = list_files(folder)
    candidate, problems = verify_candidate(folder, phase=phase, limits=limits)
    _loose_versions(files, version, problems)
    if kind == KIND_STABLE and any(word in name for name in files for word in PRERELEASE_WORDS):
        problems.append(_problem("prerelease_word"))
    if phase == PHASE_FINAL:
        for name in (MANIFEST_NAME, SIGNATURE_NAME):
            if name not in files:
                problems.append(_problem("file_missing", name))
    if candidate is None:
        return problems
    if candidate["version"] != version:
        problems.append(_problem("version_mismatch", CANDIDATE_NAME))
    if commit is not None and candidate["commit"] != commit:
        problems.append(_problem("commit_mismatch"))
    if set(asset_names(version).values()) <= set(files):
        _check_info(folder, version, candidate, files, problems)
        _check_sums(files, problems)
    if changelog_text is not None:
        _check_changelog(changelog_text, version, problems)
    if phase == PHASE_FINAL and MANIFEST_NAME in files and SIGNATURE_NAME in files:
        _check_manifest(folder, version, candidate, files, problems)
    if check_card and app_card_text(version) != card_text(version):
        problems.append(_problem("card_mismatch"))
    return problems


# ---- 모으기(assemble) ----------------------------------------------------------------------------------------------------------------------------
def _gather(version, sources):
    """원본 폴더들에서 필요한 네 파일(설치 파일·압축 파일·묶음 정보 둘)을 찾는다 → ({역할: 경로}, 문제들). 이름이 비슷한데 다른 버전인 낡은 산출물이 있으면 거절한다."""
    names = asset_names(version)
    wanted = {role: names[role] for role in (ROLE_SETUP, ROLE_PORTABLE, ROLE_INFO_JSON, ROLE_INFO_MD)}
    found, problems = {}, []
    for source in sources:
        files, listed = list_files(source)
        problems += [item for item in listed if item.code != "file_not_regular"]
        for name in sorted(files):
            if _STALE_ASSET.match(name) and name not in wanted.values():
                problems.append(_problem("stale_asset", name))
        for role, name in wanted.items():
            path = files.get(name)
            if path is None:
                continue
            if role in found and pc.sha256_file(found[role]) != pc.sha256_file(path):
                problems.append(_problem("source_conflict", name))
            found.setdefault(role, path)
    for role, name in wanted.items():
        if role not in found:
            problems.append(_problem("file_missing", name))
    return found, problems


def assemble(version, sources, out_dir, *, commit, image, changelog_text=None, pack_id=DEFAULT_PACK_ID, limits=DEFAULT_LIMITS):
    """원본 폴더들에서 `out_dir`(없거나 빈 폴더)로 파일을 모으고 `SHA256SUMS`·`release_candidate.json` 을 쓴 뒤 사슬을 확인한다 → 후보 기록. 문제가 있으면 후보 기록을 지우고 `ChainError`."""
    if version_kind(version) is None:
        raise ChainError([_problem("version_shape", version if isinstance(version, str) else "")])
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise ChainError([_problem("candidate_commit")])
    out_dir = Path(out_dir)
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise ChainError([_problem("out_not_empty")])
    found, problems = _gather(version, sources)
    if problems:
        raise ChainError(problems)
    out_dir.mkdir(parents=True, exist_ok=True)
    names = asset_names(version)
    for role, path in found.items():
        shutil.copyfile(path, out_dir / names[role])
    write_sums(out_dir)
    candidate = build_candidate(out_dir, version, commit=commit, image=image, pack_id=pack_id)
    (out_dir / CANDIDATE_NAME).write_bytes(render_candidate(candidate))
    problems = check_chain(out_dir, version, commit=commit, changelog_text=changelog_text, limits=limits)
    if problems:
        try:
            (out_dir / CANDIDATE_NAME).unlink()
        except OSError:
            pass
        raise ChainError(problems)
    return candidate


# ---- 명령줄 -----------------------------------------------------------------------------------------------------------------------------------------
def _version_from(path):
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None
    return read_version_file(raw)


def _changelog_from(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None


def _detect_commit(environ, run, root):
    value = environ.get("GITHUB_SHA", "")
    if _COMMIT.fullmatch(value):
        return value
    try:
        done = run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (done.stdout or "").strip() if done.returncode == 0 else ""
    return value if _COMMIT.fullmatch(value) else None


def _image_from(args, environ):
    name = args.image_name or environ.get("ImageOS") or "unknown"
    version = args.image_version or environ.get("ImageVersion") or "unknown"
    return name, version


def _print_problems(problems, err):
    for item in problems:
        err.write("문제: " + describe(item) + "\n")


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError()


def _build_parser():
    parser = _Parser(add_help=False, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    default_version, default_changelog = str(ROOT / "VERSION"), str(ROOT / "CHANGELOG.md")
    first = sub.add_parser("assemble")
    first.add_argument("--version-file", default=default_version)
    first.add_argument("--source", action="append", required=True)
    first.add_argument("--out", default="release")
    first.add_argument("--commit", default=None)
    first.add_argument("--changelog", default=default_changelog)
    first.add_argument("--image-name", default=None)
    first.add_argument("--image-version", default=None)
    first.add_argument("--pack-id", default=DEFAULT_PACK_ID)
    second = sub.add_parser("check")
    second.add_argument("--dir", required=True)
    second.add_argument("--version-file", default=default_version)
    second.add_argument("--changelog", default=default_changelog)
    second.add_argument("--commit", default=None)
    second.add_argument("--phase", choices=(PHASE_CANDIDATE, PHASE_FINAL), default=PHASE_CANDIDATE)
    third = sub.add_parser("sums")
    third.add_argument("--dir", required=True)
    fourth = sub.add_parser("notes")
    fourth.add_argument("--version-file", default=default_version)
    fourth.add_argument("--changelog", default=default_changelog)
    fourth.add_argument("--out", required=True)
    fifth = sub.add_parser("names")
    fifth.add_argument("--version-file", default=default_version)
    return parser


def _cmd_assemble(args, environ, out, err, run):
    version = _version_from(args.version_file)
    changelog = _changelog_from(args.changelog)
    commit = args.commit if args.commit is not None else _detect_commit(environ, run, ROOT)
    if version is None or changelog is None or commit is None:
        err.write("모으지 못했다: VERSION·변경 이력·커밋을 읽지 못했거나 버전 글이 정식(X.Y.Z)·후보(X.Y.Z-rc.N) 모양이 아니다.\n")
        return EXIT_USAGE
    image = _image_from(args, environ)
    try:
        candidate = assemble(version, args.source, args.out, commit=commit, image=image, changelog_text=changelog, pack_id=args.pack_id)
    except ChainError as error:
        err.write("모으지 못했다: 사슬 확인에서 문제가 있다.\n")
        _print_problems(error.problems, err)
        return EXIT_PROBLEMS
    out.write(f"모았다: 버전 {candidate['version']} · 태그 {candidate['tag']} · 파일 {len(candidate['assets'])}개 + 후보 기록\n")
    for item in candidate["assets"]:
        out.write(f"- {item['name']} {item['size']}바이트 {item['sha256']}\n")
    return EXIT_OK


def _cmd_check(args, out, err):
    version = _version_from(args.version_file)
    changelog = _changelog_from(args.changelog)
    if version is None or changelog is None:
        err.write("확인하지 못했다: VERSION 또는 변경 이력을 읽지 못했거나 버전 글이 정식·후보 모양이 아니다.\n")
        return EXIT_USAGE
    problems = check_chain(args.dir, version, commit=args.commit, changelog_text=changelog, phase=args.phase)
    if problems:
        err.write("사슬에 문제가 있다.\n")
        _print_problems(problems, err)
        return EXIT_PROBLEMS
    out.write(f"사슬이 맞다: 버전 {version} · 태그 {tag_of(version)} · 단계 {args.phase}\n")
    return EXIT_OK


def _cmd_sums(args, out, err):
    try:
        text = write_sums(args.dir)
    except (ChainError, OSError):
        err.write("해시 목록을 쓰지 못했다: 폴더를 읽지 못했거나 일반 파일이 아닌 것이 있다.\n")
        return EXIT_USAGE
    out.write(f"SHA256SUMS 를 다시 썼다: 파일 {len(text.splitlines())}개\n")
    return EXIT_OK


def _cmd_notes(args, out, err):
    version = _version_from(args.version_file)
    changelog = _changelog_from(args.changelog)
    if version is None or changelog is None:
        err.write("만들지 못했다: VERSION 또는 변경 이력을 읽지 못했거나 버전 글이 정식·후보 모양이 아니다.\n")
        return EXIT_USAGE
    try:
        body = release_body(changelog, version)
    except NotesError:
        err.write("만들지 못했다: 변경 이력에서 그 버전의 절을 정확히 하나 찾지 못했다.\n")
        return EXIT_PROBLEMS
    except ChainError as error:
        err.write("만들지 못했다: 릴리스 노트의 모양이 틀리다.\n")
        _print_problems(error.problems, err)
        return EXIT_PROBLEMS
    try:
        Path(args.out).write_bytes(body.encode("utf-8"))
    except OSError:
        err.write("만들지 못했다: 본문 파일을 쓰지 못했다.\n")
        return EXIT_USAGE
    out.write(f"릴리스 본문을 썼다: 제목 {title_of(version)} · {len(body)}글자\n")
    return EXIT_OK


def _cmd_names(args, out, err):
    version = _version_from(args.version_file)
    if version is None:
        err.write("보이지 못했다: VERSION 을 읽지 못했거나 버전 글이 정식·후보 모양이 아니다.\n")
        return EXIT_USAGE
    out.write("\n".join((f"tag={tag_of(version)}", f"title={title_of(version)}", f"channel={channel_of(version)}", f"prerelease={'true' if channel_of(version) == KIND_RC else 'false'}",
                         f"setup={setup_name(version)}", f"portable={portable_name(version)}")) + "\n")
    return EXIT_OK


def main(argv=None, *, environ=None, stdout=None, stderr=None, run=subprocess.run):
    """명령줄 진입점. 시험이 `environ`·`stdout`·`stderr`·`run` 을 바꿔 끼운다."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    env = os.environ if environ is None else environ
    try:
        args = _build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    except _UsageError:
        err.write("사용법 오류: assemble --source 폴더 [--out 폴더] · check --dir 폴더 · sums --dir 폴더 · notes --out 파일 · names 중 하나를 쓴다.\n")
        return EXIT_USAGE
    if args.command == "assemble":
        return _cmd_assemble(args, env, out, err, run)
    if args.command == "check":
        return _cmd_check(args, out, err)
    if args.command == "sums":
        return _cmd_sums(args, out, err)
    if args.command == "notes":
        return _cmd_notes(args, out, err)
    return _cmd_names(args, out, err)


if __name__ == "__main__":
    sys.exit(main())
