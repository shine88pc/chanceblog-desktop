"""줄 구분 글자로 쪼갠 키·토큰 시험(SECSEP, 결정 D-760) — 저장 검사(`security/scan.py`)와 가리기 엔진(`security/mask.py`)이 U+0085·U+2028·U+2029 같은 줄 구분 글자 한가운데에
끼어 쪼개진 키·토큰 모양을 알아보는가. 독립 검증이 직접 재현한 길: 가짜 키를 이 글자로 쪼갠 글은 가져오기 검사를 지나 저장되고 글 검토 화면 미리보기가 두 쪽을 그대로 냈다.

지키는 것:
  1) **글자 집합**: 저장 검사가 지우고 찾는 줄 구분 글자는 아홉(U+000B·U+000C·U+001C–U+001F·U+0085·U+2028·U+2029)이고, 모든 코드 포인트에서 '공백으로 읽히는 제어·줄 구분·문단 구분 글자 중 탭·LF·CR 을 뺀 것'과 같다.
     저장 검사가 지우는 글자는 가리기 엔진이 지우는 글자의 부분집합이다(어긋나 한쪽만 고쳐지면 빨개진다) — 엔진은 이 아홉을 범주(제어·줄 구분·문단 구분)로 이미 지운다.
  2) **저장 검사**: 여섯 유형(Google·GitHub·Bearer·OAuth·AWS·PEM)의 표본을 아홉 글자 × 쪼개는 자리(접두어 뒤·첫 글자 뒤·가운데·끝 직전·여러 곳)로 쪼개면 정확히 한 건이고, 줄·열은 쪼갠 글 그대로의 원문 위치다.
     길이는 지운 뒤에 센다(짧은 키는 쪼개도 짧다).
  3) **더 엄격한 쪽만**: 쪼개지 않아도 찾던 것(앞뒤에 영숫자 이웃이 붙은 키)은 쪼개는 글자가 이웃 사이에 있어도 **같은 자리**로 찾고, 평범한 글(줄 구분 글자가 든 한국어·영어 글, 키 접두어만 있는 글)은 새로 걸리지 않는다.
  4) **가리기 엔진**: 모든 키·토큰 모양(여섯 유형 + Slack·OpenAI·Anthropic·Stripe·GitLab·npm 같은 엔진 목록)과 이름 붙은 비밀(`password: 값`·`secret=값`)은 쪼개도 가려지고, 글자는 출력에서 지워진다.
  5) **같은 판정**: 한 길의 판정은 쪼갠 값과 쪼개지 않은 값이 같다 — 저장 검사·서비스 `check_no_secret_shape`·초안 복사 관문·가리기 엔진·화면 글(`display_text`)·올리기 직전 관문(`secret_labels`).
     화면 어댑터의 가져오기는 쪼갠 여섯 유형을 쪼개지 않은 것과 같은 고정 문장으로 거절하고 아무것도 저장하지 않는다.
  6) **병적 입력**: 구분 글자만 반복·키 모양 반복·한 글자 사이마다 구분 글자 — 6,400·64,000자에서 선형 시간이다.
  7) **알려진 한계(고정)**: 미리보기 변환(`render/markdown.py`)이 U+0085·U+2028·U+2029 를 공백으로 바꿔서, 저장 검사가 아는 여섯 유형 밖의 모양(Slack·OpenAI·Stripe …)을 쪼갠 글은 가져오기를 지나 미리보기에 두 쪽이 보인다.
     이 갈래는 `ui/`·`render/` 를 고치지 않는다 — 그 시험은 한계를 못박은 것이고 변환이 고쳐지면 빨개져서 알려 준다. 눈에 안 보이는 글자(U+200B·소프트 하이픈 …)로 쪼갠 것은 저장 검사의 기존 한계 그대로다.
가짜 비밀은 모두 실행할 때 조각을 이어 붙여 만든다. 네트워크·실제 비밀 없이 돈다.
"""
import random
import sys
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as S  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.content.model import ContentProject  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import pages as publish_pages  # noqa: E402
from chanceblog_desktop.render.pages import render_pages_post  # noqa: E402
from chanceblog_desktop.security import mask as engine, scan  # noqa: E402
from chanceblog_desktop.security.shape import named_secret_spans  # noqa: E402
from chanceblog_desktop.service import gate, projects  # noqa: E402
from chanceblog_desktop.ui import posts_adapter  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules, post_rules, posts  # noqa: E402
from chanceblog_desktop.ui.core.text import display_text  # noqa: E402

SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
NINE = (0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x1F, 0x85, 0x2028, 0x2029)             # 저장 검사가 지우고 찾는 줄 구분 글자(코드 포인트)
THREE = (0x85, 0x2028, 0x2029)                                                 # 지시서가 꼭 막으라고 한 셋(미리보기 변환이 공백으로 바꾸는 것들)
CONVERTER_KEEPS = THREE                                                        # 미리보기 변환기가 지우지 않고 공백으로 바꾸는 글자
LIMIT_SECONDS = 0.5                                                            # 10만 자 병적 입력 한 건의 시간 상한(기존 검사기 시험과 같다 — 세 번 재서 빠른 쪽)
SOURCES = {"scan": ROOT / "src" / "chanceblog_desktop" / "security" / "scan.py", "mask": ROOT / "src" / "chanceblog_desktop" / "security" / "mask.py"}


def label(code):
    return f"U+{code:04X}"


def split_at(token, positions, codes):
    """`token` 의 `positions`(글자 앞 자리, 0 이 아닌 값) 마다 `codes` 의 글자를 차례로 끼운다."""
    pieces, last = [], 0
    for index, position in enumerate(sorted(positions)):
        pieces.append(token[last:position])
        pieces.append(chr(codes[index % len(codes)]))
        last = position
    pieces.append(token[last:])
    return "".join(pieces)


