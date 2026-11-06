"""채널 프로필 판 2(P3b-1 S6) 시험 — P4b 프로필 폼이 쓸 선택 칸 열여섯 개(모두 기본값이 비어 있다)·판 1 파일이 그대로 읽힘·판 2 왕복·모르는 칸 거절 유지·키 모양 글 거절·이미지 경로 검증·색 프리셋 값·길이 상한 경계·
`needs_region` 씨앗의 두 갈래(지역 값이 있으면 채워 만들고 없으면 오류 없이 알림)·기존 채널 다섯 개 기본 프로필이 새 칸 때문에 바뀌지 않음.

입력은 모두 시험용 **예시**이고 실제 블로그 이름·아이디·주소·별명·지역은 어디에도 쓰지 않는다. 키 모양 글은 조합해서 만든다(저장소에는 키 문자열이 없다).
"""
import copy
import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402
from test_service_topics import World, put  # noqa: E402

from chanceblog_desktop.content.profiles import POST_TYPES  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.service import topic_format as tfmt  # noqa: E402
from chanceblog_desktop.topicdb import backup as bk  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import layout, notice  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.topics import wording as wd  # noqa: E402

KEY_LIKE = "AI" + "za" + "E" * 35
NEW_KEYS = ("blog_ref", "alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "color_preset", "profile_image", "cover_image", "priority_keywords", "exclude_keywords",
            "preferred_post_types", "home_regions", "day_trip_regions")
OLD_KEYS = ("key", "display_name", "language", "generation_enabled", "history_enabled", "evergreen_pct", "realtime_pct", "weights", "top_n", "cluster_cap", "subheading_min", "trend_use", "dup_cutoffs",
            "topic_clusters", "expansion_directions", "monetization_focus")
BASE = ts.PROFILES["naver_a"]


def make(**changes):
    return dataclasses.replace(BASE, **changes)


def refused(test, **changes):
    with test.assertRaises(AppError) as caught:
        make(**changes)
    test.assertEqual(caught.exception.code, "CONTENT_INVALID")
    return caught.exception.slots["항목"]


