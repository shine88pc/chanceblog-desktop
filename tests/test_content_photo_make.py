"""본문 생성기에 사진을 이은 길(`draft_body.build_body(photos=…)` — 사진 연동 3단계) 시험 — 순수 함수라 파일·네트워크·PySide6·실제 시크릿 없이 돈다.

지키는 것:
  1) 사진이 없으면(`()`·`[]`) 초안이 지금과 한 글자도 다르지 않다 — 후보 14개 × 네이버 A·B.
  2) 사진이 있으면 틀로 만든 문단은 그대로이고 사진 줄만 더해진다(자리표시자 줄은 틀로 만든 글, 설명 글·대상 문장·메모는 사용자 글). 제목·키워드·태그·요약은 같다.
  3) 글자 수·복사용 글은 끼운 뒤의 본문으로 센다. 못 찾은 자리는 확인 권장에 사진 번호로만 적힌다. 같은 입력은 늘 같은 결과다.
  4) 마지막 관문은 그대로다 — 사진 글에 키 모양이 있으면 만들지 않고, 모든 후보·블로그에서 '지어내지 않기' 검사를 통과한다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_content_draft_body import CANDIDATES, KEY, body_of, expect_error, make  # noqa: E402
from test_content_photo_flow import photo  # noqa: E402

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.content import draft_body as db  # noqa: E402
from chanceblog_desktop.content import photo_flow as pf  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402

PHOTOS = (photo(1, kind="top", subject="매장 입구 간판", note="주차는 뒤쪽이에요"), photo(2, section="내용 소제목", subject="대표 메뉴", caption="메뉴판 앞에서"), photo(3, section="마무리", note="마무리 한마디"),
          photo(4, kind="after_paragraph", nth=50, section="내용 소제목"))
NOTE = "사진 4번은 문단이 모자라 그 소제목의 마지막 문단 뒤에 넣었어요."


def photo_lines():
    return {text for item in PHOTOS for text, _made in pf.photo_lines(item)}


class SameWithoutPhotosTest(unittest.TestCase):
    def test_no_photos_gives_the_very_same_draft_for_every_candidate_and_blog(self):
        for number, row in enumerate(CANDIDATES):
            candidate = make(*row)
            for blog in ("naver_a", "naver_b"):
                with self.subTest(candidate=number, blog=blog):
                    plain = body_of(candidate, None, None, blog)
                    self.assertEqual(plain, body_of(candidate, None, None, blog, photos=()))
                    self.assertEqual(plain, body_of(candidate, None, None, blog, photos=[]))

    def test_photos_never_change_the_titles_keywords_tags_summary_or_category(self):
        plain, placed = body_of(), body_of(photos=PHOTOS)
        for name in ("titles", "selected_title", "core_keywords", "sub_keywords", "tags", "category", "summary", "style", "domain", "audience", "blog", "post_type", "sensitive", "used"):
            self.assertEqual(getattr(placed, name), getattr(plain, name), name)


class PlacedTest(unittest.TestCase):
    def test_the_placeholders_are_in_the_body_text_the_top_one_first_and_the_closing_one_last(self):
        body = body_of(photos=PHOTOS)
        found = [number for number, _start, _end in pm.find_placeholders(body.body_text)]
        self.assertEqual(sorted(found), [1, 2, 3, 4])
        self.assertEqual((found[0], found[-1]), (1, 3))
        self.assertTrue(body.body_text.startswith("{{사진 1}}"))
        self.assertEqual(pm.stray_braces(body.body_text), 0)

    def test_the_made_paragraphs_are_the_same_and_only_the_photo_lines_are_added(self):
        plain, placed = body_of(), body_of(photos=PHOTOS)
        extra = photo_lines()
        self.assertEqual(len(plain.blocks), len(placed.blocks))
        for before, after in zip(plain.blocks, placed.blocks):
            self.assertEqual((before.kind, before.key, before.heading), (after.kind, after.key, after.heading))
            kept = [(text, made) for text, made in zip(after.paragraphs, after.generated) if text not in extra]
            self.assertEqual(kept, list(zip(before.paragraphs, before.generated)))

    def test_user_lines_are_marked_user_and_only_the_placeholders_are_made_by_the_app(self):
        placed = body_of(photos=PHOTOS)
        user = [text for text in placed.user_paragraphs()]
        expected = [text for item in PHOTOS for text, made in pf.photo_lines(item) if not made]
        self.assertEqual(sorted(user), sorted(expected))
        self.assertEqual(body_of().user_paragraphs(), ())
        photo_made = sorted(text for text in placed.generated_texts() if text.startswith("{{사진 "))
        self.assertEqual(photo_made, ["{{사진 1}}", "{{사진 2}}", "{{사진 3}}", "{{사진 4}}"])

    def test_counts_and_the_copy_text_follow_the_final_body(self):
        body = body_of(photos=PHOTOS)
        self.assertEqual((body.chars, body.chars_with_spaces), db.count_chars(body.body_text))
        self.assertEqual(body.plain_text, body.selected_title + "\n\n" + body.body_text)
        self.assertGreater(body.chars, body_of().chars)

    def test_notes_for_a_moved_photo_go_to_the_checks_by_number_and_nowhere_else(self):
        body = body_of(photos=PHOTOS)
        self.assertIn(NOTE, body.checks)
        self.assertNotIn(NOTE, body_of().checks)
        self.assertEqual(body.checks[:len(body_of().checks)], body_of().checks, "원래 확인 권장은 그대로 앞에 있다")
        self.assertEqual(len(body.checks), len(set(body.checks)))

    def test_a_three_hundred_char_memo_goes_through_the_whole_build_though_the_must_include_limit_is_two_hundred(self):
        """검증 Q-13 — 사진 메모의 한도는 사진 규칙의 300자이고 `DraftOptions` 의 문장 한도(200자)와 다르다 — 메모는 `place_photos` 로만 들어가므로 거절되지 않는다."""
        memo = "가" * 300
        body = body_of(photos=(photo(1, note=memo),))
        self.assertIn(memo, body.body_text)
        self.assertIn(memo, body.user_paragraphs())

    def test_the_same_input_gives_the_same_draft_twice(self):
        self.assertEqual(body_of(photos=PHOTOS), body_of(photos=PHOTOS))
        self.assertEqual(body_of(photos=PHOTOS).to_dict(), body_of(photos=tuple(reversed(PHOTOS))).to_dict(), "사진을 넘기는 순서는 상관없다(display_order 로 정한다)")


class GuardTest(unittest.TestCase):
    def test_a_key_shape_in_a_photo_text_stops_the_draft_without_a_body(self):
        expect_error(self, lambda: body_of(photos=(photo(1, note="내 키는 " + KEY + " 이다"),)), "CONTENT_INVALID")
        expect_error(self, lambda: body_of(photos=(photo(1, subject="대상 " + KEY),)), "CONTENT_INVALID")

    def test_every_candidate_and_blog_passes_the_claims_check_with_photos(self):
        for number, row in enumerate(CANDIDATES):
            candidate = make(*row)
            for blog in ("naver_a", "naver_b"):
                with self.subTest(candidate=number, blog=blog):
                    body = body_of(candidate, None, None, blog, photos=PHOTOS)
                    self.assertFalse(claims.find_violations(list(body.generated_texts())))
                    self.assertEqual(sorted(number_ for number_, _s, _e in pm.find_placeholders(body.body_text)), [1, 2, 3, 4])

    def test_the_photo_texts_are_the_only_new_words_in_the_body(self):
        plain, placed = body_of(), body_of(photos=PHOTOS)
        added = set(placed.body_text.split()) - set(plain.body_text.split())
        allowed = set()
        for item in PHOTOS:
            for text, _made in pf.photo_lines(item):
                allowed.update(text.split())
        self.assertLessEqual(added, allowed, "사진 줄 말고 새로 생긴 낱말이 없다")


if __name__ == "__main__":
    unittest.main()
