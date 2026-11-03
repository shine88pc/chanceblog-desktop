"""작성 기반(`content/draft_plan.py` 의 `build_plan`·`compare_plans`) 시험.

지키는 것:
  1) **값 적용 순서**: 사용자 입력 → 블로그 프로필 → 글 유형 틀 → 후보 → 공통 기본값(글 유형만 사용자 → 후보 → 프로필 → 기본값). 층의 모든 부분집합에서 맨 앞의 층이 이기고, 각 값이 어느 층에서 왔는지
     `sources` 에 남는다. 프로필·사용자가 아무것도 정하지 않으면 공통 기본값(정보형·쉬운 존댓말 설명체·처음 접하는 일반 사용자·제목 3개 …)이다. 예: 기본 1,500~2,000자 + 사용자 2,500자 이상 → 2,500자 이상.
  2) 글 길이·소제목 수·제목 길이·태그 수·문단 길이는 프로필 범위를 따르고 경계(하한·상한 그대로)에서 틀리지 않는다. 제외할 말(프로필 제외 주제·사용자 제외할 내용)은 목차·소제목·핵심 내용에서 빠진다.
  3) **안전 대체**: 후기·방문·체험을 전제한 후보는 경험 입력이 없으면 경험담 없이 정보형 안내 글(4가지 대체)로 바뀌고 확인 권장에 그 사실이 적히며 제목·소제목에는 후기·체험 표현이 없다. 경험이 입력되면 경험 단락이
     목차에 더해지고 대체하지 않는다. 방문 정보가 없으면 방문 후기 형식이 없다. 확인 권장이 있어도 계획은 늘 완성이다.
  4) **같은 주제를 두 블로그에서**: 같은 후보로 만든 네이버 A·B 계획은 제목·도입 방향·소제목·설명 방식·예시·마무리·태그가 다르고(문구 풀·묶는 방식·말씨), 너무 비슷하면(`compare_plans`) 경고한다. 같은 입력은 늘 같은
     결과다(무작위 없음 — 해시 시드가 달라도).
  5) **스스로 위반하지 않는다**: 모든 글 유형 × 프로필(A·B·없음) × 경험 입력 유무 × 여러 후보에서 계획의 모든 문장에 '지어내지 않기' 검사를 돌려 위반이 없다(사용자가 입력한 글만 예외).
네트워크·파일 없이 돈다.
"""
import dataclasses
import itertools
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.check import similarity  # noqa: E402
from chanceblog_desktop.content import draft_plan as dp  # noqa: E402
from chanceblog_desktop.content import post_types as pt  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content.candidates import Candidate  # noqa: E402
from chanceblog_desktop.content.draft_options import DraftOptions  # noqa: E402
from chanceblog_desktop.content.profiles import POST_TYPES, NaverProfile  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

TODAY = "2026-11-03"
NOW = "2026-11-02T03:00:00Z"
PRODUCT_EXPERIENCE = "지난달부터 이 제품을 써 왔고 배터리는 하루 종일 갔습니다."
EXPERIENCE = "직접 사용해보니 편리했습니다. 지난주에 방문했고 구매했습니다."

# 네이버 A·B 가 같은 후보로 만든 계획이 서로 다르게 나와야 하는 후보들(글 유형마다 둘 이상)
NEUTRAL = (
    ("겨울 보일러 점검 순서", "보일러 점검", ("보일러 청소", "난방비"), POST_TYPES[0]), ("전기요금 절약 방법", "전기요금", (), POST_TYPES[0]), ("노트북 추천 비교", "노트북 비교", ("가성비 노트북",), POST_TYPES[1]),
    ("무선 청소기 선택 기준", "무선 청소기", ("청소기 추천",), POST_TYPES[1]), ("노트북 전원이 안 켜질 때", "노트북 전원", ("전원 문제",), POST_TYPES[2]), ("세탁기 배수 오류 해결", "세탁기 배수", (), POST_TYPES[2]),
    ("로봇청소기 기능 정리", "로봇청소기", ("스마트 가전",), POST_TYPES[3]), ("구독 서비스 선택 기준", "구독 서비스", ("요금제",), POST_TYPES[3]), ("서울 한강 야경 명소", "한강 야경", ("서울 데이트",), POST_TYPES[4]),
    ("동네 도서관 이용 안내", "동네 도서관", (), POST_TYPES[4]),
)
PREMISE = (
    ("서울 맛집 방문 후기", "맛집 방문 후기", ("서울 맛집",), POST_TYPES[4]), ("노트북 사용 후기", "노트북 사용후기", (), POST_TYPES[3]), ("무선 이어폰 체험단 후기", "이어폰 체험 후기", ("이어폰",), POST_TYPES[3]),
    ("로봇청소기 솔직 후기", "로봇청소기 후기", (), POST_TYPES[0]), ("직접 써본 에어프라이어", "에어프라이어 직접 써본", ("에어프라이어 요리",), POST_TYPES[3]),
)


def make(topic="겨울 보일러 점검 순서", keyword="보일러 점검", subs=("보일러 청소", "난방비"), post_type=POST_TYPES[0], blogs=("naver_a", "naver_b"), **fields):
    return Candidate.new(topic, keyword, blogs, sub_keywords=subs, post_type=post_type, now=NOW, **fields)


def profile(key="naver_a", **changes):
    base = {"naver_a": ("블로그 에이", "https://blog.naver.com/exampleaaa"), "naver_b": ("블로그 비", "https://blog.naver.com/examplebbb")}[key]
    return NaverProfile(key, base[0], base[1], **changes)


def plan_of(candidate=None, prof=None, options=None, **kwargs):
    candidate = candidate or make()
    return dp.build_plan(candidate, prof if prof is not None else profile(), options, today=TODAY, **kwargs)


def sources(plan):
    return dict(plan.sources)


def expect_invalid(test, work, code="DRAFT_OPTION_INVALID"):
    with test.assertRaises(AppError) as caught:
        work()
    test.assertEqual(caught.exception.code, code)
    return caught.exception


