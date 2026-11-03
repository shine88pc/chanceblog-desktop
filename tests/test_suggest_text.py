"""제안에 쓰는 한국어 글 다루기(`content/suggest_text.py`) 시험 — 조사를 받침으로 고르기·어근 나누기·같은 낱말 접기·닮은 정도.

지키는 것:
  1) 한글 음절 11172개 전부에서 받침을 **글자 분해(NFD)로 따로 확인한 값**과 조사가 같다(기대값을 코드에서 복사하지 않는다). 숫자·영문은 읽는 소리 표를 시험이 따로 가진다.
  2) 으로/로 는 ㄹ 받침도 '로' 이고, 을·이·은·과 는 ㄹ 받침을 받침으로 센다.
  3) 같은 낱말이 바로 이어 나오면 접고(조사가 붙은 쪽을 남김) 떨어져 있으면 그대로 둔다. 어근 나누기는 한 글자만 남으면 떼지 않는다.
  4) 제외어 비교 모양(`squash`)은 `check/profile_options` 의 점검과 모든 입력에서 같다(두 곳이 어긋나지 않게).
"""
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import profile_options  # noqa: E402
from chanceblog_desktop.content import suggest_text as tx  # noqa: E402

LIEUL_TAIL = "ᆯ"                                   # 종성 ㄹ


def tail_of(char):
    """한글 음절의 받침을 글자 분해(NFD)로 읽는다 → '' (없음) · 'ㄹ' · 그 밖의 받침 글자."""
    parts = unicodedata.normalize("NFD", char)
    return "" if len(parts) < 3 else "ㄹ" if parts[2] == LIEUL_TAIL else parts[2]


HANGUL = [chr(code) for code in range(0xAC00, 0xD7A4)]
PAIRS = {"을": ("을", "를"), "이": ("이", "가"), "은": ("은", "는"), "으로": ("으로", "로"), "과": ("과", "와")}


class ParticleTest(unittest.TestCase):
    def test_every_hangul_syllable_gets_the_particle_its_final_consonant_calls_for(self):
        wrong = []
        for char in HANGUL:
            tail = tail_of(char)
            for kind, (with_final, without) in PAIRS.items():
                if kind == "으로":
                    expected = without if tail in ("", "ㄹ") else with_final
                else:
                    expected = without if tail == "" else with_final
                got = tx.attach("가" + char, kind)
                if got != "가" + char + expected:
                    wrong.append((char, kind, got))
        self.assertEqual(wrong, [], wrong[:5])

    def test_the_particle_follows_the_last_letter_and_skips_punctuation_and_spaces(self):
        self.assertEqual(tx.attach("보험", "을"), "보험을")
        self.assertEqual(tx.attach("카드", "을"), "카드를")
        self.assertEqual(tx.attach("보험(상품) ", "이"), "보험(상품) 이", "닫는 괄호·공백 뒤여도 마지막 글자(품)의 받침을 본다")
        self.assertEqual(tx.attach("가계부.", "은"), "가계부.는")
        self.assertEqual(tx.attach("집", "으로"), "집으로")
        self.assertEqual(tx.attach("서울", "으로"), "서울로", "ㄹ 받침은 '로'")
        self.assertEqual(tx.attach("서울", "을"), "서울을", "을 은 ㄹ 받침을 받침으로 센다")
        self.assertEqual(tx.attach("김장을", "을"), "김장을", "이미 맞는 조사가 붙은 씨앗에 또 붙이지 않는다")
        self.assertEqual(tx.attach("나라를", "을"), "나라를")
        self.assertEqual(tx.attach("가계부는", "은"), "가계부는")
        self.assertEqual(tx.attach("겨울은", "은"), "겨울은")
        self.assertEqual(tx.attach("새마을", "을"), "새마을을", "낱말의 일부인 '을' — 앞 글자(마)에 받침이 없으면 조사가 아니다")
        self.assertEqual(tx.attach("마을", "을"), "마을을", "두 글자 낱말은 그대로")
        self.assertEqual(tx.attach("김장를", "을"), "김장를을", "받침과 어긋난 조사('를' 앞 '장' 에는 받침이 있다)는 조사로 보지 않는다")
        for noun, kind, want in (("고양이", "이", "고양이가"), ("전문가", "이", "전문가가"), ("도로", "으로", "도로로"), ("사과", "과", "사과와")):
            self.assertEqual(tx.attach(noun, kind), want, "낱말의 끝이기도 한 조사는 건드리지 않는다")

    def test_digits_are_read_by_their_sound(self):
        batchim = {"0": "영", "3": "삼", "6": "육"}
        rieul = {"1": "일", "7": "칠", "8": "팔"}
        plain = {"2": "이", "4": "사", "5": "오", "9": "구"}
        for digit in batchim:
            self.assertEqual((tx.attach("제" + digit, "을"), tx.attach("제" + digit, "으로")), ("제" + digit + "을", "제" + digit + "으로"), batchim[digit])
        for digit in rieul:
            self.assertEqual((tx.attach("제" + digit, "을"), tx.attach("제" + digit, "으로")), ("제" + digit + "을", "제" + digit + "로"), rieul[digit])
        for digit in plain:
            self.assertEqual((tx.attach("제" + digit, "을"), tx.attach("제" + digit, "으로")), ("제" + digit + "를", "제" + digit + "로"), plain[digit])
        self.assertEqual(tx.attach("10", "을"), "10을", "10 은 '십'")
        self.assertEqual(tx.attach("２", "이"), "２가", "전각 숫자도 같다")

    def test_latin_letters_are_read_by_their_sound(self):
        for letter, expected in {"L": "을", "M": "을", "N": "을", "R": "을", "l": "을", "A": "를", "B": "를", "S": "를", "T": "를", "I": "를", "Z": "를", "x": "를"}.items():
            self.assertEqual(tx.attach("앱" + letter, "을"), "앱" + letter + expected, letter)
        self.assertEqual(tx.attach("AI", "을"), "AI를")
        self.assertEqual(tx.attach("SNS", "이"), "SNS가")
        self.assertEqual(tx.attach("PC", "은"), "PC는")
        self.assertEqual(tx.attach("LED", "을"), "LED를")
        self.assertEqual(tx.attach("MBTI", "과"), "MBTI와")
        self.assertEqual(tx.attach("CNN", "과"), "CNN과")
        self.assertEqual(tx.attach("ABCL", "으로"), "ABCL로")

    def test_text_without_a_letter_or_digit_takes_the_no_final_form_and_unknown_kinds_are_refused(self):
        self.assertEqual(tx.attach("", "을"), "를")
        self.assertEqual(tx.attach("...", "이"), "...가")
        self.assertEqual(tx.attach("漢", "을"), "漢를", "한자는 받침 없음으로 본다")
        with self.assertRaises(ValueError):
            tx.attach("집", "에게")
        self.assertEqual(set(tx.PARTICLES), set(PAIRS))


