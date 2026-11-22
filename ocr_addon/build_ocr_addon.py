# -*- coding: utf-8 -*-
"""build_ocr_addon.py - 글자 읽기 작업자(추가 도구) 빌드: 동결(PyInstaller onedir) -> 모델·사전 얹기 -> 쓰지 않는 것 제거 -> 묶음 점검 -> 정보 파일·zip 을 한 번에(설계서 5-5·5-6·7-3).

실행(OCR 가상환경 안의 파이썬으로, 표준 사용자 토큰 아래에서):
  python -I -B -X utf8 build_ocr_addon.py all --out-dir <빌드 폴더> [--variant std|stub] [--no-remove] [--tag 이름] [--numpy-note 글]
  단계를 따로: freeze · assemble · remove · check · info · zip   (같은 --out-dir 를 주면 이어서 한다)
변형(variant): std  = 진짜 requests·urllib3·certifi·idna·charset_normalizer 를 묶는다(기본 동결 그대로)
               stub = 아무것도 안 하는 가짜 requests 한 모듈(ocr_addon\\stubs\\requests.py)로 대신하고 위 다섯 개를 묶음에서 뺀다(설계·지시서 2-5)
제거(remove): rapidocr 휠에 든 쓰지 않는 기본 모델 3개(31.7MB) · opencv 의 FFmpeg DLL(opencv_videoio_ffmpeg*.dll) · certifi 의 cacert.pem. --no-remove 면 건너뛴다(제거 전 크기를 재려고).
점검(check): 금지 파일 없음 · 묶음 안 모든 exe·DLL·pyd 의 가져오기 표(pefile)에서 네트워크 DLL(WS2_32·WinINet·WinHTTP·mswsock·iphlpapi·dnsapi …) 검사(예외: _internal 바로 아래의 파이썬 표준 _socket.pyd·select.pyd·python312.dll) · 크기 보고 · 동결본 --selftest.
점검이 하나라도 실패하면 단계가 all 이어도 거기서 멈춘다(info·zip 을 만들지 않고 종료 코드 1).
이 스크립트는 앱 저장소·시스템 파일을 건드리지 않고 --out-dir 아래에만 쓴다.
고지(info 단계, 운영자 확인 030 ②): 산출 폴더에 licenses/(묶음에 든 부품마다 설치된 패키지에서 읽은 라이선스 전문 — GEOS 의 LICENSE_GEOS 를 못 찾으면 빌드를 멈춘다)와 THIRD_PARTY_NOTICES.txt(제3자 부품 표·GEOS 안내·MPL-2.0 고지)를
만들고 OCR_INFO.json 에 geos 칸(GEOS 판·별도 파일 목록)을 적는다. 원본 소스 압축 파일은 넣지 않는다(새 내려받기 없음 — 같은 버전 소스를 공식 배포처에서 받으라고 안내한다).
"""
import argparse
import ast
import fnmatch
import hashlib
import importlib.metadata as im
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGEA = os.path.dirname(HERE)
PHOTOLAB = os.path.dirname(STAGEA)
ASSETS = os.path.join(STAGEA, "assets")
EXE_NAME = "ocr_worker"
BUNDLE_NAME = "ocr_addon"
LOCK = os.path.join(HERE, "models.lock.json")

NET_DLLS = ["ws2_32.dll", "wsock32.dll", "mswsock.dll", "wininet.dll", "winhttp.dll", "iphlpapi.dll", "dnsapi.dll", "urlmon.dll", "wldap32.dll",
            "httpapi.dll", "netapi32.dll", "rasapi32.dll", "mpr.dll", "webservices.dll", "wlanapi.dll", "fwpuclnt.dll", "winnsi.dll", "nsi.dll", "dhcpcsvc.dll"]
# 허용 예외 = 파이썬(CPython) 표준 구성요소 셋. _socket.pyd·select.pyd 는 지시서 2-5 가 정한 것이고, python312.dll(인터프리터 본체)은 a 단계 실측으로 더한다:
# 시스템에 설치된 원본 python312.dll 도 ws2_32.dll 을 가져온다(보고서 ⑥). 이 셋 밖에 하나라도 있으면 점검 실패.
PE_EXCEPTIONS = {"_socket.pyd", "select.pyd", "python312.dll"}
PE_EXCEPTION_DIR = "_internal"                   # 허용 예외는 이 폴더 바로 아래의 그 이름 파일뿐이다(a 단계 실측: _internal/_socket.pyd·select.pyd·python312.dll) — 같은 이름이 묶음의 다른 곳에 있으면 예외가 아니다(검증 S SP-11)
FORBIDDEN_NAMES = [r"opencv_videoio_ffmpeg.*\.dll", r".*\.pem$", r".*\.crt$", r".*\.key$"]
REMOVE_GLOBS = [("rapidocr 기본 모델(쓰지 않음)", "**/rapidocr/models/*.onnx"),
                ("opencv FFmpeg DLL(영상 입출력, 쓰지 않음)", "**/opencv_videoio_ffmpeg*.dll"),
                ("certifi cacert.pem(연결하지 않으므로 필요 없음)", "**/certifi/cacert.pem")]
MODEL_EXPECT = {"models/det/inference.onnx": (4826518, "a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d"),
                "models/rec/inference.onnx": (13418787, "92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08"),
                "data/ppocrv5_korean_dict.txt": (47451, "a88071c68c01707489baa79ebe0405b7beb5cca229f4fc94cc3ef992328802d7")}
