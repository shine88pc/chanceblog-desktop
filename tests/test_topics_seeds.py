"""Seed(씨앗) 시험(`topics/seeds.py`) — 모양과 검증, 유형·소속·협찬 태그·상태 이동, 마지막 선택일, '180일 미선택 쉬게 하기 제안'(제안만 한다), 쓸 수 있는 씨앗 고르기, `seeds.json` 의 엄격한 JSON 모양.

지키는 것:
  1) 씨앗 유형 다섯은 P1 `channels.PER_SEED` 의 이름·순서 그대로이고 유형마다 만들 후보 수·남길 후보 수는 그 표를 따른다. 협찬은 별도 저장소 없이 태그 하나이고 협찬 가능 유형에는 태그가 필수다.
  2) 상태는 제안(승인 전)·사용 중·쉬는 중이며 정해진 길로만 바뀐다. 승인 전(제안) 씨앗은 후보 생성에 쓰이지 않는다. 상태는 일부러 기본값이 없다.
  3) 180일 미선택 제안은 **제안만 돌려주고 씨앗을 바꾸지 않는다** — 정확히 180일(포함)부터이고 기준은 마지막 선택일(없으면 등록일), 사용 중 씨앗만 대상이다. 179일은 아직이다.
  4) `seeds.json` 모양은 엄격하다(schema 1·정확한 칸·모르는 칸·잘못된 타입·같은 번호·같은 소속의 같은 낱말 거절, 어느 번째 씨앗인지 쉬운 한국어로 안내) — 왕복하면 같은 씨앗들이다.
  5) 이 저장소에는 실제 씨앗 목록이 없다 — 시험 자료는 모두 '예시' 로 시작하는 지어낸 낱말이다.
네트워크·파일·실제 시계·난수 없이 돈다(날짜는 늘 인자).
"""
import copy
import dataclasses
import itertools
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402

TODAY = date(2026, 11, 5)


def ago(days):
    """오늘(2026-11-05)로부터 `days`일 전 날짜 글."""
    return (TODAY - timedelta(days=days)).isoformat()


def seed(**changes):
    return ts.example_seed(**changes)


def rejected(test, **changes):
    with test.assertRaises(AppError) as caught:
        seed(**changes)
    test.assertEqual(caught.exception.code, "CONTENT_INVALID")
    test.assertTrue(caught.exception.rendered().message)
    return caught.exception


class ConstantsTest(unittest.TestCase):
    def test_the_seed_types_are_the_five_names_of_the_per_seed_table_in_the_same_order(self):
        self.assertEqual(sd.SEED_TYPES, ("general", "priority", "seasonal", "realtime", "sponsorable"))
        self.assertEqual(sd.SEED_TYPES, tuple(ch.PER_SEED))

    def test_scopes_states_and_the_initial_sizes_are_these(self):
        self.assertEqual(sd.SCOPES, ("common", "github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"))
        self.assertEqual(sd.STATES, ("proposed", "active", "inactive"))
        self.assertEqual((sd.INITIAL_COMMON, sd.INITIAL_PER_CHANNEL, sd.IDLE_DAYS, sd.MAX_SEEDS), (30, 20, 180, 1000))
        self.assertEqual(sd.INITIAL_COMMON + len(ch.CHANNELS) * sd.INITIAL_PER_CHANNEL, 130, "처음 목록은 공통 30 + 채널 20 × 5 = 130")
        self.assertGreater(sd.MAX_SEEDS, 130)
        self.assertEqual(set(sd.STATE_KO), set(sd.STATES))

    def test_the_transitions_are_only_the_documented_ones(self):
        self.assertEqual(dict(sd.TRANSITIONS), {"proposed": ("active", "inactive"), "active": ("inactive",), "inactive": ("active",)})

    def test_the_candidates_per_seed_follow_the_per_seed_table(self):
        for seed_type, quota in ch.PER_SEED.items():
            extra = {"sponsor_tag": "pc_parts"} if seed_type == "sponsorable" else {}
            with self.subTest(seed_type=seed_type):
                self.assertEqual(sd.quota_of(seed(seed_type=seed_type, **extra)), quota)
        self.assertEqual(tuple(sd.quota_of(seed(seed_type="general"))), (3, 2))
        self.assertEqual(tuple(sd.quota_of(seed(seed_type="priority"))), (5, 3))
        with self.assertRaises(TypeError):
            sd.quota_of({"seed_type": "general"})


