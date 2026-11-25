# -*- coding: utf-8 -*-
"""measure.py - 설치 도구 시험(spike)의 측정 부품(결정 D-703). run_spike.py 의 measure 와 report 단계가 쓴다.

러너(일회용 윈도 가상 머신)에서만 도는 도구다 — 앱 본체(src/)와 상관없고 표준 라이브러리만 쓴다. 순수한 부분(기록 틀·PE 읽기·폴더 지문 비교·글 가리기·판정)은 어느 운영체제에서나 시험으로 지키고,
윈도에서만 되는 부분(창 찾기·방화벽·프로세스 목록)은 호출 쪽(run_spike.py)이 Host 를 거쳐 부르므로 시험이 가짜로 바꿔 끼운다.
보고서는 저장소를 읽을 수 있는 누구에게나 내려받아진다 — 그래서 모든 글은 Scrubber 로 가린다(경로·사용자 이름·컴퓨터 이름·저장소 이름·토큰 모양).
"""
import hashlib
import os
import re
import struct
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

STATUSES = ("pass", "fail", "info", "skip", "unavailable", "error")
ARMS = ("A", "B", "C")
ARM_NAMES = {"A": "Velopack+SDK", "B": "Velopack(SDK 없이)", "C": "Inno Setup"}
# 웹 접속이 가능한 윈도 부품 이름(PE 가져오기 표에서 이것이 보이면 '웹 접속 가능한 부품' 으로 기록한다 — 판정이 아니라 결정 입력)
NET_DLLS = ("winhttp.dll", "wininet.dll", "ws2_32.dll", "wsock32.dll", "dnsapi.dll", "iphlpapi.dll", "mswsock.dll", "webio.dll", "urlmon.dll", "httpapi.dll", "rasapi32.dll", "sensapi.dll", "netapi32.dll", "schannel.dll")
SECRET_SHAPES = (
    r"AIza[0-9A-Za-z_-]{35}", r"(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}", r"[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}", r"GOCSPX-[A-Za-z0-9_-]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"sk-[A-Za-z0-9]{32,}|gsk_[A-Za-z0-9]{40,}",
)
SCRUB_ENV_KEYS = ("USERNAME", "USER", "USERDOMAIN", "COMPUTERNAME", "RUNNER_NAME", "RUNNER_TEMP", "RUNNER_WORKSPACE", "RUNNER_TOOL_CACHE", "GITHUB_WORKSPACE", "GITHUB_REPOSITORY",
                  "GITHUB_REPOSITORY_OWNER", "GITHUB_ACTOR", "GITHUB_TRIGGERING_ACTOR", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "HOMEPATH")
PATH_SHAPE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'|*?]*")
MIN_SCRUB_WORD = 3


# ---- 기록 --------------------------------------------------------------------------------------------------------------------------------

def record(mid, arm, status, note="", **values):
    """측정 한 건 — id(M01…)·갈래(A·B·C 또는 공통 '-')·상태·값 사전·한 줄 메모."""
    if status not in STATUSES:
        raise ValueError("모르는 상태: %r" % (status,))
    if arm not in ARMS + ("-",):
        raise ValueError("모르는 갈래: %r" % (arm,))
    return {"id": mid, "arm": arm, "status": status, "values": values, "note": note}


class Scrubber:
    """보고서에 들어가는 모든 글에서 경로·사용자 이름·컴퓨터 이름·저장소 이름·토큰 모양을 가린다(환경 변수 값은 긴 것부터 바꾸고, 그다음 일반 경로 모양)."""

    def __init__(self, environ=None, extra=()):
        environ = os.environ if environ is None else environ
        words = {str(word) for word in extra if word}
        for key in SCRUB_ENV_KEYS:
            value = str(environ.get(key, "") or "")
            if len(value) >= MIN_SCRUB_WORD:
                words.add(value)
                words.add(value.replace("\\", "/"))
                if "/" in value or "\\" in value:
                    words.add(value.rstrip("\\/"))
        self.words = sorted((word for word in words if len(word) >= MIN_SCRUB_WORD), key=lambda item: (-len(item), item))
        self.secret = re.compile("|".join("(?:%s)" % shape for shape in SECRET_SHAPES))

    def __call__(self, text):
        if not isinstance(text, str):
            return text
        for word in self.words:
            text = re.sub(re.escape(word), "<가림>", text, flags=re.IGNORECASE)
        text = PATH_SHAPE.sub("<경로>", text)
        return self.secret.sub("<키 모양 가림>", text)

    def deep(self, value):
        """사전·목록·글을 통째로 가린다(숫자·참거짓은 그대로)."""
        if isinstance(value, str):
            return self(value)
        if isinstance(value, dict):
            return {self(key) if isinstance(key, str) else key: self.deep(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.deep(item) for item in value]
        return value


def runner_problem(environ):
    """GitHub 일회용 윈도 러너 안이 아니면 어긋난 조건의 변수 이름(값은 적지 않는다), 맞으면 ''. 시험은 이 변수 값을 가짜 세계의 환경에 넣어서만 이 장치를 지난다."""
    if environ.get("GITHUB_ACTIONS") != "true":
        return "GITHUB_ACTIONS"
    if environ.get("RUNNER_OS") != "Windows":
        return "RUNNER_OS"
    if not environ.get("RUNNER_TEMP"):
        return "RUNNER_TEMP"
    return ""


def secret_pattern(words):
    """가릴 낱말들을 한 번에 찾는 정규식(가릴 낱말이 없으면 None). 긴 낱말부터 고르고, 대소문자를 구분하지 않으며, 낱말의 글자 사이에 공백이나 줄바꿈이 끼어 있어도(되울림이 줄이 나뉘어 나올 때) 찾는다.
    네 글자보다 짧은 낱말은 글 속 우연한 겹침이 많아 무시한다."""
    ordered = sorted({word for word in words if isinstance(word, str) and len(word) >= 4}, key=lambda item: (-len(item), item))
    if not ordered:
        return None
    return re.compile("|".join(r"\s*".join(re.escape(char) for char in word) for word in ordered), re.IGNORECASE)


def hide_words(value, words):
    """비밀 낱말(예: 임시 사용자의 임의 비밀번호)이 든 글을 가린다 — 사전·목록·글을 통째로, 긴 낱말부터. 대소문자가 달라도, 낱말 한가운데에 공백이나 줄바꿈이 끼어도 가린다(되울림의 변형).
    다른 글자가 끼거나(예: 줄 이음표) 낱말의 일부만 되울리면 못 가린다 — 일회용 가상 머신의 임시 값이라 위험이 작다고 보고 문서(D-708)에 한계로 적었다."""
    pattern = secret_pattern(words)
    if pattern is None:
        return value

    def walk(item):
        if isinstance(item, str):
            return pattern.sub("<가림>", item)
        if isinstance(item, dict):
            return {(walk(key) if isinstance(key, str) else key): walk(inner) for key, inner in item.items()}
        if isinstance(item, (list, tuple)):
            return [walk(inner) for inner in item]
        return item

    return walk(value)


def tail(text, limit=400):
    """긴 출력의 뒤쪽 limit 글자만(앞은 '…')."""
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


# ---- PE 읽기(실행 파일 매니페스트·가져오기 표) ------------------------------------------------------------------------------------------------------

_MANIFEST_LEVEL = re.compile(rb'requestedExecutionLevel\s+level\s*=\s*"([A-Za-z]+)"')
MAX_IMPORTS = 400


def manifest_level(data):
    """실행 파일(바이트)의 매니페스트에 적힌 실행 수준(asInvoker·requireAdministrator·highestAvailable) — 없으면 None. 글자 사이에 NUL 이 낀 UTF-16 매니페스트도 읽는다."""
    for blob in (data, data.replace(b"\x00", b"")):
        match = _MANIFEST_LEVEL.search(blob)
        if match:
            return match.group(1).decode("ascii")
    return None


def parse_pe(data):
    """PE 머리의 필요한 부분만 읽는다 → {plus, directories[(rva, size)], sections[(vsize, vaddr, rawsize, rawptr)]} 또는 None(PE 가 아니거나 깨짐)."""
    try:
        if len(data) < 0x40 or data[:2] != b"MZ":
            return None
        (lfanew,) = struct.unpack_from("<I", data, 0x3C)
        if lfanew + 24 > len(data) or data[lfanew:lfanew + 4] != b"PE\x00\x00":
            return None
        _machine, count, _stamp, _symbols, _nsyms, optional_size, _flags = struct.unpack_from("<HHIIIHH", data, lfanew + 4)
        optional = lfanew + 24
        (magic,) = struct.unpack_from("<H", data, optional)
        if magic == 0x20B:
            directory_at, plus = optional + 112, True
        elif magic == 0x10B:
            directory_at, plus = optional + 96, False
        else:
            return None
        (numbers,) = struct.unpack_from("<I", data, directory_at - 4)
        directories = [struct.unpack_from("<II", data, directory_at + 8 * index) for index in range(min(numbers, 16))]
        sections = []
        for index in range(min(count, 96)):
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, optional + optional_size + 40 * index + 8)
            sections.append((vsize, vaddr, rawsize, rawptr))
        return {"plus": plus, "directories": directories, "sections": sections}
    except (struct.error, IndexError):
        return None


def rva_to_offset(sections, rva):
    for vsize, vaddr, rawsize, rawptr in sections:
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rawptr + (rva - vaddr)
    return None


def _c_string(data, offset, limit=260):
    if offset is None or not 0 <= offset < len(data):
        return ""
    end = data.find(b"\x00", offset, offset + limit)
    return data[offset:end if end >= 0 else offset + limit].decode("ascii", errors="replace")


def pe_imports(data):
    """가져오기 표(보통 가져오기와 늦은 가져오기)의 DLL 이름들(소문자, 겹침 없이 처음 나온 순서). PE 가 아니거나 표가 없으면 빈 목록."""
    pe = parse_pe(data)
    if not pe:
        return []
    names = []
    for index, size_of, name_at in ((1, 20, 12), (13, 32, 4)):
        if index >= len(pe["directories"]):
            continue
        rva, size = pe["directories"][index]
        offset = rva_to_offset(pe["sections"], rva) if rva and size else None
        if offset is None:
            continue
        for count in range(MAX_IMPORTS):
            at = offset + count * size_of
            if at + size_of > len(data) or not any(data[at:at + size_of]):
                break
            (name_rva,) = struct.unpack_from("<I", data, at + name_at)
            name = _c_string(data, rva_to_offset(pe["sections"], name_rva)).lower()
            if name and name not in names:
                names.append(name)
    return names


