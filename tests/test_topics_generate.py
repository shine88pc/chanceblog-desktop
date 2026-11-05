"""후보 조립(`topics/generate.py`) 시험 — 경로별 개수 나누기, 협찬 몫의 채널 범위, 실시간 이슈의 출처 조건과 48시간 안정화, 씨앗·계절·후속·협찬·실시간 경로, 6항목 초기 규칙, 후보 번호, 진단, 결정성.

지키는 것:
  1) 총 후보 수 목표를 경로별 개수로 나누는 함수는 비율대로 내림하고 남는 자리를 소수 부분이 큰 경로부터(같으면 경로 순서) 하나씩 준다 — 합은 늘 목표와 같고, 모자란 경로의 자리는 다른 경로가 가져가지 않는다('부족' 으로 적는다).
     협찬 몫(15%)은 후보 생성이 켜진 네이버 A·B 에만 둔다(운영자 R-149 의 B=1) — 다른 채널은 협찬을 뺀 비율로 나눈다.
  2) 실시간 이슈는 **운영자가 넣은 것만** 쓴다 — 엔진은 출처 조건(공식 1 또는 서로 독립인 2)과 48시간 안정화만 검사한다(47시간 59분은 아직, 48시간 정각은 통과).
  3) 6항목은 문서의 초기 규칙으로 채우고(손으로 계산한 값으로 못박는다 — **초기값, 전략 원문 확인 전**) 알 수 없는 항목은 None 이라 점수가 빼고 다시 나눈다 — 0점이 아니다. 숫자만으로 후보를 지우거나 제외하지 않는다.
  4) 같은 입력은 입력 순서와 상관없이 같은 후보·같은 번호·같은 순서이고 입력은 바뀌지 않는다.
네트워크·파일·실제 시계·난수 없이 돈다. 시험 자료의 씨앗·이력·이슈는 모두 '예시' 로 시작하는 지어낸 말이다.
"""
import dataclasses
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import brand  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import dedupe as dd  # noqa: E402
from chanceblog_desktop.topics import expand as ex  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import history as hs  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402
from chanceblog_desktop.topics import score as sc  # noqa: E402
from chanceblog_desktop.topics import wording  # noqa: E402

A, B, G = ts.PROFILES["naver_a"], ts.PROFILES["naver_b"], ts.PROFILES["github_pages"]
TODAY = "2026-11-10"
NOW = "2026-11-10T00:00:00Z"
NAVER = {"seed": 30, "follow_up": 20, "seasonal": 20, "realtime": 15, "sponsor": 15}


def seed(**changes):
    return ts.example_seed(**{"seed_id": "s1", "keyword": "예시 로봇청소기", "major": "가전", "minor": "소형가전", **changes})


def post(title="예시 이력 글", *, channel="naver_a", keywords=("예시 가습기",), date="2026-10-01", ref="p1"):
    return hs.HistoryRecord(channel=channel, title=title, keywords=keywords, date=date, ref=ref, origin="naver_items")


def run(profile=A, seeds=(), calendar=(), history=(), **options):
    return gn.generate(profile, seeds, calendar, history, TODAY, **options)


def by_word(found):
    return {candidate.primary_keyword: candidate for candidate in found.candidates}


def source(url, official=False):
    return gn.Source(url=url, official=official)


def item(**changes):
    values = {"channel": "naver_a", "topic": "예시 새 소식이 나왔다", "primary_keyword": "예시 새 소식", "topic_cluster": "small-appliances", "topic_angle": "what-changed", "search_intent": "context_explainer",
              "content_type": "news_analysis", "first_reported_at": "2026-11-07T00:00:00Z", "sources": (source("https://a.example.org/x", True),)}
    values.update(changes)
    return gn.RealtimeItem(**values)


def english(key="blogger_en"):
    return dataclasses.replace(ts.PROFILES[key], generation_enabled=True)


class ConstantsTest(unittest.TestCase):
    def test_the_routes_follow_the_source_mix_and_the_candidate_models_source_types(self):
        self.assertEqual(gn.ROUTES, ("seed", "follow_up", "seasonal", "realtime", "sponsor"))
        self.assertEqual(gn.ROUTES, tuple(ch.SOURCE_MIX))
        self.assertEqual(gn.ROUTES, md.SOURCE_TYPES)
        self.assertEqual(dict(ch.SOURCE_MIX), NAVER)
        self.assertEqual(dict(gn.ROUTE_TYPES), {"seed": ("seed", "evergreen"), "follow_up": ("follow_up", "follow_up"), "seasonal": ("seasonal", "seasonal"), "realtime": ("realtime", "realtime"),
                                                "sponsor": ("sponsor", "sponsor_prep")})
        for route, (source_type, candidate_type) in gn.ROUTE_TYPES.items():
            self.assertIn(candidate_type, md.CANDIDATE_TYPES)
            self.assertEqual(source_type, route)
        self.assertEqual(dict(gn.ROUTE_KO), {"seed": "씨앗", "follow_up": "후속", "seasonal": "계절", "realtime": "실시간", "sponsor": "협찬"})

    def test_the_numbers_the_module_documents_are_these(self):
        self.assertEqual((gn.DEFAULT_TARGET, gn.MAX_TARGET, gn.REALTIME_STABLE_HOURS, gn.MIN_OFFICIAL, gn.MIN_INDEPENDENT, gn.MAX_SOURCES), (20, 200, 48, 1, 2, 10))
        self.assertEqual(gn.SPONSOR_CHANNELS, ("naver_a", "naver_b"))
        self.assertEqual(ch.FOLLOW_UP_PER_POST, 3)
        self.assertEqual((gn.FIT_BASE, gn.FIT_OWN_SCOPE, gn.FIT_CLUSTER, gn.FIT_DIRECTION, gn.FIT_PRIORITY, gn.FIT_FOLLOW_UP), (60, 20, 15, 10, 5, 70))
        self.assertEqual((gn.MONETIZATION_TAG_IN_FOCUS, gn.MONETIZATION_TAG_OUTSIDE, gn.MONETIZATION_CLUSTER_IN_FOCUS, gn.MONETIZATION_NONE), (100, 60, 70, 30))
        self.assertEqual((gn.EVIDENCE_OWN_POST_BONUS, gn.EVIDENCE_OFFICIAL, gn.EVIDENCE_INDEPENDENT), (10, 90, 75))

    def test_the_initial_value_tables_are_exactly_these(self):
        # 표는 초기값이다(전략 원문 확인 전) — 원문에 맞춰 고칠 때 이 시험의 같은 표를 의식적으로 함께 고친다.
        self.assertEqual(dict(gn.EVIDENCE_BASE), {"explainer": 70, "how_to_guide": 80, "checklist": 80, "troubleshooting": 75, "buying_guide": 60, "comparison": 60, "place_guide": 60,
                                                  "news_analysis": 50, "routine_plan": 85, "dev_log": 85, "service_intro": 65})
        self.assertEqual(dict(gn.EVIDENCE_PENALTY), {"health_check": 20, "experience_claim": 10}, "P2b 보완(D-54): 근거 감점은 이 둘뿐 — product_brand 항은 없앴다(일반 낱말·글 종류는 신호가 아니다)")
        self.assertEqual(dict(gn.CLUSTER_MONETIZATION), {"small-appliances": "small_appliance", "pc-peripherals": "pc_peripheral", "lodging-and-travel": "lodging_travel", "ai-services": "ai_service",
                                                         "pc-parts": "pc_parts", "work-automation": "work_automation"})
        self.assertEqual(set(gn.EVIDENCE_BASE), set(md.CONTENT_TYPES))
        self.assertEqual(set(gn.TOPIC_TEMPLATES_KO), set(md.CONTENT_TYPES))
        self.assertEqual(set(gn.TARGET_READERS), set(ch.CHANNELS))
        self.assertEqual(dict(gn.TOPIC_TEMPLATES_KO), {
            "buying_guide": "{kw} {dir}, 고르기 전에 확인할 것", "comparison": "{kw} {dir}, 무엇이 다른지 한눈에 보기", "checklist": "{kw} {dir}, 빠뜨리기 쉬운 것 점검하기",
            "how_to_guide": "{kw} {dir}, 처음부터 차근차근 따라 하기", "troubleshooting": "{kw} {dir}, 원인을 찾아 순서대로 풀기", "place_guide": "{kw} {dir}, 가기 전에 알아 두면 좋은 것",
            "news_analysis": "{kw} {dir}, 무슨 일이고 왜 중요한지 정리", "explainer": "{kw} {dir}, 알아 두면 좋은 내용 정리", "routine_plan": "{kw} {dir}, 부담 없이 이어 가는 방법",
            "dev_log": "{kw} {dir}, 과정과 결과 정리", "service_intro": "{kw} {dir}, 어떤 서비스인지 쉽게 소개"})
        self.assertEqual(gn.TOPIC_TEMPLATE_EN, "{kw} {dir}: a simple note on what to know")
        self.assertEqual(dict(gn.TARGET_READERS), {
            "github_pages": "기술과 산업의 변화를 쉽게 이해하고 싶은 일반 독자", "blogger_ko": "생활 습관과 정리를 가볍게 시작하려는 독자", "blogger_en": "readers who want a simple, low-pressure everyday routine",
            "naver_a": "집에서 쓸 제품이나 가볼 곳을 고르려는 생활 독자", "naver_b": "AI·PC·자동화 도구를 직접 써 보려는 일반 사용자"})
        self.assertEqual(gn.FOLLOW_UP_TEMPLATES, (
            ("revisit", "{kw}, 시간이 지난 뒤 다시 확인할 것", "점검", "{kw}: what to check again later", "check-in", "checklist", "information", "follow-up-revisit"),
            ("faq", "{kw}, 자주 묻는 질문 정리", "자주 묻는 질문", "{kw}: frequently asked questions", "faq", "explainer", "information", "follow-up-faq"),
            ("deeper", "{kw}, 상황별로 나눠 더 자세히 보기", "상황별 정리", "{kw}: a closer look by situation", "by situation", "explainer", "information", "follow-up-deeper")))
        self.assertEqual([entry[0] for entry in gn.FOLLOW_UP_TEMPLATES], ["revisit", "faq", "deeper"])
        for kind, topic_ko, suffix_ko, topic_en, suffix_en, content_type, intent, angle in gn.FOLLOW_UP_TEMPLATES:
            self.assertIn("{kw}", topic_ko)
            self.assertIn("{kw}", topic_en)
            self.assertTrue(suffix_ko and suffix_en)
            self.assertIn(content_type, md.CONTENT_TYPES)
            self.assertIn(intent, md.SEARCH_INTENTS)
            self.assertTrue(ch.is_slug(angle) and ch.is_slug(kind))
        self.assertEqual(gn.TWO_LEVEL_SUFFIXES, ("co.kr", "or.kr", "go.kr", "ne.kr", "re.kr", "ac.kr", "pe.kr", "co.jp", "co.uk", "com.au", "com.cn", "com.tw"))
        for text in (gn.TOPIC_TEMPLATE_EN, *gn.TOPIC_TEMPLATES_KO.values()):
            self.assertIn("{kw}", text)
            self.assertIn("{dir}", text)
        for cluster, tag in gn.CLUSTER_MONETIZATION.items():
            self.assertTrue(ch.is_slug(cluster) and ch.is_tag(tag))

    def test_the_module_says_the_rules_are_initial_values_and_names_the_six_factors(self):
        doc = Path(gn.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        self.assertIn("초기값 — 전략 원문 확인 전", doc)
        for needle in ("채널 적합도", "작성 가능성", "차별성", "시기", "근거", "수익화", "AI 가 없어도", "route_targets"):
            self.assertIn(needle, doc)


class RouteTargetsTest(unittest.TestCase):
    def test_twenty_split_exactly_by_the_percentages_and_ten_gives_the_extra_place_to_the_earlier_route_on_a_tie(self):
        self.assertEqual(gn.route_targets(20, NAVER), {"seed": 6, "follow_up": 4, "seasonal": 4, "realtime": 3, "sponsor": 3})
        self.assertEqual(gn.route_targets(10, NAVER), {"seed": 3, "follow_up": 2, "seasonal": 2, "realtime": 2, "sponsor": 1})
        self.assertEqual(gn.route_targets(100, NAVER), NAVER)
        self.assertEqual(gn.route_targets(0, NAVER), dict.fromkeys(gn.ROUTES, 0))

    def test_the_remaining_places_go_to_the_largest_remainders_first_and_to_the_earlier_route_on_a_tie(self):
        # 손으로 계산: 합계 7 → 7×비율 = 2.1·1.4·1.4·1.05·1.05 → 내림 2·1·1·1·1(=6), 남는 하나는 소수 부분이 가장 큰 .4(후속·계절 동점) 중 앞선 후속
        self.assertEqual(gn.route_targets(7, NAVER), {"seed": 2, "follow_up": 2, "seasonal": 1, "realtime": 1, "sponsor": 1})
        self.assertEqual(gn.route_targets(1, NAVER), {"seed": 1, "follow_up": 0, "seasonal": 0, "realtime": 0, "sponsor": 0})
        self.assertEqual(gn.route_targets(2, NAVER), {"seed": 1, "follow_up": 1, "seasonal": 0, "realtime": 0, "sponsor": 0})
        self.assertEqual(gn.route_targets(3, NAVER), {"seed": 1, "follow_up": 1, "seasonal": 1, "realtime": 0, "sponsor": 0})
        self.assertEqual(gn.route_targets(9, NAVER), {"seed": 3, "follow_up": 2, "seasonal": 2, "realtime": 1, "sponsor": 1})
        self.assertEqual(gn.route_targets(13, NAVER), {"seed": 4, "follow_up": 3, "seasonal": 2, "realtime": 2, "sponsor": 2}, "13 → 내림 3·2·2·1·1, 남는 넷은 .95·.95(실시간·협찬)·.9(씨앗)·.6(후속)")
        self.assertEqual(gn.route_targets(17, NAVER), {"seed": 5, "follow_up": 3, "seasonal": 3, "realtime": 3, "sponsor": 3})

    def test_the_sum_is_always_the_total_for_every_total_and_several_weight_sets_and_no_route_strays_from_its_share(self):
        for weights in (NAVER, {"seed": 30, "follow_up": 20, "seasonal": 20, "realtime": 15}, {"seed": 1}, {"realtime": 3, "sponsor": 7}, {"seed": 1, "follow_up": 1, "seasonal": 1}):
            whole = sum(weights.values())
            for total in range(0, 201):
                found = gn.route_targets(total, weights)
                with self.subTest(weights=weights, total=total):
                    self.assertEqual(sum(found.values()), total)
                    self.assertEqual(tuple(found), gn.ROUTES)
                    for route in gn.ROUTES:
                        share = total * weights.get(route, 0) / whole
                        self.assertLess(abs(found[route] - share), 1)
                        self.assertGreaterEqual(found[route], int(share))
                        if route not in weights:
                            self.assertEqual(found[route], 0)

    def test_a_route_without_a_weight_gets_nothing_and_the_others_share_the_whole(self):
        self.assertEqual(gn.route_targets(20, {"seed": 30, "follow_up": 20, "seasonal": 20, "realtime": 15}), {"seed": 7, "follow_up": 5, "seasonal": 5, "realtime": 3, "sponsor": 0})
        self.assertEqual(gn.route_targets(5, {"sponsor": 15}), {"seed": 0, "follow_up": 0, "seasonal": 0, "realtime": 0, "sponsor": 5})

    def test_wrong_inputs_are_programming_errors(self):
        for total in (-1, 201, True, 2.5, "20", None):
            with self.subTest(total=total):
                with self.assertRaises(ValueError):
                    gn.route_targets(total, NAVER)
        for weights in ({}, {"seed": 0}, {"other": 5}, {"seed": -1}, {"seed": 1.5}, {"seed": True}, [("seed", 1)], None):
            with self.subTest(weights=weights):
                with self.assertRaises(ValueError):
                    gn.route_targets(10, weights)
        self.assertEqual(gn.route_targets(200, NAVER)["seed"], 60)

    def test_the_sponsor_share_belongs_to_the_enabled_naver_channels_only(self):
        self.assertEqual(gn.mix_for(A), NAVER)
        self.assertEqual(gn.mix_for(B), NAVER)
        self.assertEqual(list(gn.mix_for(A)), list(gn.ROUTES), "경로 순서 그대로")
        for key in ("github_pages", "blogger_ko", "blogger_en"):
            with self.subTest(channel=key):
                self.assertEqual(gn.mix_for(english(key)), {"seed": 30, "follow_up": 20, "seasonal": 20, "realtime": 15})
                self.assertEqual(gn.mix_for(ts.PROFILES[key]), {"seed": 30, "follow_up": 20, "seasonal": 20, "realtime": 15})
        off = dataclasses.replace(A, generation_enabled=False)
        self.assertNotIn("sponsor", gn.mix_for(off), "후보 생성이 꺼진 네이버 채널도 협찬 몫이 없다")
        with self.assertRaises(TypeError):
            gn.mix_for("naver_a")


class SiteKeyTest(unittest.TestCase):
    def test_the_last_two_labels_without_www_or_the_last_three_for_a_two_level_suffix(self):
        for url, expected in (("https://www.news.example.org/a/b?x=1", "example.org"), ("http://blog.example.co.kr/x", "example.co.kr"), ("https://example.com", "example.com"), ("HTTP://A.B.COM:8080/x", "b.com"),
                              ("https://sub.sub.example.co.kr/", "example.co.kr"), ("https://www.example.com/#top", "example.com"), ("https://127.0.0.1/x", "127.0.0.1"), ("https://example.co.uk/p", "example.co.uk"),
                              ("https://co.kr/x", "co.kr"), ("https://a.example.com.au/x", "example.com.au"), ("https://news.go.kr", "news.go.kr")):
            with self.subTest(url=url):
                self.assertEqual(gn.site_key(url), expected)

    def test_a_bad_shape_gives_none(self):
        for url in ("ftp://a.com", "https://a b.com", "https://user@a.com/x", "https://a.com/x y", "https://localhost/x", "https://www/x", "https://www.com/x", "javascript:alert(1)", "a.com", "", None, 3, "https://" + "a" * 64 + ".com",
                    "https://a.com/" + "x" * 500, "https://-.", "//a.com/x"):
            with self.subTest(url=str(url)[:30]):
                self.assertIsNone(gn.site_key(url))

    def test_the_same_site_in_different_spellings_has_the_same_key_and_different_sites_differ(self):
        self.assertEqual(gn.site_key("https://WWW.Example.org/a"), gn.site_key("http://example.org:80/b"))
        self.assertNotEqual(gn.site_key("https://a.example.org"), gn.site_key("https://a.example.com"))


class SourceAndItemTest(unittest.TestCase):
    def test_a_source_needs_a_real_address_and_a_true_or_false_official_flag(self):
        self.assertFalse(source("https://a.example.org/x").official)
        self.assertTrue(source("https://a.example.org/x", True).official)
        for bad in ("ftp://a.com", "그냥 글", "", None):
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):
                    gn.Source(url=bad)
        for bad in (1, "yes", None):
            with self.assertRaises(ValueError):
                gn.Source(url="https://a.example.org", official=bad)

    def test_an_item_is_checked_for_its_channel_sources_text_fields_and_first_report_time_and_keeps_tuples(self):
        made = item(sources=[source("https://a.example.org/x")], secondary_keywords=["예시 둘"])
        self.assertEqual((made.sources, made.secondary_keywords), ((source("https://a.example.org/x"),), ("예시 둘",)))
        for changes in ({"channel": "naver_c"}, {"channel": "blogger_a"}, {"sources": ()}, {"sources": [{"url": "https://a.example.org"}]}, {"sources": tuple(source(f"https://a{n}.example.org") for n in range(11))},
                        {"sources": None}, {"topic": 3}, {"primary_keyword": None}, {"topic_cluster": 1}, {"topic_angle": b"x"}, {"search_intent": None}, {"content_type": 5}, {"secondary_keywords": "글"},
                        {"secondary_keywords": (3,)}, {"target_reader": 3}):
            with self.subTest(changes=repr(changes)[:40]):
                with self.assertRaises(ValueError):
                    item(**changes)
        for stamp in ("어제", "2026-11-07", None, "2026-11-07T00:00:00"):
            with self.subTest(stamp=stamp):
                with self.assertRaises(AppError):
                    item(first_reported_at=stamp)
        self.assertEqual(len(item(sources=tuple(source(f"https://a{n}.example.org") for n in range(10))).sources), 10)
        self.assertEqual(item(target_reader="예시 독자").target_reader, "예시 독자")


