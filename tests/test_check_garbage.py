"""'글 모양 점검' 규칙(`check/garbage.py`, N-2) 시험 — 일곱 항목마다 걸리는 예·거르는 예·경계값, 위치 계산(빈 줄 여러 개·CRLF·앞 빈 줄), 겹침 합치기, 지문 안정성, 결과에 원문이 없음, 긴 글 상한, 순수함(소스).

원칙: 규칙의 결과에는 걸린 글이 없으므로 걸린 글은 위치(구간)로 원문을 다시 잘라 견준다(`garbage_samples.caught`). 눈에 안 보이는 글자는 코드 숫자로 만든 이름 상수만 쓴다. 네트워크·파일 없이 돈다(CI 와 같은 조건).
"""
import ast
import dataclasses
import random
import re
import sys
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import garbage_samples as S  # noqa: E402
from draft_samples import CONTROL, DAILY, NORMAL_MORE  # noqa: E402

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.check import garbage as g  # noqa: E402
from chanceblog_desktop.security import shape  # noqa: E402

SOURCES = ROOT / "src" / "chanceblog_desktop"


class BrokenCharsTest(unittest.TestCase):
    def test_replacement_characters_are_caught_and_a_run_is_one_finding(self):
        text = "안녕" + S.FFFD + "하세요 " + S.FFFD * 3 + " 끝"
        items = S.found(text, "broken")
        self.assertEqual([(item.sub, S.caught(text, item)) for item in items], [("replacement", [S.FFFD]), ("replacement", [S.FFFD * 3])])

    def test_korean_text_read_with_the_wrong_table_is_one_mojibake_run(self):
        text = "앞 " + S.MOJIBAKE_KO + " 뒤"
        items = S.found(text, "broken")
        self.assertEqual([(item.sub, S.caught(text, item)) for item in items], [("mojibake", [S.MOJIBAKE_KO])])

    def test_the_accent_the_quote_and_the_replacement_shapes_are_caught(self):
        for label, sample in (("accent", S.MOJIBAKE_ACCENT), ("quote", "그가 말했다 " + S.MOJIBAKE_QUOTE + " 그리고"), ("replacement", "값 " + S.MOJIBAKE_FFFD)):
            with self.subTest(label):
                self.assertEqual([item.sub for item in S.found(sample, "broken")], ["mojibake"])

    def test_precomposed_accents_symbols_and_compat_jamo_are_not_broken(self):
        for sample in ("café와 señor, façade 에서 만났어요", "forêt, être, naïve, Noël", "ㅎㅎ 그래요 ㅠㅠ", "5°C 4×4 ±3 © ® ½ □ ■ ▶ ✔", "NÃO é uma palavra", "ÂA e ÃO"):
            with self.subTest(sample):
                self.assertEqual(S.found(sample, "broken"), [])

    def test_private_use_characters_are_caught_as_a_run(self):
        text = "옛한글 " + S.PUA + chr(0xE0BD) + " 글자 " + chr(0xF8FF)
        items = S.found(text, "broken")
        self.assertEqual([(item.sub, len(S.caught(text, item)[0])) for item in items], [("private_use", 2), ("private_use", 1)])

    def test_noncharacters_and_lone_surrogates_are_caught(self):
        text = "가" + S.NONCHAR + "나" + chr(0xFDD0) + "다" + S.SURROGATE + "라"
        self.assertEqual([item.sub for item in S.found(text, "broken")], ["noncharacter"] * 3)

    def test_separated_hangul_jamo_need_two_in_a_row(self):
        text = "문서 " + S.NFD_HANGUL
        items = S.found(text, "broken")
        self.assertEqual([(item.sub, S.caught(text, item)) for item in items], [("jamo_run", [S.NFD_HANGUL])])
        self.assertEqual(S.found("가" + chr(0x1100) + "나", "broken"), [], "낱개 자모가 하나뿐이면 아니다")
        self.assertEqual(S.found(chr(0x1100) + " " + chr(0x1161), "broken"), [], "붙어 있지 않으면 아니다")
        self.assertEqual(len(S.found(chr(0x1100) + chr(0x1161), "broken")), 1, "둘이 붙으면 건다")

    def test_every_broken_finding_of_one_sub_kind_shares_a_fingerprint(self):
        first = S.found("가" + S.FFFD + "나", "broken")[0].fingerprint
        second = S.found("다" + S.FFFD * 4 + "라", "broken")[0].fingerprint
        self.assertEqual(first, second, "같은 글자(대체 문자)는 몇 개가 이어졌든 한 번에 무시한다")
        self.assertNotEqual(first, S.found("가" + S.PUA + "나", "broken")[0].fingerprint)

    def test_the_same_characters_share_a_fingerprint_wherever_they_are_and_other_characters_do_not(self):
        """D-324(D7) — 지문 = 하위 종류 + 걸린 글자들. 옛 동작은 하위 종류 이름뿐이라 서로 다른 모지바케·사용자 정의 영역 글자가 한 지문이었다(`무시` 한 번에 같이 숨었다)."""
        fingerprint = lambda text: S.found(text, "broken")[0].fingerprint  # noqa: E731
        self.assertEqual(fingerprint(chr(0xE000) + chr(0xE001)), fingerprint("가" + chr(0xE001) + chr(0xE000) + chr(0xE000) + "나"), "글자 모음이 같으면 순서·개수와 상관없이 같다")
        self.assertNotEqual(fingerprint("가" + chr(0xE000) + "나"), fingerprint("가" + chr(0xE001) + "나"), "다른 사용자 정의 영역 글자는 다른 지문이다")
        self.assertNotEqual(fingerprint(S.MOJIBAKE_KO), fingerprint(S.MOJIBAKE_ACCENT), "다른 잘못 읽힌 글은 다른 지문이다")
        self.assertEqual(fingerprint(S.MOJIBAKE_ACCENT), fingerprint("뒤에 " + S.MOJIBAKE_ACCENT + S.MOJIBAKE_ACCENT[3:]), "같은 잘못 읽힌 글은 같은 지문이다")
        self.assertNotEqual(fingerprint(chr(0xFFFF)), fingerprint(chr(0xFDD0)), "다른 글자가 아닌 코드는 다른 지문이다")
        self.assertNotEqual(fingerprint(chr(0x1112) + chr(0x1161)), fingerprint(chr(0x1100) + chr(0x1161)), "다른 낱개 자모 이음은 다른 지문이다")
        self.assertNotEqual(fingerprint(S.FFFD), fingerprint(S.MOJIBAKE_FFFD), "하위 종류가 다르면 같은 글자여도 다른 지문이다")

    def test_the_title_is_scanned_with_the_same_rules(self):
        items = S.found("본문", "broken", title="제목" + S.FFFD)
        self.assertEqual([(item.spans[0][0], item.spans[0][1]) for item in items], [("title", 2)])


