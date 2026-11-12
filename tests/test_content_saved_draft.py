"""저장한 초안의 기록 모양(`content/saved_draft.py`) 시험 — 순수 파이썬이다(보관함·Qt 없이 돈다, CI 와 같은 조건).

지키는 것:
  1) **글자 그대로 돌아온다**: 제목·본문은 줄 끝(CRLF·LF·CR·섞임)·이모지·결합 글자(NFC 와 NFD 가 서로 다른 채로)·널 글자·짝 없는 서로게이트·앞뒤 공백까지 한 글자도 바뀌지 않고, 10만 자도 같다.
     보관함에 들어가는 글은 ASCII 뿐이다.
  2) 읽을 때는 엄격하다 — 모르는 칸·빠진 칸·틀린 종류·틀린 시각·다른 번호·낯선 종류 표지는 `DRAFT_CORRUPT`(번호만 알리고 글은 알리지 않는다), 더 새로운 판은 `STORE_VERSION_UNSUPPORTED`.
  3) 한도(`MAX_*`)를 넘으면 `DRAFT_LIMIT` 이고 글을 자르지 않는다. 한도 바로 안은 받는다.
  4) 번호는 시계·무작위 없이 입력의 지문이다(같은 입력은 같은 번호, 한 칸이라도 다르면 다른 번호).
  5) 소스 규칙: 이 모듈은 파일·시계·무작위·네트워크를 가져오지 않는다.
시험 입력의 키 모양은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다(소스에 완성된 키가 없다).
"""
import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as SS  # noqa: E402

from chanceblog_desktop.content import draft_options as do  # noqa: E402
from chanceblog_desktop.content import saved_draft as sd  # noqa: E402
from chanceblog_desktop.content import store as content_store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import scan  # noqa: E402

STAMP = "2026-11-11T09:30:15Z"
LATER = "2026-11-11T10:00:00Z"
MODULE = ROOT / "src" / "chanceblog_desktop" / "content" / "saved_draft.py"
NFC, NFD = chr(0x00E9), "e" + chr(0x0301)
EMOJI = chr(0x1F600)
FAMILY = chr(0x1F468) + chr(0x200D) + chr(0x1F469) + chr(0x200D) + chr(0x1F467)


def make(**more):
    values = dict(title="예시 제목", body="예시 본문", blog="naver_a", post_type="정보형", candidate_id="cand-1")
    values.update(more)
    values.setdefault("draft_id", sd.make_draft_id(STAMP, values["candidate_id"], values["blog"], values["title"], values["body"]))
    return sd.SavedDraft.build(revision=values.pop("revision", 1), created_at=values.pop("created_at", STAMP), updated_at=values.pop("updated_at", STAMP), **values)


def round_trip(draft):
    return sd.SavedDraft.from_text(draft.to_text(), draft.draft_id)


def error_of(call, *args, **kwargs):
    with unittest.TestCase().assertRaises(AppError) as caught:
        call(*args, **kwargs)
    return caught.exception


def sample_base():
    return sd.BaseDraft.build("만든 제목", ["만든 제목", "후보 둘", "후보 셋"], "만든 본문\n둘째 줄", ["확인 권장 하나", "확인 권장 둘"], "generic", ["후기형", "정보형"])


