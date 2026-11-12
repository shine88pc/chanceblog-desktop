"""Package 도구 시험 도우미(시험이 아니다) — `packaging/` 의 스크립트를 불러오고, 임시 git 저장소·가짜 묶음·가짜 설치 정보·가짜 PE 파일을 만든다.

시험 파일들이 `import packaging_support as ps` 로 쓴다(`python -m unittest discover -s tests` 는 tests/ 를 import 경로에 올린다).
이 도우미는 PyInstaller·PySide6 없이 돈다(CI 에는 둘 다 없다 — D-32): 진짜 빌드는 개발 PC 에서만 하고, 시험은 PyInstaller 자리에 가짜 단계를 끼워 순서·거절·해시를 확인한다.
"""
import atexit
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(PACKAGING))

import build_package  # noqa: E402
import gui_entry  # noqa: E402
import make_manifest  # noqa: E402
import pkgcommon  # noqa: E402

ENTRY = gui_entry                                                    # 시험 파일들이 `ps.gui_entry` 로 쓴다(다시 내보내기)

HAVE_GIT = bool(shutil.which("git"))
VERSION = "0.1.0-preview.1"
COMMIT_DATE = "2026-11-11T10:00:00+09:00"
COMMIT_EPOCH = int(datetime(2026, 11, 11, 1, 0, 0, tzinfo=timezone.utc).timestamp())
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
               GIT_AUTHOR_DATE=COMMIT_DATE, GIT_COMMITTER_DATE=COMMIT_DATE)
FAKE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
FAKE_TREE = "fedcba9876543210fedcba9876543210fedcba98"
PYTHON_DLL = f"python{sys.version_info[0]}{sys.version_info[1]}.dll"
SELFTEST_KEYS = ("utf8_mode", "version_file", "package_info", "file_hashes", "licenses", "vendor_core", "capabilities", "uac_manifest", "qt_plugins", "qt_screens",
                 "gui_only_entry", "data_dir_untouched")


def temp_dir():
    """임시 폴더 — 윈도에서 백신·색인기가 막 만든 파일을 잠깐 잡고 있으면 지우기가 실패하므로(`PermissionError`, 이 PC 에서 한 번 봤다) 치우기 실패는 시험 판정과 무관하게 넘긴다."""
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def write(path, text="", *, binary=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    else:
        path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    return path


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, encoding="utf-8", env=GIT_ENV)
    if done.returncode:
        raise AssertionError(f"git {' '.join(args)} 실패: {done.stderr.strip()[:200]}")
    return done.stdout.strip()