class InvisibleCharsTest(unittest.TestCase):
    def test_every_listed_character_is_caught_in_a_plain_korean_context(self):
        for name, char in (("zwsp", S.ZWSP), ("zwnj", S.ZWNJ), ("zwj", S.ZWJ), ("word joiner", S.WJ), ("bom", S.BOM), ("soft hyphen", S.SHY), ("filler", S.FILL), ("lrm", S.LRM), ("rlm", S.RLM),
                           ("variation selector", S.VS16), ("text variation selector", S.VS15), ("tag begin", S.TAG_BEGIN), ("mongolian", chr(0x180B)), ("deprecated format", chr(0x206A)), ("halfwidth filler", chr(0xFFA0)),
                           ("jungseong filler", chr(0x1160)), ("choseong filler", chr(0x115F)), ("function application", chr(0x2061)), ("combining grapheme joiner", chr(0x034F)), ("arabic letter mark", chr(0x061C))):
            with self.subTest(name):
                text = "안녕" + char + "하세요"
                items = S.found(text, "invisible")
                self.assertEqual([(item.sub, S.caught(text, item)) for item in items], [(f"U+{ord(char):04X}", [char])])

    def test_the_same_character_is_one_finding_with_every_place(self):
        text = "가" + S.ZWSP * 3 + "나\n\n다" + S.ZWSP + "라"
        items = S.found(text, "invisible")
        self.assertEqual(len(items), 1)
        self.assertEqual([item for item in items[0].spans], [("body", 1, 2), ("body", 2, 3), ("body", 3, 4), ("body", 8, 9)])

    def test_two_different_characters_are_two_findings_in_reading_order(self):
        text = "가" + S.BOM + "나" + S.ZWSP + "다" + S.BOM
        items = S.found(text, "invisible")
        self.assertEqual([item.sub for item in items], ["U+FEFF", "U+200B"])
        self.assertEqual(len(items[0].spans), 2)

    def test_the_family_emoji_joiner_is_normal_and_a_joiner_between_letters_is_not(self):
        self.assertEqual(S.found("가족 " + S.FAMILY + " 사진", "invisible"), [])
        self.assertEqual(len(S.found("a" + S.ZWJ + "b", "invisible")), 1)
        self.assertEqual(len(S.found(S.FAMILY[:2] + S.ZWJ + "x", "invisible")), 1, "뒤가 이모지가 아니면 건다")
        self.assertEqual(len(S.found("x" + S.ZWJ + S.FAMILY[:1], "invisible")), 1, "앞이 이모지가 아니면 건다")

    def test_a_heart_and_a_keycap_variation_selector_are_normal(self):
        self.assertEqual(S.found("사랑 " + S.HEART + " 해요 " + S.KEYCAP + " 번 5" + S.VS16, "invisible"), [])
        self.assertEqual(S.found("#" + S.VS16 + " " + "*" + S.VS16, "invisible"), [])
        self.assertEqual(S.found(chr(0x00A9) + S.VS15, "invisible"), [], "텍스트 모양 선택자도 같다")

    def test_a_variation_selector_after_hangul_or_at_the_start_is_caught(self):
        self.assertEqual(len(S.found("안녕" + S.VS16 + "하세요", "invisible")), 1)
        self.assertEqual(len(S.found(S.VS16 + "첫 글자", "invisible")), 1, "글 맨 앞은 앞 글자가 없으니 정상 문맥이 아니다")
        self.assertEqual(len(S.found("a" + S.VS16, "invisible")), 1)

    def test_a_flag_tag_sequence_is_normal_and_loose_tag_characters_are_not(self):
        self.assertEqual(S.found(S.FLAG_SCOTLAND, "invisible"), [])
        self.assertEqual(len(S.found("가" + S.TAG_G + "나", "invisible")), 1)
        self.assertEqual(len(S.found(S.BLACK_FLAG + "가나다라마바사아자" + S.TAG_CANCEL, "invisible")), 1, "깃발에서 8글자보다 멀면 건다")
        self.assertEqual(len(S.found("가" + S.TAG_BEGIN, "invisible")), 1, "태그 시작은 깃발과 상관없이 건다")

    def test_a_non_joiner_is_normal_only_away_from_korean_english_digits_and_han(self):
        self.assertEqual(S.found("글자 " + S.PERSIAN + " 이에요", "invisible"), [])
        for neighbors in (("안", "녕"), ("a", "b"), ("1", "2"), (chr(0x4E2D), chr(0x6587)), ("가", chr(0x06CC)), (chr(0x0645), "나")):
            with self.subTest(neighbors):
                self.assertEqual(len(S.found(neighbors[0] + S.ZWNJ + neighbors[1], "invisible")), 1)

    def test_a_character_alone_in_a_line_is_found_with_its_place(self):
        text = "첫 문단\n\n" + S.FILL + "\n다음"
        items = S.found(text, "invisible")
        self.assertEqual([(item.sub, item.spans[0]) for item in items], [("U+3164", ("body", 6, 7))])

    def test_the_title_is_scanned_and_the_spans_name_their_field(self):
        items = S.found("본문" + S.ZWSP, "invisible", title="제" + S.ZWSP + "목")
        self.assertEqual(items[0].spans, (("title", 1, 2), ("body", 2, 3)))

    def test_the_characters_of_a_plan_example_are_not_flagged_in_plain_text(self):
        for sample in S.NORMAL_TEXTS:
            with self.subTest(sample[:20]):
                self.assertEqual(S.found(sample, "invisible"), [])


class ControlCharsTest(unittest.TestCase):
    def test_control_characters_other_than_tab_and_line_breaks_are_caught(self):
        for char in (S.NUL, S.ESC, S.FF, S.DEL, S.NEL, chr(0x0B), chr(0x07), chr(0x1F), chr(0x9F)):
            with self.subTest(hex(ord(char))):
                text = "앞" + char + "뒤"
                items = S.found(text, "control")
                self.assertEqual([(item.sub, S.caught(text, item)) for item in items], [(f"U+{ord(char):04X}", [char])])

    def test_tabs_line_breaks_and_windows_line_breaks_are_normal(self):
        for sample in ("항목" + S.TAB + "값", "줄\n줄", "줄\r\n줄\r\n", "줄\r줄", "표" + S.TAB + "복사" + S.TAB + "본"):
            with self.subTest(repr(sample)):
                self.assertEqual(S.found(sample, "control"), [])

    def test_a_written_out_escape_is_an_ordinary_text(self):
        self.assertEqual(S.found("글자 " + S.BACKSLASH + "x1b 는 이스케이프예요 " + S.BACKSLASH + "u0000", "control"), [])

    def test_a_run_of_the_same_control_character_is_one_finding(self):
        text = "가" + S.ESC * 3 + "나"
        items = S.found(text, "control")
        self.assertEqual([item.spans for item in items], [(("body", 1, 4),)])

    def test_different_adjacent_control_characters_are_separate(self):
        self.assertEqual(len(S.found("가" + S.ESC + chr(0x07) + "나", "control")), 2)

    def test_the_fingerprint_is_per_character(self):
        first, second = S.found("가" + S.ESC + "나" + S.NUL, "control")
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(S.found("다" + S.ESC, "control")[0].fingerprint, first.fingerprint)


