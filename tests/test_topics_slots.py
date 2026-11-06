"""남은 자리(`topics/slots.py`) 시험 — 계획 11.1 의 식·센 상태 표·같은 후보 세 규칙을 손으로 계산한 값으로 못박는다(P3, D-59). 네트워크·파일·실제 시계·난수 없이 돈다.

지키는 것:
  1) `remaining_slots = max(0, 목표 − 활성 − 검토 대기)` 이고 음수가 되지 않으며 틀린 입력(음수·참거짓·실수·글)은 거절한다.
  2) 센 상태·안 센 상태 표의 줄마다 한 번씩 — 제외하는 조건이 먼저이고(사람 제외·구간 제외·만료된 보류) 한 후보는 한 번만 센다. 보류 기한은 정각이면 지난 것이다.
  3) 같은 후보는 번호 / 채널+주제 해시 / 채널+씨앗+검색 의도+관점 셋으로 가르고, 씨앗 번호가 없는 후보끼리는 같다고 보지 않는다(모름 ≠ 같음).
  4) 같은 후보 묶음은 한 번만 세고 입력 순서와 상관없이 같은 개수가 나온다.
"""
import dataclasses
import itertools
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import slots  # noqa: E402

NOW = "2026-11-10T00:00:00Z"
PAST, FUTURE = "2026-11-09T23:59:59Z", "2026-11-10T00:00:01Z"
_NUMBER = itertools.count(1)


def cand(final=70, *, cid=None, status="NEW", expires=None, channel="naver_a", **more):
    """최종 점수가 `final`(None 이면 점수 없음)인 후보. 보류 구간 후보에는 기한을 따로 준다."""
    cid = cid or f"auto-{next(_NUMBER)}"
    values = {"candidate_id": cid, "channel": channel, "language": "ko", "work_status": status, "review_expires_at": expires, "created_at": "2026-10-01T00:00:00Z"}
    values.update(more)
    if final is not None:
        values["scores"] = ts.flat_card(final)
    return ts.make(**values)


