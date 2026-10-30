"""네이버 발행 패키지 시험 — 원고 하나가 한 블로그(프로필)에 맞는 복사 패키지(제목·본문·태그·이미지 자리·체크리스트)가 되고, 점검이 규칙대로 알린다.

지키는 것:
  1) 제목은 한 줄로 정리하고 상한을 넘으면 줄이며, 제목·본문·태그가 비면 NAVER_PACKAGE_INCOMPLETE, 프로필·이미지 자료의 모양이 틀리면 CONTENT_INVALID 로 거절한다.
  2) 긴 문단은 문장 끝에서 나뉘고(굵게·링크가 열린 곳·줄바꿈 문단은 나누지 않으며 글을 자르지도 않는다), 이미지는 정해진 자리에 번호 붙은 표시로 놓이고, 고지문은 글 끝에 한 번만 붙는다.
  3) 태그는 기본 태그가 먼저이고 `#`·공백·중복을 정리해 상한까지만 남는다. 금지 표현·글 길이·카테고리 매핑 없음은 warnings 로 알린다.
  4) 파일 이름·설명·주소·제목 속 HTML 은 글자로만 나온다(표시·미리보기 모두 허용 태그 밖의 것이 없다).
  5) 어떤 입력에도 죽지 않고 빨리 끝난다. 네트워크·파일 없이 돈다.
"""
import html as html_lib
import random
import re
import sys
import time
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import Asset  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.render import naver  # noqa: E402
from chanceblog_desktop.render.naver import NaverImage, NaverPackage, build_package  # noqa: E402
from pipeline.gates import ALLOWED_TAGS  # noqa: E402  (render 이 vendor/ 경로를 올려 둔다)

LONG_ENOUGH = {"min_chars": 0}


def profile(**changes):
    values = {"key": "naver_a", "display_name": "블로그 A", "blog_url": "https://blog.naver.com/example_a", "default_tags": ("아침",), **LONG_ENOUGH}
    values.update(changes)
    return NaverProfile(**values)


def build(body="첫 문단입니다.", *, title="제목", prof=None, **kwargs):
    return build_package(prof or profile(), title=title, body=body, **kwargs)


def tags_in(html):
    found = set()

    class Reader(HTMLParser):
        def handle_starttag(self, tag, attrs):
            found.add(tag)

    Reader(convert_charrefs=True).feed(html)
    return found


def refuses(test, code, *args, **kwargs):
    with test.assertRaises(AppError) as caught:
        build_package(*args, **kwargs)
    test.assertEqual(caught.exception.code, code, caught.exception.detail)
    return caught.exception


class IncompleteInputTest(unittest.TestCase):
    def test_a_missing_title_body_or_tags_is_an_incomplete_package_naming_the_item(self):
        for kwargs, item in (({"title": "", "body": "본문"}, "제목"), ({"title": "   ", "body": "본문"}, "제목"), ({"title": None, "body": "본문"}, "제목"), ({"title": 5, "body": "본문"}, "제목"),
                             ({"title": "제목", "body": ""}, "본문"), ({"title": "제목", "body": "  \n "}, "본문"), ({"title": "제목", "body": None}, "본문"), ({"title": "제목", "body": ["본문"]}, "본문"),
                             ({"title": "제목", "body": "# \n\n#"}, "본문"), ({"title": "제목", "body": "![](https://img.example/a.png)"}, "본문")):
            with self.subTest(kwargs=str(kwargs)[:40]):
                error = refuses(self, "NAVER_PACKAGE_INCOMPLETE", profile(), **kwargs)
                self.assertEqual(error.slots["항목"], item)
                self.assertIn(item, error.rendered().message)
        error = refuses(self, "NAVER_PACKAGE_INCOMPLETE", profile(default_tags=()), title="제목", body="본문")
        self.assertEqual(error.slots["항목"], "태그")
        error = refuses(self, "NAVER_PACKAGE_INCOMPLETE", profile(default_tags=()), title="제목", body="본문", tags=["", "#", "  ", None, "가" * 31])
        self.assertEqual(error.slots["항목"], "태그")

    def test_the_title_is_checked_before_the_body(self):
        self.assertEqual(refuses(self, "NAVER_PACKAGE_INCOMPLETE", profile(), title="", body="").slots["항목"], "제목")

    def test_something_that_is_not_a_profile_or_not_images_is_invalid_content(self):
        for bad in (None, {"key": "naver_a"}, "naver_a", 5):
            with self.subTest(bad=str(bad)[:20]):
                refuses(self, "CONTENT_INVALID", bad, title="제목", body="본문")
        for assets in ("", b"", "a.png", b"a.png", [{"filename": "a.png"}], [Asset("a.png"), "b.png"], [5], 5):
            with self.subTest(assets=str(assets)[:30]):
                refuses(self, "CONTENT_INVALID", profile(), title="제목", body="본문", assets=assets)
        refuses(self, "CONTENT_INVALID", profile(), title="제목", body="본문", assets=[Asset(f"{index}.png") for index in range(naver.MAX_IMAGES + 1)])
        self.assertEqual(len(build(assets=[Asset(f"{index}.png") for index in range(naver.MAX_IMAGES)]).images), naver.MAX_IMAGES)


