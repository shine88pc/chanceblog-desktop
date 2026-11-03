"""보관함의 후보에 같은 계산을 적용하는 부분(`content/suggest.py` 의 `assess`) 시험 — `candidates list --priority`·`show` 의 우선도.

지키는 것:
  1) 블로그 프로필 적합도는 후보가 프로필의 어느 씨앗(주제 90·카테고리 75·기본 태그 60)과 맞는지 + 글 유형 보너스. 겹치는 낱말이 없으면 0점이고 이유를 알리며, **프로필이 없으면 '데이터 없음'** 이라 그 요인을 빼고 다시 나눈다.
  2) 시기 적합: 후보의 외부 계절성 달이 있으면 그것(이번 달이면 100·아니면 30), 없으면 시기표(낱말이 들어 있으면 100·이어지면 70·아니면 50).
  3) 자기 자신의 제목(후보의 주제·이어진 글의 제목)은 '기존 글' 과 견주지 않는다. 비슷한 기존 글이 있으면 표시하고 신선도가 0 이다.
  4) 후보의 외부 지표가 있으면 키워드 기회도가 들어가고(수요↑·경쟁↓·상승일수록 ↑) 없으면 빠진다. 조회일은 며칠 지났는지(30일 넘으면 오래된 데이터)로 보인다. 후보 자체는 바뀌지 않는다(불변).
"""
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import suggest_support as sp  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import suggest as sg  # noqa: E402
from chanceblog_desktop.content import suggest_score as sc  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402


def assess(candidate, prof=None, **kwargs):
    kwargs.setdefault("today", sp.TODAY)
    return sg.assess(candidate, profile=sp.rich() if prof is None else prof, **kwargs)


def factor(assessment, name):
    found = {part.name: part for part in assessment.parts}
    return None if name not in found else found[name].value


class FitTest(unittest.TestCase):
    def test_the_best_matching_seed_decides_the_strength_and_the_post_type_adds_the_bonus(self):
        self.assertEqual(assess(sp.make("보일러 난방 점검", topic="겨울 보일러 난방 점검 순서")).fit, 100)
        self.assertEqual(assess(sp.make("보일러 난방 점검", topic="겨울 보일러 난방 점검 순서", post_type="비교형")).fit, 90)
        self.assertEqual(assess(sp.make("재테크 비교", topic="재테크 상품 비교")).fit, 85, "카테고리 씨앗 75 + 정보형 10")
        self.assertEqual(assess(sp.make("재테크 비교", topic="재테크 상품 비교", post_type="문제 해결형")).fit, 75)
        self.assertEqual(assess(sp.make("보험 설계", topic="보험 설계 요령")).fit, 70, "기본 태그 씨앗 60 + 10")
        self.assertEqual(assess(sp.make("보험 설계", topic="보험 설계 요령", post_type="장소·업체 정보형")).fit, 60)
        both = assess(sp.make("절약 보험", topic="생활 절약 보험 정리"))
        self.assertEqual(both.fit, 100, "주제 씨앗('생활 절약')과 태그 씨앗('보험')이 함께 맞으면 더 강한 쪽")

    def test_a_seed_matches_when_all_its_words_are_somewhere_in_the_keyword_topic_or_sub_keywords(self):
        item = sp.make("난방", topic="따뜻하게 지내기", sub_keywords=("보일러 점검",))
        self.assertEqual(assess(item).fit, 100, "보조 키워드까지 합쳐 '보일러 난방' 의 두 낱말이 모두 있다")
        self.assertEqual(assess(sp.make("보일러", topic="난방 가이드")).fit, 100, "키워드와 주제에 흩어져 있어도 낱말이 모두 있으면")
        self.assertEqual(assess(sp.make("보일러", topic="온수 가이드")).fit, 0, "한 낱말만으로는 두 낱말 씨앗과 맞지 않는다")

    def test_no_matching_word_is_zero_with_a_note_and_no_profile_is_no_data(self):
        item = sp.make("자전거 타기", topic="자전거 안전하게 타기")
        zero = assess(item)
        self.assertEqual(zero.fit, 0)
        self.assertIn("겹치는 낱말이 없어", " ".join(zero.notes))
        self.assertEqual(factor(zero, "fit"), 0)
        for prof in (None, sp.profile()):
            missing = sg.assess(item, profile=prof, today=sp.TODAY)
            self.assertIsNone(missing.fit)
            self.assertIn("프로필이 없거나 주제가 비어", " ".join(missing.notes))
            self.assertIsNone(factor(missing, "fit"))
            self.assertEqual([part.name for part in missing.parts], ["season", "freshness", "balance"])
            self.assertAlmostEqual(sum(part.share for part in missing.parts), 1.0)
            self.assertAlmostEqual(missing.parts[0].share, 20 / 55)

    def test_not_having_a_profile_is_not_the_same_as_scoring_zero(self):
        item = sp.make("자전거 타기", topic="자전거 안전하게 타기")
        zero, missing = assess(item), sg.assess(item, profile=None, today=sp.TODAY)
        self.assertNotEqual(zero.priority.score, missing.priority.score)
        self.assertGreater(missing.priority.score, zero.priority.score)