class RoundTripTest(unittest.TestCase):
    def check_text(self, title, body):
        draft = make(title=title, body=body)
        again = round_trip(draft)
        self.assertEqual(again.title, title)
        self.assertEqual(again.body, body)
        self.assertEqual(again, draft)
        return draft

    def test_plain_korean_and_english_come_back_equal(self):
        self.check_text("겨울철 실내 습도 관리", "첫 문단입니다.\n\n둘째 문단 — English too. 123 ㅋㅋ")

    def test_every_line_ending_style_is_kept_exactly(self):
        for body in ("a\r\nb", "a\nb", "a\rb", "a\r\r\nb\n\rc", "끝에 줄바꿈\r\n", "\r\n\r\n앞에 줄바꿈", "\n"):
            with self.subTest(body=body.encode("unicode_escape").decode("ascii")):
                self.check_text("제목", body)

    def test_emoji_zero_width_joiner_sequences_and_combining_marks_are_kept(self):
        self.check_text("제목 " + EMOJI + FAMILY, "본문 " + EMOJI * 3 + " " + FAMILY + " " + NFD + NFC + chr(0x0301) * 20)

    def test_nfc_and_nfd_stay_different_so_nothing_is_normalized(self):
        again = self.check_text(NFC, NFD)
        self.assertEqual((again.title, again.body), (NFC, NFD))
        self.assertNotEqual(again.title, again.body)

    def test_nul_lone_surrogates_bom_line_separators_tabs_and_edge_spaces_are_kept(self):
        odd = chr(0) + chr(0xD800) + "a" + chr(0xDFFF) + chr(0xFEFF) + chr(0x2028) + chr(0x2029) + "\t  가  \t" + chr(0x200B) + chr(0x00A0)
        self.check_text("  " + odd + "  ", odd + "\n" + odd)

    def test_a_high_surrogate_right_before_a_low_one_is_refused_because_reading_would_merge_them(self):
        for text in (chr(0xD800) + chr(0xDFFF), "가" + chr(0xD83D) + chr(0xDE00) + "나"):
            with self.subTest(text=text.encode("unicode_escape").decode("ascii")):
                self.assertEqual(error_of(make, title=text).code, "CONTENT_INVALID")
                self.assertEqual(error_of(make, body=text).code, "CONTENT_INVALID")
                self.assertEqual(error_of(make, tags=(text,)).code, "CONTENT_INVALID")
        self.assertEqual(make(title=chr(0xDFFF) + chr(0xD800)).title, chr(0xDFFF) + chr(0xD800), "뒤 반쪽 다음 앞 반쪽은 합쳐지지 않는다")

    def test_the_stored_text_is_ascii_only_even_for_odd_characters(self):
        draft = make(title="제목 " + EMOJI, body=chr(0xD800) + "본문" + chr(0))
        self.assertTrue(draft.to_text().isascii())

    def test_a_hundred_thousand_characters_come_back_the_same_and_the_utf8_bytes_too(self):
        body = ("가나다라마바사 abc 123 " + EMOJI + "\r\n") * 6000
        body = body[:100_000]
        self.assertEqual(len(body), 100_000)
        draft = self.check_text("제목", body)
        self.assertEqual(round_trip(draft).body.encode("utf-8"), body.encode("utf-8"))

    def test_the_largest_body_the_limit_allows_is_kept(self):
        self.check_text("제목", "가" * sd.MAX_BODY_CHARS)

    def test_keywords_tags_category_summary_topic_and_options_are_kept_as_given(self):
        draft = make(core_keywords=("핵심 가", " 핵심 나 "), sub_keywords=("보조", ""), tags=("#태그", "태그 2"), category="생활 정보", summary="한 줄 요약  끝", topic="후보 주제 — 부제",
                     options={"message": "전하고 싶은 말", "must_include": "줄1\n줄2", "urls": "https://example.invalid/a"}, post_type_choice="비교형", base=sample_base())
        again = round_trip(draft)
        self.assertEqual(again, draft)
        self.assertEqual(again.core_keywords, ("핵심 가", " 핵심 나 "))
        self.assertEqual(again.sub_keywords, ("보조", ""))
        self.assertEqual(again.options_dict(), {"message": "전하고 싶은 말", "must_include": "줄1\n줄2", "urls": "https://example.invalid/a"})
        self.assertEqual(again.post_type_choice, "비교형")
        self.assertEqual(again.base, sample_base())

    def test_the_same_input_gives_the_same_text_and_the_text_is_sorted_compact_json(self):
        first, second = make(tags=("가", "나")), make(tags=("가", "나"))
        self.assertEqual(first.to_text(), second.to_text())
        raw = json.loads(first.to_text())
        self.assertEqual(list(raw), sorted(raw))
        self.assertNotIn(", ", first.to_text())
        self.assertNotIn(": ", first.to_text())

    def test_the_base_draft_is_optional_and_its_absence_round_trips_as_none(self):
        self.assertIsNone(round_trip(make()).base)
        self.assertEqual(round_trip(make(base=sample_base())).base, sample_base())

    def test_there_is_no_way_to_drop_the_made_draft_from_a_record(self):
        """만든 초안 칸만 조용히 빼고 저장하는 길은 없앴다(D-368 — 운영자 결정: 발견 시 저장 중지·자동 삭제·치환 금지). 부르는 곳이 없는 메서드를 두지 않는다."""
        self.assertFalse(hasattr(sd.SavedDraft, "without_base"))
        self.assertEqual([name for name in dir(sd.SavedDraft) if "without" in name or "strip" in name or "drop" in name], [])