class EntityTest(unittest.TestCase):
    def test_named_decimal_and_hex_entities_are_caught(self):
        for sample, sub, wanted in (("가격&nbsp;12,000원", "named", "&nbsp;"), ("a&amp;b", "named", "&amp;"), ("&lt;p&gt;", "named", "&lt;"), ("&#160;", "numeric", "&#160;"), ("&#xA0;", "numeric", "&#xA0;"), ("&#X41;", "numeric", "&#X41;")):
            with self.subTest(sample):
                items = S.found(sample, "entity")
                self.assertEqual(items[0].sub, sub)
                self.assertEqual(S.caught(sample, items[0]), [wanted])

    def test_an_address_with_an_encoded_ampersand_is_caught(self):
        text = "example.test/a?x=1&amp;y=2"
        self.assertEqual([S.caught(text, item) for item in S.found(text, "entity")], [["&amp;"]])

    def test_an_ampersand_without_a_semicolon_or_with_an_unknown_name_is_normal(self):
        for sample in ("example.test/a?x=1&y=2&lang=ko", "R&D 와 AT&T, Q&A 코너", "&abc; 는 없는 이름", "&#0; 은 없는 번호", "&#1114112; 는 너무 큰 번호", "&#x110000;", "&#12345678;", "& 와 &; 와 &#;", "&a;"):
            with self.subTest(sample):
                self.assertEqual(S.found(sample, "entity"), [])

    def test_the_largest_valid_number_is_caught(self):
        self.assertEqual(len(S.found("&#1114111; &#x10FFFF; &#1;", "entity")), 3)

    def test_entities_inside_code_regions_are_not_checked(self):
        self.assertEqual(S.found("HTML 에서 " + S.TICK + "&nbsp;" + S.TICK + " 는 공백이에요", "entity"), [])
        self.assertEqual(S.found(S.fenced("&nbsp; 공백", "&amp;"), "entity"), [])
        self.assertEqual(S.found("> 인용 안의 &nbsp; 설명", "entity"), [])

    def test_an_entity_in_plain_quotes_is_still_caught(self):
        self.assertEqual(len(S.found("HTML 에서 '&nbsp;' 는 공백이에요", "entity")), 1)

    def test_entities_next_to_but_outside_a_code_region_are_caught(self):
        text = "&nbsp; " + S.TICK + "&nbsp;" + S.TICK + " &amp;"
        self.assertEqual([S.caught(text, item) for item in S.found(text, "entity")], [["&nbsp;"], ["&amp;"]])

    def test_every_occurrence_is_its_own_finding_with_one_shared_fingerprint(self):
        items = S.found("a&nbsp;b&nbsp;c&nbsp;d", "entity")
        self.assertEqual(len(items), 3)
        self.assertEqual(len({item.fingerprint for item in items}), 1)


class FenceTest(unittest.TestCase):
    def test_a_code_block_is_reported_as_one_finding_with_both_marker_lines(self):
        text = S.fenced("print(1)", info="python")
        items = S.found(text, "fence")
        self.assertEqual([(item.sub, S.caught(text, item)) for item in items], [("backtick", [S.TICK * 3, S.TICK * 3])])

    def test_marker_lines_of_several_blocks_are_grouped_into_one_finding(self):
        text = S.lines(S.fenced("a"), "사이 글", S.fenced("b", marker=S.TICK * 4))
        items = S.found(text, "fence")
        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0].spans), 4)

    def test_up_to_three_spaces_of_indent_are_allowed_and_four_are_not(self):
        self.assertEqual(len(S.found("   " + S.TICK * 3 + "\n코드\n   " + S.TICK * 3, "fence")[0].spans), 2)
        self.assertEqual(S.found("    " + S.TICK * 3 + "\n코드", "fence"), [])

    def test_three_ticks_inside_a_sentence_or_on_one_line_are_not_a_block_mark(self):
        for sample in ("문장 속 " + S.TICK * 3 + " 역따옴표", S.TICK * 3 + " 한 줄 코드 " + S.TICK * 3, "끝에 " + S.TICK * 3):
            with self.subTest(sample):
                self.assertEqual(S.found(sample, "fence"), [])

    def test_two_ticks_are_not_a_block_mark(self):
        self.assertEqual(S.found(S.TICK * 2 + "\n코드\n" + S.TICK * 2, "fence"), [])

    def test_a_tilde_block_counts_only_when_it_is_paired(self):
        paired = S.fenced("코드", marker=S.TILDE * 3)
        self.assertEqual([item.sub for item in S.found(paired, "fence")], ["tilde"])
        self.assertEqual(S.found(S.TILDE * 3 + "\n코드 끝", "fence"), [], "닫는 줄이 없으면 건다 하지 않는다")

    def test_a_tilde_decoration_line_and_a_trailing_tilde_are_normal(self):
        decorated = S.TILDE * 3 + " 오늘의 일기 " + S.TILDE * 3 + "\n본문"
        self.assertEqual(S.found(decorated, "fence"), [])
        self.assertEqual(S.found("정말 좋아요" + S.TILDE * 3, "fence"), [])
        self.assertEqual(S.found("좋아요\n" + S.TILDE * 6 + "\n다음", "fence"), [])

    def test_a_closing_mark_needs_to_be_as_long_as_the_opening_one_and_bare(self):
        short = S.TICK * 4 + "\n{{x}}\n" + S.TICK * 3
        self.assertEqual(len(S.found(short, "placeholder")), 1, "짧은 닫는 줄은 닫지 못해 블록이 아니다")
        talky = S.TICK * 3 + "\n{{x}}\n" + S.TICK * 3 + " 끝"
        self.assertEqual(len(S.found(talky, "placeholder")), 1, "뒤에 글이 붙은 줄은 닫는 줄이 아니다")
        self.assertEqual(S.found(S.TICK * 3 + "\n{{x}}\n" + S.TICK * 4, "placeholder"), [], "더 긴 닫는 줄은 닫는다")

    def test_an_unclosed_block_does_not_hide_what_follows_but_its_mark_is_still_reported(self):
        text = S.TICK * 3 + "\n{{x}}"
        self.assertEqual(len(S.found(text, "fence")), 1)
        self.assertEqual(len(S.found(text, "placeholder")), 1)

    def test_a_tilde_line_with_more_tildes_after_the_mark_is_a_decoration_and_never_opens_a_block(self):
        """D-324(D6) — '물결 세 개 + 일기 + 물결 세 개' 는 장식 줄이다(역따옴표 줄의 '같은 줄에 역따옴표가 더 있으면 표시가 아니다' 와 같은 규칙). 뒤의 맨 물결 줄과 짝이 되어 코드 블록으로 걸리던 옛 동작을 고쳤다."""
        decorated = S.TILDE * 3 + " 오늘의 일기 " + S.TILDE * 3 + "\n본문 {{이름}}\n" + S.TILDE * 6
        self.assertEqual(S.found(decorated, "fence"), [])
        self.assertEqual(len(S.found(decorated, "placeholder")), 1, "코드 영역이 아니라서 사이의 자리표시도 걸린다")
        self.assertEqual(S.found(S.TILDE * 3 + "x" + S.TILDE + "\n본문\n" + S.TILDE * 3, "fence"), [], "뒤쪽에 물결이 하나만 더 있어도 장식 줄이다")

    def test_two_bare_tilde_lines_still_make_a_code_block_a_known_limit(self):
        """한계(D-320): 맨 물결 줄 둘 사이의 글은 마크다운 규칙대로 코드 블록으로 본다 — 구분선으로 쓴 경우는 오탐이고 `무시` 로 푼다(경고뿐)."""
        text = S.TILDE * 6 + "\n본문 한 줄 {{x}}\n" + S.TILDE * 6
        self.assertEqual([item.sub for item in S.found(text, "fence")], ["tilde"])
        self.assertEqual(S.found(text, "placeholder"), [], "코드 영역으로 보니 사이의 자리표시는 걸리지 않는다")

    def test_a_stray_fence_line_pairs_with_the_closing_line_of_a_real_block_and_hides_what_is_between_a_known_limit(self):
        """한계(D-320): 실수로 친 울타리 한 줄은 뒤의 진짜 블록의 닫는 줄과 짝이 되어 그 사이의 자리표시를 가린다(마크다운도 같다) — 코드 블록 표시 자체는 알린다."""
        text = S.TICK * 3 + "\n{{가운데}}\n" + S.fenced("코드", info="python") + "\n{{뒤}}"
        self.assertEqual(len(S.found(text, "fence")), 1)
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["{{뒤}}"]])


