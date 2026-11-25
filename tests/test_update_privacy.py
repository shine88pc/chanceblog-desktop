"""업데이트 요청의 개인 정보·사진 비유출 고정 시험(UPDATE 설계서 3-12, 확인 018 '사진은 PC 를 떠나지 않는다', 위협 U14).

가짜 전송으로 **모든 요청의 바이트 전체**(요청 줄·머리글·본문)를 가로채 허용 값과 정확히 같은지 본다 — 확인·내려받기·적용·복구가 지나가는 동안 한 번도 벗어나지 않아야 한다:
  · 방법은 GET 뿐, 호스트는 두 곳뿐(`github.com`·릴리스 자산 호스트), 길은 앱 저장소의 릴리스 길 둘(자산 호스트는 서버가 정한 서명 길)뿐, 본문 0, 질의는 자산 호스트의 서명 질의뿐(github.com 쪽은 질의 0).
  · 머리글은 정확히 `Host`·`User-Agent`·`Accept`·`Accept-Encoding`·`Connection` 다섯이고 값은 고정이다: `User-Agent: ChanceBlogDesktop`(**버전·운영체제·경로 없음**), `Accept: */*`, `Accept-Encoding: identity`, `Connection: close`.
  · `Cookie`·`Authorization`·`Referer`·`Origin`·`X-` 머리글이 없다.
  · 카나리 — 데이터 폴더 경로·윈도 계정 이름·컴퓨터 이름·홈 폴더·글 제목·키 모양 가짜 값 — 을 데이터 폴더에 심어도 요청 어디에도 나오지 않는다.
변이: 사용자 에이전트에 버전을 넣거나 `Referer` 를 더하면 이 시험이 빨개진다(시험 안에서 같은 검사를 변이된 가짜 요청에 돌려 확인한다).
"""
import getpass
import os
import platform
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import outgoing_support as og  # noqa: E402
import test_update_flow as flow  # noqa: E402
import update_flow_support as fs  # noqa: E402

from chanceblog_desktop.service import projects, update_flow  # noqa: E402
from chanceblog_desktop.update import state  # noqa: E402

CANARY_TITLE = "CANARY_" + "TITLE_" + "에너지절약글"
CANARY_KEY = "CANARY_" + "KEY_" + "AIzaSyDEADBEEF0123456789"
ALLOWED_HOSTS = {"github.com", fs.CDN_HOST}
HEADER_NAMES = ["Host", "User-Agent", "Accept", "Accept-Encoding", "Connection"]
FIXED = {"User-Agent": "ChanceBlogDesktop", "Accept": "*/*", "Accept-Encoding": "identity", "Connection": "close"}
ROUTE_PATTERNS = (re.compile(re.escape(fs.BASE) + r"/latest/download/update-manifest\.json(?:\.sig)?"), re.compile(re.escape(fs.BASE) + r"/download/v[0-9.]+/[A-Za-z0-9][A-Za-z0-9._-]{0,99}"))
CDN_PATTERN = re.compile(r"/github-production-release-asset/1/[0-9a-f]{12}\?[A-Za-z0-9._%+=&;:-]+")


def request_problems(raw):
    """가로챈 요청 한 건(바이트)의 허용 값 위반 목록 — 비어 있어야 한다. 시험이 변이된 가짜 요청에도 같은 함수를 돌려 이 검사가 빈 실험이 아님을 보인다."""
    problems = []
    head, _gap, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("ascii", "replace").split("\r\n")
    method, target, version = (lines[0].split(" ") + ["", "", ""])[:3]
    if (method, version) != ("GET", "HTTP/1.1"):
        problems.append(f"요청 줄: {lines[0][:60]}")
    if body:
        problems.append("본문이 있다")
    pairs = [line.split(": ", 1) for line in lines[1:]]
    names = [pair[0] for pair in pairs]
    if names != HEADER_NAMES:
        problems.append(f"머리글 이름: {names}")
    values = {pair[0]: pair[1] if len(pair) > 1 else "" for pair in pairs}
    for name, wanted in FIXED.items():
        if values.get(name) != wanted:
            problems.append(f"{name}: {values.get(name)!r}")
    host = values.get("Host", "")
    if host not in ALLOWED_HOSTS:
        problems.append(f"호스트: {host}")
    if host == "github.com":
        if "?" in target or not any(pattern.fullmatch(target) for pattern in ROUTE_PATTERNS):
            problems.append(f"길: {target[:80]}")
    elif host == fs.CDN_HOST and not CDN_PATTERN.fullmatch(target):
        problems.append(f"자산 길: {target[:80]}")
    return problems


