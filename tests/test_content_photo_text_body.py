"""확정한 글자(사진 속 글자 읽기에서 사용자가 줄마다 확인한 글)를 초안 본문에 잇는 길 시험 — 글자 읽기 b 단계 B3(설계 2-8·2-9·4절, 6-2 의 T-D, 결정 D-520에서 D-525).
`content/photo_flow.py` 의 `photo_lines` 가 `DraftPhoto.confirmed_texts` 를 본문에 잇는다. 순수 함수라 파일·네트워크·PySide6·실제 시크릿 없이 돈다.

지키는 것:
  1) 확정한 글자가 없으면 사진 줄·본문이 지금과 한 글자도 다르지 않다(사진 0장·1장·여러 장 × 종류 9종 — 옛 함수를 시험 안에 그대로 두고 견준다).
  2) 확정한 글자가 있으면 그 사진의 줄 맨 끝에 둘이 더해진다: 틀 문장 `사진에 적힌 글이에요.`(틀로 만든 글 — '지어내지 않기' 검사와 마지막 관문 `_final_guard` 를 지난다)과
     확정한 줄들을 줄바꿈 그대로 이은 문단 하나(사용자 글 — 한 글자도 고치지 않고 그 검사에서 뺀다). 다른 곳은 하나도 바뀌지 않는다.
  3) 확정하지 않은 줄·확정하지 않은 사진의 줄은 본문에 가지 않는다. 앱은 가격·메뉴·상호를 뽑거나 해석하지 않는다 — 새 칸이 없다.
  4) 여러 줄 문단이 글 모양 점검과 복사 변환을 지나도 줄이 그대로다(마크다운 길은 줄을 합치지만 초안 본문은 그 길을 지나지 않는다).
  5) 입구 검사(`check_text`)가 막는 글(템플릿 표기·태그·비밀 모양·개인 번호 모양·빈칸 글자)은 확정 줄이 될 수 없고, 보이지 않는 글자와 줄바꿈은 입구가 지운다.
  6) 한도: 한 사진 60줄·줄당 200자까지 그대로 들어가고, 아주 많으면 저장이 한도 문장으로 거절될 뿐 글이 몰래 잘리지 않는다.
"""
import dataclasses
import itertools
import random
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "chanceblog_desktop"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_content_draft_body import CANDIDATES, PROFILE_MAKERS, body_of, expect_error, make, profile  # noqa: E402
from test_content_photo_flow import block  # noqa: E402

from chanceblog_desktop.check import claims, garbage  # noqa: E402
from chanceblog_desktop.content import body_lang as bl  # noqa: E402
from chanceblog_desktop.content import draft_body as db  # noqa: E402
from chanceblog_desktop.content import photo_flow as pf  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.content import saved_draft as sd  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.render import naver  # noqa: E402
from chanceblog_desktop.security import mask as mask_module  # noqa: E402
from chanceblog_desktop.security import shape  # noqa: E402
from chanceblog_desktop.ui.core import text as ui_text  # noqa: E402

NL = chr(10)
FRAME = "사진에 적힌 글이에요."
FRAME_HAPSYO = "사진에 적힌 글입니다."
FAKE_KEY = "CANARY_" + "AI" + "za" + "A" * 35                                   # 가짜 키(조립한 글 — 저장소에 키 문자열을 두지 않는다)
METHOD = "local:rapidocr-ko-v5"
PHOTO_TYPES = pm.DEFAULT_PHOTO_TYPES
SECTIONS = ("", "내용 소제목", "마무리")
MENU = ("한우 불고기 전골 28,000원", "된장찌개 9,000원", "공기밥 1,000원", "※ 원산지: 소고기(국내산)", "영업시간 10:00–22:00", "이용해 주셔서 감사합니다.")
RECEIPT = tuple(f"상품 {number:02d} {number * 1000:,}원" for number in range(1, 52))          # 영수증 한 장 51줄(설계서가 읽은 관찰 최대)
ODD = ("아메리카노  4,500원 ", "“따뜻한 차” 6,000원", "A+B 세트 (2인) 15,000원 …", "★ 오늘의 메뉴 ★", "가격은 매장 사정에 따라 바뀔 수 있어요!")      # 앞뒤 공백·겹 공백·따옴표·기호 — 손으로 만든 값이라 입구를 거치지 않는다
BODY_KEYS = ("blog", "keyword", "topic", "post_type", "style", "domain", "audience", "titles", "selected_title", "blocks", "core_keywords", "sub_keywords", "tags", "category", "summary", "checks", "title_text",
             "body_text", "plain_text", "tags_text", "chars", "chars_with_spaces", "used", "sponsor_slot", "sensitive", "dropped", "replaced")          # 이 묶음 전의 `DraftBody.to_dict()` 칸 — 새 칸이 없다
DRAFT_KEYS = ("number", "display_order", "photo_type", "setting", "user_subject", "user_note", "preferred_section", "placement", "caption", "confirmed_objects", "confirmed_texts")          # 이 묶음 전의 `DraftPhoto` 칸


def dphoto(number, *, texts=(), objects=(), kind="auto", nth=0, section="", subject="", note="", caption="", order=None, photo_type="기타"):
    return pm.DraftPhoto(number, order if order is not None else number, photo_type, "", subject, note, section, pm.Placement(kind, nth), caption, tuple(objects), tuple(texts))


def old_photo_lines(photo, style=None):
    """이 묶음 전의 `photo_lines` — 확정한 글자를 쓰지 않는 옛 함수 그대로('지금과 같다' 를 견주는 기준). `style` 은 본문 생성기가 문체를 넘기므로 받기만 하고 쓰지 않는다(옛 줄에는 문체를 타는 문장이 없다)."""
    lines = [(pm.placeholder(photo.number), True)]
    if photo.caption:
        lines.append((photo.caption, False))
    if photo.user_subject:
        lines.append((pf.subject_sentence(photo.user_subject), False))
    if photo.user_note:
        lines.append((photo.user_note, False))
    return tuple(lines)


def built_the_old_way(photos, **kwargs):
    """옛 `photo_lines` 로 만든 본문 — 확정한 글자를 모르는 본문 생성기."""
    with mock.patch.object(pf, "photo_lines", old_photo_lines):
        return body_of(photos=photos, **kwargs)


def path_of(number):
    return f"C:/Users/UNIQ-USERDIR-b3/Pictures/UNIQ-FILE-b3-{number:02d}.jpg"


def manifest_of(*specs):
    """사진 목록 — 사진마다 `lines`(읽은 줄들)·`confirm`(확인할 줄 번호들 또는 `all`)·`photo`(사진 확정 여부)·`type`·`subject`. → (목록, 사진마다 거른 줄 수)."""
    manifest, dropped_each = pm.empty_manifest(), []
    for number, spec in enumerate(specs, 1):
        manifest, photo_id = pm.add_photo(manifest, path_of(number), photo_type=spec.get("type", "메뉴판"), user_subject=spec.get("subject", ""))
        manifest, dropped = pm.set_analysis(manifest, photo_id, method=METHOD, texts=spec.get("lines", ()))
        dropped_each.append(dropped)
        wanted = range(len(manifest.photo(photo_id).visible_text)) if spec.get("confirm", "all") == "all" else spec["confirm"]
        for index in wanted:
            manifest = pm.confirm_item(manifest, photo_id, pm.TEXTS, index)
        manifest = pm.set_confirmed(manifest, photo_id, spec.get("photo", True))
    return manifest, dropped_each


def lines_of_photo(photo):
    return [text for text, _made in pf.photo_lines(photo)]


class SameWithoutTextTest(unittest.TestCase):
    """확정한 글자가 없으면 지금과 한 글자도 다르지 않다."""

    def test_photo_lines_without_confirmed_text_are_exactly_the_old_lines(self):
        for photo_type in PHOTO_TYPES:
            for caption, subject, note in itertools.product(("", "간판 앞에서"), ("", "매장 입구", "여기가 입구예요"), ("", "주차는 뒤쪽이에요")):
                with self.subTest(photo_type=photo_type, caption=caption, subject=subject, note=note):
                    photo = dphoto(3, photo_type=photo_type, caption=caption, subject=subject, note=note)
                    self.assertEqual(pf.photo_lines(photo), old_photo_lines(photo))

    def test_the_old_function_kept_in_this_file_is_the_documented_old_behavior(self):
        photo = dphoto(3, caption="간판 앞에서", subject="매장 입구 간판", note="주차는 뒤쪽이에요")
        self.assertEqual(old_photo_lines(photo), (("{{사진 3}}", True), ("간판 앞에서", False), ("매장 입구 간판 사진이에요.", False), ("주차는 뒤쪽이에요", False)))

    def test_the_body_without_confirmed_text_is_exactly_the_old_body_for_zero_one_and_several_photos_and_nine_types(self):
        for photo_type in PHOTO_TYPES:
            for count in (0, 1, 3):
                photos = tuple(dphoto(number, photo_type=photo_type, subject=f"대상 {number}", note=f"메모 {number}", caption=f"설명 {number}", section=SECTIONS[number % 3]) for number in range(1, count + 1))
                with self.subTest(photo_type=photo_type, count=count):
                    self.assertEqual(body_of(photos=photos), built_the_old_way(photos))

    def test_every_candidate_and_blog_gives_the_old_body_for_photos_without_text(self):
        photos = (dphoto(1, kind="top", subject="매장 입구 간판", note="주차는 뒤쪽이에요"), dphoto(2, section="내용 소제목", caption="메뉴판 앞에서"), dphoto(3, section="마무리"))
        for number, row in enumerate(CANDIDATES):
            for blog in ("naver_a", "naver_b"):
                candidate = make(*row)
                with self.subTest(candidate=number, blog=blog):
                    self.assertEqual(body_of(candidate, None, None, blog, photos=photos), built_the_old_way(photos, candidate=candidate, blog=blog))

    def test_confirmed_objects_without_text_change_nothing(self):
        """관찰한 대상(`confirmed_objects`)은 본문에 가지 않는다 — 글자 읽기는 대상 칸을 쓰지 않는다(이슈 212)."""
        photo = dphoto(1, objects=("탁자 위의 컵", "메뉴판"))
        self.assertEqual(pf.photo_lines(photo), old_photo_lines(photo))
        self.assertEqual(body_of(photos=(photo,)), built_the_old_way((photo,)))


