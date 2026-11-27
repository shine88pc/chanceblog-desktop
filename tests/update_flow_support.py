"""업데이트 서비스 시험 도우미(시험이 아니다 — v1update U-3): 가짜 릴리스 서버·서명된 가짜 릴리스·가짜 어댑터·시험 맥락. 설치 도구는 Inno Setup 이라(D-811) 가짜 릴리스의 기본 설치 종류도 `inno` 다(받는 파일은 `setup` 하나 — 릴리스는 `package`·`feed` 도 올려 두지만 앱은 받지 않는다).

**진짜 접속은 한 번도 없다** — 서버는 `net_support.FakeSocket` 위의 가짜(소켓이 열리지 않는다)이고, 앱의 진짜 접속 틀(`NetClient`)이 그 위에서 돈다: 표 검사·머리글·이동 판정·크기·해시가 모두 진짜 코드다.
릴리스는 `update_support` 의 임시 키로 서명한다(출하 키는 비어 있어 시험이 키 목록을 직접 만들어 넘긴다). 서버는 GitHub 처럼 `latest/download` → 같은 호스트의 태그 길 → 자산 호스트로 두 번 이동시킨다.
"""
import contextlib
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import net_support as ns  # noqa: E402
import service_support as ss  # noqa: E402
import update_support as us  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.net import client  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
from chanceblog_desktop.service import external  # noqa: E402
from chanceblog_desktop.update import apply, keys, state  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 12, 2, 0, 0, 0, tzinfo=UTC)
OWNER = gitrepo.EXPECTED_OWNER
BASE = f"/{OWNER}/chanceblog-desktop/releases"
CDN_HOST = "release-assets.githubusercontent.com"
RING = keys.Keyring([(keys.ROLE_CURRENT, us.SeededTestCase.PUB_A), (keys.ROLE_SPARE, us.SeededTestCase.PUB_B)])
KEY_ID = us.SeededTestCase.ID_A


CDN_QUERY = "sp=r&sv=2018-11-09&sr=b&spr=https&se=2026-12-02T01%3A00%3A00Z&rscd=attachment%3B+filename%3Dx&sig=abc%2Bdef%3D&jwt=eyJhbGciOiJIUzI1NiJ9.eyJ4IjoxfQ.sig-_x"      # 자산 호스트가 붙이는 서명된 질의 모양(%·+·=·&·점·밑줄)


def cdn_path(name):
    return f"/github-production-release-asset/1/{hashlib.sha256(name.encode()).hexdigest()[:12]}?{CDN_QUERY}"


class ServerSocket(ns.FakeSocket):
    """요청을 읽고 서버가 정한 응답을 돌려주는 가짜 소켓."""

    def __init__(self, server, host, **kwargs):
        super().__init__(b"", **kwargs)
        self.server = server
        self.host = host

    def sendall(self, data):
        super().sendall(data)
        raw = bytes(self.sent)
        if b"\r\n\r\n" in raw:
            head = raw.split(b"\r\n\r\n")[0].decode("ascii")
            method, target, _version = head.split("\r\n")[0].split(" ", 2)
            self.data = self.server.respond(self.host, method, target, head)
            self.offset = 0


