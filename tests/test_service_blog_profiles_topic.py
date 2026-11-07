"""블로그 프로필 쓰기 서비스(`service/blog_profiles.py`)의 **주제 설정 세 칸**(우선 키워드·제외 키워드·선호 글 유형 — P4c, 변경 등급 T2) 시험. **전부 임시 폴더**(이 PC 의 실제 데이터 폴더·설정 파일에는 쓰지 않는다).
옛 시험(`test_service_blog_profiles`)이 쓰기 안전 전체(원자적 저장·사본·잠금·동시 저장 …)를 이미 확인하므로 여기서는 **새 칸이 그 길 위에서 똑같이 안전한가**를 본다.

지키는 것:
  1) 칸 목록: 폼 칸은 모든 슬롯 17개(네이버 A·B 는 후보 만들기까지 18개)이고 키 모양 검사 대상 글 칸은 13개다 — 시험이 자기 상수를 돌려 쓰지 않도록 **칸 이름을 직접 적어** 못박는다(목록에서 한 칸이 빠지면 그 칸에는 비밀 모양이 그대로 저장된다).
     지역 칸 둘(`home_regions`·`day_trip_regions`)은 여전히 폼 칸이 아니다.
  2) 판정: 개수·낱말 길이·공백·대소문자 중복·위험한 표기·글 유형 중복·목록 밖은 서비스 생성자(`ChannelProfile`)와 같다(서비스는 생성자를 심판으로 쓴다).
  3) **칸 사이 규칙**(우선과 제외에 같은 낱말 금지): 한 칸만 바꿔 저장된 다른 칸과 겹쳐도·두 칸을 함께 바꿔 서로 겹쳐도 **두 칸 모두**에 `overlap` 을 붙여 거절하고 아무것도 쓰지 않는다. 두 칸을 함께 바꾸는 **옳은 요청**(바꿔치기)은 거짓으로 거절되지 않는다.
  4) 키 모양 글은 쓰기 전에 **칸 이름을 알려** 거절하고(아무것도 안 쓰고 입력한 글을 되풀이하지 않는다) 키 모양이 든 파일은 읽히지 않는다.
  5) 저장 전후 JSON 의 **키 단위 차이는 그 슬롯의 그 칸뿐**이다(손으로 고친 판 2 파일 — 엔진 칸·지역 칸·다른 슬롯·손으로 켠 값은 보존). 판 1 파일은 이 칸이 빈 기본값으로 읽히고 첫 저장이 옛 모양 사본을 남기며 올린다.
  6) 복제는 새 칸도 복사하고 새 칸 하나만 있어도 슬롯은 '비어 있지 않다'(덮어쓰지 않는다). 삭제는 새 칸을 기본값으로 되돌리되 지역 칸·엔진 칸은 그대로 둔다.
  7) 쓰기 중간에 실패해도(대표 둘: 본 파일 임시 파일 쓰는 중·이름 바꾼 직후 되읽기 불일치) 직전 값이 보존되고 임시·잠금 파일이 남지 않는다.
"""
import dataclasses
import itertools
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.topicdb import backup as tbackup  # noqa: E402
from chanceblog_desktop.topics import channels, layout  # noqa: E402
from test_service_blog_profiles import REAL, Injector, writing_error  # noqa: E402,I001