class FrameTest(unittest.TestCase):
    def test_the_frame_is_the_agreed_sentence_in_the_house_style(self):
        self.assertEqual(pf.TEXT_FRAME, FRAME)
        self.assertTrue(pf.TEXT_FRAME.endswith("요."), "기존 사진 문장(`사진이에요.`)과 같은 해요체")

    def test_the_frame_passes_the_made_sentence_check_with_no_claims_at_all(self):
        self.assertEqual(claims.find_violations([pf.TEXT_FRAME]), ())
        self.assertEqual(claims.find_claims([pf.TEXT_FRAME]), ())

    def test_the_frame_says_nothing_about_food_prices_or_shops(self):
        for word in ("메뉴", "가격", "음식", "맛", "추천", "상호", "가게", "원산지"):
            self.assertNotIn(word, pf.TEXT_FRAME)
        self.assertIsNone(re.search("[0-9]", pf.TEXT_FRAME))

    def test_the_frame_is_one_character_short_of_the_repeated_sentence_limit_so_it_may_repeat_for_every_photo(self):
        key = garbage.sentence_key(pf.TEXT_FRAME)
        self.assertEqual(len(key), 9)
        self.assertLess(len(key), garbage.MIN_SENTENCE_KEY, "한 글자만 길어져도 사진마다 '같은 문장' 경고가 난다")


class LinesTest(unittest.TestCase):
    def test_confirmed_text_adds_the_frame_and_one_paragraph_of_the_lines_at_the_very_end(self):
        photo = dphoto(3, caption="간판 앞에서", subject="매장 입구 간판", note="주차는 뒤쪽이에요", texts=MENU)
        self.assertEqual(pf.photo_lines(photo), old_photo_lines(photo) + ((FRAME, True), (NL.join(MENU), False)))

    def test_without_caption_subject_or_note_the_text_follows_the_placeholder_directly(self):
        photo = dphoto(2, texts=MENU[:2])
        self.assertEqual(pf.photo_lines(photo), (("{{사진 2}}", True), (FRAME, True), (MENU[0] + NL + MENU[1], False)))

    def test_the_lines_go_in_whole_and_untouched_even_with_odd_spacing_quotes_and_marks(self):
        paragraph = pf.photo_lines(dphoto(1, texts=ODD))[-1][0]
        self.assertEqual(paragraph, NL.join(ODD))
        self.assertEqual(paragraph.split(NL), list(ODD), "앞뒤 공백·겹 공백·따옴표·기호까지 한 글자도 안 고친다")

    def test_one_line_is_a_paragraph_without_a_line_break_and_n_lines_have_n_minus_one(self):
        for count in (1, 2, 6):
            paragraph = pf.photo_lines(dphoto(1, texts=MENU[:count]))[-1][0]
            self.assertEqual(paragraph.count(NL), count - 1)
            self.assertEqual(paragraph.split(NL), list(MENU[:count]))

    def test_the_nine_photo_types_make_the_same_lines_and_the_type_name_never_shows(self):
        seen = set()
        for photo_type in PHOTO_TYPES:
            lines = pf.photo_lines(dphoto(1, photo_type=photo_type, texts=MENU))
            seen.add(lines)
            self.assertNotIn(photo_type, " ".join(text for text, _made in lines), "종류 이름만으로는 문장을 만들지 않는다")
        self.assertEqual(len(seen), 1, "종류가 달라도 줄은 같다")

    def test_only_confirmed_texts_are_used_and_confirmed_objects_never_reach_the_lines(self):
        lines = lines_of_photo(dphoto(1, objects=("탁자 위의 컵",), texts=MENU[:1]))
        self.assertEqual(lines, ["{{사진 1}}", FRAME, MENU[0]])

    def test_the_frame_is_marked_made_and_the_lines_are_marked_user(self):
        self.assertEqual([made for _text, made in pf.photo_lines(dphoto(1, texts=MENU))], [True, True, False])

    def test_prices_and_names_are_not_picked_out_or_changed(self):
        """앱은 가격·메뉴 이름·상호를 해석하지 않는다 — 쉼표·단위·기호가 든 줄이 글자 그대로다."""
        paragraph = pf.photo_lines(dphoto(1, texts=MENU))[-1][0]
        for line in MENU:
            self.assertIn(line, paragraph.split(NL))
        self.assertIn("28,000원", paragraph)
        self.assertEqual(len(paragraph), len(NL.join(MENU)))


