"""릴리스 후보 점검(결정 D-670 이후) — 앱 v1.0 완료 기준 열두 항목(`docs/DECISIONS.md` '1.0.0 완료 기준')이 채워졌는지 한 번에 표로 보여 준다.

쓰는 법(저장소 맨 위 폴더에서):
    python -X utf8 scripts/release_check.py                      열두 항목 표
    python -X utf8 scripts/release_check.py --scan-dir 폴더 [--scan-dir 폴더 ...]
                                                                 후보 산출물 폴더(설치 파일 푼 것·zip 푼 것·로그·백업·진단 복사본)의 키·토큰 모양 훑기를 10번 항목에 반영
    python -X utf8 scripts/release_check.py --json               같은 결과를 JSON 으로
    python -X utf8 scripts/release_check.py --root 폴더           다른 저장소 사본을 점검(시험용 — 열두 점검을 부르느라 그 사본의 packaging/gui_entry.py 와 앱 코드가 실행되므로 믿는 사본에만 쓴다)

지키는 것:
  · **읽기 전용**이다. 파일을 만들거나 바꾸지 않고, 네트워크·하위 프로세스를 쓰지 않는다(표준 라이브러리와 앱의 `security/scan.py` 만 쓴다).
    단 자가 점검(`--selftest` 열두 항목)은 함수로 불러 돌리는데, 그 함수가 원래 하는 대로 시스템 임시 폴더에 빈 폴더를 잠깐 만들었다 지운다.
  · **'선언'을 하지 않는다.** 결과를 보여 줄 뿐이고 v1.0 을 선언하는 것은 운영자 몫이다.
  · 항목마다 상태 하나와 근거 한 줄을 낸다. 상태는 넷이다.
      PASS         자동으로 볼 수 있는 것이 모두 맞고, 운영자가 직접 해 봐야 할 것이 따로 없다
      FAIL         자동으로 볼 수 있는 것 중 틀린 것이 있다
      수동(운영자)  자동 확인은 끝났거나 할 수 있는 것이 없고, 운영자(또는 독립 점검자)가 직접 해 봐야 판정된다
      아직(미구현)  판정에 필요한 구현·문서·파일이 저장소에 아직 없다
    여러 이유가 겹치면 FAIL, 아직, 수동, PASS 순서로 센 쪽이 이긴다(틀린 것을 가장 먼저 보이고, 안 끝난 것을 끝난 것처럼 말하지 않는다).
  · 종료 코드: FAIL 이 하나라도 있으면 1, 없으면 0(아직·수동은 0 이지만 표에 그대로 보인다). 사용법 오류는 2.
  · 구현이 있는지는 파일 이름과 소스 글로 본다(예: `update` 로 시작하는 모듈이 있는가). 그래서 어림짐작이고, 틀리면 '아직' 쪽으로 기운다 — 어느 규칙인지는 `docs/ARCHITECTURE.md` 의 '릴리스 후보 점검' 절에 있다.

후보 산출물 훑기(`scan_folder`)는 새 검사 규칙을 만들지 않고 `security/scan.py` 의 `scan_secrets` 만 부른다. 규칙:
  · 폴더 안 모든 파일을 글이든 이진 파일이든 끝까지 읽어 훑는다(글자 부호는 UTF-8, 맨 앞이 UTF-16 표지면 UTF-16). 큰 파일은 덩어리로 읽고 덩어리 사이를 겹쳐 경계에 걸친 키도 놓치지 않는다.
  · zip 은 풀지 않고 안의 파일을 메모리에서 읽어 훑는다. 다른 압축 형식·링크(정션 포함)·클라우드(OneDrive 등)에만 있는 자리표시·너무 큰 파일·읽기 실패·깨진 압축은 훑지 못한 것이므로 **조용히 건너뛰지 않고** '읽지 못함' 으로 세어 표에 드러내고, 하나라도 있으면 FAIL 이다(0 이라고 말할 수 없다).
  · 파일이 하나도 없는 폴더·열 수 없는 폴더도 FAIL 이다(엉뚱한 폴더를 골랐을 수 있다).
  · 결과에는 파일 경로·유형·줄 번호만 있고 키 글자는 어디에도 없다. 키처럼 보이는 파일 이름은 가려서 보인다.
"""
from __future__ import annotations

import argparse
import ast
import codecs
import importlib.util
import json
import os
import re
import stat
import sys
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_MANUAL = "수동(운영자)"
STATUS_NOT_YET = "아직(미구현)"
STATUSES = (STATUS_PASS, STATUS_FAIL, STATUS_MANUAL, STATUS_NOT_YET)

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

# docs/DECISIONS.md '1.0.0 완료 기준' 의 열두 항목(순서 그대로)
TITLES = {
    1: "개인 PC 에서 새로 clone 해 빌드·시험 가능",
    2: "어느 AI 도구든 문서만으로 구조 이해",
    3: "AI 없이 앱 실행과 D-18 의 모든 기능 사용",
    4: "기본 설정에서 유료 호출 불가",
    5: "GitHub Pages 테스트 글을 만들고 승인 뒤 배포까지 성공",
    6: "Blogger 테스트 글 초안 저장 성공",
    7: "네이버 A/B 각각 독립 패키지 생성과 중복 경고",
    8: "티스토리가 기본 화면·빌드에서 제외",
    9: "업데이트 전 백업과 실패 시 복구 성공",
    10: "로그·오류 보고서에 키·토큰이 남지 않음",
    11: "설치형과 휴대용 모두 실행",
    12: "버전·변경 이력이 화면과 GitHub Release 에서 일치",
}

APP = "src/chanceblog_desktop"
SELFTEST_KEYS = ("utf8_mode", "version_file", "package_info", "file_hashes", "licenses", "vendor_core", "capabilities", "uac_manifest", "qt_plugins", "qt_screens",
                 "gui_only_entry", "data_dir_untouched")        # `packaging/build_package.py` 의 judge_selftest 가 꼭 있어야 한다고 보는 열두 점검 이름(시험이 같음을 지킨다)
# `tests/test_repo_layout.py` 의 NO_AI_FEATURES 와 같은 목록(시험이 같음을 지킨다) — 운영자가 'AI 없이 반드시 동작해야 한다'고 정한 열일곱 기능(ARCHITECTURE 절 8, D-18)
NO_AI_FEATURES = (
    "콘텐츠 직접 작성·수정", "기존 원고 불러오기", "Markdown·HTML 변환", "플랫폼별 미리보기", "GitHub Pages 게시물 생성·배포", "Blogger 초안 생성·수정",
    "네이버 A/B 발행 패키지 생성", "제목·본문·태그 복사", "네이버 글쓰기 페이지 열기", "이미지 파일과 삽입 위치 관리", "발행 상태와 URL 기록", "예약 작업",
    "배포 성공·실패 감지", "규칙 기반 오류 안내", "작업 로그", "백업·복구", "프로그램 버전 확인·업데이트",
)
CLONE_PREREQUISITES = ("packaging/build_package.py", "packaging/requirements-package.txt", "scripts/ci_shard.py", ".github/workflows/ci.yml", "docs/MIGRATION.md")
REQUIRED_DOCS = ("README.md", "AGENTS.md", "CLAUDE.md", "docs/ARCHITECTURE.md", "docs/DECISIONS.md", "docs/MIGRATION.md", "docs/RELEASE.md", "docs/PACKAGE.md", "docs/SECURITY.md",
                 "docs/TROUBLESHOOTING.md", "docs/PERSONAL_PC_TEST.md")
