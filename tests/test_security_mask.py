"""로그 가리기 시험 — 비밀 모양(chanceblog 의 패턴 정본 `secret_patterns`)이 로그·오류 줄에 나가지 않는다.

지키는 것:
  1) 패턴 정본의 모든 종류(Google·GitHub·Slack·AWS·텔레그램·sk-·OAuth 비밀·개인 키·키/토큰 할당 …)가 가려지고 앞뒤 글은 그대로다 — 정본에 패턴이 늘면(vendor 갱신) 이 시험이 새 표본을 요구한다.
  2) 주소 속 `사용자:토큰@` 도 가린다. 평범한 글·긴 해시·짧은 접두사는 건드리지 않는다. 이미 가린 글을 다시 가려도 같다.
  3) 어떤 입력(None·숫자·이상한 객체·아주 긴 글)에도 예외 없이 빠르게 돈다. safe_detail 은 한 줄·길이 제한.
  4) AppError.log_line 과 git 실패의 세부(detail)에 비밀이 실리지 않는다.
키 표본은 시험 안에서 조각을 이어 만든 가짜 값이라 저장소에는 키 문자열이 없다. 네트워크 없이 돈다.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
import chanceblog_desktop.security.mask as mask_module  # noqa: E402
from chanceblog_desktop.security import mask_text as mask_from_package  # noqa: E402
from chanceblog_desktop.security.mask import MAX_LOG_CHARS, MAX_MASK_INPUT, mask, safe_detail  # noqa: E402
from pipeline.secret_patterns import SECRET_PATTERNS  # noqa: E402  (security 가 vendor/ 경로를 올려 둔다)

SAMPLES = {
    "Google API 키": "AI" + "za" + "A" * 35,
    "Google API 키(새 형식)": "AQ." + "b" * 45,
    "Google OAuth 클라이언트 시크릿": "GOC" + "SPX-" + "c" * 24,
    "Google refresh token": "1//0" + "d" * 45,
    "Google access token": "ya29." + "e" * 35,
    "GitHub 토큰": "gh" + "p_" + "f" * 40,
    "GitHub PAT": "github_" + "pat_" + "g" * 45,
    "개인 키 블록": "-----BEGIN " + "PRIVATE KEY-----\nQUJDREVGR0g=\n-----END " + "PRIVATE KEY-----",
    "Slack 토큰": "xo" + "xb-" + "h" * 14,
    "AWS 액세스 키": "AK" + "IA" + "0" * 16,
    "Telegram 봇 토큰": "123456789:" + "AbCdEfGhIj" * 4,
    "sk- 형식 API 키": "sk" + "-" + "i" * 40,
    "client_secret JSON 값": '"client_secret": "abcdefgh12345"',
    "키/토큰 할당": 'api_key = "' + "j" * 30 + '"',
}


class PatternCoverageTest(unittest.TestCase):
    def test_every_pattern_the_source_of_truth_has_is_covered_by_a_sample(self):
        labels = [label for label, _ in SECRET_PATTERNS]
        self.assertEqual(sorted(labels), sorted(SAMPLES), "vendor 를 갱신해 패턴이 바뀌었다면 이 시험의 표본도 맞춘다")

    def test_each_kind_is_masked_with_its_name_and_the_surrounding_text_is_kept(self):
        for label, secret in SAMPLES.items():
            with self.subTest(label=label):
                masked = mask(f"앞글 {secret} 뒷글")
                self.assertTrue(masked.startswith("앞글 ") and masked.endswith(" 뒷글"), masked)
                self.assertIn(f"[가림: {label}]", masked)
                self.assertNotIn(secret, masked)

    def test_each_secret_is_found_by_the_sources_own_scan_before_and_not_after(self):
        from pipeline.secret_patterns import find_secrets
        for label, secret in SAMPLES.items():
            with self.subTest(label=label):
                self.assertTrue(find_secrets(f"x {secret} y"))
                self.assertEqual(find_secrets(mask(f"x {secret} y")), [])

    def test_masking_twice_changes_nothing(self):
        text = " / ".join(SAMPLES.values()) + " https://user:pw@example.com/a"
        once = mask(text)
        self.assertEqual(mask(once), once)

    def test_several_secrets_in_one_text_are_all_masked(self):
        text = " ".join(SAMPLES.values())
        masked = mask(text)
        for secret in SAMPLES.values():
            self.assertNotIn(secret, masked)
        self.assertEqual(masked.count("[가림: "), len(SAMPLES))


class NotASecretTest(unittest.TestCase):
    def test_ordinary_text_is_left_alone(self):
        for text in ("평범한 문장입니다.", "a" * 200, "https://example.com/a/b?c=d", "git 해시 " + "0123456789abcdef" * 2 + "01234567", "AIza", "ghp_", "token", "api_key = 짧음",
                     "문서에서 `GEMINI_API_KEY` 라는 이름만 말한다", "전화 010-1234-5678", "AQ.짧음"):
            with self.subTest(text=text[:30]):
                self.assertEqual(mask(text), text)

    def test_credentials_inside_addresses_are_hidden_but_the_rest_of_the_address_stays(self):
        self.assertEqual(mask("https://user:pw@github.com/a/b.git"), "https://***@github.com/a/b.git")
        self.assertEqual(mask("ssh://git@github.com/a/b.git"), "ssh://***@github.com/a/b.git")
        self.assertEqual(mask("git@github.com:a/b.git"), "git@github.com:a/b.git")
        token = "gh" + "p_" + "k" * 40
        self.assertNotIn(token, mask(f"https://x-access-token:{token}@github.com/a/b.git"))


class ExtraShapesTest(unittest.TestCase):
    """패턴 정본에 없지만 이 앱의 글(git 출력·주소·HTTP 머리글)에서 비밀이 실리는 모양들."""

    def test_a_password_with_an_at_sign_is_hidden_completely(self):
        self.assertEqual(mask("https://user:p@ss:w0rd@github.com/a/b.git"), "https://***@github.com/a/b.git")
        self.assertNotIn("w0rd", mask("fatal: unable to access 'https://user:p@ss:w0rd@github.com/a/b.git/': The requested URL returned error: 403"))

    def test_secret_query_arguments_of_addresses_are_hidden_and_the_other_arguments_stay(self):
        for text, secret, kept in (
            ("https://api.example.com/v1/x?access_token=abc123DEF456&page=2", "abc123DEF456", "page=2"),
            ("https://x.example/cb?state=1&client_secret=s3cr3tvalue", "s3cr3tvalue", "state=1"),
            ("GET /a?api_key=ABCD1234&b=2 HTTP/1.1", "ABCD1234", "b=2"),
            ("https://x.example/a?b=2;token=zzz9999", "zzz9999", "b=2"),
            ("https://x.example/a?Password=hunter2hunter2&b=2", "hunter2hunter2", "b=2"),
        ):
            with self.subTest(text=text):
                masked = mask(text)
                self.assertNotIn(secret, masked)
                self.assertIn("[가림: 주소 인자]", masked)
                self.assertIn(kept, masked)

    def test_ordinary_query_arguments_are_left_alone(self):
        for text in ("https://example.com/a?page=2&sort=asc", "https://example.com/a?keyword=블로그&monkey=1", "https://x.example/?tokenizer=bpe"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)

    def test_bearer_tokens_are_hidden_but_ordinary_sentences_are_not(self):
        self.assertEqual(mask("Authorization: Bearer abcdefghijklmnop0123456789XYZ"), "Authorization: Bearer [가림: 토큰]")
        self.assertEqual(mask("bearer short"), "bearer short")
        self.assertEqual(mask("the bearer of this message"), "the bearer of this message")

    def test_masking_twice_changes_nothing_for_these_shapes_too(self):
        text = "https://u:p@ss@x.example/a?access_token=abc123DEF456&page=2 Authorization: Bearer abcdefghijklmnop0123456789XYZ ?key=k1;secret=s2"
        once = mask(text)
        self.assertNotEqual(once, text)
        self.assertEqual(mask(once), once)
        self.assertEqual(safe_detail(once), safe_detail(safe_detail(once)))


class MoreShapesTest(unittest.TestCase):
    """재검토에서 빠져 있다고 나온 모양들."""

    def test_more_secret_shapes_are_hidden(self):
        jwt = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abcdefghijklmnop"
        cases = (
            (f"token {jwt} 끝", jwt),
            ("Authorization: Basic dXNlcjpwYXNzd29yZDEyMzQ1Ng==", "dXNlcjpwYXNzd29yZDEyMzQ1Ng"),
            ("hook https://hooks.slack.com/services/T00000000/B00000000/" + "X" * 24, "X" * 24),
            ("npm 토큰 npm_" + "a1B2" * 9, "a1B2" * 9),
            ("aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG" + "/bPxRfiCYEXAMPLEKEY", "bPxRfiCYEXAMPLEKEY"),
            ("password: hunter2hunter2", "hunter2hunter2"),
            ("passwd=correcthorse", "correcthorse"),
            ("API_KEY: abcd1234efgh", "abcd1234efgh"),
            ("SECRET=top5ecretvalue", "top5ecretvalue"),
        )
        for text, secret in cases:
            with self.subTest(text=text[:40]):
                masked = mask(text)
                self.assertNotIn(secret, masked)
                self.assertIn("[가림", masked)
                self.assertEqual(mask(masked), masked, "다시 가려도 같다")

    def test_a_whole_private_key_block_is_hidden_not_just_its_header(self):
        body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nabcdEFGH1234\n"
        block = "-----BEGIN " + "PRIVATE KEY-----\n" + body + "-----END " + "PRIVATE KEY-----"
        self.assertEqual(mask(f"앞 {block} 뒤"), "앞 [가림: 개인 키 블록] 뒤")
        cut = mask("-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA잘림")      # 끝줄이 없으면 글 끝까지(본문이 남지 않게)
        self.assertNotIn("MIIEow", cut)

    def test_every_listed_query_name_is_hidden_and_the_other_arguments_stay(self):
        names = ("access_token", "refresh_token", "id_token", "token", "api_key", "api-key", "apikey", "x-api-key", "key", "client_secret", "secret", "password", "passwd",
                 "pwd", "sig", "signature", "auth", "code", "private_token", "X-Amz-Signature", "x-amz-credential", "session", "sessionid", "session_id", "jwt")
        for name in names:
            with self.subTest(name=name):
                masked = mask(f"https://x.example/a?b=1&{name}=VALUE123456&c=2")
                self.assertNotIn("VALUE123456", masked)
                self.assertIn("[가림: 주소 인자]", masked, "주소 인자 규칙이 가렸다(글 속 대입 규칙이 대신 가린 것이 아니다)")
                self.assertIn("b=1", masked)
                self.assertIn("&c=2", masked)

    def test_bearer_needs_a_word_boundary_and_an_unassigned_word_is_left_alone(self):
        self.assertEqual(mask("xbearer abcdefghijklmnop0123456789"), "xbearer abcdefghijklmnop0123456789")
        for text in ("the password is a secret to everyone", "토큰 발급 방법", "pwd 명령으로 위치를 본다", "key 입력"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)

    def test_a_token_split_by_invisible_characters_is_still_hidden(self):
        token = "gh" + "p_" + "m" * 40
        for sneaky in ("\u200b", "\u2060", "\ufeff", "\u00ad", "\U000e0041", "\u202e", "\ufe0f"):
            with self.subTest(char=hex(ord(sneaky))):
                split = token[:10] + sneaky + token[10:]
                self.assertNotIn("m" * 10, mask(f"x {split} y"))

    def test_masking_is_still_fast_on_nasty_inputs(self):
        started = time.time()
        for text in ("-----BEGIN " + "PRIVATE KEY-----" * 20000, "password:" + " " * 200000 + "x", "?" + "a=" * 100000, "bearer " + "a" * 500000, "eyJ" + "a." * 100000):
            mask(text)
        self.assertLess(time.time() - started, 10)


class LimitsTest(unittest.TestCase):
    """화면 문구·로그 한 줄의 길이 한도(변이 점검이 한도 숫자를 바꿔도 통과한다고 알려 준 곳)."""

    def test_the_slot_text_is_cut_to_its_limit(self):
        from chanceblog_desktop.errors import clean_slot
        self.assertEqual(len(clean_slot("가" * 500)), 160)
        self.assertEqual(clean_slot("가" * 160), "가" * 160)

    def test_the_fields_of_the_log_line_are_cut_to_their_limits(self):
        line = AppError("FILE_IN_USE", {"이" * 100: "값" * 500}, detail="세" * 5000).log_line()
        name, value = line.split(" | ")[1][len("값="):].split("=", 1)
        self.assertEqual((len(name), len(value)), (40, 200))
        self.assertEqual(len(line.split(" | 세부=")[1]), 2000)


class FourthReviewShapesTest(unittest.TestCase):
    """4차 검토가 짚은, 숨은 글자·짧은 값·긴 입력에서 비밀이 샜거나 멀쩡한 글이 가려졌던 모양들(변이 점검이 시험의 빈틈으로 알려 준 것 포함)."""

    def test_invisible_characters_that_have_no_format_category_split_nothing_either(self):
        token = "gh" + "p_" + "m" * 40
        for code in (0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180F, 0x2800, 0x3164, 0xFFA0, 0xFFF0, 0xFFF8, 0xE0080, 0xE00FF, 0xE0100, 0xE01F0, 0xE0FFF):
            with self.subTest(char=hex(code)):
                self.assertNotIn("m" * 10, mask(f"x {token[:10]}{chr(code)}{token[10:]} y"))

    def test_header_and_short_value_forms_are_hidden_and_their_neighbours_stay(self):
        for text, secret, kept in (
            ("X-Api-Key: abcd1234efgh5678", "abcd1234efgh5678", "X-Api-Key:"),
            ("password=hunter2", "hunter2", "password="),
            ("token=abc123", "abc123", "token="),
            ("password=hunter2hunter2,next=1", "hunter2hunter2", ",next=1"),
            ("a=1&password=hunter2&b=2", "hunter2", "&b=2"),
        ):
            with self.subTest(text=text):
                masked = mask(text)
                self.assertNotIn(secret, masked)
                self.assertIn(kept, masked)

    def test_an_address_in_the_middle_of_a_sentence_does_not_swallow_the_text_up_to_a_later_at_sign(self):
        text = "주소 https://example.com 로 연락은 me@example.com"
        self.assertEqual(mask(text), text)

    def test_a_jwt_with_a_very_long_part_is_hidden_completely(self):
        jwt = "eyJ" + "a" * 5000 + "." + "b" * 40 + "." + "c" * 5000
        self.assertEqual(mask("token " + jwt), "token [가림: JWT]")

    def test_the_cut_for_a_very_long_input_does_not_leave_the_front_half_of_a_secret(self):
        secret = "gh" + "p_" + "m" * 40
        filler = "가나다 " * ((mask_module.MAX_MASK_INPUT - 20) // 4)                   # 평범한 글이 상한 20자 앞까지
        text = filler + secret + " 뒤에 더 이어지는 글" * 5
        start = text.index(secret)
        self.assertTrue(start < mask_module.MAX_MASK_INPUT < start + len(secret), "비밀이 상한에 걸쳐 있어야 이 시험이 뜻이 있다")
        masked = mask(text)
        self.assertNotIn("ghp_", masked, "반쪽으로 잘린 비밀의 앞부분이 남았다")
        self.assertTrue(masked.endswith("…(이하 생략)"))
        solid = "가" * (mask_module.MAX_MASK_INPUT + 50)                                  # 공백이 하나도 없으면 상한 그대로 자른다
        self.assertEqual(mask(solid), "가" * mask_module.MAX_MASK_INPUT + "…(이하 생략)")

    def test_the_value_cleaner_of_error_messages_drops_the_same_default_ignorable_gaps(self):
        from chanceblog_desktop.errors import clean_slot
        for code in (0x180F, 0xFFF0, 0xFFF8, 0xE0080, 0xE01F0, 0xE0FFF):
            with self.subTest(char=hex(code)):
                self.assertEqual(clean_slot(f"가{chr(code)}나"), "가 나")


class ThirdReviewShapesTest(unittest.TestCase):
    """3차 검토가 짚은, 가려야 하는데 못 가렸거나 불필요하게 가렸던 모양들."""

    def test_environment_variable_style_names_json_and_short_quoted_values_are_hidden(self):
        for text, secret in (
            ("DB_PASSWORD=hunter2hunter2", "hunter2hunter2"), ("export MY_SERVICE_TOKEN=abcd1234efgh", "abcd1234efgh"), ("GITHUB_API_KEY: zzzz1111yyyy", "zzzz1111yyyy"),
            ('{"password": "hunter2"}', "hunter2"), ("{'secret':'sh0rt'}", "sh0rt"), ('password = "x"', '"x"'), ("secret='ab'", "'ab'"),
            ("Cookie: csrftoken=abcdef123456; theme=dark", "abcdef123456"), ("Cookie: sessionid=qwertyuiop12; a=1", "qwertyuiop12"), ("session_id=asdfghjkl123", "asdfghjkl123"),
            ("client_credentials = AbCdEf123456", "AbCdEf123456"),
        ):
            with self.subTest(text=text):
                masked = mask(text)
                self.assertNotIn(secret, masked)
                self.assertIn("[가림: 값]", masked)
                self.assertEqual(mask(masked), masked, "다시 가려도 같다")
        self.assertIn("theme=dark", mask("Cookie: csrftoken=abcdef123456; theme=dark"), "다른 값은 그대로")

    def test_a_json_escaped_address_hides_its_login_too(self):
        self.assertEqual(mask(r"https:\/\/user:pw@github.com\/a\/b.git"), r"https:\/\/***@github.com\/a\/b.git")
        self.assertEqual(mask(r"{\"url\": \"https:\/\/u:p@ss@x.example\/a\"}"), r"{\"url\": \"https:\/\/***@x.example\/a\"}")

    def test_a_pgp_private_key_block_is_hidden_whole(self):
        block = "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----\nlQOYBF\nabcdEFGH1234\n-----END PGP " + "PRIVATE KEY BLOCK-----"
        self.assertEqual(mask(f"앞 {block} 뒤"), "앞 [가림: 개인 키 블록] 뒤")
        self.assertNotIn("lQOYBF", mask("-----BEGIN PGP " + "PRIVATE KEY BLOCK-----\nlQOYBF잘림"))

    def test_ordinary_words_that_looked_like_secrets_are_left_alone(self):
        for text in ("PWD=C:/Users/me/work", "basic internationalization", "Basic internationalization of the app", "https://example.com/a?code=200&x=1", "?code=404",
                     "pwd=/home/me", "token 은 짧다", "Basic abcdefghijklmnopqrstuvwxyz"):
            with self.subTest(text=text):
                self.assertEqual(mask(text), text)
        self.assertNotIn("4%2F0AX4XfWh", mask("https://x.example/cb?code=4%2F0AX4XfWhabcdef&state=1"), "긴 인증 코드는 가린다")
        self.assertIn("[가림: 주소 인자]", mask("https://x.example/cb?code=4%2F0AX4XfWhabcdef&state=1"))

    def test_basic_credentials_with_uppercase_digits_or_padding_are_hidden(self):
        for token in ("dXNlcjpwYXNzd29yZA==", "QWxhZGRpbjpvcGVuIHNlc2FtZQ", "dXNlcjpwYXNzd29yZDEyMzQ1Ng"):
            with self.subTest(token=token):
                self.assertNotIn(token, mask(f"Authorization: Basic {token}"))

    def test_characters_outside_the_basic_plane_that_hide_or_reorder_text_are_removed_first(self):
        token = "gh" + "p_" + "m" * 40
        for sneaky in ("\U0001bca0", "\U0001d173", "\U000e0041", "\u2028", "\u2029", "\u200e"):
            with self.subTest(char=hex(ord(sneaky))):
                self.assertNotIn("m" * 10, mask(f"x {token[:10]}{sneaky}{token[10:]} y"))
        self.assertEqual(mask("줄\n탭\t그대로\r"), "줄\n탭\t그대로\r", "줄바꿈·탭은 지우지 않는다")
        for sneaky in (chr(1), chr(27), chr(0xD800), chr(0xE000)):                       # 제어 문자·대용(surrogate)·사용자 지정 영역 글자도 비밀을 쪼개지 못한다
            with self.subTest(char=hex(ord(sneaky))):
                self.assertNotIn("m" * 10, mask(f"x {token[:10]}{sneaky}{token[10:]} y"))

    def test_unassigned_code_points_that_are_drawn_as_nothing_cannot_split_a_secret_either(self):
        token = "gh" + "p_" + "m" * 40
        for sneaky in (chr(0x2065), chr(0xE0000), chr(0xE0002)):                         # 글자가 배정되지 않았지만 화면에 아무것도 그리지 않는 자리(범주 Cn)
            with self.subTest(char=hex(ord(sneaky))):
                self.assertNotIn("m" * 10, mask(f"x {token[:10]}{sneaky}{token[10:]} y"))

    def test_the_value_cleaner_of_error_messages_also_drops_format_characters_outside_the_basic_plane(self):
        from chanceblog_desktop.errors import clean_slot
        for sneaky in (chr(0x1BCA0), chr(0x1D173), chr(0xE0041), chr(0x2028), chr(0x200E), chr(0x2065), chr(0xE0000)):
            with self.subTest(char=hex(ord(sneaky))):
                self.assertEqual(clean_slot(f"가{sneaky}나"), "가 나")

    def test_secrets_stuck_together_without_spaces_are_all_hidden_in_one_call(self):
        key = SAMPLES["Google API 키"]
        token = SAMPLES["GitHub 토큰"]
        for text in (f"{key}secret=hunter2hunter2", f"{token}{key}", f"x{key}y", f"password={key}", f"{key}password=hunter2hunter2{token}"):
            with self.subTest(text=text[:30]):
                masked = mask(text)
                for secret in (key, token, "hunter2hunter2"):
                    self.assertNotIn(secret, masked)
                self.assertEqual(mask(masked), masked)

    def test_a_secret_hidden_behind_another_one_is_found_on_the_second_pass(self):
        text = "=" + SAMPLES["Google API 키"] + "Bearer abcdefghijklmnop0123456789XYZ"        # `Bearer` 앞의 단어 경계는 앞의 키를 가린 뒤에야 생긴다
        once = mask_module._mask_once(text)
        self.assertIn("abcdefghijklmnop0123456789XYZ", once, "한 번으로는 다 못 가린다")
        self.assertEqual(mask(text), "=[가림: Google API 키]Bearer [가림: 토큰]")
        self.assertEqual(mask(mask(text)), mask(text))

    def test_a_long_run_of_token_like_pieces_is_not_quadratic(self):
        for text in ("-eyJaaaaaaaa" * 40000, "eyJ" + "a" * 4000 + "." + "b" * 100, "a-" * 200000, "token" * 60000 + "=", ("a.b-" * 60000)):
            started = time.time()
            mask(text)
            self.assertLess(time.time() - started, 3, text[:20])

    def test_an_enormous_input_is_cut_instead_of_taking_minutes(self):
        masked = mask("가" * (MAX_MASK_INPUT + 5000))
        self.assertLessEqual(len(masked), MAX_MASK_INPUT + 20)
        self.assertTrue(masked.endswith("…(이하 생략)"))
        self.assertEqual(mask("가" * MAX_MASK_INPUT), "가" * MAX_MASK_INPUT, "한도까지는 그대로")
        late = SAMPLES["GitHub 토큰"]
        self.assertNotIn(late, mask("가" * MAX_MASK_INPUT + late), "잘려 나간 뒷부분은 아예 내보내지 않는다")

    def test_the_package_does_not_hide_the_masking_module_behind_its_function(self):
        import inspect
        import chanceblog_desktop.security as security
        self.assertTrue(inspect.ismodule(mask_module))
        self.assertTrue(inspect.ismodule(security.mask), "`security.mask` 는 모듈이어야 한다(함수가 가리면 mock.patch 가 깨진다)")
        self.assertIs(mask_from_package, mask_module.mask)


class RobustnessTest(unittest.TestCase):
    def test_odd_inputs_never_raise(self):
        class Broken:
            def __str__(self):
                raise RuntimeError("표시할 수 없다")

        self.assertEqual(mask(None), "")
        self.assertEqual(mask(123), "123")
        self.assertEqual(mask(b"bytes"), "b'bytes'")
        self.assertEqual(mask(["목록", 1]), "['목록', 1]")
        self.assertEqual(mask(Broken()), "(표시할 수 없는 값)")
        self.assertEqual(safe_detail(None), "")

    def test_a_large_text_is_handled_quickly(self):
        big = ("가나다라 " * 100000) + SAMPLES["GitHub 토큰"] + (" x" * 100000) + " AQ." + "z" * 100000
        started = time.time()
        masked = mask(big)
        self.assertLess(time.time() - started, 5)
        self.assertNotIn(SAMPLES["GitHub 토큰"], masked)
        self.assertNotIn("z" * 100, masked)

    def test_safe_detail_is_one_short_line(self):
        self.assertEqual(safe_detail("앞\n\n  뒤\t끝"), "앞 뒤 끝")
        long = safe_detail("가" * 5000)
        self.assertEqual(len(long), MAX_LOG_CHARS)
        self.assertTrue(long.endswith("…"))
        self.assertEqual(safe_detail("가" * 50, 10), "가" * 9 + "…")
        self.assertNotIn(SAMPLES["Google API 키"], safe_detail(f"줄\n{SAMPLES['Google API 키']}\n끝"))


class LogLineTest(unittest.TestCase):
    def test_a_plain_error_is_just_its_code(self):
        self.assertEqual(AppError("GIT_PUSH_AUTH").log_line(), "GIT_PUSH_AUTH")

    def test_values_detail_and_the_asked_code_are_shown_masked_on_one_line(self):
        secret = SAMPLES["GitHub 토큰"]
        error = AppError("MADE_UP_CODE", {"경로": f"C:\\work\\{secret}", "파일": "a.md"}, detail=f"실패\n세부 {secret} 끝")
        line = error.log_line()
        self.assertNotIn(secret, line)
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith("UNEXPECTED_ERROR | 요청한 코드=MADE_UP_CODE | 값="), line)
        self.assertIn("파일=a.md", line)
        self.assertIn("세부=실패 세부 [가림: GitHub 토큰] 끝", line)

    def test_a_secret_in_the_asked_code_or_a_slot_name_is_masked_too(self):
        secret = SAMPLES["Google API 키"]
        line = AppError(secret, {secret: "값"}).log_line()
        self.assertNotIn(secret, line)

    def test_a_value_cannot_forge_the_columns_of_the_log_line(self):
        error = AppError("FILE_WRITE_FAILED", {"경로": "x | 세부=위조된 내용 | 값=또 위조"}, detail="진짜 | 세부")
        line = error.log_line()
        self.assertEqual(line.count(" | "), 2, "코드 | 값=… | 세부=… 의 칸 구분뿐이다")
        self.assertIn("¦", line)
        self.assertNotIn("\u202e", AppError("X", detail="a\u202eb").log_line())

    def test_the_log_line_still_works_when_the_masking_module_cannot_be_used(self):
        with mock.patch.dict(sys.modules, {"chanceblog_desktop.security.mask": None}):
            line = AppError("GIT_PUSH_AUTH", detail="비밀 메모").log_line()
        self.assertEqual(line.split(" | ")[0], "GIT_PUSH_AUTH")
        self.assertNotIn("비밀 메모", line)

    def test_str_of_an_error_never_shows_the_detail(self):
        error = AppError("FILE_WRITE_FAILED", {"경로": "x"}, detail="내부 메모 " + SAMPLES["GitHub 토큰"])
        self.assertNotIn("내부 메모", str(error))


class GitFailureDetailTest(unittest.TestCase):
    def test_a_token_printed_by_git_in_plain_text_is_masked_in_the_error_detail(self):
        token = SAMPLES["GitHub 토큰"]
        result = gitrepo.GitResult(128, "", f"fatal: bad credentials {token}\nfatal: unable to access 'https://github.com/a/b.git/': The requested URL returned error: 403")
        error = gitrepo._failure(result, "올리기 점검")
        self.assertEqual(error.code, "GIT_PUSH_AUTH")
        self.assertNotIn(token, error.detail)
        self.assertIn("[가림: GitHub 토큰]", error.detail)
        self.assertNotIn(token, error.log_line())

    def test_the_tail_with_the_cause_is_still_kept_and_the_length_limit_still_holds(self):
        result = gitrepo.GitResult(128, "", "x" * 3000 + "Could not resolve host: github.com")
        error = gitrepo._failure(result, "받기")
        self.assertTrue(error.detail.endswith("Could not resolve host: github.com"))
        self.assertLessEqual(len(error.detail), 420)


if __name__ == "__main__":
    unittest.main()
