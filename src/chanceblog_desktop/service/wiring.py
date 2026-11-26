"""어댑터를 꽂는 **유일한 곳**(NET 설계서 3.11.3 E4, D-733) — 켜진 스위치에 해당하는 종류만 꽂는다.

`service/external.py` 의 등록부(`register`)를 부르는 코드는 `src/` 에 **이 파일 한 곳**뿐이고, 그 호출은 모두 스위치 읽는 함수(`capabilities.…_enabled()`)의 `if` 안에 있다(시험 `test_external_write_gate` 와 `test_net_allowlist` 가 소스에서 확인한다).
그래서 스위치가 꺼진 빌드에는 어떤 어댑터도 꽂히지 않고(`registered_kinds() == ()`), 접속 클라이언트 객체는 어댑터 공장 안에서만 만들어지므로 **기본 빌드에서는 한 번도 만들어지지 않는다**.
종류와 스위치의 짝: `pages_git` ↔ 외부 쓰기 + git 가지 올리기(`pages_branch_push_enabled`) · `blogger` ↔ Blogger 로그인·읽기(`net_blogger_oauth_enabled`) · `update` ↔ 업데이트 확인·내려받기(`net_update_check_enabled`, UPDATE 갈래) · `naver_publish` ↔ 스위치 없음(늘 꽂지 않는다).

지금(NET 갈래)은 진짜 어댑터 공장이 아직 없다. 아래 두 `_…_placeholder` 가 그 자리를 채운다 — **PUBPR·BLOGGER 갈래가 자기 줄의 공장 이름만 바꾼다**(예: `external.register(external.KIND_PAGES_GIT, make_branch_backend)`).
자리표시자는 스위치를 잘못 켜도 안전하게 아무것도 열지 않는다(`pages_git` 은 파일만 읽는 `LocalOnlyBackend` 와 같은 일을 하고, `blogger` 는 부르는 곳이 아직 없다).
덧붙임(BLOGGER 갈래, D-774): `blogger` 의 자리표시자는 진짜 공장 `_blogger_factory`(→ `service/blogger_flow.py::make_blogger_adapter`)로 바뀌었다 — 위 문장의 '`blogger` 는 부르는 곳이 아직 없다' 는 옛 상태다.
"""
from __future__ import annotations

from .. import capabilities
from . import external


def _pages_placeholder(*, git=None, expected_origin=None, fetcher=None, sleep=None, monotonic=None):
    """`pages_git` 자리표시자 — 아무것도 꽂지 않았을 때와 같은 일을 한다(파일만 읽고 쓰기·접속은 거절). PUBPR 갈래가 진짜 공장으로 바꾼다."""
    return external.LocalOnlyBackend(expected_origin=expected_origin) if expected_origin is not None else external.LocalOnlyBackend()


def _blogger_factory(**parts):
    """`blogger` 어댑터 공장 — 진짜 공장(`service/blogger_flow.py::make_blogger_adapter`)을 **부를 때** 불러온다(스위치가 꺼진 빌드는 이 모듈을 가져오지도 않는다)."""
    from . import blogger_flow
    return blogger_flow.make_blogger_adapter(**parts)


def _update_factory(*, version, usage=None):
    """`update` 어댑터 공장 — 업데이트 확인·내려받기가 쓰는 접속 클라이언트(`NetClient`)를 만드는 **유일한 곳**이다(NT-18). `NET_UPDATE_CHECK` 가 켜져 꽂혔을 때만 불리고, 접속 틀은 이 함수 안에서 처음 불러온다."""
    from ..net.client import NetClient
    return NetClient(version=version, usage=usage)


def register_enabled():
    """켜진 스위치에 해당하는 어댑터 종류를 꽂는다 → 지금 꽂힌 종류들. **더하기만 한다**(이미 꽂힌 것을 빼거나 덮어쓰지 않는다 — 시험이 `external.registered` 로 꽂은 것을 지우지 않게)."""
    if capabilities.external_write_enabled() and capabilities.pages_branch_push_enabled():
        if external.KIND_PAGES_GIT not in external.registered_kinds():
            external.register(external.KIND_PAGES_GIT, _pages_placeholder)
    if capabilities.net_blogger_oauth_enabled():
        if external.KIND_BLOGGER not in external.registered_kinds():
            external.register(external.KIND_BLOGGER, _blogger_factory)
    if capabilities.net_update_check_enabled():
        if external.KIND_UPDATE not in external.registered_kinds():
            external.register(external.KIND_UPDATE, _update_factory)
    return external.registered_kinds()


__all__ = ["register_enabled"]
