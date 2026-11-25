# -*- coding: utf-8 -*-
"""run_spike.py - 설치 도구 시험(spike)의 단계 실행기(결정 D-702). 수동 워크플로 installer-spike.yml 이 한 번에 한 단계씩 부른다.

  install-tools  fetch_tools.py 가 받아 크기·SHA-256 을 맞춘 vpk 패키지를 로컬 원본만으로 설치(dotnet tool, 도구 폴더 하나)하고, Velopack 파이썬 휠은 pip 의 해시 검사로 받아 같은 값으로 다시 대조한 뒤
                 별도 가상환경에만 깐다(실제 묶음을 만드는 환경에 SDK 가 섞여 들어가지 않게). 러너에 있는 Inno Setup 의 판·파일 해시·서명자를 읽는다.
  build-bundles  실제 묶음(packaging/build_package.py)과 작은 앱 묶음 둘(SDK 없는 것·있는 것)을 --onedir --windowed 로 만들고 작은 앱은 판 0.0.1·0.0.2·0.0.3 으로 복사한다.
  pack           갈래 A·B 는 vpk pack, 갈래 C 는 ISCC 로 설치 파일을 만든다(작은 앱 셋과 실제 묶음, A 는 패키지 ID 시험용 하나 더).
  measure        M01에서 M22 를 이 순서로 잰다(measure.py 의 흐름 — 방화벽에 프로그램별 바깥 접속 차단 규칙을 넣은 채 M14 를 반복한다). 항목마다 오류를 가둬 기록한다.
  report         측정 기록에서 관문 G1에서 G8 을 판정하고 보고서(INSTALLER_SPIKE_REPORT.md·.json)와 작업 요약의 결과 블록을 만든다.
상태는 작업 폴더의 state.json·results.json 으로 단계 사이에 넘긴다. 설치 도구가 하나 실패해도 그 갈래만 '없음' 으로 기록하고 나머지는 계속한다(도구 내려받기의 크기·해시 불일치는 앞 단계에서 이미 즉시 실패한다).
러너(일회용 윈도 가상 머신)에서만 도는 도구다 — 앱 본체(src/)와 상관없고 표준 라이브러리만 쓴다. 비밀·토큰을 쓰지 않고 새 접속은 install-tools 의 pip 두 번과 dotnet 복원(로컬 원본만)뿐이다.
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGING = HERE.parent
REPO = PACKAGING.parent
for _folder in (str(HERE), str(PACKAGING)):
    if _folder not in sys.path:
        sys.path.insert(0, _folder)
import fetch_tools  # noqa: E402
import measure  # noqa: E402
from measure import ARMS, ARM_NAMES, VERSIONS, Context, Scrubber, dir_size, file_count, mb, record, sha256_file, tail  # noqa: E402

COMMANDS = ("install-tools", "build-bundles", "pack", "measure", "report")
LOCK_PATH = HERE / "tools.lock.json"
ISS_PATH = HERE / "ChanceBlogSpike.iss"
PACK_ID = {"A": "ChanceBlogSpikeA", "B": "ChanceBlogSpikeB"}
REAL_PACK_ID = "ChanceBlogDesktopApp"
ID_TEST_PACK_ID = "ChanceBlogDesktop"
INNO_DIR = {"tiny": "ChanceBlogSpikeC", "real": "ChanceBlogDesktopSpikeC"}
INNO_APP_ID = {"tiny": "ChanceBlogSpikeInnoV1", "real": "ChanceBlogSpikeInnoReal"}
ISCC_CANDIDATES = ("C:/Program Files (x86)/Inno Setup 6/ISCC.exe", "C:/Program Files/Inno Setup 6/ISCC.exe")
JOB_LIMIT_SECONDS = 52 * 60
HELP_LIMIT = 5000
GATES = (("G1", "관리자 권한 0·표준 사용자"), ("G2", "무음 설치·제거·데이터 유지"), ("G3", "훅 5초·창 0·종료 0"), ("G4", "업데이트·반쯤 바뀜 0"), ("G5", "바깥 접속 막아도 됨"), ("G6", "Defender 위협 0"),
         ("G7", "설치 파일 80MB·만들기 5분"), ("G8", "설치본 selftest 열두 항목"))
TITLES = {"M01": "도구 준비", "M02": "묶음 만들기", "M03": "설치 파일 만들기", "M04": "관리자 요구", "M05": "무음 설치", "M06": "설치 결과", "M07": "훅", "M08": "업데이트", "M09": "실행 중 업데이트", "M10": "되돌리기",
          "M11": "깨진 새 판", "M12": "제거", "M13": "ID 충돌 대조", "M14": "접속 차단", "M15": "네이티브 부품", "M16": "Defender", "M17": "한국어", "M18": "표준 사용자", "M19": "긴·한글 경로", "M20": "크기·시간",
          "M21": "이름 바꾼 Setup", "M22": "휴대용 공존"}
WORD = {"pass": "통과", "fail": "실패", "info": "기록", "skip": "건너뜀", "unavailable": "시도 불가", "error": "오류", "unknown": "미정", "n/a": "해당 없음"}
RESULT_HEADER = "=== INSTALLER_SPIKE_RESULT v1 ==="
RESULT_FOOTER = "=== END ==="


# ---- 명령 만들기(순수) --------------------------------------------------------------------------------------------------------------------------

def vpk_pack_args(vpk, *, pack_id, version, pack_dir, main_exe, title, out_dir, skip_check, delta_none, channel="stable"):
    """vpk pack 명령 — 휴대용 zip 은 만들지 않고(--noPortable), 차이 업데이트는 끈다(--delta None, 값 이름은 vpk pack --help 로 확인한다), SDK 없는 앱은 --skipVeloAppCheck."""
    args = [str(vpk), "pack", "--packId", pack_id, "--packVersion", version, "--packDir", str(pack_dir), "--mainExe", main_exe, "--packTitle", title, "--channel", channel, "--noPortable", "--outputDir", str(out_dir)]
    if delta_none:
        args += ["--delta", "None"]
    if skip_check:
        args.append("--skipVeloAppCheck")
    return args


def iscc_args(iscc, script, *, version, source_dir, app_exe, app_dir_name, out_dir, out_base, app_id):
    """ISCC 컴파일 명령 — 스크립트가 받는 값은 모두 /D 정의다(ChanceBlogSpike.iss 머리 주석)."""
    return [str(iscc), "/Q", "/O" + str(out_dir), "/F" + out_base, "/DAppVersion=" + version, "/DSourceDir=" + str(source_dir), "/DAppExe=" + app_exe, "/DAppDirName=" + app_dir_name,
            "/DAppIdText=" + app_id, str(script)]


def nuget_config_text(folder):
    """로컬 폴더 하나만 원본으로 쓰는 NuGet 설정(그 밖의 원본은 모두 비운다) — dotnet 이 검증한 vpk 패키지 파일만 설치하게 한다."""
    return ('<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <packageSources>\n    <clear />\n    <add key="spike-local" value="%s" />\n  </packageSources>\n</configuration>\n' % folder)


def dotnet_tool_args(tool_path, version, config):
    return ["dotnet", "tool", "install", "vpk", "--tool-path", str(tool_path), "--version", version, "--configfile", str(config)]


def pip_download_args(python, requirements, folder):
    return [str(python), "-m", "pip", "download", "--no-deps", "--only-binary=:all:", "--require-hashes", "--disable-pip-version-check", "--no-input", "-r", str(requirements), "-d", str(folder)]


def pip_install_local_args(python, requirements, folder):
    return [str(python), "-m", "pip", "install", "--no-index", "--find-links", str(folder), "--require-hashes", "--only-binary=:all:", "--disable-pip-version-check", "-r", str(requirements)]


def requirements_line(tool):
    """휠 한 줄 잠금 — 이름==버전 과 SHA-256 해시(pip 의 --require-hashes 가 읽는다)."""
    return "%s==%s --hash=sha256:%s\n" % (tool["project"], tool["version"], tool["sha256"])


def build_requirement_lines(text):
    """packaging/requirements-package.txt 에서 묶음을 만드는 도구([build])의 정확한 버전 줄만(PySide6 같은 실행 부품은 작은 앱에 필요 없다)."""
    mm = measure.packaging_module("make_manifest")
    return ["%s==%s\n" % (item["name"], item["version"]) for item in mm.parse_requirements(text) if item["role"] == "build"]


def core_version(text):
    found = re.match(r"\d+\.\d+\.\d+", text or "")
    return found.group(0) if found else text


def pyinstaller_args(python, *, name, entry, dist, work, spec, extra=()):
    return [str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--noupx", "--name", name, "--distpath", str(dist), "--workpath", str(work), "--specpath", str(spec),
            "--paths", str(HERE), *extra, str(entry)]


def payload_files(version):
    """판마다 내용이 다른 파일들 — 업데이트가 반쯤 바뀐 상태를 파일 지문으로 알아보게 한다(VERSION 하나만으로는 약하다)."""
    files = {"VERSION": version + "\n"}
    for number in range(1, 9):
        files["payload/p%d.txt" % number] = "version %s file %d\n" % (version, number)
    return files


# ---- 공통 --------------------------------------------------------------------------------------------------------------------------------

def load_lock():
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    problems = fetch_tools.lock_problems(lock)
    if problems:
        raise ValueError("잠금 파일 점검 실패: " + " / ".join(problems))
    return {tool["key"]: tool for tool in lock["tools"]}


def time_left(ctx):
    deadline = ctx.state.get("job_deadline")
    return (deadline - ctx.host.wall()) if deadline else 10 ** 6


def capped(ctx, seconds):
    """단계 하나의 시간 제한을 작업 전체 한도에 맞춰 줄인다(남은 시간을 넘지 않는다)."""
    return int(max(60, min(seconds, time_left(ctx) - 90)))


def version_text(text):
    found = re.search(r"\d+\.\d+\.\d+(?:\.\d+)?", text or "")
    return found.group(0) if found else ""


# ---- install-tools ------------------------------------------------------------------------------------------------------------------------

def install_vpk(ctx, tool, tools_dir):
    nupkg = tools_dir / tool["file"]
    reason = fetch_tools.check_file(nupkg, tool)
    if reason:
        return {"status": "failed", "reason": "vpk 패키지 파일 대조 실패: " + reason, "nupkg_ok": False}
    config = ctx.work / "nuget-spike.config"
    config.write_text(nuget_config_text(tools_dir), encoding="utf-8")
    target = ctx.work / "vpk"
    done = ctx.host.run(dotnet_tool_args(target, tool["version"], config), timeout=capped(ctx, 900))
    exe = target / "vpk.exe"
    if not done.ok or not exe.is_file():
        return {"status": "failed", "reason": "dotnet tool install 실패 rc %s(로컬 원본만 허용): %s" % (done.rc, tail(done.text(), 300)), "nupkg_ok": True}
    shown = ctx.host.run([str(exe), "--version"], timeout=60)
    found = version_text(shown.text())
    return {"status": "ok", "path": str(exe), "version": found, "version_ok": found == tool["version"], "version_text": tail(shown.text(), 120), "nupkg_ok": True, "install_seconds": done.seconds}


def install_sdk(ctx, tool, tools_dir, build_text):
    wheels = tools_dir / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    requirements = tools_dir / "velopack.requirements.txt"
    requirements.write_text(requirements_line(tool), encoding="utf-8")
    python = sys.executable
    downloaded = ctx.host.run(pip_download_args(python, requirements, wheels), timeout=capped(ctx, 600))
    wheel = wheels / tool["file"]
    if not downloaded.ok:
        return {"status": "failed", "reason": "pip download 실패 rc %s: %s" % (downloaded.rc, tail(downloaded.text(), 300)), "wheel_ok": False}
    reason = fetch_tools.check_file(wheel, tool)
    if reason:
        return {"status": "failed", "reason": "휠 파일 대조 실패: " + reason, "wheel_ok": False}
    venv = ctx.work / "venv-sdk"
    if not ctx.host.run([python, "-m", "venv", str(venv)], timeout=capped(ctx, 300)).ok:
        return {"status": "failed", "reason": "별도 가상환경을 만들지 못했다", "wheel_ok": True, "wheel": str(wheel)}
    venv_python = venv / "Scripts" / "python.exe"
    installed = ctx.host.run(pip_install_local_args(venv_python, requirements, wheels), timeout=capped(ctx, 300))
    if not installed.ok:
        return {"status": "failed", "reason": "휠 설치 실패 rc %s: %s" % (installed.rc, tail(installed.text(), 300)), "wheel_ok": True, "wheel": str(wheel)}
    build_file = tools_dir / "pyinstaller.requirements.txt"
    build_file.write_text("".join(build_requirement_lines(build_text)), encoding="utf-8")
    built = ctx.host.run([str(venv_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(build_file)], timeout=capped(ctx, 900))
    checked = ctx.host.run([str(venv_python), "-c", "import velopack, sys; print(velopack.__file__)"], timeout=60)
    ok = built.ok and checked.ok
    return {"status": "ok" if ok else "failed", "reason": "" if ok else "빌드 도구 설치나 import 실패: %s" % tail(built.text() + checked.text(), 300), "wheel_ok": True, "wheel": str(wheel), "python": str(venv_python)}


def find_iscc(ctx):
    found = ctx.host.which("ISCC.exe")
    if not found:
        for candidate in ISCC_CANDIDATES:
            if ctx.host.is_file(candidate):
                found = candidate
                break
    if not found:
        return {"status": "unavailable", "reason": "ISCC.exe 를 찾지 못했다(러너 이미지에 Inno Setup 이 없다)"}
    env = {"SPIKE_P": str(found)}
    shown = ctx.host.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "(Get-Item -LiteralPath $env:SPIKE_P).VersionInfo.FileVersion"], timeout=60, env=env)
    signer = ctx.host.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "(Get-AuthenticodeSignature -LiteralPath $env:SPIKE_P).SignerCertificate.Subject"], timeout=60, env=env)
    numbers = measure.version_numbers(shown.out)
    common = re.search(r"CN=([^,]+)", signer.out or "")
    return {"status": "ok", "path": str(found), "version": ".".join(str(item) for item in numbers) if numbers else "", "version_ok": measure.inno_version_ok(numbers), "sha256": sha256_file(found),
            "signer": common.group(1).strip() if common else "", "korean_isl": (Path(found).parent / "Languages" / "Korean.isl").is_file()}


def cmd_install_tools(ctx):
    began = ctx.host.now()
    ctx.state["job_deadline"] = ctx.host.wall() + JOB_LIMIT_SECONDS
    lock = load_lock()
    tools_dir = ctx.work / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tools = ctx.state["tools"]
    shown = ctx.host.run(["dotnet", "--version"], timeout=60)
    tools["dotnet"] = {"version": version_text(shown.text())}
    tools["python"] = {"version": "%d.%d.%d" % sys.version_info[:3]}
    tools["vpk"] = install_vpk(ctx, lock["vpk-nupkg"], tools_dir)
    build_text = (PACKAGING / "requirements-package.txt").read_text(encoding="utf-8")
    tools["sdk"] = install_sdk(ctx, lock["velopack-wheel"], tools_dir, build_text)
    tools["iscc"] = find_iscc(ctx)
    if tools["vpk"].get("status") == "ok":
        for key, args in (("vpk_help", ["--help"]), ("vpk_pack_help", ["pack", "--help"])):
            ctx.state["help"][key] = tail(ctx.host.run([tools["vpk"]["path"], *args], timeout=60).text(), HELP_LIMIT)
    good = [name for name in ("vpk", "sdk", "iscc") if tools[name].get("status") == "ok"]
    ctx.note_step("install-tools", "ok" if len(good) == 3 else "partial", round(ctx.host.now() - began, 1), tools_ok=good)
    for name in ("vpk", "sdk", "iscc"):
        print("[spike] %s: %s %s" % (name, tools[name].get("status"), tail(tools[name].get("reason", ""), 160)))


# ---- build-bundles ------------------------------------------------------------------------------------------------------------------------

def build_real(ctx):
    out = ctx.work / "real"
    done = ctx.host.run([sys.executable, str(PACKAGING / "build_package.py"), "--out-dir", str(out), "--skip-scan"], timeout=capped(ctx, 1500), env={"PYTHONUTF8": "1"}, cwd=REPO)
    zips = sorted((out / "release").glob("ChanceBlogDesktop-*-win64.zip")) if (out / "release").is_dir() else []
    folders = sorted(path for path in (out / "bundle").glob("ChanceBlogDesktop-*") if path.is_dir()) if (out / "bundle").is_dir() else []
    if not done.ok or not zips or not folders:
        return {"dir": None, "reason": "build_package.py 실패 rc %s: %s" % (done.rc, tail(done.text(), 400))}
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    return {"dir": str(folders[0]), "zip": str(zips[0]), "version": version, "seconds": done.seconds, "bytes": dir_size(folders[0]), "files": file_count(folders[0]), "zip_bytes": zips[0].stat().st_size}


def build_tiny(ctx, *, name, python, entry, extra=()):
    out = ctx.work / "tiny" / name
    dist = out / "dist"
    done = ctx.host.run(pyinstaller_args(python, name=name, entry=HERE / entry, dist=dist, work=out / "build", spec=out / "spec", extra=extra), timeout=capped(ctx, 900), env={"PYTHONUTF8": "1"})
    base = dist / name
    if not done.ok or not (base / (name + ".exe")).is_file():
        return {"reason": "PyInstaller 실패 rc %s: %s" % (done.rc, tail(done.text(), 300))}
    result = {"base": str(base), "seconds": done.seconds, "bytes": dir_size(base), "files": file_count(base)}
    for version in VERSIONS:
        folder = out / "versions" / version
        shutil.copytree(base, folder)
        for relative, text in payload_files(version).items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if version == "0.0.3":
            (folder / "BROKEN").write_text("시작하자마자 종료 코드 3 으로 끝나는 깨진 새 판 흉내\n", encoding="utf-8")
        result[version] = str(folder)
    return result


def cmd_build_bundles(ctx):
    began = ctx.host.now()
    bundles = ctx.state["bundles"]
    bundles["real"] = build_real(ctx)
    print("[spike] 실제 묶음:", "ok" if bundles["real"].get("dir") else bundles["real"].get("reason", "실패"))
    bundles["plain"] = build_tiny(ctx, name="SpikeApp", python=sys.executable, entry="spike_app.py")
    print("[spike] 작은 앱(SDK 없음):", "ok" if bundles["plain"].get("0.0.1") else bundles["plain"].get("reason", "실패"))
    sdk = ctx.state["tools"].get("sdk", {})
    if sdk.get("status") == "ok":
        bundles["sdk"] = build_tiny(ctx, name="SpikeAppSdk", python=sdk["python"], entry="spike_app_sdk.py", extra=("--collect-all", "velopack"))
    else:
        bundles["sdk"] = {"reason": "SDK 가상환경이 없다(install-tools 실패)"}
    print("[spike] 작은 앱(SDK 있음):", "ok" if bundles["sdk"].get("0.0.1") else bundles["sdk"].get("reason", "실패"))
    good = [key for key in ("real", "plain", "sdk") if bundles[key].get("dir") or bundles[key].get("0.0.1")]
    ctx.note_step("build-bundles", "ok" if len(good) == 3 else "partial", round(ctx.host.now() - began, 1), bundles_ok=good)


# ---- pack ------------------------------------------------------------------------------------------------------------------------------

def pack_outputs(out_dir):
    setups = sorted(Path(out_dir).glob("*Setup*.exe")) if Path(out_dir).is_dir() else []
    fulls = sorted(Path(out_dir).glob("*-full.nupkg")) if Path(out_dir).is_dir() else []
    return setups, fulls


def vpk_pack(ctx, flags, arm, *, vpk, pack_id, version, pack_dir, main_exe, title, out_dir):
    """vpk pack 을 돌린다. 모르는 값(--delta 의 끔 값, SDK 가 있는 앱의 --skipVeloAppCheck 필요 여부)은 처음 한 번 후보를 차례로 써 보고 되는 쪽을 기억한다 → (결과, 쓴 옵션, 설치 파일 목록, 전체 패키지 목록)."""
    skip_options = [True] if arm != "A" else ([flags["skip_A"]] if flags["skip_A"] is not None else [False, True])
    delta_options = [flags["delta"]] if flags["delta"] is not None else [True, False]
    last = None
    for skip in skip_options:
        for delta in delta_options:
            shutil.rmtree(out_dir, ignore_errors=True)
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            result = ctx.host.run(vpk_pack_args(vpk, pack_id=pack_id, version=version, pack_dir=pack_dir, main_exe=main_exe, title=title, out_dir=out_dir, skip_check=skip, delta_none=delta),
                                  timeout=capped(ctx, 900))
            setups, fulls = pack_outputs(out_dir)
            last = (result, {"skip_check": skip, "delta_none": delta}, setups, fulls)
            if result.ok and setups and fulls:
                if arm == "A":
                    flags["skip_A"] = skip
                flags["delta"] = delta
                return last
    return last


def entry_of(result, used, setups, fulls, out_dir):
    return {"setup": str(setups[0]), "full": str(fulls[0]), "feed": str(out_dir), "bytes": setups[0].stat().st_size, "package_bytes": fulls[0].stat().st_size, "seconds": result.seconds, "name": setups[0].name, "flags": used}


def pack_velopack_set(ctx, flags, arm, vpk, bundle_key, main_exe):
    bundles = ctx.state["bundles"].get(bundle_key, {})
    found = {}
    for version in VERSIONS:
        if not bundles.get(version):
            return found, "작은 앱 묶음 %s 가 없다" % version
        out_dir = ctx.work / "out" / arm / version
        outcome = vpk_pack(ctx, flags, arm, vpk=vpk, pack_id=PACK_ID[arm], version=version, pack_dir=bundles[version], main_exe=main_exe, title="ChanceBlog Spike " + arm, out_dir=out_dir)
        result, used, setups, fulls = outcome
        if not (result and result.ok and setups and fulls):
            return found, "vpk pack 실패 rc %s: %s" % (result.rc if result else "?", tail(result.text() if result else "", 300))
        found[version] = entry_of(result, used, setups, fulls, out_dir)
    return found, ""


def pack_inno(ctx, iscc, *, version, source_dir, app_exe, kind, out_dir, out_base):
    out_dir.mkdir(parents=True, exist_ok=True)
    result = ctx.host.run(iscc_args(iscc, ISS_PATH, version=version, source_dir=source_dir, app_exe=app_exe, app_dir_name=INNO_DIR[kind], out_dir=out_dir, out_base=out_base, app_id=INNO_APP_ID[kind]),
                          timeout=capped(ctx, 900))
    setup = out_dir / (out_base + ".exe")
    if not result.ok or not setup.is_file():
        return None, "ISCC 실패 rc %s: %s" % (result.rc, tail(result.text(), 300))
    return {"setup": str(setup), "bytes": setup.stat().st_size, "seconds": result.seconds, "name": setup.name}, ""


def cmd_pack(ctx):
    began = ctx.host.now()
    tools, bundles = ctx.state["tools"], ctx.state["bundles"]
    installers = ctx.state["installers"] = {"A": {}, "B": {}, "C": {}}
    problems = {}
    flags = {"delta": None, "skip_A": None}
    vpk = tools.get("vpk", {})
    if vpk.get("status") == "ok":
        found, why = pack_velopack_set(ctx, flags, "B", vpk["path"], "plain", "SpikeApp.exe")
        installers["B"]["tiny"] = found
        problems["B"] = why
        found, why = pack_velopack_set(ctx, flags, "A", vpk["path"], "sdk", "SpikeAppSdk.exe")
        installers["A"]["tiny"] = found
        problems["A"] = why
        real = bundles.get("real", {})
        if real.get("dir"):
            for attempt in dict.fromkeys((real["version"], core_version(real["version"]))):
                out_dir = ctx.work / "out" / "B-real"
                outcome = vpk_pack(ctx, flags, "B", vpk=vpk["path"], pack_id=REAL_PACK_ID, version=attempt, pack_dir=real["dir"], main_exe="ChanceBlogDesktop.exe", title="ChanceBlog Desktop", out_dir=out_dir)
                result, used, setups, fulls = outcome
                if result and result.ok and setups and fulls:
                    installers["B"]["real"] = dict(entry_of(result, used, setups, fulls, out_dir), pack_version=attempt)
                    break
            else:
                problems["B-real"] = "실제 묶음 vpk pack 실패: " + tail(result.text() if result else "", 300)
        plain = bundles.get("plain", {})
        if plain.get("0.0.1"):
            out_dir = ctx.work / "out" / "A-idtest"
            result, used, setups, fulls = vpk_pack(ctx, flags, "B", vpk=vpk["path"], pack_id=ID_TEST_PACK_ID, version="0.0.1", pack_dir=plain["0.0.1"], main_exe="SpikeApp.exe", title="ChanceBlog Desktop", out_dir=out_dir)
            if result and result.ok and setups and fulls:
                installers["A"]["idtest"] = entry_of(result, used, setups, fulls, out_dir)
            else:
                problems["A-idtest"] = "ID 시험용 vpk pack 실패"
    else:
        problems["A"] = problems["B"] = "vpk 가 없다: " + tail(vpk.get("reason", ""), 200)
    iscc = tools.get("iscc", {})
    if iscc.get("status") == "ok" and iscc.get("version_ok") is not False:
        tiny = {}
        plain = bundles.get("plain", {})
        for version in VERSIONS:
            if not plain.get(version):
                problems["C"] = "작은 앱 묶음 %s 가 없다" % version
                break
            entry, why = pack_inno(ctx, iscc["path"], version=version, source_dir=plain[version], app_exe="SpikeApp.exe", kind="tiny", out_dir=ctx.work / "out" / "C" / version, out_base="ChanceBlogSpike-%s-Setup" % version)
            if not entry:
                problems["C"] = why
                break
            entry["feed"] = None
            tiny[version] = entry
        installers["C"]["tiny"] = tiny
        real = bundles.get("real", {})
        if real.get("dir"):
            entry, why = pack_inno(ctx, iscc["path"], version=real["version"], source_dir=real["dir"], app_exe="ChanceBlogDesktop.exe", kind="real", out_dir=ctx.work / "out" / "C-real", out_base="ChanceBlogDesktop-%s-Setup" % real["version"])
            if entry:
                installers["C"]["real"] = entry
            else:
                problems["C-real"] = why
    else:
        problems["C"] = "Inno Setup 을 쓸 수 없다: " + tail(iscc.get("reason", "판이 6.7 이 아니다(%s)" % iscc.get("version", "?")), 200)
    ctx.state["pack_problems"] = {key: value for key, value in problems.items() if value}
    good = [arm for arm in ARMS if installers[arm].get("tiny") and len(installers[arm]["tiny"]) == 3]
    ctx.note_step("pack", "ok" if len(good) == 3 and not ctx.state["pack_problems"] else "partial", round(ctx.host.now() - began, 1), arms_ok=good, flags=flags)
    for key, value in ctx.state["pack_problems"].items():
        print("[spike] pack 문제 %s: %s" % (key, tail(value, 200)))


# ---- measure ------------------------------------------------------------------------------------------------------------------------------

def cmd_measure(ctx):
    ctx.budget = min(measure.BUDGET_SECONDS, max(300, time_left(ctx) - 240))
    measure.run_measurements(ctx)
    print("[spike] 측정 기록 %d건" % len(ctx.results))


# ---- 판정·보고서 -----------------------------------------------------------------------------------------------------------------------------

def pick(results, mid, arm=None, target=None):
    return [item for item in results if item["id"] == mid and (arm is None or item["arm"] == arm) and (target is None or item["values"].get("target") == target)]


def rollup(items):
    """기록들을 하나로: 하나라도 실패면 fail, 통과가 있고 오류가 없으면 pass, 그 밖은 unknown."""
    statuses = [item["status"] for item in items]
    if "fail" in statuses:
        return "fail"
    if "pass" in statuses and "error" not in statuses:
        return "pass"
    return "unknown"


def both(*parts):
    if "fail" in parts:
        return "fail"
    return "pass" if all(part == "pass" for part in parts) else "unknown"


def judge(results):
    """관문 G1에서 G8 — 갈래마다 {G: {status, why}}. 값이 모자라면 미정(unknown)이고 실패로 세지 않는다. 갈래 A 의 G7·G8 은 B 와 같은 실제 묶음으로 본다(추정)."""
    gates = {}
    for arm in ARMS:
        proxy = "B" if arm == "A" else arm
        row = {}
        m04, m18 = rollup(pick(results, "M04", arm)), rollup(pick(results, "M18", arm))
        status = "fail" if "fail" in (m04, m18) else ("pass" if m04 == "pass" and m18 in ("pass", "unknown") else "unknown")
        row["G1"] = {"status": status, "why": "매니페스트 %s·표준 사용자 %s" % (WORD[m04], WORD[m18])}
        row["G2"] = {"status": both(rollup(pick(results, "M05", arm)), rollup(pick(results, "M12", arm))), "why": "무음 설치 %s·제거 %s" % (WORD[rollup(pick(results, "M05", arm))], WORD[rollup(pick(results, "M12", arm))])}
        row["G3"] = {"status": "n/a", "why": "훅이 없는 갈래"} if arm == "C" else {"status": rollup(pick(results, "M07", arm)), "why": "작은 앱 네 훅"}
        row["G4"] = {"status": both(rollup(pick(results, "M08", arm)), rollup(pick(results, "M09", arm))), "why": "업데이트 %s·실행 중 %s" % (WORD[rollup(pick(results, "M08", arm))], WORD[rollup(pick(results, "M09", arm))])}
        m14 = pick(results, "M14", arm)
        row["G5"] = {"status": rollup(m14), "why": "접속 차단 반복" + ("" if any(item["status"] in ("pass", "fail") for item in m14) else "(규칙 효과 미확인이거나 못 함)")}
        row["G6"] = {"status": rollup(pick(results, "M16", arm)) if pick(results, "M16", arm) else "unknown", "why": "읽기 전용 검사"}
        row["G7"] = {"status": rollup(pick(results, "M03", proxy, "real")), "why": "실제 묶음 설치 파일·만들기 시간" + (" (B 값으로 본다, 추정)" if arm == "A" else "")}
        row["G8"] = {"status": both(rollup(pick(results, "M06", proxy, "real")), rollup(pick(results, "M22"))), "why": "설치본·휴대용 selftest" + (" (B 값으로 본다, 추정)" if arm == "A" else "")}
        gates[arm] = row
    return gates


def short(item, limit=70):
    text = str(item["values"].get("brief", "") or item.get("note", ""))
    return text if len(text) <= limit else text[:limit - 1] + "…"


def cell(items):
    if not items:
        return "-"
    return " / ".join("%s %s" % (WORD[item["status"]], short(item)) for item in items)


def result_block(ctx, results, gates, scrub):
    state, environ = ctx.state, ctx.host.environ
    tools = state.get("tools", {})
    steps = state.get("steps", {})
    lines = [RESULT_HEADER,
             "러너: %s %s · 파이썬 %s · dotnet %s · vpk %s · Inno %s · 커밋 %s" % (environ.get("ImageOS", "?"), environ.get("ImageVersion", "?"), tools.get("python", {}).get("version", "?"), tools.get("dotnet", {}).get("version", "?"),
                                                                              tools.get("vpk", {}).get("version", "없음"), tools.get("iscc", {}).get("version", "없음"), environ.get("GITHUB_SHA", "?")[:7]),
             "단계: " + " | ".join("%s %s %s초" % (name, steps.get(name, {}).get("status", "안 돎"), steps.get(name, {}).get("seconds", "-")) for name in COMMANDS[:4])]
    problems = state.get("pack_problems", {})
    if problems:
        lines.append("만들기 문제: " + "; ".join("%s=%s" % (key, tail(str(value), 60)) for key, value in sorted(problems.items())))
    lines.append("--- 측정(갈래 A %s · B %s · C %s)" % (ARM_NAMES["A"], ARM_NAMES["B"], ARM_NAMES["C"]))
    for mid in sorted(TITLES):
        per_arm = {arm: pick(results, mid, arm) for arm in ARMS}
        common = pick(results, mid, "-")
        parts = ["%s %s" % (arm, cell(items)) for arm, items in per_arm.items() if items]
        if common:
            parts.append(cell(common))
        lines.append("%s %s | %s" % (mid, TITLES[mid], " | ".join(parts) if parts else "기록 없음"))
    lines.append("--- 관문(하나라도 실패하면 그 갈래는 탈락, 미정은 실패가 아니다)")
    for gate, title in GATES:
        lines.append("%s %s | %s" % (gate, title, " | ".join("%s %s" % (arm, WORD[gates[arm][gate]["status"]]) for arm in ARMS)))
    counts = {arm: sum(1 for gate, _t in GATES if gates[arm][gate]["status"] == "pass") for arm in ARMS}
    fails = {arm: [gate for gate, _t in GATES if gates[arm][gate]["status"] == "fail"] for arm in ARMS}
    lines.append("요약: 통과한 관문 A %d·B %d·C %d / 실패 관문 A %s·B %s·C %s" % (counts["A"], counts["B"], counts["C"], ",".join(fails["A"]) or "없음", ",".join(fails["B"]) or "없음", ",".join(fails["C"]) or "없음"))
    lines.append(RESULT_FOOTER)
    return scrub("\n".join(lines))


def detail_table(results, scrub):
    rows = ["| 번호 | 갈래 | 상태 | 대상 | 요약 | 메모 |", "|---|---|---|---|---|---|"]
    for item in sorted(results, key=lambda entry: (entry["id"], entry["arm"])):
        rows.append("| %s | %s | %s | %s | %s | %s |" % (item["id"], item["arm"], WORD[item["status"]], item["values"].get("target", ""), scrub(str(item["values"].get("brief", ""))).replace("|", "/"),
                                                        scrub(tail(item.get("note", ""), 200)).replace("|", "/").replace("\n", " ")))
    return "\n".join(rows)


def build_report(ctx, *, environ=None):
    """보고서 글(md)·사전(json)·결과 블록을 만든다 — 모든 글은 Scrubber 로 가린 것이다."""
    results = ctx.results
    gates = judge(results)
    scrub = Scrubber(ctx.host.environ if environ is None else environ, extra=[str(ctx.work), str(REPO), *ctx.secret_words])
    block = result_block(ctx, results, gates, scrub)
    helps = {key: scrub(value) for key, value in ctx.state.get("help", {}).items()}
    data = {"schema": 1, "gates": {arm: {gate: dict(value) for gate, value in rows.items()} for arm, rows in gates.items()}, "results": scrub.deep(results), "steps": scrub.deep(ctx.state.get("steps", {})),
            "tools": scrub.deep({key: {k: v for k, v in value.items() if k not in ("path", "python", "wheel")} for key, value in ctx.state.get("tools", {}).items()}),
            "pack_problems": scrub.deep(ctx.state.get("pack_problems", {})), "help": helps, "block": block}
    md = ["# 설치 도구 시험(spike) 보고서", "", "수동 워크플로 Installer spike 가 만든 보고서다(운영자 확인 037 ①, 설계서 INSTALLER 3-1). 값은 러너 한 번의 측정이다 — 점수와 결정은 AI 가 따로 한다.", "",
          "## 결과 블록(이 칸 그대로 소유자 이슈에 붙인다)", "", "```text", block, "```", "", "## 측정 기록 전부", "", detail_table(results, scrub), "", "## 도구 도움말 발췌(다음 고침의 근거)", ""]
    for key, value in helps.items():
        md += ["### " + key, "", "```text", value, "```", ""]
    if not helps:
        md.append("(도구 도움말을 받지 못했다)\n")
    return block, "\n".join(md) + "\n", data


def cmd_report(ctx):
    block, md, data = build_report(ctx)
    out = ctx.work / "report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "INSTALLER_SPIKE_REPORT.md").write_text(md, encoding="utf-8")
    (out / "INSTALLER_SPIKE_REPORT.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = ctx.host.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## 설치 도구 시험 결과 블록\n\n이 칸을 그대로 복사해 소유자 이슈에 붙인다.\n\n```text\n" + block + "\n```\n")
    print(block)


HANDLERS = {"install-tools": cmd_install_tools, "build-bundles": cmd_build_bundles, "pack": cmd_pack, "measure": cmd_measure, "report": cmd_report}


def main(argv=None, *, host=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--work", required=True, help="작업 폴더(상태·도구·묶음·설치 파일이 쌓인다)")
    args = parser.parse_args(argv)
    host = host or measure.Host()
    problem = measure.runner_problem(host.environ)
    if problem:                                                   # 시작 전에 멈춘다 — 작업 폴더도 만들지 않는다
        print("[spike] " + measure.RUNNER_REFUSAL + " (어긋난 조건: %s)" % problem, file=sys.stderr)
        return 2
    ctx = Context(args.work, host=host)
    began = ctx.host.now()
    try:
        HANDLERS[args.command](ctx)
    except Exception as error:                                   # 단계 하나가 죽어도 다음 단계와 보고서는 이어진다 — 이유는 상태에 적는다
        ctx.note_step(args.command, "crashed", round(ctx.host.now() - began, 1), error="%s: %s" % (type(error).__name__, tail(str(error), 300)))
        print("[spike] %s 단계가 중간에 멈췄다: %s" % (args.command, type(error).__name__), file=sys.stderr)
        return 1 if args.command == "report" else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