class PlaceholderTest(unittest.TestCase):
    def test_every_placeholder_shape_is_caught_with_its_own_sub_kind(self):
        for sample, sub in (("안녕 {{name}} 님", "double_brace"), ("{% if a %}x{% endif %}", "percent_brace"), ("{# 메모 #}", "hash_brace"), ("총 ${price} 원", "dollar_brace"), ("오늘의 주제는 {topic} 예요", "brace"),
                            ("{tone:으로/로} 씁니다", "brace"), ("{주제}", "brace"), ("[이름] 님", "bracket")):
            with self.subTest(sample):
                items = S.found(sample, "placeholder")
                self.assertEqual(items[0].sub, sub)

    def test_the_listed_bracket_words_are_caught_and_the_others_are_not(self):
        for word in ("이름", "제목", "내용", "대상", "대상 독자", "키워드", "주제", "링크", "여기에 입력", "입력 필요", "삽입 이미지", "TODO", "todo", "Todo", "Your Name", "your name", "Insert link"):
            with self.subTest(word):
                self.assertEqual(len(S.found("앞 [" + word + "] 뒤", "placeholder")), 1)
        for word in ("리뷰", "광고", "협찬", "이미지 1", "공지", "속보", "그림"):
            with self.subTest(word):
                self.assertEqual(S.found("[" + word + "] 글", "placeholder"), [])

    def test_two_rules_that_find_the_same_spot_are_counted_once(self):
        text = "안녕 {{이름}} 님"
        items = S.found(text, "placeholder")
        self.assertEqual([(item.sub, S.caught(text, item)) for item in items], [("double_brace", ["{{이름}}"])])

    def test_the_dollar_form_swallows_the_inner_brace_form(self):
        text = "총 ${price} 원"
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["${price}"]])

    def test_anonymous_marks_and_page_markers_are_normal(self):
        self.assertEqual(S.found("OO병원에서 ○○ 씨를 만났어요 [이미지 1] [리뷰]", "placeholder"), [])

    def test_a_placeholder_inside_a_code_region_is_not_checked(self):
        self.assertEqual(S.found("템플릿은 " + S.TICK + "{{ title }}" + S.TICK + " 처럼 써요", "placeholder"), [])
        self.assertEqual(S.found(S.fenced("{{ title }}", "{% x %}"), "placeholder"), [])
        self.assertEqual(S.found("> [이름] 님께 드립니다", "placeholder"), [])

    def test_an_unclosed_opening_is_normal(self):
        self.assertEqual(S.found("{{ 열림만 있어요 {% 이것도 ${ 그리고 {# 도", "placeholder"), [])

    def test_the_double_brace_limit_is_eighty_characters_inside(self):
        self.assertEqual(len(S.found("{{" + "x" * 80 + "}}", "placeholder")), 1)
        self.assertEqual(S.found("{{" + "x" * 81 + "}}", "placeholder"), [])

    def test_the_single_brace_word_limit_is_forty_characters(self):
        self.assertEqual(len(S.found("{" + "a" * 40 + "}", "placeholder")), 1)
        self.assertEqual(S.found("{" + "a" * 41 + "}", "placeholder"), [])

    def test_a_placeholder_does_not_cross_a_line_break(self):
        self.assertEqual(S.found("{{ 가\n나 }}", "placeholder"), [])

    def test_a_set_of_curly_letters_is_caught_and_can_be_ignored(self):
        self.assertEqual(len(S.found("집합 {a} 와 {b}", "placeholder")), 2, "수학 집합도 걸린다 — 경고뿐이라 무시하면 된다")

    def test_every_occurrence_shares_a_fingerprint_with_the_same_text(self):
        items = S.found("{{이름}} 님 {{이름}} 님 {{ 다른 }}", "placeholder")
        self.assertEqual([item.fingerprint == items[0].fingerprint for item in items], [True, True, False])


