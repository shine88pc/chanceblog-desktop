"""배포 뒤, 올린 글이 공개 주소에서 실제로 열리는지 확인한다(docs/ARCHITECTURE.md §3 '배포 확인').

chanceblog 의 배포 워크플로가 쓰는 확인 코드(`scripts/verify_pages_deploy.py`, `vendor/` 에 원본 그대로)에 맡긴다 — 공개 CDN 이 '없음(404)' 도 최대 18분쯤
보관해서 같은 주소를 반복 요청하면 계속 404 를 받는다는 점(요청 모양을 바꿔 피한다)·`published: false`·미래 날짜·Jekyll 주소(permalink) 계산 같은 사정이
이미 반영돼 있다. 이 모듈은 그 코드가 '내가 올린 글 하나'만 확인하도록 임시 사이트 폴더(`_config.yml` + 그 글)를 만들어 건네고, 연결한 저장소는 건드리지 않는다.

`expected_url` 은 네트워크 없이 글의 공개 주소를 계산하고(상태 PUBLISHED 에 기록할 주소), `check_deployed` 는 그 주소가 열릴 때까지(기본 최대 12분) 기다린다.
기다리는 동안 이 함수가 멈춰 있으므로 화면과 다른 작업 줄(스레드)에서 부른다. 시험에서는 `fetcher`·`sleep`·`clock` 을 바꿔 끼워 네트워크와 대기 없이 돈다.
"""
from __future__ import annotations

import contextlib
import io
import re
import tempfile
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core import load_vendored_script
from ..errors import AppError
from ..security.mask import mask
from .pages import check_post

_Post = namedtuple("_Post", "path text")
# `_config.yml` 맨 앞 칸(들여쓰기 없음)의 url·baseurl 한 줄: 큰따옴표·작은따옴표·따옴표 없음, 뒤의 주석 허용
_CONFIG_LINE = re.compile(r"""^(?P<key>url|baseurl)[ \t]*:[ \t]*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^\s#]*))[ \t]*(?:\#.*)?$""")


@dataclass(frozen=True)
class DeployResult:
    url: str          # 열리는 것을 확인한 공개 주소
    summary: str      # 확인 기록(시도 횟수·요청 모양·경고) — 마크다운


def _verifier():
    return load_vendored_script("verify_pages_deploy")


def site_base(root):
    """연결한 저장소의 `_config.yml` 로 사이트 주소(`https://…/<baseurl>/`)를 만든다. 읽을 수 없거나 https 주소가 아니면 AppError."""
    try:
        text = (Path(root) / "_config.yml").read_bytes().decode("utf-8", "replace")
    except OSError:
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="_config.yml 을 읽을 수 없다") from None
    found = {}
    for line in text.lstrip("\ufeff").splitlines():
        match = _CONFIG_LINE.match(line)
        if match and match["key"] not in found:
            found[match["key"]] = next(value for value in (match["dq"], match["sq"], match["bare"]) if value is not None)
    url = found.get("url", "").strip().rstrip("/")
    baseurl = found.get("baseurl", "").strip().strip("/")
    base = f"{url}/{baseurl}/" if baseurl else f"{url}/"
    if not _verifier().valid_base(base):
        raise AppError("CONTENT_INVALID", {"항목": "_config.yml 의 url"}, detail=f"https 사이트 주소가 아니다: {mask(base)[:120]}")
    return base


def _write_site(site, root, path, text):
    """임시 사이트 폴더: 연결한 저장소의 `_config.yml` 복사본 + 확인할 글 하나."""
    site = Path(site)
    try:
        (site / "_config.yml").write_bytes((Path(root) / "_config.yml").read_bytes())
    except OSError:
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="_config.yml 을 읽을 수 없다") from None
    target = site / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def _selection(verifier, site, now):
    config = verifier.read_site_config(site)
    tz = verifier.site_timezone(config)
    selection = verifier.select_newest(site, now or datetime.now(timezone.utc), tz)
    if not selection.posts:
        why = "; ".join(reason for _post, reason in selection.skipped) or "글을 찾지 못했다"
        raise AppError("CONTENT_INVALID", {"항목": "공개 설정"}, detail=f"이 글은 사이트에 공개되지 않는다: {why}")
    return config, tz, selection.posts[0]


def expected_url(root, path, text, *, now=None):
    """글의 공개 주소(Jekyll permalink 로 계산, 네트워크 없음). 공개되지 않는 글(published: false·미래 날짜)이거나 계산할 수 없으면 AppError."""
    check_post(_Post(path, text))
    verifier = _verifier()
    base = site_base(root)
    with tempfile.TemporaryDirectory() as tmp:
        _write_site(tmp, root, path, text)
        config, tz, post = _selection(verifier, tmp, now)
        url, why = verifier.expected_url(base, post, config, tz)
    if url is None:
        raise AppError("CONTENT_INVALID", {"항목": "발행 주소"}, detail=f"공개 주소를 계산할 수 없다: {mask(why)[:200]}")
    return url


def check_deployed(root, path, text, *, deadline=720, interval=10, fetcher=None, sleep=None, clock=None, now=None, token="app"):
    """올린 글의 공개 주소가 열릴 때까지 확인한다(기본 최대 12분, 대기 10초에서 시작해 2배씩). 열리면 DeployResult, 끝내 안 열리면 PAGES_DEPLOY_NOT_VISIBLE."""
    url = expected_url(root, path, text, now=now)                 # 검사·주소 계산을 먼저(여기서 막히면 기다리지 않는다)
    verifier = _verifier()
    base = site_base(root)
    log = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        _write_site(tmp, root, path, text)
        try:
            with contextlib.redirect_stdout(log):               # 확인 코드가 진행 상황을 print 로 낸다 — 앱의 화면·콘솔에 섞이지 않게
                result = verifier.verify(base, tmp, deadline, interval, fetcher=fetcher, sleep=sleep, clock=clock, now=now, token=token)
        except verifier.ConfigError as error:
            raise AppError("CONTENT_INVALID", {"항목": "배포 확인 설정"}, detail=mask(str(error))[:300]) from None
    if result.skipped:
        raise AppError("CONTENT_INVALID", {"항목": "공개 설정"}, detail="이 글은 사이트에 공개되지 않아 확인할 수 없다")
    if not result.ok:
        raise AppError("PAGES_DEPLOY_NOT_VISIBLE", detail=" ".join(mask(result.summary).split())[-600:])
    return DeployResult(url, result.summary)
