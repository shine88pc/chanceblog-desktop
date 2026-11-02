"""Pages 배포 확인 시험 — 올린 글이 공개 주소에서 열리는지 확인하는 부분(네트워크·대기 없음: 가짜 요청기·가짜 시계).

지키는 것:
  1) 사이트 주소(`url`+`baseurl`)를 연결한 저장소의 `_config.yml` 에서 읽고, https 가 아니면 거절한다.
  2) 글의 공개 주소는 Jekyll permalink 로 계산한다(실제 Chance 글 두 편으로 확인) — 네트워크 없이.
  3) 열릴 때까지 기다리되 같은 모양으로 반복하지 않고(공개 CDN 이 404 를 보관한다), 마감이 지나면 PAGES_DEPLOY_NOT_VISIBLE.
  4) 공개되지 않는 글·설정이 없는 저장소는 기다리지 않고 거절. 연결한 저장소는 건드리지 않고, 임시 폴더는 남기지 않으며, 화면에 아무것도 찍지 않는다.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.core import load_vendored_script  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import deploy  # noqa: E402

VERIFY = load_vendored_script("verify_pages_deploy")
KO_TEXT = (ROOT / "tests" / "fixtures" / "chance_post_ko.md").read_text(encoding="utf-8")
EN_TEXT = (ROOT / "tests" / "fixtures" / "chance_post_en.md").read_text(encoding="utf-8")
KO_PATH = "_posts/경제·일/2026-10-29-KR-101652.md"
EN_PATH = "_posts/Society & Policy/2026-10-28-EN-184844.md"
KO_URL = "https://example.invalid/chanceblog/posts/2026/10/29/KR-101652/"
EN_URL = "https://example.invalid/chanceblog/posts/2026/10/28/EN-184844/"
CONFIG = 'title: 시험 블로그\nbaseurl: "/chanceblog"\nurl: "https://example.invalid"\ntimezone: Asia/Seoul\npermalink: /posts/:year/:month/:day/:title/\n'
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
KEY = "AI" + "za" + "A" * 35                                   # 구글 API 키 모양의 가짜 값(가림 시험용)


def code_of(callable_, *args, **kwargs):
    with unittest.TestCase().assertRaises(AppError) as caught:
        callable_(*args, **kwargs)
    return caught.exception


class Site:
    """연결한 저장소 흉내(`_config.yml` 만 있으면 된다)."""

    def __init__(self, config=CONFIG):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        if config is not None:
            (self.root / "_config.yml").write_text(config, encoding="utf-8", newline="\n")

    def cleanup(self):
        self.tmp.cleanup()


class FakeWorld:
    """가짜 요청기·가짜 시계. 글 주소로 가는 요청이 open_after 번째부터 200 을 돌려준다(그 전은 404). posts.json 은 없다(404)."""

    def __init__(self, open_after=1):
        self.open_after = open_after
        self.requests = []
        self.sleeps = []
        self.now = 0.0

    def fetcher(self, url, limit=0, headers=None):
        self.requests.append((url, dict(headers or {})))
        if url.split("?")[0].endswith("posts.json"):
            return VERIFY.Resp(404, b"", {}, "")
        post_requests = sum(1 for item in self.requests if "KR-101652" in item[0])
        return VERIFY.Resp(200 if post_requests >= self.open_after else 404, b"", {}, "")

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self):
        return self.now

    def post_requests(self):
        return [url for url, _headers in self.requests if "KR-101652" in url]

    def post_shapes(self):
        """요청 모양 = (경로, Accept-Encoding 머리글). 확인 코드는 CDN 이 404 를 보관하므로 시도마다 이 모양을 바꾼다."""
        return [(url.split("?")[0], headers.get("Accept-Encoding")) for url, headers in self.requests if "KR-101652" in url]


class SiteBaseTest(unittest.TestCase):
    def base(self, config):
        site = Site(config)
        self.addCleanup(site.cleanup)
        return deploy.site_base(site.root)

    def test_url_and_baseurl_are_joined_with_exactly_one_slash_between(self):
        self.assertEqual(self.base(CONFIG), "https://example.invalid/chanceblog/")
        for config in ('url: https://example.invalid\nbaseurl: /chanceblog\n', "url: 'https://example.invalid/'\nbaseurl: '/chanceblog/'\n",
                       'url: "https://example.invalid"   # 주소\nbaseurl: "/chanceblog"  # 하위 경로\n', '\ufeffurl: https://example.invalid\nbaseurl: chanceblog\n'):
            with self.subTest(config=config[:40]):
                self.assertEqual(self.base(config), "https://example.invalid/chanceblog/")
        self.assertEqual(self.base('url: "https://example.invalid"\nbaseurl: ""\n'), "https://example.invalid/")
        self.assertEqual(self.base('url: "https://example.invalid"\n'), "https://example.invalid/")

    def test_indented_or_repeated_keys_are_not_mistaken_for_the_top_level_ones(self):
        config = 'collections:\n  url: "https://other.invalid"\nurl: "https://example.invalid"\nbaseurl: "/a"\nurl: "https://second.invalid"\n'
        self.assertEqual(self.base(config), "https://example.invalid/a/")

    def test_a_missing_file_or_a_site_address_that_is_not_https_is_refused(self):
        site = Site(None)
        self.addCleanup(site.cleanup)
        self.assertEqual(code_of(deploy.site_base, site.root).code, "PAGES_LOCAL_REPO_INVALID")
        for config in ("title: x\n", 'url: ""\n', 'url: "http://example.invalid"\n', 'url: "ftp://example.invalid"\n', 'url: "https://user:pw@example.invalid"\n',
                       'url: "https://example.invalid?x=1"\n', 'baseurl: "/chanceblog"\n'):
            with self.subTest(config=config):
                self.assertEqual(code_of(self.base, config).code, "CONTENT_INVALID")

    def test_the_refusal_text_hides_secrets_and_stays_short(self):
        error = code_of(self.base, f'url: "http://example.invalid/{KEY}"\n')
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertNotIn(KEY, error.detail)
        self.assertIn("[가림:", error.detail)
        long = code_of(self.base, 'url: "http://example.invalid/' + "a" * 400 + '"\n')
        self.assertLessEqual(len(long.detail), 160)


class TempSiteTest(unittest.TestCase):
    def test_the_temporary_site_is_a_copy_of_the_config_and_only_this_post_with_unix_newlines(self):
        site = Site()
        self.addCleanup(site.cleanup)
        with tempfile.TemporaryDirectory() as tmp:
            deploy._write_site(tmp, site.root, KO_PATH, KO_TEXT)
            self.assertEqual((Path(tmp) / "_config.yml").read_bytes(), (site.root / "_config.yml").read_bytes())
            written = (Path(tmp) / KO_PATH).read_bytes()
            self.assertEqual(written, KO_TEXT.encode("utf-8"))
            self.assertNotIn(b"\r\n", written, "줄바꿈이 바뀌지 않는다")
            files = sorted(path.relative_to(tmp).as_posix() for path in Path(tmp).rglob("*") if path.is_file())
            self.assertEqual(files, sorted(["_config.yml", KO_PATH]))

    def test_a_config_that_cannot_be_read_is_an_error_not_an_empty_site(self):
        nothing = Site(None)
        self.addCleanup(nothing.cleanup)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(code_of(deploy._write_site, tmp, nothing.root, KO_PATH, KO_TEXT).code, "PAGES_LOCAL_REPO_INVALID")


class ExpectedUrlTest(unittest.TestCase):
    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.cleanup)

    def test_the_address_follows_the_permalink_with_the_cased_filename_slug(self):
        self.assertEqual(deploy.expected_url(self.site.root, KO_PATH, KO_TEXT, now=NOW), KO_URL)
        self.assertEqual(deploy.expected_url(self.site.root, EN_PATH, EN_TEXT, now=NOW), EN_URL)

    def test_the_category_folder_does_not_change_the_address(self):
        other = "_posts/다른 분야/2026-10-29-KR-101652.md"
        self.assertEqual(deploy.expected_url(self.site.root, other, KO_TEXT, now=NOW), KO_URL)

    def test_a_post_the_site_would_not_publish_is_refused_without_waiting(self):
        hidden = KO_TEXT.replace("layout: post", "layout: post\npublished: false", 1)
        self.assertIn("published: false", hidden)
        self.assertEqual(code_of(deploy.expected_url, self.site.root, KO_PATH, hidden, now=NOW).code, "CONTENT_INVALID")
        early = datetime(2026, 10, 1, tzinfo=timezone.utc)                        # 파일 날짜가 '지금'보다 뒤면 Jekyll 은 미래 글로 보고 공개하지 않는다
        self.assertEqual(code_of(deploy.expected_url, self.site.root, KO_PATH, KO_TEXT, now=early).code, "CONTENT_INVALID")

    def test_a_bad_post_or_an_unsupported_permalink_is_refused(self):
        self.assertEqual(code_of(deploy.expected_url, self.site.root, "_posts/../x.md", KO_TEXT, now=NOW).code, "CONTENT_INVALID")
        odd = Site(CONFIG.replace("/posts/:year/:month/:day/:title/", "/:categories/:title:output_ext"))
        self.addCleanup(odd.cleanup)
        self.assertEqual(code_of(deploy.expected_url, odd.root, KO_PATH, KO_TEXT, now=NOW).code, "CONTENT_INVALID")
        nothing = Site(None)
        self.addCleanup(nothing.cleanup)
        self.assertEqual(code_of(deploy.expected_url, nothing.root, KO_PATH, KO_TEXT, now=NOW).code, "PAGES_LOCAL_REPO_INVALID")

    def test_the_refusal_says_why_the_site_would_not_publish_the_post(self):
        hidden = KO_TEXT.replace("layout: post", "layout: post\npublished: false", 1)
        self.assertIn("published: false", code_of(deploy.expected_url, self.site.root, KO_PATH, hidden, now=NOW).detail)
        early = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.assertIn("미래 날짜", code_of(deploy.expected_url, self.site.root, KO_PATH, KO_TEXT, now=early).detail)

    def test_an_address_that_cannot_be_computed_says_why_with_secrets_hidden_and_a_short_text(self):
        secret = Site(CONFIG.replace("/posts/:year/:month/:day/:title/", KEY))
        self.addCleanup(secret.cleanup)
        error = code_of(deploy.expected_url, secret.root, KO_PATH, KO_TEXT, now=NOW)
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertNotIn(KEY, error.detail)
        self.assertIn("[가림:", error.detail)
        long = Site(CONFIG.replace("/posts/:year/:month/:day/:title/", "/:" + "a" * 500 + "/"))
        self.addCleanup(long.cleanup)
        self.assertLessEqual(len(code_of(deploy.expected_url, long.root, KO_PATH, KO_TEXT, now=NOW).detail), 260)


class CheckDeployedTest(unittest.TestCase):
    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.cleanup)

    def check(self, world, **kwargs):
        options = dict(fetcher=world.fetcher, sleep=world.sleep, clock=world.clock, now=NOW)
        options.update(kwargs)
        return deploy.check_deployed(self.site.root, KO_PATH, KO_TEXT, **options)

    def test_a_post_that_opens_at_once_is_confirmed_with_its_address(self):
        world = FakeWorld(open_after=1)
        result = self.check(world)
        self.assertEqual(result.url, KO_URL)
        self.assertEqual(world.sleeps, [])
        self.assertTrue(world.post_requests()[0].startswith(KO_URL), "첫 시도는 정규 주소")
        self.assertIn("반영", result.summary)

    def test_a_post_that_opens_only_after_the_cdn_cached_a_404_is_found_by_changing_the_request_shape(self):
        world = FakeWorld(open_after=3)
        result = self.check(world)
        self.assertEqual(result.url, KO_URL)
        self.assertEqual(world.sleeps, [10, 20], "대기는 10초에서 시작해 2배씩")
        requests = world.post_requests()
        self.assertEqual(len(requests), 3)
        self.assertEqual(len(set(world.post_shapes())), 3, "같은 모양으로 반복하지 않는다(CDN 이 404 를 보관한다)")
        self.assertEqual(world.post_shapes()[0], (KO_URL, None), "첫 시도는 정규 주소·기본 머리글")
        self.assertTrue(any("404" in line for line in result.summary.splitlines()) or "404" in result.summary, "첫 시도의 404 를 요약에 남긴다")

    def test_a_post_that_never_opens_ends_after_the_deadline_with_the_not_visible_code(self):
        world = FakeWorld(open_after=10 ** 6)
        error = code_of(self.check, world, deadline=100)
        self.assertEqual(error.code, "PAGES_DEPLOY_NOT_VISIBLE")
        self.assertIn("404", error.detail)
        self.assertLessEqual(world.now, 100 + 160, "마감 뒤에는 새 시도를 시작하지 않는다")
        self.assertGreaterEqual(len(world.post_requests()), 3)
        self.assertEqual(world.sleeps[:3], [10, 20, 40])

    def test_deadline_zero_checks_exactly_once(self):
        world = FakeWorld(open_after=10 ** 6)
        self.assertEqual(code_of(self.check, world, deadline=0).code, "PAGES_DEPLOY_NOT_VISIBLE")
        self.assertEqual((len(world.post_requests()), world.sleeps), (1, []))

    def test_a_post_the_site_would_not_publish_or_a_bad_setup_is_refused_before_any_request(self):
        world = FakeWorld()
        hidden = KO_TEXT.replace("layout: post", "layout: post\npublished: false", 1)
        with self.assertRaises(AppError):
            deploy.check_deployed(self.site.root, KO_PATH, hidden, fetcher=world.fetcher, sleep=world.sleep, clock=world.clock, now=NOW)
        nothing = Site(None)
        self.addCleanup(nothing.cleanup)
        with self.assertRaises(AppError):
            deploy.check_deployed(nothing.root, KO_PATH, KO_TEXT, fetcher=world.fetcher, sleep=world.sleep, clock=world.clock, now=NOW)
        self.assertEqual(world.requests, [])

    def test_the_connected_repository_is_not_touched_no_temp_folder_is_left_and_nothing_is_printed(self):
        before = sorted(path.relative_to(self.site.root).as_posix() for path in self.site.root.rglob("*"))
        created = []
        real = tempfile.TemporaryDirectory

        class Recording(real):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self.name)

        out = io.StringIO()
        with mock.patch.object(tempfile, "TemporaryDirectory", Recording), contextlib.redirect_stdout(out):
            self.check(FakeWorld(open_after=2))
        self.assertEqual(sorted(path.relative_to(self.site.root).as_posix() for path in self.site.root.rglob("*")), before)
        self.assertTrue(created)
        self.assertFalse(any(Path(name).exists() for name in created), "임시 폴더가 남았다")
        self.assertEqual(out.getvalue(), "", "확인 코드의 진행 출력이 화면에 섞이지 않는다")

    def test_the_english_post_is_checked_by_its_own_address(self):
        seen = []

        def fetcher(url, limit=0, headers=None):
            seen.append(url)
            return VERIFY.Resp(200 if "EN-184844" in url else 404, b"", {}, "")

        result = deploy.check_deployed(self.site.root, EN_PATH, EN_TEXT, fetcher=fetcher, sleep=lambda s: None, clock=lambda: 0.0, now=NOW)
        self.assertEqual(result.url, EN_URL)
        self.assertTrue(any(url.startswith(EN_URL) for url in seen))

    def test_only_this_post_is_checked_not_the_newest_post_of_the_repository(self):
        """연결한 저장소에 더 새 글이 있어도(봇이 방금 올림) 확인 대상은 내가 올린 글이다."""
        (self.site.root / "_posts").mkdir()
        (self.site.root / "_posts" / "2026-10-30-KR-235959.md").write_text("---\nlayout: post\n---\n더 새 글\n", encoding="utf-8")
        world = FakeWorld(open_after=1)
        self.check(world)
        self.assertTrue(all("235959" not in url for url, _headers in world.requests))

    def test_the_site_timezone_decides_whether_a_post_dated_by_its_file_name_is_already_public(self):
        world = FakeWorld()
        evening = datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc)          # 한국 시각으로는 10-30 05:00 — 파일 날짜(10-30 자정)가 이미 지났다
        result = deploy.check_deployed(self.site.root, "_posts/경제·일/2026-10-30-KR-101652.md", KO_TEXT, fetcher=world.fetcher, sleep=world.sleep, clock=world.clock, now=evening)
        self.assertEqual(result.url, "https://example.invalid/chanceblog/posts/2026/10/30/KR-101652/")

    def test_the_given_time_is_used_for_the_whole_check_not_the_real_clock(self):
        world = FakeWorld()
        far = "_posts/경제·일/2099-01-01-KR-101652.md"                          # 진짜 시계로는 아직 먼 미래라 공개되지 않는 글
        result = deploy.check_deployed(self.site.root, far, KO_TEXT, fetcher=world.fetcher, sleep=world.sleep, clock=world.clock, now=datetime(2100, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(result.url.endswith("/posts/2099/01/01/KR-101652/"), result.url)

    def test_the_defaults_wait_up_to_twelve_minutes_from_ten_seconds_and_tag_requests_with_the_app_token(self):
        world = FakeWorld(open_after=5)
        deploy.check_deployed(self.site.root, KO_PATH, KO_TEXT, fetcher=world.fetcher, sleep=world.sleep, clock=world.clock, now=NOW)
        self.assertEqual(world.sleeps, [10, 20, 40, 80], "기본 대기는 10초에서 시작해 두 배씩이고, 150초가 지나도 포기하지 않는다")
        self.assertIn("cb=app-1", world.post_requests()[0])
        self.assertIn("cb=app-5", world.post_requests()[-1])
        mine = FakeWorld()
        deploy.check_deployed(self.site.root, KO_PATH, KO_TEXT, fetcher=mine.fetcher, sleep=mine.sleep, clock=mine.clock, now=NOW, token="mine")
        self.assertIn("cb=mine-1", mine.post_requests()[0])

    def test_a_setup_problem_found_by_the_verifier_is_a_short_masked_error(self):
        with mock.patch.object(VERIFY, "verify", side_effect=VERIFY.ConfigError(KEY + " " + "x" * 500)):
            error = code_of(self.check, FakeWorld())
        self.assertEqual((error.code, error.slots["항목"]), ("CONTENT_INVALID", "배포 확인 설정"))
        self.assertNotIn(KEY, error.detail)
        self.assertLessEqual(len(error.detail), 300)

    def test_a_check_that_found_nothing_to_check_is_refused_not_reported_as_confirmed(self):
        with mock.patch.object(VERIFY, "verify", return_value=VERIFY.Result(True, True, "건너뜀", [])):
            error = code_of(self.check, FakeWorld())
        self.assertEqual((error.code, error.slots["항목"]), ("CONTENT_INVALID", "공개 설정"))

    def test_the_report_of_a_post_that_never_opened_is_one_short_masked_line_ending_with_the_latest_news(self):
        summary = "앞부분 " + "채움 " * 400 + f"\n끝에 가까운 곳 {KEY}\n\n  마지막   소식"          # 비밀 모양은 끝 600자 안에 있어야 가림 여부가 보인다
        with mock.patch.object(VERIFY, "verify", return_value=VERIFY.Result(False, False, summary, [])):
            error = code_of(self.check, FakeWorld())
        self.assertEqual(error.code, "PAGES_DEPLOY_NOT_VISIBLE")
        self.assertNotIn(KEY, error.detail)
        self.assertNotIn("\n", error.detail)
        self.assertNotIn("  ", error.detail)
        self.assertLessEqual(len(error.detail), 600)
        self.assertTrue(error.detail.endswith("마지막 소식"), error.detail[-40:])


class VendoredScriptLoaderTest(unittest.TestCase):
    def test_the_script_is_loaded_once_by_path_without_creating_a_scripts_package(self):
        first = load_vendored_script("verify_pages_deploy")
        self.assertIs(first, load_vendored_script("verify_pages_deploy"))
        self.assertNotIn("scripts", sys.modules)
        self.assertIn((ROOT / "vendor").resolve(), Path(first.__file__).resolve().parents)

    def test_a_fresh_interpreter_loads_the_script_with_the_core_set_up_and_makes_no_scripts_package(self):
        code = ("import json, sys\n"
                "sys.path.insert(0, 'src')\n"
                "from chanceblog_desktop.core import load_vendored_script\n"
                "module = load_vendored_script('verify_pages_deploy')\n"
                "print(json.dumps({'loaded': hasattr(module, 'verify'), 'key': 'chanceblog_vendor_verify_pages_deploy' in sys.modules, "
                "'cache_moved': sys.pycache_prefix is not None, "
                "'scripts': [name for name in sys.modules if name == 'scripts' or name.startswith('scripts.')]}))\n")
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPYCACHEPREFIX"}
        env.update(PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(done.returncode, 0, done.stderr[-400:])
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1]), {"loaded": True, "key": True, "cache_moved": True, "scripts": []},
                         "불러오기가 핵심 코드 준비(경로·컴파일 캐시 위치)를 함께 한다")

    def test_odd_names_are_refused(self):
        for name in ("", "../x", "a/b", "A", "x.py", None, 5, "verify pages"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    load_vendored_script(name)

    def test_a_missing_script_is_an_error_and_leaves_no_half_loaded_module(self):
        with self.assertRaises(FileNotFoundError):
            load_vendored_script("no_such_script")
        self.assertNotIn("chanceblog_vendor_no_such_script", sys.modules)


if __name__ == "__main__":
    unittest.main()