class TitleTest(unittest.TestCase):
    def test_the_title_becomes_one_clean_line(self):
        self.assertEqual(build(title="  앞 \n 뒤\u200b 제목 \t ").title, "앞 뒤 제목")
        self.assertEqual(build(title="<b>태그</b> & 글").title, "<b>태그</b> & 글", "제목은 글자 그대로(화면이 알아서 이스케이프한다)")

    def test_a_title_over_the_limit_is_shortened_with_an_ellipsis_and_a_warning(self):
        prof = profile(max_title_chars=10)
        exact = build(title="가" * 10, prof=prof)
        self.assertEqual((exact.title, [w for w in exact.warnings if "제목" in w]), ("가" * 10, []))
        cut = build(title="가나다라마바사아자차카", prof=prof)
        self.assertEqual(cut.title, "가나다라마바사아자…")
        self.assertEqual(len(cut.title), 10)
        self.assertTrue(any("제목이 11자라 10자로 줄였습니다" in warning for warning in cut.warnings), cut.warnings)

    def test_trailing_spaces_before_the_ellipsis_are_dropped(self):
        cut = build(title="가나다라마 바사아자차카", prof=profile(max_title_chars=7))
        self.assertEqual(cut.title, "가나다라마…")


class TagTest(unittest.TestCase):
    def test_the_blogs_default_tags_come_first_then_the_posts_tags_without_duplicates(self):
        package = build(prof=profile(default_tags=("아침", "루틴")), tags=["건강", "#운동 하기", "루틴", "ARTICLE", "article", "아침"])
        self.assertEqual(package.tags, ("아침", "루틴", "건강", "운동하기", "ARTICLE"))
        self.assertEqual(package.tags_text, "#아침 #루틴 #건강 #운동하기 #ARTICLE")
        self.assertEqual([w for w in package.warnings if "태그" in w], [])

    def test_tags_are_cleaned_of_hashes_spaces_and_edge_punctuation(self):
        package = build(prof=profile(default_tags=()), tags=["##두 단어", " 쉼표, ", "세미;", "#", "  ", "\u200b", "한 글 자"])
        self.assertEqual(package.tags, ("두단어", "쉼표", "세미", "한글자"))

    def test_a_tag_made_only_of_hashes_or_spaces_is_dropped_without_a_warning(self):
        package = build(prof=profile(default_tags=("정상",)), tags=["#", "##", " # ", "  "])
        self.assertEqual(package.tags, ("정상",))
        self.assertEqual([w for w in package.warnings if "쓸 수 없는 태그" in w], [], "빈 태그는 조용히 뺀다")

    def test_a_tag_that_is_too_long_or_not_text_is_dropped_with_one_warning(self):
        package = build(prof=profile(default_tags=("정상",)), tags=["가" * 31, "나" * 30, 5, None, "다" * 40])
        self.assertEqual(package.tags, ("정상", "나" * 30))
        self.assertEqual([w for w in package.warnings if "쓸 수 없는 태그" in w], ["쓸 수 없는 태그 2개를 뺐습니다(길이는 30자 이하여야 합니다)."])

    def test_tags_over_the_limit_are_cut_to_the_first_ones_with_a_warning(self):
        package = build(prof=profile(default_tags=("가", "나"), max_tags=3), tags=["다", "라", "마"])
        self.assertEqual(package.tags, ("가", "나", "다"))
        self.assertTrue(any("태그가 5개라 앞의 3개만 남겼습니다" in warning for warning in package.warnings))
        exact = build(prof=profile(default_tags=("가", "나"), max_tags=3), tags=["다"])
        self.assertEqual(exact.tags, ("가", "나", "다"))
        self.assertEqual([w for w in exact.warnings if "태그" in w], [])

    def test_tags_given_as_a_text_or_other_odd_values_do_not_crash(self):
        self.assertEqual(build(tags=()).tags, ("아침",))
        self.assertEqual(build(tags=[]).tags, ("아침",))
        with self.assertRaises(TypeError):
            build(tags=5)


