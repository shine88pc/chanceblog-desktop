"""고정 호스트·길·머리글·한도 표 — 접속 틀의 **소스 상수 표**(NET 설계서 3.6·3.7·3.8, D-724).

호스트는 정확히 일치(ASCII·소문자·점 없음·포트 없음 — 와일드카드·하위 도메인·설정으로 더하기 없음)해야 하고, 길은 정해 둔 모양(정규식 전체 일치)이어야 하며, 질의는 길마다 **고정된 쌍**이어야 한다.
표 밖의 요청은 접속하기 **전에** 거절된다(`client.py` 의 3단계). 이 표를 바꾸는 것은 코드 변경이다 — 시험(`test_net_client.HostTableTest`)이 표가 설계서와 정확히 같음을 지킨다.

용도(use) 이름은 `capabilities.NET_USES` 와 같은 이름이다. `pages_branch` 는 git 이 접속하므로 이 표에 없다. `blogger_read` 와 `blogger_draft` 는 같은 호스트의 다른 방법이라 표가 둘이다.
업데이트 확인(`update_check`)의 호스트·길은 UPDATE 설계가 정한다 — 이 표의 줄은 UPDATE 갈래가 확정·확장하는 **자리표시자**다(이동 호스트가 비어 있어 이동은 모두 거절된다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from ..publish.gitrepo import EXPECTED_OWNER

KIB = 1024
MIB = 1024 * 1024
# 시간·크기 한도(3.7) — vendor 확인 도구의 `REQUEST_TIMEOUT`(15)·`REQUEST_TOTAL`(30)·`MAX_BYTES`(20 MiB)와 같은 값이다
CONNECT_TIMEOUT = 10.0            # 이름 풀이 + 연결 + 보안 확인(핸드셰이크)
IO_TIMEOUT = 15.0                 # 소켓 작업(보내기·읽기) 한 번
TOTAL_TIMEOUT = 30.0              # 요청 하나의 총 시간 — 마감 감시가 강제한다(소켓 제한은 작업마다라 찔끔 보내는 서버가 붙잡을 수 있다)
MAX_HEADER_BYTES = 64 * KIB       # 받은 머리글 전체의 상한(`http.client` 의 줄 한도·개수 100 위에 더한 우리 쪽 한도)
MAX_URL_CHARS = 500               # 요청 주소(길 + 질의) 길이 상한
MAX_BEARER_CHARS = 4096           # 접근 토큰 글자 수 상한(모양은 영문·숫자와 점·밑줄·더하기·빗금·등호·붙임표 정도 — `client.py` 의 `_BEARER`)
USER_AGENT_PREFIX = "ChanceBlogDesktop/"   # 앱에서 나가는 유일한 값은 이 뒤의 버전 번호다(업데이트 확인의 약속)

NUMBER = r"[0-9]{1,25}"           # 블로그·글 번호 — 숫자만
CACHE_BUSTER = re.compile(r"app(?:-[0-9]{1,3})?")      # 공개 사이트 질의 `cb` 의 값 — 설계서는 `app` 고정이었지만 vendor 확인 도구가 시도마다 `app-<시도 번호>` 로 바꿔 보낸다(실측: `f"{token}-{tries}"`)
# 공개 사이트 글 주소(허용 문자 집합): 앞 `/` 로 시작, 길이 500 이하, 퍼센트 부호는 `%XX`, `..` 구간·`%2e`·`%2f`·`%5c`·`%00` 금지(`//`·`./` 는 vendor 확인 도구의 요청 모양이라 허용)
SITE_PATH = re.compile(r"/(?!(?:.*/)?\.\.(?:/|$))(?!.*%(?:2[eEfF]|5[cC]|00))(?:%[0-9A-Fa-f]{2}|[A-Za-z0-9._~+/-]){0,498}")


@dataclass(frozen=True)
class Route:
    """허용하는 요청 모양 하나 — 방법 + 길(정규식 전체 일치) + 고정 질의."""
    method: str
    path: object                     # 정확히 같아야 하는 글(고정 길) 또는 전체 일치하는 정규식(번호가 든 길)
    shown: str                       # 접속 기록에 적는 '길 이름'(숫자 ID 는 `<번호>`) — 요청 값이 아니라 표의 글이다
    query: tuple = ()                # 정확히 이 (키, 값) 쌍들만 허용한다(없으면 질의 없음). 값은 글(정확히 같아야 함)이거나 컴파일된 정규식(전체 일치)이다
    bearer: bool = False             # `Authorization: Bearer` 를 붙여도 되는 길
    content_type: str = ""           # 본문이 있는 길의 고정 Content-Type
    max_body: int = 0                # 보내는 본문의 상한(바이트) — 0 이면 본문 없음
    download: bool = False           # `request_to_file` 로 내려받아도 되는 길

    def matches(self, path):
        """요청 길이 이 길과 전체가 같은가(고정 길은 글이 정확히 같고, 모양이 있는 길은 정규식 전체 일치)."""
        return path == self.path if isinstance(self.path, str) else self.path.fullmatch(path) is not None

    def path_text(self):
        return self.path if isinstance(self.path, str) else self.path.pattern


@dataclass(frozen=True)
class Endpoint:
    """용도 하나의 접속 표 — 호스트 한 곳과 허용하는 길들, 머리글·크기·시간·이동 규칙."""
    use: str
    host: str
    routes: tuple
    accept: str                      # 고정 Accept 값
    max_response: int                # 받는 본문 상한(바이트)
    label: str                       # 사용자 문구의 「작업」 이름
    max_redirects: int = 0           # 0 = 이동(3xx) 거절(기본) — 열린 곳이 눈에 보이게
    redirect_hosts: tuple = ()       # 이동을 허용하는 **다른** 호스트(정확히 일치). 같은 호스트 이동은 max_redirects 가 0 이 아닐 때만
    cache_control: str = ""          # 붙일 Cache-Control 값(없으면 붙이지 않는다)
    accept_encodings: tuple = ("identity",)   # 허용하는 Accept-Encoding — identity 밖의 값은 본문을 읽지 않는(limit 0) 요청에서만
    total_timeout: float = TOTAL_TIMEOUT      # 요청 하나의 총 시간
    download_timeout: float = 0.0    # `request_to_file` 의 총 시간(0 이면 이 용도는 내려받기를 하지 않는다)
    max_download: int = 0             # `request_to_file` 로 받을 수 있는 파일 크기 상한(바이트)
    keep_headers: tuple = ()          # 기본으로 고르는 머리글(retry-after·content-type·content-length·x-ratelimit-*) 말고 이 용도가 더 고르는 응답 머리글(소문자) — 쓸 것만 고른다
    uncounted_statuses: tuple = (400, 422, 429)   # 연속 실패 계수(쿨다운)에 넣지 않는 HTTP 상태 — 사용자 실수(400·422)와 한도 안내(429). 공개 사이트 확인은 '아직 안 열렸다'(404)가 기다리는 동안의 정상 답이라 더 뺀다


def _routes(*items):
    return tuple(items)


_PAGES_HOST = f"{EXPECTED_OWNER.lower()}.github.io"        # 글 저장소 소유자 상수 하나에서 만든다(연결한 저장소 확인용 `EXPECTED_ORIGIN` 과 같은 상수 — 시험이 둘이 어긋나지 않음을 확인)
_BLOGGER_POST = f"/blogger/v3/blogs/{NUMBER}/posts"

ENDPOINTS = {
    # 업데이트 확인(읽기, 사용자가 누를 때만) — UPDATE 설계가 확정한다. 지금은 정적 매니페스트 주소 한 모양(GET, 질의 없음)이고 이동은 모두 거절한다.
    "update_check": Endpoint(
        use="update_check", host="github.com", accept="application/json", max_response=1 * MIB, label="업데이트 확인",
        routes=_routes(Route("GET", re.compile(r"/[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}/releases/latest/download/[A-Za-z0-9._-]{1,100}"), "/(릴리스 최신 자산)")),
    ),
    # 올린 글의 공개 주소 확인(읽기) — 호스트 한 곳(소유자의 사이트), 같은 호스트 이동 최대 2번, `cb=app` 고정 질의, `Cache-Control: no-cache`(vendor 확인 도구와 같은 요청 모양)
    "pages_site": Endpoint(
        use="pages_site", host=_PAGES_HOST, accept="*/*", max_response=20 * MIB, label="공개 주소 확인", max_redirects=2, cache_control="no-cache",
        accept_encodings=("identity", "gzip", "deflate"), keep_headers=("age", "last-modified", "cache-control", "x-cache"),           # vendor 확인 도구가 CDN 상태를 읽는 진단 머리글 넷
        uncounted_statuses=(400, 404, 422, 429),                                                                                      # 글이 열릴 때까지 404 가 이어지는 것은 정상이다 — 쿨다운에 세지 않는다(세면 12분 기다림 도중 5분을 쉬어 버린다)
        routes=_routes(Route("GET", SITE_PATH, "/(공개 사이트)", query=(("cb", CACHE_BUSTER),))),
    ),
    # Blogger 로그인 서버 — 토큰 받기·갱신·취소(양식 인코딩 본문 4 KiB 이하)
    "blogger_oauth": Endpoint(
        use="blogger_oauth", host="oauth2.googleapis.com", accept="application/json", max_response=1 * MIB, label="Blogger 로그인",
        routes=_routes(Route("POST", "/token", "/token", content_type="application/x-www-form-urlencoded", max_body=4 * KIB),
                       Route("POST", "/revoke", "/revoke", content_type="application/x-www-form-urlencoded", max_body=4 * KIB)),
    ),
    # Blogger API 읽기 — 블로그 확인(A)·같은 제목 초안 찾기(C)·초안인지 확인(D)
    "blogger_read": Endpoint(
        use="blogger_read", host="www.googleapis.com", accept="application/json", max_response=2 * MIB, label="Blogger 읽기",
        routes=_routes(Route("GET", re.compile(rf"/blogger/v3/blogs/{NUMBER}"), "/blogger/v3/blogs/<번호>", bearer=True),
                       Route("GET", re.compile(_BLOGGER_POST), "/blogger/v3/blogs/<번호>/posts", bearer=True,
                             query=(("status", "DRAFT"), ("orderBy", "UPDATED"), ("maxResults", "5"), ("fetchBodies", "false"), ("view", "ADMIN"))),
                       Route("GET", re.compile(rf"{_BLOGGER_POST}/{NUMBER}"), "/blogger/v3/blogs/<번호>/posts/<번호>", bearer=True, query=(("view", "ADMIN"),))),
    ),
    # Blogger 초안 저장 — 쓰기 한 가지(`isDraft=true` 고정 질의, JSON 본문 1 MiB 이하)
    "blogger_draft": Endpoint(
        use="blogger_draft", host="www.googleapis.com", accept="application/json", max_response=2 * MIB, label="Blogger 초안 저장",
        routes=_routes(Route("POST", re.compile(_BLOGGER_POST), "/blogger/v3/blogs/<번호>/posts", bearer=True, query=(("isDraft", "true"),),
                             content_type="application/json; charset=UTF-8", max_body=1 * MIB)),
    ),
}

HOST_PATTERN = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")      # 끝의 점·포트·사용자 정보·비 ASCII·대문자 없음


def valid_host(host):
    """표에 적을 수 있는 호스트 모양인가(ASCII 소문자 이름 · 점으로 나뉜 둘 이상의 토막 · 숫자 IP 아님)."""
    if not isinstance(host, str) or not host.isascii() or HOST_PATTERN.fullmatch(host) is None:
        return False
    return not all(part.isdigit() for part in host.split("."))


def table_problems(table=None):
    """표가 규칙을 지키는지 본다 → 어긴 곳의 글 목록(없으면 빈 목록). 시험이 진짜 표와 합성한 나쁜 표 둘 다에 쓴다."""
    problems = []
    for key, endpoint in (ENDPOINTS if table is None else table).items():
        if key != endpoint.use:
            problems.append(f"{key}: 용도 이름이 표 키와 다르다")
        for host in (endpoint.host,) + tuple(endpoint.redirect_hosts):
            if not valid_host(host):
                problems.append(f"{key}: 호스트 모양이 틀리다")
        if not endpoint.routes:
            problems.append(f"{key}: 허용하는 길이 없다")
        if endpoint.max_redirects < 0 or endpoint.max_redirects > 3:
            problems.append(f"{key}: 이동 횟수 한도가 틀리다")
        if endpoint.redirect_hosts and endpoint.max_redirects == 0:
            problems.append(f"{key}: 이동 호스트가 있는데 이동을 허용하지 않는다")
        if endpoint.max_response <= 0 or endpoint.total_timeout <= 0 or endpoint.total_timeout > 600:
            problems.append(f"{key}: 크기·시간 한도가 틀리다")
        if not all(isinstance(code, int) and 400 <= code <= 499 for code in endpoint.uncounted_statuses) or not {400, 422, 429} <= set(endpoint.uncounted_statuses):
            problems.append(f"{key}: 계수에서 빼는 상태가 틀리다(400·422·429 는 늘 빠지고 4xx 만 더할 수 있다)")
        if "identity" not in endpoint.accept_encodings:
            problems.append(f"{key}: identity 가 없다")
        for route in endpoint.routes:
            if any(not isinstance(key, str) or not (isinstance(value, str) or hasattr(value, "fullmatch")) for key, value in route.query):
                problems.append(f"{key}: 질의 칸의 모양이 틀리다")
            if route.method not in ("GET", "POST"):
                problems.append(f"{key}: 허용하지 않는 방법 {route.method}")
            if route.method == "GET" and (route.max_body or route.content_type):
                problems.append(f"{key}: GET 에 본문 칸이 있다")
            if route.method == "POST" and not (route.max_body and route.content_type):
                problems.append(f"{key}: POST 에 본문 한도·종류가 없다")
            if route.bearer and endpoint.host.endswith(".github.io"):
                problems.append(f"{key}: 공개 사이트에는 토큰을 붙이지 않는다")
            if not route.path_text().startswith("/"):
                problems.append(f"{key}: 길 모양이 / 로 시작하지 않는다")
    return problems


def url_for(use, method, path):
    """표의 길 모양에 맞는 요청 주소를 만든다(질의는 그 길의 고정 쌍) — 어댑터가 주소를 손으로 이어 붙이지 않게 하는 도우미. 표에 없는 길이면 KeyError."""
    endpoint = ENDPOINTS[use]
    for route in endpoint.routes:
        if route.method == method and route.matches(path):
            if any(not isinstance(value, str) for _key, value in route.query):
                raise KeyError(use)                                  # 값이 정규식인 길(공개 사이트)은 호출하는 쪽이 질의를 정한다
            return f"https://{endpoint.host}{path}" + ("?" + urlencode(route.query) if route.query else "")
    raise KeyError(use)


_NUMBER = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]{0,30})?")      # `ui/core/version.py` 의 번호 모양과 같다


def app_version():
    """앱 버전 번호(저장소 또는 묶음 폴더 맨 위의 `VERSION` 파일) → 읽지 못하거나 모양이 번호가 아니면 `0.0.0`. 요청의 `User-Agent` 에 실리는 유일한 값이다(읽기만 한다)."""
    try:
        text = (Path(__file__).resolve().parents[3] / "VERSION").read_text(encoding="utf-8").lstrip(chr(0xFEFF)).strip()
    except OSError:
        return "0.0.0"
    return text if _NUMBER.fullmatch(text) else "0.0.0"


def user_agent(version):
    """앱에서 나가는 `User-Agent` — `ChanceBlogDesktop/<버전>` 뿐이다(버전 번호가 앱에서 나가는 유일한 값)."""
    return USER_AGENT_PREFIX + str(version)


__all__ = ["CACHE_BUSTER", "CONNECT_TIMEOUT", "ENDPOINTS", "Endpoint", "IO_TIMEOUT", "MAX_BEARER_CHARS", "MAX_HEADER_BYTES", "MAX_URL_CHARS", "Route", "SITE_PATH", "TOTAL_TIMEOUT", "USER_AGENT_PREFIX", "app_version", "table_problems", "url_for", "user_agent", "valid_host"]