class SeedShapeTest(unittest.TestCase):
    def test_an_example_seed_has_every_field_and_the_expected_defaults(self):
        made = seed()
        self.assertEqual((made.priority, made.excluded_keywords, made.sponsor_tag, made.last_selected_on), (False, (), None, None))
        self.assertEqual(tuple(made.to_dict()), ("seed_id", "major", "minor", "keyword", "seed_type", "scope", "priority", "excluded_keywords", "sponsor_tag", "state", "registered_on",
                                                 "last_selected_on"))

    def test_the_state_has_no_default_so_an_automatic_proposal_cannot_become_active_by_accident(self):
        with self.assertRaises(TypeError):
            sd.Seed(seed_id="x1", major="가", minor="나", keyword="다", seed_type="general", scope="common", registered_on="2026-05-01")

    def test_a_full_seed_round_trips_through_its_dictionary(self):
        made = seed(priority=True, excluded_keywords=("제외 하나", "제외 둘"), seed_type="sponsorable", sponsor_tag="pc_parts", scope="naver_a", last_selected_on="2026-09-01")
        self.assertEqual(sd.Seed.from_dict(made.to_dict()), made)
        self.assertEqual(made.to_dict()["excluded_keywords"], ["제외 하나", "제외 둘"])

    def test_a_seed_is_frozen_and_hashable(self):
        made = seed()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            made.state = "inactive"
        self.assertEqual(len({made, seed()}), 1)

    def test_every_wrong_value_is_refused_with_the_field_named_in_plain_korean(self):
        bad = (("seed_id", "", "씨앗 번호"), ("seed_id", "한글", "씨앗 번호"), ("seed_id", "x" * 65, "씨앗 번호"), ("seed_id", None, "씨앗 번호"), ("major", "", "대분류"), ("major", "가" * 31, "대분류"),
               ("major", "두  칸", "대분류"), ("major", "<b>굵게</b>", "대분류"), ("major", 3, "대분류"), ("minor", "", "중분류"), ("minor", "줄\n바꿈", "중분류"), ("keyword", "", "씨앗 낱말"),
               ("keyword", "!!!", "씨앗 낱말"), ("keyword", "가" * 61, "씨앗 낱말"), ("keyword", "상위노출 보장", "씨앗 낱말"), ("keyword", "<script>x</script>", "씨앗 낱말"), ("keyword", None, "씨앗 낱말"),
               ("seed_type", "other", "씨앗 유형"), ("seed_type", "General", "씨앗 유형"), ("seed_type", None, "씨앗 유형"), ("scope", "blogger_a", "소속"), ("scope", "all", "소속"), ("scope", "", "소속"),
               ("priority", "yes", "우선 표시"), ("priority", 1, "우선 표시"), ("priority", None, "우선 표시"), ("excluded_keywords", "문자열", "제외 키워드"), ("excluded_keywords", {"가": 1}, "제외 키워드"),
               ("excluded_keywords", ("가", "가"), "제외 키워드"), ("excluded_keywords", ("",), "제외 키워드"), ("excluded_keywords", ("가" * 31,), "제외 키워드"),
               ("excluded_keywords", tuple(f"제외{n}" for n in range(21)), "제외 키워드"), ("excluded_keywords", ("<b>태그</b>",), "제외 키워드"), ("sponsor_tag", "PC_Parts", "협찬 태그"),
               ("sponsor_tag", "pc-parts", "협찬 태그"), ("sponsor_tag", "", "협찬 태그"), ("sponsor_tag", 3, "협찬 태그"), ("state", "ACTIVE", "상태"), ("state", "approved", "상태"), ("state", None, "상태"),
               ("registered_on", "2026-13-01", "등록일"), ("registered_on", "2026-02-30", "등록일"), ("registered_on", "1999-12-31", "등록일"), ("registered_on", "2026-5-1", "등록일"),
               ("registered_on", 20260501, "등록일"), ("registered_on", None, "등록일"), ("last_selected_on", "어제", "마지막 선택일"), ("last_selected_on", "2026-04-30", "마지막 선택일"),
               ("last_selected_on", 3, "마지막 선택일"))
        for name, value, label in bad:
            with self.subTest(**{name: value}):
                self.assertIn(label, rejected(self, **{name: value}).rendered().message)

    def test_the_limits_are_accepted_exactly(self):
        made = seed(seed_id="a" * 64, major="가" * ch.MAX_NAME, minor="나" * ch.MAX_NAME, keyword="다" * sd.MAX_KEYWORD, excluded_keywords=tuple(f"제{n}" for n in range(sd.MAX_EXCLUDED)))
        self.assertEqual((len(made.seed_id), len(made.keyword), len(made.excluded_keywords)), (64, 60, 20))
        self.assertEqual(seed(excluded_keywords=("가" * sd.MAX_EXCLUDED_WORD,)).excluded_keywords, ("가" * 30,))

    def test_every_scope_and_every_state_is_accepted(self):
        for scope in sd.SCOPES:
            self.assertEqual(seed(scope=scope).scope, scope)
        for state in sd.STATES:
            self.assertEqual(seed(state=state).state, state)

    def test_the_error_message_names_the_seed_and_says_what_is_wrong(self):
        error = rejected(self, major="")
        self.assertIn("씨앗의 대분류", error.rendered().message)
        self.assertIn("1~30자", error.rendered().message)
        self.assertIn("CONTENT_INVALID", CATALOG)