class SeasonTest(unittest.TestCase):
    def test_an_external_season_list_beats_the_table(self):
        item = sp.make("자전거 타기", seasonality=(11, 12), data_date="2026-11-01")
        self.assertEqual(factor(assess(item), "season"), 100)
        self.assertEqual(factor(assess(item, month=6), "season"), 30)
        self.assertIsNone(assess(item).season, "외부 자료가 정한 점수에는 시기표 항목을 붙이지 않는다")
        self.assertEqual(factor(assess(sp.make("김장 재료", seasonality=(6, 7), data_date="2026-11-01")), "season"), 30, "시기표에는 있어도 외부 자료가 이번 달이 아니라고 하면")

    def test_without_external_months_the_table_decides(self):
        self.assertEqual(factor(assess(sp.make("김장 재료 준비")), "season"), 100)
        self.assertEqual(assess(sp.make("김장 재료 준비")).season.word, "김장")
        self.assertEqual(factor(assess(sp.make("보일러 점검")), "season"), 70)
        self.assertEqual(factor(assess(sp.make("자전거 타기")), "season"), 50)
        self.assertEqual(factor(assess(sp.make("김장 재료 준비"), month=6), "season"), 50)
        self.assertIsNone(assess(sp.make("자전거 타기")).season)

    def test_the_month_defaults_to_the_month_of_today(self):
        self.assertEqual(factor(assess(sp.make("장마 대비"), today=date(2026, 7, 1)), "season"), 100)
        self.assertEqual(factor(assess(sp.make("장마 대비"), today=date(2026, 11, 3)), "season"), 50)