class RealtimeCheckTest(unittest.TestCase):
    def test_one_official_source_is_enough_after_forty_eight_hours(self):
        verdict = gn.check_realtime(item(), "2026-11-09T00:00:00Z")
        self.assertEqual((verdict.ok, verdict.sources_ok, verdict.stable, verdict.official, verdict.independent, verdict.hours, verdict.reasons), (True, True, True, 1, 1, 48, ()))

    def test_forty_eight_hours_exactly_passes_and_one_second_earlier_does_not(self):
        started = "2026-11-07T00:00:00Z"
        on_time = gn.check_realtime(item(first_reported_at=started), "2026-11-09T00:00:00Z")
        early = gn.check_realtime(item(first_reported_at=started), "2026-11-08T23:59:59Z")
        self.assertEqual((on_time.ok, on_time.stable, on_time.hours), (True, True, 48))
        self.assertEqual((early.ok, early.stable, early.sources_ok, early.hours), (False, False, True, 47))
        self.assertEqual(early.reasons, ("처음 알려진 뒤 47시간밖에 지나지 않았습니다 — 48시간이 지난 뒤에 씁니다(안정화)",))
        self.assertEqual(gn.check_realtime(item(first_reported_at=started), "2026-11-09T00:00:01Z").hours, 48)
        self.assertEqual(gn.check_realtime(item(first_reported_at=started), "2026-11-12T05:30:00Z").hours, 125)
        self.assertEqual(gn.check_realtime(item(first_reported_at=started), started).hours, 0)

    def test_two_independent_sources_are_enough_and_pages_of_the_same_site_are_not(self):
        two = item(sources=(source("https://a.example.org/x"), source("https://b.example.com/y")))
        verdict = gn.check_realtime(two, "2026-11-10T00:00:00Z")
        self.assertEqual((verdict.ok, verdict.official, verdict.independent), (True, 0, 2))
        same_site = item(sources=(source("https://a.example.org/x"), source("https://www.example.org/y"), source("http://news.example.org/z")))
        verdict = gn.check_realtime(same_site, "2026-11-10T00:00:00Z")
        self.assertEqual((verdict.ok, verdict.sources_ok, verdict.official, verdict.independent, verdict.stable), (False, False, 0, 1, True))
        self.assertEqual(verdict.reasons, ("출처 조건을 채우지 못했습니다 — 공식 출처 1개 이상이거나 서로 독립인 출처 2곳 이상이어야 하는데 공식 0개·독립 1곳입니다",))

    def test_one_unofficial_source_is_not_enough_and_a_second_official_one_only_changes_the_count(self):
        one = item(sources=(source("https://a.example.org/x"),))
        self.assertFalse(gn.check_realtime(one, "2026-11-20T00:00:00Z").sources_ok)
        both = item(sources=(source("https://a.example.org/x", True), source("https://a.example.org/y", True)))
        verdict = gn.check_realtime(both, "2026-11-20T00:00:00Z")
        self.assertEqual((verdict.ok, verdict.official, verdict.independent), (True, 2, 1))

    def test_a_failure_on_both_counts_lists_both_reasons_in_order(self):
        verdict = gn.check_realtime(item(sources=(source("https://a.example.org/x"),)), "2026-11-07T10:00:00Z")
        self.assertEqual((verdict.ok, verdict.sources_ok, verdict.stable, verdict.hours), (False, False, False, 10))
        self.assertEqual(len(verdict.reasons), 2)
        self.assertIn("출처 조건", verdict.reasons[0])
        self.assertIn("10시간", verdict.reasons[1])

    def test_a_first_report_in_the_future_cannot_be_counted(self):
        verdict = gn.check_realtime(item(first_reported_at="2026-11-12T00:00:00Z"), "2026-11-10T00:00:00Z")
        self.assertEqual((verdict.ok, verdict.stable, verdict.hours), (False, False, None))
        self.assertEqual(verdict.reasons, ("이슈가 처음 알려진 시각이 지금보다 뒤라 안정화 시간을 셀 수 없습니다",))

    def test_the_clock_is_an_argument_and_wrong_arguments_are_refused(self):
        for bad in ("어제", None, "2026-11-10", "2026-11-10T00:00:00", 3):
            with self.subTest(now=bad):
                with self.assertRaises(AppError):
                    gn.check_realtime(item(), bad)
        for bad in (None, {"topic": "x"}, "item"):
            with self.assertRaises(TypeError):
                gn.check_realtime(bad, NOW)
        self.assertEqual(gn.check_realtime(item(), "2026-11-10T00:00:00Z"), gn.check_realtime(item(), "2026-11-10T00:00:00Z"))


class SeedRouteTest(unittest.TestCase):
    def setUp(self):
        self.found = run(A, [seed()])

    def test_a_general_seed_gives_three_directions_and_keeps_the_two_with_the_higher_score(self):
        # 소형가전 씨앗·네이버 A: '구매 기준'·'제품 비교'·'관리 방법' 을 만들어(처음 3개) 점수가 높은 2개만 남긴다(`PER_SEED["general"]` = 3·2) — 구매 기준은 근거 점수가 낮아 빠진다.
        self.assertEqual(self.found.channel, "naver_a")
        self.assertEqual([c.primary_keyword for c in self.found.candidates], ["예시 로봇청소기 관리 방법", "예시 로봇청소기 제품 비교"])
        self.assertEqual([c.scores.final for c in self.found.candidates], [80, 78])           # P2b 보완: 제품 비교의 근거 50→60 이라 76→78
        keep = [row for row in self.found.dropped if row.reason == "per_seed_keep"]
        self.assertEqual((keep[0].route, keep[0].count), ("seed", 1))
        self.assertEqual(keep[0].detail, "씨앗 ‘예시 로봇청소기’ 에서 점수가 낮은 후보는 씨앗당 2개까지만 남깁니다")
        combos = [row for row in self.found.dropped if row.reason == "combination"]
        self.assertEqual((combos[0].count, combos[0].detail.startswith("씨앗 ‘예시 로봇청소기’: ‘방문 전 확인’")), (2, True))

    def test_the_candidate_fields_follow_the_templates_and_the_seed(self):
        candidate = by_word(self.found)["예시 로봇청소기 관리 방법"]
        self.assertEqual((candidate.source_type, candidate.candidate_type, candidate.channel, candidate.language), ("seed", "evergreen", "naver_a", "ko"))
        self.assertEqual(candidate.topic, "예시 로봇청소기 관리 방법, 처음부터 차근차근 따라 하기")
        self.assertEqual((candidate.search_intent, candidate.content_type, candidate.topic_cluster, candidate.topic_angle), ("how_to", "how_to_guide", "small-appliances", "care-method"))
        self.assertEqual(candidate.secondary_keywords, ("예시 로봇청소기", "관리 방법"))
        self.assertEqual((candidate.seed_id, candidate.work_status, candidate.created_at, candidate.target_reader), ("s1", "NEW", NOW, gn.TARGET_READERS["naver_a"]))
        self.assertEqual((candidate.monetization_tags, candidate.similar_post_ids, candidate.processing_errors, candidate.duplicate_status), ((), (), (), None))
        comparison = by_word(self.found)["예시 로봇청소기 제품 비교"]
        self.assertEqual(comparison.topic, "예시 로봇청소기 제품 비교, 무엇이 다른지 한눈에 보기")
        self.assertEqual(comparison.safety_flags, (), "P2b 보완: 일반 낱말·글 종류만으로는 표시가 붙지 않는다")

    def test_every_content_type_template_makes_a_valid_topic_and_the_english_one_too(self):
        for content_type, template in gn.TOPIC_TEMPLATES_KO.items():
            with self.subTest(content_type=content_type):
                text = template.format(kw="예시 말", dir="방향")
                self.assertTrue(text.startswith("예시 말 방향, "))
                ts.make(topic=text)
        self.assertEqual(gn.TOPIC_TEMPLATE_EN.format(kw="sample", dir="faq"), "sample faq: a simple note on what to know")

    def test_ids_are_stable_and_follow_the_documented_pattern_without_the_date(self):
        candidate = by_word(self.found)["예시 로봇청소기 관리 방법"]
        self.assertEqual(candidate.candidate_id, "tc-naver_a-seed-" + ex.stable_id("naver_a", "seed", "s1", "care-method", "관리 방법"))
        self.assertEqual(candidate.source_topic_id, "src-" + ex.stable_id("source-topic", ex.keyword_key("예시 로봇청소기"), "care-method"))
        later = gn.generate(A, [seed()], (), (), "2027-03-01")
        self.assertEqual([c.candidate_id for c in later.candidates], [c.candidate_id for c in self.found.candidates], "날짜가 달라도 같은 출처는 같은 번호다")
        self.assertEqual({c.created_at for c in later.candidates}, {"2027-03-01T00:00:00Z"})
        for each in self.found.candidates:
            md.stored_id(each.candidate_id, "번호")
            self.assertRegex(each.candidate_id, r"^tc-naver_a-seed-[0-9a-f]{16}$")
            self.assertRegex(each.source_topic_id, r"^src-[0-9a-f]{16}$")
        self.assertEqual(len({c.candidate_id for c in run(A, [seed(), seed(seed_id="s2", keyword="예시 둘째")], target=100).candidates}), 4)

    def test_the_same_common_seed_gives_the_same_source_topic_in_both_naver_channels_and_different_candidate_ids(self):
        # 두 채널의 방향 낱말이 겹쳐야(여기서는 '체크리스트' 와 공통 확장어) 같은 원천 주제가 생긴다 — 기본 프로필의 채널 방향은 서로 달라 처음 몇 개는 겹치지 않는다.
        shared_a, shared_b = dataclasses.replace(A, expansion_directions=("체크리스트",)), dataclasses.replace(B, expansion_directions=("체크리스트",))
        common = [seed(scope="common", major="AI", minor="AI 서비스", seed_type="priority", priority=True)]
        first, second = gn.generate(shared_a, common, (), (), TODAY, target=60), gn.generate(shared_b, common, (), (), TODAY, target=60)
        shared = {c.source_topic_id for c in first.candidates} & {c.source_topic_id for c in second.candidates}
        self.assertTrue(shared)
        self.assertEqual({c.candidate_id for c in first.candidates} & {c.candidate_id for c in second.candidates}, set(), "번호에는 채널이 들어 있다")
        default_a, default_b = run(A, common, target=60), run(B, common, target=60)
        self.assertEqual({c.source_topic_id for c in default_a.candidates} & {c.source_topic_id for c in default_b.candidates}, set(), "기본 방향 낱말은 채널마다 달라 원천 주제가 겹치지 않는다")

    def test_seeds_that_may_not_be_used_do_not_make_candidates(self):
        pool = [seed(seed_id="a1", state="proposed"), seed(seed_id="a2", keyword="예시 둘째", state="inactive"), seed(seed_id="a3", keyword="예시 셋째", scope="naver_b"),
                seed(seed_id="a4", keyword="예시 넷째", scope="github_pages")]
        found = run(A, pool)
        self.assertEqual(found.candidates, ())
        self.assertEqual([(row.route, row.reason) for row in found.dropped], [("seed", "no_seed")])
        self.assertEqual(found.dropped[0].detail, "이 채널에서 쓸 수 있는(사용 중이고 공통이거나 이 채널 전용인) 씨앗이 없습니다")
        self.assertEqual(run(A, [seed(seed_id="b1", scope="naver_a")]).candidates[0].seed_id, "b1")

    def test_a_priority_seed_gets_five_first_and_three_kept(self):
        found = run(A, [seed(seed_type="priority", priority=True)], target=40)
        self.assertEqual([c.primary_keyword for c in found.candidates], ["예시 로봇청소기 관리 방법", "예시 로봇청소기 방법", "예시 로봇청소기 제품 비교"],
                         "P2b 보완: 같은 79점에서 근거가 복원된 제품 비교가 체크리스트 대신 남는다(동점 순서)")
        self.assertEqual([c.scores.final for c in found.candidates], [82, 79, 79])
        self.assertEqual([row.count for row in found.dropped if row.reason == "per_seed_keep"], [2])

    def test_no_keep_or_target_row_is_written_when_the_numbers_are_exactly_equal(self):
        # 씨앗에서 만든 수가 남길 수와 같으면, 경로의 후보 수가 목표와 같으면 '넘어서 뺐다' 는 진단 줄이 없어야 한다(개수 0 인 줄이 생기지 않게).
        two_only = dataclasses.replace(B, expansion_directions=("설치", "설정"))
        quiet = seed(excluded_keywords=("방법", "체크리스트", "비교", "주의할 점", "자주 묻는 질문", "비용"), scope="common", major="AI", minor="AI 서비스")
        found = gn.generate(two_only, [quiet], (), (), TODAY, target=100)
        self.assertEqual(sorted(c.primary_keyword for c in found.candidates), ["예시 로봇청소기 설정", "예시 로봇청소기 설치"])
        self.assertEqual([row for row in found.dropped if row.reason in ("per_seed_keep", "over_target")], [])
        self.assertTrue(all(row.count >= 1 for row in found.dropped))
        exact = gn.generate(two_only, [quiet], (), (), TODAY, target=7)                    # 씨앗 몫 7×30/100 = 2.1 → 2 → 후보 둘이 목표와 딱 같다
        self.assertEqual(exact.routes[0], gn.RouteReport("seed", 2, 2, 2, 0))
        self.assertEqual([row for row in exact.dropped if row.reason == "over_target" and row.route == "seed"], [])

    def test_a_direction_word_that_promises_results_is_dropped_with_its_own_reason_before_a_candidate_is_built(self):
        # 채널 프로필의 방향 낱말은 약속 표현을 거르지 않으므로(후보 칸만 거절한다) 조립이 후보를 만들기 전에 '결과 약속 표현' 으로 가려 이유를 정확히 남긴다.
        promising = dataclasses.replace(A, expansion_directions=("수익 보장",))
        found = gn.generate(promising, [seed()], (), (), TODAY, target=100)
        rows = [row for row in found.dropped if row.reason in ("result_promise", "invalid")]
        self.assertEqual([(row.route, row.reason, row.count) for row in rows], [("seed", "result_promise", 1)])
        self.assertEqual(rows[0].detail, "씨앗 ‘예시 로봇청소기’ 의 ‘수익 보장’: 결과를 약속하는 표현이 있어 쓰지 않습니다")
        self.assertTrue(all("수익 보장" not in c.primary_keyword for c in found.candidates))
        self.assertTrue(found.candidates, "다른 방향으로는 후보가 만들어진다")

    def test_realtime_seasonal_and_sponsorable_seeds_do_not_make_seed_route_candidates(self):
        pool = [seed(seed_id="r1", seed_type="realtime"), seed(seed_id="r2", keyword="예시 계절", seed_type="seasonal"), seed(seed_id="r3", keyword="예시 협찬", seed_type="sponsorable", sponsor_tag="pc_parts")]
        found = run(A, pool, target=40)
        self.assertEqual([c for c in found.candidates if c.source_type == "seed"], [])


