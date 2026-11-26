"""Blogger 흐름 시험용 세계(서비스 층) — 시험이 아니다(BLOGGER 설계서 6.1, 결정 D-774).

임시 데이터 폴더·가짜 보관소·**가짜 구글**(`blogger_support.FakeGoogle`)·접속 틀의 가짜 전송기·가짜 브라우저·루프백만 허용하는 감시(`Tripwire(loopback_only=True)`)를 한 번에 만든다.
소스 상수 스위치는 시험 안에서만 임시로 켠다(`switches`). 시험이 만드는 임시 파일은 모두 시험 폴더 안에 생기게 해서 끝에 한꺼번에 훑어 볼 수 있다.
"""
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blogger_support as bs  # noqa: E402
import outgoing_support as og  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.service import blogger_flow as flow  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import external  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402

CLIENT_ID, CLIENT_SECRET, BLOG_EN, BLOG_KO = bs.CLIENT_ID, bs.CLIENT_SECRET, bs.BLOG_EN, bs.BLOG_KO
CLIENT_ID_KO = "987654321098-" + "canary" + "clientkr0042" + ".apps.example"
CLIENT_SECRET_KO = "GOCSPX-" + "CANARY_" + "SECRET_" + "zyxwvutsrqpo"
BODY_MARKDOWN = "## 소제목\n\n에너지를 아끼는 작은 습관은 매일 조금씩 실천할 때 가장 오래 갑니다. 이 글은 시험용 본문입니다.\n\n둘째 문단입니다.\n"
TITLE = "시험 글 제목"
SLOT_CLIENT = {"blogger_en": (CLIENT_ID, CLIENT_SECRET), "blogger_ko": (CLIENT_ID_KO, CLIENT_SECRET_KO)}
SLOT_BLOG = {"blogger_en": BLOG_EN, "blogger_ko": BLOG_KO}
SLOT_NAME = {"blogger_en": "영문", "blogger_ko": "한글"}


class FakeBrowser:
    """시스템 브라우저 역할 — 열기 요청을 받으면 로그인 주소를 읽어 가짜 구글에 코드를 발급하게 하고, 스레드에서 `127.0.0.1` 의 창구로 돌아온다(진짜 소켓).
    `mode`: allow(올바른 돌아옴) · deny(`access_denied`) · wrong_state_then_allow(틀린 state 먼저) · wrong_state_only · never(돌아오지 않음) · broken(열기에서 예외)."""

    def __init__(self, google, mode="allow", client_id=None, burst=0):
        self.google, self.mode, self.client_id, self.burst = google, mode, client_id, burst
        self.urls = []
        self.threads = []
        self.codes = []
        self.responses = []

    def __call__(self, url):
        self.urls.append(url)
        if self.mode == "broken":
            raise RuntimeError("CANARY_BROWSER_ERROR")
        query = dict(parse_qsl(urlsplit(url).query))
        port = int(urlsplit(query["redirect_uri"]).port)
        code = self.google.issue_code(query["code_challenge"], query["redirect_uri"], self.client_id or query["client_id"], code="4/0CANARY_CODE_" + str(len(self.urls)) + "x" * 20)
        self.codes.append(code)
        thread = threading.Thread(target=self.visit, args=(port, query["state"], code), daemon=True)
        thread.start()
        self.threads.append(thread)

    def get(self, port, target):
        with socket.create_connection(("127.0.0.1", port), timeout=6.0) as conn:
            conn.sendall(f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode("ascii"))
            data = b""
            while True:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
        self.responses.append(data)
        return data

    def visit(self, port, state, code):
        try:
            for _ in range(self.burst):
                self.get(port, "/favicon.ico")
            if self.mode == "never":
                return
            if self.mode in ("wrong_state_then_allow", "wrong_state_only"):
                self.get(port, f"/callback?code=4/0CANARY_FORGED_CODE_{'f' * 20}&state={'W' * 43}")
                if self.mode == "wrong_state_only":
                    return
            if self.mode == "deny":
                self.get(port, f"/callback?error=access_denied&state={state}")
            else:
                self.get(port, f"/callback?code={code}&state={state}&scope=x&authuser=0")
        except OSError:
            pass

    def join(self):
        for thread in self.threads:
            thread.join(10)