class DupWordTest(unittest.TestCase):
    def test_three_in_a_row_are_caught_and_two_are_not_for_korean(self):
        text = "좋아요 좋아요 좋아요"
        items = S.found(text, "dup_word")
        self.assertEqual([(item.sub, item.repeats, S.caught(text, item)) for item in items], [("hangul", 3, [text])])
        self.assertEqual(S.found("정말 정말 좋아요", "dup_word"), [])

    def test_two_in_a_row_are_caught_for_english_words(self):
        text = "This is the the best way"
        items = S.found(text, "dup_word")
        self.assertEqual([(item.sub, item.repeats, S.caught(text, item)) for item in items], [("latin", 2, ["the the"])])

    def test_the_comparison_ignores_case_and_surrounding_marks(self):
        """대소문자와 낱말을 감싼 굵은 표시·따옴표는 무시한다. 옛 단언 둘(쉼표·느낌표, 괄호를 건너뛰며 3번)은 D-323 에서 **낱말 사이에 부호·괄호가 끼면 끊긴다** 로 바뀌어 아래 새 단언과 시험으로 옮겼다 — 옛 뜻은 남기고 새 동작을 더했다."""
        self.assertEqual(S.found("THE the The", "dup_word")[0].repeats, 3)
        self.assertEqual(S.found("*좋아요* \"좋아요\" **좋아요**", "dup_word")[0].repeats, 3, "감싼 굵은 표시·따옴표는 건너뛴다(옛 단언의 괄호만 뺀 모양)")
        self.assertEqual(S.found("좋아요 좋아요 좋아요.", "dup_word")[0].repeats, 3, "마지막 낱말 뒤의 부호는 낱말 사이가 아니다")
        self.assertEqual(S.found("좋아요, 좋아요! 좋아요.", "dup_word"), [], "쉼표·느낌표가 끼면 끊긴다(옛 동작은 3번으로 셌다 — 실제 글을 오탐했다)")
        self.assertEqual(S.found("(좋아요) \"좋아요\" **좋아요**", "dup_word"), [], "닫는 괄호가 끼면 끊긴다(옛 동작은 3번으로 셌다)")

    def test_one_letter_words_jamo_digits_and_emoji_are_not_counted(self):
        for sample in ("아 아 아 아 아", "ㅋㅋㅋ ㅋㅋㅋ ㅋㅋㅋ ㅋㅋㅋ", "ㅠㅠ ㅠㅠ ㅠㅠ", "100 100 100 100", "1,000 1,000 1,000", "3.5 3.5 3.5", "a a a a", chr(0x1F600) * 2 + " " + chr(0x1F600) * 2 + " " + chr(0x1F600) * 2, "... ... ..."):
            with self.subTest(sample):
                self.assertEqual(S.found(sample, "dup_word"), [])

    def test_a_blank_line_ends_the_run_and_a_single_line_break_does_not(self):
        self.assertEqual(len(S.found("좋아요 좋아요\n좋아요", "dup_word")), 1)
        self.assertEqual(S.found("좋아요 좋아요\n\n좋아요", "dup_word"), [])
        self.assertEqual(S.found("좋아요 좋아요\r\n\r\n좋아요", "dup_word"), [])
        self.assertEqual(S.found("좋아요 좋아요\n   \n좋아요", "dup_word"), [], "공백뿐인 줄도 빈 줄이다")

    def test_other_words_between_break_the_run(self):
        self.assertEqual(S.found("좋아요 정말 좋아요 정말 좋아요", "dup_word"), [])

    def test_a_long_run_is_one_finding_with_its_count(self):
        text = "좋아요 " * 5
        items = S.found(text, "dup_word")
        self.assertEqual([(item.repeats, S.caught(text, item)) for item in items], [(5, [text.strip()])])

    def test_a_word_mixing_letters_and_digits_needs_three(self):
        self.assertEqual(S.found("mp3 mp3", "dup_word"), [])
        self.assertEqual([item.repeats for item in S.found("mp3 mp3 mp3", "dup_word")], [3])

    def test_invisible_characters_inside_do_not_hide_a_repeat(self):
        text = "좋아요" + S.ZWSP + " 좋아요 좋" + S.ZWNJ + "아요"
        self.assertEqual(S.found(text, "dup_word")[0].repeats, 3)

    def test_the_title_is_checked_and_its_field_is_named(self):
        items = S.found("본문이에요", "dup_word", title="좋아요 좋아요 좋아요 후기")
        self.assertEqual(items[0].spans, (("title", 0, 11),))

    def test_two_runs_of_the_same_length_share_a_fingerprint_and_a_longer_run_does_not(self):
        items = S.found("좋아요 좋아요 좋아요\n\n좋아요 좋아요 좋아요\n\n좋아요 좋아요 좋아요 좋아요", "dup_word")
        self.assertEqual([item.repeats for item in items], [3, 3, 4])
        self.assertEqual(len({item.fingerprint for item in items[:2]}), 1)
        self.assertNotEqual(items[0].fingerprint, items[2].fingerprint)

    def test_the_case_of_the_words_does_not_change_the_fingerprint(self):
        self.assertEqual(S.found("THE the", "dup_word")[0].fingerprint, S.found("the the", "dup_word")[0].fingerprint)

    # ---- D-323: 문장부호·괄호가 낱말 사이에 끼면 같은 낱말을 되풀이한 것이 아니라 문장·목록·인용의 짜임이다(실제 글을 오탐하던 모양) ----
    BREAK_ENDS = ".!?:;," + "".join(chr(code) for code in (0x2026, 0x3001, 0x3002, 0xFF01, 0xFF1F, 0xFF1A, 0xFF1B, 0xFF0C)) + ")]}" + "".join(chr(code) for code in (0xFF09, 0xFF3D, 0xFF5D, 0x300D, 0x300F, 0x300B, 0x3009, 0x3011, 0x3015))
    BREAK_OPENS = "([{" + "".join(chr(code) for code in (0xFF08, 0xFF3B, 0xFF5B, 0x300C, 0x300E, 0x300A, 0x3008, 0x3010, 0x3014))
    WRAPPERS = "*_" + S.TILDE + S.TICK + "\"'" + "".join(chr(code) for code in (0x2018, 0x2019, 0x201C, 0x201D, 0xAB, 0xBB, 0x2039, 0x203A))

    def test_a_sentence_mark_a_comma_or_a_bracket_between_the_words_breaks_the_run(self):
        for sample in ("좋아요, 좋아요! 좋아요.", "(좋아요) \"좋아요\" **좋아요**", "좋아요 좋아요, 좋아요", "No, no, no", "Yes. Yes. Yes.", "very, very quiet", "Sure. Sure, I would go", "wait" + S.ELLIPSIS + " wait" + S.ELLIPSIS + " wait", "Credit: ESA. ESA operates", "Procurement: Procurement of goods"):
            with self.subTest(sample):
                self.assertEqual(S.found(sample, "dup_word"), [])

    def test_the_same_words_without_a_mark_between_are_still_caught(self):
        for sample, repeats in (("No no no", 3), ("Yes Yes", 2), ("very very quiet", 2), ("좋아요 좋아요 좋아요 그리고 좋아요", 3), ("좋아요 좋아요 좋아요, 그리고 좋아요", 3), ("Credit ESA ESA operates", 2)):
            with self.subTest(sample):
                self.assertEqual(S.found(sample, "dup_word")[0].repeats, repeats)

    def test_every_end_mark_and_closing_bracket_after_a_word_breaks_the_run(self):
        for mark in self.BREAK_ENDS:
            with self.subTest(mark=f"U+{ord(mark):04X}"):
                self.assertEqual(S.found("좋아요" + mark + " 좋아요 좋아요", "dup_word"), [])
                self.assertEqual(len(S.found("좋아요 좋아요 좋아요" + mark, "dup_word")), 1, "마지막 낱말 뒤의 부호는 상관없다")

    def test_every_opening_bracket_before_a_word_breaks_the_run(self):
        for mark in self.BREAK_OPENS:
            with self.subTest(mark=f"U+{ord(mark):04X}"):
                self.assertEqual(S.found("좋아요 " + mark + "좋아요 좋아요", "dup_word"), [])
                self.assertEqual(len(S.found(mark + "좋아요 좋아요 좋아요", "dup_word")), 1, "첫 낱말 앞의 여는 괄호는 낱말 사이가 아니다")

    def test_wrappers_alone_do_not_break_the_run_but_do_not_hide_a_mark_behind_them(self):
        for wrapper in self.WRAPPERS:
            with self.subTest(wrapper=f"U+{ord(wrapper):04X}"):
                self.assertEqual(len(S.found("좋아요" + wrapper + " " + wrapper + "좋아요 좋아요", "dup_word")), 1)
                self.assertEqual(S.found("좋아요." + wrapper + " 좋아요 좋아요", "dup_word"), [], "굵은 표시·따옴표 뒤에 숨은 끝 부호도 본다")
                self.assertEqual(S.found("좋아요 " + wrapper + "(좋아요 좋아요", "dup_word"), [], "굵은 표시·따옴표 앞에 숨은 여는 괄호도 본다")

    def test_invisible_characters_do_not_hide_a_mark_and_do_not_make_one(self):
        self.assertEqual(S.found("좋아요." + S.ZWSP + " 좋아요 좋아요", "dup_word"), [])
        self.assertEqual(S.found("좋아요 " + S.ZWSP + "(좋아요 좋아요", "dup_word"), [])
        self.assertEqual(len(S.found("좋아요" + S.ZWSP + " 좋아요 좋아요", "dup_word")), 1)

    def test_the_mark_is_looked_for_after_the_word_right_before_and_every_new_run_starts_at_its_own_word(self):
        self.assertEqual(S.found("좋아요 좋아요, 좋아요", "dup_word"), [], "둘째 낱말 뒤의 쉼표가 셋째와의 이음을 끊는다(앞 낱말은 첫째가 아니라 바로 앞 낱말이다)")
        self.assertEqual(S.found("No, no. no", "dup_word"), [], "끊긴 뒤 새로 시작한 줄기도 자기 낱말의 끝 부호를 따른다")
        self.assertEqual(len(S.found("No no. no no", "dup_word")), 2, "끊기면 앞뒤가 따로 줄기가 된다")