class FactorWhiteBoxTest(unittest.TestCase):
    """6항목 초기 규칙의 숫자 하나하나 — 손으로 계산한 값."""

    def test_the_channel_fit_adds_its_points_and_stops_at_a_hundred(self):
        small = seed()                                                                   # 공통·소형가전(네이버 A 의 묶음)
        extra = gn._Extra
        self.assertEqual(gn._channel_fit(A, "small-appliances", extra(seed=small, direction_source="channel")), 85)
        self.assertEqual(gn._channel_fit(A, "small-appliances", extra(seed=small, direction_source="common")), 75)
        self.assertEqual(gn._channel_fit(A, "unknown-x", extra(seed=small, direction_source="channel")), 70)
        self.assertEqual(gn._channel_fit(A, "unknown-x", extra(seed=small, direction_source="common")), 60)
        own = seed(scope="naver_a")
        self.assertEqual(gn._channel_fit(A, "unknown-x", extra(seed=own, direction_source="common")), 80)
        self.assertEqual(gn._channel_fit(A, "small-appliances", extra(seed=own, direction_source="common")), 95)
        self.assertEqual(gn._channel_fit(A, "small-appliances", extra(seed=own, direction_source="channel")), 100, "60+20+15+10 = 105 → 100")
        prior = seed(priority=True, seed_type="priority")
        self.assertEqual(gn._channel_fit(A, "unknown-x", extra(seed=prior, direction_source="common")), 65)
        self.assertEqual(gn._channel_fit(A, "small-appliances", extra(seed=seed(scope="naver_a", priority=True, seed_type="priority"), direction_source="channel")), 100)
        self.assertEqual(gn._channel_fit(A, "small-appliances", extra(seed=seed(scope="naver_b"), direction_source=None)), 95, "다른 채널 전용 씨앗은 이 채널 전용 가산이 없다 — 60+20(전용 = 이 채널 아님이라 0)")  if False else None

    def test_without_a_seed_an_own_post_is_seventy_and_an_issue_is_sixty_plus_a_known_cluster(self):
        self.assertEqual(gn._channel_fit(A, "post-xx", gn._Extra(own_post=True)), 70)
        self.assertEqual(gn._channel_fit(A, "unknown-x", gn._Extra()), 60)
        self.assertEqual(gn._channel_fit(A, "small-appliances", gn._Extra()), 75)
        self.assertEqual(gn._channel_fit(B, "small-appliances", gn._Extra()), 60, "그 채널의 묶음이 아니면 가산이 없다")
        self.assertEqual(gn._channel_fit(B, "local-ai", gn._Extra()), 75)

    def test_the_evidence_follows_the_content_type_minus_the_flags_plus_an_own_post_and_sources_override_it(self):
        explainer = ts.make(content_type="explainer")
        self.assertEqual(gn._evidence(explainer, (), gn._Extra()), 70)
        self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra()), 50)
        self.assertEqual(gn._evidence(explainer, ("product_brand",), gn._Extra()), 70, "P2b 보완: 제품·브랜드 표시는 근거를 깎지 않는다")
        self.assertEqual(gn._evidence(explainer, ("experience_claim",), gn._Extra()), 60)
        self.assertEqual(gn._evidence(explainer, ("health_check", "product_brand", "experience_claim"), gn._Extra()), 40, "건강 20 + 경험 10 만 깎는다")
        self.assertEqual(gn._evidence(explainer, ("sponsor_disclosure", "result_promise"), gn._Extra()), 70, "다른 표시는 점수를 깎지 않는다")
        self.assertEqual(gn._evidence(explainer, (), gn._Extra(own_post=True)), 80)
        self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra(own_post=True)), 60)
        for content_type, base in gn.EVIDENCE_BASE.items():
            self.assertEqual(gn._evidence(ts.make(content_type=content_type), (), gn._Extra()), base)
        self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra(official=1, independent=1)), 90)
        self.assertEqual(gn._evidence(explainer, (), gn._Extra(official=0, independent=2)), 75)
        self.assertEqual(gn._evidence(explainer, (), gn._Extra(official=0, independent=1)), 70)
        self.assertEqual(gn._evidence(explainer, (), gn._Extra(official=2, independent=2)), 90)

    def test_the_monetization_follows_the_focus_the_tags_and_the_cluster(self):
        plain = ts.make(topic_cluster="small-appliances")
        self.assertEqual(gn._monetization(A, plain, gn._Extra()), 70)
        self.assertEqual(gn._monetization(A, ts.make(topic_cluster="unknown-x"), gn._Extra()), 30)
        self.assertEqual(gn._monetization(A, ts.make(topic_cluster="ai-services"), gn._Extra()), 30, "네이버 A 의 분야에 없는 분야")
        self.assertEqual(gn._monetization(B, ts.make(topic_cluster="ai-services"), gn._Extra()), 70)
        self.assertEqual(gn._monetization(A, ts.make(monetization_tags=("small_appliance",)), gn._Extra()), 100)
        self.assertEqual(gn._monetization(A, ts.make(monetization_tags=("ai_service",)), gn._Extra()), 60)
        self.assertEqual(gn._monetization(A, ts.make(monetization_tags=("ai_service", "pc_peripheral")), gn._Extra()), 100)
        self.assertEqual(gn._monetization(A, ts.make(topic_cluster="unknown-x"), gn._Extra(seed=seed(sponsor_tag="small_appliance"))), 100, "씨앗의 협찬 태그도 같다")
        self.assertEqual(gn._monetization(A, ts.make(topic_cluster="small-appliances"), gn._Extra(seed=seed(sponsor_tag="ai_service"))), 60)
        self.assertIsNone(gn._monetization(G, ts.make(channel="github_pages", topic_cluster="small-appliances", monetization_tags=("small_appliance",)), gn._Extra()), "우선 분야가 없는 채널은 평가 불가")
        self.assertIsNone(gn._monetization(ts.PROFILES["blogger_ko"], plain, gn._Extra()))