class FreshnessAndBalanceTest(unittest.TestCase):
    def test_a_similar_existing_post_is_flagged_and_zeroes_the_freshness(self):
        item = sp.make("보일러 점검", topic="겨울 보일러 점검 순서 정리")
        near = assess(item, existing_titles=["겨울 보일러 점검 순서 정리 방법"])
        self.assertTrue(near.similar)
        self.assertEqual(factor(near, "freshness"), 0.0)
        far = assess(item, existing_titles=["자전거 수리 방법"])
        self.assertFalse(far.similar)
        self.assertEqual(factor(far, "freshness"), 100.0)
        containing = assess(sp.make("보일러 점검", topic="점검하기"), existing_titles=["겨울철 보일러 점검 요령"])
        self.assertTrue(containing.similar, "두 낱말 키워드가 한 제목에 모두 있으면")

    def test_a_candidates_own_topic_and_its_linked_post_are_not_other_posts(self):
        item = sp.make("보일러 점검", topic="겨울 보일러 점검 순서 정리", picked={"naver_a": "2026-11-01T00:00:00Z"})
        own = assess(item, existing_titles=[item.topic])
        self.assertFalse(own.similar)
        self.assertEqual(factor(own, "freshness"), 100.0)
        linked = assess(sp.make("보일러 점검", topic="점검 주제"), existing_titles=["보일러 점검 순서 글"], own_titles=["보일러 점검 순서 글"])
        self.assertFalse(linked.similar)
        other = assess(sp.make("보일러 점검", topic="점검 주제"), existing_titles=["보일러 점검 순서 글"])
        self.assertTrue(other.similar)

    def test_a_prebuilt_title_index_gives_the_same_answer(self):
        titles = ["보일러 난방 점검 요령", "겨울 보일러 난방 관리"]
        item = sp.make("보일러 난방 점검", topic="난방 점검")
        self.assertEqual(assess(item, existing_titles=titles).to_dict(), assess(item, titles=sg.TitleIndex(titles)).to_dict())

    def test_balance_counts_the_existing_posts_that_cover_the_matched_seed(self):
        item = sp.make("보일러 난방 점검", topic="난방 점검")
        titles = ["보일러 난방 요령", "겨울 보일러 난방", "보일러만 이야기", "난방비 줄이기"]
        self.assertEqual(factor(assess(item, existing_titles=titles), "balance"), 60, "'보일러 난방' 을 모두 담은 글 둘 → 100 - 2×20")
        self.assertEqual(factor(assess(item), "balance"), 100)
        outside = sp.make("자전거 타기", topic="자전거")
        self.assertEqual(factor(assess(outside, existing_titles=["자전거 타기 요령", "자전거 타기 모음", "자전거 타기 기본"]), "balance"), 40, "씨앗이 안 맞으면 키워드 낱말로 센다")


class OpportunityTest(unittest.TestCase):
    def test_no_metrics_means_no_opportunity_factor_and_no_data_age(self):
        found = assess(sp.make("보일러 난방"))
        self.assertIsNone(factor(found, "opportunity"))
        self.assertEqual((found.data_age.data_date, found.data_age.days), (None, None))
        self.assertIn("키워드 기회도는 반영하지 않았습니다", found.reason)
        self.assertEqual(sum(part.weight for part in found.parts), 85)

    def test_metrics_add_the_opportunity_and_move_the_priority_the_right_way(self):
        def score(**metrics):
            return assess(sp.make("보일러 난방", data_date="2026-11-01", **metrics)).priority.score

        demand = [score(search_demand=value, related_blog_results=50_000, trend="보합") for value in (0, 10, 1000, 100_000)]
        self.assertEqual(demand, sorted(demand))
        self.assertTrue(demand[0] < demand[-1])
        competition = [score(search_demand=5000, related_blog_results=value, trend="보합") for value in (0, 1000, 1_000_000, 10_000_000)]
        self.assertEqual(competition, sorted(competition, reverse=True))
        self.assertTrue(competition[0] > competition[-1])
        up, flat, down = (score(search_demand=5000, related_blog_results=50_000, trend=item) for item in ("상승", "보합", "하락"))
        self.assertTrue(up > flat > down)
        found = assess(sp.make("보일러 난방", data_date="2026-11-01", search_demand=5000, trend="상승"))
        self.assertAlmostEqual(factor(found, "opportunity"), sc.opportunity(5000, None, "상승"))
        self.assertEqual(sum(part.weight for part in found.parts), 100)
        self.assertNotIn("반영하지 않았습니다", found.reason)

    def test_the_data_date_is_shown_with_its_age_and_the_old_data_note(self):
        for date_text, days, stale in (("2026-11-03", 0, False), ("2026-10-04", 30, False), ("2026-10-03", 31, True)):
            found = assess(sp.make("보일러 난방", data_date=date_text, search_demand=100))
            with self.subTest(date=date_text):
                self.assertEqual((found.data_age.days, found.data_age.stale), (days, stale))
                self.assertEqual("오래된 데이터" in found.data_age.text(), stale)

    def test_a_date_without_any_metric_is_not_external_data(self):
        found = assess(sp.make("보일러 난방", data_date="2026-10-01"))
        self.assertEqual((found.data_age.data_date, found.data_age.stale), (None, False))


