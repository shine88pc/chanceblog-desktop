# -*- coding: utf-8 -*-
"""build_rules.py - 글자 읽기 추가 도구 빌드의 점검 규칙을 순수 함수로 둔 것(설계서 5-6·6-2 T-E, a 단계 보고 ⑥ 의 R1-R4, 결정 D-528).

표준 라이브러리만, 파이썬 3.10 문법, 파일·네트워크·시계 없음(입력은 모두 인자) — 그래서 빌드 없이(pefile·PyInstaller 없이) 합성 입력으로 시험한다(tests/test_ocr_addon_build_rules.py).
build_ocr_addon.py 가 실제 묶음을 읽어 이 함수들에 넘기고, 돌려받은 문제 글이 하나라도 있으면 빌드가 실패한다(산출물을 만들지 않는다). 앱 본체(src/)는 이 파일을 가져오지 않는다.
  R1 가져오기 표: 네트워크 DLL 을 가져오는 파일은 python312.dll·_socket.pyd·select.pyd 셋뿐(CPython 표준 구성요소)
  R2 묶음 파일: FFmpeg DLL·pem 류·기본 모델이 없고, 모델 2개·사전의 크기와 SHA-256 이 박힌 값과 같다
  R3 부품: ssl·_ssl·libcrypto·_overlapped·_multiprocessing·urllib3·certifi 가 없고 requests 는 가짜 껍데기다
  R4 자가 점검: --selftest 의 결과가 모든 칸에서 통과(소켓 가드 음성 대조 5/5·정상 읽기 시도 0)
"""
import datetime
import re

# R1 ------------------------------------------------------------------------------------------------------------------
NET_DLLS = ("ws2_32.dll", "wsock32.dll", "mswsock.dll", "wininet.dll", "winhttp.dll", "iphlpapi.dll", "dnsapi.dll", "urlmon.dll", "wldap32.dll",
            "httpapi.dll", "netapi32.dll", "rasapi32.dll", "mpr.dll", "webservices.dll", "wlanapi.dll", "fwpuclnt.dll", "winnsi.dll", "nsi.dll", "dhcpcsvc.dll")
# 허용 예외 = 파이썬(CPython) 표준 구성요소 셋(총괄 결정 — python312.dll 은 인터프리터 본체라 어떤 파이썬 묶음도 뺄 수 없다). 위치까지 정확히 맞아야 한다.
PE_EXCEPTIONS = ("_internal/python312.dll", "_internal/_socket.pyd", "_internal/select.pyd")
PE_EXCEPTION_NET_OK = ("ws2_32.dll", "iphlpapi.dll")                  # 예외 파일이 가져와도 되는 네트워크 DLL(a 단계 실측) — wininet 같은 것이 끼면 예외 파일이어도 실패
PE_REQUIRED = ("ocr_worker.exe", "_internal/python312.dll")           # 점검 대상에 반드시 있어야 하는 파일 — 없으면 점검이 묶음을 못 훑은 것(아무것도 못 보고 통과하는 일 방지)
# R2 ------------------------------------------------------------------------------------------------------------------
FORBIDDEN_FILES = (r"opencv_videoio_ffmpeg.*\.dll", r".*\.pem", r".*\.crt", r".*\.key")
# R3 ------------------------------------------------------------------------------------------------------------------
FORBIDDEN_MODULES = ("ssl", "_ssl", "_hashlib", "libcrypto", "libssl", "_overlapped", "_multiprocessing", "urllib3", "certifi")
STUB_VERSION = "0+offline-stub"
RUNTIME_ABSENT = ("ssl", "urllib3", "certifi", "asyncio", "multiprocessing")     # 동결본이 실제로 못 가져와야 하는 것 — --selftest 의 imports_optional 에 '없음' 으로 적힌다(작업자가 직접 시도한 기록)
ABSENT_PREFIX = "없음"
# 묶음 안 글 파일에서 훑는 키 모양 — 본체 packaging/pkgcommon.py 의 KEY_SHAPES 와 같은 목록(시험이 같음을 지킨다)
KEY_SHAPES = (
    r"AIza[0-9A-Za-z_-]{35}",
    r"(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}",
    r"[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}",
    r"GOCSPX-[A-Za-z0-9_-]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"sk-[A-Za-z0-9]{32,}|gsk_[A-Za-z0-9]{40,}",
)
EXPECTED_KEYS = ("models/det/inference.onnx", "models/rec/inference.onnx", "data/ppocrv5_korean_dict.txt")
_HEX64, _COMMIT = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_PATH = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9A-Za-z.+!_-]+)((?:\s+--hash=sha256:[0-9a-f]{64})*)\s*$")
VERSION_PATTERN = r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?"