class PriorityTest(unittest.TestCase):
    def test_in_every_subset_of_layers_the_first_present_layer_wins(self):
        count = 0
        for size in range(1, len(dp.LAYERS) + 1):
            for chosen in itertools.combinations(dp.LAYERS, size):
                layers = {layer: f"값-{layer}" for layer in chosen}
                expected_layer = next(layer for layer in dp.LAYERS if layer in layers)
                with self.subTest(layers=chosen):
                    self.assertEqual(dp.apply_priority(layers), (f"값-{expected_layer}", expected_layer))
                count += 1
        self.assertEqual(count, 31)

    def test_the_layer_order_is_the_one_in_the_requirement(self):
        self.assertEqual(dp.LAYERS, ("user", "profile", "post_type", "candidate", "default"))
        self.assertEqual(set(dp.LAYER_KO), set(dp.LAYERS))
        self.assertEqual(dp.LAYER_KO["user"], "사용자 입력")

    def test_a_custom_order_is_followed(self):
        layers = {"user": "u", "profile": "p", "candidate": "c", "default": "d"}
        for order in itertools.permutations(("user", "profile", "candidate", "default")):
            with self.subTest(order=order):
                self.assertEqual(dp.apply_priority(layers, order), (layers[order[0]], order[0]))
        self.assertEqual(dp.apply_priority(layers, dp.TYPE_ORDER), ("u", "user"))
        self.assertEqual(dp.apply_priority({"profile": "p", "candidate": "c"}, dp.TYPE_ORDER), ("c", "candidate"))

    def test_blank_values_do_not_count_but_zero_and_false_do(self):
        for blank in ("", None, (), []):
            with self.subTest(blank=blank):
                self.assertEqual(dp.apply_priority({"user": blank, "profile": "값"}), ("값", "profile"))
        self.assertEqual(dp.apply_priority({"user": 0, "profile": 5}), (0, "user"))
        self.assertEqual(dp.apply_priority({"user": False, "profile": True}), (False, "user"))
        self.assertEqual(dp.apply_priority({"user": (1, 2), "profile": (3, 4)}), ((1, 2), "user"))

    def test_nothing_given_is_an_error(self):
        for layers in ({}, {"user": ""}, {"user": None, "default": ()}, {"unknown": "x"}):
            with self.subTest(layers=layers):
                self.assertEqual(expect_invalid(self, lambda layers=layers: dp.apply_priority(layers), "CONTENT_INVALID").code, "CONTENT_INVALID")

    def test_audience_user_then_profile_then_default(self):
        cases = (({}, None, "이 주제를 처음 접하는 일반 사용자", "default"), ({}, "프로필 독자", "프로필 독자", "profile"), ({"audience": "입력 독자"}, None, "입력 독자", "user"),
                 ({"audience": "입력 독자"}, "프로필 독자", "입력 독자", "user"))
        for fields, profile_value, value, layer in cases:
            with self.subTest(fields=fields, profile=profile_value):
                plan = plan_of(prof=profile(audience=profile_value or ""), options=DraftOptions(**fields))
                self.assertEqual((plan.audience, sources(plan)["audience"]), (value, layer))

    def test_audience_has_all_four_layers_user_profile_type_template_and_the_common_default(self):
        for post_type, template in pt.AUDIENCES.items():
            for fields, profile_value, value, layer in (({}, None, template, "post_type"), ({}, "프로필 독자", "프로필 독자", "profile"), ({"audience": "입력 독자"}, None, "입력 독자", "user"),
                                                          ({"audience": "입력 독자"}, "프로필 독자", "입력 독자", "user")):
                with self.subTest(post_type=post_type, layer=layer):
                    plan = plan_of(candidate=make(post_type=post_type), prof=profile(audience=profile_value or ""), options=DraftOptions(**fields))
                    self.assertEqual((plan.audience, sources(plan)["audience"]), (value, layer))
        self.assertNotIn("정보형", pt.AUDIENCES)
        info = plan_of(candidate=make(post_type="정보형"))
        self.assertEqual((info.audience, sources(info)["audience"]), ("이 주제를 처음 접하는 일반 사용자", "default"))
        self.assertEqual(len(set(pt.AUDIENCES.values())), 4)

    def test_tone_is_the_profile_tone_or_the_default_and_the_direction_says_so(self):
        plan = plan_of(prof=profile())
        self.assertEqual((sources(plan)["tone"], dict(plan.direction)["문체"]), ("default", "쉬운 존댓말 설명체로 씁니다"))
        plan = plan_of(prof=profile(tone="친근한 해요체"))
        self.assertEqual(sources(plan)["tone"], "profile")
        self.assertIn("친근한 해요체", dict(plan.direction)["문체"])
        self.assertNotIn("쉬운 존댓말 설명체", dict(plan.direction)["문체"])

    def test_length_user_wish_overrides_the_profile_and_the_default(self):
        default_plan = plan_of(prof=profile())
        self.assertEqual((default_plan.length, sources(default_plan)["length"]), ((1500, 2000), "default"))
        overridden = plan_of(prof=profile(), options=DraftOptions(length="2500+"))
        self.assertEqual((overridden.length, sources(overridden)["length"]), ((2500, None), "user"))
        self.assertEqual(dict(overridden.direction)["글 길이"], "2,500자 이상을 목표로 합니다")      # 문장 전체 — 조사('이상를')까지 본다
        ranged = plan_of(prof=profile(min_chars=1000, max_chars=3000), options=DraftOptions(length="1800-2200"))
        self.assertEqual((ranged.length, sources(ranged)["length"]), ((1800, 2200), "user"))
        from_profile = plan_of(prof=profile(min_chars=1000, max_chars=3000))
        self.assertEqual((from_profile.length, sources(from_profile)["length"]), ((1000, 3000), "profile"))

    def test_a_profile_length_that_is_the_class_default_counts_as_not_set(self):
        defaults = NaverProfile("naver_a", "에이", "https://blog.naver.com/exampleaaa")
        plan = plan_of(prof=defaults)
        self.assertEqual((plan.length, sources(plan)["length"]), ((1500, 2000), "default"))
        for changed in ({"min_chars": 801}, {"max_chars": 5999}, {"min_chars": 0}, {"max_chars": 6001}):
            with self.subTest(changed=changed):
                plan = plan_of(prof=profile(**changed))
                self.assertEqual(sources(plan)["length"], "profile")
                self.assertEqual(plan.length, (changed.get("min_chars", 800), changed.get("max_chars", 6000)))

    def test_a_user_length_outside_the_profile_range_is_followed_with_a_note(self):
        plan = plan_of(prof=profile(min_chars=800, max_chars=3000), options=DraftOptions(length="3500+"))
        self.assertEqual(plan.length, (3500, None))
        self.assertTrue([text for text in plan.checks if "프로필의 글 길이 기준" in text])
        inside = plan_of(prof=profile(min_chars=800, max_chars=3000), options=DraftOptions(length="1000-2000"))
        self.assertFalse([text for text in inside.checks if "프로필의 글 길이 기준" in text])
        edge = plan_of(prof=profile(min_chars=800, max_chars=3000), options=DraftOptions(length="800-3000"))
        self.assertFalse([text for text in edge.checks if "프로필의 글 길이 기준" in text])
        for wish in ("799-1000", "2000-3001", "3001+"):
            with self.subTest(wish=wish):
                self.assertTrue([text for text in plan_of(prof=profile(min_chars=800, max_chars=3000), options=DraftOptions(length=wish)).checks if "프로필의 글 길이 기준" in text])

    def test_counts_come_from_the_profile_or_the_defaults(self):
        for prof, layer, subheadings in ((profile(), "default", (3, 5)), (profile(subheading_min=2, subheading_max=4, max_title_chars=30, max_tags=6, paragraph_max_chars=120), "profile", (2, 4)), (None, "default", (3, 5))):
            with self.subTest(layer=layer, profile=prof):
                plan = dp.build_plan(make(blogs=("github_pages",)), prof, today=TODAY, blog="naver_a" if prof is not None else "github_pages")
                for item in ("subheadings", "title_limit", "tag_limit", "paragraph"):
                    self.assertEqual(sources(plan)[item], layer, item)
                self.assertTrue(subheadings[0] <= len(plan.subheadings) <= subheadings[1])
        small = plan_of(prof=profile(paragraph_max_chars=120))
        self.assertIn("120자", dict(small.direction)["문단"])
        self.assertEqual({item: sources(small)[item] for item in ("subheadings", "title_limit", "tag_limit", "paragraph")}, {"subheadings": "default", "title_limit": "default", "tag_limit": "default", "paragraph": "profile"})
        partly = plan_of(prof=profile(subheading_min=2, subheading_max=4))
        self.assertEqual({item: sources(partly)[item] for item in ("subheadings", "title_limit", "tag_limit", "paragraph")}, {"subheadings": "profile", "title_limit": "default", "tag_limit": "default", "paragraph": "default"})
        self.assertIn("180자", dict(dp.build_plan(make(blogs=("github_pages",)), None, today=TODAY).direction)["문단"])

    def test_style_fields_use_the_profile_text_when_it_is_understood_else_the_voice_default(self):
        plan = plan_of(prof=profile(intro_style="독자의 고민으로 시작", difficulty="전문가 수준으로 자세히", ending_style="체크리스트로 마무리"))
        self.assertEqual({item: sources(plan)[item] for item in ("intro_style", "difficulty", "ending_style")}, {"intro_style": "profile", "difficulty": "profile", "ending_style": "profile"})
        direction = dict(plan.direction)
        self.assertEqual(direction["도입부"], dp.INTRO_LINES["problem"][0])
        self.assertEqual(direction["설명 방식"], dp.DIFFICULTY_LINES["expert"][0])
        self.assertEqual(direction["마무리"], dp.ENDING_LINES["checklist"][0])
        unknown = plan_of(prof=profile(intro_style="톡톡 튀게", difficulty="그냥 알아서", ending_style="마음 가는 대로"))
        self.assertEqual({item: sources(unknown)[item] for item in ("intro_style", "difficulty", "ending_style")}, {"intro_style": "default", "difficulty": "default", "ending_style": "default"})
        direction = dict(unknown.direction)
        for label, text in (("도입부", "톡톡 튀게"), ("설명 방식", "그냥 알아서"), ("마무리", "마음 가는 대로")):
            self.assertIn(text, direction[label], "프로필의 안내 글을 버리지 않고 덧붙인다")
        plain = dict(plan_of(prof=profile()).direction)
        self.assertEqual(plain["도입부"], dp.INTRO_LINES["problem"][0])

    def test_style_words_are_read_by_rules(self):
        for text, style in (("독자의 고민으로 시작", "problem"), ("질문으로 시작", "problem"), ("결론부터 먼저", "purpose"), ("핵심 요약으로 시작", "purpose"), ("배경 설명으로 시작", "context"), ("계절 이야기로 시작", "context"), ("", None),
                            ("아무 말", None), ("  ", None)):
            with self.subTest(text=text):
                self.assertEqual(dp.style_of(text, dp.INTRO_STYLES), style)
        for text, style in (("쉬운 설명", "beginner"), ("초보자 눈높이", "beginner"), ("실무 중심", "practical"), ("전문적으로", "expert"), ("자세히", "expert")):
            with self.subTest(text=text):
                self.assertEqual(dp.style_of(text, dp.DIFFICULTY_STYLES), style)
        for text, style in (("핵심 요약", "summary"), ("체크리스트", "checklist"), ("다음 글 예고", "next")):
            with self.subTest(text=text):
                self.assertEqual(dp.style_of(text, dp.ENDING_STYLES), style)

    def test_post_type_user_then_candidate_then_profile_then_default_in_every_combination(self):
        options = (None, "정보형", "비교형", "문제 해결형")
        for user, candidate_type, profile_type in itertools.product(options, options, options):
            expected_type, expected_layer = pt.resolve_post_type(user, candidate_type, profile_type)
            with self.subTest(user=user, candidate=candidate_type, profile=profile_type):
                plan = dp.build_plan(make(topic="난방 방법", keyword="난방", post_type=candidate_type or "정보형"), profile(post_type=profile_type or "정보형"), today=TODAY, post_type=user)
                self.assertEqual((plan.post_type, sources(plan)["post_type"]), (expected_type, expected_layer))

    def test_category_comes_from_the_profile_mapping_or_stays_empty(self):
        plan = plan_of(candidate=make(topic="생활 팁", keyword="난방 팁", subs=()), prof=profile(categories=(("재테크", "경제"), ("생활", "생활정보"))))
        self.assertEqual((plan.category, sources(plan)["category"]), ("생활정보", "profile"))
        by_target = plan_of(candidate=make(topic="경제 이야기", keyword="물가", subs=()), prof=profile(categories=(("재테크", "경제"), ("생활", "생활정보"))))
        self.assertEqual(by_target.category, "경제")
        single = plan_of(candidate=make(topic="아무 주제", keyword="아무", subs=()), prof=profile(categories=(("재테크", "경제"),)))
        self.assertEqual((single.category, sources(single)["category"]), ("경제", "profile"))
        none = plan_of(candidate=make(topic="아무 주제", keyword="아무", subs=()), prof=profile(categories=(("재테크", "경제"), ("생활", "생활정보"))))
        self.assertEqual((none.category, sources(none)["category"]), ("", "default"))
        self.assertTrue([text for text in none.checks if "카테고리" in text])
        empty = plan_of(prof=profile())
        self.assertEqual((empty.category, sources(empty)["category"]), ("", "default"))
        self.assertFalse([text for text in empty.checks if "카테고리" in text])

    def test_every_item_has_a_recorded_source_from_a_known_layer(self):
        plan = plan_of(prof=profile(tone="친근한 해요체"), options=DraftOptions(title_direction="질문형", conclusion="결론", audience="직장인", length="1500-1800"))
        found = sources(plan)
        expected = {"post_type", "audience", "tone", "length", "subheadings", "title_limit", "tag_limit", "paragraph", "intro_style", "difficulty", "ending_style", "category", "tags", "title_direction", "conclusion",
                    "intent", "outline", "titles", "cautions", "topic", "keyword", "sub_keywords"}
        self.assertEqual(set(found), expected)
        self.assertTrue(set(found.values()) <= set(dp.LAYERS))
        self.assertEqual({found[item] for item in ("intent", "outline", "titles", "cautions")}, {"post_type"})
        self.assertEqual({found[item] for item in ("topic", "keyword", "sub_keywords")}, {"candidate"})
        self.assertEqual(set(found.values()), set(dp.LAYERS), "다섯 층이 모두 나온다")
        self.assertEqual((found["title_direction"], found["conclusion"], found["audience"], found["length"]), ("user", "user", "user", "user"))
        self.assertEqual(plan.source_of("audience"), "user")
        self.assertIsNone(plan.source_of("없는 항목"))
        bare = sources(plan_of())
        self.assertNotIn("title_direction", bare)
        self.assertNotIn("conclusion", bare)


class DefaultsTest(unittest.TestCase):
    def test_nothing_but_a_candidate_gives_a_complete_plan_from_the_common_defaults(self):
        candidate = make(blogs=("github_pages",))
        plan = dp.build_plan(candidate, None, today=TODAY)
        self.assertTrue(plan.complete)
        self.assertEqual((plan.blog, plan.post_type, plan.audience, plan.length, plan.base_date), ("github_pages", "정보형", "이 주제를 처음 접하는 일반 사용자", (1500, 2000), TODAY))
        self.assertEqual(dict(plan.direction)["문체"], "쉬운 존댓말 설명체로 씁니다")
        self.assertEqual(len(plan.titles), 3)
        self.assertEqual(len(set(plan.titles)), 3)
        self.assertEqual(plan.references, ())
        self.assertEqual(plan.category, "")
        self.assertTrue(all(layer == "default" for item, layer in plan.sources if item in ("audience", "tone", "length", "subheadings", "title_limit", "tag_limit", "paragraph", "post_type", "difficulty", "ending_style")))
        self.assertEqual(plan.topic, "겨울 보일러 점검 순서")
        self.assertEqual((plan.keyword, plan.sub_keywords), ("보일러 점검", ("보일러 청소", "난방비")))

    def test_the_default_structure_is_the_information_flow(self):
        plan = dp.build_plan(make(blogs=("github_pages",)), None, today=TODAY)
        self.assertEqual(plan.outline, ("독자가 궁금해하는 문제", "핵심 개념", "확인할 기준 + 활용 방법", "주의사항", "핵심 정리"))
        self.assertEqual(len(plan.subheadings), 5)

    def test_every_candidate_status_and_metric_set_still_gives_a_plan(self):
        for status_fields in ({}, {"search_demand": 1200, "trend": "상승", "data_date": "2026-11-01", "seasonality": (11, 12, 1), "duplicate": False}):
            with self.subTest(fields=status_fields):
                plan = plan_of(candidate=make(**status_fields))
                self.assertTrue(plan.complete)

    def test_seasonality_adds_a_neutral_timing_point_and_stale_data_adds_a_note(self):
        plan = plan_of(candidate=make(seasonality=(11, 12, 1), data_date="2026-11-01", search_demand=100))
        self.assertTrue([text for text in plan.key_points if "관심이 몰리는 달(1·11·12월)" in text])
        self.assertFalse([text for text in plan.checks if "조회일" in text])
        stale = plan_of(candidate=make(data_date="2026-09-01", search_demand=100))
        self.assertTrue([text for text in stale.checks if "조회일(2026-09-01)이 63일 전" in text])
        edge = plan_of(candidate=make(data_date="2026-10-04", search_demand=100))                     # 오늘(11-03)보다 30일 전 — 경계는 확인 권장이 아니다
        self.assertFalse([text for text in edge.checks if "조회일" in text])
        edge = plan_of(candidate=make(data_date="2026-10-03", search_demand=100))                     # 31일 전
        self.assertTrue([text for text in edge.checks if "31일 전" in text])
        duplicated = plan_of(candidate=make(duplicate=True, search_demand=100, data_date="2026-11-01"))
        self.assertTrue([text for text in duplicated.checks if "겹칠 수 있음" in text])
        self.assertFalse([text for text in plan_of(candidate=make(duplicate=False, search_demand=100, data_date="2026-11-01")).checks if "겹칠 수 있음" in text])

    def test_a_missing_naver_profile_is_a_note_and_not_a_stop(self):
        plan = dp.build_plan(make(), None, today=TODAY, blog="naver_a")
        self.assertTrue(plan.complete)
        self.assertTrue([text for text in plan.checks if "프로필이 아직 없어" in text])
        github = dp.build_plan(make(blogs=("github_pages",)), None, today=TODAY)
        self.assertFalse([text for text in github.checks if "프로필이 아직 없어" in text])

    def test_the_english_blogger_gets_a_note_about_the_korean_title_templates(self):
        plan = dp.build_plan(make(blogs=("blogger_en",)), None, today=TODAY)
        self.assertTrue([text for text in plan.checks if "영문 블로그용 제목 틀" in text])
        self.assertFalse([text for text in dp.build_plan(make(blogs=("blogger_ko",)), None, today=TODAY).checks if "영문 블로그용" in text])

    def test_the_blog_defaults_to_the_profile_then_the_first_recommended_blog(self):
        self.assertEqual(dp.build_plan(make(blogs=("naver_b", "naver_a")), None, today=TODAY).blog, "naver_b")
        self.assertEqual(dp.build_plan(make(blogs=("naver_b", "naver_a")), profile("naver_a"), today=TODAY).blog, "naver_a")
        self.assertEqual(dp.build_plan(make(blogs=("naver_b", "naver_a")), None, today=TODAY, blog="naver_a").blog, "naver_a")


