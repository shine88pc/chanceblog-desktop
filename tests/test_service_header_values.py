"""서비스 층 — **머리말 값 전부**(제목·분야·태그·대표 이미지 주소·설명·출처)에 본문과 같은 검사를 거는 시험.

배경: 독립 검증(2차)이 영어 글의 title `Breaking <script>alert(1)</script> news today`·`{{ site.url }}`·`{% include x.html %}`, tags `<b>x</b>`, image `javascript:alert(1)` 가 게이트를 통과하는 것을 재현했다
(게이트가 본문만 검사했다). 머리말 값은 사이트의 글 목록(`posts.json`)·카드·`<title>`·`<meta>` 에 들어가고, chanceblog 첫 화면(`index.html`)의 글 카드는 제목·분야·태그·이미지 주소를 이스케이프 없이 HTML 에 넣는다.

지키는 것:
  1) 머리말의 어느 값이든 HTML 태그(`RAW_HTML`)·`{% %}`/`{{ }}`/`{# #}`(`LIQUID`)·`{: }`(`KRAMDOWN`)·`javascript:`/`data:`/`vbscript:`(`UNSAFE_URL`)·광고 스크립트(`AD_SCRIPT`)가 있으면 막고,
     줄바꿈·제어 문자·너무 긴 값·https 가 아닌 이미지 주소·따옴표/꺾쇠가 든 주소·모르는 머리말 키·어긋난 출처 세 줄은 `HEADER_VALUE` 로 막는다. 정상 제목(따옴표·콜론·`#`·`---`·`&`)은 막지 않는다.
  2) 머리말 구조는 깨지지 않는다: 제목에 줄바꿈·따옴표·콜론·`---`·`#` 가 있어도 다른 키(layout·ads·published …)가 끼어들지 못한다(렌더링은 한 줄 JSON 으로 이스케이프하고, 줄바꿈은 거절하며, 게이트는 모르는 키를 거절한다).
  3) 같은 사유로 `new`·`edit`(제목), `review`·`preview`(분야·태그·이미지 주소·설명·출처), 승인, 연습 실행, 올리기에서 막는다 — 막힌 글은 저장소에 아무것도 쓰지 않는다.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content.model import ContentProject  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.render.pages import json_line, render_pages_post  # noqa: E402
from chanceblog_desktop.service import gate, pages_flow, previews, projects, review  # noqa: E402

FIXTURES = ss.ROOT / "tests" / "fixtures"
EN_FIXTURE = (FIXTURES / "chance_post_en.md").read_text(encoding="utf-8").replace("\r\n", "\n")
KO_FIXTURE = (FIXTURES / "chance_post_ko.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def with_field(base, key, value):
    """진짜 글(base)의 머리말에서 key 한 줄을 한 줄 JSON value 로 바꾼다(렌더링과 같은 `json_line` — 없으면 닫는 줄 앞에 더한다). value 가 None 이면 그 줄을 지운다."""
    lines = base.split("\n")
    end = lines.index("---", 1)
    out, done = [], False
    for index, line in enumerate(lines[: end + 1]):
        if 0 < index < end and line.startswith(key + ":"):
            if value is not None:
                out.append(f"{key}: {json_line(value)}")
            done = True
        else:
            out.append(line)
    if not done and value is not None:
        out.insert(end, f"{key}: {json_line(value)}")
    return "\n".join(out + lines[end + 1:])


def codes(text):
    return gate.run_gates(text).codes()


class EveryHeaderValueIsCheckedTest(unittest.TestCase):
    def test_the_real_chance_posts_still_pass(self):
        for name, text in (("영문", EN_FIXTURE), ("한글", KO_FIXTURE)):
            with self.subTest(post=name):
                report = gate.run_gates(text)
                self.assertTrue(report.ok, report.reasons)

    def test_the_cases_the_independent_check_found_are_all_blocked_now(self):
        cases = {
            "title <script>": ("title", "Breaking <script>alert(1)</script> news today", "RAW_HTML"),
            "title {{ }}": ("title", "Breaking {{ site.url }} news today", "LIQUID"),
            "title {% %}": ("title", "{% include x.html %} Breaking news today", "LIQUID"),
            "tags <b>": ("tags", ["<b>x</b>"], "RAW_HTML"),
            "image javascript:": ("image", "javascript:alert(1)", "UNSAFE_URL"),
        }
        for name, (key, value, code) in cases.items():
            with self.subTest(case=name):
                found = codes(with_field(EN_FIXTURE, key, value))
                self.assertIn(code, found, found)

    def test_every_key_is_checked_for_every_kind_of_danger(self):
        dangers = {"RAW_HTML": "x <img src=x onerror=alert(1)> y", "LIQUID": "x {{ site.url }} y", "KRAMDOWN": "x {:onclick=\"a()\"} y", "AD_SCRIPT": "x adsbygoogle y"}
        for key in ("title", "category", "description", "source_name"):
            for code, text in dangers.items():
                with self.subTest(key=key, code=code):
                    self.assertIn(code, codes(with_field(EN_FIXTURE, key, text)))
        for code, text in dangers.items():
            with self.subTest(key="tags", code=code):
                self.assertIn(code, codes(with_field(EN_FIXTURE, "tags", ["fine", text])))
        for key in ("image", "source_url"):
            for code in ("RAW_HTML", "LIQUID"):
                with self.subTest(key=key, code=code):
                    self.assertIn(code, codes(with_field(EN_FIXTURE, key, "https://example.com/" + dangers[code])))

    def test_a_markdown_link_with_a_script_address_hidden_in_a_description_is_blocked(self):
        self.assertIn("UNSAFE_URL", codes(with_field(EN_FIXTURE, "description", "[click](javascript:alert(1))")))
        self.assertIn("UNSAFE_URL", codes(with_field(EN_FIXTURE, "description", "javascript:alert(1)")), "주소로 시작하는 글")
        self.assertIn("UNSAFE_URL", codes(with_field(EN_FIXTURE, "title", "&#106;avascript:alert(1)")), "엔티티로 숨긴 것")
        self.assertIn("UNSAFE_URL", codes(with_field(EN_FIXTURE, "title", "java​script:alert(1)")), "보이지 않는 글자로 쪼갠 것")
        self.assertNotIn("UNSAFE_URL", codes(with_field(EN_FIXTURE, "title", "JavaScript: The Good Parts")), "콜론 뒤가 공백인 제목은 주소가 아니다")
        self.assertNotIn("UNSAFE_URL", codes(with_field(EN_FIXTURE, "title", "Data: the new oil")))

    def test_a_tag_split_by_an_invisible_character_in_a_header_value_is_still_found(self):
        for key, value in (("title", "Hi <scr​ipt>alert(1)</scr​ipt> there"), ("description", "<ima​g src=x onerror=alert(1)>"), ("category", "<⁠b>x"), ("tags", ["<sㅤtyle>x"])):
            with self.subTest(key=key):
                self.assertIn("RAW_HTML", codes(with_field(EN_FIXTURE, key, value)))

    def test_the_header_reasons_name_the_field(self):
        report = gate.run_gates(with_field(EN_FIXTURE, "title", "Breaking <script>alert(1)</script> news today"))
        self.assertTrue(any("머리말 `title`" in reason and "RAW_HTML" in reason and "<script>" in reason for reason in report.reasons), report.reasons)
        report = gate.run_gates(with_field(EN_FIXTURE, "tags", ["<b>x</b>"]))
        self.assertTrue(any("머리말 `tags`" in reason for reason in report.reasons), report.reasons)

    def test_normal_titles_are_not_blocked(self):
        english = ('He said "no": a # b --- c', "JavaScript: The Good Parts", "Rock & Roll", "Q&A: What to Ask", "x < y and y > z", "Reinforcing Frontex: The European Commission’s Proposal", "100% sure? Maybe #1")
        korean = ("C++ 입문: 포인터와 참조 #1", "AI 시대 — 일자리 3가지", "100% 확실?", "x < y 이고 y 가 크다면", "Q&A: 자주 묻는 질문", "물가 3.2% ↑ · 금리 동결")
        for base, titles in ((EN_FIXTURE, english), (KO_FIXTURE, korean)):
            for title in titles:
                with self.subTest(title=title):
                    report = gate.run_gates(with_field(base, "title", title))
                    self.assertTrue(report.ok, report.reasons)

    def test_a_title_that_is_too_long_or_has_a_line_break_is_a_header_value_problem(self):
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "title", "가" * 201)))
        self.assertNotIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "title", "가" * 200)))
        for text in ("a\nb", "a\rb", "a\x00b", "a\x1fb", "a\x85b", "a b", "a b"):                 # 한 줄 JSON 이 \uXXXX 로 쓰는 것들 — 머리말은 멀쩡해 보이지만 값에 줄바꿈이 들어 있다
            with self.subTest(text=ascii(text)):
                self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "title", text)))
        for text in ("a\x7fb", "a\x9fb"):                                                                  # 그대로 적힌 제어 문자는 머리말 검사(HEADER)에서 막힌다
            with self.subTest(text=ascii(text)):
                self.assertFalse(gate.run_gates(with_field(EN_FIXTURE, "title", text)).ok)
        self.assertNotIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "title", "탭\u0009도 받는다")))

    def test_the_limits_of_the_other_values_are_the_renderers(self):
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "category", "x" * 101)))
        self.assertNotIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "category", "x" * 100)))
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "description", "x" * 301)))
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "source_name", "x" * 201)))
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "tags", [f"t{n}" for n in range(11)])))
        self.assertNotIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "tags", [f"t{n}" for n in range(10)])))
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "tags", ["x" * 41])))
        self.assertNotIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "tags", ["x" * 40])))

    def test_invisible_characters_are_not_allowed_in_the_small_values_but_one_in_a_title_is_left_to_the_body_count(self):
        for key, value in (("category", "Soci​ety"), ("description", "des​c"), ("source_name", "Eu​ropean")):
            with self.subTest(key=key):
                self.assertIn("INVISIBLE", codes(with_field(EN_FIXTURE, key, value)))
        self.assertIn("INVISIBLE", codes(with_field(EN_FIXTURE, "tags", ["a​b"])))
        self.assertNotIn("INVISIBLE", codes(with_field(EN_FIXTURE, "title", "A​B")), "제목은 본문의 보이지 않는 글자 수와 합쳐서 센다(몇 개는 오탐하지 않는다)")

    def test_the_address_values_must_be_plain_https_or_http_addresses(self):
        for value in ("http://images.example.com/a.jpg", "//images.example.com/a.jpg", "images.example.com/a.jpg", "ftp://images.example.com/a.jpg", "https:///a.jpg", "https://user:pw@images.example.com/a.jpg",
                      "data:image/png;base64,AAAA", "javascript:alert(1)", "vbscript:x", " https://images.example.com/a.jpg", "https://images.example.com/a b.jpg"):
            with self.subTest(image=value):
                self.assertFalse(gate.run_gates(with_field(EN_FIXTURE, "image", value)).ok)
        for value in ('https://images.example.com/a.jpg"onerror="alert(1)', "https://images.example.com/a.jpg<x>", "https://images.example.com/a`b", "https://images.example.com/a\\b"):
            with self.subTest(image=value):
                self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "image", value)), "HTML 속성 밖으로 빠져나오는 글자")
        for value in ("https://images.unsplash.com/photo-1?auto=format&fit=crop&w=1000&q=80", "https://images.example.com:8443/a.jpg", "https://[::1]/a.jpg", "https://xn--hq1b.example/a.jpg"):
            with self.subTest(image=value):
                self.assertTrue(gate.run_gates(with_field(EN_FIXTURE, "image", value)).ok, gate.run_gates(with_field(EN_FIXTURE, "image", value)).reasons)

    def test_the_source_address_may_be_http_but_the_three_source_lines_must_agree(self):
        self.assertTrue(gate.run_gates(with_field(with_field(EN_FIXTURE, "source_url", "http://commission.europa.eu/a"), "source_domain", "commission.europa.eu")).ok)
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "source_domain", "evil.example")))
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "source_url", None)), "출처 세 줄이 함께 있어야 한다")
        self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, "source_name", None)))
        without = with_field(with_field(with_field(EN_FIXTURE, "source_name", None), "source_url", None), "source_domain", None)
        self.assertTrue(gate.run_gates(without).ok, "출처가 없는 글은 세 줄이 모두 없다")

    def test_a_header_key_the_renderer_never_writes_is_refused(self):
        for key, value in (("published", False), ("permalink", "/index.html"), ("date", "2099-01-01"), ("redirect_from", "/x/"), ("ads", "on"), ("sitemap", False), ("layout2", "x")):
            with self.subTest(key=key):
                self.assertIn("HEADER_VALUE", codes(with_field(EN_FIXTURE, key, value)))

    def test_a_physical_line_that_a_value_tried_to_add_is_just_an_unknown_key_and_is_refused(self):
        lines = EN_FIXTURE.split("\n")
        end = lines.index("---", 1)
        for extra in ("ads: on", "layout: evil", "published: false", "title: second"):
            with self.subTest(extra=extra):
                text = "\n".join(lines[:end] + [extra] + lines[end:])
                self.assertFalse(gate.run_gates(text).ok)


class HeaderStructureStaysIntactTest(unittest.TestCase):
    """제목에 줄바꿈·따옴표·콜론·`---`·`#` 를 넣어도 머리말 구조가 깨지거나 다른 키가 끼어들지 못한다."""

    NASTY = ('a"b', "a: b", "---", "# x", "a --- b", "%{x}", "!!str x", "&anchor *alias", "- list", "key: value", "\\n", "a\\nlayout: evil", '"quoted"', "'single'", "{ map: 1 }", "[1, 2]", "title: x", "x #comment")
    BROKEN = ("a\nlayout: evil", "a\r\nads: on", "a\nb", "a\rb", "a\x00b", "\n---\nlayout: evil", "x\nadvertisement: true")             # 렌더링이 거절한다
    ONLY_THE_GATE_REFUSES = ("a b", "a b", "a\x85b")                                                                         # 렌더링은 \uXXXX 로 이스케이프해 받지만 게이트는 값 속 줄바꿈으로 본다

    def render(self, title):
        project = ContentProject.new(title, ss.ko_text(), now="2026-11-02T00:00:00Z")
        return render_pages_post(project, category="경제·일", lang="ko", image_url="https://images.example.invalid/a.jpg", tags=("에너지",), now=ss.NOW)

    def test_a_nasty_title_comes_out_as_one_json_line_with_exactly_the_expected_keys(self):
        for title in self.NASTY:
            with self.subTest(title=title):
                post = self.render(title)
                header, _body = gate.split_post(post.text)
                self.assertEqual(sorted(header), sorted(["layout", "title", "category", "tags", "lang", "image", "description"]))
                self.assertEqual(header["title"], title.strip())
                head_lines = post.text.split("\n")[1:post.text.split("\n").index("---", 1)]
                self.assertEqual(len([line for line in head_lines if line.strip()]), 7, "머리말은 한 줄 한 키다")
                self.assertNotIn("HEADER_VALUE", gate.run_gates(post.text).codes(), "머리말 구조는 멀쩡하다")

    def test_a_title_with_a_line_break_is_refused_before_anything_is_written(self):
        for title in self.BROKEN:
            with self.subTest(title=ascii(title)):
                with self.assertRaises(AppError) as caught:
                    self.render(title)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_the_gate_refuses_what_the_renderer_would_never_make_even_if_the_stored_text_was_changed(self):
        post = self.render("정상 제목")
        for title in self.BROKEN + self.ONLY_THE_GATE_REFUSES:
            with self.subTest(title=ascii(title)):
                tampered = with_field(post.text, "title", title)
                self.assertFalse(gate.run_gates(tampered).ok)
        raw = post.text.replace('title: "정상 제목"', 'title: "정상 제목"\nads: on')
        self.assertFalse(gate.run_gates(raw).ok)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)

    def run_cli(self, *argv):
        return ss.run_cli(self.ctx, *argv)

    def pages_args(self, **override):
        values = {"category": "경제·일", "lang": "ko", "image-url": "https://images.example.invalid/a.jpg", **override}
        return [item for key, value in values.items() for item in ("--" + key, value)]


class TitleAtInputTimeTest(Base):
    def test_a_dangerous_or_multiline_title_is_refused_when_the_post_is_made_and_nothing_is_saved(self):
        for title in ("<script>alert(1)</script> 제목", "{{ site.url }} 제목", "{% include x.html %}", "줄바꿈이\n있는 제목", "제목\r\nlayout: evil", "javascript:alert(1)", '제목 <img src=x onerror=alert(1)>',
                      "제목 {: onclick=\"a()\"}", "광고 adsbygoogle 제목"):
            with self.subTest(title=ascii(title)):
                error = ss.code_of(projects.new_project, self.ctx, title, ss.ko_text())
                self.assertEqual(error.code, "CHECK_FAILED")
                self.assertTrue(error.slots["걸린 항목 목록"])
        self.assertEqual(projects.list_projects(self.ctx), [])

    def test_the_command_line_refuses_it_too_with_the_same_code_and_a_reason(self):
        code, out, err = self.run_cli("new", "--title", "<b>굵은 제목</b>", "--text", ss.ko_text())
        self.assertEqual(code, 1)
        self.assertIn("CHECK_FAILED", err)
        self.assertIn("RAW_HTML", err)
        self.assertIn("머리말 `title`", err)
        code, out, err = self.run_cli("new", "--title", "줄\n바꿈", "--text", ss.ko_text())
        self.assertEqual(code, 1)
        self.assertIn("HEADER_VALUE", err)
        code, out, err = self.run_cli("import-html", "--title", "{{ x }}", "--text", "<p>안녕하세요</p>")
        self.assertEqual(code, 1)
        self.assertIn("LIQUID", err)
        self.assertEqual(projects.list_projects(self.ctx), [])

    def test_normal_titles_are_made(self):
        for title in ('따옴표 "있는" 제목', "콜론: 있는 제목 #1", "C++ 와 Rust — 비교", "Rock & Roll", "JavaScript: 입문"):
            with self.subTest(title=title):
                self.assertEqual(projects.new_project(self.ctx, title, ss.ko_text()).title, title)

    def test_editing_the_title_is_checked_the_same_way_and_a_refused_edit_changes_nothing(self):
        view = projects.new_project(self.ctx, "처음 제목", ss.ko_text())
        for title in ("<script>x</script>", "{{ y }}", "a\nb"):
            with self.subTest(title=ascii(title)):
                self.assertEqual(ss.code_of(projects.edit_project, self.ctx, view.project_id, title=title).code, "CHECK_FAILED")
        again = projects.show_project(self.ctx, view.project_id)
        self.assertEqual((again.title, again.revision), ("처음 제목", 1))
        self.assertEqual(self.run_cli("edit", view.project_id, "--title", "<i>x</i>")[0], 1)
        self.assertTrue(projects.edit_project(self.ctx, view.project_id, title='새 "제목"').changed)

    def test_the_other_input_problems_keep_their_own_codes(self):
        self.assertEqual(ss.code_of(projects.new_project, self.ctx, "가" * 201, ss.ko_text()).code, "CONTENT_INVALID", "길이는 모델이 본다")
        self.assertEqual(ss.code_of(projects.new_project, self.ctx, "", ss.ko_text()).code, "CONTENT_INVALID")
        self.assertEqual(ss.code_of(projects.new_project, self.ctx, None, ss.ko_text()).code, "CONTENT_INVALID")


class ValuesAtReviewTimeTest(Base):
    def setUp(self):
        super().setUp()
        self.project_id = projects.new_project(self.ctx, "정상 제목", ss.ko_text()).project_id

    def assert_refused(self, code, params, **kwargs):
        error = ss.code_of(review.request_review, self.ctx, self.project_id, "github_pages", pages=params)
        self.assertEqual(error.code, "CHECK_FAILED", error.detail)
        self.assertIn(code, error.slots["걸린 항목 목록"])
        self.assertEqual(ss.code_of(previews.preview_pages, self.ctx, self.project_id, params).code, "CHECK_FAILED")
        self.assertEqual(ss.status_of(self.ctx, self.project_id), st.NOT_STARTED, "검토 중으로 보내지도 않았다")
        self.assertEqual(projects.show_project(self.ctx, self.project_id).variant("github_pages").has_rendering, False)

    def params(self, **override):
        values = dict(category="경제·일", lang="ko", image_url="https://images.example.invalid/a.jpg", tags=("에너지",), description=None, source=None)
        values.update(override)
        return previews.PagesParams(**values)

    def test_tags_category_description_image_and_source_are_checked_when_they_are_given(self):
        self.assert_refused("RAW_HTML", self.params(tags=("<b>x</b>",)))
        self.assert_refused("RAW_HTML", self.params(category="<i>경제</i>"))
        self.assert_refused("LIQUID", self.params(description="{% include x.html %} 설명"))
        self.assert_refused("RAW_HTML", self.params(description="<img src=x onerror=alert(1)>"))
        self.assert_refused("HEADER_VALUE", self.params(image_url='https://images.example.invalid/a.jpg"onerror="alert(1)'))
        self.assert_refused("RAW_HTML", self.params(source={"name": "<script>x</script>", "url": "https://example.com/a"}))
        self.assert_refused("LIQUID", self.params(source={"name": "출처", "url": "https://example.com/{{x}}"}))

    def test_a_good_set_of_values_is_reviewed_as_before(self):
        result = review.request_review(self.ctx, self.project_id, "github_pages", pages=self.params(tags=("에너지", "생활"), description="좋은 설명", source={"name": "출처", "url": "https://example.com/a"}))
        self.assertEqual(result.status, st.REVIEW_REQUIRED)
        self.assertTrue(result.pages.gates.ok, result.pages.gates.reasons)

    def test_the_command_line_says_which_value_was_refused(self):
        code, out, err = self.run_cli("review", self.project_id, "--platform", "pages", *self.pages_args(tags="<b>x</b>"))
        self.assertEqual(code, 1)
        self.assertIn("CHECK_FAILED", err)
        self.assertIn("머리말 `tags`", err)
        code, out, err = self.run_cli("preview", self.project_id, "--platform", "pages", *self.pages_args(category="{{ x }}"))
        self.assertEqual(code, 1)
        self.assertIn("LIQUID", err)
        self.assertEqual(ss.status_of(self.ctx, self.project_id), st.NOT_STARTED)


class StoredHeaderIsCheckedAtEveryLaterStepTest(Base):
    """저장된 렌더링의 머리말이 어떻게든 바뀌어 있어도(백업 복구·손으로 고친 데이터) 승인·연습 실행·올리기에서 같은 사유로 막힌다."""

    def rendered(self, project_id):
        with self.ctx.store() as store:
            return store.load(project_id).variant("github_pages").rendered

    def set_rendered(self, project_id, text):
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.variant("github_pages").rendered = text
            store.save(project)

    def tamper(self, project_id, key, value):
        self.set_rendered(project_id, with_field(self.rendered(project_id), key, value))

    def test_approval_is_refused_and_the_status_stays(self):
        view = projects.new_project(self.ctx, "정상 제목", ss.ko_text())
        review.request_review(self.ctx, view.project_id, "github_pages", pages=ss.KO_PARAMS)
        self.tamper(view.project_id, "title", "Breaking <script>alert(1)</script> news today")
        error = ss.code_of(review.grant_approval, self.ctx, view.project_id, "github_pages")
        self.assertEqual(error.code, "CHECK_FAILED")
        self.assertIn("RAW_HTML", error.slots["걸린 항목 목록"])
        self.assertEqual(ss.status_of(self.ctx, view.project_id), st.REVIEW_REQUIRED)

    def test_the_dry_run_and_the_real_publish_are_refused_and_nothing_reaches_the_repository(self):
        project_id = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        original = self.rendered(project_id)
        for key, value, reason in (("title", "{% include x.html %}", "LIQUID"), ("tags", ["<b>x</b>"], "RAW_HTML"), ("image", "javascript:alert(1)", "UNSAFE_URL"), ("published", False, "HEADER_VALUE")):
            with self.subTest(key=key):
                self.tamper(project_id, key, value)
                for call in (lambda: pages_flow.preview_publish(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):
                    error = ss.code_of(call)
                    self.assertEqual(error.code, "CHECK_FAILED")
                    self.assertIn(reason, error.slots["걸린 항목 목록"])
                for argv in (("publish-pages", project_id), ("publish-pages", project_id, "--yes")):
                    exit_code, out, err = self.run_cli(*argv)
                    self.assertEqual(exit_code, 1, argv)
                    self.assertIn("CHECK_FAILED", err)
                self.assertEqual((self.backend.count("commit"), self.backend.count("push")), (0, 0))
                self.assertEqual(ss.status_of(self.ctx, project_id), st.APPROVED)
                self.set_rendered(project_id, original)

    def test_the_untouched_post_still_goes_up(self):
        project_id = ss.make_approved(self.ctx)
        self.assertEqual(pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True).status, st.PUBLISHED)


if __name__ == "__main__":
    unittest.main()
