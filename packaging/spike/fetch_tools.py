# -*- coding: utf-8 -*-
"""fetch_tools.py - 설치 도구 시험(수동 워크플로 installer-spike.yml)의 한 단계: 고정 도구를 tools.lock.json 의 크기·SHA-256 대로 받는다(결정 D-701).

러너에서만 도는 빌드 전용 도구다 — 앱 본체(src/)에는 내려받는 코드가 없고 앱의 '밖으로 나가는 곳' 허용 목록과 상관이 없다. 표준 라이브러리만 쓴다. 비밀·토큰·계정을 쓰지 않는다.
직접 받는 도구(kind 가 direct 인 항목, vpk 패키지)는 아래 규칙으로만 받는다:
  1) 시작 주소의 호스트는 FIXED_HOSTS(github.com) 하나뿐이다(https 만, 사용자 정보·포트 없음). 잠금 파일이 다른 호스트를 가리키면 받지 않고 거절한다.
  2) 리디렉션은 REDIRECT_HOSTS(GitHub 의 공식 자산 호스트 둘)까지만 따라가고(https 만, 정확히 같은 이름만 — 닮은 이름·하위 이름·밖으로 가는 주소는 그 자리에서 거절), 횟수도 MAX_REDIRECTS 번까지다.
  3) 읽는 양은 잠금의 바이트 수를 넘지 못한다(넘으면 그 자리에서 멈춘다). 시간은 한 번의 읽기마다 SOCKET_SECONDS, 전체 TOTAL_SECONDS 를 넘지 못한다.
  4) 받은 직후 크기와 SHA-256 이 잠금 값과 같을 때만 파일을 남기고, 다르면 임시 파일을 지우고 실패한다(종료 코드 1). 일시적인 네트워크 오류·서버 5xx 만 다시 한다.
  5) 파이썬 휠(kind 가 pip 인 항목)은 여기서 받지 않는다 — run_spike.py install-tools 가 pip 의 해시 검사로 받고 이 파일의 check_file 로 같은 값을 다시 대조한다.
사용: python packaging/spike/fetch_tools.py --dest <폴더> [--lock tools.lock.json] [--check-only]
종료 코드: 0 모두 잠금 값과 같음 · 1 받기·대조 실패 · 2 잠금 파일이나 인자가 이상함.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOCK = os.path.join(HERE, "tools.lock.json")
FIXED_HOSTS = ("github.com",)
REDIRECT_HOSTS = ("release-assets.githubusercontent.com", "objects.githubusercontent.com")
PIP_HOST = "pypi.org"
PIP_FILE_HOST = "files.pythonhosted.org"
MAX_REDIRECTS = 5
USER_AGENT = "chanceblog-installer-spike/1 (fixed tools only)"
SOCKET_SECONDS = 60
TOTAL_SECONDS = 900
ATTEMPTS = 3
WAITS = (5, 20)
CHUNK = 1 << 20
SIZE_CEILING = 200 * 1024 * 1024
KINDS = ("direct", "pip")
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
VERSION_TEXT = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_TEXT = re.compile(r"^[0-9a-f]{64}$")
PATH_TEXT = re.compile(r"^/[A-Za-z0-9._/-]{1,200}$")
PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
LOG_NAME = "fetch_tools.log.json"


class FetchError(Exception):
    def __init__(self, message, retry=False):
        super().__init__(message)
        self.retry = retry


def host_of(url):
    """주소의 호스트(소문자, 끝의 점 없음) — 사용자 정보·포트가 있거나 https 가 아니면 ''(허용할 수 없는 주소)."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None or port not in (None, 443):
        return ""
    return parts.hostname.lower().rstrip(".")


