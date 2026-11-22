"""글자 읽기 추가 도구의 모델 받기(`ocr_addon/fetch_models.py` — 빌드 전용, 결정 D-529)의 시험 — **네트워크 없이** 돈다(가짜 응답을 끼운다).

지키는 것: ① 받는 곳은 Hugging Face 의 커밋 고정 주소 하나뿐(허용 호스트 `huggingface.co`·`hf.co` 와 그 하위, 닮은 이름·http·밖으로 가는 리디렉션은 거절)
② 받은 파일은 크기와 SHA-256 이 잠금 값과 같을 때만 남는다(다르면 지우고 실패, 읽는 양도 잠금 크기를 넘지 못한다)
③ 일시적인 오류만 다시 한다(해시 불일치·허용 밖 호스트는 바로 실패) ④ 이미 맞는 파일은 다시 받지 않는다 ⑤ 비밀·토큰·계정 코드가 없고 앱(`src/`)에는 내려받는 코드가 없다.
"""
import contextlib
import hashlib
import io
import itertools
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_build_support as support  # noqa: E402

fetch = support.load("fetch_models")
rules = support.load("build_rules")
ROOT = support.ROOT

DET, REC = b"det-model-bytes-" * 20, b"rec-model-bytes-" * 33
DICT = b"dictionary\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def entry_for(key, data, repo="Owner/some_repo", commit="a" * 40):
    return {"key": key, "role": key.split("/")[1], "source": {"kind": "huggingface", "repo": repo, "commit": commit, "path": "inference.onnx"}, "bytes": len(data), "sha256": sha(data)}


def small_lock():
    return {"schema": 1, "files": [entry_for("models/det/inference.onnx", DET), entry_for("models/rec/inference.onnx", REC, commit="b" * 40),
                                   {"key": "data/ppocrv5_korean_dict.txt", "role": "dict", "source": {"kind": "repo", "path": "ocr_addon/data/ppocrv5_korean_dict.txt"}, "bytes": len(DICT), "sha256": sha(DICT)}]}


class FakeResponse:
    def __init__(self, chunks, url="https://cdn.hf.co/blob", status=200):
        self.chunks, self.url, self.status, self.reads = iter(chunks), url, status, 0

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
        self.requests.append({"url": request.full_url, "headers": {k.lower(): v for k, v in request.header_items()}, "timeout": timeout})
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def run_main(argv, opener=None):
    out, err, sleeps = io.StringIO(), io.StringIO(), []
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fetch.main(argv, opener=opener, sleep=sleeps.append)
    return code, out.getvalue(), err.getvalue(), sleeps


class HostRuleTest(unittest.TestCase):
    def test_only_the_two_hosts_and_their_subdomains_are_allowed(self):
        self.assertEqual(fetch.ALLOWED_HOST_SUFFIXES, ("huggingface.co", "hf.co"))
        for host in ("huggingface.co", "cdn-lfs.huggingface.co", "hf.co", "us.aws.cdn.hf.co", "CAS-BRIDGE.XETHUB.HF.CO", "huggingface.co."):
            with self.subTest(host=host):
                self.assertTrue(fetch.host_allowed(host))
        for host in ("evilhf.co", "hf.co.evil.test", "huggingface.co.evil.test", "nothuggingface.co", "huggingface.com", "xhf.co", "", None, "localhost", "127.0.0.1", "pypi.org", "github.com"):
            with self.subTest(host=host):
                self.assertFalse(fetch.host_allowed(host))

    def test_the_download_address_is_pinned_to_the_commit_of_the_real_lock(self):
        lock = json.loads(support.read("ocr_addon/models.lock.json"))
        urls = {item["key"]: fetch.download_url(item["source"]) for item in lock["files"] if item["source"]["kind"] == "huggingface"}
        self.assertEqual(urls, {"models/det/inference.onnx": "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/e6f4fa85f00e168c862bc462aebca69eef9b3d3d/inference.onnx",
                                "models/rec/inference.onnx": "https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx/resolve/5c6f574b8e2230adf4287b33e736d71b9fabd28e/inference.onnx"})
        self.assertEqual(len([item for item in lock["files"] if item["source"]["kind"] == "repo"]), 1, "사전은 내려받지 않고 저장소 안 파일이다")

    def test_a_redirect_leaving_the_allowed_hosts_or_dropping_to_http_is_refused(self):
        handler = fetch.GuardedRedirect()
        request = urllib.request.Request("https://huggingface.co/Owner/some_repo/resolve/" + "a" * 40 + "/inference.onnx")
        for target in ("https://evil.example.invalid/blob", "http" + "://huggingface.co/blob", "https://hf.co.evil.test/blob", "ftp://hf.co/blob", "https://localhost/blob", "https://127.0.0.1/blob"):
            with self.subTest(target=target):
                with self.assertRaises(fetch.FetchError):
                    handler.redirect_request(request, None, 302, "Found", {}, target)
        for target in ("https://us.aws.cdn.hf.co/repos/x/blob", "https://cas-bridge.xethub.hf.co/x", "https://cdn-lfs.huggingface.co/x"):
            with self.subTest(target=target):
                followed = handler.redirect_request(request, None, 302, "Found", {}, target)
                self.assertEqual(followed.full_url, target)


class FetchFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.target = str(Path(self.tmp.name) / "det" / "inference.onnx")
        self.entry = entry_for("models/det/inference.onnx", DET)

    def listing(self):
        return sorted(str(p.relative_to(self.tmp.name)).replace(chr(92), "/") for p in Path(self.tmp.name).rglob("*") if p.is_file())

    def test_a_good_download_lands_with_the_exact_bytes_and_leaves_no_part_file(self):
        opener = FakeOpener(FakeResponse([DET[:100], DET[100:]]))
        fetch.fetch_file(self.entry, self.target, opener)
        self.assertEqual(Path(self.target).read_bytes(), DET)
        self.assertEqual(self.listing(), ["det/inference.onnx"])
        request = opener.requests[0]
        self.assertEqual(request["url"], fetch.download_url(self.entry["source"]))
        self.assertEqual(request["headers"]["user-agent"], fetch.USER_AGENT)
        self.assertEqual(request["timeout"], fetch.TIMEOUT)
        self.assertEqual([name for name in request["headers"] if name in ("authorization", "cookie", "proxy-authorization")], [], "비밀·로그인 머리말이 없다")

    def test_the_connection_has_a_finite_and_short_time_limit(self):
        self.assertIsInstance(fetch.TIMEOUT, (int, float))
        self.assertNotIsInstance(fetch.TIMEOUT, bool)
        self.assertTrue(0 < fetch.TIMEOUT <= 300, "러너에서 연결이 멈추면 흐름의 제한 시간(45분)까지 매달리지 않게 한다(독립 검증 S 의 SP-3)")

    def test_a_download_of_the_right_size_with_other_bytes_is_deleted_and_not_retried(self):
        other = bytes(len(DET))
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(self.entry, self.target, FakeOpener(FakeResponse([other])))
        self.assertFalse(caught.exception.retry)
        self.assertIn("SHA-256", str(caught.exception))
        self.assertEqual(self.listing(), [])

    def test_a_short_download_is_deleted_and_may_be_retried(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(self.entry, self.target, FakeOpener(FakeResponse([DET[:-1]])))
        self.assertTrue(caught.exception.retry)
        self.assertEqual(self.listing(), [])

    def test_an_endless_response_stops_at_the_locked_size_and_is_deleted(self):
        endless = FakeResponse(itertools.islice(itertools.repeat(b"x" * 64), 20000))        # '끝없는' 응답을 흉내 내되 유한하게 — 상한이 빠진 변이가 시험을 멈추지 못하게 하지 않는다
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(self.entry, self.target, FakeOpener(endless))
        self.assertFalse(caught.exception.retry)
        self.assertLessEqual(endless.reads * 64, len(DET) + 64, "잠금 크기를 넘겨 읽지 않는다")
        self.assertEqual(self.listing(), [])

    def test_a_final_address_outside_the_allowed_hosts_is_refused_before_anything_is_written(self):
        for url in ("https://evil.example.invalid/blob", "https://hf.co.evil.test/blob", "https://127.0.0.1/blob"):
            with self.subTest(url=url):
                with self.assertRaises(fetch.FetchError):
                    fetch.fetch_file(self.entry, self.target, FakeOpener(FakeResponse([DET], url=url)))
                self.assertEqual(self.listing(), [])

    def test_a_status_other_than_200_is_refused(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.fetch_file(self.entry, self.target, FakeOpener(FakeResponse([DET], status=206)))
        self.assertTrue(caught.exception.retry)
        self.assertEqual(self.listing(), [])


class RetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.target = str(Path(self.tmp.name) / "det" / "inference.onnx")
        self.entry = entry_for("models/det/inference.onnx", DET)
        self.sleeps, self.said = [], []

    def go(self, *items):
        opener = FakeOpener(*items)
        fetch.fetch_with_retries(self.entry, self.target, opener, sleep=self.sleeps.append, say=self.said.append)
        return opener

    def test_transient_network_errors_and_server_errors_are_retried_with_the_waits(self):
        http_503 = urllib.error.HTTPError("https://huggingface.co/x", 503, "busy", {}, None)
        opener = self.go(urllib.error.URLError("temporary"), http_503, FakeResponse([DET]))
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(self.sleeps, list(fetch.WAITS))
        self.assertEqual(Path(self.target).read_bytes(), DET)
        self.assertEqual(len(self.said), 2)

    def test_a_connection_cut_in_the_middle_is_retried(self):
        class Cut(FakeResponse):
            def read(self, size=-1):
                raise ConnectionResetError("cut")
        opener = self.go(Cut([]), FakeResponse([DET]))
        self.assertEqual(len(opener.requests), 2)

    def test_not_found_and_hash_mismatch_and_foreign_hosts_fail_at_once(self):
        cases = {"404": urllib.error.HTTPError("https://huggingface.co/x", 404, "gone", {}, None), "hash": FakeResponse([bytes(len(DET))]), "host": FakeResponse([DET], url="https://evil.example.invalid/x")}
        for name, item in cases.items():
            with self.subTest(case=name):
                self.sleeps.clear()
                opener = FakeOpener(item)
                with self.assertRaises(fetch.FetchError) as caught:
                    fetch.fetch_with_retries(self.entry, self.target, opener, sleep=self.sleeps.append, say=self.said.append)
                self.assertEqual(len(opener.requests), 1, "다시 하지 않는다")
                self.assertEqual(self.sleeps, [])
                self.assertIn("models/det/inference.onnx", str(caught.exception))

    def test_it_gives_up_after_the_attempt_limit(self):
        self.assertEqual(fetch.ATTEMPTS, 3)
        opener = FakeOpener(*[urllib.error.URLError("down")] * 3)
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_with_retries(self.entry, self.target, opener, sleep=self.sleeps.append, say=self.said.append)
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(self.sleeps, list(fetch.WAITS))


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.dest = str(Path(self.tmp.name) / "models")
        self.lock = Path(self.tmp.name) / "lock.json"
        self.lock.write_text(json.dumps(small_lock()), encoding="utf-8")

    def argv(self, *extra):
        return ["--dest", self.dest, "--lock", str(self.lock), *extra]

    def test_it_downloads_both_models_into_det_and_rec_and_skips_the_dictionary(self):
        opener = FakeOpener(FakeResponse([DET]), FakeResponse([REC]))
        code, out, err, _sleeps = run_main(self.argv(), opener)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((Path(self.dest) / "det" / "inference.onnx").read_bytes(), DET)
        self.assertEqual((Path(self.dest) / "rec" / "inference.onnx").read_bytes(), REC)
        self.assertEqual(sorted(p.name for p in Path(self.dest).iterdir()), ["det", "rec"], "사전은 받지 않는다")
        self.assertEqual([item["url"] for item in opener.requests], [fetch.download_url(entry["source"]) for entry in small_lock()["files"][:2]])
        self.assertIn("받았고 SHA-256 이 같다", out)

    def test_a_second_run_does_not_touch_the_network_and_a_damaged_file_is_fetched_again(self):
        run_main(self.argv(), FakeOpener(FakeResponse([DET]), FakeResponse([REC])))
        quiet = FakeOpener()
        code, out, _err, _ = run_main(self.argv(), quiet)
        self.assertEqual((code, quiet.requests), (0, []))
        self.assertEqual(out.count("이미 있고"), 2)
        (Path(self.dest) / "rec" / "inference.onnx").write_bytes(bytes(len(REC)))       # 크기는 같고 내용만 다른 망가진 파일 — 크기만 보는 확인은 놓친다
        again = FakeOpener(FakeResponse([REC]))
        code, _out, _err, _ = run_main(self.argv(), again)
        self.assertEqual(code, 0)
        self.assertEqual(len(again.requests), 1)
        self.assertEqual((Path(self.dest) / "rec" / "inference.onnx").read_bytes(), REC)

    def test_check_only_never_downloads_and_fails_when_something_is_missing_or_wrong(self):
        opener = FakeOpener()
        code, _out, err, _ = run_main(self.argv("--check-only"), opener)
        self.assertEqual((code, opener.requests), (1, []))
        self.assertIn("models/det/inference.onnx", err)
        run_main(self.argv(), FakeOpener(FakeResponse([DET]), FakeResponse([REC])))
        self.assertEqual(run_main(self.argv("--check-only"), FakeOpener())[0], 0)

    def test_a_failed_download_returns_one_and_leaves_no_file_behind(self):
        code, _out, err, _ = run_main(self.argv(), FakeOpener(FakeResponse([bytes(len(DET))])))
        self.assertEqual(code, 1)
        self.assertIn("SHA-256", err)
        self.assertEqual([p for p in Path(self.dest).rglob("*") if p.is_file()], [])

    def test_a_broken_or_unsafe_lock_is_refused_with_code_two_before_any_request(self):
        for name, mutate in {"commit": lambda lock: lock["files"][0]["source"].update(commit="main"), "repo": lambda lock: lock["files"][0]["source"].update(repo="../x"),
                             "kind": lambda lock: lock["files"][0]["source"].update(kind="url"), "extra": lambda lock: lock["files"].pop()}.items():
            with self.subTest(case=name):
                lock = small_lock()
                mutate(lock)
                self.lock.write_text(json.dumps(lock), encoding="utf-8")
                opener = FakeOpener()
                code, _out, err, _ = run_main(self.argv(), opener)
                self.assertEqual((code, opener.requests), (2, []))
                self.assertIn("잠금 파일", err)
        self.lock.write_text("not json", encoding="utf-8")
        self.assertEqual(run_main(self.argv(), FakeOpener())[0], 2)
        self.assertEqual(run_main(["--dest", self.dest, "--lock", str(Path(self.tmp.name) / "none.json")], FakeOpener())[0], 2)


class SourceBoundaryTest(unittest.TestCase):
    def test_the_download_script_holds_no_credentials_and_uses_https_only(self):
        source = support.read("ocr_addon/fetch_models.py")
        for word in ("Authorization", "Bearer", "HF_TOKEN", "huggingface_hub", "secrets.", "getpass", "keyring", "cookie", "Cookie", "http" + "://"):
            self.assertNotIn(word, source, word)

    def test_the_app_source_has_no_download_code_or_model_host_names(self):
        found = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for word in ("huggingface", "hf.co", "fetch_models", "/resolve/", "models.lock"):
                if word in text:
                    found.append((path.relative_to(ROOT).as_posix(), word))
        self.assertEqual(found, [], "앱(src/)에는 내려받는 코드가 없다 — 모델은 빌드가 받고 앱은 박은 해시로 확인만 한다")


if __name__ == "__main__":
    unittest.main()