class StructureBoundaryTest(unittest.TestCase):
    def expected_count(self, voice, experience, low, high, steps=6):
        available = steps + (1 if experience else 0) + (1 if voice == 1 else 0)               # 말씨 1 은 '핵심부터' 도입이라 맨 앞 단락이 하나 더 있다
        wanted = min(max(available, low), high)
        return min(wanted, available + len(pt.EXTRA_STEPS))

    def test_the_number_of_subheadings_stays_inside_the_profile_range_for_every_range(self):
        checked = 0
        for key, experience in itertools.product(("naver_a", "naver_b"), (False, True)):
            for low in range(1, 13):
                for high in range(low, 13):
                    with self.subTest(key=key, experience=experience, low=low, high=high):
                        options = DraftOptions(experience=PRODUCT_EXPERIENCE) if experience else None
                        plan = plan_of(prof=profile(key, subheading_min=low, subheading_max=high), options=options)
                        expected = self.expected_count(pt.VOICE[key], experience, low, high)
                        self.assertEqual((len(plan.outline), len(plan.subheadings)), (expected, expected))
                        if expected < low:
                            self.assertTrue([text for text in plan.checks if "소제목을" in text and "적습니다" in text])
                        else:
                            self.assertTrue(low <= expected <= high)
                            self.assertFalse([text for text in plan.checks if "소제목을" in text and "적습니다" in text])
                    checked += 1
        self.assertGreater(checked, 300)

    def test_grouping_keeps_every_step_once_and_in_order(self):
        for key in ("naver_a", "naver_b"):
            for low, high in ((1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (1, 3), (3, 5)):
                with self.subTest(key=key, low=low, high=high):
                    plan = plan_of(prof=profile(key, subheading_min=low, subheading_max=high))
                    names = [name for group in plan.outline for name in group.split(" + ")]
                    full = [step.name for step in pt.template_steps("정보형")]
                    if pt.VOICE[key] == 1:
                        full = [pt.LEAD_STEP.name, *full]
                    extras = [step.name for step in pt.EXTRA_STEPS]
                    self.assertEqual([name for name in names if name not in extras], full)
                    self.assertEqual(len(names), len(set(names)))

    def test_group_sizes_split_evenly_with_the_extra_in_the_middle_or_at_the_end(self):
        self.assertEqual(dp.group_sizes(6, 5, 0), [1, 1, 2, 1, 1])
        self.assertEqual(dp.group_sizes(6, 5, 1), [1, 1, 1, 1, 2])
        self.assertEqual(dp.group_sizes(6, 4, 0), [1, 2, 2, 1])
        self.assertEqual(dp.group_sizes(6, 4, 1), [1, 1, 2, 2])
        self.assertEqual(dp.group_sizes(7, 5, 0), [1, 2, 2, 1, 1])
        self.assertEqual(dp.group_sizes(7, 5, 1), [1, 1, 1, 2, 2])
        self.assertEqual(dp.group_sizes(6, 6, 0), [1] * 6)
        self.assertEqual(dp.group_sizes(6, 1, 1), [6])
        self.assertEqual(dp.group_sizes(6, 3, 0), [2, 2, 2])
        for count, groups, voice in itertools.product(range(1, 13), range(1, 13), (0, 1)):
            if groups <= count:
                sizes = dp.group_sizes(count, groups, voice)
                self.assertEqual((sum(sizes), len(sizes), max(sizes) - min(sizes) <= 1), (count, groups, True))

    def test_padding_adds_the_neutral_extra_steps_before_the_closing_step(self):
        plan = plan_of(prof=profile("naver_a", subheading_min=8, subheading_max=9))
        self.assertEqual(plan.outline[-1], "핵심 정리")
        self.assertEqual(plan.outline[-3:-1], ("자주 묻는 질문", "용어 풀이"))
        self.assertEqual(len(plan.outline), 8)

    def test_a_title_limit_is_respected_exactly_and_three_distinct_titles_always_exist(self):
        for key in ("naver_a", "naver_b"):
            for limit in range(8, 81):
                with self.subTest(key=key, limit=limit):
                    plan = plan_of(candidate=make(topic="겨울철 난방비를 줄이는 보일러 점검 순서와 방법", keyword="보일러 점검"), prof=profile(key, max_title_chars=limit))
                    self.assertEqual(len(plan.titles), 3)
                    self.assertEqual(len({title.casefold() for title in plan.titles}), 3)
                    self.assertTrue(all(0 < len(title) <= limit for title in plan.titles), plan.titles)

    def test_an_extremely_short_title_limit_is_lifted_with_a_note(self):
        for limit in (1, 2, 5, 7):
            with self.subTest(limit=limit):
                plan = plan_of(prof=profile(max_title_chars=limit))
                self.assertEqual(len(plan.titles), 3)
                self.assertTrue(all(len(title) <= 8 for title in plan.titles))
                self.assertTrue([text for text in plan.checks if "제목 길이 상한" in text])
        self.assertFalse([text for text in plan_of(prof=profile(max_title_chars=8)).checks if "제목 길이 상한" in text])
        self.assertTrue([text for text in plan_of(prof=profile(max_title_chars=7)).checks if "제목 길이 상한(7자)" in text])
        self.assertEqual(dp.MIN_TITLE_LIMIT, 8)

    def test_a_title_exactly_as_long_as_the_limit_is_allowed_and_one_character_more_is_not(self):
        for limit in (10, 20, 33, 59):
            with self.subTest(limit=limit):
                keyword = "가나다라마바사아자차카타파하"[:limit] if limit <= 14 else "가" * limit
                plan = plan_of(candidate=make(topic=keyword, keyword=keyword, subs=()), prof=profile(max_title_chars=limit))
                self.assertIn(keyword, plan.titles, "키워드 자체가 상한과 같은 길이면 제목으로 쓴다")
                longer = keyword + "가"
                self.assertNotIn(longer, plan_of(candidate=make(topic=longer, keyword=longer, subs=()), prof=profile(max_title_chars=limit)).titles)
        pattern = "{kw}, 처음이라면 알아둘 기준"
        rest = len(pattern.replace("{kw}", ""))
        exact = "가" * (60 - rest)
        titles = dp.build_plan(make(topic=exact, keyword=exact, subs=(), blogs=("github_pages",)), None, today=TODAY).titles
        self.assertIn(pattern.replace("{kw}", exact), titles, "공통 기본값의 제목 상한은 60자")
        longer = exact + "가"
        self.assertNotIn(pattern.replace("{kw}", longer), dp.build_plan(make(topic=longer, keyword=longer, subs=(), blogs=("github_pages",)), None, today=TODAY).titles)

    def test_long_keywords_and_short_ones_still_make_three_titles(self):
        for keyword in ("가", "가나", "보일러", "아주 길고 길고 또 길어서 제목 길이 상한을 훨씬 넘어 버리는 핵심 키워드 문장입니다 정말로 깁니다 아주 깁니다"[:60]):
            for limit in (8, 10, 20, 60):
                with self.subTest(keyword=keyword, limit=limit):
                    plan = plan_of(candidate=make(topic=keyword, keyword=keyword, subs=()), prof=profile(max_title_chars=limit))
                    self.assertEqual(len(plan.titles), 3)
                    self.assertEqual(len(set(plan.titles)), 3)
                    self.assertTrue(all(len(title) <= limit for title in plan.titles))

    def test_the_tag_count_is_capped_at_the_profile_limit(self):
        candidate = make(subs=tuple(f"보조{index}" for index in range(8)))
        for limit in range(1, 31):
            with self.subTest(limit=limit):
                plan = plan_of(candidate=candidate, prof=profile(max_tags=limit, default_tags=("생활", "정보", "팁")))
                self.assertLessEqual(len(plan.tags), limit)
                self.assertEqual(plan.tags[0], "보일러점검")
                self.assertEqual(len(plan.tags), len({tag.casefold() for tag in plan.tags}))
        self.assertEqual(len(plan_of(candidate=candidate, prof=profile(max_tags=1)).tags), 1)
        self.assertEqual(len(plan_of(candidate=candidate, prof=profile(max_tags=30, default_tags=("생활", "정보", "팁"))).tags), 8 + 1 + 3 + 2)

    def test_without_a_profile_the_tag_limit_is_ten(self):
        candidate = make(subs=tuple(f"보조{index}" for index in range(12)), blogs=("github_pages",))
        plan = dp.build_plan(candidate, None, today=TODAY)
        self.assertEqual(len(plan.tags), 10)
        self.assertEqual(sources(plan)["tag_limit"], "default")
        self.assertEqual(len(dp.build_plan(candidate, profile(max_tags=11), today=TODAY, blog="naver_a").tags), 11)

    def test_tags_are_clean_unique_words_that_start_with_the_keyword_tag(self):
        plan = plan_of(candidate=make(keyword="보일러 점검", subs=("난방비 #절약", "보일러 청소", "난방비절약")), prof=profile(default_tags=("생활", "난방비절약")))
        for tag in plan.tags:
            self.assertFalse(any(ch.isspace() or ch == "#" for ch in tag), tag)
            self.assertLessEqual(len(tag), 30)
        self.assertEqual(plan.tags[0], "보일러점검")
        self.assertEqual(len(plan.tags), len(set(plan.tags)))

    def test_the_default_tags_of_the_profile_are_included(self):
        self.assertIn("생활", plan_of(prof=profile(default_tags=("생활",))).tags)
        self.assertEqual(sources(plan_of(prof=profile(default_tags=("생활",))))["tags"], "profile")
        self.assertEqual(sources(plan_of(prof=profile()))["tags"], "candidate")

    def test_today_must_be_a_real_calendar_date(self):
        for bad in ("", "2026-13-01", "2026-02-30", "26-11-03", "2026/11/03", "2026-11-3", None, 20261103, "내일"):
            with self.subTest(today=bad):
                expect_invalid(self, lambda bad=bad: dp.build_plan(make(), profile(), today=bad))
        self.assertEqual(dp.build_plan(make(), profile(), today="2024-02-29").base_date, "2024-02-29")


class SafeReplacementTest(unittest.TestCase):
    CASES = (
        ("방문 후기", "위치·이용 정보와 방문 전 확인사항", "장소·업체 정보형", make("서울 맛집 방문 후기", "맛집 방문 후기", ("서울 맛집",), POST_TYPES[4])),
        ("제품 체험 후기", "공개된 제품 정보와 구매 전 확인사항", "제품·서비스 소개형", make("무선 이어폰 체험단 후기", "이어폰 체험 후기", ("이어폰",), POST_TYPES[3])),
        ("직접 사용 후기", "기능과 선택 기준 정리", "제품·서비스 소개형", make("노트북 사용 후기", "노트북 사용후기", (), POST_TYPES[3])),
        ("경험형 후기", "정보형 안내 글", "정보형", make("보일러 교체 후기", "보일러 후기", (), POST_TYPES[0])),
    )
    PREMISE_WORDS = ("후기", "체험", "리뷰", "사용기", "방문기", "내돈내산", "직접", "솔직")

    def test_each_experience_form_becomes_its_information_guide_when_nothing_was_experienced(self):
        for label_from, label_to, post_type, candidate in self.CASES:
            for key in ("naver_a", "naver_b"):
                with self.subTest(form=label_from, blog=key):
                    plan = plan_of(candidate=candidate, prof=profile(key))
                    self.assertEqual(plan.replaced, (label_from, label_to))
                    self.assertEqual(plan.post_type, post_type)
                    notes = [text for text in plan.checks if label_from in text and label_to in text]
                    self.assertEqual(len(notes), 1, plan.checks)
                    self.assertIn("경험담 없이", notes[0])
                    self.assertTrue(plan.complete)

    def test_titles_headings_and_tags_do_not_carry_review_or_experience_words(self):
        for label_from, _label_to, _post_type, candidate in self.CASES:
            for key in ("naver_a", "naver_b"):
                with self.subTest(form=label_from, blog=key):
                    plan = plan_of(candidate=candidate, prof=profile(key))
                    text = " ".join((*plan.titles, *plan.subheadings, *plan.tags, plan.topic, plan.keyword))
                    for word in self.PREMISE_WORDS:
                        self.assertNotIn(word, text, f"{word} 가 제목·소제목·태그에 남았다")

    def test_with_the_users_experience_nothing_is_replaced_and_the_experience_paragraph_is_added(self):
        for label_from, _label_to, post_type, candidate in self.CASES:
            with self.subTest(form=label_from):
                plan = plan_of(candidate=candidate, options=DraftOptions(experience=EXPERIENCE))
                self.assertIsNone(plan.replaced)
                self.assertFalse([text for text in plan.checks if "바꿔 만들었습니다" in text])
                self.assertTrue([text for text in plan.key_points if text.startswith("실제 경험(입력): ")])
                self.assertTrue(any(name in " ".join(plan.outline) for name in ("경험 이야기", "사용 경험", "방문 경험")))
                self.assertEqual(plan.post_type, candidate.post_type)

    def test_a_type_the_user_chose_is_kept_and_only_the_review_form_is_dropped(self):
        for _label_from, _label_to, _post_type, candidate in self.CASES[:3]:
            plan = plan_of(candidate=candidate, post_type="비교형")
            self.assertEqual((plan.post_type, sources(plan)["post_type"]), ("비교형", "user"))
            self.assertIsNotNone(plan.replaced)
            self.assertIn("비교형 안내 글", plan.replaced[1])

    def test_a_general_review_keeps_the_resolved_type_instead_of_forcing_the_information_type(self):
        candidate = make("로봇청소기 솔직 후기", "로봇청소기 후기", (), POST_TYPES[1])
        plan = plan_of(candidate=candidate)
        self.assertEqual((plan.post_type, plan.replaced), ("비교형", ("경험형 후기", "비교형 안내 글")))

    def test_a_place_without_visit_information_is_not_a_visit_review_and_says_so(self):
        candidate = make("동네 도서관 이용 안내", "동네 도서관", (), POST_TYPES[4])
        plan = plan_of(candidate=candidate)
        self.assertNotIn("방문 경험", " ".join(plan.outline))
        self.assertTrue([text for text in plan.checks if "실제 방문 정보가 입력되지 않아 방문 후기 형식 없이" in text])
        with_visit = plan_of(candidate=candidate, options=DraftOptions(experience="지난 주말에 갔고 열람실이 조용했습니다."))
        self.assertIn("방문 경험", " ".join(with_visit.outline))
        self.assertFalse([text for text in with_visit.checks if "방문 후기 형식 없이" in text])

    def test_a_product_without_experience_notes_that_an_experience_paragraph_can_be_added(self):
        candidate = make("로봇청소기 기능 정리", "로봇청소기", (), POST_TYPES[3])
        plan = plan_of(candidate=candidate)
        self.assertTrue([text for text in plan.checks if "사용 경험 단락이 목차에 더해집니다" in text])
        self.assertNotIn("사용 경험", " ".join(plan.outline))
        with_use = plan_of(candidate=candidate, options=DraftOptions(experience=PRODUCT_EXPERIENCE))
        self.assertIn("사용 경험", " ".join(with_use.outline))
        self.assertFalse([text for text in with_use.checks if "사용 경험 단락이 목차에 더해집니다" in text])

    def test_other_types_get_the_general_experience_note_and_the_experience_paragraph_when_given(self):
        for post_type in (POST_TYPES[0], POST_TYPES[1], POST_TYPES[2]):
            with self.subTest(post_type=post_type):
                plan = plan_of(candidate=make(post_type=post_type))
                self.assertTrue([text for text in plan.checks if "경험이 있으면" in text])
                self.assertNotIn("경험 이야기", " ".join(plan.outline))
                self.assertIn("경험 이야기", " ".join(plan_of(candidate=make(post_type=post_type), options=DraftOptions(experience=EXPERIENCE)).outline))

    def test_the_experience_is_put_in_the_key_points_verbatim_and_nothing_is_invented(self):
        plan = plan_of(options=DraftOptions(experience=EXPERIENCE))
        self.assertIn(f"실제 경험(입력): {EXPERIENCE}", plan.key_points)
        self.assertEqual([point for point in plan.key_points if point.startswith("실제 경험(입력)")], [f"실제 경험(입력): {EXPERIENCE}"])

    def test_a_claim_in_the_candidates_own_words_is_never_copied_into_titles(self):
        candidate = make("직접 써보니 편했어요 로봇청소기", "직접 써보니 편했어요 청소기", ("직접 다녀와서 편한 곳", "청소기"), POST_TYPES[3])
        for key in ("naver_a", "naver_b"):
            plan = plan_of(candidate=candidate, prof=profile(key))
            self.assertEqual(claims.find_violations(plan.texts()), (), plan.texts())
            self.assertNotIn("청소기 직접", " ".join(plan.titles))
            self.assertEqual(plan.keyword, dp.GENERIC_SUBJECT)
            self.assertTrue([text for text in plan.checks if "경험을 단정하는 표현" in text])
            self.assertNotIn("직접 다녀와서", " ".join(plan.sub_keywords))


class ExclusionTest(unittest.TestCase):
    def test_user_exclusions_remove_steps_headings_and_points_that_contain_them(self):
        full = plan_of(prof=profile(subheading_min=1, subheading_max=12))
        trimmed = plan_of(prof=profile(subheading_min=1, subheading_max=12), options=DraftOptions(exclude=("주의", "기준")))
        self.assertIn("주의사항", " ".join(full.outline))
        self.assertIn("확인할 기준", " ".join(full.outline))
        self.assertNotIn("주의", " ".join(trimmed.outline))
        self.assertNotIn("기준", " ".join(trimmed.outline))
        self.assertEqual(len(trimmed.outline), len(full.outline) - 2)
        self.assertEqual(len(trimmed.subheadings), len(trimmed.outline))
        for text in (*trimmed.subheadings, *trimmed.key_points):
            if "(입력" not in text:
                self.assertNotIn("주의", text)
                self.assertNotIn("기준", text.replace("핵심 키워드", ""))
        self.assertTrue([text for text in trimmed.checks if "제외할 내용에 걸려 목차에서 뺀 단계" in text and "주의사항" in text])

    def test_a_phrase_with_an_excluded_word_falls_back_to_the_other_voices_phrase_or_is_left_out(self):
        wide = dict(subheading_min=6, subheading_max=6)                            # 단계를 묶지 않아 단계마다 소제목이 하나다
        base = plan_of(prof=profile("naver_a", **wide))
        self.assertTrue([point for point in base.key_points if "쉬운 말로 풀어 쓰고" in point])
        one = plan_of(prof=profile("naver_a", **wide), options=DraftOptions(exclude=("쉬운 말",)))
        self.assertFalse([point for point in one.key_points if "쉬운 말" in point])
        self.assertTrue([point for point in one.key_points if "개념은 정의 한 줄과 쉬운 설명 한 줄" in point], "다른 말씨의 문구로 바꿔 쓴다")
        both = plan_of(prof=profile("naver_a", **wide), options=DraftOptions(exclude=("쉬운",)))
        self.assertFalse([point for point in both.key_points if "쉬운" in point], "두 문구가 모두 걸리면 그 핵심 내용은 뺀다")
        self.assertIn("핵심 개념", both.outline)
        self.assertEqual(len(both.key_points), len(base.key_points) - 1)

    def test_a_heading_with_an_excluded_word_falls_back_to_the_other_voices_heading_then_to_the_step_name(self):
        wide = dict(subheading_min=6, subheading_max=6)
        index = 2
        base = plan_of(prof=profile("naver_a", **wide))
        self.assertEqual((base.outline[index], base.subheadings[index]), ("확인할 기준", "보일러 점검, 이것부터 확인하세요"))
        other = plan_of(prof=profile("naver_a", **wide), options=DraftOptions(exclude=("이것부터",)))
        self.assertEqual(other.subheadings[index], "확인할 기준 정리: 보일러 점검")
        step_name = plan_of(prof=profile("naver_a", **wide), options=DraftOptions(exclude=("이것부터", "기준 정리")))
        self.assertEqual((step_name.outline[index], step_name.subheadings[index]), ("확인할 기준", "확인할 기준"))

    def test_the_profile_excluded_topics_work_the_same_way(self):
        plan = plan_of(prof=profile(excluded_topics=("활용",), subheading_min=1, subheading_max=12))
        self.assertNotIn("활용", " ".join(plan.outline))
        self.assertNotIn("활용", " ".join(plan.subheadings))

    def test_matching_ignores_spacing_case_and_width(self):
        for term in ("확인할 기준", "확인할기준", "ＡＢＣ확인할기준"[3:], "  확인할   기준 "):
            with self.subTest(term=term):
                plan = plan_of(prof=profile(subheading_min=1, subheading_max=12), options=DraftOptions(exclude=(term,)))
                self.assertNotIn("확인할 기준", " ".join(plan.outline))
        plan = plan_of(candidate=make(topic="AI 도구 소개", keyword="AI 도구", subs=()), prof=profile(excluded_topics=("ＡＩ",)))
        self.assertTrue([text for text in plan.checks if "제외 주제" in text])

    def test_excluding_everything_still_leaves_the_first_step(self):
        terms = ("독자", "개념", "기준", "활용", "주의", "정리", "핵심", "방법", "문제", "궁금")
        plan = plan_of(prof=profile("naver_a"), options=DraftOptions(exclude=terms))
        self.assertGreaterEqual(len(plan.outline), 1)
        self.assertEqual(len(plan.outline), len(plan.subheadings))
        self.assertTrue(all(plan.outline) and all(plan.subheadings), "빈 소제목이 없어야 한다")
        self.assertIn(plan.outline[0].split(" + ")[0], [step.name for step in pt.template_steps("정보형")] + [pt.LEAD_STEP.name])
        self.assertTrue([text for text in plan.checks if "목차가 비어" in text])

    def test_a_title_pattern_with_an_excluded_word_is_skipped(self):
        plan = plan_of(options=DraftOptions(exclude=("총정리", "기준")))
        for title in plan.titles:
            self.assertNotIn("총정리", title)
            self.assertNotIn("기준", title)
        self.assertEqual(len(plan.titles), 3)

    def test_forbidden_phrases_of_the_profile_are_kept_out_of_generated_titles_and_listed_in_the_cautions(self):
        plan = plan_of(prof=profile(forbidden_phrases=("총정리", "한눈에", "무조건")))
        for text in (*plan.titles, *plan.subheadings):
            self.assertNotIn("총정리", text)
            self.assertNotIn("한눈에", text)
        self.assertTrue([text for text in plan.cautions if text.startswith("이 블로그의 금지 표현은 쓰지 않습니다: ") and "무조건" in text])
        self.assertFalse([text for text in plan_of(prof=profile()).cautions if "금지 표현" in text])

    def test_only_the_first_ten_forbidden_phrases_are_listed_in_the_cautions(self):
        phrases = tuple(f"금지낱말{index}" for index in range(12))
        plan = plan_of(prof=profile(forbidden_phrases=phrases))
        listed = [text for text in plan.cautions if text.startswith("이 블로그의 금지 표현은 쓰지 않습니다: ")][0]
        self.assertIn("금지낱말9", listed)
        self.assertNotIn("금지낱말10", listed)
        many = plan_of(options=DraftOptions(exclude=tuple(f"제외낱말{index}" for index in range(12))))
        line = [text for text in many.cautions if text.startswith("제외하기로 한 내용은")][0]
        self.assertIn("제외낱말9", line)
        self.assertNotIn("제외낱말10", line)

    def test_an_excluded_word_in_the_candidates_own_words_is_noted_but_the_candidate_is_kept(self):
        plan = plan_of(candidate=make(topic="난방비 절약", keyword="난방비 절약", subs=()), prof=profile(excluded_topics=("난방",)))
        self.assertTrue([text for text in plan.checks if "이 블로그 프로필의 제외 주제 「난방」" in text and "핵심 키워드·주제" in text])
        self.assertIn("난방비 절약", plan.keyword)
        self.assertIn("난방비절약", plan.tags)
        user = plan_of(candidate=make(topic="난방비 절약", keyword="난방비 절약", subs=()), options=DraftOptions(exclude=("난방",)))
        self.assertTrue([text for text in user.checks if "제외할 내용 「난방」" in text and "제목에는 그대로 두었습니다" in text])

    def test_a_must_include_sentence_with_an_excluded_word_is_kept_and_noted(self):
        options = DraftOptions(exclude=("광고",), must_include=("광고 없이 설명합니다",), message="광고가 없습니다")
        plan = plan_of(options=options)
        self.assertIn("반드시 넣을 문장(입력): 광고 없이 설명합니다", plan.key_points)
        self.assertTrue([text for text in plan.checks if "제외할 내용 「광고」" in text and "입력하신" in text])

    def test_the_exclusion_does_not_remove_the_safety_cautions(self):
        plan = plan_of(options=DraftOptions(exclude=("경험", "가격", "과장", "확인")))
        self.assertTrue([text for text in plan.cautions if "경험하지 않은 일" in text])
        self.assertTrue([text for text in plan.cautions if text.startswith("제외하기로 한 내용은")])


class UserInputsTest(unittest.TestCase):
    FULL = dict(message="전하고 싶은 말입니다", experience=EXPERIENCE, opinion="저는 비교해 보고 고르길 권합니다", must_include=("꼭 들어갈 문장입니다", "둘째 문장입니다"), exclude=("광고",), audience="사회 초년생",
                length="2500+", title_direction="질문형으로", urls=("https://example.com/a",), price_date=("정가 12,000원(2026-11-01 기준)",), conclusion="비교한 뒤에 고르세요")

    def test_every_input_shows_up_in_the_plan(self):
        plan = plan_of(options=DraftOptions(**self.FULL))
        points = plan.key_points
        for expected in ("전하고 싶은 내용(입력): 전하고 싶은 말입니다", f"실제 경험(입력): {EXPERIENCE}", "개인 의견(입력): 저는 비교해 보고 고르길 권합니다", "반드시 넣을 문장(입력): 꼭 들어갈 문장입니다",
                         "반드시 넣을 문장(입력): 둘째 문장입니다", "가격·날짜(입력): 정가 12,000원(2026-11-01 기준)", "마무리에 넣을 결론(입력): 비교한 뒤에 고르세요"):
            self.assertIn(expected, points)
        self.assertTrue(all("(입력" in point for point in points[:7]), "사용자 입력이 먼저 나온다")
        self.assertFalse(any("(입력" in point for point in points[7:]))
        self.assertEqual(plan.audience, "사회 초년생")
        self.assertEqual(plan.length, (2500, None))
        self.assertEqual(plan.references, ("https://example.com/a",))
        self.assertEqual(dict(plan.direction)["제목 방향(입력)"], "질문형으로")
        self.assertEqual(dict(plan.direction)["결론(입력)"], "비교한 뒤에 고르세요")
        self.assertEqual(plan.titles[0], "보일러 점검, 무엇이 궁금하세요?")
        self.assertIn("보일러 점검: 비교한 뒤에 고르세요", plan.titles)
        other = plan_of(prof=profile("naver_b"), options=DraftOptions(**self.FULL))
        self.assertEqual(other.titles[0], "보일러 점검, 이런 점이 궁금하다면?")
        self.assertIn("비교한 뒤에 고르세요: 보일러 점검", other.titles)
        self.assertIn("경험 이야기", " ".join(plan.outline))
        self.assertTrue([text for text in plan.checks if "입력하신 가격·날짜는 그대로 넣었습니다" in text])
        self.assertTrue([text for text in plan.checks if "입력하신 참고 주소는 열어 보거나 가져오지 않고" in text])

    def test_without_inputs_no_input_line_exists(self):
        plan = plan_of()
        self.assertFalse([text for text in plan.key_points if "(입력" in text])
        self.assertFalse([label for label, _text in plan.direction if "(입력" in label])
        self.assertTrue([text for text in plan.checks if "참고 자료를 입력하지 않았습니다" in text])
        self.assertTrue([text for text in plan.checks if "가격·날짜 같은 수치는 계획에 넣지 않았습니다" in text])

    def test_title_direction_words_choose_a_title_form_and_unknown_text_is_used_as_typed(self):
        cases = {"질문형으로": ("보일러 점검, 무엇이 궁금하세요?", "보일러 점검, 이런 점이 궁금하다면?"), "짧게": ("보일러 점검 정리", "보일러 점검 한 줄 정리"), "결론부터": ("보일러 점검: 결론부터 정리", "결론부터 보는 보일러 점검"),
                 "비교를 강조": ("보일러 점검 비교", "보일러 점검, 비교해 보면"), "순서대로": ("보일러 점검, 순서대로 따라가기", "보일러 점검 단계별 정리"),
                 "초보자도 쉽게": ("보일러 점검, 처음이어도 쉽게", "처음 보는 분을 위한 보일러 점검"), "따뜻한 느낌": ("보일러 점검, 따뜻한 느낌", "따뜻한 느낌: 보일러 점검")}
        for direction, (first, second) in cases.items():
            with self.subTest(direction=direction):
                self.assertEqual(plan_of(prof=profile("naver_a"), options=DraftOptions(title_direction=direction)).titles[0], first)
                self.assertEqual(plan_of(prof=profile("naver_b"), options=DraftOptions(title_direction=direction)).titles[0], second)

    def test_a_conclusion_that_does_not_fit_the_title_limit_is_only_in_the_closing_point(self):
        long_conclusion = "가" * 120
        plan = plan_of(options=DraftOptions(conclusion=long_conclusion), prof=profile(max_title_chars=40))
        self.assertFalse([title for title in plan.titles if long_conclusion in title])
        self.assertIn(f"마무리에 넣을 결론(입력): {long_conclusion}", plan.key_points)

    def test_user_claims_outside_the_experience_field_are_noted_and_not_treated_as_experience(self):
        plan = plan_of(options=DraftOptions(opinion="직접 사용해보니 편리했습니다", message="수익을 냈습니다"))
        notes = [text for text in plan.checks if "직접 겪은 일을 말하는 표현이 있습니다" in text]
        self.assertEqual(len(notes), 2)
        self.assertIn("‘개인 의견’", " ".join(notes))
        self.assertIn("‘직접 전달하고 싶은 내용’", " ".join(notes))
        self.assertNotIn("경험 이야기", " ".join(plan.outline))
        with_experience = plan_of(options=DraftOptions(opinion="직접 사용해보니 편리했습니다", experience=EXPERIENCE))
        self.assertFalse([text for text in with_experience.checks if "직접 겪은 일을 말하는 표현이 있습니다" in text])
        direction = plan_of(options=DraftOptions(title_direction="직접 써본 느낌으로"))
        self.assertTrue([text for text in direction.checks if "‘원하는 제목 방향’" in text])
        self.assertFalse([title for title in direction.titles if "직접 써본" in title], "경험을 입력하지 않았으면 경험을 단정하는 제목은 만들지 않는다")

    def test_a_user_title_direction_with_braces_does_not_break_formatting(self):
        plan = plan_of(options=DraftOptions(title_direction="{이름} 느낌", conclusion="{결론}"))
        self.assertTrue(any("{이름} 느낌" in title for title in plan.titles))

    def test_the_candidate_and_the_profile_are_not_changed(self):
        candidate, prof = make(), profile(default_tags=("생활",), categories=(("생활", "생활정보"),))
        before = (candidate.to_dict(), prof.to_dict())
        dp.build_plan(candidate, prof, DraftOptions(**self.FULL), today=TODAY)
        self.assertEqual((candidate.to_dict(), prof.to_dict()), before)


class TwoBlogsTest(unittest.TestCase):
    def pair(self, candidate, options=None, **changes):
        return (dp.build_plan(candidate, profile("naver_a", **changes), options, today=TODAY), dp.build_plan(candidate, profile("naver_b", **changes), options, today=TODAY))

    def test_the_same_candidate_gives_different_plans_on_every_axis(self):
        for topic, keyword, subs, post_type in (*NEUTRAL, *PREMISE):
            candidate = make(topic, keyword, subs, post_type)
            first, second = self.pair(candidate)
            with self.subTest(topic=topic):
                self.assertNotEqual(first.titles, second.titles)
                self.assertFalse(set(first.titles) & set(second.titles), "제목이 겹친다")
                self.assertNotEqual(first.subheadings, second.subheadings)
                self.assertNotEqual(first.outline, second.outline, "소제목을 묶는 방식·순서가 같다")
                self.assertNotEqual(first.intent, second.intent)
                self.assertNotEqual(first.tags, second.tags)
                self.assertNotEqual(set(first.tags), set(second.tags), "태그의 조합(낱말)이 같다")
                self.assertNotEqual(first.key_points, second.key_points)
                for label in ("문체", "도입부", "설명 방식", "독자 관점", "예시", "마무리", "글 길이", "문단"):
                    self.assertNotEqual(dict(first.direction)[label], dict(second.direction)[label], label)

    def test_the_subheading_order_differs_by_grouping_and_by_the_purpose_first_lead(self):
        first, second = self.pair(make())
        self.assertNotIn(pt.LEAD_STEP.name, first.outline)
        self.assertEqual(second.outline[0], pt.LEAD_STEP.name)
        self.assertEqual(first.outline[0], "독자가 궁금해하는 문제")
        self.assertEqual(second.outline[1], "독자가 궁금해하는 문제")

    def test_a_profile_style_overrides_the_voice_default(self):
        first, second = self.pair(make(), intro_style="결론부터 먼저")
        self.assertEqual(first.outline[0], pt.LEAD_STEP.name)
        self.assertEqual(second.outline[0], pt.LEAD_STEP.name)
        first, second = self.pair(make(), intro_style="독자의 고민으로 시작")
        self.assertNotIn(pt.LEAD_STEP.name, first.outline)
        self.assertNotIn(pt.LEAD_STEP.name, second.outline)
        self.assertEqual(dict(first.direction)["도입부"], dict(second.direction)["도입부"].replace(dp.INTRO_LINES["problem"][1], dp.INTRO_LINES["problem"][0]))

    def test_the_default_tags_of_each_profile_make_the_tag_sets_differ_too(self):
        first = dp.build_plan(make(), profile("naver_a", default_tags=("생활",)), today=TODAY)
        second = dp.build_plan(make(), profile("naver_b", default_tags=("정보",)), today=TODAY)
        self.assertIn("생활", first.tags)
        self.assertNotIn("생활", second.tags)
        self.assertIn("정보", second.tags)

    def test_the_comparison_finds_the_two_plans_different_enough_for_every_candidate(self):
        for topic, keyword, subs, post_type in (*NEUTRAL, *PREMISE):
            for options in (None, DraftOptions(title_direction="질문형으로", conclusion="비교 뒤에 고르세요"), DraftOptions(experience=PRODUCT_EXPERIENCE, message="전하고 싶은 말입니다")):
                first, second = self.pair(make(topic, keyword, subs, post_type), options)
                with self.subTest(topic=topic, options=options is not None):
                    comparison = dp.compare_plans(first, second)
                    self.assertEqual((comparison.level, comparison.warnings), ("ok", ()), comparison.report)
                    self.assertLess(comparison.report.overall, similarity.Thresholds().warn_overall)
                    self.assertLess(comparison.report.body, similarity.Thresholds().warn_body)
                    self.assertLess(comparison.report.title, similarity.Thresholds().warn_title)

    def test_the_frame_removes_words_longest_first_and_in_dictionary_order_among_equals(self):
        base = plan_of()
        crafted = dataclasses.replace(base, keyword="가나다", topic="나다라", direction=(("제목 방향(입력)", "다라마"),))
        self.assertEqual(crafted.frame("가나다라마"), "라마")
        crafted = dataclasses.replace(base, keyword="가나", topic="가나다라", direction=())
        self.assertEqual(crafted.frame("가나다라마"), "마")
        self.assertEqual(dataclasses.replace(base, keyword="", topic="", direction=()).frame("가나다"), "가나다")

    def test_all_three_titles_count_in_the_comparison_not_only_the_first(self):
        first, second = self.pair(make())
        shared = dataclasses.replace(second, titles=(second.titles[0], first.titles[1], first.titles[2]))
        apart = dp.compare_plans(first, second).report.title
        near = dp.compare_plans(first, shared).report.title
        self.assertGreater(near, apart + 0.2, "둘째·셋째 제목이 같으면 제목 유사도가 올라야 한다")
        self.assertEqual(dp.compare_plans(first, shared).report.title, dp.compare_plans(shared, first).report.title)

    def test_the_comparison_is_symmetric(self):
        first, second = self.pair(make())
        forward, backward = dp.compare_plans(first, second), dp.compare_plans(second, first)
        self.assertEqual(forward.report.overall, backward.report.overall)
        self.assertEqual(forward.level, backward.level)

    def test_two_nearly_identical_plans_are_warned_about(self):
        first, _second = self.pair(make())
        same = dp.compare_plans(first, first)
        self.assertEqual(same.level, "high")
        self.assertEqual(same.report.overall, 0.95)
        self.assertTrue(same.warnings[0].startswith("두 블로그의 작성 기반이 많이 비슷합니다(전체 95%)"))
        self.assertGreater(len(same.warnings), 1)
        tweaked = dataclasses.replace(first, titles=("완전히 다른 제목입니다 오직 이것", *first.titles[1:]), tags=("다른태그", "또다른태그"))
        again = dp.compare_plans(first, tweaked)
        self.assertNotEqual(again.level, "ok")
        self.assertTrue(again.warnings)

    def test_the_user_text_both_blogs_receive_does_not_count_as_similarity(self):
        options = DraftOptions(message="아주 길고 똑같은 내용을 두 블로그에 모두 넣고 싶습니다 " * 5, opinion="똑같은 의견도 함께 넣습니다 " * 5)
        first, second = self.pair(make(), options)
        self.assertEqual(dp.compare_plans(first, second).level, "ok")
        self.assertNotIn("(입력", first.comparable_body())

    def test_thresholds_can_be_tightened(self):
        first, second = self.pair(make())
        strict = dp.compare_plans(first, second, similarity.Thresholds(warn_overall=0.2, high_overall=0.25))
        self.assertEqual(strict.level, "high")
        self.assertTrue(strict.warnings)
        warn_only = dp.compare_plans(first, second, similarity.Thresholds(warn_overall=0.2))
        self.assertEqual(warn_only.level, "warn")
        self.assertEqual(dp.compare_plans(first, second, similarity.Thresholds()).level, "ok")

    def test_only_plans_can_be_compared(self):
        first, _second = self.pair(make())
        for value in (None, "계획", {"titles": ()}, make()):
            with self.subTest(value=value):
                expect_invalid(self, lambda value=value: dp.compare_plans(first, value), "CONTENT_INVALID")
                expect_invalid(self, lambda value=value: dp.compare_plans(value, first), "CONTENT_INVALID")

    def test_the_same_inputs_always_give_the_same_plan(self):
        for blog in ("naver_a", "naver_b"):
            first = dp.build_plan(make(), profile(blog, default_tags=("생활",)), DraftOptions(**UserInputsTest.FULL), today=TODAY)
            for _ in range(5):
                self.assertEqual(dp.build_plan(make(), profile(blog, default_tags=("생활",)), DraftOptions(**UserInputsTest.FULL), today=TODAY), first)

    def test_the_result_does_not_depend_on_the_python_hash_seed(self):
        script = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
            "from chanceblog_desktop.content import draft_plan as dp\n"
            "from chanceblog_desktop.content.candidates import Candidate\n"
            "from chanceblog_desktop.content.draft_options import DraftOptions\n"
            "from chanceblog_desktop.content.profiles import NaverProfile\n"
            "c = Candidate.new('겨울 보일러 점검 순서', '보일러 점검', ('naver_a', 'naver_b'), sub_keywords=('보일러 청소', '난방비', '점검 주기'), now='2026-11-02T03:00:00Z')\n"
            "out = []\n"
            "for key in ('naver_a', 'naver_b'):\n"
            "    p = NaverProfile(key, '블로그', 'https://blog.naver.com/example', default_tags=('생활', '정보', '팁'), excluded_topics=('광고',), forbidden_phrases=('최고',))\n"
            "    out.append(dp.build_plan(c, p, DraftOptions(exclude=('가격', '광고'), must_include=('문장 하나', '문장 둘'), experience='경험입니다'), today='2026-11-03').to_dict())\n"
            "print(json.dumps(out, ensure_ascii=False, sort_keys=True))\n"
        )
        outputs = set()
        for seed in ("0", "1", "123", "99999"):
            done = subprocess.run([sys.executable, "-X", "utf8", "-c", script], capture_output=True, env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
            outputs.add(done.stdout)
        self.assertEqual(len(outputs), 1, "해시 시드가 달라지면 결과가 달라진다")


class SelfCheckTest(unittest.TestCase):
    """계획의 문장은 스스로 '지어내지 않기' 검사를 어기지 않는다 — 모든 글 유형 × 프로필 × 경험 입력 유무 × 후보."""

    PROFILES = (("naver_a", dict(default_tags=("생활", "정보"), categories=(("생활", "생활정보"),), forbidden_phrases=("최고", "무조건"), excluded_topics=("도박",))), ("naver_b", dict()), (None, None))

    def plans(self):
        candidates = [make(topic, keyword, subs, post_type) for topic, keyword, subs, post_type in (*NEUTRAL, *PREMISE)]
        for post_type, candidate in itertools.product(POST_TYPES, candidates):
            for key, changes in self.PROFILES:
                prof = None if key is None else profile(key, **changes)
                for experience in (False, True):
                    options = DraftOptions(experience=EXPERIENCE) if experience else DraftOptions()
                    blog = key or "github_pages"
                    yield post_type, candidate, key, experience, options, dp.build_plan(candidate, prof, options, today=TODAY, blog=blog, post_type=post_type)

    def test_no_plan_sentence_claims_anything_for_every_combination(self):
        count = 0
        for post_type, candidate, key, experience, options, plan in self.plans():
            count += 1
            found = claims.find_claims(plan.texts(), experience_given=experience, user_sentences=options.user_texts())
            with self.subTest(post_type=post_type, topic=candidate.topic, blog=key, experience=experience):
                self.assertEqual(found, (), [(claim, plan.texts()[claim.position]) for claim in found])
                self.assertEqual(len(plan.titles), 3)
                self.assertEqual(plan.post_type if plan.replaced is None else post_type, post_type)
        self.assertEqual(count, 5 * len(NEUTRAL + PREMISE) * 3 * 2)

    def test_the_users_own_words_are_the_only_exception_and_only_with_experience(self):
        plan = plan_of(options=DraftOptions(experience=EXPERIENCE, opinion="써 본 결과 만족스러웠습니다"))
        user = DraftOptions(experience=EXPERIENCE, opinion="써 본 결과 만족스러웠습니다").user_texts()
        self.assertEqual(claims.find_violations(plan.texts(), experience_given=True, user_sentences=user), ())
        self.assertTrue(claims.find_violations(plan.texts(), experience_given=False, user_sentences=user), "경험 입력이 없다고 치면 사용자 문장도 위반이다")
        self.assertTrue(claims.find_violations(plan.texts()))

    def test_the_plan_adds_no_price_date_time_or_statistic_by_itself(self):
        count = 0
        for _post_type, candidate, key, _experience, _options, plan in self.plans():
            count += 1
            with self.subTest(topic=candidate.topic, blog=key):
                self.assertEqual(claims.find_reviews(plan.texts()), ())
        self.assertEqual(count, 5 * len(NEUTRAL + PREMISE) * 3 * 2, "모든 조합을 본다")

    def test_user_given_prices_and_dates_are_the_only_reviews(self):
        options = DraftOptions(price_date=("정가 12,000원(2026-11-01 기준)",), message="운영은 오전 9시부터입니다", conclusion="30%는 줄입니다")
        plan = plan_of(options=options)
        found = claims.find_reviews(plan.texts())
        self.assertTrue(found)
        for claim in found:
            self.assertTrue(any(user in plan.texts()[claim.position] for user in options.user_texts()), plan.texts()[claim.position])

    def test_every_plan_sentence_is_free_of_result_promises(self):
        from chanceblog_desktop.content.candidates import forbidden_claim
        for _post_type, candidate, key, _experience, _options, plan in self.plans():
            for text in plan.texts():
                self.assertIsNone(forbidden_claim(text), (candidate.topic, key, text))

    def test_the_profile_text_the_operator_wrote_comes_through_without_claim_findings(self):
        prof = profile(tone="친근한 해요체", intro_style="독자의 고민으로 시작", difficulty="처음 접하는 사람도 이해", ending_style="핵심 세 줄 요약", forbidden_phrases=("직접 써본", "최고", "수익 보장"))
        plan = plan_of(prof=prof)
        self.assertEqual(claims.find_violations(plan.texts()), ())
        self.assertNotIn("직접 써본", " ".join(text for text in plan.cautions if "금지 표현" in text), "경험을 단정하는 금지 표현은 문장에 옮기지 않는다")


class ValidationTest(unittest.TestCase):
    def test_wrong_argument_types_are_content_invalid(self):
        for bad in (None, "후보", {"topic": "x"}, 5):
            with self.subTest(candidate=bad):
                expect_invalid(self, lambda bad=bad: dp.build_plan(bad, profile(), today=TODAY), "CONTENT_INVALID")
        for bad in ("프로필", {"key": "naver_a"}, 5, make()):
            with self.subTest(profile=bad):
                expect_invalid(self, lambda bad=bad: dp.build_plan(make(), bad, today=TODAY), "CONTENT_INVALID")
        for bad in ("입력", {"message": "x"}, 5, []):
            with self.subTest(options=bad):
                expect_invalid(self, lambda bad=bad: dp.build_plan(make(), profile(), bad, today=TODAY), "CONTENT_INVALID")

    def test_an_unknown_blog_type_or_a_mismatching_profile_is_refused_with_the_field_name(self):
        for bad in ("tistory", "", "네이버", 5, ["naver_a"]):
            with self.subTest(blog=bad):
                self.assertEqual(expect_invalid(self, lambda bad=bad: dp.build_plan(make(), None, today=TODAY, blog=bad)).slots["항목"], "블로그")
        self.assertEqual(expect_invalid(self, lambda: dp.build_plan(make(), profile("naver_a"), today=TODAY, blog="naver_b")).slots["항목"], "블로그")
        for bad in ("후기형", "정보", 5, ["정보형"], "정보형 "):
            with self.subTest(post_type=bad):
                self.assertEqual(expect_invalid(self, lambda bad=bad: dp.build_plan(make(), profile(), today=TODAY, post_type=bad)).slots["항목"], "글 유형")
        self.assertEqual(dp.build_plan(make(), profile(), today=TODAY, post_type="").post_type, "정보형")
        self.assertEqual(dp.build_plan(make(), profile(), today=TODAY, post_type=None).post_type, "정보형")

    def test_the_blog_may_be_any_of_the_five(self):
        for blog in st.PLATFORMS:
            with self.subTest(blog=blog):
                plan = dp.build_plan(make(blogs=(blog,)), None, today=TODAY, blog=blog)
                self.assertEqual(plan.blog, blog)


class JsonAndShapeTest(unittest.TestCase):
    def test_the_plan_is_json_serialisable_with_a_fixed_set_of_keys(self):
        plan = plan_of(options=DraftOptions(**UserInputsTest.FULL))
        data = plan.to_dict()
        self.assertEqual(json.loads(json.dumps(data, ensure_ascii=False)), data)
        self.assertEqual(set(data), {"blog", "topic", "keyword", "sub_keywords", "intent", "audience", "post_type", "titles", "direction", "outline", "subheadings", "key_points", "cautions", "category", "tags",
                                    "base_date", "references", "checks", "length", "complete", "sources", "replaced"})
        self.assertEqual(data["length"], {"min": 2500, "max": None})
        self.assertEqual(data["complete"], True)
        self.assertEqual(data["sources"]["length"], "user")
        self.assertIsNone(data["replaced"])
        self.assertEqual(data["direction"][0]["label"], "제목 방향(입력)")
        replaced = plan_of(candidate=make("서울 맛집 방문 후기", "맛집 방문 후기", (), POST_TYPES[4])).to_dict()
        self.assertEqual(replaced["replaced"], {"from": "방문 후기", "to": "위치·이용 정보와 방문 전 확인사항"})

    def test_the_plan_is_immutable_and_hashable_fields_are_tuples(self):
        plan = plan_of()
        for name in ("sub_keywords", "titles", "direction", "outline", "subheadings", "key_points", "cautions", "tags", "references", "checks", "length", "sources"):
            self.assertIsInstance(getattr(plan, name), tuple, name)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.blog = "naver_b"

    def test_texts_lists_every_sentence_and_the_outline_matches_the_subheadings(self):
        plan = plan_of(options=DraftOptions(**UserInputsTest.FULL))
        texts = plan.texts()
        for part in (plan.titles, plan.outline, plan.subheadings, plan.key_points, plan.cautions, plan.checks):
            for text in part:
                self.assertIn(text, texts)
        self.assertEqual(len(plan.outline), len(plan.subheadings))
        self.assertTrue(all(plan.titles) and all(plan.subheadings) and all(plan.key_points))
        self.assertEqual(plan.intro_text(), dict(plan.direction)["도입부"])

    def test_every_plan_is_complete_even_with_many_checks(self):
        plan = plan_of(candidate=make("서울 맛집 방문 후기", "맛집 방문 후기", (), POST_TYPES[4], duplicate=True, search_demand=1, data_date="2026-01-01"), prof=profile(excluded_topics=("맛집",)))
        self.assertGreaterEqual(len(plan.checks), 5)
        self.assertTrue(plan.complete)


class SpeedTest(unittest.TestCase):
    def test_the_largest_inputs_still_build_in_well_under_a_second(self):
        options = DraftOptions(message="가" * 500, experience="나" * 1000, opinion="다" * 500, must_include=tuple(f"문장 {index} " + "라" * 190 for index in range(10)), exclude=tuple(f"제외{index}" for index in range(20)),
                               audience="마" * 100, length="200-100000", title_direction="바" * 100, urls=tuple(f"https://example.com/{index}" for index in range(10)),
                               price_date=tuple(f"가격 {index} " + "사" * 80 for index in range(10)), conclusion="아" * 300)
        candidate = make("주" * 200, "키" * 60, tuple(f"보조{index}" for index in range(20)))
        prof = profile(default_tags=tuple(f"태그{index}" for index in range(30)), forbidden_phrases=tuple(f"금지{index}" for index in range(100)), excluded_topics=tuple(f"주제{index}" for index in range(100)),
                       categories=tuple((f"분류{index}", f"카테고리{index}") for index in range(50)), subheading_min=12, subheading_max=20, max_tags=30, max_title_chars=200)
        started = time.perf_counter()
        for _ in range(20):
            plan = dp.build_plan(candidate, prof, options, today=TODAY)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed / 20, 1.0)
        self.assertLess(elapsed, 8.0)
        started = time.perf_counter()
        dp.compare_plans(plan, plan)
        self.assertLess(time.perf_counter() - started, 1.0)
        started = time.perf_counter()
        claims.find_claims(plan.texts(), experience_given=True, user_sentences=options.user_texts())
        self.assertLess(time.perf_counter() - started, 1.0)