def lock_problems(lock):
    """잠금 파일이 모양대로인가 — 어긋난 곳의 목록(없으면 빈 목록). 호스트·경로·파일 이름·크기·SHA-256 의 모양을 닫아 두어 잠금이 바뀌어도 허용 호스트 밖으로 못 가게 한다."""
    if not isinstance(lock, dict) or lock.get("schema") != 1:
        return ["schema 가 1 이 아니다"]
    tools = lock.get("tools")
    if not isinstance(tools, list) or not tools:
        return ["tools 목록이 없다"]
    problems, keys, files = [], set(), set()
    for index, tool in enumerate(tools, start=1):
        label = "tools[%d]" % index
        if not isinstance(tool, dict):
            problems.append(label + " 가 사전이 아니다")
            continue
        key, kind, name = tool.get("key"), tool.get("kind"), tool.get("file")
        if not isinstance(key, str) or not key or key in keys:
            problems.append(label + " 의 key 가 없거나 겹친다")
        keys.add(key)
        if kind not in KINDS:
            problems.append(label + " 의 kind 가 direct·pip 가 아니다")
        if not isinstance(name, str) or not FILE_NAME.match(name) or ".." in name:
            problems.append(label + " 의 file 이름 모양이 이상하다")
        elif name in files:
            problems.append(label + " 의 file 이 겹친다")
        files.add(name)
        if not isinstance(tool.get("version"), str) or not VERSION_TEXT.match(tool.get("version", "")):
            problems.append(label + " 의 version 모양이 이상하다")
        size = tool.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= SIZE_CEILING:
            problems.append(label + " 의 bytes 가 1 이상 %d 이하의 정수가 아니다" % SIZE_CEILING)
        if not isinstance(tool.get("sha256"), str) or not SHA256_TEXT.match(tool.get("sha256", "")):
            problems.append(label + " 의 sha256 이 소문자 16진수 64자가 아니다")
        if kind == "direct":
            path = tool.get("path")
            if tool.get("host") not in FIXED_HOSTS:
                problems.append(label + " 의 host 가 고정 호스트 %s 가 아니다" % (FIXED_HOSTS,))
            if not isinstance(path, str) or not PATH_TEXT.match(path) or ".." in path or "//" in path or not path.endswith("/" + str(name)):
                problems.append(label + " 의 path 모양이 이상하다(슬래시로 시작하고 file 이름으로 끝나야 한다)")
        elif kind == "pip":
            if tool.get("host") != PIP_HOST or tool.get("file_host") != PIP_FILE_HOST:
                problems.append(label + " 의 host 가 %s·%s 가 아니다" % (PIP_HOST, PIP_FILE_HOST))
            if not isinstance(tool.get("project"), str) or not PROJECT_NAME.match(tool.get("project", "")):
                problems.append(label + " 의 project 이름 모양이 이상하다")
    return problems


def download_url(tool):
    """직접 받는 도구의 주소 — 호스트와 경로는 lock_problems 가 모양을 닫은 값이다."""
    return "https://" + tool["host"] + tool["path"]


class GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """리디렉션이 https 가 아니거나 REDIRECT_HOSTS 밖이면 따라가지 않고 멈춘다(횟수도 MAX_REDIRECTS 번까지)."""

    max_redirections = MAX_REDIRECTS                 # 서로 다른 주소를 최대 이만큼
    max_repeats = 1                                  # 같은 주소로 다시 돌아오면(되돌이) 두 번째에서 멈춘다

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = host_of(newurl)
        if host not in REDIRECT_HOSTS:
            raise FetchError("허용 목록 밖으로 넘어가는 주소를 거절했다(호스트 %s)" % (urllib.parse.urlsplit(newurl).hostname,))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def check_file(path, tool):
    """파일이 잠금의 크기와 SHA-256 에 같은가 — 같으면 '', 아니면 이유 글(없는 파일도 이유). 휠을 pip 로 받은 뒤에도 이 함수로 다시 대조한다."""
    if not os.path.isfile(path):
        return "파일이 없다"
    if os.path.getsize(path) != tool["bytes"]:
        return "크기가 잠금 값과 다르다(%d바이트, 기대 %d)" % (os.path.getsize(path), tool["bytes"])
    if sha256_file(path) != tool["sha256"]:
        return "SHA-256 이 잠금 값과 다르다"
    return ""


