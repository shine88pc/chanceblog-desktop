"""후속 정리 묶음(POLISH-1)의 순수 시험 — 사진 연동 3단계 독립 검증 S 가 참고로 남긴 글자·정규식 두 가지(PS-10). 파일·네트워크·화면이 없다.

지키는 것:
  1) 문장 끝을 찾는 정규식(`content/photo_flow.SENTENCE_END`)은 글이 길어도 **글자 수에 비례한 시간**이다 — 구두점이 아주 길게 이어진 뒤 공백이 아닌 글자가 오는 글(마침표 2만 개 + `x`)에서 제곱 시간이던 것(옛 코드는 약 9초). 찾는 결과는 옛 정규식과 한 건도 다르지 않다.
  2) 정확한 사진 자리 `{{사진 N}}` 만 사진 자리다 — 닫는 중괄호가 하나 더 붙은 `{{사진 1}}}`(앞에 여는 중괄호가 하나 더 붙은 `{{{사진 1}}` 도)는 복사할 때 `[이미지 1]` 로 바뀌지 않고(`[이미지 1]}` 가 되던 것), 글 모양 점검이 `{{ … }}` 자리표시로 걸러 낸다(옛 점검은 정확한 모양 뒤에 붙은 `}` 를 못 봤다).
"""
import random
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import garbage_samples as S  # noqa: E402

from chanceblog_desktop.content import photo_flow as pf  # noqa: E402

OLD_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s|$)")                       # 고치기 전의 정규식 — 결과가 같은지 견주는 기준


