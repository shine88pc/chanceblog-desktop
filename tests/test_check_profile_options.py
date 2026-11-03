"""네이버 프로필의 '글 만들 때 쓰는 항목' 중 점검에 쓰이는 것(소제목 수 범위·제외 주제) 시험 — `check/profile_options.py` 와 그것을 복사 패키지의 경고에 덧붙이는 `service/naver_flow.build_for_blog`.

지키는 것:
  1) 소제목 수(`#`~`#####` 제목 줄 하나가 하나, 코드 블록 안·HTML 글자는 아님)가 프로필의 하한~상한을 벗어나면 경고하고, 경계(하한·상한 그대로)는 경고하지 않는다.
  2) 제외 주제 낱말이 제목이나 본문에 있으면(대소문자·띄어쓰기 무시) 경고한다 — 이미지 표시·AI 활용 고지문 속의 글자는 보지 않는다.
  3) 경고만 한다 — 복사용 글을 내어 주는 것도 승인도 막지 않는다. 기존 경고(금지 표현·글 길이 …)는 그대로이고 새 경고는 그 뒤에 붙는다.
  4) 도입부 스타일·설명 난이도·마무리 방식·기본 글 유형·같은 주제 재사용 기준은 점검이 읽지 않는다(저장만). `build_package`(순수 변환)는 새 항목을 읽지 않는다.
"""
import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.check import profile_options as po  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.render.naver import build_package  # noqa: E402
from chanceblog_desktop.service import naver_flow, previews, projects, review  # noqa: E402
from chanceblog_desktop.service.naver_flow import NaverOptions  # noqa: E402

GOOD = {"key": "naver_a", "display_name": "블로그 A", "blog_url": "https://blog.naver.com/example_a", "min_chars": 0}


def profile(**changes):
    return NaverProfile(**{**GOOD, **changes})


def headed(count, level="##", paragraph="본문 한 문단입니다."):
    """제목 줄 `count` 개와 그 아래 문단들로 된 글."""
    if count == 0:
        return "\n\n".join([paragraph] * 3)
    return "\n\n".join(f"{level} 소제목 {index}\n\n{paragraph}" for index in range(1, count + 1))


def package(body, title="제목", **changes):
    return build_package(profile(**changes), title=title, body=body, tags=("태그",))


def warnings_for(body, title="제목", **changes):
    chosen = profile(**changes)
    return po.option_warnings(chosen, build_package(chosen, title=title, body=body, tags=("태그",)))


def said(topic, where):
    """제외 주제 경고 문장 — `where` 는 '제목' 이나 '본문'."""
    return f"제외 주제 「{topic}」 이(가) {where}에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다."


class CountingTest(unittest.TestCase):
    def test_only_h2_to_h4_tags_count(self):
        for html, expected in (("", 0), ("<p>글</p>", 0), ("<h2>a</h2>", 1), ("<h2>a</h2><p>x</p><h3>b</h3><h4>c</h4>", 3), ("<h1>a</h1><h5>b</h5><h6>c</h6>", 0), ("<h2>a</h2><h2>b</h2>", 2),
                               ("<blockquote><h2>a</h2></blockquote>", 1), ("&lt;h2&gt;글자&lt;/h2&gt;", 0), ("<h22>x</h22>", 0), ("<hr>", 0)):
            with self.subTest(html=html):
                self.assertEqual(po.subheading_count(html), expected)

    def test_every_title_line_level_counts_once_in_a_real_conversion(self):
        for level in ("#", "##", "###", "####", "#####"):
            with self.subTest(level=level):
                self.assertEqual(po.subheading_count(package(headed(3, level)).body_html), 3)

    def test_what_is_not_a_title_line_is_not_counted(self):
        for label, body, expected in (("코드 블록 안", "본문\n\n```\n## 코드 안\n```\n\n## 진짜\n\n본문", 1), ("빈 제목 줄", "##\n\n본문 ##\n\n## \n\n본문", 0), ("밑줄로 쓴 제목", "제목\n===\n\n본문", 0),
                                      ("HTML 글자", "<h2>태그</h2>\n\n본문", 0), ("인용 속 제목은 보이는 제목이다", "> ## 인용 안\n> 글\n\n본문", 1), ("번호 목록", "1. 하나\n2. 둘\n3. 셋", 0)):
            with self.subTest(label=label):
                self.assertEqual(po.subheading_count(package(body).body_html), expected)