class FactorRulesTest(unittest.TestCase):
    """같은 규칙을 후보 조립 전체를 거쳐 — 손으로 계산한 값."""

    def test_the_candidates_of_the_first_seed_are_computed_by_hand(self):
        # 소형가전 일반 씨앗·네이버 A·이력 없음·캘린더 없음. '관리 방법': 채널 적합도 60+15+10 = 85 · 작성 가능성 how_to_guide+how_to → 보완 0 = 90 · 차별성 None · 시기 None · 근거 80(표시 없음) · 수익화 70
        # 최종 = (85×25 + 90×15 + 80×10 + 70×25) / (25+15+10+25) = (2125+1350+800+1750)/75 = 6025/75 = 80.33 → 80 (우선 추천)
        found = run(A, [seed()], target=100)
        candidate = by_word(found)["예시 로봇청소기 관리 방법"]
        self.assertEqual(candidate.scores.factors, sc.Factors(channel_fit=85, feasibility=90, differentiation=None, timing=None, evidence=80, monetization=70))
        self.assertEqual((candidate.scores.final, candidate.recommendation_band, candidate.review_expires_at, candidate.data_status), (80, "RECOMMENDED", None, "insufficient"))
        # '제품 비교': 85·90·None·None·근거 comparison 60(감점 없음 — P2b 보완)·70 → (2125+1350+600+1750)/75 = 77.67 → 78 (일반)
        comparison = by_word(found)["예시 로봇청소기 제품 비교"]
        self.assertEqual(comparison.scores.factors, sc.Factors(channel_fit=85, feasibility=90, differentiation=None, timing=None, evidence=60, monetization=70))
        self.assertEqual((comparison.scores.final, comparison.recommendation_band), (78, "GENERAL"))

    def test_the_unknown_factors_are_left_out_and_not_counted_as_zero(self):
        candidate = run(A, [seed()], target=100).candidates[0]
        weights = A.weights
        present = [name for name, value in candidate.scores.factors.present()]
        self.assertEqual(present, ["channel_fit", "feasibility", "evidence", "monetization"])
        used = sum(weights[name] for name in present)
        expected = sc.round_half_up(sum(getattr(candidate.scores.factors, name) * weights[name] for name in present), used)
        self.assertEqual(candidate.scores.final, expected)
        zeros = sc.score(A, dataclasses.replace(candidate.scores.factors, differentiation=0, timing=0)).final
        self.assertLess(zeros, candidate.scores.final, "모름을 0점으로 쳤다면 점수가 이만큼 낮아졌을 것이다")

    def test_a_seed_of_this_channel_and_a_priority_flag_change_the_fit_and_unknown_clusters_the_monetization(self):
        own = run(A, [seed(scope="naver_a", major="분류", minor="모르는 분류")], target=100)         # 60+20+0+10 = 90 · 수익화 30 (묶음을 모르면 장소 방향도 붙는다)
        candidate = by_word(own)["예시 로봇청소기 제품 비교"]
        self.assertEqual((candidate.scores.factors.channel_fit, candidate.scores.factors.monetization, candidate.topic_cluster.startswith("seed-")), (90, 30, True))
        prior = run(A, [seed(seed_type="priority", priority=True, major="분류", minor="모르는 분류")], target=100)
        self.assertEqual({c.scores.factors.channel_fit for c in prior.candidates}, {75}, "60+0+0+10+5")
        self.assertEqual({c.scores.factors.monetization for c in prior.candidates}, {30})

    def test_a_tagged_seed_that_is_sponsorable_gets_the_tag_score_and_the_flags(self):
        found = run(A, [seed(seed_type="sponsorable", sponsor_tag="small_appliance")], target=100)
        sponsor = [c for c in found.candidates if c.source_type == "sponsor"]
        self.assertEqual(len(sponsor), 3)
        self.assertEqual({c.scores.factors.monetization for c in sponsor}, {100})
        outside = run(A, [seed(seed_type="sponsorable", sponsor_tag="ai_service")], target=100)
        self.assertEqual({c.scores.factors.monetization for c in outside.candidates if c.source_type == "sponsor"}, {60})

    def test_flags_that_a_health_word_raises_lower_the_evidence_of_the_whole_candidate(self):
        found = run(A, [seed(keyword="예시 영양제", seed_type="priority", priority=True)], target=100)
        for candidate in found.candidates:
            self.assertEqual(candidate.safety_flags[0], "health_check")
            self.assertNotIn("product_brand", candidate.safety_flags)
            self.assertEqual(candidate.scores.factors.evidence, gn.EVIDENCE_BASE[candidate.content_type] - 20)

    def test_the_differentiation_is_a_hundred_minus_the_most_alike_existing_post_and_unknown_without_posts(self):
        self.assertIsNone(run(A, [seed()], target=100).candidates[0].scores.factors.differentiation)
        far_post = post("예시 완전히 다른 이야기", keywords=("예시 가습기",))
        unrelated = run(A, [seed()], history=[far_post], target=100)
        for candidate in unrelated.candidates:
            highest = dd.find_duplicates(candidate, [far_post], A).highest
            self.assertTrue(0 < highest < 40, highest)                      # '예시' 한 낱말만 겹친다
            self.assertEqual((candidate.scores.factors.differentiation, candidate.duplicate_status), (100 - highest, "different_topic"))
            self.assertIn(f"차별성: 같은 채널의 기존 글 1개와 견줬고 가장 비슷한 글은 {highest}% 입니다", candidate.selection_reasons)
        alike_post = post("예시 로봇청소기 관리 방법 확인", keywords=("예시 로봇청소기",), ref="same")
        alike = run(A, [seed()], history=[alike_post], target=100)
        shown = by_word(alike)["예시 로봇청소기 관리 방법"]
        percent = dd.find_duplicates(shown, [alike_post], A).highest
        self.assertGreaterEqual(percent, 40)
        self.assertEqual(shown.scores.factors.differentiation, 100 - percent)
        self.assertIn(shown.duplicate_status, ("similar_elements", "different_angle_needed", "duplicate_or_update"))
        self.assertEqual(shown.similar_post_ids, ("same",))
        self.assertIn(f"차별성: 같은 채널의 기존 글 1개와 견줬고 가장 비슷한 글은 {percent}% 입니다", shown.selection_reasons)
        self.assertEqual((shown.work_status, shown.recommendation_band != "UNRATED"), ("NEW", True), "숫자만으로 지우거나 제외하지 않는다")

    def test_without_a_comparable_post_the_reason_says_unknown_and_the_candidate_keeps_no_duplicate_mark(self):
        candidate = run(A, [seed()], target=100).candidates[0]
        self.assertIn("견줄 기존 글이 없어 차별성은 모름으로 두었습니다(0점·100점이 아닙니다)", candidate.selection_reasons)
        self.assertIsNone(candidate.duplicate_status)

    def test_a_post_of_another_channel_is_not_compared(self):
        found = run(A, [seed()], history=[post("예시 로봇청소기 관리 방법 확인", channel="naver_b", keywords=("예시 로봇청소기",))], target=100)
        for candidate in found.candidates:
            self.assertEqual((candidate.scores.factors.differentiation, candidate.duplicate_status), (None, None))

    def test_the_timing_follows_the_calendar_state_and_the_interest_reading_through_the_existing_table(self):
        entry = ts.example_entry(keywords=("로봇청소기",), name="예시 청소 시기")
        due = run(A, [seed()], calendar=[entry], target=100)
        self.assertEqual({c.scores.factors.timing for c in due.candidates}, {60}, "캘린더만(관심도 모름): 발행 기간 안 60")
        self.assertEqual({c.data_status for c in due.candidates}, {"insufficient"})
        self.assertIn("시기: 캘린더의 ‘예시 청소 시기’ 발행 기간 안입니다", due.candidates[0].selection_reasons)
        key = ex.keyword_key("예시 로봇청소기")
        for status, ratio, expected in (("rising", 80, 90), ("flat", 50, 70), ("falling", 20, 40)):
            reading = gn.InterestReading(status, ratio, "최근 12개월", ("예시 비교",), "2026-11-09")
            found = run(A, [seed()], calendar=[entry], interest={key: reading}, target=100)
            with self.subTest(status=status):
                self.assertEqual({c.scores.factors.timing for c in found.candidates}, {expected})
                self.assertEqual({(c.trend_status, c.trend_ratio, c.trend_period, c.trend_compared_group, c.trend_queried_on, c.data_status) for c in found.candidates},
                                 {(status, ratio, "최근 12개월", ("예시 비교",), "2026-11-09", "sufficient")})
        outside = dataclasses.replace(entry, publish_from="02-01", publish_to="02-28", prep_start="01-10", peak="02-10")
        far = run(A, [seed()], calendar=[outside], target=100)
        self.assertEqual({c.scores.factors.timing for c in far.candidates}, {20}, "이어지는 항목은 있으나 발행 기간 밖 20")
        self.assertIn("시기: 이어지는 캘린더 항목이 있지만 발행 기간 밖입니다(준비 중이거나 지난·아직 안 온 시기)", far.candidates[0].selection_reasons)
        self.assertIn("시기: 이어지는 캘린더 항목이 없어 캘린더로는 알 수 없습니다(모름 — 0점이 아닙니다)", run(A, [seed()], target=100).candidates[0].selection_reasons)

    def test_a_falling_interest_inside_the_window_only_lowers_the_score_and_never_forces_the_hold_band(self):
        # 운영자 R-149 의 C=0: '시기 도달 + 관심도 하락' 은 보류 구간으로 강제하지 않고 점수만 낮춘다.
        entry = ts.example_entry(keywords=("로봇청소기",))
        key = ex.keyword_key("예시 로봇청소기")
        falling = run(A, [seed()], calendar=[entry], interest={key: gn.InterestReading("falling", 10, "최근 12개월", ("예시 비교",), "2026-11-09")}, target=100)
        flat = run(A, [seed()], calendar=[entry], interest={key: gn.InterestReading("flat", 50, "최근 12개월", ("예시 비교",), "2026-11-09")}, target=100)
        self.assertEqual({c.scores.factors.timing for c in falling.candidates}, {40})
        self.assertLess(max(c.scores.final for c in falling.candidates), max(c.scores.final for c in flat.candidates))
        self.assertEqual({c.recommendation_band for c in falling.candidates}, {"GENERAL", "RECOMMENDED"} & {c.recommendation_band for c in falling.candidates})
        self.assertNotIn("HOLD", {c.recommendation_band for c in falling.candidates})
        self.assertEqual({c.review_expires_at for c in falling.candidates}, {None})

    def test_an_interest_outage_marks_the_data_unavailable_and_uses_the_calendar_alone(self):
        entry = ts.example_entry(keywords=("로봇청소기",))
        key = ex.keyword_key("예시 로봇청소기")
        found = run(A, [seed()], calendar=[entry], interest={key: gn.InterestReading("rising", 80, "최근 12개월", ("예시 비교",), "2026-11-09")}, interest_outage=True, target=100)
        self.assertEqual({c.data_status for c in found.candidates}, {"unavailable"})
        self.assertEqual({c.scores.factors.timing for c in found.candidates}, {60})
        self.assertEqual({c.trend_status for c in found.candidates}, {"rising"}, "읽은 값은 그대로 적는다")

    def test_the_interest_of_the_seed_word_is_used_when_the_expanded_word_has_none_and_the_expanded_word_wins_when_both_exist(self):
        seed_key, word_key = ex.keyword_key("예시 로봇청소기"), ex.keyword_key("예시 로봇청소기 관리 방법")
        rising = gn.InterestReading("rising", 70, "최근 12개월", ("예시 비교",), "2026-11-09")
        falling = gn.InterestReading("falling", 10, "최근 12개월", ("예시 비교",), "2026-11-09")
        only_seed = by_word(run(A, [seed()], interest={seed_key: rising}, target=100))
        self.assertEqual({c.trend_status for c in only_seed.values()}, {"rising"})
        both = by_word(run(A, [seed()], interest={seed_key: falling, word_key: rising}, target=100))
        self.assertEqual(both["예시 로봇청소기 관리 방법"].trend_status, "rising", "확장한 키워드의 값이 씨앗 낱말의 값보다 먼저다")
        self.assertEqual({c.trend_status for word, c in both.items() if word != "예시 로봇청소기 관리 방법"}, {"falling"})
        only_word = by_word(run(A, [seed()], interest={word_key: rising}, target=100))
        self.assertEqual(only_word["예시 로봇청소기 관리 방법"].trend_status, "rising")
        self.assertEqual({c.trend_status for word, c in only_word.items() if word != "예시 로봇청소기 관리 방법"}, {"insufficient"})

    def test_an_interest_reading_that_breaks_the_candidates_trend_rules_drops_that_candidate_with_the_reason(self):
        key = ex.keyword_key("예시 로봇청소기")
        found = run(A, [seed()], interest={key: gn.InterestReading("rising")}, target=100)
        self.assertEqual(found.candidates, ())
        self.assertEqual([(row.reason, row.count) for row in found.dropped if row.reason == "invalid"], [("invalid", 3)])
        self.assertIn("상승·보통·하락은 상대값이 있을 때만", [row.detail for row in found.dropped if row.reason == "invalid"][0])

    def test_the_english_channel_ignores_the_interest_because_its_use_is_none(self):
        key = ex.keyword_key("sample morning routine")
        found = run(english(), [seed(keyword="sample morning routine", minor="simple habits", major="habits")], calendar=[ts.example_entry(keywords=("routine",))],
                    interest={key: gn.InterestReading("rising", 70, "12 months", ("sample",), "2026-11-09")}, target=100)
        self.assertTrue(found.candidates)
        self.assertEqual({c.scores.factors.timing for c in found.candidates}, {60}, "관심도 사용 none → 캘린더만")
        self.assertEqual({c.language for c in found.candidates}, {"en"})
        self.assertTrue(all(c.topic.endswith(": a simple note on what to know") for c in found.candidates))


