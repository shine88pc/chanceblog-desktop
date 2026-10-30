"""Markdown ↔ HTML 변환 시험 — 지원하는 문법이 정해진 HTML 이 되고, 어떤 입력에도 허용 태그만 나오며, 기존 글(HTML)을 Markdown 으로 되돌려도 같은 글이 된다.

지키는 것:
  1) 문법별 결과(제목·문단·줄바꿈·목록 중첩·인용·굵게/기울임·코드·링크·이미지·가로줄)가 정해진 HTML 이다.
  2) 안전: 원고 속 HTML·`javascript:` 링크·허용 밖 주소·이미지는 나가지 않고, 결과는 정화기를 한 번 더 거쳐도 달라지지 않는다. 내부 표지 글자로 속일 수 없다.
  3) HTML → Markdown: 허용 태그만 읽고, Markdown 기호는 역슬래시로 지켜 다시 변환하면 같은 HTML 이 된다(되돌려도 안정).
  4) 어떤 입력에도 예외 없이 빨리 끝난다(무작위 입력·최악의 입력·아주 깊은 중첩·큰 입력).
네트워크 없이 돈다.
"""
import random
import re
import sys
import time
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.render import markdown as md  # noqa: E402
from chanceblog_desktop.render.markdown import html_to_markdown, html_to_text, markdown_blocks, markdown_images, markdown_to_html  # noqa: E402
from pipeline.gates import ALLOWED_TAGS, sanitize_html  # noqa: E402  (render.markdown 이 vendor/ 경로를 올려 둔다)


def attributes_in(html):
    """결과 HTML 의 (태그, 속성 이름, 값) 목록."""
    found = []

    class Reader(HTMLParser):
        def handle_starttag(self, tag, attrs):
            found.extend((tag, name, value) for name, value in attrs)

    Reader(convert_charrefs=True).feed(html)
    return found


def tags_in(html):
    found = set()

    class Reader(HTMLParser):
        def handle_starttag(self, tag, attrs):
            found.add(tag)

        def handle_endtag(self, tag):
            found.add(tag)

    Reader(convert_charrefs=True).feed(html)
    return found