class SponsorTagTest(unittest.TestCase):
    def test_the_sponsorable_type_needs_a_tag_and_other_types_may_carry_one(self):
        rejected(self, seed_type="sponsorable")
        rejected(self, seed_type="sponsorable", sponsor_tag=None)
        self.assertEqual(seed(seed_type="sponsorable", sponsor_tag="small_appliance").sponsor_tag, "small_appliance")
        for seed_type in ("general", "priority", "seasonal", "realtime"):
            with self.subTest(seed_type=seed_type):
                self.assertEqual(seed(seed_type=seed_type, sponsor_tag="pc_parts").sponsor_tag, "pc_parts")
                self.assertIsNone(seed(seed_type=seed_type).sponsor_tag)

    def test_there_is_no_separate_sponsor_store_only_a_tag_in_the_same_list(self):
        self.assertFalse([name for name in dir(sd) if "sponsor" in name.lower() and name not in ("STATE_KO",)], "협찬 전용 저장소·목록 이름이 없다")
        self.assertEqual({field.name for field in dataclasses.fields(sd.Seed) if "sponsor" in field.name}, {"sponsor_tag"})

    def test_the_tag_has_the_same_shape_as_the_channel_profile_focus_tags(self):
        for tag in ("pc_parts", "ai_service", "a1", "x"):
            self.assertTrue(ch.is_tag(tag))
            self.assertEqual(seed(sponsor_tag=tag).sponsor_tag, tag)