class DefaultsAndShapeTest(unittest.TestCase):
    def test_the_sixteen_new_fields_are_optional_and_empty_by_default(self):
        for profile in ch.default_profiles():
            for name in NEW_KEYS:
                with self.subTest(channel=profile.key, field=name):
                    self.assertIn(getattr(profile, name), ("", (), None))
        self.assertEqual(ch._KEYS, OLD_KEYS + NEW_KEYS)
        self.assertEqual(ch.SCHEMA, 2)
        self.assertEqual(ch.SCHEMAS, (1, 2))
        self.assertEqual(set(ch.PROFILE_FIELD_KO), set(ch._KEYS), "모든 칸에 쉬운 한국어 이름이 있다")

    def test_the_default_profiles_hold_no_real_blog_values_and_keep_their_old_values(self):
        for profile in ch.default_profiles():
            data = profile.to_dict()
            self.assertTrue(all(data[name] in ("", [], None) for name in NEW_KEYS), "저장소의 기본 프로필은 새 칸이 모두 비어 있다")
        self.assertEqual([item.generation_enabled for item in ch.default_profiles()], [False, False, False, True, True], "후보 생성은 네이버 A·B 만 켜짐(그대로)")

    def test_a_version_1_file_reads_with_empty_new_fields_and_the_input_is_not_touched(self):
        old = {"schema": 1, "profiles": [{key: value for key, value in item.items() if key in OLD_KEYS} for item in ch.profiles_to_dict(ch.default_profiles())["profiles"]]}
        before = copy.deepcopy(old)
        found = ch.profiles_from_dict(old)
        self.assertEqual(old, before, "읽어도 입력은 바뀌지 않는다 — 파일을 몰래 다시 쓰지 않는다")
        self.assertEqual(found, ch.default_profiles())
        v1_with_new = copy.deepcopy(old)
        v1_with_new["profiles"][0]["alias"] = "예시"
        with self.assertRaises(AppError):
            ch.profiles_from_dict(v1_with_new)

    def test_version_2_round_trips_with_every_new_field_filled(self):
        full = dict(blog_ref="https://example.org/blog", alias="예시 별명", channel_role="예시 역할", main_topics=("예시 주제 하나", "예시 주제 둘"), audience="예시 독자", tone="예시 문체",
                    categories=("예시 분류",), intro="예시 소개글", color_preset="cool_technology", profile_image="예시/프로필.png", cover_image="예시/커버.png", priority_keywords=("예시 우선",),
                    exclude_keywords=("예시 제외",), preferred_post_types=("비교형", "정보형"), home_regions=("예시 지역 하나",), day_trip_regions=("예시 당일 하나", "예시 당일 둘"))
        edited = tuple(dataclasses.replace(item, **full) if item.key == "naver_a" else item for item in ch.default_profiles())
        data = json.loads(json.dumps(ch.profiles_to_dict(edited), ensure_ascii=False))
        self.assertEqual(data["schema"], 2)
        self.assertEqual(ch.profiles_from_dict(data), edited)
        mine = next(item for item in data["profiles"] if item["key"] == "naver_a")
        self.assertEqual(mine["preferred_post_types"], ["비교형", "정보형"])
        self.assertEqual(mine["color_preset"], "cool_technology")

    def test_the_exact_key_sets_are_kept_unknown_and_missing_fields_and_newer_versions_are_refused(self):
        good = ch.profiles_to_dict(ch.default_profiles())
        extra = copy.deepcopy(good)
        extra["profiles"][0]["unknown"] = 1
        with self.assertRaises(AppError):
            ch.profiles_from_dict(extra)
        for name in NEW_KEYS:
            with self.subTest(missing=name):
                broken = copy.deepcopy(good)
                del broken["profiles"][2][name]
                with self.assertRaises(AppError) as caught:
                    ch.profiles_from_dict(broken)
                self.assertIn(wd.quote(ch.PROFILE_FIELD_KO[name]), caught.exception.rendered().message)
        for version in (3, 9):
            with self.assertRaises(AppError) as caught:
                ch.profiles_from_dict({**good, "schema": version})
            self.assertIn("업데이트", caught.exception.slots["항목"])
        for bad in (0, True, "2", 2.0, None):
            with self.assertRaises(AppError):
                ch.profiles_from_dict({**good, "schema": bad})

    def test_the_plain_json_has_only_plain_types(self):
        text = json.dumps(ch.profiles_to_dict(ch.default_profiles()), ensure_ascii=False)
        self.assertNotIn("mappingproxy", text)
        self.assertEqual(type(ch.default_profiles()[0].to_dict()["main_topics"]), list)


