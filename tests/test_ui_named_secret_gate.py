"""복사 전 관문이 '이름 붙은 값'(`password: …`·`secret=…`·`api_key: …`)을 막는다(앱 2차 감사 AS-S2 권고-1, 결정 D-682) — PySide6 없이 돈다(CI 와 같은 조건).

배경: 관문은 접두사 모양(`AIza…`·`ghp_…`)과 24자 넘는 영숫자 덩어리, 검사기 여섯 유형만 봤다. 그래서 운영자가 메모(계정·비밀번호 줄)를 글에 붙여 넣으면 `password: Hunter2xyz`·`secret=Ab12Cd34` 같은 글이 막힘도 확인창도 없이
클립보드로 갔다(로그에는 가려지는 값이다). 이제 **이름 낱말(password·secret·token·api key …, 한국어 비밀번호·비번 …)에 `:`·`=` 로 붙은 값이 키·비밀번호처럼 생겼으면**(여섯 글자 이상이고 영문자와 숫자가 함께 있음) 막고 수정을 요청한다.
오탐을 줄이는 규칙: 숫자뿐·글자뿐·짧은 값, 설명 문장('비밀번호: 8자 이상'), 코드(`get_token(user1)`·`req.body.password1`·`$TOKEN_1`)와 자리 표시(`<your password>`·`YOUR_API_KEY`)는 막지 않는다.

이 파일이 못박는 것:
  1) 막아야 하는 이름 × 구분 × 값 조합 수백 가지가 모두 막히고, 막은 자리의 미리보기는 값을 한 글자도 되풀이하지 않는다(이름 쪽 앞 글만 보인다).
  2) 막으면 안 되는 설명 문장·코드·자리 표시 수십 가지와 기존 정상 예문(일상 문장·건강 대조·정상 주소·파일 이름·88개 주소)은 하나도 막히지 않는다.
  3) 주소 안의 `?token=…` 은 이 규칙이 아니라 주소 규칙이 본다(옛 판정 그대로) — 이름 없는 글에서는 옛 판정과 한 글자도 다르지 않다(`draft_gate_oracle`).
  4) 막으면 복사 관문이 '막음'(`Gate.blocked`)이고 안내 문구가 '이름: 값' 모양도 알려 준다. 제목·본문·작은 복사(키워드·태그·요약) 모두.
"""
import itertools
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_gate_oracle import old_secret_spots  # noqa: E402
from draft_samples import CONTROL, DAILY, NORMAL_ADDRESSES, NORMAL_FILE_NAMES, NORMAL_MORE, OPERATOR_C, SECRET_ADDRESSES, mixed  # noqa: E402

from chanceblog_desktop.security import shape  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

VALUES = ("CANARY" + "_Hunter2", "CANARY" + "x1", "CANARY" + "a1B2c3D4", "CANARY" + "9zKq7", "Ab12" + "Cd34", "CANARY" + "t0k3n-v4lu3")          # 가짜 값 — 영문자와 숫자가 함께 있고 여섯 글자 이상
NAMES_EN = ("password", "Password", "PASSWORD", "passwd", "secret", "Secret", "client_secret", "token", "Token", "access_token", "refresh-token", "api_key", "API key", "api-key", "apikey", "service key",
            "private_key", "DB_PASSWORD", "MY_SERVICE_TOKEN", "sessionid", "session_id", "credential", "credentials", "secret key", "x_api_key", "passwords")
NAMES_KO = ("비밀번호", "비번", "패스워드", "시크릿", "인증키")
SEPARATORS = (": ", ":", " : ", "=", " = ", ":\t", "：", "＝")
WRAPS = ("{}", "앞 글 {} 뒤 글", "- {}", "\n{}\n", "계정 메모 — {}.")


def blocked(text):
    return bool(rules.secret_spots(text))


