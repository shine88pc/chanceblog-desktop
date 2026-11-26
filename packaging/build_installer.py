"""설치 파일(Inno Setup) 만들기 — `build_package.py` 가 만든 **같은 `bundle/` 폴더**(압축 파일의 입력)에서 설치 파일 `ChanceBlogDesktop-<버전>-Setup.exe` 만 더 만든다(압축 파일은 그대로다).

사용(저장소 맨 위 폴더에서, 먼저 `build_package.py` 를 돌린 뒤): python packaging/build_installer.py [--out-dir 폴더] [--iscc ISCC.exe 경로] [--icon 아이콘.ico]
순서: ① 입력 확인(출력 폴더 표지·바깥 정보·**시험 빌드가 아님**·압축 파일 해시·SHA256SUMS) → ② 묶음 폴더 바이트가 압축 파일과 같은지(파일마다 SHA-256) → ③ 스크립트 `packaging/ChanceBlogDesktop.iss` 점검
→ ④ Inno 컴파일러(ISCC.exe) 찾기·판 확인 → ⑤ 컴파일 → ⑥ 컴파일러가 컴파일 출력에서 밝힌 판과 설치 파일 점검 → ⑦ 바깥 정보의 `installer`·`artifacts` 칸과 `SHA256SUMS` 갱신.
규칙: 윈도에서만 돈다(아니면 거절). 네트워크가 없다. 하위 프로세스는 ISCC 한 곳뿐이다(`Host.run_iscc` — 이름이 ISCC.exe 가 아니면 거절, 셸 없음, 비밀처럼 보이는 이름의 환경 변수는 넘기지 않는다).
Inno Setup 은 6.5.0 이상이어야 하고(`pkgcommon.INNO_MIN_VERSION`) 판은 컴파일러가 컴파일 출력에서 스스로 밝힌 것 → 레지스트리 → 파일 제품 판 → 파일 판 순으로 읽는다 — **읽지 못하거나 더 낮으면 설치 파일을 내놓지 않는다**(위협 T11).
서명하지 않는다. 설치 파일 이름·ID·무음 설치 인자는 `pkgcommon.py` 의 단일 출처를 쓴다. 지우는 곳은 이 도구가 만든 임시 폴더(출력 폴더 안의 `work/installer`)뿐이다. 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import ntpath
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import build_package as bp
import make_manifest as mm
import pkgcommon as pc

HERE = Path(__file__).resolve().parent
ISS_NAME = "ChanceBlogDesktop.iss"
ICON_NAME = "ChanceBlogDesktop.ico"                    # 있으면 설치 파일 아이콘으로 쓴다(운영자가 아이콘을 정하기 전에는 없다 — 기본 아이콘)
ISCC_NAME = "ISCC.exe"
ISCC_ENV = "CHANCEBLOG_ISCC"                           # ISCC.exe 의 전체 경로를 알려 주는 환경 변수(선택)
STAGE_PARTS = ("work", "installer")                    # 컴파일 결과를 먼저 두는 임시 폴더 — 다음 `build_package.py` 가 `work` 와 함께 지운다
PLACEHOLDER_LOCAL = "C:\\LocalAppData"                 # 기본 설치 폴더·데이터 폴더의 겹침을 빌드 때 확인할 때 쓰는 자리 표시(둘 다 사용자 앱 데이터 폴더 아래라 실제 값은 필요 없다 — 이 PC 의 경로·계정 이름을 쓰지 않는다)
STEPS = 7
COMPILE_SECONDS = 900
OUTPUT_TAIL = 1500                                     # 실패 문장에 싣는 컴파일 출력의 끝 글자 수
MAX_SETUP_BYTES = 200 * 1024 * 1024                    # 업데이트 매니페스트의 파일 하나 크기 상한과 같다(UPDATE 설계서 — 그보다 크면 나중에 서명·적용 단계가 거절한다)
DECODINGS = ("utf-8", "cp949")
SOURCE_LABELS = (("compile", "컴파일 출력"), ("registry", "레지스트리"), ("product", "파일 제품 판"), ("file", "파일 판"))
SECRETISH = re.compile(r"(?i)(token|secret|passw|credential|signing|private|api_?key|_key$)")     # 컴파일러 하위 프로세스에 넘기지 않는 환경 변수 이름
_VERSION_IN_TEXT = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?")
_ENGINE_LINE = re.compile(r"(?i)compiler engine version:\s*inno setup\s+(\d+\.\d+(?:\.\d+){0,2})")
_SUMS_LINE = re.compile(r"^([0-9a-f]{64})  ([^\s/\\]+)$")
_PLAIN_VALUE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")

# ---- 스크립트 점검(`.iss` 의 필수 줄과 있으면 안 되는 것) ----------------------------------------------------------
_APP_EXE = pc.EXE_NAME + ".exe"
ISS_SECTIONS = ("setup", "languages", "files", "icons", "run")
ISS_REQUIRED = {
    "setup": ("AppId=" + pc.INNO_APP_ID, "AppName=" + pc.PRODUCT, "AppVersion={#AppVersion}", "AppPublisher=" + pc.INNO_PUBLISHER, "DefaultDirName={autopf}\\" + pc.INSTALL_DIR_NAME,
              "DisableProgramGroupPage=yes", "PrivilegesRequired=lowest", "OutputDir={#OutputDir}", "OutputBaseFilename={#OutBase}", "Compression=lzma2/max", "SolidCompression=yes",
              "CloseApplications=yes", "RestartApplications=yes", "WizardStyle=modern", "UninstallDisplayIcon={app}\\" + _APP_EXE, "ArchitecturesInstallIn64BitMode=x64compatible"),
    "languages": ('Name: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"',),
    "files": ('Source: "{#SourceDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs',),
    "icons": ('Name: "{autoprograms}\\' + pc.PRODUCT + '"; Filename: "{app}\\' + _APP_EXE + '"',),
    "run": ('Filename: "{app}\\' + _APP_EXE + '"; Flags: nowait postinstall skipifsilent',),
}
ISS_ICON_LINE = "SetupIconFile={#IconFile}"                # 이 줄은 `#ifdef IconFile` 안에서만 있을 수 있다
ISS_ICON_GUARD = "#ifdef IconFile"
ISS_PREPROCESSOR = ("#ifndef AppVersion", "#error AppVersion must be defined (/DAppVersion=version)", "#ifndef SourceDir", "#error SourceDir must be defined (/DSourceDir=bundle folder)",
                    "#ifndef OutputDir", '#define OutputDir "Output"', "#ifndef OutBase", '#define OutBase "ChanceBlogDesktop-" + AppVersion + "-Setup"', ISS_ICON_GUARD, "#endif")
ISS_FORBIDDEN = (                                       # (소문자 조각, 이유) — 코드 줄에 있으면 안 되는 상수·낱말. 구역 이름은 위의 구역 허용 목록이 따로 막는다
    (("{autodesktop}", "{userdesktop}", "{commondesktop}"), "바탕화면 바로가기를 만들어요"),
    (("{userstartup}", "{commonstartup}", "{autostartup}"), "시작 프로그램(자동 실행)을 만들어요"),
    (("{localappdata}", "{userappdata}", "{commonappdata}", "{userdocs}", "{commondocs}"), "사용자 데이터가 있는 곳(앱 데이터·문서)을 건드려요"),
    (("{%", "{reg:", "{code:", "{cmd"), "환경 변수·레지스트리·코드를 읽는 상수를 써요"),
    (("schtasks", "powershell", "cmd.exe", "taskkill", "reg.exe"), "예약 작업·셸·프로세스 끝내기를 불러요"),
    (("runonce", "hkcu", "hklm", "hkey_"), "레지스트리를 건드려요"),
)
ISS_FORBIDDEN_SECTIONS = {"uninstalldelete": "UninstallDelete — 제거할 때 파일·폴더를 지워 데이터 폴더가 지워질 수 있어요", "uninstallrun": "UninstallRun — 제거할 때 프로그램을 실행해요",
                          "installdelete": "InstallDelete — 설치할 때 파일·폴더를 지워요", "registry": "Registry — 레지스트리에 써요", "tasks": "Tasks — 바탕화면 아이콘 같은 선택 작업이에요",
                          "code": "Code — 스크립트 코드(시험용 로그 코드는 없앴어요)", "ini": "INI — 설정 파일에 써요", "dirs": "Dirs — 폴더를 따로 만들어요"}


def iss_problems(text):
    """`.iss` 스크립트 글이 규칙에 맞는지 — 문제 글 목록(없으면 빈 목록). 컴파일 전에 `build()` 가 같은 규칙을 걸고 시험이 변이로 규칙 자체를 시험한다.
    규칙: 구역은 [Setup]·[Languages]·[Files]·[Icons]·[Run] 다섯뿐(각각 한 번), 구역마다 필수 줄이 정확히 한 번씩 있고 그 밖의 줄이 없으며(`SetupIconFile` 만 `#ifdef IconFile` 안에서 하나 더 가능),
    전처리 줄은 허용 목록뿐, 코드 줄은 모두 ASCII, 바탕화면·시작 자동 실행·예약 작업·사용자 데이터 폴더·레지스트리를 가리키는 낱말이 없다(`[UninstallDelete]`·`[Registry]`·`[Tasks]`·`[Code]` 구역 0)."""
    if not isinstance(text, str) or not text.strip():
        return ["스크립트 글을 읽지 못했거나 비어 있어요."]
    problems = []
    seen = {name: [] for name in ISS_SECTIONS}
    headers = []
    section = None
    guards = []
    for number, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if not line.isascii():
            problems.append(f"{number}행: 코드 줄에 한글이나 ASCII 가 아닌 글자가 있어요(한글은 주석에만 — 한국어 화면은 Korean.isl 이 맡아요)")
            continue
        lowered = line.lower()
        for pieces, reason in ISS_FORBIDDEN:
            if any(piece in lowered for piece in pieces):
                problems.append(f"{number}행: {reason}")
        if line.startswith("#"):
            normalized = " ".join(line.split())
            if normalized not in ISS_PREPROCESSOR:
                problems.append(f"{number}행: 허용 목록에 없는 전처리 줄이에요: {normalized}")
            elif normalized.startswith(("#ifndef", "#ifdef")):
                guards.append(normalized)
            elif normalized == "#endif":
                if guards:
                    guards.pop()
                else:
                    problems.append(f"{number}행: 짝이 없는 #endif 예요")
            continue
        header = re.fullmatch(r"\[([A-Za-z]+)\]", line)
        if header:
            name = header.group(1).lower()
            if name in headers:
                problems.append(f"{number}행: 구역 [{header.group(1)}] 이 두 번 나와요")
            headers.append(name)
            section = name
            if name not in ISS_SECTIONS:
                problems.append(f"{number}행: 허용하지 않는 구역 [{header.group(1)}] — " + ISS_FORBIDDEN_SECTIONS.get(name, "이 구역은 쓰지 않아요"))
            continue
        if section is None or section not in seen:
            problems.append(f"{number}행: 허용된 구역 밖의 줄이에요: {line}")
            continue
        if line == ISS_ICON_LINE and section == "setup":
            if not guards or guards[-1] != ISS_ICON_GUARD:
                problems.append(f"{number}행: SetupIconFile 줄은 '#ifdef IconFile' 안에서만 있을 수 있어요(아이콘이 없으면 기본 아이콘)")
            continue
        if guards:
            problems.append(f"{number}행: 필수 줄이 조건(#if) 안에 있어요 — 조건이 거짓이면 조용히 빠져요: {line}")
        seen[section].append(line)
    if guards:
        problems.append("#if 줄에 짝이 맞는 #endif 가 없어요")
    for name in ISS_SECTIONS:
        if name not in headers:
            problems.append(f"구역 [{name.capitalize()}] 이 없어요")
        wanted = ISS_REQUIRED[name]
        for line in wanted:
            count = seen[name].count(line)
            if count == 0:
                problems.append(f"[{name.capitalize()}] 에 필수 줄이 없어요: {line}" + (" (AppId 의 여는 중괄호는 두 번 써요)" if line.startswith("AppId=") else ""))
            elif count > 1:
                problems.append(f"[{name.capitalize()}] 에 같은 줄이 {count}번 있어요: {line}")
        for line in seen[name]:
            if line not in wanted:
                problems.append(f"[{name.capitalize()}] 에 허용하지 않은 줄이 있어요: {line}")
    return problems


# ---- 명령 만들기(순수) -------------------------------------------------------------------------------------------------

def _plain(value, label):
    text = str(value)
    if not text or re.search(r'["\x00-\x1f]', text):
        raise mm.BuildRefused(f"ISCC 에 넘길 {label} 값이 비어 있거나 따옴표·제어 문자가 들어 있어요.")
    return text


def iscc_args(iscc, script, *, version, source_dir, out_dir, out_base, icon=None):
    """ISCC 컴파일 명령 — 목록이고 셸을 거치지 않는다. 값은 `/D` 정의 둘(버전·묶음 폴더)과 출력 위치(`/O`)·이름(`/F`)뿐이고 아이콘이 있을 때만 `/DIconFile=` 이 더해진다.
    서명 인자(`/S`)·AppId 정의는 없다(AppId 는 스크립트에 고정). 이름은 `pkgcommon.setup_name` 이 만든 것과 같아야 한다."""
    try:
        expected = pc.setup_name(str(version))[:-len(".exe")]
    except ValueError:
        raise mm.BuildRefused("버전 모양이 아니어서 컴파일 명령을 만들지 않아요.") from None
    if out_base != expected:
        raise mm.BuildRefused("설치 파일 이름이 버전에서 만든 이름과 달라요.")
    args = [_plain(iscc, "컴파일러 경로"), "/O" + _plain(out_dir, "출력 폴더"), "/F" + out_base, "/DAppVersion=" + str(version), "/DSourceDir=" + _plain(source_dir, "묶음 폴더")]
    if icon is not None:
        args.append("/DIconFile=" + _plain(icon, "아이콘 파일"))
    args.append(_plain(script, "스크립트 경로"))
    return args


# ---- 판 읽기(순수) -----------------------------------------------------------------------------------------------------

def version_numbers(text):
    """글 안에서 처음 나오는 '숫자.숫자(.숫자(.숫자))' → 정수 튜플(없으면 None)."""
    match = _VERSION_IN_TEXT.search(text) if isinstance(text, str) else None
    return tuple(int(part) for part in match.groups() if part is not None) if match else None


def real_version(numbers):
    """읽은 판 숫자 — 전부 0(0.0.0.0, 실행 파일의 버전 자원이 비었을 때)이거나 숫자가 하나뿐인 것은 읽은 것으로 치지 않는다(None)."""
    return tuple(numbers) if numbers and len(numbers) >= 2 and any(numbers) else None


def inno_text_version(text):
    """ISCC 가 컴파일 출력에서 스스로 밝힌 판 → 숫자 튜플 또는 None. 'Compiler engine version: Inno Setup 6.7.1' 줄만 읽는다(머리글의 큰 판 번호 하나나 다른 곳의 판 이야기는 읽지 않는다)."""
    found = _ENGINE_LINE.search(text) if isinstance(text, str) else None
    return real_version(version_numbers(found.group(1))) if found else None


def registry_version(entries, iscc_path):
    """레지스트리 제거 항목(이름, 판, 설치 위치)들 중 **이 컴파일러가 든 폴더**의 'Inno Setup' 항목의 판 → 숫자 튜플 또는 None. 설치 위치가 다르거나 비었거나 판이 비면 읽은 것으로 치지 않는다
    (다른 곳에 깔린 Inno 의 판으로 이 컴파일러를 판정하지 않는다)."""
    wanted = ntpath.normcase(ntpath.normpath(str(iscc_path or "")))
    for entry in entries or ():
        try:
            name, version, location = entry
        except (TypeError, ValueError):
            continue
        place = ntpath.normcase(ntpath.normpath(str(location))).rstrip("\\") if str(location).strip() else ""
        numbers = real_version(version_numbers(str(version)))
        if str(name).lower().startswith("inno setup") and numbers and place and wanted.startswith(place + "\\"):
            return numbers
    return None


def read_inno_version(host, iscc, compile_text=""):
    """Inno Setup 의 판을 읽는다 — 순서: ① 컴파일러가 컴파일 출력에서 스스로 밝힌 판 ② 레지스트리 제거 항목 ③ 파일 제품 판 ④ 파일 판(파일 판은 러너 이미지에서 0.0.0.0 으로 나왔다 — 결정 D-810).
    위에서부터 처음 읽힌 것을 쓰고 읽은 값 전부를 남긴다 → {numbers, source, reads, reason}. 하나도 안 읽히면 numbers 는 None 이다."""
    product_text, file_text = host.file_versions(iscc)
    reads = {"compile": inno_text_version(compile_text), "registry": registry_version(host.registry_entries(), iscc),
             "product": real_version(version_numbers(product_text)), "file": real_version(version_numbers(file_text))}
    shown = {key: (".".join(str(part) for part in value) if value else "") for key, value in reads.items()}
    for key, label in SOURCE_LABELS:
        if reads[key]:
            return {"numbers": reads[key], "source": label, "reads": shown, "reason": ""}
    raw = {"product": product_text, "file": file_text}
    why = [f"{label} " + (f"빈 값 {raw[key]}" if raw.get(key) else "읽히지 않음") for key, label in SOURCE_LABELS]
    return {"numbers": None, "source": "", "reads": shown, "reason": " · ".join(why)}


def judge_inno_version(read):
    """읽은 판을 판정한다 — 6.5.0 이상이면 숫자 튜플을 돌려주고, **읽지 못했거나 더 낮으면 BuildRefused**(위협 T11: 어떤 판인지 모르는 컴파일러로는 설치 파일을 만들지 않는다)."""
    numbers = real_version(read.get("numbers"))
    if not numbers:
        raise mm.BuildRefused(f"Inno Setup 컴파일러의 판을 읽지 못했어요({read.get('reason', '')}) — 어떤 판인지 모르는 컴파일러로는 설치 파일을 만들지 않아요.")
    if (tuple(numbers[:3]) + (0, 0, 0))[:3] < pc.INNO_MIN_VERSION:
        raise mm.BuildRefused(f"Inno Setup 판이 너무 낮아요: {'.'.join(str(item) for item in numbers)} — {'.'.join(str(item) for item in pc.INNO_MIN_VERSION)} 이상이어야 해요(한국어 안내 파일 Korean.isl 이 들어 있는 첫 판).")
    return tuple(numbers)


# ---- 바깥 세계 ---------------------------------------------------------------------------------------------------------

def decode_bytes(data):
    for encoding in DECODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class HostResult:
    def __init__(self, rc, out="", seconds=0.0, timed_out=False, error=""):
        self.rc, self.out, self.seconds, self.timed_out, self.error = rc, out, seconds, timed_out, error


class Host:
    """바깥 세계와 닿는 모든 것 — 도구 찾기·레지스트리·파일 판·해시·ISCC 실행·환경 변수. 시험은 이 클래스와 같은 모양의 가짜를 끼워 Inno 없이 흐름을 돌린다
    (윈도 러너 이미지에는 Inno Setup 이 실제로 깔려 있어 진짜 디스크를 직접 보면 '없다'는 가짜 세계에도 그것이 보인다)."""

    def __init__(self, environ=None):
        self.environ = dict(os.environ if environ is None else environ)
        self.platform = sys.platform

    def which(self, name):
        return shutil.which(name, path=bp.env_value(self.environ, "PATH"))

    def is_file(self, path):
        return Path(path).is_file()

    def sha256(self, path):
        return pc.sha256_file(path)

    def child_env(self):
        """컴파일러에 넘기는 환경 변수 — 이름이 비밀처럼 보이는 것(토큰·비밀·암호·서명 …)은 뺀다. 컴파일러는 그런 값이 필요 없다."""
        return {key: value for key, value in self.environ.items() if not SECRETISH.search(key)}

    def registry_entries(self):
        """레지스트리 제거 항목 중 이름이 'Inno Setup' 으로 시작하는 것의 (이름, 판, 설치 위치) 목록 — 읽기만 한다. 윈도가 아니면 빈 목록."""
        try:
            import winreg
        except ImportError:
            return []
        found = []
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY), (winreg.HKEY_CURRENT_USER, 0)):
            try:
                with winreg.OpenKey(hive, base, 0, winreg.KEY_READ | view) as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        key_name = winreg.EnumKey(root, index)
                        if not key_name.lower().startswith("inno setup"):
                            continue
                        with winreg.OpenKey(root, key_name) as key:
                            values = []
                            for value_name in ("DisplayName", "DisplayVersion", "InstallLocation"):
                                try:
                                    values.append(str(winreg.QueryValueEx(key, value_name)[0]))
                                except OSError:
                                    values.append("")
                            if values[0].lower().startswith("inno setup"):
                                found.append(tuple(values))
            except OSError:
                continue
        return found

    def file_versions(self, path):
        """실행 파일의 버전 자원 → (제품 판, 파일 판) 글. 읽지 못하면 ('', ''). 윈도 전용."""
        if sys.platform != "win32":
            return ("", "")
        import ctypes
        from ctypes import wintypes

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [("signature", wintypes.DWORD), ("struc_version", wintypes.DWORD), ("file_ms", wintypes.DWORD), ("file_ls", wintypes.DWORD), ("product_ms", wintypes.DWORD),
                        ("product_ls", wintypes.DWORD), ("flags_mask", wintypes.DWORD), ("flags", wintypes.DWORD), ("os", wintypes.DWORD), ("file_type", wintypes.DWORD),
                        ("file_subtype", wintypes.DWORD), ("date_ms", wintypes.DWORD), ("date_ls", wintypes.DWORD)]

        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        version.VerQueryValueW.restype = wintypes.BOOL
        name = str(path)
        size = version.GetFileVersionInfoSizeW(name, None)
        if not size:
            return ("", "")
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(name, 0, size, buffer):
            return ("", "")
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < ctypes.sizeof(FixedFileInfo) or not pointer.value:
            return ("", "")
        info = FixedFileInfo.from_address(pointer.value)
        if info.signature != 0xFEEF04BD:
            return ("", "")
        join = lambda high, low: f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}"      # noqa: E731
        return (join(info.product_ms, info.product_ls), join(info.file_ms, info.file_ls))

    def run_iscc(self, args, *, timeout=COMPILE_SECONDS, cwd=None):
        """ISCC 를 한 번 돌리고 끝을 기다린다 — **이 파일에서 하위 프로세스를 띄우는 유일한 곳**이다. 프로그램 이름이 ISCC.exe 가 아니면 거절하고, 셸을 거치지 않으며(목록 인자),
        표준 입력을 닫고, 출력은 관(pipe)이 아니라 임시 파일로 받는다(컴파일러가 자식을 남겨도 여기서 매달리지 않는다)."""
        program = str(args[0]) if args else ""
        if ntpath.basename(program).lower() != ISCC_NAME.lower():
            raise mm.BuildRefused("이 도구는 Inno Setup 컴파일러(ISCC.exe) 말고는 아무 프로그램도 실행하지 않아요.")
        began = time.monotonic()
        with tempfile.TemporaryFile() as out_file:
            try:
                done = subprocess.run([str(item) for item in args], stdin=subprocess.DEVNULL, stdout=out_file, stderr=subprocess.STDOUT, timeout=timeout, cwd=str(cwd) if cwd else None, env=self.child_env())
                code, timed_out = done.returncode, False
            except subprocess.TimeoutExpired:
                code, timed_out = None, True
            except OSError as error:
                return HostResult(-1, "", round(time.monotonic() - began, 1), error=type(error).__name__)
            out_file.seek(0)
            text = decode_bytes(out_file.read())
        return HostResult(code, text, round(time.monotonic() - began, 1), timed_out)


def find_iscc(host, explicit=None):
    """Inno Setup 컴파일러(ISCC.exe)의 위치 — 순서: 명령줄로 준 경로 → 환경 변수 `CHANCEBLOG_ISCC` → PATH → 잘 알려진 설치 폴더(Program Files 의 `Inno Setup 6`·사용자 프로그램 폴더). 못 찾으면 거절.
    준 경로가 없거나 이름이 ISCC.exe 가 아니면 다른 것으로 바꿔치기하지 않고 거절한다."""
    if explicit:
        if ntpath.basename(str(explicit)).lower() != ISCC_NAME.lower() or not host.is_file(explicit):
            raise mm.BuildRefused("--iscc 로 준 경로에 ISCC.exe 가 없어요.")
        return str(explicit)
    from_env = bp.env_value(host.environ, ISCC_ENV)
    if from_env:
        if ntpath.basename(from_env).lower() != ISCC_NAME.lower() or not host.is_file(from_env):
            raise mm.BuildRefused(f"환경 변수 {ISCC_ENV} 가 가리키는 곳에 ISCC.exe 가 없어요.")
        return from_env
    found = host.which(ISCC_NAME)
    if found:
        return str(found)
    folders = []
    for name in ("ProgramFiles(x86)", "ProgramFiles"):
        base = bp.env_value(host.environ, name)
        if base:
            folders.append(ntpath.join(base, "Inno Setup 6"))
    local = bp.env_value(host.environ, "LOCALAPPDATA")
    if local:
        folders.append(ntpath.join(local, "Programs", "Inno Setup 6"))
    folders += ["C:\\Program Files (x86)\\Inno Setup 6", "C:\\Program Files\\Inno Setup 6"]
    for folder in folders:
        candidate = ntpath.join(folder, ISCC_NAME)
        if host.is_file(candidate):
            return candidate
    raise mm.BuildRefused(f"Inno Setup 컴파일러(ISCC.exe)를 찾지 못했어요 — PATH 에 없고 잘 알려진 설치 폴더에도 없어요. Inno Setup 6.5.0 이상을 설치한 PC 에서 돌리거나 환경 변수 {ISCC_ENV} 나 --iscc 로 위치를 알려 주세요"
                          "(GitHub 의 윈도 러너에는 미리 깔려 있어요).")


# ---- 입력 확인(출력 폴더 → 정보 파일 → 압축 파일 → 묶음 폴더) -----------------------------------------------------------------

def parse_sums(text):
    """`SHA256SUMS`(`<해시 64자리 소문자>  <이름>` 한 줄씩) → {이름: 해시}. 모양이 틀리거나 이름이 겹치거나 비어 있으면 BuildRefused."""
    found = {}
    for line in str(text).splitlines():
        match = _SUMS_LINE.match(line)
        if match is None or match.group(2) in found:
            raise mm.BuildRefused("SHA256SUMS 의 줄 모양이 틀렸거나 같은 이름이 두 번 있어요.")
        found[match.group(2)] = match.group(1)
    if not found:
        raise mm.BuildRefused("SHA256SUMS 가 비어 있어요.")
    return found


def _read_json(path, what):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise mm.BuildRefused(f"{what}(정보 파일)을 읽지 못했어요 — 없거나 JSON 이 아니에요. 먼저 build_package.py 를 돌려 주세요.") from None
    if not isinstance(data, dict):
        raise mm.BuildRefused(f"{what}(정보 파일)이 JSON 객체가 아니에요.")
    return data


def read_inputs(out):
    """출력 폴더(`build_package.py` 가 만든 것)에서 설치 파일의 입력을 읽고 **싼 확인**을 한다 → 입력 사전. 맞지 않으면 BuildRefused.
    확인: 표지 파일 · 바깥 정보(outer·schema·제품) · **시험 빌드가 아님** · 관문·자가 점검 통과(release_eligible) · 버전 모양 · 압축 파일의 크기·해시가 정보 파일·SHA256SUMS 와 같음 ·
    묶음 폴더와 그 안 VERSION·안쪽 정보가 바깥 정보와 같음."""
    out = Path(out)
    if not (out / bp.OUT_MARKER).is_file():
        raise mm.BuildRefused(f"출력 폴더가 build_package.py 가 만든 폴더가 아니에요(표지 파일 {bp.OUT_MARKER} 이 없어요) — 먼저 build_package.py 를 돌리거나 --out-dir 을 확인해 주세요.")
    release = out / "release"
    info = _read_json(release / pc.INFO_JSON, "release 폴더의 PACKAGE_INFO.json")
    if info.get("variant") != "outer" or info.get("schema") != pc.SCHEMA or info.get("product") != pc.PRODUCT:
        raise mm.BuildRefused("release 폴더의 정보 파일이 바깥 정보(outer, schema 1)가 아니에요.")
    if info.get("trial") is not False:
        if info.get("trial") is True:
            raise mm.BuildRefused(f"시험 빌드({pc.TRIAL_TAG})에는 설치 파일을 만들지 않아요 — 개인 PC 로 보내지 않는 빌드예요. 관문 모듈이 있는 소스로 정식 빌드를 만든 뒤 다시 해 주세요.")
        raise mm.BuildRefused("정보 파일의 trial 칸을 읽지 못해 시험 빌드인지 알 수 없어요.")
    if info.get("release_eligible") is not True:
        raise mm.BuildRefused("관문·자가 점검을 통과하지 못한 빌드예요(release_eligible 이 참이 아니에요) — 설치 파일을 만들지 않아요.")
    version = info.get("version")
    if not isinstance(version, str) or pc.parse_version_text(version) != version:
        raise mm.BuildRefused("정보 파일의 버전이 버전 모양이 아니에요.")
    zip_path = release / pc.zip_name(version)
    package = info.get("package")
    if not isinstance(package, dict) or package.get("name") != zip_path.name or not isinstance(package.get("sha256"), str) or not isinstance(package.get("bytes"), int):
        raise mm.BuildRefused("정보 파일의 압축 파일 칸(package)이 틀렸어요.")
    if not zip_path.is_file():
        raise mm.BuildRefused(f"압축 파일 {zip_path.name} 이 release 폴더에 없어요.")
    if zip_path.stat().st_size != package["bytes"]:
        raise mm.BuildRefused("압축 파일의 크기가 정보 파일에 적힌 값과 달라요.")
    digest = pc.sha256_file(zip_path)
    if digest != package["sha256"]:
        raise mm.BuildRefused("압축 파일의 해시가 정보 파일에 적힌 값과 달라요.")
    try:
        sums = parse_sums((release / pc.SUMS_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        raise mm.BuildRefused("release 폴더의 SHA256SUMS 를 읽지 못했어요.") from None
    if sums.get(zip_path.name) != digest:
        raise mm.BuildRefused("SHA256SUMS 에 압축 파일 줄이 없거나 압축 파일의 해시와 달라요.")
    top = pc.top_folder(version)
    bundle = out / "bundle" / top
    if not bundle.is_dir():
        raise mm.BuildRefused(f"묶음 폴더 bundle/{top} 가 없어요 — 설치 파일은 압축 파일과 같은 묶음 폴더에서 만들어요.")
    try:
        number = (bundle / "VERSION").read_bytes()
    except OSError:
        raise mm.BuildRefused("묶음 폴더 안의 VERSION 파일을 읽지 못했어요.") from None
    if number != (version + "\n").encode("utf-8"):
        raise mm.BuildRefused("묶음 폴더 안의 VERSION 이 정보 파일의 버전과 달라요.")
    inner = _read_json(bundle / pc.INFO_JSON, "묶음 폴더 안의 PACKAGE_INFO.json")
    if inner.get("variant") != "inner" or inner.get("version") != version or (inner.get("git") or {}).get("commit") != (info.get("git") or {}).get("commit") or inner.get("files") != info.get("files"):
        raise mm.BuildRefused("묶음 폴더 안의 정보 파일(inner)이 바깥 정보와 어긋나요(버전·커밋·파일 목록).")
    return {"out": out, "release": release, "info": info, "version": version, "top": top, "bundle": bundle, "zip": zip_path, "package": {"name": package["name"], "sha256": digest, "bytes": package["bytes"]}}


def check_bundle_matches_zip(found):
    """**묶음 폴더의 바이트가 압축 파일과 같은지** 확인한다 — 폴더의 모든 파일 SHA-256 이 정보 파일의 목록과 같고, 압축 파일 안 항목(이름·해시)이 폴더 파일(정보 파일 둘 포함)과 정확히 같다.
    설치 파일은 이 폴더를 통째로 담으므로 둘이 같아야 설치형과 휴대용이 같은 프로그램이다. 다르면 BuildRefused."""
    bundle, info = found["bundle"], found["info"]
    files = mm.collect_files(bundle)
    if files != info.get("files"):
        raise mm.BuildRefused("묶음 폴더의 파일 목록(해시)이 정보 파일의 목록과 달라요 — 압축 파일을 만든 뒤 묶음 폴더가 바뀌었을 수 있어요. build_package.py 를 다시 돌려 주세요.")
    with_info = dict(files)
    for name in pc.FILES_EXCLUDED_FROM_LIST:
        path = bundle / name
        if not path.is_file():
            raise mm.BuildRefused(f"묶음 폴더 안에 {name} 이 없어요.")
        with_info[name] = pc.sha256_file(path)
    try:
        bp.verify_zip(found["zip"], found["top"], with_info)
    except (zipfile.BadZipFile, OSError):
        raise mm.BuildRefused("압축 파일을 다시 열지 못했어요(깨졌어요).") from None


def read_release(out):
    """입력 확인 전체 — `read_inputs`(싼 확인) 뒤에 `check_bundle_matches_zip`(파일마다 해시)."""
    found = read_inputs(out)
    check_bundle_matches_zip(found)
    return found


# ---- 전체 순서 ---------------------------------------------------------------------------------------------------------

class Options:
    def __init__(self, out_dir=bp.DEFAULT_OUT, iscc=None, icon=None):
        self.out_dir, self.iscc, self.icon = Path(out_dir), iscc, icon


def built_on(environ):
    """바깥 정보에 적는 '만든 곳' — GitHub 러너면 이미지 이름과 판(`win25-vs2026 20261116.315.1`), 아니면 `local`. 이 PC 의 이름·경로는 적지 않는다."""
    image, version = bp.env_value(environ, "ImageOS"), bp.env_value(environ, "ImageVersion")
    if image and version and _PLAIN_VALUE.match(image) and _PLAIN_VALUE.match(version):
        return f"{image} {version}"
    return "local"


def _tail(text):
    text = (text or "").strip()
    return text[-OUTPUT_TAIL:]


def _remove(path):
    """이 도구가 만든 임시 폴더를 지운다(읽기 전용 파일도) — 3.12 부터는 `onexc`, 그 전에는 `onerror`."""
    if not Path(path).exists():
        return

    def writable(function, target, _error):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable)
    else:
        shutil.rmtree(path, onerror=writable)


def _write_atomic(path, data):
    path = Path(path)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def build(options, *, host=None, say=print, iss_path=None):
    """전체 순서. `host` 로 바깥 세계(도구 찾기·ISCC 실행)를 바꿔 끼울 수 있다(시험용). 돌려주는 값: 만든 것들의 사전. 거절·실패는 `BuildRefused`이고 그때 release 폴더에는 새 설치 파일이 나오지 않는다."""
    host = host or Host()
    iss_path = Path(iss_path) if iss_path else HERE / ISS_NAME
    if host.platform != "win32":
        raise mm.BuildRefused("설치 파일(Setup)은 Windows 에서만 만들 수 있어요.")
    say(f"[1/{STEPS}] 입력 확인 — 출력 폴더 표지·바깥 정보·시험 빌드가 아님·압축 파일 해시")
    found = read_inputs(options.out_dir)
    version, release = found["version"], found["release"]
    name = pc.setup_name(version)
    say(f"[2/{STEPS}] 묶음 폴더와 압축 파일이 같은지 — 파일마다 SHA-256 (설치 파일은 이 폴더를 통째로 담아요)")
    check_bundle_matches_zip(found)
    say(f"[3/{STEPS}] 스크립트 점검 — {ISS_NAME}")
    try:
        script = iss_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        raise mm.BuildRefused(f"스크립트 파일 {iss_path.name} 을 읽지 못했어요.") from None
    problems = iss_problems(script)
    if problems:
        raise mm.BuildRefused(f"스크립트 점검에서 문제가 나왔어요(총 {len(problems)}건): " + " / ".join(problems[:bp.SHOWN_PROBLEMS]))
    overlap = pc.install_dir_problem(pc.default_install_dir(PLACEHOLDER_LOCAL), pc.default_data_dir(PLACEHOLDER_LOCAL))
    if overlap:
        raise mm.BuildRefused("기본 설치 폴더와 데이터 폴더가 겹쳐요 — " + overlap)
    say(f"[4/{STEPS}] Inno Setup 컴파일러 찾기와 판 확인")
    iscc = find_iscc(host, options.iscc)
    before = read_inno_version(host, iscc)
    if before["numbers"]:
        judge_inno_version(before)
    icon = options.icon or (str(HERE / ICON_NAME) if host.is_file(HERE / ICON_NAME) else None)
    if icon is not None and not host.is_file(icon):
        raise mm.BuildRefused("--icon 으로 준 아이콘 파일이 없어요.")
    iscc_sha = host.sha256(iscc)
    stage = found["out"].joinpath(*STAGE_PARTS)
    temp = release / (name + ".tmp")
    placed = False
    try:
        _remove(stage)
        stage.mkdir(parents=True)
        say(f"[5/{STEPS}] 컴파일(ISCC) — 보통 30초 안팎 · 컴파일 전에 읽은 판: " + (".".join(str(part) for part in before["numbers"]) if before["numbers"] else "아직 읽지 못함(컴파일 출력에서 읽어요)"))
        args = iscc_args(iscc, iss_path, version=version, source_dir=found["bundle"], out_dir=stage, out_base=name[:-len(".exe")], icon=icon)
        result = host.run_iscc(args, timeout=COMPILE_SECONDS, cwd=iss_path.parent)
        if result.error:
            raise mm.BuildRefused(f"ISCC 를 실행하지 못했어요({result.error}).")
        if result.timed_out:
            raise mm.BuildRefused(f"컴파일이 {COMPILE_SECONDS}초 안에 끝나지 않아 멈췄어요(시간 초과).")
        if result.rc != 0:
            raise mm.BuildRefused(f"컴파일이 실패했어요(종료 코드 {result.rc}) — 컴파일 출력의 끝: {_tail(result.out)}")
        setup = stage / name
        if not setup.is_file():
            raise mm.BuildRefused(f"컴파일은 끝났는데 설치 파일 {name} 이 만들어지지 않았어요.")
        say(f"[6/{STEPS}] 컴파일러가 밝힌 판 확인과 설치 파일 점검")
        read = read_inno_version(host, iscc, result.out)
        numbers = judge_inno_version(read)
        size = setup.stat().st_size
        if size <= 0:
            raise mm.BuildRefused("설치 파일이 비어 있어요.")
        if size > MAX_SETUP_BYTES:
            raise mm.BuildRefused(f"설치 파일이 너무 커요({size:,}바이트, 한도 {MAX_SETUP_BYTES:,}바이트) — 업데이트 매니페스트의 파일 크기 상한을 넘어요.")
        with setup.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise mm.BuildRefused("만들어진 설치 파일이 윈도 실행 파일 모양이 아니에요.")
        target = release / name
        shutil.copyfile(setup, temp)
        os.replace(temp, target)
        placed = True
        sha, total = pc.sha256_file(target), target.stat().st_size
        if sha != pc.sha256_file(setup) or total != size:
            raise mm.BuildRefused("release 폴더로 옮긴 설치 파일이 컴파일 결과와 달라요.")
        record = {"tool": pc.INSTALLER_TOOL, "tool_version": ".".join(str(part) for part in numbers), "iscc_sha256": iscc_sha, "built_on": built_on(host.environ)}
        artifacts = {"setup": {"name": name, "sha256": sha, "bytes": total}, "portable": dict(found["package"])}
        newer = mm.with_installer(found["info"], record, artifacts)
        mm.write_outer(release, newer, found["zip"])
        placed = False                                                                         # 정보 파일까지 썼다 — 여기부터는 지우지 않는다
    except BaseException:
        if placed and target.exists():
            target.unlink()                                                                    # 정보 파일을 못 쓴 채 설치 파일만 release 에 남기지 않는다
        raise
    finally:
        _remove(stage)
        if temp.exists():
            temp.unlink()
    say(f"[7/{STEPS}] 끝 — {name} {total:,}바이트 · SHA-256 {sha} · Inno Setup {record['tool_version']} (바깥 정보의 installer·artifacts 칸과 SHA256SUMS 도 갱신)")
    return {"setup": target, "name": name, "sha256": sha, "bytes": total, "release": release, "info": newer, "installer": record, "artifacts": artifacts}


def main(argv=None):
    parser = argparse.ArgumentParser(description="build_package.py 가 만든 묶음 폴더에서 설치 파일(Inno Setup)을 만든다 — 압축 파일은 그대로 두고 설치 파일만 더한다.")
    parser.add_argument("--out-dir", default=str(bp.DEFAULT_OUT), help="build_package.py 의 출력 폴더(기본: 저장소의 dist/package)")
    parser.add_argument("--iscc", default=None, help=f"Inno Setup 컴파일러(ISCC.exe)의 경로 — 없으면 환경 변수 {ISCC_ENV}·PATH·잘 알려진 설치 폴더에서 찾는다")
    parser.add_argument("--icon", default=None, help=f"설치 파일에 쓸 아이콘(.ico) — 없으면 packaging/{ICON_NAME} 이 있을 때만 쓰고, 그것도 없으면 기본 아이콘")
    args = parser.parse_args(argv)
    try:
        build(Options(out_dir=args.out_dir, iscc=args.iscc, icon=args.icon))
    except mm.BuildRefused as refused:
        print(f"설치 파일 만들기를 멈췄어요: {refused}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"설치 파일 만들기를 멈췄어요: 파일을 다루다 운영체제가 거절했어요({type(error).__name__}). 출력 폴더의 이름·권한·남은 디스크를 확인해 주세요.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