class ParagraphSplitTest(unittest.TestCase):
    def split(self, text, limit):
        return naver._split_paragraph(html_lib.escape(text, quote=False), limit)

    def test_a_short_paragraph_is_left_alone(self):
        self.assertEqual(self.split("짧은 문단입니다.", 100), ["짧은 문단입니다."])
        self.assertEqual(self.split("가" * 100, 100), ["가" * 100], "상한과 같은 길이는 나누지 않는다")

    def test_a_paragraph_exactly_at_the_limit_comes_back_untouched_even_with_odd_spacing(self):
        text = "가나다.  라마바."                                 # 공백이 둘 — 나눴다 다시 이으면 한 칸이 된다
        self.assertEqual(self.split(text, len(text)), [text])
        self.assertEqual(self.split(text, len(text) - 1), ["가나다. 라마바."], "한 자 줄이면 나뉘고(한 칸으로 이어 붙어 상한 안에 든다)")
        self.assertEqual(self.split(text, len(text) - 2), ["가나다.", "라마바."])

    def test_splitting_goes_on_after_a_bold_part_is_closed(self):
        inner = "<strong>굵은 시작 문장입니다.</strong> 둘째 문장은 이렇습니다. 셋째 문장도 그렇습니다."
        self.assertEqual(naver._split_paragraph(inner, 20), ["<strong>굵은 시작 문장입니다.</strong> 둘째 문장은 이렇습니다.", "셋째 문장도 그렇습니다."])

    def test_a_text_of_only_spaces_comes_back_whole(self):
        self.assertEqual(naver._split_paragraph(" " * 100, 40), [" " * 100])

    def test_a_long_paragraph_is_split_at_sentence_ends_into_pieces_within_the_limit(self):
        sentences = ["첫째 문장은 이렇습니다.", "둘째 문장은 이렇습니다.", "셋째 문장은 이렇습니다!", "넷째 문장은 이렇습니다?", "다섯째 문장은 이렇습니다."]
        pieces = self.split(" ".join(sentences), 28)
        self.assertEqual(pieces, ["첫째 문장은 이렇습니다. 둘째 문장은 이렇습니다.", "셋째 문장은 이렇습니다! 넷째 문장은 이렇습니다?", "다섯째 문장은 이렇습니다."])
        self.assertTrue(all(len(piece) <= 28 for piece in pieces), pieces)
        self.assertEqual(" ".join(pieces), " ".join(sentences), "글자는 하나도 잃지 않는다")

    def test_pieces_are_filled_up_to_the_limit_not_one_sentence_each(self):
        text = " ".join(["가나다라마."] * 6)
        pieces = self.split(text, 20)
        self.assertEqual(pieces, ["가나다라마. 가나다라마. 가나다라마."] * 2)
        self.assertEqual([len(piece) for piece in pieces], [20, 20], "문장 셋이 20자 안에 최대한 들어간다(한 문장씩 나누지 않는다)")
        self.assertEqual(self.split(text, 19), ["가나다라마. 가나다라마."] * 3, "한 자 줄이면 두 문장씩")

    def test_one_sentence_longer_than_the_limit_stays_whole(self):
        long = "가" * 50 + "."
        self.assertEqual(self.split(long + " 짧은 문장.", 20), [long, "짧은 문장."])

    def test_the_end_marks_are_dots_question_exclamation_and_ellipsis_with_closing_quotes(self):
        for end in (".", "?", "!", "…", "...", '."', ".'", ".”", ".)", "?!", '.")'):
            with self.subTest(end=end):
                pieces = self.split(f"가나다라마바사{end} 아자차카타파하{end} 끝", 12)
                self.assertGreaterEqual(len(pieces), 2, pieces)
                self.assertTrue(pieces[0].endswith(end), pieces)
                self.assertEqual(" ".join(pieces), f"가나다라마바사{end} 아자차카타파하{end} 끝")

    def test_a_dot_inside_a_number_or_without_a_space_after_it_is_not_a_sentence_end(self):
        text = "가격은 3.5배이고 주소는 a.b.c 입니다 그리고 끝납니다"
        self.assertEqual(self.split(text, 10), [text])

    def test_a_paragraph_with_a_hard_line_break_is_never_split(self):
        inner = "첫 줄입니다. 둘째 문장입니다.<br>둘째 줄입니다. 셋째 문장입니다."
        self.assertEqual(naver._split_paragraph(inner, 10), [inner])

    def test_bold_italic_and_links_are_never_cut_in_the_middle(self):
        inner = "앞 문장입니다. <strong>굵은 글 안의 문장입니다. 이어지는 굵은 글입니다.</strong> 뒤 문장입니다."
        pieces = naver._split_paragraph(inner, 20)
        self.assertEqual(" ".join(pieces), inner)
        for piece in pieces:
            self.assertEqual(piece.count("<strong>"), piece.count("</strong>"), piece)
        self.assertEqual(naver._split_paragraph("<a href=\"https://example.com/a\">링크 글입니다. 이어집니다.</a> 끝문장입니다.", 12)[0][:2], "<a")
        pieces = naver._split_paragraph("<em>기울임 안의 문장입니다. 둘째입니다.</em> 끝문장입니다. 마지막입니다.", 14)
        for piece in pieces:
            self.assertEqual(piece.count("<em>"), piece.count("</em>"), piece)

    def test_the_visible_length_ignores_tags_and_counts_entities_as_one_character(self):
        self.assertEqual(naver._visible_length("<strong>가나</strong>다"), 3)
        self.assertEqual(naver._visible_length("a &amp; b &lt; c"), 9)
        self.assertEqual(naver._visible_length(""), 0)

    def test_inside_a_package_long_paragraphs_become_short_ones_and_other_blocks_stay(self):
        body = "# 제목\n\n" + " ".join(["문장입니다 이렇게 길게 이어집니다."] * 6) + "\n\n- 목록 하나\n- 목록 둘\n\n> 인용 문단"
        package = build(body, prof=profile(paragraph_max_chars=60))
        self.assertGreater(package.body_html.count("<p>"), 2)
        self.assertEqual(package.body_html.count("<h2>"), 1)
        self.assertEqual(package.body_html.count("<ul>"), 1)
        self.assertEqual(package.body_html.count("<blockquote>"), 1)
        for paragraph in re.findall(r"<p>(.*?)</p>", package.body_html):
            self.assertLessEqual(naver._visible_length(paragraph), 60 if "AI" not in paragraph else 999, paragraph)
        self.assertEqual(package.core_text.replace("\n\n", " ").count("문장입니다 이렇게 길게 이어집니다."), 6, "글자는 하나도 잃지 않는다")

    def test_a_package_never_loses_a_word_when_it_splits(self):
        rng = random.Random(5)
        words = ["가나다", "라마", "바사아자", "차카", "타파하", "hello", "world", "3.5", "a.b"]
        for _ in range(60):
            sentences = [" ".join(rng.choice(words) for _ in range(rng.randint(2, 9))) + rng.choice([".", "!", "?", "…", ""]) for _ in range(rng.randint(1, 8))]
            text = " ".join(sentences)
            pieces = self.split(text, rng.randint(10, 60))
            self.assertEqual(" ".join(pieces).split(), text.split(), text)
            self.assertTrue(all(piece.strip() for piece in pieces))


