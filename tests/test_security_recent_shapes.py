"""최근에 생긴 키·토큰 모양(`security/mask.py` 의 `_RECENT_PATTERNS`)과 올리기 직전 마지막 관문(`publish/pages.py` 의 `secret_labels`) 시험 — L8 F069, 결정 D-556(관문)·D-557(새 모양).

지키는 것:
  1) 새 모양 열여덟(AWS 임시·식별 키, Slack 앱·갱신 토큰, Stripe 키·웹훅 비밀, GitLab, Hugging Face, SendGrid, PyPI, Groq, NVIDIA, DigitalOcean, Shopify, Notion, Linear, Perplexity, xAI, Replicate)은 어느 자리에서나 걸리고(글 한가운데·한글 바로 옆·주소 인자·JSON·여러 줄·눈에 안 보이는 글자로 쪼갠 것)
     출력에서는 이름이 붙은 가림 표지(`[가림: 이름]`)로 바뀌며 가짜 키의 글자가 남지 않는다. 시험의 표(`SAMPLES`)와 목록(`_RECENT_PATTERNS`)의 이름이 정확히 같다 — 모양 하나를 빼거나 시험 없이 더하면 걸린다.
  2) **이미 있는 모양은 되풀이하지 않는다** — 새 모양의 표본은 정본(vendor/)·본문 속 비밀 형태 검사기·가리기 목록의 옛 모양 어디에도 걸리지 않던 것이다(그래서 새 패턴이 필요했다). 지시서가 예로 든 모양(GitHub 세밀 토큰·`ghs_`·`gho_`·텔레그램·`AIza`·`xox`·개인 키 머리말)은 옛 목록이 이미 막는다.
  3) 정상 글은 걸리지 않는다 — 꼬리가 모자란 것·길이가 넘치는 것·앞에 영문이 붙은 것·접두사만 설명한 영어 문장·붙임표로 이은 긴 글 주소·해시·UUID·긴 숫자와, 실제 글 두 편·앱이 실제로 내는 글 이천여 개·손으로 쓴 정상 글 백스물두 개·저장소의 문서와 소스.
  4) 올리기 직전 관문(`check_post`·commit 제목)은 정본만이 아니라 앱의 모든 목록(검사기 여섯 유형·가리기 목록)을 **글 끝까지** 본다 — 복사·저장 관문은 막는데 이 관문만 놓치던 모양(`sk-proj-`·Anthropic·npm·JWT·Bearer·Slack 웹훅·`ENCRYPTED` 개인 키 머리말·AWS `ASIA`)과 20만 자 뒤에 숨은 키.
  5) 모든 정규식은 입력 길이에 선형이다(병적 입력 20만 자가 몇 초 안).
가짜 키는 `CANARY` 로 시작하는 몸을 실행할 때 조립한다(저장소의 비밀 검사가 소스를 훑는다 — 완성된 키 모양을 소스에 쓰지 않는다). 16진수만 받는 두 모양(DigitalOcean·Shopify)은 `CANARY` 글자가 16진수가 아니라 `ca7a12` 로 시작한다.
네트워크·실제 비밀 없이 돈다.
"""
import re
import string
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pcsec1_mask_cases as pc  # noqa: E402
import test_pages_publish as tp  # noqa: E402
import test_security_mask_engine as engine  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.core import use_vendored_core  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import pages  # noqa: E402
from chanceblog_desktop.security import mask as mk  # noqa: E402
from chanceblog_desktop.security import scan  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules  # noqa: E402

use_vendored_core()
from pipeline.secret_patterns import find_secrets  # noqa: E402

ROOT = HERE.parent
ALNUM = string.ascii_letters + string.digits
UPPER_DIGITS = string.ascii_uppercase + string.digits
HEX = "0123456789abcdef"
B64URL = ALNUM + "_-"
MARK = "CANARY"                                                                       # 가짜 몸의 머리 — 출력에 이 글이 남았으면 가려지지 않은 것이다


def body(length, alphabet=ALNUM):
    """`CANARY`(글자 집합에 밑줄이 있으면 `CANARY_`)로 시작하는 `length` 글자 — 16진수만 받는 자리는 `ca7a12` 로 시작한다. 나머지는 고정된 계산으로 채운다."""
    head = "ca7a12" if alphabet == HEX else MARK + ("_" if "_" in alphabet else "")
    fill = "".join(alphabet[(index * 7 + 3) % len(alphabet)] for index in range(max(length - len(head), 0)))
    return (head + fill)[:length]


def cat(*parts):
    return "".join(parts)


