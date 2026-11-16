"""사진을 본문의 어디에 어떤 줄로 넣을지(`content/photo_flow.py` — 사진 연동 3단계, 설계 4-2·4-6) 시험 — 순수 함수라 파일·네트워크·PySide6·실제 시크릿 없이 돈다.

지키는 것:
  1) 사진이 없으면 블록을 한 글자도 안 바꾼다(같은 객체). 입력은 바꾸지 않는다. 같은 입력은 늘 같은 결과.
  2) 한 사진의 줄: `{{사진 N}}`(틀로 만든 글) · 설명 글 · `<대상> 사진이에요.` · 메모 — 사용자 글은 한 글자도 안 고친다(300자 메모도 그대로). 대상이 없으면 틀 문장이 없다. 이미 문장으로 끝난 대상에는 더 붙이지 않는다.
  3) 자리: 맨 앞·소제목 바로 뒤·n 번째 문단 뒤·n 번째 문장 뒤·자동(첫 문단 뒤) — 모자라면 가장 가까운 자리에 넣고 사진 번호로만 알린다.
  4) 들어갈 곳: 도입·내용 소제목·분위기 소제목·마무리·정확한 소제목 글·별칭 — 못 찾으면 내용 소제목에 넣고 알린다. 후보가 여럿이면 floor((k-1)·S/P) 로 고르게 나눈다.
  5) 알림 글에는 사진 번호뿐이다(사용자 글·경로가 없다).
"""
import dataclasses
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import draft_body as db  # noqa: E402
from chanceblog_desktop.content import photo_flow as pf  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402

MEMO = "가" * 300


def photo(number, *, kind="auto", nth=0, section="", subject="", note="", caption="", order=None):
    return pm.DraftPhoto(number, order if order is not None else number, "기타", "", subject, note, section, pm.Placement(kind, nth), caption, (), ())


def block(kind, heading, *paragraphs, made=None):
    flags = tuple(made) if made is not None else tuple(True for _ in paragraphs)
    return db.BodyBlock(kind, kind if not heading else "k-" + heading, heading, tuple(paragraphs), flags)


def blocks():
    return (block(db.INTRO, "", "도입 첫째 문단.", "도입 둘째 문단."),
            block(db.SECTION, "먼저 알아둘 점", "알아둘 점 하나. 알아둘 점 둘. 알아둘 점 셋.", "알아둘 점 둘째 문단."),
            block(db.SECTION, "매장 분위기", "분위기 첫 문단.", "분위기 둘째 문단.", "분위기 셋째 문단."),
            block(db.SECTION, "메뉴 구성", "메뉴 첫 문단.", "메뉴 둘째 문단."),
            block(db.CAUTIONS, "확인할 점", "주의 문단."),
            block(db.CLOSING, "마무리", "마무리 문단."))


def texts_of(result_blocks):
    return [[(text, made) for text, made in zip(item.paragraphs, item.generated)] for item in result_blocks]


def lines_of(item):
    return list(item.paragraphs)


class ConstantsTest(unittest.TestCase):
    def test_the_kind_names_match_the_body_generator(self):
        self.assertEqual((pf.INTRO, pf.SECTION, pf.EXPERIENCE, pf.CAUTIONS, pf.CLOSING, pf.REFERENCES), (db.INTRO, db.SECTION, db.EXPERIENCE, db.CAUTIONS, db.CLOSING, db.REFERENCES))


class NothingTest(unittest.TestCase):
    def test_no_photos_returns_the_same_blocks_and_no_notes(self):
        source = blocks()
        result, notes = pf.place_photos(source, ())
        self.assertIs(result[0], source[0])
        self.assertEqual((result, notes), (source, ()))

    def test_the_input_is_never_changed_and_the_same_input_gives_the_same_result(self):
        source = blocks()
        snapshot = [dataclasses.astuple(item) for item in source]
        photos = (photo(1, kind="after_paragraph", nth=1, section="내용 소제목", note="메모"), photo(2, kind="between_sentences", nth=2, section="먼저 알아둘 점"))
        first = pf.place_photos(source, photos)
        second = pf.place_photos(source, photos)
        self.assertEqual(first, second)
        self.assertEqual([dataclasses.astuple(item) for item in source], snapshot)