class IdTest(unittest.TestCase):
    def test_the_id_is_a_prefix_and_twenty_hex_characters(self):
        draft_id = sd.make_draft_id(STAMP, "c", "naver_a", "제목", "본문")
        self.assertRegex(draft_id, r"^dd-[0-9a-f]{20}$")
        self.assertTrue(sd.is_draft_id(draft_id))
        self.assertLessEqual(len(draft_id), 64, "보관함 번호 규칙(영숫자·밑줄·붙임표 64자까지)")

    def test_the_same_input_gives_the_same_id_and_any_part_changes_it(self):
        base = (STAMP, "c", "naver_a", "제목", "본문")
        self.assertEqual(sd.make_draft_id(*base), sd.make_draft_id(*base))
        for index, other in enumerate((LATER, "d", "naver_b", "제목2", "본문2")):
            changed = list(base)
            changed[index] = other
            with self.subTest(part=index):
                self.assertNotEqual(sd.make_draft_id(*changed), sd.make_draft_id(*base))

    def test_the_parts_cannot_slide_into_each_other(self):
        self.assertNotEqual(sd.make_draft_id(STAMP, "c", "naver_a", "ab", "c"), sd.make_draft_id(STAMP, "c", "naver_a", "a", "bc"))

    def test_odd_characters_never_break_the_id(self):
        self.assertTrue(sd.is_draft_id(sd.make_draft_id(STAMP, "c", "naver_a", chr(0xD800) + EMOJI, chr(0) + "본문")))

    def test_ids_that_are_not_the_shape_are_not_ids(self):
        for value in ("", "dd-", "dd-" + "g" * 20, "dd-" + "a" * 19, "dd-" + "a" * 21, "DD-" + "a" * 20, "x-" + "a" * 20, None, 5, b"dd-" + b"a" * 20, "dd-" + "a" * 20 + "\n"):
            with self.subTest(value=value):
                self.assertFalse(sd.is_draft_id(value))

    def test_the_short_id_is_the_first_eleven_characters(self):
        draft_id = sd.make_draft_id(STAMP, "c", "naver_a", "제목", "본문")
        self.assertEqual(sd.short_id(draft_id), draft_id[:11])
        self.assertEqual(sd.short_id("dd-abc"), "dd-abc")