class StemTest(unittest.TestCase):
    def test_a_trailing_particle_is_cut_but_never_down_to_one_letter(self):
        for word, expected in {"보험을": "보험", "카드를": "카드", "보일러는": "보일러", "난방으로": "난방", "난방에서": "난방", "비교하고": "비교", "보험이나": "보험", "가계부와": "가계부", "비용의": "비용"}.items():
            self.assertEqual(tx.stem(word), expected, word)
        for word in ("아이", "나이", "추가", "하나", "정도", "제도", "수의", "회의"):
            self.assertEqual(tx.stem(word), word, f"{word} 는 한 글자만 남으므로 떼지 않는다")
        self.assertEqual(tx.stem("에어컨"), "에어컨")
        self.assertEqual(tx.stem("AI"), "ai")
        self.assertEqual(tx.stem("Ｃ++"), "c++")
        self.assertEqual(tx.stem(""), "")

    def test_the_longest_ending_wins_and_only_one_is_cut(self):
        self.assertEqual(tx.stem("난방에서는"), "난방")
        self.assertEqual(tx.stem("난방으로서"), "난방")
        self.assertEqual(tx.stem("보험을는"), "보험을", "한 번만 뗀다")

    def test_words_and_stems_split_on_spaces_and_symbols_and_fold_case_and_width(self):
        self.assertEqual(tx.words("보일러-점검,  ＡＩ 입문(2판)"), ["보일러", "점검", "ai", "입문", "2판"])
        self.assertEqual(tx.stems("보일러를 점검하고 AI 를"), ["보일러", "점검", "ai", "를"])
        self.assertEqual(tx.stem_set("보험 보험을 카드"), frozenset({"보험", "카드"}))
        self.assertEqual(tx.words(""), [])
        self.assertEqual(tx.words("   ...   "), [])

    def test_jaccard_and_containment(self):
        self.assertEqual(tx.jaccard(frozenset("abc"), frozenset("abd")), 0.5)
        self.assertEqual(tx.jaccard(frozenset("ab"), frozenset("ab")), 1.0)
        self.assertEqual(tx.jaccard(frozenset("ab"), frozenset("cd")), 0.0)
        self.assertEqual(tx.jaccard(frozenset(), frozenset("a")), 0.0)
        self.assertEqual(tx.jaccard(frozenset(), frozenset()), 0.0)
        self.assertTrue(tx.contains_all(frozenset("abc"), frozenset("ab")))
        self.assertFalse(tx.contains_all(frozenset("ab"), frozenset("abc")))
        self.assertFalse(tx.contains_all(frozenset("ab"), frozenset()), "빈 것은 포함으로 치지 않는다")
        self.assertFalse(tx.contains_all(frozenset(), frozenset("a")))