def fetch_file(tool, target, opener, *, clock=time.monotonic, deadline=None):
    """한 파일을 받아 크기·SHA-256 이 잠금 값과 같을 때만 target 으로 옮긴다. 읽는 양은 잠금 크기를 넘지 못하고, 전체 시간은 deadline(clock 기준 시각)을 넘지 못한다."""
    if host_of(download_url(tool)) not in FIXED_HOSTS:
        raise FetchError("시작 주소가 고정 호스트가 아니다")
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    temp = target + ".part"
    digest, total = hashlib.sha256(), 0
    request = urllib.request.Request(download_url(tool), headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
    try:
        with opener.open(request, timeout=SOCKET_SECONDS) as response:
            host = host_of(response.geturl())
            if host not in FIXED_HOSTS + REDIRECT_HOSTS:
                raise FetchError("받은 곳이 허용 목록 밖이다(호스트 %s)" % (urllib.parse.urlsplit(response.geturl()).hostname,))
            if getattr(response, "status", 200) != 200:
                raise FetchError("HTTP 상태가 200 이 아니다(%s)" % (response.status,), retry=True)
            headers = getattr(response, "headers", None)
            encoding = headers.get("Content-Encoding") if headers is not None else None
            if encoding and encoding.strip().lower() != "identity":
                raise FetchError("응답이 압축·변환돼 있다(Content-Encoding %s) — 바이트 그대로 받지 못한다" % encoding.strip()[:20])
            length = headers.get("Content-Length") if headers is not None else None
            if length is not None and length.strip().isdigit() and int(length) != tool["bytes"]:
                raise FetchError("알려 준 크기가 잠금 값과 다르다(%s바이트, 기대 %d)" % (length.strip()[:20], tool["bytes"]))
            with open(temp, "wb") as out:
                for block in iter(lambda: response.read(CHUNK), b""):
                    total += len(block)
                    if total > tool["bytes"]:
                        raise FetchError("받은 크기가 잠금 값(%d바이트)보다 크다" % tool["bytes"])
                    if deadline is not None and clock() > deadline:
                        raise FetchError("전체 시간 상한(%d초)을 넘었다" % TOTAL_SECONDS)
                    digest.update(block)
                    out.write(block)
        if total != tool["bytes"]:
            raise FetchError("받은 크기가 잠금 값과 다르다(%d바이트, 기대 %d)" % (total, tool["bytes"]), retry=True)
        if digest.hexdigest() != tool["sha256"]:
            raise FetchError("받은 파일의 SHA-256 이 잠금 값과 다르다")
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def fetch_with_retries(tool, target, opener, *, sleep=time.sleep, clock=time.monotonic, say=print, deadline=None):
    """일시적인 네트워크 오류·서버 5xx·크기 부족만 다시 한다(최대 ATTEMPTS 번). 해시 불일치·허용 밖 호스트·크기 초과·시간 상한은 바로 실패한다 → 시도 횟수."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            fetch_file(tool, target, opener, clock=clock, deadline=deadline)
            return attempt
        except FetchError as error:
            retry, reason = error.retry, str(error)
        except urllib.error.HTTPError as error:
            retry, reason = error.code in (408, 429) or error.code >= 500, "HTTP %d" % error.code
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            retry, reason = True, type(error).__name__
        if deadline is not None and clock() > deadline:
            retry = False
        if not retry or attempt == ATTEMPTS:
            raise FetchError("%s: %s" % (tool["key"], reason))
        say("[도구] %s 받기 실패(%s) — %d초 뒤 다시 한다(%d/%d)" % (tool["key"], reason, WAITS[attempt - 1], attempt, ATTEMPTS))
        sleep(WAITS[attempt - 1])
    raise FetchError(tool["key"] + ": 받지 못했다")


def main(argv=None, *, opener=None, sleep=time.sleep, clock=time.monotonic):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", required=True, help="도구를 둘 폴더")
    parser.add_argument("--lock", default=DEFAULT_LOCK)
    parser.add_argument("--check-only", action="store_true", help="받지 않고 이미 있는 파일이 잠금 값과 같은지만 본다")
    args = parser.parse_args(argv)
    try:
        with open(args.lock, "rb") as handle:
            lock = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError) as error:
        print("[도구] 잠금 파일을 읽지 못했다(%s)" % type(error).__name__, file=sys.stderr)
        return 2
    problems = lock_problems(lock)
    if problems:
        print("[도구] 잠금 파일 점검 실패: " + " / ".join(problems), file=sys.stderr)
        return 2
    opener = opener or urllib.request.build_opener(GuardedRedirect())
    deadline = clock() + TOTAL_SECONDS
    log = []
    try:
        for tool in lock["tools"]:
            if tool["kind"] != "direct":
                print("[도구] %s 는 pip 로 받는 도구라 여기서 받지 않는다(run_spike.py install-tools 가 받는다)" % tool["key"])
                continue
            target = os.path.join(args.dest, tool["file"])
            if not check_file(target, tool):
                print("[도구] %s %s바이트 — 이미 있고 SHA-256 이 같다" % (tool["key"], format(tool["bytes"], ",")))
                log.append({"key": tool["key"], "bytes": tool["bytes"], "sha256_ok": True, "seconds": 0.0, "attempts": 0, "reused": True})
                continue
            if args.check_only:
                raise FetchError("%s: 없거나 잠금 값과 다르다" % tool["key"])
            print("[도구] %s 받는 중 — 호스트 %s, 버전 %s, 기대 %s바이트" % (tool["key"], tool["host"], tool["version"], format(tool["bytes"], ",")))
            began = clock()
            attempts = fetch_with_retries(tool, target, opener, sleep=sleep, clock=clock, deadline=deadline)
            seconds = round(clock() - began, 1)
            print("[도구] %s %s바이트 — 받았고 크기와 SHA-256 이 같다(%s초, %d번째 시도)" % (tool["key"], format(tool["bytes"], ","), seconds, attempts))
            log.append({"key": tool["key"], "bytes": tool["bytes"], "sha256_ok": True, "seconds": seconds, "attempts": attempts, "reused": False})
    except FetchError as error:
        print("[도구] 실패 — " + str(error), file=sys.stderr)
        return 1
    if not args.check_only:
        os.makedirs(args.dest, exist_ok=True)
        with open(os.path.join(args.dest, LOG_NAME), "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "fetched": log}, handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