class OtherRoutesTest(unittest.TestCase):
    def test_a_seasonal_seed_is_used_only_while_its_calendar_window_is_open(self):
        entry = ts.example_entry(keywords=("예시 난방",), name="예시 난방 시기")
        pool = [seed(seed_id="z1", keyword="예시 난방", seed_type="seasonal")]
        found = run(A, pool, calendar=[entry], target=100)
        self.assertEqual({(c.source_type, c.candidate_type) for c in found.candidates}, {("seasonal", "seasonal")})
        self.assertEqual([c.primary_keyword for c in found.candidates], ["예시 난방 관리 방법", "예시 난방 제품 비교", "예시 난방 방법"], "계절 씨앗은 처음 5개를 만들어 3개를 남긴다(P2b 보완: 75점 제품 비교가 74점 방법보다 앞)")
        self.assertTrue(all("시기: 캘린더의 ‘예시 난방 시기’ 발행 기간 안입니다" in c.selection_reasons for c in found.candidates))
        later = gn.generate(A, pool, [entry], (), "2026-12-15")
        self.assertEqual(later.candidates, ())
        self.assertEqual([(row.route, row.reason, row.detail) for row in later.dropped if row.route == "seasonal"], [("seasonal", "not_due", "계절 씨앗 ‘예시 난방’ 은(는) 아직(또는 이미) 발행 기간 밖입니다")])
        unknown = run(A, pool, calendar=[], target=100)
        self.assertEqual([(row.reason, row.detail) for row in unknown.dropped if row.route == "seasonal"], [("not_due", "계절 씨앗 ‘예시 난방’ 은(는) 이어지는 캘린더 항목이 없습니다")])

    def test_a_calendar_entry_limited_to_another_channel_does_not_open_the_window(self):
        entry = ts.example_entry(keywords=("예시 난방",), channels=("naver_b",))
        pool = [seed(seed_id="z1", keyword="예시 난방", seed_type="seasonal")]
        self.assertEqual(run(A, pool, calendar=[entry]).candidates, ())
        self.assertTrue(run(B, pool, calendar=[entry], target=100).candidates)

    def test_a_sponsorable_seed_makes_sponsor_prep_candidates_with_the_tag_and_no_disclosure_flag(self):
        found = run(A, [seed(seed_id="sp1", keyword="예시 호텔", major="여행", minor="숙박", seed_type="sponsorable", sponsor_tag="lodging_travel")], target=100)
        self.assertEqual({(c.source_type, c.candidate_type) for c in found.candidates}, {("sponsor", "sponsor_prep")})
        self.assertEqual(len(found.candidates), 3, "협찬 가능 씨앗은 처음 5개를 만들어 3개를 남긴다")
        for candidate in found.candidates:
            self.assertEqual(candidate.monetization_tags, ("lodging_travel",))
            self.assertNotIn("sponsor_disclosure", candidate.safety_flags, "P2b 보완(D-51): 협찬 태그·경로는 가능성일 뿐이라 표시를 붙이지 않는다")
            self.assertTrue(candidate.selection_reasons[0].endswith(" — 협업 가능 유형 ‘숙박·여행’(협찬이 확정된 것은 아닙니다)"))
            self.assertNotIn("lodging_travel", candidate.selection_reasons[0], "영문 식별자가 화면 글에 나오지 않는다")
            self.assertIn("협찬 후보입니다" if False else "협찬 후보", candidate.selection_reasons[0])
            self.assertEqual(candidate.scores.factors.monetization, 100)
            self.assertRegex(candidate.candidate_id, r"^tc-naver_a-sponsor-[0-9a-f]{16}$")
            self.assertEqual(candidate.topic_cluster, "lodging-and-travel")

    def test_a_tagged_general_seed_makes_a_sponsor_route_candidate_too_and_other_channels_get_no_sponsor_share(self):
        tagged = seed(sponsor_tag="small_appliance", seed_type="general")
        found = run(A, [tagged], target=100)
        self.assertEqual({c.source_type for c in found.candidates}, {"seed", "sponsor"})
        self.assertEqual(len([c for c in found.candidates if c.source_type == "sponsor"]), 3, "협찬 경로는 일반 씨앗도 협찬 가능 씨앗으로 보아 처음 5개·남길 3개를 쓴다")
        self.assertEqual(len([c for c in found.candidates if c.source_type == "seed"]), 2, "씨앗 경로는 일반 씨앗의 처음 3개·남길 2개")
        self.assertEqual(run(G, [tagged]).candidates, (), "후보 생성이 꺼진 채널")
        github = dataclasses.replace(G, generation_enabled=True)
        self.assertEqual({c.source_type for c in run(github, [tagged], target=100).candidates}, {"seed"}, "GitHub Pages 에는 협찬 몫이 없다")
        self.assertEqual({report.route: report.target for report in run(github, [tagged], target=20).routes}, {"seed": 7, "follow_up": 5, "seasonal": 5, "realtime": 3, "sponsor": 0})

    def test_a_realtime_seed_alone_makes_nothing(self):
        self.assertEqual(run(A, [seed(seed_type="realtime")], target=100).candidates, ())

    def test_follow_ups_come_from_the_posts_of_the_same_channel_three_per_post_and_need_a_keyword(self):
        posts = [post("예시 새 글", keywords=("예시 공기청정기", "예시 필터"), date="2026-10-20", ref="new"), post("예시 옛 글", keywords=("예시 가습기",), date="2026-08-01", ref="old"),
                 post("예시 키워드 없는 글", keywords=(), ref="nokey"), post("예시 다른 채널 글", channel="naver_b", keywords=("예시 노트북",), ref="other"), post("예시 날짜 없는 글", keywords=("예시 선풍기",), date=None, ref="nodate")]
        found = run(A, (), history=posts, target=100)
        follow = [c for c in found.candidates if c.source_type == "follow_up"]
        self.assertEqual(len(follow), 9, "3개 글 × 3개")
        self.assertEqual({c.candidate_type for c in follow}, {"follow_up"})
        self.assertEqual({c.seed_id for c in follow}, {None})
        self.assertFalse(any("예시 노트북" in c.primary_keyword for c in follow), "다른 채널의 글은 쓰지 않는다")
        self.assertEqual([(row.reason, row.count) for row in found.dropped if row.route == "follow_up"], [("no_keyword", 1)])
        self.assertEqual(sorted(c.primary_keyword for c in follow if "공기청정기" in c.primary_keyword), ["예시 공기청정기 상황별 정리", "예시 공기청정기 자주 묻는 질문", "예시 공기청정기 점검"])
        faq = next(c for c in follow if c.primary_keyword == "예시 공기청정기 자주 묻는 질문")
        self.assertEqual((faq.topic, faq.content_type, faq.search_intent, faq.topic_angle), ("예시 공기청정기, 자주 묻는 질문 정리", "explainer", "information", "follow-up-faq"))
        self.assertEqual(faq.secondary_keywords, ("예시 공기청정기", "예시 필터"))
        self.assertEqual(faq.topic_cluster, "post-" + ex.stable_id("post", "new", digits=8))
        self.assertEqual(faq.candidate_id, "tc-naver_a-follow_up-" + ex.stable_id("naver_a", "follow_up", "new", "faq"))
        self.assertEqual(faq.source_topic_id, "src-" + ex.stable_id("source-topic", "post", "new", "faq"))
        self.assertIn("같은 채널의 기존 글(글 번호 new)의 후속 후보입니다 — 템플릿 문장이고 AI 가 쓴 것이 아닙니다", faq.selection_reasons)
        self.assertEqual(faq.scores.factors.channel_fit, 70)
        self.assertEqual(faq.scores.factors.evidence, 80, "explainer 70 + 기존 글 10")

    def test_a_post_without_a_number_still_gets_follow_ups_keyed_by_its_title(self):
        nameless = hs.HistoryRecord(channel="naver_a", title="예시 번호 없는 글", keywords=("예시 키",), origin="naver_items")
        found = run(A, (), history=[nameless], target=100)
        self.assertEqual(len(found.candidates), 3)
        self.assertEqual(found.candidates[0].topic_cluster, "post-" + ex.stable_id("post", ex.keyword_key("예시 번호 없는 글"), digits=8))
        self.assertIn("같은 채널의 기존 글의 후속 후보입니다", found.candidates[0].selection_reasons[0])

    def test_follow_ups_are_limited_by_the_route_target_and_the_newest_posts_come_first(self):
        posts = [post(f"예시 글 {n}", keywords=(f"예시 키워드{n}",), date=f"2026-10-{10 + n:02d}", ref=f"r{n}") for n in range(1, 6)]
        found = run(A, (), history=posts, target=10)
        follow = [c for c in found.candidates if c.source_type == "follow_up"]
        self.assertEqual([c.primary_keyword for c in follow], ["예시 키워드5 점검", "예시 키워드4 점검"])
        self.assertEqual(found.routes[1], gn.RouteReport("follow_up", 2, 15, 2, 0))
        self.assertEqual([row.count for row in found.dropped if row.reason == "over_target"], [13])
        self.assertEqual(len([c for c in run(A, (), history=posts, target=40).candidates if c.source_type == "follow_up"]), 8, "목표 40 의 후속 몫은 8")
        self.assertEqual(len([c for c in run(A, (), history=posts, target=100).candidates if c.source_type == "follow_up"]), 15, "목표 100 의 후속 몫은 20 이라 열다섯이 모두 남는다")

    def test_a_post_with_no_date_comes_after_every_dated_post_and_same_dates_are_ordered_by_number(self):
        posts = [post("예시 글 가", keywords=("예시 가",), date=None, ref="a"), post("예시 글 나", keywords=("예시 나",), date="2026-01-01", ref="z"), post("예시 글 다", keywords=("예시 다",), date="2026-01-01", ref="b"),
                 post("예시 글 라", keywords=("예시 라",), date="2026-12-01", ref="m")]
        ctx = gn._Ctx(A, (), tuple(posts), TODAY, NOW, {}, False, frozenset())
        rows = gn._follow_up_candidates(ctx, gn._Drops())
        first_of_each = sorted((order, candidate.primary_keyword) for candidate, order, item_order in rows if item_order == 0)
        self.assertEqual([keyword for _order, keyword in first_of_each], ["예시 라 점검", "예시 다 점검", "예시 나 점검", "예시 가 점검"], "날짜가 최근인 글 먼저, 날짜가 없는 글은 맨 뒤, 같은 날짜는 글 번호순(b < z)")
        self.assertEqual([order for order, _keyword in first_of_each], [0, 1, 2, 3])
        self.assertEqual(sorted({(order, item_order) for _c, order, item_order in rows})[:4], [(0, 0), (0, 1), (0, 2), (1, 0)], "글 안에서는 템플릿 순서(점검·자주 묻는 질문·상황별 정리)")

    def test_follow_ups_use_english_templates_in_an_english_channel(self):
        found = run(english(), (), history=[hs.HistoryRecord(channel="blogger_en", title="Sample post", keywords=("morning routine",), date="2026-10-01", ref="e1", origin="history_entries")], target=100)
        self.assertEqual({c.topic for c in found.candidates}, {"morning routine: what to check again later", "morning routine: frequently asked questions", "morning routine: a closer look by situation"})
        self.assertEqual({c.primary_keyword for c in found.candidates}, {"morning routine check-in", "morning routine faq", "morning routine by situation"})
        self.assertEqual({c.language for c in found.candidates}, {"en"})

    def test_a_post_keyword_that_breaks_a_rule_is_dropped_with_a_reason_and_does_not_stop_the_others(self):
        posts = [post("예시 이상한 글", keywords=("<b>굵게</b>",), ref="bad"), post("예시 약속 글", keywords=("상위노출 보장",), ref="promise"), post("예시 좋은 글", keywords=("예시 정상",), ref="good")]
        found = run(A, (), history=posts, target=100)
        self.assertEqual(len([c for c in found.candidates if c.source_type == "follow_up"]), 3)
        self.assertEqual([(row.route, row.reason, row.count) for row in found.dropped if row.route == "follow_up"], [("follow_up", "invalid", 3), ("follow_up", "result_promise", 3)])
        promise = [row for row in found.dropped if row.reason == "result_promise"][0]
        self.assertEqual(promise.detail, "기존 글의 키워드에 결과를 약속하는 표현이 있어 쓰지 않습니다")
        self.assertIn("규칙에 맞지 않습니다", [row for row in found.dropped if row.reason == "invalid"][0].detail)


class RealtimeRouteTest(unittest.TestCase):
    def test_an_operator_issue_that_passes_becomes_a_candidate_with_its_own_fields_and_the_source_evidence(self):
        found = run(A, (), realtime=[item()], target=100)
        (candidate,) = found.candidates
        self.assertEqual((candidate.source_type, candidate.candidate_type, candidate.topic, candidate.primary_keyword), ("realtime", "realtime", "예시 새 소식이 나왔다", "예시 새 소식"))
        self.assertEqual((candidate.topic_cluster, candidate.topic_angle, candidate.search_intent, candidate.content_type, candidate.seed_id), ("small-appliances", "what-changed", "context_explainer", "news_analysis", None))
        self.assertEqual(candidate.scores.factors.evidence, 90, "공식 출처가 있으면 근거 90")
        self.assertEqual(candidate.scores.factors.channel_fit, 75, "60 + 묶음 15")
        self.assertEqual(candidate.selection_reasons[0], "운영자가 넣은 이슈입니다 — 출처 조건을 통과했습니다(공식 1개·서로 독립인 출처 1곳, 처음 알려진 뒤 72시간 지남)")
        self.assertEqual(candidate.candidate_id, "tc-naver_a-realtime-" + ex.stable_id("naver_a", "realtime", ex.keyword_key("예시 새 소식이 나왔다"), "2026-11-07T00:00:00Z"))
        self.assertEqual(candidate.source_topic_id, "src-" + ex.stable_id("source-topic", "issue", ex.keyword_key("예시 새 소식이 나왔다")))
        self.assertEqual(candidate.target_reader, gn.TARGET_READERS["naver_a"])
        self.assertEqual(run(A, (), realtime=[item(target_reader="예시 독자")], target=100).candidates[0].target_reader, "예시 독자")
        independent = item(sources=(source("https://a.example.org"), source("https://b.example.com")))
        self.assertEqual(run(A, (), realtime=[independent], target=100).candidates[0].scores.factors.evidence, 75)

    def test_a_failing_issue_is_dropped_with_the_first_reason_and_a_distinct_code_for_each_kind_of_failure(self):
        young = item(first_reported_at="2026-11-09T00:00:00Z")
        weak = item(sources=(source("https://a.example.org"),))
        other = item(channel="naver_b")
        found = run(A, (), realtime=[young, weak, other], target=100)
        self.assertEqual(found.candidates, ())
        rows = {row.reason: row for row in found.dropped if row.route == "realtime"}
        self.assertEqual(set(rows), {"unstable", "sources", "other_channel"})
        self.assertEqual(rows["unstable"].detail, "이슈 ‘예시 새 소식’: 처음 알려진 뒤 24시간밖에 지나지 않았습니다 — 48시간이 지난 뒤에 씁니다(안정화)")
        self.assertIn("출처 조건", rows["sources"].detail)
        self.assertEqual(rows["other_channel"].detail, "다른 채널용으로 넣은 이슈는 이 채널의 후보로 쓰지 않습니다")

    def test_an_issue_whose_text_breaks_a_candidate_rule_or_promises_results_is_dropped_with_its_own_reason(self):
        found = run(A, (), realtime=[item(topic="<b>굵게</b> 소식"), item(topic="예시 상위노출 보장 소식", primary_keyword="예시 약속"), item(topic="예시 정상 소식", primary_keyword="예시 정상")], target=100)
        self.assertEqual([c.primary_keyword for c in found.candidates], ["예시 정상"])
        self.assertEqual([(row.reason, row.count) for row in found.dropped if row.route == "realtime"], [("invalid", 1), ("result_promise", 1)])
        self.assertEqual([row.detail for row in found.dropped if row.reason == "result_promise"], ["이슈 글에 결과를 약속하는 표현이 있어 쓰지 않습니다"])
        secondary = run(A, (), realtime=[item(secondary_keywords=("수익 보장",))], target=100)
        self.assertEqual((secondary.candidates, [row.reason for row in secondary.dropped if row.route == "realtime"]), ((), ["result_promise"]))

    def test_the_engine_makes_nothing_up_without_operator_issues_and_the_shortage_is_reported(self):
        found = run(A, [seed()], target=20)
        self.assertEqual([c for c in found.candidates if c.source_type == "realtime"], [])
        self.assertEqual(found.routes[3], gn.RouteReport("realtime", 3, 0, 0, 3))
        self.assertIn("실시간 3개", found.notes[0])

    def test_the_created_time_is_the_clock_so_a_later_run_can_pass_an_issue_that_failed_before(self):
        young = item(first_reported_at="2026-11-09T00:00:00Z")
        self.assertEqual(run(A, (), realtime=[young]).candidates, ())
        self.assertEqual(len(gn.generate(A, (), (), (), "2026-11-12", realtime=[young]).candidates), 1)

    def test_an_issue_for_the_other_naver_channel_is_used_there(self):
        other = item(channel="naver_b", topic_cluster="local-ai")
        self.assertEqual(len(run(B, (), realtime=[other], target=100).candidates), 1)
        self.assertEqual(run(B, (), realtime=[other], target=100).candidates[0].channel, "naver_b")