# 새 모양 하나 = (`delta` 만큼 꼬리를 늘이거나 줄인 표본을 만드는 함수, 걸리는 가장 짧은 표본의 delta, 더 길어도 걸리는가)
SAMPLES = {
    "AWS 임시·식별 키": (lambda d=0: cat("AS", "IA", body(16 + d, UPPER_DIGITS)), 0, False),
    "Slack 앱 토큰": (lambda d=0: cat("xa", "pp-1-", body(11, UPPER_DIGITS), "-1234567890123-", body(64 + d)), -32, True),
    "Slack 갱신 토큰": (lambda d=0: cat("xo", "xe-1-", body(80 + d, ALNUM + "-")), -40, True),
    "Stripe 비밀 키": (lambda d=0: cat("sk", "_live_", body(28 + d)), -4, True),
    "Stripe 웹훅 서명 비밀": (lambda d=0: cat("wh", "sec_", body(32 + d)), 0, True),
    "GitLab 토큰": (lambda d=0: cat("gl", "pat-", body(20 + d, B64URL)), 0, True),
    "Hugging Face 토큰": (lambda d=0: cat("h", "f_", body(34 + d)), 0, True),
    "SendGrid 키": (lambda d=0: cat("S", "G.", body(22 + d, B64URL), ".", body(43, B64URL)), 0, False),
    "PyPI 토큰": (lambda d=0: cat("py", "pi-AgEIcHlwaS5vcmc", body(70 + d, B64URL)), -20, True),
    "Groq 키": (lambda d=0: cat("gs", "k_", body(52 + d)), -12, True),
    "NVIDIA 키": (lambda d=0: cat("nv", "api-", "Z9", body(62 + d, B64URL)), -24, True),
    "DigitalOcean 토큰": (lambda d=0: cat("do", "p_v1_", body(64 + d, HEX)), 0, True),
    "Shopify 토큰": (lambda d=0: cat("sh", "pat_", body(32 + d, HEX)), 0, True),
    "Notion 토큰": (lambda d=0: cat("nt", "n_", body(44 + d)), -4, True),
    "Linear 키": (lambda d=0: cat("lin", "_api_", body(40 + d)), 0, True),
    "Perplexity 키": (lambda d=0: cat("pp", "lx-", body(48 + d)), -8, True),
    "xAI 키": (lambda d=0: cat("xa", "i-", body(80 + d)), -10, True),
    "Replicate 토큰": (lambda d=0: cat("r", "8_", body(37 + d)), 0, False),
}
RECENT = {label: (pattern, need) for label, pattern, need in mk._RECENT_PATTERNS}
# 한 모양이 접두어를 여럿 묶은 것의 나머지 접두어들 — 표본(`SAMPLES`)은 첫 접두어 하나만 만들므로 나머지가 빠지지 않았는지 따로 본다
VARIANTS = {
    "AWS 임시·식별 키": [cat(prefix, body(16, UPPER_DIGITS)) for prefix in ("AS" + "IA", "AG" + "PA", "AI" + "DA", "AR" + "OA", "AN" + "PA", "AN" + "VA", "AI" + "PA")],
    "Stripe 비밀 키": [cat("rk", "_live_", body(28))],
    "GitLab 토큰": [cat("gl", prefix, "-", body(20, B64URL)) for prefix in ("ptt", "rt", "dt", "soat", "cbt", "imt", "agent", "ft", "oas")],
    "Shopify 토큰": [cat("sh", "p", prefix, "_", body(32, HEX)) for prefix in ("ss", "ca", "pa")],
    "DigitalOcean 토큰": [cat("do", letter, "_v1_", body(64, HEX)) for letter in ("o", "r")],
}


def sample(label, delta=0):
    return SAMPLES[label][0](delta)


OPEN_ENDED = ("Slack 앱 토큰", "Slack 갱신 토큰", "Stripe 비밀 키", "Stripe 웹훅 서명 비밀", "GitLab 토큰", "Hugging Face 토큰", "PyPI 토큰", "Groq 키", "NVIDIA 키", "Notion 토큰", "Linear 키", "Perplexity 키", "xAI 키")        # 꼬리 길이에 상한이 없는 모양 — 실제 키가 표본보다 길어도 끝까지 가린다
FIXED_LENGTH = ("AWS 임시·식별 키", "DigitalOcean 토큰", "Replicate 토큰", "SendGrid 키", "Shopify 토큰")                                                                                               # 길이가 정해진 모양


def nvidia_key(digit_at=None, upper_at=None, length=64):
    """소문자뿐인 몸(`canary` 로 시작)에 숫자는 `digit_at` 번째, 대문자는 `upper_at` 번째 한 곳에만 둔 NVIDIA 모양 키 — 실제 키에서 숫자·대문자가 앞쪽에 없는 경우를 흉내 낸다(`None` 이면 그 글자는 없다)."""
    chars = list("canary" + "".join(string.ascii_lowercase[(index * 7 + 3) % 26] for index in range(length - 6)))
    if digit_at is not None:
        chars[digit_at] = "7"
    if upper_at is not None:
        chars[upper_at] = "Q"
    return cat("nv", "api-", "".join(chars))


SCAN_ALREADY_KNOWS = frozenset({"AWS 임시·식별 키"})                                       # 본문 속 비밀 형태 검사기(`scan.py`, 저장·백업 관문)는 아는데 가리기 목록만 몰랐던 모양 — 가림 규칙의 알려 둔 한계 ① 이었다


def old_mask_lists_catch(text):
    """이 변경 **전** 가리기 목록(정본 + 가리기 모듈의 옛 모양)이 그 글을 잡는가 — 새 모양의 표본은 여기에 걸리면 안 된다(중복 금지)."""
    recent = {pattern for _label, pattern, _need in mk._RECENT_PATTERNS}
    view = mk._strip_invisible(text)
    return bool(find_secrets(view) or any(pattern.search(view) for pattern in mk._SHAPE_PATTERNS if pattern not in recent))


def old_lists_catch(text):
    """옛 가리기 목록이나 본문 속 비밀 형태 검사기(여섯 유형)가 그 글을 잡는가."""
    return bool(old_mask_lists_catch(text) or scan.has_secret(mk._strip_invisible(text)))


def new_patterns_hit(text):
    return [label for label, pattern, _need in mk._RECENT_PATTERNS if pattern.search(text)]


