"""발행 이력 읽기(`topics/history.py`) 시험 — 실제 블로그 저장소에서 확인한 **모양**과 같은 짧은 가짜 자료로, 관대하게 읽고(못 읽은 항목은 건너뛰며 경고) 지어내지 않고(모르면 None) 큰 칸은 읽지 않는다.

지키는 것:
  1) 읽는 모양 다섯 — `posts.json`(만든 결과 배열)·글 머리말·이력 항목 목록(Blogger·네이버 발행 이력)·`history.json`(제목 글자와 kr_title·en_title 항목)·네이버 항목 틀 — 이 모두 같은 `HistoryRecord` 로 나온다.
  2) 못 읽은 항목은 예외 없이 건너뛰고 '어느 항목이 왜' 를 쉬운 한국어 경고로 돌려준다. 어떤 이상한 입력(None·숫자·섞인 목록·거대한 목록)에도 멈추지 않는다.
  3) 날짜·주소·언어·글 번호·원천 주제는 모르면 None 이고(0 이나 기본값으로 채우지 않는다), 본문(`content`)·그림·상태 같은 칸은 읽지 않는다.
  4) 같은 입력은 늘 같은 결과이고 입력은 바뀌지 않는다. 이 모듈은 파일을 열지 않는다(값만 받는다).
시험 자료의 제목·키워드는 모두 지어낸 짧은 글이다(실제 글을 옮기지 않는다).
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import copy
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402, F401

from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import history as hs  # noqa: E402

# 실제 `posts.json` 결과 한 항목과 같은 칸(값은 지어낸 것)
POST = {"path": "_posts/Sample/2026-10-18-AI.md", "url": "/sample/2026/10/18/example/", "absoluteUrl": "https://blog.example.test/sample/2026/10/18/example/", "name": "2026-10-18-AI.md",
        "title": "예시 글 제목 하나", "category": "Sample", "lang": "kr", "date": "2026-10-18", "image": "https://images.example.test/a.png", "tags": ["예시", "표본"], "content": "<p>본문</p>" * 50,
        "contentIsHtml": True, "previewText": "미리보기"}
# 실제 `*_history.json` 한 항목과 같은 칸(값은 지어낸 것)
ENTRY = {"v": 1, "blog": "sample_blog", "date": "2026-10-21", "generated_at": "2026-10-21T01:03:39.091290+09:00", "status": "draft_uploaded", "topic": "예시 주제", "topic_source": "seed",
         "title": "예시 이력 제목", "labels": ["라벨 하나", "라벨 둘", "라벨 셋"], "url": "https://sample.example.test/", "post_id": "6324376636606257982", "model": "sample-model", "attempts": 1,
         "reasons": []}
HEADER = ('---\nlayout: post\ntitle: "예시 머리말 제목: 부제가 있는 경우"\ncategory: Sample\ntags: [예시, "쉼표, 들어간 태그", 표본]\nlang: ko\nsource_url: https://source.example.test/x\n'
          'source_name: "Example Source"\nimage: https://images.example.test/a.png\n---\n\n본문 첫 줄\n')
JUNK = (None, 3, 2.5, True, "글자", b"bytes", [], {}, [None], [[]], [[1, 2]], {"title": None}, {"title": 3}, {"title": []}, ("튜플",), {1, 2}, object())


def messages(result):
    return [warning.message() for warning in result.warnings]


class RecordTest(unittest.TestCase):
    def make(self, **changes):
        values = {"channel": "github_pages", "title": "예시 제목", "origin": hs.ORIGIN_POSTS}
        values.update(changes)
        return hs.HistoryRecord(**values)

    def test_a_minimal_record_has_unknown_values_as_none_and_not_as_zero_or_defaults(self):
        record = self.make()
        self.assertEqual((record.keywords, record.date, record.url, record.language, record.topic, record.ref), ((), None, None, None, None, None))

    def test_a_full_record_keeps_every_value(self):
        record = self.make(keywords=("가", "나"), date="2026-10-18", url="https://a.example.test/x", language="en", topic="주제", ref="2026-10-18-AI.md", origin=hs.ORIGIN_ENTRIES)
        self.assertEqual(record.to_dict(), {"channel": "github_pages", "title": "예시 제목", "keywords": ["가", "나"], "date": "2026-10-18", "url": "https://a.example.test/x", "language": "en",
                                            "topic": "주제", "ref": "2026-10-18-AI.md", "origin": "history_entries"})

    def test_every_wrong_value_is_refused(self):
        bad = (("channel", "blogger_a"), ("channel", None), ("title", ""), ("title", "두  칸"), ("title", "줄\n바꿈"), ("title", "x" * 301), ("title", 3), ("keywords", ["리스트"]), ("keywords", ("",)),
               ("keywords", ("x" * 61,)), ("keywords", tuple(f"k{n}" for n in range(21))), ("keywords", (3,)), ("date", "2026-13-01"), ("date", "1999-01-01"), ("date", "2026-1-1"), ("date", 20261018),
               ("url", "ftp://a.example.test/x"), ("url", "//a.example.test/x"), ("url", "javascript:alert(1)"), ("url", "a b"), ("url", ""), ("language", "kr"), ("language", "fr"),
               ("topic", ""), ("topic", "두  칸"), ("ref", "한글번호"), ("ref", "-abc"), ("ref", "x" * 121), ("ref", ""), ("origin", "other"), ("origin", None))
        for name, value in bad:
            with self.subTest(**{name: value}):
                with self.assertRaises(ValueError):
                    self.make(**{name: value})

    def test_the_limits_are_accepted_exactly(self):
        record = self.make(title="가" * hs.MAX_TITLE, keywords=tuple(f"k{n}" for n in range(hs.MAX_KEYWORDS)), ref="a" * 120, url="/" + "a" * (hs.MAX_URL - 1), topic="나" * 300)
        self.assertEqual(len(record.title), 300)

    def test_a_record_is_frozen_and_hashable_and_equal_when_the_values_are(self):
        record = self.make(keywords=("가",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.title = "바뀜"
        self.assertEqual(record, self.make(keywords=("가",)))
        self.assertEqual(len({record, self.make(keywords=("가",))}), 1)

    def test_the_constants_are_these(self):
        self.assertEqual(hs.ORIGINS, ("posts_json", "front_matter", "history_entries", "history_titles", "naver_items"))
        self.assertEqual(hs.NAVER_CHANNELS, ("naver_a", "naver_b"))
        self.assertEqual((hs.MAX_ITEMS, hs.MAX_TITLE, hs.MAX_KEYWORDS), (20_000, 300, 20))


class PostsJsonTest(unittest.TestCase):
    def test_a_real_shaped_item_becomes_one_github_pages_record_without_the_body(self):
        result = hs.read_posts_json([POST])
        self.assertEqual(result.warnings, ())
        record = result.records[0]
        self.assertEqual((record.channel, record.title, record.keywords, record.date, record.language, record.ref, record.origin),
                         ("github_pages", "예시 글 제목 하나", ("예시", "표본"), "2026-10-18", "ko", "2026-10-18-AI", "posts_json"))      # P2b(독립 검증 M5) 의도적 갱신: 글 번호는 `.md` 를 뗀 모양이다(머리말 길과 같은 글에 같은 번호)
        self.assertEqual(record.url, "https://blog.example.test/sample/2026/10/18/example/", "절대 주소를 먼저 쓴다")
        self.assertNotIn("content", record.to_dict())
        self.assertNotIn("본문", repr(record))

    def test_the_relative_address_is_used_when_there_is_no_absolute_one_and_a_bad_one_is_dropped_with_a_warning(self):
        no_abs = dict(POST, absoluteUrl="")
        self.assertEqual(hs.read_posts_json([no_abs]).records[0].url, "/sample/2026/10/18/example/")
        both_bad = dict(POST, absoluteUrl="not a url", url="javascript:x")
        result = hs.read_posts_json([both_bad])
        self.assertIsNone(result.records[0].url)
        self.assertTrue(any("주소" in text and text.endswith("나머지는 그대로 읽습니다") for text in messages(result)))
        none = {"title": "주소 없음"}
        self.assertEqual(hs.read_posts_json([none]).warnings, ())

    def test_the_language_names_of_the_site_are_translated_and_unknown_ones_stay_unknown(self):
        for lang, expected in (("kr", "ko"), ("ko", "ko"), ("en", "en"), ("EN", "en"), (" kr ", "ko"), ("fr", None), ("", None), (None, None), (3, None)):
            with self.subTest(lang=lang):
                self.assertEqual(hs.read_posts_json([dict(POST, lang=lang)]).records[0].language, expected)
        missing = {key: value for key, value in POST.items() if key != "lang"}
        self.assertIsNone(hs.read_posts_json([missing]).records[0].language)

    def test_a_bad_date_is_dropped_with_a_warning_and_a_missing_date_is_just_none(self):
        for bad in ("2026-13-45", "어제", "2026/10/18", 20261018, "1999-01-01"):
            with self.subTest(date=bad):
                result = hs.read_posts_json([dict(POST, date=bad)])
                self.assertIsNone(result.records[0].date)
                self.assertTrue(any("날짜" in text for text in messages(result)))
        for missing in (None, ""):
            result = hs.read_posts_json([dict(POST, date=missing)])
            self.assertEqual((result.records[0].date, result.warnings), (None, ()))

    def test_tags_become_keywords_once_each_and_a_bad_tag_list_is_dropped_with_a_warning(self):
        self.assertEqual(hs.read_posts_json([dict(POST, tags=["가", "나", "가", " 나 ", "다"])]).records[0].keywords, ("가", "나", "다"))
        self.assertEqual(hs.read_posts_json([dict(POST, tags=None)]).records[0].keywords, ())
        for bad in ("문자열 하나", 3, {"a": 1}):
            with self.subTest(tags=bad):
                result = hs.read_posts_json([dict(POST, tags=bad)])
                self.assertEqual(result.records[0].keywords, ())
                self.assertTrue(any("키워드" in text for text in messages(result)))
        many = hs.read_posts_json([dict(POST, tags=[f"태그{n}" for n in range(25)] )])
        self.assertEqual(len(many.records[0].keywords), hs.MAX_KEYWORDS)
        self.assertTrue(any("키워드 일부" in text for text in messages(many)))
        odd = hs.read_posts_json([dict(POST, tags=["좋음", 3, "", None, "x" * 61, "또 좋음"])])
        self.assertEqual(odd.records[0].keywords, ("좋음", "또 좋음"))
        self.assertTrue(any("키워드 일부" in text for text in messages(odd)))

    def test_items_without_a_usable_title_are_skipped_with_the_item_number_in_the_warning(self):
        items = [POST, {"date": "2026-10-18"}, "문자열", {"title": "  "}, {"title": 3}, None, dict(POST, title="마지막 글")]
        result = hs.read_posts_json(items)
        self.assertEqual([record.title for record in result.records], ["예시 글 제목 하나", "마지막 글"])
        skipped = [warning for warning in result.warnings if warning.skipped]
        self.assertEqual([warning.where for warning in skipped], ["항목 2", "항목 3", "항목 4", "항목 5", "항목 6"])
        self.assertTrue(all(warning.message().endswith("건너뜁니다") for warning in skipped))

    def test_a_long_title_is_cut_with_a_warning(self):
        result = hs.read_posts_json([dict(POST, title="가" * 400)])
        self.assertEqual(len(result.records[0].title), 300)
        self.assertTrue(any("너무 길어" in text for text in messages(result)))

    def test_the_title_is_cleaned_to_one_line_and_hidden_characters_are_removed(self):
        title = "줄\n바꿈  과\t탭" + chr(0x200B) + "숨은글자"
        self.assertEqual(hs.read_posts_json([dict(POST, title=title)]).records[0].title, "줄 바꿈 과 탭숨은글자")

    def test_a_value_that_is_not_a_list_gives_no_records_and_one_whole_list_warning(self):
        for value in (None, {}, {"posts": [POST]}, "글", 3, POST):
            with self.subTest(value=repr(value)[:20]):
                result = hs.read_posts_json(value)
                self.assertEqual(result.records, ())
                self.assertEqual([warning.where for warning in result.warnings], ["목록 전체"])
        self.assertEqual(hs.read_posts_json([]), hs.HistoryResult((), ()))

    def test_a_huge_list_is_read_up_to_the_limit_with_one_warning(self):
        result = hs.read_posts_json([{"title": f"t{n}"} for n in range(hs.MAX_ITEMS + 5)])
        self.assertEqual(len(result.records), hs.MAX_ITEMS)
        self.assertEqual([warning.where for warning in result.warnings], ["목록 전체"])
        self.assertEqual(hs.read_posts_json([{"title": f"t{n}"} for n in range(hs.MAX_ITEMS)]).warnings, ())

    def test_the_order_is_the_input_order_and_the_input_is_not_changed(self):
        items = [dict(POST, title=f"글 {n}", date=f"2026-10-{20 - n:02d}") for n in range(5)]
        before = copy.deepcopy(items)
        first, second = hs.read_posts_json(items), hs.read_posts_json(tuple(items))
        self.assertEqual(first, second)
        self.assertEqual([record.title for record in first.records], [f"글 {n}" for n in range(5)])
        self.assertEqual(items, before)


class DayDigitsTest(unittest.TestCase):
    # P2b(독립 검증 M6 ②): 날짜 정규식의 `[0-9]` 를 `\d` 로 바꿔도 시험이 통과했다 — 전각·아랍 숫자 날짜는 날짜가 아니다.
    def test_only_ascii_digits_make_a_day(self):
        for good in ("2026-11-05", "2000-01-01", "2200-12-31", "2028-02-29"):
            self.assertEqual(hs.valid_day(good), good)
        fullwidth = "".join(chr(ord(ch) + 0xFEE0) if ch.isdigit() else ch for ch in "2026-11-05")
        arabic = "".join(chr(0x0660 + int(ch)) if ch.isdigit() else ch for ch in "2026-11-05")
        devanagari = "".join(chr(0x0966 + int(ch)) if ch.isdigit() else ch for ch in "2026-11-05")
        mixed = "2026-" + chr(0x0661) + chr(0x0661) + "-05"
        for bad in (fullwidth, arabic, devanagari, mixed, "2026-11-05" + chr(10), " 2026-11-05","2026-11-05 ", "2026/11/05", "26-11-05", "2026-1-05", "2026-02-30", "1999-12-31", "", None, 20261105):
            with self.subTest(day=repr(bad)[:20]):
                self.assertIsNone(hs.valid_day(bad))

    def test_a_record_and_the_readers_refuse_such_dates_too(self):
        arabic = "".join(chr(0x0660 + int(ch)) if ch.isdigit() else ch for ch in "2026-10-18")
        with self.assertRaises(ValueError):
            hs.HistoryRecord(channel="github_pages", title="예시", date=arabic, origin="posts_json")
        result = hs.read_posts_json([dict(POST, date=arabic)])
        self.assertIsNone(result.records[0].date)
        self.assertEqual(messages(result), ["항목 1: 날짜를 읽지 못했습니다 — 나머지는 그대로 읽습니다"])


class SameRefTest(unittest.TestCase):
    # P2b(독립 검증 M5): 같은 글이 `posts.json` 길과 머리말 길로 들어오면 서로 다른 글 번호(`…KR-000001.md` 와 `…KR-000001`)가 되어 서로 다른 글로 세어질 수 있었다.
    def test_the_two_paths_give_the_same_ref_for_the_same_post_file(self):
        for name in ("2026-10-18-KR-000001.md", "2026-10-18-AI.md", "2026-10-18-EN-225949.md", "2026-10-19-KR-233513.md"):
            with self.subTest(name=name):
                from_json = hs.read_posts_json([dict(POST, name=name)]).records[0]
                from_header = hs.read_front_matter(HEADER, filename=name).records[0]
                self.assertEqual(from_json.ref, from_header.ref)
                self.assertEqual(from_json.ref, name[:-3])
                self.assertFalse(from_json.ref.endswith(".md"))

    def test_a_path_or_an_upper_case_extension_is_cut_the_same_way_on_both_paths(self):
        for name in ("_posts/Sample/2026-10-18-KR-000001.md", "_posts\\Sample\\2026-10-18-KR-000001.md", "2026-10-18-KR-000001.MD", "2026-10-18-KR-000001.Md"):
            with self.subTest(name=name):
                self.assertEqual(hs.read_posts_json([dict(POST, name=name)]).records[0].ref, "2026-10-18-KR-000001")
                self.assertEqual(hs.read_front_matter(HEADER, filename=name).records[0].ref, "2026-10-18-KR-000001")

    def test_a_name_without_the_extension_or_a_number_name_is_kept_and_a_missing_or_odd_name_gives_no_ref(self):
        self.assertEqual(hs.read_posts_json([dict(POST, name="2026-10-18-KR-000001")]).records[0].ref, "2026-10-18-KR-000001")
        self.assertEqual(hs.read_posts_json([dict(POST, name=12345)]).records[0].ref, "12345")
        for name in (None, "", ".md", "한글.md"):
            with self.subTest(name=name):
                self.assertIsNone(hs.read_posts_json([dict(POST, name=name)]).records[0].ref)


class FrontMatterTest(unittest.TestCase):
    def test_a_real_shaped_header_gives_the_title_tags_language_and_the_date_from_the_file_name(self):
        result = hs.read_front_matter(HEADER, filename="2026-10-18-AI.md")
        self.assertEqual(result.warnings, ())
        record = result.records[0]
        self.assertEqual((record.channel, record.title, record.keywords, record.date, record.language, record.ref, record.origin),
                         ("github_pages", "예시 머리말 제목: 부제가 있는 경우", ("예시", "쉼표, 들어간 태그", "표본"), "2026-10-18", "ko", "2026-10-18-AI", "front_matter"))
        self.assertIsNone(record.url)

    def test_a_title_that_is_only_a_yaml_marker_is_not_read_as_a_title(self):
        # P2b(독립 검증 L5): `title: >`·`|-`·`null`·`~`·`true` 가 그대로 제목이 되어 '>' 나 'null' 이라는 글이 이력에 들어갔다.
        for marker in (">", "|", ">-", "|-", ">+", "|+", "null", "Null", "NULL", "~", "true", "True", "false", "FALSE"):
            with self.subTest(marker=marker):
                result = hs.read_front_matter(f"---\ntitle: {marker}\ntags: [가]\n---\n본문\n", filename="2026-10-18-KR-000001.md")
                self.assertEqual(result.records, ())
                self.assertEqual(len(result.warnings), 1)
                self.assertTrue(result.warnings[0].skipped)
                self.assertIn("YAML 표시", result.warnings[0].message())

    def test_a_quoted_marker_or_a_title_that_only_starts_like_one_is_a_real_title(self):
        for raw, expected in (('"null"', "null"), ("'true'", "true"), ('">"', ">"), ("nullable 이야기", "nullable 이야기"), ("true story", "true story"), ("~물결", "~물결"), ("> 인용 같은 제목", "> 인용 같은 제목")):
            with self.subTest(raw=raw):
                result = hs.read_front_matter(f"---\ntitle: {raw}\n---\n본문\n")
                self.assertEqual([record.title for record in result.records], [expected])

    def test_an_unreadable_header_date_is_a_warning_and_falls_back_to_the_file_name_day(self):
        # 독립 검증 L5: 머리말 날짜가 틀려도 경고 없이 파일 이름의 날짜가 쓰였다.
        broken = HEADER.replace("lang: ko\n", "lang: ko\ndate: 어제 오후\n")
        result = hs.read_front_matter(broken, filename="2026-10-18-KR-000001.md")
        self.assertEqual(result.records[0].date, "2026-10-18")
        self.assertEqual(messages(result), ["머리말: 머리말 날짜를 읽지 못했습니다(파일 이름의 날짜를 씁니다) — 나머지는 그대로 읽습니다"])
        none_at_all = hs.read_front_matter(broken, filename="이름.md")
        self.assertIsNone(none_at_all.records[0].date)
        self.assertEqual(messages(none_at_all), ["머리말: 머리말 날짜를 읽지 못했습니다 — 나머지는 그대로 읽습니다"])
        self.assertEqual(hs.read_front_matter(HEADER.replace("lang: ko\n", "lang: ko\ndate: 2026-10-20T09:00:00+09:00\n"), filename="2026-10-18-KR-000001.md").warnings, ())
        self.assertEqual(hs.read_front_matter(HEADER.replace("lang: ko\n", "lang: ko\ndate:\n"), filename="2026-10-18-KR-000001.md").warnings, (), "비어 있는 날짜는 없는 것과 같다")

    def test_the_directory_part_of_the_file_name_is_ignored_for_both_slash_kinds(self):
        for name in ("_posts/EN - Space/2026-10-19-KR-233513.md", "_posts\\KR - Tech\\2026-10-19-KR-233513.md", "2026-10-19-KR-233513.md"):
            with self.subTest(filename=name):
                record = hs.read_front_matter(HEADER, filename=name).records[0]
                self.assertEqual((record.date, record.ref), ("2026-10-19", "2026-10-19-KR-233513"))

    def test_the_language_comes_from_lang_or_from_the_en_marker_in_the_file_name_and_otherwise_is_unknown(self):
        no_lang = HEADER.replace("lang: ko\n", "")
        self.assertEqual(hs.read_front_matter(no_lang, filename="2026-10-18-EN-225949.md").records[0].language, "en")
        self.assertEqual(hs.read_front_matter(no_lang, filename="2026-10-18-en-1.md").records[0].language, "en")
        self.assertIsNone(hs.read_front_matter(no_lang, filename="2026-10-18-KR-225949.md").records[0].language)
        self.assertIsNone(hs.read_front_matter(no_lang).records[0].language)
        self.assertEqual(hs.read_front_matter(HEADER.replace("lang: ko", "lang: en"), filename="2026-10-18-KR-1.md").records[0].language, "en")
        self.assertEqual(hs.read_front_matter(HEADER.replace("lang: ko", "lang: kr")).records[0].language, "ko")

    def test_a_date_line_in_the_header_wins_over_the_file_name_and_may_carry_a_time(self):
        for line, expected in (("date: 2026-09-01", "2026-09-01"), ("date: 2026-09-01 09:00:00 +0900", "2026-09-01"), ('date: "2026-09-01T09:00:00+09:00"', "2026-09-01")):
            with self.subTest(line=line):
                record = hs.read_front_matter(HEADER.replace("lang: ko", line), filename="2026-10-18-AI.md").records[0]
                self.assertEqual(record.date, expected)

    def test_a_bad_header_date_falls_back_to_the_file_name_and_no_date_at_all_is_none(self):
        bad = HEADER.replace("lang: ko", "date: 어제")
        self.assertEqual(hs.read_front_matter(bad, filename="2026-10-18-AI.md").records[0].date, "2026-10-18")
        self.assertIsNone(hs.read_front_matter(bad).records[0].date)
        self.assertIsNone(hs.read_front_matter(HEADER, filename="no-date-here.md").records[0].date)
        self.assertIsNone(hs.read_front_matter(HEADER, filename="2026-13-45-bad.md").records[0].date)

    def test_windows_line_endings_a_leading_bom_and_block_style_tags_are_read(self):
        crlf = HEADER.replace("\n", "\r\n")
        self.assertEqual(hs.read_front_matter(crlf, filename="2026-10-18-AI.md").records[0].keywords, ("예시", "쉼표, 들어간 태그", "표본"))
        bom = chr(0xFEFF) + HEADER
        self.assertEqual(hs.read_front_matter(bom).records[0].title, "예시 머리말 제목: 부제가 있는 경우")
        block = HEADER.replace('tags: [예시, "쉼표, 들어간 태그", 표본]', "tags:\n  - 첫째\n  - '둘째'\n- 셋째")
        self.assertEqual(hs.read_front_matter(block).records[0].keywords, ("첫째", "둘째", "셋째"))
        self.assertEqual(hs.read_front_matter(HEADER.replace('tags: [예시, "쉼표, 들어간 태그", 표본]\n', "")).records[0].keywords, ())

    def test_quotes_around_the_title_are_removed_and_escaped_quotes_are_kept(self):
        for line, expected in (('title: "큰따옴표 제목"', "큰따옴표 제목"), ("title: '작은따옴표 제목'", "작은따옴표 제목"), ("title: 따옴표 없는 제목", "따옴표 없는 제목"),
                               ('title: "말했다 \\"안녕\\" 라고"', '말했다 "안녕" 라고'), ("title: 'it''s fine'", "it's fine"), ('title: "여는 따옴표만', '"여는 따옴표만')):
            with self.subTest(line=line):
                text = "---\n" + line + "\n---\n본문"
                self.assertEqual(hs.read_front_matter(text).records[0].title, expected)

    def test_a_tag_list_that_is_not_in_brackets_is_dropped_with_a_warning_and_the_record_is_still_read(self):
        result = hs.read_front_matter(HEADER.replace('tags: [예시, "쉼표, 들어간 태그", 표본]', "tags: 예시, 표본"))
        self.assertEqual(result.records[0].keywords, ())
        self.assertTrue(any("tags" in text for text in messages(result)))

    def test_text_without_a_usable_header_gives_no_record_and_one_skipped_warning(self):
        cases = ("본문만 있는 글", "", "  ---\ntitle: x\n---", "---\ntitle: 닫히지 않음\n본문", "---\nlayout: post\n---\n본문", "---\ntitle:\n---\n본문", '---\ntitle: ""\n---\n', "---\ntitle: '   '\n---\n")
        for text in cases:
            with self.subTest(text=text[:25]):
                result = hs.read_front_matter(text)
                self.assertEqual(result.records, ())
                self.assertEqual(len(result.warnings), 1)
                self.assertTrue(result.warnings[0].skipped)
        for value in (None, 3, b"---\ntitle: x\n---", ["---"]):
            with self.subTest(value=repr(value)[:15]):
                self.assertEqual(hs.read_front_matter(value).records, ())

    def test_only_the_header_is_read_and_a_body_line_that_looks_like_a_key_is_ignored(self):
        text = "---\ntitle: 진짜 제목\n---\n\ntitle: 본문 속 가짜 제목\ntags: [가짜]\n"
        record = hs.read_front_matter(text).records[0]
        self.assertEqual((record.title, record.keywords), ("진짜 제목", ()))

    def test_indented_lines_in_the_header_are_not_new_keys_and_comments_are_ignored(self):
        text = "---\n# 주석 줄\ntitle: 제목\n  title: 들여쓴 가짜\nimage: x\n---\n"
        self.assertEqual(hs.read_front_matter(text).records[0].title, "제목")

    def test_a_long_title_is_cut_with_a_warning_and_an_odd_file_name_gives_no_reference(self):
        result = hs.read_front_matter("---\ntitle: " + "가" * 350 + "\n---\n", filename="한글 이름 파일.md")
        self.assertEqual(len(result.records[0].title), 300)
        self.assertIsNone(result.records[0].ref)
        self.assertTrue(any("너무 길어" in text for text in messages(result)))

    def test_the_file_name_argument_is_optional_and_a_wrong_kind_is_ignored(self):
        for name in ("", None, 3, b"x"):
            with self.subTest(filename=name):
                record = hs.read_front_matter(HEADER, filename=name).records[0]
                self.assertEqual((record.date, record.ref), (None, None))


class HistoryEntriesTest(unittest.TestCase):
    def test_a_real_shaped_entry_becomes_a_record_for_the_given_channel_and_ignores_status_and_model(self):
        for channel in ch.CHANNELS:
            with self.subTest(channel=channel):
                result = hs.read_history_entries([ENTRY], channel)
                self.assertEqual(result.warnings, ())
                record = result.records[0]
                self.assertEqual((record.channel, record.title, record.keywords, record.date, record.url, record.topic, record.ref, record.language, record.origin),
                                 (channel, "예시 이력 제목", ("라벨 하나", "라벨 둘", "라벨 셋"), "2026-10-21", "https://sample.example.test/", "예시 주제", "6324376636606257982", None, "history_entries"))
        for forbidden in ("status", "model", "attempts", "reasons", "generated_at"):
            self.assertNotIn(forbidden, hs.read_history_entries([ENTRY], "blogger_ko").records[0].to_dict())

    def test_the_date_comes_from_generated_at_when_there_is_no_date_and_the_post_id_may_be_a_number(self):
        without = {key: value for key, value in ENTRY.items() if key != "date"}
        self.assertEqual(hs.read_history_entries([without], "naver_a").records[0].date, "2026-10-21")
        self.assertIsNone(hs.read_history_entries([dict(without, generated_at="어제")], "naver_a").records[0].date)
        self.assertIsNone(hs.read_history_entries([{key: value for key, value in without.items() if key != "generated_at"}], "naver_a").records[0].date)
        self.assertEqual(hs.read_history_entries([dict(ENTRY, post_id=88)], "naver_a").records[0].ref, "88")
        self.assertIsNone(hs.read_history_entries([dict(ENTRY, post_id=True)], "naver_a").records[0].ref)
        self.assertIsNone(hs.read_history_entries([dict(ENTRY, post_id="")], "naver_a").records[0].ref)

    def test_an_empty_address_is_none_without_a_warning_and_a_bad_one_gives_a_warning(self):
        result = hs.read_history_entries([dict(ENTRY, url="")], "blogger_ko")
        self.assertEqual((result.records[0].url, result.warnings), (None, ()))
        bad = hs.read_history_entries([dict(ENTRY, url="주소 아님")], "blogger_ko")
        self.assertIsNone(bad.records[0].url)
        self.assertTrue(any("주소" in text for text in messages(bad)))

    def test_missing_labels_and_topic_stay_empty(self):
        record = hs.read_history_entries([{"title": "제목만"}], "blogger_en").records[0]
        self.assertEqual((record.keywords, record.topic, record.date, record.url, record.ref), ((), None, None, None, None))

    def test_the_second_shape_variant_with_an_extra_image_key_is_fine(self):
        self.assertEqual(len(hs.read_history_entries([dict(ENTRY, image="https://i.example.test/x.png")], "blogger_ko").records), 1)

    def test_entries_without_a_title_or_that_are_not_objects_are_skipped(self):
        result = hs.read_history_entries([ENTRY, {"topic": "제목 없음"}, "문자열", None, dict(ENTRY, title="끝")], "blogger_ko")
        self.assertEqual([record.title for record in result.records], ["예시 이력 제목", "끝"])
        self.assertEqual([warning.where for warning in result.warnings if warning.skipped], ["항목 2", "항목 3", "항목 4"])

    def test_an_unknown_channel_is_a_programming_error(self):
        for channel in ("blogger_a", "naver", None, 3, ""):
            with self.subTest(channel=channel):
                with self.assertRaises(ValueError):
                    hs.read_history_entries([ENTRY], channel)

    def test_the_topic_is_cut_when_too_long_with_a_warning(self):
        result = hs.read_history_entries([dict(ENTRY, topic="주" * 400)], "blogger_ko")
        self.assertEqual(len(result.records[0].topic), 300)
        self.assertTrue(any("원천 주제" in text for text in messages(result)))
        self.assertIsNone(hs.read_history_entries([dict(ENTRY, topic=3)], "blogger_ko").records[0].topic)


class TitlesTest(unittest.TestCase):
    ENTRY = {"date": "2026-10-19", "topic": "예시 원천 주제", "kr_title": "예시 한글 제목", "en_title": "Example English Title", "kr_image": "https://i.example.test/k.png",
             "en_image": "https://i.example.test/e.png", "slot": 9, "lane": "technology", "source": "Example Source", "source_url": "https://source.example.test/news/1"}

    def test_a_plain_string_is_a_title_and_nothing_else(self):
        record = hs.read_titles(["예시 제목 글자"]).records[0]
        self.assertEqual((record.channel, record.title, record.date, record.language, record.topic, record.origin), ("github_pages", "예시 제목 글자", None, None, None, "history_titles"))

    def test_an_item_with_both_titles_gives_a_korean_and_an_english_record_that_share_date_and_topic(self):
        result = hs.read_titles([self.ENTRY])
        self.assertEqual([(record.title, record.language, record.date, record.topic) for record in result.records],
                         [("예시 한글 제목", "ko", "2026-10-19", "예시 원천 주제"), ("Example English Title", "en", "2026-10-19", "예시 원천 주제")])
        self.assertEqual(result.warnings, ())

    def test_the_source_address_and_images_are_not_taken_as_the_address_of_the_post(self):
        for record in hs.read_titles([self.ENTRY]).records:
            self.assertIsNone(record.url)
            self.assertNotIn("source", repr(record.to_dict()).replace("origin", ""))

    def test_one_title_missing_gives_one_record_and_both_missing_falls_back_to_the_topic(self):
        only_kr = {key: value for key, value in self.ENTRY.items() if key != "en_title"}
        self.assertEqual([record.language for record in hs.read_titles([only_kr]).records], ["ko"])
        neither = {key: value for key, value in self.ENTRY.items() if key not in ("kr_title", "en_title")}
        record = hs.read_titles([neither]).records[0]
        self.assertEqual((record.title, record.language, record.topic), ("예시 원천 주제", None, None))
        nothing = {key: value for key, value in neither.items() if key != "topic"}
        result = hs.read_titles([nothing])
        self.assertEqual((result.records, [warning.skipped for warning in result.warnings]), ((), [True]))

    def test_a_mixed_list_is_read_in_order_and_junk_items_are_skipped(self):
        result = hs.read_titles(["첫 글자", self.ENTRY, 3, None, "", "   ", "끝 글자"])
        self.assertEqual([record.title for record in result.records], ["첫 글자", "예시 한글 제목", "Example English Title", "끝 글자"])
        self.assertEqual([warning.where for warning in result.warnings if warning.skipped], ["항목 3", "항목 4", "항목 5", "항목 6"])

    def test_a_blank_korean_title_is_not_a_record(self):
        result = hs.read_titles([dict(self.ENTRY, kr_title="   ")])
        self.assertEqual([record.language for record in result.records], ["en"])


class NaverItemsTest(unittest.TestCase):
    ITEM = {"title": "예시 네이버 글", "keywords": ["키워드 하나", "키워드 둘"], "date": "2026-11-01", "url": "https://blog.naver.com/example/1", "ref": "n-1", "topic": "예시 주제"}

    def test_the_frame_reads_items_for_the_two_naver_channels_only(self):
        for channel in hs.NAVER_CHANNELS:
            with self.subTest(channel=channel):
                result = hs.read_naver_items([self.ITEM], channel)
                self.assertEqual(result.warnings, ())
                record = result.records[0]
                self.assertEqual((record.channel, record.title, record.keywords, record.date, record.url, record.ref, record.topic, record.origin),
                                 (channel, "예시 네이버 글", ("키워드 하나", "키워드 둘"), "2026-11-01", "https://blog.naver.com/example/1", "n-1", "예시 주제", "naver_items"))
        for channel in ("github_pages", "blogger_ko", "blogger_en", "naver", None):
            with self.subTest(channel=channel):
                with self.assertRaises(ValueError):
                    hs.read_naver_items([self.ITEM], channel)

    def test_missing_values_are_none_and_a_missing_title_skips_the_item(self):
        record = hs.read_naver_items([{"title": "제목만"}], "naver_a").records[0]
        self.assertEqual((record.keywords, record.date, record.url, record.ref, record.topic), ((), None, None, None, None))
        result = hs.read_naver_items([{"keywords": ["x"]}, self.ITEM], "naver_b")
        self.assertEqual((len(result.records), len(result.warnings)), (1, 1))

    def test_it_does_not_read_any_file_or_store_it_only_takes_values(self):
        import inspect
        source = inspect.getsource(hs.read_naver_items)
        for word in ("open(", "Path", "sqlite", "import "):
            self.assertNotIn(word, source)


class NeverStopsTest(unittest.TestCase):
    READERS = (("posts", hs.read_posts_json), ("entries", lambda value: hs.read_history_entries(value, "blogger_ko")), ("titles", hs.read_titles),
               ("naver", lambda value: hs.read_naver_items(value, "naver_a")))

    def test_junk_as_the_whole_value_or_as_an_item_never_raises(self):
        for name, reader in self.READERS:
            for junk in JUNK:
                with self.subTest(reader=name, whole=repr(junk)[:20]):
                    self.assertIsInstance(reader(junk), hs.HistoryResult)
                with self.subTest(reader=name, item=repr(junk)[:20]):
                    result = reader([junk])
                    self.assertIsInstance(result, hs.HistoryResult)
                    for record in result.records:
                        self.assertIsInstance(record, hs.HistoryRecord)

    def test_junk_as_the_header_text_never_raises(self):
        for junk in JUNK + ("---", "---\n---", "---\n: x\n---", "---\n\x00\n---"):
            with self.subTest(text=repr(junk)[:20]):
                self.assertIsInstance(hs.read_front_matter(junk), hs.HistoryResult)

    def test_every_field_with_every_kind_of_junk_never_raises(self):
        for key in ("title", "date", "url", "absoluteUrl", "name", "tags", "lang", "labels", "topic", "post_id", "generated_at", "kr_title", "en_title", "keywords", "ref"):
            for junk in JUNK:
                base = {"title": "제목", "kr_title": "한글", "en_title": "English"}
                base[key] = junk
                for name, reader in self.READERS:
                    with self.subTest(key=key, junk=repr(junk)[:15], reader=name):
                        self.assertIsInstance(reader([base]), hs.HistoryResult)

    def test_a_warning_always_says_where_and_why_in_plain_words(self):
        result = hs.read_posts_json([None, {"title": 3}, POST, "x"])
        for warning in result.warnings:
            self.assertTrue(warning.where and warning.reason)
            self.assertTrue(warning.message().startswith(warning.where))


if __name__ == "__main__":
    unittest.main()