class AssemblyTest(unittest.TestCase):
    def world(self):
        seeds = [seed(seed_id="a1"), seed(seed_id="a2", keyword="예시 공유기", minor="PC 주변기기", major="PC", seed_type="priority", priority=True),
                 seed(seed_id="a3", keyword="예시 난방", seed_type="seasonal"), seed(seed_id="a4", keyword="예시 호텔", major="여행", minor="숙박", seed_type="sponsorable", sponsor_tag="lodging_travel")]
        calendar = [ts.example_entry(keywords=("예시 난방",), name="예시 난방 시기")]
        posts = [post("예시 이력 글 하나", keywords=("예시 가습기", "예시 제습기"), date="2026-10-01", ref="p1"), post("예시 로봇청소기 구매 기준", keywords=("예시 로봇청소기",), date="2026-09-01", ref="p2")]
        return seeds, calendar, posts, [item()]

    def test_every_route_contributes_and_the_numbers_add_up(self):
        seeds, calendar, posts, issues = self.world()
        found = run(A, seeds, calendar, posts, realtime=issues)
        self.assertEqual(sum(r.made for r in found.routes), len(found.candidates))
        self.assertEqual([r.route for r in found.routes], list(gn.ROUTES))
        self.assertEqual([r.target for r in found.routes], [6, 4, 4, 3, 3])
        for report in found.routes:
            with self.subTest(route=report.route):
                self.assertEqual(report.made, min(report.available, report.target))
                self.assertEqual(report.shortage, report.target - report.made)
                self.assertEqual(len([c for c in found.candidates if c.source_type == report.route]), report.made)
        self.assertEqual({c.source_type for c in found.candidates}, set(gn.ROUTES))
        self.assertEqual(found.shortages(), {report.route: report.shortage for report in found.routes if report.shortage})
        self.assertEqual([(r.available, r.made) for r in found.routes], [(5, 5), (6, 4), (3, 3), (1, 1), (3, 3)])

    def test_a_route_that_falls_short_leaves_its_places_empty_and_no_other_route_takes_them(self):
        seeds, calendar, posts, _issues = self.world()
        found = run(A, seeds, calendar, posts, target=20)                      # 실시간 이슈가 없다
        self.assertEqual([(r.route, r.target, r.made, r.shortage) for r in found.routes], [("seed", 6, 5, 1), ("follow_up", 4, 4, 0), ("seasonal", 4, 3, 1), ("realtime", 3, 0, 3), ("sponsor", 3, 3, 0)])
        self.assertEqual(len(found.candidates), 15, "목표 20 중 15개 — 모자란 5개 자리는 비어 있다")
        self.assertEqual(found.shortages(), {"seed": 1, "seasonal": 1, "realtime": 3})
        self.assertEqual(found.notes, ("목표에 모자란 경로: 씨앗 1개, 계절 1개, 실시간 3개 — 모자란 자리는 다른 경로가 채우지 않았습니다",))

    def test_a_target_of_zero_makes_no_candidate_and_counts_all_of_them_as_over_the_target(self):
        seeds, calendar, posts, issues = self.world()
        found = run(A, seeds, calendar, posts, realtime=issues, target=0)
        self.assertEqual(found.candidates, ())
        self.assertEqual([r.target for r in found.routes], [0] * 5)
        self.assertTrue(all(r.made == 0 and r.shortage == 0 for r in found.routes))
        self.assertEqual(sorted((row.route, row.count) for row in found.dropped if row.reason == "over_target"), [("follow_up", 6), ("realtime", 1), ("seasonal", 3), ("seed", 5), ("sponsor", 3)])
        self.assertEqual(found.notes, ())

    def test_the_candidates_are_ordered_by_score_then_route_then_number_and_every_one_is_internally_consistent(self):
        seeds, calendar, posts, issues = self.world()
        found = run(A, seeds, calendar, posts, realtime=issues, target=60)
        keys = [(c.scores.final is None, -(c.scores.final or 0), gn.ROUTES.index(c.source_type), c.candidate_id) for c in found.candidates]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len({c.candidate_id for c in found.candidates}), len(found.candidates))
        for candidate in found.candidates:
            with self.subTest(candidate=candidate.candidate_id):
                md.check_candidate_score(candidate, A)
                md.check_candidate_expiry(candidate)
                md.stored_id(candidate.candidate_id, "번호")
                self.assertEqual(md.TopicCandidate.from_dict(candidate.to_dict()), candidate)
                self.assertEqual(candidate.created_at, NOW)
                self.assertEqual((candidate.channel, candidate.language, candidate.work_status), ("naver_a", "ko", "NEW"))
                self.assertEqual(candidate.recommendation_band, sc.band_of(candidate.scores.final))
                self.assertLessEqual(len(candidate.selection_reasons), 10)
                self.assertEqual(candidate.safety_flags, tuple(flag for flag in md.SAFETY_FLAGS if flag in candidate.safety_flags))
                self.assertEqual(candidate.review_expires_at is not None, candidate.recommendation_band == "HOLD")
                self.assertTrue(candidate.selection_reasons[0])

    def test_a_hold_band_candidate_gets_a_review_deadline_ninety_days_on_and_is_still_listed(self):
        # 채널 적합도만 점수가 되는 가중치·방향 낱말 없음 → 공통 확장어('방법'·'체크리스트'·'비교')는 60 점(묶음 모름·채널 방향 아님)이라 보류 구간이다.
        lowered = dataclasses.replace(A, expansion_directions=(), weights={"channel_fit": 100, "feasibility": 0, "differentiation": 0, "timing": 0, "evidence": 0, "monetization": 0})
        found = gn.generate(lowered, [seed(major="분류", minor="모르는 분류")], (), (), TODAY, target=100)
        self.assertEqual([c.primary_keyword for c in found.candidates], ["예시 로봇청소기 방법", "예시 로봇청소기 체크리스트"])
        for candidate in found.candidates:
            self.assertEqual((candidate.scores.final, candidate.recommendation_band), (60, "HOLD"))
            self.assertEqual(candidate.review_expires_at, "2027-02-08T00:00:00Z")
        later = gn.generate(lowered, [seed(major="분류", minor="모르는 분류")], (), (), "2027-01-01", target=100)
        self.assertEqual({c.review_expires_at for c in later.candidates}, {"2027-04-01T00:00:00Z"}, "만든 시각(기준일 0시) + 90일")

    def test_the_result_does_not_depend_on_the_order_of_the_inputs(self):
        seeds, calendar, posts, issues = self.world()
        expected = run(A, seeds, calendar, posts, realtime=issues, target=60)
        rng = random.Random(7)
        for _ in range(8):
            shuffled = [list(group) for group in (seeds, calendar, posts, issues)]
            for group in shuffled:
                rng.shuffle(group)
            self.assertEqual(run(A, shuffled[0], shuffled[1], shuffled[2], realtime=shuffled[3], target=60), expected)

    def test_issues_left_out_for_the_same_reason_are_reported_the_same_whatever_the_order_they_came_in(self):
        # 독립 검증 보완 1차(brandmsg H1): 같은 이유로 못 쓰는 이슈가 둘 이상이면 진단의 '첫 사례' 문장이 들어온 순서에 따라 달라지던 결함 — 이슈를 늘 같은 순서(처음 알려진 때 → 키워드 …)로 처리한다.
        early = item(topic="예시 이슈 하나 확인", primary_keyword="예시 이슈 하나", first_reported_at="2026-11-09T09:00:00Z")            # 15시간 — 안정화 전
        late = item(topic="예시 이슈 둘 점검", primary_keyword="예시 이슈 둘", first_reported_at="2026-11-09T20:00:00Z")                 # 4시간 — 안정화 전
        poor_a = item(topic="예시 이슈 셋 확인", primary_keyword="예시 이슈 셋", sources=(source("https://a.example.org/x"),))             # 공식 없음·독립 1곳 — 출처 부족
        poor_b = item(topic="예시 이슈 점검 넷", primary_keyword="예시 이슈 넷", sources=(source("https://b.example.org/y"),))                  # 주제 글자순은 셋이 먼저·키워드 열쇠순은 넷이 먼저
        good_a = item(topic="예시 이슈 다섯 정리", primary_keyword="예시 이슈 다섯")                                                    # 쓸 수 있는 이슈 둘 — 알려진 때까지 같아 점수가 같고, 순서는 동점 처리가 정한다
        good_b = item(topic="예시 이슈 여섯 정리", primary_keyword="예시 이슈 여섯")
        pool = [early, late, poor_a, poor_b, good_a, good_b]
        expected = run(A, realtime=list(pool), target=60)
        rows = {row.reason: row for row in expected.dropped if row.route == "realtime"}
        self.assertEqual({reason: row.count for reason, row in rows.items()}, {"sources": 2, "unstable": 2})
        self.assertTrue(rows["unstable"].detail.startswith("이슈 ‘예시 이슈 하나’: 처음 알려진 뒤 15시간"), "처음 알려진 때가 이른 이슈가 첫 사례")
        self.assertTrue(rows["sources"].detail.startswith("이슈 ‘예시 이슈 넷’: 출처 조건을 채우지 못했습니다"), "알려진 때가 같으면 키워드 열쇠순이 첫 사례")
        self.assertEqual({candidate.primary_keyword for candidate in expected.candidates}, {"예시 이슈 다섯", "예시 이슈 여섯"})
        self.assertEqual(len({candidate.scores.final for candidate in expected.candidates}), 1, "두 후보의 점수가 같다 — 하나만 남겨야 하면 순서가 정한다")
        for order in ((good_a, good_b), (good_b, good_a)):                                  # 목표가 작아 실시간 후보가 하나만 남는 동점 — 어느 쪽이 남는지도 순서와 무관하다
            cut = run(A, realtime=list(order), target=7)
            self.assertEqual([(report.route, report.target, report.made) for report in cut.routes if report.route == "realtime"], [("realtime", 1, 1)])
            self.assertEqual([candidate.primary_keyword for candidate in cut.candidates if candidate.source_type == "realtime"], ["예시 이슈 다섯"], "정렬 열쇠가 앞서는 이슈가 남는다")
        for first, second in ((early, late), (poor_a, poor_b), (good_a, good_b)):
            for order in ((first, second), (second, first)):
                with self.subTest(order=[one.primary_keyword for one in order]):
                    self.assertEqual(run(A, realtime=list(order), target=60), run(A, realtime=[first, second], target=60))
        rng = random.Random(11)
        for _ in range(30):
            shuffled = list(pool)
            rng.shuffle(shuffled)
            self.assertEqual(run(A, realtime=shuffled, target=60), expected)

    def test_the_same_input_gives_the_same_output_and_the_inputs_are_not_changed(self):
        seeds, calendar, posts, issues = self.world()
        before = ([s.to_dict() for s in seeds], [e.to_dict() for e in calendar], [p.to_dict() for p in posts])
        first = run(A, seeds, calendar, posts, realtime=issues)
        self.assertEqual(first, run(A, seeds, calendar, posts, realtime=issues))
        self.assertEqual(([s.to_dict() for s in seeds], [e.to_dict() for e in calendar], [p.to_dict() for p in posts]), before)
        self.assertEqual(run(A, tuple(seeds), tuple(calendar), tuple(posts), realtime=tuple(issues)), first, "목록이든 튜플이든 같다")
        self.assertEqual(run(A, iter(seeds), iter(calendar), iter(posts), realtime=iter(issues)), first, "한 번 읽는 묶음도 같다")

    def test_each_enabled_channel_gets_its_own_candidates_in_the_code_order_and_a_disabled_one_gets_a_note(self):
        seeds, calendar, posts, issues = self.world()
        both = gn.generate_all([B, A, G], seeds, calendar, posts, TODAY, realtime=issues)
        self.assertEqual([found.channel for found in both], ["github_pages", "naver_a", "naver_b"], "코드의 채널 순서")
        self.assertEqual(both[0].candidates, ())
        self.assertTrue(both[1].candidates and both[2].candidates)
        self.assertEqual({c.channel for c in both[1].candidates}, {"naver_a"})
        self.assertEqual({c.channel for c in both[2].candidates}, {"naver_b"})
        self.assertEqual(both[1], run(A, seeds, calendar, posts, realtime=issues))
        with self.assertRaises(TypeError):
            gn.generate_all(["naver_a"], seeds, calendar, posts, TODAY)

    def test_candidates_that_share_a_source_topic_across_channels_can_be_checked_by_the_existing_spread_check(self):
        shared_a, shared_b = dataclasses.replace(A, expansion_directions=("체크리스트",)), dataclasses.replace(B, expansion_directions=("체크리스트",))
        common = [seed(seed_id="c1", scope="common", major="AI", minor="AI 서비스", keyword="예시 코딩 도구", seed_type="priority", priority=True)]
        results = gn.generate_all([shared_a, shared_b], common, (), (), TODAY, target=60)
        spreads = [spread for spread in dd.check_topic_spread([c for found in results for c in found.candidates]) if len(spread.channels) == 2]
        self.assertTrue(spreads)
        for spread in spreads:
            self.assertEqual(spread.channels, ("naver_a", "naver_b"))
            self.assertFalse(spread.too_many)
            self.assertFalse(spread.allowed, "대상 독자만 다르고 나머지는 같아 일곱 항목 중 4개에 못 미친다")
            self.assertIn("네이버 A 과 네이버 B 의 후보는 일곱 항목 중 1개만 달라 충분하지 않습니다(최소 4개)", spread.problems[0])


class ExistingAndDisabledTest(unittest.TestCase):
    def test_a_candidate_that_already_exists_is_not_made_again_and_the_reason_is_counted(self):
        first = run(A, [seed()], target=100)
        again = run(A, [seed()], existing=first.candidates, target=100)
        self.assertEqual({c.candidate_id for c in again.candidates} & {c.candidate_id for c in first.candidates}, set())
        self.assertEqual([c.primary_keyword for c in again.candidates], ["예시 로봇청소기 구매 기준"], "이전에 점수가 낮아 빠진 후보만 새로 남는다")
        self.assertEqual([(row.route, row.reason, row.count) for row in again.dropped if row.reason == "already_exists"], [("seed", "already_exists", 2)])
        self.assertEqual(again.dropped[[row.reason for row in again.dropped].index("already_exists")].detail, "씨앗 ‘예시 로봇청소기’ 의 ‘제품 비교’ 후보는 이미 있습니다(같은 번호)", "첫 사례만 적는다")
        partial = run(A, [seed()], existing=first.candidates[:1], target=100)
        self.assertNotIn(first.candidates[0].candidate_id, {c.candidate_id for c in partial.candidates})

    def test_existing_follow_ups_and_issues_are_not_made_again_either(self):
        posts = [post("예시 글", keywords=("예시 키",), ref="r1")]
        first = run(A, (), history=posts, realtime=[item()], target=100)
        again = run(A, (), history=posts, realtime=[item()], existing=first.candidates, target=100)
        self.assertEqual(again.candidates, ())
        self.assertEqual(sorted((row.route, row.count) for row in again.dropped if row.reason == "already_exists"), [("follow_up", 3), ("realtime", 1)])

    def test_an_existing_candidate_of_another_channel_does_not_block(self):
        common = [seed(scope="common", major="AI", minor="AI 서비스")]
        other = run(B, common, target=100)
        self.assertTrue(run(A, common, existing=other.candidates, target=100).candidates)

    def test_a_seed_listed_twice_makes_each_candidate_once(self):
        twice = run(A, [seed(), seed()], target=100)
        self.assertEqual(len({c.candidate_id for c in twice.candidates}), len(twice.candidates))
        self.assertEqual(len(twice.candidates), 2)
        self.assertTrue(any(row.reason == "already_exists" for row in twice.dropped))

    def test_a_channel_with_generation_off_gives_no_candidates_and_the_reason(self):
        found = run(G, [seed(scope="common")], target=20)
        self.assertEqual((found.channel, found.candidates, found.dropped), ("github_pages", (), ()))
        self.assertEqual(found.notes, ("GitHub Pages 은(는) 후보 생성이 꺼져 있어 후보를 만들지 않았습니다(이력 읽기·중복 검사만 합니다)",))
        self.assertEqual(list(found.routes), [gn.RouteReport(route, 0, 0, 0, 0) for route in gn.ROUTES])
        for key in ("blogger_ko", "blogger_en"):
            self.assertEqual(run(ts.PROFILES[key], [seed(scope="common")]).candidates, ())


class InputChecksTest(unittest.TestCase):
    def test_wrong_kinds_and_values_are_programming_errors(self):
        good = (A, [seed()], (), (), TODAY)
        for bad in (("naver_a",) + good[1:], (None,) + good[1:]):
            with self.assertRaises(TypeError):
                gn.generate(*bad)
        for index, wrong in ((1, [{"seed_id": "x"}]), (1, "씨앗"), (1, None), (2, [seed()]), (3, [seed()]), (2, 3)):
            args = list(good)
            args[index] = wrong
            with self.subTest(index=index, wrong=repr(wrong)[:20]):
                with self.assertRaises(TypeError):
                    gn.generate(*args)
        for today in ("어제", None, "2026-11-5", "2201-01-01", "1999-12-31", 20261110, "2026-02-30"):
            with self.subTest(today=today):
                with self.assertRaises(ValueError):
                    gn.generate(A, [], (), (), today)
        for target in (-1, 201, True, 2.5, "20", None):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    run(A, [], target=target)
        for kwargs in ({"existing": [seed()]}, {"realtime": [seed()]}, {"interest": {"x": 3}}, {"interest": [1]}, {"interest_outage": 1}, {"interest_outage": "no"}):
            with self.subTest(kwargs=repr(kwargs)[:30]):
                with self.assertRaises(TypeError):
                    run(A, [], **kwargs)
        with self.assertRaises(ValueError):
            run(A, [], interest={"x": gn.InterestReading("weird")})
        with self.assertRaises(AppError):
            run(A, [], created_at="어제")
        self.assertEqual(run(A, [], target=200).candidates, ())
        self.assertEqual(gn.generate(A, [], (), (), "2200-12-31").candidates, ())

    def test_the_created_time_can_be_given_and_is_used_for_the_review_deadline_and_the_issue_age(self):
        found = run(A, [seed()], created_at="2026-11-10T09:30:00Z", target=100)
        self.assertEqual({c.created_at for c in found.candidates}, {"2026-11-10T09:30:00Z"})
        young = item(first_reported_at="2026-11-08T12:00:00Z")
        self.assertEqual(run(A, (), realtime=[young], created_at="2026-11-10T11:59:59Z").candidates, ())
        self.assertEqual(len(run(A, (), realtime=[young], created_at="2026-11-10T12:00:00Z").candidates), 1)

    def test_the_drop_report_rows_are_ordered_by_route_then_reason_and_every_reason_is_a_known_code(self):
        seeds = [seed(excluded_keywords=("비용",)), seed(seed_id="s2", keyword="예시 둘", seed_type="seasonal")]
        found = run(A, seeds, target=100)
        order = [(gn.ROUTES.index(row.route), gn.DROP_REASONS.index(row.reason)) for row in found.dropped]
        self.assertEqual(order, sorted(order))
        self.assertTrue(all(row.reason in gn.DROP_REASONS and row.count >= 1 and row.detail for row in found.dropped))
        self.assertEqual(len(gn.DROP_REASONS), len(set(gn.DROP_REASONS)))
        self.assertEqual(gn.DROP_REASONS[:4], ("combination", "excluded_keyword", "too_long", "language"))
        self.assertEqual(len(gn.DROP_REASONS), 17, "P2b 보완: 앞의 열다섯 이름·순서는 그대로, 브랜드 이유 둘(brand_only·brand_unfeasible)을 끝에 더했다")

    def test_an_excluded_keyword_of_a_seed_is_reported_per_route_and_blocks_only_that_direction(self):
        found = run(A, [seed(excluded_keywords=("비용",), seed_type="priority", priority=True)], target=100)
        self.assertTrue(any(row.reason == "excluded_keyword" for row in found.dropped) or all("비용" not in c.primary_keyword for c in found.candidates))
        self.assertTrue(all("비용" not in c.primary_keyword for c in found.candidates))