class MarkdownToHtmlTest(unittest.TestCase):
    CASES = (
        ("# 제목", "<h2>제목</h2>"),
        ("## 소제목", "<h2>소제목</h2>"),
        ("### 셋째", "<h3>셋째</h3>"),
        ("#### 넷째 ####", "<h4>넷째</h4>"),
        ("###### 여섯째", "<h4>여섯째</h4>"),
        ("문단 하나\n\n문단 둘", "<p>문단 하나</p><p>문단 둘</p>"),
        ("한 줄\n이어지는 줄", "<p>한 줄 이어지는 줄</p>"),
        ("끝에 공백 둘  \n다음 줄", "<p>끝에 공백 둘<br>다음 줄</p>"),
        ("끝에 역슬래시\\\n다음 줄", "<p>끝에 역슬래시<br>다음 줄</p>"),
        ("**굵게** 와 __굵게__", "<p><strong>굵게</strong> 와 <strong>굵게</strong></p>"),
        ("*기울임* 과 _기울임_", "<p><em>기울임</em> 과 <em>기울임</em></p>"),
        ("***둘 다***", "<p><em><strong>둘 다</strong></em></p>"),
        ("**_둘 다_**", "<p><strong><em>둘 다</em></strong></p>"),
        ("*가 _나_ 다*", "<p><em>가 나 다</em></p>"),
        ("_*밑*_", "<p><em>밑</em></p>"),
        ("**가 __나__ 다**", "<p><strong>가 나 다</strong></p>"),
        ("**굵게 *기울임* 굵게**", "<p><strong>굵게 <em>기울임</em> 굵게</strong></p>"),
        ("*기울임 **굵게** 기울임*", "<p><em>기울임 <strong>굵게</strong> 기울임</em></p>"),
        ("snake_case_word 는 그대로", "<p>snake_case_word 는 그대로</p>"),
        ("2 * 3 * 4", "<p>2 * 3 * 4</p>"),
        ("`코드 <b>` 조각", "<p>코드 &lt;b&gt; 조각</p>"),
        ("``백틱 ` 포함``", "<p>백틱 ` 포함</p>"),
        ("- 하나\n- 둘", "<ul><li>하나</li><li>둘</li></ul>"),
        ("* 별표\n+ 더하기", "<ul><li>별표</li><li>더하기</li></ul>"),
        ("1. 첫째\n2. 둘째\n3) 셋째", "<ol><li>첫째</li><li>둘째</li><li>셋째</li></ol>"),
        ("- 상위\n  - 하위 하나\n  - 하위 둘\n- 상위 둘", "<ul><li>상위<ul><li>하위 하나</li><li>하위 둘</li></ul></li><li>상위 둘</li></ul>"),
        ("1. 번호\n   - 그 아래 점\n2. 둘째", "<ol><li>번호<ul><li>그 아래 점</li></ul></li><li>둘째</li></ol>"),
        ("- 점\n\n1. 번호", "<ul><li>점</li></ul><ol><li>번호</li></ol>"),
        ("1. 하나\n\n2. 둘\n\n3. 셋", "<ol><li>하나</li><li>둘</li><li>셋</li></ol>"),
        ("- 이어지는\n  두 줄", "<ul><li>이어지는 두 줄</li></ul>"),
        ("> 인용\n> 둘째 줄", "<blockquote><p>인용 둘째 줄</p></blockquote>"),
        ("> # 인용 속 제목\n>\n> - 목록", "<blockquote><h2>인용 속 제목</h2><ul><li>목록</li></ul></blockquote>"),
        ("> 바깥\n>> 안쪽", "<blockquote><p>바깥</p><blockquote><p>안쪽</p></blockquote></blockquote>"),
        ("앞\n\n---\n\n뒤", "<p>앞</p><p>뒤</p>"),
        ("```\n줄 하나\n  줄 둘 <i>\n```", "<p>줄 하나<br>  줄 둘 &lt;i&gt;</p>"),
        ("~~~python\nprint(1)\n~~~", "<p>print(1)</p>"),
        ("```\n닫히지 않은 코드", "<p>닫히지 않은 코드</p>"),
        ("```\n코드\n```\n뒤 글\n둘째 줄", "<p>코드</p><p>뒤 글 둘째 줄</p>"),
        ("```\n```", ""),
        ("- 상위\n\t- 탭으로 들여쓴 하위", "<ul><li>상위<ul><li>탭으로 들여쓴 하위</li></ul></li></ul>"),
        ("- 하나\n\n  같은 항목의 다음 문단", "<ul><li>하나 같은 항목의 다음 문단</li></ul>"),
        ("`  앞뒤 공백  ` 끝", "<p>앞뒤 공백 끝</p>"),
        ("> \n>", ""),
        ("- ` 코드 ` 목록", "<ul><li>코드 목록</li></ul>"),
        ("# ` 제목 코드 `", "<h2>제목 코드</h2>"),
        ("**` 굵은 코드 `** 끝", "<p><strong>굵은 코드</strong> 끝</p>"),
        ("- 앞 ![그림](https://img.example/1.png) 뒤", "<ul><li>앞 뒤</li></ul>"),
        ("# ![그림](https://img.example/1.png) 제목", "<h2>제목</h2>"),
        ("- a\n  - b\n    - c\n      - d\n        1. e", "<ul><li>a<ul><li>b<ul><li>c<ul><li>d</li><li>e</li></ul></li></ul></li></ul></li></ul>"),
        ("끝에 홀로 둔 역슬래시\\", "<p>끝에 홀로 둔 역슬래시\\</p>"),
        ("- 하나\n  * * *\n- 둘", "<ul><li>하나 * * *</li><li>둘</li></ul>"),
        ("앞 글\n> 인용", "<p>앞 글</p><blockquote><p>인용</p></blockquote>"),
        ("앞 글\n```\n코드\n```", "<p>앞 글</p><p>코드</p>"),
        ("앞 글\n***\n뒤 글", "<p>앞 글</p><p>뒤 글</p>"),
        ("앞 글\n# 제목", "<p>앞 글</p><h2>제목</h2>"),
        ("앞 글\n1. 번호", "<p>앞 글</p><ol><li>번호</li></ol>"),
        ("2026. 10. 30 에 시작했다", "<p>2026. 10. 30 에 시작했다</p>"),
        ("#해시태그 는 제목이 아니다", "<p>#해시태그 는 제목이 아니다</p>"),
        ("\\*별표\\* 와 \\# 샵 과 \\\\ 역슬래시", "<p>*별표* 와 # 샵 과 \\ 역슬래시</p>"),
        ("A & B < C > D", "<p>A &amp; B &lt; C &gt; D</p>"),
        ("", ""),
        ("   \n\n  ", ""),
        ("# \n\n#", ""),
    )

    def test_each_construct_becomes_the_expected_html(self):
        for source, expected in self.CASES:
            with self.subTest(source=source[:40]):
                self.assertEqual(markdown_to_html(source), expected)

    def test_windows_line_endings_tabs_bom_and_control_characters_are_normalized(self):
        self.assertEqual(markdown_to_html("\ufeff# 제목\r\n\r\n본문\r\n둘째 줄\x00\x07"), "<h2>제목</h2><p>본문 둘째 줄</p>")
        self.assertEqual(markdown_to_html("-\t탭 목록\n-\t둘"), "<ul><li>탭 목록</li><li>둘</li></ul>")
        self.assertEqual(markdown_to_html("old mac\r두번째 줄\r\r새 문단"), "<p>old mac 두번째 줄</p><p>새 문단</p>")

    def test_a_list_after_a_paragraph_and_an_interrupting_heading_split_the_blocks(self):
        self.assertEqual(markdown_to_html("문단\n- 목록\n# 제목\n끝"), "<p>문단</p><ul><li>목록</li></ul><h2>제목</h2><p>끝</p>")

    def test_a_numbered_list_only_starts_with_one_so_dates_and_years_keep_their_numbers(self):
        self.assertEqual(markdown_to_html("문단\n2. 이어지는 줄"), "<p>문단 2. 이어지는 줄</p>")
        self.assertEqual(markdown_to_html("1. 목록\n5. 번호가 건너뛰어도 목록"), "<ol><li>목록</li><li>번호가 건너뛰어도 목록</li></ol>")
        self.assertEqual(markdown_to_html("3. 3번부터는 목록이 아니다"), "<p>3. 3번부터는 목록이 아니다</p>")

    def test_links_are_text_unless_allowed_and_https_and_on_an_allowed_host(self):
        source = "[내 글](https://example.com/a?b=1&c=2) [위험](javascript:alert(1)) [메일](mailto:a@b.c) [http](http://example.com) <https://auto.example.com/x>"
        self.assertEqual(markdown_to_html(source), "<p>내 글 위험 메일 http https://auto.example.com/x</p>")
        allowed = markdown_to_html(source, allow_links=True, allowed_hosts=("example.com", "auto.example.com"))
        self.assertIn('<a href="https://example.com/a?b=1&amp;c=2" rel="nofollow noopener">내 글</a>', allowed)
        self.assertIn('<a href="https://auto.example.com/x" rel="nofollow noopener">https://auto.example.com/x</a>', allowed)
        for gone in ("javascript", "mailto", "http://example.com"):
            self.assertNotIn(gone, allowed)
        only_other = markdown_to_html("[a](https://evil.example/x)", allow_links=True, allowed_hosts=("example.com",))
        self.assertEqual(only_other, "<p>a</p>")
        anyhost = markdown_to_html("[a](https://evil.example/x)", allow_links=True)
        self.assertIn("https://evil.example/x", anyhost)
        self.assertEqual(markdown_to_html("[a](https://user:pw@example.com/)", allow_links=True), "<p>a</p>", "로그인 정보가 든 주소는 링크로 두지 않는다")
        self.assertEqual(markdown_to_html("[`코드` 와 \\*별\\*](https://example.com/)", allow_links=True), '<p><a href="https://example.com/" rel="nofollow noopener">코드 와 *별*</a></p>')
        self.assertIn("<a ", markdown_to_html("[a](https://blog.example.com/x)", allow_links=True, allowed_hosts=("Example.COM",)), "허용 주소는 대소문자를 가리지 않는다")
        self.assertEqual(markdown_to_html('[x](https://ok.example/a"b)', allow_links=True), '<p><a href="https://ok.example/a&quot;b" rel="nofollow noopener">x</a></p>', "주소 속 따옴표는 속성을 끊지 못한다")
        inner = markdown_to_html("[**굵은** 링크 글](https://example.com/)", allow_links=True)
        self.assertEqual(inner, '<p><a href="https://example.com/" rel="nofollow noopener"><strong>굵은</strong> 링크 글</a></p>')

    def test_subdomains_of_an_allowed_host_are_allowed_but_lookalikes_are_not(self):
        for url, ok in (("https://blog.example.com/x", True), ("https://example.com/x", True), ("https://notexample.com/x", False), ("https://example.com.evil.example/x", False)):
            with self.subTest(url=url):
                html = markdown_to_html(f"[t]({url})", allow_links=True, allowed_hosts=("example.com",))
                self.assertEqual("<a " in html, ok)

    def test_images_are_not_in_the_html_but_are_listed_in_order_outside_code(self):
        source = "앞 ![ 첫째 그림 ](https://img.example/1.png) 뒤\n\n![](https://img.example/2.png)\n\n`![코드 속](x)`\n\n```\n![블록 속](y)\n```\n\n![셋째](https://img.example/3.png \"제목\")"
        self.assertEqual(markdown_to_html(source), "<p>앞 뒤</p><p>![코드 속](x)</p><p>![블록 속](y)</p>")
        self.assertEqual(markdown_images(source), [("첫째 그림", "https://img.example/1.png"), ("", "https://img.example/2.png"), ("셋째", "https://img.example/3.png")])

    def test_the_same_emphasis_inside_itself_is_merged_and_odd_html_is_left_alone(self):
        self.assertEqual(md._flatten_emphasis("<em>가<em>나</em><strong>다<em>라</em></strong></em>"), "<em>가나<strong>다라</strong></em>")
        self.assertEqual(md._flatten_emphasis("<strong>가</strong><strong>나</strong>"), "<strong>가</strong><strong>나</strong>")
        for odd in ("<em>가</strong>", "<em>가", "<em><em>가", "가</em>", "<em><strong>가</em></strong>"):                        # 짝이 맞지 않으면 손대지 않는다
            self.assertEqual(md._flatten_emphasis(odd), odd)

    def test_emphasis_inside_words_follows_the_usual_rules(self):
        self.assertEqual(markdown_to_html("a*b*c"), "<p>a<em>b</em>c</p>")
        self.assertEqual(markdown_to_html("a_b_c"), "<p>a_b_c</p>")
        self.assertEqual(markdown_to_html("**굵게**글자"), "<p><strong>굵게</strong>글자</p>")
        self.assertEqual(markdown_to_html("** 공백 있으면 아니다 **"), "<p>** 공백 있으면 아니다 **</p>")
        self.assertEqual(markdown_to_html("a__b__c"), "<p>a__b__c</p>")
        self.assertEqual(markdown_to_html("_a_b"), "<p>_a_b</p>")
        self.assertEqual(markdown_to_html("a__b__ c"), "<p>a__b__ c</p>")
        self.assertEqual(markdown_to_html("__b__c"), "<p>__b__c</p>")
        self.assertEqual(markdown_to_html("a_b_ c"), "<p>a_b_ c</p>")

    def test_the_link_check_is_strict_by_itself_not_only_through_the_final_cleaning(self):
        anywhere, only_example, nothing = md._Context(True, ()), md._Context(True, ("example.com",)), md._Context(False, ())
        cases = (
            (anywhere, "https://example.com/a", True), (anywhere, "https://example.com/a b", False), (anywhere, "https://example.com/a\tb", False), (anywhere, "https://example.com/a\x00b", False),
            (anywhere, "", False), (anywhere, "http://example.com/a", False), (anywhere, "javascript:alert(1)", False), (anywhere, "https://user:pw@example.com/", False), (anywhere, "https:///nohost", False),
            (only_example, "https://example.com/a", True), (only_example, "https://blog.example.com/a", True), (only_example, "https://notexample.com/a", False),
            (only_example, "https://example.com.evil.example/a", False), (only_example, "https://other.example/a", False),
            (nothing, "https://example.com/a", False),
        )
        for context, url, ok in cases:
            with self.subTest(url=url, hosts=context.allowed_hosts, links=context.allow_links):
                self.assertEqual(md._link_ok(url, context), ok)
        self.assertTrue(md._link_ok("https://blog.example.com/a", md._Context(True, ("Example.COM",))), "허용 주소는 대소문자를 가리지 않는다")


