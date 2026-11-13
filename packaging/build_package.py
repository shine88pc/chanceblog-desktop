"""개인 PC 제한 시험용 Package(예: 0.1.0-preview.1) 만들기 — 같은 커밋·같은 잠금 파일의 도구·같은 Python 이고 묶음에 들어가는 DLL 이 같은 곳(가상환경·기본 Python·Windows 폴더)에서 오면 같은 압축 파일이 나오도록(재현 가능하게) 만든다.

사용(저장소 맨 위 폴더에서, 잠금 파일의 도구가 설치된 Python 3.12 로): python packaging/build_package.py [--out-dir 폴더] [--skip-scan] [--allow-missing-gate]
순서: ① 작업 트리가 깨끗한지(아니면 거절)·VERSION·잠금 파일과 설치된 도구가 같은지 확인 → ② PyInstaller(`--onedir --windowed`, GUI 전용 시작 파일 `packaging/gui_entry.py`,
`--python-option "X utf8"`) → ③ 실행 파일 옆에 `vendor/`·`VERSION`·`LICENSES/` 를 배치(코드의 경로 가정을 고치지 않고 빌드가 정확히 놓는다) → ④ 묶음 안 `PACKAGE_INFO.*` →
⑤ 묶음 실행 파일의 `--selftest`(실패하면 산출물을 만들지 않는다) → ⑥ 결정적 zip(시각·순서·압축 수준 고정) → ⑦ 압축 파일 옆 `PACKAGE_INFO.*`·`SHA256SUMS`(+ 읽기 전용 악성코드 검사).
결정적으로 만드는 방법: 환경 변수 `PYTHONHASHSEED=0`·`SOURCE_DATE_EPOCH=<커밋 시각>`, zip 의 항목 시각은 커밋 시각·순서는 경로 순·압축 수준 9 고정, 묶음 안 정보 파일에는 시계를 넣지 않는다.
PyInstaller 는 묶을 DLL 이 부르는 DLL 을 PATH 순서대로 찾으므로(PATH 앞의 자바·Git·사내 프로그램 폴더 DLL 이 묶음에 들어온다) PyInstaller 를 부를 때 PATH 는 가상환경·기본 Python·Windows 폴더만으로 좁힌다(D-468).
시스템·보안 설정을 바꾸지 않고, 네트워크를 쓰지 않으며, 지우는 곳은 이 도구가 만든 출력 폴더(표지 파일 `.chanceblog-package-out`) 안의 work·spec·dist·bundle·release 뿐이다. 표준 라이브러리만 쓴다(PyInstaller 는 하위 프로세스로 부른다).
외부 쓰기 관문(`chanceblog_desktop.capabilities`) 모듈이 아직 없는 소스는 `--allow-missing-gate` 로 시험 빌드만 만들 수 있고, 시험 빌드는 압축 파일·묶음 폴더 이름에 `TESTBUILD` 가 붙고 정보 파일·화면에도 그렇게 적힌다(개인 PC 로 보내지 않는다).
"""
from __future__ import annotations

import argparse
import ast
import json
import ntpath
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from importlib import metadata
from pathlib import Path, PureWindowsPath