class StrictReadTest(unittest.TestCase):
    def setUp(self):
        self.draft = make(base=sample_base(), options={"message": "x"}, tags=("가",))
        self.raw = json.loads(self.draft.to_text())

    def text_of(self, raw):
        return json.dumps(raw, ensure_ascii=True)

    def read(self, raw, draft_id=None):
        return sd.SavedDraft.from_text(raw if isinstance(raw, str) else self.text_of(raw), draft_id or self.draft.draft_id)

    def test_the_good_record_reads(self):
        self.assertEqual(self.read(self.raw), self.draft)

    def test_every_broken_record_is_a_corrupt_draft_that_names_only_the_number(self):
        broken = {"not json": "{", "empty": "", "a list": "[]", "a number": "5", "null": "null", "a string": '"x"'}
        for name, text in broken.items():
            with self.subTest(case=name):
                error = error_of(self.read, text)
                self.assertEqual(error.code, "DRAFT_CORRUPT")
                self.assertNotIn("예시 본문", error.rendered().message)
                self.assertIn(sd.short_id(self.draft.draft_id), error.rendered().message)

    def test_a_missing_or_extra_field_is_corrupt(self):
        for key in list(self.raw):
            raw = dict(self.raw)
            del raw[key]
            with self.subTest(missing=key):
                self.assertEqual(error_of(self.read, raw).code, "DRAFT_CORRUPT")
        extra = dict(self.raw, surprise="x")
        self.assertEqual(error_of(self.read, extra).code, "DRAFT_CORRUPT")

    def test_a_wrong_kind_marker_schema_or_id_is_corrupt(self):
        for name, change in (("kind", {"kind": "autosave"}), ("kind none", {"kind": None}), ("schema 0", {"schema": 0}), ("schema bool", {"schema": True}), ("schema text", {"schema": "1"}),
                             ("other id", {"draft_id": "dd-" + "0" * 20}), ("id not a string", {"draft_id": 5})):
            with self.subTest(case=name):
                self.assertEqual(error_of(self.read, dict(self.raw, **change)).code, "DRAFT_CORRUPT")

    def test_a_newer_schema_is_not_read_and_says_so(self):
        error = error_of(self.read, dict(self.raw, schema=sd.SCHEMA + 1))
        self.assertEqual(error.code, "STORE_VERSION_UNSUPPORTED")
        self.assertNotIn("예시 본문", error.rendered().message)

    def test_every_field_of_the_wrong_kind_is_corrupt(self):
        wrong = {"revision": ("1", 0, -1, True, 1.5, None), "created_at": ("2026-11-11", 5, None, "2026-11-11T09:30:15"), "updated_at": ("x", 5, None),
                 "candidate_id": (5, "a b", "x" * 65, None), "blog": ("naver_c", 5, None), "title": (5, None, ["x"]), "body": (5, None, ["x"]),
                 "core_keywords": ("x", 5, None, [5], {"a": 1}), "sub_keywords": ("x", [None]), "tags": ("x", [5]), "category": (5, None), "summary": (5, None), "topic": (5, None),
                 "post_type": ("없는 유형", 5, None), "post_type_choice": ("없는 유형", 5), "options": ([], "x", {"unknown": "x"}, {"message": 5}), "generator": ("", 5, "a b", "x" * 41),
                 "base": ("x", [], {}, {"title": "x"})}
        for name, values in wrong.items():
            for value in values:
                with self.subTest(field=name, value=repr(value)[:30]):
                    self.assertEqual(error_of(self.read, dict(self.raw, **{name: value})).code, "DRAFT_CORRUPT")

    def test_a_broken_base_inside_is_corrupt_and_the_error_does_not_show_the_text(self):
        for change in ({"titles": "x"}, {"checks": [5]}, {"replaced": ["a"]}, {"replaced": "ab"}, {"domain": "a b"}, {"domain": 5}, {"body": 5}, {"extra": 1}):
            base = dict(self.raw["base"], **change)
            with self.subTest(change=sorted(change)):
                error = error_of(self.read, dict(self.raw, base=base))
                self.assertEqual(error.code, "DRAFT_CORRUPT")
                self.assertNotIn("만든 본문", error.rendered().message + error.rendered().action + error.detail)

    def test_a_record_over_the_limits_is_read_as_corrupt_not_as_a_limit_message(self):
        self.assertEqual(error_of(self.read, dict(self.raw, title="x" * (sd.MAX_TITLE_CHARS + 1))).code, "DRAFT_CORRUPT")
        self.assertEqual(error_of(self.read, dict(self.raw, body="x" * (sd.MAX_BODY_CHARS + 1))).code, "DRAFT_CORRUPT")

    def test_the_corrupt_error_never_carries_the_stored_text(self):
        key = SS.google()
        raw = dict(self.raw, body="본문 " + key, summary=5)
        error = error_of(self.read, raw)
        shown = error.rendered().message + error.rendered().action + error.detail + repr(error) + str(error)
        self.assertFalse(SS.leaked(shown, key))