def norm_path(path):
    """묶음 안 상대 경로를 비교용으로 바꾼다 — 슬래시 하나로, 앞의 ./ 를 떼고, 소문자(윈도는 대소문자를 가리지 않는다)."""
    text = str(path).replace(chr(92), "/")
    while text.startswith("./"):
        text = text[2:]
    return text.lower()


def canon(name):
    return re.sub(r"[-_.]+", "-", str(name)).lower()


# ---- R1 ----------------------------------------------------------------------------------------------------------------
def net_imports(row):
    """가져오기 표 한 줄({path, imports, delay, bound})에서 네트워크 DLL 이름들(정적·지연·묶음 가져오기 모두)."""
    found = set()
    for key in ("imports", "delay", "bound"):
        found.update(str(name).lower() for name in row.get(key) or ())
    return sorted(found & set(NET_DLLS))


def pe_problems(rows, errors=()):
    """R1 — 모든 exe·DLL·pyd 의 가져오기 표. 네트워크 DLL 을 가져오는 파일은 PE_EXCEPTIONS 셋뿐이고, 그 셋도 ws2_32·iphlpapi 밖의 네트워크 DLL 은 못 가져온다."""
    problems, seen = [], set()
    for row in rows:
        path = norm_path(row["path"])
        seen.add(path)
        net = net_imports(row)
        if not net:
            continue
        if path not in PE_EXCEPTIONS:
            problems.append("R1 가져오기 표에 네트워크 DLL 이 있는 파일(허용 예외 밖): %s (%s)" % (row["path"], ", ".join(net)))
        elif [name for name in net if name not in PE_EXCEPTION_NET_OK]:
            problems.append("R1 허용 예외 파일이 허용 밖의 네트워크 DLL 을 가져온다: %s (%s)" % (row["path"], ", ".join(net)))
    for need in PE_REQUIRED:
        if need not in seen:
            problems.append("R1 가져오기 표 점검 대상에 %s 가 없다 — 점검이 묶음을 제대로 훑지 못했다" % need)
    if errors:
        problems.append("R1 가져오기 표를 읽지 못한 파일 %d개: %s" % (len(errors), ", ".join(str(item) for item in list(errors)[:5])))
    return problems


# ---- R2 ----------------------------------------------------------------------------------------------------------------
def bundle_file_problems(sizes, expected, digest_of):
    """R2 — sizes: {묶음 안 상대 경로: 바이트}, expected: {경로: (바이트, SHA-256)}, digest_of: 경로 -> SHA-256(박힌 파일 셋에만 부른다)."""
    problems = []
    banned = sorted(path for path in sizes if any(re.fullmatch(pattern, norm_path(path).rsplit("/", 1)[-1]) for pattern in FORBIDDEN_FILES))
    if banned:
        problems.append("R2 묶음에 있으면 안 되는 파일(FFmpeg DLL·pem 류): " + ", ".join(banned[:6]))
    extra = sorted(path for path in sizes if path.lower().endswith(".onnx") and path not in expected)
    if extra:
        problems.append("R2 기본 모델·알 수 없는 모델 파일이 묶음에 있다: " + ", ".join(extra[:6]))
    if "ocr_worker.exe" not in sizes:
        problems.append("R2 ocr_worker.exe 가 묶음에 없다")
    for key, (size, digest) in sorted(expected.items()):
        if key not in sizes:
            problems.append("R2 모델·사전 파일이 없다: " + key)
        elif sizes[key] != size:
            problems.append("R2 모델·사전 크기가 박힌 값과 다르다: %s (%s 바이트, 기대 %s)" % (key, sizes[key], size))
        elif digest_of(key) != digest:
            problems.append("R2 모델·사전 SHA-256 이 박힌 값과 다르다: " + key)
    return problems


# ---- R3 ----------------------------------------------------------------------------------------------------------------
def module_key(name):
    """묶음 안 이름(모듈·파일·폴더)을 부품 이름 하나로 줄인다 — _ssl.cp312-win_amd64.pyd 는 _ssl, libcrypto-3.dll 은 libcrypto, urllib3.util.retry 는 urllib3."""
    base = str(name).replace(chr(92), "/").rsplit("/", 1)[-1].lower()
    return re.split(r"[.-]", base, maxsplit=1)[0]


