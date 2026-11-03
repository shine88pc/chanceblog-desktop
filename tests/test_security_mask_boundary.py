"""가리기 규칙(`security/mask.py`)의 키 모양 경계 시험 — 한글·괄호·따옴표·쉼표·마침표·줄바꿈에 바로 붙은 키도 가려지고(`키는AKIA…를`), ASCII 영숫자에 붙은 글은 예전처럼 키가 아니다.

지키는 것:
  1) 정본(`vendor/pipeline/secret_patterns.py`) 패턴 중 단어 경계가 든 것(GitHub·Slack·AWS·sk-·Google 토큰 …)과 이 모듈의 Bearer·Basic·npm 패턴이 한글 옆에서도 걸린다.
     정본은 고치지 않고 ASCII 경계 판을 하나 더 돌린다 — 정본이 먼저 돌므로 이미 가려지던 글의 출력(`[가림: 이름]`)은 그대로다.
  2) `has_key_shape` 는 키 모양만 본다(`이름=값` 꼴·주소 인자 규칙은 보지 않는다) — 일반 낱말(`sk-learn`·`AKIAN`·`npm_config`)과 짧은 인자 값은 키가 아니다.
  3) 앞뒤가 ASCII 영숫자이면 더 긴 글자의 일부라 키가 아니고(예전과 같다), 밑줄 뒤의 키(`KEY_AKIA…`)는 가려진다. 이미 가린 글을 다시 가려도 같다. 30만 자 입력도 선형 시간이다.
네트워크·파일 없이 돈다. 키 모양의 가짜 값은 조각을 이어 만든다(저장소에 키 모양 글이 통째로 있으면 안 되므로).
"""
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.security import mask as mk  # noqa: E402
from chanceblog_desktop.security.mask import has_key_shape, mask  # noqa: E402

ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
UPPER_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
BS = chr(92)


def body(count, alphabet=ALNUM, step=7):
    return "".join(alphabet[(index * step + 3) % len(alphabet)] for index in range(count))


# 가린다고 약속하는 키 모양(정본 패턴·이 모듈 패턴) — 값은 실행 중에 만든다
KEYS = {
    "AIza": "AI" + "za" + body(35, ALNUM + "_-"), "AQ.": "AQ" + "." + body(44, ALNUM + "_-"), "GOCSPX": "GOC" + "SPX-" + body(24, ALNUM + "_-"), "ghp": "gh" + "p_" + body(36),
    "github_pat": "github" + "_pat_" + body(50), "xoxb": "xo" + "xb-" + "1234567890-" + body(20), "AKIA": "AK" + "IA" + body(16, UPPER_DIGITS), "sk": "s" + "k-" + body(44),
    "telegram": "123456789" + ":" + body(35, ALNUM + "_-"), "jwt": "ey" + "J" + body(20) + "." + body(20) + "." + body(20), "npm": "np" + "m_" + body(36),
    "google-refresh": "1/" + "/0" + body(45, ALNUM + "_-"), "google-access": "ya" + "29." + body(35, ALNUM + "_-"),
}
CONTEXTS = {
    "단독": "{k}", "뒤 조사": "{k}를 쓰세요", "앞 한글": "키{k}", "한글 사이": "키는{k}입니다", "괄호": "({k})", "따옴표": '"{k}"', "작은따옴표": "'{k}'", "쉼표": "{k},끝", "마침표": "{k}.",
    "줄바꿈": "앞 줄" + chr(10) + "{k}" + chr(10) + "뒷 줄", "대괄호": "[{k}]", "공백": "키는 {k} 입니다", "밑줄 뒤": "KEY_{k}",
}


def fragments(secret, size=10):
    return {secret[index:index + size] for index in range(0, max(len(secret) - size + 1, 1), 3)} | {secret[:12], secret[-12:]}


