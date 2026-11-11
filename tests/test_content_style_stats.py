"""'내 글 문체 참고값'(N-3a)의 순수 계산(`content/style_stats.py`, 결정 D-330–D-339) 시험 — 표준 라이브러리만 쓰고 파일·창·네트워크가 없다(CI 에서 그대로 돈다).

지키는 것:
  1) 운영자가 정한 값 — 최대 10만 자·짧은 글(문장 10개 미만·600자 미만)·한글 50%·줄바꿈 습관 30%·글 둘의 차이 기준 넷(40%·3·2배·15%p)의 상수와 경계.
  2) 손으로 정답을 정한 예문 표 — 문장 나누기 경계·문장 끝 네 부류·질문·목록·소제목·전처리(머리말·코드·표·인용·그림·링크·표시·장식·해시태그·보이지 않는 글자·줄 끝)를 형식(md·txt·붙여 넣은 글)마다.
  3) 줄바꿈 습관 불변성 — 같은 글을 줄바꿈만 다르게 해도(문단마다 한 줄·여러 칸 억지 줄바꿈·한 문장 한 줄) 값이 같다. 옛 방식(줄마다 문장 경계)이 얼마나 흔들리는지도 함께 못박는다.
  4) 값에는 글이 없다 — 모든 칸이 숫자·참/거짓·None(타입 시험), 고유 표지 글이 값·`repr`·오류에 8글자 이상 남지 않는다.
  5) 글 둘의 합산(문장·문단을 모아 계산 — 평균의 평균이 아님)·범위·차이 기준 경계·`알 수 없음`(None) 과 0 의 구별.
  6) 소스 규칙 — 표준 라이브러리와 N-2 의 보이지 않는 글자 목록만 가져오고 파일·네트워크·시계·무작위·프로필·설정·보관함이 없다.
  7) n3afix(독립 검증 낮은 지적 수정, D-430–D-439) — 짧은 문장을 억지 줄바꿈한 글은 문장 수가 틀리면 줄바꿈 안내가 켜진다·`…나요`·`…ㄴ가요` 는 물음표가 있을 때만 질문·`…아니다` 는 평서·`Q.`/`A.` 라벨은 문장이 아니다·
     고치지 않은 한계는 문서가 말한 오차 그대로 숫자에 나타난다.
소스·시험에는 물결 글자와 웹 주소를 날것으로 쓰지 않는다(글자는 코드 숫자로, 주소 머리는 조각으로).
"""
import ast
import dataclasses
import re
import sys
import textwrap
import unicodedata
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.check import claims, garbage  # noqa: E402
from chanceblog_desktop.content import style_stats as S  # noqa: E402
from chanceblog_desktop.service import own_posts  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "content" / "style_stats.py"
FIXTURE = ROOT / "tests" / "fixtures" / "chance_post_ko.md"
TILDE = chr(0x7E)                                  # 물결 글자는 시험 글에도 직접 쓰지 않는다
SCHEME = "https" + "://"                           # 웹 주소 머리는 조각으로 잇는다
LS, PS = chr(0x2028), chr(0x2029)
FORMS = ("md", "txt", "pasted")
KEYS = ("sentences", "chars", "paragraphs", "list_blocks", "headings", "end_formal", "end_polite", "end_plain", "end_other", "questions", "casual_ends", "quote_chars", "joined_sentences", "lined_sentences", "line_mode")


def run(text, form="txt"):
    return S.analyze(text, form)


def pick(stats, *names):
    return {name: getattr(stats, name) for name in names}


def values(stats):
    """줄바꿈 습관이 달라져도 같아야 하는 값들(진단 칸 — 두 방식의 문장 수·줄바꿈 판정 — 은 빼고)."""
    return (stats.sentences, stats.chars, stats.paragraphs, stats.list_blocks, stats.end_formal, stats.end_polite, stats.end_plain, stats.end_other, stats.questions, stats.letters, stats.hangul, stats.casual_ends, stats.quote_chars)


def sentence_of(length, mark="."):
    """공백 뺀 글자가 `length` 인 한 문장(끝 부호 하나 포함)."""
    return "가" * (length - 1) + mark


# ---- 1) 운영자가 정한 값 ---------------------------------------------------------------------------------------------------------
class ConstantsTest(unittest.TestCase):
    def test_the_limits_and_thresholds_are_the_values_the_operator_confirmed(self):
        self.assertEqual(S.MAX_CHARS, 100_000)
        self.assertEqual(S.MAX_CHARS, own_posts.MAX_TEXT_CHARS, "읽기 기반의 글 길이 상한과 같은 값이다")
        self.assertEqual((S.MIN_SENTENCES, S.MIN_CHARS), (10, 600))
        self.assertEqual(S.LOW_HANGUL_PERCENT, 50)
        self.assertEqual(S.WRAP_GAP_PERCENT, 30)
        self.assertEqual(S.NFC_CHUNK, 512)                                              # 정규화를 부르는 조각 크기(N-2 의 조각과 같은 값 — 너무 작으면 앞으로 가지 못하고 너무 크면 병적 입력에서 제곱 시간이다)
        self.assertEqual((S.DIFF_SENTENCE_LENGTH, S.DIFF_HEADINGS, S.DIFF_PER_PARAGRAPH, S.DIFF_QUESTION), (Fraction(7, 5), 3, Fraction(2), Fraction(3, 20)))

    def test_the_forms_the_metrics_and_the_notice_keys_are_fixed_lists(self):
        self.assertEqual(S.FORMS, FORMS)
        self.assertEqual(len(S.METRICS), 9)
        self.assertEqual(len(set(S.METRICS)), 9)
        self.assertEqual(S.NOTICES, ("empty", "short", "quote", "low_hangul", "casual", "wrap"))

    def test_an_unknown_form_or_a_non_string_or_a_too_long_text_is_refused_with_a_fixed_sentence(self):
        marker = "고유표지-zq7k3j9x-본문"
        for args in (("가나다입니다.", "html"), (None, "md"), (b"abc", "txt"), (marker * 20000, "md"), ("가" * (S.MAX_CHARS + 1), "txt")):
            with self.subTest(form=args[1], kind=type(args[0]).__name__):
                with self.assertRaises(ValueError) as caught:
                    S.analyze(*args)
                self.assertNotIn("고유표지", str(caught.exception))
                self.assertNotIn("가가가", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)

    def test_exactly_the_limit_is_accepted(self):
        stats = S.analyze(("가나다입니다. " * 20000)[:S.MAX_CHARS], "md")
        self.assertGreater(stats.sentences, 1000)


# ---- 2) 값의 모양 ----------------------------------------------------------------------------------------------------------------
class ShapeTest(unittest.TestCase):
    def test_every_field_is_a_number_a_truth_value_or_none_and_the_annotations_say_so(self):
        for item in dataclasses.fields(S.StyleStats):
            self.assertIn(item.type, ("int", "int | None", "bool"), item.name)
        sample = run("저는 오늘 시장에 갔습니다. 정말요? 좋았죠.", "md")
        for item in dataclasses.fields(sample):
            self.assertIsInstance(getattr(sample, item.name), (int, bool, type(None)), item.name)
        self.assertEqual(len([item for item in dataclasses.fields(sample) if item.type == "bool"]), 1)

    def test_the_value_is_frozen(self):
        stats = run("가나다입니다.")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            stats.sentences = 5
        with self.assertRaises(dataclasses.FrozenInstanceError):
            stats.headings = 1

    def test_a_value_with_a_text_a_negative_a_float_or_a_boolean_in_a_number_field_cannot_be_built(self):
        good = dataclasses.asdict(run("가나다입니다."))
        for name, bad in (("sentences", "가나다"), ("chars", -1), ("paragraphs", 1.5), ("list_blocks", True), ("headings", "3"), ("headings", -2), ("line_mode", 1), ("end_formal", None), ("questions", b"x")):
            with self.subTest(field=name, bad=repr(bad)[:12]):
                with self.assertRaises(ValueError):
                    S.StyleStats(**{**good, name: bad})
        S.StyleStats(**{**good, "headings": None})
        S.StyleStats(**{**good, "headings": 0})

    def test_the_summary_holds_only_numbers_truth_values_and_the_per_text_values(self):
        summary = S.summarize([run("가나다입니다."), run("라마바입니다.")])
        self.assertIsInstance(summary.items, tuple)
        self.assertIsInstance(summary.pooled, S.StyleStats)
        self.assertEqual(len(summary.differs), 4)
        self.assertTrue(all(isinstance(flag, bool) for flag in summary.differs))
        self.assertIsInstance(summary.range_only, bool)
        self.assertEqual({item.name for item in dataclasses.fields(S.StyleSummary)}, {"items", "pooled", "differs"})

    def test_the_text_never_appears_in_the_value_its_repr_or_its_notices(self):
        marker = "고유표지문장zq7k3j9x본문"
        text = f"{marker}입니다. 이 문장은 UNIQUEMARK-r4t6y8-body 를 담고 있습니다.\n\n> 인용 {marker}\n\n- {marker} 목록\n\n## {marker} 제목"
        for form in FORMS:
            stats = run(text, form)
            haystack = repr(stats) + str(stats) + repr(dataclasses.astuple(stats)) + repr(stats.notices()) + repr(S.summarize([stats]))
            for piece in (marker, marker[:8], "UNIQUEMARK", "r4t6y8"):
                self.assertNotIn(piece, haystack, (form, piece))


# ---- 3) 문장 나누기 ---------------------------------------------------------------------------------------------------------------
SPLIT_TABLE = (
    # (글, 문장 수, 공백 뺀 글자 합)
    ("안녕하세요. 반갑습니다.", 2, 12),
    ("가격은 3.5배입니다. 좋습니다.", 2, 16),                         # 소수점은 자르지 않는다
    ("정말요? 좋아요! 그렇죠.", 3, 12),
    ("그랬나… 모르겠어요.", 2, 10),                                    # 말줄임표 뒤 공백
    ('그는 "갑니다." 라고 했어요.', 2, 14),                             # 닫는 따옴표가 붙은 끝 부호
    ("끝나는 말이 없어요", 1, 8),                                       # 끝 부호가 없어도 한 문장
    ("가나다.라마바.", 1, 8),                                          # 끝 부호 뒤에 공백이 없으면 자르지 않는다
    ("뭐라고?! 정말요?!", 2, 10),                                       # 끝 부호 묶음은 하나
    ("좋아요. ...", 1, 4),                                             # 글자가 없는 조각은 버린다
    ("This is fine. It works.", 2, 19),
    ("Dr. Kim 은 의사예요.", 2, 12),                                    # 알려 둔 한계: 약어의 마침표도 자른다
    ("첫째。 둘째！ 셋째？", 3, 9),                                      # 전각 끝 부호
    ("문장입니다.)  다음 문장입니다.", 2, 15),
    ("가나다 ... 라마바", 2, 9),                                        # 알려 둔 한계: 문장 가운데 말줄임표 뒤 공백도 자른다
    (chr(0x201C) + "안녕하세요." + chr(0x201D) + " 라고 말했습니다.", 2, 16),
    ("", 0, 0),
    ("   \n\n  ", 0, 0),
)


class SplitTest(unittest.TestCase):
    def test_the_hand_labeled_sentence_boundaries_hold_in_every_form(self):
        for form in FORMS:
            for text, sentences, chars in SPLIT_TABLE:
                with self.subTest(form=form, text=text[:24]):
                    stats = run(text, form)
                    self.assertEqual((stats.sentences, stats.chars), (sentences, chars))

    def test_the_boundary_rule_is_the_one_of_the_claim_check_when_there_is_one_line(self):
        """`check/claims.split_sentences` 와 같은 규칙 — 한 줄짜리 글에서는 두 나누기가 같은 수를 낸다(글자·숫자가 없는 조각만 우리가 더 버린다)."""
        for text, sentences, _chars in SPLIT_TABLE:
            if text.strip() and "..." not in text:
                with self.subTest(text=text[:24]):
                    self.assertEqual(len(claims.split_sentences(text)), sentences)

    def test_a_text_with_nothing_to_count_is_unknown_not_zero(self):
        stats = run("")
        self.assertTrue(stats.no_sentences)
        self.assertEqual(stats.notices(), ("empty",))
        for metric in ("sentence_length", "per_paragraph", "end_formal", "end_polite", "end_plain", "end_other", "question"):
            self.assertIsNone(S.value(stats, metric), metric)
        self.assertIsNone(stats.end_shares)
        self.assertIsNone(stats.list_share)
        self.assertEqual(S.value(run("가나다입니다."), "question"), Fraction(0))        # 0 은 센 결과이고 None 은 알 수 없음이다


