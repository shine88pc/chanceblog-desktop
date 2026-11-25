"""Blogger 시험 도우미(시험이 아니다 — BLOGGER 설계서 6.1·6.3, 결정 D-770) — 가짜 구글 서버와 접속 틀의 가짜 전송기.

**가짜 서버는 요청 모양을 엄격히 검사한다**: 앱이 보낼 수 있는 요청은 여섯 모양(`SHAPES` — 이 파일이 **독립으로** 적어 둔 표이고 생산 표(`net/endpoints.py`)를 읽어 오지 않는다)뿐이고,
방법·호스트·길·질의·본문 종류·머리글(토큰 서버에는 `Authorization` 이 없고 API 에는 Bearer 가 있다)이 하나라도 다르면 400 으로 답하고 `violations` 에 적는다 — 시험이 `violations == []` 를 단언하므로 앱이 규칙을 어기면 빨개진다.
소켓은 한 번도 열리지 않는다(접속 틀의 `_dial` 자리에 끼운다).

가짜 값은 모두 `CANARY_` 로 시작하는 **조립한 글**이다(구글 토큰 모양 `ya29.`·`1//0`·`GOCSPX-` 를 실행 때 이어 붙여 저장소 비밀 검사에 걸리지 않게 한다).
"""
import base64
import contextlib
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import net_support as ns  # noqa: E402

CLIENT_ID = "123456789012-" + "canary" + "clientid0042" + ".apps.example"
CLIENT_SECRET = "GOCSPX-" + "CANARY_" + "SECRET_" + "abcdefghijkl"
REFRESH = "1//0" + "CANARY_" + "REFRESH_" + "abcdefghijklmnopqrstuvwxyz"
CODE = "4/0" + "CANARY_" + "CODE_" + "abcdefghijklmnopqrstuvwxyz"
BLOG_EN = "1234567890123456789"
BLOG_KO = "9876543210987654321"
SCOPE = "https://www.googleapis.com/auth/blogger"
SLOW_SECONDS = 25.0

OAUTH_HOST = "oauth2.googleapis.com"
API_HOST = "www.googleapis.com"
NUMBER = r"[0-9]{1,25}"
# (호스트, 방법, 길, 질의(정확히 이것), 본문 종류, Bearer 필요) — 독립으로 적은 여섯 모양
SHAPES = (
    (OAUTH_HOST, "POST", re.compile(r"/token"), {}, "application/x-www-form-urlencoded", False),
    (OAUTH_HOST, "POST", re.compile(r"/revoke"), {}, "application/x-www-form-urlencoded", False),
    (API_HOST, "GET", re.compile(rf"/blogger/v3/blogs/{NUMBER}"), {}, None, True),
    (API_HOST, "POST", re.compile(rf"/blogger/v3/blogs/{NUMBER}/posts"), {"isDraft": "true"}, "application/json; charset=UTF-8", True),
    (API_HOST, "GET", re.compile(rf"/blogger/v3/blogs/{NUMBER}/posts"), {"status": "DRAFT", "orderBy": "UPDATED", "maxResults": "5", "fetchBodies": "false", "view": "ADMIN"}, None, True),
    (API_HOST, "GET", re.compile(rf"/blogger/v3/blogs/{NUMBER}/posts/{NUMBER}"), {"view": "ADMIN"}, None, True),
)
ALLOWED_INSERT_KEYS = {"kind", "title", "content", "labels"}


def token(prefix, seed, size=24):
    """조립한 가짜 토큰 — `ya29.` 같은 모양을 실행 때 이어 붙인다."""
    return prefix + "CANARY_" + seed + "_" + ("x" * size)


def stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Req:
    """가짜 서버가 읽은 요청 한 건."""

    def __init__(self, host, method, target, headers, body):
        self.host, self.method, self.target, self.headers, self.body = host, method, target, headers, body
        parts = urlsplit(target)
        self.path = parts.path
        self.query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        self.query = dict(self.query_pairs)

    def form(self):
        return dict(parse_qsl(self.body.decode("ascii"), keep_blank_values=True, strict_parsing=True))

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def bearer(self):
        value = self.headers.get("authorization", "")
        return value[7:] if value.startswith("Bearer ") else ""

    def summary(self):
        return f"{self.method} {self.host}{self.path}" + ("?" + "&".join(f"{k}={v}" for k, v in self.query_pairs) if self.query_pairs else "")


