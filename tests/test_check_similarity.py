"""네이버 A·B 유사도 비교 시험 — 같은 글은 '높음', 같은 주제를 다르게 쓴 글은 '괜찮음', 일부만 고친 복사본은 '높음' 으로 알리고, 점수는 0~1·순서 무관·항목마다 정해진 기준에서 단계가 바뀐다.

지키는 것:
  1) 정규화(NFKC·구두점·공백 제거)와 3글자 묶음·Jaccard·편집 거리 비율의 모서리(빈 글·짧은 글·둘 다 빈 것).
  2) 점수는 0~1, 두 글의 순서를 바꿔도 같고, 가중치 합은 1 이다. 같은 글은 본문·제목·도입부가 1.0 이다.
  3) 항목(전체·본문·제목·도입부)마다 기준 **이상**이면 단계가 바뀐다(경계 포함). 가장 높은 단계가 이긴다. 이유 문장에 항목 이름과 백분율이 나온다.
  4) `check_pair` 는 높음이면 직접 승인(approved) 없이는 NAVER_SIMILARITY_HIGH 로 거절하고, 승인하면 보고서를 돌려준다.
  5) 패키지(`render/naver.py`)에서 바로 만들 수 있고, 아주 긴 글도 빨리 끝난다. 네트워크·파일 없이 돈다.
"""
import difflib
import random
import sys
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.check import Comparable, SimilarityReport, Thresholds, check_pair, compare  # noqa: E402
from chanceblog_desktop.check import similarity as sim  # noqa: E402
from chanceblog_desktop.content import Asset  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.render.naver import build_package  # noqa: E402

A = ("아침에 일어나면 먼저 물 한 컵을 마시고 가벼운 스트레칭으로 몸을 풀어 줍니다. 창문을 열어 환기를 하고 하루 계획을 간단히 적어 봅니다.\n\n"
     "출근 전에는 따뜻한 아침을 챙겨 먹는 것이 좋습니다. 단백질과 채소를 함께 먹으면 오전 내내 속이 편안합니다.\n\n"
     "저녁에는 일찍 불을 줄이고 휴대전화를 멀리 두면 숙면에 도움이 됩니다.")
B = ("하루를 상쾌하게 시작하려면 기상 직후 미지근한 물을 천천히 마시는 습관이 도움이 됩니다. 이어서 목과 어깨를 돌려 굳은 근육을 깨워 줍니다.\n\n"
     "아침 식사는 거르지 말고 계란이나 두부 같은 단백질에 샐러드를 곁들이면 좋습니다. 점심까지 든든하게 버틸 수 있습니다.\n\n"
     "밤에는 조명을 낮추고 스마트폰 사용을 줄이면 잠들기가 한결 쉬워집니다.")
COPY = A.replace("아침에 일어나면 먼저 물 한 컵을 마시고 가벼운 스트레칭으로 몸을 풀어 줍니다.", "눈을 뜨면 곧바로 물을 마시고 몸을 가볍게 폅니다.")


class HelperTest(unittest.TestCase):
    def test_normalizing_keeps_letters_and_digits_only_in_one_case_and_width(self):
        self.assertEqual(sim.normalize("  Hello, 세계! 123 _x_ "), "hello세계123x")
        self.assertEqual(sim.normalize("ＡＢＣ １２３"), "abc123", "전각은 NFKC 로")
        self.assertEqual(sim.normalize("가\u200b나\n다\t라 ... —"), "가나다라".replace("\u200b", ""))
        self.assertEqual((sim.normalize(""), sim.normalize(None), sim.normalize(5)), ("", "", "5"))

    def test_grams_are_three_letter_pieces_and_short_texts_are_one_piece(self):
        self.assertEqual(sim._grams("가나다라"), {"가나다", "나다라"})
        self.assertEqual(sim._grams("가나다"), {"가나다"})
        self.assertEqual(sim._grams("가나"), {"가나"})
        self.assertEqual(sim._grams(""), set())
        self.assertEqual(sim._grams("가가가가"), {"가가가"})

    def test_jaccard_and_ratio_edges(self):
        self.assertEqual(sim._jaccard({1, 2}, {2, 3}), 1 / 3)
        self.assertEqual(sim._jaccard({1}, {1}), 1.0)
        self.assertEqual((sim._jaccard(set(), {1}), sim._jaccard({1}, set()), sim._jaccard(set(), set())), (0.0, 0.0, 0.0), "둘 다 비면 겹친다고 하지 않는다")
        self.assertEqual(sim._ratio("가나다", "가나다"), 1.0)
        self.assertEqual((sim._ratio("", "가"), sim._ratio("가", ""), sim._ratio("", "")), (0.0, 0.0, 0.0))
        self.assertEqual(sim._ratio("가나다라", "마바사아"), 0.0)
        self.assertEqual(sim._ratio([1, 2, 3], [1, 2, 3]), 1.0)

    def test_the_weights_add_up_to_one_and_name_the_six_items(self):
        self.assertAlmostEqual(sum(sim.WEIGHTS.values()), 1.0)
        self.assertEqual(sorted(sim.WEIGHTS), ["body", "images", "intro", "structure", "tags", "title"])

    def test_paragraph_shape_is_the_length_bucket_of_each_paragraph(self):
        self.assertEqual(sim._shape("가" * 5 + "\n\n" + "가" * 45 + "\n\n" + "가" * 5000), [0, 1, sim.MAX_BUCKET])
        self.assertEqual(sim._shape(""), [])
        self.assertEqual(sim._shape("\n\n \n\n"), [])

    def test_identities_and_tags_are_compared_without_case_or_marks(self):
        self.assertEqual(sim._identities(["A.PNG", " a.png ", "", "  "]), {"a.png"})
        self.assertEqual(sim._tags(["#건강", "건강", "Health!", ""]), {"건강", "health"})