class TitleGateTest(unittest.TestCase):
    """제목 후보는 모두 한 관문(제외어·금지 표현·'지어내지 않기')을 지난다 — 제목 방향·결론으로 고른 틀 제목도 예외가 아니다."""
    DIRECTIONS = (("질문형으로", "궁금"), ("짧게", "정리"), ("간결하게", "정리"), ("결론부터", "결론"), ("비교", "비교"), ("순서대로 방법", "순서"), ("단계별로", "단계"), ("초보도 쉽게", "처음"), ("쉽게", "쉽게"),
                  ("입문자용", "입문"), ("한 줄 결론", "한 줄"), ("물음표로", "물음"))

    def test_a_title_template_picked_by_the_direction_never_contains_an_excluded_word(self):
        for key in ("naver_a", "naver_b"):
            for direction, word in self.DIRECTIONS:
                with self.subTest(blog=key, direction=direction, excluded=word):
                    plan = plan_of(candidate=make("노트북 선택", "노트북 선택", (), blogs=(key,)), prof=profile(key), options=DraftOptions(exclude=(word,), title_direction=direction))
                    self.assertEqual(len(plan.titles), 3)
                    for title in plan.titles:
                        self.assertNotIn(word, title.replace("노트북 선택", ""), plan.titles)

    def test_the_exact_case_from_the_review(self):
        plan = plan_of(candidate=make("노트북 선택", "노트북 선택", ()), prof=profile("naver_a"), options=DraftOptions(exclude=("정리",), title_direction="짧게"))
        self.assertTrue(all("정리" not in title for title in plan.titles), plan.titles)
        plain = plan_of(candidate=make("노트북 선택", "노트북 선택", ()), prof=profile("naver_a"), options=DraftOptions(title_direction="짧게"))
        self.assertTrue(any("정리" in title for title in plain.titles), "제외하지 않으면 그 방향의 틀 제목이 나온다")

    def test_profile_exclusions_and_forbidden_phrases_gate_the_direction_titles_too(self):
        plan = plan_of(candidate=make("노트북 선택", "노트북 선택", ()), prof=profile("naver_a", excluded_topics=("정리",)), options=DraftOptions(title_direction="짧게"))
        self.assertTrue(all("정리" not in title for title in plan.titles), plan.titles)
        plan = plan_of(candidate=make("노트북 선택", "노트북 선택", ()), prof=profile("naver_b", forbidden_phrases=("결론부터",)), options=DraftOptions(title_direction="결론"))
        self.assertTrue(all("결론부터" not in title for title in plan.titles), plan.titles)
        plan = plan_of(candidate=make("노트북 선택", "노트북 선택", ()), prof=profile("naver_b", excluded_topics=("결론",)), options=DraftOptions(conclusion="필요한 것만 고르세요"))
        self.assertTrue(all("결론" not in title.replace("필요한 것만 고르세요", "") for title in plan.titles), plan.titles)

    def test_the_users_own_words_in_a_title_are_not_blocked_by_the_users_own_exclusions(self):
        plan = plan_of(candidate=make("노트북 선택", "노트북 선택", ()), prof=profile("naver_a"), options=DraftOptions(exclude=("광고",), title_direction="광고 없이 솔직하게"))
        self.assertTrue(any("광고 없이 솔직하게" in title for title in plan.titles), plan.titles)

    def test_a_title_made_of_the_users_conclusion_is_dropped_if_it_claims_an_experience(self):
        plan = plan_of(candidate=make("노트북 선택", "노트북 선택", ()), prof=profile("naver_a"), options=DraftOptions(conclusion="직접 써보니 좋았습니다"))
        self.assertTrue(all(not claims.find_violations([title]) for title in plan.titles), plan.titles)

    def test_random_combinations_keep_excluded_words_out_of_every_generated_line(self):
        import random
        rng = random.Random(20261103)
        words = ["정리", "기준", "방법", "비교", "확인", "가격", "후기", "결론", "순서", "처음"]
        directions = ["", "질문형으로", "짧게", "결론부터", "비교", "단계별 방법", "초보도 쉽게", "감성적인 어조"]
        subjects = (("노트북 선택", "노트북 선택", ()), ("보일러 점검 순서", "보일러 점검", ("보일러 청소",)), ("전기요금 절약", "전기요금", ("요금제",)))
        checked = 0
        for _ in range(240):
            topic, keyword, subs = rng.choice(subjects)
            key = rng.choice(("naver_a", "naver_b"))
            excluded = tuple(rng.sample(words, rng.randint(1, 3)))
            options = DraftOptions(exclude=excluded, title_direction=rng.choice(directions), conclusion=rng.choice(("", "꼼꼼히 확인하면 충분합니다", "필요한 것만 고르세요")))
            plan = plan_of(candidate=make(topic, keyword, subs, blogs=(key,)), prof=profile(key, subheading_min=2, subheading_max=8), options=options)
            given = [value for label, value in plan.direction if "(입력" in label]
            for place, texts in (("제목", plan.titles), ("소제목", plan.subheadings), ("목차", plan.outline), ("핵심 내용", [text for text in plan.key_points if "(입력" not in text]), ("태그", plan.tags)):
                for text in texts:
                    rest = text
                    for word in sorted({keyword, topic, *subs, *plan.sub_keywords, *given, plan.keyword, plan.topic}, key=len, reverse=True):
                        rest = rest.replace(word, "") if word else rest
                    for word in excluded:
                        self.assertNotIn(word, rest, f"{place}: {text} / {options}")
                        checked += 1
        self.assertGreater(checked, 2000)