LABEL_TABLE = (
    # (글, 문장 수, 공백 뺀 글자 합) — 영문 글자 하나와 끝 부호뿐인 조각(`Q.`·`A.` 라벨)은 문장이 아니다(D-433). 한글 한 글자(`네.`)는 문장이다
    ("Q. 사용법이 어렵나요? A. 아니요, 쉬워요.", 2, 17),
    ("Q. 질문입니까?\nA. 답입니다.", 2, 11),
    ("네. 알겠어요.", 2, 7),
    ("I. 첫째입니다.", 1, 6),
    ("Plan B. 다음입니다.", 2, 12),                                    # 글자가 둘 이상이면 라벨이 아니다
    ("A) 첫째입니다.", 1, 8),                                          # 끝 부호가 아닌 `)` 는 조각을 가르지 않는다
    ("**Q.** 어렵나요?", 1, 5),
)


class LabelTest(unittest.TestCase):
    def test_a_piece_of_one_latin_letter_and_a_stop_is_a_label_and_not_a_sentence_in_every_form(self):
        for form in FORMS:
            for text, sentences, chars in LABEL_TABLE:
                with self.subTest(form=form, text=text[:24]):
                    stats = run(text, form)
                    self.assertEqual((stats.sentences, stats.chars), (sentences, chars))

    def test_the_label_check_is_for_one_latin_letter_in_a_short_piece_only(self):
        for piece in ("Q.", "a.", "A..", "Z!", "Q", "Q" + "." * 7):
            self.assertTrue(S._label_only(piece), piece)
        for piece in ("네.", "1.", "AB.", "가나다입니다.", "A. B.", ".", "Q" + "." * 8):
            self.assertFalse(S._label_only(piece), piece)


# ---- 4) 문장 끝·질문 --------------------------------------------------------------------------------------------------------------
ENDING_TABLE = (
    # (문장, 끝 부류 0 …니다/…니까/…십시오 · 1 …요/…죠 · 2 …다 · 3 그 밖, 질문, 이모지 같은 끝)
    ("저는 갑니다.", 0, 0, 0), ("가십시오.", 0, 0, 0), ("가시겠습니까?", 0, 1, 0), ("합니까", 0, 1, 0), ("됩니다)", 0, 0, 0),
    ("좋아요.", 1, 0, 0), ("그렇죠.", 1, 0, 0), ("정말요?!", 1, 1, 0), ("학교에 가요", 1, 0, 0),
    ("갔다.", 2, 0, 0), ("대단하다!", 2, 0, 0), ("그것이다.", 2, 0, 0),
    ("끝남.", 3, 0, 0), ("합니다만.", 3, 0, 0), ("It works.", 3, 0, 0),
    ("좋아요ㅎㅎ", 3, 0, 1), ("좋아요 😊", 3, 0, 1), ("좋아요^^", 3, 0, 1), ("재밌네ㅋㅋㅋ.", 3, 0, 1),
    ("감사합니다" + TILDE, 0, 0, 0), ("감사해요" + TILDE + TILDE, 1, 0, 0),                  # 물결은 문장 끝 부호처럼 떼고 본다
    ('"갑니다."', 0, 0, 0), ("(웃음)", 3, 0, 0),
    ("정말 그런가요", 1, 0, 0), ("할까요", 1, 1, 0), ("있나요", 1, 0, 0), ("괜찮은가요", 1, 0, 0), ("충분한가요", 1, 0, 0), ("인가요", 1, 0, 0),         # D-431: `…나요`·`…ㄴ가요` 는 물음표가 있을 때만 질문(옛 단언은 물음표 없이도 질문 1) — `…까요` 는 그대로
    ("정말 그런가요?", 1, 1, 0), ("있나요?", 1, 1, 0), ("괜찮은가요?", 1, 1, 0), ("충분한가요?", 1, 1, 0), ("인가요?", 1, 1, 0), ("만나요?", 1, 1, 0),   # 같은 끝말도 물음표가 있으면 질문이다
    ("만나요", 1, 0, 0), ("생각나요", 1, 0, 0), ("기억나요", 1, 0, 0), ("화가 나요", 1, 0, 0), ("냄새가 나요", 1, 0, 0), ("안가요", 1, 0, 0),             # 평서문(독립 검증 D2) — 질문으로 세지 않는다
    ("이것은 우연이 아니다.", 2, 0, 0), ("아니다", 2, 0, 0), ("아닙니다.", 0, 0, 0), ("아니겠습니까?", 0, 1, 0),                                    # D-433: `…아니다` 는 `…니다` 로 끝나도 평서(합쇼는 `…ㅂ니다`·`…습니다`)
    ("뭐지?", 3, 1, 0), ("뭐지" + chr(0xFF1F), 3, 1, 0), ("그렇죠?", 1, 1, 0), ("그렇죠", 1, 0, 0), ("좋다", 2, 0, 0),
    ("가요", 1, 0, 0), ("은가요", 1, 0, 0), ("은가요?", 1, 1, 0),                                  # 물음표가 없으면 `…ㄴ가요` 도 질문이 아니다(D-431) — 글자가 둘뿐인 글도 안전하게
    ("필요.", 1, 0, 0),                                                                      # 알려 둔 한계: 명사 '필요' 도 겉모양이 '…요' 라 해요 부류다
)


class EndingTest(unittest.TestCase):
    def test_the_hand_labeled_endings_questions_and_light_endings_hold_in_every_form(self):
        for form in FORMS:
            for sentence, kind, asked, light in ENDING_TABLE:
                with self.subTest(form=form, sentence=sentence):
                    stats = run(sentence, form)
                    self.assertEqual(stats.sentences, 1)
                    counts = (stats.end_formal, stats.end_polite, stats.end_plain, stats.end_other)
                    self.assertEqual(counts, tuple(int(index == kind) for index in range(4)))
                    self.assertEqual((stats.questions, stats.casual_ends), (asked, light))

    def test_the_four_shares_add_up_to_one_and_the_question_share_is_a_share_of_the_sentences(self):
        stats = run("저는 갑니다. 좋아요. 갔다. 끝남. 정말요? 합니까?")
        shares = stats.end_shares
        self.assertEqual(sum(shares), Fraction(1))
        self.assertEqual(shares, (Fraction(2, 6), Fraction(2, 6), Fraction(1, 6), Fraction(1, 6)))
        self.assertEqual(stats.question_share, Fraction(2, 6))

    def test_the_formal_ending_is_taken_before_the_yo_and_plain_endings(self):
        """'…니다' 는 '다' 로도 끝나지만 합쇼 부류가 먼저다 — 평서 부류는 앞의 부류를 뺀 '…다' 만 센다."""
        stats = run("갑니다. 갔다.")
        self.assertEqual((stats.end_formal, stats.end_plain), (1, 1))

    def test_a_nayo_or_n_gayo_ending_is_a_question_only_with_a_question_mark_while_nikka_and_kkayo_still_are_without_one(self):
        """D-431 — `…나요`·`…ㄴ가요` 는 평서문(만나요·생각나요·안 가요)이 흔해서 물음표가 있을 때만 질문이다. `…니까`·`…까요` 는 물음표 없이도 질문(옛 단언 그대로)."""
        statements = "내일 친구를 만나요. 꽃 냄새가 나요. 그 장면이 기억나요. 문득 생각나요. 오늘은 안가요. 가끔 화가 나요."
        for form in FORMS:
            with self.subTest(form=form):
                self.assertEqual(run(statements, form).questions, 0)
                self.assertEqual(run(statements.replace(".", "?"), form).questions, 6, "같은 문장도 물음표가 있으면 질문이다")
                self.assertEqual(run("어떻게 하십니까. 같이 갈까요. 정말 괜찮나요. 이게 맞는가요.", form).questions, 2, "…니까·…까요 둘만 물음표 없이도 질문이다")
                self.assertEqual(run(statements, form).end_shares, (Fraction(0), Fraction(1), Fraction(0), Fraction(0)), "끝 부류는 그대로 해요 부류")

    def test_a_plain_anida_is_a_plain_ending_even_though_it_ends_with_nida(self):
        """D-433 — `이것은 우연이 아니다.` 는 합쇼(…니다)가 아니라 평서(…다)다. `…입니다`·`…아닙니다` 는 그대로 합쇼."""
        for form in FORMS:
            stats = run("이것은 우연이 아니다. 그건 아닙니다. 이것은 책입니다. 아니다.", form)
            self.assertEqual((stats.end_formal, stats.end_plain), (2, 2), form)


# ---- 5) 목록·소제목·문단 ----------------------------------------------------------------------------------------------------------
LIST_TABLE = (
    # (글, 형식, 목록 덩어리, 산문 문단)
    ("- a\n- b\n- c", "md", 1, 0), ("- a\n\n- b", "md", 1, 0), ("- a\n  이어지는 글\n- b", "md", 1, 0), ("1. a\n2. b", "md", 1, 0), ("1) a", "md", 1, 0), ("* a", "md", 1, 0), ("+ a", "md", 1, 0),
    ("• a", "md", 1, 0), ("① a", "md", 1, 0), (chr(0x318D) + "a 는 목록 아님입니다.", "md", 0, 1), ("-5도입니다.", "md", 0, 1), ("1.5배입니다.", "md", 0, 1), ("**굵게** 입니다.", "md", 0, 1),
    ("문단입니다.\n\n- a\n- b\n\n다음 문단입니다.", "md", 1, 2), ("- a\n문단입니다.\n- b", "md", 2, 1), ("문장입니다.\n- 항목\n이어서 문장입니다.", "md", 1, 2),
    ("- a\n- b", "txt", 1, 0), ("- a\n- b", "pasted", 1, 0), ("문단입니다.\n- a", "txt", 1, 1),
    ("100. a", "md", 1, 0), ("1000. a 입니다.", "md", 0, 1), ("- a\n\t이어지는 글\n- b", "md", 1, 0), ("- a\n문단입니다.", "txt", 1, 1),
)
HEADING_TABLE = (
    ("# 제목\n\n## 소제목1\n\n본문입니다.\n\n### 소제목2", 2),                  # 글 맨 앞 1단계 제목은 글 제목이라 뺀다
    ("## 소제목\n\n# 제목", 2),                                                # 맨 앞이 1단계 제목이 아니면 뒤의 1단계 제목은 센다
    ("---\nlayout: post\n---\n\n# 제목\n\n본문입니다.", 0),                       # 머리말 뒤 첫 줄이 1단계 제목
    ("```\n# 주석\n```\n\n본문입니다.", 0),                                      # 코드 블록 안은 세지 않는다
    ("#태그\n\n본문입니다.", 0),                                                 # 공백 없는 # 는 제목이 아니다
    ("###### 6단계\n\n####### 7개\n\n본문입니다.", 1),
    ("# 하나\n\n# 둘\n\n# 셋", 2),
    ("# 제목 #\n\n## 소제목 ##\n\n본문입니다.", 1),
    ("##\n\n본문입니다.", 1),                                                   # 글자가 없는 빈 제목 표시도 소제목이다
    ("#\n\n## 소제목\n\n본문입니다.", 1),                                        # 빈 1단계 제목은 글 제목 자리다
)