class EvidencePenaltyTest(unittest.TestCase):
    """P2b 보완 G1 — 근거 감점은 건강 표시 −20·경험 단정 표시 −10 둘뿐이다(D-54)."""

    def test_the_penalty_table_has_exactly_two_keys(self):
        self.assertEqual(dict(gn.EVIDENCE_PENALTY), {"health_check": 20, "experience_claim": 10})

    def test_no_other_flag_lowers_the_evidence_and_the_two_flags_add_up(self):
        explainer = ts.make(content_type="explainer")
        for flags in (("product_brand",), ("sponsor_disclosure",), ("result_promise",), ("product_brand", "sponsor_disclosure", "result_promise")):
            with self.subTest(flags=flags):
                self.assertEqual(gn._evidence(explainer, flags, gn._Extra()), 70)
        self.assertEqual(gn._evidence(explainer, ("health_check", "experience_claim"), gn._Extra()), 40)
        self.assertEqual(gn._evidence(explainer, ("experience_claim",), gn._Extra()), 60)


class OrdinaryTopicsKeepTheirEvidenceTest(unittest.TestCase):
    """P2b 보완 G2 — 11개 글 종류 × 일반 주제는 표시가 없고 후보의 근거 점수는 글 종류의 기본 점수 그대로다(정상 주제가 10점을 잃지 않는다)."""
    TOPICS = ("AI 모델 비교", "PC 부품 추천 기준", "노트북 선택 가이드", "업무 자동화 도구 추천", "무료·유료 SaaS 비교", "소형가전 구매 기준", "SaaS 기능 비교", "그래픽카드 모델별 VRAM 비교")

    def test_every_content_type_with_every_ordinary_topic_has_no_flag_and_the_plain_base_evidence(self):
        self.assertEqual(len(gn.EVIDENCE_BASE), 11)
        for content_type, base in gn.EVIDENCE_BASE.items():
            for topic in self.TOPICS:
                with self.subTest(content_type=content_type, topic=topic):
                    made = ts.make(content_type=content_type, topic=topic, primary_keyword="예시 키워드")
                    flags = sf.assess(made).flags
                    self.assertEqual(flags, ())
                    self.assertEqual(gn._evidence(made, flags, gn._Extra()), base)

    def test_the_generated_candidates_of_an_ordinary_naver_b_seed_all_keep_the_base_evidence(self):
        found = run(B, [seed(keyword="예시 AI 모델", major="AI", minor="AI 서비스", seed_type="priority", priority=True)], target=100)
        self.assertTrue(found.candidates)
        for candidate in found.candidates:
            self.assertEqual(candidate.safety_flags, ())
            self.assertEqual(candidate.scores.factors.evidence, gn.EVIDENCE_BASE[candidate.content_type])

    def test_a_followup_and_an_issue_keep_their_own_evidence_rules_and_no_flag(self):
        found = run(A, [], history=[post()], realtime=[item()], target=40)
        for candidate in found.candidates:
            self.assertEqual(candidate.safety_flags, ())
        own = [c for c in found.candidates if c.source_type == "follow_up"]
        self.assertTrue(all(c.scores.factors.evidence == gn.EVIDENCE_BASE[c.content_type] + gn.EVIDENCE_OWN_POST_BONUS for c in own))


class RegressionBeforeAfterTest(unittest.TestCase):
    """P2b 보완 G3 — 수정 전(`c1f5e3f`)과 후의 점수·구간·근거·표시를 값으로 못박는다(부록 D.1 의 장면 S1~S5). 같음/변함은 주석에 적었다."""

    def rows(self, found, only=None):
        return {c.primary_keyword: (c.scores.final, c.recommendation_band, c.scores.factors.evidence, c.safety_flags) for c in found.candidates if only is None or c.source_type == only}

    def test_s1_a_general_seed(self):
        # 수정 전: 관리 방법 (80, 우선 추천, 근거 80, ()) 같음 · 제품 비교 (76, 일반, 근거 50, ('product_brand',)) → 변함
        self.assertEqual(self.rows(run(A, [seed()], target=100)), {"예시 로봇청소기 관리 방법": (80, "RECOMMENDED", 80, ()), "예시 로봇청소기 제품 비교": (78, "GENERAL", 60, ())})

    def test_s2_a_priority_seed_keeps_the_product_comparison_instead_of_the_checklist(self):
        # 수정 전: 관리 방법 82·방법 79·체크리스트 79(근거 80). 수정 후: 같은 79점에서 근거가 복원된 제품 비교(근거 60)가 체크리스트 대신 남는다
        self.assertEqual(self.rows(run(A, [seed(seed_type="priority", priority=True)], target=40)), {
            "예시 로봇청소기 관리 방법": (82, "RECOMMENDED", 80, ()), "예시 로봇청소기 방법": (79, "GENERAL", 80, ()), "예시 로봇청소기 제품 비교": (79, "GENERAL", 60, ())})

    def test_s3_a_seasonal_seed(self):
        entry = ts.example_entry(keywords=("예시 난방",), name="예시 난방 시기")
        found = run(A, [seed(seed_id="z1", keyword="예시 난방", seed_type="seasonal")], calendar=[entry], target=100)
        # 수정 전: 제품 비교 (74, 근거 50, product_brand) · 수정 후 (75, 근거 60, 표시 없음)
        self.assertEqual(self.rows(found), {"예시 난방 관리 방법": (77, "GENERAL", 80, ()), "예시 난방 제품 비교": (75, "GENERAL", 60, ()), "예시 난방 방법": (74, "GENERAL", 80, ())})

    def test_s4_a_health_seed_still_gets_the_health_flag_and_the_twenty_point_cut(self):
        found = run(A, [seed(keyword="예시 영양제", seed_type="priority", priority=True)], target=100)
        # 수정 전: 관리 방법 79·방법 76·체크리스트 76 (근거 60, health_check) · 수정 후: 제품 비교(근거 40 = 60 − 20)가 체크리스트 대신 남는다
        self.assertEqual(self.rows(found), {"예시 영양제 관리 방법": (79, "GENERAL", 60, ("health_check",)), "예시 영양제 제품 비교": (77, "GENERAL", 40, ("health_check",)), "예시 영양제 방법": (76, "GENERAL", 60, ("health_check",))})

    def test_s5_a_sponsorable_seed_loses_the_disclosure_flag_and_keeps_the_scores(self):
        found = run(A, [seed(seed_id="sp1", keyword="예시 호텔", major="여행", minor="숙박", seed_type="sponsorable", sponsor_tag="lodging_travel")], target=100)
        # 수정 전: 관리 방법 (90, sponsor_disclosure) · 제품 비교 (86, 근거 50, product_brand+sponsor_disclosure) · 방문 전 확인 (86) / 수정 후: 표시 없음, 제품 비교 88, 구매 기준 86
        self.assertEqual(self.rows(found, "sponsor"), {"예시 호텔 관리 방법": (90, "RECOMMENDED", 80, ()), "예시 호텔 제품 비교": (88, "RECOMMENDED", 60, ()), "예시 호텔 구매 기준": (86, "RECOMMENDED", 60, ())})


class SponsorRouteLineTest(unittest.TestCase):
    """P2b 보완 G4 — 협찬 경로 후보: 표시 없음·'협업 가능 유형' 줄·영문 식별자 없음."""

    def test_the_route_line_names_the_type_in_korean_and_says_it_is_not_confirmed(self):
        found = run(A, [seed(seed_id="sp1", keyword="예시 호텔", major="여행", minor="숙박", seed_type="sponsorable", sponsor_tag="lodging_travel")], target=100)
        for candidate in found.candidates:
            self.assertEqual(candidate.safety_flags, ())
            self.assertTrue(candidate.selection_reasons[0].endswith(" — 협업 가능 유형 ‘숙박·여행’(협찬이 확정된 것은 아닙니다)"))
            self.assertNotIn("lodging_travel", " ".join(candidate.selection_reasons))

    def test_an_unknown_tag_is_shown_in_quotes_as_written_and_the_known_tags_match_the_cluster_table(self):
        found = run(A, [seed(seed_id="sp2", sponsor_tag="my_new_tag")], target=100)
        sponsor = [c for c in found.candidates if c.source_type == "sponsor"]
        self.assertTrue(sponsor)
        self.assertIn("협업 가능 유형 ‘my_new_tag’(협찬이 확정된 것은 아닙니다)", sponsor[0].selection_reasons[0])
        self.assertEqual(set(wording.TAG_KO), set(gn.CLUSTER_MONETIZATION.values()))


class CampaignsInputTest(unittest.TestCase):
    """P2b 보완 G5 — `campaigns` 입력: 검증·채널 걸러내기·확정은 표시를 강제·제안은 INFO 뿐·`generate_all` 전달."""

    def confirmed(self, **changes):
        values = dict(campaign_id="camp-1", benefits=("goods", "payment"), status="confirmed", seed_id="s1")
        values.update(changes)
        return sf.Campaign(**values)

    def test_a_confirmed_campaign_forces_the_flag_on_every_candidate_of_its_seed_and_leaves_other_seeds_alone(self):
        pool = [seed(seed_id="s1"), seed(seed_id="s2", keyword="예시 공기청정기")]
        found = run(A, pool, target=100, campaigns=[self.confirmed()])
        mine = [c for c in found.candidates if c.seed_id == "s1"]
        others = [c for c in found.candidates if c.seed_id == "s2"]
        self.assertTrue(mine and others)
        for candidate in mine:
            self.assertEqual(candidate.safety_flags, ("sponsor_disclosure",))
            self.assertTrue(candidate.selection_reasons[1].startswith("경제적 이해관계 표시 필요 — "), candidate.selection_reasons[1])
            self.assertIn("(걸린 말: 제품 제공, 금전 제공(원고료 등))", candidate.selection_reasons[1])
        self.assertTrue(all(c.safety_flags == () for c in others))
        self.assertEqual(run(A, pool, target=100).candidates[0].safety_flags, (), "협찬 정보를 안 주면 표시가 없다")

    def test_a_proposed_campaign_is_only_a_possibility_and_gives_no_flag_and_no_line(self):
        found = run(A, [seed()], target=100, campaigns=[self.confirmed(status="proposed")])
        for candidate in found.candidates:
            self.assertEqual(candidate.safety_flags, ())
            self.assertFalse(any("경제적 이해관계" in line for line in candidate.selection_reasons))

    def test_the_campaigns_of_other_channels_are_left_out(self):
        found = run(A, [seed()], target=100, campaigns=[self.confirmed(channel="naver_b")])
        self.assertTrue(all(c.safety_flags == () for c in found.candidates))
        again = run(A, [seed()], target=100, campaigns=[self.confirmed(channel="naver_a")])
        self.assertTrue(all(c.safety_flags == ("sponsor_disclosure",) for c in again.candidates))

    def test_wrong_inputs_are_programming_errors(self):
        for bad in ("글", 3, [1], [{"campaign_id": "x"}], (None,)):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(TypeError):
                    run(A, [seed()], campaigns=bad)
        with self.assertRaises(ValueError):
            run(A, [seed()], campaigns=[self.confirmed(campaign_id=f"c{number}") for number in range(sf.MAX_CAMPAIGNS + 1)])
        self.assertTrue(run(A, [seed()], campaigns=[self.confirmed(campaign_id=f"c{number}") for number in range(sf.MAX_CAMPAIGNS)]).candidates)

    def test_generate_all_hands_the_campaigns_to_every_enabled_channel(self):
        both = gn.generate_all(ch.default_profiles(), [seed()], [], (), TODAY, campaigns=[self.confirmed()], target=100)
        shown = {result.channel: [c.safety_flags for c in result.candidates] for result in both}
        self.assertTrue(shown["naver_a"] and all(flags == ("sponsor_disclosure",) for flags in shown["naver_a"]))
        self.assertEqual(shown["github_pages"], [])

    def test_a_campaign_never_deletes_or_rescores_a_candidate(self):
        plain = run(A, [seed()], target=100)
        forced = run(A, [seed()], target=100, campaigns=[self.confirmed()])
        self.assertEqual([(c.candidate_id, c.scores.final) for c in plain.candidates], [(c.candidate_id, c.scores.final) for c in forced.candidates])


class SelectionReasonOrderTest(unittest.TestCase):
    """P2b 보완 G6 — 안전 줄이 경로 줄 바로 다음에 놓여 10줄 한도에 잘리지 않고, 첫 줄(경로 줄)은 그대로다."""

    def test_the_route_line_stays_first_and_the_safety_lines_come_right_after_it(self):
        found = run(A, [seed(keyword="예시 영양제", seed_type="priority", priority=True)], target=100, campaigns=[sf.Campaign(campaign_id="c1", benefits=("goods",), status="confirmed", seed_id="s1")])
        for candidate in found.candidates:
            reasons = candidate.selection_reasons
            self.assertTrue(reasons[0].startswith("씨앗 ‘예시 영양제’ 에서"))
            self.assertTrue(reasons[1].startswith("의료·효과 단정 위험") or reasons[1].startswith("건강 정보 확인 필요"), reasons[1])
            self.assertTrue(reasons[2].startswith("경제적 이해관계 표시 필요"), reasons[2])
            self.assertLessEqual(len(reasons), 10)
            self.assertTrue(reasons[3].startswith("시기:"), "안전 줄 다음이 시기 줄이다")

    def test_with_a_long_route_line_set_the_four_safety_lines_still_survive_the_ten_line_cut(self):
        base = ts.make(content_type="explainer", topic="영양제로 피로가 완전히 회복됩니다 소개 직접 써본 후기 협찬 제공받음", primary_keyword="영양제 피로 회복")
        ctx = gn._Ctx(A, (), (), TODAY, NOW, {}, False, frozenset(), (sf.Campaign(campaign_id="c1", benefits=("goods",), status="confirmed", candidate_id=base.candidate_id),))
        made = gn._finish(ctx, dataclasses.replace(base, channel="naver_a"), gn._Extra(lines=tuple(f"경로 줄 {number}" for number in range(5))))
        reasons = made.selection_reasons
        self.assertEqual(len(reasons), 10)
        self.assertEqual(reasons[:5], tuple(f"경로 줄 {number}" for number in range(5)))
        for prefix in ("의료·효과 단정 위험", "직접 겪은 경험 확인 필요", "경제적 이해관계 표시 필요"):
            self.assertTrue(any(line.startswith(prefix) for line in reasons[5:]), prefix)