class InfoArticleTest(unittest.TestCase):
    """후기를 '쓴' 글이 아니라 후기에 '대한' 정보 글은 후기로 오인하지 않는다 — 키워드를 깎거나 글 유형을 바꾸지 않는다."""
    ARTICLES = ("후기 작성 방법", "체험단 신청 방법", "맛집 리뷰 앱 추천", "후기 잘 쓰는 법", "리뷰 작성 요령", "체험단 모집 사이트", "블로그 후기 쓰는 방법", "리뷰 이벤트 참여 방법")

    def test_the_keyword_and_the_type_are_kept_and_nothing_is_replaced(self):
        for key in ("naver_a", "naver_b"):
            for keyword in self.ARTICLES:
                with self.subTest(blog=key, keyword=keyword):
                    plan = plan_of(candidate=make(keyword, keyword, (), POST_TYPES[0], blogs=(key,)), prof=profile(key))
                    self.assertEqual(plan.keyword, keyword)
                    self.assertIsNone(plan.replaced)
                    self.assertEqual(plan.post_type, POST_TYPES[0])
                    self.assertFalse([text for text in plan.checks if "형식이지만" in text], plan.checks)

    def test_a_real_review_candidate_is_still_replaced(self):
        plan = plan_of(candidate=make("서울 맛집 방문 후기 추천 메뉴", "맛집 방문 후기", ()), prof=profile("naver_a"))
        self.assertIsNotNone(plan.replaced)
        self.assertEqual(plan.post_type, POST_TYPES[4])