class ListHeadingParagraphTest(unittest.TestCase):
    def test_the_hand_labeled_lists_hold(self):
        for text, form, lists, paragraphs in LIST_TABLE:
            with self.subTest(text=text[:30], form=form):
                stats = run(text, form)
                self.assertEqual((stats.list_blocks, stats.paragraphs), (lists, paragraphs))

    def test_the_list_share_is_list_blocks_over_list_blocks_plus_prose_paragraphs(self):
        self.assertEqual(run("문단입니다.\n\n- a\n- b\n\n다음 문단입니다.", "md").list_share, Fraction(1, 3))
        self.assertEqual(run("- a\n- b", "md").list_share, Fraction(1))
        self.assertEqual(run("문단입니다.", "md").list_share, Fraction(0))
        self.assertIsNone(run("", "md").list_share)

    def test_the_hand_labeled_headings_hold_for_markdown_and_are_unknown_not_zero_for_text(self):
        for text, count in HEADING_TABLE:
            with self.subTest(text=text[:30]):
                self.assertEqual(run(text, "md").headings, count)
                for form in ("txt", "pasted"):
                    self.assertIsNone(run(text, form).headings, "제목 표시가 없는 형식은 0 이 아니라 알 수 없음이다")

    def test_a_paragraph_is_a_block_between_blank_lines_and_headings_lists_quotes_and_decoration_cut_it(self):
        self.assertEqual(pick(run("가나다입니다. 라마바입니다.\n\n사아자입니다.", "md"), "sentences", "paragraphs"), {"sentences": 3, "paragraphs": 2})
        self.assertEqual(run("가나다입니다. 라마바입니다.\n\n사아자입니다.", "md").per_paragraph, Fraction(3, 2))
        self.assertEqual(run("첫 줄입니다.\n## 소제목\n둘째 줄입니다.", "md").paragraphs, 2)
        self.assertEqual(run("첫 줄입니다.\n> 인용\n둘째 줄입니다.", "md").paragraphs, 2)
        self.assertEqual(run("첫 줄입니다.\n----\n둘째 줄입니다.", "md").paragraphs, 2)

    def test_a_paragraph_without_any_sentence_is_not_counted(self):
        stats = run("![그림](a.png)\n\n본문입니다.\n\n" + chr(0x2605) * 5, "md")
        self.assertEqual((stats.sentences, stats.paragraphs), (1, 1))


# ---- 6) 전처리 -------------------------------------------------------------------------------------------------------------------
PREPARE_TABLE = (
    # (글, 형식, 문장 수, 글자 합, 인용 글자 수)
    ("---\ntitle: x\n---\n\n본문입니다.", "md", 1, 6, 0),                      # 머리말
    ("---\ntitle: x\n...\n본문입니다.", "md", 1, 6, 0),
    ("---\n\n본문입니다.\n\n---\n", "md", 1, 6, 0),                            # 이름: 모양이 아닌 가로줄 둘은 머리말이 아니다
    ("---\ntitle: x\n본문입니다.", "md", 1, 13, 0),                            # 닫는 줄이 없으면 머리말이 아니다
    ("본문입니다.\n\n```\ncode. more code.\n```\n\n끝입니다.", "md", 2, 11, 0),    # 코드 블록
    ("본문입니다.\n\n```\ncode. more code.\n\n끝입니다.", "md", 1, 6, 0),         # 닫히지 않은 코드 블록은 끝까지
    ("본문입니다.\n\n" + TILDE * 3 + "\ncode. more code.\n" + TILDE * 3 + "\n\n끝입니다.", "md", 2, 11, 0),
    ("| a | b |\n|---|---|\n| 1 | 2 |\n\n본문입니다.", "md", 1, 6, 0),              # 표
    ("a | b\n--|--\n1 | 2\n\n본문입니다.", "md", 1, 6, 0),                       # 첫 | 없이 시작하는 표
    ("> 인용문입니다.\n\n본문입니다.", "md", 1, 6, 7),                            # 인용
    ("> 인용문입니다.\n\n본문입니다.", "txt", 1, 6, 7),
    ("![그림 설명](a.png)\n\n본문입니다.", "md", 1, 6, 0),                       # 그림
    ("그림 ![설명](a.png) 입니다.", "md", 1, 6, 0),
    ("[여기](" + SCHEME + "x.y)를 보세요.", "md", 1, 7, 0),                    # 링크는 글자만 남긴다
    ("**굵은** 글입니다.", "md", 1, 7, 0),                                      # 굵게 표시
    ("**굵은** 글입니다.", "txt", 1, 7, 0),
    ("자세한 내용은 " + SCHEME + "x.y/a?b=1 에서 봅니다.", "md", 1, 12, 0),       # 인터넷 주소
    ("자세한 내용은 " + SCHEME + "x.y/a?b=1 에서 봅니다.", "txt", 1, 12, 0),
    ("<b>굵은</b> 글입니다.<br>다음입니다.", "md", 2, 13, 0),                      # HTML 표시
    ("A&nbsp;B입니다.", "md", 1, 6, 0),
    ("본문입니다.\n\n#여행 #맛집", "md", 1, 6, 0),                                # 해시태그만 있는 줄
    ("본문입니다.\n\n#여행 #맛집", "txt", 1, 6, 0),
    ("본문입니다.\n\n----\n\n" + chr(0x2605) * 3 + "\n\n끝입니다.", "md", 2, 11, 0),   # 장식 줄
    ("가" + chr(0x200B) + "나" + chr(0x200D) + "다.", "md", 1, 4, 0),             # 보이지 않는 글자
    ("가" + chr(0x1B) + "나다.", "md", 1, 4, 0),                                  # 제어 문자
    ("가" + chr(0xFEFF) + "나다.", "txt", 1, 4, 0),
    ("가" + chr(0xE0020) + "나다.", "txt", 1, 4, 0),
    (unicodedata.normalize("NFD", "합니다."), "txt", 1, 4, 0),                    # 분리형 한글도 합쳐 센다
    ("<B>굵은</B> 글입니다.<BR>다음입니다.", "md", 2, 13, 0),                       # HTML 표시는 대문자도
    ("참고 " + SCHEME + "x.y/z. 다음입니다.", "md", 2, 9, 0),                       # 주소 끝의 마침표는 주소가 아니라 문장 끝 부호다
    ("```코드``` 본문입니다.\n\n끝입니다.", "md", 2, 13, 0),                        # 한 줄 안 역따옴표 묶음은 코드 블록 표시가 아니다
    ("````\n```\n본문입니다.\n````\n\n끝입니다.", "md", 1, 5, 0),                # 더 긴 울타리는 짧은 울타리 줄로 닫히지 않는다
    ("가" + chr(0xA0) + "나" + chr(0x3000) + "다.", "txt", 1, 4, 0),              # 줄 안 공백(NBSP·전각 공백)은 글자 수에 넣지 않는다
    ("    > 들여쓴 줄입니다.", "md", 1, 9, 0),                                     # 네 칸 들여쓴 꺾쇠는 인용이 아니다
    ("   | a | b |\n\n본문입니다.", "md", 1, 6, 0),                               # 세 칸까지 들여쓴 표
    ("    | a | b |\n\n본문입니다.", "md", 2, 11, 0),                              # 네 칸 들여쓰면 표가 아니다
    ("본문입니다.\n\n   ```\ncode.\n   ```\n\n끝입니다.", "md", 2, 11, 0),       # 세 칸까지 들여쓴 코드 블록
    ("    ```\n본문입니다.", "md", 1, 6, 0),                                       # 네 칸 들여쓰면 코드 블록이 아니다
    ("   > 세 칸 들여쓴 인용입니다.\n\n본문입니다.", "md", 1, 6, 11),                  # 세 칸까지 들여쓴 꺾쇠는 인용이다(네 칸은 위 행처럼 산문)
    ("   > 세 칸 들여쓴 인용입니다.\n\n본문입니다.", "txt", 1, 6, 11),
    ("자세한 내용은 <" + SCHEME + "x.y/a?b=1> 에서 봅니다.", "md", 1, 12, 0),         # 꺾쇠로 감싼 주소는 꺾쇠째 지운다
    ("자세한 내용은 <" + SCHEME + "x.y/a?b=1> 에서 봅니다.", "txt", 1, 12, 0),
    ("본문입니다.\n\n```\ncode.\n``` 닫는 줄이 아님.\nmore code.\n```\n\n끝입니다.", "md", 2, 11, 0),    # 닫는 줄 뒤에 글이 있으면 코드 블록을 닫지 못한다
    ("자세한 내용은 www.x.y/a 에서 봅니다.", "md", 1, 12, 0),                       # www 로 시작하는 주소도 지운다
    ("자세한 내용은 www.x.y/a 에서 봅니다.", "txt", 1, 12, 0),
    ("__굵은__ 글입니다.", "md", 1, 7, 0),                                          # 밑줄 두 개 굵게 표시
    ("__굵은__ 글입니다.", "txt", 1, 7, 0),
    ("snake_case_name 은 한 낱말입니다.", "md", 1, 23, 0),                          # 밑줄 하나는 표시가 아니다(지우지 않는다)
)


class PrepareTest(unittest.TestCase):
    def test_the_hand_labeled_preprocessing_holds(self):
        for text, form, sentences, chars, quote in PREPARE_TABLE:
            with self.subTest(text=text[:36], form=form):
                stats = run(text, form)
                self.assertEqual((stats.sentences, stats.chars, stats.quote_chars), (sentences, chars, quote))

    def test_line_ends_are_unified_so_a_crlf_file_still_has_paragraphs(self):
        for glue in ("\r\n", "\r", "\n", PS, LS + LS):
            with self.subTest(glue=repr(glue)):
                stats = run(f"첫 문단입니다.{glue}{glue}둘째 문단입니다.", "txt")
                self.assertEqual((stats.sentences, stats.paragraphs), (2, 2))
        self.assertEqual(run("첫 문단입니다.\r\n\r\n둘째 문단입니다.\r\n", "md").paragraphs, 2)
        self.assertEqual(run("첫 문단입니다." + PS + "둘째 문단입니다.", "txt").paragraphs, 2, "문단 구분 글자(U+2029)는 빈 줄이다")

    def test_a_wrapped_paragraph_with_crlf_is_one_paragraph_not_one_per_line(self):
        base = "첫 줄은 이렇게 쓰고\n둘째 줄은 이어서 씁니다.\n\n다음 문단입니다."
        for form in FORMS:
            crlf = run(base.replace("\n", "\r\n"), form)
            self.assertEqual(crlf, run(base, form), form)
            self.assertEqual((crlf.paragraphs, crlf.sentences), (2, 2), form)

    def test_the_same_text_with_crlf_lf_or_cr_gives_the_same_values(self):
        base = "# 제목\n\n첫 문단입니다. 둘째 문장입니다.\n\n- 항목\n\n> 인용\n\n끝 문단입니다."
        for form in FORMS:
            expected = run(base, form)
            for glue in ("\r\n", "\r"):
                self.assertEqual(run(base.replace("\n", glue), form), expected, (form, repr(glue)))

    def test_every_invisible_character_of_the_n2_list_is_removed(self):
        codes = []
        for code in garbage._INVISIBLE_CODES:
            codes += list(range(code[0], code[1] + 1)) if isinstance(code, tuple) else [code]
        self.assertGreater(len(codes), 50)
        for code in codes:
            with self.subTest(code=hex(code)):
                stats = run("가" + chr(code) + "나다입니다.", "txt")
                self.assertEqual((stats.sentences, stats.chars), (1, 7))

    def test_the_other_control_characters_are_removed_but_tab_and_newline_are_kept(self):
        for code in list(range(0, 9)) + list(range(0x0E, 0x20)) + list(range(0x7F, 0xA0)):
            if code in (0x85, 0x1C, 0x1D, 0x1E):                   # 이 글자들은 줄 구분으로 읽는다(아래 시험)
                continue
            with self.subTest(code=hex(code)):
                self.assertEqual(run("가" + chr(code) + "나다입니다.", "txt").chars, 7)
        self.assertEqual(run("가\t나다입니다.", "txt").sentences, 1)
        for code in (0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x85):
            with self.subTest(break_code=hex(code)):
                self.assertEqual(run("첫 문장입니다." + chr(code) + "둘째 문장입니다.", "txt").sentences, 2)

    def test_nfc_is_chunked_but_equal_to_a_whole_normalization_when_the_text_has_spaces_or_is_hangul(self):
        spaced = unicodedata.normalize("NFD", "한글 문장입니다 ") * 400
        self.assertEqual(S._nfc(spaced), unicodedata.normalize("NFC", spaced))
        long_hangul = unicodedata.normalize("NFD", "한글문장입니다") * 300
        self.assertEqual(S._nfc(long_hangul), unicodedata.normalize("NFC", long_hangul), "공백 없는 긴 분리형 한글도 글자가 갈리지 않는다")
        self.assertEqual(S._nfc("abc"), "abc")

    def test_a_hash_line_with_a_word_that_is_not_a_tag_is_prose(self):
        self.assertEqual(run("#1 순위입니다.", "md").sentences, 1)
        self.assertEqual(run("#여행 좋아요", "txt").sentences, 1)