def good_request(host="github.com", target=None):
    target = target or f"{fs.BASE}/latest/download/update-manifest.json"
    lines = [f"GET {target} HTTP/1.1", f"Host: {host}"] + [f"{name}: {value}" for name, value in FIXED.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


class ChecksCatchMutationsTest(unittest.TestCase):
    def test_the_checker_accepts_a_good_request_and_catches_each_kind_of_drift(self):
        self.assertEqual(request_problems(good_request()), [])
        self.assertEqual(request_problems(good_request(fs.CDN_HOST, fs.cdn_path("update-manifest.json"))), [])
        good = good_request()
        drifted = {
            "버전이 든 사용자 에이전트": good.replace(b"User-Agent: ChanceBlogDesktop\r\n", b"User-Agent: ChanceBlogDesktop/1.0.0\r\n"), "Referer": good.replace(b"Connection: close\r\n", b"Connection: close\r\nReferer: https://example.invalid/\r\n"),
            "Cookie": good.replace(b"Connection: close\r\n", b"Connection: close\r\nCookie: a=b\r\n"), "Authorization": good.replace(b"Connection: close\r\n", b"Connection: close\r\nAuthorization: Bearer x\r\n"),
            "다른 Accept": good.replace(b"Accept: */*", b"Accept: application/json"), "압축 허용": good.replace(b"identity", b"gzip"), "POST": good.replace(b"GET ", b"POST ", 1),
            "본문": good + b"title=x", "다른 호스트": good.replace(b"Host: github.com", b"Host: evil.example.test"), "질의": good.replace(b"update-manifest.json HTTP", b"update-manifest.json?u=1 HTTP"),
            "다른 길": good.replace(b"update-manifest.json", b"other.json"), "머리글 순서": good.replace(b"Accept: */*\r\nAccept-Encoding: identity", b"Accept-Encoding: identity\r\nAccept: */*"),
            "운영체제 이름": good.replace(b"ChanceBlogDesktop\r\n", b"ChanceBlogDesktop (Windows NT 10.0)\r\n"),
        }
        for label, raw in drifted.items():
            with self.subTest(label=label):
                self.assertTrue(request_problems(raw), label)


class WholeFlowRequestsTest(flow.FlowCase):
    switches = ("NET_UPDATE_CHECK", "UPDATE_APPLY")

    def setUp(self):
        super().setUp()
        projects.new_project(self.ctx, CANARY_TITLE, "본문 " + CANARY_KEY)
        (self.ctx.workspace.root / "notes.txt").write_text(CANARY_KEY, encoding="utf-8")

    def secrets_here(self):
        try:
            user = getpass.getuser()
        except Exception:                   # noqa: BLE001 - 사용자 이름을 알 수 없는 환경에서도 시험이 돈다
            user = ""
        found = {user, os.environ.get("USERNAME", "?"), os.environ.get("COMPUTERNAME", "?"), platform.node(), str(Path.home()), str(self.ctx.workspace.root), str(self.tmp), self.tmp.name,
                 sys.executable, tempfile.gettempdir(), CANARY_TITLE, CANARY_KEY}
        return sorted(item for item in found if len(item) >= 4)

    def test_a_whole_update_check_download_apply_walk_sends_only_allowed_requests_and_leaks_nothing(self):
        session = update_flow.UpdateSession(self.ctx, install_kind="velopack", current_version="1.0.0", keyring=fs.RING, adapter=fs.FakeAdapter(self.folder))
        session.check()
        session.download()
        session.apply(confirmed=True)
        self.assertEqual(len(self.harness.made), 10, "확인 여섯(매니페스트·서명 × 최신 길 → 태그 길 → 자산 호스트) + 파일 둘 × 둘(태그 길 → 자산 호스트) — 적용은 접속하지 않는다")
        raw_all = b""
        for sock in self.harness.made:
            raw = bytes(sock.sent)
            raw_all += raw
            self.assertEqual(request_problems(raw), [], raw[:200])
        text = raw_all.decode("latin-1")
        for secret in self.secrets_here():
            self.assertNotIn(secret.lower(), text.lower(), f"요청에 새어 나갔다: {secret[:12]}")
        self.assertEqual(set(self.server.hosts()), ALLOWED_HOSTS)
        self.assertNotRegex(text, r"(?i)cookie|referer|authorization|origin:|x-|accept-language")

    def test_the_user_agent_never_carries_the_version_even_when_the_app_version_is_a_real_number(self):
        self.check()
        wire = bytes(self.harness.made[0].sent).decode("ascii")
        self.assertIn("User-Agent: ChanceBlogDesktop\r\n", wire)
        self.assertNotRegex(wire, r"[0-9]+\.[0-9]+\.[0-9]+")

    def test_a_state_file_with_a_notice_and_last_check_does_not_change_what_is_sent(self):
        state.write_state(self.folder, state.State(last_seq=5, last_seen_utc="2026-12-01T00:00:00Z", last_check=state.LastCheck("2026-12-01T00:00:00Z", "UP_TO_DATE", "1.0.0", ""), notice="not_applied"))
        self.check()
        for sock in self.harness.made:
            self.assertEqual(request_problems(bytes(sock.sent)), [])

    def test_no_request_is_made_by_a_check_when_the_switch_is_off_and_the_wire_stays_empty(self):
        with mock.patch.object(update_flow.capabilities, "NET_UPDATE_CHECK", False):
            self.assertEqual(flow.code_of(self.check), "NETWORK_DISABLED")
        self.assertEqual((self.harness.made, self.server.requests), ([], []))


class SourceCodeNeverSendsLocalDataTest(unittest.TestCase):
    def test_no_update_module_formats_a_request_from_local_data(self):
        """주소는 상수(저장소·릴리스 길)와 검증된 태그·이름으로만 만든다 — 데이터 폴더·설정·환경 변수·사용자 이름을 읽는 코드가 `source.py`·`update_flow.py` 의 주소·머리글 만들기에 없다."""
        for rel in ("update/source.py", "net/endpoints.py"):
            text = (ROOT / "src" / "chanceblog_desktop" / rel).read_text(encoding="utf-8")
            for word in ("getpass", "os.environ", "platform.", "expanduser", "Path.home", "getlogin", "gethostname"):
                if rel == "net/endpoints.py" and word == "Path.home":
                    continue
                self.assertNotIn(word, text, f"{rel}: {word}")


if __name__ == "__main__":
    unittest.main()