KEY_SHAPES = {"aws": "AK" + "IA" + "ABCDEFGHIJKLMNOP", "slack": "xo" + "xb-" + "1234567890-ABCDEF", "pem": "-----BEGIN " + "PRIVATE KEY-----"}      # 키 모양의 가짜 값(낱말 하나의 한도 30자 안에 들어가는 것) — 조각으로 나눠 적어 저장소에 키 문자열이 없다
THREE = ("priority_keywords", "exclude_keywords", "preferred_post_types")
TOPIC = {"priority_keywords": ("예시 키워드 하나", "예시 키워드 둘"), "exclude_keywords": ("예시 제외어",), "preferred_post_types": ("정보형", "비교형")}      # 가짜 낱말만 — 실제 키워드가 아니다
POST_TYPES = ("정보형", "비교형", "문제 해결형", "제품·서비스 소개형", "장소·업체 정보형")      # 서비스의 `POST_TYPES` 와 같은 다섯 — 시험이 직접 적어 서비스 상수를 돌려 쓰지 않는다
EDITED_NAME = "손으로 쓴 별명"


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(tmp.name)
        self.paths = tf.topic_paths(self.ctx.workspace)
        self.root = Path(self.ctx.workspace.root)

    def snap(self):
        return bp.read_snapshot(self.ctx)

    def by_key(self):
        return {profile.key: profile for profile in self.snap().profiles}

    def tree(self):
        return ss.tree_snapshot(self.root)

    def leftovers(self):
        return sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file() and (path.name.endswith(".tmp") or path.name.endswith(".lock")))

    def save(self, key="naver_a", fields=None, **changes):
        fields = {"display_name": "예시 블로그 가", "blog_ref": "example-blog-a", **TOPIC} if fields is None else dict(fields)
        fields.update(changes)
        return bp.save_slot(self.ctx, key, fields, expected_version=self.snap().version)

    def put_profiles(self, mutate):
        """사람이 JSON 을 고친 것처럼 파일을 미리 만들어 둔다."""
        profiles = mutate(channels.default_profiles())
        self.paths.folder.mkdir(parents=True, exist_ok=True)
        self.paths.profiles.write_text(json.dumps(channels.profiles_to_dict(profiles), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def hand_edited(self):
        """손으로 고친 판 2 파일 — 엔진 칸·지역 칸·손으로 켠 값·다른 슬롯의 주제 설정 값이 모두 들어 있다."""
        def tweak(profiles):
            out = []
            for profile in profiles:
                if profile.key == "naver_a":
                    profile = dataclasses.replace(profile, top_n=9, cluster_cap=3, history_enabled=False, home_regions=("예시 지역 하나",), day_trip_regions=("예시 지역 둘",),
                                                  monetization_focus=("small_appliance", "my_custom_tag"), alias=EDITED_NAME)
                elif profile.key == "naver_b":
                    profile = dataclasses.replace(profile, top_n=7, priority_keywords=("예시 B 우선",), exclude_keywords=("예시 B 제외",), preferred_post_types=("문제 해결형",))
                elif profile.key == "blogger_ko":
                    profile = dataclasses.replace(profile, generation_enabled=True, priority_keywords=("예시 C 우선",))
                out.append(profile)
            return tuple(out)

        self.put_profiles(tweak)


def key_diff(before, after):
    """저장 전후 JSON 의 키 단위 차이 `{(슬롯, 칸)}` — 바뀐 칸만."""
    assert [item["key"] for item in before["profiles"]] == [item["key"] for item in after["profiles"]]
    found = set()
    for old, new in zip(before["profiles"], after["profiles"], strict=True):
        for name in set(old) | set(new):
            if old.get(name) != new.get(name):
                found.add((old["key"], name))
    return found


# ---- 1) 칸 목록 못박기 ----------------------------------------------------------------------------------------------------------------
class FieldListsTest(unittest.TestCase):
    def test_the_form_fields_are_pinned_by_name_seventeen_for_every_slot_and_eighteen_for_naver(self):
        common = ("display_name", "blog_ref", "language", "alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "color_preset", "profile_image", "cover_image",
                  "monetization_focus", "priority_keywords", "exclude_keywords", "preferred_post_types")
        self.assertEqual(bp.COMMON_FIELDS, common)
        self.assertEqual(len(set(common)), 17)
        for key in ("github_pages", "blogger_en", "blogger_ko"):
            self.assertEqual(bp.form_fields(key), common, key)
        for key in ("naver_a", "naver_b"):
            self.assertEqual(bp.form_fields(key), common + ("generation_enabled",), key)
            self.assertEqual(len(bp.form_fields(key)), 18)

    def test_the_key_shape_checked_fields_are_the_thirteen_text_fields_and_everything_else_is_a_fixed_list(self):
        """목록에서 칸이 빠지면 그 칸에 비밀 모양이 저장된다 — 글 칸 열세 개를 이름으로 못박고, 폼 칸 중 목록에 **없는** 칸은 고정 목록·스위치뿐임을 반대쪽에서도 못박는다."""
        self.assertEqual(bp.TEXT_FIELDS, ("display_name", "blog_ref", "alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "profile_image", "cover_image", "priority_keywords", "exclude_keywords"))
        self.assertEqual(len(bp.TEXT_FIELDS), 13)
        self.assertEqual(set(bp.COMMON_FIELDS) - set(bp.TEXT_FIELDS), {"language", "color_preset", "monetization_focus", "preferred_post_types"}, "키 모양 검사에 없는 폼 칸은 정해진 값을 고르는 칸뿐이다")
        self.assertLessEqual(set(bp.TEXT_FIELDS), set(bp.COMMON_FIELDS))
        self.assertEqual(bp.KEYWORD_FIELDS, ("priority_keywords", "exclude_keywords"))
        self.assertLessEqual(set(bp.KEYWORD_FIELDS), set(bp.TEXT_FIELDS))

    def test_the_two_region_fields_and_the_engine_fields_are_still_not_form_fields(self):
        names = {field.name for field in dataclasses.fields(channels.ChannelProfile)}
        outside = {"home_regions", "day_trip_regions", "history_enabled", "weights", "top_n", "cluster_cap", "subheading_min", "trend_use", "dup_cutoffs", "topic_clusters", "expansion_directions", "evergreen_pct",
                   "realtime_pct", "key"}
        self.assertLessEqual(outside, names)
        for key in bp.SLOTS:
            self.assertEqual(set(bp.form_fields(key)) & outside, set(), key)
            self.assertLessEqual(set(bp.form_fields(key)), names, key)

    def test_the_post_type_names_are_the_services(self):
        self.assertEqual(channels.POST_TYPES, POST_TYPES, "시험이 직접 적은 다섯 이름이 서비스의 것과 같다 — 화면이 이 이름을 칩 이름으로 그대로 쓴다")


# ---- 2) 판정 — 서비스 생성자와 같다 -------------------------------------------------------------------------------------------------------
BASE = bp.default_profile("naver_a")


def constructor_rejects(**changes):
    try:
        dataclasses.replace(BASE, **changes)
    except AppError as error:
        if error.requested_code != "CONTENT_INVALID":
            raise
        return True
    return False


def service_rejects(name, value):
    try:
        bp.apply_fields(BASE, {name: value})
    except bp.ProfileProblems as error:
        assert error.problems == {name: "invalid"}, error.problems
        return True
    return False


class VerdictTest(unittest.TestCase):
    def words(self, count, size=3):
        return tuple(f"{'가' * size}{index}" for index in range(count))

    def keyword_cases(self):
        zero = chr(0x200B)
        return [(), ("가",), ("가", "나"), ["가", "나"], ("A", "a"), ("가", "가"), self.words(20), self.words(21), ("가" * 30,), ("가" * 31,), ("  가",), ("가  나",), ("가\n나",), ("",), ("   ",), ("<b>x</b>",), ("javascript: x",),
                ("JavaScript:alert(1)",), ("{{템플릿}}",), ("{% x %}",), ("onclick=run()",), ("a<b 비교",), ("Map<String, List<Integer>>",), (f"보이지{zero}않는",), ("가 나",), ("숙박·여행",), "가", "가, 나", {"가"}, {"가": 1}, None, 3, ("가", 3),
                ("가", None), b"abc"]

    def test_the_two_keyword_fields_are_judged_like_the_constructor(self):
        for name in bp.KEYWORD_FIELDS:
            for value in self.keyword_cases():
                with self.subTest(field=name, value=repr(value)[:30]):
                    self.assertEqual(service_rejects(name, value), constructor_rejects(**{name: value}))

    def test_the_documented_keyword_limits_are_what_the_service_enforces(self):
        """생성자와 견주는 것과 별개로 **규칙을 직접 적어** 못박는다 — 20개까지·낱말마다 30자까지·같은 낱말(대소문자 무시) 불가·빈 낱말 불가·글 한 줄·위험한 표기 불가."""
        self.assertEqual((channels.MAX_KEYWORDS, channels.MAX_KEYWORD_WORD), (20, 30))
        for name in bp.KEYWORD_FIELDS:
            ok = bp.apply_fields(BASE, {name: self.words(20, 5)})
            self.assertEqual(len(getattr(ok, name)), 20)
            self.assertTrue(service_rejects(name, self.words(21)), "21개")
            self.assertEqual(getattr(bp.apply_fields(BASE, {name: ("가" * 30,)}), name), ("가" * 30,), "30자")
            self.assertTrue(service_rejects(name, ("가" * 31,)), "31자")
            self.assertTrue(service_rejects(name, ("Abc", "aBC")), "대소문자만 다른 같은 낱말")
            self.assertTrue(service_rejects(name, ("",)), "빈 낱말")
            self.assertTrue(service_rejects(name, ("가  나",)), "낱말 안의 겹 공백(한 줄로 다듬은 글이 아니다)")
            self.assertTrue(service_rejects(name, ("<b>가</b>",)), "HTML 태그")
            self.assertEqual(getattr(bp.apply_fields(BASE, {name: ("  가 ",)}), name), ("가",), "앞뒤 공백은 다듬어 받는다")
            self.assertTrue(service_rejects(name, "가, 나"), "글 한 줄은 낱말 목록이 아니다")

    def test_the_post_types_are_judged_like_the_constructor_and_only_the_five_names_once_each(self):
        cases = [(), ("정보형",), ("비교형", "정보형"), POST_TYPES, list(POST_TYPES[:2]), ("정보형", "정보형"), ("후기형",), ("정보형", "후기형"), ("",), ("정보형 ",), ("정보 형",), "정보형", {"정보형"}, None, 3, ("정보형", 3), POST_TYPES + ("정보형",),
                 tuple(reversed(POST_TYPES))]
        for value in cases:
            with self.subTest(value=repr(value)[:30]):
                self.assertEqual(service_rejects("preferred_post_types", value), constructor_rejects(preferred_post_types=value))
        for size in range(len(POST_TYPES) + 1):
            for combo in itertools.combinations(POST_TYPES, size):
                self.assertEqual(bp.apply_fields(BASE, {"preferred_post_types": combo}).preferred_post_types, combo, "다섯 중 중복 없이 어느 조합이든 — 받은 순서 그대로 저장한다")
        self.assertTrue(service_rejects("preferred_post_types", ("정보형", "정보형")))
        self.assertTrue(service_rejects("preferred_post_types", ("후기형",)), "경험담·후기는 글 유형이 아니다 — 목록 밖 값은 거절")

    def test_all_three_fields_default_to_empty_and_an_empty_value_is_fine(self):
        for name in THREE:
            self.assertEqual(getattr(BASE, name), ())
            self.assertEqual(getattr(bp.apply_fields(BASE, {name: ()}), name), ())

    def test_several_wrong_fields_are_all_reported_together_by_name(self):
        with self.assertRaises(bp.ProfileProblems) as caught:
            bp.apply_fields(BASE, {"priority_keywords": ("가" * 31,), "exclude_keywords": ("나", "나"), "preferred_post_types": ("후기형",), "alias": "가" * 99})
        self.assertEqual(caught.exception.problems, {"priority_keywords": "invalid", "exclude_keywords": "invalid", "preferred_post_types": "invalid", "alias": "invalid"})


# ---- 3) 칸 사이 규칙: 우선과 제외에 같은 낱말 금지 ------------------------------------------------------------------------------------------
class OverlapRuleTest(unittest.TestCase):
    POOL = ("가", "나", "Abc", "aBC", "ß", "SS", "İ", "i" + chr(0x307), "ǆ", "ǅ", "Σ", "ς", "ﬁ", "fi")      # 대소문자 구분 없이(`casefold`) 같아지는 어려운 쌍(독일어 ß·터키어 İ·그리스어 시그마·합자 ﬁ 등)을 일부러 넣었다

    def lists(self):
        found = []
        for size in (0, 1, 2):
            for combo in itertools.combinations(self.POOL, size):
                if len({word.casefold() for word in combo}) == len(combo):                  # 한 목록 안의 중복은 다른 규칙이라 걸러 낸다 — 여기서는 칸 사이 규칙만 본다
                    found.append(combo)
        return found

    def test_the_overlap_rule_is_judged_like_the_constructor_for_thousands_of_pairs(self):
        lists = self.lists()
        self.assertGreater(len(lists) ** 2, 5000)
        mismatch = []
        for priority, exclude in itertools.product(lists, lists):
            expected = constructor_rejects(priority_keywords=priority, exclude_keywords=exclude)
            mine = bp.keywords_overlap(BASE, {"priority_keywords": priority, "exclude_keywords": exclude})
            if mine != expected:
                mismatch.append((priority, exclude, mine, expected))
        self.assertEqual(mismatch[:5], [], "서비스의 겹침 판정이 생성자와 다른 쌍")

    def test_an_overlap_is_reported_on_both_fields_and_a_clean_pair_is_applied(self):
        lists = self.lists()
        for priority, exclude in itertools.islice(itertools.product(lists, lists), 0, None, 37):
            fields = {"priority_keywords": priority, "exclude_keywords": exclude}
            if constructor_rejects(**fields):
                with self.assertRaises(bp.ProfileProblems) as caught:
                    bp.apply_fields(BASE, fields)
                self.assertEqual(caught.exception.problems, {"priority_keywords": "overlap", "exclude_keywords": "overlap"})
            else:
                done = bp.apply_fields(BASE, fields)
                self.assertEqual((done.priority_keywords, done.exclude_keywords), (priority, exclude))

    def test_a_pair_that_is_checked_against_the_stored_other_field_uses_the_stored_value(self):
        stored = dataclasses.replace(BASE, priority_keywords=("가", "Abc"), exclude_keywords=("나",))
        for fields, rejected in (({"exclude_keywords": ("가",)}, True), ({"exclude_keywords": ("aBC",)}, True), ({"exclude_keywords": ("나", "다")}, False), ({"priority_keywords": ("나",)}, True),
                                 ({"priority_keywords": ("다",)}, False), ({"alias": "다른 별명"}, False), ({}, False)):
            with self.subTest(fields=fields):
                if rejected:
                    with self.assertRaises(bp.ProfileProblems) as caught:
                        bp.apply_fields(stored, fields)
                    self.assertEqual(caught.exception.problems, {"priority_keywords": "overlap", "exclude_keywords": "overlap"})
                else:
                    self.assertEqual(bp.apply_fields(stored, fields).alias, fields.get("alias", ""))

    def test_swapping_words_between_the_two_fields_in_one_request_is_not_refused_by_the_stored_value(self):
        """P4c 가 새로 만들 뻔한 결함 — 칸을 하나씩 저장된 다른 칸과 견주면 옳은 요청(우선에서 `가` 를 빼고 제외에 `가` 를 넣기)이 거짓으로 거절된다."""
        stored = dataclasses.replace(BASE, priority_keywords=("가", "나"), exclude_keywords=("다",))
        with self.assertRaises(AppError, msg="생성자는 저장된 우선과 겹치는 한 칸만의 변경을 거절한다 — 칸을 하나씩 이 모양으로 견주면 아래 옳은 요청도 거절된다"):
            dataclasses.replace(stored, exclude_keywords=("가",))
        done = bp.apply_fields(stored, {"priority_keywords": ("나",), "exclude_keywords": ("다", "가")})
        self.assertEqual((done.priority_keywords, done.exclude_keywords), (("나",), ("다", "가")), "함께 바꾸면 최종 값이 겹치지 않으니 받는다")
        swapped = bp.apply_fields(stored, {"priority_keywords": ("다",), "exclude_keywords": ("가", "나")})
        self.assertEqual((swapped.priority_keywords, swapped.exclude_keywords), (("다",), ("가", "나")))

    def test_a_wrong_field_is_reported_as_invalid_and_the_overlap_waits_until_the_fields_are_fine(self):
        with self.assertRaises(bp.ProfileProblems) as caught:
            bp.apply_fields(BASE, {"priority_keywords": ("가" * 31, "x"), "exclude_keywords": ("x",)})
        self.assertEqual(caught.exception.problems, {"priority_keywords": "invalid"})

    def test_the_overlap_error_carries_the_field_names_and_never_the_words(self):
        with self.assertRaises(bp.ProfileProblems) as caught:
            bp.apply_fields(BASE, {"priority_keywords": ("예시 겹침 낱말",), "exclude_keywords": ("예시 겹침 낱말",)})
        error = caught.exception
        self.assertEqual(error.code, "CONTENT_INVALID")
        shown = repr(error.problems) + str(error) + error.detail + error.log_line() + repr(error.slots)
        self.assertNotIn("예시 겹침 낱말", shown)
        self.assertIn("우선 키워드", repr(error.slots))
        self.assertIn("제외 키워드", repr(error.slots))


# ---- 4) 키 모양 --------------------------------------------------------------------------------------------------------------------------
class KeyShapeTest(Base):
    def test_a_key_shaped_keyword_is_refused_by_field_name_and_nothing_is_written(self):
        self.save()
        before, listing = self.tree(), sorted(str(path) for path in self.tmp.rglob("*"))
        for name in bp.KEYWORD_FIELDS:
            for label, shape in KEY_SHAPES.items():
                for words in ((shape,), ("예시 낱말", shape)):
                    with self.subTest(field=name, shape=label, words=len(words)):
                        with self.assertRaises(bp.ProfileProblems) as caught:
                            bp.save_slot(self.ctx, "naver_a", {name: words}, expected_version=self.snap().version)
                        self.assertEqual(caught.exception.problems, {name: "key_shape"})
                        self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                        shown = repr(caught.exception.problems) + str(caught.exception) + caught.exception.detail + caught.exception.log_line() + repr(caught.exception.slots)
                        self.assertNotIn(shape, shown, "오류에 입력한 값이 없다")
        self.assertEqual(self.tree(), before)
        self.assertEqual(sorted(str(path) for path in self.tmp.rglob("*")), listing, "잠금도 임시 파일도 만들지 않았다")

    def test_a_key_shape_inside_a_longer_phrase_is_refused_too(self):
        self.save()
        before = self.tree()
        for name in bp.KEYWORD_FIELDS:
            with self.assertRaises(bp.ProfileProblems) as caught:
                bp.save_slot(self.ctx, "naver_a", {name: ("예시 " + KEY_SHAPES["aws"],)}, expected_version=self.snap().version)
            self.assertEqual(caught.exception.problems, {name: "key_shape"})
        self.assertEqual(self.tree(), before)

    def test_a_too_long_key_shaped_word_is_refused_as_too_long_and_never_stored(self):
        """낱말 하나의 한도(30자)를 넘는 긴 키 모양(예: 40자 토큰)은 키 모양 검사에 닿기 전에 '틀린 값' 으로 거절된다 — 어느 쪽이든 저장되지 않는다."""
        self.save()
        before = self.tree()
        longer = "gh" + "p_" + "A" * 36
        for name in bp.KEYWORD_FIELDS:
            with self.assertRaises(bp.ProfileProblems) as caught:
                bp.save_slot(self.ctx, "naver_a", {name: (longer,)}, expected_version=self.snap().version)
            self.assertEqual(caught.exception.problems, {name: "invalid"})
        self.assertEqual(self.tree(), before)

    def test_a_hand_edited_file_with_a_key_shaped_keyword_is_not_read_and_a_post_type_cannot_hold_one(self):
        for name in bp.KEYWORD_FIELDS:
            poisoned = tuple(dataclasses.replace(profile, **{name: (KEY_SHAPES["aws"],)}) if profile.key == "naver_a" else profile for profile in channels.default_profiles())
            self.paths.folder.mkdir(parents=True, exist_ok=True)
            self.paths.profiles.write_text(json.dumps(channels.profiles_to_dict(poisoned)), encoding="utf-8")
            self.assertEqual(code_of(bp.read_snapshot, self.ctx), "CONTENT_INVALID", name)
        self.assertEqual(code_of(bp.save_slot, self.ctx, "naver_a", {"alias": "x"}, expected_version="x" * 64), "CONTENT_INVALID", "틀린 파일 위에는 쓰지 않는다")
        self.assertEqual(tbackup.PROFILE_TEXT_KEYS.count("priority_keywords") + tbackup.PROFILE_TEXT_KEYS.count("exclude_keywords"), 2, "읽을 때의 키 모양 검사에도 두 글 칸이 들어 있다")
        self.assertNotIn("preferred_post_types", tbackup.PROFILE_TEXT_KEYS)
        for shape in KEY_SHAPES.values():
            self.assertTrue(constructor_rejects(preferred_post_types=(shape,)), "선호 글 유형은 다섯 이름뿐이라 키 모양이 들어갈 수 없다")


# ---- 5) 저장 전후 JSON 의 키 단위 차이 --------------------------------------------------------------------------------------------------------
class SaveDiffTest(Base):
    def read_json(self):
        return json.loads(self.paths.profiles.read_text(encoding="utf-8"))

    def test_a_save_of_the_three_fields_changes_only_those_keys_of_that_slot_in_a_hand_edited_version_two_file(self):
        self.hand_edited()
        before = self.read_json()
        saved = bp.save_slot(self.ctx, "naver_a", dict(TOPIC), expected_version=self.snap().version)
        self.assertEqual((saved.kind, saved.changed), ("saved", ("naver_a",)))
        after = self.read_json()
        self.assertEqual(key_diff(before, after), {("naver_a", name) for name in THREE}, "바뀐 것은 그 슬롯의 세 칸뿐 — 엔진 칸·지역·손으로 켠 값·다른 슬롯은 그대로")
        mine = next(item for item in after["profiles"] if item["key"] == "naver_a")
        self.assertEqual((mine["priority_keywords"], mine["exclude_keywords"], mine["preferred_post_types"]), (list(TOPIC["priority_keywords"]), list(TOPIC["exclude_keywords"]), list(TOPIC["preferred_post_types"])))
        self.assertEqual((mine["top_n"], mine["cluster_cap"], mine["history_enabled"], mine["home_regions"], mine["day_trip_regions"], mine["alias"]),
                         (9, 3, False, ["예시 지역 하나"], ["예시 지역 둘"], EDITED_NAME))
        self.assertEqual(mine["monetization_focus"], ["small_appliance", "my_custom_tag"], "목록 밖 협찬 분야도 보존")
        self.assertEqual({item["key"]: item["generation_enabled"] for item in after["profiles"]}["blogger_ko"], True, "손으로 켠 Blogger 후보 생성 값도 보존")
        self.assertEqual(after["schema"], 2)

    def test_each_of_the_three_fields_changes_only_its_own_key(self):
        for name, value in (("priority_keywords", ("예시 우선 하나",)), ("exclude_keywords", ("예시 제외 하나",)), ("preferred_post_types", ("장소·업체 정보형",))):
            with self.subTest(field=name):
                self.hand_edited()
                before = self.read_json()
                bp.save_slot(self.ctx, "naver_a", {name: value}, expected_version=self.snap().version)
                self.assertEqual(key_diff(before, self.read_json()), {("naver_a", name)})

    def test_every_slot_can_hold_the_three_fields_and_saving_one_slot_never_touches_another(self):
        for key in bp.SLOTS:
            with self.subTest(slot=key):
                self.hand_edited()
                before = self.read_json()
                bp.save_slot(self.ctx, key, {"priority_keywords": ("예시 우선",), "preferred_post_types": ("비교형",)}, expected_version=self.snap().version)
                after = self.read_json()
                self.assertEqual({slot for slot, _name in key_diff(before, after)}, {key})
                self.assertEqual({name for _slot, name in key_diff(before, after)}, {"priority_keywords", "preferred_post_types"})

    def test_a_hand_edited_file_shows_the_three_values_and_saving_another_field_keeps_them(self):
        self.hand_edited()
        by_key = self.by_key()
        self.assertEqual((by_key["naver_b"].priority_keywords, by_key["naver_b"].exclude_keywords, by_key["naver_b"].preferred_post_types), (("예시 B 우선",), ("예시 B 제외",), ("문제 해결형",)))
        self.assertEqual(by_key["blogger_ko"].priority_keywords, ("예시 C 우선",))
        before = self.read_json()
        bp.save_slot(self.ctx, "naver_b", {"alias": "새 별명"}, expected_version=self.snap().version)
        self.assertEqual(key_diff(before, self.read_json()), {("naver_b", "alias")}, "다른 칸을 저장해도 세 칸은 그대로 남는다")

    def test_saved_values_keep_the_given_order_and_a_second_identical_save_writes_nothing(self):
        self.save(priority_keywords=("나", "가", "다"), preferred_post_types=("비교형", "정보형"))
        mine = self.by_key()["naver_a"]
        self.assertEqual((mine.priority_keywords, mine.preferred_post_types), (("나", "가", "다"), ("비교형", "정보형")))
        before, listing = self.tree(), sorted(str(path) for path in self.tmp.rglob("*"))
        again = bp.save_slot(self.ctx, "naver_a", {"priority_keywords": ("나", "가", "다"), "preferred_post_types": ("비교형", "정보형")}, expected_version=self.snap().version)
        self.assertEqual((again.kind, again.changed), ("unchanged", ()))
        self.assertEqual(self.tree(), before)
        self.assertEqual(sorted(str(path) for path in self.tmp.rglob("*")), listing)

    def test_clearing_a_field_by_saving_an_empty_value_works_and_changes_only_that_key(self):
        self.save()
        before = self.read_json()
        bp.save_slot(self.ctx, "naver_a", {"exclude_keywords": ()}, expected_version=self.snap().version)
        self.assertEqual(key_diff(before, self.read_json()), {("naver_a", "exclude_keywords")})
        self.assertEqual(self.by_key()["naver_a"].exclude_keywords, ())

    def test_a_save_of_these_fields_writes_exactly_the_profile_file_and_its_backup(self):
        self.save()
        before = self.tree()
        self.save("naver_a", {"priority_keywords": ("예시 새 우선",)})
        after = self.tree()
        changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
        self.assertEqual(changed, {"topic_engine/channel_profiles.json", "topic_engine/channel_profiles.json.bak"})
        self.assertEqual(self.leftovers(), [])

    def test_a_saved_file_with_the_three_fields_reads_back_and_passes_the_backup_check(self):
        from chanceblog_desktop.service import topics as topic_service
        self.save()
        self.save("naver_b", {"display_name": "예시 블로그 나", "blog_ref": "example-blog-b", "priority_keywords": ("예시 우선 B",), "preferred_post_types": POST_TYPES})
        loaded = {profile.key: profile for profile in tf.load_profiles(self.paths).value}
        self.assertEqual((loaded["naver_a"].priority_keywords, loaded["naver_a"].exclude_keywords, loaded["naver_a"].preferred_post_types), (TOPIC["priority_keywords"], TOPIC["exclude_keywords"], TOPIC["preferred_post_types"]))
        self.assertEqual(loaded["naver_b"].preferred_post_types, POST_TYPES)
        made = topic_service.backup_topics(self.ctx)
        self.assertIn(layout.CHANNEL_PROFILES_FILE, made.files)


# ---- 6) 복제·삭제·비어 있음 --------------------------------------------------------------------------------------------------------------
class CloneClearTest(Base):
    def test_clone_copies_the_three_fields_into_the_empty_slot_and_leaves_the_engine_and_region_fields_to_the_target(self):
        self.hand_edited()
        bp.save_slot(self.ctx, "naver_b", {"priority_keywords": (), "exclude_keywords": (), "preferred_post_types": ()}, expected_version=self.snap().version)      # 손으로 적어 둔 주제 설정을 비워 '비어 있는 슬롯' 으로 만든다(엔진 값 top_n=7 은 남는다)
        self.save("naver_a", {"display_name": "예시 블로그 가", "blog_ref": "example-blog-a", **TOPIC})
        self.assertTrue(bp.is_empty(self.by_key()["naver_b"]))
        cloned = bp.clone_slot(self.ctx, "naver_a", "naver_b", expected_version=self.snap().version)
        by_key = {profile.key: profile for profile in cloned.snapshot.profiles}
        self.assertEqual(cloned.changed, ("naver_b",))
        for name in THREE:
            self.assertEqual(getattr(by_key["naver_b"], name), getattr(by_key["naver_a"], name), name)
        self.assertEqual((by_key["naver_b"].home_regions, by_key["naver_b"].top_n), ((), 7), "지역 칸·엔진 칸은 복사하지 않고 대상 슬롯의 것이 그대로다")
        self.assertEqual(by_key["naver_a"].home_regions, ("예시 지역 하나",), "원본도 그대로")

    def test_clone_works_between_the_blogger_slots_too_and_a_github_slot_has_nowhere_to_go(self):
        self.save("blogger_ko", {"display_name": "예시 블로그 다", "blog_ref": "example-blog-c", "language": "ko", **TOPIC})
        bp.clone_slot(self.ctx, "blogger_ko", "blogger_en", expected_version=self.snap().version)
        by_key = self.by_key()
        for name in THREE:
            self.assertEqual(getattr(by_key["blogger_en"], name), TOPIC[name], name)
        self.save("github_pages", {"display_name": "예시 블로그 라", "blog_ref": "example-blog-d", **TOPIC})
        self.assertIsNone(bp.clone_target(self.snap().profiles, "github_pages"))

    def test_a_slot_with_only_one_of_the_three_fields_set_is_not_empty_so_it_is_not_overwritten(self):
        self.save("naver_a", dict(TOPIC))
        for name, value in (("priority_keywords", ("예시 우선",)), ("exclude_keywords", ("예시 제외",)), ("preferred_post_types", ("정보형",))):
            with self.subTest(field=name):
                self.put_profiles(lambda profiles, name=name, value=value: tuple(dataclasses.replace(p, **{name: value}) if p.key == "naver_b" else p for p in profiles))
                self.assertFalse(bp.is_empty(self.by_key()["naver_b"]), "새 칸 하나만 있어도 비어 있지 않다")
                self.assertIsNone(bp.clone_target(self.snap().profiles, "naver_a"))
                before = self.tree()
                self.assertEqual(code_of(bp.clone_slot, self.ctx, "naver_a", "naver_b", expected_version=self.snap().version), "CONTENT_INVALID", "덮어쓰기 금지")
                self.assertEqual(self.tree(), before)
                self.assertEqual(getattr(self.by_key()["naver_b"], name), value)

    def test_the_empty_check_looks_at_each_of_the_three_fields_separately(self):
        for name, value in (("priority_keywords", ("예시 우선",)), ("exclude_keywords", ("예시 제외",)), ("preferred_post_types", ("정보형",))):
            for key in bp.SLOTS:
                self.assertTrue(bp.is_empty(bp.default_profile(key)))
                self.assertFalse(bp.is_empty(dataclasses.replace(bp.default_profile(key), **{name: value})), (key, name))

    def test_clear_empties_the_three_fields_and_leaves_the_regions_the_engine_values_and_other_slots(self):
        self.hand_edited()
        self.save("naver_a", dict(TOPIC))
        before = json.loads(self.paths.profiles.read_text(encoding="utf-8"))
        cleared = bp.clear_slot(self.ctx, "naver_a", confirmed=True, expected_version=self.snap().version)
        after = json.loads(self.paths.profiles.read_text(encoding="utf-8"))
        by_key = {profile.key: profile for profile in cleared.snapshot.profiles}
        for name in THREE:
            self.assertEqual(getattr(by_key["naver_a"], name), (), name)
        self.assertEqual((by_key["naver_a"].home_regions, by_key["naver_a"].day_trip_regions, by_key["naver_a"].top_n, by_key["naver_a"].history_enabled), (("예시 지역 하나",), ("예시 지역 둘",), 9, False))
        self.assertTrue(bp.is_empty(by_key["naver_a"]))
        self.assertEqual({slot for slot, _name in key_diff(before, after)}, {"naver_a"}, "다른 슬롯은 한 칸도 안 바뀐다")
        self.assertEqual((by_key["naver_b"].priority_keywords, by_key["naver_b"].preferred_post_types), (("예시 B 우선",), ("문제 해결형",)))
        again = bp.clear_slot(self.ctx, "naver_a", confirmed=True, expected_version=cleared.snapshot.version)
        self.assertEqual(again.kind, "unchanged")

    def test_clearing_needs_the_real_confirmation_even_when_only_the_new_fields_are_set(self):
        self.save("naver_a", {"priority_keywords": ("예시 우선",)})
        before = self.tree()
        for value in (False, None, 1, "yes"):
            self.assertEqual(code_of(bp.clear_slot, self.ctx, "naver_a", confirmed=value, expected_version="x"), "CONFIRMATION_REQUIRED")
        self.assertEqual(self.tree(), before)


# ---- 판 1 파일 -----------------------------------------------------------------------------------------------------------------------------
class VersionOneTest(Base):
    def make_v1(self):
        data = channels.profiles_to_dict(channels.default_profiles())
        data["schema"] = 1
        data["profiles"] = [{name: value for name, value in item.items() if name in channels._KEYS_V1} for item in data["profiles"]]
        self.paths.folder.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.paths.profiles.write_bytes(raw)
        return raw

    def test_a_version_one_file_reads_the_three_fields_as_empty_defaults_without_being_rewritten(self):
        raw = self.make_v1()
        snap = self.snap()
        for profile in snap.profiles:
            for name in THREE:
                self.assertEqual(getattr(profile, name), (), (profile.key, name))
        self.assertEqual(self.paths.profiles.read_bytes(), raw, "읽기는 파일을 다시 쓰지 않는다")

    def test_the_first_save_of_a_new_field_upgrades_the_file_to_version_two_after_keeping_an_old_shape_copy(self):
        raw = self.make_v1()
        saved = bp.save_slot(self.ctx, "naver_a", {"priority_keywords": ("예시 우선",), "preferred_post_types": ("정보형",)}, expected_version=self.snap().version)
        self.assertEqual((saved.kind, saved.backed_up), ("saved", True))
        old = self.paths.folder / "channel_profiles.json.v1.bak"
        self.assertEqual(old.read_bytes(), raw, "옛 모양 그대로의 사본")
        data = json.loads(self.paths.profiles.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], 2)
        by_key = {item["key"]: item for item in data["profiles"]}
        self.assertEqual((by_key["naver_a"]["priority_keywords"], by_key["naver_a"]["preferred_post_types"], by_key["naver_a"]["exclude_keywords"]), (["예시 우선"], ["정보형"], []))
        for key in ("github_pages", "blogger_en", "blogger_ko", "naver_b"):
            for name in THREE:
                self.assertEqual(by_key[key][name], [], (key, name))
        self.assertEqual(self.leftovers(), [])


# ---- 7) 쓰기 중간 실패(대표 둘) ---------------------------------------------------------------------------------------------------------
class FailureInjectionTest(Base):
    MAIN = "channel_profiles.json"

    def setUp(self):
        super().setUp()
        self.save()
        self.save("naver_a", {"priority_keywords": ("예시 저장된 우선",)})
        self.before = self.tree()
        self.injector = Injector(self)

    def try_save(self):
        return code_of(bp.save_slot, self.ctx, "naver_a", {"priority_keywords": ("예시 실패해야 하는 우선",), "exclude_keywords": ("예시 실패 제외",), "preferred_post_types": ("문제 해결형",)}, expected_version=self.snap().version)

    def assert_untouched(self, code, expected):
        self.assertEqual(code, expected)
        self.assertEqual(self.tree(), self.before, "기존 값(본 파일·사본·다른 파일)이 한 바이트도 안 바뀌었다")
        self.assertEqual(self.leftovers(), [], "임시 파일·잠금 파일이 남지 않았다")

    def assert_retry_works(self):
        for name in REAL:
            setattr(os, name, REAL[name])
        saved = bp.save_slot(self.ctx, "naver_a", {"priority_keywords": ("예시 다시 한 우선",)}, expected_version=self.snap().version)
        self.assertEqual(saved.kind, "saved")
        self.assertEqual(self.by_key()["naver_a"].priority_keywords, ("예시 다시 한 우선",))

    def test_the_main_temp_file_fails_while_a_topic_field_is_being_written(self):
        self.injector.when("write", self.MAIN + ".tmp", writing_error())
        self.assert_untouched(self.try_save(), "FILE_WRITE_FAILED")
        self.assertEqual(self.by_key()["naver_a"].priority_keywords, ("예시 저장된 우선",), "직전 값 보존")
        self.assert_retry_works()

    def test_a_file_that_reads_back_differently_after_the_rename_is_rolled_back_to_the_previous_topic_values(self):
        def corrupt(args):
            Path(os.fspath(args[1])).write_bytes(b"{garbage")

        self.injector.when("replace", self.MAIN, after=corrupt)
        self.assertEqual(self.try_save(), "FILE_WRITE_FAILED")
        self.assertEqual(json.loads(self.paths.profiles.read_bytes()), json.loads(self.before["topic_engine/channel_profiles.json"]), "본 파일은 직전 내용으로 돌아왔다")
        self.assertEqual(self.by_key()["naver_a"].priority_keywords, ("예시 저장된 우선",))
        self.assertEqual(self.leftovers(), [])
        self.assert_retry_works()


if __name__ == "__main__":
    unittest.main()