class FlowCase(unittest.TestCase):
    """서비스 층 시험의 세계."""

    switches = bs.ALL_SWITCHES
    clients = ("blogger_en", "blogger_ko")

    def setUp(self):
        flow.forget()
        self.addCleanup(flow.forget)
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patcher = mock.patch.object(tempfile, "tempdir", str(self.tmp))                        # 이 시험이 만드는 임시 파일은 모두 이 폴더 안에 생긴다(마지막에 훑어 본다)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctx = ss.make_ctx(self.tmp, repo=None, clock=ss.Clock())
        self.store = self.ctx.keystore
        self.google = bs.FakeGoogle(now=self.ctx.now())
        self.google.clients = {CLIENT_ID: CLIENT_SECRET, CLIENT_ID_KO: CLIENT_SECRET_KO}
        self.env = bs.GoogleHarness(self, self.google, switches=self.switches)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        opened = mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True)
        opened.start()
        self.addCleanup(opened.stop)
        register = external.registered(external.KIND_BLOGGER, flow.make_blogger_adapter)
        register.__enter__()
        self.addCleanup(register.__exit__, None, None, None)
        self.wire = og.Tripwire(loopback_only=True)
        self.wire.__enter__()
        self.addCleanup(self.wire.__exit__, None, None, None)
        for slot in self.clients:
            self.add_slot(slot)

    # ---- 준비 ----------------------------------------------------------------------------------------------------------------------------------
    def add_slot(self, slot):
        client_id, secret = SLOT_CLIENT[slot]
        entry = cn.add_entry(self.ctx, "blogger", name=SLOT_NAME[slot], fields={"client_id": client_id, "client_secret": secret}, keystore=self.store).entry
        self.set_blog(slot, SLOT_BLOG[slot])
        return entry

    def set_blog(self, slot, blog_ref):
        bp.save_slot(self.ctx, slot, {"blog_ref": blog_ref}, expected_version=bp.read_snapshot(self.ctx).version)

    def entry(self, slot):
        return flow.find_entry(self.ctx, slot)

    def login(self, slot="blogger_en", mode="allow", **kwargs):
        browser = FakeBrowser(self.google, mode)
        result = flow.login(self.ctx, slot, open_url=browser, **kwargs)
        browser.join()
        return result

    def login_both(self):
        for slot in self.clients:
            self.login(slot)
        self.google.requests.clear()

    def approve(self, slot="blogger_en", title=TITLE, markdown=BODY_MARKDOWN, references=(), assets=()):
        view = projects.new_project(self.ctx, title, markdown, references=references, assets=assets)
        with self.ctx.store() as store:
            project = store.load(view.project_id)
            project.set_rendered(slot, "승인한 렌더링")
            project.transition(slot, st.REVIEW_REQUIRED)
            project.transition(slot, st.APPROVED)
            store.save(project)
        return view.project_id

    def poison(self, project_id, markdown):
        """승인한 글의 원고를 **승인을 풀지 않고** 직접 바꾼다 — 글 만들기 단계의 검사를 비켜 간 글이 보내기 직전 검사에서 막히는지 본다."""
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.source_content = markdown
            store.save(project)

    def reapprove(self, project_id, slot="blogger_en", markdown=None, title=None):
        """승인한 글의 원고(또는 제목)를 **실제 고치기 길**로 고친다 — 판이 올라가고(`ContentProject.edit`) 다시 렌더링·검토·승인을 거친다(재작업 1 권고-2 의 시험이 쓴다)."""
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.edit(source_content=markdown, title=title)
            project.set_rendered(slot, "승인한 렌더링(고친 판)")
            project.transition(slot, st.REVIEW_REQUIRED)
            project.transition(slot, st.APPROVED)
            store.save(project)

    def post_hash(self, project_id, slot="blogger_en", tags=()):
        """그 글을 지금 보내면 저널에 적힐 내용 해시(`save_draft` 가 만드는 HTML 의 해시) — 저널을 손으로 만드는 시험이 '같은 글' 의 저널임을 나타내려고 쓴다."""
        from chanceblog_desktop.render import blogger as render
        with self.ctx.store() as store:
            project = store.load(project_id)
        return flow._sha(render.render_blogger_post(project, flow.SLOT_LANG[slot], hero=None, tags=tags).html)

    def variant(self, project_id, slot="blogger_en"):
        with self.ctx.store() as store:
            return store.load(project_id).variant(slot)

    def save(self, project_id, slot="blogger_en", **kwargs):
        kwargs.setdefault("confirmed", True)
        return flow.save_draft(self.ctx, project_id, slot, **kwargs)

    def advance(self, **kwargs):
        self.ctx.clock.advance(**kwargs)
        self.google.now = self.ctx.now()

    def cool(self):
        self.env.usage._state.clear()

    def inserts(self):
        return [item for item in self.google.requests if item.method == "POST" and item.path.endswith("/posts")]

    def assertClean(self):
        self.assertEqual(self.google.violations, [], "가짜 서버가 약속과 다른 요청을 받았다")
        self.assertEqual(self.wire.calls, [], "루프백 밖으로 나가는 연결·이름 풀이가 있었다")

    def journal_dir(self):
        return Path(self.ctx.workspace.journal_dir) / "blogger"

    def journals(self):
        folder = self.journal_dir()
        return sorted(path.name for path in folder.glob("*.json")) if folder.exists() else []