class ImageTest(unittest.TestCase):
    BODY = "첫 문단\n\n둘째 문단\n\n셋째 문단"

    def positions(self, package):
        """미리보기 HTML 에서 문단과 이미지 표시의 순서(문단은 '문단', 표시는 '표시N'). 끝의 고지문은 뺀다."""
        found = []
        for text in re.findall(r"<p>(.*?)</p>", package.body_html):
            if text.startswith("이 글은 AI 도구"):
                continue
            match = re.match(r"\[이미지 (\d+)\]", text)
            found.append("표시" + match.group(1) if match else "문단")
        return found

    def test_images_are_placed_before_the_block_their_position_counts_from_and_numbered_in_order(self):
        package = build(self.BODY, assets=[Asset("a.png", "가 그림", 0), Asset("b.png", "나 그림", 1), Asset("c.png", "다 그림", 3)])
        self.assertEqual(self.positions(package), ["표시1", "문단", "표시2", "문단", "문단", "표시3"])
        self.assertEqual([(image.number, image.filename, image.alt, image.position) for image in package.images], [(1, "a.png", "가 그림", 0), (2, "b.png", "나 그림", 1), (3, "c.png", "다 그림", 3)])
        self.assertTrue(all(isinstance(image, NaverImage) for image in package.images))
        self.assertIn("[이미지 1] 파일 a.png — 가 그림", package.body_text)

    def test_assets_given_out_of_order_are_numbered_by_their_place(self):
        package = build(self.BODY, assets=[Asset("late.png", "늦은", 2), Asset("early.png", "이른", 0)])
        self.assertEqual([image.filename for image in package.images], ["early.png", "late.png"])
        self.assertEqual([image.number for image in package.images], [1, 2])

    def test_pictures_written_in_the_text_keep_their_place_and_come_after_an_asset_at_the_same_place(self):
        body = "첫 문단\n\n![본문 그림](https://img.example/a.png)\n\n둘째 문단"
        package = build(body, assets=[Asset("z.png", "파일 그림", 1)])
        self.assertEqual(self.positions(package), ["문단", "표시1", "표시2", "문단"])
        self.assertEqual([(image.filename, image.url) for image in package.images], [("z.png", ""), ("", "https://img.example/a.png")])
        self.assertIn("[이미지 2] 주소 https://img.example/a.png — 본문 그림", package.body_text)

    def test_an_image_past_the_end_goes_to_the_end_with_a_warning(self):
        package = build(self.BODY, assets=[Asset("far.png", "먼 그림", 99)])
        self.assertEqual(self.positions(package), ["문단", "문단", "문단", "표시1"])
        self.assertEqual(package.images[0].position, 3)
        self.assertTrue(any("far.png" in warning and "맨 뒤로 옮겼습니다" in warning for warning in package.warnings), package.warnings)
        exact = build(self.BODY, assets=[Asset("end.png", "끝 그림", 3)])
        self.assertEqual([w for w in exact.warnings if "맨 뒤" in w], [])

    def test_a_picture_in_the_text_that_is_not_https_is_dropped_with_a_warning(self):
        for url in ("http://img.example/a.png", "javascript:alert(1)", "data:image/png;base64,AAAA", "ftp://x/a.png", "//img.example/a.png"):
            with self.subTest(url=url):
                package = build(f"앞\n\n![그림]({url})\n\n뒤")
                self.assertEqual(package.images, ())
                self.assertNotIn(url, package.body_html)
                self.assertTrue(any("https 가 아니라 뺐습니다" in warning for warning in package.warnings), package.warnings)

    def test_an_image_without_a_description_is_named_by_its_file_and_warned_about(self):
        package = build(self.BODY, assets=[Asset("noalt.png", "", 0)])
        self.assertEqual(package.images[0].label, "noalt.png")
        self.assertTrue(any("이미지 1번(「noalt.png」)에 설명이 없습니다" in warning for warning in package.warnings), package.warnings)
        self.assertEqual([w for w in build(self.BODY, assets=[Asset("a.png", "설명 있음", 0)]).warnings if "설명이 없습니다" in w], [])

    def test_the_label_is_short_and_single_line(self):
        package = build(self.BODY, assets=[Asset("a.png", "아주 긴 설명 " * 30, 0)])
        self.assertLessEqual(len(package.images[0].label), naver.LABEL_CHARS)
        self.assertTrue(package.images[0].label.endswith("…"))

    def test_file_names_and_descriptions_with_html_stay_text_in_both_outputs(self):
        evil = Asset('x"><b onmouseover=alert(1)>&.png', "<img src=x onerror=alert(1)> & 설명", 0)
        package = build(self.BODY, assets=[evil])
        self.assertNotIn("<b ", package.body_html)
        self.assertNotIn("<img", package.body_html)
        self.assertIn("&lt;b onmouseover=alert(1)&gt;&amp;.png", package.body_html)
        self.assertIn('x"><b onmouseover=alert(1)>&.png', package.body_text, "평문에는 글자 그대로")
        self.assertLessEqual(tags_in(package.body_html), set(ALLOWED_TAGS))

    def test_no_images_means_no_image_step_in_the_checklist(self):
        self.assertFalse(any("이미지" in line for line in build(self.BODY).checklist if "AI 활용" not in line))


