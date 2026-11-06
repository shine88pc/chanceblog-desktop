"""씨앗 판 2(P3b-1 S1) 시험 — 새 칸 열두 개와 기본값·판 1·2 읽기와 판 3 거절·대상 유형 11개와 묶음 3개·허용 채널·계절 일정 칸·씨앗 제안 파일 읽기(모두 승인 전)·채널별 사용 가능 수.

입력은 모두 시험용으로 지어낸 **예시**이고 실제 씨앗·블로그 값이 아니다. 네트워크·파일·시계 없이 돈다(날짜는 인자로 준다).
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import schedule as sc  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.topics import wording as wd  # noqa: E402

V1_KEYS = ("seed_id", "major", "minor", "keyword", "seed_type", "scope", "priority", "excluded_keywords", "sponsor_tag", "state", "registered_on", "last_selected_on", "active_since")
NEW_KEYS = ("target_type", "allowed_channels", "priority_keywords", "reason", "needs_region", "brand_case", "prepare_from", "publish_from", "publish_until", "peak_period", "recurrence",
            "seasonal_priority_state")
SEASON = dict(seed_type="seasonal", prepare_from="12-05", publish_from="12-20", publish_until="01-20", peak_period=("12-28", "01-10"), recurrence="yearly")


def seed(**changes):
    return ts.example_seed(**changes)


def refused(test, **changes):
    with test.assertRaises(AppError) as caught:
        seed(**changes)
    test.assertEqual(caught.exception.code, "CONTENT_INVALID")
    return caught.exception.slots["항목"]


class DefaultsTest(unittest.TestCase):
    def test_the_new_fields_all_have_defaults_so_a_version_1_seed_is_built_unchanged(self):
        made = seed()
        self.assertEqual((made.target_type, made.priority_keywords, made.reason, made.needs_region, made.brand_case), (None, (), "", False, False))
        self.assertEqual((made.prepare_from, made.publish_from, made.publish_until, made.peak_period, made.recurrence, made.seasonal_priority_state), (None,) * 6)
        self.assertEqual(sd._KEYS, V1_KEYS + NEW_KEYS)
        self.assertEqual(set(sd.SEED_FIELD_KO), set(sd._KEYS), "모든 칸에 쉬운 한국어 이름이 있다")

    def test_the_default_allowed_channels_keep_the_old_behaviour(self):
        self.assertEqual(seed(scope="common").allowed_channels, ch.CHANNELS, "판 1 의 공통 씨앗은 다섯 채널 모두에서 쓰였다 — 그대로")
        for code in ch.CHANNELS:
            self.assertEqual(seed(scope=code).allowed_channels, (code,))

    def test_idle_days_is_the_seed_inactive_review_constant_so_the_number_lives_in_one_place(self):
        self.assertEqual((sd.IDLE_DAYS, sc.SEED_INACTIVE_REVIEW_DAYS), (180, 180))
        self.assertIs(sd.IDLE_DAYS, sc.SEED_INACTIVE_REVIEW_DAYS)


class JsonVersionTest(unittest.TestCase):
    def v1_file(self):
        return {"schema": 1, "seeds": [{key: value for key, value in seed(seed_id="ex-a", keyword="예시 하나").to_dict().items() if key in V1_KEYS},
                                       {key: value for key, value in seed(seed_id="ex-b", keyword="예시 둘", scope="naver_a").to_dict().items() if key in V1_KEYS}]}

    def test_it_writes_version_2_and_reads_both_1_and_2(self):
        data = sd.seeds_to_dict((seed(),))
        self.assertEqual(data["schema"], 2)
        self.assertEqual(sd.seeds_from_dict(data), (seed(),))
        self.assertEqual(sd.SCHEMAS, (1, 2))
        self.assertEqual(sd.seeds_from_dict({"schema": 1, "seeds": []}), ())

    def test_a_version_1_file_reads_with_defaults_and_the_input_is_not_touched(self):
        old = self.v1_file()
        before = copy.deepcopy(old)
        found = sd.seeds_from_dict(old)
        self.assertEqual(old, before, "읽어도 입력(파일 내용)은 바뀌지 않는다 — 몰래 다시 쓰지 않는다")
        self.assertEqual([item.seed_id for item in found], ["ex-a", "ex-b"])
        self.assertEqual(found[0].allowed_channels, ch.CHANNELS)
        self.assertEqual(found[1].allowed_channels, ("naver_a",))
        self.assertTrue(all(item.target_type is None and item.reason == "" for item in found))
        again = sd.seeds_to_dict(found)
        self.assertEqual(again["schema"], 2)
        self.assertEqual(sd.seeds_from_dict(again), found, "판 2 로 올려 써도 같은 씨앗이다")

    def test_a_newer_version_is_refused_safely_with_an_update_hint(self):
        for version in (3, 4, 99):
            with self.subTest(version=version):
                with self.assertRaises(AppError) as caught:
                    sd.seeds_from_dict({"schema": version, "seeds": []})
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                self.assertIn("업데이트", caught.exception.slots["항목"])
        for bad in (0, -1, True, "2", 2.0, None):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(AppError):
                    sd.seeds_from_dict({"schema": bad, "seeds": []})

    def test_the_two_versions_keep_their_exact_field_sets(self):
        v1 = self.v1_file()
        v1["seeds"][0]["target_type"] = "product"                               # 판 1 파일에 판 2 칸이 있으면 모르는 칸이다
        with self.assertRaises(AppError):
            sd.seeds_from_dict(v1)
        v2 = sd.seeds_to_dict((seed(),))
        for name in NEW_KEYS:
            with self.subTest(missing=name):
                broken = copy.deepcopy(v2)
                del broken["seeds"][0][name]
                with self.assertRaises(AppError) as caught:
                    sd.seeds_from_dict(broken)
                self.assertIn("1번째 씨앗", caught.exception.rendered().message)
        extra = copy.deepcopy(v2)
        extra["seeds"][0]["unknown"] = 1
        with self.assertRaises(AppError):
            sd.seeds_from_dict(extra)

    def test_every_new_field_survives_a_round_trip(self):
        full = seed(seed_type="seasonal", scope="common", target_type="place_lodging", allowed_channels=("naver_b", "naver_a"), priority_keywords=("우선 하나",), reason="예시 이유",
                    needs_region=True, keyword="{기준 지역} 예시 단풍", brand_case=True, seasonal_priority_state="preparing", **{k: v for k, v in SEASON.items() if k != "seed_type"})
        data = sd.seeds_to_dict((full,))
        self.assertEqual(data["seeds"][0]["allowed_channels"], ["naver_a", "naver_b"], "코드의 채널 순서로 정리해 저장한다")
        self.assertEqual(data["seeds"][0]["peak_period"], ["12-28", "01-10"])
        self.assertEqual(sd.seeds_from_dict(data), (full,))


class TargetTypeTest(unittest.TestCase):
    def test_eleven_types_and_three_bundles_each_have_a_korean_name(self):
        self.assertEqual(len(sd.TARGET_TYPES), 11)
        self.assertEqual([wd.TARGET_TYPE_KO[key] for key in sd.TARGET_TYPES], ["제품", "장소", "숙박", "서비스", "SaaS", "PC 부품", "문제", "생활 습관", "실시간 이슈", "정책", "API"])
        self.assertEqual(sd.TARGET_BUNDLES, ("place_lodging", "service_saas", "policy_api"))
        self.assertEqual([wd.TARGET_TYPE_KO[key] for key in sd.TARGET_BUNDLES], ["장소·숙박", "서비스·SaaS", "정책·API"])
        self.assertEqual(tuple(wd.TARGET_TYPE_KO), sd.ALL_TARGET_TYPES)

    def test_each_type_is_accepted_and_the_rest_are_refused_with_korean_names(self):
        for key in sd.ALL_TARGET_TYPES:
            self.assertEqual(seed(target_type=key).target_type, key)
        message = refused(self, target_type="gadget")
        self.assertIn("‘제품’", message)
        self.assertNotIn("product", message, "영문 값 이름은 화면 글에 없다")
        refused(self, target_type=7)

    def test_importance_and_target_type_are_independent_axes(self):
        for importance in sd.SEED_TYPES:
            for key in ("product", "api"):
                tag = {"sponsor_tag": "pc_parts"} if importance == "sponsorable" else {}
                made = seed(seed_type=importance, target_type=key, **tag)
                self.assertEqual((made.seed_type, made.target_type), (importance, key))
                self.assertEqual(sd.quota_of(made), ch.PER_SEED[importance], "후보 생성 수는 중요도가 정한다 — 대상 유형은 건드리지 않는다")


class AllowedChannelsTest(unittest.TestCase):
    def test_a_common_seed_needs_at_least_one_channel_and_is_stored_in_code_order(self):
        self.assertEqual(seed(scope="common", allowed_channels=("naver_b", "github_pages")).allowed_channels, ("github_pages", "naver_b"))
        self.assertEqual(seed(scope="common", allowed_channels=["naver_a"]).allowed_channels, ("naver_a",))
        for bad in ((), [], ("naver_a", "naver_a"), ("naver_c",), ("blogger_a",), "naver_a", ("naver_a", 3), 5):
            with self.subTest(bad=repr(bad)):
                refused(self, scope="common", allowed_channels=bad)

    def test_a_channel_seed_allows_only_its_own_channel(self):
        self.assertEqual(seed(scope="naver_a", allowed_channels=("naver_a",)).allowed_channels, ("naver_a",))
        message = refused(self, scope="naver_a", allowed_channels=("naver_a", "naver_b"))
        self.assertIn("공통", message)
        refused(self, scope="naver_a", allowed_channels=("naver_b",))

    def test_the_message_names_channels_in_korean(self):
        message = refused(self, scope="common", allowed_channels=("zzz",))
        self.assertIn("‘네이버 A’", message)
        self.assertNotIn("naver_a", message)


class OtherFieldsTest(unittest.TestCase):
    def test_priority_keywords_are_a_separate_word_list_from_the_priority_flag(self):
        made = seed(priority=True, priority_keywords=("우선 하나", "우선 둘"))
        self.assertEqual((made.priority, made.priority_keywords), (True, ("우선 하나", "우선 둘")))
        self.assertEqual(seed(priority=False, priority_keywords=("우선",)).priority, False)
        refused(self, priority_keywords=("같은", "같은"))
        refused(self, priority_keywords="문자열")
        refused(self, priority_keywords=tuple(f"낱말{number}" for number in range(sd.MAX_PRIORITY_KEYWORDS + 1)))
        self.assertEqual(len(seed(priority_keywords=tuple(f"낱말{number}" for number in range(sd.MAX_PRIORITY_KEYWORDS))).priority_keywords), sd.MAX_PRIORITY_KEYWORDS)
        refused(self, excluded_keywords=("겹침",), priority_keywords=("겹침",))

    def test_the_reason_is_one_line_up_to_200_characters(self):
        self.assertEqual(seed(reason="가" * 200).reason, "가" * 200)
        refused(self, reason="가" * 201)
        refused(self, reason="두 줄\n입니다")
        refused(self, reason="<script>x</script>")
        refused(self, reason=5)

    def test_the_region_placeholder_and_the_needs_region_flag_must_agree(self):
        made = seed(keyword="{기준 지역} 예시 나들이", needs_region=True)
        self.assertEqual(sd.with_region(made, "예시시").keyword, "예시시 예시 나들이")
        self.assertFalse(sd.with_region(made, "예시시").needs_region)
        plain = seed()
        self.assertIs(sd.with_region(plain, "예시시"), plain, "자리표시가 없는 씨앗은 그대로 돌려준다")
        message = refused(self, keyword="{기준 지역} 예시 나들이", needs_region=False)
        self.assertIn("지역", message)
        refused(self, keyword="예시 나들이", needs_region=True)
        with self.assertRaises(AppError):
            sd.with_region(made, "  ")

    def test_a_brand_exception_needs_its_reason(self):
        self.assertTrue(seed(brand_case=True, reason="예시 허용 사유").brand_case)
        refused(self, brand_case=True)
        refused(self, brand_case="네")


class SeasonFieldsTest(unittest.TestCase):
    def test_the_season_fields_are_only_for_the_seasonal_importance_and_all_three_dates_come_together(self):
        made = seed(**SEASON)
        self.assertEqual((made.prepare_from, made.publish_from, made.publish_until, made.peak_period, made.recurrence), ("12-05", "12-20", "01-20", ("12-28", "01-10"), "yearly"))
        refused(self, **{**SEASON, "seed_type": "general"})
        refused(self, seed_type="seasonal", prepare_from="12-05", publish_from="12-20")
        refused(self, seed_type="seasonal", recurrence="yearly")
        refused(self, seed_type="seasonal", peak_period=("01-01", "01-02"))
        self.assertIsNone(seed(seed_type="seasonal").prepare_from, "일정이 없는 계절 씨앗(판 1)은 그대로 만들어진다")

    def test_recurrence_defaults_to_yearly_when_dates_are_given(self):
        made = seed(seed_type="seasonal", prepare_from="12-05", publish_from="12-20", publish_until="01-20")
        self.assertEqual(made.recurrence, "yearly")
        self.assertEqual(seed(seed_type="seasonal", recurrence="monthly", prepare_from="20", publish_from="25", publish_until="05").recurrence, "monthly")
        refused(self, **{**SEASON, "recurrence": "weekly"})

    def test_the_date_rules_match_the_calendar_entry_rules(self):
        refused(self, **{**SEASON, "prepare_from": "02-29"})                                 # 2월 29일은 없다
        refused(self, **{**SEASON, "publish_from": "13-01"})
        refused(self, **{**SEASON, "prepare_from": "05-01"})                                 # 준비 시작이 발행 시작보다 180일을 넘게 앞선다
        refused(self, **{**SEASON, "publish_until": "07-15"})                                # 발행 기간 183일 초과
        refused(self, **{**SEASON, "peak_period": ("03-01", "03-05")})                       # 피크가 발행 기간 밖
        refused(self, **{**SEASON, "peak_period": ("01-10", "12-28")})                       # 피크 끝이 시작보다 앞선다
        refused(self, **{**SEASON, "peak_period": ("12-28",)})
        self.assertEqual(seed(**{**SEASON, "peak_period": None}).peak_period, None)

    def test_the_monthly_dates_are_two_digit_days_1_to_28(self):
        monthly = dict(seed_type="seasonal", recurrence="monthly")
        self.assertEqual(seed(**monthly, prepare_from="20", publish_from="25", publish_until="05", peak_period=("27", "03")).publish_until, "05")
        for bad in ("00", "29", "5", "ab", "1-5", "２０"):
            with self.subTest(bad=bad):
                refused(self, **monthly, prepare_from=bad, publish_from="25", publish_until="05")
        refused(self, **monthly, prepare_from="20", publish_from="25", publish_until="05", peak_period=("10", "03"))

    def test_the_stored_state_must_be_a_known_state(self):
        for state in sc.SEASON_STATES:
            self.assertEqual(seed(**SEASON, seasonal_priority_state=state).seasonal_priority_state, state)
        refused(self, **SEASON, seasonal_priority_state="resting")
        self.assertEqual(set(wd.SEASONAL_STATE_KO), set(sc.SEASON_STATES))
        self.assertEqual(set(wd.RECURRENCE_KO), set(sc.RECURRENCES))


def pair_seeds():
    """예시 씨앗 130개 — 공통 30(허용 채널 짝은 아래 표)과 채널 전용 20×5. 모두 사용 중이고 낱말은 번호뿐이다(실제 씨앗 목록이 아니다)."""
    pairs = ([("naver_b", "github_pages")] * 8 + [("blogger_ko", "naver_a")] * 6 + [("blogger_ko", "blogger_en")] * 6 + [("naver_a", "naver_b")] * 4 + [("blogger_ko", "naver_b")] * 3 +
             [("github_pages", "naver_a"), ("github_pages", "blogger_en"), ("github_pages", "blogger_ko")])
    made = [seed(seed_id=f"ex-c{number:03d}", keyword=f"예시 공통 {number}", scope="common", allowed_channels=pair) for number, pair in enumerate(pairs, start=1)]
    for code in ch.CHANNELS:
        made += [seed(seed_id=f"ex-{code}-{number:02d}", keyword=f"예시 {code} {number}", scope=code) for number in range(1, 21)]
    return made


class UsableSeedsTest(unittest.TestCase):
    PROFILES = {profile.key: profile for profile in ch.default_profiles()}

    def test_the_example_pool_has_the_planned_shape(self):
        pool = pair_seeds()
        self.assertEqual((len(pool), sum(item.scope == "common" for item in pool)), (130, 30))

    def test_allowed_channels_decide_who_can_use_a_common_seed(self):
        pool = pair_seeds()
        counts = {code: len(sd.usable_seeds(pool, code)) for code in ch.CHANNELS}
        # 승인되었다고 가정하면 채널마다 GitHub Pages 31·Blogger 영문 27·Blogger 한글 36·네이버 A 31·네이버 B 35 (제안 노트 §5 의 숫자 — 소속만 보면 채널마다 50)
        self.assertEqual(counts, {"github_pages": 31, "blogger_en": 27, "blogger_ko": 36, "naver_a": 31, "naver_b": 35})
        self.assertEqual(sum(counts.values()), 100 + 60)

    def test_with_a_profile_only_the_channels_that_generate_candidates_use_seeds(self):
        pool = pair_seeds()
        counts = {code: len(sd.usable_seeds(pool, profile)) for code, profile in self.PROFILES.items()}
        self.assertEqual(counts, {"github_pages": 0, "blogger_en": 0, "blogger_ko": 0, "naver_a": 31, "naver_b": 35}, "첫 버전: 네이버 A·B 만 켜짐")
        turned_on = ch.ChannelProfile.from_dict(dict(self.PROFILES["github_pages"].to_dict(), generation_enabled=True))
        self.assertEqual(len(sd.usable_seeds(pool, turned_on)), 31)

    def test_a_seed_that_is_not_active_or_not_allowed_is_never_used(self):
        proposed = seed(seed_id="ex-p", keyword="예시 승인 전", scope="naver_a", state="proposed")
        resting = seed(seed_id="ex-r", keyword="예시 쉬는 중", scope="naver_a", state="inactive")
        only_b = seed(seed_id="ex-b", keyword="예시 B만", scope="common", allowed_channels=("naver_b",))
        pool = (proposed, resting, only_b, seed(seed_id="ex-ok", keyword="예시 쓸 수 있음", scope="naver_a"))
        self.assertEqual([item.seed_id for item in sd.usable_seeds(pool, "naver_a")], ["ex-ok"])
        self.assertEqual([item.seed_id for item in sd.usable_seeds(pool, "naver_b")], ["ex-b"])
        self.assertEqual([item.seed_id for item in sd.usable_seeds(pool, "blogger_a")], [], "별칭도 받는다")

    def test_a_version_1_common_seed_is_still_usable_on_every_channel(self):
        old = seed(seed_id="ex-old", keyword="예시 옛 공통", scope="common")
        self.assertEqual([code for code in ch.CHANNELS if sd.usable_seeds((old,), code)], list(ch.CHANNELS), "판 1 의 현재 값 — 공통 씨앗은 다섯 채널 모두에 쓰였다")

    def test_the_order_is_unchanged_priority_first_then_names(self):
        pool = (seed(seed_id="ex-2", keyword="예시 나", scope="naver_a"), seed(seed_id="ex-1", keyword="예시 가", scope="naver_a"), seed(seed_id="ex-3", keyword="예시 다", scope="naver_a", priority=True))
        self.assertEqual([item.seed_id for item in sd.usable_seeds(pool, "naver_a")], ["ex-3", "ex-1", "ex-2"])


def proposal(**changes):
    """제안 파일의 씨앗 한 건(예시 값 — 실제 목록이 아니다)."""
    base = {"id": "EX001", "scope": "naver_a", "allowed_channels": ["naver_a"], "language": "ko", "category_l1": "예시 대분류", "category_l2": "예시 중분류", "keyword": "예시 제습기", "target_type": "product",
            "importance": "general", "priority_keywords": ["예시 우선"], "exclude_keywords": ["예시 제외"], "monetization_tags": [], "reason": "예시 이유", "generation": "active_first",
            "needs_region": False, "brand_case": False}
    base.update(changes)
    return base


def proposal_file(*entries, **top):
    return {"schema_note": "예시", "proposal_version": "v1", "default_status": "proposed", "seeds": list(entries), **top}


class ProposalReadTest(unittest.TestCase):
    TODAY = "2026-11-06"

    def read(self, *entries, **top):
        return sd.parse_proposals(proposal_file(*entries, **top), self.TODAY)

    def test_every_column_of_a_proposal_lands_in_a_seed_field(self):
        full = proposal(id="EX010", scope="common", allowed_channels=["naver_b", "github_pages"], importance="seasonal", target_type="policy_api", keyword="{기준 지역} 예시 행사", needs_region=True,
                        brand_case=True, reason="브랜드 허용 사유 예시", monetization_tags=["pc_parts"], priority_keywords=["우선 하나", "우선 둘"], exclude_keywords=["제외 하나"],
                        season={"prepare_from": "12-05", "publish_from": "12-20", "publish_until": "01-20", "peak_from": "12-28", "peak_to": "01-10", "recurrence": "yearly"})
        read = self.read(full)
        self.assertEqual((read.total, read.rejected, read.notes), (1, (), ()))
        made = read.seeds[0]
        self.assertEqual((made.seed_id, made.major, made.minor, made.keyword, made.seed_type, made.scope), ("EX010", "예시 대분류", "예시 중분류", "{기준 지역} 예시 행사", "seasonal", "common"))
        self.assertEqual((made.allowed_channels, made.target_type, made.sponsor_tag, made.reason, made.needs_region, made.brand_case), (("github_pages", "naver_b"), "policy_api", "pc_parts", "브랜드 허용 사유 예시", True, True))
        self.assertEqual((made.priority_keywords, made.excluded_keywords), (("우선 하나", "우선 둘"), ("제외 하나",)))
        self.assertEqual((made.prepare_from, made.publish_from, made.publish_until, made.peak_period, made.recurrence), ("12-05", "12-20", "01-20", ("12-28", "01-10"), "yearly"))
        self.assertEqual((made.state, made.registered_on, made.last_selected_on, made.active_since), ("proposed", self.TODAY, None, None))

    def test_everything_is_registered_as_proposed_even_if_the_file_says_otherwise(self):
        read = self.read(proposal(), proposal(id="EX002", keyword="예시 청소기"), default_status="active")
        self.assertEqual([item.state for item in read.seeds], ["proposed", "proposed"])
        self.assertEqual(len(read.notes), 1)
        self.assertIn("승인 전", read.notes[0])
        self.assertEqual(self.read(proposal()).notes, (), "승인 전이라고 적었으면 안내가 없다")

    def test_the_priority_flag_follows_the_importance(self):
        read = self.read(proposal(importance="priority"), proposal(id="EX002", keyword="예시 둘"))
        self.assertEqual([item.priority for item in read.seeds], [True, False])

    def test_a_proposal_seed_is_not_usable_until_approved(self):
        read = self.read(proposal())
        self.assertEqual(sd.usable_seeds(read.seeds, "naver_a"), ())
        approved = sd.change_state(read.seeds[0], "active", self.TODAY)
        self.assertEqual(len(sd.usable_seeds((approved,), "naver_a")), 1)

    def test_a_bad_seed_is_rejected_by_name_and_the_rest_are_still_read(self):
        read = self.read(proposal(), proposal(id="EX002", keyword="예시 둘", target_type="gadget"), proposal(id="EX003", keyword="예시 셋", monetization_tags=["a_b", "c_d"]),
                         proposal(id="EX004", keyword="예시 넷", language="fr"), proposal(id="EX005", keyword="예시 다섯", generation="always"), "문자열",
                         dict(proposal(id="EX007", keyword="예시 일곱"), extra=1), {key: value for key, value in proposal(id="EX008", keyword="예시 여덟").items() if key != "reason"})
        self.assertEqual([item.seed_id for item in read.seeds], ["EX001"])
        self.assertEqual([name for name, _reason in read.rejected], ["EX002", "EX003", "EX004", "EX005", "6번째 씨앗", "EX007", "EX008"])
        self.assertTrue(all(reason and "‘" in reason or "씨앗" in reason for _name, reason in read.rejected))
        self.assertIn("‘제품’", read.rejected[0][1])
        self.assertNotIn("gadget", read.rejected[0][1], "틀린 값 이름이 아니라 고를 수 있는 한국어 이름을 보인다")

    def test_duplicates_inside_one_file_reject_the_later_one(self):
        read = self.read(proposal(), proposal(keyword="예시 다른 낱말"), proposal(id="EX002", keyword="예시 제습기"), proposal(id="EX003", keyword="예시 제습기", scope="naver_b", allowed_channels=["naver_b"]))
        self.assertEqual([item.seed_id for item in read.seeds], ["EX001", "EX003"], "같은 소속의 같은 낱말은 뒤의 것을 빼지만 다른 소속이면 둘 다 읽는다")
        self.assertEqual([name for name, _reason in read.rejected], ["EX001", "EX002"])
        self.assertIn("씨앗 번호", read.rejected[0][1])
        self.assertIn("씨앗 낱말", read.rejected[1][1])

    def test_a_file_with_the_wrong_overall_shape_is_refused_as_a_whole(self):
        for bad in (None, [], "x", 3, {}, {"seeds": "x"}, {"seeds": {}}, {"seeds": [], "surprise": 1}, {"proposal_version": "v9", "seeds": []}, {"proposal_version": 1, "seeds": []}):
            with self.subTest(bad=repr(bad)[:40]):
                with self.assertRaises(AppError) as caught:
                    sd.parse_proposals(bad, self.TODAY)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        with self.assertRaises(AppError):
            sd.parse_proposals({"seeds": [proposal()] * (sd.MAX_SEEDS + 1)}, self.TODAY)
        with self.assertRaises(AppError):
            sd.parse_proposals(proposal_file(), "어제")

    def test_a_peak_needs_both_ends_and_the_season_keys_are_exact(self):
        good = {"prepare_from": "12-05", "publish_from": "12-20", "publish_until": "01-20", "peak_from": None, "peak_to": None, "recurrence": "yearly"}
        read = self.read(proposal(importance="seasonal", season=good))
        self.assertEqual((read.rejected, read.seeds[0].peak_period), ((), None))
        for broken in (dict(good, peak_from="12-28"), {key: value for key, value in good.items() if key != "recurrence"}, dict(good, surprise=1), "문자열", dict(good, publish_until="07-15")):
            with self.subTest(broken=repr(broken)[:50]):
                self.assertEqual(len(self.read(proposal(importance="seasonal", season=broken)).rejected), 1)
        self.assertEqual(len(self.read(proposal(season=good)).rejected), 1, "계절이 아닌 씨앗에 계절 일정이 있으면 거절한다")

    def test_the_label_of_a_seed_without_a_clean_id_is_its_position(self):
        read = self.read(proposal(id="공백 있는 번호!", keyword="예시 하나"), proposal(id=7, keyword="예시 둘"))
        self.assertEqual([name for name, _reason in read.rejected], ["1번째 씨앗", "2번째 씨앗"])


if __name__ == "__main__":
    unittest.main()