class MustBlockTest(unittest.TestCase):
    def test_every_name_separator_value_combination_is_blocked_wherever_it_sits(self):
        count = 0
        for name, separator, value in itertools.product((*NAMES_EN, *NAMES_KO), SEPARATORS, VALUES):
            written = f"{name}{separator}{value}"
            for wrap in WRAPS if (count % 7 == 0) else WRAPS[:1]:                  # 모든 조합에 바탕 글 다섯을 다 곱하면 오래 걸려 일곱 조합마다 다섯을 모두 쓴다
                text = wrap.format(written)
                with self.subTest(text=text[:40]):
                    spots = rules.secret_spots(text)
                    self.assertTrue(spots, text)
                    self.assertTrue(any(value in text[start:end] or text[start:end] in value for start, end in spots), "걸린 자리가 값을 덮는다")
                    for place in rules.secret_places(("본문", text)):
                        self.assertNotIn(value, place)
                        self.assertNotIn(value[:4], place, "값의 앞 네 글자도 미리보기에 되풀이하지 않는다")
                        self.assertIn("[가림", place, "값은 가림 표시로 바뀐다(이름 붙은 값 규칙의 `[가림]` 이거나 옛 규칙이 이미 잡던 긴 덩어리의 `[가림: 값]`)")
            count += 1
        self.assertGreaterEqual(count, 31 * 8 * 6)

    def test_quoted_json_env_and_attached_forms_are_blocked(self):
        value = "CANARY" + "a1B2c3D4"
        for text in (f'password: "{value}"', f"password: '{value}'", "{" + '"password": "' + value + '"' + "}", "{" + '"api_key":"' + value + '","other":1' + "}", f"export DB_PASSWORD={value}", f"secret = '{value}'", f"Password:{value}",
                     f"비밀번호: {value}입니다", f"비밀번호는 아래와 같아요.\n비밀번호: {value}\n끝", f"아이디: abc / 비밀번호: {value}", f"api_key: {value}.", f"token: {value}!", f"TOKEN={value};", f"secret=“{value}”",
                     f"curl -H 'x-api-key: {value}'", f"sessionid={value}; path=/"):
            with self.subTest(text=text[:40]):
                self.assertTrue(blocked(text), text)

    def test_the_audit_examples_are_blocked(self):
        """감사 재현: `password: Hunter2xyz`·`secret=Ab12Cd34` 같은 글이 막힘도 확인창도 없이 갔다."""
        for text in ("password: " + "CANARY" + "_Hunter2", "client_secret=" + "CANARY" + "x1", "password: Hunter2xyz", "secret=Ab12Cd34", "api_key: " + mixed("audit", 24)):
            with self.subTest(text=text[:30]):
                self.assertTrue(rules.has_secret(text))
                self.assertTrue(rules.secret_places(("본문", text)))

    def test_it_is_a_block_at_the_copy_gate_for_the_body_the_title_and_the_small_copies(self):
        value = "CANARY" + "a1B2c3D4"
        memo = f"안내 글입니다.\n아이디: abc\n비밀번호: {value}\n끝."
        for title, body in (("제목", memo), (f"password: {value}", "정상 본문"), ("제목", "정상 본문 secret=" + value)):
            with self.subTest(title=title[:10], body=body[:10]):
                inspection = rules.inspect_text(title, body)
                self.assertTrue(inspection.secret)
                self.assertTrue(inspection.places)
                gate = rules.gate_for("body", inspection, (), False, {})
                self.assertTrue(gate.blocked)
                self.assertEqual([kind for kind, _places in gate.blocks], ["keyshape"])
        for words in (f"api_key: {value}", f"token={value}"):
            self.assertTrue(rules.has_secret(words), "키워드·태그·요약의 작은 복사도 같은 관문이다")

    def test_the_block_message_also_tells_about_name_and_value_text(self):
        message = T["drf_secret_body"]
        self.assertTrue(message.startswith("키나 토큰처럼 보이는 글이 들어 있어서 복사하지 않았어요"), "기존 시험이 못박은 앞부분은 그대로다")
        self.assertIn("비밀번호", message)
        self.assertIn("값", message)
        self.assertNotRegex(message, r"password|secret|token|[A-Za-z_]{4,}", "쉬운 말뿐이다")