class ReasonAndShapeTest(unittest.TestCase):
    def test_the_reason_names_every_factor_with_value_and_share_and_the_season_sentence(self):
        found = assess(sp.make("김장 재료 준비", topic="김장 재료 준비 순서"))
        self.assertTrue(found.reason)
        for part in found.parts:
            self.assertIn(f"{sc.FACTOR_NAMES[part.name]} {sg.num(part.value)}점", found.reason)
        self.assertIn("김장", found.reason)
        self.assertIn(f"콘텐츠 작성 우선도 {sg.num(found.priority.score)}점", found.reason)
        self.assertIsNone(cd.forbidden_claim(found.reason))

    def test_the_priority_follows_the_level_boundaries_and_the_score_matches_the_parts(self):
        found = assess(sp.make("보일러 난방 점검", topic="겨울 보일러 난방 점검 순서"))
        self.assertEqual(found.priority.level, sc.level_of(found.priority.score))
        self.assertAlmostEqual(found.priority.score, round(sum(part.points for part in found.parts), 1), places=1)

    def test_to_dict_is_plain_json_with_the_factors(self):
        found = assess(sp.make("보일러 난방", data_date="2026-11-01", search_demand=1000))
        data = json.loads(json.dumps(found.to_dict(), ensure_ascii=False))
        self.assertEqual(set(data), {"priority", "profile_fit", "season", "data", "similar_post_exists", "reason", "notes", "factors"})
        self.assertEqual(data["priority"], {"level": found.priority.level, "score": found.priority.score})
        self.assertEqual([item["name"] for item in data["factors"]], [part.name for part in found.parts])
        self.assertEqual(data["data"]["data_date"], "2026-11-01")

    def test_when_no_factor_can_be_computed_the_assessment_says_so_instead_of_inventing_a_score(self):
        from unittest import mock
        with mock.patch.object(sc, "combine", return_value=(None, ())):
            found = assess(sp.make("보일러 난방"))
        self.assertEqual((found.priority, found.parts, found.reason), (None, (), ""))
        self.assertEqual(found.to_dict()["priority"], None)
        self.assertEqual(found.to_dict()["factors"], [])

    def test_assessing_does_not_change_the_candidate(self):
        item = sp.make("보일러 난방", data_date="2026-11-01", search_demand=1000, priority=12.5, profile_fit=33.0, keyword_opportunity=7.0)
        before = item.to_dict()
        assess(item)
        self.assertEqual(item.to_dict(), before)
        self.assertEqual((item.priority, item.profile_fit, item.keyword_opportunity), (12.5, 33.0, 7.0), "저장된 값은 계산에 쓰이지도 바뀌지도 않는다")

    def test_a_wrong_month_or_today_is_refused(self):
        for kwargs in ({"month": 13}, {"month": 0}, {"today": "2026-11-03"}, {"today": date(1999, 1, 1)}):
            with self.assertRaises(AppError) as caught:
                assess(sp.make("보일러 난방"), **kwargs)
            self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")

    def test_the_assessment_of_a_hidden_stored_value_never_leaks_into_the_score(self):
        low = assess(sp.make("보일러 난방", data_date="2026-11-01", priority=1.0, keyword_opportunity=1.0))
        high = assess(sp.make("보일러 난방", data_date="2026-11-01", priority=99.0, keyword_opportunity=99.0))
        self.assertEqual(low.priority, high.priority)


if __name__ == "__main__":
    unittest.main()
