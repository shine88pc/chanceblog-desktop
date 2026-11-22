# -*- coding: utf-8 -*-
"""build_ocr_addon.py - 글자 읽기 작업자(추가 도구) 빌드: 동결(PyInstaller onedir) -> 모델·사전 얹기 -> 쓰지 않는 것 제거 -> 묶음 점검(R1-R4) -> 정보 파일·zip 을 한 번에(설계서 5-5·5-6, 결정 D-527 에서 D-531).

실행(OCR 가상환경 안의 파이썬 3.12 로 — 잠금 파일(requirements-ocr.lock·requirements-build.txt)을 --require-hashes 로 설치한 환경):
  python ocr_addon/build_ocr_addon.py all --out-dir <빌드 폴더> --models-dir <fetch_models.py 가 받은 폴더> [--require-clean]
  단계를 따로: freeze · assemble · remove · notices · check · info · zip   (같은 --out-dir 를 주면 이어서 한다)
재료: 모델 2개는 --models-dir(안에 det·rec 폴더), 글자 사전은 ocr_addon/data/, 모두 models.lock.json 의 크기·SHA-256 과 대조한다. 가짜 requests(stubs/requests.py)로 requests 계열을 대신하고 뺀다.
제거(remove): rapidocr 휠에 든 쓰지 않는 기본 모델 3개(31.7MB) · opencv 의 FFmpeg DLL(opencv_videoio_ffmpeg*.dll) · certifi 의 cacert.pem.
고지(notices, 운영자 확인 030 ② — 점검 앞): 묶음 폴더에 licenses/(묶음에 든 부품마다 설치된 패키지에서 읽은 라이선스 전문 — GEOS 의 LICENSE_GEOS 를 못 찾으면 빌드를 멈춘다)와 THIRD_PARTY_NOTICES.txt(제3자 부품 표·GEOS 안내·MPL-2.0 고지)를 만들고
  GEOS 기록(geos.json)을 남긴다 — 점검(check)보다 앞에서 만들어야 R2(금지 이름)·키 모양 훑기가 이 파일들도 보고 정보 파일(OCR_INFO.json)의 파일 목록에 들어간다. 정보 파일에는 geos 칸(GEOS 판·별도 파일 목록)을 적는다.
  원본 소스 압축 파일은 넣지 않는다(새 내려받기 없음 — 같은 버전 소스를 공식 배포처에서 받으라고 안내한다).
점검(check, 규칙은 build_rules.py): R1 가져오기 표(pefile) · R2 묶음 파일·모델 해시 · R3 OpenSSL·진짜 requests 부재 · R4 동결본 --selftest · 묶음 글 파일의 키 모양 · DLL 출처 허용 뿌리 · 설치된 판 = 잠금 판.
  하나라도 걸리면 종료 코드 1 이고 정보 파일·zip 을 만들지 않는다(점검을 건너뛰는 옵션은 없다).
재현: 시각은 SOURCE_DATE_EPOCH(없으면 이 저장소 HEAD 의 커밋 시각)로 고정하고 PyInstaller 는 좁힌 PATH 로 부른다(본체 packaging/build_package.py 와 같은 함수 — 러너 PATH 의 자바·Git DLL 이 묶음에 새는 것을 막는다, D-468).
이 스크립트는 산출물을 --out-dir 아래에만 쓰고 네트워크를 쓰지 않는다(모델은 fetch_models.py 가 따로 받는다). 다만 곁다리로 --out-dir 밖에도 닿는다: git status 가 .git/index 를 고칠 수 있고, PyInstaller 는 --clean 으로 자기 캐시(기본 위치 %LOCALAPPDATA% 아래 pyinstaller 폴더)를 지우고 다시 쓰며, 파이썬이 ocr_addon·packaging 에 __pycache__ 를 쓸 수 있다(독립 검증 S 의 SN-13 — 러너에서는 무해하고 개발 PC 에서 돌리는 사람이 알 일).
"""
import argparse
import datetime
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
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import build_rules as rules  # noqa: E402

