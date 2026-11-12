"""개인 PC 제한 시험용 묶음(Package)의 시작 파일 — **화면(GUI) 전용**이다.

묶음 실행 파일(`ChanceBlogDesktop.exe`)이 이 파일로 시작한다. 소스 실행(`python -m chanceblog_desktop …`)과 다르게:
  · 명령줄 부명령(`publish-pages`·`doctor`·`keys` …)과 `--yes` 계열 옵션을 **열지 않는다**: 인자가 하나라도 오면 값을 되풀이하지 않는 고정 문장으로 안내하고 끝낸다(종료 코드 2).
    개발자용 명령줄은 소스 실행에서만 쓴다(운영자 2026-11-11 결정 5·9 — 묶음에는 외부로 쓰는 길이 없다).
  · 숨은 점검 옵션 하나만 받는다: `--selftest`(정확히 이 한 단어일 때만). 묶음이 제대로 만들어졌는지 확인한다 — 아래 `run_selftest`.
창 없는(windowed) 실행 파일이라 표준 출력이 없을 수 있다(더블클릭). 그때는 안내를 메시지 상자로 보이고, 콘솔에서 열었다면 그 콘솔에 쓴다.
이 파일은 앱 코드(`src/`)를 고치지 않고 부르기만 한다 — 경로 가정(`vendor/`·`VERSION` 이 실행 파일 옆)은 코드로 고치지 않고 빌드가 정확히 배치하며, 자가 점검이 그 가정을 확인한다.
표준 라이브러리만 쓴다(`ctypes` 는 윈도의 메시지 상자·콘솔 붙이기에만, 오류 길에서만).
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

import pkgcommon as pc

SELFTEST_FLAG = "--selftest"
EXIT_FAILED = 1
EXIT_USAGE = 2                                                                  # 명령줄(`service/cli.py`)·화면 실행기의 사용법 오류와 같은 번호
REFUSED = ("이 프로그램은 화면(GUI)만 엽니다. 명령이나 옵션을 받지 않아요(입력한 값은 보이지 않습니다).\n"
           "실행 파일을 그냥 두 번 눌러 열어 주세요.")
START_FAILED = "화면을 시작하지 못했어요(오류 종류: {kind}). 압축을 다시 풀어 보고, 그래도 안 되면 이 글을 그대로 알려 주세요."
STATUS_LABEL = {"ok": "통과", "fail": "실패", "skip": "건너뜀"}
SCREENS = ("home", "topics", "drafts", "seed", "blogs", "settings")             # 화면 이동 키(`ui/core/app_state.py` 의 NAV)
IMAGE_FORMATS = ("jpeg", "png", "webp", "svg")                                  # 화면이 읽는 그림 형식(docs/UI_IMAGES.md §4)
QT_PLUGIN_FILES = ("platforms/qwindows.dll", "imageformats/qjpeg.dll", "imageformats/qwebp.dll", "imageformats/qsvg.dll")
REFUSED_ARGUMENT_SAMPLES = (["publish-pages", "--yes"], ["doctor"], ["gui"], ["--sample"], ["--help"], [SELFTEST_FLAG, "extra"], [SELFTEST_FLAG.upper()])
CLI_MODULES = ("chanceblog_desktop.service.cli", "chanceblog_desktop.__main__")  # 화면 전용 시작이 불러오면 안 되는 모듈
VENDOR_MODULES = ("pipeline", "pipeline.console", "pipeline.gates", "pipeline.secret_patterns")
_MANIFEST_LEVEL = re.compile(rb'requestedExecutionLevel\s+level\s*=\s*"([A-Za-z]+)"')


class Result(NamedTuple):
    key: str                 # 영문 점검 이름 — 빌드 도구가 읽는다
    status: str              # ok · fail · skip
    text: str                # 쉬운 한국어 설명(비밀·긴 경로 없음)


class _NullWriter:
    """표준 출력이 없는(창 없는 실행) 때 `write` 를 부르는 코드가 죽지 않게 하는 빈 쓰개."""
    encoding = "utf-8"

    def write(self, text):
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


# ---- 입출력 ------------------------------------------------------------

def is_frozen():
    return bool(getattr(sys, "frozen", False))


def app_root():
    """앱 폴더 — 묶음 실행 파일이 있는 폴더(소스 실행이면 저장소 맨 위). `vendor/`·`VERSION`·`PACKAGE_INFO.*` 가 여기에 있어야 한다."""
    return Path(sys.executable).resolve().parent if is_frozen() else Path(__file__).resolve().parents[1]


def prepare_streams():
    """표준 출력·오류가 없으면 빈 쓰개를 달고, 있으면 UTF-8 로 맞춘다(`X utf8` 가 빠져도 한글 출력이 죽지 않게 하는 안전망)."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, _NullWriter())
        elif hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def has_output():
    return not isinstance(sys.stdout, _NullWriter)