class FoldTest(unittest.TestCase):
    def test_a_word_repeated_right_after_itself_is_folded(self):
        self.assertEqual(tx.fold_repeats("보험 비교 비교"), "보험 비교")
        self.assertEqual(tx.fold_repeats("점검 점검 순서"), "점검 순서")
        self.assertEqual(tx.fold_repeats("가 나 나 나 다"), "가 나 다")
        self.assertEqual(tx.fold_repeats("AI ai 활용"), "AI 활용", "대소문자가 달라도 같은 낱말")
        self.assertEqual(tx.fold_repeats("Ａ ａ"), "Ａ", "전각도 같다")

    def test_the_longer_form_with_the_particle_is_kept_and_the_first_wins_a_tie(self):
        self.assertEqual(tx.fold_repeats("보험 비교 비교를 위한"), "보험 비교를 위한")
        self.assertEqual(tx.fold_repeats("비교를 비교 정리"), "비교를 정리")
        self.assertEqual(tx.fold_repeats("Ab aB"), "Ab")

    def test_words_that_are_apart_or_only_look_alike_stay(self):
        self.assertEqual(tx.fold_repeats("점검 순서 점검"), "점검 순서 점검")
        self.assertEqual(tx.fold_repeats("보험 보험료"), "보험 보험료")
        self.assertEqual(tx.fold_repeats("a  b\t c\n"), "a b c", "공백은 하나로 정리한다")
        self.assertEqual(tx.fold_repeats(""), "")
        self.assertEqual(tx.fold_repeats("- -"), "- -", "낱말이 없는 기호는 접지 않는다")


class SquashTest(unittest.TestCase):
    SAMPLES = ["", " ", "가상 자산", "가상자산", "ＡＩ  툴", "Ａ　Ｉ", "Hello World", "ＨＥＬＬＯ", "코인\t주식\n", "ﬁ ligature", "①②③ 번", "한 글", "é", "é", "AbC dEf", "보일러　점검"]

    def test_squash_is_the_same_comparison_the_profile_option_check_uses(self):
        for sample in self.SAMPLES:
            with self.subTest(sample=sample):
                self.assertEqual(tx.squash(sample), profile_options._squash(sample))

    def test_squash_ignores_spaces_width_and_case(self):
        self.assertEqual(tx.squash("가상 자산"), tx.squash("가상자산"))
        self.assertEqual(tx.squash("ＡＩ"), "ai")
        self.assertNotEqual(tx.squash("가상"), tx.squash("가정"))


class RenderTest(unittest.TestCase):
    def test_slots_are_filled_particles_attached_and_repeats_folded(self):
        self.assertEqual(tx.render("{주제:을} 시작하기 전에", {"주제": "보험"}), "보험을 시작하기 전에")
        self.assertEqual(tx.render("{주제:을} 시작하기 전에", {"주제": "카드"}), "카드를 시작하기 전에")
        self.assertEqual(tx.render("{계절} 시기에 챙길 {주제}", {"주제": "난방", "계절": "한파"}), "한파 시기에 챙길 난방")
        self.assertEqual(tx.render("{주제} 점검 점검 순서", {"주제": "보일러"}), "보일러 점검 순서")
        self.assertEqual(tx.render("{주제} 비교", {"주제": "보험 비교"}), "보험 비교", "씨앗이 틀의 끝 낱말과 같으면 접는다")
        self.assertEqual(tx.render("{주제:으로} 해결", {"주제": "서울"}), "서울로 해결")
        self.assertEqual(tx.render("{계절:이} 오면", {"주제": "x", "계절": "장마"}), "장마가 오면")

    def test_a_missing_value_or_an_unknown_particle_is_a_data_error_not_a_silent_blank(self):
        with self.assertRaises(ValueError):
            tx.render("{계절} {주제}", {"주제": "보험"})
        with self.assertRaises(ValueError):
            tx.render("{주제}", {"주제": ""})
        with self.assertRaises(ValueError):
            tx.render("{주제:에게}", {"주제": "보험"})
        self.assertEqual(tx.render("{기타} 그대로", {"주제": "보험"}), "{기타} 그대로", "모르는 자리 이름은 건드리지 않는다")


if __name__ == "__main__":
    unittest.main()