MIN_DOC_CHARS = 200                                      # 공백을 뺀 글자가 이보다 적으면 빈 문서로 본다
DECISIONS_DOC = "docs/DECISIONS.md"
DECISION_INDEX = "docs/DECISIONS_INDEX.md"               # 결정 색인(DOCS 갈래가 만든다 — 없으면 '아직')
MATRIX_DOC = "docs/UI_POST_FLOW.md"                      # D-18 기능 → 화면 → 시험 표(GUI 갈래가 만든다 — 없으면 '아직')
ARCH_DOC = "docs/ARCHITECTURE.md"
POLICY_DOC = "docs/PLATFORM_POLICY.md"
CAPABILITIES = f"{APP}/capabilities.py"
CONNECTIONS = f"{APP}/service/connections.py"
PAID_GUARD_FILES = (f"{APP}/service/quota.py", f"{APP}/service/connections.py", CAPABILITIES)
PAGES_FILES = ("publish/pages.py", "publish/gitrepo.py", "publish/deploy.py", "render/pages.py", "service/pages_flow.py", "service/gate.py")
NAVER_FILES = ("render/naver.py", "check/similarity.py", "content/profiles.py", "service/naver_flow.py")
SECURITY_FILES = ("security/mask.py", "security/boundary.py", "security/errorlog.py", "security/scan.py")
BACKUP_FILE = "service/backup_flow.py"
VERSION_READER = f"{APP}/ui/core/version.py"
TISTORY_DIRS = ("src", "packaging", ".github", "ocr_addon")      # 기본 화면(src)·빌드 목록(packaging·워크플로·글자 읽기 묶음)
TISTORY = re.compile(r"tistory|티스토리", re.IGNORECASE)
EXCLUDED_MARK = "제외·격리"
SKIP_DIRS = frozenset({"__pycache__", ".git"})
SEMVER = re.compile(r"(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:[.](?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
                    r"(?:[+][0-9A-Za-z-]+(?:[.][0-9A-Za-z-]+)*)?")           # semver.org 2.0.0 의 공식 모양
CAPABILITY_NAMES = ("EXTERNAL_WRITE", "BLOGGER_OAUTH_INPUT", "LOCAL_OCR")
PURPOSE_FIELDS = ("works_without_key", "fallback_providers", "implemented")
UNREADABLE = object()                                    # 소스 상수·기본값이 글자 그대로의 값이 아니라서 읽지 못했다는 표시

# ---- 후보 산출물 훑기 ----------------------------------------------------------------------------------------------------------------------
CHUNK_BYTES = 1 << 20                                    # 파일을 읽는 덩어리(1MiB)
OVERLAP_CHARS = 4096                                     # 덩어리 사이를 겹치는 글자 수 — 키·토큰 모양은 이보다 짧아 경계에서 놓치지 않는다(`topicdb/backup.py` 의 겹친 창과 같은 생각)
MAX_FILE_BYTES = 1 << 30                                 # 이보다 큰 파일은 훑지 못한 것으로 센다
MAX_MEMBER_BYTES = 256 << 20                             # zip 안 파일 하나의 풀어 읽는 상한
MAX_ARCHIVE_BYTES = 1 << 30                              # zip 한 파일에서 풀어 읽는 총량 상한(압축 폭탄 방어)
SHOWN_LIMIT = 20                                         # 표 밑에 이름을 보이는 발견·읽지 못함 수(나머지는 '외 N개')
ZIP_MAGIC = b"PK\x03\x04"
OTHER_ARCHIVES = ((b"\x1f\x8b", "gzip"), (b"BZh", "bzip2"), (b"\xfd7zXZ\x00", "xz"), (b"7z\xbc\xaf\x27\x1c", "7z"), (b"Rar!", "rar"), (b"MSCF", "cab"))
_NEWLINE = re.compile(r"\r\n|\n|\r")                     # `security/scan.py` 가 줄을 세는 방법과 같다(시험이 같음을 지킨다)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CLOUD_ONLY = 0x1000 | 0x40000 | 0x400000                # 윈도 파일 속성 OFFLINE·RECALL_ON_OPEN·RECALL_ON_DATA_ACCESS — 클라우드(OneDrive 등)에만 있어 읽으면 내려받기가 시작되는 자리표시
_NAME_SURROGATE = 0x20000000                             # 윈도 재해석 지점 표의 '다른 이름을 가리킨다' 비트 — 심볼릭 링크·정션만 켜져 있다(OneDrive 자리표시는 꺼져 있다)

REASON_TEXT = {
    "link": "링크(따라가지 않음)",
    "cloud_only": "클라우드에만 있는 자리표시(읽으면 내려받기가 시작돼 열지 않음)",
    "too_big": "너무 큰 파일",
    "os_error": "읽을 수 없음",
    "other_archive": "열지 못하는 압축 형식",
    "zip_broken": "깨진 압축 파일",
    "zip_encrypted": "암호가 걸린 압축 파일",
    "zip_nested": "압축 파일 안의 압축 파일",
    "zip_budget": "압축을 푼 용량 한도 초과",
    "not_regular": "일반 파일이 아님",
}


@dataclass(frozen=True)
class Row:
    number: int
    title: str
    status: str
    basis: str


@dataclass(frozen=True)
class Finding:
    path: str            # 폴더 안 상대 경로(키 모양 이름은 가려진 글)
    label: str           # 유형 이름표(`security/scan.py` 의 KIND_LABELS)
    line: int


@dataclass(frozen=True)
class Unread:
    path: str
    reason: str          # REASON_TEXT 의 열쇠


@dataclass
class FolderScan:
    label: str
    openable: bool = True
    files_read: int = 0
    bytes_read: int = 0
    archives_opened: int = 0
    findings: list = field(default_factory=list)
    unread: list = field(default_factory=list)