class BodyTest(unittest.TestCase):
    def photos(self, count, photo_type, with_text):
        return tuple(dphoto(number, photo_type=photo_type, texts=MENU[:2 + number] if with_text else (), subject=f"대상 {number}", section=SECTIONS[number % 3]) for number in range(1, count + 1))

    def test_each_photos_lines_sit_together_in_the_body_text_with_the_frame_and_the_lines_last(self):
        photos = (dphoto(1, kind="top", texts=MENU[:2], note="메모 하나"), dphoto(2, section="마무리", texts=MENU[2:5], subject="대표 메뉴"))
        body = body_of(photos=photos)
        for photo in photos:
            expected = (NL + NL).join(lines_of_photo(photo))
            self.assertEqual(body.body_text.count(expected), 1, expected)
        self.assertTrue(body.body_text.startswith("{{사진 1}}" + NL + NL + "메모 하나" + NL + NL + FRAME + NL + NL + MENU[0] + NL + MENU[1]))

    def test_matrix_nine_types_by_zero_one_and_several_photos_with_and_without_text(self):
        for photo_type in PHOTO_TYPES:
            for count in (0, 1, 3):
                for with_text in (False, True):
                    photos = self.photos(count, photo_type, with_text)
                    with self.subTest(photo_type=photo_type, count=count, text=with_text):
                        body = body_of(photos=photos)
                        self.assertEqual(sorted(number for number, _start, _end in pm.find_placeholders(body.body_text)), list(range(1, count + 1)))
                        self.assertEqual(pm.stray_braces(body.body_text), 0)
                        self.assertEqual(claims.find_violations(list(body.generated_texts())), ())
                        self.assertEqual(body.generated_texts().count(FRAME), count if with_text else 0)
                        for photo in photos:
                            if photo.confirmed_texts:
                                self.assertIn(NL.join(photo.confirmed_texts), body.user_paragraphs())
                                self.assertNotIn(NL.join(photo.confirmed_texts), body.generated_texts())

    def test_every_candidate_and_blog_builds_with_confirmed_text_and_passes_the_made_sentence_check(self):
        photos = (dphoto(1, kind="top", subject="매장 입구 간판", texts=MENU[:3]), dphoto(2, section="내용 소제목", caption="메뉴판 앞에서", texts=MENU), dphoto(3, section="마무리", texts=RECEIPT[:10]))
        for number, row in enumerate(CANDIDATES):
            for blog in ("naver_a", "naver_b"):
                with self.subTest(candidate=number, blog=blog):
                    body = body_of(make(*row), None, None, blog, photos=photos)
                    self.assertEqual(claims.find_violations(list(body.generated_texts())), ())
                    self.assertEqual(body.generated_texts().count(FRAME), 3)
                    self.assertEqual(sorted(found for found, _start, _end in pm.find_placeholders(body.body_text)), [1, 2, 3])

    def test_with_text_only_the_added_paragraphs_differ_from_the_old_body(self):
        photos = (dphoto(1, kind="top", subject="매장 입구 간판", texts=MENU[:3]), dphoto(2, section="내용 소제목", caption="메뉴판 앞에서", texts=MENU), dphoto(3, section="마무리", note="마무리 한마디"),
                  dphoto(4, kind="after_paragraph", nth=50, section="내용 소제목", texts=RECEIPT))
        new, old = body_of(photos=photos), built_the_old_way(photos)
        added = set()
        for photo in photos:
            if photo.confirmed_texts:
                added |= {(FRAME, True), (NL.join(photo.confirmed_texts), False)}
        self.assertEqual(len(new.blocks), len(old.blocks))
        for after, before in zip(new.blocks, old.blocks):
            self.assertEqual((after.kind, after.key, after.heading), (before.kind, before.key, before.heading))
            kept = [(text, made) for text, made in zip(after.paragraphs, after.generated) if (text, made) not in added]
            self.assertEqual(kept, list(zip(before.paragraphs, before.generated)), "틀로 만든 글·다른 사진 줄은 그대로이고 확정 글자 문단만 더해졌다")
        for name in ("titles", "selected_title", "core_keywords", "sub_keywords", "tags", "category", "summary", "style", "domain", "audience", "blog", "post_type", "sensitive", "used", "dropped", "sponsor_slot",
                     "replaced", "checks"):
            self.assertEqual(getattr(new, name), getattr(old, name), name)
        self.assertGreater(new.chars, old.chars)
        self.assertEqual((new.chars, new.chars_with_spaces), db.count_chars(new.body_text), "글자 수는 끼운 뒤의 본문으로 센다")
        self.assertEqual(new.plain_text, new.selected_title + NL + NL + new.body_text)
        self.assertEqual(set(new.to_dict()), set(old.to_dict()))

    def test_the_body_has_no_new_field_so_nothing_is_structured(self):
        body = body_of(photos=(dphoto(1, texts=MENU),))
        self.assertEqual(tuple(body.to_dict()), BODY_KEYS)
        self.assertEqual(pm.DRAFT_KEYS, DRAFT_KEYS)
        self.assertEqual(tuple(item.name for item in dataclasses.fields(pm.DraftPhoto)), DRAFT_KEYS)
        for line in MENU:
            self.assertEqual(body.body_text.count(line), 1, "줄은 본문에 한 번, 글자 그대로")

    def test_the_frame_is_checked_by_the_final_guard_so_a_bad_frame_stops_the_draft(self):
        photos = (dphoto(1, texts=MENU[:2]),)
        bad = "직접 써 보니 사진에 적힌 글이에요."
        self.assertTrue(claims.find_violations([bad]))
        with mock.patch.object(pf, "TEXT_FRAME", bad):
            expect_error(self, lambda: body_of(photos=photos), "CONTENT_INVALID")
        self.assertIn(FRAME, body_of(photos=photos).generated_texts(), "틀 문장은 틀로 만든 글이라 마지막 관문이 본다")

    def test_user_lines_are_left_out_of_the_made_sentence_check_even_when_they_read_like_a_claim(self):
        claimy = ("사용해 보니 정말 좋았어요", "직접 사용해 보니 효과가 좋았어요", "어제 다녀왔는데 맛있었어요")
        for line in claimy:
            self.assertTrue(claims.find_violations([line]), line)
        body = body_of(photos=(dphoto(1, texts=claimy),))
        self.assertIn(NL.join(claimy), body.body_text)
        self.assertIn(NL.join(claimy), body.user_paragraphs())
        self.assertFalse(any(line in text for line in claimy for text in body.generated_texts()))

    def test_the_final_guard_still_sees_the_whole_body_and_stops_on_a_key_shape_in_a_confirmed_line(self):
        for lines in ((FAKE_KEY,), ("메뉴 하나", "키는 " + FAKE_KEY + " 이다")):
            with self.subTest(lines=len(lines)):
                error = expect_error(self, lambda: body_of(photos=(dphoto(1, texts=lines),)), "CONTENT_INVALID")      # 손으로 만든 값 — 입구와 `draft_inputs` 를 지나지 않았어도 마지막 관문이 막는다
                for shown in (str(error), error.detail, repr(error.slots), error.log_line()):
                    self.assertNotIn(FAKE_KEY, shown, "오류에 값이 없다")

    def test_the_checks_and_notes_do_not_grow_because_of_confirmed_text(self):
        photos = (dphoto(1, texts=MENU), dphoto(2, kind="after_paragraph", nth=50, section="내용 소제목", texts=MENU[:2]))
        self.assertEqual(body_of(photos=photos).checks, built_the_old_way(photos).checks)

    def test_the_same_input_gives_the_same_draft_twice_and_the_photo_order_does_not_matter(self):
        photos = (dphoto(1, texts=MENU[:2]), dphoto(2, section="마무리", texts=MENU[2:4]), dphoto(3, kind="top", texts=MENU[4:]))
        self.assertEqual(body_of(photos=photos), body_of(photos=photos))
        self.assertEqual(body_of(photos=photos).to_dict(), body_of(photos=tuple(reversed(photos))).to_dict())