class TableTest(unittest.TestCase):
    def test_the_table_and_the_pattern_list_have_exactly_the_same_names(self):
        self.assertEqual(set(SAMPLES), set(RECENT))
        self.assertEqual(len(RECENT), len(mk._RECENT_PATTERNS), "이름이 겹치지 않는다")
        self.assertEqual(len(SAMPLES), 18)

    def test_every_sample_is_a_fake_one_with_the_canary_head(self):
        for label in SAMPLES:
            with self.subTest(label=label):
                self.assertTrue(MARK in sample(label) or "ca7a12" in sample(label))

    def test_the_prefilter_words_of_every_pattern_appear_in_its_sample(self):
        for label, (_pattern, need) in RECENT.items():
            with self.subTest(label=label):
                self.assertTrue(need and all(isinstance(piece, str) and piece for piece in need))
                self.assertTrue(any(piece in sample(label) for piece in need), "사전 확인 낱말이 표본에 없으면 규칙이 아예 돌지 않는다")

    def test_the_new_shapes_were_unknown_to_the_old_mask_lists_so_nothing_is_duplicated(self):
        for label in SAMPLES:
            with self.subTest(label=label):
                text = "토큰은 " + sample(label) + " 입니다"
                self.assertFalse(old_mask_lists_catch(text), "정본·옛 가리기 모양이 이미 막는 모양은 더하지 않는다")
                self.assertEqual(scan.has_secret(text), label in SCAN_ALREADY_KNOWS, "검사기가 아는 모양은 이 한 가지뿐이다 — 가림 규칙의 알려 둔 한계 ① 을 닫는다")

    def test_the_shapes_the_brief_named_were_already_blocked_so_they_are_not_added_again(self):
        named = {"github fine-grained": cat("github", "_pat_", body(11), "_", body(59)), "ghs": cat("gh", "s_", body(36)), "gho": cat("gh", "o_", body(36)), "telegram": cat("123456789", ":AA", body(33, B64URL)),
                 "google": cat("AI", "za", body(35, B64URL)), "slack": cat("xo", "xb-123456789012-123456789012-", body(24)), "private key header": cat("-----", "BEGIN OPENSSH PRIVATE KEY", "-----")}
        for label, text in named.items():
            with self.subTest(label=label):
                self.assertTrue(old_lists_catch("토큰은 " + text + " 입니다"))
                self.assertEqual(new_patterns_hit(text), [], "새 목록은 이 모양을 되풀이하지 않는다")