class FieldRulesTest(unittest.TestCase):
    def test_text_fields_accept_exactly_their_limit(self):
        for name, limit in (("alias", 30), ("channel_role", 60), ("audience", 120), ("tone", 120), ("intro", 300)):
            with self.subTest(field=name):
                self.assertEqual(getattr(make(**{name: "가" * limit}), name), "가" * limit)
                self.assertIn(ch.PROFILE_FIELD_KO[name], refused(self, **{name: "가" * (limit + 1)}))
        self.assertEqual(make(alias="").alias, "", "비워 둘 수 있다")

    def test_text_fields_are_one_line_without_markup_or_control_characters(self):
        for name in ("alias", "channel_role", "audience", "tone", "intro"):
            for bad in ("두 줄\n입니다", "<b>굵게</b>", "{% 반복 %}", "제어\x00글자", 5, None):
                with self.subTest(field=name, bad=repr(bad)[:12]):
                    refused(self, **{name: bad})
            self.assertEqual(getattr(make(**{name: "  앞뒤 공백은 다듬어 저장  "}), name), "앞뒤 공백은 다듬어 저장", "앞뒤 공백은 다듬어 저장한다(기존 칸과 같은 규칙)")

    def test_word_lists_have_count_and_length_limits_and_no_repeats(self):
        for name, count, high in (("main_topics", 10, 30), ("categories", 30, 40), ("priority_keywords", 20, 30), ("exclude_keywords", 20, 30), ("home_regions", 20, 30), ("day_trip_regions", 20, 30)):
            with self.subTest(field=name):
                self.assertEqual(len(getattr(make(**{name: tuple(f"낱말{number}" for number in range(count))}), name)), count)
                refused(self, **{name: tuple(f"낱말{number}" for number in range(count + 1))})
                self.assertEqual(getattr(make(**{name: ("가" * high,)}), name), ("가" * high,))
                refused(self, **{name: ("가" * (high + 1),)})
                refused(self, **{name: ("같은", "같은")})
                refused(self, **{name: ("<b>x</b>",)})
                refused(self, **{name: "문자열 하나"})
                refused(self, **{name: ("",)})

    def test_priority_and_exclude_keywords_cannot_overlap(self):
        self.assertEqual(make(priority_keywords=("가",), exclude_keywords=("나",)).priority_keywords, ("가",))
        refused(self, priority_keywords=("겹침",), exclude_keywords=("겹침",))

    def test_the_color_preset_is_empty_or_one_of_two_values_never_a_hex_color(self):
        self.assertEqual(ch.COLOR_PRESETS, ("warm_lifestyle", "cool_technology"))
        self.assertIsNone(make().color_preset)
        for value in ch.COLOR_PRESETS:
            self.assertEqual(make(color_preset=value).color_preset, value)
        for bad in ("#ff8800", "red", "WARM_LIFESTYLE", "", 3, ["warm_lifestyle"]):
            with self.subTest(bad=repr(bad)):
                refused(self, color_preset=bad)
        self.assertEqual(set(wd.COLOR_PRESET_KO), set(ch.COLOR_PRESETS))
        self.assertNotIn("warm_lifestyle", refused(self, color_preset="red"), "영문 값 이름 대신 쉬운 한국어 이름을 보인다")

    def test_the_blog_reference_is_an_id_or_an_https_address_without_account_info(self):
        for good in ("", "exampleid", "example.id_01-x", "a" * 64, "https://example.org", "https://blog.example.org/path/to", "https://example.org:8080/a?b=1", "https://xn--abc.example.org/가"):
            with self.subTest(good=good[:30]):
                self.assertEqual(make(blog_ref=good).blog_ref, good)
        for bad in ("a" * 65, "http://example.org", "ftp://example.org", "javascript:alert(1)", "https://user:pw@example.org", "https://example.org/#top", "https://", "https://localhost", "예시 아이디", "with space",
                    "a@b", "-leading", "https://example.org/" + "a" * 200, 5, None, "<b>x</b>"):
            with self.subTest(bad=str(bad)[:30]):
                refused(self, blog_ref=bad)

    def test_the_image_fields_are_path_text_only_and_never_look_at_a_file(self):
        for name in ("profile_image", "cover_image"):
            for good in ("", "images/예시 프로필.png", r"C:\예시\폴더\프로필.png", "../어딘가/없는 파일.jpg", "x" * 260):
                with self.subTest(field=name, good=good[:20]):
                    self.assertEqual(getattr(make(**{name: good}), name), good, "파일이 있는지는 보지 않는다")
            for bad in ("x" * 261, "줄\n바꿈", "제어\x00글자", "data:image/png;base64,AAAA", "DATA:text/plain,x", "data: 그림.png", "javascript: 그림.png", "<img src=x>", 7, None, b"bytes"):
                with self.subTest(field=name, bad=repr(bad)[:20]):
                    refused(self, **{name: bad})

    def test_preferred_post_types_are_a_set_of_the_five_known_types(self):
        self.assertEqual(len(POST_TYPES), 5)
        self.assertEqual(make(preferred_post_types=POST_TYPES).preferred_post_types, POST_TYPES)
        self.assertEqual(make(preferred_post_types=[POST_TYPES[1]]).preferred_post_types, (POST_TYPES[1],))
        for bad in (("없는 유형",), (POST_TYPES[0], POST_TYPES[0]), POST_TYPES + ("여섯째",), "정보형", [3]):
            with self.subTest(bad=repr(bad)[:30]):
                refused(self, preferred_post_types=bad)

    def test_the_old_fields_are_still_checked_exactly_as_before(self):
        for changes in ({"top_n": 0}, {"evergreen_pct": 50, "realtime_pct": 60}, {"language": "fr"}, {"display_name": ""}, {"trend_use": "always"}):
            with self.subTest(changes=changes), self.assertRaises(AppError):
                make(**changes)