class ManifestFlowTest(unittest.TestCase):
    """사진 목록 → `draft_inputs` → 본문 — 확정한 것만 가고 입구가 막는 글은 확정 줄이 될 수 없다."""

    ADVERSARIAL = {
        "double braces": "{{사진 9}}", "template name": "{{이름}} 님", "liquid": "{% if x %}", "hash tag": "{# 주석 #}", "close only": "닫기 }}",
        "script tag": "<script>alert(1)</script>", "bold tag": "<b>굵게</b>", "image tag": "<img src=x onerror=alert(1)>", "script url": "javascript:alert(1)", "event attribute": "onclick=alert(1)", "comment": "<!-- 숨김 -->",
        "key": FAKE_KEY, "key in a sentence": "키는 " + FAKE_KEY + " 입니다",
        "resident number": "900101-1234567", "card number": "4111 1111 1111 1111",
        "blank filler": chr(0x3164), "filler inside": "가" + chr(0x3164) + "나", "braille blank": chr(0x2800), "variation selector": "가" + chr(0xFE0F),
        "empty": "", "too long": "가" * 201,
    }
    CLEANED = {          # 입구가 지워서 받는 글 → 지운 뒤의 글
        "zero width space": ("가" + chr(0x200B) + "나", "가나"), "bidi mark": ("ab" + chr(0x202E) + "cd", "abcd"), "joiner": ("가" + chr(0x200D) + "나", "가나"), "bom": (chr(0xFEFF) + "가나", "가나"),
        "line break": ("가" + NL + "나", "가 나"), "tab": ("가" + chr(9) + "나", "가 나"), "line separator": ("가" + chr(0x2028) + "나", "가 나"),
    }

    def test_only_the_confirmed_lines_of_a_confirmed_photo_reach_the_body_in_order(self):
        manifest, _dropped = manifest_of(dict(lines=MENU, confirm=(0, 2, 3)), dict(lines=("둘째 사진 글", "둘째 사진 글 둘"), photo=False), dict(lines=("셋째 사진 글",), confirm=()))
        inputs = pm.draft_inputs(manifest)
        self.assertEqual([photo.number for photo in inputs], [1, 3], "확정하지 않은 사진은 아예 가지 않는다")
        self.assertEqual(inputs[0].confirmed_texts, (MENU[0], MENU[2], MENU[3]))
        self.assertEqual(inputs[1].confirmed_texts, ())
        body = body_of(photos=inputs)
        self.assertIn(NL.join((MENU[0], MENU[2], MENU[3])), body.body_text)
        for left_out in (MENU[1], MENU[4], MENU[5], "둘째 사진 글", "셋째 사진 글"):
            self.assertNotIn(left_out, body.body_text)
        self.assertEqual(body.body_text.count(FRAME), 1, "확정한 줄이 있는 사진은 한 장뿐")
        self.assertEqual(sorted(number for number, _start, _end in pm.find_placeholders(body.body_text)), [1, 3])

    def test_a_photo_with_no_confirmed_line_gets_no_frame_and_no_empty_paragraph(self):
        manifest, _dropped = manifest_of(dict(lines=MENU, confirm=()))
        body = body_of(photos=pm.draft_inputs(manifest))
        self.assertNotIn(FRAME, body.body_text)
        self.assertEqual(body, built_the_old_way(pm.draft_inputs(manifest)))
        self.assertNotIn(NL + NL + NL, body.body_text, "빈 문단이 없다")

    def test_editing_a_confirmed_line_takes_it_out_again_until_it_is_confirmed_once_more(self):
        manifest, _dropped = manifest_of(dict(lines=MENU[:3]))
        manifest = pm.edit_item(manifest, "p001", pm.TEXTS, 1, "된장찌개 9,500원")
        self.assertEqual(pm.draft_inputs(manifest), (), "고치면 그 줄은 확인 전이 되고 사진 확정도 풀린다")
        manifest = pm.set_confirmed(manifest, "p001", True)
        self.assertEqual(pm.draft_inputs(manifest)[0].confirmed_texts, (MENU[0], MENU[2]), "고친 줄은 다시 확인하기 전까지 빠진다")
        manifest = pm.set_confirmed(pm.confirm_item(manifest, "p001", pm.TEXTS, 1), "p001", True)
        self.assertEqual(pm.draft_inputs(manifest)[0].confirmed_texts, (MENU[0], "된장찌개 9,500원", MENU[2]))
        self.assertIn(NL.join((MENU[0], "된장찌개 9,500원", MENU[2])), body_of(photos=pm.draft_inputs(manifest)).body_text)

    def test_the_same_line_twice_goes_in_once(self):
        manifest, _dropped = manifest_of(dict(lines=("합계 12,000원", "합계 12,000원", "감사합니다")))
        body = body_of(photos=pm.draft_inputs(manifest))
        self.assertEqual(body.body_text.count("합계 12,000원"), 1)
        self.assertIn("합계 12,000원" + NL + "감사합니다", body.body_text)

    def test_the_same_line_far_apart_goes_in_once_too_so_the_body_has_fewer_lines_than_the_user_confirmed(self):
        """알려 둔 한계(독립 검증 QP-3, 결정 D-523) — `draft_inputs` 는 같은 글의 항목을 하나만 남긴다(B1 때부터의 규칙, 운영자 답을 기다리는 질문). 수량이 둘인 영수증처럼 같은 줄이 멀리 떨어져 있어도 뒤쪽 줄이 빠진다."""
        lines = ("아메리카노 4,500원", "합계 9,000원", "아메리카노 4,500원", "감사합니다", "합계 9,000원")
        manifest, dropped = manifest_of(dict(lines=lines))
        self.assertEqual((dropped, [item.confirmed for item in manifest.photo("p001").visible_text]), ([0], [True] * 5), "사용자가 확인한 줄은 다섯")
        inputs = pm.draft_inputs(manifest)
        self.assertEqual(inputs[0].confirmed_texts, ("아메리카노 4,500원", "합계 9,000원", "감사합니다"), "본문에 들어가는 줄은 셋 — 같은 줄은 앞쪽 하나만 남는다")
        body = body_of(photos=inputs)
        self.assertIn(NL.join(("아메리카노 4,500원", "합계 9,000원", "감사합니다")), body.body_text)
        self.assertEqual((body.body_text.count("아메리카노 4,500원"), body.body_text.count("합계 9,000원")), (1, 1))

    def test_the_repr_of_a_draft_photo_shows_no_text_and_only_the_two_numbers(self):
        """확정한 글이 본문으로 흐르므로 `DraftPhoto` 가 오류·기록·화면 문장에 글을 새기지 않는다는 약속(독스트링)을 지킨다(독립 검증 QP-5)."""
        photo = dphoto(7, texts=MENU, objects=("탁자 위의 컵",), subject="UNIQ-SUBJECT-b3", note="UNIQ-NOTE-b3", caption="UNIQ-CAP-b3", section="UNIQ-SECTION-b3", photo_type="UNIQ-TYPE-b3")
        shown = repr(photo) + str(photo) + repr((photo,)) + repr({"photo": photo})
        for text in (*MENU, "탁자 위의 컵", "UNIQ-SUBJECT-b3", "UNIQ-NOTE-b3", "UNIQ-CAP-b3", "UNIQ-SECTION-b3", "UNIQ-TYPE-b3"):
            self.assertNotIn(text, shown)
        self.assertEqual([item.name for item in dataclasses.fields(pm.DraftPhoto) if item.repr], ["number", "display_order"])
        self.assertIn("number=7", repr(photo))

    def test_none_of_the_hostile_lines_can_become_a_line_of_a_photo(self):
        for name, line in self.ADVERSARIAL.items():
            with self.subTest(name):
                self.assertIsNotNone(pm.check_text("observation", line)[1], "입구 검사 `check_text` 가 거절한다 — 읽을 때·고칠 때·합칠 때가 모두 이 검사를 쓴다")
                manifest, dropped = manifest_of(dict(lines=("좋은 줄", line, "또 좋은 줄")))
                self.assertEqual(dropped, [1], "입구가 거르고 개수만 센다")
                self.assertEqual([item.text for item in manifest.photo("p001").visible_text], ["좋은 줄", "또 좋은 줄"])
                body = body_of(photos=pm.draft_inputs(manifest))
                self.assertIn("좋은 줄" + NL + "또 좋은 줄", body.body_text)
                self.assertEqual(pm.stray_braces(body.body_text), 0)
                self.assertEqual(sorted(number for number, _start, _end in pm.find_placeholders(body.body_text)), [1])

    def test_editing_a_line_into_a_hostile_one_is_refused_and_so_is_building_the_value(self):
        manifest, _dropped = manifest_of(dict(lines=("좋은 줄", "다음 줄")))
        for name, line in self.ADVERSARIAL.items():
            with self.subTest(name):
                expect_error(self, lambda: pm.edit_item(manifest, "p001", pm.TEXTS, 0, line), "CONTENT_INVALID")
                expect_error(self, lambda: pm.Observation(line), "CONTENT_INVALID")

    def test_merging_two_fine_lines_into_a_card_number_or_a_too_long_line_is_refused(self):
        manifest, _dropped = manifest_of(dict(lines=("4111 1111", "1111 1111", "가" * 120, "나" * 120)))
        expect_error(self, lambda: pm.merge_items(manifest, "p001", pm.TEXTS, 0), "CONTENT_INVALID")
        expect_error(self, lambda: pm.merge_items(manifest, "p001", pm.TEXTS, 2), "CONTENT_INVALID")

    def test_invisible_and_line_break_characters_are_cleaned_at_the_entrance_so_a_line_never_holds_a_line_break(self):
        for name, (raw, cleaned) in self.CLEANED.items():
            with self.subTest(name):
                self.assertEqual(pm.check_text("observation", raw), (cleaned, None), "입구 검사가 지워서 받는다")
                manifest, dropped = manifest_of(dict(lines=(raw,)))
                self.assertEqual((dropped, [item.text for item in manifest.photo("p001").visible_text]), ([0], [cleaned]))
                body = body_of(photos=pm.draft_inputs(manifest))
                self.assertIn(FRAME + NL + NL + cleaned, body.body_text)
                self.assertNotIn(raw, body.body_text)
                self.assertEqual([item for item in garbage.scan("", body.body_text).findings if item.kind in ("invisible", "control")], [])

    def test_sixty_lines_of_two_hundred_characters_go_in_and_the_sixty_first_is_dropped_and_counted(self):
        lines = tuple(f"{number:02d}" + "가" * 198 for number in range(61))
        manifest, dropped = manifest_of(dict(lines=lines))
        self.assertEqual(dropped, [1])
        self.assertEqual(len(manifest.photo("p001").visible_text), pm.MAX_TEXT_ITEMS)
        body = body_of(photos=pm.draft_inputs(manifest))
        paragraph = NL.join(lines[:60])
        self.assertEqual((len(paragraph), paragraph.count(NL)), (60 * 200 + 59, 59))
        self.assertIn(paragraph, body.body_text)
        self.assertNotIn(lines[60], body.body_text)

    def test_the_text_cap_is_sixty_for_texts_and_twenty_for_objects(self):
        self.assertEqual((pm.MAX_TEXT_ITEMS, pm.MAX_OBJECT_ITEMS, pm.MAX_OBSERVATION_CHARS), (60, 20, 200))


