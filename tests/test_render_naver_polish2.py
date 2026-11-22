"""후속 정리 둘째 묶음(POLISH-2)의 순수 시험 — 네이버 복사 패키지의 문장 끝 정규식(`render/naver._SENTENCE_END`)이 글이 길어도 **글자 수에 비례한 시간**이다.

지키는 것(독립 검증 S 의 참고 SP-4 — 사진 글 쪽 같은 모양의 정규식은 POLISH-1 에서 고쳤고 이쪽만 남아 있었다):
  1) 구두점이 아주 길게 이어진 뒤 공백이 아닌 글자가 오는 문단(마침표 2만 개 + `x`)에서 옛 정규식은 시작 자리마다 끝까지 되돌아가 제곱 시간이었다(이 PC 에서 2만 개에 약 7초). 고친 뒤에는 몇 밀리초다.
  2) 문장 끝을 찾는 결과(걸린 자리)는 옛 정규식과 한 건도 다르지 않다 — 작은 글자 집합의 모든 글을 하나도 빠짐없이 견주고, 무작위 글도 견준다. 문단을 나누는 결과(`_split_paragraph`)도 같다.
  3) 앞 되돌아보기(`(?<![.!?…])`)가 구조로도 남아 있다 — 지우면 위 시험이 빨개진다.
파일·네트워크·화면이 없다.
"""
import html as html_lib
import itertools
import random
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.render import naver  # noqa: E402

OLD_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s)")                       # 고치기 전의 정규식 — 걸린 자리가 같은지 견주는 기준


def spans(pattern, text):
    return [found.span() for found in pattern.finditer(text)]