class LinesTest(unittest.TestCase):
    def test_the_lines_of_one_photo_are_placeholder_caption_subject_and_note_in_that_order_with_the_right_flags(self):
        result, _notes = pf.place_photos(blocks(), (photo(3, caption="간판 앞에서", subject="매장 입구 간판", note="주차는 뒤쪽이에요", section="도입"),))
        intro = texts_of(result)[0]
        self.assertEqual(intro[:5], [("도입 첫째 문단.", True), ("{{사진 3}}", True), ("간판 앞에서", False), ("매장 입구 간판 사진이에요.", False), ("주차는 뒤쪽이에요", False)])
        self.assertEqual(intro[5:], [("도입 둘째 문단.", True)])

    def test_a_photo_without_subject_caption_or_note_adds_only_the_placeholder(self):
        result, notes = pf.place_photos(blocks(), (photo(2, section="마무리"),))
        self.assertEqual(texts_of(result)[5], [("마무리 문단.", True), ("{{사진 2}}", True)])
        self.assertEqual(notes, ())

    def test_a_subject_that_is_already_a_sentence_gets_no_frame(self):
        for subject in ("간판이에요.", "여기가 입구예요", "메뉴판입니다", "사진 잘 나왔네요!", "정말 넓네요…", "맛있어요?"):
            with self.subTest(subject=subject):
                self.assertEqual(pf.subject_sentence(subject), subject)
        for subject in ("매장 입구", "한우 불고기 전골", "반찬 5개"):
            self.assertEqual(pf.subject_sentence(subject), subject + " 사진이에요.")

    def test_a_three_hundred_char_memo_goes_in_whole_and_user_text_is_never_changed(self):
        result, _notes = pf.place_photos(blocks(), (photo(1, note=MEMO, caption="설명 글  그대로", subject="대상  글"),))
        found = [text for item in result for text in item.paragraphs]
        self.assertIn(MEMO, found)
        self.assertIn("설명 글  그대로", found, "공백도 그대로")
        self.assertIn("대상  글 사진이에요.", found)

    def test_every_line_made_by_the_app_is_only_the_placeholder_and_user_lines_are_marked_user(self):
        photos = tuple(photo(number, subject=f"대상 {number}", note=f"메모 {number}", caption=f"설명 {number}") for number in range(1, 6))
        result, _notes = pf.place_photos(blocks(), photos)
        made = {text for item in result for text, flag in zip(item.paragraphs, item.generated) if flag and re.fullmatch(r"[{][{]사진 [0-9]+[}][}]", text)}
        self.assertEqual(made, {f"{{{{사진 {number}}}}}" for number in range(1, 6)})
        for item in result:
            for text, flag in zip(item.paragraphs, item.generated):
                if "사진이에요" in text or text.startswith(("메모 ", "설명 ")):
                    self.assertFalse(flag, text)
        self.assertEqual(len(photos) * 4 + sum(len(item.paragraphs) for item in blocks()), sum(len(item.paragraphs) for item in result))