class ScoreTest(unittest.TestCase):
    def test_the_same_text_is_a_perfect_match_and_needs_approval(self):
        report = compare(Comparable("아침 루틴", A), Comparable("아침 루틴", A))
        self.assertEqual((report.title, report.intro, report.body, report.structure), (1.0, 1.0, 1.0, 1.0))
        self.assertEqual((report.images, report.tags), (0.0, 0.0), "이미지·태그가 둘 다 없으면 겹친다고 보지 않는다")
        self.assertEqual((report.level, report.needs_approval), ("high", True))
        self.assertIsInstance(report, SimilarityReport)

    def test_two_different_ways_of_writing_the_same_topic_are_fine(self):
        report = compare(Comparable("아침 루틴", A), Comparable("상쾌한 하루 시작법", B))
        self.assertLess(report.body, 0.15)
        self.assertLess(report.intro, 0.15)
        self.assertEqual(report.level, "ok")
        self.assertEqual(report.reasons, ())
        self.assertFalse(report.needs_approval)

    def test_a_copy_with_only_the_first_sentence_changed_is_still_high(self):
        report = compare(Comparable("아침 루틴", A), Comparable("아침 루틴", COPY))
        self.assertGreater(report.body, 0.6)
        self.assertEqual(report.level, "high")
        self.assertTrue(any("본문 유사도" in reason for reason in report.reasons), report.reasons)

    def test_unrelated_texts_do_not_match(self):
        report = compare(Comparable("자동차 정비", "엔진 오일을 갈고 타이어 공기압을 확인하는 방법을 순서대로 적었습니다."), Comparable("김치찌개", "묵은지와 돼지고기를 볶다가 물을 붓고 끓이면 깊은 맛이 납니다."))
        self.assertLess(report.body, 0.05)
        self.assertLess(report.title, 0.3)
        self.assertEqual(report.level, "ok")

    def test_scores_stay_between_zero_and_one_and_do_not_depend_on_the_order(self):
        rng = random.Random(9)
        words = ["아침", "물", "스트레칭", "계란", "샐러드", "조명", "숙면", "산책", "커피", "책", "음악", "정리"]
        for _ in range(80):
            def make():
                body = "\n\n".join(" ".join(rng.choice(words) + rng.choice(["을", "를", "이", "은", ""]) for _ in range(rng.randint(1, 12))) + rng.choice([".", "", "!"]) for _ in range(rng.randint(0, 5)))
                return Comparable(" ".join(rng.choice(words) for _ in range(rng.randint(0, 4))), body, tuple(rng.sample(words, rng.randint(0, 4))),
                                  tuple(f"{rng.choice(words)}.png" for _ in range(rng.randint(0, 3))), rng.choice(["", "2026-10-30", "2026-10-31"]))
            first, second = make(), make()
            report, reverse = compare(first, second), compare(second, first)
            self.assertEqual(report, reverse)
            for name in sim.WEIGHTS:
                self.assertTrue(0.0 <= getattr(report, name) <= 1.0, (name, report))
            self.assertTrue(0.0 <= report.overall <= 1.0)
            self.assertAlmostEqual(report.overall, sum(sim.WEIGHTS[name] * getattr(report, name) for name in sim.WEIGHTS), delta=0.003)

    def test_empty_texts_never_look_like_copies(self):
        report = compare(Comparable("", ""), Comparable("", ""))
        self.assertEqual((report.title, report.intro, report.body, report.structure, report.tags, report.images, report.overall, report.level), (0.0,) * 7 + ("ok",))
        report = compare(Comparable("제목", ""), Comparable("제목", "본문"))
        self.assertEqual(report.body, 0.0)

    def test_short_texts_are_compared_as_a_whole(self):
        self.assertEqual(compare(Comparable("가", "가나"), Comparable("가", "가나")).body, 1.0)
        self.assertEqual(compare(Comparable("가", "가나"), Comparable("가", "가다")).body, 0.0)

    def test_the_structure_score_follows_the_shape_of_the_paragraphs(self):
        same_shape = compare(Comparable("a", "가" * 10 + "\n\n" + "나" * 100), Comparable("a", "다" * 10 + "\n\n" + "라" * 100))
        self.assertEqual(same_shape.structure, 1.0)
        other_shape = compare(Comparable("a", "가" * 10 + "\n\n" + "나" * 100), Comparable("a", "다" * 300))
        self.assertLess(other_shape.structure, 0.5)

    def test_images_tags_and_the_publish_day(self):
        first = Comparable("a", "본문", tags=("건강", "#운동", "Health"), images=("A.png", "b.png"), date="2026-10-30")
        second = Comparable("b", "다른 본문", tags=("건강", "운동", "health", "여행"), images=("a.png", "c.png"), date="2026-10-30")
        report = compare(first, second)
        self.assertEqual(report.tags, 0.75)
        self.assertEqual(report.images, round(1 / 3, 3))
        self.assertTrue(report.same_day)
        self.assertTrue(any("발행일이 같습니다(2026-10-30)" in reason for reason in report.reasons))
        self.assertFalse(compare(first, Comparable("b", "다른 본문", date="2026-10-31")).same_day)
        self.assertFalse(compare(Comparable("a", "x"), Comparable("b", "y")).same_day, "날짜가 비어 있으면 같은 날이 아니다")
        self.assertFalse(compare(Comparable("a", "x", date=""), Comparable("b", "y", date="")).same_day)

    def test_nearly_identical_tags_or_images_are_called_out_in_the_reasons(self):
        same = Comparable("a", "본문", tags=("가", "나", "다", "라", "마"), images=("x.png", "y.png"))
        other = Comparable("b", "전혀 다른 글입니다 정말로", tags=("가", "나", "다", "라", "마"), images=("x.png", "y.png"))
        reasons = compare(same, other).reasons
        self.assertTrue(any(reason.startswith("태그가 100% 같습니다") for reason in reasons), reasons)
        self.assertTrue(any(reason == "이미지가 거의 같습니다." for reason in reasons), reasons)
        partial = compare(Comparable("a", "본문", tags=("가", "나", "다", "라", "마")), Comparable("b", "다른 글 정말로 그렇습니다", tags=("가", "나", "다", "라", "바"))).reasons
        self.assertFalse(any("태그" in reason for reason in partial), "4/6 은 0.8 미만")

    def test_the_intro_can_be_given_or_is_the_first_paragraph(self):
        first = Comparable("a", "도입부 하나입니다 아주 길게\n\n본문 둘째 문단입니다 다르게")
        second = Comparable("b", "도입부 하나입니다 아주 길게\n\n전혀 다른 둘째 문단을 씁니다 정말")
        self.assertEqual(compare(first, second).intro, 1.0)
        given = Comparable("a", "본문 하나\n\n본문 둘", intro="완전히 다른 도입부를 따로 줍니다")
        self.assertLess(compare(given, Comparable("b", "본문 하나\n\n본문 둘")).intro, 0.2)
        self.assertEqual(compare(Comparable("a", "", intro="같은 도입부 문장입니다"), Comparable("b", "", intro="같은 도입부 문장입니다")).intro, 1.0)

    def test_comparing_something_that_is_not_a_comparable_text_is_invalid_content(self):
        for bad in ("글", None, {"title": "a"}, 5):
            with self.assertRaises(AppError) as caught:
                compare(Comparable("a", "b"), bad)
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")
            with self.assertRaises(AppError):
                compare(bad, Comparable("a", "b"))


