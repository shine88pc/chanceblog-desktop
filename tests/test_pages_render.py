"""GitHub Pages(Chance 블로그) 글 만들기 시험 — 실제 글 두 편(한글·영어)을 글자 단위로 되살리고, 경로·머리말·본문 규칙과 거절을 확인한다.

지키는 것:
  1) 렌더러가 chanceblog 생성기의 실제 결과(tests/fixtures 의 두 글)를 경로·머리말·본문까지 글자 그대로 만든다 — 설명 자동 추출도 같다.
  2) 파일 이름·폴더 규칙(한국 시각, KR/EN, 안전한 폴더 이름, Windows 에서 못 만드는 글자 정리).
  3) 머리말 값은 한 줄 JSON 으로 안전하게(따옴표·역슬래시·줄바꿈 글자), 본문은 줄바꿈·BOM 을 정리하고 머리말처럼 시작하지 않으며 대표 이미지가 한 번은 있다.
  4) 잘못된 값은 CONTENT_INVALID(어느 항목인지)로 거절하고, 원고(project)는 바꾸지 않는다. 파일은 쓰지 않는다(순수 함수).
네트워크 없이 돈다.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import ContentProject  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.render import front_matter_problems, post_path, render_pages_post  # noqa: E402
from chanceblog_desktop.render import pages  # noqa: E402

KST = timezone(timedelta(hours=9))
FIXTURES = ROOT / "tests" / "fixtures"
IMAGE = "https://images.unsplash.com/photo-1?auto=format&fit=crop&w=1000&q=80"
NOW = datetime(2026, 10, 28, 18, 48, 44, tzinfo=KST)
LONG_PARAGRAPH = "이 문단은 설명으로 뽑히기에 충분히 길어서 예순 글자를 넘기도록 일부러 길게 쓴 문장입니다. 두 번째 문장까지 이어서 씁니다."


def parse_fixture(name):
    raw = (FIXTURES / name).read_bytes().decode("utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n\n(.*)\Z", raw, re.S)
    front = {}
    for line in match.group(1).split("\n"):
        key, value = line.split(": ", 1)
        front[key] = value
    return raw, front, match.group(2)


def proj(body="본문입니다.\n\n둘째 문단입니다.", title="제목입니다"):
    return ContentProject.new(title, body, project_id="p1", now="2026-10-30T03:00:00Z")


def render(**kwargs):
    kwargs.setdefault("project", proj())
    kwargs.setdefault("category", "생활")
    kwargs.setdefault("lang", "ko")
    kwargs.setdefault("image_url", IMAGE)
    kwargs.setdefault("now", NOW)
    return render_pages_post(kwargs.pop("project"), **kwargs)


def raises_item(test, item, **kwargs):
    with test.assertRaises(AppError) as caught:
        render(**kwargs)
    test.assertEqual(caught.exception.code, "CONTENT_INVALID", caught.exception.detail)
    test.assertEqual(caught.exception.slots["항목"], item, caught.exception.detail)


class GoldenTest(unittest.TestCase):
    CASES = (("en", "chance_post_en.md", datetime(2026, 10, 28, 18, 48, 44, tzinfo=KST)), ("ko", "chance_post_ko.md", datetime(2026, 10, 29, 10, 16, 52, tzinfo=KST)))

    def build(self, lang, name, stamp, **overrides):
        raw, front, body = parse_fixture(name)
        project = proj(body=body, title=json.loads(front["title"]))
        kwargs = dict(category=json.loads(front["category"]), lang=lang, image_url=json.loads(front["image"]), tags=json.loads(front["tags"]),
                      source={"name": json.loads(front["source_name"]), "url": json.loads(front["source_url"]), "title": "원문"}, now=stamp)
        kwargs.update(overrides)
        return raw, front, body, render_pages_post(project, **kwargs)

    def test_the_two_real_posts_are_reproduced_byte_for_byte_with_the_same_file_name(self):
        for lang, name, stamp in self.CASES:
            with self.subTest(lang=lang):
                raw, _front, _body, post = self.build(lang, name, stamp)
                self.assertEqual(post.text, raw)
                self.assertEqual(post.path, {"en": "_posts/Society & Policy/2026-10-28-EN-184844.md", "ko": "_posts/경제·일/2026-10-29-KR-101652.md"}[lang])
                self.assertEqual((post.lang, post.category), (lang, json.loads(parse_fixture(name)[1]["category"])))

    def test_the_automatic_description_is_what_the_real_posts_carry(self):
        for lang, name, _stamp in self.CASES:
            with self.subTest(lang=lang):
                _raw, front, body = parse_fixture(name)
                self.assertEqual(pages.auto_description(body), json.loads(front["description"]))

    def test_the_real_posts_pass_the_checker_and_have_the_documented_key_order(self):
        for _lang, name, _stamp in self.CASES:
            raw, front, _body = parse_fixture(name)
            self.assertEqual(front_matter_problems(raw), [])
            self.assertEqual(list(front), ["layout", "title", "category", "tags", "lang", "image", "description", "source_name", "source_url", "source_domain"])

    def test_git_is_told_not_to_convert_the_fixtures_line_endings(self):
        rules = [line.strip() for line in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()]
        self.assertIn("tests/fixtures/** -text", rules, "없으면 Windows 에서 기준 글이 CRLF 로 바뀌어 글자 대조가 어긋난다")

    def test_the_fixtures_are_unix_text_without_a_byte_order_mark(self):
        for _lang, name, _stamp in self.CASES:
            data = (FIXTURES / name).read_bytes()
            self.assertNotIn(b"\r", data)
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
            self.assertTrue(data.endswith(b"\n") and not data.endswith(b"\n\n"))


class PathTest(unittest.TestCase):
    def test_the_file_name_uses_korean_time_and_the_language_prefix(self):
        self.assertEqual(post_path("생활", "ko", datetime(2026, 10, 28, 9, 48, 44, tzinfo=timezone.utc)), "_posts/생활/2026-10-28-KR-184844.md")
        self.assertEqual(post_path("Tech", "en", datetime(2026, 10, 28, 9, 48, 44, tzinfo=timezone.utc)), "_posts/Tech/2026-10-28-EN-184844.md")
        self.assertEqual(post_path("Tech", "en", datetime(2026, 10, 28, 23, 30, 5, tzinfo=timezone.utc)), "_posts/Tech/2026-10-29-EN-083005.md", "UTC 밤은 한국 시각으로 다음 날")
        self.assertEqual(post_path("Tech", "en", datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=-5)))), "_posts/Tech/2026-01-02-EN-170405.md")

    def test_a_time_without_a_zone_or_a_non_time_is_refused(self):
        for bad in (datetime(2026, 10, 28, 9, 0, 0), "2026-10-28", None, 5):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(AppError) as caught:
                    post_path("생활", "ko", bad)
                self.assertEqual((caught.exception.code, caught.exception.slots["항목"]), ("CONTENT_INVALID", "시각"))

    def test_without_a_time_the_current_time_is_used_in_the_right_shape(self):
        self.assertRegex(render(now=None).path, r"^_posts/생활/\d{4}-\d{2}-\d{2}-KR-\d{6}\.md$")

    def test_folder_names_are_made_safe_like_the_generator_and_for_windows(self):
        cases = {
            "경제·일": "경제·일", "Society & Policy": "Society & Policy", "a/b": "a-b", "a\\b": "a-b", "../x": "-x", "a..b": "a.b", "  spaced  ": "spaced",
            "끝점.": "끝점", 'Q&A: "왜"?': 'Q&A- -왜--', "a|b*c<d>e": "a-b-c-d-e", "line\nbreak": "line-break", "": "KR - Uncategorized", "   ": "KR - Uncategorized", "...": "KR - Uncategorized",
        }
        for category, expected in cases.items():
            with self.subTest(category=category):
                self.assertEqual(pages.category_dir(category, "ko"), expected)
        self.assertEqual(pages.category_dir("", "en"), "EN - Uncategorized")


class FrontMatterTest(unittest.TestCase):
    def header(self, post):
        return post.text.split("\n---\n", 1)[0].split("\n")

    def test_the_header_lines_come_in_the_documented_order(self):
        lines = self.header(render(project=proj(body=LONG_PARAGRAPH), source={"name": "출처", "url": "https://example.com/a", "title": "기사"}))
        self.assertEqual([line.split(":", 1)[0] for line in lines], ["---", "layout", "title", "category", "tags", "lang", "image", "description", "source_name", "source_url", "source_domain"])
        self.assertEqual(lines[1], "layout: post")

    def test_title_and_category_are_one_line_json_even_with_quotes_backslashes_and_line_separators(self):
        post = render(project=proj(title='그는 "안녕" 이라고 \\ 말했다\u2028다음'), category='"따옴표" 분야')
        lines = self.header(post)
        self.assertEqual(json.loads(lines[2][len("title: "):]), '그는 "안녕" 이라고 \\ 말했다\u2028다음')
        self.assertIn("\\u2028", lines[2])
        self.assertNotIn("\u2028", post.text)
        self.assertEqual(json.loads(lines[3][len("category: "):]), '"따옴표" 분야')
        self.assertEqual(front_matter_problems(post.text), [])

    def test_tags_are_a_json_list_without_duplicates(self):
        self.assertIn('tags: ["a", "B", "한글"]', render(tags=["a", "B", "b", "A", "한글"]).text)
        self.assertIn("tags: []", render().text)
        self.assertIn("tags: []", render(tags=[]).text)

    def test_bad_tags_are_refused(self):
        for bad in ("a,b", b"a", [""], ["  "], ["x" * 41], [5], ["a\nb"], [f"t{i}" for i in range(11)], ["a\x00"]):
            with self.subTest(bad=repr(bad)[:30]):
                raises_item(self, "태그", tags=bad)

    def test_the_description_is_given_automatic_or_left_out(self):
        self.assertIn('description: "직접 쓴 설명"', render(description="직접 쓴 설명").text)
        automatic = render(project=proj(body=LONG_PARAGRAPH))
        self.assertRegex(automatic.text, r'\ndescription: "이 문단은 설명으로 뽑히기에')
        self.assertNotIn("\ndescription:", render().text, "뽑을 문단이 없으면 줄을 쓰지 않는다")
        self.assertNotIn("\ndescription:", render(project=proj(body="짧은 글")).text)

    def test_the_automatic_description_is_cut_at_a_word_and_ends_with_an_ellipsis(self):
        text = pages.auto_description("가나다 " * 80)
        self.assertTrue(text.endswith("…"))
        self.assertLessEqual(len(text), 156)
        self.assertFalse(text[:-1].endswith(" "))
        self.assertEqual(pages.auto_description("![그림](https://x/y.png)\n\n" + LONG_PARAGRAPH), LONG_PARAGRAPH, "이미지만 있는 문단은 건너뛴다")
        self.assertEqual(pages.auto_description("# 제목\n\n[링크 글자](https://x) " + "가" * 70), "링크 글자 " + "가" * 70)

    def test_the_automatic_description_needs_a_paragraph_of_sixty_characters(self):
        self.assertEqual(pages.auto_description("가" * 59), "")
        self.assertEqual(pages.auto_description("가" * 60), "가" * 60)
        self.assertEqual(pages.auto_description("가" * 59 + "\n\n" + "나" * 60), "나" * 60, "짧은 문단은 건너뛰고 다음 문단을 본다")
        self.assertEqual(pages.auto_description("가" * 155), "가" * 155)
        self.assertEqual(pages.auto_description("가" * 156), "가" * 155 + "…", "155자를 넘으면 자르고 말줄임표")

    def test_a_bad_description_is_refused(self):
        for bad in ("줄\n바꿈", "x" * 301, 5, "\x00"):
            with self.subTest(bad=repr(bad)[:20]):
                raises_item(self, "설명", description=bad)

    def test_image_and_language_and_category_are_checked(self):
        for bad in ("", "http://x.com/a.png", "ftp://x.com/a", "https://u:p@x.com/a.png", "https://x.com/a b.png", "https://", "javascript:alert(1)", None, 5):
            with self.subTest(image=bad):
                raises_item(self, "대표 이미지 주소", image_url=bad)
        for bad in ("fr", "KO", "", None):
            with self.subTest(lang=bad):
                raises_item(self, "언어", lang=bad)
        for bad in ("", "   ", "x" * 101, None, "a\nb", "a\x00b"):
            with self.subTest(category=repr(bad)[:20]):
                raises_item(self, "분야", category=bad)

    def test_the_source_adds_three_lines_and_a_list_unless_the_address_is_already_in_the_body(self):
        source = {"name": "유럽 집행위원회", "url": "https://Commission.Europa.eu/news/a_en", "title": "원문 기사 제목"}
        ko = render(source=source)
        self.assertIn('source_name: "유럽 집행위원회"', ko.text)
        self.assertIn('source_url: "https://Commission.Europa.eu/news/a_en"', ko.text)
        self.assertIn('source_domain: "commission.europa.eu"', ko.text, "도메인은 소문자 호스트")
        self.assertIn("\n\n## 출처\n- [유럽 집행위원회: 원문 기사 제목](https://Commission.Europa.eu/news/a_en)\n", ko.text)
        en = render(lang="en", source=source)
        self.assertIn("\n\n## Sources\n- [", en.text)
        already = render(project=proj(body="본문 [원문](https://Commission.Europa.eu/news/a_en) 참고"), source=source)
        self.assertNotIn("## 출처", already.text)
        default_title = render(source={"name": "이름", "url": "https://example.com/x"})
        self.assertIn("- [이름: 제목입니다](https://example.com/x)", default_title.text, "출처 제목이 없으면 글 제목")

    def test_an_http_source_address_is_accepted_because_older_articles_use_it(self):
        post = render(source={"name": "옛 기사", "url": "http://old.example.org/a", "title": "제목"})
        self.assertIn('source_url: "http://old.example.org/a"', post.text)
        self.assertIn('source_domain: "old.example.org"', post.text)

    def test_the_final_check_catches_a_header_that_the_value_checks_missed(self):
        with mock.patch.object(pages, "json_line", lambda value: str(value)):
            raises_item(self, "머리말")

    def test_a_bad_source_is_refused(self):
        for bad in ({"name": "", "url": "https://x.com/a"}, {"name": "이름", "url": "ftp://x.com/a"}, {"name": "이름", "url": "https://u:p@x.com/a"}, {"name": "이름", "url": "https://x.com/a b"},
                    {"name": "이름"}, {"url": "https://x.com/a"}, {"name": "줄\n바꿈", "url": "https://x.com/a"}):
            with self.subTest(bad=str(bad)[:40]):
                with self.assertRaises(AppError) as caught:
                    render(source=bad)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")


class BodyTest(unittest.TestCase):
    def body_of(self, post):
        return post.text.split("\n---\n\n", 1)[1]

    def test_line_endings_bom_and_blank_edges_are_normalized(self):
        post = render(project=proj(body="\ufeff\r\n\r\n첫 줄\r\n둘째 줄\r\r셋째 줄\r\n\r\n\r\n"))
        self.assertNotIn("\r", post.text)
        self.assertNotIn("\ufeff", post.text)
        self.assertTrue(self.body_of(post).startswith("첫 줄\n둘째 줄\n\n셋째 줄\n\n![Thumbnail]("))
        self.assertTrue(post.text.endswith(")\n") and not post.text.endswith("\n\n"))

    def test_the_thumbnail_is_added_only_when_the_body_has_no_image(self):
        self.assertIn(f"\n\n![Thumbnail]({IMAGE})\n", render().text)
        has = render(project=proj(body=f"앞\n\n![직접 고른 그림](https://example.com/own.png)\n\n뒤"))
        self.assertNotIn("Thumbnail", has.text)
        self.assertEqual(has.text.count("!["), 1)
        inline = render(project=proj(body="문장 안에 ![작은](https://example.com/a.png) 그림이 있다"))
        self.assertIn("![Thumbnail](", inline.text, "줄 맨 앞의 이미지가 아니면 대표 이미지를 더한다")

    def test_a_body_that_starts_like_a_header_is_refused(self):
        for bad in ("---\ntitle: x\n---\n본문", "title: 제목\n본문", "layout: post\n본문", "\n\n  \n---\n본문", "첫\n둘\nlayout: post\n넷", "----\n본문"):
            with self.subTest(bad=bad[:20]):
                raises_item(self, "본문 머리", project=proj(body=bad))
        render(project=proj(body="첫\n둘\n셋\ntitle: 넷째 줄은 괜찮다"))

    def test_control_characters_in_the_body_are_refused(self):
        for bad in ("본문\x00끝", "본문\x1b[31m", "줄\u2028바꿈", "줄\u0085바꿈"):
            with self.subTest(bad=repr(bad)):
                raises_item(self, "본문", project=proj(body=bad))
        render(project=proj(body="탭\t은 괜찮다"))

    def test_the_project_is_not_changed_and_no_file_is_written(self):
        project = proj(body="\ufeff앞\r\n뒤")
        before = project.to_dict()
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                render(project=project)
                self.assertEqual(os.listdir(tmp), [])
            finally:
                os.chdir(old)
        self.assertEqual(project.to_dict(), before)


class CheckerTest(unittest.TestCase):
    GOOD = '---\nlayout: post\ntitle: "제목"\ncategory: "분야"\ntags: ["a"]\nlang: ko\nimage: "https://x.com/a.png"\n---\n\n본문\n'

    def test_a_good_text_has_no_problems(self):
        self.assertEqual(front_matter_problems(self.GOOD), [])
        self.assertEqual(front_matter_problems(self.GOOD.replace('tags: ["a"]\n', "")), [])

    def test_each_broken_rule_is_reported(self):
        def bad(old, new):
            self.assertIn(old, self.GOOD)
            return self.GOOD.replace(old, new)

        cases = {
            "BOM": "\ufeff" + self.GOOD,
            "첫 줄": "\n" + self.GOOD,
            "닫는 줄 없음": self.GOOD.replace("\n---\n", "\n"),
            "닫는 줄 모양": bad("\n---\n\n본문", "\n----\n\n본문"),
            "CR": bad('tags: ["a"]', 'tags: ["a"]\r'),
            "제어 문자": bad("lang: ko", "lang: k\x01o"),
            "키 값 모양 아님": bad("lang: ko", "lang ko"),
            "키 중복": bad("lang: ko", "lang: ko\nlang: en"),
            "값 비어 있음": bad("lang: ko", "lang: "),
            "필수 키 없음": bad("lang: ko\n", ""),
            "layout 값": bad("layout: post", "layout: default"),
            "lang 값": bad("lang: ko", "lang: fr"),
            "title 이 JSON 아님": bad('title: "제목"', "title: 제목"),
            "image 가 JSON 아님": bad('image: "https://x.com/a.png"', "image: https://x.com/a.png"),
            "tags 가 목록 아님": bad('tags: ["a"]', 'tags: "a"'),
            "tags 항목 비어 있음": bad('tags: ["a"]', 'tags: [""]'),
            "본문이 울타리로 시작": bad("\n\n본문\n", "\n\n---\n본문\n"),
            "본문이 머리말처럼 시작": bad("\n\n본문\n", "\n\ntitle: 또\n본문\n"),
            "줄이 너무 김": bad('title: "제목"', 'title: "' + "가" * 2100 + '"'),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertTrue(front_matter_problems(text), name)

    def test_the_messages_never_contain_the_values(self):
        problems = front_matter_problems(self.GOOD.replace('title: "제목"', "title: 비밀스러운제목"))
        self.assertTrue(problems)
        self.assertNotIn("비밀스러운제목", " ".join(problems))


if __name__ == "__main__":
    unittest.main()