class Reply:
    """가짜 서버의 답 하나 — 상태·JSON 본문·머리글."""

    def __init__(self, status=200, body=None, headers=(), raw=None):
        self.status, self.body, self.headers, self.raw = status, body, tuple(headers), raw

    def bytes(self):
        if self.raw is not None:
            return self.raw
        body = json.dumps(self.body, ensure_ascii=False).encode("utf-8") if self.body is not None else b""
        headers = [("Content-Type", "application/json; charset=UTF-8"), *self.headers] if body else list(self.headers)
        return ns.http_response(self.status, "X", headers, body)


DISCONNECT = "disconnect"                      # 답 없이 끊는다(서버가 요청을 봤을 수 있다)
STORE_THEN_DISCONNECT = "store_then_disconnect"  # 글을 저장한 뒤 답 없이 끊는다(서버는 저장함)


def google_error(status, reason="", message="CANARY_SERVER_MESSAGE <b>x</b>"):
    """구글 API 오류 모양 — `error.errors[0].reason` 이 사유. 서버의 글(`message`)에는 카나리를 넣어 앱이 그것을 쓰지 않는지 본다."""
    body = {"error": {"code": status, "message": message, "errors": [{"domain": "global", "reason": reason, "message": message}] if reason else [], "status": "X"}}
    return Reply(status, body)


def oauth_error(status, name, description="CANARY_SERVER_DESCRIPTION"):
    return Reply(status, {"error": name, "error_description": description})