class DetectionTest(unittest.TestCase):
    CONTEXTS = {
        "plain": "토큰은 {} 입니다",
        "hangul adjacent": "키는{}를 쓴다",
        "url query": "https://example.com/api?x={}&y=1",
        "json": '{{"k": "{}"}}',
        "multiline": "첫째 줄\n둘째 줄 {}\n마지막 줄",
        "markdown": "```\nexport K={}\n```",
        "start of text": "{} 가 맨 앞에 있다",
        "end of text": "맨 뒤에 {}",
        "after punctuation": "(키:{})",
    }

    def assert_masked(self, text, token, label):
        masked = mk.mask(text)
        self.assertNotIn(token[-16:], masked, "가짜 키의 글자가 출력에 남았다")
        self.assertIn(f"[가림: {label}]", masked)
        self.assertEqual(mk.mask(masked), masked, "이미 가린 글을 다시 가려도 같다")

    def test_every_shape_is_found_and_masked_in_every_context(self):
        for label in SAMPLES:
            token = sample(label)
            for name, template in self.CONTEXTS.items():
                with self.subTest(label=label, context=name):
                    text = template.format(token)
                    self.assertTrue(mk.has_key_shape(text))
                    self.assertTrue(mk.has_key_shape_anywhere(text))
                    self.assert_masked(text, token, label)

    def test_a_shape_split_by_invisible_characters_is_still_found(self):
        for label in SAMPLES:
            for hider in (0x200B, 0x00AD, 0x2060, 0xFE0F):
                with self.subTest(label=label, hider=hex(hider)):
                    token = sample(label)
                    cut = len(token) // 2
                    text = "실수 " + token[:cut] + chr(hider) + token[cut:] + " 로"
                    self.assertTrue(mk.has_key_shape(text))
                    self.assertNotIn(token[-16:], mk.mask(text))

    def test_two_shapes_in_one_text_are_both_masked_with_their_own_names(self):
        first, second = sample("Groq 키"), sample("Hugging Face 토큰")
        masked = mk.mask("첫째 " + first + " 둘째 " + second + " 끝")
        self.assertIn("[가림: Groq 키]", masked)
        self.assertIn("[가림: Hugging Face 토큰]", masked)
        self.assertNotIn(first[-16:], masked)
        self.assertNotIn(second[-16:], masked)

    def test_every_alternative_prefix_of_a_grouped_shape_is_found_and_masked_with_the_same_name(self):
        for label, tokens in VARIANTS.items():
            for token in tokens:
                with self.subTest(label=label, token=token[:12]):
                    self.assertTrue(RECENT[label][0].search(token))
                    self.assert_masked("토큰은 " + token + " 입니다", token, label)
                    if label != "AWS 임시·식별 키":
                        self.assertFalse(old_mask_lists_catch(token), "옛 목록이 이미 막는 접두어는 아니다")

    def test_the_length_boundaries_are_exact(self):
        for label, (_factory, shortest, longer_matches) in SAMPLES.items():
            with self.subTest(label=label):
                pattern = RECENT[label][0]
                self.assertTrue(pattern.search(sample(label, shortest)), "걸리는 가장 짧은 모양")
                self.assertFalse(pattern.search(sample(label, shortest - 1)), "한 글자만 모자라도 아니다")
                self.assertEqual(bool(pattern.search(sample(label, shortest + 10))), longer_matches)

    def test_a_letter_or_digit_right_before_the_prefix_means_it_is_not_a_token(self):
        for label in SAMPLES:
            with self.subTest(label=label):
                pattern = RECENT[label][0]
                self.assertFalse(pattern.search("a" + sample(label)))
                self.assertFalse(pattern.search("9" + sample(label)))

    def test_an_underscore_a_dash_or_any_symbol_before_the_prefix_still_counts_as_a_boundary(self):
        for label in SAMPLES:
            for before in ("_", "-", "=", ":", "/", '"', "(", "한"):
                with self.subTest(label=label, before=before):
                    self.assertTrue(RECENT[label][0].search(before + sample(label)))

    def test_the_hugging_face_token_ends_at_its_own_last_character(self):
        pattern = RECENT["Hugging Face 토큰"][0]
        token = sample("Hugging Face 토큰")
        self.assertTrue(pattern.search(token + " 끝"))
        self.assertTrue(pattern.search(token + "."))
        self.assertTrue(pattern.search(token + "Z"), "영숫자가 더 이어지면 더 긴 토큰이다")
        self.assertFalse(pattern.search(token + "_more"), "밑줄로 이어지는 긴 이름은 토큰이 아니다")

    def test_nvidia_style_keys_need_a_digit_and_a_capital_so_hyphenated_slugs_are_not_keys(self):
        pattern = RECENT["NVIDIA 키"][0]
        self.assertTrue(pattern.search(sample("NVIDIA 키")))
        self.assertFalse(pattern.search("https://example.com/nvapi-how-to-use-the-nvidia-api-in-your-own-application-with-python"))
        self.assertFalse(pattern.search("nvapi-" + "abcdefghij-" * 6), "소문자와 붙임표뿐인 긴 글")
        self.assertFalse(pattern.search("nvapi-" + "ABCDEFGHIJ-" * 6), "숫자가 없다")
        self.assertFalse(pattern.search("nvapi-" + "abcdefghij1-" * 6), "대문자가 없다")

    def test_an_nvidia_key_whose_first_digit_and_capital_come_late_is_still_found_and_masked(self):
        """독립 검증 Q 의 QP1 — 숫자·대문자 조건의 앞내다보기 창은 60자다. 표본은 숫자·대문자를 맨 앞에 두었고 창을 3자로 줄여도 통과했다. 실제 키(몸 64자 무작위)는 숫자·대문자가 앞쪽에 없을 수 있다(없을 확률 약 4e-5)."""
        pattern = RECENT["NVIDIA 키"][0]
        for digit_at, upper_at in ((10, 55), (55, 10), (45, 50), (59, 60), (60, 59), (60, 58)):
            with self.subTest(digit_at=digit_at, upper_at=upper_at):
                key = nvidia_key(digit_at, upper_at)
                self.assertTrue(pattern.search(key), "첫 숫자·대문자가 몸의 61번째 글자 안에 있으면 모양이다")
                self.assertTrue(mk.has_key_shape("토큰은 " + key + " 입니다"))
                self.assert_masked("토큰은 " + key + " 입니다", key, "NVIDIA 키")

    def test_the_nvidia_look_ahead_window_is_exactly_sixty_characters(self):
        """창은 입력 길이에 선형이도록 일부러 막아 둔 값이다(문서의 '앞내다보기를 60자로'). 숫자나 대문자가 61번째 글자 뒤에서야 처음 나오면 모양으로 보지 않는다."""
        pattern = RECENT["NVIDIA 키"][0]
        self.assertFalse(pattern.search(nvidia_key(61, 5)), "첫 숫자가 62번째 글자")
        self.assertFalse(pattern.search(nvidia_key(5, 61)), "첫 대문자가 62번째 글자")
        self.assertFalse(pattern.search(nvidia_key(None, 5)), "숫자가 아예 없다")
        self.assertFalse(pattern.search(nvidia_key(5, None)), "대문자가 아예 없다")
        self.assertTrue(pattern.search(nvidia_key(60, 5)) and pattern.search(nvidia_key(5, 60)))

    def test_the_slack_app_token_middle_chunks_take_any_length_from_eight(self):
        """독립 검증 Q 의 QP2 — 가운데 두 덩어리(앱 번호 영숫자·숫자)는 8자 이상이면 모두 받는다. 표본의 길이(11·13)로 못박아도 통과했다."""
        pattern = RECENT["Slack 앱 토큰"][0]
        tail = body(64)
        for app_id in (8, 9, 10, 11, 12, 20):
            for number in (8, 9, 12, 13, 14, 30):
                with self.subTest(app_id=app_id, number=number):
                    token = cat("xa", "pp-1-", body(app_id, UPPER_DIGITS), "-", "1" * number, "-", tail)
                    self.assertTrue(pattern.search(token))
                    self.assert_masked("토큰은 " + token + " 입니다", token, "Slack 앱 토큰")
        self.assertFalse(pattern.search(cat("xa", "pp-1-", body(7, UPPER_DIGITS), "-", "1" * 13, "-", tail)), "앱 번호 덩어리가 7자")
        self.assertFalse(pattern.search(cat("xa", "pp-1-", body(11, UPPER_DIGITS), "-", "1" * 7, "-", tail)), "숫자 덩어리가 7자")
        self.assertFalse(pattern.search(cat("xa", "pp-1-", body(11, UPPER_DIGITS).lower(), "-", "1" * 13, "-", tail)), "앱 번호 덩어리는 대문자·숫자만이다")

    def test_every_open_ended_shape_masks_a_much_longer_real_key_to_its_last_character(self):
        """독립 검증 Q 의 QP3 — 꼬리 길이에 상한이 없는 모양은 실제로 더 긴 키(Stripe 는 99자)의 꼬리까지 가린다. 상한이 생기면 가림 출력(로그·화면)에 키 꼬리가 남는다(모양 검사는 통과해 관문은 막지만 출력에는 남는다)."""
        for label in OPEN_ENDED:
            for extra in (60, 200):
                with self.subTest(label=label, extra=extra):
                    token = sample(label, extra)
                    text = "토큰은 " + token + " 입니다"
                    masked = mk.mask(text)
                    self.assertEqual(masked, f"토큰은 [가림: {label}] 입니다", "긴 꼬리까지 통째로 한 표지로 바뀐다")
                    self.assertNotIn(token[-16:], masked)
                    self.assertTrue(RECENT[label][0].fullmatch(token), "모양이 키 전체에 걸린다 — 앞부분만이 아니다")

    def test_the_two_lists_cover_every_shape_and_agree_with_the_pattern_text(self):
        """위 시험이 보는 '꼬리 길이에 상한이 없는 모양' 과 길이가 정해진 다섯 모양(AWS·SendGrid·DigitalOcean·Shopify·Replicate)을 이름으로 못박는다 — 모양을 더하면 어느 쪽인지 정해야 하고, 모양의 글(`{n,}`)이 이름과 어긋나면 알린다."""
        self.assertEqual(sorted(OPEN_ENDED + FIXED_LENGTH), sorted(SAMPLES))
        self.assertEqual(len(OPEN_ENDED), 13)
        for label in OPEN_ENDED:
            with self.subTest(label=label, kind="open"):
                self.assertIn(",}", RECENT[label][0].pattern, "꼬리 길이에 상한이 없다(`{n,}`)")
        for label in FIXED_LENGTH:
            with self.subTest(label=label, kind="fixed"):
                self.assertNotIn(",}", RECENT[label][0].pattern)
                self.assertTrue(RECENT[label][0].fullmatch(sample(label)), "표본은 모양 그대로다")

    def test_a_digitalocean_token_is_lowercase_hex_only_and_a_shopify_token_takes_either_case(self):
        """독립 검증 Q 의 QP4 — 입력 변형. DigitalOcean 토큰의 몸은 소문자 16진수뿐이다(대문자를 받으면 대문자 16진 해시 곁의 `dop_v1_` 글이 걸린다). Shopify 는 지금 대소문자를 모두 받는다 — 지금 모양을 못박는다."""
        digitalocean = RECENT["DigitalOcean 토큰"][0]
        lower = body(64, HEX)
        self.assertTrue(digitalocean.search(cat("do", "p_v1_", lower)))
        self.assertNotEqual(lower, lower.upper(), "시험의 전제 — 표본에 글자(a–f)가 있다")
        self.assertFalse(digitalocean.search(cat("do", "p_v1_", lower.upper())), "모두 대문자")
        at = next(index for index in range(10, 64) if lower[index] in "abcdef")
        self.assertFalse(digitalocean.search(cat("do", "p_v1_", lower[:at] + lower[at].upper() + lower[at + 1:])), "한 글자만 대문자")
        self.assertFalse(digitalocean.search(cat("do", "p_v1_", lower[:63] + "g")), "16진수가 아닌 글자")
        shopify = RECENT["Shopify 토큰"][0]
        self.assertTrue(shopify.search(cat("sh", "pat_", body(32, HEX))))
        self.assertTrue(shopify.search(cat("sh", "pat_", body(32, HEX).upper())))
        self.assertFalse(shopify.search(cat("sh", "pat_", body(31, HEX) + "g")), "16진수가 아닌 글자")