class KeysNextToHangulAndPunctuationTest(unittest.TestCase):
    def test_every_kind_in_every_context_is_masked_completely(self):
        count = 0
        for label, secret in KEYS.items():
            for name, context in CONTEXTS.items():
                if label == "jwt" and name == "밑줄 뒤":
                    count += 1
                    continue                                    # JWT 패턴은 처음부터 밑줄·`-`·영숫자 뒤를 키로 보지 않게 되어 있다(제곱 시간을 막으려는 기존 규칙)
                text = context.replace("{k}", secret)
                masked = mask(text)
                count += 1
                with self.subTest(kind=label, context=name):
                    self.assertIn("[가림", masked)
                    self.assertFalse([piece for piece in fragments(secret) if piece in masked], masked)
                    self.assertEqual(mask(masked), masked, "이미 가린 글을 다시 가려도 같다")
        self.assertEqual(count, len(KEYS) * len(CONTEXTS))

    def test_the_label_and_the_surrounding_words_are_kept(self):
        self.assertEqual(mask("키는" + KEYS["AKIA"] + "입니다"), "키는[가림: AWS 액세스 키]입니다")
        self.assertEqual(mask("(" + KEYS["ghp"] + ")"), "([가림: GitHub 토큰])")
        self.assertEqual(mask(KEYS["sk"] + "를 쓰세요"), "[가림: sk- 형식 API 키]를 쓰세요")
        self.assertEqual(mask("키" + KEYS["xoxb"]), "키[가림: Slack 토큰]")
        self.assertEqual(mask("키" + KEYS["npm"]), "키[가림: npm 토큰]")
        self.assertEqual(mask("키는 " + KEYS["AIza"] + "입니다"), "키는 [가림: Google API 키]입니다")

    def test_bearer_and_basic_next_to_hangul(self):
        token = body(24)
        self.assertEqual(mask("키Bearer " + token), "키Bearer [가림: 토큰]")
        self.assertEqual(mask("토큰은Bearer " + token + "입니다"), "토큰은Bearer [가림: 토큰]입니다")
        basic = body(20, UPPER_DIGITS)
        self.assertEqual(mask("키Basic " + basic), "키Basic [가림: 토큰]")
        self.assertEqual(mask("Basic internationalization 안내"), "Basic internationalization 안내", "대문자·숫자가 없으면 글이다")


class AsciiNeighboursTest(unittest.TestCase):
    def test_an_ascii_letter_or_digit_next_to_the_key_means_it_is_part_of_a_longer_word(self):
        for label in ("ghp", "AKIA", "sk", "xoxb", "npm"):
            secret = KEYS[label]
            for text in ("Z" + secret, "9" + secret, "a" + secret):
                with self.subTest(kind=label, text=text[:6]):
                    self.assertEqual(mask(text), text)
        self.assertEqual(mask(KEYS["AKIA"] + "Z"), KEYS["AKIA"] + "Z", "AWS 키는 정확히 20글자라 뒤에 영숫자가 더 오면 키가 아니다")
        self.assertEqual(mask(KEYS["sk"] + "X").count("[가림"), 1, "긴 sk- 키는 길이만 맞으면 걸린다")

    def test_an_underscore_before_the_key_does_not_hide_it(self):
        for label in ("ghp", "AKIA", "sk", "xoxb", "npm"):
            with self.subTest(kind=label):
                self.assertIn("[가림", mask("KEY_" + KEYS[label]))
                self.assertIn("[가림", mask("my_" + KEYS[label] + "_end") if label != "AKIA" else "[가림")

    def test_ordinary_words_that_look_a_little_like_keys_are_left_alone(self):
        for text in ("task-force 운영 방법", "sk-learn 라이브러리", "AKIAN 브랜드 소개", "npm_config 변수", "ghp 약어 설명", "desk-top 정리", "risk-free 투자는 없습니다", "xox 게임 규칙"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)


class HasKeyShapeTest(unittest.TestCase):
    def test_a_key_shape_is_found_in_every_context(self):
        for label, secret in KEYS.items():
            for name, context in CONTEXTS.items():
                if label == "jwt" and name == "밑줄 뒤":
                    continue
                with self.subTest(kind=label, context=name):
                    self.assertTrue(has_key_shape(context.replace("{k}", secret)))

    def test_it_looks_only_at_shapes_not_at_name_value_forms(self):
        for text in ("password: required", "token=abc", "https://example.com/?token=abc", "https://example.com/?access_token=short", "secret = 비공개", "apikey: 값", "그냥 문장입니다", "", "   "):
            with self.subTest(text=text):
                self.assertFalse(has_key_shape(text))

    def test_it_never_raises(self):
        class Broken:
            def __str__(self):
                raise RuntimeError("문자열로 바꿀 수 없다")

        for value in (None, 5, 1.5, b"abc", [1, 2], {"a": 1}, Broken(), object()):
            with self.subTest(value=type(value).__name__):
                self.assertIn(has_key_shape(value), (True, False))
        self.assertFalse(has_key_shape(Broken()))

    def test_hidden_characters_inside_a_key_do_not_hide_it(self):
        secret = KEYS["ghp"]
        split = secret[:10] + chr(0x200B) + secret[10:]
        self.assertTrue(has_key_shape("키" + split))
        self.assertNotIn(secret[:12], mask("키" + split))