class DisclosureTest(unittest.TestCase):
    def test_the_disclosure_is_added_once_at_the_end_when_the_post_is_ai_assisted(self):
        package = build("본문 하나\n\n본문 둘")
        self.assertTrue(package.body_text.rstrip().endswith("이 글은 AI 도구의 도움을 받아 초안을 만들고, 사람이 읽고 고쳐서 올렸습니다."))
        self.assertEqual(package.body_text.count("AI 도구의 도움"), 1)
        custom = build("본문", prof=profile(disclosure="AI 의 도움을 받았습니다 <b>&</b>"))
        self.assertIn("AI 의 도움을 받았습니다 &lt;b&gt;&amp;&lt;/b&gt;", custom.body_html)
        self.assertNotIn("<b>", custom.body_html)
        self.assertTrue(custom.body_text.rstrip().endswith("AI 의 도움을 받았습니다 <b>&</b>"))

    def test_it_is_left_out_when_the_post_is_not_ai_assisted_and_not_repeated_when_already_there(self):
        self.assertNotIn("AI 도구", build("본문", ai_assisted=False).body_text)
        self.assertNotIn("AI 활용 고지문을 확인", " ".join(build("본문", ai_assisted=False).checklist))
        already = build("본문\n\n이 글은 AI 도구의 도움을 받아 초안을 만들고, 사람이 읽고 고쳐서 올렸습니다.")
        self.assertEqual(already.body_text.count("AI 도구의 도움"), 1)

    def test_the_disclosure_is_not_part_of_the_compared_text_or_the_counts(self):
        package = build("본문 한 줄")
        self.assertNotIn("AI", package.core_text)
        self.assertEqual(package.chars, len("본문한줄"))
        self.assertEqual(package.paragraphs, 1)