class NormalTextTest(unittest.TestCase):
    def test_prose_that_only_describes_the_prefixes_is_not_a_token(self):
        prose = (
            "Stripe live keys start with sk_live_ followed by random characters, so never paste one.", "GitLab personal access tokens begin with glpat- and are shown only once.",
            "Create a Hugging Face token in the settings page and export it as HF_TOKEN.", "SendGrid keys start with SG. and have two parts separated by a dot.", "Slack app-level tokens start with xapp- and rotating ones with xoxe-.",
            "Groq keys start with gsk_ and Perplexity keys with pplx- and xAI keys with xai-.", "Notion integration tokens start with ntn_ these days.", "PyPI tokens start with pypi-AgEI and are long.",
            "NVIDIA build keys start with nvapi- and Replicate tokens with r8_ so keep them secret.", "DigitalOcean tokens look like dop_v1_ plus hex and Shopify tokens like shpat_ plus hex.",
            "토큰 앞머리는 hf_ 이거나 gsk_ 이거나 lin_api_ 입니다.", "키 이름은 whsec_ 로 시작하는 경우가 많습니다.",
        )
        for text in prose:
            with self.subTest(text=text[:40]):
                self.assertEqual(new_patterns_hit(text), [])
                self.assertEqual(mk.mask(text), text)
                self.assertFalse(mk.has_key_shape_anywhere(text))

    def test_long_ordinary_strings_are_not_tokens(self):
        uuid = "123e4567-e89b-12d3-a456-426614174000"
        ordinary = ("hf_" + "x" * 10, "gsk_" + "a" * 39, "xai-" + "b" * 69, "pplx-" + "c" * 39, "glpat-" + "d" * 19, "lin_api_" + "e" * 39, "ntn_" + "f" * 39, "r8_" + "g" * 36,
                    "https://example.com/blog/" + "very-long-article-slug-about-travel-" * 4, "https://example.com/files/" + pc.SHA256 + ".pdf", "commit " + pc.SHA1, "id " + uuid, "주문번호 " + "1234567890" * 6,
                    "ghcr.io/example/app:" + pc.SHA1, "docker pull example/" + "a" * 40, "sk_test_example_only", "xoxe", "xapp-1", "SG.short.short", "whsec_short", "dop_v1_" + "0" * 63, "shpat_" + "a" * 31,
                    "xhf_" + "A" * 34 + "b", "Ahf_" + "A" * 40, "axai-" + "b" * 80, "9gsk_" + "c" * 52,
                    cat("sk", "_test_", body(28)), cat("pk", "_live_", body(28)), cat("gl", "xyz-", body(20, B64URL)), cat("sh", "pxx_", body(32, HEX)), cat("do", "x_v1_", body(64, HEX)),
                    cat("AK", "IA", body(16, UPPER_DIGITS)))
        for text in ordinary:
            with self.subTest(text=text[:40]):
                self.assertEqual(new_patterns_hit(text), [])

    def test_the_hand_written_normal_texts_and_the_texts_the_app_really_prints_are_untouched_by_the_new_shapes(self):
        groups = engine.harvested_normal_texts()
        groups["pcsec1.NORMAL_TEXTS"] = list(pc.NORMAL_TEXTS)
        total = 0
        for name, texts in sorted(groups.items()):
            for index, text in enumerate(texts):
                total += 1
                self.assertEqual(new_patterns_hit(text), [], f"{name}[{index}] 이 새 모양에 걸렸다: {text[:60]!r}")
        self.assertGreater(total, 2000, "예문 모음을 거두지 못했다")

    def test_the_real_posts_in_the_fixtures_pass_the_publish_gate_with_every_list(self):
        for name in ("chance_post_ko.md", "chance_post_en.md"):
            with self.subTest(name=name):
                text = (HERE / "fixtures" / name).read_text(encoding="utf-8")
                self.assertEqual(pages.secret_labels(text), set())
                self.assertFalse(mk.has_key_shape_anywhere(text))

    def test_the_repository_own_documents_and_sources_contain_no_new_shape(self):
        checked = 0
        for folder in ("docs", "src"):
            for path in sorted((ROOT / folder).rglob("*")):
                if path.suffix not in (".md", ".py") or not path.is_file():
                    continue
                checked += 1
                with self.subTest(file=path.relative_to(ROOT).as_posix()):
                    self.assertEqual(new_patterns_hit(path.read_text(encoding="utf-8", errors="replace")), [])
        self.assertGreater(checked, 150)