class ReviewStyleKeywordTest(unittest.TestCase):
    """후기형 후보를 경험담 없이 바꿀 때 키워드가 낱말 단위로 정리되어 어색한 조각('어요'·'더니')이 제목·소제목에 남지 않는다."""
    CASES = (("배달 앱 비교 써봤어요", "배달 앱 비교"), ("무선 이어폰 비교 직접 써봤더니", "무선 이어폰 비교"), ("로봇청소기 구매 후기와 장단점", "로봇청소기 구매와 장단점"), ("신형 노트북 언박싱과 후기", "신형 노트북"),
             ("서울 근교 캠핑장 다녀왔어요", "서울 근교 캠핑장"), ("에어프라이어 써보니", "에어프라이어"), ("에어프라이어 사용 소감", "에어프라이어"), ("아이오닉 6 시승기", "아이오닉 6"), ("Galaxy S25 review", "Galaxy S25"))

    def test_the_keyword_in_the_plan_is_clean_and_no_title_or_heading_has_a_fragment(self):
        for key in ("naver_a", "naver_b"):
            for keyword, expected in self.CASES:
                with self.subTest(blog=key, keyword=keyword):
                    plan = plan_of(candidate=make(keyword, keyword, (), POST_TYPES[0], blogs=(key,)), prof=profile(key))
                    self.assertEqual(plan.keyword, expected)
                    self.assertIsNotNone(plan.replaced, "경험 입력이 없으면 안전 대체를 한다")
                    self.assertEqual(claims.find_violations(plan.texts()), ())
                    for text in (*plan.titles, *plan.subheadings, *plan.key_points):
                        for fragment in (" 어요", " 더니", "어요 ", "더니 ", "후기", "써봤", "다녀왔", "review"):
                            self.assertNotIn(fragment, text, text)

    def test_a_modifier_keyword_is_kept_instead_of_turning_into_the_generic_subject(self):
        for keyword in ("느렸던 노트북 속도 개선", "불편했던 점을 모아 정리한 설치 가이드", "아쉬웠던 기능 보완 방법"):
            with self.subTest(keyword=keyword):
                plan = plan_of(candidate=make(keyword, keyword, ()), prof=profile("naver_a"))
                self.assertEqual(plan.keyword, keyword)
                self.assertNotEqual(plan.keyword, dp.GENERIC_SUBJECT)
                self.assertFalse([text for text in plan.checks if "경험을 단정하는 표현" in text], plan.checks)
                self.assertTrue(all(title.startswith("이 주제") is False for title in plan.titles), plan.titles)


