"""개인 PC 제한 시험용 Package 의 공통 상수·작은 부품 — 빌드 도구(`build_package.py`·`make_manifest.py`)와 묶음의 시작 파일(`gui_entry.py`)이 같이 쓴다.

표준 라이브러리만 쓴다(묶음 실행 파일 안에도 들어가므로 가볍게 둔다). 시계·무작위·네트워크가 없다.
이름과 문구를 한곳에 두는 까닭: 빌드가 만드는 파일 이름·`PACKAGE_INFO.json` 의 칸·묶음 안 `--selftest` 가 찾는 이름이 어긋나면 '빌드는 되는데 실행하면 막히는' 묶음이 나온다.
"""
from __future__ import annotations

import ast
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

PRODUCT = "ChanceBlog Desktop"
EXE_NAME = "ChanceBlogDesktop"                    # 실행 파일 이름(`.exe` 는 윈도에서 붙는다) — 데이터 폴더 `ChanceblogDesktop`(소문자 b)과 글자 하나 다르다(D-1 M7: 이름 유지)
CHANNEL = "personal-pc-preview"                   # 이 묶음의 갈래 — `PACKAGE_INFO.json` 의 `channel` 이고 화면 '정보' 카드의 한 줄을 켠다
NOTICE = "개인 PC 제한 시험용, 미서명 Package"
NOTICE_LONG = NOTICE + " — 공개 배포용이 아닙니다"
TRIAL_TAG = "TESTBUILD"                           # 시험 빌드(관문 모듈이 아직 없는 소스를 `--allow-missing-gate` 로 만든 것)의 압축 파일·묶음 폴더 이름에 붙는 낱말 — 개인 PC 로 보내지 않는 빌드를 이름만 봐도 알아보게 한다(D-416)
TRIAL_NOTICE = "시험 빌드 — 개인 PC 로 보내지 않는 빌드예요"      # 화면 '정보' 카드의 시험 빌드 표시 — `ui/core/version.py` 의 PACKAGE_TRIAL_NOTICE 와 같다(시험이 같음을 지킨다)
GATE_MISSING_TEXT = "외부 쓰기 관문(capabilities) 모듈이 없어요"    # `--selftest` 의 capabilities 점검이 '모듈 자체가 없을 때' 쓰는 글의 앞부분 — `--allow-missing-gate` 는 이 글로 시작하는 실패만 넘긴다(D-419)
# 소스 상수 스위치의 출하 표(NET 설계서 3.3, D-722). 점검 도구가 읽는 곳이라 이 파일에 둔다. 켜는 변경은 `capabilities.py` 의 상수 한 줄 + 이 표 한 줄이고, 켜는 확인(번호 있는 승인)을 받은 것만 더한다.
GATE_CONSTANTS = ("EXTERNAL_WRITE", "BLOGGER_OAUTH_INPUT", "LOCAL_OCR", "NET_UPDATE_CHECK", "NET_PAGES_SITE", "PAGES_BRANCH_PUSH", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT", "UPDATE_APPLY")   # `capabilities.SWITCH_NAMES` 와 같다(시험이 같음을 지킨다) — 점검이 소스의 표만 믿지 않게 한 벌 더 둔다
SHIPPED_OPEN_SWITCHES = ()                        # 켜진 채 내보내도 되는 스위치 이름 — 지금은 빈 표(모두 꺼진 채 출하한다). `--selftest` 는 켜진 상수의 집합이 이 표와 정확히 같을 때만 통과한다
INFORMATIONAL_SWITCHES = ("LOCAL_OCR",)           # 켜져 있어도 알림 줄일 뿐 실패 조건이 아닌 스위치(이 PC 안 계산이라 바깥에 쓰지 않는다 — D-512). 옛 모듈에 없어도 통과한다
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


# ---- 설치 파일(Inno Setup) — 이름·ID·인자의 단일 출처(V1INSTALL, 결정 D-830 이후) -------------------------------
# 이 파일은 `packaging/` 도구와 시험이 읽는 단일 출처다. 앱 소스(`src/`)는 이 폴더를 불러오지 못하고 이 파일도 앱을 불러오지 못하므로(표준 라이브러리만),
# UPDATE U-4(설치 도구 어댑터)가 같은 무음 인자를 `src/` 쪽에 따로 두고 두 값이 같음을 지키는 시험(`VERSION_PATTERN`·`ui/core/version.py` 와 같은 방식)을 더해야 한다.
INSTALLER_TOOL = "inno-setup"                      # 바깥 정보의 `installer.tool` 값
SETUP_SUFFIX = "-Setup.exe"                        # 설치 파일 이름의 끝 — `ChanceBlogDesktop-<버전>-Setup.exe`
INSTALL_DIR_NAME = "ChanceBlogDesktop"             # 설치 폴더 이름(`DefaultDirName={autopf}\ChanceBlogDesktop` — 사용자 권한이면 `%LocalAppData%\Programs\ChanceBlogDesktop`) — 제품·실행 파일 이름과 같다
DATA_DIR_NAME = "ChanceblogDesktop"                # 데이터 폴더 이름(소문자 b) — 앱의 `service/context.py` `APP_DIR_NAME` 과 같다(시험이 같음을 지킨다). 설치 폴더 이름과 대소문자만 다르다
INNO_PROGRAMS_FOLDER = "Programs"                  # 사용자 권한 설치에서 `{autopf}` 가 가리키는 `%LocalAppData%` 아래 폴더
INNO_PUBLISHER = "ChanceBlog"                      # 설치 파일의 게시자 칸 — 개인 이름을 넣지 않는다
INNO_MIN_VERSION = (6, 5, 0)                       # 한국어 안내 파일(Korean.isl)이 들어 있는 첫 Inno Setup 판(결정 D-810) — 더 낮거나 판을 읽지 못하면 빌드를 거절한다(위협 T11)
INNO_APP_GUID = "CF5B18A9-6CBC-4916-9978-7729E88B70C8"   # 이 갈래가 한 번 만든 영구 고정 GUID — 바꾸면 같은 앱의 새 판이 아니라 별개 앱으로 설치된다
INNO_APP_ID = "{" * 2 + INNO_APP_GUID + "}"        # `.iss` 의 AppId 줄에 적는 글 — Inno 는 여는 중괄호를 두 번 써야 글자 하나로 읽는다(닫는 중괄호는 하나)
INNO_UNINSTALLER_NAME = "unins000.exe"             # Inno 가 설치 폴더에 두는 제거 프로그램 이름(설치 종류 감지·제거 명령에 쓴다)
INNO_SILENT_INSTALL_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-")      # 무음 설치 — 러너 측정(M05·M19)에서 확인한 인자. `/DIR=`·`/LOG=`·`/LANG=` 은 부르는 쪽이 따로 붙인다
INNO_UPDATE_EXTRA_ARGS = ("/CLOSEAPPLICATIONS",)   # 업데이트 호출이 무음 설치 인자에 더하는 것 — 켜져 있는 앱을 Setup 이 닫게 한다(UPDATE 설계서 3-8). 앱이 먼저 끝나는 호출과 함께 쓴다
INNO_SILENT_UPDATE_ARGS = INNO_SILENT_INSTALL_ARGS + INNO_UPDATE_EXTRA_ARGS
INNO_SILENT_UNINSTALL_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")            # 무음 제거(`unins000.exe` 에 준다) — 러너 측정(M12)에서 확인. 데이터 폴더·자격 증명은 지워지지 않는다
SETUP_NOT_TRIAL_TEXT = "시험 빌드(TESTBUILD)에는 설치 파일을 만들지 않아요."
_INSTALL_PROBLEM_UNREADABLE = "폴더 경로를 읽을 수 없어요 — 비어 있거나 드라이브 글자로 시작하는 전체 경로가 아니어서 설치 폴더와 데이터 폴더가 겹치는지 확인하지 못했어요."
_INSTALL_PROBLEM_SAME = "설치 폴더와 데이터 폴더가 같은 폴더예요(윈도는 대소문자·끝의 점·공백을 같게 봐요) — 제거하거나 다시 설치할 때 데이터가 지워질 수 있어요."
_INSTALL_PROBLEM_INSTALL_INSIDE = "설치 폴더가 데이터 폴더 안에 있어요 — 설치와 제거가 데이터 폴더 안을 건드려요."
_INSTALL_PROBLEM_DATA_INSIDE = "데이터 폴더가 설치 폴더 안에 있어요 — 설치·제거·업데이트가 데이터에 닿아요."


def top_folder(version, trial=False):
    """압축을 풀면 생기는 폴더 하나의 이름 — 압축 파일 이름에서 `-win64.zip` 을 뺀 것(데이터 폴더 `ChanceblogDesktop` 과 같은 이름이 되지 않는다).
    시험 빌드면 버전 뒤에 `-TESTBUILD` 가 붙는다."""
    return f"{EXE_NAME}-{version}-{TRIAL_TAG}" if trial else f"{EXE_NAME}-{version}"


def zip_name(version, trial=False):
    """압축 파일 이름 — `ChanceBlogDesktop-0.1.0-preview.1-win64.zip`, 시험 빌드는 `ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD-win64.zip`."""
    return f"{top_folder(version, trial)}-win64.zip"


def setup_name(version, trial=False):
    """설치 파일 이름 — `ChanceBlogDesktop-0.1.0-preview.1-Setup.exe`. **시험 빌드(TESTBUILD)에는 설치 파일을 만들지 않으므로** `trial` 이 참이면 이름을 만들지 않고 ValueError 다.
    버전은 `VERSION_PATTERN` 에 통째로 맞아야 한다(이 이름이 명령줄·파일 이름에 들어가므로 따옴표·공백·경로 구분자가 든 글을 거절한다)."""
    if trial:
        raise ValueError(SETUP_NOT_TRIAL_TEXT)
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("버전 모양이 아니어서 설치 파일 이름을 만들지 않아요.")
    return f"{EXE_NAME}-{version}{SETUP_SUFFIX}"


def default_install_dir(local_appdata):
    """사용자 권한 설치의 기본 설치 폴더 — `<LocalAppData>\\Programs\\ChanceBlogDesktop`(윈도 글)."""
    return str(local_appdata).rstrip("\\/") + "\\" + INNO_PROGRAMS_FOLDER + "\\" + INSTALL_DIR_NAME


def default_data_dir(local_appdata):
    """앱의 기본 데이터 폴더 — `<LocalAppData>\\ChanceblogDesktop`(윈도 글)."""
    return str(local_appdata).rstrip("\\/") + "\\" + DATA_DIR_NAME


def _folder_parts(value):
    """폴더 글 → 겹침을 견주는 조각 목록(맨 앞은 드라이브 또는 서버·공유), 읽을 수 없으면 None. 윈도 규칙으로 본다 — 대소문자·유니코드 정규화(NFKC)·`/`·`.`·`..`·겹친 구분자·이름 끝의 점과 공백을 무시한다.
    `\\\\?\\` 확장 경로 접두어는 뗀다. 상대 경로·드라이브 없는 경로·`C:` 만 있는 글은 읽을 수 없다. 짧은 이름(8.3)·링크·정션은 풀지 않는다(글자만 본다)."""
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        return None
    text = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", value.strip()).casefold()).replace("/", "\\")
    unc = False
    for long_prefix in ("\\" * 2 + "?" + "\\", "\\" * 2 + "." + "\\"):                     # 확장 경로·장치 경로 접두어
        if text.startswith(long_prefix):
            text = text[len(long_prefix):]
            if text.startswith("unc\\"):
                text, unc = "\\" * 2 + text[len("unc\\"):], True
            break
    unc = unc or (text.startswith("\\" * 2) and not text.startswith("\\" * 3))
    if unc:
        names = [name for name in text.split("\\") if name]
        if len(names) < 2:
            return None                                                      # 서버 이름만 있고 공유 이름이 없다
        root, rest = ["\\" * 2, names[0], names[1]], names[2:]
    else:
        match = re.match(r"^([a-z]):\\(.*)$", text, re.S)
        if match is None:
            return None                                                      # 드라이브 글자로 시작하는 전체 경로가 아니다
        root, rest = [match.group(1) + ":"], match.group(2).split("\\")
    parts = []
    for name in rest:
        if name in ("", "."):
            continue
        if name == "..":
            if parts:
                parts.pop()
            continue
        name = name.rstrip(" .")                                            # 윈도는 이름 끝의 점과 공백을 말없이 지운다
        if name:
            parts.append(name)
    return root + parts


def install_dir_problem(install_dir, data_dir):
    """설치 폴더와 데이터 폴더가 겹치면 문제 글, 아니면 ''. 같거나 **한쪽이 다른 쪽 안에 들면** 겹친다(윈도 규칙으로 — 대소문자·끝의 점·공백·슬래시·`..`·유니코드 정규화를 무시하고, 경계는 폴더 이름 단위라
    `ChanceblogDesktop2` 는 `ChanceblogDesktop` 안이 아니다). 읽을 수 없는 값(비었음·전체 경로 아님)도 문제다. 문제 글은 고정 문장이라 입력한 경로를 되풀이하지 않는다."""
    install, data = _folder_parts(install_dir), _folder_parts(data_dir)
    if install is None or data is None:
        return _INSTALL_PROBLEM_UNREADABLE
    if install == data:
        return _INSTALL_PROBLEM_SAME
    if data[:len(install)] == install:
        return _INSTALL_PROBLEM_DATA_INSIDE
    if install[:len(data)] == data:
        return _INSTALL_PROBLEM_INSTALL_INSIDE
    return ""


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