class CopyGateTest(unittest.TestCase):
    """복사 관문(`ui/core/draft_rules.py`)은 주소 안에서는 알려진 키 모양만 본다 — 새 모양이 목록에 없으면 주소 속 키가 복사를 통과했다(탐침: 옛 코드는 일곱 모양 모두 통과)."""
    ADDRESSES = ("참고: https://example.com/page?x={}&y=1 입니다", "참고: https://example.com/files/{}/index.html 입니다", "이미지 https://cdn.example.com/a/{}.png", "[링크](https://example.com/?q={})")

    def test_every_new_shape_inside_a_web_address_blocks_the_copy_without_repeating_the_key(self):
        for label in SAMPLES:
            token = sample(label)
            for template in self.ADDRESSES:
                with self.subTest(label=label, address=template[:24]):
                    text = template.format(token)
                    self.assertTrue(draft_rules.has_secret(text))
                    places = draft_rules.secret_places(("본문", text))
                    self.assertTrue(places)
                    self.assertFalse(any(token[-16:] in place for place in places), "막은 자리의 미리보기에 키 글자를 되풀이하지 않는다")

    def test_the_same_shapes_in_plain_text_still_block_and_ordinary_addresses_still_pass(self):
        for label in SAMPLES:
            self.assertTrue(draft_rules.has_secret("키는 " + sample(label) + " 입니다"), label)
        for text in ("참고: https://example.com/page?x=1&y=2 입니다", "https://example.com/blog/very-long-article-slug-about-travel-and-food/", "https://example.com/files/" + pc.SHA256 + ".pdf",
                     "https://github.com/example/project/pull/49", "hf_ 로 시작하는 토큰 이야기"):
            with self.subTest(text=text[:40]):
                self.assertFalse(draft_rules.has_secret(text))


