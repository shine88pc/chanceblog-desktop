"""릴리스 후보 점검(`scripts/release_check.py`) 시험 도우미(시험이 아니다) — 가짜 저장소 사본을 임시 폴더에 만들고, 가짜 자가 점검 결과를 건네고, 폴더 전체의 바이트 지문을 낸다.

시험 파일들이 `import release_check_support as rs` 로 쓴다(`python -m unittest discover -s tests` 는 tests/ 를 import 경로에 올린다).
가짜 저장소는 점검이 읽는 파일만 아주 작게 담는다 — 처음 모양('기준 사본')은 아직·수동이 섞인 지금 저장소와 같은 모양이고, 시험은 파일을 지우거나 바꿔 각 항목의 PASS·FAIL·수동·아직 길을 지난다.
키 모양은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다(소스에 완성된 키 모양 글을 쓰지 않는다). 네트워크·실제 비밀 없이 돈다.
"""
import hashlib
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_check as rc  # noqa: E402

SelfResult = namedtuple("SelfResult", "key status text")
SOURCE_ONLY_SKIPS = ("package_info", "file_hashes", "licenses", "uac_manifest", "qt_plugins", "qt_screens")        # 소스 실행에서 건너뛰는 점검 여섯
APP = "src/chanceblog_desktop"


def selftest_ok():
    """소스 실행 모양의 가짜 자가 점검 결과 — 열두 항목 중 여섯 통과·여섯 건너뜀·실패 0."""
    return [SelfResult(key, "skip" if key in SOURCE_ONLY_SKIPS else "ok", "가짜 결과") for key in rc.SELFTEST_KEYS]


def filler(label):
    """공백을 뺀 글자가 200자를 훨씬 넘는 문서 내용."""
    return (f"{label} 문서의 내용입니다. 시험용 가짜 문장을 반복해서 채웁니다. " * 12) + "\n"


ARCH_TEXT = ("# 구조\n\n" + filler("구조") + "\n## 8. AI 없이 반드시 동작해야 하는 기능 (시험으로 지킨다)\n\n" + " · ".join(rc.NO_AI_FEATURES) + ".\n\n## 9. 데이터 모델\n\n" + filler("모델"))
DECISIONS_TEXT = ("# 결정 기록\n\n| 번호 | 날짜 | 결정 | 상태 |\n|---|---|---|---|\n"
                  "| D-01 | 2026-10-30 | **플랫폼 범위** 네이버·Blogger·Pages 만 하고 티스토리는 제외·격리한다 | 확정 |\n"
                  "| D-18 | 2026-10-30 | **AI 없이 반드시 동작해야 하는 기능** | 확정 |\n"
                  "| D-19 | 2026-10-30 | **다음 결정** | 확정 |\n\n" + filler("결정"))
POLICY_TEXT = "# 플랫폼 정책\n\n| 플랫폼 | 하는 것 | 하지 않는 것 |\n|---|---|---|\n| **티스토리** | **제외·격리**(D-01) 공식 수단이 없다 | 기본 화면·빌드에 넣지 않는다 |\n\n" + filler("정책")
CHANGELOG_TEXT = "# 변경 이력\n\n## [0.1.0-preview.1] — 2026-11-11 (시험)\n\n- 시험 줄\n\n## [0.0.0] — 2026-10-30\n\n- 처음\n"
CAPABILITIES_TEXT = '"""관문."""\nEXTERNAL_WRITE = False\nBLOGGER_OAUTH_INPUT = False\nLOCAL_OCR = False\n'
CONNECTIONS_TEXT = '''"""연결 용도 표(가짜)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Purpose:
    key: str
    label: str
    fallback_providers: tuple = ()
    implemented: bool = False
    works_without_key: bool = True


def _purposes():
    return (
        Purpose("alpha", "에이"),
        Purpose("beta", "비", implemented=False),
        Purpose("gamma", "씨"),
    )
'''
UI_TEXT = '"""화면(가짜) — 서비스 흐름을 아직 부르지 않는다."""\n'
VERSION_READER_TEXT = '"""화면의 버전 표시(가짜) — VERSION 파일을 읽는다."""\nNAME = "VERSION"\n'


def base_files():
    """기준 사본의 파일 {상대 경로: 글}."""
    files = {
        "VERSION": "0.1.0-preview.1\n",
        "CHANGELOG.md": CHANGELOG_TEXT,
        "README.md": filler("README"),
        "AGENTS.md": filler("AGENTS"),
        "CLAUDE.md": filler("CLAUDE"),
        "docs/ARCHITECTURE.md": ARCH_TEXT,
        "docs/DECISIONS.md": DECISIONS_TEXT,
        "docs/MIGRATION.md": filler("MIGRATION"),
        "docs/RELEASE.md": filler("RELEASE"),
        "docs/PACKAGE.md": filler("PACKAGE"),
        "docs/SECURITY.md": filler("SECURITY"),
        "docs/TROUBLESHOOTING.md": filler("TROUBLESHOOTING"),
        "docs/PERSONAL_PC_TEST.md": filler("PERSONAL_PC_TEST"),
        "docs/PLATFORM_POLICY.md": POLICY_TEXT,
        "packaging/build_package.py": "# 빌드 도구(가짜)\n",
        "packaging/requirements-package.txt": "pyinstaller==0\n",
        "scripts/ci_shard.py": "# 조각 도구(가짜)\n",
        ".github/workflows/ci.yml": "name: ci\n",
        f"{APP}/capabilities.py": CAPABILITIES_TEXT,
        f"{APP}/service/connections.py": CONNECTIONS_TEXT,
        f"{APP}/service/quota.py": "# 한도(가짜)\n",
        f"{APP}/ui/core/version.py": VERSION_READER_TEXT,
        f"{APP}/ui/screen.py": UI_TEXT,
    }
    for rel in rc.PAGES_FILES + rc.NAVER_FILES + rc.SECURITY_FILES + (rc.BACKUP_FILE,):
        files.setdefault(f"{APP}/{rel}", "# 구현(가짜)\n")
    return files


def write_files(root, files):
    root = Path(root)
    for rel, text in files.items():
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return root


def build_repo(root, *, drop=(), extra=None):
    """기준 사본을 `root` 에 만든다. `drop` 의 파일은 빼고 `extra`({경로: 글}) 는 더하거나 바꾼다."""
    files = base_files()
    for rel in drop:
        if rel not in files:
            raise KeyError(rel)
        del files[rel]
    files.update(extra or {})
    return write_files(root, files)


def temp_dir():
    """임시 폴더 — 윈도에서 백신·색인기가 막 만든 파일을 잠깐 잡고 있어도 치우기 실패가 시험 판정을 바꾸지 않게 한다."""
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def rows_of(root, *, selftest=selftest_ok, scans=None):
    """`run_checks` 결과를 {번호: Row} 로."""
    return {row.number: row for row in rc.run_checks(root, selftest_runner=selftest, scans=scans)}


def tree_fingerprint(root):
    """폴더 안 모든 파일(과 폴더)의 이름·바이트 지문 — 읽기 전용인지 확인하는 데 쓴다."""
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
