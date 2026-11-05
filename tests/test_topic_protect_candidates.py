"""특성 시험(P0) — 후보 모양·가져오기(CSV)·설정 파일의 엄격함과 '채널 열거' 를 **현재 모습 그대로** 못박는다(계획 문서 `docs/TOPIC_ENGINE_PLAN.md` 의 G3·G4 열거). 네트워크·시크릿·실제 시계·자식 프로세스 없음.

왜: 5채널 주제 선정 전략의 새 엔진은 기존 `Candidate`·보관함·설정을 바꾸지 않고 나란히 놓는다. 그러려면 지금 이 값들이 어떤 모양인지(어떤 칸이 있고 어떤 칸은 거절되는지, 숫자 하나가 횟수로 읽히는지)를 먼저 못박아야 뒤의 단계가 '의도한 변경' 으로만 보인다.
이 시험은 '옳다고 정한 것' 이 아니라 '지금 이렇다' 이다 — 바꾸려면 새 결정(D-nn)을 쓰고 해당 시험을 의식적으로 고친다. 알려진 결함은 이름에 `KNOWN_DEFECT` 를 달았다(상대지수와 실제 횟수를 구분하는 장치 없음).
이미 있는 시험과 겹치지 않게 더한다 — 이미 있는 것: 모르는 칸을 거절하는 일반 규칙(`test_content_candidates.test_unknown_or_malformed_stored_data_is_refused_not_repaired`)·깨진 후보 한 행이 목록을 멈추는 일(`test_content_candidates_store` 의 `CANDIDATE_CORRUPT`)·
CSV 의 모르는 열 무시와 알림(`test_candidate_csv.HeaderTest.test_unknown_columns_are_ignored_and_listed`)·열 이름 별칭 전수·`PLATFORMS` 순서(`test_content_candidates` 와 `test_content_candidates_store` 의 `PLATFORMS` 비교)·`SCHEMA_VERSION`·`MIGRATIONS`(`test_content_migration`).
"""
import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import service_support as support  # noqa: E402
from chanceblog_desktop.content import candidate_csv as csv_  # noqa: E402
from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import profiles  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content import suggest_score as sc  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import format as fmt  # noqa: E402
from chanceblog_desktop.service.format import PLATFORM_KO  # noqa: E402

NOW = "2026-11-03T00:00:00Z"
DAY = "2026-11-03"
# 새 엔진 후보·연결·출처 스냅샷이 쓸 이름들(운영자 확정 사항) — 지금 `Candidate` 에는 하나도 없다. 새 이름은 기존 칸과 겹치지 않는다.
NEW_ENGINE_NAMES = (
    "search_demand_count", "search_count_source", "trend_ratio", "trend_status", "trend_period", "trend_compared_group", "trend_queried_on", "data_status",
    "work_status", "recommendation_band", "engine_candidate_id", "legacy_candidate_id", "draft_plan_id", "source_topic_id", "seed_id", "channel",
    "topic_cluster", "topic_angle", "monetization_tags", "scores", "search_intent", "target_reader", "language", "provenance",
)
CANDIDATE_KEYS = ["blogs", "candidate_id", "created_at", "data_date", "duplicate", "keyword", "keyword_opportunity", "mobile_share", "post_type", "priority", "profile_fit", "project_id", "reason",
                  "related_blog_results", "revision", "schema", "search_demand", "seasonality", "selections", "status", "sub_keywords", "topic", "trend", "updated_at"]


def make(**fields):
    return cd.Candidate.new("주제 테스트 문장", "키워드", ("naver_b",), candidate_id="c0000001", now=NOW, **fields)


def code_of(callable_, *args, **kwargs):
    with unittest.TestCase().assertRaises(AppError) as caught:
        callable_(*args, **kwargs)
    return caught.exception.code


class RelativeIndexLooksLikeACountTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 상대지수 87 을 `search_demand=87` 로 넣으면 그대로 통과해 '월간 검색 수요 87' 로 저장된다 — 상대지수와 실제 횟수를 구분하는 장치(출처·기간·종류 칸)가 없다.
    # 뒤집는 단계가 계획에 없다 — Legacy 칸은 그대로 두고(D-37 ③) 새 Trend 칸이 대신한다. 이 시험은 '이 칸은 상대값과 횟수를 구분하지 못한다' 는 현재 모습을 계속 기록한다.
    def test_KNOWN_DEFECT_the_number_87_passes_as_a_monthly_search_demand_of_87_with_no_way_to_tell_an_index_from_a_count(self):
        found = make(search_demand=87, data_date=DAY)
        self.assertEqual((found.search_demand, found.data_date, found.has_data()), (87, DAY, True))
        self.assertEqual(cd.LABELS["search_demand"], "월간 검색 수요")
        self.assertEqual(found.to_dict()["search_demand"], 87)
        self.assertEqual(cd.Candidate.from_dict(found.to_dict()), found)                    # 저장했다 읽어도 똑같이 87
        self.assertEqual(sorted(found.to_dict()), CANDIDATE_KEYS)                           # 출처·기간·종류를 적는 칸이 없다(데이터 조회일 하나뿐)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_search_demand_accepts_only_whole_numbers_from_zero_to_a_billion(self):
        self.assertEqual(cd.MAX_SEARCH_DEMAND, 1_000_000_000)
        for good in (0, 1, 87, 1_000_000_000):
            with self.subTest(good=good):
                self.assertEqual(make(search_demand=good, data_date=DAY).search_demand, good)
        for bad in (87.5, "87", True, -1, 1_000_000_001):
            with self.subTest(bad=bad):
                self.assertEqual(code_of(make, search_demand=bad, data_date=DAY), "CANDIDATE_INVALID")
        self.assertEqual(code_of(make, search_demand=87), "CANDIDATE_INVALID", "지표가 있으면 조회일이 있어야 한다")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_opportunity_turns_the_demand_into_a_log_scale_where_a_hundred_thousand_searches_is_one_hundred(self):
        expected = {0: 0.0, 1: 6.02, 10: 20.83, 87: 38.89, 100: 40.09, 1000: 60.01, 10_000: 80.0, 100_000: 100.0, 1_000_000: 100.0}
        self.assertEqual({demand: round(sc.opportunity(search_demand=demand), 2) for demand in expected}, expected)
        self.assertEqual((sc.DEMAND_FULL, sc.RESULTS_FULL, sc.OPPORTUNITY_WEIGHTS), (100_000, 10_000_000, {"demand": 50, "competition": 30, "trend": 20}))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 점수는 87 을 '87회' 의 로그 눈금으로 보므로 87 점이 아니라 38.89 점이 된다 — 같은 87 을 상대지수(0~100)로 읽으면 매우 높은 값인데 반대로 낮게 매겨진다.
    # 뒤집는 단계가 계획에 없다 — Legacy 칸은 그대로 두고(D-37 ③) 새 Trend 칸이 대신한다. 이 시험은 '이 칸은 상대값과 횟수를 구분하지 못한다' 는 현재 모습을 계속 기록한다.
    def test_KNOWN_DEFECT_the_same_87_scores_far_below_87_because_it_is_read_as_a_count(self):
        self.assertLess(sc.opportunity(search_demand=87), 40)
        self.assertLess(sc.opportunity(search_demand=87), sc.opportunity(search_demand=100))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_candidate_has_none_of_the_new_engine_names_and_no_field_says_where_a_number_came_from(self):
        fields = {field.name for field in dataclasses.fields(cd.Candidate)}
        self.assertEqual(len(fields), 23)
        self.assertEqual(fields & set(NEW_ENGINE_NAMES), set(), "새 엔진 이름이 기존 후보의 칸이 됐다 — 새 엔진은 `Candidate` 와 나란히 두는 계획이다(D-36)")
        self.assertEqual(sorted(fields | {"schema"}), CANDIDATE_KEYS)
        self.assertEqual(set(cd.METRIC_FIELDS), {"search_demand", "related_blog_results", "trend", "mobile_share", "seasonality", "duplicate", "profile_fit", "priority", "keyword_opportunity"})
        self.assertEqual(cd.TRENDS, ("상승", "보합", "하락"))                                  # 관심도 변화는 세 낱말뿐 — '데이터 부족' 값이 없다(없으면 None)


class LegacyCountOnTheCommandLineTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_command_line_prints_the_legacy_count_as_monthly_search_demand_in_times_and_never_as_a_relative_value(self):
        # 화면 쪽 이름·단위는 `test_topic_protect_ui.LegacyDemandLabelTest` 가 못박는다. 여기는 명령줄 출력(`candidates show`·`suggest`)이 같은 칸을 부르는 이름과 단위다 — 운영자 조건 1: 재해석하지 않는다.
        self.assertEqual(cd.LABELS["search_demand"], "월간 검색 수요")
        self.assertEqual(fmt.METRIC_UNITS, {"search_demand": "{:,}회", "related_blog_results": "{:,}건", "mobile_share": "{}%"})
        self.assertEqual([fmt.metric_text("search_demand", value) for value in (None, 0, 87, 8600)], ["데이터 없음", "0회", "87회", "8,600회"])
        self.assertEqual((fmt.metric_text("related_blog_results", 4120), fmt.metric_text("mobile_share", 71)), ("4,120건", "71%"))
        for word in ("상대", "관심도", "지수"):
            self.assertNotIn(word, cd.LABELS["search_demand"])
            self.assertNotIn(word, fmt.METRIC_UNITS["search_demand"])


class StrictShapeTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_strategy_style_and_engine_names_are_refused_as_unknown_fields_when_read_and_when_edited(self):
        data = make().to_dict()
        for name in NEW_ENGINE_NAMES:
            with self.subTest(name=name):
                self.assertEqual(code_of(cd.Candidate.from_dict, {**data, name: "x"}), "CANDIDATE_INVALID")
                self.assertEqual(code_of(make().edited, **{name: "x"}), "CANDIDATE_INVALID")
        self.assertEqual(code_of(make().edited, status="REVIEW"), "CANDIDATE_INVALID", "상태는 edited 로 못 바꾼다(moved 로만)")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_new_with_an_unknown_field_name_is_a_plain_type_error_not_a_candidate_error(self):
        with self.assertRaises(TypeError):
            make(topic_cluster="x")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_candidate_carries_one_to_five_channels_so_one_candidate_can_name_every_channel(self):
        five = cd.Candidate.new("주제 테스트 문장", "키워드", st.PLATFORMS, candidate_id="c0000002", now=NOW)
        self.assertEqual(five.blogs, st.PLATFORMS)
        self.assertEqual(five.to_dict()["blogs"], list(st.PLATFORMS))
        for bad in ((), ("naver_c",), ("naver_a", "naver_a"), ("tistory",), "naver_a"):
            with self.subTest(blogs=bad):
                self.assertEqual(code_of(cd.Candidate.new, "주제 테스트 문장", "키워드", bad, candidate_id="c0000003", now=NOW), "CANDIDATE_INVALID")      # 시각·번호를 직접 줘서 실제 시계를 읽지 않는다


