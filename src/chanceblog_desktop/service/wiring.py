"""어댑터를 꽂는 **유일한 곳**(NET 설계서 3.11.3 E4, D-733) — 켜진 스위치에 해당하는 종류만 꽂는다.

`service/external.py` 의 등록부(`register`)를 부르는 코드는 `src/` 에 **이 파일 한 곳**뿐이고, 그 호출은 모두 스위치 읽는 함수(`capabilities.…_enabled()`)의 `if` 안에 있다(시험 `test_external_write_gate` 와 `test_net_allowlist` 가 소스에서 확인한다).
그래서 스위치가 꺼진 빌드에는 어떤 어댑터도 꽂히지 않고(`registered_kinds() == ()`), 접속 클라이언트 객체는 어댑터 공장 안에서만 만들어지므로 **기본 빌드에서는 한 번도 만들어지지 않는다**.
종류와 스위치의 짝: `pages_git` ↔ 외부 쓰기 + git 가지 올리기(`pages_branch_push_enabled`) · `blogger` ↔ Blogger 로그인·읽기(`net_blogger_oauth_enabled`) · `naver_publish` ↔ 스위치 없음(늘 꽂지 않는다).

`pages_git` 의 공장은 PUBPR 갈래의 `make_branch_backend` 다(새 가지에만 올리는 `GitBranchBackend` — main 으로 올리는 길은 없다). `blogger` 는 아직 자리표시자다 — **BLOGGER 갈래가 자기 줄의 공장 이름만 바꾼다**.
자리표시자는 스위치를 잘못 켜도 안전하게 아무것도 열지 않는다(`blogger` 는 부르는 곳이 아직 없다).
"""
from __future__ import annotations

from .. import capabilities
from . import external


def make_branch_backend(*, git=None, expected_origin=None, fetcher=None, sleep=None, monotonic=None):
    """`pages_git` 공장(PUBPR) — 새 가지에만 올리는 어댑터 `GitBranchBackend` 를 만든다. 스위치가 켜졌을 때만 이 공장이 불린다(`register_enabled`). `git` 을 주지 않았거나 모든 호출을 거절하는 기본 실행기(`refusing_git`)면 진짜 실행기를 쓴다
    (켜진 빌드의 연결은 앱이 기본값으로 만들므로) — 시험이 가짜 실행기를 주면 그것을 그대로 쓴다. 이 모듈을 가져와도 접속 코드는 불리지 않는다(어댑터 공장 안에서만 가져온다)."""
    from ..publish import gitrepo
    from .backend import GitBranchBackend
    runner = gitrepo.run_git if git is None or git is external.refusing_git else git
    return GitBranchBackend(git=runner, expected_origin=expected_origin if expected_origin is not None else gitrepo.EXPECTED_ORIGIN, fetcher=fetcher, sleep=sleep, monotonic=monotonic)


def _blogger_placeholder(**parts):
    """`blogger` 자리표시자 — 이 어댑터를 부르는 코드가 아직 없다. BLOGGER 갈래가 진짜 공장으로 바꾼다."""
    return None


def register_enabled():
    """켜진 스위치에 해당하는 어댑터 종류를 꽂는다 → 지금 꽂힌 종류들. **더하기만 한다**(이미 꽂힌 것을 빼거나 덮어쓰지 않는다 — 시험이 `external.registered` 로 꽂은 것을 지우지 않게)."""
    if capabilities.external_write_enabled() and capabilities.pages_branch_push_enabled():
        if external.KIND_PAGES_GIT not in external.registered_kinds():
            external.register(external.KIND_PAGES_GIT, make_branch_backend)
    if capabilities.net_blogger_oauth_enabled():
        if external.KIND_BLOGGER not in external.registered_kinds():
            external.register(external.KIND_BLOGGER, _blogger_placeholder)
    return external.registered_kinds()


__all__ = ["make_branch_backend", "register_enabled"]