class KeyShapeTest(unittest.TestCase):
    def file_with(self, **changes):
        profiles = tuple(dataclasses.replace(item, **changes) if item.key == "naver_a" else item for item in ch.default_profiles())
        return json.dumps(ch.profiles_to_dict(profiles), ensure_ascii=False).encode("utf-8")

    def test_a_key_shaped_text_in_any_new_text_field_is_refused_when_the_file_is_read_and_never_repeated(self):
        # 키 모양(39자)이 들어갈 수 있는 칸은 길이 상한이 39자 이상인 칸들이다 — 30자 이하 칸(별명·낱말 목록들)에는 키 모양이 들어갈 수 없다(아래에서 길이 상한이 먼저 거절함을 본다)
        roomy = {"blog_ref": "https://example.org/" + KEY_LIKE, "channel_role": KEY_LIKE, "audience": KEY_LIKE, "tone": KEY_LIKE, "categories": (KEY_LIKE,), "intro": "소개 " + KEY_LIKE,
                 "profile_image": "예시/" + KEY_LIKE + ".png", "cover_image": "예시/" + KEY_LIKE + ".png"}
        for name, value in roomy.items():
            with self.subTest(field=name):
                with self.assertRaises(AppError) as caught:
                    bk.check_json_bytes(layout.CHANNEL_PROFILES_FILE, self.file_with(**{name: value}))
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                shown = str(caught.exception.slots) + str(caught.exception.detail) + caught.exception.rendered().message
                self.assertNotIn(KEY_LIKE, shown, "키 모양 글은 되풀이하지 않는다")
                self.assertIn("네이버 A", shown)
                self.assertIn("키·토큰처럼 보이는", shown)
                self.assertTrue(notice.is_clean(str(caught.exception.slots["항목"])))
        self.assertTrue(set(roomy) < set(bk.PROFILE_TEXT_KEYS))
        for name in sorted(set(bk.PROFILE_TEXT_KEYS) - set(roomy)):
            with self.subTest(short_field=name):
                value = "예시 " + KEY_LIKE if name == "alias" else (KEY_LIKE,)
                with self.assertRaises(AppError) as caught:
                    make(**{name: value})
                self.assertEqual(caught.exception.code, "CONTENT_INVALID", "30자 이하 칸은 길이 상한이 먼저 거절한다 — 키가 저장될 길이 없다")

    def test_ordinary_new_field_values_pass_the_file_check_and_old_fields_are_not_scanned_by_it(self):
        good = self.file_with(alias="예시 별명", intro="예시 소개글", blog_ref="https://example.org/blog", home_regions=("예시지역",))
        self.assertEqual(next(item for item in bk.check_json_bytes(layout.CHANNEL_PROFILES_FILE, good) if item.key == "naver_a").alias, "예시 별명")
        old_field = self.file_with(display_name="예시 " + KEY_LIKE[:20])
        self.assertTrue(bk.check_json_bytes(layout.CHANNEL_PROFILES_FILE, old_field), "옛 칸의 동작은 그대로다(이 검사는 새 글칸만 본다)")

    def test_the_file_check_reads_both_versions(self):
        v1 = {"schema": 1, "profiles": [{key: value for key, value in item.items() if key in OLD_KEYS} for item in ch.profiles_to_dict(ch.default_profiles())["profiles"]]}
        self.assertEqual(bk.check_json_bytes(layout.CHANNEL_PROFILES_FILE, json.dumps(v1).encode("utf-8")), ch.default_profiles())
        self.assertEqual(bk.check_json_bytes(layout.CHANNEL_PROFILES_FILE, json.dumps(ch.profiles_to_dict(ch.default_profiles())).encode("utf-8")), ch.default_profiles())


def region_seed(**changes):
    values = dict(seed_id="ex-region", keyword="{기준 지역} 예시 나들이", needs_region=True, scope="naver_a", major="예시 대분류", minor="지역", target_type="place")
    values.update(changes)
    return ts.example_seed(**values)