class DupSentenceTest(unittest.TestCase):
    SENTENCE = "사랑해요 영원히 변하지 않을 거예요."

    def test_a_sentence_that_comes_twice_is_one_finding_with_both_places(self):
        text = self.SENTENCE + "\n\n그날을 기억해요.\n\n" + self.SENTENCE
        items = S.found(text, "dup_sentence")
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].repeats, items[0].adjacent, S.caught(text, items[0])), (2, False, [self.SENTENCE, self.SENTENCE]))

    def test_a_sentence_repeated_right_after_itself_is_marked_adjacent_and_comes_first(self):
        other = "여기는 오래된 골목이고 아침마다 빵 냄새가 나요."
        text = S.lines(other, "중간 문장이에요.", other, "", self.SENTENCE, self.SENTENCE)
        items = S.found(text, "dup_sentence")
        self.assertEqual([item.adjacent for item in items], [True, False], "바로 이어진 반복(붙여 넣다 겹친 흔적)을 앞에 둔다")

    def test_ten_letters_and_digits_are_needed(self):
        ten, nine = "가나다라마바사아자차.", "가나다라마바사아자."
        self.assertEqual(len(S.found(S.lines(ten, "다른 줄", ten), "dup_sentence")), 1)
        self.assertEqual(S.found(S.lines(nine, "다른 줄", nine), "dup_sentence"), [])

    def test_spacing_marks_case_and_width_do_not_matter(self):
        text = "Hello World Again Today!\n\n" + "hello,  world again  today" + chr(0xFF01)
        self.assertEqual(len(S.found(text, "dup_sentence")), 1)

    def test_every_sentence_ending_counts(self):
        for end in ("?", "!", S.ELLIPSIS, S.IDEOGRAPHIC_STOP, "."):
            with self.subTest(end):
                sentence = "정말 그렇게 생각하세요" + end
                self.assertEqual(len(S.found(sentence + " " + sentence, "dup_sentence")), 1)

    def test_a_sentence_three_times_is_one_finding(self):
        text = S.lines(self.SENTENCE, "가운데 다른 문장이에요.", self.SENTENCE, "또 다른 문장이 하나 더 있어요.", self.SENTENCE)
        items = S.found(text, "dup_sentence")
        self.assertEqual((len(items), items[0].repeats, len(items[0].spans)), (1, 3, 3))

    def test_two_sentences_on_one_line_are_checked(self):
        self.assertEqual(len(S.found(self.SENTENCE + " " + self.SENTENCE, "dup_sentence")), 1)

    def test_the_title_is_not_compared_with_the_body(self):
        self.assertEqual(S.found(self.SENTENCE, "dup_sentence", title=self.SENTENCE), [])

    def test_invisible_characters_inside_a_sentence_are_ignored(self):
        text = self.SENTENCE + "\n\n" + self.SENTENCE.replace("영원히", "영원" + S.ZWSP + "히")
        self.assertEqual(len(S.found(text, "dup_sentence")), 1)

    def test_different_sentences_are_not_found(self):
        self.assertEqual(S.found("오늘은 맑았어요. 내일은 비가 올 거예요. 모레는 흐려요.", "dup_sentence"), [])

    def test_the_fingerprint_follows_the_normalized_sentence(self):
        english = "Hello World Again Today."
        first = S.found(english + "\n\n" + english, "dup_sentence")[0].fingerprint
        second = S.found("Other one.\n\n" + english.upper() + "\n\n" + english, "dup_sentence")[0].fingerprint
        self.assertEqual(first, second)
        self.assertNotEqual(first, S.found(self.SENTENCE + "\n\n" + self.SENTENCE, "dup_sentence")[0].fingerprint)


class CodeRegionTest(unittest.TestCase):
    def test_placeholders_and_entities_are_not_checked_in_code_but_other_rules_still_are(self):
        text = S.fenced("{{x}} &nbsp; " + S.ZWSP + " " + S.FFFD + " 좋아요 좋아요 좋아요")
        self.assertEqual({item.kind for item in S.found(text)}, {"fence", "invisible", "broken", "dup_word"})

    def test_a_pair_of_ticks_on_one_line_excludes_what_is_between(self):
        text = "앞 {{a}} " + S.TICK + "{{b}}" + S.TICK + " 뒤 {{c}}"
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["{{a}}"], ["{{c}}"]])

    def test_the_code_span_limit_is_two_hundred_characters_inside(self):
        inside_200 = S.TICK + "&nbsp;" + "x" * 194 + S.TICK
        inside_201 = S.TICK + "&nbsp;" + "x" * 195 + S.TICK
        self.assertEqual(len(inside_200) - 2, 200)
        self.assertEqual(S.found(inside_200, "entity"), [])
        self.assertEqual(len(S.found(inside_201, "entity")), 1)

    def test_ticks_must_pair_on_the_same_line_and_with_the_same_length(self):
        self.assertEqual(len(S.found(S.TICK + "&nbsp;\n" + S.TICK, "entity")), 1, "줄을 건너 짝을 짓지 않는다")
        self.assertEqual(len(S.found(S.TICK * 2 + "&nbsp;" + S.TICK, "entity")), 1, "길이가 다르면 짝이 아니다")
        self.assertEqual(S.found(S.TICK * 2 + "&nbsp; " + S.TICK + " " + S.TICK * 2, "entity"), [], "같은 길이끼리 짝이고 사이의 한 개는 글자다")
        self.assertEqual(len(S.found("&nbsp; " + S.TICK + "혼자", "entity")), 1)

    def test_every_pair_of_ticks_in_a_line_is_its_own_region(self):
        text = S.TICK + "{{a}}" + S.TICK + " {{b}} " + S.TICK + "{{c}}" + S.TICK
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["{{b}}"]])

    def test_a_quote_line_excludes_only_that_line(self):
        text = "> 인용 {{a}}\n본문 {{b}}\n  > 들여쓴 인용 {{c}}\n    > 네 칸은 인용이 아니에요 {{d}}"
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["{{b}}"], ["{{d}}"]])

    def test_a_block_excludes_through_its_closing_line_only(self):
        text = S.lines("앞 {{a}}", S.fenced("{{b}}"), "뒤 {{c}}")
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["{{a}}"], ["{{c}}"]])

    def test_a_tilde_block_is_a_code_region_too(self):
        self.assertEqual(S.found(S.fenced("{{b}} &amp;", marker=S.TILDE * 3), "placeholder"), [])

    def test_regions_do_not_swallow_each_other(self):
        text = S.lines(S.fenced("{{a}}"), "> {{b}}", "사이 {{c}}", S.TICK + "{{d}}" + S.TICK)
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["{{c}}"]])