class FakeGoogle:
    """가짜 구글 토큰 서버 + 가짜 Blogger API 한 벌."""

    def __init__(self, clock=None, blogs=None, now=None):
        self.clock = clock
        self.now = now or datetime(2026, 11, 25, 9, 0, 0, tzinfo=timezone.utc)
        self.requests = []
        self.violations = []
        self.clients = {CLIENT_ID: CLIENT_SECRET}
        self.codes = {}                  # code -> {challenge, redirect_uri, client_id}
        self.refresh_tokens = {}         # token -> client_id
        self.access_tokens = {}          # token -> refresh token
        self.minted = 0
        self.blogs = {BLOG_EN: {"name": "영문 <b>블로그</b>", "url": "https://english.example.test/"}, BLOG_KO: {"name": "한글 블로그", "url": "https://korean.example.test/"}} if blogs is None else blogs
        self.posts = {}                  # (blog, post) -> dict
        self.next_post = 1000
        self.mode = {"token": "ok", "refresh": "ok", "revoke": "ok", "insert": "ok", "list": "ok", "get": "ok", "blog": "ok"}
        self.queue = {}                  # 이름 -> [Reply | 문자열, …]  (한 번씩 쓰고 사라진다)
        self.stored_on_disconnect = True

    # ---- 준비 --------------------------------------------------------------------------------------------------------------------------------
    def issue_code(self, challenge, redirect_uri, client_id=CLIENT_ID, code=CODE):
        self.codes[code] = {"challenge": challenge, "redirect_uri": redirect_uri, "client_id": client_id}
        return code

    def grant(self, client_id=CLIENT_ID, refresh=REFRESH):
        """로그인을 이미 마친 것처럼 갱신 토큰 하나를 만든다."""
        self.refresh_tokens[refresh] = client_id
        return refresh

    def push(self, name, *items):
        self.queue.setdefault(name, []).extend(items)

    def add_post(self, blog, title, *, status="DRAFT", updated=None, content="x"):
        self.next_post += 1
        post = {"id": str(self.next_post), "title": title, "content": content, "labels": [], "status": status, "updated": stamp(updated or self.now), "blog": blog}
        self.posts[(blog, post["id"])] = post
        return post

    def drafts(self, blog=None):
        return [post for (key, _), post in self.posts.items() if post["status"] == "DRAFT" and (blog is None or key == blog)]

    def count(self, text):
        return len([item for item in self.requests if text in item.summary()])

    def summaries(self):
        return [item.summary() for item in self.requests]

    # ---- 요청 하나 -----------------------------------------------------------------------------------------------------------------------------
    def violation(self, request, why):
        self.violations.append(f"{why}: {request.summary()}")
        return Reply(400, {"error": {"code": 400, "message": "STRICT"}})

    def shape_of(self, request):
        for shape in SHAPES:
            host, method, path, query, content_type, bearer = shape
            if request.host == host and request.method == method and path.fullmatch(request.path) and request.query == query and len(request.query_pairs) == len(query):
                return shape
        return None

    def check(self, request):
        """접속 틀이 보낸 요청의 머리글·본문이 약속과 같은가 → 어기면 이유 글."""
        shape = self.shape_of(request)
        if shape is None:
            return "여섯 모양 밖의 요청"
        host, method, path, query, content_type, bearer = shape
        headers = request.headers
        expected = {"host", "user-agent", "accept", "accept-encoding", "connection"}
        if request.body or method == "POST":
            expected |= {"content-type", "content-length"}
        if bearer:
            expected.add("authorization")
        if set(headers) - expected:
            return f"약속에 없는 머리글 {sorted(set(headers) - expected)}"
        if not headers.get("user-agent", "").startswith("ChanceBlogDesktop/") or headers.get("accept") != "application/json" or headers.get("accept-encoding") != "identity" or headers.get("connection") != "close":
            return "고정 머리글이 다르다"
        if content_type is not None and headers.get("content-type") != content_type:
            return "본문 종류가 다르다"
        if bearer and not request.bearer:
            return "Bearer 가 없다"
        if not bearer and "authorization" in headers:
            return "토큰 서버 요청에 Authorization 이 있다"
        if "cookie" in headers or "referer" in headers:
            return "쿠키·Referer 가 있다"
        return ""

    def handle(self, request):
        """요청 → 답 바이트(또는 `b""` — 끊김). 모든 요청은 기록된다."""
        self.requests.append(request)
        problem = self.check(request)
        if problem:
            return self.violation(request, problem).bytes()
        name = self.route(request)
        queued = self.queue.get(name)
        if queued:
            item = queued.pop(0)
            if item == DISCONNECT:
                return b""
            if item == STORE_THEN_DISCONNECT:
                self.respond(name, request)                      # 저장은 하되 답은 보내지 않는다
                return b""
            if isinstance(item, Reply):
                return item.bytes()
        reply = self.respond(name, request)
        return reply.bytes() if isinstance(reply, Reply) else reply

    @staticmethod
    def route(request):
        if request.host == OAUTH_HOST:
            return "revoke" if request.path == "/revoke" else "token"
        if request.method == "POST":
            return "insert"
        if request.path.endswith("/posts"):
            return "list"
        if "/posts/" in request.path:
            return "get"
        return "blog"

    def respond(self, name, request):
        if name == "token":
            return self.token_endpoint(request)
        if name == "revoke":
            return self.revoke_endpoint(request)
        blog = request.path.split("/")[4]
        if request.bearer not in self.access_tokens:
            return google_error(401, "authError")
        if blog not in self.blogs:
            return google_error(404, "notFound")
        mode = self.mode[name]
        if mode.startswith("status:"):
            status, _, reason = mode[7:].partition(":")
            return google_error(int(status), reason)
        return getattr(self, f"{name}_endpoint")(request, blog, mode)

    # ---- 토큰 서버 ------------------------------------------------------------------------------------------------------------------------------
    def mint(self, refresh):
        self.minted += 1
        value = token("ya29.", f"ACCESS{self.minted}")
        self.access_tokens[value] = refresh
        return value

    def token_endpoint(self, request):
        form = request.form()
        grant = form.get("grant_type")
        client_id = form.get("client_id")
        if self.clients.get(client_id) != form.get("client_secret"):
            return oauth_error(401, "invalid_client")
        mode = self.mode["token"] if grant == "authorization_code" else self.mode["refresh"]
        if mode == "invalid_client":
            return oauth_error(401, "invalid_client")
        if mode == "invalid_grant":
            return oauth_error(400, "invalid_grant")
        if mode.startswith("status:"):
            return Reply(int(mode[7:]), {"error": "server_error"})
        if grant == "authorization_code":
            record = self.codes.pop(form.get("code"), None)
            verifier = form.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
            if record is None or record["challenge"] != challenge or record["redirect_uri"] != form.get("redirect_uri") or record["client_id"] != client_id:
                return oauth_error(400, "invalid_grant")
            if set(form) != {"client_id", "client_secret", "code", "code_verifier", "grant_type", "redirect_uri"}:
                return self.violation(request, "교환 본문의 칸이 다르다")
            self.refresh_count = getattr(self, "refresh_count", 0) + 1
            refresh = self.grant(client_id, refresh=token("1//0", f"REFRESH{self.refresh_count}", 26))                       # 로그인마다 새 갱신 토큰(같은 값이 되풀이되지 않는다)
            body = {"access_token": self.mint(refresh), "expires_in": 3599, "refresh_token": refresh, "scope": SCOPE, "token_type": "Bearer"}
            return Reply(200, self.damaged(body, mode))
        if grant == "refresh_token":
            if set(form) != {"client_id", "client_secret", "grant_type", "refresh_token"}:
                return self.violation(request, "갱신 본문의 칸이 다르다")
            if self.refresh_tokens.get(form.get("refresh_token")) != client_id:
                return oauth_error(400, "invalid_grant")
            body = {"access_token": self.mint(form["refresh_token"]), "expires_in": 3599, "scope": SCOPE, "token_type": "Bearer"}
            return Reply(200, self.damaged(body, mode))
        return self.violation(request, "모르는 grant_type")

    @staticmethod
    def damaged(body, mode):
        body = dict(body)
        if mode == "no_refresh":
            body.pop("refresh_token", None)
        elif mode == "scope_narrow":
            body["scope"] = "openid"
        elif mode == "scope_wide":
            body["scope"] = SCOPE + " https://www.googleapis.com/auth/drive"
        elif mode == "scope_missing":
            body.pop("scope", None)
        elif mode == "bad_type":
            body["token_type"] = "MAC"
        elif mode == "bad_expires":
            body["expires_in"] = "soon"
        elif mode == "tiny_expires":
            body["expires_in"] = 5
        elif mode == "huge_expires":
            body["expires_in"] = 10 ** 9
        elif mode == "short_access":
            body["access_token"] = "short"
        elif mode == "long_access":
            body["access_token"] = "ya29." + "A" * 3000
        elif mode == "short_refresh":
            body["refresh_token"] = "1//short"
        elif mode == "long_refresh":
            body["refresh_token"] = "1//" + "A" * 600
        elif mode == "space_access":
            body["access_token"] = "ya29.CANARY has space " + "x" * 30
        return body

    def revoke_endpoint(self, request):
        form = request.form()
        if set(form) != {"token"}:
            return self.violation(request, "취소 본문의 칸이 다르다")
        mode = self.mode["revoke"]
        if mode.startswith("status:"):
            return Reply(int(mode[7:]), {"error": "server_error"})
        value = form["token"]
        if value in self.refresh_tokens:
            del self.refresh_tokens[value]
            for access in [key for key, parent in self.access_tokens.items() if parent == value]:
                del self.access_tokens[access]
            return Reply(200, {})
        return Reply(400, {"error": "invalid_token"})

    # ---- Blogger API ----------------------------------------------------------------------------------------------------------------------------
    def blog_endpoint(self, request, blog, mode):
        info = self.blogs[blog]
        body = {"kind": "blogger#blog", "id": blog if mode != "id_mismatch" else "1", "name": info["name"], "url": info["url"], "locale": {"language": "ko"}}
        if mode == "no_url":
            body.pop("url")
        if mode == "bad_url":
            body["url"] = "http://plain.example.test/"
        if mode == "long_name":
            body["name"] = "가" * 600
        return Reply(200, body)

    def insert_endpoint(self, request, blog, mode):
        data = request.json()
        if not isinstance(data, dict) or set(data) - ALLOWED_INSERT_KEYS or data.get("kind") != "blogger#post" or not isinstance(data.get("title"), str) or not isinstance(data.get("content"), str):
            return self.violation(request, "초안 저장 본문의 칸이 다르다")
        self.next_post += 1
        post = {"id": str(self.next_post), "title": data["title"], "content": data["content"], "labels": data.get("labels", []), "status": "LIVE" if mode == "ignore_draft" else "DRAFT",
                "updated": stamp(self.now), "blog": blog}
        if mode == "scheduled":
            post["status"] = "SCHEDULED"
        self.posts[(blog, post["id"])] = post
        body = {"kind": "blogger#post", "id": post["id"], "blog": {"id": blog if mode != "blog_mismatch" else "1"}, "title": post["title"], "status": post["status"]}
        if mode == "with_url":
            body["url"] = "https://english.example.test/2026/11/x.html"
        if mode == "bad_url":
            body["url"] = "http://plain.example.test/x.html"
        if mode == "no_status":
            body.pop("status")
        if mode == "lowercase_status":
            body["status"] = post["status"].lower()
        if mode == "bad_id":
            body["id"] = "abc"
        return Reply(200, body)

    def list_endpoint(self, request, blog, mode):
        items = sorted((post for (key, _), post in self.posts.items() if key == blog and post["status"] == "DRAFT"), key=lambda post: post["updated"], reverse=True)[:5]
        body = {"kind": "blogger#postList"}
        if items:
            body["items"] = [{"kind": "blogger#post", "id": post["id"], "title": post["title"], "updated": post["updated"], "status": post["status"]} for post in items]
        if mode == "bad_items":
            body["items"] = "not a list"
        return Reply(200, body)

    def get_endpoint(self, request, blog, mode):
        post = self.posts.get((blog, request.path.rsplit("/", 1)[1]))
        if post is None:
            return google_error(404, "notFound")
        body = {"kind": "blogger#post", "id": post["id"], "status": post["status"], "title": post["title"]}
        if mode == "no_status":
            body.pop("status")
        if mode == "live":
            body["status"] = "LIVE"
        if mode == "id_mismatch":
            body["id"] = "1"
        return Reply(200, body)