class LevelTest(unittest.TestCase):
    """항목마다 기준 이상(경계 포함)이면 단계가 바뀌고, 가장 높은 단계가 이긴다."""

    FIRST = Comparable("아침 루틴 정리", A)
    SECOND = Comparable("아침 루틴 정리 하기", COPY)

    def setUp(self):
        self.report = compare(self.FIRST, self.SECOND)

    def values(self):
        return {"overall": self.report.overall, "body": self.report.body, "title": self.report.title, "intro": self.report.intro}

    def test_each_item_switches_the_level_exactly_at_its_threshold(self):
        off = {f"{kind}_{name}": 1.1 for kind in ("high", "warn") for name in ("overall", "body", "title", "intro")}
        for name, value in self.values().items():
            with self.subTest(item=name):
                none = compare(self.FIRST, self.SECOND, Thresholds(**off))
                self.assertEqual((none.level, none.reasons), ("ok", ()))
                warn = compare(self.FIRST, self.SECOND, Thresholds(**{**off, f"warn_{name}": value}))
                self.assertEqual(warn.level, "warn", "기준과 같은 값도 경고(이상)")
                self.assertEqual(len(warn.reasons), 1)
                self.assertIn("경고 기준", warn.reasons[0])
                above = compare(self.FIRST, self.SECOND, Thresholds(**{**off, f"warn_{name}": value + 0.0011}))
                self.assertEqual(above.level, "ok", "기준보다 아주 조금 낮으면 괜찮음")
                high = compare(self.FIRST, self.SECOND, Thresholds(**{**off, f"high_{name}": value}))
                self.assertEqual((high.level, high.needs_approval), ("high", True))
                self.assertIn("직접 승인이 필요합니다", high.reasons[0])
                near = compare(self.FIRST, self.SECOND, Thresholds(**{**off, f"high_{name}": value + 0.0011}))
                self.assertEqual(near.level, "ok")

    def test_a_high_item_wins_over_a_warn_item_in_any_order(self):
        off = {f"{kind}_{name}": 1.1 for kind in ("high", "warn") for name in ("overall", "body", "title", "intro")}
        for high_name, warn_name in (("body", "title"), ("title", "body"), ("overall", "intro"), ("intro", "overall")):
            with self.subTest(high=high_name, warn=warn_name):
                values = self.values()
                report = compare(self.FIRST, self.SECOND, Thresholds(**{**off, f"high_{high_name}": values[high_name], f"warn_{warn_name}": values[warn_name]}))
                self.assertEqual(report.level, "high")
                self.assertEqual(len(report.reasons), 2)

    def test_the_reason_names_the_item_the_percentage_and_the_limit(self):
        report = compare(self.FIRST, self.SECOND)
        text = " ".join(report.reasons)
        self.assertIn(f"본문 유사도 {report.body:.0%} — 기준({Thresholds().high_body:.0%}) 이상이라 직접 승인이 필요합니다.", text)
        mild = compare(Comparable("아침 루틴", A), Comparable("아침 루틴 하기", A.replace("출근 전에는", "일하러 가기 전에는").replace("저녁에는", "밤에는")),
                       Thresholds(high_overall=2, high_body=2, high_title=2, high_intro=2))
        self.assertEqual(mild.level, "warn")
        self.assertTrue(all("경고 기준" in reason for reason in mild.reasons), mild.reasons)

    def test_the_defaults_are_the_documented_ones(self):
        self.assertEqual(Thresholds(), Thresholds(0.60, 0.60, 0.85, 0.75, 0.40, 0.35, 0.60, 0.50))
        with self.assertRaises(Exception):
            Thresholds().high_body = 0.1