class DownstreamTest(unittest.TestCase):
    """여러 줄 문단이 글 모양 점검·복사 변환·마크다운 길에서 어떻게 보이는가(결정 D-521의 근거)."""

    def body(self, *texts_by_photo):
        return body_of(photos=tuple(dphoto(number, texts=texts) for number, texts in enumerate(texts_by_photo, 1)))

    def test_the_body_check_finds_nothing_new_in_ordinary_menu_receipt_and_label_lines(self):
        plain = body_of(photos=tuple(dphoto(number) for number in (1, 2, 3)))
        with_text = self.body(MENU, RECEIPT, ("원재료명: 정제수, 설탕", "내용량 500ml", "유통기한 제조일로부터 12개월"))
        shape = lambda body: sorted((item.kind, item.sub, item.fingerprint) for item in garbage.scan(body.selected_title, body.body_text).findings)
        self.assertEqual(shape(with_text), shape(plain))

    def test_the_frame_repeating_for_every_photo_is_not_reported_as_a_repeated_sentence_or_word(self):
        body = self.body(*[tuple(f"가게 {number}번 안내 문구 {line}" for line in range(3)) for number in range(1, 7)])
        self.assertEqual(body.body_text.count(FRAME), 6)
        report = garbage.scan(body.selected_title, body.body_text)
        self.assertEqual([item for item in report.findings if item.kind in ("dup_sentence", "dup_word")], [])

    def test_the_body_check_reads_the_lines_as_lines_of_one_paragraph(self):
        text = self.body(MENU).body_text
        first = garbage.locate(text, text.index(MENU[0]))
        third = garbage.locate(text, text.index(MENU[2]))
        self.assertEqual(first[0], third[0], "같은 문단")
        self.assertEqual((first[1], third[1]), (1, 3), "그 문단의 첫째 줄과 셋째 줄")
        self.assertEqual(garbage.locate(text, text.index(FRAME))[0] + 1, first[0], "틀 문장은 바로 앞 문단")

    def test_the_check_still_reports_a_real_template_leftover_inside_the_paragraph(self):
        """입구가 걸러도 손으로 넣은 값(복사하다 생긴 글)에 `{{ … }}` 가 있으면 점검이 위치로 알린다 — 점검을 풀지 않았다."""
        text = body_of(photos=(dphoto(1, texts=("메뉴 하나", "{{이름}} 님께", "메뉴 셋")),)).body_text
        found = [item for item in garbage.scan("", text).findings if item.kind == "placeholder"]
        self.assertEqual(len(found), 1)
        self.assertEqual(garbage.locate(text, found[0].spans[0][1])[1], 2, "문단의 둘째 줄")

    def test_the_copy_conversion_keeps_every_line_and_only_turns_the_slots_into_image_marks(self):
        body = body_of(photos=(dphoto(1, texts=MENU), dphoto(2, section="마무리", texts=ODD)))
        copied = pf.to_copy_text(body.body_text)
        self.assertNotIn("{{", copied)
        self.assertEqual(copied.replace("[이미지 1]", "{{사진 1}}").replace("[이미지 2]", "{{사진 2}}"), body.body_text)
        for line in (*MENU, *ODD):
            self.assertIn(line, copied.split(NL))
        self.assertEqual(copied.count(NL), body.body_text.count(NL), "줄바꿈 수가 그대로")

    def test_the_markdown_package_path_joins_the_lines_of_a_paragraph_but_a_draft_body_never_goes_that_way(self):
        body = body_of(photos=(dphoto(1, texts=MENU[:3]),))
        package = naver.build_package(profile("naver_a"), title="제목", body=body.body_text, tags=("태그",), ai_assisted=False)
        self.assertIn(" ".join(MENU[:3]), package.core_text, "마크다운 길은 한 문단의 줄을 공백으로 합친다")
        self.assertNotIn(NL.join(MENU[:3]), package.core_text)
        callers = sorted(path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py") if "build_package(" in path.read_text(encoding="utf-8") and path.relative_to(SRC).as_posix() != "render/naver.py")
        self.assertEqual(callers, ["service/naver_flow.py"], "초안 본문은 평문이다 — 이 길(원고 → 네이버 패키지)로 보내는 코드가 새로 생기면 결정 D-521 을 다시 본다")


class FuzzTest(unittest.TestCase):
    """무작위(씨앗 고정) 본문 구조 × 확정 글자가 든 무작위 사진 — 어떤 입력에서도: 사진마다 자리표시자 한 번 · 틀 문장 바로 뒤에 그 사진의 글자 문단 · 틀로 만든 글은 자리표시자와 틀 문장뿐 ·
    원래 문단은 사진 줄을 빼면 그대로 · 글자가 없는 사진은 옛 줄 그대로."""

    WORDS = ("가나", "다라마", "바사", "아자차", "카타", "파하")
    SECTION_NAMES = ("", "도입", "내용 소제목", "분위기 소제목", "마무리", "주의", "경험", "없는 소제목 글")

    def sentence(self, rng):
        return " ".join(rng.choice(self.WORDS) for _ in range(rng.randint(1, 4))) + rng.choice((".", "!", "?", "…", "."))

    def random_blocks(self, rng):
        result = [block(db.INTRO, "", *[" ".join(self.sentence(rng) for _ in range(rng.randint(1, 3))) for _ in range(rng.randint(0, 3))])]
        for index in range(rng.randint(1, 5)):
            result.append(block(rng.choice((db.SECTION, db.SECTION, db.EXPERIENCE)), rng.choice(("소제목 둘", "분위기 이야기", f"소제목 {index}")), *[" ".join(self.sentence(rng) for _ in range(rng.randint(1, 4))) for _ in range(rng.randint(0, 4))]))
        result.append(block(db.CLOSING, "마무리", *[self.sentence(rng) for _ in range(rng.randint(0, 2))]))
        return tuple(result)

    def random_photos(self, rng):
        kinds = (("auto", 0), ("top", 0), ("after_heading", 0), ("after_paragraph", 1), ("after_paragraph", 3), ("between_sentences", 1), ("between_sentences", 2), ("between_sentences", 9), ("after_paragraph", 50))
        photos = []
        for number in rng.sample(range(1, 40), rng.randint(1, 10)):
            kind, nth = rng.choice(kinds)
            texts = tuple(f"{number}번 {rng.choice(self.WORDS)} {rng.randint(1000, 99999):,}원 {index}" for index in range(rng.choice((0, 0, 1, 2, 5, 12))))
            photos.append(dphoto(number, kind=kind, nth=nth, section=rng.choice(self.SECTION_NAMES), subject=rng.choice(("", f"대상 {number}")), note=rng.choice(("", f"메모 {number}")), caption=rng.choice(("", f"설명 {number}")),
                                 order=rng.randint(1, 5), texts=texts))
        return tuple(photos)

    def test_the_invariants_hold_for_three_hundred_random_inputs(self):
        rng = random.Random(20261122)
        for round_number in range(300):
            source, photos = self.random_blocks(rng), self.random_photos(rng)
            result, notes = pf.place_photos(source, photos)
            self.assertEqual((result, notes), pf.place_photos(source, tuple(reversed(photos))), "넘기는 순서는 상관없다")
            flat = [(text, made) for item in result for text, made in zip(item.paragraphs, item.generated)]
            texts = [text for text, _made in flat]
            expected_pairs = sorted(NL.join(photo.confirmed_texts) for photo in photos if photo.confirmed_texts)
            followers = [flat[index + 1] for index, item in enumerate(flat) if item == (FRAME, True) and index + 1 < len(flat)]
            self.assertEqual(sorted(text for text, _made in followers), expected_pairs, round_number)
            self.assertTrue(all(made is False for _text, made in followers), "틀 문장 바로 뒤는 사용자 글")
            self.assertEqual(texts.count(FRAME), len(expected_pairs), round_number)
            made_by_app = {text for text, made in flat if made and (text == FRAME or text.startswith("{{사진 "))}
            self.assertEqual(made_by_app, {f"{{{{사진 {photo.number}}}}}" for photo in photos} | ({FRAME} if expected_pairs else set()), round_number)
            for photo in photos:
                self.assertEqual(texts.count(f"{{{{사진 {photo.number}}}}}"), 1)
                if photo.confirmed_texts:
                    self.assertEqual(texts.count(NL.join(photo.confirmed_texts)), 1, "사진마다 글이 달라 한 번뿐")
                else:
                    self.assertEqual(pf.photo_lines(photo), old_photo_lines(photo))
            added = {text for photo in photos for text, _made in pf.photo_lines(photo)}
            for before, after in zip(source, result):
                kept = [text for text in after.paragraphs if text not in added]
                self.assertEqual(" ".join(" ".join(kept).split()), " ".join(" ".join(before.paragraphs).split()), (round_number, before.heading))
            for note in notes:
                self.assertRegex(note, r"^사진 [0-9]+번은 [^0-9{}]+$", note)


class LimitsTest(unittest.TestCase):
    """저장한 초안의 '처음 만든 초안' 본문 한도(`MAX_BASE_BODY_CHARS`)와 확정 글자의 크기."""

    def base_draft(self, body):
        return sd.BaseDraft.build(body.selected_title, body.titles, body.body_text, body.checks, body.domain, body.replaced)

    def test_ten_receipts_of_fifty_one_lines_still_fit_the_saved_base_draft_limit(self):
        photos = tuple(dphoto(number, texts=tuple(f"{number}번 영수증 {line}" for line in RECEIPT)) for number in range(1, 11))
        body = body_of(photos=photos)
        self.assertLess(len(body.body_text), sd.MAX_BASE_BODY_CHARS)
        self.assertEqual(self.base_draft(body).body, body.body_text)

    def test_a_body_over_the_mask_limit_is_refused_as_a_whole_and_never_cut(self):
        """30장 × 60줄 × 200자(약 36만 자)는 마지막 관문의 비밀 모양 검사(`security.mask` 는 20만 자까지만 본다)가 통째로 거절한다 — 몰래 자르지 않는다. 그 전에 저장 한도(3만 자)가 먼저 막는다."""
        def pile(count):
            return tuple(dphoto(number, texts=tuple(f"{number:02d}-{index:02d}-" + "가" * 194 for index in range(60))) for number in range(1, count + 1))
        under = body_of(photos=pile(15))
        self.assertLess(len(under.body_text), mask_module.MAX_MASK_INPUT)
        self.assertGreater(len(under.body_text), sd.MAX_BASE_BODY_CHARS, "만들어지지만 저장 한도는 넘는다")
        self.assertGreater(30 * 60 * 200, mask_module.MAX_MASK_INPUT)
        error = expect_error(self, lambda: body_of(photos=pile(30)), "CONTENT_INVALID")
        self.assertNotIn("가가가가", str(error) + error.detail + repr(error.slots) + error.log_line(), "오류에 글이 없다")

    def test_a_huge_pile_of_confirmed_text_makes_the_save_say_the_limit_instead_of_cutting_text(self):
        lines = tuple(f"{index:02d}" + "가" * 198 for index in range(60))
        photos = tuple(dphoto(number, texts=tuple(f"{number:02d}-{line}"[:200] for line in lines)) for number in range(1, 5))
        body = body_of(photos=photos)
        self.assertGreater(len(body.body_text), sd.MAX_BASE_BODY_CHARS)
        expect_error(self, lambda: self.base_draft(body), "DRAFT_LIMIT")
        for photo in photos:
            self.assertIn(NL.join(photo.confirmed_texts), body.body_text, "본문은 잘리지 않았다 — 저장만 한도 문장으로 거절된다")


class FrameStyleTest(unittest.TestCase):
    """틀 문장은 글의 문체를 따른다 — 합니다체 글에 해요체 문장이 섞이지 않는다(독립 검증 QP-1, 결정 D-520)."""

    def hapsyo(self, blog="naver_a"):
        return PROFILE_MAKERS["자세히"](blog)

    def test_the_two_frames_are_one_sentence_in_the_two_styles_and_both_pass_every_made_sentence_check(self):
        self.assertEqual((pf.TEXT_FRAME, pf.TEXT_FRAME_HAPSYO), (FRAME, FRAME_HAPSYO))
        self.assertTrue(pf.TEXT_FRAME.endswith("이에요.") and pf.TEXT_FRAME_HAPSYO.endswith("입니다."), "해요체와 합니다체")
        self.assertEqual(pf.TEXT_FRAME.removesuffix("이에요."), pf.TEXT_FRAME_HAPSYO.removesuffix("입니다."), "끝맺음만 다르다")
        for frame in (pf.TEXT_FRAME, pf.TEXT_FRAME_HAPSYO):
            with self.subTest(frame=frame):
                self.assertEqual(claims.find_violations([frame]), ())
                self.assertEqual(claims.find_claims([frame]), ())
                self.assertEqual(len(garbage.sentence_key(frame)), 9)
                self.assertLess(len(garbage.sentence_key(frame)), garbage.MIN_SENTENCE_KEY, "한 글자만 길어져도 사진마다 '같은 문장' 경고가 난다")
                self.assertIsNone(re.search("[0-9]", frame))
                for word in ("메뉴", "가격", "음식", "맛", "추천", "상호", "가게", "원산지"):
                    self.assertNotIn(word, frame)

    def test_text_frame_follows_the_style_and_any_other_style_falls_back_to_the_house_style(self):
        self.assertEqual((bl.STYLE_HAEYO, bl.STYLE_HAPSYO), (pf.STYLE_HAEYO, pf.STYLE_HAPSYO), "이 모듈이 글자로 적은 문체 이름이 본문 생성기의 것과 같다")
        self.assertEqual((pf.text_frame(), pf.text_frame(pf.STYLE_HAEYO), pf.text_frame(pf.STYLE_HAPSYO)), (FRAME, FRAME, FRAME_HAPSYO))
        for style in (None, "", "unknown"):
            self.assertEqual(pf.text_frame(style), FRAME, repr(style))

    def test_photo_lines_and_place_photos_take_the_style_and_the_frame_stays_marked_as_made(self):
        photo = dphoto(3, caption="간판 앞에서", subject="매장 입구 간판", texts=MENU)
        self.assertEqual(pf.photo_lines(photo), pf.photo_lines(photo, pf.STYLE_HAEYO))
        self.assertEqual(pf.photo_lines(photo, pf.STYLE_HAPSYO), old_photo_lines(photo) + ((FRAME_HAPSYO, True), (NL.join(MENU), False)))
        for style, frame, other in ((pf.STYLE_HAEYO, FRAME, FRAME_HAPSYO), (pf.STYLE_HAPSYO, FRAME_HAPSYO, FRAME)):
            with self.subTest(style=style):
                result, _notes = pf.place_photos((block(db.INTRO, "", "첫 문단이다."),), (dphoto(1, texts=MENU[:2]),), style=style)
                flat = [(text, made) for item in result for text, made in zip(item.paragraphs, item.generated)]
                self.assertIn((frame, True), flat)
                self.assertNotIn((other, True), flat)
                self.assertIn((NL.join(MENU[:2]), False), flat)

    def test_a_hapsyo_profile_makes_the_hapsyo_frame_and_every_other_profile_the_haeyo_frame(self):
        photos = (dphoto(1, kind="top", texts=MENU[:2]), dphoto(2, section="마무리", texts=MENU[2:4]), dphoto(3))
        for number, row in enumerate(CANDIDATES):
            for name, maker in PROFILE_MAKERS.items():
                for blog in ("naver_a", "naver_b"):
                    with self.subTest(candidate=number, profile=name, blog=blog):
                        body = body_of(make(*row), maker(blog), None, blog, photos=photos)
                        self.assertEqual(body.style, bl.STYLE_HAPSYO if name == "자세히" else bl.STYLE_HAEYO)
                        frame, other = (FRAME_HAPSYO, FRAME) if body.style == bl.STYLE_HAPSYO else (FRAME, FRAME_HAPSYO)
                        self.assertEqual(body.generated_texts().count(frame), 2, "확정한 글자가 있는 사진 둘에 한 번씩")
                        self.assertNotIn(other, body.body_text)
                        self.assertEqual(claims.find_violations(list(body.generated_texts())), ())

    def test_the_hapsyo_body_without_confirmed_text_is_the_old_hapsyo_body(self):
        photos = (dphoto(1, kind="top", subject="매장 입구 간판", note="주차는 뒤쪽입니다"), dphoto(2, section="마무리", caption="메뉴판 앞에서"), dphoto(3, objects=("탁자 위의 컵",)))
        prof = self.hapsyo()
        self.assertEqual(body_of(prof=prof, photos=photos), built_the_old_way(photos, prof=prof))
        self.assertNotIn(FRAME_HAPSYO, body_of(prof=prof, photos=photos).body_text)

    def test_the_hapsyo_frame_is_checked_by_the_final_guard_too_and_the_haeyo_frame_is_left_alone(self):
        photos = (dphoto(1, texts=MENU[:2]),)
        bad = "직접 써 보니 사진에 적힌 글입니다."
        self.assertTrue(claims.find_violations([bad]))
        with mock.patch.object(pf, "TEXT_FRAME_HAPSYO", bad):
            expect_error(self, lambda: body_of(prof=self.hapsyo(), photos=photos), "CONTENT_INVALID")
            self.assertIn(FRAME, body_of(photos=photos).generated_texts(), "해요체 글은 이 틀을 쓰지 않는다")
        self.assertIn(FRAME_HAPSYO, body_of(prof=self.hapsyo(), photos=photos).generated_texts())

    def test_the_hapsyo_frame_may_repeat_for_every_photo_without_a_repeated_sentence_or_word_warning(self):
        photos = tuple(dphoto(number, texts=tuple(f"가게 {number}번 안내 문구 {line}" for line in range(3))) for number in range(1, 7))
        body = body_of(prof=self.hapsyo(), photos=photos)
        self.assertEqual(body.body_text.count(FRAME_HAPSYO), 6)
        report = garbage.scan(body.selected_title, body.body_text)
        self.assertEqual([item for item in report.findings if item.kind in ("dup_sentence", "dup_word")], [])


class JoinedLinesTest(unittest.TestCase):
    """줄 하나씩은 입구를 지나도, 줄바꿈으로 이은 본문이 `security.mask` 의 '이름: 값' 꼴로 읽히면 마지막 관문(`_final_guard`)이 초안 전체를 막는다 — 독립 검증 SP-1(결정 D-522).
    사진 정보 검사(`draft_inputs`)가 이은 모양도 미리 보고 사진 번호로 멈춘다 — 화면이 사진 정보를 가리키고 글은 어디에도 없다."""

    LABELS = ("Wi-Fi Password:", "Password:", "Token:", "Secret:", "Credentials:", "API Key:", "License Key:", "Master key:", "Secret Key:", "x-api-key:", "password=", "secret =", "token :", "Passwd :", "API_KEY=")
    STARTS_A_VALUE = ("12345678", "아메리카노", "와이파이", "abcd", "(주)한솔", "1234-5678", '"abcd"', "'abcd'")           # 이름 줄 바로 뒤에 오면 `mask` 가 값으로 읽는 줄 — 첫 낱말이 네 글자 이상이거나 따옴표로 감싼 글
    DOES_NOT = ("콘센트 사용 가능", "콘센트", "4,500원", "12,000원", "카페 와이파이", "합계", "ab", "x y z", "—")           # 첫 낱말이 짧거나 쉼표·공백에서 끊겨 값으로 안 읽히는 줄
    ORDINARY_LABELS = ("영업시간:", "원재료명:", "TEL:", "Wi-Fi:", "Menu:", "ID:", "Session ID:", "주소:", "가격 :")            # 비밀 이름이 아닌 평범한 쌍점 줄
    SPLIT = (("Wi-Fi Password", ": 12345678"), ("Password", "= abcd1234"), ("API Key", ":xyz98765"), ("Token", ": 가나다라마"))   # 이름과 쌍점이 두 줄로 갈라진 글 — 줄 하나씩은 아무 데도 안 걸린다

    def manifest_with(self, lines):
        """사진 셋 — 둘째가 시험할 줄을 가진다(오류가 가리키는 사진 번호를 보려고)."""
        manifest, dropped = manifest_of(dict(lines=("첫째 사진 글",)), dict(lines=lines), dict(lines=("셋째 사진 글",)))
        self.assertEqual(dropped, [0, 0, 0], "입구는 줄 하나씩이라 모두 받는다")
        return manifest

    def assert_refused_at_photo_two(self, lines):
        error = expect_error(self, lambda: pm.draft_inputs(self.manifest_with(lines)), "CONTENT_INVALID")
        self.assertTrue(error.slots["항목"].startswith("사진 2 — "), error.slots)
        for shown in (str(error), error.detail, repr(error.slots), error.log_line()):
            for line in lines:
                self.assertNotIn(line, shown, "오류에 글이 없다")

    def test_every_label_and_follower_line_passes_the_entrance_alone(self):
        for line in (*self.LABELS, *self.STARTS_A_VALUE, *self.DOES_NOT, *self.ORDINARY_LABELS, *(line for pair in self.SPLIT for line in pair)):
            with self.subTest(line):
                self.assertEqual(pm.check_text("observation", line), (line, None), "입구는 줄 하나씩만 본다")

    def test_a_name_line_followed_by_a_line_that_starts_a_value_stops_the_draft_at_the_photo_info_naming_the_photo(self):
        for label, follower in itertools.product(self.LABELS, self.STARTS_A_VALUE):
            lines = ("아메리카노 4,500원", label, follower, "콘센트 사용 가능")
            with self.subTest(label=label, follower=follower):
                self.assertNotEqual(mask_module.mask(NL.join(lines)), NL.join(lines), "이은 글은 `mask` 가 바꾼다 — 마지막 관문이 막을 글")
                self.assert_refused_at_photo_two(lines)

    def test_the_wifi_sign_case_of_the_verifier_is_refused_at_the_photo_and_one_line_is_cut_at_the_entrance_instead(self):
        lines = ("아메리카노 4,500원", "Wi-Fi Password:", "12345678", "콘센트 사용 가능")
        self.assert_refused_at_photo_two(lines)
        manifest, dropped = manifest_of(dict(lines=("아메리카노 4,500원", "Wi-Fi Password: 12345678", "콘센트 사용 가능")))
        self.assertEqual(dropped, [1], "같은 내용이 한 줄이면 입구가 거른다 — 쪼개진 두 줄만 이 틈이었다")
        self.assertEqual(body_of(photos=pm.draft_inputs(manifest)).body_text.count("콘센트 사용 가능"), 1)

    def test_the_final_guard_is_still_there_and_stops_the_same_lines_when_they_are_handed_to_the_body_directly(self):
        for label in self.LABELS:
            with self.subTest(label=label):
                error = expect_error(self, lambda: body_of(photos=(dphoto(2, texts=("아메리카노 4,500원", label, "12345678", "콘센트 사용 가능")),)), "CONTENT_INVALID")
                self.assertEqual(error.slots, {"항목": "본문"}, "마지막 관문의 오류 — 사진 정보 검사의 오류('사진 N — …')와 다르다")
        for follower in self.STARTS_A_VALUE:
            with self.subTest(follower=follower):
                expect_error(self, lambda: body_of(photos=(dphoto(2, texts=("Password:", follower)),)), "CONTENT_INVALID")

    def test_an_unconfirmed_name_line_is_not_joined_but_a_confirmed_one_at_the_end_is_refused_until_it_is_removed(self):
        manifest, _dropped = manifest_of(dict(lines=("아메리카노 4,500원", "Wi-Fi Password:", "12345678", "콘센트 사용 가능"), confirm=(0, 2, 3)))
        self.assertEqual(pm.draft_inputs(manifest)[0].confirmed_texts, ("아메리카노 4,500원", "12345678", "콘센트 사용 가능"), "이름 줄을 확인하지 않으면 값 줄이 이어져도 걸리지 않는다")
        self.assertIn("12345678", body_of(photos=pm.draft_inputs(manifest)).body_text)
        manifest, _dropped = manifest_of(dict(lines=("아메리카노 4,500원", "Wi-Fi Password:", "12345678"), confirm=(0, 1)))
        expect_error(self, lambda: pm.draft_inputs(manifest), "CONTENT_INVALID")
        manifest = pm.remove_item(manifest, "p001", pm.TEXTS, 1)
        self.assertEqual(pm.draft_inputs(pm.set_confirmed(manifest, "p001", True))[0].confirmed_texts, ("아메리카노 4,500원",), "이름 줄을 지우면 풀린다")

    def test_a_name_and_its_colon_split_over_two_lines_is_caught_too(self):
        for name, rest in self.SPLIT:
            with self.subTest(name=name):
                self.assertNotEqual(mask_module.mask(name + NL + rest), name + NL + rest)
                self.assert_refused_at_photo_two(("아메리카노 4,500원", name, rest, "콘센트 사용 가능"))

    def test_followers_that_start_no_value_and_ordinary_colon_lines_are_not_refused(self):
        pairs = [*itertools.product(self.LABELS, self.DOES_NOT), *itertools.product(self.ORDINARY_LABELS, (*self.STARTS_A_VALUE, *self.DOES_NOT))]
        for number, (label, follower) in enumerate(pairs):
            lines = ("아메리카노 4,500원", label, follower, "주차는 뒤쪽이에요")
            with self.subTest(label=label, follower=follower):
                self.assertEqual(mask_module.mask(NL.join(lines)), NL.join(lines))
                inputs = pm.draft_inputs(self.manifest_with(lines))
                self.assertEqual(inputs[1].confirmed_texts, lines)
                if number % 9 == 0:
                    self.assertIn(NL.join(lines), body_of(photos=inputs).body_text)
        for label in self.ORDINARY_LABELS:
            with self.subTest(last_line=label):
                self.assertFalse(pm.joined_looks_secret(("아메리카노 4,500원", label)), "비밀 이름이 아닌 쌍점 줄은 맨 끝이어도 괜찮다")

    def test_ordinary_menus_receipts_and_odd_lines_are_never_refused(self):
        for name, lines in (("menu", MENU), ("receipt", RECEIPT), ("odd", ODD), ("one", MENU[:1])):
            with self.subTest(name):
                self.assertFalse(pm.joined_looks_secret(lines))
        self.assertFalse(pm.joined_looks_secret(()), "줄이 없으면 거짓")
        manifest, _dropped = manifest_of(dict(lines=MENU), dict(lines=RECEIPT), dict(lines=ODD))
        self.assertEqual(len(pm.draft_inputs(manifest)), 3)

    def test_the_check_joins_the_lines_with_a_line_break_like_the_body_does_so_a_name_and_a_long_word_on_two_lines_pass(self):
        """공백으로 이으면 `Password abcdefgh12345678`(이름 바로 뒤 긴 값)으로 읽혀 걸리지만 본문은 줄바꿈으로 잇는다 — 본문에서 걸리지 않을 글을 미리 거절하지 않는다."""
        for name, rest in (("Password", "abcdefgh12345678"), ("Token", "Zq8vN2kLm4Xp7RtY9aBc"), ("API Key", "ab12cd34ef56gh78")):
            with self.subTest(name=name):
                self.assertNotEqual(mask_module.mask(name + " " + rest), name + " " + rest, "공백으로 이으면 걸린다")
                self.assertEqual(mask_module.mask(name + NL + rest), name + NL + rest, "줄바꿈으로 이으면 안 걸린다 — 본문은 이쪽이다")
                manifest, _dropped = manifest_of(dict(lines=("아메리카노 4,500원", name, rest, "주차는 뒤쪽이에요")))
                self.assertIn(NL.join((name, rest)), body_of(photos=pm.draft_inputs(manifest)).body_text)

    def test_a_name_line_as_the_last_line_is_refused_too_because_what_follows_in_the_body_would_become_its_value(self):
        for label in self.LABELS:
            with self.subTest(label=label):
                self.assertTrue(pm.joined_looks_secret(("아메리카노 4,500원", label)))
                self.assertNotEqual(mask_module.mask(label + NL + NL + "{{사진 2}}"), label + NL + NL + "{{사진 2}}", "다음 사진 자리({{사진 N}})가 값으로 읽힌다")
                self.assert_refused_at_photo_two(("아메리카노 4,500원", label))
        error = expect_error(self, lambda: body_of(photos=(dphoto(1, kind="top", texts=("메뉴 하나", "Password:")), dphoto(2, kind="top"))), "CONTENT_INVALID")
        self.assertEqual(error.slots, {"항목": "본문"}, "손으로 넣으면 실제로 다음 사진 자리가 값이 되어 마지막 관문이 막는다")

    def test_one_probe_word_stands_for_every_text_that_can_follow_the_lines_in_a_body(self):
        """무작위 줄 × 뒤따를 수 있는 글(따옴표로 시작하는 글 포함): 이은 글을 `mask` 가 바꾸면 사진 정보 검사도 거절한다(거절이 더 넓은 것은 괜찮다 — 그 반대만 틈이다). 이름 줄이 맨 끝일 때 무엇이 뒤따르든 한 낱말(`JOIN_PROBE`)로 대신할 수 있다는 근거다."""
        rng = random.Random(20261122)
        pieces = ("Wi-Fi Password:", "Password", "Token:", "secret", "API Key", "License Key:", ":", "=", ":=", '"', "'", "abcd", "12345678", "아메리카노", "콘센트", "4,500원", "합계", "—", "x y", "Wi-Fi", "ID: cafe", "영업시간:", "Key:", "API", "Key", ",", ";", "&")
        follows = ("abcd", "12345678", '"맛집"', "'맛집'", '"맛집', "맛집", "{{사진 2}}", "그래서, 다음", "ab", "가나다라", '"', "'x'", "이용 안내", "(주)한솔", "※ 주의", "—", "a,b,c", "그래서 다음 문단이에요")
        innocent = [text for text in follows if mask_module.mask(text) == text]
        self.assertEqual(innocent, list(follows), "뒤따르는 글 자체는 비밀 모양이 아니다")
        changed = 0
        for round_number in range(600):
            lines = tuple(rng.choice(pieces) for _ in range(rng.randint(1, 4)))
            text = NL.join(lines) + NL + NL + rng.choice(follows)
            if mask_module.mask(text) != text:
                changed += 1
                self.assertTrue(pm.joined_looks_secret(lines), (round_number, lines, text))
        self.assertGreater(changed, 60, "시험이 비어 있지 않다 — 이은 글이 바뀌는 경우가 충분히 나온다")

    def test_when_the_photo_info_check_lets_the_lines_through_the_body_always_builds(self):
        """무작위 사진 목록 — 사진 정보 검사(`draft_inputs`)가 통과시키면 본문 만들기가 입구 아닌 마지막 관문에서 멈추는 일이 없다. 멈추는 쪽은 늘 사진 번호만 말한다."""
        rng = random.Random(20261123)
        pool = (*self.LABELS[:6], *self.STARTS_A_VALUE, *self.DOES_NOT, *self.ORDINARY_LABELS[:4], *(line for pair in self.SPLIT for line in pair), *MENU, "아메리카노 4,500원", "콘센트 사용 가능")
        blocked = built = 0
        for round_number in range(120):
            specs = [dict(lines=tuple(rng.choice(pool) for _ in range(rng.randint(1, 6)))) for _ in range(rng.randint(1, 3))]
            manifest, _dropped = manifest_of(*specs)
            try:
                inputs = pm.draft_inputs(manifest)
            except AppError as error:
                self.assertEqual(error.code, "CONTENT_INVALID", round_number)
                self.assertRegex(error.slots["항목"], r"^사진 [1-3] — ", round_number)
                blocked += 1
                continue
            body_of(photos=inputs)                    # 올라오는 오류가 있으면 시험이 여기서 실패한다
            built += 1
        self.assertGreater(blocked, 20)
        self.assertGreater(built, 20)


class DocsTest(unittest.TestCase):
    """결정 기록·변경 이력·보안 문서·화면 상태 문서가 이 길을 사실대로 적는다(숫자는 코드의 값과 견준다)."""

    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def section(self, rel, heading):
        """제목 줄에서 다음 `## ` 제목 줄 앞까지(마지막 절이면 끝까지) — 다른 묶음이 이 절 뒤에 절을 덧붙여도 그쪽 글을 읽지 않는다."""
        text = self.read(rel)
        self.assertEqual(text.count(heading), 1, heading)
        start = text.index(heading)
        stop = text.find(chr(10) + "## ", start + len(heading))
        return text[start:] if stop < 0 else text[start:stop]

    def new_parts(self):
        lines = self.read("docs/DECISIONS.md").splitlines()
        decisions = [line for number in range(520, 526) for line in lines if line.startswith(f"| D-{number} |")]
        changelog = [line for line in self.read("CHANGELOG.md").splitlines() if "결정 D-520 에서 D-525" in line]
        return {"DECISIONS": "\n".join(decisions), "SECURITY": self.section("docs/SECURITY.md", "## 글자 읽기 — 확정한 글자만 초안 본문에 들어간다"),
                "UI_STATES": self.section("docs/UI_STATES.md", "## 11. 확정한 글자가 든 초안 본문의 모습"), "CHANGELOG": "\n".join(changelog)}

    def test_the_six_decision_rows_are_there_once_each_and_the_changelog_has_one_line(self):
        lines = self.read("docs/DECISIONS.md").splitlines()
        for number in range(520, 526):
            found = [line for line in lines if line.startswith(f"| D-{number} |")]
            self.assertEqual(len(found), 1, f"D-{number}")
            self.assertTrue(found[0].rstrip().endswith("|"), f"D-{number}")
        self.assertEqual(len([line for line in self.read("CHANGELOG.md").splitlines() if "결정 D-520 에서 D-525" in line]), 1)

    def test_the_docs_name_the_facts_and_their_numbers_match_the_code(self):
        parts = self.new_parts()
        for name, part in parts.items():
            self.assertIn(pf.TEXT_FRAME, part, name)
            self.assertIn(pf.TEXT_FRAME_HAPSYO, part, name)
        decisions, security, states = parts["DECISIONS"], parts["SECURITY"], parts["UI_STATES"]
        for needle in ("TEXT_FRAME", "TEXT_FRAME_HAPSYO", "text_frame", "photo_lines", "confirmed_texts", "_final_guard", "check_text", "LineIndex", "to_copy_text", "render/naver.build_package", "service/naver_flow.py", "MAX_BASE_BODY_CHARS", "DRAFT_LIMIT",
                       "다시 만들기", "스물한 가지", "일곱 가지", "joined_looks_secret", "JOIN_PROBE", "pho_make_blocked", "MAX_SCAN_CHARS", "확인창도 없이", "같은 줄이 둘이면 본문에는 한 줄만 들어간다", "비밀번호:", "dup_word", "독립 검증"):
            self.assertIn(needle, decisions, needle)
        self.assertIn(f"길이가 {len(garbage.sentence_key(pf.TEXT_FRAME))} 라", decisions)
        self.assertIn(f"기준({garbage.MIN_SENTENCE_KEY})", decisions)
        self.assertIn(f"영수증 한 장({len(RECEIPT)}줄)", decisions)
        self.assertIn(f"빈 줄 {len(RECEIPT) - 1}개", decisions)
        self.assertEqual((len(ManifestFlowTest.ADVERSARIAL), len(ManifestFlowTest.CLEANED)), (21, 7), "결정 D-522 의 '스물한 가지·일곱 가지'")
        for name in ("SECURITY", "UI_STATES"):
            self.assertIn(f"{sd.MAX_BASE_BODY_CHARS:,}자", parts[name], name)
        for name in ("DECISIONS", "SECURITY", "UI_STATES"):
            self.assertIn(f"{mask_module.MAX_MASK_INPUT:,}자", parts[name], name)
            self.assertIn(f"{shape.MAX_SCAN_CHARS:,}자", parts[name], name)
            self.assertIn("확인창도 없이", parts[name], name)
        for needle in ("draft_inputs", "_final_guard", "check_text", "DRAFT_LIMIT", "다시 만들기", "service/naver_flow.py", "visible_text", "joined_looks_secret", "JOIN_PROBE", "같은 줄이 둘이면 본문에는 한 줄만 들어간다", "비밀번호:"):
            self.assertIn(needle, security, needle)
        for needle in ("글자 없음", "글자 있음", "줄을 이으면 키 모양", "글 모양 점검", "복사", "건강 효과 단정", "줄이 바뀜", "저장", "다시 열기", "알려 둔 한계", "pho_all_ask", "같은 줄이 둘이면 본문에는 한 줄만 들어간다", "합니다체", "비밀번호:"):
            self.assertIn(needle, states, needle)

    def test_the_screen_sentences_the_docs_quote_are_the_real_ones(self):
        """문서가 따옴표로 옮긴 화면 문장이 실제 문구와 같다(독립 검증 QP-6 — 문구가 바뀌어도 문서가 모르고 지나가던 틈)."""
        parts = self.new_parts()
        blocked = "사진 정보에 키처럼 보이는 글이 있어 초안을 만들지 않았어요"
        self.assertTrue(ui_text.T["pho_make_blocked"].startswith(blocked))
        self.assertIn(ui_text.T["pho_make_blocked"], parts["UI_STATES"], "화면 상태 문서는 문장 전체를 옮겼다")
        self.assertIn(blocked, parts["SECURITY"])
        copy_wording = "키나 토큰처럼 보이는 글이 들어 있어서 복사하지 않았어요"
        self.assertTrue(ui_text.T["drf_secret_body"].startswith(copy_wording))
        for name in ("DECISIONS", "UI_STATES"):
            self.assertIn(copy_wording, parts[name], name)
        self.assertIn("pho_all_ask", ui_text.T, "문서가 이름을 부른 문구 열쇠가 실제로 있다")

    def test_the_documented_test_counts_match_the_real_counts(self):
        """CHANGELOG 와 D-524 가 적은 시험 개수가 이 묶음의 두 시험 파일의 실제 개수와 같다(독립 검증 QP-6 — 개수가 틀려도 모르고 지나가던 틈)."""
        import test_ui_photo_text_body as ui_tests          # 늦게 가져온다 — 그 파일이 이 파일을 가져온다
        loader = unittest.defaultTestLoader
        content = loader.loadTestsFromModule(sys.modules[__name__]).countTestCases()
        ui = loader.loadTestsFromModule(ui_tests).countTestCases()
        parts = self.new_parts()
        self.assertIn(f"시험 {content + ui}개", parts["CHANGELOG"])
        self.assertIn(f"새 시험 {content + ui}개", parts["DECISIONS"])
        self.assertIn(f"`tests/test_content_photo_text_body.py` {content}개", parts["DECISIONS"])
        self.assertIn(f"`tests/test_ui_photo_text_body.py` {ui}개", parts["DECISIONS"])

    def test_the_new_doc_parts_have_no_ascii_tilde_and_no_http_link(self):
        for name, part in self.new_parts().items():
            self.assertNotIn(chr(0x7E), part, name)
            self.assertNotIn("http", part, name)


if __name__ == "__main__":
    unittest.main()