class PositionTest(unittest.TestCase):
    TEXT = "첫 줄\n둘째 줄\n\n\n셋째 문단 첫 줄\n  \n넷째 문단"

    def at(self, text, needle):
        return g.locate(text, text.index(needle))

    def test_a_paragraph_is_a_block_between_blank_lines_and_lines_count_inside_it(self):
        self.assertEqual(self.at(self.TEXT, "첫 줄\n둘"), (1, 1, 1))
        self.assertEqual(self.at(self.TEXT, "둘째"), (1, 2, 1))
        self.assertEqual(self.at(self.TEXT, "줄\n\n\n"), (1, 2, 4))
        self.assertEqual(self.at(self.TEXT, "셋째"), (2, 1, 1))
        self.assertEqual(self.at(self.TEXT, "문단 첫"), (2, 1, 4))
        self.assertEqual(self.at(self.TEXT, "넷째"), (3, 1, 1), "공백뿐인 줄도 빈 줄이다")

    def test_a_hit_on_a_blank_line_has_line_zero_and_the_paragraph_before_it(self):
        self.assertEqual(g.locate(self.TEXT, self.TEXT.index("\n\n\n") + 1), (1, 0, 1))
        self.assertEqual(g.locate(self.TEXT, self.TEXT.index("\n  \n") + 1), (2, 0, 1))
        self.assertEqual(g.locate(self.TEXT, self.TEXT.index("\n  \n") + 2), (2, 0, 2))

    def test_leading_blank_lines_do_not_count_as_a_paragraph(self):
        text = "\n\n본문\n\n끝"
        self.assertEqual(g.locate(text, 0), (0, 0, 1))
        self.assertEqual(self.at(text, "본문"), (1, 1, 1))
        self.assertEqual(self.at(text, "끝"), (2, 1, 1))

    def test_windows_line_breaks_and_lone_carriage_returns_count_as_one_break_each(self):
        crlf = "가\r\n나\r\n\r\n다"
        self.assertEqual([self.at(crlf, ch) for ch in "가나다"], [(1, 1, 1), (1, 2, 1), (2, 1, 1)])
        lone = "가\r나\r\r다"
        self.assertEqual([self.at(lone, ch) for ch in "가나다"], [(1, 1, 1), (1, 2, 1), (2, 1, 1)])

    def test_lines_with_only_invisible_characters_are_blank_lines(self):
        text = "가\n" + S.ZWSP + S.BOM + "\n나"
        self.assertEqual(self.at(text, S.ZWSP), (1, 0, 1))
        self.assertEqual(self.at(text, "나"), (2, 1, 1))

    def test_the_column_counts_characters_in_the_line_from_one(self):
        text = "가나다\n라마바사"
        self.assertEqual([self.at(text, ch)[2] for ch in "가나다라마바사"], [1, 2, 3, 1, 2, 3, 4])

    def test_a_position_past_the_end_stays_in_the_last_line_and_a_negative_one_in_the_first(self):
        self.assertEqual(g.locate("가나\n다라", 99), (1, 2, 97))
        self.assertEqual(g.locate("가나", -5), (1, 1, 1))
        self.assertEqual(g.locate("", 0), (0, 0, 1))

    def test_the_line_index_gives_the_start_of_the_line_of_a_position(self):
        index = g.LineIndex("가나\r\n다라\n마")
        self.assertEqual([index.line_start(i) for i in (0, 1, 4, 5, 7)], [0, 0, 4, 4, 7])

    def test_is_blank_treats_whitespace_and_invisible_characters_alike(self):
        self.assertTrue(g.is_blank(""))
        self.assertTrue(g.is_blank("  " + S.TAB + chr(0x3000) + S.ZWSP))
        self.assertFalse(g.is_blank(" 가 "))
        self.assertFalse(g.is_blank("-"))


class OverlapTest(unittest.TestCase):
    def test_the_longest_of_overlapping_spots_of_one_kind_is_kept(self):
        text = "{{{이름}}}"
        items = S.found(text, "placeholder")
        self.assertEqual(len(items), 1)
        self.assertEqual(S.caught(text, items[0]), ["{{{이름}}"])

    def test_spots_of_different_kinds_are_both_reported(self):
        text = "{{" + S.ZWSP + "이름}}"
        self.assertEqual({item.kind for item in S.found(text)}, {"placeholder", "invisible"})

    def test_touching_spots_are_not_overlapping(self):
        text = "{{a}}{{b}}"
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["{{a}}"], ["{{b}}"]])

    def test_the_order_is_by_kind_then_by_place(self):
        text = "{{a}} " + S.ZWSP + " &nbsp; " + S.FFFD + " " + S.ESC
        self.assertEqual([item.kind for item in S.found(text)], ["broken", "invisible", "control", "entity", "placeholder"])
        self.assertEqual(list(g.KINDS), ["broken", "invisible", "control", "entity", "fence", "placeholder", "dup_word", "dup_sentence"])


class FingerprintTest(unittest.TestCase):
    def test_a_fingerprint_is_the_kind_and_twelve_hex_digits(self):
        for item in S.found("{{a}} &nbsp; " + S.ZWSP):
            with self.subTest(item.kind):
                kind, _colon, digest = item.fingerprint.partition(":")
                self.assertEqual(kind, item.kind)
                self.assertEqual((len(digest), set(digest) <= set("0123456789abcdef")), (12, True))

    def test_the_same_caught_text_has_the_same_fingerprint_wherever_it_is(self):
        first = S.found("앞 {{이름}} 뒤", "placeholder")[0].fingerprint
        self.assertEqual(S.found("전혀 다른 글 속의 {{이름}} 그리고 더", "placeholder")[0].fingerprint, first)
        self.assertEqual(S.found("본문", "placeholder", title="{{이름}}")[0].fingerprint, first)
        self.assertEqual(S.found("{{이름}}", "placeholder")[0].fingerprint, first)

    def test_a_different_caught_text_or_kind_has_a_different_fingerprint(self):
        names = {item.fingerprint for item in S.found("{{a}} {{b}} [이름] {c} " + "&nbsp; &amp; " + S.ZWSP + S.WJ + S.BOM)}
        self.assertEqual(len(names), 9)

    def test_whitespace_inside_a_placeholder_is_normalized(self):
        self.assertEqual(S.found("{{ x }}", "placeholder")[0].fingerprint, S.found("{{  x  }}", "placeholder")[0].fingerprint)
        self.assertNotEqual(S.found("{{ x }}", "placeholder")[0].fingerprint, S.found("{{x}}", "placeholder")[0].fingerprint)

    def test_the_fingerprint_does_not_change_between_calls_or_processes_inputs(self):
        text = "{{a}} " + S.ZWSP + " 좋아요 좋아요 좋아요 &nbsp;"
        self.assertEqual([item.fingerprint for item in S.found(text)], [item.fingerprint for item in S.found(text)])
        for sample, kind, expected in (("{{a}}", "placeholder", "placeholder:041a24ae9b13"), ("a" + S.ZWSP + "b", "invisible", "invisible:a7516923b649"), ("x&nbsp;y", "entity", "entity:05b7690b644c")):
            self.assertEqual(S.found(sample, kind)[0].fingerprint, expected, "해시 방식(소금·SHA-256)이 바뀌면 이 값이 바뀐다 — 프로세스·파이썬 판이 달라도 같아야 한다")

    def test_a_fingerprint_follows_the_kind_and_the_sub_kind(self):
        self.assertNotEqual(g._fingerprint("entity", "named", "x", {}), g._fingerprint("entity", "numeric", "x", {}))
        self.assertNotEqual(g._fingerprint("entity", "named", "x", {}), g._fingerprint("placeholder", "named", "x", {}))


