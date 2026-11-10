"""'글 모양 점검' 규칙의 **병적 입력과 속도** — 10만 자 글도 넉넉한 상한(2초) 안에 끝나고(운영자 병합 조건), 열림만 있는 `{{`·`&`·역따옴표·길이가 다른 역따옴표 열림·공백 글·같은 낱말 반복 같은 입력에서도 선형 시간이다.
상한은 느린 러너에서도 흔들리지 않게 실제 측정(개발 PC 에서 0.03–0.4초)의 대여섯 배로 넉넉하게 잡았다. 시간은 시험이 직접 재서(`time.perf_counter`) 상한과 견준다 — 결과도 함께 확인해 '빨리 끝났지만 틀린' 경우를 막는다.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import garbage_samples as S  # noqa: E402

from chanceblog_desktop.check import garbage as g  # noqa: E402

LIMIT_SECONDS = 2.0
SIZE = g.MAX_SCAN_CHARS


def timed(title, body):
    start = time.perf_counter()
    report = g.scan(title, body)
    return time.perf_counter() - start, report


def prose(size=SIZE):
    """같은 문장이 되풀이되지 않는 정상 글(번호를 붙여 서로 다르게)."""
    parts, length, number = [], 0, 0
    while length < size:
        number += 1
        sentence = f"{number}번째 날에는 날씨가 맑아서 산책을 다녀왔고 점심에는 따뜻한 국수를 먹었어요.\n" + ("\n" if number % 4 == 0 else "")
        parts.append(sentence)
        length += len(sentence)
    return "".join(parts)[:size]


class HundredThousandCharsTest(unittest.TestCase):
    def test_a_normal_body_of_exactly_the_limit_finishes_within_the_limit_and_has_no_findings(self):
        body = prose()
        self.assertEqual(len(body), SIZE)
        seconds, report = timed("제목", body)
        self.assertLess(seconds, LIMIT_SECONDS)
        self.assertEqual((report.skipped, report.findings), (False, ()))

    def test_a_long_body_full_of_findings_finishes_within_the_limit(self):
        unit = "가나 " + S.ZWSP + "{{이름}} &nbsp; 좋아요 좋아요 좋아요 " + S.FFFD + "\n\n"
        body = (unit * (SIZE // len(unit) + 1))[:SIZE]
        seconds, report = timed("", body)
        self.assertLess(seconds, LIMIT_SECONDS)
        self.assertEqual({item.kind for item in report.findings}, {"broken", "invisible", "entity", "placeholder", "dup_word", "dup_sentence"})

    def test_the_same_sentence_repeated_a_thousand_times_is_one_finding(self):
        body = ("오늘은 정말 좋은 날이에요. 날씨가 맑아서 산책을 다녀왔고, 점심에는 따뜻한 국수를 먹었어요.\n\n" * 1200)[:SIZE]
        seconds, report = timed("", body)
        self.assertLess(seconds, LIMIT_SECONDS)
        self.assertEqual([item.kind for item in report.findings], ["dup_sentence", "dup_sentence"])


class UnclosedOpeningsTest(unittest.TestCase):
    def check(self, body, kinds):
        seconds, report = timed("", body)
        self.assertLess(seconds, LIMIT_SECONDS, repr(body[:12]))
        self.assertEqual(sorted({item.kind for item in report.findings}), sorted(kinds))
        return report

    def test_only_double_open_braces(self):
        self.check("{{" * (SIZE // 2), [])

    def test_only_percent_hash_and_dollar_openings(self):
        for unit in ("{%", "{#", "${", "{", "[", "[이"):
            with self.subTest(unit):
                self.check(unit * (SIZE // len(unit)), [])

    def test_only_ampersands_and_unfinished_entities(self):
        self.check("&" * SIZE, [])
        self.check("&amp" * (SIZE // 4), [])
        self.check("&#" * (SIZE // 2), [])

    def test_only_ticks_and_ticks_of_different_lengths(self):
        report = self.check(S.TICK * SIZE, ["fence"])                                   # 역따옴표만 있는 한 줄은 코드 블록 표시다
        self.assertEqual(len(report.findings), 1)
        report = self.check("".join(S.TICK * length + "a " for length in range(1, 441)), [])
        self.assertEqual(report.findings, ())
        pairs = ("`a` " * (SIZE // 4))[:SIZE]
        self.check(pairs, [])

    def test_a_block_opening_with_no_closing_and_many_block_marks(self):
        self.check(S.TICK * 3 + "\n" + "코드 줄\n" * (SIZE // 6), ["fence"])
        report = self.check((S.TICK * 3 + "\n") * (SIZE // 4), ["fence"])
        self.assertEqual(len(report.findings), 1)

    def test_only_blank_text_and_only_line_breaks(self):
        self.check(" " * SIZE, [])
        self.check("\n" * SIZE, [])
        self.check(("\r\n") * (SIZE // 2), [])
        self.check("가 " * (SIZE // 2), [])

    def test_one_word_repeated_and_one_huge_token(self):
        report = self.check("좋아요 " * (SIZE // 4), ["dup_word"])
        self.assertEqual(report.findings[0].repeats, SIZE // 4)
        self.check("가" * SIZE, [])
        self.check("." * SIZE, [])
        self.check("!?" * (SIZE // 2), [])

    def test_a_hundred_thousand_invisible_characters_are_one_finding(self):
        report = self.check(S.ZWSP * SIZE, ["invisible"])
        self.assertEqual((len(report.findings), len(report.findings[0].spans)), (1, SIZE))

    def test_sixteen_thousand_entities_and_many_lines(self):
        report = self.check("&nbsp;" * 16_000, ["entity"])
        self.assertEqual(len(report.findings), 16_000)
        self.check("a\n" * (SIZE // 2), [])

    def test_many_short_sentences_and_many_placeholders(self):
        self.check("가나. " * (SIZE // 4), [])                                          # 문장은 두 글자뿐이라 세지 않고, 문장마다 마침표가 낱말 되풀이를 끊는다(D-323 — 옛 동작은 한 줄기 2만 5천 번으로 걸렸다)
        report = self.check("가나 " * (SIZE // 3), ["dup_word"])                         # 부호가 없으면 여전히 같은 낱말이 붙어서 되풀이된 것으로 걸린다
        self.assertEqual((len(report.findings), report.findings[0].repeats), (1, SIZE // 3))
        report = self.check("{{a}}" * (SIZE // 5), ["placeholder"])
        self.assertEqual(len(report.findings), SIZE // 5)


class SlowNormalizationTest(unittest.TestCase):
    """D-322 — 문장 지문의 NFKC 를 한 번에 부르면 제곱 시간이던 입력들(검증자가 찾은 U+0F73 10만 개 19초·U+FDFA 10만 개 3.4–4.5초)과 내가 더 찾은 것이 조각으로 나눈 지금은 10만 자에서 상한 안이다.
    상한은 그대로 2초 — 지금 값(이 PC 0.03–0.35초)의 5배 이상이다(느린 CI 러너에서도 흔들리지 않게). 입력 크기는 10만 자 그대로다."""

    def check(self, label, title, body):
        seconds, report = timed(title, body)
        self.assertLess(seconds, LIMIT_SECONDS, label)
        self.assertFalse(report.skipped, label)
        return report

    def test_one_sentence_of_the_letters_that_made_the_normalization_quadratic(self):
        for code in (0x0F73, 0xFDFA, 0xFDFB, 0x0F81, 0x3313, 0x0344, 0xFB1D, 0xFB2C):
            with self.subTest(code=f"U+{code:04X}"):
                self.check(f"U+{code:04X}", "", chr(code) * SIZE)

    def test_pieces_that_split_at_every_offset_of_the_piece_size(self):
        self.check("앞에 글자 하나", "", "가" + chr(0x0F73) * (SIZE - 1))
        self.check("조각 하나 딱 맞는 문장 여럿", "", (chr(0x0F73) * (g.NFKC_CHUNK - 1) + ". ") * (SIZE // (g.NFKC_CHUNK + 1)))
        self.check("조각 둘로 나뉘는 문장 여럿", "", (chr(0x0F73) * (g.NFKC_CHUNK + 1) + ". ") * (SIZE // (g.NFKC_CHUNK + 3)))
        self.check("문장마다 100개", "", (chr(0x0F73) * 100 + ". ") * (SIZE // 102))

    def test_other_shapes_that_cost_the_most_in_pieces(self):
        self.check("분리형 한글", "", "".join(chr(code) for code in (0x1112, 0x1161, 0x11AB)) * (SIZE // 3))
        self.check("결합 글자 연속", "", ("a" + chr(0x0301)) * (SIZE // 2))
        self.check("결합 글자 내림차순 덩어리", "", "a" + "".join(chr(code) * (SIZE // 8) for code in (0x0301, 0x0316, 0x0334, 0x0322, 0x0F71, 0x0F72, 0x0F74)))
        self.check("악보 기호(비BMP)", "", chr(0x1D15E) * (SIZE // 2))
        self.check("소문자화로 늘어나는 글자", "", chr(0x0390) * SIZE)

    def test_title_and_body_both_slow_at_the_same_time(self):
        """제목도 본문도 10만 자 — 제목은 문장 지문을 만들지 않으므로 본문의 정규화 비용만 더해진다. 합쳐도 상한의 5배 아래가 되게 제목은 다른 느린 글자로 채운다."""
        self.check("제목 U+FDFA·본문 U+0F73", chr(0xFDFA) * SIZE, chr(0x0F73) * SIZE)
        self.check("제목 U+0F73·본문 U+0F73", chr(0x0F73) * SIZE, chr(0x0F73) * SIZE)
        self.check("제목 U+0F73·본문 U+FDFA", chr(0x0F73) * SIZE, chr(0xFDFA) * SIZE)

    def test_the_marks_between_words_and_wrappers_in_a_long_run_stay_linear(self):
        self.check("쉼표 낱말 반복", "", "좋아요, " * (SIZE // 5))
        self.check("닫는 괄호 낱말 반복", "", "(a) " * (SIZE // 4))
        self.check("굵은 표시 낱말 반복", "", "**a** " * (SIZE // 6))
        self.check("보이지 않는 글자가 낀 긴 낱말", "", ("가" + S.ZWSP) * (SIZE // 2))
        self.check("물결 줄 번갈아", "", (S.TILDE * 3 + "\n코드\n") * (SIZE // 8))
        self.check("물결 장식 줄 번갈아", "", (S.TILDE * 3 + " a " + S.TILDE * 3 + "\n") * (SIZE // 12))


class ThreadSafetyTest(unittest.TestCase):
    def test_the_rule_gives_the_same_result_from_several_threads_at_once(self):
        import threading
        body = "안녕 {{이름}} " + S.ZWSP + " 좋아요 좋아요 좋아요 &nbsp;\n\n" + "문장이 반복돼요 정말로 그래요.\n\n" * 3
        expected = g.scan("제목", body)
        results = []
        threads = [threading.Thread(target=lambda: results.append(g.scan("제목", body))) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(results, [expected] * 6)


if __name__ == "__main__":
    unittest.main()
