"""`네이버 글쓰기 열기` 주소의 폴백(`service/draft_engine.py` 의 `naver_blog_url`·`channel_address`·`blog_context`) 시험 — 진짜 임시 폴더의 엔진 보관함·설정 파일·채널 프로필 파일로 확인한다(PySide6 없이 돈다).

지키는 것:
  1) **옛 네이버 프로필에 주소가 있으면 지금까지와 같다**(바이트까지 같은 주소·같은 출처 `profile`). 옛 프로필에 주소가 없을 때만 채널 프로필(블로그 관리 화면)의 `블로그 ID 또는 주소` 에서 같은 모양
     (방식 https·호스트 blog.naver.com·경로 아이디 한 토막 → 화면이 글쓰기 주소를 만든다)으로 얻는다 — 조사 실험 C(채널 프로필만 있으면 단추가 꺼지던 것)의 재현이 이제 켜진다.
  2) 둘 다 없으면 주소는 비고(`none`), 적어 둔 주소가 네이버 블로그 주소가 아니면 비고 `unusable` 로 알린다(안내 문구가 사실대로 갈리게).
  3) 주소 검사는 화면의 규칙(`ui/core/draft_rules.naver_write_url`)과 같은 답을 낸다 — 허용 호스트는 `blog.naver.com` 뿐이고 다른 호스트·방식·로그인 정보·포트·인자·조각·여러 토막 경로·공백은 거절.
  4) 읽기 전용이다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
from test_service_draft_engine import engine_candidate  # noqa: E402
from test_ui_candidates_service import World  # noqa: E402

from chanceblog_desktop.service import blog_profiles, draft_engine  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402

URL_CASES = (
    "https://blog.naver.com/myid", "https://blog.naver.com/myid/", "https://blog.naver.com//myid", "HTTPS://BLOG.NAVER.COM/MyId", "https://blog.naver.com/my_id-1", "https://blog.naver.com/" + "a" * 40,
    "https://blog.naver.com/" + "a" * 41, "https://blog.naver.com/", "https://blog.naver.com", "http://blog.naver.com/myid", "ftp://blog.naver.com/myid", "//blog.naver.com/myid",
    "https://m.blog.naver.com/myid", "https://blog.naver.com.evil.example/myid", "https://evilblog.naver.com/myid", "https://naver.com/myid", "https://example.invalid/myid", "https://localhost/myid",
    "https://127.0.0.1/myid", "https://user:pass@blog.naver.com/myid", "https://user@blog.naver.com/myid", "https://blog.naver.com@example.invalid/myid", "https://blog.naver.com:443/myid",
    "https://blog.naver.com:8080/myid", "https://blog.naver.com/myid?Redirect=Write", "https://blog.naver.com/myid?x=1", "https://blog.naver.com/myid#top", "https://blog.naver.com/a/b",
    "https://blog.naver.com/PostList.naver?blogId=x", "https://blog.naver.com/my.id", "https://blog.naver.com/my%20id", "https://blog.naver.com/my id", "https://blog.naver.com/한글", "https://blog.naver.com/\n",
    "https://blog.naver.com/myid\n", " https://blog.naver.com/myid", "https://[blog.naver.com/myid", "https://blog.naver.com:abc/myid", "https://blog.naver.com/" + "a" * 300, "javascript://blog.naver.com/%0aalert(1)",
)
SCREEN_ONLY = {"https://blog.naver.com//myid"}            # 화면 규칙(`strip("/")`)은 받고 서비스 규칙은 받지 않는 모양 — `//` 로 이어진 경로(서비스 규칙이 더 엄격하다)
ID_CASES = ("myid", "my_id-1", "A1", "a" * 40, "a" * 41, "my.id", "my id", "한글", "", " ", "my/id", "my?x", "my#x", "my@x", "httpfan", "http:blog", "://myid", "x" * 300)


class AddressRuleTest(unittest.TestCase):
    def test_every_address_the_service_rule_makes_the_screen_rule_accepts_the_same_and_only_one_shape_is_stricter(self):
        for text in URL_CASES:
            with self.subTest(text=text[:50]):
                mine, screen = draft_engine.naver_blog_url(text), rules.naver_write_url(text)
                if mine:
                    self.assertEqual(rules.naver_write_url(mine), screen)
                    self.assertTrue(mine.startswith("https://blog.naver.com/") and mine.count("/") == 3)
                else:
                    self.assertEqual(bool(screen), text in SCREEN_ONLY, "화면 규칙만 받는 모양은 알려진 것뿐이다")

    def test_a_bare_id_means_the_blog_address_of_that_id_for_both_rules(self):
        for text in ID_CASES:
            with self.subTest(text=text[:50]):
                mine = draft_engine.naver_blog_url(text)
                screen = rules.naver_write_url("https://blog.naver.com/" + text)
                if mine:
                    self.assertEqual(rules.naver_write_url(mine), screen)
                    self.assertEqual(mine, "https://blog.naver.com/" + text)
                else:
                    self.assertFalse(bool(screen) and text.strip() == text and "://" not in text and "/" not in text)

    def test_only_the_naver_blog_host_is_ever_accepted_and_only_with_https(self):
        for text in URL_CASES:
            url = draft_engine.naver_blog_url(text)
            if url:
                self.assertTrue(url.startswith("https://blog.naver.com/"), text)
        for host in ("m.blog.naver.com", "blog.naver.com.evil.example", "evilblog.naver.com", "naver.com", "example.invalid", "localhost", "127.0.0.1", "blog.naver.co", "blog-naver.com"):
            self.assertEqual(draft_engine.naver_blog_url(f"https://{host}/myid"), "", host)
        for scheme in ("http", "ftp", "file", "javascript", "data", "mailto"):
            self.assertEqual(draft_engine.naver_blog_url(f"{scheme}://blog.naver.com/myid"), "", scheme)

    def test_a_good_address_is_normalized_to_the_plain_blog_address_and_the_id_keeps_its_case(self):
        self.assertEqual(draft_engine.naver_blog_url("HTTPS://BLOG.NAVER.COM/MyId/"), "https://blog.naver.com/MyId")
        self.assertEqual(draft_engine.naver_blog_url("MyId"), "https://blog.naver.com/MyId")

    def test_things_that_are_not_text_or_are_too_long_are_refused(self):
        for value in (None, 5, b"myid", ["myid"], "x" * 201):
            self.assertEqual(draft_engine.naver_blog_url(value), "")

    def test_the_channel_address_says_which_of_the_three_states_it_is(self):
        self.assertEqual(draft_engine.channel_address("myid"), ("https://blog.naver.com/myid", "channel"))
        self.assertEqual(draft_engine.channel_address("https://example.invalid/x"), ("", "unusable"))
        self.assertEqual(draft_engine.channel_address("my.id"), ("", "unusable"))
        self.assertEqual(draft_engine.channel_address(""), ("", "none"))
        self.assertEqual(draft_engine.channel_address("   "), ("", "none"))
        self.assertEqual(draft_engine.channel_address(None), ("", "none"))
        self.assertEqual(set(draft_engine.ADDRESS_STATES), {"profile", "channel", "unusable", "none"})


class EngineBodyAddressTest(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.ctx = self.world.ctx
        self.engine = engine_candidate(1, "naver_a")
        self.world.add(self.engine)

    def register(self, ref, key="naver_a"):
        snapshot = blog_profiles.read_snapshot(self.ctx)
        blog_profiles.save_slot(self.ctx, key, {"display_name": "예시 블로그", "blog_ref": ref}, expected_version=snapshot.version)

    def made(self, blog=None):
        return draft_engine.make_body_for_engine(self.ctx, self.engine.candidate_id, blog=blog)

    def test_with_only_a_channel_profile_the_address_is_made_from_the_blog_id_and_the_button_can_turn_on(self):
        self.register("myblogid")
        made = self.made()
        self.assertEqual((made.blog_url, made.address, made.profile_found, made.channel_found), ("https://blog.naver.com/myblogid", "channel", False, True))
        self.assertEqual(rules.naver_write_url(made.blog_url), "https://blog.naver.com/myblogid?Redirect=Write")

    def test_with_only_a_channel_profile_a_full_blog_address_works_too(self):
        self.register("https://blog.naver.com/myblogid/")
        made = self.made()
        self.assertEqual((made.blog_url, made.address), ("https://blog.naver.com/myblogid", "channel"))

    def test_the_old_profile_address_wins_and_is_exactly_what_it_was_before(self):
        ss.naver_profiles(self.ctx)
        self.register("channelid")
        made = self.made()
        self.assertEqual((made.blog_url, made.address, made.profile_found), ("https://blog.naver.com/exampleaaa", "profile", True))
        self.assertEqual(rules.naver_write_url(made.blog_url), "https://blog.naver.com/exampleaaa?Redirect=Write")

    def test_the_old_profile_alone_behaves_as_before_even_without_a_channel_profile(self):
        ss.naver_profiles(self.ctx)
        made = self.made()
        self.assertEqual((made.blog_url, made.address, made.channel_found), ("https://blog.naver.com/exampleaaa", "profile", False))

    def test_with_neither_the_address_is_empty_and_says_none(self):
        made = self.made()
        self.assertEqual((made.blog_url, made.address, made.profile_found, made.channel_found), ("", "none", False, False))
        self.assertEqual(rules.naver_write_url(made.blog_url), "")

    def test_a_channel_address_that_is_not_a_naver_blog_gives_no_address_and_says_unusable(self):
        for ref in ("https://example.invalid/myid", "my.id", "https://blog.naver.com/a/b"):
            with self.subTest(ref=ref):
                self.register(ref)
                made = self.made()
                self.assertEqual((made.blog_url, made.address), ("", "unusable"))

    def test_the_other_blog_slot_uses_its_own_channel_address(self):
        other = engine_candidate(2, "naver_b")
        self.world.add(other)
        self.register("aaaid", "naver_a")
        self.register("bbbid", "naver_b")
        made_b = draft_engine.make_body_for_engine(self.ctx, other.candidate_id)
        self.assertEqual((made_b.blog, made_b.blog_url), ("naver_b", "https://blog.naver.com/bbbid"))
        made_a = draft_engine.make_body_for_engine(self.ctx, self.engine.candidate_id)
        self.assertEqual(made_a.blog_url, "https://blog.naver.com/aaaid")

    def test_making_the_draft_still_changes_no_file(self):
        self.register("myblogid")
        before = ss.tree_snapshot(self.world.tmp)
        self.made()
        self.assertEqual(ss.tree_snapshot(self.world.tmp), before)


class BlogContextTest(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.ctx = self.world.ctx

    def test_the_context_has_the_same_address_rule_as_making_a_draft(self):
        snapshot = blog_profiles.read_snapshot(self.ctx)
        blog_profiles.save_slot(self.ctx, "naver_a", {"display_name": "예시 블로그", "blog_ref": "myblogid"}, expected_version=snapshot.version)
        context = draft_engine.blog_context(self.ctx, "naver_a")
        self.assertEqual((context.blog, context.blog_url, context.address, context.channel_found, context.profile_found), ("naver_a", "https://blog.naver.com/myblogid", "channel", True, False))
        self.assertEqual(dict(context.blog_names)["naver_a"], "예시 블로그")
        ss.naver_profiles(self.ctx)
        self.assertEqual(draft_engine.blog_context(self.ctx, "naver_a").address, "profile")

    def test_an_unknown_blog_slot_has_no_old_profile_and_the_context_reads_nothing_it_should_not(self):
        before = ss.tree_snapshot(self.world.tmp)
        context = draft_engine.blog_context(self.ctx, "naver_b")
        self.assertEqual((context.blog_url, context.address), ("", "none"))
        self.assertEqual(ss.tree_snapshot(self.world.tmp), before)


if __name__ == "__main__":
    unittest.main()