class ProfileTextTest(unittest.TestCase):
    """블로그 프로필의 말투·안내 글에 경험을 단정하는 표현이 있어도 계획 문장은 위반하지 않는다 — 그 글은 계획에 옮기지 않고 확인 권장으로 알린다."""
    CLAIMING = dict(tone="직접 써보니 편했다는 말투", audience="어제 다녀왔어요 하는 독자", intro_style="직접 사용해보니 좋았다고 시작", difficulty="써봤는데 쉬웠어요 수준", ending_style="구매했습니다 하며 마무리")

    def test_claiming_profile_text_is_not_copied_and_is_reported(self):
        for key in ("naver_a", "naver_b"):
            plan = plan_of(candidate=make(blogs=(key,)), prof=profile(key, **self.CLAIMING))
            with self.subTest(blog=key):
                self.assertEqual(claims.find_violations(plan.texts()), (), plan.texts())
                notes = [text for text in plan.checks if "블로그 프로필의" in text and "단정하는 표현" in text]
                self.assertEqual(len(notes), 5, plan.checks)
                for label in ("말투", "대상 독자", "도입부 스타일", "설명 난이도", "마무리 방식"):
                    self.assertTrue([text for text in notes if f"‘{label}’" in text], label)
                self.assertEqual({item: sources(plan)[item] for item in ("tone", "audience", "intro_style", "difficulty", "ending_style")},
                                 {"tone": "default", "audience": "default", "intro_style": "default", "difficulty": "default", "ending_style": "default"})
                self.assertNotIn("직접 써보니", " ".join(plan.texts()))

    def test_clean_profile_text_is_kept_and_not_reported(self):
        plan = plan_of(prof=profile(tone="친근한 해요체", audience="직장인 독자"))
        self.assertEqual((plan.audience, sources(plan)["audience"]), ("직장인 독자", "profile"))
        self.assertFalse([text for text in plan.checks if "단정하는 표현" in text])

    def test_every_option_field_and_profile_text_combination_is_free_of_claims(self):
        safe_all = dict(message="독자에게 전하고 싶은 말입니다.", opinion="개인적으로는 꼼꼼한 확인이 중요하다고 봅니다.", must_include=("보증 기간 안내", "고객센터 안내"), exclude=("광고", "직접 써본 후기"), audience="초보 직장인",
                        length="2500+", title_direction="질문형으로", urls=("https://example.com/guide",), price_date=("정가 12,000원(2026-11-01 기준)",), conclusion="필요한 것만 고르세요")
        profiles = (dict(), self.CLAIMING, dict(tone="친근한 해요체", audience="직장인 독자", intro_style="독자의 고민으로 시작", difficulty="처음 접하는 사람도 이해", ending_style="핵심 세 줄 요약", forbidden_phrases=("직접 써본", "최고"),
                                                 excluded_topics=("직접 사용해본", "도박"), default_tags=("생활", "직접써본후기"), categories=(("생활", "생활정보"),)))
        count = 0
        for key, changes, experience in itertools.product(("naver_a", "naver_b"), profiles, (False, True)):
            for topic, keyword, subs, post_type in (*NEUTRAL[:4], *PREMISE[:3]):
                options = DraftOptions(experience=EXPERIENCE if experience else "", **safe_all)
                plan = dp.build_plan(make(topic, keyword, subs, post_type, blogs=(key,)), profile(key, **changes), options, today=TODAY, blog=key)
                found = claims.find_violations(plan.texts(), experience_given=experience, user_sentences=options.user_texts())
                count += 1
                with self.subTest(blog=key, topic=topic, experience=experience, profile=sorted(changes)):
                    self.assertEqual(found, (), [(claim, plan.texts()[claim.position]) for claim in found])
                    self.assertNotIn("직접써본후기", plan.tags)
        self.assertEqual(count, 2 * 3 * 2 * 7)

    def test_quoted_words_of_the_user_appear_only_as_whole_user_text(self):
        options = DraftOptions(exclude=("직접 써본 후기", "가격"), experience=EXPERIENCE)
        self.assertIn("직접 써본 후기", options.user_texts())
        plan = plan_of(options=options)
        self.assertEqual(claims.find_violations(plan.texts(), experience_given=True, user_sentences=options.user_texts()), ())