DATA_DIR = os.path.join(HERE, "data")
EXE_NAME = "ocr_worker"
BUNDLE_NAME = "ocr_addon"                                 # 정보 파일의 name(앱 service/ocr_addon.py 가 이 값을 요구한다)
BUNDLE_DIR = "ocr"                                        # 묶음 폴더·압축 파일 맨 위 폴더 이름 = 앱이 본체 옆에서 찾는 폴더 이름(FOLDER_NAME)
LOCK = os.path.join(HERE, "models.lock.json")
PINS = os.path.join(HERE, "requirements-ocr.lock")
BUILD_PINS = os.path.join(HERE, "requirements-build.txt")
PIN_META = os.path.join(HERE, "requirements-ocr.meta.json")
OUT_MARKER = ".chanceblog-ocr-out"
GEOS_RECORD = "geos.json"                                 # notices 단계가 남기고 info 단계가 읽는 GEOS 기록(out 폴더 안 — 묶음에는 들어가지 않는다)
OUT_SUBFOLDERS = ("build", "dist", "gen", "spec", "release", "selftest_tmp")
TEXT_SUFFIXES = (".py", ".pyi", ".json", ".txt", ".md", ".xml", ".cfg", ".ini", ".toml", ".yml", ".yaml", ".html", ".js", ".css", ".csv")
TEXT_SCAN_LIMIT = 5 * 1024 * 1024
REMOVE_GLOBS = [("rapidocr 기본 모델(쓰지 않음)", "**/rapidocr/models/*.onnx"),
                ("opencv FFmpeg DLL(영상 입출력, 쓰지 않음)", "**/opencv_videoio_ffmpeg*.dll"),
                ("certifi cacert.pem(연결하지 않으므로 필요 없음)", "**/certifi/cacert.pem")]
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
    return os.path.join(out_dir, "dist", BUNDLE_DIR)


