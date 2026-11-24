"""정식 CI 의 Qt 칸(`ci.yml` 의 둘째 잡 `qt`)을 준비한다 — 잠금 파일에서 PySide6 두 줄만 설치하고 가져와 본다(D-710·D-711, 운영자 확인 037 ① 승인 범위, 설계서 CIQT 3-2).

왜: 정식 CI 열두 칸은 PySide6 없이 돌아 화면(Qt) 시험이 모두 '건너뜀' 이다. 이 스크립트로 PySide6 를 깐 칸에서만 Qt 시험이 진짜로 돈다
    (`scripts/ci_shard.py` 의 `CI_REQUIRE_QT` 가드가 그 칸에서 건너뜀이 하나라도 나오면 빨갛게 만든다).
하는 일(차례대로, 하나라도 실패하면 종료 코드가 0 이 아니다):
  1) `packaging/requirements-package.txt` 의 `# [runtime]` 아래 요구 줄을 읽는다. **정확히 두 줄**(`PySide6_Essentials==X`·`shiboken6==X`, 같은 X)이 아니면 거절한다 —
     runtime 에 줄이 더해지면 이 칸이 빨개져 의식적으로 고치게 한다('두 줄만'). 줄의 모양은 `이름==버전`(해시 옵션은 선택)뿐이고 다른 모양(범위·주소·옵션)은 거절한다.
  2) `python -m pip install --disable-pip-version-check --isolated --only-binary=:all: --no-deps 두 줄` 을 **고정 인자 목록으로**(셸 없음) 돌린다.
     `--isolated` 는 환경 변수·사용자 설정으로 설치처가 바뀌는 길을, `--only-binary` 는 설치 중 코드(setup.py) 실행을, `--no-deps` 는 딸려 오는 다른 패키지를 막는다.
     잠금 줄에 `--hash` 가 생기면 그 두 줄만 담은 임시 요구 파일과 `--require-hashes` 로 바꿔 부른다(해시 잠금은 따로 승인받는 일 — 지금 잠금에는 해시가 없다).
  3) 설치된 버전이 잠금과 같은지 보고, 화면 없는(offscreen) `QApplication` 을 만들어 보고, 글꼴 이름 몇 줄을 찍는다.
     한글을 그릴 수 있는 글꼴이 없으면 **알림만** 낸다(실패 아님 — 글자 잘림 시험이 붉을 때 어떻게 할지는 첫 실행 뒤 사람이 정한다, docs/CI_QT.md).
사용: python scripts/ci_qt_setup.py [--lock=파일] [--dry-run] [--probe-only]
  --dry-run     잠금을 읽어 pip 명령만 보여 주고 끝난다(아무것도 설치하지 않는다).
  --probe-only  설치는 건너뛰고 점검(3)만 한다(PySide6 가 이미 있는 PC 에서 확인용).
  `ci.yml` 은 인자 없이 부른다(시험이 못박는다) — 인자 없이 부르면 진짜로 설치한다.
종료 코드: 0 성공 · 2 잠금·인자를 읽지 못함 · 3 pip 설치 실패 · 4 설치된 버전이 잠금과 다름 · 5 Qt 점검 실패.
출력은 버전·글꼴 이름 몇 줄뿐이다(경로·사용자 이름 없음). 설치 도구의 출력은 실패했을 때 끝 몇 줄만, 사용자 폴더와 이름을 가려서 보인다.
표준 라이브러리만 쓴다(PySide6 는 점검 단계에서만 가져온다). 파이썬 3.10 문법.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / "packaging" / "requirements-package.txt"
RUNTIME_MARK = "# [runtime]"
SECTION_MARK = re.compile(r"^#\s*\[[A-Za-z0-9_-]+\]\s*$")                      # `# [runtime]`·`# [build]` 같은 절 표시 — 다음 표시에서 runtime 절이 끝난다
WANTED = ("pyside6-essentials", "shiboken6")                                   # 이 칸이 깔 수 있는 이름 둘(PEP 503 로 정리한 이름)
HASH_VALUE = r"sha256:[0-9a-f]{64}"
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[0-9][0-9A-Za-z.+!_-]*)(?P<hashes>(?:\s+--hash=" + HASH_VALUE + r")*)$")
PIP_TIMEOUT_SECONDS = 1500
TAIL_LINES = 20                                                                # 설치가 실패했을 때 보여 주는 설치 도구 출력의 끝 줄 수
KNOWN_HANGUL_FONTS = ("Malgun Gothic", "맑은 고딕", "Gulim", "굴림", "Dotum", "돋움", "Batang", "바탕", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR")
FONT_ALIASES = {"맑은 고딕": "Malgun Gothic", "굴림": "Gulim", "돋움": "Dotum", "바탕": "Batang"}               # 윈도가 한글 이름으로 알려 주는 글꼴의 Qt 쪽(영문) 이름
EXIT_LOCK, EXIT_PIP, EXIT_VERSION, EXIT_QT = 2, 3, 4, 5


class LockError(ValueError):
    """잠금 파일이 이 칸이 받아들이는 모양이 아니다(메시지에 줄 내용은 담지 않는다 — 줄에 주소·계정이 있어도 새지 않게)."""


class ProbeError(RuntimeError):
    """PySide6 점검(가져오기·화면 없는 QApplication 만들기)이 실패했다."""


class Lock(NamedTuple):
    version: str
    requirements: tuple            # ((잠금 파일에 적힌 이름, 버전, (해시, ...)), ...) 두 줄
    hashed: bool


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_lines(text):
    """`# [runtime]` 표시와 다음 표시(또는 파일 끝) 사이의 요구 줄을 이어 붙인 줄 하나씩. 빈 줄·주석 줄은 건너뛰고 줄 끝 `#` 주석은 뗀다."""
    lines = text.replace("\r\n", "\n").split("\n")
    marks = [number for number, line in enumerate(lines) if line.strip() == RUNTIME_MARK]
    if not marks:
        raise LockError("`# [runtime]` 표시가 없다")
    if len(marks) > 1:
        raise LockError("`# [runtime]` 표시가 둘 이상이다")
    found, pending = [], ""
    for line in lines[marks[0] + 1:]:
        stripped = line.strip()
        if pending:
            if not stripped or stripped.startswith("#"):
                raise LockError("줄 끝의 역슬래시 뒤에 이어지는 줄이 없다")
        else:
            if SECTION_MARK.match(stripped):
                break
            if not stripped or stripped.startswith("#"):
                continue
        stripped = re.sub(r"\s+#.*$", "", stripped)                          # 줄 끝 주석
        if stripped.endswith("\\"):
            pending = (pending + " " + stripped[:-1].strip()).strip()
            continue
        found.append((pending + " " + stripped).strip())
        pending = ""
    if pending:
        raise LockError("줄 끝의 역슬래시 뒤에 이어지는 줄이 없다")
    return found


def read_lock(text):
    """잠금 글에서 runtime 두 줄을 읽어 `Lock` 으로. 정확히 PySide6_Essentials·shiboken6 한 줄씩이고 버전이 같아야 한다(해시는 둘 다 있거나 둘 다 없어야 한다) — 아니면 LockError."""
    lines = runtime_lines(text)
    if len(lines) != 2:
        raise LockError(f"runtime 요구 줄이 정확히 두 줄이어야 한다(지금 {len(lines)}줄)")
    parsed = []
    for number, line in enumerate(lines, start=1):
        found = REQUIREMENT.match(line)
        if not found:
            raise LockError(f"runtime {number}번째 요구 줄을 읽을 수 없다('이름==버전' 모양만 받는다 — 범위·주소·옵션·표시는 거절)")
        hashes = tuple(re.findall(HASH_VALUE, found.group("hashes")))
        parsed.append((found.group("name"), found.group("version"), tuple("--hash=" + item for item in hashes)))
    if sorted(normalize(name) for name, _version, _hashes in parsed) != sorted(WANTED):
        raise LockError("runtime 두 줄의 이름은 PySide6_Essentials 와 shiboken6 여야 한다")
    if len({version for _name, version, _hashes in parsed}) != 1:
        raise LockError("runtime 두 줄의 버전이 같아야 한다")
    flags = {bool(hashes) for _name, _version, hashes in parsed}
    if len(flags) != 1:
        raise LockError("해시는 두 줄 모두에 있거나 모두 없어야 한다")
    return Lock(version=parsed[0][1], requirements=tuple(parsed), hashed=flags.pop())


def pip_command(lock, python, requirements_file=None):
    """설치 명령(인자 목록, 셸 없음). 고정 인자 + 잠금의 두 줄뿐이다. 해시 잠금이면 두 줄을 담은 임시 요구 파일(`requirements_file`)과 `--require-hashes` 를 쓴다."""
    command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--isolated", "--only-binary=:all:", "--no-deps"]
    if lock.hashed:
        return command + ["--require-hashes", "-r", str(requirements_file)]
    return command + [f"{name}=={version}" for name, version, _hashes in lock.requirements]


def requirements_text(lock):
    """해시 잠금일 때 임시 요구 파일에 쓰는 글(줄마다 `이름==버전 --hash=… --hash=…`)."""
    return "".join(" ".join([f"{name}=={version}", *hashes]) + "\n" for name, version, hashes in lock.requirements)


def scrub(text):
    """설치 도구 출력에서 사용자 폴더와 계정 이름을 가린다(실패했을 때 끝 몇 줄을 보여 주기 전에)."""
    home = str(Path.home())
    for secret, mask in ((home, "<홈>"), (home.replace("\\", "/"), "<홈>"), (os.environ.get("USERNAME") or os.environ.get("USER") or "", "<사용자>")):
        if len(secret) >= 3:
            text = text.replace(secret, mask)
    return text


def install(lock, run=subprocess.run):
    """pip 를 돌려 (종료 코드, 실패했을 때 보일 끝 몇 줄)을 돌려준다. `run` 은 시험이 가짜로 바꿔 끼우는 자리다."""
    with tempfile.TemporaryDirectory() as folder:
        requirements_file = None
        if lock.hashed:
            requirements_file = Path(folder) / "qt-requirements.txt"
            requirements_file.write_text(requirements_text(lock), encoding="utf-8")
        command = pip_command(lock, sys.executable, requirements_file)
        try:
            done = run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PIP_TIMEOUT_SECONDS, shell=False,
                       env=dict(os.environ, PYTHONUTF8="1"))
        except subprocess.TimeoutExpired:
            return 1, f"설치가 {PIP_TIMEOUT_SECONDS}초 안에 끝나지 않았다"
        except OSError as error:
            return 1, f"설치 도구를 시작하지 못했다({type(error).__name__})"
    output = (done.stdout or "") + (done.stderr or "")
    tail = "\n".join(line[:300] for line in scrub(output).strip().splitlines()[-TAIL_LINES:])
    return done.returncode, tail


def version_problems(lock, lookup=importlib.metadata.version):
    """설치된 두 패키지의 버전이 잠금과 다르거나 없으면 그 문장들(없으면 빈 목록)."""
    importlib.invalidate_caches()
    problems = []
    for name, version, _hashes in lock.requirements:
        try:
            got = lookup(name)
        except importlib.metadata.PackageNotFoundError:
            problems.append(f"{name} 이 설치되어 있지 않다")
            continue
        if got != version:
            problems.append(f"{name} 의 설치된 버전 {got} 이 잠금의 {version} 과 다르다")
    return problems


def font_facts(all_families, korean_families, message_font):
    """글꼴 목록에서 찍을 사실들. 한글을 그릴 수 있는 글꼴 = Qt 가 한글 문자 체계로 꼽은 것 + 이름이 알려진 한글 글꼴."""
    names = set(all_families)
    hangul = sorted(set(korean_families) | (names & set(KNOWN_HANGUL_FONTS)), key=lambda name: (name not in KNOWN_HANGUL_FONTS, name))      # 이름이 알려진 글꼴이 앞에 온다
    in_list = bool(message_font) and (message_font in names or FONT_ALIASES.get(message_font) in names)
    return {"count": len(names), "hangul": hangul, "message_font": message_font, "message_in_list": in_list}


def report_lines(lock, facts):
    """성공했을 때 찍는 줄들 — 버전·화면 방식·글꼴 이름뿐(경로·계정 없음). 한글 글꼴이 없으면 알림 줄이 더해진다(실패 아님)."""
    hangul = facts["hangul"]
    shown = ", ".join(hangul[:6]) + (f" 외 {len(hangul) - 6}개" if len(hangul) > 6 else "")
    message = facts["message_font"]
    lines = [
        f"Qt 준비: PySide6_Essentials·shiboken6 {lock.version}(잠금과 같다), Qt {facts['qt']}",
        f"Qt 화면 방식: {facts['platform']} — QApplication 만들기 통과",
        f"글꼴: 목록 {facts['count']}개·한글을 그릴 수 있는 글꼴 {len(hangul)}개" + (f"({shown})" if hangul else ""),
        "윈도 메시지 글꼴: " + (f"{message}({'목록에 있음' if facts['message_in_list'] else '목록에 없음'})" if message else "읽지 못함(윈도가 아니거나 읽기 실패)"),
    ]
    if not hangul:
        lines.append("알림: 한글을 그릴 수 있는 글꼴이 하나도 없다 — 글자 잘림 시험이 붉으면 docs/CI_QT.md 의 '한글 글꼴이 다를 때' 를 따른다(판정 기준은 낮추지 않는다)")
    return lines


def probe():
    """PySide6 를 가져와 화면 없는 `QApplication` 을 만들고 글꼴 사실을 모아 돌려준다. 실패하면 ProbeError."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import ui_offscreen
        ui_offscreen.prepare_environment()                                      # 시험과 같은 방식으로 offscreen 과 윈도 글꼴 폴더를 정한다
        from PySide6.QtCore import qVersion
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        platform = app.platformName()
        facts = font_facts(QFontDatabase.families(), QFontDatabase.families(QFontDatabase.WritingSystem.Korean), ui_offscreen.windows_message_font())
        facts.update(qt=qVersion(), platform=platform)
    except Exception as error:                                                  # 가져오기·DLL·플랫폼 플러그인 어느 쪽이든 칸을 빨갛게 한다
        raise ProbeError(f"{type(error).__name__}: {scrub(str(error))[:300]}") from None
    if platform != "offscreen":
        raise ProbeError(f"화면 방식이 offscreen 이 아니다({platform})")
    return facts