class PlacementTest(unittest.TestCase):
    def place(self, *photos):
        result, notes = pf.place_photos(blocks(), photos)
        return [lines_of(item) for item in result], notes

    def test_auto_goes_after_the_first_paragraph_of_a_content_block(self):
        lines, notes = self.place(photo(1))
        self.assertEqual(lines[1], ["알아둘 점 하나. 알아둘 점 둘. 알아둘 점 셋.", "{{사진 1}}", "알아둘 점 둘째 문단."])
        self.assertEqual(notes, ())

    def test_top_goes_before_everything_in_the_body_whatever_the_section_says(self):
        lines, _notes = self.place(photo(1, kind="top", section="마무리"))
        self.assertEqual(lines[0][:2], ["{{사진 1}}", "도입 첫째 문단."])
        self.assertEqual(lines[5], ["마무리 문단."])

    def test_after_heading_goes_before_the_first_paragraph_of_the_block(self):
        lines, _notes = self.place(photo(1, kind="after_heading", section="매장 분위기"))
        self.assertEqual(lines[2][:2], ["{{사진 1}}", "분위기 첫 문단."])

    def test_after_heading_in_the_intro_has_no_heading_so_it_goes_before_the_first_paragraph(self):
        lines, _notes = self.place(photo(1, kind="after_heading", section="도입"))
        self.assertEqual(lines[0][:2], ["{{사진 1}}", "도입 첫째 문단."])

    def test_after_paragraph_counts_paragraphs_and_the_last_paragraph_is_the_limit(self):
        lines, notes = self.place(photo(1, kind="after_paragraph", nth=2, section="매장 분위기"))
        self.assertEqual(lines[2], ["분위기 첫 문단.", "분위기 둘째 문단.", "{{사진 1}}", "분위기 셋째 문단."])
        self.assertEqual(notes, ())
        lines, notes = self.place(photo(4, kind="after_paragraph", nth=9, section="메뉴 구성"))
        self.assertEqual(lines[3], ["메뉴 첫 문단.", "메뉴 둘째 문단.", "{{사진 4}}"])
        self.assertEqual(notes, ("사진 4번은 문단이 모자라 그 소제목의 마지막 문단 뒤에 넣었어요.",))

    def test_between_sentences_splits_the_first_paragraph_after_the_nth_sentence_and_keeps_the_words(self):
        lines, notes = self.place(photo(1, kind="between_sentences", nth=2, section="먼저 알아둘 점"))
        self.assertEqual(lines[1], ["알아둘 점 하나. 알아둘 점 둘.", "{{사진 1}}", "알아둘 점 셋.", "알아둘 점 둘째 문단."])
        self.assertEqual(notes, ())

    def test_between_sentences_after_the_last_sentence_is_after_the_paragraph_without_a_note_and_beyond_it_with_a_note(self):
        lines, notes = self.place(photo(1, kind="between_sentences", nth=3, section="먼저 알아둘 점"))
        self.assertEqual(lines[1], ["알아둘 점 하나. 알아둘 점 둘. 알아둘 점 셋.", "{{사진 1}}", "알아둘 점 둘째 문단."])
        self.assertEqual(notes, ())
        lines, notes = self.place(photo(2, kind="between_sentences", nth=8, section="먼저 알아둘 점"))
        self.assertEqual(lines[1], ["알아둘 점 하나. 알아둘 점 둘. 알아둘 점 셋.", "{{사진 2}}", "알아둘 점 둘째 문단."])
        self.assertEqual(notes, ("사진 2번은 첫 문단에 문장이 모자라 첫 문단 뒤에 넣었어요.",))

    def test_two_photos_in_the_same_paragraph_cut_in_sentence_order_and_the_same_cut_keeps_the_photo_order(self):
        lines, _notes = self.place(photo(2, kind="between_sentences", nth=1, section="먼저 알아둘 점"), photo(1, kind="between_sentences", nth=2, section="먼저 알아둘 점"), photo(3, kind="between_sentences", nth=1, section="먼저 알아둘 점"))
        self.assertEqual(lines[1], ["알아둘 점 하나.", "{{사진 2}}", "{{사진 3}}", "알아둘 점 둘.", "{{사진 1}}", "알아둘 점 셋.", "알아둘 점 둘째 문단."])

    def test_a_sentence_end_inside_quotes_or_without_a_following_space_is_not_a_cut(self):
        self.assertEqual(pf.sentence_ends("가격은 3.5만원이에요. 좋아요!"), (len("가격은 3.5만원이에요."), len("가격은 3.5만원이에요. 좋아요!")))
        self.assertEqual(pf.sentence_ends("그가 “왔어요.” 라고 했다."), (len("그가 “왔어요.”"), len("그가 “왔어요.” 라고 했다.")))
        self.assertEqual(pf.sentence_ends("글이 길어요… 그래서요?! 네."), (len("글이 길어요…"), len("글이 길어요… 그래서요?!"), len("글이 길어요… 그래서요?! 네.")), "말줄임표·물음표·느낌표도 문장 끝이다")
        self.assertEqual(pf.sentence_ends("끝이 없는 글"), ())
        self.assertEqual(pf.sentence_ends("점 하나.둘"), ())

    def test_the_same_slot_goes_top_first_then_display_order(self):
        lines, _notes = self.place(photo(1, kind="after_heading", section="도입"), photo(2, kind="top"), photo(3, kind="after_heading", section="도입", order=1), photo(4, kind="after_heading", section="도입", order=9))
        placeholders = [text for text in lines[0] if text.startswith("{{")]
        self.assertEqual(placeholders, ["{{사진 2}}", "{{사진 1}}", "{{사진 3}}", "{{사진 4}}"], "맨 앞 사진이 먼저, 나머지는 display_order(같으면 번호) 순서")


