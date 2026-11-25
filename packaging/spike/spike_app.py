# -*- coding: utf-8 -*-
"""spike_app.py - 설치 도구 시험(spike)용 작은 앱(결정 D-704): 설치 훅 인자·버전·종료 코드·시작 즉시 실패를 흉내 낸다.

창이 없고(PyInstaller --windowed 로 묶는다) 사용자 데이터 파일 이름과 비밀 모양이 없다. 표준 라이브러리만 쓴다. 쓰는 것은 환경 변수 SPIKE_LOG 가 가리키는 로그 파일 한 줄씩뿐이고(없으면 아무것도 쓰지 않는다) 네트워크·하위 프로세스가 없다.
동작:
  · 인자가 정확히 둘이고 첫째가 훅 넷(--veloapp-install·--veloapp-updated·--veloapp-obsolete·--veloapp-uninstall) 중 하나, 둘째가 버전 모양에 통째로 맞으면 아무것도 쓰지 않고 곧바로 종료 코드 0(설계서 G-A 의 좁은 허용과 같은 규칙).
  · 실행 파일 옆에 BROKEN 파일이 있으면 시작하자마자 종료 코드 3(깨진 새 판 흉내, M11).
  · --hold 초: 그만큼 켜 둔다(실행 중 업데이트 시험, M09). --update-from 폴더: Velopack 파이썬 SDK 가 있는 갈래 A 에서만 — 그 폴더를 원본으로 확인·내려받기·적용(적용하고 곧 끝낸다, M08).
  · 그 밖의 인자는 종료 코드 2 로 거절한다(값을 되풀이하지 않는다).
버전은 실행 파일 옆 VERSION 파일에서 읽는다(묶음을 복사하고 이 파일만 바꿔 0.0.1·0.0.2·0.0.3 을 만든다).
"""
import os
import re
import sys
import time
from pathlib import Path

HOOKS = ("--veloapp-install", "--veloapp-updated", "--veloapp-obsolete", "--veloapp-uninstall")
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?")      # packaging/pkgcommon.py 의 VERSION_PATTERN 과 같다(시험이 같음을 지킨다)
EXIT_OK, EXIT_REFUSED, EXIT_BROKEN, EXIT_UPDATE_FAILED = 0, 2, 3, 4
MAX_HOLD_SECONDS = 600


def app_dir():
    """묶음 실행 파일이 있는 폴더(소스 실행이면 이 파일의 폴더)."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def read_version(directory):
    try:
        text = (Path(directory) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return text if VERSION_PATTERN.fullmatch(text) else "unknown"


def is_hook(argv):
    """훅 한 줄 모양인가 — 인자가 정확히 둘, 첫째는 소문자 그대로 훅 넷 중 하나, 둘째는 버전 모양에 통째로 맞는다."""
    return len(argv) == 2 and argv[0] in HOOKS and bool(VERSION_PATTERN.fullmatch(argv[1]))


def write_log(env, text):
    path = (env or {}).get("SPIKE_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def parse_options(argv):
    """허용하는 인자만 읽는다 → (옵션 사전, 문제 글 또는 ''). 허용: (없음) · --hold 숫자 · --update-from 폴더."""
    options, index = {}, 0
    while index < len(argv):
        name = argv[index]
        if name in ("--hold", "--update-from") and index + 1 < len(argv) and name not in options:
            options[name] = argv[index + 1]
            index += 2
            continue
        return {}, "모르는 인자"
    if "--hold" in options:
        if not re.fullmatch(r"\d{1,3}", options["--hold"]) or not 0 <= int(options["--hold"]) <= MAX_HOLD_SECONDS:
            return {}, "--hold 값이 이상하다"
    return options, ""


def hold(seconds, env, version, *, clock=time.monotonic, sleep=time.sleep):
    write_log(env, "holding %s %ds" % (version, seconds))
    began = clock()
    while clock() - began < seconds:
        sleep(0.5)
    write_log(env, "released %s" % version)


def update_with_sdk(sdk, feed, env, version):
    """Velopack 파이썬 SDK 로 feed(폴더)를 원본 삼아 확인·내려받기·적용(적용 뒤 끝낸다). 갈래 A 전용 — 결과는 로그 파일에만 적는다."""
    manager = sdk.UpdateManager(feed)
    write_log(env, "check from %s" % version)
    info = manager.check_for_updates()
    if not info:
        write_log(env, "no update")
        return EXIT_OK
    manager.download_updates(info)
    write_log(env, "downloaded")
    manager.apply_updates_and_exit(info)
    write_log(env, "apply requested")
    return EXIT_OK


def main(argv=None, env=None, *, directory=None, sdk=None, clock=time.monotonic, sleep=time.sleep):
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    directory = Path(directory) if directory else app_dir()
    if is_hook(argv):
        return EXIT_OK                                            # 훅: 아무것도 쓰지 않고 바로 끝낸다(창·상자·파일·네트워크 0)
    version = read_version(directory)
    if (directory / "BROKEN").exists():
        write_log(env, "broken %s exit %d" % (version, EXIT_BROKEN))
        return EXIT_BROKEN
    options, problem = parse_options(argv)
    if problem:
        write_log(env, "refused: " + problem)
        return EXIT_REFUSED
    if "--update-from" in options and sdk is None:
        write_log(env, "refused: SDK 가 없는 앱이라 --update-from 을 받지 않는다")
        return EXIT_REFUSED
    write_log(env, "started %s" % version)
    try:
        if "--update-from" in options:
            return update_with_sdk(sdk, options["--update-from"], env, version)
        if "--hold" in options:
            hold(int(options["--hold"]), env, version, clock=clock, sleep=sleep)
    except Exception as error:                                    # 시험용 앱 — 어떤 오류든 종류만 로그에 남기고 종료 코드로 알린다
        write_log(env, "update failed: %s" % type(error).__name__)
        return EXIT_UPDATE_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