class LimitTest(unittest.TestCase):
    def test_each_limit_accepts_the_largest_value_and_refuses_one_more_without_cutting(self):
        cases = (("title", sd.MAX_TITLE_CHARS, "x"), ("body", sd.MAX_BODY_CHARS, "x"), ("summary", sd.MAX_SHORT_CHARS, "x"), ("category", sd.MAX_SHORT_CHARS, "x"), ("topic", sd.MAX_SHORT_CHARS, "x"))
        for name, limit, char in cases:
            with self.subTest(field=name):
                self.assertEqual(getattr(make(**{name: char * limit}), name), char * limit)
                error = error_of(make, **{name: char * (limit + 1)})
                self.assertEqual(error.code, "DRAFT_LIMIT")
                self.assertIn("넘어요", error.rendered().message)

    def test_lists_and_their_items_have_limits(self):
        for name in ("core_keywords", "sub_keywords", "tags"):
            with self.subTest(field=name):
                self.assertEqual(len(getattr(make(**{name: ("가",) * sd.MAX_LIST_ITEMS}), name)), sd.MAX_LIST_ITEMS)
                self.assertEqual(error_of(make, **{name: ("가",) * (sd.MAX_LIST_ITEMS + 1)}).code, "DRAFT_LIMIT")
                self.assertEqual(getattr(make(**{name: ("가" * sd.MAX_ITEM_CHARS,)}), name)[0], "가" * sd.MAX_ITEM_CHARS)
                self.assertEqual(error_of(make, **{name: ("가" * (sd.MAX_ITEM_CHARS + 1),)}).code, "DRAFT_LIMIT")

    def test_a_limit_message_names_the_place_and_never_uses_a_particle_that_was_not_chosen(self):
        """예전 문구는 '핵심 키워드이(가) 200자를 넘어요' 처럼 조사를 고르지 못한 채 나갔다 — 칸 이름 뒤에 '칸이'·'칸의 항목이'·'칸의 항목 하나가' 로 받침을 가리지 않게 쓴다(D-371)."""
        reasons = []
        for name, limit in (("title", sd.MAX_TITLE_CHARS), ("body", sd.MAX_BODY_CHARS), ("summary", sd.MAX_SHORT_CHARS), ("category", sd.MAX_SHORT_CHARS), ("topic", sd.MAX_SHORT_CHARS)):
            reason = error_of(make, **{name: "x" * (limit + 1)}).slots["이유"]
            self.assertEqual(reason, f"{sd.LABELS[name]} 칸이 {limit:,}자를 넘어요")
            reasons.append(reason)
        for name in ("core_keywords", "sub_keywords", "tags"):
            many = error_of(make, **{name: ("가",) * (sd.MAX_LIST_ITEMS + 1)}).slots["이유"]
            long = error_of(make, **{name: ("가" * (sd.MAX_ITEM_CHARS + 1),)}).slots["이유"]
            self.assertEqual(many, f"{sd.LABELS[name]} 칸의 항목이 {sd.MAX_LIST_ITEMS}개를 넘어요")
            self.assertEqual(long, f"{sd.LABELS[name]} 칸의 항목 하나가 {sd.MAX_ITEM_CHARS}자를 넘어요")
            reasons += [many, long]
        reasons.append(error_of(make, options={"message": "가" * (sd.MAX_SHORT_CHARS + 1)}).slots["이유"])
        reasons.append(error_of(sd.BaseDraft.build, "t", ["t"], "x" * (sd.MAX_BASE_BODY_CHARS + 1), [], "generic", None).slots["이유"])
        reasons.append(error_of(sd.BaseDraft.build, "t", ["t"], "x", ["c"] * (sd.MAX_CHECKS + 1), "generic", None).slots["이유"])
        reasons.append(error_of(sd.BaseDraft.build, "t", ["t"], "x", ["c" * (sd.MAX_CHECK_CHARS + 1)], "generic", None).slots["이유"])
        for reason in reasons:
            for particle in ("이(가)", "은(는)", "을(를)", "와(과)", "으로(로)", "(이)", "(을)"):
                self.assertNotIn(particle, reason)
            self.assertIn("넘어요", reason)

    def test_an_option_value_has_a_limit(self):
        self.assertEqual(make(options={"message": "가" * sd.MAX_SHORT_CHARS}).options_dict()["message"], "가" * sd.MAX_SHORT_CHARS)
        self.assertEqual(error_of(make, options={"message": "가" * (sd.MAX_SHORT_CHARS + 1)}).code, "DRAFT_LIMIT")

    def test_the_base_has_its_own_limits(self):
        sd.BaseDraft.build("t", ["t"], "x" * sd.MAX_BASE_BODY_CHARS, ["c"] * sd.MAX_CHECKS, "generic", None)
        self.assertEqual(error_of(sd.BaseDraft.build, "t", ["t"], "x" * (sd.MAX_BASE_BODY_CHARS + 1), [], "generic", None).code, "DRAFT_LIMIT")
        self.assertEqual(error_of(sd.BaseDraft.build, "t", ["t"], "x", ["c"] * (sd.MAX_CHECKS + 1), "generic", None).code, "DRAFT_LIMIT")
        self.assertEqual(error_of(sd.BaseDraft.build, "t", ["t"], "x", ["c" * (sd.MAX_CHECK_CHARS + 1)], "generic", None).code, "DRAFT_LIMIT")

    def test_a_record_too_big_for_one_storage_cell_after_escaping_is_a_limit_not_a_cut(self):
        base = sd.BaseDraft.build("t", ["t"], EMOJI * sd.MAX_BASE_BODY_CHARS, [], "generic", None)
        draft = make(body=EMOJI * sd.MAX_BODY_CHARS, base=base)
        error = error_of(draft.to_text)
        self.assertEqual(error.code, "DRAFT_LIMIT")
        self.assertEqual(len(make(body=EMOJI * sd.MAX_BODY_CHARS).to_text()) < sd.MAX_TEXT_CHARS, True)

    def test_the_cell_size_is_the_stores_own_limit(self):
        self.assertEqual(sd.MAX_TEXT_CHARS, content_store.MAX_DRAFT_CHARS)

    def test_a_wrong_kind_of_value_is_a_content_error_not_a_limit(self):
        for name, value in (("title", 5), ("body", None), ("summary", b"x"), ("tags", "가나다"), ("core_keywords", None), ("options", ["x"]), ("options", {"nope": "x"}), ("blog", "naver_c"), ("candidate_id", "a b"),
                            ("post_type", "없는 유형"), ("post_type_choice", "없는 유형")):
            with self.subTest(field=name):
                self.assertEqual(error_of(make, **{name: value}).code, "CONTENT_INVALID")

    def test_a_bad_id_stamp_or_count_is_a_content_error(self):
        self.assertEqual(error_of(make, draft_id="x").code, "CONTENT_INVALID")
        self.assertEqual(error_of(make, created_at="2026-11-11").code, "CONTENT_INVALID")
        self.assertEqual(error_of(make, updated_at=5).code, "CONTENT_INVALID")
        self.assertEqual(error_of(make, revision=0).code, "CONTENT_INVALID")
        self.assertEqual(error_of(make, revision=True).code, "CONTENT_INVALID")
        self.assertEqual(error_of(make, generator="").code, "CONTENT_INVALID")

    def test_the_post_type_choice_may_be_none_and_the_used_one_may_be_empty_but_not_the_other_way(self):
        self.assertIsNone(make(post_type_choice=None).post_type_choice)
        self.assertEqual(make(post_type="").post_type, "")
        self.assertEqual(error_of(make, post_type_choice="").code, "CONTENT_INVALID")
        self.assertEqual(error_of(make, post_type=None).code, "CONTENT_INVALID")


