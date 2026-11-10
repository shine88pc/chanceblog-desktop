"""'글 모양 점검' 규칙의 기준값·글자 모음·정규식 조각·예외 한 곳마다, 그 한 곳만 바꾸면 결과가 달라지는 예문을 하나씩 못박는다(기존 `test_check_claims_mutants` 방식). 변이 점검(사본에서 소스 한 곳씩 바꿔 시험을 돌린다)이 모두 잡히도록 만들었고,
처음 한 바퀴에서 살아남은 변이마다 이 파일에 예문을 더했다. 번호(M01 …)는 변이 점검 표와 같다. 네트워크·파일 없이 돈다.

원칙: 한 예문에는 그 기준 하나만 이유가 되게 했다 — 같은 뜻의 다른 낱말이 함께 있으면 하나를 바꿔도 결과가 같아 변이를 놓친다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import garbage_samples as S  # noqa: E402

from chanceblog_desktop.check import garbage as g  # noqa: E402


def n(text, kind, **options):
    return len(S.found(text, kind, **options))


class ThresholdTest(unittest.TestCase):
    def test_M01_korean_repeat_threshold_is_three(self):
        self.assertEqual((n("좋아요 좋아요", "dup_word"), n("좋아요 좋아요 좋아요", "dup_word"), n("좋아요 좋아요 좋아요 좋아요", "dup_word")), (0, 1, 1))

    def test_M02_english_repeat_threshold_is_two_and_a_single_word_is_not_a_repeat(self):
        self.assertEqual((n("good", "dup_word"), n("good good", "dup_word"), n("good good good", "dup_word")), (0, 1, 1))

    def test_M03_a_two_letter_english_word_counts_and_a_one_letter_word_does_not(self):
        self.assertEqual((n("go go", "dup_word"), n("a a", "dup_word"), n("가 가 가", "dup_word")), (1, 0, 0))

    def test_M04_sentence_key_threshold_is_ten(self):
        ten, nine, eleven = "가나다라마바사아자차.", "가나다라마바사아자.", "가나다라마바사아자차카."
        self.assertEqual([n(S.lines(sentence, "다른 줄이에요 정말요", sentence), "dup_sentence") for sentence in (nine, ten, eleven)], [0, 1, 1])

    def test_M05_code_span_limit_is_two_hundred(self):
        for inside, wanted in ((199, 0), (200, 0), (201, 1), (202, 1)):
            with self.subTest(inside):
                text = S.TICK + "&nbsp;" + "x" * (inside - 6) + S.TICK
                self.assertEqual(n(text, "entity"), wanted)

    def test_M06_a_block_mark_is_three_ticks_or_more(self):
        self.assertEqual((n(S.TICK * 2 + "\n코드\n" + S.TICK * 2, "fence"), n(S.fenced("코드"), "fence"), n(S.fenced("코드", marker=S.TICK * 5), "fence")), (0, 1, 1))

    def test_M07_the_indent_limit_is_three_spaces(self):
        self.assertEqual([n(" " * indent + S.TICK * 3 + "\n코드", "fence") for indent in (0, 2, 3, 4)], [1, 1, 1, 0])

    def test_M08_the_flag_tag_distance_is_seven_characters_between(self):
        for between, wanted in ((0, 0), (7, 0), (8, 1), (9, 1)):
            with self.subTest(between):
                self.assertEqual(n(S.BLACK_FLAG + "가" * between + S.TAG_G, "invisible"), wanted)

    def test_M09_the_largest_entity_number_is_a_plane_end(self):
        self.assertEqual((n("&#1114111;", "entity"), n("&#1114112;", "entity"), n("&#x10FFFF;", "entity"), n("&#x110000;", "entity")), (1, 0, 1, 0))

    def test_M10_an_entity_name_must_be_in_the_html_table_and_end_with_a_semicolon(self):
        self.assertEqual((n("&nbsp;", "entity"), n("&nbsp", "entity"), n("&abcd;", "entity"), n("&Aacute;", "entity")), (1, 0, 0, 1))
        self.assertEqual((n("&alpha;", "entity"), n("&hearts;", "entity"), n("&alpha", "entity")), (1, 1, 0), "옛 꼴(세미콜론 없는 이름)이 따로 없는 이름도 이름표에 있다")

    def test_M11_zero_is_not_an_entity_number_and_one_is(self):
        self.assertEqual((n("&#0;", "entity"), n("&#1;", "entity"), n("&#x0;", "entity"), n("&#x1;", "entity")), (0, 1, 0, 1))

    def test_M12_placeholder_inner_limits(self):
        for limit_text, wanted in (("{{" + "x" * 80 + "}}", 1), ("{{" + "x" * 81 + "}}", 0), ("{%" + "x" * 80 + "%}", 1), ("{%" + "x" * 81 + "%}", 0), ("{#" + "x" * 80 + "#}", 1), ("{#" + "x" * 81 + "#}", 0),
                                   ("${" + "x" * 60 + "}", 1), ("${" + "x" * 61 + "}", 0), ("{" + "x" * 40 + "}", 1), ("{" + "x" * 41 + "}", 0), ("{a:" + "x" * 20 + "/b}", 1), ("{a:" + "x" * 21 + "/b}", 0),
                                   ("{a:b/" + "x" * 20 + "}", 1), ("{a:b/" + "x" * 21 + "}", 0)):
            with self.subTest(limit_text[:12] + str(len(limit_text))):
                self.assertEqual(n(limit_text, "placeholder"), wanted)

    def test_M13_bracket_word_tails_have_limits(self):
        for text, wanted in (("[대상" + " " + "x" * 19 + "]", 1), ("[대상" + " " + "x" * 20 + "]", 0), ("[여기에 " + "x" * 19 + "]", 1), ("[여기에 " + "x" * 20 + "]", 0), ("[입력" + "x" * 10 + "]", 1), ("[입력" + "x" * 11 + "]", 0),
                             ("[삽입" + "x" * 10 + "]", 1), ("[삽입" + "x" * 11 + "]", 0), ("[your " + "x" * 20 + "]", 1), ("[your " + "x" * 21 + "]", 0), ("[insert " + "x" * 20 + "]", 1), ("[insert " + "x" * 21 + "]", 0)):
            with self.subTest(text):
                self.assertEqual(n(text, "placeholder"), wanted)

    def test_M14_the_text_limit_is_one_hundred_thousand_characters(self):
        self.assertEqual((g.scan("", "가" * 100_000).skipped, g.scan("", "가" * 100_001).skipped, g.scan("가" * 100_000, "").skipped, g.scan("가" * 100_001, "").skipped), (False, True, False, True))


class CharacterSetTest(unittest.TestCase):
    def test_M15_every_edge_of_the_invisible_set_is_in_and_the_neighbours_are_out(self):
        inside = (0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x180B, 0x180E, 0x200B, 0x200C, 0x200F, 0x2060, 0x2064, 0x206A, 0x206F, 0x3164, 0xFE00, 0xFE0F, 0xFEFF, 0xFFA0, 0xE0001, 0xE0020, 0xE007F)
        outside = (0x00AC, 0x00AE, 0x034E, 0x0350, 0x061B, 0x061D, 0x115E, 0x1161, 0x180A, 0x180F, 0x200A, 0x2010, 0x205F, 0x2065, 0x2066, 0x2069, 0x2069, 0x3163, 0x3165, 0xFDFF, 0xFE10, 0xFEFE, 0xFF00, 0xFF9F, 0xFFA1, 0xE0000, 0xE0002, 0xE001F, 0xE0080)
        for code in inside:
            with self.subTest(hex(code), where="in"):
                text = "안" + chr(code) + "녕"
                self.assertEqual([item.sub for item in S.found(text, "invisible")], [f"U+{code:04X}"])
        for code in outside:
            with self.subTest(hex(code), where="out"):
                self.assertEqual(S.found("안" + chr(code) + "녕", "invisible"), [])

    def test_M16_every_control_edge_is_in_and_tab_line_breaks_and_the_neighbours_are_out(self):
        inside = (0x00, 0x08, 0x0B, 0x0C, 0x0E, 0x1F, 0x7F, 0x80, 0x9F)
        outside = (0x09, 0x0A, 0x0D, 0x20, 0x7E, 0xA0)
        for code in inside:
            with self.subTest(hex(code), where="in"):
                self.assertEqual(n("a" + chr(code) + "b", "control"), 1)
        for code in outside:
            with self.subTest(hex(code), where="out"):
                self.assertEqual(n("a" + chr(code) + "b", "control"), 0)

    def test_M17_private_use_nonchar_and_surrogate_edges(self):
        for code, sub in ((0xE000, "private_use"), (0xF8FF, "private_use"), (0xFDD0, "noncharacter"), (0xFDEF, "noncharacter"), (0xFFFE, "noncharacter"), (0xFFFF, "noncharacter"), (0xD800, "noncharacter"), (0xDFFF, "noncharacter"), (0xFFFD, "replacement")):
            with self.subTest(hex(code)):
                self.assertEqual([item.sub for item in S.found("가" + chr(code) + "나", "broken")], [sub])
        for code in (0xF900, 0xFDCF, 0xFDF0, 0xFFFB, 0xFFFC, 0xD7FF):
            with self.subTest(hex(code), where="out"):
                self.assertEqual(S.found("가" + chr(code) + "나", "broken"), [])

    def test_M18_every_jamo_block_makes_a_run_and_one_jamo_next_to_a_neighbour_block_does_not(self):
        for low, high in ((0x1100, 0x11FF), (0xA960, 0xA97F), (0xD7B0, 0xD7FF)):
            with self.subTest(hex(low)):
                self.assertEqual(n("가" + chr(low) + chr(high) + "나", "broken"), 1)
        for before, after in ((0x10FF, 0x1100), (0x11FF, 0x1200), (0xA95F, 0xA960), (0xA97F, 0xA980), (0xD7AF, 0xD7B0)):
            with self.subTest((hex(before), hex(after)), where="out"):
                self.assertEqual(n(chr(before) + chr(after), "broken"), 0)

    def test_M19_each_of_the_four_mojibake_shapes_is_needed(self):
        for label, sample, wanted in (("ã", "x" + chr(0xC3) + chr(0xA9), 1), ("â", "x" + chr(0xC2) + chr(0xA0), 1), ("quote", "x" + chr(0xE2) + chr(0x20AC) + chr(0x201C), 1), ("quote2", "x" + chr(0xE2) + chr(0x20AC) + chr(0x00A6), 1),
                                      ("korean", "x" + chr(0xEA) + chr(0xB0) + chr(0x20AC), 1), ("korean2", "x" + chr(0xEB) + chr(0x82) + chr(0x02DC), 1), ("korean3", "x" + chr(0xEC) + chr(0x2022) + chr(0x02C6), 1), ("korean4", "x" + chr(0xED) + chr(0x0152) + chr(0x0178), 1),
                                      ("fffd", "x" + chr(0xEF) + chr(0xBF) + chr(0xBD), 1), ("single tail", "x" + chr(0xEA) + chr(0xB0), 0), ("letter tail", "x" + chr(0xEA) + "ab", 0), ("capital a alone", "x" + chr(0xC3) + "a", 0), ("quote without euro", "x" + chr(0xE2) + chr(0x201C), 0)):
            with self.subTest(label):
                self.assertEqual(n(sample, "broken"), wanted)

    def test_M20_every_emoji_range_and_code_lets_a_joiner_pass(self):
        for code in (0x1F600, 0x2194, 0x231A, 0x24C2, 0x2764, 0x2934, 0x2B50, 0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299, 0x20E3, 0x1F3FB):
            with self.subTest(hex(code)):
                emoji = chr(code)
                self.assertEqual(S.found(emoji + S.ZWJ + emoji, "invisible"), [])
        for code in (0x218F, 0x2200, 0x22FF, 0x2400, 0x245F, 0x2500, 0x259F, 0x27C0, 0x28FF, 0x2980, 0x2AFF, 0x2C00, 0x1EFFF, 0x1FB00):
            with self.subTest(hex(code), where="out"):
                self.assertEqual(n(chr(code) + S.ZWJ + chr(code), "invisible"), 1)

    def test_M21_a_wordish_neighbour_is_ascii_letters_digits_hangul_or_han(self):
        for char, wanted in (("a", 1), ("Z", 1), ("0", 1), ("9", 1), ("가", 1), ("힣", 1), (chr(0x1100), 1), (chr(0x3131), 1), (chr(0x4E00), 1), (chr(0x9FFF), 1), (chr(0x3400), 1), (chr(0x4DBF), 1), (chr(0x0645), 0), ("-", 0), (" ", 0), (chr(0xABFF), 0), (chr(0xD7A4), 0)):
            with self.subTest(hex(ord(char))):
                self.assertEqual(n(char + S.ZWNJ + chr(0x0645), "invisible"), wanted)


class RuleShapeTest(unittest.TestCase):
    def test_M22_a_joiner_needs_an_emoji_on_both_sides(self):
        emoji = chr(0x1F468)
        self.assertEqual((n(emoji + S.ZWJ + emoji, "invisible"), n(emoji + S.ZWJ + "x", "invisible"), n("x" + S.ZWJ + emoji, "invisible")), (0, 1, 1))

    def test_M23_a_variation_selector_after_a_digit_a_hash_or_a_star_or_an_emoji_is_normal(self):
        self.assertEqual([n(prefix + S.VS16, "invisible") for prefix in ("5", "#", "*", chr(0x2764), chr(0x00A9), "a", "가", "")], [0, 0, 0, 0, 0, 1, 1, 1])

    def test_M24_a_tag_character_is_normal_only_after_the_black_flag(self):
        self.assertEqual((n(S.FLAG_SCOTLAND, "invisible"), n(chr(0x1F3F3) + S.TAG_G, "invisible"), n(S.TAG_G, "invisible")), (0, 1, 1))

    def test_M25_a_non_joiner_is_normal_when_neither_neighbour_is_wordish_and_not_when_either_is(self):
        arabic = chr(0x0645)
        self.assertEqual((n(arabic + S.ZWNJ + arabic, "invisible"), n("a" + S.ZWNJ + arabic, "invisible"), n(arabic + S.ZWNJ + "a", "invisible"), n(S.ZWNJ + arabic, "invisible"), n(arabic + S.ZWNJ, "invisible")), (0, 1, 1, 0, 0))

    def test_M26_a_closing_block_mark_must_be_as_long_and_bare_and_a_tilde_block_must_be_paired(self):
        self.assertEqual((n(S.fenced("{{x}}"), "placeholder"), n(S.TICK * 4 + "\n{{x}}\n" + S.TICK * 3, "placeholder"), n(S.TICK * 3 + "\n{{x}}\n" + S.TICK * 3 + "x", "placeholder"), n(S.TICK * 3 + "\n{{x}}\n" + S.TICK * 4, "placeholder")), (0, 1, 1, 0))
        self.assertEqual((n(S.TICK * 3 + "\n{{x}}\n" + S.TILDE * 3, "placeholder"), n(S.TILDE * 3 + "\n{{x}}\n" + S.TICK * 3, "placeholder")), (1, 1), "열고 닫는 글자가 다르면 짝이 아니다")

    def test_M27_only_a_backtick_line_with_no_other_backtick_after_the_mark_is_a_block_mark(self):
        self.assertEqual((n(S.TICK * 3 + "x\ny", "fence"), n(S.TICK * 3 + "x" + S.TICK + "\ny", "fence"), n(S.TICK * 3 + " " + S.TICK * 3, "fence")), (1, 0, 0))

    def test_M28_a_quote_line_has_at_most_three_spaces_of_indent(self):
        self.assertEqual([n(" " * indent + "> {{a}}", "placeholder") for indent in (0, 3, 4, 5)], [0, 0, 1, 1])

    def test_M29_a_quote_mark_must_be_first_on_the_line(self):
        self.assertEqual((n("글 > {{a}}", "placeholder"), n(">{{a}}", "placeholder")), (1, 0))

    def test_M30_touching_spots_of_one_kind_are_both_kept_and_overlapping_ones_are_merged(self):
        self.assertEqual((n("{{a}}{{b}}", "placeholder"), n("{{{a}}}", "placeholder"), n("${x}", "placeholder")), (2, 1, 1))

    def test_M31_an_adjacent_repeat_comes_first_and_only_a_following_sentence_makes_one(self):
        first, second = "첫째 문장은 이렇게 길어요 정말로.", "둘째 문장은 저렇게 길어요 정말로."
        text = S.lines(first, second, first, "", second, second)
        items = S.found(text, "dup_sentence")
        self.assertEqual([(item.adjacent, S.caught(text, item)[0]) for item in items], [(True, second), (False, first)])

    def test_M32_the_fingerprint_of_a_repeat_follows_its_length_and_ignores_case(self):
        three, four = S.found("A b c\n\nThe the the", "dup_word"), S.found("the the the the", "dup_word")
        self.assertNotEqual(three[0].fingerprint, four[0].fingerprint)
        self.assertEqual(S.found("THE the the", "dup_word")[0].fingerprint, three[0].fingerprint)

    def test_M33_a_blank_line_with_only_spaces_or_invisible_characters_ends_a_repeat(self):
        for gap in ("\n\n", "\n \n", "\n" + S.TAB + "\n", "\r\n\r\n", "\r\r"):
            with self.subTest(repr(gap)):
                self.assertEqual(n("좋아요 좋아요" + gap + "좋아요", "dup_word"), 0)
        self.assertEqual(n("좋아요 좋아요\n좋아요", "dup_word"), 1)

    def test_M34_the_marks_around_a_word_are_stripped_but_inner_marks_are_kept(self):
        """D-323 — 옛 단언 `*좋아요* [좋아요] 좋아요?!` 는 대괄호를 건너뛰며 1건이었다. 대괄호가 낱말 사이에 끼면 끊기게 바뀌어 같은 뜻(바깥 기호 무시)을 대괄호 없는 모양으로 남기고, 대괄호가 끼면 0건이라는 새 단언을 더했다."""
        self.assertEqual((n("*좋아요* \"좋아요\" 좋아요?!", "dup_word"), n("좋-아요 좋.아요 좋_아요", "dup_word")), (1, 0))
        self.assertEqual(n("*좋아요* [좋아요] 좋아요?!", "dup_word"), 0, "여는·닫는 대괄호가 낱말 사이에 끼면 끊긴다")
        self.assertEqual(n("좋아요! 좋아요! 좋아요!", "dup_word"), 0)

    def test_M35_numbers_with_separators_and_jamo_only_words_are_not_repeats(self):
        self.assertEqual([n(word + " " + word + " " + word, "dup_word") for word in ("12,345", "1.5", "007", "ㅎㅎㅎ", "ㅠㅠ", "ab12", "한글12")], [0, 0, 0, 0, 0, 1, 1])

    def test_M36_the_sentence_key_ignores_invisible_characters_case_width_and_marks(self):
        base = "Hello World Again Today."
        fullwidth = "".join(chr(code) for code in (0xFF28, 0xFF45, 0xFF4C, 0xFF4C, 0xFF4F))
        for variant in ("hello world again today.", "Hello" + S.ZWSP + " World Again Today.", "Hello" + S.FILL + " World Again Today.", "He" + chr(0xFFA0) + "llo World" + S.BOM + " Again Today.", fullwidth + " World Again Today.", "HELLO, WORLD; AGAIN, TODAY!",
                        "Hello World Again Today" + chr(0xFF01)):
            with self.subTest(variant):
                self.assertEqual(n(base + "\n\n" + variant, "dup_sentence"), 1)

    def test_M37_every_sentence_end_and_every_closing_mark_ends_a_sentence(self):
        sentence = "정말 그렇게 생각하세요"
        for end in ("?", "!", ".", S.ELLIPSIS, S.IDEOGRAPHIC_STOP, chr(0xFF01), chr(0xFF1F)):
            for closer in ("", '"', "'", ")", "]", chr(0x201D), chr(0x2019), chr(0x300D), chr(0x300F)):
                with self.subTest(end + closer):
                    self.assertEqual(n(sentence + end + closer + " " + sentence + end + closer, "dup_sentence"), 1)

    def test_M38_a_dot_inside_a_number_does_not_end_a_sentence(self):
        text = "버전은 3.5 에서 4.0 으로 올랐어요. 버전은 3.5 에서 4.0 으로 올랐어요."
        self.assertEqual(n(text, "dup_sentence"), 1)
        self.assertEqual(len(g.sentence_spans("값은 3.5 입니다")), 1)

    def test_M39_a_line_of_only_invisible_characters_is_a_blank_line_for_positions(self):
        self.assertEqual(g.locate("가\n" + S.ZWSP + "\n나", 2), (1, 0, 1))
        self.assertEqual(g.locate("가\n \n나", 2), (1, 0, 1))
        self.assertEqual(g.locate("가\n-\n나", 2), (1, 2, 1))

    def test_M40_the_title_is_scanned_for_everything_but_sentences(self):
        sentence = "같은 문장이 두 번 나와요 정말로."
        self.assertEqual(S.found("", "dup_sentence", title=sentence + " " + sentence), [])
        for text, kind in ((S.ZWSP, "invisible"), (S.FFFD, "broken"), (S.ESC, "control"), ("&nbsp;", "entity"), ("{{a}}", "placeholder"), (" 좋아요 좋아요 좋아요", "dup_word")):
            with self.subTest(kind):
                self.assertEqual(n("본문", kind, title="제목" + text), 1)

    def test_M41_the_places_of_one_group_are_ordered_by_field_first_and_then_by_position(self):
        items = S.found(S.ZWSP + "본문", "invisible", title="제목입니다" + S.ZWSP)
        self.assertEqual(items[0].spans, (("title", 5, 6), ("body", 0, 1)))


class NewCodeTest(unittest.TestCase):
    """N2FIX(D-322–D-324)로 더한 코드 한 곳마다의 변이 killer."""

    def test_M42_a_long_sentence_keeps_its_key_whole_across_the_pieces_and_a_second_piece_is_normalized_too(self):
        plain = "".join(chr(0x61 + index % 26) for index in range(2000))
        self.assertEqual(g.sentence_key(plain), plain, "조각 경계에서 글자가 빠지거나 겹치지 않는다")
        fullwidth_tail = plain[:1000] + "".join(chr(ord(char) + 0xFEE0) for char in plain[1000:])
        self.assertEqual(g.sentence_key(fullwidth_tail), plain, "둘째 조각 뒤의 호환 문자도 풀린다")
        self.assertEqual(g.sentence_key(plain[:-1] + "Z"), plain[:-1] + "z", "마지막 조각의 글자도 키에 든다")
        self.assertEqual(g.sentence_key(""), "")

    def test_M43_the_pieces_are_exactly_five_hundred_twelve_characters(self):
        """조각 경계가 결합 글자와 글자 사이에 걸치면 그 한 쌍은 합쳐지지 않는다(같은 문장을 못 알아보는 쪽일 뿐 거짓 경고는 없다). 경계의 위치로 조각 크기를 못박는다 — 한 칸만 달라도 이 둘 중 하나가 깨진다."""
        accent = "e" + chr(0x0301)
        precomposed = chr(0xE9)
        straddled, aligned = "x" + accent * 600, "xy" + accent * 600
        self.assertNotEqual(g.sentence_key(straddled), g.sentence_key("x" + precomposed * 600), "경계가 쌍을 가르면 합쳐지지 않는다")
        self.assertEqual(g.sentence_key(aligned), g.sentence_key("xy" + precomposed * 600), "경계가 쌍 사이에 있으면 합쳐진다")
        self.assertEqual(g.NFKC_CHUNK, 512)

    def test_M44_a_hundred_thousand_chars_of_a_slow_normalizing_letter_end_within_the_limit(self):
        import time
        for char in (chr(0x0F73), chr(0xFDFA)):
            with self.subTest(char=f"U+{ord(char):04X}"):
                start = time.perf_counter()
                self.assertEqual(g.sentence_key(char * 100_000)[:1], g.sentence_key(char)[:1])
                self.assertLess(time.perf_counter() - start, 2.0)

    def test_M45_a_broken_fingerprint_is_the_sub_kind_and_the_sorted_set_of_the_caught_characters(self):
        one = S.found(chr(0xE000) + chr(0xE001), "broken")[0]
        again = S.found(chr(0xE001) + chr(0xE001) + chr(0xE000), "broken")[0]
        other = S.found(chr(0xE000), "broken")[0]
        self.assertEqual(one.fingerprint, again.fingerprint)
        self.assertNotEqual(one.fingerprint, other.fingerprint)
        self.assertTrue(one.fingerprint.startswith("broken:"))

    def test_M46_only_a_tilde_line_with_no_more_tildes_after_the_mark_can_open_a_block(self):
        self.assertEqual((n(S.TILDE * 3 + "\n{{x}}\n" + S.TILDE * 3, "placeholder"), n(S.TILDE * 3 + "a" + S.TILDE + "\n{{x}}\n" + S.TILDE * 3, "placeholder"), n(S.TILDE * 3 + "a\n{{x}}\n" + S.TILDE * 3, "placeholder")), (0, 1, 0))
        self.assertEqual(n(S.TICK * 3 + "a" + S.TILDE + "\n{{x}}\n" + S.TICK * 3, "placeholder"), 0, "물결 규칙은 역따옴표 줄에 번지지 않는다")

    def test_M47_the_skip_set_has_the_emphasis_marks_the_quotes_and_the_invisible_characters(self):
        for char in "*_" + S.TILDE + S.TICK + "\"'":
            self.assertIn(char, g._RUN_SKIP, f"U+{ord(char):04X}")
        for code in (0x2018, 0x2019, 0x201C, 0x201D, 0xAB, 0xBB, 0x2039, 0x203A, 0x200B, 0xFEFF, 0x00AD, 0x3164, 0xE0020):
            self.assertIn(chr(code), g._RUN_SKIP, f"U+{code:04X}")
        self.assertEqual(g._INVISIBLE_CHARS.count(chr(0x200B)), 1)
        self.assertEqual(len(g._INVISIBLE_CHARS), len(set(g._INVISIBLE_CHARS)))

    def test_M48_the_chars_helper_expands_numbers_and_ranges_into_one_string(self):
        self.assertEqual(g._chars(0x61, (0x62, 0x64), 0x7A), "abcdz")
        self.assertEqual(g._chars((0x31, 0x31)), "1")


if __name__ == "__main__":
    unittest.main()
