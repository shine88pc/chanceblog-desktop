"""설치 도구 시험의 도구 받기(`packaging/spike/fetch_tools.py` — 러너 전용, 결정 D-701)와 잠금 표(`tools.lock.json`)의 시험 — **네트워크 없이** 돈다(가짜 응답·가짜 https 핸들러를 끼운다).

지키는 것: ① 잠금 표의 값이 총괄이 공개 채널에서 읽은 값 그대로이고 호스트가 정확히 둘(`github.com`·`pypi.org`)이다 ② 직접 받는 곳은 `github.com` 하나뿐이고 리디렉션은 GitHub 의 공식 자산 호스트 둘까지만
(닮은 이름·하위 이름·http·사용자 정보·포트·밖으로 가는 주소는 그 자리에서 거절, 횟수도 제한) ③ 받은 파일은 크기와 SHA-256 이 잠금 값과 같을 때만 남는다(다르면 지우고 실패 — 읽는 양도 잠금 크기를 넘지 못하고
시간 상한이 있다) ④ 일시적인 오류만 다시 한다(해시 불일치·허용 밖 호스트·크기 초과·시간 상한은 바로 실패) ⑤ 이미 맞는 파일은 다시 받지 않고 pip 항목은 받지 않는다 ⑥ 표준 라이브러리만 쓰고 비밀·인증서 끄기가 없다.
"""
import ast
import contextlib
import email.message
import hashlib
import http.client
import io
import json
import re
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_spike_support as support  # noqa: E402

fetch = support.load("fetch_tools")
LOCK_PATH = support.SPIKE / "tools.lock.json"
DATA = b"vpk-package-bytes-" * 40


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tool_for(data=DATA, **extra):
    base = {"key": "vpk-nupkg", "kind": "direct", "host": "github.com", "path": "/owner/repo/releases/download/1.0.0/vpk.1.0.0.nupkg", "file": "vpk.1.0.0.nupkg", "version": "1.0.0",
            "bytes": len(data), "sha256": sha(data)}
    base.update(extra)
    return base


def small_lock(data=DATA):
    wheel = {"key": "velopack-wheel", "kind": "pip", "host": "pypi.org", "file_host": "files.pythonhosted.org", "project": "velopack", "file": "velopack-1.0.0-cp38-abi3-win_amd64.whl",
             "version": "1.0.0", "bytes": 1234, "sha256": "a" * 64}
    return {"schema": 1, "tools": [tool_for(data), wheel]}


class FakeResponse:
    def __init__(self, chunks, url="https://release-assets.githubusercontent.com/blob", status=200, headers=None):
        self.chunks, self.url, self.status, self.reads = iter(chunks), url, status, 0
        self.headers = email.message.Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        self.reads += 1
        return next(self.chunks, b"")

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, *items):
        self.items, self.requests = list(items), []

    def open(self, request, timeout=None):
        self.requests.append({"url": request.full_url, "headers": {key.lower(): value for key, value in request.header_items()}, "timeout": timeout})
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def good(data=DATA, **extra):
    return FakeResponse([data[:100], data[100:]], **extra)


def run_main(argv, opener=None, clock=None):
    out, err, sleeps = io.StringIO(), io.StringIO(), []
    kwargs = {"clock": clock} if clock else {}
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fetch.main(argv, opener=opener, sleep=sleeps.append, **kwargs)
    return code, out.getvalue(), err.getvalue(), sleeps


class NoRealNetwork(unittest.TestCase):
    """이 시험 모듈의 모든 시험은 진짜 접속을 만들면 곧바로 오류가 난다(가짜만 쓴다)."""

    def setUp(self):
        guard = mock.patch.object(socket.socket, "connect", side_effect=AssertionError("진짜 접속을 시도했다"))
        guard.start()
        self.addCleanup(guard.stop)