class NeedsRegionTest(unittest.TestCase):
    TODAY = "2026-11-10"

    def run_for(self, profile, *pool):
        return gn.generate(profile, pool, (), (), self.TODAY, target=20)

    def test_with_a_region_the_placeholder_is_filled_and_candidates_are_made(self):
        profile = make(home_regions=("예시시", "예시군"), day_trip_regions=("예시당일",))
        found = self.run_for(profile, region_seed(), ts.example_seed(seed_id="ex-plain", keyword="예시 일반 물건", scope="naver_a"))
        mine = [item for item in found.candidates if item.seed_id == "ex-region"]
        self.assertTrue(mine)
        self.assertTrue(all("예시시" in item.primary_keyword and "{" not in item.topic + item.primary_keyword for item in mine), "첫 상시 이동권 지역으로 채운다")
        self.assertEqual(found.region_missing, ())
        self.assertTrue([item for item in found.candidates if item.seed_id == "ex-plain"], "지역이 필요 없는 씨앗은 그대로다")

    def test_the_day_trip_region_is_used_when_there_is_no_home_region(self):
        found = self.run_for(make(day_trip_regions=("예시당일",)), region_seed())
        self.assertTrue(found.candidates)
        self.assertTrue(all("예시당일" in item.primary_keyword for item in found.candidates))

    def test_without_any_region_no_candidate_is_made_and_it_is_a_notice_not_an_error(self):
        found = self.run_for(make(), region_seed(), region_seed(seed_id="ex-region-2", keyword="{기준 지역} 예시 행사"), ts.example_seed(seed_id="ex-plain", keyword="예시 일반 물건", scope="naver_a"))
        self.assertEqual(found.region_missing, ("ex-region", "ex-region-2"))
        self.assertTrue(all(item.seed_id == "ex-plain" for item in found.candidates), "지역 값이 필요한 씨앗은 후보를 만들지 않는다")
        self.assertTrue(found.candidates, "다른 씨앗은 영향이 없다")
        self.assertNotIn("{", " ".join(item.topic for item in found.candidates))

    def test_a_region_that_makes_the_seed_too_long_drops_only_that_seed_with_a_reason(self):
        long_region = "가" * 30
        found = self.run_for(make(home_regions=(long_region,)), region_seed(keyword="{기준 지역} " + "나" * 45))
        self.assertEqual(found.candidates, ())
        self.assertTrue(any(row.reason == "invalid" for row in found.dropped))

    def test_the_other_channels_are_off_so_nothing_is_made_even_with_a_region(self):
        off = dataclasses.replace(ts.PROFILES["github_pages"], home_regions=("예시시",))
        self.assertEqual(self.run_for(off, region_seed(scope="github_pages")).candidates, ())

    def test_the_service_shows_a_plain_notice_in_the_plan_and_the_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            seeds_now = tf.load_seeds(world.paths).value
            put(world.paths.seeds, sd.seeds_to_dict((*seeds_now, region_seed(seed_id="ex-r1", keyword="{기준 지역} 예시 나들이"))))
            result = world.plan(channel="naver_a")
            plan = next(item for item in result.plans if item.channel == "naver_a")
            self.assertEqual(plan.needs_region, ("ex-r1",))
            lines = tfmt.plan_lines(result)
            line = next(text for text in lines if "지역 값이 필요한 씨앗" in text)
            self.assertIn("후보를 만들지 않았습니다", line)
            self.assertIn("오류가 아니라 알림", line)
            self.assertIn("‘ex-r1’", line)
            self.assertEqual(plan.to_dict()["needs_region_seeds"], ["ex-r1"])
            code, out, err = ss.run_cli(world.ctx, "topics", "plan", "--channel", "naver_a", "--today", self.TODAY)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("지역 값이 필요한 씨앗 1개", out)
            profiles = tuple(dataclasses.replace(item, home_regions=("예시시",)) if item.key == "naver_a" else item for item in ch.default_profiles())
            put(world.paths.profiles, ch.profiles_to_dict(profiles))
            again = world.plan(channel="naver_a")
            filled = next(item for item in again.plans if item.channel == "naver_a")
            self.assertEqual(filled.needs_region, ())
            self.assertTrue(any(candidate.seed_id == "ex-r1" and "예시시" in candidate.primary_keyword for candidate in filled.candidates))

    def test_a_key_shaped_seed_id_is_masked_in_the_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            put(world.paths.seeds, sd.seeds_to_dict((region_seed(seed_id=KEY_LIKE, keyword="{기준 지역} 예시 하나"), ts.example_seed(seed_id="ex-plain", keyword="예시 일반 물건", scope="naver_a"))))
            result = world.plan(channel="naver_a")
            shown = "\n".join(tfmt.plan_lines(result)) + json.dumps(result.to_dict(), ensure_ascii=False)
            self.assertNotIn(KEY_LIKE, shown)


if __name__ == "__main__":
    unittest.main()