class LinearTimeTest(unittest.TestCase):
    def test_a_paragraph_with_a_very_long_run_of_punctuation_and_then_a_letter_is_split_in_linear_time(self):
        """마침표 2만 개 + `x` 가 든 긴 문단 — 옛 정규식은 이 문단 하나에 약 7초가 걸렸다."""
        tail = " 나" * 30
        for run in (".", "…", "?!", "!?.", "!)"):
            text = "가" * 50 + run * (20000 // len(run)) + "x" + tail
            started = time.perf_counter()
            pieces = naver._split_paragraph(html_lib.escape(text, quote=False), 100)
            took = time.perf_counter() - started
            self.assertLess(took, 2.0, f"글자 수에 비례한 시간이어야 한다: {run!r} {took:.2f}초")
            self.assertEqual(" ".join(pieces).replace(" ", ""), html_lib.escape(text, quote=False).replace(" ", ""), "글을 자르거나 잃지 않는다")

    def test_the_pattern_alone_finds_nothing_in_a_long_run_of_marks_followed_by_a_letter_and_does_it_fast(self):
        for text in ("." * 30000 + "x", "…" * 30000 + "x", "?!" * 15000 + "가", ("." * 3000 + ")") * 10 + "x"):
            started = time.perf_counter()
            found = spans(naver._SENTENCE_END, text)
            self.assertLess(time.perf_counter() - started, 2.0, text[:6])
            self.assertEqual(found, [], "공백이 아닌 글자가 바로 이어지면 문장 끝이 아니다")

    def test_the_time_grows_about_with_the_length_not_with_its_square(self):
        def seconds(count):
            """세 번 재서 가장 짧은 값 — 다른 프로그램이 CPU 를 잠깐 가져가 한 번 느려진 값에 시험이 흔들리지 않는다(제곱 시간이면 세 번 모두 느리다)."""
            best = None
            for _ in range(3):
                started = time.perf_counter()
                list(naver._SENTENCE_END.finditer("." * count + "x"))
                took = time.perf_counter() - started
                best = took if best is None else min(best, took)
            return best
        small, large = seconds(6000), seconds(12000)
        self.assertLess(large, small * 3.0 + 0.05, f"두 배로 늘렸더니 시간이 {large / max(small, 1e-9):.1f}배다 — 제곱이면 4배")

    def test_the_pattern_starts_only_at_the_first_mark_of_a_run(self):
        """구조 점검 — 부호 덩어리의 가운데에서 다시 시작하지 않는다(그 되돌아가기가 제곱 시간의 원인이었다)."""
        self.assertTrue(naver._SENTENCE_END.pattern.startswith("(?<![.!?…])"), naver._SENTENCE_END.pattern)


class SameAsTheOldPatternTest(unittest.TestCase):
    def test_every_text_of_a_small_alphabet_finds_exactly_the_same_ends_as_the_old_pattern(self):
        """작은 글자 집합(부호·닫는 따옴표·괄호·공백·글자)의 모든 글을 길이 6 까지 하나도 빠짐없이 견준다 — 걸린 자리(시작·끝)가 한 건도 다르지 않다."""
        total = 0
        for alphabet, longest in ((".!…)”x ", 6), (".?\"'] \n가", 5), (".…]" + chr(0x3000) + chr(0xA0) + "x\n)", 5), ("!?.'\"”’)] x\t", 4)):
            for length in range(longest + 1):
                for chars in itertools.product(alphabet, repeat=length):
                    text = "".join(chars)
                    total += 1
                    if spans(OLD_SENTENCE_END, text) != spans(naver._SENTENCE_END, text):
                        self.fail(f"걸린 자리가 다르다: {text!r}")
        self.assertGreater(total, 150000, "견준 글 수가 모자라지 않다")

    def test_random_texts_find_exactly_the_same_ends_as_the_old_pattern(self):
        rng = random.Random(20261122)
        alphabet = [".", "!", "?", "…", "”", "’", "\"", "'", ")", "]", " ", "\n", "가", "a", "3", ".", chr(0x3000), chr(0xA0)]
        for _ in range(8000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            self.assertEqual(spans(naver._SENTENCE_END, text), spans(OLD_SENTENCE_END, text), repr(text))

    def test_the_known_sentences_still_end_where_they_ended_and_the_paragraph_is_split_as_before(self):
        sentences = ["가격은 3.5만원이에요.", "좋아요!", "그가 “왔어요.”", "라고 했다.", "글이 길어요…", "그래서요?!", "네.)"]
        text = " ".join(sentences)
        expected, cursor = [], 0
        for sentence in sentences[:-1]:                                         # 맨 끝 문장은 뒤에 공백이 없어 끝으로 세지 않는다(`_split_paragraph` 가 남은 글을 마지막 조각으로 붙인다)
            cursor += len(sentence)
            expected.append(cursor)
            cursor += 1
        self.assertEqual([match.end() for match in naver._SENTENCE_END.finditer(text)], expected)
        self.assertEqual(spans(naver._SENTENCE_END, "점 하나.둘"), [], "공백이 뒤따르지 않는 점은 끝이 아니다")
        self.assertEqual(spans(naver._SENTENCE_END, "말줄임표...... 다음"), [(4, 10)], "부호가 이어진 덩어리는 한 번만 끝으로 센다")
        self.assertEqual(naver._split_paragraph("첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.", 10), ["첫 문장입니다.", "둘째 문장입니다.", "셋째 문장입니다."])

    def test_a_paragraph_is_split_exactly_as_the_old_pattern_would_split_it(self):
        """문단 나누기 결과가 같다 — 옛 정규식으로 `_split_paragraph` 를 돌린 결과(같은 함수 몸통에 옛 정규식만 끼움)와 견준다."""
        original = naver._SENTENCE_END
        rng = random.Random(20261123)
        words = ["첫째 문장입니다.", "그래서요?!", "네…", "끝)", "”라고 했다.", "마침표...", "x.y", "가격 3.5만원.", "굵게", "<strong>굵은 글. 둘째.</strong>", "<em>기울임!</em>", "<a href=\"#a\">링크 글. 이어짐.</a>", "..", "….", " "]
        pieces_of = lambda inner, limit: naver._split_paragraph(inner, limit)  # noqa: E731
        for _ in range(1500):
            inner = " ".join(rng.choice(words) for _ in range(rng.randint(1, 12)))
            limit = rng.choice((10, 20, 40, 80))
            naver._SENTENCE_END = OLD_SENTENCE_END
            try:
                expected = pieces_of(inner, limit)
            finally:
                naver._SENTENCE_END = original
            self.assertEqual(pieces_of(inner, limit), expected, f"{limit} {inner!r}")


if __name__ == "__main__":
    unittest.main()