class BlocksTest(unittest.TestCase):
    """최상위 블록 목록과 이미지의 자리 — 플랫폼 글에서 이미지를 제자리에 놓는 데 쓴다."""

    SOURCE = ("![맨 앞 그림](https://img.example/0.png)\n\n# 제목\n\n첫 문단 ![문단 속](https://img.example/1.png) 이어지는 글\n\n- 목록 하나\n- 목록 둘\n\n"
              "![홀로 선 그림](https://img.example/2.png)\n\n> 인용\n\n끝 문단\n\n![맨 뒤 그림](https://img.example/3.png)")

    def test_blocks_joined_are_the_whole_html_and_each_block_is_one_top_level_element(self):
        blocks, _images = markdown_blocks(self.SOURCE)
        self.assertEqual(blocks, ["<h2>제목</h2>", "<p>첫 문단 이어지는 글</p>", "<ul><li>목록 하나</li><li>목록 둘</li></ul>", "<blockquote><p>인용</p></blockquote>", "<p>끝 문단</p>"])
        self.assertEqual("".join(blocks), markdown_to_html(self.SOURCE))

    def test_each_image_knows_how_many_blocks_come_before_it(self):
        _blocks, images = markdown_blocks(self.SOURCE)
        self.assertEqual(images, [("맨 앞 그림", "https://img.example/0.png", 0), ("문단 속", "https://img.example/1.png", 1), ("홀로 선 그림", "https://img.example/2.png", 3),
                                  ("맨 뒤 그림", "https://img.example/3.png", 5)])
        self.assertEqual([(alt, url) for alt, url, _place in images], markdown_images(self.SOURCE))

    def test_an_image_inside_a_quote_stands_before_the_whole_quote(self):
        blocks, images = markdown_blocks("앞\n\n> 인용 ![속](https://img.example/q.png) 글\n\n뒤")
        self.assertEqual(blocks, ["<p>앞</p>", "<blockquote><p>인용 글</p></blockquote>", "<p>뒤</p>"])
        self.assertEqual(images, [("속", "https://img.example/q.png", 1)])

    def test_blocks_inside_a_quote_do_not_move_the_place_of_the_image_after_it(self):
        blocks, images = markdown_blocks("> 가\n>\n> 나\n\n![그림](https://img.example/a.png)\n\n다")
        self.assertEqual(blocks, ["<blockquote><p>가</p><p>나</p></blockquote>", "<p>다</p>"])
        self.assertEqual(images, [("그림", "https://img.example/a.png", 1)], "인용 안의 문단은 최상위 블록으로 세지 않는다")

    def test_a_paragraph_with_only_pictures_is_not_a_block_at_all(self):
        blocks, images = markdown_blocks("![하나](https://img.example/1.png)\n\n![둘](https://img.example/2.png)\n\n본문")
        self.assertEqual(blocks, ["<p>본문</p>"])
        self.assertEqual(images, [("하나", "https://img.example/1.png", 0), ("둘", "https://img.example/2.png", 0)])

    def test_a_block_the_cleaner_leaves_empty_is_left_out_and_the_places_of_later_images_shift_with_it(self):
        real = md._clean

        def clean(html, allow_links, allowed_hosts):
            return "" if "버릴" in html else real(html, allow_links, allowed_hosts)

        with mock.patch.object(md, "_clean", clean):
            blocks, images = markdown_blocks("앞\n\n버릴 문단\n\n![그림](https://img.example/a.png)\n\n뒤")
        self.assertEqual(blocks, ["<p>앞</p>", "<p>뒤</p>"], "정화하고 나서 빈 블록은 목록에 넣지 않는다")
        self.assertEqual(images, [("그림", "https://img.example/a.png", 1)], "빠진 블록만큼 이미지 자리도 당겨진다")

    def test_nothing_in_nothing_out(self):
        self.assertEqual(markdown_blocks(""), ([], []))
        self.assertEqual(markdown_blocks("![](https://img.example/a.png)"), ([], [("", "https://img.example/a.png", 0)]))

    def test_blocks_always_add_up_to_the_whole_html_for_random_documents(self):
        rng = random.Random(11)
        make = RoundTripTest()
        for _ in range(120):
            source = "\n\n".join(make.block(rng) for _ in range(rng.randint(1, 6)))
            blocks, images = markdown_blocks(source)
            self.assertEqual("".join(blocks), markdown_to_html(source))
            self.assertTrue(all(0 <= place <= len(blocks) for _alt, _url, place in images))
            for block in blocks:
                self.assertEqual(tags_in(block) & {"p", "h2", "h3", "h4", "ul", "ol", "blockquote"} != set(), True, block)

    def test_links_follow_the_same_rules_per_block(self):
        blocks, _images = markdown_blocks("[내 글](https://example.com/a) 와 [밖](https://evil.example/)", allow_links=True, allowed_hosts=("example.com",))
        self.assertEqual(blocks, ['<p><a href="https://example.com/a" rel="nofollow noopener">내 글</a> 와 밖</p>'])