class SentenceEndTest(unittest.TestCase):
    def test_a_very_long_run_of_punctuation_followed_by_a_letter_is_scanned_in_linear_time(self):
        """마침표 2만 개 + `x` — 옛 정규식은 시작 자리마다 끝까지 되돌아가서 제곱 시간이었다(이 PC 에서 약 9초)."""
        for text in ("." * 20000 + "x", "…" * 20000 + "x", "?!" * 10000 + "가", ("." * 5000 + ")") * 4 + "x", "." * 20000 + "\"" * 5000 + "x"):
            started = time.perf_counter()
            self.assertEqual(pf.sentence_ends(text), (), text[:6])
            self.assertLess(time.perf_counter() - started, 2.0, "글자 수에 비례한 시간이어야 한다")

    def test_the_time_grows_about_with_the_length_not_with_its_square(self):
        def seconds(count):
            started = time.perf_counter()
            for _ in range(3):
                pf.sentence_ends("." * count + "x")
            return time.perf_counter() - started
        small, large = seconds(6000), seconds(12000)
        self.assertLess(large, small * 3.0 + 0.05, f"두 배로 늘렸더니 시간이 {large / max(small, 1e-9):.1f}배다 — 제곱이면 4배")

    def test_the_found_ends_are_exactly_the_same_as_the_old_pattern_on_random_texts(self):
        """고친 정규식이 문장 끝을 찾는 결과는 옛 정규식과 한 건도 다르지 않다 — 부호·닫는 따옴표·괄호·공백·줄바꿈·글자를 마구 섞은 글 몇천 개."""
        rng = random.Random(20261117)
        alphabet = [".", "!", "?", "…", "”", "’", "\"", "'", ")", "]", " ", "\n", "가", "a", "3", "."]
        for _ in range(6000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            expected = tuple(found.end() for found in OLD_SENTENCE_END.finditer(text))
            self.assertEqual(pf.sentence_ends(text), expected, repr(text))

    def test_the_known_sentences_still_end_where_they_ended(self):
        self.assertEqual(pf.sentence_ends("가격은 3.5만원이에요. 좋아요!"), (len("가격은 3.5만원이에요."), len("가격은 3.5만원이에요. 좋아요!")))
        self.assertEqual(pf.sentence_ends("그가 “왔어요.” 라고 했다."), (len("그가 “왔어요.”"), len("그가 “왔어요.” 라고 했다.")))
        self.assertEqual(pf.sentence_ends("글이 길어요… 그래서요?! 네."), (len("글이 길어요…"), len("글이 길어요… 그래서요?!"), len("글이 길어요… 그래서요?! 네.")))
        self.assertEqual(pf.sentence_ends("끝이 없는 글"), ())
        self.assertEqual(pf.sentence_ends("점 하나.둘"), ())
        self.assertEqual(pf.sentence_ends("말줄임표...... 다음"), (len("말줄임표......"),), "부호가 이어진 덩어리는 한 번만 끝으로 센다")
        self.assertEqual(pf.sentence_ends("끝.)"), (3,))
        self.assertEqual(pf.sentence_ends("끝.)x"), (), "닫는 부호 뒤에 글자가 바로 오면 끝이 아니다")

    def test_the_pattern_only_starts_at_the_first_mark_of_a_run(self):
        """구조 점검 — 부호 덩어리의 가운데에서 다시 시작하지 않는다(그 되돌아가기가 제곱 시간의 원인이었다)."""
        pattern = pf.SENTENCE_END.pattern
        self.assertTrue(pattern.startswith("(?<![.!?…])"), pattern)


class CopyTextTest(unittest.TestCase):
    def test_only_the_exact_slot_becomes_an_image_mark_and_a_slot_with_one_more_brace_is_left_as_it_is(self):
        self.assertEqual(pf.to_copy_text("{{사진 1}}"), "[이미지 1]")
        self.assertEqual(pf.to_copy_text("앞 {{사진 12}} 뒤"), "앞 [이미지 12] 뒤")
        self.assertEqual(pf.to_copy_text("x{{사진 3}}y"), "x[이미지 3]y", "글자가 바로 붙어도 정확한 자리는 바뀐다")
        for text in ("{{사진 1}}}", "{{{사진 1}}", "{{사진 1}}}}", "{{{사진 1}}}", "앞 {{사진 2}}} 뒤"):
            self.assertEqual(pf.to_copy_text(text), text, repr(text))
        self.assertEqual(pf.to_copy_text("앞 {{사진 1}} 뒤 {{사진 2}}} 끝 {{사진 3}}"), "앞 [이미지 1] 뒤 {{사진 2}}} 끝 [이미지 3]")

    def test_the_slots_the_app_puts_in_are_always_exact_so_they_still_all_turn_into_image_marks(self):
        from chanceblog_desktop.content import photo_manifest as pm
        for number in (1, 9, 10, 99, 100, 999):
            self.assertEqual(pf.to_copy_text(pm.placeholder(number)), f"[이미지 {number}]")
        self.assertEqual(pf.to_copy_text("보통 글 {중괄호} {{이름}} [이미지 1]"), "보통 글 {중괄호} {{이름}} [이미지 1]", "그 밖의 글은 한 글자도 안 바뀐다")
        self.assertEqual(pf.to_copy_text(None), None)


class GarbageSlotTest(unittest.TestCase):
    def test_a_photo_slot_with_one_more_brace_is_caught_like_any_other_double_brace_shape(self):
        for shape in ("{{사진 1}}}", "{{사진 1}}}}", "{{{사진 1}}", "앞 문단\n\n{{사진 1}}}\n\n뒤 문단", "{{사진 12}}}"):
            with self.subTest(shape):
                items = S.found(shape, "placeholder")
                self.assertEqual(len(items), 1, shape)
                self.assertEqual(items[0].sub, "double_brace")

    def test_the_exact_slot_is_still_normal_even_with_text_or_another_slot_next_to_it(self):
        for text in ("{{사진 1}}", "앞 문단\n\n{{사진 1}}\n\n뒤 문단", "{{사진 1}}\n{{사진 2}}", "글{{사진 3}}글", "}{{사진 1}}{"):
            with self.subTest(text):
                self.assertEqual(S.found(text, "placeholder"), [], text)

    def test_a_stray_brace_next_to_a_slot_does_not_hide_the_slot_next_to_another_template_mark(self):
        text = "{{사진 1}}}\n\n안녕 {{이름}} 님"
        self.assertEqual([S.caught(text, item) for item in S.found(text, "placeholder")], [["{{사진 1}}"], ["{{이름}}"]])

    def test_the_title_still_catches_a_photo_slot_and_the_old_shapes_are_still_caught(self):
        self.assertEqual(len(S.found("제목은 아무거나", "placeholder", title="{{사진 1}} 제목")), 1)
        for shape in ("{{사진}}", "{{사진 0}}", "{{사진 1000}}", "{{ 사진 1 }}", "{{사진 1 }}", "{{그림 1}}"):
            self.assertEqual(len(S.found(shape, "placeholder")), 1, shape)


if __name__ == "__main__":
    unittest.main()