import make_manifest as mm
import pkgcommon as pc

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "dist" / "package"
ENTRY_RELATIVE = "packaging/gui_entry.py"
OUT_SUBFOLDERS = ("work", "spec", "dist", "bundle", "release")
LICENSE_SOURCE_DIR = "packaging/LICENSES"
BINARY_SUFFIXES = (".exe", ".dll", ".pyd")
TEXT_SUFFIXES = (".py", ".pyi", ".json", ".txt", ".md", ".xml", ".cfg", ".ini", ".toml", ".yml", ".yaml", ".html", ".js", ".css", ".csv")
TEXT_SCAN_LIMIT = 5 * 1024 * 1024
BUNDLE_ENV = {"PYTHONHASHSEED": "0", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
PATH_POLICY = "narrow-v1"                              # PyInstaller 에 주는 PATH 의 정책 이름 — 어느 폴더를 넣는가가 바뀌면 올린다. 정보 파일의 결정적 빌드 환경 기록에 적는다(D-468)
PATH_SEPARATOR = ";"                                   # 윈도의 PATH 구분자 — 시험이 어느 운영체제에서나 같은 글을 보도록 이 PC 의 구분자 상수 대신 고정한다(빌드는 윈도에서만 돈다)
SHOWN_PROBLEMS = 6                                     # 묶음 점검 실패 문장에 그대로 적는 문제 수 — 나머지는 건수와 출처 폴더별 요약으로 알린다(D-468)
SHOWN_FOLDERS = 8                                      # 출처 폴더별 요약에 이름을 적는 폴더 수 — 나머지는 곳 수와 건수만
ORIGIN_MARKER = "(출처 "                               # `binary_origin_problems` 가 문제 글에 붙이는 표지(이름(출처 경로)) — 요약이 같은 표지로 읽는다
UNKNOWN_FOLDER = "(폴더를 알 수 없음)"
# 개발용 가상환경에 같이 깔린 것이 묶음에 새어 들어오지 않았는지 보는 이름(묶음 안에 있으면 거절)
UNEXPECTED_BUNDLED = ("PIL", "webview", "clr_loader", "pythonnet", "bottle", "proxy_tools", "cffi", "pycparser", "_cffi_backend", "typing_extensions.py")
QT_FILES = ("PySide6/plugins/platforms/qwindows.dll", "PySide6/plugins/imageformats/qjpeg.dll", "PySide6/plugins/imageformats/qwebp.dll", "PySide6/plugins/imageformats/qsvg.dll")
# 앱이 쓰지 않는 Qt 네트워크 — `PySide6/__init__.py` 안의 `from . import QtNetwork`(OpenSSL 폴더가 있을 때만 실행) 때문에 PyInstaller 가 이것을 묶고, 그 훅이 빌드 PC 의 PATH 에서
# OpenSSL `-x64` DLL 을 찾아 묶음에 넣었다(다른 프로그램의 DLL 이 묶음에 새고 압축 파일이 PATH 에 달려 있었다 — D-415). 빼고, 다시 들어오면 빌드가 거절한다.
# `PySide6/Qt6Network.dll` 은 빼도 남는다 — `PySide6/plugins/generic/qtuiotouchplugin.dll`(Qt 의 TUIO 터치 플러그인)이 정적으로 가져오기 때문이다(PE 가져오기 표로 확인, 앱은 그 플러그인을 쓰지 않는다 —
# 환경 변수나 명령줄 `-plugin` 으로 불러야 쓰인다는 것은 Qt 동작에 대한 지식이고 실행으로 확인하지는 않았다). PySide6 폴더(허용된 뿌리)의 Qt 자신의 DLL 이라 막지 않는다 — 막을 것은 QtNetwork 모듈·TLS 플러그인·PATH 에서 온 OpenSSL 이다.
EXCLUDED_MODULES = ("PySide6.QtNetwork",)
UNWANTED_BUNDLED = ("libssl-3-x64.dll", "libcrypto-3-x64.dll", "PySide6/QtNetwork.pyd", "PySide6/plugins/tls", "PySide6/plugins/networkinformation")
OPENSSL_X64 = re.compile(r"lib(?:ssl|crypto)-[0-9_]+-x64[.]dll", re.IGNORECASE)      # PATH 의 다른 프로그램이 싣는 OpenSSL `-x64` 쌍 꼴(`-3-x64`·`-1_1-x64`) — 묶음 어디에 있어도 거절한다(N5)
PE_SUFFIXES = (".dll", ".pyd", ".exe")                  # 종류가 DATA 로 적혀 있어도 이 확장자면 실행 파일로 보고 출처를 본다(N5)
OUT_PATH_LIMIT = 130                                    # 출력 폴더 경로 글자 수 — 윈도 경로 한계 260자에 묶음 안 가장 긴 경로(약 110자)와 여유가 더해진다(N7)
RESERVED_DEVICE_NAMES = frozenset(("CON", "PRN", "AUX", "NUL") + tuple(f"COM{number}" for number in range(1, 10)) + tuple(f"LPT{number}" for number in range(1, 10)))
FORBIDDEN_NAME_CHARS = frozenset('<>:"|?*') | frozenset(chr(code) for code in range(32))
OUT_MARKER = ".chanceblog-package-out"                 # 이 도구가 만든 출력 폴더라는 표지 — 표지 없는 비어 있지 않은 폴더는 지우지 않고 거절한다(D-417)
GATE_SOURCE = ("src", "chanceblog_desktop", "capabilities.py")      # 외부 쓰기 관문 모듈의 소스 — 없으면 `--allow-missing-gate` 시험 빌드(TESTBUILD)
_RESULT_LINE = re.compile(r"^\[(통과|실패|건너뜀)\] ([A-Za-z0-9_]+): (.*)$")
STATUS_KEY = {"통과": "passed", "실패": "failed", "건너뜀": "skipped"}


# ---- 순수 부품(시험이 PyInstaller 없이 부른다) ----------------------------------

def read_version(repo):
    try:
        text = (Path(repo) / "VERSION").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise mm.BuildRefused("VERSION 파일을 읽지 못했어요(없거나 열 수 없어요).") from None
    number = pc.parse_version_text(text)
    if number is None:
        raise mm.BuildRefused("VERSION 파일을 읽지 못했거나 번호 모양이 아니에요.")
    return number


def zip_date_time(epoch):
    """압축 파일 항목에 적을 시각 — 커밋 시각(UTC)을 ZIP 이 쓰는 2초 단위·1980 년 이후로 맞춘다."""
    parts = list(time.gmtime(int(epoch))[:6])
    if parts[0] < 1980:
        return (1980, 1, 1, 0, 0, 0)
    parts[5] -= parts[5] % 2
    return tuple(parts)


def version_file_text(version, trial=False):
    """PyInstaller 가 실행 파일에 넣는 윈도 버전 정보(속성 → 자세히) — 시험판·개인 시험용 미서명 표시(시험 빌드면 '시험 빌드' 도)."""
    numbers = [int(part) for part in re.findall(r"\d+", re.split(r"[-+]", version, maxsplit=1)[0])][:3]
    numbers += [0] * (4 - len(numbers))
    tuple_text = ", ".join(str(number) for number in numbers)
    description = f"{pc.PRODUCT} ({pc.NOTICE}{' — 시험 빌드 ' + pc.TRIAL_TAG if trial else ''})"
    return (
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers=({tuple_text}), prodvers=({tuple_text}), mask=0x3f, flags=0xA, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([StringTable('041204B0', [\n"
        "      StringStruct('CompanyName', ''),\n"
        f"      StringStruct('FileDescription', '{description}'),\n"
        f"      StringStruct('FileVersion', '{version}'),\n"
        f"      StringStruct('InternalName', '{pc.EXE_NAME}'),\n"
        f"      StringStruct('OriginalFilename', '{pc.EXE_NAME}.exe'),\n"
        f"      StringStruct('ProductName', '{pc.PRODUCT}'),\n"
        f"      StringStruct('ProductVersion', '{version}')])]),\n"
        "    VarFileInfo([VarStruct('Translation', [1042, 1200])])\n"
        "  ]\n"
        ")\n"
    )


def gate_source_exists(repo):
    return Path(repo).joinpath(*GATE_SOURCE).is_file()


def hidden_imports(repo):
    """PyInstaller 가 코드만 봐서는 못 찾는 모듈 — vendor 파일이 쓰는 표준 모듈(vendor 는 실행할 때 파일로 읽는다)과 외부 쓰기 관문 모듈(문자열로 불러온다)."""
    names = set()
    vendor = Path(repo) / "vendor"
    for path in sorted(vendor.rglob("*.py")):
        names.update(pc.stdlib_imports(path.read_text(encoding="utf-8")))
    if gate_source_exists(repo):
        names.add("chanceblog_desktop.capabilities")
    return sorted(names)


def pyinstaller_args(repo, out, version_file, imports):
    """`python -m PyInstaller` 뒤에 붙일 인자 — 한 폴더(--onedir)·창 없음(--windowed)·UTF-8 모드·GUI 전용 시작 파일. UAC 관리자 옵션(--uac-admin)·한 파일(--onefile)은 쓰지 않는다."""
    repo, out = Path(repo), Path(out)
    args = ["--noconfirm", "--clean", "--onedir", "--windowed", "--name", pc.EXE_NAME,
            "--distpath", str(out / "dist"), "--workpath", str(out / "work"), "--specpath", str(out / "spec"),
            "--paths", str(repo / "src"), "--python-option", "X utf8", "--version-file", str(version_file), "--log-level", "INFO"]
    for name in EXCLUDED_MODULES:
        args += ["--exclude-module", name]
    for name in imports:
        args += ["--hidden-import", name]
    args.append(str(repo / ENTRY_RELATIVE))
    return args


def recorded_command(args, repo, out):
    """정보 파일에 적을 명령 — 이 PC 의 경로를 `<저장소>`·`<출력>` 으로 바꿔 어느 PC 에서나 같은 글이 되게 한다."""
    swap = lambda text: text.replace("\\", "/")      # noqa: E731
    out_text, repo_text = swap(str(Path(out))), swap(str(Path(repo)))
    shown = []
    for arg in args:
        text = swap(arg).replace(out_text, "<출력>").replace(repo_text, "<저장소>")
        shown.append(text)
    return ["python", "-m", "PyInstaller", *shown]


def env_value(environ, name):
    """환경 사전에서 이름이 같은 값 — 윈도의 환경 변수 이름은 대소문자를 가리지 않으므로(`SystemRoot`·`SYSTEMROOT`·`systemroot` 가 같다. `dict(os.environ)` 의 이름은 윈도에서 모두 대문자다) 대소문자 없이 찾는다. 없으면 None."""
    wanted = name.upper()
    for key, value in environ.items():
        if isinstance(key, str) and key.upper() == wanted:
            return value
    return None


def shown_folder(folder, home=None):
    """폴더 글을 알림 문장에 쓸 때의 모양 — 사용자 폴더 안이면 사용자 이름을 가린다(`C:/Users/<이름>/…` → `C:/Users/<사용자>/…`, 환경 변수 USERPROFILE 아래는 `%USERPROFILE%/…`). 러너 경로는 그대로다.
    새로 덧붙이는 요약·진행 줄에만 쓴다 — 실패 문장의 앞 문제 글은 예전 그대로 적는다."""
    path = PureWindowsPath(str(folder))
    home_path = PureWindowsPath(str(home)) if home else None
    if home_path is not None and len(home_path.parts) >= 2:                                    # 드라이브 맨 위(`C:/`)가 사용자 폴더일 리는 없다 — 그대로 두면 그 드라이브 전체가 가려진다
        try:
            return str(PureWindowsPath("%USERPROFILE%", *path.relative_to(home_path).parts))
        except ValueError:
            pass
    parts = list(path.parts)
    if path.drive and len(parts) >= 3 and parts[1].lower() == "users":
        parts[2] = "<사용자>"
        return str(PureWindowsPath(*parts))
    return str(path)


def narrowed_path_folders(environ, *, prefix=None, base_prefix=None, isdir=os.path.isdir):
    """PyInstaller 에 줄 PATH 의 폴더들(이 순서 그대로) — 이 가상환경과 그 Scripts · 기본 Python 과 그 DLLs·Scripts · Windows 폴더의 System32·Windows 자신·System32/Wbem 뿐이다(D-468).
    존재하는 폴더만, 같은 폴더(대소문자·슬래시·끝 구분자만 다른 것)는 한 번만. `environ` 에서는 SystemRoot(없으면 windir, 그것도 없으면 C:/Windows)만 읽고 입력의 PATH 는 읽지 않는다 —
    PATH 에 있던 자바(JDK)·Git·사내 프로그램 폴더가 PyInstaller 의 DLL 찾기에 끼어들지 못하게 하는 것이 목적이다. 허용 뿌리 검사(`allowed_roots`)와 같은 세 뿌리(가상환경·기본 Python·Windows 폴더)에서만 고른다.
    윈도의 PATH 는 세미콜론으로 나뉘므로 이름에 세미콜론이 든 폴더는 넣을 수 없어 거절한다(조용히 빼면 묶음이 달라진다)."""
    windows = env_value(environ, "SystemRoot") or env_value(environ, "windir") or "C:/Windows"
    prefix = str(sys.prefix if prefix is None else prefix)
    base_prefix = str(sys.base_prefix if base_prefix is None else base_prefix)
    wanted = [prefix, ntpath.join(prefix, "Scripts"), base_prefix, ntpath.join(base_prefix, "DLLs"), ntpath.join(base_prefix, "Scripts"),
              ntpath.join(windows, "System32"), windows, ntpath.join(windows, "System32", "Wbem")]
    folders, seen = [], set()
    for folder in wanted:
        folder = ntpath.normpath(folder)
        key = ntpath.normcase(folder)
        if key in seen or not isdir(folder):
            continue
        if PATH_SEPARATOR in folder:
            raise mm.BuildRefused(f"PATH 에 넣을 폴더 {shown_folder(folder)} 의 이름에 세미콜론(;)이 있어요 — 윈도의 PATH 는 세미콜론으로 폴더를 나누므로 넣을 수 없어요. 세미콜론이 없는 폴더에 가상환경을 만들어 주세요.")
        seen.add(key)
        folders.append(folder)
    return folders


def pyinstaller_env(epoch, environ=None, *, prefix=None, base_prefix=None, isdir=os.path.isdir):
    """PyInstaller 를 부를 환경 — 결정적 빌드 값을 정하고, `PYTHONPATH` 처럼 묶음을 오염시킬 수 있는 값은 빼고, **PATH 를 좁힌다**(D-468).
    PyInstaller 는 묶을 DLL 이 부르는 DLL 을 PATH 순서대로 찾는다 — PATH 앞에 자바(JDK)·Git·사내 프로그램 폴더가 있으면 그 폴더의 UCRT·VC 런타임 DLL 이 묶음에 들어오고 허용 뿌리 검사가 거절한다(GitHub 러너에서 실제로 났다).
    입력의 PATH 는 이름(`Path`·`PATH`·`path` 어느 대소문자든)과 값을 모두 버리고 `PATH` 하나만 `narrowed_path_folders` 의 폴더들로 쓴다 — 입력에 PATH 가 없어도 된다. 받은 사전은 바꾸지 않는다."""
    env = dict(os.environ if environ is None else environ)
    narrowed = PATH_SEPARATOR.join(narrowed_path_folders(env, prefix=prefix, base_prefix=base_prefix, isdir=isdir))
    for name in [name for name in env if isinstance(name, str) and name.upper() == "PATH"]:
        del env[name]
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONOPTIMIZE"):
        env.pop(name, None)
    env.update(BUNDLE_ENV)
    env["SOURCE_DATE_EPOCH"] = str(int(epoch))
    env["PATH"] = narrowed
    return env


def bundle_environment_record(epoch):
    """정보 파일에 적는 결정적 빌드 환경 — 실제로 정한 환경 변수 넷과, PATH 를 어떤 정책으로 좁혔는지(`PATH_POLICY` — 환경 변수 이름이 아니라 정책 이름이다. 폴더 목록은 PC 마다 달라 적지 않는다)."""
    return {**BUNDLE_ENV, "SOURCE_DATE_EPOCH": str(int(epoch)), "PATH_POLICY": PATH_POLICY}


def out_path_problem(text):
    """출력 폴더 경로 글에서 윈도가 말없이 바꾸거나 못 만드는 이름을 찾아 문제 글을 돌려준다('' 이면 문제 없음) — 이름 끝의 공백·점(윈도가 지워서 다른 폴더가 된다 — 저장소 안 입력 폴더 거절을 피해 가던 틈),
    쓸 수 없는 글자, `CON` 같은 예약 이름(D-440). 운영체제와 상관없이 윈도 규칙으로 본다."""
    path = PureWindowsPath(str(text))
    names = path.parts[1:] if path.anchor else path.parts
    for name in names:
        if name in (".", ".."):
            continue
        if name != name.rstrip(" ."):
            return f"출력 폴더 경로의 이름 {name!r} 이 공백이나 점으로 끝나요 — 윈도가 그 글자를 말없이 지워 다른 폴더가 돼요. 이름을 고쳐 주세요."
        if any(char in FORBIDDEN_NAME_CHARS for char in name):
            return f"출력 폴더 경로의 이름 {name!r} 에 윈도에서 쓸 수 없는 글자(< > : \" | ? * 나 제어 문자)가 있어요."
        if name.split(".")[0].rstrip(" ").upper() in RESERVED_DEVICE_NAMES:                  # 확장자 앞 공백(`CON .txt`)도 같은 이름으로 본다
            return f"출력 폴더 경로의 이름 {name!r} 은 윈도 예약 이름(CON·PRN·AUX·NUL·COM1 에서 COM9·LPT1 에서 LPT9)이라 폴더로 쓸 수 없어요."
    return ""


def plain_text(text):
    """윈도의 확장 경로 접두어(역슬래시 둘 + 물음표 + 역슬래시, UNC 는 그 뒤 `UNC` + 역슬래시)를 뗀 글 — `Path.resolve()` 가 접두어 붙은 경로를 돌려주면 저장소 경로와 글자 비교가 어긋난다(N1)."""
    back = chr(92)
    prefix = back * 2 + "?" + back
    if text.upper().startswith(prefix + "UNC" + back):
        return back * 2 + text[len(prefix) + 4:]
    if text.startswith(prefix):
        return text[len(prefix):]
    return text


def plain_path(path):
    return Path(plain_text(str(path)))


def is_root(path):
    """드라이브 맨 위(`D:/`)나 파일 시스템 맨 위(`/`)인가 — 맨 위의 부모는 자기 자신이다(경로 종류와 상관없이 같은 규칙)."""
    return path.parent == path


def git_ignores(repo, path):
    """git 이 이 폴더 안의 경로를 무시하는가 — 저장소 안 출력 폴더가 `dist/` 처럼 '무시되는 곳'인지 보는 데 쓴다(없는 경로도 .gitignore 규칙만으로 판단한다)."""
    try:
        relative = Path(path).resolve().relative_to(Path(repo).resolve()).as_posix()
        done = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", "--", relative + "/probe"], capture_output=True, timeout=60)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def safe_out_dir(out, repo, *, ignores=None):
    """출력 폴더가 저장소 자신이거나 저장소를 품거나 드라이브 맨 위면 거절 — 지우는 일이 있으니 가장 먼저 확인한다. 이름 끝 공백·점·쓸 수 없는 글자·예약 이름·너무 긴 경로도 거절 문장으로 알린다(D-440).
    저장소 안이라면 빌드 입력 폴더(src·vendor·packaging)나 .git 안은 안 되고, git 이 무시하는 곳(기본 dist/)이어야 한다(아니면 빌드가 저장소를 더럽힌다 — D-417)."""
    problem = out_path_problem(out)                                                            # 이름 점검이 먼저다 — 윈도가 이름을 말없이 바꾸기 전의 글로 본다
    if problem:
        raise mm.BuildRefused(problem)
    try:
        out, repo = plain_path(Path(out).resolve()), plain_path(Path(repo).resolve())
    except (OSError, ValueError, RuntimeError) as error:                                       # 그 밖의 이상한 경로(없는 드라이브·고리 링크 등)도 추적이 아니라 문장으로 끝낸다
        raise mm.BuildRefused(f"출력 폴더 경로를 읽지 못했어요({type(error).__name__}) — 다른 폴더를 골라 주세요.") from None
    if len(str(out)) > OUT_PATH_LIMIT:
        raise mm.BuildRefused(f"출력 폴더 경로가 {OUT_PATH_LIMIT}자를 넘어요(지금 {len(str(out))}자) — 윈도의 경로 길이 한계(260자)에 묶음 안의 가장 긴 경로(약 110자)가 더해지면 넘쳐요. 더 짧은 폴더를 골라 주세요.")
    if out == repo or out in repo.parents or is_root(out):
        raise mm.BuildRefused("출력 폴더가 저장소이거나 저장소를 품고 있거나 드라이브 맨 위예요 — 다른 폴더를 골라 주세요.")
    if repo in out.parents:
        first = out.relative_to(repo).parts[0]
        if first == ".git" or first in mm.INPUT_FOLDERS:
            raise mm.BuildRefused("출력 폴더가 빌드 입력 폴더(src·vendor·packaging)나 .git 안이에요 — dist 처럼 git 이 무시하는 폴더나 저장소 밖을 골라 주세요.")
        if not (ignores or git_ignores)(repo, out):
            raise mm.BuildRefused("출력 폴더가 저장소 안인데 git 이 무시하는 곳이 아니에요 — dist 처럼 무시되는 폴더나 저장소 밖을 골라 주세요(아니면 빌드 도중 작업 트리가 더러워져요).")
    return out


def _writable(function, path, _error):
    os.chmod(path, stat.S_IWRITE)
    function(path)


def clean_out_dir(out):
    """출력 폴더를 비운다 — 이 도구가 만든 폴더(표지 파일이 있다)거나 비어 있을 때만. 이미 있는 파일 경로·표지 없는 비어 있지 않은 폴더는 아무것도 지우지 않고 거절한다(D-417)."""
    out = Path(out)
    if out.exists() and not out.is_dir():
        raise mm.BuildRefused("출력 경로가 폴더가 아니라 이미 있는 파일이에요 — 다른 경로를 골라 주세요.")
    if out.is_dir() and not (out / OUT_MARKER).is_file() and any(out.iterdir()):
        raise mm.BuildRefused(f"출력 폴더가 비어 있지 않은데 이 도구가 만든 폴더가 아니에요(표지 파일 {OUT_MARKER} 이 없어요) — 새 폴더나 빈 폴더를 골라 주세요. "
                              "이 도구는 출력 폴더 안의 work·spec·dist·bundle·release 를 지워요.")
    for name in OUT_SUBFOLDERS:
        if (out / name).exists() and not (out / name).is_dir():
            raise mm.BuildRefused(f"출력 폴더 안의 {name!r} 가 폴더가 아니라 파일이에요 — 아무것도 지우지 않았어요. 그 파일을 치우거나 다른 폴더를 골라 주세요.")
    for name in OUT_SUBFOLDERS:
        target = out / name
        if target.exists():
            shutil.rmtree(target, onerror=_writable)
    out.mkdir(parents=True, exist_ok=True)
    (out / OUT_MARKER).write_bytes("이 폴더는 packaging/build_package.py 의 출력 폴더예요. 안의 work·spec·dist·bundle·release 는 다음 빌드 때 지워져요.\n".encode("utf-8"))


def copy_vendor(repo, bundle):
    """`vendor/` 를 한 글자도 바꾸지 않고 실행 파일 옆에 둔다(바이트 그대로) — 복사한 뒤 VENDOR.json 의 해시와 대조한다."""
    source, target = Path(repo) / "vendor", Path(bundle) / "vendor"
    shutil.copytree(source, target, copy_function=shutil.copyfile, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    manifest = json.loads((target / "VENDOR.json").read_text(encoding="utf-8"))
    wrong = [name for name, digest in manifest["files"].items() if not (target / name).is_file() or pc.sha256_file(target / name) != digest]
    if wrong:
        raise mm.BuildRefused("복사한 vendor 파일이 VENDOR.json 의 해시와 달라요: " + ", ".join(sorted(wrong)))


def find_pyinstaller_license(distribution=metadata.distribution):
    dist = distribution("pyinstaller")
    for item in dist.files or []:
        if item.name.upper() == "COPYING.TXT" and "licenses" in item.parts:
            return Path(dist.locate_file(item))
    raise mm.BuildRefused("PyInstaller 의 라이선스 파일(COPYING.txt)을 찾지 못했어요.")


def notices_text(version, packages, commit):
    """LICENSES/THIRD_PARTY_NOTICES.md — 이 묶음에 들어 있는 외부 구성 요소와 라이선스를 알리는 글(법률 판단이 아니다)."""
    runtime = {item["name"].lower(): item for item in packages if item["role"] == "runtime"}
    pyside = runtime.get("pyside6_essentials") or runtime.get("pyside6") or {"version": "?", "license": "?"}
    shiboken = runtime.get("shiboken6") or {"version": "?", "license": "?"}
    lines = [
        f"**{pc.NOTICE_LONG}**", "", f"# 제3자 고지 — {pc.PRODUCT} {version}", "",
        "이 글은 이 묶음에 들어 있는 외부 구성 요소와 그 라이선스를 알리는 목록입니다. **법률 판단이 아닙니다.** 라이선스 전문은 같은 폴더(LICENSES)의 파일에 있습니다.", "",
        "| 구성 요소 | 버전 | 라이선스 | 이 묶음에서의 쓰임 |", "|---|---|---|---|",
        f"| Qt for Python (PySide6 Essentials) | {pyside['version']} | {pyside['license']} — 이 묶음은 LGPL-3.0 조건으로 씁니다 | 화면(GUI) |",
        f"| Shiboken6 | {shiboken['version']} | {shiboken['license']} — 이 묶음은 LGPL-3.0 조건으로 씁니다 | PySide6 의 실행 라이브러리 |",
        "| Qt 6 라이브러리(DLL·플러그인) | PySide6 배포본과 같은 빌드 | LGPL-3.0 | 화면·그림 읽기(JPEG·WebP·SVG) |",
        f"| Python 런타임 | {sys.version.split()[0]} | PSF License(PYTHON-LICENSE.txt) | 프로그램 실행 |",
        "| PyInstaller 부트로더 | 빌드 도구 버전과 같음 | GPL-2.0 와 부트로더 예외(PYINSTALLER-COPYING.txt) | 실행 파일의 시작 부분 |",
        f"| vendor/ (chanceblog 의 파이프라인 파일 4개·스크립트 1개) | 저장소 커밋 {commit[:7]} | 이 저장소 소유자의 코드(한 글자도 바꾸지 않고 가져옴) | 글 검사·변환 |",
        "| OpenSSL 3 (libssl-3.dll·libcrypto-3.dll) | Python 3.12 가 함께 싣는 것 | Apache-2.0 | Python 의 암호·인증 표준 모듈(`_ssl` — 화면은 쓰지 않음). Qt 의 네트워크 파이썬 모듈(QtNetwork)·TLS 플러그인과 그 OpenSSL(`-x64` 이름)은 앱이 쓰지 않아 묶음에서 뺐고, 들어 있으면 빌드가 거절합니다(Qt6Network.dll 자체는 PySide6 의 Qt DLL 이고 Qt 의 터치 플러그인 qtuiotouchplugin.dll 이 가져오기 때문에 남습니다) |",
        "| libffi · SQLite · bzip2 · liblzma | Python 3.12 가 함께 싣는 것 | MIT · 퍼블릭 도메인 · BSD 계열 · 퍼블릭 도메인 | Python 표준 모듈(ctypes·sqlite3·bz2·lzma) |",
        "| Microsoft Visual C++ 런타임(VCRUNTIME140·MSVCP140) | 빌드한 PC 의 것 | Microsoft 의 재배포 가능 구성 요소 | Python·Qt 의 실행에 필요 |",
        "| Mesa 소프트웨어 OpenGL(opengl32sw.dll) | PySide6 배포본과 같음 | MIT 계열 | 그래픽 장치가 없을 때의 대체(Qt 가 싣는 것) |", "",
        "## LGPL(Qt·PySide6) 안내", "",
        "- 사용 방식: 동적 링크입니다. Qt DLL 과 PySide6 모듈은 `_internal` 폴더 안 `PySide6` 에 **각자 별개 파일**로 있고 하나의 실행 파일로 합치지 않았습니다.",
        "- 바꿔 끼우기: 같은 버전의 Qt 또는 PySide6 파일로 `_internal` 안의 해당 파일을 바꿔 넣을 수 있습니다.",
        f"- 소스: Qt 와 Qt for Python 의 소스는 Qt 프로젝트(`code.qt.io`)와 PySide 프로젝트(`pyside.org`)에서 받을 수 있습니다. 이 묶음의 PySide6 는 파이썬 패키지 저장소(PyPI)의 PySide6_Essentials {pyside['version']} 배포 파일 그대로이고 이 앱이 고치지 않았습니다.",
        "- 라이선스 전문: `LGPL-3.0.txt` 와 `GPL-3.0.txt`(LGPL 3.0 이 GPL 3.0 의 조건을 포함하므로 함께 둡니다).",
        f"- 이 앱의 소스: 공개 저장소 {mm.REPOSITORY} 의 커밋 {commit} (소스 전체는 그 저장소에 있습니다).", "",
        "## 알려진 한계", "",
        "- Qt 안에 들어 있는 제3자 구성 요소(libpng·FreeType·HarfBuzz·zlib·PCRE2 등)와 위 표 아래쪽 네 줄(OpenSSL·libffi 등·VC++ 런타임·Mesa)의 고지는 각 프로젝트의 문서를 따르며, 이 폴더가 그 전문을 모두 담았다고 보장하지 않습니다(표도 빠진 것이 있을 수 있습니다).",
        "- 이 묶음의 모든 DLL·확장 모듈은 빌드한 PC 의 가상환경·기본 Python·Windows 폴더에서 왔습니다(그 밖의 폴더에서 온 것이 있으면 빌드가 거절합니다).",
        "- ChanceBlog Desktop 자체의 라이선스는 아직 정해지지 않았습니다(D-13). 개인 시험용이며 다시 배포하지 마세요.",
        "- LGPL-3.0·GPL-3.0 전문은 이 묶음을 만든 PC 에 설치된 Git for Windows 의 라이선스 폴더에 있던 FSF 원문을 한 글자도 바꾸지 않고 복사한 것입니다(출처와 해시는 저장소의 packaging/LICENSES/SOURCES.txt).", ""]
    return "\n".join(lines)


def collect_licenses(repo, bundle, version, packages, commit, *, distribution=metadata.distribution, base_prefix=None):
    """LICENSES 폴더를 채운다 — 저장소의 LGPL·GPL 전문 + 이 PC 의 Python·PyInstaller 라이선스 + 만든 고지문. 하나라도 못 찾으면 거절."""
    folder = Path(bundle) / pc.LICENSES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    source = Path(repo) / LICENSE_SOURCE_DIR
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        if not (source / name).is_file():
            raise mm.BuildRefused(f"저장소에 {LICENSE_SOURCE_DIR}/{name} 이 없어요.")
        shutil.copyfile(source / name, folder / name)
    python_license = Path(base_prefix or sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise mm.BuildRefused("Python 의 LICENSE.txt 를 찾지 못했어요.")
    shutil.copyfile(python_license, folder / "PYTHON-LICENSE.txt")
    shutil.copyfile(find_pyinstaller_license(distribution), folder / "PYINSTALLER-COPYING.txt")
    (folder / "THIRD_PARTY_NOTICES.md").write_bytes(notices_text(version, packages, commit).encode("utf-8"))
    missing = [name for name in pc.LICENSE_FILES if not (folder / name).is_file()]
    if missing:
        raise mm.BuildRefused("LICENSES 에 빠진 파일: " + ", ".join(missing))


def allowed_roots(environ=None):
    """묶음에 들어갈 DLL·확장 모듈이 와도 되는 뿌리 — 이 가상환경·기본 Python·Windows 폴더. 빌드 PC 의 PATH 에 있는 다른 프로그램의 DLL 은 여기에 없다(D-415)."""
    environ = os.environ if environ is None else environ
    windows = environ.get("SystemRoot") or environ.get("windir") or "C:/Windows"
    return [sys.prefix, sys.base_prefix, windows]


def origin_problem(dest, source):
    """출처 문제 글 — `이름(출처 경로)`. 이 모양을 `origin_of` 가 되읽는다(시험이 둘이 어긋나지 않음을 지킨다)."""
    return f"{dest}{ORIGIN_MARKER}{source})"


def origin_of(problem):
    """`origin_problem` 이 만든 글에서 (이름, 출처 경로)를 읽는다. 그 모양이 아니면(묶음 점검의 다른 문제 글) None."""
    name, marker, rest = problem.partition(ORIGIN_MARKER)
    if not marker or not rest.endswith(")"):
        return None
    return name, rest[:-1]


def binary_origin_problems(toc_text, roots):
    """PyInstaller 의 묶음 목록(`COLLECT-00.toc`) 안 DLL·확장 모듈(BINARY·EXTENSION, 종류가 DATA 라도 `.dll`·`.pyd`·`.exe`)이 허용된 뿌리 밖에서 왔으면 그 이름·출처 글들 — 목록을 못 읽어도 문제다(출처를 모르는 채 내보내지 않는다)."""
    try:
        entries = ast.literal_eval(toc_text)[0]
        rows = [(str(dest), str(source), str(kind)) for dest, source, kind in entries]
    except (ValueError, SyntaxError, IndexError, TypeError, MemoryError, RecursionError):
        return ["PyInstaller 의 묶음 목록(COLLECT-00.toc)을 읽지 못했어요"]
    allowed = [PureWindowsPath(ntpath.normpath(root)) for root in roots if root]
    problems = []
    for dest, source, kind in rows:
        if kind == "EXECUTABLE" or (kind not in ("BINARY", "EXTENSION") and not dest.lower().endswith(PE_SUFFIXES)):
            continue                                                                          # 시작 파일은 빌드 산출물이고, 그 밖의 종류도 PE 확장자가 아니면 DLL 이 아니다
        path = PureWindowsPath(ntpath.normpath(source))                                       # `..` 를 풀어서 견준다 — 가상환경 안인 척 밖을 가리키는 줄을 걸러 낸다
        if not any(root == path or root in path.parents for root in allowed):
            problems.append(origin_problem(dest, source))
    return problems


def check_binary_origins(toc_path, roots=None):
    """`binary_origin_problems` 를 파일에 돌린다 — 파일이 없으면 그것도 문제."""
    try:
        text = Path(toc_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ["PyInstaller 의 묶음 목록 파일(COLLECT-00.toc)이 없어요"]
    return binary_origin_problems(text, allowed_roots() if roots is None else roots)


def origin_folder_counts(problems):
    """문제 글들을 출처 폴더별로 센다 → [(폴더, 건수), …](건수가 많은 폴더부터, 같으면 폴더 글자 순). 출처가 없는 문제 글(`origin_of` 가 None)은 세지 않는다. 폴더는 윈도 규칙으로 `..`·슬래시·대소문자를 풀어 같은 폴더끼리 합친다."""
    counts = {}
    for problem in problems:
        found = origin_of(problem)
        if found is None:
            continue
        folder = ntpath.dirname(ntpath.normpath(found[1])) or UNKNOWN_FOLDER
        key = ntpath.normcase(folder)
        shown, count = counts.get(key, (folder, 0))
        counts[key] = (shown, count + 1)
    return sorted(counts.values(), key=lambda item: (-item[1], ntpath.normcase(item[0])))


def problem_message(problems, *, home=None):
    """묶음 점검 실패 문장 — `묶음 점검에서 문제가 나왔어요(총 N건): 앞 6건(그대로) / …외 M건 — 출처 폴더별 건수: 폴더 N건 · …`. 6건 너머가 같은 폴더에서 왔는지 한 번에 알 수 있다(D-468).
    요약의 폴더는 사용자 폴더 이름을 가려 적는다(`shown_folder`) — 앞 문제 글은 예전 그대로다."""
    total = len(problems)
    text = f"묶음 점검에서 문제가 나왔어요(총 {total}건): " + " / ".join(problems[:SHOWN_PROBLEMS])
    if total > SHOWN_PROBLEMS:
        text += f" / …외 {total - SHOWN_PROBLEMS}건"
    home = env_value(os.environ, "USERPROFILE") if home is None else home
    counts = origin_folder_counts(problems)
    notes = []
    if counts:
        listed = " · ".join(f"{shown_folder(folder, home)} {count}건" for folder, count in counts[:SHOWN_FOLDERS])
        rest = counts[SHOWN_FOLDERS:]
        if rest:
            listed += f" · 그 밖 {len(rest)}곳 {sum(count for _folder, count in rest)}건"
        notes.append("출처 폴더별 건수: " + listed)
    without = total - sum(count for _folder, count in counts)
    if without:
        notes.append(f"출처를 알 수 없는 문제 {without}건")
    return text + (" — " + " · ".join(notes) if notes else "")


def bundle_problems(bundle):
    """묶음이 갖춰졌는지·섞이면 안 되는 것이 없는지 — 문제 글 목록(없으면 빈 목록)."""
    bundle = Path(bundle)
    problems = []
    exe = bundle / f"{pc.EXE_NAME}.exe"
    if not exe.is_file():
        problems.append(f"{pc.EXE_NAME}.exe 가 없어요")
    for needed in ("VERSION", "vendor/VENDOR.json", "vendor/pipeline/gates.py"):
        if not (bundle / needed).is_file():
            problems.append(f"{needed} 가 없어요")
    internal = bundle / "_internal"
    if not internal.is_dir():
        problems.append("_internal 폴더가 없어요")
    else:
        for relative in QT_FILES:
            if not (internal / relative).is_file():
                problems.append(f"Qt 구성 요소가 빠졌어요: {relative}")
        python_dll = f"python{sys.version_info[0]}{sys.version_info[1]}.dll"
        if not (internal / python_dll).is_file():
            problems.append(f"{python_dll} 이 없어요")
        for name in UNEXPECTED_BUNDLED:
            if (internal / name).exists():
                problems.append(f"개발 환경의 다른 패키지가 묶음에 섞였어요: {name}")
        for name in UNWANTED_BUNDLED:
            if (internal / name).exists():
                problems.append(f"앱이 쓰지 않는 네트워크 구성 요소(QtNetwork·OpenSSL)가 묶음에 들어갔어요: {name}")
    pattern = re.compile("|".join(pc.KEY_SHAPES))
    named_above = {f"_internal/{item}" for item in UNWANTED_BUNDLED}                              # 위에서 이름으로 이미 알린 것은 다시 적지 않는다
    for current, directories, names in os.walk(bundle):
        directories.sort()
        for name in sorted(names):
            path = Path(current) / name
            relative = path.relative_to(bundle).as_posix()
            reason = pc.forbidden_name(relative)
            if OPENSSL_X64.fullmatch(name) and relative not in named_above:
                problems.append(f"앱이 쓰지 않는 네트워크 구성 요소(QtNetwork·OpenSSL)가 묶음에 들어갔어요: {relative}")
            if reason:
                problems.append(f"묶음에 있으면 안 되는 파일({reason}): {relative}")
            elif name.lower().endswith(TEXT_SUFFIXES) and path.stat().st_size <= TEXT_SCAN_LIMIT:
                if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                    problems.append(f"키 모양 글이 든 파일: {relative}")
    return problems


def write_zip(source, zip_path, top, date_time):
    """결정적 zip — 항목은 경로 순, 시각은 `date_time` 하나, 속성·압축 수준 고정, 맨 위에 폴더 하나(`top`) — 같은 내용이면 같은 바이트."""
    source = Path(source)
    names = sorted(path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file())
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in names:
            info = zipfile.ZipInfo(f"{top}/{relative}", date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o100755 if relative.lower().endswith(BINARY_SUFFIXES) else 0o100644
            info.external_attr = mode << 16
            archive.writestr(info, (source / relative).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return names


def verify_zip(zip_path, top, files):
    """만든 zip 을 다시 열어 항목 이름·해시가 묶음 파일 목록(정보 파일 둘 포함)과 같은지 확인한다."""
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise mm.BuildRefused("만든 압축 파일이 깨졌어요.")
        got = {}
        for item in archive.infolist():
            if not item.filename.startswith(top + "/"):
                raise mm.BuildRefused("압축 파일 안에 맨 위 폴더 밖의 항목이 있어요.")
            got[item.filename[len(top) + 1:]] = pc.sha256_bytes(archive.read(item))
    expected = dict(files)
    if got != expected:
        raise mm.BuildRefused("압축 파일 안 내용이 묶음 폴더와 달라요.")


def parse_selftest(text):
    """묶음의 `--selftest` 출력 → {passed: [...], failed: [...], skipped: [...], failed_text: {...}}."""
    result = {"passed": [], "failed": [], "skipped": [], "failed_text": {}}
    for line in text.splitlines():
        match = _RESULT_LINE.match(line.strip())
        if match:
            bucket = STATUS_KEY[match.group(1)]
            result[bucket].append(match.group(2))
            if bucket == "failed":
                result["failed_text"][match.group(2)] = match.group(3)
    return result


def judge_selftest(parsed, *, allow_missing_gate):
    """자가 점검을 평가한다 → (통과 여부, 관문 확인됨, 관문 없는 소스로 넘어갔는지, 실패한 점검 이름들). 관문 모듈이 '없는' 실패만 `--allow-missing-gate` 로 넘길 수 있다 —
    모듈은 있는데 안에서 가져오기가 실패한 경우·상수가 열려 있는 경우는 넘기지 않는다(D-419)."""
    failed = list(parsed["failed"])
    gate_present = "capabilities" in parsed["passed"]
    override = False
    if allow_missing_gate and "capabilities" in failed and parsed["failed_text"].get("capabilities", "").startswith(pc.GATE_MISSING_TEXT):
        failed.remove("capabilities")
        override = True
    required = {"utf8_mode", "version_file", "package_info", "file_hashes", "licenses", "vendor_core", "capabilities", "uac_manifest", "qt_plugins", "qt_screens", "gui_only_entry", "data_dir_untouched"}
    absent = sorted(required - set(parsed["passed"]) - set(parsed["failed"]))
    ok = not failed and not absent and not parsed["skipped"]
    return ok, gate_present, override, failed + absent


def run_frozen_selftest(exe, *, runner=subprocess.run, timeout=300):
    """묶음 실행 파일에 `--selftest` 를 시킨다 — `PYTHONUTF8` 등 입출력 환경 변수를 모두 빼고(UTF-8 이 빌드 옵션 때문인지 보려고), 출력은 엄격한 UTF-8 로 읽는다."""
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONUTF8", "PYTHONIOENCODING", "QT_QPA_PLATFORM", "PYTHONPATH")}
    completed = runner([str(exe), "--selftest"], capture_output=True, timeout=timeout, env=env, cwd=str(Path(exe).parent))
    try:
        text = completed.stdout.decode("utf-8") + completed.stderr.decode("utf-8")
    except UnicodeDecodeError:
        raise mm.BuildRefused("묶음 실행 파일의 자가 점검 출력이 UTF-8 이 아니에요(UTF-8 모드 옵션이 안 먹었어요).") from None
    return completed.returncode, text


def run_pyinstaller(args, env, cwd, log_path):
    """PyInstaller 를 하위 프로세스로 돌려 출력을 로그 파일에 둔다(로그에는 이 PC 의 경로가 들어 있어 산출물에 넣지 않는다)."""
    command = [sys.executable, "-s", "-m", "PyInstaller", *args]
    with open(log_path, "wb") as log:
        completed = subprocess.run(command, env=env, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    return completed.returncode


# ---- 전체 순서 ---------------------------------------------------------------

class Options:
    def __init__(self, repo=REPO, out_dir=DEFAULT_OUT, skip_scan=False, allow_missing_gate=False):
        self.repo, self.out_dir, self.skip_scan, self.allow_missing_gate = Path(repo), Path(out_dir), skip_scan, allow_missing_gate


def build(options, *, steps=None, say=print):
    """전체 빌드. `steps` 로 PyInstaller·자가 점검·검사·시계를 바꿔 끼울 수 있다(시험용). 돌려주는 값: 만든 것들의 사전. 거절·실패는 `BuildRefused`."""
    steps = steps or {}
    if steps.get("platform", sys.platform) != "win32":                                          # 묶음은 윈도 실행 파일이다 — 다른 PC 에서는 PyInstaller 도 돌리지 않는다
        raise mm.BuildRefused("이 묶음(Windows 실행 파일)은 Windows 에서만 만들 수 있어요.")
    clock = steps.get("clock", time.time)
    started = clock()
    repo = options.repo.resolve()
    out = safe_out_dir(options.out_dir, repo, ignores=steps.get("ignores"))
    version = read_version(repo)
    trial = bool(options.allow_missing_gate and not gate_source_exists(repo))                  # 관문 모듈이 없는 소스를 옵션으로 넘긴 빌드 = 시험 빌드(TESTBUILD) — 개인 PC 로 보내지 않는다(D-416)
    say(f"[1/8] 준비 — 버전 {version}, 작업 트리·잠금 파일 확인")
    state = mm.require_clean(steps.get("git_state", mm.git_state)(repo))
    lock_text = (repo / mm.LOCK_RELATIVE).read_text(encoding="utf-8")
    requirements = mm.parse_requirements(lock_text)
    mm.check_installed(requirements, lookup=steps.get("lookup", metadata.version))
    epoch = state["committed_epoch"]
    # PyInstaller 에 줄 환경(PATH 를 좁힌다)은 출력 폴더를 비우기 전에 만든다 — PATH 에 넣을 수 없는 폴더 이름(세미콜론)이면 아무것도 지우지 않고 거절한다
    env = pyinstaller_env(epoch)
    clean_out_dir(out)
    version_file = out / "version_info.txt"
    version_file.write_bytes(version_file_text(version, trial).encode("utf-8"))               # 줄 끝 LF 그대로(윈도의 write_text 는 CRLF 로 바꾼다)
    imports = hidden_imports(repo)
    args = pyinstaller_args(repo, out, version_file, imports)
    folders = [folder for folder in env["PATH"].split(PATH_SEPARATOR) if folder]
    home = env_value(os.environ, "USERPROFILE")
    say(f"[2/8] PyInstaller(--onedir --windowed, UTF-8 모드) — 보통 1분 안팎 · PATH 는 {len(folders)}곳으로 좁혀서 부름(" + "; ".join(shown_folder(folder, home) for folder in folders) + ")")
    code = steps.get("pyinstaller", run_pyinstaller)(args, env, out, out / "build.log")
    if code != 0:
        raise mm.BuildRefused(f"PyInstaller 가 실패했어요(종료 코드 {code}) — {out / 'build.log'} 를 보세요.")
    top = pc.top_folder(version, trial)
    bundle = out / "bundle" / top
    bundle.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(out / "dist" / pc.EXE_NAME), str(bundle))
    say("[3/8] 배치 — vendor·VERSION·LICENSES 를 실행 파일 옆에")
    copy_vendor(repo, bundle)
    (bundle / "VERSION").write_bytes((version + "\n").encode("utf-8"))
    dependencies = mm.dependency_entries(requirements, distribution=steps.get("distribution", metadata.distribution))
    collect_licenses(repo, bundle, version, dependencies, state["commit"], distribution=steps.get("distribution", metadata.distribution), base_prefix=steps.get("base_prefix"))
    problems = steps.get("origin_check", check_binary_origins)(out / "work" / pc.EXE_NAME / "COLLECT-00.toc") + bundle_problems(bundle)
    if problems:
        raise mm.BuildRefused(problem_message(problems))
    say("[4/8] 묶음 안 PACKAGE_INFO 작성")
    record = mm.default_build_record(recorded_command(args, repo, out), tool=f"PyInstaller {steps.get('pyinstaller_version') or metadata.version('pyinstaller')}",
                                     env=bundle_environment_record(epoch), gate_override=trial)
    common = dict(repo=repo, bundle=bundle, version=version, build=record, state=state, lookup=steps.get("lookup", metadata.version),
                  distribution=steps.get("distribution", metadata.distribution), trial=trial)
    inner = mm.gather(variant="inner", **common)
    mm.write_inner(bundle, inner)
    say("[5/8] 묶음 실행 파일의 자가 점검(--selftest) — 실패하면 산출물을 만들지 않습니다")
    exe = bundle / f"{pc.EXE_NAME}.exe"
    code, text = steps.get("selftest", run_frozen_selftest)(exe)
    parsed = parse_selftest(text)
    ok, gate_present, override, bad = judge_selftest(parsed, allow_missing_gate=options.allow_missing_gate)
    if not ok:
        raise mm.BuildRefused("자가 점검이 통과하지 못했어요 — 실패 " + ", ".join(bad) + "\n" + text.strip() + f"\n(실패한 묶음 폴더: {bundle})")
    if override != trial:
        raise mm.BuildRefused(f"자가 점검의 관문 판정이 시험 빌드 표시와 달라요(시험 빌드 {'예' if trial else '아니요'} · 관문 모듈 없음 판정 {'예' if override else '아니요'}) — 소스를 확인해 주세요.")
    say("[6/8] 결정적 zip 만들기")
    release = out / "release"
    zip_path = release / pc.zip_name(version, trial)
    names = write_zip(bundle, zip_path, top, zip_date_time(epoch))
    files = mm.collect_files(bundle)
    files_with_info = dict(files)
    for info_name in pc.FILES_EXCLUDED_FROM_LIST:
        files_with_info[info_name] = pc.sha256_file(bundle / info_name)
    verify_zip(zip_path, top, files_with_info)
    say("[7/8] 압축 파일 옆 PACKAGE_INFO·SHA256SUMS 작성(읽기 전용 악성코드 검사 포함)")
    package = {"name": zip_path.name, "sha256": pc.sha256_file(zip_path), "bytes": zip_path.stat().st_size}
    scan = None if options.skip_scan else steps.get("scan", mm.scan_with_defender)([zip_path, bundle])
    check = {"passed": parsed["passed"], "failed": bad, "skipped": parsed["skipped"], "gate_present": gate_present, "gate_override": override, "exit_code": code}
    host = {"python": sys.version.split()[0], "platform": platform.platform(), "seconds": round(clock() - started, 1), "entries_in_zip": len(names)}
    outer = mm.gather(variant="outer", package=package, scan=scan, selftest=check, host=host, **common)
    if outer["files"] != inner["files"]:
        raise mm.BuildRefused("안 사본과 밖 사본의 파일 목록이 달라요.")
    mm.write_outer(release, outer, zip_path)
    say(f"[8/8] 끝 — {zip_path.name} {package['bytes']:,}바이트 · SHA-256 {package['sha256']}")
    return {"zip": zip_path, "sha256": package["sha256"], "bytes": package["bytes"], "bundle": bundle, "release": release, "info": outer, "scan": scan, "selftest": parsed,
            "gate_present": gate_present, "gate_override": override, "trial": trial}


def main(argv=None):
    parser = argparse.ArgumentParser(description="개인 PC 제한 시험용 Package 를 만든다(작업 트리가 깨끗해야 하고 잠금 파일의 도구가 설치돼 있어야 한다).")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT), help="출력 폴더(기본: 저장소의 dist/package — git 이 무시하는 곳)")
    parser.add_argument("--skip-scan", action="store_true", help="Windows Defender 읽기 전용 검사를 건너뛴다(정보 파일에 '검사 안 함' 으로 적힌다)")
    parser.add_argument("--allow-missing-gate", action="store_true",
                        help="외부 쓰기 관문(capabilities) 모듈이 아직 없는 소스로 시험 빌드를 만든다 — 압축 파일·묶음 폴더 이름에 TESTBUILD 가 붙고 정보 파일·화면에 '시험 빌드 — 개인 PC 로 보내지 않음' 이 적힌다. 모듈이 있는데 열려 있거나 가져오기가 실패하는 경우는 넘기지 않는다.")
    args = parser.parse_args(argv)
    try:
        build(Options(out_dir=args.out_dir, skip_scan=args.skip_scan, allow_missing_gate=args.allow_missing_gate))
    except mm.BuildRefused as refused:
        print(f"빌드를 멈췄어요: {refused}", file=sys.stderr)
        return 2
    except OSError as error:                                                                   # 파일을 만들고 옮기다 운영체제가 거절한 경우(권한·경로·디스크) — 파이썬 추적 대신 문장으로
        print(f"빌드를 멈췄어요: 파일을 다루다 운영체제가 거절했어요({type(error).__name__}: {error}). 출력 폴더의 이름·권한·남은 디스크를 확인해 주세요.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