def init_repo(path, files, *, ignore=""):
    """임시 git 저장소를 만들고 한 번 커밋한다(작성자·시각 고정) — 커밋 해시를 돌려준다."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    if ignore:
        write(path / ".gitignore", ignore)
    for name, text in files.items():
        write(path / name, text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "x")
    return git(path, "rev-parse", "HEAD")


def pe_bytes(*, signed=False, plus=True, size=1024):
    """맨 앞 머리만 맞는 가짜 PE 파일 — 보안 디렉터리(서명) 크기를 정할 수 있다."""
    pe_offset = 0x80
    magic = 0x20B if plus else 0x10B
    optional_header = bytearray(240 if plus else 224)
    struct.pack_into("<H", optional_header, 0, magic)
    directory_start = 112 if plus else 96
    if signed:
        struct.pack_into("<II", optional_header, directory_start + 8 * 4, 0x400, 0x200)
    data = bytearray(pe_offset) + b"PE\0\0" + bytes(20) + bytes(optional_header)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, pe_offset)
    return bytes(data).ljust(size, b"\0")


def fake_dist_dir(path, *, exe=None):
    """PyInstaller 가 만들 법한 한 폴더 — 실행 파일·`_internal`(Python DLL·Qt 파일 넷)·윈도 버전 파일 자리."""
    path = Path(path)
    write(path / f"{pkgcommon.EXE_NAME}.exe", exe if exe is not None else pe_bytes(), binary=True)
    write(path / "_internal" / PYTHON_DLL, b"python-dll", binary=True)
    write(path / "_internal" / "base_library.zip", b"zip", binary=True)
    for relative in build_package.QT_FILES:
        write(path / "_internal" / relative, b"qt:" + relative.encode(), binary=True)
    return path


def collect_toc(rows=None):
    """PyInstaller 의 `COLLECT-00.toc` 흉내 — `([(이름, 출처, 종류), …],)` 한 칸짜리 튜플 글. 기본은 허용된 뿌리(기본 Python 폴더)에서 온 파이썬 DLL 하나와 실행 파일."""
    base = sys.base_prefix.replace(os.sep, "/")
    rows = rows if rows is not None else [(f"{pkgcommon.EXE_NAME}.exe", "C:/out/work/ChanceBlogDesktop/ChanceBlogDesktop.exe", "EXECUTABLE"), (PYTHON_DLL, f"{base}/{PYTHON_DLL}", "BINARY")]
    return repr(([tuple(row) for row in rows],)) + "\n"


class FakeMetadata(dict):
    def get_all(self, key, default=None):
        value = self.get(key)
        return default if value is None else (value if isinstance(value, list) else [value])


class FakePath:
    """`importlib.metadata.PackagePath` 흉내 — `name`·`parts` 만."""

    def __init__(self, text):
        self.text = text
        self.parts = tuple(text.split("/"))
        self.name = self.parts[-1]


class FakeDistribution:
    def __init__(self, name, version, *, record="", license_text="MIT", files=(), root=None, classifiers=()):
        self.name, self.version = name, version
        self._record = record
        self.metadata = FakeMetadata({"License": license_text, "Name": name, "Version": version})
        if classifiers:
            self.metadata["Classifier"] = list(classifiers)
        self.files = [FakePath(item) for item in files]
        self._root = Path(root) if root else None

    def read_text(self, filename):
        return self._record if filename == "RECORD" else None

    def locate_file(self, item):
        return self._root / item.text


def lock_versions(lock_text=None):
    """잠금 파일의 {이름(정규화): 버전} — 가짜 설치 조회를 이 값으로 만든다."""
    text = lock_text if lock_text is not None else (PACKAGING / "requirements-package.txt").read_text(encoding="utf-8")
    return {make_manifest.normalize_name(item["name"]): item["version"] for item in make_manifest.parse_requirements(text)}


def fake_lookup(versions=None):
    from importlib import metadata
    table = dict(versions if versions is not None else lock_versions())

    def lookup(name):
        key = make_manifest.normalize_name(name)
        if key not in table:
            raise metadata.PackageNotFoundError(name)
        return table[key]
    return lookup


def fake_distribution_factory(root):
    """잠금 파일의 모든 패키지에 대해 가짜 배포본을 돌려주는 함수 — pyinstaller 에는 라이선스 파일(COPYING.txt)이 있다."""
    root = Path(root)
    write(root / "pyinstaller-0.0.dist-info" / "licenses" / "COPYING.txt", "GPL with exception\n")
    versions = lock_versions()

    def distribution(name):
        key = make_manifest.normalize_name(name)
        if key not in versions:
            from importlib import metadata
            raise metadata.PackageNotFoundError(name)
        files = ("pyinstaller-0.0.dist-info/licenses/COPYING.txt",) if key == "pyinstaller" else ()
        license_text = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only" if key in ("pyside6-essentials", "shiboken6") else "MIT"
        return FakeDistribution(name, versions[key], record=f"{name}/__init__.py,sha256=abc,10\n{name}/data.bin,sha256=def,20\n", license_text=license_text, files=files, root=root)
    return distribution


def selftest_text(*, overrides=None, version=VERSION, drop=()):
    """묶음 실행 파일의 `--selftest` 출력 흉내 — 모두 통과, `overrides` 로 점검마다 (상태, 글)을 바꾼다."""
    overrides = overrides or {}
    labels = {"ok": "통과", "fail": "실패", "skip": "건너뜀"}
    lines = [f"{pkgcommon.PRODUCT} {version} 자가 점검 — {pkgcommon.NOTICE}"]
    for key in SELFTEST_KEYS:
        if key in drop:
            continue
        status, text = overrides.get(key, ("ok", "정상"))
        lines.append(f"[{labels[status]}] {key}: {text}")
    return "\n".join(lines) + "\n"


_TEMPLATE = {}


def _build_template(path):
    path = Path(path)
    for relative in ("vendor/VENDOR.json", "vendor/pipeline/__init__.py", "vendor/pipeline/console.py", "vendor/pipeline/gates.py",
                     "vendor/pipeline/secret_patterns.py", "vendor/scripts/verify_pages_deploy.py", "packaging/requirements-package.txt",
                     "packaging/LICENSES/LGPL-3.0.txt", "packaging/LICENSES/GPL-3.0.txt"):
        write(path / relative, (ROOT / relative).read_bytes(), binary=True)
    write(path / "VERSION", VERSION + "\n")
    write(path / "src" / "chanceblog_desktop" / "__init__.py", "")
    write(path / "packaging" / "gui_entry.py", "")
    write(path / ".gitignore", "dist/\nbuild/\n*.zip\n*.exe\n")
    git(path, "init", "-q")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "x")


def make_build_repo(path, *, extra=None):
    """`build_package.build` 시험용 가짜 저장소 — 진짜 `vendor/`·잠금 파일·라이선스 전문을 담아 한 번만 만들어 커밋하고(git 필요) 시험마다 폴더째 복사한다(커밋 해시가 늘 같다 — git 호출을 줄여 시험이 빠르다)."""
    if "dir" not in _TEMPLATE:
        root = Path(tempfile.mkdtemp(prefix="pckit-template-"))
        atexit.register(shutil.rmtree, str(root), True)
        _build_template(root / "repo")
        _TEMPLATE["dir"] = root / "repo"
    path = Path(path)
    shutil.copytree(_TEMPLATE["dir"], path)
    if extra:
        for name, text in extra.items():
            write(path / name, text)
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "extra")
    return path


class FakeBuild:
    """`build_package.build` 의 단계들을 가짜로 바꿔 끼우는 묶음 — PyInstaller 자리에 가짜 폴더, 자가 점검 자리에 정한 출력을 둔다."""

    def __init__(self, tmp, repo, *, selftest=None, scan=None):
        self.tmp, self.repo = Path(tmp), Path(repo)
        self.calls = []
        self.selftest_output = selftest if selftest is not None else selftest_text()
        self.scan_result = scan
        self.toc_rows = None                                                  # 가짜 묶음 목록의 행들(없으면 허용된 뿌리에서 온 것만) — 시험이 바꿔 끼운다
        base = self.tmp / "base_prefix"
        write(base / "LICENSE.txt", "PSF license text\n")
        self.steps = {
            "clock": lambda: 1_700_000_000.0,
            "pyinstaller": self.pyinstaller,
            "selftest": self.selftest,
            "scan": self.scan,
            "lookup": fake_lookup(),
            "distribution": fake_distribution_factory(self.tmp / "dists"),
            "pyinstaller_version": "6.22.3",
            "platform": "win32",
            "base_prefix": base,
        }

    def pyinstaller(self, args, env, cwd, log_path):
        self.calls.append(("pyinstaller", list(args), dict(env)))
        dist = Path(args[args.index("--distpath") + 1]) / pkgcommon.EXE_NAME
        fake_dist_dir(dist)
        write(Path(args[args.index("--workpath") + 1]) / pkgcommon.EXE_NAME / "COLLECT-00.toc", collect_toc(self.toc_rows))
        write(log_path, "log")
        return 0

    def selftest(self, exe):
        self.calls.append(("selftest", str(exe)))
        return 0, self.selftest_output

    def scan(self, paths):
        self.calls.append(("scan", [str(p) for p in paths]))
        return self.scan_result if self.scan_result is not None else {"status": "not_run", "reason": "시험", "tool": "가짜", "targets": [], "exit_codes": []}


def _top_block(code, key):
    """최상위 `key:` 아래의 들여쓴 줄들(없으면 None) — 같은 줄에 적은 값은 맨 앞 항목으로."""
    lines, block, inside = code.split("\n"), [], False
    for line in lines:
        if not inside:
            match = re.match(rf"^{key}:(.*)$", line)
            if match:
                inside = True
                if match.group(1).strip():
                    block.append(match.group(1).strip())
            continue
        if line and not line.startswith((" ", "\t")):
            break
        block.append(line)
    return block if inside else None


def _upload_steps(code):
    """`actions/upload-artifact` 를 부르는 단계들의 글 — 단계는 여섯 칸 들여쓴 `- ` 로 시작한다."""
    steps, current = [], None
    for line in code.split("\n"):
        if re.match(r"^      - ", line):
            current = [line]
            steps.append(current)
        elif current is not None:
            current.append(line)
    return ["\n".join(step) for step in steps if "actions/upload-artifact@" in "\n".join(step)]


def _upload_paths(step):
    lines = step.split("\n")
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)path:\s*(.*)$", line)
        if not match:
            continue
        inline = match.group(2).strip()
        if inline and inline not in ("|", ">", "|-"):
            return [inline.strip("\"'")]
        base = len(match.group(1))
        found = []
        for follow in lines[index + 1:]:
            if follow.strip() and len(follow) - len(follow.lstrip()) <= base:
                break
            if follow.strip():
                found.append(follow.strip())
        return found
    return []


def workflow_violations(text):
    """빌드 워크플로 초안이 지켜야 할 규칙을 글만 보고 검사한다 → 어긴 것의 목록(없으면 빈 목록). 시험이 좋은 글·나쁜 글로 이 검사 자체도 시험한다.
    규칙: 수동 실행만 · 읽기 권한만 · windows-latest · Python 3.12 · 액션은 전체 커밋 SHA 고정 · 비밀 값(secrets.) 0 · 서명 단계 0 · 올리는 산출물은 허용 목록뿐(압축 파일·SHA256SUMS·PACKAGE_INFO.*,
    폴더는 release) · 보존 14일 · 없으면 실패 · 우리 빌드 스크립트를 실행 · 시험 빌드 옵션(--allow-missing-gate) 없음."""
    import fnmatch
    problems = []
    code = "\n".join(line for line in text.replace("\r\n", "\n").split("\n") if not line.lstrip().startswith("#"))
    block = _top_block(code, "on")
    triggers = []
    for line in block or []:
        match = re.match(r"^  ([a-z_]+):", line)
        if match:
            triggers.append(match.group(1))
        elif line.strip() and not line.startswith(" "):
            triggers += re.findall(r"[a-z_]+", line)
    if sorted(set(triggers)) != ["workflow_dispatch"]:
        problems.append(f"on: 은 workflow_dispatch 하나여야 한다({sorted(set(triggers))})")
    permissions = [line.strip() for line in (_top_block(code, "permissions") or []) if line.strip()]
    if permissions != ["contents: read"]:
        problems.append(f"최상위 permissions 는 contents: read 하나여야 한다({permissions})")
    if re.search(r"\bwrite(-all)?\b", code):
        problems.append("쓰기 권한 낱말(write)이 있다")
    runners = re.findall(r"runs-on:\s*(\S+)", code)
    if runners != ["windows-latest"]:
        problems.append(f"runs-on 은 windows-latest 하나({runners})")
    if not re.search(r"python-version:\s*['\"]?3\.12['\"]?\s*$", code, re.M):
        problems.append("파이썬 3.12 를 쓴다")
    for ref in re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", code, re.M):
        if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref):
            problems.append(f"액션이 전체 커밋 SHA 로 고정되지 않았다: {ref}")
    for word in ("secrets.", "github.token", "GITHUB_TOKEN"):
        if word in code:
            problems.append(f"비밀 값을 쓴다: {word}")
    for word in ("signtool", "Set-AuthenticodeSignature", "trusted-signing", "azure/", "certificate", ".pfx", "AZURE_"):
        if word.lower() in code.lower():
            problems.append(f"서명 단계 낱말: {word}")
    if "packaging/build_package.py" not in code:
        problems.append("packaging/build_package.py 를 실행하지 않는다")
    if "--allow-missing-gate" in code:
        problems.append("시험 빌드 옵션 --allow-missing-gate 를 쓴다(관문 없는 소스를 내보내게 된다)")
    uploads = _upload_steps(code)
    if not uploads:
        problems.append("upload-artifact 가 없다")
    for step in uploads:
        entries = _upload_paths(step)
        if not entries:
            problems.append("upload-artifact 의 path 를 읽지 못했다")
        for entry in entries:
            cleaned = entry.replace(chr(92), "/")
            folder, _, leaf = cleaned.rpartition("/")
            allowed = fnmatch.fnmatchcase(leaf, "ChanceBlogDesktop-*-win64.zip") or leaf in ("SHA256SUMS", "PACKAGE_INFO.md", "PACKAGE_INFO.json")
            if not allowed:
                problems.append(f"허용 목록 밖의 산출물: {entry}")
            elif not folder.endswith("/release"):
                problems.append(f"release 폴더 밖의 산출물: {entry}")
        if not re.search(r"^\s*retention-days:\s*14\s*$", step, re.M):
            problems.append("retention-days: 14 가 아니다")
        if not re.search(r"^\s*if-no-files-found:\s*error\s*$", step, re.M):
            problems.append("if-no-files-found: error 가 아니다")
    return problems


def sample_info(variant="outer", *, gate=True, failed=(), scan=None, files=None, signed=False, trial=False):
    state = {"commit": FAKE_COMMIT, "tree": FAKE_TREE, "clean": True, "dirty_count": 0, "committed_epoch": COMMIT_EPOCH, "committed_utc": "2026-11-11T01:00:00Z"}
    requirements = make_manifest.parse_requirements((PACKAGING / "requirements-package.txt").read_text(encoding="utf-8"))
    dependencies = [{"name": item["name"], "version": item["version"], "role": item["role"], "license": "MIT", "fingerprint": "sha256:" + "1" * 64, "files": 3} for item in requirements]
    files = files if files is not None else {f"{pkgcommon.EXE_NAME}.exe": "a" * 64, "VERSION": "b" * 64, "vendor/VENDOR.json": "c" * 64, "vendor/pipeline/gates.py": "d" * 64, "vendor/pipeline/secret_patterns.py": "e" * 64}
    build = make_manifest.default_build_record(["python", "-m", "PyInstaller", "--onedir"], tool="PyInstaller 6.22.3", env={"PYTHONHASHSEED": "0", "SOURCE_DATE_EPOCH": "1"}, gate_override=not gate)
    signing = {"signed": signed, "exe": "signed" if signed else "unsigned", "summary": make_manifest.SIGNING_TEXT, "signed_third_party_binaries": 3}
    kwargs = {}
    if variant == "outer":
        kwargs = dict(package={"name": pkgcommon.zip_name(VERSION), "sha256": "f" * 64, "bytes": 12345}, scan=scan, built_utc="2026-11-11T02:00:00Z",
                      selftest={"passed": ["utf8_mode"], "failed": list(failed), "skipped": [], "gate_present": gate, "gate_override": not gate}, host={"python": "3.12.10"})
    return make_manifest.build_info(variant=variant, version=VERSION, git=state, requirements=requirements, python_version="3.12.10", lock_sha256="9" * 64, build=build,
                         dependencies=dependencies, files=files, signing=signing, trial=trial, **kwargs)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