EXCLUDED_ENGINE_MODULES = ["rapidocr.inference_engine.pytorch", "rapidocr.inference_engine.openvino", "rapidocr.inference_engine.paddle",
                           "rapidocr.inference_engine.mnn", "rapidocr.inference_engine.tensorrt", "rapidocr.inference_engine.onnxruntime_dml_unused"]
GENERIC_EXCLUDES = ["tkinter", "matplotlib", "pandas", "scipy", "IPython", "pytest", "torch", "tensorflow", "openvino", "paddle", "MNN", "tensorrt", "setuptools", "pkg_resources", "distutils", "pip"]

# 확인 030 ②(2026-11-22): GEOS(LGPL-2.1)·MPL-2.0 의무는 '라이선스 전문·고지문·소스 안내문을 추가 도구 폴더에 넣는' 방식으로 지킨다. 원본 소스 압축 파일은 넣지 않는다.
LICENSES_DIR = "licenses"                         # 산출 폴더 안의 라이선스 전문 폴더(부품 이름별 하위 폴더)
NOTICES_NAME = "THIRD_PARTY_NOTICES.txt"          # 제3자 부품 표·GEOS 안내·MPL-2.0 고지·소스 안내문
GEOS_LICENSE_NAME = "LICENSE_GEOS"                # shapely 휠에 든 GEOS(LGPL-2.1) 라이선스 전문 — 빌드 때 설치된 패키지에서 읽는다
GEOS_SOURCE_HOST = "libgeos.org"                  # GEOS 프로젝트 공식 사이트 — 주소는 host 글자만 쓴다(앞에 스킴을 붙이지 않는다). 근거: stage0b licenses 의 LICENSE_TABLE 6번 줄
LICENSE_NAME_RE = re.compile(r"(licen[sc]e|notice|copying|attribution|third.?party)", re.I)
NOT_LICENSE_SUFFIXES = (".py", ".pyc", ".pyo", ".pyd", ".pyi", ".dll", ".so", ".exe", ".json", ".c", ".cc", ".cpp", ".h", ".hpp")
GEOS_DLL_RE = re.compile(r"geos(_c)?[-_.0-9a-z]*\.dll", re.I)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_files(root):
    for d, _dirs, files in os.walk(root):
        for fn in files:
            yield os.path.join(d, fn)


def rel(root, p):
    return os.path.relpath(p, root).replace("\\", "/")


def dist_dir(out_dir):
    return os.path.join(out_dir, "dist", BUNDLE_NAME)