# ---- 7) 줄바꿈 습관(하드랩) --------------------------------------------------------------------------------------------------------
class HardWrapTest(unittest.TestCase):
    HARD = "저는 오늘 아침에 일찍\n일어나서 시장에 갔습니다.\n\n다음 문단은 짧게\n씁니다."

    def test_lines_that_end_mid_sentence_are_joined_as_a_hard_wrapped_text(self):
        for form in ("txt", "pasted"):
            stats = run(self.HARD, form)
            self.assertEqual((stats.sentences, stats.paragraphs, stats.line_mode), (2, 2, False), form)
            self.assertEqual((stats.joined_sentences, stats.lined_sentences), (2, 4))
            self.assertTrue(stats.wrap_unstable)

    def test_markdown_always_joins_the_lines_of_a_paragraph_and_never_warns(self):
        stats = run(self.HARD, "md")
        self.assertEqual((stats.sentences, stats.line_mode, stats.joined_sentences, stats.lined_sentences), (2, False, 2, 2))
        self.assertFalse(stats.wrap_unstable)

    def test_markdown_never_counts_per_line_even_when_most_lines_end_with_a_sentence_mark(self):
        text = "첫 문장입니다.\n둘째 문장입니다.\n제목 같은 줄\n넷째 문장입니다."
        stats = run(text, "md")
        self.assertEqual((stats.sentences, stats.line_mode), (3, False))
        for form in ("txt", "pasted"):
            other = run(text, form)
            self.assertEqual((other.sentences, other.line_mode), (4, True), form)

    def test_lines_that_each_end_a_sentence_are_one_sentence_per_line(self):
        stats = run("첫 문장입니다.\n둘째 문장입니다.\n셋째 문장입니다.", "txt")
        self.assertEqual((stats.sentences, stats.line_mode, stats.joined_sentences, stats.lined_sentences), (3, True, 3, 3))
        self.assertFalse(stats.wrap_unstable)

    def test_the_half_way_point_decides_by_the_lines_inside_a_paragraph_not_counting_the_last_line(self):
        four = "가나다입니다.\n라마바 사아자\n차카타입니다.\n파하 가나다\n마지막입니다."        # 마지막 줄을 뺀 4줄 중 2줄이 부호로 끝남(정확히 절반) → 줄마다
        self.assertTrue(run(four, "txt").line_mode)
        less = "가나다입니다.\n라마바 사아자\n차카타 파하\n파하 가나다\n마지막입니다."          # 4줄 중 1줄(25%) → 이어 센다
        self.assertFalse(run(less, "txt").line_mode)
        self.assertEqual(run(less, "txt").sentences, 2, "이어 세면 '…입니다.' 둘뿐")
        self.assertEqual(run(four, "txt").sentences, 5 - 0, "줄마다 센 문장 수 — 다섯 줄이 모두 문장")

    def test_the_half_way_point_is_exactly_fifty_percent_even_with_a_hundred_inner_lines(self):
        def paragraph(ended):
            return "\n".join(["가나다 라마바"] * (100 - ended) + ["가나다 라마바."] * ended + ["마지막입니다."])
        self.assertFalse(run(paragraph(49), "txt").line_mode)
        self.assertTrue(run(paragraph(50), "txt").line_mode)
        self.assertTrue(run(paragraph(51), "txt").line_mode)

    def test_paragraphs_of_one_line_have_no_inner_lines_so_the_decision_never_matters(self):
        stats = run("첫 문단입니다.\n\n둘째 문단입니다.\n\n셋째 문단입니다.", "txt")
        self.assertEqual((stats.line_mode, stats.joined_sentences, stats.lined_sentences), (False, 3, 3))

    def test_the_last_line_of_each_paragraph_does_not_count_so_short_wrapped_paragraphs_are_joined(self):
        """2줄짜리 문단이 여럿이고 첫 줄은 모두 문장 가운데서 끝난다 — 마지막 줄(부호로 끝남)까지 세면 절반이라 줄마다로 갈릴 수 있다."""
        text = "\n\n".join("저는 오늘 아침에 일찍\n일어나서 시장에 갔습니다." for _ in range(6))
        stats = run(text, "txt")
        self.assertEqual((stats.line_mode, stats.sentences, stats.paragraphs), (False, 6, 6))

    def test_the_wrap_gap_boundary_is_thirty_percent_exclusive(self):
        def broken(lines):
            return "\n".join(["가나다 라마바"] * (lines - 1) + ["사아자."])
        for lines, unstable in ((3, False), (4, False), (5, True)):
            with self.subTest(lines=lines):
                text = "\n\n".join([broken(lines)] + ["가나다."] * 6)
                stats = run(text, "txt")
                self.assertEqual((stats.joined_sentences, stats.lined_sentences), (7, lines + 6))
                self.assertEqual(stats.wrap_unstable, unstable)
        exact = run("\n\n".join([broken(4)] + ["가나다."] * 6), "txt")
        self.assertEqual(abs(exact.joined_sentences - exact.lined_sentences) * 100, 30 * max(exact.joined_sentences, exact.lined_sentences), "정확히 30% — 초과가 아니라 안내하지 않는다")

    def test_pasted_and_txt_are_counted_the_same_way(self):
        for text in (self.HARD, "첫 문장입니다.\n둘째 문장입니다.", "# 제목\n- 항목\n본문입니다.", ""):
            self.assertEqual(run(text, "txt"), run(text, "pasted"))

    def test_a_per_line_text_with_a_line_that_stops_mid_sentence_gets_the_wrap_notice_even_when_the_gap_is_small(self):
        """D-430 — 줄마다 문장 경계로 읽었는데(안쪽 줄의 절반 이상이 끝 부호로 끝남) 끝 부호로 끝나지 않은 줄이 하나라도 섞이면 억지 줄바꿈을 한 문장씩으로 잘못 읽었을 수 있다 — 두 방식의 차이가 30% 이하여도 안내한다."""
        text = "\n".join(["가나다입니다."] * 8 + ["라마바 사아자", "차카타입니다."])
        for form in ("txt", "pasted"):
            stats = run(text, form)
            self.assertEqual((stats.line_mode, stats.joined_sentences, stats.lined_sentences), (True, 9, 10), form)
            self.assertLessEqual(abs(stats.joined_sentences - stats.lined_sentences) * 100, S.WRAP_GAP_PERCENT * 10, "차이가 30% 이하라 옛 규칙은 조용했다")
            self.assertTrue(stats.wrap_unstable, form)
            self.assertIn("wrap", stats.notices(), form)
        markdown = run(text, "md")
        self.assertEqual((markdown.line_mode, markdown.joined_sentences, markdown.lined_sentences), (False, 9, 9))
        self.assertFalse(markdown.wrap_unstable)

    def test_one_line_that_stops_mid_sentence_among_a_hundred_is_enough_for_the_notice(self):
        text = "\n".join(["가나다입니다."] * 99 + ["라마바 사아자", "차카타입니다."])
        stats = run(text, "txt")
        self.assertEqual((stats.line_mode, stats.joined_sentences, stats.lined_sentences), (True, 100, 101))
        self.assertTrue(stats.wrap_unstable, "차이가 1% 여도 문장 중간에서 끝난 줄이 있으면 안내한다")

    def test_a_per_line_text_whose_every_inner_line_ends_with_a_mark_or_a_one_line_paragraph_never_gets_the_notice(self):
        every_line = "\n".join(["가나다입니다."] * 20)
        one_line = "\n\n".join(["가나다입니다. 라마바입니다. 사아자입니다."] * 5)
        for form in ("txt", "pasted"):
            for text in (every_line, one_line):
                self.assertFalse(run(text, form).wrap_unstable, (form, text[:12]))


class ShortSentenceSweepTest(unittest.TestCase):
    """D-430 — 짧은 문장(열두 글자 안팎)을 억지로 줄바꿈한 글. 폭 20–100칸 어디서 줄바꿈해도 '문장 수가 틀렸는데 줄바꿈 안내가 없는' 글이 없다(독립 검증 D1: 옛 규칙은 같은 글 묶음에서 138건을 안내 없이 틀렸다)."""
    SHORT = (
        "아침에 일찍 일어났습니다.", "창문을 활짝 열었습니다.", "찬 바람이 들어왔습니다.", "커피를 한 잔 내렸습니다.", "빵도 하나 구웠습니다.",
        "잠시 책을 읽었습니다.", "해가 천천히 떴습니다.", "마음이 한결 편했습니다.", "오늘은 쉬는 날입니다.", "그래서 더 여유로웠습니다.",
        "공원까지 걸어갔습니다.", "벤치에 잠깐 앉았습니다.", "새소리가 들렸습니다.", "강아지가 지나갔습니다.", "주인이 손을 흔들었습니다.",
        "저도 웃으며 답했습니다.", "점심은 간단히 먹었습니다.", "오후엔 청소를 했습니다.", "방이 깨끗해졌습니다.", "기분도 맑아졌습니다.",
    )
    POLITE = (
        "오늘은 날씨가 좋아요.", "산책을 다녀왔어요.", "공원에 사람이 많았죠.", "벤치에 앉아 쉬었어요.", "바람이 시원했어요.",
        "커피도 한 잔 마셨죠.", "책을 조금 읽었어요.", "집에 돌아왔어요.", "저녁은 간단히 먹었죠.", "일찍 잠들었어요.",
        "내일도 걸을 거예요.", "여러분은 어떠세요?",
    )

    def texts(self):
        """(이름, 문단들 — 문단마다 문장 목록). 문장 수는 손으로 센 것이다(합쇼 20·해요 12·섞음 17)."""
        short, polite = self.SHORT, self.POLITE
        return (
            ("합쇼 20문장 문단 둘", [short[0:10], short[10:20]]),
            ("합쇼 20문장 문단 셋", [short[0:7], short[7:14], short[14:20]]),
            ("합쇼 20문장 문단 하나", [short]),
            ("해요 12문장 문단 둘", [polite[:6], polite[6:]]),
            ("해요 12문장 문단 넷", [polite[0:3], polite[3:6], polite[6:9], polite[9:12]]),
            ("섞음 문단 셋", [short[0:4] + polite[0:3], polite[3:8], short[4:9]]),
        )

    @staticmethod
    def wrapped(paragraphs, width):
        return "\n\n".join(textwrap.fill(" ".join(group), width=width, break_long_words=False, break_on_hyphens=False) for group in paragraphs)

    def test_the_hand_counted_sentences_are_what_the_text_has_before_it_is_wrapped(self):
        for name, paragraphs in self.texts():
            truth = sum(len(group) for group in paragraphs)
            for form in FORMS:
                with self.subTest(name=name, form=form):
                    self.assertEqual(run("\n\n".join(" ".join(group) for group in paragraphs), form).sentences, truth)

    def test_a_wrong_sentence_count_always_comes_with_the_wrap_notice(self):
        wrong = total = 0
        for name, paragraphs in self.texts():
            truth = sum(len(group) for group in paragraphs)
            for width in range(20, 101):
                text = self.wrapped(paragraphs, width)
                for form in ("txt", "pasted"):
                    stats = run(text, form)
                    total += 1
                    if stats.sentences != truth:
                        wrong += 1
                        self.assertIn("wrap", stats.notices(), f"{name} {width}칸 {form}: 문장 {truth} → {stats.sentences} 인데 줄바꿈 안내가 없다")
        self.assertEqual(total, 6 * 81 * 2)
        self.assertGreater(wrong, 100, "이 글 묶음에는 문장 수가 틀리는 폭이 실제로 있다(없으면 이 시험은 아무것도 지키지 못한다)")

    def test_the_same_texts_without_a_forced_wrap_never_get_the_notice_and_are_counted_exactly(self):
        for name, paragraphs in self.texts():
            truth = sum(len(group) for group in paragraphs)
            variants = (("문단마다 한 줄", "\n\n".join(" ".join(group) for group in paragraphs)), ("문장마다 한 줄", "\n\n".join("\n".join(group) for group in paragraphs)))
            for label, text in variants:
                for form in ("txt", "pasted"):
                    with self.subTest(name=name, wrapping=label, form=form):
                        stats = run(text, form)
                        self.assertNotIn("wrap", stats.notices())
                        self.assertEqual(stats.sentences, truth)

    def test_markdown_never_gets_the_notice_at_any_width_and_always_counts_exactly(self):
        for name, paragraphs in self.texts():
            truth = sum(len(group) for group in paragraphs)
            for width in range(20, 101):
                stats = run(self.wrapped(paragraphs, width), "md")
                self.assertEqual((stats.sentences, stats.wrap_unstable), (truth, False), f"{name} {width}칸")