class HtmlToTextTest(unittest.TestCase):
    CASES = (
        ("<p>문단 하나</p><p>문단 둘</p>", "문단 하나\n\n문단 둘\n"),
        ("<h2>제목</h2><p>본문</p>", "제목\n\n본문\n"),
        ("<p><strong>굵게</strong> 와 <em>기울임</em> 와 <b>b</b> <i>i</i></p>", "굵게 와 기울임 와 b i\n"),
        ("<p>줄<br>바꿈</p>", "줄\n바꿈\n"),
        ("<ul><li>하나</li><li>둘<ul><li>하위</li></ul></li></ul>", "- 하나\n- 둘\n  - 하위\n"),
        ("<ol><li>첫째</li><li>둘째</li></ol>", "1. 첫째\n2. 둘째\n"),
        ("<ul>흩어진 항목<li>항목</li></ul>", "- 흩어진 항목\n- 항목\n"),
        ("<ul><li>가<ul>흩어진 글<li>다</li></ul></li></ul>", "- 가\n  - 흩어진 글\n  - 다\n"),
        ("<p>가<br> 나 <br>다</p>", "가\n나\n다\n"),
        ("<blockquote><p>인용</p><p>둘째</p></blockquote>", "> 인용\n>\n> 둘째\n"),
        ("<p>A &amp; B &lt; C * _ # [x]</p>", "A & B < C * _ # [x]\n"),
        ("<p>  공백이 \n  여럿  </p>", "공백이 여럿\n"),
        ("텍스트만", "텍스트만\n"),
        ("<p>앞</p>흩어진 글<p>뒤</p>", "앞\n\n흩어진 글\n\n뒤\n"),
        ("<p></p><ul></ul><blockquote></blockquote>", ""),
        ("", ""),
        ("<li>목록 밖의 항목</li>", "목록 밖의 항목\n"),
        ("<p>안녕 <script>alert(1)</script>하세요</p><iframe src=x></iframe>", "안녕 하세요\n"),
    )

    def test_each_tag_becomes_the_expected_plain_text(self):
        for html, expected in self.CASES:
            with self.subTest(html=html[:40]):
                self.assertEqual(html_to_text(html), expected)

    def test_links_keep_only_their_words(self):
        html = '<p>보세요 <a href="https://example.com/a">여기</a></p>'
        self.assertEqual(html_to_text(html), "보세요 여기\n")
        self.assertEqual(html_to_text(html, allow_links=True, allowed_hosts=("example.com",)), "보세요 여기\n")

    def test_what_comes_from_markdown_reads_naturally(self):
        source = "# 제목\n\n오늘은 **세 가지**만 해 봅니다. *천천히* 하세요.\n\n1. 물 마시기\n2. 스트레칭\n   - 목\n   - 어깨\n\n> 작은 습관\n\n끝  \n안녕"
        self.assertEqual(html_to_text(markdown_to_html(source)), "제목\n\n오늘은 세 가지만 해 봅니다. 천천히 하세요.\n\n1. 물 마시기\n2. 스트레칭\n  - 목\n  - 어깨\n\n> 작은 습관\n\n끝\n안녕\n")

    def test_odd_values_and_big_inputs_are_handled(self):
        for value in (None, 123, b"bytes", ["목록"]):
            self.assertIsInstance(html_to_text(value), str)
        self.assertIn("깊은", html_to_text("<blockquote>" * 3000 + "깊은" + "</blockquote>" * 3000))
        self.assertEqual(html_to_text("<ul>" * 3000 + "<li>x</li>" + "</ul>" * 3000).count("x"), 1)
        with self.assertRaises(AppError):
            html_to_text("a" * (md.MAX_CHARS + 1))


