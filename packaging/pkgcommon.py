"""개인 PC 제한 시험용 Package 의 공통 상수·작은 부품 — 빌드 도구(`build_package.py`·`make_manifest.py`)와 묶음의 시작 파일(`gui_entry.py`)이 같이 쓴다.

표준 라이브러리만 쓴다(묶음 실행 파일 안에도 들어가므로 가볍게 둔다). 시계·무작위·네트워크가 없다.
이름과 문구를 한곳에 두는 까닭: 빌드가 만드는 파일 이름·`PACKAGE_INFO.json` 의 칸·묶음 안 `--selftest` 가 찾는 이름이 어긋나면 '빌드는 되는데 실행하면 막히는' 묶음이 나온다.
"""
from __future__ import annotations

import ast
import hashlib
import re
import sys
from pathlib import Path

PRODUCT = "ChanceBlog Desktop"
EXE_NAME = "ChanceBlogDesktop"                    # 실행 파일 이름(`.exe` 는 윈도에서 붙는다) — 데이터 폴더 `ChanceblogDesktop`(소문자 b)과 글자 하나 다르다(D-1 M7: 이름 유지)
CHANNEL = "personal-pc-preview"                   # 이 묶음의 갈래 — `PACKAGE_INFO.json` 의 `channel` 이고 화면 '정보' 카드의 한 줄을 켠다
NOTICE = "개인 PC 제한 시험용, 미서명 Package"
NOTICE_LONG = NOTICE + " — 공개 배포용이 아닙니다"
TRIAL_TAG = "TESTBUILD"                           # 시험 빌드(관문 모듈이 아직 없는 소스를 `--allow-missing-gate` 로 만든 것)의 압축 파일·묶음 폴더 이름에 붙는 낱말 — 개인 PC 로 보내지 않는 빌드를 이름만 봐도 알아보게 한다(D-416)
TRIAL_NOTICE = "시험 빌드 — 개인 PC 로 보내지 않는 빌드예요"      # 화면 '정보' 카드의 시험 빌드 표시 — `ui/core/version.py` 의 PACKAGE_TRIAL_NOTICE 와 같다(시험이 같음을 지킨다)
GATE_MISSING_TEXT = "외부 쓰기 관문(capabilities) 모듈이 없어요"    # `--selftest` 의 capabilities 점검이 '모듈 자체가 없을 때' 쓰는 글의 앞부분 — `--allow-missing-gate` 는 이 글로 시작하는 실패만 넘긴다(D-419)
SCHEMA = 1
INFO_JSON = "PACKAGE_INFO.json"
INFO_MD = "PACKAGE_INFO.md"
SUMS_NAME = "SHA256SUMS"
LICENSES_DIR = "LICENSES"
# 묶음 안 LICENSES 폴더에 꼭 있어야 하는 파일 — 빌드가 만들고 `--selftest` 가 확인한다
LICENSE_FILES = ("LGPL-3.0.txt", "GPL-3.0.txt", "PYTHON-LICENSE.txt", "PYINSTALLER-COPYING.txt", "THIRD_PARTY_NOTICES.md")
FILES_EXCLUDED_FROM_LIST = (INFO_JSON, INFO_MD)   # 자기 자신의 해시를 자기 안에 적을 수 없으니 목록에서 뺀다
VERSION_PATTERN = r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?"       # `ui/core/version.py` 의 `_NUMBER` 와 같다(시험이 같음을 지킨다)
_VERSION = re.compile(VERSION_PATTERN)
BOM = chr(0xFEFF)                                  # UTF-8 BOM(메모장이 맨 앞에 붙이는 보이지 않는 글자) — 소스에는 가시 글자 대신 chr() 를 쓴다
# 저장소 시험(`tests/test_repo_layout.py`)의 키 모양과 같은 목록 — 묶음 안 글 파일에 키 모양이 없는지 빌드가 훑을 때 쓴다
KEY_SHAPES = (
    r"AIza[0-9A-Za-z_-]{35}",
    r"(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}",
    r"[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}",
    r"GOCSPX-[A-Za-z0-9_-]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"sk-[A-Za-z0-9]{32,}|gsk_[A-Za-z0-9]{40,}",
)
# 묶음 안에 있으면 안 되는 파일 이름(사용자 데이터·비밀 파일 모양) — 소문자로 비교한다
FORBIDDEN_NAMES = ("settings.json", "connections.json", "quota_state.json", "chanceblog.db", "channel_profiles.json", "seeds.json", "calendar.json", "topic_engine.db", "restore-in-progress.json")
# 앱이 읽지 못한 데이터 파일을 옮겨 둔 사본(`settings.json.bak`)·저장소 구조를 올릴 때의 사본(`chanceblog.db.v1.bak`·`.v1.2.bak`)·쓰다 만 임시 파일(`.tmp`)도 같은 데이터다
COPY_SUFFIX = re.compile(r"(?:\.v[0-9][0-9.]*)?\.(?:bak|tmp)$")
FORBIDDEN_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".jks", ".keystore", ".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")
FORBIDDEN_PREFIXES = (".env", "client_secret", "credentials", "token", "secret", "id_rsa", "id_ed25519", ".netrc", ".git-credentials")
CODE_SUFFIXES = (".py", ".pyi", ".pyc", ".pyd", ".dll", ".exe", ".md", ".qm")      # 코드·문서·실행 파일은 이름이 비슷해도 비밀 파일이 아니다(예: vendor/pipeline/secret_patterns.py)


def top_folder(version, trial=False):
    """압축을 풀면 생기는 폴더 하나의 이름 — 압축 파일 이름에서 `-win64.zip` 을 뺀 것(데이터 폴더 `ChanceblogDesktop` 과 같은 이름이 되지 않는다).
    시험 빌드면 버전 뒤에 `-TESTBUILD` 가 붙는다."""
    return f"{EXE_NAME}-{version}-{TRIAL_TAG}" if trial else f"{EXE_NAME}-{version}"


def zip_name(version, trial=False):
    """압축 파일 이름 — `ChanceBlogDesktop-0.1.0-preview.1-win64.zip`, 시험 빌드는 `ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD-win64.zip`."""
    return f"{top_folder(version, trial)}-win64.zip"


def parse_version_text(raw):
    """VERSION 파일 내용 → 번호 또는 None(앞뒤 공백·줄바꿈·맨 앞 BOM 만 허용 — `ui/core/version.py` 와 같은 규칙)."""
    if not isinstance(raw, str):
        return None
    number = raw.lstrip(BOM).strip()
    return number if _VERSION.fullmatch(number) else None


def stdlib_imports(source):
    """파이썬 소스 글에서 표준 모듈 이름(점이 있으면 점까지)을 모은다 — 실행하지 않는다(구문 분석만). 묶음 도구가 vendor 파일이 쓰는 표준 모듈을 찾는 데 쓴다."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    return sorted(name for name in names if name.split(".")[0] in stdlib)


def sha256_file(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def forbidden_name(relative):
    """묶음 안에 둘 수 없는 이름이면 이유 글, 아니면 ''. `relative` 는 `/` 로 나눈 상대 경로."""
    name = Path(relative).name.lower()
    if name in FORBIDDEN_NAMES or COPY_SUFFIX.sub("", name) in FORBIDDEN_NAMES:
        return "사용자 데이터 파일 이름"
    if name.endswith(FORBIDDEN_SUFFIXES):
        return "비밀·데이터 파일 확장자"
    if name.startswith(FORBIDDEN_PREFIXES) and not name.endswith(CODE_SUFFIXES):
        return "비밀 파일 이름"
    return ""