BASE_PROSE = (
    "저는 요즘 아침마다 동네 공원을 걷습니다. 처음에는 십 분만 걸어도 숨이 찼는데 지금은 삼십 분을 걸어도 괜찮습니다. 걷는 시간이 늘면서 하루가 한결 가벼워졌어요. 여러분은 어떤 운동을 하고 계신가요?\n\n"
    "걷기를 오래 하려면 준비가 필요합니다. 먼저 발에 맞는 신발을 고르세요. 두 번째로 물을 챙기는 것이 좋습니다. 날씨가 더운 날에는 이른 아침을 고르는 편이 낫죠. 무리하지 않는 것이 가장 중요합니다.\n\n"
    "처음 시작한 날을 기록해 두면 변화가 눈에 보입니다. 저는 달력에 표시를 했어요. 한 달이 지나자 표시가 빼곡해졌습니다. 이제는 걷지 않으면 허전합니다. 오늘도 걸었습니다.\n\n"
    "다음 글에서는 걷기에 어울리는 간식을 소개해 드리겠습니다. 기대해 주세요."
)


class InvarianceTest(unittest.TestCase):
    """같은 글을 줄바꿈만 다르게 해도 값이 같다 — 줄바꿈 습관이 숫자를 바꾸지 않는다."""

    @staticmethod
    def wrapped(text, width):
        return "\n\n".join(textwrap.fill(paragraph, width=width) for paragraph in text.split("\n\n"))

    @staticmethod
    def sentence_lines(text):
        return "\n\n".join("\n".join(claims.split_sentences(paragraph)) for paragraph in text.split("\n\n"))

    def variants(self):
        found = {"문단마다 한 줄": BASE_PROSE, "한 문장 한 줄": self.sentence_lines(BASE_PROSE)}
        for width in (36, 44, 52, 60, 72, 80):
            found[f"{width}칸 억지 줄바꿈"] = self.wrapped(BASE_PROSE, width)
        return found

    def test_the_values_are_the_same_for_every_line_wrapping_in_every_form(self):
        for form in FORMS:
            expected = values(run(BASE_PROSE, form))
            for name, text in self.variants().items():
                with self.subTest(form=form, wrapping=name):
                    self.assertEqual(values(run(text, form)), expected)

    def test_the_old_way_of_cutting_at_every_line_break_would_have_shaken_the_numbers(self):
        """증명 — 같은 글을 줄마다 가르면 문장 수가 크게 불어난다(24 → 47 같은 흔들림). 우리 값은 그대로다."""
        def naive(text):
            return sum(len(claims.split_sentences(line)) for line in text.split("\n") if line.strip())
        sentences = run(BASE_PROSE, "txt").sentences
        self.assertEqual(naive(BASE_PROSE), sentences)
        wrapped = self.wrapped(BASE_PROSE, 36)
        self.assertGreater(naive(wrapped), sentences * 1.5)
        self.assertEqual(run(wrapped, "txt").sentences, sentences)
        self.assertTrue(run(wrapped, "txt").wrap_unstable, "두 방식이 많이 달라서 안내가 켜진다")

    def test_the_average_sentence_length_and_the_per_paragraph_count_do_not_move(self):
        for form in FORMS:
            base = run(BASE_PROSE, form)
            for width in (40, 60, 80):
                other = run(self.wrapped(BASE_PROSE, width), form)
                self.assertEqual((other.sentence_length, other.per_paragraph, other.end_shares), (base.sentence_length, base.per_paragraph, base.end_shares), (form, width))

    def test_the_base_text_has_the_hand_counted_numbers(self):
        stats = run(BASE_PROSE, "md")
        self.assertEqual((stats.sentences, stats.paragraphs, stats.questions), (16, 4, 1))
        self.assertEqual((stats.end_formal, stats.end_polite, stats.end_plain, stats.end_other), (10, 6, 0, 0))


class PrototypeNumbersTest(unittest.TestCase):
    """실제 글(자동 발행 글 한 편)의 줄바꿈 민감도 — 같은 글을 60칸에서 억지로 줄바꿈하면 줄마다 센 문장 수는 크게 늘고(시제품 24 → 47), 우리 값은 그대로다."""

    @classmethod
    def setUpClass(cls):
        cls.original = FIXTURE.read_text(encoding="utf-8")
        head, _separator, body = cls.original.partition("\n---\n\n")

        def wrap(**options):
            blocks = [block if block.lstrip().startswith(("#", "-", "*", ">", "|", "!")) or "\n" in block else textwrap.fill(block, width=60, **options) for block in body.split("\n\n")]
            return head + "\n---\n\n" + "\n\n".join(blocks)
        cls.wrapped = wrap(break_on_hyphens=False, break_long_words=False)          # 공백에서만 끊는 줄바꿈(편집기가 하는 것 — 링크 글 가운데서 줄이 바뀐다)
        cls.wrapped_at_hyphens = wrap()                                               # 하이픈에서도 끊는 줄바꿈(인터넷 주소가 줄에 걸친다)

    def test_the_wrapped_copy_really_has_many_more_lines(self):
        self.assertGreater(self.wrapped.count("\n"), self.original.count("\n") + 20)
        self.assertGreater(self.wrapped_at_hyphens.count("\n"), self.original.count("\n") + 20)

    def test_the_hand_counted_numbers_of_the_real_post_in_markdown(self):
        stats = run(self.original, "md")
        self.assertEqual((stats.sentences, stats.paragraphs, stats.list_blocks, stats.headings), (22, 12, 1, 3))
        self.assertEqual((stats.end_formal, stats.end_other), (18, 4))
        self.assertEqual(stats.notices(), ())

    def test_markdown_values_do_not_change_when_the_post_is_wrapped_at_sixty_columns(self):
        self.assertEqual(run(self.wrapped, "md"), run(self.original, "md"))

    def test_markdown_values_do_not_change_even_when_a_web_address_is_wrapped_at_its_hyphens(self):
        """하이픈 뒤에서 끊긴 주소는 공백 없이 다시 이어 한 덩어리로 지운다."""
        self.assertEqual(run(self.wrapped_at_hyphens, "md"), run(self.original, "md"))

    def test_the_text_form_does_not_change_either_and_the_naive_count_would_have(self):
        base, other = run(self.original, "txt"), run(self.wrapped, "txt")
        self.assertEqual(values(other), values(base))

        def naive(text):
            return sum(len(claims.split_sentences(line)) for line in text.split("\n") if line.strip())
        self.assertGreater(naive(self.wrapped), naive(self.original) * 1.3)

    def test_the_links_at_the_end_of_a_sentence_do_not_eat_the_sentence_end_or_the_particle_after_them(self):
        """원문 실제 모양 — `…주소>.` 의 마침표와 `(주소)로 제공됩니다` 의 조사가 주소와 함께 지워지지 않는다."""
        stats = run("원문은 라이선스(" + SCHEME + "x.y/z.ko)로 제공됩니다. 다음입니다.", "md")
        self.assertEqual((stats.sentences, stats.end_formal), (2, 2))
        self.assertEqual(stats.chars, len("원문은라이선스()로제공됩니다.") + len("다음입니다."))
        stats = run("자료 <" + SCHEME + "x.y/a-b_c>. 이어지는 말입니다.", "md")
        self.assertEqual(stats.sentences, 2)


# ---- 8) 신뢰 안내의 경계 ----------------------------------------------------------------------------------------------------------
class NoticeBoundaryTest(unittest.TestCase):
    def prose(self, lengths):
        return " ".join(sentence_of(length) for length in lengths)

    def test_short_text_is_fewer_than_ten_sentences_or_fewer_than_six_hundred_characters(self):
        self.assertFalse(run(self.prose([60] * 10), "md").short)                    # 문장 10개·600자 — 둘 다 기준 이상
        self.assertTrue(run(self.prose([60] * 9 + [59]), "md").short)              # 599자
        self.assertTrue(run(self.prose([80] * 9), "md").short)                     # 문장 9개(720자)
        self.assertFalse(run(self.prose([60] * 10), "md").no_sentences)
        stats = run(self.prose([60] * 10), "md")
        self.assertEqual((stats.sentences, stats.chars), (10, 600))
        self.assertEqual(run(self.prose([60] * 9 + [59]), "md").chars, 599)

    def test_a_text_without_sentences_says_empty_not_short(self):
        stats = run("", "md")
        self.assertEqual(stats.notices(), ("empty",))
        self.assertFalse(stats.short)

    def test_low_hangul_is_below_half_of_the_letters(self):
        self.assertFalse(run("가가가가가aaaaa.", "txt").low_hangul)             # 정확히 50%
        self.assertTrue(run("가가가가aaaaa.", "txt").low_hangul)                 # 44%
        self.assertFalse(run("가가가가가가aaaaa.", "txt").low_hangul)
        self.assertFalse(run("1234 5678.", "txt").low_hangul, "글자가 하나도 없으면 한글이 적다고 하지 않는다")
        stats = run("가가가가가aaaaa.", "txt")
        self.assertEqual((stats.hangul, stats.letters), (5, 10))
        self.assertEqual(stats.hangul_share, Fraction(1, 2))

    def test_quote_heavy_is_thirty_percent_or_more_of_the_prose_plus_the_quote_lines(self):
        def with_quote(prose, quote):
            return sentence_of(prose) + "\n\n> " + "나" * quote
        self.assertTrue(run(with_quote(70, 30), "md").quote_heavy)                  # 30/100
        self.assertFalse(run(with_quote(71, 29), "md").quote_heavy)                 # 29/100
        self.assertFalse(run(sentence_of(70), "md").quote_heavy)
        self.assertTrue(run("> " + "나" * 20, "md").quote_heavy)

    def test_light_endings_are_flagged_from_twenty_percent_of_the_sentences(self):
        def mixed(light):
            return " ".join(["좋아요ㅎㅎ."] * light + ["좋아요."] * (10 - light))
        self.assertTrue(run(mixed(2), "txt").casual_heavy)
        self.assertFalse(run(mixed(1), "txt").casual_heavy)
        self.assertEqual(run(mixed(2), "txt").casual_ends, 2)

    def test_light_endings_boundary_is_exact_with_twenty_one_sentences(self):
        def mixed(light):
            return " ".join(["좋아요ㅎㅎ."] * light + ["좋아요."] * (21 - light))
        self.assertFalse(run(mixed(4), "txt").casual_heavy)             # 4/21 = 19.05%
        self.assertTrue(run(mixed(5), "txt").casual_heavy)              # 5/21 = 23.8%

    def test_notices_come_in_the_fixed_order_with_their_keys(self):
        stats = run("> " + "나" * 40 + "\n\nHello there. Nice day.\n\n좋아요ㅎㅎ.", "md")
        self.assertEqual((stats.sentences, stats.quote_chars, stats.letters, stats.hangul, stats.casual_ends), (3, 40, 22, 5, 1))
        self.assertEqual(stats.notices(), ("short", "quote", "low_hangul", "casual"))
        self.assertEqual(run("저는 오늘 아침에 일찍\n일어나서 시장에 갔습니다.", "txt").notices(), ("short", "wrap"))
        self.assertEqual(run("").notices(), ("empty",))