class SafetyTest(unittest.TestCase):
    ATTACKS = (
        "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<a href=\"javascript:alert(1)\">x</a>", "<iframe src=//evil></iframe>", "<style>*{}</style>",
        "<svg onload=alert(1)>", "<b onmouseover=alert(1)>x</b>", "&lt;script&gt;", "<!-- 주석 --><p>x</p>", "<![CDATA[x]]>", "<?php echo 1 ?>",
        "[x](javascript:alert(1))", "[x](JaVaScRiPt:alert(1))", "[x](  javascript:alert(1))", "[x](data:text/html;base64,PHNjcmlwdD4=)", "![x](javascript:alert(1))",
        "[x](https://ok.example/\"onmouseover=\"alert(1))", "<https://ok.example/\"onclick=\"x>", "[\"><script>](https://example.com)", "[x](https://example.com/\"><script>alert(1)</script>)",
        "`<script>`", "```\n<script>alert(1)</script>\n```", "> <script>x</script>", "- <img src=x onerror=alert(1)>", "# <script>x</script>",
        "\ue000999\ue001", "\ue000\ue001\ue000", "\ue010", "a\ue000" + "0" + "\ue001b",
    )

    def test_nothing_outside_the_allowed_tags_ever_comes_out(self):
        allowed = set(ALLOWED_TAGS) | {"a"}
        for attack in self.ATTACKS:
            for links in (False, True):
                with self.subTest(attack=attack[:40], links=links):
                    html = markdown_to_html(attack, allow_links=links)
                    self.assertLessEqual(tags_in(html), allowed, html)
                    for tag, name, value in attributes_in(html):             # 속성은 링크의 href·rel 뿐이고 href 는 https 다(글자로 남은 `javascript:` 는 위험하지 않다)
                        self.assertEqual(tag, "a", html)
                        self.assertIn(name, ("href", "rel"), html)
                        self.assertTrue(name != "href" or value.startswith("https://"), html)
                    self.assertEqual(sanitize_html(html, allow_links=links)[0], html, "정화기를 한 번 더 거쳐도 달라지지 않는다")

    def test_the_internal_marker_characters_in_the_input_cannot_inject_stored_html(self):
        html = markdown_to_html("앞 `코드` 와 \ue000" + "0" + "\ue001 와 \ue010 끝")
        self.assertEqual(html, "<p>앞 코드 와 0 와 끝</p>")

    def test_too_big_an_input_is_a_clean_error_not_a_hang(self):
        with self.assertRaises(AppError) as caught:
            markdown_to_html("a" * (md.MAX_CHARS + 1))
        self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        with self.assertRaises(AppError):
            html_to_markdown("a" * (md.MAX_CHARS + 1))

    def test_html_from_other_blogs_is_cleaned_before_it_becomes_markdown(self):
        self.assertEqual(html_to_markdown("<p>안녕 <script>alert(1)</script><b>굵게</b></p><iframe src=x></iframe>"), "안녕 **굵게**\n")
        self.assertEqual(html_to_markdown("<p onclick=x>속성은 사라진다</p><a href=\"javascript:x\">링크</a>"), "속성은 사라진다\n\n링크\n")