def log(msg):
    sys.stdout.write("[build %s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


class BuildError(Exception):
    """빌드를 계속할 수 없는 이유(쉬운 한국어) — main 이 한 줄로 알리고 종료 코드 2 로 끝낸다."""


def read_json(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def load_lock():
    """models.lock.json -> (잠금 사전, {키: (바이트, SHA-256)}). 모양이 이상하면 BuildError."""
    lock = read_json(LOCK)
    problems = rules.lock_problems(lock)
    if problems:
        raise BuildError("models.lock.json 점검 실패: " + " / ".join(problems))
    return lock, rules.expected_files(lock)


def git_text(*args):
    done = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if done.returncode != 0:
        raise BuildError("git 이 실패했다 — 이 폴더가 git 저장소가 맞는지 확인해 주세요(git %s)" % args[0])
    return done.stdout


def source_state():
    """이 저장소 HEAD 의 커밋·시각과 ocr_addon 폴더가 깨끗한지. 시각은 SOURCE_DATE_EPOCH 가 있으면 그것(숫자 아니면 거절), 없으면 커밋 시각(재현 빌드의 시계 하나)."""
    commit = git_text("rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise BuildError("git 이 돌려준 커밋 해시의 모양이 이상하다")
    given = os.environ.get("SOURCE_DATE_EPOCH")
    if given is not None and not given.isdigit():
        raise BuildError("SOURCE_DATE_EPOCH 는 숫자(초)여야 한다")
    epoch = int(given) if given else int(git_text("show", "-s", "--format=%ct", "HEAD").strip())
    dirty = [line for line in git_text("status", "--porcelain", "--untracked-files=all", "--", "ocr_addon", "VERSION").splitlines() if line.strip()]
    return {"commit": commit, "epoch": epoch, "epoch_from": "SOURCE_DATE_EPOCH" if given else "git commit", "committed_utc": rules.utc_text(epoch), "clean": not dirty, "dirty_count": len(dirty)}


def read_version():
    with open(os.path.join(REPO, "VERSION"), "rb") as f:
        text = f.read().decode("utf-8").lstrip(chr(0xFEFF)).strip()
    rules.zip_name(text)                                       # 모양 확인(어긋나면 ValueError -> main 이 알린다)
    return text


def import_packaging():
    """본체 빌드(packaging/build_package.py)의 함수를 읽기 전용으로 가져다 쓴다 — 본체 코드는 고치지 않는다. 표준 라이브러리만 가져오는 모듈이다."""
    folder = os.path.join(REPO, "packaging")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import build_package as bp
    return bp


def prepare_out_dir(out):
    """출력 폴더가 비었거나 이 도구가 만든 폴더(표지 파일)일 때만 쓴다 — 아니면 아무것도 지우지 않고 거절. 이 도구가 만든 폴더면 이전 결과(하위 폴더·점검 결과)를 지운다."""
    out = str(import_packaging().safe_out_dir(out, REPO))      # 본체 빌드의 출력 폴더 점검(저장소·드라이브 맨 위·이상한 이름·긴 경로 거절)을 그대로 쓴다
    if os.path.isfile(out):
        raise BuildError("출력 경로가 폴더가 아니라 이미 있는 파일이다")
    if os.path.isdir(out) and os.listdir(out) and not os.path.isfile(os.path.join(out, OUT_MARKER)):
        raise BuildError("출력 폴더가 비어 있지 않은데 이 도구가 만든 폴더가 아니다(표지 파일 %s 가 없다) — 새 폴더나 빈 폴더를 골라 주세요" % OUT_MARKER)
    os.makedirs(out, exist_ok=True)
    for name in OUT_SUBFOLDERS:
        shutil.rmtree(os.path.join(out, name), ignore_errors=True)
    for name in ("freeze_meta.json", "removed.json", "check_result.json", GEOS_RECORD):          # 앞선 빌드의 건넴 파일이 새 빌드에 남지 않게(GEOS 기록 포함)
        if os.path.isfile(os.path.join(out, name)):
            os.remove(os.path.join(out, name))
    with open(os.path.join(out, OUT_MARKER), "wb") as f:
        f.write("이 폴더는 ocr_addon/build_ocr_addon.py 의 출력 폴더다. 다음 빌드 때 안의 하위 폴더가 지워진다.\n".encode("utf-8"))
    return out


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


def freeze(out_dir, epoch):
    t0 = time.time()
    bp = import_packaging()
    gen, versions = gen_buildinfo(out_dir)
    work = os.path.join(out_dir, "build")
    dist_root = os.path.join(out_dir, "dist")
    for d in (work, dist_root):
        shutil.rmtree(d, ignore_errors=True)
    cmd = [sys.executable, "-s", "-B", "-X", "utf8", "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--noupx",
           "--name", EXE_NAME, "--distpath", dist_root, "--workpath", work, "--specpath", os.path.join(out_dir, "spec"),
           "--paths", HERE, "--paths", gen, "--paths", os.path.join(HERE, "stubs"),
           "--collect-data", "rapidocr",
           "--hidden-import", "rapidocr.main", "--hidden-import", "rapidocr.inference_engine.onnxruntime",
           "--hidden-import", "buildinfo"]
    # 가짜 requests(stubs/requests.py)가 진짜 requests 계열을 대신한다. ssl(OpenSSL 의 libcrypto-3.dll 이 ws2_32 를 가져온다)·asyncio(_overlapped.pyd)·multiprocessing(_multiprocessing.pyd)도 뺀다 — 작업자는 쓰지 않는다
    excludes = list(GENERIC_EXCLUDES) + EXCLUDED_ENGINE_MODULES + ["urllib3", "charset_normalizer", "idna", "certifi", "ssl", "_ssl", "_hashlib", "asyncio", "multiprocessing", "_overlapped", "_multiprocessing"]
    for m in excludes:
        cmd += ["--exclude-module", m]
    cmd.append(os.path.join(HERE, "worker_main.py"))
    env = bp.pyinstaller_env(epoch)                            # 좁힌 PATH(가상환경·기본 파이썬·Windows 폴더)·PYTHONHASHSEED=0·SOURCE_DATE_EPOCH — 본체 빌드와 같은 함수
    folders = [folder for folder in env["PATH"].split(bp.PATH_SEPARATOR) if folder]
    log("PyInstaller 시작 — PATH 는 %d곳으로 좁혀서 부른다(정책 %s)" % (len(folders), bp.PATH_POLICY))
    log(" ".join(cmd[5:]))
    r = subprocess.run(cmd, cwd=out_dir, env=env, timeout=1800)
    if r.returncode != 0:
        raise BuildError("PyInstaller 가 실패했다(종료 코드 %d)" % r.returncode)
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
        json.dump({"freeze_seconds": round(time.time() - t0, 1), "path_policy": bp.PATH_POLICY, "path_folders": len(folders)}, f, ensure_ascii=False, indent=1)


# ───────────────────────────── assemble ─────────────────────────────
def assemble(out_dir, models_dir):
    """모델 2개(--models-dir 의 det·rec 폴더)와 글자 사전(ocr_addon/data)을 묶음에 얹는다 — 모두 잠금 파일의 크기·SHA-256 과 대조하고 다르면 멈춘다."""
    dst = dist_dir(out_dir)
    _lock, expected = load_lock()
    for key, (size, sha) in expected.items():
        folder = models_dir if key.startswith("models/") else DATA_DIR
        src = os.path.join(folder, *key.split("/")[1:])
        if not os.path.isfile(src) or os.path.getsize(src) != size or sha256_file(src) != sha:
            raise BuildError("모델·사전 원본이 잠금 파일의 크기·SHA-256 과 다르거나 없다: %s" % key)
        os.makedirs(os.path.dirname(os.path.join(dst, key)), exist_ok=True)
        shutil.copyfile(src, os.path.join(dst, key))
    info_src = os.path.join(DATA_DIR, "ppocrv5_korean_dict.info.json")
    if os.path.isfile(info_src):
        shutil.copyfile(info_src, os.path.join(dst, "data", "ppocrv5_korean_dict.info.json"))
    log("모델 2개·사전 얹음(크기·SHA-256 일치)")


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


def pe_rows(dst):
    """묶음 안 모든 exe·DLL·pyd 의 가져오기 표(정적·지연·묶음 가져오기)를 pefile 로 읽는다 — pefile 은 빌드 환경에만 있다. 반환 (줄 목록, 못 읽은 파일 목록)."""
    import pefile
    rows, errors = [], []
    wanted = [pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"], pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"], pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_BOUND_IMPORT"]]
    for p in sorted(walk_files(dst)):
        if not p.lower().endswith((".exe", ".dll", ".pyd")):
            continue
        try:
            pe = pefile.PE(p, fast_load=True)
            pe.parse_data_directories(directories=wanted)
            imports = sorted({e.dll.decode("ascii", "replace").lower() for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []})
            delay = sorted({e.dll.decode("ascii", "replace").lower() for e in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []) or []})
            bound = sorted({e.name.decode("ascii", "replace").lower() for e in getattr(pe, "DIRECTORY_ENTRY_BOUND_IMPORT", []) or []})
            pe.close()
            rows.append({"path": rel(dst, p), "bytes": os.path.getsize(p), "imports": imports, "delay": delay, "bound": bound})
        except Exception as e:
            errors.append("%s (%s)" % (rel(dst, p), type(e).__name__))
    return rows, errors


def snapshot(root):
    """폴더 안 파일 목록과 크기·수정 시각 — 자가 점검이 묶음 안에 쓰지 않았는지 전후를 견준다."""
    return {rel(root, p): (os.path.getsize(p), os.stat(p).st_mtime_ns) for p in walk_files(root)}


def run_selftest(out_dir, dst):
    """동결본 --selftest 를 돌린다 — 임시 폴더를 비어 있는 새 폴더로 돌려 두고, 끝난 뒤 묶음 폴더가 그대로이고 임시 폴더가 비어 있는지도 본다(파일을 쓰지 않는다는 약속).
    반환 (종료 코드, 마지막 줄 JSON 또는 None, 추가 문제 글들, 걸린 초, 표준 오류 끝)."""
    exe = os.path.join(dst, EXE_NAME + ".exe")
    tmp = os.path.join(out_dir, "selftest_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    before = snapshot(dst)
    env = dict(os.environ, TEMP=tmp, TMP=tmp, PYTHONDONTWRITEBYTECODE="1")
    t0 = time.time()
    r = subprocess.run([exe, "--selftest"], capture_output=True, cwd=dst, timeout=300, env=env)
    seconds = round(time.time() - t0, 2)
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        report = json.loads(out[-1]) if out else None
    except ValueError:
        report = None
    problems, after = [], snapshot(dst)
    if after != before:
        changed = sorted(set(before) ^ set(after)) or sorted(k for k in after if after[k] != before.get(k))
        problems.append("R4 --selftest 가 묶음 폴더 안의 파일을 바꿨다(약속: 파일을 쓰지 않는다): %s" % changed[:5])
    leftovers = sorted(os.listdir(tmp))
    if leftovers:
        problems.append("R4 --selftest 가 임시 폴더에 파일을 남겼다(약속: 파일을 쓰지 않는다): %d개" % len(leftovers))
    return r.returncode, report, problems, seconds, r.stderr.decode("utf-8", "replace")[-1500:]


def check(out_dir):
    """묶음 점검 — 하나라도 문제면 (False, 문제 목록). 규칙 판정은 build_rules.py(순수 함수), 여기서는 실제 묶음을 읽어 넘긴다."""
    dst = dist_dir(out_dir)
    bp = import_packaging()
    _lock, expected = load_lock()
    res = {"problems": []}
    problems = res["problems"]
    sizes = {rel(dst, p): os.path.getsize(p) for p in walk_files(dst)}
    problems += rules.bundle_file_problems(sizes, expected, lambda key: sha256_file(os.path.join(dst, *key.split("/"))))      # R2
    problems += ["R2 라이선스 고지 산출물이 없다: " + name for name in missing_outputs(sorted(sizes))]                           # 확인 030 ②: 고지문·licenses/ 도 점검을 거친다(없으면 notices 단계가 안 돈 것)
    problems += ["묶음에 있으면 안 되는 파일(%s): %s" % (bp.pc.forbidden_name(path), path) for path in sorted(sizes) if bp.pc.forbidden_name(path)]       # 본체의 비밀·사용자 데이터 파일 이름 목록
    problems += rules.key_shape_problems((path, read_lossy(os.path.join(dst, *path.split("/")))) for path in sorted(sizes)
                                         if (path.lower().endswith(TEXT_SUFFIXES) or path.startswith(LICENSES_DIR + "/")) and sizes[path] <= TEXT_SCAN_LIMIT)      # licenses/ 아래는 LICENSE·COPYING 처럼 확장자가 없어도 훑는다(확인 030 ②)
    rows, errors = pe_rows(dst)                                                                                                    # R1
    problems += rules.pe_problems(rows, errors)
    with open(os.path.join(out_dir, "pe_imports_all.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=0)
    problems += bp.check_binary_origins(os.path.join(out_dir, "build", EXE_NAME, "COLLECT-00.toc"))                              # DLL 출처: 가상환경·기본 파이썬·Windows 폴더뿐
    code, report, more, seconds, stderr_tail = run_selftest(out_dir, dst)                                                          # R4
    problems += rules.selftest_problems(report, code) + more
    if isinstance(report, dict):                                                                                                   # 러너 로그에서 첫 관측 값을 바로 읽게
        log("자가 점검 %.1f초 — 엔진 %s · 모델 올리기 %s초 · 점검 그림 읽기 %s밀리초" % (seconds, report.get("engine"), report.get("load_s"), report.get("read_ms")))
    problems += rules.module_problems(bundled_modules(out_dir), (report or {}).get("imports"), (report or {}).get("imports_optional"))                                    # R3
    pins = rules.parse_lock(read_text(PINS))
    problems += rules.installed_problems(pins, {pin["name"]: installed_version(pin["name"]) for pin in pins})
    problems += rules.pin_age_problems(pins, read_json(PIN_META))
    res.update({"files": len(sizes), "pe_files_checked": len(rows), "selftest_seconds": seconds, "selftest_exit": code, "selftest": report, "size": size_report(dst)})
    if problems and stderr_tail.strip():
        res["selftest_stderr_tail"] = stderr_tail
    res["ok"] = not problems
    with open(os.path.join(out_dir, "check_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    log("점검 %s — 문제 %d건, 파일 %d개 %d바이트, 가져오기 표 %d개 파일" % ("통과" if res["ok"] else "실패", len(problems), res["size"]["files"], res["size"]["bytes"], len(rows)))
    for pr in problems:
        log("  ★ " + pr)
    return res["ok"], res


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def read_lossy(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "replace")


def installed_version(name):
    try:
        return im.version(name)
    except im.PackageNotFoundError:
        return None


# ───────────────────────────── 라이선스 전문·고지문(확인 030 ②) ─────────────────────────────
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


def package_records(out_dir, state):
    """잠금 파일의 패키지 21개 기록(이름·설치된 판·라이선스 표기·휠·업로드일·나이·묶임 여부) — 고지문(notices 단계)과 정보 파일(info 단계)이 **같은 기록**을 쓴다(묶임 판정이 두 곳에서 갈라지지 않게)."""
    pins = rules.parse_lock(read_text(PINS))
    meta = read_json(PIN_META)
    mods = {n.split(".")[0] for n in bundled_modules(out_dir)}
    top_names = {"opencv-python-headless": "cv2", "pillow": "PIL", "pyyaml": "yaml", "protobuf": "google", "charset-normalizer": "charset_normalizer"}
    today = datetime.date.fromisoformat(state["committed_utc"][:10])
    packages = []
    for pin in pins:
        name, entry = pin["name"], meta["packages"][pin["name"]]
        top = top_names.get(name, name.replace("-", "_"))
        stubbed = name == "requests"                       # 묶인 것은 진짜 requests 가 아니라 가짜 껍데기(stubs/requests.py)다
        packages.append({"name": name, "version": installed_version(name), "license_metadata": pypi_license(name), "wheel_file": entry["wheel_file"], "wheel_bytes": entry["wheel_bytes"],
                         "wheel_sha256": pin["hashes"][0], "pypi_upload": entry["uploaded"], "age_days_at_build": (today - datetime.date.fromisoformat(entry["uploaded"])).days,
                         "bundled_in_dist": top in mods and not stubbed, "replaced_by_offline_stub": stubbed})
    return packages


def write_notices(out_dir, state):
    """notices 단계 — licenses/·THIRD_PARTY_NOTICES.txt 를 묶음 폴더에 만들고 GEOS 기록을 geos.json 에 남긴다. **점검(check)보다 앞이다**: R2(금지 이름)·키 모양 훑기가 이 파일들도 보고 정보 파일의 파일 목록에 들어간다.
    GEOS 라이선스 전문·판·별도 GEOS 파일을 못 찾는 등 못 만들면 BuildError — 조용히 건너뛰지 않는다."""
    removed_path = os.path.join(out_dir, "removed.json")
    removed = read_json(removed_path) if os.path.isfile(removed_path) else []
    geos = write_license_outputs(dist_dir(out_dir), package_records(out_dir, state), removed)
    with open(os.path.join(out_dir, GEOS_RECORD), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(geos, handle, ensure_ascii=False, indent=1)
    log("라이선스 전문·고지문 만듦 — GEOS %s · 별도 파일 %d개 · 고지문 %s" % (geos["version"], len(geos["dll_files"]), NOTICES_NAME))
    return geos


def read_geos_record(out_dir):
    """notices 단계가 남긴 GEOS 기록 — 없으면 정보 파일을 만들지 않는다(먼저 notices 단계를 거쳐야 한다)."""
    path = os.path.join(out_dir, GEOS_RECORD)
    if not os.path.isfile(path):
        raise BuildError("GEOS 기록(%s)이 없다 — 먼저 notices 단계(라이선스 전문·고지문 만들기)를 해야 정보 파일을 만든다" % GEOS_RECORD)
    return read_json(path)


# ───────────────────────────── info / zip ─────────────────────────────
def pypi_license(name):
    try:
        md = im.metadata(name)
    except Exception:
        return None
    return md.get("License-Expression") or md.get("License") or "; ".join(c.split("::")[-1].strip() for c in (md.get_all("Classifier") or []) if c.startswith("License"))


def bundled_modules(out_dir):
    """묶음에 실제로 들어간 최상위 모듈·파일 이름 집합: PYZ 보관소(PYZ-00.pyz)의 모듈 목록 + _internal 직속 이름(.pyd·폴더) + 묶음 맨 위 이름. PyInstaller 의 읽기 도구를 쓴다 — 못 읽으면 멈춘다(R3 이 눈감지 않게)."""
    names = set()
    pyz = os.path.join(out_dir, "build", EXE_NAME, "PYZ-00.pyz")
    try:
        from PyInstaller.archive.readers import ZlibArchiveReader
        for n in ZlibArchiveReader(pyz).toc:
            names.add(str(n).split(".")[0])
    except Exception as e:
        raise BuildError("PyInstaller 의 모듈 보관소(PYZ-00.pyz)를 읽지 못했다(%s) — 묶음 안 부품 목록을 알 수 없다" % type(e).__name__)
    for folder in (os.path.join(dist_dir(out_dir), "_internal"), dist_dir(out_dir)):
        if os.path.isdir(folder):
            names.update(n for n in os.listdir(folder))
    return names


def worker_proto():
    """작업자와 같은 약속 번호 — 같은 폴더의 protocol.py(표준 라이브러리만)를 경로로 읽는다(sys.path 에 기대지 않고, 흔한 이름 protocol 을 모듈 목록에 남기지 않는다)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ocr_addon_protocol", os.path.join(HERE, "protocol.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PROTO


def make_info(out_dir, state, version):
    dst = dist_dir(out_dir)
    _lock, expected = load_lock()
    packages = package_records(out_dir, state)
    geos = read_geos_record(out_dir)                       # notices 단계가 남긴 기록 — 고지 파일은 점검 앞에서 이미 만들어져 아래 파일 목록에 들어간다
    tools = {}
    for line in read_text(BUILD_PINS).splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==", line.strip())
        if match:
            tools[rules.canon(match.group(1))] = installed_version(match.group(1))
    check_path = os.path.join(out_dir, "check_result.json")
    c = read_json(check_path)
    chk = {"ok": c["ok"], "rules": ["R1", "R2", "R3", "R4"], "problems": c["problems"], "pe_files_checked": c["pe_files_checked"], "pe_exceptions_allowed": list(rules.PE_EXCEPTIONS),
           "selftest_ok": (c.get("selftest") or {}).get("ok"), "selftest_exit": c.get("selftest_exit")}
    removed = read_json(os.path.join(out_dir, "removed.json")) if os.path.isfile(os.path.join(out_dir, "removed.json")) else []
    lock_hashes = {os.path.basename(p): hashlib.sha256(read_text(p).replace("\r\n", "\n").encode("utf-8")).hexdigest() for p in (PINS, BUILD_PINS, PIN_META, LOCK)}
    info = {"schema": 1, "name": BUNDLE_NAME, "proto": worker_proto(), "channel": "personal-pc-preview", "notice": "개인 PC 제한 시험용, 미서명 추가 도구 — 공개 배포용이 아닙니다",
            "version": version, "source": {"commit": state["commit"], "committed_utc": state["committed_utc"], "clean": state["clean"], "time_from": state["epoch_from"]},
            "python": sys.version.split()[0], "variant": "inner", "build_tools": tools, "lock_sha256": lock_hashes, "packages": packages, "removed_from_bundle": removed,
            "models_dict": {k: {"bytes": v[0], "sha256": v[1]} for k, v in expected.items()}, "checks": chk,
            "license_notes": license_notes(geos), "geos": geos}
    files = []
    for p in sorted(walk_files(dst)):
        r = rel(dst, p)
        if r != "OCR_INFO.json":
            files.append({"path": r, "bytes": os.path.getsize(p), "sha256": sha256_file(p)})
    info["files"], info["file_count"], info["total_bytes"] = files, len(files), sum(f["bytes"] for f in files)
    absent = missing_outputs([f["path"] for f in files])
    if absent:
        raise BuildError("산출 목록에 꼭 있어야 하는 것이 없다: %s" % ", ".join(absent))
    with open(os.path.join(dst, "OCR_INFO.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    log("OCR_INFO.json 만듦 — 파일 %d개 %d바이트, 패키지 %d개(묶임 %d)" % (len(files), info["total_bytes"], len(packages), sum(1 for p in packages if p["bundled_in_dist"])))
    return info


def make_zip(out_dir, version, info):
    """결정적 zip(시각·순서·압축 수준 고정, 맨 위 폴더 ocr) + 옆에 SHA256SUMS·PACKAGE_INFO.json(= 정보 파일 + 압축 파일 이름·해시·크기) — 이 셋이 올리는 산출물의 전부다."""
    dst = dist_dir(out_dir)
    release = os.path.join(out_dir, "release")
    os.makedirs(release, exist_ok=True)
    zip_path = os.path.join(release, rules.zip_name(version))
    entries = sorted(walk_files(dst), key=lambda p: rel(dst, p))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in entries:
            zi = zipfile.ZipInfo(BUNDLE_DIR + "/" + rel(dst, p), date_time=(1980, 1, 1, 0, 0, 0))   # 결정적 zip: 시각·순서·압축 수준 고정
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(p, "rb") as f:
                z.writestr(zi, f.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(zip_path) as z:                                                            # 다시 열어 항목 이름·해시가 묶음 폴더와 같은지 확인
        if z.testzip() is not None:
            raise BuildError("만든 압축 파일이 깨졌다")
        got = {i.filename: hashlib.sha256(z.read(i)).hexdigest() for i in z.infolist()}
    want = {BUNDLE_DIR + "/" + rel(dst, p): sha256_file(p) for p in entries}
    if got != want:
        raise BuildError("압축 파일의 항목이 묶음 폴더와 다르다")
    sha = sha256_file(zip_path)
    outer = dict(info, variant="outer", package={"name": os.path.basename(zip_path), "sha256": sha, "bytes": os.path.getsize(zip_path)})
    with open(os.path.join(release, "PACKAGE_INFO.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(outer, ensure_ascii=False, indent=2) + "\n")
    with open(os.path.join(release, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
        f.write(rules.render_sums([(os.path.basename(zip_path), sha)]))
    log("zip %s  %d바이트  SHA-256 %s" % (os.path.basename(zip_path), os.path.getsize(zip_path), sha))


def passed_check(out_dir):
    """info·zip 을 따로 돌릴 때도 통과한 점검 결과가 있어야 한다 — 점검을 거치지 않은 묶음으로는 산출물을 만들지 않는다."""
    path = os.path.join(out_dir, "check_result.json")
    if not os.path.isfile(path) or read_json(path).get("ok") is not True:
        raise BuildError("통과한 점검 결과(check_result.json)가 없다 — 먼저 check 를 통과해야 정보 파일·zip 을 만든다")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=("all", "freeze", "assemble", "remove", "notices", "check", "info", "zip"))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--models-dir", default=None, help="fetch_models.py 가 받은 모델 폴더(안에 det·rec 폴더) — assemble 이 필요로 한다")
    ap.add_argument("--require-clean", action="store_true", help="ocr_addon 폴더·VERSION 에 커밋되지 않은 변경이 있으면 거절한다(빌드 흐름이 쓴다)")
    a = ap.parse_args(argv)
    st = a.stage
    started = time.time()
    try:
        state = source_state()
        if a.require_clean and not state["clean"]:
            raise BuildError("ocr_addon 폴더에 커밋되지 않은 변경이 %d개 있다 — 모두 커밋한 뒤 다시 빌드해 주세요(커밋 해시가 묶음 내용을 대표해야 한다)" % state["dirty_count"])
        version = read_version()
        out = prepare_out_dir(a.out_dir) if st in ("all", "freeze") else os.path.abspath(a.out_dir)
        if st in ("all", "assemble") and not a.models_dir:
            raise BuildError("--models-dir(fetch_models.py 가 받은 모델 폴더)가 필요하다")
        log("버전 %s · 커밋 %s · 시각 %s(%s) · 작업 폴더 %s" % (version, state["commit"][:12], state["committed_utc"], state["epoch_from"], "깨끗함" if state["clean"] else "변경 있음"))
        if st in ("all", "freeze"):
            freeze(out, state["epoch"])
        if st in ("all", "assemble"):
            assemble(out, os.path.abspath(a.models_dir))
        if st in ("all", "remove"):
            remove_unused(out)
        if st in ("all", "notices"):
            write_notices(out, state)
        if st in ("all", "check"):
            ok, _res = check(out)
            if not ok:
                return 1
        if st in ("info", "zip"):
            passed_check(out)
        info = make_info(out, state, version) if st in ("all", "info") else None
        if st in ("all", "zip"):
            make_zip(out, version, info or read_json(os.path.join(dist_dir(out), "OCR_INFO.json")))
        log("끝 — %s 단계, 걸린 시간 %.0f초" % (st, time.time() - started))
    except (BuildError, ValueError) as error:
        sys.stderr.write("빌드를 멈췄다: %s\n" % error)
        return 2
    except Exception as error:
        if type(error).__name__ == "BuildRefused":             # 본체 packaging 의 출력 폴더 점검이 거절한 경우
            sys.stderr.write("빌드를 멈췄다: %s\n" % error)
            return 2
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
