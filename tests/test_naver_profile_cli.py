"""명령줄 `naver-profile` 의 '글 만들 때 쓰는 항목' 옵션(도입부 스타일·소제목 수·설명 난이도·마무리 방식·제외 주제·같은 주제 재사용 기준·기본 글 유형) 시험.

지키는 것:
  1) **예전 출력은 한 글자도 안 바뀐다** — 새 옵션 없이 쓰는 `naver-profile set` 의 글·JSON, `show` 의 글 전체와 `show --json`, 저장 파일의 모양이 이 묶음 이전(기준 커밋 0623668)에 직접 받아 둔 것과 같다.
  2) 새 항목은 `NaverProfile` 의 검사를 그대로 받는다(모양이 틀리면 PROFILE_INVALID — '블로그 프로필의 …' 한국어 안내, 저장된 것은 그대로) — 숫자가 아닌 값은 사용법 오류.
  3) `show` 는 새 항목을 하나라도 정한 프로필에 한해 프로필 줄 아래에 항목마다 한 줄씩 보이고 기본값과 같은 것은 '기본값' 으로 보인다(하나도 안 정했으면 줄을 더하지 않는다). 기본값에서 바꾼 항목만 저장 파일에 나타난다.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402

# 이 묶음 이전의 코드(기준 커밋)로 같은 명령을 돌려 직접 받아 둔 출력
OLD_SET_A = "네이버 A 프로필을 저장했습니다: 블로그 에이 — https://blog.naver.com/exampleaaa\n"
OLD_SHOW_EMPTY_JSON = '{\n  "ok": true,\n  "command": "naver-profile",\n  "data": {\n    "profiles": {}\n  }\n}\n'
OLD_SET_JSON = """{
  "ok": true,
  "command": "naver-profile",
  "data": {
    "profile": {
      "key": "naver_a",
      "display_name": "블로그 에이",
      "blog_url": "https://blog.naver.com/exampleaaa",
      "topic": "",
      "audience": "",
      "tone": "차분하게",
      "categories": [
        [
          "경제",
          "경제 이야기"
        ]
      ],
      "default_tags": [
        "생활"
      ],
      "forbidden_phrases": [
        "광고",
        "협찬"
      ],
      "image_spec": "",
      "min_chars": 10,
      "max_chars": 6000,
      "max_title_chars": 60,
      "paragraph_max_chars": 180,
      "max_tags": 10,
      "disclosure": "",
      "publish_cycle": ""
    }
  }
}
"""
OLD_SHOW_JSON = """{
  "ok": true,
  "command": "naver-profile",
  "data": {
    "profiles": {
      "naver_a": {
        "audience": "",
        "blog_url": "https://blog.naver.com/exampleaaa",
        "categories": [
          [
            "경제",
            "경제 이야기"
          ]
        ],
        "default_tags": [
          "생활"
        ],
        "disclosure": "",
        "display_name": "블로그 에이",
        "forbidden_phrases": [
          "광고",
          "협찬"
        ],
        "image_spec": "",
        "key": "naver_a",
        "max_chars": 6000,
        "max_tags": 10,
        "max_title_chars": 60,
        "min_chars": 10,
        "paragraph_max_chars": 180,
        "publish_cycle": "",
        "tone": "차분하게",
        "topic": ""
      }
    }
  }
}
"""
OLD_FIRST_LINE_A = "네이버 A: 블로그 에이 — https://blog.naver.com/exampleaaa"
OLD_FIRST_LINE_B = "네이버 B: 블로그 비 — https://blog.naver.com/examplebbb"
NEW_KEYS = ("intro_style", "subheading_min", "subheading_max", "difficulty", "ending_style", "excluded_topics", "topic_reuse_days", "post_type")
BASE_SET = ("naver-profile", "set", "naver_a", "--name", "블로그 에이", "--url", "https://blog.naver.com/exampleaaa")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo="")

    def run_cli(self, *argv):
        return ss.run_cli(self.ctx, *argv)

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual((code, err), (0, ""), (argv, out, err))
        return out

    def fails(self, *argv, code=1):
        got, out, err = self.run_cli(*argv)
        self.assertEqual((got, out), (code, ""), (argv, out, err))
        self.assertNotIn("Traceback", err)
        return err

    def error_json(self, *argv):
        code, out, err = self.run_cli("--json", *argv)
        self.assertEqual((code, err), (1, ""), (argv, out, err))
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        return payload

    def stored(self):
        return json.loads(self.ctx.workspace.settings_path.read_text(encoding="utf-8"))["naver_profiles"]

    def first(self, *extra):
        self.ok(*BASE_SET, *extra)


class OldOutputIsUnchangedTest(Base):
    def test_an_empty_show_is_the_same_as_before(self):
        self.assertEqual(self.ok("naver-profile", "show"), "설정된 네이버 블로그 프로필이 없습니다.\n")
        self.assertEqual(self.ok("--json", "naver-profile", "show"), OLD_SHOW_EMPTY_JSON)

    def test_set_without_the_new_options_prints_exactly_the_old_line_and_the_old_json(self):
        self.assertEqual(self.ok(*BASE_SET, "--tags", "생활", "--min-chars", "10"), OLD_SET_A)
        self.assertEqual(self.ok("--json", "naver-profile", "set", "naver_a", "--tone", "차분하게", "--category-map", "경제=경제 이야기", "--forbidden", "광고,협찬"), OLD_SET_JSON)

    def test_show_keeps_its_first_line_and_its_json_byte_for_byte(self):
        self.ok(*BASE_SET, "--tags", "생활", "--min-chars", "10")
        self.ok("naver-profile", "set", "naver_a", "--tone", "차분하게", "--category-map", "경제=경제 이야기", "--forbidden", "광고,협찬")
        self.assertEqual(self.ok("--json", "naver-profile", "show"), OLD_SHOW_JSON)
        self.assertEqual(self.ok("naver-profile", "show"), OLD_FIRST_LINE_A + "\n", "새 항목을 하나도 정하지 않은 프로필은 예전과 출력이 한 글자도 다르지 않다")

    def test_two_profiles_the_one_that_uses_no_new_item_keeps_exactly_its_old_line_and_the_other_gets_its_own_block(self):
        self.ok(*BASE_SET)
        self.ok("naver-profile", "set", "naver_b", "--name", "블로그 비", "--url", "https://blog.naver.com/examplebbb", "--subheading-min", "2", "--subheading-max", "3")
        lines = self.ok("naver-profile", "show").splitlines()
        self.assertEqual(lines[:3], [OLD_FIRST_LINE_A, OLD_FIRST_LINE_B, "  글 만들 때 쓰는 항목:"])
        self.assertIn("    소제목 수: 2~3개", lines[3:])
        self.assertIn("    도입부 스타일: 기본값(정하지 않음)", lines[3:])
        self.assertEqual(len(lines), 2 + 8)

    def test_a_profile_saved_without_the_new_options_is_written_in_the_old_shape(self):
        self.ok(*BASE_SET, "--tags", "생활")
        self.assertEqual(sorted(self.stored()["naver_a"]), sorted(NaverProfile("naver_a", "x", "https://blog.naver.com/x").to_dict()))
        self.assertTrue(set(NEW_KEYS).isdisjoint(self.stored()["naver_a"]))

    def test_the_other_commands_and_json_commands_names_did_not_change(self):
        payload = json.loads(self.ok("--json", "naver-profile", "show"))
        self.assertEqual(payload["command"], "naver-profile")
        self.assertEqual(json.loads(self.ok("--json", "list"))["command"], "list")


class SettingNewOptionsTest(Base):
    def test_each_option_reaches_the_profile(self):
        self.first("--intro-style", "독자의 고민으로 시작", "--subheading-min", "2", "--subheading-max", "4", "--difficulty", "처음 접하는 사람도 이해", "--ending-style", "핵심 세 줄 요약",
                   "--excluded-topics", "주식, 코인 ,부동산", "--topic-reuse-days", "30", "--post-type", "비교형")
        profile = NaverProfile.from_dict(self.stored()["naver_a"])
        self.assertEqual((profile.intro_style, profile.subheading_min, profile.subheading_max, profile.difficulty, profile.ending_style), ("독자의 고민으로 시작", 2, 4, "처음 접하는 사람도 이해", "핵심 세 줄 요약"))
        self.assertEqual((profile.excluded_topics, profile.topic_reuse_days, profile.post_type), (("주식", "코인", "부동산"), 30, "비교형"))
        self.assertEqual(set(self.stored()["naver_a"]) & set(NEW_KEYS), set(NEW_KEYS))

    def test_the_excluded_topics_are_split_at_half_width_and_full_width_commas_alike(self):
        for text in ("주식,코인,부동산", "주식，코인，부동산", "주식, 코인，부동산", "주식，코인,부동산", " 주식 ，， 코인 ,, 부동산 ，"):
            with self.subTest(text=text):
                self.first("--excluded-topics", text)
                self.assertEqual(self.stored()["naver_a"]["excluded_topics"], ["주식", "코인", "부동산"])
        self.first("--excluded-topics", "한 개만")
        self.assertEqual(self.stored()["naver_a"]["excluded_topics"], ["한 개만"])

    def test_the_other_comma_lists_still_split_at_the_half_width_comma_only(self):
        self.first("--tags", "생활，건강,요리")
        self.assertEqual(self.stored()["naver_a"]["default_tags"], ["생활，건강", "요리"], "전각 쉼표 처리는 제외 주제에만 더했다 — 예전 옵션은 그대로다")

    def test_the_options_can_be_set_later_one_at_a_time_and_keep_the_rest(self):
        self.first("--tags", "생활")
        self.ok("naver-profile", "set", "naver_a", "--topic-reuse-days", "30")
        self.ok("naver-profile", "set", "naver_a", "--post-type", "문제 해결형")
        profile = NaverProfile.from_dict(self.stored()["naver_a"])
        self.assertEqual((profile.topic_reuse_days, profile.post_type, profile.default_tags, profile.subheading_min), (30, "문제 해결형", ("생활",), 3))

    def test_only_values_that_differ_from_the_defaults_are_saved(self):
        self.first("--subheading-min", "3", "--subheading-max", "5", "--topic-reuse-days", "90", "--post-type", "정보형", "--excluded-topics", "", "--intro-style", "")
        self.assertTrue(set(NEW_KEYS).isdisjoint(self.stored()["naver_a"]), self.stored()["naver_a"])
        self.ok("naver-profile", "set", "naver_a", "--topic-reuse-days", "0")
        self.assertEqual(self.stored()["naver_a"]["topic_reuse_days"], 0, "0 은 기본값(90)과 다르니 저장된다")
        self.ok("naver-profile", "set", "naver_a", "--topic-reuse-days", "90")
        self.assertNotIn("topic_reuse_days", self.stored()["naver_a"])

    def test_an_empty_value_clears_a_text_option_and_the_excluded_topics(self):
        self.first("--intro-style", "처음", "--difficulty", "쉽게", "--ending-style", "요약", "--excluded-topics", "주식,코인")
        self.ok("naver-profile", "set", "naver_a", "--intro-style", "", "--difficulty", "", "--ending-style", "", "--excluded-topics", "")
        self.assertTrue(set(NEW_KEYS).isdisjoint(self.stored()["naver_a"]))

    def test_set_prints_one_extra_line_with_what_differs_only_when_a_new_option_was_given(self):
        out = self.ok(*BASE_SET, "--subheading-min", "2", "--subheading-max", "4", "--excluded-topics", "주식,코인", "--post-type", "비교형")
        self.assertEqual(out.splitlines(), [OLD_SET_A.strip(), "  글 만들 때 쓰는 항목(기본값과 다른 것): 소제목 수 2~4개 · 제외 주제 주식, 코인 · 기본 글 유형 비교형"])
        again = self.ok("naver-profile", "set", "naver_a", "--tone", "차분하게")
        self.assertEqual(again.splitlines(), [OLD_SET_A.strip()], "새 옵션을 안 준 명령은 예전과 같은 한 줄이다")
        back = self.ok("naver-profile", "set", "naver_a", "--subheading-min", "3", "--subheading-max", "5", "--excluded-topics", "", "--post-type", "정보형")
        self.assertEqual(back.splitlines()[1], "  글 만들 때 쓰는 항목(기본값과 다른 것): 모두 기본값")

    def test_the_json_of_set_shows_the_saved_profile_with_only_the_non_default_new_keys(self):
        payload = json.loads(self.ok("--json", *BASE_SET, "--topic-reuse-days", "30"))
        profile = payload["data"]["profile"]
        self.assertEqual(profile["topic_reuse_days"], 30)
        self.assertEqual(set(profile) & set(NEW_KEYS), {"topic_reuse_days"})


class RefusedValuesTest(Base):
    def test_values_the_profile_refuses_are_handled_errors_in_korean_and_change_nothing(self):
        self.first("--tags", "생활")
        before = self.ctx.workspace.settings_path.read_bytes()
        for argv, item in ((("--subheading-min", "0"), "소제목 수 하한"), (("--subheading-max", "21"), "소제목 수 상한"), (("--subheading-min", "6"), "소제목 수 상한"),
                           (("--subheading-max", "2"), "소제목 수 상한"), (("--subheading-min", "5", "--subheading-max", "4"), "소제목 수 상한"), (("--topic-reuse-days", "-1"), "같은 주제 재사용 기준"),
                           (("--topic-reuse-days", "3651"), "같은 주제 재사용 기준"), (("--post-type", "후기"), "기본 글 유형"), (("--post-type", ""), "기본 글 유형"),
                           (("--excluded-topics", "주식,주식"), "제외 주제"), (("--excluded-topics", "<script>"), "제외 주제"), (("--excluded-topics", "{{ x }}"), "제외 주제"),
                           (("--intro-style", "<b>굵게</b>"), "도입부 스타일"), (("--difficulty", "가" * 201), "설명 난이도"), (("--ending-style", "javascript:x"), "마무리 방식")):
            with self.subTest(argv=argv):
                err = self.fails("naver-profile", "set", "naver_a", *argv)
                self.assertIn("코드: PROFILE_INVALID", err)
                self.assertIn("블로그 프로필의", err, "원고가 아니라 프로필의 말로 알린다")
                self.assertNotIn("원고", err)
                self.assertIn(item, err)
                self.assertIn("하실 일:", err)
                self.assertIn("naver-profile set", err)
                self.assertEqual(self.ctx.workspace.settings_path.read_bytes(), before, "거절된 값은 저장된 프로필을 그대로 둔다")

    def test_an_error_in_an_old_profile_item_is_told_in_the_profiles_words_too_not_as_a_manuscript_error(self):
        self.first("--tags", "생활")
        before = self.ctx.workspace.settings_path.read_bytes()
        for argv in (("--url", "https://example.com/not-naver"), ("--min-chars", "-3"), ("--name", "가" * 300)):
            with self.subTest(argv=argv):
                err = self.fails("naver-profile", "set", "naver_a", *argv)
                self.assertIn("코드: PROFILE_INVALID", err)
                self.assertIn("블로그 프로필의", err)
                self.assertNotIn("원고", err)
        self.assertEqual(self.ctx.workspace.settings_path.read_bytes(), before)
        payload = self.error_json("naver-profile", "set", "naver_a", "--topic-reuse-days", "-1")
        self.assertEqual((payload["command"], payload["error"]["code"]), ("naver-profile", "PROFILE_INVALID"))
        self.assertIn("같은 주제 재사용 기준", payload["error"]["message"])

    def test_a_blog_without_a_profile_is_still_told_to_give_a_name_and_an_address_not_called_invalid(self):
        err = self.fails("naver-profile", "set", "naver_b", "--topic-reuse-days", "30")
        self.assertIn("NAVER_PROFILE_MISSING", err)
        self.assertNotIn("PROFILE_INVALID", err)

    def test_a_subheading_range_error_adds_a_hint_about_setting_both_ends(self):
        self.first()
        err = self.fails("naver-profile", "set", "naver_a", "--subheading-min", "6")
        self.assertIn("하한은 상한보다 클 수 없습니다", err)
        self.assertIn("--subheading-min 6 --subheading-max 8", err)
        self.ok("naver-profile", "set", "naver_a", "--subheading-min", "6", "--subheading-max", "8")
        self.assertEqual((self.stored()["naver_a"]["subheading_min"], self.stored()["naver_a"]["subheading_max"]), (6, 8))
        err = self.fails("naver-profile", "set", "naver_a", "--topic-reuse-days", "-1")
        self.assertNotIn("하한은 상한보다", err, "다른 항목의 오류에는 붙이지 않는다")

    def test_a_value_that_is_not_a_number_is_a_usage_error(self):
        self.first()
        for argv in (("--subheading-min", "abc"), ("--subheading-max", "3.5"), ("--topic-reuse-days", "많이"), ("--topic-reuse-days", "")):
            with self.subTest(argv=argv):
                err = self.fails("naver-profile", "set", "naver_a", *argv, code=2)
                self.assertIn("사용법 오류", err)
                self.assertIn("숫자", err)

    def test_the_names_cannot_be_shortened(self):
        self.first()
        for argv in (("--subheading", "3"), ("--topic-reuse", "30"), ("--excluded", "주식"), ("--post", "비교형"), ("--intro", "처음")):
            with self.subTest(argv=argv):
                self.fails("naver-profile", "set", "naver_a", *argv, code=2)

    def test_a_blog_that_has_no_profile_yet_still_needs_a_name_and_an_address(self):
        err = self.fails("naver-profile", "set", "naver_b", "--topic-reuse-days", "30")
        self.assertIn("코드: NAVER_PROFILE_MISSING", err)
        self.assertFalse(self.ctx.workspace.settings_path.exists())


class ShowNewOptionsTest(Base):
    def test_when_some_are_set_every_item_is_listed_and_the_rest_say_default(self):
        self.first("--intro-style", "독자의 고민으로 시작", "--subheading-min", "2", "--subheading-max", "4", "--excluded-topics", "주식,코인", "--post-type", "비교형")
        lines = self.ok("naver-profile", "show").splitlines()
        self.assertEqual(lines, [OLD_FIRST_LINE_A, "  글 만들 때 쓰는 항목:", "    도입부 스타일: 독자의 고민으로 시작", "    소제목 수: 2~4개", "    설명 난이도: 기본값(정하지 않음)", "    마무리 방식: 기본값(정하지 않음)",
                                 "    제외 주제: 주식, 코인", "    같은 주제 재사용 기준: 기본값(90일)", "    기본 글 유형: 비교형"])

    def test_every_item_can_show_the_default_marker_and_a_value_equal_to_the_default_counts_as_default(self):
        self.first("--topic-reuse-days", "30")
        lines = self.ok("naver-profile", "show").splitlines()
        for name in ("도입부 스타일", "설명 난이도", "마무리 방식"):
            self.assertIn(f"    {name}: 기본값(정하지 않음)", lines)
        self.assertIn("    소제목 수: 기본값(3~5개)", lines)
        self.assertIn("    제외 주제: 기본값(없음)", lines)
        self.assertIn("    같은 주제 재사용 기준: 30일", lines)
        self.assertIn("    기본 글 유형: 기본값(정보형)", lines)

    def test_zero_reuse_days_is_said_in_words(self):
        self.first("--topic-reuse-days", "0")
        self.assertIn("    같은 주제 재사용 기준: 0일(경고하지 않음)", self.ok("naver-profile", "show").splitlines())

    def test_one_end_of_the_subheading_range_changed_shows_the_whole_range(self):
        self.first("--subheading-min", "1")
        self.assertIn("    소제목 수: 1~5개", self.ok("naver-profile", "show").splitlines())

    def test_the_other_end_of_the_subheading_range_changed_alone_shows_the_whole_range_too(self):
        self.first("--subheading-max", "7")
        self.assertIn("    소제목 수: 3~7개", self.ok("naver-profile", "show").splitlines())
        self.first("--subheading-min", "2", "--subheading-max", "5")
        self.assertIn("    소제목 수: 2~5개", self.ok("naver-profile", "show").splitlines())

    def test_a_stored_profile_whose_new_value_was_edited_by_hand_is_reported_not_crashed_on(self):
        self.first()
        path = self.ctx.workspace.settings_path
        data = json.loads(path.read_text(encoding="utf-8"))
        data["naver_profiles"]["naver_a"]["subheading_min"] = 99
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        lines = self.ok("naver-profile", "show").splitlines()
        self.assertEqual(lines[0], OLD_FIRST_LINE_A)
        self.assertIn("읽을 수 없습니다", lines[1])
        self.assertEqual(json.loads(self.ok("--json", "naver-profile", "show"))["data"]["profiles"]["naver_a"]["subheading_min"], 99, "JSON 은 저장된 그대로 보여 준다")

    def test_the_help_of_the_command_describes_the_new_options_in_korean(self):
        out = self.ok("naver-profile", "--help")
        for needle in ("--intro-style", "--subheading-min", "--subheading-max", "--difficulty", "--ending-style", "--excluded-topics", "--topic-reuse-days", "--post-type", "글 만들 때 쓰는 항목",
                       "정보형", "비교형", "소제목이 이보다 적으면"):
            self.assertIn(needle, out)
        for word in ("usage:", "positional arguments", "options:"):
            self.assertNotIn(word, out)


if __name__ == "__main__":
    unittest.main()