def module_problems(names, imports, optional):
    """R3 — names: 묶음에 실제 들어간 최상위 모듈·파일 이름들, imports: --selftest 의 imports 칸({부품: 판 글}), optional: imports_optional 칸(동결본이 직접 가져와 보려 한 기록)."""
    problems = []
    if not names:
        problems.append("R3 묶음 안 부품 목록을 읽지 못했다")
    found = sorted({module_key(name) for name in names} & set(FORBIDDEN_MODULES))
    if found:
        problems.append("R3 묶음에 있으면 안 되는 부품(OpenSSL·asyncio·진짜 requests 계열): " + ", ".join(found))
    value = (imports or {}).get("requests")
    if value != STUB_VERSION:
        problems.append("R3 requests 가 가짜 껍데기(%s)가 아니다: %s" % (STUB_VERSION, value))
    for name in RUNTIME_ABSENT:
        seen = (optional or {}).get(name)
        if not (isinstance(seen, str) and seen.startswith(ABSENT_PREFIX)):
            problems.append("R3 동결본이 %s 를 가져올 수 있거나 확인 기록이 없다: %s" % (name, seen))
    return problems


# ---- R4 ----------------------------------------------------------------------------------------------------------------
def selftest_problems(report, exit_code):
    """R4 — --selftest 가 낸 JSON 한 줄(report)과 종료 코드. 작업자가 낸 ok 한 칸만 믿지 않고 세부 칸을 하나씩 다시 본다."""
    if not isinstance(report, dict):
        return ["R4 --selftest 의 마지막 줄을 JSON 으로 읽지 못했다"]
    problems = []
    if exit_code != 0:
        problems.append("R4 --selftest 종료 코드가 %s 다" % exit_code)
    probes = report.get("negative_control")
    checks = (("ok", report.get("ok") is True), ("frozen", report.get("frozen") is True), ("guard_active", report.get("guard_active") is True),
              ("negative_control 5/5 막힘", isinstance(probes, list) and len(probes) == 5 and all(isinstance(item, dict) and item.get("blocked_and_counted") is True for item in probes)),
              ("negative_control_attempts == 5", report.get("negative_control_attempts") == 5),
              ("시험용 주소만 시도", report.get("negative_control_recent_targets_only_test_addresses") is True),
              ("loopback_not_counted", report.get("loopback_not_counted") is True), ("files_ok", report.get("files_ok") is True),
              ("imports_failed 비어 있음", report.get("imports_failed") == []), ("selfcheck_ok(점검 그림이 같은 글로 읽힘)", report.get("selfcheck_ok") is True),
              ("정상 읽기 소켓 시도 0", report.get("guard_attempts_during_normal_read") == 0))
    problems += ["R4 --selftest 칸이 통과가 아니다: " + label for label, good in checks if not good]
    return problems


# ---- 묶음 글 파일(키 모양) · 설치 · 잠금 ----------------------------------------------------------------------------------
def key_shape_problems(items):
    """items: (상대 경로, 글) 들 — 키 모양 글이 든 파일 이름만 알린다(걸린 글은 담지 않는다)."""
    pattern = re.compile("|".join(KEY_SHAPES))
    return ["키 모양 글이 든 파일: " + path for path, text in items if pattern.search(text)]