class MustNotBlockTest(unittest.TestCase):
    PROSE = (
        "Password: use at least 8 characters", "password: strong", "Password rules: 8+ characters", "token: 123456", "token: 2026-11-24", "secret: The Garden", "Secret: ingredients", "api_key=YOUR_API_KEY",
        "api_key=<your key>", "password=<your password>", "password: ********", "password = input()", "token = get_token(user1)", "secret_key = os.environ['SECRET_KEY']", "Tokens: 1, 2 and 3", "key: value", "Key: ABC",
        "passwords: abc", "secret: s3", "password: 12345678", "client_secret=XXXXXXXX", "PASSWORD=xxxxxxxx", "token=$TOKEN_1", "token=${TOKEN_1}", "const password = req.body.password1;", "password = hash_password(password1)",
        "secret = getSecret(2)", "session: abc123 ok", "Secret santa: Alice1234", "tokenization: abc123def", "secretary: Ab12Cd34", "monkey: Ab12Cd34", "keyword: abc123xyz", "password:", "password: ", "token=",
        "비밀번호: 8자 이상", "비밀번호는 8자 이상으로 만드세요", "비밀번호: 영문, 숫자, 특수문자 포함", "비번 설정: 쉬운 것은 피하세요", "비밀번호: 1234", "시크릿 모드: 켜기", "시크릿: 비밀 레시피", "패스워드 관리자: 추천 3가지",
        "인증키: 발급받는 방법", "토큰: ETH", "비밀번호 찾기: 이메일로 받기", "암호: 1234", "password policy: at least 1 number and 1 symbol",
    )

    def test_explaining_sentences_code_and_placeholders_are_not_blocked(self):
        for text in self.PROSE:
            for wrap in ("{}", "앞 글 {} 뒤 글", "- {}", "\n{}\n"):
                written = wrap.format(text)
                with self.subTest(text=written[:50]):
                    self.assertFalse(blocked(written), written)

    def test_a_strong_looking_example_value_is_blocked_on_purpose(self):
        """안전한 기본값 — 값이 비밀번호처럼 생겼으면 예시여도 막는다(오탐은 '수정 요청' 쪽, 위임 규칙). 안내 문구가 값을 지우거나 문장으로 바꾸라고 알려 준다."""
        self.assertTrue(blocked("Password: Strong1 (example)"))
        self.assertTrue(blocked("예를 들어 password=abc12345 처럼 쓰면 안 돼요"))

    def test_none_of_the_existing_normal_samples_is_blocked(self):
        plain, addresses = (*DAILY, *CONTROL, *OPERATOR_C), (*NORMAL_ADDRESSES, *NORMAL_FILE_NAMES, *NORMAL_MORE)
        self.assertGreaterEqual(len(plain) + len(addresses), 200)
        for sample in (*plain, *addresses):
            for wrap in ("{}", "참고한 곳은 {} 입니다.", "앞 글\n{}\n뒤 글"):
                written = wrap.format(sample)
                with self.subTest(sample=written[:40]):
                    if sample in plain:
                        self.assertEqual(shape.named_secret_spans(written), (), written)
                    self.assertEqual(rules.secret_spots(written), old_secret_spots(written), "이름 붙은 값이 없는 글의 판정은 옛 판정과 같다")

    def test_a_named_argument_inside_an_address_is_left_to_the_address_rules(self):
        for address in ("https://example.com/p?token=ab12cd", "https://example.com/p?token=abc123XYZ&x=1", "https://example.com/p?secret=a1b2c3d4", "참고 https://example.com/login?password=abc123xyz 입니다",
                        "www.example.com/a?api_key=ab12cd34", "example.com/a?token=ab12cd34", "https://example.com/a/password=abc123xyz/b", "https://example.com/x#access_token=ab12cd34ef"):
            with self.subTest(address=address[:40]):
                self.assertEqual(rules.secret_spots(address), old_secret_spots(address), "주소 안의 짧은 인자는 옛 판정 그대로(알려진 한계 — D-312)")

    def test_the_known_limits_stay_open_and_are_written_down(self):
        """값이 숫자뿐이거나 글자뿐이거나 여섯 글자 미만이면 막지 않는다 — 막으면 '비밀번호: 1234' 같은 설명이 모두 잠긴다. SECURITY.md 의 한계 절에 적혀 있다."""
        for text in ("password: 1234567890", "secret: abcdefghijkl", "token: ab12", "비밀번호: 12345678"):
            with self.subTest(text=text):
                self.assertFalse(blocked(text))
        security = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
        for word in ("이름 붙은 값", "숫자뿐", "여섯 글자"):
            self.assertIn(word, security)