def attach_parent_console():            # pragma: no cover - 윈도 콘솔 전용
    """창 없는 실행 파일이 콘솔에서 열렸으면 그 콘솔에 쓰게 한다(`--selftest` 결과를 보이려고). 못 붙이면 False."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        if not ctypes.windll.kernel32.AttachConsole(-1):
            return False
        sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        return True
    except (OSError, AttributeError, ValueError):
        return False


def message_box(text, error=False):     # pragma: no cover - 윈도 전용
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, pc.PRODUCT, 0x10 if error else 0x40)
    except (OSError, AttributeError):
        pass


def say(text, *, error=False):
    """안내 글을 보인다 — 표준 출력(오류면 표준 오류)이 있으면 거기에, 없으면 메시지 상자."""
    if has_output():
        print(text, file=sys.stderr if error else sys.stdout)
    else:
        message_box(text, error)


# ---- 점검(--selftest) ------------------------------------------------------

def check_utf8(flag, encoding, frozen):
    good = bool(flag) and str(encoding).lower().replace("-", "").replace("_", "") == "utf8"
    if good:
        return Result("utf8_mode", "ok", "파이썬 UTF-8 모드가 켜져 있어요(기본 글 인코딩 utf-8)")
    if frozen:
        return Result("utf8_mode", "fail", "UTF-8 모드가 꺼져 있어요(빌드 옵션 'X utf8' 이 빠졌어요) — 한글 파일을 읽다 오류가 날 수 있어요")
    return Result("utf8_mode", "skip", "소스 실행이에요 — PYTHONUTF8=1 로 UTF-8 모드를 켜는 것을 권해요")


def read_info(root):
    """묶음 안 `PACKAGE_INFO.json` → 사전 또는 None(없음·깨짐)."""
    try:
        data = json.loads((Path(root) / pc.INFO_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def check_version_file(root, app_version_path, info, frozen):
    """`VERSION` 이 앱이 읽는 자리(실행 파일 옆)에 있고 번호 모양이며, 정보 파일의 버전과 같다."""
    wanted = Path(root) / "VERSION"
    try:
        number = pc.parse_version_text(wanted.read_text(encoding="utf-8"))
    except OSError:
        number = None
    if number is None:
        return Result("version_file", "fail" if frozen else "skip", "VERSION 파일이 없거나 번호 모양이 아니에요")
    if Path(app_version_path).resolve() != wanted.resolve():
        return Result("version_file", "fail", "앱이 VERSION 을 찾는 자리와 실제 VERSION 이 있는 자리가 달라요(경로 가정이 어긋났어요)")
    if info is not None and info.get("version") != number:
        return Result("version_file", "fail", "VERSION 과 PACKAGE_INFO.json 의 버전이 달라요(섞인 묶음일 수 있어요)")
    return Result("version_file", "ok", f"VERSION {number} 이 앱이 찾는 자리에 있어요")


def check_package_info(root, info, frozen):
    if info is None:
        return Result("package_info", "fail" if frozen else "skip", "PACKAGE_INFO.json 이 없거나 읽을 수 없어요" if frozen else "소스 실행에는 PACKAGE_INFO.json 이 없어요(묶음에만 있어요)")
    problems = []
    git = info.get("git") if isinstance(info.get("git"), dict) else {}
    signing = info.get("signing") if isinstance(info.get("signing"), dict) else {}
    if info.get("schema") != pc.SCHEMA:
        problems.append("schema")
    if info.get("channel") != pc.CHANNEL or info.get("variant") != "inner":
        problems.append("channel/variant")
    if not isinstance(info.get("trial"), bool):
        problems.append("trial 칸(시험 빌드 표시)")
    if not re.fullmatch(r"[0-9a-f]{40}", str(git.get("commit", ""))) or git.get("clean") is not True:
        problems.append("git(커밋·깨끗함)")
    if signing.get("signed") is not False:
        problems.append("signing(미서명 표시)")
    if pc.NOTICE not in str(info.get("notice", "")):
        problems.append("notice 문구")
    if not isinstance(info.get("files"), dict) or not info["files"]:
        problems.append("files 목록")
    if not (Path(root) / pc.INFO_MD).is_file():
        problems.append("PACKAGE_INFO.md 없음")
    if problems:
        return Result("package_info", "fail", "정보 파일에 문제가 있어요: " + ", ".join(problems))
    trial_text = f" · {pc.TRIAL_NOTICE}" if info.get("trial") else ""
    return Result("package_info", "ok", f"버전 {info.get('version')} · 커밋 {git['commit'][:7]} · {pc.NOTICE}{trial_text}")


def check_file_hashes(root, info, frozen, *, limit=5):
    """정보 파일의 파일별 SHA-256 목록과 실제 파일을 대조한다 — 빠졌거나(압축 해제 실패·백신 격리) 다르면 실패, 목록에 없는 파일은 알리기만 한다."""
    if info is None or not isinstance(info.get("files"), dict):
        return Result("file_hashes", "fail" if frozen else "skip", "파일 목록이 없어서 대조하지 못했어요" if frozen else "소스 실행에는 파일 목록이 없어요")
    root = Path(root)
    listed = info["files"]
    missing, different = [], []
    for relative, digest in listed.items():
        path = root / relative
        if not path.is_file():
            missing.append(relative)
        elif pc.sha256_file(path) != digest:
            different.append(relative)
    extras = []
    for current, _directories, names in os.walk(root):
        for name in names:
            relative = (Path(current) / name).relative_to(root).as_posix()
            if relative not in listed and relative not in pc.FILES_EXCLUDED_FROM_LIST:
                extras.append(relative)
    if missing or different:
        shown = [f"없음 {name}" for name in missing[:limit]] + [f"다름 {name}" for name in different[:limit]]
        return Result("file_hashes", "fail", f"목록과 다른 파일이 있어요(없음 {len(missing)} · 다름 {len(different)}): " + " / ".join(shown))
    note = f" (목록에 없는 파일 {len(extras)}개는 알림만: {', '.join(extras[:3])})" if extras else ""
    return Result("file_hashes", "ok", f"파일 {len(listed):,}개가 목록의 SHA-256 과 모두 같아요{note}")


def check_licenses(root, frozen):
    folder = Path(root) / pc.LICENSES_DIR
    if not folder.is_dir():
        return Result("licenses", "fail" if frozen else "skip", "LICENSES 폴더가 없어요" if frozen else "소스 실행에는 LICENSES 폴더가 없어요(묶음에만 있어요)")
    problems = []
    for name in pc.LICENSE_FILES:
        path = folder / name
        if not path.is_file() or path.stat().st_size == 0:
            problems.append(name)
    if not problems:
        lgpl = (folder / "LGPL-3.0.txt").read_text(encoding="utf-8", errors="replace")
        gpl = (folder / "GPL-3.0.txt").read_text(encoding="utf-8", errors="replace")
        notices = (folder / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8", errors="replace")
        if "GNU LESSER GENERAL PUBLIC LICENSE" not in lgpl or "Version 3" not in lgpl:
            problems.append("LGPL-3.0.txt 내용")
        if "GNU GENERAL PUBLIC LICENSE" not in gpl or "Version 3" not in gpl:
            problems.append("GPL-3.0.txt 내용")
        if "PySide6" not in notices or "LGPL" not in notices:
            problems.append("THIRD_PARTY_NOTICES.md 내용")
    if problems:
        return Result("licenses", "fail", "라이선스 파일에 문제가 있어요: " + ", ".join(problems))
    return Result("licenses", "ok", f"라이선스 파일 {len(pc.LICENSE_FILES)}개가 있어요")


def check_vendor(root, core, *, find_spec=importlib.util.find_spec):
    """`vendor/` 가 앱이 찾는 자리(실행 파일 옆)에 있고, VENDOR.json 의 해시와 같고, 불러와지고, 그 파일들이 쓰는 표준 모듈이 묶음에 있다."""
    wanted = Path(root) / "vendor"
    vendor = Path(core.vendor_dir())
    if vendor.resolve() != wanted.resolve() or not vendor.is_dir():
        return Result("vendor_core", "fail", "앱이 vendor 를 찾는 자리와 실제 vendor 가 있는 자리가 달라요(경로 가정이 어긋났어요)")
    try:
        manifest = json.loads((vendor / "VENDOR.json").read_text(encoding="utf-8"))
        files = manifest["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return Result("vendor_core", "fail", "vendor/VENDOR.json 을 읽지 못했어요")
    wrong = [name for name, digest in sorted(files.items()) if not (vendor / name).is_file() or pc.sha256_file(vendor / name) != digest]
    if wrong:
        return Result("vendor_core", "fail", "vendor 파일이 VENDOR.json 의 해시와 달라요: " + ", ".join(wrong[:5]))
    core.use_vendored_core()
    try:
        for module in VENDOR_MODULES:
            importlib.import_module(module)
    except Exception as error:      # noqa: BLE001 - 어떤 불러오기 실패든 점검 실패로 알린다
        return Result("vendor_core", "fail", f"vendor 모듈을 불러오지 못했어요({type(error).__name__}: {module})")
    missing = []
    for name in sorted(files):
        if name.endswith(".py"):
            for imported in pc.stdlib_imports((vendor / name).read_text(encoding="utf-8")):
                try:
                    if find_spec(imported) is None:
                        missing.append(imported)
                except (ImportError, ValueError):
                    missing.append(imported)
    if missing:
        return Result("vendor_core", "fail", "vendor 파일이 쓰는 표준 모듈이 묶음에 없어요: " + ", ".join(sorted(set(missing))[:5]))
    return Result("vendor_core", "ok", f"vendor 파일 {len(files)}개의 해시가 같고 모듈이 불러와져요")


def check_capabilities(*, import_module=importlib.import_module):
    """외부 쓰기 관문 — 소스 상수 `EXTERNAL_WRITE` 와 `BLOGGER_OAUTH_INPUT` 이 둘 다 `False` 여야 한다(없어도 실패 — 관문 없는 소스로는 시험용도 내보내지 않는다).
    '모듈 자체가 없음'과 '모듈은 있는데 안에서 가져오기가 실패함'은 다른 글로 알린다 — 빌드의 `--allow-missing-gate` 는 앞의 것만 넘긴다(D-419)."""
    try:
        module = import_module("chanceblog_desktop.capabilities")
    except ModuleNotFoundError as error:
        if error.name == "chanceblog_desktop.capabilities":
            return Result("capabilities", "fail", pc.GATE_MISSING_TEXT + " — 이 소스에는 외부 쓰기를 막는 관문이 아직 없어요")
        return Result("capabilities", "fail", f"외부 쓰기 관문 모듈 안에서 필요한 다른 모듈을 불러오지 못했어요(오류 종류: {type(error).__name__})")
    except ImportError as error:
        return Result("capabilities", "fail", f"외부 쓰기 관문 모듈을 불러오지 못했어요(오류 종류: {type(error).__name__})")
    for name in ("EXTERNAL_WRITE", "BLOGGER_OAUTH_INPUT"):
        if not hasattr(module, name):
            return Result("capabilities", "fail", f"관문 상수 {name} 이 없어요")
        if getattr(module, name) is not False:
            return Result("capabilities", "fail", f"관문 상수 {name} 이 False 가 아니에요 — 외부 쓰기가 열려 있어요")
    return Result("capabilities", "ok", "외부 쓰기·Blogger 입력 관문이 모두 꺼져 있어요(EXTERNAL_WRITE=False · BLOGGER_OAUTH_INPUT=False)")


def check_uac_manifest(exe_path, frozen):
    """실행 파일의 매니페스트가 일반 사용자 권한(asInvoker)으로 시작한다고 적혀 있다(관리자 권한 요구 0)."""
    if not frozen:
        return Result("uac_manifest", "skip", "소스 실행에는 실행 파일 매니페스트가 없어요")
    try:
        data = Path(exe_path).read_bytes()
    except OSError:
        return Result("uac_manifest", "fail", "실행 파일을 읽지 못했어요")
    match = _MANIFEST_LEVEL.search(data)
    if match is None:
        return Result("uac_manifest", "fail", "실행 파일 매니페스트에서 실행 수준을 찾지 못했어요")
    level = match.group(1).decode("ascii")
    if level != "asInvoker":
        return Result("uac_manifest", "fail", f"실행 수준이 {level} 예요 — 관리자 권한을 요구할 수 있어요")
    return Result("uac_manifest", "ok", "실행 수준 asInvoker — 관리자 권한을 요구하지 않아요")


def check_gui_only(main_function, modules=None):
    """인자가 오면 열지 않고(종료 코드 2·입력값 되풀이 없음), 화면 전용 시작이 명령줄 모듈을 불러오지 않았다."""
    modules = sys.modules if modules is None else modules
    for arguments in REFUSED_ARGUMENT_SAMPLES:
        spoken = []
        code = main_function(list(arguments), say=lambda text, error=False: spoken.append(text))
        if code != EXIT_USAGE or spoken != [REFUSED]:                       # 유일한 출력이 고정 문장이어야 한다 — 입력한 값을 되풀이할 수 없다
            return Result("gui_only_entry", "fail", "인자를 받았는데 거절하지 않았거나 고정 문장 말고 다른 글을 냈어요")
    loaded = [name for name in CLI_MODULES if name in modules]
    if loaded:
        return Result("gui_only_entry", "fail", "화면 전용 시작이 명령줄 모듈을 불러왔어요: " + ", ".join(loaded))
    return Result("gui_only_entry", "ok", "인자를 모두 거절하고(값 되풀이 없음) 명령줄 모듈은 불러오지 않았어요")


def check_data_dir(temp_root):
    """점검 중 `LOCALAPPDATA`(점검용 임시 폴더로 바꿔 둔 것) 안에 아무것도 생기지 않았다 — 점검은 데이터 폴더를 만들지 않는다."""
    created = sorted(path.relative_to(temp_root).as_posix() for path in Path(temp_root).rglob("*"))
    if created:
        return Result("data_dir_untouched", "fail", "점검이 데이터 폴더에 파일을 만들었어요: " + ", ".join(created[:5]))
    return Result("data_dir_untouched", "ok", "점검 중 데이터 폴더(LOCALAPPDATA 아래)에 아무것도 만들지 않았어요")


def check_qt(frozen):
    """PySide6 가 있고(묶음은 꼭), 플러그인 파일·그림 형식·화면 여섯이 창 없이(offscreen) 만들어진다."""
    if importlib.util.find_spec("PySide6") is None:
        return [Result("qt_plugins", "fail" if frozen else "skip", "PySide6 가 없어요" + ("" if frozen else "(소스 실행에서는 선택 설치)")),
                Result("qt_screens", "fail" if frozen else "skip", "PySide6 가 없어서 화면을 만들지 못했어요")]
    os.environ["QT_QPA_PLATFORM"] = "offscreen"                              # 창을 띄우지 않는다(점검 한정)
    results = []
    problems = []
    try:
        import PySide6
        from PySide6 import QtCore, QtGui
        from chanceblog_desktop.ui.core.services import FakeHomeProvider
        from chanceblog_desktop.ui.qt import app as qt_app
        from chanceblog_desktop.ui.qt.shell import AppShell
        application = qt_app.make_app(["selftest"])
        if sys.platform == "win32":
            plugins = Path(PySide6.__file__).resolve().parent / "plugins"
            problems += [name for name in QT_PLUGIN_FILES if not (plugins / name).is_file()]
        formats = {bytes(item).decode("ascii", "replace").lower() for item in QtGui.QImageReader.supportedImageFormats()}
        problems += [f"그림 형식 {name}" for name in IMAGE_FORMATS if name not in formats and not (name == "jpeg" and "jpg" in formats)]
        if problems:
            results.append(Result("qt_plugins", "fail", "빠진 Qt 구성 요소: " + ", ".join(problems)))
        else:
            results.append(Result("qt_plugins", "ok", "Windows 화면 플러그인과 그림 형식(jpeg·png·webp·svg)이 모두 있어요"))
        caught = []
        previous_hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: caught.append(kind.__name__)
        try:
            window = AppShell(FakeHomeProvider(delay=0.0), autoload=False)
            window.show()
            opened = []
            for key in SCREENS:
                window.go(key)
                application.processEvents()
                if window.state.page == key and window.screen_widget is not None:
                    opened.append(key)
            QtCore.QTimer.singleShot(400, application.quit)             # 화면을 읽는 작업(스레드)이 신호를 한 번 돌려주게 짧게 돈다
            application.exec()
            window.close()
            window.deleteLater()
            application.processEvents()
        finally:
            sys.excepthook = previous_hook
        if len(opened) != len(SCREENS) or caught:
            results.append(Result("qt_screens", "fail", f"화면 {len(opened)}/{len(SCREENS)}개만 열렸어요" + (f" · 처리 못 한 예외: {', '.join(sorted(set(caught)))}" if caught else "")))
        else:
            results.append(Result("qt_screens", "ok", f"화면 {len(SCREENS)}개(홈·후보·초안·Seed·블로그·설정)가 창 없이 열렸어요"))
    except Exception as error:      # noqa: BLE001 - 어떤 실패든 점검 결과로 알린다
        results.append(Result("qt_screens", "fail", f"화면 점검 중 오류({type(error).__name__})"))
        if not any(item.key == "qt_plugins" for item in results):
            results.insert(0, Result("qt_plugins", "fail", f"Qt 점검 중 오류({type(error).__name__})"))
    return results


def guarded(function, key, *args, **kwargs):
    """점검 하나를 돌리고 예상 못 한 예외는 그 점검의 실패로 바꾼다(다른 점검은 계속)."""
    try:
        return function(*args, **kwargs)
    except Exception as error:      # noqa: BLE001
        return Result(key, "fail", f"점검 중 오류({type(error).__name__})")


def apply_frozen_strictness(results, frozen):
    """묶음(frozen)에서는 건너뜀도 실패로 센다(묶음은 건너뛸 수 있는 점검이 없다) — 소스 실행은 그대로."""
    if not frozen:
        return list(results)
    return [Result(item.key, "fail", "묶음에서는 건너뛸 수 없는 점검이에요: " + item.text) if item.status == "skip" else item for item in results]


def run_selftest(*, main_function=None):
    """묶음이 제대로 만들어졌는지 확인한다 — 결과 목록을 돌려준다(콘솔에 보이는 일은 `selftest_main`).
    데이터 폴더를 만들지 않으려고 이 점검 안에서만 `LOCALAPPDATA`·`XDG_DATA_HOME` 을 임시 폴더로 바꾸고 .pyc 를 쓰지 않는다. 묶음(frozen)이면 건너뜀도 실패로 센다."""
    frozen = is_frozen()
    root = app_root()
    temp_root = tempfile.mkdtemp(prefix="cbd-selftest-")
    saved = {name: os.environ.get(name) for name in ("LOCALAPPDATA", "XDG_DATA_HOME", "QT_QPA_PLATFORM")}
    saved_bytecode = sys.dont_write_bytecode
    os.environ["LOCALAPPDATA"] = os.environ["XDG_DATA_HOME"] = temp_root
    sys.dont_write_bytecode = True
    results = []
    try:
        if not frozen:
            src = root / "src"
            if src.is_dir() and str(src) not in sys.path:
                sys.path.insert(0, str(src))
        import locale
        results.append(guarded(check_utf8, "utf8_mode", sys.flags.utf8_mode, locale.getpreferredencoding(False), frozen))
        info = read_info(root)
        try:
            from chanceblog_desktop import core
            from chanceblog_desktop.ui.core import version as app_version
        except Exception as error:      # noqa: BLE001
            core = app_version = None
            results.append(Result("app_import", "fail", f"앱 모듈을 불러오지 못했어요({type(error).__name__})"))
        if core is not None:
            results.append(guarded(check_version_file, "version_file", root, app_version.default_path(), info, frozen))
        results.append(guarded(check_package_info, "package_info", root, info, frozen))
        results.append(guarded(check_file_hashes, "file_hashes", root, info, frozen))
        results.append(guarded(check_licenses, "licenses", root, frozen))
        if core is not None:
            results.append(guarded(check_vendor, "vendor_core", root, core))
        results.append(guarded(check_capabilities, "capabilities"))
        results.append(guarded(check_uac_manifest, "uac_manifest", sys.executable, frozen))
        if core is not None:
            results.extend(check_qt(frozen))
        results.append(guarded(check_gui_only, "gui_only_entry", main_function or main))
        results.append(guarded(check_data_dir, "data_dir_untouched", temp_root))
    finally:
        sys.dont_write_bytecode = saved_bytecode
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(temp_root, ignore_errors=True)
    return apply_frozen_strictness(results, frozen)


def format_results(results, version):
    lines = [f"{pc.PRODUCT} {version} 자가 점검 — {pc.NOTICE}"]
    lines += [f"[{STATUS_LABEL[item.status]}] {item.key}: {item.text}" for item in results]
    counts = {status: sum(1 for item in results if item.status == status) for status in STATUS_LABEL}
    verdict = "모두 정상" if not counts["fail"] else "점검 실패"
    lines.append(f"결과: 통과 {counts['ok']} · 실패 {counts['fail']} · 건너뜀 {counts['skip']} — {verdict}")
    return lines


def selftest_exit_code(results):
    return EXIT_FAILED if any(item.status == "fail" for item in results) else 0


def selftest_main(*, main_function=None):
    if not has_output():
        attach_parent_console()
    results = run_selftest(main_function=main_function)
    root = app_root()
    try:
        number = pc.parse_version_text((root / "VERSION").read_text(encoding="utf-8")) or "?"
    except OSError:
        number = "?"
    code = selftest_exit_code(results)
    say("\n".join(format_results(results, number)), error=bool(code))
    return code


# ---- 화면 시작 ----------------------------------------------------------

def start_gui():
    """화면을 연다(`ui/launcher.py`) — 인자 없이. 시작하지 못하면 고정 문장(오류 종류 이름만)으로 안내한다."""
    if not is_frozen():
        src = Path(__file__).resolve().parents[1] / "src"
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
    buffer = io.StringIO()
    try:
        from chanceblog_desktop.ui.launcher import main as gui_main
        code = gui_main([], out=buffer)
    except Exception as error:      # noqa: BLE001 - 추적·메시지에는 경로와 값이 들어 있어 종류 이름만 보인다
        say(START_FAILED.format(kind=type(error).__name__), error=True)
        return EXIT_FAILED
    text = buffer.getvalue().strip()
    if text:
        say(text, error=bool(code))
    return int(code or 0)


def main(argv=None, *, say=say, start=None):
    """인자가 없으면 화면, 정확히 `--selftest` 하나면 자가 점검, 그 밖의 인자는 모두 거절한다(값은 되풀이하지 않는다)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == [SELFTEST_FLAG]:
        return selftest_main()
    if args:
        say(REFUSED, error=True)
        return EXIT_USAGE
    return (start or start_gui)()


def finish(code, *, selftest):
    """종료한다 — 자가 점검은 글을 다 내보낸 뒤 바로 끝낸다(Qt 정리 중 멈춤 방지), 화면은 보통 종료."""
    if not selftest:
        sys.exit(code)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
    os._exit(code)


if __name__ == "__main__":
    prepare_streams()
    finish(main(), selftest=sys.argv[1:] == [SELFTEST_FLAG])