class ReleaseServer:
    """길 → 응답 표. `put` 은 본문, `redirect` 는 이동, `fail` 은 상태만. 받은 요청은 모두 `requests`(호스트, 방법, 길, 머리글 글)에 남는다."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        self.hooks = {}

    def put(self, host, path, body, *, status=200, headers=()):
        self.routes[(host, path)] = (status, tuple(headers), body)

    def redirect(self, host, path, location, status=302):
        self.routes[(host, path)] = (status, (("Location", location),), b"")

    def respond(self, host, method, target, head):
        self.requests.append((host, method, target, head))
        hook = self.hooks.get((host, target))
        if hook is not None:
            hook()
        found = self.routes.get((host, target))
        if found is None:
            return ns.http_response(404, "Not Found", body=b"")
        status, headers, body = found
        return ns.http_response(status, "OK" if status == 200 else "Found" if 300 <= status < 400 else "Error", headers=list(headers), body=body)

    def hosts(self):
        return sorted({host for host, *_rest in self.requests})


class Release:
    """서명된 가짜 릴리스 하나 — 매니페스트·서명·파일 본문을 만들고 서버에 올린다."""

    def __init__(self, version="1.0.1", *, seq=None, seed=us.SeededTestCase.SEED_A, kind="inno", sizes=(3000, 400), min_version="1.0.0", issued="2026-12-01T03:00:00Z", expires="2027-05-30T03:00:00Z", pack_id="ChanceBlogDesktopApp", channel="stable"):
        self.version = version
        self.tag = "v" + version
        self.seed = seed
        issued_digits = int(issued.replace("-", "").replace("T", "").replace(":", "").replace("Z", ""))
        self.bodies = {}
        package_name, feed_name, setup_name = f"ChanceBlogDesktopApp-{version}-stable-full.nupkg", "releases.stable.json", f"ChanceBlogDesktop-{version}-Setup.exe"
        seeded = hashlib.sha256(version.encode()).digest()
        self.bodies[package_name] = (seeded * (sizes[0] // len(seeded) + 1))[:sizes[0]]
        self.bodies[feed_name] = (seeded * (sizes[1] // len(seeded) + 1))[:sizes[1]]
        self.bodies[setup_name] = (seeded[::-1] * (sizes[0] // len(seeded) + 1))[:sizes[0]]
        files = [{"role": role, "name": name, "size": len(self.bodies[name]), "sha256": hashlib.sha256(self.bodies[name]).hexdigest()}
                 for role, name in (("setup", setup_name), ("package", package_name), ("feed", feed_name))]
        self.dict = us.manifest_dict(version=version, channel=channel, tag=self.tag, seq=issued_digits if seq is None else seq, issued_utc=issued, expires_utc=expires, min_version=min_version, files=files,
                                     key_id=us.key_id_of(us.public_key(seed)), installer={"kind": kind, "pack_id": pack_id})
        self.manifest_bytes = us.encode_manifest(self.dict)
        self.signature = us.signature_file(seed, self.manifest_bytes)

    def install(self, server, *, tamper=None, latest=True):
        """서버에 올린다 — `tamper` 는 {이름: 바꾼 본문}(자산이 서명된 값과 다르게 오는 경우), `latest=False` 면 '최신' 길은 두지 않는다(이전 릴리스를 태그 길로만 받는 복구 시험)."""
        tamper = tamper or {}
        files = {"update-manifest.json": self.manifest_bytes, "update-manifest.json.sig": self.signature}
        files.update({name: tamper.get(name, body) for name, body in self.bodies.items()})
        for name, body in files.items():
            tagged = f"{BASE}/download/{self.tag}/{name}"
            if latest:
                server.redirect("github.com", f"{BASE}/latest/download/{name}", f"https://github.com{tagged}")
            server.redirect("github.com", tagged, f"https://{CDN_HOST}{cdn_path(name)}")
            server.put(CDN_HOST, cdn_path(name), body)
        return server


class FlowHarness(ns.Harness):
    """가짜 서버를 물린 접속 환경 — 앱의 진짜 접속 틀이 그 위에서 돈다."""

    def __init__(self, test, server, *, switches=("NET_UPDATE_CHECK",), **kwargs):
        super().__init__(test, b"", switches=switches, **kwargs)
        self.server = server
        self.made = []                                           # 만든 가짜 소켓 전부 — 보낸 바이트(`sent`)를 시험이 훑는다

    def _dial(self, connection, address):
        self.dials.append((connection.host, address))
        if self.dial_error is not None:
            raise self.dial_error
        sock = ServerSocket(self.server, connection.host, clock=self.clock)
        self.last_socket = sock
        self.made.append(sock)
        return sock

    def factory(self, **parts):
        return client.NetClient(version=parts.get("version", ns.VERSION), usage=self.usage)

    @contextlib.contextmanager
    def plugged(self):
        """`update` 어댑터를 꽂은 채 — 앱이 쓰는 길(`external.adapter_factory`)로 클라이언트를 얻게 한다."""
        with external.registered(external.KIND_UPDATE, self.factory):
            yield self


class FakeAdapter(apply.ApplyAdapter):
    """설치 도구를 띄우지 않는 가짜 어댑터 — 넘겨 받은 것과 그 순간의 디스크 상태를 기록한다."""

    def __init__(self, folder, *, kind="inno", fail=None, kill=None):
        self.kind = kind
        self.folder = folder
        self.fail = fail
        self.kill = kill
        self.calls = []
        self.pending_seen = []

    def _apply(self, staged, *, from_version, to_version, recovery):
        try:
            self.pending_seen.append(state.read_state(self.folder).pending)
        except state.StateError:
            self.pending_seen.append("unreadable")
        self.calls.append((sorted(staged.files), from_version, to_version, recovery))
        if self.kill is not None:
            raise self.kill
        if self.fail is not None:
            raise self.fail
        return "handed-off"


class Killed(BaseException):
    """시험이 '그 자리에서 프로세스가 죽었다' 를 흉내 내는 예외 — 어떤 `except Exception` 도 삼키지 못한다."""


def make_world(tmp, *, with_store=True):
    """임시 폴더의 시험 맥락 — 시계는 2026-12-02. 글 보관함 파일을 만들어 백업이 담을 것이 있게 한다."""
    ctx = ss.make_ctx(tmp, clock=ss.Clock(NOW))
    if with_store:
        ctx.store().close()
    return ctx


@contextlib.contextmanager
def switches_on(*names):
    with contextlib.ExitStack() as stack:
        for name in names:
            stack.enter_context(mock.patch.object(capabilities, name, True))
        yield