def parse_request(buffer, host):
    """보낸 바이트가 요청 하나로 완성됐으면 `Req`, 아니면 None."""
    raw = bytes(buffer)
    end = raw.find(b"\r\n\r\n")
    if end == -1:
        return None
    lines = raw[:end].decode("latin-1").split("\r\n")
    method, target, _version = lines[0].split(" ")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = raw[end + 4:]
    if len(body) < length:
        return None
    return Req(host, method, target, headers, body[:length])


class ScriptedSocket(ns.FakeSocket):
    """보낸 요청이 다 모이면 가짜 서버에 넘겨 답을 정하는 가짜 소켓."""

    def __init__(self, google, host, **kwargs):
        super().__init__(b"", **kwargs)
        self.google, self.host = google, host
        self.answered = False

    def sendall(self, data):
        super().sendall(data)
        if not self.answered:
            request = parse_request(self.sent, self.host)
            if request is not None:
                self.answered = True
                self.data = self.google.handle(request)
                self.offset = 0


class GoogleHarness(ns.Harness):
    """접속 틀의 전송 자리에 가짜 구글을 끼운다 — `with GoogleHarness(self, google, switches=…) as env:` 안에서 앱의 접속 틀이 가짜 서버와 이야기한다."""

    def __init__(self, test, google, *, switches=(), **kwargs):
        super().__init__(test, b"", switches=switches, **kwargs)
        self.google = google
        google.clock = self.clock

    def _dial(self, connection, address):
        self.dials.append((connection.host, address))
        if self.dial_error is not None:
            raise self.dial_error
        sock = ScriptedSocket(self.google, connection.host, clock=self.clock)
        self.last_socket = sock
        return sock


ALL_SWITCHES = ("EXTERNAL_WRITE", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT")
LOGIN_SWITCHES = ("NET_BLOGGER_OAUTH",)


@contextlib.contextmanager
def no_switches():
    yield