class NamedSpansTest(unittest.TestCase):
    """`shape.named_secret_spans` — 이름 붙은 값의 자리(값 부분)를 돌려준다. 값은 돌려주지 않는다."""

    def test_the_span_is_the_value_part_including_quotes(self):
        text = '앞 password: "CANARYa1B2c3D4" 뒤'
        (start, end), = shape.named_secret_spans(text)
        self.assertEqual(text[start:end], '"CANARYa1B2c3D4"')
        text = "x token=CANARYx1y2z3, y"
        (start, end), = shape.named_secret_spans(text)
        self.assertEqual(text[start:end], "CANARYx1y2z3")

    def test_several_values_are_found_in_order_and_it_never_raises(self):
        text = "password: CANARYa1b2c3 and secret=CANARYd4e5f6 and token: nothing"
        spans = shape.named_secret_spans(text)
        self.assertEqual([text[start:end] for start, end in spans], ["CANARYa1b2c3", "CANARYd4e5f6"])
        for odd in (None, 5, b"password: abc123xyz", ["password: abc123xyz"], "", "x" * 10, "password" * 1000):
            self.assertEqual(shape.named_secret_spans(odd), ())
        self.assertEqual(shape.named_secret_spans("password: abc123xyz" + "가" * shape.MAX_SCAN_CHARS), (), "너무 긴 글은 이 규칙이 아니라 길이 한도가 막는다")

    def test_value_classes(self):
        keylike = shape.is_secret_like_value
        for value in ("Hunter2xyz", "Ab12Cd34", "abc123", "CANARY_Hunter2", "P@ssw0rd!", '"quoted1Value"', "x9y8z7w6", "sk_test_1234567890abcdef", "ya29.A0AfH6SMBx1"):
            self.assertTrue(keylike(value), value)
        for value in ("12345678", "abcdefgh", "ab12", "", "********", "<your password>", "YOUR_API_KEY", "$TOKEN_1", "req.body.password1", "get_token(user1)", "한글만있는값입니다", "a b c 1 2 3", "8자", "1,2,3"):
            self.assertFalse(keylike(value), value)

    def test_a_named_argument_of_an_address_is_not_a_named_value_here_either(self):
        """주소 인자(`?이름=…`·`&이름=…`·`;이름=…`·`#이름=…`)는 주소 규칙의 몫이다 — 이름 앞이 `? & ; #` 이면(앞에 이름 글자가 붙어 있어도) 이 규칙은 건너뛴다."""
        for text in ("?token=ab12cd34", "x?x_token=ab12cd34", "a&secret=Ab12Cd34", "a;api_key=Ab12Cd34", "#access_token=ab12cd34ef", "u?v=1&client_secret=Ab12Cd34", "?api.key=Ab12Cd34"):
            with self.subTest(text=text):
                self.assertEqual(shape.named_secret_spans(text), ())
        for text in ("x token=ab12cd34", "x?\ntoken=ab12cd34", "path/token=ab12cd34"):
            with self.subTest(text=text):
                self.assertTrue(shape.named_secret_spans(text), "이름 앞이 공백·줄바꿈·경로면 주소 인자가 아니다")

    def test_it_is_fast_on_pathological_texts(self):
        for label, text in (("이름만 되풀이", "password " * 6000), ("이름과 구분만", "password: " * 6000), ("닫히지 않은 따옴표", 'password: "' * 6000), ("값이 긴 덩어리", "secret=" + "a1" * 20000),
                            ("이름이 붙어 있음", "secretsecretsecret" * 3000), ("줄바꿈 가득", "token:\n" * 9000), ("정상 값 되풀이", "token=CANARYa1b2c3 " * 3000)):
            started = time.perf_counter()
            shape.named_secret_spans(text[:shape.MAX_SCAN_CHARS])
            self.assertLess(time.perf_counter() - started, 2.0, label)

    def test_ten_times_the_length_costs_less_than_twenty_times_the_time(self):
        def best(text):
            spent = []
            for _ in range(3):
                started = time.perf_counter()
                shape.named_secret_spans(text)
                spent.append(time.perf_counter() - started)
            return min(spent)

        for label, make in (("정상 값 되풀이", lambda n: "token=CANARYa1b2c3 " * (n // 19)), ("이름과 구분만", lambda n: "password: " * (n // 10)), ("닫히지 않은 따옴표", lambda n: 'secret="' * (n // 8))):
            small, large = best(make(3000)), best(make(30000))
            self.assertLess(large / max(small, 0.0005), 20, f"{label}: {small:.4f}초 → {large:.4f}초")


class NeighborPreviewTest(unittest.TestCase):
    """감사 참고-12: 미리보기의 앞 글(14자)이 바로 앞의 **다른 비밀의 꼬리**를 그대로 보였다. 짧은 이름 붙은 값이 이웃하면 값 전체가 보일 수 있어서(이름 붙은 값을 막기 시작하며 더 흔해진다) 앞 글 안의 걸린 자리는 `[가림]` 으로 바꾼다."""
    FIRST, SECOND = "CANARY" + "a1B2c3D4", "CANARY" + "x9y8z7W6"

    def test_a_secret_right_before_another_is_never_repeated_in_the_second_preview(self):
        for text in (f"비밀번호: {self.FIRST} / 인증키: {self.SECOND}", f"password: {self.FIRST} token: {self.SECOND}", f"secret={self.FIRST} api_key={self.SECOND}", f"비번 password:{self.FIRST}, secret:{self.SECOND}"):
            with self.subTest(text=text[:40]):
                places = rules.secret_places(("본문", text))
                self.assertEqual(len(places), 2)
                for place in places:
                    for piece in (self.FIRST, self.SECOND, self.FIRST[:6], self.SECOND[:6], self.FIRST[-6:], self.SECOND[-6:]):
                        self.assertNotIn(piece, place, "이웃한 비밀의 어느 부분도 미리보기에 되풀이하지 않는다")
                self.assertGreaterEqual(places[1].count(T["drf_spot_hidden"]), 2, "앞 비밀 자리와 이 자리 둘 다 표시로 바뀐다")

    def test_key_shapes_in_a_row_hide_the_tail_of_the_previous_one(self):
        """감사 재현(참고-12): `gap=' '` 에서 첫 비밀의 꼬리 12자가 그대로 보였다."""
        key = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
        for gap in (" ", "  ", "\n", " / ", ", ", ""):
            text = key + gap + key.replace("ABCDEF", "UVWXYZ")
            with self.subTest(gap=repr(gap)):
                for place in rules.secret_places(("본문", text)):
                    self.assertNotIn(key[-12:], place)
                    self.assertNotIn("GHIJKLMNOP", place)

    def test_a_single_spot_and_far_apart_spots_are_unchanged(self):
        """이웃이 없으면 옛 미리보기와 한 글자도 다르지 않다."""
        from draft_gate_oracle import old_secret_places
        key = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
        far = key + "  " + "가나다라마바사아자차카타파하 " * 4 + key.replace("ABCDEF", "UVWXYZ")
        for text in ("앞 글 " + key + " 뒤 글", key, far, "https://example.com/?k=" + key):
            with self.subTest(text=text[:20]):
                self.assertEqual(rules.secret_places(("본문", text)), old_secret_places(("본문", text)))

    def test_hidden_neighbors_cost_nothing_for_many_spots(self):
        text = ("password: " + self.FIRST + " ") * 3000
        started = time.perf_counter()
        places = rules.secret_places(("본문", text))
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertLessEqual(len(places), rules.SPOT_LIMIT)
        self.assertEqual(len(rules.secret_spots(text)), 3000)


class PublishGateTest(unittest.TestCase):
    """올리기 직전 관문(`service/gate.py`)도 같은 검사를 한다 — 실제 Chance 글 두 편과 기존 통과 글은 그대로 통과하고, 이름 붙은 값이 든 글만 `[NAMED_SECRET]` 로 막힌다."""

    @staticmethod
    def post_text(body, *, lang="ko", title="제목"):
        import service_support as ss
        from chanceblog_desktop.content.model import ContentProject
        from chanceblog_desktop.render.pages import render_pages_post
        project = ContentProject.new(title, body, now="2026-11-02T00:00:00Z")
        params = ss.KO_PARAMS if lang == "ko" else ss.EN_PARAMS
        return render_pages_post(project, category=params.category, lang=lang, image_url=params.image_url, tags=params.tags, now=ss.NOW).text

    def test_a_named_value_in_the_body_stops_the_gate_and_the_clean_post_passes(self):
        import service_support as ss
        from chanceblog_desktop.service import gate
        nl = chr(10)
        base = ss.ko_text()
        clean = self.post_text(base)
        self.assertTrue(gate.run_gates(clean).ok, gate.run_gates(clean).reasons)
        value = "CANARY" + "a1B2c3D4"
        for line in (f"비밀번호: {value}", f"password: {value}", f"api_key={value}", f"export DB_PASSWORD={value}"):
            with self.subTest(line=line[:20]):
                report = gate.run_gates(self.post_text(base + nl + nl + line + nl))
                self.assertFalse(report.ok)
                self.assertIn("NAMED_SECRET", report.codes())
                self.assertNotIn(value, " ".join(report.reasons), "이유에는 값이 들어가지 않는다")
        explained = self.post_text(base + nl + nl + "비밀번호: 8자 이상으로 만드세요" + nl + nl + "password: use at least 8 characters" + nl)
        self.assertTrue(gate.run_gates(explained).ok, "설명 문장은 막지 않는다")

    def test_the_two_real_posts_still_pass(self):
        from chanceblog_desktop.service import gate
        fixtures = ROOT / "tests" / "fixtures"
        for name in ("chance_post_ko.md", "chance_post_en.md"):
            with self.subTest(post=name):
                report = gate.run_gates((fixtures / name).read_text(encoding="utf-8"))
                self.assertTrue(report.ok, report.reasons)


class NoRegressionTest(unittest.TestCase):
    """이름 낱말이 든 글에서도 옛 판정을 **포함**한다 — 더 막을 뿐 덜 막지 않는다."""

    def test_the_new_spots_always_contain_the_old_ones_as_covered_text(self):
        samples = ["참고 https://example.com/?ref=" + "AK" + "IA" + "ABCDEFGHIJKLMNOP", "앞 글 " + "AK" + "IA" + "ABCDEFGHIJKLMNOP" + " 뒤 글 password: CANARYa1B2c3D4", "password: " + "AK" + "IA" + "ABCDEFGHIJKLMNOP",
                   "secret=" + "gh" + "p_" + mixed("nr", 36), "token: abc123xyz\n" + "AK" + "IA" + "ABCDEFGHIJKLMNOP", "-----BEGIN " + "PRIVATE KEY-----\npassword: CANARYa1B2c3D4\n-----END " + "PRIVATE KEY-----"]
        for text in samples:
            old = old_secret_spots(text)
            new = rules.secret_spots(text)
            with self.subTest(text=text[:30]):
                self.assertTrue(all((start, end) in new or any(start < other_end and other_start < end for other_start, other_end in new) for start, end in old), (old, new))


if __name__ == "__main__":
    unittest.main()