# ---- 9) 글 둘 ---------------------------------------------------------------------------------------------------------------------
class SummaryTest(unittest.TestCase):
    def test_one_text_is_its_own_pooled_value_and_never_differs(self):
        stats = run("가나다입니다. 라마바입니다.", "md")
        summary = S.summarize([stats])
        self.assertIs(summary.pooled, stats)
        self.assertEqual(summary.differs, (False, False, False, False))
        self.assertFalse(summary.range_only)

    def test_two_texts_are_pooled_by_collecting_sentences_and_paragraphs_not_by_averaging_averages(self):
        first = run(sentence_of(10), "txt")                                         # 문장 1개·글자 10
        second = run(" ".join([sentence_of(20)] * 3), "txt")                      # 문장 3개·글자 60
        pooled = S.summarize([first, second]).pooled
        self.assertEqual((pooled.sentences, pooled.chars, pooled.paragraphs), (4, 70, 2))
        self.assertEqual(pooled.sentence_length, Fraction(70, 4))                  # 17.5 — 평균의 평균(15)이 아니다
        self.assertNotEqual(pooled.sentence_length, (first.sentence_length + second.sentence_length) / 2)
        self.assertEqual(pooled.per_paragraph, Fraction(4, 2))

    def test_the_pooled_headings_are_the_sum_and_unknown_when_any_text_does_not_know_them(self):
        both = S.summarize([run("## a\n\n본문입니다.", "md"), run("## a\n\n## b\n\n본문입니다.", "md")]).pooled
        self.assertEqual(both.headings, 3)
        mixed = S.summarize([run("## a\n\n본문입니다.", "md"), run("본문입니다.", "pasted")]).pooled
        self.assertIsNone(mixed.headings)

    def test_the_pooled_line_mode_is_true_if_any_text_was_counted_per_line(self):
        pooled = S.summarize([run("첫 문장입니다.\n둘째 문장입니다.", "txt"), run("가나다입니다.", "txt")]).pooled
        self.assertTrue(pooled.line_mode)
        self.assertFalse(S.summarize([run("가나다입니다.", "md"), run("라마바입니다.", "md")]).pooled.line_mode)

    def test_the_sentence_length_difference_is_forty_percent_exclusive(self):
        small = run(sentence_of(10), "txt")
        for other, flagged in ((14, False), (15, True), (13, False)):
            with self.subTest(other=other):
                summary = S.summarize([small, run(sentence_of(other), "txt")])
                self.assertEqual(summary.differs[0], flagged)
        self.assertTrue(S.summarize([run(sentence_of(15), "txt"), small]).differs[0], "순서가 바뀌어도 같다")

    def test_the_heading_count_difference_is_more_than_three(self):
        zero = run("본문입니다.", "md")
        for count, flagged in ((3, False), (4, True)):
            with self.subTest(count=count):
                other = run("## a\n\n" * count + "본문입니다.", "md")
                self.assertEqual(other.headings, count)
                self.assertEqual(S.summarize([zero, other]).differs[1], flagged)

    def test_the_per_paragraph_difference_is_more_than_double(self):
        one = run("가나다입니다.", "txt")
        self.assertFalse(S.summarize([one, run("가나다입니다. 라마바입니다.", "txt")]).differs[2])             # 정확히 2배
        self.assertTrue(S.summarize([one, run("가나다입니다. 라마바입니다. 사아자입니다.", "txt")]).differs[2])
        self.assertTrue(S.summarize([run("가나다입니다. 라마바입니다. 사아자입니다.", "txt"), one]).differs[2])

    def test_the_question_share_difference_is_more_than_fifteen_points(self):
        def asked(count):
            return " ".join(["정말요?"] * count + ["그래요."] * (20 - count))
        zero = run(asked(0), "txt")
        self.assertFalse(S.summarize([zero, run(asked(3), "txt")]).differs[3])        # 15%p 정확히
        self.assertTrue(S.summarize([zero, run(asked(4), "txt")]).differs[3])
        self.assertTrue(S.summarize([run(asked(4), "txt"), zero]).differs[3])

    def test_range_only_is_true_when_any_one_of_the_four_criteria_is_exceeded(self):
        a, b = run(sentence_of(10), "txt"), run(sentence_of(15), "txt")
        summary = S.summarize([a, b])
        self.assertEqual(summary.differs, (True, False, False, False))
        self.assertTrue(summary.range_only)
        calm = S.summarize([a, run(sentence_of(14), "txt")])
        self.assertFalse(calm.range_only)

    def test_a_criterion_that_cannot_be_compared_is_not_flagged(self):
        empty, other = run("", "txt"), run(sentence_of(40), "md")
        summary = S.summarize([empty, other])
        self.assertEqual(summary.differs, (False, False, False, False))
        self.assertEqual(summary.pooled.sentences, 1)
        unknown_headings = S.summarize([run("본문입니다.", "pasted"), run("## a\n\n" * 9 + "본문입니다.", "md")])
        self.assertFalse(unknown_headings.differs[1], "제목 수를 모르는 글과는 견주지 않는다")

    def test_value_and_span_give_per_metric_numbers_and_ranges(self):
        a, b = run("가나다입니다. 정말요?", "md"), run("라마바입니다. 사아자입니다. 차카타입니다.", "md")
        self.assertEqual(S.value(a, "question"), Fraction(1, 2))
        self.assertEqual(S.span([a, b], "question"), (Fraction(0), Fraction(1, 2)))
        self.assertEqual(S.span([a, b], "headings"), (0, 0))
        self.assertEqual(S.span([a, b], "end_formal"), (Fraction(1, 2), Fraction(1)))
        self.assertIsNone(S.span([run("", "md")], "sentence_length"))
        self.assertIsNone(S.span([run("가", "pasted")], "headings"))
        self.assertEqual(S.span([run("본문입니다.", "pasted"), run("## a\n\n본문입니다.", "md")], "headings"), (1, 1), "알 수 없는 글은 범위에서 뺀다")
        for metric in S.METRICS:
            if S.value(a, metric) is not None:
                self.assertEqual(S.span([a], metric), (S.value(a, metric), S.value(a, metric)), metric)
        with self.assertRaises(ValueError):
            S.value(a, "nothing")

    def test_the_wrong_number_or_kind_of_items_is_refused(self):
        stats = run("가나다입니다.")
        for bad in ([], [stats, stats, stats], [stats, "가나다"], [None], "가"):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(ValueError):
                    S.summarize(bad)


# ---- 10) 형식 ---------------------------------------------------------------------------------------------------------------------
class FormsTest(unittest.TestCase):
    def test_pasted_text_and_a_text_file_are_counted_in_exactly_the_same_way(self):
        for text, _form, *_ in PREPARE_TABLE:
            self.assertEqual(run(text, "txt"), run(text, "pasted"))

    def test_markdown_and_text_differ_only_where_the_form_gives_a_meaning(self):
        text = "# 제목\n\n본문입니다.\n\n```\ncode.\n```\n\n| a | b |\n|---|---|\n\n끝입니다."
        md, txt = run(text, "md"), run(text, "txt")
        self.assertEqual((md.headings, txt.headings), (0, None))
        self.assertEqual((md.sentences, txt.sentences), (2, 5), "텍스트 형식은 제목·코드·표 표시를 모르니 그 줄들도 산문으로 센다")

    def test_the_same_markdown_text_gives_the_same_values_every_time(self):
        raw = FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(run(raw, "md"), run(raw, "md"))
        self.assertEqual(run(raw, "md"), run(raw.replace("\n", "\r\n"), "md"))


# ---- 10b) 고치지 않은 한계 ---------------------------------------------------------------------------------------------------------
class KnownLimitsTest(unittest.TestCase):
    """D-432 — 독립 검증이 찾았고 **고치지 않은** 한계. 문서(결정 기록·UI 문서)가 말한 오차가 정말 이 숫자로 나타난다 — 이 시험이 깨지면(누가 한계를 고치면) 문서의 표도 함께 고친다."""
    LIMITS = (
        # (이름, 글, 형식, 셈(오차가 있는 값), 사람 눈의 정답)
        ("밑줄 제목(=====)", "제목입니다\n======\n\n본문 문장입니다.", "md", dict(sentences=2, headings=0, paragraphs=2), dict(sentences=1, headings=1, paragraphs=1)),
        ("네 칸 들여쓴 코드", "설명 문장입니다.\n\n    print(\"x.\")\n    값 = 3\n\n다음 문장입니다.", "md", dict(sentences=4, chars=30, paragraphs=3), dict(sentences=2, chars=16, paragraphs=2)),
        ("참조식 링크 정의 줄", "자세한 내용은 [문서][1] 에 있습니다.\n\n[1]: " + SCHEME + "example.com/docs", "md", dict(sentences=2, chars=23), dict(sentences=1, chars=14)),
        ("공백 낀 가로줄", "앞 문단입니다.\n\n* * *\n\n뒤 문단입니다.", "md", dict(list_blocks=1), dict(list_blocks=0)),
        ("번호 목록 뒤 점 목록", "1. 하나\n2. 둘\n\n- 셋\n- 넷", "md", dict(list_blocks=1), dict(list_blocks=2)),
        ("한 겹 밑줄 기울임", "_기울임_ 표시입니다.", "md", dict(chars=11), dict(chars=9)),
        ("감탄 조각 ㅎㅎ", "맛있다!! ㅎㅎ", "txt", dict(sentences=2, chars=7), dict(sentences=1, chars=5)),
        ("한국식 불릿 ·", "문단입니다.\n\n" + chr(0xB7) + " 하나입니다.\n" + chr(0xB7) + " 둘입니다.", "md", dict(list_blocks=0, sentences=3), dict(list_blocks=1, sentences=1)),
        ("한국식 번호 가. 나.", "문단입니다.\n\n가. 하나입니다.\n나. 둘입니다.", "md", dict(list_blocks=0, sentences=5), dict(list_blocks=1, sentences=1)),
        ("괄호 번호 (1) (2)", "문단입니다.\n\n(1) 하나입니다.\n(2) 둘입니다.", "md", dict(list_blocks=0, sentences=3), dict(list_blocks=1, sentences=1)),
        ("굵은 라벨 **해석.**", "**해석.** 이 방법은 간단합니다.", "md", dict(sentences=2, chars=13), dict(sentences=1)),
        ("물음표 없는 질문 …나요", "이 방법이 맞나요. 같이 갈까요. 혹시 괜찮은가요.", "md", dict(questions=1), dict(questions=3)),
    )

    def test_each_limit_that_was_not_fixed_shows_the_error_the_documents_describe(self):
        for name, text, form, shown, truth in self.LIMITS:
            with self.subTest(limit=name):
                stats = run(text, form)
                self.assertEqual(pick(stats, *shown), shown, "문서가 말한 오차가 숫자로 나타난다")
                self.assertTrue([key for key in truth if shown[key] != truth[key]], "이 행은 사람 눈의 정답과 다른 값이 있는 행이다")

    def test_the_text_form_has_the_same_limits_for_the_shapes_it_understands(self):
        """마크다운 표시가 아닌 한계(감탄 조각·물음표 없는 질문)는 텍스트·붙여 넣은 글에서도 같다."""
        for form in ("txt", "pasted"):
            self.assertEqual(pick(run("맛있다!! ㅎㅎ", form), "sentences", "chars"), dict(sentences=2, chars=7))
            self.assertEqual(run("이 방법이 맞나요. 같이 갈까요. 혹시 괜찮은가요.", form).questions, 1)