def cut_sets(token, prefix):
    """쪼개는 자리 다섯 가지 → {이름: 자리들} — 접두어 바로 뒤·첫 글자 뒤·가운데·끝 직전·여러 곳(서로 다른 네 곳)."""
    size = len(token)
    found = {"첫 글자 뒤": (1,), "가운데": (size // 2,), "끝 직전": (size - 1,), "여러 곳": tuple(sorted({2, size // 3, 2 * size // 3, size - 2}))}
    if 1 < prefix < size - 1:
        found["접두어 바로 뒤"] = (prefix,)
    return found


def samples():
    """(이름, 유형, 앞 낱말, 발견 글, 접두어 길이) — 앞 낱말은 쪼개지 않는다. 발견 글이 곧 쪼갤 글이다(Bearer·이름 붙은 값은 값만)."""
    rows = [("google", "google_api_key", "key=", S.google(), 4), ("github ghp_", "github_token", "token: ", S.github("p"), 4), ("github ghs_", "github_token", "", S.github("s"), 4),
            ("github_pat_", "github_token", "", S.github_pat(), 11), ("bearer", "bearer_token", "Authorization: Bearer ", S.bearer_value(), 0), ("ya29.", "oauth_token", "", S.ya29(), 5),
            ("1//", "oauth_token", "", S.refresh(), 3), ("GOCSPX-", "oauth_token", "", S.gocspx(), 7), ("jwt", "oauth_token", "", S.jwt(), 3),
            ("access_token=", "oauth_token", "access_token=", S.body(30, S.B64URL, 8), 0), ("refresh_token", "oauth_token", 'refresh_token": "', S.body(28, S.B64URL, 2), 0),
            ("aws AKIA", "aws_access_key", "id ", S.aws("AKIA"), 4), ("aws ASIA", "aws_access_key", "", S.aws("ASIA"), 4),
            ("pem RSA", "pem_private_key", "", S.pem("RSA "), 5), ("pem", "pem_private_key", "", S.pem(""), 5)]
    return tuple(rows)


CONTEXTS = (
    ("줄 사이(LF)", lambda lead, piece: "앞 줄\n" + lead + piece + "\n뒷 줄"),
    ("한글 바로 옆", lambda lead, piece: "토큰은" + lead + piece + "입니다"),
    ("CRLF", lambda lead, piece: "앞 줄\r\n둘째 줄\r\n" + lead + piece + "\r\n뒷 줄"),
)


def engine_shapes():
    """가리기 엔진이 아는 모양 — 저장 검사의 여섯 유형 + 그 밖의 모양(Slack·OpenAI·Anthropic·Stripe·GitLab·npm·Hugging Face). (이름, 글, 저장 검사가 아는 유형인가)."""
    return (("aws", S.aws(), True), ("github", S.github(), True), ("google", S.google(), True), ("jwt", S.jwt(), True),
            ("slack", "xo" + "xb-" + "1234567890-" + S.body(24, S.ALNUM), False), ("openai", "sk-" + "proj-" + S.body(40, S.B64URL), False),
            ("anthropic", "sk-" + "ant-" + "api03" + "-" + S.body(40, S.B64URL), False), ("stripe", "sk_" + "live_" + S.body(28, S.ALNUM), False),
            ("gitlab", "gl" + "pat-" + S.body(24, S.B64URL), False), ("npm", "npm_" + S.body(36, S.ALNUM), False), ("huggingface", "hf_" + S.body(36, S.ALNUM), False))


def hidden(output, token):
    """출력에 키의 연속 여섯 글자가 하나도 없는가(실패 출력에 키를 찍지 않으려고 불리언만)."""
    return not S.leaked(output, token, 6)


class SeparatorSetTest(unittest.TestCase):
    def test_the_nine_codes_are_exactly_whitespace_that_is_a_control_or_line_or_paragraph_separator_without_tab_lf_cr(self):
        """모든 코드 포인트에서: 공백으로 읽히고(`str.isspace`) 범주가 제어·줄 구분·문단 구분(엔진이 지우는 범주)인 글자에서 탭·LF·CR 을 뺀 것이 저장 검사의 아홉이다."""
        derived = tuple(code for code in range(0x110000) if chr(code).isspace() and unicodedata.category(chr(code)) in ("Cc", "Zl", "Zp") and code not in (0x09, 0x0A, 0x0D))
        self.assertEqual(derived, tuple(sorted(NINE)))
        self.assertEqual(tuple(sorted(scan._SPLIT_CODES)), tuple(sorted(NINE)), "저장 검사의 목록이 아홉이 아니다")
        self.assertEqual(len(set(scan._SPLIT_CODES)), len(scan._SPLIT_CODES), "같은 글자가 두 번 있다")

    def test_the_engine_deletes_every_one_of_the_nine_and_the_scan_set_is_a_subset_of_what_the_engine_deletes_for_every_code_point(self):
        for code in NINE:
            with self.subTest(label(code)):
                self.assertEqual(engine._strip_invisible("가" + chr(code) + "나"), "가나")
        for code in scan._SPLIT_CODES:
            self.assertEqual(engine._strip_invisible(chr(code)), "", f"{label(code)}: 저장 검사는 지우는데 엔진은 안 지운다")
        for code in range(0x110000):                                         # 거꾸로도: 공백으로 읽히는 제어·구분 글자(탭·LF·CR 말고)를 엔진이 지우면 저장 검사도 지운다
            if chr(code).isspace() and engine._strip_invisible(chr(code)) == "" and code not in (0x09, 0x0A, 0x0D):
                self.assertIn(code, scan._SPLIT_CODES, f"{label(code)}: 엔진은 공백으로 읽히는 이 글자를 지우는데 저장 검사는 안 지운다")

    def test_the_scan_never_deletes_tab_lf_cr_spaces_or_the_invisible_characters_of_its_documented_limit(self):
        token = S.github()
        half = len(token) // 2
        for code in (0x09, 0x0A, 0x0D, 0x20, 0xA0, 0x3000, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0xAD, 0xFE0F, 0x1680, 0x180E, 0x00, 0x01, 0x7F, 0x80, 0x9F):
            with self.subTest(label(code)):
                text = "앞 " + token[:half] + chr(code) + token[half:] + " 뒤"
                self.assertEqual(scan.scan_secrets(text), (), "기존 한계(공백·줄바꿈·눈에 안 보이는 글자로 쪼갠 토큰은 못 찾는다)가 넓어졌다")
                self.assertFalse(scan.has_secret(text))

    def test_a_text_without_any_of_the_nine_is_looked_at_once_and_gives_the_same_view(self):
        text = "가나다 " + S.github() + " 라마바"
        self.assertEqual(scan._without_splitters(text), (text, None))
        self.assertIs(scan._without_splitters(text)[0], text)

    def test_the_second_eye_is_used_only_when_one_of_the_nine_is_in_the_text(self):
        calls = []
        real = scan._matches

        def spy(text, mapping):
            calls.append(mapping is None)
            return real(text, mapping)
        with mock.patch.object(scan, "_matches", spy):
            scan.scan_secrets("평범한 글 " + S.github() + " 끝")
            self.assertEqual(calls, [True], "구분 글자가 없는 글은 한 번만 본다(비용이 늘지 않는다)")
            calls.clear()
            scan.scan_secrets("평범한 글" + chr(0x2028) + " 끝")
            self.assertEqual(calls, [True, False], "구분 글자가 있으면 원문 눈 다음에 지운 글 눈")

    def test_the_deleted_text_and_the_position_table_map_every_kept_character_back_to_the_original(self):
        rng = random.Random(20261126)
        alphabet = list("abcXYZ019 가나😀") + [chr(code) for code in NINE] * 4 + ["\n", "\r\n", chr(0x200B)]
        for round_number in range(400):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
            clean, mapping = scan._without_splitters(text)
            with self.subTest(round_number):
                self.assertEqual(clean, "".join(char for char in text if ord(char) not in NINE))
                if mapping is None:
                    self.assertEqual(clean, text)
                    continue
                self.assertEqual(len(mapping), len(text) - len(clean))
                self.assertEqual(mapping, sorted(mapping))
                for index, char in enumerate(clean):
                    self.assertEqual(text[scan._original_index(index, mapping)], char)
                self.assertEqual([scan._original_index(index, mapping) for index in range(len(clean))], [at for at, char in enumerate(text) if ord(char) not in NINE])


class ScanSeesThroughTest(unittest.TestCase):
    def assert_found_once(self, text, kind, piece, lead="", note=""):
        """쪼갠 글 `piece` 가 정확히 한 건이고 줄·열이 원문 위치와 같다. 단 첫 쪼개는 글자 앞의 조각(앞 낱말 `lead` 와 함께)이 혼자서도 키로 읽히면(끝 직전을 쪼갠 긴 키) 원문 눈이 그 자리를 이미 짚으므로
        그 자리가 그대로 남는다(예전과 같다 — 원문 눈의 결과는 달라지지 않는다)."""
        result = scan.scan_secrets(text, "본문")
        line, col_start, col_end = S.locate(text, piece)
        first = piece[:min(piece.index(chr(code)) for code in NINE if chr(code) in piece)]
        alone = scan.scan_secrets(lead + first)
        if alone:
            col_end = col_start + (alone[0].col_end - alone[0].col_start)
        self.assertEqual(S.triples(result), [(kind, line, col_start, col_end)], note)
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.assertTrue(piece.startswith(lines[line - 1][col_start - 1:col_end]), "발견 자리의 글이 쪼갠 글의 앞부분이 아니다")
        self.assertTrue(scan.has_secret(text), note)

    def test_every_sample_split_at_every_place_by_every_one_of_the_nine_is_one_finding_at_the_original_position(self):
        count = 0
        for name, kind, lead, token, prefix in samples():
            for cut_name, positions in cut_sets(token, prefix).items():
                for code in NINE:
                    for context_name, build in CONTEXTS:
                        piece = split_at(token, positions, (code,))
                        with self.subTest(sample=name, cut=cut_name, code=label(code), context=context_name):
                            self.assert_found_once(build(lead, piece), kind, piece, lead)
                        count += 1
        self.assertGreater(count, 1000)

    def test_one_key_cut_in_several_places_with_different_separators_is_still_one_finding(self):
        for name, kind, lead, token, prefix in samples():
            positions = cut_sets(token, prefix)["여러 곳"]
            for start in range(len(NINE)):
                codes = tuple(NINE[(start + index) % len(NINE)] for index in range(len(positions)))
                piece = split_at(token, positions, codes)
                with self.subTest(sample=name, start=start):
                    self.assert_found_once("앞 줄\n" + lead + piece + " 뒤", kind, piece, lead)

    def test_a_key_written_in_fullwidth_letters_and_split_by_every_one_of_the_nine_is_one_finding_at_the_original_position(self):
        """호환(전각) 글자로 쓴 키도 쪼개면 찾는다 — 지운 글은 호환 글자를 접은 글(`_fold`)에서 만들어야 한다. 원문에서 만들면 전각 글자 + 구분 글자 우회가 조용히 열린다(독립 검증 S 권고-4·Q 권고-1)."""
        def wide(text):
            return "".join(chr(ord(char) + 0xFEE0) if "!" <= char <= chr(126) else char for char in text)
        for name, kind, lead, token, prefix in samples():
            whole = wide(token)
            self.assertNotEqual(whole, token, name)
            text = "앞 줄\n" + lead + whole + "\n뒷 줄"
            with self.subTest(sample=name, code="쪼개지 않음"):
                self.assertEqual(S.triples(scan.scan_secrets(text)), [(kind, *S.locate(text, whole))], "대조: 쪼개지 않은 전각 키는 원래도 한 건이다")
            for code in NINE:
                half = len(whole) // 2
                piece = whole[:half] + chr(code) + whole[half:]
                text = "앞 줄\n" + lead + piece + "\n뒷 줄"
                with self.subTest(sample=name, code=label(code)):
                    self.assertEqual(S.triples(scan.scan_secrets(text)), [(kind, *S.locate(text, piece))])
                    self.assertTrue(scan.has_secret(text))

    def test_two_separators_in_a_row_and_a_run_of_separators_inside_a_key_count_as_nothing(self):
        for name, kind, lead, token, prefix in samples():
            middle = len(token) // 2
            for run in (chr(0x2028) * 2, chr(0x2028) + chr(0x2029) + chr(0x85), "".join(chr(code) for code in NINE), chr(0x1C) * 50):
                piece = token[:middle] + run + token[middle:]
                with self.subTest(sample=name, run=len(run)):
                    self.assert_found_once("앞 " + lead + piece + " 뒤", kind, piece, lead)

    def test_a_word_split_inside_bearer_and_a_split_inside_a_named_value_name_are_found_too(self):
        value = S.bearer_value()
        for code in NINE:
            with self.subTest("bearer 낱말 " + label(code)):
                text = "Authorization: Bear" + chr(code) + "er " + value
                self.assertEqual(S.triples(scan.scan_secrets(text)), [("bearer_token", *S.locate(text, value))])
            with self.subTest("이름 " + label(code)):
                text = "acc" + chr(code) + "ess_token=" + S.body(30, S.B64URL, 8)
                self.assertEqual([item.kind for item in scan.scan_secrets(text)], ["oauth_token"])
            with self.subTest("접두어 " + label(code)):
                text = "Bearer" + chr(code) + " " + value
                self.assertEqual(S.triples(scan.scan_secrets(text)), [("bearer_token", *S.locate(text, value))])

    def test_a_separator_between_bearer_and_the_value_with_no_space_is_not_a_split_it_is_nothing_in_between(self):
        value = S.bearer_value()
        for code in NINE:
            with self.subTest(label(code)):
                self.assertEqual(scan.scan_secrets("Bearer" + chr(code) + value), (), "낱말과 값 사이에 공백이 없으면 지워도 한 낱말이다(쪼갠 값이 아니다)")

    def test_the_length_counts_after_the_deletion_so_a_short_key_stays_short_and_the_shortest_long_one_is_found(self):
        pairs = (("google", S.google(length=34), S.google(length=35), "google_api_key"), ("github", S.github(length=35), S.github(length=36), "github_token"),
                 ("aws", S.aws(length=15), S.aws(length=16), "aws_access_key"), ("ya29", S.ya29(length=19), S.ya29(length=20), "oauth_token"))
        for name, short, enough, kind in pairs:
            for code in NINE:
                with self.subTest(name=name, code=label(code)):
                    cut = len(short) // 2
                    self.assertEqual(scan.scan_secrets("앞 " + short[:cut] + chr(code) + short[cut:] + " 뒤"), (), "쪼개는 글자를 글자로 세어 짧은 키가 길어졌다")
                    piece = enough[:cut] + chr(code) + enough[cut:]
                    self.assertEqual(S.triples(scan.scan_secrets("앞 " + piece + " 뒤")), [(kind, 1, 3, 2 + len(piece))])

    def test_positions_stay_in_original_characters_after_noise_lines_and_separators_before_the_key(self):
        token = S.github()
        piece = token[:10] + chr(0x2028) + token[10:20] + chr(0x85) + token[20:]
        noise = "😀" + chr(0x301) * 3 + chr(0x2029) + chr(0x0B) + "가" + chr(0x200B) + chr(0x1C)
        for newline in ("\n", "\r\n", "\r"):
            text = newline.join(["첫 줄" + noise, noise * 4 + "둘째 줄", "셋째 줄 " + noise + " " + piece + noise + " 끝", "마지막"])
            with self.subTest(newline=repr(newline)):
                self.assert_found_once(text, "github_token", piece)

    def test_a_separator_at_the_start_or_the_end_of_the_text_and_right_next_to_a_split_key_moves_no_position(self):
        token = S.google()
        piece = token[:15] + chr(0x2028) + token[15:]
        for code in NINE:
            edge = chr(code)
            for number, (text, start) in enumerate(((edge + piece, 2), (piece + edge, 1), (edge + piece + edge, 2), (edge * 3 + piece + edge * 3, 4), ("앞" + edge + piece + edge + "뒤", 3), (edge, None), (edge * 5, None))):
                with self.subTest(code=label(code), case=number):
                    expected = [] if start is None else [("google_api_key", 1, start, start + len(piece) - 1)]
                    self.assertEqual(S.triples(scan.scan_secrets(text)), expected)
                    self.assertEqual(scan.has_secret(text), bool(expected))

    def test_random_mixtures_of_noise_newlines_separators_and_split_keys_are_found_exactly_where_they_were_put(self):
        """고정 씨앗으로 만든 글 300개 — 잡음(줄 구분 글자 포함)과 줄바꿈 사이에 쪼갠 키·쪼개지 않은 키 1–5개를 넣고, 검사기와 따로 센 줄·열과 같은지 본다(쪼개는 자리는 앞쪽 절반 — 앞 조각이 혼자 키로 읽히지 않는다)."""
        rng = random.Random(20261125)
        pool = [(kind, lead, token) for _name, kind, lead, token, _prefix in samples()]
        atoms = ["가나다", "hello world", " ", "\t", "😀", chr(0x301), chr(0x200B), "…", "한글 문장입니다", ".", ",", "(", ")", '"', "토큰"] + [chr(code) for code in NINE]
        glue = [" ", "\n", "\r\n", "\r", "\t", "가", "😀", chr(0x3000), "\n\n", " \r\n "]
        for round_number in range(300):
            parts, expected, length = [], [], 0
            for _ in range(rng.randint(1, 5)):
                noise = "".join(rng.choice(atoms) for _ in range(rng.randint(0, 5)))
                before, after = rng.choice(glue), rng.choice(glue)
                kind, lead, token = rng.choice(pool)
                cuts = sorted(rng.sample(range(1, len(token) // 2), rng.randint(0, 3))) if rng.random() < 0.8 else []
                piece = split_at(token, cuts, [rng.choice(NINE) for _ in cuts] or [0x2028])
                parts += [noise, before, lead, piece, after]
                length += len(noise) + len(before) + len(lead)
                expected.append((kind, length, piece))
                length += len(piece) + len(after)
            text = "".join(parts)
            want = []
            for kind, offset, piece in expected:
                line, col = S.position(text, offset)
                want.append((kind, line, col, col + len(piece) - 1))
            with self.subTest(round_number):
                self.assertEqual(S.triples(scan.scan_secrets(text)), want)

    def test_several_split_keys_and_whole_keys_are_all_found_in_text_order(self):
        google, github, aws = S.google(), S.github(), S.aws()
        text = "\n".join(["가", aws[:8] + chr(0x2029) + aws[8:], "x " + github + " y " + google[:20] + chr(0x85) + google[20:], "", github[:5] + chr(0x1E) + github[5:] + " 끝"])
        result = scan.scan_secrets(text)
        self.assertEqual([(item.kind, item.line) for item in result], [("aws_access_key", 2), ("github_token", 3), ("google_api_key", 3), ("github_token", 5)])
        self.assertEqual(list(result), sorted(result, key=lambda item: (item.line, item.col_start)))
        self.assertEqual(S.triples(result)[0][2:], S.locate(text, aws[:8] + chr(0x2029) + aws[8:])[1:])

    def test_scan_fields_works_with_split_keys_and_a_separator_in_a_label_is_still_refused(self):
        token = S.google()
        piece = token[:12] + chr(0x2028) + token[12:]
        found = scan.scan_fields({"제목": "제목 " + piece, "본문": None, "출처": "https://example.invalid/?k=" + piece})
        self.assertEqual([(item.where, item.kind) for item in found], [("제목", "google_api_key"), ("출처", "google_api_key")])
        with self.assertRaises(ValueError):
            scan.scan_secrets("글", "본문" + chr(0x2028))

    def test_the_summary_and_description_say_where_but_never_the_key(self):
        token = S.github()
        piece = token[:10] + chr(0x2028) + token[10:]
        result = scan.scan_secrets("앞\n" + piece, "본문")
        self.assertEqual(scan.describe(result[0]), "본문 2번째 줄에 GitHub 토큰처럼 보이는 글이 있어요")
        self.assertFalse(S.leaked(scan.summarize(result) + repr(result) + scan.describe(result[0]), token, 8))


class StaysStrictTest(unittest.TestCase):
    """쪼개지 않아도 찾던 것은 구분 글자가 이웃과 키 사이에 끼어 있어도 **같은 자리**로 찾는다 — 지운 글만 보면 키와 이웃 영숫자가 붙어 경계 규칙이 실패해 놓치기 때문이다."""

    NEEDS_LEAD = ("bearer", "access_token=", "refresh_token")                     # 값 바로 앞에 이름·낱말이 있어야 모양이 되는 표본 — 이웃 영숫자는 그 앞 낱말 앞에 붙인다

    def test_a_key_with_a_separator_and_a_letter_on_each_side_is_found_exactly_where_it_was_before(self):
        count = 0
        for name, kind, lead, token, prefix in samples():
            for code in NINE:
                if name in self.NEEDS_LEAD:
                    cases = (("뒤에 영숫자", "x " + lead + token + chr(code) + "next 뒤"), ("앞에 영숫자", "word" + chr(code) + lead + token + " x"), ("앞뒤 모두", "word" + chr(code) + lead + token + chr(code) + "next"))
                else:
                    cases = (("뒤에 영숫자", "x " + lead + token + chr(code) + "next 뒤"), ("앞에 영숫자", "word" + chr(code) + token + " x"), ("앞뒤 모두", "word" + chr(code) + token + chr(code) + "next"))
                for where, text in cases:
                    with self.subTest(sample=name, code=label(code), where=where):
                        self.assertEqual(S.triples(scan.scan_secrets(text)), [(kind, *S.locate(text, token))], "붙임 때문에 예전에 찾던 것을 놓쳤다")
                        self.assertTrue(scan.has_secret(text))
                    count += 1
        self.assertGreater(count, 250)

    def test_the_span_of_a_finding_is_the_token_itself_not_the_longer_glued_run_the_deleted_view_would_see(self):
        token = S.github()
        text = "x " + token + chr(0x2028) + "더 긴 글" + "abc"
        self.assertEqual(S.triples(scan.scan_secrets(text)), [("github_token", 1, 3, 2 + len(token))])
        text = "x " + token + chr(0x2028) + "abc"
        self.assertEqual(S.triples(scan.scan_secrets(text)), [("github_token", 1, 3, 2 + len(token))], "지운 글에서는 영숫자가 이어져 더 긴 한 건이지만 원문 눈이 이미 찾은 자리는 그대로다")

    def test_a_split_key_next_to_a_whole_key_is_two_findings_in_either_order(self):
        google, github = S.google(), S.github()
        text = google[:15] + chr(0x2028) + google[15:] + " " + github
        self.assertEqual([item.kind for item in scan.scan_secrets(text)], ["google_api_key", "github_token"])
        text = github + chr(0x2029) + " " + google[:15] + chr(0x85) + google[15:]
        self.assertEqual([item.kind for item in scan.scan_secrets(text)], ["github_token", "google_api_key"])

    def test_a_split_key_that_only_touches_a_find_is_counted_apart_and_one_that_starts_inside_a_find_is_not(self):
        """합성의 맞닿음·겹침 판정(독립 검증 S 참고-1·Q 참고 2). 지운 글 눈의 발견이 원문 눈의 발견과 **닿기만** 하면(끝 = 시작) 따로 센다 — PEM 머리 줄 바로 뒤의 쪼갠 AWS 키, 쪼갠 AWS 키 바로 뒤의 PEM 머리 줄은 2건이다.
        원문 눈의 발견 **안에서 시작하면**(Bearer 값 안에서 시작하는 쪼갠 GitHub 토큰) 같은 비밀이라 더하지 않는다 — 1건이다."""
        aws, github, header = S.aws(), S.github(), S.pem("")
        split_aws = aws[:8] + chr(0x2028) + aws[8:]
        text = "앞 줄\n" + header + split_aws + "\n뒷 줄"
        self.assertEqual(S.triples(scan.scan_secrets(text)), [("pem_private_key", 2, 1, len(header)), ("aws_access_key", 2, len(header) + 1, len(header) + len(split_aws))])
        text = "앞 줄\n" + split_aws + header + "\n뒷 줄"
        self.assertEqual(S.triples(scan.scan_secrets(text)), [("aws_access_key", 2, 1, len(split_aws)), ("pem_private_key", 2, len(split_aws) + 1, len(split_aws) + len(header))])
        lead = "Authorization: Bearer " + "abcdefghij-"
        alone = scan.scan_secrets(lead + github[:10])
        self.assertEqual([item.kind for item in alone], ["bearer_token"], "앞 조각만으로도 Bearer 값이다(원문 눈이 짚는다)")
        self.assertEqual(S.triples(scan.scan_secrets(lead + github[:10] + chr(0x2028) + github[10:])), S.triples(alone), "그 값 안에서 시작하는 쪼갠 토큰은 따로 세지 않는다 — 1건")

    def test_a_whole_key_is_never_reported_twice_when_the_text_also_has_separators_elsewhere(self):
        token = S.github()
        text = chr(0xFEFF) + "가" + chr(0x2028) + "나 " + token + " 다" + chr(0x2029) + "라"
        self.assertEqual(len(scan.scan_secrets(text)), 1)
        self.assertEqual(len(scan.scan_secrets(text * 3)), 3)

    def test_known_limit_a_key_glued_to_letters_on_both_sides_and_split_inside_is_not_found(self):
        token = S.aws()
        piece = token[:10] + chr(0x2028) + token[10:]
        text = "word" + chr(0x2028) + piece + chr(0x2028) + "next"
        self.assertEqual(scan.scan_secrets(text), (), "알려진 한계(D-760): 앞뒤가 모두 영숫자에 붙고 속도 쪼개졌으면 어느 쪽 눈에도 경계가 맞지 않는다")


class OrdinaryTextTest(unittest.TestCase):
    def test_ordinary_text_with_separators_is_not_found(self):
        texts = ["가나다" + chr(0x2028) + "라마바" + chr(0x2029) + "사아자", "Hello" + chr(0x85) + "world" + chr(0x0B) + "again" + chr(0x0C) + "end", "ghp_ is a prefix" + chr(0x2028) + "for tokens",
                 "AKIA" + chr(0x2028) + "AKIA" + chr(0x2028) * 3 + "AKIA", "AI" + "za" + chr(0x2028) + "short", "git " + "a" * 40 + chr(0x2028) + "b" * 40, "-----BEGIN" + chr(0x2029) + "PUBLIC KEY-----",
                 "Bearer" + chr(0x2028) + "tokens are used", "access_token" + chr(0x2028) + "= short", ("본문 " * 50 + chr(0x2029)) * 40, chr(0x1C) * 100 + "ya29" + chr(0x1D) * 100]
        for text in texts:
            with self.subTest(text[:20]):
                self.assertEqual(scan.scan_secrets(text), ())
                self.assertFalse(scan.has_secret(text))

    def test_random_ordinary_text_with_separators_is_never_found(self):
        rng = random.Random(20261125)
        alphabet = list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,-:=가나다라마바사아자차카타파하") + [chr(code) for code in NINE] * 6 + ["\n", "\r\n", "\t", chr(0x200B), "😀"]
        for round_number in range(300):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 400)))
            with self.subTest(round_number):
                self.assertEqual(scan.scan_secrets(text), ())

    def test_a_label_with_a_separator_is_refused_with_the_fixed_sentence_and_not_scanned_as_text(self):
        for code in NINE:
            with self.subTest(label(code)):
                with self.assertRaises(ValueError) as raised:
                    scan.scan_secrets("글", "칸" + chr(code))
                self.assertEqual(str(raised.exception), "칸 이름은 짧은 한 줄 이름이어야 해요(글 내용을 넣지 마세요)")


class EngineTest(unittest.TestCase):
    """가리기 엔진은 쪼갠 모양을 이미 알아본다 — 여기서는 그것을 못박는다(저장 검사가 엔진과 어긋나지 않게)."""

    def test_every_engine_shape_split_by_every_separator_is_hidden_by_all_the_engine_entry_points(self):
        count = 0
        for name, token, _known in engine_shapes():
            self.assertTrue(hidden(engine.mask("앞 " + token + " 뒤"), token), f"{name}: 표본이 쪼개지 않아도 안 가려진다")
            for cut_name, positions in cut_sets(token, 4).items():
                for code in NINE:
                    piece = split_at(token, positions, (code,))
                    text = "앞 글 " + piece + " 뒤 글"
                    with self.subTest(shape=name, cut=cut_name, code=label(code)):
                        self.assertTrue(hidden(engine.mask(text), token), "mask")
                        self.assertTrue(hidden(engine.safe_detail(text), token), "safe_detail")
                        self.assertTrue(hidden(display_text(text, 1000), token), "display_text")
                        self.assertTrue(engine.has_key_shape(text), "has_key_shape")
                        self.assertTrue(engine.has_key_shape_anywhere(text), "has_key_shape_anywhere")
                    count += 1
        self.assertGreater(count, 400)

    def test_the_engine_output_has_no_separator_left_so_a_deliberate_line_break_character_is_removed_from_what_is_shown(self):
        for code in NINE:
            with self.subTest(label(code)):
                self.assertEqual(engine.mask("앞 줄" + chr(code) + "뒷 줄"), "앞 줄뒷 줄", "문서가 말하는 표시 영향: 이 글자는 가린 글에서 지워진다")
                self.assertEqual(engine.safe_detail("앞" + chr(code) + "뒤"), "앞뒤")
        self.assertEqual(engine.mask("가\n나\r\n다\t라"), "가\n나\r\n다\t라", "줄바꿈(LF·CR)·탭은 그대로다")

    def test_ordinary_text_without_a_secret_is_returned_unchanged_apart_from_the_deleted_separators(self):
        for text in ("평범한 글입니다. 오늘은 날씨가 좋아요.", "Plain text 123 with punctuation: a=b; c|d", "줄1\n줄2\r\n줄3", ""):
            self.assertEqual(engine.mask(text), text)
            with_separators = text + chr(0x2028) + text + chr(0x85)
            self.assertEqual(engine.mask(with_separators), text + text)

    def test_named_secrets_split_by_a_separator_are_hidden_and_the_gate_function_sees_the_joined_value(self):
        value = "Hunter2" + S.body(10, S.ALNUM)
        for code in NINE:
            for name in ("password", "secret", "token"):
                for glue in (": ", "="):
                    text = "설정 " + name + glue + value[:6] + chr(code) + value[6:] + " 끝"
                    with self.subTest(name=name, glue=repr(glue), code=label(code)):
                        self.assertTrue(hidden(engine.mask(text), value), "가리기")
                        self.assertTrue(named_secret_spans(engine._strip_invisible(text)), "관문이 쓰는 지운 글에서 이름 붙은 값이 보인다")

    def test_a_split_pem_header_is_one_private_key_block_for_the_engine(self):
        header = S.pem("RSA ")
        body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC" + "x" * 30
        footer = "-----" + "END RSA " + "PRIVATE KEY-----"
        for code in NINE:
            with self.subTest(label(code)):
                text = "앞\n" + header[:12] + chr(code) + header[12:] + "\n" + body + "\n" + footer + "\n뒤"
                masked = engine.mask(text)
                self.assertTrue(hidden(masked, body))
                self.assertIn("개인 키 블록", masked)


class PathsAgreeTest(unittest.TestCase):
    """한 길의 판정은 쪼갠 값과 쪼개지 않은 값이 같다(길마다 아는 모양은 다르다 — 저장 검사는 여섯 유형, 엔진·관문은 모든 모양)."""

    def decisions(self, text):
        """길마다의 판정(불리언) — 같은 글을 모든 길에 건다."""
        refused = False
        try:
            projects.check_no_secret_shape(title="제목", markdown=text)
        except AppError as error:
            refused = error.code == "SECRET_SHAPE_FOUND"
        return {"저장 검사": bool(scan.scan_secrets(text)), "서비스 거절": refused, "초안 관문": bool(draft_rules.secret_spots(text)), "엔진 키 모양": engine.has_key_shape(text),
                "올리기 직전 관문": bool(publish_pages.secret_labels(text)), "엔진이 가림": engine.mask(text) != engine._strip_invisible(text)}

    def test_every_path_decides_the_same_for_the_split_and_the_whole_key(self):
        count = 0
        for name, token, known in engine_shapes():
            whole = self.decisions("앞 글 " + token + " 뒤 글")
            self.assertEqual(whole["엔진 키 모양"], True, name)
            self.assertEqual((whole["저장 검사"], whole["서비스 거절"]), (known, known), f"{name}: 저장 검사가 아는 유형인지 표본 표와 다르다")
            for code in NINE:
                for cut_name, positions in cut_sets(token, 4).items():
                    piece = split_at(token, positions, (code,))
                    with self.subTest(shape=name, code=label(code), cut=cut_name):
                        self.assertEqual(self.decisions("앞 글 " + piece + " 뒤 글"), whole)
                    count += 1
        self.assertGreater(count, 400)

    def test_the_service_check_refuses_a_split_key_with_the_same_code_and_a_message_without_the_key_in_every_field(self):
        for name, kind, lead, token, prefix in samples():
            piece = split_at(token, (len(token) // 2,), (0x2028,))
            for field, kwargs in (("본문", {"markdown": "앞 " + lead + piece}), ("제목", {"title": lead + piece}), ("출처", {"references": ["https://example.invalid/?x=" + lead + piece]})):
                with self.subTest(sample=name, field=field):
                    with self.assertRaises(AppError) as raised:
                        projects.check_no_secret_shape(**kwargs)
                    error = raised.exception
                    self.assertEqual(error.code, "SECRET_SHAPE_FOUND")
                    self.assertFalse(S.leaked(repr(error.__dict__) + str(error.notes), token, 8), "오류에 키 글자가 있다")

    def test_the_approval_gate_blocks_the_split_key_like_the_whole_key(self):
        """승인 관문(`service.gate.run_gates` — 발행 직전 같은 검사)은 쪼갠 키도 쪼개지 않은 키처럼 막는다. 줄 구분 글자 아홉은 올리기 길의 제어 문자 검사가 먼저 거절한다(코드는 달라도 막힌다)."""
        project = ContentProject.new("제목", ss.ko_text(), now="2026-11-02T00:00:00Z")
        base = render_pages_post(project, category=ss.KO_PARAMS.category, lang="ko", image_url=ss.KO_PARAMS.image_url, tags=ss.KO_PARAMS.tags, now=ss.NOW).text
        self.assertTrue(gate.run_gates(base).ok, "비밀이 없는 글은 통과한다(시험이 헛돌지 않는다)")
        for name, token, _known in engine_shapes():
            whole = gate.run_gates(base.rstrip("\n") + "\n\n값은 " + token + " 입니다.\n")
            self.assertFalse(whole.ok, name)
            self.assertTrue(any("SECRET_IN_TEXT_BLOCKED" in reason for reason in whole.reasons), name)
            for code in NINE:
                piece = split_at(token, (len(token) // 2,), (code,))
                with self.subTest(shape=name, code=label(code)):
                    report = gate.run_gates(base.rstrip("\n") + "\n\n값은 " + piece + " 입니다.\n")
                    self.assertFalse(report.ok)
                    self.assertTrue(any(("SECRET_IN_TEXT_BLOCKED" in reason or "CONTENT_INVALID" in reason) for reason in report.reasons), report.reasons)
                    self.assertFalse(S.leaked(repr(report.reasons), token, 8), "관문 사유에 키 글자가 있다")

    def test_the_draft_gate_functions_see_through_the_separators_too(self):
        token = S.google()
        for code in NINE:
            piece = token[:12] + chr(code) + token[12:]
            with self.subTest(label(code)):
                self.assertTrue(draft_rules.secret_spots("앞 " + piece + " 뒤"))
                self.assertTrue(draft_rules.has_secret("앞 " + piece + " 뒤"))

    def test_the_release_check_and_backup_scanners_use_the_same_function(self):
        token = S.github()
        piece = token[:10] + chr(0x2028) + token[10:]
        self.assertTrue(scan.has_secret("백업 글 " + piece))
        self.assertEqual([item.kind for item in scan.scan_secrets("줄\n" + piece, "후보")], ["github_token"])


class AdapterTest(unittest.TestCase):
    """화면 어댑터(진짜 서비스·임시 데이터 폴더)의 가져오기·검토·승인 — `p02_e2e` 와 같은 길이다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ss.make_ctx(self.tmp.name, repo="")
        self.provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: self.ctx)

    def do_import(self, body):
        return self.provider.import_post(posts.ImportRequest("markdown", "분리 글", body), SAFE, NEVER)

    def failure_of(self, body):
        with self.assertRaises(posts.PostFailure) as raised:
            self.do_import(body)
        return raised.exception

    def test_a_split_key_of_the_six_kinds_is_refused_exactly_like_the_whole_key_and_nothing_is_saved(self):
        for name, kind, lead, token, prefix in samples():
            whole = self.failure_of(ss.ko_text(extra="값은 " + lead + token + " 입니다"))
            self.assertEqual((whole.kind, whole.code), ("secret", "SECRET_SHAPE_FOUND"), name)
            for code in NINE:
                piece = split_at(token, (len(token) // 2,), (code,))
                with self.subTest(sample=name, code=label(code)):
                    failure = self.failure_of(ss.ko_text(extra="값은 " + lead + piece + " 입니다"))
                    self.assertEqual((failure.kind, failure.code, failure.user_message), (whole.kind, whole.code, whole.user_message))
                    self.assertFalse(S.leaked(failure.user_message + repr(failure.__dict__), token, 8))
        self.assertEqual(self.provider.load_posts(SAFE, NEVER).rows, (), "거절한 글은 저장되지 않는다")

    def test_an_already_stored_split_key_is_found_by_the_review_spots_and_blocks_the_approval_check(self):
        project_id = self.do_import(ss.ko_text()).detail.project_id
        token = S.aws()
        piece = token[:9] + chr(0x2028) + token[9:]
        ss.inject_text(self.ctx, project_id, text=ss.ko_text() + "\n\n맨 끝에 " + piece)
        view = projects.show_project(self.ctx, project_id)
        spots = post_rules.secret_spots(view.title, view.source_content, view.references, view.assets)
        self.assertEqual([item[2] for item in spots], ["AWS 액세스 키"])
        self.assertEqual(post_rules.text_blocks(view.title, view.source_content, view.references, view.assets), ("secret",))
        self.assertFalse(S.leaked(repr(spots), token, 8))

    def test_known_limit_the_preview_converter_turns_three_separators_into_a_space_for_shapes_outside_the_six_kinds(self):
        """**알려진 한계(D-760 ⑥) — 이 시험은 한계를 못박은 것이다.** 저장 검사가 모르는 모양(Slack·OpenAI·Stripe …)은 쪼개지 않아도 가져오기를 지나고 미리보기가 가린다.
        U+0085·U+2028·U+2029 로 쪼갠 것은 미리보기 변환(`render/markdown.py` 의 글자 뽑기)이 그 글자를 공백으로 바꿔 엔진이 보기 전에 쪼개져 두 쪽이 그대로 보인다(나머지 여섯 글자는 변환기가 지워 새지 않는다).
        고치는 곳은 `ui/core/post_rules.py`·`render/markdown.py`(이 갈래 밖)다 — 고쳐져서 이 시험이 빨개지면 '누출 0' 단언으로 바꾼다."""
        for name, token, known in engine_shapes():
            if known:
                continue
            whole = self.do_import(ss.ko_text(extra="값은 " + token + " 입니다")).detail.preview
            self.assertTrue(hidden("\n".join(block.text for block in whole.blocks), token), f"{name}: 쪼개지 않은 값은 미리보기가 가린다")
            for code in NINE:
                piece = split_at(token, (len(token) // 2,), (code,))
                with self.subTest(shape=name, code=label(code)):
                    shown = "\n".join(block.text for block in self.do_import(ss.ko_text(extra="값은 " + piece + " 입니다")).detail.preview.blocks)
                    if code in CONVERTER_KEEPS:
                        self.assertFalse(hidden(shown, token), "한계가 고쳐졌다 — 이 단언을 누출 0 으로 바꾼다")
                    else:
                        self.assertTrue(hidden(shown, token), "변환기가 지우는 제어 글자로 쪼갠 값은 미리보기가 가린다")


class PerformanceTest(unittest.TestCase):
    """병적 입력(구분 글자만·한 글자 사이마다·키 모양 반복·짧은 키를 한 번씩 쪼갠 것 반복)이 선형 시간이다 — 새 지움·위치표·합성이 제곱으로 느려지지 않는다."""

    SIZES = (16_000, 64_000)                                                   # 네 배 단계 — 선형이면 약 4배, 제곱이면 약 16배(독립 검증 Q 권고-2)
    GROWTH_LIMIT = 8                                                           # 선형(4)과 제곱(16) 사이

    @staticmethod
    def shapes(size):
        sep_a, sep_b = chr(0x2028), chr(0x85)
        token = S.github()
        aws = S.aws()
        count = size // 4
        return {
            "구분 글자만": sep_a * size,
            "아홉 글자 번갈아": "".join(chr(NINE[index % 9]) for index in range(size)),
            "한 글자 사이마다": ("a" + sep_a) * (size // 2),
            "접두어와 구분 글자": ("ghp_" + sep_a) * count,
            "접두어 다음 한 글자씩": "ghp_" + ("a" + sep_b) * (size // 2),
            "Bearer 와 한 글자씩": "Bearer " + ("a" + sep_a) * (size // 2),
            "키 모양 반복(쪼갠 것)": (token[:10] + sep_a + token[10:] + " ") * (size // 40),
            "키 모양 반복(쪼개지 않음)": (token + sep_a + "x ") * (size // 40),
            "AWS 접두어 반복": ("AKIA" + sep_b + "A") * (size // 5),
            "PEM 머리 반복": ("-----BEGIN" + sep_a + " ") * (size // 11),
            "OAuth 이름 반복": ("access_token=" + sep_a) * (size // 14),
            "한글 사이마다": ("가" + sep_a) * (size // 2),
            "짧은 AWS 키를 한 번씩 쪼갠 것 반복": (aws[:8] + sep_a + aws[8:] + " ") * (size // 22),
            "통 키와 쪼갠 키 번갈아": (aws + " " + aws[:8] + sep_b + aws[8:] + " ") * (size // 43),
        }

    @staticmethod
    def best(call, text):
        times = []
        for _ in range(3):
            began = time.perf_counter()
            call(text)
            times.append(time.perf_counter() - began)
        return min(times)

    def test_every_pathological_shape_is_fast_and_grows_linearly(self):
        calls = {"scan_secrets": scan.scan_secrets, "has_secret": scan.has_secret, "mask": engine.mask, "has_key_shape": engine.has_key_shape}
        small, big = (self.shapes(size) for size in self.SIZES)
        for name in big:
            for call_name, call in calls.items():
                low, high = self.best(call, small[name]), self.best(call, big[name])
                with self.subTest(shape=name, call=call_name):
                    self.assertLess(high, LIMIT_SECONDS, "64,000자가 0.5초 안에 끝나지 않는다")
                    self.assertLess(high, max(low, 0.002) * self.GROWTH_LIMIT, "네 배 긴 입력이 여덟 배 넘게 걸린다 — 제곱 시간 의심")

    def test_a_hundred_thousand_separators_inside_one_key_still_end_fast_and_find_it(self):
        token = S.github()
        text = "앞 " + token[:20] + chr(0x2028) * 100_000 + token[20:] + " 뒤"
        began = time.perf_counter()
        result = scan.scan_secrets(text)
        self.assertLess(time.perf_counter() - began, LIMIT_SECONDS)
        self.assertEqual([item.kind for item in result], ["github_token"])
        self.assertEqual((result[0].line, result[0].col_start, result[0].col_end), (1, 3, 2 + len(token) + 100_000))


class SourceTest(unittest.TestCase):
    def test_the_new_helper_names_and_the_engine_names_other_modules_import_still_exist(self):
        for name in ("_SPLIT_CODES", "_without_splitters", "_original_index", "_matches", "_resolve", "_find"):
            self.assertTrue(hasattr(scan, name), name)
        for name in ("_strip_invisible", "_INVISIBLE", "_HIDDEN", "mask", "has_key_shape", "has_key_shape_anywhere", "safe_detail"):
            self.assertTrue(hasattr(engine, name), name)
        self.assertEqual(engine._HIDDEN, frozenset({"Cf", "Cc", "Cs", "Co", "Zl", "Zp"}))

    def test_the_scan_source_has_no_raw_separator_character_only_the_integer_list(self):
        source = SOURCES["scan"].read_text(encoding="utf-8")
        for code in NINE:
            self.assertNotIn(chr(code), source, f"{label(code)} 글자가 소스에 그대로 적혀 있다 — 정수 목록으로 둔다")


class DocsTest(unittest.TestCase):
    """문서 세 곳(결정 행·보안 문서 절·변경 이력 줄)이 있고 말하는 것이 코드와 같다 — 이 묶음의 글은 번호와 낱말로 찾는다(다른 묶음의 행·줄이 늘어도 깨지지 않게 최댓값은 못박지 않는다)."""
    SENTENCE = "줄 구분 글자도 눈에 안 보이는 글자처럼 지우고 찾는다(U+2028·U+2029·U+0085 를 포함한 아홉 글자)"
    HEADING = "### 줄 구분 글자로 쪼갠 키·토큰(SECSEP — D-760)"

    @staticmethod
    def read(rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def plain(self, text, what):
        self.assertNotIn(chr(126), text, what + ": 물결표")
        self.assertNotRegex(text, r"(?i)(https?|ftp)://|www[.]", what + ": 웹 주소")
        self.assertNotIn("@@", text, what + ": 채우지 않은 자리")
        self.assertNotIn("{" * 2, text, what + ": 이중 중괄호")
        self.assertNotIn("}" * 2, text, what + ": 이중 중괄호")

    def test_the_decision_row_is_one_line_inside_the_big_table_with_the_words_that_matter(self):
        lines = self.read("docs/DECISIONS.md").splitlines()
        mine = [index for index, line in enumerate(lines) if line.startswith("| D-760 |")]
        self.assertEqual(len(mine), 1, "D-760 행은 정확히 한 줄이어야 한다")
        row = lines[mine[0]]
        self.assertTrue(lines[mine[0] - 1].startswith("| D-"), "큰 결정 표 안(앞 줄이 결정 행)이어야 한다 — 문서 끝에 새 표를 붙이지 않는다")
        self.assertTrue(row.rstrip().endswith("|") and row.split("|")[2].strip() == "2026-11-25")
        for word in ("SECSEP", "줄 구분 글자", "U+0085", "U+2028", "U+2029", "scan.py", "mask.py", "미리보기", "붙임", "차분", "변이", "T2", "지우고도 찾는다", "한계", "부분집합", "거짓 양성", "앞붙임", "SECSEP2", "50개까지"):
            self.assertIn(word, row, word)
        self.assertNotIn(" | ", row[len("| D-760 | 2026-11-25 | "):-1], "결정 칸 속의 세로줄은 색인이 칸 나눔으로 읽는다")
        self.plain(row, "D-760 행")

    def test_the_security_document_says_it_inside_the_scan_section_with_its_limits(self):
        text = self.read("docs/SECURITY.md")
        self.assertEqual(text.count(self.SENTENCE), 1)
        start = text.index("## 본문 속 Secret 형태 검사")
        end = text.index("\n## ", start + 5)
        self.assertTrue(start < text.index(self.SENTENCE) < end, "저장 검사 절 안에 있어야 한다")
        self.assertEqual(text.count(self.HEADING), 1)
        part = text[text.index(self.HEADING):end]
        for word in ("U+000B", "U+000C", "U+001C–U+001F", "U+0085", "U+2028", "U+2029", "두 눈", "한계", "미리보기", "붙임", "차분", "mask.py", "scan.py", "`_strip_invisible`", "앞붙임", "SECSEP2", "50개까지", "VT·U+001C"):
            self.assertIn(word, part, word)
        self.plain(part, "보안 문서의 새 절")

    def test_the_changelog_has_one_line_of_this_bundle(self):
        lines = [line for line in self.read("CHANGELOG.md").splitlines() if line.startswith("- 줄 구분 글자 아홉으로 쪼갠 키·토큰을 저장 검사가 알아본다(SECSEP")]
        self.assertEqual(len(lines), 1, "이 묶음의 고유 문장으로 찾는다 — 다른 갈래의 줄이 늘어도 깨지지 않는다")
        for word in ("줄 구분 글자 아홉", "security/scan.py", "security/mask.py", "tests/test_security_separator_split.py", "D-760", "T2", "한계"):
            self.assertIn(word, lines[0], word)
        self.plain(lines[0], "변경 이력 줄")

    def test_the_sources_point_at_the_decision_and_the_document_lists_the_nine_the_code_has(self):
        for name, path in SOURCES.items():
            self.assertIn("D-760", path.read_text(encoding="utf-8"), name)
        part = self.read("docs/SECURITY.md")
        part = part[part.index(self.HEADING):]
        for code in (0x0B, 0x0C, 0x85, 0x2028, 0x2029):
            self.assertIn(label(code), part, label(code))
        self.assertEqual(sorted(scan._SPLIT_CODES), sorted(NINE))


if __name__ == "__main__":
    unittest.main()
