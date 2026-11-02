"""서비스 층 — 발행 전 검사(게이트) 시험. 승인한 글 한 편이 올라가도 되는지 보는 규칙이 하나라도 걸리면 막는다(fail closed).

지키는 것:
  1) 실제 Chance 글 두 편(`tests/fixtures/`)과, 글자 수·언어 비율을 채운 글은 통과한다.
  2) 본문이 짧거나·언어가 어긋나거나·AI 가 흘린 자기 소개·템플릿 잔여물이 있거나·이 PC 의 폴더 경로(`C:/Users/…`·데이터 폴더·저장소 폴더)가 들어 있으면 CHECK_FAILED.
  3) 키 모양 문자열·깨진 머리말은 그 오류 코드 그대로(고치기 전에는 아무것도 못 한다) — 보고서에도 오류에도 키 글자가 나오지 않는다.
  4) `run_gates` 는 예외를 내지 않고 `require_gates` 가 막을지 정한다.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content.model import ContentProject  # noqa: E402
from chanceblog_desktop.render.pages import render_pages_post  # noqa: E402
from chanceblog_desktop.service import gate  # noqa: E402

FIXTURES = ss.ROOT / "tests" / "fixtures"
KO_FIXTURE = (FIXTURES / "chance_post_ko.md").read_text(encoding="utf-8")
EN_FIXTURE = (FIXTURES / "chance_post_en.md").read_text(encoding="utf-8")


def post_text(body, *, lang="ko", title="제목", params=None):
    project = ContentProject.new(title, body, now="2026-11-02T00:00:00Z")
    params = params or (ss.KO_PARAMS if lang == "ko" else ss.EN_PARAMS)
    return render_pages_post(project, category=params.category, lang=lang, image_url=params.image_url, tags=params.tags, now=ss.NOW).text


class PassingTest(unittest.TestCase):
    def test_the_two_real_chance_posts_pass(self):
        for name, text in (("한글", KO_FIXTURE), ("영문", EN_FIXTURE)):
            with self.subTest(post=name):
                report = gate.run_gates(text)
                self.assertTrue(report.ok, report.reasons)
                self.assertEqual((report.reasons, report.warnings, report.blocking), ((), (), None))
                self.assertGreater(report.chars, 1000)

    def test_a_long_enough_post_in_the_right_language_passes_and_require_returns_the_report(self):
        for lang, body in (("ko", ss.ko_text()), ("en", ss.en_text())):
            with self.subTest(lang=lang):
                text = post_text(body, lang=lang, title="A title" if lang == "en" else "제목")
                self.assertTrue(gate.run_gates(text).ok)
                self.assertTrue(gate.require_gates(text).ok)

    def test_the_minimum_length_is_the_one_the_cloud_generator_uses(self):
        self.assertEqual(gate.LENGTH_MIN, {"ko": 1000, "en": 1500})
        self.assertEqual(gate.gate_profile("ko")["length"], {"min_chars": 1000})
        self.assertEqual(gate.gate_profile("en")["length"], {"min_chars": 1500})

    def test_the_report_converts_to_plain_data(self):
        data = gate.run_gates(KO_FIXTURE).to_dict()
        self.assertEqual(sorted(data), ["chars", "ok", "reasons", "warnings"])


class BlockingTest(unittest.TestCase):
    def test_a_short_post_is_check_failed_and_says_how_short(self):
        text = post_text("짧은 글입니다. " * 20)
        report = gate.run_gates(text)
        self.assertFalse(report.ok)
        self.assertIn("LEN_SHORT", report.codes())
        error = ss.code_of(gate.require_gates, text)
        self.assertEqual(error.code, "CHECK_FAILED")
        self.assertIn("LEN_SHORT", error.slots["걸린 항목 목록"])
        self.assertIn("최소 1000자", error.detail)

    def test_the_minimum_is_counted_the_way_the_cloud_generator_counts_without_spaces(self):
        """공백을 한 칸씩 세면 1000자가 넘지만 공백을 빼면 모자란 글 — 핵심 코드의 글자 수만으로는 통과하지만 생성기와 같은 계산에는 걸린다."""
        body = "가 " * 520
        text = post_text(body)
        report = gate.run_gates(text)
        self.assertNotIn("LEN_SHORT", report.codes(), "공백 포함으로는 충분하다")
        self.assertIn("LEN_BODY", report.codes())
        self.assertEqual(gate.readable_chars(body), 520)
        error = ss.code_of(gate.require_gates, text)
        self.assertEqual(error.code, "CHECK_FAILED")
        self.assertIn("본문(출처 목록·공백·보이지 않는 글자 제외) 520자 (최소 1000자", error.detail)

    def test_the_source_list_does_not_count_toward_the_minimum(self):
        story = "가나다라마바사아자차카타파하 " * 40                              # 공백 제외 560자
        sources = "\n".join(f"- [출처 {number}](https://example.com/{number})" for number in range(300))      # 목록 쪽 글자만으로도 1000자를 훌쩍 넘는다
        self.assertGreater(gate.readable_chars(sources), 1000)
        for heading in ("## 출처", "## 참고 자료", "## Sources", "## sources", "##출처", "##   SOURCES"):
            with self.subTest(heading=heading):
                text = post_text(story + f"\n\n{heading}\n{sources}\n")
                self.assertEqual(gate.readable_chars(story + f"\n\n{heading}\n{sources}\n"), 560, "출처 목록 앞의 글만 센다")
                self.assertIn("LEN_BODY", gate.run_gates(text).codes())
        self.assertGreater(gate.readable_chars(story + f"\n\n### 출처 아님\n{sources}"), 1000, "`###` 소제목은 출처 목록의 시작이 아니라 본문이다")

    def test_a_heading_that_is_not_at_the_start_of_a_line_does_not_end_the_story(self):
        story = "가나다라마바사아자차카타파하 " * 40
        rest = "라마바사아자차카타파하가나다 " * 60                                  # 공백 제외 780자 — 합치면 1340자
        for line in ("참고로 ## 출처", " ## 출처", "\t## 출처", "- ## Sources"):
            with self.subTest(line=line):
                self.assertEqual(gate.readable_chars(story + f"\n\n{line}\n{rest}\n") > 1000, True)
                self.assertNotIn("LEN_BODY", gate.run_gates(post_text(story + f"\n\n{line}\n{rest}\n")).codes())

    def test_images_links_tags_and_markdown_symbols_are_stripped_before_counting(self):
        body = "![그림 설명](https://x.example/a.png)\n\n[글자만 센다](https://x.example/long/long/long/long)\n\n<b>태그</b> **굵게** _기울임_ `코드` > 인용 # 제목 | 표 ~ 물결"
        self.assertEqual(gate.readable_chars(body), len("글자만센다") + len("태그") + len("굵게") + len("기울임") + len("코드") + len("인용") + len("제목") + len("표") + len("물결"))
        self.assertEqual(gate.readable_chars(""), 0)

    def test_the_real_chance_posts_meet_the_cloud_minimum_exactly_as_counted(self):
        for name, text, minimum in (("한글", KO_FIXTURE, 1000), ("영문", EN_FIXTURE, 1500)):
            with self.subTest(post=name):
                self.assertGreaterEqual(gate.readable_chars(gate.split_post(text)[1]), minimum)

    def test_the_english_minimum_is_higher_than_the_korean_one(self):
        body = "A reasonably long english sentence about saving energy at home. " * 18          # 1100자쯤 — 한글 기준은 넘지만 영문 기준(1500)에는 모자란다
        self.assertIn("LEN_SHORT", gate.run_gates(post_text(body, lang="en", title="Energy")).codes())

    def test_the_wrong_language_is_check_failed(self):
        self.assertIn("LANG", gate.run_gates(post_text(ss.en_text(), lang="ko")).codes())
        self.assertIn("LANG", gate.run_gates(post_text(ss.ko_text(), lang="en", title="English title")).codes())

    def test_text_an_ai_left_behind_is_check_failed(self):
        for phrase in ("AI 언어 모델로서 답변드립니다.", "As an AI language model, I cannot do that.", "Lorem ipsum dolor sit amet", "{topic} 에 대해 씁니다", "[대상: 독자]", "제목: 이런 줄"):
            with self.subTest(phrase=phrase):
                text = post_text(ss.ko_text(extra=phrase))
                self.assertIn("LEAK", gate.run_gates(text).codes())

    def test_words_that_are_fine_in_a_magazine_are_not_flagged(self):
        """chanceblog 의 건강 블로그 프로필이 막는 낱말('language model'·'todo')을 이 앱은 막지 않는다 — 정책을 새로 만들지 않는다."""
        text = post_text(ss.en_text(2200) + "\n\nA large language model and the Mastodon network are not an AI persona leaking.", lang="en", title="Models")
        self.assertTrue(gate.run_gates(text).ok, gate.run_gates(text).reasons)

    def test_a_path_of_this_pc_in_the_text_is_check_failed(self):
        for leak in (r"C:\Users\운영자\Desktop\원고.md", "c:/users/someone/x", r"D:\Documents and Settings\x"):
            with self.subTest(leak=leak):
                text = post_text(ss.ko_text(extra=f"원본은 {leak} 에 있습니다."))
                self.assertIn("LOCAL_PATH", gate.run_gates(text).codes())

    def test_the_data_folder_and_the_connected_folder_are_not_allowed_in_the_text_either(self):
        text = post_text(ss.ko_text(extra="저장 위치는 /srv/example/내데이터/chanceblog 입니다."))
        self.assertTrue(gate.run_gates(text).ok)
        paths = ("/srv/example/내데이터/chanceblog",)
        self.assertIn("LOCAL_PATH", gate.run_gates(text, local_paths=paths).codes())
        windows = post_text(ss.ko_text(extra=r"위치는 E:\work\내폴더\chanceblog 입니다."))
        self.assertIn("LOCAL_PATH", gate.run_gates(windows, local_paths=(r"E:\work\내폴더\chanceblog",)).codes())
        self.assertIn("LOCAL_PATH", gate.run_gates(windows.replace("\\", "/"), local_paths=(r"E:\work\내폴더\chanceblog",)).codes(), "역슬래시와 슬래시를 같게 본다")

    def test_very_short_or_empty_paths_are_ignored_so_a_root_folder_cannot_flag_everything(self):
        text = post_text(ss.ko_text())
        self.assertTrue(gate.run_gates(text, local_paths=("", "/", "C:", "abc")).ok)

    def test_a_key_shaped_string_keeps_its_own_code_and_never_appears_in_any_output(self):
        text = post_text(ss.ko_text(extra=f"실수로 {ss.KEY} 를 붙였습니다."))
        report = gate.run_gates(text)
        self.assertFalse(report.ok)
        self.assertEqual(report.blocking.code, "SECRET_IN_TEXT_BLOCKED")
        self.assertNotIn(ss.KEY, " ".join(report.reasons + report.warnings))
        error = ss.code_of(gate.require_gates, text)
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
        self.assertNotIn(ss.KEY, error.detail + error.log_line() + str(error))

    def test_a_broken_header_is_content_invalid_and_run_gates_does_not_raise(self):
        for text in ("머리말이 없는 글\n", "---\nlayout: post\n---\n\n본문\n", KO_FIXTURE.replace("lang: ko", "lang: fr"), ""):
            with self.subTest(text=text[:20]):
                report = gate.run_gates(text)
                self.assertFalse(report.ok)
                self.assertEqual(report.blocking.code, "CONTENT_INVALID")
                self.assertEqual(ss.code_of(gate.require_gates, text).code, "CONTENT_INVALID")

    def test_a_post_the_converter_refuses_is_reported_not_raised(self):
        text = post_text(ss.ko_text())
        with mock.patch.object(gate, "markdown_to_html", side_effect=gate.AppError("CONTENT_INVALID", {"항목": "본문"}, detail="너무 크다")):
            report = gate.run_gates(text)
        self.assertFalse(report.ok)
        self.assertTrue(any(reason.startswith("[BODY]") for reason in report.reasons))

    def test_too_many_tags_are_refused_by_the_core_check(self):
        text = post_text(ss.ko_text())
        many = text.replace('tags: ["에너지", "생활"]', "tags: " + str([f"태그{n}" for n in range(11)]).replace("'", '"'))
        self.assertIn("LABELS", gate.run_gates(many).codes())


class SplitPostTest(unittest.TestCase):
    def test_the_header_values_and_the_body_are_read_back(self):
        header, body = gate.split_post(KO_FIXTURE)
        self.assertEqual((header["layout"], header["lang"], header["category"]), ("post", "ko", "경제·일"))
        self.assertEqual(header["tags"][:2], ["에너지안보", "정유산업"])
        self.assertTrue(header["image"].startswith("https://"))
        self.assertTrue(body.startswith("에너지 전환 정책의"))
        self.assertFalse(body.startswith("\n"))

    def test_a_blank_line_inside_the_header_is_allowed(self):
        text = KO_FIXTURE.replace("layout: post\n", "layout: post\n\n", 1)
        self.assertEqual(gate.split_post(text)[0]["layout"], "post")
        self.assertTrue(gate.run_gates(text).ok)

    def test_a_post_without_tags_has_an_empty_list(self):
        text = post_text(ss.ko_text(), params=ss.PagesParams("경제·일", "ko", "https://images.example.invalid/a.jpg"))
        self.assertEqual(gate.split_post(text)[0]["tags"], [])

    def test_a_bad_json_value_is_content_invalid(self):
        text = post_text(ss.ko_text()).replace('title: "제목"', "title: 제목")
        self.assertEqual(ss.code_of(gate.split_post, text).code, "CONTENT_INVALID")


if __name__ == "__main__":
    unittest.main()