class NoOriginalTextTest(unittest.TestCase):
    MARKER = "고유표지문장은이렇게길다"

    def test_the_report_holds_only_kinds_sub_kinds_fingerprints_field_names_and_numbers(self):
        text = "{{" + self.MARKER + "}} " + self.MARKER + " " + self.MARKER + " " + self.MARKER + "\n\n" + self.MARKER + " 이다." + S.ZWSP + "&nbsp;"
        report = g.scan(self.MARKER, text)
        allowed = set(g.KINDS) | set(g.FIELDS)
        for item in report.findings:
            self.assertEqual(set(dataclasses.asdict(item)), {"kind", "sub", "fingerprint", "spans", "repeats", "adjacent"})
            self.assertTrue(item.fingerprint.startswith(item.kind + ":"))
            self.assertIn(item.kind, allowed)
            self.assertTrue(all(isinstance(field, str) and field in g.FIELDS and isinstance(start, int) and isinstance(end, int) for field, start, end in item.spans))
            self.assertTrue(isinstance(item.repeats, int) and isinstance(item.adjacent, bool))
        flat = repr(report)
        for start in range(0, len(self.MARKER) - 3):
            self.assertNotIn(self.MARKER[start:start + 4], flat, "걸린 글의 조각이 결과에 있다")

    def test_the_findings_are_frozen(self):
        item = S.found("{{a}}", "placeholder")[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.kind = "x"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            g.scan("", "").skipped = True


class LimitTest(unittest.TestCase):
    def test_the_limit_is_the_same_as_the_copy_gate_scan_limit(self):
        self.assertEqual(g.MAX_SCAN_CHARS, shape.MAX_SCAN_CHARS)
        self.assertEqual(g.MAX_SCAN_CHARS, 100_000)

    def test_a_body_of_exactly_the_limit_is_scanned_and_one_more_is_skipped(self):
        body = "가" * (g.MAX_SCAN_CHARS - 6) + " {{a}} "
        self.assertEqual(len(body), g.MAX_SCAN_CHARS + 1)
        self.assertTrue(g.scan("", body).skipped)
        report = g.scan("", body[1:])
        self.assertEqual((report.skipped, [item.kind for item in report.findings]), (False, ["placeholder"]))

    def test_a_skipped_report_has_no_findings(self):
        report = g.scan("제목", "{{a}}" + "가" * g.MAX_SCAN_CHARS)
        self.assertEqual((report.skipped, report.findings), (True, ()))

    def test_a_title_over_the_limit_skips_the_scan_too(self):
        self.assertTrue(g.scan("가" * (g.MAX_SCAN_CHARS + 1), "{{a}}").skipped)
        self.assertFalse(g.scan("가" * g.MAX_SCAN_CHARS, "{{a}}").skipped)

    def test_things_that_are_not_text_count_as_empty(self):
        self.assertEqual(g.scan(None, 5), g.Report())
        self.assertEqual(g.scan("", ""), g.Report())
        self.assertEqual(len(g.scan(None, "{{a}}").findings), 1)


class PurityTest(unittest.TestCase):
    STDLIB = {"hashlib", "re", "unicodedata", "bisect", "dataclasses", "html", "__future__"}
    CALLS = {"open", "print", "exec", "eval", "compile", "input", "__import__"}

    def test_the_rule_module_imports_only_the_standard_library(self):
        tree = ast.parse((SOURCES / "check" / "garbage.py").read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imported - self.STDLIB, set())

    def test_the_rule_module_has_no_file_network_clock_random_or_global_state_calls(self):
        tree = ast.parse((SOURCES / "check" / "garbage.py").read_text(encoding="utf-8"))
        names = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)} | {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertEqual(names & self.CALLS, set())
        source = (SOURCES / "check" / "garbage.py").read_text(encoding="utf-8")
        for word in (r"\btime\.", r"\brandom\b", r"\bsocket\b", r"\burllib\b", r"\bsubprocess\b", r"\bdatetime\b", r"\bos\.", r"\bpathlib\b", r"\bglobal\b", r"\bthreading\b"):
            self.assertIsNone(re.search(word, source), word)

    def test_the_result_does_not_change_the_inputs_and_is_the_same_every_time(self):
        title, body = "제목 {{a}}", "본문 " + S.ZWSP + " 좋아요 좋아요 좋아요\n\n" + DupSentenceTest.SENTENCE + " " + DupSentenceTest.SENTENCE
        before = (title.encode(), body.encode())
        first, second = g.scan(title, body), g.scan(title, body)
        self.assertEqual(first, second)
        self.assertEqual((title.encode(), body.encode()), before)

    def test_no_new_source_file_has_an_invisible_character_a_tilde_or_a_web_address_written_out(self):
        bad = {"Cc", "Cf", "Co", "Cn", "Cs", "Zl", "Zp"}
        files = [SOURCES / "check" / "garbage.py", SOURCES / "ui" / "core" / "draft_garbage.py", ROOT / "tests" / "garbage_samples.py", *sorted((ROOT / "tests").glob("test_check_garbage*.py"))]
        for path in files:
            text = path.read_text(encoding="utf-8")
            odd = [hex(ord(ch)) for ch in text if ch not in "\n\r\t" and (unicodedata.category(ch) in bad or ord(ch) in (0xFFFD, 0x3164, 0xFFA0, 0x115F, 0x1160, 0x034F) or 0xFE00 <= ord(ch) <= 0xFE0F)]
            self.assertEqual(odd, [], f"{path.name}: 눈에 안 보이는 글자는 코드 숫자로 쓴다")
            self.assertNotIn(chr(0x7E), text, f"{path.name}: 물결 글자를 소스에 쓰지 않는다(범위는 –)")
            self.assertNotIn("http" + "://", text)
            self.assertNotIn("http" + "s://", text)


class SentenceSplitEquivalenceTest(unittest.TestCase):
    """위치를 아는 문장 나누기가 기존 `check/claims.split_sentences` 와 같은 조각을 낸다 — 두 규칙이 어긋나면 이 시험이 알린다."""

    def pieces(self, text):
        return [text[start:end] for start, end in g.sentence_spans(text)]

    def test_known_examples_are_split_the_same(self):
        for sample in (*S.NORMAL_TEXTS, *CONTROL, *DAILY, *NORMAL_MORE[:30]):
            with self.subTest(sample[:30]):
                self.assertEqual(self.pieces(sample), claims.split_sentences(sample))

    def test_edge_shapes_are_split_the_same(self):
        for sample in ("", " ", "\n", "...", "?!", "가. 나? 다! 라… 마。 바！ 사？", "그가 말했다. \"좋아요.\" 그리고 (끝.) 'ok.' 끝", "3.5 와 4.0 은 소수예요. 1. 항목", "줄1\n줄2.\r\n줄3?\r줄4" + chr(0x2028) + "줄5",
                       "끝에 마침표가 없어요", "가....나 .. 다", "  앞뒤 공백 .  ", "\"따옴표 끝.\"다음 문장"):
            with self.subTest(repr(sample)):
                self.assertEqual(self.pieces(sample), claims.split_sentences(sample))

    def test_random_texts_are_split_the_same(self):
        rng = random.Random(20261110)
        alphabet = ["가", "나", "다 ", "라", ".", "?", "!", S.ELLIPSIS, S.IDEOGRAPHIC_STOP, " ", "  ", "\n", "\r\n", "\r", chr(0x2028), chr(0x2029), "\"", "'", ")", "]", chr(0x201D), chr(0x300D), "3.5", "ok", S.ZWSP]
        for _ in range(300):
            sample = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            self.assertEqual(self.pieces(sample), claims.split_sentences(sample), repr(sample))

    def test_the_key_ignores_marks_invisible_characters_case_and_width(self):
        self.assertEqual(g.sentence_key("Hello,  World!"), g.sentence_key("hello" + S.ZWSP + " world" + chr(0xFF01)))
        self.assertEqual(g.sentence_key(" ... "), "")


if __name__ == "__main__":
    unittest.main()