class HtmlToMarkdownTest(unittest.TestCase):
    CASES = (
        ("<p>문단 하나</p><p>문단 둘</p>", "문단 하나\n\n문단 둘\n"),
        ("<h2>제목</h2><h3>둘째</h3><h4>셋째</h4>", "## 제목\n\n### 둘째\n\n#### 셋째\n"),
        ("<p><strong>굵게</strong> <b>굵게</b> <em>기울임</em> <i>기울임</i></p>", "**굵게** **굵게** *기울임* *기울임*\n"),
        ("<p>줄<br>바꿈</p>", "줄  \n바꿈\n"),
        ("<ul><li>하나</li><li>둘<ul><li>하위</li></ul></li></ul>", "- 하나\n- 둘\n    - 하위\n"),
        ("<ol><li>첫째</li><li>둘째</li></ol>", "1. 첫째\n2. 둘째\n"),
        ("<blockquote><p>인용</p><p>둘째</p></blockquote>", "> 인용\n>\n> 둘째\n"),
        ("<p>A &amp; B &lt; C</p>", "A & B \\< C\n"),
        ("<p>별표 * 와 밑줄 _ 와 백틱 ` 와 [대괄호]</p>", "별표 \\* 와 밑줄 \\_ 와 백틱 \\` 와 \\[대괄호\\]\n"),
        ("<p># 샵으로 시작</p>", "\\# 샵으로 시작\n"),
        ("<p>- 대시로 시작</p><p>1. 번호로 시작</p><p>---</p>", "\\- 대시로 시작\n\n1\\. 번호로 시작\n\n\\---\n"),
        ("<p>  공백이 \n  여럿  </p>", "공백이 여럿\n"),
        ("텍스트만", "텍스트만\n"),
        ("<p>앞</p>흩어진 글<p>뒤</p>", "앞\n\n흩어진 글\n\n뒤\n"),
        ("<p></p><ul></ul><blockquote></blockquote>", ""),
        ("", ""),
        ("<li>목록 밖의 항목</li>", "목록 밖의 항목\n"),
        ("<p>&gt; 인용처럼 보이는 글 a\\b</p>", "\\> 인용처럼 보이는 글 a\\\\b\n"),
        ("<p>+ 더하기로 시작</p>", "\\+ 더하기로 시작\n"),
        ("<p>1) 괄호 번호로 시작</p>", "1\\) 괄호 번호로 시작\n"),
        ("<p><strong> <em>x</em> </strong></p>", "**_x_**\n"),
        ("<p>앞<strong></strong>뒤</p>", "앞뒤\n"),
        ("<p><strong><em>둘 다</em></strong></p>", "**_둘 다_**\n"),
        ("<p><em><strong>둘 다</strong></em></p>", "***둘 다***\n"),
        ("<p><em>가 <em>나</em> 다</em> <strong>라 <b>마</b></strong></p>", "*가 나 다* **라 마**\n"),
        ("<ul>흩어진 항목<li>항목</li></ul><ol>흩어진 번호<li>번호</li></ol>", "- 흩어진 항목\n- 항목\n\n1. 흩어진 번호\n2. 번호\n"),
    )

    def test_each_tag_becomes_the_expected_markdown(self):
        for html, expected in self.CASES:
            with self.subTest(html=html[:40]):
                self.assertEqual(html_to_markdown(html), expected)

    def test_links_are_kept_only_when_allowed(self):
        html = '<p>보세요 <a href="https://example.com/a">여기</a> 와 <a href="http://insecure.example">저기</a></p>'
        self.assertEqual(html_to_markdown(html), "보세요 여기 와 저기\n")
        self.assertEqual(html_to_markdown(html, allow_links=True, allowed_hosts=("example.com",)), "보세요 [여기](https://example.com/a) 와 저기\n")

    def test_what_comes_out_of_the_converter_is_stable_when_converted_back_and_forth(self):
        for html, _ in self.CASES:
            with self.subTest(html=html[:40]):
                second = markdown_to_html(html_to_markdown(html))
                third = markdown_to_html(html_to_markdown(second))
                self.assertEqual(second, third)