class WarningTest(unittest.TestCase):
    def test_forbidden_phrases_are_found_in_the_title_and_the_body_ignoring_case(self):
        prof = profile(forbidden_phrases=("무조건", "Click Here"))
        package = build("이렇게 하면 무조건 됩니다. click here 를 누르세요", title="무조건 따라 하세요", prof=prof)
        self.assertIn("금지 표현 「무조건」 이(가) 제목에 있습니다.", package.warnings)
        self.assertIn("금지 표현 「무조건」 이(가) 본문에 있습니다.", package.warnings)
        self.assertIn("금지 표현 「Click Here」 이(가) 본문에 있습니다.", package.warnings)
        self.assertNotIn("금지 표현 「Click Here」 이(가) 제목에 있습니다.", package.warnings)
        self.assertEqual([w for w in build("깨끗한 본문", prof=prof).warnings if "금지" in w], [])

    def test_a_forbidden_phrase_only_in_the_disclosure_or_an_image_marker_is_not_reported(self):
        prof = profile(forbidden_phrases=("AI 도구", "첨부"), disclosure="AI 도구를 썼습니다")
        package = build("깨끗한 본문", prof=prof, assets=[Asset("첨부.png", "첨부 그림", 0)])
        self.assertEqual([w for w in package.warnings if "금지" in w], [])

    def test_a_body_shorter_or_longer_than_the_blogs_range_is_warned_about_with_the_count(self):
        prof = profile(min_chars=10, max_chars=20)
        short = build("가나다", prof=prof)
        self.assertEqual(short.chars, 3)
        self.assertIn("본문이 3자로 이 블로그 기준(10~20자)보다 짧습니다.", short.warnings)
        exact_low, exact_high = build("가" * 10, prof=prof), build("가" * 20, prof=prof)
        self.assertEqual([w for w in exact_low.warnings + exact_high.warnings if "기준" in w], [])
        self.assertIn("본문이 21자로 이 블로그 기준(10~20자)보다 깁니다.", build("가" * 21, prof=prof).warnings)

    def test_spaces_do_not_count_as_characters(self):
        self.assertEqual(build("가 나 다\n\n라 마").chars, 5)

    def test_a_category_without_a_mapping_is_warned_about_and_a_mapped_one_is_used(self):
        prof = profile(categories={"건강": "생활 건강"})
        package = build("본문", prof=prof, category="건강")
        self.assertEqual(package.category, "생활 건강")
        self.assertEqual([w for w in package.warnings if "카테고리" in w], [])
        self.assertTrue(any("카테고리" in w and "여행" in w for w in build("본문", prof=prof, category="여행").warnings))
        none_given = build("본문", prof=prof)
        self.assertEqual((none_given.category, [w for w in none_given.warnings if "카테고리" in w]), ("", []))
        self.assertIn("생활 건강", " ".join(package.checklist))
        self.assertNotIn("카테고리 「", " ".join(none_given.checklist))