def parse(argv):
    options = {"lock": LOCK_FILE, "dry_run": False, "probe_only": False}
    for item in argv:
        if item == "--dry-run":
            options["dry_run"] = True
        elif item == "--probe-only":
            options["probe_only"] = True
        elif item.startswith("--lock=") and len(item) > len("--lock="):
            options["lock"] = Path(item[len("--lock="):])
        else:
            raise ValueError(f"모르는 인자: {item!r} (--lock=파일 · --dry-run · --probe-only 만 받는다)")
    if options["dry_run"] and options["probe_only"]:
        raise ValueError("--dry-run 과 --probe-only 는 함께 쓸 수 없다")
    return options


def use_utf8_output():
    """출력이 파이프일 때 윈도 기본 인코딩(cp1252 등)으로 한글을 찍다 죽지 않게 한다(ci.yml 의 이 단계에는 PYTHONUTF8 이 없다)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main(argv=None, run=subprocess.run, probe_function=None, lookup=None):
    use_utf8_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        options = parse(argv)
    except ValueError as error:
        print(f"인자를 읽지 못했다: {error}", file=sys.stderr)
        return EXIT_LOCK
    try:
        lock = read_lock(Path(options["lock"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, LockError) as error:
        print(f"잠금 파일을 받아들일 수 없다: {error if isinstance(error, LockError) else type(error).__name__}", file=sys.stderr)
        return EXIT_LOCK
    if options["dry_run"]:
        shown = pip_command(lock, "python", "<임시 요구 파일>")
        print("설치 명령(실행하지 않는다): " + " ".join(shown))
        return 0
    if not options["probe_only"]:
        code, tail = install(lock, run=run)
        if code != 0:
            print(f"PySide6 설치에 실패했다(종료 코드 {code}). 설치 도구 출력의 끝:\n{tail}", file=sys.stderr)
            return EXIT_PIP
    problems = version_problems(lock, lookup or importlib.metadata.version)
    if problems:
        print("설치된 PySide6 가 잠금과 맞지 않는다: " + " / ".join(problems), file=sys.stderr)
        return EXIT_VERSION
    try:
        facts = (probe_function or probe)()
    except ProbeError as error:
        print(f"PySide6 점검에 실패했다: {error}", file=sys.stderr)
        return EXIT_QT
    print("\n".join(report_lines(lock, facts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
