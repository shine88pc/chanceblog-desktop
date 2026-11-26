"""Blogger 글 만들기(`render/blogger.py`) 시험 — BLOGGER 설계서 BT-50–55 + 오류 문구 행(D-770). 접속·파일 쓰기 없이 돈다(순수 변환).

지키는 것:
  1) **사진은 이 PC 를 떠나지 않는다**(BT-50·51): 이 PC 의 사진 파일(`Asset`)·인터넷 주소가 아닌 사진 표기가 하나라도 있으면 `BLOGGER_IMAGE_UNSUPPORTED` 로 멈추고, 파일 이름·경로·사용자 이름은 HTML·오류·표시 어디에도 없다.
  2) **결정적이고 기존 변환기와 같다**(BT-52): 같은 입력 = 같은 출력, 본문은 `markdown_to_html` 결과와 같고 더해진 것은 고정 블록(대표 사진·본문 사진)뿐이다.
  3) 라벨 10개·40자, 제목 200자, 크기 한도(BT-53) · 스크립트·`javascript:`·이벤트 속성은 지워지거나 거절(BT-54) · 대표 사진 블록의 모양과 출처 한 줄(BT-55).
  4) 새 오류 코드 여섯과 고친 기존 문구 셋이 문서 표와 카탈로그에 같게 있고 카드 글이 쉬운 말이다(결정 D-770).
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
import service_support as ss  # noqa: E402,F401  (src 경로를 올린다)

from chanceblog_desktop.content.model import Asset, ContentProject  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError, render  # noqa: E402
from chanceblog_desktop.render import blogger as bl  # noqa: E402
from chanceblog_desktop.render.markdown import markdown_to_html  # noqa: E402
from chanceblog_desktop.ui.core.attribution import PhotoCredit  # noqa: E402

BS = chr(92)
CANARY_NAME = "CANARY_" + "PHOTO" + "_" + "NAME" + "0042"
CANARY_USER = "CANARY_" + "WINUSER" + "_" + "0042"
HERO_URL = "https://images.unsplash.com/photo-1500000000000-aaaaaaaaaaaa?w=1200&ixid=abc123"
BODY = "## 첫 제목\n\n문단 **굵게** 입니다.\n\n둘째 문단입니다.\n\n- 하나\n- 둘\n"


def project(source=BODY, title="시험 글", references=(), assets=()):
    return ContentProject.new(title, source, references, assets, project_id="p0001")


def credit():
    return PhotoCredit("Jane <Doe> & Co", "https://unsplash.com/photos/abc123", "https://unsplash.com/@jane")


def refused(test, source=BODY, assets=()):
    with test.assertRaises(AppError) as caught:
        bl.render_blogger_post(project(source, assets=assets), "ko")
    return caught.exception


def everything_visible(error):
    shown = error.rendered()
    return " ".join([error.code, repr(error.slots), str(error.detail), shown.message, shown.action, repr(error), str(error)])


class LocalImageTest(unittest.TestCase):
    def test_a_local_photo_asset_is_refused_and_its_name_is_nowhere(self):
        """BT-50 — `Asset` 하나가 있으면 멈춘다. 오류에는 사진 개수뿐이다."""
        error = refused(self, assets=(Asset(CANARY_NAME + ".png", "설명"),))
        self.assertEqual((error.code, error.slots), ("BLOGGER_IMAGE_UNSUPPORTED", {"사진 수": "1"}))
        self.assertNotIn(CANARY_NAME, everything_visible(error))
        self.assertIn("1", error.rendered().message)
        error = refused(self, assets=(Asset("a.png"), Asset("b.png")))
        self.assertEqual(error.slots, {"사진 수": "2"})

    def test_every_non_internet_image_notation_in_the_text_counts_as_a_local_photo(self):
        shapes = (f"C:{BS}Users{BS}{CANARY_USER}{BS}a.png", f"c:/Users/{CANARY_USER}/a.png", "file:///C:/Users/" + CANARY_USER + "/a.png", "photo.jpg", "./img/photo.jpg", "../photo.jpg", "/mnt/c/Users/" + CANARY_USER + "/a.png",
                  "data:image/png;base64,AAAA", "//host.example/a.png", "javascript:alert(1)", f"{BS}{BS}server{BS}share{BS}a.png", "~/a.png")
        for url in shapes:
            with self.subTest(url=url[:30]):
                error = refused(self, source=f"{BODY}\n![사진 설명]({url})\n")
                self.assertEqual((error.code, error.slots), ("BLOGGER_IMAGE_UNSUPPORTED", {"사진 수": "1"}))
                self.assertNotIn(CANARY_USER, everything_visible(error))

    def test_assets_and_text_photos_are_added_together(self):
        error = refused(self, source=BODY + "\n![a](photo.jpg)\n\n![b](https://images.unsplash.com/photo-2)\n", assets=(Asset("x.png"),))
        self.assertEqual(error.slots, {"사진 수": "2"})

    def test_an_internet_photo_on_a_blocked_host_is_dropped_with_a_note_and_not_treated_as_local(self):
        for url in ("https://other.example/a.png", "http://images.unsplash.com/photo-1", "https://user:pw@images.unsplash.com/photo-1", "https://images.unsplash.com:8443/photo-1", "https://images.unsplash.com.evil.test/a.png"):
            with self.subTest(url=url):
                post = bl.render_blogger_post(project(BODY + f"\n![사진]({url})\n"), "ko")
                self.assertNotIn("<img", post.html)
                self.assertNotIn("evil.test", post.html)
                self.assertTrue(any("사진" in note for note in post.notes), post.notes)

    def test_the_allowed_photo_host_table_is_exactly_one_host_and_its_neighbours_stay_blocked(self):
        """재작업 1 시험 렌즈 Q 권고 R1 — 허용 사진 호스트 표를 글자 그대로 못박는다. 표가 한 줄이라도 늘면(예: `unsplash.com`) 이 시험이 빨개진다 — 호스트를 더하는 일은 승인과 설계 문서 갱신이 따로 필요한 일이다.
        이웃 호스트(`unsplash.com`·`plus.`·`www.`·`source.`·글자가 붙거나 바뀐 이름)는 막히고, 글에서는 조용히 빠지며 알림만 남는다."""
        self.assertEqual(bl.ALLOWED_IMAGE_HOSTS, ("images.unsplash.com",))
        self.assertEqual(bl.classify_image(HERO_URL), "ok")
        for url in ("https://unsplash.com/photo-1", "https://plus.unsplash.com/premium_photo-1", "https://www.unsplash.com/photo-1", "https://source.unsplash.com/random", "https://evilimages.unsplash.com/photo-1",
                    "https://images.unsplash.com.evil.test/a.png", "https://images.unsplash.org/photo-1", "https://images-unsplash.com/photo-1"):
            with self.subTest(url=url):
                self.assertEqual(bl.classify_image(url), "blocked")
                post = bl.render_blogger_post(project(BODY + f"\n![사진]({url})\n"), "ko")
                self.assertNotIn("<img", post.html)
                self.assertTrue(any("사진" in note for note in post.notes), post.notes)

    def test_a_file_address_with_a_server_name_is_this_pcs_file_and_never_an_internet_photo(self):
        """재작업 1 시험 렌즈 Q 권고 R5 — `file://서버/공유/x.jpg` 는 이 PC 쪽(네트워크 공유) 파일이라 `local` 이다 — 호스트 이름이 있어도 인터넷 사진(`blocked`)이 아니다. `blocked` 는 글에서 조용히 빼고 알림만 하지만 `local` 은 글을 멈춘다
        (사진은 이 PC 를 떠나지 않는다 — BT-50). 옛 표본은 호스트 없는 `file:///C:/…` 뿐이었다."""
        for url in ("file://server/share/photo.jpg", "file://localhost/C:/photo.jpg", "FILE://SERVER/share/a.png", "ftp://server/share/a.png"):
            with self.subTest(url=url):
                self.assertEqual(bl.classify_image(url), "local")
                error = refused(self, source=f"{BODY}\n![사진 설명]({url})\n")
                self.assertEqual((error.code, error.slots), ("BLOGGER_IMAGE_UNSUPPORTED", {"사진 수": "1"}))

    def test_the_html_never_contains_a_local_path_or_a_user_name_for_a_clean_post(self):
        """BT-51 — 사진을 거절하는 길 말고도, 깨끗한 글의 결과에 경로 모양·이 PC 의 사용자 이름이 없다(대표 사진·본문 사진이 있어도)."""
        post = bl.render_blogger_post(project(BODY + "\n![사진](" + HERO_URL + ")\n"), "ko", hero=bl.HeroImage(HERO_URL, credit(), "대표"), tags=("가", "나"))
        for needle in (CANARY_USER, CANARY_NAME, "C:" + BS, "file:", "/Users/", BS):
            self.assertNotIn(needle, post.html)
            self.assertNotIn(needle, post.title)
            self.assertNotIn(needle, " ".join(post.labels + post.notes))


class DeterministicBodyTest(unittest.TestCase):
    def test_without_extras_the_html_is_exactly_the_existing_converter_output(self):
        """BT-52 — 더해진 것이 없을 때 본문은 `markdown_to_html` 결과와 글자까지 같다."""
        post = bl.render_blogger_post(project(BODY), "ko")
        self.assertEqual(post.html, markdown_to_html(BODY))
        self.assertEqual(post.title, "시험 글")
        self.assertEqual((post.labels, post.notes), ((), ()))

    def test_same_input_same_output_every_time(self):
        source = BODY + "\n![사진](" + HERO_URL + ")\n\n[기사](https://news.example/a)\n"
        first = bl.render_blogger_post(project(source, references=("https://news.example/a",)), "en", hero=bl.HeroImage(HERO_URL, credit()), tags=("A", "b"))
        for _ in range(3):
            again = bl.render_blogger_post(project(source, references=("https://news.example/a",)), "en", hero=bl.HeroImage(HERO_URL, credit()), tags=("A", "b"))
            self.assertEqual(again, first)

    def test_only_the_fixed_blocks_are_added_to_the_converter_output(self):
        hero = bl.HeroImage(HERO_URL, credit(), "대표 설명")
        source = BODY + f"\n![본문 사진]({HERO_URL})\n"
        post = bl.render_blogger_post(project(source), "ko", hero=hero)
        base = markdown_to_html(source)
        stripped = post.html.replace(bl.hero_block(hero, "ko"), "").replace(bl.image_block(HERO_URL, "본문 사진", "ko"), "")
        self.assertEqual(stripped, base)
        self.assertTrue(post.html.startswith(bl.hero_block(hero, "ko")), "대표 사진 블록이 맨 앞")

    def test_the_body_photo_lands_after_the_block_it_followed_in_the_text(self):
        source = "첫 문단.\n\n![가운데](" + HERO_URL + ")\n\n끝 문단.\n"
        post = bl.render_blogger_post(project(source), "ko")
        block = bl.image_block(HERO_URL, "가운데", "ko")
        self.assertEqual(post.html, "<p>첫 문단.</p>" + block + "<p>끝 문단.</p>")
        tail = bl.render_blogger_post(project("첫 문단.\n\n![끝](" + HERO_URL + ")\n"), "ko")
        self.assertTrue(tail.html.endswith(bl.image_block(HERO_URL, "끝", "ko")))
        head = bl.render_blogger_post(project("![처음](" + HERO_URL + ")\n\n첫 문단.\n"), "ko")
        self.assertTrue(head.html.startswith(bl.image_block(HERO_URL, "처음", "ko")))

    def test_links_open_only_for_the_hosts_of_the_references(self):
        source = "읽어 보세요 [기사](https://news.example/a) 그리고 [딴 곳](https://other.example/x) 입니다.\n"
        post = bl.render_blogger_post(project(source, references=("https://news.example/a",)), "ko")
        self.assertIn('<a href="https://news.example/a"', post.html)
        self.assertNotIn("other.example", post.html)
        self.assertTrue(any("1" in note and "링크" in note for note in post.notes), post.notes)
        closed = bl.render_blogger_post(project(source), "ko")
        self.assertNotIn("<a ", closed.html, "출처가 없으면 링크는 모두 글자로만 남는다(호스트 표가 비면 아무 https 가 열리는 변환기 규칙을 막는다)")
        self.assertTrue(any("링크" in note for note in closed.notes), closed.notes)
        plain = bl.render_blogger_post(project("링크 없는 글.\n"), "ko")
        self.assertEqual(plain.notes, ())


class LimitsTest(unittest.TestCase):
    def test_title_limits(self):
        """BT-53 — 제목 200자·비었거나 `<`·`>`·줄바꿈·제어 문자가 있으면 거절."""
        self.assertEqual(bl.clean_title("가" * 200), "가" * 200)
        self.assertEqual(bl.clean_title("  앞뒤 공백  "), "앞뒤 공백")
        for bad in ("", "   ", "가" * 201, "a<b", "a>b", "줄\n바꿈", "탭\t글", "x\x00y", "방향\u202e글", None, 5):
            with self.subTest(bad=repr(bad)[:20]), self.assertRaises(AppError) as caught:
                bl.clean_title(bad)
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_label_limits_and_cleaning(self):
        ten = tuple(f"라벨{n}" for n in range(10))
        self.assertEqual(bl.clean_labels(ten), ten)
        self.assertEqual(bl.clean_labels(("가나", "  가나 ", "가나")), ("가나",), "중복은 하나로")
        self.assertEqual(bl.clean_labels(("Python", "python", "PYTHON")), ("Python",), "대소문자만 다른 것도 같은 라벨")
        self.assertEqual(bl.clean_labels(("a,b", "c，d", "e;f")), ("a b", "c d", "e f"), "쉼표류는 공백으로 — 라벨 하나가 둘로 갈라지지 않는다")
        self.assertEqual(bl.clean_labels(("a\x00b", "  ", "")), ("a b",), "제어 문자는 공백으로, 빈 라벨은 버린다")
        self.assertEqual(bl.clean_labels(["가" * 40]), ("가" * 40,))
        for bad in (tuple(f"라벨{n}" for n in range(11)), ("가" * 41,), ("a<b",), ("a>b",), ("<b>",), (5,), "abc", None):         # 꺾쇠는 여는 쪽도 닫는 쪽도 따로 막는다(재작업 1 — 시험 렌즈 Q R5)
            with self.subTest(bad=repr(bad)[:30]), self.assertRaises(AppError) as caught:
                bl.clean_labels(bad)
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_size_limit(self):
        big = ("가" * 90 + "\n\n") * 2000                          # 한글 한 글자 3바이트 — 50만 바이트를 넘긴다
        with self.assertRaises(AppError) as caught:
            bl.render_blogger_post(project(big), "ko")
        self.assertEqual((caught.exception.code, caught.exception.slots), ("CONTENT_INVALID", {"항목": "본문 크기"}))
        ok = bl.render_blogger_post(project(("가" * 90 + "\n\n") * 1000), "ko")
        self.assertLessEqual(len(ok.html.encode("utf-8")), bl.MAX_HTML_BYTES)

    def test_language_and_empty_body_are_checked(self):
        for lang in ("", "ja", None):
            with self.subTest(lang=lang), self.assertRaises(AppError):
                bl.render_blogger_post(project(), lang)
        fake = mock.Mock(title="제목", source_content="   ", references=(), assets=())
        with self.assertRaises(AppError):
            bl.render_blogger_post(fake, "ko")


class InjectionTest(unittest.TestCase):
    def test_script_javascript_and_event_attributes_do_not_come_out(self):
        """BT-54 — 원고 속 위험한 글은 지워지거나 글자로만 남는다."""
        hostile = ("<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n<img src=x onerror=alert(1)>\n\n<iframe src=\"https://evil.test\"></iframe>\n\n"
                   "<a href=\"https://evil.test\" onclick=\"x()\">y</a>\n\n<style>p{}</style>\n\n[z](data:text/html;base64,AAAA)\n")
        post = bl.render_blogger_post(project(hostile, references=("https://news.example/a",)), "ko")
        for needle in ("<script", "javascript:", "<img", "<iframe", "<style", "<a ", "data:text"):
            self.assertNotIn(needle, post.html.lower())
        self.assertIn("&lt;script&gt;", post.html, "원고 속 HTML 은 해석하지 않고 글자로만 남는다")
        self.assertEqual(bl.check_markup(post.html), [], "남은 것은 허용한 태그뿐")

    def test_the_final_check_flags_every_shape_outside_the_allowed_table(self):
        cases = {
            "<script>x</script>": "태그 script", "<iframe></iframe>": "태그 iframe", "<style>p{}</style>": "태그 style", "<embed>": "태그 embed", "<form></form>": "태그 form",
            '<a href="javascript:alert(1)">x</a>': "a 의 속성 href", '<a href="http://plain.example/">x</a>': "a 의 속성 href", '<a href="https://user:pw@h.example/">x</a>': "a 의 속성 href",
            '<a href="https://h.example/" onclick="x()">x</a>': "a 의 속성 onclick", '<a href="https://h.example/" rel="me">x</a>': "a 의 속성 rel", '<a href="https://h.example/" target="_top">x</a>': "a 의 속성 target",
            '<div style="background:url(x)">x</div>': "div 의 속성 style", '<div class="x">x</div>': "div 의 속성 class", '<p style="x">x</p>': "p 의 속성 style", '<p onclick="x()">x</p>': "p 의 속성 onclick",
            '<img src="https://other.example/a.png" alt="x">': "img 의 속성 src", '<img src="http://images.unsplash.com/a.png" alt="x">': "img 의 속성 src", '<img src="https://images.unsplash.com/a.png" onerror="x()">': "img 의 속성 onerror",
            '<img src="https://images.unsplash.com/a.png" alt="x" style="width:9999px">': "img 의 속성 style", "<!-- c -->": "주석", "<!DOCTYPE html>": "선언", "<?php x ?>": "처리 명령",
            '<a href="https://h.example/" href="https://h.example/">x</a>': "a 의 속성 href", "</script>": "닫는 태그 script", "</br>": "닫는 태그 br",
        }
        for html, name in cases.items():
            with self.subTest(html=html[:40]):
                self.assertIn(name, bl.check_markup(html), html)

    def test_clean_blocks_pass_the_final_check(self):
        for html in ("<p>글 <strong>굵게</strong> <em>기울임</em><br></p>", "<h2>제목</h2><ul><li>하나</li></ul><ol><li>둘</li></ol><blockquote>인용</blockquote>", '<p><a href="https://h.example/x?a=1&amp;b=2" rel="nofollow noopener">링크</a></p>',
                     bl.image_block(HERO_URL, "설명", "ko"), bl.hero_block(bl.HeroImage(HERO_URL, credit()), "ko")):
            with self.subTest(html=html[:40]):
                self.assertEqual(bl.check_markup(html), [])

    def test_when_the_converter_lets_a_bad_block_through_the_final_check_stops_the_post(self):
        with mock.patch.object(bl, "markdown_blocks", lambda *args, **kwargs: (["<p>좋은</p>", '<script>alert(1)</script>'], [])):
            with self.assertRaises(AppError) as caught:
                bl.render_blogger_post(project(), "ko")
        self.assertEqual((caught.exception.code, caught.exception.slots), ("CONTENT_INVALID", {"항목": "Blogger 글"}))
        self.assertNotIn("alert", everything_visible(caught.exception), "오류에는 본문 글이 없다")

    def test_the_check_names_problems_without_the_values(self):
        problems = bl.check_markup('<a href="https://h.example/" onclick="CANARY_VALUE_X()">x</a>')
        self.assertEqual(problems, ["a 의 속성 onclick"])
        self.assertNotIn("CANARY_VALUE_X", " ".join(problems))


class HeroBlockTest(unittest.TestCase):
    def test_exact_shape_of_the_hero_block(self):
        """BT-55 — 블로그 저장소 `main_image.build_block` 과 같은 모양(가운데 정렬 div · img · 출처 한 줄)."""
        hero = bl.HeroImage(HERO_URL, credit(), 'He said "hi" <b>')
        name = "Jane &lt;Doe&gt; &amp; Co"
        expected = ('<div style="text-align:center;margin:0 0 1.5em;"><img src="' + HERO_URL.replace("&", "&amp;") + '" alt="He said &quot;hi&quot; &lt;b&gt;" style="max-width:100%;height:auto;">'
                    '<br><small>Photo by <a href="' + credit().profile_link().replace("&", "&amp;") + '" rel="noopener nofollow" target="_blank">' + name + '</a> on <a href="'
                    + credit().photo_link().replace("&", "&amp;") + '" rel="noopener nofollow" target="_blank">Unsplash</a></small></div>')
        self.assertEqual(bl.hero_block(hero, "ko"), expected)
        self.assertIn("utm_source=chanceblog_desktop", expected)
        self.assertEqual(bl.check_markup(expected), [])

    def test_the_credit_line_names_the_photographer_and_links_unsplash_only(self):
        block = bl.hero_block(bl.HeroImage(HERO_URL, credit()), "en")
        hrefs = re.findall(r'href="([^"]+)"', block)
        self.assertEqual(len(hrefs), 2)
        for href in hrefs:
            self.assertTrue(href.startswith("https://unsplash.com/"), href)
        self.assertIn("Photo by", block)
        self.assertIn(">Unsplash</a>", block)

    def test_default_alt_follows_the_language(self):
        self.assertIn('alt="대표 사진"', bl.hero_block(bl.HeroImage(HERO_URL, credit()), "ko"))
        self.assertIn('alt="Featured photo"', bl.hero_block(bl.HeroImage(HERO_URL, credit()), "en"))
        self.assertIn('alt="대표 사진"', bl.image_block(HERO_URL, "  ", "ko"))

    def test_a_hero_on_a_wrong_host_or_with_a_broken_credit_is_refused(self):
        for url in ("https://other.example/a.png", "http://images.unsplash.com/a.png", "C:" + BS + "a.png", ""):
            with self.subTest(url=url), self.assertRaises(AppError) as caught:
                bl.hero_block(bl.HeroImage(url, credit()), "ko")
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        for broken in (None, object(), mock.Mock(photographer_name="", profile_link=lambda: "https://unsplash.com/@a", photo_link=lambda: "https://unsplash.com/photos/a")):
            with self.subTest(broken=type(broken).__name__), self.assertRaises(AppError):
                bl.hero_block(bl.HeroImage(HERO_URL, broken), "ko")

    def test_a_hero_goes_first_and_passes_through_the_post(self):
        post = bl.render_blogger_post(project(), "ko", hero=bl.HeroImage(HERO_URL, credit(), "대표"))
        self.assertTrue(post.html.startswith('<div style="text-align:center;margin:0 0 1.5em;"><img src="https://images.unsplash.com/'))
        self.assertEqual(bl.check_markup(post.html), [])


class ErrorRowsTest(unittest.TestCase):
    """결정 D-770 — 새 오류 코드 여섯과 고친 기존 문구 셋."""

    NEW = {"BLOGGER_NOT_CONNECTED": ((), "after_user"), "BLOGGER_LOGIN_FAILED": (("이유",), "after_user"), "BLOGGER_NOT_DRAFT": ((), "no"),
           "BLOGGER_DRAFT_UNKNOWN": ((), "after_user"), "BLOGGER_IMAGE_UNSUPPORTED": (("사진 수",), "after_user"), "BLOGGER_API_NOT_ENABLED": ((), "after_user")}

    def test_six_new_codes_exist_with_the_planned_slots_and_retry_kind(self):
        for code, (slots, kind) in self.NEW.items():
            with self.subTest(code=code):
                info = CATALOG[code]
                self.assertEqual((info.area, info.slots, info.retry_kind), ("Blogger", slots, kind))
                self.assertTrue(info.when and info.message and info.action)
                doc = (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
                self.assertIn(f"| `{code}` |", doc)

    def test_the_card_text_of_the_new_rows_is_plain_and_has_no_developer_words(self):
        for code in self.NEW:
            with self.subTest(code=code):
                info = CATALOG[code]
                card = info.message + info.action.split("명령줄·개발자 안내:")[0]
                for banned in ("--", "python", "터미널", ".json", ".log", "git ", "옵션", "커밋", "푸시", "프로세스", "`"):
                    self.assertNotIn(banned, card, f"{code}: 카드 글에 개발 말이 있다 — {banned}")
                self.assertTrue(info.action.split("명령줄·개발자 안내:")[0].strip())
                self.assertNotIn("http", info.message + info.action)
                self.assertNotIn("~", info.message + info.action, "ASCII 물결표는 쓰지 않는다")

    def test_the_login_and_image_rows_render_their_slot_values(self):
        shown = render("BLOGGER_LOGIN_FAILED", {"이유": "시간이 지났거나 취소했어요"})
        self.assertIn("시간이 지났거나 취소했어요", shown.message)
        self.assertIn("3분", shown.action)
        self.assertIn("accounts.google.com", shown.action)
        self.assertIn("2", render("BLOGGER_IMAGE_UNSUPPORTED", {"사진 수": "2"}).message)
        self.assertIn("공개", render("BLOGGER_NOT_DRAFT", {}).action)
        self.assertIn("확인 없이", render("BLOGGER_DRAFT_UNKNOWN", {}).action)
        self.assertIn("사용 설정", render("BLOGGER_API_NOT_ENABLED", {}).action)

    def test_the_three_old_rows_changed_only_where_the_design_says(self):
        expired = CATALOG["BLOGGER_AUTH_EXPIRED"]
        self.assertEqual((expired.message, expired.retry_kind), ("Blogger 로그인이 만료되었습니다.", "after_user"))
        card, tail = expired.action.split("명령줄·개발자 안내:")
        self.assertEqual(card.strip(), "Blogger 에 **다시 로그인**합니다(브라우저가 열립니다). 끝나면 '다시 시도' 를 누릅니다.")
        self.assertIn("7일", tail)
        self.assertIn("프로덕션", tail)
        server = CATALOG["BLOGGER_SERVER_ERROR"]
        self.assertEqual((server.retry, server.retry_kind, server.retry_max), ("예(1회)", "auto", 1))
        self.assertIn("확인 없이 다시 보내지 않아요", server.action)
        self.assertTrue(server.action.startswith("몇 분 뒤 다시 시도합니다."))
        denied = CATALOG["BLOGGER_PERMISSION_DENIED"]
        self.assertIn("블로그 번호(숫자)가 맞는지도 확인해 주세요.", denied.action)
        self.assertTrue(denied.action.startswith("로그인한 구글 계정이 그 블로그의 관리자·작성자인지 확인하고"))
        self.assertEqual(CATALOG["BLOGGER_NOT_FOUND"].retry_kind, "no")


if __name__ == "__main__":
    unittest.main()