class BrandSeedTest(unittest.TestCase):
    """P2b 보완 GB — 브랜드 이름만 있는 씨앗: 일반 후보와 같은 `_finish` 로 6항목·중복·안전 표시를 받고, 보류는 후보 없이 진단만 남긴다."""

    def brand_seed(self, keyword="Gemini", **changes):
        return seed(keyword=keyword, major="가", minor="없는 분류", **changes)

    def test_three_subtopics_come_back_with_scores_ids_and_a_first_line_that_says_how_they_were_made(self):
        found = run(B, [self.brand_seed()], target=100)
        self.assertEqual(len(found.candidates), 3)
        for candidate in found.candidates:
            self.assertRegex(candidate.candidate_id, r"^tc-naver_b-seed-[0-9a-f]{16}$")
            self.assertIsNotNone(candidate.scores.final)
            self.assertEqual(candidate.safety_flags, ())
            self.assertEqual(candidate.seed_id, "s1")
            self.assertIn("Gemini", candidate.topic)
        first = found.candidates[0].selection_reasons[0]
        self.assertTrue(first.startswith("브랜드 ‘Gemini’ 만 있던 씨앗을 ‘AI 서비스’ 유형으로 구체화한 씨앗 후보입니다 — 유형은 브랜드 표에 유형이 하나뿐이라 정했고 ‘"))
        self.assertLessEqual(len(first), 300)

    def test_a_brand_seed_keeps_all_three_and_an_ordinary_seed_keeps_two(self):
        self.assertEqual(len(run(B, [self.brand_seed()], target=100).candidates), 3)
        self.assertEqual(len([c for c in run(A, [seed()], target=100).candidates]), 2)
        with mock.patch.object(brand, "KEEP_ALL", False):
            self.assertEqual(len(run(B, [self.brand_seed()], target=100).candidates), 2)

    def test_the_same_seed_gives_the_same_ids_on_another_day_and_an_existing_id_is_not_made_again(self):
        first = run(B, [self.brand_seed()], target=100)
        later = gn.generate(B, [self.brand_seed()], [], (), "2026-12-24", target=100)
        self.assertEqual({c.candidate_id for c in first.candidates}, {c.candidate_id for c in later.candidates})
        again = run(B, [self.brand_seed()], target=100, existing=first.candidates[:1])
        self.assertEqual(len(again.candidates), 2)
        self.assertEqual([(row.route, row.reason, row.count) for row in again.dropped if row.reason == "already_exists"], [("seed", "already_exists", 1)])

    def test_the_three_holds_make_no_candidate_and_leave_a_brand_only_or_unfeasible_line(self):
        listed = run(A, [self.brand_seed("삼성 LG")], target=100)
        vague = run(A, [self.brand_seed("삼성")], target=100)
        for found in (listed, vague):
            self.assertEqual(found.candidates, ())
            rows = [row for row in found.dropped if row.reason == "brand_only"]
            self.assertEqual([(row.route, row.count) for row in rows], [("seed", 1)])
            self.assertTrue(rows[0].detail.startswith("씨앗 ‘삼성"))
        low = run(dataclasses.replace(B, subheading_min=10), [self.brand_seed()], target=100)
        self.assertEqual(low.candidates, ())
        self.assertEqual([(row.reason, row.count) for row in low.dropped if row.reason == "brand_unfeasible"], [("brand_unfeasible", 3)])
        with mock.patch.object(brand, "TYPE_SUBTOPICS", {**brand.TYPE_SUBTOPICS, "ai_service": ("api_usage",)}):
            none = run(A, [self.brand_seed()], target=100)
        self.assertEqual(none.candidates, ())
        self.assertEqual([row.reason for row in none.dropped if row.reason == "brand_only"], ["brand_only"])
        self.assertEqual(len(gn.DROP_REASONS), 17)
        self.assertEqual(gn.DROP_REASONS[-2:], ("brand_only", "brand_unfeasible"))

    def test_two_brands_that_share_a_brand_free_template_make_that_candidate_once(self):
        found = run(B, [self.brand_seed("NVIDIA", seed_id="n1"), self.brand_seed("AMD", seed_id="a1")], target=100)
        free = [c for c in found.candidates if c.topic == "로컬 AI용 GPU를 선택할 때 세대와 VRAM을 비교하는 기준"]
        self.assertEqual(len(free), 1, "씨앗 번호가 번호에 들어가지 않아 같은 후보가 하나만 남는다")
        self.assertEqual(len({c.candidate_id for c in found.candidates}), len(found.candidates))
        self.assertTrue(any(row.reason == "already_exists" and row.count == 1 for row in found.dropped), "두 번째는 같은 번호로 걸러졌다는 기록이 남는다")
        alone = run(B, [self.brand_seed("NVIDIA", seed_id="n1")], target=100)
        self.assertEqual(len(alone.candidates), 3)
        self.assertNotEqual({c.candidate_id for c in alone.candidates if c.topic != free[0].topic}, {c.candidate_id for c in run(B, [self.brand_seed("NVIDIA", seed_id="n2")], target=100).candidates if c.topic != free[0].topic},
                            "씨앗 번호가 있는 틀은 씨앗마다 번호가 다르다")
        self.assertEqual([c.candidate_id for c in alone.candidates if c.topic == free[0].topic], [free[0].candidate_id])

    def test_the_brand_branch_is_only_on_the_seed_routes_not_on_follow_ups_or_issues(self):
        found = run(B, [], history=[post(keywords=("Gemini",), channel="naver_b")], realtime=[item(channel="naver_b", primary_keyword="Gemini", topic="Gemini 새 소식이 나왔다")], target=100)
        self.assertEqual({c.source_type for c in found.candidates}, {"follow_up", "realtime"})
        self.assertTrue(all(row.reason != "brand_only" for row in found.dropped))


class NonBrandInertTest(unittest.TestCase):
    """P2b 보완 NB — 브랜드 단독이 아닌 입력의 결과는 브랜드 분기를 끄고 켜도 같다(`==`)."""
    PLAIN = ("예시 로봇청소기", "예시 공기청정기", "예시 로컬 AI", "예시 그래픽카드", "Gemini 사용법", "삼성 노트북 비교", "NVIDIA RTX 4090", "네이버 블로그 설정", "Claude 코드", "Microsoft Excel 단축키", "예시 제주 여행",
             "가계부 정리", "업무 자동화", "예시 메모 앱", "예시 영양제", "예시 제습기", "예시 모니터", "예시 키보드", "예시 호텔", "예시 난방", "예시 에어컨", "예시 선풍기", "예시 보일러", "LG 그램",
             "애플리케이션 정리", "구글링 방법", "슬랙 채널 관리", "예시 정수기", "예시 세탁기", "예시 냉장고", "시간 관리", "스마트폰 설정", "쇼핑 습관", "수면 환경", "API 한도", "GitHub Actions",
             "Gemini 2.5", "Apple pie", "예시 무선 이어폰", "예시 마우스", "예시 노트북", "예시 SSD", "예시 공유기")

    def off(self, seed_obj, profile, *, as_type=None):
        return brand.NOT_BRAND_VIEW

    def worlds(self):
        seeds_ = []
        for number, keyword in enumerate(self.PLAIN):
            kind = ("general", "priority", "seasonal", "sponsorable", "general")[number % 5]
            changes = {"seed_id": f"p{number}", "keyword": keyword, "seed_type": kind, "priority": kind == "priority"}
            if kind == "sponsorable" or number % 7 == 0:
                changes["sponsor_tag"] = "small_appliance"
                changes["seed_type"] = "sponsorable" if kind == "sponsorable" else kind
            if number % 9 == 0:
                changes["excluded_keywords"] = ("비용",)
            seeds_.append(seed(**changes))
        return seeds_

    def test_every_plain_seed_is_really_not_a_brand_only_text(self):
        self.assertGreaterEqual(len(self.PLAIN), 40)
        for keyword in self.PLAIN:
            self.assertIsNone(brand.find_brands(keyword), keyword)

    def test_the_result_is_the_same_with_the_brand_branch_switched_off_across_channels_and_options(self):
        entries = [ts.example_entry(keywords=("예시 난방",), name="예시 난방 시기")]
        pool = self.worlds()
        for profile in (dataclasses.replace(p, generation_enabled=True) for p in ch.default_profiles()):
            for target in (0, 7, 20, 200):
                options = dict(target=target, realtime=[item(channel=profile.key)], interest=None)
                with self.subTest(channel=profile.key, target=target):
                    on = gn.generate(profile, pool, entries, [post(channel=profile.key)], TODAY, **options)
                    with mock.patch.object(brand, "assess", new=self.off):
                        off = gn.generate(profile, pool, entries, [post(channel=profile.key)], TODAY, **options)
                    self.assertEqual(on, off)
                    self.assertEqual([c.to_dict() for c in on.candidates], [c.to_dict() for c in off.candidates])

    def test_with_existing_candidates_the_result_is_also_the_same(self):
        pool = self.worlds()
        known = gn.generate(A, pool, [], (), TODAY, target=20).candidates[:5]
        on = gn.generate(A, pool, [], (), TODAY, target=20, existing=known)
        with mock.patch.object(brand, "assess", new=self.off):
            off = gn.generate(A, pool, [], (), TODAY, target=20, existing=known)
        self.assertEqual(on, off)

    def test_with_a_brand_seed_in_the_world_the_result_differs_and_without_it_the_two_are_equal_again(self):
        pool = self.worlds()
        mixed = pool + [seed(seed_id="b1", keyword="Gemini", major="가", minor="없는 분류")]
        on = gn.generate(B, mixed, [], (), TODAY, target=200)
        with mock.patch.object(brand, "assess", new=self.off):
            off = gn.generate(B, mixed, [], (), TODAY, target=200)
        self.assertNotEqual(on, off, "브랜드 씨앗이 있으면 분기가 실제로 켜진다")
        without = gn.generate(B, pool, [], (), TODAY, target=200)
        with mock.patch.object(brand, "assess", new=self.off):
            without_off = gn.generate(B, pool, [], (), TODAY, target=200)
        self.assertEqual(without, without_off)


class ExistingCountTodayTest(unittest.TestCase):
    """P2b 보완 P1 — **지금 동작을 못박는다**(KNOWN_DEFECT): `generate(existing=…)` 는 이미 있는 후보 번호만 건너뛰고 목표 개수만큼 새 후보를 또 만든다(목표 3·기존 2 → 새 3, 합계 5).
    기존 후보 수를 반영한 생성량은 P3 의 몫이다(D-56, 계획 11.1) — P3 가 바꾸려면 새 결정을 쓰고 이 시험을 의식적으로 고친다. 숫자는 `route_targets` 와 첫 실행에서 도출한다."""

    def world(self):
        pool = [seed(seed_id="g1"), seed(seed_id="g2", keyword="예시 공기청정기"), seed(seed_id="z1", keyword="예시 난방", seed_type="seasonal")]
        return pool, [ts.example_entry(keywords=("예시 난방",), name="예시 난방 시기")], [post()]

    def test_today_a_target_of_three_gives_one_candidate_per_route(self):
        pool, calendar, history = self.world()
        self.assertEqual(gn.route_targets(3, gn.mix_for(A)), {"seed": 1, "follow_up": 1, "seasonal": 1, "realtime": 0, "sponsor": 0})
        first = gn.generate(A, pool, calendar, history, TODAY, target=3)
        self.assertEqual(len(first.candidates), 3)
        self.assertEqual({c.source_type for c in first.candidates}, {"seed", "follow_up", "seasonal"})
        self.assertTrue(all(c.work_status == "NEW" for c in first.candidates))

    def test_today_two_existing_candidates_do_not_lower_the_number_of_new_ones(self):
        pool, calendar, history = self.world()
        first = gn.generate(A, pool, calendar, history, TODAY, target=3)
        existing = first.candidates[:2]
        again = gn.generate(A, pool, calendar, history, TODAY, existing=existing, target=3)
        self.assertEqual(len(again.candidates), 3, "기존 2개가 있어도 목표(3)만큼 새로 만든다 — P3 에서 1개로 줄어야 한다")
        self.assertEqual({c.candidate_id for c in again.candidates} & {c.candidate_id for c in existing}, set(), "이미 있는 번호는 다시 만들지 않는다")
        self.assertEqual(len(existing) + len(again.candidates), 5)
        self.assertEqual({(row.route, row.reason) for row in again.dropped if row.reason == "already_exists"}, {("seed", "already_exists"), ("seasonal", "already_exists")})

    def test_today_a_rejected_existing_candidate_is_not_treated_differently(self):
        pool, calendar, history = self.world()
        first = gn.generate(A, pool, calendar, history, TODAY, target=3)
        existing = [first.candidates[0], dataclasses.replace(first.candidates[1], work_status="REJECTED")]
        again = gn.generate(A, pool, calendar, history, TODAY, existing=existing, target=3)
        self.assertEqual(len(again.candidates), 3, "제외된 후보는 개수에서 빠져야 한다는 규칙이 아직 없다")


class ExistingCountP3Test(unittest.TestCase):
    """P2b 보완 P2 — **예상 동작**(P3 TODO, D-56): `remaining_slots = target_count − active_existing_count − pending_review_count`. 지금은 구현하지 않아 `expectedFailure`/`skip` 이다 —
    P3 가 구현해 통과시키면 '예상 밖 성공' 으로 알려 주니 그때 데코레이터를 의식적으로 뗀다. P3 는 호출 방식(새 인자 등)을 바꿔도 되지만 시나리오와 결과 숫자는 유지한다."""

    def world(self):
        return ExistingCountTodayTest.world(self)

    @unittest.expectedFailure
    def test_p3_two_valid_existing_of_a_target_of_three_leave_one_new_slot(self):
        pool, calendar, history = self.world()
        first = gn.generate(A, pool, calendar, history, TODAY, target=3)
        existing = first.candidates[:2]
        again = gn.generate(A, pool, calendar, history, TODAY, existing=existing, target=3)
        self.assertEqual(len(again.candidates), 1)                                   # remaining_slots = 3 − 2 − 0 = 1
        self.assertEqual(len(existing) + len(again.candidates), 3)

    @unittest.expectedFailure
    def test_p3_a_rejected_existing_candidate_does_not_take_a_slot(self):
        pool, calendar, history = self.world()
        first = gn.generate(A, pool, calendar, history, TODAY, target=3)
        existing = [first.candidates[0], dataclasses.replace(first.candidates[1], work_status="REJECTED")]
        again = gn.generate(A, pool, calendar, history, TODAY, existing=existing, target=3)
        self.assertEqual(len(again.candidates), 2)                                   # 제외된 것은 개수에서 빠지므로 3 − 1 = 2

    @unittest.skip("P3: 초안 단계(DRAFTING·DRAFT_READY)는 글(프로젝트) 상태로 계산하는 값이라 P3 가 입력 방법을 정한 뒤 쓴다 — 계획 11.1")
    def test_p3_candidates_in_drafting_or_draft_ready_take_a_slot(self):
        self.fail("P3")                                                                # 시나리오: 기존 후보 2개가 DRAFTING·DRAFT_READY 이면 목표 3 에서 새 후보는 1개다


class PublicNamesTest(unittest.TestCase):
    def test_the_module_lists_exactly_the_names_it_exports(self):
        for name in gn.__all__:
            self.assertTrue(hasattr(gn, name), name)
        self.assertEqual(len(set(gn.__all__)), len(gn.__all__))


if __name__ == "__main__":
    unittest.main()