class SubheadingRangeTest(unittest.TestCase):
    def test_the_boundaries_are_exact_for_several_ranges(self):
        for low, high in ((3, 5), (1, 1), (2, 2), (1, 20), (5, 5), (4, 6)):
            for count in range(0, 23):
                with self.subTest(low=low, high=high, count=count):
                    found = [item for item in warnings_for(headed(count), subheading_min=low, subheading_max=high) if item.startswith("소제목이")]
                    if low <= count <= high:
                        self.assertEqual(found, [])
                    else:
                        self.assertEqual(len(found), 1)
                        span = f"{low}개" if low == high else f"{low}~{high}개"
                        direction = "적습니다" if count < low else "많습니다"
                        self.assertEqual(found[0], f"소제목이 {count}개입니다 — 이 블로그의 기준({span})보다 {direction}.")

    def test_the_default_range_is_three_to_five(self):
        self.assertEqual([bool(warnings_for(headed(count))) for count in range(0, 8)], [True, True, True, False, False, False, True, True])
        self.assertEqual(warnings_for(headed(0)), ("소제목이 0개입니다 — 이 블로그의 기준(3~5개)보다 적습니다.",))
        self.assertEqual(warnings_for(headed(6)), ("소제목이 6개입니다 — 이 블로그의 기준(3~5개)보다 많습니다.",))

    def test_a_post_with_no_title_line_at_all_is_below_every_range(self):
        for low in (1, 2, 7):
            self.assertEqual(len(warnings_for(headed(0), subheading_min=low, subheading_max=max(low, 7))), 1)


class ExcludedTopicsTest(unittest.TestCase):
    def test_a_word_in_the_title_the_body_or_both_is_named_with_where(self):
        for title, body, expected in (("주식 투자 입문", "본문 한 문단입니다.", ["제외 주제 「주식」 이(가) 제목에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다."]),
                                      ("제목", "오늘은 주식 이야기를 합니다.", ["제외 주제 「주식」 이(가) 본문에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다."]),
                                      ("주식 입문", "주식 이야기.", ["제외 주제 「주식」 이(가) 제목에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다.",
                                                                      "제외 주제 「주식」 이(가) 본문에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다."]),
                                      ("제목", "아무 상관 없는 글.", [])):
            with self.subTest(title=title):
                found = [item for item in warnings_for(headed(4, paragraph=body), title=title, excluded_topics=("주식",)) if item.startswith("제외 주제")]
                self.assertEqual(found, expected)

    def test_each_topic_is_checked_in_the_profile_order_title_first(self):
        def said(topic, where):
            return f"제외 주제 「{topic}」 이(가) {where}에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다."

        found = warnings_for(headed(4, paragraph="코인과 주식 이야기"), title="코인 소개", excluded_topics=("주식", "코인", "부동산"))
        self.assertEqual(found, (said("주식", "본문"), said("코인", "제목"), said("코인", "본문")))

    def test_case_and_spacing_do_not_hide_a_topic(self):
        for topic, body in (("Bitcoin", "I like BITCOIN a lot"), ("가상 자산", "가상    자산 시장"), ("가상 자산", "가상\n자산 시장"), ("가상 자산", "가상  \n자산 시장"), ("주식", "주식"), ("STOCK", "stock")):
            with self.subTest(topic=topic, body=body):
                self.assertTrue([item for item in warnings_for(headed(4, paragraph=body), excluded_topics=(topic,)) if item.startswith("제외 주제")])

    def test_full_width_letters_and_digits_and_a_topic_written_joined_or_apart_are_the_same_word(self):
        """전각(`ＡＩ`·`２０２５`)과 반각, 띄어 쓴 것과 붙여 쓴 것을 같은 낱말로 본다(경고일 뿐이라 놓치는 쪽이 더 나쁘다)."""
        for topic, body in (("AI", "ＡＩ 시대의 투자"), ("ＡＩ", "AI 시대의 투자"), ("2025", "２０２５년 전망"), ("２０２５", "2025년 전망"), ("가상 자산", "가상자산 시장"), ("가상자산", "가상 자산 시장"),
                            ("가상 자산", "가 상 자 산 시장"), ("ＡＩ 투자", "ai투자 이야기"), ("Bit coin", "BITCOIN 가격")):
            with self.subTest(topic=topic, body=body):
                found = [item for item in warnings_for(headed(4, paragraph=body), excluded_topics=(topic,)) if item.startswith("제외 주제")]
                self.assertEqual(found, [said(topic, "본문")])
        titled = [item for item in warnings_for(headed(4), title="ＡＩ 투자 입문", excluded_topics=("ai 투자",)) if item.startswith("제외 주제")]
        self.assertEqual(titled, [said("ai 투자", "제목")])

    def test_a_different_word_is_not_caught_by_the_wider_comparison(self):
        for topic, body in (("AI", "인공 지능 이야기"), ("2025", "2024년 전망"), ("가상 자산", "가상 현실"), ("코인", "코스피 인덱스")):
            with self.subTest(topic=topic):
                self.assertEqual([item for item in warnings_for(headed(4, paragraph=body), excluded_topics=(topic,)) if item.startswith("제외 주제")], [])

    def test_a_longer_word_that_merely_contains_the_topic_still_counts_but_a_split_word_does_not(self):
        self.assertTrue(warnings_for(headed(4, paragraph="주식시장 전망"), excluded_topics=("주식",)) != ())
        self.assertEqual([item for item in warnings_for(headed(4, paragraph="가상 자산"), excluded_topics=("가자",)) if item.startswith("제외 주제")], [])

    def test_the_ai_notice_and_the_image_markers_are_not_looked_at(self):
        from chanceblog_desktop.content.model import Asset
        chosen = profile(excluded_topics=("도구", "그림파일"))
        built = build_package(chosen, title="제목", body=headed(4), tags=("태그",), assets=(Asset("그림파일.png", "설명", 1),))
        self.assertIn("AI 도구의 도움", built.body_html, "고지문은 패키지에 붙는다")
        self.assertIn("그림파일.png", built.body_html, "이미지 표시도 붙는다")
        self.assertEqual(po.option_warnings(chosen, built), ())

    def test_no_topics_means_no_such_warning(self):
        self.assertEqual([item for item in warnings_for(headed(4, paragraph="주식 코인 부동산")) if item.startswith("제외 주제")], [])