class PinnedValuesTest(unittest.TestCase):
    """이 묶음이 정한 값은 시험이 숫자로 못박는다(바꾸려면 결정 기록(D-360)과 함께 이 시험을 고친다)."""

    def test_the_limits_are_the_decided_numbers(self):
        self.assertEqual((sd.MAX_TITLE_CHARS, sd.MAX_BODY_CHARS, sd.MAX_BASE_BODY_CHARS, sd.MAX_SHORT_CHARS, sd.MAX_ITEM_CHARS), (1_000, 150_000, 30_000, 2_000, 200))
        self.assertEqual((sd.MAX_LIST_ITEMS, sd.MAX_CHECKS, sd.MAX_CHECK_CHARS, sd.MAX_SAVED, sd.MAX_TEXT_CHARS), (50, 50, 1_000, 300, 2_000_000))

    def test_the_record_identity_constants_are_the_decided_ones(self):
        self.assertEqual((sd.SCHEMA, sd.KIND, sd.ID_PREFIX, sd.GENERATOR, sd.SHORT_ID), (1, "desktop_draft", "dd-", "rule-v1", 11))
        self.assertEqual(sd.BLOGS, ("naver_a", "naver_b"))
        self.assertEqual(sd.MADE_DRAFT_HEAD, sd.LABELS["base"])

    def test_the_record_has_exactly_these_fields_in_the_stored_text(self):
        raw = json.loads(make(base=sample_base()).to_text())
        self.assertEqual(sorted(raw), sorted(["schema", "kind", "draft_id", "revision", "created_at", "updated_at", "generator", "candidate_id", "topic", "blog", "post_type_choice", "post_type", "title", "body",
                                              "core_keywords", "sub_keywords", "tags", "category", "summary", "options", "base"]))
        self.assertEqual(sorted(raw["base"]), sorted(["title", "titles", "body", "checks", "domain", "replaced"]))