# ---- 11) 소스 규칙 ---------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.text)

    def imports(self):
        found = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                found += [(alias.name, 0) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                found += [((node.module or "") if not node.names else (node.module or "") + ":" + ",".join(alias.name for alias in node.names), node.level)]
        return found

    def test_only_the_standard_library_and_the_n2_invisible_characters_are_imported(self):
        self.assertEqual(sorted(self.imports()), sorted([("re", 0), ("unicodedata", 0), ("dataclasses:dataclass,fields", 0), ("fractions:Fraction", 0), ("__future__:annotations", 0), ("check:garbage", 2)]))

    def test_no_profile_setting_store_service_or_network_module_is_named_in_an_import(self):
        names = " ".join(name for name, _level in self.imports())
        for word in ("profiles", "blog_profiles", "channels", "context", "store", "topics", "topicdb", "journal", "connections", "service", "security", "publish", "render", "ui", "os", "sys", "time", "random", "datetime", "socket", "urllib", "http", "subprocess", "shutil", "tempfile", "logging", "threading", "pathlib", "io", "json", "sqlite3", "ctypes"):
            self.assertNotRegex(names, r"(?<![A-Za-z_])" + word + r"(?![A-Za-z_])", word)

    def test_no_call_opens_prints_executes_or_reads_the_environment(self):
        calls = {ast.unparse(node.func) for node in ast.walk(self.tree) if isinstance(node, ast.Call)}
        for forbidden in ("open", "print", "exec", "eval", "compile", "input", "__import__", "breakpoint", "globals", "locals", "vars", "setattr", "delattr"):
            self.assertNotIn(forbidden, calls, forbidden)
        for node in ast.walk(self.tree):
            self.assertNotIsInstance(node, (ast.Global, ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom))

    def test_no_state_is_kept_between_calls(self):
        """모듈 맨 위에서 바뀌는 그릇(리스트·사전·집합)을 만들지 않는다 — 상수·정규식·튜플뿐이다."""
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) != "__all__":
                value = node.value
                self.assertNotIsInstance(value, (ast.List, ast.Set, ast.ListComp, ast.SetComp), ast.unparse(node)[:60])
                if isinstance(value, (ast.Dict, ast.DictComp)):
                    self.assertTrue(ast.unparse(node.targets[0]) == "_NEWLINES", "바뀌지 않게만 쓰는 글자 바꾸기 표 하나뿐이다")

    def test_the_text_and_the_comments_have_no_tilde_no_web_address_and_no_raw_line_separator(self):
        self.assertNotIn(TILDE, self.text)
        self.assertNotRegex(self.text, r"(?i)(https?|ftp)://|www[.]")
        for code in (0x2028, 0x2029, 0x85, 0x0B, 0x0C, 0xFEFF, 0x200B):
            self.assertNotIn(chr(code), self.text, hex(code))

    def test_no_secret_word_and_no_new_error_code_are_in_the_strings(self):
        words = re.compile(r"(?i)\b(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?\b")
        exported = {item.value for node in self.tree.body if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "__all__" for item in node.value.elts}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertIsNone(words.search(node.value))
                if node.value not in exported:                                      # 내보내는 이름표 목록은 빼고 — 오류 코드처럼 생긴 대문자 글이 없다
                    self.assertNotRegex(node.value, r"^[A-Z][A-Z0-9_]{5,}$", node.value[:30])
        self.assertNotIn("AppError", self.text)

    def test_the_source_never_keeps_the_text_in_a_module_level_name(self):
        names = {target.id for node in self.tree.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
        for name in names:
            self.assertTrue(name.isupper() or name.startswith("_"), name)


class DocsTest(unittest.TestCase):
    """이 모듈을 가리키는 문서 줄이 있다 — 결정 기록의 D-330 이 이 파일 이름·한계를 말한다."""

    def test_the_module_docstring_names_the_decisions_the_six_numbers_and_the_limits(self):
        doc = S.__doc__
        for word in ("D-330", "여섯 가지", "겉모양 규칙", "선형 시간", "하드랩", "None", "Fraction"):
            self.assertIn(word, doc, word)


class BundleDocsTest(unittest.TestCase):
    """이 묶음의 문서 — 결정 행 D-330–D-339·보안·구조·UI 문서 넷·변경 이력. **이 묶음 자신의 행·줄·절만** 못박는다(다른 묶음의 결정 번호나 번호의 최댓값은 못박지 않는다 — 다음 묶음이 행을 더해도 이 시험은 깨지지 않는다)."""
    ROW_WORDS = {
        "D-330": ("N-3a", "N-3b", "T1", "설정 화면 맨 아래", "check_pasted_text", "최대 2개", "2MB", "100,000", "diff 0", "naver_profiles", "channel_profiles.json"),
        "D-331": ("claims.split_sentences", "계획 B.2", "하드랩", "50%", "알 수 없음", "NFC", "512자", "CRLF", "부드러운 줄바꿈", "HTML 입력"),
        "D-332": ("OR", "600", "30%", "20%", "한글", "알 수 없음", "고정 문장", "style_rough", "empty", "casual"),
        "D-333": ("1.4배", "15%p", "Fraction", "합산", "범위", "문장·문단을 모아서", "평균의 평균이 아니다", "기준은 넷이고"),
        "D-334": ("카나리", "__traceback__", "CONTENT_INVALID", "8글자", "문자열 칸 0", "except", "service/context", "파이썬은 문자열을 메모리에서 즉시 지울 수 없어"),
        "D-335": ("세대 번호", "Tab", "760", "94%", "test_ui_qt_settings", "저장 단추·체크 칸·확인창이 없고", "초록·주황"),
        "D-336": ("선형", "512자", "2초", "병적 입력", "3.12", "3.10"),
        "D-337": ("변이", "원복", "test_ui_qt_style", "test_content_style_stats", "PastedTextTest", "해시"),
        "D-338": ("하지 않은 것", "오차가 큰 입력", "안내가 없는 한계", "Dr.", "필요"),
        "D-339": ("N-3b", "프로필 통합", "진입점", "차이 기준", "붙여 넣기", "운영자가 확인할 기본값"),
    }
    WRITING_PLACES = "**화면에서 파일에 쓰는 곳은 `블로그 관리`(이 항목)·`Seed 관리`·`주제 후보`(아래 두 항목)와 `설정` 의 키 넣기(§8 — 키 원문은 자격 증명 관리자에, 비밀이 아닌 값은 `connections.json` 에) 네 곳이다**"
    SECTIONS = {
        "docs/UI_STATES.md": "## 5-6c. 내 글 문체 참고값 보기 대화상자의 상태 (N-3a)",
        "docs/UI_DESIGN_SPEC.md": "## 4-8. 내 글 문체 참고값 보기(N-3a",
        "docs/UI_COMPONENTS.md": "## 3-7. 내 글 문체 참고값 보기 부품 (N-3a",
        "docs/UI_VISUAL_QA.md": "## 10-9. 내 글 문체 참고값 보기",
    }
    SECTION_WORDS = {
        "docs/UI_STATES.md": ("`select`", "`running`", "`result`", "저장 단추·체크 칸·확인창이 없다", "알 수 없음", "범위만 보여 드려요", "다른 글로 다시 하기"),
        "docs/UI_DESIGN_SPEC.md": ("760px", "94%", "`열기`", "저장·적용·복사 단추는 없다", "알 수 없음", "초록·주황은 쓰지 않는다", "문체 참고값 표"),
        "docs/UI_COMPONENTS.md": ("style_entry_card", "PasteBox", "StyleDialog", "StyleStudy", "ServiceStyleProvider", "Tab 순서", "setTabChangesFocus"),
        "docs/UI_VISUAL_QA.md": ("--only style", "병합 조건 증명", "카나리", "변이 점검", "images/ui/1366x768_100_style_picked.png"),
    }

    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def section(self, rel):
        lines = self.read(rel).splitlines()
        start = [number for number, line in enumerate(lines) if line.startswith(self.SECTIONS[rel])]
        self.assertEqual(len(start), 1, f"{rel}: 이 묶음의 절은 정확히 하나다")
        end = next((number for number in range(start[0] + 1, len(lines)) if lines[number].startswith("## ")), len(lines))
        return "\n".join(lines[start[0]:end])

    def test_each_decision_row_of_this_bundle_exists_once_in_order_and_carries_its_own_words(self):
        text = self.read("docs/DECISIONS.md")
        positions = []
        for number, words in self.ROW_WORDS.items():
            found = [line for line in text.splitlines() if line.startswith(f"| {number} |")]
            self.assertEqual(len(found), 1, f"{number} 행은 정확히 한 줄이어야 한다")
            row = found[0]
            positions.append(text.index(f"| {number} |"))
            self.assertEqual(len(row.split("|")), 6, f"{number}: 표의 한 행은 칸이 다섯이어야 한다")
            self.assertTrue(row.startswith(f"| {number} | 2026-11-11 | **"), number)
            for word in words:
                self.assertIn(word, row, f"{number} 행에 '{word}' 가 없다")
            self.assertNotIn(TILDE, row, number)
            self.assertNotRegex(row, r"(?i)(https?|ftp)://|www[.]", number)
            self.assertNotIn("@@", row, number)
        self.assertEqual(positions, sorted(positions), "행은 번호 순서로 있어야 한다")

    def test_the_security_doc_keeps_the_sentence_about_where_the_screens_write_and_adds_a_reading_only_bullet(self):
        lines = self.read("docs/SECURITY.md").splitlines()
        writing = [number for number, line in enumerate(lines) if line.startswith("- **화면에서 파일에 쓰는 곳은")]
        self.assertEqual(len(writing), 1)
        self.assertIn(self.WRITING_PLACES, lines[writing[0]], "쓰는 곳 목록은 이 묶음이 바꾸지 않는다")
        for word in ("문체", "N-3a", "style_stats"):
            self.assertNotIn(word, lines[writing[0]], "이 묶음의 화면은 쓰는 곳에 들어가지 않는다")
        mine = [number for number, line in enumerate(lines) if line.startswith("- **내 글 문체 참고값 보기(N-3a")]
        self.assertEqual(len(mine), 1)
        self.assertGreater(mine[0], writing[0])
        bullet = lines[mine[0]]
        for word in ("저장 0", "AI 0", "네트워크 0", "D-330–D-339", "check_pasted_text", "카나리", "naver_profiles", "channel_profiles.json", "CONTENT_INVALID", "읽기만 한다"):
            self.assertIn(word, bullet, word)
        self.assertNotIn(TILDE, bullet)
        self.assertNotRegex(bullet, r"(?i)(https?|ftp)://|www[.]")

    def test_the_architecture_lines_come_after_the_cautions_of_the_reading_base_and_the_module_table_names_the_module(self):
        lines = self.read("docs/ARCHITECTURE.md").splitlines()
        module = next(number for number, line in enumerate(lines) if line.startswith("- **기존 글 읽기 기반**(") and "own_posts.py" in line)
        caution = next(number for number, line in enumerate(lines) if line.startswith("  이 읽기 길을 쓰는 N-3a 가 조심할 점 여덟"))
        self.assertEqual(caution, module + 1, "이 묶음의 줄을 모듈 줄과 조심할 점 줄 사이에 끼우지 않았다")
        mine = [number for number, line in enumerate(lines) if line.startswith("- **내 글 문체 참고값 보기**(")]
        self.assertEqual(len(mine), 1)
        following = next(number for number in range(caution + 1, len(lines)) if lines[number].startswith("- **하지 않는 것**"))
        self.assertTrue(caution < mine[0] < following, "조심할 점 줄 뒤, 다음 항목 앞에 있다")
        for word in ("D-330–D-339", "style_stats.py", "check_pasted_text", "StyleStudy", "저장 없음", "StyleStats"):
            self.assertIn(word, lines[mine[0]], word)
        screen = [line for line in lines if line.startswith("- **내 글 문체 참고값 보기(D-330–D-339)**")]
        self.assertEqual(len(screen), 1)
        for word in ("PasteBox", "StyleDialog", "ServiceStyleProvider", "세대 번호", "760px"):
            self.assertIn(word, screen[0], word)
        table = [line for line in lines if line.startswith("| `content/` |")]
        self.assertEqual(len(table), 1)
        self.assertIn("style_stats.py", table[0])
        for line in (lines[mine[0]], screen[0]):
            self.assertNotIn(TILDE, line)
            self.assertNotRegex(line, r"(?i)(https?|ftp)://|www[.]")

    def test_the_changelog_names_the_bundle(self):
        lines = [line for line in self.read("CHANGELOG.md").splitlines() if "style_stats.py" in line]
        self.assertEqual(len(lines), 1)
        for word in ("D-330–D-339", "check_pasted_text", "CONTENT_INVALID", "저장 0", "AI 0", "네트워크 0", "T1", "1.4배", "원복 해시"):
            self.assertIn(word, lines[0], word)
        self.assertNotIn(TILDE, lines[0])
        self.assertNotRegex(lines[0], r"(?i)(https?|ftp)://|www[.]")
        self.assertNotIn("@@", lines[0])

    def test_the_four_ui_docs_each_have_one_section_with_its_words_no_tilde_no_web_address_and_real_photos(self):
        for rel in self.SECTIONS:
            with self.subTest(doc=rel):
                section = self.section(rel)
                for word in self.SECTION_WORDS[rel]:
                    self.assertIn(word, section, word)
                self.assertNotIn(TILDE, section)
                self.assertNotRegex(section, r"(?i)(https?|ftp)://|www[.]")
                self.assertNotIn("@@", section)
        photos = re.findall(r"\(images/ui/([^)]+[.]png)\)", self.section("docs/UI_VISUAL_QA.md"))
        self.assertGreaterEqual(len(photos), 3, "새 사진이 둘에서 셋 넘게 있다")
        for name in photos:
            self.assertTrue((ROOT / "docs" / "images" / "ui" / name).is_file(), name)

    def test_no_unfilled_placeholder_is_left_in_any_changed_doc(self):
        for rel in ("docs/DECISIONS.md", "docs/SECURITY.md", "docs/ARCHITECTURE.md", "docs/UI_STATES.md", "docs/UI_DESIGN_SPEC.md", "docs/UI_COMPONENTS.md", "docs/UI_VISUAL_QA.md", "CHANGELOG.md"):
            self.assertNotIn("@@", self.read(rel), rel)


class FixDocsTest(unittest.TestCase):
    """N3AFIX(독립 검증 낮은 지적 수정)의 문서 — 결정 행 D-430–D-439·UI 문서의 끝 줄·열 머리·한계 표·바꾼 사진의 형식·변경 이력. **이 묶음 자신의 행·줄·사진만** 못박는다(다른 묶음의 결정 번호나 번호의 최댓값은 못박지 않는다 — 다음 묶음이 행을 더해도 이 시험은 깨지지 않는다)."""
    ROW_WORDS = {
        "D-430": ("N3AFIX", "wrap_unstable", "1,539", "127", "45–65%", "line_mode", "오탐", "ShortSentenceSweepTest", "972"),
        "D-431": ("…나요", "…ㄴ가요", "물음표", "D-331", "한계", "…니까", "안가요"),
        "D-432": ("style_rough", "KnownLimitsTest", "밑줄 제목", "들여쓴 코드", "참조식 링크 정의", "* * *", "ㅎㅎ", "한국식 불릿", "해석.", "D-338", "문장 나누기와 문장 끝은"),
        "D-433": ("아니다", "_label_only", "Q.", "ㅎㅎ", "D-432", "FAQ"),
        "D-434": ("style_yours_result", "붙여 넣음", "StyleOutcome.pasted", "style_col_one_pasted", "900×560", "style_trust"),
        "D-435": ("192색", "팔레트", "LANCZOS", "MEDIANCUT", "그림 견주기", "306장", "픽셀까지 같", "make_palette_photos"),
        "D-436": ("D7", "_INVISIBLE_CLASS", "D6", "D9", "N-3b", "diff 0"),
        "D-437": ("변이", "원복", "해시", "새 시험", "test_content_style_stats", "test_ui_style_core", "test_ui_qt_style", "회귀", "3.10"),
        "D-438": ("ENDING_TABLE", "1 → 0", "기존 시험", "D-431"),
        "D-439": ("N-3b", "병합 순서", "충돌", "ui_capture.py", "운영자가 확인할 기본값", "되돌리"),
    }
    PHOTOS = (
        "1366x768_100_keys_cards.png", "1366x768_100_keys_nostore.png", "1366x768_100_keys_real.png", "1366x768_100_settings_all.png", "1366x768_100_settings_real.png", "1366x768_100_settings_usage.png",
        "1920x1080_100_keys_cards.png", "1920x1080_100_settings_all.png", "1920x1080_125_settings_usage.png",
        "1366x768_100_style_picked.png", "1366x768_100_style_result_min.png", "1920x1080_125_style_result_two.png", "1920x1080_125_style_result_range.png",
        "1920x1080_125_style_result_pasted.png", "1366x768_100_style_result_pasted_min_bottom.png",
    )
    NEW_PHOTOS = ("1920x1080_125_style_result_pasted.png", "1366x768_100_style_result_pasted_min_bottom.png")
    LIMIT_WORDS = ("밑줄 제목", "들여쓴 코드", "링크 정의", "공백 낀 가로줄", "점 목록", "밑줄 기울임", "ㅎㅎ", "한국식 불릿", "굵은 라벨", "…나요")

    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def section(self, rel, start):
        lines = self.read(rel).splitlines()
        first = [number for number, line in enumerate(lines) if line.startswith(start)]
        self.assertEqual(len(first), 1, f"{rel}: {start} 절은 정확히 하나다")
        end = next((number for number in range(first[0] + 1, len(lines)) if lines[number].startswith("## ")), len(lines))
        return "\n".join(lines[first[0]:end])

    def test_each_decision_row_of_this_fix_exists_once_in_order_inside_the_table_and_carries_its_own_words(self):
        text = self.read("docs/DECISIONS.md")
        lines = text.splitlines()
        positions = []
        for number, words in self.ROW_WORDS.items():
            found = [line for line in lines if line.startswith(f"| {number} |")]
            self.assertEqual(len(found), 1, f"{number} 행은 정확히 한 줄이어야 한다")
            row = found[0]
            positions.append(text.index(f"| {number} |"))
            self.assertEqual(len(row.split("|")), 6, f"{number}: 표의 한 행은 칸이 다섯이어야 한다")
            self.assertTrue(row.startswith(f"| {number} | 2026-11-11 | **"), number)
            for word in words:
                self.assertIn(word, row, f"{number} 행에 '{word}' 가 없다")
            self.assertNotIn(TILDE, row, number)
            self.assertNotRegex(row, r"(?i)(https?|ftp)://|www[.]", number)
            self.assertNotIn("@@", row, number)
        self.assertEqual(positions, sorted(positions), "행은 번호 순서로 있어야 한다")
        first = lines.index(next(line for line in lines if line.startswith("| D-430 |")))
        self.assertTrue(lines[first - 1].startswith("| D-"), "이 묶음의 첫 행은 결정 표 안(다른 결정 행 바로 뒤)에 있다 — 문서 끝에 새 표를 덧붙이지 않았다")

    def test_the_user_doc_lists_every_limit_the_known_limits_test_pins_with_its_numbers(self):
        section = self.section("docs/UI_STATES.md", "## 5-6c. 내 글 문체 참고값 보기 대화상자의 상태 (N-3a)")
        self.assertIn("알려 둔 한계 — 화면이 따로 안내하지 않는 것", section)
        self.assertIn("KnownLimitsTest", section)
        table = [line for line in section.splitlines() if line.startswith("| ") and "흔들리는 숫자" not in line and "---" not in line and "→" in line and "입력 모양" not in line]
        self.assertGreaterEqual(len(table), 10, "한계 표의 줄은 열 줄 이상이다")
        for word in self.LIMIT_WORDS:
            self.assertTrue(any(word in line for line in table), f"한계 표에 '{word}' 줄이 없다")
        for line in table:
            self.assertEqual(len(line.split("|")), 5, f"한계 표의 한 줄은 칸이 셋이다: {line[:30]}")
        for fixed in ("…아니다", "Q.", "A."):
            self.assertIn(fixed, section.split("**알려 둔 한계")[1], "고친 둘은 표에서 빠졌다고 적었다")

    def test_the_other_ui_docs_name_the_new_result_lines_and_the_pasted_header(self):
        states = self.section("docs/UI_STATES.md", "## 5-6c. 내 글 문체 참고값 보기 대화상자의 상태 (N-3a)")
        spec = self.section("docs/UI_DESIGN_SPEC.md", "## 4-8. 내 글 문체 참고값 보기(N-3a")
        for section in (states, spec):
            for word in ("직접 쓴 글만 골랐을 때의 숫자예요", "문장 나누기와 문장 끝은 글자 모양만 보고 세는 규칙이라", "글 2 (붙여 넣음)"):
                self.assertIn(word, section, word)
            self.assertNotIn(TILDE, section)
            self.assertNotRegex(section, r"(?i)(https?|ftp)://|www[.]")
        self.assertIn("줄바꿈 습관(줄마다 한 문장으로 읽었는데 문장 중간에서 끝난 줄이 섞인 글도 켜진다)", states)

    def test_the_changed_and_new_photos_are_palette_pngs_no_wider_than_a_thousand_pixels_and_the_new_ones_are_in_the_doc(self):
        for name in self.PHOTOS:
            with self.subTest(photo=name):
                head = (ROOT / "docs" / "images" / "ui" / name).read_bytes()[:26]
                self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n", name)
                width, depth, color_type = int.from_bytes(head[16:20], "big"), head[24], head[25]
                self.assertEqual(color_type, 3, f"{name}: 기존 사진과 같은 팔레트(색 형식 3)여야 한다")
                self.assertLessEqual(depth, 8, name)
                self.assertLessEqual(width, 1000, name)
        quality = self.section("docs/UI_VISUAL_QA.md", "## 10-9. 내 글 문체 참고값 보기")
        for name in self.NEW_PHOTOS:
            self.assertIn(f"(images/ui/{name})", quality, name)
        self.assertIn("N3AFIX", quality)

    def test_the_changelog_names_the_fix(self):
        lines = [line for line in self.read("CHANGELOG.md").splitlines() if "N3AFIX" in line]
        self.assertEqual(len(lines), 1)
        for word in ("D-430–D-439", "127 → 0", "붙여 넣음", "192색", "T1", "원복 해시", "…나요"):
            self.assertIn(word, lines[0], word)
        self.assertNotIn(TILDE, lines[0])
        self.assertNotRegex(lines[0], r"(?i)(https?|ftp)://|www[.]")
        self.assertNotIn("@@", lines[0])
        self.assertNotIn("style_stats.py", lines[0], "N-3a 변경 이력 줄이 이 파일 이름을 가진 유일한 줄이다")

    def test_no_unfilled_placeholder_is_left_in_the_rows_lines_and_block_this_fix_wrote(self):
        mine = [line for line in self.read("docs/DECISIONS.md").splitlines() if re.match(r"\| D-43\d \|", line)]
        mine += [line for line in self.read("CHANGELOG.md").splitlines() if "N3AFIX" in line]
        mine.append(self.section("docs/UI_VISUAL_QA.md", "## 10-9. 내 글 문체 참고값 보기").split("**N3AFIX 보완")[1])
        self.assertEqual(len(mine), 12, "결정 행 열 + 변경 이력 한 줄 + 보완 블록 하나")
        for text in mine:
            for bad in ("{{", "}}", "{f[", "측정 중", "@@"):
                self.assertNotIn(bad, text, bad)


if __name__ == "__main__":
    unittest.main()