class RoundTripTest(unittest.TestCase):
    """Markdown → HTML → Markdown → HTML 이 처음 HTML 과 같다(되돌려 쓰고 다시 읽어도 글이 변하지 않는다)."""

    WORDS = ("가나다", "라마바", "hello", "world", "snake_case", "2026", "*별*", "_밑_", "a&b", "x<y", "[대괄호]", "(소괄호)", "#샵", "1.5", "-하이픈", "`틱`", "\\역슬래시", "!느낌표", "http://x.y")

    def sentence(self, rng):
        parts = []
        for _ in range(rng.randint(1, 6)):
            word = rng.choice(self.WORDS)
            parts.append({0: word, 1: f"**{word}**", 2: f"*{word}*", 3: word, 4: word}[rng.randint(0, 4)])
        return " ".join(parts)

    def block(self, rng, depth=0):
        kind = rng.choice(("p", "p", "h", "ul", "ol", "quote", "br"))
        if kind == "h":
            return "#" * rng.randint(1, 4) + " " + self.sentence(rng)
        if kind in ("ul", "ol") and depth < 3:
            lines = []
            for index in range(rng.randint(1, 4)):
                marker = "- " if kind == "ul" else f"{index + 1}. "
                lines.append(marker + self.sentence(rng))
                if rng.random() < 0.3 and depth < 2:
                    lines.extend(("    " + row) for row in self.block(rng, depth + 1).split("\n") if row.strip() and row.lstrip()[:2] in ("- ", "1"))
            return "\n".join(lines)
        if kind == "quote" and depth < 2:
            return "\n".join("> " + row if row else ">" for row in self.block(rng, depth + 1).split("\n"))
        if kind == "br":
            return self.sentence(rng) + "  \n" + self.sentence(rng)
        return self.sentence(rng)

    def test_random_documents_survive_the_trip(self):
        rng = random.Random(20261030)
        failures = []
        for number in range(250):
            source = "\n\n".join(self.block(rng) for _ in range(rng.randint(1, 5)))
            first = markdown_to_html(source)
            back = html_to_markdown(first)
            second = markdown_to_html(back)
            if first != second:
                failures.append((source, first, back, second))
        self.assertEqual(failures[:2], [], f"{len(failures)}개 문서가 되돌려 쓰면 달라진다")

    def test_a_realistic_post_survives_the_trip(self):
        source = ("# 아침 루틴으로 몸 깨우기\n\n오늘은 **세 가지**만 해 봅니다. *천천히* 하세요.\n\n## 1단계\n\n1. 물 한 컵 마시기\n2. 가볍게 스트레칭\n   - 목\n   - 어깨\n3. 창문 열기\n\n"
                  "> 작은 습관이 모입니다.\n\n## 마무리\n\n- 무리하지 않기\n- 꾸준히 하기\n\n끝까지 읽어 주셔서 감사합니다.  \n내일 또 만나요.\n")
        first = markdown_to_html(source)
        self.assertEqual(markdown_to_html(html_to_markdown(first)), first)
        self.assertEqual(html_to_markdown(first), html_to_markdown(markdown_to_html(html_to_markdown(first))))


