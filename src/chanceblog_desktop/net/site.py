"""공개 사이트 확인용 `fetcher`(NET 설계서 F1·3.6, D-736) — vendor 확인 도구(`verify_pages_deploy`)에 **주입**해 그 도구의 접속이 이 틀을 지나게 한다.

vendor 도구는 `verify(…, fetcher=…)` 로 요청 함수를 받는다(`fetcher(url, limit=…, headers=None)` → `Resp(status, body, headers, error)`). 이 함수를 넘기면 vendor 를 한 글자도 바꾸지 않고
접속이 `NetClient`(`pages_site` 용도 — 호스트 한 곳·같은 호스트 이동 최대 2번·`cb=app` 고정 질의·시간·크기 한도)를 지나고, vendor 도구의 `urllib`·`http` 길은 앱에서 **한 번도 불리지 않는다**(시험 `test_net_allowlist`).
`Resp` 의 모양(`resp_type`)은 호출하는 쪽이 vendor 에서 가져와 넘긴다 — 이 모듈은 vendor 를 가져오지 않는다. 오류는 상태 0 + 오류 **코드 이름**(예: `NETWORK_TIMEOUT`)으로 돌려준다(예외 문장·주소는 버린다).
"""
from __future__ import annotations

from .client import NetClient
from .endpoints import ENDPOINTS, app_version
from .errors import NetError


def site_fetcher(resp_type, *, client=None):
    """vendor 의 `fetcher` 모양 함수를 만든다. `client` 를 주지 않으면 앱 버전으로 `NetClient` 를 만든다(어댑터 공장이 스위치가 켜졌을 때만 이 함수를 부른다)."""
    net = client if client is not None else NetClient(version=app_version())

    def fetch(url, limit=ENDPOINTS["pages_site"].max_response, headers=None):
        encoding = (headers or {}).get("Accept-Encoding", "identity")
        try:
            response = net.request("pages_site", "GET", url, accept_encoding=encoding, limit=limit)
        except NetError as error:
            return resp_type(0, b"", {}, error.code)
        return resp_type(response.status, response.body, response.headers, "")

    return fetch


__all__ = ["site_fetcher"]