class DatesAndStatesTest(unittest.TestCase):
    def test_the_last_selection_cannot_be_before_the_registration_but_the_same_day_is_fine(self):
        self.assertEqual(seed(registered_on="2026-05-01", last_selected_on="2026-05-01").last_selected_on, "2026-05-01")
        self.assertEqual(seed(registered_on="2026-05-01", last_selected_on="2026-11-05").last_selected_on, "2026-11-05")
        rejected(self, registered_on="2026-05-01", last_selected_on="2026-04-30")

    def test_a_proposed_seed_has_never_been_selected(self):
        self.assertEqual(seed(state="proposed").last_selected_on, None)
        error = rejected(self, state="proposed", last_selected_on="2026-06-01")
        self.assertIn("승인 전", error.rendered().message)
        self.assertEqual(seed(state="inactive", last_selected_on="2026-06-01").last_selected_on, "2026-06-01")

    def test_each_of_the_nine_state_changes_is_allowed_or_refused_as_documented(self):
        for old, new in itertools.product(sd.STATES, repeat=2):
            with self.subTest(old=old, new=new):
                made = seed(state=old)
                if new in sd.TRANSITIONS[old]:
                    self.assertEqual(sd.change_state(made, new).state, new)
                else:
                    with self.assertRaises(AppError) as caught:
                        sd.change_state(made, new)
                    self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                    self.assertIn("바꿀 수 없다", caught.exception.rendered().message)

    def test_a_state_change_gives_a_new_seed_and_leaves_the_original_alone(self):
        original = seed(state="proposed")
        approved = sd.change_state(original, "active")
        self.assertEqual((original.state, approved.state), ("proposed", "active"))
        self.assertEqual(dataclasses.replace(approved, state="proposed"), original)

    def test_an_unknown_state_name_and_wrong_kinds_are_refused(self):
        for bad in ("ACTIVE", "approved", None, 3):
            with self.subTest(new_state=bad):
                with self.assertRaises(AppError):
                    sd.change_state(seed(), bad)
        with self.assertRaises(TypeError):
            sd.change_state({"state": "active"}, "inactive")

    def test_selecting_records_the_day_and_only_an_active_seed_can_be_selected(self):
        picked = sd.selected(seed(), "2026-08-01")
        self.assertEqual(picked.last_selected_on, "2026-08-01")
        self.assertEqual(sd.selected(picked, "2026-08-01").last_selected_on, "2026-08-01", "같은 날 다시 골라도 된다")
        self.assertEqual(sd.selected(picked, "2026-09-01").last_selected_on, "2026-09-01")
        for state in ("proposed", "inactive"):
            with self.subTest(state=state):
                with self.assertRaises(AppError):
                    sd.selected(seed(state=state), "2026-08-01")

    def test_selecting_cannot_go_back_in_time(self):
        picked = sd.selected(seed(registered_on="2026-05-01"), "2026-08-01")
        with self.assertRaises(AppError):
            sd.selected(picked, "2026-07-31")
        with self.assertRaises(AppError):
            sd.selected(seed(registered_on="2026-05-01"), "2026-04-30")
        for bad in ("어제", None, "2026-13-01", 3):
            with self.assertRaises(AppError):
                sd.selected(seed(), bad)