class SecretAdviceTest(unittest.TestCase):
    """키·토큰 모양을 찾았을 때의 안내(`secret_advice`) — 위치와 종류와 고치는 법뿐이고 찾은 글은 없다. 만든 초안 칸에서 찾았으면 전용 문구(후보·블로그 프로필·선택 입력을 고쳐 다시 만들기·먼저 복사)."""

    def findings(self, kind, **place):
        token, line = SS.sample(kind)
        return token, tuple(scan.scan_fields({name: "앞 줄\n" + line for name in place.values()}))

    def test_a_made_draft_place_is_the_one_that_starts_with_the_made_draft_name(self):
        self.assertEqual(sd.MADE_DRAFT_HEAD, "만든 초안")
        for where in ("만든 초안 본문", "만든 초안 제목 후보", "만든 초안 분야", "만든 초안 확인 권장", "만든 초안 바꾼 형식", "만든 초안 제목"):
            self.assertTrue(sd.is_made_draft_place(where), where)
        for where in ("본문", "제목", "후보 번호", "선택 입력(실제 사용 경험)", "", None, 5):
            self.assertFalse(sd.is_made_draft_place(where), where)

    def test_an_edited_field_gets_the_old_advice_exactly(self):
        token, found = self.findings("github_token", a="본문")
        self.assertEqual(sd.secret_advice(found), scan.summarize(found, "저장"))
        self.assertNotIn(sd.MADE_DRAFT_ADVICE, sd.secret_advice(found))

    def test_a_made_draft_field_gets_the_place_and_the_special_sentence_and_not_the_edit_this_line_advice(self):
        token, found = self.findings("google_api_key", a="만든 초안 본문")
        advice = sd.secret_advice(found)
        self.assertIn("만든 초안 본문에서 1건(Google API 키 1) — 2번째 줄", advice)
        self.assertTrue(advice.endswith(sd.MADE_DRAFT_ADVICE))
        self.assertNotIn("해당 줄을 만든 초안 본문에서 지운 뒤", advice, "화면에서 못 고치는 칸이라 '그 줄을 지우라' 는 말은 맞지 않는다")
        self.assertIn("블로그 프로필", sd.MADE_DRAFT_ADVICE)
        self.assertIn("선택 입력", sd.MADE_DRAFT_ADVICE)
        self.assertIn("다시 만들기", sd.MADE_DRAFT_ADVICE)
        self.assertIn("먼저 복사", sd.MADE_DRAFT_ADVICE)
        self.assertIn("자동으로 지우거나 바꾸지 않아요", advice)
        self.assertFalse(SS.leaked(advice, token))

    def test_both_kinds_of_place_are_told_each_in_its_own_way(self):
        token, found = self.findings("aws_access_key", a="본문", b="만든 초안 제목 후보")
        advice = sd.secret_advice(found)
        self.assertIn("본문에서 1건(AWS 액세스 키 1) — 2번째 줄", advice)
        self.assertIn("해당 줄을 본문에서 지운 뒤 다시 저장해 주세요", advice)
        self.assertIn("만든 초안 제목 후보에서 1건(AWS 액세스 키 1) — 2번째 줄", advice)
        self.assertEqual(advice.count(sd.MADE_DRAFT_ADVICE), 1)
        self.assertFalse(SS.leaked(advice, token))

    def test_nothing_found_means_nothing_to_say(self):
        self.assertEqual(sd.secret_advice(()), "")


