"""설치 파일(Inno Setup) 만들기 시험 도우미(시험이 아니다) — `packaging/build_installer.py` 를 불러오고, 진짜 `build_package.build` 를 가짜 단계로 한 번 돌려 출력 폴더(묶음·압축 파일·정보 파일)를 만들고,
ISCC 없이 도는 가짜 바깥 세계(`FakeHost`)를 준다. PyInstaller·Inno Setup·네트워크 없이 돈다(CI 에는 PyInstaller 가 없다 — D-32).

시험 파일들이 `import installer_build_support as bs` 로 쓴다. `packaging_support` 를 먼저 불러 `packaging/` 를 import 경로에 올린다.
이 도우미는 스파이크(`packaging/spike/`·`tests/installer_spike_*.py`)를 쓰지 않는다 — 그 폴더는 나중에 지워진다.
"""
import atexit
import ntpath
import shutil
import tempfile
from pathlib import Path

import packaging_support as ps

import build_installer as bi  # noqa: E402  (packaging_support 가 packaging/ 를 import 경로에 올렸다)

pc = ps.pkgcommon
bp = ps.build_package
mm = ps.make_manifest

ISCC_PATH = "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"           # 가짜 세계의 ISCC — 이 PC 의 디스크에는 없다
ENGINE_LINE = "Compiler engine version: Inno Setup 6.7.1"
ISS_PATH = ps.PACKAGING / "ChanceBlogDesktop.iss"


def norm(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def compile_text(version="6.7.1", extra=""):
    return f"Compiler engine version: Inno Setup {version}\n{extra}Successful compile\n"


class FakeHost:
    """`build_installer.Host` 와 같은 모양의 가짜 — 윈도 러너 이미지에는 Inno Setup 6.7.1 이 실제로 깔려 있으므로(CI) 진짜 디스크·레지스트리를 보지 않는다.
    `found` 는 가짜 세계에 있는 파일들, `registry` 는 제거 항목 `(이름, 판, 설치 위치)` 목록, `compile_text` 는 ISCC 가 낼 글(`None` 이면 6.7.1 을 밝힌다)."""

    def __init__(self, *, found=(ISCC_PATH,), on_path=True, environ=None, platform="win32", compile_text=None, registry=(), file_versions=("0.0.0.0", "0.0.0.0"), exit_code=0, make_setup=True,
                 setup_bytes=2048, timed_out=False):
        self.platform = platform
        self.environ = dict(environ or {})
        self.found = [norm(path) for path in found]
        self.shown = list(found)
        self.on_path = on_path
        self.compile_output = (ENGINE_LINE + "\n") if compile_text is None else compile_text
        self.registry = list(registry)
        self.versions = tuple(file_versions)
        self.exit_code = exit_code
        self.make_setup = make_setup
        self.setup_bytes = setup_bytes
        self.timed_out = timed_out
        self.calls = []
        self.hashed = []

    def which(self, name):
        return self.shown[0] if self.on_path and self.shown and name.lower() == "iscc.exe" else None

    def is_file(self, path):
        return norm(path) in self.found

    def registry_entries(self):
        return list(self.registry)

    def file_versions(self, path):
        return self.versions

    def sha256(self, path):
        self.hashed.append(str(path))
        return pc.sha256_bytes(("fake-iscc:" + norm(path)).encode("utf-8"))

    def run_iscc(self, args, *, timeout, cwd=None):
        self.calls.append({"args": list(args), "timeout": timeout, "cwd": str(cwd) if cwd else None})
        if self.timed_out:
            return bi.HostResult(None, "", float(timeout), timed_out=True)
        out_dir = next(item[2:] for item in args if str(item).startswith("/O"))
        base = next(item[2:] for item in args if str(item).startswith("/F"))
        if self.make_setup and self.exit_code == 0:
            target = Path(out_dir) / (base + ".exe")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"" if self.setup_bytes == 0 else ps.pe_bytes(size=self.setup_bytes))
        return bi.HostResult(self.exit_code, self.compile_output, 0.1)


def make_out(root, *, trial=False):
    """진짜 `build_package.build` 를 가짜 단계로 한 번 돌려 출력 폴더를 만든다(git 필요) → (출력 폴더, 빌드 결과). 시험 빌드면 관문 없는 소스 표시(TESTBUILD)가 붙는다."""
    root = Path(root)
    repo = ps.make_build_repo(root / "repo")
    selftest = ps.selftest_text(overrides={"capabilities": ("fail", pc.GATE_MISSING_TEXT)}) if trial else None
    fake = ps.FakeBuild(root, repo, selftest=selftest)
    out = root / "out"
    result = bp.build(bp.Options(repo=repo, out_dir=out, skip_scan=True, allow_missing_gate=trial), steps=fake.steps, say=lambda text: None)
    return out, result


_SHARED = {}


def shared_outs():
    """가짜 빌드 출력 폴더 둘(정식·시험 빌드)을 이 프로세스에서 한 번만 만든다 → (정식, 시험). 시험마다 `copy_out` 으로 사본을 쓴다(git 호출을 줄여 시험이 빠르다)."""
    if "good" not in _SHARED:
        root = Path(tempfile.mkdtemp(prefix="instkit-shared-"))
        atexit.register(shutil.rmtree, str(root), True)
        _SHARED["good"] = make_out(root / "good")[0]
        _SHARED["trial"] = make_out(root / "trial", trial=True)[0]
    return _SHARED["good"], _SHARED["trial"]


def copy_out(source, target):
    shutil.copytree(source, target)
    return Path(target)


def temp_dir():
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