class ApprovalTest(unittest.TestCase):
    def test_a_high_result_is_refused_until_the_operator_approves_it(self):
        first, second = Comparable("아침 루틴", A), Comparable("아침 루틴", A)
        with self.assertRaises(AppError) as caught:
            check_pair(first, second)
        error = caught.exception
        self.assertEqual(error.code, "NAVER_SIMILARITY_HIGH")
        self.assertIn("본문 유사도 100%", error.detail)
        self.assertEqual(error.rendered().message, "네이버 A 와 B 의 글이 많이 비슷합니다.")
        report = check_pair(first, second, approved=True)
        self.assertEqual(report.level, "high")

    def test_a_fine_or_warned_result_is_returned_without_approval(self):
        self.assertEqual(check_pair(Comparable("아침 루틴", A), Comparable("상쾌한 하루", B)).level, "ok")
        loose = Thresholds(high_overall=2, high_body=2, high_title=2, high_intro=2, warn_body=0.0)
        self.assertEqual(check_pair(Comparable("아침 루틴", A), Comparable("아침 루틴", A), thresholds=loose).level, "warn")

    def test_approval_is_a_choice_not_a_default(self):
        with self.assertRaises(AppError):
            check_pair(Comparable("a", A), Comparable("a", A), approved=False)
        with self.assertRaises(AppError):
            check_pair(Comparable("a", A), Comparable("a", A), approved=None)