class IdleProposalTest(unittest.TestCase):
    def test_exactly_180_days_is_proposed_and_179_is_not(self):
        for days, expected in ((179, False), (180, True), (181, True), (0, False), (365, True)):
            with self.subTest(days=days):
                found = sd.idle_proposals([seed(registered_on=ago(days + 30), last_selected_on=ago(days))], ago(0))
                self.assertEqual(bool(found), expected)

    def test_the_basis_is_the_last_selection_and_without_one_the_registration_day(self):
        selected_long_ago = seed(seed_id="s1", registered_on=ago(400), last_selected_on=ago(10))
        never_selected_long = seed(seed_id="s2", registered_on=ago(200))
        never_selected_new = seed(seed_id="s3", registered_on=ago(100))
        found = sd.idle_proposals([selected_long_ago, never_selected_long, never_selected_new], ago(0))
        self.assertEqual([(item.seed_id, item.idle_days, item.never_selected, item.since) for item in found], [("s2", 200, True, ago(200))])

    def test_only_active_seeds_are_candidates_for_a_rest_proposal(self):
        old = {"registered_on": ago(400)}
        pool = [seed(seed_id="a", state="active", **old), seed(seed_id="p", state="proposed", **old), seed(seed_id="i", state="inactive", **old)]
        self.assertEqual([item.seed_id for item in sd.idle_proposals(pool, ago(0))], ["a"])

    def test_the_longest_idle_comes_first_and_ties_are_ordered_by_number(self):
        pool = [seed(seed_id="b", registered_on=ago(300)), seed(seed_id="a", registered_on=ago(300)), seed(seed_id="c", registered_on=ago(500)), seed(seed_id="d", registered_on=ago(190))]
        for order in itertools.permutations(pool):
            self.assertEqual([item.seed_id for item in sd.idle_proposals(order, ago(0))], ["c", "a", "b", "d"])

    def test_proposals_only_propose_and_change_nothing(self):
        pool = [seed(seed_id="a", registered_on=ago(400)), seed(seed_id="b", registered_on=ago(400), keyword="예시 씨앗 둘")]
        before = copy.deepcopy([item.to_dict() for item in pool])
        found = sd.idle_proposals(pool, ago(0))
        self.assertEqual(len(found), 2)
        self.assertEqual([item.to_dict() for item in pool], before)
        self.assertTrue(all(item.state == "active" for item in pool))

    def test_the_number_of_days_can_be_changed_and_is_checked(self):
        pool = [seed(registered_on=ago(100))]
        self.assertEqual(len(sd.idle_proposals(pool, ago(0), days=100)), 1)
        self.assertEqual(len(sd.idle_proposals(pool, ago(0), days=101)), 0)
        for bad in (0, -1, 3651, True, 180.0, None, "180"):
            with self.subTest(days=bad):
                with self.assertRaises(AppError):
                    sd.idle_proposals(pool, ago(0), days=bad)

    def test_idle_days_counts_from_the_basis_and_never_goes_below_zero(self):
        made = seed(registered_on="2026-05-01", last_selected_on="2026-06-01")
        self.assertEqual(sd.idle_days(made, "2026-06-01"), 0)
        self.assertEqual(sd.idle_days(made, "2026-06-02"), 1)
        self.assertEqual(sd.idle_days(made, "2026-05-01"), 0, "오늘이 기준보다 앞서면 0")
        self.assertEqual(sd.idle_days(seed(registered_on="2026-05-01"), "2026-05-09"), 8)
        self.assertEqual(sd.idle_days(seed(registered_on="2026-05-01"), "2027-05-01"), 365)

    def test_today_is_always_an_argument_and_a_wrong_one_is_refused(self):
        for bad in ("어제", None, "2026-13-01", 20261105, "2026-11-5"):
            with self.subTest(today=bad):
                with self.assertRaises(AppError):
                    sd.idle_proposals([seed()], bad)
                with self.assertRaises(AppError):
                    sd.idle_days(seed(), bad)

    def test_the_sentence_says_how_long_and_that_nothing_changes_before_approval(self):
        never = sd.idle_proposals([seed(registered_on=ago(200), keyword="예시 씨앗 하나")], ago(0))[0].message()
        self.assertIn("예시 씨앗 하나", never)
        self.assertIn("한 번도 선택하지 않았고 200일", never)
        self.assertIn("승인 전에는 바뀌지 않습니다", never)
        again = sd.idle_proposals([seed(registered_on=ago(300), last_selected_on=ago(190))], ago(0))[0].message()
        self.assertIn("마지막으로 선택한 뒤 190일", again)

    def test_wrong_kinds_are_programming_errors(self):
        with self.assertRaises(TypeError):
            sd.idle_proposals([{"state": "active"}], ago(0))
        with self.assertRaises(TypeError):
            sd.idle_days({"registered_on": "2026-01-01"}, ago(0))


