"""서비스 층 — 발행 전 검사(게이트)를 독립 검증이 재현한 빈틈에 맞게 조인 것의 시험.

지키는 것:
  1) **올라가는 글 그대로(Markdown 원문)** 를 본다: 원시 HTML 태그(script·ins·iframe·img onerror·style·meta·form …)·`javascript:`/`data:`/`vbscript:` 주소(대소문자·공백·엔티티·줄바꿈으로 숨긴 것 포함)·
     `{% %}`·`{{ }}` 템플릿 표기·`{: }` 속성 붙이기·광고 스크립트가 있으면 막는다. 정상 글(굵게·https 링크·이미지·목록·인용·자동 링크)과 실제 Chance 글 두 편은 통과한다.
  2) 길이 기준의 경계: 한글 1000자 통과·999자 탈락, 영어 1500자 통과·1499자 탈락(`<` → `<=`·`- 1` 변이가 살아남지 않게).
  3) 눈에 안 보이는 글자는 글자 수에 세지 않고, 비정상적으로 많으면(50개 초과·본문의 5% 초과) 막는다. 이모지의 ZWJ·변형 선택자와 몇 개의 보이지 않는 글자는 오탐하지 않는다.
  4) 이 PC 의 경로: UNC·8.3 짧은 이름·`file:`·WSL 경로·대소문자만 다른 저장소 경로를 막고, 글 속 `1~10` 같은 표기·주소는 막지 않는다.
  5) 아주 긴 이상한 입력(`[a` 수만 번)에서도 글자 수 계산이 빨리 끝난다.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content.model import ContentProject  # noqa: E402
from chanceblog_desktop.render.pages import render_pages_post  # noqa: E402
from chanceblog_desktop.service import gate, pages_flow, previews, projects, review  # noqa: E402

FIXTURES = ss.ROOT / "tests" / "fixtures"
KO_FIXTURE = (FIXTURES / "chance_post_ko.md").read_text(encoding="utf-8")
EN_FIXTURE = (FIXTURES / "chance_post_en.md").read_text(encoding="utf-8")


def post_text(body, *, lang="ko", title="제목"):
    project = ContentProject.new(title, body, now="2026-11-02T00:00:00Z")
    params = ss.KO_PARAMS if lang == "ko" else ss.EN_PARAMS
    return render_pages_post(project, category=params.category, lang=lang, image_url=params.image_url, tags=params.tags, now=ss.NOW).text


def codes(body, *, lang="ko", title="제목", local_paths=()):
    return gate.run_gates(post_text(body, lang=lang, title=title), local_paths=local_paths).codes()


class BoundaryTest(unittest.TestCase):
    def test_korean_exactly_one_thousand_passes_and_nine_hundred_ninety_nine_fail(self):
        for count, short in ((1000, False), (999, True), (1001, False)):
            with self.subTest(count=count):
                body = ("가나다라마바사아자차" * 101)[:count]
                self.assertEqual(gate.readable_chars(body), count)
                self.assertEqual("LEN_BODY" in codes(body), short)
        self.assertTrue(gate.run_gates(post_text(("가나다라마바사아자차" * 101)[:1000])).ok, gate.run_gates(post_text(("가나다라마바사아자차" * 101)[:1000])).reasons)

    def test_english_exactly_fifteen_hundred_passes_and_fourteen_hundred_ninety_nine_fail(self):
        for count, short in ((1500, False), (1499, True), (1501, False)):
            with self.subTest(count=count):
                body = ("abcdefghi " * 170)
                letters = 0
                kept = []
                for word in body.split():
                    take = min(len(word), count - letters)
                    if take:
                        kept.append(word[:take])
                        letters += take
                body = " ".join(kept)
                self.assertEqual(gate.readable_chars(body), count)
                self.assertEqual("LEN_BODY" in codes(body, lang="en", title="Energy"), short)

    def test_the_minimums_are_the_cloud_generators(self):
        self.assertEqual(gate.LENGTH_MIN, {"ko": 1000, "en": 1500})


class InvisibleCharactersTest(unittest.TestCase):
    FILLERS = ("\u200b", "\u2060", "\u3164", "\u2800", "\u115f", "\u1160", "\uffa0", "\u180e", "\u00ad", "\u200e", "\u034f", "\U0001d173")        # (U+FEFF \ub294 \uae00 \uc55e\ucabd\uc5d0\uc11c \ubaa8\ub378\uc774 \uc774\ubbf8 \uac77\uc5b4 \ub0b8\ub2e4)

    def test_a_flood_of_invisible_characters_with_a_few_korean_letters_is_short_and_flagged(self):
        for char in self.FILLERS:
            with self.subTest(char=hex(ord(char))):
                body = char * 1200 + "가나다라마바사아자차카타"
                self.assertEqual(gate.readable_chars(body), 12)
                found = codes(body)
                self.assertIn("LEN_BODY", found)
                self.assertIn("INVISIBLE", found)
                self.assertEqual(ss.code_of(gate.require_gates, post_text(body)).code, "CHECK_FAILED")

    def test_the_same_in_english(self):
        body = "\u200b" * 1600 + "Energy saving tips"
        self.assertEqual(gate.readable_chars(body), len("Energysavingtips"))
        self.assertIn("LEN_BODY", codes(body, lang="en", title="Energy"))

    def test_spaces_inside_the_text_and_invisible_characters_between_letters_are_all_left_out(self):
        self.assertEqual(gate.readable_chars("가\u200b나\u2060 다\u3164라\u2800마"), 5)
        self.assertEqual(gate.readable_chars(""), 0)

    def test_fifty_invisible_characters_in_a_long_post_pass_and_fifty_one_do_not(self):
        story = ss.ko_text(3000)
        self.assertGreater(len(story), 1000)
        for count, flagged in ((50, False), (51, True)):
            with self.subTest(count=count):
                text = post_text(story + "\n\n" + "\u200b" * count)
                self.assertEqual("INVISIBLE" in gate.run_gates(text).codes(), flagged, gate.run_gates(text).reasons)

    def test_more_than_five_percent_of_the_body_is_flagged_even_when_below_fifty(self):
        small = "가" * 400
        base = len(gate.split_post(post_text(small))[1])                 # 대표 이미지 줄까지 든 본문 길이 — n 개를 더하면 n > 0.05 * (base + n) 일 때 막는다
        allowed = int(base / 19)
        self.assertNotIn("INVISIBLE", codes(small + "\u200b" * allowed))
        self.assertIn("INVISIBLE", codes(small + "\u200b" * (allowed + 1)))
        self.assertLess(allowed, 50)

    def test_a_normal_post_with_emoji_joiners_variation_selectors_and_a_stray_mark_is_not_flagged(self):
        extra = "가족 이모지 👨\u200d👩\u200d👧 와 하트 ❤\ufe0f 그리고 깃발 🏳\ufe0f\u200d🌈 입니다. 소프트 하이픈은\u00ad 한 번뿐입니다."
        text = post_text(ss.ko_text(extra=extra))
        report = gate.run_gates(text)
        self.assertTrue(report.ok, report.reasons)
        self.assertNotIn("INVISIBLE", report.codes())
        self.assertEqual(gate.invisible_count("👨\u200d👩\u200d👧 ❤\ufe0f"), 0, "ZWJ·변형 선택자는 '많음' 판단에서 뺀다")
        self.assertEqual(gate.invisible_count("가\u200b나\u00ad다"), 2)

    def test_the_two_real_chance_posts_still_pass(self):
        for name, text in (("한글", KO_FIXTURE), ("영문", EN_FIXTURE)):
            with self.subTest(post=name):
                report = gate.run_gates(text)
                self.assertTrue(report.ok, report.reasons)
                self.assertEqual(report.codes(), ())


class LocalPathTest(unittest.TestCase):
    def blocked(self, leak, *, local_paths=()):
        return "LOCAL_PATH" in codes(ss.ko_text(extra=f"원본은 {leak} 에 있습니다."), local_paths=local_paths)

    def test_unc_paths_are_blocked_in_every_spelling(self):
        for leak in (r"\\fileserver\share\원고.md", r"\\\\fileserver\\share\\원고.md", r"\\192.168.0.10\공유\초안", r"\\wsl$\Ubuntu\home\kim", r"\\?\UNC\server\share\x", r"\\wsl.localhost\Ubuntu\x"):
            with self.subTest(leak=leak):
                self.assertTrue(self.blocked(leak), leak)

    def test_short_eight_dot_three_names_are_blocked(self):
        for leak in (r"C:\PROGRA~1\앱", "c:/progra~1/app", r"D:\Users2\SDI_US~1\Desktop", r"\SDI_US~1\Desktop", r"E:\DOCUME~1\x", r"위치 C:\Work\LONGFI~2.TXT 입니다"):
            with self.subTest(leak=leak):
                self.assertTrue(self.blocked(leak), leak)

    def test_file_urls_and_wsl_paths_and_other_user_folder_spellings_are_blocked(self):
        for leak in ("file:///C:/Users/kim/x.md", "FILE:///d:/work/x", "file://server/share/x", "file:////server/share/x", "/mnt/c/Users/kim/원고.md", "/cygdrive/d/users/kim/x", r"c:\USERS\kim\x", "C:/users/kim/x",
                     r"\\?\C:\Users\kim\x", "file:///C:%5CUsers%5Ckim"):
            with self.subTest(leak=leak):
                self.assertTrue(self.blocked(leak), leak)

    def test_the_connected_folder_is_found_whatever_the_case_slashes_or_encoding(self):
        repo = r"E:\Work\내폴더\ChanceBlog"
        for leak in (r"e:\work\내폴더\chanceblog", "E:/WORK/내폴더/CHANCEBLOG", r"E:\Work\내폴더\ChanceBlog\_posts", "file:///E:/work/%EB%82%B4%ED%8F%B4%EB%8D%94/chanceblog", "e:\\\\work\\\\내폴더\\\\chanceblog".replace("\\\\", "\\")):
            with self.subTest(leak=leak):
                self.assertTrue(self.blocked(leak, local_paths=(repo,)), leak)
        self.assertFalse(self.blocked("E:/Other/폴더", local_paths=(repo,)))

    def test_ordinary_tildes_ranges_and_urls_are_not_mistaken_for_paths(self):
        for text in ("범위는 1~10 입니다", "약 ~1.5배", "A~1 등급과 B~2 등급", "https://example.com/post~1/page", "//cdn.example.com/x.js 처럼 쓰는 주소", "비용은 5\\~10만 원", r"윈도우 폴더는 C:\Windows\System32 입니다",
                     "슬래시 하나 \\ 그리고 둘 \\\\ 만"):
            with self.subTest(text=text):
                self.assertFalse(self.blocked(text), text)

    def test_the_old_checks_still_work(self):
        for leak in (r"C:\Users\운영자\Desktop\원고.md", "c:/users/someone/x", r"D:\Documents and Settings\x"):
            self.assertTrue(self.blocked(leak), leak)
        self.assertTrue(gate.run_gates(post_text(ss.ko_text()), local_paths=("", "/", "C:", "abc")).ok)


class RawMarkdownTest(unittest.TestCase):
    """저장소에 올라가는 것은 Markdown 원문이다 — HTML 로 바꾼 결과만 보던 때에는 아래가 모두 통과했다."""

    REPRODUCED = (
        ("script·광고", '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1"></script>', ("RAW_HTML", "AD_SCRIPT")),
        ("ins 광고", '<ins class="adsbygoogle" style="display:block" data-ad-client="ca-pub-1" data-ad-slot="1"></ins>', ("RAW_HTML", "AD_SCRIPT")),
        ("iframe", '<iframe src="https://evil.example/" width="1" height="1"></iframe>', ("RAW_HTML",)),
        ("img onerror", "<img src=x onerror=alert(1)>", ("RAW_HTML",)),
        ("javascript 링크", "[클릭](javascript:alert(1))", ("UNSAFE_URL",)),
        ("data 링크", "[열기](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)", ("UNSAFE_URL",)),
        ("style", "<style>body{display:none}</style>", ("RAW_HTML",)),
        ("meta refresh", '<meta http-equiv="refresh" content="0;url=https://evil.example/">', ("RAW_HTML",)),
        ("form", '<form action="https://evil.example/"><input name="a"></form>', ("RAW_HTML",)),
        ("Liquid include", "{% include nonexistent_file.html %}", ("LIQUID",)),
        ("Liquid if", "{% if site.url %}보임{% endif %}", ("LIQUID",)),
        ("Liquid 출력", "{{ site.url }}", ("LIQUID",)),
    )

    def test_each_reproduced_input_is_blocked_with_its_own_reason(self):
        for name, payload, expected in self.REPRODUCED:
            with self.subTest(case=name):
                text = post_text(ss.ko_text(extra=payload))
                report = gate.run_gates(text)
                self.assertFalse(report.ok, name)
                for code in expected:
                    self.assertIn(code, report.codes(), f"{name}: {report.reasons}")
                error = ss.code_of(gate.require_gates, text)
                self.assertEqual(error.code, "CHECK_FAILED")
                for code in expected:
                    self.assertIn(code, error.slots["걸린 항목 목록"])

    def test_hidden_spellings_of_a_dangerous_address_are_found(self):
        for payload in ("[a](JaVaScRiPt:alert(1))", "[a](java&#x09;script:alert(1))", "[a](&#106;avascript:alert(1))", "[a](java&Tab;script:alert(1))", "[a](  javascript:alert(1))", "[a](<javascript:alert(1)>)",
                        "[a](java\nscript:alert(1))", "[a](vbscript:msgbox(1))", "[a](  DATA:text/html,x)", "[x][1]\n\n[1]: javascript:alert(1)", "<javascript:alert(1)>", "[a](j\u200bavascript:alert(1))",
                        "![a](data:image/svg+xml;base64,PHN2Zz4=)", "[a](&#x6A;&#x61;vascript&colon;alert(1))"):
            with self.subTest(payload=payload):
                self.assertIn("UNSAFE_URL", codes(ss.ko_text(extra=payload)), payload)

    def test_hidden_spellings_of_a_tag_are_found(self):
        for payload in ("<SCRIPT>alert(1)</SCRIPT>", "<script\n>alert(1)</script>", "<scr\u200bipt>alert(1)</script>", "<svg onload=alert(1)>", "<!-- 숨긴 말 -->", "<?php echo 1 ?>", "<a href=\"https://x.example\" onclick=\"y\">링크</a>",
                        "<br>", "<br/>", "</div>", "<o:p>x</o:p>", "<details><summary>더 보기</summary>내용</details>"):
            with self.subTest(payload=payload):
                self.assertIn("RAW_HTML", codes(ss.ko_text(extra=payload)), payload)

    def test_a_tag_whose_every_part_is_split_by_an_invisible_character_is_still_found(self):
        """닫는 태그까지 모두 쪼갠 것 — 한쪽이 멀쩡하면 그것만으로 걸리므로 시험이 보이지 않는 글자를 먼저 지우는 단계를 정말 지켜 주지 못한다(변이 G6)."""
        for payload in ("<scr​ipt>alert(1)</scr​ipt>", "<ima​g src=x onerror=alert(1)>", "<⁠script>alert(1)", "<if­rame src=https://evil.example/>", "<sㅤtyle>body{display:none}",
                        "<ins​ class=adsbygoogle>", "<​script src=x>"):
            with self.subTest(payload=payload):
                self.assertIn("RAW_HTML", codes(ss.ko_text(extra=payload)), payload)
                self.assertIn("RAW_HTML", [reason.split("]")[0].lstrip("[") for reason in gate.raw_markdown_problems(payload)], "본문 검사 함수가 직접")

    def test_template_tokens_and_attribute_lists_are_found_even_inside_code(self):
        for payload, code in (("```\n{{ page.title }}\n```", "LIQUID"), ("`{% raw %}`", "LIQUID"), ("{# 주석 #}", "LIQUID"), ("[링크](https://example.com){: onclick=\"alert(1)\"}", "KRAMDOWN"),
                              ("{::nomarkdown}x{:/nomarkdown}", "KRAMDOWN")):
            with self.subTest(payload=payload):
                self.assertIn(code, codes(ss.ko_text(extra=payload)), payload)

    def test_ad_scripts_are_found_in_any_case(self):
        for payload in ("window.AdsByGoogle", "pagead2.googlesyndication.com 에서", "&#97;dsbygoogle"):
            with self.subTest(payload=payload):
                self.assertIn("AD_SCRIPT", codes(ss.ko_text(extra=payload)), payload)

    def test_a_normal_post_passes_bold_links_images_lists_quotes_and_autolinks(self):
        normal = ("## 소제목\n\n**굵게** 와 _기울임_, [https 링크](https://example.com/a?b=1&c=2) 그리고 ![그림](https://images.example.invalid/a.jpg)\n\n"
                  "- 목록 하나\n- 목록 둘\n\n1. 순서 하나\n2. 순서 둘\n\n> 인용 문장입니다.\n\n자동 링크 <https://example.com/auto> 와 <mailto:a@example.com> 도 있습니다.\n\n"
                  "엔티티로 쓴 &lt;script&gt; 는 글자일 뿐입니다. 수식 1 < 2 이고 3 > 2 입니다. <이름> 처럼 한글 꺾쇠도 괜찮습니다.\n\n"
                  "책 이름은 JavaScript: The Good Parts 이고, Data: 2024 년 자료이며 [Data: 판매](https://example.com/data:foo) 입니다. 코드는 `print(1)` 입니다.\n\n---\n\n"
                  "| 열 | 값 |\n|---|---|\n| a | b |\n")
        report = gate.run_gates(post_text(ss.ko_text(extra=normal)))
        self.assertTrue(report.ok, report.reasons)
        self.assertEqual(gate.raw_markdown_problems(normal), [])

    def test_the_real_chance_posts_have_nothing_dangerous_in_their_original_text(self):
        for text in (KO_FIXTURE, EN_FIXTURE):
            self.assertEqual(gate.raw_markdown_problems(gate.split_post(text)[1]), [])

    def test_each_reason_says_what_to_do_in_plain_words(self):
        reasons = gate.raw_markdown_problems("<script>x</script> {{ a }} {: b } [x](javascript:y) adsbygoogle")
        self.assertEqual([reason.split("]")[0] for reason in reasons], ["[RAW_HTML", "[LIQUID", "[KRAMDOWN", "[UNSAFE_URL", "[AD_SCRIPT"])
        for reason in reasons:
            self.assertRegex(reason, "지운다|바꾼다|쓴다")


class WholeFlowBlocksTest(unittest.TestCase):
    """같은 검사를 연습 실행(미리 보기)·검토·승인·올리기 앞에서 모두 한다."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)
        self.payload = '\n\n<script async src="https://pagead2.googlesyndication.com/x.js"></script>\n\n{% include nonexistent_file.html %}\n\n[클릭](javascript:alert(1))'

    def test_preview_and_review_show_the_reasons_approval_and_publishing_refuse(self):
        view = projects.new_project(self.ctx, "위험한 글", ss.ko_text() + self.payload)
        preview = previews.preview_pages(self.ctx, view.project_id, ss.KO_PARAMS)
        self.assertFalse(preview.gates.ok)
        self.assertTrue({"RAW_HTML", "LIQUID", "UNSAFE_URL", "AD_SCRIPT"} <= set(preview.gates.codes()), preview.gates.reasons)
        code, out, err = ss.run_cli(self.ctx, "preview", view.project_id, "--platform", "pages", "--category", "경제·일", "--lang", "ko", "--image-url", "https://images.example.invalid/a.jpg")
        self.assertEqual(code, 0, err)
        for tag in ("[RAW_HTML]", "[LIQUID]", "[UNSAFE_URL]", "[AD_SCRIPT]"):
            self.assertIn(tag, out)
        self.assertIn("이대로는 승인·발행할 수 없습니다", out)
        review.request_review(self.ctx, view.project_id, "github_pages", pages=ss.KO_PARAMS)                  # 검토 요청은 보여 주기만 한다
        error = ss.code_of(review.grant_approval, self.ctx, view.project_id, "github_pages")
        self.assertEqual(error.code, "CHECK_FAILED")
        self.assertEqual(ss.status_of(self.ctx, view.project_id), st.REVIEW_REQUIRED)

    def test_publishing_checks_again_so_a_stored_approval_with_such_text_is_stopped(self):
        project_id = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.variants["github_pages"].rendered += "\n\n<iframe src=\"https://evil.example/\"></iframe>\n"
            store.save(project)
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "CHECK_FAILED")
            self.assertIn("RAW_HTML", error.slots["걸린 항목 목록"])
        self.assertEqual(self.backend.count("commit"), 0)


class LinearTimeTest(unittest.TestCase):
    def test_pathological_repeats_finish_quickly(self):
        for name, text in (("[a", "[a" * 100_000), ("![a](", "![a](" * 40_000), ("<a", "<a" * 100_000), ("[", "[" * 200_000), ("](", "](" * 100_000), ("!", "![" * 100_000)):
            with self.subTest(case=name):
                started = time.monotonic()
                gate.readable_chars(text)
                gate.raw_markdown_problems(text)
                self.assertLess(time.monotonic() - started, 8, f"{name} 반복이 오래 걸린다")


if __name__ == "__main__":
    unittest.main()