class FromPackageTest(unittest.TestCase):
    def profiles(self):
        a = NaverProfile("naver_a", "블로그 A", "https://blog.naver.com/a", default_tags=("에이",), min_chars=0)
        b = NaverProfile("naver_b", "블로그 B", "https://blog.naver.com/b", default_tags=("비",), min_chars=0)
        return a, b

    def test_a_package_becomes_a_comparable_text_without_the_image_marks_and_disclosure(self):
        a, _ = self.profiles()
        package = build_package(a, title="아침 루틴", body=A, tags=["건강"], assets=[Asset("a.png", "그림", 1)])
        comparable = Comparable.from_package(package, "2026-10-30")
        self.assertEqual((comparable.title, comparable.tags, comparable.images, comparable.date), ("아침 루틴", ("에이", "건강"), ("a.png",), "2026-10-30"))
        self.assertNotIn("[이미지", comparable.body)
        self.assertNotIn("AI 도구", comparable.body)
        self.assertEqual(comparable.intro, package.intro)

    def test_the_same_manuscript_for_both_blogs_is_caught_but_a_rewritten_one_passes(self):
        a, b = self.profiles()
        same_a, same_b = (build_package(profile, title="아침 루틴", body=A) for profile in (a, b))
        self.assertEqual(compare(Comparable.from_package(same_a), Comparable.from_package(same_b)).level, "high")
        rewritten = build_package(b, title="상쾌한 하루 시작법", body=B)
        self.assertEqual(compare(Comparable.from_package(same_a), Comparable.from_package(rewritten)).level, "ok")
        copied = build_package(b, title="아침 루틴", body=COPY)
        self.assertEqual(compare(Comparable.from_package(same_a), Comparable.from_package(copied)).level, "high")

    def test_the_two_blogs_default_tags_make_their_tags_differ_even_for_the_same_manuscript(self):
        a, b = self.profiles()
        report = compare(Comparable.from_package(build_package(a, title="t", body=A, tags=["건강"])), Comparable.from_package(build_package(b, title="t", body=A, tags=["건강"])))
        self.assertEqual(report.tags, round(1 / 3, 3))