class BodyTest(unittest.TestCase):
    def test_markdown_becomes_the_allowed_html_and_the_plain_text(self):
        package = build("# 제목\n\n**굵게** 와 *기울임* 과 [링크](https://example.com/a)\n\n1. 하나\n2. 둘\n\n> 인용", prof=profile(paragraph_max_chars=2000))
        self.assertEqual(package.body_html.split("<p>이 글은")[0],
                         "<h2>제목</h2><p><strong>굵게</strong> 와 <em>기울임</em> 과 링크</p><ol><li>하나</li><li>둘</li></ol><blockquote><p>인용</p></blockquote>")
        self.assertIn("1. 하나\n2. 둘", package.body_text)
        self.assertIn("> 인용", package.body_text)
        self.assertNotIn("**", package.body_text)

    def test_html_in_the_manuscript_is_shown_as_text_never_run(self):
        package = build("<script>alert(1)</script> 와 <img src=x onerror=alert(1)> 와 [x](javascript:alert(1))")
        self.assertLessEqual(tags_in(package.body_html), set(ALLOWED_TAGS))
        self.assertNotIn("<script", package.body_html)
        self.assertIn("&lt;script&gt;", package.body_html)
        self.assertNotIn("javascript:", package.body_html.replace("[x](javascript:alert(1))", ""))

    def test_counts_and_first_paragraph(self):
        package = build("# 제목\n\n첫 문단입니다.\n\n둘째 문단입니다.\n\n- 목록", prof=profile(paragraph_max_chars=2000))
        self.assertEqual(package.paragraphs, 2, "제목·목록은 문단 수에 넣지 않는다")
        self.assertEqual(package.intro, "첫 문단입니다.", "도입부는 제목·목록이 아니라 첫 문단이다")
        self.assertEqual(build("# 제목만\n\n- 목록만").intro, "", "문단이 없으면 도입부도 없다")

    def test_the_package_is_a_value_that_cannot_be_changed(self):
        package = build("본문")
        with self.assertRaises(Exception):
            package.title = "다른 제목"
        self.assertEqual(package, build("본문"))
        self.assertIsInstance(package.tags, tuple)
        self.assertIsInstance(package.warnings, tuple)
        self.assertIsInstance(package.checklist, tuple)

    def test_two_blogs_make_their_own_packages_from_the_same_manuscript(self):
        a = build_package(profile(display_name="블로그 A", default_tags=("에이",)), title="같은 제목", body="같은 본문입니다.")
        b = build_package(profile(key="naver_b", display_name="블로그 B", default_tags=("비",), blog_url="https://blog.naver.com/example_b"), title="같은 제목", body="같은 본문입니다.")
        self.assertEqual((a.profile_key, b.profile_key), ("naver_a", "naver_b"))
        self.assertEqual((a.tags, b.tags), (("에이",), ("비",)))
        self.assertIn("「블로그 A」", a.checklist[-1])
        self.assertIn("「블로그 B」", b.checklist[-1])


