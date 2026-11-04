"""채널별 우수 후보 고르기 시험 — 우선 추천 먼저·같은 주제 묶음 상한·부족하면 일반 후보로 보충·보류함 이하로는 억지로 채우지 않기·모자란 수·결정적 순서·채널 거르기·꺼진 채널·입력 불변.

지키는 것:
  1) 우선 추천(80점 이상)을 점수 높은 순으로 고르되 같은 묶음은 채널의 상한(기본 2)을 넘기지 않는다. 상한은 정확히 상한 개수까지 허용한다.
  2) N 개(기본 5)에 못 미치면 일반 후보(65~79점)로 같은 규칙으로 보충하고(묶음 개수는 이어서 센다), 보류함(50~64)·제외·점수 없음으로는 채우지 않는다. 모자란 수는 구조값(`shortfall`)이다.
  3) 같은 입력은 입력 순서와 상관없이 늘 같은 결과다(동점은 먼저 만든 후보, 그다음 후보 번호). 입력은 바꾸지 않는다.
  4) 다른 채널 후보는 거르고, 후보 생성이 꺼진 채널은 빈 결과와 이유를 낸다.
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import dataclasses
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import select as sel  # noqa: E402

B = ts.PROFILES["naver_b"]
A = ts.PROFILES["naver_a"]


def ids(view):
    return [item.candidate_id for item in view.items]


def rated(final, cluster, candidate_id, **more):
    return ts.rated(final, cluster=cluster, candidate_id=candidate_id, **more)


class FewOrNoCandidatesTest(unittest.TestCase):
    def test_nothing_in_means_nothing_out_and_everything_missing(self):
        view = sel.top_view([], B)
        self.assertEqual((view.items, view.shortfall, view.reason), ((), 5, None))

    def test_three_recommended_candidates_leave_two_missing(self):
        view = sel.top_view([rated(90, "a", "x1"), rated(85, "b", "x2"), rated(81, "c", "x3")], B)
        self.assertEqual(ids(view), ["x1", "x2", "x3"])
        self.assertEqual(view.shortfall, 2)

    def test_a_full_set_has_nothing_missing(self):
        view = sel.top_view([rated(95 - n, f"c{n}", f"x{n}") for n in range(5)], B)
        self.assertEqual((len(view.items), view.shortfall), (5, 0))

    def test_more_than_n_candidates_keep_the_best_n_and_the_shortfall_is_never_negative(self):
        view = sel.top_view([rated(99 - n, f"c{n}", f"x{n}") for n in range(8)], B)
        self.assertEqual(ids(view), ["x0", "x1", "x2", "x3", "x4"])
        self.assertEqual(view.shortfall, 0)

    def test_the_number_of_candidates_follows_the_profile(self):
        three = dataclasses.replace(B, top_n=3)
        view = sel.top_view([rated(99 - n, f"c{n}", f"x{n}") for n in range(8)], three)
        self.assertEqual((len(view.items), view.shortfall), (3, 0))
        self.assertEqual(sel.top_view([rated(90, "a", "x1")], three).shortfall, 2)
        ten = dataclasses.replace(B, top_n=10, cluster_cap=10)
        self.assertEqual(sel.top_view([rated(90, "a", "x1")], ten).shortfall, 9)


class OrderAndBandsTest(unittest.TestCase):
    def test_recommended_candidates_come_in_descending_score_order(self):
        view = sel.top_view([rated(82, "a", "low"), rated(97, "b", "high"), rated(88, "c", "mid")], B)
        self.assertEqual(ids(view), ["high", "mid", "low"])

    def test_the_band_edges_decide_who_is_recommended_general_or_left_out(self):
        pool = [rated(80, "a", "s80"), rated(79, "b", "s79"), rated(65, "c", "s65"), rated(64, "d", "s64"), rated(50, "e", "s50"), rated(49, "f", "s49")]
        view = sel.top_view(pool, B)
        self.assertEqual(ids(view), ["s80", "s79", "s65"])
        self.assertEqual(view.shortfall, 2)

    def test_general_candidates_fill_the_gap_after_the_recommended_ones(self):
        pool = [rated(90, "a", "r1"), rated(85, "b", "r2")] + [rated(79 - n, f"g{n}", f"g{n}") for n in range(4)]
        view = sel.top_view(pool, B)
        self.assertEqual(ids(view), ["r1", "r2", "g0", "g1", "g2"])
        self.assertEqual(view.shortfall, 0)

    def test_a_general_candidate_never_goes_before_a_recommended_one(self):
        pool = [rated(79, "a", "general"), rated(80, "b", "recommended")]
        self.assertEqual(ids(sel.top_view(pool, B)), ["recommended", "general"])

    def test_the_hold_box_the_excluded_and_the_unrated_are_never_used_to_fill_up(self):
        pool = [rated(64, "a", "h1"), rated(55, "b", "h2"), rated(50, "c", "h3"), rated(49, "d", "e1"), rated(0, "e", "e2"), ts.make(candidate_id="unrated", topic_cluster="f")]
        view = sel.top_view(pool, B)
        self.assertEqual((view.items, view.shortfall), ((), 5))

    def test_low_candidates_do_not_help_even_when_some_good_ones_exist(self):
        pool = [rated(90, "a", "r1"), rated(70, "b", "g1"), rated(60, "c", "h1"), rated(40, "d", "e1")]
        view = sel.top_view(pool, B)
        self.assertEqual(ids(view), ["r1", "g1"])
        self.assertEqual(view.shortfall, 3)

    def test_the_work_status_is_not_looked_at_only_the_recommendation_band(self):
        pool = [rated(90, "a", "held", work_status="HOLD"), rated(85, "b", "rejected", work_status="REJECTED"), rated(80, "c", "new")]
        self.assertEqual(ids(sel.top_view(pool, B)), ["held", "rejected", "new"])


class ClusterCapTest(unittest.TestCase):
    def test_the_third_candidate_of_one_cluster_is_skipped_and_the_best_two_stay(self):
        pool = [rated(95, "ai", "a1"), rated(94, "ai", "a2"), rated(93, "ai", "a3"), rated(92, "ai", "a4"), rated(91, "pc", "p1"), rated(90, "pc", "p2"), rated(89, "pc", "p3")]
        self.assertEqual(ids(sel.top_view(pool, B)), ["a1", "a2", "p1", "p2"])

    def test_exactly_the_cap_is_allowed(self):
        view = sel.top_view([rated(95, "ai", "a1"), rated(94, "ai", "a2")], B)
        self.assertEqual(ids(view), ["a1", "a2"])
        self.assertEqual(sel.top_view([rated(95, "ai", "a1"), rated(94, "ai", "a2"), rated(93, "ai", "a3")], B).shortfall, 3)

    def test_a_cap_of_one_and_a_cap_of_three(self):
        pool = [rated(95 - n, "ai", f"a{n}") for n in range(4)] + [rated(80, "pc", "p1")]
        self.assertEqual(ids(sel.top_view(pool, dataclasses.replace(B, cluster_cap=1))), ["a0", "p1"])
        self.assertEqual(ids(sel.top_view(pool, dataclasses.replace(B, cluster_cap=3))), ["a0", "a1", "a2", "p1"])

    def test_a_skipped_candidate_makes_room_for_the_next_best_one_of_another_cluster(self):
        pool = [rated(99, "ai", "a1"), rated(98, "ai", "a2"), rated(97, "ai", "a3"), rated(96, "pc", "p1"), rated(95, "pc", "p2"), rated(94, "pc", "p3"), rated(93, "x", "x1"), rated(92, "y", "y1")]
        view = sel.top_view(pool, B)
        self.assertEqual(ids(view), ["a1", "a2", "p1", "p2", "x1"])
        self.assertEqual(view.shortfall, 0)

    def test_the_cluster_count_carries_over_from_the_recommended_to_the_general_pass(self):
        pool = [rated(90, "ai", "r1"), rated(85, "ai", "r2"), rated(79, "ai", "g1"), rated(78, "pc", "g2"), rated(77, "ai", "g3"), rated(76, "pc", "g4")]
        view = sel.top_view(pool, B)
        self.assertEqual(ids(view), ["r1", "r2", "g2", "g4"])
        self.assertEqual(view.shortfall, 1)

    def test_a_recommended_candidate_skipped_by_the_cap_is_not_rescued_as_a_general_one(self):
        pool = [rated(95, "ai", "r1"), rated(94, "ai", "r2"), rated(93, "ai", "r3")]
        self.assertEqual(ids(sel.top_view(pool, B)), ["r1", "r2"])

    def test_clusters_are_compared_exactly(self):
        pool = [rated(95, "ai", "a1"), rated(94, "ai-tools", "a2"), rated(93, "ai", "a3"), rated(92, "ai", "a4")]
        self.assertEqual(ids(sel.top_view(pool, B)), ["a1", "a2", "a3"])


class DeterminismTest(unittest.TestCase):
    def test_equal_scores_are_ordered_by_creation_time_then_by_id(self):
        pool = [rated(90, "a", "b-id", created_at="2026-11-04T10:00:00Z"), rated(90, "b", "a-id", created_at="2026-11-04T10:00:00Z"), rated(90, "c", "z-id", created_at="2026-11-04T09:00:00Z"),
                rated(90, "d", "m-id", created_at="2026-11-04T11:00:00Z")]
        self.assertEqual(ids(sel.top_view(pool, B)), ["z-id", "a-id", "b-id", "m-id"])

    def test_every_input_order_gives_the_same_result(self):
        pool = [rated(90, "a", "k1"), rated(90, "a", "k2"), rated(90, "a", "k3"), rated(85, "b", "k4"), rated(70, "c", "k5")]
        expected = ids(sel.top_view(pool, B))
        for order in itertools.permutations(pool):
            self.assertEqual(ids(sel.top_view(list(order), B)), expected)
        self.assertEqual(expected, ["k1", "k2", "k4", "k5"])

    def test_the_same_call_twice_gives_equal_results(self):
        pool = [rated(90 - n, f"c{n % 3}", f"x{n}") for n in range(9)]
        self.assertEqual(sel.top_view(pool, B), sel.top_view(pool, B))

    def test_the_same_candidate_given_twice_is_used_once(self):
        one = rated(90, "a", "same")
        view = sel.top_view([one, one, rated(80, "b", "other")], B)
        self.assertEqual(ids(view), ["same", "other"])
        self.assertEqual(view.shortfall, 3)


class ChannelFilterTest(unittest.TestCase):
    def test_candidates_of_other_channels_are_left_out(self):
        pool = [rated(95, "a", "n-a1", channel="naver_a"), rated(94, "b", "n-b1"), rated(93, "c", "n-a2", channel="naver_a"), rated(92, "d", "n-b2")]
        self.assertEqual(ids(sel.top_view(pool, B)), ["n-b1", "n-b2"])
        self.assertEqual(ids(sel.top_view(pool, A)), ["n-a1", "n-a2"])

    def test_the_cluster_cap_is_counted_per_channel_view(self):
        pool = [rated(95, "ai", "n-a1", channel="naver_a"), rated(94, "ai", "n-a2", channel="naver_a"), rated(93, "ai", "n-b1"), rated(92, "ai", "n-b2")]
        self.assertEqual(ids(sel.top_view(pool, B)), ["n-b1", "n-b2"])

    def test_a_pool_without_this_channel_is_all_missing(self):
        view = sel.top_view([rated(95, "a", "n-a1", channel="naver_a")], B)
        self.assertEqual((view.items, view.shortfall, view.reason), ((), 5, None))

    def test_a_channel_with_generation_off_gives_an_empty_view_and_the_reason(self):
        pages = ts.PROFILES["github_pages"]
        self.assertFalse(pages.generation_enabled)
        view = sel.top_view([rated(95, "a", "g1", channel="github_pages"), rated(94, "b", "g2", channel="github_pages")], pages)
        self.assertEqual((view.items, view.shortfall, view.reason), ((), 0, sel.REASON_GENERATION_OFF))
        self.assertEqual(sel.REASON_GENERATION_OFF, "generation_off")

    def test_every_channel_with_generation_off_is_empty_whatever_the_pool(self):
        pool = [rated(95, "a", "n1", channel="naver_b"), rated(94, "b", "g1", channel="github_pages"), rated(93, "c", "k1", channel="blogger_ko"), rated(92, "d", "e1", channel="blogger_en"),
                rated(91, "e", "n2", channel="naver_a")]
        for key, profile in ts.PROFILES.items():
            with self.subTest(channel=key):
                view = sel.top_view(pool, profile)
                if profile.generation_enabled:
                    self.assertEqual(len(view.items), 1)
                    self.assertIsNone(view.reason)
                else:
                    self.assertEqual((view.items, view.shortfall, view.reason), ((), 0, "generation_off"))

    def test_turning_generation_on_makes_the_channel_work(self):
        pages = dataclasses.replace(ts.PROFILES["github_pages"], generation_enabled=True)
        view = sel.top_view([rated(95, "a", "g1", channel="github_pages"), rated(94, "b", "g2", channel="naver_a")], pages)
        self.assertEqual((ids(view), view.shortfall, view.reason), (["g1"], 4, None))


class PurityTest(unittest.TestCase):
    def test_the_input_list_and_the_candidates_are_not_changed(self):
        pool = [rated(70, "a", "g1"), rated(95, "b", "r1"), rated(94, "b", "r2"), rated(93, "b", "r3"), rated(40, "c", "e1")]
        before = list(pool)
        snapshot = [item.to_dict() for item in pool]
        sel.top_view(pool, B)
        self.assertEqual(pool, before)
        self.assertTrue(all(left is right for left, right in zip(pool, before, strict=True)))
        self.assertEqual([item.to_dict() for item in pool], snapshot)

    def test_the_result_is_an_immutable_tuple_of_the_same_candidate_objects(self):
        one = rated(90, "a", "r1")
        view = sel.top_view([one], B)
        self.assertIsInstance(view.items, tuple)
        self.assertIs(view.items[0], one)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            view.shortfall = 0

    def test_any_iterable_of_candidates_is_accepted(self):
        pool = [rated(90, "a", "r1"), rated(85, "b", "r2")]
        for source in (tuple(pool), iter(pool), (item for item in pool), set(pool)):
            self.assertEqual(sorted(ids(sel.top_view(source, B))), ["r1", "r2"])

    def test_wrong_kinds_of_input_are_refused(self):
        with self.assertRaises(TypeError):
            sel.top_view([rated(90, "a", "r1")], None)
        with self.assertRaises(TypeError):
            sel.top_view([rated(90, "a", "r1")], {"key": "naver_b"})
        with self.assertRaises(TypeError):
            sel.top_view([rated(90, "a", "r1"), {"candidate_id": "x"}], B)
        with self.assertRaises(TypeError):
            sel.top_view(None, B)
        with self.assertRaises(TypeError):
            sel.top_view([rated(90, "a", "r1").scores], B)


if __name__ == "__main__":
    unittest.main()