class RealLockTest(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    def test_the_real_lock_follows_its_own_shape(self):
        self.assertEqual(fetch.lock_problems(self.lock), [])

    def test_the_values_are_exactly_the_ones_the_coordinator_read_on_2026_11_24(self):
        by_key = {tool["key"]: tool for tool in self.lock["tools"]}
        self.assertEqual(sorted(by_key), ["velopack-wheel", "vpk-nupkg"])
        vpk, wheel = by_key["vpk-nupkg"], by_key["velopack-wheel"]
        self.assertEqual((vpk["file"], vpk["version"], vpk["bytes"], vpk["sha256"]),
                         ("vpk.1.2.161.nupkg", "1.2.161", 146884263, "2b56ce117f803fc70c103cb423bd040e395e40370f6ff6e10818e9ff9c26a323"))
        self.assertEqual((wheel["file"], wheel["version"], wheel["bytes"], wheel["sha256"]),
                         ("velopack-1.2.161-cp38-abi3-win_amd64.whl", "1.2.161", 1363140, "3a85b4a39c7644d06dafa44bd197d1e88d429f3f05ead57031552cf17ffcf36e"))
        self.assertEqual(vpk["path"], "/velopack/velopack/releases/download/1.2.161/vpk.1.2.161.nupkg")
        self.assertEqual((vpk["kind"], vpk["host"]), ("direct", "github.com"))
        self.assertEqual((wheel["kind"], wheel["host"], wheel["file_host"], wheel["project"]), ("pip", "pypi.org", "files.pythonhosted.org", "velopack"))

    def test_there_are_exactly_two_tools_from_exactly_two_fixed_hosts(self):
        self.assertEqual(len(self.lock["tools"]), 2)
        self.assertEqual(sorted(tool["host"] for tool in self.lock["tools"]), ["github.com", "pypi.org"])
        self.assertEqual(self.lock["values_read_on"], "2026-11-24")

    def test_the_lock_text_has_no_address_scheme_and_no_secret_words(self):
        text = LOCK_PATH.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(?i)(https?|ftp)://|www[.]", text))
        self.assertNotIn(chr(0x7E), text)
        for word in ("token", "secret", "password", "Authorization"):
            self.assertNotIn(word, text)

    def test_the_wheel_is_old_enough_for_the_fourteen_day_rule(self):
        self.assertEqual(self.lock["tools"][1]["uploaded_on"], "2026-09-29")           # 설계서: 올린 지 14일 이상인 것만(1.2.161 은 56일)


class LockShapeTest(unittest.TestCase):
    def problems(self, mutate):
        lock = small_lock()
        mutate(lock)
        return fetch.lock_problems(lock)

    def test_the_small_lock_is_fine(self):
        self.assertEqual(fetch.lock_problems(small_lock()), [])

    def test_each_bad_edit_is_caught(self):
        edits = {
            "schema 2": lambda lock: lock.update(schema=2),
            "tools 없음": lambda lock: lock.update(tools=[]),
            "tools 가 목록이 아님": lambda lock: lock.update(tools={}),
            "다른 호스트": lambda lock: lock["tools"][0].update(host="evil.example.com"),
            "하위 호스트": lambda lock: lock["tools"][0].update(host="api.github.com"),
            "닮은 호스트": lambda lock: lock["tools"][0].update(host="github.com.evil.example"),
            "경로에 ..": lambda lock: lock["tools"][0].update(path="/a/../b/vpk.1.0.0.nupkg"),
            "경로에 질의": lambda lock: lock["tools"][0].update(path="/a/b/vpk.1.0.0.nupkg?x=1"),
            "경로가 file 로 안 끝남": lambda lock: lock["tools"][0].update(path="/a/b/other.nupkg"),
            "경로가 슬래시로 안 시작": lambda lock: lock["tools"][0].update(path="a/b/vpk.1.0.0.nupkg"),
            "경로 이중 슬래시": lambda lock: lock["tools"][0].update(path="/a//vpk.1.0.0.nupkg"),
            "파일 이름에 슬래시": lambda lock: lock["tools"][0].update(file="a/vpk.1.0.0.nupkg"),
            "파일 이름 점점": lambda lock: lock["tools"][0].update(file="..vpk"),
            "bytes 0": lambda lock: lock["tools"][0].update(bytes=0),
            "bytes 상한 초과": lambda lock: lock["tools"][0].update(bytes=fetch.SIZE_CEILING + 1),
            "bytes 글자": lambda lock: lock["tools"][0].update(bytes="146884263"),
            "bytes 불리언": lambda lock: lock["tools"][0].update(bytes=True),
            "sha 대문자": lambda lock: lock["tools"][0].update(sha256="A" * 64),
            "sha 짧음": lambda lock: lock["tools"][0].update(sha256="a" * 63),
            "버전 모양": lambda lock: lock["tools"][0].update(version="latest"),
            "kind 모름": lambda lock: lock["tools"][0].update(kind="curl"),
            "key 겹침": lambda lock: lock["tools"][1].update(key="vpk-nupkg"),
            "file 겹침": lambda lock: lock["tools"][1].update(file="vpk.1.0.0.nupkg"),
            "pip 호스트 틀림": lambda lock: lock["tools"][1].update(host="pypi.example"),
            "pip 파일 호스트 틀림": lambda lock: lock["tools"][1].update(file_host="evil.example"),
            "pip 프로젝트 이상": lambda lock: lock["tools"][1].update(project="a b"),
        }
        for name, edit in edits.items():
            with self.subTest(edit=name):
                self.assertTrue(self.problems(edit), name + " 는 걸려야 한다")


class HostRuleTest(unittest.TestCase):
    def test_the_two_constants_are_exact_and_not_suffix_rules(self):
        self.assertEqual(fetch.FIXED_HOSTS, ("github.com",))
        self.assertEqual(fetch.REDIRECT_HOSTS, ("release-assets.githubusercontent.com", "objects.githubusercontent.com"))
        for host in fetch.FIXED_HOSTS + fetch.REDIRECT_HOSTS:
            self.assertFalse(host.startswith((".", "*")), host)

    def test_host_of_reads_only_plain_https_addresses(self):
        cases = {
            "https://github.com/a/b": "github.com",
            "https://GitHub.COM./a": "github.com",
            "https://release-assets.githubusercontent.com/x?sig=1&y=2": "release-assets.githubusercontent.com",
            "https://github.com:443/a": "github.com",
            "http://github.com/a": "",
            "https://user@github.com/a": "",
            "https://user:pw@github.com/a": "",
            "https://github.com:8443/a": "",
            "https://github.com:bad/a": "",
            "ftp://github.com/a": "",
            "//github.com/a": "",
            "github.com/a": "",
            "https:///a": "",
            "": "",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(fetch.host_of(url), expected)

    def test_look_alike_hosts_are_not_in_the_lists(self):
        for url in ("https://github.com.evil.example/a", "https://evilgithub.com/a", "https://api.github.com/a", "https://githubusercontent.com/a",
                    "https://x.release-assets.githubusercontent.com/a", "https://release-assets.githubusercontent.com.evil.example/a", "https://objects.githubusercontent.com.cn/a"):
            with self.subTest(url=url):
                self.assertNotIn(fetch.host_of(url), fetch.FIXED_HOSTS + fetch.REDIRECT_HOSTS)

    def test_guarded_redirect_follows_only_the_two_asset_hosts(self):
        handler = fetch.GuardedRedirect()
        request = urllib.request.Request("https://github.com/a/b")
        for good_url in ("https://release-assets.githubusercontent.com/github-production-release-asset/1?sp=r", "https://objects.githubusercontent.com/github-production-release-asset-2e65be/1"):
            with self.subTest(url=good_url):
                new = handler.redirect_request(request, io.BytesIO(b""), 302, "Found", {}, good_url)
                self.assertEqual(new.full_url, good_url)
        for bad_url in ("https://evil.example/a", "http://release-assets.githubusercontent.com/a", "https://github.com/other", "https://api.github.com/a",
                        "https://release-assets.githubusercontent.com.evil.example/a", "https://user@release-assets.githubusercontent.com/a", "https://release-assets.githubusercontent.com:81/a",
                        "https://sub.objects.githubusercontent.com/a", "file:///etc/passwd", "ftp://objects.githubusercontent.com/a"):
            with self.subTest(url=bad_url):
                with self.assertRaises(fetch.FetchError):
                    handler.redirect_request(request, io.BytesIO(b""), 302, "Found", {}, bad_url)

    def test_the_redirect_count_is_bounded(self):
        self.assertEqual(fetch.GuardedRedirect.max_redirections, fetch.MAX_REDIRECTS)
        self.assertLessEqual(fetch.MAX_REDIRECTS, 5)


class FetchFileTest(NoRealNetwork):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = str(Path(self.tmp.name) / "out" / "vpk.1.0.0.nupkg")

    def leftovers(self):
        return sorted(path.name for path in Path(self.target).parent.iterdir()) if Path(self.target).parent.exists() else []

    def test_a_matching_download_is_kept_and_nothing_else_is_left(self):
        opener = FakeOpener(good())
        fetch.fetch_file(tool_for(), self.target, opener)
        self.assertEqual(Path(self.target).read_bytes(), DATA)
        self.assertEqual(self.leftovers(), ["vpk.1.0.0.nupkg"])
        request = opener.requests[0]
        self.assertEqual(request["url"], "https://github.com/owner/repo/releases/download/1.0.0/vpk.1.0.0.nupkg")
        self.assertEqual(request["timeout"], fetch.SOCKET_SECONDS)
        self.assertTrue(request["headers"]["user-agent"].startswith("chanceblog-installer-spike/"))
        self.assertNotIn("authorization", request["headers"])
        self.assertNotIn("cookie", request["headers"])

    def test_a_different_sha256_removes_the_file_and_is_not_retried(self):
        wrong = DATA[:-1] + b"X"
        opener = FakeOpener(good(wrong))
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(tool_for(), self.target, opener)
        self.assertFalse(caught.exception.retry)
        self.assertIn("SHA-256", str(caught.exception))
        self.assertEqual(self.leftovers(), [])
        opener = FakeOpener(good(wrong))
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_with_retries(tool_for(), self.target, opener, sleep=lambda seconds: self.fail("해시 불일치를 다시 하면 안 된다"))
        self.assertEqual(len(opener.requests), 1)

    def test_a_shorter_download_fails_and_may_be_retried(self):
        opener = FakeOpener(FakeResponse([DATA[:50]]))
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(tool_for(), self.target, opener)
        self.assertTrue(caught.exception.retry)
        self.assertEqual(self.leftovers(), [])

    def test_a_longer_download_stops_at_the_locked_size_and_never_reads_on(self):
        chunks = [DATA, b"z" * 10]
        response = FakeResponse(chunks)
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(tool_for(), self.target, FakeOpener(response))
        self.assertIn("보다 크다", str(caught.exception))
        self.assertFalse(caught.exception.retry)
        self.assertEqual(response.reads, 2)                      # 잠금 크기를 넘긴 그 읽기에서 멈춘다 — 다음 읽기는 없다
        endless = FakeResponse(iter(lambda: b"y" * 1000, None))
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_file(tool_for(), self.target, FakeOpener(endless))
        self.assertLess(endless.reads, 10)                       # 끝없는 응답이어도 몇 번 읽지 않는다
        self.assertEqual(self.leftovers(), [])

    def test_a_content_length_that_differs_is_refused_before_any_body_is_read(self):
        response = FakeResponse([DATA], headers={"Content-Length": str(len(DATA) + 1)})
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(tool_for(), self.target, FakeOpener(response))
        self.assertIn("알려 준 크기", str(caught.exception))
        self.assertEqual(response.reads, 0)
        self.assertEqual(self.leftovers(), [])

    def test_a_matching_content_length_is_fine_and_a_garbage_one_is_ignored_then_checked_by_the_body(self):
        fetch.fetch_file(tool_for(), self.target, FakeOpener(good(headers={"Content-Length": str(len(DATA))})))
        self.assertEqual(Path(self.target).read_bytes(), DATA)
        Path(self.target).unlink()
        fetch.fetch_file(tool_for(), self.target, FakeOpener(good(headers={"Content-Length": "abc"})))
        self.assertEqual(Path(self.target).read_bytes(), DATA)

    def test_an_encoded_response_is_refused_but_identity_is_fine(self):
        for encoding in ("gzip", "br", "deflate"):
            with self.subTest(encoding=encoding):
                with self.assertRaises(fetch.FetchError):
                    fetch.fetch_file(tool_for(), self.target, FakeOpener(good(headers={"Content-Encoding": encoding})))
                self.assertEqual(self.leftovers(), [])
        fetch.fetch_file(tool_for(), self.target, FakeOpener(good(headers={"Content-Encoding": "identity"})))
        self.assertEqual(Path(self.target).read_bytes(), DATA)

    def test_a_final_host_outside_the_lists_is_refused(self):
        for url in ("https://evil.example/blob", "https://api.github.com/blob", "http://release-assets.githubusercontent.com/blob", "https://release-assets.githubusercontent.com.evil.example/b"):
            with self.subTest(url=url):
                with self.assertRaises(fetch.FetchError) as caught:
                    fetch.fetch_file(tool_for(), self.target, FakeOpener(good(url=url)))
                self.assertIn("허용 목록 밖", str(caught.exception))
                self.assertEqual(self.leftovers(), [])

    def test_the_start_address_must_be_a_fixed_host_even_if_the_lock_check_was_skipped(self):
        opener = FakeOpener(good())
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_file(tool_for(host="evil.example.com"), self.target, opener)
        self.assertEqual(opener.requests, [])                     # 요청 자체를 보내지 않는다

    def test_a_non_200_status_may_be_retried(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(tool_for(), self.target, FakeOpener(FakeResponse([DATA], status=206)))
        self.assertTrue(caught.exception.retry)

    def test_the_total_time_limit_stops_a_slow_download(self):
        ticks = iter(range(0, 100000, 400))
        clock = lambda: next(ticks)  # noqa: E731
        response = FakeResponse([DATA[:60], DATA[60:120], DATA[120:]])
        deadline = clock() + fetch.TOTAL_SECONDS
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(tool_for(), self.target, FakeOpener(response), clock=clock, deadline=deadline)
        self.assertIn("시간 상한", str(caught.exception))
        self.assertFalse(caught.exception.retry)
        self.assertLess(response.reads, 4)
        self.assertEqual(self.leftovers(), [])

    def test_the_time_limits_are_real_numbers(self):
        self.assertLessEqual(fetch.SOCKET_SECONDS, 120)
        self.assertLessEqual(fetch.TOTAL_SECONDS, 1800)
        self.assertGreater(fetch.TOTAL_SECONDS, fetch.SOCKET_SECONDS)


class RetryTest(NoRealNetwork):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = str(Path(self.tmp.name) / "vpk.1.0.0.nupkg")

    def run_retry(self, *items, **kwargs):
        sleeps = []
        opener = FakeOpener(*items)
        try:
            attempts = fetch.fetch_with_retries(tool_for(), self.target, opener, sleep=sleeps.append, say=lambda text: None, **kwargs)
        except fetch.FetchError as error:
            return opener, sleeps, error
        return opener, sleeps, attempts

    def test_a_transient_error_is_retried_then_succeeds(self):
        for failure in (urllib.error.URLError("reset"), TimeoutError("timed out"), http.client.IncompleteRead(b"x"), ConnectionResetError("reset"),
                        urllib.error.HTTPError("https://github.com/a", 503, "Service Unavailable", {}, io.BytesIO(b""))):
            with self.subTest(failure=type(failure).__name__):
                opener, sleeps, result = self.run_retry(failure, good())
                self.assertEqual(result, 2)
                self.assertEqual(sleeps, [fetch.WAITS[0]])
                self.assertEqual(len(opener.requests), 2)
                Path(self.target).unlink()

    def test_it_gives_up_after_three_attempts(self):
        opener, sleeps, error = self.run_retry(*[urllib.error.URLError("x")] * 3)
        self.assertIsInstance(error, fetch.FetchError)
        self.assertEqual(len(opener.requests), fetch.ATTEMPTS)
        self.assertEqual(sleeps, list(fetch.WAITS))
        self.assertIn("vpk-nupkg", str(error))
        self.assertFalse(Path(self.target).exists())

    def test_these_errors_are_never_retried(self):
        for failure in (urllib.error.HTTPError("https://github.com/a", 404, "Not Found", {}, io.BytesIO(b"")), urllib.error.HTTPError("https://github.com/a", 403, "Forbidden", {}, io.BytesIO(b"")),
                        urllib.error.HTTPError("https://github.com/a", 302, "redirect error", {}, io.BytesIO(b"")), fetch.FetchError("허용 목록 밖으로 넘어가는 주소를 거절했다")):
            with self.subTest(failure=str(failure)):
                opener, sleeps, error = self.run_retry(failure)
                self.assertIsInstance(error, fetch.FetchError)
                self.assertEqual(len(opener.requests), 1)
                self.assertEqual(sleeps, [])

    def test_429_and_408_are_retried(self):
        for code in (429, 408, 500, 502):
            with self.subTest(code=code):
                opener, sleeps, result = self.run_retry(urllib.error.HTTPError("https://github.com/a", code, "x", {}, io.BytesIO(b"")), good())
                self.assertEqual(result, 2)
                Path(self.target).unlink()

    def test_no_retry_once_the_total_time_is_used_up(self):
        ticks = iter([1000, 2000, 3000, 4000, 5000])
        opener, sleeps, error = self.run_retry(urllib.error.URLError("x"), good(), clock=lambda: next(ticks), deadline=900)
        self.assertIsInstance(error, fetch.FetchError)
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(sleeps, [])


class RedirectThroughRealUrllibTest(NoRealNetwork):
    """진짜 urllib 의 리디렉션 장치를 그대로 쓰되 https 접속만 가짜 핸들러로 바꾼다(핸들러 연결이 틀리면 여기서 빨개진다)."""

    START = "https://github.com/owner/repo/releases/download/1.0.0/vpk.1.0.0.nupkg"
    ASSET = "https://release-assets.githubusercontent.com/github-production-release-asset/42?sp=r&sig=abc"

    def build(self, routes):
        log = []

        def raw(status, headers, body):
            reason = {200: "OK", 302: "Found"}[status]
            head = "HTTP/1.1 %d %s\r\n" % (status, reason) + "".join("%s: %s\r\n" % item for item in headers.items()) + "Content-Length: %d\r\n\r\n" % len(body)
            return head.encode("ascii") + body

        class FakeSocket:
            def __init__(self, data):
                self.data = io.BytesIO(data)

            def makefile(self, *args, **kwargs):
                return self.data

        class FakeHTTPS(urllib.request.HTTPSHandler):
            def https_open(self, request):
                log.append(request.full_url)
                status, headers, body = routes[request.full_url]
                response = http.client.HTTPResponse(FakeSocket(raw(status, headers, body)))
                response.begin()
                response.url = request.full_url
                response.msg = response.reason
                return response

        return urllib.request.build_opener(fetch.GuardedRedirect(), FakeHTTPS()), log

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = str(Path(self.tmp.name) / "vpk.1.0.0.nupkg")

    def test_the_github_release_chain_to_the_asset_host_works(self):
        opener, log = self.build({self.START: (302, {"Location": self.ASSET}, b""), self.ASSET: (200, {}, DATA)})
        attempts = fetch.fetch_with_retries(tool_for(), self.target, opener, sleep=lambda seconds: None)
        self.assertEqual(attempts, 1)
        self.assertEqual(Path(self.target).read_bytes(), DATA)
        self.assertEqual(log, [self.START, self.ASSET])

    def test_the_older_objects_host_also_works(self):
        asset = "https://objects.githubusercontent.com/github-production-release-asset-2e65be/42?X-Amz-Signature=abc"
        opener, log = self.build({self.START: (302, {"Location": asset}, b""), asset: (200, {}, DATA)})
        fetch.fetch_with_retries(tool_for(), self.target, opener, sleep=lambda seconds: None)
        self.assertEqual(Path(self.target).read_bytes(), DATA)

    def test_a_redirect_to_another_host_is_refused_without_a_second_request(self):
        for evil in ("https://evil.example/blob", "https://github.com.evil.example/blob", "http://release-assets.githubusercontent.com/blob", "https://api.github.com/blob"):
            with self.subTest(target=evil):
                opener, log = self.build({self.START: (302, {"Location": evil}, b""), evil: (200, {}, DATA)})
                with self.assertRaises(fetch.FetchError) as caught:
                    fetch.fetch_with_retries(tool_for(), self.target, opener, sleep=lambda seconds: self.fail("다시 하면 안 된다"))
                self.assertIn("허용 목록", str(caught.exception))
                self.assertEqual(log, [self.START])
                self.assertFalse(Path(self.target).exists())

    def test_a_redirect_loop_stops_and_is_not_retried(self):
        loop_a = "https://release-assets.githubusercontent.com/a"
        loop_b = "https://release-assets.githubusercontent.com/b"
        routes = {self.START: (302, {"Location": loop_a}, b""), loop_a: (302, {"Location": loop_b}, b""), loop_b: (302, {"Location": loop_a}, b"")}
        opener, log = self.build(routes)
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_with_retries(tool_for(), self.target, opener, sleep=lambda seconds: self.fail("다시 하면 안 된다"))
        self.assertLessEqual(len(log), fetch.MAX_REDIRECTS + 1)

    def test_the_asset_host_serving_other_bytes_is_caught_by_the_hash(self):
        opener, log = self.build({self.START: (302, {"Location": self.ASSET}, b""), self.ASSET: (200, {}, b"Z" * len(DATA))})
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_with_retries(tool_for(), self.target, opener, sleep=lambda seconds: None)
        self.assertIn("SHA-256", str(caught.exception))
        self.assertFalse(Path(self.target).exists())


class CheckFileTest(unittest.TestCase):
    def test_check_file_names_the_first_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "f.bin")
            self.assertIn("없다", fetch.check_file(path, tool_for()))
            Path(path).write_bytes(DATA)
            self.assertEqual(fetch.check_file(path, tool_for()), "")
            Path(path).write_bytes(DATA + b"x")
            self.assertIn("크기", fetch.check_file(path, tool_for()))
            Path(path).write_bytes(DATA[:-1] + b"x")
            self.assertIn("SHA-256", fetch.check_file(path, tool_for()))


class MainTest(NoRealNetwork):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = str(Path(self.tmp.name) / "tools")
        self.lock = str(Path(self.tmp.name) / "tools.lock.json")
        Path(self.lock).write_text(json.dumps(small_lock()), encoding="utf-8")

    def args(self, *extra):
        return ["--dest", self.dest, "--lock", self.lock, *extra]

    def test_a_good_run_downloads_the_direct_tool_only_and_writes_a_small_log(self):
        opener = FakeOpener(good())
        code, out, err, sleeps = run_main(self.args(), opener)
        self.assertEqual((code, err, sleeps), (0, "", []))
        self.assertEqual(len(opener.requests), 1)                 # pip 항목(휠)은 받지 않는다
        self.assertEqual((Path(self.dest) / "vpk.1.0.0.nupkg").read_bytes(), DATA)
        self.assertIn("pip 로 받는 도구", out)
        log = json.loads((Path(self.dest) / fetch.LOG_NAME).read_text(encoding="utf-8"))
        self.assertEqual(log["fetched"][0]["key"], "vpk-nupkg")
        self.assertTrue(log["fetched"][0]["sha256_ok"])
        self.assertEqual(sorted(path.name for path in Path(self.dest).iterdir()), [fetch.LOG_NAME, "vpk.1.0.0.nupkg"])

    def test_a_second_run_reuses_the_matching_file_and_makes_no_request(self):
        run_main(self.args(), FakeOpener(good()))
        opener = FakeOpener()
        code, out, err, sleeps = run_main(self.args(), opener)
        self.assertEqual(code, 0)
        self.assertEqual(opener.requests, [])
        self.assertIn("이미 있고", out)

    def test_a_file_that_differs_is_downloaded_again(self):
        Path(self.dest).mkdir(parents=True)
        (Path(self.dest) / "vpk.1.0.0.nupkg").write_bytes(b"old")
        opener = FakeOpener(good())
        self.assertEqual(run_main(self.args(), opener)[0], 0)
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual((Path(self.dest) / "vpk.1.0.0.nupkg").read_bytes(), DATA)

    def test_a_hash_mismatch_exits_one_and_leaves_no_tool_file(self):
        code, out, err, sleeps = run_main(self.args(), FakeOpener(good(b"Q" * len(DATA))))
        self.assertEqual(code, 1)
        self.assertIn("SHA-256", err)
        self.assertEqual(sleeps, [])
        self.assertFalse(list(Path(self.dest).glob("vpk*")))
        self.assertFalse((Path(self.dest) / fetch.LOG_NAME).exists())

    def test_check_only_never_downloads(self):
        opener = FakeOpener()
        code, out, err, sleeps = run_main(self.args("--check-only"), opener)
        self.assertEqual(code, 1)
        self.assertEqual(opener.requests, [])
        run_main(self.args(), FakeOpener(good()))
        self.assertEqual(run_main(self.args("--check-only"), FakeOpener())[0], 0)

    def test_a_missing_or_broken_lock_exits_two(self):
        self.assertEqual(run_main(["--dest", self.dest, "--lock", str(Path(self.tmp.name) / "nope.json")], FakeOpener())[0], 2)
        Path(self.lock).write_text("{ not json", encoding="utf-8")
        self.assertEqual(run_main(self.args(), FakeOpener())[0], 2)
        bad = small_lock()
        bad["tools"][0]["host"] = "evil.example.com"
        Path(self.lock).write_text(json.dumps(bad), encoding="utf-8")
        opener = FakeOpener()
        code, out, err, sleeps = run_main(self.args(), opener)
        self.assertEqual(code, 2)
        self.assertEqual(opener.requests, [])
        self.assertIn("잠금 파일 점검 실패", err)

    def test_the_real_lock_is_read_and_the_first_request_goes_to_the_fixed_address(self):
        opener = FakeOpener(urllib.error.HTTPError("https://github.com/x", 404, "Not Found", {}, io.BytesIO(b"")))
        code, out, err, sleeps = run_main(["--dest", self.dest], opener)
        self.assertEqual(code, 1)
        self.assertEqual(opener.requests[0]["url"], "https://github.com/velopack/velopack/releases/download/1.2.161/vpk.1.2.161.nupkg")
        self.assertEqual(len(opener.requests), 1)                 # 404 는 다시 하지 않는다

    def test_the_whole_run_has_a_time_limit_that_a_slow_run_hits(self):
        ticks = iter([0, 0, 1000, 2000, 3000, 4000, 5000, 6000])
        code, out, err, sleeps = run_main(self.args(), FakeOpener(good(), good()), clock=lambda: next(ticks))
        self.assertEqual(code, 1)
        self.assertIn("시간 상한", err)


class SourceRulesTest(unittest.TestCase):
    """fetch_tools.py 는 표준 라이브러리만 쓰고, 비밀·인증서 끄기·셸 실행·소켓 직접 사용이 없다."""

    @classmethod
    def setUpClass(cls):
        cls.source = (support.SPIKE / "fetch_tools.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def imported(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
        return names

    def test_only_standard_library_modules_are_imported(self):
        self.assertTrue(self.imported() <= set(sys.stdlib_module_names), sorted(self.imported() - set(sys.stdlib_module_names)))

    def test_no_shell_no_socket_no_ssl_no_subprocess(self):
        for name in ("subprocess", "socket", "ssl", "ctypes", "shutil", "webbrowser", "ftplib", "smtplib"):
            self.assertNotIn(name, self.imported(), name)
        for word in ("os.system", "os.popen", "eval(", "exec(", "_create_unverified_context", "CERT_NONE", "check_hostname", "verify=False", "Authorization", "Cookie", "GITHUB_TOKEN", "secrets"):
            self.assertNotIn(word, self.source, word)

    def test_the_file_only_names_two_fixed_origins(self):
        hosts = set(re.findall(r"(?<![\w.])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org)(?![\w-])", self.source))
        self.assertTrue(hosts <= {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "pypi.org", "files.pythonhosted.org", "githubusercontent.com"}, sorted(hosts))

    def test_docstring_and_comments_have_no_address_scheme_no_tilde_no_double_brace(self):
        docstring = ast.get_docstring(self.tree)
        comments = "\n".join(line.split("#", 1)[1] for line in self.source.splitlines() if "#" in line and not line.lstrip().startswith(('"', "'")))
        for text in (docstring, comments):
            self.assertIsNone(re.search(r"(?i)(https?|ftp)://|www[.]", text))
            self.assertNotIn(chr(0x7E), text)
            self.assertNotIn("{{", text)

    def test_the_lock_and_the_downloader_agree_on_the_default_path(self):
        self.assertEqual(Path(fetch.DEFAULT_LOCK), LOCK_PATH)


if __name__ == "__main__":
    unittest.main()