class UsableSeedsTest(unittest.TestCase):
    def pool(self):
        return [
            seed(seed_id="c1", major="나 대분류", minor="가 중분류", keyword="예시 공통 씨앗 하나", scope="common"),
            seed(seed_id="c2", major="가 대분류", minor="가 중분류", keyword="예시 공통 씨앗 둘", scope="common", priority=True),
            seed(seed_id="a1", major="가 대분류", minor="나 중분류", keyword="예시 에이 씨앗", scope="naver_a"),
            seed(seed_id="b1", major="가 대분류", minor="나 중분류", keyword="예시 비 씨앗", scope="naver_b"),
            seed(seed_id="b2", major="가 대분류", minor="가 중분류", keyword="예시 비 우선 씨앗", scope="naver_b", priority=True),
            seed(seed_id="p1", keyword="예시 제안 씨앗", scope="common", state="proposed"),
            seed(seed_id="i1", keyword="예시 쉬는 씨앗", scope="common", state="inactive"),
            seed(seed_id="e1", keyword="예시 영문 씨앗", scope="blogger_en"),
        ]

    def test_a_channel_gets_the_common_seeds_and_its_own_and_only_the_active_ones(self):
        self.assertEqual([item.seed_id for item in sd.usable_seeds(self.pool(), "naver_b")], ["c2", "b2", "b1", "c1"])      # 우선 표시 둘(c2·b2)이 앞 — 같은 대분류·중분류라 씨앗 낱말 순(공통 < 비)
        self.assertEqual([item.seed_id for item in sd.usable_seeds(self.pool(), "naver_a")], ["c2", "a1", "c1"])
        self.assertEqual([item.seed_id for item in sd.usable_seeds(self.pool(), "blogger_en")], ["c2", "c1", "e1"])
        self.assertEqual([item.seed_id for item in sd.usable_seeds(self.pool(), "github_pages")], ["c2", "c1"])

    def test_a_proposed_seed_is_never_used_until_it_is_approved(self):
        pool = self.pool()
        self.assertNotIn("p1", [item.seed_id for key in ch.CHANNELS for item in sd.usable_seeds(pool, key)])
        approved = [sd.change_state(item, "active") if item.seed_id == "p1" else item for item in pool]
        self.assertIn("p1", [item.seed_id for item in sd.usable_seeds(approved, "naver_b")])

    def test_priority_seeds_come_first_then_major_minor_keyword_and_number(self):
        self.assertEqual([item.seed_id for item in sd.usable_seeds(self.pool(), "naver_b")][:2], ["c2", "b2"])
        flat = [seed(seed_id=f"s{n}", keyword=f"예시 씨앗 {n}") for n in (3, 1, 2)]
        self.assertEqual([item.seed_id for item in sd.usable_seeds(flat, "naver_b")], ["s1", "s2", "s3"])

    def test_the_result_does_not_depend_on_the_input_order(self):
        pool = self.pool()[:5]
        expected = sd.usable_seeds(pool, "naver_b")
        for order in itertools.permutations(pool):
            self.assertEqual(sd.usable_seeds(list(order), "naver_b"), expected)

    def test_the_strategy_aliases_of_the_blogger_channels_are_accepted_as_input_only(self):
        pool = self.pool()
        self.assertEqual(sd.usable_seeds(pool, "blogger_b"), sd.usable_seeds(pool, "blogger_en"))
        self.assertEqual(sd.usable_seeds(pool, "blogger_a"), sd.usable_seeds(pool, "blogger_ko"))
        with self.assertRaises(AppError):
            seed(scope="blogger_b")

    def test_an_unknown_channel_and_wrong_kinds_are_refused(self):
        for bad in ("naver", "", None, 3):
            with self.subTest(channel=bad):
                with self.assertRaises(AppError):
                    sd.usable_seeds(self.pool(), bad)
        with self.assertRaises(TypeError):
            sd.usable_seeds([{"state": "active"}], "naver_b")

    def test_an_empty_list_gives_nothing_and_the_input_is_not_changed(self):
        self.assertEqual(sd.usable_seeds([], "naver_b"), ())
        pool = self.pool()
        before = [item.to_dict() for item in pool]
        sd.usable_seeds(iter(pool), "naver_b")
        self.assertEqual([item.to_dict() for item in pool], before)