def log(msg):
    sys.stdout.write("[build %s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


def build_clock(fmt):
    """빌드 시각 글. 환경 변수 SOURCE_DATE_EPOCH 가 있으면 그 시각(UTC)을 써서 같은 입력이면 같은 정보 파일·zip 이 나오게 한다(재현 빌드)."""
    ep = os.environ.get("SOURCE_DATE_EPOCH")
    if ep and ep.isdigit():
        return time.strftime(fmt, time.gmtime(int(ep)))
    return time.strftime(fmt)


def normalize_base_library(path):
    """PyInstaller 의 base_library.zip 은 항목 내용·시각은 같은데 항목 순서가 실행마다 달라질 수 있다(해시 무작위). 이름 순으로 다시 묶어 순서를 고정한다(내용·시각·압축은 그대로)."""
    if not os.path.isfile(path):
        return
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in sorted(z.infolist(), key=lambda x: x.filename)]
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for i, data in items:
            zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = i.external_attr
            z.writestr(zi, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    os.replace(tmp, path)


# ───────────────────────────── freeze ─────────────────────────────
def gen_buildinfo(out_dir):
    gen = os.path.join(out_dir, "gen")
    os.makedirs(gen, exist_ok=True)
    versions = {}
    for d in im.distributions():
        n = (d.metadata["Name"] or "").lower().replace("_", "-")
        if n:
            versions[n] = d.version
    with open(os.path.join(gen, "buildinfo.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# -*- coding: utf-8 -*-\n# build_ocr_addon.py 가 만든 파일 — 묶음 안에서 패키지 판 이름을 알려 준다.\nVERSIONS = %r\n" % (versions,))
    return gen, versions


def freeze(out_dir, variant, extra_excludes=()):
    t0 = time.time()
    gen, versions = gen_buildinfo(out_dir)
    work = os.path.join(out_dir, "build")
    dist_root = os.path.join(out_dir, "dist")
    for d in (work, dist_root):
        shutil.rmtree(d, ignore_errors=True)
    cmd = [sys.executable, "-I", "-B", "-X", "utf8", "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--noupx",
           "--name", EXE_NAME, "--distpath", dist_root, "--workpath", work, "--specpath", os.path.join(out_dir, "spec"),
           "--paths", HERE, "--paths", gen,
           "--additional-hooks-dir", os.path.join(HERE, "hooks"),
           "--collect-data", "rapidocr",
           "--hidden-import", "rapidocr.main", "--hidden-import", "rapidocr.inference_engine.onnxruntime",
           "--hidden-import", "buildinfo"]
    excludes = list(GENERIC_EXCLUDES) + EXCLUDED_ENGINE_MODULES
    if variant == "stub":
        cmd += ["--paths", os.path.join(HERE, "stubs")]
        # 진짜 requests 계열과 ssl(OpenSSL 의 libcrypto-3.dll 이 ws2_32 를 가져온다)·asyncio(_overlapped.pyd)·multiprocessing(_multiprocessing.pyd)을 뺀다 — 작업자는 쓰지 않는다
        excludes += ["urllib3", "charset_normalizer", "idna", "certifi", "ssl", "_ssl", "_hashlib", "asyncio", "multiprocessing", "_overlapped", "_multiprocessing"]
    excludes += list(extra_excludes)
    for m in excludes:
        cmd += ["--exclude-module", m]
    cmd.append(os.path.join(HERE, "worker_main.py"))
    log("PyInstaller 시작 (variant=%s)" % variant)
    log(" ".join(cmd[3:]))
    r = subprocess.run(cmd, cwd=out_dir)
    if r.returncode != 0:
        log("★ PyInstaller 실패 (종료 코드 %d)" % r.returncode)
        return r.returncode
    src = os.path.join(dist_root, EXE_NAME)
    dst = dist_dir(out_dir)
    shutil.rmtree(dst, ignore_errors=True)
    # 방금 만든 폴더 이름 바꾸기는 윈도에서 보안 프로그램·색인기가 새 파일을 훑는 동안 '액세스 거부' 로 드물게 실패한다(한 번 겪음) → 잠깐씩 쉬며 다시 시도, 끝내 안 되면 복사 뒤 지운다
    for attempt in range(20):
        try:
            os.rename(src, dst)
            break
        except PermissionError:
            time.sleep(1.0)
    else:
        shutil.copytree(src, dst)
        shutil.rmtree(src, ignore_errors=True)
    normalize_base_library(os.path.join(dst, "_internal", "base_library.zip"))
    log("동결 끝 %.1f초 -> %s" % (time.time() - t0, dst))
    with open(os.path.join(out_dir, "freeze_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"variant": variant, "freeze_seconds": round(time.time() - t0, 1), "pyinstaller_cmd": cmd[3:]}, f, ensure_ascii=False, indent=1)
    return 0


# ───────────────────────────── assemble ─────────────────────────────
def assemble(out_dir):
    dst = dist_dir(out_dir)
    for relp, (size, sha) in MODEL_EXPECT.items():
        src = os.path.join(ASSETS, relp)
        if not os.path.isfile(src) or os.path.getsize(src) != size or sha256_file(src) != sha:
            log("★ 모델·사전 원본 확인 실패: %s" % relp)
            return 1
        os.makedirs(os.path.dirname(os.path.join(dst, relp)), exist_ok=True)
        shutil.copyfile(src, os.path.join(dst, relp))
    info_src = os.path.join(ASSETS, "data", "ppocrv5_korean_dict.info.json")
    if os.path.isfile(info_src):
        shutil.copyfile(info_src, os.path.join(dst, "data", "ppocrv5_korean_dict.info.json"))
    log("모델 2개·사전 얹음(크기·SHA-256 일치)")
    return 0


# ───────────────────────────── remove ─────────────────────────────
def remove_unused(out_dir):
    dst = dist_dir(out_dir)
    removed = []
    for label, pat in REMOVE_GLOBS:
        for p in sorted(walk_files(dst)):
            r = rel(dst, p)
            if fnmatch.fnmatch(r, pat) or fnmatch.fnmatch("x/" + r, pat):
                removed.append({"what": label, "path": r, "bytes": os.path.getsize(p)})
                os.remove(p)
    with open(os.path.join(out_dir, "removed.json"), "w", encoding="utf-8") as f:
        json.dump(removed, f, ensure_ascii=False, indent=1)
    log("제거 %d개, 합계 %d바이트" % (len(removed), sum(x["bytes"] for x in removed)))
    for x in removed:
        log("  - %s  %s  %d" % (x["what"], x["path"], x["bytes"]))
    return 0


# ───────────────────────────── check ─────────────────────────────
def size_report(dst):
    files = list(walk_files(dst))
    total = sum(os.path.getsize(p) for p in files)
    top10 = sorted(((os.path.getsize(p), rel(dst, p)) for p in files), reverse=True)[:10]
    groups = {}
    for p in files:
        r = rel(dst, p)
        parts = r.split("/")
        if parts[0] == "_internal" and len(parts) > 2:
            key = parts[1]
        elif parts[0] == "_internal":
            key = "(_internal 직속 파일)"
        else:
            key = "(" + parts[0] + ")" if len(parts) > 1 else "(루트 파일)"
        groups[key] = groups.get(key, 0) + os.path.getsize(p)
    return {"files": len(files), "bytes": total, "top10": [{"bytes": b, "path": r} for b, r in top10],
            "by_package": dict(sorted(groups.items(), key=lambda kv: -kv[1]))}


def pe_table(dst):
    import pefile
    rows, errors = [], []
    for p in sorted(walk_files(dst)):
        if not p.lower().endswith((".exe", ".dll", ".pyd")):
            continue
        try:
            pe = pefile.PE(p, fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"], pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
                                                   pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_BOUND_IMPORT"]])
            names, delay = set(), set()
            for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
                names.add(e.dll.decode("ascii", "replace").lower())
            for e in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []) or []:
                delay.add(e.dll.decode("ascii", "replace").lower())
            bound = set()
            for e in getattr(pe, "DIRECTORY_ENTRY_BOUND_IMPORT", []) or []:
                bound.add(e.name.decode("ascii", "replace").lower())
            pe.close()
            net = sorted((names | delay | bound) & set(NET_DLLS))
            rows.append({"path": rel(dst, p), "bytes": os.path.getsize(p), "n_imports": len(names), "n_delay": len(delay), "net_dlls": net,
                         "net_static": sorted(names & set(NET_DLLS)), "net_delay": sorted(delay & set(NET_DLLS)), "imports": sorted(names)})
        except Exception as e:
            errors.append({"path": rel(dst, p), "error": "%s: %s" % (type(e).__name__, str(e)[:100])})
    return rows, errors


def net_offenders(rows):
    """가져오기 표(pe_table 의 행들)에서 네트워크 DLL 을 가져오는 파일 중 허용 예외(PE_EXCEPTION_DIR 바로 아래의 PE_EXCEPTIONS 이름 파일) 밖인 것 -> 행 목록(순수 함수)."""
    out = []
    for row in rows:
        if not row.get("net_dlls"):
            continue
        folder, _slash, name = str(row["path"]).replace("\\", "/").rpartition("/")
        if folder == PE_EXCEPTION_DIR and name.lower() in PE_EXCEPTIONS:
            continue
        out.append(row)
    return out


def check(out_dir, run_selftest=True):
    dst = dist_dir(out_dir)
    res = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "problems": []}
    # 1) 금지 파일
    bad = []
    for p in walk_files(dst):
        b = os.path.basename(p).lower()
        if any(re.fullmatch(pat, b) for pat in FORBIDDEN_NAMES):
            bad.append(rel(dst, p))
        if fnmatch.fnmatch(rel(dst, p), "*/rapidocr/models/*.onnx"):
            bad.append(rel(dst, p))
    res["forbidden_files"] = bad
    if bad:
        res["problems"].append("금지 파일이 묶음에 있음: %s" % bad)
    # 2) 모델·사전
    mfail = []
    for relp, (size, sha) in MODEL_EXPECT.items():
        p = os.path.join(dst, relp)
        if not os.path.isfile(p) or os.path.getsize(p) != size or sha256_file(p) != sha:
            mfail.append(relp)
    res["model_dict_ok"] = not mfail
    if mfail:
        res["problems"].append("모델·사전 크기/해시 불일치: %s" % mfail)
    # 3) 가져오기 표
    rows, errors = pe_table(dst)
    with_net = [r for r in rows if r["net_dlls"]]
    offenders = net_offenders(with_net)
    res["pe"] = {"files_checked": len(rows), "parse_errors": errors, "with_net_dll": [{k: r[k] for k in ("path", "bytes", "net_static", "net_delay")} for r in with_net],
                 "exceptions_allowed": sorted(PE_EXCEPTIONS), "offenders": [r["path"] for r in offenders]}
    if offenders:
        res["problems"].append("가져오기 표에 네트워크 DLL 이 있는 파일(허용 예외 밖): %s" % [(r["path"], r["net_dlls"]) for r in offenders])
    if errors:
        res["problems"].append("가져오기 표를 읽지 못한 파일 %d개" % len(errors))
    with open(os.path.join(out_dir, "pe_imports_all.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=0)
    # 4) 크기
    res["size"] = size_report(dst)
    # 5) 동결본 자가 점검
    if run_selftest:
        exe = os.path.join(dst, EXE_NAME + ".exe")
        t0 = time.time()
        r = subprocess.run([exe, "--selftest"], capture_output=True, cwd=dst, timeout=300)
        res["selftest_seconds"] = round(time.time() - t0, 2)
        res["selftest_exit"] = r.returncode
        out = r.stdout.decode("utf-8", "replace").strip().splitlines()
        try:
            res["selftest"] = json.loads(out[-1]) if out else None
        except Exception:
            res["selftest"] = {"raw_tail": out[-3:]}
        if r.returncode != 0 or not (res["selftest"] or {}).get("ok"):
            res["problems"].append("동결본 --selftest 실패(종료 %s)" % r.returncode)
            res["selftest_stderr_tail"] = r.stderr.decode("utf-8", "replace")[-1500:]
    res["ok"] = not res["problems"]
    with open(os.path.join(out_dir, "check_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    log("점검 %s — 문제 %d건, 파일 %d개 %d바이트" % ("통과" if res["ok"] else "실패", len(res["problems"]), res["size"]["files"], res["size"]["bytes"]))
    for pr in res["problems"]:
        log("  ★ " + pr)
    return 0 if res["ok"] else 1


# ───────────────────────────── 라이선스 전문·고지문(확인 030 ②) ─────────────────────────────
class BuildError(Exception):
    """빌드를 멈추는 문제 — 조용히 건너뛰지 않고 이유를 알린다."""


def is_license_file(record_path):
    """분포 파일 목록(RECORD)의 경로 하나가 라이선스·고지문 닮은 글 파일인가(순수 함수 — 파일을 열지 않는다)."""
    parts = str(record_path).replace("\\", "/").split("/")
    base = parts[-1]
    if "__pycache__" in parts or not LICENSE_NAME_RE.search(base):
        return False
    return not base.lower().endswith(NOT_LICENSE_SUFFIXES)


def license_target(record_path):
    """분포 안 경로 -> licenses/<부품 이름>/ 아래 상대 경로(순수 함수): `*.dist-info/` 와 그 안의 `licenses/` 폴더 접두를 떼고 나머지 폴더 구조는 지킨다(같은 이름의 파일이 겹치지 않게)."""
    parts = str(record_path).replace("\\", "/").split("/")
    if parts and parts[0].endswith(".dist-info"):
        parts = parts[1:]
        if len(parts) > 1 and parts[0] == "licenses":
            parts = parts[1:]
    return "/".join(parts)


def geos_license_path(record_paths):
    """shapely 분포 파일 목록에서 GEOS 라이선스 전문(LICENSE_GEOS)의 경로 -> 없으면 None(순수 함수)."""
    for path in record_paths:
        text = str(path).replace("\\", "/")
        if text.split("/")[-1].lower() == GEOS_LICENSE_NAME.lower() and is_license_file(text):
            return text
    return None


def read_geos_version():
    """설치된 shapely 가 알려 주는 GEOS 판 글(예: 3.14.1) -> 읽지 못하면 None(지어내지 않는다)."""
    try:
        import shapely
        text = getattr(shapely, "geos_version_string", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        parts = getattr(shapely, "geos_version", None)
        if isinstance(parts, tuple) and parts and all(isinstance(n, int) for n in parts):
            return ".".join(str(n) for n in parts)
    except Exception:
        pass
    return None


def geos_dll_files(dst):
    """묶음 안의 별도 GEOS 파일(geos*.dll·geos_c*.dll) 경로들."""
    return sorted(rel(dst, p) for p in walk_files(dst) if GEOS_DLL_RE.fullmatch(os.path.basename(p)))


def collect_licenses(dst, packages, distribution=None):
    """묶음에 든 부품마다 설치된 분포에서 라이선스·고지문 파일을 `dst/licenses/<부품 이름>/` 로 복사한다 -> {부품 이름: [licenses/<이름>/ 아래 상대 경로, …]}.
    shapely 의 GEOS 라이선스 전문(LICENSE_GEOS)을 못 찾으면 BuildError — 조용히 건너뛰지 않는다. 쓰기는 dst 아래뿐이다."""
    lookup = distribution or im.distribution                 # 호출할 때 찾는다(시험이 바꿔 끼울 수 있게)
    root = os.path.join(dst, LICENSES_DIR)
    shutil.rmtree(root, ignore_errors=True)                  # 이전 실행의 찌꺼기가 산출 목록에 섞이지 않게(dst 아래만)
    collected = {}
    for package in sorted((p for p in packages if p.get("bundled_in_dist")), key=lambda item: item["name"]):
        name = package["name"]
        try:
            dist = lookup(name)
        except Exception:
            raise BuildError("묶음에 든 부품 %s 의 설치된 패키지를 찾지 못했다 — 라이선스 파일을 모을 수 없다" % name) from None
        entries = [(item, str(item).replace("\\", "/")) for item in (dist.files or ())]
        if name == "shapely" and geos_license_path([text for _item, text in entries]) is None:
            raise BuildError("shapely 안 GEOS 의 라이선스 전문(%s)을 설치된 패키지에서 찾지 못했다 — 조용히 건너뛰지 않고 빌드를 멈춘다" % GEOS_LICENSE_NAME)
        names = []
        for item, text in entries:
            if not is_license_file(text):
                continue
            target = license_target(text)
            if not target or target.startswith("/") or ":" in target or ".." in target.split("/"):
                raise BuildError("라이선스 파일 경로가 안전하지 않다: %s" % text)
            destination = os.path.join(root, name, *target.split("/"))
            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copyfile(str(dist.locate_file(item)), destination)
            except OSError as error:
                raise BuildError("라이선스 파일을 복사하지 못했다(%s): %s" % (text, type(error).__name__)) from None
            names.append(target)
        collected[name] = sorted(names)
    return collected


def render_notices(packages, geos, collected, removed=()):
    """THIRD_PARTY_NOTICES.txt 의 글(순수 함수 — 같은 입력이면 같은 글. 시각처럼 빌드마다 달라지는 값은 없다). 글에는 인터넷 주소의 스킴(앞머리)도 물결표도 쓰지 않는다."""
    bundled = sorted((p for p in packages if p.get("bundled_in_dist")), key=lambda item: item["name"])
    lines = ["글자 읽기 추가 도구 — 제3자 부품 고지 (THIRD_PARTY_NOTICES.txt)",
             "이 파일은 추가 도구를 만들 때 빌드가 자동으로 만든다. 법률 자문이 아니라 부품 파일에 적힌 표기를 옮긴 안내다. 운영자 확인 030 ② 에 따라 라이선스 전문(licenses 폴더)·이 고지문·소스 안내문을 이 폴더에 함께 둔다.",
             "",
             "[1] 이 묶음에 든 제3자 부품 (이름 | 버전 | 라이선스 표기 | 라이선스 전문 파일)"]
    for package in bundled:
        files = collected.get(package["name"]) or []
        where = "%s/%s/ (%d개 파일)" % (LICENSES_DIR, package["name"], len(files)) if files else "(휠에 라이선스 파일이 없다 — 표기만 적는다)"
        lines.append("- %s | %s | %s | %s" % (package["name"], package.get("version") or "?", package.get("license_metadata") or "?", where))
    lines += ["각 부품의 라이선스 전문은 이 폴더의 licenses 폴더에 부품 이름별로 들어 있다.",
              "",
              "[2] GEOS — LGPL-2.1 (소스 안내와 바꿔 끼우기)",
              "- 무엇: shapely 가 가져온 GEOS 라이브러리다. 별도 파일 geos*.dll 로 들어 있어 바꿔 끼울 수 있음 — 같은 이름의 호환되는 GEOS 판으로 바꿔 쓸 수 있다.",
              "- 별도 파일의 위치: " + ", ".join(geos["dll_files"]),
              "- 이 묶음의 GEOS 판: %s (OCR_INFO.json 의 geos 칸에도 같은 값이 적혀 있다)." % geos["version"],
              "- 라이선스 전문: " + geos["license_file"],
              "- 원본 소스: 이 묶음에는 원본 소스 압축 파일을 넣지 않았다. GEOS 프로젝트(공식 사이트 %s)가 공개 배포하는 같은 버전 소스를 받으세요(버전은 OCR_INFO.json 의 geos 칸)." % geos["source_host"],
              "",
              "[3] MPL-2.0 조건의 부품 — 고지"]
    mpl = [p for p in bundled if "MPL-2.0" in str(p.get("license_metadata"))]
    onnx = next((p for p in bundled if p["name"] == "onnxruntime"), None)
    for package in mpl:
        lines.append("- %s %s (%s)" % (package["name"], package.get("version") or "?", package.get("license_metadata")))
    if onnx is not None:
        lines.append("- onnxruntime %s 안에 든 Eigen (MPL-2.0 — onnxruntime 의 제3자 고지 파일 ThirdPartyNotices.txt 에 적혀 있다)" % (onnx.get("version") or "?"))
    if mpl or onnx is not None:
        lines.append("이 부품들은 이 묶음에서 고치지 않은 채 다시 배포한다. 해당 코드의 원본 소스는 각 프로젝트가 공개 배포하는 같은 버전 소스를 받으세요. MPL-2.0 전문과 고지는 licenses 폴더의 부품별 폴더(tqdm·onnxruntime 등)에 있다.")
    else:
        lines.append("- 이 묶음에는 MPL-2.0 조건의 부품이 없다.")
    if any("opencv_videoio_ffmpeg" in str(item.get("path", "")) for item in removed if isinstance(item, dict)):
        lines += ["", "[4] 이 묶음에서 뺀 것", "- opencv 휠의 FFmpeg DLL(opencv_videoio_ffmpeg*.dll, 파일에 LGPL-2.1 로 적혀 있음)은 쓰지 않아 이 묶음에서 제거했다."]
    lines += ["", "그 밖의 부품(MIT·BSD·Apache-2.0 등)의 고지 조건은 licenses 폴더의 라이선스 전문 파일로 지킨다."]
    return "\n".join(lines) + "\n"


def license_notes(geos):
    """OCR_INFO.json 의 license_notes 칸(순수 함수) — 방식이 정해졌다는 문구(확인 030 ②)."""
    return {"memo": "법률 자문이 아님. 휠 메타데이터 기준 표기이며, GEOS(LGPL-2.1)·MPL-2.0 부품의 의무는 확인 030 ② 에 따라 라이선스 전문(licenses 폴더)·고지문(%s)·소스 안내문을 이 폴더에 넣는 방식으로 지킨다(원본 소스 압축 파일은 넣지 않는다)." % NOTICES_NAME,
            "geos": "shapely 휠에 GEOS %s 동봉 — LGPL-2.1 — 확인 030 ② 에 따라 라이선스 전문·고지문·소스 안내문 동봉(별도 파일이라 바꿔 끼울 수 있음, 원본 소스는 같은 버전을 GEOS 프로젝트 공식 배포처 %s 에서 받음)" % (geos["version"], geos["source_host"]),
            "ffmpeg": "opencv 휠의 FFmpeg DLL 은 이 묶음에서 제거(재배포 의무 대상에서 뺌)",
            "mpl2": "certifi·tqdm MPL-2.0 — 고치지 않은 채 재배포, 확인 030 ② 에 따라 고지문(%s)과 라이선스 전문(licenses 폴더) 동봉, onnxruntime 안 Eigen(MPL-2.0)도 같은 고지(variant=stub 에서는 certifi 가 묶음에 없음)" % NOTICES_NAME}


def missing_outputs(paths):
    """산출 목록(OCR_INFO.json 의 files 경로들)에 꼭 있어야 하는데 빠진 것 -> 이름 목록(순수 함수): 고지문 · licenses/ 폴더(파일이 하나라도) · GEOS 라이선스 전문."""
    paths = [str(p).replace("\\", "/") for p in paths]
    missing = []
    if NOTICES_NAME not in paths:
        missing.append(NOTICES_NAME)
    if not any(p.startswith(LICENSES_DIR + "/") for p in paths):
        missing.append(LICENSES_DIR + "/")
    if not any(p.startswith(LICENSES_DIR + "/shapely/") and p.split("/")[-1] == GEOS_LICENSE_NAME for p in paths):
        missing.append("%s/shapely/%s" % (LICENSES_DIR, GEOS_LICENSE_NAME))
    return missing


def write_license_outputs(dst, packages, removed=(), distribution=None, geos_version=None):
    """licenses/ 폴더와 THIRD_PARTY_NOTICES.txt 를 dst 안에 만든다 -> GEOS 기록(dict — OCR_INFO.json 의 geos 칸). 하나라도 못 만들면 BuildError(조용히 건너뛰지 않는다)."""
    if not any(p.get("name") == "shapely" and p.get("bundled_in_dist") for p in packages):
        raise BuildError("shapely(GEOS)가 묶음에 든 것으로 확인되지 않는다 — 이 빌드 흐름의 전제와 다르다")
    collected = collect_licenses(dst, packages, distribution)
    license_files = [name for name in collected.get("shapely", ()) if name.split("/")[-1] == GEOS_LICENSE_NAME]
    if not license_files or not os.path.isfile(os.path.join(dst, LICENSES_DIR, "shapely", *license_files[0].split("/"))):
        raise BuildError("GEOS 라이선스 전문(%s)을 산출 폴더에 복사하지 못했다" % GEOS_LICENSE_NAME)
    version = (geos_version or read_geos_version)()
    version = version.strip() if isinstance(version, str) else None
    if not version:
        raise BuildError("설치된 shapely 에서 GEOS 판을 읽지 못했다 — 소스 안내문에 판을 적을 수 없어 빌드를 멈춘다")
    dlls = geos_dll_files(dst)
    if not dlls:
        raise BuildError("묶음에서 별도 파일 geos*.dll 을 찾지 못했다 — 바꿔 끼울 수 있다는 고지를 쓸 수 없어 빌드를 멈춘다")
    geos = {"name": "GEOS", "version": version, "license": "LGPL-2.1", "dll_files": dlls, "license_file": "%s/shapely/%s" % (LICENSES_DIR, license_files[0]), "replaceable": True,
            "source_host": GEOS_SOURCE_HOST, "source_included": False}
    with open(os.path.join(dst, NOTICES_NAME), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_notices(packages, geos, collected, removed))
    return geos


# ───────────────────────────── info / zip ─────────────────────────────
def pypi_license(name):
    try:
        md = im.metadata(name)
    except Exception:
        return None
    return md.get("License-Expression") or md.get("License") or "; ".join(c.split("::")[-1].strip() for c in (md.get_all("Classifier") or []) if c.startswith("License"))


def bundled_modules(out_dir):
    """묶음에 실제로 들어간 최상위 모듈 이름 집합: PYZ 보관소(PYZ-00.pyz)의 모듈 목록 + _internal 직속 이름(.pyd·폴더). PyInstaller 의 읽기 도구를 쓴다."""
    names = set()
    pyz = os.path.join(out_dir, "build", EXE_NAME, "PYZ-00.pyz")
    try:
        from PyInstaller.archive.readers import ZlibArchiveReader
        r = ZlibArchiveReader(pyz)
        for n in r.toc:
            names.add(str(n).split(".")[0])
    except Exception:
        pass
    inter = os.path.join(dist_dir(out_dir), "_internal")
    if os.path.isdir(inter):
        for n in os.listdir(inter):
            names.add(n.split(".")[0])
    return names


def make_info(out_dir, tag="", extra=None):
    dst = dist_dir(out_dir)
    table = json.load(open(os.path.join(PHOTOLAB, "stage2", "wheels_table.json"), encoding="utf-8"))
    pinned = {r["canon"]: r for r in table["files"] if r["file"].endswith(".whl")}
    mods = bundled_modules(out_dir)
    top_names = {"opencv-python-headless": "cv2", "pillow": "PIL", "pyyaml": "yaml", "protobuf": "google", "charset-normalizer": "charset_normalizer",
                 "rapidocr": "rapidocr", "onnxruntime": "onnxruntime", "numpy": "numpy", "shapely": "shapely", "pyclipper": "pyclipper", "omegaconf": "omegaconf",
                 "flatbuffers": "flatbuffers", "colorlog": "colorlog", "six": "six", "tqdm": "tqdm", "packaging": "packaging", "colorama": "colorama",
                 "requests": "requests", "urllib3": "urllib3", "certifi": "certifi", "idna": "idna"}
    # PyPI 업로드 날짜(2단계 verify_pypi.json + a 단계 verify_*.json)와 설치한 판의 휠 파일(휠 폴더에서 이름·판이 맞는 것)을 찾아 크기·해시를 적는다
    uploads = {}
    for jp in (os.path.join(PHOTOLAB, "stage2", "verify_pypi.json"), os.path.join(STAGEA, "results", "verify_numpy254.json"), os.path.join(STAGEA, "results", "verify_build_wheels.json")):
        if os.path.isfile(jp):
            for it in json.load(open(jp, encoding="utf-8")).get("items", []):
                if it.get("upload"):
                    uploads[it["file"]] = it["upload"]
    wheel_dirs = (os.path.join(STAGEA, "wheels_build"), os.path.join(PHOTOLAB, "wheels_rapid"))

    def find_wheel(name, ver):
        key = (name.replace("-", "_") + "-" + ver + "-").lower()
        for wd in wheel_dirs:
            if os.path.isdir(wd):
                for fn in os.listdir(wd):
                    if fn.lower().startswith(key) and fn.endswith(".whl"):
                        pth = os.path.join(wd, fn)
                        return fn, os.path.getsize(pth), sha256_file(pth)
        return None, None, None

    today = build_clock("%Y-%m-%d")
    packages = []
    for canon, rec in sorted(pinned.items()):
        try:
            ver = im.version(rec["name"])
        except Exception:
            ver = None
        top = top_names.get(canon, canon.replace("-", "_"))
        bundled = top in mods
        stubbed = bool(canon == "requests" and os.path.isfile(os.path.join(out_dir, "freeze_meta.json")) and json.load(open(os.path.join(out_dir, "freeze_meta.json"), encoding="utf-8")).get("variant") == "stub")
        if stubbed:
            bundled = False                                  # 묶인 것은 진짜 requests 가 아니라 가짜 껍데기(stubs\requests.py)다
        fn, size, sha = find_wheel(canon, ver) if ver else (None, None, None)
        up = uploads.get(fn or rec["file"])
        age = None
        if up:
            import datetime
            age = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(up[:10])).days
        packages.append({"name": canon, "version": ver, "stage2_pinned_version": rec["version"], "license_metadata": pypi_license(rec["name"]) or rec.get("license"),
                         "wheel_file": fn or rec["file"], "wheel_bytes": size if fn else rec["bytes"], "wheel_sha256": sha if fn else rec["sha256"],
                         "pypi_upload": up[:10] if up else None, "age_days_at_build": age, "bundled_in_dist": bool(bundled), "replaced_by_offline_stub": stubbed})
    tools = {}
    for n in ("pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "setuptools", "packaging"):
        try:
            tools[n] = im.version(n)
        except Exception:
            tools[n] = None
    chk = None
    cp = os.path.join(out_dir, "check_result.json")
    if os.path.isfile(cp):
        c = json.load(open(cp, encoding="utf-8"))
        chk = {"ok": c.get("ok"), "problems": c.get("problems"), "pe_files_checked": c["pe"]["files_checked"], "pe_files_with_net_dll": c["pe"]["with_net_dll"],
               "pe_exceptions_allowed": c["pe"]["exceptions_allowed"], "forbidden_files": c["forbidden_files"], "model_dict_ok": c["model_dict_ok"],
               "selftest_ok": (c.get("selftest") or {}).get("ok"), "selftest_exit": c.get("selftest_exit")}
    removed = json.load(open(os.path.join(out_dir, "removed.json"), encoding="utf-8")) if os.path.isfile(os.path.join(out_dir, "removed.json")) else []
    fm = json.load(open(os.path.join(out_dir, "freeze_meta.json"), encoding="utf-8")) if os.path.isfile(os.path.join(out_dir, "freeze_meta.json")) else {}
    geos = write_license_outputs(dst, packages, removed)                 # licenses/·THIRD_PARTY_NOTICES.txt 를 먼저 만든다(아래 파일 목록에 들어가도록) — GEOS 라이선스를 못 찾으면 BuildError
    info = {"schema": 1, "name": BUNDLE_NAME, "stage": "a-prototype", "tag": tag, "proto": 1, "built_local_time": build_clock("%Y-%m-%d %H:%M:%S"),
            "python": sys.version.split()[0], "variant": fm.get("variant"), "build_tools": tools, "packages": packages, "removed_from_bundle": removed,
            "models_dict": {k: {"bytes": v[0], "sha256": v[1]} for k, v in MODEL_EXPECT.items()}, "checks": chk,
            "license_notes": license_notes(geos)}
    info["geos"] = geos
    if extra:
        info.update(extra)
    files = []
    for p in sorted(walk_files(dst)):
        r = rel(dst, p)
        if r == "OCR_INFO.json":
            continue
        files.append({"path": r, "bytes": os.path.getsize(p), "sha256": sha256_file(p)})
    info["files"] = files
    info["file_count"] = len(files)
    info["total_bytes"] = sum(f["bytes"] for f in files)
    absent = missing_outputs([f["path"] for f in files])
    if absent:
        raise BuildError("산출 목록에 꼭 있어야 하는 것이 없다: %s" % ", ".join(absent))
    with open(os.path.join(dst, "OCR_INFO.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    log("OCR_INFO.json 만듦 — 파일 %d개 %d바이트, 패키지 %d개(묶임 %d)" % (len(files), info["total_bytes"], len(packages), sum(1 for p in packages if p["bundled_in_dist"])))
    return 0


def make_zip(out_dir, zip_path):
    dst = dist_dir(out_dir)
    entries = sorted(walk_files(dst), key=lambda p: rel(dst, p))
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in entries:
            zi = zipfile.ZipInfo(BUNDLE_NAME + "/" + rel(dst, p), date_time=(1980, 1, 1, 0, 0, 0))   # 결정적 zip: 시각·순서·압축 수준 고정
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(p, "rb") as f:
                z.writestr(zi, f.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    sha = sha256_file(zip_path)
    with open(zip_path + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write("%s *%s\n" % (sha, os.path.basename(zip_path)))
    log("zip %s  %d바이트  SHA-256 %s" % (zip_path, os.path.getsize(zip_path), sha))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=("all", "freeze", "assemble", "remove", "check", "info", "zip"))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--variant", choices=("std", "stub"), default="std")
    ap.add_argument("--no-remove", action="store_true")
    ap.add_argument("--no-selftest", action="store_true")
    ap.add_argument("--extra-exclude", default="", help="쉼표로 구분한 추가 --exclude-module(실험용)")
    ap.add_argument("--tag", default="")
    ap.add_argument("--zip", default=None, help="zip 경로(기본: <out-dir>\\ocr_addon_<tag>.zip)")
    a = ap.parse_args()
    out = os.path.abspath(a.out_dir)
    os.makedirs(out, exist_ok=True)
    st = a.stage
    if st in ("all", "freeze"):
        if freeze(out, a.variant, [x for x in a.extra_exclude.split(",") if x]):
            return 1
    if st in ("all", "assemble"):
        if assemble(out):
            return 1
    if st in ("all", "remove") and not a.no_remove:
        remove_unused(out)
    if st in ("all", "check"):
        rc = check(out, not a.no_selftest)
        if rc:                                                       # 점검이 실패하면 단계가 all 이어도 info·zip 으로 가지 않는다 — 실패한 묶음의 zip 을 만들지 않고 0 이 아닌 코드로 끝낸다(검증 S SP-1)
            return rc
    if st in ("all", "info"):
        try:
            if make_info(out, a.tag):
                return 1
        except BuildError as error:
            log("★ 빌드를 멈춘다: %s" % error)
            return 1
    if st in ("all", "zip"):
        make_zip(out, a.zip or os.path.join(out, "ocr_addon_%s.zip" % (a.tag or "proto")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
