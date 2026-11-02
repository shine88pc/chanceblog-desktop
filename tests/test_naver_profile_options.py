"""네이버 블로그 프로필의 '글을 만들 때 쓰는 선택 항목' 시험 — 도입부 스타일·소제목 수 범위·설명 난이도·마무리 방식·제외 주제·같은 주제 재사용 기준·기본 글 유형.

지키는 것:
  1) 모두 기본값이 있어 옛 프로필(이 항목이 없는 JSON)이 그대로 읽히고, 새 항목을 쓰지 않는 프로필의 저장 모양은 예전과 한 글자도 다르지 않다.
  2) 모르는 칸은 여전히 거절한다(새 칸 여덟 개만 더 허용된다).
  3) 새 항목도 엄격하게 검사한다 — 모양이 틀리면 CONTENT_INVALID 로 거절하고 고쳐 받지 않는다.
  4) 기본값에서 벗어난 값만 저장 모양에 나타나고, 되돌려 읽어도 같다. 기존 변환(`render/naver.py`)은 새 항목에 영향을 받지 않는다.
네트워크·파일 없이 돈다.
"""
import dataclasses
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import profiles  # noqa: E402
from chanceblog_desktop.content.profiles import DEFAULT_POST_TYPE, DEFAULT_TOPIC_REUSE_DAYS, MAX_EXCLUDED, MAX_PHRASE, MAX_REUSE_DAYS, MAX_SUBHEADINGS, POST_TYPES, NaverProfile  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.render.naver import build_package  # noqa: E402

GOOD = {"key": "naver_a", "display_name": "블로그 A", "blog_url": "https://blog.naver.com/example_a"}
# 이 항목들이 생기기 전에 저장된 프로필 JSON(tests/test_naver_profiles.py 의 StoredShapeTest.FULL 과 같다) — 지금도 그대로 읽히고 그대로 저장돼야 한다
OLD_FULL = {
    "key": "naver_b", "display_name": "블로그 B", "blog_url": "https://blog.naver.com/example_b", "topic": "생활", "audience": "직장인", "tone": "차분한 말투",
    "categories": [["건강", "생활 건강"]], "default_tags": ["생활", "팁"], "forbidden_phrases": ["무조건"], "image_spec": "가로 800px 이상", "min_chars": 500, "max_chars": 4000,
    "max_title_chars": 50, "paragraph_max_chars": 150, "max_tags": 8, "disclosure": "AI 도움을 받았습니다.", "publish_cycle": "주 2회",
}
OLD_KEYS = tuple(OLD_FULL)
NEW_KEYS = ("intro_style", "subheading_min", "subheading_max", "difficulty", "ending_style", "excluded_topics", "topic_reuse_days", "post_type")
NON_DEFAULT = {"intro_style": "독자의 고민으로 시작", "subheading_min": 2, "subheading_max": 4, "difficulty": "처음 접하는 사람도 이해", "ending_style": "핵심 세 줄 요약",
               "excluded_topics": ("주식", "코인"), "topic_reuse_days": 30, "post_type": "비교형"}


def make(**changes):
    return NaverProfile(**{**GOOD, **changes})