class JsonShapeTest(unittest.TestCase):
    def several(self):
        return [seed(seed_id="s1", keyword="예시 씨앗 하나"), seed(seed_id="s2", keyword="예시 씨앗 둘", scope="naver_a", priority=True, excluded_keywords=("제외",)),
                seed(seed_id="s3", keyword="예시 씨앗 셋", seed_type="sponsorable", sponsor_tag="pc_parts", state="proposed"),
                seed(seed_id="s4", keyword="예시 씨앗 넷", state="inactive", last_selected_on="2026-07-01")]

    def test_the_empty_template_has_the_schema_and_an_empty_list(self):
        self.assertEqual(sd.seeds_to_dict(()), {"schema": 1, "seeds": []})
        self.assertEqual(sd.seeds_from_dict({"schema": 1, "seeds": []}), ())

    def test_the_seeds_round_trip_in_the_same_order(self):
        data = sd.seeds_to_dict(self.several())
        self.assertEqual(tuple(data), ("schema", "seeds"))
        self.assertEqual(sd.seeds_from_dict(data), tuple(self.several()))
        self.assertEqual(sd.seeds_to_dict(sd.seeds_from_dict(data)), data)
        self.assertEqual([entry["seed_id"] for entry in data["seeds"]], ["s1", "s2", "s3", "s4"])

    def test_a_wrong_schema_or_top_level_shape_is_refused(self):
        good = sd.seeds_to_dict(self.several())
        for bad in (None, [], "x", 3, {}, dict(good, schema=0), dict(good, schema=2), dict(good, schema=True), dict(good, schema="1"), dict(good, schema=1.0), dict(good, extra=1),
                    {"schema": 1}, {"seeds": []}, dict(good, seeds={}), dict(good, seeds="x"), dict(good, seeds=None)):
            with self.subTest(bad=repr(bad)[:40]):
                with self.assertRaises(AppError) as caught:
                    sd.seeds_from_dict(bad)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_an_entry_with_an_unknown_or_missing_field_or_a_wrong_type_is_refused_and_the_number_is_in_the_message(self):
        good = sd.seeds_to_dict(self.several())
        for index in range(len(good["seeds"])):
            for name in good["seeds"][index]:
                missing = copy.deepcopy(good)
                del missing["seeds"][index][name]
                with self.subTest(index=index, missing=name):
                    with self.assertRaises(AppError) as caught:
                        sd.seeds_from_dict(missing)
                    self.assertIn(f"{index + 1}번째 씨앗", caught.exception.rendered().message)
        extra = copy.deepcopy(good)
        extra["seeds"][1]["unknown"] = 1
        with self.assertRaises(AppError) as caught:
            sd.seeds_from_dict(extra)
        self.assertIn("2번째 씨앗", caught.exception.rendered().message)
        self.assertIn("모르는 칸", caught.exception.rendered().message)
        for bad_entry in (None, [], "x", 3):
            broken = copy.deepcopy(good)
            broken["seeds"][2] = bad_entry
            with self.subTest(entry=repr(bad_entry)):
                with self.assertRaises(AppError) as caught:
                    sd.seeds_from_dict(broken)
                self.assertIn("3번째 씨앗", caught.exception.rendered().message)

    def test_every_field_with_a_wrong_type_is_refused_when_reading(self):
        good = sd.seeds_to_dict(self.several())
        wrong = {"seed_id": 3, "major": None, "minor": [], "keyword": 5, "seed_type": 1, "scope": None, "priority": "true", "excluded_keywords": "x", "sponsor_tag": 3, "state": 0,
                 "registered_on": 20260501, "last_selected_on": 3}
        for name, value in wrong.items():
            broken = copy.deepcopy(good)
            broken["seeds"][0][name] = value
            with self.subTest(field=name):
                with self.assertRaises(AppError):
                    sd.seeds_from_dict(broken)

    def test_the_same_number_twice_or_the_same_word_in_the_same_scope_twice_is_refused(self):
        with self.assertRaises(AppError) as caught:
            sd.seeds_from_dict(sd.seeds_to_dict([seed(seed_id="same", keyword="예시 하나"), seed(seed_id="same", keyword="예시 둘")]))
        self.assertIn("같은 씨앗 번호", caught.exception.rendered().message)
        for second in ("예시 하나", "예시하나", "예시  하나".replace("  ", " "), "예시 하나!", "ＹＥ".replace("ＹＥ", "예시") + " 하나"):
            with self.subTest(second=second):
                with self.assertRaises(AppError) as caught:
                    sd.seeds_to_dict([seed(seed_id="a", keyword="예시 하나"), seed(seed_id="b", keyword=second)])
                self.assertIn("같은 씨앗 낱말", caught.exception.rendered().message)
        self.assertEqual(len(sd.seeds_to_dict([seed(seed_id="a", keyword="예시 하나", scope="common"), seed(seed_id="b", keyword="예시 하나", scope="naver_a")])["seeds"]), 2)

    def test_the_size_limit_is_enforced_both_ways(self):
        many = [seed(seed_id=f"s{n}", keyword=f"예시 씨앗 {n}") for n in range(sd.MAX_SEEDS)]
        data = sd.seeds_to_dict(many)
        self.assertEqual(len(sd.seeds_from_dict(data)), sd.MAX_SEEDS)
        with self.assertRaises(AppError):
            sd.seeds_to_dict(many + [seed(seed_id="one-more", keyword="예시 하나 더")])
        data["seeds"].append(dict(data["seeds"][0], seed_id="one-more", keyword="예시 하나 더"))
        with self.assertRaises(AppError):
            sd.seeds_from_dict(data)

    def test_only_seeds_can_be_written(self):
        for bad in ([{"seed_id": "x"}], [None], ["x"]):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(AppError):
                    sd.seeds_to_dict(bad)

    def test_the_dictionary_is_plain_data_the_caller_can_dump_as_json(self):
        import json
        data = sd.seeds_to_dict(self.several())
        self.assertEqual(sd.seeds_from_dict(json.loads(json.dumps(data, ensure_ascii=False))), tuple(self.several()))

    def test_reading_does_not_change_the_input(self):
        data = sd.seeds_to_dict(self.several())
        before = copy.deepcopy(data)
        sd.seeds_from_dict(data)
        self.assertEqual(data, before)


class NoRealSeedsTest(unittest.TestCase):
    def test_the_module_holds_no_seed_list_only_the_schema_rules_and_the_empty_template(self):
        lists = [name for name, value in vars(sd).items() if isinstance(value, (tuple, list)) and value and all(isinstance(item, sd.Seed) for item in value)]
        self.assertEqual(lists, [])
        self.assertEqual(sd.seeds_to_dict(()), {"schema": 1, "seeds": []})

    def test_every_seed_used_in_the_tests_is_marked_as_an_example(self):
        for made in (ts.example_seed(), *UsableSeedsTest().pool(), *JsonShapeTest().several()):
            with self.subTest(keyword=made.keyword):
                self.assertTrue(made.keyword.startswith("예시") or made.keyword == "예시 씨앗 하나")
                self.assertTrue(made.major.endswith("대분류") or made.major.startswith("예시"))


if __name__ == "__main__":
    unittest.main()