def net_imports(names):
    """가져오기 이름 목록 중 웹 접속이 가능한 윈도 부품(NET_DLLS)만."""
    return [name for name in names if name.lower() in NET_DLLS]


def wheel_inventory(path, *, limit_bytes=64 * 1024 * 1024):
    """휠 안의 파일(이름·크기)과 그 안 실행 부품(.pyd·.dll·.exe)의 가져오기 표 → {files, binaries: [{name, bytes, imports, net}], total_bytes}."""
    files, binaries, total = [], [], 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            files.append({"name": info.filename, "bytes": info.file_size})
            total += info.file_size
            if info.filename.lower().endswith((".pyd", ".dll", ".exe")) and info.file_size <= limit_bytes:
                imports = pe_imports(archive.read(info))
                binaries.append({"name": info.filename, "bytes": info.file_size, "imports": imports, "net": net_imports(imports)})
    return {"files": files, "binaries": binaries, "total_bytes": total}


_HANGUL_UTF8 = re.compile(rb"(?:[\xea-\xed][\x80-\xbf][\x80-\xbf]){3,}")
_HANGUL_UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00|[\x00-\xff][\xac-\xd7]){6,}")


def hangul_samples(data, limit=5):
    """실행 파일 안의 한글 글(UTF-8 연속 세 글자 이상, 또는 ASCII 가 섞인 UTF-16 글 여섯 글자 이상)의 표본 → {utf8, utf16, samples}. 무작위 바이트가 우연히 맞을 수 있어 '추정' 이다."""
    samples, utf8, utf16 = [], 0, 0
    for match in _HANGUL_UTF8.finditer(data):
        text = match.group(0).decode("utf-8", errors="ignore")
        if text:
            utf8 += 1
            samples.append(text[:40])
    for match in _HANGUL_UTF16.finditer(data):
        text = match.group(0).decode("utf-16le", errors="ignore")
        syllables = sum(1 for char in text if "가" <= char <= "힣")
        if syllables >= 2 and any(" " <= char <= "~" for char in text):
            utf16 += 1
            samples.append(text[:40])
    return {"utf8": utf8, "utf16": utf16, "samples": samples[:limit]}


# ---- 폴더 지문·크기·상태 --------------------------------------------------------------------------------------------------------------------