class ChecklistTest(unittest.TestCase):
    def test_the_checklist_is_the_publishing_steps_in_order_ending_with_the_manual_publish(self):
        package = build("본문", prof=profile(image_spec="가로 800px 이상", categories={"건강": "생활 건강"}), assets=[Asset("a.png", "그림", 0)], category="건강")
        self.assertTrue(all(line.startswith("- [ ] ") for line in package.checklist))
        text = "\n".join(package.checklist)
        self.assertLess(text.index("미리보기"), text.index("이미지 1장"))
        self.assertLess(text.index("이미지 1장"), text.index("태그 1개"))
        self.assertLess(text.index("태그 1개"), text.index("카테고리 「생활 건강」"))
        self.assertLess(text.index("카테고리 「생활 건강」"), text.index("AI 활용 고지문"))
        self.assertLess(text.index("AI 활용 고지문"), text.index("비교 결과"))
        self.assertTrue(package.checklist[-1].endswith("발행한 글의 주소를 입력합니다"))
        self.assertIn("대표 이미지 규격: 가로 800px 이상", text)
        self.assertIn("사실 확인을 하지 않습니다", text)

    def test_nothing_in_the_checklist_promises_an_automatic_publish_or_login(self):
        text = "\n".join(build("본문", assets=[Asset("a.png", "그림", 0)]).checklist)
        for needle in ("자동으로 발행", "자동 발행", "로그인", "쿠키", "비밀번호"):
            self.assertNotIn(needle, text)


class RobustnessTest(unittest.TestCase):
    def test_odd_manuscripts_never_crash_and_always_give_allowed_tags(self):
        rng = random.Random(3)
        alphabet = list("*_`[]()<>#-+1.2!\\&\"' \t\n") + ["**", "```", "![", "](", "> ", "- ", "1. ", "  \n", "한", "글", "https://a.b/", "<script>", ". ", "? ", "! ", "… ", "다. ", "<br>"]
        for _ in range(300):
            body = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 150)))
            try:
                package = build_package(profile(paragraph_max_chars=rng.randint(40, 120)), title="제목", body=body, assets=[Asset("a.png", "", rng.randint(0, 6))])
            except AppError as error:
                self.assertEqual(error.code, "NAVER_PACKAGE_INCOMPLETE", repr(body))
                continue
            self.assertLessEqual(tags_in(package.body_html), set(ALLOWED_TAGS), repr(body))
            self.assertIsInstance(package.body_text, str)

    def test_the_worst_inputs_finish_quickly(self):
        nasty = ("가나다. " * 20000, "가" * 200000, "*가 " * 5000, ("가나다라마바사아자차카타파하" * 20 + ". ") * 500, "> " * 3000 + "x", "- a\n" * 5000)
        started = time.time()
        for body in nasty:
            begin = time.time()
            build(body, prof=profile(paragraph_max_chars=60))
            self.assertLess(time.time() - begin, 10, body[:20])
        self.assertLess(time.time() - started, 40)


if __name__ == "__main__":
    unittest.main()
