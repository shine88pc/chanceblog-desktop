"""네이버 블로그 프로필 시험 — A·B 두 블로그의 설정이 엄격하게 검사되고, 카테고리 매핑·고지문이 규칙대로 나오며, 저장 모양(JSON)이 되돌려도 같다.

지키는 것:
  1) 블로그 구분은 naver_a·naver_b 뿐, 주소는 blog.naver.com 의 https 주소(로그인 정보·검색어·다른 호스트 거절), 숫자 설정은 범위 안의 정수, 낱말 목록은 중복·빈 낱말·너무 긴 낱말 없이.
  2) 글은 한 줄로 정리돼 저장되고(제어·서식 문자 제거) 모양이 틀리면 CONTENT_INVALID 로 거절한다 — 고치지 않고 조용히 받지 않는다.
  3) 카테고리 매핑은 대소문자를 가리지 않고, 매핑이 없으면 빈 글이다. 고지문은 비우면 기본 문구다.
  4) to_dict/from_dict 는 되돌려도 같고, 모르는 칸·빠진 필수 칸은 거절한다. 프로필은 바꿀 수 없다(frozen).
네트워크·파일 없이 돈다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content.profiles import DEFAULT_DISCLOSURE, KEYS, NaverProfile, clean_line  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

GOOD = {"key": "naver_a", "display_name": "블로그 A", "blog_url": "https://blog.naver.com/example_a"}


def make(**changes):
    return NaverProfile(**{**GOOD, **changes})


class CleanLineTest(unittest.TestCase):
    def test_control_and_format_characters_go_and_spaces_fold(self):
        self.assertEqual(clean_line("  앞\u200b뒤 \t 둘째\n줄  "), "앞뒤 둘째 줄")
        self.assertEqual(clean_line("a\u202eb\u2028c\u2029d\x00e"), "ab c d" + "e")
        self.assertEqual(clean_line(123), "123")
        self.assertEqual(clean_line("한   글"), "한 글")


class ValidationTest(unittest.TestCase):
    def refuses(self, **changes):
        with self.assertRaises(AppError) as caught:
            make(**changes)
        self.assertEqual(caught.exception.code, "CONTENT_INVALID", changes)
        return caught.exception

    def test_a_minimal_profile_gets_the_documented_defaults(self):
        profile = make()
        self.assertEqual((profile.key, profile.display_name, profile.blog_url), ("naver_a", "블로그 A", "https://blog.naver.com/example_a"))
        self.assertEqual((profile.min_chars, profile.max_chars, profile.max_title_chars, profile.paragraph_max_chars, profile.max_tags), (800, 6000, 60, 180, 10))
        self.assertEqual((profile.categories, profile.default_tags, profile.forbidden_phrases), ((), (), ()))
        self.assertEqual(KEYS, ("naver_a", "naver_b"))
        self.assertEqual(make(key="naver_b").key, "naver_b")

    def test_the_blog_key_is_one_of_the_two(self):
        for key in ("naver_c", "", "NAVER_A", "naver_a ", None, 1):
            with self.subTest(key=key):
                self.refuses(key=key)

    def test_the_display_name(self):
        self.assertEqual(make(display_name="  이름  ").display_name, "이름", "앞뒤 공백만 있으면 그냥 정리한다")
        self.refuses(display_name="이\u200b름")                              # 보이지 않는 글자가 섞인 이름은 고쳐 받지 않고 거절한다
        self.refuses(display_name="이  름")                                  # 안쪽의 겹친 공백도 한 줄로 정리된 모양이 아니다
        self.assertEqual(len(make(display_name="가" * 60).display_name), 60)
        for bad in ("", "   ", "가" * 61, None, 5, ["이름"]):
            with self.subTest(bad=repr(bad)[:20]):
                self.refuses(display_name=bad)

    def test_the_blog_address_must_be_a_plain_https_naver_blog_address(self):
        for url in ("https://blog.naver.com/abc", "https://m.blog.naver.com/abc", "https://blog.naver.com/abc/", "https://blog.naver.com/a/b"):
            with self.subTest(url=url):
                self.assertEqual(make(blog_url=url).blog_url, url)
        for url in ("http://blog.naver.com/abc", "https://blog.naver.com", "https://blog.naver.com/", "https://evil.example/abc", "https://blog.naver.com.evil.example/abc",
                    "https://user:pw@blog.naver.com/abc", "https://blog.naver.com/abc?x=1", "https://blog.naver.com/abc#top", "https://blog.naver.com/a bc", "ftp://blog.naver.com/abc",
                    "", None, 5, "https://blog.naver.com/" + "a" * 200, "blog.naver.com/abc", "https://NAVER.com/abc", "https://cafe.naver.com/abc"):
            with self.subTest(url=str(url)[:40]):
                self.refuses(blog_url=url)

    def test_free_text_fields_are_one_short_line(self):
        for field in ("topic", "audience", "tone", "image_spec", "publish_cycle", "disclosure"):
            with self.subTest(field=field):
                self.assertEqual(getattr(make(**{field: "한 줄"}), field), "한 줄")
                self.assertEqual(getattr(make(**{field: ""}), field), "")
                self.refuses(**{field: "줄\n바꿈"})
                self.refuses(**{field: "가" * (301 if field == "disclosure" else 201)})
                self.refuses(**{field: 5})
        self.assertEqual(len(make(topic="가" * 200).topic), 200)
        self.assertEqual(len(make(disclosure="가" * 300).disclosure), 300)

    def test_number_settings_are_integers_in_range_and_ordered(self):
        good = {"min_chars": 0, "max_chars": 1, "max_title_chars": 200, "paragraph_max_chars": 40, "max_tags": 30}
        self.assertEqual(make(**good).max_title_chars, 200)
        self.assertEqual(make(min_chars=5, max_chars=5).max_chars, 5)
        self.assertEqual(make(max_chars=100000, min_chars=100000).max_chars, 100000)
        for field, bad in (("min_chars", -1), ("min_chars", 100001), ("min_chars", True), ("min_chars", "5"), ("min_chars", 5.0), ("max_chars", 0), ("max_chars", 100001),
                           ("max_title_chars", 0), ("max_title_chars", 201), ("paragraph_max_chars", 39), ("paragraph_max_chars", 2001), ("max_tags", 0), ("max_tags", 31), ("max_tags", None)):
            with self.subTest(field=field, bad=bad):
                self.refuses(**{field: bad})
        self.refuses(min_chars=500, max_chars=499)
        self.assertEqual(make(min_chars=500, max_chars=500).min_chars, 500)

    def test_word_lists_have_no_empty_duplicate_or_overlong_words(self):
        for field, limit, count in (("default_tags", 30, 30), ("forbidden_phrases", 60, 100)):
            with self.subTest(field=field):
                words = tuple(f"낱말{index}" for index in range(count))
                self.assertEqual(getattr(make(**{field: words}), field), words)
                self.assertEqual(getattr(make(**{field: ["가" * limit]}), field), ("가" * limit,))
                self.assertEqual(getattr(make(**{field: ["  앞뒤 "]}), field), ("앞뒤",))
                self.refuses(**{field: words + ("하나 더",)})
                self.refuses(**{field: ["가" * (limit + 1)]})
                self.refuses(**{field: ["", "가"]})
                self.refuses(**{field: ["가", "가"]})
                self.refuses(**{field: ["Abc", "aBC"]})
                self.refuses(**{field: "문자열 하나"})
                self.refuses(**{field: "가나다"})                           # 글자마다 낱말이 되어 통과해 버리면 안 된다
                self.refuses(**{field: [5]})
                self.refuses(**{field: 5})
        self.assertEqual(make(default_tags={"가", "나"}).default_tags in (("가", "나"), ("나", "가")), True)

    def test_category_mapping_is_pairs_without_duplicates(self):
        self.assertEqual(make(categories={"건강": "생활 건강", "음식": "맛집"}).categories, (("건강", "생활 건강"), ("음식", "맛집")))
        self.assertEqual(make(categories=[["건강", "생활 건강"], ("음식", "맛집")]).categories, (("건강", "생활 건강"), ("음식", "맛집")))
        self.assertEqual(len(make(categories={f"분류{index}": "이름" for index in range(50)}).categories), 50)
        for bad in ({f"분류{index}": "이름" for index in range(51)}, [("건강", "a"), ("건강", "b")], [("건강", "a"), ("건강".upper(), "b")], [("health", "a"), ("Health", "b")], [("", "a")], [("a", "")], [("a",)], [("a", "b", "c")], [5],
                    "건강", {"a": 5}, {5: "a"}, [("가" * 61, "a")], [("a", "가" * 61)]):
            with self.subTest(bad=str(bad)[:40]):
                self.refuses(categories=bad)

    def test_category_lookup_ignores_case_and_gives_nothing_for_an_unknown_one(self):
        profile = make(categories={"Health": "생활 건강", "음식": "맛집"})
        self.assertEqual(profile.category_for("health"), "생활 건강")
        self.assertEqual(profile.category_for("  HEALTH  "), "생활 건강")
        self.assertEqual(profile.category_for("음식"), "맛집")
        self.assertEqual(profile.category_for("여행"), "")
        self.assertEqual(profile.category_for(""), "")
        self.assertEqual(make().category_for("음식"), "")

    def test_the_disclosure_falls_back_to_the_default_text(self):
        self.assertEqual(make().disclosure_text(), DEFAULT_DISCLOSURE)
        self.assertEqual(make(disclosure="AI 도움을 받았습니다.").disclosure_text(), "AI 도움을 받았습니다.")
        self.assertIn("AI", DEFAULT_DISCLOSURE)

    def test_a_profile_cannot_be_changed_after_it_is_made(self):
        profile = make()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            profile.display_name = "다른 이름"
        self.assertEqual(profile, make())
        self.assertEqual(hash(make(default_tags=("가",))), hash(make(default_tags=["가"])))


class StoredShapeTest(unittest.TestCase):
    FULL = {
        "key": "naver_b", "display_name": "블로그 B", "blog_url": "https://blog.naver.com/example_b", "topic": "생활", "audience": "직장인", "tone": "차분한 말투",
        "categories": [["건강", "생활 건강"]], "default_tags": ["생활", "팁"], "forbidden_phrases": ["무조건"], "image_spec": "가로 800px 이상", "min_chars": 500, "max_chars": 4000,
        "max_title_chars": 50, "paragraph_max_chars": 150, "max_tags": 8, "disclosure": "AI 도움을 받았습니다.", "publish_cycle": "주 2회",
    }

    def test_the_stored_shape_round_trips(self):
        profile = NaverProfile.from_dict(self.FULL)
        self.assertEqual(profile.to_dict(), self.FULL)
        self.assertEqual(NaverProfile.from_dict(profile.to_dict()), profile)
        self.assertEqual(sorted(make().to_dict()), sorted(self.FULL), "저장되는 칸 목록")

    def test_only_the_three_required_fields_may_be_missing_others(self):
        profile = NaverProfile.from_dict(GOOD)
        self.assertEqual(profile, make())

    def test_unknown_or_missing_required_fields_are_refused(self):
        for bad in ({**GOOD, "비밀": "x"}, {"key": "naver_a", "display_name": "x"}, {"display_name": "x", "blog_url": GOOD["blog_url"]}, {}, [], None, "text", 5,
                    {**GOOD, "min_chars": "5"}):
            with self.subTest(bad=str(bad)[:40]):
                with self.assertRaises(AppError) as caught:
                    NaverProfile.from_dict(bad)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_the_stored_shape_has_no_secrets(self):
        text = repr(make(topic="생활").to_dict()).lower()
        for needle in ("password", "token", "cookie", "secret", "session"):
            self.assertNotIn(needle, text)


if __name__ == "__main__":
    unittest.main()