def parse_lock(text):
    """잠금 파일 -> [{name, version, hashes}] — 모든 줄이 name==version 과 해시, 중복 없음(어긋나면 ValueError)."""
    pins, seen = [], set()
    for number, raw in enumerate(re.sub(r"\\\r?\n[ \t]*", " ", text).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _PIN.match(line)
        if not match or not match.group(3).strip():
            raise ValueError("잠금 파일 %d행이 'name==version --hash=sha256:…' 꼴이 아니다" % number)
        key = canon(match.group(1))
        if key in seen:
            raise ValueError("잠금 파일 %d행: 같은 패키지가 두 번 있다" % number)
        seen.add(key)
        pins.append({"name": key, "version": match.group(2), "hashes": re.findall(r"--hash=sha256:([0-9a-f]{64})", match.group(3))})
    if not pins:
        raise ValueError("잠금 파일에 핀이 없다")
    return pins


def installed_problems(pins, installed):
    """설치된 판이 잠금 파일과 같은가 — installed: {이름: 판 글 또는 None}. 해시 없이 깔린 것(--require-hashes 를 빠뜨림)을 판 차이로 잡는 두 번째 그물이다."""
    return ["설치된 판이 잠금 파일과 다르다: %s (잠금 %s, 설치 %s)" % (pin["name"], pin["version"], installed.get(pin["name"])) for pin in pins if installed.get(pin["name"]) != pin["version"]]


def pin_age_problems(pins, meta):
    """모든 핀은 PyPI 업로드 후 min_age_days(14일) 이상 — 고정일(pinned_on) 기준. meta: requirements-ocr.meta.json 내용."""
    problems = []
    try:
        pinned = datetime.date.fromisoformat(meta["pinned_on"])
        floor = int(meta["min_age_days"])
        known = meta["packages"]
    except (KeyError, TypeError, ValueError):
        return ["핀 메타 파일의 모양이 다르다(pinned_on·min_age_days·packages)"]
    for pin in pins:
        entry = known.get(pin["name"])
        if not isinstance(entry, dict) or entry.get("version") != pin["version"]:
            problems.append("핀 메타에 이 판이 없다: %s %s" % (pin["name"], pin["version"]))
            continue
        try:
            age = (pinned - datetime.date.fromisoformat(entry["uploaded"])).days
        except (KeyError, TypeError, ValueError):
            problems.append("핀 메타의 업로드 날짜를 읽지 못했다: " + pin["name"])
            continue
        if age < floor:
            problems.append("PyPI 업로드 후 %d일밖에 안 된 핀: %s %s (%d일 이상이어야 한다)" % (age, pin["name"], pin["version"], floor))
    return problems


# ---- 모델 잠금 · 산출물 이름 ------------------------------------------------------------------------------------------------
def lock_problems(lock):
    """models.lock.json 모양 점검 — 알려진 파일 셋(EXPECTED_KEYS)뿐, 크기·SHA-256·커밋·저장소 이름·경로 모양. 어긋나면 문제 글들."""
    if not isinstance(lock, dict) or lock.get("schema") != 1 or not isinstance(lock.get("files"), list):
        return ["models.lock.json 의 모양이 다르다(schema 1·files 목록)"]
    problems, keys = [], []
    for entry in lock["files"]:
        if not isinstance(entry, dict):
            problems.append("files 항목이 객체가 아니다")
            continue
        key, source = entry.get("key"), entry.get("source")
        keys.append(key)
        if type(entry.get("bytes")) is not int or entry["bytes"] <= 0 or not _HEX64.fullmatch(str(entry.get("sha256", ""))):
            problems.append("크기 또는 SHA-256 모양이 다르다: %s" % key)
        if not isinstance(source, dict) or source.get("kind") not in ("huggingface", "repo") or not _PATH.fullmatch(str(source.get("path", ""))) or {".", ".."} & set(str(source.get("path")).split("/")):
            problems.append("source 모양이 다르다: %s" % key)
        elif source["kind"] == "huggingface" and (not _REPO.fullmatch(str(source.get("repo", ""))) or not _COMMIT.fullmatch(str(source.get("commit", "")))):
            problems.append("저장소 이름 또는 커밋(40자리 16진수)이 다르다: %s" % key)
    if sorted(map(str, keys)) != sorted(EXPECTED_KEYS):
        problems.append("파일 목록이 알려진 셋(모델 2개·사전)과 다르다: %s" % sorted(map(str, keys)))
    return problems


def expected_files(lock):
    """{키: (바이트, SHA-256)} — 잠금 파일에서(점검은 lock_problems 가 빈 목록일 때만 부른다)."""
    return {entry["key"]: (entry["bytes"], entry["sha256"]) for entry in lock["files"]}


def zip_name(version):
    """올리는 압축 파일 이름 — 본체의 허용 모양 ChanceBlogDesktop-*-win64.zip 안에 든다(tests/test_workflow_artifacts.py 의 허용 목록)."""
    if not isinstance(version, str) or not re.fullmatch(VERSION_PATTERN, version):
        raise ValueError("버전 글의 모양이 다르다")
    return "ChanceBlogDesktop-OCR-%s-win64.zip" % version


def render_sums(entries):
    """sha256sum -c 로 확인할 수 있는 모양 — `<해시>  <이름>` 한 줄씩(이름 순, 줄 끝 LF). 본체의 SHA256SUMS 와 같은 모양."""
    return "".join("%s  %s\n" % (digest, name) for name, digest in sorted(entries))


def utc_text(epoch):
    return datetime.datetime.fromtimestamp(int(epoch), tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