class TagTest(unittest.TestCase):
    def test_tags_never_claim_an_experience_and_never_contain_excluded_words(self):
        prof = profile("naver_a", default_tags=("직접써본후기", "생활", "광고성", "정보"))
        plan = plan_of(candidate=make("노트북 선택", "노트북 선택", ("직접 써본 팁", "배터리 시간")), prof=prof, options=DraftOptions(exclude=("광고",)))
        self.assertEqual(claims.find_violations(plan.tags), (), plan.tags)
        self.assertNotIn("직접써본후기", plan.tags)
        self.assertNotIn("광고성", plan.tags)
        self.assertIn("생활", plan.tags)
        self.assertTrue(all("광고" not in tag for tag in plan.tags), plan.tags)

    def test_an_excluded_word_inside_a_subject_tag_is_still_allowed_when_the_subject_has_it(self):
        plan = plan_of(candidate=make("광고 노트북 선택", "광고 노트북", ()), prof=profile("naver_a"), options=DraftOptions(exclude=("광고",)))
        self.assertTrue(any("광고" in tag for tag in plan.tags), "후보의 낱말로 만든 태그는 그대로 둔다")


class SourcesAfterReplacementTest(unittest.TestCase):
    def test_a_safe_replacement_records_the_post_type_template_layer(self):
        plan = plan_of(candidate=make("서울 맛집 방문 후기", "맛집 방문 후기", (), POST_TYPES[0]), prof=profile("naver_a"))
        self.assertEqual(plan.post_type, POST_TYPES[4])
        self.assertEqual(sources(plan)["post_type"], "post_type")
        asked = plan_of(candidate=make("서울 맛집 방문 후기", "맛집 방문 후기", (), POST_TYPES[0]), prof=profile("naver_a"), post_type=POST_TYPES[1])
        self.assertEqual((asked.post_type, sources(asked)["post_type"]), (POST_TYPES[1], "user"))

    def test_the_general_experience_note_does_not_repeat_the_replacement_note(self):
        plan = plan_of(candidate=make("서울 맛집 방문 후기", "맛집 방문 후기", ()), prof=profile("naver_a"))
        self.assertEqual(len([text for text in plan.checks if "‘실제 사용 경험’ 칸" in text]), 1, plan.checks)
        self.assertTrue([text for text in plan.checks if "형식이지만" in text])
        plain = plan_of(candidate=make("노트북 선택", "노트북 선택", ()), prof=profile("naver_a"))
        self.assertEqual(len([text for text in plain.checks if "‘실제 사용 경험’ 칸" in text]), 1, plain.checks)


class TitleOrderTest(unittest.TestCase):
    def test_voice_zero_puts_the_topic_title_first_and_voice_one_does_not(self):
        candidate = make("겨울 보일러 점검 순서", "보일러 점검", ())
        first = plan_of(candidate=candidate, prof=profile("naver_a"))
        second = plan_of(candidate=candidate, prof=profile("naver_b"))
        self.assertEqual(first.titles[0], "겨울 보일러 점검 순서")
        self.assertNotEqual(second.titles[0], "겨울 보일러 점검 순서")

    def test_a_repeated_word_in_a_title_pattern_is_folded_in_every_title(self):
        for key in ("naver_a", "naver_b"):
            plan = plan_of(candidate=make("점검 방법", "점검", (), blogs=(key,)), prof=profile(key))
            for title in plan.titles:
                words = title.replace(",", " ").replace(":", " ").split()
                for before, after in zip(words, words[1:]):
                    self.assertFalse(len(before) >= 2 and after.startswith(before), title)


class SmallBranchesTest(unittest.TestCase):
    """범위 점검에서 안 닿은 작은 가지 — 받침이 없는 끝(빈 글·기호), 제외 낱말 묶음의 참거짓, 후보 낱말에 금지 표현이 있을 때의 안내."""

    def test_the_final_consonant_of_text_without_letters_is_none(self):
        self.assertEqual((dp._final(""), dp._final("…"), dp._final(" ·")), (0, 0, 0))
        self.assertEqual(dp.particle("", "을", "를"), "를")
        self.assertEqual(dp._fill("{x:을/를}", x=""), "를")

    def test_the_excluder_is_true_only_with_words(self):
        self.assertFalse(dp._Excluder((), ()))
        self.assertFalse(dp._Excluder(("  ",), ("",)))
        self.assertTrue(dp._Excluder(("가격",), ()))

    def test_a_forbidden_phrase_in_the_candidates_own_words_is_noted(self):
        plan = plan_of(candidate=make("최고의 노트북 고르기", "최고 노트북", ()), prof=profile("naver_a", forbidden_phrases=("최고",)))
        notes = [text for text in plan.checks if "금지 표현" in text and "「최고」" in text]
        self.assertTrue(notes, plan.checks)
        self.assertTrue(any("후보의 주제" in text for text in notes) or any("후보의 핵심 키워드" in text for text in notes), notes)


class PolishTest(unittest.TestCase):
    def test_particles_follow_the_last_letter(self):
        self.assertEqual(dp._fill("{length:을/를} 목표로 합니다", length="2,500자 이상"), "2,500자 이상을 목표로 합니다")
        self.assertEqual(dp._fill("{length:을/를} 목표로 합니다", length="1,500~2,000자"), "1,500~2,000자를 목표로 합니다")
        self.assertEqual(dp._fill("{tone:으로/로} 씁니다", tone="쉬운 존댓말 설명체"), "쉬운 존댓말 설명체로 씁니다")
        self.assertEqual(dp._fill("{tone:으로/로} 씁니다", tone="담백한 설명"), "담백한 설명으로 씁니다")
        self.assertEqual(dp._fill("{tone:으로/로} 씁니다", tone="친절한 글말"), "친절한 글말로 씁니다")                 # ㄹ 받침은 '로'
        self.assertEqual(dp._fill("{x:이/가}", x="책"), "책이")
        self.assertEqual(dp._fill("{x:이/가}", x="나무"), "나무가")
        self.assertEqual(dp._fill("{x:은/는}", x="3"), "3은")                                                       # 삼 — 받침 있음
        self.assertEqual(dp._fill("{x:은/는}", x="2"), "2는")                                                       # 이 — 받침 없음
        self.assertEqual(dp._fill("{x:으로/로}", x="7"), "7로")                                                     # 칠 — ㄹ 받침
        self.assertEqual(dp._fill("{x:을/를}", x="(주)에이앤"), "(주)에이앤을")                                          # 영문 N — 엔
        self.assertEqual(dp._fill("{x:을/를}", x="ABC)"), "ABC)를")                                                  # 닫는 괄호는 건너뛰고 C(씨)의 받침을 본다 — 조사는 값 뒤에 붙는다
        self.assertEqual(dp._fill("{a} 그리고 {a}", a="값"), "값 그리고 값")

    def test_the_length_line_in_the_plan_has_the_right_particle(self):
        for key, voice in (("naver_a", 0), ("naver_b", 1)):
            open_ended = dict(plan_of(candidate=make(blogs=(key,)), prof=profile(key), options=DraftOptions(length="2500+")).direction)["글 길이"]
            ranged = dict(plan_of(candidate=make(blogs=(key,)), prof=profile(key), options=DraftOptions(length="1500-2000")).direction)["글 길이"]
            self.assertNotIn("이상를", open_ended)
            self.assertNotIn("이상를", ranged)
            if voice == 0:
                self.assertEqual((open_ended, ranged), ("2,500자 이상을 목표로 합니다", "1,500~2,000자를 목표로 합니다"))

    def test_the_tone_line_uses_the_right_particle_for_every_default_style(self):
        for key in ("naver_a", "naver_b"):
            line = dict(plan_of(candidate=make(blogs=(key,)), prof=profile(key)).direction)["문체"]
            self.assertNotRegex(line, "체을|체이|으로 씁니다")
            self.assertIn("쉬운 존댓말 설명체", line)

    def test_repeated_or_prefixed_words_are_collapsed(self):
        self.assertEqual(dp._collapse("점검 점검법"), "점검법")
        self.assertEqual(dp._collapse("노트북 비교 비교 기준"), "노트북 비교 기준")
        self.assertEqual(dp._collapse("노트북 비교 가이드"), "노트북 비교 가이드")
        self.assertEqual(dp._collapse("가 가나"), "가 가나")                                                         # 한 글자는 접두로 보지 않는다
        self.assertEqual(dp._collapse("방법, 방법: 정리"), "방법: 정리")

    def test_no_generated_line_repeats_a_word_in_any_combination(self):
        for topic, keyword, subs, post_type in NEUTRAL:
            for key in ("naver_a", "naver_b"):
                plan = plan_of(candidate=make(topic, keyword, subs, post_type), prof=profile(key))
                for text in (*plan.titles, *plan.subheadings):
                    words = text.replace(",", " ").replace(":", " ").split()
                    for before, after in zip(words, words[1:]):
                        self.assertFalse(len(before) >= 2 and after.startswith(before), f"{before!r} 다음에 {after!r}: {text}")

    def test_a_sub_keyword_with_an_excluded_word_is_left_out_everywhere(self):
        candidate = make("노트북 선택", "노트북 선택", ("가격 비교", "배터리 시간"))
        plan = plan_of(candidate=candidate, prof=profile("naver_a"), options=DraftOptions(exclude=("가격",)))
        self.assertEqual(plan.sub_keywords, ("배터리 시간",))
        self.assertTrue(all("가격" not in text for text in plan.key_points), plan.key_points)
        self.assertTrue(all("가격" not in tag for tag in plan.tags), plan.tags)
        self.assertTrue([text for text in plan.checks if "제외할 내용에 걸려 뺀 보조 키워드" in text and "가격 비교" in text], plan.checks)
        everything = plan_of(candidate=candidate, prof=profile("naver_a"))
        self.assertEqual(everything.sub_keywords, ("가격 비교", "배터리 시간"))
        profile_side = plan_of(candidate=candidate, prof=profile("naver_a", excluded_topics=("가격",)))
        self.assertEqual(profile_side.sub_keywords, ("배터리 시간",))

    def test_the_tags_source_is_the_profile_only_when_a_profile_tag_survived(self):
        candidate = make("노트북 선택", "노트북 선택", ())
        kept = plan_of(candidate=candidate, prof=profile("naver_a", default_tags=("생활정보", "리뷰")))
        self.assertEqual(sources(kept)["tags"], "profile")
        self.assertIn("생활정보", kept.tags)
        none_left = plan_of(candidate=candidate, prof=profile("naver_a", default_tags=("생활정보", "리뷰")), options=DraftOptions(exclude=("생활정보", "리뷰")))
        self.assertNotIn("생활정보", none_left.tags)
        self.assertEqual(sources(none_left)["tags"], "candidate")
        capped = plan_of(candidate=candidate, prof=profile("naver_a", default_tags=("생활정보",), max_tags=1))
        self.assertEqual(sources(capped)["tags"], "candidate")                                                      # 상한 때문에 프로필 태그가 밀려났다
        self.assertEqual(sources(plan_of(candidate=candidate, prof=profile("naver_a")))["tags"], "candidate")

    def test_an_exclusion_that_itself_claims_an_experience_is_not_quoted_in_the_cautions(self):
        for key in ("naver_a", "naver_b"):
            plan = plan_of(candidate=make(blogs=(key,)), prof=profile(key), options=DraftOptions(exclude=("직접 써본 후기", "가격")))
            self.assertEqual(claims.find_violations(plan.texts()), (), plan.texts())
            line = next(text for text in plan.cautions if text.startswith("제외하기로 한 내용"))
            self.assertIn("가격", line)
            self.assertNotIn("직접 써본", line)
            self.assertIn("외 1개", line)
        only = plan_of(options=DraftOptions(exclude=("직접 써본 후기",)))
        self.assertEqual(claims.find_violations(only.texts()), (), only.texts())
        self.assertTrue(next(text for text in only.cautions if text.startswith("제외하기로 한 내용")).endswith("모두 1개"))

    def test_other_quoted_words_in_the_notes_are_checked_the_same_way(self):
        candidate = make("직접 써본 청소기 비교", "청소기 비교", ())
        plan = plan_of(candidate=candidate, prof=profile("naver_a", excluded_topics=("직접 써본",)), options=DraftOptions(experience=PRODUCT_EXPERIENCE))
        self.assertEqual(claims.find_violations(plan.texts(), experience_given=True, user_sentences=[PRODUCT_EXPERIENCE]), (), plan.texts())


if __name__ == "__main__":
    unittest.main()