class ExactNumbersTest(unittest.TestCase):
    """반올림하지 않은 정확한 값에서의 모서리 — 기준 경계·이유 경계·항목별 가중치·길이 한도·두 글의 순서."""

    OFF = {f"{kind}_{name}": 1.1 for kind in ("high", "warn") for name in ("overall", "body", "title", "intro")}

    def test_a_score_exactly_on_the_threshold_counts_for_both_levels(self):
        first, second = Comparable("abcd", "가"), Comparable("abce", "나")
        self.assertEqual(sim._ratio("abcd", "abce"), 0.75)
        self.assertEqual(compare(first, second, Thresholds(**{**self.OFF, "high_title": 0.75})).level, "high")
        self.assertEqual(compare(first, second, Thresholds(**{**self.OFF, "warn_title": 0.75})).level, "warn")
        self.assertEqual(compare(first, second, Thresholds(**{**self.OFF, "high_title": 0.7501})).level, "ok")
        self.assertEqual(compare(first, second, Thresholds(**{**self.OFF, "warn_title": 0.7501})).level, "ok")

    def test_tags_and_images_are_called_out_from_exactly_eighty_percent(self):
        four = ("가", "나", "다", "라")
        five = four + ("마",)
        report = compare(Comparable("a", "x", tags=four, images=four), Comparable("b", "y", tags=five, images=five))
        self.assertEqual((report.tags, report.images), (0.8, 0.8))
        self.assertTrue(any(reason.startswith("태그가 80% 같습니다") for reason in report.reasons), report.reasons)
        self.assertIn("이미지가 거의 같습니다.", report.reasons)

    def test_each_item_has_its_own_weight_in_the_overall_score(self):
        base = dict(title="가나다라마", body="가나다 라마바 사아자", intro="같은 도입부 문장입니다", tags=("가",), images=("x.png",))
        self.assertEqual(compare(Comparable(**base), Comparable(**base)).overall, 1.0)
        for item, change, expected in (
            ("tags", {"tags": ("나",)}, 0.85),
            ("body", {"body": "하하하 하하하 하하하"}, 0.65),
            ("title", {"title": "하하하하하"}, 0.80),
            ("intro", {"intro": "아침 산책 이야기 하나"}, 0.85),
            ("structure", {"body": "가나다\n\n라마바\n\n사아자"}, 0.95),          # 글자는 같고 문단 나눔만 다르다(문단 길이 모양 [0] ↔ [0, 0, 0] — 반만 닮음)
            ("images", {"images": ("y.png",)}, 0.95),
        ):
            with self.subTest(item=item):
                report = compare(Comparable(**base), Comparable(**{**base, **change}))
                self.assertEqual(report.overall, expected)
                self.assertEqual(getattr(report, item), 0.5 if item == "structure" else 0.0)

    def test_the_edit_ratio_is_the_same_whichever_text_comes_first(self):
        self.assertNotEqual(difflib.SequenceMatcher(None, "tide", "diet", autojunk=False).ratio(),
                            difflib.SequenceMatcher(None, "diet", "tide", autojunk=False).ratio(), "(이 시험의 전제: 순서에 따라 값이 다른 쌍)")
        self.assertEqual(sim._ratio("tide", "diet"), 0.375)
        self.assertEqual(sim._ratio("diet", "tide"), 0.375)
        self.assertEqual(compare(Comparable("tide", "x"), Comparable("diet", "y")).title, compare(Comparable("diet", "y"), Comparable("tide", "x")).title)

    def test_only_the_first_part_of_a_very_long_title_or_body_is_compared(self):
        rng = random.Random(3)
        title_head = "".join(rng.choice("가나다라마바사아자차카타파하") for _ in range(500))
        same_head = compare(Comparable(title_head + "가" * 400, "x"), Comparable(title_head + "하" * 400, "y"))
        self.assertEqual(same_head.title, 1.0, "제목은 앞 500자만 본다")
        body_head = "".join(rng.choice("가나다라마바사아자차카타파하") for _ in range(sim.MAX_COMPARE_CHARS))
        tail_a = "".join(rng.choice("abcdefghijklmn") for _ in range(30000))
        tail_b = "".join(rng.choice("opqrstuvwxyz") for _ in range(30000))
        report = compare(Comparable("t", body_head + tail_a, intro="같은 도입부 글입니다"), Comparable("t", body_head + tail_b, intro="같은 도입부 글입니다"))
        self.assertEqual(report.body, 1.0, "본문은 한도(MAX_COMPARE_CHARS)까지만 본다")

    def test_an_image_with_both_a_file_name_and_an_address_is_known_by_its_file_name(self):
        image = types.SimpleNamespace(filename="a.png", url="https://img.example/b.png")
        package = types.SimpleNamespace(title="t", core_text="본문", tags=(), intro="본문", images=(image,))
        self.assertEqual(Comparable.from_package(package).images, ("a.png",))
        only_url = types.SimpleNamespace(filename="", url="https://img.example/b.png")
        self.assertEqual(Comparable.from_package(types.SimpleNamespace(title="t", core_text="본문", tags=(), intro="본문", images=(only_url,))).images, ("https://img.example/b.png",))


class PerformanceTest(unittest.TestCase):
    def test_very_long_texts_finish_quickly(self):
        rng = random.Random(1)
        letters = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"
        first = " ".join("".join(rng.choice(letters) for _ in range(rng.randint(2, 6))) for _ in range(40000))
        second = first[: len(first) // 2] + " ".join("".join(rng.choice(letters) for _ in range(rng.randint(2, 6))) for _ in range(20000))
        started = time.time()
        report = compare(Comparable("제목 " * 100, first), Comparable("제목 " * 100, second))
        self.assertLess(time.time() - started, 5)
        self.assertGreater(report.body, 0.2)
        huge = "가나다라마바사 " * 200000
        started = time.time()
        compare(Comparable("a", huge), Comparable("b", huge))
        self.assertLess(time.time() - started, 5, "한도(MAX_COMPARE_CHARS)를 넘는 글은 앞부분만 본다")

    def test_many_tiny_paragraphs_do_not_blow_up_the_structure_score(self):
        many = "\n\n".join(["가나다"] * 3000)
        started = time.time()
        compare(Comparable("a", many), Comparable("b", many))
        self.assertLess(time.time() - started, 10)


if __name__ == "__main__":
    unittest.main()