class ScanFieldsTest(unittest.TestCase):
    def test_every_edited_text_field_is_offered_to_the_scanner_with_a_short_korean_name(self):
        draft = make(title="T", body="B", core_keywords=("k1", "k2"), sub_keywords=("s1",), tags=("t1", "t2", "t3"), category="C", summary="S", topic="P", options={"message": "M", "urls": "U"})
        fields = draft.text_fields()
        self.assertEqual(fields["제목"], "T")
        self.assertEqual(fields["본문"], "B")
        self.assertEqual(fields["핵심 키워드"], "k1\nk2")
        self.assertEqual(fields["보조 키워드"], "s1")
        self.assertEqual(fields["태그"], "t1\nt2\nt3")
        self.assertEqual(fields["카테고리"], "C")
        self.assertEqual(fields["요약"], "S")
        self.assertEqual(fields["후보 주제"], "P")
        self.assertEqual(fields["후보 번호"], "cand-1", "후보 번호 칸도 훑는다(서비스를 직접 부르면 키 모양이 들어갈 수 있는 칸 — D-368)")
        option_names = [name for name in fields if name.startswith("선택 입력")]
        self.assertEqual(len(option_names), 2)
        for name in fields:
            self.assertTrue(name.isprintable() and len(name) <= 80, name)
        self.assertEqual(len(fields), 11)

    def test_the_option_names_are_the_korean_labels_of_the_service(self):
        draft = make(options={"experience": "E"})
        self.assertEqual(list(draft.text_fields())[-1], "선택 입력(" + do.LABELS["experience"] + ")")

    def test_the_base_fields_are_separate_and_none_without_a_base(self):
        self.assertEqual(make().base_fields(), {})
        fields = make(base=sample_base()).base_fields()
        self.assertEqual(len(fields), 6)
        self.assertIn("만든 초안 본문", fields)
        self.assertEqual(fields["만든 초안 분야"], "generic", "분야 칸도 훑는다(이름만 받는 칸이지만 40자까지 키 모양이 들어갈 수 있다 — D-368)")
        self.assertEqual(fields["만든 초안 제목 후보"], "만든 제목\n후보 둘\n후보 셋")
        self.assertEqual(make(base=sd.BaseDraft.build("t", [], "b", [], "generic", None)).base_fields().keys() & {"만든 초안 바꾼 형식"}, set())

    def test_the_option_keys_are_the_input_fields_the_generator_knows(self):
        self.assertEqual(sd.OPTION_KEYS, do.KEYS)
        self.assertEqual(sd.BLOGS, ("naver_a", "naver_b"))

    def test_body_chars_counts_without_spaces_and_line_breaks(self):
        self.assertEqual(sd.body_chars("가 나\n다\r\n 라\t마"), 5)
        self.assertEqual(sd.body_chars(""), 0)


class SourceRulesTest(unittest.TestCase):
    def test_the_record_module_imports_no_file_clock_random_or_network_module(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add((node.module or "").split(".")[0])
        self.assertFalse(names & {"os", "sys", "time", "datetime", "random", "secrets", "uuid", "socket", "subprocess", "pathlib", "sqlite3", "urllib", "http", "shutil", "tempfile", "webbrowser", "ctypes"}, names)

    def test_the_module_calls_no_clock_or_file_function(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        for name in calls:
            self.assertFalse(any(word in name for word in ("open", "now", "time", "random", "uuid", "write", "read_text", "mkdir", "unlink")), name)

    def test_no_english_secret_word_is_written_in_a_string_of_the_module(self):
        import re
        words = re.compile(r"(?i)(?<![A-Za-z0-9_])(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?(?![A-Za-z0-9_])")
        for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertIsNone(words.search(node.value), node.value[:40])


if __name__ == "__main__":
    unittest.main()