class RobustnessTest(unittest.TestCase):
    ALPHABET = list("*_`[]()<>#-+1.2!\\&\"' \t\n") + ["**", "__", "```", "~~~", "![", "](", "> ", "- ", "1. ", "  \n", "\\\n", "한", "글", "\ue000", "\u200b", "&amp;", "&#x3C;", "<b>", "</b>", "<script>", "javascript:", "https://a.b/"]

    def test_random_input_never_raises_and_only_gives_allowed_tags(self):
        rng = random.Random(7)
        allowed = set(ALLOWED_TAGS) | {"a"}
        for _ in range(400):
            text = "".join(rng.choice(self.ALPHABET) for _ in range(rng.randint(0, 120)))
            for links in (False, True):
                html = markdown_to_html(text, allow_links=links)
                self.assertLessEqual(tags_in(html), allowed, repr(text))
                self.assertEqual(sanitize_html(html, allow_links=links)[0], html, repr(text))
            back = html_to_markdown(markdown_to_html(text))
            self.assertIsInstance(back, str)
            markdown_images(text)

    def test_odd_values_are_handled(self):
        for value in (None, 123, 0, b"bytes", ["목록"], "", " ", "\n" * 50):
            with self.subTest(value=repr(value)):
                self.assertIsInstance(markdown_to_html(value), str)
                self.assertIsInstance(html_to_markdown(value), str)

    def test_the_worst_inputs_finish_quickly(self):
        nasty = ("*a " * 2500, "`a" * 4000, "[a](" * 2000, "_a " * 2500, "**a " * 2000, "![" * 3000, "<" * 8000, "> " * 3000 + "x", "- " * 3000, "1. " * 2000 + "x",
                 "    " * 1500 + "- x", "- a\n" + "  - b\n" * 5000, ("> " * 30 + "깊은 인용\n") * 100, "# " * 4000, "\\" * 20000, "a\n" * 100000, "*" * 20000, "`" * 20000)
        started = time.time()
        for text in nasty:
            begin = time.time()
            markdown_to_html(text)
            html_to_markdown(text)
            self.assertLess(time.time() - begin, 5, repr(text[:30]))
        self.assertLess(time.time() - started, 30)

    def test_very_deep_nesting_is_cut_off_instead_of_blowing_the_stack(self):
        deep = markdown_to_html("> " * 3000 + "깊은 인용")
        self.assertIn("깊은", deep)
        self.assertEqual(deep.count("<blockquote>"), md.MAX_DEPTH + 1, "인용은 정해진 깊이까지만 중첩하고 나머지는 글로 둔다")
        lines = "\n".join("  " * level + "- 단계" for level in range(300))
        html = markdown_to_html(lines)
        self.assertLessEqual(html.count("<ul>"), md.MAX_LIST_DEPTH)
        self.assertEqual(html.count("단계"), 300, "깊이를 잘라도 글은 하나도 잃지 않는다")
        self.assertEqual(html_to_markdown("<ul>" * 200 + "<li>x</li>" + "</ul>" * 200).count("x"), 1)
        self.assertIn("깊은", html_to_markdown("<blockquote>" * 3000 + "깊은" + "</blockquote>" * 3000))
        self.assertEqual(html_to_markdown("<ul>" * 3000 + "<li>x</li>" + "</ul>" * 3000).count("x"), 1)

    def test_a_paragraph_exactly_at_the_limit_is_still_converted_but_one_more_character_is_not(self):
        head = "**굵게** "
        exact = head + "가" * (md.INLINE_LIMIT - len(head))
        self.assertEqual(len(exact), md.INLINE_LIMIT)
        self.assertIn("<strong>굵게</strong>", markdown_to_html(exact))
        self.assertNotIn("<strong>", markdown_to_html(exact + "가"))

    def test_a_long_paragraph_is_kept_as_plain_text(self):
        long = "굵게 **강조** 와 " * 1500
        self.assertGreater(len(long), md.INLINE_LIMIT)
        html = markdown_to_html(long)
        self.assertIn("**강조**", html)
        self.assertNotIn("<strong>", html)


if __name__ == "__main__":
    unittest.main()
