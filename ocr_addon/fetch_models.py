# -*- coding: utf-8 -*-
"""fetch_models.py - 빌드 전용: 모델 2파일을 models.lock.json 의 저장소·커밋·크기·SHA-256 대로 받는다(설계서 5-3·5-5 의 4단계, 결정 D-529).

앱 본체(src/)에는 내려받는 코드가 없다 — 이 파일은 추가 도구 빌드 흐름(.github/workflows/package-ocr.yml)의 한 단계에서만 돈다.
받는 곳은 Hugging Face 의 커밋 고정 주소 하나뿐이고(huggingface.co 와 그 하위, 파일을 싣는 hf.co 하위 — 리디렉션도 같은 규칙, 밖이면 그 자리에서 거절), 받은 파일은 크기와 SHA-256 이 잠금 값과
같을 때만 남긴다(다르면 지우고 실패). 비밀·토큰·계정을 쓰지 않는다. 이미 있는 파일이 잠금 값과 같으면 받지 않는다(다시 돌려도 안전).
사용: python ocr_addon/fetch_models.py --dest <폴더> [--lock models.lock.json] [--check-only]   (폴더 안에 det/inference.onnx · rec/inference.onnx 가 생긴다)
종료 코드: 0 모두 잠금 값과 같음 · 1 받기·대조 실패 · 2 잠금 파일이나 인자가 이상함.
"""
import argparse
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import build_rules as rules  # noqa: E402

ALLOWED_HOST_SUFFIXES = ("huggingface.co", "hf.co")
USER_AGENT = "chanceblog-ocr-build/1 (model files only)"
ATTEMPTS = 3
WAITS = (5, 20)
TIMEOUT = 60
CHUNK = 1 << 20
DEFAULT_LOCK = os.path.join(HERE, "models.lock.json")


class FetchError(Exception):
    def __init__(self, message, retry=False):
        super().__init__(message)
        self.retry = retry


def host_allowed(host):
    host = (host or "").lower().rstrip(".")
    return any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def download_url(source):
    """커밋 고정 주소 — 저장소·커밋·경로는 rules.lock_problems 가 모양을 확인한 값이다(`..`·물음표·샵·공백이 못 든다)."""
    return "https://huggingface.co/%s/resolve/%s/%s" % (source["repo"], source["commit"], source["path"])


class GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """리디렉션이 https 가 아니거나 허용 호스트 밖이면 따라가지 않고 멈춘다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or not host_allowed(parts.hostname):
            raise FetchError("허용 목록 밖으로 넘어가는 주소를 거절했다(호스트 %s)" % (parts.hostname,))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verified(path, entry):
    return os.path.isfile(path) and os.path.getsize(path) == entry["bytes"] and sha256_file(path) == entry["sha256"]


def fetch_file(entry, target, opener):
    """한 파일을 받아 크기·SHA-256 이 잠금 값과 같을 때만 target 으로 옮긴다. 읽는 양은 잠금 크기를 넘지 못한다(거대 응답으로 디스크를 채우지 못하게)."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temp = target + ".part"
    digest, total = hashlib.sha256(), 0
    request = urllib.request.Request(download_url(entry["source"]), headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            host = urllib.parse.urlsplit(response.geturl()).hostname
            if not host_allowed(host):
                raise FetchError("받은 곳이 허용 목록 밖이다(호스트 %s)" % (host,))
            if getattr(response, "status", 200) != 200:
                raise FetchError("HTTP 상태가 200 이 아니다(%s)" % (response.status,), retry=True)
            with open(temp, "wb") as out:
                for block in iter(lambda: response.read(CHUNK), b""):
                    total += len(block)
                    if total > entry["bytes"]:
                        raise FetchError("받은 크기가 잠금 값(%d바이트)보다 크다" % entry["bytes"])
                    digest.update(block)
                    out.write(block)
        if total != entry["bytes"]:
            raise FetchError("받은 크기가 잠금 값과 다르다(%d바이트, 기대 %d)" % (total, entry["bytes"]), retry=True)
        if digest.hexdigest() != entry["sha256"]:
            raise FetchError("받은 파일의 SHA-256 이 잠금 값과 다르다")
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def fetch_with_retries(entry, target, opener, *, sleep=time.sleep, say=print):
    """일시적인 네트워크 오류·서버 5xx·크기 부족만 다시 한다(최대 ATTEMPTS 번). 해시 불일치·허용 밖 호스트·크기 초과는 바로 실패한다."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fetch_file(entry, target, opener)
        except FetchError as error:
            retry = error.retry
            reason = str(error)
        except urllib.error.HTTPError as error:
            retry, reason = error.code in (408, 429) or error.code >= 500, "HTTP %d" % error.code
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            retry, reason = True, type(error).__name__
        if not retry or attempt == ATTEMPTS:
            raise FetchError("%s: %s" % (entry["key"], reason))
        say("[모델] %s 받기 실패(%s) — %d초 뒤 다시 한다(%d/%d)" % (entry["key"], reason, WAITS[attempt - 1], attempt, ATTEMPTS))
        sleep(WAITS[attempt - 1])


def target_of(dest, key):
    """잠금 키(models/det/inference.onnx)를 받는 폴더 안 경로(dest/det/inference.onnx)로 — 빌드의 --models-dir 가 같은 모양을 읽는다."""
    if not key.startswith("models/"):
        raise FetchError("모델이 아닌 키다: " + key)
    return os.path.join(dest, *key.split("/")[1:])


def main(argv=None, *, opener=None, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", required=True, help="모델을 둘 폴더(안에 det·rec 폴더가 생긴다)")
    parser.add_argument("--lock", default=DEFAULT_LOCK)
    parser.add_argument("--check-only", action="store_true", help="받지 않고 이미 있는 파일이 잠금 값과 같은지만 본다")
    args = parser.parse_args(argv)
    try:
        with open(args.lock, "rb") as handle:
            lock = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError) as error:
        print("[모델] 잠금 파일을 읽지 못했다(%s)" % type(error).__name__, file=sys.stderr)
        return 2
    problems = rules.lock_problems(lock)
    if problems:
        print("[모델] 잠금 파일 점검 실패: " + " / ".join(problems), file=sys.stderr)
        return 2
    opener = opener or urllib.request.build_opener(GuardedRedirect())
    try:
        for entry in lock["files"]:
            if entry["source"]["kind"] != "huggingface":
                continue
            target = target_of(args.dest, entry["key"])
            if verified(target, entry):
                print("[모델] %s %s바이트 — 이미 있고 SHA-256 이 같다" % (entry["key"], format(entry["bytes"], ",")))
                continue
            if args.check_only:
                raise FetchError("%s: 없거나 잠금 값과 다르다" % entry["key"])
            print("[모델] %s 받는 중 — 저장소 %s 커밋 %s" % (entry["key"], entry["source"]["repo"], entry["source"]["commit"][:12]))
            fetch_with_retries(entry, target, opener, sleep=sleep)
            print("[모델] %s %s바이트 — 받았고 SHA-256 이 같다" % (entry["key"], format(entry["bytes"], ",")))
    except FetchError as error:
        print("[모델] 실패 — " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