def dumped(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


class CompatibilityTest(unittest.TestCase):
    def test_the_new_options_have_the_documented_defaults(self):
        profile = make()
        self.assertEqual((profile.intro_style, profile.subheading_min, profile.subheading_max, profile.difficulty), ("", 3, 5, ""))
        self.assertEqual((profile.ending_style, profile.excluded_topics, profile.topic_reuse_days, profile.post_type), ("", (), 90, "정보형"))
        self.assertEqual((DEFAULT_TOPIC_REUSE_DAYS, DEFAULT_POST_TYPE), (90, "정보형"))
        self.assertEqual(profiles._NEW_DEFAULTS, {"intro_style": "", "subheading_min": 3, "subheading_max": 5, "difficulty": "", "ending_style": "", "excluded_topics": (),
                                                  "topic_reuse_days": 90, "post_type": "정보형"})

    def test_a_profile_json_saved_before_these_options_existed_still_reads(self):
        profile = NaverProfile.from_dict(OLD_FULL)
        self.assertEqual((profile.key, profile.display_name, profile.min_chars, profile.publish_cycle), ("naver_b", "블로그 B", 500, "주 2회"))
        self.assertEqual((profile.topic_reuse_days, profile.post_type, profile.subheading_min, profile.excluded_topics), (90, "정보형", 3, ()))
        self.assertEqual(NaverProfile.from_dict(GOOD), make())

    def test_saving_an_old_profile_again_does_not_change_one_character(self):
        self.assertEqual(dumped(NaverProfile.from_dict(OLD_FULL).to_dict()), dumped(OLD_FULL))
        self.assertEqual(sorted(make().to_dict()), sorted(OLD_KEYS))
        self.assertTrue(set(NEW_KEYS).isdisjoint(make().to_dict()), "기본값뿐이면 새 항목은 저장 모양에 나타나지 않는다")

    def test_old_fields_keep_their_positions_when_a_profile_is_built_by_position(self):
        profile = NaverProfile("naver_a", "이름", "https://blog.naver.com/x", "주제", "독자", "말투", {"건강": "생활"}, ("태그",), ("금지",), "규격", 100, 900, 40, 120, 7, "고지", "주 3회")
        self.assertEqual((profile.topic, profile.audience, profile.tone, profile.categories, profile.default_tags, profile.forbidden_phrases, profile.image_spec),
                         ("주제", "독자", "말투", (("건강", "생활"),), ("태그",), ("금지",), "규격"))
        self.assertEqual((profile.min_chars, profile.max_chars, profile.max_title_chars, profile.paragraph_max_chars, profile.max_tags, profile.disclosure, profile.publish_cycle),
                         (100, 900, 40, 120, 7, "고지", "주 3회"))
        self.assertEqual(profile.post_type, "정보형")

    def test_the_existing_conversion_does_not_read_the_new_options(self):
        body = "첫 문단입니다. 독자가 궁금해하는 문제를 먼저 짚습니다.\n\n둘째 문단입니다. 기준과 방법을 설명합니다.\n\n셋째 문단입니다. 주의사항을 정리합니다."
        plain = build_package(make(), title="제목", body=body, tags=("태그",))
        styled = build_package(make(**NON_DEFAULT), title="제목", body=body, tags=("태그",))
        self.assertEqual(plain, styled, "새 항목은 아직 변환에 쓰이지 않는다(초안 만들기 묶음에서 쓴다)")


class StoredShapeTest(unittest.TestCase):
    def test_the_allowed_keys_are_the_old_ones_plus_exactly_the_eight_new_ones(self):
        self.assertEqual(set(profiles._KEYS), set(OLD_KEYS) | set(NEW_KEYS))
        self.assertEqual(len(profiles._KEYS), 17 + 8)
        self.assertEqual(set(profiles._NEW_KEYS), set(NEW_KEYS))
        self.assertEqual({item.name for item in dataclasses.fields(NaverProfile)}, set(profiles._KEYS))

    def test_a_new_option_appears_in_the_stored_shape_only_when_it_differs_from_its_default(self):
        for name, value in NON_DEFAULT.items():
            with self.subTest(name=name):
                data = make(**{name: value}).to_dict()
                self.assertEqual(set(data) - set(make().to_dict()), {name})
                self.assertEqual(data[name], list(value) if isinstance(value, tuple) else value)
                again = make(**{name: profiles._NEW_DEFAULTS[name]}).to_dict()
                self.assertNotIn(name, again, "기본값을 일부러 적어 주어도 저장 모양에는 나타나지 않는다")

    def test_every_option_set_at_once_round_trips_through_json_text(self):
        profile = make(**NON_DEFAULT)
        data = profile.to_dict()
        self.assertEqual(set(data), set(OLD_KEYS) | set(NEW_KEYS))
        self.assertEqual(data["excluded_topics"], ["주식", "코인"])
        back = NaverProfile.from_dict(json.loads(json.dumps(data, ensure_ascii=False)))
        self.assertEqual(back, profile)
        self.assertEqual(back.to_dict(), data)

    def test_the_new_keys_are_accepted_when_reading_and_other_unknown_keys_are_still_refused(self):
        self.assertEqual(NaverProfile.from_dict({**GOOD, **{name: (list(value) if isinstance(value, tuple) else value) for name, value in NON_DEFAULT.items()}}), make(**NON_DEFAULT))
        for bad in ({**GOOD, "비밀": "x"}, {**GOOD, "intro_stile": "x"}, {**GOOD, "subheading": 3}, {**GOOD, "reuse_days": 90}, {**GOOD, "excluded": []}, {**GOOD, "type": "정보형"}):
            with self.subTest(bad=sorted(set(bad) - set(GOOD))):
                with self.assertRaises(AppError) as caught:
                    NaverProfile.from_dict(bad)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_the_stored_shape_has_no_secrets(self):
        text = repr(make(**NON_DEFAULT).to_dict()).lower()
        for needle in ("password", "token", "cookie", "secret", "session"):
            self.assertNotIn(needle, text)


class ValidationTest(unittest.TestCase):
    def refuses(self, **changes):
        with self.assertRaises(AppError) as caught:
            make(**changes)
        self.assertEqual(caught.exception.code, "CONTENT_INVALID", changes)
        return caught.exception

    def test_the_style_notes_are_one_short_line_and_may_be_empty(self):
        for field in ("intro_style", "difficulty", "ending_style"):
            with self.subTest(field=field):
                self.assertEqual(getattr(make(**{field: "한 줄"}), field), "한 줄")
                self.assertEqual(getattr(make(**{field: ""}), field), "")
                self.assertEqual(len(getattr(make(**{field: "가" * 200}), field)), 200)
                self.assertEqual(getattr(make(**{field: "  앞뒤 공백  "}), field), "앞뒤 공백")
                for bad in ("가" * 201, "줄\n바꿈", "겹친  공백", "숨은​글자", "널\x00문자", 5, None, ["글"]):
                    self.refuses(**{field: bad})

    def test_the_subheading_range_is_whole_numbers_from_1_to_20_with_the_low_end_not_above_the_high_end(self):
        self.assertEqual(MAX_SUBHEADINGS, 20)
        for low, high in ((1, 1), (1, 20), (20, 20), (3, 5), (5, 5), (2, 9)):
            with self.subTest(low=low, high=high):
                profile = make(subheading_min=low, subheading_max=high)
                self.assertEqual((profile.subheading_min, profile.subheading_max), (low, high))
        for low, high in ((0, 5), (-1, 5), (3, 21), (21, 21), (5, 4), (6, 5), (20, 19)):
            with self.subTest(low=low, high=high):
                self.refuses(subheading_min=low, subheading_max=high)
        for bad in (True, False, 3.0, "3", None, [3]):
            with self.subTest(bad=repr(bad)):
                self.refuses(subheading_min=bad)
                self.refuses(subheading_max=bad)
        self.refuses(subheading_min=6)                         # 높은 쪽(기본 5)보다 큰 하한만 따로 줄 수는 없다
        self.refuses(subheading_max=2)                         # 낮은 쪽(기본 3)보다 작은 상한만 따로 줄 수는 없다

    def test_excluded_topics_follow_the_same_rules_as_the_other_word_lists(self):
        words = tuple(f"주제{index}" for index in range(MAX_EXCLUDED))
        self.assertEqual(make(excluded_topics=words).excluded_topics, words)
        self.assertEqual(make(excluded_topics=["  앞뒤 "]).excluded_topics, ("앞뒤",))
        self.assertEqual(make(excluded_topics=["가" * MAX_PHRASE]).excluded_topics, ("가" * MAX_PHRASE,))
        for bad in (words + ("하나 더",), ["가" * (MAX_PHRASE + 1)], ["", "가"], ["가", "가"], ["Abc", "aBC"], "문자열 하나", "가나다", [5], 5, None, ["줄\n바꿈"]):
            with self.subTest(bad=str(bad)[:30]):
                self.refuses(excluded_topics=bad)

    def test_the_limits_of_the_word_lists_and_lines_are_these_literal_numbers(self):
        """상수를 불러다 쓰는 시험은 상수가 몰래 바뀌면 같이 바뀐다 — 경계를 글자 그대로의 숫자로도 지킨다."""
        self.assertEqual((MAX_EXCLUDED, MAX_PHRASE, MAX_SUBHEADINGS, MAX_REUSE_DAYS), (100, 60, 20, 3650))
        self.assertEqual(len(make(excluded_topics=[f"주제{index}" for index in range(100)]).excluded_topics), 100)
        self.refuses(excluded_topics=[f"주제{index}" for index in range(101)])
        self.assertEqual(len(make(excluded_topics=["가" * 60]).excluded_topics[0]), 60)
        self.refuses(excluded_topics=["가" * 61])
        self.assertEqual(len(make(intro_style="가" * 200).intro_style), 200)
        self.refuses(intro_style="가" * 201)

    def test_excluded_topics_take_only_lists_and_tuples_because_a_set_or_dict_has_no_fixed_order(self):
        for bad in ({"주식"}, frozenset({"주식"}), {"주식": 1}, (word for word in ("주식",)), iter(("주식",)), range(1)):
            with self.subTest(bad=repr(bad)[:30]):
                self.refuses(excluded_topics=bad)
        self.assertEqual(make(excluded_topics=("주식", "코인")).excluded_topics, ("주식", "코인"))
        self.assertEqual(make(excluded_topics=["주식"]).excluded_topics, ("주식",))
        self.assertEqual(make(default_tags={"가"}).default_tags, ("가",), "예전 칸(기본 태그)은 예전처럼 어떤 묶음도 받는다 — 옛 프로필이 그대로 읽혀야 한다")

    DANGEROUS = ("<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<iframe src=x>", "<style>", "<form action=x>", "<b>굵게</b>", "<br/>", "{% if x %}", "{{ x }}", "javascript:alert(1)",
                 "vbscript:x", "text onclick=alert(1)", "<svg onload=x>", "<!-- 주석 -->")
    FINE = ("Map<String, List<Integer>> 쓰기", "JavaScript: 비동기 설명", "3 < 5 비교", "a<b 비교", "가격 > 100만원", "C# 과 C++")

    def test_the_new_text_fields_refuse_dangerous_tags_scripts_and_template_marks(self):
        for field in ("intro_style", "difficulty", "ending_style"):
            for bad in self.DANGEROUS:
                with self.subTest(field=field, bad=bad):
                    self.refuses(**{field: bad})
            for fine in self.FINE:
                with self.subTest(field=field, fine=fine):
                    self.assertEqual(getattr(make(**{field: fine}), field), fine)
        for bad in self.DANGEROUS:
            with self.subTest(excluded=bad):
                self.refuses(excluded_topics=["정상", bad])
        for fine in self.FINE:
            self.assertEqual(make(excluded_topics=[fine]).excluded_topics, (fine,))

    def test_the_old_text_fields_keep_their_old_rules_so_an_old_profile_still_reads(self):
        """예전 칸(주제·대상 독자·말투·대표 이미지 규격·발행 주기)은 이번에 규칙을 바꾸지 않았다 — 이미 저장된 프로필이 다시 읽히지 않으면 안 된다."""
        for field in ("topic", "audience", "tone", "image_spec", "publish_cycle"):
            self.assertEqual(getattr(make(**{field: "<b>x</b> {{ y }}"}), field), "<b>x</b> {{ y }}")

    def test_the_reuse_window_is_a_whole_number_of_days_from_0_to_3650(self):
        self.assertEqual(MAX_REUSE_DAYS, 3650)
        for good in (0, 1, 30, 90, 3650):
            self.assertEqual(make(topic_reuse_days=good).topic_reuse_days, good)
        for bad in (-1, 3651, True, False, 90.0, "90", None, [90]):
            with self.subTest(bad=repr(bad)):
                self.refuses(topic_reuse_days=bad)

    def test_the_default_post_type_is_one_of_the_five_types(self):
        self.assertEqual(POST_TYPES, ("정보형", "비교형", "문제 해결형", "제품·서비스 소개형", "장소·업체 정보형"))
        for kind in POST_TYPES:
            self.assertEqual(make(post_type=kind).post_type, kind)
        for bad in ("경험형 후기", "후기", "방문 후기", "", "정보형 ", "info", None, 5, ["정보형"]):
            with self.subTest(bad=repr(bad)):
                self.refuses(post_type=bad)

    def test_a_profile_with_the_new_options_is_still_unchangeable_and_hashable(self):
        profile = make(**NON_DEFAULT)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            profile.post_type = "정보형"
        self.assertEqual(hash(profile), hash(make(**{**NON_DEFAULT, "excluded_topics": ["주식", "코인"]})))
        changed = dataclasses.replace(profile, post_type="장소·업체 정보형")
        self.assertEqual((changed.post_type, changed.topic_reuse_days, changed.excluded_topics), ("장소·업체 정보형", 30, ("주식", "코인")))
        with self.assertRaises(AppError):
            dataclasses.replace(profile, subheading_max=1)       # 바꿔도 검사를 다시 거친다(하한 2 > 상한 1)


if __name__ == "__main__":
    unittest.main()