def sha256_file(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hashes(root, *, skip=()):
    """폴더 안 모든 파일의 {슬래시로 나눈 상대 경로: SHA-256}. skip 에 든 이름(파일 이름만 비교, 소문자)은 뺀다."""
    root = Path(root)
    found = {}
    if not root.is_dir():
        return found
    skipped = {name.lower() for name in skip}
    for current, _folders, names in os.walk(root):
        for name in names:
            if name.lower() in skipped:
                continue
            path = Path(current) / name
            found[path.relative_to(root).as_posix()] = sha256_file(path)
    return found


def tree_state(current, old, new):
    """설치된 폴더의 지문(current)이 옛 판(old)인지·새 판(new)인지·반쯤 섞였는지 — 'old'·'new'·'mixed'·'empty'·'other'. 두 판이 달라지는 파일(old 와 new 의 해시가 다른 경로)만 본다."""
    if not current:
        return "empty"
    differing = [path for path in sorted(set(old) | set(new)) if old.get(path) != new.get(path)]
    if not differing:
        return "same" if all(current.get(path) == old.get(path) for path in old) else "other"
    from_old = sum(1 for path in differing if current.get(path) == old.get(path))
    from_new = sum(1 for path in differing if current.get(path) == new.get(path))
    if from_old == len(differing):
        return "old"
    if from_new == len(differing):
        return "new"
    if from_old and from_new:
        return "mixed"
    return "other"


def dir_size(root):
    total = 0
    for current, _folders, names in os.walk(root):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError:
                continue
    return total


def file_count(root):
    return sum(len(names) for _current, _folders, names in os.walk(root))


def mb(value):
    """바이트를 메가바이트(소수 한 자리)로."""
    return round(value / (1024 * 1024), 1)


class Stopwatch:
    def __init__(self, clock=time.monotonic):
        self.clock, self.began = clock, clock()

    def seconds(self):
        return round(self.clock() - self.began, 1)


# ---- 방화벽·프로세스·창(윈도 전용 — 실제 실행은 Host 를 거쳐 호출 쪽이 한다) ----------------------------------------------------------------------------

def firewall_add_args(name, program):
    """프로그램 하나의 바깥(out) 접속을 막는 규칙을 더하는 명령(모든 프로필)."""
    return ["netsh", "advfirewall", "firewall", "add", "rule", "name=" + name, "dir=out", "action=block", "program=" + str(program), "enable=yes", "profile=any"]


def firewall_delete_args(name):
    return ["netsh", "advfirewall", "firewall", "delete", "rule", "name=" + name]


def rule_name(index):
    return "installer-spike-block-%03d" % index


def tasklist_names(text):
    """`tasklist /FO CSV /NH` 출력에서 실행 파일 이름(소문자) 목록."""
    names = []
    for line in (text or "").splitlines():
        match = re.match(r'^"([^"]+)"', line.strip())
        if match:
            names.append(match.group(1).lower())
    return names


def windows_of_pid(pid):
    """그 프로세스가 가진 보이는 최상위 창의 클래스 이름들(윈도 전용 — 다른 운영체제에서는 빈 목록). 메시지 상자는 보통 클래스 '#32770' 이다."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buffer, 256)
            found.append(buffer.value)
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return found


# ---- 도구 출력 읽기 ---------------------------------------------------------------------------------------------------------------------------

_VERSION_IN_TEXT = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def version_numbers(text):
    """글 안에서 처음 나오는 '숫자.숫자(.숫자)' → 정수 튜플(없으면 None)."""
    match = _VERSION_IN_TEXT.search(text or "")
    return tuple(int(part) for part in match.groups() if part is not None) if match else None


def inno_version_ok(numbers):
    """Inno Setup 은 6.7 줄이어야 한다(설계서 T11 — 러너 이미지가 바뀌어 다른 판이면 결과가 달라진다)."""
    return bool(numbers) and numbers[:2] == (6, 7)


def parse_selftest_counts(parsed):
    """`build_package.parse_selftest` 결과 → {통과, 실패, 건너뜀, 실패 이름}."""
    return {"passed": len(parsed.get("passed", [])), "failed": len(parsed.get("failed", [])), "skipped": len(parsed.get("skipped", [])), "failed_names": list(parsed.get("failed", []))}


def read_text_guess(path, limit=2 * 1024 * 1024):
    """로그 파일을 UTF-8(BOM 포함)·UTF-16·CP949 순으로 읽는다(못 읽으면 빈 글)."""
    try:
        data = Path(path).read_bytes()[:limit]
    except OSError:
        return ""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def packaging_module(name):
    """packaging/ 의 기존 도구(build_package·make_manifest)를 불러온다 — 이 파일이 어느 폴더에서 불려도 같은 파일을 쓴다."""
    import importlib
    folder = str(Path(__file__).resolve().parent.parent)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    return importlib.import_module(name)


# ---- 바깥 세계(프로세스·시계) — 시험이 Host 를 가짜로 바꿔 끼운다 --------------------------------------------------------------------------------------

DECODINGS = ("utf-8", "cp949")
VERSIONS = ("0.0.1", "0.0.2", "0.0.3")
TINY_EXE = {"A": "SpikeAppSdk.exe", "B": "SpikeApp.exe", "C": "SpikeApp.exe"}
REAL_EXE = "ChanceBlogDesktop.exe"
SENTINEL_TEXT = "CANARY_SPIKE_DATA — 설치·제거가 지우면 안 되는 가짜 사용자 데이터"
FAKE_CREDENTIAL = "CANARY_" + "spike_not_a_secret"
HOOKS = ("--veloapp-install", "--veloapp-updated", "--veloapp-obsolete", "--veloapp-uninstall")
UNINSTALL_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall"
SETUP_SECONDS_LIMIT = 120
UPDATE_SECONDS_LIMIT = 120
HOOK_SECONDS_LIMIT = 5.0
SETUP_MB_LIMIT = 80
PACK_SECONDS_LIMIT = 300
DEFENDER_BUDGET_SECONDS = 420
BUDGET_SECONDS = 1500
STD_USER = "spikeuser"
PASSWORD_PREFIX = "Sp1ke!"
RUNNER_REFUSAL = ("이 도구는 GitHub 의 일회용 윈도 러너 안에서만 돈다 — 방화벽 규칙·가짜 자격 증명·임시 사용자 만들기·프로그램 이름으로 끝내기를 하므로 개발 PC 에서는 돌리지 않는다"
                  "(환경 변수 GITHUB_ACTIONS 가 true, RUNNER_OS 가 Windows 이고 RUNNER_TEMP 가 있어야 한다).")


def decode_bytes(data):
    if not data:
        return ""
    if isinstance(data, str):
        return data
    for encoding in DECODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class HostResult:
    def __init__(self, rc, seconds, out="", err="", timed_out=False, error=""):
        self.rc, self.seconds, self.out, self.err, self.timed_out, self.error = rc, seconds, out, err, timed_out, error

    @property
    def ok(self):
        return self.rc == 0 and not self.timed_out and not self.error

    def text(self):
        return (self.out or "") + (self.err or "")


class Host:
    """바깥 세계와 닿는 모든 것 — 프로세스 실행·기다리기·시계·도구 찾기. 시험은 이 클래스를 가짜로 바꿔 끼워 설치 도구 없이 흐름을 돌린다."""

    def __init__(self, environ=None):
        self.environ = dict(os.environ if environ is None else environ)

    def now(self):
        return time.monotonic()

    def wall(self):
        return time.time()

    def sleep(self, seconds):
        time.sleep(seconds)

    def which(self, name):
        import shutil
        return shutil.which(name, path=self.environ.get("PATH"))

    def is_file(self, path):
        """이 경로에 파일이 있는가 — 도구를 정해진 자리에서 찾을 때 쓴다. 시험은 이 메서드도 바꿔 끼운다: 윈도 러너 이미지에는 Inno Setup 이 실제로 깔려 있어, 실제 디스크를 직접 보면 '없다'는 가짜 세계에도 그것이 보인다."""
        return Path(path).is_file()

    def _environment(self, env, drop):
        merged = dict(self.environ)
        for key in drop:
            merged.pop(key, None)
        merged.update(env or {})
        return merged

    def run(self, args, *, timeout=120, env=None, cwd=None, drop_env=()):
        """프로그램을 돌리고 끝을 기다린다. 출력은 관(pipe)이 아니라 임시 파일로 받는다 — 설치 도구가 자식 프로세스를 남기고 끝나도(관을 물려받은 자식이 살아 있으면 관 읽기가 끝나지 않는다) 여기서 매달리지 않는다."""
        import subprocess
        import tempfile
        began = time.monotonic()
        with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
            try:
                done = subprocess.run([str(item) for item in args], stdin=subprocess.DEVNULL, stdout=out_file, stderr=err_file, timeout=timeout, env=self._environment(env, drop_env),
                                      cwd=str(cwd) if cwd else None)
                code, timed_out = done.returncode, False
            except subprocess.TimeoutExpired:
                code, timed_out = None, True
            except OSError as error:
                return HostResult(-1, round(time.monotonic() - began, 1), error=type(error).__name__)
            out_file.seek(0)
            err_file.seek(0)
            return HostResult(code, round(time.monotonic() - began, 1), decode_bytes(out_file.read()), decode_bytes(err_file.read()), timed_out=timed_out)

    def defender_scan(self, paths, *, timeout=240):
        """읽기 전용 Defender 검사(기존 make_manifest.scan_with_defender — 치료·격리 없음). 경로 하나마다 시간을 timeout 초로 줄인다."""
        import subprocess

        def short_runner(command, **kwargs):
            kwargs["timeout"] = timeout
            return subprocess.run(command, **kwargs)

        return packaging_module("make_manifest").scan_with_defender(paths, runner=short_runner)

    def reachable(self, host="github.com", port=443, timeout=8):
        """공개 호스트에 한 번 접속해 본다(방화벽 규칙이 듣는지 보는 대조 — 막혀야 정상이다)."""
        import socket
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except OSError:
            return False

    def start(self, args, *, env=None, cwd=None):
        """프로세스를 띄우고 기다리지 않는다(켜 둔 앱 흉내) → 프로세스 객체 또는 None."""
        import subprocess
        try:
            return subprocess.Popen([str(item) for item in args], env=self._environment(env, ()), cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return None

    def kill(self, process):
        """자기가 띄운 프로세스와 그 자식을 끝낸다(프로세스 번호로만)."""
        if process is None:
            return
        try:
            self.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], timeout=30)
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except Exception:                                       # 이미 끝났거나 끝낼 수 없다 — 시험 러너는 곧 사라진다
            pass

    def watch(self, args, *, seconds, env=None, cwd=None, peek_after=1.5):
        """프로세스를 띄워 seconds 초까지 기다리며 창을 본다 → {rc, seconds, timed_out, windows}. 끝나지 않으면 죽인다."""
        process = self.start(args, env=env, cwd=cwd)
        if process is None:
            return {"rc": -1, "seconds": 0.0, "timed_out": False, "windows": [], "error": "OSError"}
        began, windows = time.monotonic(), []
        while True:
            rc = process.poll()
            elapsed = time.monotonic() - began
            if rc is not None or elapsed >= seconds:
                break
            if elapsed >= peek_after and not windows:
                windows = windows_of_pid(process.pid)
            time.sleep(0.25)
        timed_out = rc is None
        if timed_out:
            windows = windows_of_pid(process.pid) or windows
            self.kill(process)
        return {"rc": rc, "seconds": round(time.monotonic() - began, 1), "timed_out": timed_out, "windows": windows}


def read_json(path, default):
    try:
        import json
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    import json
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Context:
    """한 단계가 쓰는 작업 폴더·상태·측정 기록·바깥 세계(Host). 상태(state.json)는 단계 사이에 넘기고 측정 기록(results.json)은 measure 가 쓴다."""

    def __init__(self, work, *, host=None, budget_seconds=BUDGET_SECONDS):
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.host = host or Host()
        self.state_path, self.results_path = self.work / "state.json", self.work / "results.json"
        self.state = read_json(self.state_path, None) or {"schema": 1, "steps": {}, "tools": {}, "bundles": {}, "installers": {}, "help": {}}
        for key in ("steps", "tools", "bundles", "installers", "help"):
            self.state.setdefault(key, {})
        self.results = read_json(self.results_path, [])
        self.began = self.host.now()
        self.budget = budget_seconds
        self.blocked = {}
        self.logs = self.work / "logs"
        self.secret_words = []

    def save(self):
        write_json(self.state_path, self.state)
        write_json(self.results_path, self.results)

    def hide(self, word):
        """측정 기록에 글이 들어가는 순간 가릴 낱말을 더한다(Scrubber 의 extra 와 같은 뜻). 이 값은 상태 파일에도 쓰지 않으므로 따로 도는 report 단계의 Scrubber 는 모른다 — 그래서 기록을 쓸 때 가린다."""
        if isinstance(word, str) and len(word) >= 4 and word not in self.secret_words:
            self.secret_words.append(word)

    def mask(self, text):
        """글에서 가릴 낱말을 가려 돌려준다. 글을 자르기(tail) 전에 불러야 한다 — 자른 뒤에 가리면 낱말 한가운데가 잘려 낱말 전체가 안 맞아 조각이 그대로 남는다(독립 검증 재작업 권고 2)."""
        return hide_words(text, self.secret_words)

    def add(self, rec):
        rec = hide_words(rec, self.secret_words)
        self.results.append(rec)
        return rec

    def over_budget(self):
        return self.host.now() - self.began > self.budget

    def guard(self, mid, arm, function, *args):
        """측정 하나를 감싼다 — 어떤 오류든 그 항목만 '오류' 로 기록하고 나머지는 계속한다."""
        try:
            return function(*args)
        except Exception as error:                              # 측정 하나가 죽어도 보고서는 만들어져야 한다
            self.add(record(mid, arm, "error", note="%s: %s" % (type(error).__name__, tail(self.mask(str(error)), 200)), brief="오류 " + type(error).__name__))
            return None

    def note_step(self, name, status, seconds, **extra):
        self.state["steps"][name] = dict({"status": status, "seconds": seconds}, **extra)
        self.save()

    def env(self, name, default=""):
        return self.host.environ.get(name, default)


# ---- 갈래별 명령 만들기(순수) -----------------------------------------------------------------------------------------------------------------

def velopack_arm(arm):
    return arm in ("A", "B")


def install_args(arm, setup, root, log, korean=False):
    """조용한 설치 명령 — Velopack Setup 은 --silent·--installto·--log, Inno 는 /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR /LOG(필요하면 /LANG=korean)."""
    if velopack_arm(arm):
        return [str(setup), "--silent", "--installto", str(root), "--log", str(log)]
    args = [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=" + str(root), "/LOG=" + str(log)]
    if korean:
        args.append("/LANG=korean")
    return args


def uninstall_variants(arm, root):
    """조용한 제거 명령 후보(앞의 것이 안 되면 다음 것) — Velopack 은 설치 뿌리의 Update.exe, Inno 는 unins000.exe."""
    root = Path(root)
    if velopack_arm(arm):
        update = str(root / "Update.exe")
        return [[update, "uninstall", "--silent"], [update, "--silent", "uninstall"]]
    return [[str(root / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]]


def apply_args(root, package):
    """설치 뿌리의 Update.exe 로 패키지 파일을 적용하는 명령(앱을 다시 띄우지 않는다)."""
    return [str(Path(root) / "Update.exe"), "apply", "--package", str(package), "--norestart"]


def app_dir(arm, root):
    return Path(root) / "current" if velopack_arm(arm) else Path(root)


def read_version_file(directory):
    try:
        return (Path(directory) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def program_paths(arm, root, exe_name, setups=()):
    """방화벽으로 막을 프로그램들 — 설치 파일들과 설치된 쪽 실행 파일들."""
    root = Path(root)
    paths = [str(item) for item in setups]
    if velopack_arm(arm):
        paths += [str(root / "Update.exe"), str(root / exe_name), str(root / "current" / exe_name)]
    else:
        paths += [str(root / exe_name), str(root / "unins000.exe")]
    return paths


def shortcut_dirs(environ):
    folders = []
    appdata, profile = environ.get("APPDATA", ""), environ.get("USERPROFILE", "")
    if appdata:
        folders.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if profile:
        folders.append(Path(profile) / "Desktop")
    return folders


def shortcut_snapshot(ctx):
    names = set()
    for folder in shortcut_dirs(ctx.host.environ):
        if folder.is_dir():
            names |= {path.name for path in folder.rglob("*.lnk")}
    return names


def uninstall_keys(ctx):
    result = ctx.host.run(["reg", "query", UNINSTALL_KEY], timeout=30)
    return {line.strip().rsplit("\\", 1)[-1] for line in result.out.splitlines() if line.strip().upper().startswith("HKEY_CURRENT_USER")}


def wait_until(ctx, predicate, timeout, interval=1.0):
    """predicate 가 참이 될 때까지 기다린다(시험의 가짜 시계가 시간을 흘려 준다) → 참이 됐는지."""
    began = ctx.host.now()
    while True:
        if predicate():
            return True
        if ctx.host.now() - began >= timeout:
            return False
        ctx.host.sleep(interval)


def process_names(ctx):
    return set(tasklist_names(ctx.host.run(["tasklist", "/FO", "CSV", "/NH"], timeout=60).out))


def kill_images(ctx, names):
    """시험이 만든 작은 앱·실제 앱 실행 파일 이름으로 남은 프로세스를 정리한다(러너는 일회용 가상 머신이다). 러너가 아니면 하지 않는다 — 개발 PC 의 실제 앱을 이름으로 끝낼 수 있다."""
    if runner_problem(ctx.host.environ):
        return
    for name in names:
        ctx.host.run(["taskkill", "/F", "/T", "/IM", name], timeout=30)


# ---- 방화벽 --------------------------------------------------------------------------------------------------------------------------------

def block(ctx, program):
    """프로그램 하나의 바깥 접속을 막는다(이미 막은 경로는 다시 만들지 않는다) → 규칙이 들어갔는지."""
    key = str(program).lower()
    if key in ctx.blocked:
        return True
    name = rule_name(len(ctx.blocked) + 1)
    result = ctx.host.run(firewall_add_args(name, program), timeout=30)
    if result.ok:
        ctx.blocked[key] = name
    return result.ok


def unblock_all(ctx):
    for name in list(ctx.blocked.values()):
        ctx.host.run(firewall_delete_args(name), timeout=30)
    ctx.blocked.clear()


def firewall_control(ctx):
    """규칙이 정말 듣는지 — 이 파이썬의 바깥 접속을 막은 채 공개 호스트에 한 번 접속해 본다. 막혔다면(접속 실패) True. 규칙은 곧바로 지운다."""
    program = ctx.env("SPIKE_PYTHON") or sys.executable
    name = rule_name(900)
    added = ctx.host.run(firewall_add_args(name, program), timeout=30)
    if not added.ok:
        return {"effective": None, "reason": "규칙을 넣지 못했다(rc %s)" % added.rc}
    try:
        ctx.host.sleep(2)
        reachable = ctx.host.reachable()
    finally:
        ctx.host.run(firewall_delete_args(name), timeout=30)
    return {"effective": not reachable, "reason": "규칙을 넣은 파이썬의 접속 시도가 " + ("성공했다(규칙이 안 듣는다)" if reachable else "막혔다")}


# ---- 가짜 사용자 데이터·자격 증명 --------------------------------------------------------------------------------------------------------------

def prepare_data(ctx, arm):
    folder = ctx.work / "data" / arm
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sentinel.txt").write_text(SENTINEL_TEXT, encoding="utf-8")
    target = "ChanceBlogDesktop:spike-" + arm
    created = ctx.host.run(["cmdkey", "/generic:" + target, "/user:spike", "/pass:" + FAKE_CREDENTIAL], timeout=30).ok
    return {"dir": folder, "target": target, "credential": created}


def data_survived(ctx, info):
    """센티넬 파일과 가짜 자격 증명이 남아 있는가 → (파일, 자격 증명 또는 None=시험 못 함)."""
    try:
        file_ok = (info["dir"] / "sentinel.txt").read_text(encoding="utf-8") == SENTINEL_TEXT
    except OSError:
        file_ok = False
    if not info["credential"]:
        return file_ok, None
    listed = ctx.host.run(["cmdkey", "/list:" + info["target"]], timeout=30)
    return file_ok, bool(listed.ok and info["target"].lower() in listed.text().lower())


def cleanup_data(ctx, info):
    if info["credential"]:
        ctx.host.run(["cmdkey", "/delete:" + info["target"]], timeout=30)


# ---- 설치·제거·적용 한 번씩 ---------------------------------------------------------------------------------------------------------------------

def installers_of(ctx, arm, kind="tiny"):
    return ctx.state.get("installers", {}).get(arm, {}).get(kind, {})


def bundle_tree(ctx, arm, version):
    """설치할 작은 앱 묶음(갈래에 맞는 쪽)의 한 판 폴더 지문."""
    kind = "sdk" if arm == "A" else "plain"
    folder = ctx.state.get("bundles", {}).get(kind, {}).get(version)
    return tree_hashes(folder) if folder else {}


def do_install(ctx, arm, setup, root, tag, *, korean=False, wait_for=None):
    """조용히 설치하고 설치 폴더가 갖춰질 때까지 기다린다 → (결과, 갖춰졌나, 로그 경로)."""
    ctx.logs.mkdir(parents=True, exist_ok=True)
    log = ctx.logs / ("%s-%s.log" % (arm, tag))
    result = ctx.host.run(install_args(arm, setup, root, log, korean), timeout=300)
    exe = wait_for or TINY_EXE[arm]
    ready = wait_until(ctx, lambda: bool(read_version_file(app_dir(arm, root)) or (app_dir(arm, root) / exe).is_file()), 60, 1.0)
    return result, ready, log


def do_uninstall(ctx, arm, root):
    """조용히 제거하고 설치 폴더가 사라질 때까지 기다린다 → (결과, 폴더 사라짐, 쓴 명령 번호)."""
    result, used = None, 0
    for used, args in enumerate(uninstall_variants(arm, root)):
        result = ctx.host.run(args, timeout=180)
        if result.ok:
            break
    gone = wait_until(ctx, lambda: not Path(root).exists() or not any(Path(root).iterdir()), 45, 1.0)
    return result, gone, used


def update_to(ctx, arm, root, version, inst, *, running=None, log_tag="update"):
    """설치된 것을 version 으로 바꾼다(A: 앱이 SDK 로 확인·내려받기·적용, B: Update.exe apply, C: 새 Setup 무음) → {rc, seconds, version_after, timed_out, via}."""
    entry = inst[version]
    began = ctx.host.now()
    env = {"SPIKE_LOG": str(ctx.logs / ("%s-%s.spikelog" % (arm, log_tag)))}
    if arm == "A":
        args, via = [str(app_dir(arm, root) / TINY_EXE["A"]), "--update-from", str(entry["feed"])], "sdk"
        result = ctx.host.run(args, timeout=180, env=env)
    elif arm == "B":
        result, via = ctx.host.run(apply_args(root, entry["full"]), timeout=180, env=env), "update-apply"
    else:
        result, via = ctx.host.run(install_args("C", entry["setup"], root, ctx.logs / ("C-%s.log" % log_tag)), timeout=300, env=env), "setup"
    wait_until(ctx, lambda: read_version_file(app_dir(arm, root)) == version, 60 if arm != "C" else 5, 1.0)
    return {"rc": result.rc, "seconds": round(ctx.host.now() - began, 1), "version_after": read_version_file(app_dir(arm, root)), "timed_out": result.timed_out, "via": via, "out": result.text()}


def state_of(ctx, arm, root, old_version, new_version):
    """설치된 폴더가 옛 판·새 판·반쯤 섞인 판 중 무엇인가."""
    skip = ("unins000.exe", "unins000.dat", "unins000.msg") if arm == "C" else ()
    return tree_state(tree_hashes(app_dir(arm, root), skip=skip), bundle_tree(ctx, arm, old_version), bundle_tree(ctx, arm, new_version))


def fresh_v1(ctx, arm, inst, root, tag):
    """설치 폴더를 비우고(제거 → 남은 것 지움) 0.0.1 을 새로 설치한다 → 갖춰졌나."""
    if Path(root).exists():
        do_uninstall(ctx, arm, root)
        import shutil
        shutil.rmtree(root, ignore_errors=True)
    _result, ready, _log = do_install(ctx, arm, inst["0.0.1"]["setup"], root, tag, korean=(arm == "C"))
    return ready


# ---- 측정 하나씩 -----------------------------------------------------------------------------------------------------------------------------

def m01_tools(ctx):
    tools = ctx.state.get("tools", {})
    for arm, key in (("A", "vpk"), ("B", "vpk")):
        info = tools.get(key, {})
        if info.get("status") == "ok":
            ctx.add(record("M01", arm, "pass", note=tail(info.get("version_text", ""), 120), brief="vpk " + info.get("version", "?"), nupkg=info.get("nupkg_ok"), wheel=tools.get("sdk", {}).get("wheel_ok"), version=info.get("version")))
        else:
            ctx.add(record("M01", arm, "fail", note=tail(info.get("reason", "도구 준비 안 됨"), 200), brief="vpk 없음"))
    iscc = tools.get("iscc", {})
    if iscc.get("status") == "ok":
        ctx.add(record("M01", "C", "pass" if iscc.get("version_ok") else "fail", note="ISCC 파일 SHA-256 앞 12자리 " + str(iscc.get("sha256", ""))[:12] + ", 서명자 " + tail(str(iscc.get("signer", "")), 60),
                       brief="Inno " + str(iscc.get("version", "?")), version=iscc.get("version"), signer=iscc.get("signer", ""), sha256=iscc.get("sha256", "")))
    else:
        ctx.add(record("M01", "C", "unavailable", note=tail(iscc.get("reason", "ISCC 를 찾지 못했다"), 200), brief="Inno 없음"))


def m02_m03_from_state(ctx):
    bundles = ctx.state.get("bundles", {})
    real = bundles.get("real", {})
    ctx.add(record("M02", "-", "pass" if real.get("dir") else "fail", note=tail(real.get("reason", ""), 200), brief="실제 묶음 %s MB %s초" % (mb(real.get("bytes", 0)), real.get("seconds", "?")) if real.get("dir") else "실제 묶음 실패",
                   bundle_bytes=real.get("bytes"), bundle_files=real.get("files"), seconds=real.get("seconds"), zip_bytes=real.get("zip_bytes"),
                   plain_ok=bool(bundles.get("plain", {}).get("0.0.1")), sdk_ok=bool(bundles.get("sdk", {}).get("0.0.1"))))
    for arm in ARMS:
        entry = ctx.state.get("installers", {}).get(arm, {}).get("real") or {}
        tiny = ctx.state.get("installers", {}).get(arm, {}).get("tiny", {}).get("0.0.1", {})
        if arm == "A":
            ctx.add(record("M03", arm, "info", note="갈래 A 는 실제 묶음에 SDK(휠 1.4MB 안팎)를 더한 것으로 본다 — 실제 묶음은 B 의 값을 쓴다(추정)", brief="작은 앱 %s MB %s초" % (mb(tiny.get("bytes", 0)), tiny.get("seconds", "?")) if tiny else "없음",
                           target="tiny", setup_bytes=tiny.get("bytes"), seconds=tiny.get("seconds")))
            continue
        if not entry:
            ctx.add(record("M03", arm, "unavailable", note="실제 묶음의 설치 파일이 없다(앞 단계 실패) — 관문 G7 은 미정으로 둔다", brief="없음", target="real"))
            continue
        ok = mb(entry.get("bytes", 0)) <= SETUP_MB_LIMIT and entry.get("seconds", 9999) <= PACK_SECONDS_LIMIT
        ctx.add(record("M03", arm, "pass" if ok else "fail", brief="%s MB %s초" % (mb(entry.get("bytes", 0)), entry.get("seconds", "?")), target="real", setup_bytes=entry.get("bytes"), seconds=entry.get("seconds"),
                       package_bytes=entry.get("package_bytes"), setup_name=entry.get("name")))


def m04_admin(ctx):
    """설치 파일의 매니페스트 실행 수준 — Velopack Setup(A·B 작은 앱, 실제 묶음)과 Inno Setup."""
    for arm in ARMS:
        found = {}
        for label, setup in (("tiny", (installers_of(ctx, arm).get("0.0.1") or {}).get("setup")), ("real", (ctx.state.get("installers", {}).get(arm, {}).get("real") or {}).get("setup"))):
            if setup and Path(setup).is_file():
                found[label] = manifest_level(Path(setup).read_bytes())
        if not found:
            ctx.add(record("M04", arm, "unavailable", note="설치 파일이 없다", brief="없음"))
            continue
        levels = sorted({str(level) for level in found.values()})
        if any(level is None for level in found.values()):
            ctx.add(record("M04", arm, "unavailable", brief="매니페스트를 못 읽음", levels=found, note="설치 파일에서 실행 수준(requestedExecutionLevel)을 찾지 못했다 — 도구가 자원을 압축했을 수 있다"))
            continue
        ok = all(level == "asInvoker" for level in found.values())
        ctx.add(record("M04", arm, "pass" if ok else "fail", brief="수준 " + "·".join(levels), levels=found, note="Inno 는 PrivilegesRequired=lowest 로 만들었다" if arm == "C" else ""))


def hook_check(ctx, exe, cwd, label, *, seconds=20):
    rows = []
    for hook in HOOKS:
        got = ctx.host.watch([exe, hook, "0.0.1"], seconds=seconds, cwd=cwd, env={"SPIKE_LOG": ""})
        rows.append({"hook": hook, "rc": got["rc"], "seconds": got["seconds"], "timed_out": got["timed_out"], "windows": len(got["windows"]), "classes": sorted(set(got["windows"]))[:3]})
    return rows


def m07_hooks(ctx, arm, root):
    exe = app_dir(arm, root) / TINY_EXE[arm]
    rows = hook_check(ctx, exe, app_dir(arm, root), "tiny")
    ok = all(row["rc"] == 0 and row["seconds"] <= HOOK_SECONDS_LIMIT and not row["windows"] and not row["timed_out"] for row in rows)
    ctx.add(record("M07", arm, "pass" if ok else "fail", brief="훅 %d/4 종료 0 최대 %s초 창 %d" % (sum(1 for row in rows if row["rc"] == 0), max(row["seconds"] for row in rows), sum(row["windows"] for row in rows)), target="tiny", rows=rows))


def m07_real_bundle(ctx):
    """지금의 실제 묶음에 같은 훅 인자(F1 재현) — 판정이 아니라 증상 기록."""
    real = ctx.state.get("bundles", {}).get("real", {})
    exe = Path(real.get("dir", "")) / REAL_EXE
    if not real.get("dir") or not exe.is_file():
        ctx.add(record("M07", "-", "unavailable", note="실제 묶음이 없다", brief="없음", target="real"))
        return
    rows = hook_check(ctx, exe, exe.parent, "real", seconds=12)
    ctx.add(record("M07", "-", "info", brief="실제 묶음 훅: 종료 코드 %s·최대 %s초·창 %d·멈춤 %d" % ("/".join(str(row["rc"]) for row in rows), max(row["seconds"] for row in rows), sum(row["windows"] for row in rows), sum(1 for row in rows if row["timed_out"])),
                   target="real", rows=rows, note="설치 훅 인자를 지금의 gui_entry 에 주면 거절 문장이 메시지 상자로 뜨는지(F1) 본다"))


def flow_tiny(ctx, arm):
    """작은 앱으로 한 갈래의 설치·훅·업데이트·실행 중 업데이트·되돌리기·깨진 새 판·제거(M05–M12, M21)."""
    inst = installers_of(ctx, arm)
    if not inst or any(version not in inst for version in VERSIONS):
        ctx.add(record("M05", arm, "unavailable", note="작은 앱 설치 파일 셋이 없다(앞 단계 실패)", brief="없음"))
        return
    exe_name = TINY_EXE[arm]
    root = ctx.work / "run" / arm / "root"
    data = prepare_data(ctx, arm)
    before_links, before_keys = shortcut_snapshot(ctx), uninstall_keys(ctx)
    try:
        # M05 무음 설치
        result, ready, _log = do_install(ctx, arm, inst["0.0.1"]["setup"], root, "install-1", korean=(arm == "C"))
        running = [name for name in process_names(ctx) if name in {exe_name.lower()}]
        ok = result.ok and ready and result.seconds <= SETUP_SECONDS_LIMIT and not running
        ctx.add(record("M05", arm, "pass" if ok else "fail", brief="종료 %s %s초 %s" % (result.rc, result.seconds, "앱 저절로 뜸" if running else "앱 안 뜸"), target="tiny", rc=result.rc, seconds=result.seconds, ready=ready, autostart=bool(running),
                       note=tail(result.text(), 200) if not ok else ""))
        # M06 설치 결과
        layout = describe_layout(arm, root, exe_name)
        links = sorted(shortcut_snapshot(ctx) - before_links)
        keys = sorted(uninstall_keys(ctx) - before_keys)
        ctx.add(record("M06", arm, "pass" if layout["version"] == "0.0.1" and layout["app_dir"] else "fail", brief="폴더 %s 바로가기 %d 제거 항목 %d" % ("ok" if layout["app_dir"] else "없음", len(links), len(keys)), target="tiny",
                       layout=layout, shortcuts=links, uninstall_keys=keys))
        # M07 훅(A·B)
        if velopack_arm(arm):
            m07_hooks(ctx, arm, root)
        if arm == "B":                                          # 다음 고침의 근거 — 설치 뿌리의 Update.exe 도움말(읽기 전용 명령)
            for key, extra in (("update_exe_help", ["--help"]), ("update_apply_help", ["apply", "--help"])):
                ctx.state["help"][key] = tail(ctx.host.run([str(Path(root) / "Update.exe"), *extra], timeout=30).text(), 3000)
        # M08 업데이트 0.0.1 -> 0.0.2
        update = update_to(ctx, arm, root, "0.0.2", inst, log_tag="update-2")
        state = state_of(ctx, arm, root, "0.0.1", "0.0.2")
        file_ok, cred_ok = data_survived(ctx, data)
        ok = update["version_after"] == "0.0.2" and state == "new" and update["seconds"] <= UPDATE_SECONDS_LIMIT and file_ok and cred_ok is not False
        ctx.add(record("M08", arm, "pass" if ok else "fail", brief="%s -> %s %s초 상태 %s" % ("0.0.1", update["version_after"] or "?", update["seconds"], state), target="tiny", rc=update["rc"], seconds=update["seconds"], via=update["via"], state=state,
                       data_kept=file_ok, credential_kept=cred_ok, note=tail(update["out"], 200) if not ok else ""))
        # M10 되돌리기(낮은 판 다시 적용)
        rollback = rollback_to_v1(ctx, arm, root, inst)
        ctx.add(record("M10", arm, "info", brief="낮은 판 적용 -> %s %s" % (rollback["version_after"] or "?", "됨" if rollback["version_after"] == "0.0.1" else "안 됨"), target="tiny", **rollback["values"]))
        # M09 실행 중 업데이트
        m09_running_update(ctx, arm, root, inst, data)
        # M11 깨진 새 판
        m11_broken(ctx, arm, root, inst)
        # M12 제거
        m12_uninstall(ctx, arm, root, data, before_links, before_keys, "tiny")
    finally:
        kill_images(ctx, {exe_name})
        cleanup_data(ctx, data)


def describe_layout(arm, root, exe_name):
    root = Path(root)
    folder = app_dir(arm, root)
    info = {"root_exists": root.is_dir(), "app_dir": folder.is_dir(), "files": file_count(folder) if folder.is_dir() else 0, "bytes": dir_size(root) if root.is_dir() else 0, "version": read_version_file(folder)}
    if velopack_arm(arm):
        info.update(update_exe=(root / "Update.exe").is_file(), stub_exe=(root / exe_name).is_file(), packages=(root / "packages").is_dir())
    else:
        info.update(uninstaller=any(root.glob("unins*.exe")) if root.is_dir() else False)
    return info


def rollback_to_v1(ctx, arm, root, inst):
    """낮은 판(0.0.1)을 다시 적용한다 — Velopack 은 Update.exe apply 로, Inno 는 옛 Setup 재실행으로."""
    began = ctx.host.now()
    if velopack_arm(arm):
        result = ctx.host.run(apply_args(root, inst["0.0.1"]["full"]), timeout=180)
    else:
        result = ctx.host.run(install_args("C", inst["0.0.1"]["setup"], root, ctx.logs / "C-rollback.log"), timeout=300)
    wait_until(ctx, lambda: read_version_file(app_dir(arm, root)) == "0.0.1", 20, 1.0)
    after = read_version_file(app_dir(arm, root))
    return {"version_after": after, "values": {"rc": result.rc, "seconds": round(ctx.host.now() - began, 1), "state": state_of(ctx, arm, root, "0.0.1", "0.0.2"), "note_out": tail(result.text(), 160)}}


def m09_running_update(ctx, arm, root, inst, data):
    """작은 앱을 켜 둔 채 0.0.1 -> 0.0.2 — 자동으로 닫고 새 판이 되거나 반쯤 바뀐 상태 없이 깨끗이 실패해야 한다."""
    if not fresh_v1(ctx, arm, inst, root, "install-hold"):
        ctx.add(record("M09", arm, "error", note="0.0.1 을 다시 설치하지 못했다", brief="준비 실패"))
        return
    process = ctx.host.start([str(app_dir(arm, root) / TINY_EXE[arm]), "--hold", "120"], cwd=app_dir(arm, root), env={"SPIKE_LOG": str(ctx.logs / ("%s-hold.spikelog" % arm))})
    ctx.host.sleep(2)
    alive_before = process is not None and process.poll() is None
    try:
        update = update_to(ctx, arm, root, "0.0.2", inst, running=process, log_tag="update-running")
        state = state_of(ctx, arm, root, "0.0.1", "0.0.2")
        alive_after = process is not None and process.poll() is None
    finally:
        ctx.host.kill(process)
    clean = state in ("old", "new") and update["version_after"] in ("0.0.1", "0.0.2")
    ctx.add(record("M09", arm, "pass" if clean and alive_before else "fail", brief="켜 둔 채 -> %s 상태 %s 앱 %s" % (update["version_after"] or "?", state, "계속 켜짐" if alive_after else "닫힘"), target="tiny", state=state, rc=update["rc"],
                   seconds=update["seconds"], app_alive_before=alive_before, app_alive_after=alive_after, via=update["via"], note=tail(update["out"], 160) if not clean else ""))


def m11_broken(ctx, arm, root, inst):
    """시작하자마자 종료 코드 3 으로 끝나는 0.0.3 을 적용한다 — 도구가 스스로 이전 판으로 되돌리는지 기록(기대: 안 함 — 앱 쪽 복구 코드가 필요)."""
    if not fresh_v1(ctx, arm, inst, root, "install-broken"):
        ctx.add(record("M11", arm, "error", note="0.0.1 을 다시 설치하지 못했다", brief="준비 실패"))
        return
    update = update_to(ctx, arm, root, "0.0.3", inst, log_tag="update-3")
    ran = ctx.host.run([str(app_dir(arm, root) / TINY_EXE[arm])], timeout=30, cwd=app_dir(arm, root), env={"SPIKE_LOG": str(ctx.logs / ("%s-broken.spikelog" % arm))})
    after = read_version_file(app_dir(arm, root))
    applied = update["version_after"] == "0.0.3"
    verdict = "적용 안 됨" if not applied and after == "0.0.1" else ("스스로 되돌림" if applied and after == "0.0.1" else "되돌리지 않음")
    ctx.add(record("M11", arm, "info", brief="0.0.3 적용 -> %s, 새 판 종료 코드 %s, %s" % (after or "?", ran.rc, verdict), target="tiny", applied=applied, applied_rc=update["rc"], version_after=after, new_version_exit=ran.rc,
                   auto_rollback=bool(applied and after == "0.0.1"), via=update["via"]))


def m12_uninstall(ctx, arm, root, data, before_links, before_keys, target):
    """제거 — 종료 코드 0, 설치 폴더·바로가기·제거 항목 0, 센티넬 데이터와 가짜 자격 증명 유지."""
    result, gone, used = do_uninstall(ctx, arm, root)
    links_left = sorted(shortcut_snapshot(ctx) - before_links)
    keys_left = sorted(uninstall_keys(ctx) - before_keys)
    file_ok, cred_ok = data_survived(ctx, data)
    folder_left = Path(root).exists() and any(Path(root).iterdir())
    ok = bool(result and result.ok) and gone and not links_left and not keys_left and file_ok and cred_ok is not False
    ctx.add(record("M12", arm, "pass" if ok else "fail", brief="종료 %s 폴더 %s 바로가기 %d 항목 %d 데이터 %s 자격 %s" % (result.rc if result else "?", "남음" if folder_left else "없음", len(links_left), len(keys_left), "유지" if file_ok else "삭제됨",
                   {True: "유지", False: "삭제됨", None: "시험 못 함"}[cred_ok]), target=target, rc=result.rc if result else None, folder_left=folder_left, shortcuts_left=links_left, keys_left=keys_left, data_kept=file_ok, credential_kept=cred_ok,
                   variant=used, note=tail(result.text(), 160) if (result and not result.ok) else ""))


def flow_blocked(ctx, arm, control):
    """M14 — 그 프로그램들의 바깥 접속을 막은 채 설치와 업데이트를 한 번 더 한다."""
    inst = installers_of(ctx, arm)
    if not inst or any(version not in inst for version in VERSIONS):
        ctx.add(record("M14", arm, "unavailable", note="작은 앱 설치 파일 셋이 없다", brief="없음"))
        return
    if control.get("effective") is not True:
        note = "방화벽 규칙이 듣는지 확인하지 못했다(%s) — 결과를 믿을 수 없다" % control.get("reason", "")
    else:
        note = ""
    exe_name = TINY_EXE[arm]
    root = ctx.work / "run" / arm / "blocked-root"
    ruled = all(block(ctx, setup) for setup in ((inst["0.0.1"]["setup"], inst["0.0.2"]["setup"]) if arm == "C" else (inst["0.0.1"]["setup"],)))
    install_result, ready, _log = do_install(ctx, arm, inst["0.0.1"]["setup"], root, "blocked-install", korean=(arm == "C"))
    for program in program_paths(arm, root, exe_name):
        block(ctx, program)
    update = update_to(ctx, arm, root, "0.0.2", inst, log_tag="blocked-update")
    done, _gone, _used = do_uninstall(ctx, arm, root)
    ok = ruled and install_result.ok and ready and update["version_after"] == "0.0.2" and bool(done and done.ok)
    status = "pass" if ok else "fail"
    if ok and control.get("effective") is not True:
        status = "info"
    ctx.add(record("M14", arm, status, brief="막은 채 설치 %s 업데이트 %s 제거 %s%s" % (install_result.rc, update["version_after"] or "?", done.rc if done else "?", "" if control.get("effective") is True else " (규칙 효과 미확인)"), rules=len(ctx.blocked),
                   control=control, install_rc=install_result.rc, update_version=update["version_after"], uninstall_rc=done.rc if done else None, note=note))
    kill_images(ctx, {exe_name})


def real_selftest(ctx, exe):
    """실제 묶음의 --selftest — 빌드와 같은 방식(입출력 환경 변수를 빼고 UTF-8 로 읽는다) → (종료 코드, 판정 사전)."""
    bp = packaging_module("build_package")
    result = ctx.host.run([str(exe), "--selftest"], timeout=300, cwd=Path(exe).parent, drop_env=("PYTHONUTF8", "PYTHONIOENCODING", "QT_QPA_PLATFORM", "PYTHONPATH"))
    parsed = bp.parse_selftest(result.text())
    ok, gate_present, _override, bad = bp.judge_selftest(parsed, allow_missing_gate=False)
    counts = parse_selftest_counts(parsed)
    counts.update(ok=bool(ok and result.rc == 0), rc=result.rc, bad=bad, seconds=result.seconds)
    return counts


def flow_real(ctx, arm, defender_state):
    """실제 묶음으로 한 갈래(B·C)의 설치·selftest·Defender·긴 한글 경로·제거(M05·M06·M12·M16·M19 의 real 쪽)."""
    entry = (ctx.state.get("installers", {}).get(arm, {}).get("real")) or {}
    real = ctx.state.get("bundles", {}).get("real", {})
    if not entry.get("setup") or not real.get("dir"):
        ctx.add(record("M05", arm, "unavailable", note="실제 묶음 설치 파일이 없다(앞 단계 실패)", brief="없음", target="real"))
        return
    root = ctx.work / "run" / arm / "real-root"
    data = prepare_data(ctx, arm + "real")
    before_links, before_keys = shortcut_snapshot(ctx), uninstall_keys(ctx)
    try:
        result, ready, _log = do_install(ctx, arm, entry["setup"], root, "real-install", korean=(arm == "C"), wait_for=REAL_EXE)
        running = [name for name in process_names(ctx) if name == REAL_EXE.lower()]
        ok = result.ok and ready and result.seconds <= SETUP_SECONDS_LIMIT and not running
        ctx.add(record("M05", arm, "pass" if ok else "fail", brief="실제 묶음 종료 %s %s초 %s" % (result.rc, result.seconds, "앱 저절로 뜸" if running else "앱 안 뜸"), target="real", rc=result.rc, seconds=result.seconds, ready=ready, autostart=bool(running),
                       installed_mb=mb(dir_size(root)) if root.exists() else 0, note=tail(result.text(), 200) if not ok else ""))
        exe = app_dir(arm, root) / REAL_EXE
        if exe.is_file():
            counts = real_selftest(ctx, exe)
            ctx.add(record("M06", arm, "pass" if counts["ok"] and counts["passed"] == 12 else "fail", brief="설치본 selftest 통과 %d 실패 %d 건너뜀 %d" % (counts["passed"], counts["failed"], counts["skipped"]), target="real", **counts))
        else:
            ctx.add(record("M06", arm, "fail", brief="설치본 실행 파일 없음", target="real"))
        scan_targets = [entry["setup"], root] + ([entry["full"]] if entry.get("full") else [])
        defender_scan(ctx, arm, scan_targets, defender_state, target="real")
        m19_long_path(ctx, arm, entry, exe_name=REAL_EXE, real=True)
        m12_uninstall(ctx, arm, root, data, before_links, before_keys, "real")
    finally:
        cleanup_data(ctx, data)


def defender_scan(ctx, arm, paths, state, *, target="tiny"):
    """M16 — 읽기 전용 Defender 검사(치료 없음). 시간 예산을 넘으면 건너뛴다."""
    if state["spent"] > DEFENDER_BUDGET_SECONDS:
        ctx.add(record("M16", arm, "skip", note="검사 시간 예산을 다 썼다", brief="건너뜀", target=target))
        return
    began = ctx.host.now()
    scan = ctx.host.defender_scan([Path(path) for path in paths if Path(path).exists()])
    state["spent"] += ctx.host.now() - began
    status = scan.get("status")
    mapped = {"clean": "pass", "threats_found": "fail", "scan_failed": "error", "not_run": "unavailable"}.get(status, "error")
    ctx.add(record("M16", arm, mapped, brief="Defender %s %s초" % (status, scan.get("seconds", "?")), target=target, tool_status=status, exit_codes=scan.get("exit_codes", []), engine=scan.get("engine_version", ""),
                   signatures=scan.get("signature_version", ""), targets=scan.get("targets", []), note=tail(scan.get("reason", ""), 200)))


def m16_status(ctx):
    """Defender 실시간 보호 상태(읽기 전용 질의)."""
    result = ctx.host.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                           "Get-MpComputerStatus | Select-Object AMServiceEnabled,AntivirusEnabled,RealTimeProtectionEnabled | ConvertTo-Json -Compress"], timeout=60)
    import json
    try:
        data = json.loads(result.out) if result.ok and result.out.strip() else {}
    except ValueError:
        data = {}
    ctx.add(record("M16", "-", "info", brief="실시간 보호 %s" % data.get("RealTimeProtectionEnabled", "읽지 못함"), target="status", defender=data))


def m19_long_path(ctx, arm, entry_or_inst, exe_name, real=False):
    """한글·공백이 든 100자 안팎 경로에 설치해 본다(실제 묶음은 --selftest, 작은 앱은 실행) 뒤 제거."""
    base = ctx.work / "run" / arm / ("한글 공백 " + "가나다라마바 " * 6).strip()
    root = base / ("real" if real else "tiny")
    setup = entry_or_inst["setup"] if real else entry_or_inst["0.0.1"]["setup"]
    result, ready, _log = do_install(ctx, arm, setup, root, "long-path" + ("-real" if real else ""), korean=(arm == "C"), wait_for=exe_name)
    exe = app_dir(arm, root) / exe_name
    outcome = {"installed": bool(ready and exe.is_file()), "path_chars": len(str(root))}
    if outcome["installed"]:
        if real:
            counts = real_selftest(ctx, exe)
            outcome["selftest_ok"] = counts["ok"]
        else:
            ran = ctx.host.run([str(exe)], timeout=30, cwd=exe.parent, env={"SPIKE_LOG": str(ctx.logs / ("%s-long.spikelog" % arm))})
            outcome["selftest_ok"] = ran.rc == 0
    ok = result.ok and outcome["installed"] and outcome.get("selftest_ok", False)
    ctx.add(record("M19", arm, "pass" if ok else "fail", brief="경로 %d자 설치 %s 실행 %s" % (outcome["path_chars"], "ok" if outcome["installed"] else "실패", "ok" if outcome.get("selftest_ok") else "실패"), target="real" if real else "tiny", rc=result.rc, **outcome))
    do_uninstall(ctx, arm, root)
    import shutil
    shutil.rmtree(base, ignore_errors=True)


def m21_renamed_setup(ctx, arm):
    """A·B — 설치 파일 이름을 ChanceBlogDesktop-0.0.1-Setup.exe 로 바꿔도 설치되는지."""
    inst = installers_of(ctx, arm)
    if not inst or "0.0.1" not in inst:
        ctx.add(record("M21", arm, "unavailable", note="설치 파일이 없다", brief="없음"))
        return
    import shutil
    folder = ctx.work / "run" / arm / "renamed"
    folder.mkdir(parents=True, exist_ok=True)
    renamed = folder / "ChanceBlogDesktop-0.0.1-Setup.exe"
    shutil.copyfile(inst["0.0.1"]["setup"], renamed)
    root = ctx.work / "run" / arm / "renamed-root"
    result, ready, _log = do_install(ctx, arm, renamed, root, "renamed", korean=(arm == "C"))
    ctx.add(record("M21", arm, "pass" if result.ok and ready else "fail", brief="이름 바꾼 Setup 종료 %s %s" % (result.rc, "설치됨" if ready else "안 됨"), rc=result.rc, installed=ready, note=tail(result.text(), 160) if not (result.ok and ready) else ""))
    do_uninstall(ctx, arm, root)


def m13_id_collision(ctx):
    """A — 패키지 ID 를 ChanceBlogDesktop 으로 일부러 만든 Velopack 설치를 제거하면 대소문자만 다른 데이터 폴더(ChanceblogDesktop)가 지워지는가(F2 재현)."""
    entry = ctx.state.get("installers", {}).get("A", {}).get("idtest") or {}
    local = ctx.env("LOCALAPPDATA")
    if not entry.get("setup") or not local:
        ctx.add(record("M13", "A", "unavailable", note="ID 시험용 설치 파일이나 LOCALAPPDATA 가 없다", brief="없음"))
        return
    data_folder = Path(local) / "ChanceblogDesktop"
    install_folder = Path(local) / "ChanceBlogDesktop"
    if data_folder.exists() or install_folder.exists():
        ctx.add(record("M13", "A", "skip", note="러너에 같은 이름의 폴더가 이미 있어 건드리지 않았다", brief="건너뜀"))
        return
    try:
        ctx.logs.mkdir(parents=True, exist_ok=True)
        installed = ctx.host.run([str(entry["setup"]), "--silent", "--log", str(ctx.logs / "A-idtest.log")], timeout=300)
        ready = wait_until(ctx, lambda: (install_folder / "Update.exe").is_file(), 60, 1.0)
        data_folder.mkdir(parents=True, exist_ok=True)                 # 데이터는 설치 뒤에 둔다 — 설치가 지우는 것과 제거가 지우는 것을 가른다
        sentinel = data_folder / "spike-sentinel.txt"
        sentinel.write_text(SENTINEL_TEXT, encoding="utf-8")
        same_folder = bool(ready and install_folder.exists() and os.path.samefile(install_folder, data_folder))
        removed = ctx.host.run([str(install_folder / "Update.exe"), "uninstall", "--silent"], timeout=180)
        wait_until(ctx, lambda: not install_folder.exists(), 45, 1.0)
        survived = sentinel.exists()
        brief = "설치 못 함(종료 %s)" % installed.rc if not ready else "같은 폴더 %s 제거 뒤 데이터 %s" % ("예" if same_folder else "아니오", "남음" if survived else "지워짐")
        ctx.add(record("M13", "A", "info", brief=brief, installed=ready, same_folder=same_folder, sentinel_survived=survived, install_rc=installed.rc, uninstall_rc=removed.rc,
                       note="지워지면 '패키지 ID 는 데이터 폴더 이름과 대소문자까지 달라야 한다' 규칙이 확정된다(F2)"))
    finally:
        import shutil
        shutil.rmtree(data_folder, ignore_errors=True)
        shutil.rmtree(install_folder, ignore_errors=True)


def m15_native(ctx):
    """A·B — 번들에 들어오는 네이티브 부품(휠 안 파일·PE 가져오기 표)과 설치 폴더의 Update.exe·Setup.exe 의 가져오기 표(웹 접속 가능 DLL 이름) 기록."""
    tools = ctx.state.get("tools", {})
    wheel = tools.get("sdk", {}).get("wheel")
    if wheel and Path(wheel).is_file() and not zipfile.is_zipfile(wheel):
        ctx.add(record("M15", "A", "error", note="휠이 zip 으로 읽히지 않는다", brief="휠 깨짐", target="wheel"))
    elif wheel and Path(wheel).is_file():
        inventory = wheel_inventory(wheel)
        nets = sorted({name for item in inventory["binaries"] for name in item["net"]})
        ctx.add(record("M15", "A", "info", brief="휠 %s MB 부품 %d 웹 DLL %s" % (mb(inventory["total_bytes"]), len(inventory["binaries"]), ",".join(nets) or "없음"), target="wheel", total_bytes=inventory["total_bytes"],
                       files=[item["name"] for item in inventory["files"]][:40], binaries=inventory["binaries"]))
    else:
        ctx.add(record("M15", "A", "unavailable", note="휠을 찾지 못했다", brief="없음", target="wheel"))
    sizes = {}
    for kind in ("plain", "sdk"):
        folder = ctx.state.get("bundles", {}).get(kind, {}).get("0.0.1")
        sizes[kind] = dir_size(folder) if folder and Path(folder).exists() else None
    if sizes["plain"] and sizes["sdk"]:
        ctx.add(record("M15", "A", "info", brief="SDK 판 묶음이 %s MB 더 크다" % mb(sizes["sdk"] - sizes["plain"]), target="bundle-delta", plain_bytes=sizes["plain"], sdk_bytes=sizes["sdk"]))
    for arm in ("A", "B"):
        setup = (installers_of(ctx, arm).get("0.0.1") or {}).get("setup")
        if setup and Path(setup).is_file():
            data = Path(setup).read_bytes()
            imports = pe_imports(data)
            ctx.add(record("M15", arm, "info", brief="Setup 가져오기 %d개 웹 DLL %s" % (len(imports), ",".join(net_imports(imports)) or "없음"), target="setup", imports=imports, net=net_imports(imports), setup_bytes=len(data)))


def m17_korean(ctx):
    """한국어 — C 는 Inno 로그의 언어 줄과 Korean.isl 안내 글, A·B 는 Setup 글자에 한글이 있는지."""
    for arm in ("A", "B"):
        setup = (installers_of(ctx, arm).get("0.0.1") or {}).get("setup")
        if setup and Path(setup).is_file():
            samples = hangul_samples(Path(setup).read_bytes())
            ctx.add(record("M17", arm, "info", brief="Setup 한글 글 UTF-8 %d·UTF-16 %d(추정)" % (samples["utf8"], samples["utf16"]), samples=samples["samples"], note="영어뿐이면 '마법사 없음·오류 상자 영어' 로 본다(무작위 바이트가 우연히 맞을 수 있어 추정)"))
        else:
            ctx.add(record("M17", arm, "unavailable", note="설치 파일이 없다", brief="없음"))
    log = ctx.logs / "C-install-1.log"
    text = read_text_guess(log) if log.exists() else ""
    lang = re.search(r"SPIKE_LANG=(\S+)", text)
    nxt = re.search(r"SPIKE_NEXT=(.*)", text)
    has_hangul = bool(nxt and re.search(r"[가-힣]", nxt.group(1)))
    if text:
        ctx.add(record("M17", "C", "pass" if (lang and lang.group(1).lower() == "korean" and has_hangul) else "fail", brief="언어 %s 안내 글 한글 %s" % (lang.group(1) if lang else "?", "있음" if has_hangul else "없음"),
                       language=lang.group(1) if lang else "", next_button_hangul=has_hangul, log_chars=len(text)))
    else:
        ctx.add(record("M17", "C", "unavailable", note="Inno 설치 로그를 읽지 못했다", brief="로그 없음"))


def std_user_script():
    return ("$pw = ConvertTo-SecureString $env:SPIKE_PW -AsPlainText -Force; "
            "$cred = New-Object System.Management.Automation.PSCredential('.\\' + $env:SPIKE_USER, $pw); "
            "$p = Start-Process -FilePath $env:SPIKE_SETUP -ArgumentList $env:SPIKE_ARGS -Credential $cred -LoadUserProfile -Wait -PassThru -WorkingDirectory $env:SPIKE_CWD; "
            "exit $p.ExitCode")


def std_user_folders(ctx):
    """표준 사용자 시험이 건드리는 폴더 둘 → (공용 폴더 안의 작업 자리, 사용자 프로필 폴더) 또는 None. 환경 변수 PUBLIC(윈도 표준 — 러너에서는 공용 사용자 폴더)이 없으면 None 이다 — 실제 폴더 이름을 짐작해 쓰지 않는다.
    프로필이 생기는 뿌리는 SPIKE_USERS_DIR(시험이 지정)이 있으면 그것, 없으면 PUBLIC 의 위 폴더(러너에서는 사용자 폴더 전체)다."""
    public_root = ctx.env("PUBLIC")
    if not public_root:
        return None
    users_root = ctx.env("SPIKE_USERS_DIR") or str(Path(public_root).parent)
    return Path(public_root) / "spike_std", Path(users_root) / STD_USER / "AppData" / "Local"


def m18_standard_user(ctx, arm):
    """러너에 임시 표준 사용자를 만들어 그 계정으로 무음 설치를 시도한다. 안 되면 '시도 불가' 로 기록한다(운영자 실기로)."""
    import secrets
    import shutil
    inst = installers_of(ctx, arm)
    if not inst or "0.0.1" not in inst:
        ctx.add(record("M18", arm, "unavailable", note="설치 파일이 없다", brief="없음"))
        return
    folders = std_user_folders(ctx)
    if not folders:                                                 # 사용자를 만들기 전에 멈춘다
        ctx.add(record("M18", arm, "unavailable", note="공용 폴더 환경 변수(PUBLIC)가 없어 임시 사용자를 만들지 않았다 — 실제 폴더 이름을 짐작해 쓰지 않는다", brief="시도 불가: 환경 변수 없음"))
        return
    public, profile = folders
    password = PASSWORD_PREFIX + secrets.token_urlsafe(12)
    ctx.hide(password)                                              # net user 명령줄에 들어가는 값이다 — 어떤 도구가 되울려도 기록에서는 가린다
    ctx.hide(password[len(PASSWORD_PREFIX):])                       # 무작위 부분만(접두어의 느낌표가 바뀌거나 빠져서 되울려도)
    ctx.hide(password.upper())                                      # 대문자 되울림(가리개가 대소문자를 구분하지 않아도 새지 않게 변형을 한 줄씩 더 둔다)
    ctx.hide(password.lower())                                      # 소문자 되울림
    ctx.hide(quote(password, safe=""))                              # URL 인코딩 되울림(느낌표가 %21 로) — 접두어까지 한 덩어리로 가린다
    created = ctx.host.run(["net", "user", STD_USER, password, "/add", "/Y"], timeout=60)
    if not created.ok:
        ctx.add(record("M18", arm, "unavailable", note="임시 사용자를 만들지 못했다(rc %s)" % created.rc, brief="시도 불가: 사용자 만들기 실패"))
        return
    try:
        public.mkdir(parents=True, exist_ok=True)
        setup = public / ("setup-%s.exe" % arm)
        shutil.copyfile(inst["0.0.1"]["setup"], setup)
        ctx.host.run(["icacls", str(public), "/grant", "Users:(OI)(CI)RX"], timeout=60)
        arguments = "--silent" if velopack_arm(arm) else "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-"
        result = ctx.host.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", std_user_script()], timeout=180,
                              env={"SPIKE_PW": password, "SPIKE_USER": STD_USER, "SPIKE_SETUP": str(setup), "SPIKE_ARGS": arguments, "SPIKE_CWD": str(public)})
        installed = bool(profile.is_dir() and any(profile.rglob("VERSION")))
        if result.rc == 0 and installed:
            ctx.add(record("M18", arm, "pass", brief="표준 사용자 설치 성공 %s초" % result.seconds, rc=result.rc, seconds=result.seconds))
        elif result.timed_out or result.rc not in (0,):
            ctx.add(record("M18", arm, "unavailable", brief="시도 불가 또는 실패(rc %s)" % result.rc, rc=result.rc, installed=installed, note="러너 안에서 다른 계정으로 설치를 못 돌렸다 — 운영자 실기(T-INST-04)로 넘긴다. " + tail(ctx.mask(result.text()), 160)))
        else:
            ctx.add(record("M18", arm, "fail", brief="종료 0 인데 설치 흔적 없음", rc=result.rc, installed=installed))
    finally:
        ctx.host.run(["net", "user", STD_USER, "/delete"], timeout=60)
        shutil.rmtree(public, ignore_errors=True)


def m20_sizes(ctx):
    """설치 파일·nupkg·zip·설치 폴더 크기와 단계별 시간을 모아 적는다(기록)."""
    steps = {name: info.get("seconds") for name, info in ctx.state.get("steps", {}).items()}
    sizes = {}
    for arm in ARMS:
        for kind in ("tiny", "real"):
            entry = ctx.state.get("installers", {}).get(arm, {}).get(kind)
            if kind == "tiny" and entry:
                entry = entry.get("0.0.1")
            if entry:
                sizes["%s-%s" % (arm, kind)] = {"setup_mb": mb(entry.get("bytes", 0)), "package_mb": mb(entry.get("package_bytes", 0)) if entry.get("package_bytes") else None, "seconds": entry.get("seconds")}
    real = ctx.state.get("bundles", {}).get("real", {})
    ctx.add(record("M20", "-", "info", brief="실제 묶음 %s MB zip %s MB, 단계 시간 %s" % (mb(real.get("bytes", 0)), mb(real.get("zip_bytes", 0)), ",".join("%s %ss" % (key, value) for key, value in steps.items() if value is not None)),
                   bundle_mb=mb(real.get("bytes", 0)), zip_mb=mb(real.get("zip_bytes", 0)), installers=sizes, steps=steps))


def m22_portable(ctx):
    """같은 묶음 zip 을 풀어 --selftest 를 돌리고 설치본 결과와 견준다(데이터 폴더 이름 상수는 하나 — 실제 같은 폴더인지는 운영자 실기)."""
    real = ctx.state.get("bundles", {}).get("real", {})
    archive = real.get("zip")
    if not archive or not Path(archive).is_file():
        ctx.add(record("M22", "-", "unavailable", note="실제 묶음 zip 이 없다", brief="없음"))
        return
    target = ctx.work / "run" / "portable"
    import shutil
    shutil.rmtree(target, ignore_errors=True)
    with zipfile.ZipFile(archive) as opened:
        opened.extractall(target)
    exes = list(target.rglob(REAL_EXE))
    if not exes:
        ctx.add(record("M22", "-", "fail", brief="압축을 풀었는데 실행 파일이 없다"))
        return
    counts = real_selftest(ctx, exes[0])
    infos = list(target.rglob("PACKAGE_INFO.json"))
    ctx.add(record("M22", "-", "pass" if counts["ok"] and counts["passed"] == 12 else "fail", brief="휴대용 selftest 통과 %d 실패 %d" % (counts["passed"], counts["failed"]), **counts,
                   package_info_sha256=sha256_file(infos[0]) if infos else "", note="설치본과 휴대용은 같은 데이터 폴더 이름 상수(ChanceblogDesktop)를 쓴다 — 실제로 같은 폴더인지는 운영자 실기 T-INST-09"))
    shutil.rmtree(target, ignore_errors=True)


def run_measurements(ctx):
    """M01 에서 M22 를 이 순서로 돈다(방화벽 규칙을 넣은 채 M14 반복). 항목마다 오류를 가둬 기록하고, 시간 예산을 넘으면 남은 흐름은 건너뛴다."""
    ctx.results = []
    ctx.logs.mkdir(parents=True, exist_ok=True)
    began = ctx.host.now()
    defender = {"spent": 0.0}
    ctx.guard("M01", "-", m01_tools, ctx)
    ctx.guard("M02", "-", m02_m03_from_state, ctx)
    ctx.guard("M04", "-", m04_admin, ctx)
    ctx.guard("M16", "-", m16_status, ctx)
    ctx.guard("M07", "-", m07_real_bundle, ctx)
    control = ctx.guard("M14", "-", firewall_control, ctx) or {"effective": None, "reason": "확인 실패"}
    ctx.add(record("M14", "-", "info", brief="방화벽 규칙 효과 확인: %s" % {True: "막힘", False: "안 막힘", None: "확인 못 함"}[control.get("effective")], control=control))
    try:
        for arm in ARMS:
            if ctx.over_budget():
                ctx.add(record("M05", arm, "skip", note="시간 예산을 넘어 건너뛰었다", brief="건너뜀"))
                continue
            ctx.guard("M05", arm, flow_tiny, ctx, arm)
        for arm in ARMS:
            if not ctx.over_budget():
                ctx.guard("M14", arm, flow_blocked, ctx, arm, control)
        unblock_all(ctx)
        for arm in ("B", "C"):
            if not ctx.over_budget():
                ctx.guard("M05", arm, flow_real, ctx, arm, defender)
        for arm in ARMS:
            if not ctx.over_budget():
                inst = installers_of(ctx, arm)
                if inst and "0.0.1" in inst:
                    ctx.guard("M19", arm, m19_long_path, ctx, arm, inst, TINY_EXE[arm])
        for arm in ("A", "B"):
            ctx.guard("M21", arm, m21_renamed_setup, ctx, arm)
        ctx.guard("M13", "A", m13_id_collision, ctx)
        if not ctx.over_budget():
            tiny_a = (installers_of(ctx, "A").get("0.0.1") or {}).get("setup")
            if tiny_a and not ctx.over_budget():
                ctx.guard("M16", "A", defender_scan, ctx, "A", [tiny_a], defender)
        for arm in ARMS:
            if not ctx.over_budget():
                ctx.guard("M18", arm, m18_standard_user, ctx, arm)
    finally:
        unblock_all(ctx)
        kill_images(ctx, {"SpikeApp.exe", "SpikeAppSdk.exe", REAL_EXE})
    ctx.guard("M15", "-", m15_native, ctx)
    ctx.guard("M17", "-", m17_korean, ctx)
    ctx.guard("M22", "-", m22_portable, ctx)
    ctx.guard("M20", "-", m20_sizes, ctx)
    ctx.note_step("measure", "ok", round(ctx.host.now() - began, 1))
    ctx.save()
    return ctx.results