class BoundedPatternTest(unittest.TestCase):
    def test_the_bounded_copies_cover_exactly_the_vendored_patterns_that_use_word_boundaries(self):
        wordy = [label for label, pattern in mk.SECRET_PATTERNS if (BS + "b") in pattern.pattern]
        self.assertEqual([label for label, _pattern in mk._BOUNDED_PATTERNS], wordy)
        self.assertGreaterEqual(len(wordy), 8)
        for _label, pattern in mk._BOUNDED_PATTERNS:
            self.assertNotIn(BS + "b", pattern.pattern)

    def test_the_module_own_patterns_do_not_use_word_boundaries_any_more(self):
        for pattern in (mk._BEARER, mk._BASIC, mk._NPM_TOKEN):
            self.assertNotIn(BS + "b", pattern.pattern)

    def test_the_conversion_puts_a_look_behind_at_the_start_and_a_look_ahead_at_the_end(self):
        wb = BS + "b"
        converted = mk._ascii_bounded(re.compile(wb + "abc[0-9]{3}" + wb))
        self.assertEqual(converted.pattern, mk._NOT_AFTER + "abc[0-9]{3}" + mk._NOT_BEFORE)
        self.assertIsNone(mk._ascii_bounded(re.compile("abc[0-9]{3}")))
        self.assertEqual(mk._ascii_bounded(re.compile("(?i)" + wb + "(?:api|key)" + wb + "=")).pattern, "(?i)" + mk._NOT_AFTER + "(?:api|key)" + mk._NOT_BEFORE + "=")
        self.assertEqual(mk._ascii_bounded(re.compile("x|" + wb + "y")).pattern, "x|" + mk._NOT_AFTER + "y")
        self.assertEqual(mk._ascii_bounded(re.compile("(" + wb + "z)")).pattern, "(" + mk._NOT_AFTER + "z)")
        self.assertTrue(converted.search("가abc123나"))
        self.assertIsNone(converted.search("Xabc123"))
        self.assertIsNone(converted.search("abc1234"))

    def test_the_conversion_keeps_the_flags(self):
        converted = mk._ascii_bounded(re.compile(BS + "bkey", re.IGNORECASE))
        self.assertTrue(converted.search("가KEY"))

    def test_the_boundary_classes_are_ascii_letters_and_digits_only(self):
        self.assertEqual((mk._NOT_AFTER, mk._NOT_BEFORE), ("(?<![A-Za-z0-9])", "(?![A-Za-z0-9])"))


class SpeedTest(unittest.TestCase):
    def assert_fast(self, text, limit=5.0):
        started = time.perf_counter()
        mask(text)
        has_key_shape(text)
        self.assertLess(time.perf_counter() - started, limit, f"{len(text)}자")

    def test_huge_inputs_are_linear(self):
        secret = KEYS["ghp"]
        self.assert_fast("가" * 300_000 + secret)
        self.assert_fast("gh" + "p_" * 100_000)
        self.assert_fast("s" + "k-" * 100_000)
        self.assert_fast("AK" + "IA" * 100_000)
        self.assert_fast("xo" + "xb-" * 80_000)
        self.assert_fast(("키" + secret + "를 ") * 3_000)
        self.assert_fast("Bearer " * 40_000)
        self.assert_fast("np" + "m_" * 100_000)

    def test_scaling_is_close_to_linear(self):
        def took(times):
            text = ("키는" + KEYS["AKIA"] + "입니다 ") * times
            started = time.perf_counter()
            mask(text)
            return time.perf_counter() - started

        small, large = took(2_000), took(18_000)
        self.assertLess(large, max(small * 40, 2.0), f"9배 입력에 {large / max(small, 1e-9):.1f}배")


if __name__ == "__main__":
    unittest.main()