class RemainingSlotsTest(unittest.TestCase):
    def test_the_formula_with_hand_computed_values(self):
        for target, active, pending, expected in ((3, 0, 0, 3), (3, 2, 0, 1), (3, 1, 1, 1), (3, 2, 1, 0), (3, 3, 3, 0), (3, 9, 0, 0), (0, 0, 0, 0), (0, 5, 5, 0), (20, 7, 4, 9), (200, 0, 0, 200)):
            with self.subTest(target=target, active=active, pending=pending):
                self.assertEqual(slots.remaining_slots(target, active, pending), expected)

    def test_the_largest_allowed_count_is_accepted_and_one_more_is_refused(self):
        self.assertEqual(slots.remaining_slots(slots.MAX_COUNT, 0, 0), slots.MAX_COUNT)
        self.assertEqual(slots.remaining_slots(0, slots.MAX_COUNT, slots.MAX_COUNT), 0)
        with self.assertRaises(ValueError):
            slots.remaining_slots(0, slots.MAX_COUNT + 1, 0)

    def test_it_never_goes_below_zero_and_each_part_lowers_the_result_by_exactly_its_size(self):
        for active in range(0, 6):
            for pending in range(0, 6):
                self.assertEqual(slots.remaining_slots(5, active, pending), max(0, 5 - active - pending))

    def test_wrong_inputs_are_refused_not_corrected(self):
        for args in ((-1, 0, 0), (3, -1, 0), (3, 0, -1), (True, 0, 0), (3, False, 0), (3, 0, True), (3.0, 0, 0), (3, 1.5, 0), ("3", 0, 0), (None, 0, 0), (3, None, 0), (slots.MAX_COUNT + 1, 0, 0)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    slots.remaining_slots(*args)


class ClassifyTest(unittest.TestCase):
    def test_every_row_of_the_counting_table(self):
        rows = (
            ("사람이 제외", cand(90, status="REJECTED"), None, False, None, slots.WHY_REJECTED),
            ("구간 제외", cand(40), None, False, None, slots.WHY_EXCLUDED),
            ("만료된 구간 보류", cand(55, expires=PAST), None, False, None, slots.WHY_EXPIRED),
            ("만료된 작업 보류", cand(90, status="HOLD", expires=PAST), None, False, None, slots.WHY_EXPIRED),
            ("초안 쓰는 중", cand(70), slots.DRAFTING, True, slots.KIND_ACTIVE, slots.WHY_DRAFTING),
            ("초안 준비됨", cand(70), slots.DRAFT_READY, True, slots.KIND_ACTIVE, slots.WHY_DRAFT_READY),
            ("선택됨", cand(70, status="SELECTED"), None, True, slots.KIND_ACTIVE, slots.WHY_SELECTED),
            ("기한 안의 구간 보류", cand(55, expires=FUTURE), None, True, slots.KIND_PENDING, slots.WHY_HOLD),
            ("작업 보류(기한 없음)", cand(90, status="HOLD"), None, True, slots.KIND_PENDING, slots.WHY_HOLD),
            ("작업 보류(기한 안)", cand(70, status="HOLD", expires=FUTURE), None, True, slots.KIND_PENDING, slots.WHY_HOLD),
            ("우선 추천(새 후보)", cand(85), None, True, slots.KIND_ACTIVE, slots.WHY_RECOMMENDED),
            ("일반(검토 중)", cand(70, status="REVIEW"), None, True, slots.KIND_ACTIVE, slots.WHY_GENERAL),
            ("점수 없음", cand(None), None, True, slots.KIND_PENDING, slots.WHY_UNRATED),
        )
        for name, candidate, draft, counted, kind, why in rows:
            with self.subTest(row=name):
                self.assertEqual(slots.classify(candidate, NOW, draft_state=draft), slots.Verdict(counted, kind, why))

    def test_every_reason_in_the_table_is_reached_by_some_row_and_has_a_korean_name(self):
        self.assertEqual(set(slots.REASON_KO), set(slots.REASONS))
        self.assertEqual(len(set(slots.REASONS)), len(slots.REASONS))
        self.assertEqual(set(slots.COUNTED_REASONS) | set(slots.IGNORED_REASONS), set(slots.REASONS))
        self.assertTrue(all(isinstance(text, str) and text for text in slots.REASON_KO.values()))

    def test_the_excluding_conditions_win_over_the_counting_ones(self):
        self.assertEqual(slots.classify(cand(90, status="REJECTED"), NOW, draft_state=slots.DRAFTING).why, slots.WHY_REJECTED)
        self.assertEqual(slots.classify(cand(40, status="SELECTED"), NOW).why, slots.WHY_EXCLUDED)
        self.assertEqual(slots.classify(cand(40, status="REJECTED"), NOW).why, slots.WHY_REJECTED, "둘 다 제외 조건이면 사람의 제외가 먼저다")
        self.assertEqual(slots.classify(cand(55, status="SELECTED", expires=PAST), NOW).why, slots.WHY_EXPIRED, "기한이 지난 보류는 선택됨이어도 자리를 차지하지 않는다")
        self.assertEqual(slots.classify(cand(55, expires=PAST), NOW, draft_state=slots.DRAFT_READY).why, slots.WHY_EXPIRED)

    def test_the_hold_deadline_is_inclusive_the_exact_second_is_already_over(self):
        for expiry, expected in ((FUTURE, True), (NOW, False), (PAST, False)):
            with self.subTest(expiry=expiry):
                self.assertEqual(slots.classify(cand(55, expires=expiry), NOW).counted, expected)

    def test_a_held_candidate_without_a_deadline_is_a_valid_hold_and_unknown_is_not_zero(self):
        self.assertEqual(slots.classify(cand(None, status="HOLD"), NOW), slots.Verdict(True, slots.KIND_PENDING, slots.WHY_HOLD))
        self.assertTrue(slots.classify(cand(None), NOW).counted, "점수가 없다고 0 점으로 보고 빼지 않는다")
        self.assertFalse(slots.classify(cand(0), NOW).counted, "0 점은 제외 구간이다(모름과 다르다)")

    def test_wrong_inputs(self):
        with self.assertRaises(ValueError):
            slots.classify(cand(70), NOW, draft_state="PUBLISHED")
        with self.assertRaises(ValueError):
            slots.classify(cand(70), NOW, draft_state="drafting")
        with self.assertRaises(TypeError):
            slots.classify({"a": 1}, NOW)
        with self.assertRaises(AppError):
            slots.classify(cand(70), "어제")                               # 시각 모양이 틀리면 기한 없는 후보도 거절한다
        with self.assertRaises(AppError):
            slots.classify(cand(70), None)


class SameCandidateTest(unittest.TestCase):
    def test_the_three_rules(self):
        base = cand(70, cid="c-a", topic="예시 로봇청소기 고르는 기준", seed_id="s1", search_intent="selection_guide", topic_angle="buying-criteria")
        same_id = cand(60, cid="c-a", topic="전혀 다른 주제", search_intent="comparison", topic_angle="x")
        same_topic = cand(60, cid="c-b", topic="예시 로봇청소기, 고르는 기준!", search_intent="comparison", topic_angle="x")
        same_seed = cand(60, cid="c-c", topic="다른 주제입니다", seed_id="s1", search_intent="selection_guide", topic_angle="buying-criteria")
        different = cand(60, cid="c-d", topic="다른 주제입니다", seed_id="s1", search_intent="comparison", topic_angle="buying-criteria")
        for name, other, expected in (("번호가 같다", same_id, True), ("주제 글이 띄어쓰기·기호만 다르다", same_topic, True), ("씨앗·의도·관점이 같다", same_seed, True), ("의도가 다르다", different, False)):
            with self.subTest(rule=name):
                self.assertEqual(slots.same_candidate(base, other), expected)
                self.assertEqual(slots.same_candidate(other, base), expected, "순서를 바꿔도 같다")

    def test_a_different_channel_is_never_the_same_except_by_number(self):
        one = cand(70, cid="c-a", channel="naver_a", topic="예시 같은 주제", seed_id="s1")
        other = cand(70, cid="c-b", channel="naver_b", topic="예시 같은 주제", seed_id="s1")
        self.assertFalse(slots.same_candidate(one, other))
        self.assertTrue(slots.same_candidate(one, dataclasses.replace(other, candidate_id="c-a")), "번호가 같으면 같다")

    def test_no_seed_on_both_sides_does_not_make_them_the_same_unknown_is_not_equal(self):
        one = cand(70, cid="c-a", topic="예시 첫 주제", seed_id=None)
        two = cand(70, cid="c-b", topic="예시 둘째 주제", seed_id=None)
        self.assertEqual((one.search_intent, one.topic_angle), (two.search_intent, two.topic_angle))
        self.assertFalse(slots.same_candidate(one, two))

    def test_two_different_topics_without_any_letter_or_digit_are_not_the_same_unknown_is_not_equal(self):
        one = cand(70, cid="c-a", topic="!!!", seed_id="s1", search_intent="comparison", topic_angle="p")
        two = cand(70, cid="c-b", topic="???", seed_id="s2", search_intent="information", topic_angle="q")
        self.assertIsNone(slots.normalized_topic_hash(one.topic))
        self.assertIsNone(slots.normalized_topic_hash(two.topic))
        self.assertFalse(slots.same_candidate(one, two), "글자도 숫자도 없는 두 주제를 같다고 보지 않는다")
        self.assertTrue(slots.same_candidate(one, dataclasses.replace(two, seed_id="s1", search_intent="comparison", topic_angle="p")), "씨앗 규칙으로는 같을 수 있다")

    def test_the_seed_rule_needs_the_same_angle_too(self):
        base = cand(70, cid="c-a", topic="예시 첫째 주제", seed_id="s1", search_intent="comparison", topic_angle="angle-one")
        for name, other in (("관점이 다름", cand(70, cid="c-b", topic="예시 둘째 주제", seed_id="s1", search_intent="comparison", topic_angle="angle-two")),
                            ("의도가 다름", cand(70, cid="c-c", topic="예시 셋째 주제", seed_id="s1", search_intent="information", topic_angle="angle-one")),
                            ("씨앗이 다름", cand(70, cid="c-d", topic="예시 넷째 주제", seed_id="s2", search_intent="comparison", topic_angle="angle-one"))):
            with self.subTest(case=name):
                self.assertFalse(slots.same_candidate(base, other))
        self.assertTrue(slots.same_candidate(base, cand(70, cid="c-e", topic="예시 다섯째 주제", seed_id="s1", search_intent="comparison", topic_angle="angle-one")))

    def test_a_hub_candidate_joins_two_others_that_are_not_the_same_as_each_other(self):
        hub = cand(70, cid="hub", topic="예시 허브 주제", seed_id="s5", search_intent="comparison", topic_angle="p")
        by_topic = cand(70, cid="a", topic="예시 허브 주제", seed_id=None)                            # 허브와 주제 해시가 같다
        by_seed = cand(70, cid="b", topic="전혀 다른 둘째 글", seed_id="s5", search_intent="comparison", topic_angle="p")        # 허브와 씨앗 규칙이 같다
        self.assertFalse(slots.same_candidate(by_topic, by_seed))
        self.assertEqual(slots.group_same([by_topic, by_seed, hub]), (("a", "b", "hub"),), "서로 같지 않아도 허브를 거쳐 한 묶음이다 — 어느 순서로 넣어도")
        self.assertEqual(slots.group_same([hub, by_seed, by_topic]), (("hub", "b", "a"),))
        self.assertEqual(slots.count_slots([by_topic, by_seed, hub], 5, NOW).active_existing, 1)

    def test_the_topic_hash_is_stable_and_ignores_spacing_case_and_marks_but_not_meaning(self):
        self.assertEqual(slots.normalized_topic_hash("로컬 AI 사양"), slots.normalized_topic_hash("로컬ai사양"))
        self.assertEqual(slots.normalized_topic_hash("C++ 입문"), slots.normalized_topic_hash("c++입문"))
        self.assertNotEqual(slots.normalized_topic_hash("C++ 입문"), slots.normalized_topic_hash("C# 입문"))
        self.assertEqual(len(slots.normalized_topic_hash("예시")), 16)
        self.assertEqual(slots.normalized_topic_hash("예시"), slots.normalized_topic_hash("예시"))
        self.assertIsNone(slots.normalized_topic_hash("!!! ???"), "글자도 숫자도 없으면 모름이고 같다고 보지 않는다")
        with self.assertRaises(TypeError):
            slots.normalized_topic_hash(None)

    def test_find_same_and_group_same(self):
        a = cand(70, cid="c-a", topic="예시 가 주제")
        b = cand(70, cid="c-b", topic="예시 가주제")                      # a 와 같다(주제 해시)
        c = cand(70, cid="c-c", topic="전혀 다름", seed_id="s9", search_intent="comparison", topic_angle="z")
        d = cand(70, cid="c-d", topic="또 다름", seed_id="s9", search_intent="comparison", topic_angle="z")      # c 와 같다(씨앗 규칙)
        e = cand(70, cid="c-e", topic="혼자")
        self.assertEqual(slots.find_same(a, [a, b, c, d, e]), ("c-a", "c-b"))
        self.assertEqual(slots.group_same([a, b, c, d, e]), (("c-a", "c-b"), ("c-c", "c-d"), ("c-e",)))
        chain = [cand(70, cid="x1", topic="예시 사슬 하나", seed_id="s5", search_intent="comparison", topic_angle="p"),
                 cand(70, cid="x2", topic="사슬 둘째 글", seed_id="s5", search_intent="comparison", topic_angle="p"),
                 cand(70, cid="x3", topic="사슬 둘째글!")]                                                     # x1~x2 씨앗 규칙, x2~x3 주제 해시 — 사슬로 한 묶음
        self.assertEqual(slots.group_same(chain), (("x1", "x2", "x3"),))


class CountSlotsTest(unittest.TestCase):
    def test_the_p2b_scenario_two_valid_existing_of_a_target_of_three_leave_one_slot(self):
        existing = [cand(85, cid="e1", topic="예시 첫째"), cand(70, cid="e2", topic="예시 둘째", seed_id="s2")]
        result = slots.count_slots(existing, 3, NOW)
        self.assertEqual((result.target, result.active_existing, result.pending_review, result.remaining, result.ignored), (3, 2, 0, 1, ()))

    def test_a_rejected_candidate_does_not_take_a_slot(self):
        existing = [cand(85, cid="e1", topic="예시 첫째"), cand(70, cid="e2", topic="예시 둘째", status="REJECTED")]
        result = slots.count_slots(existing, 3, NOW)
        self.assertEqual((result.active_existing, result.remaining, result.ignored), (1, 2, ((slots.WHY_REJECTED, 1),)))

    def test_drafting_and_draft_ready_come_from_the_caller_and_take_a_slot(self):
        existing = [cand(85, cid="e1", topic="예시 첫째", status="SELECTED"), cand(70, cid="e2", topic="예시 둘째", status="SELECTED")]
        states = {"e1": slots.DRAFTING, "e2": slots.DRAFT_READY}
        result = slots.count_slots(existing, 3, NOW, draft_states=states)
        self.assertEqual((result.active_existing, result.remaining), (2, 1))
        self.assertEqual(dict(result.verdicts)["e1"].why, slots.WHY_DRAFTING)
        self.assertEqual(dict(result.verdicts)["e2"].why, slots.WHY_DRAFT_READY)
        self.assertEqual(slots.count_slots(existing, 3, NOW).remaining, 1, "글 상태를 안 알려 주면 선택됨으로만 센다 — 같은 개수")

    def test_unrated_and_valid_holds_are_pending_review_and_take_slots(self):
        existing = [cand(None, cid="e1", topic="예시 점수 없음"), cand(55, cid="e2", topic="예시 보류", expires=FUTURE), cand(85, cid="e3", topic="예시 추천")]
        result = slots.count_slots(existing, 5, NOW)
        self.assertEqual((result.active_existing, result.pending_review, result.remaining), (1, 2, 2))

    def test_expired_holds_excluded_bands_and_rejections_are_listed_by_reason(self):
        existing = [cand(55, cid="e1", topic="예시 만료", expires=PAST), cand(30, cid="e2", topic="예시 제외 구간"), cand(90, cid="e3", topic="예시 사람 제외", status="REJECTED"),
                    cand(85, cid="e4", topic="예시 살아 있는 후보")]
        result = slots.count_slots(existing, 3, NOW)
        self.assertEqual(result.ignored, ((slots.WHY_REJECTED, 1), (slots.WHY_EXCLUDED, 1), (slots.WHY_EXPIRED, 1)))
        self.assertEqual((result.active_existing, result.remaining), (1, 2))

    def test_the_same_candidate_stored_twice_is_counted_once(self):
        existing = [cand(85, cid="e1", topic="예시 같은 주제"), cand(85, cid="e2", topic="예시 같은주제!"), cand(70, cid="e3", topic="예시 다른 주제")]
        result = slots.count_slots(existing, 5, NOW)
        self.assertEqual((result.active_existing, result.remaining, result.ignored), (2, 3, ((slots.WHY_DUPLICATE, 1),)))
        self.assertEqual([item[1].why for item in result.verdicts], [slots.WHY_RECOMMENDED, slots.WHY_DUPLICATE, slots.WHY_GENERAL])

    def test_an_excluding_member_wins_over_a_counting_twin_but_an_expired_twin_does_not(self):
        rejected_pair = [cand(85, cid="e1", topic="예시 같은 주제"), cand(85, cid="e2", topic="예시 같은 주제", status="REJECTED")]
        self.assertEqual(slots.count_slots(rejected_pair, 3, NOW).remaining, 3, "사람이 제외한 후보와 같은 후보는 자리를 차지하지 않는다")
        expired_pair = [cand(55, cid="e1", topic="예시 같은 주제", expires=PAST), cand(85, cid="e2", topic="예시 같은 주제")]
        result = slots.count_slots(expired_pair, 3, NOW)
        self.assertEqual((result.active_existing, result.remaining), (1, 2), "기한이 지난 보류는 같은 후보의 살아 있는 쪽을 가리지 않는다")

    def test_in_one_same_candidate_group_the_active_member_decides_before_the_pending_one(self):
        pending = cand(55, cid="e1", topic="예시 같은 주제", expires=FUTURE)                    # 검토 대기(유효한 보류)
        active = cand(85, cid="e2", topic="예시 같은 주제")                                    # 활성(우선 추천)
        for order in ((pending, active), (active, pending)):
            result = slots.count_slots(list(order), 3, NOW)
            self.assertEqual((result.active_existing, result.pending_review, result.remaining), (1, 0, 2), "묶음은 활성으로 한 번만 센다 — 들어온 순서와 상관없다")
            self.assertEqual(result.ignored, ((slots.WHY_DUPLICATE, 1),))

    def test_a_twin_in_the_excluded_score_band_also_takes_the_group_out(self):
        pair = [cand(85, cid="e1", topic="예시 같은 주제"), cand(30, cid="e2", topic="예시 같은 주제")]
        for order in (pair, pair[::-1]):
            result = slots.count_slots(order, 3, NOW)
            self.assertEqual((result.active_existing, result.pending_review, result.remaining), (0, 0, 3), "구간 제외(0~49점)인 같은 후보가 있으면 묶음은 자리를 차지하지 않는다")
            self.assertIn((slots.WHY_EXCLUDED, 1), result.ignored)

    def test_the_result_does_not_depend_on_the_input_order(self):
        existing = [cand(85, cid="e1", topic="예시 하나"), cand(85, cid="e2", topic="예시하나"), cand(None, cid="e3", topic="예시 둘"), cand(55, cid="e4", topic="예시 셋", expires=FUTURE),
                    cand(90, cid="e5", topic="예시 넷", status="REJECTED"), cand(30, cid="e6", topic="예시 다섯"), cand(70, cid="e7", topic="예시 여섯", status="SELECTED")]
        reference = slots.count_slots(existing, 10, NOW, draft_states={"e7": slots.DRAFTING})
        for seed in range(12):
            shuffled = list(existing)
            random.Random(seed).shuffle(shuffled)
            result = slots.count_slots(shuffled, 10, NOW, draft_states={"e7": slots.DRAFTING})
            self.assertEqual((result.active_existing, result.pending_review, result.remaining), (reference.active_existing, reference.pending_review, reference.remaining), seed)
            self.assertEqual(sorted(result.ignored), sorted(reference.ignored))

    def test_an_empty_list_leaves_the_whole_target_and_a_full_list_leaves_none(self):
        self.assertEqual(slots.count_slots([], 4, NOW).remaining, 4)
        full = [cand(85, cid=f"e{n}", topic=f"예시 주제 {n}") for n in range(4)]
        self.assertEqual(slots.count_slots(full, 4, NOW).remaining, 0)
        self.assertEqual(slots.count_slots(full + [cand(85, cid="e9", topic="예시 주제 9")], 4, NOW).remaining, 0)

    def test_candidates_from_two_channels_are_refused_and_the_input_is_not_changed(self):
        with self.assertRaises(ValueError):
            slots.count_slots([cand(85, cid="e1", channel="naver_a"), cand(85, cid="e2", channel="naver_b")], 3, NOW)
        existing = [cand(85, cid="e1", topic="예시 하나")]
        before = list(existing)
        slots.count_slots(existing, 3, NOW)
        self.assertEqual(existing, before)

    def test_wrong_inputs(self):
        for call in (lambda: slots.count_slots("abc", 3, NOW), lambda: slots.count_slots([1], 3, NOW), lambda: slots.count_slots([], -1, NOW), lambda: slots.count_slots([], True, NOW)):
            with self.assertRaises((TypeError, ValueError)):
                call()
        with self.assertRaises(ValueError):
            slots.count_slots([], 3, NOW, draft_states={"e1": "PUBLISHED"})
        with self.assertRaises(ValueError):
            slots.count_slots([], 3, NOW, draft_states=[("e1", "DRAFTING")])


def old_group_same(pool):
    """P3 첫 구현 그대로 — 쌍마다 `same_candidate` 로 견주는 O(n²) 묶기. 새 열쇠 사전 구현이 이것과 정확히 같은 결과를 내는지 견주는 기준이다(D-71)."""
    parent = list(range(len(pool)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(pool)):
        for right in range(left + 1, len(pool)):
            if slots.same_candidate(pool[left], pool[right]):
                parent[root(right)] = root(left)
    groups = {}
    for index, item in enumerate(pool):
        groups.setdefault(root(index), []).append(item.candidate_id)
    return tuple(tuple(ids) for ids in groups.values())


class GroupSameEquivalenceTest(unittest.TestCase):
    """열쇠 사전으로 묶는 새 `group_same` 은 옛 쌍 비교 구현과 정확히 같은 묶음(묶음의 순서·안의 순서까지)을 낸다 — 무작위 입력 5,000개. 열쇠가 `same_candidate` 와 같은 뜻인지도 같은 입력으로 견준다."""

    IDS = [f"cand{number:04d}" for number in range(1, 8)]
    TOPICS = ["예시 주제 하나 글", "예시 주제 하나 글 !", "예시 주제 둘 글", "!!!", "예시 주제 셋", "예시 주제 하나, 글", "…"]

    def random_pool(self, rng):
        pool = []
        for _ in range(rng.randint(0, 12)):
            pool.append(ts.make(candidate_id=rng.choice(self.IDS), channel=rng.choice(["naver_a", "naver_b", "github_pages"]), language="ko", topic=rng.choice(self.TOPICS),
                                seed_id=rng.choice([None, None, "s1", "s2"]), search_intent=rng.choice(["selection_guide", "how_to"]), topic_angle=rng.choice(["angle-a", "angle-b"])))
        return pool

    def test_five_thousand_random_pools_give_the_same_groups_as_the_old_pairwise_version(self):
        rng = random.Random(20261106)
        shapes = set()
        for _ in range(5000):
            pool = self.random_pool(rng)
            self.assertEqual(slots.group_same(pool), old_group_same(pool), [(item.candidate_id, item.channel, item.topic, item.seed_id) for item in pool])
            shapes.add(tuple(len(group) for group in old_group_same(pool)))
        self.assertGreater(len(shapes), 20, "시험 입력이 다양한 묶음 모양(겹침·사슬·홀로)을 실제로 만든다")

    def test_the_keys_mean_exactly_what_same_candidate_means(self):
        rng = random.Random(7)
        agree = {True: 0, False: 0}
        for _ in range(1500):
            pool = self.random_pool(rng)
            for left, right in itertools.combinations(pool, 2):
                by_keys = not set(slots.sameness_keys(left)).isdisjoint(slots.sameness_keys(right))
                self.assertEqual(by_keys, slots.same_candidate(left, right))
                agree[by_keys] += 1
        self.assertGreater(min(agree.values()), 500, "같은 쌍과 다른 쌍을 모두 충분히 견줬다")

    def test_a_thousand_candidates_are_counted_in_well_under_the_old_ten_seconds(self):
        pool = [cand(70, cid=f"cand{number:05d}", topic=f"예시 주제 {number} 번째 글 모음", seed_id=f"seed-{number}", source_topic_id=f"src-{number}") for number in range(1000)]
        started = time.monotonic()
        counted = slots.count_slots(pool, 20, NOW)
        self.assertLess(time.monotonic() - started, 4.0, "옛 구현은 1,000개에서 약 10초였다 — 열쇠로 묶으면 0.1초 안팎")
        self.assertEqual((counted.active_existing, counted.remaining), (1000, 0))
        again = [cand(70, cid=f"cand{number:05d}", topic="예시 같은 주제 글", seed_id="seed-1") for number in range(1000)]
        self.assertEqual(slots.count_slots(again, 5000, NOW).active_existing, 1, "전부 같은 후보면 한 번만 센다")

    def test_the_sameness_keys_reject_what_is_not_a_candidate(self):
        with self.assertRaises(TypeError):
            slots.sameness_keys({"candidate_id": "x"})


class PublicNamesTest(unittest.TestCase):
    def test_all_lists_exactly_the_public_names(self):
        for name in slots.__all__:
            self.assertTrue(hasattr(slots, name), name)
        self.assertEqual(len(set(slots.__all__)), len(slots.__all__))


if __name__ == "__main__":
    unittest.main()
