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

from .. import capabilities
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


def require_pages_host(url, host):
    """공개 확인이 닿는 곳은 `<소유자>.github.io` 한 곳뿐이다(NET 의 `pages_site` 용도) — 이 저장소의 `_config.yml` 이 다른 주소(사용자 지정 도메인 등)를 가리키면 앱은 그곳에 접속하지 않으므로
    끝내 안 열리는 확인을 최대 12분 기다리게 하지 않고 곧바로 이유를 알린다(글은 이미 올라가 있다 — 공개 확인만 사람이 브라우저에서 한다).
    호스트 이름이 같아도 포트(`:8443`)나 사용자 정보(`user@`)가 붙은 주소는 접속 틀(`net/`)이 접속 전에 거절하므로 같은 까닭으로 곧바로 알린다(독립 검증 S 참고 N-3 — 예전에는 호스트 이름만 견줘 그런 주소가 통과하고 vendor 확인 도구가 마감까지 되풀이했다)."""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    actual = (parts.hostname or "").lower()
    if actual != str(host).lower():
        raise AppError("CONTENT_INVALID", {"항목": "_config.yml 의 url"},
                       detail=f"공개 주소의 호스트({mask(actual)[:80] or '없음'})가 앱이 확인하는 {host} 가 아니라 앱은 접속하지 않았다 — 사용자 지정 도메인이면 공개 확인은 브라우저에서 직접 한다")
    if parts.netloc.lower() != actual:                                            # 포트·사용자 정보가 붙었다(주소 속 비밀은 글에 싣지 않는다)
        raise AppError("CONTENT_INVALID", {"항목": "_config.yml 의 url"},
                       detail=f"공개 주소({host})에 포트나 사용자 정보가 붙어 있어 앱은 접속하지 않았다 — 공개 확인은 브라우저에서 직접 한다")


def check_deployed(root, path, text, *, deadline=720, interval=10, fetcher=None, sleep=None, clock=None, now=None, token="app"):
    """올린 글의 공개 주소가 열릴 때까지 확인한다(기본 최대 12분, 대기 10초에서 시작해 2배씩). 열리면 DeployResult, 끝내 안 열리면 PAGES_DEPLOY_NOT_VISIBLE."""
    capabilities.require_external_write("올린 글의 공개 주소 확인(네트워크)")        # 외부 관문 — 이 시험 버전은 꺼져 있어 요청을 한 번도 보내지 않는다
    capabilities.require_net("pages_site", "올린 글의 공개 주소 확인")             # 둘째 문장: 좁은 스위치(NET_PAGES_SITE)도 켜져 있어야 한다 — EXTERNAL_WRITE 만으로는 열리지 않는다(NET 설계서 3.3)
    url = expected_url(root, path, text, now=now)                 # 검사·주소 계산을 먼저(여기서 막히면 기다리지 않는다)
    verifier = _verifier()
    if fetcher is None:
        from ..net.endpoints import ENDPOINTS
        from ..net.site import site_fetcher                      # 접속 틀(`ssl`·`http.client`)은 여기서 처음 불러온다 — 기본 빌드는 시작 때 불러오지 않는다(독립 검증 S 참고-3, D-739)
        require_pages_host(url, ENDPOINTS["pages_site"].host)     # 사이트 주소가 `<소유자>.github.io` 가 아니면 12분을 기다리지 않고 바로 알린다(PUBPR Q11)
        fetcher = site_fetcher(verifier.Resp)                     # vendor 도구의 `urlopen` 길(자동 이동·시스템 프록시)을 쓰지 않고 접속이 `net/` 틀을 지나게 한다(NET 설계서 F1·NT-16)
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