# ---- 작은 부품 ----------------------------------------------------------------------------------------------------------------------------------
def _scan_module():
    """앱의 `security/scan.py` — 이 스크립트가 있는 저장소의 것을 쓴다. 가져오면서 .pyc 를 쓰지 않는다(읽기 전용)."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        from chanceblog_desktop.security import scan
    finally:
        sys.dont_write_bytecode = saved
    return scan


def _plain(text, limit=120):
    """화면에 보일 글 — 보이지 않는 글자는 물음표로, 길면 자른다."""
    shown = "".join(ch if ch.isprintable() else "?" for ch in str(text))
    return shown if len(shown) <= limit else shown[:limit - 1] + "…"


def _names(items, limit=3):
    items = list(items)
    shown = ", ".join(_plain(item, 80) for item in items[:limit])
    return shown + (f" 외 {len(items) - limit}개" if len(items) > limit else "")


def _cell(text):
    return str(text).replace("|", "/").replace("\r", " ").replace("\n", " ")


class Repo:
    """점검할 저장소 폴더 — 읽기만 한다. 경로는 늘 슬래시로 적는다."""

    def __init__(self, root):
        self.root = Path(root)

    def path(self, rel):
        return self.root.joinpath(*rel.split("/"))

    def is_file(self, rel):
        return self.path(rel).is_file()

    def is_dir(self, rel):
        return self.path(rel).is_dir()

    def read(self, rel):
        """글 파일의 내용(없거나 못 읽으면 None). UTF-8 이고 맨 앞 BOM 은 버린다."""
        try:
            data = self.path(rel).read_bytes()
        except OSError:
            return None
        return data.decode("utf-8-sig", errors="replace")

    def walk_files(self, rel):
        """폴더 안의 모든 파일 `(상대 경로, 전체 경로)` — 이름 순, `__pycache__` 와 `.git` 은 뺀다. 없는 폴더는 비어 있다."""
        base = self.path(rel)
        if not base.is_dir():
            return
        for current, directories, names in os.walk(base):
            directories[:] = sorted(name for name in directories if name not in SKIP_DIRS)
            for name in sorted(names):
                full = Path(current) / name
                yield full.relative_to(self.root).as_posix(), full


def _row(number, status, basis):
    return Row(number, TITLES[number], status, basis)


def _missing(repo, rels):
    return [rel for rel in rels if not repo.is_file(rel)]


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return UNREADABLE


def read_capabilities(repo):
    """`capabilities.py` 의 소스 상수 → {이름: 값}(글자 그대로 쓰인 값만 — 계산식이면 UNREADABLE). 파일이 없거나 구문이 깨졌으면 None. 가져오지 않고 구문만 읽는다."""
    text = repo.read(CAPABILITIES)
    if text is None:
        return None
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in CAPABILITY_NAMES:
                found[target.id] = _literal(value)
    return found


def read_purposes(repo):
    """`service/connections.py` 의 `Purpose` 기본값과 용도 표 → `(클래스 기본값 {이름: 값}, [(용도 이름, {바꾼 칸: 값}), ...])`. 읽을 수 없으면 None."""
    text = repo.read(CONNECTIONS)
    if text is None:
        return None
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    defaults, calls = {}, []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Purpose":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id in PURPOSE_FIELDS and stmt.value is not None:
                    defaults[stmt.target.id] = _literal(stmt.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Purpose":
            key = _literal(node.args[0]) if node.args else UNREADABLE
            changed = {kw.arg: _literal(kw.value) for kw in node.keywords if kw.arg in PURPOSE_FIELDS}
            calls.append((key if isinstance(key, str) else "?", changed))
    return defaults, calls


def find_section(text, title):
    """`## ` 로 시작하는 절 중 제목이 `title` 인 것의 본문(다음 `## ` 절 앞까지). 없으면 None. 제목 앞의 '8. ' 같은 번호는 있어도 없어도 된다."""
    match = re.search(r"^## (?:[0-9]+[.] )?" + re.escape(title), text, re.M)
    if match is None:
        return None
    rest = text[match.end():]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def decision_numbers(text):
    """결정 기록 표의 결정 번호들(`| D-12 |` 으로 시작하는 줄)."""
    return {int(number) for number in re.findall(r"^\| D-([0-9]+) \|", text, re.M)}


def index_numbers(text):
    """결정 색인 표의 결정 번호들 — 표 줄의 첫 칸 맨 앞이 `D-12`(굵게·링크·코드 글자로 감싸도 된다)인 것."""
    return {int(number) for number in re.findall(r"^\|\s*(?:\*\*|\[|`)*D-([0-9]+)(?![0-9])", text, re.M)}


def markdown_data_rows(text):
    """글 속 마크다운 표들의 데이터 줄 수(머리 줄과 구분선은 뺀다)."""
    lines = text.splitlines()
    rows = 0
    for index in range(len(lines) - 1):
        head, divider = lines[index].strip(), lines[index + 1].strip()
        if head.startswith("|") and re.fullmatch(r"\|[\s:|-]*-[\s:|-]*", divider):
            follow = index + 2
            while follow < len(lines) and lines[follow].strip().startswith("|"):
                rows += 1
                follow += 1
    return rows


def named_test_files(text):
    """글 속 백틱 안의 시험 파일 이름들(`tests/test_x.py`·`test_x.py`·`tests/test_x`) — 중복 없이, 확장자 없는 모듈 이름으로."""
    found = []
    for token in re.findall(r"`([^`\n]+)`", text):
        match = re.fullmatch(r"(?:tests/)?(test_[A-Za-z0-9_]+)(?:[.]py)?(?:[:#][^`]*)?", token.strip())
        if match and (token.strip().startswith("tests/") or token.strip().split(":")[0].endswith(".py")):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found


# ---- 열두 항목 ------------------------------------------------------------------------------------------------------------------------------------
def check_1(repo):
    missing = _missing(repo, CLONE_PREREQUISITES)
    if missing:
        return _row(1, STATUS_FAIL, f"새 clone 에서 시험·빌드하는 데 필요한 파일이 없다: {_names(missing)}")
    return _row(1, STATUS_MANUAL, f"준비물 {len(CLONE_PREREQUISITES)}개(빌드 도구·잠금 파일·시험 조각 도구·CI 설정·새 PC 안내)는 있다 — 새 clone 에서 시험하고 빌드하는 것은 운영자 개인 PC 에서 직접 해 봐야 한다")


def check_2(repo):
    problems = []
    for rel in REQUIRED_DOCS:
        text = repo.read(rel)
        if text is None:
            problems.append(f"{rel} 없음")
        elif len("".join(text.split())) < MIN_DOC_CHARS:
            problems.append(f"{rel} 비어 있음")
    if problems:
        return _row(2, STATUS_FAIL, f"입구·핵심 문서가 모자란다: {_names(problems)}")
    count = len(REQUIRED_DOCS)
    index = repo.read(DECISION_INDEX)
    if index is None:
        return _row(2, STATUS_NOT_YET, f"문서 {count}개는 있다 — 결정 색인({DECISION_INDEX})이 아직 없다")
    wanted, listed = decision_numbers(repo.read(DECISIONS_DOC)), index_numbers(index)
    if not listed:
        return _row(2, STATUS_FAIL, f"결정 색인({DECISION_INDEX})에서 결정 번호를 하나도 읽지 못했다")
    if listed != wanted:
        only_index = sorted(listed - wanted)
        only_log = sorted(wanted - listed)
        parts = []
        if only_index:
            parts.append("색인에만 있음 " + _names(f"D-{number}" for number in only_index))
        if only_log:
            parts.append("결정 기록에만 있음 " + _names(f"D-{number}" for number in only_log))
        return _row(2, STATUS_FAIL, "결정 색인이 결정 기록과 다르다(" + " · ".join(parts) + ") — 색인을 다시 만들어야 한다")
    return _row(2, STATUS_MANUAL, f"문서 {count}개가 있고 결정 색인이 결정 기록과 같다(결정 {len(wanted)}개) — 문서만 읽은 다른 AI 의 이해 시험은 따로 해야 한다")


def check_3(repo):
    arch = repo.read(ARCH_DOC)
    section = None if arch is None else find_section(arch, "AI 없이 반드시 동작해야 하는 기능")
    if section is None:
        return _row(3, STATUS_FAIL, f"{ARCH_DOC} 에 'AI 없이 반드시 동작해야 하는 기능' 절이 없다")
    absent = [name for name in NO_AI_FEATURES if name not in section]
    if absent:
        return _row(3, STATUS_FAIL, f"AI 없이 동작해야 하는 기능 {len(NO_AI_FEATURES)}개 중 {len(absent)}개가 그 절에서 빠졌다: {_names(absent)}")
    matrix = repo.read(MATRIX_DOC)
    if matrix is None:
        return _row(3, STATUS_NOT_YET, f"D-18 기능 → 화면 → 시험 표({MATRIX_DOC})가 아직 없다")
    rows = markdown_data_rows(matrix)
    if "D-18" not in matrix or rows == 0:
        return _row(3, STATUS_NOT_YET, f"{MATRIX_DOC} 는 있지만 D-18 표(데이터 줄)가 아직 없다")
    named = named_test_files(matrix)
    gone = [name for name in named if not repo.is_file(f"tests/{name}.py")]
    if gone:
        return _row(3, STATUS_NOT_YET, f"표 {rows}행 — 표가 가리키는 시험 파일 {len(gone)}개가 아직 없다: {_names(gone)}")
    return _row(3, STATUS_MANUAL, f"표 {rows}행·시험 파일 {len(named)}개가 있다 — 키·인터넷 없는 PC 에서 모든 기능을 쓰는 것은 운영자가 직접 해 봐야 한다")


def _gate_text(caps):
    return " · ".join(f"{name}={'켜짐' if caps.get(name) is True else '꺼짐' if caps.get(name) is False else '없음'}" for name in CAPABILITY_NAMES)


def check_4(repo):
    missing = _missing(repo, PAID_GUARD_FILES)
    if missing:
        return _row(4, STATUS_FAIL, f"유료 호출을 막는 쪽의 파일이 없다: {_names(missing)}")
    caps = read_capabilities(repo)
    if caps is None:
        return _row(4, STATUS_FAIL, "관문 상수 파일(capabilities.py)을 읽지 못했다")
    bad = [name for name in ("EXTERNAL_WRITE", "BLOGGER_OAUTH_INPUT") if not isinstance(caps.get(name), bool)]
    bad += [name for name in ("LOCAL_OCR",) if name in caps and not isinstance(caps[name], bool)]
    if bad:
        return _row(4, STATUS_FAIL, f"관문 상수가 없거나 True·False 글자 그대로가 아니다: {_names(bad)}")
    purposes = read_purposes(repo)
    if purposes is None or not purposes[1]:
        return _row(4, STATUS_FAIL, "연결 용도 표(service/connections.py 의 Purpose)를 읽지 못했다")
    defaults, calls = purposes
    problems = []
    if defaults.get("works_without_key") is not True:
        problems.append("용도 기본값 works_without_key 가 True 가 아니다(키 없이 동작하지 않는다)")
    if defaults.get("fallback_providers") != ():
        problems.append("용도 기본값 fallback_providers 가 빈 값이 아니다(다음 공급자 자동 전환)")
    if defaults.get("implemented") is not False:
        problems.append("용도 기본값 implemented 가 False 가 아니다(호출 코드 있음으로 시작)")
    for key, changed in calls:
        if changed.get("works_without_key") is False or changed.get("works_without_key") is UNREADABLE:
            problems.append(f"용도 {key} 는 키가 없으면 동작하지 않는다")
        if changed.get("fallback_providers") not in (None, ()):
            problems.append(f"용도 {key} 에 다음 공급자 자동 전환이 켜져 있다")
    if problems:
        return _row(4, STATUS_FAIL, "기본 설정에서 유료 호출을 막지 못한다: " + _names(problems))
    callable_now = [key for key, changed in calls if changed.get("implemented") is True]
    return _row(4, STATUS_PASS, f"관문 상수({_gate_text(caps)}) · 용도 {len(calls)}개가 모두 키 없이 동작하고 다음 공급자 자동 전환이 없다 · 호출 코드가 있는 용도 {len(callable_now)}개")


def check_5(repo):
    missing = _missing(repo, [f"{APP}/{rel}" for rel in PAGES_FILES])
    if missing:
        return _row(5, STATUS_FAIL, f"GitHub Pages 올리기 코드 파일이 없다: {_names(missing)}")
    caps = read_capabilities(repo)
    if caps is None or not isinstance(caps.get("EXTERNAL_WRITE"), bool):
        return _row(5, STATUS_FAIL, "외부 쓰기 관문 상수(EXTERNAL_WRITE)를 읽지 못했다")
    if caps["EXTERNAL_WRITE"] is False:
        return _row(5, STATUS_NOT_YET, f"Pages 올리기 코드 {len(PAGES_FILES)}개는 있지만 외부 쓰기 관문이 꺼져 있다(EXTERNAL_WRITE=False) — 가지 올리기 설계·승인 전이라 시험 글을 올릴 수 없다")
    return _row(5, STATUS_MANUAL, "외부 쓰기 관문이 켜져 있다 — 시험 글을 만들어 승인하고 배포되는지는 운영자 PC 에서 직접 해 봐야 한다")


def _blogger_modules(repo):
    found = []
    for folder in ("publish", "service", "render"):
        for rel, _full in repo.walk_files(f"{APP}/{folder}"):
            name = rel.rsplit("/", 1)[-1]
            if name.endswith(".py") and "blogger" in name.lower():
                found.append(rel)
    return found


def check_6(repo):
    caps = read_capabilities(repo)
    if caps is None or not isinstance(caps.get("BLOGGER_OAUTH_INPUT"), bool):
        return _row(6, STATUS_FAIL, "Blogger 입력 관문 상수(BLOGGER_OAUTH_INPUT)를 읽지 못했다")
    modules = _blogger_modules(repo)
    if caps["BLOGGER_OAUTH_INPUT"] is True and not modules:
        return _row(6, STATUS_FAIL, "Blogger 입력 관문이 켜져 있는데 Blogger 호출 코드가 없다")
    if not modules:
        return _row(6, STATUS_NOT_YET, "Blogger 초안 저장 코드가 아직 없다(BLOGGER_OAUTH_INPUT=False)")
    if caps["BLOGGER_OAUTH_INPUT"] is False:
        return _row(6, STATUS_NOT_YET, f"Blogger 코드 {len(modules)}개는 있지만 입력 관문이 꺼져 있다(BLOGGER_OAUTH_INPUT=False) — 운영자 승인 전이다")
    return _row(6, STATUS_MANUAL, "Blogger 입력 관문이 켜져 있다 — 테스트 글 초안이 저장되는지는 운영자가 로그인해서 직접 해 봐야 한다")


def _ui_mentions(repo, word):
    hits = []
    for rel, full in repo.walk_files(f"{APP}/ui"):
        if not rel.endswith(".py"):
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if word in text:
            hits.append(rel)
    return hits


def check_7(repo):
    missing = _missing(repo, [f"{APP}/{rel}" for rel in NAVER_FILES])
    if missing:
        return _row(7, STATUS_FAIL, f"네이버 패키지·중복 경고 코드 파일이 없다: {_names(missing)}")
    callers = _ui_mentions(repo, "naver_flow")
    if not callers:
        return _row(7, STATUS_NOT_YET, "네이버 패키지·중복 경고 서비스는 있지만 화면이 아직 그것을 부르지 않는다(ui 아래 naver_flow 언급 0)")
    return _row(7, STATUS_MANUAL, f"서비스와 화면 연결({len(callers)}곳)이 있다 — 네이버 A·B 독립 패키지와 중복 경고는 운영자 시험지로 직접 해 봐야 한다")


def check_8(repo):
    hits, scanned, unreadable = [], 0, []
    for folder in TISTORY_DIRS:
        for rel, full in repo.walk_files(folder):
            try:
                text = full.read_bytes().decode("utf-8", errors="replace")
            except OSError:
                unreadable.append(rel)
                continue
            scanned += 1
            match = TISTORY.search(text)
            if match:
                hits.append(f"{rel}:{text.count(chr(10), 0, match.start()) + 1}")
    problems = []
    if hits:
        problems.append(f"기본 화면·빌드 쪽 파일에 티스토리 낱말이 있다: {_names(hits)}")
    if unreadable:
        problems.append(f"읽지 못한 파일 {len(unreadable)}개: {_names(unreadable)}")
    if scanned == 0:
        problems.append("훑을 파일이 하나도 없다(src·packaging·.github·ocr_addon)")
    decisions = repo.read(DECISIONS_DOC) or ""
    row = next((line for line in decisions.splitlines() if line.startswith("| D-01 |")), "")
    if EXCLUDED_MARK not in row:
        problems.append("결정 D-01 에 '제외·격리' 가 없다")
    policy = repo.read(POLICY_DOC) or ""
    row = next((line for line in policy.splitlines() if line.startswith("| **티스토리**")), "")
    if EXCLUDED_MARK not in row:
        problems.append("플랫폼 정책 표의 티스토리 줄에 '제외·격리' 가 없다")
    if problems:
        return _row(8, STATUS_FAIL, " · ".join(problems))
    return _row(8, STATUS_PASS, f"src·packaging·.github·ocr_addon 의 파일 {scanned}개에 티스토리 낱말이 0 · 결정 D-01 과 플랫폼 정책 표가 '제외·격리' 로 적혀 있다")


def _pieces(repo, folder, test):
    found = []
    for rel, _full in repo.walk_files(folder):
        if test(rel.lower()):
            found.append(rel)
    return found


def _update_pieces(repo):
    found = []
    base = repo.path(APP)
    if base.is_dir():
        for current, directories, names in os.walk(base):
            directories[:] = sorted(name for name in directories if name not in SKIP_DIRS)
            for name in directories + sorted(names):
                if name.lower().startswith("update"):
                    found.append((Path(current) / name).relative_to(repo.root).as_posix())
    return sorted(found)


def check_9(repo):
    if not repo.is_file(f"{APP}/{BACKUP_FILE}"):
        return _row(9, STATUS_FAIL, f"백업·복원 코드({BACKUP_FILE})가 없다")
    pieces = _update_pieces(repo)
    if not pieces:
        return _row(9, STATUS_NOT_YET, "백업·복원은 있지만 업데이트 경로(update 로 시작하는 모듈)가 아직 없어 '업데이트 전 백업과 실패 시 복구' 를 시험할 수 없다")
    return _row(9, STATUS_MANUAL, f"업데이트 코드({len(pieces)}곳)가 있다 — 중단·변조·연속 실패에서 백업으로 되돌아가는지는 운영자 PC 에서 직접 해 봐야 한다")


def check_10(repo, scans):
    missing = _missing(repo, [f"{APP}/{rel}" for rel in SECURITY_FILES])
    if missing:
        return _row(10, STATUS_FAIL, f"키·토큰을 가리고 검사하는 코드 파일이 없다: {_names(missing)}")
    if not scans:
        return _row(10, STATUS_MANUAL, "후보 산출물 폴더를 --scan-dir 로 주면 훑는다(설치 파일 푼 것·zip 푼 것·로그·백업·진단 복사본) — 지금은 폴더가 없어 확인하지 않았다")
    closed = [scan for scan in scans if not scan.openable]
    files = sum(scan.files_read for scan in scans)
    found = sum(len(scan.findings) for scan in scans)
    unread = sum(len(scan.unread) for scan in scans)
    size = sum(scan.bytes_read for scan in scans)
    detail = f"폴더 {len(scans)}개 · 훑은 파일 {files:,}개 · {_megabytes(size)} · 발견 {found}건 · 읽지 못함 {unread}개"
    problems = []
    if closed:
        problems.append(f"열 수 없는 폴더 {len(closed)}개")
    if found:
        problems.append(f"키·토큰 모양 {found}건")
    if unread:
        problems.append(f"읽지 못한 파일 {unread}개(0 이라고 말할 수 없다)")
    if files == 0 and not closed:
        problems.append("훑은 파일이 0개(빈 폴더이거나 폴더를 잘못 골랐을 수 있다)")
    if problems:
        return _row(10, STATUS_FAIL, " · ".join(problems) + f" — {detail}")
    return _row(10, STATUS_PASS, detail)


def _megabytes(size):
    return f"{size / (1024 * 1024):,.1f}MB"


def _installer_pieces(repo):
    return _pieces(repo, "packaging", lambda path: "install" in path or path.endswith(".iss") or "velopack" in path or "vpk" in path)


def summarize_selftest(results):
    """자가 점검 결과 → `(실패한 이름들, 빠진 이름들, 통과 수, 건너뜀 수)`."""
    keys = [getattr(item, "key", None) for item in results]
    failed = [item.key for item in results if getattr(item, "status", None) == "fail"]
    absent = [name for name in SELFTEST_KEYS if name not in keys]
    passed = sum(1 for item in results if getattr(item, "status", None) == "ok")
    skipped = sum(1 for item in results if getattr(item, "status", None) == "skip")
    return failed, absent, passed, skipped


def check_11(repo, selftest_runner):
    try:
        results = list(selftest_runner())
    except Exception as error:      # noqa: BLE001 - 어떤 실패든 이 항목의 실패로 알린다(다른 항목은 계속)
        return _row(11, STATUS_FAIL, f"자가 점검(--selftest)을 함수로 부르지 못했다(오류 종류: {type(error).__name__})")
    failed, absent, passed, skipped = summarize_selftest(results)
    if failed or absent:
        parts = []
        if failed:
            parts.append(f"실패한 점검 {len(failed)}개: {_names(failed)}")
        if absent:
            parts.append(f"결과에 없는 점검 {len(absent)}개: {_names(absent)}")
        return _row(11, STATUS_FAIL, "자가 점검에서 " + " · ".join(parts))
    summary = f"자가 점검 {len(SELFTEST_KEYS)}개 중 통과 {passed} · 건너뜀 {skipped} · 실패 0(소스 실행이면 묶음 전용 점검을 건너뛴다)"
    pieces = _installer_pieces(repo)
    if not pieces:
        return _row(11, STATUS_NOT_YET, summary + " · 설치 파일을 만드는 코드가 아직 없다(휴대용 zip 만 있다)")
    return _row(11, STATUS_MANUAL, summary + f" · 설치 파일 코드({len(pieces)}곳)가 있다 — 설치·제거·휴대용 실행은 운영자 PC 에서 직접 해 봐야 한다")


def check_12(repo):
    raw = repo.read("VERSION")
    if raw is None:
        return _row(12, STATUS_FAIL, "VERSION 파일을 읽지 못했다")
    version = raw.strip()
    if not SEMVER.fullmatch(version):
        return _row(12, STATUS_FAIL, f"VERSION 이 SemVer 번호 모양이 아니다: {_plain(version, 40)}")
    changelog = repo.read("CHANGELOG.md")
    match = None if changelog is None else re.search(r"^## \[([^\]]+)\]", changelog, re.M)
    if match is None:
        return _row(12, STATUS_FAIL, "CHANGELOG.md 에서 맨 위 절 번호('## [번호]')를 찾지 못했다")
    if match.group(1) != version:
        return _row(12, STATUS_FAIL, f"VERSION({_plain(version, 40)})과 CHANGELOG 맨 위 절({_plain(match.group(1), 40)})이 다르다")
    reader = repo.read(VERSION_READER)
    if reader is None or "VERSION" not in reader:
        return _row(12, STATUS_FAIL, "화면의 버전 표시가 VERSION 파일을 읽는지 확인하지 못했다(ui/core/version.py)")
    return _row(12, STATUS_MANUAL, f"VERSION {version} = CHANGELOG 맨 위 절 = 화면이 읽는 번호(자동 확인) — GitHub Release 와 같은지는 Release 를 만든 뒤 운영자가 직접 봐야 한다")


# ---- 자가 점검(--selftest) 함수 호출 ------------------------------------------------------------------------------------------------------------
def run_repo_selftest(root=ROOT):
    """그 저장소의 `packaging/gui_entry.py` 를 파일 경로로 불러 `run_selftest()` 를 함수로 부른다(하위 프로세스 없음) → 결과 목록. 불러오면서 .pyc 를 쓰지 않는다."""
    packaging = Path(root) / "packaging"
    spec = importlib.util.spec_from_file_location("release_check_gui_entry", packaging / "gui_entry.py")
    if spec is None or spec.loader is None:
        raise ImportError("gui_entry.py 를 찾지 못했다")
    module = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(packaging))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
        if str(packaging) in sys.path:
            sys.path.remove(str(packaging))
    return list(module.run_selftest())


def run_checks(root=ROOT, *, selftest_runner=None, scans=None):
    """열두 항목을 점검해 `Row` 열두 개를 번호 순으로 돌려준다. `selftest_runner` 는 자가 점검 결과 목록을 돌려주는 함수(기본: 그 저장소의 것을 함수로 호출), `scans` 는 `FolderScan` 목록."""
    repo = Repo(root)
    runner = selftest_runner or (lambda: run_repo_selftest(root))
    checks = (
        (1, lambda: check_1(repo)), (2, lambda: check_2(repo)), (3, lambda: check_3(repo)), (4, lambda: check_4(repo)), (5, lambda: check_5(repo)), (6, lambda: check_6(repo)),
        (7, lambda: check_7(repo)), (8, lambda: check_8(repo)), (9, lambda: check_9(repo)), (10, lambda: check_10(repo, scans or [])), (11, lambda: check_11(repo, runner)),
        (12, lambda: check_12(repo)),
    )
    rows = []
    for number, check in checks:
        try:
            rows.append(check())
        except Exception as error:      # noqa: BLE001 - 한 항목의 예상 못 한 오류가 나머지 표를 막지 않게 그 항목의 실패로 알린다
            rows.append(_row(number, STATUS_FAIL, f"점검 중 예상하지 못한 오류(종류: {type(error).__name__})"))
    return rows


def exit_code(rows):
    return EXIT_FAILED if any(row.status == STATUS_FAIL for row in rows) else EXIT_OK


def counts(rows):
    return {status: sum(1 for row in rows if row.status == status) for status in STATUSES}


# ---- 후보 산출물 훑기 -----------------------------------------------------------------------------------------------------------------------------
def _is_link(info):
    """이 이름 자신이 링크인가 — 심볼릭 링크이거나 윈도의 이름을 가리키는 재해석 지점(정션·마운트 지점). `service/own_posts.py` 와 같은 판정이다."""
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT) and bool(getattr(info, "st_reparse_tag", 0) & _NAME_SURROGATE)


def _decoder(head):
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
        return codecs.getincrementaldecoder("utf-16")(errors="replace")
    return codecs.getincrementaldecoder("utf-8-sig")(errors="replace")


def _line_starts(text):
    return [0] + [match.end() for match in _NEWLINE.finditer(text)]


class _TooBig(Exception):
    pass


def scan_stream(stream, scan, *, chunk_bytes=CHUNK_BYTES, overlap_chars=OVERLAP_CHARS, limit_bytes=None):
    """열린 바이트 흐름 하나를 끝까지 훑는다 → `([(유형, 줄), ...], 읽은 바이트)`. `security/scan.py` 의 `scan_secrets` 만 부른다.
    덩어리마다 앞 덩어리의 끝 `overlap_chars` 글자를 겹쳐 붙여 훑는다. 한 발견을 정확히 한 번만 세려고, 덩어리 끝에서 `overlap_chars` 의 절반 안쪽에 끝나는 발견은
    다음 덩어리로 미룬다(끝이 잘려 모양이 달라지거나 짧은 앞부분만 걸리는 것을 막는다) — 마지막 덩어리에서는 남은 것을 모두 센다. 줄 번호는 흐름 맨 앞부터 센 값이다."""
    findings, total = [], 0
    block = stream.read(max(chunk_bytes, 4))                    # 첫 덩어리는 글자 부호 표지(UTF-16 BOM)를 알아볼 만큼은 읽는다
    if not block:
        return findings, 0
    decoder = _decoder(block)
    margin = max(overlap_chars // 2, 1)
    tail, lines_before, reported = "", 0, 0                     # reported: tail 기준으로 그 위치까지 끝난 발견은 이미 센 것
    while block:
        total += len(block)
        if limit_bytes is not None and total > limit_bytes:
            raise _TooBig()
        following = stream.read(chunk_bytes)
        last = not following
        combined = tail + decoder.decode(block, final=last)
        block = following
        limit = len(combined) if last else len(combined) - margin
        hits = scan.scan_secrets(combined)
        if hits:
            starts = _line_starts(combined)
            for hit in hits:
                if reported < starts[hit.line - 1] + hit.col_end <= limit:
                    findings.append((hit.kind, lines_before + hit.line))
        keep = combined[-overlap_chars:] if len(combined) > overlap_chars else combined
        dropped = combined[:len(combined) - len(keep)]
        if dropped.endswith("\r") and keep.startswith("\n"):
            dropped, keep = dropped[:-1], "\r" + keep
        reported = max(limit - len(dropped), 0)
        lines_before += len(_NEWLINE.findall(dropped))
        tail = keep
    return findings, total


def _shown(scan, rel):
    """화면에 보일 이름 — 키·토큰처럼 보이는 이름은 가리고, 보이지 않는 글자는 물음표로 바꾼다."""
    if scan.has_secret(rel):
        return "(이름이 키 모양이라 가림)"
    return _plain(rel)


def _note_name(result, scan, rel, name):
    """파일·폴더 **이름**(마지막 마디 `name`)에 키·토큰 모양이 있으면 발견으로 센다(줄 번호 0 = 이름). 이름도 산출물에 들어 있는 글이다."""
    for hit in scan.scan_secrets(name):
        result.findings.append(Finding(_shown(scan, rel), scan.KIND_LABELS[hit.kind], 0))


def _archive_kind(head):
    """파일 맨 앞 바이트로 본 압축 종류 — 'zip'(풀지 않고 안을 읽는다)·'other'(열지 못한다)·없으면 None."""
    if head.startswith(ZIP_MAGIC):
        return "zip"
    if any(head.startswith(magic) for magic, _name in OTHER_ARCHIVES):
        return "other"
    return None


def _read_into(result, stream, shown, scan, options, limit, broken):
    """열린 바이트 흐름 하나를 훑어 결과에 더한다 → 읽은 바이트 수. 끝까지 못 읽으면 None(이유 `broken` 또는 too_big 을 읽지 못함에 적는다)."""
    try:
        hits, size = scan_stream(stream, scan, chunk_bytes=options["chunk_bytes"], overlap_chars=options["overlap_chars"], limit_bytes=limit)
    except _TooBig:
        result.unread.append(Unread(shown, "too_big"))
        return None
    except (OSError, zipfile.BadZipFile, NotImplementedError, ValueError, EOFError, RuntimeError, zlib.error):         # 읽다 실패(잠김·깨진 압축·모르는 압축 방식·암호) — 그 파일 하나만
        result.unread.append(Unread(shown, broken))
        return None
    result.files_read += 1
    result.bytes_read += size
    result.findings.extend(Finding(shown, scan.KIND_LABELS[kind], line) for kind, line in hits)
    return size


def _scan_zip(stream, rel, result, scan, options):
    """zip 한 개 — 풀지 않고 안의 파일을 메모리에서 읽어 훑는다. 깨졌으면 그 파일 하나를, 안쪽 파일이 못 읽히면 그 안쪽 파일을 '읽지 못함' 으로 센다."""
    shown = _shown(scan, rel)
    try:
        archive = zipfile.ZipFile(stream)
    except (zipfile.BadZipFile, OSError, NotImplementedError, ValueError):
        result.unread.append(Unread(shown, "zip_broken"))
        return
    result.archives_opened += 1
    budget = MAX_ARCHIVE_BYTES
    with archive:
        for info in archive.infolist():
            member = _shown(scan, info.filename)
            name = f"{shown}!{member}"
            for hit in scan.scan_secrets(info.filename):
                result.findings.append(Finding(name, scan.KIND_LABELS[hit.kind], 0))
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                result.unread.append(Unread(name, "zip_encrypted"))
                continue
            limit = min(MAX_MEMBER_BYTES, budget)
            if info.file_size > limit:
                result.unread.append(Unread(name, "zip_budget"))
                continue
            try:
                opened = archive.open(info)
            except (zipfile.BadZipFile, OSError, NotImplementedError, ValueError, RuntimeError, zlib.error):
                result.unread.append(Unread(name, "zip_broken"))
                continue
            with opened:
                try:
                    kind = _archive_kind(opened.peek(8)[:8])
                except (zipfile.BadZipFile, OSError, NotImplementedError, ValueError, RuntimeError, EOFError, zlib.error):
                    result.unread.append(Unread(name, "zip_broken"))
                    continue
                if kind is not None:
                    result.unread.append(Unread(name, "zip_nested" if kind == "zip" else "other_archive"))
                    continue
                size = _read_into(result, opened, name, scan, options, limit, "zip_broken")
            if size is not None:
                budget -= size


def _scan_file(full, rel, info, result, scan, options):
    shown = _shown(scan, rel)
    if info.st_size > MAX_FILE_BYTES:
        result.unread.append(Unread(shown, "too_big"))
        return
    try:
        with options["opener"](full) as stream:
            head = stream.read(8)
            stream.seek(0)
            kind = _archive_kind(head)
            if kind == "other":
                result.unread.append(Unread(shown, "other_archive"))
            elif kind == "zip":
                _scan_zip(stream, rel, result, scan, options)
            else:
                _read_into(result, stream, shown, scan, options, MAX_FILE_BYTES, "os_error")
    except OSError:
        result.unread.append(Unread(shown, "os_error"))


def scan_folder(folder, label="폴더 1", *, chunk_bytes=CHUNK_BYTES, overlap_chars=OVERLAP_CHARS, opener=None, link_test=None):
    """폴더 하나를 끝까지 훑는다 → `FolderScan`. 하위 폴더·숨은 파일·확장자가 없는 파일까지 모두 훑고, 훑지 못한 것은 `unread` 에 이유와 함께 모은다(조용히 건너뛰지 않는다).
    `opener`(파일 경로 → 바이트로 열린 파일)·`link_test`(lstat 결과 → 링크인가)는 시험이 바꿔 끼우는 자리다."""
    scan = _scan_module()
    options = {"opener": opener or (lambda path: open(path, "rb")), "chunk_bytes": chunk_bytes, "overlap_chars": overlap_chars}
    is_link = link_test or _is_link
    result = FolderScan(label)
    base = Path(folder)
    if not base.is_dir():
        result.openable = False
        return result
    pending = [base]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as listing:
                entries = sorted(listing, key=lambda entry: entry.name)
        except OSError:
            result.unread.append(Unread(_shown(scan, current.relative_to(base).as_posix()), "os_error"))
            continue
        folders = []
        for entry in entries:
            full = Path(entry.path)
            rel = full.relative_to(base).as_posix()
            _note_name(result, scan, rel, entry.name)
            try:
                info = os.lstat(full)
            except OSError:
                result.unread.append(Unread(_shown(scan, rel), "os_error"))
                continue
            if is_link(info):
                result.unread.append(Unread(_shown(scan, rel), "link"))
            elif getattr(info, "st_file_attributes", 0) & _CLOUD_ONLY:
                result.unread.append(Unread(_shown(scan, rel), "cloud_only"))
            elif stat.S_ISDIR(info.st_mode):
                folders.append(full)
            elif stat.S_ISREG(info.st_mode):
                _scan_file(full, rel, info, result, scan, options)
            else:
                result.unread.append(Unread(_shown(scan, rel), "not_regular"))
        pending.extend(reversed(folders))
    return result


# ---- 보여 주기 ------------------------------------------------------------------------------------------------------------------------------------
def render_table(rows):
    lines = ["| 번호 | 항목 | 상태 | 근거 |", "|---|---|---|---|"]
    lines += [f"| {row.number} | {_cell(row.title)} | {row.status} | {_cell(row.basis)} |" for row in rows]
    return "\n".join(lines)


def render_scans(scans):
    if not scans:
        return ""
    lines = ["", "후보 산출물 키·토큰 모양 훑기(`security/scan.py` 의 기존 검사만 사용 — 새 규칙 없음, 키 글자는 어디에도 나오지 않는다)",
             "| 폴더 | 훑은 파일 | 용량 | 열어 본 zip | 발견 | 읽지 못함 |", "|---|---|---|---|---|---|"]
    for scan in scans:
        lines.append(f"| {_cell(scan.label)} | {scan.files_read:,} | {_megabytes(scan.bytes_read)} | {scan.archives_opened} | {len(scan.findings)} | {len(scan.unread)} |")
    for scan in scans:
        for title, items in (("발견", [f"{item.path} (파일 이름) {item.label}" if item.line == 0 else f"{item.path}:{item.line} {item.label}" for item in scan.findings]),
                             ("읽지 못함", [f"{item.path} — {REASON_TEXT.get(item.reason, item.reason)}" for item in scan.unread])):
            if items:
                lines.append(f"- {scan.label} {title} {len(items)}개")
                lines += [f"  - {_plain(item, 200)}" for item in items[:SHOWN_LIMIT]]
                if len(items) > SHOWN_LIMIT:
                    lines.append(f"  - 외 {len(items) - SHOWN_LIMIT}개")
    return "\n".join(lines)


def render_report(rows, scans, version):
    tally = counts(rows)
    manual = [str(row.number) for row in rows if row.status == STATUS_MANUAL]
    not_yet = [str(row.number) for row in rows if row.status == STATUS_NOT_YET]
    failed = [str(row.number) for row in rows if row.status == STATUS_FAIL]
    lines = [f"릴리스 후보 점검 — 앱 v1.0 완료 기준 열두 항목(저장소 버전 {_plain(version, 40)})",
             "읽기만 하는 점검이고 v1.0 을 선언하지 않습니다 — 선언은 운영자 몫입니다.", "", render_table(rows), ""]
    lines.append("요약: " + " · ".join(f"{status} {tally[status]}" for status in STATUSES))
    lines.append(f"운영자가 직접 해 봐야 하는 항목(수동): {', '.join(manual) or '없음'}")
    lines.append(f"아직 만들어지지 않아 판정할 수 없는 항목(아직): {', '.join(not_yet) or '없음'}")
    lines.append(f"틀린 항목(FAIL): {', '.join(failed) or '없음'}")
    lines.append("상태 뜻: PASS = 자동으로 볼 수 있는 것이 모두 맞고 운영자 실기가 따로 필요 없음 · FAIL = 틀린 것이 있음 · 수동(운영자) = 운영자가 직접 해 봐야 판정됨 · 아직(미구현) = 판정에 필요한 구현·문서가 아직 없음")
    lines.append("종료 코드: " + (f"{EXIT_FAILED} (FAIL 이 있습니다)" if failed else f"{EXIT_OK} (FAIL 이 없습니다 — 아직·수동은 종료 코드에 영향이 없습니다)"))
    block = render_scans(scans)
    if block:
        lines.append(block)
    return "\n".join(lines)


def render_json(rows, scans, version):
    return json.dumps({
        "version": version,
        "rows": [{"number": row.number, "title": row.title, "status": row.status, "basis": row.basis} for row in rows],
        "summary": counts(rows),
        "exit_code": exit_code(rows),
        "scans": [{"label": scan.label, "openable": scan.openable, "files_read": scan.files_read, "bytes_read": scan.bytes_read, "archives_opened": scan.archives_opened,
                   "findings": [{"path": item.path, "kind": item.label, "line": item.line} for item in scan.findings],
                   "unread": [{"path": item.path, "reason": item.reason} for item in scan.unread]} for scan in scans],
    }, ensure_ascii=False, indent=2)


def read_version(root):
    raw = Repo(root).read("VERSION")
    return raw.strip() if raw is not None else "?"


def build_parser():
    parser = argparse.ArgumentParser(prog="release_check.py", description="앱 v1.0 완료 기준 열두 항목 점검표(읽기 전용 — v1.0 을 선언하지 않는다)")
    parser.add_argument("--scan-dir", action="append", default=[], metavar="폴더", help="후보 산출물 폴더의 키·토큰 모양을 훑어 10번 항목에 반영한다(여러 번 줄 수 있다)")
    parser.add_argument("--json", action="store_true", help="표 대신 JSON 으로 낸다")
    parser.add_argument("--root", default=None, metavar="폴더", help="점검할 저장소 폴더(기본: 이 스크립트가 있는 저장소). 다른 사본을 주면 그 사본의 자가 점검 코드를 실행하니 믿는 사본에만 쓴다")
    return parser


def main(argv=None, *, out=None, selftest_runner=None):
    args = build_parser().parse_args(argv)
    stream = out or sys.stdout
    if out is None and hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
    root = Path(args.root) if args.root else ROOT
    scans = []
    for number, folder in enumerate(args.scan_dir, 1):
        if out is None:
            print(f"폴더 {number} 훑는 중(큰 폴더는 몇 분 걸린다)", file=sys.stderr)
        scans.append(scan_folder(Path(folder), f"폴더 {number}"))
    rows = run_checks(root, selftest_runner=selftest_runner, scans=scans)
    version = read_version(root)
    print(render_json(rows, scans, version) if args.json else render_report(rows, scans, version), file=stream)
    return exit_code(rows)


if __name__ == "__main__":
    sys.exit(main())