class CsvAndTrendColumnTest(unittest.TestCase):
    def one_row(self, head, row):
        table = csv_.parse_table(f"{head}\n{row}\n")
        return table, csv_.row_fields(table, table.records[0])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: '검색량' 이라는 이름의 열 값 87 은 그대로 월간 검색 수요 87 로 받는다 — 열에도 상대값인지 횟수인지 적는 곳이 없다.
    # 뒤집는 단계가 계획에 없다 — Legacy 칸은 그대로 두고(D-37 ③) 새 Trend 칸이 대신한다. 이 시험은 '이 칸은 상대값과 횟수를 구분하지 못한다' 는 현재 모습을 계속 기록한다.
    def test_KNOWN_DEFECT_a_column_named_search_volume_is_taken_as_the_monthly_search_demand(self):
        for head in ("검색량", "Search Volume", "월간 검색량", "monthly searches"):
            with self.subTest(head=head):
                table, fields = self.one_row(f"주제,핵심 키워드,대상 블로그,{head},조회일", f"가나다 주제,가나다,naver_b,87,{DAY}")
                self.assertEqual(table.columns["search_demand"], 3)
                self.assertEqual((fields["search_demand"], fields["data_date"], fields["blogs"], table.unknown), (87, DAY, ("naver_b",), ()))
        self.assertEqual(csv_.parse_count("1,234", "x", cd.MAX_SEARCH_DEMAND), 1234)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_trend_column_takes_only_the_three_words_so_a_number_in_it_is_refused_with_the_allowed_words(self):
        for value in ("87", "87%", "55.5", "100"):
            with self.subTest(value=value):
                with self.assertRaises(csv_.CsvCellError) as caught:
                    self.one_row("주제,핵심 키워드,대상 블로그,트렌드,조회일", f"가나다 주제,가나다,naver_b,{value},{DAY}")
                self.assertEqual((caught.exception.item, caught.exception.reason), (cd.LABELS["trend"], "다음 중 하나여야 합니다: 상승, 보합, 하락"))
        _table, fields = self.one_row("주제,핵심 키워드,대상 블로그,트렌드,조회일", f"가나다 주제,가나다,naver_b,상승,{DAY}")
        self.assertEqual(fields["trend"], "상승")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_columns_that_name_a_relative_index_are_not_known_so_they_are_listed_and_their_values_are_dropped(self):
        table, fields = self.one_row("주제,핵심 키워드,대상 블로그,트렌드 지수,Relative Index,Search Trend,조회일", f"가나다 주제,가나다,naver_b,87,55,60,{DAY}")
        self.assertEqual(table.unknown, ("트렌드 지수", "Relative Index", "Search Trend"))
        self.assertEqual(sorted(fields), ["blogs", "data_date", "keyword", "topic"])           # 지표 칸으로 새지 않는다 — 조용히 버려질 뿐(알림은 `unknown_columns`)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_csv_alias_table_has_exactly_the_sixteen_fields_and_no_engine_name(self):
        self.assertEqual(list(csv_.FIELD_ALIASES), ["topic", "keyword", "sub_keywords", "blogs", "post_type", "search_demand", "related_blog_results", "trend", "mobile_share", "seasonality",
                                                    "duplicate", "profile_fit", "priority", "keyword_opportunity", "reason", "data_date"])
        flat_names = {csv_.flat(name) for names in csv_.FIELD_ALIASES.values() for name in names}
        self.assertFalse(flat_names & {csv_.flat(name) for name in NEW_ENGINE_NAMES}, "새 엔진 이름이 CSV 열 이름이 됐다")


class SettingsStrictnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = support.make_ctx(self.tmp.name)
        self.path = self.ctx.settings.path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, body):
        self.path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return self.path.read_bytes()

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_an_unknown_top_level_field_makes_the_settings_unreadable_and_the_file_is_left_alone(self):
        for extra in ("channel_profiles", "seeds", "calendar", "topic_engine"):
            with self.subTest(extra=extra):
                before = self.write({"schema": 1, "repo_path": "", "naver_profiles": {}, extra: {}})
                self.assertEqual(code_of(self.ctx.settings.repo_path), "SETTINGS_INVALID")
                self.assertEqual(code_of(self.ctx.settings.naver_profile_dicts), "SETTINGS_INVALID")
                self.assertEqual(code_of(self.ctx.settings.save_repo_path, "x"), "SETTINGS_INVALID")
                self.assertEqual(self.path.read_bytes(), before)                            # 읽지 못해도 파일은 건드리지 않는다

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_settings_hold_only_naver_profiles_so_a_profile_for_another_channel_is_refused(self):
        for key in ("github_pages", "blogger_en", "blogger_ko"):
            with self.subTest(key=key):
                self.write({"schema": 1, "repo_path": "", "naver_profiles": {key: {}}})
                self.assertEqual(code_of(self.ctx.settings.naver_profile_dicts), "SETTINGS_INVALID")
        self.write({"schema": 2, "repo_path": "", "naver_profiles": {}})
        self.assertEqual(code_of(self.ctx.settings.repo_path), "SETTINGS_INVALID")
        self.write({"schema": 1, "repo_path": "", "naver_profiles": {}})
        self.assertEqual((self.ctx.settings.repo_path(), self.ctx.settings.naver_profile_dicts()), ("", {}))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_saving_a_naver_profile_adds_no_new_top_level_field(self):
        support.naver_profiles(self.ctx)
        self.assertEqual(sorted(json.loads(self.path.read_text(encoding="utf-8"))), ["naver_profiles", "repo_path", "schema"])
        self.assertEqual(sorted(json.loads(self.path.read_text(encoding="utf-8"))["naver_profiles"]), ["naver_a", "naver_b"])


class ChannelEnumerationTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_platforms_run_pages_then_blogger_english_then_blogger_korean_then_naver_a_and_b(self):
        self.assertEqual(st.PLATFORMS, ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"))
        self.assertEqual(list(st.PLATFORM_FAMILY.items()), [("github_pages", "pages"), ("blogger_en", "blogger"), ("blogger_ko", "blogger"), ("naver_a", "naver"), ("naver_b", "naver")])
        self.assertLess(st.PLATFORMS.index("blogger_en"), st.PLATFORMS.index("blogger_ko"), "코드에서는 영문이 한글보다 앞이다 — 전략 문서의 Blogger A(한글)·B(영문) 순서와 반대")
        self.assertEqual((st.PAGES, st.BLOGGER, st.NAVER), ("pages", "blogger", "naver"))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_strategys_blogger_a_korean_and_b_english_are_blogger_ko_and_blogger_en_in_every_name_table(self):
        self.assertEqual(csv_.parse_blogs("Blogger 한글"), ("blogger_ko",))
        self.assertEqual(csv_.parse_blogs("Blogger 영문"), ("blogger_en",))
        self.assertEqual(csv_.parse_blogs("블로거 한글;Blogger English"), ("blogger_ko", "blogger_en"))
        self.assertEqual((PLATFORM_KO["blogger_ko"], PLATFORM_KO["blogger_en"]), ("Blogger 한글", "Blogger 영문"))
        self.assertEqual(set(csv_.BLOG_NAMES), set(st.PLATFORMS))
        self.assertEqual(set(PLATFORM_KO), set(st.PLATFORMS))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_naver_profile_accepts_only_naver_a_or_b_and_a_naver_blog_address(self):
        self.assertEqual(profiles.KEYS, ("naver_a", "naver_b"))
        for key in ("github_pages", "blogger_en", "blogger_ko"):
            with self.subTest(key=key):
                self.assertEqual(code_of(profiles.NaverProfile, key, "표시 이름", "https://blog.naver.com/exampleaaa"), "CONTENT_INVALID")
        for url in ("https://example.blogspot.com/abc", "https://abc.tistory.com/x", "https://example.github.io/abc", "https://example.com/abc"):
            with self.subTest(url=url):
                self.assertEqual(code_of(profiles.NaverProfile, "naver_a", "표시 이름", url), "CONTENT_INVALID")
        self.assertEqual(profiles.NaverProfile("naver_b", "표시 이름", "https://blog.naver.com/examplebbb").key, "naver_b")


if __name__ == "__main__":
    unittest.main()