class NotReadByTheCheckTest(unittest.TestCase):
    def test_the_other_new_items_change_nothing(self):
        body = headed(4)
        base = warnings_for(body)
        for changes in ({"intro_style": "독자의 고민으로 시작"}, {"difficulty": "쉽게"}, {"ending_style": "세 줄 요약"}, {"post_type": "비교형"}, {"topic_reuse_days": 0}, {"topic_reuse_days": 3650}):
            with self.subTest(changes=changes):
                self.assertEqual(warnings_for(body, **changes), base)
                self.assertEqual(package(body, **changes), package(body), "변환 결과도 같다")

    def test_the_conversion_itself_still_ignores_the_range_and_the_excluded_topics(self):
        body = headed(7, paragraph="주식 이야기")
        plain, strict = package(body), package(body, subheading_min=1, subheading_max=2, excluded_topics=("주식",), title="주식")
        self.assertEqual(plain.warnings, strict.warnings, "build_package 의 경고에는 이 항목들이 들어가지 않는다 — 서비스 층이 덧붙인다")
        self.assertEqual(dataclasses.replace(plain, title="x", warnings=()), dataclasses.replace(strict, title="x", warnings=()))


class ServiceFlowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.ctx = ss.make_ctx(tmp.name)
        ss.naver_profiles(self.ctx, both=False)

    def project(self, body, title="에너지 절약 습관"):
        return projects.new_project(self.ctx, title, body).project_id

    def test_build_for_blog_appends_the_new_warnings_after_the_old_ones_and_changes_nothing_else(self):
        options = {**GOOD, "min_chars": 5000, "max_chars": 6000, "forbidden_phrases": ("에너지",), "default_tags": ("생활",)}
        view = projects.new_project(self.ctx, "에너지 절약 습관", ss.ko_text())
        with self.ctx.store() as store:
            project = store.load(view.project_id)
        plain_profile, strict_profile = NaverProfile(**options), NaverProfile(**{**options, "excluded_topics": ("습관",)})
        old = build_package(plain_profile, title=project.title, body=project.source_content, tags=(), assets=project.assets).warnings
        self.assertEqual([item for item in old if item.startswith("금지 표현")], ["금지 표현 「에너지」 이(가) 제목에 있습니다.", "금지 표현 「에너지」 이(가) 본문에 있습니다."])
        self.assertTrue(any("보다 짧습니다" in item for item in old))
        no_heading = "소제목이 0개입니다 — 이 블로그의 기준(3~5개)보다 적습니다."
        plain, built = naver_flow.build_for_blog(plain_profile, project), naver_flow.build_for_blog(strict_profile, project)
        self.assertEqual(plain.warnings, old + (no_heading,), "새 경고는 변환이 만든 경고 뒤에 붙는다")
        self.assertEqual(built.warnings, old + (no_heading, "제외 주제 「습관」 이(가) 제목에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다.",
                                                "제외 주제 「습관」 이(가) 본문에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다."))
        self.assertEqual(dataclasses.replace(built, warnings=()), dataclasses.replace(plain, warnings=()), "경고 말고는 변환 결과가 그대로다")

    def test_a_post_that_raises_no_new_warning_comes_back_exactly_as_the_conversion_made_it(self):
        project = dataclasses.replace(projects.new_project(self.ctx, "제목", headed(4)), source_content=headed(4))
        with self.ctx.store() as store:
            stored = store.load(project.project_id)
        chosen = NaverProfile(**{**GOOD, "default_tags": ("생활",)})
        self.assertEqual(naver_flow.build_for_blog(chosen, stored), build_package(chosen, title=stored.title, body=stored.source_content, tags=(), assets=stored.assets))

    def test_review_preview_and_the_copy_text_show_the_new_warnings_and_nothing_is_blocked(self):
        chosen = NaverProfile("naver_a", "블로그 에이", "https://blog.naver.com/exampleaaa", default_tags=("생활",), min_chars=10, max_chars=20000, excluded_topics=("습관",))
        self.ctx.settings.save_naver_profile(chosen)
        project_id = self.project(ss.ko_text())
        result = review.request_review(self.ctx, project_id, "naver_a")
        warnings = result.naver.package.warnings
        self.assertEqual(warnings[:2], ("소제목이 0개입니다 — 이 블로그의 기준(3~5개)보다 적습니다.", "제외 주제 「습관」 이(가) 제목에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다."))
        shown = previews.preview_naver(self.ctx, project_id, {})
        self.assertIn(warnings[0], shown.items[0].package.warnings)
        issued = review.issue_naver_package(self.ctx, project_id, "naver_a")
        self.assertEqual(issued.status, "READY_TO_COPY", "경고는 막지 않는다")
        text = naver_flow.copy_text(issued.package)
        self.assertIn("[주의]", text)
        self.assertIn("- 소제목이 0개입니다", text)

    def test_a_post_that_fits_the_range_has_no_new_warning(self):
        project_id = self.project("\n\n".join(f"## 소제목 {n}\n\n{ss.ko_text(400)}" for n in range(1, 5)))
        warnings = review.request_review(self.ctx, project_id, "naver_a").naver.package.warnings
        self.assertEqual([item for item in warnings if item.startswith(("소제목이", "제외 주제"))], [])

    def test_the_options_of_the_other_blog_are_not_used(self):
        ss.naver_profiles(self.ctx)
        self.ctx.settings.save_naver_profile(NaverProfile("naver_b", "블로그 비", "https://blog.naver.com/examplebbb", default_tags=("정보",), min_chars=10, max_chars=20000, subheading_min=1, subheading_max=1))
        project_id = self.project("## 하나\n\n" + ss.ko_text(600))
        a = review.request_review(self.ctx, project_id, "naver_a").naver.package.warnings
        b = review.request_review(self.ctx, project_id, "naver_b").naver.package.warnings
        self.assertTrue(any(item.startswith("소제목이 1개입니다") for item in a))
        self.assertEqual([item for item in b if item.startswith("소제목이")], [])

    def test_the_stored_package_keeps_the_warnings_so_the_copy_text_is_the_reviewed_one(self):
        project_id = self.project(ss.ko_text())
        review.request_review(self.ctx, project_id, "naver_a")
        self.ctx.settings.save_naver_profile(NaverProfile("naver_a", "블로그 에이", "https://blog.naver.com/exampleaaa", default_tags=("생활",), min_chars=10, max_chars=20000, excluded_topics=("습관",)))
        issued = review.issue_naver_package(self.ctx, project_id, "naver_a")
        self.assertTrue(any(item.startswith("소제목이 0개입니다") for item in issued.package.warnings))
        self.assertEqual([item for item in issued.package.warnings if item.startswith("제외 주제")], [], "검토한 그 패키지가 그대로 나간다 — 프로필을 나중에 바꿔도 다시 만들지 않는다")

    def test_the_command_line_review_prints_the_new_warning_line(self):
        project_id = self.project(ss.ko_text())
        code, out, err = ss.run_cli(self.ctx, "review", project_id, "--platform", "naver_a")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("  주의: 소제목이 0개입니다 — 이 블로그의 기준(3~5개)보다 적습니다.", out)


if __name__ == "__main__":
    unittest.main()