class PathologicalInputTest(unittest.TestCase):
    SEEDS = ("hf_", "xai-", "pplx-", "gsk_", "glpat-", "nvapi-", "SG.", "xapp-1-", "xoxe-1-", "sk_live_", "whsec_", "dop_v1_", "shpat_", "ntn_", "lin_api_", "r8_", "pypi-AgEIcHlwaS5vcmc")

    def test_every_pattern_is_linear_on_adversarial_input(self):
        for seed in self.SEEDS:
            for text in (seed * (200_000 // len(seed)), (seed + "A") * (200_000 // (len(seed) + 1)), seed + "a" * 199_000, "a-" * 100_000 + seed, ("nvapi-" + "A1" * 5 + "-") * 18_000):
                started = time.process_time()
                for _label, pattern, _need in mk._RECENT_PATTERNS:
                    pattern.search(text)
                self.assertLess(time.process_time() - started, 4.0, f"{seed!r} 병적 입력이 느리다")

    def test_the_whole_checks_stay_fast_on_the_worst_inputs(self):
        for text in ("hf_" * 66_000, "xai-" * 50_000, ("nvapi-" + "A1" * 5 + "-") * 12_000, "SG." * 66_000):
            started = time.process_time()
            mk.has_key_shape(text)
            mk.mask(text)
            self.assertLess(time.process_time() - started, 8.0)

    def test_masking_a_big_text_with_a_token_inside_stays_fast(self):
        token = sample("Groq 키")
        text = ("평범한 글 " * 30_000) + token + (" 끝" * 10_000)
        started = time.process_time()
        masked = mk.mask(text)
        self.assertLess(time.process_time() - started, 4.0)
        self.assertNotIn(token[-16:], masked)


class WindowedScanTest(unittest.TestCase):
    def test_it_is_the_same_as_the_plain_check_for_texts_within_the_limit(self):
        for text in ("", "평범한 글", "키는 " + sample("Groq 키") + " 입니다", None, 123, ["a", sample("xAI 키")], b"bytes"):
            with self.subTest(text=str(text)[:20]):
                self.assertEqual(mk.has_key_shape_anywhere(text), mk.has_key_shape(text))

    def test_a_value_that_cannot_become_text_is_false_like_the_plain_check(self):
        class Broken:
            def __str__(self):
                raise RuntimeError("no text")

        self.assertFalse(mk.has_key_shape(Broken()))
        self.assertFalse(mk.has_key_shape_anywhere(Broken()))

    def test_a_key_hidden_after_the_plain_checks_limit_is_found(self):
        text = "a " * 150_000 + sample("Groq 키")                                         # 30만 글자 뒤
        self.assertGreater(len(text), mk.MAX_MASK_INPUT + 50_000)
        self.assertFalse(mk.has_key_shape(text), "가리기용 검사는 앞 20만 자만 본다")
        self.assertTrue(mk.has_key_shape_anywhere(text))

    def test_a_key_crossing_a_window_edge_is_found_at_every_offset_near_the_edges(self):
        token = sample("Hugging Face 토큰")
        step = mk._SCAN_WINDOW - mk._SCAN_OVERLAP
        total = mk._SCAN_WINDOW * 3
        for edge in (mk._SCAN_WINDOW, step, mk._SCAN_WINDOW + step):
            for shift in (-len(token) - 1, -len(token) // 2, -1, 0, 5):
                with self.subTest(edge=edge, shift=shift):
                    at = edge + shift
                    text = "x" * at + " " + token + " " + "y" * (total - at)
                    self.assertTrue(mk.has_key_shape_anywhere(text))

    def test_the_overlap_is_longer_than_any_new_shape_so_an_edge_cannot_cut_one(self):
        longest = max(len(sample(label)) for label in SAMPLES)
        self.assertGreater(mk._SCAN_OVERLAP, longest * 2)
        self.assertLess(mk._SCAN_WINDOW, mk.MAX_MASK_INPUT)
        self.assertLess(mk._SCAN_OVERLAP, mk._SCAN_WINDOW)

    def test_a_clean_big_text_is_clean(self):
        self.assertFalse(mk.has_key_shape_anywhere("평범한 문장입니다. " * 60_000))


def leaks(text, token):
    return token[-16:] in text


class PublishGateTest(unittest.TestCase):
    def blocked(self, text):
        """`check_post` 가 낸 AppError(막지 않았으면 None)."""
        try:
            pages.check_post(tp.Post(tp.KO_PATH, text))
        except AppError as error:
            return error
        return None

    def test_the_gate_accepts_a_plain_post(self):
        self.assertIsNone(self.blocked(tp.KO_TEXT))
        self.assertEqual(pages.secret_labels(tp.KO_TEXT), set())

    def test_every_new_shape_blocks_the_post_and_the_error_never_repeats_the_key(self):
        for label in SAMPLES:
            with self.subTest(label=label):
                token = sample(label)
                error = self.blocked(tp.KO_TEXT + f"\n실수로 {token} 가 들어갔다\n")
                self.assertIsNotNone(error)
                self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
                self.assertFalse(leaks(error.detail + error.log_line() + str(error), token))
                self.assertIn("키 모양 문자열", error.detail)

    def test_shapes_the_copy_and_save_gates_block_were_missed_by_this_gate_until_now(self):
        cases = {
            "OpenAI project key": cat("sk", "-proj-", body(60, B64URL)), "Anthropic key": cat("sk", "-ant-api03-", body(80, B64URL)), "OpenRouter key": cat("sk", "-or-v1-", body(64, HEX)),
            "npm token": cat("np", "m_", body(36)), "JWT": cat("ey", "J", body(30, B64URL), ".", "ey", "J", body(20, B64URL), ".", body(30, B64URL)), "Bearer": cat("Bear", "er ", body(32, B64URL)),
            "Slack webhook": cat("https://hooks.slack", ".com/services/T01234567/B01234567/", body(24)), "encrypted private key header": cat("-----", "BEGIN ENCRYPTED PRIVATE KEY", "-----"),
            "AWS temporary key": cat("AS", "IA", body(16, UPPER_DIGITS)), "named access token": "access_token=" + body(30, B64URL),
        }
        for label, token in cases.items():
            with self.subTest(label=label):
                self.assertFalse(find_secrets(mk._strip_invisible(token)), "정본(vendor/)만으로는 걸리지 않던 모양이다")
                error = self.blocked(tp.KO_TEXT + f"\n실수로 {token} 가 들어갔다\n")
                self.assertIsNotNone(error)
                self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
                self.assertFalse(leaks(error.detail + str(error), token))

    def test_the_names_in_the_error_come_from_the_known_lists_and_never_from_the_text(self):
        google = cat("AI", "za", body(35, B64URL))
        self.assertEqual(pages.secret_labels("키 " + google), {"Google API 키"}, "정본과 검사기가 같은 이름을 쓴다")
        telegram = cat("123456789", ":AA", body(33, B64URL))
        self.assertEqual(pages.secret_labels("키 " + telegram), {"Telegram 봇 토큰"}, "정본이 이름을 아는 모양은 정본의 이름 그대로")
        self.assertEqual(pages.secret_labels("키 " + sample("Groq 키")), {"키·토큰 모양"}, "이름 없이 가리기 목록만 아는 모양은 고정된 이름 하나")
        self.assertEqual(pages.secret_labels("키 " + cat("sk", "-proj-", body(60, B64URL))), {"키·토큰 모양"})
        text = tp.KO_TEXT + "\n키 " + google + "\n"
        self.assertEqual(self.blocked(text).detail, "키 모양 문자열: " + ", ".join(sorted(pages.secret_labels(text))), "오류 세부는 이름뿐이다 — 글 조각이 없다(독립 검증 S 의 SP-6 F3)")

    def test_a_key_padded_with_thousands_of_invisible_characters_across_a_window_edge_still_blocks_the_post(self):
        """독립 검증 S 의 SP-6 F1 — 관문은 글 전체의 보이지 않는 글자를 창으로 나누기 전에 먼저 지운다. 지우지 않으면 4096개를 넘는 패딩이 낀 키가 150000자 창의 겹침(4096) 경계에 걸쳐 관문을 지난다."""
        token = sample("Groq 키")
        half = len(token) // 2
        step = 150_000 - 4_096
        head = tp.KO_TEXT + "\n" + "a " * ((step - 1_000 - len(tp.KO_TEXT) - 1) // 2)
        span = len(token) + 6_000
        self.assertTrue(len(head) < step and len(head) + span > 150_000, "키가 두 창 어디에도 통째로 들어가지 않는 자리다(앞 창은 150000자에서 끝나고 뒤 창은 145904자에서 시작한다)")
        text = head + token[:half] + chr(0x200B) * 6_000 + token[half:] + " b" * 30_000
        self.assertGreater(len(text), mk.MAX_MASK_INPUT)
        self.assertLess(len(text.encode("utf-8")), pages.MAX_POST_BYTES)
        error = self.blocked(text)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")

    def test_a_key_split_by_invisible_characters_is_still_blocked(self):
        token = sample("Groq 키")
        for hider in (0x200B, 0x00AD, 0x2060):
            with self.subTest(hider=hex(hider)):
                self.assertIsNotNone(self.blocked(tp.KO_TEXT + "\n실수 " + token[:10] + chr(hider) + token[10:] + " 로\n"))

    def test_a_key_after_the_masking_limit_still_blocks_the_post(self):
        token = sample("xAI 키")
        text = tp.KO_TEXT + "a " * 190_000 + token + "\n"                                # 약 38만 글자 — 글 상한(50만 바이트) 안
        self.assertLess(len(text.encode("utf-8")), pages.MAX_POST_BYTES)
        self.assertGreater(len(text), mk.MAX_MASK_INPUT + 100_000)
        error = self.blocked(text)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")

    def test_the_commit_title_gets_the_same_lists(self):
        for label in ("Groq 키", "Stripe 비밀 키"):
            with self.subTest(label=label):
                post = tp.Post(tp.KO_PATH, tp.KO_TEXT)
                with mock.patch.object(capabilities, "EXTERNAL_WRITE", True):
                    with self.assertRaises(AppError) as caught:
                        pages.commit_post(str(ROOT / "no-such-repo"), post, title="제목 " + sample(label))
                self.assertEqual(caught.exception.code, "SECRET_IN_TEXT_BLOCKED")
                self.assertIn("commit 제목", caught.exception.detail)
                self.assertFalse(leaks(str(caught.exception) + caught.exception.detail, sample(label)))

    def test_ordinary_posts_pass_even_with_many_kinds_of_numbers_and_addresses(self):
        text = tp.KO_TEXT + "\n" + "\n".join(("주문번호 1234567890123456 입니다", "해시 " + pc.SHA256, "커밋 " + pc.SHA1, "링크 https://example.com/a?page=2&sort=asc", "Hugging Face 토큰은 hf_ 로 시작합니다",
                                              "영어 문장: Bearer authentication is a scheme, and an access token expires.", "사진 파일 IMG_20261111_123456.jpg", "버전 v1.2.3-rc.1+build.5"))
        self.assertIsNone(self.blocked(text))


class SourceRulesTest(unittest.TestCase):
    def test_the_new_pattern_source_has_no_complete_key_and_no_tilde_or_link(self):
        text = (ROOT / "src" / "chanceblog_desktop" / "security" / "mask.py").read_text(encoding="utf-8")
        start = text.index("_RECENT_PATTERNS = (")
        block = text[start:text.index("\n)\n", start)]
        self.assertNotIn(chr(126), block)
        self.assertNotIn("http", block)
        self.assertEqual(len(re.findall(r'\("[^"]+", re\.compile\(', block)), 18)

    def test_the_publish_gate_calls_the_one_shared_function_for_the_text_and_for_the_title(self):
        text = (ROOT / "src" / "chanceblog_desktop" / "publish" / "pages.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("secret_labels("), 4, "정의 하나·글 검사·commit 제목 검사 둘(commit_post·build_branch_commit)")
        self.assertEqual(text.count("find_secrets("), 1, "정본 패턴은 `secret_labels` 안에서만 부른다")


if __name__ == "__main__":
    unittest.main()