class SectionTest(unittest.TestCase):
    def place(self, *photos):
        result, notes = pf.place_photos(blocks(), photos)
        return [lines_of(item) for item in result], notes

    def where(self, lines, number):
        marker = f"{{{{사진 {number}}}}}"
        return [index for index, item in enumerate(lines) if marker in item]

    def test_the_named_sections(self):
        lines, notes = self.place(photo(1, section="도입"), photo(2, section="마무리"), photo(3, section="분위기 소제목"), photo(4, section="내용 소제목"))
        self.assertEqual(self.where(lines, 1), [0])
        self.assertEqual(self.where(lines, 2), [5])
        self.assertEqual(self.where(lines, 3), [2], "소제목에 분위기 가 들어 있는 블록")
        self.assertIn(self.where(lines, 4)[0], (1, 2, 3))
        self.assertEqual(notes, ())

    def test_a_missing_mood_section_moves_to_the_content_sections_with_a_note(self):
        source = tuple(item for item in blocks() if item.heading != "매장 분위기")
        result, notes = pf.place_photos(source, (photo(7, section="분위기 소제목"),))
        self.assertEqual(notes, ("사진 7번은 분위기 소제목을 찾지 못해 내용 소제목에 넣었어요.",))
        self.assertTrue(any("{{사진 7}}" in item.paragraphs for item in result if item.kind == db.SECTION))

    def test_an_exact_heading_text_an_alias_and_an_unknown_text(self):
        lines, notes = self.place(photo(1, section="메뉴 구성"), photo(2, section="  메뉴   구성 "), photo(3, section="주의"), photo(4, section="closing"))
        self.assertEqual(self.where(lines, 1), [3])
        self.assertEqual(self.where(lines, 2), [3], "공백을 접어 견준다")
        self.assertEqual(self.where(lines, 3), [4])
        self.assertEqual(self.where(lines, 4), [5])
        self.assertEqual(notes, ())
        lines, notes = self.place(photo(5, section="없는 소제목"))
        self.assertEqual(notes, ("사진 5번은 고른 들어갈 곳을 찾지 못해 내용 소제목에 넣었어요.",))
        self.assertTrue(self.where(lines, 5)[0] in (1, 2, 3))

    def test_the_even_spread_is_floor_k_minus_one_times_s_over_p(self):
        for count in range(1, 9):
            for homes in range(1, 6):
                with self.subTest(photos=count, sections=homes):
                    source = (block(db.INTRO, "", "도입."),) + tuple(block(db.SECTION, f"소제목 {index}", f"본문 {index}.") for index in range(homes)) + (block(db.CLOSING, "마무리", "끝."),)
                    result, _notes = pf.place_photos(source, tuple(photo(number) for number in range(1, count + 1)))
                    for number in range(1, count + 1):
                        expected = 1 + (number - 1) * homes // count
                        found = [index for index, item in enumerate(result) if f"{{{{사진 {number}}}}}" in item.paragraphs]
                        self.assertEqual(found, [expected], (number, count, homes))

    def test_photos_that_name_the_same_section_spread_only_inside_that_group_and_other_groups_do_not_move_them(self):
        lines, _notes = self.place(photo(1), photo(2), photo(3, section="마무리"), photo(4, section="도입"))
        self.assertEqual(self.where(lines, 3), [5])
        self.assertEqual(self.where(lines, 4), [0])
        self.assertNotEqual(self.where(lines, 1), self.where(lines, 2), "내용 소제목 셋에 두 장 — 서로 다른 소제목")

    def test_an_alias_for_a_block_the_body_does_not_have_falls_back_to_the_content_sections(self):
        source = tuple(item for item in blocks() if item.kind != db.CAUTIONS)
        result, notes = pf.place_photos(source, (photo(1, section="주의"),))
        self.assertEqual(notes, ("사진 1번은 고른 들어갈 곳을 찾지 못해 내용 소제목에 넣었어요.",))
        self.assertTrue(any("{{사진 1}}" in item.paragraphs for item in result if item.kind == db.SECTION))


class NotesTest(unittest.TestCase):
    def test_notes_have_only_photo_numbers_never_the_users_words_and_repeats_are_dropped(self):
        secret_words = "비밀-섹션-글"
        photos = tuple(photo(number, kind="after_paragraph", nth=9, section=secret_words, subject=f"대상-{number}", note=f"메모-{number}", caption=f"설명-{number}") for number in (1, 2))
        _result, notes = pf.place_photos(blocks(), photos)
        joined = " ".join(notes)
        for word in (secret_words, "대상-", "메모-", "설명-"):
            self.assertNotIn(word, joined)
        self.assertEqual(len(notes), len(set(notes)))
        self.assertEqual([re.findall("[0-9]+", note)[0] for note in notes], ["1", "1", "2", "2"], "찾지 못한 들어갈 곳 + 모자란 문단, 사진마다")
        self.assertTrue(all("번" in note for note in notes))

    def test_a_body_with_no_paragraphs_in_the_chosen_block_still_takes_the_photo(self):
        source = (block(db.INTRO, ""), block(db.SECTION, "빈 소제목"), block(db.CLOSING, "마무리", "끝."))
        result, _notes = pf.place_photos(source, (photo(1), photo(2, kind="after_paragraph", nth=3), photo(3, kind="between_sentences", nth=1)))
        self.assertEqual([text for text in result[1].paragraphs], ["{{사진 1}}", "{{사진 2}}", "{{사진 3}}"])


if __name__ == "__main__":
    unittest.main()
